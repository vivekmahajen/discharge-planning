"""Formatting utilities for discharge planning system output."""
import sys
from typing import Optional


def print_section_header(title: str, width: int = 70, file=None) -> None:
    """Print a nicely formatted section header.

    Args:
        title: The section title to display.
        width: Total width of the header line.
        file: Output file (defaults to sys.stderr for progress messages).
    """
    if file is None:
        file = sys.stderr

    border = "=" * width
    padding = max(0, (width - len(title) - 2) // 2)
    padded_title = " " * padding + title + " " * padding
    # Adjust for odd-length titles
    if len(padded_title) < width - 2:
        padded_title += " "

    print(border, file=file)
    print(f"  {title}", file=file)
    print(border, file=file)


def format_agent_output(agent_name: str, output: str, width: int = 70) -> str:
    """Format a single agent's output with a labeled section header.

    Args:
        agent_name: Human-readable name of the agent.
        output: The agent's text output.
        width: Width for the separator lines.

    Returns:
        Formatted string with header and content.
    """
    border = "-" * width
    header = f"[ {agent_name.upper()} ]"
    padding = max(0, (width - len(header)) // 2)
    centered_header = " " * padding + header

    lines = [
        border,
        centered_header,
        border,
        output,
        "",
    ]
    return "\n".join(lines)


def format_patient_summary(patient_data: dict) -> str:
    """Format key patient identifiers for progress display.

    Args:
        patient_data: Patient data dictionary.

    Returns:
        Brief one-line patient summary string.
    """
    name = patient_data.get("patient_name", "Unknown Patient")
    mrn = patient_data.get("mrn", "N/A")
    dx = patient_data.get("primary_diagnosis", "")
    return f"{name} | MRN: {mrn} | Dx: {dx}"
