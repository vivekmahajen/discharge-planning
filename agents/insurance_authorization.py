"""Insurance Authorization Agent for discharge planning."""
import sys

import anthropic

from agents.base_agent import BaseAgent


class InsuranceAuthorizationAgent(BaseAgent):
    """Verifies insurance coverage and identifies authorization requirements.

    Analyzes the patient's payer profile, checks benefit limits, identifies
    prior auth requirements, assesses denial risk, and summarizes cost exposure.
    """

    SYSTEM_PROMPT = """You are an insurance and authorization specialist supporting hospital discharge planning.

Given the patient's insurance information and identified post-discharge needs, your job is to verify coverage, identify prior authorization requirements, assess denial risk, and summarize patient cost exposure.

Output your findings in this structured format:

INSURANCE PROFILE:
- Primary: [payer name, plan type, member ID]
- Secondary: [if applicable]
- Medicare status: [Traditional / Advantage / Not applicable]

BENEFIT SUMMARY:
[Table or list of each recommended service with coverage status, limits, and co-pay]

PRIOR AUTHORIZATIONS NEEDED:
[List each service requiring auth, documents needed, expected turnaround]

SNF ELIGIBILITY: [Eligible / Not eligible / Pending 3-day stay]
HOME HEALTH ELIGIBILITY: [Eligible / Not eligible / Homebound status needs verification]

DENIAL RISK FLAGS:
[Any services with high denial risk, peer-to-peer likely situations]

ESTIMATED PATIENT COST:
[Brief summary of likely out-of-pocket exposure]

INSURANCE FLAGS:
[Urgent authorization needs, benefit exhaustion warnings, compliance items]"""

    def format_input(self, patient_data: dict) -> str:
        """Format patient data for insurance authorization review.

        Args:
            patient_data: Dictionary containing patient and insurance information.

        Returns:
            Formatted string emphasizing insurance and coverage fields.
        """
        lines = ["PATIENT INSURANCE DATA FOR AUTHORIZATION REVIEW:", ""]

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

        # Admission info for SNF 3-day rule
        lines.append(
            f"Admission Date: {patient_data.get('admission_date', 'N/A')}"
        )
        lines.append(
            f"Anticipated Discharge Date: {patient_data.get('anticipated_discharge_date', 'N/A')}"
        )
        lines.append("")

        # Insurance details
        insurance = patient_data.get("insurance", {})
        if insurance:
            lines.append("Insurance Information:")
            for k, v in insurance.items():
                if isinstance(v, dict):
                    lines.append(f"  {k}:")
                    for sk, sv in v.items():
                        lines.append(f"    {sk}: {sv}")
                else:
                    lines.append(f"  {k}: {v}")
        lines.append("")

        # Identified post-discharge needs (from clinical assessment context)
        needs = patient_data.get("anticipated_post_discharge_needs", [])
        if needs:
            lines.append("Anticipated Post-Discharge Needs:")
            for need in needs:
                lines.append(f"  - {need}")
        lines.append("")

        # Functional status (for SNF/HH eligibility context)
        functional = patient_data.get("functional_status", {})
        if functional:
            lines.append("Functional Status (for level-of-care determination):")
            for k, v in functional.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Hospital course
        course = patient_data.get("hospital_course", "")
        if course:
            lines.append(f"Hospital Course:\n{course}")
            lines.append("")

        return "\n".join(lines)

    async def run(self, patient_data: dict) -> str:
        """Run insurance authorization review against patient data.

        Args:
            patient_data: Dictionary containing patient and insurance information.

        Returns:
            Structured insurance authorization assessment string.
        """
        print(
            "[INFO] InsuranceAuthorizationAgent: starting review...",
            file=sys.stderr,
        )
        result = await super().run(patient_data)
        print(
            "[INFO] InsuranceAuthorizationAgent: review complete.",
            file=sys.stderr,
        )
        return result
