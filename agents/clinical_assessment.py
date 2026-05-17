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

    SYSTEM_PROMPT = """You are a clinical assessment specialist supporting hospital discharge planning.

Given a patient's clinical data, your job is to:

1. Summarize the primary diagnosis, secondary diagnoses, and relevant comorbidities
2. Assess functional status:
   - Mobility (ambulatory, requires assist, non-ambulatory)
   - Activities of Daily Living (independent, partial assist, total assist)
   - Cognitive status (intact, mild impairment, moderate/severe impairment)
   - Fall risk level (low, medium, high)
3. Identify clinical needs that must be addressed before discharge:
   - Pending labs, imaging, or specialist consults
   - Wound care, IV therapy, or skilled nursing needs
   - Therapy needs (PT, OT, ST)
4. Assess discharge readiness:
   - Is the patient medically stable?
   - Are vital signs and key clinical indicators trending toward baseline?
   - Are there any active issues that would make discharge unsafe?
5. Recommend appropriate level of care:
   - Home (independent or with support)
   - Home with home health services
   - Skilled Nursing Facility (SNF)
   - Inpatient Rehabilitation Facility (IRF)
   - Long-Term Acute Care (LTAC)
   - Acute Inpatient Hospice

Output your findings in this structured format:

CLINICAL SUMMARY:
[2-3 sentence plain language summary of patient's clinical picture]

FUNCTIONAL STATUS:
- Mobility: [assessment]
- ADLs: [assessment]
- Cognition: [assessment]
- Fall Risk: [Low / Medium / High]

PENDING CLINICAL ITEMS:
[List any outstanding items that must be resolved before discharge]

DISCHARGE READINESS: [Ready / Not Ready / Conditional]
If conditional, explain what conditions must be met.

RECOMMENDED LEVEL OF CARE: [recommendation]
RATIONALE: [brief clinical justification]

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
