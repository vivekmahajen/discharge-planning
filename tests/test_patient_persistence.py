"""Tests for Patient Record Persistence endpoints and auto-save stream logic."""
import pytest
from unittest.mock import patch


class TestListPatients:
    async def test_list_patients_no_db_returns_empty(self, authed_client):
        r = await authed_client.get("/api/patients")
        assert r.status_code == 200
        data = r.json()
        assert data["patients"] == []
        assert data["total"] == 0

    async def test_list_patients_with_db(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        fake_patients = [
            {"id": 1, "mrn": "12345", "patient_name": "Test Patient",
             "admission_date": "2026-01-01", "status": "active",
             "org_domain": "hospital.org", "total_runs": 2,
             "last_run_at": None, "last_run_by": None,
             "created_by": "doc@hospital.org", "primary_diagnosis": "CHF",
             "date_of_birth": None, "created_at": "2026-01-01T00:00:00Z",
             "updated_at": "2026-01-01T00:00:00Z"}
        ]
        with patch("db.patients.get_patients_for_org", return_value=fake_patients):
            r = await db_authed_client.get("/api/patients")
        assert r.status_code == 200
        data = r.json()
        assert len(data["patients"]) == 1
        assert data["patients"][0]["mrn"] == "12345"

    async def test_search_patients(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.search_patients", return_value=[]) as mock_search:
            r = await db_authed_client.get("/api/patients?search=smith")
        assert r.status_code == 200
        mock_search.assert_called_once()

    async def test_list_db_error_returns_empty(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.get_patients_for_org", side_effect=Exception("DB error")):
            r = await db_authed_client.get("/api/patients")
        assert r.status_code == 200
        data = r.json()
        assert data["patients"] == []
        assert "error" in data


class TestGetPatient:
    async def test_get_patient_no_db(self, authed_client):
        r = await authed_client.get("/api/patients/1")
        assert r.status_code == 503

    async def test_get_patient_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.get_patient_detail", return_value=None):
            r = await db_authed_client.get("/api/patients/999")
        assert r.status_code == 404

    async def test_get_patient_success(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        fake = {
            "id": 1, "mrn": "12345", "patient_name": "Test", "status": "active",
            "admission_date": "2026-01-01", "org_domain": "hospital.org",
            "runs": [], "notes": [], "status_history": [],
            "created_by": "doc@hospital.org", "primary_diagnosis": None,
            "date_of_birth": None, "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with patch("db.patients.get_patient_detail", return_value=fake):
            r = await db_authed_client.get("/api/patients/1")
        assert r.status_code == 200
        assert r.json()["patient"]["mrn"] == "12345"


class TestGetPrefill:
    async def test_prefill_no_db(self, authed_client):
        r = await authed_client.get("/api/patients/1/prefill")
        assert r.status_code == 503

    async def test_prefill_patient_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.get_patient_detail", return_value=None):
            r = await db_authed_client.get("/api/patients/999/prefill")
        assert r.status_code == 404

    async def test_prefill_returns_snapshot(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        fake_patient = {
            "id": 1, "mrn": "12345", "patient_name": "Test", "status": "active",
            "runs": [{"id": 10, "started_at": "2026-01-01"}],
            "notes": [], "status_history": [],
        }
        fake_snapshot = {"mrn": "12345", "primary_diagnosis": "CHF"}
        with (
            patch("db.patients.get_patient_detail", return_value=fake_patient),
            patch("db.patients.get_latest_snapshot", return_value=fake_snapshot),
        ):
            r = await db_authed_client.get("/api/patients/1/prefill")
        assert r.status_code == 200
        data = r.json()
        assert data["patient_data"]["mrn"] == "12345"
        assert data["run_count"] == 1


class TestUpdateStatus:
    async def test_update_status_no_db(self, authed_client):
        r = await authed_client.patch("/api/patients/1/status",
                                       json={"status": "discharged"})
        assert r.status_code == 503

    async def test_update_status_invalid(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        r = await db_authed_client.patch("/api/patients/1/status",
                                          json={"status": "invalid_status"})
        assert r.status_code == 400

    async def test_update_status_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.get_patient_detail", return_value=None):
            r = await db_authed_client.patch("/api/patients/1/status",
                                              json={"status": "discharged"})
        assert r.status_code == 404

    async def test_update_status_success(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        fake_patient = {"id": 1, "status": "active"}
        with (
            patch("db.patients.get_patient_detail", return_value=fake_patient),
            patch("db.patients.update_patient_status", return_value=None),
        ):
            r = await db_authed_client.patch("/api/patients/1/status",
                                              json={"status": "discharged"})
        assert r.status_code == 200
        assert r.json()["status"] == "discharged"


class TestPatientNotes:
    async def test_add_note_no_db(self, authed_client):
        r = await authed_client.post("/api/patients/1/notes",
                                      json={"note_text": "Test note"})
        assert r.status_code == 503

    async def test_add_note_missing_text(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        r = await db_authed_client.post("/api/patients/1/notes",
                                         json={"note_text": ""})
        assert r.status_code == 400

    async def test_add_note_patient_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.get_patient_detail", return_value=None):
            r = await db_authed_client.post("/api/patients/1/notes",
                                             json={"note_text": "Test"})
        assert r.status_code == 404

    async def test_add_note_success(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        import datetime
        fake_note = {
            "id": 1, "patient_id": 1, "note_text": "Test note",
            "author_email": "dbtest@example.com", "is_deleted": False,
            "created_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
            "updated_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        }
        with (
            patch("db.patients.get_patient_detail", return_value={"id": 1}),
            patch("db.patients.add_patient_note", return_value=fake_note),
        ):
            r = await db_authed_client.post("/api/patients/1/notes",
                                             json={"note_text": "Test note"})
        assert r.status_code == 200
        assert r.json()["note_text"] == "Test note"

    async def test_delete_note_no_db(self, authed_client):
        r = await authed_client.delete("/api/patients/1/notes/1")
        assert r.status_code == 503

    async def test_delete_note_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.delete_patient_note", return_value=False):
            r = await db_authed_client.delete("/api/patients/1/notes/999")
        assert r.status_code == 404

    async def test_delete_note_success(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.delete_patient_note", return_value=True):
            r = await db_authed_client.delete("/api/patients/1/notes/1")
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestExportRun:
    async def test_export_no_db(self, authed_client):
        r = await authed_client.get("/api/patients/1/runs/1/export")
        assert r.status_code == 503

    async def test_export_patient_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        with patch("db.patients.get_patient_detail", return_value=None):
            r = await db_authed_client.get("/api/patients/1/runs/999/export")
        assert r.status_code == 404

    async def test_export_run_not_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        fake_patient = {"id": 1, "mrn": "123", "patient_name": "Test",
                        "admission_date": "2026-01-01", "runs": []}
        with patch("db.patients.get_patient_detail", return_value=fake_patient):
            r = await db_authed_client.get("/api/patients/1/runs/999/export")
        assert r.status_code == 404

    async def test_export_run_success(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        import datetime
        fake_patient = {
            "id": 1, "mrn": "12345", "patient_name": "John Doe",
            "admission_date": datetime.date(2026, 1, 1),
            "runs": [{
                "id": 1, "run_number": 1, "status": "complete",
                "started_at": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
                "completed_at": datetime.datetime(2026, 1, 2, tzinfo=datetime.timezone.utc),
                "run_by": "doc@hospital.org", "final_plan": "Test plan",
                "agents": [{"agent_name": "clinical", "output_text": "Clinical output"}],
            }],
        }
        with patch("db.patients.get_patient_detail", return_value=fake_patient):
            r = await db_authed_client.get("/api/patients/1/runs/1/export")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "John Doe" in r.text
        assert "12345" in r.text


class TestPatientPages:
    async def test_my_patients_page_unauthenticated_redirects(self, client):
        r = await client.get("/my-patients", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    async def test_my_patients_page_authenticated(self, authed_client):
        r = await authed_client.get("/my-patients")
        assert r.status_code == 200
        assert "Discharge Planning AI" in r.text

    async def test_patient_detail_page_unauthenticated_redirects(self, client):
        r = await client.get("/patients/1", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    async def test_patient_detail_page_authenticated(self, authed_client):
        r = await authed_client.get("/patients/1")
        assert r.status_code == 200
        assert "Discharge Planning AI" in r.text


class TestAutoSaveInStream:
    async def test_stream_emits_warning_without_mrn(
            self, authed_client, mock_stream_plan, sample_patient):
        sample = dict(sample_patient)
        sample.pop("mrn", None)
        sample.pop("admission_date", None)
        chunks = []
        async with authed_client.stream("POST", "/api/plan/stream", json=sample) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    chunks.append(line[6:])
        import json
        events = [json.loads(c) for c in chunks if c]
        types = [e["type"] for e in events]
        assert "warning" in types

    async def test_stream_saves_patient_record_when_db_available(
            self, db_authed_client, mock_stream_plan, sample_patient, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)

        fake_patient = {"id": 42, "mrn": "MRN001", "status": "active"}

        with (
            patch("db.patients.get_or_create_patient", return_value=fake_patient),
            patch("db.patients.save_snapshot", return_value=1),
            patch("db.patients.start_plan_run", return_value=7),
            patch("db.patients.save_agent_output", return_value=None),
            patch("db.patients.complete_plan_run", return_value=None),
        ):
            chunks = []
            async with db_authed_client.stream(
                    "POST", "/api/plan/stream", json=sample_patient) as resp:
                assert resp.status_code == 200
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunks.append(line[6:])

        import json
        events = [json.loads(c) for c in chunks if c]
        types = [e["type"] for e in events]
        assert "patient_record" in types
        pr_event = next(e for e in events if e["type"] == "patient_record")
        assert pr_event["data"]["patient_id"] == 42
        assert pr_event["data"]["run_id"] == 7
