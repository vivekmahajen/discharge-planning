# Discharge Planning AI — Part 3: Features

This document describes each user-facing feature using a consistent template. Every behavioral claim is cited as `file → function/route`. Acronyms are defined on first use; see `docs/00-overview.md § 1.12 Glossary` for the full list. Modes referenced: **FILE MODE** (no DB) and **DB MODE** (PostgreSQL) — see `docs/00-overview.md § 1.4`.

> **PHI note.** Patient-identifying fields are flagged **(PHI)**. All examples are synthetic.

## Table of Contents

- [(a) AI discharge-plan generation](#a-ai-discharge-plan-generation)
- [(b) Predictive LOS / discharge-date](#b-predictive-los--discharge-date)
- [(c) Patient persistence](#c-patient-persistence)
- [(d) Post-acute directory](#d-post-acute-directory)
- [(e) Eligibility verification](#e-eligibility-verification)
- [(f) Clinical-document generators](#f-clinical-document-generators)
- [(g) TCM module](#g-tcm-module)
- [(h) SMART-on-FHIR EHR integration](#h-smart-on-fhir-ehr-integration)
- [(i) Org onboarding & invites](#i-org-onboarding--invites)
- [(j) Security](#j-security)
- [(k) Report export](#k-report-export)
- [Open Questions](#open-questions)

---

**Acronyms used in this document (first-use key):** LOS = Length of Stay; SNF = Skilled Nursing Facility; IRF = Inpatient Rehabilitation Facility; LTACH = Long-Term Acute Care Hospital; TCM = Transitional Care Management; MDM = Medical Decision Making; HRRP = Hospital Readmissions Reduction Program; CDPH = California Department of Public Health; IMM = Important Message from Medicare; CMS = Centers for Medicare & Medicaid Services; Medi-Cal = California Medicaid; QIO = Quality Improvement Organization; LACE = readmission-risk index; PKCE = Proof Key for Code Exchange.

---

## (a) AI discharge-plan generation

**What it delivers.** A complete, Markdown discharge plan synthesized by five LLM specialist agents and a coordinator, streamed live to the browser, with optional patient-record persistence, TCM episode creation, and barrier extraction.

**Where it lives.**
- Screen: home page `static/index.html` (served at `GET /`).
- Backend: `web_app.py → stream_plan` (the generator), `web_app.py → create_plan` (route wrapper) at **`POST /api/plan/stream`**; agents in `agents/*`; orchestrator (CLI) in `orchestrator.py`.

**How it works (step-by-step).**
1. `create_plan` records `request.state.audit_mrn` from `patient_data["mrn"]` **(PHI)** for the audit middleware, then returns a `StreamingResponse` of SSE events (`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`).
2. If `zip_code` present (DB MODE), it enriches `patient_data["nearby_facilities"]` from the directory (`search_facilities`).
3. If `mrn` + `admission_date` present (DB MODE), it upserts the patient, saves a snapshot, and starts a plan run, emitting a `patient_record` SSE event; otherwise it emits a `warning` that the plan will not be saved.
4. `stream_plan` builds normalized `agent_data` via `build_agent_data` (maps the form fields to the agent input schema).
5. **Eligibility pre-flight** (only if `ELIGIBILITY_ENABLED` and the service imported): detects payer, runs mock or live eligibility, emits `eligibility_result`, and injects `_eligibility_result` into the data so the insurance agent sees real-time coverage.
6. The five LLM agents run concurrently via an `asyncio.Queue`, each emitting `agent_start` then `agent_complete` (or `agent_error`). Each uses `claude-sonnet-4-6`, `max_tokens=4000`, `temperature=0.2`, with its domain `SYSTEM_PROMPT` (`agents/base_agent.py`).
7. The coordinator runs (`coordinator_start` → `coordinator_complete`), `claude-sonnet-4-6`, `max_tokens=8000`, producing the final fixed-section Markdown plan (`agents/coordinator.py → CoordinatorAgent.SYSTEM_PROMPT`).
8. Post-stream (DB MODE): saves each `agent_output`, completes the plan run with the coordinator output + a fresh `predict_los` result, conditionally creates a TCM episode (`_maybe_create_tcm_episode`, emitting `tcm_episode_created` or `tcm_not_applicable`), and runs the `BarrierExtractionAgent` to create milestones (emitting `barriers_detected`).

**SSE event types** (`web_app.py → stream_plan` / `create_plan`): `patient_record`, `warning`, `eligibility_result`, `agent_start`, `agent_complete`, `agent_error`, `coordinator_start`, `coordinator_complete`, `tcm_episode_created`, `tcm_not_applicable`, `barriers_detected`, `error`.

**Inputs/outputs.** Input: free-form patient JSON body (form fields like `patient_name` **(PHI)**, `mrn` **(PHI)**, `age`, `gender`, `admission_date`, `primary_diagnosis`, medication lists, therapy evals, insurance, social fields). Output: SSE stream; the final plan is the coordinator's Markdown.

**Mode/role requirements.** Any authenticated user (`Depends(get_current_org)`). Plan generation itself works in FILE MODE (no save); persistence/TCM/barriers require DB MODE.

**Limits & failure modes.** Rate limit **`10/hour`** per key. Subject to the global AI budget guard → **503** when `GLOBAL_AI_HOURLY_CAP` exceeded. Missing `ANTHROPIC_API_KEY` → an `error` SSE event and the stream ends. A single agent failure emits `agent_error` and the coordinator proceeds with partial output (`orchestrator.py → run`, `web_app.py → stream_plan`).

---

## (b) Predictive LOS / discharge-date

**What it delivers.** A predicted length of stay, discharge date with an 80% confidence range, a risk tier, and the top contributing factors.

**Where it lives.**
- Screen: `static/predictive-discharge.html` (`GET /predictive-discharge`).
- Backend: `agents/predictive_los.py`; route **`POST /api/predict/los`** (`web_app.py → predict_los_endpoint`). Also invoked inside the plan stream to populate `plan_runs.los_prediction`.
- Training: `scripts/train_los_model.py` (produces `models/los_model.joblib`).

**How it works.** `predict_los` loads the cached joblib bundle (`LOSModelBundle` with median/p10/p90 quantile models). `extract_features` derives 12 features (age, ICD-10 chapter, comorbidity count, insurance type, has_pt/ot/st, living_alone, has_caregiver, snf_days_used, discharge_to_snf, admission_month). If the model file is missing, `_heuristic_los` produces a deterministic estimate from weighted feature addends. Discharge dates are computed by adding median/p10/p90 days to `admission_date`. Risk tier is bucketed by median LOS (`Short <4`, `Moderate <8`, `Extended ≤14`, `Complex >14`). **No LLM call.**

**Inputs/outputs.** Input: patient feature dict. Output: `LOSPrediction` dataclass (`predicted_los_days`, `los_p10/p90`, three discharge dates, `risk_tier`, `risk_color`, `top_factors`, `model_source` = `ml_model`|`heuristic`, `model_mae_days`, `confidence_pct=80`).

**Mode/role requirements.** Any authenticated user; works in FILE MODE (no DB needed — model is a local file).

**Limits & failure modes.** Rate limit **`60/hour`**. The `PredictiveLOSAgent.run` wraps prediction in try/except and returns a heuristic-baseline message string on error. scikit-learn version pinned `>=1.9.0,<1.10` so the committed model unpickles (`requirements.txt`). ⚠ NEEDS VERIFICATION: whether `models/los_model.joblib` is committed/present in all deployments (otherwise the heuristic path is always used).

---

## (c) Patient persistence

**What it delivers.** Saved patient records with version history: patient row, immutable snapshots, plan runs, per-agent outputs, notes, a status lifecycle, and run export. **DB MODE only.**

**Where it lives.**
- Screens: `static/my-patients.html` (`GET /my-patients`), `static/patient-detail.html` (`GET /patients/{id}`).
- Backend: `db/patients.py`; routes under `/api/patients*` in `web_app.py`.

**How it works.** During plan generation (`create_plan`), `get_or_create_patient` upserts on `(mrn, admission_date, org_domain)`, `save_snapshot` stores the full submitted form as JSONB, `start_plan_run` opens a run, `save_agent_output` records each agent's text, and `complete_plan_run` finalizes with the coordinator plan + LOS JSON. The patient list/detail/prefill endpoints read these; `org_domain` (from email) scopes all queries.

**Status lifecycle.** `VALID_STATUSES = {"active", "pending_discharge", "discharged", "readmitted"}` (`db/patients.py`). `PATCH /api/patients/{id}/status` (`web_app.py`) rejects values outside the set with **400** and records the change in `status_history`. See `docs/data-model.md § Patient status lifecycle`.

**Endpoints** (all `Depends(get_current_org)`):
| Endpoint | Limit | Purpose |
|---|---|---|
| `GET /api/patients` | 120/hour | list/search patients |
| `GET /api/patients/{id}` | 120/hour | detail |
| `GET /api/patients/{id}/prefill` | 120/hour | prefill form from latest snapshot |
| `PATCH /api/patients/{id}/status` | 60/hour | status change |
| `POST /api/patients/{id}/notes` | 60/hour | add note **(PHI)** |
| `DELETE /api/patients/{id}/notes/{note_id}` | 60/hour | soft-delete note |
| `GET /api/patients/{id}/runs/{run_id}/export` | 30/hour | export a run |
| `PATCH /api/patients/{id}/discharge-data` | 60/hour | record actual discharge/ROI data |

**Inputs/outputs.** JSON bodies/results scoped to the caller's `org_domain`. Snapshots and notes hold PHI.

**Mode/role requirements.** DB MODE; otherwise endpoints return empty results (e.g. `list_patients` returns `{"patients": [], "total": 0}` when `not DATABASE_URL`). Any authenticated user within the org.

**Limits & failure modes.** Per-endpoint limits above. Cross-org access is prevented by `org_domain` filtering.

---

## (d) Post-acute directory

**What it delivers.** A searchable directory of California post-acute facilities (SNF/IRF/LTACH) with CMS star ratings, county summaries, distance filtering, and a chunked CMS+CDPH sync.

**Where it lives.**
- Screen: `static/post-acute-directory.html` (`GET /post-acute-directory`).
- Backend: `services/directory_sync.py`, `db/directory.py`; routes `/api/directory/*`.

**How it works.**
- **Search:** `GET /api/directory/search` (`web_app.py`, limit 120/hour) → `db.directory.search_facilities` with ZIP-centroid distance, rating/type/Medi-Cal filters, sort.
- **Facility detail:** `GET /api/directory/facility/{ccn}` (120/hour).
- **County summary:** `GET /api/directory/county-summary` (60/hour).
- **Sync (chunked):** `POST /api/directory/sync` (`directory_sync_trigger`, 120/hour) processes **one ~500-row page per call** to stay within serverless time limits; the client loops passing `next_offset` until `status == "done"`. On the first page it short-circuits if data is <1h fresh and seeds ZIP centroids. Each page calls `services.directory_sync.run_sync_page`, which fetches from CMS (POST then GET fallback through a WAF, browser-like User-Agent), maps records (`_map_cms_record`), assigns coordinates (CMS lat/long, else ZIP centroid), and batch-upserts.
- **Full sync:** `services/directory_sync.py → run_full_sync` fetches all CMS CA facilities concurrently, optionally enriches with CDPH/CHHS location + bed data when `DIRECTORY_ENABLE_CDPH` is set (matched by ZIP + name similarity, `_match_cdph`), and deactivates facilities no longer present.
- **Cron:** `GET /api/directory/cron-sync` (12/hour) is the Vercel daily-cron target (`vercel.json`, `0 6 * * *`), protected by `CRON_SECRET` (Bearer) when configured.
- **Diagnostics:** `GET /api/directory/debug-fetch` (`debug_cms_fetch`) probes CMS reachability; `GET /api/directory/sync-status`.

**Data sources.** CMS Provider Data Catalog datastore (`CMS_API`), CDPH via CHHS (`CHHS_API`, location + bed resources). See `services/directory_sync.py` constants.

**Inputs/outputs.** Search query params (zip, radius, type, rating, medi-cal, sort, limit); results are facility rows from `db/directory.py § facilities`.

**Mode/role requirements.** DB MODE — endpoints return **503** "Directory database not available" when `not DATABASE_URL`. Any authenticated user (cron endpoint is unauthenticated but `CRON_SECRET`-gated).

**Limits & failure modes.** Per-endpoint limits above. CMS WAF 403s are mitigated by the browser UA + POST→GET fallback; CDPH enrichment is best-effort and never fatal (`fetch_cdph_ca_facilities` returns `{}` on error). Bounded HTTP timeouts prevent serverless hangs.

---

## (e) Eligibility verification

**What it delivers.** Real-time insurance eligibility (270/271) with payer auto-detection, a mock mode, and DB-mode caching.

**Where it lives.** `services/eligibility.py`; routes `/api/eligibility/*`; integrated into the plan stream as a pre-flight.

**How it works.**
- **Payer detection:** `detect_payer_id` matches a payer name against `KNOWN_PAYERS` aliases (Medicare/CMS, Medi-Cal/CAMC, Aetna, UHC, Cigna, Humana, Anthem CA, Health Net, Kaiser, Molina, L.A. Care, IEHP, CalOptima, Partnership) → `(payer_id, canonical_name)`.
- **Live check:** `check_eligibility` POSTs an X12-270-style JSON payload to Stedi's medical-network eligibility v3 endpoint with `Authorization: Key {STEDI_API_KEY}` and a 10s timeout, then `parse_271_response` extracts eligibility status, coverage dates, deductible/OOP, specialist copay, prior-auth flag.
- **Mock:** `get_mock_result` returns canned results per payer (Medicare with 87 SNF days, Medi-Cal with prior auth required, generic PPO).
- **Cache (DB MODE):** key = SHA-256[:32] of `member_id|payer_id|date` (`_make_cache_key`), stored in `eligibility_cache` with `expires_at`.
- **Plan pre-flight:** in `stream_plan`, when `ELIGIBILITY_ENABLED`, the result is emitted as `eligibility_result` and injected as `_eligibility_result` for the insurance agent (`agents/insurance_authorization.py → format_input`).

**Endpoints:** `GET /api/eligibility/payers` (120/hour), `POST /api/eligibility/mock` (60/hour), `POST /api/eligibility/check` (30/hour).

**Inputs/outputs.** Input: member id **(PHI)**, patient name **(PHI)**, DOB **(PHI)**, payer, NPI. Output: `EligibilityResult` dataclass (`source` = `live`|`mock`).

**Mode/role requirements.** Live check requires `STEDI_API_KEY` + `HOSPITAL_NPI`; pre-flight requires `ELIGIBILITY_ENABLED`. Caching requires DB MODE. Any authenticated user.

**Limits & failure modes.** `check_eligibility` raises `ValueError` on HTTP 422 (bad member/payer) and `RuntimeError` on other non-2xx (`services/eligibility.py`). Without `ELIGIBILITY_ENABLED` the plan pre-flight is skipped entirely (insurance agent runs AI-only).

---

## (f) Clinical-document generators

**What it delivers.** Standalone AI tools that generate specific clinical documents from pasted/structured input. Each is a static HTML page + a generation endpoint. All use `claude-sonnet-4-6` (`web_app.py`).

**Where it lives & how it works.**

| Tool | Page (route) | Endpoint | Limit | Model / notes |
|---|---|---|---|---|
| Discharge summary generator | `static/summary-generator.html` (`/summary-generator`) | `POST /api/summary/generate` | 20/hour | `claude-sonnet-4-6` |
| Full discharge summary | `static/discharge-summary-generator.html` (`/discharge-summary-generator`) | `POST /api/discharge-summary/generate` | 20/hour | `claude-sonnet-4-6` |
| Teach-back checklist | `static/teachback-checklist.html` (`/teachback-checklist`) | `POST /api/teachback/generate` | 30/hour | `claude-sonnet-4-6` |
| CDPH compliance | `static/cdph-compliance.html` (`/cdph-compliance`) | `POST /api/cdph-compliance/analyze` | 30/hour | `claude-sonnet-4-6` |
| HRRP flagging | `static/hrrp-flagging.html` (`/hrrp-flagging`) | `POST /api/hrrp/generate` | 30/hour | `claude-sonnet-4-6` |
| ROI narrative | `static/roi-tracker.html` (`/roi-tracker`) | `POST /api/roi/generate` | 30/hour | `claude-sonnet-4-6` |
| Multilingual instructions | `static/multilingual-prompt-system.html` (`/multilingual-prompt-system`) | `POST /api/multilingual/generate` | 30/hour | `claude-sonnet-4-6`; `LANGUAGE_CONFIGS` (es-MX etc.) |
| IMM prompt system | `static/imm-prompt-system.html` (`/imm-prompt-system`) | — (static tool page) | — | ⚠ NEEDS VERIFICATION: no `/api/immunisation` or IMM generation route was found; IMM appears to be a client-side static tool. The audit prefix `/api/immunisation` exists but no matching route was located. |

Each generation endpoint calls `client.messages.create(model="claude-sonnet-4-6", ...)` directly in `web_app.py` (lines ~1225, 1275, 1321, 1389, 1542, 1624, 3916), several with `temperature=0` for deterministic compliance output (e.g. summary at line 1225).

**Inputs/outputs.** Input: tool-specific JSON (clinical text, patient context, target language). Output: generated document text (JSON or streamed depending on endpoint). HRRP = Hospital Readmissions Reduction Program; CDPH = California Department of Public Health.

**Mode/role requirements.** Any authenticated user; FILE MODE OK (no persistence required).

**Limits & failure modes.** Per-tool limits above; the AI-budget guard covers `/api/summary/generate`, `/api/discharge-summary/generate`, `/api/teachback/generate`, `/api/cdph-compliance/analyze`, `/api/roi/generate`, `/api/hrrp/generate`, `/api/multilingual/generate` → 503 when capped. Missing `ANTHROPIC_API_KEY` fails the call.

---

## (g) TCM module

**What it delivers.** Transitional Care Management billing automation: episode creation, AI-assessed MDM complexity, automatic CPT 99495/99496 selection, contact/visit deadline tracking, a compliance dashboard, claim generation, and claim export. **DB MODE only.**

**Where it lives.** `tcm_module.py` (pure logic), `migrations/tcm_module.sql` (tables), routes `/api/tcm/*`, calculator page `static/tcm-roi-calculator.html` (`/tcm-roi-calculator`).

**How it works.**
1. **Episode creation:** `POST /api/tcm/episodes` (30/hour) and the auto-path `_maybe_create_tcm_episode` (called from the plan stream when DB MODE). `assess_mdm_complexity` calls `claude-sonnet-4-6`, **`temperature=0`** (deterministic billing) with `MDM_SYSTEM_PROMPT` to read the discharge plan and return JSON: eligibility, MDM complexity (moderate/high), recommended CPT, deadlines, per-element rationales, key diagnoses, estimated reimbursement (`tcm_module.py → assess_mdm_complexity`). It also checks eligibility (excludes hospice, ED-only discharge, duplicate TCM billing, no Part B) and qualifying discharge settings.
2. **CPT selection:** MODERATE MDM → **99495** (14-day visit window); HIGH MDM → **99496** (7-day window). `cpt_final` is the DB-generated `COALESCE(cpt_override, recommended_cpt)`.
3. **Deadlines:** contact deadline = **2 business days** after discharge (`_add_business_days`); visit deadline = 7 or 14 days by CPT (`compute_window_status`).
4. **Contacts/visits:** `POST /api/tcm/episodes/{id}/contacts` (60/hour), `POST /api/tcm/episodes/{id}/visits` (30/hour). A contact qualifies only if `contact_result == 'reached'` (`tcm_contacts.is_qualifying` generated column).
5. **Dashboard:** `GET /api/tcm/dashboard` (60/hour) computes `compute_window_status` per active episode → alert level (green/amber/red), counts red/amber/claim-ready, and an estimated monthly revenue from non-facility rates (`tcm_module.py → _RATES`: 99495 $166.28, 99496 $228.14 non-facility).
6. **Claim generation:** `POST /api/tcm/episodes/{id}/generate-claim` (30/hour) → `generate_tcm_claim` builds a CMS-1500/837P-mapped record with a full audit trail, returns 400 if not claim-eligible, persists via `save_tcm_claim`, and sets episode status to `claim_ready`.
7. **Claim export:** `GET /api/tcm/claims/export` (10/hour, `format=csv|json`) exports claim-ready episodes for clearinghouse submission.
8. **Platform ROI:** `GET /api/tcm/platform-roi` (60/hour).

**State machine.** 11-state `TCMStatus` enum; transitions derived in `compute_window_status`. See `docs/data-model.md § TCM state machine`.

**Inputs/outputs.** Inputs: discharge plan text + episode metadata (provider NPI, discharge date/setting, patient identifiers **(PHI)**). Outputs: episode record, MDM JSON, claim record.

**Mode/role requirements.** DB MODE — every TCM endpoint returns **503** "TCM module requires PostgreSQL" when `not DATABASE_URL`. Any authenticated user within the org (RLS-isolated tables). `ANTHROPIC_API_KEY` required for MDM assessment (`assess_mdm_complexity` raises `ValueError` if unset).

**Limits & failure modes.** Per-endpoint limits above. MDM JSON is parsed after stripping markdown fences; malformed JSON propagates as an exception. `generate_tcm_claim` returns `{"claimable": False, "reason": ...}` when windows are missed.

---

## (h) SMART-on-FHIR EHR integration

**What it delivers.** Pull a patient's clinical data directly from an EHR (Epic, Cerner/Oracle Health, athenahealth) via SMART-on-FHIR and generate a discharge plan from it — no manual data entry.

**Where it lives.** `fhir/auth.py` (PKCE, cookies, token exchange/refresh), `fhir/ehr_config.py` (per-EHR config), `fhir/client.py` (parallel R4 fetch), `fhir/normalizers.py` (FHIR → agent data); routes `/api/fhir/*`, `/launch`, `/api/auth/epic/callback`.

**How it works.**
1. **EHR list / status:** `GET /api/fhir/ehrs`, `GET /api/fhir/status` (`fhir/ehr_config.py → list_ehr_display`, `config_status`).
2. **Authorize:** `GET /api/fhir/authorize?ehr=...&launch=...&iss_override=...` (`web_app.py → fhir_authorize`). Resolves auth/token endpoints (priority: `iss_override` SMART discovery > env overrides > URL-derived). Generates PKCE only when `smart_version != "v1"` (`generate_pkce_pair`, S256). Stores `state`, `code_verifier`, endpoints, EHR, user in a signed `fhir_auth_state` cookie (5-min TTL). Builds the authorize URL with `aud` (FHIR base, required by Epic for standalone v1 **and** v2), `code_challenge`/`code_challenge_method` when PKCE, and prepends `launch/patient` scope for EHR-embedded launches.
3. **Callback:** `GET /api/fhir/callback` (`web_app.py → fhir_callback`) validates `state` against the cookie (CSRF guard), exchanges the code for tokens (`exchange_code_for_token`; HTTP Basic for confidential clients like athenahealth), and stores tokens in the signed `fhir_session` cookie (8-h TTL). Tokens/PHI are never persisted to the DB (`fhir/auth.py` docstring).
4. **Session:** `GET /api/fhir/session` reports the active FHIR session; tokens are silently refreshed when within `TOKEN_REFRESH_BUFFER` (`needs_refresh`, `refresh_access_token`).
5. **Patient fetch:** `GET /api/fhir/patient/{id}` and the plan generator fetch a normalized bundle via `FHIRClient.fetch_patient_bundle` — Patient, Condition (active), MedicationRequest (active), AllergyIntolerance (active), Appointment (booked), CareTeam (active), DocumentReference (discharge-summary LOINC 34133-9), all in parallel with `asyncio.gather(return_exceptions=True)` so one failed resource yields a `FetchWarning` rather than aborting (`fhir/client.py`). 401→`FHIRAuthError`, 403→`FHIRForbiddenError`, 404→empty bundle, 429/5xx→retry with backoff `[1,2,4,8]s`. Logs counts/types only, never PHI values.
6. **Plan from FHIR:** `POST /api/fhir/patient/{id}/plan` (`generate_plan_from_fhir`) enforces patient-context match (403 on mismatch), maps the bundle via `fhir_bundle_to_agent_data`, overlays optional supplemental fields, and streams the plan via the same `stream_plan`.

**Epic specifics.** Epic is a **public** client (PKCE), pinned to **SMART v1** by default (`EPIC_SMART_VERSION=v1` → no PKCE per the v1 path, but `aud` still sent); override to `v2` per app. Scopes overridable via `FHIR_SCOPES_EPIC` (space-separated) because Epic rejects the whole authorize request if a requested scope maps to an unregistered API (`fhir/ehr_config.py → _scopes_from_env`). Default Phase-1 scopes are read-only `patient/*.read` + `openid` (`FHIR_SCOPES_PHASE1`). Auth/token endpoints derived from the FHIR base URL pattern, overridable via `EPIC_AUTH_ENDPOINT`/`EPIC_TOKEN_ENDPOINT`. Cerner and athenahealth configured analogously; athenahealth is a **confidential** client (`FHIR_CLIENT_SECRET_ATHENA`).

**Inputs/outputs.** Output bundle: normalized dataclasses in `fhir/schemas.py` (`PatientBundle` never persisted). Input to plan: FHIR-derived + supplemental JSON.

**Mode/role requirements.** Works in FILE MODE (stateless, cookie-based). Requires the relevant `FHIR_CLIENT_ID_*` configured. Any authenticated app user. A `CapabilityStatement` is served at `GET /fhir/metadata` for ONC 170.315(g)(10) testing.

**Limits & failure modes.** If the FHIR module failed to import, all FHIR routes return an "unavailable" response (`_FHIR_IMPORT_ERROR`, `_fhir_unavailable`). SMART discovery failures → 502; token expiry → 401; EHR errors → 503.

---

## (i) Org onboarding & invites

**What it delivers.** Self-service organization creation, slug availability check, invitation-based user provisioning, and org/superadmin administration. **DB MODE for full multi-tenancy.**

**Where it lives.** Routes `/api/onboard/*`, `/api/invite/*`, `/api/admin/*`, `/api/superadmin/*` in `web_app.py`; tables in `migrations/001_multi_tenant_base.sql`.

**How it works.**
- **Create org:** `POST /api/onboard/create-org` (5/hour, IP-keyed) creates an `organizations` row + first admin user.
- **Slug check:** `GET /api/onboard/check-slug` (30/minute, IP-keyed).
- **Invitations:** `POST /api/admin/invite` (30/hour) — gated to `org_admin`/`super_admin` via `require_role` — creates an `invitations` row with a unique token and 7-day expiry. Accept flow: `GET /api/invite/accept` (20/hour, IP) renders, `POST /api/invite/accept` (10/hour, IP) consumes the token and creates the user.
- **Admin/superadmin:** `GET /api/admin/users` (`org_admin`/`super_admin`), `GET /api/superadmin/orgs` (`super_admin`) list users / cross-org orgs.

**Inputs/outputs.** Org name/slug, invitee email/role, accept token. Outputs are JSON.

**Mode/role requirements.** Admin/invite/superadmin routes enforce roles via `require_role` (see `docs/00-overview.md § 1.6`). Multi-tenancy + RLS require DB MODE; in FILE MODE there is a single implicit org (`DEFAULT_ORG_ID`).

**Limits & failure modes.** IP-keyed limits on the public onboarding/invite endpoints prevent enumeration/abuse. Invitations expire after 7 days (`invitations.expires_at`).

---

## (j) Security

**What it delivers.** Defense-in-depth: progressive account lockout, layered rate limiting + global AI budget, HIPAA audit logging, and signed-cookie session integrity.

**Where it lives.** `web_app.py` (lockout, limiter, audit middleware, session helpers); `fhir/auth.py` (FHIR session integrity); `migrations/001_multi_tenant_base.sql` (RLS).

**How it works.**
- **Lockout:** `LOCKOUT_THRESHOLDS = {5:60, 10:300, 20:1800, 50:86400}` over a rolling 1-hour failure window; in-memory `_login_failures`/`_login_lockouts`; cleared on success (`_check_lockout`, `_record_failed_attempt`, `_apply_lockout`, `_clear_failed_attempts`).
- **Rate limiting:** slowapi moving-window, user- or IP-keyed (`_get_key`, `_get_ip_key`); structured 429 with `Retry-After`/`X-RateLimit-*` headers (`_rate_limit_handler`). See `docs/00-overview.md § 1.8`.
- **Global AI budget:** middleware → 503 with `Retry-After: 300` when `GLOBAL_AI_HOURLY_CAP` exceeded (`global_ai_budget_guard`).
- **Audit:** middleware logs audited prefixes with email/org/MRN/status/IP; DB-persisted (`write_audit_log`) or logged in FILE MODE (`_audit_log_middleware`). See `docs/00-overview.md § 1.9`.
- **Session integrity:** itsdangerous-signed `dp_session` cookie (`httponly`, `samesite=lax`, `secure`, 8-h TTL); `SECRET_KEY` mandatory at startup. PBKDF2-SHA256 (260k iterations) password hashing with constant-time compare. RLS enforces tenant isolation at the DB layer.

**Mode/role requirements.** Applies in all modes (lockout/rate-limit/sessions). RLS isolation is DB MODE.

**Limits & failure modes.** ⚠ NEEDS VERIFICATION: lockout and global-AI counters are in-process (per-instance), so behavior across serverless instances/restarts is not guaranteed (see `docs/00-overview.md § Open Questions`).

---

## (k) Report export

**What it delivers.** A client-side helper letting any tool page serialize its on-screen report to a clean, self-contained, offline-openable HTML file or print it to PDF.

**Where it lives.** `static/report-export.js` (global `RE` object), loaded by the tool pages.

**How it works.** `RE.buildDoc({title, subtitle, accent, bodyHtml, disclaimer, print})` builds a full standalone HTML document (inline CSS, `@media print` rules, optional auto-print script). `RE.download(filename, html)` creates a Blob (`text/html`) and triggers a browser download (e.g. "Download HTML"). `RE.print(html)` opens the document and invokes `window.print()` for "Save as PDF". Helpers `RE.esc`, `RE.table(rows)`, `RE.section`, `RE.box`, `RE.list` build the `bodyHtml`, with HTML-escaping of all values (`report-export.js → esc`).

**Inputs/outputs.** Input: report data assembled on the page. Output: a downloaded `.html` file or a print/PDF dialog. Entirely client-side — no server call, no PHI leaves the browser via this path.

**Mode/role requirements.** Runs in the browser on any tool page; no mode/role dependency.

**Limits & failure modes.** Output fidelity depends on the page assembling correct `bodyHtml`; PDF rendering depends on the browser's print engine.

---

## Open Questions

- ⚠ No server-side IMM generation route (`/api/immunisation*`) was found; IMM appears to be a static client-side tool (`static/imm-prompt-system.html`) despite the audit-prefix entry `/api/immunisation`. Confirm whether IMM generation is purely client-side.
- ⚠ Presence of `models/los_model.joblib` in deployments determines whether predictive LOS uses the ML model or always the heuristic fallback.
- ⚠ Several generator endpoints (summary/discharge-summary/teachback/etc.) were confirmed to use `claude-sonnet-4-6`; whether any stream vs. return-JSON was not exhaustively traced per endpoint.
- ⚠ `_maybe_create_tcm_episode` auto-creation criteria (which discharge settings/MDM results trigger an episode) were read at a high level; exact gating thresholds were not fully extracted.
- ⚠ Lockout / global-AI-budget per-instance behavior under serverless (carried from `docs/00-overview.md`).
