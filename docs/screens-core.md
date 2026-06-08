# Discharge Planning AI — Core Screen Documentation

> Source of truth: each screen's `static/<file>.html` (HTML + inline `<script>`) and the
> `web_app.py` routes it calls. Citations use the form `static/index.html → generatePlan()`
> for client handlers and `web_app.py → <fn>` for backend handlers.
>
> **PHI WARNING:** Many fields capture Protected Health Information (PHI). Each PHI field is
> flagged inline. All examples below are **synthetic** — never paste real patient data into docs.
>
> **Modes:** *FILE MODE* (`DATABASE_URL` unset → DB-backed features return 503 / empty payloads)
> vs *DB MODE* (Postgres connected). Each screen notes which mode it needs.

## Table of Contents

1. [Shared Component — Global Navigation Bar](#shared-component--global-navigation-bar)
2. [Screen: Sign In / Sign Up (`/login`)](#screen-sign-in--sign-up-login)
3. [Screen: Discharge Plan Builder (`/`)](#screen-discharge-plan-builder-)
4. [Screen: My Patients (`/my-patients`)](#screen-my-patients-my-patients)
5. [Screen: Patient Detail (`/patients/{id}`)](#screen-patient-detail-patientsid)
6. [Screen: Predictive Discharge Date (`/predictive-discharge`)](#screen-predictive-discharge-date-predictive-discharge)
7. [Screen: Post-Acute Provider Directory (`/post-acute-directory`)](#screen-post-acute-provider-directory-post-acute-directory)
8. [Screen: Settings (`/settings`)](#screen-settings-settings)
9. [Screen: Run Export Printable (`/api/patients/{id}/runs/{run_id}/export`)](#screen-run-export-printable-apipatientsidrunsrun_idexport)
10. [Auxiliary Screens](#auxiliary-screens)
    - [Ward Barriers (`/ward-barriers`)](#aux-ward-barriers-ward-barriers)
    - [Ward Referrals (`/ward-referrals`)](#aux-ward-referrals-ward-referrals)
    - [ROI Measured (`/roi-measured`)](#aux-roi-measured-roi-measured)
    - [Pilot (`/pilot`)](#aux-pilot-pilot)
    - [TCM ROI Calculator (`/tcm-roi-calculator`)](#aux-tcm-roi-calculator-tcm-roi-calculator)
    - [Offline (`/offline`)](#aux-offline-offline)
11. [Open Questions / NEEDS VERIFICATION](#open-questions--needs-verification)

---

## Shared Component — Global Navigation Bar

A `<header>` element is rendered at the top of every authenticated tool page. It is **not** a single
shared file — each page hard-codes its own `<header>` markup, so the link set varies slightly per page
(see each screen's "Entry points" / clickable table). The pages share styling and two cross-cutting
behaviors injected via `static/mobile.css` and `static/report-export.js`.

### Common link set (union across pages)
Links seen across `index.html`, `my-patients.html`, `patient-detail.html`, `predictive-discharge.html`,
`post-acute-directory.html`, `settings.html`, `ward-barriers.html`, `ward-referrals.html`:

| Label | Route |
| --- | --- |
| Home / Planner | `/` |
| My Patients | `/my-patients` |
| Predict LOS | `/predictive-discharge` |
| Summary Tool / Summary | `/discharge-summary-generator` |
| Teach-back | `/teachback-checklist` |
| CDPH | `/cdph-compliance` |
| HRRP | `/hrrp-flagging` |
| ROI Estimates | `/roi-tracker` |
| ROI Measured ★ (gold) | `/roi-measured` |
| Tracker | `/readmission-tracker` |
| Prompts | `/summary-generator` |
| IMM | `/imm-prompt-system` |
| Multilingual | `/multilingual-prompt-system` |
| Facilities / Directory | `/post-acute-directory` |
| Barriers (with overdue badge) | `/ward-barriers` |
| Referrals | `/ward-referrals` |
| Settings | `/settings` |
| TCM Calculator (`target="_blank"`) | `/tcm-roi-calculator` |
| Sign Out | `/api/auth/logout` |

- **Sign Out** is a plain `<a href="/api/auth/logout">`. Backend `web_app.py → logout` (302 redirect to
  `/login`, deletes the `dp_session` cookie).
- **Barriers overdue badge** (`#nav-overdue-badge`): hidden by default. On pages that include it
  (`my-patients.html → loadWardOverdueBadge()`, etc.) a call to `/api/milestones/ward-summary`
  populates `summary.overdue_count`; the red pill shows only when `> 0`.

### Bold clinician-review disclaimer banner (every header page)
- Rendered purely in CSS by `static/mobile.css` via the `header::after` pseudo-element (lines 236–251).
  Content string: **"Multi-Agent Clinical Decision Support · All outputs require clinician review before
  action"**, full-width, bold, bordered top, centered, below the nav links.
- Pages **without** a standard `<header>` (`/login`, `/offline`) render the same disclaimer as a literal
  blue `<div>` banner at the very top of `<body>` instead.
- `mobile.css` also reflows the header: `.spacer` becomes a full-width zero-height flex break so nav links
  wrap onto their own centered row; on phones `nav`/`.nav` collapses to a horizontal scroll strip.

### Report-export buttons (`static/report-export.js` → `window.ReportExport`)
Loaded as a plain script (before any Babel block) on tool pages that export an on-screen report
(e.g. `index.html`, `predictive-discharge.html`, and `roi-measured.html` via its own print path).
Public API:

| Function | Purpose |
| --- | --- |
| `ReportExport.buildDoc(opts)` | Build a clean self-contained HTML string from `{title, subtitle, accent, bodyHtml, disclaimer, print}`. |
| `ReportExport.capture(node, opts)` | Clone an on-screen DOM node, strip interactive controls + `[data-export-skip]`/`.no-print`, inline page `<style>`/font links, return printable HTML. |
| `ReportExport.download(filename, html)` | Save the HTML as a Blob download. |
| `ReportExport.print(html)` | Open a new window and write the HTML (auto-prints if `print:true`; alerts if pop-up blocked). |
| `ReportExport.dateStamp()` | `YYYY-MM-DD` for filenames. |
| Helpers | `esc`, `table(rows)`, `section(title,inner)`, `box(label,value)`, `list(items)`. |

Default disclaimer baked into exports: *"AI-assisted decision support — estimates and drafts only.
Verify all content and confirm clinical actions with the care team before use."*

### Auth / session primitives (shared by all routes)
- Session cookie `dp_session` (signed; `web_app.py` constants `COOKIE_NAME`, `DEFAULT_ORG_ID`).
- HTML page routes call `web_app.py → require_login(request)` → 302 to `/login` when no valid session.
- API routes depend on `web_app.py → get_current_org` → raises **401** when the cookie is missing/invalid;
  client JS typically redirects to `/login` on a 401.
- In FILE MODE, `org_id` defaults to `DEFAULT_ORG_ID` so the app runs without a DB.

---

## Screen: Sign In / Sign Up (`/login`)

- **File:** `static/login.html` — served by `web_app.py → login_page`.
- **Purpose:** Authenticate an existing user or self-register, then redirect to the planner (`/`).
  Optionally offers organization SSO when Auth0 is configured.
- **Access & preconditions:** Public (no session required). Available in both modes.
- **Entry points:** `require_login` redirects here from any protected page; `web_app.py → logout`
  redirects here after sign-out; SSO errors redirect to `/login?error=...`.
- **Layout overview (top→bottom):**
  1. Blue full-width disclaimer banner (literal `<div>`, not `header::after`).
  2. Brand card (🏥, "Discharge Planning AI", "Clinical Decision Support System").
  3. Two tabs: **Sign In** / **Create Account** (`switchTab`).
  4. Active form panel (login or signup) with inline message bar.
  5. SSO card (`#sso-section`) — hidden unless SSO enabled.
  6. Footer: "Authorized personnel only. All patient data is protected under HIPAA."

### Sections / fields

**Sign In panel (`#panel-login`)**
| Label | Input | Required | Validation | Sample | PHI? |
| --- | --- | --- | --- | --- | --- |
| Email Address | `email` (`#login-email`) | Yes | client: HTML `required` (form is `novalidate`); server: must contain `@` + a dotted domain | `clinician@example-hospital.org` | No (user credential) |
| Password | `password` (`#login-password`) | Yes | server-checked on submit | (hidden) | No (credential) |

**Sign Up panel (`#panel-signup`)**
| Label | Input | Required | Validation | Sample | PHI? |
| --- | --- | --- | --- | --- | --- |
| Email Address | `email` (`#signup-email`) | Yes | `@` + dotted domain; `ALLOWED_EMAILS` allow-list if configured | `newuser@example-hospital.org` | No |
| Password | `password` (`#signup-password`) | Yes | client + server: **min 8 chars** (hint: "Minimum 8 characters") | (hidden) | No |
| Confirm Password | `password` (`#signup-confirm`) | Yes | client: must equal Password (adds `.invalid` class on mismatch) | (hidden) | No |

**SSO card (`#sso-section`)** — conditional, shown only when `/api/auth/sso/config` returns `{enabled:true}`.
Contains a single **"Sign in with SSO"** link → `/auth/sso/login`.

### Clickable elements
| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
| --- | --- | --- | --- | --- | --- | --- |
| Sign In tab | button | `switchTab('login')` | Show login panel; clear both message bars | — | Login panel active | n/a |
| Create Account tab | button | `switchTab('signup')` | Show signup panel; clear messages | — | Signup panel active | n/a |
| Sign In submit | submit button | `login-form` submit listener (addEventListener) | Collect email/password, POST login | `web_app.py → do_login` (`POST /api/auth/login`) | On `res.ok` → `location='/'`; else show error | Button disabled, text "Signing in..." during request |
| Create Account submit | submit button | `signup-form` submit listener | Validate min-8 + match, POST signup | `web_app.py → do_signup` (`POST /api/auth/signup`) | On `res.ok` → `location='/'`; else show error | Button disabled, text "Creating account..." |
| Sign in with SSO | link | (none — plain `<a>`) | Begin Auth0 OIDC flow | `web_app.py → sso_login` (`/auth/sso/login`) | 302 to Auth0 authorize URL | n/a |

### Functions (client-side)
- **`switchTab(mode)`** — trigger: tab clicks. Toggles `.active` on `tab-*`/`panel-*`; resets message bars to hidden/error class.
- **`showMsg(id, text, type)`** — sets a message bar's text + class (`msg error`/`msg success`) and shows it.
- **login submit listener** — `e.preventDefault()`; trims email; disables button; POSTs JSON `{email,password}`;
  parses JSON (tolerant of empty body); on success navigates to `/`; on failure shows `data.error` or
  `Server error (status)`; network failure → "Could not reach the server."
- **signup submit listener** — client guards: password `< 8` → error; mismatch → error + `.invalid`.
  Then POSTs `{email,password}`; same success/failure handling as login.
- **SSO config probe** — on load, `fetch('/api/auth/sso/config')`; if `d.enabled`, reveals `#sso-section`. Failure is swallowed.

### API interactions
- `GET /api/auth/sso/config` → `{enabled: bool}` (`web_app.py → sso_config`, reflects Auth0 env config).
- `POST /api/auth/login` body `{email,password}` → `200 {ok:true}` + sets `dp_session`; errors: **400** invalid
  email, **401** bad credentials (`data.error`), **403** not authorized (allow-list), **429** lockout.
- `POST /api/auth/signup` body `{email,password}` → `200 {ok:true}` + session; errors: **400** invalid email /
  short password, **403** not on allow-list, **409** already registered.

### States & feedback
- **Loading:** submit buttons disabled with progress label.
- **Success:** immediate redirect to `/` (no success bar shown on login/signup; `msg.success` class exists but
  the happy path navigates away).
- **Error:** red message bar with server `error` text or fallback.
- **Lockout:** `web_app.py → do_login` enforces in-memory thresholds `LOCKOUT_THRESHOLDS = {5:60s, 10:300s,
  20:1800s, 50:86400s}` keyed by email; returns **429** `"Account temporarily locked. Try again in <duration>."`
  with `Retry-After`. Rate limits: login `5/minute`, signup `3/minute` (per IP).

### End-user walkthrough
1. Open `/login`. The Sign In tab is active by default.
2. Enter email + password → **Sign In**.
3. On success you land on the Discharge Plan Builder (`/`).
4. New user: click **Create Account**, enter email + 8+ char password twice → **Create Account** → redirected to `/`.
5. If your org uses SSO, click **Sign in with SSO** instead.

### Edge cases & notes
- Form is `novalidate`; the browser does not block submit — validation is JS + server side.
- `ALLOWED_EMAILS` (env) is an optional registration/login allow-list; absence means anyone may register.
- Lockout state is **in-process memory** — not shared across serverless instances or restarts. ⚠ NEEDS VERIFICATION:
  effective lockout behavior on multi-instance/serverless deploys.

---

## Screen: Discharge Plan Builder (`/`)

- **File:** `static/index.html` — served by `web_app.py → index` (after `require_login`).
- **Purpose:** Collect a full patient intake across a 7-step wizard and stream a multi-agent AI discharge
  plan, with optional EHR import, eligibility pre-check, ML LOS banner, and (DB MODE) auto-save to the patient record.
- **Access & preconditions:** Login required (302 to `/login`). Plan generation requires `ANTHROPIC_API_KEY`
  on the server. Patient persistence, TCM, and barrier extraction require DB MODE. Eligibility pre-check
  requires eligibility env config.
- **Entry points:** Post-login landing; "← Planner"/"Home"/"+ New Patient" links from other pages;
  "Continue" from My Patients (via `sessionStorage.prefill_patient`); FHIR OAuth return (`/?source=fhir`).
- **Layout overview (top→bottom):**
  1. Global header (planner-specific link set + Sign Out).
  2. "⚡ Load Sample Patient" row.
  3. Tab bar: steps 1–7 (`goTab`).
  4. Form card containing the EHR import panel + the active step panel.
  5. LOS banner, eligibility banner, barriers banner (all hidden until their SSE events).
  6. Progress panel (agent status cards) — shown during generation.
  7. Report panel (rendered Markdown plan + actions + DRAFT alert).

### Sections / fields (every field)

> All patient-identifying fields below are **PHI**. Collected client-side by `collectFormData()` and POSTed to
> `/api/plan/stream`.

**Step 1 — Demographics (`#tab-0`)**
| Label | Input | Required | Validation | Sample | PHI? |
| --- | --- | --- | --- | --- | --- |
| Patient Name | text `#patient_name` | soft* | — | `Jane Doe` | **PHI** |
| MRN | text `#mrn` | soft (needed to save) | used as save key with admission date | `MRN-100200` | **PHI** |
| Age | number `#age` (0–130) | No | min/max attrs | `72` | **PHI** |
| Gender | select `#gender` | No | Male/Female/Other/Prefer not to say | `Female` | **PHI** |
| Admission Date | date `#admission_date` | soft (needed to save) | — | `2026-06-01` | **PHI** |
| Expected Discharge Date | date `#expected_discharge_date` | No | — | `2026-06-07` | **PHI** |
| Attending Physician | text `#attending_physician` | No | — | `Dr. Smith` | maybe |

\* "soft": `generatePlan()` requires **at least** a patient name **or** primary diagnosis before generating.

**Step 2 — Diagnoses (`#tab-1`)**
| Label | Input | Required | Sample | PHI? |
| --- | --- | --- | --- | --- |
| Primary Diagnosis | textarea `#primary_diagnosis` | soft | `Acute decompensated heart failure (HFrEF, EF 30%)` | **PHI** |
| Secondary Diagnoses | textarea `#secondary_diagnoses` (one per line) | No | `Type 2 DM` / `HTN` / `CKD Stage 3` | **PHI** |
| Additional Clinical Notes | textarea `#additional_clinical_notes` | No | progress notes, labs, course | **PHI** |

**Step 3 — Insurance (`#tab-2`)**
| Label | Input | Required | Sample | PHI? |
| --- | --- | --- | --- | --- |
| Patient First Name | text `#patient_first_name` | No (eligibility) | `Jane` | **PHI** |
| Patient Last Name | text `#patient_last_name` | No (eligibility) | `Doe` | **PHI** |
| Date of Birth | date `#date_of_birth` | No (eligibility) | `1953-04-10` | **PHI** |
| Insurance Member ID | text `#insurance_member_id` | No (eligibility) | `MBR-555` | **PHI** |
| Primary Insurance | text `#primary_insurance` | No | `Medicare Traditional` | maybe |
| Secondary Insurance | text `#secondary_insurance` | No | `Medigap Plan G` | maybe |
| Medicare Part A Active? | select `#medicare_part_a` | No (default `N/A`) | `Yes`/`No`/`N/A` | maybe |
| SNF Days Used This Benefit Period | number `#snf_days_used` (0–100, default 0) | No | `0` (hint: Medicare covers up to 100/period) | maybe |

Step 3 also has **Quick Eligibility Check** (`quickEligibilityCheck()`), a status `<span>`, and an inline result card `#eligibilityInlineCard`.

**Step 4 — Medications (`#tab-3`)** — three textareas, "Drug Name, Dose, Frequency" one per line, all **PHI**:
`#admission_medications` (home meds), `#inpatient_medications` (current inpatient), `#discharge_medications` (anticipated d/c meds).

**Step 5 — Therapy (`#tab-4`)** — three textareas (default value sent as "Not evaluated" when blank, set in `collectFormData()`):
`#pt_evaluation` (PT), `#ot_evaluation` (OT), `#st_evaluation` (ST). **PHI**.

**Step 6 — Social History (`#tab-5`)**
| Label | Input | Sample | PHI? |
| --- | --- | --- | --- |
| Living Situation | textarea `#living_situation` | `Lives with spouse, 2-story home` | **PHI** |
| Housing Type | select `#housing_type` | House/Apartment/Assisted Living/Nursing Home/Shelter/Homeless/Other | **PHI** |
| Bedroom Location | select `#bedroom_location` | First floor/Second floor/Other | **PHI** |
| Identified Caregiver | text `#caregiver` | `Daughter, 4 hrs/day` | **PHI** |
| Primary Language | text `#primary_language` (default `English`) | `Spanish` | **PHI** |
| Transportation | textarea `#transportation` | `Has car; daughter drives` | maybe |

**Step 7 — Goals (`#tab-6`)** — three textareas, all **PHI/sensitive**:
`#patient_family_preference`, `#physician_goals`, `#additional_notes`. Contains the green **🤖 Generate Discharge Plan** button + `#errorMsg`.

**Import-from-EHR panel (`#ehr-panel`)** — hidden unless an EHR is configured (`initEhrPanel`).
Fields: `#ehr-select` (configured EHR dropdown), **Connect** button, `#ehr-status` text; on connect a second
row reveals `#ehr-patient-id` (text "FHIR Patient ID") + **Load patient** button.

**Conditional/dynamic banners**
- `#losBanner` — ML predicted discharge date, predicted LOS, 80% CI, risk tier (from `los_prediction` SSE).
- `#eligibilityBanner` — payer/plan, deductible/OOP, SNF days, prior-auth, source badge (from `eligibility_result` SSE).
- `#barriersBanner` — count + top-3 barriers, "View All →" deep link (from `barriers_detected` SSE).
- `#prefill-banner` — injected when arriving via My Patients "Continue"; shows "Continuing plan for <name> · Run #N".
- Save-confirmation toast and `#warning-banner` — see SSE lifecycle.

### Clickable elements
| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
| --- | --- | --- | --- | --- | --- | --- |
| ⚡ Load Sample Patient | button | `loadSample()` | Fetch and populate all fields | `GET /api/sample-patient` (`web_app.py → get_sample_patient`) | Fields filled; jump to step 1 | alert on failure |
| Step tabs 1–7 | buttons | `goTab(n)` | Switch active step panel | — | Panel `n` shown | n/a |
| Next → / ← Back | buttons | `goTab(n±1)` | Navigate steps | — | — | n/a |
| Connect (EHR) | button | `connectEhr()` | Begin SMART-on-FHIR auth for selected EHR | `GET /api/fhir/authorize?ehr=...` (`web_app.py → fhir_authorize`) | Browser redirect to EHR auth | n/a |
| Load patient (EHR) | button | `loadFhirPatient(id)` | Fetch FHIR bundle, map to form | `GET /api/fhir/patient/{id}` (`web_app.py → get_fhir_patient_bundle`) | Form populated; status msg | inline status text |
| ⚡ Quick Eligibility Check | button | `quickEligibilityCheck()` | Mock eligibility for payer | `POST /api/eligibility/mock` (`web_app.py → eligibility_mock_endpoint`) | `#eligibilityInlineCard` shows result | button disabled, "Checking…" |
| 🤖 Generate Discharge Plan | button | `generatePlan()` | Stream multi-agent plan (SSE) | `POST /api/plan/stream` (`web_app.py → create_plan`) | Progress panel → report panel | disabled, "⏳ Generating…" |
| 📋 Copy | button | `copyReport()` | Copy raw Markdown to clipboard | — | alert "Report copied" | n/a |
| ⬇ Download HTML | button | `downloadPlanReport(false)` | Capture report → download HTML | — (`ReportExport.capture/download`) | File saved | n/a |
| 🖨️ Save as PDF | button | `downloadPlanReport(true)` | Capture report → print window | — (`ReportExport.print`) | Print dialog | pop-up-blocked alert |
| 🔄 New Patient | button | `resetForm()` | Clear all inputs + hide panels | — | Fresh form at step 1 | n/a |
| Sign Out + nav links | links | — | Navigate / logout | per link | — | n/a |
| `#prefill-banner` × | button | inline `this.parentElement.remove()` | Dismiss prefill banner | — | Banner removed | n/a |
| Save toast "View patient history →" | link | — | Open saved patient detail | — | Navigates to `/patients/{id}` | n/a |

### Functions (client-side)
- **`goTab(n)`** — toggles `.active` on tab buttons + panels; tracks `currentTab`.
- **`collectFormData()`** — reads/trims all 30+ fields; applies defaults (`snf_days_used`→`'0'`, PT/OT/ST→`'Not evaluated'`, language→`'English'`).
- **`loadSample()`** — `GET /api/sample-patient`; setter populates every field; `goTab(0)`; alert on error.
- **`generatePlan()`** — guard (name or diagnosis required → `#errorMsg`); disable button; show progress panel; reset all 7 agent statuses to "Waiting"; POST `collectFormData()` to `/api/plan/stream`; read the response body as a stream, split on `\n`, parse `data: {json}` lines, dispatch each to `handleEvent`. Network/non-OK → error text + re-enable button.
- **`handleEvent(event)`** — SSE dispatcher (see lifecycle).
- **`setStatus(agent,status,label)`** — recolors an agent status pill.
- **`renderLosBanner(p)`** — fills `#losBanner` (formatted date, `predicted_los_days`, p10–p90 CI, `risk_tier`).
- **`showReport(text)`** — stores raw text; `marked.parse()` into `#reportBody`; timestamp; show + scroll; re-enable button.
- **`renderEligibilityCard(e[,targetId])`** — color/icon by `is_eligible`; source badge (`live`/`mock`/`cached`); detail grid of payer/plan/deductible/OOP/SNF/prior-auth/notes.
- **`quickEligibilityCheck()`** — requires Member ID + Primary Insurance; POSTs `{payer_name}`; renders inline card.
- **`renderBarriersCard(event)`** — shows count + top-3 with priority dots; "View All →" → `/patients/{lastSavedId}`; hides when count 0.
- **`showSaveConfirmation(data)`** — green toast "✓ Plan saved · Run #N · View patient history →"; stores `window._lastSavedPatientId`.
- **`showWarningBanner(message)`** — yellow `#warning-banner` (e.g. "No MRN or admission date provided — this plan will not be saved").
- **`resetForm()`** — clears inputs/selects, resets defaults, hides panels, `goTab(0)`.
- **EHR:** `initEhrPanel()` (`GET /api/fhir/status` → list configured EHRs; `GET /api/fhir/session` → reveal patient row if active), `connectEhr()`, `loadFhirPatient(patientId)` (`GET /api/fhir/patient/{id}` → `form_data` mapping). Runs on load.
- **Prefill IIFE** — reads `sessionStorage.prefill_patient`, calls `populateForm()`, injects `#prefill-banner`.
- **FHIR-return IIFE** — if `?source=fhir`, cleans URL, resolves patient id from query or `/api/fhir/session`, calls `loadFhirPatient`.

### API interactions
- `GET /api/sample-patient` → synthetic patient dict (`sample_patient.SAMPLE_PATIENT_WEB`).
- `POST /api/plan/stream` (`text/event-stream`). Payload = `collectFormData()`. Server (`web_app.py → create_plan` →
  `stream_plan`) runs 6 specialist agents in parallel then the coordinator. **SSE event lifecycle** (`handleEvent`):
  - `patient_record` `{patient_id, run_id, mrn}` → green save toast (DB MODE only, requires MRN + admission date).
  - `warning` `{message}` → yellow banner (e.g. plan not saved).
  - `eligibility_result` → eligibility banner (pre-flight, when eligibility configured).
  - `agent_start` / `agent_complete` / `agent_error` (`agent` ∈ predictive_los, clinical, care_needs, insurance, medications, social) → status pills.
  - `los_prediction` → `#losBanner` (informational; does not count toward completion).
  - `coordinator_start` → coordinator pill "Synthesizing…".
  - `coordinator_complete` `{output}` → render report (Markdown) + re-enable button.
  - `barriers_detected` `{count, barriers[]}` → barriers banner (DB MODE + milestones available).
  - `tcm_episode_created` / `tcm_not_applicable` → emitted after coordinator in DB MODE; **no dedicated UI handler exists in `handleEvent`** (events are ignored client-side). ⚠ NEEDS VERIFICATION: intended UI for TCM events on this screen.
  - `error` `{message}` → `#errorMsg` + re-enable button.
- `POST /api/eligibility/mock` `{payer_name}` → mock eligibility dataclass.
- FHIR: `GET /api/fhir/status`, `GET /api/fhir/session`, `GET /api/fhir/authorize`, `GET /api/fhir/patient/{id}`.

### States & feedback
- **Loading:** generate button disabled "⏳ Generating…"; per-agent pulsing "Running…" pills.
- **Success:** report panel with rendered Markdown + persistent **"⚠️ DRAFT ONLY"** alert; save toast in DB MODE.
- **Error:** `#errorMsg` red text; `agent_error`/`error` events recolor pills + re-enable button.
- **Warning:** `#warning-banner` when no MRN/admission date (plan not persisted).
- **Empty/FILE MODE:** no `patient_record` event → a `warning` is emitted that the plan is not saved.

### End-user walkthrough
1. (Optional) Click **Load Sample Patient** to prefill, or import via the EHR panel.
2. Work through steps 1–7, entering at least a patient name or primary diagnosis.
3. (Optional, step 3) Run **Quick Eligibility Check**.
4. On step 7, click **Generate Discharge Plan** and watch agent cards complete.
5. Review the rendered plan; **Copy**, **Download HTML**, or **Save as PDF**.
6. In DB MODE, click the save toast's **View patient history →**, or **New Patient** to start over.

### Edge cases & notes
- Plan is **not saved** without both MRN and admission date (FILE MODE never saves).
- `ANTHROPIC_API_KEY` unset → first SSE event is `{type:error, message:"ANTHROPIC_API_KEY not set"}`.
- Rate limit: `POST /api/plan/stream` is `10/hour`.
- The report renders untrusted Markdown via `marked` (raw HTML in the model output is rendered). ⚠ Sanitization not evident in source — NEEDS VERIFICATION.

---

## Screen: My Patients (`/my-patients`)

- **File:** `static/my-patients.html` — served by `web_app.py → my_patients_page` (after `require_login`).
- **Purpose:** List/search the org's patients with status filtering and continue/view actions.
- **Access & preconditions:** Login required. **DB MODE** — in FILE MODE `GET /api/patients`
  (`web_app.py → list_patients`) returns `{patients:[], total:0}`, so the list is empty.
- **Entry points:** Header "My Patients" link from any page; "+ New Patient" returns to `/`.
- **Layout (top→bottom):** header → page header ("My Patients" + "+ New Patient") → toolbar (search + sort) →
  status tabs (All/Active/Pending/Discharged/Readmitted, each with count badge) → skeleton loader → patient list → empty state.

### Sections / fields
| Element | Input | Notes |
| --- | --- | --- |
| Search | text `#search-input` | placeholder "Search by name, MRN, or diagnosis…"; debounced 400ms → server search |
| Sort By | select `#sort-select` | `updated_at` (Last activity) / `admission_date` / `patient_name` — **client-side sort** |
| Status tabs | buttons `data-status` | all / active / pending_discharge / discharged / readmitted — **client-side filter** |

**Patient card** (per `renderCard`): status dot, name (or `Patient MRN: <mrn>` — **PHI**), status badge,
optional barrier badge (open/overdue), `MRN · Admitted · diagnosis (60-char trunc)` — **PHI**, run count + last activity/by.

### Clickable elements
| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
| --- | --- | --- | --- | --- | --- | --- |
| + New Patient / + Start new plan | links | — | Go to planner | — | `/` | n/a |
| Search box | input | `input` listener (debounced) | Server search | `GET /api/patients?search=` | List re-rendered | skeleton shown |
| Sort select | select | `change` listener | `applyFiltersAndSort()` | — | Client re-sort | n/a |
| Status tabs | buttons | `click` listener | Set `activeStatus`, re-filter | — | List filtered + counts | n/a |
| Continue | button | `continuePatient(id, event)` | Prefill planner from latest snapshot | `GET /api/patients/{id}/prefill` | Stores `sessionStorage.prefill_patient`, navigates to `/` | button disabled, "..." |
| View | link | — | Open detail | — | `/patients/{id}` | n/a |

### Functions (client-side)
- **`loadPatients(search)`** — shows skeleton; `GET /api/patients[?search]`; 401 → `/login`; honors `x-sw-offline` header (offline banner); stores `allPatients`; `applyFiltersAndSort()`; failure → red error text.
- **`applyFiltersAndSort()`** — filters by `activeStatus`, sorts by `sortKey` (name via `localeCompare`, else descending), renders, updates counts.
- **`updateCounts()`** — tallies status counts into the tab badges.
- **`renderCard(p)` / `renderList(patients)`** — build cards; prefetch first 10 for offline (`window.PwaUtils`); empty state when none.
- **`continuePatient(id,e)`** — `GET /api/patients/{id}/prefill`; save to `sessionStorage`; navigate to `/`; failure → re-enable + alert.
- **`timeAgo`, `statusBadge`** — formatting helpers.
- **`loadWardOverdueBadge()`** — `GET /api/milestones/ward-summary` → header Barriers overdue badge.

### API interactions
- `GET /api/patients[?search=]` → `{patients:[...], total}` (org-scoped via `get_org_domain`). FILE MODE → empty.
- `GET /api/patients/{id}/prefill` → `{patient_data, run_count, last_run_at, patient_name, mrn}`.
- `GET /api/milestones/ward-summary` → overdue badge.

### States & feedback
- **Loading:** shimmer skeleton cards.
- **Empty:** "📋 No patients found" + "+ Start new discharge plan".
- **Error:** red "Failed to load patients. Please refresh."
- **Offline:** yellow "Showing cached data — you are offline" banner when SW served cache.

### End-user walkthrough
1. Open **My Patients**; cards load for your org.
2. Filter by status tab and/or type in search; pick a sort order.
3. **Continue** to resume a plan in the builder, or **View** to open the patient detail.

### Edge cases & notes
- Search is server-side; status filter + sort are client-side over the loaded set.
- Counts reflect the currently loaded set (the full org list when not searching; the search result set when searching).

---

## Screen: Patient Detail (`/patients/{id}`)

- **File:** `static/patient-detail.html` — served by `web_app.py → patient_detail_page` (after `require_login`).
- **Purpose:** Single-patient workspace: discharge barriers, plan-run history with per-agent output, clinical
  notes, status changes + history, discharge-data capture, measured ROI, and referrals.
- **Access & preconditions:** Login required. **DB MODE** — `GET /api/patients/{id}`
  (`web_app.py → get_patient`) returns **503** in FILE MODE ("Database not available"); **404** if not in org.
- **Entry points:** "View" on My Patients; barrier deep links; save toast on the planner.
- **Layout (top→bottom):** header → patient header (back link, name/MRN/admission/dx, status select) →
  view tabs (Discharge Barriers / Plan Runs / 📋 Record Discharge / 📊 ROI Outcome / 📤 Referrals) →
  one of the panels below.

### Sections
- **Patient header:** name (or `MRN: <mrn>` — **PHI**), sub line MRN/admission/dx (**PHI**), `#status-select`
  (Active / Pending Discharge / Discharged / Readmitted) styled by status.
- **Plan Runs tab:** left sidebar = Plan History run list + Clinical Notes form/list + Status History;
  main panel = LOS card + per-agent tabs (Predict LOS, Clinical, Care Needs, Insurance, Medications, Social,
  Final Plan) + agent output + "🖨 Print / Export PDF".
- **Discharge Barriers tab (default):** toolbar (title + "+ Add Barrier") + barrier list (checkbox resolve,
  priority dot, description, category/assignee/due, AI vs Manual source, Resolve/Reopen + Delete).
- **Record Discharge tab:** Actual Discharge Date, Destination select, DRG code (typeahead → `/api/drg/search`),
  30-Day Readmission? (+date), live Outcome Preview, Save/Cancel.
- **ROI Outcome tab:** metric cards (days saved, cost impact, total value), episode details, methodology details, Recalculate.
- **Referrals tab:** per-patient referral cards + "+ New Referral" (directory) / "All Referrals →".

### Notes fields
| Field | Input | PHI? |
| --- | --- | --- |
| Clinical note | textarea `#note-input` | **PHI** (free clinical text) |
| Add Barrier — Type/Description/Priority/Assigned To/Due Date | `#b-type`/`#b-desc`/`#b-priority`/`#b-assigned`/`#b-due` | desc/assignee may be **PHI** |
| Discharge date / destination / DRG / readmission | discharge panel inputs | **PHI** |

### Clickable elements
| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state |
| --- | --- | --- | --- | --- | --- |
| View tabs (5) | buttons | `switchView(view)` | Show panel; lazy-load data | per-tab loaders | Panel swapped |
| Status select | select | `changeStatus(value)` | Prompt for note, PATCH status | `PATCH /api/patients/{id}/status` | Toast + reload (discharged also triggers ROI calc) |
| Run item | div | `selectRun(id)` | Show that run | — (from loaded patient) | Main panel updates |
| Agent tab | button | `showAgent(name)` | Show agent's `output_text` (or final plan) | — | Output text shown |
| 🖨 Print / Export PDF | link (`_blank`) | — | Open printable run | `GET /api/patients/{id}/runs/{run_id}/export` | New tab auto-prints |
| Add Note | button | `addNote()` | Create note | `POST /api/patients/{id}/notes` | Note prepended + toast |
| 🗑 (own note) | button | `deleteNote(id)` | Confirm + delete | `DELETE /api/patients/{id}/notes/{note_id}` | Note removed + toast |
| + Add Barrier | button | `openAddBarrier()` | Open modal | — | Modal open |
| Save (barrier) | button | `saveBarrier()` | Create barrier | `POST /api/patients/{id}/milestones` | Reload barriers + toast |
| Barrier checkbox / Resolve / Reopen | input/buttons | `toggleBarrier(id, bool)` | PATCH status | `PATCH /api/patients/{id}/milestones/{id}` | Reload + toast |
| Delete (barrier) | button | `deleteBarrier(id)` | Confirm + delete | `DELETE /api/patients/{id}/milestones/{id}` | Reload + toast |
| DRG typeahead | input | `drgSearch(q)`→`selectDrg(d)` | Search/select DRG | `GET /api/drg/search?q=` | Dropdown + info box |
| Save Discharge Data | button | `saveDischargeData()` | Save discharge fields | `PATCH /api/patients/{id}/discharge-data` | Msg; may auto-switch to ROI |
| Recalculate (ROI) | button | `recalcROI()` | Recompute outcome | `POST /api/roi/outcomes/{id}/calculate` | Outcome re-rendered |

### Functions (client-side)
- **`load()`** — parallel `GET /api/patients/{id}` + `GET /api/me`; 401 → `/login`; non-OK → "Patient not found";
  honors `x-sw-offline`; stores `patient`/`myEmail`; `render()`; prefetch for offline.
- **`render()` / `selectRun()` / `renderRun()` / `showAgent()`** — build header, run list, LOS card, agent tabs/output.
- **`renderNotes()`** — list notes; 🗑 shown only for notes whose `author_email === myEmail`.
- **`renderStatusHistory()`** — old→new status, who, when, optional note.
- **`changeStatus(newStatus)`** — `prompt()` optional note; PATCH; on success toast + `load()`; failure reverts select.
- **`addNote()` / `deleteNote(id)`** — POST/DELETE notes with confirm; toasts.
- **Barriers:** `loadCatalog()` (`/api/milestones/catalog`), `loadBarriers()` (`/api/patients/{id}/milestones`),
  `renderBarriers()` (open list + collapsible resolved), `updateBarrierBadge()`, `toggleBarrier`, `deleteBarrier`, `openAddBarrier`/`saveBarrier`.
- **Discharge:** `prefillDischargeForm()`, `drgSearch`/`selectDrg`/`showDrgInfo`, `toggleReadmitFields`,
  `updateOutcomePreview()` (computes actual LOS, days saved, $ at $4,100/day, HRRP note), `saveDischargeData()`.
- **ROI:** `loadRoiOutcome()` (`/api/roi/outcomes/{id}`; 404 → empty msg), `renderRoiOutcome()`, `recalcROI()`.
- **Referrals:** `loadPatientReferrals()` (`/api/referrals?patient_id={id}`) + status/channel/date formatters.
- **`init()`** — `load()` then `loadCatalog()` + `loadBarriers()`.

### API interactions
- `GET /api/patients/{id}` → `{patient:{... runs[], notes[], status_history[], discharge fields}}` (org-scoped).
- `GET /api/me` → `{email, org_id, role}` (used to gate note deletion).
- `PATCH /api/patients/{id}/status` `{status, note}` — `VALID_STATUSES` enforced server-side; discharged status
  fires async ROI outcome calculation.
- `POST /api/patients/{id}/notes` / `DELETE .../notes/{note_id}` (delete only by author).
- `GET /api/patients/{id}/milestones`, `POST`/`PATCH`/`DELETE` milestones; `GET /api/milestones/catalog`.
- `GET /api/drg/search`, `PATCH /api/patients/{id}/discharge-data`, `GET /api/roi/outcomes/{id}`, `POST /api/roi/outcomes/{id}/calculate`, `GET /api/referrals?patient_id=`.
- `GET /api/patients/{id}/runs/{run_id}/export` (printable; see dedicated screen).

### States & feedback
- **Loading:** "Loading…" placeholders per panel.
- **Success:** green toasts; ROI auto-switch after discharge save.
- **Error:** red inline messages / `alert()` with server text; **503** in FILE MODE.
- **Empty:** "No discharge barriers tracked…", "No plan runs yet.", "No outcome recorded.", "No referrals…".

### End-user walkthrough
1. Open a patient from My Patients.
2. Default **Discharge Barriers** tab: add/resolve/delete barriers.
3. **Plan Runs**: pick a run, browse agent tabs, **Print / Export PDF**.
4. Add clinical notes; change status (with optional note) — history updates.
5. **Record Discharge**: enter date + DRG; preview outcome; **Save** (calculates ROI).
6. **ROI Outcome** / **Referrals** tabs for measured value and post-acute sends.

### Edge cases & notes
- Note 🗑 appears only to the author; server also enforces author-only delete.
- `updateOutcomePreview()` uses a hard-coded `$4,100/day` (AHA 2024 CA) for the preview only; server recompute may differ.
- DRG geometric-mean LOS labeled "CMS FY 2026"; ⚠ NEEDS VERIFICATION of dataset currency.

---

## Screen: Predictive Discharge Date (`/predictive-discharge`)

- **File:** `static/predictive-discharge.html` — served by `web_app.py → predictive_discharge_page` (after `require_login`).
- **Purpose:** Standalone ML length-of-stay prediction with a discharge-window timeline, risk tier, and contributing factors.
- **Access & preconditions:** Login required. Works in both modes (no DB needed — prediction is computed by `agents.predictive_los`).
- **Entry points:** "Predict LOS" nav link; LOS banner context on the planner.
- **Layout (top→bottom):** header → hero ("Predictive Discharge Date", "Powered by Gradient Boosting · 50,000 CA admissions") →
  intake form card → Results (hidden until run): prediction-results card (metrics + timeline) and Top Factors card.

### Sections / fields (intake)
| Label | Input | Sample | PHI? |
| --- | --- | --- | --- |
| Patient Age | number `#age` (18–99) | `72` | **PHI** |
| Admission Date | date `#admission_date` (defaults to today) | `2026-06-08` | **PHI** |
| Primary Diagnosis / ICD-10 | text `#primary_diagnosis` | `I50.9 Congestive Heart Failure` | **PHI** |
| Primary Insurance | select `#primary_insurance` | Medicare/Medi-Cal/HMO/PPO/Other | maybe |
| Secondary Diagnoses | textarea `#secondary_diagnoses` (one/line) | `E11.9…` | **PHI** |
| Living Situation | text `#living_situation` | `Lives alone, apartment` | **PHI** |
| Caregiver Available | select `#caregiver` | Unknown/Yes/None | **PHI** |
| SNF Benefit Days Used | number `#snf_days_used` (0–100) | `0` | maybe |
| Patient / Family Preference | text `#patient_family_preference` | `Home with PT` | **PHI** |
| PT / OT / ST | selects `#pt_evaluation`/`#ot_evaluation`/`#st_evaluation` | Not evaluated/Ordered/Completed | maybe |

**Results card:** Predicted Discharge Date, Predicted LOS (+80% CI), Risk Tier badge, Earliest Possible (p10),
discharge-window timeline (admit/earliest/predicted/latest/today markers). **Top Factors card:** importance bars + decision-support disclaimer.

### Clickable elements
| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
| --- | --- | --- | --- | --- | --- | --- |
| 🔮 Predict Discharge Date | button | `runPrediction()` | Build payload, POST | `POST /api/predict/los` (`web_app.py → predict_los_endpoint`) | `renderResults()` + scroll | disabled; loading bar shown |
| ⚡ Load Sample Patient | button | `loadSample()` | Fill from sample | `GET /api/sample-patient` | Fields populated | alert on error |
| ⬇ Download HTML | button | `downloadLosReport(false)` | Capture results → download | — (`ReportExport`) | File saved | n/a |
| 🖨 Save as PDF | button | `downloadLosReport(true)` | Capture results → print | — | Print dialog | n/a |

### Functions (client-side)
- **`runPrediction()`** — disables button, shows loading bar; builds `{patient_data:{age, admission_date, primary_diagnosis,
  primary_insurance, secondary_diagnoses, living_situation, caregiver, snf_days_used, patient_family_preference,
  therapy_evaluations:{PT,OT,ST}}}`; POSTs; on `json.success` → `renderResults(prediction, admission_date)`; failure → alert; always re-enable.
- **`renderResults(p, admitIso)`** — fills metrics; risk-tier badge color by `p.risk_color`; tier description map
  (Short/Moderate/Extended/Complex); calls `renderTimeline`; builds factor bars + dynamic disclaimer (model source + MAE + CI).
- **`renderTimeline(admitIso,p)`** — positions earliest/predicted/latest/today markers proportionally between min/max dates.
- **`loadSample()`** — `GET /api/sample-patient`; maps fields (caregiver truthy→"Yes" else "None").
- **`fmtDate`, `daysBetween`** — helpers. On DOM load, admission date defaults to today.

### API interactions
- `POST /api/predict/los` body `{patient_data:{...}}` → `{success:true, prediction:{predicted_discharge_date,
  predicted_los_days, los_p10, los_p90, earliest_discharge_date, latest_discharge_date, risk_tier, risk_color,
  model_source, model_mae_days, top_factors:[{label,direction,importance}]}}` or `{success:false, error}` (500).

### States & feedback
- **Loading:** animated `#loadingBar`; button disabled.
- **Success:** Results section revealed + smooth scroll; Top Factors shown when present.
- **Error:** `alert('Prediction failed: ...')`.
- **Empty:** Results hidden until first run.

### End-user walkthrough
1. Open **Predict LOS**; admission date defaults to today.
2. Enter age, diagnosis, etc. (or **Load Sample Patient**).
3. Click **Predict Discharge Date**; review metrics, timeline, and factors.
4. **Download HTML** / **Save as PDF** to export.

### Edge cases & notes
- Disclaimer states the model is trained on **synthetic** CA admissions and is decision-support only.
- `model_source` may be `ml_model` or "Heuristic fallback" — affects the disclaimer wording.

---

## Screen: Post-Acute Provider Directory (`/post-acute-directory`)

- **File:** `static/post-acute-directory.html` — served by `web_app.py → post_acute_directory_page` (after `require_login`).
- **Purpose:** Search live CMS post-acute facilities (SNF/IRF/LTACH) near a ZIP, view ratings/details, add to plan,
  send referrals, view a county summary, and trigger/refresh the CMS data sync.
- **Access & preconditions:** Login required (page also does a client `GET /api/me` guard → `/login`). **DB MODE** —
  search/county/sync return errors or empty in FILE MODE (`web_app.py → directory_search` → `{error:"Directory database not available"}`).
- **Entry points:** "Facilities/Directory" nav link; "+ New Referral" from patient detail/referrals.
- **Layout (top→bottom):** header (with freshness badge) → search bar (ZIP + radius + Search) → filters panel →
  sync banner (conditional) → results header (count + County Summary + Refresh Data) → county table (hidden) →
  results list → toast → referral modal.

### Sections / fields
| Label | Input | Default | Notes |
| --- | --- | --- | --- |
| ZIP Code | text `#zipInput` (maxlength 5) | (from `sessionStorage`) | must be 5 digits |
| Radius | select `#radiusSelect` | 25 mi | 5/10/25/50/100 |
| Facility Types | select `#typesSelect` | All (SNF,IRF,LTACH) | combos incl. SNF Only, SNF+IRF |
| Min Star Rating | select `#minRatingSelect` | Any | 2+/3+/4+/5 |
| Medi-Cal | select `#mediCalSelect` | Any | Accepts / Does Not |
| Medicare | select `#medicareSelect` | Any | Certified / Not |
| Sort By | select `#sortSelect` | Distance | Distance/Rating/Name |
| Exclude SFF Facilities | checkbox `#excludeSffCheck` | off | Special Focus Facility filter |

**Facility card** (`renderFacilityCard`): name, type badge, SFF/abuse flags, address + county + distance chip,
stars + tel link, cert pills (Medicare/Medi-Cal/beds/No Medicare), **Details ▼**, **+ Add to Plan**, **📤 Refer**.
**Detail panel** (`renderDetailPanel`): rating bars (health inspection/staffing/quality) + grid (CCN, ownership,
census, fines, penalties, bed counts, data source, last updated). No PHI (facility data).

### Clickable elements
| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
| --- | --- | --- | --- | --- | --- | --- |
| Search | button | `doSearch()` | Validate ZIP, query | `GET /api/directory/search?...` | Results rendered; freshness updated | button "Searching..."; spinner |
| ZIP field Enter | keydown | `doSearch()` | Same as Search | same | — | — |
| County Summary | button | `toggleCounty()` | Show/hide county table | `GET /api/directory/county-summary` (loaded after search) | Table toggled | n/a |
| ↻ Refresh Data | button | `triggerSync()` → `driveSync()` | Chunked CMS sync to completion | `POST /api/directory/sync` (repeated) | Banner progress → results | button "Refreshing..." |
| Details ▼/▲ | button | `toggleDetail(idx)` | Expand/collapse detail panel | — | Panel shown | n/a |
| + Add to Plan | button | `addToPlan(idx)` | Copy facility summary to clipboard | — | Toast "Copied!" | n/a |
| 📤 Refer | button | `openReferModal(idx)` | Open referral modal; load patients | `GET /api/patients?status=active&limit=50` | Modal open | — |
| Create & Send Referral | button | `submitReferral()` | Create (+ send) referral | `POST /api/referrals` then `POST /api/referrals/{id}/send` (if channel ≠ manual) | Toast with referral id | button "Creating referral…" |
| ✕ (modal) | button | `closeReferModal()` | Close modal | — | Modal closed | n/a |

### Functions (client-side)
- **DOMContentLoaded** — `GET /api/me` guard → `/login` on failure; prefill ZIP from `sessionStorage`; `checkSyncStatus()`.
- **`checkSyncStatus()`** — `GET /api/directory/sync-status`; set freshness label; if `total_active_facilities === 0` → `driveSync()`,
  else hide banner and auto-search if a 5-digit ZIP is present.
- **`driveSync()`** — loops up to 30 times: `POST /api/directory/sync {offset}` → `running`(advance `next_offset`)/`done`/`error`;
  shows progress/errors; on done updates freshness + auto-search. Guarded by `syncInProgress`.
- **`doSearch()`** — validates 5-digit ZIP; saves ZIP; builds query params; `GET /api/directory/search`;
  `renderNoDB()` for the DB-missing error, `showError()` otherwise; renders results; loads county summary in background.
- **`renderResults`/`renderFacilityCard`/`renderStars`/`renderDetailPanel`/`toggleDetail`** — list + detail rendering.
- **`addToPlan(idx)`** — clipboard copy (with `execCommand` fallback) + toast.
- **`loadCountySummary()`/`toggleCounty()`** — county table.
- **`triggerSync()`** — wraps `driveSync()` with button state + toast.
- **Referral modal:** `openReferModal`, `closeReferModal`, `submitReferral` (creates then auto-sends unless manual).
- **`escHtml`** — output escaping.

### API interactions
- `GET /api/directory/search?zip&radius&types&min_rating&medi_cal&medicare&exclude_sff&sort&limit` → `{results[], total, zip, radius_miles, data_freshness}`; **400** invalid ZIP; **500**/`error` for DB issues.
- `GET /api/directory/county-summary` → `{counties[]}`.
- `GET /api/directory/sync-status` → `{last_sync, total_active_facilities, data_freshness_hours}`.
- `POST /api/directory/sync {offset}` → `{status:"running", next_offset}` | `{status:"done", total_active_facilities}` | `{status:"error", error}` (page-at-a-time, 500-row pages).
- Referrals: `GET /api/patients?status=active&limit=50`, `POST /api/referrals`, `POST /api/referrals/{id}/send`.

### States & feedback
- **Loading:** "Searching..." spinner; sync banner with spinner + record count.
- **Success:** results header count; freshness badge.
- **Error:** red error state (`showError`); sync error banner with retry guidance.
- **Empty:** "🔍 No facilities found" (widen radius/filters).
- **No DB:** `renderNoDB()` → "🗄️ Database Not Connected" (requires `POSTGRES_URL`).

### End-user walkthrough
1. Open **Directory**. If unsynced, the chunked CMS sync runs automatically (~1 min).
2. Enter a 5-digit ZIP, choose radius/filters, **Search**.
3. Expand **Details ▼**; **+ Add to Plan** (copy) or **📤 Refer** to send a referral.
4. Use **County Summary** for aggregate counts; **↻ Refresh Data** to re-sync.

### Edge cases & notes
- Sync is intentionally chunked so each request stays within serverless time limits; the client drives it to completion.
- A separate cron route `GET /api/directory/cron-sync` (CRON_SECRET-protected) refreshes stale data server-side.
- Facility data is non-PHI; the referral modal pulls patient names (**PHI**) into the dropdown.

---

## Screen: Settings (`/settings`)

- **File:** `static/settings.html` — served by `web_app.py → settings_page` (after `require_login`).
- **Purpose:** Show system/eligibility/referral configuration status, supported payers, and run a mock eligibility test.
  Most values are **read-only environment status**; only referral settings are editable.
- **Access & preconditions:** Login required (page redirects to `/login` on a 401 from `/api/settings`).
  Status reflects current env/DB regardless of mode.
- **Entry points:** "Settings" nav link.
- **Layout (top→bottom):** header → System Status → Post-Acute Referral Settings (editable) → Real-Time Eligibility
  (status + `.env` snippet) → Supported Payers → Quick Eligibility Test → Security & HIPAA notice.

### Sections / fields
- **System Status** (`/api/settings`): Eligibility Service (Available/Unavailable), Patient DB (Connected/Not),
  Provider Directory (Connected/Not) — rendered as colored badges.
- **Referral Settings (editable):** Default Channel select (Fax/Manual/CarePort), Org NPI, Organization Name
  (fax header), Org Fax Number; delivery-channel status badges (Fax/CarePort/Direct). **Save** button.
- **Real-Time Eligibility (read-only badges):** `ELIGIBILITY_ENABLED`, `ELIGIBILITY_MOCK`, `STEDI_API_KEY`,
  `HOSPITAL_NPI` + a copyable `.env` example block.
- **Supported Payers:** grid of name + payer_id from `/api/eligibility/payers`.
- **Quick Eligibility Test:** Payer Name text input (default "Medicare Traditional") + **Run Mock Check** → result table.
- **Security & HIPAA:** static notes (cache is PHI; raw 271 never stored; minimal audit fields; 4h cache TTL).

### Clickable elements
| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
| --- | --- | --- | --- | --- | --- | --- |
| Save (referral settings) | button | `saveReferralSettings()` | Persist referral config | `PATCH /api/referrals/settings` | Button "✓ Saved" 2s | disabled "Saving…" |
| Run Mock Check | button | `runMockCheck()` | Mock eligibility for payer | `POST /api/eligibility/mock` | Result table (green/red) | n/a |

### Functions (client-side)
- **`loadSettings()`** — `GET /api/settings`; 401 → `/login`; renders status + eligibility badges via helper `b()`.
- **`loadPayers()`** — `GET /api/eligibility/payers` → payer grid; "Unavailable"/error fallback.
- **`runMockCheck()`** — `POST /api/eligibility/mock {payer_name}`; renders a table (Status, Payer, Plan, Type,
  Coverage Start, Deductible, OOP Max, SNF Days Left, Prior Auth, Source); colors by `is_eligible`; **no real API call**.
- **`loadReferralSettings()`** — parallel `GET /api/referrals/settings` + `/api/referrals/delivery-status`;
  populates inputs + channel badges (Fax active if DOCUMO key; CarePort if CAREPORT key; Direct = HISP required).
- **`saveReferralSettings()`** — `PATCH /api/referrals/settings {default_channel, org_name, org_fax, org_npi}`.
- On load: `loadSettings()`, `loadPayers()`, `loadReferralSettings()`.

### API interactions
- `GET /api/settings` → `{eligibility_enabled, eligibility_mock, stedi_configured, hospital_npi_configured, db_available, directory_available, eligibility_service_available}`.
- `GET /api/eligibility/payers` → `{payers:[{payer_id,name}]}`.
- `POST /api/eligibility/mock {payer_name}` → eligibility dataclass (mock).
- `GET/PATCH /api/referrals/settings`, `GET /api/referrals/delivery-status`.

### States & feedback
- **Loading:** "Loading…/Checking…" placeholders.
- **Success:** colored badges; mock result table; "✓ Saved".
- **Error:** "Could not load settings", alert on save failure.

### End-user walkthrough
1. Open **Settings**; review System Status and eligibility/referral configuration.
2. Edit referral defaults (channel/NPI/org name/fax) → **Save**.
3. Type a payer name → **Run Mock Check** to preview eligibility output (no live call).

### Edge cases & notes
- Eligibility/NPI/Stedi values are display-only here — actual changes are made via environment variables.
- Mock check never contacts Stedi; it uses deterministic mock data per resolved payer.

---

## Screen: Run Export Printable (`/api/patients/{id}/runs/{run_id}/export`)

- **File:** generated HTML string in `web_app.py → export_run_endpoint` (no static file).
- **Purpose:** Produce a confidential, auto-printing, self-contained HTML document of a single plan run for printing or PDF.
- **Access & preconditions:** Login required (API depends on `get_current_org`). **DB MODE** — **503** in FILE MODE;
  **404** if the patient (org-scoped via `get_org_domain`) or run is not found. Rate limit `30/hour`.
- **Entry points:** "🖨 Print / Export PDF" link on Patient Detail (opens in a new tab).
- **Layout (top→bottom):**
  1. **Header:** "🏥 DISCHARGE PLAN — CONFIDENTIAL" + meta (Patient name, MRN, Admission date, Plan generated, Run #, By). **PHI**.
  2. **DRAFT banner:** "⚠ DRAFT — Clinical decision support only. Not a substitute for clinical judgment."
  3. **Per-agent sections** in fixed order — Predictive Discharge Date, Clinical Assessment, Care Needs Assessment,
     Insurance Authorization, Medication Reconciliation, Social Determinants, Final Discharge Plan — each a `<pre>` of
     the stored `output_text` (HTML-escaped). If no `coordinator` agent row but `final_plan` exists, it is appended as "Final Discharge Plan".
  4. **Footer:** "Generated by Discharge Planning AI · <UTC timestamp>" + confidentiality notice.
- **Behavior:** inline `<script>window.onload = function(){ window.print(); };</script>` triggers the print dialog automatically.

### Clickable elements
| Element | Type | Action |
| --- | --- | --- |
| (auto) | script | Calls `window.print()` on load. No interactive controls (it is print-oriented HTML). |

### States & feedback
- **Success:** full document renders and the browser print dialog opens.
- **Error:** **503** (no DB), **404** (patient/run not found), **500** (other).

### Notes
- Org-scoped: a run from another org returns 404. Content is **PHI**; document is labeled confidential and DRAFT.

---

## Auxiliary Screens

<a id="aux-ward-barriers-ward-barriers"></a>
### Ward Barriers (`/ward-barriers`)
- **File:** `static/ward-barriers.html` — `web_app.py → ward_barriers_page` (after `require_login`).
- **Purpose:** Ward-wide view of discharge barriers across all patients, with summary stats and filters.
- **Access:** Login required. **DB MODE** (depends on patients + milestones APIs).
- **Key sections:** stat cards (Overdue / Open / Resolved Today / Total Patients); filters (Status default "open",
  Category, Priority, Overdue-only checkbox); barrier list (priority dot, title, patient deep link, category, overdue tag, status/assignee/due/source).
- **Main clickable elements + APIs:**
  - **↺ Refresh** → `load()`.
  - Filter selects/checkbox → `applyFilters()` (client-side over loaded barriers).
  - Patient link → `/patients/{id}`.
  - `load()` calls `GET /api/patients`, `GET /api/milestones/ward-summary`, then `GET /api/patients/{id}/milestones` per patient (fan-out).
- **States:** "Loading barriers…", empty ("No barriers match…"), failure message. 401 → `/login`.

<a id="aux-ward-referrals-ward-referrals"></a>
### Ward Referrals (`/ward-referrals`)
- **File:** `static/ward-referrals.html` — `web_app.py → ward_referrals_page` (depends on `get_current_org`; **401 → JS handles**).
- **Purpose:** Manage post-acute referrals org-wide: summary stats, analytics, filtering, detail modal with status updates, resends, and messages.
- **Access:** Login required. **DB MODE** (referrals APIs).
- **Key sections:** summary stats (Total / Accepted / Pending / Sent-awaiting); analytics (by status, by channel —
  toggled by 📊 Analytics); filters (status, time window default 90 days); referral list; detail modal.
- **Main clickable elements + APIs:**
  - **+ New Referral** → `/post-acute-directory`.
  - **📊 Analytics** → `loadAnalytics()` → `GET /api/referrals/analytics`.
  - Filters → `loadReferrals()` → `GET /api/referrals{?status,days}`.
  - **View** (row) → `openDetail(id)` → `GET /api/referrals/{id}`, `/delivery-log`, `/messages`.
  - **Resend** (row, when sent/pending_review) → `resendReferral(id)` → `POST /api/referrals/{id}/resend`.
  - **Update** (modal) → `updateStatus(id)` → `PATCH /api/referrals/{id}/status`.
  - **Send** (message) → `sendMessage(id)` → `POST /api/referrals/{id}/messages`.
  - ✕ / backdrop → `closeDetailModal()`/`closeModal(event)`.
- **States:** "Loading referrals…"; modal detail; per-action errors. ⚠ NEEDS VERIFICATION: full FILE-MODE behavior of referral endpoints (not fully reviewed).

<a id="aux-roi-measured-roi-measured"></a>
### ROI Measured (`/roi-measured`)
- **File:** `static/roi-measured.html` — `web_app.py → roi_measured_page` (after `require_login`).
- **Purpose:** Org-level measured-outcomes ROI dashboard (days saved, cost savings, DRG breakdown, per-episode list) with date-range controls, CSV/print export, and editable ROI settings.
- **Access:** Login required (page calls `/api/me`). **DB MODE** — `web_app.py → roi_dashboard` returns default/zeroed data in FILE MODE.
- **Key sections:** date-range buttons (30d/90d/180d/YTD/Custom); header actions (Export CSV, Print, ⚙ Configure);
  KPI cards; DRG breakdown table (sortable, click-to-filter); episodes list (Load more); settings modal.
- **Main clickable elements + APIs:**
  - Range buttons → `setRange(...)`/`toggleCustom(...)`.
  - **⬇ Export CSV** → `exportCsv()` → `GET /api/roi/export`; **🖨 Print** → `window.print()`.
  - **⚙ Configure** → `openSettings()`; **Save & Reload** → `saveSettings()` → `PATCH /api/roi/settings`.
  - DRG table headers/rows → `sortDrg(col)` / `selectDrg(code)` (client filter) / `clearDrgFilter()`.
  - **Load more episodes** → `loadMoreEpisodes()` → `GET /api/roi/outcomes?limit&offset`.
  - Initial: `GET /api/roi/dashboard?...`, `GET /api/roi/outcomes?...`, `GET /api/roi/settings`.
- **States:** loading; **Retry** button on dashboard load error; empty when no outcomes. 401 handling via `/api/me`.

<a id="aux-pilot-pilot"></a>
### Pilot (`/pilot`)
- **File:** `static/pilot.html` — `web_app.py → pilot_page_route`.
- **Purpose:** Public marketing/application page for the 6-month revenue-share pilot (5 hospital spots).
- **Access:** **Public — no login** (route has no `require_login`/`get_current_org`).
- **Key sections:** hero with remaining-spots count; "What You Get"; estimated math; eligibility; application form;
  FAQ accordion.
- **Form fields:** hospital_name, applicant_name, (title, phone, ehr_system, annual_discharges, how_found,
  challenge_text optional), email, licensed_beds, two required consent checkboxes (revenue share + CA hospital).
- **Main clickable elements + APIs:**
  - **Submit** → `submitApplication()` → `POST /api/pilot/apply` (rate-limited `3/hour`; server validates name/email/consents, 100+ beds).
  - FAQ questions → `toggleFaq(i)`.
  - On load: `GET /api/pilot/spots` → `{total_spots:5, confirmed_pilots, remaining}` (defaults to 5 remaining in FILE MODE).
- **States:** spots count; success message ("Thank you, <first name>…"); validation errors (400).

<a id="aux-tcm-roi-calculator-tcm-roi-calculator"></a>
### TCM ROI Calculator (`/tcm-roi-calculator`)
- **File:** `static/tcm-roi-calculator.html` — `web_app.py → tcm_roi_calculator_page`.
- **Purpose:** Public, fully client-side calculator estimating Transitional Care Management (TCM) revenue vs platform cost.
- **Access:** **Public — no login**. No PHI (aggregate hospital inputs only).
- **Key sections:** hospital-size presets (175/350/625/800 beds with discharges/Medicare %); "Without Discharge
  Planning AI"; "Platform Subscription vs TCM Revenue"; methodology/assumptions.
- **Main clickable elements:**
  - Size preset cards → `selectSize(this)` (reads `data-beds/discharges/medicare`; computation is client-side).
  - **📥 Download as PDF** → `window.print()`.
- **States:** live recalculation as inputs change. ⚠ NEEDS VERIFICATION: exact recalculation handler names (input listeners not fully enumerated here).

<a id="aux-offline-offline"></a>
### Offline (`/offline`)
- **File:** `static/offline.html` — `web_app.py → offline_page` (**no auth** so the service worker can serve it).
- **Purpose:** PWA offline fallback. Lists patient records cached by the service worker and pending sync count; auto-reloads when back online.
- **Access:** Public (served by SW). Reads only **local** browser caches/IndexedDB (no network APIs).
- **Key sections:** top blue disclaimer banner; "Connection restored" notice; stat cards (Cached Patients / Pending Syncs);
  cached patient list; "Go to My Patients".
- **Main behaviors (no server APIs):**
  - `loadCachedPatients()` reads `caches` keys (`dp-patient-*`) and `match('/api/patients/{id}')`; reads IndexedDB
    `dp-sync-queue → mutations` count; refreshes every 10s.
  - `window 'online'` listener shows the restore banner and redirects to `/my-patients` after 3s.
- **Notes:** cached patient cards link to `/patient/{id}` (singular). ⚠ NEEDS VERIFICATION: this path differs from the
  app's `/patients/{id}` (plural) detail route — possible dead link / SW-rewrite dependency.

---

## Open Questions / NEEDS VERIFICATION

1. **TCM SSE events on the planner** — `web_app.py → create_plan` emits `tcm_episode_created` / `tcm_not_applicable`,
   but `static/index.html → handleEvent()` has no case for them (silently ignored). Intended UI?
2. **Markdown sanitization** — `index.html → showReport()` renders model output via `marked` without an obvious
   sanitizer; confirm XSS handling for AI/EHR-derived content.
3. **Login lockout durability** — `LOCKOUT_THRESHOLDS` and failure counts live in process memory
   (`_login_failures`/`_login_lockouts`); behavior across serverless instances/restarts unverified.
4. **Offline cached-patient link** — `offline.html` links to `/patient/{id}` (singular) vs the real `/patients/{id}`
   (plural); verify the SW rewrites this or fix the link.
5. **TCM ROI Calculator handlers** — only `selectSize`/`window.print` confirmed; the live input recalculation
   handlers were not exhaustively enumerated.
6. **Ward Referrals FILE-MODE behavior** — referral endpoints' empty/503 responses were not fully traced.
7. **DRG dataset currency** — UI labels reference "CMS FY 2026" geometric-mean LOS and "$4,100/day (AHA 2024, CA)";
   confirm these constants match the server-side ROI engine.
