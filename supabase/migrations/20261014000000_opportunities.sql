-- Deals / opportunities (Phase 4). A projection like leads: rebuilt from raw_events on replay, so existing event
-- history becomes deals automatically. One account (company) can have several deals, each with several contacts.

CREATE TABLE IF NOT EXISTS opportunities (
    opp_id VARCHAR NOT NULL,
    account_id VARCHAR,
    account_key VARCHAR,
    name VARCHAR,
    kind VARCHAR,
    status VARCHAR,
    stage VARCHAR,
    stage_entered_at TIMESTAMP WITH TIME ZONE,
    opened_at TIMESTAMP WITH TIME ZONE,
    closed_at TIMESTAMP WITH TIME ZONE,
    open_rule VARCHAR,
    primary_lead_id VARCHAR,
    contact_ids JSONB,
    owner_rep_id VARCHAR,
    amount FLOAT,
    predicted_acv FLOAT,
    close_prob FLOAT,
    expected_value FLOAT,
    is_stalled BOOLEAN,
    close_date VARCHAR,
    lost_reason TEXT,
    committee JSONB,
    transitions JSONB,
    last_activity_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (opp_id)
);
CREATE INDEX IF NOT EXISTS ix_opportunities_account_id ON opportunities (account_id);
CREATE INDEX IF NOT EXISTS ix_opportunities_account_key ON opportunities (account_key);
CREATE INDEX IF NOT EXISTS ix_opportunities_status ON opportunities (status);
CREATE INDEX IF NOT EXISTS ix_opportunities_stage ON opportunities (stage);
CREATE INDEX IF NOT EXISTS ix_opportunities_owner_rep_id ON opportunities (owner_rep_id);

ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
