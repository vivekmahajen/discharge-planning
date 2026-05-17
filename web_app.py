"""FastAPI web application for the Multi-Agent Discharge Planning System."""
import asyncio
import json
import os

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

app = FastAPI(title="Discharge Planning AI")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main single-page application."""
    with open("static/index.html") as f:
        return f.read()


@app.get("/api/sample-patient")
async def get_sample_patient():
    """Return sample patient data pre-mapped to web form fields."""
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

    # Build a patient_data dict that the existing agents can work with.
    # The web form sends flat string fields; map them to the nested structure
    # that the specialist agents' format_input() methods expect.
    def build_agent_data(raw: dict) -> dict:
        """Translate flat web form fields into the nested dict the agents expect."""
        def parse_med_list(text: str) -> list:
            return [line.strip() for line in text.splitlines() if line.strip()]

        def parse_diagnoses(text: str) -> list:
            return [line.strip() for line in text.splitlines() if line.strip()]

        return {
            # Demographics
            "patient_name": raw.get("patient_name", ""),
            "age": raw.get("age", ""),
            "sex": raw.get("gender", ""),
            "mrn": raw.get("mrn", ""),
            "admission_date": raw.get("admission_date", ""),
            "anticipated_discharge_date": raw.get("expected_discharge_date", ""),
            "attending_physician": raw.get("attending_physician", ""),

            # Diagnoses
            "primary_diagnosis": raw.get("primary_diagnosis", ""),
            "secondary_diagnoses": parse_diagnoses(raw.get("secondary_diagnoses", "")),

            # Clinical notes
            "clinical_notes": raw.get("additional_clinical_notes", ""),

            # Medications
            "admission_medications": parse_med_list(raw.get("admission_medications", "")),
            "inpatient_medications": parse_med_list(raw.get("inpatient_medications", "")),
            "discharge_medications": parse_med_list(raw.get("discharge_medications", "")),

            # Therapy evaluations
            "therapy_evaluations": {
                "PT": raw.get("pt_evaluation", "Not evaluated"),
                "OT": raw.get("ot_evaluation", "Not evaluated"),
                "ST": raw.get("st_evaluation", "Not evaluated"),
            },

            # Insurance — nested structure the insurance agent expects
            "insurance": {
                "primary": {
                    "payer_name": raw.get("primary_insurance", ""),
                    "medicare_type": raw.get("medicare_part_a", "N/A"),
                    "snf_days_used_this_benefit_period": raw.get("snf_days_used", 0),
                },
                "secondary": {
                    "payer_name": raw.get("secondary_insurance", ""),
                },
            },
            # Also expose flat insurance fields for agents that look for them directly
            "primary_insurance": raw.get("primary_insurance", ""),
            "secondary_insurance": raw.get("secondary_insurance", ""),
            "medicare_part_a": raw.get("medicare_part_a", "N/A"),
            "snf_days_used": raw.get("snf_days_used", 0),

            # Social / home environment
            "support_system": {
                "living_situation": raw.get("living_situation", ""),
                "primary_caregiver": raw.get("caregiver", ""),
            },
            "home_environment": {
                "housing_type": raw.get("housing_type", ""),
                "bedroom_location": raw.get("bedroom_location", ""),
            },
            "transportation": {
                "primary_transportation": raw.get("transportation", ""),
            },
            "language_literacy": {
                "primary_language": raw.get("primary_language", "English"),
            },
            # Flat social fields for agents that access them directly
            "living_situation": raw.get("living_situation", ""),
            "caregiver": raw.get("caregiver", ""),
            "primary_language": raw.get("primary_language", "English"),
            "transportation_notes": raw.get("transportation", ""),
            "housing_type": raw.get("housing_type", ""),
            "bedroom_location": raw.get("bedroom_location", ""),

            # Discharge goals
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

    # Use a queue to stream events as agents complete
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

    # Launch all agent tasks
    tasks = [asyncio.create_task(run_agent(name, agent)) for name, agent in agents.items()]

    # Stream events as they arrive
    completed = 0
    agent_outputs: dict = {}

    while completed < len(agents):
        event = await queue.get()
        yield f"data: {json.dumps(event)}\n\n"
        if event["type"] in ("agent_complete", "agent_error"):
            completed += 1
            agent_outputs[event["agent"]] = event.get("output", event.get("error", ""))

    # Wait for all tasks to finish
    await asyncio.gather(*tasks)

    # Run coordinator
    yield f"data: {json.dumps({'type': 'coordinator_start'})}\n\n"
    try:
        coordinator = CoordinatorAgent(client)
        plan = await coordinator.run(agent_outputs)
        yield f"data: {json.dumps({'type': 'coordinator_complete', 'output': plan})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


@app.post("/api/plan/stream")
async def create_plan(request: Request):
    """Accept patient data and stream SSE events as agents execute."""
    patient_data = await request.json()
    return StreamingResponse(
        stream_plan(patient_data),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
