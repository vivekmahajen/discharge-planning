-- Migration 004: SSO user support
-- Makes password fields nullable so Auth0/SAML users don't need a local password.
-- Adds sso_provider to track the identity provider (auth0, okta, azure_ad, etc.)

ALTER TABLE users ALTER COLUMN salt DROP NOT NULL;
ALTER TABLE users ALTER COLUMN hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sso_provider TEXT;

-- Cross-org email index for SSO login (no org_id known at login time)
CREATE INDEX IF NOT EXISTS users_email_global ON users (email) WHERE deleted_at IS NULL;
