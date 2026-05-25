"""Referral persistence layer — CRUD for post-acute referrals, delivery log, messages, and org settings."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from db.connection import get_db_conn

_log = logging.getLogger(__name__)


# ── JSON-safe helper (same pattern as db/roi.py) ─────────────────────────────

def _json_safe(obj):
    """Recursively convert DB-returned types (date, datetime, Decimal) to JSON primitives."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


# ── Referral CRUD ─────────────────────────────────────────────────────────────

def create_referral(patient_id: int, org_domain: str, created_by: str, referral_data: dict) -> dict:
    """INSERT a new referral row and return the created dict."""
    d = referral_data
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO referrals (
                        patient_id, org_domain, created_by,
                        facility_ccn, facility_name, facility_fax,
                        facility_email, facility_direct,
                        status, delivery_channel,
                        urgency, service_type, referral_notes,
                        clinician_confirmed
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s,
                        %s, %s, %s,
                        %s
                    )
                    RETURNING *
                    """,
                    (
                        patient_id, org_domain, created_by,
                        d.get("facility_ccn"), d.get("facility_name"), d.get("facility_fax"),
                        d.get("facility_email"), d.get("facility_direct"),
                        d.get("status", "draft"), d.get("delivery_channel"),
                        d.get("urgency", "routine"), d.get("service_type"), d.get("referral_notes"),
                        d.get("clinician_confirmed", False),
                    ),
                )
                row = cur.fetchone()
                return _json_safe(dict(row))
    finally:
        conn.close()


def get_referral(referral_id: int, org_domain: str) -> Optional[dict]:
    """SELECT a referral by id scoped to org_domain. Returns None if not found."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM referrals WHERE id = %s AND org_domain = %s",
                    (referral_id, org_domain),
                )
                row = cur.fetchone()
                return _json_safe(dict(row)) if row else None
    finally:
        conn.close()


def list_referrals(
    org_domain: str,
    patient_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """SELECT referrals for an org with optional patient_id and status filters."""
    conditions = ["org_domain = %s"]
    params: list = [org_domain]

    if patient_id is not None:
        conditions.append("patient_id = %s")
        params.append(patient_id)
    if status is not None:
        conditions.append("status = %s")
        params.append(status)

    where = " AND ".join(conditions)
    params.extend([limit, offset])

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM referrals WHERE {where} "
                    f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    params,
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


def update_referral_status(
    referral_id: int,
    org_domain: str,
    status: str,
    updated_by: str,
    notes: Optional[str] = None,
) -> Optional[dict]:
    """UPDATE referral status, append entry to status_history JSONB, return updated row."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Fetch current status_history to append
                cur.execute(
                    "SELECT status, status_history FROM referrals WHERE id = %s AND org_domain = %s",
                    (referral_id, org_domain),
                )
                row = cur.fetchone()
                if not row:
                    return None

                old_status = row["status"]
                existing_history = row["status_history"] or []
                if isinstance(existing_history, str):
                    existing_history = json.loads(existing_history)

                history_entry = {
                    "from": old_status,
                    "to": status,
                    "updated_by": updated_by,
                    "at": datetime.utcnow().isoformat() + "Z",
                }
                if notes:
                    history_entry["notes"] = notes
                existing_history.append(history_entry)

                # Set accepted_at when transitioning to accepted
                accepted_at_clause = ""
                if status == "accepted":
                    accepted_at_clause = ", accepted_at = NOW()"

                cur.execute(
                    f"""
                    UPDATE referrals
                    SET status = %s,
                        status_updated_at = NOW(),
                        status_history = %s::jsonb,
                        updated_at = NOW()
                        {accepted_at_clause}
                    WHERE id = %s AND org_domain = %s
                    RETURNING *
                    """,
                    (status, json.dumps(existing_history), referral_id, org_domain),
                )
                updated = cur.fetchone()
                return _json_safe(dict(updated)) if updated else None
    finally:
        conn.close()


def log_delivery_attempt(
    referral_id: int,
    channel: str,
    success: bool,
    reference_id: Optional[str],
    error_msg: Optional[str],
) -> int:
    """INSERT a delivery attempt record. Returns the new row id.

    HIPAA: logs only referral_id, channel, success/fail, reference_id — never PHI.
    """
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO referral_delivery_log
                        (referral_id, channel, success, reference_id, error_message)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (referral_id, channel, success, reference_id, error_msg),
                )
                new_id = cur.fetchone()["id"]
                _log.info(
                    "delivery_attempt referral_id=%s channel=%s success=%s reference_id=%s",
                    referral_id, channel, success, reference_id,
                )
                return new_id
    finally:
        conn.close()


def get_delivery_log(referral_id: int) -> list[dict]:
    """SELECT all delivery log entries for a referral."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM referral_delivery_log WHERE referral_id = %s ORDER BY attempted_at ASC",
                    (referral_id,),
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


def get_referral_analytics(org_domain: str, days: int = 90) -> dict:
    """Aggregate referral metrics for an org over the past N days.

    Returns: total, by_status, by_channel, avg_time_to_accept_hours, by_facility.
    """
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Total referrals
                cur.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM referrals
                    WHERE org_domain = %s
                      AND created_at >= NOW() - INTERVAL '1 day' * %s
                    """,
                    (org_domain, days),
                )
                total = cur.fetchone()["total"]

                # By status
                cur.execute(
                    """
                    SELECT status, COUNT(*) AS cnt
                    FROM referrals
                    WHERE org_domain = %s
                      AND created_at >= NOW() - INTERVAL '1 day' * %s
                    GROUP BY status
                    ORDER BY cnt DESC
                    """,
                    (org_domain, days),
                )
                by_status = {r["status"]: r["cnt"] for r in cur.fetchall()}

                # By delivery channel
                cur.execute(
                    """
                    SELECT COALESCE(delivery_channel, 'unset') AS channel, COUNT(*) AS cnt
                    FROM referrals
                    WHERE org_domain = %s
                      AND created_at >= NOW() - INTERVAL '1 day' * %s
                    GROUP BY delivery_channel
                    ORDER BY cnt DESC
                    """,
                    (org_domain, days),
                )
                by_channel = {r["channel"]: r["cnt"] for r in cur.fetchall()}

                # Average time to accept (hours)
                cur.execute(
                    """
                    SELECT ROUND(
                        AVG(EXTRACT(EPOCH FROM (accepted_at - sent_at)) / 3600.0)::numeric,
                        2
                    ) AS avg_hours
                    FROM referrals
                    WHERE org_domain = %s
                      AND accepted_at IS NOT NULL
                      AND sent_at IS NOT NULL
                      AND created_at >= NOW() - INTERVAL '1 day' * %s
                    """,
                    (org_domain, days),
                )
                avg_row = cur.fetchone()
                avg_time_to_accept_hours = float(avg_row["avg_hours"]) if avg_row["avg_hours"] else None

                # By facility (top facilities by referral count)
                cur.execute(
                    """
                    SELECT
                        COALESCE(facility_ccn, 'unknown') AS facility_ccn,
                        COALESCE(facility_name, 'Unknown') AS facility_name,
                        COUNT(*) AS cnt,
                        SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) AS accepted
                    FROM referrals
                    WHERE org_domain = %s
                      AND created_at >= NOW() - INTERVAL '1 day' * %s
                    GROUP BY facility_ccn, facility_name
                    ORDER BY cnt DESC
                    LIMIT 20
                    """,
                    (org_domain, days),
                )
                by_facility = _json_safe([dict(r) for r in cur.fetchall()])

                return {
                    "org_domain": org_domain,
                    "days": days,
                    "total": total,
                    "by_status": by_status,
                    "by_channel": by_channel,
                    "avg_time_to_accept_hours": avg_time_to_accept_hours,
                    "by_facility": by_facility,
                }
    finally:
        conn.close()


# ── Org referral settings ─────────────────────────────────────────────────────

def get_org_referral_settings(org_domain: str) -> dict:
    """Return org referral settings, or defaults if not yet configured."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM org_referral_settings WHERE org_domain = %s",
                    (org_domain,),
                )
                row = cur.fetchone()
                if row:
                    return _json_safe(dict(row))
                return {
                    "org_domain": org_domain,
                    "default_channel": "fax",
                    "documo_enabled": False,
                    "careport_enabled": False,
                    "direct_enabled": False,
                    "fax_cover_header": None,
                    "org_name": None,
                    "org_fax": None,
                    "org_npi": None,
                    "org_address": None,
                }
    finally:
        conn.close()


def upsert_org_referral_settings(org_domain: str, settings: dict) -> dict:
    """Create or update org referral settings."""
    allowed = {
        "default_channel", "documo_enabled", "careport_enabled", "direct_enabled",
        "fax_cover_header", "org_name", "org_fax", "org_npi", "org_address",
    }
    filtered = {k: v for k, v in settings.items() if k in allowed}
    if not filtered:
        return get_org_referral_settings(org_domain)

    set_clauses = ", ".join(f"{k} = %s" for k in filtered)
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO org_referral_settings (org_domain, {", ".join(filtered)})
                    VALUES (%s, {", ".join(["%s"] * len(filtered))})
                    ON CONFLICT (org_domain) DO UPDATE SET
                        {set_clauses},
                        updated_at = NOW()
                    RETURNING *
                    """,
                    [org_domain] + list(filtered.values()) + list(filtered.values()),
                )
                row = cur.fetchone()
                return _json_safe(dict(row)) if row else get_org_referral_settings(org_domain)
    finally:
        conn.close()


# ── Referral messages ─────────────────────────────────────────────────────────

def add_referral_message(
    referral_id: int,
    org_domain: str,
    author_email: str,
    message_text: str,
) -> dict:
    """INSERT a message on a referral thread and return the created row."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO referral_messages
                        (referral_id, org_domain, author_email, message_text)
                    VALUES (%s, %s, %s, %s)
                    RETURNING *
                    """,
                    (referral_id, org_domain, author_email, message_text),
                )
                row = cur.fetchone()
                return _json_safe(dict(row))
    finally:
        conn.close()


def get_referral_messages(referral_id: int, org_domain: str) -> list[dict]:
    """SELECT all messages for a referral, scoped to org_domain."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM referral_messages
                    WHERE referral_id = %s AND org_domain = %s
                    ORDER BY created_at ASC
                    """,
                    (referral_id, org_domain),
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


# ── Migrations ────────────────────────────────────────────────────────────────

def run_referral_migrations() -> None:
    """CREATE TABLE IF NOT EXISTS for all referral tables and indexes."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS referrals (
            id                   SERIAL PRIMARY KEY,
            patient_id           INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
            org_domain           VARCHAR(255) NOT NULL,
            created_by           VARCHAR(255) NOT NULL,
            facility_ccn         VARCHAR(20),
            facility_name        VARCHAR(300),
            facility_fax         VARCHAR(30),
            facility_email       VARCHAR(255),
            facility_direct      VARCHAR(255),
            status               VARCHAR(30) DEFAULT 'draft',
            delivery_channel     VARCHAR(30),
            packet_html          TEXT,
            fhir_service_request JSONB,
            urgency              VARCHAR(20) DEFAULT 'routine',
            service_type         VARCHAR(100),
            referral_notes       TEXT,
            clinician_confirmed  BOOLEAN DEFAULT FALSE,
            confirmed_by         VARCHAR(255),
            confirmed_at         TIMESTAMPTZ,
            sent_at              TIMESTAMPTZ,
            status_updated_at    TIMESTAMPTZ,
            accepted_at          TIMESTAMPTZ,
            status_history       JSONB DEFAULT '[]',
            created_at           TIMESTAMPTZ DEFAULT NOW(),
            updated_at           TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS referral_delivery_log (
            id           SERIAL PRIMARY KEY,
            referral_id  INTEGER NOT NULL REFERENCES referrals(id) ON DELETE CASCADE,
            channel      VARCHAR(30) NOT NULL,
            attempted_at TIMESTAMPTZ DEFAULT NOW(),
            success      BOOLEAN NOT NULL,
            reference_id VARCHAR(200),
            error_message TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS referral_messages (
            id           SERIAL PRIMARY KEY,
            referral_id  INTEGER NOT NULL REFERENCES referrals(id) ON DELETE CASCADE,
            org_domain   VARCHAR(255) NOT NULL,
            author_email VARCHAR(255) NOT NULL,
            message_text TEXT NOT NULL,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS org_referral_settings (
            org_domain       VARCHAR(255) PRIMARY KEY,
            default_channel  VARCHAR(30) DEFAULT 'fax',
            documo_enabled   BOOLEAN DEFAULT FALSE,
            careport_enabled BOOLEAN DEFAULT FALSE,
            direct_enabled   BOOLEAN DEFAULT FALSE,
            fax_cover_header VARCHAR(300),
            org_name         VARCHAR(200),
            org_fax          VARCHAR(30),
            org_npi          VARCHAR(20),
            org_address      TEXT,
            created_at       TIMESTAMPTZ DEFAULT NOW(),
            updated_at       TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_referrals_org ON referrals(org_domain)",
        "CREATE INDEX IF NOT EXISTS idx_referrals_patient ON referrals(patient_id)",
        "CREATE INDEX IF NOT EXISTS idx_referrals_status ON referrals(status)",
        "CREATE INDEX IF NOT EXISTS idx_referral_delivery_referral ON referral_delivery_log(referral_id)",
        "CREATE INDEX IF NOT EXISTS idx_referral_messages_referral ON referral_messages(referral_id)",
        "ALTER TABLE patients ADD COLUMN IF NOT EXISTS snf_referral_status VARCHAR(30)",
    ]

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                for stmt in statements:
                    s = stmt.strip()
                    if s:
                        cur.execute(s)
    finally:
        conn.close()
