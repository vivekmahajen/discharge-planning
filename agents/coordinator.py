"""Coordinator Agent for discharge planning — synthesizes all specialist outputs."""
import asyncio
import sys
from functools import partial

import anthropic

from agents.base_agent import BaseAgent


class CoordinatorAgent(BaseAgent):
    """Synthesizes outputs from all five specialist agents into a unified discharge plan.

    Runs after the five parallel specialist agents complete and produces a
    complete, actionable discharge planning document including readmission
    risk assessment and an open-items checklist.
    """

    MAX_TOKENS = 8000

    SYSTEM_PROMPT = """You are the Discharge Planning Coordinator AI. You receive outputs from five specialist agents and are responsible for synthesizing them into a complete, actionable discharge plan.

Your responsibilities:
1. Synthesize all agent findings and resolve any conflicts
2. Manage the discharge timeline with a day-by-day task checklist
3. Summarize external coordination status (SNF/IRF placement, home health, DME, pharmacy, follow-up appointments, transportation)
4. Assess patient and family readiness
5. Ensure compliance documentation
6. Assess 30-day readmission risk (Low/Medium/High) with top 3 contributing factors and mitigation plan

Produce a complete unified discharge plan document with these sections:
- PATIENT INFORMATION
- DISCHARGE DESTINATION (with rationale)
- CLINICAL SUMMARY
- POST-DISCHARGE SERVICES
- MEDICATIONS
- FOLLOW-UP APPOINTMENTS
- PATIENT EDUCATION COMPLETED
- EQUIPMENT & SUPPLIES
- EMERGENCY INSTRUCTIONS
- OPEN ITEMS — MUST RESOLVE BEFORE DISCHARGE
- COORDINATOR FLAGS FOR CLINICIAN REVIEW
- READMISSION RISK ASSESSMENT

Always end with:
⚠️ DRAFT ONLY — This discharge plan has been prepared by an AI system to support clinical decision-making. It requires review, modification as needed, and approval by a licensed clinician before implementation. No actions should be taken based solely on this draft."""

    def format_input(self, patient_data: dict) -> str:
        """Not used directly for CoordinatorAgent — see run() override.

        Args:
            patient_data: Unused; coordinator receives agent_outputs instead.

        Returns:
            Empty string placeholder.
        """
        return ""

    def _sync_create_coordinator(self, user_message: str) -> str:
        """Execute a synchronous Anthropic API call with coordinator token budget.

        Args:
            user_message: The formatted message combining all agent outputs.

        Returns:
            The synthesized discharge plan text.

        Raises:
            anthropic.APIError: If the API call fails.
        """
        response = self.client.messages.create(
            model=self.MODEL,
            max_tokens=self.MAX_TOKENS,
            temperature=self.TEMPERATURE,
            system=self.SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": user_message},
            ],
        )
        return response.content[0].text

    async def run(self, agent_outputs: dict) -> str:  # type: ignore[override]
        """Synthesize all specialist agent outputs into a unified discharge plan.

        Args:
            agent_outputs: Dict mapping agent names to their text outputs.
                Expected keys: clinical, care_needs, insurance, medications, social.

        Returns:
            Complete unified discharge plan as a formatted string.

        Raises:
            anthropic.APIError: If the API call fails.
        """
        print(
            "[INFO] CoordinatorAgent: synthesizing specialist outputs...",
            file=sys.stderr,
        )

        sections = [
            "You have received the following outputs from five specialist discharge planning agents.",
            "Please synthesize them into a complete, unified discharge plan.",
            "",
        ]

        agent_labels = {
            "clinical": "CLINICAL ASSESSMENT AGENT OUTPUT",
            "care_needs": "CARE NEEDS AGENT OUTPUT",
            "insurance": "INSURANCE AUTHORIZATION AGENT OUTPUT",
            "medications": "MEDICATION RECONCILIATION AGENT OUTPUT",
            "social": "SOCIAL DETERMINANTS AGENT OUTPUT",
        }

        for key, label in agent_labels.items():
            output = agent_outputs.get(key, "[No output received]")
            sections.append(f"{'=' * 60}")
            sections.append(label)
            sections.append(f"{'=' * 60}")
            sections.append(str(output))
            sections.append("")

        user_message = "\n".join(sections)

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None, partial(self._sync_create_coordinator, user_message)
            )
        except anthropic.APIError as exc:
            print(
                f"[ERROR] CoordinatorAgent API call failed: {exc}",
                file=sys.stderr,
            )
            raise

        print(
            "[INFO] CoordinatorAgent: discharge plan synthesis complete.",
            file=sys.stderr,
        )
        return result
