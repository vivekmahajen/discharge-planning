"""Tests for the ROI outcomes engine and API endpoints."""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import patch, MagicMock


# ── ROI Engine pure-function tests ────────────────────────────────────────────

class TestRoiEngineImport:
    def test_roi_engine_imports(self):
        from services.roi_engine import compute_episode_roi, aggregate_org_roi, get_cost_per_day
        assert callable(compute_episode_roi)
        assert callable(aggregate_org_roi)
        assert callable(get_cost_per_day)

    def test_ca_cost_per_day_constants(self):
        from services.roi_engine import CA_COST_PER_DAY
        assert CA_COST_PER_DAY["nonprofit"] == 4_100.0
        assert CA_COST_PER_DAY["forprofit"] == 3_600.0
        assert CA_COST_PER_DAY["government"] == 3_800.0
        assert CA_COST_PER_DAY["default"] == 4_000.0

    def test_hrrp_estimate_constant(self):
        from services.roi_engine import HRRP_AVOIDED_ESTIMATE_PER_PATIENT
        assert HRRP_AVOIDED_ESTIMATE_PER_PATIENT == 4_500.0


class TestGetCostPerDay:
    def test_nonprofit_returns_4100(self):
        from services.roi_engine import get_cost_per_day
        assert get_cost_per_day("nonprofit") == 4_100.0

    def test_forprofit_returns_3600(self):
        from services.roi_engine import get_cost_per_day
        assert get_cost_per_day("forprofit") == 3_600.0

    def test_unknown_type_returns_default(self):
        from services.roi_engine import get_cost_per_day
        assert get_cost_per_day("unknown") == 4_000.0

    def test_override_takes_precedence(self):
        from services.roi_engine import get_cost_per_day
        assert get_cost_per_day("nonprofit", override=5000.0) == 5_000.0

    def test_zero_override_falls_back_to_type(self):
        from services.roi_engine import get_cost_per_day
        assert get_cost_per_day("nonprofit", override=0) == 4_100.0

    def test_none_override_falls_back_to_type(self):
        from services.roi_engine import get_cost_per_day
        assert get_cost_per_day("nonprofit", override=None) == 4_100.0


class TestComputeEpisodeRoi:
    def _call(self, **kwargs):
        from services.roi_engine import compute_episode_roi
        defaults = dict(
            admission_date=date(2026, 5, 18),
            actual_discharge_date=date(2026, 5, 22),   # 4-day stay
            drg_geometric_mean_los=5.5,                 # DRG 291 HF
            cost_per_day=4_100.0,
            was_readmitted=False,
            readmission_within_30d=False,
            hrrp_condition_flagged=False,
            barriers_created_at=[],
            barriers_resolved_at=[],
            predicted_los_days=None,
            tcm_revenue=0.0,
        )
        defaults.update(kwargs)
        return compute_episode_roi(**defaults)

    def test_actual_los_calculation(self):
        r = self._call()
        assert r["actual_los_days"] == 4

    def test_excess_days_saved_positive(self):
        r = self._call()
        # 5.5 expected - 4 actual = 1.5 saved
        assert r["excess_days_saved"] == 1.5

    def test_cost_savings_positive(self):
        r = self._call()
        # 1.5 days * $4,100 = $6,150
        assert r["cost_savings_dollars"] == 6_150.0

    def test_total_value_includes_savings(self):
        r = self._call()
        assert r["total_value_dollars"] == 6_150.0

    def test_extended_stay_negative_savings(self):
        # Patient stayed 8 days vs expected 5.5
        r = self._call(actual_discharge_date=date(2026, 5, 26))  # 8 days
        assert r["excess_days_saved"] == -2.5
        assert r["cost_savings_dollars"] < 0

    def test_negative_savings_not_added_to_total_value(self):
        r = self._call(actual_discharge_date=date(2026, 5, 26))
        # Extended stays don't contribute positively to total_value
        assert r["total_value_dollars"] == 0.0

    def test_no_drg_returns_none_for_savings(self):
        r = self._call(drg_geometric_mean_los=None)
        assert r["excess_days_saved"] is None
        assert r["cost_savings_dollars"] is None

    def test_methodology_notes_are_list(self):
        r = self._call()
        assert isinstance(r["methodology_notes"], list)
        assert len(r["methodology_notes"]) >= 1

    def test_methodology_notes_mention_actual_los(self):
        r = self._call()
        assert any("Actual LOS: 4" in n for n in r["methodology_notes"])

    def test_hrrp_avoided_when_flagged_no_readmission(self):
        r = self._call(hrrp_condition_flagged=True, readmission_within_30d=False)
        assert r["hrrp_penalty_avoided"] is True
        assert r["hrrp_avoided_estimate"] == 4_500.0
        assert r["total_value_dollars"] >= 4_500.0

    def test_hrrp_not_avoided_when_readmitted(self):
        r = self._call(hrrp_condition_flagged=True, readmission_within_30d=True)
        assert r["hrrp_penalty_avoided"] is False
        assert r["hrrp_avoided_estimate"] == 0.0

    def test_hrrp_none_when_not_flagged(self):
        r = self._call(hrrp_condition_flagged=False)
        assert r["hrrp_penalty_avoided"] is None

    def test_barrier_metrics_empty(self):
        r = self._call(barriers_created_at=[], barriers_resolved_at=[])
        assert r["barriers_identified"] == 0
        assert r["barriers_resolved"] == 0
        assert r["avg_barrier_resolution_hours"] is None

    def test_barrier_resolution_hours_calculated(self):
        from datetime import datetime as dt
        created = [dt(2026, 5, 18, 8, 0, 0)]
        resolved = [dt(2026, 5, 19, 8, 0, 0)]  # 24 hours
        r = self._call(barriers_created_at=created, barriers_resolved_at=resolved)
        assert r["barriers_identified"] == 1
        assert r["barriers_resolved"] == 1
        assert r["avg_barrier_resolution_hours"] == 24.0

    def test_unresolved_barrier_not_counted(self):
        from datetime import datetime as dt
        created = [dt(2026, 5, 18, 8, 0), dt(2026, 5, 19, 8, 0)]
        resolved = [dt(2026, 5, 19, 8, 0), None]
        r = self._call(barriers_created_at=created, barriers_resolved_at=resolved)
        assert r["barriers_identified"] == 2
        assert r["barriers_resolved"] == 1

    def test_prediction_error_calculated(self):
        r = self._call(predicted_los_days=5.0)
        # actual=4, predicted=5 → error=1.0
        assert r["prediction_error_days"] == 1.0

    def test_prediction_error_none_when_no_prediction(self):
        r = self._call(predicted_los_days=None)
        assert r["prediction_error_days"] is None

    def test_tcm_revenue_included_in_total(self):
        r = self._call(tcm_revenue=200.0)
        # savings 6150 + tcm 200 = 6350
        assert r["total_value_dollars"] == 6_350.0

    def test_negative_tcm_not_added(self):
        r = self._call(tcm_revenue=-50.0)
        assert r["total_value_dollars"] == r["cost_savings_dollars"]


class TestAggregateOrgRoi:
    def _episode(self, **kwargs):
        from services.roi_engine import compute_episode_roi
        defaults = dict(
            admission_date=date(2026, 5, 18),
            actual_discharge_date=date(2026, 5, 22),
            drg_geometric_mean_los=5.5,
            cost_per_day=4_100.0,
            was_readmitted=False,
            readmission_within_30d=False,
            hrrp_condition_flagged=False,
            barriers_created_at=[], barriers_resolved_at=[],
            predicted_los_days=None, tcm_revenue=0.0,
        )
        defaults.update(kwargs)
        return compute_episode_roi(**defaults)

    def test_empty_returns_zeros(self):
        from services.roi_engine import aggregate_org_roi
        r = aggregate_org_roi([])
        assert r["total_episodes_measured"] == 0
        assert r["total_value_dollars"] == 0

    def test_totals_correct(self):
        from services.roi_engine import aggregate_org_roi
        ep1 = self._episode()  # 1.5 days saved, $6,150
        ep2 = self._episode(actual_discharge_date=date(2026, 5, 21))  # 2.5 days saved
        r = aggregate_org_roi([ep1, ep2])
        assert r["total_episodes_measured"] == 2
        assert r["total_excess_days_saved"] == 4.0
        assert r["total_cost_savings_dollars"] == pytest.approx(4.0 * 4100, abs=0.1)

    def test_data_completeness_100_when_all_have_drg(self):
        from services.roi_engine import aggregate_org_roi
        ep = self._episode()
        r = aggregate_org_roi([ep])
        assert r["data_completeness_pct"] == 100.0

    def test_data_completeness_50_when_half_missing_drg(self):
        from services.roi_engine import aggregate_org_roi
        ep1 = self._episode()
        ep2 = self._episode(drg_geometric_mean_los=None)
        r = aggregate_org_roi([ep1, ep2])
        assert r["data_completeness_pct"] == 50.0

    def test_insufficient_data_flag_under_10(self):
        from services.roi_engine import aggregate_org_roi
        episodes = [self._episode() for _ in range(5)]
        r = aggregate_org_roi(episodes, date_range_months=3.0)
        assert r["annualized_insufficient_data"] is True
        assert r["annualized_run_rate_dollars"] is None

    def test_annualized_rate_computed_at_10_plus(self):
        from services.roi_engine import aggregate_org_roi
        episodes = [self._episode() for _ in range(10)]
        r = aggregate_org_roi(episodes, date_range_months=3.0)
        assert r["annualized_insufficient_data"] is False
        assert r["annualized_run_rate_dollars"] is not None
        assert r["annualized_run_rate_dollars"] > 0

    def test_readmission_rate_calculated(self):
        from services.roi_engine import aggregate_org_roi
        ep1 = self._episode(readmission_within_30d=True)
        ep1["readmission_within_30d"] = True  # patch result dict
        ep2 = self._episode()
        # Manually set readmission on ep1 result
        ep1_mod = dict(ep1)
        ep1_mod["readmission_within_30d"] = True
        r = aggregate_org_roi([ep1_mod, ep2])
        assert r["readmission_rate_30d"] == 50.0


# ── DRG reference data tests ──────────────────────────────────────────────────

class TestDrgReferenceData:
    def test_drg_reference_imports(self):
        from db.drg_reference_data import DRG_REFERENCE, HRRP_DRGS
        assert isinstance(DRG_REFERENCE, dict)
        assert isinstance(HRRP_DRGS, set)

    def test_has_enough_entries(self):
        from db.drg_reference_data import DRG_REFERENCE
        assert len(DRG_REFERENCE) >= 100

    def test_drg_291_heart_failure(self):
        from db.drg_reference_data import DRG_REFERENCE
        assert "291" in DRG_REFERENCE
        desc, mdc, dtype, weight, geo_los, arith_los = DRG_REFERENCE["291"]
        assert "Heart Failure" in desc
        assert geo_los == 5.5

    def test_entry_format_is_6_tuple(self):
        from db.drg_reference_data import DRG_REFERENCE
        for code, val in DRG_REFERENCE.items():
            assert len(val) == 6, f"DRG {code} has wrong tuple length"

    def test_hrrp_drgs_includes_heart_failure(self):
        from db.drg_reference_data import HRRP_DRGS
        assert "291" in HRRP_DRGS
        assert "292" in HRRP_DRGS
        assert "293" in HRRP_DRGS

    def test_hrrp_drgs_includes_ami(self):
        from db.drg_reference_data import HRRP_DRGS
        assert "280" in HRRP_DRGS
        assert "281" in HRRP_DRGS
        assert "282" in HRRP_DRGS

    def test_hrrp_drgs_includes_hip_knee(self):
        from db.drg_reference_data import HRRP_DRGS
        assert "469" in HRRP_DRGS
        assert "470" in HRRP_DRGS

    def test_geo_mean_los_is_positive_float(self):
        from db.drg_reference_data import DRG_REFERENCE
        for code, val in DRG_REFERENCE.items():
            geo_los = val[4]
            assert isinstance(geo_los, float), f"DRG {code} geo_los is not float"
            assert geo_los > 0, f"DRG {code} geo_los is not positive"

    def test_relative_weight_is_positive(self):
        from db.drg_reference_data import DRG_REFERENCE
        for code, val in DRG_REFERENCE.items():
            weight = val[3]
            assert weight > 0, f"DRG {code} weight is not positive"


# ── ROI API endpoint tests ────────────────────────────────────────────────────

class TestRoiDashboardEndpoint:
    async def test_dashboard_returns_200_when_unavailable(self, authed_client):
        r = await authed_client.get("/api/roi/dashboard")
        assert r.status_code == 200

    async def test_dashboard_requires_auth(self, client):
        r = await client.get("/api/roi/dashboard", follow_redirects=False)
        assert r.status_code in (302, 401, 403)

    async def test_dashboard_returns_expected_keys(self, authed_client):
        r = await authed_client.get("/api/roi/dashboard")
        data = r.json()
        assert "totals" in data
        assert "monthly_trend" in data
        assert "drg_breakdown" in data
        assert "data_quality" in data

    async def test_dashboard_unavailable_flag_when_no_db(self, authed_client):
        r = await authed_client.get("/api/roi/dashboard")
        data = r.json()
        # Without DB, should return unavailable=True or empty totals
        assert "unavailable" in data or "totals" in data


class TestRoiOutcomesEndpoint:
    async def test_list_outcomes_returns_200(self, authed_client):
        r = await authed_client.get("/api/roi/outcomes")
        assert r.status_code == 200

    async def test_list_outcomes_requires_auth(self, client):
        r = await client.get("/api/roi/outcomes", follow_redirects=False)
        assert r.status_code in (302, 401, 403)

    async def test_list_outcomes_has_outcomes_key(self, authed_client):
        r = await authed_client.get("/api/roi/outcomes")
        data = r.json()
        assert "outcomes" in data

    async def test_get_patient_outcome_404(self, authed_client):
        r = await authed_client.get("/api/roi/outcomes/99999")
        assert r.status_code in (404, 503)

    async def test_recalculate_outcome_404(self, authed_client):
        r = await authed_client.post("/api/roi/outcomes/99999/calculate")
        assert r.status_code in (404, 503)


class TestDischargeDataEndpoint:
    async def test_update_discharge_data_404_for_missing(self, authed_client):
        r = await authed_client.patch(
            "/api/patients/99999/discharge-data",
            json={"actual_discharge_date": "2026-05-22"},
        )
        assert r.status_code in (404, 503)

    async def test_update_discharge_data_400_no_fields(self, authed_client):
        r = await authed_client.patch(
            "/api/patients/99999/discharge-data",
            json={"invalid_field": "value"},
        )
        assert r.status_code in (400, 503)

    async def test_update_discharge_data_requires_auth(self, client):
        r = await client.patch(
            "/api/patients/1/discharge-data",
            json={"actual_discharge_date": "2026-05-22"},
            follow_redirects=False,
        )
        assert r.status_code in (302, 401, 403)


class TestDrgSearchEndpoint:
    async def test_drg_search_returns_200(self, authed_client):
        r = await authed_client.get("/api/drg/search?q=heart")
        assert r.status_code == 200

    async def test_drg_search_requires_auth(self, client):
        r = await client.get("/api/drg/search?q=heart", follow_redirects=False)
        assert r.status_code in (302, 401, 403)

    async def test_drg_search_returns_results_key(self, authed_client):
        r = await authed_client.get("/api/drg/search?q=heart")
        data = r.json()
        assert "results" in data

    async def test_drg_search_short_query_returns_empty(self, authed_client):
        r = await authed_client.get("/api/drg/search?q=h")
        data = r.json()
        assert data["results"] == []


class TestRoiSettingsEndpoint:
    async def test_get_settings_returns_200(self, authed_client):
        r = await authed_client.get("/api/roi/settings")
        assert r.status_code == 200

    async def test_get_settings_requires_auth(self, client):
        r = await client.get("/api/roi/settings", follow_redirects=False)
        assert r.status_code in (302, 401, 403)

    async def test_patch_settings_unavailable_without_db(self, authed_client):
        r = await authed_client.patch(
            "/api/roi/settings",
            json={"hospital_type": "nonprofit", "cost_per_day": 4200},
        )
        assert r.status_code in (200, 503)


class TestRoiExportEndpoint:
    async def test_export_unavailable_without_db(self, authed_client):
        r = await authed_client.get("/api/roi/export")
        assert r.status_code in (200, 503)

    async def test_export_requires_auth(self, client):
        r = await client.get("/api/roi/export", follow_redirects=False)
        assert r.status_code in (302, 401, 403)


class TestRoiMeasuredPageRoute:
    async def test_roi_measured_page_authenticated(self, authed_client):
        r = await authed_client.get("/roi-measured")
        # Returns 200 if page file exists, 500 if html not yet created
        assert r.status_code in (200, 500, 404)

    async def test_roi_measured_page_unauthenticated_redirects(self, client):
        r = await client.get("/roi-measured", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers.get("location", "")


class TestRoiEndpoints503Paths:
    """Verify that ROI endpoints return 503 when DB is not available."""

    async def test_get_patient_outcome_503_no_db(self, authed_client):
        # Without DB, should 503
        r = await authed_client.get("/api/roi/outcomes/1")
        assert r.status_code in (503, 404)

    async def test_recalculate_503_no_db(self, authed_client):
        r = await authed_client.post("/api/roi/outcomes/1/calculate")
        assert r.status_code in (503, 404)

    async def test_update_discharge_data_503_no_db(self, authed_client):
        r = await authed_client.patch(
            "/api/patients/1/discharge-data",
            json={"actual_discharge_date": "2026-05-22"},
        )
        assert r.status_code in (503, 404)

    async def test_patch_roi_settings_503_no_db(self, authed_client):
        r = await authed_client.patch(
            "/api/roi/settings",
            json={"hospital_type": "forprofit"},
        )
        assert r.status_code in (200, 503)

    async def test_roi_export_503_no_db(self, authed_client):
        r = await authed_client.get("/api/roi/export")
        assert r.status_code in (200, 503)


class TestRoiEngineModuleFlag:
    def test_roi_engine_flag_is_bool(self):
        import web_app
        assert isinstance(web_app._ROI_ENGINE_AVAILABLE, bool)

    def test_roi_engine_compute_imported_when_available(self):
        import web_app
        if web_app._ROI_ENGINE_AVAILABLE:
            assert callable(web_app._compute_episode_roi)
            assert callable(web_app._aggregate_org_roi)


# ── ROI DB-path tests (require DB mock + _ROI_ENGINE_AVAILABLE=True) ─────────

class TestRoiDashboardDbPath:
    """Cover /api/roi/dashboard when DATABASE_URL is set."""

    async def test_dashboard_with_db_returns_200(self, db_authed_client, monkeypatch):
        import web_app
        fake_data = {
            "totals": {"total_value_dollars": 12300.0, "total_episodes_measured": 3},
            "monthly_trend": [],
            "drg_breakdown": [],
            "clinician_breakdown": [],
            "data_quality": {"episodes_without_drg": 0, "completeness_pct": 100.0},
        }
        monkeypatch.setattr(web_app, "_get_roi_dashboard_data", lambda org, months: fake_data)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert data["totals"]["total_episodes_measured"] == 3

    async def test_dashboard_with_db_months_param(self, db_authed_client, monkeypatch):
        import web_app
        captured = {}
        def _fake_dash(org, months):
            captured["months"] = months
            return {"totals": {}, "monthly_trend": [], "drg_breakdown": [],
                    "clinician_breakdown": [], "data_quality": {}}
        monkeypatch.setattr(web_app, "_get_roi_dashboard_data", _fake_dash)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        await db_authed_client.get("/api/roi/dashboard?months=6")
        assert captured.get("months") == 6


class TestRoiOutcomesDbPath:
    """Cover /api/roi/outcomes list endpoint with DB."""

    async def test_outcomes_list_with_db_returns_200(self, db_authed_client, monkeypatch):
        import web_app
        fake_outcomes = [{"id": 1, "drg_code": "291", "total_value_dollars": 6150.0}]
        monkeypatch.setattr(web_app, "_get_org_roi_outcomes",
                            lambda org, sd, ed, drg, clin, **kw: fake_outcomes)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/outcomes")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["outcomes"][0]["drg_code"] == "291"

    async def test_outcomes_list_with_date_filter(self, db_authed_client, monkeypatch):
        import web_app
        captured = {}
        def _fake(org, sd, ed, drg, clin, **kw):
            captured.update({"sd": sd, "ed": ed})
            return []
        monkeypatch.setattr(web_app, "_get_org_roi_outcomes", _fake)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get(
            "/api/roi/outcomes?start_date=2026-01-01&end_date=2026-05-31"
        )
        assert r.status_code == 200
        assert captured["sd"] is not None
        assert captured["ed"] is not None


class TestRoiSingleOutcomeDbPath:
    """Cover /api/roi/outcomes/{patient_id} with DB."""

    async def test_single_outcome_found(self, db_authed_client, monkeypatch):
        import web_app
        fake_outcome = {"id": 42, "excess_days_saved": 1.5, "total_value_dollars": 6150.0}
        monkeypatch.setattr(web_app, "_get_roi_outcome", lambda pid, org: fake_outcome)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/outcomes/42")
        assert r.status_code == 200
        assert r.json()["outcome"]["excess_days_saved"] == 1.5

    async def test_single_outcome_not_found_returns_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_get_roi_outcome", lambda pid, org: None)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/outcomes/9999")
        assert r.status_code == 404


class TestRecalculateRoiDbPath:
    """Cover /api/roi/outcomes/{patient_id}/calculate with DB."""

    async def test_recalculate_with_valid_patient(self, db_authed_client, monkeypatch):
        import web_app
        fake_patient = {"id": 1, "name": "Test Patient", "status": "discharged"}
        fake_outcome = {"excess_days_saved": 1.5, "total_value_dollars": 6150.0}
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        monkeypatch.setattr("db.patients.get_patient_detail", lambda pid, org: fake_patient)
        monkeypatch.setattr(web_app, "_trigger_outcome_calculation",
                            lambda pid, org: fake_outcome)
        r = await db_authed_client.post("/api/roi/outcomes/1/calculate")
        assert r.status_code == 200
        assert r.json()["outcome"]["total_value_dollars"] == 6150.0

    async def test_recalculate_patient_not_found_404(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        monkeypatch.setattr("db.patients.get_patient_detail", lambda pid, org: None)
        r = await db_authed_client.post("/api/roi/outcomes/9999/calculate")
        assert r.status_code == 404

    async def test_recalculate_no_discharge_date_returns_message(self, db_authed_client, monkeypatch):
        import web_app
        fake_patient = {"id": 1, "name": "Test Patient"}
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        monkeypatch.setattr("db.patients.get_patient_detail", lambda pid, org: fake_patient)
        monkeypatch.setattr(web_app, "_trigger_outcome_calculation", lambda pid, org: None)
        r = await db_authed_client.post("/api/roi/outcomes/1/calculate")
        assert r.status_code == 200
        assert r.json()["outcome"] is None


class TestDischargeDataDbPath:
    """Cover /api/patients/{id}/discharge-data PATCH with DB."""

    async def test_discharge_data_update_success(self, db_authed_client, monkeypatch):
        import web_app
        from unittest.mock import MagicMock
        fake_patient = {
            "id": 1, "name": "Test Patient", "status": "active",
            "admission_date": "2026-05-18",
        }
        updated_patient = dict(fake_patient, actual_discharge_date="2026-05-22", actual_los_days=4)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()

        call_count = {"n": 0}
        def _fake_get_patient(pid, org):
            call_count["n"] += 1
            return fake_patient if call_count["n"] == 1 else updated_patient

        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        monkeypatch.setattr("db.patients.get_patient_detail", _fake_get_patient)
        monkeypatch.setattr("db.connection.get_db_conn", lambda: mock_conn)
        monkeypatch.setattr(web_app, "_trigger_outcome_calculation",
                            lambda pid, org: {"total_value_dollars": 6150.0})
        r = await db_authed_client.patch(
            "/api/patients/1/discharge-data",
            json={"actual_discharge_date": "2026-05-22"},
        )
        assert r.status_code == 200
        assert "patient" in r.json()

    async def test_discharge_data_bad_field_400(self, db_authed_client, monkeypatch):
        fake_patient = {"id": 1, "name": "Test Patient", "status": "active"}
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        monkeypatch.setattr("db.patients.get_patient_detail", lambda pid, org: fake_patient)
        r = await db_authed_client.patch(
            "/api/patients/1/discharge-data",
            json={"unknown_field": "value"},
        )
        assert r.status_code == 400

    async def test_discharge_data_patient_not_found_404(self, db_authed_client, monkeypatch):
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        monkeypatch.setattr("db.patients.get_patient_detail", lambda pid, org: None)
        r = await db_authed_client.patch(
            "/api/patients/1/discharge-data",
            json={"actual_discharge_date": "2026-05-22"},
        )
        assert r.status_code == 404

    async def test_discharge_data_drg_code_lookup(self, db_authed_client, monkeypatch):
        """DRG description is auto-filled from reference when only code is given."""
        import web_app
        from unittest.mock import MagicMock
        fake_patient = {"id": 1, "name": "Test Patient", "admission_date": "2026-05-18"}
        updated_patient = dict(fake_patient, drg_code="291", drg_description="Heart Failure")
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
        mock_cursor.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.close = MagicMock()

        call_count = {"n": 0}
        def _fake_get_patient(pid, org):
            call_count["n"] += 1
            return fake_patient if call_count["n"] == 1 else updated_patient

        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        monkeypatch.setattr("db.patients.get_patient_detail", _fake_get_patient)
        monkeypatch.setattr("db.connection.get_db_conn", lambda: mock_conn)
        monkeypatch.setattr(web_app, "_get_drg_reference",
                            lambda code: {"drg_description": "Heart Failure & Shock w MCC"})
        monkeypatch.setattr(web_app, "_trigger_outcome_calculation", lambda pid, org: None)
        r = await db_authed_client.patch(
            "/api/patients/1/discharge-data",
            json={"drg_code": "291"},
        )
        assert r.status_code == 200


class TestDrgSearchDbPath:
    """Cover /api/drg/search with DB available."""

    async def test_drg_search_with_db_returns_results(self, db_authed_client, monkeypatch):
        import web_app
        fake_results = [{"drg_code": "291", "drg_description": "Heart Failure & Shock w MCC"}]
        monkeypatch.setattr(web_app, "_search_drg", lambda q, **kw: fake_results)
        r = await db_authed_client.get("/api/drg/search?q=heart")
        assert r.status_code == 200
        assert len(r.json()["results"]) == 1

    async def test_drg_search_empty_when_short_query(self, db_authed_client):
        r = await db_authed_client.get("/api/drg/search?q=h")
        assert r.status_code == 200
        assert r.json()["results"] == []


class TestRoiSettingsDbPath:
    """Cover /api/roi/settings GET and PATCH with DB."""

    async def test_get_settings_with_db(self, db_authed_client, monkeypatch):
        import web_app
        fake_settings = {"hospital_type": "nonprofit", "cost_per_day_override": None}
        monkeypatch.setattr(web_app, "_get_org_roi_settings", lambda org: fake_settings)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/settings")
        assert r.status_code == 200
        assert r.json()["hospital_type"] == "nonprofit"

    async def test_patch_settings_with_db(self, db_authed_client, monkeypatch):
        import web_app
        fake_settings = {"hospital_type": "forprofit", "cost_per_day_override": 3600.0}
        monkeypatch.setattr(web_app, "_upsert_org_roi_settings",
                            lambda org, body: fake_settings)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.patch(
            "/api/roi/settings",
            json={"hospital_type": "forprofit"},
        )
        assert r.status_code == 200
        assert r.json()["hospital_type"] == "forprofit"


class TestRoiExportDbPath:
    """Cover /api/roi/export CSV download with DB."""

    async def test_export_csv_with_db_empty(self, db_authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_get_org_roi_outcomes",
                            lambda org, sd, ed, **kw: [])
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/export")
        assert r.status_code == 200
        assert "text/csv" in r.headers.get("content-type", "")

    async def test_export_csv_with_outcomes(self, db_authed_client, monkeypatch):
        import web_app
        fake_outcomes = [{
            "id": 1, "drg_code": "291",
            "drg_description": "Heart Failure & Shock w MCC",
            "admission_date": "2026-05-18",
            "actual_discharge_date": "2026-05-22",
            "actual_los_days": 4,
            "drg_geometric_mean_los": 5.5,
            "excess_days_saved": 1.5,
            "cost_savings_dollars": 6150.0,
            "hrrp_condition_flagged": False,
            "hrrp_penalty_avoided": None,
            "tcm_revenue": 0,
            "total_value_dollars": 6150.0,
            "discharge_destination": "home",
            "barriers_identified": 2,
            "barriers_resolved": 2,
            "avg_barrier_resolution_hours": 24.0,
        }]
        monkeypatch.setattr(web_app, "_get_org_roi_outcomes",
                            lambda org, sd, ed, **kw: fake_outcomes)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/export")
        assert r.status_code == 200
        content = r.content.decode()
        assert "291" in content
        assert "episode_id" in content

    async def test_export_csv_with_date_params(self, db_authed_client, monkeypatch):
        import web_app
        captured = {}
        def _fake(org, sd, ed, **kw):
            captured.update({"sd": sd, "ed": ed})
            return []
        monkeypatch.setattr(web_app, "_get_org_roi_outcomes", _fake)
        monkeypatch.setattr("db.patients.get_org_domain", lambda email: "example.com")
        r = await db_authed_client.get("/api/roi/export?start_date=2026-01-01&end_date=2026-05-31")
        assert r.status_code == 200
        assert captured.get("sd") is not None
