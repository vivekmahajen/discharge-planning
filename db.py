"""Org-scoped database layer for multi-tenant discharge planning.

All tenant queries must go through org_scoped_cursor() which sets the
PostgreSQL session variable app.current_org_id before any query runs.
This variable is read by the RLS policies defined in migrations/001_multi_tenant_base.sql.

HIPAA 45 CFR 164.312(a)(1) — Access control
ONC 170.315(g)(10) — Per-org data isolation
"""
from __future__ import annotations

import hashlib
import os
import secrets
from contextlib import contextmanager
from typing import Any


def _get_conn():  # pragma: no cover
    import psycopg2
    import psycopg2.extras
    return psycopg2.connect(
        os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


@contextmanager
def org_scoped_cursor(org_id: str):  # pragma: no cover
    """Context manager that opens a connection, sets RLS org variable, yields cursor.

    The SET LOCAL is transaction-scoped so cross-connection leakage is impossible.
    """
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Validate that org_id is a valid UUID before injection into SQL
                import uuid as _uuid
                _uuid.UUID(org_id)  # raises ValueError if not a valid UUID
                cur.execute("SET LOCAL app.current_org_id = %s", (org_id,))
                yield cur
    finally:
        conn.close()


# ── Organizations ─────────────────────────────────────────────────────────────

def create_organization(name: str, slug: str, domain: str | None = None,
                        plan: str = "trial") -> dict:  # pragma: no cover
    """Create a new organization and return its row as a dict."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO organizations (name, slug, domain, plan)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (name, slug, domain, plan),
                )
                return dict(cur.fetchone())
    finally:
        conn.close()


def get_organization_by_id(org_id: str) -> dict | None:  # pragma: no cover
    """Fetch an organization by UUID. Returns None if not found."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM organizations WHERE id = %s AND active = TRUE",
                    (org_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    finally:
        conn.close()


def get_organization_by_slug(slug: str) -> dict | None:  # pragma: no cover
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM organizations WHERE slug = %s AND active = TRUE",
                    (slug,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    finally:
        conn.close()


def get_organization_by_domain(domain: str) -> dict | None:  # pragma: no cover
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM organizations WHERE domain = %s AND active = TRUE",
                    (domain,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    finally:
        conn.close()


def list_all_organizations() -> list[dict]:  # pragma: no cover
    """Superadmin: list every organization."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM organizations ORDER BY created_at DESC")
                return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def slug_exists(slug: str) -> bool:  # pragma: no cover
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM organizations WHERE slug = %s", (slug,))
                return cur.fetchone() is not None
    finally:
        conn.close()


# ── Users ─────────────────────────────────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return dk.hex()


def register_user_db(org_id: str, email: str, password: str,
                     role: str = "clinician") -> str | None:  # pragma: no cover
    """Insert a new user into the org-scoped users table.

    Returns None on success, error string on failure.
    """
    import psycopg2
    salt = secrets.token_hex(16)
    pw_hash = _hash_password(password, salt)
    try:
        with org_scoped_cursor(org_id) as cur:
            cur.execute(
                """
                INSERT INTO users (organization_id, email, salt, hash, role)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (org_id, email, salt, pw_hash, role),
            )
    except psycopg2.errors.UniqueViolation:
        return "An account with this email already exists."
    return None


def authenticate_user_db(org_id: str, email: str,
                         password: str) -> str | None:  # pragma: no cover
    """Verify credentials for a user within an org.

    Returns None if valid, error string if not.
    """
    import secrets as _sec
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT salt, hash FROM users WHERE email = %s AND organization_id = %s"
            " AND active = TRUE AND deleted_at IS NULL",
            (email, org_id),
        )
        row = cur.fetchone()
    if not row:
        return "No account found with this email. Please sign up first."
    if not _sec.compare_digest(_hash_password(password, row["salt"]), row["hash"]):
        return "Incorrect password."
    return None


def get_user_by_email(org_id: str, email: str) -> dict | None:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT * FROM users WHERE email = %s AND organization_id = %s"
            " AND deleted_at IS NULL",
            (email, org_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def list_users(org_id: str) -> list[dict]:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT id, email, role, active, created_at, last_login_at"
            " FROM users WHERE organization_id = %s AND deleted_at IS NULL"
            " ORDER BY email",
            (org_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def update_user_role(org_id: str, user_id: str, role: str) -> None:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "UPDATE users SET role = %s WHERE id = %s AND organization_id = %s",
            (role, user_id, org_id),
        )


def deactivate_user(org_id: str, user_id: str) -> None:  # pragma: no cover
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "UPDATE users SET deleted_at = %s, active = FALSE"
            " WHERE id = %s AND organization_id = %s",
            (now, user_id, org_id),
        )


# ── Invitations ───────────────────────────────────────────────────────────────

def create_invitation(org_id: str, email: str, role: str,
                      invited_by_id: str | None = None) -> dict:  # pragma: no cover
    """Create a signed invite token. Returns the invitation row."""
    token = secrets.token_urlsafe(32)
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            """
            INSERT INTO invitations (organization_id, email, role, token, invited_by)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (org_id, email, role, token, invited_by_id),
        )
        return dict(cur.fetchone())


def get_invitation_by_token(token: str) -> dict | None:  # pragma: no cover
    """Fetch an invitation by token (no RLS needed — token is the credential)."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT i.*, o.name AS org_name, o.slug AS org_slug
                    FROM invitations i
                    JOIN organizations o ON o.id = i.organization_id
                    WHERE i.token = %s
                      AND i.accepted_at IS NULL
                      AND i.expires_at > NOW()
                    """,
                    (token,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    finally:
        conn.close()


def mark_invitation_accepted(token: str) -> None:  # pragma: no cover
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE invitations SET accepted_at = NOW() WHERE token = %s",
                    (token,),
                )
    finally:
        conn.close()


# ── Audit log ─────────────────────────────────────────────────────────────────

def write_audit_log(org_id: str | None, user_hash: str, endpoint: str,
                    method: str, status: int, ip: str) -> None:  # pragma: no cover
    """Write an audit entry scoped to an organization."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log
                        (organization_id, user_hash, endpoint, method, status, ip)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (org_id, user_hash, endpoint, method, status, ip),
                )
    finally:
        conn.close()


def get_audit_log(org_id: str, limit: int = 500) -> list[dict]:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT * FROM audit_log WHERE organization_id = %s"
            " ORDER BY ts DESC LIMIT %s",
            (org_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]
