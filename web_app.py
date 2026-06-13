"""FastAPI web application for the Multi-Agent Discharge Planning System."""
import asyncio
import hashlib
import json
import logging
import math
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

import anthropic
import httpx
from dotenv import load_dotenv
from dataclasses import dataclass
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from typing import Any, Optional
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

try:
    from fhir.ehr_config import get_ehr_config, list_ehr_display
    from fhir.auth import (
        FHIR_SESSION_COOKIE,
        FHIR_SESSION_TTL,
        FHIR_STATE_COOKIE,
        FHIR_STATE_TTL,
        decode_fhir_session_cookie,
        decode_fhir_state_cookie,
        discover_smart_endpoints,
        encode_fhir_cookie,
        exchange_code_for_token,
        generate_pkce_pair,
        generate_secure_state,
        needs_refresh,
        refresh_access_token,
    )
    from fhir.client import FHIRAuthError, FHIRClient, FHIRForbiddenError
    from fhir.normalizers import fhir_bundle_to_agent_data
    _FHIR_IMPORT_ERROR: str | None = None
except Exception as _e:  # pragma: no cover
    # Capture the exact error so /api/healthz and FHIR route handlers can report it.
    # Define stubs so the route decorators below don't cause NameErrors at module load.
    _FHIR_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"
    get_ehr_config = list_ehr_display = None  # type: ignore[assignment]
    FHIRClient = FHIRAuthError = FHIRForbiddenError = None  # type: ignore[assignment,misc]
    fhir_bundle_to_agent_data = None  # type: ignore[assignment]
    FHIR_SESSION_COOKIE = "fhir_session"
    FHIR_SESSION_TTL = 28800
    FHIR_STATE_COOKIE = "fhir_auth_state"
    FHIR_STATE_TTL = 300
    decode_fhir_session_cookie = decode_fhir_state_cookie = None  # type: ignore[assignment]
    discover_smart_endpoints = encode_fhir_cookie = None  # type: ignore[assignment]
    exchange_code_for_token = generate_pkce_pair = None  # type: ignore[assignment]
    generate_secure_state = needs_refresh = refresh_access_token = None  # type: ignore[assignment]

import auth0_oidc

# Patient persistence (imported lazily to handle missing DB gracefully)
_PATIENT_DB_AVAILABLE = False
try:
    from db.patients import run_migrations, get_org_domain as _get_org_domain
    _PATIENT_DB_AVAILABLE = True
except Exception:
    def _get_org_domain(email: str) -> str:
        return email.split("@")[-1].lower() if "@" in email else "unknown"

# Directory DB (imported lazily)
_DIRECTORY_DB_AVAILABLE = False
try:
    from db.directory import (run_directory_migrations, search_facilities as _search_facilities,
                               get_facility_by_ccn, get_county_summary, get_sync_status,
                               seed_zip_coordinates)
    _DIRECTORY_DB_AVAILABLE = True
except Exception:
    pass

# Eligibility service (imported lazily)
_ELIGIBILITY_AVAILABLE = False
ELIGIBILITY_ENABLED = os.getenv("ELIGIBILITY_ENABLED", "false").lower() == "true"
ELIGIBILITY_MOCK = os.getenv("ELIGIBILITY_MOCK", "false").lower() == "true"
try:
    from services.eligibility import (
        check_eligibility as _check_eligibility,
        get_mock_result as _get_mock_result,
        detect_payer_id as _detect_payer_id,
        KNOWN_PAYERS as _KNOWN_PAYERS,
        _make_cache_key as _elig_cache_key,
    )
    _ELIGIBILITY_AVAILABLE = True
except Exception:
    pass

# Milestones / barrier tracking (imported lazily)
_MILESTONES_AVAILABLE = False
try:
    from db.milestones import (
        run_milestone_migrations as _run_milestone_migrations,
        create_milestone as _create_milestone,
        get_milestones_for_patient as _get_milestones_for_patient,
        get_open_milestone_count as _get_open_milestone_count,
        get_org_milestone_summary as _get_org_milestone_summary,
        update_milestone as _update_milestone,
        bulk_create_milestones as _bulk_create_milestones,
        get_milestone_by_id as _get_milestone_by_id,
        delete_milestone as _delete_milestone,
    )
    from db.milestones_catalog import BARRIER_CATALOG as _BARRIER_CATALOG
    from agents.barrier_extraction import BarrierExtractionAgent as _BarrierExtractionAgent
    _MILESTONES_AVAILABLE = True
except Exception:
    pass

# ROI outcomes engine (imported lazily)
_ROI_ENGINE_AVAILABLE = False
try:
    from services.roi_engine import compute_episode_roi as _compute_episode_roi, \
        aggregate_org_roi as _aggregate_org_roi, get_cost_per_day as _get_cost_per_day
    from db.roi import (
        get_org_roi_settings as _get_org_roi_settings,
        upsert_org_roi_settings as _upsert_org_roi_settings,
        get_drg_reference as _get_drg_reference,
        search_drg as _search_drg,
        upsert_roi_outcome as _upsert_roi_outcome,
        get_roi_outcome as _get_roi_outcome,
        get_org_roi_outcomes as _get_org_roi_outcomes,
        get_monthly_roi_trend as _get_monthly_roi_trend,
        get_drg_roi_breakdown as _get_drg_roi_breakdown,
        get_clinician_roi_breakdown as _get_clinician_roi_breakdown,
        get_roi_dashboard_data as _get_roi_dashboard_data,
        trigger_outcome_calculation as _trigger_outcome_calculation,
    )
    _ROI_ENGINE_AVAILABLE = True
except Exception as _roi_import_e:
    logging.getLogger(__name__).debug("ROI engine unavailable: %s", _roi_import_e)

# Referral workflow (imported lazily)
_REFERRALS_AVAILABLE = False
try:
    from db.referrals import (
        create_referral as _create_referral,
        get_referral as _get_referral,
        list_referrals as _list_referrals,
        update_referral_status as _update_referral_status,
        log_delivery_attempt as _log_delivery_attempt,
        get_delivery_log as _get_delivery_log,
        get_referral_analytics as _get_referral_analytics,
        get_org_referral_settings as _get_org_referral_settings,
        upsert_org_referral_settings as _upsert_org_referral_settings,
        add_referral_message as _add_referral_message,
        get_referral_messages as _get_referral_messages,
    )
    from services.referral_packet import (
        build_fhir_service_request as _build_fhir_sr,
        build_referral_html as _build_referral_html,
        generate_ai_clinical_summary as _gen_ai_summary,
    )
    from services.referral_delivery import (
        send_via_fax as _send_via_fax,
        send_via_careport as _send_via_careport,
        get_delivery_status as _get_delivery_status,
    )
    _REFERRALS_AVAILABLE = True
except Exception as _ref_import_e:
    logging.getLogger(__name__).debug("Referrals module unavailable: %s", _ref_import_e)

load_dotenv()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

# ── Rate limiting configuration ──────────────────────────────────────────────
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_STORAGE = os.getenv("RATE_LIMIT_STORAGE", "memory")
GLOBAL_AI_HOURLY_CAP = int(os.getenv("GLOBAL_AI_HOURLY_CAP", "500"))

_rl_logger = logging.getLogger("rate_limit.events")


def _build_storage_uri() -> str:
    """Return limits-library storage URI based on RATE_LIMIT_STORAGE env var."""
    if RATE_LIMIT_STORAGE == "upstash":  # pragma: no cover
        url = os.environ["UPSTASH_REDIS_REST_URL"]
        token = os.environ["UPSTASH_REDIS_REST_TOKEN"]
        return f"async+redis://:{token}@{url.replace('https://', '')}:6379"
    return "memory://"


def _get_key(request: Request) -> str:
    """Bypass-resistant key: signed session email for authed users, IP for anonymous.

    Never relies solely on X-Forwarded-For (easily spoofed by attackers).
    """
    try:
        _s = URLSafeTimedSerializer(os.environ["SECRET_KEY"])
        data = _s.loads(request.cookies.get("dp_session", ""), max_age=28800)
        return f"user:{data['email']}"
    except Exception:
        forwarded = request.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else get_remote_address(request)
        return f"ip:{ip}"


def _get_ip_key(request: Request) -> str:
    """IP-only key for auth endpoints.

    Auth endpoints (login, signup) must always be keyed by IP — never by session
    email — because a successful signup/login sets a new session cookie, which
    would change the key on every subsequent request and make per-IP limits trivially
    bypassable by rotating sessions.
    """
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else get_remote_address(request)


def _format_retry_after(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} seconds"
    if seconds < 3600:
        return f"{math.ceil(seconds / 60)} minutes"
    return f"{math.ceil(seconds / 3600)} hours"


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Structured JSON 429 with retry guidance and HIPAA-safe audit logging."""
    retry_after = getattr(exc, "retry_after", 60)
    limit_str = str(getattr(exc, "limit", "unknown"))
    key = _get_key(request)
    _rl_logger.warning(json.dumps({
        "event": "rate_limit_exceeded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "endpoint": request.url.path,
        "method": request.method,
        "key_type": "user" if key.startswith("user:") else "ip",
        "key_hash": hashlib.sha256(key.encode()).hexdigest()[:12],
        "limit": limit_str,
    }))
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": f"Too many requests. Limit: {limit_str}.",
            "retry_after_seconds": retry_after,
            "retry_after_human": _format_retry_after(retry_after),
            "support": "If you believe this limit is affecting your clinical workflow, "
                       "contact your system administrator.",
        },
        headers={
            "Retry-After": str(retry_after),
            "X-RateLimit-Limit": limit_str,
            "X-RateLimit-Reset": str(int(time.time()) + retry_after),
            "Content-Type": "application/json",
        },
    )


limiter = Limiter(
    key_func=_get_key,
    storage_uri=_build_storage_uri(),
    enabled=RATE_LIMIT_ENABLED,
    headers_enabled=True,
    strategy="moving-window",
)
app = FastAPI(title="Discharge Planning AI")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ── Progressive account lockout ──────────────────────────────────────────────
LOCKOUT_THRESHOLDS = {5: 60, 10: 300, 20: 1800, 50: 86400}

_login_failures: dict[str, list[float]] = {}   # email -> [fail_timestamp, ...]
_login_lockouts: dict[str, float] = {}          # email -> unlock_timestamp


async def _check_lockout(email: str) -> tuple[bool, int]:
    unlock_ts = _login_lockouts.get(email.lower(), 0)
    if unlock_ts > time.time():
        return True, int(unlock_ts - time.time())
    return False, 0


async def _record_failed_attempt(email: str) -> int:
    email = email.lower()
    now = time.time()
    recent = [t for t in _login_failures.get(email, []) if now - t < 3600]
    recent.append(now)
    _login_failures[email] = recent
    return len(recent)


async def _apply_lockout(email: str, fail_count: int) -> None:
    lockout_secs = 0
    for threshold, duration in sorted(LOCKOUT_THRESHOLDS.items(), reverse=True):
        if fail_count >= threshold:
            lockout_secs = duration
            break
    if lockout_secs:
        _login_lockouts[email.lower()] = time.time() + lockout_secs


async def _clear_failed_attempts(email: str) -> None:
    email = email.lower()
    _login_failures.pop(email, None)
    _login_lockouts.pop(email, None)


@app.get("/api/healthz")
async def healthz():
    """Public diagnostic endpoint — shows registered routes and import status."""
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    return {
        "status": "ok",
        "fhir_loaded": _FHIR_IMPORT_ERROR is None,
        "fhir_import_error": _FHIR_IMPORT_ERROR,
        "python_path": __import__("sys").path[:4],
        "routes": sorted(routes),
    }


@app.get("/fhir/metadata", response_class=JSONResponse)
async def capability_statement():
    """FHIR R4 CapabilityStatement — required for 170.315(g)(10) ATL testing."""
    base = "http://hl7.org/fhir/us/core/StructureDefinition"
    def _res(resource_type, profile, searches):
        return {
            "type": resource_type,
            "profile": f"{base}/{profile}",
            "interaction": [{"code": "read"}, {"code": "search-type"}],
            "searchParam": [{"name": n, "type": t} for n, t in searches],
        }
    return {
        "resourceType": "CapabilityStatement",
        "status": "active",
        "date": "2026-05-01",
        "kind": "instance",
        "fhirVersion": "4.0.1",
        "format": ["application/fhir+json"],
        "implementationGuide": [
            "http://hl7.org/fhir/us/core/ImplementationGuide/hl7.fhir.us.core"
        ],
        "rest": [{
            "mode": "server",
            "security": {
                "extension": [{
                    "url": "http://fhir-registry.smarthealthit.org/StructureDefinition/capabilities",
                    "valueCode": "launch-ehr",
                }],
                "service": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/restful-security-service", "code": "SMART-on-FHIR"}]}],
            },
            "resource": [
                _res("Patient", "us-core-patient", [("_id", "token"), ("identifier", "token"), ("family", "string"), ("birthdate", "date")]),
                _res("AllergyIntolerance", "us-core-allergyintolerance", [("patient", "reference"), ("clinical-status", "token")]),
                _res("CarePlan", "us-core-careplan", [("patient", "reference"), ("status", "token"), ("category", "token")]),
                _res("CareTeam", "us-core-careteam", [("patient", "reference"), ("status", "token")]),
                _res("Condition", "us-core-condition", [("patient", "reference"), ("clinical-status", "token"), ("category", "token")]),
                _res("DiagnosticReport", "us-core-diagnosticreport-note", [("patient", "reference"), ("category", "token"), ("date", "date")]),
                _res("DocumentReference", "us-core-documentreference", [("patient", "reference"), ("type", "token"), ("date", "date")]),
                _res("Encounter", "us-core-encounter", [("patient", "reference"), ("status", "token"), ("date", "date")]),
                _res("Goal", "us-core-goal", [("patient", "reference"), ("lifecycle-status", "token")]),
                _res("Immunization", "us-core-immunization", [("patient", "reference"), ("status", "token"), ("date", "date")]),
                _res("MedicationRequest", "us-core-medicationrequest", [("patient", "reference"), ("status", "token"), ("intent", "token")]),
                _res("Observation", "us-core-vital-signs", [("patient", "reference"), ("category", "token"), ("code", "token"), ("date", "date")]),
                _res("Procedure", "us-core-procedure", [("patient", "reference"), ("status", "token"), ("date", "date")]),
                _res("Provenance", "us-core-provenance", [("patient", "reference"), ("target", "reference")]),
                _res("Device", "us-core-implantable-device", [("patient", "reference"), ("type", "token")]),
                _res("Location", "us-core-location", [("name", "string"), ("address", "string")]),
                _res("Organization", "us-core-organization", [("name", "string"), ("identifier", "token")]),
                _res("Practitioner", "us-core-practitioner", [("name", "string"), ("identifier", "token")]),
            ],
        }],
    }

# Auth config — SECRET_KEY must be set in environment; no insecure fallback
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:  # pragma: no cover
    raise RuntimeError("SECRET_KEY environment variable is required and not set.")
ALLOWED_EMAILS_RAW = os.getenv("ALLOWED_EMAILS", "")
ALLOWED_EMAILS = {e.strip().lower() for e in ALLOWED_EMAILS_RAW.split(",") if e.strip()}

_serializer = URLSafeTimedSerializer(SECRET_KEY)
COOKIE_NAME = "dp_session"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours
SSO_STATE_COOKIE = "sso_auth_state"
SSO_STATE_TTL = 300  # 5 minutes

# Postgres URL — Vercel injects POSTGRES_URL automatically; DATABASE_URL is the fallback
DATABASE_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")

# Default org UUID used in file-based / test mode (no real DB)
DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


@dataclass
class OrgContext:
    """Decoded, verified identity from session cookie — org_id and role included."""
    email: str
    org_id: str
    role: str

# ── HIPAA audit log ───────────────────────────────────────────────────────────
_audit_logger = logging.getLogger("hipaa.audit")
logging.basicConfig(level=logging.INFO)

_AUDITED_PREFIXES = ("/api/plan", "/api/fhir", "/api/summary", "/api/discharge",
                     "/api/teachback", "/api/cdph", "/api/hrrp", "/api/medications",
                     "/api/multilingual", "/api/immunisation", "/api/predict")


def _get_audit_context(request: Request) -> tuple[str | None, str | None]:
    """Return (email, org_id) from session cookie without raising."""
    try:
        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return None, None
        data = _serializer.loads(token, max_age=COOKIE_MAX_AGE)
        return data.get("email"), data.get("org_id", DEFAULT_ORG_ID)
    except Exception:
        return None, None


async def _audit_log_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if any(path.startswith(p) for p in _AUDITED_PREFIXES):
        email, org_id = _get_audit_context(request)
        if email:
            mrn = getattr(request.state, "audit_mrn", None) or None
            ip = request.client.host if request.client else "unknown"
            if DATABASE_URL:  # pragma: no cover
                try:
                    from db import write_audit_log
                    await asyncio.to_thread(
                        write_audit_log, org_id, email, path,
                        request.method, response.status_code, ip, mrn,
                    )
                except Exception:
                    _audit_logger.exception("Audit log write failed")
            else:
                _audit_logger.info(
                    "AUDIT email=%s org=%s endpoint=%s mrn=%s status=%s ip=%s",
                    email, org_id, path, mrn, response.status_code, ip,
                )
    return response


app.middleware("http")(_audit_log_middleware)

# ── Global AI budget guard ───────────────────────────────────────────────────
_AI_ENDPOINTS = {
    "/api/plan/stream",
    "/api/summary/generate",
    "/api/discharge-summary/generate",
    "/api/teachback/generate",
    "/api/cdph-compliance/analyze",
    "/api/roi/generate",
    "/api/hrrp/generate",
    "/api/multilingual/generate",
}

_global_ai_counters: dict[str, int] = {}


@app.middleware("http")
async def global_ai_budget_guard(request: Request, call_next):
    """Middleware: enforces a global hourly cap on AI calls across all users.

    Returns 503 when exceeded so ops teams can distinguish system-level saturation
    from per-user 429s. Fails open if Redis is unavailable.
    """
    if request.url.path not in _AI_ENDPOINTS or not RATE_LIMIT_ENABLED:
        return await call_next(request)
    hour_key = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    for old_key in [k for k in _global_ai_counters if k != hour_key]:
        _global_ai_counters.pop(old_key, None)
    _global_ai_counters[hour_key] = _global_ai_counters.get(hour_key, 0) + 1
    if _global_ai_counters[hour_key] > GLOBAL_AI_HOURLY_CAP:
        return JSONResponse(
            status_code=503,
            content={
                "error": "Service temporarily at capacity",
                "detail": "The AI generation service is experiencing high demand. "
                          "Please try again in a few minutes.",
                "retry_after_seconds": 300,
            },
            headers={"Retry-After": "300"},
        )
    return await call_next(request)


# ── Password helpers ─────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return dk.hex()


def _verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return secrets.compare_digest(_hash_password(password, salt), stored_hash)


# ── User store ───────────────────────────────────────────────────────────────
# Uses Postgres when DATABASE_URL / POSTGRES_URL is set, otherwise falls back
# to a local JSON file (convenient for local development without a DB).

def _get_conn():  # pragma: no cover
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def _ensure_table() -> None:  # pragma: no cover
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    salt  TEXT NOT NULL,
                    hash  TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            _ensure_audit_log_schema(cur)
        conn.commit()


def _ensure_audit_log_schema(cur) -> None:
    """Create/repair the audit_log table so it matches what write_audit_log()
    inserts. Older deployments have a drifted schema (missing organization_id /
    user_email / mrn), which made every audited request log a DB error and
    write no audit row. ADD COLUMN IF NOT EXISTS backfills those in place."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id              BIGSERIAL PRIMARY KEY,
            organization_id TEXT,
            user_email      TEXT,
            endpoint        TEXT,
            method          TEXT,
            status          INT,
            ip              TEXT,
            mrn             TEXT,
            ts              TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    for col, coltype in (
        ("organization_id", "TEXT"),
        ("user_email", "TEXT"),
        ("endpoint", "TEXT"),
        ("method", "TEXT"),
        ("status", "INT"),
        ("ip", "TEXT"),
        ("mrn", "TEXT"),
        ("ts", "TIMESTAMPTZ"),
    ):
        cur.execute(f"ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS {col} {coltype}")


# File-based fallback for local dev
_LOCAL_USERS_FILE = BASE_DIR / "data" / "users.json"

def _file_load() -> dict:
    if _LOCAL_USERS_FILE.exists():
        try:
            return json.loads(_LOCAL_USERS_FILE.read_text(encoding="utf-8"))
        except Exception:  # pragma: no cover
            return {}
    return {}

def _file_save(users: dict) -> None:
    _LOCAL_USERS_FILE.parent.mkdir(exist_ok=True)
    _LOCAL_USERS_FILE.write_text(json.dumps(users, indent=2), encoding="utf-8")


def register_user(email: str, password: str) -> str | None:
    """Create user. Returns None on success, error string on failure."""
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)

    if DATABASE_URL:
        import psycopg2
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (email, salt, hash) VALUES (%s, %s, %s)",
                        (email, salt, pw_hash),
                    )
                conn.commit()
        except psycopg2.errors.UniqueViolation:
            return "An account with this email already exists."
        return None

    # File fallback
    users = _file_load()
    if email in users:
        return "An account with this email already exists."
    users[email] = {"salt": salt, "hash": pw_hash}
    _file_save(users)
    return None


def authenticate_user(email: str, password: str) -> str | None:
    """Return None if credentials are valid, error string if not."""
    if DATABASE_URL:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT salt, hash FROM users WHERE email = %s", (email,))
                row = cur.fetchone()
        if not row:
            return "No account found with this email. Please sign up first."
        salt, stored_hash = row
    else:
        users = _file_load()
        if email not in users:
            return "No account found with this email. Please sign up first."
        salt, stored_hash = users[email]["salt"], users[email]["hash"]

    if not _verify_password(password, salt, stored_hash):
        return "Incorrect password."
    return None


@app.on_event("startup")
async def startup():
    if DATABASE_URL:  # pragma: no cover
        await asyncio.to_thread(_ensure_table)
    if DATABASE_URL and _PATIENT_DB_AVAILABLE:
        try:
            run_migrations()
        except Exception as _e:
            logging.getLogger(__name__).warning("Patient migrations failed: %s", _e)
    if DATABASE_URL and _MILESTONES_AVAILABLE:
        try:
            _run_milestone_migrations()
        except Exception as _e:
            logging.getLogger(__name__).warning("Milestone migrations failed: %s", _e)
    if DATABASE_URL and _ROI_ENGINE_AVAILABLE:
        try:
            from scripts.seed_drg_reference import seed_drg_reference as _seed_drg
            await asyncio.to_thread(_seed_drg)
        except Exception as _e:
            logging.getLogger(__name__).warning("DRG seed failed: %s", _e)
    if DATABASE_URL and _DIRECTORY_DB_AVAILABLE:
        try:
            run_directory_migrations()
            # Seed zip codes if needed
            csv_path = str(BASE_DIR / "data" / "ca_zips.csv")
            if os.path.exists(csv_path):
                seed_zip_coordinates(csv_path)
            # NOTE: the directory data sync is NOT run here. On serverless
            # (Vercel) the instance is frozen/torn down once a request returns,
            # so a background thread spawned at startup is killed before the
            # multi-second CMS sync completes. The sync runs synchronously via
            # the Vercel Cron endpoint (/api/directory/cron-sync) and on demand
            # via POST /api/directory/sync (which the page triggers on first
            # load when the table is empty).
        except Exception as e:
            logging.getLogger(__name__).warning("Directory setup failed: %s", e)


# ── Session helpers ──────────────────────────────────────────────────────────

def make_session_cookie(email: str, org_id: str = DEFAULT_ORG_ID,
                        role: str = "clinician") -> str:
    return _serializer.dumps({"email": email, "org_id": org_id, "role": role})


def verify_session_cookie(token: str) -> str | None:
    """Return the email from a valid session cookie (used by legacy helpers)."""
    try:
        data = _serializer.loads(token, max_age=COOKIE_MAX_AGE)
        return data.get("email")
    except (BadSignature, SignatureExpired):
        return None


def get_current_org(request: Request) -> OrgContext:
    """FastAPI dependency — extract and validate org context from signed session cookie.

    In file-based mode (DATABASE_URL is None) the org_id defaults to
    DEFAULT_ORG_ID so tests work without a real database.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        data = _serializer.loads(token, max_age=COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=401, detail="Unauthorized")
    email = data.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Unauthorized")
    org_id = data.get("org_id", DEFAULT_ORG_ID)
    role = data.get("role", "clinician")
    return OrgContext(email=email, org_id=org_id, role=role)


def require_role(*roles: str):
    """Factory: returns a FastAPI dependency that enforces one of the given roles."""
    def _dep(ctx: OrgContext = Depends(get_current_org)) -> OrgContext:
        if ctx.role not in roles:
            raise HTTPException(status_code=403, detail="Forbidden")
        return ctx
    return _dep


def get_current_user(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_session_cookie(token)


def require_login(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return None


def _set_session(response: JSONResponse, email: str,
                 org_id: str = DEFAULT_ORG_ID,
                 role: str = "clinician") -> JSONResponse:
    response.set_cookie(
        key=COOKIE_NAME,
        value=make_session_cookie(email, org_id, role),
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=COOKIE_MAX_AGE,
    )
    return response


# ── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open(STATIC_DIR / "login.html", encoding="utf-8") as f:
        return f.read()


@app.post("/api/auth/signup")
@limiter.limit("3/minute", key_func=_get_ip_key)
async def do_signup(request: Request, body: dict[str, Any] = Body(default={})):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse({"error": "Invalid email address."}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters."}, status_code=400)
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        return JSONResponse({"error": "This email is not authorized to register."}, status_code=403)

    err = register_user(email, password)
    if err:
        return JSONResponse({"error": err}, status_code=409)

    response = JSONResponse({"ok": True})
    return _set_session(response, email)


@app.post("/api/auth/login")
@limiter.limit("5/minute", key_func=_get_ip_key)
async def do_login(request: Request, body: dict[str, Any] = Body(default={})):
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse({"error": "Invalid email address."}, status_code=400)
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        return JSONResponse({"error": "This email is not authorized."}, status_code=403)

    is_locked, secs = await _check_lockout(email)
    if is_locked:
        return JSONResponse(
            {"error": f"Account temporarily locked. Try again in {_format_retry_after(secs)}."},
            status_code=429,
            headers={"Retry-After": str(secs)},
        )

    err = authenticate_user(email, password)
    if err:
        fail_count = await _record_failed_attempt(email)
        await _apply_lockout(email, fail_count)
        return JSONResponse({"error": err}, status_code=401)

    await _clear_failed_attempts(email)
    response = JSONResponse({"ok": True})
    return _set_session(response, email)


@app.get("/api/auth/logout")
@limiter.limit("30/minute")
async def logout(request: Request):
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/api/auth/sso/config")
async def sso_config():
    """Returns whether Auth0 SSO is configured — login page uses this to show the SSO button."""
    return JSONResponse({"enabled": auth0_oidc.is_configured()})


@app.get("/auth/sso/login")
async def sso_login(request: Request):
    """Initiate Auth0 OIDC Authorization Code + PKCE flow."""
    if not auth0_oidc.is_configured():
        raise HTTPException(status_code=503, detail="SSO is not configured on this instance")
    code_verifier, code_challenge = auth0_oidc.generate_pkce_pair()
    state = auth0_oidc.generate_state()
    redirect_uri = os.getenv("AUTH0_CALLBACK_URL") or f"{APP_URL}/auth/sso/callback"
    authorize_url = auth0_oidc.build_authorize_url(state, code_challenge, redirect_uri)
    response = RedirectResponse(url=authorize_url, status_code=302)
    response.set_cookie(
        key=SSO_STATE_COOKIE,
        value=_serializer.dumps({"state": state, "code_verifier": code_verifier}),
        max_age=SSO_STATE_TTL,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


@app.get("/auth/sso/callback")
async def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Receive Auth0 callback, exchange code for tokens, set session cookie."""
    if error:
        return RedirectResponse(url=f"/login?error={quote(str(error))}", status_code=302)
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    raw = request.cookies.get(SSO_STATE_COOKIE)
    if not raw:
        raise HTTPException(status_code=400, detail="SSO session expired — please try again")
    try:
        sso_state = _serializer.loads(raw, max_age=SSO_STATE_TTL)
    except (BadSignature, SignatureExpired):
        raise HTTPException(status_code=400, detail="Invalid SSO state — please try again")

    if sso_state.get("state") != state:
        raise HTTPException(status_code=400, detail="State mismatch — possible CSRF attempt")

    redirect_uri = os.getenv("AUTH0_CALLBACK_URL") or f"{APP_URL}/auth/sso/callback"
    try:
        tokens = await auth0_oidc.exchange_code(code, sso_state["code_verifier"], redirect_uri)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Token exchange failed: {exc}")

    try:
        userinfo = await auth0_oidc.get_userinfo(tokens["access_token"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch user info: {exc}")

    email = userinfo.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="SSO provider did not return an email address")

    org_id = DEFAULT_ORG_ID
    role = "clinician"
    if DATABASE_URL:  # pragma: no cover
        try:
            from db import get_user_by_email_global, provision_sso_user
            existing = get_user_by_email_global(email)
            if existing:
                org_id = str(existing["organization_id"])
                role = existing.get("role", "clinician")
            else:
                provision_sso_user(email, org_id)
        except Exception as exc:
            _audit_logger.error("SSO user lookup/provision failed for %s: %s", email, exc)
            raise HTTPException(
                status_code=503,
                detail=f"SSO provisioning failed: {exc}",
            )

    response = RedirectResponse(url="/", status_code=302)
    _set_session(response, email, org_id, role)
    response.delete_cookie(SSO_STATE_COOKIE)
    return response


@app.get("/api/me")
@limiter.limit("120/hour")
async def me(request: Request, ctx: OrgContext = Depends(get_current_org)):
    return JSONResponse({"email": ctx.email, "org_id": ctx.org_id, "role": ctx.role})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/sample-patient")
@limiter.limit("60/hour")
async def get_sample_patient(request: Request,
                             ctx: OrgContext = Depends(get_current_org)):
    from sample_patient import SAMPLE_PATIENT_WEB
    return JSONResponse(dict(SAMPLE_PATIENT_WEB))


async def stream_plan(patient_data: dict):
    """Generate SSE events as each specialist agent runs, then the coordinator."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not set'})}\n\n"
        return

    client = anthropic.Anthropic(api_key=api_key)

    from agents.clinical_assessment import ClinicalAssessmentAgent
    from agents.care_needs import CareNeedsAgent
    from agents.insurance_authorization import InsuranceAuthorizationAgent
    from agents.medication_reconciliation import MedicationReconciliationAgent
    from agents.social_determinants import SocialDeterminantsAgent
    from agents.coordinator import CoordinatorAgent

    def build_agent_data(raw: dict) -> dict:
        def parse_med_list(text: str) -> list:
            return [line.strip() for line in text.splitlines() if line.strip()]

        def parse_diagnoses(text: str) -> list:
            return [line.strip() for line in text.splitlines() if line.strip()]

        return {
            "patient_name": raw.get("patient_name", ""),
            "age": raw.get("age", ""),
            "sex": raw.get("gender", ""),
            "mrn": raw.get("mrn", ""),
            "admission_date": raw.get("admission_date", ""),
            "anticipated_discharge_date": raw.get("expected_discharge_date", ""),
            "attending_physician": raw.get("attending_physician", ""),
            "primary_diagnosis": raw.get("primary_diagnosis", ""),
            "secondary_diagnoses": parse_diagnoses(raw.get("secondary_diagnoses", "")),
            "clinical_notes": raw.get("additional_clinical_notes", ""),
            "admission_medications": parse_med_list(raw.get("admission_medications", "")),
            "inpatient_medications": parse_med_list(raw.get("inpatient_medications", "")),
            "discharge_medications": parse_med_list(raw.get("discharge_medications", "")),
            "therapy_evaluations": {
                "PT": raw.get("pt_evaluation", "Not evaluated"),
                "OT": raw.get("ot_evaluation", "Not evaluated"),
                "ST": raw.get("st_evaluation", "Not evaluated"),
            },
            "insurance": {
                "primary": {
                    "payer_name": raw.get("primary_insurance", ""),
                    "medicare_type": raw.get("medicare_part_a", "N/A"),
                    "snf_days_used_this_benefit_period": raw.get("snf_days_used", 0),
                },
                "secondary": {"payer_name": raw.get("secondary_insurance", "")},
            },
            "primary_insurance": raw.get("primary_insurance", ""),
            "secondary_insurance": raw.get("secondary_insurance", ""),
            "medicare_part_a": raw.get("medicare_part_a", "N/A"),
            "snf_days_used": raw.get("snf_days_used", 0),
            "support_system": {
                "living_situation": raw.get("living_situation", ""),
                "primary_caregiver": raw.get("caregiver", ""),
            },
            "home_environment": {
                "housing_type": raw.get("housing_type", ""),
                "bedroom_location": raw.get("bedroom_location", ""),
            },
            "transportation": {"primary_transportation": raw.get("transportation", "")},
            "language_literacy": {"primary_language": raw.get("primary_language", "English")},
            "living_situation": raw.get("living_situation", ""),
            "caregiver": raw.get("caregiver", ""),
            "primary_language": raw.get("primary_language", "English"),
            "transportation_notes": raw.get("transportation", ""),
            "housing_type": raw.get("housing_type", ""),
            "bedroom_location": raw.get("bedroom_location", ""),
            "patient_family_preference": raw.get("patient_family_preference", ""),
            "physician_goals": raw.get("physician_goals", ""),
            "additional_notes": raw.get("additional_notes", ""),
        }

    agent_data = build_agent_data(patient_data)

    # Pre-flight eligibility check — emits eligibility_result SSE event if successful.
    # If ELIGIBILITY_ENABLED=false or STEDI_API_KEY is unset, this block is skipped entirely
    # so the insurance agent runs with AI-only output exactly as before.
    if ELIGIBILITY_ENABLED and _ELIGIBILITY_AVAILABLE:
        _member_id = patient_data.get("insurance_member_id", "").strip()
        _payer_name = patient_data.get("primary_insurance", "")
        _payer_id, _resolved_payer = _detect_payer_id(_payer_name)
        _npi = os.getenv("HOSPITAL_NPI", "").strip()
        _stedi_key = os.getenv("STEDI_API_KEY", "").strip()
        _can_check = bool(_member_id and _payer_id != "UNKNOWN" and _npi and
                         (ELIGIBILITY_MOCK or _stedi_key))
        if _can_check:
            try:
                import dataclasses as _dc
                if ELIGIBILITY_MOCK:
                    _elig = _get_mock_result(_payer_id, _resolved_payer)
                else:
                    _first = patient_data.get("patient_first_name", "").strip()
                    _last = patient_data.get("patient_last_name", "").strip()
                    _dob = patient_data.get("date_of_birth", "").strip()
                    _elig = await _check_eligibility(_member_id, _first, _last, _dob, _payer_id, _npi)
                _elig_dict = _dc.asdict(_elig)
                agent_data["_eligibility_result"] = _elig_dict
                yield f"data: {json.dumps({'type': 'eligibility_result', 'data': _elig_dict})}\n\n"
                if DATABASE_URL and _PATIENT_DB_AVAILABLE:
                    try:
                        from db.patients import cache_eligibility_result as _cer
                        _ck = _elig_cache_key(_member_id, _payer_id,
                                              datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                        await asyncio.to_thread(_cer, _ck, _elig_dict, _payer_id)
                    except Exception:
                        pass
            except Exception as _ee:
                logging.getLogger(__name__).warning("Eligibility pre-flight failed: %s", _ee)

    from agents.predictive_los import PredictiveLOSAgent
    agents = {
        "predictive_los": PredictiveLOSAgent(None),
        "clinical": ClinicalAssessmentAgent(client),
        "care_needs": CareNeedsAgent(client),
        "insurance": InsuranceAuthorizationAgent(client),
        "medications": MedicationReconciliationAgent(client),
        "social": SocialDeterminantsAgent(client),
    }

    queue: asyncio.Queue = asyncio.Queue()

    async def run_agent(name, agent):
        await queue.put({"type": "agent_start", "agent": name})
        try:
            result = await agent.run(agent_data)
            await queue.put({"type": "agent_complete", "agent": name, "output": result})
            if name == "predictive_los":
                try:
                    import dataclasses
                    from agents.predictive_los import predict_los
                    pred = predict_los(agent_data)
                    await queue.put({"type": "los_prediction", "data": dataclasses.asdict(pred)})
                except Exception:  # pragma: no cover
                    pass
            return name, result
        except Exception as e:  # pragma: no cover
            await queue.put({"type": "agent_error", "agent": name, "error": str(e)})
            return name, f"[ERROR: {str(e)}]"

    tasks = [asyncio.create_task(run_agent(name, agent)) for name, agent in agents.items()]

    completed = 0
    agent_outputs: dict = {}

    while completed < len(agents):
        event = await queue.get()
        yield f"data: {json.dumps(event)}\n\n"
        if event["type"] in ("agent_complete", "agent_error"):
            completed += 1
            agent_outputs[event["agent"]] = event.get("output", event.get("error", ""))
        # los_prediction is an extra informational event — does not count toward completion

    await asyncio.gather(*tasks)

    yield f"data: {json.dumps({'type': 'coordinator_start'})}\n\n"
    try:
        coordinator = CoordinatorAgent(client)
        plan = await coordinator.run(agent_outputs)
        yield f"data: {json.dumps({'type': 'coordinator_complete', 'output': plan})}\n\n"
    except Exception as e:  # pragma: no cover
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@app.get("/summary-generator", response_class=HTMLResponse)
async def summary_generator_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "summary-generator.html", encoding="utf-8") as f:
        return f.read()


@app.get("/imm-prompt-system", response_class=HTMLResponse)
async def imm_prompt_system_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "imm-prompt-system.html", encoding="utf-8") as f:
        return f.read()


@app.get("/multilingual-prompt-system", response_class=HTMLResponse)
async def multilingual_prompt_system_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "multilingual-prompt-system.html", encoding="utf-8") as f:
        return f.read()


@app.get("/discharge-summary-generator", response_class=HTMLResponse)
async def discharge_summary_generator_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "discharge-summary-generator.html", encoding="utf-8") as f:
        return f.read()


@app.get("/teachback-checklist", response_class=HTMLResponse)
async def teachback_checklist_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "teachback-checklist.html", encoding="utf-8") as f:
        return f.read()


@app.get("/cdph-compliance", response_class=HTMLResponse)
async def cdph_compliance_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "cdph-compliance.html", encoding="utf-8") as f:
        return f.read()


@app.get("/post-acute-directory", response_class=HTMLResponse)
async def post_acute_directory_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "post-acute-directory.html", encoding="utf-8") as f:
        return f.read()


@app.get("/hrrp-flagging", response_class=HTMLResponse)
async def hrrp_flagging_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "hrrp-flagging.html", encoding="utf-8") as f:
        return f.read()


@app.get("/roi-tracker", response_class=HTMLResponse)
async def roi_tracker_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "roi-tracker.html", encoding="utf-8") as f:
        return f.read()


@app.get("/readmission-tracker", response_class=HTMLResponse)
async def readmission_tracker_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "readmission-tracker.html", encoding="utf-8") as f:
        return f.read()


@app.get("/predictive-discharge", response_class=HTMLResponse)
async def predictive_discharge_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "predictive-discharge.html", encoding="utf-8") as f:
        return f.read()


@app.post("/api/predict/los")
@limiter.limit("60/hour")
async def predict_los_endpoint(request: Request, ctx: OrgContext = Depends(get_current_org)):
    """Return structured LOS prediction JSON for a given patient_data payload."""
    import dataclasses
    from agents.predictive_los import predict_los

    body = await request.json()
    patient_data = body.get("patient_data", body)
    request.state.audit_mrn = patient_data.get("mrn") or None
    try:
        prediction = predict_los(patient_data)
        return JSONResponse({"success": True, "prediction": dataclasses.asdict(prediction)})
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)



@app.post("/api/roi/generate")
@limiter.limit("30/hour")
async def generate_roi_summary(request: Request, body: dict[str, Any] = Body(default={}),
                               ctx: OrgContext = Depends(get_current_org)):
    user_prompt = body.get("prompt", "")
    if not user_prompt.strip():
        return JSONResponse({"error": "prompt is required"}, status_code=400)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Server not configured"}, status_code=500)

    system_prompt = (
        "You are a healthcare analytics specialist writing concise executive summaries "
        "for hospital C-suite presentations. Write in confident, professional prose. "
        "Numbers are pre-calculated — cite them exactly. Return JSON only."
    )

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=800, temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    try:
        raw_text = await asyncio.to_thread(_call_api)
    except anthropic.APIError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    clean = clean.strip()

    try:
        result = json.loads(clean)
        result["disclaimer"] = (
            "These are AI-estimated projections, not measured outcomes. "
            "For auditable measured ROI, use the Measured ROI dashboard at /roi-measured."
        )
        result["measured_roi_url"] = "/roi-measured"
        return JSONResponse({"success": True, "result": result})
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"JSON parse failed: {exc}", "raw": raw_text}, status_code=500)


@app.post("/api/hrrp/generate")
@limiter.limit("30/hour")
async def generate_hrrp_briefing(request: Request, body: dict[str, Any] = Body(default={}),
                                 ctx: OrgContext = Depends(get_current_org)):
    user_prompt = body.get("prompt", "")
    if not user_prompt.strip():
        return JSONResponse({"error": "prompt is required"}, status_code=400)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Server not configured"}, status_code=500)

    system_prompt = (
        "You are a CMS HRRP and TEAM model financial risk specialist in California. "
        "Analyze flagged conditions and return a concise risk briefing as JSON only — "
        "no prose, no markdown fences."
    )

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6", max_tokens=1500, temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    try:
        raw_text = await asyncio.to_thread(_call_api)
    except anthropic.APIError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    clean = clean.strip()

    try:
        result = json.loads(clean)
        return JSONResponse({"success": True, "result": result})
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"JSON parse failed: {exc}", "raw": raw_text}, status_code=500)


@app.post("/api/cdph-compliance/analyze")
@limiter.limit("30/hour")
async def analyze_cdph_compliance(request: Request, body: dict[str, Any] = Body(default={}),
                                  ctx: OrgContext = Depends(get_current_org)):
    user_prompt = body.get("prompt", "")
    if not user_prompt.strip():
        return JSONResponse({"error": "prompt is required"}, status_code=400)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Server not configured"}, status_code=500)

    system_prompt = (
        "You are a California healthcare compliance specialist. Analyze the discharge planning data "
        "provided and return a concise compliance risk report as JSON. Focus on California-specific "
        "issues: CDPH CoPs, Medi-Cal managed care auth, Commence Health QIO timelines, and the 3-day SNF rule. "
        "Be specific about regulatory citations. Return ONLY valid JSON — no prose, no markdown fences."
    )

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response

    try:
        response = await asyncio.to_thread(_call_api)
    except anthropic.APIError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    raw_text = response.content[0].text
    # A truncated response (hit the token ceiling) yields invalid JSON — surface a
    # clear message instead of a cryptic "Unterminated string" parse error.
    if getattr(response, "stop_reason", None) == "max_tokens":
        return JSONResponse(
            {"success": False,
             "error": "The compliance report was cut off before it finished. "
                      "Please try again, or reduce the amount of input data.",
             "raw": raw_text},
            status_code=500,
        )

    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    clean = clean.strip()

    try:
        result = json.loads(clean)
        return JSONResponse({"success": True, "result": result})
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"JSON parse failed: {exc}", "raw": raw_text}, status_code=500)


@app.post("/api/teachback/generate")
@limiter.limit("30/hour")
async def generate_teachback(request: Request, body: dict[str, Any] = Body(default={}),
                             ctx: OrgContext = Depends(get_current_org)):
    user_prompt = body.get("prompt", "")
    if not user_prompt.strip():
        return JSONResponse({"error": "prompt is required"}, status_code=400)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Server not configured"}, status_code=500)

    system_prompt = (
        "You are a patient education specialist and teach-back methodology expert embedded in a "
        "clinical discharge planning system. Generate highly specific, clinically accurate "
        "teach-back questions for discharge planners.\n\n"
        "RULES:\n"
        "- Questions must be open-ended (never yes/no). Start with 'Show me...', 'Tell me...', "
        "'What would you do if...', or 'Walk me through...'\n"
        "- Reference the patient's EXACT medication names, condition, and circumstances\n"
        "- Be CONCISE: expected_answer ≤ 25 words, planner_tip ≤ 20 words, "
        "red_flag ≤ 15 words, follow_up_teaching ≤ 25 words\n"
        "- Max 2 questions per medication; max 3 warning-sign questions total; "
        "max 2 questions for each remaining category\n"
        "- Return ONLY valid JSON — no prose, no markdown fences"
    )

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    try:
        raw_text = await asyncio.to_thread(_call_api)
    except anthropic.APIError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    clean = raw_text.strip()
    # Strip markdown fences regardless of language tag (```json, ```JSON, etc.)
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    clean = clean.strip()

    try:
        result = json.loads(clean)
        if not isinstance(result.get("categories"), list):
            return JSONResponse({"success": False, "error": "Response missing 'categories' field", "raw": raw_text}, status_code=500)
        return JSONResponse({"success": True, "result": result})
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"JSON parse failed: {exc}", "raw": raw_text}, status_code=500)


@app.post("/api/discharge-summary/generate")
@limiter.limit("20/hour")
async def generate_discharge_summary_v2(request: Request, body: dict[str, Any] = Body(default={}),
                                        org: OrgContext = Depends(get_current_org)):
    ctx = body.get("ctx", {})
    notes = body.get("notes", "")
    if not notes.strip():
        return JSONResponse({"error": "notes is required"}, status_code=400)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Server not configured"}, status_code=500)

    system_prompt = (
        "You are an expert clinical documentation specialist embedded in a HIPAA-compliant "
        "hospital discharge planning system serving California acute care hospitals. Your role "
        "is to generate accurate, structured, CMS-compliant discharge summaries from clinical "
        "notes provided by discharge planners and case managers.\n\n"
        "NON-NEGOTIABLE RULES:\n"
        "- NEVER fabricate clinical data, medications, lab values, or diagnoses not present in the source notes\n"
        "- If data is missing for a field, use null — never guess or invent\n"
        "- All patient_instruction text must be written at a 6th-grade reading level\n"
        "- Warning signs must include a specific action for each: 'call your doctor', 'go to the emergency room', or 'call 911'\n"
        "- Medication names are kept as-is (generic + brand). NEVER alter drug names\n"
        "- Flag if physician review is required (high-alert meds, complex discharge, ambiguous instructions)\n"
        "- Return ONLY valid JSON — no prose, no markdown fences, no preamble"
    )

    user_prompt = (
        f"Generate a complete discharge summary from the clinical notes below.\n\n"
        f"PATIENT CONTEXT:\n"
        f"- Admission date: {ctx.get('admissionDate') or 'not provided'}\n"
        f"- Discharge date: {ctx.get('dischargeDate') or 'not provided'}\n"
        f"- Attending physician: {ctx.get('attending') or 'not provided'}\n"
        f"- Service / unit: {ctx.get('unit') or 'not provided'}\n"
        f"- Insurance / payer: {ctx.get('payer') or 'not provided'}\n"
        f"- LACE risk score: {ctx.get('laceScore') or 'not calculated'}\n"
        f"- HRRP flagged condition: {ctx.get('hrrpFlag') or 'none'}\n\n"
        f"CLINICAL NOTES:\n{notes}\n\n"
        'Return a single valid JSON object with this exact structure:\n\n'
        '{\n'
        '  "meta": {\n'
        '    "confidence": "high | medium | low",\n'
        '    "requires_physician_review": true | false,\n'
        '    "review_reason": "<reason or null>",\n'
        '    "missing_fields": ["<field name>"],\n'
        '    "generated_at": "<ISO timestamp>",\n'
        '    "hrrp_flagged": true | false,\n'
        '    "hrrp_condition": "<condition or null>",\n'
        '    "lace_score": "<integer or null>",\n'
        '    "lace_tier": "high | moderate | low | unknown"\n'
        '  },\n'
        '  "diagnosis": {\n'
        '    "primary": "<ICD-10 code — Plain English name>",\n'
        '    "secondary": ["<ICD-10 — name>"],\n'
        '    "admission_reason": "<1-2 sentence plain English>",\n'
        '    "hospital_course": "<3-5 sentence narrative of stay>",\n'
        '    "condition_at_discharge": "stable | improved | unchanged | declined",\n'
        '    "functional_status": "<ADL and mobility status at discharge>"\n'
        '  },\n'
        '  "medications": [\n'
        '    {\n'
        '      "name": "<generic (Brand)>",\n'
        '      "dose": "<dose and units>",\n'
        '      "route": "<oral | IV | topical | inhaled | subcut>",\n'
        '      "frequency": "<plain English>",\n'
        '      "duration": "<X days | ongoing | as needed>",\n'
        '      "indication": "<why patient takes it>",\n'
        '      "is_new": true,\n'
        '      "is_changed": false,\n'
        '      "is_high_alert": false,\n'
        '      "patient_instruction": "<one sentence>",\n'
        '      "special_instructions": "<or null>"\n'
        '    }\n'
        '  ],\n'
        '  "medications_stopped": [{ "name": "<med>", "reason": "<reason>" }],\n'
        '  "reconciliation_complete": true,\n'
        '  "follow_up": {\n'
        '    "appointments": [\n'
        '      {\n'
        '        "provider": "<name or specialty>",\n'
        '        "timeframe": "<within X days>",\n'
        '        "reason": "<plain English>",\n'
        '        "scheduled": true,\n'
        '        "phone": "<or null>",\n'
        '        "patient_instruction": "<what to do>"\n'
        '      }\n'
        '    ],\n'
        '    "labs_pending": ["<lab — expected turnaround>"],\n'
        '    "imaging_pending": ["<imaging — expected turnaround>"],\n'
        '    "tcm_applicable": true,\n'
        '    "follow_up_call_scheduled": false,\n'
        '    "call_cadence": "<24h | 24h+72h | 24h+72h+7d+14d | none>"\n'
        '  },\n'
        '  "warning_signs": [\n'
        '    {\n'
        '      "sign": "<symptom in plain English>",\n'
        '      "action": "call_doctor | go_to_er | call_911",\n'
        '      "action_label": "<Call your doctor | Go to the emergency room | Call 911 immediately>",\n'
        '      "urgency": "urgent | emergent | life_threatening"\n'
        '    }\n'
        '  ],\n'
        '  "activity_restrictions": "<concrete instructions or null>",\n'
        '  "diet_instructions": "<specific guidance or null>",\n'
        '  "wound_care": "<step-by-step or null>",\n'
        '  "patient_education": {\n'
        '    "diagnosis_explained": "<2-3 sentences a patient can understand>",\n'
        '    "teach_back_topics": ["<topic>"]'
        '  },\n'
        '  "post_acute": {\n'
        '    "destination": "home | SNF | IRF | LTACH | hospice | assisted_living | other",\n'
        '    "home_health": true,\n'
        '    "home_health_services": ["<nursing | PT | OT | SLP | aide>"],\n'
        '    "dme": ["<equipment ordered>"]\n'
        '  },\n'
        '  "attestation": "I certify this discharge plan was developed in collaboration with the patient '
        'and/or authorized representative in compliance with CMS CoP 42 CFR §482.43 and California CDPH '
        'discharge planning requirements."\n'
        '}'
    )

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    try:
        raw_text = await asyncio.to_thread(_call_api)
    except anthropic.APIError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
    clean = clean.strip()

    try:
        summary = json.loads(clean)
        return JSONResponse({"success": True, "summary": summary})
    except json.JSONDecodeError:
        return JSONResponse({"success": False, "error": "JSON parse failed", "raw": raw_text}, status_code=500)


@app.post("/api/summary/generate")
@limiter.limit("20/hour")
async def generate_summary(request: Request, body: dict[str, Any] = Body(default={}),
                           ctx: OrgContext = Depends(get_current_org)):
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"}, status_code=500)

    clinical_notes = body.get("clinicalNotes", "")
    ctx = body.get("patientContext", {})

    if not clinical_notes.strip():
        return JSONResponse({"error": "clinicalNotes is required"}, status_code=400)

    SYSTEM_PROMPT = """You are an expert clinical documentation specialist embedded in a HIPAA-compliant hospital discharge planning system. Your role is to generate accurate, structured, CMS-compliant discharge summaries for use by licensed discharge planners, case managers, and attending physicians in California acute care hospitals.

You operate under these non-negotiable constraints:
- NEVER fabricate clinical data, medications, lab values, or diagnoses not present in the source notes
- NEVER include information that could identify a patient beyond what is explicitly provided
- ALWAYS flag missing critical information rather than inventing it
- ALWAYS use plain-language patient instructions alongside clinical terminology
- ALWAYS include California-specific regulatory elements: CDPH CoP compliance, Commence Health QIO appeal rights, Medi-Cal auth status where applicable
- Output must be structured JSON matching the schema provided — no prose, no markdown fences, no preamble

Your output will be parsed programmatically and rendered into a printable, legally defensible discharge document. Accuracy and completeness take precedence over brevity."""

    user_prompt = f"""Generate a complete, CMS-compliant discharge summary from the clinical notes below.

## Patient Context
- Admission date: {ctx.get('admissionDate', 'Not provided')}
- Discharge date: {ctx.get('dischargeDate', 'Not provided')}
- Attending physician: {ctx.get('attending', 'Not provided')}
- Unit / service: {ctx.get('unit', 'Not provided')}
- Insurance / payer: {ctx.get('payer', 'Not provided')}
- Patient preferred language: {ctx.get('language', 'English')}
- LACE risk score: {ctx.get('laceScore', 'Not calculated')} ({ctx.get('laceTier', 'Unknown')})
- HRRP flagged condition: {ctx.get('hrrpFlag', 'None')}

## Source Clinical Notes
{clinical_notes}

## Instructions
Return a single valid JSON object with these top-level keys: summary_metadata, patient_summary, medications, follow_up, patient_education, post_acute_plan, california_compliance, liability_documentation, readmission_risk.

Rules:
1. If source notes lack data for a field, set it to null and add to summary_metadata.missing_fields
2. If any high-alert medication (warfarin, insulin, opioids, anticoagulants, digoxin) is present, set requires_physician_review to true
3. If LACE score >= 10, set follow_up_call_cadence to "24h + 72h + 7d + 14d"
4. All patient_instruction fields must be written at a 6th-grade reading level
5. warning_signs must include at minimum: fever, worsening pain, signs of infection, medication side effects
6. Do not wrap output in markdown fences"""

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text

    try:
        raw_text = await asyncio.to_thread(_call_api)
    except anthropic.APIError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    # Strip markdown fences defensively
    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1]
        if clean.endswith("```"):
            clean = clean.rsplit("```", 1)[0]
    clean = clean.strip()

    try:
        summary = json.loads(clean)
        # Enforce CA compliance rules server-side
        if summary.get("california_compliance", {}).get("hrrp_condition_flagged"):
            if "readmission_risk" in summary:
                summary["readmission_risk"]["follow_up_call_cadence"] = "24h + 72h + 7d + 14d"
        return JSONResponse({"success": True, "summary": summary})
    except json.JSONDecodeError:
        return JSONResponse({"success": False, "error": "JSON parse failed", "raw": raw_text}, status_code=500)


@app.post("/api/plan/stream")
@limiter.limit("10/hour")
async def create_plan(request: Request, patient_data: dict[str, Any] = Body(default={}),
                      ctx: OrgContext = Depends(get_current_org)):
    request.state.audit_mrn = patient_data.get("mrn") or None
    async def _stream_with_tcm():
        coordinator_output: str | None = None
        _agent_outputs: dict = {}
        # Make a mutable copy so we can enrich with nearby facilities
        _patient_data = dict(patient_data)
        mrn = _patient_data.get("mrn", "").strip()
        # Enrich with nearby facilities if zip_code provided
        if _patient_data.get("zip_code") and DATABASE_URL and _DIRECTORY_DB_AVAILABLE:
            try:
                from db.directory import search_facilities as _sf_enrich
                nearby = await asyncio.to_thread(
                    _sf_enrich, _patient_data["zip_code"], 25.0, None, None, None, None, False, "rating", 5
                )
                if nearby:
                    _patient_data["nearby_facilities"] = [
                        {"name": f["name"], "distance_miles": f["distance_miles"],
                         "rating": f["overall_rating"], "city": f["city"],
                         "beds": f.get("licensed_total_beds") or f.get("certified_beds"),
                         "medi_cal": f["accepts_medi_cal"], "phone": f["phone"]}
                        for f in nearby[:5]
                    ]
            except Exception:
                pass
        admission_date_val = _patient_data.get("admission_date", "").strip()
        user_email = ctx.email

        patient_id: int | None = None
        run_id: int | None = None
        agent_start_times: dict = {}

        if mrn and admission_date_val and DATABASE_URL and _PATIENT_DB_AVAILABLE:
            try:
                from db.patients import (get_or_create_patient, save_snapshot,
                                         start_plan_run, get_org_domain)
                org_d = get_org_domain(user_email)
                pat = await asyncio.to_thread(get_or_create_patient, mrn, admission_date_val, user_email, _patient_data)
                patient_id = pat["id"]
                snap_id = await asyncio.to_thread(save_snapshot, patient_id, _patient_data, user_email)
                run_id = await asyncio.to_thread(start_plan_run, patient_id, snap_id, user_email)
                yield f"data: {json.dumps({'type': 'patient_record', 'data': {'patient_id': patient_id, 'run_id': run_id, 'mrn': mrn}})}\n\n"
            except Exception as _pe:
                logging.getLogger(__name__).warning("Patient record setup failed: %s", _pe)
        elif not mrn or not admission_date_val:
            yield f"data: {json.dumps({'type': 'warning', 'message': 'No MRN or admission date provided — this plan will not be saved to patient record.'})}\n\n"

        async for chunk in stream_plan(_patient_data):
            yield chunk
            try:
                event_str = chunk.removeprefix("data: ").strip()
                event_data = json.loads(event_str)
                etype = event_data.get("type")
                if etype == "agent_start":
                    agent_start_times[event_data.get("agent", "")] = time.time()
                elif etype == "agent_complete":
                    aname = event_data.get("agent", "")
                    _agent_outputs[aname] = event_data.get("output", "")
                    if run_id and _PATIENT_DB_AVAILABLE:
                        try:
                            from db.patients import save_agent_output
                            dur = int((time.time() - agent_start_times.get(aname, time.time())) * 1000)
                            await asyncio.to_thread(save_agent_output, run_id, aname, event_data.get("output", ""), dur)
                        except Exception:
                            pass
                elif etype == "coordinator_complete":
                    coordinator_output = event_data.get("output", "")
            except Exception:
                pass

        if run_id and _PATIENT_DB_AVAILABLE and coordinator_output is not None:
            try:
                from db.patients import complete_plan_run
                import dataclasses
                los_pred = None
                try:
                    from agents.predictive_los import predict_los
                    los_pred = dataclasses.asdict(predict_los(_patient_data))
                except Exception:
                    pass
                await asyncio.to_thread(complete_plan_run, run_id, coordinator_output, los_pred)
            except Exception:
                pass

        if DATABASE_URL and coordinator_output is not None:
            tcm_result = await _maybe_create_tcm_episode(
                coordinator_output, _patient_data, ctx.org_id, ctx.email)
            if tcm_result:
                yield f"data: {json.dumps({'type': 'tcm_episode_created', **tcm_result})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'tcm_not_applicable'})}\n\n"

        if patient_id and _MILESTONES_AVAILABLE and coordinator_output is not None:
            try:
                import anthropic as _anthropic
                _api_key = os.getenv("ANTHROPIC_API_KEY")
                _anthro_client = _anthropic.Anthropic(api_key=_api_key) if _api_key else None
                if _anthro_client is None:
                    raise RuntimeError("ANTHROPIC_API_KEY not set")
                agent = _BarrierExtractionAgent(_anthro_client)
                barriers = await agent.run(coordinator_output, _agent_outputs, _patient_data)
                if barriers:
                    _org_domain = ctx.email.split("@")[-1] if "@" in ctx.email else ""
                    created_rows = await asyncio.to_thread(
                        _bulk_create_milestones,
                        patient_id, _org_domain, barriers, ctx.email, run_id
                    )
                    yield f"data: {json.dumps({'type': 'barriers_detected', 'count': len(created_rows), 'barriers': barriers})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'barriers_detected', 'count': 0, 'barriers': []})}\n\n"
            except Exception as _be:
                logging.getLogger(__name__).warning("Barrier extraction failed: %s", _be)

    return StreamingResponse(
        _stream_with_tcm(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── Patient persistence endpoints ─────────────────────────────────────────────

@app.get("/api/patients")
@limiter.limit("120/hour")
async def list_patients(request: Request, search: str = "",
                        ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        return JSONResponse({"patients": [], "total": 0})
    try:
        from db.patients import get_patients_for_org, search_patients, get_org_domain
        org_domain = get_org_domain(ctx.email)
        if search.strip():
            patients = await asyncio.to_thread(search_patients, org_domain, search.strip())
        else:
            patients = await asyncio.to_thread(get_patients_for_org, org_domain)
        # Serialize datetime/date fields
        import datetime as _dt
        def _ser(v):
            if isinstance(v, (_dt.datetime, _dt.date)):
                return v.isoformat()
            return v
        result = [{k: _ser(v) for k, v in p.items()} for p in patients]
        return JSONResponse({"patients": result, "total": len(result)})
    except Exception as e:
        return JSONResponse({"patients": [], "total": 0, "error": str(e)})


@app.get("/api/patients/{patient_id}")
@limiter.limit("120/hour")
async def get_patient(request: Request, patient_id: int,
                      ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        from db.patients import get_patient_detail, get_org_domain
        import datetime as _dt
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        def _ser(obj):
            if isinstance(obj, dict):
                return {k: _ser(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_ser(i) for i in obj]
            if isinstance(obj, (_dt.datetime, _dt.date)):
                return obj.isoformat()
            return obj
        return JSONResponse({"patient": _ser(patient)})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patients/{patient_id}/prefill")
@limiter.limit("120/hour")
async def prefill_patient(request: Request, patient_id: int,
                           ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        from db.patients import get_latest_snapshot, get_patient_detail, get_org_domain
        import datetime as _dt
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        snapshot = await asyncio.to_thread(get_latest_snapshot, patient_id)
        runs = patient.get("runs", [])
        last_run_at = None
        if runs:
            lr = runs[-1].get("completed_at") or runs[-1].get("started_at")
            if isinstance(lr, (_dt.datetime, _dt.date)):
                last_run_at = lr.isoformat()
            else:
                last_run_at = str(lr) if lr else None
        return JSONResponse({
            "patient_data": snapshot or {},
            "run_count": len(runs),
            "last_run_at": last_run_at,
            "patient_name": patient.get("patient_name"),
            "mrn": patient.get("mrn"),
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/patients/{patient_id}/status")
@limiter.limit("60/hour")
async def update_patient_status_endpoint(request: Request, patient_id: int,
                                          ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        body = await request.json()
        new_status = body.get("status", "").strip()
        note = body.get("note")
        from db.patients import update_patient_status, get_patient_detail, get_org_domain, VALID_STATUSES
        if new_status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(VALID_STATUSES)}")
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        await asyncio.to_thread(update_patient_status, patient_id, new_status, ctx.email, note)
        if new_status == "discharged" and _ROI_ENGINE_AVAILABLE and DATABASE_URL:
            asyncio.create_task(
                asyncio.to_thread(_trigger_outcome_calculation, patient_id, org_domain)
            )
        return JSONResponse({"ok": True, "status": new_status})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/patients/{patient_id}/notes")
@limiter.limit("60/hour")
async def add_patient_note_endpoint(request: Request, patient_id: int,
                                     ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        body = await request.json()
        note_text = body.get("note_text", "").strip()
        if not note_text:
            raise HTTPException(status_code=400, detail="note_text is required")
        from db.patients import add_patient_note, get_patient_detail, get_org_domain
        import datetime as _dt
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        note = await asyncio.to_thread(add_patient_note, patient_id, note_text, ctx.email)
        def _ser(v):
            if isinstance(v, (_dt.datetime, _dt.date)):
                return v.isoformat()
            return v
        return JSONResponse({k: _ser(v) for k, v in note.items()})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/patients/{patient_id}/notes/{note_id}")
@limiter.limit("60/hour")
async def delete_patient_note_endpoint(request: Request, patient_id: int, note_id: int,
                                        ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        from db.patients import delete_patient_note
        deleted = await asyncio.to_thread(delete_patient_note, note_id, ctx.email)
        if not deleted:
            raise HTTPException(status_code=404, detail="Note not found or you are not the author")
        return JSONResponse({"ok": True})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/patients/{patient_id}/runs/{run_id}/export")
@limiter.limit("30/hour")
async def export_run_endpoint(request: Request, patient_id: int, run_id: int,
                               ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    try:
        from db.patients import get_patient_detail, get_org_domain
        import datetime as _dt
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        run = next((r for r in patient.get("runs", []) if r["id"] == run_id), None)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")

        AGENT_LABELS = {
            "predictive_los": "Predictive Discharge Date",
            "clinical": "Clinical Assessment",
            "care_needs": "Care Needs Assessment",
            "insurance": "Insurance Authorization",
            "medications": "Medication Reconciliation",
            "social": "Social Determinants",
            "coordinator": "Final Discharge Plan",
        }

        def fmt_dt(v):
            if isinstance(v, (_dt.datetime, _dt.date)):
                return v.strftime("%B %d, %Y")
            return str(v) if v else "—"

        agents_html = ""
        agent_order = ["predictive_los","clinical","care_needs","insurance","medications","social","coordinator"]
        agents_by_name = {a["agent_name"]: a for a in run.get("agents", [])}

        for aname in agent_order:
            if aname in agents_by_name:
                label = AGENT_LABELS.get(aname, aname)
                text = agents_by_name[aname]["output_text"].replace("<","&lt;").replace(">","&gt;")
                agents_html += f'<section class="section"><h2>{label}</h2><pre>{text}</pre></section>\n'

        if run.get("final_plan") and "coordinator" not in agents_by_name:
            text = run["final_plan"].replace("<","&lt;").replace(">","&gt;")
            agents_html += f'<section class="section"><h2>Final Discharge Plan</h2><pre>{text}</pre></section>\n'

        started = fmt_dt(run.get("started_at"))
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Discharge Plan — {patient.get("patient_name","Unknown")} — {patient.get("mrn","")}</title>
<style>
  body{{font-family:Georgia,serif;font-size:12pt;color:#111;margin:40px;line-height:1.6}}
  .header{{border-bottom:2px solid #1a56db;padding-bottom:16px;margin-bottom:24px}}
  .header h1{{font-size:18pt;color:#1a56db;margin:0 0 8px}}
  .meta{{font-size:10pt;color:#555}}
  .draft-banner{{background:#fef3cd;border:1px solid #f59e0b;padding:10px 16px;border-radius:6px;margin:16px 0;font-size:10pt}}
  .section{{margin:24px 0;page-break-inside:avoid}}
  .section h2{{font-size:13pt;color:#1e3a8a;border-bottom:1px solid #e2e8f0;padding-bottom:6px}}
  pre{{white-space:pre-wrap;font-family:inherit;font-size:11pt;margin:8px 0}}
  .footer{{margin-top:40px;padding-top:16px;border-top:1px solid #e2e8f0;font-size:9pt;color:#888;text-align:center}}
  @media print{{body{{margin:20px}}.draft-banner{{-webkit-print-color-adjust:exact}}}}
</style>
</head><body>
<div class="header">
  <h1>🏥 DISCHARGE PLAN — CONFIDENTIAL</h1>
  <div class="meta">
    <strong>Patient:</strong> {patient.get("patient_name","Unknown")} &nbsp;|&nbsp;
    <strong>MRN:</strong> {patient.get("mrn","—")} &nbsp;|&nbsp;
    <strong>Admission:</strong> {fmt_dt(patient.get("admission_date"))}<br>
    <strong>Plan generated:</strong> {started} &nbsp;|&nbsp;
    <strong>Run #:</strong> {run.get("run_number","—")} &nbsp;|&nbsp;
    <strong>By:</strong> {run.get("run_by","—")}
  </div>
</div>
<div class="draft-banner">⚠ DRAFT — Clinical decision support only. Not a substitute for clinical judgment.</div>
{agents_html}
<div class="footer">
  Generated by Discharge Planning AI · {_dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}<br>
  This document is confidential and intended for authorized clinical personnel only.
</div>
<script>window.onload = function(){{ window.print(); }};</script>
</body></html>"""

        from fastapi.responses import HTMLResponse as _HR
        return _HR(content=html, headers={"Content-Disposition": "inline"})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/my-patients", response_class=HTMLResponse)
async def my_patients_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "my-patients.html", encoding="utf-8") as f:
        return f.read()


@app.get("/patients/{patient_id}", response_class=HTMLResponse)
async def patient_detail_page(request: Request, patient_id: int):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "patient-detail.html", encoding="utf-8") as f:
        return f.read()


APP_URL = os.environ.get("NEXT_PUBLIC_APP_URL", "https://discharge-planning.vercel.app")
FHIR_REDIRECT_URI = os.getenv("FHIR_REDIRECT_URI", f"{APP_URL}/api/fhir/callback")


# ── Post-Acute Provider Directory API ────────────────────────────────────────

@app.get("/api/directory/search")
@limiter.limit("120/hour")
async def directory_search(request: Request, zip: str = "", radius: float = 25.0,
                           types: str = "SNF,IRF,LTACH", min_rating: int = None,
                           medi_cal: str = None, medicare: str = None,
                           exclude_sff: str = "false", sort: str = "distance",
                           limit: int = 50, ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _DIRECTORY_DB_AVAILABLE:
        return JSONResponse({"results": [], "total": 0, "error": "Directory database not available"})
    zip = zip.strip()
    if not zip or not zip.isdigit() or len(zip) != 5:
        return JSONResponse({"results": [], "total": 0, "error": "Valid 5-digit ZIP code required"}, status_code=400)
    radius = max(1.0, min(100.0, radius))
    limit = max(1, min(100, limit))
    facility_types = [t.strip().upper() for t in types.split(",") if t.strip()] if types else None
    try:
        from db.directory import search_facilities as _sf, get_sync_status as _gss
        results = await asyncio.to_thread(
            _sf, zip, radius, facility_types,
            min_rating if min_rating else None,
            True if medi_cal == "true" else (False if medi_cal == "false" else None),
            True if medicare == "true" else (False if medicare == "false" else None),
            exclude_sff == "true", sort, limit
        )
        sync = await asyncio.to_thread(_gss)
        freshness = f"Synced {int(sync.get('data_freshness_hours', 0))} hours ago" if sync.get('last_sync') else "Not yet synced"
        return JSONResponse({"results": results, "total": len(results), "zip": zip,
                             "radius_miles": radius, "data_freshness": freshness})
    except Exception as e:
        return JSONResponse({"results": [], "total": 0, "error": str(e)}, status_code=500)


@app.get("/api/directory/facility/{ccn}")
@limiter.limit("120/hour")
async def directory_facility_detail(request: Request, ccn: str,
                                     ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _DIRECTORY_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Directory database not available")
    try:
        from db.directory import get_facility_by_ccn as _gf
        import datetime as _dt
        facility = await asyncio.to_thread(_gf, ccn)
        if not facility:
            raise HTTPException(status_code=404, detail="Facility not found")
        def _ser(v):
            if isinstance(v, (_dt.datetime, _dt.date)): return v.isoformat()
            return v
        return JSONResponse({"facility": {k: _ser(v) for k, v in facility.items()}})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/directory/county-summary")
@limiter.limit("60/hour")
async def directory_county_summary(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _DIRECTORY_DB_AVAILABLE:
        return JSONResponse({"counties": []})
    try:
        from db.directory import get_county_summary as _gcs
        counties = await asyncio.to_thread(_gcs)
        return JSONResponse({"counties": counties})
    except Exception as e:
        return JSONResponse({"counties": [], "error": str(e)})


@app.post("/api/directory/sync")
@limiter.limit("120/hour")
async def directory_sync_trigger(request: Request, ctx: OrgContext = Depends(get_current_org)):
    """Chunked sync driver. Each call processes ONE page (~500 rows) so it stays
    well within a serverless function's time limit; the client calls repeatedly,
    passing the returned next_offset, until status == "done". This is the only
    approach that reliably completes within a short function budget."""
    if not DATABASE_URL or not _DIRECTORY_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Directory database not available")
    page_size = 500
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        offset = max(0, int(body.get("offset", 0) or 0))
    except (TypeError, ValueError):
        offset = 0

    try:
        # On the first page: short-circuit if data is already fresh, and make
        # sure ZIP centroids are seeded for the coordinate fallback.
        if offset == 0:
            from db.directory import get_sync_status as _gss
            status = await asyncio.to_thread(_gss)
            fh = status.get("data_freshness_hours")
            total = status.get("total_active_facilities", 0)
            if total > 0 and fh is not None and fh < 1:
                return JSONResponse({"status": "done", "total_active_facilities": total,
                                     "message": "Sync completed recently — no refresh needed"})
            from db.directory import seed_zip_coordinates as _seed
            csv_path = str(BASE_DIR / "data" / "ca_zips.csv")
            if os.path.exists(csv_path):
                await asyncio.to_thread(_seed, csv_path)

        from services.directory_sync import run_sync_page
        result = await asyncio.to_thread(run_sync_page, offset, page_size)

        if result["fetched"] < page_size:
            # Last page — record a successful sync so freshness updates.
            from db.directory import start_sync_log, finish_sync_log, get_sync_status
            log_id = await asyncio.to_thread(start_sync_log, "chunk")
            await asyncio.to_thread(finish_sync_log, log_id, result["upserted"], 0, "success")
            final = await asyncio.to_thread(get_sync_status)
            return JSONResponse({"status": "done", "upserted": result["upserted"],
                                 "total_active_facilities": final.get("total_active_facilities", 0)})
        return JSONResponse({"status": "running", "next_offset": offset + page_size,
                             "upserted": result["upserted"]})
    except Exception as e:
        try:
            from db.directory import start_sync_log, finish_sync_log
            log_id = await asyncio.to_thread(start_sync_log, "chunk")
            await asyncio.to_thread(finish_sync_log, log_id, 0, 0, "error", str(e))
        except Exception:
            pass
        return JSONResponse({"status": "error", "error": str(e)})


@app.get("/api/directory/debug-fetch")
@limiter.limit("20/hour")
async def directory_debug_fetch(request: Request, ctx: OrgContext = Depends(get_current_org)):
    """Diagnostic: report exactly what the deployment sees when calling the CMS
    endpoint (POST + GET), plus a control request to a known-reachable host."""
    from services.directory_sync import debug_cms_fetch
    result = await asyncio.to_thread(debug_cms_fetch)
    return JSONResponse(result)


@app.get("/api/directory/cron-sync")
@limiter.limit("12/hour")
async def directory_cron_sync(request: Request):
    """Vercel Cron target. Runs the directory sync synchronously when data is
    missing or stale. Protected by CRON_SECRET when configured (Vercel sends it
    as `Authorization: Bearer <CRON_SECRET>`)."""
    secret = os.getenv("CRON_SECRET")
    if secret and request.headers.get("authorization", "") != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not DATABASE_URL or not _DIRECTORY_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Directory database not available")
    try:
        from db.directory import get_sync_status as _gss
        status = await asyncio.to_thread(_gss)
        fh = status.get("data_freshness_hours")
        total = status.get("total_active_facilities", 0)
        if total > 0 and fh is not None and fh < 12:
            return JSONResponse({"message": "fresh", "data_freshness_hours": fh,
                                 "total_active_facilities": total})
        from services.directory_sync import run_full_sync as _rfs
        result = await asyncio.to_thread(_rfs, "cron")
        return JSONResponse({"message": "sync complete", **result})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/directory/sync-status")
@limiter.limit("120/hour")
async def directory_sync_status_endpoint(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _DIRECTORY_DB_AVAILABLE:
        return JSONResponse({"last_sync": None, "total_active_facilities": 0})
    try:
        from db.directory import get_sync_status as _gss
        import datetime as _dt
        status = await asyncio.to_thread(_gss)
        def _ser(v):
            if isinstance(v, (_dt.datetime, _dt.date)): return v.isoformat()
            return v
        if status.get("last_sync"):
            status["last_sync"] = {k: _ser(v) for k, v in status["last_sync"].items()}
        return JSONResponse(status)
    except Exception as e:
        return JSONResponse({"last_sync": None, "total_active_facilities": 0, "error": str(e)})


# ── Eligibility endpoints ─────────────────────────────────────────────────────

@app.get("/api/eligibility/payers")
@limiter.limit("120/hour")
async def eligibility_payers(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not _ELIGIBILITY_AVAILABLE:
        return JSONResponse({"payers": []})
    return JSONResponse({"payers": [
        {"payer_id": v["payer_id"], "name": v["name"]}
        for v in _KNOWN_PAYERS.values()
    ]})


@app.post("/api/eligibility/mock")
@limiter.limit("60/hour")
async def eligibility_mock_endpoint(request: Request, body: dict[str, Any] = Body(default={}),
                                    ctx: OrgContext = Depends(get_current_org)):
    if not _ELIGIBILITY_AVAILABLE:
        return JSONResponse({"error": "Eligibility service unavailable"}, status_code=503)
    payer_name = body.get("payer_name", "Medicare Traditional")
    payer_id, resolved_name = _detect_payer_id(payer_name)
    result = _get_mock_result(payer_id, resolved_name)
    import dataclasses
    return JSONResponse(dataclasses.asdict(result))


@app.post("/api/eligibility/check")
@limiter.limit("30/hour")
async def eligibility_check_endpoint(request: Request, body: dict[str, Any] = Body(default={}),
                                     ctx: OrgContext = Depends(get_current_org)):
    if not _ELIGIBILITY_AVAILABLE:
        return JSONResponse({"error": "Eligibility service unavailable"}, status_code=503)
    if not ELIGIBILITY_ENABLED:
        return JSONResponse(
            {"error": "Eligibility verification not enabled. Set ELIGIBILITY_ENABLED=true."},
            status_code=503,
        )
    stedi_key = os.getenv("STEDI_API_KEY", "").strip()
    if not stedi_key:
        return JSONResponse({"error": "STEDI_API_KEY not configured"}, status_code=503)
    member_id = body.get("member_id", "").strip()
    payer_id = body.get("payer_id", "").strip()
    npi = os.getenv("HOSPITAL_NPI", body.get("npi", "")).strip()
    first = body.get("first_name", "").strip()
    last = body.get("last_name", "").strip()
    dob = body.get("date_of_birth", "").strip()
    if not all([member_id, payer_id, npi]):
        return JSONResponse({"error": "member_id, payer_id, and npi are required"}, status_code=400)
    import dataclasses
    # Try DB cache first
    if DATABASE_URL and _PATIENT_DB_AVAILABLE:
        try:
            from db.patients import get_cached_eligibility as _gce
            _ck = _elig_cache_key(member_id, payer_id,
                                   datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            cached = await asyncio.to_thread(_gce, _ck)
            if cached:
                cached["source"] = "cache"
                return JSONResponse(cached)
        except Exception:
            pass
    try:
        result = await _check_eligibility(member_id, first, last, dob, payer_id, npi)
        result_dict = dataclasses.asdict(result)
        if DATABASE_URL and _PATIENT_DB_AVAILABLE:
            try:
                from db.patients import cache_eligibility_result as _cer
                _ck = _elig_cache_key(member_id, payer_id,
                                       datetime.now(timezone.utc).strftime("%Y-%m-%d"))
                await asyncio.to_thread(_cer, _ck, result_dict, payer_id)
            except Exception:
                pass
        return JSONResponse(result_dict)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    except Exception as e:
        return JSONResponse({"error": f"Eligibility check failed: {str(e)}"}, status_code=500)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "settings.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/settings")
@limiter.limit("60/hour")
async def get_settings(request: Request, ctx: OrgContext = Depends(get_current_org)):
    return JSONResponse({
        "eligibility_enabled": ELIGIBILITY_ENABLED,
        "eligibility_mock": ELIGIBILITY_MOCK,
        "stedi_configured": bool(os.getenv("STEDI_API_KEY", "")),
        "hospital_npi_configured": bool(os.getenv("HOSPITAL_NPI", "")),
        "db_available": _PATIENT_DB_AVAILABLE,
        "directory_available": _DIRECTORY_DB_AVAILABLE,
        "eligibility_service_available": _ELIGIBILITY_AVAILABLE,
    })


# ── Measured ROI Outcomes Engine ─────────────────────────────────────────────

@app.get("/roi-measured", response_class=HTMLResponse)
async def roi_measured_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "roi-measured.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/roi/dashboard")
@limiter.limit("30/hour")
async def roi_dashboard(request: Request, months: int = 12,
                        ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        return JSONResponse({
            "settings": {"hospital_type": "nonprofit", "cost_per_day": 4000},
            "totals": _aggregate_org_roi([]) if _ROI_ENGINE_AVAILABLE else {},
            "monthly_trend": [],
            "drg_breakdown": [],
            "clinician_breakdown": [],
            "data_quality": {"episodes_without_drg": 0, "completeness_pct": 0, "recommendation": ""},
            "unavailable": True,
        })
    from db.patients import get_org_domain
    org_domain = get_org_domain(ctx.email)
    try:
        data = await asyncio.to_thread(_get_roi_dashboard_data, org_domain, months)
        return JSONResponse(data)
    except Exception as _e:
        logging.getLogger(__name__).warning("ROI dashboard DB error: %s", _e)
        return JSONResponse({
            "settings": {"hospital_type": "nonprofit", "cost_per_day": 4000},
            "totals": _aggregate_org_roi([]) if _ROI_ENGINE_AVAILABLE else {},
            "monthly_trend": [],
            "drg_breakdown": [],
            "clinician_breakdown": [],
            "data_quality": {"episodes_without_drg": 0, "completeness_pct": 0, "recommendation": ""},
            "unavailable": True,
            "db_error": str(_e),
        })


@app.get("/api/roi/outcomes")
@limiter.limit("30/hour")
async def list_roi_outcomes(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    drg_code: str = None,
    clinician: str = None,
    ctx: OrgContext = Depends(get_current_org),
):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        return JSONResponse({"outcomes": [], "total": 0, "unavailable": True})
    from db.patients import get_org_domain
    from datetime import date as _date
    org_domain = get_org_domain(ctx.email)
    sd = _date.fromisoformat(start_date) if start_date else None
    ed = _date.fromisoformat(end_date) if end_date else None
    try:
        outcomes = await asyncio.to_thread(
            _get_org_roi_outcomes, org_domain, sd, ed, drg_code, clinician
        )
        return JSONResponse({"outcomes": outcomes, "total": len(outcomes)})
    except Exception as _e:
        logging.getLogger(__name__).warning("ROI outcomes DB error: %s", _e)
        return JSONResponse({"outcomes": [], "total": 0, "unavailable": True})


@app.get("/api/roi/outcomes/{patient_id}")
@limiter.limit("60/hour")
async def get_patient_roi_outcome_endpoint(request: Request, patient_id: int,
                                           ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        raise HTTPException(status_code=503, detail="ROI engine not available")
    from db.patients import get_org_domain
    org_domain = get_org_domain(ctx.email)
    outcome = await asyncio.to_thread(_get_roi_outcome, patient_id, org_domain)
    if not outcome:
        raise HTTPException(status_code=404, detail="No ROI outcome recorded for this patient")
    return JSONResponse({"outcome": outcome})


@app.post("/api/roi/outcomes/{patient_id}/calculate")
@limiter.limit("30/hour")
async def recalculate_patient_roi(request: Request, patient_id: int,
                                   ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        raise HTTPException(status_code=503, detail="ROI engine not available")
    from db.patients import get_org_domain, get_patient_detail
    org_domain = get_org_domain(ctx.email)
    patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    outcome = await asyncio.to_thread(_trigger_outcome_calculation, patient_id, org_domain)
    if not outcome:
        return JSONResponse({"outcome": None, "message": "Discharge date required to calculate ROI"})
    return JSONResponse({"outcome": outcome})


@app.patch("/api/patients/{patient_id}/discharge-data")
@limiter.limit("60/hour")
async def update_discharge_data(request: Request, patient_id: int,
                                 ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _PATIENT_DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Database not available")
    from db.patients import get_org_domain, get_patient_detail
    org_domain = get_org_domain(ctx.email)
    patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    body = await request.json()

    # Validate allowed fields
    allowed_fields = {
        "actual_discharge_date", "drg_code", "drg_description",
        "discharge_destination", "was_readmitted", "readmission_date", "readmission_dx",
    }
    updates = {k: v for k, v in body.items() if k in allowed_fields}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid discharge fields provided")

    # Compute actual_los_days if we have both dates
    admission = patient.get("admission_date")
    discharge = updates.get("actual_discharge_date")
    if discharge and admission:
        from datetime import date as _date
        try:
            d_date = _date.fromisoformat(str(discharge))
            a_date = admission if isinstance(admission, _date) else _date.fromisoformat(str(admission))
            updates["actual_los_days"] = (d_date - a_date).days
        except (ValueError, TypeError):
            pass

    # DRG description lookup if drg_code provided without description
    if "drg_code" in updates and not updates.get("drg_description") and _ROI_ENGINE_AVAILABLE:
        drg_ref = await asyncio.to_thread(_get_drg_reference, updates["drg_code"])
        if drg_ref:
            updates["drg_description"] = drg_ref["drg_description"]

    # Build SET clause
    set_parts = ", ".join(f"{k} = %s" for k in updates)
    values = list(updates.values()) + [patient_id]

    from db.connection import get_db_conn as _get_db_conn
    conn = _get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE patients SET {set_parts}, updated_at = NOW() WHERE id = %s",
                    values,
                )
    finally:
        conn.close()

    # Trigger ROI recalculation
    roi_outcome = None
    if _ROI_ENGINE_AVAILABLE and updates.get("actual_discharge_date"):
        roi_outcome = await asyncio.to_thread(_trigger_outcome_calculation, patient_id, org_domain)

    updated_patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
    return JSONResponse({
        "patient": updated_patient,
        "roi_outcome": roi_outcome,
    })


@app.get("/api/drg/search")
@limiter.limit("120/hour")
async def drg_search_endpoint(request: Request, q: str = "",
                               ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        return JSONResponse({"results": []})
    if len(q) < 2:
        return JSONResponse({"results": []})
    results = await asyncio.to_thread(_search_drg, q)
    return JSONResponse({"results": results})


@app.get("/api/roi/settings")
@limiter.limit("60/hour")
async def get_roi_settings_endpoint(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        return JSONResponse({"hospital_type": "nonprofit", "cost_per_day": 4000})
    from db.patients import get_org_domain
    org_domain = get_org_domain(ctx.email)
    settings = await asyncio.to_thread(_get_org_roi_settings, org_domain)
    return JSONResponse(settings)


@app.patch("/api/roi/settings")
@limiter.limit("10/hour")
async def update_roi_settings(request: Request, body: dict = Body(default={}),
                               ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        raise HTTPException(status_code=503, detail="ROI engine not available")
    from db.patients import get_org_domain
    org_domain = get_org_domain(ctx.email)
    settings = await asyncio.to_thread(_upsert_org_roi_settings, org_domain, body)
    return JSONResponse(settings)


@app.get("/api/roi/export")
@limiter.limit("10/hour")
async def export_roi_csv(
    request: Request,
    start_date: str = None,
    end_date: str = None,
    ctx: OrgContext = Depends(get_current_org),
):
    if not DATABASE_URL or not _ROI_ENGINE_AVAILABLE:
        raise HTTPException(status_code=503, detail="ROI engine not available")
    from db.patients import get_org_domain
    from datetime import date as _date
    import csv, io as _io

    org_domain = get_org_domain(ctx.email)
    sd = _date.fromisoformat(start_date) if start_date else None
    ed = _date.fromisoformat(end_date) if end_date else None
    outcomes = await asyncio.to_thread(_get_org_roi_outcomes, org_domain, sd, ed)

    output = _io.StringIO()
    # Methodology header
    output.write(
        "# Discharge Planning AI Measured ROI Export | "
        "Baseline: CMS FY 2026 IPPS Final Rule Table 5 geometric mean LOS | "
        f"Cost per day: AHA 2024 CA defaults\n"
    )
    writer = csv.writer(output)
    writer.writerow([
        "episode_id", "drg_code", "drg_description",
        "admission_date", "discharge_date",
        "actual_los", "drg_expected_los", "excess_days_saved",
        "cost_savings", "hrrp_flagged", "hrrp_avoided",
        "tcm_revenue", "total_value",
        "discharge_destination", "barriers_identified", "barriers_resolved",
        "avg_barrier_resolution_hours",
    ])
    for o in outcomes:
        writer.writerow([
            o.get("id"),
            o.get("drg_code", ""),
            o.get("drg_description", ""),
            o.get("admission_date", ""),
            o.get("actual_discharge_date", ""),
            o.get("actual_los_days", ""),
            o.get("drg_geometric_mean_los", ""),
            o.get("excess_days_saved", ""),
            o.get("cost_savings_dollars", ""),
            o.get("hrrp_condition_flagged", False),
            o.get("hrrp_penalty_avoided", ""),
            o.get("tcm_revenue", 0),
            o.get("total_value_dollars", 0),
            o.get("discharge_destination", ""),
            o.get("barriers_identified", 0),
            o.get("barriers_resolved", 0),
            o.get("avg_barrier_resolution_hours", ""),
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    filename = f"roi_export_{org_domain.replace('.', '_')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Pilot Programme & TCM ROI Calculator routes ──────────────────────────────

@app.get("/tcm-roi-calculator", response_class=HTMLResponse)
async def tcm_roi_calculator_page(request: Request):
    with open(STATIC_DIR / "tcm-roi-calculator.html", encoding="utf-8") as f:
        return f.read()


@app.get("/pilot", response_class=HTMLResponse)
async def pilot_page_route(request: Request):
    with open(STATIC_DIR / "pilot.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/pilot/spots")
async def pilot_spots(request: Request):
    if not DATABASE_URL:
        return JSONResponse({"total_spots": 5, "confirmed_pilots": 0, "remaining": 5})
    try:
        from db.connection import get_db_conn as _gdc
        conn = _gdc()
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS n FROM pilot_applications WHERE status = 'confirmed'")
                    confirmed = cur.fetchone()["n"] or 0
        finally:
            conn.close()
        remaining = max(0, 5 - confirmed)
        return JSONResponse({"total_spots": 5, "confirmed_pilots": confirmed, "remaining": remaining})
    except Exception as _e:
        return JSONResponse({"total_spots": 5, "confirmed_pilots": 0, "remaining": 5})


@app.post("/api/pilot/apply")
@limiter.limit("3/hour")
async def pilot_apply(request: Request, body: dict = Body(default={})):
    hospital_name = (body.get("hospital_name") or "").strip()
    applicant_name = (body.get("applicant_name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    licensed_beds = body.get("licensed_beds")
    consent_revenue_share = body.get("consent_revenue_share", False)
    consent_ca_hospital = body.get("consent_ca_hospital", False)

    if not hospital_name:
        raise HTTPException(status_code=400, detail="Hospital name is required")
    if not applicant_name:
        raise HTTPException(status_code=400, detail="Your name is required")
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Valid work email is required")
    if not consent_revenue_share or not consent_ca_hospital:
        raise HTTPException(status_code=400, detail="Both acknowledgments are required")
    if licensed_beds is not None:
        try:
            if int(licensed_beds) < 100:
                raise HTTPException(status_code=400, detail="Pilot is open to hospitals with 100+ licensed beds")
        except (ValueError, TypeError):
            pass

    if DATABASE_URL:
        try:
            from db.connection import get_db_conn as _gdc
            conn = _gdc()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute("""
                            INSERT INTO pilot_applications
                            (hospital_name, applicant_name, applicant_title, email, phone,
                             licensed_beds, ehr_system, annual_discharges, how_found,
                             challenge_text, calculator_inputs)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            hospital_name, applicant_name,
                            body.get("applicant_title"), email, body.get("phone"),
                            licensed_beds, body.get("ehr_system"),
                            body.get("annual_discharges"), body.get("how_found"),
                            body.get("challenge_text"),
                            json.dumps(body.get("calculator_inputs", {})),
                        ))
            finally:
                conn.close()
        except Exception as _e:
            logging.getLogger(__name__).warning("Pilot apply DB error: %s", _e)

    logging.getLogger("pilot.applications").info(
        "New pilot application: hospital=%s email_domain=%s beds=%s",
        hospital_name[:50], email.split("@")[-1], licensed_beds,
    )
    first_name = applicant_name.split()[0] if applicant_name else applicant_name
    return JSONResponse({
        "ok": True,
        "message": (
            f"Thank you, {first_name}. Your application for {hospital_name} has been received. "
            f"We'll respond to {email} within 2 business days."
        ),
    })


@app.get("/api/tcm/platform-roi")
@limiter.limit("60/hour")
async def tcm_platform_roi(request: Request, ctx: OrgContext = Depends(get_current_org)):
    import datetime as _dt
    from db.patients import get_org_domain as _god
    org_domain = _god(ctx.email)

    settings = {}
    if DATABASE_URL:
        try:
            from db.roi import get_org_roi_settings as _gros
            settings = await asyncio.to_thread(_gros, org_domain)
        except Exception:
            pass

    subscription_monthly = float(settings.get("platform_subscription_monthly") or 7000)
    annual_beds = int(settings.get("license_beds") or 250)
    annual_discharges = int(settings.get("annual_discharges") or 10000)

    monthly_revenue = 0.0
    alltime_revenue = 0.0
    total_episodes = 0
    completed_episodes = 0

    if DATABASE_URL:
        try:
            from db.connection import get_db_conn as _gdc
            conn = _gdc()
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT COUNT(*) AS n, COALESCE(SUM(estimated_revenue),0) AS rev "
                            "FROM tcm_episodes WHERE org_id = %s AND status IN ('claim_ready','billed')",
                            (ctx.org_id,)
                        )
                        row = cur.fetchone()
                        completed_episodes = int(row["n"] or 0)
                        alltime_revenue = float(row["rev"] or 0)

                        first_of_month = _dt.date.today().replace(day=1)
                        cur.execute(
                            "SELECT COALESCE(SUM(estimated_revenue),0) AS rev "
                            "FROM tcm_episodes WHERE org_id = %s AND status IN ('claim_ready','billed') "
                            "AND discharge_date >= %s",
                            (ctx.org_id, first_of_month)
                        )
                        monthly_revenue = float(cur.fetchone()["rev"] or 0)

                        cur.execute("SELECT COUNT(*) AS n FROM tcm_episodes WHERE org_id = %s", (ctx.org_id,))
                        total_episodes = int(cur.fetchone()["n"] or 0)
            finally:
                conn.close()
        except Exception as _e:
            logging.getLogger(__name__).warning("TCM platform ROI query failed: %s", _e)

    annual_sub = subscription_monthly * 12
    annual_current = monthly_revenue * 12 if monthly_revenue > 0 else (alltime_revenue if alltime_revenue > 0 else 0)
    annual_net = annual_current - annual_sub
    annual_roi = round(annual_current / annual_sub, 2) if annual_sub > 0 else 0

    # 50% capture projection using CA-adjusted 2026 rates
    tcm_50_episodes = annual_discharges * 0.44 * 0.65 * 0.50
    avg_rate = (259.60 * 0.70 + 351.64 * 0.30) * 0.60 + (220 * 0.70 + 298 * 0.30) * 0.40
    annual_50pct = round(tcm_50_episodes * avg_rate, 2)

    calculator_url = f"/tcm-roi-calculator?beds={annual_beds}&discharges={annual_discharges}&target_capture=50"

    return JSONResponse({
        "monthly_tcm_revenue": round(monthly_revenue, 2),
        "alltime_tcm_revenue": round(alltime_revenue, 2),
        "subscription_monthly": subscription_monthly,
        "coverage_ratio_monthly": round(monthly_revenue / subscription_monthly, 2) if subscription_monthly > 0 else 0,
        "total_episodes": total_episodes,
        "completed_episodes": completed_episodes,
        "annual_projection_current": round(annual_current, 2),
        "annual_projection_50pct": annual_50pct,
        "annual_sub_cost": round(annual_sub, 2),
        "annual_net_current": round(annual_net, 2),
        "annual_roi_current": annual_roi,
        "calculator_share_url": calculator_url,
    })


# ── Referral Workflow ─────────────────────────────────────────────────────────

@app.get("/ward-referrals", response_class=HTMLResponse)
async def ward_referrals_page(request: Request, ctx: OrgContext = Depends(get_current_org)):
    return HTMLResponse((STATIC_DIR / "ward-referrals.html").read_text())


@app.post("/api/referrals")
@limiter.limit("60/hour")
async def create_referral_endpoint(request: Request, body: dict = Body(...), ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        raise HTTPException(503, "Referrals module unavailable")
    org_domain = _get_org_domain(ctx.email)
    ref = await asyncio.to_thread(_create_referral, body.get("patient_id"), org_domain, ctx.email, body)
    return JSONResponse(ref)


@app.get("/api/referrals")
@limiter.limit("120/hour")
async def list_referrals_endpoint(
    request: Request,
    patient_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    ctx: OrgContext = Depends(get_current_org),
):
    if not _REFERRALS_AVAILABLE:
        return JSONResponse({"referrals": [], "total": 0})
    org_domain = _get_org_domain(ctx.email)
    refs = await asyncio.to_thread(_list_referrals, org_domain, patient_id, status, limit, offset)
    return JSONResponse({"referrals": refs, "total": len(refs)})


@app.get("/api/referrals/analytics")
@limiter.limit("30/hour")
async def referral_analytics_endpoint(request: Request, days: int = 90, ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        return JSONResponse({"by_status": {}, "by_channel": {}, "total": 0})
    org_domain = _get_org_domain(ctx.email)
    data = await asyncio.to_thread(_get_referral_analytics, org_domain, days)
    return JSONResponse(data)


@app.get("/api/referrals/settings")
@limiter.limit("60/hour")
async def get_referral_settings_endpoint(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        return JSONResponse({"default_channel": "fax"})
    org_domain = _get_org_domain(ctx.email)
    settings = await asyncio.to_thread(_get_org_referral_settings, org_domain)
    return JSONResponse(settings)


@app.patch("/api/referrals/settings")
@limiter.limit("30/hour")
async def patch_referral_settings_endpoint(request: Request, body: dict = Body(...), ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        raise HTTPException(503, "Referrals module unavailable")
    org_domain = _get_org_domain(ctx.email)
    settings = await asyncio.to_thread(_upsert_org_referral_settings, org_domain, body)
    return JSONResponse(settings)


@app.get("/api/referrals/delivery-status")
@limiter.limit("60/hour")
async def referral_delivery_status_endpoint(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        return JSONResponse({"fax": False, "careport": False, "direct": False})
    status = _get_delivery_status()
    return JSONResponse(status)


@app.get("/api/referrals/{referral_id}")
@limiter.limit("120/hour")
async def get_referral_endpoint(request: Request, referral_id: int, ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        raise HTTPException(503, "Referrals module unavailable")
    org_domain = _get_org_domain(ctx.email)
    ref = await asyncio.to_thread(_get_referral, referral_id, org_domain)
    if not ref:
        raise HTTPException(404, "Referral not found")
    return JSONResponse(ref)


@app.patch("/api/referrals/{referral_id}/status")
@limiter.limit("60/hour")
async def update_referral_status_endpoint(
    request: Request,
    referral_id: int,
    body: dict = Body(...),
    ctx: OrgContext = Depends(get_current_org),
):
    if not _REFERRALS_AVAILABLE:
        raise HTTPException(503, "Referrals module unavailable")
    org_domain = _get_org_domain(ctx.email)
    status = body.get("status", "")
    valid = {"draft", "sent", "pending_review", "accepted", "declined", "cancelled"}
    if status not in valid:
        raise HTTPException(422, f"Invalid status. Must be one of: {', '.join(sorted(valid))}")
    ref = await asyncio.to_thread(_update_referral_status, referral_id, org_domain, status, ctx.email, body.get("notes"))
    if not ref:
        raise HTTPException(404, "Referral not found")
    return JSONResponse(ref)


@app.post("/api/referrals/{referral_id}/send")
@limiter.limit("30/hour")
async def send_referral_endpoint(request: Request, referral_id: int, ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        raise HTTPException(503, "Referrals module unavailable")
    org_domain = _get_org_domain(ctx.email)
    ref = await asyncio.to_thread(_get_referral, referral_id, org_domain)
    if not ref:
        raise HTTPException(404, "Referral not found")

    channel = ref.get("delivery_channel") or "manual"
    result = {"success": False, "channel": channel, "error": "No delivery attempted"}

    if channel == "fax" and ref.get("facility_fax"):
        packet_html = ref.get("packet_html") or ""
        result = await _send_via_fax(referral_id, ref["facility_fax"], packet_html, ref.get("facility_ccn", ""))
    elif channel == "careport":
        fhir_sr = ref.get("fhir_service_request") or {}
        result = await _send_via_careport(referral_id, fhir_sr, ref.get("facility_ccn", ""))
    elif channel == "manual":
        result = {"success": True, "channel": "manual", "reference_id": None, "error": None}

    await asyncio.to_thread(
        _log_delivery_attempt,
        referral_id, channel, result.get("success", False),
        result.get("reference_id"), result.get("error")
    )

    if result.get("success"):
        await asyncio.to_thread(_update_referral_status, referral_id, org_domain, "sent", ctx.email, None)

    return JSONResponse(result)


@app.post("/api/referrals/{referral_id}/resend")
@limiter.limit("20/hour")
async def resend_referral_endpoint(request: Request, referral_id: int, ctx: OrgContext = Depends(get_current_org)):
    return await send_referral_endpoint(request, referral_id, ctx)


@app.get("/api/referrals/{referral_id}/delivery-log")
@limiter.limit("60/hour")
async def referral_delivery_log_endpoint(request: Request, referral_id: int, ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        return JSONResponse({"log": []})
    org_domain = _get_org_domain(ctx.email)
    ref = await asyncio.to_thread(_get_referral, referral_id, org_domain)
    if not ref:
        raise HTTPException(404, "Referral not found")
    log = await asyncio.to_thread(_get_delivery_log, referral_id)
    return JSONResponse({"log": log})


@app.get("/api/referrals/{referral_id}/messages")
@limiter.limit("60/hour")
async def get_referral_messages_endpoint(request: Request, referral_id: int, ctx: OrgContext = Depends(get_current_org)):
    if not _REFERRALS_AVAILABLE:
        return JSONResponse({"messages": []})
    org_domain = _get_org_domain(ctx.email)
    ref = await asyncio.to_thread(_get_referral, referral_id, org_domain)
    if not ref:
        raise HTTPException(404, "Referral not found")
    msgs = await asyncio.to_thread(_get_referral_messages, referral_id, org_domain)
    return JSONResponse({"messages": msgs})


@app.post("/api/referrals/{referral_id}/messages")
@limiter.limit("60/hour")
async def add_referral_message_endpoint(
    request: Request,
    referral_id: int,
    body: dict = Body(...),
    ctx: OrgContext = Depends(get_current_org),
):
    if not _REFERRALS_AVAILABLE:
        raise HTTPException(503, "Referrals module unavailable")
    org_domain = _get_org_domain(ctx.email)
    ref = await asyncio.to_thread(_get_referral, referral_id, org_domain)
    if not ref:
        raise HTTPException(404, "Referral not found")
    text = (body.get("message_text") or "").strip()
    if not text:
        raise HTTPException(422, "message_text required")
    msg = await asyncio.to_thread(_add_referral_message, referral_id, org_domain, ctx.email, text)
    return JSONResponse(msg)


# ── PWA routes ───────────────────────────────────────────────────────────────

@app.get("/sw.js")
async def service_worker(request: Request):
    """Serve the service worker from the root scope (must not be under /static/)."""
    sw_path = STATIC_DIR / "sw.js"
    content = sw_path.read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


@app.get("/manifest.json")
async def web_manifest(request: Request):
    manifest_path = STATIC_DIR / "manifest.json"
    return Response(
        content=manifest_path.read_bytes(),
        media_type="application/manifest+json",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/offline", response_class=HTMLResponse)
async def offline_page(request: Request):
    """Offline fallback page — no auth required so the SW can serve it."""
    with open(STATIC_DIR / "offline.html", encoding="utf-8") as f:
        return f.read()


# ── Discharge Milestone / Barrier Tracking API ───────────────────────────────

@app.get("/ward-barriers", response_class=HTMLResponse)
async def ward_barriers_page(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "ward-barriers.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/milestones/catalog")
@limiter.limit("120/hour")
async def get_milestone_catalog(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not _MILESTONES_AVAILABLE:
        return JSONResponse({"catalog": [], "categories": {}})
    from db.milestones_catalog import BARRIER_CATALOG, BARRIER_CATEGORIES
    catalog = [
        {"barrier_type": k, **{f: v for f, v in info.items() if f != "auto_detect_keywords"}}
        for k, info in BARRIER_CATALOG.items()
    ]
    return JSONResponse({"catalog": catalog, "categories": BARRIER_CATEGORIES})


@app.get("/api/milestones/ward-summary")
@limiter.limit("60/hour")
async def ward_milestone_summary(request: Request, ctx: OrgContext = Depends(get_current_org)):
    if not DATABASE_URL or not _MILESTONES_AVAILABLE:
        return JSONResponse({"summary": {}})
    try:
        from db.patients import get_org_domain
        org_domain = get_org_domain(ctx.email)
        raw = await asyncio.to_thread(_get_org_milestone_summary, org_domain)
        summary = {
            "open_count": raw.get("total_open", 0),
            "overdue_count": raw.get("overdue", 0),
            "resolved_today": raw.get("resolved_today", 0),
            "patients_with_barriers": len(raw.get("by_patient", [])),
            "by_category": raw.get("by_category", {}),
            "by_patient": raw.get("by_patient", []),
        }
        return JSONResponse({"summary": summary})
    except Exception as e:
        return JSONResponse({"summary": {}, "error": str(e)}, status_code=500)


@app.get("/api/patients/{patient_id}/milestones/summary")
@limiter.limit("120/hour")
async def patient_milestone_summary(
    request: Request, patient_id: int,
    ctx: OrgContext = Depends(get_current_org),
):
    if not DATABASE_URL or not _MILESTONES_AVAILABLE:
        return JSONResponse({"open": 0, "overdue": 0})
    try:
        from db.patients import get_patient_detail, get_org_domain
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        counts = await asyncio.to_thread(_get_open_milestone_count, patient_id, org_domain)
        return JSONResponse({"open": counts["total_open"], "overdue": counts["overdue"]})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"open": 0, "overdue": 0, "error": str(e)}, status_code=500)


@app.get("/api/patients/{patient_id}/milestones")
@limiter.limit("120/hour")
async def list_patient_milestones(
    request: Request, patient_id: int,
    include_resolved: bool = False,
    ctx: OrgContext = Depends(get_current_org),
):
    if not DATABASE_URL or not _MILESTONES_AVAILABLE:
        return JSONResponse({"milestones": []})
    try:
        from db.patients import get_patient_detail, get_org_domain
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        milestones = await asyncio.to_thread(
            _get_milestones_for_patient, patient_id, org_domain, include_resolved
        )
        return JSONResponse({"milestones": milestones, "total": len(milestones)})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"milestones": [], "error": str(e)}, status_code=500)


@app.post("/api/patients/{patient_id}/milestones")
@limiter.limit("60/hour")
async def create_patient_milestone(
    request: Request, patient_id: int,
    body: dict = Body(default={}),
    ctx: OrgContext = Depends(get_current_org),
):
    if not DATABASE_URL or not _MILESTONES_AVAILABLE:
        raise HTTPException(status_code=503, detail="Milestone service not available")
    try:
        from db.patients import get_patient_detail, get_org_domain
        from datetime import datetime as _dt_cls
        org_domain = get_org_domain(ctx.email)
        patient = await asyncio.to_thread(get_patient_detail, patient_id, org_domain)
        if not patient:
            raise HTTPException(status_code=404, detail="Patient not found")
        due_date_raw = body.get("due_date")
        due_date = _dt_cls.fromisoformat(due_date_raw) if due_date_raw else None
        milestone = await asyncio.to_thread(
            _create_milestone,
            patient_id, org_domain,
            body.get("barrier_type", "custom"),
            ctx.email,
            body.get("description", ""),
            body.get("priority", "medium"),
            body.get("assigned_to"),
            due_date,
            "manual",
        )
        result = dict(milestone) if not isinstance(milestone, dict) else milestone
        return JSONResponse({"milestone": result}, status_code=201)
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.patch("/api/patients/{patient_id}/milestones/{milestone_id}")
@limiter.limit("120/hour")
async def update_patient_milestone(
    request: Request, patient_id: int, milestone_id: int,
    body: dict = Body(default={}),
    ctx: OrgContext = Depends(get_current_org),
):
    if not DATABASE_URL or not _MILESTONES_AVAILABLE:
        raise HTTPException(status_code=503, detail="Milestone service not available")
    try:
        from db.patients import get_org_domain
        from datetime import datetime as _dt_cls
        org_domain = get_org_domain(ctx.email)
        existing = await asyncio.to_thread(_get_milestone_by_id, milestone_id, org_domain)
        if not existing or existing["patient_id"] != patient_id:
            raise HTTPException(status_code=404, detail="Milestone not found")
        due_date_raw = body.get("due_date")
        due_date = _dt_cls.fromisoformat(due_date_raw) if due_date_raw else None
        updated = await asyncio.to_thread(
            _update_milestone,
            milestone_id, org_domain, ctx.email,
            body.get("status"),
            body.get("priority"),
            body.get("assigned_to"),
            due_date,
            body.get("notes"),
            body.get("dismiss_reason"),
        )
        return JSONResponse({"milestone": updated})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.delete("/api/patients/{patient_id}/milestones/{milestone_id}")
@limiter.limit("60/hour")
async def delete_patient_milestone(
    request: Request, patient_id: int, milestone_id: int,
    ctx: OrgContext = Depends(get_current_org),
):
    if not DATABASE_URL or not _MILESTONES_AVAILABLE:
        raise HTTPException(status_code=503, detail="Milestone service not available")
    try:
        from db.patients import get_org_domain
        org_domain = get_org_domain(ctx.email)
        existing = await asyncio.to_thread(_get_milestone_by_id, milestone_id, org_domain)
        if not existing or existing["patient_id"] != patient_id:
            raise HTTPException(status_code=404, detail="Milestone not found")
        deleted = await asyncio.to_thread(_delete_milestone, milestone_id, org_domain, ctx.email)
        if not deleted:
            raise HTTPException(status_code=403, detail="Cannot delete AI-detected barriers; use dismiss instead")
        return JSONResponse({"success": True})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Legacy Epic SMART launch (kept for backward-compatibility) ────────────────
# New integrations should use /api/fhir/authorize?ehr=epic instead.

EPIC_CLIENT_ID = os.environ.get("NEXT_PUBLIC_EPIC_CLIENT_ID", "")

@app.get("/launch")
async def epic_launch_legacy(request: Request, iss: str, launch: str = None):  # pragma: no cover
    """Legacy EHR-embedded SMART launch. Redirects to the generic FHIR authorize flow."""
    redirect_url = f"/api/fhir/authorize?ehr=epic"
    if iss:
        redirect_url += f"&iss_override={iss}"
    if launch:
        redirect_url += f"&launch={launch}"
    return RedirectResponse(url=redirect_url)


@app.get("/api/auth/epic/callback")
async def epic_callback_legacy(request: Request, code: str = None, state: str = None, error: str = None):  # pragma: no cover
    """Legacy Epic callback — delegates to the unified FHIR callback handler."""
    return await fhir_callback(request, code=code, state=state, error=error)


# ── FHIR R4 connector routes ──────────────────────────────────────────────────

_fhir_audit_logger = logging.getLogger("fhir.audit")
logging.basicConfig(level=logging.INFO)
if _FHIR_IMPORT_ERROR:  # pragma: no cover
    _fhir_audit_logger.error("fhir package unavailable: %s", _FHIR_IMPORT_ERROR)


def _fhir_unavailable():  # pragma: no cover
    """Return 503 with the exact import error when fhir package couldn't load."""
    return JSONResponse(
        {"error": "FHIR connector unavailable", "detail": _FHIR_IMPORT_ERROR},
        status_code=503,
    )


@app.get("/api/fhir/ehrs")
async def list_fhir_ehrs(request: Request):  # pragma: no cover
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse({"ehrs": list_ehr_display()})


@app.get("/api/fhir/status")
async def fhir_config_status(request: Request):
    """Read-only EHR configuration diagnostic. Reports, per EHR, whether
    credentials are present and the resolved (non-secret) base/auth/token URLs,
    so an operator can confirm the live config at a glance. No secrets exposed."""
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from fhir.ehr_config import config_status
    return JSONResponse({
        "fhir_loaded": _FHIR_IMPORT_ERROR is None,
        "app_url": APP_URL,
        "redirect_uri": FHIR_REDIRECT_URI,
        "ehrs": config_status(),
    })


@app.get("/api/fhir/authorize")
async def fhir_authorize(  # pragma: no cover
    request: Request,
    ehr: str = "epic",
    iss_override: str = None,
    launch: str = None,
):
    """Begin SMART on FHIR authorization for the specified EHR.

    Generates PKCE pair and secure state, stores them in a signed HttpOnly
    cookie, then redirects the browser to the EHR's authorization endpoint.
    """
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        config = get_ehr_config(ehr)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    if not config.client_id:
        return JSONResponse(
            {"error": f"FHIR_CLIENT_ID_{ehr.upper()} is not configured on this server."},
            status_code=500,
        )

    # Resolve FHIR base and auth/token endpoints.
    # Priority: iss_override (EHR-embedded launch) > env var overrides > URL-derived defaults.
    fhir_base = iss_override or config.fhir_base_url

    if iss_override:
        # EHR-embedded launch supplies a hospital-specific ISS — must discover endpoints.
        try:
            smart_config = await discover_smart_endpoints(fhir_base)
            auth_endpoint = smart_config.get("authorization_endpoint", "")
            token_endpoint = smart_config.get("token_endpoint", "")
        except Exception as exc:
            _fhir_audit_logger.error(
                "SMART discovery failed for iss_override: ehr=%s error=%s", ehr, type(exc).__name__
            )
            return JSONResponse(
                {"error": "Could not reach the EHR SMART configuration endpoint. "
                          "Verify the EHR base URL is reachable."},
                status_code=502,
            )
    elif config.auth_endpoint_override and config.token_endpoint_override:
        # Use pre-configured endpoints (avoids a server-side SMART discovery call
        # that some EHRs block outside browser context).
        auth_endpoint = config.auth_endpoint_override
        token_endpoint = config.token_endpoint_override
    else:
        # Fallback: attempt SMART discovery for EHRs without hardcoded endpoints.
        try:
            smart_config = await discover_smart_endpoints(fhir_base)
            auth_endpoint = smart_config.get("authorization_endpoint", "")
            token_endpoint = smart_config.get("token_endpoint", "")
        except Exception as exc:
            _fhir_audit_logger.error("SMART discovery failed: ehr=%s error=%s", ehr, type(exc).__name__)
            return JSONResponse(
                {"error": "Could not reach EHR SMART configuration endpoint."}, status_code=502
            )

    if not auth_endpoint or not token_endpoint:
        return JSONResponse({"error": "EHR did not return SMART authorization endpoints."}, status_code=502)

    use_pkce = config.smart_version != "v1"
    if use_pkce:
        code_verifier, code_challenge = generate_pkce_pair()
    else:
        code_verifier = code_challenge = None

    state = generate_secure_state()

    auth_state = {
        "state": state,
        "code_verifier": code_verifier,
        "token_endpoint": token_endpoint,
        "fhir_base": fhir_base,
        "ehr": ehr,
        "user": user,
    }

    scopes = list(config.scopes)
    if launch:
        scopes = ["launch/patient"] + scopes

    params: dict = {
        "response_type": "code",
        "client_id": config.client_id,
        "redirect_uri": FHIR_REDIRECT_URI,
        "scope": " ".join(scopes),
        "state": state,
        # Epic requires `aud` (the FHIR base) for standalone launch in both
        # SMART v1 and v2; only PKCE is v2-specific.
        "aud": fhir_base,
    }
    if use_pkce:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    if launch:
        params["launch"] = launch

    auth_url = auth_endpoint + "?" + urlencode(params)

    _fhir_audit_logger.info("FHIR auth initiated: ehr=%s user=%s", ehr, user)

    response = RedirectResponse(url=auth_url, status_code=302)
    response.set_cookie(
        key=FHIR_STATE_COOKIE,
        value=encode_fhir_cookie(auth_state),
        max_age=FHIR_STATE_TTL,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    return response


@app.get("/api/fhir/callback")
async def fhir_callback(  # pragma: no cover
    request: Request,
    code: str = None,
    state: str = None,
    error: str = None,
):
    """OAuth callback — validates state, exchanges code for tokens, stores session cookie."""
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    if error:
        _fhir_audit_logger.warning("FHIR auth error from EHR: %s", error)
        return RedirectResponse(url=f"/?fhir_error={error}", status_code=302)

    if not code:
        return JSONResponse({"error": "Missing authorization code."}, status_code=400)

    raw_state = request.cookies.get(FHIR_STATE_COOKIE)
    if not raw_state:
        return RedirectResponse(url="/login?error=fhir_session_expired", status_code=302)

    auth_state = decode_fhir_state_cookie(raw_state)
    if not auth_state:
        return RedirectResponse(url="/login?error=fhir_session_invalid", status_code=302)

    if state != auth_state.get("state"):
        _fhir_audit_logger.warning("FHIR state mismatch — possible CSRF attempt")
        return RedirectResponse(url="/login?error=fhir_state_mismatch", status_code=302)

    ehr = auth_state["ehr"]
    try:
        config = get_ehr_config(ehr)
    except ValueError:
        return JSONResponse({"error": "Invalid EHR in session state."}, status_code=400)

    try:
        tokens = await exchange_code_for_token(
            code=code,
            token_endpoint=auth_state["token_endpoint"],
            client_id=config.client_id,
            redirect_uri=FHIR_REDIRECT_URI,
            code_verifier=auth_state.get("code_verifier"),
            client_secret=config.client_secret,
        )
    except Exception as exc:
        _fhir_audit_logger.error(
            "FHIR token exchange failed: ehr=%s error=%s", ehr, type(exc).__name__
        )
        return RedirectResponse(url="/?fhir_error=token_failed", status_code=302)

    if not tokens.get("access_token"):
        _fhir_audit_logger.error("FHIR token exchange returned no access_token: ehr=%s", ehr)
        return RedirectResponse(url="/?fhir_error=token_failed", status_code=302)

    patient_id = tokens.get("patient", "")
    expires_in = int(tokens.get("expires_in", 3600))

    # Store only tokens + metadata in session — no PHI
    session_data = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "token_endpoint": auth_state["token_endpoint"],
        "patient_id": patient_id,
        "expires_at": time.time() + expires_in,
        "fhir_base": auth_state["fhir_base"],
        "ehr": ehr,
        "user": auth_state.get("user", ""),
    }

    _fhir_audit_logger.info(
        "FHIR auth complete: ehr=%s user=%s has_patient_context=%s",
        ehr,
        auth_state.get("user", ""),
        bool(patient_id),
    )

    response = RedirectResponse(url=f"/?patient={patient_id}&source=fhir", status_code=302)
    response.set_cookie(
        key=FHIR_SESSION_COOKIE,
        value=encode_fhir_cookie(session_data),
        max_age=FHIR_SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=True,
    )
    response.delete_cookie(FHIR_STATE_COOKIE)
    return response


async def _get_valid_fhir_session(request: Request) -> tuple[dict | None, str | None]:  # pragma: no cover
    """Return (session_dict, updated_cookie_value).

    Performs silent token refresh if the access token is within 60 s of expiry.
    Returns (None, None) if no valid session exists or refresh fails.
    The caller must set the updated cookie on the response when it is not None.
    """
    raw = request.cookies.get(FHIR_SESSION_COOKIE)
    if not raw:
        return None, None

    session = decode_fhir_session_cookie(raw)
    if not session:
        return None, None

    if needs_refresh(session.get("expires_at", 0)):
        refresh_token = session.get("refresh_token")
        if not refresh_token:
            _fhir_audit_logger.warning(
                "FHIR session expired and no refresh_token: ehr=%s", session.get("ehr")
            )
            return None, None
        try:
            config = get_ehr_config(session["ehr"])
            new_tokens = await refresh_access_token(
                refresh_token=refresh_token,
                token_endpoint=session["token_endpoint"],
                client_id=config.client_id,
                client_secret=config.client_secret,
            )
            session["access_token"] = new_tokens["access_token"]
            session["expires_at"] = time.time() + int(new_tokens.get("expires_in", 3600))
            if new_tokens.get("refresh_token"):
                session["refresh_token"] = new_tokens["refresh_token"]
            _fhir_audit_logger.info(
                "FHIR token refreshed: ehr=%s user=%s", session["ehr"], session.get("user", "")
            )
            return session, encode_fhir_cookie(session)
        except Exception as exc:
            _fhir_audit_logger.warning(
                "FHIR token refresh failed: ehr=%s error=%s", session.get("ehr"), type(exc).__name__
            )
            return None, None

    return session, None


def _apply_refreshed_cookie(response, new_cookie: str | None) -> None:  # pragma: no cover
    if new_cookie:
        response.set_cookie(
            key=FHIR_SESSION_COOKIE,
            value=new_cookie,
            max_age=FHIR_SESSION_TTL,
            httponly=True,
            samesite="lax",
            secure=True,
        )


@app.get("/api/fhir/session")
async def fhir_session_status(request: Request):  # pragma: no cover
    """Return current FHIR session state (no PHI — only EHR name and patient context ID)."""
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    session, new_cookie = await _get_valid_fhir_session(request)
    if not session:
        return JSONResponse({"active": False})

    response = JSONResponse({
        "active": True,
        "ehr": session.get("ehr"),
        "ehr_fhir_base": session.get("fhir_base"),
        "patient_id": session.get("patient_id"),
        "expires_at": session.get("expires_at"),
    })
    _apply_refreshed_cookie(response, new_cookie)
    return response


@app.get("/api/fhir/patient/{patient_id}")
async def get_fhir_patient_bundle(request: Request, patient_id: str):  # pragma: no cover
    """Fetch and normalize all Phase 1 FHIR resources for a patient.

    Data is fetched fresh from the EHR on every request — never cached to disk.
    """
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    session, new_cookie = await _get_valid_fhir_session(request)
    if not session:
        return JSONResponse(
            {"error": "No active FHIR session. Please authenticate with your EHR."},
            status_code=401,
        )

    # Enforce patient context from token — prevents accessing arbitrary patient IDs
    session_patient = session.get("patient_id")
    if session_patient and session_patient != patient_id:
        _fhir_audit_logger.warning(
            "FHIR patient ID mismatch: ehr=%s session_patient=%s requested=%s user=%s",
            session.get("ehr"),
            session_patient,
            patient_id,
            user,
        )
        return JSONResponse(
            {"error": "Patient ID does not match FHIR session context."},
            status_code=403,
        )

    fhir_client = FHIRClient(
        fhir_base=session["fhir_base"],
        access_token=session["access_token"],
        ehr=session["ehr"],
    )

    _fhir_audit_logger.info(
        "FHIR bundle fetch: ehr=%s user=%s resource_count=7", session["ehr"], user
    )

    try:
        bundle = await fhir_client.fetch_patient_bundle(patient_id)
    except FHIRAuthError:
        return JSONResponse(
            {"error": "FHIR access token expired. Please re-authenticate with your EHR."},
            status_code=401,
        )
    except FHIRForbiddenError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except Exception as exc:
        _fhir_audit_logger.error(
            "FHIR bundle fetch error: ehr=%s user=%s error=%s", session["ehr"], user, type(exc).__name__
        )
        return JSONResponse(
            {
                "error": "EHR data temporarily unavailable.",
                "detail": "Plan generation will proceed with partial data if available.",
            },
            status_code=503,
        )

    from dataclasses import asdict
    response = JSONResponse({
        "bundle": asdict(bundle),
        "form_data": fhir_bundle_to_agent_data(bundle),
    })
    _apply_refreshed_cookie(response, new_cookie)
    return response


@app.post("/api/fhir/patient/{patient_id}/communication")
@limiter.limit("30/hour")
async def fhir_send_communication(request: Request, patient_id: str,
                                  body: dict[str, Any] = Body(default={})):  # pragma: no cover
    """Write a Communication (a note to the care team) back to the EHR for a patient.

    Requires an active FHIR session whose token carries Communication.Write — i.e.
    the provider/clinician app (ehr=epic_provider). This is an explicit clinician
    action: the message is written as a clearly-labeled draft for review."""
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    session, new_cookie = await _get_valid_fhir_session(request)
    if not session:
        return JSONResponse(
            {"error": "No active FHIR session. Connect a provider EHR app first."},
            status_code=401,
        )
    # If the session is patient-scoped, it must match the target patient.
    session_patient = session.get("patient_id")
    if session_patient and session_patient != patient_id:
        return JSONResponse(
            {"error": "Patient ID does not match FHIR session context."}, status_code=403,
        )

    fhir_client = FHIRClient(
        fhir_base=session["fhir_base"],
        access_token=session["access_token"],
        ehr=session.get("ehr", ""),
    )
    recipients = body.get("recipients") or None
    category_text = (body.get("category_text") or "Discharge plan").strip()
    sender_display = body.get("sender_display") or user

    _fhir_audit_logger.info(
        "FHIR Communication write: ehr=%s user=%s", session.get("ehr"), user
    )
    try:
        created = await fhir_client.create_communication(
            patient_id=patient_id, message=message, category_text=category_text,
            recipients=recipients, sender_display=sender_display,
        )
    except FHIRAuthError:
        return JSONResponse(
            {"error": "FHIR access token expired. Please re-authenticate with your EHR."},
            status_code=401,
        )
    except FHIRForbiddenError as exc:
        return JSONResponse({"error": str(exc)}, status_code=403)
    except Exception as exc:
        _fhir_audit_logger.error(
            "FHIR Communication write error: ehr=%s user=%s error=%s",
            session.get("ehr"), user, type(exc).__name__,
        )
        return JSONResponse({"error": f"EHR write failed: {exc}"}, status_code=502)

    response = JSONResponse({"success": True, "id": created.get("id"), "resource": created})
    _apply_refreshed_cookie(response, new_cookie)
    return response


@app.post("/api/fhir/patient/{patient_id}/plan")
async def generate_plan_from_fhir(request: Request, patient_id: str):  # pragma: no cover
    """Fetch FHIR data for a patient and stream a discharge plan.

    Accepts an optional JSON body with additional fields (insurance, living
    situation, etc.) that are not available from Phase 1 FHIR resources.
    These are merged with the FHIR-derived data before plan generation.
    """
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    session, new_cookie = await _get_valid_fhir_session(request)
    if not session:
        return JSONResponse({"error": "No active FHIR session."}, status_code=401)

    session_patient = session.get("patient_id")
    if session_patient and session_patient != patient_id:
        return JSONResponse({"error": "Patient context mismatch."}, status_code=403)

    # Optional supplemental fields from the request body
    extra: dict = {}
    try:
        body = await request.json()
        if isinstance(body, dict):
            extra = body
    except Exception:
        pass

    fhir_client = FHIRClient(
        fhir_base=session["fhir_base"],
        access_token=session["access_token"],
        ehr=session["ehr"],
    )

    _fhir_audit_logger.info(
        "FHIR plan generation: ehr=%s user=%s", session["ehr"], user
    )

    try:
        bundle = await fhir_client.fetch_patient_bundle(patient_id)
    except FHIRAuthError:
        return JSONResponse({"error": "FHIR token expired."}, status_code=401)
    except Exception as exc:
        _fhir_audit_logger.error(
            "FHIR fetch before plan: ehr=%s error=%s", session["ehr"], type(exc).__name__
        )
        return JSONResponse({"error": "EHR temporarily unavailable."}, status_code=503)

    # Map FHIR bundle → agent input, then overlay any manually supplied fields
    patient_data = fhir_bundle_to_agent_data(bundle)
    for key, value in extra.items():
        if value and not patient_data.get(key):
            patient_data[key] = value

    response = StreamingResponse(
        stream_plan(patient_data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    _apply_refreshed_cookie(response, new_cookie)
    return response


# ── Multilingual discharge instruction generation ────────────────────────────

LANGUAGE_CONFIGS: dict[str, dict] = {
    "es":    {"name": "Spanish",             "locale": "es-MX", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "Use usted (formal). Avoid literal idiom translation. Emergency room = sala de emergencias."},
    "zh-TW": {"name": "Cantonese Chinese",   "locale": "zh-HK", "direction": "ltr", "date_fmt": "YYYY/MM/DD",
              "notes": "Traditional Chinese script. Older patients prefer Traditional; never use Simplified. Formal register."},
    "zh-CN": {"name": "Mandarin Chinese",    "locale": "zh-CN", "direction": "ltr", "date_fmt": "YYYY/MM/DD",
              "notes": "Simplified Chinese script. Formal register. Use approved Chinese pharmacopeia drug names where available."},
    "vi":    {"name": "Vietnamese",          "locale": "vi-VN", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "All tone diacritics mandatory. Missing marks change word meaning completely. Never omit."},
    "tl":    {"name": "Tagalog",             "locale": "tl-PH", "direction": "ltr", "date_fmt": "MM/DD/YYYY",
              "notes": "Drug names often kept in English. Mix of Tagalog and English loanwords is standard."},
    "ko":    {"name": "Korean",              "locale": "ko-KR", "direction": "ltr", "date_fmt": "YYYY. MM. DD",
              "notes": "Formal jondaemal register. Honorifics critical for elderly patients."},
    "hy":    {"name": "Armenian",            "locale": "hy-AM", "direction": "ltr", "date_fmt": "DD.MM.YYYY",
              "notes": "Eastern Armenian (Yerevan dialect). Verify medical terms against Armenian medical glossary."},
    "fa":    {"name": "Persian/Farsi",       "locale": "fa-IR", "direction": "rtl", "date_fmt": "DD/MM/YYYY",
              "notes": "Right-to-left. Formal. Western numerals (0-9) for all medical data."},
    "ru":    {"name": "Russian",             "locale": "ru-RU", "direction": "ltr", "date_fmt": "DD.MM.YYYY",
              "notes": "Formal register. Transliterate drug names from English if no Russian pharmacopeia name. Dates: DD.MM.YYYY."},
    "km":    {"name": "Khmer",               "locale": "km-KH", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "High health literacy barrier. Very simple sentences. Always set interpreter_recommended: true."},
    "hi":    {"name": "Hindi",               "locale": "hi-IN", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "Formal (aap). Drug names: English generic name with Devanagari transliteration in parentheses."},
    "pa":    {"name": "Punjabi",             "locale": "pa-IN", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "Gurmukhi script. Verify script preference (Gurmukhi vs Shahmukhi) with clinician."},
    "ar":    {"name": "Arabic",              "locale": "ar-SA", "direction": "rtl", "date_fmt": "DD/MM/YYYY",
              "notes": "Right-to-left. Modern Standard Arabic for written materials. Western numerals (0-9) in medical data."},
    "pt":    {"name": "Portuguese (Brazilian)", "locale": "pt-BR", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "Brazilian Portuguese, not European. ANVISA approved drug names if available."},
    "ja":    {"name": "Japanese",            "locale": "ja-JP", "direction": "ltr", "date_fmt": "YYYY/MM/DD",
              "notes": "Formal keigo register. Drug names in katakana. Dates: YYYY/MM/DD."},
    "ium":   {"name": "Mien/Iu Mien",        "locale": "ium",   "direction": "ltr", "date_fmt": "MM/DD/YYYY",
              "notes": "Low-literacy community. Simplest possible sentences. Always set interpreter_recommended: true."},
    "hmn":   {"name": "Hmong",               "locale": "hmn",   "direction": "ltr", "date_fmt": "MM/DD/YYYY",
              "notes": "RPA orthography. Very low health literacy in older population. Always set interpreter_recommended: true."},
    "so":    {"name": "Somali",              "locale": "so-SO", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "Formal register. Flag alcohol/gelatin in medications for Islamic dietary review if relevant."},
    "am":    {"name": "Amharic",             "locale": "am-ET", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "Ethiopic script. Formal. Relatively higher health literacy. Loanwords like 'hospital' are acceptable."},
    "th":    {"name": "Thai",                "locale": "th-TH", "direction": "ltr", "date_fmt": "DD/MM/YYYY",
              "notes": "Polite particles (khrap/kha) required. Thai FDA approved drug names if available, otherwise English."},
}

_LOW_LITERACY_LOCALES = {"hmn", "ium", "km-KH"}
_LOW_LITERACY_NAMES   = {"Hmong", "Mien/Iu Mien", "Khmer"}


def build_multilingual_system_prompt(lang_config: dict) -> str:
    return (
        "You are a clinical linguist and medical translation specialist embedded in a "
        "HIPAA-compliant hospital discharge planning system for California acute care hospitals.\n\n"
        "YOUR ROLE:\n"
        f"Translate the English discharge instructions below into patient-ready {lang_config['name']}.\n"
        f"Patient preferred language: {lang_config['name']} ({lang_config['locale']} locale).\n"
        f"Script direction: {lang_config['direction']}.\n"
        f"Date format for this locale: {lang_config['date_fmt']}.\n\n"
        "NON-NEGOTIABLE CLINICAL ACCURACY RULES:\n\n"
        "RULE 1 -- DRUG NAMES: Never alter medication names. Use one of:\n"
        "  (a) The English generic name exactly as written.\n"
        f"  (b) The approved {lang_config['name']} pharmacopeia name if one definitively exists.\n"
        "  (c) The English name with transliteration in parentheses.\n"
        "  If uncertain between (b) and (c), use the English name unchanged.\n\n"
        "RULE 2 -- DOSAGES AND FREQUENCIES: Translate exact wording only.\n"
        "  'Twice daily' is never 'often'. '500 mg' stays '500 mg'.\n"
        "  'Every 8 hours' stays 'every 8 hours' -- never substitute 'three times a day'.\n\n"
        "RULE 3 -- WARNING SIGNS: Equal or greater urgency. Never soften.\n"
        "  US emergency number is always 911. Do not substitute other country numbers.\n\n"
        "RULE 4 -- NO OMISSIONS: Every section must appear in output.\n"
        "  If a section cannot be accurately translated, return the English text with:\n"
        "  [TRANSLATION PENDING -- INTERPRETER REQUIRED]\n\n"
        f"RULE 5 -- READING LEVEL: 6th grade or below in {lang_config['name']}.\n"
        "  Sentences under 15 words. No jargon without plain-language explanation.\n"
        "  Active voice. Use: take, call, go, stop, drink, rest.\n\n"
        "RULE 6 -- BILINGUAL: Return English source alongside translation in every section.\n\n"
        f"CULTURAL COMPETENCY FOR {lang_config['name']}:\n{lang_config['notes']}\n\n"
        "QUALITY CHECKS (run before returning output):\n"
        "  - Every medication name from source must appear in medications[].name_display.\n"
        "    If any name is altered: set requires_clinician_review: true, add to review_reasons.\n"
        "  - Warning sign count in output must equal count in source.\n"
        "    If lower: set requires_clinician_review: true, add 'Warning sign count mismatch'.\n"
        "  - Estimate reading level. If above 6.5: simplify before returning.\n"
        f"  - For Hmong, Mien/Iu Mien, Khmer: always set interpreter_recommended: true.\n"
        "  - List ALL cultural adaptations beyond literal translation in cultural_adaptations.\n"
        "  - when_to_call.emergency_instruction must contain '911' for US patients.\n\n"
        "OUTPUT JSON SCHEMA -- use these EXACT keys. For every bilingual section, put the\n"
        "ORIGINAL English in the `source_*` key and the " + lang_config['name'] + " translation in the\n"
        "matching key. Never leave a translation key empty when a source value exists. Omit a\n"
        "section only if the source has no such content.\n"
        "{\n"
        '  "meta": {\n'
        '    "target_language_name": "' + lang_config['name'] + '",\n'
        '    "generated_at": "<ISO 8601 timestamp>",\n'
        '    "requires_clinician_review": false,\n'
        '    "interpreter_recommended": false,\n'
        '    "review_reasons": ["<reason>", ...],\n'
        '    "cultural_adaptations": ["<adaptation>", ...]\n'
        "  },\n"
        '  "patient_header": { "source_greeting": "<English>", "greeting": "<translation>" },\n'
        '  "diagnosis": { "source_content": "<English>", "content": "<translation>" },\n'
        '  "medications": [\n'
        '    { "name": "<generic name>", "name_display": "<name as shown to patient>",\n'
        '      "dose": "<e.g. 25 mg>", "frequency": "<e.g. once daily>",\n'
        '      "source_instruction": "<English instruction>", "instruction": "<translation>",\n'
        '      "why": "<short reason, optional>" }\n'
        "  ],\n"
        '  "warning_signs": [\n'
        '    { "urgency": "routine|urgent|emergent",\n'
        '      "source_sign": "<English symptom>", "sign": "<translation>",\n'
        '      "action_text": "<translated action, optional>" }\n'
        "  ],\n"
        '  "activity_restrictions": { "source_content": "<English>", "content": "<translation>" },\n'
        '  "diet_instructions": { "source_content": "<English>", "content": "<translation>" },\n'
        '  "wound_care": { "source_content": "<English>", "content": "<translation>" },\n'
        '  "follow_up": { "appointments": [\n'
        '    { "provider": "<name/specialty>", "timeframe": "<when>",\n'
        '      "source_instruction": "<English>", "instruction": "<translation>" }\n'
        "  ] },\n"
        '  "when_to_call": { "er_instruction": "<translation>", "emergency_instruction": "<translation incl. 911>" },\n'
        '  "teach_back_prompt": "<translation>",\n'
        '  "attestation": "<translation>"\n'
        "}\n\n"
        "Return ONLY valid JSON. No prose. No markdown fences."
    )


def validate_translation(source_plan: "dict | str", translation: dict, lang_config: dict) -> dict:
    """Server-side clinical safety validation after translation."""
    meta = translation.setdefault("meta", {})
    reasons = meta.setdefault("review_reasons", [])
    adaptations = meta.setdefault("cultural_adaptations", [])

    if isinstance(source_plan, str):
        try:
            source_plan = json.loads(source_plan)
        except Exception:
            source_plan = {}

    # 1. Drug name integrity
    src_meds = {m.get("name", "").lower() for m in source_plan.get("medications", []) if m.get("name")}
    out_meds = {m.get("name_display", "").lower() for m in translation.get("medications", []) if m.get("name_display")}
    missing = src_meds - out_meds
    if missing:
        meta["requires_clinician_review"] = True
        reasons.append(f"Drug name may be altered or missing: {', '.join(missing)}")

    # 2. Warning sign count
    src_count = len(source_plan.get("warning_signs", []))
    out_count = len(translation.get("warning_signs", []))
    if src_count > 0 and out_count < src_count:
        meta["requires_clinician_review"] = True
        reasons.append(f"Warning sign count: source has {src_count}, output has {out_count}")

    # 3. Ensure 911 in emergency instruction
    wc = translation.setdefault("when_to_call", {})
    ei = wc.get("emergency_instruction", "")
    if "911" not in ei:
        wc["emergency_instruction"] = (ei + " -- " if ei else "") + "Call 911 (US emergency)"
        adaptations.append("Appended 911 emergency number to when_to_call.emergency_instruction")

    # 4. Interpreter recommended for low-literacy languages
    if lang_config.get("locale") in _LOW_LITERACY_LOCALES or lang_config.get("name") in _LOW_LITERACY_NAMES:
        meta["interpreter_recommended"] = True
        if "interpreter_recommended set: low-literacy language group" not in adaptations:
            adaptations.append("interpreter_recommended set: low-literacy language group")

    # 5. RTL completeness check — flag if text fields look like English-only placeholders
    if lang_config.get("direction") == "rtl":
        rtl_chars = "؀-ۿ֐-׿"  # Arabic/Persian and Hebrew ranges
        import unicodedata
        diag = translation.get("diagnosis", {})
        content = diag.get("content", "") or ""
        has_rtl = any(unicodedata.category(c) in ("Lo",) and "؀" <= c <= "ۿ" for c in content)
        if content and not has_rtl:
            meta["requires_clinician_review"] = True
            reasons.append("RTL translation may be incomplete — diagnosis content appears to be English")

    return translation


@app.post("/api/multilingual/generate")
@limiter.limit("30/hour")
async def generate_multilingual_instructions(request: Request, body: dict[str, Any] = Body(default={}),
                                             ctx: OrgContext = Depends(get_current_org)):
    target_lang = (body.get("target_language") or "").strip().lower()
    source_plan = (body.get("discharge_plan") or "").strip()

    if not target_lang or target_lang not in LANGUAGE_CONFIGS:
        return JSONResponse(
            {"error": f"Unsupported language: '{target_lang}'.",
             "supported": list(LANGUAGE_CONFIGS.keys())},
            status_code=400,
        )
    if not source_plan:
        return JSONResponse({"error": "discharge_plan is required"}, status_code=400)

    lang_config = LANGUAGE_CONFIGS[target_lang]
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Server not configured"}, status_code=500)

    system_prompt = build_multilingual_system_prompt(lang_config)
    user_prompt = f"Translate this discharge plan to {lang_config['name']}:\n\n{source_plan}"

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return resp.content[0].text

    try:
        raw = await asyncio.to_thread(_call_api)
    except anthropic.APIError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean).strip()

    try:
        result = json.loads(clean)
    except json.JSONDecodeError as e:
        return JSONResponse({"success": False, "error": f"JSON parse failed: {e}", "raw": raw}, status_code=500)

    result = validate_translation(source_plan, result, lang_config)

    return JSONResponse({
        "success": True,
        "translation": result,
        "language": lang_config["name"],
        "direction": lang_config["direction"],
        "interpreter_recommended": result.get("meta", {}).get("interpreter_recommended", False),
        "requires_review": result.get("meta", {}).get("requires_clinician_review", False),
    })


# ── Multi-tenant org provisioning ─────────────────────────────────────────────

@app.post("/api/onboard/create-org")
@limiter.limit("5/hour", key_func=_get_ip_key)
async def create_org(request: Request, body: dict[str, Any] = Body(default={})):
    """Create a new organization and seed its first admin user.

    Available without an existing session — used during initial SaaS onboarding.
    When DATABASE_URL is not set, returns a stub response for local dev.
    """
    name = (body.get("name") or "").strip()
    slug = (body.get("slug") or "").strip().lower()
    admin_email = (body.get("admin_email") or "").strip().lower()
    admin_password = body.get("admin_password") or ""
    domain = (body.get("domain") or "").strip() or None

    if not name or not slug or not admin_email or not admin_password:
        return JSONResponse({"error": "name, slug, admin_email, and admin_password are required"},
                            status_code=400)
    if "@" not in admin_email or "." not in admin_email.split("@")[-1]:
        return JSONResponse({"error": "Invalid admin_email"}, status_code=400)
    if len(admin_password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)
    if not re.match(r"^[a-z0-9-]+$", slug):
        return JSONResponse({"error": "slug must be lowercase alphanumeric with hyphens only"},
                            status_code=400)

    if not DATABASE_URL:
        # File-based dev mode: just sign up and return default org info
        err = register_user(admin_email, admin_password)
        if err:
            return JSONResponse({"error": err}, status_code=409)
        response = JSONResponse({
            "ok": True,
            "org": {"id": DEFAULT_ORG_ID, "name": name, "slug": slug},
        })
        return _set_session(response, admin_email, DEFAULT_ORG_ID, "org_admin")

    # DB mode
    from db import create_organization, slug_exists, register_user_db
    if slug_exists(slug):
        return JSONResponse({"error": "This slug is already taken."}, status_code=409)
    try:
        org = create_organization(name=name, slug=slug, domain=domain, plan="trial")
    except Exception as exc:
        return JSONResponse({"error": f"Failed to create organization: {exc}"}, status_code=500)

    err = register_user_db(org["id"], admin_email, admin_password, role="org_admin")
    if err:
        return JSONResponse({"error": err}, status_code=409)

    response = JSONResponse({
        "ok": True,
        "org": {"id": str(org["id"]), "name": org["name"], "slug": org["slug"]},
    })
    return _set_session(response, admin_email, str(org["id"]), "org_admin")


@app.get("/api/onboard/check-slug")
@limiter.limit("30/minute", key_func=_get_ip_key)
async def check_slug(request: Request, slug: str = ""):
    """Check whether an org slug is available."""
    slug = slug.strip().lower()
    if not slug or not re.match(r"^[a-z0-9-]+$", slug):
        return JSONResponse({"available": False, "reason": "Invalid slug format"})
    if not DATABASE_URL:
        return JSONResponse({"available": True})
    from db import slug_exists
    return JSONResponse({"available": not slug_exists(slug)})


# ── Invitation flow ───────────────────────────────────────────────────────────

@app.get("/api/invite/accept")
@limiter.limit("20/hour", key_func=_get_ip_key)
async def invite_info(request: Request, token: str = ""):
    """Return invitation metadata so the frontend can pre-fill the signup form."""
    if not token:
        return JSONResponse({"error": "token is required"}, status_code=400)
    if not DATABASE_URL:
        return JSONResponse({"error": "Invitations require database mode"}, status_code=503)
    from db import get_invitation_by_token
    invite = get_invitation_by_token(token)
    if not invite:
        return JSONResponse({"error": "Invalid or expired invitation"}, status_code=404)
    return JSONResponse({
        "email": invite["email"],
        "role": invite["role"],
        "org_name": invite.get("org_name"),
        "org_slug": invite.get("org_slug"),
    })


@app.post("/api/invite/accept")
@limiter.limit("10/hour", key_func=_get_ip_key)
async def accept_invite(request: Request, body: dict[str, Any] = Body(default={})):
    """Accept an invitation: create user account and set session."""
    token = (body.get("token") or "").strip()
    password = body.get("password") or ""
    if not token or not password:
        return JSONResponse({"error": "token and password are required"}, status_code=400)
    if len(password) < 8:
        return JSONResponse({"error": "Password must be at least 8 characters"}, status_code=400)
    if not DATABASE_URL:
        return JSONResponse({"error": "Invitations require database mode"}, status_code=503)

    from db import get_invitation_by_token, register_user_db, mark_invitation_accepted
    invite = get_invitation_by_token(token)
    if not invite:
        return JSONResponse({"error": "Invalid or expired invitation"}, status_code=404)

    org_id = str(invite["organization_id"])
    email = invite["email"]
    role = invite["role"]

    err = register_user_db(org_id, email, password, role=role)
    if err:
        return JSONResponse({"error": err}, status_code=409)

    mark_invitation_accepted(token)
    response = JSONResponse({"ok": True, "email": email, "org_id": org_id, "role": role})
    return _set_session(response, email, org_id, role)


# ── Admin endpoints (org_admin and above) ─────────────────────────────────────

@app.get("/api/admin/users")
@limiter.limit("60/hour")
async def admin_list_users(request: Request,
                           ctx: OrgContext = Depends(require_role("org_admin", "super_admin"))):
    """List all users in the current org."""
    if not DATABASE_URL:
        return JSONResponse({"users": [], "note": "file-based mode — no user records"})
    from db import list_users
    return JSONResponse({"users": list_users(ctx.org_id)})


@app.post("/api/admin/invite")
@limiter.limit("30/hour")
async def admin_invite_user(request: Request, body: dict[str, Any] = Body(default={}),
                            ctx: OrgContext = Depends(require_role("org_admin", "super_admin"))):
    """Send an invitation to a new user within the current org."""
    email = (body.get("email") or "").strip().lower()
    role = (body.get("role") or "clinician").strip()
    if "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse({"error": "Invalid email"}, status_code=400)
    if role not in ("org_admin", "clinician", "read_only"):
        return JSONResponse({"error": "Invalid role"}, status_code=400)
    if not DATABASE_URL:
        return JSONResponse({"error": "Invitations require database mode"}, status_code=503)
    from db import create_invitation
    invite = create_invitation(ctx.org_id, email, role)
    return JSONResponse({"ok": True, "token": invite["token"], "email": email, "role": role})


# ── Superadmin endpoints ───────────────────────────────────────────────────────

@app.get("/api/superadmin/orgs")
@limiter.limit("30/hour")
async def superadmin_list_orgs(request: Request,
                               ctx: OrgContext = Depends(require_role("super_admin"))):
    """List all organizations (super_admin only)."""
    if not DATABASE_URL:
        return JSONResponse({"orgs": [{"id": DEFAULT_ORG_ID, "name": "Original Users",
                                        "slug": "original-users"}]})
    from db import list_all_organizations
    return JSONResponse({"orgs": list_all_organizations()})


# ── TCM Billing CPT Automation ────────────────────────────────────────────────
# CMS TCM MLN Fact Sheet ICN908628 / Medicare Claims Processing Manual Ch.12 Sec.30.6

async def _maybe_create_tcm_episode(  # pragma: no cover
    discharge_plan: str,
    patient_data: dict,
    org_id: str,
    user_email: str,
) -> dict | None:
    """Auto-assess TCM eligibility after plan generation. Non-blocking — never raises.

    Returns a summary dict if a TCM episode was created, None otherwise.
    Requires discharge_date, discharge_setting, patient_mrn, patient_name,
    discharge_diagnosis, attending_provider_npi, attending_provider_name.
    """
    required = [
        "discharge_date", "discharge_setting", "patient_mrn", "patient_name",
        "discharge_diagnosis", "attending_provider_npi", "attending_provider_name",
    ]
    if not all(patient_data.get(f) for f in required):
        return None
    try:
        from tcm_module import assess_mdm_complexity
        from datetime import date as _date
        import db as _db
        discharge_date = _date.fromisoformat(str(patient_data["discharge_date"]))
        mdm = await assess_mdm_complexity(
            discharge_plan=discharge_plan,
            discharge_date=discharge_date,
            discharge_setting=patient_data["discharge_setting"],
        )
        if mdm.get("eligibility") != "eligible":
            return None
        episode_id = await asyncio.to_thread(
            _db.create_tcm_episode, org_id,
            {
                **patient_data,
                "discharge_date": discharge_date,
                "recommended_cpt": mdm.get("recommended_cpt"),
                "mdm_complexity": mdm.get("mdm_complexity"),
                "mdm_rationale": mdm.get("mdm_rationale"),
                "mdm_rationale_json": json.dumps(mdm),
                "mdm_assessed_by": "ai_assisted",
                "status": "pending_contact",
                "created_by": None,
            },
        )
        rates = mdm.get("estimated_reimbursement", {})
        return {
            "episode_id": episode_id,
            "cpt": mdm.get("recommended_cpt"),
            "contact_deadline": mdm.get("contact_deadline"),
            "estimated_revenue": rates.get("rate_non_facility", 0),
        }
    except Exception as e:
        logging.getLogger("tcm").warning("TCM auto-assessment skipped: %s", e)
        return None


@app.post("/api/tcm/episodes")
@limiter.limit("30/hour")
async def create_tcm_episode_endpoint(
    request: Request,
    body: dict[str, Any] = Body(default={}),
    ctx: OrgContext = Depends(get_current_org),
):
    """Create a TCM episode and run AI MDM assessment.

    Requires DATABASE_URL. Returns MDM assessment with CPT recommendation,
    contact deadline (2 business days), and visit deadline (7 or 14 days).
    """
    required_fields = [
        "patient_mrn", "patient_name", "discharge_date", "discharge_setting",
        "discharge_diagnosis", "attending_provider_npi", "attending_provider_name",
        "discharge_plan_text",
    ]
    for field in required_fields:
        if not body.get(field):
            return JSONResponse({"error": f"Missing required field: {field}"}, status_code=400)

    valid_settings = [
        "inpatient_hospital", "snf", "irf", "ltch", "observation", "partial_hospitalization",
    ]
    if body["discharge_setting"] not in valid_settings:
        return JSONResponse(
            {"error": f"Invalid discharge_setting. Must be one of: {valid_settings}"},
            status_code=400,
        )

    from datetime import date as _date
    try:
        discharge_date = _date.fromisoformat(body["discharge_date"])
    except ValueError:
        return JSONResponse(
            {"error": "discharge_date must be YYYY-MM-DD format"}, status_code=400)

    if not DATABASE_URL:
        return JSONResponse(
            {"error": "TCM module requires PostgreSQL — set POSTGRES_URL"}, status_code=503)

    from tcm_module import assess_mdm_complexity
    try:
        mdm = await assess_mdm_complexity(
            discharge_plan=body["discharge_plan_text"],
            discharge_date=discharge_date,
            discharge_setting=body["discharge_setting"],
        )
    except Exception as e:
        return JSONResponse({"error": f"MDM assessment failed: {e}"}, status_code=500)

    import db as _db
    episode_id = await asyncio.to_thread(
        _db.create_tcm_episode, ctx.org_id,
        {
            **body,
            "discharge_date": discharge_date,
            "recommended_cpt": mdm.get("recommended_cpt"),
            "mdm_complexity": mdm.get("mdm_complexity"),
            "mdm_rationale": mdm.get("mdm_rationale"),
            "mdm_rationale_json": json.dumps(mdm),
            "mdm_assessed_by": "ai_assisted",
            "status": ("pending_contact" if mdm.get("eligibility") == "eligible"
                       else "not_eligible"),
            "created_by": None,
        },
    )

    cpt = mdm.get("recommended_cpt", "not_eligible")
    return JSONResponse({
        "ok": True,
        "episode_id": episode_id,
        "mdm_assessment": mdm,
        "contact_deadline": mdm.get("contact_deadline"),
        "visit_deadline": (mdm.get("visit_deadline_7day") if cpt == "99496"
                           else mdm.get("visit_deadline_14day")),
    })


@app.post("/api/tcm/episodes/{episode_id}/contacts")
@limiter.limit("60/hour")
async def record_tcm_contact(
    episode_id: str,
    request: Request,
    body: dict[str, Any] = Body(default={}),
    ctx: OrgContext = Depends(get_current_org),
):
    """Record a contact attempt (qualifying or non-qualifying) for a TCM episode."""
    required_fields = ["contact_date", "contact_time", "contact_method",
                       "contact_result", "contacted_by"]
    for f in required_fields:
        if not body.get(f):
            return JSONResponse({"error": f"Missing: {f}"}, status_code=400)
    if body["contact_method"] not in ("phone", "video", "in_person"):
        return JSONResponse(
            {"error": "contact_method must be phone, video, or in_person"}, status_code=400)
    if body["contact_result"] not in (
        "reached", "left_voicemail", "no_answer", "patient_declined"
    ):
        return JSONResponse({"error": "Invalid contact_result"}, status_code=400)

    if not DATABASE_URL:
        return JSONResponse(
            {"error": "TCM module requires PostgreSQL — set POSTGRES_URL"}, status_code=503)

    import db as _db
    contact_id = await asyncio.to_thread(
        _db.create_tcm_contact, ctx.org_id, episode_id,
        {**body, "contacted_by_id": None},
    )
    if body["contact_result"] == "reached":
        await asyncio.to_thread(
            _db.update_episode_status, ctx.org_id, episode_id, "contact_completed")
    return JSONResponse({
        "ok": True,
        "contact_id": contact_id,
        "qualifying": body["contact_result"] == "reached",
    })


@app.post("/api/tcm/episodes/{episode_id}/visits")
@limiter.limit("30/hour")
async def record_tcm_visit(
    episode_id: str,
    request: Request,
    body: dict[str, Any] = Body(default={}),
    ctx: OrgContext = Depends(get_current_org),
):
    """Record a face-to-face visit for a TCM episode."""
    for f in ("visit_date", "visit_type", "provider_npi", "provider_name"):
        if not body.get(f):
            return JSONResponse({"error": f"Missing: {f}"}, status_code=400)

    if not DATABASE_URL:
        return JSONResponse(
            {"error": "TCM module requires PostgreSQL — set POSTGRES_URL"}, status_code=503)

    import db as _db
    visit_id = await asyncio.to_thread(
        _db.create_tcm_visit, ctx.org_id, episode_id, body)
    await asyncio.to_thread(
        _db.update_episode_status, ctx.org_id, episode_id, "visit_completed")
    return JSONResponse({"ok": True, "visit_id": visit_id})


@app.get("/api/tcm/episodes/{episode_id}")
@limiter.limit("120/hour")
async def get_tcm_episode_endpoint(
    episode_id: str,
    request: Request,
    ctx: OrgContext = Depends(get_current_org),
):
    """Get a single TCM episode with real-time window status."""
    if not DATABASE_URL:
        return JSONResponse(
            {"error": "TCM module requires PostgreSQL — set POSTGRES_URL"}, status_code=503)

    import db as _db
    from tcm_module import compute_window_status
    ep = await asyncio.to_thread(_db.get_tcm_episode, ctx.org_id, episode_id)
    if not ep:
        return JSONResponse({"error": "Episode not found"}, status_code=404)
    contacts = await asyncio.to_thread(_db.get_tcm_contacts, ctx.org_id, episode_id)
    visits = await asyncio.to_thread(_db.get_tcm_visits, ctx.org_id, episode_id)
    window = compute_window_status(ep, contacts, visits)
    return JSONResponse({
        "episode": {k: str(v) if hasattr(v, "isoformat") else v for k, v in ep.items()},
        "contacts": contacts,
        "visits": visits,
        "window_status": {
            **window.__dict__,
            "discharge_date": str(window.discharge_date),
            "contact_deadline": str(window.contact_deadline),
            "contact_date": str(window.contact_date) if window.contact_date else None,
            "visit_deadline": str(window.visit_deadline),
            "visit_date": str(window.visit_date) if window.visit_date else None,
            "overall_status": window.overall_status.value,
        },
    })


@app.get("/api/tcm/dashboard")
@limiter.limit("60/hour")
async def tcm_dashboard(request: Request, ctx: OrgContext = Depends(get_current_org)):
    """Dashboard: all active TCM episodes with alert levels and revenue estimate."""
    if not DATABASE_URL:
        return JSONResponse({
            "episodes": [], "total_active": 0, "red_alerts": 0,
            "amber_alerts": 0, "claim_ready": 0, "estimated_monthly_revenue": 0,
            "note": "TCM module requires PostgreSQL",
        })

    import db as _db
    from tcm_module import compute_window_status, _get_reimbursement_rates
    episodes = await asyncio.to_thread(_db.get_active_tcm_episodes, ctx.org_id)
    dashboard = []
    total_revenue = 0.0
    for ep in episodes:
        contacts = await asyncio.to_thread(_db.get_tcm_contacts, ctx.org_id, str(ep["id"]))
        visits = await asyncio.to_thread(_db.get_tcm_visits, ctx.org_id, str(ep["id"]))
        window = compute_window_status(ep, contacts, visits)
        rates = _get_reimbursement_rates(ep.get("cpt_final") or ep.get("recommended_cpt"))
        row = {
            "episode_id": str(ep["id"]),
            "patient_name": ep["patient_name"],
            "discharge_date": str(ep["discharge_date"]),
            "cpt_code": ep.get("cpt_final") or ep.get("recommended_cpt"),
            "alert_level": window.alert_level,
            "alert_message": window.alert_message,
            "contact_deadline": str(window.contact_deadline),
            "contact_completed": window.contact_completed,
            "visit_deadline": str(window.visit_deadline),
            "visit_completed": window.visit_completed,
            "status": window.overall_status.value,
            "estimated_revenue": rates["rate_non_facility"],
        }
        dashboard.append(row)
        if window.claim_eligible:
            total_revenue += rates["rate_non_facility"]

    return JSONResponse({
        "episodes": dashboard,
        "total_active": len(dashboard),
        "red_alerts": sum(1 for d in dashboard if d["alert_level"] == "red"),
        "amber_alerts": sum(1 for d in dashboard if d["alert_level"] == "amber"),
        "claim_ready": sum(1 for d in dashboard if d["status"] == "claim_ready"),
        "estimated_monthly_revenue": round(total_revenue, 2),
    })


@app.post("/api/tcm/episodes/{episode_id}/generate-claim")
@limiter.limit("30/hour")
async def generate_tcm_claim_endpoint(
    episode_id: str,
    request: Request,
    ctx: OrgContext = Depends(get_current_org),
):
    """Generate and persist a claim-ready billing record for a TCM episode."""
    if not DATABASE_URL:
        return JSONResponse(
            {"error": "TCM module requires PostgreSQL — set POSTGRES_URL"}, status_code=503)

    import db as _db
    from tcm_module import generate_tcm_claim, compute_window_status
    ep = await asyncio.to_thread(_db.get_tcm_episode, ctx.org_id, episode_id)
    if not ep:
        return JSONResponse({"error": "Episode not found"}, status_code=404)
    contacts = await asyncio.to_thread(_db.get_tcm_contacts, ctx.org_id, episode_id)
    visits = await asyncio.to_thread(_db.get_tcm_visits, ctx.org_id, episode_id)
    mdm = json.loads(ep.get("mdm_rationale_json") or "{}")
    claim = generate_tcm_claim(ep, contacts, visits, mdm)
    if not claim["claimable"]:
        return JSONResponse({"error": claim["reason"]}, status_code=400)
    claim_id = await asyncio.to_thread(_db.save_tcm_claim, ctx.org_id, episode_id, claim)
    await asyncio.to_thread(
        _db.update_episode_status, ctx.org_id, episode_id, "claim_ready")
    return JSONResponse({"ok": True, "claim_id": claim_id, "claim": claim})


@app.get("/api/tcm/claims/export")
@limiter.limit("10/hour")
async def export_tcm_claims(
    request: Request,
    format: str = "csv",
    ctx: OrgContext = Depends(get_current_org),
):
    """Export all claim-ready episodes as CSV or JSON for clearinghouse submission."""
    if not DATABASE_URL:
        return JSONResponse(
            {"error": "TCM module requires PostgreSQL — set POSTGRES_URL"}, status_code=503)

    import db as _db
    from tcm_module import generate_tcm_claim
    episodes = await asyncio.to_thread(_db.get_claim_ready_episodes, ctx.org_id)
    claims = []
    for ep in episodes:
        contacts = await asyncio.to_thread(_db.get_tcm_contacts, ctx.org_id, str(ep["id"]))
        visits = await asyncio.to_thread(_db.get_tcm_visits, ctx.org_id, str(ep["id"]))
        mdm = json.loads(ep.get("mdm_rationale_json") or "{}")
        claim = generate_tcm_claim(ep, contacts, visits, mdm)
        if claim["claimable"]:
            claims.append(claim)

    if format == "json":
        return JSONResponse({
            "claims": claims,
            "count": len(claims),
            "total_estimated": round(sum(c["estimated_reimbursement"] for c in claims), 2),
        })

    if not claims:
        return JSONResponse({"error": "No claim-ready episodes found"}, status_code=404)
    import csv, io
    output = io.StringIO()
    writer = csv.DictWriter(
        output, fieldnames=list(claims[0].keys()), extrasaction="ignore")
    writer.writeheader()
    writer.writerows(claims)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=tcm_claims_{__import__('datetime').date.today()}.csv"
            )
        },
    )


# ── TCM deadline alert scheduler (6 AM daily) ────────────────────────────────

@app.on_event("startup")
async def start_tcm_scheduler():  # pragma: no cover
    """Start APScheduler daily job that scans TCM deadlines.

    Note: requires a persistent process — does not run on serverless deployments.
    """
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        logging.getLogger("tcm.scheduler").warning(
            "apscheduler not installed — TCM deadline alerts disabled. "
            "Run: pip install apscheduler"
        )
        return

    async def _run_deadline_scan():
        if not DATABASE_URL:
            return
        import db as _db
        from tcm_module import compute_window_status
        log = logging.getLogger("tcm.scheduler")
        log.info("Running TCM deadline alert scan...")
        orgs = await asyncio.to_thread(_db.list_all_organizations)
        total_alerts = 0
        for org in orgs:
            episodes = await asyncio.to_thread(_db.get_active_tcm_episodes, str(org["id"]))
            for ep in episodes:
                contacts = await asyncio.to_thread(
                    _db.get_tcm_contacts, str(org["id"]), str(ep["id"]))
                visits = await asyncio.to_thread(
                    _db.get_tcm_visits, str(org["id"]), str(ep["id"]))
                window = compute_window_status(ep, contacts, visits)
                if window.alert_level in ("red", "amber"):
                    total_alerts += 1
                    log.warning(json.dumps({
                        "alert_type": "tcm_deadline",
                        "org_id": str(org["id"])[:8],
                        "episode_id": str(ep["id"])[:8],
                        "alert_level": window.alert_level,
                        "alert_msg": window.alert_message,
                        "cpt_code": window.cpt_code,
                    }))
        log.info("TCM alert scan complete. %d alerts.", total_alerts)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        _run_deadline_scan,
        CronTrigger(hour=6, minute=0),
        id="tcm_deadline_alerts",
        misfire_grace_time=3600,
    )
    scheduler.start()
    logging.getLogger("tcm.scheduler").info("TCM deadline alert scheduler started")
