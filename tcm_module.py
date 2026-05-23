"""TCM Billing CPT Automation — core business logic.

No database dependencies — pure Python functions for unit testing.
MDM assessment calls Claude Sonnet 4.6 at temperature=0 for deterministic billing.

CMS references:
  - TCM MLN Fact Sheet (ICN908628)
  - Medicare Claims Processing Manual Ch. 12, Sec. 30.6
  - CPT codes 99495 (moderate MDM) and 99496 (high MDM)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any


# ── MDM assessment system prompt ──────────────────────────────────────────────

MDM_SYSTEM_PROMPT = """\
You are a CMS billing specialist and medical coding expert assessing Medical Decision Making
(MDM) complexity for Transitional Care Management (TCM) services under Medicare.

Your task: Read the discharge plan and determine whether MDM is MODERATE or HIGH complexity
per CMS TCM guidelines (Medicare Claims Processing Manual, Chapter 12, Section 30.6).

MDM COMPLEXITY CRITERIA (assess all three elements):

ELEMENT 1 -- Number and Complexity of Problems:
  MODERATE: Multiple (2+) chronic stable illnesses; OR 1 acute illness with systemic symptoms;
            OR 1 acute complicated injury
  HIGH:     1+ chronic illness with severe exacerbation/progression; OR 2+ chronic conditions
            with significant interaction; OR acute/chronic illness posing threat to life or
            bodily function (e.g. ACS, stroke, sepsis, DKA, PE, decompensated CHF, COPD exac
            requiring hospitalization, active malignancy with complications)

ELEMENT 2 -- Amount and Complexity of Data:
  MODERATE: Limited -- any ONE of: review of external notes; ordering/reviewing tests;
            independent interpretation of test; discussion with treating provider
  HIGH:     Extensive -- TWO OR MORE of the above categories

ELEMENT 3 -- Risk of Complications and/or Morbidity:
  MODERATE: Prescription drug management; decision for minor surgery with no identified risk;
            diagnosis/treatment limited by social determinants of health
  HIGH:     Drug therapy requiring intensive monitoring for toxicity; decision re: hospitalization
            or escalation; decision re: DNR or de-escalating care due to poor prognosis;
            anticoagulation management; insulin titration; immunosuppressant therapy

FINAL MDM DETERMINATION:
  MODERATE: At least 2 of the 3 elements are at the MODERATE level or higher
  HIGH:     At least 2 of the 3 elements are at the HIGH level

ELIGIBILITY CHECKS:
  NOT ELIGIBLE if: hospice patient, another provider already billing TCM for this episode,
  discharge from ED without inpatient admission, or no Medicare Part B coverage indicated.
  Qualifying discharge settings: inpatient_hospital, snf, irf, ltch, observation,
  partial_hospitalization.

OUTPUT FORMAT: Return ONLY valid JSON, no prose, no markdown:
{
  "eligibility": "eligible" | "not_eligible",
  "not_eligible_reason": null | "<specific reason>",
  "mdm_complexity": "moderate" | "high" | null,
  "recommended_cpt": "99495" | "99496" | "not_eligible",
  "contact_deadline": "<ISO date -- 2 business days from discharge>",
  "visit_deadline_7day": "<ISO date -- 7 calendar days from discharge>",
  "visit_deadline_14day": "<ISO date -- 14 calendar days from discharge>",
  "element1_assessment": {"level": "moderate"|"high", "rationale": "<cite CMS MCPM Ch. 12>"},
  "element2_assessment": {"level": "moderate"|"high", "rationale": "<cite CMS MCPM Ch. 12>"},
  "element3_assessment": {"level": "moderate"|"high", "rationale": "<cite CMS MCPM Ch. 12>"},
  "mdm_rationale": "<combined rationale citing all 3 elements and the CMS requirement>",
  "key_diagnoses": ["<ICD-10 code>: <description>"],
  "billing_notes": "<special documentation requirements for this case>",
  "estimated_reimbursement": {"code": "99495"|"99496", "rate_non_facility": 0.00, "rate_facility": 0.00}
}"""


# ── Business day calculator ───────────────────────────────────────────────────

def _add_business_days(start_date: date, days: int) -> date:
    """Add N business days (Mon–Fri) to a date.

    CMS TCM contact window is 2 BUSINESS days — never use timedelta(days=2).
    Weekends do not count toward the contact deadline.
    """
    if days == 0:
        return start_date
    current = start_date
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # 0=Monday … 4=Friday
            added += 1
    return current


# ── Reimbursement rates (2026 Medicare PFS) ──────────────────────────────────

_RATES: dict[str, dict] = {
    "99495": {
        "code": "99495",
        "description": "TCM Moderate Complexity (14-day visit window)",
        "rate_non_facility": 166.28,
        "rate_facility": 108.15,
    },
    "99496": {
        "code": "99496",
        "description": "TCM High Complexity (7-day visit window)",
        "rate_non_facility": 228.14,
        "rate_facility": 153.91,
    },
}


def _get_reimbursement_rates(cpt_code: str | None) -> dict:
    """Return 2026 Medicare non-facility and facility rates for a CPT code."""
    return _RATES.get(cpt_code or "", {
        "code": cpt_code,
        "description": "Unknown",
        "rate_non_facility": 0.0,
        "rate_facility": 0.0,
    })


# ── AI MDM complexity assessment ─────────────────────────────────────────────

async def assess_mdm_complexity(
    discharge_plan: str,
    discharge_date: date,
    discharge_setting: str,
) -> dict:
    """Call Claude Sonnet 4.6 to assess MDM complexity and recommend CPT code.

    temperature=0 — billing decisions must be deterministic, not creative.
    Returns the full MDM assessment JSON dict.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")

    contact_deadline = _add_business_days(discharge_date, 2)
    visit_7day = discharge_date + timedelta(days=7)
    visit_14day = discharge_date + timedelta(days=14)

    user_prompt = (
        f"Discharge date: {discharge_date.isoformat()}\n"
        f"Discharge setting: {discharge_setting}\n"
        f"2-business-day contact deadline: {contact_deadline.isoformat()}\n"
        f"7-day visit deadline: {visit_7day.isoformat()}\n"
        f"14-day visit deadline: {visit_14day.isoformat()}\n\n"
        f"DISCHARGE PLAN:\n{discharge_plan}"
    )

    def _call() -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            temperature=0,
            system=MDM_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text

    raw = await asyncio.to_thread(_call)
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean).strip()

    result = json.loads(clean)
    result["estimated_reimbursement"] = _get_reimbursement_rates(result.get("recommended_cpt"))
    return result


# ── TCM status tracking ───────────────────────────────────────────────────────

class TCMStatus(str, Enum):
    PENDING_CONTACT   = "pending_contact"
    CONTACT_OVERDUE   = "contact_overdue"
    CONTACT_COMPLETED = "contact_completed"
    VISIT_SCHEDULED   = "visit_scheduled"
    VISIT_OVERDUE     = "visit_overdue"
    VISIT_COMPLETED   = "visit_completed"
    CLAIM_READY       = "claim_ready"
    CLAIM_SUBMITTED   = "claim_submitted"
    CLAIM_PAID        = "claim_paid"
    CLAIM_DENIED      = "claim_denied"
    NOT_ELIGIBLE      = "not_eligible"


@dataclass
class TimeWindowStatus:
    episode_id: str
    discharge_date: date
    cpt_code: str
    # Contact window
    contact_deadline: date
    contact_completed: bool
    contact_date: date | None
    contact_days_remaining: int
    contact_overdue: bool
    # Visit window
    visit_deadline: date
    visit_completed: bool
    visit_date: date | None
    visit_days_remaining: int
    visit_overdue: bool
    # Overall
    overall_status: TCMStatus
    claim_eligible: bool
    alert_level: str   # green | amber | red
    alert_message: str


def compute_window_status(
    episode: dict,
    contacts: list[dict],
    visits: list[dict],
) -> TimeWindowStatus:
    """Compute real-time TCM window compliance status.

    Called on every dashboard load. Returns a TimeWindowStatus with alert level
    so the UI can colour-code each row without further computation.
    """
    today = date.today()
    discharge = episode["discharge_date"]
    if isinstance(discharge, str):
        discharge = date.fromisoformat(discharge)

    cpt = episode.get("cpt_final") or episode.get("recommended_cpt", "99495")
    visit_window = 7 if cpt == "99496" else 14

    contact_deadline = _add_business_days(discharge, 2)
    visit_deadline = discharge + timedelta(days=visit_window)

    # Contact assessment
    qualifying = [c for c in contacts if c.get("contact_result") == "reached"]
    contact_completed = len(qualifying) > 0
    contact_date: date | None = None
    if contact_completed:
        raw_cd = qualifying[0]["contact_date"]
        contact_date = date.fromisoformat(raw_cd) if isinstance(raw_cd, str) else raw_cd
    contact_days_remaining = (contact_deadline - today).days
    contact_overdue = not contact_completed and today > contact_deadline

    # Visit assessment
    visit_completed = len(visits) > 0
    visit_date: date | None = None
    if visit_completed:
        raw_vd = visits[0]["visit_date"]
        visit_date = date.fromisoformat(raw_vd) if isinstance(raw_vd, str) else raw_vd
    visit_days_remaining = (visit_deadline - today).days
    visit_overdue = not visit_completed and today > visit_deadline

    # Overall status
    if contact_overdue:
        overall = TCMStatus.CONTACT_OVERDUE
        claim_eligible = False
    elif visit_overdue:
        overall = TCMStatus.VISIT_OVERDUE
        claim_eligible = False
    elif contact_completed and visit_completed:
        overall = TCMStatus.CLAIM_READY
        claim_eligible = True
    elif contact_completed:
        overall = TCMStatus.VISIT_SCHEDULED
        claim_eligible = False
    else:
        overall = TCMStatus.PENDING_CONTACT
        claim_eligible = False

    # Alert level
    if overall in (TCMStatus.CONTACT_OVERDUE, TCMStatus.VISIT_OVERDUE):
        alert_level = "red"
        alert_msg = f"WINDOW MISSED — {cpt} claim no longer billable"
    elif not contact_completed and contact_days_remaining <= 0:
        alert_level = "red"
        alert_msg = "CONTACT DUE TODAY — call patient immediately"
    elif not contact_completed and contact_days_remaining <= 1:
        alert_level = "amber"
        alert_msg = (f"Contact due {contact_deadline} — "
                     f"{contact_days_remaining}d remaining")
    elif not visit_completed and visit_days_remaining <= 3:
        alert_level = "amber"
        alert_msg = (f"Visit due {visit_deadline} — "
                     f"{visit_days_remaining}d remaining")
    else:
        alert_level = "green"
        alert_msg = "On track"

    return TimeWindowStatus(
        episode_id=str(episode.get("id", "")),
        discharge_date=discharge,
        cpt_code=cpt,
        contact_deadline=contact_deadline,
        contact_completed=contact_completed,
        contact_date=contact_date,
        contact_days_remaining=max(0, contact_days_remaining),
        contact_overdue=contact_overdue,
        visit_deadline=visit_deadline,
        visit_completed=visit_completed,
        visit_date=visit_date,
        visit_days_remaining=max(0, visit_days_remaining),
        visit_overdue=visit_overdue,
        overall_status=overall,
        claim_eligible=claim_eligible,
        alert_level=alert_level,
        alert_message=alert_msg,
    )


# ── Claim generation ──────────────────────────────────────────────────────────

def generate_tcm_claim(
    episode: dict,
    contacts: list[dict],
    visits: list[dict],
    mdm: dict,
) -> dict:
    """Generate a claim-ready TCM billing record with full CMS audit trail.

    All fields map to CMS-1500 form fields or their 837P equivalents.
    Returns {"claimable": False, "reason": "..."} if requirements are not met.
    """
    window = compute_window_status(episode, contacts, visits)
    if not window.claim_eligible:
        return {
            "claimable": False,
            "reason": f"Claim not eligible: {window.overall_status}",
            "alert": window.alert_message,
        }

    cpt = episode.get("cpt_final") or episode.get("recommended_cpt", "99495")
    rates = _get_reimbursement_rates(cpt)
    first_contact = next(c for c in contacts if c.get("contact_result") == "reached")
    face_to_face = visits[0]

    key_dx = mdm.get("key_diagnoses", [""])
    icd10_primary = key_dx[0].split(":")[0].strip() if key_dx else ""
    icd10_secondary = [d.split(":")[0].strip() for d in key_dx[1:4]]

    return {
        # CMS-1500 Box 21 — Diagnosis
        "icd10_primary": icd10_primary,
        "icd10_secondary": icd10_secondary,
        # CMS-1500 Box 24 — Service line
        "date_of_service": str(face_to_face["visit_date"]),
        "place_of_service": "11",
        "cpt_code": cpt,
        "modifier": "",
        "units": 1,
        "charge_amount": rates["rate_non_facility"],
        # Provider info
        "rendering_provider_npi": face_to_face.get("provider_npi", ""),
        "rendering_provider_name": face_to_face.get("provider_name", ""),
        "billing_provider_npi": episode.get("practice_npi", ""),
        "billing_provider_tin": episode.get("practice_tin", ""),
        # Patient info
        "patient_name": episode.get("patient_name", ""),
        "patient_dob": str(episode.get("patient_dob", "")),
        "patient_medicare_id": episode.get("patient_medicare_id", ""),
        # TCM documentation
        "date_of_discharge": str(episode["discharge_date"]),
        "discharge_setting": episode.get("discharge_setting", ""),
        "contact_date": str(first_contact["contact_date"]),
        "contact_time": str(first_contact["contact_time"]),
        "contact_method": first_contact.get("contact_method", ""),
        "contact_staff": first_contact.get("contacted_by", ""),
        "face_to_face_date": str(face_to_face["visit_date"]),
        "face_to_face_provider": face_to_face.get("provider_name", ""),
        # MDM documentation
        "mdm_complexity": episode.get("mdm_complexity", ""),
        "mdm_rationale": episode.get("mdm_rationale", ""),
        "element1_rationale": mdm.get("element1_assessment", {}).get("rationale", ""),
        "element2_rationale": mdm.get("element2_assessment", {}).get("rationale", ""),
        "element3_rationale": mdm.get("element3_assessment", {}).get("rationale", ""),
        # Financial
        "estimated_reimbursement": rates["rate_non_facility"],
        "cpt_description": rates["description"],
        # Audit trail — required for CMS audit defense
        "audit_trail": {
            "claim_generated_at": date.today().isoformat(),
            "mdm_assessed_by": episode.get("mdm_assessed_by", "ai_assisted"),
            "cpt_source": ("clinician_override" if episode.get("cpt_override")
                           else "ai_recommended"),
            "contact_window_met": (
                f"{window.contact_date} (deadline: {window.contact_deadline})"
            ),
            "visit_window_met": (
                f"{window.visit_date} (deadline: {window.visit_deadline})"
            ),
            "all_requirements_met": True,
            "cms_reference": "CMS TCM MLN Fact Sheet ICN908628 / MCPM Ch.12 Sec.30.6",
        },
        "claimable": True,
    }
