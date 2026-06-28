"""Tests for all POST API endpoints — happy path, bad input, and unauthenticated."""
import json
import pytest


class TestSummaryGenerate:
    async def test_valid_notes_returns_success(self, authed_client, mock_claude):
        r = await authed_client.post("/api/summary/generate", json={
            "clinicalNotes": "Patient admitted for CHF exacerbation. Diuresis effective.",
            "patientContext": {"admissionDate": "2026-05-01", "attending": "Dr. Smith"},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert "summary" in r.json()

    async def test_empty_notes_returns_400(self, authed_client, mock_claude):
        r = await authed_client.post("/api/summary/generate",
            json={"clinicalNotes": "   ", "patientContext": {}})
        assert r.status_code == 400
        assert "required" in r.json()["error"].lower()

    async def test_missing_notes_field_returns_400(self, authed_client, mock_claude):
        r = await authed_client.post("/api/summary/generate",
            json={"patientContext": {}})
        assert r.status_code == 400

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/summary/generate",
            json={"clinicalNotes": "Some notes"})
        assert r.status_code == 401

    async def test_calls_claude_with_correct_model(self, authed_client, mock_claude):
        await authed_client.post("/api/summary/generate",
            json={"clinicalNotes": "Test notes", "patientContext": {}})
        call = mock_claude.messages.create.call_args
        assert call.kwargs["model"] == "claude-sonnet-4-6"
        assert call.kwargs["temperature"] == 0


class TestDischargeSummaryGenerate:
    async def test_valid_request_returns_summary(self, authed_client, mock_claude):
        r = await authed_client.post("/api/discharge-summary/generate", json={
            "notes": "Patient discharged home with medications.",
            "ctx": {"admissionDate": "2026-05-01", "dischargeDate": "2026-05-05"},
        })
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_empty_notes_returns_400(self, authed_client, mock_claude):
        r = await authed_client.post("/api/discharge-summary/generate",
            json={"notes": "", "ctx": {}})
        assert r.status_code == 400

    async def test_whitespace_notes_returns_400(self, authed_client, mock_claude):
        r = await authed_client.post("/api/discharge-summary/generate",
            json={"notes": "   \n\t   ", "ctx": {}})
        assert r.status_code == 400

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/discharge-summary/generate",
            json={"notes": "test", "ctx": {}})
        assert r.status_code == 401

    async def test_truncated_response_returns_friendly_error(self, authed_client, mock_claude):
        # Model hit the token ceiling → incomplete JSON. Surface a clear message
        # instead of a cryptic parse failure.
        mock_claude.messages.create.return_value.stop_reason = "max_tokens"
        mock_claude.messages.create.return_value.content[0].text = '{"meta": {"confidence":'
        r = await authed_client.post("/api/discharge-summary/generate", json={
            "notes": "Long synthetic clinical note for a complex patient.",
            "ctx": {},
        })
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert "cut off" in body["error"].lower()


class TestTeachbackGenerate:
    async def test_valid_prompt_returns_categories(self, authed_client, mock_claude):
        mock_claude.messages.create.return_value.content[0].text = json.dumps({
            "categories": [{"category": "Medications", "questions": []}]
        })
        r = await authed_client.post("/api/teachback/generate",
            json={"prompt": "Patient: John. Diagnosis: CHF. Med: Lasix 40mg."})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "categories" in body["result"]

    async def test_missing_prompt_returns_400(self, authed_client, mock_claude):
        r = await authed_client.post("/api/teachback/generate", json={"prompt": ""})
        assert r.status_code == 400

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/teachback/generate", json={"prompt": "test"})
        assert r.status_code == 401

    async def test_malformed_claude_response_returns_500(self, authed_client, mock_claude):
        mock_claude.messages.create.return_value.content[0].text = "not json at all"
        r = await authed_client.post("/api/teachback/generate",
            json={"prompt": "Some clinical context"})
        assert r.status_code in (200, 500)


class TestCdphComplianceAnalyze:
    async def test_valid_prompt_returns_json(self, authed_client, mock_claude):
        mock_claude.messages.create.return_value.content[0].text = json.dumps(
            {"compliance_score": 92, "flags": [], "recommendations": []})
        r = await authed_client.post("/api/cdph-compliance/analyze",
            json={"prompt": "Patient discharge plan details here."})
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_empty_prompt_returns_400(self, authed_client, mock_claude):
        r = await authed_client.post("/api/cdph-compliance/analyze",
            json={"prompt": ""})
        assert r.status_code == 400

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/cdph-compliance/analyze",
            json={"prompt": "test"})
        assert r.status_code == 401


class TestRoiGenerate:
    async def test_valid_prompt_returns_json(self, authed_client, mock_claude):
        mock_claude.messages.create.return_value.content[0].text = json.dumps(
            {"headline": "15% reduction in readmissions", "details": []})
        r = await authed_client.post("/api/roi/generate",
            json={"prompt": "Hospital data: 150 patients, $2M savings."})
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_empty_prompt_returns_400(self, authed_client, mock_claude):
        r = await authed_client.post("/api/roi/generate", json={"prompt": ""})
        assert r.status_code == 400

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/roi/generate", json={"prompt": "test"})
        assert r.status_code == 401


class TestHrrpGenerate:
    async def test_valid_prompt_returns_json(self, authed_client, mock_claude):
        mock_claude.messages.create.return_value.content[0].text = json.dumps(
            {"risk_level": "high", "conditions": ["CHF"], "penalty_estimate": 12000})
        r = await authed_client.post("/api/hrrp/generate",
            json={"prompt": "Patient with CHF, 2 prior admissions in 12 months."})
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/hrrp/generate", json={"prompt": "test"})
        assert r.status_code == 401


class TestMultilingualGenerate:
    def test_system_prompt_pins_output_schema_keys(self):
        """The prompt must specify the exact bilingual keys the UI renders, or the
        model invents key names and the translated text shows up blank."""
        import web_app
        cfg = web_app.LANGUAGE_CONFIGS["es"]
        prompt = web_app.build_multilingual_system_prompt(cfg)
        for key in ['"source_content"', '"content"', '"source_instruction"',
                    '"instruction"', '"source_sign"', '"sign"', '"name_display"',
                    '"follow_up"', '"when_to_call"']:
            assert key in prompt, f"schema key {key} missing from translation prompt"

    async def test_valid_request_returns_translation(self, authed_client, mock_claude):
        mock_claude.messages.create.return_value.content[0].text = json.dumps({
            "meta": {
                "target_language": "es", "target_language_name": "Spanish",
                "requires_clinician_review": False, "interpreter_recommended": False,
                "cultural_adaptations": [], "review_reasons": [],
                "generated_at": "2026-05-01T00:00:00Z", "model": "claude-sonnet-4-6",
            },
            "diagnosis": {"title": "Diagnóstico", "content": "Texto traducido",
                          "source_title": "Diagnosis", "source_content": "Translated text"},
            "medications": [],
            "warning_signs": [],
            "when_to_call": {"emergency_instruction": "Llame al 911"},
            "attestation": "Cert text",
        })
        r = await authed_client.post("/api/multilingual/generate", json={
            "target_language": "es",
            "discharge_plan": "Patient discharged home. Take metoprolol 25mg daily.",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        assert "translation" in body
        assert body["language"] == "Spanish"

    async def test_unsupported_language_returns_400(self, authed_client):
        r = await authed_client.post("/api/multilingual/generate", json={
            "target_language": "xx-unsupported",
            "discharge_plan": "Some plan text",
        })
        assert r.status_code == 400
        assert "supported" in r.json()

    async def test_missing_discharge_plan_returns_400(self, authed_client):
        r = await authed_client.post("/api/multilingual/generate", json={
            "target_language": "es",
            "discharge_plan": "",
        })
        assert r.status_code == 400

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/multilingual/generate", json={
            "target_language": "es", "discharge_plan": "Some plan",
        })
        assert r.status_code == 401

    async def test_interpreter_flag_set_for_khmer(self, authed_client, mock_claude):
        mock_claude.messages.create.return_value.content[0].text = json.dumps({
            "meta": {
                "requires_clinician_review": False, "interpreter_recommended": False,
                "cultural_adaptations": [], "review_reasons": [],
                "generated_at": "2026-05-01T00:00:00Z",
            },
            "medications": [], "warning_signs": [],
            "when_to_call": {"emergency_instruction": "Call 911"},
            "attestation": "",
        })
        r = await authed_client.post("/api/multilingual/generate", json={
            "target_language": "km",
            "discharge_plan": "Patient discharged home.",
        })
        assert r.status_code == 200
        assert r.json()["interpreter_recommended"] is True


class TestSamplePatient:
    async def test_authenticated_returns_patient_dict(self, authed_client):
        r = await authed_client.get("/api/sample-patient")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)
        assert len(data) > 0

    async def test_unauthenticated_returns_401(self, client):
        r = await client.get("/api/sample-patient")
        assert r.status_code == 401
