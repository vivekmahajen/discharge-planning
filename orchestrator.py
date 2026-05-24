"""Orchestrator — runs all specialist agents in parallel then coordinates output."""
import asyncio
import sys

import anthropic

from agents.clinical_assessment import ClinicalAssessmentAgent
from agents.care_needs import CareNeedsAgent
from agents.insurance_authorization import InsuranceAuthorizationAgent
from agents.medication_reconciliation import MedicationReconciliationAgent
from agents.social_determinants import SocialDeterminantsAgent
from agents.coordinator import CoordinatorAgent
from agents.predictive_los import PredictiveLOSAgent
from utils.formatting import print_section_header, format_patient_summary


class DischargeOrchestrator:
    """Orchestrates the full multi-agent discharge planning workflow.

    Runs five specialist agents in parallel via asyncio.gather(), then passes
    all outputs to the Coordinator Agent to produce a unified discharge plan.
    """

    def __init__(self, api_key: str) -> None:
        """Initialize the orchestrator with a shared Anthropic client.

        Args:
            api_key: Anthropic API key used to authenticate all agent calls.
        """
        self.client = anthropic.Anthropic(api_key=api_key)
        self.agents: dict = {
            "predictive_los": PredictiveLOSAgent(None),
            "clinical": ClinicalAssessmentAgent(self.client),
            "care_needs": CareNeedsAgent(self.client),
            "insurance": InsuranceAuthorizationAgent(self.client),
            "medications": MedicationReconciliationAgent(self.client),
            "social": SocialDeterminantsAgent(self.client),
        }
        self.coordinator = CoordinatorAgent(self.client)

    async def run(self, patient_data: dict) -> str:
        """Run the full discharge planning workflow for a patient.

        Executes all five specialist agents concurrently, handles any individual
        agent failures gracefully, then passes all outputs to the coordinator.

        Args:
            patient_data: Dictionary containing all patient information fields.

        Returns:
            The complete unified discharge plan as a formatted string.
        """
        summary = format_patient_summary(patient_data)
        print_section_header(f"DISCHARGE PLANNING — {summary}")
        print(
            f"[INFO] Launching {len(self.agents)} specialist agents in parallel...",
            file=sys.stderr,
        )

        # Run all 5 specialist agents in parallel
        tasks = {
            name: agent.run(patient_data)
            for name, agent in self.agents.items()
        }
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        agent_outputs: dict = dict(zip(tasks.keys(), results))

        # Handle any agent errors gracefully
        error_count = 0
        for name, result in agent_outputs.items():
            if isinstance(result, Exception):
                error_count += 1
                agent_outputs[name] = (
                    f"[AGENT ERROR: {name} failed — {str(result)}]"
                )
                print(
                    f"[WARN] Agent '{name}' failed: {result}",
                    file=sys.stderr,
                )

        if error_count:
            print(
                f"[WARN] {error_count}/{len(self.agents)} agents encountered errors. "
                "Coordinator will proceed with available outputs.",
                file=sys.stderr,
            )
        else:
            print(
                f"[INFO] All {len(self.agents)} specialist agents completed successfully.",
                file=sys.stderr,
            )

        # Run coordinator with all outputs
        print_section_header("COORDINATOR — synthesizing discharge plan")
        discharge_plan = await self.coordinator.run(agent_outputs)
        return discharge_plan
