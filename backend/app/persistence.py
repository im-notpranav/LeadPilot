"""Write-behind persistence of the event log and projections to SQLite (Postgres-compatible schema).

The in-memory store is the working set; every processing step queues rows here and flushes them in one
transaction at the end of the step (or in batches during warm-up and replay).
"""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import create_engine, event, insert, select, text, update

from .models import tables as T

_UPSERT_TABLES = {"leads", "quality_flags", "actions", "review_queue", "reps", "sources", "accounts"}


def jsonable(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, float) and obj != obj:
        return None
    return obj


class NullPersistence:
    enabled = False

    def add(self, table: str, row: dict) -> None: ...
    def upsert(self, table: str, row: dict) -> None: ...
    def repoint_events(self, event_ids: list[str], lead_id: str) -> None: ...
    def flush(self) -> None: ...
    def reset(self) -> None: ...
    def clear_projections(self) -> None: ...
    def count(self, table: str) -> int:
        return 0

    def load_raw_events(self) -> list[dict]:
        return []

    def load_historical(self) -> list[dict]:
        return []


class Persistence:
    enabled = True

    def __init__(self, url: str | None = None):
        if url is None:
            path = Path(os.environ.get("LEADPILOT_DB", Path(__file__).resolve().parents[1] / "var" / "leadpilot.db"))
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{path}"
        file_db = url.startswith("sqlite") and ":memory:" not in url
        self.engine = create_engine(url, future=True,
                                    connect_args={"check_same_thread": False} if file_db else {})
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()
        T.metadata.create_all(self.engine)
        self._inserts: dict[str, list[dict]] = {}
        self._upserts: dict[str, dict] = {}
        self._repoints: list[tuple[list[str], str]] = []

    def add(self, table: str, row: dict) -> None:
        self._inserts.setdefault(table, []).append(row)

    def upsert(self, table: str, row: dict) -> None:
        tbl = getattr(T, table)
        pk = [c.name for c in tbl.primary_key.columns][0]
        self._upserts.setdefault(table, {})[row[pk]] = row

    def repoint_events(self, event_ids: list[str], lead_id: str) -> None:
        self._repoints.append((event_ids, lead_id))

    def _clean(self, table: str, row: dict) -> dict:
        tbl = getattr(T, table)
        out = {}
        for c in tbl.columns:          # every column present: executemany needs homogeneous rows
            v = row.get(c.name)
            out[c.name] = jsonable(v) if isinstance(c.type, T.JSON) else v
        return out

    def flush(self) -> None:
        if not (self._inserts or self._upserts or self._repoints):
            return
        with self.engine.begin() as conn:
            for table, rows in self._inserts.items():
                if rows:
                    conn.execute(insert(getattr(T, table)), [self._clean(table, r) for r in rows])
            for table, rows in self._upserts.items():
                if rows:
                    conn.execute(insert(getattr(T, table)).prefix_with("OR REPLACE"),
                                 [self._clean(table, r) for r in rows.values()])
            for ids, lead_id in self._repoints:
                conn.execute(update(T.events).where(T.events.c.event_id.in_(ids)).values(lead_id=lead_id))
        self._inserts.clear()
        self._upserts.clear()
        self._repoints.clear()

    def reset(self) -> None:
        self._inserts.clear()
        self._upserts.clear()
        self._repoints.clear()
        with self.engine.begin() as conn:
            for tbl in reversed(T.metadata.sorted_tables):
                conn.execute(tbl.delete())

    def clear_projections(self) -> None:
        """Everything except the event logs and seed tables (used by /replay)."""
        keep = {"raw_events", "events", "historical_deals", "reps", "sources"}
        self._inserts.clear()
        self._upserts.clear()
        with self.engine.begin() as conn:
            for tbl in reversed(T.metadata.sorted_tables):
                if tbl.name not in keep:
                    conn.execute(tbl.delete())

    def count(self, table: str) -> int:
        with self.engine.connect() as conn:
            return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()

    def load_raw_events(self) -> list[dict]:
        """The raw envelope log in arrival order: the input to a startup rebuild."""
        with self.engine.connect() as conn:
            return [dict(r.body) for r in conn.execute(select(T.raw_events.c.body).order_by(T.raw_events.c.seq))]

    def load_historical(self) -> list[dict]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(T.historical_deals)).mappings().all()
        return [dict(r) for r in rows]
