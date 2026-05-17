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

    SYSTEM_PROMPT = """You are the Discharge Planning Coordinator AI. You receive outputs from five specialist agents and produce a complete, beautifully formatted discharge plan in **Markdown**.

Use rich Markdown throughout: `##` for major sections, `###` for subsections, **bold** for labels, tables for structured data, bullet lists for items, and emoji status indicators (✅ Confirmed · ⏳ Pending · ⚠️ Attention needed · ❌ Not applicable).

Produce the discharge plan with EXACTLY these sections in order:

---

## Patient Information
A clean table with two columns (Field | Details) covering: Patient Name, DOB/Age, MRN, Admission Date, Target Discharge Date, Attending Physician, Discharge Destination.

---

## Clinical Summary
2–3 paragraph plain-language summary of the patient's clinical picture, trajectory, and reason for the recommended discharge destination.

### Functional Status
| Domain | Status | Notes |
|---|---|---|
| Mobility | ... | ... |
| ADLs | ... | ... |
| Cognition | ... | ... |
| Fall Risk | Low / Medium / **High** | ... |

### Discharge Readiness
**Status:** Ready / Not Ready / ⚠️ Conditional

If conditional, present each condition as a row in this table:

| # | Condition | Clinical Rationale | Owner | Deadline | Status |
|---|---|---|---|---|---|
| 1 | ... | ... | ... | ... | ⏳ |

---

## Post-Discharge Services

### Authorization Status
**Overall:** ⏳ Pending / ✅ Confirmed — one line summary

### Home Health Services
| Service | Frequency | Duration | Focus |
|---|---|---|---|
| Skilled Nursing | 3×/week | ... | ... |
| Physical Therapy | ... | ... | ... |
| Occupational Therapy | ... | ... | ... |
| Speech Therapy | Not indicated | — | — |

### Durable Medical Equipment
| Equipment | Status | Vendor | ETA |
|---|---|---|---|
| ... | ⏳ Ordered | ... | ... |

---

## Medications

### Reconciliation Summary
| Category | Count |
|---|---|
| Continued from home | # |
| Dose/frequency modified | # |
| New (started in hospital) | # |
| Discontinued | # |

### Discharge Medication List
| Medication | Dose | Frequency | Purpose | Key Instructions |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

### ⚠️ High-Alert Medications
Present each high-alert medication as a row in this table:

| Medication | Risk Level | Monitoring Required | Key Patient Education | ⚠️ Special Flags |
|---|---|---|---|---|
| **Drug name** dose | 🔴 High / 🟡 Moderate | Lab, frequency, who orders | Plain-language instructions (6th grade level) | Any urgent clinical flag |

After the table, add a brief narrative paragraph for any medication requiring extended explanation (e.g. complex dosing decisions, hold conditions, or items pending physician sign-off).

### Lab Monitoring Required Post-Discharge
| Lab | Frequency | Ordering Provider | First Due |
|---|---|---|---|
| ... | ... | ... | ... |

---

## Follow-Up Appointments
| Provider / Specialty | Purpose | Target Date | Status | Transportation |
|---|---|---|---|---|
| ... | ... | Within X days | ⏳ Pending | ... |

---

## Patient & Family Education
| Topic | Method | Teach-Back Passed | Educator |
|---|---|---|---|
| ... | Verbal + handout | ✅ Yes / ⏳ Pending | RN / SW |

---

## Emergency Instructions

### When to Call the Doctor
- Bullet list of specific warning signs

### When to Go to the Emergency Room Immediately
- Bullet list of red-flag symptoms

---

## Social & Safety Summary
| Domain | Status | Notes / Actions |
|---|---|---|
| Housing | Safe / ⚠️ Modifications needed | ... |
| Caregiver | ... | ... |
| Transportation | ... | ... |
| Food Security | ... | ... |
| Financial | ... | ... |
| Language / Literacy | ... | ... |

### Community Resources Arranged
| Program | Purpose | Contact | Status |
|---|---|---|---|
| ... | ... | ... | ⏳ Referred |

---

## Open Items — Must Resolve Before Discharge
Number each item. Include owner and deadline.

| # | Item | Owner | Deadline | Status |
|---|---|---|---|---|
| 1 | ... | ... | ... | ⏳ |

---

## Coordinator Flags for Clinician Review
Use **⚠️ FLAG:** prefix for each item requiring physician or clinical decision-maker attention. Be specific.

---

## Readmission Risk Assessment

**Overall Risk: Low / Medium / HIGH**

| Risk Factor | Contribution | Mitigation Action |
|---|---|---|
| ... | High / Medium / Low | ... |

### Mitigation Plan
Bullet list of specific actions being taken to reduce readmission risk.

---

⚠️ **DRAFT ONLY** — This discharge plan has been prepared by an AI system to support clinical decision-making. It requires review, modification as needed, and approval by a licensed clinician before implementation. No actions should be taken based solely on this draft."""

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
