"""FHIR R4 normalizer tests — patient-bundle normalization & agent-data mapping.

Covers the spec section 17 / section 22 coverage gap: `fhir/*` is excluded from
the coverage config and the normalizers (the riskiest "never throw" code) had no
dedicated automated tests. Normalizers must be defensive: a single malformed
resource may never break plan generation.
"""
import pytest

from fhir import normalizers as N
from fhir.schemas import FetchWarning, PatientBundle


# ── normalize_patient ────────────────────────────────────────────────────────

class TestNormalizePatient:
    def test_full_patient(self):
        rec = N.normalize_patient({
            "resourceType": "Patient", "id": "p1", "gender": "female",
            "birthDate": "1950-03-15",
            "name": [{"use": "official", "given": ["Jane", "A"], "family": "Doe"}],
            "identifier": [{"type": {"coding": [{"code": "MR"}]}, "value": "MRN-123"}],
            "telecom": [{"system": "phone", "value": "555-1212"}],
            "communication": [{"preferred": True, "language": {"text": "Spanish"}}],
            "address": [{"use": "home", "line": ["1 Main St"], "city": "Sac",
                         "state": "CA", "postalCode": "95762"}],
        })
        assert rec.first_name == "Jane A"
        assert rec.last_name == "Doe"
        assert rec.mrn == "MRN-123"
        assert rec.preferred_language == "Spanish"
        assert rec.phone == "555-1212"
        assert rec.gender == "female"
        assert "95762" in rec.address

    def test_wrong_resource_type_returns_none(self):
        assert N.normalize_patient({"resourceType": "Observation"}) is None
        assert N.normalize_patient(None) is None

    def test_mrn_falls_back_to_first_identifier(self):
        rec = N.normalize_patient({
            "resourceType": "Patient", "id": "p2",
            "identifier": [{"value": "ANY-1"}],
        })
        assert rec.mrn == "ANY-1"

    def test_language_defaults_to_en(self):
        rec = N.normalize_patient({"resourceType": "Patient", "id": "p3"})
        assert rec.preferred_language == "en"

    def test_missing_name_does_not_raise(self):
        rec = N.normalize_patient({"resourceType": "Patient", "id": "p4"})
        assert rec.first_name == ""
        assert rec.last_name == ""


# ── normalize_conditions ─────────────────────────────────────────────────────

class TestNormalizeConditions:
    def test_icd10_and_category(self):
        conds = N.normalize_conditions({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Condition", "id": "c1",
                          "code": {"coding": [{
                              "system": "http://hl7.org/fhir/sid/icd-10-cm",
                              "code": "I50.9", "display": "CHF"}]},
                          "category": [{"coding": [{"code": "encounter-diagnosis"}]}]}},
        ]})
        assert len(conds) == 1
        assert conds[0].icd10_code == "I50.9"
        assert conds[0].display_name == "CHF"
        assert conds[0].category == "encounter-diagnosis"

    def test_text_only_condition_has_empty_icd(self):
        conds = N.normalize_conditions({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Condition", "id": "c2",
                          "code": {"text": "Diabetes"}}},
        ]})
        assert conds[0].icd10_code == ""
        assert conds[0].display_name == "Diabetes"

    def test_condition_without_display_is_skipped(self):
        conds = N.normalize_conditions({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Condition", "id": "c3", "code": {}}},
        ]})
        assert conds == []

    def test_non_bundle_returns_empty(self):
        assert N.normalize_conditions(None) == []
        assert N.normalize_conditions({"resourceType": "Patient"}) == []

    def test_non_condition_entries_ignored(self):
        conds = N.normalize_conditions({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Observation", "id": "o1"}},
        ]})
        assert conds == []


# ── normalize_medications ────────────────────────────────────────────────────

class TestNormalizeMedications:
    def test_codeable_concept_with_rxnorm_and_dosage(self):
        meds = N.normalize_medications({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "MedicationRequest", "id": "m1",
                          "medicationCodeableConcept": {"coding": [{
                              "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                              "code": "29046", "display": "Lisinopril 10 MG"}]},
                          "dosageInstruction": [{"text": "10 mg PO daily"}],
                          "authoredOn": "2026-01-05"}},
        ]})
        assert len(meds) == 1
        assert meds[0].name == "Lisinopril 10 MG"
        assert meds[0].rxnorm_code == "29046"
        assert meds[0].dosage_text == "10 mg PO daily"
        assert meds[0].authored_on == "2026-01-05"

    def test_structured_dose_quantity_when_no_text(self):
        meds = N.normalize_medications({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "MedicationRequest", "id": "m2",
                          "medicationCodeableConcept": {"text": "Metoprolol"},
                          "dosageInstruction": [{"doseAndRate": [{
                              "doseQuantity": {"value": 25, "unit": "mg"}}]}]}},
        ]})
        assert meds[0].dosage_text == "25 mg"

    def test_medication_reference_fallback_name(self):
        meds = N.normalize_medications({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "MedicationRequest", "id": "m3",
                          "medicationReference": {"display": "Warfarin 5mg"}}},
        ]})
        assert meds[0].name == "Warfarin 5mg"


# ── normalize_allergies ──────────────────────────────────────────────────────

class TestNormalizeAllergies:
    def test_allergy_with_reaction(self):
        allergies = N.normalize_allergies({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "AllergyIntolerance", "id": "a1",
                          "code": {"text": "Penicillin"},
                          "criticality": "high",
                          "reaction": [{"manifestation": [{"text": "Hives"}]}]}},
        ]})
        assert allergies[0].substance == "Penicillin"
        assert allergies[0].criticality == "high"
        assert allergies[0].reaction == "Hives"

    def test_allergy_without_substance_skipped(self):
        allergies = N.normalize_allergies({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "AllergyIntolerance", "id": "a2", "code": {}}},
        ]})
        assert allergies == []

    def test_criticality_defaults(self):
        allergies = N.normalize_allergies({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "AllergyIntolerance", "id": "a3",
                          "code": {"text": "Latex"}}},
        ]})
        assert allergies[0].criticality == "unable-to-assess"
        assert allergies[0].type == "allergy"


# ── normalize_appointments / care_team / documents ───────────────────────────

class TestOtherNormalizers:
    def test_appointment_practitioner_and_location(self):
        appts = N.normalize_appointments({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Appointment", "id": "ap1",
                          "status": "booked", "start": "2026-02-01T10:00:00Z",
                          "serviceType": [{"text": "Cardiology"}],
                          "participant": [
                              {"actor": {"reference": "Practitioner/1",
                                         "display": "Dr. Heart"}},
                              {"actor": {"reference": "Location/5",
                                         "display": "Clinic A"}}]}},
        ]})
        assert appts[0].service_type == "Cardiology"
        assert appts[0].practitioners == ["Dr. Heart"]
        assert appts[0].location == "Clinic A"
        assert appts[0].status == "booked"

    def test_care_team_dedup(self):
        team = N.normalize_care_team({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "CareTeam", "id": "ct1", "participant": [
                {"member": {"reference": "Practitioner/1", "display": "Dr. A"},
                 "role": [{"text": "Cardiologist"}]},
                {"member": {"reference": "Practitioner/1", "display": "Dr. A"}},
            ]}},
        ]})
        assert len(team) == 1
        assert team[0].name == "Dr. A"
        assert team[0].role == "Cardiologist"

    def test_document_normalization(self):
        docs = N.normalize_documents({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "DocumentReference", "id": "d1",
                          "type": {"text": "Discharge Summary"},
                          "date": "2026-01-10",
                          "author": [{"display": "Dr. B"}],
                          "content": [{"attachment": {"url": "http://x/doc"}}]}},
        ]})
        assert docs[0].title == "Discharge Summary"
        assert docs[0].author == "Dr. B"
        assert docs[0].content_url == "http://x/doc"


# ── fhir_bundle_to_agent_data ────────────────────────────────────────────────

class TestBundleToAgentData:
    def _bundle(self, **kw):
        defaults = dict(
            patient=None, conditions=[], medications=[], allergies=[],
            appointments=[], care_team=[], documents=[], fetch_warnings=[],
            fhir_base="http://x", ehr="epic",
        )
        defaults.update(kw)
        return PatientBundle(**defaults)

    def test_demographics_and_age(self):
        pat = N.normalize_patient({
            "resourceType": "Patient", "id": "p1", "gender": "male",
            "birthDate": "1960-01-01",
            "name": [{"given": ["John"], "family": "Smith"}],
            "identifier": [{"type": {"coding": [{"code": "MR"}]}, "value": "M-9"}],
        })
        data = N.fhir_bundle_to_agent_data(self._bundle(patient=pat))
        assert data["patient_name"] == "John Smith"
        assert data["mrn"] == "M-9"
        assert data["gender"] == "male"
        assert int(data["age"]) >= 60

    def test_none_patient_does_not_raise(self):
        data = N.fhir_bundle_to_agent_data(self._bundle())
        assert data["patient_name"] == ""
        assert data["primary_language"] == "English"

    def test_encounter_diagnosis_prioritized_as_primary(self):
        conds = N.normalize_conditions({"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Condition", "id": "c1",
                          "code": {"text": "Diabetes"},
                          "category": [{"coding": [{"code": "problem-list-item"}]}]}},
            {"resource": {"resourceType": "Condition", "id": "c2",
                          "code": {"text": "CHF"},
                          "category": [{"coding": [{"code": "encounter-diagnosis"}]}]}},
        ]})
        data = N.fhir_bundle_to_agent_data(self._bundle(conditions=conds))
        # Encounter diagnosis (CHF) must come first regardless of bundle order.
        assert data["primary_diagnosis"].startswith("CHF")
        assert "Diabetes" in data["secondary_diagnoses"]

    def test_fetch_warnings_surfaced_in_notes(self):
        data = N.fhir_bundle_to_agent_data(
            self._bundle(fetch_warnings=[FetchWarning("Medication", "timeout")]))
        assert "DATA FETCH WARNINGS" in data["additional_clinical_notes"]
        assert "Medication" in data["additional_clinical_notes"]

    def test_import_provenance_note(self):
        data = N.fhir_bundle_to_agent_data(self._bundle())
        assert "EPIC" in data["additional_notes"]
