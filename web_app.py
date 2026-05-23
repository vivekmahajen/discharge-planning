"""FastAPI web application for the Multi-Agent Discharge Planning System."""
import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import anthropic
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
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
except Exception as _e:
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

load_dotenv()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Discharge Planning AI")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable is required and not set.")
ALLOWED_EMAILS_RAW = os.getenv("ALLOWED_EMAILS", "")
ALLOWED_EMAILS = {e.strip().lower() for e in ALLOWED_EMAILS_RAW.split(",") if e.strip()}

_serializer = URLSafeTimedSerializer(SECRET_KEY)
COOKIE_NAME = "dp_session"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours

# Postgres URL — Vercel injects POSTGRES_URL automatically; DATABASE_URL is the fallback
DATABASE_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")

# ── HIPAA audit log ───────────────────────────────────────────────────────────
_audit_logger = logging.getLogger("hipaa.audit")
logging.basicConfig(level=logging.INFO)

_AUDITED_PREFIXES = ("/api/plan", "/api/fhir", "/api/summary", "/api/discharge",
                     "/api/teachback", "/api/cdph", "/api/hrrp", "/api/medications",
                     "/api/multilingual", "/api/immunisation")

async def _audit_log_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if any(path.startswith(p) for p in _AUDITED_PREFIXES):
        user = get_current_user(request)
        if user:
            await asyncio.to_thread(_write_audit_entry, {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_hash": hashlib.sha256(user.encode()).hexdigest()[:16],
                "endpoint": path,
                "method": request.method,
                "status": response.status_code,
                "ip": request.client.host if request.client else "unknown",
            })
    return response

def _write_audit_entry(entry: dict) -> None:
    if DATABASE_URL:
        try:
            with _get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS audit_log (
                            id BIGSERIAL PRIMARY KEY,
                            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            user_hash TEXT,
                            endpoint TEXT,
                            method TEXT,
                            status INT,
                            ip TEXT
                        )
                    """)
                    cur.execute(
                        "INSERT INTO audit_log (ts, user_hash, endpoint, method, status, ip) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (entry["timestamp"], entry["user_hash"], entry["endpoint"],
                         entry["method"], entry["status"], entry["ip"]),
                    )
                conn.commit()
        except Exception:
            _audit_logger.exception("Audit log write failed")
    else:
        _audit_logger.info("AUDIT %s", entry)

app.middleware("http")(_audit_log_middleware)


# ── Password helpers ─────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return dk.hex()


def _verify_password(password: str, salt: str, stored_hash: str) -> bool:
    return secrets.compare_digest(_hash_password(password, salt), stored_hash)


# ── User store ───────────────────────────────────────────────────────────────
# Uses Postgres when DATABASE_URL / POSTGRES_URL is set, otherwise falls back
# to a local JSON file (convenient for local development without a DB).

def _get_conn():
    import psycopg2
    return psycopg2.connect(DATABASE_URL)


def _ensure_table() -> None:
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
        conn.commit()


# File-based fallback for local dev
_LOCAL_USERS_FILE = BASE_DIR / "data" / "users.json"

def _file_load() -> dict:
    if _LOCAL_USERS_FILE.exists():
        try:
            return json.loads(_LOCAL_USERS_FILE.read_text(encoding="utf-8"))
        except Exception:
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
    if DATABASE_URL:
        await asyncio.to_thread(_ensure_table)


# ── Session helpers ──────────────────────────────────────────────────────────

def make_session_cookie(email: str) -> str:
    return _serializer.dumps({"email": email})


def verify_session_cookie(token: str) -> str | None:
    try:
        data = _serializer.loads(token, max_age=COOKIE_MAX_AGE)
        return data.get("email")
    except (BadSignature, SignatureExpired):
        return None


def get_current_user(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return verify_session_cookie(token)


def require_login(request: Request):
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return None


def _set_session(response: JSONResponse, email: str) -> JSONResponse:
    response.set_cookie(
        key=COOKIE_NAME,
        value=make_session_cookie(email),
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
@limiter.limit("5/minute")
async def do_signup(request: Request):
    body = await request.json()
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
@limiter.limit("5/minute")
async def do_login(request: Request):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse({"error": "Invalid email address."}, status_code=400)
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        return JSONResponse({"error": "This email is not authorized."}, status_code=403)

    err = authenticate_user(email, password)
    if err:
        return JSONResponse({"error": err}, status_code=401)

    response = JSONResponse({"ok": True})
    return _set_session(response, email)


@app.get("/api/auth/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/api/me")
async def me(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse({"email": user})


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    redirect = require_login(request)
    if redirect:
        return redirect
    with open(STATIC_DIR / "index.html", encoding="utf-8") as f:
        return f.read()


@app.get("/api/sample-patient")
async def get_sample_patient(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    from sample_patient import SAMPLE_PATIENT_WEB
    return SAMPLE_PATIENT_WEB


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

    agents = {
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
            return name, result
        except Exception as e:
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

    await asyncio.gather(*tasks)

    yield f"data: {json.dumps({'type': 'coordinator_start'})}\n\n"
    try:
        coordinator = CoordinatorAgent(client)
        plan = await coordinator.run(agent_outputs)
        yield f"data: {json.dumps({'type': 'coordinator_complete', 'output': plan})}\n\n"
    except Exception as e:
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


@app.post("/api/roi/generate")
@limiter.limit("20/minute")
async def generate_roi_summary(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
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
        return JSONResponse({"success": True, "result": result})
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"JSON parse failed: {exc}", "raw": raw_text}, status_code=500)


@app.post("/api/hrrp/generate")
@limiter.limit("20/minute")
async def generate_hrrp_briefing(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
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
async def analyze_cdph_compliance(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    user_prompt = body.get("prompt", "")
    if not user_prompt.strip():
        return JSONResponse({"error": "prompt is required"}, status_code=400)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "Server not configured"}, status_code=500)

    system_prompt = (
        "You are a California healthcare compliance specialist. Analyze the discharge planning data "
        "provided and return a concise compliance risk report as JSON. Focus on California-specific "
        "issues: CDPH CoPs, Medi-Cal managed care auth, Livanta QIO timelines, and the 3-day SNF rule. "
        "Be specific about regulatory citations. Return ONLY valid JSON — no prose, no markdown fences."
    )

    def _call_api():
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
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
        clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
    clean = clean.strip()

    try:
        result = json.loads(clean)
        return JSONResponse({"success": True, "result": result})
    except json.JSONDecodeError as exc:
        return JSONResponse({"success": False, "error": f"JSON parse failed: {exc}", "raw": raw_text}, status_code=500)


@app.post("/api/teachback/generate")
@limiter.limit("20/minute")
async def generate_teachback(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
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
@limiter.limit("20/minute")
async def generate_discharge_summary_v2(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
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
@limiter.limit("20/minute")
async def generate_summary(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return JSONResponse({"error": "ANTHROPIC_API_KEY not configured"}, status_code=500)

    body = await request.json()
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
- ALWAYS include California-specific regulatory elements: CDPH CoP compliance, Livanta QIO appeal rights, Medi-Cal auth status where applicable
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
@limiter.limit("20/minute")
async def create_plan(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    patient_data = await request.json()
    return StreamingResponse(
        stream_plan(patient_data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

APP_URL = os.environ.get("NEXT_PUBLIC_APP_URL", "https://discharge-planning.vercel.app")
FHIR_REDIRECT_URI = os.getenv("FHIR_REDIRECT_URI", f"{APP_URL}/api/fhir/callback")



# ── Legacy Epic SMART launch (kept for backward-compatibility) ────────────────
# New integrations should use /api/fhir/authorize?ehr=epic instead.

EPIC_CLIENT_ID = os.environ.get("NEXT_PUBLIC_EPIC_CLIENT_ID", "")

@app.get("/launch")
async def epic_launch_legacy(request: Request, iss: str, launch: str = None):
    """Legacy EHR-embedded SMART launch. Redirects to the generic FHIR authorize flow."""
    redirect_url = f"/api/fhir/authorize?ehr=epic"
    if iss:
        redirect_url += f"&iss_override={iss}"
    if launch:
        redirect_url += f"&launch={launch}"
    return RedirectResponse(url=redirect_url)


@app.get("/api/auth/epic/callback")
async def epic_callback_legacy(request: Request, code: str = None, state: str = None, error: str = None):
    """Legacy Epic callback — delegates to the unified FHIR callback handler."""
    return await fhir_callback(request, code=code, state=state, error=error)


# ── FHIR R4 connector routes ──────────────────────────────────────────────────

_fhir_audit_logger = logging.getLogger("fhir.audit")
logging.basicConfig(level=logging.INFO)
if _FHIR_IMPORT_ERROR:
    _fhir_audit_logger.error("fhir package unavailable: %s", _FHIR_IMPORT_ERROR)


def _fhir_unavailable():
    """Return 503 with the exact import error when fhir package couldn't load."""
    return JSONResponse(
        {"error": "FHIR connector unavailable", "detail": _FHIR_IMPORT_ERROR},
        status_code=503,
    )


@app.get("/api/fhir/ehrs")
async def list_fhir_ehrs(request: Request):
    if _FHIR_IMPORT_ERROR:
        return _fhir_unavailable()
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return JSONResponse({"ehrs": list_ehr_display()})


@app.get("/api/fhir/authorize")
async def fhir_authorize(
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
async def fhir_callback(
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


async def _get_valid_fhir_session(request: Request) -> tuple[dict | None, str | None]:
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


def _apply_refreshed_cookie(response, new_cookie: str | None) -> None:
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
async def fhir_session_status(request: Request):
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
async def get_fhir_patient_bundle(request: Request, patient_id: str):
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


@app.post("/api/fhir/patient/{patient_id}/plan")
async def generate_plan_from_fhir(request: Request, patient_id: str):
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
@limiter.limit("20/minute")
async def generate_multilingual_instructions(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
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
