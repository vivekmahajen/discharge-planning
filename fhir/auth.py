"""SMART on FHIR v2 authentication helpers.

Handles PKCE generation, state cookies, token exchange, and silent token refresh.
Tokens are stored in signed HttpOnly cookies — PHI is never stored here.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
import time
from typing import Optional

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

# Cookie names
FHIR_STATE_COOKIE = "fhir_auth_state"
FHIR_SESSION_COOKIE = "fhir_session"

# TTLs
FHIR_STATE_TTL = 300        # 5 minutes — covers the auth redirect round-trip
FHIR_SESSION_TTL = 60 * 60 * 8  # 8 hours — one clinical shift
TOKEN_REFRESH_BUFFER = 60   # refresh this many seconds before expiry

# Use a dedicated signing key for FHIR sessions, falling back to the app secret.
_FHIR_SECRET = os.getenv("FHIR_SESSION_SECRET") or os.getenv(
    "SECRET_KEY", "discharge-planning-fhir-dev-change-in-prod"
)
_serializer = URLSafeTimedSerializer(_FHIR_SECRET, salt="fhir-v1")


# ── PKCE ─────────────────────────────────────────────────────────────────────

def generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256 method."""
    verifier_bytes = secrets.token_bytes(32)
    verifier = base64.urlsafe_b64encode(verifier_bytes).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def generate_secure_state() -> str:
    return secrets.token_urlsafe(32)


# ── Cookie encoding / decoding ────────────────────────────────────────────────

def encode_fhir_cookie(data: dict) -> str:
    return _serializer.dumps(data)


def decode_fhir_state_cookie(token: str) -> Optional[dict]:
    try:
        return _serializer.loads(token, max_age=FHIR_STATE_TTL)
    except (BadSignature, SignatureExpired):
        return None


def decode_fhir_session_cookie(token: str) -> Optional[dict]:
    try:
        return _serializer.loads(token, max_age=FHIR_SESSION_TTL)
    except (BadSignature, SignatureExpired):
        return None


# ── Token helpers ─────────────────────────────────────────────────────────────

def needs_refresh(expires_at: float) -> bool:
    """True if the access token should be refreshed (within buffer window)."""
    return time.time() >= expires_at - TOKEN_REFRESH_BUFFER


# ── SMART discovery ───────────────────────────────────────────────────────────

async def discover_smart_endpoints(fhir_base: str) -> dict:
    """Fetch /.well-known/smart-configuration from the EHR FHIR base URL."""
    url = fhir_base.rstrip("/") + "/.well-known/smart-configuration"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        return resp.json()


# ── Token exchange ────────────────────────────────────────────────────────────

async def exchange_code_for_token(
    code: str,
    token_endpoint: str,
    client_id: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,
    client_secret: Optional[str] = None,
) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": client_id,
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    if client_secret:
        # Confidential client: HTTP Basic Auth (client_secret_basic)
        creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(token_endpoint, data=data, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(
    refresh_token: str,
    token_endpoint: str,
    client_id: str,
    client_secret: Optional[str] = None,
) -> dict:
    """Use a refresh token to obtain a new access token."""
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    headers = {"Content-Type": "application/x-www-form-urlencoded"}

    if client_secret:
        creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {creds}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(token_endpoint, data=data, headers=headers)
        resp.raise_for_status()
        return resp.json()
