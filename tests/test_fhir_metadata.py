"""170.315(g)(10) — FHIR CapabilityStatement tests.

ATL test (g)(10)-FHIR-05: GET /fhir/metadata returns valid R4 CapabilityStatement.
"""
import pytest

REQUIRED_RESOURCES = [
    "Patient", "AllergyIntolerance", "CarePlan", "CareTeam", "Condition",
    "DiagnosticReport", "DocumentReference", "Encounter", "Goal", "Immunization",
    "MedicationRequest", "Observation", "Procedure", "Provenance", "Device",
]


async def test_capability_statement_returns_200(client):
    resp = await client.get("/fhir/metadata")
    assert resp.status_code == 200


async def test_capability_statement_resource_type(client):
    data = (await client.get("/fhir/metadata")).json()
    assert data["resourceType"] == "CapabilityStatement"


async def test_capability_statement_fhir_version(client):
    data = (await client.get("/fhir/metadata")).json()
    assert data["fhirVersion"] == "4.0.1"


async def test_capability_statement_us_core_ig(client):
    data = (await client.get("/fhir/metadata")).json()
    assert any("us/core" in ig for ig in data.get("implementationGuide", []))


async def test_capability_statement_smart_security(client):
    data = (await client.get("/fhir/metadata")).json()
    security = data["rest"][0]["security"]
    service_codes = [
        c["code"]
        for svc in security.get("service", [])
        for c in svc.get("coding", [])
    ]
    assert "SMART-on-FHIR" in service_codes


async def test_capability_statement_has_required_resources(client):
    data = (await client.get("/fhir/metadata")).json()
    declared = {r["type"] for r in data["rest"][0]["resource"]}
    missing = set(REQUIRED_RESOURCES) - declared
    assert not missing, f"Missing US Core resources: {missing}"


async def test_capability_statement_patient_search_params(client):
    data = (await client.get("/fhir/metadata")).json()
    patient = next(r for r in data["rest"][0]["resource"] if r["type"] == "Patient")
    param_names = {p["name"] for p in patient.get("searchParam", [])}
    assert "_id" in param_names
    assert "identifier" in param_names


async def test_capability_statement_json_format(client):
    data = (await client.get("/fhir/metadata")).json()
    assert "application/fhir+json" in data["format"]
