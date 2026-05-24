"""Tests for Real-Time Insurance Eligibility Verification."""
import dataclasses
import pytest
from unittest.mock import patch, AsyncMock

from services.eligibility import (
    EligibilityResult,
    KNOWN_PAYERS,
    detect_payer_id,
    _make_cache_key,
    get_mock_result,
    parse_271_response,
)


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def sample_271_active():
    return {
        "payer": {
            "organizationName": "Test Payer",
            "planName": "Test Gold PPO",
            "planCode": "PPO",
        },
        "subscriber": {
            "memberId": "TESTMEM001",
            "groupNumber": "GRP9999",
            "coverages": [
                {
                    "eligibilityCode": "1",
                    "eligibilityDescription": "Active Coverage",
                    "serviceTypeCode": "30",
                    "benefitSummary": {
                        "startDate": "20240101",
                        "endDate": "20241231",
                        "deductibleInNetwork": {"amount": 1500.0},
                        "deductibleMetInNetwork": {"amount": 750.0},
                        "outOfPocketInNetwork": {"amount": 5000.0},
                        "outOfPocketMetInNetwork": {"amount": 2000.0},
                    },
                    "benefitDetails": [],
                }
            ],
        },
    }


@pytest.fixture
def sample_271_inactive():
    return {
        "payer": {"organizationName": "Inactive Payer", "planName": "", "planCode": ""},
        "subscriber": {
            "memberId": "TESTMEM002",
            "groupNumber": "",
            "coverages": [
                {
                    "eligibilityCode": "6",
                    "eligibilityDescription": "Inactive",
                    "serviceTypeCode": "30",
                    "benefitSummary": {},
                    "benefitDetails": [],
                }
            ],
        },
    }


@pytest.fixture
def sample_271_prior_auth():
    return {
        "payer": {"organizationName": "Auth Payer", "planName": "HMO", "planCode": "HMO"},
        "subscriber": {
            "memberId": "TESTMEM003",
            "groupNumber": "",
            "coverages": [
                {
                    "eligibilityCode": "1",
                    "eligibilityDescription": "Prior Authorization required for specialist",
                    "serviceTypeCode": "30",
                    "benefitSummary": {},
                    "benefitDetails": [],
                }
            ],
        },
    }


@pytest.fixture
def sample_271_snf():
    return {
        "payer": {"organizationName": "SNF Payer", "planName": "Medicare", "planCode": "MED"},
        "subscriber": {
            "memberId": "TESTMEM004",
            "groupNumber": "",
            "coverages": [
                {
                    "eligibilityCode": "1",
                    "eligibilityDescription": "Active Coverage",
                    "serviceTypeCode": "48",
                    "benefitSummary": {},
                    "benefitDetails": [
                        {"code": "C", "amount": 194.5},
                    ],
                }
            ],
        },
    }


# ── TestDetectPayerId ─────────────────────────────────────────────────────────

class TestDetectPayerId:
    def test_medicare_traditional_maps_to_cms(self):
        payer_id, name = detect_payer_id("Medicare Traditional")
        assert payer_id == "CMS"
        assert name == "Medicare"

    def test_medicare_case_insensitive(self):
        payer_id, name = detect_payer_id("MEDICARE")
        assert payer_id == "CMS"

    def test_medi_cal_maps_to_camc(self):
        payer_id, name = detect_payer_id("medi-cal")
        assert payer_id == "CAMC"
        assert name == "Medi-Cal"

    def test_medi_cal_managed_care_maps_to_camc(self):
        payer_id, name = detect_payer_id("Medi-Cal Managed Care")
        assert payer_id == "CAMC"

    def test_kaiser_maps_to_94270(self):
        payer_id, name = detect_payer_id("Kaiser")
        assert payer_id == "94270"
        assert name == "Kaiser Permanente"

    def test_kaiser_permanente_full_name(self):
        payer_id, name = detect_payer_id("Kaiser Permanente Northern California")
        assert payer_id == "94270"

    def test_unknown_payer_returns_unknown(self):
        payer_id, name = detect_payer_id("unknown payer xyz")
        assert payer_id == "UNKNOWN"
        assert name == "unknown payer xyz"

    def test_empty_string_returns_unknown(self):
        payer_id, name = detect_payer_id("")
        assert payer_id == "UNKNOWN"

    def test_aetna_maps_correctly(self):
        payer_id, name = detect_payer_id("Aetna Health Plan")
        assert payer_id == "60054"

    def test_uhc_alias(self):
        payer_id, name = detect_payer_id("UHC")
        assert payer_id == "87726"

    def test_anthem_maps_correctly(self):
        payer_id, name = detect_payer_id("Anthem Blue Cross California")
        assert payer_id == "ANTCA"


# ── TestMakeCacheKey ──────────────────────────────────────────────────────────

class TestMakeCacheKey:
    def test_returns_32_char_hex_string(self):
        key = _make_cache_key("MEM001", "CMS", "2024-01-01")
        assert isinstance(key, str)
        assert len(key) == 32
        assert all(c in "0123456789abcdef" for c in key)

    def test_same_inputs_produce_same_key(self):
        key1 = _make_cache_key("MEM001", "CMS", "2024-01-01")
        key2 = _make_cache_key("MEM001", "CMS", "2024-01-01")
        assert key1 == key2

    def test_different_member_id_produces_different_key(self):
        key1 = _make_cache_key("MEM001", "CMS", "2024-01-01")
        key2 = _make_cache_key("MEM002", "CMS", "2024-01-01")
        assert key1 != key2

    def test_different_payer_produces_different_key(self):
        key1 = _make_cache_key("MEM001", "CMS", "2024-01-01")
        key2 = _make_cache_key("MEM001", "CAMC", "2024-01-01")
        assert key1 != key2

    def test_different_date_produces_different_key(self):
        key1 = _make_cache_key("MEM001", "CMS", "2024-01-01")
        key2 = _make_cache_key("MEM001", "CMS", "2024-01-02")
        assert key1 != key2

    def test_key_is_deterministic_across_calls(self):
        keys = [_make_cache_key("TESTMEMBER", "87726", "2026-05-24") for _ in range(5)]
        assert len(set(keys)) == 1


# ── TestGetMockResult ─────────────────────────────────────────────────────────

class TestGetMockResult:
    def test_medicare_mock_is_eligible(self):
        result = get_mock_result("CMS", "Medicare")
        assert result.is_eligible is True
        assert result.source == "mock"
        assert result.payer_id == "CMS"

    def test_medicare_mock_plan_details(self):
        result = get_mock_result("CMS", "Medicare")
        assert result.plan_name == "Medicare Part A & B"
        assert result.plan_type == "Medicare Traditional"
        assert result.deductible_individual == 1600.0
        assert result.deductible_met == 800.0
        assert result.snf_days_remaining == 87
        assert result.prior_auth_required is False
        assert result.coverage_start == "2024-01-01"

    def test_medicare_mock_checked_at_is_set(self):
        result = get_mock_result("CMS", "Medicare")
        assert result.checked_at != ""

    def test_medi_cal_mock_prior_auth_required(self):
        result = get_mock_result("CAMC", "Medi-Cal")
        assert result.prior_auth_required is True
        assert result.source == "mock"
        assert result.is_eligible is True

    def test_medi_cal_mock_plan_details(self):
        result = get_mock_result("CAMC", "Medi-Cal")
        assert result.plan_name == "Medi-Cal Managed Care"
        assert result.plan_type == "Medicaid"
        assert result.snf_days_remaining is None
        assert result.coverage_start == "2023-07-01"

    def test_fallback_payer_returns_ppo_plan(self):
        result = get_mock_result("60054", "Aetna")
        assert result.is_eligible is True
        assert result.source == "mock"
        assert result.plan_name == "Aetna PPO"
        assert result.deductible_individual == 3000.0
        assert result.deductible_met == 1200.0
        assert result.out_of_pocket_max == 6000.0
        assert result.prior_auth_required is True

    def test_result_is_eligibility_result_instance(self):
        result = get_mock_result("87726", "UHC")
        assert isinstance(result, EligibilityResult)


# ── TestParse271Response ──────────────────────────────────────────────────────

class TestParse271Response:
    def test_active_coverage_is_eligible_true(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.is_eligible is True

    def test_inactive_coverage_is_eligible_false(self, sample_271_inactive):
        result = parse_271_response(sample_271_inactive)
        assert result.is_eligible is False

    def test_date_parsing_yyyymmdd_to_iso(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.coverage_start == "2024-01-01"
        assert result.coverage_end == "2024-12-31"

    def test_payer_name_extracted(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.payer_name == "Test Payer"

    def test_plan_name_extracted(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.plan_name == "Test Gold PPO"

    def test_group_number_extracted(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.group_number == "GRP9999"

    def test_deductible_amounts_extracted(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.deductible_individual == 1500.0
        assert result.deductible_met == 750.0

    def test_oop_amounts_extracted(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.out_of_pocket_max == 5000.0
        assert result.out_of_pocket_met == 2000.0

    def test_source_is_live(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.source == "live"

    def test_checked_at_is_set(self, sample_271_active):
        result = parse_271_response(sample_271_active)
        assert result.checked_at != ""

    def test_prior_auth_detected_case_insensitive(self, sample_271_prior_auth):
        result = parse_271_response(sample_271_prior_auth)
        assert result.prior_auth_required is True

    def test_snf_copay_extracted_from_benefit_details(self, sample_271_snf):
        result = parse_271_response(sample_271_snf)
        assert result.copay_specialist == 194.5

    def test_empty_response_is_eligible_false(self):
        result = parse_271_response({})
        assert result.is_eligible is False
        assert result.payer_name == ""

    def test_pending_coverage_code_7_not_eligible(self):
        response = {
            "payer": {"organizationName": "Test", "planName": "", "planCode": ""},
            "subscriber": {
                "memberId": "MEM999",
                "groupNumber": "",
                "coverages": [
                    {
                        "eligibilityCode": "7",
                        "eligibilityDescription": "Pending",
                        "serviceTypeCode": "30",
                        "benefitSummary": {},
                        "benefitDetails": [],
                    }
                ],
            },
        }
        result = parse_271_response(response)
        assert result.is_eligible is False


# ── TestEligibilityEndpoints ──────────────────────────────────────────────────

class TestEligibilityEndpoints:
    async def test_get_payers_returns_200(self, authed_client):
        r = await authed_client.get("/api/eligibility/payers")
        assert r.status_code == 200
        data = r.json()
        assert "payers" in data
        assert isinstance(data["payers"], list)

    async def test_get_payers_contains_medicare(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        r = await authed_client.get("/api/eligibility/payers")
        assert r.status_code == 200
        names = [p["name"] for p in r.json()["payers"]]
        assert "Medicare" in names

    async def test_get_payers_unauthenticated_returns_401(self, client):
        r = await client.get("/api/eligibility/payers")
        assert r.status_code == 401

    async def test_mock_endpoint_medicare_returns_eligible(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        r = await authed_client.post(
            "/api/eligibility/mock",
            json={"payer_name": "Medicare Traditional"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["is_eligible"] is True
        assert data["source"] == "mock"

    async def test_mock_endpoint_unknown_payer_returns_mock(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        r = await authed_client.post(
            "/api/eligibility/mock",
            json={"payer_name": "Some Unknown Insurance Co"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "mock"

    async def test_mock_endpoint_default_payer_when_missing(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        r = await authed_client.post("/api/eligibility/mock", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "mock"

    async def test_mock_endpoint_unavailable_returns_503(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", False)
        r = await authed_client.post(
            "/api/eligibility/mock", json={"payer_name": "Medicare Traditional"}
        )
        assert r.status_code == 503

    async def test_mock_endpoint_unauthenticated_returns_401(self, client):
        r = await client.post(
            "/api/eligibility/mock", json={"payer_name": "Medicare Traditional"}
        )
        assert r.status_code == 401

    async def test_check_without_eligibility_enabled_returns_503(self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", False)
        r = await authed_client.post(
            "/api/eligibility/check",
            json={
                "member_id": "TESTMEM001",
                "payer_id": "CMS",
                "first_name": "JOHN",
                "last_name": "DOE",
                "date_of_birth": "19400101",
                "npi": "1234567890",
            },
        )
        assert r.status_code == 503
        assert "not enabled" in r.json()["error"].lower() or "STEDI_API_KEY" in r.json()["error"]

    async def test_check_without_stedi_key_returns_503(self, authed_client, monkeypatch):
        import web_app
        import os
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.delenv("STEDI_API_KEY", raising=False)
        r = await authed_client.post(
            "/api/eligibility/check",
            json={
                "member_id": "TESTMEM001",
                "payer_id": "CMS",
                "first_name": "JOHN",
                "last_name": "DOE",
                "date_of_birth": "19400101",
                "npi": "1234567890",
            },
        )
        assert r.status_code == 503

    async def test_check_unauthenticated_returns_401(self, client):
        r = await client.post(
            "/api/eligibility/check",
            json={
                "member_id": "TESTMEM001",
                "payer_id": "CMS",
                "first_name": "JOHN",
                "last_name": "DOE",
                "date_of_birth": "19400101",
                "npi": "1234567890",
            },
        )
        assert r.status_code == 401

    async def test_check_missing_required_fields_returns_400(self, authed_client, monkeypatch):
        import web_app
        import os
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")
        r = await authed_client.post(
            "/api/eligibility/check",
            json={"payer_id": "CMS"},
        )
        assert r.status_code == 400

    async def test_check_with_stedi_key_calls_service(self, authed_client, monkeypatch):
        import web_app
        import services.eligibility as svc
        from datetime import datetime, timezone

        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")

        mock_result = EligibilityResult(
            is_eligible=True,
            payer_id="CMS",
            payer_name="Medicare",
            plan_name="Medicare Part A & B",
            source="live",
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

        async def _fake_check(member_id, first, last, dob, payer_id, npi):
            return mock_result

        monkeypatch.setattr(web_app, "_check_eligibility", _fake_check)

        r = await authed_client.post(
            "/api/eligibility/check",
            json={
                "member_id": "TESTMEM001",
                "payer_id": "CMS",
                "first_name": "JOHN",
                "last_name": "DOE",
                "date_of_birth": "19400101",
                "npi": "1234567890",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["is_eligible"] is True
        assert data["payer_id"] == "CMS"


# ── TestCacheDb ───────────────────────────────────────────────────────────────

class TestCacheDb:
    def test_get_cached_eligibility_returns_none_on_miss(self, monkeypatch):
        """get_cached_eligibility returns None when db query returns nothing."""
        import db.patients as dp

        fake_row = None

        class FakeCur:
            def execute(self, sql, params):
                pass
            def fetchone(self):
                return fake_row
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        class FakeConn:
            def cursor(self):
                return FakeCur()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def close(self):
                pass

        monkeypatch.setattr(dp, "get_db_conn", lambda: FakeConn())
        result = dp.get_cached_eligibility("nonexistent-key-abc123")
        assert result is None

    def test_get_cached_eligibility_returns_dict_on_hit(self, monkeypatch):
        """get_cached_eligibility returns the cached dict when db has a valid row."""
        import db.patients as dp

        payload = {"is_eligible": True, "payer_id": "CMS", "source": "live"}

        class FakeCur:
            def execute(self, sql, params):
                pass
            def fetchone(self):
                return {"result_json": payload}
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        class FakeConn:
            def cursor(self):
                return FakeCur()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def close(self):
                pass

        monkeypatch.setattr(dp, "get_db_conn", lambda: FakeConn())
        result = dp.get_cached_eligibility("some-key")
        assert result is not None
        assert result["is_eligible"] is True
        assert result["payer_id"] == "CMS"

    def test_cache_eligibility_result_executes_upsert(self, monkeypatch):
        """cache_eligibility_result calls execute with the correct INSERT ON CONFLICT SQL."""
        import db.patients as dp

        executed_sqls = []
        executed_params = []

        class FakeCur:
            def execute(self, sql, params):
                executed_sqls.append(sql)
                executed_params.append(params)
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass

        class FakeConn:
            def cursor(self):
                return FakeCur()
            def __enter__(self):
                return self
            def __exit__(self, *a):
                pass
            def close(self):
                pass

        monkeypatch.setattr(dp, "get_db_conn", lambda: FakeConn())
        dp.cache_eligibility_result(
            cache_key="testkey123",
            result_json={"is_eligible": True},
            payer_id="CMS",
            ttl_hours=4,
        )
        assert len(executed_sqls) == 1
        assert "INSERT INTO eligibility_cache" in executed_sqls[0]
        assert "ON CONFLICT" in executed_sqls[0]
        params = executed_params[0]
        assert params[0] == "testkey123"
        assert params[1] == "CMS"
        assert params[3] == 4

    async def test_cache_miss_triggers_live_check_in_stream(
        self, db_authed_client, monkeypatch
    ):
        """When get_cached_eligibility returns None during plan stream, live check is attempted."""
        import web_app
        import db.patients as dp

        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_MOCK", True)

        get_calls = []
        cache_calls = []

        def _fake_get_cached(key):
            get_calls.append(key)
            return None

        def _fake_cache_result(cache_key, result_json, payer_id, ttl_hours=4):
            cache_calls.append(payer_id)

        monkeypatch.setattr(dp, "get_cached_eligibility", _fake_get_cached)
        monkeypatch.setattr(dp, "cache_eligibility_result", _fake_cache_result)

        r = await db_authed_client.post(
            "/api/eligibility/mock",
            json={"payer_name": "Medicare Traditional"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "mock"


# ── TestEligibilityCheckDb — covers DB cache paths ─────────────────────────────

class TestEligibilityCheckDb:
    """Tests for /api/eligibility/check with DB enabled — covers cache read/write paths."""

    async def test_check_returns_cached_result_when_db_has_entry(
        self, db_authed_client, monkeypatch
    ):
        import web_app
        import db.patients as dp
        from datetime import datetime, timezone

        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")

        cached_data = {
            "is_eligible": True,
            "payer_id": "CMS",
            "payer_name": "Medicare",
            "plan_name": "Medicare Part A & B",
            "plan_type": "Medicare Traditional",
            "coverage_start": "2024-01-01",
            "coverage_end": "",
            "group_number": "",
            "deductible_individual": 1600.0,
            "deductible_met": 800.0,
            "out_of_pocket_max": None,
            "out_of_pocket_met": None,
            "copay_specialist": None,
            "coinsurance_pct": None,
            "snf_days_remaining": 87,
            "home_health_authorized": None,
            "prior_auth_required": False,
            "source": "live",
            "checked_at": "2026-05-24T00:00:00+00:00",
            "error_message": "",
        }

        monkeypatch.setattr(dp, "get_cached_eligibility", lambda key: cached_data)
        monkeypatch.setattr(web_app, "_elig_cache_key", _make_cache_key)

        r = await db_authed_client.post(
            "/api/eligibility/check",
            json={
                "member_id": "TESTMEM001",
                "payer_id": "CMS",
                "first_name": "JOHN",
                "last_name": "DOE",
                "date_of_birth": "19400101",
                "npi": "1234567890",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["source"] == "cache"
        assert data["is_eligible"] is True

    async def test_check_writes_to_cache_after_live_call(
        self, db_authed_client, monkeypatch
    ):
        import web_app
        import db.patients as dp
        from datetime import datetime, timezone

        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")

        cache_calls = []

        monkeypatch.setattr(dp, "get_cached_eligibility", lambda key: None)
        monkeypatch.setattr(
            dp, "cache_eligibility_result",
            lambda ck, rj, pid, ttl_hours=4: cache_calls.append(pid)
        )

        mock_result = EligibilityResult(
            is_eligible=True,
            payer_id="CMS",
            payer_name="Medicare",
            source="live",
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

        async def _fake_check(member_id, first, last, dob, payer_id, npi):
            return mock_result

        monkeypatch.setattr(web_app, "_check_eligibility", _fake_check)
        monkeypatch.setattr(web_app, "_elig_cache_key", _make_cache_key)

        r = await db_authed_client.post(
            "/api/eligibility/check",
            json={
                "member_id": "TESTMEM001",
                "payer_id": "CMS",
                "first_name": "JOHN",
                "last_name": "DOE",
                "date_of_birth": "19400101",
                "npi": "1234567890",
            },
        )
        assert r.status_code == 200
        assert len(cache_calls) == 1
        assert cache_calls[0] == "CMS"

    async def test_check_handles_stedi_value_error_as_422(
        self, authed_client, monkeypatch
    ):
        import web_app

        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")

        async def _bad_check(*a, **kw):
            raise ValueError("Invalid eligibility request — check member ID and payer ID")

        monkeypatch.setattr(web_app, "_check_eligibility", _bad_check)

        r = await authed_client.post(
            "/api/eligibility/check",
            json={"member_id": "X", "payer_id": "CMS", "npi": "1234567890"},
        )
        assert r.status_code == 422
        assert "Invalid" in r.json()["error"]

    async def test_check_handles_runtime_error_as_500(
        self, authed_client, monkeypatch
    ):
        import web_app

        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")

        async def _bad_check(*a, **kw):
            raise RuntimeError("Stedi API error: 503")

        monkeypatch.setattr(web_app, "_check_eligibility", _bad_check)

        r = await authed_client.post(
            "/api/eligibility/check",
            json={"member_id": "X", "payer_id": "CMS", "npi": "1234567890"},
        )
        assert r.status_code == 500
        assert "failed" in r.json()["error"]


# ── TestSettingsEndpoints ─────────────────────────────────────────────────────

class TestSettingsEndpoints:
    async def test_settings_page_authenticated(self, authed_client):
        r = await authed_client.get("/settings")
        assert r.status_code == 200
        assert "Settings" in r.text

    async def test_settings_page_unauthenticated_redirects(self, client):
        r = await client.get("/settings", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    async def test_api_settings_returns_config(self, authed_client):
        r = await authed_client.get("/api/settings")
        assert r.status_code == 200
        data = r.json()
        assert "eligibility_enabled" in data
        assert "stedi_configured" in data
        assert isinstance(data["eligibility_enabled"], bool)

    async def test_api_settings_unauthenticated_returns_401(self, client):
        r = await client.get("/api/settings")
        assert r.status_code == 401


class TestEligibilityUnavailablePaths:
    """Covers branches where _ELIGIBILITY_AVAILABLE=False."""

    async def test_payers_returns_empty_list_when_service_unavailable(
        self, authed_client, monkeypatch
    ):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", False)
        r = await authed_client.get("/api/eligibility/payers")
        assert r.status_code == 200
        assert r.json()["payers"] == []

    async def test_check_returns_503_when_service_unavailable(
        self, authed_client, monkeypatch
    ):
        import web_app
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", False)
        r = await authed_client.post(
            "/api/eligibility/check",
            json={"member_id": "X", "payer_id": "CMS", "npi": "1234567890"},
        )
        assert r.status_code == 503

    async def test_check_cache_exception_swallowed_falls_through_to_live(
        self, db_authed_client, monkeypatch
    ):
        import web_app
        import db.patients as dp
        from datetime import datetime, timezone

        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")

        def _bad_cache_get(key):
            raise RuntimeError("DB exploded")

        monkeypatch.setattr(dp, "get_cached_eligibility", _bad_cache_get)

        mock_result = EligibilityResult(
            is_eligible=True,
            payer_id="CMS",
            payer_name="Medicare",
            source="live",
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

        async def _fake_check(*a, **kw):
            return mock_result

        monkeypatch.setattr(web_app, "_check_eligibility", _fake_check)
        monkeypatch.setattr(web_app, "_elig_cache_key", _make_cache_key)
        monkeypatch.setattr(dp, "cache_eligibility_result", lambda *a, **kw: None)

        r = await db_authed_client.post(
            "/api/eligibility/check",
            json={"member_id": "X", "payer_id": "CMS", "npi": "1234567890"},
        )
        assert r.status_code == 200
        assert r.json()["is_eligible"] is True

    async def test_check_cache_write_exception_swallowed_returns_result(
        self, db_authed_client, monkeypatch
    ):
        import web_app
        import db.patients as dp
        from datetime import datetime, timezone

        monkeypatch.setattr(web_app, "_PATIENT_DB_AVAILABLE", True)
        monkeypatch.setattr(web_app, "_ELIGIBILITY_AVAILABLE", True)
        monkeypatch.setattr(web_app, "ELIGIBILITY_ENABLED", True)
        monkeypatch.setenv("STEDI_API_KEY", "test-key-fake")

        monkeypatch.setattr(dp, "get_cached_eligibility", lambda key: None)

        def _bad_cache_write(*a, **kw):
            raise RuntimeError("Write failed")

        monkeypatch.setattr(dp, "cache_eligibility_result", _bad_cache_write)

        mock_result = EligibilityResult(
            is_eligible=True,
            payer_id="CMS",
            payer_name="Medicare",
            source="live",
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

        async def _fake_check(*a, **kw):
            return mock_result

        monkeypatch.setattr(web_app, "_check_eligibility", _fake_check)
        monkeypatch.setattr(web_app, "_elig_cache_key", _make_cache_key)

        r = await db_authed_client.post(
            "/api/eligibility/check",
            json={"member_id": "X", "payer_id": "CMS", "npi": "1234567890"},
        )
        assert r.status_code == 200
        assert r.json()["is_eligible"] is True
