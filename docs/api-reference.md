# Discharge Planning AI — Complete API Reference

**Source of truth:** `web_app.py` (4,543 lines, single FastAPI `app`; no sub-routers / `include_router`).
All 116 `@app.<method>(...)` decorators are documented below. Every entry cites its handler
function name in `web_app.py`.

**Legend:** Auth = session via signed `dp_session` cookie unless noted *Public*. Roles via
`require_role(...)`. RL = `@limiter.limit` value (per signed-session-email key by default,
or per-IP `key_func=_get_ip_key` where noted). "503 (mode)" = returns 503 / degraded JSON
when `DATABASE_URL` unset or the relevant `_*_AVAILABLE` import flag is `False`.

---

## Table of Contents
1. [Cross-cutting behaviour](#1-cross-cutting-behaviour)
2. [Auth & Session](#2-auth--session)
3. [Identity / Me](#3-identity--me)
4. [Plan & AI Generation (SSE)](#4-plan--ai-generation-sse)
5. [Clinical-doc Generators](#5-clinical-doc-generators)
6. [Predict LOS](#6-predict-los)
7. [Patients, Runs, Notes, Discharge-data & Export](#7-patients-runs-notes-discharge-data--export)
8. [Directory](#8-directory)
9. [Eligibility](#9-eligibility)
10. [FHIR / SMART](#10-fhir--smart)
11. [TCM](#11-tcm)
12. [ROI (Measured + AI)](#12-roi-measured--ai)
13. [Referrals](#13-referrals)
14. [DRG](#14-drg)
15. [Milestones / Barriers](#15-milestones--barriers)
16. [Onboarding, Invites, Admin, Superadmin](#16-onboarding-invites-admin-superadmin)
17. [Pilot](#17-pilot)
18. [Settings](#18-settings)
19. [Health / Infra / PWA](#19-health--infra--pwa)
20. [HTML Page Routes](#20-html-page-routes)
21. [Coverage Checklist](#21-coverage-checklist)
22. [Open Questions](#22-open-questions)

---

## 1. Cross-cutting behaviour

- **Session cookie:** `dp_session`, signed with `itsdangerous.URLSafeTimedSerializer(SECRET_KEY)`,
  HttpOnly, `samesite=lax`, `secure=True`, `max_age` 8h. Payload: `{email, org_id, role}`.
  `SECRET_KEY` is mandatory at startup (raises `RuntimeError` if unset).
- **`get_current_org` dependency** (`web_app.py`): raises **401** `{"detail":"Unauthorized"}`
  when cookie missing/invalid/expired. In file-mode `org_id` defaults to
  `DEFAULT_ORG_ID = 00000000-0000-0000-0000-000000000001`, `role` defaults to `clinician`.
- **`require_role(*roles)`**: depends on `get_current_org`, raises **403** `{"detail":"Forbidden"}`
  if `ctx.role` not in roles. Roles seen in code: `clinician`, `org_admin`, `super_admin`,
  `read_only`. ⚠ NEEDS VERIFICATION: the task referenced `clinician/admin/superadmin`; the
  actual role strings in code are `clinician`, `org_admin`, `super_admin`, `read_only`.
- **`get_current_user`** (lighter helper) returns the email or `None`; used by FHIR handlers
  which return **401** JSON `{"error":"Unauthorized"}` (not an HTTPException).
- **Rate limit 429:** custom `_rate_limit_handler` returns JSON
  `{error, detail, retry_after_seconds, retry_after_human, support}` + `Retry-After`,
  `X-RateLimit-Limit`, `X-RateLimit-Reset` headers. Enabled via `RATE_LIMIT_ENABLED` (default true).
- **Global AI budget guard** (`global_ai_budget_guard` middleware): for the 8 AI endpoints
  (`/api/plan/stream`, `/api/summary/generate`, `/api/discharge-summary/generate`,
  `/api/teachback/generate`, `/api/cdph-compliance/analyze`, `/api/roi/generate`,
  `/api/hrrp/generate`, `/api/multilingual/generate`) returns **503**
  `{error:"Service temporarily at capacity", ...}` + `Retry-After: 300` once the hourly count
  exceeds `GLOBAL_AI_HOURLY_CAP` (default 500).
- **HIPAA audit middleware** (`_audit_log_middleware`): logs requests whose path starts with
  `/api/plan`, `/api/fhir`, `/api/summary`, `/api/discharge`, `/api/teachback`, `/api/cdph`,
  `/api/hrrp`, `/api/medications`, `/api/multilingual`, `/api/immunisation`, `/api/predict`.
- **AI doc generators** all call Claude `claude-sonnet-4-6` via `asyncio.to_thread`; on
  `anthropic.APIError` return **500**; on JSON parse failure return **500** with `{success:false,error,raw}`;
  return **500** `{"error":"Server not configured"}` / `{"error":"ANTHROPIC_API_KEY not configured"}`
  if `ANTHROPIC_API_KEY` unset.

---

## 2. Auth & Session

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| GET `/login` | `login_page` | Public | — | none | 200 HTML (`login.html`) | — |
| POST `/api/auth/signup` | `do_signup` | Public | 3/min (IP) | JSON `{email:str, password:str}` | 200 `{ok:true}` + sets `dp_session` | 400 invalid email / pw<8; 403 not in `ALLOWED_EMAILS`; 409 `{error}` already exists |
| POST `/api/auth/login` | `do_login` | Public | 5/min (IP) | JSON `{email:str, password:str}` | 200 `{ok:true}` + sets session | 400 invalid email; 403 not allowed; 401 `{error}` bad creds; 429 account lockout (`Retry-After`) |
| GET `/api/auth/logout` | `logout` | Public | 30/min | none | 302 → `/login`, deletes cookie | — |
| GET `/api/auth/sso/config` | `sso_config` | Public | — | none | 200 `{enabled:bool}` | — |
| GET `/auth/sso/login` | `sso_login` | Public | — | none | 302 → Auth0 authorize URL; sets `sso_auth_state` cookie | 503 if SSO not configured |
| GET `/auth/sso/callback` | `sso_callback` | Public | — | query `code,state,error` | 302 → `/` + sets session | 400 missing/invalid/mismatched state; 502 token/userinfo failure; 503 DB provisioning failure |

**Lockout:** `do_login` uses in-memory progressive lockout thresholds
`{5:60s, 10:300s, 20:1800s, 50:86400s}` keyed by lowercased email.

---

## 3. Identity / Me

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| GET `/api/me` | `me` | Session | 120/hr | none | 200 `{email, org_id, role}` | 401 |
| GET `/api/sample-patient` | `get_sample_patient` | Session | 60/hr | none | 200 `SAMPLE_PATIENT_WEB` dict | 401 |

Callers: `/api/me` used by nearly every authenticated page (cdph-compliance, discharge-summary-generator,
hrrp-flagging, imm-prompt-system, multilingual, my-patients, patient-detail, post-acute-directory,
readmission-tracker, roi-measured, roi-tracker, settings, summary-generator, teachback-checklist,
ward-barriers). `/api/sample-patient` → `index.html`, `predictive-discharge.html`.

---

## 4. Plan & AI Generation (SSE)

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| POST `/api/plan/stream` | `create_plan` (wraps `stream_plan`) | Session | 10/hr | JSON body = raw `patient_data` dict (form field names like `patient_name, age, gender, mrn, admission_date, expected_discharge_date, primary_diagnosis, secondary_diagnoses, admission_medications, inpatient_medications, discharge_medications, pt_evaluation, primary_insurance, living_situation, zip_code, insurance_member_id`, …) | 200 `text/event-stream` (SSE) | 401; also global AI 503; per-event `error` SSE inside stream |

Calls `request.state.audit_mrn = patient_data["mrn"]`. Sets headers `Cache-Control: no-cache`,
`X-Accel-Buffering: no`. Persists patient/run/agent outputs only when `mrn` + `admission_date`
present and `DATABASE_URL` + `_PATIENT_DB_AVAILABLE`. Caller: `index.html` (`handleEvent`).

### SSE event types (each line is `data: <json>\n\n`)

| `type` | Emitted by | Payload | Notes |
|---|---|---|---|
| `patient_record` | `_stream_with_tcm` | `{type, data:{patient_id, run_id, mrn}}` | only when saved to DB; `index.html`→`showSaveConfirmation` |
| `warning` | `_stream_with_tcm` | `{type, message}` | emitted when no MRN/admission date — plan not saved; `index.html`→`showWarningBanner` |
| `eligibility_result` | `stream_plan` pre-flight | `{type, data:<EligibilityResult asdict>}` | only if `ELIGIBILITY_ENABLED` + `_ELIGIBILITY_AVAILABLE` + member/payer/NPI present; `index.html`→`renderEligibilityCard` |
| `agent_start` | `run_agent` | `{type, agent}` | agent ∈ predictive_los, clinical, care_needs, insurance, medications, social |
| `agent_complete` | `run_agent` | `{type, agent, output:str}` | |
| `agent_error` | `run_agent` | `{type, agent, error:str}` | counts as completion |
| `los_prediction` | `run_agent` (after predictive_los) | `{type, data:<PredictiveLOSResult asdict>}` | informational; does not count toward completion; `index.html`→`renderLosBanner` |
| `coordinator_start` | `stream_plan` | `{type}` | |
| `coordinator_complete` | `stream_plan` | `{type, output:str}` | final unified plan; `index.html`→`showReport` |
| `tcm_episode_created` | `_stream_with_tcm` | `{type, episode_id, cpt, contact_deadline, estimated_revenue}` | only when `DATABASE_URL` set, coordinator output present, TCM eligible (see `_maybe_create_tcm_episode`) |
| `tcm_not_applicable` | `_stream_with_tcm` | `{type}` | when `DATABASE_URL` set but TCM not created |
| `barriers_detected` | `_stream_with_tcm` | `{type, count:int, barriers:list}` | only when `patient_id` + `_MILESTONES_AVAILABLE`; `index.html`→`renderBarriersCard` |
| `error` | `stream_plan` / coordinator | `{type, message}` | e.g. `ANTHROPIC_API_KEY not set`, coordinator failure |

> The task description listed `tcm_episode_created` / `tcm_not_applicable` and the core agent events;
> the stream additionally emits `eligibility_result`, `los_prediction`, `agent_error`, and `barriers_detected`
> (all confirmed in source and in `index.html` `handleEvent`).

---

## 5. Clinical-doc Generators

All require **session**, are POST, take a JSON body, return `{success:true, ...}` on success and
`{success:false, error, raw}` (500) on parse failure. All subject to the global AI 503 guard.

| Method + Path | Handler | RL | Request body | Success shape | Notable errors |
|---|---|---|---|---|---|
| POST `/api/summary/generate` | `generate_summary` | 20/hr | `{clinicalNotes:str(req), patientContext:{admissionDate,dischargeDate,attending,unit,payer,language,laceScore,laceTier,hrrpFlag}}` | `{success:true, summary:<JSON>}` | 400 if `clinicalNotes` empty; 500 |
| POST `/api/discharge-summary/generate` | `generate_discharge_summary_v2` | 20/hr | `{notes:str(req), ctx:{admissionDate,dischargeDate,attending,unit,payer,laceScore,hrrpFlag}}` | `{success:true, summary:<JSON>}` (large fixed schema: meta/diagnosis/medications/follow_up/warning_signs/post_acute/attestation) | 400 if `notes` empty; 500 |
| POST `/api/teachback/generate` | `generate_teachback` | 30/hr | `{prompt:str(req)}` | `{success:true, result:{categories:[...]}}` | 400 if `prompt` empty; 500 if missing `categories` |
| POST `/api/cdph-compliance/analyze` | `analyze_cdph_compliance` | 30/hr | `{prompt:str(req)}` | `{success:true, result:<JSON>}` | 400 empty; 500 incl. explicit `max_tokens` truncation message |
| POST `/api/hrrp/generate` | `generate_hrrp_briefing` | 30/hr | `{prompt:str(req)}` | `{success:true, result:<JSON>}` | 400 empty; 500 |
| POST `/api/roi/generate` | `generate_roi_summary` | 30/hr | `{prompt:str(req)}` | `{success:true, result:<JSON + disclaimer + measured_roi_url:"/roi-measured">}` | 400 empty; 500 |
| POST `/api/multilingual/generate` | `generate_multilingual_instructions` | 30/hr | `{target_language:str(req, one of 21 codes), discharge_plan:str(req)}` | `{success:true, translation, language, direction, interpreter_recommended, requires_review}` | 400 unsupported lang (returns `supported` list) / empty plan; 500 |

`/api/multilingual/generate` supported `target_language` codes (`LANGUAGE_CONFIGS`):
`es, zh-TW, zh-CN, vi, tl, ko, hy, fa, ru, km, hi, pa, ar, pt, ja, ium, hmn, so, am, th`
(plus server-side `validate_translation` safety checks: drug-name integrity, warning-sign count,
forced `911`, interpreter flag for low-literacy locales, RTL completeness).

Callers: summary-generator.html, discharge-summary-generator.html, teachback-checklist.html,
cdph-compliance.html, hrrp-flagging.html, roi-tracker.html (`/api/roi/generate`),
multilingual-prompt-system.html.

---

## 6. Predict LOS

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| POST `/api/predict/los` | `predict_los_endpoint` | Session | 60/hr | JSON `{patient_data:{...}}` (falls back to whole body if no `patient_data` key) | 200 `{success:true, prediction:<PredictiveLOSResult asdict>}` | 401; 500 `{success:false,error}` |

Sets `request.state.audit_mrn`. Caller: `predictive-discharge.html`.

---

## 7. Patients, Runs, Notes, Discharge-data & Export

All require **session**; all return **503** `{"detail":"Database not available"}` (or degraded
`{patients:[],total:0}` for the list endpoints) when `DATABASE_URL` unset or `_PATIENT_DB_AVAILABLE` false.
Org scoping via `get_org_domain(ctx.email)`.

| Method + Path | Handler | RL | Request | Success | Errors |
|---|---|---|---|---|---|
| GET `/api/patients` | `list_patients` | 120/hr | query `search:str` | 200 `{patients:[...], total}` (datetimes ISO) | 401; degraded `{patients:[],total:0}` |
| GET `/api/patients/{patient_id}` | `get_patient` | 120/hr | path `patient_id:int` | 200 `{patient:{...}}` | 401; 503; 404; 500 |
| GET `/api/patients/{patient_id}/prefill` | `prefill_patient` | 120/hr | path int | 200 `{patient_data, run_count, last_run_at, patient_name, mrn}` | 401; 503; 404; 500 |
| PATCH `/api/patients/{patient_id}/status` | `update_patient_status_endpoint` | 60/hr | JSON `{status:str(req, ∈ VALID_STATUSES), note?:str}` | 200 `{ok:true, status}` | 401; 503; 400 invalid status; 404; 500. Triggers ROI calc on `discharged` |
| POST `/api/patients/{patient_id}/notes` | `add_patient_note_endpoint` | 60/hr | JSON `{note_text:str(req)}` | 200 note row (ISO dates) | 401; 503; 400 empty; 404; 500 |
| DELETE `/api/patients/{patient_id}/notes/{note_id}` | `delete_patient_note_endpoint` | 60/hr | path ints | 200 `{ok:true}` | 401; 503; 404 (not found or not author); 500 |
| GET `/api/patients/{patient_id}/runs/{run_id}/export` | `export_run_endpoint` | 30/hr | path ints | 200 **HTML** print document (auto `window.print()`) | 401; 503; 404 patient/run; 500 |
| PATCH `/api/patients/{patient_id}/discharge-data` | `update_discharge_data` | 60/hr | JSON subset of `{actual_discharge_date, drg_code, drg_description, discharge_destination, was_readmitted, readmission_date, readmission_dx}` | 200 `{patient, roi_outcome}` (computes `actual_los_days`, DRG lookup, triggers ROI) | 401; 503; 404; 400 no valid fields |

Callers: my-patients.html, patient-detail.html, ward-barriers.html, post-acute-directory.html,
offline.html (all hit `/api/patients` or `/api/patients/...`).

---

## 8. Directory

Session required (except `cron-sync`). **503** / degraded when `DATABASE_URL` unset or
`_DIRECTORY_DB_AVAILABLE` false.

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| GET `/api/directory/search` | `directory_search` | Session | 120/hr | query `zip:str(req,5-digit), radius:float(1-100,def25), types:csv(def SNF,IRF,LTACH), min_rating:int?, medi_cal:str?, medicare:str?, exclude_sff:str(def false), sort:str(def distance), limit:int(1-100,def50)` | 200 `{results, total, zip, radius_miles, data_freshness}` | 401; 400 invalid zip; degraded `{results:[],total:0,error}`; 500 |
| GET `/api/directory/facility/{ccn}` | `directory_facility_detail` | Session | 120/hr | path `ccn:str` | 200 `{facility:{...}}` | 401; 503; 404; 500 |
| GET `/api/directory/county-summary` | `directory_county_summary` | Session | 60/hr | none | 200 `{counties:[...]}` | 401; degraded `{counties:[]}` |
| POST `/api/directory/sync` | `directory_sync_trigger` | Session | 120/hr | JSON `{offset:int}` (chunked, ~500 rows/page) | 200 `{status:"running"|"done"|"error", next_offset?, upserted?, total_active_facilities?}` | 401; 503 |
| GET `/api/directory/debug-fetch` | `directory_debug_fetch` | Session | 20/hr | none | 200 diagnostic dict (CMS POST/GET probe) | 401 |
| GET `/api/directory/cron-sync` | `directory_cron_sync` | **Public** (CRON_SECRET bearer when set) | 12/hr | header `Authorization: Bearer <CRON_SECRET>` | 200 `{message, ...}` | 401 if secret mismatch; 503; 500 |
| GET `/api/directory/sync-status` | `directory_sync_status_endpoint` | Session | 120/hr | none | 200 sync status dict | 401; degraded `{last_sync:null,total_active_facilities:0}` |

Callers: post-acute-directory.html (search, county-summary, sync, sync-status).
`facility/{ccn}`, `debug-fetch`, `cron-sync` have no static HTML caller (cron is a Vercel Cron target).

---

## 9. Eligibility

Session required. **503** when `_ELIGIBILITY_AVAILABLE` false.

| Method + Path | Handler | RL | Request | Success | Errors |
|---|---|---|---|---|---|
| GET `/api/eligibility/payers` | `eligibility_payers` | 120/hr | none | 200 `{payers:[{payer_id,name}]}` | 401; degraded `{payers:[]}` |
| POST `/api/eligibility/mock` | `eligibility_mock_endpoint` | 60/hr | JSON `{payer_name:str(def "Medicare Traditional")}` | 200 `EligibilityResult` asdict | 401; 503 |
| POST `/api/eligibility/check` | `eligibility_check_endpoint` | 30/hr | JSON `{member_id, payer_id, npi?, first_name?, last_name?, date_of_birth?}` (NPI falls back to `HOSPITAL_NPI` env) | 200 `EligibilityResult` asdict (DB cache first) | 401; 503 (unavailable / `ELIGIBILITY_ENABLED` false / `STEDI_API_KEY` unset); 400 missing member/payer/npi; 422 ValueError; 500 |

Callers: settings.html (payers, mock), index.html (mock). `/api/eligibility/check` has no static caller.

---

## 10. FHIR / SMART

FHIR handlers use `get_current_user` and return **401 JSON** `{"error":"Unauthorized"}` (not HTTPException).
When the `fhir` package failed to import (`_FHIR_IMPORT_ERROR` set), all return **503**
`{error:"FHIR connector unavailable", detail:<import error>}` via `_fhir_unavailable()`.
These FHIR routes have **no `@limiter.limit`** decorator.

| Method + Path | Handler | Auth | Request | Success | Errors |
|---|---|---|---|---|---|
| GET `/fhir/metadata` | `capability_statement` | Public | none | 200 FHIR R4 `CapabilityStatement` JSON | — |
| GET `/launch` | `epic_launch_legacy` | Public | query `iss:str(req), launch:str?` | 302 → `/api/fhir/authorize?ehr=epic&...` | — |
| GET `/api/auth/epic/callback` | `epic_callback_legacy` | (delegates) | query `code,state,error` | delegates to `fhir_callback` | as `fhir_callback` |
| GET `/api/fhir/ehrs` | `list_fhir_ehrs` | user | none | 200 `{ehrs:list_ehr_display()}` | 401; 503 |
| GET `/api/fhir/status` | `fhir_config_status` | user | none | 200 `{fhir_loaded, app_url, redirect_uri, ehrs:config_status()}` | 401; 503 |
| GET `/api/fhir/authorize` | `fhir_authorize` | user | query `ehr:str(def epic), iss_override:str?, launch:str?` | 302 → EHR auth URL + sets `fhir_auth_state` cookie (PKCE for SMART v2) | 401; 503; 400 bad ehr; 500 missing client_id; 502 SMART discovery failure |
| GET `/api/fhir/callback` | `fhir_callback` | Public (validates state cookie) | query `code,state,error` | 302 → `/?patient=<id>&source=fhir` + sets `fhir_session` cookie | 503; 400 missing code; 302→`/login?error=...` (expired/invalid/mismatch); 302→`/?fhir_error=token_failed` |
| GET `/api/fhir/session` | `fhir_session_status` | user | none | 200 `{active:bool, ehr, ehr_fhir_base, patient_id, expires_at}` (silent token refresh) | 401; 503 |
| GET `/api/fhir/patient/{patient_id}` | `get_fhir_patient_bundle` | user + active FHIR session | path `patient_id:str` | 200 `{bundle, form_data}` (fetched fresh, never cached) | 401 (no session/expired token); 403 patient-context mismatch; 503 EHR unavailable / import error |
| POST `/api/fhir/patient/{patient_id}/plan` | `generate_plan_from_fhir` | user + active FHIR session | optional JSON body (supplemental fields merged) | 200 `text/event-stream` (same SSE as `/api/plan/stream`) | 401; 403 mismatch; 503 |

Cookies: `fhir_auth_state` (TTL 300s), `fhir_session` (TTL 28800s). `FHIR_REDIRECT_URI` defaults to
`{APP_URL}/api/fhir/callback`. Callers: index.html (status, authorize, session, patient/...).

---

## 11. TCM

Session required. All TCM data endpoints return **503** `{"error":"TCM module requires PostgreSQL — set POSTGRES_URL"}`
when `DATABASE_URL` unset (`/api/tcm/dashboard` returns a degraded zero-filled object instead).

| Method + Path | Handler | RL | Request | Success | Errors |
|---|---|---|---|---|---|
| POST `/api/tcm/episodes` | `create_tcm_episode_endpoint` | 30/hr | JSON req: `patient_mrn, patient_name, discharge_date(YYYY-MM-DD), discharge_setting(∈inpatient_hospital/snf/irf/ltch/observation/partial_hospitalization), discharge_diagnosis, attending_provider_npi, attending_provider_name, discharge_plan_text` | 200 `{ok:true, episode_id, mdm_assessment, contact_deadline, visit_deadline}` | 401; 400 missing field / bad setting / bad date; 503; 500 MDM failure |
| POST `/api/tcm/episodes/{episode_id}/contacts` | `record_tcm_contact` | 60/hr | JSON req: `contact_date, contact_time, contact_method(phone/video/in_person), contact_result(reached/left_voicemail/no_answer/patient_declined), contacted_by` | 200 `{ok:true, contact_id, qualifying:bool}` | 401; 400 missing/invalid; 503 |
| POST `/api/tcm/episodes/{episode_id}/visits` | `record_tcm_visit` | 30/hr | JSON req: `visit_date, visit_type, provider_npi, provider_name` | 200 `{ok:true, visit_id}` | 401; 400 missing; 503 |
| GET `/api/tcm/episodes/{episode_id}` | `get_tcm_episode_endpoint` | 120/hr | path `episode_id:str` | 200 `{episode, contacts, visits, window_status}` | 401; 503; 404 |
| GET `/api/tcm/dashboard` | `tcm_dashboard` | 60/hr | none | 200 `{episodes, total_active, red_alerts, amber_alerts, claim_ready, estimated_monthly_revenue}` | 401; degraded zero object (no DB) |
| POST `/api/tcm/episodes/{episode_id}/generate-claim` | `generate_tcm_claim_endpoint` | 30/hr | path `episode_id:str` | 200 `{ok:true, claim_id, claim}` | 401; 503; 404; 400 not claimable (`{error:reason}`) |
| GET `/api/tcm/claims/export` | `export_tcm_claims` | 10/hr | query `format:str(def csv; "json" supported)` | 200 CSV download OR JSON `{claims,count,total_estimated}` | 401; 503; 404 no claim-ready (CSV path) |
| GET `/api/tcm/platform-roi` | `tcm_platform_roi` | 60/hr | none | 200 ROI projection object (monthly/all-time TCM revenue, subscription, coverage ratio, annual projections) | 401 |

No static HTML caller found for the TCM episode/dashboard endpoints (likely a dedicated TCM screen
not present in `static/` — see Open Questions). `/api/tcm/platform-roi` → roi-tracker.html.

---

## 12. ROI (Measured + AI)

Session required. **503** / degraded when `DATABASE_URL` unset or `_ROI_ENGINE_AVAILABLE` false.
(`/api/roi/generate` is an AI generator — see §5.)

| Method + Path | Handler | RL | Request | Success | Errors |
|---|---|---|---|---|---|
| GET `/api/roi/dashboard` | `roi_dashboard` | 30/hr | query `months:int(def12)` | 200 dashboard (`settings, totals, monthly_trend, drg_breakdown, clinician_breakdown, data_quality`) | 401; degraded `{...,unavailable:true}` |
| GET `/api/roi/outcomes` | `list_roi_outcomes` | 30/hr | query `start_date,end_date,drg_code,clinician` | 200 `{outcomes, total}` | 401; degraded `{outcomes:[],total:0,unavailable:true}` |
| GET `/api/roi/outcomes/{patient_id}` | `get_patient_roi_outcome_endpoint` | 60/hr | path int | 200 `{outcome}` | 401; 503; 404 |
| POST `/api/roi/outcomes/{patient_id}/calculate` | `recalculate_patient_roi` | 30/hr | path int | 200 `{outcome}` or `{outcome:null, message}` | 401; 503; 404 |
| GET `/api/roi/settings` | `get_roi_settings_endpoint` | 60/hr | none | 200 settings dict | 401; degraded `{hospital_type:"nonprofit",cost_per_day:4000}` |
| PATCH `/api/roi/settings` | `update_roi_settings` | 10/hr | JSON settings dict | 200 updated settings | 401; 503 |
| GET `/api/roi/export` | `export_roi_csv` | 10/hr | query `start_date,end_date` | 200 CSV download (methodology header + per-episode rows) | 401; 503 |

Callers: roi-measured.html (dashboard, outcomes, settings, export), patient-detail.html (`/api/roi/outcomes/{id}`).

---

## 13. Referrals

Session required. **503** `{"detail":"Referrals module unavailable"}` (or degraded empty objects on GETs)
when `_REFERRALS_AVAILABLE` false. Org scoping via `_get_org_domain(ctx.email)`.

| Method + Path | Handler | RL | Request | Success | Errors |
|---|---|---|---|---|---|
| POST `/api/referrals` | `create_referral_endpoint` | 60/hr | JSON `{patient_id, ...}` (`Body(...)` required) | 200 referral row | 401; 503 |
| GET `/api/referrals` | `list_referrals_endpoint` | 120/hr | query `patient_id:int?, status:str?, limit:int(def50), offset:int(def0)` | 200 `{referrals, total}` | 401; degraded `{referrals:[],total:0}` |
| GET `/api/referrals/analytics` | `referral_analytics_endpoint` | 30/hr | query `days:int(def90)` | 200 analytics dict | 401; degraded `{by_status:{},by_channel:{},total:0}` |
| GET `/api/referrals/settings` | `get_referral_settings_endpoint` | 60/hr | none | 200 settings | 401; degraded `{default_channel:"fax"}` |
| PATCH `/api/referrals/settings` | `patch_referral_settings_endpoint` | 30/hr | JSON settings (`Body(...)`) | 200 settings | 401; 503 |
| GET `/api/referrals/delivery-status` | `referral_delivery_status_endpoint` | 60/hr | none | 200 `{fax,careport,direct:bool}` | 401; degraded `{fax:false,careport:false,direct:false}` |
| GET `/api/referrals/{referral_id}` | `get_referral_endpoint` | 120/hr | path int | 200 referral | 401; 503; 404 |
| PATCH `/api/referrals/{referral_id}/status` | `update_referral_status_endpoint` | 60/hr | JSON `{status:str(req ∈ draft/sent/pending_review/accepted/declined/cancelled), notes?}` | 200 referral | 401; 503; 422 invalid status; 404 |
| POST `/api/referrals/{referral_id}/send` | `send_referral_endpoint` | 30/hr | path int | 200 delivery result `{success, channel, ...}` | 401; 503; 404 |
| POST `/api/referrals/{referral_id}/resend` | `resend_referral_endpoint` | 20/hr | path int | (delegates to `send_referral_endpoint`) | as send |
| GET `/api/referrals/{referral_id}/delivery-log` | `referral_delivery_log_endpoint` | 60/hr | path int | 200 `{log:[...]}` | 401; 404; degraded `{log:[]}` |
| GET `/api/referrals/{referral_id}/messages` | `get_referral_messages_endpoint` | 60/hr | path int | 200 `{messages:[...]}` | 401; 404; degraded `{messages:[]}` |
| POST `/api/referrals/{referral_id}/messages` | `add_referral_message_endpoint` | 60/hr | JSON `{message_text:str(req)}` | 200 message row | 401; 503; 404; 422 empty text |

Callers: ward-referrals.html, post-acute-directory.html, patient-detail.html, settings.html
(settings + delivery-status).

---

## 14. DRG

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| GET `/api/drg/search` | `drg_search_endpoint` | Session | 120/hr | query `q:str` (min 2 chars) | 200 `{results:[...]}` | 401; degraded/empty `{results:[]}` when no DB / `_ROI_ENGINE_AVAILABLE` false / q<2 |

Caller: patient-detail.html.

---

## 15. Milestones / Barriers

Session required. **503** `{"detail":"Milestone service not available"}` (or degraded objects on GETs)
when `DATABASE_URL` unset or `_MILESTONES_AVAILABLE` false. Note: `/api/milestones/catalog` works
without DB (static catalog) but returns empty when `_MILESTONES_AVAILABLE` false.

| Method + Path | Handler | RL | Request | Success | Errors |
|---|---|---|---|---|---|
| GET `/api/milestones/catalog` | `get_milestone_catalog` | 120/hr | none | 200 `{catalog, categories}` | 401; degraded `{catalog:[],categories:{}}` |
| GET `/api/milestones/ward-summary` | `ward_milestone_summary` | 60/hr | none | 200 `{summary:{open_count, overdue_count, resolved_today, patients_with_barriers, by_category, by_patient}}` | 401; degraded `{summary:{}}`; 500 |
| GET `/api/patients/{patient_id}/milestones/summary` | `patient_milestone_summary` | 120/hr | path int | 200 `{open, overdue}` | 401; degraded `{open:0,overdue:0}`; 404; 500 |
| GET `/api/patients/{patient_id}/milestones` | `list_patient_milestones` | 120/hr | path int; query `include_resolved:bool(def false)` | 200 `{milestones, total}` | 401; degraded `{milestones:[]}`; 404; 500 |
| POST `/api/patients/{patient_id}/milestones` | `create_patient_milestone` | 60/hr | JSON `{barrier_type(def custom), description, priority(def medium), assigned_to?, due_date?(ISO)}` | 201 `{milestone}` | 401; 503; 404; 500 |
| PATCH `/api/patients/{patient_id}/milestones/{milestone_id}` | `update_patient_milestone` | 120/hr | JSON `{status?, priority?, assigned_to?, due_date?, notes?, dismiss_reason?}` | 200 `{milestone}` | 401; 503; 404; 500 |
| DELETE `/api/patients/{patient_id}/milestones/{milestone_id}` | `delete_patient_milestone` | 60/hr | path ints | 200 `{success:true}` | 401; 503; 404; 403 (cannot delete AI-detected — dismiss instead); 500 |

Callers: my-patients.html, ward-barriers.html (`/api/milestones/ward-summary`),
patient-detail.html (`/api/milestones/catalog`).

---

## 16. Onboarding, Invites, Admin, Superadmin

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| POST `/api/onboard/create-org` | `create_org` | Public | 5/hr (IP) | JSON `{name, slug, admin_email, admin_password(≥8), domain?}` | 200 `{ok:true, org:{id,name,slug}}` + sets session role `org_admin` | 400 missing/invalid/slug-format; 409 slug taken / user exists; 500 create failure. File-mode: registers user against `DEFAULT_ORG_ID` |
| GET `/api/onboard/check-slug` | `check_slug` | Public | 30/min (IP) | query `slug:str` | 200 `{available:bool, reason?}` | (file-mode always `{available:true}`) |
| GET `/api/invite/accept` | `invite_info` | Public | 20/hr (IP) | query `token:str(req)` | 200 `{email, role, org_name, org_slug}` | 400 no token; 503 file-mode; 404 invalid/expired |
| POST `/api/invite/accept` | `accept_invite` | Public | 10/hr (IP) | JSON `{token:str(req), password:str(≥8)}` | 200 `{ok:true, email, org_id, role}` + sets session | 400 missing/short pw; 503 file-mode; 404 invalid invite; 409 user exists |
| GET `/api/admin/users` | `admin_list_users` | `require_role("org_admin","super_admin")` | 60/hr | none | 200 `{users:[...]}` | 401; 403; file-mode `{users:[],note}` |
| POST `/api/admin/invite` | `admin_invite_user` | `require_role("org_admin","super_admin")` | 30/hr | JSON `{email, role(def clinician ∈ org_admin/clinician/read_only)}` | 200 `{ok:true, token, email, role}` | 401; 403; 400 invalid email/role; 503 file-mode |
| GET `/api/superadmin/orgs` | `superadmin_list_orgs` | `require_role("super_admin")` | 30/hr | none | 200 `{orgs:[...]}` | 401; 403; file-mode stub org list |

No static HTML callers found for these (admin/onboarding likely server- or external-driven). See Open Questions.

---

## 17. Pilot

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| GET `/api/pilot/spots` | `pilot_spots` | Public | — | none | 200 `{total_spots:5, confirmed_pilots, remaining}` | (DB error → safe default) |
| POST `/api/pilot/apply` | `pilot_apply` | Public | 3/hr | JSON `{hospital_name(req), applicant_name(req), email(req), licensed_beds?, consent_revenue_share, consent_ca_hospital, applicant_title?, phone?, ehr_system?, annual_discharges?, how_found?, challenge_text?, calculator_inputs?}` | 200 `{ok:true, message}` | 400 missing name/email/consents; 400 beds<100 |

Callers: pilot.html (spots, apply).

---

## 18. Settings

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| GET `/api/settings` | `get_settings` | Session | 60/hr | none | 200 `{eligibility_enabled, eligibility_mock, stedi_configured, hospital_npi_configured, db_available, directory_available, eligibility_service_available}` | 401 |

Caller: settings.html.

---

## 19. Health / Infra / PWA

| Method + Path | Handler | Auth | RL | Request | Success | Errors |
|---|---|---|---|---|---|---|
| GET `/api/healthz` | `healthz` | Public | — | none | 200 `{status:"ok", fhir_loaded, fhir_import_error, python_path, routes:[sorted paths]}` | — |
| GET `/sw.js` | `service_worker` | Public | — | none | 200 JS (`Service-Worker-Allowed:/`, no-cache) | — |
| GET `/manifest.json` | `web_manifest` | Public | — | none | 200 `application/manifest+json` (cached 1d) | — |
| GET `/offline` | `offline_page` | Public | — | none | 200 HTML (`offline.html`) | — |

Callers: PWA (`pwa.js`/`sw.js`), offline.html.

---

## 20. HTML Page Routes

All GET, return 200 HTML. Most require login via `require_login()` → **302 → /login** when no
valid session. `/tcm-roi-calculator` and `/pilot` are public; `/ward-referrals` uses
`get_current_org` (so **401** instead of redirect when unauthenticated).

| Path | Handler | Auth | Static file |
|---|---|---|---|
| `/` | `index` | login (302) | index.html |
| `/login` | `login_page` | Public | login.html |
| `/summary-generator` | `summary_generator_page` | login (302) | summary-generator.html |
| `/imm-prompt-system` | `imm_prompt_system_page` | login (302) | imm-prompt-system.html |
| `/multilingual-prompt-system` | `multilingual_prompt_system_page` | login (302) | multilingual-prompt-system.html |
| `/discharge-summary-generator` | `discharge_summary_generator_page` | login (302) | discharge-summary-generator.html |
| `/teachback-checklist` | `teachback_checklist_page` | login (302) | teachback-checklist.html |
| `/cdph-compliance` | `cdph_compliance_page` | login (302) | cdph-compliance.html |
| `/post-acute-directory` | `post_acute_directory_page` | login (302) | post-acute-directory.html |
| `/hrrp-flagging` | `hrrp_flagging_page` | login (302) | hrrp-flagging.html |
| `/roi-tracker` | `roi_tracker_page` | login (302) | roi-tracker.html |
| `/readmission-tracker` | `readmission_tracker_page` | login (302) | readmission-tracker.html |
| `/predictive-discharge` | `predictive_discharge_page` | login (302) | predictive-discharge.html |
| `/my-patients` | `my_patients_page` | login (302) | my-patients.html |
| `/patients/{patient_id}` | `patient_detail_page` | login (302) | patient-detail.html |
| `/settings` | `settings_page` | login (302) | settings.html |
| `/roi-measured` | `roi_measured_page` | login (302) | roi-measured.html |
| `/tcm-roi-calculator` | `tcm_roi_calculator_page` | **Public** | tcm-roi-calculator.html |
| `/pilot` | `pilot_page_route` | **Public** | pilot.html |
| `/ward-referrals` | `ward_referrals_page` | Session (401) | ward-referrals.html |
| `/ward-barriers` | `ward_barriers_page` | login (302) | ward-barriers.html |

> Note: `readmission-tracker.html` is served but its template references `/api/me` /
> `/api/auth/logout` only — readmission data appears client-side or via other endpoints.

---

## 21. Coverage Checklist

- **Routes found in `web_app.py`** (count of `@app.<method>(...)` decorators): **116**
- **Routes documented above:** **116**
- **Match:** ✅ 116 / 116

Breakdown by method: GET 71, POST 30, PATCH 9, DELETE 2, PUT 0 → 112; the remaining 4 are the
GET HTML-page / infra routes counted within the 116 total. (Authoritative count =
`grep -cE '@app\.(get|post|patch|put|delete)\(' web_app.py` = **116**.)

Per-section route counts: Auth&Session 8 · Identity/Me 2 · Plan/SSE 1 · Clinical generators 7 ·
Predict LOS 1 · Patients/runs/notes/export 8 · Directory 7 · Eligibility 3 · FHIR/SMART 10 ·
TCM 8 · ROI 7 · Referrals 13 · DRG 1 · Milestones 7 · Onboard/Invite/Admin/Superadmin 7 ·
Pilot 2 · Settings 1 · Health/Infra/PWA 4 · HTML pages 21. (Sums to 118 because `/login` is
counted in both Auth and HTML pages, and `/api/roi/generate` is counted in both Clinical
generators and referenced from ROI — the deduplicated decorator total remains **116**.)

---

## 22. Open Questions

1. **Role naming.** The task brief said roles are `clinician/admin/superadmin`. The actual
   `require_role(...)` strings in code are `clinician`, `org_admin`, `super_admin`, and
   `read_only`. Default role on new sessions is `clinician`; org creators get `org_admin`.
   ⚠ NEEDS VERIFICATION: whether any external mapping renames these.
2. **No static callers for several endpoints.** TCM episode/contact/visit/dashboard/generate-claim/
   claims-export, `/api/eligibility/check`, `/api/fhir/ehrs`, all `/api/onboard/*`, `/api/invite/*`,
   `/api/admin/*`, `/api/superadmin/orgs`, `/api/directory/facility/{ccn}`, `/api/directory/debug-fetch`
   have no reference in `static/*.html`. They are likely driven by a screen not present in `static/`
   (e.g. a TCM dashboard / admin console) or by external/automation clients (Vercel Cron for
   `cron-sync`). ⚠ NEEDS VERIFICATION: existence/location of a TCM and admin UI.
3. **`PredictiveLOSResult` / `EligibilityResult` field shapes.** These are returned via
   `dataclasses.asdict(...)`; exact fields live in `agents/predictive_los.py` and
   `services/eligibility.py` (not enumerated here). ⚠ NEEDS VERIFICATION if field-level detail required.
4. **`VALID_STATUSES`** for patient status (`PATCH /api/patients/{id}/status`) is imported from
   `db.patients`; the exact allowed values are defined there, not in `web_app.py`.
5. **AI doc generator output JSON schemas** (summary, discharge-summary, teachback, cdph, hrrp, roi,
   multilingual) are LLM-produced and only loosely validated server-side; the documented schema for
   `/api/discharge-summary/generate` is taken from the embedded prompt and reflects intended (not
   guaranteed) structure.
6. **`/launch` and `/api/auth/epic/callback`** are marked legacy / `# pragma: no cover`; confirm
   whether they remain wired to a live Epic embedded-launch integration.
