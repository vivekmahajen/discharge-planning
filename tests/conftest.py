"""Shared pytest fixtures for Discharge Planning AI test suite."""
import json
import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient, ASGITransport

# Set env vars BEFORE importing web_app — never after.
os.environ["SECRET_KEY"] = "test-secret-key-exactly-32-chars!!"
os.environ["ANTHROPIC_API_KEY"] = "sk-test-not-real"
os.environ["ALLOWED_EMAILS"] = ""
os.environ.pop("POSTGRES_URL", None)
os.environ.pop("DATABASE_URL", None)

from web_app import app  # noqa: E402

MOCK_SUMMARY_JSON = json.dumps({
    "summary_metadata": {
        "confidence": "high",
        "requires_physician_review": False,
        "missing_fields": [],
        "generated_at": "2026-01-01T00:00:00Z",
    },
    "patient_summary": {"primary_diagnosis": "Test diagnosis"},
    "medications": [],
    "warning_signs": [],
    "follow_up": {"appointments": []},
    "post_acute_plan": {"destination": "home"},
    "california_compliance": {"hrrp_condition_flagged": False},
    "readmission_risk": {"lace_score": 4, "follow_up_call_cadence": "none"},
})


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset in-memory rate limit counters and lockout state before each test."""
    import web_app
    for attr in ("_storage", "_limiter"):
        try:
            getattr(web_app.limiter, attr).reset()
        except Exception:
            pass
        try:
            getattr(getattr(web_app.limiter, attr, None), "_storage", None).reset()
        except Exception:
            pass
    web_app._login_failures.clear()
    web_app._login_lockouts.clear()
    web_app._global_ai_counters.clear()


@pytest.fixture
async def client():
    # Use https so httpx sends Secure cookies back (app sets secure=True on all cookies)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as ac:
        yield ac


@pytest.fixture
async def authed_client(client, tmp_path, monkeypatch):
    """Client with a valid session cookie using an isolated per-test user store."""
    import web_app
    monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(web_app, "DATABASE_URL", None)
    r = await client.post(
        "/api/auth/signup",
        json={"email": "test@example.com", "password": "SecurePass123!"},
    )
    assert r.status_code == 200, f"Signup failed: {r.text}"
    yield client


@pytest.fixture
def mock_claude(monkeypatch):
    """Replace Anthropic API with a fast mock. Returns mock client for assertions."""
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=MOCK_SUMMARY_JSON)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: mock_client)
    return mock_client


@pytest.fixture
async def db_authed_client(client, tmp_path, monkeypatch):
    """Client with a valid session cookie + DATABASE_URL mocked to a non-None value.

    Allows testing the DB-mode code paths without a real PostgreSQL instance.
    All db module functions are replaced with no-op stubs.
    """
    import web_app
    import db as _db

    # Sign up in file mode to get a session cookie
    monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(web_app, "DATABASE_URL", None)
    r = await client.post(
        "/api/auth/signup",
        json={"email": "dbtest@example.com", "password": "SecurePass123!"},
    )
    assert r.status_code == 200, f"Signup failed: {r.text}"

    # Switch to fake DB mode — all db calls are stubbed out
    monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake/db")
    monkeypatch.setattr(_db, "get_active_tcm_episodes", lambda org_id: [])
    monkeypatch.setattr(_db, "get_tcm_contacts", lambda org_id, ep_id: [])
    monkeypatch.setattr(_db, "get_tcm_visits", lambda org_id, ep_id: [])
    monkeypatch.setattr(_db, "get_tcm_episode", lambda org_id, ep_id: None)
    monkeypatch.setattr(_db, "create_tcm_contact", lambda *a: "contact-uuid-001")
    monkeypatch.setattr(_db, "create_tcm_visit", lambda *a: "visit-uuid-001")
    monkeypatch.setattr(_db, "update_episode_status", lambda *a: None)
    monkeypatch.setattr(_db, "save_tcm_claim", lambda *a: "claim-uuid-001")
    monkeypatch.setattr(_db, "get_claim_ready_episodes", lambda org_id: [])
    yield client


@pytest.fixture
def mock_stream_plan(monkeypatch):
    """Replace stream_plan with a minimal fake emitting the expected SSE event sequence."""
    import web_app

    async def _fake(patient_data):
        import json as _j
        for agent in ["predictive_los", "clinical", "care_needs", "insurance", "medications", "social"]:
            start = _j.dumps({"type": "agent_start", "agent": agent})
            done = _j.dumps({"type": "agent_complete", "agent": agent, "output": "ok"})
            yield f"data: {start}\n\n"
            yield f"data: {done}\n\n"
        coord_start = _j.dumps({"type": "coordinator_start"})
        coord_done = _j.dumps({"type": "coordinator_complete", "output": "## Discharge Plan\nTest."})
        yield f"data: {coord_start}\n\n"
        yield f"data: {coord_done}\n\n"

    monkeypatch.setattr(web_app, "stream_plan", _fake)


@pytest.fixture
def sample_patient():
    from sample_patient import SAMPLE_PATIENT_WEB
    return dict(SAMPLE_PATIENT_WEB)
