"""CLI entry point for the Multi-Agent Discharge Planning System."""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from orchestrator import DischargeOrchestrator
from sample_patient import SAMPLE_PATIENT
from utils.formatting import print_section_header


def load_patient_data(path: str) -> dict:
    """Load patient data from a JSON file.

    Args:
        path: Filesystem path to a JSON file containing patient data.

    Returns:
        Parsed patient data dictionary.

    Raises:
        SystemExit: If the file cannot be read or parsed.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        print(f"[INFO] Loaded patient data from: {path}", file=sys.stderr)
        return data
    except FileNotFoundError:
        print(f"[ERROR] Patient data file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as exc:
        print(
            f"[ERROR] Failed to parse JSON from {path}: {exc}", file=sys.stderr
        )
        sys.exit(1)


def save_output(plan: str, patient_data: dict) -> None:
    """Save the discharge plan to a timestamped output file.

    Args:
        plan: The complete discharge plan text.
        patient_data: Patient data dict (used for filename).
    """
    mrn = patient_data.get("mrn", "UNKNOWN").replace("/", "-").replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"discharge_plan_{mrn}_{timestamp}.txt"
    try:
        with open(filename, "w", encoding="utf-8") as fh:
            fh.write(plan)
        print(f"[INFO] Discharge plan saved to: {filename}", file=sys.stderr)
    except OSError as exc:
        print(f"[WARN] Could not save output file: {exc}", file=sys.stderr)


async def main() -> None:
    """Main async entry point.

    Loads configuration, selects patient data source, runs the orchestrator,
    and outputs the discharge plan to stdout.
    """
    # Load environment variables from .env if present
    load_dotenv()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "[ERROR] ANTHROPIC_API_KEY environment variable is not set.\n"
            "        Create a .env file based on .env.example and set your key.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Determine patient data source
    if len(sys.argv) > 1:
        patient_data = load_patient_data(sys.argv[1])
    else:
        print(
            "[INFO] No patient data file provided — using built-in sample patient.",
            file=sys.stderr,
        )
        patient_data = SAMPLE_PATIENT

    # Run the multi-agent orchestration
    orchestrator = DischargeOrchestrator(api_key=api_key)

    try:
        discharge_plan = await orchestrator.run(patient_data)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"[ERROR] Orchestration failed: {exc}", file=sys.stderr)
        sys.exit(1)

    # Output the plan to stdout (clean — no progress noise)
    print_section_header("DISCHARGE PLAN OUTPUT", file=sys.stdout)
    print(discharge_plan)

    # Optionally persist to file
    save_output(discharge_plan, patient_data)


if __name__ == "__main__":
    asyncio.run(main())
