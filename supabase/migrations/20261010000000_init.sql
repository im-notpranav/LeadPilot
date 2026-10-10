-- LeadPilot initial schema.
-- Mirrors backend/app/models/tables.py; tests/test_postgres.py checks the two stay in step.
-- Idempotent (IF NOT EXISTS) so it can be re-run or applied by the Supabase CLI.
--
-- raw_events is the durable source of truth: every accepted event envelope, exactly as ingested.
-- Every other table is a projection that LeadPilot rebuilds from raw_events.

CREATE TABLE IF NOT EXISTS accounts (
    company_id VARCHAR NOT NULL,
    normalized_name VARCHAR,
    domain VARCHAR,
    employees INTEGER,
    employee_band VARCHAR,
    industry VARCHAR,
    revenue_band VARCHAR,
    country VARCHAR,
    region VARCHAR,
    tech_stack JSONB,
    funding_stage VARCHAR,
    PRIMARY KEY (company_id)
);
CREATE INDEX IF NOT EXISTS ix_accounts_domain ON accounts (domain);

CREATE TABLE IF NOT EXISTS actions (
    id VARCHAR NOT NULL,
    lead_id VARCHAR,
    rep_id VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    rule_id VARCHAR,
    action TEXT,
    channel VARCHAR,
    due_at TIMESTAMP WITH TIME ZONE,
    urgency VARCHAR,
    reason TEXT,
    template VARCHAR,
    status VARCHAR,
    closed_at TIMESTAMP WITH TIME ZONE,
    closed_by_event_id VARCHAR,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_actions_lead_id ON actions (lead_id);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER NOT NULL,
    lead_id VARCHAR,
    rep_id VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    reason TEXT,
    candidate_scores JSONB,
    type VARCHAR,
    previous_rep_id VARCHAR,
    rule_id VARCHAR,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_assignments_lead_id ON assignments (lead_id);

CREATE TABLE IF NOT EXISTS events (
    event_id VARCHAR NOT NULL,
    seq INTEGER,
    lead_id VARCHAR,
    type VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    actor VARCHAR,
    rep_id VARCHAR,
    source VARCHAR,
    payload JSONB,
    lead_ref JSONB,
    derived BOOLEAN,
    ingested_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (event_id)
);
CREATE INDEX IF NOT EXISTS ix_events_lead_id ON events (lead_id);
CREATE INDEX IF NOT EXISTS ix_events_seq ON events (seq);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events (ts);
CREATE INDEX IF NOT EXISTS ix_events_type ON events (type);

CREATE TABLE IF NOT EXISTS factor_snapshots (
    id INTEGER NOT NULL,
    lead_id VARCHAR,
    event_id VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    factors JSONB,
    parts JSONB,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_factor_snapshots_lead_id ON factor_snapshots (lead_id);

CREATE TABLE IF NOT EXISTS historical_deals (
    id VARCHAR NOT NULL,
    rep_id VARCHAR,
    source VARCHAR,
    segment VARCHAR,
    industry VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    won BOOLEAN,
    amount FLOAT,
    score FLOAT,
    grade VARCHAR,
    features JSONB,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_historical_deals_rep_id ON historical_deals (rep_id);

CREATE TABLE IF NOT EXISTS leads (
    lead_id VARCHAR NOT NULL,
    account_id VARCHAR,
    name VARCHAR,
    email_norm VARCHAR,
    phone_e164 VARCHAR,
    title VARCHAR,
    seniority VARCHAR,
    company VARCHAR,
    source_primary VARCHAR,
    sources JSONB,
    status VARCHAR,
    merged_into VARCHAR,
    owner_rep_id VARCHAR,
    stage VARCHAR,
    is_stalled BOOLEAN,
    score FLOAT,
    grade VARCHAR,
    intent_level VARCHAR,
    fake_score FLOAT,
    predicted_acv FLOAT,
    close_prob FLOAT,
    expected_value FLOAT,
    priority FLOAT,
    created_at TIMESTAMP WITH TIME ZONE,
    last_inbound_at TIMESTAMP WITH TIME ZONE,
    last_outbound_at TIMESTAMP WITH TIME ZONE,
    first_response_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (lead_id)
);
CREATE INDEX IF NOT EXISTS ix_leads_account_id ON leads (account_id);
CREATE INDEX IF NOT EXISTS ix_leads_email_norm ON leads (email_norm);
CREATE INDEX IF NOT EXISTS ix_leads_owner_rep_id ON leads (owner_rep_id);
CREATE INDEX IF NOT EXISTS ix_leads_phone_e164 ON leads (phone_e164);
CREATE INDEX IF NOT EXISTS ix_leads_stage ON leads (stage);

CREATE TABLE IF NOT EXISTS merges (
    id INTEGER NOT NULL,
    survivor_id VARCHAR,
    merged_id VARCHAR,
    confidence FLOAT,
    match_keys JSONB,
    ts TIMESTAMP WITH TIME ZONE,
    mode VARCHAR,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS quality_flags (
    lead_id VARCHAR NOT NULL,
    fake_score FLOAT,
    signals JSONB,
    status VARCHAR,
    reviewed_by VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (lead_id)
);

CREATE TABLE IF NOT EXISTS raw_events (
    seq INTEGER NOT NULL,
    event_id VARCHAR NOT NULL,
    body JSONB NOT NULL,
    PRIMARY KEY (seq),
    UNIQUE (event_id)
);

CREATE TABLE IF NOT EXISTS reps (
    rep_id VARCHAR NOT NULL,
    name VARCHAR,
    territories JSONB,
    industries JSONB,
    segments JSONB,
    languages JSONB,
    capacity_points INTEGER,
    active BOOLEAN,
    profile VARCHAR,
    PRIMARY KEY (rep_id)
);

CREATE TABLE IF NOT EXISTS review_queue (
    id VARCHAR NOT NULL,
    kind VARCHAR,
    lead_id VARCHAR,
    candidate_id VARCHAR,
    confidence FLOAT,
    match_keys JSONB,
    detail JSONB,
    status VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    resolved_at TIMESTAMP WITH TIME ZONE,
    resolution VARCHAR,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS score_changes (
    id INTEGER NOT NULL,
    lead_id VARCHAR,
    event_id VARCHAR,
    event_type VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    old_score FLOAT,
    new_score FLOAT,
    delta FLOAT,
    contributions JSONB,
    summary TEXT,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_score_changes_lead_id ON score_changes (lead_id);

CREATE TABLE IF NOT EXISTS source_quality_daily (
    id INTEGER NOT NULL,
    source_id VARCHAR,
    date VARCHAR,
    volume INTEGER,
    dup_rate FLOAT,
    fake_rate FLOAT,
    contact_rate FLOAT,
    sql_rate FLOAT,
    win_rate FLOAT,
    median_first_response_min FLOAT,
    avg_score FLOAT,
    revenue FLOAT,
    quality_index FLOAT,
    flagged BOOLEAN,
    flag_reasons JSONB,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_source_quality_daily_source_id ON source_quality_daily (source_id);

CREATE TABLE IF NOT EXISTS sources (
    source_id VARCHAR NOT NULL,
    name VARCHAR,
    channel VARCHAR,
    cost_per_lead FLOAT,
    PRIMARY KEY (source_id)
);

CREATE TABLE IF NOT EXISTS stage_transitions (
    id INTEGER NOT NULL,
    lead_id VARCHAR,
    ts TIMESTAMP WITH TIME ZONE,
    from_stage VARCHAR,
    to_stage VARCHAR,
    rule_id VARCHAR,
    evidence_event_ids JSONB,
    mode VARCHAR,
    reason TEXT,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_stage_transitions_lead_id ON stage_transitions (lead_id);

CREATE TABLE IF NOT EXISTS stall_flags (
    id INTEGER NOT NULL,
    lead_id VARCHAR,
    ts_detected TIMESTAMP WITH TIME ZONE,
    rule_ids JSONB,
    details JSONB,
    risk INTEGER,
    cleared_at TIMESTAMP WITH TIME ZONE,
    cleared_by_event_id VARCHAR,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_stall_flags_lead_id ON stall_flags (lead_id);
CREATE TABLE IF NOT EXISTS meta (
    key VARCHAR NOT NULL,
    value JSONB,
    PRIMARY KEY (key)
);

-- Row level security: on for every table with no policies, so Supabase's anon / authenticated API roles
-- (PostgREST, supabase-js) can read nothing. The backend connects as the database owner, which bypasses RLS.
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE factor_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE historical_deals ENABLE ROW LEVEL SECURITY;
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE merges ENABLE ROW LEVEL SECURITY;
ALTER TABLE quality_flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE reps ENABLE ROW LEVEL SECURITY;
ALTER TABLE review_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE score_changes ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_quality_daily ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE stage_transitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE stall_flags ENABLE ROW LEVEL SECURITY;
ALTER TABLE meta ENABLE ROW LEVEL SECURITY;
ALTER TABLE leadpilot_migrations ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
