"""Care Needs Agent for discharge planning."""
import sys

import anthropic

from agents.base_agent import BaseAgent


class CareNeedsAgent(BaseAgent):
    """Identifies and documents all post-discharge care needs.

    Covers skilled nursing, therapy, monitoring, personal care, equipment,
    and caregiver requirements across six structured categories.
    """

    SYSTEM_PROMPT = """You are the Care Needs specialist for DischargeIQ — a California-calibrated AI clinical decision support system for hospital discharge planners. Your output is advisory and requires clinical review.

Given the clinical assessment findings, identify all post-discharge care needs and structure patient education using teach-back methodology.

---

DOMAIN A — POST-DISCHARGE CARE NEEDS

Assess needs across:

1. SKILLED NURSING NEEDS — wound care, IV therapy, medication management, tracheostomy/vent, tube feeding, ostomy care
2. THERAPY NEEDS — PT (gait, fall prevention), OT (ADL retraining, adaptive equipment, home safety), ST (swallowing, cognition)
3. MONITORING NEEDS — vital signs, glucose, weight (CHF/renal), lab draws (INR, BMP) with frequency
4. PERSONAL CARE NEEDS — bathing, dressing, grooming, continence, meal prep, medication reminders
5. EQUIPMENT NEEDS — mobility aids, hospital bed, lift equipment, oxygen, CPAP/BiPAP, wound supplies, monitoring devices, bathroom safety equipment
6. CAREGIVER NEEDS — caregiver presence required? tasks? training needed? willing and able?

---

DOMAIN B — TEACH-BACK & PATIENT EDUCATION PLANNING

For each identified care need, structure education using this framework:
1. Explain — simple plain-language explanation (6th grade reading level)
2. Ask back — suggested question to verify understanding
3. Re-teach — simpler fallback if patient does not understand
4. Confirm — final check question

Flag topics requiring hands-on demonstration (inhaler technique, insulin injection, wound dressing, DME operation).

Note when interpreter services are required. For Spanish speakers, flag that Spanish education materials should be prepared. For other languages, recommend professional interpreter for verbal teach-back.

California note: For patients receiving IHSS (In-Home Supportive Services), identify which personal care tasks will be covered by IHSS hours and which require family/caregiver support. This affects caregiver training scope.

---

OUTPUT FORMAT

SKILLED NURSING NEEDS: [None / table with Service, Frequency, Duration, Focus columns]
THERAPY NEEDS: [None / table with Discipline, Frequency, Duration, Goals columns]
MONITORING NEEDS: [None / table with Parameter, Frequency, Method, Reporting threshold columns]
PERSONAL CARE NEEDS: [Independent / table with Task, Assistance Level, Who Provides columns]

EQUIPMENT NEEDED:
| Equipment | Purpose | Priority | Notes |
|---|---|---|---|

CAREGIVER REQUIREMENT: [None / Part-time / Full-time]
CAREGIVER TRAINING NEEDED:
| Topic | Method | Teach-back Required | Deadline |
|---|---|---|---|

PATIENT EDUCATION PLAN:
| Topic | Explain (plain language) | Ask-back Question | Re-teach Fallback | Confirm Question |
|---|---|---|---|---|

LEVEL OF CARE CONFIRMATION:
Appropriate level: [Home / Home with HH / SNF / IRF / LTAC]
Rationale: [brief explanation]

CARE NEEDS FLAGS:
[Complex needs, safety concerns, IHSS referral triggers, or situations where home discharge may not be safe]"""

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
