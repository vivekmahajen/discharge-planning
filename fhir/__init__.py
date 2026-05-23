"""FHIR R4 connector for Discharge Planning AI — SMART on FHIR v2, read-only Phase 1."""

from .schemas import (
    PatientRecord,
    Condition,
    Medication,
    Allergy,
    AppointmentRecord,
    CareTeamMember,
    DocumentRecord,
    FetchWarning,
    PatientBundle,
)
from .client import FHIRClient, FHIRAuthError, FHIRForbiddenError, FHIRServerError, FHIRNetworkError
from .ehr_config import get_ehr_config, list_ehrs, EHRConfig
from .normalizers import fhir_bundle_to_agent_data

__all__ = [
    "PatientRecord",
    "Condition",
    "Medication",
    "Allergy",
    "AppointmentRecord",
    "CareTeamMember",
    "DocumentRecord",
    "FetchWarning",
    "PatientBundle",
    "FHIRClient",
    "FHIRAuthError",
    "FHIRForbiddenError",
    "FHIRServerError",
    "FHIRNetworkError",
    "get_ehr_config",
    "list_ehrs",
    "EHRConfig",
    "fhir_bundle_to_agent_data",
]
