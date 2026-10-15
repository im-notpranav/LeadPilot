"""SQLAlchemy Core tables. SQLite locally; Postgres (Supabase) in production, where the DDL lives in
supabase/migrations/ and must be kept in step with this file (tests/test_migrations.py checks that)."""
from __future__ import annotations

from sqlalchemy import JSON as _JSON
from sqlalchemy import Boolean, Column, DateTime, Float, Integer, MetaData, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB

JSON = _JSON().with_variant(JSONB(), "postgresql")   # jsonb on Postgres, JSON text on SQLite

metadata = MetaData()

accounts = Table(
    "accounts", metadata,
    Column("company_id", String, primary_key=True),
    Column("normalized_name", String), Column("domain", String, index=True), Column("employees", Integer),
    Column("employee_band", String), Column("industry", String), Column("revenue_band", String),
    Column("country", String), Column("region", String), Column("tech_stack", JSON), Column("funding_stage", String),
)

leads = Table(
    "leads", metadata,
    Column("lead_id", String, primary_key=True),
    Column("account_id", String, index=True), Column("name", String), Column("email_norm", String, index=True),
    Column("phone_e164", String, index=True), Column("title", String), Column("seniority", String),
    Column("company", String), Column("source_primary", String), Column("sources", JSON), Column("status", String),
    Column("merged_into", String), Column("owner_rep_id", String, index=True), Column("stage", String, index=True),
    Column("is_stalled", Boolean), Column("score", Float), Column("grade", String), Column("intent_level", String),
    Column("fake_score", Float), Column("predicted_acv", Float), Column("close_prob", Float),
    Column("expected_value", Float), Column("priority", Float), Column("created_at", DateTime(timezone=True)),
    Column("last_inbound_at", DateTime(timezone=True)), Column("last_outbound_at", DateTime(timezone=True)),
    Column("first_response_at", DateTime(timezone=True)),
)

raw_events = Table(
    "raw_events", metadata,
    # The durable source of truth: every accepted envelope exactly as ingested, in arrival order.
    # Projections (including `events`) are rebuilt from this log on startup and on /api/replay.
    Column("seq", Integer, primary_key=True, autoincrement=False),
    Column("event_id", String, unique=True, nullable=False), Column("body", JSON, nullable=False),
)

events = Table(
    "events", metadata,
    Column("event_id", String, primary_key=True),
    Column("seq", Integer, index=True), Column("lead_id", String, index=True), Column("type", String, index=True),
    Column("ts", DateTime(timezone=True), index=True), Column("actor", String), Column("rep_id", String),
    Column("source", String), Column("payload", JSON), Column("lead_ref", JSON), Column("derived", Boolean),
    Column("ingested_at", DateTime(timezone=True)),
    Column("config_version", Integer),        # the settings version that processed this event
)

score_changes = Table(
    "score_changes", metadata,
    Column("id", Integer, primary_key=True),
    Column("lead_id", String, index=True), Column("event_id", String), Column("event_type", String),
    Column("ts", DateTime(timezone=True)), Column("old_score", Float), Column("new_score", Float),
    Column("delta", Float), Column("contributions", JSON), Column("summary", Text),
    Column("config_version", Integer),        # the settings version that produced this score
)

factor_snapshots = Table(
    "factor_snapshots", metadata,
    Column("id", Integer, primary_key=True),
    Column("lead_id", String, index=True), Column("event_id", String), Column("ts", DateTime(timezone=True)),
    Column("factors", JSON), Column("parts", JSON),
)

stage_transitions = Table(
    "stage_transitions", metadata,
    Column("id", Integer, primary_key=True),
    Column("lead_id", String, index=True), Column("ts", DateTime(timezone=True)), Column("from_stage", String),
    Column("to_stage", String), Column("rule_id", String), Column("evidence_event_ids", JSON), Column("mode", String),
    Column("reason", Text),
)

stall_flags = Table(
    "stall_flags", metadata,
    Column("id", Integer, primary_key=True),
    Column("lead_id", String, index=True), Column("ts_detected", DateTime(timezone=True)), Column("rule_ids", JSON),
    Column("details", JSON), Column("risk", Integer), Column("cleared_at", DateTime(timezone=True)),
    Column("cleared_by_event_id", String),
)

reps = Table(
    "reps", metadata,
    Column("rep_id", String, primary_key=True),
    Column("name", String), Column("territories", JSON), Column("industries", JSON), Column("segments", JSON),
    Column("languages", JSON), Column("capacity_points", Integer), Column("active", Boolean), Column("profile", String),
)

assignments = Table(
    "assignments", metadata,
    Column("id", Integer, primary_key=True),
    Column("lead_id", String, index=True), Column("rep_id", String), Column("ts", DateTime(timezone=True)),
    Column("reason", Text), Column("candidate_scores", JSON), Column("type", String), Column("previous_rep_id", String),
    Column("rule_id", String),
)

actions = Table(
    "actions", metadata,
    Column("id", String, primary_key=True),
    Column("lead_id", String, index=True), Column("rep_id", String), Column("ts", DateTime(timezone=True)),
    Column("rule_id", String), Column("action", Text), Column("channel", String),
    Column("due_at", DateTime(timezone=True)), Column("urgency", String), Column("reason", Text),
    Column("template", String), Column("status", String), Column("closed_at", DateTime(timezone=True)),
    Column("closed_by_event_id", String),
)

quality_flags = Table(
    "quality_flags", metadata,
    Column("lead_id", String, primary_key=True),
    Column("fake_score", Float), Column("signals", JSON), Column("status", String), Column("reviewed_by", String),
    Column("ts", DateTime(timezone=True)),
)

merges = Table(
    "merges", metadata,
    Column("id", Integer, primary_key=True),
    Column("survivor_id", String), Column("merged_id", String), Column("confidence", Float), Column("match_keys", JSON),
    Column("ts", DateTime(timezone=True)), Column("mode", String),
)

review_queue = Table(
    "review_queue", metadata,
    Column("id", String, primary_key=True),
    Column("kind", String), Column("lead_id", String), Column("candidate_id", String), Column("confidence", Float),
    Column("match_keys", JSON), Column("detail", JSON), Column("status", String), Column("ts", DateTime(timezone=True)),
    Column("resolved_at", DateTime(timezone=True)), Column("resolution", String),
)

sources = Table(
    "sources", metadata,
    Column("source_id", String, primary_key=True),
    Column("name", String), Column("channel", String), Column("cost_per_lead", Float),
)

source_quality_daily = Table(
    "source_quality_daily", metadata,
    Column("id", Integer, primary_key=True),
    Column("source_id", String, index=True), Column("date", String), Column("volume", Integer),
    Column("dup_rate", Float), Column("fake_rate", Float), Column("contact_rate", Float), Column("sql_rate", Float),
    Column("win_rate", Float), Column("median_first_response_min", Float), Column("avg_score", Float),
    Column("revenue", Float), Column("quality_index", Float), Column("flagged", Boolean), Column("flag_reasons", JSON),
)

historical_deals = Table(
    "historical_deals", metadata,
    Column("id", String, primary_key=True),
    Column("rep_id", String, index=True), Column("source", String), Column("segment", String),
    Column("industry", String), Column("created_at", DateTime(timezone=True)),
    Column("closed_at", DateTime(timezone=True)), Column("won", Boolean), Column("amount", Float),
    Column("score", Float), Column("grade", String), Column("features", JSON),
)

meta = Table(
    "meta", metadata,
    # Small key/value facts about the stored projections, e.g. which config fingerprint produced them.
    Column("key", String, primary_key=True), Column("value", JSON),
)


# ---- Accounts: who may use LeadPilot. Not projections: never rebuilt from the event log, never reset by demo mode.

profiles = Table(
    "profiles", metadata,
    # One row per Supabase Auth user (user_id = auth.users.id). Roles: admin | manager | rep | pending.
    Column("user_id", String, primary_key=True),
    Column("email", String, index=True), Column("name", String), Column("role", String, nullable=False),
    Column("rep_id", String),                 # the sales rep this user works as (reps only)
    Column("team_rep_ids", JSON),             # managers: the reps they oversee; null = every rep
    Column("created_at", DateTime(timezone=True)), Column("updated_at", DateTime(timezone=True)),
    Column("last_seen_at", DateTime(timezone=True)),
    Column("phone", String),                  # for SMS notifications (E.164), set by the person themselves
    Column("notify", JSON),                   # notification preferences: {"email": bool, "sms": bool}
)

api_keys = Table(
    "api_keys", metadata,
    # Machine credentials for event ingestion. Only a SHA-256 hash of the secret is stored.
    Column("id", String, primary_key=True),
    Column("name", String, nullable=False), Column("prefix", String, nullable=False),
    Column("key_hash", String, nullable=False, unique=True), Column("created_by", String),
    Column("created_at", DateTime(timezone=True)), Column("last_used_at", DateTime(timezone=True)),
    Column("revoked_at", DateTime(timezone=True)),
)


# ---- Connectors: how outside systems send events in. Like accounts, they survive demo resets and replays.

opportunities = Table(
    "opportunities", metadata,
    # Deals: a projection like leads (rebuilt from raw_events). One account can have several, each with several
    # contacts. status: open | won | lost | void (no longer produced by the event log, e.g. after a merge).
    Column("opp_id", String, primary_key=True),
    Column("account_id", String, index=True), Column("account_key", String, index=True), Column("name", String),
    Column("kind", String), Column("status", String, index=True), Column("stage", String, index=True),
    Column("stage_entered_at", DateTime(timezone=True)), Column("opened_at", DateTime(timezone=True)),
    Column("closed_at", DateTime(timezone=True)), Column("open_rule", String), Column("primary_lead_id", String),
    Column("contact_ids", JSON), Column("owner_rep_id", String, index=True), Column("amount", Float),
    Column("predicted_acv", Float), Column("close_prob", Float), Column("expected_value", Float),
    Column("is_stalled", Boolean), Column("close_date", String), Column("lost_reason", Text),
    Column("committee", JSON), Column("transitions", JSON), Column("last_activity_at", DateTime(timezone=True)),
)

quotes = Table(
    "quotes", metadata,
    # Quotes on deals: a projection rebuilt from the deal's quote events (engine/quotes.py). status: draft | sent |
    # accepted | declined | void | superseded. Lines keep their own prices.
    Column("quote_id", String, primary_key=True),
    Column("opp_id", String, index=True), Column("lead_id", String, index=True), Column("account_id", String),
    Column("title", String), Column("status", String, index=True), Column("rev", Integer), Column("currency", String),
    Column("lines", JSON), Column("discount_pct", Float), Column("total", Float), Column("recurring_total", Float),
    Column("one_time_total", Float), Column("list_total", Float), Column("effective_discount_pct", Float),
    Column("needs_approval", Boolean), Column("approved_by", String), Column("valid_until", String),
    Column("created_by", String), Column("created_at", DateTime(timezone=True)),
    Column("sent_at", DateTime(timezone=True)), Column("viewed_at", DateTime(timezone=True)), Column("views", Integer),
    Column("accepted_at", DateTime(timezone=True)), Column("declined_at", DateTime(timezone=True)),
    Column("decline_reason", Text), Column("updated_at", DateTime(timezone=True)),
)

connectors = Table(
    "connectors", metadata,
    # kind: webhook (LeadPilot events, HMAC) | form | crm | email | tracker (website snippet, public site key).
    # The secret signs webhooks (or is the URL token for tools that cannot sign); a tracker's is its site key.
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False), Column("name", String, nullable=False), Column("source", String),
    Column("secret", String, nullable=False, unique=True), Column("settings", JSON),
    Column("created_by", String), Column("created_at", DateTime(timezone=True)),
    Column("last_received_at", DateTime(timezone=True)), Column("received_count", Integer),
    Column("revoked_at", DateTime(timezone=True)),
)

connector_deliveries = Table(
    "connector_deliveries", metadata,
    # One row per inbound request: what arrived, what LeadPilot did with it, and why it was refused.
    Column("id", String, primary_key=True),
    Column("connector_id", String, index=True), Column("received_at", DateTime(timezone=True)),
    Column("status", String), Column("http_status", Integer), Column("reason", Text),
    Column("events", Integer), Column("results", JSON), Column("sample", Text),
)

tracker_visitors = Table(
    "tracker_visitors", metadata,
    # Website visitors seen by a tracker. Page views wait in `pending` until a form tells us who the visitor is.
    Column("id", String, primary_key=True),           # <connector id>:<visitor id>
    Column("connector_id", String, index=True), Column("email", String),
    Column("first_seen", DateTime(timezone=True)), Column("last_seen", DateTime(timezone=True)),
    Column("page_views", Integer), Column("pending", JSON),
)


# ---- Settings: versioned rule changes on top of backend/config/*.yaml. Like accounts, they survive resets and replays.

config_versions = Table(
    "config_versions", metadata,
    # Each version stores only what differs from the YAML defaults (`overrides`), so a code update that adds a new
    # default still reaches every version. status: draft (saved, never used) | active (exactly one) | retired.
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("note", Text), Column("overrides", JSON, nullable=False), Column("fingerprint", String),
    Column("status", String, nullable=False, index=True), Column("restored_from", Integer),
    Column("created_by", String), Column("created_at", DateTime(timezone=True)),
    Column("activated_by", String), Column("activated_at", DateTime(timezone=True)),
    Column("retired_at", DateTime(timezone=True)),
)

notifications = Table(
    "notifications", metadata,
    # Side effects of live processing (never of replays), so they survive replays; a demo reset clears them.
    # audience: rep (one rep, rep_id) | managers (managers whose team includes scope_rep_id, and admins).
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("ts", DateTime(timezone=True), index=True), Column("rule", String, index=True), Column("severity", String),
    Column("audience", String), Column("rep_id", String, index=True), Column("scope_rep_id", String),
    Column("lead_id", String, index=True), Column("opp_id", String), Column("title", Text), Column("body", Text),
    Column("link", String), Column("channels", JSON),
)

notification_deliveries = Table(
    "notification_deliveries", metadata,
    # One row per channel and recipient: sent | failed | skipped, with the reason.
    Column("id", String, primary_key=True),           # <notification id>:<n>
    Column("notification_id", Integer, index=True), Column("ts", DateTime(timezone=True)),
    Column("channel", String), Column("target", String), Column("status", String), Column("detail", Text),
)

notification_reads = Table(
    "notification_reads", metadata,
    # What each person has read: everything up to last_read_id, plus read_ids above it.
    Column("user_key", String, primary_key=True),
    Column("last_read_id", Integer), Column("read_ids", JSON),
)

calls = Table(
    "calls", metadata,
    # Phone calls as they arrived (source data, like raw_events): kept through replays, cleared by a demo reset.
    # The analysis is also written into the call's call_logged event, so replays never need Gemini again.
    Column("id", String, primary_key=True),           # <provider>:<provider call id>
    Column("provider", String), Column("provider_call_id", String), Column("connector_id", String),
    Column("lead_id", String, index=True), Column("lead_ref", JSON), Column("rep_id", String),
    Column("direction", String), Column("from_number", String), Column("to_number", String),
    Column("started_at", DateTime(timezone=True)), Column("ended_at", DateTime(timezone=True)),
    Column("duration_s", Float), Column("status", String, index=True), Column("transcript", Text),
    Column("recording_url", Text), Column("recording_path", String), Column("provider_analysis", JSON),
    Column("disconnection_reason", String), Column("outcome_hint", String), Column("analysis", JSON),
    Column("analyzed_by", String), Column("error", Text), Column("event_ids", JSON),
    Column("created_at", DateTime(timezone=True), index=True), Column("updated_at", DateTime(timezone=True)),
)
