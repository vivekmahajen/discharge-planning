"""
Referral delivery service.
Supports: Documo fax, CarePort (future, activates when CAREPORT_API_KEY set), manual.

Security:
- Never logs referral_html (PHI)
- Logs only: referral_id, facility_ccn, channel, success/fail, reference_id
- CarePort: no-op stub unless CAREPORT_API_KEY is set; never hard-codes endpoint
- API keys are loaded from environment at call time, never stored in DB
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import httpx

_log = logging.getLogger(__name__)

# These are intentionally NOT module-level constants populated at import time.
# They are always read fresh from os.environ at delivery call time so that
# environment changes (e.g. secret injection) are picked up without restart.
DOCUMO_API_KEY = None  # loaded from env at delivery time, not stored in DB
CAREPORT_API_KEY = None  # idem


async def send_via_fax(
    referral_id: int,
    facility_fax: str,
    packet_html: str,
    facility_ccn: str,
) -> dict:
    """Send referral via Documo fax API.

    Returns a result dict: {success: bool, reference_id: str|None, error: str|None}

    Security:
    - packet_html is NEVER logged (it contains PHI)
    - Only referral_id, facility_ccn, channel, success/fail, and reference_id are logged
    - DOCUMO_API_KEY is read from os.environ at call time
    """
    api_key = os.environ.get("DOCUMO_API_KEY")
    if not api_key:
        _log.warning(
            "fax_send_skipped referral_id=%s facility_ccn=%s reason=DOCUMO_API_KEY_not_configured",
            referral_id, facility_ccn,
        )
        return {
            "success": False,
            "reference_id": None,
            "error": "DOCUMO_API_KEY not configured",
            "channel": "fax",
        }

    try:
        # Encode the HTML referral packet as a file attachment
        html_bytes = packet_html.encode("utf-8")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.documo.com/v1/faxes",
                headers={"Authorization": f"Basic {api_key}"},
                data={
                    "to": facility_fax,
                    "subject": f"Post-Acute Care Referral (ID: {referral_id})",
                },
                files={
                    "file": ("referral_packet.html", html_bytes, "text/html"),
                },
            )
            response.raise_for_status()
            result_json = response.json()
            reference_id = (
                result_json.get("jobId")
                or result_json.get("id")
                or result_json.get("faxId")
                or str(result_json.get("fax_id", ""))
                or None
            )
            _log.info(
                "fax_sent referral_id=%s facility_ccn=%s channel=fax success=True reference_id=%s",
                referral_id, facility_ccn, reference_id,
            )
            return {"success": True, "reference_id": reference_id, "error": None, "channel": "fax"}

    except httpx.HTTPStatusError as exc:
        error_msg = f"Documo HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        _log.error(
            "fax_failed referral_id=%s facility_ccn=%s channel=fax success=False error=%s",
            referral_id, facility_ccn, error_msg,
        )
        return {"success": False, "reference_id": None, "error": error_msg, "channel": "fax"}

    except Exception as exc:
        error_msg = str(exc)
        _log.error(
            "fax_failed referral_id=%s facility_ccn=%s channel=fax success=False error=%s",
            referral_id, facility_ccn, error_msg,
        )
        return {"success": False, "reference_id": None, "error": error_msg, "channel": "fax"}


async def send_via_careport(
    referral_id: int,
    fhir_service_request: dict,
    facility_ccn: str,
) -> dict:
    """CarePort delivery — activates automatically when CAREPORT_API_KEY is set.

    When key is not set: returns a not-activated stub response.
    When key IS set: POSTs the FHIR ServiceRequest JSON to the endpoint configured
    via CAREPORT_API_ENDPOINT env var.

    Security:
    - Never hard-codes the CarePort API endpoint; endpoint must come from env var
    - CAREPORT_API_KEY is read from os.environ at call time, not stored in DB
    - Does not attempt any HTTP call unless both key AND endpoint are configured
    """
    api_key = os.environ.get("CAREPORT_API_KEY")
    if not api_key:
        _log.info(
            "careport_skipped referral_id=%s facility_ccn=%s reason=CAREPORT_API_KEY_not_set",
            referral_id, facility_ccn,
        )
        return {
            "success": False,
            "reference_id": None,
            "error": "CarePort integration not yet activated",
            "channel": "careport",
        }

    api_endpoint = os.environ.get("CAREPORT_API_ENDPOINT")
    if not api_endpoint:
        _log.warning(
            "careport_skipped referral_id=%s facility_ccn=%s reason=CAREPORT_API_ENDPOINT_not_set",
            referral_id, facility_ccn,
        )
        return {
            "success": False,
            "reference_id": None,
            "error": "CAREPORT_API_ENDPOINT not configured",
            "channel": "careport",
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                api_endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/fhir+json",
                    "Accept": "application/fhir+json",
                },
                content=json.dumps(fhir_service_request).encode("utf-8"),
            )
            response.raise_for_status()
            result_json = response.json()
            reference_id = (
                result_json.get("id")
                or result_json.get("referralId")
                or result_json.get("reference_id")
                or None
            )
            _log.info(
                "careport_sent referral_id=%s facility_ccn=%s channel=careport success=True reference_id=%s",
                referral_id, facility_ccn, reference_id,
            )
            return {
                "success": True,
                "reference_id": reference_id,
                "error": None,
                "channel": "careport",
            }

    except httpx.HTTPStatusError as exc:
        error_msg = f"CarePort HTTP {exc.response.status_code}: {exc.response.text[:200]}"
        _log.error(
            "careport_failed referral_id=%s facility_ccn=%s channel=careport success=False error=%s",
            referral_id, facility_ccn, error_msg,
        )
        return {
            "success": False,
            "reference_id": None,
            "error": error_msg,
            "channel": "careport",
        }

    except Exception as exc:
        error_msg = str(exc)
        _log.error(
            "careport_failed referral_id=%s facility_ccn=%s channel=careport success=False error=%s",
            referral_id, facility_ccn, error_msg,
        )
        return {
            "success": False,
            "reference_id": None,
            "error": error_msg,
            "channel": "careport",
        }


async def send_via_direct(
    referral_id: int,
    direct_address: str,
    packet_html: str,
    facility_ccn: str,
) -> dict:
    """Direct Secure Messaging stub.

    Full Direct Secure Messaging requires a Health Information Service Provider (HISP)
    integration (e.g. Surescripts, CommonWell, or a self-hosted HISP). This stub returns
    instructions to the caller rather than attempting a send.

    Returns a result dict indicating that manual action or HISP configuration is needed.
    """
    _log.info(
        "direct_skipped referral_id=%s facility_ccn=%s channel=direct reason=HISP_not_configured",
        referral_id, facility_ccn,
    )
    return {
        "success": False,
        "reference_id": None,
        "error": "Direct Secure Messaging requires HISP configuration",
        "channel": "direct",
        "instructions": (
            f"To send this referral via Direct Secure Messaging, forward the referral packet "
            f"to {direct_address} using your organization's HISP-connected Direct client. "
            "Contact your HIT team to configure automated Direct delivery."
        ),
    }


def get_delivery_status() -> dict:
    """Return dict of which delivery channels are currently configured/active.

    Keys:
    - fax: True if DOCUMO_API_KEY is set
    - careport: True if CAREPORT_API_KEY is set
    - direct: Always False (requires HISP integration not yet implemented)
    - careport_endpoint_configured: True if CAREPORT_API_ENDPOINT is set
    """
    return {
        "fax": bool(os.environ.get("DOCUMO_API_KEY")),
        "careport": bool(os.environ.get("CAREPORT_API_KEY")),
        "direct": False,
        "careport_endpoint_configured": bool(os.environ.get("CAREPORT_API_ENDPOINT")),
    }
