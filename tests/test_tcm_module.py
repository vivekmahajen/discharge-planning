"""Tests for TCM Billing CPT Automation module.

Covers: business day calculator, reimbursement rates, window status engine,
claim generator, and API endpoint auth / validation.

All tests run without a database or real Anthropic API key.
"""
import json
import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock


# ── Business day calculator ───────────────────────────────────────────────────

class TestAddBusinessDays:
    def test_two_days_no_weekend_crosses_nothing(self):
        """Wednesday + 2 business days = Friday (no weekend in between)."""
        from tcm_module import _add_business_days
        wed = date(2026, 5, 20)  # Wednesday
        assert _add_business_days(wed, 2) == date(2026, 5, 22)  # Friday

    def test_two_days_crosses_weekend(self):
        """Friday + 2 business days = Tuesday (skips Saturday and Sunday)."""
        from tcm_module import _add_business_days
        fri = date(2026, 5, 22)  # Friday
        result = _add_business_days(fri, 2)
        assert result == date(2026, 5, 26)  # Tuesday
        assert result.weekday() == 1  # Tuesday

    def test_one_day_friday_gives_monday(self):
        """Friday + 1 business day = Monday."""
        from tcm_module import _add_business_days
        fri = date(2026, 5, 22)
        assert _add_business_days(fri, 1) == date(2026, 5, 25)

    def test_zero_days_returns_same_date(self):
        from tcm_module import _add_business_days
        d = date(2026, 5, 20)
        assert _add_business_days(d, 0) == d

    def test_result_is_never_a_weekend(self):
        """All results must fall on weekdays."""
        from tcm_module import _add_business_days
        for day_offset in range(10):
            start = date(2026, 5, 18) + timedelta(days=day_offset)
            result = _add_business_days(start, 2)
            assert result.weekday() < 5, (
                f"Expected weekday, got {result} (weekday={result.weekday()})"
            )


# ── Reimbursement rates ───────────────────────────────────────────────────────

class TestGetReimbursementRates:
    def test_99495_non_facility_rate(self):
        from tcm_module import _get_reimbursement_rates
        r = _get_reimbursement_rates("99495")
        assert r["code"] == "99495"
        assert r["rate_non_facility"] == pytest.approx(166.28)
        assert r["rate_facility"] == pytest.approx(108.15)

    def test_99496_non_facility_rate(self):
        from tcm_module import _get_reimbursement_rates
        r = _get_reimbursement_rates("99496")
        assert r["code"] == "99496"
        assert r["rate_non_facility"] == pytest.approx(228.14)
        assert r["rate_facility"] == pytest.approx(153.91)

    def test_99496_higher_than_99495(self):
        """High complexity (99496) always reimburses more than moderate (99495)."""
        from tcm_module import _get_reimbursement_rates
        r95 = _get_reimbursement_rates("99495")
        r96 = _get_reimbursement_rates("99496")
        assert r96["rate_non_facility"] > r95["rate_non_facility"]

    def test_unknown_code_returns_zero_rates(self):
        from tcm_module import _get_reimbursement_rates
        r = _get_reimbursement_rates("not_eligible")
        assert r["rate_non_facility"] == 0.0
        assert r["rate_facility"] == 0.0

    def test_none_code_returns_zero_rates(self):
        from tcm_module import _get_reimbursement_rates
        r = _get_reimbursement_rates(None)
        assert r["rate_non_facility"] == 0.0


# ── Window status computation ─────────────────────────────────────────────────

def _make_episode(cpt: str = "99495", days_ago: int = 1) -> dict:
    """Build a minimal episode dict."""
    return {
        "id": "ep-test-001",
        "discharge_date": date.today() - timedelta(days=days_ago),
        "recommended_cpt": cpt,
        "cpt_final": None,
        "mdm_complexity": "moderate",
        "mdm_rationale": "Test rationale",
        "patient_name": "Test Patient",
    }


def _make_contact(result: str = "reached", days_ago: int = 0) -> dict:
    """Build a minimal contact dict."""
    return {
        "contact_date": str(date.today() - timedelta(days=days_ago)),
        "contact_time": "10:00:00",
        "contact_method": "phone",
        "contact_result": result,
        "contacted_by": "Nurse Johnson",
    }


def _make_visit(days_ago: int = 0) -> dict:
    return {
        "visit_date": str(date.today() - timedelta(days=days_ago)),
        "visit_type": "office",
        "provider_npi": "1234567890",
        "provider_name": "Dr. Smith",
    }


class TestComputeWindowStatus:
    def test_pending_contact_is_green_same_day_discharge(self):
        from tcm_module import compute_window_status, TCMStatus
        ep = _make_episode(days_ago=0)
        ws = compute_window_status(ep, [], [])
        assert ws.overall_status == TCMStatus.PENDING_CONTACT
        assert ws.alert_level == "green"
        assert ws.contact_completed is False
        assert ws.claim_eligible is False

    def test_contact_overdue_when_past_deadline_no_contact(self):
        from tcm_module import compute_window_status, TCMStatus
        # Discharge 10 days ago, no contact = well past 2-business-day window
        ep = _make_episode(days_ago=10)
        ws = compute_window_status(ep, [], [])
        assert ws.overall_status == TCMStatus.CONTACT_OVERDUE
        assert ws.alert_level == "red"
        assert ws.contact_overdue is True
        assert ws.claim_eligible is False

    def test_contact_completed_pending_visit(self):
        from tcm_module import compute_window_status, TCMStatus
        ep = _make_episode(days_ago=3)
        ws = compute_window_status(ep, [_make_contact("reached", days_ago=2)], [])
        assert ws.overall_status == TCMStatus.VISIT_SCHEDULED
        assert ws.contact_completed is True
        assert ws.visit_completed is False
        assert ws.claim_eligible is False

    def test_claim_ready_when_both_complete(self):
        from tcm_module import compute_window_status, TCMStatus
        ep = _make_episode(days_ago=5)
        ws = compute_window_status(
            ep, [_make_contact("reached", days_ago=3)], [_make_visit(days_ago=1)])
        assert ws.overall_status == TCMStatus.CLAIM_READY
        assert ws.claim_eligible is True
        assert ws.alert_level == "green"

    def test_99496_has_7_day_visit_window(self):
        from tcm_module import compute_window_status
        ep = _make_episode(cpt="99496", days_ago=1)
        ws = compute_window_status(ep, [], [])
        expected_deadline = date.today() - timedelta(days=1) + timedelta(days=7)
        assert ws.visit_deadline == expected_deadline

    def test_99495_has_14_day_visit_window(self):
        from tcm_module import compute_window_status
        ep = _make_episode(cpt="99495", days_ago=1)
        ws = compute_window_status(ep, [], [])
        expected_deadline = date.today() - timedelta(days=1) + timedelta(days=14)
        assert ws.visit_deadline == expected_deadline

    def test_non_qualifying_contact_does_not_count(self):
        from tcm_module import compute_window_status, TCMStatus
        ep = _make_episode(days_ago=1)
        voicemail = _make_contact("left_voicemail", days_ago=0)
        ws = compute_window_status(ep, [voicemail], [])
        assert ws.contact_completed is False
        assert ws.overall_status == TCMStatus.PENDING_CONTACT

    def test_visit_overdue_when_past_14_days_no_visit(self):
        from tcm_module import compute_window_status, TCMStatus
        # Discharge 16 days ago, contact made day 1, no visit = past 14-day window
        ep = _make_episode(cpt="99495", days_ago=16)
        ws = compute_window_status(ep, [_make_contact("reached", days_ago=15)], [])
        assert ws.visit_overdue is True
        assert ws.overall_status == TCMStatus.VISIT_OVERDUE
        assert ws.claim_eligible is False

    def test_discharge_date_as_string_is_parsed(self):
        """compute_window_status must handle ISO string discharge_date from DB."""
        from tcm_module import compute_window_status
        ep = {
            "id": "ep-str-date",
            "discharge_date": str(date.today() - timedelta(days=2)),
            "recommended_cpt": "99495",
            "cpt_final": None,
        }
        ws = compute_window_status(ep, [_make_contact("reached", days_ago=1)], [])
        assert ws.contact_completed is True


# ── Claim generation ──────────────────────────────────────────────────────────

class TestGenerateTcmClaim:
    def _ready_episode(self) -> dict:
        return {
            "id": "ep-claim-001",
            "discharge_date": date.today() - timedelta(days=5),
            "discharge_setting": "inpatient_hospital",
            "recommended_cpt": "99495",
            "cpt_final": None,
            "cpt_override": None,
            "mdm_complexity": "moderate",
            "mdm_rationale": "CHF + DM2 with systemic symptoms",
            "mdm_assessed_by": "ai_assisted",
            "patient_name": "Jane Doe",
            "patient_dob": "1950-03-15",
            "patient_medicare_id": "1EG4-TE5-MK72",
            "practice_tin": "123456789",
            "practice_npi": "9876543210",
        }

    def _ready_contact(self) -> dict:
        return {
            "contact_date": str(date.today() - timedelta(days=3)),
            "contact_time": "09:30:00",
            "contact_method": "phone",
            "contact_result": "reached",
            "contacted_by": "RN Martinez",
        }

    def _ready_visit(self) -> dict:
        return {
            "visit_date": str(date.today() - timedelta(days=1)),
            "visit_type": "office",
            "provider_npi": "1234567890",
            "provider_name": "Dr. Williams",
        }

    def _mdm(self) -> dict:
        return {
            "key_diagnoses": ["I50.9: CHF unspecified", "E11.9: T2DM without complications"],
            "element1_assessment": {"rationale": "Multiple chronic conditions (E1 moderate)"},
            "element2_assessment": {"rationale": "Med review + external notes (E2 high)"},
            "element3_assessment": {"rationale": "Prescription drug management (E3 moderate)"},
        }

    def test_generates_claimable_record(self):
        from tcm_module import generate_tcm_claim
        claim = generate_tcm_claim(
            self._ready_episode(), [self._ready_contact()], [self._ready_visit()], self._mdm())
        assert claim["claimable"] is True
        assert claim["cpt_code"] == "99495"
        assert claim["charge_amount"] == pytest.approx(166.28)

    def test_claim_contains_audit_trail(self):
        from tcm_module import generate_tcm_claim
        claim = generate_tcm_claim(
            self._ready_episode(), [self._ready_contact()], [self._ready_visit()], self._mdm())
        audit = claim["audit_trail"]
        assert audit["all_requirements_met"] is True
        assert "CMS" in audit["cms_reference"]
        assert "contact_window_met" in audit
        assert "visit_window_met" in audit

    def test_claim_contains_icd10_primary(self):
        from tcm_module import generate_tcm_claim
        claim = generate_tcm_claim(
            self._ready_episode(), [self._ready_contact()], [self._ready_visit()], self._mdm())
        assert claim["icd10_primary"] == "I50.9"
        assert "E11.9" in claim["icd10_secondary"]

    def test_not_claimable_when_contact_overdue(self):
        from tcm_module import generate_tcm_claim
        ep = self._ready_episode()
        ep["discharge_date"] = date.today() - timedelta(days=20)
        claim = generate_tcm_claim(ep, [], [], self._mdm())
        assert claim["claimable"] is False
        assert "reason" in claim

    def test_not_claimable_when_visit_missing(self):
        from tcm_module import generate_tcm_claim
        claim = generate_tcm_claim(
            self._ready_episode(), [self._ready_contact()], [], self._mdm())
        assert claim["claimable"] is False

    def test_99496_uses_higher_rate(self):
        from tcm_module import generate_tcm_claim
        ep = self._ready_episode()
        ep["recommended_cpt"] = "99496"
        claim = generate_tcm_claim(ep, [self._ready_contact()], [self._ready_visit()], self._mdm())
        assert claim["claimable"] is True
        assert claim["cpt_code"] == "99496"
        assert claim["charge_amount"] == pytest.approx(228.14)


# ── API endpoint auth and validation ─────────────────────────────────────────

class TestTcmEndpointAuth:
    async def test_dashboard_unauthenticated_returns_401(self, client):
        r = await client.get("/api/tcm/dashboard")
        assert r.status_code == 401

    async def test_create_episode_unauthenticated_returns_401(self, client):
        r = await client.post("/api/tcm/episodes", json={})
        assert r.status_code == 401

    async def test_record_contact_unauthenticated_returns_401(self, client):
        r = await client.post("/api/tcm/episodes/some-id/contacts", json={})
        assert r.status_code == 401

    async def test_record_visit_unauthenticated_returns_401(self, client):
        r = await client.post("/api/tcm/episodes/some-id/visits", json={})
        assert r.status_code == 401

    async def test_get_episode_unauthenticated_returns_401(self, client):
        r = await client.get("/api/tcm/episodes/some-id")
        assert r.status_code == 401

    async def test_generate_claim_unauthenticated_returns_401(self, client):
        r = await client.post("/api/tcm/episodes/some-id/generate-claim")
        assert r.status_code == 401


class TestTcmEndpointValidation:
    """Validation tests that run before any DB call — work in file mode (returns 503 or 400)."""

    async def test_dashboard_authenticated_returns_200_in_file_mode(self, authed_client):
        """Dashboard returns empty data (not 503) in file mode for usability."""
        r = await authed_client.get("/api/tcm/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert "episodes" in body
        assert body["total_active"] == 0

    async def test_create_episode_missing_fields_returns_400(self, authed_client):
        r = await authed_client.post("/api/tcm/episodes", json={
            "patient_mrn": "MRN001"
        })
        assert r.status_code == 400

    async def test_create_episode_invalid_setting_returns_400(self, authed_client):
        r = await authed_client.post("/api/tcm/episodes", json={
            "patient_mrn": "MRN001",
            "patient_name": "John Doe",
            "discharge_date": "2026-05-01",
            "discharge_setting": "ed_no_admission",
            "discharge_diagnosis": "CHF",
            "attending_provider_npi": "1234567890",
            "attending_provider_name": "Dr. Smith",
            "discharge_plan_text": "Plan text here.",
        })
        assert r.status_code == 400

    async def test_create_episode_invalid_date_returns_400(self, authed_client):
        r = await authed_client.post("/api/tcm/episodes", json={
            "patient_mrn": "MRN001",
            "patient_name": "John Doe",
            "discharge_date": "not-a-date",
            "discharge_setting": "inpatient_hospital",
            "discharge_diagnosis": "CHF",
            "attending_provider_npi": "1234567890",
            "attending_provider_name": "Dr. Smith",
            "discharge_plan_text": "Plan text here.",
        })
        assert r.status_code == 400

    async def test_record_contact_missing_fields_returns_400(self, authed_client):
        r = await authed_client.post("/api/tcm/episodes/some-id/contacts", json={})
        assert r.status_code == 400

    async def test_record_contact_invalid_method_returns_400(self, authed_client):
        r = await authed_client.post("/api/tcm/episodes/some-id/contacts", json={
            "contact_date": "2026-05-01",
            "contact_time": "09:00:00",
            "contact_method": "carrier_pigeon",
            "contact_result": "reached",
            "contacted_by": "Nurse",
        })
        assert r.status_code == 400

    async def test_record_contact_invalid_result_returns_400(self, authed_client):
        r = await authed_client.post("/api/tcm/episodes/some-id/contacts", json={
            "contact_date": "2026-05-01",
            "contact_time": "09:00:00",
            "contact_method": "phone",
            "contact_result": "hung_up",
            "contacted_by": "Nurse",
        })
        assert r.status_code == 400

    async def test_record_visit_missing_fields_returns_400(self, authed_client):
        r = await authed_client.post("/api/tcm/episodes/some-id/visits", json={})
        assert r.status_code == 400

    async def test_create_episode_valid_data_requires_db(self, authed_client):
        """All validation passes, but DATABASE_URL is None → 503."""
        r = await authed_client.post("/api/tcm/episodes", json={
            "patient_mrn": "MRN999",
            "patient_name": "Jane Doe",
            "discharge_date": "2026-05-01",
            "discharge_setting": "inpatient_hospital",
            "discharge_diagnosis": "CHF exacerbation",
            "attending_provider_npi": "1234567890",
            "attending_provider_name": "Dr. Smith",
            "discharge_plan_text": "Discharge with home health follow-up.",
        })
        assert r.status_code == 503

    async def test_record_contact_valid_data_requires_db(self, authed_client):
        """All validation passes for contact → 503 without a database."""
        r = await authed_client.post("/api/tcm/episodes/some-id/contacts", json={
            "contact_date": "2026-05-01",
            "contact_time": "09:00:00",
            "contact_method": "phone",
            "contact_result": "reached",
            "contacted_by": "Nurse Smith",
        })
        assert r.status_code == 503

    async def test_record_visit_valid_data_requires_db(self, authed_client):
        """All validation passes for visit → 503 without a database."""
        r = await authed_client.post("/api/tcm/episodes/some-id/visits", json={
            "visit_date": "2026-05-01",
            "visit_type": "office",
            "provider_npi": "1234567890",
            "provider_name": "Dr. Williams",
        })
        assert r.status_code == 503

    async def test_claims_export_requires_db(self, authed_client):
        r = await authed_client.get("/api/tcm/claims/export")
        assert r.status_code == 503

    async def test_get_single_episode_requires_db(self, authed_client):
        r = await authed_client.get("/api/tcm/episodes/some-uuid-here")
        assert r.status_code == 503


# ── DB-mode tests (DATABASE_URL mocked, db functions stubbed) ─────────────────

class TestTcmDbMode:
    """Tests that exercise the DB-code paths using the db_authed_client fixture."""

    async def test_dashboard_db_mode_returns_200_with_empty_episodes(self, db_authed_client):
        """In DB mode with no active episodes, dashboard returns a valid empty payload."""
        r = await db_authed_client.get("/api/tcm/dashboard")
        assert r.status_code == 200
        body = r.json()
        assert "episodes" in body
        assert body["total_active"] == 0
        assert body["red_alerts"] == 0
        assert body["claim_ready"] == 0
        assert body["estimated_monthly_revenue"] == 0

    async def test_get_episode_not_found_returns_404(self, db_authed_client):
        """Episode lookup returns 404 when the db stub returns None."""
        r = await db_authed_client.get("/api/tcm/episodes/nonexistent-id")
        assert r.status_code == 404
        assert "not found" in r.json()["error"].lower()

    async def test_record_contact_valid_persists_and_returns_ok(self, db_authed_client):
        """Valid contact data goes through to the (mocked) DB and returns ok."""
        r = await db_authed_client.post("/api/tcm/episodes/ep-001/contacts", json={
            "contact_date": "2026-05-01",
            "contact_time": "09:00:00",
            "contact_method": "phone",
            "contact_result": "reached",
            "contacted_by": "Nurse Martinez",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["qualifying"] is True

    async def test_record_visit_valid_persists_and_returns_ok(self, db_authed_client):
        """Valid visit data goes through to the (mocked) DB and returns ok."""
        r = await db_authed_client.post("/api/tcm/episodes/ep-001/visits", json={
            "visit_date": "2026-05-01",
            "visit_type": "office",
            "provider_npi": "1234567890",
            "provider_name": "Dr. Williams",
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ── Predictive LOS endpoint tests ─────────────────────────────────────────────

class TestPredictiveLosEndpoint:
    """Tests for /api/predict/los and /predictive-discharge page."""

    async def test_predict_los_unauthenticated_returns_401(self, client):
        r = await client.post("/api/predict/los", json={})
        assert r.status_code == 401

    async def test_predict_los_returns_prediction(self, authed_client):
        """Authenticated request returns a valid LOS prediction."""
        r = await authed_client.post("/api/predict/los", json={
            "patient_data": {
                "age": "72",
                "admission_date": "2026-05-01",
                "primary_diagnosis": "I50.9 Congestive Heart Failure",
                "primary_insurance": "Medicare",
                "secondary_diagnoses": "E11.9 Type 2 Diabetes\nN18.3 CKD stage 3\nI10 Hypertension",
                "living_situation": "Lives alone",
                "caregiver": "None",
                "snf_days_used": "0",
                "patient_family_preference": "Home with PT",
                "therapy_evaluations": {"PT": "Ordered", "OT": "Not evaluated", "ST": "Not evaluated"},
            }
        })
        assert r.status_code == 200
        body = r.json()
        assert body["success"] is True
        pred = body["prediction"]
        assert pred["predicted_los_days"] >= 1
        assert pred["predicted_discharge_date"] >= "2026-05-01"
        assert pred["risk_tier"] in ("Short", "Moderate", "Extended", "Complex")
        assert pred["los_p10"] <= pred["predicted_los_days"] <= pred["los_p90"]
        assert len(pred["top_factors"]) > 0

    async def test_predict_los_72yo_chf_is_moderate_or_extended(self, authed_client):
        """Sample 72yo Medicare CHF patient with 3 comorbidities should predict 6–10 days."""
        r = await authed_client.post("/api/predict/los", json={
            "patient_data": {
                "age": "72",
                "primary_diagnosis": "I50.9",
                "primary_insurance": "Medicare",
                "secondary_diagnoses": "E11.9\nN18.3\nI10",
                "admission_date": "2026-05-01",
                "caregiver": "None",
                "living_situation": "Lives alone",
            }
        })
        assert r.status_code == 200
        pred = r.json()["prediction"]
        # Should predict between 4 and 14 days (Moderate or Extended tier)
        assert 4 <= pred["predicted_los_days"] <= 14
        assert pred["risk_tier"] in ("Moderate", "Extended")

    async def test_predict_los_flat_payload_accepted(self, authed_client):
        """Endpoint accepts flat patient_data (no nesting) for convenience."""
        r = await authed_client.post("/api/predict/los", json={
            "age": "65",
            "primary_diagnosis": "J18.9",
            "primary_insurance": "PPO",
        })
        assert r.status_code == 200
        assert r.json()["success"] is True

    async def test_predictive_discharge_page_loads(self, authed_client):
        r = await authed_client.get("/predictive-discharge")
        assert r.status_code == 200
        assert "Predictive Discharge Date" in r.text
        assert "Gradient Boosting" in r.text
