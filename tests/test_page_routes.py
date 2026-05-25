"""Page route tests — HTML-serving GET endpoints.

These routes just read static HTML files and return them. Tests verify:
- Authenticated user gets 200 with HTML content
- Unauthenticated user is redirected to /login
"""
import pytest

PAGE_ROUTES = [
    "/",
    "/summary-generator",
    "/imm-prompt-system",
    "/multilingual-prompt-system",
    "/discharge-summary-generator",
    "/teachback-checklist",
    "/cdph-compliance",
    "/post-acute-directory",
    "/hrrp-flagging",
    "/roi-tracker",
    "/readmission-tracker",
]


class TestPageRoutes:
    async def test_index_authenticated_returns_200(self, authed_client):
        r = await authed_client.get("/")
        assert r.status_code == 200
        assert "html" in r.headers.get("content-type", "").lower()

    async def test_index_unauthenticated_redirects_to_login(self, client):
        r = await client.get("/", follow_redirects=False)
        assert r.status_code == 302
        assert "/login" in r.headers.get("location", "")

    async def test_all_page_routes_return_200_when_authed(self, authed_client):
        """Every page route must return 200 HTML for an authenticated user."""
        for route in PAGE_ROUTES:
            r = await authed_client.get(route)
            assert r.status_code == 200, (
                f"Expected 200 for {route}, got {r.status_code}: {r.text[:100]}")
            assert "html" in r.headers.get("content-type", "").lower(), (
                f"Expected HTML content-type for {route}")

    async def test_all_page_routes_redirect_when_anonymous(self, client):
        """Every page route must redirect unauthenticated users to /login."""
        for route in PAGE_ROUTES:
            r = await client.get(route, follow_redirects=False)
            assert r.status_code == 302, (
                f"Expected redirect for anonymous {route}, got {r.status_code}")
            assert "/login" in r.headers.get("location", ""), (
                f"Expected redirect to /login for {route}")

    async def test_login_page_returns_200(self, client):
        r = await client.get("/login")
        assert r.status_code == 200


class TestPwaRoutes:
    async def test_sw_js_returns_200(self, client):
        r = await client.get("/sw.js")
        assert r.status_code == 200

    async def test_sw_js_content_type_is_javascript(self, client):
        r = await client.get("/sw.js")
        assert "javascript" in r.headers.get("content-type", "")

    async def test_sw_js_has_service_worker_allowed_header(self, client):
        r = await client.get("/sw.js")
        assert r.headers.get("service-worker-allowed") == "/"

    async def test_sw_js_cache_control_no_cache(self, client):
        r = await client.get("/sw.js")
        cc = r.headers.get("cache-control", "")
        assert "no-cache" in cc

    async def test_manifest_returns_200(self, client):
        r = await client.get("/manifest.json")
        assert r.status_code == 200

    async def test_manifest_content_type(self, client):
        r = await client.get("/manifest.json")
        assert "manifest" in r.headers.get("content-type", "") or "json" in r.headers.get("content-type", "")

    async def test_manifest_has_name(self, client):
        r = await client.get("/manifest.json")
        data = r.json()
        assert data["name"] == "Discharge Planning AI"

    async def test_manifest_has_shortcuts(self, client):
        r = await client.get("/manifest.json")
        data = r.json()
        assert len(data["shortcuts"]) == 3

    async def test_offline_page_returns_200_without_auth(self, client):
        r = await client.get("/offline")
        assert r.status_code == 200

    async def test_offline_page_contains_cached_patients(self, client):
        r = await client.get("/offline")
        assert "Cached Patients" in r.text

    async def test_offline_page_no_redirect(self, client):
        r = await client.get("/offline", follow_redirects=False)
        assert r.status_code == 200


class TestHealthz:
    async def test_healthz_returns_200(self, client):
        r = await client.get("/api/healthz")
        assert r.status_code == 200

    async def test_healthz_returns_ok_status(self, client):
        data = (await client.get("/api/healthz")).json()
        assert data["status"] == "ok"

    async def test_healthz_lists_routes(self, client):
        data = (await client.get("/api/healthz")).json()
        assert isinstance(data["routes"], list)
        assert len(data["routes"]) > 0
