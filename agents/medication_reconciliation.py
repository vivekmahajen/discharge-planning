"""Medication Reconciliation Agent for discharge planning."""
import sys

import anthropic

from agents.base_agent import BaseAgent


class MedicationReconciliationAgent(BaseAgent):
    """Reconciles medications and prepares patient-facing discharge instructions.

    Reviews admission vs. discharge medication lists, identifies safety issues,
    flags drug interactions and affordability barriers, and produces clear
    patient education materials written at a 6th-grade reading level.
    """

    SYSTEM_PROMPT = """You are the Medication Reconciliation specialist for DischargeIQ — a California-calibrated AI clinical decision support system for hospital discharge planners. Your output is advisory; all medication changes require pharmacist and physician review before implementation.

---

DOMAIN A — MEDICATION RECONCILIATION

1. Compare admission medication list to current inpatient medication list
2. Classify each medication: continued / modified (dose, route, or frequency change) / new / discontinued (with reason)
3. Flag discrepancies requiring physician clarification
4. Identify drug-drug interactions and high-alert medications
5. Flag medications requiring prior authorization from pharmacy benefit

---

DOMAIN B — HIGH-ALERT MEDICATION SAFETY

For each high-alert medication (anticoagulants, insulin, opioids, digoxin, narrow therapeutic index drugs), provide:
- Risk level: 🔴 High / 🟡 Moderate
- Specific monitoring requirements (lab, frequency, ordering provider)
- Post-discharge lab schedule
- Special dispensing requirements (controlled substances, cold chain)

California formulary note: Flag any medications that may not be covered under the patient's Medi-Cal MMCP formulary. Suggest therapeutic alternatives if applicable. Note that Medi-Cal managed care plans may have step-therapy requirements for newer medications.

---

DOMAIN C — PATIENT MEDICATION EDUCATION (TEACH-BACK)

For each discharge medication, generate plain-language education using the teach-back framework:
1. Explain — what it is, what it does (6th grade reading level, no jargon)
2. Ask back — "In your own words, what is this medication for?"
3. Timing / how to take it — specific instructions
4. What to avoid — foods, OTC drugs, activities
5. Warning signs — what to watch for and when to call the doctor
6. Missed dose — what to do
7. Confirm — final teach-back question

Flag medications requiring demonstration (inhalers, insulin pens, patches, eye drops).
Always offer Spanish-language instructions. Note when professional interpreter is needed for verbal teach-back.

---

OUTPUT FORMAT

RECONCILIATION SUMMARY:
| Category | Count | Medications |
|---|---|---|
| Continued from home | # | list |
| Modified (dose/frequency/route) | # | list with changes |
| New (started in hospital) | # | list |
| Discontinued | # | list with reason |
| Discrepancies requiring MD clarification | # | list |

HIGH-ALERT MEDICATIONS:
| Medication | Risk Level | Monitoring Required | Key Patient Education | ⚠️ Special Flags |
|---|---|---|---|---|

[After the table, add a brief narrative for any medication with complex pending decisions, hold conditions, or physician sign-off required before finalizing dose.]

DRUG INTERACTIONS FLAGGED:
| Interaction | Medications Involved | Clinical Significance | Recommended Action |
|---|---|---|---|

PRESCRIPTIONS TO WRITE:
| Medication | Dose | Route | Quantity | Refills | Special Instructions |
|---|---|---|---|---|---|

FILL BEFORE DISCHARGE (bedside delivery candidates):
[List medications that should be dispensed at bedside before patient leaves]

PATIENT MEDICATION EDUCATION:
| Medication | Purpose (plain language) | How/When to Take | Foods/Drugs to Avoid | Warning Signs → Call MD | Missed Dose | Teach-back Question |
|---|---|---|---|---|---|---|

LAB MONITORING POST-DISCHARGE:
| Lab | Frequency | First Due | Ordering Provider | Critical Values to Report |
|---|---|---|---|---|

AFFORDABILITY FLAGS:
| Medication | Estimated Cost | Concern | Alternative / Assistance Program |
|---|---|---|---|

MEDICATION FLAGS:
[Any urgent issues requiring pharmacist or physician attention before discharge order is placed]"""

    def format_input(self, patient_data: dict) -> str:
        """Format patient data for medication reconciliation.

        Args:
            patient_data: Dictionary containing patient and medication information.

        Returns:
            Formatted string emphasizing medication-relevant fields.
        """
        lines = ["PATIENT MEDICATION DATA FOR RECONCILIATION:", ""]

        lines.append(f"Patient: {patient_data.get('patient_name', 'N/A')}")
        lines.append(
            f"Age/Sex: {patient_data.get('age', 'N/A')} / {patient_data.get('sex', 'N/A')}"
        )
        lines.append(f"MRN: {patient_data.get('mrn', 'N/A')}")
        lines.append(
            f"Primary Diagnosis: {patient_data.get('primary_diagnosis', 'N/A')}"
        )
        secondary = patient_data.get("secondary_diagnoses", [])
        if secondary:
            lines.append("Secondary Diagnoses: " + ", ".join(secondary))
        lines.append("")

        # Relevant labs for medication context
        labs = patient_data.get("labs", {})
        if labs:
            lines.append("Relevant Labs (for medication safety):")
            for k, v in labs.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Admission medications
        admission_meds = patient_data.get("admission_medications", [])
        if admission_meds:
            lines.append("Admission Medications (home medications on arrival):")
            for med in admission_meds:
                lines.append(f"  - {med}")
        lines.append("")

        # Inpatient medications
        inpatient_meds = patient_data.get("inpatient_medications", [])
        if inpatient_meds:
            lines.append("Inpatient Medications:")
            for med in inpatient_meds:
                lines.append(f"  - {med}")
        lines.append("")

        # Discharge medications
        discharge_meds = patient_data.get("discharge_medications", [])
        if discharge_meds:
            lines.append("Proposed Discharge Medications:")
            for med in discharge_meds:
                lines.append(f"  - {med}")
        lines.append("")

        # Allergies
        allergies = patient_data.get("allergies", [])
        if allergies:
            lines.append("Allergies/Adverse Reactions:")
            for allergy in allergies:
                lines.append(f"  - {allergy}")
        lines.append("")

        # Insurance for affordability context
        insurance = patient_data.get("insurance", {})
        primary = insurance.get("primary", {})
        if primary:
            lines.append(
                f"Insurance: {primary.get('payer_name', 'N/A')} ({primary.get('plan_type', 'N/A')})"
            )
        lines.append("")

        # Financial context
        financial = patient_data.get("financial_info", {})
        if financial:
            lines.append("Financial Information:")
            for k, v in financial.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        return "\n".join(lines)

    async def run(self, patient_data: dict) -> str:
        """Run medication reconciliation against patient data.

        Args:
            patient_data: Dictionary containing patient and medication information.

        Returns:
            Structured medication reconciliation assessment string.
        """
        print(
            "[INFO] MedicationReconciliationAgent: starting reconciliation...",
            file=sys.stderr,
        )
        result = await super().run(patient_data)
        print(
            "[INFO] MedicationReconciliationAgent: reconciliation complete.",
            file=sys.stderr,
        )
        return result
