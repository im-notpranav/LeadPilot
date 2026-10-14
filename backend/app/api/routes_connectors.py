"""Connectors: how outside systems feed LeadPilot.

* Admin:  /api/connectors            create, configure, rotate secrets, disable, read the delivery log
* Public: /api/hooks/{id}            signed webhooks (LeadPilot events), forms, CRM records, inbound email
          /api/track/{site key}      the website tracker's page views and form submissions
          /api/t.js                  the tracker script itself
* Manager: /api/import/preview|commit  CSV / CRM-export import

Public endpoints authenticate with the connector's own secret (HMAC signature, or a URL token for tools that
cannot sign); the tracker's site key is public by design and only ever creates page views and form leads.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response

from ..auth import Principal
from ..connectors import csv_import, signing
from ..connectors.email_parse import email_event
from ..connectors.fields import CAPTURE_METHODS, FORM_KINDS, flatten, lead_events, lead_from_fields, page_category
from ..connectors.store import KINDS
from ..engine.types import iso
from .deps import state
from .security import admin, manager

public = APIRouter(prefix="/api")
admin_router = APIRouter(prefix="/api/connectors", dependencies=[Depends(admin)])
import_router = APIRouter(prefix="/api/import", dependencies=[Depends(manager)])

TRACKER_JS = (Path(__file__).resolve().parents[1] / "connectors" / "tracker.js").read_text(encoding="utf-8")
MAX_HOOK_BYTES = 1024 * 1024
MAX_TRACK_BYTES = 64 * 1024
MAX_RECORDS = 500
# Events only the engine itself writes, or that would let a sender drive the clock / merges / reviews.
BLOCKED_TYPES = {"quality_assessed", "lead_enriched", "lead_merged", "time_tick", "sla_check", "merge_approved",
                 "review_rejected", "quality_cleared"}
BOTS = re.compile(r"bot|crawl|spider|slurp|headless|lighthouse|pingdom|monitor|preview|facebookexternalhit", re.I)
VID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
ID_FIELDS = ("event_id", "submission_id", "submissionId", "response_id", "token", "hs_object_id", "objectId",
             "vid", "Id", "id", "uuid")


# ================================================================================================ helpers
class RateLimiter:
    """Sliding one-minute window per key, in memory."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str, per_minute: int, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= per_minute:
            return False
        q.append(now)
        if len(self.hits) > 50_000:                   # forget idle keys
            for k in [k for k, v in self.hits.items() if not v or now - v[-1] > 60]:
                del self.hits[k]
        return True


rate = RateLimiter()
replay_guard = signing.ReplayGuard()


def _view(c: dict, with_secret: bool = False) -> dict:
    out = {k: (iso(v) if isinstance(v, datetime) else v) for k, v in c.items() if k != "secret"}
    secret = c["secret"]
    if c["kind"] == "tracker":
        out["site_key"] = secret                      # public by design: it sits in every page's HTML
    else:
        out["secret_hint"] = secret[:10] + "…"
    if with_secret:
        out["secret"] = secret
    out["endpoint"] = f"/api/track/{secret}" if c["kind"] == "tracker" else f"/api/hooks/{c['id']}"
    out["status"] = "disabled" if c.get("revoked_at") else "active"
    if c["kind"] == "tracker":
        out["stats"] = state.connectors.tracker_stats(c["id"])
    return out


def _delivery_view(d: dict) -> dict:
    return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in d.items()}


def client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip() or None
    return request.client.host if request.client else None


async def publish(events: list[dict], via: str) -> list[dict]:
    out = []
    for ev in events:
        ev.setdefault("ingested_via", via)
        r = await state.bus.publish(ev)
        out.append({"event_id": r.get("event_id"), "type": ev.get("type"), "status": r.get("status"),
                    "lead_id": r.get("lead_id"), "reason": r.get("reason")})
    return out


def summarize(results: list[dict]) -> str:
    statuses = {r["status"] for r in results}
    if not results:
        return "ignored"
    if statuses == {"duplicate"}:
        return "duplicate"
    if statuses <= {"processed", "duplicate"}:
        return "accepted"
    if "processed" in statuses:
        return "partial"
    return "unresolved" if statuses <= {"unresolved", "duplicate"} else "rejected"


def _validate_settings(kind: str, settings: dict) -> dict:
    s = dict(settings or {})
    if "form_kind" in s and s["form_kind"] not in FORM_KINDS:
        raise HTTPException(422, f"form_kind must be one of {', '.join(FORM_KINDS)}")
    if "capture_method" in s and s["capture_method"] not in CAPTURE_METHODS:
        raise HTTPException(422, f"capture_method must be one of {', '.join(CAPTURE_METHODS)}")
    for flag in ("allow_token", "capture_forms", "use_record_source"):
        if flag in s:
            s[flag] = bool(s[flag])
    if "allowed_origins" in s:
        origins = s["allowed_origins"] or []
        if isinstance(origins, str):
            origins = [o for o in re.split(r"[\s,]+", origins) if o]
        clean = []
        for o in origins:
            host = (urlparse(o if "//" in o else f"//{o}").hostname or "").lower()
            if not host:
                raise HTTPException(422, f"not a host name: {o!r}")
            clean.append(host)
        s["allowed_origins"] = sorted(set(clean))
    if "page_rules" in s:
        rules = s["page_rules"] or []
        for r in rules:
            try:
                re.compile(r["pattern"])
                if not str(r["category"]).strip():
                    raise KeyError("category")
            except (re.error, KeyError, TypeError):
                raise HTTPException(422, f"page rule needs a valid regex 'pattern' and a 'category': {r!r}") from None
        s["page_rules"] = [{"pattern": r["pattern"], "category": str(r["category"]).strip()} for r in rules]
    if "field_map" in s:
        fm = s["field_map"] or {}
        if not isinstance(fm, dict) or any(v not in (*csv_import.TARGETS, "") for v in fm.values()):
            raise HTTPException(422, f"field_map values must be one of {', '.join(csv_import.TARGETS)} or ''")
        s["field_map"] = {str(k): v for k, v in fm.items()}
    return s


# ================================================================================================ admin
@admin_router.get("")
async def list_connectors():
    return {"items": [_view(c) for c in state.connectors.list()], "kinds": list(KINDS),
            "form_kinds": list(FORM_KINDS), "capture_methods": list(CAPTURE_METHODS),
            "fields": list(csv_import.TARGETS), "signature_tolerance_s": signing.TOLERANCE}


@admin_router.post("")
async def create_connector(body: dict = Body(...), p: Principal = Depends(admin)):
    kind = body.get("kind")
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(KINDS)}")
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "give the connector a name, e.g. 'Website demo form'")
    settings = _validate_settings(kind, body.get("settings") or {})
    source = (str(body.get("source") or "").strip().lower().replace(" ", "_") or None)
    row = await asyncio.to_thread(state.connectors.create, kind, name[:80], source, settings, p.email or p.name)
    return _view(row, with_secret=True)


@admin_router.patch("/{cid}")
async def update_connector(cid: str, body: dict = Body(...)):
    con = state.connectors.get(cid)
    if con is None:
        raise HTTPException(404, "connector not found")
    changes = {}
    if "name" in body:
        name = str(body["name"] or "").strip()
        if not name:
            raise HTTPException(422, "name cannot be empty")
        changes["name"] = name[:80]
    if "source" in body:
        changes["source"] = str(body["source"] or "").strip().lower().replace(" ", "_") or None
    if "settings" in body:
        changes["settings"] = _validate_settings(con["kind"], body["settings"] or {})
    row = await asyncio.to_thread(state.connectors.update, cid, changes)
    return _view(row)


@admin_router.post("/{cid}/reveal")
async def reveal_secret(cid: str):
    con = state.connectors.get(cid)
    if con is None:
        raise HTTPException(404, "connector not found")
    return {"id": cid, "secret": con["secret"]}


@admin_router.post("/{cid}/rotate")
async def rotate_secret(cid: str):
    try:
        row = await asyncio.to_thread(state.connectors.rotate, cid)
    except KeyError:
        raise HTTPException(404, "connector not found") from None
    return _view(row, with_secret=True)


@admin_router.delete("/{cid}")
async def disable_connector(cid: str):
    try:
        row = await asyncio.to_thread(state.connectors.revoke, cid)
    except KeyError:
        raise HTTPException(404, "connector not found") from None
    return _view(row)


@admin_router.get("/{cid}/deliveries")
async def deliveries(cid: str, limit: int = 100):
    if state.connectors.get(cid) is None:
        raise HTTPException(404, "connector not found")
    return {"items": [_delivery_view(d) for d in state.connectors.recent(cid, min(limit, 500))]}


# ================================================================================================ inbound hooks
async def _parse_body(request: Request, raw: bytes):
    ctype = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in ctype:
        return dict(parse_qsl(raw.decode("utf-8", "replace"), keep_blank_values=False))
    if "multipart/form-data" in ctype:
        form = await request.form()
        return {k: v for k, v in form.items() if isinstance(v, str)}
    try:
        return json.loads(raw or b"null")
    except ValueError:
        raise HTTPException(400, "body must be JSON, form-encoded or multipart form data") from None


def _record_id(rec: dict, flat: dict) -> str | None:
    for k in ID_FIELDS:
        v = rec.get(k)
        if v in (None, "") and k in flat:
            v = flat[k]
        if v not in (None, "") and not isinstance(v, (dict, list)):
            return str(v)
    return None


def _webhook_events(data) -> list[dict]:
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and isinstance(data.get("events"), list):
        items = data["events"]
    else:
        items = [data]
    if len(items) > MAX_RECORDS:
        raise HTTPException(413, f"send at most {MAX_RECORDS} events per request")
    for ev in items:
        if not isinstance(ev, dict) or not ev.get("type"):
            raise HTTPException(422, "each event needs a 'type'")
        if ev["type"] in BLOCKED_TYPES:
            raise HTTPException(422, f"'{ev['type']}' events are written by LeadPilot itself")
    return [dict(ev) for ev in items]


def _record_events(con: dict, data, ip: str | None) -> tuple[list[dict], list[dict]]:
    """Form / CRM records -> events; also returns per-record errors."""
    s = con.get("settings") or {}
    if isinstance(data, list):
        records = data
    elif isinstance(data, dict) and isinstance(data.get("records"), list):
        records = data["records"]
    else:
        records = [data]
    if len(records) > MAX_RECORDS:
        raise HTTPException(413, f"send at most {MAX_RECORDS} records per request")
    is_form = con["kind"] == "form"
    events, errors = [], []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            errors.append({"index": i, "status": "rejected", "reason": "each record must be an object"})
            continue
        flat = flatten(rec)
        form_name = flat.get("form_name") or flat.get("formName") or (rec.get("name") if "data" in rec else None)
        m = lead_from_fields(flat, source=con["source"], capture_method=s.get("capture_method", "form_submit"),
                             form_name=form_name, form_kind=s.get("form_kind", "auto") if is_form else "none",
                             column_map=s.get("field_map"), use_record_source=bool(s.get("use_record_source")),
                             ip=ip if is_form else None)
        if not m["ok"]:
            errors.append({"index": i, "status": "rejected", "reason": m["error"]})
            continue
        rid = _record_id(rec, flat)
        basis = f"{con['id']}|{rid}" if rid else f"{con['id']}|{json.dumps(rec, sort_keys=True, default=str)}"
        events.extend(lead_events(m, f"{con['kind'][:3]}_{hashlib.sha256(basis.encode()).hexdigest()[:20]}"))
    return events, errors


@public.post("/hooks/{cid}")
async def receive_hook(cid: str, request: Request):
    con = state.connectors.get(cid)
    if con is None:
        raise HTTPException(404, "unknown connector")
    if con.get("revoked_at"):
        raise HTTPException(410, "this connector has been disabled")
    raw = await request.body()
    sample = raw[:2000].decode("utf-8", "replace")

    def refuse(status: int, reason: str):
        state.connectors.record(cid, status="rejected", http_status=status, reason=reason, sample=sample)
        raise HTTPException(status, reason)

    if len(raw) > MAX_HOOK_BYTES:
        refuse(413, "body larger than 1 MB")
    settings = con.get("settings") or {}
    if request.headers.get("x-leadpilot-signature") or request.headers.get("x-leadpilot-timestamp"):
        try:
            signing.verify(con["secret"], request.headers, raw, replay_guard)
        except signing.SignatureError as exc:
            refuse(exc.status, exc.reason)
    elif settings.get("allow_token"):
        if not signing.token_matches(con["secret"], request.query_params.get("token")
                                     or request.headers.get("x-leadpilot-token")):
            refuse(401, "missing or wrong token: add ?token=<secret> or sign the request")
    else:
        refuse(401, "this connector requires a signed request (X-LeadPilot-Timestamp / X-LeadPilot-Signature)")

    try:
        data = await _parse_body(request, raw)
        errors: list[dict] = []
        if con["kind"] == "webhook":
            events = _webhook_events(data)
            for ev in events:
                ev.setdefault("source", con["source"])
        elif con["kind"] in ("form", "crm"):
            events, errors = _record_events(con, data, client_ip(request))
        elif con["kind"] == "email":
            if not isinstance(data, dict):
                raise HTTPException(422, "an inbound email must be one JSON object or form post")
            parsed = email_event(data, source=con["source"])
            if not parsed["ok"]:
                raise HTTPException(422, parsed["error"])
            events = [parsed["event"]]
        else:
            raise HTTPException(400, "tracker connectors receive data at /api/track/{site key}")
    except HTTPException as exc:
        refuse(exc.status_code, exc.detail)

    results = await publish(events, f"connector:{cid}") + errors
    status = summarize(results)
    state.connectors.record(cid, status=status, http_status=200, events=len(events), results=results, sample=sample,
                            reason=next((r["reason"] for r in results if r.get("reason")), None))
    return {"status": status, "results": results}


# ================================================================================================ website tracker
@public.get("/t.js", include_in_schema=False)
async def tracker_script():
    return Response(TRACKER_JS, media_type="application/javascript; charset=utf-8",
                    headers={"Cache-Control": "public, max-age=300", "Access-Control-Allow-Origin": "*"})


def _origin_allowed(con: dict, request: Request) -> bool:
    allowed = (con.get("settings") or {}).get("allowed_origins") or []
    if not allowed:
        return True
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    host = (urlparse(origin).hostname or "").lower()
    return bool(host) and any(host == a or host.endswith("." + a) for a in allowed)


@public.post("/track/{key}", status_code=204)
async def track(key: str, request: Request):
    con = state.connectors.by_site_key(key)
    if con is None or con.get("revoked_at"):
        raise HTTPException(404, "unknown site key")
    if not _origin_allowed(con, request):
        raise HTTPException(403, "this site is not allowed to send to this tracker")
    ip = client_ip(request)
    if not rate.allow(f"ip:{key}:{ip}", 300):
        raise HTTPException(429, "too many requests")
    raw = await request.body()
    if len(raw) > MAX_TRACK_BYTES:
        raise HTTPException(413, "too large")
    if BOTS.search(request.headers.get("user-agent") or ""):
        return Response(status_code=204)
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise HTTPException(400, "expected a JSON object")
    vid = str(data.get("vid") or "")
    if not VID.match(vid):
        raise HTTPException(400, "missing visitor id")
    if not rate.allow(f"vid:{key}:{vid}", 60):
        raise HTTPException(429, "too many requests")
    cid, s = con["id"], con.get("settings") or {}
    visitor = state.connectors.visitor(cid, vid)

    if data.get("type") == "page_view":
        path = str(data.get("path") or "/")[:300]
        payload = {"url": str(data.get("url") or "")[:500] or None, "path": path,
                   "title": str(data.get("title") or "")[:200] or None,
                   "referrer": str(data.get("referrer") or "")[:500] or None,
                   "page_category": page_category(path, s.get("page_rules")), "anonymous_id": vid}
        ev = {"event_id": "trk_" + secrets.token_hex(8), "type": "page_view", "ts": iso(state.runtime.clock.now()),
              "source": con["source"], "payload": {k: v for k, v in payload.items() if v is not None}}
        if visitor["email"]:
            state.connectors.seen_page(cid, vid, None)
            await publish([{**ev, "lead_ref": {"email": visitor["email"]}}], f"tracker:{cid}")
        else:
            state.connectors.seen_page(cid, vid, ev)       # waits until the visitor fills in a form
        return Response(status_code=204)

    if data.get("type") == "identify":
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        fields = {str(k)[:100]: str(v)[:2000] for k, v in list(fields.items())[:60]}
        form_name = str(data.get("form_name") or "")[:120] or None
        m = lead_from_fields(fields, source=con["source"], capture_method="form_submit", form_name=form_name, ip=ip)
        email = m["payload"].get("email") if m["ok"] else None
        if not email:
            return Response(status_code=204)
        pending = state.connectors.identify(cid, vid, email)
        events = lead_events(m, "trk_" + secrets.token_hex(8)) if s.get("capture_forms", True) else []
        replay = [{**ev, "lead_ref": {"email": email}} for ev in pending]
        results = await publish(events + replay, f"tracker:{cid}")
        state.connectors.record(cid, status=summarize(results), http_status=204, events=len(results),
                                results=results, sample=json.dumps({"form_name": form_name, "email": email,
                                                                    "page_views_linked": len(replay)}))
        return Response(status_code=204)
    raise HTTPException(400, "type must be page_view or identify")


# ================================================================================================ CSV import
def _import_args(body: dict) -> dict:
    csv_text = body.get("csv")
    if not isinstance(csv_text, str):
        raise HTTPException(422, "send the file contents as 'csv'")
    source = str(body.get("source") or "csv_import").strip().lower().replace(" ", "_")[:40] or "csv_import"
    column_map = body.get("column_map") or {}
    if not isinstance(column_map, dict) or any(v not in (*csv_import.TARGETS, "") for v in column_map.values()):
        raise HTTPException(422, f"column_map values must be one of {', '.join(csv_import.TARGETS)} or ''")
    return {"text": csv_text, "source": source, "capture_method": body.get("capture_method") or "cold_import",
            "column_map": column_map, "use_record_source": bool(body.get("use_record_source", True))}


def _map(body: dict) -> dict:
    try:
        return csv_import.map_rows(**_import_args(body), now=state.runtime.clock.now())
    except csv_import.CsvImportError as exc:
        raise HTTPException(422, str(exc)) from None


@import_router.post("/preview")
async def import_preview(body: dict = Body(...)):
    plan = await asyncio.to_thread(_map, body)
    return {**{k: v for k, v in plan.items() if k not in ("events", "rows")},
            "sample": [r for r in plan["rows"] if r["ok"]][:25],
            "errors": [r for r in plan["rows"] if not r["ok"]][:100], "events": len(plan["events"])}


@import_router.post("/commit")
async def import_commit(body: dict = Body(...), p: Principal = Depends(manager)):
    plan = await asyncio.to_thread(_map, body)
    t0 = time.perf_counter()
    results = await publish(plan["events"], f"import:{p.email or p.name}:{plan['batch_id']}")
    created = [r for r in results if r["type"] == "lead_created"]
    by_status: dict[str, int] = defaultdict(int)
    for r in created:
        by_status[r["status"]] += 1
    return {"batch_id": plan["batch_id"], "counts": plan["counts"], "leads": dict(by_status),
            "events": len(results), "lead_ids": sorted({r["lead_id"] for r in created if r.get("lead_id")})[:500],
            "errors": [r for r in plan["rows"] if not r["ok"]][:100], "seconds": round(time.perf_counter() - t0, 2)}
