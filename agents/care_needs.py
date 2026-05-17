"""Care Needs Agent for discharge planning."""
import sys

import anthropic

from agents.base_agent import BaseAgent


class CareNeedsAgent(BaseAgent):
    """Identifies and documents all post-discharge care needs.

    Covers skilled nursing, therapy, monitoring, personal care, equipment,
    and caregiver requirements across six structured categories.
    """

    SYSTEM_PROMPT = """You are a care needs specialist supporting hospital discharge planning.

Given the clinical assessment findings, your job is to identify and document all post-discharge care needs across the following categories:

1. SKILLED NURSING NEEDS
2. THERAPY NEEDS
3. MONITORING NEEDS
4. PERSONAL CARE NEEDS
5. EQUIPMENT NEEDS
6. CAREGIVER NEEDS

Output your findings in this structured format:

SKILLED NURSING NEEDS: [None / list with frequency]
THERAPY NEEDS: [None / list by discipline]
MONITORING NEEDS: [None / list with frequency]
PERSONAL CARE NEEDS: [Independent / list assistance required]
EQUIPMENT NEEDED: [None / list each item]
CAREGIVER REQUIREMENT: [None / Part-time / Full-time]
CAREGIVER TRAINING NEEDED: [Yes / No / list topics if yes]

LEVEL OF CARE CONFIRMATION:
Based on identified needs, the appropriate level of care is: [Home / Home with HH / SNF / IRF / LTAC]
Rationale: [brief explanation]

CARE NEEDS FLAGS:
[Any complex needs, safety concerns, or situations where home discharge may not be safe]"""

    def format_input(self, patient_data: dict) -> str:
        """Format patient data for care needs assessment.

        Args:
            patient_data: Dictionary containing patient information.

        Returns:
            Formatted string emphasizing care-relevant fields.
        """
        lines = ["PATIENT DATA FOR CARE NEEDS ASSESSMENT:", ""]

        lines.append(f"Patient: {patient_data.get('patient_name', 'N/A')}")
        lines.append(
            f"Age/Sex: {patient_data.get('age', 'N/A')} / {patient_data.get('sex', 'N/A')}"
        )
        lines.append(
            f"Primary Diagnosis: {patient_data.get('primary_diagnosis', 'N/A')}"
        )

        secondary = patient_data.get("secondary_diagnoses", [])
        if secondary:
            lines.append("Secondary Diagnoses: " + ", ".join(secondary))
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

        # Home environment
        home = patient_data.get("home_environment", {})
        if home:
            lines.append("Home Environment:")
            for k, v in home.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Support system
        support = patient_data.get("support_system", {})
        if support:
            lines.append("Support System:")
            for k, v in support.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Medications (for nursing needs context)
        discharge_meds = patient_data.get("discharge_medications", [])
        if discharge_meds:
            lines.append("Discharge Medications (for care needs context):")
            for med in discharge_meds:
                lines.append(f"  - {med}")
        lines.append("")

        # Hospital course
        course = patient_data.get("hospital_course", "")
        if course:
            lines.append(f"Hospital Course:\n{course}")
            lines.append("")

        return "\n".join(lines)

    async def run(self, patient_data: dict) -> str:
        """Run care needs assessment against patient data.

        Args:
            patient_data: Dictionary containing patient information.

        Returns:
            Structured care needs assessment string.
        """
        print(
            "[INFO] CareNeedsAgent: starting assessment...",
            file=sys.stderr,
        )
        result = await super().run(patient_data)
        print(
            "[INFO] CareNeedsAgent: assessment complete.",
            file=sys.stderr,
        )
        return result
