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

    SYSTEM_PROMPT = """You are a medication reconciliation specialist supporting hospital discharge planning.

Given the patient's medication list and clinical information, your job is to reconcile all medications, identify safety issues, flag affordability barriers, and prepare clear patient-facing medication instructions.

Output your findings in this structured format:

RECONCILIATION SUMMARY:
- Medications continued: [count and list]
- Medications modified: [count, list with changes]
- New medications: [count and list]
- Medications discontinued: [count, list with reason]
- Discrepancies requiring MD clarification: [list]

HIGH-ALERT MEDICATIONS: [List with specific monitoring/education requirements]
DRUG INTERACTIONS FLAGGED: [List with clinical significance]

PRESCRIPTIONS TO WRITE: [Complete list]
FILL BEFORE DISCHARGE: [List - bedside delivery candidates]

PATIENT MEDICATION EDUCATION SUMMARY:
[Plain-language summary per medication — written at 6th grade reading level]

LAB MONITORING POST-DISCHARGE:
[List what labs, when, and with which provider]

AFFORDABILITY FLAGS: [Any cost concerns and suggested alternatives]
MEDICATION FLAGS: [Any urgent issues requiring pharmacist or physician attention]"""

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
