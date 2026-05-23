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

    async def test_audit_entry_uses_hashed_user_id(
            self, authed_client, mock_claude, caplog):
        """Audit log must use a hashed user ID, never the raw email address."""
        with caplog.at_level(logging.INFO, logger="hipaa.audit"):
            await authed_client.post("/api/summary/generate", json={
                "clinicalNotes": "Test notes", "patientContext": {}})
        log_text = caplog.text
        assert "test@example.com" not in log_text

    async def test_no_audit_for_public_endpoints(self, client, caplog):
        """Public endpoints (healthz, login page) must not produce audit entries."""
        with caplog.at_level(logging.INFO, logger="hipaa.audit"):
            await client.get("/api/healthz")
        audit_lines = [r for r in caplog.records if r.name == "hipaa.audit"]
        assert len(audit_lines) == 0, "Audit log should not fire for /api/healthz"

    async def test_audit_entry_written_to_postgres_when_db_url_set(
            self, authed_client, mock_claude, monkeypatch):
        """When DATABASE_URL is set, audit entries go to the audit_log table."""
        import web_app
        written_entries = []

        def fake_write_audit(entry):
            written_entries.append(entry)

        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake")
        monkeypatch.setattr(web_app, "_write_audit_entry", fake_write_audit)

        await authed_client.post("/api/summary/generate", json={
            "clinicalNotes": "Test notes", "patientContext": {}})

        # Give asyncio.to_thread a moment to run the audit write
        import asyncio
        await asyncio.sleep(0.05)

        assert len(written_entries) >= 1
        entry = written_entries[0]
        assert "endpoint" in entry
        assert "user_hash" in entry
        assert "status" in entry
        assert "test@example.com" not in str(entry), "Raw email must not appear in audit entry"


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
