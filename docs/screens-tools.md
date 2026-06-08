# Discharge Planning AI — AI Tool / Generator Screens

Technical reference for the AI "tool/generator" screens. Documented strictly from source: `static/<file>.html` (HTML + inline `<script type="text/babel">` React components) and `web_app.py` backend routes. Synthetic examples only; no real PHI.

## Table of Contents

1. [Summary Generator (`/summary-generator`)](#1-summary-generator-summary-generator)
2. [Discharge Summary Generator (`/discharge-summary-generator`)](#2-discharge-summary-generator-discharge-summary-generator)
3. [Teach-back Checklist (`/teachback-checklist`)](#3-teach-back-checklist-teachback-checklist)
4. [CDPH Compliance (`/cdph-compliance`)](#4-cdph-compliance-cdph-compliance)
5. [HRRP Flagging (`/hrrp-flagging`)](#5-hrrp-flagging-hrrp-flagging)
6. [ROI Tracker (`/roi-tracker`)](#6-roi-tracker-roi-tracker)
7. [Readmission Tracker (`/readmission-tracker`)](#7-readmission-tracker-readmission-tracker)
8. [Multilingual Instructions (`/multilingual-prompt-system`)](#8-multilingual-instructions-multilingual-prompt-system)
9. [IMM Compliance Module (`/imm-prompt-system`)](#9-imm-compliance-module-imm-prompt-system)
- [Appendix A — Shared elements](#appendix-a--shared-elements-global-nav-disclaimer-export)
- [Appendix B — FILE vs DB modes](#appendix-b--file-vs-db-modes)
- [Open Questions](#open-questions)

---

## Shared conventions (read first)

These tool pages share three cross-cutting elements documented once in **Appendix A**, referenced (not re-documented) per screen:

- **Global nav bar** — the blue gradient `<header>` with links to every tool plus `Sign Out` (`/api/auth/logout`).
- **Clinician-review disclaimer** — every exported/printed report carries an AI-assisted decision-support disclaimer; the global planner page (`web_app.py` line 2018) shows a `⚠ DRAFT — Clinical decision support only.` banner. Tool pages embed their own disclaimer text inside exports (see `static/report-export.js`).
- **Report-export buttons** — Download HTML / Save as PDF, served by `static/report-export.js → window.ReportExport`.

**Auth gate (all pages):** an inline `<script>` calls `fetch('/api/me')`; on non-OK it redirects to `/login`. Page routes (`@app.get("/summary-generator")` etc.) are served by `web_app.py` (lines 1087–1177). All `/api/.../generate|analyze` POST routes depend on `get_current_org` (`web_app.py → get_current_org`, line 684) and are rate-limited via SlowAPI `@limiter.limit`.

**FILE vs DB:** the generator endpoints themselves do NOT branch on storage mode — they call Anthropic and return JSON (stateless; results are not persisted server-side). Only the ROI dashboard reads (`/api/roi/*`, `/api/tcm/platform-roi`) and the planner's `/api/plan/stream` path touch the DB. See **Appendix B**.

**PHI note:** these generators accept free-text clinical notes / discharge plans and patient context (initials, MRN, DOB, dates, diagnosis, payer). All such inputs are PHI. Demo data shipped in the pages (e.g. `E.M.`, `****4821`) is synthetic. None of the generate endpoints persist input or output (no DB writes in the route bodies) — ⚠ NEEDS VERIFICATION that the audit middleware does not log request bodies.

---

## 1. Summary Generator (`/summary-generator`)

- **File:** `static/summary-generator.html`
- **Purpose:** Dual-purpose page. (a) A **prompt-engineering reference** displaying the production system prompt, user-prompt template, output schema, integration code, translation prompt, and prompt rules; (b) a live **"Try it"** discharge-summary generator that POSTs to `/api/summary/generate`.
- **Access & preconditions:** Authenticated session (`/api/me`). Server requires `ANTHROPIC_API_KEY` (else 500 "ANTHROPIC_API_KEY not configured"). Rate limit 20/hour (`web_app.py → generate_summary`).
- **Entry points:** Global nav (`Prompts` link on sibling pages); direct route `/summary-generator` (`web_app.py` line 1087).
- **Layout overview:** Global `<header>`; a dark tab bar with 7 tabs; a content pane (max-width 900) that renders either a code/prompt viewer, the rules grid, or the Try-it form; a footer with three "Copy" buttons.

### Sections / panels

- **Tab bar** (`static/summary-generator.html → DischargeSummaryPrompt`, `tabs` array): `System prompt`, `User prompt template`, `Output schema`, `Integration code`, `Translation prompt`, `Prompt rules`, `▶ Try it`.
- **Prompt viewer** (tabs system/user/output/integration/translation): read-only `<pre>` with the content of `promptContent[activeTab]`; a per-tab "Copy prompt" button; contextual info callouts for the `user` and `integration` tabs; an approximate token count footer.
- **Prompt rules** (tab `rules`): 5 color-coded cards (`Accuracy & Safety`, `California Compliance`, `Readability`, `Output Reliability`, `Translation`) rendered from the `rules` array — static reference text, no interactivity beyond display.
- **Try it form** (tab `try`):
  | Field | Label | Type | Required | Validation | Sample | PHI? |
  |---|---|---|---|---|---|---|
  | admissionDate | Admission Date | date | no | none | 2026-05-14 | yes |
  | dischargeDate | Discharge Date | date | no | none | 2026-05-18 | yes |
  | attending | Attending Physician | text | no | none | Dr. Sarah Chen | yes |
  | unit | Unit / Service | text | no | none | Cardiology — 4W | no |
  | payer | Insurance / Payer | text | no | none | Medicare FFS | yes |
  | language | Patient Language | text | no | default "English" | English | no |
  | laceScore | LACE Score | text | no | none | 11 | yes |
  | laceTier | LACE Tier (low/moderate/high) | text | no | none | high | no |
  | hrrpFlag | HRRP Condition (or None) | text | no | none | Heart Failure | no |
  | tryNotes | Clinical Notes * | textarea | **yes** | non-empty `.trim()` client-side; else "Please enter clinical notes." | free text H&P | **yes** |
  - **Conditional content:** physician-review banner shown when `tryResult.summary_metadata.requires_physician_review` is true; result block (Download HTML / Save as PDF / Copy JSON + raw JSON `<pre>`) shown only when `tryResult` is set.

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Tab buttons (×7) | button | `setActiveTab(t.id)` | Switches content pane | none | re-render | n/a |
| Copy prompt | button | `copy(promptContent[activeTab], activeTab)` | `navigator.clipboard.writeText` | none | label → "✓ Copied" 2s | n/a |
| Generate Discharge Summary | button | `handleTry` | Validates notes, POSTs context+notes | `POST /api/summary/generate` | sets `tryResult` or `tryError` | disabled while `tryLoading`; label "Generating…" |
| Download HTML | button | `ReportExport.download(..., ReportExport.capture("#dp-report", {...}))` | Saves self-contained report | none | downloads `.html` | n/a |
| Save as PDF | button | `ReportExport.print(ReportExport.capture("#dp-report", {print:true}))` | Opens print window | none | print dialog | n/a |
| Copy JSON | button | `copy(JSON.stringify(tryResult,null,2),"try-result")` | Copies result JSON | none | "✓ Copied" 2s | n/a |
| Footer Copy system/user/integration | button | `copy(promptContent[id], "footer-"+id)` | Copies that prompt | none | "✓" 2s | n/a |

### Functions (client-side)

- **`copy(text, id)`** — trigger: any copy button. Writes to clipboard, sets `copied=id` for 2s. No API, no error path beyond promise rejection (unhandled).
- **`handleTry()`** — trigger: Generate button. Inputs: `tryNotes`, `tryContext`. Steps: guard empty notes → set loading → `fetch('/api/summary/generate', {clinicalNotes, patientContext})` → parse JSON defensively → on `res.ok && data.success` set `tryResult`, else set `tryError` to `data.error` or `Server error <status>`. Catch → "Could not reach the server." Finally clears loading. Render: result block + optional MD-review banner. Empty/loading/error all handled.

### API interactions

- **Endpoint:** `POST /api/summary/generate` (`web_app.py → generate_summary`, line 1569).
- **Request payload:** `{ "clinicalNotes": "<string, required>", "patientContext": { admissionDate, dischargeDate, attending, unit, payer, language, laceScore, laceTier, hrrpFlag } }`.
- **Server behavior:** builds system + user prompt, calls `claude-sonnet-4-6`, `max_tokens=4000`, `temperature=0`; strips markdown fences; `json.loads`. **Server-side enforcement:** if `summary.california_compliance.hrrp_condition_flagged` is truthy, sets `summary.readmission_risk.follow_up_call_cadence = "24h + 72h + 7d + 14d"` (HRRP follow-up cadence override — `web_app.py` lines 1648–1650). (The prompt also instructs the model to set that cadence when LACE ≥ 10, rule #3, but only the HRRP-flag branch is hard-enforced in code.)
- **Response (rendered):** `{ "success": true, "summary": {...} }`. On parse failure: `{ "success": false, "error": "JSON parse failed", "raw": "<text>" }` (HTTP 500). The page renders `summary` verbatim as pretty JSON plus the review banner.
- **Output JSON schema** (top-level keys the page expects; full schema is the `EXAMPLE_OUTPUT` / `USER_PROMPT_TEMPLATE` constants in the page):
  ```
  summary_metadata { generated_at, source_note_quality(complete|partial|insufficient),
                     missing_fields[], confidence(high|medium|low),
                     requires_physician_review(bool), review_reason }
  patient_summary  { primary_diagnosis, secondary_diagnoses[], admission_reason,
                     hospital_course, procedures_performed[], condition_at_discharge, functional_status }
  medications      { discharge_medications[{name,dose,route,frequency,duration,indication,new_or_changed,patient_instruction}],
                     medications_stopped[{name,reason_stopped}], reconciliation_complete,
                     high_alert_medications[], reconciliation_notes }
  follow_up        { appointments[{provider,timeframe,reason,scheduled,scheduling_instructions}],
                     labs_pending[], imaging_pending[], primary_care_notified }
  patient_education{ diagnosis_explanation, warning_signs[{sign,action}], activity_restrictions,
                     diet_instructions, wound_care, teach_back_topics[] }
  post_acute_plan  { discharge_destination, home_health_ordered, home_health_services[], dme_ordered[],
                     snf_name, snf_cms_stars, three_day_rule_met, patient_choice_documented }
  california_compliance { cdph_cop_checklist_complete, imm_delivered, imm_delivery_timestamp,
                          livanta_qio_rights_provided, appeal_deadline, medi_cal_auth_status,
                          medi_cal_plan, ab_1195_rights_provided, hrrp_condition_flagged,
                          hrrp_condition, team_model_bundle_applicable, estimated_hrrp_exposure }
  liability_documentation { discharge_against_advice, patient_refused_services[],
                            family_concerns_documented, unsafe_discharge_complaint,
                            planner_attestation_required, attestation_statement }
  readmission_risk { lace_score, risk_tier, primary_risk_factors[], mitigation_interventions[],
                     follow_up_call_cadence(24h only|24h + 72h|24h + 72h + 7d + 14d),
                     transitional_care_management_applicable }
  ```
  Note: the page-displayed schema (`USER_PROMPT_TEMPLATE`) is a reference; the live server prompt (`web_app.py`) requests the same top-level keys but is not byte-identical to the page constant.

### States & feedback
- Loading: button text "Generating…", disabled, dim color.
- Error: red callout above button.
- Success: result block + MD-review banner if flagged.

### End-user walkthrough
1. Open `/summary-generator`; browse System/User/Output/Integration/Translation/Rules tabs to learn the prompt design; use Copy to grab prompts.
2. Click `▶ Try it`.
3. Fill patient context fields (optional) and paste clinical notes (required).
4. Click **Generate Discharge Summary**.
5. Review the MD-review banner (if shown) and the structured JSON.
6. Download HTML / Save as PDF / Copy JSON.

### Edge cases & notes
- Empty notes blocks the call client-side.
- Server 500 if `ANTHROPIC_API_KEY` missing or model output isn't valid JSON (raw text returned for debugging).
- Integration-code tab is purely illustrative Next.js (references `process.env.ANTHROPIC_API_KEY`) — not the actual server code path.

---

## 2. Discharge Summary Generator (`/discharge-summary-generator`)

- **File:** `static/discharge-summary-generator.html`
- **Purpose:** Live structured-summary generator with a rich rendered (non-JSON) clinical view; distinct from screen #1 (which is prompt-reference-first). POSTs to `/api/discharge-summary/generate`.
- **Access & preconditions:** Auth session; server `ANTHROPIC_API_KEY`. Rate limit 20/hour (`web_app.py → generate_discharge_summary_v2`, line 1418).
- **Entry points:** Nav `Summary` links; route line 1114.
- **Layout overview:** Global `<header>`; a dark tool top-bar with Copy JSON / Print (shown once a summary exists); a 2-tab switcher (`📋 Input`, `📄 Summary`); panel content.

### Sections / panels

**Input tab — Patient context** (`static/discharge-summary-generator.html → DischargeSummaryGenerator`, `ctx` state):
| Field | Label | Type | Required | Validation | Sample | PHI? |
|---|---|---|---|---|---|---|
| admissionDate | Admission date | date | no | none | 2026-05-14 | yes |
| dischargeDate | Discharge date | date | no | none | 2026-05-18 | yes |
| attending | Attending physician | text | no | none | Dr. Sarah Chen, MD | yes |
| unit | Unit / service | text | no | none | Cardiology — 4W | no |
| payer | Insurance / payer | text | no | none | Medicare Fee-for-Service | yes |
| laceScore | LACE risk score | number | no | none | 11 | yes |
| hrrpFlag | HRRP condition | text | no | none | Heart Failure | no |

**Input tab — Clinical notes:**
| Field | Label | Type | Required | Validation | Sample | PHI? |
|---|---|---|---|---|---|---|
| notes | Clinical notes | textarea | **yes** | Generate disabled if `!notes.trim()` | `DEMO_NOTES` (synthetic CHF case) | **yes** |
- Word counter under the textarea.

**Summary tab:** renders the structured summary via `SectionCard` components: header (LACE chip + HRRP/MD-review/confidence badges), optional MD-review banner, optional missing-fields banner, then sections Diagnosis & Hospital Course, Medications (`MedCard`, high-alert highlight + stopped meds), Follow-Up Plan (`apt` cards, labs/imaging, call cadence), Warning Signs (`WarnRow`, urgency colors + action icons), Patient Education (teach-back checkboxes, activity/diet), Post-Acute Plan, and a Planner attestation block. **LACE display:** `summary.meta.lace_score` + `lace_tier` shown as a colored chip (tierColor map high/moderate/low/unknown).

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| 📋 Input / 📄 Summary tabs | button | `setActiveTab(t)` | Switch panel | none | re-render | n/a |
| Context inputs | input | `setCtx(p=>{...})` | Update ctx | none | — | n/a |
| Clinical notes | textarea | `setNotes` | Update notes | none | — | n/a |
| ✦ Generate Discharge Summary | button | `generate` | Calls API, switches to Summary | `POST /api/discharge-summary/generate` | sets `summary`/`error` | disabled if loading or empty notes; spinner |
| Copy JSON (top-bar + action row) | button | `copyJSON` | Copies summary JSON | none | "✓ Copied" 2s | n/a |
| 🖨 Print (top-bar) | button | `window.print()` | Browser print (CSS `@media print` hides chrome) | none | print dialog | n/a |
| ⬇ Download HTML | button | `ReportExport.download(..., ReportExport.capture("#dp-report",{...}))` | Save report | none | downloads `.html` | n/a |
| 🖨 Save as PDF | button | `ReportExport.print(ReportExport.capture("#dp-report",{print:true}))` | Print report | none | print window | n/a |
| ← Edit Input | button | `setActiveTab("input")` | Back to form | none | — | n/a |
| ↺ New Summary | button | `setSummary(null); setActiveTab("input")` | Reset | none | — | n/a |

### Functions (client-side)
- **`callClaude(ctx, notes)`** — POSTs `{ctx, notes}`; throws on `!res.ok` (uses `data.error`) or `!data.success`; returns `data.summary`.
- **`generate()`** — sets loading, clears error/summary, awaits `callClaude`, on success sets summary and switches to Summary tab; catch sets error; finally clears loading. Handles loading (spinner + progress bar) and empty states ("No summary yet").
- **`copyJSON()`** — clipboard write of `JSON.stringify(summary,null,2)`, 2s toast.
- Presentational: `Badge`, `SectionCard`, `Field`, `MedCard`, `WarnRow` (render-only, with `URGENCY_COLORS` / `ACTION_ICON` maps).

### API interactions
- **Endpoint:** `POST /api/discharge-summary/generate` (`web_app.py → generate_discharge_summary_v2`).
- **Request:** `{ "ctx": {admissionDate,dischargeDate,attending,unit,payer,laceScore,hrrpFlag}, "notes": "<string,required>" }`.
- **Server:** `claude-sonnet-4-6`, `max_tokens=4000`, `temperature=0`; strips fences; returns `{success:true, summary}` or `{success:false, error:"JSON parse failed", raw}` (500). No HRRP cadence override here (unlike screen #1) — cadence is whatever the model returns in `follow_up.call_cadence`.
- **Output schema (rendered keys):**
  ```
  meta { confidence, requires_physician_review, review_reason, missing_fields[],
         generated_at, hrrp_flagged, hrrp_condition, lace_score, lace_tier(high|moderate|low|unknown) }
  diagnosis { primary, secondary[], admission_reason, hospital_course,
              condition_at_discharge(stable|improved|unchanged|declined), functional_status }
  medications[] { name, dose, route, frequency, duration, indication,
                  is_new, is_changed, is_high_alert, patient_instruction, special_instructions }
  medications_stopped[] { name, reason }
  reconciliation_complete
  follow_up { appointments[{provider,timeframe,reason,scheduled,phone,patient_instruction}],
              labs_pending[], imaging_pending[], tcm_applicable,
              follow_up_call_scheduled, call_cadence(24h|24h+72h|24h+72h+7d+14d|none) }
  warning_signs[] { sign, action(call_doctor|go_to_er|call_911), action_label, urgency(urgent|emergent|life_threatening) }
  activity_restrictions, diet_instructions, wound_care
  patient_education { diagnosis_explained, teach_back_topics[] }
  post_acute { destination, home_health, home_health_services[], dme[] }
  attestation
  ```

### States & feedback
- Loading: spinner + animated progress bar in Summary pane; Generate button shows spinner.
- Empty Summary: "No summary yet" placeholder + "Go to Input".
- Error: red banner in Input pane.

### End-user walkthrough
1. Open page (Input tab pre-filled with demo CHF context + notes).
2. Edit context / paste notes.
3. Click **✦ Generate Discharge Summary** → auto-switches to Summary tab.
4. Review badges (LACE/HRRP/confidence), MD-review and missing-fields banners.
5. Tick teach-back checkboxes (UI only — not persisted).
6. Copy JSON / Print / Download HTML / Save as PDF.

### Edge cases & notes
- Teach-back checkboxes and the attestation block are display-only (no state binding / persistence).
- LACE chip only renders when `meta.lace_score != null`.

---

## 3. Teach-back Checklist (`/teachback-checklist`)

- **File:** `static/teachback-checklist.html`
- **Purpose:** Generates patient-specific teach-back questions, lets the planner record per-question responses + notes, and sign an attestation. POSTs to `/api/teachback/generate`.
- **Access & preconditions:** Auth session; server `ANTHROPIC_API_KEY`. Rate limit 30/hour (`web_app.py → generate_teachback`, line 1359).
- **Entry points:** Nav `Teach-back`; route line 1123.
- **Layout overview:** Global `<header>`; dark tool bar with Download HTML / Save as PDF (when questions exist); two-column body — left sidebar (patient context inputs + source-data toggle + Generate), right panel (doc header with progress ring, stats, category tabs, question cards, attestation).

### Sections / panels

**Left sidebar — Patient context** (`static/teachback-checklist.html → TeachBackChecklist`, `ctx` state):
| Field | Label | Type | Required | Validation | Sample | PHI? |
|---|---|---|---|---|---|---|
| patientInitials | Initials | text | no | none | E.M. | yes |
| mrn | MRN (last 4) | text | no | none | ****4821 | yes |
| laceScore | LACE score | number | no | none | 11 | yes |
| language | Language | text | no | none | English | no |
| destination | Destination | text | no | none | home | no |
- **LACE risk callout:** computed `lace = parseInt(ctx.laceScore)`; color/label thresholds — `>=10` High (red), `>=5` Moderate (amber), else Low (green); if `>=10` shows "All questions marked required."

**Left sidebar — Source data:** toggle `Demo CHF` (uses `DEMO_SUMMARY`) vs `Manual`. In Manual mode, 5 textareas appear (`medications`, `warningsSigns`, `followUp`, `activity`, `diet`) — all PHI-bearing free text.

**Right panel — generated record:** doc header (patient initials/MRN/date + `patientSummary` + `ProgressRing`); 5 stat cards (Total / Required / Passed / Partial / Remaining); required-incomplete warning; category tabs; per-category question cards; attestation block.

**Question categories (output structure):** array of category objects, each `{ id, label, icon, priority, questions[] }`. Canonical categories requested in prompt: `medications` (Medications, pill, critical), `warning_signs` (Warning Signs, alert, critical), `diagnosis` (Understanding Condition, heart, high), `followup` (Follow-up & Next Steps, calendar, high), `lifestyle` (Activity & Diet, leaf, standard). Each question: `{ id, required, priority, topic, question, expected_answer, planner_tip, red_flag, follow_up_teaching }`.

**Per-question response capture** (`QuestionCard`): three response buttons — `demonstrated` (✓), `needs_reinforcement` (↺), `not_attempted` (—) — plus a free-text notes textarea. `red_flag` and `follow_up_teaching` blocks reveal only when response is `needs_reinforcement`.

**Attestation block:** static certification text; computed summary (required passed, need-reinforcement, overall, high-alert verified); inputs `plannerName` (text) and `date` (date); Sign button.

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Demo CHF / Manual toggle | button | `setUseDemoSummary(v)` | Choose source | none | shows/hides manual textareas | n/a |
| ✦ Generate questions | button | `generate` | Builds prompt, calls API | `POST /api/teachback/generate` | sets `questions`, `patientSummary`, expands first Q per cat | disabled while loading; "Generating…" |
| ↺ Regenerate | button | `generate` | Re-run | same | replaces questions | n/a |
| Response buttons (×3/Q) | button | `setResponse(q.id, key)` | Records response | none | recolors card; reveals risk/teaching if reinforcement | n/a |
| Notes textarea | textarea | `setNote(q.id,val)` | Stores note | none | — | n/a |
| Question header | div onClick | `toggleExpand(q.id)` | Expand/collapse detail | none | — | n/a |
| Category tab | button | `setActiveCategory(cat.id)` | Switch category | none | — | n/a |
| Expand all | button | inline setExpanded for category | Expand all Qs in category | none | — | n/a |
| Sign & lock | button | `setAttestation(p=>{signed:true})` | Locks attestation | none | shows "✓ Attested by …" | disabled unless `canAttest && plannerName && !signed` |
| Download HTML / Save as PDF | button | `ReportExport.download/print(ReportExport.capture("#dp-report",{...}))` | Export record | none | file / print | n/a |

### Functions (client-side)
- **`buildPrompt(summary, ctx)`** — assembles the user prompt from summary medications/warnings/follow-up + ctx, embedding the required JSON schema and rules (e.g. ≥1 question per med, ≥2 warning-sign questions, all high-alert meds required, LACE≥10 → all med/warning Qs required).
- **`callClaude(summary, ctx)`** — POSTs `{prompt: buildPrompt(...)}`; throws on `!res.ok`, `!data.success`, or **missing categories**: `if (!data.result?.categories?.length) throw "Claude returned an unexpected structure — please try again."` (the "missing categories" error). Returns `data.result`.
- **`generate()`** — clears responses/notes/expanded, awaits `callClaude` (demo or empty summary), sets categories + patientSummary + first active category, auto-expands first question of each category; catch sets error; finally loading off.
- **Computed:** `allQ`, `requiredQ`, `answered`, `passed`, `partial`, `requiredPassed`, `requiredPartial`, `completionPct`, `canAttest = requiredQ.length>0 && requiredQ.every(answered)`.
- Presentational: `Pill`, `ProgressRing` (SVG), `QuestionCard`.

### API interactions
- **Endpoint:** `POST /api/teachback/generate` (`web_app.py → generate_teachback`).
- **Request:** `{ "prompt": "<full user prompt string>" }` (system prompt lives server-side).
- **Server:** `claude-sonnet-4-6`, `max_tokens=8000`, `temperature=0`; strips fences; **validates** `categories` is a list, else `{success:false, error:"Response missing 'categories' field"}` (500). Success: `{success:true, result}`.
- **Output schema (rendered):**
  ```
  { patient_summary, total_required,
    categories[ { id, label, icon, priority,
                  questions[ { id, required, priority, topic, question,
                               expected_answer, planner_tip, red_flag, follow_up_teaching } ] } ] }
  ```

### States & feedback
- Loading: spinner + rotating status lines.
- Empty: "Ready to generate teach-back questions" placeholder.
- Error: red box in sidebar (`⚠ Error: <msg>`), including the missing-categories message.
- Required-incomplete: red banner counting unanswered required items.

### End-user walkthrough
1. Open page; set patient context (left).
2. Choose Demo CHF or Manual (and fill source textareas if Manual).
3. Click **✦ Generate questions**.
4. Click a category tab; expand questions; for each, click Demonstrated / Needs reinforcement / Not attempted and add notes.
5. Watch progress ring + stats update; resolve required items flagged red.
6. Enter planner name + date; click **Sign & lock teach-back record**.
7. Download HTML / Save as PDF.

### Edge cases & notes
- Responses, notes, and attestation are client-only state — not persisted to a server (lost on reload). ⚠ NEEDS VERIFICATION whether any autosave exists (none found).
- `q.is_high_alert` is read by the card but is not in the documented schema — relies on the model adding it.
- Generate disables only on loading, not on empty context (it can run on demo data).

---

## 4. CDPH Compliance (`/cdph-compliance`)

- **File:** `static/cdph-compliance.html`
- **Purpose:** California-specific discharge compliance workspace (CDPH CoP checklist, Medi-Cal auth tracking, Commence Health/Livanta QIO IMM/appeal timeline, 3-day SNF rule calculator) that produces an AI compliance-risk report via `/api/cdph-compliance/analyze`.
- **Access & preconditions:** Auth session; server `ANTHROPIC_API_KEY`. Rate limit 30/hour (`web_app.py → analyze_cdph_compliance`, line 1299).
- **Entry points:** Nav `CDPH`; route line 1132.
- **Layout overview:** Forest-green top bar (compliance % + "Compliance report" button); patient-context strip; 5 tabs (`CDPH Checklist`, `Medi-Cal Auth`, `Commence Health QIO`, `3-Day SNF Rule`, `Compliance Report`); tab bodies; an AI report view.

### Sections / panels

**Patient context** (`CDPHComplianceChecklist`, `patient` state): `initials`, `mrn`, `admitDate`, `dcDate`, `payer` (e.g. `medi_cal_managed`), `planId`, `medicare` (bool), `lace`, `diagnosis`, `attending`. All identifying fields are **PHI**.

**CDPH Checklist tab:** items from a `CHECKLIST` constant with `critical` priority; toggled via `toggleCheck(id)`; per-item notes. Computed `compliancePct = checkedCount/totalItems`.

**Medi-Cal Auth tab:** `authItems[]` `{ id, service, status(approved|pending|denied|not_req|not_init|urgent), authNum, expiry, requested }`; editable rows; `+ Add service` (`addAuth`); `StatusBadge` per row.

**Commence Health QIO tab:** `livanta` state — IMM delivery date/time/signed, re-delivery date/time/signed, appeal filed/date/time, Commence Health call time/case number, determination/date. `Countdown` components compute live remaining time to `appealDeadline = redelivDate + 1 day` and `livantaDetDeadline = appealDate + 1 day`.

**3-Day SNF Rule tab:** `snf` state — `admitStatus` (inpatient/observation), dates, `teamModel`, `cahSwingBed`. `snfCalc()` (client-only) determines Medicare SNF eligibility: TEAM+CAH swing-bed → waived; observation → ineligible (0 days); else counts inpatient days, `>=3` eligible.

**Compliance Report tab:** rendered AI report — overall status, score, critical gaps, warnings, CA-specific notes, one-liners (Commence Health/Medi-Cal/SNF), attestation readiness/blockers.

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Tab buttons (×5) | button | `setTab(t.id)` | Switch tab | none | re-render | n/a |
| Context/auth/livanta/snf inputs | input/select | `setPt/updateAuth/setL/setS` | Update state | none | recompute pct/countdowns/snfCalc | n/a |
| Checklist item | toggle | `toggleCheck(id)` | Check/uncheck | none | updates compliancePct | n/a |
| + Add service | button | `addAuth` | Append auth row | none | new row | n/a |
| ⚡ Compliance report (top bar) | button | `generateReport` | Build prompt, call API, switch to report tab | `POST /api/cdph-compliance/analyze` | sets `report`/`genError` | disabled while `genLoading`; "Analyzing…" |
| Generate compliance report ↗ (in SNF tab) | button | `generateReport` | Same as above | same | — | n/a |
| ⬇ Download report | button | `downloadReport` | Builds bespoke self-contained HTML (own template, not report-export.js) and downloads | none | `.html` file `CDPH-Compliance-<initials>-<date>.html` | n/a |
| ↺ Re-analyze | button | `generateReport` | Re-run | same | — | n/a |

### Functions (client-side)
- **`callClaude(prompt)`** — POSTs `{prompt}`; throws on `!res.ok`, `!data.success`, or non-object `data.result`; returns `data.result`.
- **`generateReport()`** — assembles a CA-compliance prompt from patient/checklist/auth/livanta/snf state (embedding the target JSON schema), awaits `callClaude`, sets `report`, switches to `report` tab; catch sets `genError`; finally loading off.
- **`downloadReport()`** — serializes `report` into a hand-written HTML document (its own `esc()` + inline CSS) with score bar, context table, gaps/warnings/notes, attestation block, and an AI-assisted disclaimer; Blob download. (Does NOT use `ReportExport`.)
- **`snfCalc()`** — pure client logic for 3-day rule (no backend).
- **`Countdown`** — `setInterval` 30s ticking to a deadline; flags urgent < 24h.
- Helpers: `dateDiff`, `addDays`, `fmt`; presentational `StatusBadge`, `Field`, `Sel`.

### API interactions
- **Endpoint:** `POST /api/cdph-compliance/analyze` (`web_app.py → analyze_cdph_compliance`).
- **Request:** `{ "prompt": "<assembled CA compliance prompt>" }`.
- **Server:** `claude-sonnet-4-6`, `max_tokens=8000`, `temperature=0`. Special handling: if `response.stop_reason == "max_tokens"` returns a clear "report was cut off" error (500) instead of a parse error. Otherwise strips fences and `json.loads`; success → `{success:true, result}`; parse fail → `{success:false, error:"JSON parse failed: …", raw}`.
- **Output schema (requested/rendered):**
  ```
  { overall_status(compliant|at_risk|non_compliant), compliance_score(0-100),
    critical_gaps[{ issue, citation, action, urgency(immediate|today|before_dc) }],
    warnings[{ issue, recommendation }],
    california_specific_notes[],
    livanta_status, medi_cal_status, snf_status,
    attestation_ready(bool), attestation_blockers[] }
  ```

### States & feedback
- Loading: top-bar button "Analyzing…" with spinner; disabled.
- Error: `genError` (rendering location ⚠ NEEDS VERIFICATION beyond report tab; set via `setGenError`).
- Live countdowns turn red when < 24h or EXPIRED.

### End-user walkthrough
1. Open `/cdph-compliance`; confirm patient context strip.
2. Work the CDPH Checklist (watch % climb), Medi-Cal Auth rows, Commence Health QIO timeline (countdowns), and 3-Day SNF Rule.
3. Click **⚡ Compliance report** (or the in-tab button).
4. Review overall status/score, critical gaps (with CFR/CA citations), warnings, CA notes, attestation readiness.
5. Click **⬇ Download report** for a printable HTML.

### Edge cases & notes
- All checklist/auth/timeline/SNF state is client-only; nothing persists across reload.
- "Commence Health" is the QIO branding used in UI; backend prompt text references both "Commence Health QIO" and CMS BFCC-QIO concepts.
- Report download uses a separate template from the shared `report-export.js`.

---

## 5. HRRP Flagging (`/hrrp-flagging`)

- **File:** `static/hrrp-flagging.html`
- **Purpose:** Flags HRRP penalty conditions and TEAM bundle episodes from ICD-10 codes, computes financial exposure (client-side), drives condition-specific checklists, and generates an AI risk briefing via `/api/hrrp/generate`.
- **Access & preconditions:** Auth session; server `ANTHROPIC_API_KEY`. Rate limit 30/hour (`web_app.py → generate_hrrp_briefing`, line 1254).
- **Entry points:** Nav `HRRP`; route line 1150.
- **Layout overview:** Global `<header>`; ICD-10 code entry; HRRP/TEAM flag cards; financial-exposure panel; condition checklists; AI briefing panel with export.

### Sections / panels
- **Dx code entry** (`HRRPFlagging`, `dx` state, default `["I50.9","Z95.1"]`): text input + Add button; chips with remove buttons; quick-add buttons per condition.
- **Inputs:** `lace` (number, default 11), `payer` (default "medicare"), `annualDischarges` (420), `hospitalPenaltyPct` (1.4). LACE and ICD codes are clinical/PHI-adjacent; payer is PHI.
- **Flag detection (client-only):** `hrrpFlags` = `HRRP_CONDITIONS` whose `icd_prefix` matches any dx; `teamFlags` = `TEAM_EPISODES` matched by code prefix or linked `hrrp_id`.
- **Financials (client-only `financials` memo):** `hrrpPenaltyTotal` = Σ condition `penalty_per_readmit`; `teamExposure` = Σ (bundle_high − bundle_low); `hospitalAnnualRisk` = `annualDischarges × 12400 × penaltyPct/100`; `total` = hrrp + team.
- **Checklists:** items from each flagged condition's `checklist` (or the active condition); progress + critical counts computed client-side.
- **AI briefing panel:** renders `brief` (headline, insights, top priorities, CA note, FY2027 warning) once generated.

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Add code | button | `addCode(dxInput)` | Add ICD-10 chip | none | recompute flags/financials | n/a |
| Remove chip | button | `setDx(filter)` | Remove code | none | recompute | n/a |
| Quick-add condition | button | `addCode(c.icd_prefix[0])` | Seed a code | none | recompute | n/a |
| Condition card / list | button | `setActiveCondition(...)` | Focus a condition's checklist | none | — | n/a |
| Checklist items | toggle | `setChecked` | Mark complete | none | progress update | n/a |
| Generate briefing | button | `generateBrief` | Call AI | `POST /api/hrrp/generate` | sets `brief`/`briefErr` | disabled while `briefLoading` |
| ⬇ Download HTML | button | `downloadBrief` (builds via `buildBriefHtml(false)`) | Save bespoke briefing HTML | none | `.html` | n/a |
| 🖨 Save as PDF | button | `printBrief` (`buildBriefHtml(true)`) | Print briefing | none | print window | n/a |
| Add code (suggested codes) | button | `addCode(code)` | Add suggestion | none | recompute | n/a |

### Functions (client-side)
- **`callClaude(hrrpFlags, teamFlags, lace, exposure)`** — builds a briefing prompt (conditions, TEAM episodes, LACE, total exposure) with the JSON schema; POSTs `{prompt}`; throws on `!data.success`; returns `data.result`.
- **`generateBrief()`** (useCallback) — awaits `callClaude(...)`, sets `brief`; catch sets `briefErr`; manages `briefLoading`.
- **`buildBriefHtml(printMode)`** — hand-built self-contained HTML (own `esc()` + CSS) with headline, exposure box, context table, flagged conditions/TEAM lists, AI insights/priorities, disclaimer; optional auto-print script. (Separate from `report-export.js`.)
- Memos: `hrrpFlags`, `teamFlags`, `financials`. Helper `fmt$`.

### API interactions
- **Endpoint:** `POST /api/hrrp/generate` (`web_app.py → generate_hrrp_briefing`).
- **Request:** `{ "prompt": "<briefing prompt>" }`.
- **Server:** `claude-sonnet-4-6`, `max_tokens=1500`, `temperature=0`; strips fences; `{success:true, result}` or parse-fail 500.
- **Output schema (rendered):**
  ```
  { risk_headline, hrrp_insight, team_insight,
    top_discharge_priorities[{ priority, action, why }],
    california_specific, fy2027_warning }
  ```

### States & feedback
- Loading: Generate button busy.
- Error: `briefErr` shown near the briefing panel.
- Exposure numbers update live as codes/inputs change.

### End-user walkthrough
1. Open `/hrrp-flagging`; default codes seed CHF.
2. Add/remove ICD-10 codes; set LACE, payer, annual discharges, hospital penalty %.
3. Review flagged HRRP conditions, TEAM episodes, and computed exposure.
4. Work condition checklists.
5. Click **Generate briefing** → review AI headline, insights, priorities, CA note, FY2027 warning.
6. Download HTML / Save as PDF.

### Edge cases & notes
- All flagging/financials are deterministic client logic; the model only writes prose.
- `hospitalAnnualRisk` uses a fixed $12,400 average DRG constant.

---

## 6. ROI Tracker (`/roi-tracker`)

- **File:** `static/roi-tracker.html`
- **Purpose:** Outcomes & ROI workspace with dashboard/tracker/calculator/config tabs, a live "platform ROI" panel sourced from measured TCM claims, and an AI executive-summary generator via `/api/roi/generate`.
- **Access & preconditions:** Auth session; server `ANTHROPIC_API_KEY` (for the AI brief). Rate limit 30/hour (`web_app.py → generate_roi_summary`, line 1204).
- **Entry points:** Nav `ROI Estimates`; route line 1159. (Sibling `/roi-measured` is a separate, measured-data page — not documented here.)
- **Layout overview:** Global `<header>`; a "platform ROI" panel (`#platform-roi-body`) populated by an inline IIFE; a navy top bar with Download HTML / Save as PDF / AI executive summary; 4 tabs (`Dashboard`, `Rate tracker`, `ROI calculator`, `Hospital config`).

### Sections / panels
- **Platform ROI panel** (vanilla JS IIFE `loadPlatformRoi`): fetches `GET /api/tcm/platform-roi`; renders monthly/all-time TCM revenue, subscription cost, episodes completed, projections, ROI multiple, and a coverage-ratio badge ("Pays for itself" vs "Below cost"). On failure shows "Platform ROI data unavailable." Buttons: Export for CFO (`window.print()`), Share calculator link (`copyCalcLink`), Apply for pilot (`/pilot`).
- **Tabs** (`ROITracker`, `tab` state): `dashboard`, `tracker` (Rate tracker), `roi` (ROI calculator), `config` (Hospital config). Config holds `cfg` (hospital name, pilot months/start, rates, costs — used by metrics + AI brief).
- **AI executive summary:** `brief` state rendered after generation (headline, summary, key_stat).

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Tab buttons (×4) | button | `setTab(id)` | Switch tab | none | re-render | n/a |
| AI executive summary | button | `genBrief` | Build payload, call AI | `POST /api/roi/generate` | sets `brief`/`briefErr` | disabled while `briefLoad`; "Writing…" |
| ⬇ Download HTML | button | `ReportExport.download(..., ReportExport.capture("#root",{...}))` | Save whole-page report | none | `.html` | n/a |
| 🖨 Save as PDF | button | `ReportExport.print(ReportExport.capture("#root",{print:true}))` | Print report | none | print window | n/a |
| Export for CFO (platform panel) | button | `window.print()` | Browser print | none | print dialog | n/a |
| Share calculator link | button | `copyCalcLink(path)` | Copy `location.origin+path` to clipboard, alert | none | clipboard | n/a |
| Apply for pilot | link | href `/pilot` (new tab) | Navigate | none | — | n/a |

### Functions (client-side)
- **`loadPlatformRoi()`** (IIFE) — `fetch('/api/tcm/platform-roi',{cache:'no-store'})`; formats currency; sets coverage badge; injects HTML into `#platform-roi-body`; try/catch fallback message.
- **`copyCalcLink(path)`** — clipboard write + alert.
- **`callClaude(data)`** — builds an executive-summary prompt from metrics; POSTs `{prompt}`; throws on `!d.success`; returns `d.result`.
- **`genBrief()`** (useCallback) — packages `cfg` + computed `metrics` into the payload, awaits `callClaude`, sets `brief`; catch sets `briefErr`; manages `briefLoad`.
- Metrics computed client-side from `cfg` (the `metrics` memo — pilotDischarges, baseline/current rate, readmissionsPrevented, hrrpSavings, timeSavings, subCost, roiPct). Helpers `fmt$`, `fmtPct`.

### API interactions
- **Primary:** `POST /api/roi/generate` (`web_app.py → generate_roi_summary`). Request `{ "prompt": "<exec-summary prompt>" }`. Server: `claude-sonnet-4-6`, `max_tokens=800`, `temperature=0`; strips fences; `json.loads`; **augments** result with `disclaimer` ("AI-estimated projections, not measured outcomes…") and `measured_roi_url:"/roi-measured"`; returns `{success:true, result}`.
  - Output schema (rendered): `{ headline, summary, key_stat }` (+ server-added `disclaimer`, `measured_roi_url`).
- **Dashboard read:** `GET /api/tcm/platform-roi` (`web_app.py → ...` line 2711) — measured TCM/subscription/ROI figures: `{ monthly_tcm_revenue, alltime_tcm_revenue, subscription_monthly, completed_episodes, total_episodes, annual_projection_current, annual_net_current, annual_projection_50pct, annual_roi_current, coverage_ratio_monthly, calculator_share_url }`.
- **Other `/api/roi/*` endpoints exist** (`/api/roi/dashboard`, `/api/roi/outcomes`, `/api/roi/settings`, `/api/roi/export` — `web_app.py` lines 2352–2546) but are consumed by the **Measured ROI** page (`/roi-measured`), not by this tracker page (which only calls `/api/roi/generate` and `/api/tcm/platform-roi`).

### States & feedback
- AI button: "Writing…" + spinner while `briefLoad`.
- Platform panel: badge green ("Pays for itself") vs amber ("Below cost"); fallback text on error.
- Error: `briefErr` near brief output.

### End-user walkthrough
1. Open `/roi-tracker`; the platform-ROI panel auto-loads measured figures (or shows unavailable).
2. Switch tabs to view dashboard / rate tracker / calculator / hospital config; edit config.
3. Click **AI executive summary** → headline/summary/key stat (with projections disclaimer + link to measured ROI).
4. Download HTML / Save as PDF; or Export for CFO / Share calculator link.

### Edge cases & notes
- The AI brief is explicitly framed as estimated projections (server appends disclaimer + measured-ROI link).
- The dashboard data is the only DB-backed read on this page (depends on configured TCM claims; see Appendix B).

---

## 7. Readmission Tracker (`/readmission-tracker`)

- **File:** `static/readmission-tracker.html`
- **Purpose:** Local cohort tracker for 30/60/90-day readmissions with pre/post-adoption rate comparison, LACE display, filtering/sorting, and CSV export. **Fully client-side** — no AI/backend generate calls.
- **Access & preconditions:** Auth session only (page route line 1168). No `ANTHROPIC_API_KEY` needed.
- **Entry points:** Nav `Tracker`.
- **Layout overview:** Global `<header>`; tabs (`tracker`, plus dashboard-style views); a records table; add/edit form; cohort stats.

### Sections / panels
- **Records store:** `records` state loaded from `window.storage` (a **localStorage shim** defined inline at line 131) under `STORAGE_KEY`; falls back to the `SEED` array (20 synthetic patients `p001`–`p020`). Each record: `{ id, initials, mrn, admit, dc, condition, hrrp, lace, dest, app, r30/r30d, r60/r60d, r90/r90d, notes }`. All patient fields are **PHI** (stored only in the browser).
- **Add/Edit form** (`form` state via `blank()`): inputs Patient initials, MRN last 4, Admission date, Discharge date, LACE score (number), plus condition/destination/readmit flags. `submitForm` coerces `lace = parseInt||0`.
- **Records table:** columns Patient, DC Date, Condition, Destination, LACE, App, 30/60/90-day, Actions. **LACE display:** colored by threshold — `>=10` red (`#E24B4A`), `>=5` amber, else green; `0/empty` shows "—". This is the stored value, not recomputed.
- **30-day status** (`r30Status`): Readmitted / No readmit / "Nd left" (window open) / Overdue (>30d, still null).
- **Cohort stats** (`stats` memo, **client-only**): pre/post cohorts (split by `app` flag, HRRP, resolved r30), readmission rates, % reduction, per-condition before/after, open/overdue windows.

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Tab buttons | button | `setActiveTab` | Switch view | none | re-render | n/a |
| Add / form fields | input | `setF(k,v)` | Edit form | none | — | n/a |
| Save (submit) | button | `submitForm` | Add/update record → `updateRecords` → `save` to localStorage | none (localStorage) | table updates | `saving` flag |
| Edit row | button | `editRecord(rec)` | Load row into form | none | — | n/a |
| Delete row | button | `deleteRecord(id)` | `window.confirm` then remove | none | table updates | n/a |
| Mark 30/60/90 readmit | control | `markReadmit(id,field,val)` | Inline status update | none | persists to localStorage | n/a |
| Sort headers | button | `setSort` | Re-sort (dc/lace/cond) | none | — | n/a |
| Filters | controls | `setFilter` | Filter cohort | none | — | n/a |
| Export CSV | button | builds CSV string + download | Exports records | none | `.csv` download | n/a |

### Functions (client-side)
- **`window.storage`** — localStorage shim (`get`/`set`).
- **load `useEffect`** — reads `STORAGE_KEY`, parses to `records` or `SEED`; sets `loaded`.
- **`save(recs)`** / **`updateRecords(recs)`** — persist to localStorage.
- **`submitForm` / `editRecord` / `deleteRecord` / `markReadmit`** — CRUD over `records`.
- **`filtered`** (memo) — filter + sort. **`stats`** (memo) — cohort math.
- **`r30Status`, `daysSince`, helpers** — status rendering.
- **CSV export** — assembles header + rows, sanitizes commas in notes, triggers download.

### API interactions
- **None for data.** Only the shared `/api/me` auth check. **All readmission/LACE logic is client-only**; LACE is a manually entered/stored field with color thresholds (no LACE *scoring algorithm* here — contrast with screens that pass LACE to the model). No backend persistence — records live in browser localStorage.

### States & feedback
- "Loading records…" until `loaded`.
- `saving` flag during writes.
- Delete confirmation dialog.

### End-user walkthrough
1. Open `/readmission-tracker`; seeded with 20 synthetic records (or your saved set).
2. Add/edit records; mark 30/60/90-day readmission outcomes inline.
3. Filter/sort; review cohort pre/post adoption readmission rates and % reduction.
4. Export CSV.

### Edge cases & notes
- Data is browser-local only — not shared across devices/users and not on the server.
- "LACE scoring" here = display + thresholds, not a calculator. ⚠ The dashboard/rate-tracker tab labels were not all read line-by-line; tab IDs beyond `tracker` are present in `activeTab` but their exact set is ⚠ NEEDS VERIFICATION.

---

## 8. Multilingual Instructions (`/multilingual-prompt-system`)

- **File:** `static/multilingual-prompt-system.html`
- **Purpose:** Translates an English discharge plan (JSON or text) into one of 20 languages, rendering a bilingual side-by-side output with clinical-review flags. POSTs to `/api/multilingual/generate`.
- **Access & preconditions:** Auth session; server `ANTHROPIC_API_KEY`; target language must be in server `LANGUAGE_CONFIGS`. Rate limit 30/hour (`web_app.py → generate_multilingual_instructions`, line 3889).
- **Entry points:** Nav `Multilingual`; route line 1105.
- **Layout overview:** Global `<header>`; header card (Title VI / CA Gov Code 7290 / CDPH); input card (language selector + plan textarea + sample toggle + Translate); the bilingual `Output` component.

### Sections / panels
**Input card** (`App` component):
| Field | Label | Type | Required | Validation | Sample | PHI? |
|---|---|---|---|---|---|---|
| lang | Target Language | select (20 langs, RTL marked) | yes | must be in `LANGUAGE_CONFIGS` (server 400 otherwise) | Spanish | no |
| planText / SAMPLE_PLAN | English Discharge Plan (JSON or plain text) | textarea | **yes** | non-empty `.trim()`; else "Paste a discharge plan…" | `SAMPLE_PLAN` (synthetic HFrEF) | **yes** |
- **Conditional UI:** RTL note for `dir==="rtl"` languages (Farsi, Arabic); interpreter-recommendation note for `["ium","hmn","km"]`. "Use sample plan" toggles read-only sample.

**Output component** (`Output`, `BiRow`/`MedCard`/`WarnCard`): status bar (clinician-review-required / interpreter-recommended / review reasons + target language + generated time), then sections that render only when present: Patient Greeting, Diagnosis, Medications, Warning Signs, Activity/Diet/Wound, Follow-up Appointments, When to Call, Teach-back Prompt, Cultural adaptations (screen-only), Attestation.

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Target Language | select | `setLang` | Choose language | none | RTL/interpreter notes | n/a |
| Use sample plan / Clear sample | button | `setUseSample(v=>!v)` | Toggle sample | none | textarea read-only when sample | n/a |
| Plan textarea | textarea | `setPlanText` (clears sample) | Edit plan | none | — | n/a |
| Translate to `<lang>` | button | `generate` | Validate, POST | `POST /api/multilingual/generate` | sets `result`/`error` | disabled while `loading`; "Translating…" |
| ⬇ Download HTML | button | `ReportExport.download(..., ReportExport.capture("#dp-report",{...}))` | Save bilingual report | none | `.html` | shown only when `result` |
| 🖨 Save as PDF | button | `ReportExport.print(ReportExport.capture("#dp-report",{print:true}))` | Print | none | print window | shown only when `result` |

### Functions (client-side)
- **`generate()`** — picks sample-or-typed text, guards empty, POSTs `{target_language, discharge_plan}`; on `!res.ok || !data.success` sets `error=data.error`; else sets `result`; network catch → "Network error — please try again."; finally loading off.
- **Presentational:** `BiRow` (English-source / translation two-column; honors `dir`), `MedCard` (preserves `name`/`dose`/`frequency`; source vs translated instruction; `why`), `WarnCard` (urgency badge emergent/urgent/routine; `source_sign` vs `sign`; `action_text` in `dir`), `Output`, `Spinner`, `badge()`.

### API interactions
- **Endpoint:** `POST /api/multilingual/generate` (`web_app.py → generate_multilingual_instructions`).
- **Request:** `{ "target_language": "<code>", "discharge_plan": "<English JSON/text>" }`.
- **Server:** validates language (400 with `supported` list if unknown) and non-empty plan; builds language-specific system prompt (`build_multilingual_system_prompt`); `claude-sonnet-4-6`, `max_tokens=4096`, `temperature=0`; strips fences; `json.loads`; then **`validate_translation(source_plan, result, lang_config)`** post-processes (e.g. interpreter/review flags). Returns `{ success, translation, language, direction, interpreter_recommended, requires_review }`.
- **Bilingual output schema (rendered as `data.translation`):**
  ```
  meta { requires_clinician_review(bool), interpreter_recommended(bool), review_reasons[],
         target_language_name, generated_at, cultural_adaptations[] }
  patient_header { source_greeting, greeting }
  diagnosis { source_content, content }
  medications[] { name, name_display?, dose, frequency, why, source_instruction, instruction }
  warning_signs[] { source_sign, sign, urgency(emergent|urgent|routine), action_text }
  activity_restrictions { source_content, content }
  diet_instructions { source_content, content }
  wound_care { source_content, content }
  follow_up { appointments[{ provider, timeframe, source_instruction, instruction }] }
  when_to_call { er_instruction, emergency_instruction }
  teach_back_prompt
  attestation
  ```
  Top-level response wrapper: `{ success, translation, language, direction(ltr|rtl), interpreter_recommended, requires_review }`.

### States & feedback
- Loading: "Translating…" + spinner; disabled.
- Error: red box (validation/server/network).
- Status bar: review-required (red) vs no-flags (green), interpreter-recommended (amber), review reasons listed.
- RTL output gets `dir="rtl"` applied automatically.

### End-user walkthrough
1. Open `/multilingual-prompt-system`; pick a target language.
2. Paste an English discharge plan (JSON or text), or click **Use sample plan**.
3. Click **Translate to `<language>`**.
4. Review the bilingual side-by-side output and the clinician-review/interpreter status bar.
5. Download HTML / Save as PDF.

### Edge cases & notes
- Drug names/doses are preserved (per prompt rules); warning-sign urgency is mirrored.
- Unsupported language returns 400 with a `supported` list (UI shows `data.error`).
- Some languages auto-flag interpreter recommendation (Mien, Hmong, Khmer in UI hint; final flags come from server `validate_translation`).

---

## 9. IMM Compliance Module (`/imm-prompt-system`)

- **File:** `static/imm-prompt-system.html`
- **Purpose:** **Reference/documentation module** for the IMM (Important Message from Medicare) delivery/re-delivery/appeal workflow. Displays the IMM system prompt, delivery-log prompt, re-delivery check, appeal workflow, an API+DB schema example, and compliance rules — with copy buttons. **No live generation call.**
- **Access & preconditions:** Auth session only (route line 1096). No `ANTHROPIC_API_KEY` used by the page (no backend generate route exists for IMM).
- **Entry points:** Nav `IMM` / `IMM Module`.
- **Layout overview:** Dark module header (CMS §482.13(e) / CDPH / Commence Health BFCC-QIO; timing chips 2 days / 2 days / 24 hrs / Commence Health phone); dark tab bar (6 tabs); content pane with a per-tab Copy button; the `integration` tab adds an `API route` / `DB schema` sub-toggle.

### Sections / panels / tabs
- **Tabs** (`IMMPromptSystem`, `tabs` array): `System prompt`, `Delivery log prompt`, `Re-delivery check`, `Appeal workflow`, `API + DB schema` (integration), `Compliance rules`.
- **IMM workflow timing (header chips):** initial delivery window 2 days; re-delivery before DC 2 days; patient appeal window 24 hrs; QIO = Commence Health (1-877-588-1123).
- **Content:** read-only prompt/code text (`CONTENT[activeTab]`, or `INTEGRATION_CODE` / `DB_SCHEMA` for integration). Contextual callouts: delivery tab (20 template variables), re-delivery (run as 6-hour cron; escalate at 24h), appeal (discharge hold active on filing; call Commence Health before any discharge action). Rules tab renders compliance-rule cards.

### Clickable elements

| Element | Type | JS handler/action | What it does | Backend call(s) | Result/next state | Disabled/loading |
|---|---|---|---|---|---|---|
| Tab buttons (×6) | button | `setActiveTab(t.id)` | Switch content | none | re-render | n/a |
| API route / DB schema | button | `setDbView(v)` | Toggle integration view | none | shows INTEGRATION_CODE vs DB_SCHEMA | n/a |
| Copy | button | `copy(getContent(), activeTab)` | Clipboard write of current content | none | "✓ Copied" 2s | n/a |

### Functions (client-side)
- **`copy(text,id)`** — clipboard write + 2s toast.
- **`getContent()`** — returns `INTEGRATION_CODE`/`DB_SCHEMA` for the integration tab (per `dbView`), else `CONTENT[activeTab]`.
- **`getFilename()`** — maps tab to a display filename for the code panel.

### API interactions / Anthropic usage
- **No live API call from this page.** The auth check (`/api/me`) is the only fetch. The `INTEGRATION_CODE` string **displays** a sample Next.js route that calls `https://api.anthropic.com/v1/messages` directly (server-side, with `process.env`), but this is **documentation text, not executed** — and there is **no `/api/imm/generate` backend route** in `web_app.py`. So: the IMM module does **not** call Anthropic from the client, and unlike the other generators it has **no backend generate endpoint** at all; it is a static prompt/spec reference.
- **IMM workflow documented (from displayed prompts/schema):** delivery logging (append-only `imm_delivery_logs`), re-delivery gap detection vs prior IMM history, 24-hour appeal window with discharge hold, financial-liability notice (HINN) guidance, alerts (critical/warning). Output schema shown in the page includes blocks like `financial_liability_notice`, `documentation_required[]`, `alerts[{severity,message,action}]`.

### States & feedback
- Copy toast ("✓ Copied").
- No loading/error states (no network generation).

### End-user walkthrough
1. Open `/imm-prompt-system`.
2. Read the timing chips (2/2 days, 24-hr appeal, Commence Health number).
3. Browse tabs (System / Delivery / Re-delivery / Appeal / API+DB / Rules); use the API route ↔ DB schema toggle on the integration tab.
4. Click **Copy** to grab any prompt/snippet for implementation.

### Edge cases & notes
- This is the only screen of the nine with no live AI generation — it is a build/reference spec.
- The displayed integration code references `claude-sonnet-4-20250514` (illustrative) whereas the live generator routes use `claude-sonnet-4-6`; treat page snippets as reference, not the deployed config.

---

## Appendix A — Shared elements (global nav, disclaimer, export)

- **Global nav bar:** each page's `<header>` (blue gradient) links to My Patients, Planner, and every tool (Summary, Teach-back, CDPH, HRRP, ROI Estimates, ROI Measured ★, Tracker, IMM, Multilingual, Facilities, Predict LOS, TCM Calculator) and `Sign Out` → `/api/auth/logout`. The current page may mark its link `active` (e.g. multilingual).
- **Auth gate:** inline `fetch('/api/me')` → redirect `/login` on failure (all nine pages).
- **Clinician-review disclaimer:** `static/report-export.js` injects a default disclaimer into every export: *"AI-assisted decision support — estimates and drafts only. Verify all content and confirm clinical actions with the care team before use."* CDPH and HRRP build their own export templates with equivalent disclaimers. The global planner page carries a `⚠ DRAFT — Clinical decision support only.` banner (`web_app.py` line 2018).
- **Report export (`static/report-export.js → window.ReportExport`):** `buildDoc`, `capture(node, opts)` (clones a region, strips `button/input/select/textarea/[data-export-skip]/.no-print`, inlines page styles), `download(filename, html)`, `print(html)` (opens a window; warns if pop-ups blocked), helpers `esc/table/section/box/list`, `dateStamp`. Used by Summary Generator (#1), Discharge Summary (#2), Teach-back (#3), ROI Tracker (#6), Multilingual (#8). CDPH (#4) and HRRP (#5) ship bespoke export templates instead.

## Appendix B — FILE vs DB modes

- **Mode selector:** `web_app.py` line 396 — `DATABASE_URL = os.getenv("POSTGRES_URL") or os.getenv("DATABASE_URL")`. When set → DB mode (Postgres-backed patients, plan runs, TCM episodes, ROI outcomes); when unset → FILE/dev mode (e.g. `register_user` file path, `DEFAULT_ORG_ID` stub).
- **Generator endpoints (#1, #2, #3, #4, #5, #8):** stateless — they call Anthropic and return JSON. They do **not** read or write the patient DB and behave identically in FILE and DB modes (subject to `ANTHROPIC_API_KEY`). No request/response persistence found in the route bodies.
- **ROI Tracker (#6):** the platform-ROI panel and `/api/roi/*` reads are DB-backed (TCM claims / outcomes). In FILE mode these return stubs/empty (e.g. `/api/roi/dashboard` returns empty `clinician_breakdown`), so the panel shows "Platform ROI data unavailable."
- **Readmission Tracker (#7):** neither FILE nor DB server storage — purely browser **localStorage** (`window.storage` shim). Independent of `DATABASE_URL`.
- **IMM Module (#9):** no storage, no generate route — static reference regardless of mode.

## Open Questions

1. **Audit logging of PHI:** generate routes don't persist bodies, but request middleware sets `request.state.audit_mrn` on the planner path. ⚠ NEEDS VERIFICATION whether the audit layer logs full request/response bodies for the generator endpoints (PHI exposure risk).
2. **Teach-back / CDPH state persistence:** responses, notes, and attestations on Teach-back (#3) and all CDPH (#4) checklist/timeline state appear client-only with no save endpoint. ⚠ Confirm there is no intended server persistence/audit of completed teach-back or compliance records.
3. **CDPH error surfacing:** `setGenError` is set on failure, but the on-screen render location for `genError` outside the report tab was not fully traced. ⚠ NEEDS VERIFICATION.
4. **Readmission Tracker tab set:** `activeTab` supports more than `tracker` (dashboard-style views), but the full tab ID list / dashboard layout was not read line-by-line. ⚠ NEEDS VERIFICATION.
5. **`q.is_high_alert` in Teach-back:** rendered by `QuestionCard` but absent from the documented output schema — relies on the model emitting it. ⚠ Confirm whether the server prompt requests this field.
6. **Schema drift (page constants vs live prompts):** Summary Generator (#1) page schema constants and IMM (#9) integration snippet reference `claude-sonnet-4-20250514`, while live routes use `claude-sonnet-4-6`. Page-displayed schemas are reference material and may differ slightly from the live server prompts.
