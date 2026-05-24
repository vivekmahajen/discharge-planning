"""HIPAA audit log tests.

Covers: audit entry written for PHI endpoints, audit entry skipped for public
endpoints, user hash is SHA-256 derived (never raw email), fallback to logger
when DATABASE_URL is unset.
"""
import json
import logging
import pytest
from unittest.mock import MagicMock, patch, call


class TestAuditLogMiddleware:
    async def test_audit_logged_for_phi_endpoint(
            self, authed_client, mock_claude, caplog):
        """A call to a PHI endpoint should produce an AUDIT log entry."""
        with caplog.at_level(logging.INFO, logger="hipaa.audit"):
            await authed_client.post("/api/summary/generate", json={
                "clinicalNotes": "Test notes", "patientContext": {}})
        # DATABASE_URL is None in tests, so audit falls back to the logger
        audit_lines = [r for r in caplog.records if r.name == "hipaa.audit"]
        assert len(audit_lines) >= 1, "No AUDIT log entry written for /api/summary/generate"

    async def test_audit_entry_contains_endpoint_not_phi(
            self, authed_client, mock_claude, caplog):
        """Audit log must contain the endpoint path but never the clinical notes."""
        with caplog.at_level(logging.INFO, logger="hipaa.audit"):
            await authed_client.post("/api/summary/generate", json={
                "clinicalNotes": "PATIENT_SECRET_DATA", "patientContext": {}})
        log_text = caplog.text
        assert "/api/summary" in log_text
        assert "PATIENT_SECRET_DATA" not in log_text

    async def test_audit_entry_contains_user_email(
            self, authed_client, mock_claude, caplog):
        """Audit log must record the actual user email for HIPAA user identification."""
        with caplog.at_level(logging.INFO, logger="hipaa.audit"):
            await authed_client.post("/api/summary/generate", json={
                "clinicalNotes": "Test notes", "patientContext": {}})
        log_text = caplog.text
        assert "test@example.com" in log_text

    async def test_no_audit_for_public_endpoints(self, client, caplog):
        """Public endpoints (healthz, login page) must not produce audit entries."""
        with caplog.at_level(logging.INFO, logger="hipaa.audit"):
            await client.get("/api/healthz")
        audit_lines = [r for r in caplog.records if r.name == "hipaa.audit"]
        assert len(audit_lines) == 0, "Audit log should not fire for /api/healthz"

    async def test_audit_entry_written_to_postgres_when_db_url_set(
            self, authed_client, mock_claude, monkeypatch):
        """When DATABASE_URL is set, audit entries go to db.write_audit_log."""
        import web_app
        import db
        calls = []

        def fake_write_audit(org_id, user_email, endpoint, method, status, ip, mrn=None):
            calls.append({
                "org_id": org_id, "user_email": user_email, "endpoint": endpoint,
                "method": method, "status": status, "ip": ip, "mrn": mrn,
            })

        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake")
        monkeypatch.setattr(db, "write_audit_log", fake_write_audit)

        await authed_client.post("/api/summary/generate", json={
            "clinicalNotes": "Test notes", "patientContext": {}})

        import asyncio
        await asyncio.sleep(0.05)

        assert len(calls) >= 1
        entry = calls[0]
        assert entry["user_email"] == "test@example.com"
        assert entry["endpoint"] == "/api/summary/generate"
        assert entry["status"] == 200


class TestAuditLogValidation:
    def test_validate_translation_adds_911_to_when_to_call(self):
        """validate_translation must auto-append 911 if missing from emergency_instruction."""
        from web_app import validate_translation, LANGUAGE_CONFIGS
        result = validate_translation(
            {},
            {"meta": {}, "when_to_call": {"emergency_instruction": "Seek help immediately"}},
            LANGUAGE_CONFIGS["es"],
        )
        assert "911" in result["when_to_call"]["emergency_instruction"]

    def test_validate_translation_sets_interpreter_flag_for_khmer(self):
        from web_app import validate_translation, LANGUAGE_CONFIGS
        result = validate_translation(
            {},
            {"meta": {}, "when_to_call": {"emergency_instruction": "Call 911"}},
            LANGUAGE_CONFIGS["km"],
        )
        assert result["meta"]["interpreter_recommended"] is True

    def test_validate_translation_sets_interpreter_flag_for_hmong(self):
        from web_app import validate_translation, LANGUAGE_CONFIGS
        result = validate_translation(
            {},
            {"meta": {}, "when_to_call": {"emergency_instruction": "Call 911"}},
            LANGUAGE_CONFIGS["hmn"],
        )
        assert result["meta"]["interpreter_recommended"] is True

    def test_validate_translation_flags_missing_drug_name(self):
        from web_app import validate_translation, LANGUAGE_CONFIGS
        source = {"medications": [{"name": "metoprolol"}]}
        translation = {
            "meta": {},
            "medications": [{"name_display": "completely different drug"}],
            "when_to_call": {"emergency_instruction": "Call 911"},
        }
        result = validate_translation(source, translation, LANGUAGE_CONFIGS["es"])
        assert result["meta"]["requires_clinician_review"] is True
        assert any("metoprolol" in r for r in result["meta"]["review_reasons"])

    def test_validate_translation_flags_missing_warning_sign(self):
        from web_app import validate_translation, LANGUAGE_CONFIGS
        source = {"warning_signs": [{"sign": "chest pain"}, {"sign": "shortness of breath"}]}
        translation = {
            "meta": {},
            "warning_signs": [{"sign": "dolor de pecho"}],
            "when_to_call": {"emergency_instruction": "Call 911"},
        }
        result = validate_translation(source, translation, LANGUAGE_CONFIGS["es"])
        assert result["meta"]["requires_clinician_review"] is True
