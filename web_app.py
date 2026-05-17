"""FastAPI web application for the Multi-Agent Discharge Planning System."""
import asyncio
import json
import os
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

# Auth helpers
SECRET_KEY = os.getenv("SECRET_KEY", "discharge-planning-dev-secret-change-in-prod")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")
ALLOWED_EMAILS_RAW = os.getenv("ALLOWED_EMAILS", "")  # comma-separated; empty = any email allowed
ALLOWED_EMAILS = {e.strip().lower() for e in ALLOWED_EMAILS_RAW.split(",") if e.strip()}

_serializer = URLSafeTimedSerializer(SECRET_KEY)
COOKIE_NAME = "dp_session"
COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


def make_session_cookie(email: str) -> str:
    return _serializer.dumps({"email": email})


def verify_session_cookie(token: str) -> str | None:
    """Return email if valid, None otherwise."""
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
    """Return redirect response if not authenticated, else None."""
    if not get_current_user(request):
        return RedirectResponse(url="/login", status_code=302)
    return None


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page():
    with open(STATIC_DIR / "login.html", encoding="utf-8") as f:
        return f.read()


@app.post("/api/auth/login")
async def do_login(request: Request):
    body = await request.json()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    # Validate email format (basic)
    if "@" not in email or "." not in email.split("@")[-1]:
        return JSONResponse({"error": "Invalid email address."}, status_code=400)

    # Validate password
    if not AUTH_PASSWORD:
        return JSONResponse({"error": "AUTH_PASSWORD is not configured on the server."}, status_code=500)
    if password != AUTH_PASSWORD:
        return JSONResponse({"error": "Incorrect password."}, status_code=401)

    # Check allowed emails list (if configured)
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        return JSONResponse({"error": "This email is not authorized."}, status_code=403)

    # Set signed session cookie
    token = make_session_cookie(email)
    response = JSONResponse({"ok": True})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # set True if enforcing HTTPS in production
        max_age=COOKIE_MAX_AGE,
    )
    return response


@app.get("/api/auth/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie(COOKIE_NAME)
    return response


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
