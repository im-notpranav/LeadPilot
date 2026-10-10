"""Write-behind persistence of the event log and projections to SQLite or Postgres (Supabase).

The in-memory store is the working set. Every processing step queues rows here and `flush()` hands them over as
one batch. On SQLite batches are written inline. On Postgres a single writer thread commits them in order, so a
remote round trip never blocks event processing; `drain()` waits until everything queued is committed.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import JSON, create_engine, event, insert, select, text, update
from sqlalchemy.dialects import postgresql, sqlite

from .migrate import apply_migrations
from .models import tables as T

log = logging.getLogger("leadpilot.persistence")

SEED_TABLES = {"historical_deals", "reps", "sources", "meta"}
LOG_TABLES = {"raw_events", "events"}
ACCOUNT_TABLES = {"profiles", "api_keys"}       # people and keys: survive demo resets and replays


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


def normalize_url(url: str) -> str:
    """Supabase hands out postgres:// / postgresql:// URLs; route them to the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class NullPersistence:
    enabled = False

    def add(self, table: str, row: dict) -> None: ...
    def upsert(self, table: str, row: dict) -> None: ...
    def repoint_events(self, event_ids: list[str], lead_id: str) -> None: ...
    def flush(self) -> None: ...
    def drain(self, timeout: float | None = None) -> bool:
        return True
    def close(self) -> None: ...
    def reset(self) -> None: ...
    def clear_projections(self) -> None: ...
    def clear_events(self) -> None: ...
    def count(self, table: str) -> int:
        return 0

    def get_meta(self, key: str):
        return None

    def set_meta(self, key: str, value) -> None: ...

    def load_raw_events(self) -> list[dict]:
        return []

    def load_historical(self) -> list[dict]:
        return []

    def status(self) -> dict:
        return {"backend": "memory"}


@dataclass
class Batch:
    inserts: dict[str, list[dict]] = field(default_factory=dict)
    upserts: dict[str, dict] = field(default_factory=dict)
    repoints: list[tuple[list[str], str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.inserts or self.upserts or self.repoints)

    @classmethod
    def merge(cls, batches: list["Batch"]) -> "Batch":
        """Fold batches into one: inserts concatenate, upserts keep the last row per key, repoints keep order.

        Safe because no table is both inserted and upserted, inserted rows have unique ids, and an event row
        always carries its current lead_id, so applying upserts before repoints gives the same final state.
        """
        out = cls()
        for b in batches:
            for table, rows in b.inserts.items():
                out.inserts.setdefault(table, []).extend(rows)
            for table, rows in b.upserts.items():
                out.upserts.setdefault(table, {}).update(rows)
            out.repoints.extend(b.repoints)
        return out


class Persistence:
    enabled = True

    def __init__(self, url: str | None = None, schema: str | None = None, async_writes: bool | None = None):
        if url is None:
            path = Path(os.environ.get("LEADPILOT_DB", Path(__file__).resolve().parents[1] / "var" / "leadpilot.db"))
            path.parent.mkdir(parents=True, exist_ok=True)
            url = f"sqlite:///{path}"
        url = normalize_url(url)
        self.is_sqlite = url.startswith("sqlite")
        self.schema = None if self.is_sqlite else (schema or "public")
        file_db = self.is_sqlite and ":memory:" not in url
        kwargs: dict = {"future": True}
        if file_db:
            kwargs["connect_args"] = {"check_same_thread": False}
        if not self.is_sqlite:
            kwargs.update(pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=300)
        self.engine = create_engine(url, **kwargs)
        if self.is_sqlite:
            @event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
                cur.close()
            T.metadata.create_all(self.engine)
        else:
            schema_name = self.schema

            @event.listens_for(self.engine, "connect")
            def _search_path(dbapi_conn, _):
                cur = dbapi_conn.cursor()
                cur.execute(f'SET search_path TO "{schema_name}"')
                cur.close()
                dbapi_conn.commit()
            self.applied_migrations = apply_migrations(self.engine, self.schema)
        self._insert = (sqlite if self.is_sqlite else postgresql).insert
        self._batch = Batch()
        self.async_writes = (not self.is_sqlite) if async_writes is None else async_writes
        self._queue: queue.Queue[Batch | None] = queue.Queue()
        self._writer: threading.Thread | None = None
        self.last_error: str | None = None
        self.written_batches = 0
        if self.async_writes:
            self._writer = threading.Thread(target=self._writer_loop, name="leadpilot-db-writer", daemon=True)
            self._writer.start()

    # ------------------------------------------------------------------ queueing (called under the runtime lock)
    def add(self, table: str, row: dict) -> None:
        self._batch.inserts.setdefault(table, []).append(row)

    def upsert(self, table: str, row: dict) -> None:
        tbl = getattr(T, table)
        pk = [c.name for c in tbl.primary_key.columns][0]
        self._batch.upserts.setdefault(table, {})[row[pk]] = row

    def repoint_events(self, event_ids: list[str], lead_id: str) -> None:
        self._batch.repoints.append((event_ids, lead_id))

    def flush(self) -> None:
        if not self._batch:
            return
        batch, self._batch = self._batch, Batch()
        if self.async_writes:
            self._queue.put(batch)
        else:
            self._write([batch])

    def drain(self, timeout: float | None = None) -> bool:
        """Flush and block until every queued batch is committed. Returns False on timeout."""
        self.flush()
        if not self.async_writes:
            return True
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._queue.unfinished_tasks:
            if deadline is not None and time.monotonic() > deadline:
                return False
            time.sleep(0.01)
        return True

    def close(self) -> None:
        self.drain(timeout=30)
        if self._writer is not None:
            self._queue.put(None)
            self._writer.join(timeout=5)
            self._writer = None
        self.engine.dispose()

    # ------------------------------------------------------------------ writing
    def _clean(self, table: str, row: dict) -> dict:
        tbl = getattr(T, table)
        out = {}
        for c in tbl.columns:          # every column present: executemany needs homogeneous rows
            v = row.get(c.name)
            out[c.name] = jsonable(v) if isinstance(c.type, JSON) else v
        return out

    def _upsert_stmt(self, table: str):
        tbl = getattr(T, table)
        pk = [c.name for c in tbl.primary_key.columns][0]
        stmt = self._insert(tbl)
        return stmt.on_conflict_do_update(index_elements=[pk],
                                          set_={c.name: stmt.excluded[c.name] for c in tbl.columns if c.name != pk})

    def _write(self, batches: list[Batch]) -> None:
        """Apply batches as one merged batch (one statement per table) in one transaction."""
        b = Batch.merge(batches) if len(batches) > 1 else batches[0]
        with self.engine.begin() as conn:
            for table, rows in b.inserts.items():
                if rows:
                    conn.execute(insert(getattr(T, table)), [self._clean(table, r) for r in rows])
            for table, rows in b.upserts.items():
                if rows:
                    conn.execute(self._upsert_stmt(table), [self._clean(table, r) for r in rows.values()])
            for ids, lead_id in b.repoints:
                conn.execute(update(T.events).where(T.events.c.event_id.in_(ids)).values(lead_id=lead_id))
        self.written_batches += len(batches)

    def write_now(self, table: str, row: dict) -> None:
        """Upsert one row synchronously, outside the event batches (accounts: rare, must be durable at once)."""
        with self.engine.begin() as conn:
            conn.execute(self._upsert_stmt(table), [self._clean(table, row)])

    def _writer_loop(self) -> None:
        backoff = 0.5
        while True:
            first = self._queue.get()
            if first is None:
                self._queue.task_done()
                return
            batches = [first]
            stop = False
            while len(batches) < 2000:         # group whatever is already waiting into one commit
                try:
                    nxt = self._queue.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    stop = True
                    self._queue.task_done()
                    break
                batches.append(nxt)
            while True:                        # never drop a batch: retry until the database accepts it
                try:
                    self._write(batches)
                    self.last_error, backoff = None, 0.5
                    break
                except Exception as exc:  # noqa: BLE001 - logged and retried
                    self.last_error = f"{type(exc).__name__}: {exc}"[:500]
                    log.exception("database write failed; retrying in %.1fs", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30)
            for _ in batches:
                self._queue.task_done()
            if stop:
                return

    # ------------------------------------------------------------------ maintenance (drain first, then act)
    def _clear(self, tables: list) -> None:
        self.drain()
        self._batch = Batch()
        with self.engine.begin() as conn:
            if self.is_sqlite:
                for tbl in tables:
                    conn.execute(tbl.delete())
            elif tables:
                conn.execute(text("TRUNCATE " + ", ".join(f'"{t.name}"' for t in tables)))

    def reset(self) -> None:
        self._clear([t for t in reversed(T.metadata.sorted_tables) if t.name not in ACCOUNT_TABLES])

    def clear_projections(self) -> None:
        """Everything except the event logs and seed tables (used by /replay)."""
        keep = LOG_TABLES | SEED_TABLES | ACCOUNT_TABLES
        self._clear([t for t in reversed(T.metadata.sorted_tables) if t.name not in keep])

    def clear_events(self) -> None:
        """The processed-event projection; the raw log is never cleared by replay."""
        self._clear([T.events])

    # ------------------------------------------------------------------ reading
    def count(self, table: str) -> int:
        self.drain()
        with self.engine.connect() as conn:
            return conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()

    def load_raw_events(self) -> list[dict]:
        """The raw envelope log in arrival order: the input to a startup rebuild."""
        self.drain()
        with self.engine.connect() as conn:
            return [dict(r.body) for r in conn.execute(select(T.raw_events.c.body).order_by(T.raw_events.c.seq))]

    def get_meta(self, key: str):
        self.drain()
        with self.engine.connect() as conn:
            return conn.execute(select(T.meta.c.value).where(T.meta.c.key == key)).scalar_one_or_none()

    def set_meta(self, key: str, value) -> None:
        self.upsert("meta", {"key": key, "value": value})

    def load_historical(self) -> list[dict]:
        self.drain()
        with self.engine.connect() as conn:
            rows = conn.execute(select(T.historical_deals).order_by(T.historical_deals.c.id)).mappings().all()
        return [dict(r) for r in rows]

    def status(self) -> dict:
        return {"backend": "sqlite" if self.is_sqlite else "postgres", "schema": self.schema,
                "async_writes": self.async_writes, "pending_batches": self._queue.unfinished_tasks,
                "written_batches": self.written_batches, "last_error": self.last_error}
