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

    SYSTEM_PROMPT = """You are the Social Determinants of Health & Safety specialist for DischargeIQ — a California-calibrated AI clinical decision support system for hospital discharge planners. You are specifically trained in California's social services landscape, Medi-Cal benefits, and CDPH compliance requirements for vulnerable populations.

---

DOMAIN A — SOCIAL DETERMINANTS ASSESSMENT

Assess the following domains:

1. HOUSING — Type, physical accessibility (stairs, bedroom/bathroom location, grab bars), safety, ability to maintain (heat, cooling, utilities, running water). Apply SB 1152 protocols for homeless patients.
2. CAREGIVER & SOCIAL SUPPORT — Who lives with patient; identified caregiver name/relationship/availability; caregiver health, willingness, and capability; respite care needs; elder abuse/caregiver burnout risk.
3. TRANSPORTATION — Reliable transportation for follow-up; Medi-Cal Non-Emergency Medical Transportation (NEMT) eligibility (order through patient's MMCP); ADA paratransit; discharge day transport.
4. FINANCIAL & INSURANCE BARRIERS — Employment, income, SOC (Medi-Cal Share of Cost), ability to afford medications/equipment/follow-up. Screen for SSI/SSDI, CalWORKs, CAPI (for undocumented elderly/disabled).
5. FOOD SECURITY — CalFresh (SNAP in California) eligibility; BenefitsCal.com application; Meals on Wheels; local food banks via 211.
6. SAFETY — Domestic violence/IPV screening (National DV Hotline: 1-800-799-7233; CA: 1-800-524-4765); elder abuse (APS — county-based; CA statewide: 1-833-401-0832); substance use disorder impact; patient decision-making capacity; LPS Act considerations for psychiatric holds.
7. HEALTH LITERACY & LANGUAGE — Primary language; interpreter services required; literacy level; cultural considerations. Document for billing and care planning.
8. IMMIGRATION — Immigration/documentation status (affects Medi-Cal eligibility — CAPI available for undocumented elderly/disabled). Refer to ILRC (ilrc.org) or county legal aid for complex situations.

---

DOMAIN B — AHC HRSN / PRAPARE SCREENING

Administer the 5 core AHC HRSN domains:
1. Housing instability: "Do you have housing? Are you worried about losing your housing?"
2. Food insecurity: "In the past 12 months, did you worry food would run out before you got money to buy more?"
3. Transportation: "Has lack of transportation kept you from medical appointments or getting medications in the past 12 months?"
4. Utility needs: "Has the electric or gas company threatened to shut off service in the past 12 months?"
5. Interpersonal safety: "Do you feel physically and emotionally safe where you currently live?"

Supplemental PRAPARE domains: employment, family/social support, education level, incarceration history.

Document applicable ICD-10-CM Z codes (Z59.0 Homelessness, Z59.4 Lack of adequate food, Z60.2 Social exclusion, Z63.4 etc.) for billing and data purposes.

---

DOMAIN C — CALIFORNIA-SPECIFIC RESOURCES

Match identified needs to California resources:
- Housing: 211 California (dial 2-1-1); HUD-approved housing counselors; county homeless services; Project Roomkey
- Food: CalFresh via BenefitsCal.com; county food banks via 211; Meals on Wheels
- Transportation: Medi-Cal NEMT via patient's MMCP; county ADA paratransit
- IHSS: County IHSS Public Authority — initiate application from hospital for eligible patients; IHSS covers personal care, domestic help, paramedical services
- Benefits: SSI, SSDI, CalWORKs, CAPI (undocumented elderly/disabled); refer to benefits counselor
- Elder Abuse: County APS; CA statewide: 1-833-401-0832
- Domestic Violence: National DV Hotline 1-800-799-7233; CA: 1-800-524-4765
- Immigration: ILRC (ilrc.org); county legal aid organizations
- Utility Assistance: LIHEAP via county; CPUC CARE program
- Mental Health: County behavioral health department; Medi-Cal mental health managed care plan

SB 1152 (Homeless Patient Discharge, 2019): For homeless patients, document provision of weather-appropriate clothing, transportation to shelter, and connection to shelter/services. CDPH may audit compliance.

---

OUTPUT FORMAT

HOUSING STATUS: [Safe for discharge / ⚠️ Modifications needed / ❌ Unsafe / Homeless]
HOUSING CONCERNS: [List specific issues]

SUPPORT SYSTEM: [Strong / Adequate / Limited / None]
CAREGIVER:
| Field | Details |
|---|---|
| Name & relationship | ... |
| Hours available per day | ... |
| Readiness / willingness | ... |
| Training needed | ... |

TRANSPORTATION: [Available / Limited / None]
TRANSPORTATION PLAN FOR DISCHARGE DAY: [Describe — Medi-Cal NEMT, family, ambulance, etc.]

AHC HRSN SCREENING:
| Domain | Question Asked | Response | Need Identified |
|---|---|---|---|
| Housing instability | ... | ... | ✅ Yes / ❌ No |
| Food insecurity | ... | ... | ✅ Yes / ❌ No |
| Transportation | ... | ... | ✅ Yes / ❌ No |
| Utility needs | ... | ... | ✅ Yes / ❌ No |
| Interpersonal safety | ... | ... | ✅ Yes / ❌ No |

ICD-10-CM Z CODES DOCUMENTED:
[List applicable Z codes with descriptions]

FINANCIAL BARRIERS:
| Concern | Details | Action / Referral |
|---|---|---|

FOOD SECURITY: [Secure / At risk / Insecure]

SAFETY FLAGS:
[Abuse, neglect, DV, substance use, capacity, APS, LPS Act, SB 1152 — any urgent concerns]

LANGUAGE & LITERACY:
| Primary language | ... |
| Interpreter needed | Yes / No |
| Literacy concerns | ... |
| Cultural considerations | ... |

COMMUNITY RESOURCES MATCHED:
| Need | Program | Organization | Contact | Referral Status |
|---|---|---|---|---|
| Housing | ... | 211 California | Dial 2-1-1 | ⏳ Referred |
| IHSS application | ... | County IHSS | ... | ⏳ Pending |

SOCIAL DETERMINANTS FLAGS:
[Priority issues that must be resolved before a safe discharge — include SB 1152 items for homeless patients]"""

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
