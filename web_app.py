"""FastAPI web application for the Multi-Agent Discharge Planning System."""
import asyncio
import hashlib
import json
import os
import secrets
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

load_dotenv()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Discharge Planning AI")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Auth config
SECRET_KEY = os.getenv("SECRET_KEY", "discharge-planning-dev-secret-change-in-prod")
ALLOWED_EMAILS_RAW = os.getenv("ALLOWED_EMAILS", "")
ALLOWED_EMAILS = {e.strip().lower() for e in ALLOWED_EMAILS_RAW.split(",") if e.strip()}

_serializer = URLSafeTimedSerializer(SECRET_KEY)
COOKIE_NAME = "dp_session"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours

# Postgres URL — Vercel injects POSTGRES_URL automatically; DATABASE_URL is the fallback
DATABASE_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")


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
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _ensure_table)


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
        secure=False,
        max_age=COOKIE_MAX_AGE,
    )
    return response


# ── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open(STATIC_DIR / "login.html", encoding="utf-8") as f:
        return f.read()


@app.post("/api/auth/signup")
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


@app.post("/api/summary/generate")
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

    loop = asyncio.get_event_loop()
    try:
        raw_text = await loop.run_in_executor(None, _call_api)
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
async def create_plan(request: Request):
    if not get_current_user(request):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    patient_data = await request.json()
    return StreamingResponse(
        stream_plan(patient_data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
