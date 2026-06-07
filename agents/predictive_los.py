"""Predictive LOS Agent — ML-based length-of-stay and discharge date prediction."""
from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import joblib

_MODEL_PATH = Path(__file__).parent.parent / "models" / "los_model.joblib"
_BUNDLE = None
_BUNDLE_LOADED = False  # flag to avoid re-trying a missing file every call


# LOSModelBundle must be defined here (not in the training script) so that
# joblib.load() can find the class at the same import path used to save it.
@dataclass
class LOSModelBundle:
    median_model: object
    p10_model: object
    p90_model: object
    feature_names: list
    feature_importances: list  # [(name, importance), ...] sorted desc
    trained_at: str
    training_samples: int
    test_mae: float
    test_r2: float


def _load_bundle():
    global _BUNDLE, _BUNDLE_LOADED
    if not _BUNDLE_LOADED:
        _BUNDLE_LOADED = True
        if _MODEL_PATH.exists():
            _BUNDLE = joblib.load(_MODEL_PATH)
    return _BUNDLE


# ── Feature maps ──────────────────────────────────────────────────────────────

INSURANCE_MAP = {
    "medicare": 0, "medi-cal": 1, "medicaid": 1,
    "hmo": 2, "blue shield": 2,
    "ppo": 3, "blue cross": 3,
}

ICD10_CHAPTER_MAP = {c: i for i, c in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ")}

ICD10_LOS_ADDEND = {
    "I": 1.2, "J": 1.8, "N": 0.9, "M": 2.1, "K": 1.1,
    "C": 2.8, "S": 1.5, "E": 0.7, "F": 1.9, "G": 1.4,
}

INSURANCE_LOS_ADDEND = {0: 0.3, 1: 0.8, 2: -0.4, 3: -0.2, 4: 0.1}

FEATURE_NAMES = [
    "age", "icd10_chapter", "comorbidity_count", "insurance_type",
    "has_pt", "has_ot", "has_st", "living_alone", "has_caregiver",
    "snf_days_used", "discharge_to_snf", "admission_month",
]

FEATURE_LABELS = {
    "age": "Patient age",
    "icd10_chapter": "Primary diagnosis category",
    "comorbidity_count": "Number of comorbidities",
    "insurance_type": "Insurance / payer type",
    "has_pt": "Physical therapy ordered",
    "has_ot": "Occupational therapy ordered",
    "has_st": "Speech therapy ordered",
    "living_alone": "Lives alone",
    "has_caregiver": "Caregiver available",
    "snf_days_used": "SNF benefit days used",
    "discharge_to_snf": "Planned SNF discharge",
    "admission_month": "Admission month",
}

INCREASES_LOS = {
    "age", "icd10_chapter", "comorbidity_count", "living_alone",
    "snf_days_used", "discharge_to_snf", "has_pt", "has_ot", "has_st",
}


# ── Feature extraction ────────────────────────────────────────────────────────

def extract_features(patient_data: dict) -> list:
    """Extract 12 model features from patient_data dict. Never raises."""

    def safe_int(v, default=0):
        try:
            return int(float(str(v).strip()))
        except Exception:
            return default

    age = max(18, min(99, safe_int(patient_data.get("age", 65), 65)))

    dx = str(patient_data.get("primary_diagnosis", "I")).strip().upper()
    icd_char = dx[0] if dx and dx[0].isalpha() else "I"
    icd10_chapter = ICD10_CHAPTER_MAP.get(icd_char, 8)

    secondary = patient_data.get("secondary_diagnoses", [])
    if isinstance(secondary, str):
        secondary = [l for l in secondary.splitlines() if l.strip()]
    elif not isinstance(secondary, (list, tuple)):
        secondary = []
    comorbidity_count = min(8, len(secondary))

    ins = str(patient_data.get("primary_insurance", "")).lower()
    insurance_type = next((v for k, v in INSURANCE_MAP.items() if k in ins), 4)

    therapy = patient_data.get("therapy_evaluations", {})
    if not isinstance(therapy, dict):
        therapy = {}
    has_pt = 0 if str(therapy.get("PT", "Not evaluated")).lower() == "not evaluated" else 1
    has_ot = 0 if str(therapy.get("OT", "Not evaluated")).lower() == "not evaluated" else 1
    has_st = 0 if str(therapy.get("ST", "Not evaluated")).lower() == "not evaluated" else 1

    living = str(patient_data.get("living_situation", "")).lower()
    living_alone = 1 if "alone" in living else 0

    caregiver = str(patient_data.get("caregiver", "")).strip()
    has_caregiver = 0 if caregiver.lower() in ("", "none", "n/a", "no") else 1

    snf_days = max(0, min(100, safe_int(patient_data.get("snf_days_used", 0), 0)))

    pref = str(patient_data.get("patient_family_preference", "")).lower()
    discharge_to_snf = 1 if any(kw in pref for kw in ("snf", "skilled", "nursing")) else 0

    adm_date = str(patient_data.get("admission_date", ""))
    try:
        admission_month = datetime.date.fromisoformat(adm_date[:10]).month
    except Exception:
        admission_month = 6

    return [age, icd10_chapter, comorbidity_count, insurance_type,
            has_pt, has_ot, has_st, living_alone, has_caregiver,
            snf_days, discharge_to_snf, admission_month]


def _heuristic_los(patient_data: dict) -> tuple[float, float, float]:
    """Fallback when model file is missing. Returns (p10, median, p90)."""
    feats = extract_features(patient_data)
    age, icd_ch, comorbidities, ins, pt, ot, st, living_alone, has_caregiver, snf_days, to_snf, _ = feats
    icd_char = chr(icd_ch + ord("A"))
    base = (3.5 + (age - 18) / 81.0 * 2.0 + comorbidities * 0.6
            + ICD10_LOS_ADDEND.get(icd_char, 0.8)
            + INSURANCE_LOS_ADDEND.get(ins, 0.1)
            + pt * 0.9 + ot * 0.7 + st * 0.4
            + to_snf * 1.1 + living_alone * 0.5 - has_caregiver * 0.6)
    median = max(1.0, round(base, 1))
    return max(1.0, median - 1.5), median, median + 2.0


# ── Prediction result ─────────────────────────────────────────────────────────

@dataclass
class LOSPrediction:
    predicted_los_days: float
    los_p10: float
    los_p90: float
    predicted_discharge_date: str
    earliest_discharge_date: str
    latest_discharge_date: str
    risk_tier: str
    risk_color: str
    top_factors: list
    model_source: str
    model_mae_days: Optional[float]
    confidence_pct: int


def predict_los(patient_data: dict) -> LOSPrediction:
    """Run LOS prediction. Falls back to heuristic if model is missing."""
    bundle = _load_bundle()
    feats = extract_features(patient_data)
    X = [feats]

    if bundle is not None:
        median_los = float(bundle.median_model.predict(X)[0])
        p10_los = float(bundle.p10_model.predict(X)[0])
        p90_los = float(bundle.p90_model.predict(X)[0])
        model_source = "ml_model"
        model_mae = getattr(bundle, "test_mae", None)
        importances = dict(bundle.feature_importances)
    else:
        p10_los, median_los, p90_los = _heuristic_los(patient_data)
        model_source = "heuristic"
        model_mae = None
        importances = {}

    median_los = max(1.0, round(median_los, 1))
    p10_los = max(1.0, round(min(p10_los, median_los), 1))
    p90_los = max(median_los, round(p90_los, 1))

    adm_str = str(patient_data.get("admission_date", ""))
    try:
        adm_date = datetime.date.fromisoformat(adm_str[:10])
    except Exception:
        adm_date = datetime.date.today()

    predicted_discharge = adm_date + datetime.timedelta(days=int(median_los))
    earliest_discharge = adm_date + datetime.timedelta(days=int(p10_los))
    latest_discharge = adm_date + datetime.timedelta(days=int(p90_los))

    if median_los < 4:
        tier, color = "Short", "green"
    elif median_los < 8:
        tier, color = "Moderate", "amber"
    elif median_los <= 14:
        tier, color = "Extended", "orange"
    else:
        tier, color = "Complex", "red"

    top_factors = []
    if importances:
        feat_vals = dict(zip(FEATURE_NAMES, feats))
        sorted_feats = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:3]
        for fname, imp in sorted_feats:
            direction = "↑" if fname in INCREASES_LOS and feat_vals.get(fname, 0) > 0 else "↓"
            top_factors.append({
                "name": fname,
                "label": FEATURE_LABELS.get(fname, fname),
                "value": feat_vals.get(fname),
                "direction": direction,
                "importance": round(imp * 100, 1),
            })

    return LOSPrediction(
        predicted_los_days=median_los,
        los_p10=p10_los,
        los_p90=p90_los,
        predicted_discharge_date=predicted_discharge.isoformat(),
        earliest_discharge_date=earliest_discharge.isoformat(),
        latest_discharge_date=latest_discharge.isoformat(),
        risk_tier=tier,
        risk_color=color,
        top_factors=top_factors,
        model_source=model_source,
        model_mae_days=model_mae,
        confidence_pct=80,
    )


# ── Agent class ───────────────────────────────────────────────────────────────

class PredictiveLOSAgent:
    """ML-based LOS prediction agent — no LLM call, runs synchronously."""

    def __init__(self, client=None):
        _load_bundle()

    async def run(self, patient_data: dict) -> str:
        try:
            pred = predict_los(patient_data)
        except Exception as e:
            return f"LOS prediction unavailable — using heuristic baseline. ({e})"

        lines = [
            "PREDICTIVE DISCHARGE DATE ANALYSIS",
            "",
            f"Predicted LOS:           {pred.predicted_los_days} days",
            f"Predicted discharge:     {pred.predicted_discharge_date}",
            f"80% confidence range:    {pred.earliest_discharge_date} — {pred.latest_discharge_date}",
            f"                         ({pred.los_p10}–{pred.los_p90} days)",
            f"Risk tier:               {pred.risk_tier}",
            f"Model source:            {pred.model_source}",
        ]
        if pred.model_mae_days:
            lines.append(f"Model accuracy (MAE):    ±{pred.model_mae_days:.1f} days on holdout data")
        if pred.top_factors:
            lines.append("")
            lines.append("Top contributing factors:")
            for f in pred.top_factors:
                lines.append(f"  {f['direction']} {f['label']} ({f['importance']}% feature importance)")

        return "\n".join(lines)
