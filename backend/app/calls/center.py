"""Calls from arrival to event: store the call, analyse it once (Gemini, or rules when Gemini is not set up), keep a
copy of the recording, then publish a `call_logged` event (and `meeting_scheduled` when a meeting was agreed) with
the analysis inside it.

The analysis lives in the event, so replays, restarts and settings activations rebuild the same scores and stages
without calling Gemini again. Calls themselves are source data like the raw event log: kept through replays,
cleared by a demo reset.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import logging
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from ..engine.types import iso
from ..models import tables as T
from .gemini import Gemini, GeminiError
from .parse import prospect_text, rule_analysis
from .storage import RecordingStore, StorageError

log = logging.getLogger("leadpilot.calls")

KEEP = 5000
PENDING = ("queued", "analyzing")
RESULT_LABEL = {"meeting_booked": "meeting booked", "interested": "interested", "callback_requested": "call back",
                "needs_info": "needs more info", "not_interested": "not interested", "wrong_person": "wrong person",
                "no_conversation": "no conversation"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def call_key(provider: str, provider_call_id: str) -> str:
    return f"{provider}:{provider_call_id}"


def event_id_for(cid: str) -> str:
    return "call_" + hashlib.sha256(cid.encode()).hexdigest()[:20]


class CallCenter:
    def __init__(self, db, gemini: Gemini | None = None, recordings: RecordingStore | None = None):
        self.db = db
        self.gemini = gemini or Gemini()
        self.recordings = recordings or RecordingStore(None)
        self.calls: OrderedDict[str, dict] = OrderedDict()
        self.runtime = None
        self.publish = None                      # async (events) -> results; main wires the event bus in
        self.live = False
        self.queue: asyncio.Queue | None = None
        self._lock = threading.Lock()
        if getattr(db, "enabled", False):
            with db.engine.connect() as conn:
                rows = conn.execute(select(T.calls).order_by(T.calls.c.created_at.desc()).limit(KEEP)).mappings().all()
            for r in reversed(rows):
                self.calls[r["id"]] = dict(r)

    def attach(self, runtime, publish, live: bool) -> None:
        self.runtime, self.publish, self.live = runtime, publish, live

    def reset(self) -> None:
        with self._lock:
            self.calls.clear()

    # ---------------------------------------------------------------- arrival
    def receive(self, call: dict, connector_id: str | None = None) -> tuple[dict, bool]:
        """Store a new call and queue it. Returns (record, is_new); a call seen before is left alone."""
        cid = call_key(call["provider"], call["provider_call_id"])
        with self._lock:
            old = self.calls.get(cid)
            if old is not None:
                return old, False
            now = _now()
            rec = {**copy.deepcopy(call), "id": cid, "connector_id": connector_id, "status": "queued",
                   "lead_id": None, "analysis": None, "analyzed_by": None, "error": None, "event_ids": [],
                   "recording_path": None, "created_at": now, "updated_at": now}
            self.calls[cid] = rec
            while len(self.calls) > KEEP:
                self.calls.popitem(last=False)
        self._save(rec)
        if self.queue is not None:
            self.queue.put_nowait(cid)
        return rec, True

    def _save(self, rec: dict) -> None:
        rec["updated_at"] = _now()
        if getattr(self.db, "enabled", False):
            self.db.write_now("calls", {c.name: rec.get(c.name) for c in T.calls.columns})

    async def _save_async(self, rec: dict) -> None:
        await asyncio.to_thread(self._save, rec)

    async def run(self) -> None:
        """Worker loop (started by main): one call at a time, so Gemini and the recording copy never pile up."""
        self.queue = asyncio.Queue()
        for cid, rec in list(self.calls.items()):     # anything a restart interrupted
            if rec["status"] in PENDING:
                self.queue.put_nowait(cid)
        while True:
            cid = await self.queue.get()
            try:
                await self.process(cid)
            except Exception:  # noqa: BLE001 - one bad call must not stop the others
                log.exception("processing call %s failed", cid)

    # ---------------------------------------------------------------- processing
    def _lead(self, ref: dict):
        rt = self.runtime
        if rt is None or not ref:
            return None
        return rt.processor._resolve(SimpleNamespace(lead_ref=ref))

    async def process(self, cid: str) -> dict:
        rec = self.calls[cid]
        lead = self._lead(rec.get("lead_ref") or {})
        if lead is None:
            rec.update(status="unmatched", error="No lead has this phone number or email yet. Link the call to a lead.")
            await self._save_async(rec)
            return rec
        rec.update(status="analyzing", lead_id=lead.lead_id, error=None)
        await self._save_async(rec)

        name = lead.profile.name if lead.profile else lead.lead_id
        if rec.get("analysis") is None:
            rec["analysis"], rec["analyzed_by"], note = await self._analyze(rec, name)
            if note:
                rec["error"] = note
        if rec.get("recording_url") and not rec.get("recording_path") and self.recordings.configured:
            try:
                rec["recording_path"] = await self.recordings.copy_from(rec["recording_url"], cid.replace(":", "/"))
            except StorageError as e:
                rec["error"] = "; ".join(x for x in (rec.get("error"), f"Recording not copied: {e}") if x)

        events = self.events_for(rec, lead)
        results = await self.publish(events) if self.publish else []
        bad = [r for r in results if r.get("status") not in ("processed", "duplicate")]
        rec["event_ids"] = [e["event_id"] for e in events]
        rec["status"] = "failed" if bad else "done"
        if bad:
            rec["error"] = f"The event was refused: {bad[0].get('reason') or bad[0].get('status')}"
        await self._save_async(rec)
        return rec

    async def _analyze(self, rec: dict, lead_name: str) -> tuple[dict, str, str | None]:
        cfg = self.runtime.cfg
        hint = rec.get("outcome_hint")
        talk = prospect_text(rec.get("transcript") or "").strip()
        note = None
        if self.gemini.configured and len(talk) >= 20 and hint in (None, "connected"):
            try:
                a = await self.gemini.analyze_call(rec["transcript"], rec["direction"], lead_name, rec.get("duration_s"))
                if hint:
                    a["outcome"] = hint
                return a, f"gemini:{self.gemini.model}", None
            except GeminiError as e:
                note = f"Gemini analysis failed, so rules were used: {e}"
                log.warning("call %s: %s", rec["id"], e)
        a = rule_analysis(rec, cfg)
        by = "provider" if (rec.get("provider_analysis") or {}).get("summary") else "rules"
        return a, by, note

    def events_for(self, rec: dict, lead) -> list[dict]:
        """The events a processed call becomes. Same call → same event ids, so a re-delivery changes nothing."""
        a = rec["analysis"]
        rt = self.runtime
        when = rec.get("ended_at") or rec.get("started_at")
        now = rt.clock.now() if rt else _now()
        ts = when if (self.live and when) else now          # demo runs on its own clock: file the call "now"
        rep = rec.get("rep_id") or lead.owner
        mgr_q = rt.cfg.assignment.reassignment.manager_queue_id if rt else None
        rep = None if rep == mgr_q else rep
        actor = "prospect" if rec["direction"] == "inbound" else "rep"
        eid = event_id_for(rec["id"])
        base = {"ts": iso(ts), "lead_ref": {"lead_id": lead.lead_id}, "source": "call", "rep_id": rep}
        payload = {"call_id": rec["id"], "provider": rec["provider"], "direction": rec["direction"],
                   "duration_s": round(rec["duration_s"], 1) if rec.get("duration_s") is not None else None,
                   **a, "analyzed_by": rec["analyzed_by"],
                   "has_recording": bool(rec.get("recording_path") or rec.get("recording_url"))}
        events = [{**base, "event_id": eid, "type": "call_logged", "actor": actor, "payload": payload}]
        if a.get("meeting_booked"):
            events.append({**base, "event_id": f"{eid}.m", "type": "meeting_scheduled", "actor": "rep",
                           "payload": {"from_call": rec["id"], "meeting_type": "discovery",
                                       "note": a.get("next_step") or "Agreed on the call"}})
        return events

    # ---------------------------------------------------------------- fixing up
    async def link(self, cid: str, lead_id: str) -> dict:
        rec = self.calls[cid]
        rec.update(lead_ref={"lead_id": lead_id}, status="queued", error=None)
        await self._save_async(rec)
        return await self.process(cid)

    async def retry(self, cid: str) -> dict:
        rec = self.calls[cid]
        rec.update(analysis=None, analyzed_by=None, status="queued", error=None)
        return await self.process(cid)

    # ---------------------------------------------------------------- reading
    def for_lead(self, lead_ids: set[str]) -> list[dict]:
        return [r for r in reversed(self.calls.values()) if r.get("lead_id") in lead_ids]

    def view(self, rec: dict, full: bool = False) -> dict:
        out = {k: rec.get(k) for k in ("id", "provider", "provider_call_id", "direction", "status", "lead_id", "rep_id",
                                       "duration_s", "analysis", "analyzed_by", "error", "event_ids",
                                       "disconnection_reason")}
        out.update(started_at=iso(rec.get("started_at")), ended_at=iso(rec.get("ended_at")),
                   created_at=iso(rec.get("created_at")),
                   has_recording=bool(rec.get("recording_path") or rec.get("recording_url")),
                   recording_stored=bool(rec.get("recording_path")),
                   number=rec.get("to_number") if rec.get("direction") == "outbound" else rec.get("from_number"))
        if full:
            out["transcript"] = rec.get("transcript") or ""
        return out

    async def recording_link(self, rec: dict) -> str | None:
        if rec.get("recording_path") and self.recordings.configured:
            return await self.recordings.signed_url(rec["recording_path"])
        return rec.get("recording_url")

    def status(self) -> dict:
        return {"gemini": {"configured": self.gemini.configured, "model": self.gemini.model},
                "recordings": {"configured": self.recordings.configured, "bucket": self.recordings.bucket}}
