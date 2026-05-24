"""Real-Time Insurance Eligibility Verification service."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

_log = logging.getLogger(__name__)

STEDI_API_KEY = os.getenv("STEDI_API_KEY", "")

KNOWN_PAYERS: dict[str, dict] = {
    "CMS": {
        "payer_id": "CMS",
        "name": "Medicare",
        "aliases": ["medicare", "cms", "medicare traditional", "medicare fee for service", "medicare part a", "medicare part b"],
    },
    "CAMC": {
        "payer_id": "CAMC",
        "name": "Medi-Cal",
        "aliases": ["medi-cal", "medicaid", "medi cal", "medical california", "dhcs", "camc"],
    },
    "60054": {
        "payer_id": "60054",
        "name": "Aetna",
        "aliases": ["aetna"],
    },
    "87726": {
        "payer_id": "87726",
        "name": "UnitedHealthcare",
        "aliases": ["unitedhealthcare", "united health", "uhc", "united healthcare", "optum"],
    },
    "62308": {
        "payer_id": "62308",
        "name": "Cigna",
        "aliases": ["cigna", "cigna healthcare"],
    },
    "61101": {
        "payer_id": "61101",
        "name": "Humana",
        "aliases": ["humana"],
    },
    "ANTCA": {
        "payer_id": "ANTCA",
        "name": "Anthem Blue Cross CA",
        "aliases": ["anthem", "anthem blue cross", "blue cross", "anthem ca", "wellpoint"],
    },
    "CA600": {
        "payer_id": "CA600",
        "name": "Health Net",
        "aliases": ["health net", "healthnet"],
    },
    "94270": {
        "payer_id": "94270",
        "name": "Kaiser Permanente",
        "aliases": ["kaiser", "kaiser permanente", "kp"],
    },
    "37602": {
        "payer_id": "37602",
        "name": "Molina Healthcare",
        "aliases": ["molina", "molina healthcare"],
    },
    "LACAR": {
        "payer_id": "LACAR",
        "name": "L.A. Care",
        "aliases": ["la care", "l.a. care", "lacare", "los angeles care"],
    },
    "IEHPL": {
        "payer_id": "IEHPL",
        "name": "IEHP",
        "aliases": ["iehp", "inland empire health plan", "iehpl"],
    },
    "CALOP": {
        "payer_id": "CALOP",
        "name": "CalOptima",
        "aliases": ["caloptima", "cal optima"],
    },
    "PTNSH": {
        "payer_id": "PTNSH",
        "name": "Partnership HealthPlan",
        "aliases": ["partnership healthplan", "partnership health plan", "php", "ptnsh"],
    },
}


@dataclasses.dataclass
class EligibilityResult:
    is_eligible: bool
    payer_id: str
    payer_name: str
    plan_name: str = ""
    plan_type: str = ""
    coverage_start: str = ""
    coverage_end: str = ""
    group_number: str = ""
    deductible_individual: Optional[float] = None
    deductible_met: Optional[float] = None
    out_of_pocket_max: Optional[float] = None
    out_of_pocket_met: Optional[float] = None
    copay_specialist: Optional[float] = None
    coinsurance_pct: Optional[float] = None
    snf_days_remaining: Optional[int] = None
    home_health_authorized: Optional[bool] = None
    prior_auth_required: bool = False
    source: str = "live"
    checked_at: str = ""
    error_message: str = ""


def detect_payer_id(payer_name: str) -> tuple[str, str]:
    lower = payer_name.lower()
    for key, info in KNOWN_PAYERS.items():
        for alias in info["aliases"]:
            if alias in lower:
                return (info["payer_id"], info["name"])
    return ("UNKNOWN", payer_name)


def _make_cache_key(member_id: str, payer_id: str, date_str: str) -> str:
    raw = f"{member_id}|{payer_id}|{date_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _parse_date(raw: str) -> str:
    if len(raw) == 8:
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw


def parse_271_response(response: dict) -> EligibilityResult:
    payer = response.get("payer", {})
    subscriber = response.get("subscriber", {})

    payer_name = payer.get("organizationName", "")
    plan_name = payer.get("planName", "")
    plan_code = payer.get("planCode", "")
    member_id = subscriber.get("memberId", "")
    group_number = subscriber.get("groupNumber", "")

    is_eligible = False
    coverage_start = ""
    coverage_end = ""
    deductible_individual: Optional[float] = None
    deductible_met: Optional[float] = None
    out_of_pocket_max: Optional[float] = None
    out_of_pocket_met: Optional[float] = None
    copay_specialist: Optional[float] = None
    coinsurance_pct: Optional[float] = None
    snf_days_remaining: Optional[int] = None
    prior_auth_required = False

    coverages = subscriber.get("coverages", [])
    for coverage in coverages:
        eligibility_code = coverage.get("eligibilityCode", "")
        eligibility_description = coverage.get("eligibilityDescription", "")
        service_type_code = coverage.get("serviceTypeCode", "")

        if eligibility_code == "1":
            is_eligible = True
        elif eligibility_code in ("6", "7"):
            pass

        if "prior authorization" in eligibility_description.lower():
            prior_auth_required = True

        benefit_summary = coverage.get("benefitSummary", {})
        if benefit_summary:
            start_raw = benefit_summary.get("startDate", "")
            end_raw = benefit_summary.get("endDate", "")
            if start_raw:
                coverage_start = _parse_date(start_raw)
            if end_raw:
                coverage_end = _parse_date(end_raw)

            ded = benefit_summary.get("deductibleInNetwork", {})
            if ded and "amount" in ded:
                deductible_individual = float(ded["amount"])

            ded_met = benefit_summary.get("deductibleMetInNetwork", {})
            if ded_met and "amount" in ded_met:
                deductible_met = float(ded_met["amount"])

            oop = benefit_summary.get("outOfPocketInNetwork", {})
            if oop and "amount" in oop:
                out_of_pocket_max = float(oop["amount"])

            oop_met = benefit_summary.get("outOfPocketMetInNetwork", {})
            if oop_met and "amount" in oop_met:
                out_of_pocket_met = float(oop_met["amount"])

        if service_type_code == "48":
            benefit_details = coverage.get("benefitDetails", [])
            for detail in benefit_details:
                code = detail.get("code", "")
                amount = detail.get("amount")
                if code == "C" and amount is not None:
                    copay_specialist = float(amount)

    return EligibilityResult(
        is_eligible=is_eligible,
        payer_id="",
        payer_name=payer_name,
        plan_name=plan_name,
        plan_type=plan_code,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        group_number=group_number,
        deductible_individual=deductible_individual,
        deductible_met=deductible_met,
        out_of_pocket_max=out_of_pocket_max,
        out_of_pocket_met=out_of_pocket_met,
        copay_specialist=copay_specialist,
        coinsurance_pct=coinsurance_pct,
        snf_days_remaining=snf_days_remaining,
        prior_auth_required=prior_auth_required,
        source="live",
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


def get_mock_result(payer_id: str, payer_name: str) -> EligibilityResult:
    now = datetime.now(timezone.utc).isoformat()
    if payer_id == "CMS":
        return EligibilityResult(
            is_eligible=True,
            payer_id=payer_id,
            payer_name=payer_name,
            plan_name="Medicare Part A & B",
            plan_type="Medicare Traditional",
            deductible_individual=1600.0,
            deductible_met=800.0,
            snf_days_remaining=87,
            prior_auth_required=False,
            coverage_start="2024-01-01",
            source="mock",
            checked_at=now,
        )
    if payer_id == "CAMC":
        return EligibilityResult(
            is_eligible=True,
            payer_id=payer_id,
            payer_name=payer_name,
            plan_name="Medi-Cal Managed Care",
            plan_type="Medicaid",
            snf_days_remaining=None,
            prior_auth_required=True,
            coverage_start="2023-07-01",
            source="mock",
            checked_at=now,
        )
    return EligibilityResult(
        is_eligible=True,
        payer_id=payer_id,
        payer_name=payer_name,
        plan_name=f"{payer_name} PPO",
        deductible_individual=3000.0,
        deductible_met=1200.0,
        out_of_pocket_max=6000.0,
        prior_auth_required=True,
        source="mock",
        checked_at=now,
    )


async def check_eligibility(
    member_id: str,
    patient_first_name: str,
    patient_last_name: str,
    date_of_birth: str,
    payer_id: str,
    npi: str,
) -> EligibilityResult:
    payload = {
        "controlNumber": "000000001",
        "tradingPartnerServiceId": payer_id,
        "provider": {"organizationName": "DischargeIQ", "npi": npi},
        "subscriber": {
            "memberId": member_id,
            "firstName": patient_first_name.upper(),
            "lastName": patient_last_name.upper(),
            "dateOfBirth": date_of_birth.replace("-", ""),
        },
        "encounter": {"serviceTypeCodes": ["30"]},
    }

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            "https://healthcare.us.stedi.com/2024-04-01/change/medicalnetwork/eligibility/v3",
            json=payload,
            headers={"Authorization": f"Key {STEDI_API_KEY}"},
        )

    duration_ms = int((time.monotonic() - t0) * 1000)

    if response.status_code == 422:
        raise ValueError("Invalid eligibility request — check member ID and payer ID")
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"Stedi API error: {response.status_code}")

    result = parse_271_response(response.json())
    result.payer_id = payer_id

    _log.info(json.dumps({
        "event": "eligibility_check",
        "payer_id": payer_id,
        "is_eligible": result.is_eligible,
        "source": "live",
        "duration_ms": duration_ms,
    }))

    return result
