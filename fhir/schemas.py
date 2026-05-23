"""Internal schema definitions for normalized FHIR R4 resources.

All fields are snake_case equivalents of the FHIR R4 TS interfaces in the spec.
Optional fields return None rather than raising — normalizers must never throw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PatientRecord:
    id: str
    mrn: str
    first_name: str
    last_name: str
    date_of_birth: str          # YYYY-MM-DD
    gender: str
    preferred_language: str     # BCP-47 language code or text
    phone: str
    address: str


@dataclass
class Condition:
    id: str
    icd10_code: str
    display_name: str
    onset: Optional[str]
    severity: Optional[str]
    category: str               # 'encounter-diagnosis' | 'problem-list-item'


@dataclass
class Medication:
    id: str
    name: str
    rxnorm_code: Optional[str]
    dosage_text: Optional[str]
    frequency: Optional[str]
    route: Optional[str]
    prescriber: Optional[str]
    authored_on: Optional[str]
    is_new: bool                # True if authored within the current encounter


@dataclass
class Allergy:
    id: str
    substance: str
    type: str                   # 'allergy' | 'intolerance'
    criticality: str            # 'low' | 'high' | 'unable-to-assess'
    reaction: Optional[str]


@dataclass
class AppointmentRecord:
    id: str
    service_type: Optional[str]
    start: Optional[str]        # ISO-8601
    end: Optional[str]
    status: str
    practitioners: list[str]
    location: Optional[str]


@dataclass
class CareTeamMember:
    id: str
    name: str
    role: Optional[str]
    specialty: Optional[str]


@dataclass
class DocumentRecord:
    id: str
    title: Optional[str]
    date: Optional[str]
    author: Optional[str]
    content_url: Optional[str]


@dataclass
class FetchWarning:
    resource: str
    error: str


@dataclass
class PatientBundle:
    """Complete normalized patient data bundle — never persisted to database."""

    patient: Optional[PatientRecord]
    conditions: list[Condition]
    medications: list[Medication]
    allergies: list[Allergy]
    appointments: list[AppointmentRecord]
    care_team: list[CareTeamMember]
    documents: list[DocumentRecord]
    fetch_warnings: list[FetchWarning]
    fhir_base: str
    ehr: str
