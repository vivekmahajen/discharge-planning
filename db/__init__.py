"""Org-scoped database layer for multi-tenant discharge planning.

All tenant queries must go through org_scoped_cursor() which sets the
PostgreSQL session variable app.current_org_id before any query runs.
This variable is read by the RLS policies defined in migrations/001_multi_tenant_base.sql.

HIPAA 45 CFR 164.312(a)(1) — Access control
ONC 170.315(g)(10) — Per-org data isolation
"""
from __future__ import annotations

import hashlib
import json
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


# ── SSO user functions ────────────────────────────────────────────────────────

def get_user_by_email_global(email: str) -> dict | None:  # pragma: no cover
    """Look up a user by email across all orgs — used for SSO login."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT organization_id, email, role FROM users "
                    "WHERE email = %s AND deleted_at IS NULL LIMIT 1",
                    (email,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
    finally:
        conn.close()


def provision_sso_user(email: str, org_id: str, role: str = "clinician") -> None:  # pragma: no cover
    """Insert a password-less user for first-time SSO login. No-op if already exists."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (organization_id, email, salt, hash, role, sso_provider) "
                    "VALUES (%s, %s, NULL, NULL, %s, 'auth0') "
                    "ON CONFLICT (email) DO NOTHING",
                    (org_id, email, role),
                )
    finally:
        conn.close()


# ── Audit log ─────────────────────────────────────────────────────────────────

def write_audit_log(org_id: str | None, user_email: str | None, endpoint: str,
                    method: str, status: int, ip: str,
                    mrn: str | None = None) -> None:  # pragma: no cover
    """Write a HIPAA audit entry: who (user_email), what (endpoint+mrn), when (ts), where (ip)."""
    conn = _get_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_log
                        (organization_id, user_email, endpoint, method, status, ip, mrn)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (org_id, user_email, endpoint, method, status, ip, mrn),
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


# ── TCM Billing functions ─────────────────────────────────────────────────────

def create_tcm_episode(org_id: str, data: dict) -> str:  # pragma: no cover
    """Insert a new TCM episode. Returns the episode UUID as a string."""
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            """
            INSERT INTO tcm_episodes (
                organization_id, patient_mrn, patient_name, patient_dob,
                patient_medicare_id, discharge_date, discharge_setting,
                admitting_diagnosis, discharge_diagnosis,
                attending_provider_npi, attending_provider_name,
                practice_tin, practice_npi,
                recommended_cpt, mdm_complexity, mdm_rationale,
                mdm_rationale_json, mdm_assessed_by, status, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING id
            """,
            (
                org_id,
                data["patient_mrn"],
                data["patient_name"],
                data.get("patient_dob"),
                data.get("patient_medicare_id"),
                data["discharge_date"],
                data["discharge_setting"],
                data.get("admitting_diagnosis", "Not provided"),
                data["discharge_diagnosis"],
                data["attending_provider_npi"],
                data["attending_provider_name"],
                data.get("practice_tin"),
                data.get("practice_npi"),
                data.get("recommended_cpt"),
                data.get("mdm_complexity"),
                data.get("mdm_rationale"),
                data.get("mdm_rationale_json"),
                data.get("mdm_assessed_by", "ai_assisted"),
                data.get("status", "pending_contact"),
                data.get("created_by"),
            ),
        )
        return str(cur.fetchone()["id"])


def update_episode_status(org_id: str, episode_id: str,
                          status: str) -> None:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "UPDATE tcm_episodes SET status = %s, updated_at = NOW()"
            " WHERE id = %s AND organization_id = %s",
            (status, episode_id, org_id),
        )


def get_tcm_episode(org_id: str, episode_id: str) -> dict | None:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT * FROM tcm_episodes WHERE id = %s AND organization_id = %s",
            (episode_id, org_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_active_tcm_episodes(org_id: str) -> list[dict]:  # pragma: no cover
    """Return all non-terminal episodes for the dashboard."""
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            """
            SELECT * FROM tcm_episodes
            WHERE organization_id = %s
              AND status NOT IN ('claim_paid', 'claim_denied', 'not_eligible')
            ORDER BY discharge_date DESC
            """,
            (org_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_claim_ready_episodes(org_id: str) -> list[dict]:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT * FROM tcm_episodes WHERE organization_id = %s AND status = 'claim_ready'"
            " ORDER BY discharge_date",
            (org_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def create_tcm_contact(org_id: str, episode_id: str,
                       data: dict) -> str:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            """
            INSERT INTO tcm_contacts (
                episode_id, organization_id, contact_date, contact_time,
                contact_method, contact_result, contacted_by,
                contacted_by_id, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                episode_id, org_id,
                data["contact_date"], data["contact_time"],
                data["contact_method"], data["contact_result"],
                data["contacted_by"], data.get("contacted_by_id"),
                data.get("notes"),
            ),
        )
        return str(cur.fetchone()["id"])


def get_tcm_contacts(org_id: str, episode_id: str) -> list[dict]:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT * FROM tcm_contacts WHERE episode_id = %s AND organization_id = %s"
            " ORDER BY contact_date, contact_time",
            (episode_id, org_id),
        )
        return [dict(r) for r in cur.fetchall()]


def create_tcm_visit(org_id: str, episode_id: str,
                     data: dict) -> str:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            """
            INSERT INTO tcm_visits (
                episode_id, organization_id, visit_date, visit_type,
                provider_npi, provider_name, visit_notes, time_spent_mins
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                episode_id, org_id,
                data["visit_date"], data["visit_type"],
                data["provider_npi"], data["provider_name"],
                data.get("visit_notes"), data.get("time_spent_mins"),
            ),
        )
        return str(cur.fetchone()["id"])


def get_tcm_visits(org_id: str, episode_id: str) -> list[dict]:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            "SELECT * FROM tcm_visits WHERE episode_id = %s AND organization_id = %s"
            " ORDER BY visit_date",
            (episode_id, org_id),
        )
        return [dict(r) for r in cur.fetchall()]


def save_tcm_claim(org_id: str, episode_id: str,
                   claim: dict) -> str:  # pragma: no cover
    with org_scoped_cursor(org_id) as cur:
        cur.execute(
            """
            INSERT INTO tcm_claims (
                episode_id, organization_id, cpt_code, icd10_primary,
                icd10_additional, service_date, date_of_discharge,
                place_of_service, rendering_provider_npi, billing_provider_npi,
                billing_provider_tin, claim_amount, audit_trail
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                episode_id, org_id,
                claim["cpt_code"],
                claim["icd10_primary"],
                claim.get("icd10_secondary", []),
                claim["date_of_service"],
                claim["date_of_discharge"],
                claim.get("place_of_service", "11"),
                claim["rendering_provider_npi"],
                claim["billing_provider_npi"],
                claim["billing_provider_tin"],
                claim.get("charge_amount", 0),
                json.dumps(claim.get("audit_trail", {})),
            ),
        )
        return str(cur.fetchone()["id"])

