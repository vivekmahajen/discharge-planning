"""Multi-tenant data isolation tests.

Proves that:
  1. A clinician at Org A cannot list users from Org B.
  2. A forged org_id in the session cookie is rejected.
  3. DB-level RLS blocks queries run without app.current_org_id set.
  4. org_scoped_cursor correctly filters to the current org.

Most tests require a real PostgreSQL connection and are skipped automatically
when POSTGRES_URL / DATABASE_URL is not set.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch

# ── Skip guard ────────────────────────────────────────────────────────────────
_NEEDS_DB = pytest.mark.skipif(
    not os.getenv("POSTGRES_URL") and not os.getenv("DATABASE_URL"),
    reason="Requires PostgreSQL (set POSTGRES_URL or DATABASE_URL)",
)


# ── In-memory / unit tests (always run) ───────────────────────────────────────

class TestOrgContextParsing:
    """Session cookie encoding / decoding — no DB required."""

    async def test_signup_sets_org_id_in_cookie(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/auth/signup",
            json={"email": "orgtest@x.com", "password": "StrongPass1!"})
        assert r.status_code == 200
        # Cookie must be present
        assert "dp_session" in r.cookies

    async def test_me_endpoint_returns_org_id_and_role(self, authed_client):
        r = await authed_client.get("/api/me")
        assert r.status_code == 200
        body = r.json()
        assert "org_id" in body
        assert "role" in body
        assert "email" in body
        assert body["org_id"] == "00000000-0000-0000-0000-000000000001"
        assert body["role"] == "clinician"

    async def test_forged_org_id_in_cookie_is_unsigned(self, client):
        """A cookie with a forged org_id cannot be signed with the test SECRET_KEY."""
        import web_app
        # Build a *real* session cookie for one email, then manually corrupt it
        good_token = web_app.make_session_cookie("legit@x.com", "org-real", "clinician")
        # Tamper by replacing a character — signature will be invalid
        tampered = good_token[:-4] + "XXXX"
        client.cookies.set("dp_session", tampered, domain="test")
        r = await client.get("/api/me")
        assert r.status_code == 401

    def test_make_session_cookie_includes_org_and_role(self):
        import web_app
        from itsdangerous import URLSafeTimedSerializer
        from unittest.mock import patch
        import os
        secret = os.environ["SECRET_KEY"]
        token = web_app.make_session_cookie("u@x.com", "org-abc", "org_admin")
        s = URLSafeTimedSerializer(secret)
        data = s.loads(token, max_age=86400)
        assert data["email"] == "u@x.com"
        assert data["org_id"] == "org-abc"
        assert data["role"] == "org_admin"

    def test_get_current_org_raises_401_without_cookie(self):
        import web_app
        from fastapi import HTTPException
        from unittest.mock import MagicMock
        request = MagicMock()
        request.cookies.get.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            web_app.get_current_org(request)
        assert exc_info.value.status_code == 401

    def test_get_current_org_raises_401_with_bad_signature(self):
        import web_app
        from fastapi import HTTPException
        from unittest.mock import MagicMock
        request = MagicMock()
        request.cookies.get.return_value = "completely.invalid.token"
        with pytest.raises(HTTPException) as exc_info:
            web_app.get_current_org(request)
        assert exc_info.value.status_code == 401

    def test_get_current_org_returns_org_context(self):
        import web_app
        from unittest.mock import MagicMock
        token = web_app.make_session_cookie("doc@hospital.com", "org-999", "org_admin")
        request = MagicMock()
        request.cookies.get.return_value = token
        ctx = web_app.get_current_org(request)
        assert ctx.email == "doc@hospital.com"
        assert ctx.org_id == "org-999"
        assert ctx.role == "org_admin"

    def test_require_role_passes_matching_role(self):
        import web_app
        from unittest.mock import MagicMock
        token = web_app.make_session_cookie("admin@x.com", "org-1", "org_admin")
        request = MagicMock()
        request.cookies.get.return_value = token
        dep = web_app.require_role("org_admin", "super_admin")
        ctx = dep(web_app.get_current_org(request))
        assert ctx.role == "org_admin"

    def test_require_role_rejects_wrong_role(self):
        import web_app
        from fastapi import HTTPException
        from unittest.mock import MagicMock
        token = web_app.make_session_cookie("user@x.com", "org-1", "clinician")
        request = MagicMock()
        request.cookies.get.return_value = token
        dep = web_app.require_role("org_admin", "super_admin")
        with pytest.raises(HTTPException) as exc_info:
            dep(web_app.get_current_org(request))
        assert exc_info.value.status_code == 403


class TestAdminEndpointsFileMode:
    """Admin endpoints in file-based (DATABASE_URL=None) mode."""

    async def test_admin_users_requires_admin_role(self, authed_client):
        """Default authed_client is 'clinician' — should get 403."""
        r = await authed_client.get("/api/admin/users")
        assert r.status_code == 403

    async def test_admin_invite_requires_admin_role(self, authed_client):
        r = await authed_client.post("/api/admin/invite",
            json={"email": "new@x.com", "role": "clinician"})
        assert r.status_code == 403

    async def test_superadmin_orgs_requires_super_admin(self, authed_client):
        r = await authed_client.get("/api/superadmin/orgs")
        assert r.status_code == 403

    async def test_admin_users_works_for_org_admin(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        # Sign up as org_admin (via create-org endpoint)
        r = await client.post("/api/onboard/create-org", json={
            "name": "Test Hospital",
            "slug": "test-hospital",
            "admin_email": "admin@hospital.com",
            "admin_password": "AdminPass1!",
        })
        assert r.status_code == 200
        # Now list users — should return empty list in file mode
        r2 = await client.get("/api/admin/users")
        assert r2.status_code == 200
        assert "users" in r2.json()

    async def test_superadmin_orgs_works_for_super_admin(self, client, tmp_path, monkeypatch):
        import web_app
        from web_app import app, get_current_org, OrgContext
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        # Use FastAPI dependency_overrides — the only reliable way to override Depends()
        app.dependency_overrides[get_current_org] = lambda: OrgContext(
            "sa@x.com", web_app.DEFAULT_ORG_ID, "super_admin"
        )
        try:
            r = await client.get("/api/superadmin/orgs")
            assert r.status_code == 200
            assert "orgs" in r.json()
        finally:
            del app.dependency_overrides[get_current_org]


class TestOnboardEndpoints:
    async def test_create_org_validates_required_fields(self, client):
        r = await client.post("/api/onboard/create-org", json={})
        assert r.status_code == 400

    async def test_create_org_rejects_invalid_slug(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/onboard/create-org", json={
            "name": "X", "slug": "INVALID SLUG!", "admin_email": "a@b.com",
            "admin_password": "SecurePass1!",
        })
        assert r.status_code == 400

    async def test_create_org_file_mode_sets_org_admin_session(self, client, tmp_path, monkeypatch):
        import web_app
        monkeypatch.setattr(web_app, "_LOCAL_USERS_FILE", tmp_path / "u.json")
        monkeypatch.setattr(web_app, "DATABASE_URL", None)
        r = await client.post("/api/onboard/create-org", json={
            "name": "County Hospital",
            "slug": "county-hospital",
            "admin_email": "admin@county.com",
            "admin_password": "AdminPass1!",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "org" in body

    async def test_check_slug_returns_available_in_file_mode(self, client):
        r = await client.get("/api/onboard/check-slug", params={"slug": "any-slug"})
        assert r.status_code == 200
        assert r.json()["available"] is True

    async def test_check_slug_rejects_bad_format(self, client):
        r = await client.get("/api/onboard/check-slug", params={"slug": "BAD SLUG!!"})
        assert r.status_code == 200
        assert r.json()["available"] is False

    async def test_invite_endpoints_require_db(self, client):
        r = await client.get("/api/invite/accept", params={"token": "tok"})
        assert r.status_code == 503
        r2 = await client.post("/api/invite/accept",
            json={"token": "tok", "password": "Password1!"})
        assert r2.status_code == 503


# ── PostgreSQL integration tests (skipped without DB) ─────────────────────────

@_NEEDS_DB
class TestDatabaseIsolation:
    """These tests prove RLS isolation at the database level.

    Each test creates two organizations and verifies that queries scoped
    to one org cannot see data from the other.
    """

    def _make_test_orgs(self):
        """Create two test organizations and return (org_a, org_b)."""
        from db import create_organization
        import uuid
        suffix = uuid.uuid4().hex[:8]
        org_a = create_organization(
            name=f"Hospital A {suffix}",
            slug=f"hospital-a-{suffix}",
            plan="trial",
        )
        org_b = create_organization(
            name=f"Hospital B {suffix}",
            slug=f"hospital-b-{suffix}",
            plan="trial",
        )
        return org_a, org_b

    def test_cross_tenant_user_list_is_blocked(self):
        """Users registered under org_a are not visible when querying as org_b."""
        from db import register_user_db, list_users
        import uuid
        org_a, org_b = self._make_test_orgs()
        email_a = f"user-{uuid.uuid4().hex[:6]}@hospital-a.com"
        err = register_user_db(str(org_a["id"]), email_a, "TestPass1!")
        assert err is None

        # Query from org_b — should return empty list (RLS blocks org_a rows)
        users_b = list_users(str(org_b["id"]))
        emails_b = [u["email"] for u in users_b]
        assert email_a not in emails_b, (
            f"Cross-tenant isolation failure: {email_a} visible in org_b user list"
        )

    def test_cross_tenant_plan_access_is_blocked(self):
        """Discharge plans inserted for org_a are not visible to org_b queries."""
        from db import org_scoped_cursor
        import uuid
        org_a, org_b = self._make_test_orgs()

        # Insert a discharge plan for org_a
        with org_scoped_cursor(str(org_a["id"])) as cur:
            cur.execute(
                "INSERT INTO discharge_plans (organization_id, patient_mrn)"
                " VALUES (%s, %s) RETURNING id",
                (str(org_a["id"]), "MRN-TEST-001"),
            )
            plan_id = cur.fetchone()["id"]

        # Query plans as org_b — must return nothing for this plan
        with org_scoped_cursor(str(org_b["id"])) as cur:
            cur.execute("SELECT id FROM discharge_plans WHERE id = %s", (str(plan_id),))
            row = cur.fetchone()
        assert row is None, (
            f"Cross-tenant isolation failure: plan {plan_id} from org_a visible in org_b"
        )

    def test_rls_blocks_query_without_org_context(self):
        """A raw query without SET LOCAL app.current_org_id must return zero rows
        (RLS policy returns NULL for missing setting, which casts to NULL != any UUID)."""
        from db import _get_conn, register_user_db
        import uuid
        org_a, _ = self._make_test_orgs()
        email = f"rls-test-{uuid.uuid4().hex[:6]}@test.com"
        register_user_db(str(org_a["id"]), email, "TestPass1!")

        conn = _get_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    # No SET LOCAL — RLS should block all rows
                    cur.execute("SELECT email FROM users WHERE email = %s", (email,))
                    row = cur.fetchone()
            assert row is None, (
                "RLS failure: row visible without app.current_org_id set"
            )
        finally:
            conn.close()

    def test_org_scoped_cursor_filters_correctly(self):
        """org_scoped_cursor returns only rows for the specified org."""
        from db import register_user_db, org_scoped_cursor
        import uuid
        org_a, org_b = self._make_test_orgs()
        email_a = f"scoped-{uuid.uuid4().hex[:6]}@org-a.com"
        email_b = f"scoped-{uuid.uuid4().hex[:6]}@org-b.com"
        register_user_db(str(org_a["id"]), email_a, "TestPass1!")
        register_user_db(str(org_b["id"]), email_b, "TestPass1!")

        with org_scoped_cursor(str(org_a["id"])) as cur:
            cur.execute("SELECT email FROM users WHERE email IN (%s, %s)", (email_a, email_b))
            rows = [r["email"] for r in cur.fetchall()]

        assert email_a in rows, "Own-org row missing"
        assert email_b not in rows, "Cross-org row leaked through RLS"

    def test_invalid_org_id_raises_value_error(self):
        """Passing a non-UUID string to org_scoped_cursor raises ValueError."""
        from db import org_scoped_cursor
        with pytest.raises(ValueError):
            with org_scoped_cursor("not-a-uuid") as _cur:
                pass
