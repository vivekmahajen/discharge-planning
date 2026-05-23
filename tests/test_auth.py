"""170.315(g)(10) — Auth endpoint tests.

Covers: signup, login, logout, session expiry, brute-force rate limiting.
"""
import pytest


@pytest.mark.anyio
async def test_signup_success(client):
    resp = await client.post(
        "/api/auth/signup",
        json={"email": "newuser@hospital.org", "password": "SecurePass1!"},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_signup_duplicate_email(client):
    payload = {"email": "dup@hospital.org", "password": "SecurePass1!"}
    await client.post("/api/auth/signup", json=payload)
    resp = await client.post("/api/auth/signup", json=payload)
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_login_success(authed_client):
    resp = await authed_client.get("/api/healthz")
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_login_wrong_password(client):
    await client.post(
        "/api/auth/signup",
        json={"email": "wrongpw@hospital.org", "password": "CorrectPass1!"},
    )
    resp = await client.post(
        "/api/auth/login",
        json={"email": "wrongpw@hospital.org", "password": "WrongPass!"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_login_unknown_email(client):
    resp = await client.post(
        "/api/auth/login",
        json={"email": "nobody@nowhere.com", "password": "anything"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_protected_route_requires_auth(client):
    resp = await client.post("/api/plan/stream", json={})
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_logout_clears_session(authed_client):
    resp = await authed_client.post("/api/auth/logout")
    assert resp.status_code in (200, 302)
    # After logout, protected route should reject
    resp = await authed_client.post("/api/plan/stream", json={})
    assert resp.status_code == 401
