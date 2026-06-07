"""Tests for the Live Post-Acute Provider Directory feature."""
import pytest
from unittest.mock import patch
import datetime


# ─── No-DB path tests (no mocking needed — DATABASE_URL is None in test env) ──

class TestDirectorySearchNoDb:
    async def test_search_no_db_returns_gracefully(self, authed_client):
        """When DATABASE_URL is None, search returns empty results, not an error."""
        r = await authed_client.get("/api/directory/search?zip=94103")
        assert r.status_code == 200
        data = r.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_search_invalid_zip_returns_400_when_db_available(self, db_authed_client, monkeypatch):
        """Invalid ZIP returns 400 when DB is available."""
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        r = await db_authed_client.get("/api/directory/search?zip=abc")
        assert r.status_code == 400
        assert "ZIP" in r.json()["error"]

    async def test_search_short_zip_returns_400(self, db_authed_client, monkeypatch):
        """A 4-digit ZIP returns 400."""
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        r = await db_authed_client.get("/api/directory/search?zip=1234")
        assert r.status_code == 400

    async def test_search_unauthenticated_returns_401(self, client):
        r = await client.get("/api/directory/search?zip=94103")
        assert r.status_code == 401


class TestFacilityDetailNoDb:
    async def test_facility_detail_no_db_returns_503(self, authed_client):
        r = await authed_client.get("/api/directory/facility/123456")
        assert r.status_code == 503

    async def test_facility_detail_unauthenticated_returns_401(self, client):
        r = await client.get("/api/directory/facility/123456")
        assert r.status_code == 401


class TestSyncStatusNoDb:
    async def test_sync_status_no_db_returns_gracefully(self, authed_client):
        r = await authed_client.get("/api/directory/sync-status")
        assert r.status_code == 200
        data = r.json()
        assert data["last_sync"] is None
        assert data["total_active_facilities"] == 0

    async def test_sync_status_unauthenticated_returns_401(self, client):
        r = await client.get("/api/directory/sync-status")
        assert r.status_code == 401


class TestCountySummaryNoDb:
    async def test_county_summary_no_db_returns_empty(self, authed_client):
        r = await authed_client.get("/api/directory/county-summary")
        assert r.status_code == 200
        data = r.json()
        assert data["counties"] == []

    async def test_county_summary_unauthenticated_returns_401(self, client):
        r = await client.get("/api/directory/county-summary")
        assert r.status_code == 401


class TestSyncTriggerNoDb:
    async def test_sync_trigger_no_db_returns_503(self, authed_client):
        r = await authed_client.post("/api/directory/sync")
        assert r.status_code == 503

    async def test_sync_trigger_unauthenticated_returns_401(self, client):
        r = await client.post("/api/directory/sync")
        assert r.status_code == 401


class TestDirectoryPageRoute:
    async def test_directory_page_unauthenticated_redirects(self, client):
        r = await client.get("/post-acute-directory", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    async def test_directory_page_authenticated_returns_200(self, authed_client):
        r = await authed_client.get("/post-acute-directory")
        assert r.status_code == 200
        assert "Directory" in r.text or "directory" in r.text.lower()

    async def test_directory_page_contains_search_ui(self, authed_client):
        r = await authed_client.get("/post-acute-directory")
        assert r.status_code == 200
        # Should have a ZIP input
        assert "zipInput" in r.text or "zip" in r.text.lower()


# ─── DB path tests (monkeypatch DATABASE_URL + _DIRECTORY_DB_AVAILABLE) ───────

FAKE_FACILITY = {
    "id": 1,
    "ccn": "055123",
    "cdph_facid": "123456",
    "name": "Test Skilled Nursing",
    "facility_type": "SNF",
    "address": "100 Main St",
    "city": "San Francisco",
    "county": "San Francisco",
    "state": "CA",
    "zip": "94103",
    "phone": "(415) 555-0100",
    "latitude": 37.7726,
    "longitude": -122.4099,
    "overall_rating": 4,
    "health_inspection_rating": 4,
    "staffing_rating": 4,
    "quality_measures_rating": 4,
    "total_beds": 100,
    "certified_beds": 99,
    "average_daily_census": 85.0,
    "ownership_type": "For-Profit Corporation",
    "medicare_certified": True,
    "medicaid_certified": True,
    "accepts_medi_cal": True,
    "is_special_focus": False,
    "is_special_focus_candidate": False,
    "abuse_icon": False,
    "total_fines_dollars": 5000.0,
    "number_of_fines": 1,
    "total_penalties": 2,
    "licensed_snf_beds": 99,
    "licensed_icf_beds": 0,
    "licensed_alf_beds": 0,
    "licensed_total_beds": 99,
    "data_source": "CMS",
    "last_synced_at": "2026-01-01T00:00:00+00:00",
    "is_active": True,
    "created_at": "2026-01-01T00:00:00+00:00",
    "updated_at": "2026-01-01T00:00:00+00:00",
    "distance_miles": 0.5,
    "star_display": "★★★★☆",
    "quality_flag": None,
}

FAKE_SYNC_STATUS = {
    "last_sync": {
        "id": 1,
        "sync_type": "startup",
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": "2026-01-01T00:05:00+00:00",
        "facilities_upserted": 1200,
        "facilities_deactivated": 0,
        "status": "success",
        "error_message": None,
    },
    "total_active_facilities": 1200,
    "data_freshness_hours": 2.5,
}


class TestDirectorySearchWithDb:
    async def test_search_with_mock_db_returns_results(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with (
            patch("db.directory.search_facilities", return_value=[FAKE_FACILITY]),
            patch("db.directory.get_sync_status", return_value=FAKE_SYNC_STATUS),
        ):
            r = await db_authed_client.get("/api/directory/search?zip=94103")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["results"][0]["name"] == "Test Skilled Nursing"
        assert data["zip"] == "94103"

    async def test_search_no_results_returns_empty_list(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with (
            patch("db.directory.search_facilities", return_value=[]),
            patch("db.directory.get_sync_status", return_value=FAKE_SYNC_STATUS),
        ):
            r = await db_authed_client.get("/api/directory/search?zip=90210")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["results"] == []

    async def test_search_db_error_returns_500(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with patch("db.directory.search_facilities", side_effect=Exception("DB error")):
            r = await db_authed_client.get("/api/directory/search?zip=94103")
        assert r.status_code == 500
        assert "error" in r.json()

    async def test_search_radius_clamped(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with (
            patch("db.directory.search_facilities", return_value=[]) as mock_sf,
            patch("db.directory.get_sync_status", return_value=FAKE_SYNC_STATUS),
        ):
            # Radius 200 should be clamped to 100
            r = await db_authed_client.get("/api/directory/search?zip=94103&radius=200")
        assert r.status_code == 200
        call_args = mock_sf.call_args
        assert call_args[0][1] == 100.0  # radius clamped

    async def test_search_with_filters(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with (
            patch("db.directory.search_facilities", return_value=[FAKE_FACILITY]) as mock_sf,
            patch("db.directory.get_sync_status", return_value=FAKE_SYNC_STATUS),
        ):
            r = await db_authed_client.get(
                "/api/directory/search?zip=94103&min_rating=4&medi_cal=true&medicare=true&exclude_sff=true"
            )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1


class TestFacilityDetailWithDb:
    async def test_facility_detail_found(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        # Make a copy without distance/star fields (those are search-only)
        facility_data = {k: v for k, v in FAKE_FACILITY.items()
                        if k not in ("distance_miles", "star_display", "quality_flag")}
        with patch("db.directory.get_facility_by_ccn", return_value=facility_data):
            r = await db_authed_client.get("/api/directory/facility/055123")
        assert r.status_code == 200
        data = r.json()
        assert data["facility"]["ccn"] == "055123"
        assert data["facility"]["name"] == "Test Skilled Nursing"

    async def test_facility_detail_not_found_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with patch("db.directory.get_facility_by_ccn", return_value=None):
            r = await db_authed_client.get("/api/directory/facility/999999")
        assert r.status_code == 404

    async def test_facility_detail_db_error_returns_500(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with patch("db.directory.get_facility_by_ccn", side_effect=Exception("DB error")):
            r = await db_authed_client.get("/api/directory/facility/055123")
        assert r.status_code == 500


class TestCountySummaryWithDb:
    async def test_county_summary_with_data(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        fake_counties = [
            {"county": "Los Angeles", "total_facilities": 100, "avg_rating": 3.5,
             "total_beds": 8000, "medi_cal_count": 90},
            {"county": "San Francisco", "total_facilities": 20, "avg_rating": 4.1,
             "total_beds": 1500, "medi_cal_count": 18},
        ]
        with patch("db.directory.get_county_summary", return_value=fake_counties):
            r = await db_authed_client.get("/api/directory/county-summary")
        assert r.status_code == 200
        data = r.json()
        assert len(data["counties"]) == 2
        assert data["counties"][0]["county"] == "Los Angeles"

    async def test_county_summary_db_error_returns_gracefully(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with patch("db.directory.get_county_summary", side_effect=Exception("DB error")):
            r = await db_authed_client.get("/api/directory/county-summary")
        assert r.status_code == 200
        data = r.json()
        assert data["counties"] == []
        assert "error" in data


class TestSyncStatusWithDb:
    async def test_sync_status_with_data(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with patch("db.directory.get_sync_status", return_value=FAKE_SYNC_STATUS):
            r = await db_authed_client.get("/api/directory/sync-status")
        assert r.status_code == 200
        data = r.json()
        assert data["total_active_facilities"] == 1200

    async def test_sync_status_db_error_returns_gracefully(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        with patch("db.directory.get_sync_status", side_effect=Exception("DB error")):
            r = await db_authed_client.get("/api/directory/sync-status")
        assert r.status_code == 200
        data = r.json()
        assert data["total_active_facilities"] == 0


class TestSyncTriggerWithDb:
    async def test_sync_trigger_recent_sync_skips(self, db_authed_client, monkeypatch):
        """If data is fresh (<1h), sync trigger returns no-refresh-needed."""
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        fresh_status = dict(FAKE_SYNC_STATUS, data_freshness_hours=0.3)
        with patch("db.directory.get_sync_status", return_value=fresh_status):
            r = await db_authed_client.post("/api/directory/sync")
        assert r.status_code == 200
        data = r.json()
        assert "no refresh needed" in data["message"].lower() or "recently" in data["message"].lower()

    async def test_sync_trigger_stale_starts_sync(self, db_authed_client, monkeypatch):
        """If data is stale (>1h), sync trigger returns sync started message."""
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        stale_status = dict(FAKE_SYNC_STATUS, data_freshness_hours=5.0)

        # Mock run_full_sync to be a no-op so the background thread completes quickly
        with (
            patch("db.directory.get_sync_status", return_value=stale_status),
            patch("db.directory.start_sync_log", return_value=42),
            patch("services.directory_sync.run_full_sync", return_value={"status": "success"}),
        ):
            r = await db_authed_client.post("/api/directory/sync")
        assert r.status_code == 200
        data = r.json()
        assert "sync_id" in data or "message" in data


# ─── Batch upsert + ZIP-centroid + sync execution (serverless-safe) ───────────

class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.executed = []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None): self.executed.append((sql, params))
    def fetchall(self): return self._rows
    def fetchone(self): return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, rows=None):
        self._cur = _FakeCursor(rows)
        self.closed = False
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return self._cur
    def close(self): self.closed = True
    def commit(self): pass


class TestBatchUpsert:
    def test_upsert_facilities_batches_and_closes(self, monkeypatch):
        import db.directory as d
        conn = _FakeConn()
        monkeypatch.setattr(d, "get_db_conn", lambda: conn)
        captured = {}

        def fake_ev(cur, sql, rows, template=None, page_size=None):
            captured["sql"] = sql
            captured["rows"] = list(rows)
            captured["template"] = template

        monkeypatch.setattr("psycopg2.extras.execute_values", fake_ev)
        facs = [
            {"ccn": "055123", "name": "A", "zip": "94103", "latitude": 1.0, "longitude": 2.0},
            {"ccn": "055124", "name": "B"},
            {"name": "no ccn — skipped"},
        ]
        n = d.upsert_facilities(facs)
        assert n == 2
        assert conn.closed is True
        assert "INSERT INTO facilities" in captured["sql"]
        assert "ON CONFLICT (ccn) DO UPDATE" in captured["sql"]
        assert len(captured["rows"]) == 2
        # template carries the three trailing NOW()/TRUE/NOW() literals
        assert captured["template"].endswith("NOW(), TRUE, NOW())")

    def test_upsert_facilities_empty_returns_zero(self, monkeypatch):
        import db.directory as d
        monkeypatch.setattr(d, "get_db_conn", lambda: (_ for _ in ()).throw(AssertionError("should not connect")))
        assert d.upsert_facilities([]) == 0

    def test_get_all_zip_coords_skips_bad_rows(self, monkeypatch):
        import db.directory as d
        conn = _FakeConn(rows=[
            {"zip": "94103", "latitude": 37.7, "longitude": -122.4},
            {"zip": "90001", "latitude": 33.9, "longitude": -118.2},
            {"zip": "bad", "latitude": None, "longitude": None},
        ])
        monkeypatch.setattr(d, "get_db_conn", lambda: conn)
        out = d.get_all_zip_coords()
        assert out["94103"] == (37.7, -122.4)
        assert "bad" not in out
        assert conn.closed is True


class TestRunFullSync:
    def test_cms_only_assigns_zip_centroids(self, monkeypatch):
        import services.directory_sync as ds
        cms = [
            {"ccn": "055123", "name": "A", "zip": "94103", "latitude": None, "longitude": None},
            {"ccn": "055124", "name": "B", "zip": "90001", "latitude": None, "longitude": None},
            {"ccn": "055125", "name": "C", "zip": "99999", "latitude": None, "longitude": None},
        ]
        monkeypatch.setattr(ds, "fetch_cms_ca_facilities", lambda: [dict(x) for x in cms])
        monkeypatch.setattr("db.directory.seed_zip_coordinates", lambda p: 0)
        monkeypatch.setattr("db.directory.get_all_zip_coords",
                            lambda: {"94103": (37.7, -122.4), "90001": (33.9, -118.2)})
        captured = {}

        def fake_upsert(facs, batch_size=500):
            captured["facs"] = facs
            return len([f for f in facs if f.get("ccn")])

        monkeypatch.setattr("db.directory.upsert_facilities", fake_upsert)
        monkeypatch.setattr("db.directory.deactivate_missing_facilities", lambda ccns: 0)
        monkeypatch.setattr("db.directory.start_sync_log", lambda t: 1)
        monkeypatch.setattr("db.directory.finish_sync_log", lambda *a, **k: None)
        # CDPH should NOT be fetched when the flag is off
        monkeypatch.delenv("DIRECTORY_ENABLE_CDPH", raising=False)
        monkeypatch.setattr(ds, "fetch_cdph_ca_facilities",
                            lambda: (_ for _ in ()).throw(AssertionError("CDPH must not be fetched")))

        res = ds.run_full_sync("test")
        assert res["status"] == "success"
        assert res["upserted"] == 3
        by_ccn = {f["ccn"]: f for f in captured["facs"]}
        assert by_ccn["055123"]["latitude"] == 37.7
        assert by_ccn["055124"]["longitude"] == -118.2
        # No centroid for 99999 — stays None (won't appear in distance search)
        assert by_ccn["055125"]["latitude"] is None

    def test_cdph_failure_is_non_fatal(self, monkeypatch):
        import services.directory_sync as ds
        monkeypatch.setattr(ds, "fetch_cms_ca_facilities",
                            lambda: [{"ccn": "055123", "name": "A", "zip": "94103",
                                      "latitude": None, "longitude": None}])
        monkeypatch.setattr("db.directory.seed_zip_coordinates", lambda p: 0)
        monkeypatch.setattr("db.directory.get_all_zip_coords", lambda: {"94103": (37.7, -122.4)})
        monkeypatch.setattr("db.directory.upsert_facilities", lambda facs, batch_size=500: len(facs))
        monkeypatch.setattr("db.directory.deactivate_missing_facilities", lambda ccns: 0)
        monkeypatch.setattr("db.directory.start_sync_log", lambda t: 1)
        monkeypatch.setattr("db.directory.finish_sync_log", lambda *a, **k: None)
        monkeypatch.setenv("DIRECTORY_ENABLE_CDPH", "1")
        monkeypatch.setattr(ds, "fetch_cdph_ca_facilities",
                            lambda: (_ for _ in ()).throw(RuntimeError("CHHS down")))
        res = ds.run_full_sync("test")
        assert res["status"] == "success"
        assert res["upserted"] == 1


class TestCronSync:
    async def test_cron_sync_no_db_returns_503(self, client):
        r = await client.get("/api/directory/cron-sync")
        assert r.status_code == 503

    async def test_cron_sync_requires_secret_when_set(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        monkeypatch.setenv("CRON_SECRET", "topsecret")
        r = await db_authed_client.get("/api/directory/cron-sync")
        assert r.status_code == 401

    async def test_cron_sync_fresh_skips(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        monkeypatch.setenv("CRON_SECRET", "s3")
        fresh = dict(FAKE_SYNC_STATUS, data_freshness_hours=2.0, total_active_facilities=1200)
        with patch("db.directory.get_sync_status", return_value=fresh):
            r = await db_authed_client.get(
                "/api/directory/cron-sync", headers={"Authorization": "Bearer s3"})
        assert r.status_code == 200
        assert r.json()["message"] == "fresh"

    async def test_cron_sync_stale_runs(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        monkeypatch.delenv("CRON_SECRET", raising=False)
        stale = dict(FAKE_SYNC_STATUS, data_freshness_hours=48.0, total_active_facilities=0)
        with (
            patch("db.directory.get_sync_status", return_value=stale),
            patch("services.directory_sync.run_full_sync",
                  return_value={"status": "success", "upserted": 1200, "deactivated": 0,
                                "duration_seconds": 3.0}),
        ):
            r = await db_authed_client.get("/api/directory/cron-sync")
        assert r.status_code == 200
        data = r.json()
        assert data["message"] == "sync complete"
        assert data["upserted"] == 1200


class TestManualSyncSynchronous:
    async def test_manual_sync_runs_inline_and_reports_count(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_DIRECTORY_DB_AVAILABLE", True)
        stale = dict(FAKE_SYNC_STATUS, data_freshness_hours=5.0)
        with (
            patch("db.directory.get_sync_status", return_value=stale),
            patch("services.directory_sync.run_full_sync",
                  return_value={"status": "success", "upserted": 1200, "deactivated": 2,
                                "duration_seconds": 3.0}),
        ):
            r = await db_authed_client.post("/api/directory/sync")
        assert r.status_code == 200
        data = r.json()
        assert data["message"] == "Sync complete"
        assert data["upserted"] == 1200


# ─── CMS fetch: WAF-resilient request + error surfacing ──────────────────────

class TestCmsFetch:
    def _client_factory(self, handler):
        import httpx
        original_client = httpx.Client  # capture before monkeypatch replaces it

        def factory(*args, **kwargs):
            kwargs.pop("transport", None)
            return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

        return factory

    def test_post_blocked_falls_back_to_get(self, monkeypatch):
        import httpx
        import services.directory_sync as ds

        def handler(request):
            if request.method == "POST":
                return httpx.Response(403, text="Forbidden")
            return httpx.Response(200, json={"results": [{
                "cms_certification_number_ccn": "055123",
                "provider_name": "Test SNF",
                "provider_state": "CA",
                "provider_zip_code": "94103",
            }]})

        monkeypatch.setattr(ds.httpx, "Client", self._client_factory(handler))
        monkeypatch.setattr(ds.time, "sleep", lambda *_a: None)
        facs = ds.fetch_cms_ca_facilities()
        assert len(facs) == 1
        assert facs[0]["ccn"] == "055123"

    def test_total_failure_raises_with_reason(self, monkeypatch):
        import httpx
        import services.directory_sync as ds

        def handler(request):
            return httpx.Response(403, text="Forbidden")

        monkeypatch.setattr(ds.httpx, "Client", self._client_factory(handler))
        monkeypatch.setattr(ds.time, "sleep", lambda *_a: None)
        with pytest.raises(RuntimeError, match="CMS API request failed"):
            ds.fetch_cms_ca_facilities()

    def test_run_full_sync_reports_error_when_cms_unreachable(self, monkeypatch):
        import services.directory_sync as ds
        monkeypatch.setattr(ds, "fetch_cms_ca_facilities",
                            lambda: (_ for _ in ()).throw(RuntimeError("CMS API request failed: 403")))
        monkeypatch.setattr("db.directory.start_sync_log", lambda t: 1)
        captured = {}
        monkeypatch.setattr("db.directory.finish_sync_log",
                            lambda log_id, up, deact, status, error=None: captured.update(status=status, error=error))
        res = ds.run_full_sync("test")
        assert res["status"] == "error"
        assert "CMS API request failed" in res["error"]
        assert captured["status"] == "error"


# ─── Diagnostic probe endpoint ───────────────────────────────────────────────

class TestDebugFetch:
    def test_debug_cms_fetch_reports_statuses(self, monkeypatch):
        import httpx
        import services.directory_sync as ds
        original = httpx.Client

        def handler(request):
            if "api.github.com" in str(request.url):
                return httpx.Response(200, json={"ok": True})
            if request.method == "POST":
                return httpx.Response(403, text="Forbidden")
            return httpx.Response(200, json={"results": [{"x": 1}]})

        def factory(*a, **k):
            k.pop("transport", None)
            return original(*a, transport=httpx.MockTransport(handler), **k)

        monkeypatch.setattr(ds.httpx, "Client", factory)
        out = ds.debug_cms_fetch()
        assert out["cms_post"]["status"] == 403
        assert out["cms_get"]["status"] == 200
        assert out["egress_control"]["status"] == 200

    def test_debug_cms_fetch_captures_exceptions(self, monkeypatch):
        import httpx
        import services.directory_sync as ds
        original = httpx.Client

        def handler(request):
            raise httpx.ConnectTimeout("connection timed out")

        def factory(*a, **k):
            k.pop("transport", None)
            return original(*a, transport=httpx.MockTransport(handler), **k)

        monkeypatch.setattr(ds.httpx, "Client", factory)
        out = ds.debug_cms_fetch()
        assert out["cms_post"]["ok"] is False
        assert "ConnectTimeout" in out["cms_post"]["error"]

    async def test_debug_endpoint_requires_auth(self, client):
        r = await client.get("/api/directory/debug-fetch")
        assert r.status_code == 401

    async def test_debug_endpoint_returns_probe(self, authed_client):
        fake = {
            "cms_api": "https://x",
            "cms_post": {"ok": False, "error": "ConnectTimeout: timed out"},
            "cms_get": {"ok": False, "error": "ConnectTimeout: timed out"},
            "egress_control": {"ok": True, "status": 200},
        }
        with patch("services.directory_sync.debug_cms_fetch", return_value=fake):
            r = await authed_client.get("/api/directory/debug-fetch")
        assert r.status_code == 200
        assert r.json()["egress_control"]["status"] == 200
