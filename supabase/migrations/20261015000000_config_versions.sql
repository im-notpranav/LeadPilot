-- Settings console (Phase 5). Rule changes are stored as versions on top of backend/config/*.yaml: each row holds
-- only what differs from the YAML defaults. Exactly one version is active; activating one replays the event log.
-- Every processed event and score change records the version that produced it.

CREATE TABLE IF NOT EXISTS config_versions (
    id INTEGER NOT NULL,
    note TEXT,
    overrides JSONB NOT NULL,
    fingerprint VARCHAR,
    status VARCHAR NOT NULL,
    restored_from INTEGER,
    created_by VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    activated_by VARCHAR,
    activated_at TIMESTAMP WITH TIME ZONE,
    retired_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_config_versions_status ON config_versions (status);

ALTER TABLE events ADD COLUMN IF NOT EXISTS config_version INTEGER;
ALTER TABLE score_changes ADD COLUMN IF NOT EXISTS config_version INTEGER;

ALTER TABLE config_versions ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
