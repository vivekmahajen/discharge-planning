"""FHIR R4 resource normalizers.

Each normalize_* function accepts raw FHIR JSON and returns the internal schema.
All functions are safe — they never raise; missing/unexpected fields return None
or an empty list so that a single malformed resource never breaks plan generation.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from .schemas import (
    Allergy,
    AppointmentRecord,
    CareTeamMember,
    Condition,
    DocumentRecord,
    FetchWarning,
    Medication,
    PatientBundle,
    PatientRecord,
)

logger = logging.getLogger(__name__)


# ── FHIR structure helpers ────────────────────────────────────────────────────

def _entries(bundle: Optional[dict]) -> list[dict]:
    """Extract resource objects from a FHIR Bundle."""
    if not bundle or bundle.get("resourceType") != "Bundle":
        return []
    return [
        e["resource"]
        for e in bundle.get("entry", [])
        if isinstance(e, dict) and isinstance(e.get("resource"), dict)
    ]


def _codings(concept: Optional[dict]) -> list[dict]:
    if not concept:
        return []
    return [c for c in concept.get("coding", []) if isinstance(c, dict)]


def _coding_by_system(codings: list[dict], *system_prefixes: str) -> Optional[dict]:
    """Return the first coding whose system starts with any of the given prefixes."""
    for prefix in system_prefixes:
        for c in codings:
            if c.get("system", "").startswith(prefix):
                return c
    return codings[0] if codings else None


def _text_or_display(concept: Optional[dict], *system_prefixes: str) -> str:
    """Resolve CodeableConcept to display text, preferring .text over coding.display."""
    if not concept:
        return ""
    if concept.get("text"):
        return concept["text"]
    codings = _codings(concept)
    c = _coding_by_system(codings, *system_prefixes) or (codings[0] if codings else None)
    if c:
        return c.get("display") or c.get("code", "")
    return ""


def _safe(fn, *args, **kwargs):
    """Call fn and return None on any exception — used to guard optional field extraction."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


# ── Patient ───────────────────────────────────────────────────────────────────

def normalize_patient(resource: Optional[dict]) -> Optional[PatientRecord]:
    if not resource or resource.get("resourceType") != "Patient":
        return None
    try:
        # Name
        names = resource.get("name", [])
        official = next(
            (n for n in names if n.get("use") == "official"),
            names[0] if names else {},
        )
        first_name = " ".join(official.get("given") or [])
        last_name = official.get("family") or ""

        # MRN — look for type.coding.code == 'MR' or type.text containing 'mrn'
        identifiers = resource.get("identifier", [])
        mrn = ""
        for ident in identifiers:
            type_concept = ident.get("type", {})
            type_text = type_concept.get("text", "").lower()
            type_codes = [c.get("code", "").lower() for c in _codings(type_concept)]
            if "mr" in type_codes or "mrn" in type_text:
                mrn = ident.get("value", "")
                break
        if not mrn and identifiers:
            mrn = identifiers[0].get("value", "")

        # Preferred language
        communications = resource.get("communication", [])
        pref_comm = next(
            (c for c in communications if c.get("preferred")),
            communications[0] if communications else {},
        )
        lang_concept = pref_comm.get("language", {})
        lang_codings = _codings(lang_concept)
        preferred_language = (
            lang_concept.get("text")
            or (lang_codings[0].get("display") or lang_codings[0].get("code", "en") if lang_codings else "en")
        )

        # Phone
        telecoms = resource.get("telecom", [])
        phone = next(
            (t.get("value", "") for t in telecoms if t.get("system") == "phone"), ""
        )

        # Address
        addresses = resource.get("address", [])
        home_addr = next(
            (a for a in addresses if a.get("use") == "home"),
            addresses[0] if addresses else {},
        )
        addr_parts = [
            " ".join(home_addr.get("line") or []),
            home_addr.get("city", ""),
            home_addr.get("state", ""),
            home_addr.get("postalCode", ""),
        ]
        address = ", ".join(p for p in addr_parts if p)

        return PatientRecord(
            id=resource.get("id", ""),
            mrn=mrn,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=resource.get("birthDate", ""),
            gender=resource.get("gender", ""),
            preferred_language=preferred_language,
            phone=phone,
            address=address,
        )
    except Exception as exc:
        logger.warning("normalize_patient failed: %s", type(exc).__name__)
        return None


# ── Conditions ────────────────────────────────────────────────────────────────

def normalize_conditions(bundle: Optional[dict]) -> list[Condition]:
    results = []
    for resource in _entries(bundle):
        if resource.get("resourceType") != "Condition":
            continue
        try:
            code_concept = resource.get("code", {})
            codings = _codings(code_concept)
            icd_coding = _coding_by_system(
                codings,
                "http://hl7.org/fhir/sid/icd-10",
                "http://hl7.org/fhir/sid/icd-10-cm",
            )
            icd10_code = icd_coding.get("code", "") if icd_coding else ""

            display_name = _text_or_display(
                code_concept,
                "http://hl7.org/fhir/sid/icd-10",
                "http://snomed.info",
            )
            if not display_name:
                continue

            # Category
            category = "problem-list-item"
            for cat in resource.get("category", []):
                cat_codes = [c.get("code", "") for c in _codings(cat)]
                if "encounter-diagnosis" in cat_codes:
                    category = "encounter-diagnosis"
                    break
                if cat_codes:
                    category = cat_codes[0]

            severity_concept = resource.get("severity")
            onset = resource.get("onsetDateTime") or _safe(
                lambda r: r.get("onsetPeriod", {}).get("start"), resource
            )

            results.append(
                Condition(
                    id=resource.get("id", ""),
                    icd10_code=icd10_code,
                    display_name=display_name,
                    onset=onset,
                    severity=_text_or_display(severity_concept) if severity_concept else None,
                    category=category,
                )
            )
        except Exception as exc:
            logger.warning("normalize_conditions entry failed: %s", type(exc).__name__)
    return results


# ── Medications ───────────────────────────────────────────────────────────────

def normalize_medications(bundle: Optional[dict]) -> list[Medication]:
    results = []
    for resource in _entries(bundle):
        if resource.get("resourceType") != "MedicationRequest":
            continue
        try:
            # Medication name — CodeableConcept or contained/referenced Medication
            med_concept = resource.get("medicationCodeableConcept") or {}
            med_name = _text_or_display(
                med_concept, "http://www.nlm.nih.gov/research/umls/rxnorm"
            )
            if not med_name:
                med_ref = resource.get("medicationReference", {})
                med_name = med_ref.get("display", "Unknown medication")

            rxnorm_coding = _coding_by_system(
                _codings(med_concept),
                "http://www.nlm.nih.gov/research/umls/rxnorm",
            )
            rxnorm_code = rxnorm_coding.get("code") if rxnorm_coding else None

            dosage_instructions = resource.get("dosageInstruction", [])
            first_dosage = dosage_instructions[0] if dosage_instructions else {}

            # Dosage text — prefer free-text, fall back to structured
            dosage_text = first_dosage.get("text")
            if not dosage_text:
                dose_rate = (first_dosage.get("doseAndRate") or [{}])[0]
                qty = dose_rate.get("doseQuantity", {})
                if qty.get("value") and qty.get("unit"):
                    dosage_text = f"{qty['value']} {qty['unit']}"

            # Frequency
            timing = first_dosage.get("timing", {})
            frequency = _text_or_display(timing.get("code")) or None

            route = _text_or_display(first_dosage.get("route")) or None

            requester = resource.get("requester", {})
            prescriber = requester.get("display") if requester else None

            results.append(
                Medication(
                    id=resource.get("id", ""),
                    name=med_name,
                    rxnorm_code=rxnorm_code,
                    dosage_text=dosage_text,
                    frequency=frequency,
                    route=route,
                    prescriber=prescriber,
                    authored_on=resource.get("authoredOn"),
                    is_new=False,
                )
            )
        except Exception as exc:
            logger.warning("normalize_medications entry failed: %s", type(exc).__name__)
    return results


# ── Allergies ─────────────────────────────────────────────────────────────────

def normalize_allergies(bundle: Optional[dict]) -> list[Allergy]:
    results = []
    for resource in _entries(bundle):
        if resource.get("resourceType") != "AllergyIntolerance":
            continue
        try:
            substance_concept = resource.get("code") or resource.get("substance", {})
            substance = _text_or_display(substance_concept)
            if not substance:
                continue

            reactions = resource.get("reaction", [])
            first_reaction = reactions[0] if reactions else {}
            manifestations = first_reaction.get("manifestation", [])
            reaction_text = _text_or_display(manifestations[0]) if manifestations else None

            results.append(
                Allergy(
                    id=resource.get("id", ""),
                    substance=substance,
                    type=resource.get("type", "allergy"),
                    criticality=resource.get("criticality", "unable-to-assess"),
                    reaction=reaction_text,
                )
            )
        except Exception as exc:
            logger.warning("normalize_allergies entry failed: %s", type(exc).__name__)
    return results


# ── Appointments ──────────────────────────────────────────────────────────────

def normalize_appointments(bundle: Optional[dict]) -> list[AppointmentRecord]:
    results = []
    for resource in _entries(bundle):
        if resource.get("resourceType") != "Appointment":
            continue
        try:
            service_types = resource.get("serviceType", [])
            service_type = _text_or_display(service_types[0]) if service_types else None

            practitioners: list[str] = []
            location: Optional[str] = None
            for participant in resource.get("participant", []):
                actor = participant.get("actor", {})
                ref = actor.get("reference", "")
                display = actor.get("display", "")
                if "Practitioner" in ref or "PractitionerRole" in ref:
                    if display:
                        practitioners.append(display)
                elif "Location" in ref and display:
                    location = display

            results.append(
                AppointmentRecord(
                    id=resource.get("id", ""),
                    service_type=service_type,
                    start=resource.get("start"),
                    end=resource.get("end"),
                    status=resource.get("status", ""),
                    practitioners=practitioners,
                    location=location,
                )
            )
        except Exception as exc:
            logger.warning("normalize_appointments entry failed: %s", type(exc).__name__)
    return results


# ── CareTeam ──────────────────────────────────────────────────────────────────

def normalize_care_team(bundle: Optional[dict]) -> list[CareTeamMember]:
    results = []
    seen: set[str] = set()

    for resource in _entries(bundle):
        if resource.get("resourceType") != "CareTeam":
            continue
        try:
            for participant in resource.get("participant", []):
                member = participant.get("member", {})
                ref = member.get("reference", "")
                name = member.get("display", "")
                if not name or ref in seen:
                    continue
                seen.add(ref or name)

                roles = participant.get("role", [])
                role_text = _text_or_display(roles[0]) if roles else None

                results.append(
                    CareTeamMember(
                        id=ref or str(len(results)),
                        name=name,
                        role=role_text,
                        specialty=None,
                    )
                )
        except Exception as exc:
            logger.warning("normalize_care_team entry failed: %s", type(exc).__name__)
    return results


# ── Documents ─────────────────────────────────────────────────────────────────

def normalize_documents(bundle: Optional[dict]) -> list[DocumentRecord]:
    results = []
    for resource in _entries(bundle):
        if resource.get("resourceType") != "DocumentReference":
            continue
        try:
            type_concept = resource.get("type", {})
            title = _text_or_display(type_concept) or resource.get("description")

            authors = resource.get("author", [])
            author = authors[0].get("display") if authors else None

            content = resource.get("content", [])
            content_url = (
                content[0].get("attachment", {}).get("url") if content else None
            )

            results.append(
                DocumentRecord(
                    id=resource.get("id", ""),
                    title=title,
                    date=resource.get("date") or resource.get("indexed"),
                    author=author,
                    content_url=content_url,
                )
            )
        except Exception as exc:
            logger.warning("normalize_documents entry failed: %s", type(exc).__name__)
    return results


# ── FHIR → agent data mapping ─────────────────────────────────────────────────

def _calculate_age(dob_str: str) -> int:
    try:
        dob = date.fromisoformat(dob_str)
        today = date.today()
        return (today - dob).days // 365
    except (ValueError, TypeError):
        return 0


def _format_medication(med: Medication) -> str:
    parts = [med.name]
    if med.dosage_text:
        parts.append(med.dosage_text)
    if med.frequency:
        parts.append(med.frequency)
    if med.route:
        parts.append(f"({med.route})")
    return " ".join(parts)


def _format_condition(cond: Condition) -> str:
    if cond.icd10_code:
        return f"{cond.display_name} ({cond.icd10_code})"
    return cond.display_name


def _format_allergy(allergy: Allergy) -> str:
    text = allergy.substance
    if allergy.reaction:
        text += f" — {allergy.reaction}"
    if allergy.criticality in ("high",):
        text += " [HIGH CRITICALITY]"
    return text


def fhir_bundle_to_agent_data(bundle: PatientBundle) -> dict:
    """Map a normalized PatientBundle to the raw patient_data format expected by stream_plan.

    Fields unavailable in Phase 1 FHIR resources (Encounter, Coverage, etc.)
    are left empty so the clinical team can supplement them via the UI.
    """
    patient = bundle.patient

    # Demographics
    patient_name = (
        f"{patient.first_name} {patient.last_name}".strip() if patient else ""
    )
    age = str(_calculate_age(patient.date_of_birth)) if (patient and patient.date_of_birth) else ""
    gender = patient.gender if patient else ""
    mrn = patient.mrn if patient else ""
    primary_language = patient.preferred_language if patient else "English"

    # Conditions — encounter diagnoses take priority
    encounter_diags = [c for c in bundle.conditions if c.category == "encounter-diagnosis"]
    problem_list = [c for c in bundle.conditions if c.category != "encounter-diagnosis"]
    all_conditions = encounter_diags + problem_list

    primary_diagnosis = _format_condition(all_conditions[0]) if all_conditions else ""
    secondary_diagnoses = "\n".join(_format_condition(c) for c in all_conditions[1:])

    # Medications
    med_lines = [_format_medication(m) for m in bundle.medications]
    medications_text = "\n".join(med_lines)

    # Allergies block — surfaced in additional clinical notes
    allergy_lines = [_format_allergy(a) for a in bundle.allergies]

    # Upcoming appointments
    appt_lines = []
    for appt in bundle.appointments:
        line = appt.service_type or "Appointment"
        if appt.start:
            line += f" on {appt.start[:10]}"
        if appt.practitioners:
            line += f" with {', '.join(appt.practitioners)}"
        if appt.location:
            line += f" at {appt.location}"
        appt_lines.append(line)

    # Care team
    care_team_lines = []
    for member in bundle.care_team:
        line = member.name
        if member.role:
            line += f" ({member.role})"
        care_team_lines.append(line)

    # Assemble additional clinical notes (no PHI field names — just structured text)
    note_sections: list[str] = []
    if allergy_lines:
        note_sections.append("KNOWN ALLERGIES:\n" + "\n".join(allergy_lines))
    if appt_lines:
        note_sections.append("PENDING FOLLOW-UP APPOINTMENTS:\n" + "\n".join(appt_lines))
    if care_team_lines:
        note_sections.append("CARE TEAM:\n" + "\n".join(care_team_lines))
    if bundle.fetch_warnings:
        warn_lines = [f"- {w.resource}: {w.error}" for w in bundle.fetch_warnings]
        note_sections.append(
            "DATA FETCH WARNINGS (partial data — verify with EHR):\n" + "\n".join(warn_lines)
        )

    return {
        "patient_name": patient_name,
        "age": age,
        "gender": gender,
        "mrn": mrn,
        "primary_language": primary_language,
        "primary_diagnosis": primary_diagnosis,
        "secondary_diagnoses": secondary_diagnoses,
        # Medications: FHIR gives us the current active list; treat as discharge meds
        # (admission list requires Encounter context — Phase 3)
        "discharge_medications": medications_text,
        "inpatient_medications": medications_text,
        "admission_medications": "",
        "additional_clinical_notes": "\n\n".join(note_sections),
        # Fields not available in Phase 1 — clinical staff must supplement
        "admission_date": "",
        "expected_discharge_date": "",
        "attending_physician": care_team_lines[0] if care_team_lines else "",
        "pt_evaluation": "Not evaluated",
        "ot_evaluation": "Not evaluated",
        "st_evaluation": "Not evaluated",
        "primary_insurance": "",
        "secondary_insurance": "",
        "medicare_part_a": "N/A",
        "snf_days_used": 0,
        "living_situation": "",
        "caregiver": "",
        "housing_type": "",
        "bedroom_location": "",
        "transportation": "",
        "patient_family_preference": "",
        "physician_goals": "",
        "additional_notes": f"Patient data imported from {bundle.ehr.upper()} EHR via FHIR R4. "
                            f"Conditions: {len(bundle.conditions)} | "
                            f"Medications: {len(bundle.medications)} | "
                            f"Allergies: {len(bundle.allergies)}",
    }
