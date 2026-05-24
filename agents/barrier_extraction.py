"""Barrier Extraction Agent — scans discharge plan for discharge barriers."""

from __future__ import annotations
import json
import re
import logging
from db.milestones_catalog import BARRIER_CATALOG

log = logging.getLogger(__name__)


class BarrierExtractionAgent:
    """
    Runs after the coordinator output is available.
    Calls Claude with the full plan text and a structured extraction prompt.
    Returns a list of dicts, each representing an identified barrier.
    Does NOT write to DB — caller handles persistence.
    """

    def __init__(self, client):
        self.client = client

    async def run(
        self,
        coordinator_output: str,
        agent_outputs: dict,
        patient_data: dict,
    ) -> list[dict]:
        import asyncio

        catalog_json = json.dumps({
            k: {"label": v["label"], "category": v["category"],
                "keywords": v["auto_detect_keywords"]}
            for k, v in BARRIER_CATALOG.items()
            if k != "custom"
        }, indent=2)

        primary_dx = patient_data.get("primary_diagnosis", "unknown")
        insurance = patient_data.get("primary_insurance", "unknown")
        patient_name = patient_data.get("patient_name", "Patient")

        system_prompt = (
            "You are a clinical discharge coordinator AI specialized in identifying "
            "discharge barriers in hospital discharge plans for California acute care hospitals.\n\n"
            "Your task: scan the discharge plan below and extract ALL discharge barriers "
            "that are explicitly mentioned OR strongly implied. A barrier is anything that "
            "could delay or prevent a timely, safe discharge.\n\n"
            "Return ONLY valid JSON — no prose, no markdown fences.\n"
            "Return a JSON array (can be empty []) of barrier objects.\n\n"
            "Each barrier object MUST have these exact fields:\n"
            "  barrier_type: string — use the closest key from the CATALOG below, "
            "                or 'custom' if no catalog match\n"
            "  label: string — use catalog label if matched, otherwise 1-5 word label\n"
            "  category: string — clinical | authorization | placement | social | documentation | other\n"
            "  description: string — 1-2 sentences of specific context FROM THE PLAN\n"
            "  priority: string — 'critical' (blocking discharge today), 'high' (blocks discharge "
            "            within 24h), 'medium' (within 48h), 'low' (advisory)\n"
            "  ai_confidence: float — 0.0 to 1.0 (how certain you are this is a real barrier)\n"
            "  ai_evidence: string — verbatim phrase from the plan text that triggered this, "
            "               max 100 chars\n\n"
            "RULES:\n"
            "- Only include barriers with ai_confidence >= 0.6\n"
            "- Do NOT invent barriers not mentioned or implied in the text\n"
            "- Do NOT include barriers that are already resolved in the text\n"
            "- Mark California-specific barriers (Medi-Cal, Livanta, CalAIM, SNF auth) as priority 'high' minimum\n"
            "- If the plan says a barrier is 'pending', 'not yet', 'needs to be', 'not scheduled', "
            "  'not arranged', 'not confirmed' — that is a barrier\n"
            "- Deduplicate: do not return the same barrier type twice\n\n"
            f"BARRIER CATALOG:\n{catalog_json}"
        )

        full_text = f"""PATIENT: {patient_name}
PRIMARY DIAGNOSIS: {primary_dx}
PRIMARY INSURANCE: {insurance}

=== COORDINATOR FINAL PLAN ===
{coordinator_output}

=== INSURANCE AUTHORIZATION AGENT ===
{agent_outputs.get("insurance", "")}

=== CARE NEEDS AGENT ===
{agent_outputs.get("care_needs", "")}

=== SOCIAL DETERMINANTS AGENT ===
{agent_outputs.get("social", "")}

=== CLINICAL ASSESSMENT AGENT ===
{agent_outputs.get("clinical", "")}
"""

        def _call():
            resp = self.client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2000,
                temperature=0,
                system=system_prompt,
                messages=[{"role": "user", "content": full_text}],
            )
            return resp.content[0].text

        try:
            raw = await asyncio.to_thread(_call)
            clean = raw.strip()
            if clean.startswith("```"):
                clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
                clean = re.sub(r"\n?```$", "", clean).strip()
            barriers = json.loads(clean)
            if not isinstance(barriers, list):
                return []
            valid = []
            seen_types = set()
            for b in barriers:
                bt = b.get("barrier_type", "custom")
                if bt in seen_types:
                    continue
                seen_types.add(bt)
                conf = float(b.get("ai_confidence", 0))
                if conf < 0.6:
                    continue
                if bt not in BARRIER_CATALOG:
                    bt = "custom"
                catalog_entry = BARRIER_CATALOG[bt]
                valid.append({
                    "barrier_type": bt,
                    "label": b.get("label") or catalog_entry["label"],
                    "category": b.get("category") or catalog_entry["category"],
                    "description": str(b.get("description", ""))[:500],
                    "priority": b.get("priority", "medium") if b.get("priority") in ("critical","high","medium","low") else "medium",
                    "ai_confidence": round(conf, 2),
                    "ai_evidence": str(b.get("ai_evidence", ""))[:100],
                })
            return valid
        except Exception as e:
            log.warning("BarrierExtractionAgent failed: %s", e)
            return []
