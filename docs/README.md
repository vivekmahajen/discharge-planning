# Discharge Planning AI — Documentation

Complete end‑user and technical documentation for **Discharge Planning AI**, a multi‑agent
hospital discharge‑planning web application (FastAPI backend serving static HTML screens,
Anthropic agent orchestration, optional PostgreSQL, SMART‑on‑FHIR).

> **Grounding & accuracy.** Every behavioral claim in these docs is traceable to a source
> file (`file → function/route`). Items that could not be verified from source are marked
> `⚠ NEEDS VERIFICATION` and collected in each document's *Open Questions* section (summarized
> at the bottom of this page).
>
> **PHI.** This app handles Protected Health Information. All examples use **synthetic data only**.

---

## Table of contents

| Doc | Part | Contents |
|-----|------|----------|
| [00-overview.md](./00-overview.md) | Part 1 — Global/System | Product overview, architecture (diagram), the multi‑agent pipeline, runtime modes, auth & sessions, roles, multi‑tenancy, rate limiting & AI budget, HIPAA audit logging, configuration reference, deployment, glossary |
| [screens-core.md](./screens-core.md) | Part 2 — Screens (core) | Global nav bar, Login, Discharge Plan Builder, My Patients, Patient Detail, Predictive Discharge, Provider Directory, Settings, Run Export, and auxiliary screens |
| [screens-tools.md](./screens-tools.md) | Part 2 — Screens (generators) | Summary, Discharge Summary, Teach‑back, CDPH, HRRP, ROI Tracker, Readmission Tracker, Multilingual, IMM |
| [features.md](./features.md) | Part 3 — Features | Every delivered capability (AI plan generation, predictive LOS, persistence, directory, eligibility, doc generators, TCM, FHIR, onboarding, security, report export) |
| [api-reference.md](./api-reference.md) | Part 4 — API | All 116 `web_app.py` routes grouped by area + the plan SSE event table |
| [data-model.md](./data-model.md) | Part 5 — Data model | Tables, columns, relationships, indexes, status/TCM state machines, ERD |

---

## Quick Start for End Users

1. **Sign in** at `/login` (or create an account on the Sign‑up tab; your organization is derived
   from your email domain).
2. You land on the **Discharge Plan Builder** (`/`). Either click **⚡ Load Sample Patient** to try it,
   or fill the 7 intake tabs (Demographics → Diagnoses → Insurance → Medications → Therapy →
   Social History → Goals). Enter the **MRN** if you want the plan saved to a patient record.
3. *(Optional)* Click **Quick Eligibility Check** to verify insurance, and connect an EHR with
   **Import from EHR** to auto‑populate from a patient's chart.
4. Click **Generate Plan**. Six specialist AI agents run in parallel and a coordinator
   synthesizes the **Discharge Plan — AI Draft**, with a predicted length‑of‑stay banner.
5. **Copy**, **Print/PDF**, or start a **New Patient**. Saved plans appear under **My Patients**;
   open one to see **Patient Detail** (plan history, clinical notes, status).
6. Use the top **nav bar** for the specialized tools (Directory, Predictive Discharge, Summary,
   Teach‑back, CDPH, HRRP, ROI, Multilingual, IMM, Readmission, Settings).

> **Every AI output is a draft.** A bold banner on every screen states: *"Multi‑Agent Clinical
> Decision Support · All outputs require clinician review before action."*

---

## Runtime modes (feature availability)

The app runs in one of two modes depending on whether a PostgreSQL connection is configured
(`DATABASE_URL`/`POSTGRES_URL`). See [00-overview.md §1.4](./00-overview.md).

| Capability | FILE mode (no DB) | DB mode |
|---|---|---|
| Login / signup | ✅ (local JSON user file) | ✅ (Postgres) |
| AI plan generation & all doc generators | ✅ | ✅ |
| Predictive LOS | ✅ | ✅ |
| Patient records / history / notes / export | ❌ (503) | ✅ |
| Post‑acute directory | ❌ (empty/503) | ✅ |
| TCM module | ❌ (503) | ✅ |
| Eligibility caching | ❌ (computed, uncached) | ✅ |
| Multi‑tenancy / org isolation | single local user | ✅ |

## Roles

Roles enforced via `require_role` (see [00-overview.md §1.6](./00-overview.md)). **Note:** the actual
role identifiers in source are **`clinician`** (default), **`org_admin`**, **`super_admin`**, and a
schema‑defined **`read_only`** (currently not enforced by any route).

---

## Coverage checklist

**Screens — 21/21** (all `static/*.html` served by a route):

Login ✅ · Discharge Plan Builder ✅ · My Patients ✅ · Patient Detail ✅ · Predictive Discharge ✅ ·
Post‑Acute Directory ✅ · Settings ✅ · Run Export (printable) ✅ · Ward Barriers ✅ · Ward Referrals ✅ ·
ROI Measured ✅ · Pilot ✅ · TCM ROI Calculator ✅ · Offline ✅ *(screens-core.md)*
— Summary Generator ✅ · Discharge Summary Generator ✅ · Teach‑back ✅ · CDPH Compliance ✅ ·
HRRP Flagging ✅ · ROI Tracker ✅ · Readmission Tracker ✅ · Multilingual ✅ · IMM ✅ *(screens-tools.md)*

**API — 116/116 routes** documented in [api-reference.md](./api-reference.md) (authoritative count from
`grep -cE '@app\.(get|post|patch|put|delete)\(' web_app.py`; no sub‑routers).

**Agents — 9/9** in [00-overview.md §1.3](./00-overview.md): clinical_assessment, care_needs,
insurance_authorization, medication_reconciliation, social_determinants, predictive_los,
coordinator, barrier_extraction, base_agent.

**Migrations — 5/5** in [data-model.md](./data-model.md): 001_multi_tenant_base, 002_migrate_existing_users,
003_audit_log_mrn_email, 004_sso_users, tcm_module.

---

## Consolidated Open Questions / NEEDS VERIFICATION

Each document carries its own list; the most material items surfaced during documentation:

- **In‑process state on serverless.** Login lockout counters and the "global" hourly AI‑budget
  counter are in‑process dicts — **per‑instance**, not cluster‑wide, despite docstrings implying
  global scope. (00-overview, features)
- **Model vs. temperature.** Agents pin `claude-sonnet-4-6` with a `temperature` set; documented
  as‑is. (00-overview, features)
- **`read_only` role** exists in the schema enum but no route enforces it. (00-overview)
- **IMM module is client‑side only** — no backend generation route; the `api.anthropic.com`
  reference is inside displayed sample code. (screens-tools)
- **Readmission Tracker is entirely client‑side** (localStorage); its "LACE" is a stored field with
  color thresholds, not a calculator. (screens-tools)
- **HRRP follow‑up cadence** is enforced server‑side only on `/api/summary/generate`, not on
  `/api/discharge-summary/generate`. (screens-tools)
- **TCM SSE events** (`tcm_episode_created`/`tcm_not_applicable`) are emitted but have no handler
  case in `index.html → handleEvent()` (silently ignored). (screens-core)
- **Offline page link** uses `/patient/{id}` (singular) vs the real `/patients/{id}` (plural). (screens-core)
- **Org isolation mechanism is mixed** — base/TCM tables use PostgreSQL RLS; clinical tables
  (patients, milestones, referrals, ROI) isolate via `org_domain` string filtering. (data-model)
- **Two `users` definitions coexist** — org‑scoped (migration 001) vs a flat table
  (`web_app.py → _ensure_table`). (00-overview, data-model)
- Several routes (all TCM, onboarding/admin/superadmin, eligibility/check, a few directory/FHIR)
  have **no static‑HTML caller** — external/cron clients or not‑yet‑built UI. (api-reference)

---

*Generated from source at branch `claude/clever-einstein-KpYDO`. Verify against the live source as the app evolves.*
