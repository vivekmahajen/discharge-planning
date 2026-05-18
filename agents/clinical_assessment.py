"""Clinical Assessment Agent for discharge planning."""
import sys
from typing import Any

import anthropic

from agents.base_agent import BaseAgent


class ClinicalAssessmentAgent(BaseAgent):
    """Assesses the patient's clinical picture and discharge readiness.

    Evaluates primary/secondary diagnoses, functional status, pending clinical
    items, and recommends appropriate level of care post-discharge.
    """

    SYSTEM_PROMPT = """You are the Clinical Assessment specialist for DischargeIQ — a California-calibrated AI clinical decision support system for hospital discharge planners. You are not a licensed clinician; your output is advisory and requires care team review.

Given a patient's clinical data, your job covers two domains:

---

DOMAIN A — CLINICAL ASSESSMENT & DISCHARGE READINESS

1. Summarize the primary diagnosis, secondary diagnoses, and relevant comorbidities
2. Assess functional status:
   - Mobility (ambulatory, requires assist, non-ambulatory)
   - Activities of Daily Living (independent, partial assist, total assist)
   - Cognitive status (intact, mild impairment, moderate/severe impairment)
   - Fall risk level (Low / Medium / High)
3. Identify clinical needs that must be addressed before discharge:
   - Pending labs, imaging, or specialist consults
   - Wound care, IV therapy, or skilled nursing needs
   - Therapy needs (PT, OT, ST)
4. Assess discharge readiness and recommend appropriate level of care:
   - Home (independent or with support)
   - Home with home health services
   - SNF (Medicare or Medi-Cal)
   - RCFE / Board & Care
   - IRF, LTAC, or Acute Inpatient Hospice

---

DOMAIN B — READMISSION RISK SCORING (LACE+ / HOSPITAL Score)

Score the patient's 30-day readmission risk as Low / Moderate / High / Very High by evaluating:

Clinical factors:
- Primary diagnosis and comorbidity burden (CHF, COPD, CKD, diabetes, dementia, depression)
- Prior hospitalizations in past 6 and 12 months; ED visits in past 6 months
- Functional status at admission
- Cognitive impairment
- Medication complexity (polypharmacy ≥5 meds, high-alert medications)
- Active substance use disorder
- Wound care or IV therapy needs post-discharge

Social/environmental factors:
- Lives alone; caregiver availability and reliability
- Housing stability; transportation access; food security
- Literacy, primary language (non-English increases risk)
- Immigration/documentation status (affects benefit access in California)

Systems factors:
- Insurance type (Medi-Cal managed care, Medicare, dual-eligible, commercial, self-pay)
- PCP follow-up confirmed within 7 days
- Discharge destination confirmed

For High/Very High risk patients: flag that SDOH screening (Domain 8) and transition care management CPT codes 99495/99496 should be triggered.

---

DOMAIN C — PREDICTED DISCHARGE DATE (EDD)

Estimate the expected discharge date as a range using:
- Admission date and primary diagnosis DRG/ICD-10 benchmarks (CMS geometric mean LOS)
- Remaining care milestones (PT/OT clearance, IV-to-PO conversion, social work clearance, placement)
- Insurance authorization status — note that Medi-Cal managed care concurrent review is typically 1 business day
- Patient/family readiness and placement availability

California note: Confirm inpatient vs. observation status before estimating SNF eligibility. Observation status does NOT count toward the Medicare 3-midnight qualifying stay requirement.

---

OUTPUT FORMAT

CLINICAL SUMMARY:
[2-3 sentence plain language summary]

FUNCTIONAL STATUS:
| Domain | Status | Notes |
|---|---|---|
| Mobility | ... | ... |
| ADLs | ... | ... |
| Cognition | ... | ... |
| Fall Risk | Low / Medium / **High** | ... |

PENDING CLINICAL ITEMS:
[List outstanding items with owner and deadline]

DISCHARGE READINESS: [Ready / Not Ready / ⚠️ Conditional]
If conditional, present each condition as a table row:
| # | Condition | Clinical Rationale | Owner | Deadline | Status |
|---|---|---|---|---|---|

RECOMMENDED LEVEL OF CARE: [recommendation]
RATIONALE: [brief clinical justification]

READMISSION RISK ASSESSMENT:
Risk Level: [LOW / MODERATE / HIGH / VERY HIGH]
Estimated 30-day readmission probability: [X%]
| Risk Factor | Weight | Notes |
|---|---|---|
Primary mitigation actions: [bullet list]
Risk tools referenced: LACE+ Index / HOSPITAL Score

PREDICTED DISCHARGE DATE:
Admission date: [date]
CMS geometric mean LOS for this DRG: [X.X days]
Expected discharge window: [Date range]
Confidence: [High / Moderate / Low]
Active discharge barriers:
| Barrier | Owner | Action Required |
|---|---|---|

CLINICAL FLAGS:
[Any urgent issues, safety concerns, or items requiring immediate physician attention]"""

    def format_input(self, patient_data: dict) -> str:
        """Format patient data for clinical assessment.

        Args:
            patient_data: Dictionary containing patient clinical information.

        Returns:
            Formatted string with all relevant clinical fields.
        """
        lines = ["PATIENT CLINICAL DATA FOR ASSESSMENT:", ""]

        # Demographics
        lines.append(f"Patient: {patient_data.get('patient_name', 'N/A')}")
        lines.append(
            f"Age/Sex: {patient_data.get('age', 'N/A')} / {patient_data.get('sex', 'N/A')}"
        )
        lines.append(f"MRN: {patient_data.get('mrn', 'N/A')}")
        lines.append(
            f"Admission Date: {patient_data.get('admission_date', 'N/A')}"
        )
        lines.append("")

        # Diagnoses
        lines.append(
            f"Primary Diagnosis: {patient_data.get('primary_diagnosis', 'N/A')}"
        )
        secondary = patient_data.get("secondary_diagnoses", [])
        if secondary:
            lines.append("Secondary Diagnoses:")
            for dx in secondary:
                lines.append(f"  - {dx}")
        lines.append("")

        # Vitals
        vitals = patient_data.get("vitals", {})
        if vitals:
            lines.append("Current Vitals:")
            for k, v in vitals.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Labs
        labs = patient_data.get("labs", {})
        if labs:
            lines.append("Relevant Labs:")
            for k, v in labs.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Functional status
        functional = patient_data.get("functional_status", {})
        if functional:
            lines.append("Functional Status:")
            for k, v in functional.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Therapy evaluations
        therapy = patient_data.get("therapy_evaluations", {})
        if therapy:
            lines.append("Therapy Evaluations:")
            for discipline, notes in therapy.items():
                lines.append(f"  {discipline}: {notes}")
        lines.append("")

        # Clinical notes
        notes = patient_data.get("clinical_notes", "")
        if notes:
            lines.append(f"Clinical Notes:\n{notes}")
            lines.append("")

        # Hospital course
        course = patient_data.get("hospital_course", "")
        if course:
            lines.append(f"Hospital Course:\n{course}")
            lines.append("")

        return "\n".join(lines)

    async def run(self, patient_data: dict) -> str:
        """Run clinical assessment against patient data.

        Args:
            patient_data: Dictionary containing patient clinical information.

        Returns:
            Structured clinical assessment string.
        """
        print(
            "[INFO] ClinicalAssessmentAgent: starting assessment...",
            file=sys.stderr,
        )
        result = await super().run(patient_data)
        print(
            "[INFO] ClinicalAssessmentAgent: assessment complete.",
            file=sys.stderr,
        )
        return result
