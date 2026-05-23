"""Shared pytest fixtures for Discharge Planning AI test suite."""
import os
import pytest
from httpx import AsyncClient, ASGITransport

# Set required env vars before importing the app
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-pytest-only")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from web_app import app  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
async def authed_client(client):
    """Client with a valid session cookie."""
    resp = await client.post(
        "/api/auth/signup",
        json={"email": "test@hospital.org", "password": "TestPass123!"},
    )
    # May already exist — try login instead
    if resp.status_code not in (200, 201):
        resp = await client.post(
            "/api/auth/login",
            json={"email": "test@hospital.org", "password": "TestPass123!"},
        )
    assert resp.status_code == 200, f"Auth failed: {resp.text}"
    return client
