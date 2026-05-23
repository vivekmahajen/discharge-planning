-- Migration 001: Multi-tenant base schema
-- Creates organizations, users (with org scoping), invitations,
-- discharge_plans, and audit_log tables with PostgreSQL Row-Level Security.
--
-- HIPAA 45 CFR 164.312(a)(1) — Access control
-- ONC 170.315(g)(10) — Multi-hospital SaaS per-org isolation

-- ── Role for application queries ─────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user;
    END IF;
END
$$;

-- ── Extension ────────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Organizations ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS organizations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    domain          TEXT,                          -- optional SSO email domain
    plan            TEXT NOT NULL DEFAULT 'trial', -- trial | standard | enterprise
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Users ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    salt            TEXT NOT NULL,
    hash            TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'clinician',
    -- role: super_admin | org_admin | clinician | read_only
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ,
    deleted_at      TIMESTAMPTZ,                   -- soft delete
    UNIQUE (organization_id, email)
);

CREATE INDEX IF NOT EXISTS users_org_email ON users (organization_id, email);

-- ── Invitations ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS invitations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email           TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'clinician',
    token           TEXT NOT NULL UNIQUE,
    invited_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '7 days',
    accepted_at     TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS invitations_token ON invitations (token);
CREATE INDEX IF NOT EXISTS invitations_org ON invitations (organization_id);

-- ── Discharge plans ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS discharge_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    created_by      UUID REFERENCES users(id),
    patient_mrn     TEXT,                          -- hashed or de-identified at app layer
    plan_json       JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ                    -- soft delete
);

CREATE INDEX IF NOT EXISTS discharge_plans_org ON discharge_plans (organization_id);

-- ── Audit log ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    organization_id UUID REFERENCES organizations(id),
    user_id         UUID REFERENCES users(id),
    user_hash       TEXT,                          -- HMAC of email for HIPAA-safe logging
    endpoint        TEXT,
    method          TEXT,
    status          INT,
    ip              TEXT,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audit_log_org_ts ON audit_log (organization_id, ts DESC);

-- ── Grant app_user read/write on tenant tables ────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON organizations    TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON users            TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON invitations      TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON discharge_plans  TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON audit_log        TO app_user;
GRANT USAGE, SELECT ON SEQUENCE audit_log_id_seq         TO app_user;

-- ── Row-Level Security ────────────────────────────────────────────────────────
-- All tenant tables enforce org isolation at the database layer.
-- The application sets: SET LOCAL app.current_org_id = '<uuid>' inside each txn.
-- Even if application code has a bug, the DB rejects cross-tenant queries.

ALTER TABLE users            ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations      ENABLE ROW LEVEL SECURITY;
ALTER TABLE discharge_plans  ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log        ENABLE ROW LEVEL SECURITY;

-- Users: each org sees only its own rows
CREATE POLICY users_org_isolation ON users
    USING (organization_id = current_setting('app.current_org_id', TRUE)::uuid);

-- Invitations: each org sees only its own invitations
CREATE POLICY invitations_org_isolation ON invitations
    USING (organization_id = current_setting('app.current_org_id', TRUE)::uuid);

-- Discharge plans: each org sees only its own plans
CREATE POLICY discharge_plans_org_isolation ON discharge_plans
    USING (organization_id = current_setting('app.current_org_id', TRUE)::uuid);

-- Audit log: each org sees only its own audit entries
CREATE POLICY audit_log_org_isolation ON audit_log
    USING (
        organization_id IS NULL
        OR organization_id = current_setting('app.current_org_id', TRUE)::uuid
    );

-- Superadmin bypass: app connects as superuser to read across orgs
-- Application code uses a separate superadmin connection that bypasses RLS.
