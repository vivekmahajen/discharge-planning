"""EHR-specific SMART on FHIR configuration.

Auth/token endpoints are derived from each EHR's known URL pattern or from
env var overrides. SMART discovery (/.well-known/smart-configuration) is only
used for custom hospital instances where the base URL has been overridden.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

# Phase 1 read-only scopes for standalone (patient-facing) launch.
# Excludes launch/patient (EHR-embedded only) and offline_access (requires
# special app-level approval in Epic) to work with standard app registrations.
FHIR_SCOPES_PHASE1 = [
    "patient/Patient.read",
    "patient/Condition.read",
    "patient/MedicationRequest.read",
    "patient/AllergyIntolerance.read",
    "patient/Appointment.read",
    "patient/CareTeam.read",
    "patient/DocumentReference.read",
    "openid",
]

# athenahealth uses the same standalone scope set.
FHIR_SCOPES_ATHENA = FHIR_SCOPES_PHASE1[:]


@dataclass
class EHRConfig:
    name: str
    display_name: str
    fhir_base_url: str
    client_id: str
    client_secret: Optional[str]    # None for public (PKCE-only) clients
    is_public_client: bool          # True = PKCE required, no client_secret
    scopes: list[str]
    # Override SMART discovery when endpoints are known at deploy time.
    auth_endpoint_override: Optional[str] = None
    token_endpoint_override: Optional[str] = None
    # "v1" = no PKCE, no aud param (Epic sandbox is locked to SMART v1)
    smart_version: str = "v2"


def _epic_oauth_root(fhir_base: str) -> str:
    """Derive the Epic OAuth root from the FHIR base URL.

    Epic FHIR base:  https://host/path/api/FHIR/R4
    Epic OAuth root: https://host/path
    Auth endpoint:   https://host/path/oauth2/authorize
    Token endpoint:  https://host/path/oauth2/token
    """
    return fhir_base.rstrip("/").removesuffix("/api/FHIR/R4")


def _build_registry() -> dict[str, EHRConfig]:
    epic_fhir_base = os.getenv(
        "FHIR_BASE_URL_EPIC",
        "https://fhir.epic.com/interconnect-fhir-oauth/api/FHIR/R4",
    )
    _epic_root = _epic_oauth_root(epic_fhir_base)

    return {
        "epic": EHRConfig(
            name="epic",
            display_name="Epic",
            fhir_base_url=epic_fhir_base,
            client_id=os.getenv("FHIR_CLIENT_ID_EPIC", ""),
            client_secret=None,
            is_public_client=True,
            scopes=FHIR_SCOPES_PHASE1,
            # Epic's app registration exposes SMART v1 for these sandbox/standalone
            # patient apps (v2 cannot be enabled), so match it: no PKCE. Override
            # with EPIC_SMART_VERSION=v2 if a given Epic app supports v2.
            smart_version=os.getenv("EPIC_SMART_VERSION", "v1"),
            # Derive from URL pattern — avoids SMART discovery which Epic blocks
            # server-side. Override with EPIC_AUTH_ENDPOINT for non-standard instances.
            auth_endpoint_override=os.getenv(
                "EPIC_AUTH_ENDPOINT", f"{_epic_root}/oauth2/authorize"
            ),
            token_endpoint_override=os.getenv(
                "EPIC_TOKEN_ENDPOINT", f"{_epic_root}/oauth2/token"
            ),
        ),
        "cerner": EHRConfig(
            name="cerner",
            display_name="Oracle Health (Cerner)",
            fhir_base_url=os.getenv(
                "FHIR_BASE_URL_CERNER",
                "https://fhir-ehr-code.cerner.com/r4/ec2458f2-1e24-41c8-b71b-0e701af7583d",
            ),
            client_id=os.getenv("FHIR_CLIENT_ID_CERNER", ""),
            client_secret=None,
            is_public_client=True,
            scopes=FHIR_SCOPES_PHASE1,
            auth_endpoint_override=os.getenv("CERNER_AUTH_ENDPOINT"),
            token_endpoint_override=os.getenv("CERNER_TOKEN_ENDPOINT"),
        ),
        "athena": EHRConfig(
            name="athena",
            display_name="athenahealth",
            fhir_base_url=os.getenv(
                "FHIR_BASE_URL_ATHENA",
                "https://api.preview.platform.athenahealth.com/fhir/r4",
            ),
            client_id=os.getenv("FHIR_CLIENT_ID_ATHENA", ""),
            client_secret=os.getenv("FHIR_CLIENT_SECRET_ATHENA"),
            is_public_client=False,
            scopes=FHIR_SCOPES_ATHENA,
            auth_endpoint_override=os.getenv("ATHENA_AUTH_ENDPOINT"),
            token_endpoint_override=os.getenv("ATHENA_TOKEN_ENDPOINT"),
        ),
    }


def get_ehr_config(name: str) -> EHRConfig:
    registry = _build_registry()
    if name not in registry:
        raise ValueError(f"Unknown EHR: {name!r}. Supported: {sorted(registry)}")
    return registry[name]


def list_ehrs() -> list[str]:
    return sorted(_build_registry())


def list_ehr_display() -> list[dict]:
    return [
        {"name": k, "display_name": v.display_name}
        for k, v in _build_registry().items()
    ]


# Host fragments that indicate a vendor sandbox/test endpoint (not production).
_SANDBOX_HINTS = (
    "fhir.epic.com",
    "interconnect-fhir-oauth",
    "fhir-ehr-code.cerner.com",
    "preview.platform.athenahealth.com",
    "sandbox",
)


def config_status() -> list[dict]:
    """Safe, read-only view of EHR configuration for diagnostics. Reports only
    booleans + resolved (non-secret) URLs — never client_id/secret values."""
    out = []
    for _name, c in _build_registry().items():
        base = c.fhir_base_url or ""
        configured = bool(c.client_id) and (c.is_public_client or bool(c.client_secret))
        out.append({
            "name": c.name,
            "display_name": c.display_name,
            "configured": configured,
            "client_id_set": bool(c.client_id),
            "requires_client_secret": not c.is_public_client,
            "client_secret_set": bool(c.client_secret),
            "fhir_base_url": base,
            "auth_endpoint": c.auth_endpoint_override or "(SMART discovery / URL-derived)",
            "token_endpoint": c.token_endpoint_override or "(SMART discovery / URL-derived)",
            "smart_version": c.smart_version,
            "is_sandbox_default": any(h in base for h in _SANDBOX_HINTS),
        })
    return out
