"""SQLAlchemy Core tables (SQLite here; schema is Postgres-compatible)."""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, MetaData, String, Table, Text

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
)

score_changes = Table(
    "score_changes", metadata,
    Column("id", Integer, primary_key=True),
    Column("lead_id", String, index=True), Column("event_id", String), Column("event_type", String),
    Column("ts", DateTime(timezone=True)), Column("old_score", Float), Column("new_score", Float),
    Column("delta", Float), Column("contributions", JSON), Column("summary", Text),
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
