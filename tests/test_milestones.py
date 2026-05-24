"""Tests for Discharge Milestone / Barrier Tracking feature."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Catalog and db module unit tests ────────────────────────────────────────


class TestMilestonesCatalog:
    def test_barrier_catalog_has_24_entries(self):
        from db.milestones_catalog import BARRIER_CATALOG
        assert len(BARRIER_CATALOG) == 24

    def test_barrier_catalog_has_required_fields(self):
        from db.milestones_catalog import BARRIER_CATALOG
        required = {"label", "category", "default_sla_hours", "description", "auto_detect_keywords"}
        for key, entry in BARRIER_CATALOG.items():
            assert required.issubset(entry.keys()), f"Entry {key} missing fields"

    def test_barrier_categories_has_6_entries(self):
        from db.milestones_catalog import BARRIER_CATEGORIES
        assert len(BARRIER_CATEGORIES) == 6

    def test_barrier_categories_keys(self):
        from db.milestones_catalog import BARRIER_CATEGORIES
        expected = {"clinical", "authorization", "placement", "social", "documentation", "other"}
        assert set(BARRIER_CATEGORIES.keys()) == expected

    def test_all_barrier_types_have_valid_category(self):
        from db.milestones_catalog import BARRIER_CATALOG, BARRIER_CATEGORIES
        for key, entry in BARRIER_CATALOG.items():
            assert entry["category"] in BARRIER_CATEGORIES, (
                f"{key} has unknown category {entry['category']}"
            )

    def test_custom_barrier_type_exists(self):
        from db.milestones_catalog import BARRIER_CATALOG
        assert "custom" in BARRIER_CATALOG

    def test_pt_eval_pending_is_clinical(self):
        from db.milestones_catalog import BARRIER_CATALOG
        assert BARRIER_CATALOG["pt_eval_pending"]["category"] == "clinical"

    def test_snf_auth_pending_has_48h_sla(self):
        from db.milestones_catalog import BARRIER_CATALOG
        assert BARRIER_CATALOG["snf_auth_pending"]["default_sla_hours"] == 48

    def test_auto_detect_keywords_are_lists(self):
        from db.milestones_catalog import BARRIER_CATALOG
        for key, entry in BARRIER_CATALOG.items():
            assert isinstance(entry["auto_detect_keywords"], list)
            if key != "custom":
                assert len(entry["auto_detect_keywords"]) >= 1


class TestBarrierExtractionAgent:
    """Unit tests for BarrierExtractionAgent."""

    def _make_agent(self, response_text: str):
        from agents.barrier_extraction import BarrierExtractionAgent
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=response_text)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        return BarrierExtractionAgent(mock_client)

    async def test_run_returns_list(self):
        barriers_json = json.dumps([
            {
                "barrier_type": "pt_eval_pending",
                "label": "PT Evaluation Pending",
                "category": "clinical",
                "description": "PT eval not completed.",
                "priority": "high",
                "ai_confidence": 0.9,
                "ai_evidence": "PT evaluation not yet scheduled",
            }
        ])
        agent = self._make_agent(barriers_json)
        result = await agent.run("Discharge plan text", {}, {"patient_name": "Test"})
        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["barrier_type"] == "pt_eval_pending"

    async def test_run_filters_low_confidence(self):
        barriers_json = json.dumps([
            {
                "barrier_type": "pt_eval_pending",
                "label": "PT Evaluation",
                "category": "clinical",
                "description": "Maybe pending",
                "priority": "low",
                "ai_confidence": 0.3,
                "ai_evidence": "maybe",
            }
        ])
        agent = self._make_agent(barriers_json)
        result = await agent.run("plan", {}, {})
        assert len(result) == 0

    async def test_run_deduplicates_same_barrier_type(self):
        barriers_json = json.dumps([
            {"barrier_type": "pt_eval_pending", "label": "PT", "category": "clinical",
             "description": "PT pending", "priority": "high", "ai_confidence": 0.8, "ai_evidence": "ev1"},
            {"barrier_type": "pt_eval_pending", "label": "PT again", "category": "clinical",
             "description": "PT again", "priority": "medium", "ai_confidence": 0.75, "ai_evidence": "ev2"},
        ])
        agent = self._make_agent(barriers_json)
        result = await agent.run("plan", {}, {})
        assert len(result) == 1

    async def test_run_returns_empty_list_on_bad_json(self):
        agent = self._make_agent("not valid json at all")
        result = await agent.run("plan", {}, {})
        assert result == []

    async def test_run_returns_empty_on_empty_array(self):
        agent = self._make_agent("[]")
        result = await agent.run("plan", {}, {})
        assert result == []

    async def test_run_strips_markdown_fences(self):
        barriers_json = "```json\n[]\n```"
        agent = self._make_agent(barriers_json)
        result = await agent.run("plan", {}, {})
        assert result == []

    async def test_run_unknown_barrier_type_becomes_custom(self):
        barriers_json = json.dumps([
            {"barrier_type": "nonexistent_type_xyz", "label": "Unknown", "category": "other",
             "description": "desc", "priority": "medium", "ai_confidence": 0.9, "ai_evidence": "ev"}
        ])
        agent = self._make_agent(barriers_json)
        result = await agent.run("plan", {}, {})
        assert len(result) == 1
        assert result[0]["barrier_type"] == "custom"

    async def test_run_includes_agent_outputs_in_prompt(self):
        from agents.barrier_extraction import BarrierExtractionAgent
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="[]")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        agent = BarrierExtractionAgent(mock_client)
        agent_outputs = {"insurance": "Insurance text here", "care_needs": "Care needs text"}
        await agent.run("coordinator output", agent_outputs, {"patient_name": "Jane"})
        call_args = mock_client.messages.create.call_args
        content = call_args.kwargs.get("messages", [{}])[0].get("content", "")
        assert "Insurance text here" in content
        assert "Care needs text" in content


# ── Milestone API endpoint tests ─────────────────────────────────────────────


class TestMilestoneCatalogEndpoint:
    async def test_catalog_endpoint_returns_200(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        r = await authed_client.get("/api/milestones/catalog")
        assert r.status_code == 200
        data = r.json()
        assert "catalog" in data
        assert "categories" in data

    async def test_catalog_endpoint_unavailable_returns_empty(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", False)
        r = await authed_client.get("/api/milestones/catalog")
        assert r.status_code == 200
        assert r.json()["catalog"] == []

    async def test_catalog_has_24_entries(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        r = await authed_client.get("/api/milestones/catalog")
        assert r.status_code == 200
        assert len(r.json()["catalog"]) == 24

    async def test_catalog_does_not_include_auto_detect_keywords(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        r = await authed_client.get("/api/milestones/catalog")
        for entry in r.json()["catalog"]:
            assert "auto_detect_keywords" not in entry


class TestWardSummaryEndpoint:
    async def test_ward_summary_unavailable_returns_empty(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", False)
        r = await authed_client.get("/api/milestones/ward-summary")
        assert r.status_code == 200
        assert r.json()["summary"] == {}

    async def test_ward_summary_no_db_returns_empty(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await authed_client.get("/api/milestones/ward-summary")
        assert r.status_code == 200
        assert r.json()["summary"] == {}

    async def test_ward_summary_with_db_returns_summary(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        fake_summary = {
            "total_open": 5, "overdue": 2, "by_category": {"clinical": 3}, "by_patient": [{"patient_id": 1, "total": 2, "overdue": 1}]
        }
        monkeypatch.setattr(web_app, "_get_org_milestone_summary", lambda org: fake_summary)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/milestones/ward-summary")
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["open_count"] == 5
        assert data["summary"]["overdue_count"] == 2
        assert data["summary"]["patients_with_barriers"] == 1

    async def test_ward_summary_db_error_returns_500(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_get_org_milestone_summary", lambda org: (_ for _ in ()).throw(RuntimeError("DB error")))
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/milestones/ward-summary")
        assert r.status_code == 500


class TestListPatientMilestones:
    async def test_list_unavailable_returns_empty(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", False)
        r = await authed_client.get("/api/patients/1/milestones")
        assert r.status_code == 200
        assert r.json()["milestones"] == []

    async def test_list_no_db_returns_empty(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await authed_client.get("/api/patients/1/milestones")
        assert r.status_code == 200

    async def test_list_patient_not_found_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(_dp, "get_patient_detail", lambda pid, org: None)
        r = await db_authed_client.get("/api/patients/999/milestones")
        assert r.status_code == 404

    async def test_list_returns_milestones(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(_dp, "get_patient_detail", lambda pid, org: {"id": 1, "mrn": "MRN001"})
        fake_milestones = [
            {"id": 1, "patient_id": 1, "barrier_type": "pt_eval_pending", "status": "open", "is_overdue": False},
        ]
        monkeypatch.setattr(web_app, "_get_milestones_for_patient", lambda pid, org, inc: fake_milestones)
        r = await db_authed_client.get("/api/patients/1/milestones")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["milestones"][0]["barrier_type"] == "pt_eval_pending"


class TestCreatePatientMilestone:
    async def test_create_unavailable_returns_503(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", False)
        r = await authed_client.post("/api/patients/1/milestones", json={"barrier_type": "pt_eval_pending"})
        assert r.status_code == 503

    async def test_create_no_db_returns_503(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await authed_client.post("/api/patients/1/milestones", json={"barrier_type": "custom"})
        assert r.status_code == 503

    async def test_create_patient_not_found_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(_dp, "get_patient_detail", lambda pid, org: None)
        r = await db_authed_client.post("/api/patients/999/milestones", json={"barrier_type": "custom"})
        assert r.status_code == 404

    async def test_create_success_returns_201(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(_dp, "get_patient_detail", lambda pid, org: {"id": 1, "mrn": "MRN001"})
        fake_milestone = {"id": 42, "patient_id": 1, "barrier_type": "custom", "status": "open"}
        monkeypatch.setattr(web_app, "_create_milestone", lambda *a, **kw: fake_milestone)
        r = await db_authed_client.post(
            "/api/patients/1/milestones",
            json={"barrier_type": "custom", "description": "test barrier", "priority": "medium"}
        )
        assert r.status_code == 201
        assert r.json()["milestone"]["id"] == 42


class TestUpdatePatientMilestone:
    async def test_update_unavailable_returns_503(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", False)
        r = await authed_client.patch("/api/patients/1/milestones/1", json={"status": "resolved"})
        assert r.status_code == 503

    async def test_update_milestone_not_found_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(web_app, "_get_milestone_by_id", lambda mid, org: None)
        r = await db_authed_client.patch("/api/patients/1/milestones/999", json={"status": "resolved"})
        assert r.status_code == 404

    async def test_update_wrong_patient_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        # Milestone belongs to patient_id=99, not 1
        monkeypatch.setattr(web_app, "_get_milestone_by_id", lambda mid, org: {"id": mid, "patient_id": 99})
        r = await db_authed_client.patch("/api/patients/1/milestones/10", json={"status": "resolved"})
        assert r.status_code == 404

    async def test_update_success(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(web_app, "_get_milestone_by_id", lambda mid, org: {"id": mid, "patient_id": 1})
        updated = {"id": 1, "patient_id": 1, "status": "resolved"}
        monkeypatch.setattr(web_app, "_update_milestone", lambda *a, **kw: updated)
        r = await db_authed_client.patch("/api/patients/1/milestones/1", json={"status": "resolved"})
        assert r.status_code == 200
        assert r.json()["milestone"]["status"] == "resolved"


class TestDeletePatientMilestone:
    async def test_delete_unavailable_returns_503(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", False)
        r = await authed_client.delete("/api/patients/1/milestones/1")
        assert r.status_code == 503

    async def test_delete_not_found_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(web_app, "_get_milestone_by_id", lambda mid, org: None)
        r = await db_authed_client.delete("/api/patients/1/milestones/999")
        assert r.status_code == 404

    async def test_delete_ai_barrier_returns_403(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(web_app, "_get_milestone_by_id", lambda mid, org: {"id": mid, "patient_id": 1})
        monkeypatch.setattr(web_app, "_delete_milestone", lambda mid, org, by: False)
        r = await db_authed_client.delete("/api/patients/1/milestones/1")
        assert r.status_code == 403

    async def test_delete_manual_barrier_succeeds(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(web_app, "_get_milestone_by_id", lambda mid, org: {"id": mid, "patient_id": 1})
        monkeypatch.setattr(web_app, "_delete_milestone", lambda mid, org, by: True)
        r = await db_authed_client.delete("/api/patients/1/milestones/1")
        assert r.status_code == 200
        assert r.json()["success"] is True


class TestPatientMilestoneSummary:
    async def test_summary_unavailable_returns_zeros(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", False)
        r = await authed_client.get("/api/patients/1/milestones/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["open"] == 0

    async def test_summary_patient_not_found_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(_dp, "get_patient_detail", lambda pid, org: None)
        r = await db_authed_client.get("/api/patients/999/milestones/summary")
        assert r.status_code == 404

    async def test_summary_returns_open_and_overdue(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_MILESTONES_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        from db import patients as _dp
        monkeypatch.setattr(_dp, "get_org_domain", lambda email: "example.com")
        monkeypatch.setattr(_dp, "get_patient_detail", lambda pid, org: {"id": 1})
        monkeypatch.setattr(web_app, "_get_open_milestone_count", lambda pid, org: {"total_open": 3, "overdue": 1, "critical": 0, "ca_specific": 0})
        r = await db_authed_client.get("/api/patients/1/milestones/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["open"] == 3
        assert data["overdue"] == 1


class TestWardBarriersPage:
    async def test_ward_barriers_page_redirects_when_not_logged_in(self, client):
        r = await client.get("/ward-barriers", follow_redirects=False)
        assert r.status_code in (302, 307)

    async def test_ward_barriers_page_returns_200_when_logged_in(self, authed_client, monkeypatch):
        import web_app
        # Ensure the static file exists
        import os
        from pathlib import Path
        html_path = Path(web_app.STATIC_DIR) / "ward-barriers.html"
        assert html_path.exists(), "ward-barriers.html must exist"
        r = await authed_client.get("/ward-barriers")
        assert r.status_code == 200
        assert "Ward Barriers" in r.text or "ward" in r.text.lower()


class TestMilestonesImportBlock:
    def test_milestones_available_flag_is_bool(self):
        import web_app
        assert isinstance(web_app._MILESTONES_AVAILABLE, bool)

    def test_milestones_available_is_true(self):
        import web_app
        assert web_app._MILESTONES_AVAILABLE is True

    def test_barrier_catalog_imported(self):
        import web_app
        assert hasattr(web_app, "_BARRIER_CATALOG")
        assert len(web_app._BARRIER_CATALOG) == 24


class TestMilestonesDbModule:
    """Unit tests for db/milestones.py functions (no real DB)."""

    def test_serialize_row_converts_datetimes(self):
        from db.milestones import _serialize_row
        from datetime import datetime, timezone
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        row = {"id": 1, "due_date": dt, "status": "open"}
        result = _serialize_row(row)
        assert result["due_date"] == dt.isoformat()
        assert result["status"] == "open"

    def test_enrich_row_marks_overdue(self):
        from db.milestones import _enrich_row
        from datetime import datetime, timezone, timedelta
        past_date = datetime.now(timezone.utc) - timedelta(hours=2)
        row = {"id": 1, "due_date": past_date, "status": "open", "patient_id": 1,
               "barrier_type": "pt_eval_pending", "org_domain": "hosp.org",
               "category": "clinical", "label": "PT Eval", "description": "",
               "assigned_to": None, "resolved_at": None, "dismissed_at": None,
               "dismissed_reason": None, "source": "manual", "run_id": None,
               "ai_confidence": None, "ai_evidence": None, "priority": "high",
               "is_ca_specific": False, "created_by": "dr@hosp.org",
               "created_at": datetime.now(timezone.utc),
               "updated_at": datetime.now(timezone.utc), "notes": None}
        result = _enrich_row(row)
        assert result["is_overdue"] is True

    def test_enrich_row_not_overdue_when_resolved(self):
        from db.milestones import _enrich_row
        from datetime import datetime, timezone, timedelta
        past_date = datetime.now(timezone.utc) - timedelta(hours=2)
        row = {"id": 1, "due_date": past_date, "status": "resolved", "patient_id": 1,
               "barrier_type": "pt_eval_pending", "org_domain": "hosp.org",
               "category": "clinical", "label": "PT Eval", "description": "",
               "assigned_to": None, "resolved_at": datetime.now(timezone.utc),
               "dismissed_at": None, "dismissed_reason": None, "source": "manual",
               "run_id": None, "ai_confidence": None, "ai_evidence": None,
               "priority": "medium", "is_ca_specific": False, "created_by": "dr@hosp.org",
               "created_at": datetime.now(timezone.utc),
               "updated_at": datetime.now(timezone.utc), "notes": None}
        result = _enrich_row(row)
        assert result["is_overdue"] is False

    def test_enrich_row_no_due_date_not_overdue(self):
        from db.milestones import _enrich_row
        from datetime import datetime, timezone
        row = {"id": 1, "due_date": None, "status": "open", "patient_id": 1,
               "barrier_type": "custom", "org_domain": "hosp.org",
               "category": "other", "label": "Custom", "description": "",
               "assigned_to": None, "resolved_at": None, "dismissed_at": None,
               "dismissed_reason": None, "source": "manual", "run_id": None,
               "ai_confidence": None, "ai_evidence": None, "priority": "low",
               "is_ca_specific": False, "created_by": "dr@hosp.org",
               "created_at": datetime.now(timezone.utc),
               "updated_at": datetime.now(timezone.utc), "notes": None}
        result = _enrich_row(row)
        assert result["is_overdue"] is False
        assert result["hours_until_due"] is None

    def test_valid_statuses_constant(self):
        from db.milestones import VALID_STATUSES
        assert "open" in VALID_STATUSES
        assert "resolved" in VALID_STATUSES
        assert "dismissed" in VALID_STATUSES

    def test_ca_specific_types_constant(self):
        from db.milestones import CA_SPECIFIC_TYPES
        assert "snf_auth_pending" in CA_SPECIFIC_TYPES
        assert "medi_cal_eligibility_issue" in CA_SPECIFIC_TYPES
