# EHR Write‑Back — file the discharge plan as a chart note

Writes the AI discharge plan back into the EHR as a **FHIR R4 `DocumentReference`**
(a clinical note attached to the patient's chart). It's an explicit **clinician action**
that files a clearly‑labeled **DRAFT** (`docStatus = preliminary`) for review — never automatic.

> We use **DocumentReference** because that's the write Epic actually exposes
> (`DocumentReference.Create (Clinical Notes) (R4)`), and it's available under a
> **Patients‑audience** app — so the same patient session can read *and* write.
> (Epic does **not** expose a `Communication.Write`/`.Create` API in the sandbox, which is
> why the earlier Communication approach wasn't usable. A `create_communication()` helper
> remains in the client for environments that do offer it, but the UI uses DocumentReference.)

## How it works

1. Connect an EHR session that has write access — **Import from EHR → "Epic (write‑back)"**
   (`/api/fhir/authorize?ehr=epic_provider`), which requests the patient read scopes **plus**
   `patient/DocumentReference.write`.
2. On the generated plan, click **📤 Send to care team (EHR)** (`static/index.html → sendPlanToEhr()`).
   It confirms, prepends a DRAFT/clinician‑review banner, and calls the API.
3. **`POST /api/fhir/patient/{patient_id}/document`** (`web_app.py → fhir_write_document`)
   writes it via `fhir/client.py → FHIRClient.create_document_reference()` →
   `POST {fhir_base}/DocumentReference`.

### Resource shape (`create_document_reference`)
```json
{
  "resourceType": "DocumentReference",
  "status": "current",
  "docStatus": "preliminary",
  "type": { "coding": [{ "system": "http://loinc.org", "code": "18842-5", "display": "Discharge summary" }],
            "text": "Discharge Plan (DRAFT — review required)" },
  "subject": { "reference": "Patient/<id>" },
  "date": "<ISO-8601>",
  "content": [{ "attachment": { "contentType": "text/plain", "data": "<base64 plan text>",
                                "title": "Discharge Plan (DRAFT — review required)" } }]
}
```

### Endpoint
| | |
|---|---|
| Method/path | `POST /api/fhir/patient/{patient_id}/document` |
| Auth | logged‑in **and** active FHIR session with `DocumentReference.write` |
| Rate limit | 30/hour |
| Body | `{ "content": "<required plan text>", "title"?: "..." }` |
| Success | `200 { "success": true, "id": "<DocumentReference id>", "resource": {...} }` |
| Errors | `400` no content · `401` no auth/session or token expired · `403` patient‑context mismatch **or** `DocumentReference.Write` not granted · `502` EHR write failed (surfaces Epic's error detail) |

Writes are **not retried** (a timed‑out write must not be silently duplicated). The endpoint is
`# pragma: no cover` (live‑EHR dependent); the builder + config are unit‑tested in
`tests/test_fhir_write.py`.

## Epic app — registration (you do this in Epic)

You can add write to your **existing patient app**, or use a dedicated write app. The shipped
config (`epic_provider`) expects a dedicated app:

1. **fhir.epic.com → Build Apps → Create** — **Application Audience: Patients**.
2. **Incoming APIs (R4):** add the **read** set (Patient, Condition, MedicationRequest,
   AllergyIntolerance, Appointment, CareTeam, DocumentReference — Read + Search) **plus**
   **`DocumentReference.Create (Clinical Notes) (R4)`** (and optionally `DocumentReference.Update`).
3. **Endpoint/Redirect URI:** `https://discharge-planning.vercel.app/api/auth/epic/callback`.
4. Public client (leave confidential unchecked) unless you set `FHIR_CLIENT_SECRET_EPIC_PROVIDER`.
5. **SMART Scope Version** to match `EPIC_PROVIDER_SMART_VERSION` (default `v1`).
6. Fill **Summary**, **Save & Ready for Sandbox**, copy the **Non‑Production Client ID**.

## Environment variables (`fhir/ehr_config.py → epic_provider`)

| Var | Purpose | Default |
|---|---|---|
| `FHIR_CLIENT_ID_EPIC_PROVIDER` | Write‑back app client ID (required to enable) | — |
| `FHIR_CLIENT_SECRET_EPIC_PROVIDER` | Set only if the app is a confidential client | — (public/PKCE) |
| `FHIR_SCOPES_EPIC_PROVIDER` | Space‑separated scope override | patient read set + `patient/DocumentReference.write` |
| `EPIC_PROVIDER_SMART_VERSION` | `v1`/`v2` to match the app | `v1` |
| `FHIR_BASE_URL_EPIC` | Shared Epic FHIR base | Epic sandbox |

Verify at **`/api/fhir/status`** — `epic_provider` ("Epic (write‑back)") shows `configured: true`
once the client ID is set.

## Use it
**Import from EHR → "Epic (write‑back)"** → log in as the sandbox **patient** (e.g. `fhircamila`)
→ generate a plan → **📤 Send to care team (EHR)** → confirm. The plan is filed as a draft
DocumentReference on the chart.

## Caveats
- Epic's `DocumentReference.Create` availability/required fields vary by org/sandbox; the endpoint
  surfaces Epic's exact error on 400/403/502 so you can adjust (e.g. add `category`/`context`).
- ⚠ NEEDS VERIFICATION: the LOINC `type` (`18842-5` Discharge summary) and whether your Epic
  requires `context.encounter` — tune per your environment if Epic rejects the create.
- Production requires Epic app review + switching `FHIR_CLIENT_ID_EPIC_PROVIDER` to the
  **Production** client ID, and the hospital enabling the write API.
