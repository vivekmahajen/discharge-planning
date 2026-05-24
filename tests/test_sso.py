"""Tests for Auth0 SSO routes: /api/auth/sso/config, /auth/sso/login, /auth/sso/callback."""
import pytest
from unittest.mock import AsyncMock, patch


class TestSsoConfig:
    async def test_sso_config_disabled_when_env_not_set(self, client):
        r = await client.get("/api/auth/sso/config")
        assert r.status_code == 200
        assert r.json() == {"enabled": False}

    async def test_sso_config_enabled_when_env_set(self, client, monkeypatch):
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "client123")
        monkeypatch.setenv("AUTH0_CLIENT_SECRET", "secret456")
        r = await client.get("/api/auth/sso/config")
        assert r.status_code == 200
        assert r.json() == {"enabled": True}


class TestSsoLogin:
    async def test_sso_login_returns_503_when_not_configured(self, client):
        r = await client.get("/auth/sso/login", follow_redirects=False)
        assert r.status_code == 503

    async def test_sso_login_redirects_to_auth0_when_configured(self, client, monkeypatch):
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "client123")
        monkeypatch.setenv("AUTH0_CLIENT_SECRET", "secret456")
        r = await client.get("/auth/sso/login", follow_redirects=False)
        assert r.status_code == 302
        location = r.headers["location"]
        assert "test.auth0.com/authorize" in location
        assert "client123" in location
        assert "code_challenge" in location
        assert "openid" in location

    async def test_sso_login_sets_state_cookie(self, client, monkeypatch):
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "client123")
        monkeypatch.setenv("AUTH0_CLIENT_SECRET", "secret456")
        r = await client.get("/auth/sso/login", follow_redirects=False)
        assert "sso_auth_state" in r.cookies


class TestSsoCallback:
    def _make_state_cookie(self, state: str, verifier: str) -> str:
        import web_app
        return web_app._serializer.dumps({"state": state, "code_verifier": verifier})

    async def test_callback_missing_code_returns_400(self, client):
        r = await client.get("/auth/sso/callback?state=abc", follow_redirects=False)
        assert r.status_code == 400

    async def test_callback_missing_state_returns_400(self, client):
        r = await client.get("/auth/sso/callback?code=xyz", follow_redirects=False)
        assert r.status_code == 400

    async def test_callback_missing_state_cookie_returns_400(self, client):
        r = await client.get("/auth/sso/callback?code=xyz&state=abc", follow_redirects=False)
        assert r.status_code == 400

    async def test_callback_state_mismatch_returns_400(self, client):
        cookie = self._make_state_cookie("correct-state", "verifier123")
        r = await client.get(
            "/auth/sso/callback?code=xyz&state=wrong-state",
            cookies={"sso_auth_state": cookie},
            follow_redirects=False,
        )
        assert r.status_code == 400
        assert "mismatch" in r.json()["detail"].lower()

    async def test_callback_auth0_error_redirects_to_login(self, client):
        r = await client.get(
            "/auth/sso/callback?error=access_denied",
            follow_redirects=False,
        )
        assert r.status_code == 302
        assert "/login" in r.headers["location"]

    async def test_callback_success_sets_session_cookie(self, client, monkeypatch):
        state = "test-state-value"
        verifier = "test-verifier-value"
        cookie = self._make_state_cookie(state, verifier)

        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "client123")
        monkeypatch.setenv("AUTH0_CLIENT_SECRET", "secret456")

        with (
            patch("auth0_oidc.exchange_code", new=AsyncMock(return_value={"access_token": "tok123"})),
            patch("auth0_oidc.get_userinfo", new=AsyncMock(return_value={"email": "sso-user@hospital.org"})),
        ):
            r = await client.get(
                f"/auth/sso/callback?code=authcode&state={state}",
                cookies={"sso_auth_state": cookie},
                follow_redirects=False,
            )

        assert r.status_code == 302
        assert r.headers["location"] == "/"
        assert "dp_session" in r.cookies

    async def test_callback_no_email_returns_400(self, client, monkeypatch):
        state = "test-state-value"
        verifier = "test-verifier-value"
        cookie = self._make_state_cookie(state, verifier)

        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "client123")
        monkeypatch.setenv("AUTH0_CLIENT_SECRET", "secret456")

        with (
            patch("auth0_oidc.exchange_code", new=AsyncMock(return_value={"access_token": "tok"})),
            patch("auth0_oidc.get_userinfo", new=AsyncMock(return_value={})),
        ):
            r = await client.get(
                f"/auth/sso/callback?code=authcode&state={state}",
                cookies={"sso_auth_state": cookie},
                follow_redirects=False,
            )

        assert r.status_code == 400
        assert "email" in r.json()["detail"].lower()

    async def test_callback_token_exchange_failure_returns_502(self, client, monkeypatch):
        state = "test-state-value"
        verifier = "test-verifier-value"
        cookie = self._make_state_cookie(state, verifier)

        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_CLIENT_ID", "client123")
        monkeypatch.setenv("AUTH0_CLIENT_SECRET", "secret456")

        with patch("auth0_oidc.exchange_code", new=AsyncMock(side_effect=Exception("network error"))):
            r = await client.get(
                f"/auth/sso/callback?code=authcode&state={state}",
                cookies={"sso_auth_state": cookie},
                follow_redirects=False,
            )

        assert r.status_code == 502
        assert "Token exchange failed" in r.json()["detail"]
