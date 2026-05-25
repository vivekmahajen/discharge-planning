"""
ROI outcomes calculation engine.
All functions are pure — they accept plain Python values and return dicts.
DB writes live in db/roi.py.

Cost-per-day source: AHA 2024, California inpatient day cost.
DRG baseline source: CMS FY 2026 IPPS Final Rule, Table 5 geometric mean LOS.
HRRP penalty estimate: CMS HRRP fact sheet, conservative median.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

# ── CA cost-per-day (AHA 2024 data, reported January 2026) ────────────────────
CA_COST_PER_DAY: dict[str, float] = {
    "nonprofit":  4_100.0,
    "forprofit":  3_600.0,
    "government": 3_800.0,
    "default":    4_000.0,
}

# Conservative CMS HRRP avoided-penalty estimate per episode.
# Source: CMS HRRP fact sheet — 3% of base DRG payment; CA median ~$4,500.
HRRP_AVOIDED_ESTIMATE_PER_PATIENT: float = 4_500.0

# Minimum episodes required before annualizing is meaningful
MIN_EPISODES_FOR_ANNUALIZATION = 10


def get_cost_per_day(hospital_type: str, override: Optional[float] = None) -> float:
    if override and override > 0:
        return float(override)
    return CA_COST_PER_DAY.get(hospital_type, CA_COST_PER_DAY["default"])


def compute_episode_roi(
    admission_date: date,
    actual_discharge_date: date,
    drg_geometric_mean_los: Optional[float],
    cost_per_day: float,
    was_readmitted: bool,
    readmission_within_30d: bool,
    hrrp_condition_flagged: bool,
    barriers_created_at: list,     # list of date or datetime
    barriers_resolved_at: list,    # list of date/datetime or None — parallel to created_at
    predicted_los_days: Optional[float],
    tcm_revenue: float,
) -> dict:
    """
    Compute all measured outcomes for a single discharged patient episode.

    Returns a dict containing calculated metrics and methodology_notes audit trail.
    Negative excess_days_saved means the patient stayed longer than the DRG baseline.
    """
    notes: list[str] = []

    actual_los = (actual_discharge_date - admission_date).days
    notes.append(
        f"Actual LOS: {actual_los} days "
        f"({admission_date.isoformat()} to {actual_discharge_date.isoformat()})"
    )

    # ── Excess days & cost savings ─────────────────────────────────────────────
    excess_days: Optional[float] = None
    cost_savings: Optional[float] = None

    if drg_geometric_mean_los is not None:
        excess_days = round(drg_geometric_mean_los - actual_los, 2)
        cost_savings = round(excess_days * cost_per_day, 2)
        direction = "saved" if excess_days >= 0 else "extended beyond"
        notes.append(
            f"DRG geometric mean LOS (CMS FY 2026 Table 5): {drg_geometric_mean_los} days. "
            f"Actual: {actual_los} days. "
            f"{abs(excess_days)} days {direction} baseline. "
            f"Cost per day: ${cost_per_day:,.0f} (AHA 2024, CA hospitals). "
            f"{'Savings' if excess_days >= 0 else 'Extended-stay cost'}: "
            f"${abs(cost_savings):,.0f}."
        )
    else:
        notes.append(
            "No DRG code on record — excess days and cost savings cannot be calculated. "
            "Enter DRG code on this patient to enable measurement. "
            "Totals include this episode with $0 cost impact."
        )

    # ── HRRP penalty avoidance ────────────────────────────────────────────────
    hrrp_penalty_avoided: Optional[bool] = None
    hrrp_avoided_dollars: float = 0.0

    if hrrp_condition_flagged:
        hrrp_penalty_avoided = not readmission_within_30d
        if hrrp_penalty_avoided:
            hrrp_avoided_dollars = HRRP_AVOIDED_ESTIMATE_PER_PATIENT
            notes.append(
                f"HRRP condition flagged. No 30-day readmission recorded. "
                f"Estimated penalty avoided: ~${HRRP_AVOIDED_ESTIMATE_PER_PATIENT:,.0f} "
                f"(conservative CMS median, 3% of base DRG payment)."
            )
        else:
            notes.append(
                "HRRP condition flagged. 30-day readmission recorded — "
                "penalty avoidance not counted."
            )

    # ── Barrier resolution metrics ─────────────────────────────────────────────
    barriers_identified = len(barriers_created_at)
    barriers_resolved = 0
    resolution_hours: list[float] = []
    had_overdue = False

    for i, created in enumerate(barriers_created_at):
        resolved = barriers_resolved_at[i] if i < len(barriers_resolved_at) else None
        if resolved is not None:
            barriers_resolved += 1
            # Handle both date and datetime inputs
            if isinstance(created, datetime) and isinstance(resolved, datetime):
                hrs = (resolved - created).total_seconds() / 3600.0
            elif isinstance(created, date) and isinstance(resolved, date):
                hrs = float((resolved - created).days * 24)
            else:
                # Mixed types — coerce to date
                c = created.date() if isinstance(created, datetime) else created
                r = resolved.date() if isinstance(resolved, datetime) else resolved
                hrs = float((r - c).days * 24)
            resolution_hours.append(hrs)

    avg_resolution = (
        round(sum(resolution_hours) / len(resolution_hours), 1)
        if resolution_hours else None
    )

    # ── Prediction accuracy ────────────────────────────────────────────────────
    prediction_error: Optional[float] = None
    if predicted_los_days is not None:
        prediction_error = round(abs(predicted_los_days - actual_los), 1)
        notes.append(
            f"ML-predicted LOS: {predicted_los_days} days. "
            f"Actual: {actual_los} days. Prediction error: {prediction_error} days."
        )

    # ── Total value (conservative: only count positive savings) ───────────────
    total_value = 0.0
    if cost_savings is not None and cost_savings > 0:
        total_value += cost_savings
    total_value += hrrp_avoided_dollars
    total_value += max(float(tcm_revenue), 0.0)

    notes.append(
        f"Total value: ${total_value:,.2f} "
        f"(cost savings: ${max(cost_savings or 0, 0):,.0f} + "
        f"HRRP avoided: ${hrrp_avoided_dollars:,.0f} + "
        f"TCM revenue: ${max(float(tcm_revenue), 0):,.0f})."
    )

    return {
        "actual_los_days": actual_los,
        "excess_days_saved": excess_days,
        "cost_savings_dollars": cost_savings,
        "hrrp_penalty_avoided": hrrp_penalty_avoided,
        "hrrp_avoided_estimate": hrrp_avoided_dollars,
        "barriers_identified": barriers_identified,
        "barriers_resolved": barriers_resolved,
        "avg_barrier_resolution_hours": avg_resolution,
        "had_overdue_barriers": had_overdue,
        "prediction_error_days": prediction_error,
        "tcm_revenue": float(tcm_revenue),
        "total_value_dollars": round(total_value, 2),
        "methodology_notes": notes,
    }


def aggregate_org_roi(outcomes: list[dict], date_range_months: Optional[float] = None) -> dict:
    """
    Aggregate a list of compute_episode_roi results into org-level metrics.

    date_range_months: if provided, used for annualized run rate calculation.
    Annualized run rate is only reported when >= MIN_EPISODES_FOR_ANNUALIZATION episodes
    and date_range_months is provided.
    """
    if not outcomes:
        return {
            "total_episodes_measured": 0,
            "episodes_with_drg": 0,
            "total_excess_days_saved": 0.0,
            "total_cost_savings_dollars": 0.0,
            "avg_excess_days_per_episode": None,
            "avg_cost_savings_per_episode": None,
            "total_hrrp_penalties_avoided": 0,
            "total_hrrp_avoided_dollars": 0.0,
            "total_tcm_revenue": 0.0,
            "total_value_dollars": 0.0,
            "avg_barrier_resolution_hours": None,
            "episodes_with_overdue_barriers": 0,
            "readmission_rate_30d": 0.0,
            "avg_prediction_error_days": None,
            "annualized_run_rate_dollars": None,
            "annualized_insufficient_data": True,
            "data_completeness_pct": 0.0,
        }

    with_drg = [o for o in outcomes if o.get("excess_days_saved") is not None]
    total_saved = sum(o["excess_days_saved"] for o in with_drg)
    total_cost_savings = sum(
        o["cost_savings_dollars"] for o in with_drg
        if o.get("cost_savings_dollars") is not None
    )
    hrrp_avoided = [o for o in outcomes if o.get("hrrp_penalty_avoided") is True]
    hrrp_avoided_dollars = sum(o.get("hrrp_avoided_estimate", 0) for o in outcomes)
    readmissions_30d = sum(1 for o in outcomes if o.get("readmission_within_30d"))
    prediction_errors = [
        o["prediction_error_days"] for o in outcomes
        if o.get("prediction_error_days") is not None
    ]
    resolution_hours = [
        o["avg_barrier_resolution_hours"] for o in outcomes
        if o.get("avg_barrier_resolution_hours") is not None
    ]
    tcm_revenue = sum(o.get("tcm_revenue", 0.0) for o in outcomes)
    total_value = sum(o.get("total_value_dollars", 0.0) for o in outcomes)

    # Annualized run rate
    n = len(outcomes)
    ann_run_rate: Optional[float] = None
    insufficient = n < MIN_EPISODES_FOR_ANNUALIZATION
    if not insufficient and date_range_months and date_range_months > 0:
        monthly_rate = total_value / date_range_months
        ann_run_rate = round(monthly_rate * 12, 2)

    return {
        "total_episodes_measured": n,
        "episodes_with_drg": len(with_drg),
        "total_excess_days_saved": round(total_saved, 1),
        "total_cost_savings_dollars": round(total_cost_savings, 2),
        "avg_excess_days_per_episode": round(total_saved / len(with_drg), 2) if with_drg else None,
        "avg_cost_savings_per_episode": round(total_cost_savings / len(with_drg), 2) if with_drg else None,
        "total_hrrp_penalties_avoided": len(hrrp_avoided),
        "total_hrrp_avoided_dollars": round(hrrp_avoided_dollars, 2),
        "total_tcm_revenue": round(tcm_revenue, 2),
        "total_value_dollars": round(total_value, 2),
        "avg_barrier_resolution_hours": round(sum(resolution_hours) / len(resolution_hours), 1) if resolution_hours else None,
        "episodes_with_overdue_barriers": sum(1 for o in outcomes if o.get("had_overdue_barriers")),
        "readmission_rate_30d": round(readmissions_30d / n * 100, 1),
        "avg_prediction_error_days": round(sum(prediction_errors) / len(prediction_errors), 1) if prediction_errors else None,
        "annualized_run_rate_dollars": ann_run_rate,
        "annualized_insufficient_data": insufficient,
        "data_completeness_pct": round(len(with_drg) / n * 100, 1),
    }
