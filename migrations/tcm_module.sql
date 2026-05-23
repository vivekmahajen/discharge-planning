-- migrations/tcm_module.sql
-- TCM episode tracking, contact log, face-to-face visits, and claim generation.
-- All tables have RLS policies enforcing org-level isolation.
-- HIPAA 45 CFR 164.312(a)(1) / CMS TCM MLN Fact Sheet / MCPM Ch. 12 Sec. 30.6

CREATE TABLE IF NOT EXISTS tcm_episodes (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    patient_mrn             TEXT NOT NULL,
    patient_name            TEXT NOT NULL,
    patient_dob             DATE,
    patient_medicare_id     TEXT,
    discharge_date          DATE NOT NULL,
    discharge_setting       TEXT NOT NULL,
    -- inpatient_hospital | snf | irf | ltch | observation | partial_hospitalization
    admitting_diagnosis     TEXT NOT NULL DEFAULT 'Not provided',
    discharge_diagnosis     TEXT NOT NULL,
    attending_provider_npi  TEXT NOT NULL,
    attending_provider_name TEXT NOT NULL,
    practice_tin            TEXT,
    practice_npi            TEXT,
    -- MDM assessment
    mdm_complexity          TEXT,            -- moderate | high | not_eligible
    mdm_rationale           TEXT,            -- AI narrative citing CMS criteria
    mdm_rationale_json      TEXT,            -- Full MDM assessment JSON
    mdm_assessed_by         TEXT DEFAULT 'ai_assisted',
    -- CPT determination
    recommended_cpt         TEXT,            -- 99495 | 99496 | not_eligible
    cpt_override            TEXT,            -- clinician override
    cpt_final               TEXT GENERATED ALWAYS AS (COALESCE(cpt_override, recommended_cpt)) STORED,
    -- Status
    status                  TEXT NOT NULL DEFAULT 'pending_contact',
    -- pending_contact | contact_overdue | contact_completed | visit_scheduled
    -- | visit_overdue | visit_completed | claim_ready | claim_submitted
    -- | claim_paid | claim_denied | not_eligible
    created_by              UUID REFERENCES users(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tcm_contacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id      UUID NOT NULL REFERENCES tcm_episodes(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    contact_date    DATE NOT NULL,
    contact_time    TIME NOT NULL,
    contact_method  TEXT NOT NULL,   -- phone | video | in_person
    contact_result  TEXT NOT NULL,   -- reached | left_voicemail | no_answer | patient_declined
    contacted_by    TEXT NOT NULL,
    contacted_by_id UUID REFERENCES users(id),
    notes           TEXT,
    is_qualifying   BOOLEAN GENERATED ALWAYS AS (contact_result = 'reached') STORED,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tcm_visits (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id      UUID NOT NULL REFERENCES tcm_episodes(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL,
    visit_date      DATE NOT NULL,
    visit_type      TEXT NOT NULL,   -- office | telehealth | home
    provider_npi    TEXT NOT NULL,
    provider_name   TEXT NOT NULL,
    visit_notes     TEXT,
    time_spent_mins INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tcm_claims (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id              UUID NOT NULL REFERENCES tcm_episodes(id) ON DELETE CASCADE,
    organization_id         UUID NOT NULL,
    cpt_code                TEXT NOT NULL,
    icd10_primary           TEXT NOT NULL,
    icd10_additional        TEXT[],
    service_date            DATE NOT NULL,
    date_of_discharge       DATE NOT NULL,
    place_of_service        TEXT NOT NULL DEFAULT '11',
    rendering_provider_npi  TEXT NOT NULL,
    billing_provider_npi    TEXT NOT NULL,
    billing_provider_tin    TEXT NOT NULL,
    claim_status            TEXT NOT NULL DEFAULT 'draft',
    submitted_at            TIMESTAMPTZ,
    payer_id                TEXT,
    claim_amount            NUMERIC(10,2),
    paid_amount             NUMERIC(10,2),
    denial_reason           TEXT,
    audit_trail             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tcm_episodes_org
    ON tcm_episodes(organization_id);
CREATE INDEX IF NOT EXISTS idx_tcm_episodes_mrn
    ON tcm_episodes(organization_id, patient_mrn);
CREATE INDEX IF NOT EXISTS idx_tcm_episodes_status
    ON tcm_episodes(organization_id, status);
CREATE INDEX IF NOT EXISTS idx_tcm_episodes_discharge
    ON tcm_episodes(discharge_date);
CREATE INDEX IF NOT EXISTS idx_tcm_contacts_episode
    ON tcm_contacts(episode_id);
CREATE INDEX IF NOT EXISTS idx_tcm_visits_episode
    ON tcm_visits(episode_id);
CREATE INDEX IF NOT EXISTS idx_tcm_claims_episode
    ON tcm_claims(episode_id);

-- Grant app_user access
GRANT SELECT, INSERT, UPDATE, DELETE ON tcm_episodes TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tcm_contacts TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tcm_visits   TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tcm_claims   TO app_user;

-- Row-Level Security
ALTER TABLE tcm_episodes ENABLE ROW LEVEL SECURITY;
ALTER TABLE tcm_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tcm_visits   ENABLE ROW LEVEL SECURITY;
ALTER TABLE tcm_claims   ENABLE ROW LEVEL SECURITY;

ALTER TABLE tcm_episodes FORCE ROW LEVEL SECURITY;
ALTER TABLE tcm_contacts FORCE ROW LEVEL SECURITY;
ALTER TABLE tcm_visits   FORCE ROW LEVEL SECURITY;
ALTER TABLE tcm_claims   FORCE ROW LEVEL SECURITY;

CREATE POLICY tcm_episodes_isolation ON tcm_episodes FOR ALL TO app_user
    USING (organization_id = current_setting('app.current_org_id', TRUE)::uuid);
CREATE POLICY tcm_contacts_isolation ON tcm_contacts FOR ALL TO app_user
    USING (organization_id = current_setting('app.current_org_id', TRUE)::uuid);
CREATE POLICY tcm_visits_isolation ON tcm_visits FOR ALL TO app_user
    USING (organization_id = current_setting('app.current_org_id', TRUE)::uuid);
CREATE POLICY tcm_claims_isolation ON tcm_claims FOR ALL TO app_user
    USING (organization_id = current_setting('app.current_org_id', TRUE)::uuid);
