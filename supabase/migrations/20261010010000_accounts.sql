-- Accounts and access (Phase 2).
-- profiles: LeadPilot role for each Supabase Auth user. api_keys: hashed ingestion keys.
-- Neither is a projection: they are never rebuilt from raw_events and never cleared by demo resets.

CREATE TABLE IF NOT EXISTS profiles (
    user_id VARCHAR NOT NULL,
    email VARCHAR,
    name VARCHAR,
    role VARCHAR NOT NULL,
    rep_id VARCHAR,
    team_rep_ids JSONB,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    last_seen_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (user_id),
    CONSTRAINT profiles_role_check CHECK (role IN ('admin', 'manager', 'rep', 'pending'))
);
CREATE INDEX IF NOT EXISTS ix_profiles_email ON profiles (email);

CREATE TABLE IF NOT EXISTS api_keys (
    id VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    prefix VARCHAR NOT NULL,
    key_hash VARCHAR NOT NULL,
    created_by VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    UNIQUE (key_hash)
);

ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
