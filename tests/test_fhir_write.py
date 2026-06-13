"""Tests for FHIR write-back: Communication resource builder, the provider
(clinician) Epic app config, and the write endpoint's auth guard."""
import pytest

from fhir.client import FHIRClient
from fhir.ehr_config import get_ehr_config, config_status


class TestCommunicationBuilder:
    async def test_builds_r4_communication_and_posts(self):
        c = FHIRClient(fhir_base="https://x/api/FHIR/R4", access_token="t", ehr="epic_provider")
        captured = {}

        async def fake_post(path, body):
            captured["path"] = path
            captured["body"] = body
            return {"id": "comm123", "resourceType": "Communication"}

        c._post = fake_post  # type: ignore[assignment]
        res = await c.create_communication(
            patient_id="P1", message="Discharge plan ready for review",
            recipients=["CareTeam/CT1"], sender_display="Dr. Smith",
        )
        assert res["id"] == "comm123"
        assert captured["path"] == "/Communication"
        b = captured["body"]
        assert b["resourceType"] == "Communication"
        assert b["status"] == "completed"
        assert b["subject"]["reference"] == "Patient/P1"
        assert b["payload"][0]["contentString"] == "Discharge plan ready for review"
        assert b["recipient"][0]["reference"] == "CareTeam/CT1"
        assert b["sender"]["display"] == "Dr. Smith"
        assert "sent" in b

    async def test_recipients_optional(self):
        c = FHIRClient(fhir_base="https://x", access_token="t")
        captured = {}

        async def fake_post(path, body):
            captured["body"] = body
            return {"id": "c2"}

        c._post = fake_post  # type: ignore[assignment]
        await c.create_communication(patient_id="P9", message="hi")
        assert "recipient" not in captured["body"]


class TestProviderConfig:
    def test_epic_provider_has_write_scope(self, monkeypatch):
        monkeypatch.delenv("FHIR_SCOPES_EPIC_PROVIDER", raising=False)
        c = get_ehr_config("epic_provider")
        assert "user/Communication.write" in c.scopes
        assert c.display_name.startswith("Epic")

    def test_provider_scopes_overridable(self, monkeypatch):
        monkeypatch.setenv("FHIR_SCOPES_EPIC_PROVIDER", "openid user/Communication.write")
        c = get_ehr_config("epic_provider")
        assert c.scopes == ["openid", "user/Communication.write"]

    def test_provider_confidential_when_secret_set(self, monkeypatch):
        monkeypatch.setenv("FHIR_CLIENT_SECRET_EPIC_PROVIDER", "shh")
        c = get_ehr_config("epic_provider")
        assert c.is_public_client is False
        monkeypatch.delenv("FHIR_CLIENT_SECRET_EPIC_PROVIDER", raising=False)
        c2 = get_ehr_config("epic_provider")
        assert c2.is_public_client is True

    def test_config_status_lists_provider(self):
        assert "epic_provider" in {e["name"] for e in config_status()}


class TestWriteEndpointAuth:
    async def test_requires_auth(self, client):
        r = await client.post("/api/fhir/patient/P1/communication", json={"message": "hi"})
        assert r.status_code == 401
