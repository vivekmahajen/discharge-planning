# EHR Write‑Back — Communication to Care Team

Writes the AI discharge plan back into the EHR as a **FHIR R4 `Communication`** (a note to
the care team). This is an explicit **clinician action** that files a clearly‑labeled **DRAFT**
for review — never automatic.

> Read‑back (pulling patient data) uses the **patient** Epic app. Write‑back requires a
> **separate provider/clinician** Epic app with write scopes — Epic gates and approves writes
> independently of reads, and clinical writes generally require provider context.

## How it works

1. Clinician connects a **provider** EHR session — **Import from EHR → "Epic (provider write‑back)"**
   (`/api/fhir/authorize?ehr=epic_provider`), which requests `user/*` scopes incl.
   `user/Communication.write`.
2. On the generated plan, click **📤 Send to care team (EHR)** (`static/index.html → sendPlanToEhr()`).
   It confirms, prepends a DRAFT/clinician‑review banner to the plan text, and calls the API.
3. **`POST /api/fhir/patient/{patient_id}/communication`** (`web_app.py → fhir_send_communication`)
   builds the resource and writes it via `fhir/client.py → FHIRClient.create_communication()`
   → `POST {fhir_base}/Communication`.

### Resource shape (`create_communication`)
```json
{
  "resourceType": "Communication",
  "status": "completed",
  "category": [{ "coding": [{ "system": ".../communication-category", "code": "notification" }],
                "text": "Discharge plan (DRAFT — review required)" }],
  "subject": { "reference": "Patient/<id>" },
  "sent": "<ISO-8601>",
  "payload": [{ "contentString": "DRAFT — AI-prepared discharge plan... <plan text>" }],
  "recipient": [{ "reference": "CareTeam/<id>" }],   // optional
  "sender": { "display": "<clinician email/name>" }
}
```

### Endpoint
| | |
|---|---|
| Method/path | `POST /api/fhir/patient/{patient_id}/communication` |
| Auth | logged‑in **and** active FHIR session (provider) |
| Rate limit | 30/hour |
| Body | `{ "message": "<required>", "category_text"?: "...", "recipients"?: ["CareTeam/x"], "sender_display"?: "..." }` |
| Success | `200 { "success": true, "id": "<communication id>", "resource": {...} }` |
| Errors | `400` no message · `401` no auth/session or token expired · `403` patient‑context mismatch **or** `Communication.Write` not granted · `502` EHR write failed |

Writes are **not retried** (a timed‑out write must not be silently duplicated). The endpoint
is `# pragma: no cover` (live‑EHR dependent); the builder and config are unit‑tested in
`tests/test_fhir_write.py`.

## Epic provider app — registration (you do this in Epic)

Create a **second** Epic app (this is separate from the patient read app):

1. **Application Audience → Clinicians or Administrative Users**.
2. **SMART on FHIR → R4**; **SMART Scope Version** to match (`EPIC_PROVIDER_SMART_VERSION`, default `v1`).
3. **Incoming APIs (R4):** add **`Communication.Read`** and **`Communication.Write`** (a.k.a.
   `Communication.Create`), plus `Patient.Read` for context. (Epic must enable the write API.)
4. **Redirect/Endpoint URI:** `https://discharge-planning.vercel.app/api/auth/epic/callback`
   (same unified callback).
5. Confidential vs public: if you register it confidential, set `FHIR_CLIENT_SECRET_EPIC_PROVIDER`
   (the app auto‑switches to confidential when that secret is present).
6. **Save & Ready for Sandbox**, copy the **Non‑Production Client ID**.

## Environment variables (`fhir/ehr_config.py → epic_provider`)

| Var | Purpose | Default |
|---|---|---|
| `FHIR_CLIENT_ID_EPIC_PROVIDER` | Provider app client ID (required to enable write‑back) | — |
| `FHIR_CLIENT_SECRET_EPIC_PROVIDER` | Set only if the provider app is a confidential client | — (public/PKCE) |
| `FHIR_SCOPES_EPIC_PROVIDER` | Space‑separated scope override | `openid user/Patient.read user/Communication.read user/Communication.write` |
| `EPIC_PROVIDER_SMART_VERSION` | `v1`/`v2` to match the app | `v1` |
| `FHIR_BASE_URL_EPIC` | Shared Epic FHIR base (also used by the read app) | Epic sandbox |

Verify config any time at **`/api/fhir/status`** — `epic_provider` shows `configured: true` and
its resolved scopes/endpoints once the client ID is set.

## Caveats
- Epic's `Communication.Write` availability depends on the org/sandbox; if not granted the API
  returns **403** with a clear message.
- Production requires Epic app review/attestation and the hospital enabling the write API, then
  switching `FHIR_CLIENT_ID_EPIC_PROVIDER` to the **Production** client ID.
- ⚠ NEEDS VERIFICATION: exact recipient references (CareTeam/Practitioner) for a given org — the
  UI currently sends no `recipient` (Epic routes by patient/encounter context); pass `recipients`
  in the request body if your workflow needs explicit routing.
