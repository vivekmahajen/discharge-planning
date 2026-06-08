"""Tests for the read-only FHIR/EHR configuration diagnostic
(fhir.ehr_config.config_status and GET /api/fhir/status)."""
import json

from fhir.ehr_config import config_status


class TestConfigStatus:
    def test_unconfigured_by_default(self, monkeypatch):
        for v in ("FHIR_CLIENT_ID_EPIC", "FHIR_CLIENT_ID_CERNER",
                  "FHIR_CLIENT_ID_ATHENA", "FHIR_CLIENT_SECRET_ATHENA"):
            monkeypatch.delenv(v, raising=False)
        st = {e["name"]: e for e in config_status()}
        assert set(st) == {"epic", "cerner", "athena"}
        assert st["epic"]["configured"] is False
        assert st["epic"]["client_id_set"] is False
        assert st["epic"]["is_sandbox_default"] is True
        assert st["athena"]["requires_client_secret"] is True
        assert st["epic"]["requires_client_secret"] is False

    def test_epic_configured_with_client_id_only(self, monkeypatch):
        monkeypatch.setenv("FHIR_CLIENT_ID_EPIC", "abc123")
        st = {e["name"]: e for e in config_status()}
        assert st["epic"]["client_id_set"] is True
        # public/PKCE client needs no secret
        assert st["epic"]["configured"] is True

    def test_athena_needs_id_and_secret(self, monkeypatch):
        monkeypatch.setenv("FHIR_CLIENT_ID_ATHENA", "id")
        monkeypatch.delenv("FHIR_CLIENT_SECRET_ATHENA", raising=False)
        st = {e["name"]: e for e in config_status()}
        assert st["athena"]["client_id_set"] is True
        assert st["athena"]["configured"] is False  # missing secret
        monkeypatch.setenv("FHIR_CLIENT_SECRET_ATHENA", "sec")
        st2 = {e["name"]: e for e in config_status()}
        assert st2["athena"]["client_secret_set"] is True
        assert st2["athena"]["configured"] is True

    def test_no_secret_values_leaked(self, monkeypatch):
        monkeypatch.setenv("FHIR_CLIENT_ID_EPIC", "supersecretid")
        monkeypatch.setenv("FHIR_CLIENT_ID_ATHENA", "athenaid")
        monkeypatch.setenv("FHIR_CLIENT_SECRET_ATHENA", "supersecretvalue")
        blob = json.dumps(config_status())
        assert "supersecretid" not in blob
        assert "athenaid" not in blob
        assert "supersecretvalue" not in blob


class TestStatusEndpoint:
    async def test_requires_auth(self, client):
        r = await client.get("/api/fhir/status")
        assert r.status_code == 401

    async def test_returns_config_for_authed_user(self, authed_client):
        r = await authed_client.get("/api/fhir/status")
        assert r.status_code == 200
        data = r.json()
        assert data["fhir_loaded"] is True
        assert "redirect_uri" in data
        assert len(data["ehrs"]) == 3
        assert all("configured" in e and "fhir_base_url" in e for e in data["ehrs"])
