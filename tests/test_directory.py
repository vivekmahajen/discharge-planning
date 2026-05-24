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
