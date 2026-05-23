"""Tests for the parallel multi-agent orchestrator.

Covers: all-agents-succeed, one-agent-fails, all-agents-fail, error isolation,
parallel execution, error marker in coordinator input.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from orchestrator import DischargeOrchestrator
from sample_patient import SAMPLE_PATIENT

GOOD_OUTPUT = "Clinical assessment: Patient is stable for discharge."

_AGENT_PATCHES = [
    "orchestrator.ClinicalAssessmentAgent",
    "orchestrator.CareNeedsAgent",
    "orchestrator.InsuranceAuthorizationAgent",
    "orchestrator.MedicationReconciliationAgent",
    "orchestrator.SocialDeterminantsAgent",
]


def _mock_all_agents_good(mocks):
    for m in mocks:
        m.return_value.run = AsyncMock(return_value=GOOD_OUTPUT)


class TestOrchestratorHappyPath:
    async def test_all_agents_succeed_returns_coordinator_output(self):
        coordinator_output = "## Final discharge plan — all agents succeeded"
        with patch(_AGENT_PATCHES[0]) as C1, patch(_AGENT_PATCHES[1]) as C2, \
             patch(_AGENT_PATCHES[2]) as C3, patch(_AGENT_PATCHES[3]) as C4, \
             patch(_AGENT_PATCHES[4]) as C5, \
             patch("orchestrator.CoordinatorAgent") as CC:
            _mock_all_agents_good([C1, C2, C3, C4, C5])
            CC.return_value.run = AsyncMock(return_value=coordinator_output)
            orc = DischargeOrchestrator(api_key="test")
            result = await orc.run(SAMPLE_PATIENT)
        assert result == coordinator_output

    async def test_coordinator_receives_all_five_outputs(self):
        captured = {}

        async def fake_coordinator_run(agent_outputs):
            captured.update(agent_outputs)
            return "done"

        with patch(_AGENT_PATCHES[0]) as C1, patch(_AGENT_PATCHES[1]) as C2, \
             patch(_AGENT_PATCHES[2]) as C3, patch(_AGENT_PATCHES[3]) as C4, \
             patch(_AGENT_PATCHES[4]) as C5, \
             patch("orchestrator.CoordinatorAgent") as CC:
            _mock_all_agents_good([C1, C2, C3, C4, C5])
            CC.return_value.run = AsyncMock(side_effect=fake_coordinator_run)
            orc = DischargeOrchestrator(api_key="test")
            await orc.run(SAMPLE_PATIENT)
        assert len(captured) == 5

    async def test_all_five_agents_start_in_parallel(self):
        start_times = []

        async def timed_agent(patient_data):
            start_times.append(asyncio.get_event_loop().time())
            await asyncio.sleep(0.02)
            return GOOD_OUTPUT

        with patch(_AGENT_PATCHES[0]) as C1, patch(_AGENT_PATCHES[1]) as C2, \
             patch(_AGENT_PATCHES[2]) as C3, patch(_AGENT_PATCHES[3]) as C4, \
             patch(_AGENT_PATCHES[4]) as C5, \
             patch("orchestrator.CoordinatorAgent") as CC:
            for Cls in [C1, C2, C3, C4, C5]:
                Cls.return_value.run = timed_agent
            CC.return_value.run = AsyncMock(return_value="done")
            orc = DischargeOrchestrator(api_key="test")
            await orc.run(SAMPLE_PATIENT)
        assert len(start_times) == 5
        # All 5 agents should start within 50ms — they run in parallel
        assert max(start_times) - min(start_times) < 0.05


class TestOrchestratorErrorIsolation:
    async def test_one_agent_failure_does_not_crash_job(self):
        with patch(_AGENT_PATCHES[0]) as C1, patch(_AGENT_PATCHES[1]) as C2, \
             patch(_AGENT_PATCHES[2]) as C3, patch(_AGENT_PATCHES[3]) as C4, \
             patch(_AGENT_PATCHES[4]) as C5, \
             patch("orchestrator.CoordinatorAgent") as CC:
            C1.return_value.run = AsyncMock(side_effect=RuntimeError("API timeout"))
            for Cls in [C2, C3, C4, C5]:
                Cls.return_value.run = AsyncMock(return_value=GOOD_OUTPUT)
            CC.return_value.run = AsyncMock(return_value="partial plan")
            orc = DischargeOrchestrator(api_key="test")
            result = await orc.run(SAMPLE_PATIENT)
        assert result == "partial plan"

    async def test_failed_agent_output_contains_error_marker(self):
        captured = {}

        async def fake_coordinator(agent_outputs):
            captured.update(agent_outputs)
            return "done"

        with patch(_AGENT_PATCHES[0]) as C1, patch(_AGENT_PATCHES[1]) as C2, \
             patch(_AGENT_PATCHES[2]) as C3, patch(_AGENT_PATCHES[3]) as C4, \
             patch(_AGENT_PATCHES[4]) as C5, \
             patch("orchestrator.CoordinatorAgent") as CC:
            C1.return_value.run = AsyncMock(side_effect=ValueError("Bad input data"))
            for Cls in [C2, C3, C4, C5]:
                Cls.return_value.run = AsyncMock(return_value=GOOD_OUTPUT)
            CC.return_value.run = AsyncMock(side_effect=fake_coordinator)
            orc = DischargeOrchestrator(api_key="test")
            await orc.run(SAMPLE_PATIENT)
        clinical_out = captured.get("clinical", "")
        assert "AGENT ERROR" in clinical_out, (
            f"Failed agent output should contain [AGENT ERROR:], got: {clinical_out!r}")

    async def test_all_agents_fail_coordinator_still_runs(self):
        with patch(_AGENT_PATCHES[0]) as C1, patch(_AGENT_PATCHES[1]) as C2, \
             patch(_AGENT_PATCHES[2]) as C3, patch(_AGENT_PATCHES[3]) as C4, \
             patch(_AGENT_PATCHES[4]) as C5, \
             patch("orchestrator.CoordinatorAgent") as CC:
            for Cls in [C1, C2, C3, C4, C5]:
                Cls.return_value.run = AsyncMock(side_effect=Exception("All systems down"))
            CC.return_value.run = AsyncMock(return_value="degraded plan")
            orc = DischargeOrchestrator(api_key="test")
            result = await orc.run(SAMPLE_PATIENT)
        assert isinstance(result, str)
        assert len(result) > 0

    async def test_three_agent_failures_four_succeed_coordinator_gets_all(self):
        captured = {}

        async def fake_coordinator(agent_outputs):
            captured.update(agent_outputs)
            return "mixed plan"

        with patch(_AGENT_PATCHES[0]) as C1, patch(_AGENT_PATCHES[1]) as C2, \
             patch(_AGENT_PATCHES[2]) as C3, patch(_AGENT_PATCHES[3]) as C4, \
             patch(_AGENT_PATCHES[4]) as C5, \
             patch("orchestrator.CoordinatorAgent") as CC:
            C1.return_value.run = AsyncMock(side_effect=Exception("fail"))
            C2.return_value.run = AsyncMock(side_effect=Exception("fail"))
            C3.return_value.run = AsyncMock(side_effect=Exception("fail"))
            C4.return_value.run = AsyncMock(return_value=GOOD_OUTPUT)
            C5.return_value.run = AsyncMock(return_value=GOOD_OUTPUT)
            CC.return_value.run = AsyncMock(side_effect=fake_coordinator)
            orc = DischargeOrchestrator(api_key="test")
            await orc.run(SAMPLE_PATIENT)
        assert len(captured) == 5
