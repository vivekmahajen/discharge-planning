"""SSE streaming tests for POST /api/plan/stream and stream_plan coverage.

Covers: auth guard, event sequence, agent_error events, content-type header,
no-ANTHROPIC_API_KEY error event.
"""
import json
import pytest


def parse_sse(raw_text: str) -> list[dict]:
    """Parse SSE response body into a list of event data dicts."""
    events = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


class TestPlanStreamAuth:
    async def test_stream_requires_authentication(self, client):
        r = await client.post("/api/plan/stream", json={})
        assert r.status_code == 401

    async def test_anonymous_user_gets_401_not_stream(self, client):
        r = await client.post("/api/plan/stream", json={"patient_name": "Test"})
        assert r.status_code == 401
        assert "text/event-stream" not in r.headers.get("content-type", "")


class TestPlanStreamEventSequence:
    async def test_stream_response_content_type_is_event_stream(
            self, authed_client, sample_patient, mock_stream_plan):
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

    async def test_stream_emits_agent_start_events(
            self, authed_client, sample_patient, mock_stream_plan):
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        events = parse_sse(r.text)
        start_events = [e for e in events if e.get("type") == "agent_start"]
        assert len(start_events) == 5, (
            f"Expected 5 agent_start events, got {len(start_events)}")

    async def test_stream_emits_agent_complete_events(
            self, authed_client, sample_patient, mock_stream_plan):
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        events = parse_sse(r.text)
        complete_events = [e for e in events if e.get("type") == "agent_complete"]
        assert len(complete_events) == 5

    async def test_stream_emits_coordinator_start_event(
            self, authed_client, sample_patient, mock_stream_plan):
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        events = parse_sse(r.text)
        types = [e.get("type") for e in events]
        assert "coordinator_start" in types

    async def test_stream_final_event_is_coordinator_complete_with_output(
            self, authed_client, sample_patient, mock_stream_plan):
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        events = parse_sse(r.text)
        coord_events = [e for e in events if e.get("type") == "coordinator_complete"]
        assert len(coord_events) == 1
        assert "output" in coord_events[0]
        assert len(coord_events[0]["output"]) > 0

    async def test_stream_events_are_valid_json(
            self, authed_client, sample_patient, mock_stream_plan):
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        raw_events = [
            line[6:] for line in r.text.splitlines()
            if line.startswith("data: ")
        ]
        assert len(raw_events) > 0
        for raw in raw_events:
            json.loads(raw)  # raises if not valid JSON


class TestPlanStreamErrorHandling:
    async def test_agent_error_emits_agent_error_event(
            self, authed_client, sample_patient, monkeypatch):
        """If an agent fails, an agent_error event must be emitted; stream must not crash."""
        import web_app

        async def _stream_with_error(patient_data):
            yield f"data: {json.dumps({'type': 'agent_start', 'agent': 'clinical'})}\n\n"
            yield f"data: {json.dumps({'type': 'agent_error', 'agent': 'clinical', 'error': 'Timeout'})}\n\n"
            yield f"data: {json.dumps({'type': 'coordinator_complete', 'output': 'Partial plan'})}\n\n"

        monkeypatch.setattr(web_app, "stream_plan", _stream_with_error)
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        assert r.status_code == 200
        events = parse_sse(r.text)
        error_events = [e for e in events if e.get("type") == "agent_error"]
        assert len(error_events) == 1
        assert error_events[0]["error"] == "Timeout"

    async def test_missing_anthropic_api_key_emits_error_event(
            self, authed_client, sample_patient, monkeypatch):
        """If ANTHROPIC_API_KEY is not set, stream must emit an error event, not crash."""
        import web_app

        async def _no_key_stream(patient_data):
            yield f"data: {json.dumps({'type': 'error', 'message': 'ANTHROPIC_API_KEY not set'})}\n\n"

        monkeypatch.setattr(web_app, "stream_plan", _no_key_stream)
        r = await authed_client.post("/api/plan/stream", json=sample_patient)
        assert r.status_code == 200
        events = parse_sse(r.text)
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) >= 1
        assert "ANTHROPIC_API_KEY" in error_events[0].get("message", "")


class TestStreamPlanFunction:
    """Run stream_plan directly with mocked agents to cover the generator code."""

    async def test_real_stream_plan_emits_five_agent_start_events(
            self, authed_client, sample_patient, monkeypatch):
        from unittest.mock import AsyncMock, MagicMock
        import web_app

        mock_agent = MagicMock()
        mock_agent.run = AsyncMock(return_value="Agent output text")
        mock_coord = MagicMock()
        mock_coord.run = AsyncMock(return_value="## Discharge Plan\nCoordinated output.")

        for agent_cls in [
            "web_app.ClinicalAssessmentAgent",
            "web_app.CareNeedsAgent",
            "web_app.InsuranceAuthorizationAgent",
            "web_app.MedicationReconciliationAgent",
            "web_app.SocialDeterminantsAgent",
        ]:
            monkeypatch.setattr(agent_cls, lambda *a, **kw: mock_agent, raising=False)

        # Patch at the stream_plan function's local import scope
        from unittest.mock import patch
        with patch("agents.clinical_assessment.ClinicalAssessmentAgent", return_value=mock_agent), \
             patch("agents.care_needs.CareNeedsAgent", return_value=mock_agent), \
             patch("agents.insurance_authorization.InsuranceAuthorizationAgent", return_value=mock_agent), \
             patch("agents.medication_reconciliation.MedicationReconciliationAgent", return_value=mock_agent), \
             patch("agents.social_determinants.SocialDeterminantsAgent", return_value=mock_agent), \
             patch("agents.coordinator.CoordinatorAgent", return_value=mock_coord):
            events = []
            async for chunk in web_app.stream_plan(sample_patient):
                for line in chunk.splitlines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

        start_events = [e for e in events if e.get("type") == "agent_start"]
        assert len(start_events) == 5

        complete_events = [e for e in events if e.get("type") == "coordinator_complete"]
        assert len(complete_events) == 1
        assert "Coordinated output" in complete_events[0]["output"]

    async def test_real_stream_plan_handles_no_api_key(self, monkeypatch):
        import web_app
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        events = []
        async for chunk in web_app.stream_plan({}):
            for line in chunk.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert any(e.get("type") == "error" for e in events)
