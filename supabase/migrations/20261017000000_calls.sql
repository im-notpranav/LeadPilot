-- Call intelligence (Phase 8). Calls from the phone system (Retell or the generic format) or logged by a rep.
-- The analysis (Gemini, or rules) is also written into each call's call_logged event, so replays never call Gemini.
-- Recordings live in the private Supabase Storage bucket call-recordings (created on first use).

CREATE TABLE IF NOT EXISTS calls (
    id VARCHAR NOT NULL,
    provider VARCHAR,
    provider_call_id VARCHAR,
    connector_id VARCHAR,
    lead_id VARCHAR,
    lead_ref JSONB,
    rep_id VARCHAR,
    direction VARCHAR,
    from_number VARCHAR,
    to_number VARCHAR,
    started_at TIMESTAMP WITH TIME ZONE,
    ended_at TIMESTAMP WITH TIME ZONE,
    duration_s FLOAT,
    status VARCHAR,
    transcript TEXT,
    recording_url TEXT,
    recording_path VARCHAR,
    provider_analysis JSONB,
    disconnection_reason VARCHAR,
    outcome_hint VARCHAR,
    analysis JSONB,
    analyzed_by VARCHAR,
    error TEXT,
    event_ids JSONB,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_calls_lead_id ON calls (lead_id);
CREATE INDEX IF NOT EXISTS ix_calls_status ON calls (status);
CREATE INDEX IF NOT EXISTS ix_calls_created_at ON calls (created_at);

ALTER TABLE calls ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
