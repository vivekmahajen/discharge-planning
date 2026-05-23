"""Async FHIR R4 HTTP client.

Fetches all Phase 1 resources in parallel using asyncio.gather with
return_exceptions=True — a single failed resource never blocks plan generation.
Implements exponential backoff for 429 / 5xx per spec section 7.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from .normalizers import (
    normalize_allergies,
    normalize_appointments,
    normalize_care_team,
    normalize_conditions,
    normalize_documents,
    normalize_medications,
    normalize_patient,
)
from .schemas import FetchWarning, PatientBundle

logger = logging.getLogger(__name__)

# Retry delays (seconds) for 429 / 5xx — spec section 7
_RETRY_DELAYS = [1.0, 2.0, 4.0, 8.0]

# LOINC code for discharge summary documents
_DISCHARGE_SUMMARY_LOINC = "34133-9"


class FHIRAuthError(Exception):
    """HTTP 401 — token expired or invalid."""


class FHIRForbiddenError(Exception):
    """HTTP 403 — scope not granted or app not approved for this resource."""


class FHIRServerError(Exception):
    """HTTP 5xx or max retries exceeded."""


class FHIRNetworkError(Exception):
    """Network / timeout error."""


class FHIRClient:
    """Authenticated FHIR R4 client for a single patient session.

    Usage:
        client = FHIRClient(fhir_base="https://...", access_token="...", ehr="epic")
        bundle = await client.fetch_patient_bundle(patient_id)
    """

    def __init__(self, fhir_base: str, access_token: str, ehr: str = ""):
        self.fhir_base = fhir_base.rstrip("/")
        self.access_token = access_token
        self.ehr = ehr
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/fhir+json",
        }

    async def _get(self, path: str) -> dict:
        """Single FHIR GET with retry for 429/5xx. Raises typed exceptions on failure."""
        url = self.fhir_base + path
        last_exc: Optional[Exception] = None

        for attempt, delay in enumerate([0.0] + _RETRY_DELAYS):
            if delay:
                await asyncio.sleep(delay)
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    resp = await http.get(url, headers=self._headers)

                if resp.status_code == 200:
                    return resp.json()

                if resp.status_code == 401:
                    raise FHIRAuthError("Token expired or invalid")

                if resp.status_code == 403:
                    resource_type = path.lstrip("/").split("?")[0].split("/")[0]
                    raise FHIRForbiddenError(
                        f"This EHR has not approved access to {resource_type}. "
                        "Contact your IT admin."
                    )

                if resp.status_code == 404:
                    # Resource does not exist for this patient — treat as empty bundle
                    return {"resourceType": "Bundle", "total": 0, "entry": []}

                if resp.status_code == 429 or resp.status_code >= 500:
                    resource_label = path.lstrip("/").split("?")[0].split("/")[0]
                    logger.warning(
                        "FHIR %s HTTP %d, attempt %d/%d",
                        resource_label,
                        resp.status_code,
                        attempt + 1,
                        len(_RETRY_DELAYS) + 1,
                    )
                    last_exc = FHIRServerError(
                        f"EHR returned {resp.status_code} for {resource_label}"
                    )
                    continue  # retry

                resp.raise_for_status()

            except (FHIRAuthError, FHIRForbiddenError):
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                resource_label = path.lstrip("/").split("?")[0].split("/")[0]
                logger.warning(
                    "FHIR %s network error attempt %d: %s",
                    resource_label,
                    attempt + 1,
                    type(exc).__name__,
                )
                last_exc = FHIRNetworkError(str(exc))
                continue

        raise last_exc or FHIRServerError(f"Max retries exceeded for {path}")

    async def fetch_patient_bundle(self, patient_id: str) -> PatientBundle:
        """Fetch all Phase 1 FHIR resources in parallel and return a normalized bundle.

        Uses asyncio.gather(return_exceptions=True) so a single failed resource
        produces a FetchWarning rather than aborting the entire fetch.
        """
        resource_names = [
            "Patient",
            "Condition",
            "MedicationRequest",
            "AllergyIntolerance",
            "Appointment",
            "CareTeam",
            "DocumentReference",
        ]
        paths = [
            f"/Patient/{patient_id}",
            f"/Condition?patient={patient_id}&clinical-status=active",
            f"/MedicationRequest?patient={patient_id}&status=active",
            f"/AllergyIntolerance?patient={patient_id}&clinical-status=active",
            f"/Appointment?patient={patient_id}&status=booked",
            f"/CareTeam?patient={patient_id}&status=active",
            f"/DocumentReference?patient={patient_id}&type={_DISCHARGE_SUMMARY_LOINC}",
        ]

        # Log fetch initiation — resource types only, no PHI
        logger.info(
            "FHIR bundle fetch start: ehr=%s resources=%s",
            self.ehr,
            resource_names,
        )

        results = await asyncio.gather(
            *[self._get(p) for p in paths],
            return_exceptions=True,
        )

        warnings: list[FetchWarning] = []

        def unwrap(idx: int) -> Optional[dict]:
            result = results[idx]
            if isinstance(result, Exception):
                warnings.append(
                    FetchWarning(
                        resource=resource_names[idx],
                        error=str(result),
                    )
                )
                return None
            return result

        patient_raw = unwrap(0)
        conditions_raw = unwrap(1)
        medications_raw = unwrap(2)
        allergies_raw = unwrap(3)
        appointments_raw = unwrap(4)
        care_team_raw = unwrap(5)
        docs_raw = unwrap(6)

        # Audit log — counts only, never PHI values
        counts = {
            "Condition": len((conditions_raw or {}).get("entry", [])),
            "MedicationRequest": len((medications_raw or {}).get("entry", [])),
            "AllergyIntolerance": len((allergies_raw or {}).get("entry", [])),
            "Appointment": len((appointments_raw or {}).get("entry", [])),
            "CareTeam": len((care_team_raw or {}).get("entry", [])),
            "DocumentReference": len((docs_raw or {}).get("entry", [])),
        }
        logger.info(
            "FHIR bundle fetch complete: ehr=%s counts=%s warnings=%d",
            self.ehr,
            counts,
            len(warnings),
        )

        return PatientBundle(
            patient=normalize_patient(patient_raw),
            conditions=normalize_conditions(conditions_raw) if conditions_raw else [],
            medications=normalize_medications(medications_raw) if medications_raw else [],
            allergies=normalize_allergies(allergies_raw) if allergies_raw else [],
            appointments=normalize_appointments(appointments_raw) if appointments_raw else [],
            care_team=normalize_care_team(care_team_raw) if care_team_raw else [],
            documents=normalize_documents(docs_raw) if docs_raw else [],
            fetch_warnings=warnings,
            fhir_base=self.fhir_base,
            ehr=self.ehr,
        )
