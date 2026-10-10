"""Postgres / Supabase persistence. Opt-in: LEADPILOT_TEST_POSTGRES=1 (make test-pg).

Uses LEADPILOT_TEST_DB_URL, else LEADPILOT_DB_URL (backend/.env), but always inside its own schema
`leadpilot_test`, which is dropped before and after the run, so the real tables are never touched.
"""
import os
import time
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import load_config
from app.migrate import apply_migrations, migration_files
from app.models import tables as T
from app.persistence import Persistence, normalize_url
from app.runtime import Runtime
from app.settings import load_dotenv
from test_invariants import assignments, snapshot
from test_live_mode import live_events

SCHEMA = "leadpilot_test"

load_dotenv()
URL = os.environ.get("LEADPILOT_TEST_DB_URL") or os.environ.get("LEADPILOT_DB_URL")
pytestmark = pytest.mark.skipif(os.environ.get("LEADPILOT_TEST_POSTGRES") != "1" or not URL
                                or URL.startswith("sqlite"),
                                reason="set LEADPILOT_TEST_POSTGRES=1 and a Postgres LEADPILOT_DB_URL")


def _drop_schema():
    eng = create_engine(normalize_url(URL))
    with eng.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE'))
    eng.dispose()


@pytest.fixture(scope="module", autouse=True)
def clean_schema():
    _drop_schema()
    yield
    _drop_schema()


def pg() -> Persistence:
    db = Persistence(URL, schema=SCHEMA)
    db.reset()
    return db


def test_migrations_create_every_table_and_are_idempotent():
    db = Persistence(URL, schema=SCHEMA)
    try:
        assert apply_migrations(db.engine, SCHEMA) == []          # already applied by Persistence()
        insp = inspect(db.engine)
        tables = set(insp.get_table_names(schema=SCHEMA))
        assert {t.name for t in T.metadata.sorted_tables} | {"leadpilot_migrations"} <= tables
        for t in T.metadata.sorted_tables:                          # the SQL file matches tables.py
            cols = {c["name"] for c in insp.get_columns(t.name, schema=SCHEMA)}
            assert cols == {c.name for c in t.columns}, t.name
        with db.engine.connect() as conn:
            versions = [r[0] for r in conn.execute(text("SELECT version FROM leadpilot_migrations ORDER BY 1"))]
            no_rls = [r[0] for r in conn.execute(text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :s AND c.relkind = 'r' AND NOT c.relrowsecurity"), {"s": SCHEMA})]
        assert versions == [p.stem for p in migration_files()]
        assert no_rls == []                                         # anon / authenticated can read nothing
    finally:
        db.close()


def test_writes_are_async_and_upserts_replace():
    db = pg()
    try:
        assert db.async_writes
        db.upsert("reps", {"rep_id": "R-X", "name": "First", "territories": ["APAC"], "active": True})
        db.flush()
        db.upsert("reps", {"rep_id": "R-X", "name": "Second", "territories": ["EMEA"], "active": False})
        db.add("raw_events", {"seq": 1, "event_id": "x-1", "body": {"type": "page_view", "payload": {"n": 1}}})
        db.flush()
        assert db.drain(timeout=30)
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT name, territories, active FROM reps WHERE rep_id = 'R-X'")).one()
        assert tuple(row) == ("Second", ["EMEA"], False)
        assert db.load_raw_events() == [{"type": "page_view", "payload": {"n": 1}}]
        assert db.status()["last_error"] is None
    finally:
        db.close()


def test_live_restart_on_postgres_rebuilds_identical_state():
    db = pg()
    first = Runtime(load_config(), db, live=True)
    first.rebuild()
    for e in live_events(first.clock.now()):
        assert first.emit(e)["status"] == "processed"
    before, before_assign = snapshot(first), assignments(first)
    db.close()

    db2 = Persistence(URL, schema=SCHEMA)
    try:
        second = Runtime(load_config(), db2, live=True)
        second.rebuild()
        assert snapshot(second) == before and assignments(second) == before_assign
        assert db2.count("raw_events") == 4 and db2.count("leads") == 1
    finally:
        db2.close()


def test_demo_world_round_trips_through_postgres():
    db = pg()
    cfg = load_config(overrides={"simulator": {"warmup_days": 2}})
    demo = Runtime(cfg, db)
    t0 = time.perf_counter()
    demo.reset(seed=5)
    demo.run_until(demo.clock.now() + timedelta(hours=4))
    assert db.drain(timeout=120)
    write_s = time.perf_counter() - t0
    expected = snapshot(demo)
    assert db.count("raw_events") == len(demo.store.raw_log)
    db.close()

    db2 = Persistence(URL, schema=SCHEMA)
    try:
        t1 = time.perf_counter()
        rebuilt = Runtime(cfg, db2, live=True)
        rebuilt.rebuild()
        assert db2.drain(timeout=120)
        rebuild_s = time.perf_counter() - t1
        assert snapshot(rebuilt) == expected
        assert db2.count("leads") == len(expected)
        print(f"\n  demo write {write_s:.1f}s, live rebuild {rebuild_s:.1f}s for {len(rebuilt.store.raw_log)} raw events")
    finally:
        db2.close()
