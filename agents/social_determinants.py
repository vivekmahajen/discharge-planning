"""Social Determinants of Health Agent for discharge planning."""
import sys

import anthropic

from agents.base_agent import BaseAgent


class SocialDeterminantsAgent(BaseAgent):
    """Assesses non-medical factors impacting discharge safety and success.

    Evaluates housing, support systems, transportation, financial barriers,
    food security, safety concerns, language/literacy, and matches community
    resources to address identified needs.
    """

    SYSTEM_PROMPT = """You are a social determinants of health and patient safety specialist supporting hospital discharge planning.

Given the patient's social history and clinical context, your job is to assess and address all non-medical factors that could impact discharge safety and success.

Output your findings in this structured format:

HOUSING STATUS: [Safe for discharge / Modifications needed / Unsafe / Homeless]
HOUSING CONCERNS: [List specific issues]

SUPPORT SYSTEM: [Strong / Adequate / Limited / None]
CAREGIVER: [Name, relationship, hours available, readiness]
CAREGIVER CONCERNS: [List any issues]

TRANSPORTATION: [Available / Limited / None]
TRANSPORTATION PLAN FOR DISCHARGE DAY: [Describe]

FINANCIAL BARRIERS: [None identified / List concerns]
FOOD SECURITY: [Secure / At risk / Insecure]

SAFETY FLAGS:
[Any abuse, neglect, domestic violence, substance use, or mental health concerns]
[Any Adult Protective Services or legal issues]

LANGUAGE & LITERACY: [Primary language, interpreter needed Y/N, literacy concerns]

COMMUNITY RESOURCES MATCHED:
[List programs recommended with contact information if available]

SOCIAL DETERMINANTS FLAGS:
[Priority issues that must be resolved before a safe discharge can occur]"""

    def format_input(self, patient_data: dict) -> str:
        """Format patient data for social determinants assessment.

        Args:
            patient_data: Dictionary containing patient social history.

        Returns:
            Formatted string emphasizing social and environmental fields.
        """
        lines = ["PATIENT SOCIAL DATA FOR SDOH ASSESSMENT:", ""]

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

        # Functional status (for housing/safety assessment)
        functional = patient_data.get("functional_status", {})
        if functional:
            lines.append("Functional Status:")
            for k, v in functional.items():
                lines.append(f"  {k}: {v}")
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

        # Transportation
        transport = patient_data.get("transportation", {})
        if transport:
            lines.append("Transportation:")
            for k, v in transport.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Financial information
        financial = patient_data.get("financial_info", {})
        if financial:
            lines.append("Financial Information:")
            for k, v in financial.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Food security
        food = patient_data.get("food_security", "")
        if food:
            lines.append(f"Food Security: {food}")
        lines.append("")

        # Safety concerns
        safety = patient_data.get("safety_concerns", [])
        if safety:
            lines.append("Safety Concerns:")
            for concern in safety:
                lines.append(f"  - {concern}")
        lines.append("")

        # Language and literacy
        lang = patient_data.get("language_literacy", {})
        if lang:
            lines.append("Language & Literacy:")
            for k, v in lang.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        # Social history
        social_history = patient_data.get("social_history", {})
        if social_history:
            lines.append("Social History:")
            for k, v in social_history.items():
                lines.append(f"  {k}: {v}")
        lines.append("")

        return "\n".join(lines)

    async def run(self, patient_data: dict) -> str:
        """Run social determinants assessment against patient data.

        Args:
            patient_data: Dictionary containing patient social information.

        Returns:
            Structured social determinants assessment string.
        """
        print(
            "[INFO] SocialDeterminantsAgent: starting assessment...",
            file=sys.stderr,
        )
        result = await super().run(patient_data)
        print(
            "[INFO] SocialDeterminantsAgent: assessment complete.",
            file=sys.stderr,
        )
        return result
