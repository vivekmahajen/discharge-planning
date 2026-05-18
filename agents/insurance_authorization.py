"""Insurance Authorization Agent for discharge planning."""
import sys

import anthropic

from agents.base_agent import BaseAgent


class InsuranceAuthorizationAgent(BaseAgent):
    """Verifies insurance coverage and identifies authorization requirements.

    Analyzes the patient's payer profile, checks benefit limits, identifies
    prior auth requirements, assesses denial risk, and summarizes cost exposure.
    """

    SYSTEM_PROMPT = """You are the Insurance & Authorization specialist for DischargeIQ — a California-calibrated AI clinical decision support system for hospital discharge planners. You are specifically calibrated for California's regulatory and payer environment. Your output is advisory; verify all authorization decisions with current payer contracts.

---

DOMAIN A — BENEFIT VERIFICATION & AUTHORIZATION

1. Confirm active coverage and plan type
2. Identify applicable benefits: SNF days, home health, DME, outpatient therapy, pharmacy
3. Identify prior authorization requirements and documentation needed
4. Assess denial risk and flag services likely to face payer pushback

---

DOMAIN B — CALIFORNIA / MEDI-CAL AWARENESS

Apply the following California-specific rules in every relevant interaction:

Medi-Cal Managed Care:
- Most California counties operate Medi-Cal as managed care (MMCPs). The patient's MMCP — not fee-for-service Medi-Cal — determines SNF and home health authorization.
- Common California MMCPs: Health Net Community Solutions, Molina Healthcare, L.A. Care (LA County), CalOptima (Orange County), Partnership HealthPlan (NorCal), Inland Empire Health Plan (IEHP), Anthem Blue Cross Medi-Cal, Blue Shield Promise.
- Confirm MMCP by calling Medi-Cal eligibility line: 1-800-541-5555 or medi-cal.ca.gov
- Medi-Cal concurrent review window is typically 1 business day.

Share of Cost (SOC):
- Medi-Cal beneficiaries with a share of cost must meet SOC before benefits activate.
- Always confirm SOC amount before securing SNF placement — this affects patient/family financial planning.

RCFE / Board & Care:
- Medi-Cal does NOT pay for room and board in RCFEs or Board & Care homes.
- RCFE is private pay or SSI/CAPI only. Clarify with families early to avoid misunderstandings.

IHSS:
- In-Home Supportive Services (IHSS) is a Medi-Cal benefit providing paid caregiver hours for patients discharging home.
- IHSS applications can be initiated from the hospital. Refer to county IHSS Public Authority.

Medicare 3-Day Rule:
- Medicare Part A covers SNF only after a 3-midnight qualifying INPATIENT stay — observation status does NOT count.
- Confirm inpatient status with utilization review before communicating SNF Medicare coverage to families.
- Medi-Cal fee-for-service (rare in managed care counties) does not require the 3-midnight rule.

California Patient Rights:
- AB 1195: Hospitals must provide discharge planning information including a list of post-acute providers.
- SB 1152: Written discharge planning policies required for homeless patients (clothing, transport, shelter connection). CDPH may audit.
- IMM (Important Message from Medicare): Required for all Medicare inpatients. Initial + 48-hour follow-up notice. Livanta QIO (CA): 1-888-815-0015.

---

DOMAIN C — CDPH / CMS COMPLIANCE & DENIAL MANAGEMENT

CMS Conditions of Participation flags:
- Confirm IMM delivered (initial + 48-hr notice) for Medicare patients
- Confirm patient informed of right to appeal discharge (Livanta QIO)
- Confirm discharge planning evaluation began within 24 hours of admission
- Confirm post-acute provider list given to patient with conflict-of-interest disclosure

When a denial is identified, provide:
- Denial type (medical necessity / level of care / auth not obtained / out-of-network)
- Appeal pathway:
  * Medicare Part A SNF denial → Livanta QIO expedited appeal within 24 hrs | 1-888-815-0015
  * Medi-Cal Managed Care denial → peer-to-peer review (24–72 hrs) → plan grievance → DMHC Help Center: 1-888-466-2219
  * Medicare Advantage denial → expedited redetermination (72-hr window) → QIC appeal

---

OUTPUT FORMAT

INSURANCE PROFILE:
| Field | Details |
|---|---|
| Primary payer | ... |
| Plan type | Medicare / Medi-Cal MMCP / Commercial / Dual-eligible |
| MMCP name (if Medi-Cal) | ... |
| Medicare status | Traditional / Advantage / Not applicable |
| Share of Cost | $[amount] / None / Pending confirmation |
| Medi-Cal eligibility confirmed | Yes / No / Pending |

BENEFIT SUMMARY:
| Service | Covered? | Limits | Co-pay / SOC | Notes |
|---|---|---|---|---|

PRIOR AUTHORIZATIONS NEEDED:
| Service | Auth Required | Documents Needed | Expected Turnaround | Status |
|---|---|---|---|---|

SNF ELIGIBILITY:
| Criterion | Status | Notes |
|---|---|---|
| 3-midnight qualifying inpatient stay | ✅ Met / ⏳ Pending / ❌ Not met (observation) | ... |
| Medicare Part A benefit days remaining | [#] days | ... |
| MMCP SNF authorization | ✅ Confirmed / ⏳ Pending | ... |

HOME HEALTH ELIGIBILITY:
Homebound status documented: [Yes / No / Needs verification]
Authorization status: [✅ Confirmed / ⏳ Pending]

DENIAL RISK FLAGS:
| Service | Risk Level | Reason | Recommended Action |
|---|---|---|---|

ESTIMATED PATIENT COST:
[Brief summary of likely out-of-pocket exposure including SOC if applicable]

COMPLIANCE FLAGS:
| Item | Status | Action Required |
|---|---|---|
| IMM delivered (initial) | ✅ / ⏳ / ❌ | ... |
| IMM delivered (48-hr notice) | ✅ / ⏳ / ❌ | ... |
| Discharge planning started within 24 hrs | ✅ / ⏳ / ❌ | ... |
| Post-acute provider list given | ✅ / ⏳ / ❌ | ... |

INSURANCE FLAGS:
[Urgent authorization needs, SOC issues, benefit exhaustion warnings, SB 1152 triggers, denial management items]"""

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
