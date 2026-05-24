-- HIPAA audit log: add user_email and mrn columns
-- user_email replaces the unusable user_hash for real audit trails
-- mrn links each access event to the specific patient record touched

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_email TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS mrn       TEXT;

-- Fast lookup by user (compliance queries: "show all accesses by user X")
CREATE INDEX IF NOT EXISTS audit_log_user_email ON audit_log (user_email, ts DESC);

-- Fast lookup by patient MRN (breach notification: "who accessed patient Y?")
CREATE INDEX IF NOT EXISTS audit_log_mrn ON audit_log (mrn, ts DESC);
