"""Patient persistence layer."""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from typing import Optional
from db.connection import get_db_conn

_log = logging.getLogger(__name__)

VALID_STATUSES = {"active", "pending_discharge", "discharged", "readmitted"}


def get_org_domain(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else "unknown"


def run_migrations() -> None:
    """Create patient persistence tables if they don't exist."""
    sql = """
    CREATE TABLE IF NOT EXISTS patients (
        id              SERIAL PRIMARY KEY,
        mrn             VARCHAR(50)  NOT NULL,
        admission_date  DATE         NOT NULL,
        created_by      VARCHAR(255) NOT NULL,
        org_domain      VARCHAR(255) NOT NULL,
        created_at      TIMESTAMPTZ  DEFAULT NOW(),
        updated_at      TIMESTAMPTZ  DEFAULT NOW(),
        status          VARCHAR(30)  DEFAULT 'active',
        patient_name    VARCHAR(255),
        date_of_birth   DATE,
        primary_diagnosis VARCHAR(500),
        UNIQUE (mrn, admission_date, org_domain)
    );
    CREATE TABLE IF NOT EXISTS patient_snapshots (
        id              SERIAL PRIMARY KEY,
        patient_id      INTEGER      NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        snapshot_data   JSONB        NOT NULL,
        submitted_by    VARCHAR(255) NOT NULL,
        submitted_at    TIMESTAMPTZ  DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS plan_runs (
        id              SERIAL PRIMARY KEY,
        patient_id      INTEGER      NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        snapshot_id     INTEGER      NOT NULL REFERENCES patient_snapshots(id) ON DELETE CASCADE,
        run_number      INTEGER      NOT NULL,
        started_at      TIMESTAMPTZ  DEFAULT NOW(),
        completed_at    TIMESTAMPTZ,
        run_by          VARCHAR(255) NOT NULL,
        status          VARCHAR(20)  DEFAULT 'running',
        final_plan      TEXT,
        los_prediction  JSONB
    );
    CREATE TABLE IF NOT EXISTS agent_outputs (
        id              SERIAL PRIMARY KEY,
        run_id          INTEGER      NOT NULL REFERENCES plan_runs(id) ON DELETE CASCADE,
        agent_name      VARCHAR(50)  NOT NULL,
        output_text     TEXT         NOT NULL,
        completed_at    TIMESTAMPTZ  DEFAULT NOW(),
        duration_ms     INTEGER
    );
    CREATE TABLE IF NOT EXISTS patient_notes (
        id              SERIAL PRIMARY KEY,
        patient_id      INTEGER      NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        note_text       TEXT         NOT NULL,
        author_email    VARCHAR(255) NOT NULL,
        created_at      TIMESTAMPTZ  DEFAULT NOW(),
        updated_at      TIMESTAMPTZ  DEFAULT NOW(),
        is_deleted      BOOLEAN      DEFAULT FALSE
    );
    CREATE TABLE IF NOT EXISTS status_history (
        id              SERIAL PRIMARY KEY,
        patient_id      INTEGER      NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        old_status      VARCHAR(30),
        new_status      VARCHAR(30)  NOT NULL,
        changed_by      VARCHAR(255) NOT NULL,
        changed_at      TIMESTAMPTZ  DEFAULT NOW(),
        note            TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_patients_org         ON patients(org_domain);
    CREATE INDEX IF NOT EXISTS idx_patients_mrn_org     ON patients(mrn, org_domain);
    CREATE INDEX IF NOT EXISTS idx_plan_runs_patient    ON plan_runs(patient_id);
    CREATE INDEX IF NOT EXISTS idx_agent_outputs_run    ON agent_outputs(run_id);
    CREATE INDEX IF NOT EXISTS idx_notes_patient        ON patient_notes(patient_id);
    CREATE TABLE IF NOT EXISTS eligibility_cache (
        id              SERIAL PRIMARY KEY,
        cache_key       VARCHAR(64)  NOT NULL UNIQUE,
        payer_id        VARCHAR(50)  NOT NULL,
        result_json     JSONB        NOT NULL,
        checked_at      TIMESTAMPTZ  DEFAULT NOW(),
        expires_at      TIMESTAMPTZ  NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_eligibility_cache_key ON eligibility_cache(cache_key);
    CREATE INDEX IF NOT EXISTS idx_eligibility_cache_exp ON eligibility_cache(expires_at);
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS actual_discharge_date DATE;
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS drg_code VARCHAR(10);
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS drg_description VARCHAR(300);
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS actual_los_days INTEGER;
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS hospital_type VARCHAR(20) DEFAULT 'nonprofit';
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS discharge_destination VARCHAR(50);
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS was_readmitted BOOLEAN DEFAULT FALSE;
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS readmission_date DATE;
    ALTER TABLE patients ADD COLUMN IF NOT EXISTS readmission_dx VARCHAR(300);
    CREATE TABLE IF NOT EXISTS drg_reference (
        drg_code            VARCHAR(10)  PRIMARY KEY,
        drg_description     VARCHAR(300) NOT NULL,
        mdc_code            VARCHAR(5),
        mdc_description     VARCHAR(200),
        drg_type            VARCHAR(20),
        relative_weight     FLOAT,
        geometric_mean_los  FLOAT NOT NULL,
        arithmetic_mean_los FLOAT,
        fiscal_year         INTEGER DEFAULT 2026,
        is_ca_hrrp_drg      BOOLEAN DEFAULT FALSE
    );
    CREATE TABLE IF NOT EXISTS roi_outcomes (
        id                          SERIAL PRIMARY KEY,
        patient_id                  INTEGER      NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
        org_domain                  VARCHAR(255) NOT NULL,
        mrn                         VARCHAR(50)  NOT NULL,
        admission_date              DATE         NOT NULL,
        actual_discharge_date       DATE         NOT NULL,
        actual_los_days             INTEGER      NOT NULL,
        drg_code                    VARCHAR(10),
        drg_description             VARCHAR(300),
        drg_geometric_mean_los      FLOAT,
        hospital_type               VARCHAR(20)  DEFAULT 'nonprofit',
        cost_per_day                FLOAT        NOT NULL,
        excess_days_saved           FLOAT,
        cost_savings_dollars        FLOAT,
        discharge_destination       VARCHAR(50),
        was_readmitted              BOOLEAN DEFAULT FALSE,
        readmission_within_30d      BOOLEAN DEFAULT FALSE,
        hrrp_condition_flagged      BOOLEAN DEFAULT FALSE,
        hrrp_penalty_avoided        BOOLEAN,
        barriers_identified         INTEGER DEFAULT 0,
        barriers_resolved           INTEGER DEFAULT 0,
        avg_barrier_resolution_hours FLOAT,
        had_overdue_barriers        BOOLEAN DEFAULT FALSE,
        total_plan_runs             INTEGER DEFAULT 1,
        first_run_at                TIMESTAMPTZ,
        predicted_los_days          FLOAT,
        prediction_error_days       FLOAT,
        tcm_episode_id              VARCHAR(50),
        tcm_cpt_code                VARCHAR(10),
        tcm_revenue                 FLOAT DEFAULT 0,
        primary_clinician           VARCHAR(255),
        calculated_at               TIMESTAMPTZ DEFAULT NOW(),
        calculation_version         INTEGER DEFAULT 1,
        UNIQUE(patient_id)
    );
    CREATE TABLE IF NOT EXISTS org_roi_settings (
        org_domain          VARCHAR(255) PRIMARY KEY,
        hospital_type       VARCHAR(20)  DEFAULT 'nonprofit',
        cost_per_day        FLOAT        DEFAULT 4000,
        hospital_name       VARCHAR(200),
        license_beds        INTEGER,
        annual_discharges   INTEGER,
        fiscal_year_start   INTEGER DEFAULT 10,
        created_at          TIMESTAMPTZ DEFAULT NOW(),
        updated_at          TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX IF NOT EXISTS idx_roi_outcomes_org     ON roi_outcomes(org_domain);
    CREATE INDEX IF NOT EXISTS idx_roi_outcomes_date    ON roi_outcomes(actual_discharge_date);
    CREATE INDEX IF NOT EXISTS idx_roi_outcomes_drg     ON roi_outcomes(drg_code);
    CREATE INDEX IF NOT EXISTS idx_roi_outcomes_patient ON roi_outcomes(patient_id);
    CREATE INDEX IF NOT EXISTS idx_drg_reference_code   ON drg_reference(drg_code);
    CREATE TABLE IF NOT EXISTS pilot_applications (
        id              SERIAL PRIMARY KEY,
        hospital_name   VARCHAR(300) NOT NULL,
        applicant_name  VARCHAR(200) NOT NULL,
        applicant_title VARCHAR(100),
        email           VARCHAR(255) NOT NULL,
        phone           VARCHAR(30),
        licensed_beds   INTEGER,
        ehr_system      VARCHAR(50),
        annual_discharges INTEGER,
        how_found       VARCHAR(100),
        challenge_text  TEXT,
        status          VARCHAR(30) DEFAULT 'pending',
        submitted_at    TIMESTAMPTZ DEFAULT NOW(),
        reviewed_at     TIMESTAMPTZ,
        reviewed_by     VARCHAR(255),
        notes           TEXT,
        calculator_inputs JSONB
    );
    ALTER TABLE org_roi_settings
        ADD COLUMN IF NOT EXISTS platform_subscription_monthly FLOAT DEFAULT 7000
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
        from db.referrals import run_referral_migrations
        run_referral_migrations()
    except Exception as e:
        _log.warning("Patient migrations skipped (no DB?): %s", e)


def get_or_create_patient(mrn: str, admission_date: str, user_email: str, patient_data: dict) -> dict:
    org_domain = get_org_domain(user_email)
    patient_name = patient_data.get("patient_name") or None
    primary_diagnosis = patient_data.get("primary_diagnosis") or None
    dob = patient_data.get("date_of_birth") or None

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO patients (mrn, admission_date, created_by, org_domain, patient_name, primary_diagnosis, date_of_birth)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (mrn, admission_date, org_domain) DO UPDATE SET
                        updated_at = NOW(),
                        patient_name = COALESCE(EXCLUDED.patient_name, patients.patient_name),
                        primary_diagnosis = COALESCE(EXCLUDED.primary_diagnosis, patients.primary_diagnosis),
                        date_of_birth = COALESCE(EXCLUDED.date_of_birth, patients.date_of_birth)
                    RETURNING *
                """, (mrn, admission_date, user_email, org_domain, patient_name, primary_diagnosis, dob))
                row = cur.fetchone()
                return dict(row)
    finally:
        conn.close()


def save_snapshot(patient_id: int, patient_data: dict, user_email: str) -> int:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO patient_snapshots (patient_id, snapshot_data, submitted_by) VALUES (%s, %s, %s) RETURNING id",
                    (patient_id, json.dumps(patient_data), user_email)
                )
                return cur.fetchone()["id"]
    finally:
        conn.close()


def start_plan_run(patient_id: int, snapshot_id: int, user_email: str) -> int:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as cnt FROM plan_runs WHERE patient_id = %s", (patient_id,))
                run_number = cur.fetchone()["cnt"] + 1
                cur.execute(
                    "INSERT INTO plan_runs (patient_id, snapshot_id, run_number, run_by) VALUES (%s, %s, %s, %s) RETURNING id",
                    (patient_id, snapshot_id, run_number, user_email)
                )
                return cur.fetchone()["id"]
    finally:
        conn.close()


def save_agent_output(run_id: int, agent_name: str, output_text: str, duration_ms: int = 0) -> None:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO agent_outputs (run_id, agent_name, output_text, duration_ms) VALUES (%s, %s, %s, %s)",
                    (run_id, agent_name, output_text, duration_ms)
                )
    finally:
        conn.close()


def complete_plan_run(run_id: int, final_plan: str, los_prediction: Optional[dict] = None) -> None:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE plan_runs SET status='complete', completed_at=NOW(), final_plan=%s, los_prediction=%s
                    WHERE id=%s
                """, (final_plan, json.dumps(los_prediction) if los_prediction else None, run_id))
                cur.execute("UPDATE patients SET updated_at=NOW() WHERE id=(SELECT patient_id FROM plan_runs WHERE id=%s)", (run_id,))
    finally:
        conn.close()


def fail_plan_run(run_id: int, error: str) -> None:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE plan_runs SET status='failed', final_plan=%s WHERE id=%s", (error, run_id))
    finally:
        conn.close()


def get_patients_for_org(org_domain: str, limit: int = 100) -> list[dict]:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.*,
                        COUNT(DISTINCT r.id) as total_runs,
                        MAX(r.completed_at) as last_run_at,
                        (SELECT r2.run_by FROM plan_runs r2 WHERE r2.patient_id = p.id ORDER BY r2.started_at DESC LIMIT 1) as last_run_by,
                        COALESCE((SELECT COUNT(*) FROM discharge_milestones m WHERE m.patient_id = p.id AND m.status = 'open'), 0) as open_milestone_count,
                        COALESCE((SELECT COUNT(*) FROM discharge_milestones m WHERE m.patient_id = p.id AND m.status = 'open' AND m.due_date IS NOT NULL AND m.due_date < NOW()), 0) as overdue_milestone_count
                    FROM patients p
                    LEFT JOIN plan_runs r ON r.patient_id = p.id
                    WHERE p.org_domain = %s
                    GROUP BY p.id
                    ORDER BY p.updated_at DESC
                    LIMIT %s
                """, (org_domain, limit))
                return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_patient_detail(patient_id: int, org_domain: str) -> Optional[dict]:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM patients WHERE id=%s AND org_domain=%s", (patient_id, org_domain))
                patient = cur.fetchone()
                if not patient:
                    return None
                result = dict(patient)

                cur.execute("SELECT * FROM plan_runs WHERE patient_id=%s ORDER BY run_number ASC", (patient_id,))
                runs = [dict(r) for r in cur.fetchall()]
                for run in runs:
                    cur.execute("SELECT * FROM agent_outputs WHERE run_id=%s ORDER BY completed_at ASC", (run["id"],))
                    run["agents"] = [dict(a) for a in cur.fetchall()]
                result["runs"] = runs

                cur.execute("SELECT * FROM patient_notes WHERE patient_id=%s AND is_deleted=FALSE ORDER BY created_at DESC", (patient_id,))
                result["notes"] = [dict(n) for n in cur.fetchall()]

                cur.execute("SELECT * FROM status_history WHERE patient_id=%s ORDER BY changed_at DESC", (patient_id,))
                result["status_history"] = [dict(s) for s in cur.fetchall()]

                return result
    finally:
        conn.close()


def get_latest_snapshot(patient_id: int) -> Optional[dict]:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT snapshot_data FROM patient_snapshots WHERE patient_id=%s ORDER BY submitted_at DESC LIMIT 1", (patient_id,))
                row = cur.fetchone()
                return dict(row["snapshot_data"]) if row else None
    finally:
        conn.close()


def update_patient_status(patient_id: int, new_status: str, changed_by: str, note: Optional[str] = None) -> None:
    if new_status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {new_status}")
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT status FROM patients WHERE id=%s", (patient_id,))
                row = cur.fetchone()
                old_status = row["status"] if row else None
                cur.execute("UPDATE patients SET status=%s, updated_at=NOW() WHERE id=%s", (new_status, patient_id))
                cur.execute(
                    "INSERT INTO status_history (patient_id, old_status, new_status, changed_by, note) VALUES (%s,%s,%s,%s,%s)",
                    (patient_id, old_status, new_status, changed_by, note)
                )
    finally:
        conn.close()


def add_patient_note(patient_id: int, note_text: str, author_email: str) -> dict:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO patient_notes (patient_id, note_text, author_email) VALUES (%s,%s,%s) RETURNING *",
                    (patient_id, note_text, author_email)
                )
                return dict(cur.fetchone())
    finally:
        conn.close()


def delete_patient_note(note_id: int, author_email: str) -> bool:
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE patient_notes SET is_deleted=TRUE WHERE id=%s AND author_email=%s AND is_deleted=FALSE",
                    (note_id, author_email)
                )
                return cur.rowcount > 0
    finally:
        conn.close()


def get_cached_eligibility(cache_key: str) -> Optional[dict]:
    """Return cached eligibility result if not expired, else None."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT result_json FROM eligibility_cache WHERE cache_key=%s AND expires_at > NOW()",
                    (cache_key,),
                )
                row = cur.fetchone()
                return dict(row["result_json"]) if row else None
    finally:
        conn.close()


def cache_eligibility_result(cache_key: str, result_json: dict, payer_id: str, ttl_hours: int = 4) -> None:
    """Insert or replace eligibility cache entry."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO eligibility_cache (cache_key, payer_id, result_json, expires_at)
                    VALUES (%s, %s, %s, NOW() + INTERVAL '1 hour' * %s)
                    ON CONFLICT (cache_key) DO UPDATE SET
                        result_json = EXCLUDED.result_json,
                        checked_at  = NOW(),
                        expires_at  = EXCLUDED.expires_at
                    """,
                    (cache_key, payer_id, json.dumps(result_json), ttl_hours),
                )
    finally:
        conn.close()


def search_patients(org_domain: str, query: str, limit: int = 20) -> list[dict]:
    q = f"%{query}%"
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT p.*,
                        COUNT(r.id) as total_runs,
                        MAX(r.completed_at) as last_run_at,
                        (SELECT r2.run_by FROM plan_runs r2 WHERE r2.patient_id = p.id ORDER BY r2.started_at DESC LIMIT 1) as last_run_by
                    FROM patients p
                    LEFT JOIN plan_runs r ON r.patient_id = p.id
                    WHERE p.org_domain = %s AND (p.mrn ILIKE %s OR p.patient_name ILIKE %s OR p.primary_diagnosis ILIKE %s)
                    GROUP BY p.id
                    ORDER BY p.updated_at DESC
                    LIMIT %s
                """, (org_domain, q, q, q, limit))
                return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
