"""Rate limiting tests — auth brute-force protection, AI cost guards, lockout.

Covers: per-IP auth limits, per-user AI hourly limits, progressive account
lockout, 429 JSON response format, Retry-After header, global budget guard,
and rate-limit response headers on successful responses.
"""
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def ensure_rate_limiting_enabled(monkeypatch):
    """Ensure RATE_LIMIT_ENABLED is True for all tests in this module."""
    import web_app
    monkeypatch.setattr(web_app, "RATE_LIMIT_ENABLED", True)


class TestAuthRateLimiting:
    async def test_login_rate_limited_after_5_attempts(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        await client.post("/api/auth/signup",
            json={"email": "victim@x.com", "password": "StrongPass1!"})
        statuses = []
        for _ in range(7):
            r = await client.post("/api/auth/login",
                json={"email": "victim@x.com", "password": "WRONG"})
            statuses.append(r.status_code)
        assert 429 in statuses, f"Expected 429 after 5 failed attempts; got {statuses}"

    async def test_signup_rate_limited_after_3_per_minute(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        statuses = []
        for i in range(5):
            r = await client.post("/api/auth/signup",
                json={"email": f"spam{i}@x.com", "password": "StrongPass1!"})
            statuses.append(r.status_code)
        assert 429 in statuses, f"Expected 429 after 3 signups/minute; got {statuses}"

    async def test_429_response_includes_retry_after_header(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        await client.post("/api/auth/signup",
            json={"email": "v2@x.com", "password": "StrongPass1!"})
        r = None
        for _ in range(7):
            r = await client.post("/api/auth/login",
                json={"email": "v2@x.com", "password": "WRONG"})
            if r.status_code == 429:
                break
        assert r.status_code == 429
        assert "retry-after" in r.headers
        assert int(r.headers["retry-after"]) > 0

    async def test_429_response_body_is_structured_json(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        await client.post("/api/auth/signup",
            json={"email": "v3@x.com", "password": "StrongPass1!"})
        r = None
        for _ in range(7):
            r = await client.post("/api/auth/login",
                json={"email": "v3@x.com", "password": "WRONG"})
            if r.status_code == 429:
                break
        assert r.status_code == 429
        body = r.json()
        assert "error" in body
        assert "retry_after_seconds" in body
        assert "retry_after_human" in body
        assert "support" in body
        assert isinstance(body["retry_after_seconds"], int)

    async def test_429_response_includes_ratelimit_reset_header(
            self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        await client.post("/api/auth/signup",
            json={"email": "v4@x.com", "password": "StrongPass1!"})
        r = None
        for _ in range(7):
            r = await client.post("/api/auth/login",
                json={"email": "v4@x.com", "password": "WRONG"})
            if r.status_code == 429:
                break
        assert r.status_code == 429
        assert "x-ratelimit-limit" in r.headers or "X-RateLimit-Limit" in r.headers


class TestAiEndpointRateLimiting:
    async def test_rate_limit_headers_present_on_successful_ai_response(
            self, authed_client, mock_claude):
        r = await authed_client.post("/api/summary/generate",
            json={"clinicalNotes": "Test notes", "patientContext": {}})
        assert r.status_code == 200
        headers_lower = {k.lower(): v for k, v in r.headers.items()}
        assert "x-ratelimit-limit" in headers_lower, (
            "X-RateLimit-Limit header missing from AI endpoint response")
        assert "x-ratelimit-remaining" in headers_lower, (
            "X-RateLimit-Remaining header missing from AI endpoint response")

    async def test_ai_endpoint_rate_limited_after_hourly_threshold(
            self, authed_client, mock_claude):
        """POST /api/summary/generate returns 429 after 20 calls/hour.

        Pre-fills the moving-window storage using the same key construction
        slowapi uses, then verifies the next request is rejected.
        """
        import web_app
        from limits import parse as _parse
        item = _parse("20/hour")
        identifier = "user:test@example.com//api/summary/generate"
        storage = web_app.limiter._storage
        for _ in range(20):
            storage.acquire_entry(item.key_for(identifier), item.amount, item.get_expiry())

        r = await authed_client.post("/api/summary/generate",
            json={"clinicalNotes": "Test", "patientContext": {}})
        assert r.status_code == 429, (
            f"Expected 429 after exhausting 20/hour limit; got {r.status_code}")

    async def test_plan_stream_rate_limited_after_10_per_hour(
            self, authed_client, mock_stream_plan):
        """POST /api/plan/stream returns 429 after 10 calls/hour."""
        import web_app
        from limits import parse as _parse
        item = _parse("10/hour")
        identifier = "user:test@example.com//api/plan/stream"
        storage = web_app.limiter._storage
        for _ in range(10):
            storage.acquire_entry(item.key_for(identifier), item.amount, item.get_expiry())
        from sample_patient import SAMPLE_PATIENT_WEB
        r = await authed_client.post("/api/plan/stream", json=dict(SAMPLE_PATIENT_WEB))
        assert r.status_code == 429, (
            f"Expected 429 after exhausting 10/hour limit; got {r.status_code}")


class TestProgressiveLockout:
    async def test_locked_account_returns_429_immediately(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        with patch("web_app._check_lockout", AsyncMock(return_value=(True, 1800))):
            r = await client.post("/api/auth/login",
                json={"email": "locked@x.com", "password": "AnyPassword"})
        assert r.status_code == 429
        assert "locked" in r.json()["error"].lower()

    async def test_locked_account_429_includes_retry_after(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        with patch("web_app._check_lockout", AsyncMock(return_value=(True, 300))):
            r = await client.post("/api/auth/login",
                json={"email": "locked@x.com", "password": "AnyPassword"})
        assert r.status_code == 429
        assert "retry-after" in r.headers
        assert int(r.headers["retry-after"]) >= 299  # allow 1s timing slack

    async def test_successful_login_clears_failure_counter(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        await client.post("/api/auth/signup",
            json={"email": "clear@x.com", "password": "StrongPass1!"})
        # Record some failures
        web_app._login_failures["clear@x.com"] = [time.time() - 10, time.time() - 5]
        # Successful login should clear them
        r = await client.post("/api/auth/login",
            json={"email": "clear@x.com", "password": "StrongPass1!"})
        assert r.status_code == 200
        assert "clear@x.com" not in web_app._login_failures

    async def test_lockout_applied_after_failure_threshold(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        await client.post("/api/auth/signup",
            json={"email": "threshold@x.com", "password": "StrongPass1!"})
        # Inject 4 existing failures (threshold is 5)
        web_app._login_failures["threshold@x.com"] = [time.time()] * 4
        # 5th failure should trigger lockout
        await client.post("/api/auth/login",
            json={"email": "threshold@x.com", "password": "WRONG"})
        assert "threshold@x.com" in web_app._login_lockouts, (
            "Lockout entry should be created after 5 failed attempts")
        assert web_app._login_lockouts["threshold@x.com"] > time.time()

    async def test_lockout_functions_unit(self):
        import web_app
        email = "unit@test.com"
        # Record failures up to threshold
        for _ in range(5):
            count = await web_app._record_failed_attempt(email)
        assert count == 5
        await web_app._apply_lockout(email, count)
        is_locked, secs = await web_app._check_lockout(email)
        assert is_locked is True
        assert secs > 0
        # Clear should unlock
        await web_app._clear_failed_attempts(email)
        is_locked, _ = await web_app._check_lockout(email)
        assert is_locked is False


class TestGlobalAiBudgetGuard:
    async def test_budget_guard_returns_503_when_cap_exceeded(
            self, authed_client, mock_claude, monkeypatch):
        import web_app
        hour_key = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y%m%d%H")
        monkeypatch.setattr(web_app, "GLOBAL_AI_HOURLY_CAP", 0)
        web_app._global_ai_counters[hour_key] = 1
        r = await authed_client.post("/api/summary/generate",
            json={"clinicalNotes": "Test", "patientContext": {}})
        assert r.status_code == 503
        body = r.json()
        assert "capacity" in body["error"].lower()
        assert "retry_after_seconds" in body

    async def test_budget_guard_does_not_affect_non_ai_endpoints(
            self, authed_client, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "GLOBAL_AI_HOURLY_CAP", 0)
        hour_key = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y%m%d%H")
        web_app._global_ai_counters[hour_key] = 9999
        r = await authed_client.get("/api/me")
        assert r.status_code == 200

    async def test_budget_guard_bypassed_when_rate_limit_disabled(
            self, authed_client, mock_claude, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "RATE_LIMIT_ENABLED", False)
        monkeypatch.setattr(web_app, "GLOBAL_AI_HOURLY_CAP", 0)
        hour_key = __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y%m%d%H")
        web_app._global_ai_counters[hour_key] = 9999
        r = await authed_client.post("/api/summary/generate",
            json={"clinicalNotes": "Test", "patientContext": {}})
        assert r.status_code != 503


class TestFormatRetryAfter:
    def test_seconds_format(self):
        import web_app
        assert web_app._format_retry_after(45) == "45 seconds"

    def test_minutes_format(self):
        import web_app
        assert web_app._format_retry_after(90) == "2 minutes"

    def test_hours_format(self):
        import web_app
        assert web_app._format_retry_after(7200) == "2 hours"

    def test_exact_minute_boundary(self):
        import web_app
        assert web_app._format_retry_after(60) == "1 minutes"
