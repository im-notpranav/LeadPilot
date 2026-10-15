"""Connectors, their delivery log and website visitors: cached in memory, written to the database in the background.

Connector definitions change rarely and are written at once. Deliveries, visitor state and "last received"
counters change on every inbound request, so they are marked dirty and written by `flush()` every few seconds
(off the event loop), which keeps webhook and tracker requests fast even with a remote database.
"""
from __future__ import annotations

import logging
import secrets
import threading
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import tables as T

log = logging.getLogger("leadpilot.connectors")

KINDS = ("webhook", "form", "crm", "email", "tracker", "call")
DEFAULTS: dict[str, dict] = {
    "webhook": {"allow_token": False},
    "form": {"allow_token": True, "form_kind": "auto", "capture_method": "form_submit", "field_map": {}},
    "crm": {"allow_token": False, "capture_method": "form_submit", "field_map": {}, "use_record_source": True},
    "email": {"allow_token": True},
    "tracker": {"allowed_origins": [], "page_rules": [], "capture_forms": True},
    # Phone calls: Retell's webhook (signed with RETELL_API_KEY) or LeadPilot's generic call format.
    # process_on (Retell): auto = call_ended when Gemini is set up, otherwise call_analyzed (Retell's own summary).
    "call": {"allow_token": True, "provider": "retell", "process_on": "auto"},
}
DEFAULT_SOURCE = {"webhook": None, "form": "website", "crm": "crm", "email": "email", "tracker": "website",
                  "call": "call"}
MAX_PENDING = 50               # anonymous page views kept per visitor until they identify themselves
MAX_DELIVERIES = 1000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_secret(kind: str) -> str:
    return ("lpk_" + secrets.token_urlsafe(12)) if kind == "tracker" else ("whsec_" + secrets.token_urlsafe(24))


class ConnectorStore:
    def __init__(self, db):
        self.db = db
        self._lock = threading.Lock()
        self.connectors: dict[str, dict] = {}
        self.visitors: dict[str, dict] = {}
        self.deliveries: deque = deque(maxlen=MAX_DELIVERIES)
        self._dirty: dict[str, dict[str, dict]] = {"connectors": {}, "connector_deliveries": {}, "tracker_visitors": {}}
        if getattr(db, "enabled", False):
            with db.engine.connect() as conn:
                self.connectors = {r["id"]: dict(r) for r in conn.execute(select(T.connectors)).mappings()}
                self.visitors = {r["id"]: dict(r) for r in conn.execute(select(T.tracker_visitors)).mappings()}
                recent = conn.execute(select(T.connector_deliveries)
                                      .order_by(T.connector_deliveries.c.received_at.desc())
                                      .limit(MAX_DELIVERIES)).mappings()
                self.deliveries.extend(reversed([dict(r) for r in recent]))
        self.by_secret = {c["secret"]: c for c in self.connectors.values()}

    # ------------------------------------------------------------------ persistence
    def _save_now(self, table: str, row: dict) -> None:
        if getattr(self.db, "enabled", False):
            self.db.write_now(table, row)

    def _mark(self, table: str, row: dict) -> None:
        self._dirty[table][row["id"]] = dict(row)

    def flush(self) -> int:
        """Write dirty rows (blocking: call from a thread). Returns how many rows were written."""
        with self._lock:
            dirty, self._dirty = self._dirty, {t: {} for t in self._dirty}
        if not getattr(self.db, "enabled", False):
            return 0
        n = 0
        try:
            for table, rows in dirty.items():
                if rows:
                    self.db.write_rows(table, list(rows.values()))
                    n += len(rows)
        except Exception:  # noqa: BLE001 - put them back and retry on the next flush
            log.exception("connector state write failed; will retry")
            with self._lock:
                for table, rows in dirty.items():
                    for k, v in rows.items():
                        self._dirty[table].setdefault(k, v)
            return 0
        return n

    # ------------------------------------------------------------------ connectors
    def create(self, kind: str, name: str, source: str | None, settings: dict | None, created_by: str | None) -> dict:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        row = {"id": "con_" + secrets.token_hex(5), "kind": kind, "name": name, "secret": new_secret(kind),
               "source": source or DEFAULT_SOURCE[kind], "settings": {**DEFAULTS[kind], **(settings or {})},
               "created_by": created_by, "created_at": _now(), "last_received_at": None, "received_count": 0,
               "revoked_at": None}
        with self._lock:
            self.connectors[row["id"]] = row
            self.by_secret[row["secret"]] = row
        self._save_now("connectors", row)
        return dict(row)

    def update(self, cid: str, changes: dict) -> dict:
        with self._lock:
            row = self.connectors.get(cid)
            if row is None:
                raise KeyError(cid)
            if "name" in changes:
                row["name"] = changes["name"]
            if "source" in changes:
                row["source"] = changes["source"] or DEFAULT_SOURCE[row["kind"]]
            if "settings" in changes:
                row["settings"] = {**DEFAULTS[row["kind"]], **(row.get("settings") or {}), **changes["settings"]}
            snapshot = dict(row)
        self._save_now("connectors", snapshot)
        return snapshot

    def rotate(self, cid: str) -> dict:
        with self._lock:
            row = self.connectors.get(cid)
            if row is None:
                raise KeyError(cid)
            self.by_secret.pop(row["secret"], None)
            row["secret"] = new_secret(row["kind"])
            self.by_secret[row["secret"]] = row
            snapshot = dict(row)
        self._save_now("connectors", snapshot)
        return snapshot

    def revoke(self, cid: str) -> dict:
        with self._lock:
            row = self.connectors.get(cid)
            if row is None:
                raise KeyError(cid)
            row["revoked_at"] = row["revoked_at"] or _now()
            snapshot = dict(row)
        self._save_now("connectors", snapshot)
        return snapshot

    def get(self, cid: str) -> dict | None:
        row = self.connectors.get(cid)
        return dict(row) if row else None

    def by_site_key(self, key: str) -> dict | None:
        row = self.by_secret.get(key)
        return dict(row) if row and row["kind"] == "tracker" else None

    def list(self) -> list[dict]:
        with self._lock:
            return sorted((dict(c) for c in self.connectors.values()), key=lambda c: c["created_at"], reverse=True)

    # ------------------------------------------------------------------ deliveries
    def record(self, cid: str, *, status: str, http_status: int, reason: str | None = None, events: int = 0,
               results: list | None = None, sample: str | None = None, count: bool = True) -> dict:
        now = _now()
        row = {"id": "dlv_" + secrets.token_hex(6), "connector_id": cid, "received_at": now, "status": status,
               "http_status": http_status, "reason": reason, "events": events, "results": results or [],
               "sample": (sample or "")[:2000] or None}
        with self._lock:
            self.deliveries.append(row)
            self._mark("connector_deliveries", row)
            con = self.connectors.get(cid)
            if con is not None and count:
                con["last_received_at"] = now
                con["received_count"] = (con.get("received_count") or 0) + 1
                self._mark("connectors", con)
        return row

    def recent(self, cid: str | None = None, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = [dict(d) for d in reversed(self.deliveries) if cid is None or d["connector_id"] == cid]
        return rows[:limit]

    # ------------------------------------------------------------------ website visitors
    def visitor(self, cid: str, vid: str) -> dict:
        key = f"{cid}:{vid}"
        with self._lock:
            row = self.visitors.get(key)
            if row is None:
                now = _now()
                row = self.visitors[key] = {"id": key, "connector_id": cid, "email": None, "first_seen": now,
                                            "last_seen": now, "page_views": 0, "pending": []}
            return dict(row, pending=list(row.get("pending") or []))

    def seen_page(self, cid: str, vid: str, event: dict | None) -> None:
        """Count a page view; keep it in `pending` while the visitor is anonymous (event is None once known)."""
        key = f"{cid}:{vid}"
        with self._lock:
            row = self.visitors[key]
            row["last_seen"] = _now()
            row["page_views"] = (row.get("page_views") or 0) + 1
            if event is not None:
                row["pending"] = ((row.get("pending") or []) + [event])[-MAX_PENDING:]
            self._mark("tracker_visitors", row)

    def identify(self, cid: str, vid: str, email: str) -> list[dict]:
        """Attach an email to a visitor and hand back the anonymous page views to replay for them."""
        key = f"{cid}:{vid}"
        with self._lock:
            row = self.visitors[key]
            pending, row["pending"] = list(row.get("pending") or []), []
            row["email"] = email
            row["last_seen"] = _now()
            self._mark("tracker_visitors", row)
        return pending

    def tracker_stats(self, cid: str) -> dict:
        with self._lock:
            rows = [v for v in self.visitors.values() if v["connector_id"] == cid]
        return {"visitors": len(rows), "identified": sum(1 for v in rows if v.get("email")),
                "page_views": sum(v.get("page_views") or 0 for v in rows)}
