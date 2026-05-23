"""170.315(g)(10) — Authentication endpoint tests.

Covers: signup, login, logout, session cookie, ALLOWED_EMAILS, brute-force rate limiting.
"""
import pytest


class TestSignup:
    async def test_valid_signup_returns_200_and_sets_cookie(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "new@example.com", "password": "StrongPass1!"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert "dp_session" in r.cookies

    async def test_signup_sets_httponly_and_samesite_cookie(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "a@b.com", "password": "StrongPass1!"})
        cookie = r.headers.get("set-cookie", "")
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie

    async def test_duplicate_email_returns_409(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        payload = {"email": "dup@x.com", "password": "StrongPass1!"}
        await client.post("/api/auth/signup", json=payload)
        r = await client.post("/api/auth/signup", json=payload)
        assert r.status_code == 409
        assert "already exists" in r.json()["error"]

    async def test_weak_password_returns_400(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "a@b.com", "password": "short"})
        assert r.status_code == 400
        assert "8 characters" in r.json()["error"]

    async def test_invalid_email_returns_400(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "not-an-email", "password": "StrongPass1!"})
        assert r.status_code == 400

    async def test_allowed_emails_blocks_unlisted_email(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        monkeypatch.setattr(web_app, "ALLOWED_EMAILS", {"allowed@hospital.com"})
        r = await client.post("/api/auth/signup",
            json={"email": "intruder@evil.com", "password": "StrongPass1!"})
        assert r.status_code == 403

    async def test_allowed_emails_permits_listed_email(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        monkeypatch.setattr(web_app, "ALLOWED_EMAILS", {"allowed@hospital.com"})
        r = await client.post("/api/auth/signup",
            json={"email": "allowed@hospital.com", "password": "StrongPass1!"})
        assert r.status_code == 200


class TestLogin:
    async def test_valid_login_returns_200_and_sets_cookie(self, authed_client):
        r = await authed_client.post("/api/auth/login",
            json={"email": "test@example.com", "password": "SecurePass123!"})
        assert r.status_code == 200
        assert "dp_session" in r.cookies

    async def test_wrong_password_returns_401(self, authed_client):
        r = await authed_client.post("/api/auth/login",
            json={"email": "test@example.com", "password": "WRONGPASSWORD"})
        assert r.status_code == 401
        assert "Incorrect" in r.json()["error"]

    async def test_unknown_email_returns_401(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/login",
            json={"email": "ghost@x.com", "password": "AnyPass123!"})
        assert r.status_code == 401
        assert "No account" in r.json()["error"]

    async def test_invalid_email_format_returns_400(self, client):
        r = await client.post("/api/auth/login",
            json={"email": "notanemail", "password": "SomePass1!"})
        assert r.status_code == 400


class TestLogout:
    async def test_logout_redirects_to_login(self, authed_client):
        r = await authed_client.get("/api/auth/logout", follow_redirects=False)
        assert r.status_code == 302
        assert r.headers["location"] == "/login"

    async def test_logout_clears_session_cookie(self, authed_client):
        r = await authed_client.get("/api/auth/logout", follow_redirects=False)
        cookie = r.headers.get("set-cookie", "")
        assert "dp_session" in cookie
        assert "Max-Age=0" in cookie or 'dp_session=""' in cookie or "dp_session=;" in cookie

    async def test_after_logout_protected_route_returns_401(self, authed_client):
        await authed_client.get("/api/auth/logout", follow_redirects=False)
        r = await authed_client.post("/api/plan/stream", json={})
        assert r.status_code == 401


class TestMeEndpoint:
    async def test_me_returns_email_when_authed(self, authed_client):
        r = await authed_client.get("/api/me")
        assert r.status_code == 200
        assert r.json()["email"] == "test@example.com"

    async def test_me_returns_401_when_anonymous(self, client):
        r = await client.get("/api/me")
        assert r.status_code == 401


class TestRateLimiting:
    async def test_signup_rate_limited_after_threshold(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        responses = []
        for i in range(8):
            r = await client.post("/api/auth/signup",
                json={"email": f"user{i}@x.com", "password": "StrongPass1!"})
            responses.append(r.status_code)
        assert 429 in responses, "Rate limiting not triggered after repeated signup attempts"

    async def test_login_rate_limited_after_threshold(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        await client.post("/api/auth/signup",
            json={"email": "victim@x.com", "password": "StrongPass1!"})
        responses = []
        for _ in range(8):
            r = await client.post("/api/auth/login",
                json={"email": "victim@x.com", "password": "WRONG"})
            responses.append(r.status_code)
        assert 429 in responses, "Rate limiting not triggered on /api/auth/login"
