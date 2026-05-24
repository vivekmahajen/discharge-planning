"""Discharge milestone and barrier tracking persistence layer."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from db.connection import get_db_conn
from db.milestones_catalog import BARRIER_CATALOG

_log = logging.getLogger(__name__)

VALID_STATUSES = ("open", "in_progress", "blocked", "resolved", "dismissed", "cancelled")
VALID_PRIORITIES = ("critical", "high", "medium", "low")
CA_SPECIFIC_TYPES = {"medi_cal_eligibility_issue", "calaim_care_mgmt_pending",
                     "livanta_notice_not_issued", "snf_auth_pending"}


def run_milestone_migrations() -> None:
    """Create discharge milestone tables if they don't exist."""
    sql = """
CREATE TABLE IF NOT EXISTS discharge_milestones (
    id              SERIAL PRIMARY KEY,
    patient_id      INTEGER      NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    org_domain      VARCHAR(255) NOT NULL,
    barrier_type    VARCHAR(80)  NOT NULL,
    category        VARCHAR(40)  NOT NULL,
    label           VARCHAR(200) NOT NULL,
    description     TEXT,
    status          VARCHAR(30)  NOT NULL DEFAULT 'open',
    assigned_to     VARCHAR(255),
    due_date        TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    dismissed_at    TIMESTAMPTZ,
    dismissed_reason TEXT,
    source          VARCHAR(30)  DEFAULT 'manual',
    run_id          INTEGER      REFERENCES plan_runs(id) ON DELETE SET NULL,
    ai_confidence   FLOAT,
    ai_evidence     TEXT,
    priority        VARCHAR(10)  DEFAULT 'medium',
    is_ca_specific  BOOLEAN      DEFAULT FALSE,
    created_by      VARCHAR(255) NOT NULL,
    created_at      TIMESTAMPTZ  DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  DEFAULT NOW(),
    notes           TEXT
);
CREATE TABLE IF NOT EXISTS milestone_history (
    id              SERIAL PRIMARY KEY,
    milestone_id    INTEGER      NOT NULL REFERENCES discharge_milestones(id) ON DELETE CASCADE,
    old_status      VARCHAR(30),
    new_status      VARCHAR(30)  NOT NULL,
    changed_by      VARCHAR(255) NOT NULL,
    changed_at      TIMESTAMPTZ  DEFAULT NOW(),
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_milestones_patient    ON discharge_milestones(patient_id);
CREATE INDEX IF NOT EXISTS idx_milestones_org        ON discharge_milestones(org_domain);
CREATE INDEX IF NOT EXISTS idx_milestones_status     ON discharge_milestones(status);
CREATE INDEX IF NOT EXISTS idx_milestones_due        ON discharge_milestones(due_date);
CREATE INDEX IF NOT EXISTS idx_milestone_history_mid ON milestone_history(milestone_id)
"""
    try:
        conn = get_db_conn()
        try:
            with conn:
                with conn.cursor() as cur:
                    for statement in sql.strip().split(';'):
                        s = statement.strip()
                        if s:
                            cur.execute(s)
        finally:
            conn.close()
    except Exception as e:
        _log.warning("Milestone migrations skipped (no DB?): %s", e)


def _serialize_row(row: dict) -> dict:
    """Convert datetime/date values in a row dict to ISO strings."""
    result = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            result[k] = v.isoformat()
        else:
            result[k] = v
    return result


def _enrich_row(row: dict) -> dict:
    """Add is_overdue and hours_until_due to a milestone row dict."""
    now = datetime.now(timezone.utc)
    due_date = row.get("due_date")
    status = row.get("status", "")

    # due_date may be a datetime or an ISO string (after serialization)
    if due_date is not None and isinstance(due_date, str):
        from datetime import datetime as dt
        try:
            due_date = dt.fromisoformat(due_date)
        except ValueError:
            due_date = None

    active = status not in ("resolved", "dismissed", "cancelled")
    is_overdue = bool(active and due_date is not None and due_date < now)
    hours_until_due = (
        (due_date - now).total_seconds() / 3600 if due_date is not None else None
    )

    serialized = _serialize_row(row)
    serialized["is_overdue"] = is_overdue
    serialized["hours_until_due"] = hours_until_due
    return serialized


def create_milestone(
    patient_id: int,
    org_domain: str,
    barrier_type: str,
    created_by: str,
    description: str = "",
    priority: str = "medium",
    assigned_to: Optional[str] = None,
    due_date: Optional[datetime] = None,
    source: str = "manual",
    run_id: Optional[int] = None,
    ai_confidence: Optional[float] = None,
    ai_evidence: Optional[str] = None,
) -> dict:
    catalog_entry = BARRIER_CATALOG.get(barrier_type, BARRIER_CATALOG["custom"])
    label = catalog_entry["label"]
    category = catalog_entry["category"]

    if due_date is None:
        due_date = datetime.now(timezone.utc) + timedelta(hours=catalog_entry["default_sla_hours"])

    is_ca_specific = barrier_type in CA_SPECIFIC_TYPES

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO discharge_milestones (
                        patient_id, org_domain, barrier_type, category, label, description,
                        status, assigned_to, due_date, source, run_id, ai_confidence,
                        ai_evidence, priority, is_ca_specific, created_by, notes
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        'open', %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, NULL
                    ) RETURNING *
                    """,
                    (
                        patient_id, org_domain, barrier_type, category, label, description,
                        assigned_to, due_date, source, run_id, ai_confidence,
                        ai_evidence, priority, is_ca_specific, created_by,
                    ),
                )
                return dict(cur.fetchone())
    finally:
        conn.close()


def get_milestones_for_patient(
    patient_id: int,
    org_domain: str,
    include_resolved: bool = False,
) -> list[dict]:
    base_sql = """
        SELECT * FROM discharge_milestones
        WHERE patient_id=%s AND org_domain=%s
    """
    if not include_resolved:
        base_sql += " AND status NOT IN ('resolved','dismissed','cancelled')"

    base_sql += """
        ORDER BY
            is_ca_specific DESC,
            CASE priority
                WHEN 'critical' THEN 0
                WHEN 'high'     THEN 1
                WHEN 'medium'   THEN 2
                WHEN 'low'      THEN 3
            END ASC,
            due_date ASC NULLS LAST
    """

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(base_sql, (patient_id, org_domain))
                rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    return [_enrich_row(row) for row in rows]


def get_open_milestone_count(patient_id: int, org_domain: str) -> dict:
    sql = """
        SELECT
            COUNT(*) FILTER (WHERE status IN ('open','in_progress','blocked')) AS total_open,
            COUNT(*) FILTER (WHERE status IN ('open','in_progress','blocked') AND due_date < NOW()) AS overdue,
            COUNT(*) FILTER (WHERE priority='critical' AND status IN ('open','in_progress','blocked')) AS critical,
            COUNT(*) FILTER (WHERE is_ca_specific=TRUE AND status IN ('open','in_progress','blocked')) AS ca_specific
        FROM discharge_milestones WHERE patient_id=%s AND org_domain=%s
    """
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, (patient_id, org_domain))
                row = cur.fetchone()
                if row:
                    return {
                        "total_open": int(row["total_open"] or 0),
                        "overdue": int(row["overdue"] or 0),
                        "critical": int(row["critical"] or 0),
                        "ca_specific": int(row["ca_specific"] or 0),
                    }
                return {"total_open": 0, "overdue": 0, "critical": 0, "ca_specific": 0}
    finally:
        conn.close()


def get_org_milestone_summary(org_domain: str) -> dict:
    sql = """
        SELECT dm.*, p.patient_name, p.mrn
        FROM discharge_milestones dm
        JOIN patients p ON p.id = dm.patient_id
        WHERE dm.org_domain=%s AND dm.status IN ('open','in_progress','blocked')
    """
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, (org_domain,))
                rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    now = datetime.now(timezone.utc)
    total_open = len(rows)
    overdue = sum(
        1 for r in rows if r.get("due_date") is not None and r["due_date"] < now
    )

    by_category: dict[str, int] = {}
    for r in rows:
        cat = r.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + 1

    # Group by patient
    patient_map: dict[int, dict] = {}
    for r in rows:
        pid = r["patient_id"]
        if pid not in patient_map:
            patient_map[pid] = {
                "patient_id": pid,
                "patient_name": r.get("patient_name", ""),
                "mrn": r.get("mrn", ""),
                "overdue": 0,
                "total": 0,
            }
        patient_map[pid]["total"] += 1
        if r.get("due_date") is not None and r["due_date"] < now:
            patient_map[pid]["overdue"] += 1

    by_patient = sorted(patient_map.values(), key=lambda x: x["overdue"], reverse=True)

    return {
        "total_open": total_open,
        "overdue": overdue,
        "by_category": by_category,
        "by_patient": by_patient,
    }


def update_milestone(
    milestone_id: int,
    org_domain: str,
    updated_by: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    due_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    dismiss_reason: Optional[str] = None,
) -> Optional[dict]:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Verify milestone exists and belongs to org
                cur.execute(
                    "SELECT * FROM discharge_milestones WHERE id=%s AND org_domain=%s",
                    (milestone_id, org_domain),
                )
                existing = cur.fetchone()
                if not existing:
                    return None
                existing = dict(existing)

                set_clauses = ["updated_at=NOW()"]
                params: list = []

                if status is not None:
                    set_clauses.append("status=%s")
                    params.append(status)
                    if status == "resolved":
                        set_clauses.append("resolved_at=NOW()")
                    elif status == "dismissed":
                        set_clauses.append("dismissed_at=NOW()")
                        set_clauses.append("dismissed_reason=%s")
                        params.append(dismiss_reason)

                if priority is not None:
                    set_clauses.append("priority=%s")
                    params.append(priority)

                if assigned_to is not None:
                    set_clauses.append("assigned_to=%s")
                    params.append(assigned_to)

                if due_date is not None:
                    set_clauses.append("due_date=%s")
                    params.append(due_date)

                if notes is not None:
                    set_clauses.append("notes=%s")
                    params.append(notes)

                params.append(milestone_id)
                params.append(org_domain)

                cur.execute(
                    f"UPDATE discharge_milestones SET {', '.join(set_clauses)} "
                    f"WHERE id=%s AND org_domain=%s RETURNING *",
                    params,
                )
                updated = cur.fetchone()

                # Record history if status changed
                if status is not None and status != existing.get("status"):
                    cur.execute(
                        """
                        INSERT INTO milestone_history (milestone_id, old_status, new_status, changed_by, changed_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        """,
                        (milestone_id, existing.get("status"), status, updated_by),
                    )

                return dict(updated) if updated else None
    finally:
        conn.close()


def bulk_create_milestones(
    patient_id: int,
    org_domain: str,
    barriers: list[dict],
    created_by: str,
    run_id: Optional[int] = None,
) -> list[dict]:
    created = []
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                for barrier in barriers:
                    barrier_type = barrier.get("barrier_type", "custom")

                    # Check for existing open/in_progress/blocked milestone of same type
                    cur.execute(
                        """
                        SELECT id FROM discharge_milestones
                        WHERE patient_id=%s AND barrier_type=%s
                          AND status NOT IN ('resolved','dismissed','cancelled')
                        """,
                        (patient_id, barrier_type),
                    )
                    if cur.fetchone():
                        continue  # Already exists, skip

                    catalog_entry = BARRIER_CATALOG.get(barrier_type, BARRIER_CATALOG["custom"])
                    label = catalog_entry["label"]
                    category = catalog_entry["category"]
                    priority = barrier.get("priority", "medium")
                    description = barrier.get("description", "")
                    ai_confidence = barrier.get("ai_confidence")
                    ai_evidence = barrier.get("ai_evidence")
                    due_date = datetime.now(timezone.utc) + timedelta(hours=catalog_entry["default_sla_hours"])
                    is_ca_specific = barrier_type in CA_SPECIFIC_TYPES

                    cur.execute(
                        """
                        INSERT INTO discharge_milestones (
                            patient_id, org_domain, barrier_type, category, label, description,
                            status, due_date, source, run_id, ai_confidence, ai_evidence,
                            priority, is_ca_specific, created_by
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s,
                            'open', %s, 'ai_extracted', %s, %s, %s,
                            %s, %s, %s
                        ) RETURNING *
                        """,
                        (
                            patient_id, org_domain, barrier_type, category, label, description,
                            due_date, run_id, ai_confidence, ai_evidence,
                            priority, is_ca_specific, created_by,
                        ),
                    )
                    row = cur.fetchone()
                    if row:
                        created.append(dict(row))
    finally:
        conn.close()

    return created


def get_milestone_by_id(milestone_id: int, org_domain: str) -> Optional[dict]:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM discharge_milestones WHERE id=%s AND org_domain=%s",
                    (milestone_id, org_domain),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _enrich_row(dict(row))
    finally:
        conn.close()


def delete_milestone(milestone_id: int, org_domain: str, deleted_by: str) -> bool:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT source, org_domain FROM discharge_milestones WHERE id=%s",
                    (milestone_id,),
                )
                row = cur.fetchone()
                if not row:
                    return False
                if row["source"] != "manual":
                    return False  # AI barriers must be dismissed, not deleted
                if row["org_domain"] != org_domain:
                    return False

                cur.execute(
                    "DELETE FROM discharge_milestones WHERE id=%s AND org_domain=%s AND source='manual'",
                    (milestone_id, org_domain),
                )
                return cur.rowcount > 0
    finally:
        conn.close()
