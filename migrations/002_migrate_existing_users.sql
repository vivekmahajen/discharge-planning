-- Migration 002: Migrate existing flat users to multi-tenant schema
-- Creates a default "Original Users" organization and migrates any existing
-- users from the old flat users table (if present) into the new schema.

-- Create the default organization for pre-migration users
INSERT INTO organizations (id, name, slug, plan)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'Original Users',
    'original-users',
    'standard'
)
ON CONFLICT (id) DO NOTHING;

-- Migrate existing rows from the old flat users table (if it exists and has
-- the old schema: email, salt, hash, created_at with no organization_id column)
DO $$
BEGIN
    IF EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'users'
          AND column_name = 'email'
          AND table_schema = 'public'
    ) AND NOT EXISTS (
        SELECT FROM information_schema.columns
        WHERE table_name = 'users'
          AND column_name = 'organization_id'
          AND table_schema = 'public'
    ) THEN
        -- Old flat users table exists without organization_id — migrate rows
        INSERT INTO users (organization_id, email, salt, hash, role, created_at)
        SELECT
            '00000000-0000-0000-0000-000000000001'::uuid,
            old.email,
            old.salt,
            old.hash,
            'clinician',
            COALESCE(old.created_at, NOW())
        FROM users old
        ON CONFLICT (organization_id, email) DO NOTHING;

        -- Drop old table after migration
        DROP TABLE IF EXISTS users_old;
    END IF;
END
$$;
