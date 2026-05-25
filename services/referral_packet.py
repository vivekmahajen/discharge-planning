"""
Referral packet builder.
- Generates a FHIR R4 ServiceRequest JSON structure.
- Generates a human-readable HTML referral packet (suitable for fax/print).
- AI-assisted clinical summary generation using Claude.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from typing import Optional

_log = logging.getLogger(__name__)

# FHIR urgency mapping: internal value -> FHIR priority code
_URGENCY_MAP = {
    "routine": "routine",
    "urgent": "urgent",
    "stat": "asap",
}

# SNOMED code for post-acute / SNF referral category
_REFERRAL_CATEGORY = [
    {
        "coding": [
            {
                "system": "http://snomed.info/sct",
                "code": "306206005",
                "display": "Referral to service",
            }
        ]
    }
]


def build_fhir_service_request(
    patient_data: dict,
    facility: dict,
    referral_id: int,
    service_type: str,
    urgency: str,
    referral_notes: str,
    ordering_clinician: str,
) -> dict:
    """Build a FHIR R4 ServiceRequest resource for post-acute referral.

    Status is set to 'draft'; callers should update to 'active' upon send.
    """
    fhir_priority = _URGENCY_MAP.get(urgency, "routine")
    today_str = date.today().isoformat()

    # Build note text from service_type + referral_notes
    note_text_parts = []
    if service_type:
        note_text_parts.append(f"Service requested: {service_type}")
    if referral_notes:
        note_text_parts.append(referral_notes)
    note_text = "\n".join(note_text_parts) if note_text_parts else ""

    # Performer (facility) reference
    performer: list[dict] = []
    facility_name = facility.get("facility_name") or facility.get("name")
    facility_ccn = facility.get("facility_ccn") or facility.get("ccn")
    if facility_name or facility_ccn:
        display = facility_name or facility_ccn
        performer_entry: dict = {"display": display}
        if facility_ccn:
            performer_entry["identifier"] = {
                "system": "urn:oid:2.16.840.1.113883.4.336",  # CMS Certification Number OID
                "value": facility_ccn,
            }
        performer.append(performer_entry)

    # Patient subject reference (use MRN if available, no PHI in logging)
    mrn = patient_data.get("mrn", "")
    patient_name = patient_data.get("patient_name", "")
    subject: dict = {}
    if mrn:
        subject = {
            "identifier": {
                "system": "urn:discharge-planning:mrn",
                "value": mrn,
            }
        }
        if patient_name:
            subject["display"] = patient_name

    # Requester (ordering clinician)
    requester: dict = {}
    if ordering_clinician:
        requester = {"display": ordering_clinician}

    resource: dict = {
        "resourceType": "ServiceRequest",
        "id": str(referral_id),
        "status": "draft",
        "intent": "order",
        "priority": fhir_priority,
        "category": _REFERRAL_CATEGORY,
        "identifier": [
            {
                "system": "urn:discharge-planning:referrals",
                "value": str(referral_id),
            }
        ],
        "occurrenceDateTime": today_str,
        "authoredOn": datetime.now(timezone.utc).isoformat(),
    }

    if subject:
        resource["subject"] = subject
    if performer:
        resource["performer"] = performer
    if requester:
        resource["requester"] = requester
    if service_type:
        resource["code"] = {"text": service_type}
    if note_text:
        resource["note"] = [{"text": note_text}]

    return resource


async def generate_ai_clinical_summary(
    patient_data: dict,
    barriers: list[dict],
    anthropic_client,
) -> str:
    """Use Claude Haiku to generate a brief clinical summary for the referral packet.

    Returns plain text (2-3 sentences). Falls back to '' on error.
    Never logs patient data.
    """
    try:
        # Build a prompt with clinical context — no PHI is logged here
        diagnosis = patient_data.get("primary_diagnosis", "")
        drg_desc = patient_data.get("drg_description", "")
        admission_date = patient_data.get("admission_date", "")
        discharge_dest = patient_data.get("discharge_destination", "")

        # Summarise open/resolved barriers for clinical context
        barrier_lines: list[str] = []
        for b in barriers[:10]:  # cap to avoid token bloat
            label = b.get("milestone_label") or b.get("barrier_type") or b.get("description") or ""
            bstatus = b.get("status", "")
            if label:
                barrier_lines.append(f"- {label} ({bstatus})")
        barriers_text = "\n".join(barrier_lines) if barrier_lines else "None documented."

        prompt = (
            "You are a discharge planning assistant. "
            "Write a concise 2-3 sentence clinical summary suitable for a post-acute care referral packet. "
            "Focus on the patient's current clinical status, care needs, and reason for referral. "
            "Do not invent information; only use what is provided.\n\n"
            f"Primary diagnosis: {diagnosis}\n"
            f"DRG: {drg_desc}\n"
            f"Admission date: {admission_date}\n"
            f"Planned discharge destination: {discharge_dest}\n"
            f"Discharge barriers / care needs:\n{barriers_text}\n\n"
            "Clinical summary (2-3 sentences, plain text only):"
        )

        response = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text.strip() if response.content else ""
        return summary
    except Exception:
        # Never log patient data on error
        _log.warning("AI clinical summary generation failed (referral packet); returning empty string")
        return ""


def build_referral_html(
    patient_data: dict,
    facility: dict,
    referral: dict,
    org_settings: dict,
    ai_summary: str,
    fhir_sr: dict,
) -> str:
    """Build a printable/faxable HTML referral packet.

    Contains: org letterhead, patient info, facility, clinical summary,
    services requested, FHIR reference ID, clinician signature block.

    Note: This HTML contains PHI. Do NOT log its contents.
    """
    # Org / sender info
    org_name = org_settings.get("org_name") or "Discharging Hospital"
    org_fax = org_settings.get("org_fax") or ""
    org_npi = org_settings.get("org_npi") or ""
    org_address = org_settings.get("org_address") or ""
    fax_header = org_settings.get("fax_cover_header") or ""

    # Patient info
    patient_name = patient_data.get("patient_name") or "Patient"
    mrn = patient_data.get("mrn") or ""
    dob = patient_data.get("date_of_birth") or ""
    admission_date = patient_data.get("admission_date") or ""
    primary_diagnosis = patient_data.get("primary_diagnosis") or ""
    drg_code = patient_data.get("drg_code") or ""
    drg_desc = patient_data.get("drg_description") or ""

    # Facility info
    facility_name = facility.get("facility_name") or referral.get("facility_name") or "Receiving Facility"
    facility_fax = facility.get("facility_fax") or referral.get("facility_fax") or ""
    facility_ccn = facility.get("facility_ccn") or referral.get("facility_ccn") or ""

    # Referral details
    referral_id = referral.get("id") or ""
    service_type = referral.get("service_type") or ""
    urgency = referral.get("urgency") or "routine"
    referral_notes = referral.get("referral_notes") or ""
    created_by = referral.get("created_by") or ""
    confirmed_by = referral.get("confirmed_by") or created_by
    confirmed_at_raw = referral.get("confirmed_at") or ""
    confirmed_at = str(confirmed_at_raw)[:19].replace("T", " ") if confirmed_at_raw else ""

    # FHIR reference id
    fhir_ref = fhir_sr.get("id") or str(referral_id)

    # Render date
    rendered_date = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Urgency badge color
    urgency_color = {
        "stat": "#cc0000",
        "urgent": "#e67300",
        "routine": "#2a6ebb",
    }.get(urgency, "#2a6ebb")

    def _row(label: str, value: str) -> str:
        if not value:
            return ""
        return (
            f'<tr><td style="font-weight:bold;padding:4px 8px;width:180px;'
            f'vertical-align:top;color:#555;">{_esc(label)}</td>'
            f'<td style="padding:4px 8px;">{_esc(value)}</td></tr>'
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Post-Acute Care Referral — {_esc(facility_name)}</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; font-size: 12px; color: #222; margin: 0; padding: 0; }}
    .page {{ max-width: 800px; margin: 0 auto; padding: 24px; }}
    .letterhead {{ border-bottom: 3px solid #2a6ebb; padding-bottom: 12px; margin-bottom: 20px; }}
    .letterhead h1 {{ margin: 0 0 4px 0; font-size: 20px; color: #2a6ebb; }}
    .letterhead p {{ margin: 2px 0; font-size: 11px; color: #555; }}
    .section {{ margin-bottom: 18px; }}
    .section h2 {{ font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;
                   color: #fff; background: #2a6ebb; padding: 5px 10px; margin: 0 0 8px 0; }}
    table {{ border-collapse: collapse; width: 100%; }}
    td {{ border: none; }}
    .urgency-badge {{ display: inline-block; padding: 3px 10px; border-radius: 4px;
                      color: #fff; font-weight: bold; font-size: 11px;
                      background: {urgency_color}; text-transform: uppercase; }}
    .summary-box {{ background: #f5f8fd; border-left: 4px solid #2a6ebb;
                    padding: 10px 14px; font-style: italic; color: #333; }}
    .footer {{ border-top: 1px solid #ccc; padding-top: 10px; margin-top: 24px;
               font-size: 10px; color: #888; }}
    .sig-block {{ margin-top: 16px; }}
    .fhir-ref {{ font-family: monospace; font-size: 10px; color: #888; }}
  </style>
</head>
<body>
<div class="page">

  <!-- Letterhead -->
  <div class="letterhead">
    <h1>{_esc(org_name)}</h1>
    {"<p>" + _esc(fax_header) + "</p>" if fax_header else ""}
    {"<p>Address: " + _esc(org_address) + "</p>" if org_address else ""}
    {"<p>Fax: " + _esc(org_fax) + " &nbsp;|&nbsp; NPI: " + _esc(org_npi) + "</p>" if org_fax or org_npi else ""}
    <p style="margin-top:8px;font-size:12px;color:#222;">
      <strong>POST-ACUTE CARE REFERRAL</strong> &nbsp;
      <span class="urgency-badge">{_esc(urgency)}</span>
    </p>
    <p>Date: {_esc(rendered_date)} &nbsp;|&nbsp; Referral ID: {_esc(str(referral_id))}</p>
  </div>

  <!-- Receiving Facility -->
  <div class="section">
    <h2>Receiving Facility</h2>
    <table>
      {_row("Facility Name", facility_name)}
      {_row("CCN", facility_ccn)}
      {_row("Fax", facility_fax)}
    </table>
  </div>

  <!-- Patient Information -->
  <div class="section">
    <h2>Patient Information</h2>
    <table>
      {_row("Patient Name", patient_name)}
      {_row("MRN", mrn)}
      {_row("Date of Birth", str(dob))}
      {_row("Admission Date", str(admission_date))}
      {_row("Primary Diagnosis", primary_diagnosis)}
      {_row("DRG", (drg_code + " — " + drg_desc).strip(" — ") if drg_code or drg_desc else "")}
    </table>
  </div>

  <!-- Referral Details -->
  <div class="section">
    <h2>Referral Details</h2>
    <table>
      {_row("Service Requested", service_type)}
      {_row("Urgency", urgency.capitalize())}
      {_row("Referring Clinician", created_by)}
      {_row("Clinician Confirmed By", confirmed_by)}
      {_row("Confirmed At", confirmed_at)}
    </table>
    {"<p style='margin-top:8px;'><strong>Notes:</strong> " + _esc(referral_notes) + "</p>" if referral_notes else ""}
  </div>

  <!-- Clinical Summary -->
  {"<div class='section'><h2>Clinical Summary</h2><div class='summary-box'>" + _esc(ai_summary) + "</div></div>" if ai_summary else ""}

  <!-- Clinician Signature Block -->
  <div class="section sig-block">
    <h2>Ordering Clinician</h2>
    <p>Name: {_esc(confirmed_by or created_by)}</p>
    <p>Date/Time: {_esc(confirmed_at or rendered_date)}</p>
    <br/>
    <p>Signature: ___________________________________</p>
  </div>

  <!-- Footer / FHIR reference -->
  <div class="footer">
    <p>This document was generated by an automated discharge planning system and must be reviewed
       and confirmed by a licensed clinician before transmission.</p>
    <p class="fhir-ref">FHIR ServiceRequest ID: {_esc(fhir_ref)} | Generated: {_esc(rendered_date)}</p>
    <p><strong>CONFIDENTIALITY NOTICE:</strong> This facsimile contains privileged and confidential
       health information. If you have received this in error, please notify the sender immediately
       and destroy all copies.</p>
  </div>

</div>
</body>
</html>"""

    return html


def _esc(text: str) -> str:
    """Minimal HTML escaping for untrusted strings inserted into HTML."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )
