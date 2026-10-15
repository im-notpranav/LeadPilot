-- Quotes on deals (Phase 9). A projection like opportunities: rebuilt from the deal's quote events in raw_events
-- (quote_created, quote_revised, quote_approved, proposal_sent, proposal_viewed, deal_won, quote_declined,
-- quote_voided), so a replay rebuilds every quote. Lines keep their own prices.

CREATE TABLE IF NOT EXISTS quotes (
    quote_id VARCHAR NOT NULL,
    opp_id VARCHAR,
    lead_id VARCHAR,
    account_id VARCHAR,
    title VARCHAR,
    status VARCHAR,
    rev INTEGER,
    currency VARCHAR,
    lines JSONB,
    discount_pct FLOAT,
    total FLOAT,
    recurring_total FLOAT,
    one_time_total FLOAT,
    list_total FLOAT,
    effective_discount_pct FLOAT,
    needs_approval BOOLEAN,
    approved_by VARCHAR,
    valid_until VARCHAR,
    created_by VARCHAR,
    created_at TIMESTAMP WITH TIME ZONE,
    sent_at TIMESTAMP WITH TIME ZONE,
    viewed_at TIMESTAMP WITH TIME ZONE,
    views INTEGER,
    accepted_at TIMESTAMP WITH TIME ZONE,
    declined_at TIMESTAMP WITH TIME ZONE,
    decline_reason TEXT,
    updated_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (quote_id)
);
CREATE INDEX IF NOT EXISTS ix_quotes_opp_id ON quotes (opp_id);
CREATE INDEX IF NOT EXISTS ix_quotes_lead_id ON quotes (lead_id);
CREATE INDEX IF NOT EXISTS ix_quotes_status ON quotes (status);

ALTER TABLE quotes ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
