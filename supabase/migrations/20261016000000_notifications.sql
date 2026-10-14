-- Notifications (Phase 7). Created only by live processing (never by replays), delivered in the app and, once
-- their keys are set, by email, Slack and SMS. They survive replays; a demo reset clears them.

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER NOT NULL,
    ts TIMESTAMP WITH TIME ZONE,
    rule VARCHAR,
    severity VARCHAR,
    audience VARCHAR,
    rep_id VARCHAR,
    scope_rep_id VARCHAR,
    lead_id VARCHAR,
    opp_id VARCHAR,
    title TEXT,
    body TEXT,
    link VARCHAR,
    channels JSONB,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_notifications_ts ON notifications (ts);
CREATE INDEX IF NOT EXISTS ix_notifications_rule ON notifications (rule);
CREATE INDEX IF NOT EXISTS ix_notifications_rep_id ON notifications (rep_id);
CREATE INDEX IF NOT EXISTS ix_notifications_lead_id ON notifications (lead_id);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id VARCHAR NOT NULL,
    notification_id INTEGER,
    ts TIMESTAMP WITH TIME ZONE,
    channel VARCHAR,
    target VARCHAR,
    status VARCHAR,
    detail TEXT,
    PRIMARY KEY (id)
);
CREATE INDEX IF NOT EXISTS ix_notification_deliveries_notification_id ON notification_deliveries (notification_id);

CREATE TABLE IF NOT EXISTS notification_reads (
    user_key VARCHAR NOT NULL,
    last_read_id INTEGER,
    read_ids JSONB,
    PRIMARY KEY (user_key)
);

-- Each person's own notification settings: a phone number for SMS and which channels they want.
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS phone VARCHAR;
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS notify JSONB;

ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_reads ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I FROM anon, authenticated', current_schema());
    END IF;
END
$$;
