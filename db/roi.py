"""ROI outcomes DB layer — reads, writes, and aggregation queries."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from db.connection import get_db_conn

_log = logging.getLogger(__name__)


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


# ── Org settings ──────────────────────────────────────────────────────────────

def get_org_roi_settings(org_domain: str) -> dict:
    """Return org ROI settings, or defaults if not yet configured."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM org_roi_settings WHERE org_domain = %s",
                    (org_domain,),
                )
                row = cur.fetchone()
                if row:
                    return _json_safe(dict(row))
                return {
                    "org_domain": org_domain,
                    "hospital_type": "nonprofit",
                    "cost_per_day": 4000.0,
                    "hospital_name": None,
                    "license_beds": None,
                    "annual_discharges": None,
                    "fiscal_year_start": 10,
                }
    finally:
        conn.close()


def upsert_org_roi_settings(org_domain: str, settings: dict) -> dict:
    """Create or update org ROI settings."""
    allowed = {
        "hospital_type", "cost_per_day", "hospital_name",
        "license_beds", "annual_discharges", "fiscal_year_start",
    }
    filtered = {k: v for k, v in settings.items() if k in allowed}
    if not filtered:
        return get_org_roi_settings(org_domain)

    set_clauses = ", ".join(f"{k} = %s" for k in filtered)
    values = list(filtered.values()) + [org_domain]

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO org_roi_settings (org_domain, {", ".join(filtered)})
                    VALUES (%s, {", ".join(["%s"] * len(filtered))})
                    ON CONFLICT (org_domain) DO UPDATE SET
                        {set_clauses},
                        updated_at = NOW()
                    RETURNING *
                    """,
                    [org_domain] + list(filtered.values()) + list(filtered.values()),
                )
                row = cur.fetchone()
                return _json_safe(dict(row)) if row else get_org_roi_settings(org_domain)
    finally:
        conn.close()


# ── DRG reference ─────────────────────────────────────────────────────────────

def get_drg_reference(drg_code: str) -> Optional[dict]:
    """Return DRG reference row by code. Returns None if not found."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM drg_reference WHERE drg_code = %s",
                    (drg_code.strip().lstrip("0") or drg_code.strip(),),
                )
                # Try exact match first, then zero-padded forms
                row = cur.fetchone()
                if not row:
                    # Try zero-padded (e.g. "064" stored as "64")
                    cur.execute(
                        "SELECT * FROM drg_reference WHERE drg_code = %s",
                        (drg_code.strip().zfill(3),),
                    )
                    row = cur.fetchone()
                return _json_safe(dict(row)) if row else None
    finally:
        conn.close()


def search_drg(query: str, limit: int = 20) -> list[dict]:
    """Search DRG reference by code or description. Returns up to limit rows."""
    q = f"%{query}%"
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT drg_code, drg_description, mdc_code, drg_type,
                           geometric_mean_los, relative_weight, is_ca_hrrp_drg
                    FROM drg_reference
                    WHERE drg_code ILIKE %s OR drg_description ILIKE %s
                    ORDER BY
                      CASE WHEN drg_code ILIKE %s THEN 0 ELSE 1 END,
                      drg_code
                    LIMIT %s
                    """,
                    (q, q, f"{query}%", limit),
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


# ── ROI outcomes ──────────────────────────────────────────────────────────────

def upsert_roi_outcome(patient_id: int, org_domain: str, outcome_data: dict) -> dict:
    """Insert or update the roi_outcomes row for a patient episode."""
    d = outcome_data
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO roi_outcomes (
                        patient_id, org_domain, mrn, admission_date,
                        actual_discharge_date, actual_los_days,
                        drg_code, drg_description, drg_geometric_mean_los,
                        hospital_type, cost_per_day,
                        excess_days_saved, cost_savings_dollars,
                        discharge_destination,
                        was_readmitted, readmission_within_30d,
                        hrrp_condition_flagged, hrrp_penalty_avoided,
                        barriers_identified, barriers_resolved,
                        avg_barrier_resolution_hours, had_overdue_barriers,
                        total_plan_runs, first_run_at,
                        predicted_los_days, prediction_error_days,
                        tcm_episode_id, tcm_cpt_code, tcm_revenue,
                        primary_clinician,
                        total_value_dollars, calculation_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (patient_id) DO UPDATE SET
                        actual_discharge_date   = EXCLUDED.actual_discharge_date,
                        actual_los_days         = EXCLUDED.actual_los_days,
                        drg_code                = EXCLUDED.drg_code,
                        drg_description         = EXCLUDED.drg_description,
                        drg_geometric_mean_los  = EXCLUDED.drg_geometric_mean_los,
                        hospital_type           = EXCLUDED.hospital_type,
                        cost_per_day            = EXCLUDED.cost_per_day,
                        excess_days_saved       = EXCLUDED.excess_days_saved,
                        cost_savings_dollars    = EXCLUDED.cost_savings_dollars,
                        discharge_destination   = EXCLUDED.discharge_destination,
                        was_readmitted          = EXCLUDED.was_readmitted,
                        readmission_within_30d  = EXCLUDED.readmission_within_30d,
                        hrrp_condition_flagged  = EXCLUDED.hrrp_condition_flagged,
                        hrrp_penalty_avoided    = EXCLUDED.hrrp_penalty_avoided,
                        barriers_identified     = EXCLUDED.barriers_identified,
                        barriers_resolved       = EXCLUDED.barriers_resolved,
                        avg_barrier_resolution_hours = EXCLUDED.avg_barrier_resolution_hours,
                        had_overdue_barriers    = EXCLUDED.had_overdue_barriers,
                        total_plan_runs         = EXCLUDED.total_plan_runs,
                        predicted_los_days      = EXCLUDED.predicted_los_days,
                        prediction_error_days   = EXCLUDED.prediction_error_days,
                        tcm_revenue             = EXCLUDED.tcm_revenue,
                        primary_clinician       = EXCLUDED.primary_clinician,
                        total_value_dollars     = EXCLUDED.total_value_dollars,
                        calculated_at           = NOW(),
                        calculation_version     = EXCLUDED.calculation_version
                    RETURNING *
                    """,
                    (
                        patient_id, org_domain,
                        d.get("mrn"), d.get("admission_date"),
                        d.get("actual_discharge_date"), d.get("actual_los_days"),
                        d.get("drg_code"), d.get("drg_description"),
                        d.get("drg_geometric_mean_los"),
                        d.get("hospital_type", "nonprofit"),
                        d.get("cost_per_day", 4000.0),
                        d.get("excess_days_saved"), d.get("cost_savings_dollars"),
                        d.get("discharge_destination"),
                        d.get("was_readmitted", False),
                        d.get("readmission_within_30d", False),
                        d.get("hrrp_condition_flagged", False),
                        d.get("hrrp_penalty_avoided"),
                        d.get("barriers_identified", 0),
                        d.get("barriers_resolved", 0),
                        d.get("avg_barrier_resolution_hours"),
                        d.get("had_overdue_barriers", False),
                        d.get("total_plan_runs", 1),
                        d.get("first_run_at"),
                        d.get("predicted_los_days"),
                        d.get("prediction_error_days"),
                        d.get("tcm_episode_id"),
                        d.get("tcm_cpt_code"),
                        d.get("tcm_revenue", 0.0),
                        d.get("primary_clinician"),
                        d.get("total_value_dollars", 0.0),
                        d.get("calculation_version", 1),
                    ),
                )
                row = cur.fetchone()
                return _json_safe(dict(row)) if row else {}
    finally:
        conn.close()


def get_roi_outcome(patient_id: int, org_domain: str) -> Optional[dict]:
    """Return roi_outcomes row for a patient, or None."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM roi_outcomes WHERE patient_id = %s AND org_domain = %s",
                    (patient_id, org_domain),
                )
                row = cur.fetchone()
                return _json_safe(dict(row)) if row else None
    finally:
        conn.close()


def get_org_roi_outcomes(
    org_domain: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    drg_code: Optional[str] = None,
    clinician: Optional[str] = None,
    limit: int = 500,
) -> list[dict]:
    """Return roi_outcomes rows for an org with optional filters."""
    conditions = ["org_domain = %s"]
    params: list = [org_domain]

    if start_date:
        conditions.append("actual_discharge_date >= %s")
        params.append(start_date)
    if end_date:
        conditions.append("actual_discharge_date <= %s")
        params.append(end_date)
    if drg_code:
        conditions.append("drg_code = %s")
        params.append(drg_code)
    if clinician:
        conditions.append("primary_clinician = %s")
        params.append(clinician)

    where = " AND ".join(conditions)
    params.append(limit)

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM roi_outcomes WHERE {where} "
                    f"ORDER BY actual_discharge_date DESC LIMIT %s",
                    params,
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


def get_monthly_roi_trend(org_domain: str, months: int = 12) -> list[dict]:
    """Monthly aggregated ROI metrics for the past N months."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        EXTRACT(YEAR  FROM actual_discharge_date)::int AS year,
                        EXTRACT(MONTH FROM actual_discharge_date)::int AS month,
                        COUNT(*)                                        AS episodes,
                        COALESCE(SUM(CASE WHEN excess_days_saved > 0 THEN excess_days_saved ELSE 0 END), 0) AS excess_days_saved,
                        COALESCE(SUM(CASE WHEN cost_savings_dollars > 0 THEN cost_savings_dollars ELSE 0 END), 0) AS cost_savings,
                        COALESCE(SUM(CASE WHEN hrrp_penalty_avoided THEN 4500 ELSE 0 END), 0) AS hrrp_avoided_dollars,
                        COALESCE(SUM(tcm_revenue), 0)                  AS tcm_revenue,
                        COALESCE(SUM(total_value_dollars), 0)          AS total_value
                    FROM roi_outcomes
                    WHERE org_domain = %s
                      AND actual_discharge_date >= NOW() - INTERVAL '1 month' * %s
                    GROUP BY year, month
                    ORDER BY year, month
                    """,
                    (org_domain, months),
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


def get_drg_roi_breakdown(org_domain: str, limit: int = 20) -> list[dict]:
    """ROI grouped by DRG code, sorted by total cost savings DESC."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        drg_code,
                        drg_description,
                        COUNT(*)                                    AS episodes,
                        ROUND(AVG(excess_days_saved)::numeric, 2)   AS avg_excess_days,
                        COALESCE(SUM(CASE WHEN cost_savings_dollars > 0 THEN cost_savings_dollars ELSE 0 END), 0) AS total_savings,
                        COALESCE(SUM(total_value_dollars), 0)       AS total_value
                    FROM roi_outcomes
                    WHERE org_domain = %s AND drg_code IS NOT NULL
                    GROUP BY drg_code, drg_description
                    ORDER BY total_savings DESC
                    LIMIT %s
                    """,
                    (org_domain, limit),
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


def get_clinician_roi_breakdown(org_domain: str) -> list[dict]:
    """ROI grouped by primary clinician, sorted by total value DESC."""
    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        primary_clinician                            AS clinician,
                        COUNT(*)                                     AS episodes,
                        COALESCE(SUM(excess_days_saved), 0)         AS total_excess_days,
                        COALESCE(SUM(total_value_dollars), 0)       AS total_value
                    FROM roi_outcomes
                    WHERE org_domain = %s AND primary_clinician IS NOT NULL
                    GROUP BY primary_clinician
                    ORDER BY total_value DESC
                    """,
                    (org_domain,),
                )
                return _json_safe([dict(r) for r in cur.fetchall()])
    finally:
        conn.close()


def get_roi_dashboard_data(org_domain: str, months: int = 12) -> dict:
    """Single call returning everything needed for the CFO dashboard."""
    settings = get_org_roi_settings(org_domain)
    outcomes = get_org_roi_outcomes(org_domain, limit=500)

    from services.roi_engine import aggregate_org_roi
    totals = aggregate_org_roi(outcomes, date_range_months=float(months))

    monthly = get_monthly_roi_trend(org_domain, months=months)
    drg_breakdown = get_drg_roi_breakdown(org_domain)
    clinician_breakdown = get_clinician_roi_breakdown(org_domain)

    missing_drg = sum(1 for o in outcomes if not o.get("drg_code"))
    completeness = totals["data_completeness_pct"]
    recommendation = ""
    if missing_drg > 0:
        recommendation = (
            f"Add DRG codes to {missing_drg} more discharged patient"
            f"{'s' if missing_drg != 1 else ''} to improve accuracy. "
            f"Current data completeness: {completeness:.0f}%."
        )

    return {
        "settings": settings,
        "totals": totals,
        "monthly_trend": monthly,
        "drg_breakdown": drg_breakdown,
        "clinician_breakdown": clinician_breakdown,
        "data_quality": {
            "episodes_without_drg": missing_drg,
            "completeness_pct": completeness,
            "recommendation": recommendation,
        },
    }


def trigger_outcome_calculation(patient_id: int, org_domain: str) -> Optional[dict]:
    """
    Read all episode data from DB, compute ROI, and upsert the result.
    Called automatically when a patient is marked discharged or DRG code changes.
    """
    from services.roi_engine import compute_episode_roi, get_cost_per_day
    from db.drg_reference_data import HRRP_DRGS

    conn = get_db_conn()
    try:
        with conn:
            with conn.cursor() as cur:
                # Patient record
                cur.execute(
                    "SELECT * FROM patients WHERE id = %s AND org_domain = %s",
                    (patient_id, org_domain),
                )
                patient = cur.fetchone()
                if not patient:
                    return None
                patient = dict(patient)

                if not patient.get("actual_discharge_date") or not patient.get("admission_date"):
                    _log.debug("Patient %s missing discharge/admission date — skipping ROI", patient_id)
                    return None

                # Plan runs (for LOS prediction and first run metadata)
                cur.execute(
                    "SELECT * FROM plan_runs WHERE patient_id = %s ORDER BY started_at ASC",
                    (patient_id,),
                )
                runs = [dict(r) for r in cur.fetchall()]

                # Discharge milestones
                cur.execute(
                    """
                    SELECT created_at, resolved_at
                    FROM discharge_milestones
                    WHERE patient_id = %s AND org_domain = %s
                    """,
                    (patient_id, org_domain),
                )
                milestones = [dict(m) for m in cur.fetchall()]

                # TCM episode (optional)
                tcm_revenue = 0.0
                tcm_id = None
                tcm_cpt = None
                try:
                    cur.execute(
                        "SELECT id, cpt_final, billing_amount FROM tcm_episodes "
                        "WHERE patient_id = %s ORDER BY created_at DESC LIMIT 1",
                        (patient_id,),
                    )
                    tcm = cur.fetchone()
                    if tcm:
                        tcm = dict(tcm)
                        tcm_id = str(tcm.get("id", ""))
                        tcm_cpt = tcm.get("cpt_final")
                        tcm_revenue = float(tcm.get("billing_amount") or 0.0)
                except Exception:
                    pass  # TCM table may not exist

    finally:
        conn.close()

    # Org settings for cost per day
    settings = get_org_roi_settings(org_domain)
    cost_per_day = get_cost_per_day(
        settings.get("hospital_type", "nonprofit"),
        settings.get("cost_per_day"),
    )

    # DRG lookup
    drg_code = patient.get("drg_code")
    drg_ref = get_drg_reference(drg_code) if drg_code else None
    geo_mean_los = drg_ref["geometric_mean_los"] if drg_ref else None
    drg_desc = drg_ref["drg_description"] if drg_ref else patient.get("drg_description")
    is_hrrp = drg_code in HRRP_DRGS if drg_code else False

    # LOS prediction from latest run with non-null los_prediction
    predicted_los: Optional[float] = None
    first_run_at = None
    for run in runs:
        if first_run_at is None:
            first_run_at = run.get("started_at")
        los_pred = run.get("los_prediction")
        if los_pred and isinstance(los_pred, dict):
            predicted_los = los_pred.get("predicted_los_days") or los_pred.get("predicted_days")
        elif los_pred and isinstance(los_pred, str):
            try:
                import json as _json
                p = _json.loads(los_pred)
                predicted_los = p.get("predicted_los_days") or p.get("predicted_days")
            except Exception:
                pass

    # Primary clinician = user who ran the first plan
    primary_clinician = runs[0].get("run_by") if runs else patient.get("created_by")

    # Barrier timing
    created_at_list = [m["created_at"] for m in milestones]
    resolved_at_list = [m.get("resolved_at") for m in milestones]

    result = compute_episode_roi(
        admission_date=patient["admission_date"],
        actual_discharge_date=patient["actual_discharge_date"],
        drg_geometric_mean_los=geo_mean_los,
        cost_per_day=cost_per_day,
        was_readmitted=patient.get("was_readmitted") or False,
        readmission_within_30d=_is_within_30d(
            patient.get("actual_discharge_date"),
            patient.get("readmission_date"),
        ),
        hrrp_condition_flagged=is_hrrp,
        barriers_created_at=created_at_list,
        barriers_resolved_at=resolved_at_list,
        predicted_los_days=predicted_los,
        tcm_revenue=tcm_revenue,
    )

    outcome_data = {
        **result,
        "mrn": patient.get("mrn"),
        "admission_date": patient.get("admission_date"),
        "actual_discharge_date": patient.get("actual_discharge_date"),
        "drg_code": drg_code,
        "drg_description": drg_desc,
        "drg_geometric_mean_los": geo_mean_los,
        "hospital_type": settings.get("hospital_type", "nonprofit"),
        "cost_per_day": cost_per_day,
        "discharge_destination": patient.get("discharge_destination"),
        "was_readmitted": patient.get("was_readmitted") or False,
        "readmission_within_30d": _is_within_30d(
            patient.get("actual_discharge_date"),
            patient.get("readmission_date"),
        ),
        "hrrp_condition_flagged": is_hrrp,
        "total_plan_runs": len(runs),
        "first_run_at": first_run_at,
        "tcm_episode_id": tcm_id,
        "tcm_cpt_code": tcm_cpt,
        "tcm_revenue": tcm_revenue,
        "primary_clinician": primary_clinician,
        "calculation_version": 1,
    }

    return upsert_roi_outcome(patient_id, org_domain, outcome_data)


def _is_within_30d(discharge_date, readmission_date) -> bool:
    if not discharge_date or not readmission_date:
        return False
    if isinstance(discharge_date, datetime):
        discharge_date = discharge_date.date()
    if isinstance(readmission_date, datetime):
        readmission_date = readmission_date.date()
    return (readmission_date - discharge_date).days <= 30
