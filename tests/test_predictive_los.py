"""Predictive Length-of-Stay tests — feature extraction, tier boundaries, invariants.

Covers spec section 11 (LOS-001 … LOS-011). `agents/*` is excluded from the
coverage config, so these cases close a documented coverage gap.

The model file (`models/los_model.joblib`) may or may not load depending on the
local scikit-learn version, so every test pins the module's bundle state
explicitly (heuristic vs. a synthetic ML bundle) for deterministic results.
"""
import datetime

import pytest

import agents.predictive_los as plos
from agents.predictive_los import (
    FEATURE_NAMES,
    LOSModelBundle,
    extract_features,
    predict_los,
)


# ── Fixtures ────────────────────────────────────────────────────────────────

class _FakeModel:
    """Constant-output regressor stand-in."""

    def __init__(self, value):
        self.value = value

    def predict(self, X):
        return [self.value]


@pytest.fixture
def heuristic_mode(monkeypatch):
    """Force the heuristic path (no ML bundle), independent of the joblib file."""
    monkeypatch.setattr(plos, "_BUNDLE", None)
    monkeypatch.setattr(plos, "_BUNDLE_LOADED", True)


@pytest.fixture
def ml_bundle(monkeypatch):
    """Install a synthetic ML bundle producing a controllable (p10, median, p90)."""

    def _install(median, p10, p90):
        bundle = LOSModelBundle(
            median_model=_FakeModel(median),
            p10_model=_FakeModel(p10),
            p90_model=_FakeModel(p90),
            feature_names=FEATURE_NAMES,
            feature_importances=[
                ("age", 0.5), ("comorbidity_count", 0.3), ("icd10_chapter", 0.2),
            ],
            trained_at="2026-01-01T00:00:00Z",
            training_samples=5000,
            test_mae=1.3,
            test_r2=0.82,
        )
        monkeypatch.setattr(plos, "_BUNDLE", bundle)
        monkeypatch.setattr(plos, "_BUNDLE_LOADED", True)
        return bundle

    return _install


# ── LOS-011 / feature extraction never raises ───────────────────────────────

class TestExtractFeatures:
    def test_returns_twelve_features(self):
        feats = extract_features({"age": 70, "primary_diagnosis": "I50"})
        assert isinstance(feats, list)
        assert len(feats) == 12

    def test_empty_dict_returns_defaults(self):
        feats = extract_features({})
        assert len(feats) == 12
        # age default 65, icd chapter for 'I' == 8, admission_month default 6
        assert feats[0] == 65
        assert feats[1] == 8
        assert feats[11] == 6

    @pytest.mark.parametrize("bad", [
        {"age": "abc", "secondary_diagnoses": None, "therapy_evaluations": "nope"},
        {"age": ["a", "list"], "primary_diagnosis": None},
        {"secondary_diagnoses": 12345, "snf_days_used": "lots"},
        {"living_situation": None, "caregiver": None, "admission_date": "garbage"},
        {"primary_diagnosis": 42, "primary_insurance": None},
    ])
    def test_weird_inputs_never_raise(self, bad):
        feats = extract_features(bad)
        assert len(feats) == 12
        assert all(isinstance(f, int) for f in feats)

    @pytest.mark.parametrize("raw_age,expected", [
        ("abc", 65),   # unparseable → default 65
        (5, 18),       # below floor → clamp to 18
        (200, 99),     # above ceiling → clamp to 99
        ("88", 88),    # numeric string parsed
    ])
    def test_age_clamped(self, raw_age, expected):
        assert extract_features({"age": raw_age})[0] == expected

    def test_icd10_chapter_mapping(self):
        # 'J' is the 10th letter → index 9
        assert extract_features({"primary_diagnosis": "J18.9"})[1] == 9
        # Non-alpha leading char falls back to 'I' (index 8)
        assert extract_features({"primary_diagnosis": "123"})[1] == 8

    def test_insurance_mapping(self):
        assert extract_features({"primary_insurance": "Medicare"})[3] == 0
        assert extract_features({"primary_insurance": "Medi-Cal MCP"})[3] == 1
        # Unknown payer → 4
        assert extract_features({"primary_insurance": "SelfPay"})[3] == 4

    def test_therapy_flags(self):
        feats = extract_features({"therapy_evaluations": {
            "PT": "Recommended", "OT": "Not evaluated", "ST": "Not evaluated"}})
        assert feats[4] == 1  # has_pt
        assert feats[5] == 0  # has_ot
        assert feats[6] == 0  # has_st

    def test_living_alone_and_caregiver(self):
        feats = extract_features({
            "living_situation": "Lives alone in apartment", "caregiver": "none"})
        assert feats[7] == 1  # living_alone
        assert feats[8] == 0  # has_caregiver (none → 0)
        feats2 = extract_features({
            "living_situation": "Lives with spouse", "caregiver": "Daughter"})
        assert feats2[7] == 0
        assert feats2[8] == 1

    def test_comorbidity_count_from_string_and_capped(self):
        many = "\n".join(f"dx{i}" for i in range(20))
        assert extract_features({"secondary_diagnoses": many})[2] == 8  # capped at 8


# ── LOS-002 / LOS-007 / LOS-009 — predict_los invariants (heuristic) ─────────

class TestPredictLosHeuristic:
    def test_heuristic_source_when_model_absent(self, heuristic_mode):
        pred = predict_los({"age": 70, "primary_diagnosis": "I50"})
        assert pred.model_source == "heuristic"
        assert pred.model_mae_days is None
        assert pred.top_factors == []

    def test_percentile_invariant(self, heuristic_mode):
        pred = predict_los({"age": 80, "primary_diagnosis": "C50",
                            "secondary_diagnoses": "a\nb\nc"})
        assert pred.los_p10 <= pred.predicted_los_days <= pred.los_p90
        assert pred.los_p10 >= 1.0
        assert pred.predicted_los_days >= 1.0

    def test_empty_patient_data_does_not_raise(self, heuristic_mode):
        pred = predict_los({})
        assert pred.predicted_los_days >= 1.0
        assert pred.risk_tier in {"Short", "Moderate", "Extended", "Complex"}

    def test_missing_admission_date_uses_today(self, heuristic_mode):
        pred = predict_los({"age": 70})
        today = datetime.date.today()
        disc = datetime.date.fromisoformat(pred.predicted_discharge_date)
        # discharge = today + int(median); median small, so within a month
        assert today <= disc <= today + datetime.timedelta(days=60)

    def test_confidence_pct_default(self, heuristic_mode):
        assert predict_los({}).confidence_pct == 80


# ── LOS-003 — risk tier mapping (via controllable ML bundle) ─────────────────

class TestRiskTierMapping:
    @pytest.mark.parametrize("median,tier,color", [
        (3.0, "Short", "green"),
        (3.9, "Short", "green"),
        (4.0, "Moderate", "amber"),
        (7.0, "Moderate", "amber"),
        (8.0, "Extended", "orange"),
        (14.0, "Extended", "orange"),
        (15.0, "Complex", "red"),
        (25.0, "Complex", "red"),
    ])
    def test_tier_boundaries(self, ml_bundle, median, tier, color):
        ml_bundle(median=median, p10=max(1.0, median - 2), p90=median + 3)
        pred = predict_los({"age": 70, "primary_diagnosis": "I50"})
        assert pred.risk_tier == tier
        assert pred.risk_color == color


# ── LOS-004 — discharge date arithmetic ──────────────────────────────────────

class TestDischargeDates:
    def test_discharge_date_is_admission_plus_median(self, ml_bundle):
        ml_bundle(median=10.0, p10=6.0, p90=16.0)
        pred = predict_los({"primary_diagnosis": "I50", "admission_date": "2026-01-01"})
        assert pred.predicted_discharge_date == "2026-01-11"
        assert pred.earliest_discharge_date == "2026-01-07"   # +p10 (6)
        assert pred.latest_discharge_date == "2026-01-17"     # +p90 (16)

    def test_admission_date_with_time_component(self, ml_bundle):
        ml_bundle(median=5.0, p10=3.0, p90=9.0)
        pred = predict_los({"admission_date": "2026-03-10T08:30:00"})
        assert pred.predicted_discharge_date == "2026-03-15"


# ── LOS-008 — ML path reports source + top factors ───────────────────────────

class TestPredictLosMlPath:
    def test_ml_source_and_mae(self, ml_bundle):
        ml_bundle(median=9.0, p10=5.0, p90=15.0)
        pred = predict_los({"age": 80, "primary_diagnosis": "I50"})
        assert pred.model_source == "ml_model"
        assert pred.model_mae_days == 1.3

    def test_top_factors_populated(self, ml_bundle):
        ml_bundle(median=9.0, p10=5.0, p90=15.0)
        pred = predict_los({"age": 80, "primary_diagnosis": "I50"})
        assert len(pred.top_factors) == 3
        first = pred.top_factors[0]
        assert {"name", "label", "value", "direction", "importance"} <= set(first)
        assert first["direction"] in {"↑", "↓"}


# ── LOS-001 / LOS-010 — HTTP endpoint ────────────────────────────────────────

class TestPredictLosEndpoint:
    async def test_success_shape(self, authed_client, heuristic_mode):
        r = await authed_client.post("/api/predict/los", json={"patient_data": {
            "age": 72, "primary_diagnosis": "I50", "admission_date": "2026-01-01"}})
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        pred = body["prediction"]
        for key in ("predicted_los_days", "los_p10", "los_p90",
                    "predicted_discharge_date", "risk_tier", "risk_color",
                    "model_source", "confidence_pct"):
            assert key in pred
        assert pred["los_p10"] <= pred["predicted_los_days"] <= pred["los_p90"]

    async def test_accepts_bare_body(self, authed_client, heuristic_mode):
        # Endpoint falls back to the whole body when "patient_data" key is absent.
        r = await authed_client.post("/api/predict/los",
                                     json={"age": 65, "primary_diagnosis": "J18"})
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_unauthenticated_returns_401(self, client):
        r = await client.post("/api/predict/los", json={"patient_data": {}})
        assert r.status_code == 401
