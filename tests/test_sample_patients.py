"""Tests for the 100 synthetic demo patients + picker endpoints."""
import sample_patients as sp

_FORM_FIELDS = [
    "patient_name", "age", "gender", "mrn", "admission_date", "expected_discharge_date",
    "attending_physician", "primary_diagnosis", "secondary_diagnoses",
    "additional_clinical_notes", "primary_insurance", "secondary_insurance",
    "medicare_part_a", "snf_days_used", "admission_medications", "inpatient_medications",
    "discharge_medications", "pt_evaluation", "ot_evaluation", "st_evaluation",
    "living_situation", "caregiver", "primary_language", "transportation",
    "housing_type", "bedroom_location", "patient_family_preference",
    "physician_goals", "additional_notes",
]


class TestSamplePatientsModule:
    def test_exactly_100_with_unique_ids(self):
        assert len(sp.SAMPLE_PATIENTS) == 100
        ids = [p["id"] for p in sp.SAMPLE_PATIENTS]
        assert len(set(ids)) == 100
        assert ids[0] == "001" and ids[-1] == "100"

    def test_every_patient_has_all_form_fields_populated(self):
        for p in sp.SAMPLE_PATIENTS:
            for f in _FORM_FIELDS:
                assert f in p, f"{p['id']} missing {f}"
                assert str(p[f]).strip(), f"{p['id']} empty {f}"

    def test_data_richness(self):
        # Each patient should have multiple secondary dx + multiple discharge meds.
        for p in sp.SAMPLE_PATIENTS:
            assert len(p["secondary_diagnoses"].splitlines()) >= 3
            assert len(p["discharge_medications"].splitlines()) >= 3

    def test_list_and_lookup(self):
        lst = sp.list_sample_patients()
        assert len(lst) == 100
        assert all("label" in x and "id" in x for x in lst)
        one = sp.get_sample_patient("042")
        assert one and one["id"] == "042"
        assert sp.get_sample_patient("42")["id"] == "042"  # zero-pads
        assert sp.get_sample_patient("999") is None


class TestRichRecords:
    def test_exactly_100_rich_records(self):
        assert len(sp.RICH_PATIENTS) == 100
        ids = [r["id"] for r in sp.RICH_PATIENTS]
        assert len(set(ids)) == 100

    def test_every_record_is_synthetic_with_disclaimer(self):
        for r in sp.RICH_PATIENTS:
            assert r["synthetic"] is True
            assert r["disclaimer"]
            # No real-looking PHI prefixes — MRN/member id must use SYN-.
            assert r["demographics"]["mrn"].startswith("SYN-")
            assert r["payer"]["member_id"].startswith("SYN-")

    def test_records_have_all_nested_sections(self):
        sections = [
            "demographics", "encounter", "problem_list", "medications", "allergies",
            "vitals", "labs", "functional_status", "sdoh", "payer", "discharge",
            "risk", "tcm", "preferences",
        ]
        for r in sp.RICH_PATIENTS:
            for s in sections:
                assert s in r, f"{r['id']} missing section {s}"
            # medication sub-lists + reconciliation
            meds = r["medications"]
            assert meds["discharge"] and meds["reconciliation"]
            assert r["labs"]
            assert any(p.get("primary") for p in r["problem_list"])

    def test_all_records_are_coherent(self):
        problems = []
        for r in sp.RICH_PATIENTS:
            problems += sp.validate_coherence(r)
        assert problems == [], f"coherence issues: {problems[:10]}"

    def test_validator_catches_injected_contradictions(self):
        import copy
        r = copy.deepcopy(sp.RICH_PATIENTS[0])
        # Inject an allergy that is also a discharge med.
        r["medications"]["discharge"] = ["Penicillin 500 mg PO BID"]
        r["allergies"] = [{"substance": "Penicillin", "reaction": "hives", "severity": "severe"}]
        assert any("allergy" in i for i in sp.validate_coherence(r))

    def test_get_sample_record(self):
        rec = sp.get_sample_record("007")
        assert rec and rec["id"] == "007"
        assert sp.get_sample_record("7")["id"] == "007"  # zero-pads
        assert sp.get_sample_record("999") is None

    def test_list_includes_picker_fields(self):
        for x in sp.list_sample_patients():
            for f in ("dx_short", "disposition", "payer_short", "complexity", "language"):
                assert x[f], f"{x['id']} missing {f}"


class TestSamplePatientEndpoints:
    async def test_list_requires_auth(self, client):
        r = await client.get("/api/sample-patients")
        assert r.status_code in (401, 403)

    async def test_list_returns_100(self, authed_client):
        r = await authed_client.get("/api/sample-patients")
        assert r.status_code == 200
        assert len(r.json()["patients"]) == 100

    async def test_get_by_id(self, authed_client):
        r = await authed_client.get("/api/sample-patient/007")
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == "007"
        assert d["primary_diagnosis"]

    async def test_get_missing_404(self, authed_client):
        r = await authed_client.get("/api/sample-patient/999")
        assert r.status_code == 404
