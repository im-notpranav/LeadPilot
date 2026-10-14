-- Connectors (Phase 3): signed webhooks, form / CRM / inbound-email hooks and the website tracker.
-- Like profiles and api_keys these are not projections: never rebuilt from raw_events, never cleared by resets.

CREATE TABLE IF NOT EXISTS connectors (
    id VARCHAR NOT NULL,
    kind VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    source VARCHAR,
    secret VARCHAR NOT NULL,
    settings JSONB,
    created_by VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    last_received_at TIMESTAMP WITH TIME ZONE,
    received_count INTEGER,
    revoked_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    UNIQUE (secret),
    CONSTRAINT connectors_kind_check CHECK (kind IN ('webhook', 'form', 'crm', 'email', 'tracker'))
);

CREATE TABLE IF NOT EXISTS connector_deliveries (
    id VARCHAR NOT NULL,
    connector_id VARCHAR,
    received_at TIMESTAMP WITH TIME ZONE,
    status VARCHAR,
    http_status INTEGER,
    reason TEXT,
    events INTEGER,
    results JSONB,
    sample TEXT,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_connector_deliveries_connector_id ON connector_deliveries (connector_id);

CREATE TABLE IF NOT EXISTS tracker_visitors (
    id VARCHAR NOT NULL,
    connector_id VARCHAR,
    email VARCHAR,
    first_seen TIMESTAMP WITH TIME ZONE,
    last_seen TIMESTAMP WITH TIME ZONE,
    page_views INTEGER,
    pending JSONB,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_tracker_visitors_connector_id ON tracker_visitors (connector_id);

-- Server-only: the API reads these with the database role. Secrets must never be reachable through PostgREST.
ALTER TABLE connectors ENABLE ROW LEVEL SECURITY;
ALTER TABLE connector_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE tracker_visitors ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
