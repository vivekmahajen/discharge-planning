"""Training script — generate synthetic CA hospital data and train LOS models.

Run once from the project root:
    python scripts/train_los_model.py

Output: models/los_model.joblib (~200 KB)
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

PROJECT_ROOT = Path(__file__).parent.parent
MODELS_DIR = PROJECT_ROOT / "models"
MODELS_DIR.mkdir(exist_ok=True)
OUTPUT_PATH = MODELS_DIR / "los_model.joblib"

# Import LOSModelBundle from agents so joblib serialises with the correct path
import sys
sys.path.insert(0, str(PROJECT_ROOT))
from agents.predictive_los import LOSModelBundle  # noqa: E402

FEATURE_NAMES = [
    "age", "icd10_chapter", "comorbidity_count", "insurance_type",
    "has_pt", "has_ot", "has_st", "living_alone", "has_caregiver",
    "snf_days_used", "discharge_to_snf", "admission_month",
]

ICD10_CHAPTERS = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
ICD10_WEIGHTS = {
    "I": 0.22, "J": 0.15, "N": 0.12, "M": 0.10, "K": 0.09,
    "E": 0.08, "S": 0.07, "C": 0.06,
}
# Distribute remaining 11% across remaining 18 chapters
_remaining_chapters = [c for c in ICD10_CHAPTERS if c not in ICD10_WEIGHTS]
_remaining_weight = (1.0 - sum(ICD10_WEIGHTS.values())) / len(_remaining_chapters)
for _c in _remaining_chapters:
    ICD10_WEIGHTS[_c] = _remaining_weight

ICD10_LOS_ADDEND = {
    "I": 1.2, "J": 1.8, "N": 0.9, "M": 2.1, "K": 1.1,
    "C": 2.8, "S": 1.5, "E": 0.7, "F": 1.9, "G": 1.4,
}
INSURANCE_LOS_ADDEND = {0: 0.3, 1: 0.8, 2: -0.4, 3: -0.2, 4: 0.1}



def generate_synthetic_data(n: int = 50_000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)

    # Age: normal(68, 18), clipped 18–99
    age = rng.normal(68, 18, n).clip(18, 99).astype(int)

    # ICD-10 chapter: weighted sample A–Z → encoded 0–25
    chapters = list(ICD10_WEIGHTS.keys())
    weights = np.array([ICD10_WEIGHTS[c] for c in chapters])
    weights /= weights.sum()
    icd_chars = rng.choice(chapters, size=n, p=weights)
    icd10_chapter = np.array([ord(c) - ord("A") for c in icd_chars])

    # Comorbidities: Poisson(2.3) clipped 0–8
    comorbidity_count = rng.poisson(2.3, n).clip(0, 8)

    # Insurance: Medicare=45%, Medi-Cal=28%, HMO=15%, PPO=8%, Other=4%
    ins_probs = [0.45, 0.28, 0.15, 0.08, 0.04]
    insurance_type = rng.choice(5, size=n, p=ins_probs)

    # Therapy — correlated with comorbidities and icd10 chapter
    therapy_base = (comorbidity_count / 8.0) * 0.7
    has_pt = (rng.random(n) < (therapy_base + 0.15)).astype(int)
    has_ot = (rng.random(n) < (therapy_base + 0.10)).astype(int)
    has_st = (rng.random(n) < (therapy_base + 0.05)).astype(int)

    living_alone = (rng.random(n) < 0.35).astype(int)
    has_caregiver = (rng.random(n) < 0.60).astype(int)

    # SNF days: Medicare patients accumulate more SNF days
    is_medicare = (insurance_type == 0).astype(float)
    snf_days_used = (rng.poisson(8, n) * is_medicare).clip(0, 100).astype(int)

    discharge_to_snf = (rng.random(n) < 0.28).astype(int)
    admission_month = rng.integers(1, 13, n)

    X = np.column_stack([
        age, icd10_chapter, comorbidity_count, insurance_type,
        has_pt, has_ot, has_st, living_alone, has_caregiver,
        snf_days_used, discharge_to_snf, admission_month,
    ])

    # LOS target — deterministic formula + noise
    base_los = np.full(n, 3.5)
    age_factor = (age - 18) / 81.0 * 2.0
    comorbidity_factor = comorbidity_count * 0.6
    icd_factor = np.array([ICD10_LOS_ADDEND.get(c, 0.8) for c in icd_chars])
    ins_factor = np.array([INSURANCE_LOS_ADDEND[i] for i in insurance_type])
    therapy_factor = has_pt * 0.9 + has_ot * 0.7 + has_st * 0.4
    snf_factor = discharge_to_snf * 1.1
    caregiver_factor = np.where(has_caregiver, -0.6, 0.0)
    living_factor = living_alone * 0.5
    noise = rng.normal(0, 1.2, n)

    los_raw = (base_los + age_factor + comorbidity_factor + icd_factor
               + ins_factor + therapy_factor + snf_factor
               + caregiver_factor + living_factor + noise)
    y = np.maximum(1, np.round(los_raw)).astype(float)

    return X, y


def train() -> None:
    print("Generating 50,000 synthetic CA hospital admissions...")
    X, y = generate_synthetic_data(50_000)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42)

    gbr_kwargs = dict(n_estimators=200, max_depth=4, learning_rate=0.05, random_state=42)

    print("Training median model (squared_error)...")
    median_model = GradientBoostingRegressor(loss="squared_error", **gbr_kwargs)
    median_model.fit(X_train, y_train)

    print("Training p10 model (quantile α=0.10)...")
    p10_model = GradientBoostingRegressor(loss="quantile", alpha=0.1, **gbr_kwargs)
    p10_model.fit(X_train, y_train)

    print("Training p90 model (quantile α=0.90)...")
    p90_model = GradientBoostingRegressor(loss="quantile", alpha=0.9, **gbr_kwargs)
    p90_model.fit(X_train, y_train)

    y_pred = median_model.predict(X_test)
    mae = mean_absolute_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    importances = list(zip(FEATURE_NAMES, median_model.feature_importances_))
    importances.sort(key=lambda x: x[1], reverse=True)

    print("\nFeature importances (ranked):")
    for name, imp in importances:
        print(f"  {imp:5.1%}  {name}")

    bundle = LOSModelBundle(
        median_model=median_model,
        p10_model=p10_model,
        p90_model=p90_model,
        feature_names=FEATURE_NAMES,
        feature_importances=importances,
        trained_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        training_samples=len(X_train),
        test_mae=round(mae, 3),
        test_r2=round(r2, 4),
    )

    joblib.dump(bundle, OUTPUT_PATH, compress=3)
    size_kb = OUTPUT_PATH.stat().st_size // 1024
    print(f"\nModel saved to {OUTPUT_PATH}")
    print(f"Size: {size_kb} KB  |  MAE: {mae:.2f} days  |  R²: {r2:.3f}")


if __name__ == "__main__":
    train()
