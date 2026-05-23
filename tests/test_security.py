"""Security and HIPAA compliance tests.

Covers: SECRET_KEY safety, cookie flags, session forgery, PHI not in logs,
rate limiting. All must pass before ONC certification submission.
"""
import pytest


class TestSecretKey:
    def test_app_raises_if_secret_key_not_set(self):
        """SECRET_KEY must not have a hardcoded fallback — missing key must raise.

        Uses a subprocess so the import is isolated and does not corrupt the
        module state in the current test process.
        """
        import subprocess, sys, os
        env = {k: v for k, v in os.environ.items() if k != "SECRET_KEY"}
        result = subprocess.run(
            [sys.executable, "-c", "import web_app"],
            capture_output=True, text=True, env=env,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent),
        )
        assert result.returncode != 0, (
            "Expected non-zero exit when SECRET_KEY env var is missing")
        assert "SECRET_KEY" in result.stderr or "SECRET_KEY" in result.stdout

    def test_insecure_default_not_active_in_test_environment(self):
        import web_app
        insecure_default = "discharge-planning-dev-secret-change-in-prod"
        assert web_app.SECRET_KEY != insecure_default, (
            "Insecure default SECRET_KEY is active. Set SECRET_KEY env var.")

    def test_secret_key_is_non_empty_string(self):
        import web_app
        assert isinstance(web_app.SECRET_KEY, str)
        assert len(web_app.SECRET_KEY) >= 16


class TestCookieSecurity:
    async def test_session_cookie_is_httponly(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "a@b.com", "password": "StrongPass1!"})
        assert "HttpOnly" in r.headers.get("set-cookie", "")

    async def test_session_cookie_is_samesite_lax(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "a@b.com", "password": "StrongPass1!"})
        assert "SameSite=lax" in r.headers.get("set-cookie", "")

    async def test_session_cookie_has_max_age_8_hours(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "a@b.com", "password": "StrongPass1!"})
        assert "Max-Age=28800" in r.headers.get("set-cookie", "")

    async def test_session_cookie_has_secure_flag(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "a@b.com", "password": "StrongPass1!"})
        assert "Secure" in r.headers.get("set-cookie", ""), (
            "Session cookie missing Secure flag (required per Sprint 1 security fix)")


class TestSessionForgery:
    async def test_cookie_signed_with_wrong_key_returns_401(self, client):
        from itsdangerous import URLSafeTimedSerializer
        forged = URLSafeTimedSerializer("wrong-secret-key").dumps(
            {"email": "admin@hospital.com"})
        client.cookies.set("dp_session", forged)
        r = await client.get("/api/me")
        assert r.status_code == 401

    async def test_tampered_cookie_returns_401(self, client):
        client.cookies.set("dp_session",
            "eyJlbWFpbCI6ICJoYWNrZXJAZXZpbC5jb20ifQ.BADSIG")
        r = await client.get("/api/me")
        assert r.status_code == 401

    async def test_arbitrary_string_cookie_returns_401(self, client):
        client.cookies.set("dp_session", "not-a-valid-session-token-at-all")
        r = await client.get("/api/me")
        assert r.status_code == 401

    async def test_empty_cookie_returns_401(self, client):
        client.cookies.set("dp_session", "")
        r = await client.get("/api/me")
        assert r.status_code == 401


class TestPhiNotInLogs:
    async def test_patient_name_not_in_application_logs(
            self, authed_client, mock_claude, caplog):
        """HIPAA: PHI must never appear in application log output."""
        import logging
        with caplog.at_level(logging.INFO):
            await authed_client.post("/api/summary/generate", json={
                "clinicalNotes": "Patient John Smith DOB 1950-01-01 admitted for CHF.",
                "patientContext": {"attending": "Dr. Jones"},
            })
        log_text = caplog.text
        assert "John Smith" not in log_text
        assert "1950-01-01" not in log_text

    async def test_email_not_logged_in_plaintext_during_signup(
            self, client, tmp_path, monkeypatch, caplog):
        """HIPAA: User email (PII) must not appear in application logs."""
        import web_app, logging
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        with caplog.at_level(logging.INFO):
            await client.post("/api/auth/signup",
                json={"email": "patient.private@hospital.com", "password": "StrongPass1!"})
        assert "patient.private@hospital.com" not in caplog.text

    async def test_password_never_appears_in_logs(
            self, client, tmp_path, monkeypatch, caplog):
        import web_app, logging
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        with caplog.at_level(logging.DEBUG):
            await client.post("/api/auth/signup",
                json={"email": "x@x.com", "password": "SuperSecret1!"})
        assert "SuperSecret1!" not in caplog.text


class TestProtectedRoutes:
    async def test_all_api_routes_require_auth(self, client):
        """Every POST AI endpoint must return 401 for unauthenticated requests."""
        protected = [
            ("/api/plan/stream", {}),
            ("/api/summary/generate", {"clinicalNotes": "x"}),
            ("/api/discharge-summary/generate", {"notes": "x", "ctx": {}}),
            ("/api/teachback/generate", {"prompt": "x"}),
            ("/api/cdph-compliance/analyze", {"prompt": "x"}),
            ("/api/roi/generate", {"prompt": "x"}),
            ("/api/hrrp/generate", {"prompt": "x"}),
            ("/api/multilingual/generate", {"target_language": "es", "discharge_plan": "x"}),
        ]
        for path, body in protected:
            r = await client.post(path, json=body)
            assert r.status_code == 401, (
                f"Expected 401 for unauthenticated {path}, got {r.status_code}")
