"""Tests for Post-Acute Referral Workflow endpoints."""
from __future__ import annotations
import pytest
from unittest.mock import MagicMock


pytestmark = pytest.mark.anyio


# ── Pure-unit tests for referral_packet service ───────────────────────────────

class TestBuildFhirServiceRequest:
    def test_returns_valid_fhir_structure(self):
        from services.referral_packet import build_fhir_service_request
        result = build_fhir_service_request(
            patient_data={"mrn": "MRN001", "patient_name": "John Doe", "primary_diagnosis": "CHF"},
            facility={"name": "Sunrise SNF", "ccn": "123456"},
            referral_id=42,
            service_type="Skilled Nursing Facility",
            urgency="routine",
            referral_notes="Needs SNF level of care",
            ordering_clinician="dr@hospital.com",
        )
        assert result["resourceType"] == "ServiceRequest"
        assert result["intent"] == "order"
        assert result["status"] == "draft"
        assert any(
            id_["system"] == "urn:discharge-planning:referrals" and id_["value"] == "42"
            for id_ in result.get("identifier", [])
        )

    def test_urgency_mapping_stat(self):
        from services.referral_packet import build_fhir_service_request
        result = build_fhir_service_request(
            patient_data={"mrn": "MRN002"},
            facility={"name": "Test Facility", "ccn": "999"},
            referral_id=1,
            service_type="IRF",
            urgency="stat",
            referral_notes="",
            ordering_clinician="clinician@org.com",
        )
        assert result["priority"] == "asap"

    def test_urgency_mapping_urgent(self):
        from services.referral_packet import build_fhir_service_request
        result = build_fhir_service_request(
            patient_data={"mrn": "MRN003"},
            facility={"name": "Test Facility", "ccn": "999"},
            referral_id=2,
            service_type="SNF",
            urgency="urgent",
            referral_notes="",
            ordering_clinician="clinician@org.com",
        )
        assert result["priority"] == "urgent"

    def test_urgency_mapping_routine(self):
        from services.referral_packet import build_fhir_service_request
        result = build_fhir_service_request(
            patient_data={"mrn": "MRN004"},
            facility={"name": "Test Facility", "ccn": "999"},
            referral_id=3,
            service_type="SNF",
            urgency="routine",
            referral_notes="",
            ordering_clinician="clinician@org.com",
        )
        assert result["priority"] == "routine"

    def test_category_uses_snomed(self):
        from services.referral_packet import build_fhir_service_request
        result = build_fhir_service_request(
            patient_data={"mrn": "M1"},
            facility={"name": "Facility", "ccn": "1"},
            referral_id=10,
            service_type="SNF",
            urgency="routine",
            referral_notes="",
            ordering_clinician="dr@h.com",
        )
        categories = result.get("category", [])
        assert any("snomed.info" in str(c) for c in categories)


class TestBuildReferralHtml:
    def test_returns_html_string(self):
        from services.referral_packet import build_referral_html
        html = build_referral_html(
            patient_data={"mrn": "MRN001", "patient_name": "Jane Doe"},
            facility={"name": "Sunrise SNF", "ccn": "123456"},
            referral={
                "id": 1, "urgency": "routine", "service_type": "SNF",
                "referral_notes": "Needs SNF", "facility_name": "Sunrise SNF",
                "created_at": "2026-05-25T00:00:00",
            },
            org_settings={"org_name": "General Hospital", "org_fax": "+14155550000"},
            ai_summary="Patient requires skilled nursing care.",
            fhir_sr={"resourceType": "ServiceRequest", "identifier": [{"value": "1"}]},
        )
        assert "<!DOCTYPE html>" in html or "<html" in html
        assert "Sunrise SNF" in html

    def test_html_escapes_patient_name(self):
        from services.referral_packet import build_referral_html
        html = build_referral_html(
            patient_data={"mrn": "X1", "patient_name": "<script>xss</script>"},
            facility={"name": "Facility", "ccn": "1"},
            referral={"id": 99, "urgency": "routine", "service_type": "SNF",
                      "referral_notes": "", "facility_name": "Facility",
                      "created_at": "2026-05-25"},
            org_settings={},
            ai_summary="",
            fhir_sr={},
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html or "script" not in html


class TestDeliveryStatus:
    def test_returns_dict_with_channel_keys(self, monkeypatch):
        from services.referral_delivery import get_delivery_status
        import os
        monkeypatch.delenv("DOCUMO_API_KEY", raising=False)
        monkeypatch.delenv("CAREPORT_API_KEY", raising=False)
        status = get_delivery_status()
        assert "fax" in status
        assert "careport" in status
        assert "direct" in status
        assert status["fax"] is False
        assert status["careport"] is False

    def test_fax_active_when_documo_key_set(self, monkeypatch):
        from services.referral_delivery import get_delivery_status
        monkeypatch.setenv("DOCUMO_API_KEY", "doc-test-key")
        monkeypatch.delenv("CAREPORT_API_KEY", raising=False)
        status = get_delivery_status()
        assert status["fax"] is True

    def test_careport_active_when_key_set(self, monkeypatch):
        from services.referral_delivery import get_delivery_status
        monkeypatch.setenv("CAREPORT_API_KEY", "cp-test-key")
        status = get_delivery_status()
        assert status["careport"] is True


class TestSendViaFax:
    async def test_returns_error_when_key_not_configured(self, monkeypatch):
        from services.referral_delivery import send_via_fax
        monkeypatch.delenv("DOCUMO_API_KEY", raising=False)
        result = await send_via_fax(1, "+14155551234", "<html>packet</html>", "123456")
        assert result["success"] is False
        assert "DOCUMO_API_KEY" in result["error"]

    async def test_never_includes_packet_html_in_error(self, monkeypatch):
        from services.referral_delivery import send_via_fax
        monkeypatch.delenv("DOCUMO_API_KEY", raising=False)
        secret_content = "PATIENT_SECRET_DATA"
        result = await send_via_fax(1, "+14155551234", f"<html>{secret_content}</html>", "123")
        result_str = str(result)
        assert secret_content not in result_str


class TestSendViaCarePort:
    async def test_returns_stub_when_key_not_set(self, monkeypatch):
        from services.referral_delivery import send_via_careport
        monkeypatch.delenv("CAREPORT_API_KEY", raising=False)
        result = await send_via_careport(1, {"resourceType": "ServiceRequest"}, "123456")
        assert result["success"] is False
        assert "careport" in result["channel"].lower() or "careport" in str(result).lower()

    async def test_does_not_make_http_call_without_key(self, monkeypatch):
        from services.referral_delivery import send_via_careport
        monkeypatch.delenv("CAREPORT_API_KEY", raising=False)
        http_calls = []
        monkeypatch.setattr("httpx.AsyncClient.post", lambda *a, **kw: http_calls.append(a))
        await send_via_careport(1, {}, "123")
        assert len(http_calls) == 0


# ── API endpoint tests ────────────────────────────────────────────────────────

class TestReferralPageRoute:
    async def test_ward_referrals_page_requires_auth(self, client):
        r = await client.get("/ward-referrals")
        assert r.status_code in (302, 307, 401, 403)

    async def test_ward_referrals_page_returns_html(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await authed_client.get("/ward-referrals")
        assert r.status_code == 200
        assert "referral" in r.text.lower()


class TestReferralsAvailableFlag:
    async def test_list_returns_empty_when_unavailable(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", False)
        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake/db")
        r = await authed_client.get("/api/referrals")
        assert r.status_code == 200
        assert r.json()["referrals"] == []

    async def test_analytics_returns_empty_when_unavailable(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", False)
        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake/db")
        r = await authed_client.get("/api/referrals/analytics")
        assert r.status_code == 200
        assert r.json()["total"] == 0

    async def test_delivery_status_returns_false_when_unavailable(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", False)
        r = await authed_client.get("/api/referrals/delivery-status")
        assert r.status_code == 200
        data = r.json()
        assert data["fax"] is False
        assert data["careport"] is False


class TestReferralCrudEndpoints:
    async def test_list_referrals(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_list_referrals", lambda *a, **kw: [
            {"id": 1, "facility_name": "Test SNF", "status": "sent", "patient_id": 5}
        ])
        r = await db_authed_client.get("/api/referrals")
        assert r.status_code == 200
        data = r.json()
        assert len(data["referrals"]) == 1
        assert data["referrals"][0]["facility_name"] == "Test SNF"

    async def test_list_referrals_filters_by_status(self, db_authed_client, monkeypatch):
        import web_app
        captured = {}
        def _fake_list(org, patient_id, status, limit, offset):
            captured["status"] = status
            return []
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_list_referrals", _fake_list)
        r = await db_authed_client.get("/api/referrals?status=accepted")
        assert r.status_code == 200
        assert captured["status"] == "accepted"

    async def test_create_referral(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_create_referral", lambda pid, org, by, data: {
            "id": 10, "patient_id": pid, "status": "draft",
            "facility_name": data.get("facility_name", "Test"),
        })
        r = await db_authed_client.post("/api/referrals", json={
            "patient_id": 5, "facility_name": "Sunrise SNF",
            "facility_fax": "+14155551234", "delivery_channel": "fax",
        })
        assert r.status_code == 200
        assert r.json()["id"] == 10
        assert r.json()["status"] == "draft"

    async def test_get_referral_not_found_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: None)
        r = await db_authed_client.get("/api/referrals/999")
        assert r.status_code == 404

    async def test_get_referral_returns_data(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {
            "id": rid, "status": "sent", "facility_name": "Test SNF"
        })
        r = await db_authed_client.get("/api/referrals/5")
        assert r.status_code == 200
        assert r.json()["status"] == "sent"

    async def test_update_status_valid(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_update_referral_status", lambda rid, org, status, by, notes: {
            "id": rid, "status": status
        })
        r = await db_authed_client.patch("/api/referrals/5/status", json={"status": "accepted"})
        assert r.status_code == 200
        assert r.json()["status"] == "accepted"

    async def test_update_status_invalid_422(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        r = await db_authed_client.patch("/api/referrals/5/status", json={"status": "invalid_status"})
        assert r.status_code == 422

    async def test_update_status_not_found_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_update_referral_status", lambda *a: None)
        r = await db_authed_client.patch("/api/referrals/999/status", json={"status": "accepted"})
        assert r.status_code == 404


class TestReferralDeliveryEndpoints:
    async def test_send_referral_manual_channel(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {
            "id": rid, "delivery_channel": "manual", "facility_fax": None,
            "packet_html": "", "facility_ccn": "", "facility_name": "Test SNF",
        })
        monkeypatch.setattr(web_app, "_log_delivery_attempt", lambda *a: 1)
        monkeypatch.setattr(web_app, "_update_referral_status", lambda *a: {"id": 1, "status": "sent"})
        r = await db_authed_client.post("/api/referrals/1/send")
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_send_referral_fax_no_key(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {
            "id": rid, "delivery_channel": "fax", "facility_fax": "+14155551234",
            "packet_html": "<html>Test</html>", "facility_ccn": "123456",
        })
        monkeypatch.setattr(web_app, "_log_delivery_attempt", lambda *a: 1)
        monkeypatch.setattr(web_app, "_update_referral_status", lambda *a: None)
        monkeypatch.delenv("DOCUMO_API_KEY", raising=False)
        r = await db_authed_client.post("/api/referrals/1/send")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False

    async def test_resend_referral(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {
            "id": rid, "delivery_channel": "manual", "facility_fax": None,
            "packet_html": "", "facility_ccn": "",
        })
        monkeypatch.setattr(web_app, "_log_delivery_attempt", lambda *a: 1)
        monkeypatch.setattr(web_app, "_update_referral_status", lambda *a: {"id": 1, "status": "sent"})
        r = await db_authed_client.post("/api/referrals/1/resend")
        assert r.status_code == 200

    async def test_delivery_log(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {"id": rid})
        monkeypatch.setattr(web_app, "_get_delivery_log", lambda rid: [
            {"id": 1, "channel": "fax", "success": True, "reference_id": "doc-123"}
        ])
        r = await db_authed_client.get("/api/referrals/1/delivery-log")
        assert r.status_code == 200
        assert len(r.json()["log"]) == 1


class TestReferralMessagesEndpoints:
    async def test_get_messages_empty(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {"id": rid})
        monkeypatch.setattr(web_app, "_get_referral_messages", lambda rid, org: [])
        r = await db_authed_client.get("/api/referrals/1/messages")
        assert r.status_code == 200
        assert r.json()["messages"] == []

    async def test_add_message(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {"id": rid})
        monkeypatch.setattr(web_app, "_add_referral_message", lambda rid, org, author, text: {
            "id": 1, "message_text": text, "author_email": author
        })
        r = await db_authed_client.post(
            "/api/referrals/1/messages",
            json={"message_text": "Patient accepted, confirm bed availability"},
        )
        assert r.status_code == 200
        assert "message_text" in r.json()

    async def test_add_message_empty_text_422(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: {"id": rid})
        r = await db_authed_client.post(
            "/api/referrals/1/messages",
            json={"message_text": "  "},
        )
        assert r.status_code == 422

    async def test_add_message_referral_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral", lambda rid, org: None)
        r = await db_authed_client.post(
            "/api/referrals/999/messages",
            json={"message_text": "Test"},
        )
        assert r.status_code == 404


class TestReferralSettingsEndpoints:
    async def test_get_settings(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_org_referral_settings", lambda org: {
            "default_channel": "fax", "org_name": "Test Hospital"
        })
        r = await db_authed_client.get("/api/referrals/settings")
        assert r.status_code == 200
        assert r.json()["default_channel"] == "fax"

    async def test_patch_settings(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_upsert_org_referral_settings", lambda org, data: {
            "default_channel": data.get("default_channel", "fax"),
            "org_name": data.get("org_name", ""),
        })
        r = await db_authed_client.patch(
            "/api/referrals/settings",
            json={"default_channel": "manual", "org_name": "Updated Hospital"},
        )
        assert r.status_code == 200
        assert r.json()["default_channel"] == "manual"

    async def test_get_delivery_status_endpoint(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_delivery_status", lambda: {
            "fax": True, "careport": False, "direct": False
        })
        r = await db_authed_client.get("/api/referrals/delivery-status")
        assert r.status_code == 200
        data = r.json()
        assert data["fax"] is True

    async def test_get_settings_unavailable_returns_defaults(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", False)
        monkeypatch.setattr(web_app, "DATABASE_URL", "postgresql://fake/db")
        r = await authed_client.get("/api/referrals/settings")
        assert r.status_code == 200
        assert "default_channel" in r.json()


class TestReferralAnalytics:
    async def test_analytics_returns_data(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_REFERRALS_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_referral_analytics", lambda org, days: {
            "total": 10,
            "by_status": {"sent": 4, "accepted": 3, "declined": 3},
            "by_channel": {"fax": 8, "manual": 2},
            "avg_time_to_accept_hours": 24.5,
        })
        r = await db_authed_client.get("/api/referrals/analytics")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 10
        assert "by_status" in data


class TestReferralAuthRequired:
    async def test_list_requires_auth(self, client):
        r = await client.get("/api/referrals")
        assert r.status_code in (302, 307, 401, 403)

    async def test_create_requires_auth(self, client):
        r = await client.post("/api/referrals", json={"patient_id": 1})
        assert r.status_code in (302, 307, 401, 403)

    async def test_send_requires_auth(self, client):
        r = await client.post("/api/referrals/1/send")
        assert r.status_code in (302, 307, 401, 403)
