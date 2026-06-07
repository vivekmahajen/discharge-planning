"""AI generation JSON-repair edge cases — fence stripping, missing keys, errors.

Covers the spec section 13 + section 22 coverage gap: "AI generation JSON-repair
edge cases (fence stripping, partial JSON, missing keys) across all generators".
The happy/empty/auth paths live in test_api_endpoints.py; this file exercises the
defensive parsing branches that turn raw model text into structured responses.
"""
import json

import anthropic
import pytest


def _set_response(mock_claude, text):
    mock_claude.messages.create.return_value.content[0].text = text


# ── Markdown fence stripping (GEN-007) ───────────────────────────────────────

class TestFenceStripping:
    @pytest.mark.parametrize("wrapped", [
        "```json\n{}\n```",
        "```JSON\n{}\n```",
        "```\n{}\n```",
        "  ```json\n{}\n```  ",
    ])
    async def test_roi_strips_fences(self, authed_client, mock_claude, wrapped):
        _set_response(mock_claude, wrapped.replace("{}", '{"headline":"x"}'))
        r = await authed_client.post("/api/roi/generate", json={"prompt": "data"})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert body["result"]["headline"] == "x"

    async def test_summary_strips_fences(self, authed_client, mock_claude):
        _set_response(mock_claude, "```json\n" + json.dumps(
            {"patient_summary": {"primary_diagnosis": "CHF"}}) + "\n```")
        r = await authed_client.post("/api/summary/generate",
                                     json={"clinicalNotes": "notes", "patientContext": {}})
        assert r.status_code == 200
        assert r.json()["success"] is True


# ── Invalid JSON preserves raw (GEN-008) ─────────────────────────────────────

class TestInvalidJson:
    async def test_roi_invalid_json_returns_500_with_raw(self, authed_client, mock_claude):
        _set_response(mock_claude, "this is not json")
        r = await authed_client.post("/api/roi/generate", json={"prompt": "data"})
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert "JSON parse failed" in body["error"]
        assert body["raw"] == "this is not json"

    async def test_hrrp_partial_json_returns_500(self, authed_client, mock_claude):
        _set_response(mock_claude, '{"risk_level": "high"')  # truncated
        r = await authed_client.post("/api/hrrp/generate", json={"prompt": "data"})
        assert r.status_code == 500
        assert r.json()["success"] is False

    async def test_summary_invalid_json_returns_500_with_raw(self, authed_client, mock_claude):
        _set_response(mock_claude, "<<garbage>>")
        r = await authed_client.post("/api/summary/generate",
                                     json={"clinicalNotes": "notes", "patientContext": {}})
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert body["raw"] == "<<garbage>>"


# ── Missing required keys (GEN-006) ──────────────────────────────────────────

class TestMissingKeys:
    async def test_teachback_missing_categories(self, authed_client, mock_claude):
        _set_response(mock_claude, json.dumps({"questions": []}))  # no "categories"
        r = await authed_client.post("/api/teachback/generate", json={"prompt": "ctx"})
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert "categories" in body["error"]

    async def test_teachback_categories_wrong_type(self, authed_client, mock_claude):
        _set_response(mock_claude, json.dumps({"categories": "not-a-list"}))
        r = await authed_client.post("/api/teachback/generate", json={"prompt": "ctx"})
        assert r.status_code == 500
        assert r.json()["success"] is False


# ── Anthropic API errors surfaced (GEN-009) ──────────────────────────────────

class TestApiErrors:
    @pytest.fixture
    def raising_claude(self, mock_claude):
        req = httpx_request()
        mock_claude.messages.create.side_effect = anthropic.APIError(
            "upstream boom", request=req, body=None)
        return mock_claude

    async def test_roi_api_error_returns_500(self, authed_client, raising_claude):
        r = await authed_client.post("/api/roi/generate", json={"prompt": "data"})
        assert r.status_code == 500
        assert "error" in r.json()

    async def test_cdph_api_error_returns_500(self, authed_client, raising_claude):
        r = await authed_client.post("/api/cdph-compliance/analyze",
                                     json={"prompt": "data"})
        assert r.status_code == 500

    async def test_error_body_has_no_secrets(self, authed_client, raising_claude):
        r = await authed_client.post("/api/hrrp/generate", json={"prompt": "data"})
        body_text = r.text.lower()
        assert "sk-test-not-real" not in body_text
        assert "secret_key" not in body_text


# ── Server-side HRRP cadence enforcement (GEN-013) ───────────────────────────

class TestHrrpCadenceOverride:
    async def test_flagged_condition_overrides_cadence(self, authed_client, mock_claude):
        _set_response(mock_claude, json.dumps({
            "california_compliance": {"hrrp_condition_flagged": True},
            "readmission_risk": {"lace_score": 12, "follow_up_call_cadence": "none"},
        }))
        r = await authed_client.post("/api/summary/generate",
                                     json={"clinicalNotes": "CHF readmit risk",
                                           "patientContext": {}})
        assert r.status_code == 200
        summary = r.json()["summary"]
        assert summary["readmission_risk"]["follow_up_call_cadence"] == "24h + 72h + 7d + 14d"

    async def test_unflagged_condition_leaves_cadence(self, authed_client, mock_claude):
        _set_response(mock_claude, json.dumps({
            "california_compliance": {"hrrp_condition_flagged": False},
            "readmission_risk": {"lace_score": 4, "follow_up_call_cadence": "none"},
        }))
        r = await authed_client.post("/api/summary/generate",
                                     json={"clinicalNotes": "low risk",
                                           "patientContext": {}})
        assert r.status_code == 200
        summary = r.json()["summary"]
        assert summary["readmission_risk"]["follow_up_call_cadence"] == "none"


def httpx_request():
    """Build a minimal httpx.Request for constructing anthropic.APIError."""
    import httpx
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")
