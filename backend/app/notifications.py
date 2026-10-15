"""Notifications: turn what happens in the engine into messages for the right people, in the app and, once their
keys are set, by email (Resend), Slack (incoming webhook) and SMS (Twilio).

Notifications are side effects, not projections: the processor only reports messages while it broadcasts, which it
never does during replays, restarts, settings activations or the demo warm-up. So a replay never notifies anyone
again, and the notification tables survive replays (only a demo reset clears them).

The rules (who hears about what, on which channels) are in backend/config/notifications.yaml.
"""
from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select

from .config import CONFIG_DIR
from .engine.types import iso
from .models import tables as T

log = logging.getLogger("leadpilot.notifications")

RULES_FILE = CONFIG_DIR / "notifications.yaml"
SEVERITIES = ("info", "important", "urgent")
EXTERNAL = ("email", "slack", "sms")
MEETING_TEXT = {"meeting_scheduled": "booked a meeting", "demo_request": "requested a demo",
                "contact_sales": "asked to talk to sales"}


def load_rules(path: Path = RULES_FILE) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = data.get("rules") or {}
    for name, r in rules.items():
        r.setdefault("enabled", True)
        r["to"] = list(r.get("to") or [])
        r["channels"] = [c for c in (r.get("channels") or ["in_app"]) if c in ("in_app", *EXTERNAL)]
        if r.get("severity") not in SEVERITIES:
            r["severity"] = "info"
    return {"rules": rules, "keep_in_memory": int(data.get("keep_in_memory") or 2000)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _real(value: str | None) -> str | None:
    return value.strip() if value and value.strip() and "<" not in value else None


def mask_phone(phone: str | None) -> str | None:
    return f"…{phone[-4:]}" if phone and len(phone) > 4 else phone


# ================================================================================================ channels
class Channels:
    """Delivery channels, configured from the environment. A channel without its keys is off."""

    def __init__(self, env: dict | None = None, transport=None):
        env = os.environ if env is None else env
        self.resend_key = _real(env.get("RESEND_API_KEY"))
        self.email_from = (env.get("LEADPILOT_EMAIL_FROM") or "").strip() or None   # "Name <a@b.c>" is fine
        self.slack_url = _real(env.get("SLACK_WEBHOOK_URL"))
        self.twilio_sid = _real(env.get("TWILIO_ACCOUNT_SID"))
        self.twilio_token = _real(env.get("TWILIO_AUTH_TOKEN"))
        self.twilio_from = _real(env.get("TWILIO_FROM_NUMBER"))
        self.public_url = (_real(env.get("LEADPILOT_PUBLIC_URL")) or "").rstrip("/") or None
        self.in_demo = (env.get("LEADPILOT_NOTIFY_IN_DEMO") or "").strip().lower() in ("1", "true", "yes", "on")
        self.transport = transport               # tests pass an httpx.MockTransport

    def configured(self, channel: str) -> bool:
        if channel == "in_app":
            return True
        if channel == "email":
            return bool(self.resend_key and self.email_from)
        if channel == "slack":
            return bool(self.slack_url)
        if channel == "sms":
            return bool(self.twilio_sid and self.twilio_token and self.twilio_from)
        return False

    def status(self) -> list[dict]:
        need = {"email": ["RESEND_API_KEY", "LEADPILOT_EMAIL_FROM"], "slack": ["SLACK_WEBHOOK_URL"],
                "sms": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"]}
        label = {"email": "Email (Resend)", "slack": "Slack", "sms": "SMS (Twilio)"}
        return [{"channel": "in_app", "label": "In the app", "configured": True, "needs": []}] + [
            {"channel": c, "label": label[c], "configured": self.configured(c), "needs": need[c]} for c in EXTERNAL]

    def link(self, path: str | None) -> str | None:
        return f"{self.public_url}{path}" if self.public_url and path else None

    def client(self):
        import httpx
        return httpx.AsyncClient(timeout=10.0, transport=self.transport)

    async def send(self, client, channel: str, to: str | None, n: dict) -> dict:
        """Send one notification on one channel. Returns {status: sent | failed, detail}."""
        url = self.link(n.get("link"))
        try:
            if channel == "email":
                text = n["body"] + (f"\n\nOpen in LeadPilot: {url}" if url else "")
                r = await client.post("https://api.resend.com/emails",
                                      headers={"Authorization": f"Bearer {self.resend_key}"},
                                      json={"from": self.email_from, "to": [to], "subject": n["title"], "text": text})
            elif channel == "slack":
                text = f"*{n['title']}*\n{n['body']}" + (f"\n<{url}|Open in LeadPilot>" if url else "")
                r = await client.post(self.slack_url, json={"text": text})
            elif channel == "sms":
                body = f"{n['title']}: {n['body']}"[:300] + (f" {url}" if url else "")
                r = await client.post(
                    f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json",
                    auth=(self.twilio_sid, self.twilio_token), data={"From": self.twilio_from, "To": to, "Body": body})
            else:
                return {"status": "failed", "detail": f"unknown channel {channel}"}
        except Exception as e:  # noqa: BLE001 - network errors are recorded, never raised into the engine
            return {"status": "failed", "detail": f"{type(e).__name__}: {e}"[:300]}
        if r.status_code >= 400:
            return {"status": "failed", "detail": f"HTTP {r.status_code}: {r.text[:200]}"}
        return {"status": "sent", "detail": None}


# ================================================================================================ center
class NotificationCenter:
    """Creates notifications from engine messages, keeps the newest in memory, tracks who read what, and queues
    external deliveries for the async delivery loop."""

    def __init__(self, db, accounts, channels: Channels | None = None, rules: dict | None = None,
                 live: bool = False):
        self.db = db
        self.accounts = accounts
        self.channels = channels or Channels()
        cfg = rules or load_rules()
        self.rules = cfg["rules"]
        self.items: deque = deque(maxlen=cfg["keep_in_memory"])
        self.reads: dict[str, dict] = {}            # user key -> {"last_read_id": int, "read_ids": set}
        self.live = live
        self.runtime = None
        self.pending: queue.SimpleQueue = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._next = 1
        if getattr(db, "enabled", False):
            self._load()

    def _load(self) -> None:
        with self.db.engine.connect() as conn:
            rows = conn.execute(select(T.notifications).order_by(T.notifications.c.id.desc())
                                .limit(self.items.maxlen)).mappings().all()
            ids = [r["id"] for r in rows]
            dels: dict[int, list] = {}
            if ids:
                q = select(T.notification_deliveries).where(T.notification_deliveries.c.notification_id >= min(ids))
                for d in conn.execute(q.order_by(T.notification_deliveries.c.id)).mappings():
                    dels.setdefault(d["notification_id"], []).append(self._delivery_view(dict(d)))
            for r in reversed(rows):
                n = dict(r)
                n["ts"] = iso(n["ts"])
                n["deliveries"] = dels.get(n["id"], [])
                self.items.append(n)
            last = conn.execute(select(T.notifications.c.id).order_by(T.notifications.c.id.desc()).limit(1)).scalar()
            self._next = (last or 0) + 1
            for r in conn.execute(select(T.notification_reads)).mappings():
                self.reads[r["user_key"]] = {"last_read_id": r["last_read_id"] or 0, "read_ids": set(r["read_ids"] or [])}

    def attach(self, runtime) -> None:
        self.runtime = runtime
        runtime.processor.listeners.append(self.on_message)

    def reset(self) -> None:
        """Demo reset: the tables were wiped with everything else, so start over."""
        with self._lock:
            self.items.clear()
            self.reads.clear()
            self._next = 1
        while not self.pending.empty():
            self.pending.get_nowait()

    # ---------------------------------------------------------------- creating (under the runtime lock)
    def on_message(self, kind: str, data: dict) -> None:
        try:
            self._route(kind, data)
        except Exception:  # noqa: BLE001 - a notification problem must never stop event processing
            log.exception("could not create a notification for %s", kind)

    def _route(self, kind: str, d: dict) -> None:
        rt = self.runtime
        store = rt.store
        lead = store.leads.get(d.get("lead_id") or "") if d.get("lead_id") else None
        who = _who(lead)
        link = f"/leads/{lead.lead_id}" if lead else None
        mgr_q = rt.cfg.assignment.reassignment.manager_queue_id

        if kind in ("lead.assigned", "lead.reassigned") and lead is not None and lead.ev is not None:
            new, prev, typ = d.get("rep_id"), d.get("previous_rep_id"), d.get("type")
            if typ == "escalation" or new == mgr_q:
                self._make("escalated", d, f"{who['name']} needs an owner", d.get("reason") or "Escalated to the "
                           "manager queue.", link, lead=lead, scope=prev)
                return
            if kind == "lead.reassigned" and typ == "reassign":
                reason = (d.get("reason") or "").split(". Reassigned to")[0].rstrip(".") + "."
                self._make("lead_reassigned", d, f"{who['name']} moved from {store.rep_name(prev)} to "
                           f"{store.rep_name(new)}", reason, link, lead=lead, scope=prev, owner=new, previous=prev)
            grade, score = lead.ev.score.grade, lead.ev.score.score
            act = lead.open_action()
            hot = self.rules.get("hot_lead") or {}
            facts = f"{who['company'] + ' · ' if who['company'] else ''}grade {grade}, score {score:.0f}."
            if hot.get("enabled") and grade in (hot.get("grades") or []):
                self._make("hot_lead", d, f"Hot lead for you: {who['name']}",
                           facts + (f" Next: {act['action']}." if act else ""), link, lead=lead, owner=new)
            else:
                self._make("lead_assigned", d, f"New lead for you: {who['name']}", facts, link, lead=lead, owner=new)
        elif kind == "event.processed" and lead is not None and d.get("type") == "call_logged":
            ev = rt.store.events.get(d.get("event_id") or "")
            pl = (ev.payload if ev is not None else None) or {}
            if pl.get("call_id") and pl.get("provider") != "manual":
                from .calls.center import RESULT_LABEL
                what = "meeting booked" if pl.get("meeting_booked") else RESULT_LABEL.get(pl.get("result"), "call")
                self._make("call_analyzed", d, f"Call with {who['name']}: {what}",
                           pl.get("summary") or f"{pl.get('outcome', 'call').replace('_', ' ').capitalize()}.",
                           link, lead=lead, owner=lead.owner)
        elif kind == "event.processed" and lead is not None and d.get("actor") != "rep":
            typ = d.get("type")
            if typ == "email_replied":
                self._make("reply_received", d, f"{who['name']} replied",
                           f"{who['company'] + ' · ' if who['company'] else ''}{d.get('summary') or 'New reply.'}",
                           link, lead=lead, owner=lead.owner)
            elif typ in ((self.rules.get("meeting_booked") or {}).get("events") or []):
                self._make("meeting_booked", d, f"{who['name']} {MEETING_TEXT.get(typ, typ.replace('_', ' '))}",
                           f"{who['company'] + ' · ' if who['company'] else ''}{d.get('summary') or ''}".strip(" ·"),
                           link, lead=lead, owner=lead.owner)
        elif kind == "stall.detected" and lead is not None:
            rule = self.rules.get("stalled") or {}
            if (d.get("risk") or 0) >= rule.get("min_risk", 0):
                details = d.get("details") or []
                self._make("stalled", d, f"{who['name']} has stalled",
                           (details[0] if details else ", ".join(d.get("rules") or [])) + f" (risk {d.get('risk', 0):.0f}).",
                           link, lead=lead, owner=lead.owner)
        elif kind == "opportunity.changed" and d.get("stage") in ("won", "lost") and d.get("from") not in (None, d.get("stage")):
            won = d["stage"] == "won"
            self._make("deal_won" if won else "deal_lost", d, f"Deal {'won' if won else 'lost'}: {d.get('name')}",
                       f"Expected value ${d.get('expected_value') or 0:,.0f}." if won else f"Was in {d['from'].replace('_', ' ')}.",
                       f"/deals/{d['opp_id']}", opp_id=d["opp_id"], owner=d.get("owner_rep_id"), scope=d.get("owner_rep_id"),
                       lead=lead)
        elif kind == "quote.changed":
            self._route_quote(d, lead, who)
        elif kind == "lead.flagged" and d.get("status") == "suspicious" and lead is not None:
            self._make("review_needed", d, f"Review {who['name']}: looks suspicious",
                       f"Fake-lead score {d.get('fake_score', 0):.0f} from {d.get('source') or 'an unknown source'}.",
                       "/quality#review", lead=lead, scope=lead.owner)
        elif kind == "source.flagged":
            reasons = d.get("reasons") or []
            self._make("source_flagged", d, f"Source flagged: {d.get('source_id')}",
                       reasons[0] if reasons else "It looks like it is sending junk.", "/quality#sources")

    def _route_quote(self, d: dict, lead, who: dict) -> None:
        link = f"/deals/{d['opp_id']}#quotes"
        owner = d.get("owner_rep_id")
        what = f"{d.get('title')} ({d.get('deal_name')}), ${d.get('total') or 0:,.0f}"
        if d["waiting_approval"] and not d["was_waiting"]:
            self._make("quote_approval", d, f"Approve a {d.get('discount_pct') or 0:.0f}% discount",
                       f"{what}. Drafted by {d.get('created_by') or 'a rep'}.", link, lead=lead, scope=owner,
                       opp_id=d["opp_id"])
        elif d["was_waiting"] and not d["waiting_approval"] and d["status"] == "draft":
            self._make("quote_approved", d, f"Quote approved: {d.get('title')}", f"{what}. It can be sent now.",
                       link, lead=lead, owner=owner, scope=owner, opp_id=d["opp_id"])
        if d.get("first_view") and d["status"] == "sent":
            self._make("quote_viewed", d, f"{who['name']} opened the quote", what + ".", link, lead=lead,
                       owner=owner, scope=owner, opp_id=d["opp_id"])
        if d["status"] == "declined" and d.get("from") == "sent":
            self._make("quote_declined", d, f"Quote declined: {d.get('title')}",
                       f"{who['name']} declined {what}." + (f" Reason: {d['decline_reason']}" if d.get("decline_reason")
                                                            else ""), link, lead=lead, owner=owner, scope=owner,
                       opp_id=d["opp_id"])

    def _make(self, rule_name: str, d: dict, title: str, body: str, link: str | None, *, lead=None,
              opp_id: str | None = None, owner: str | None = None, previous: str | None = None,
              scope: str | None = None) -> None:
        rule = self.rules.get(rule_name)
        if not rule or not rule.get("enabled"):
            return
        mgr_q = self.runtime.cfg.assignment.reassignment.manager_queue_id
        targets = []
        for to in rule["to"]:
            if to in ("owner", "previous_owner"):
                rep = owner if to == "owner" else previous
                if rep and rep != mgr_q:
                    targets.append(("rep", rep))
            elif to == "managers":
                targets.append(("managers", None))
        now = self.runtime.clock.now()
        for audience, rep in targets:
            with self._lock:
                nid = self._next
                self._next += 1
            n = {"id": nid, "ts": iso(now), "rule": rule_name, "severity": rule["severity"], "audience": audience,
                 "rep_id": rep, "scope_rep_id": rep if audience == "rep" else (scope if scope is not None else owner),
                 "lead_id": lead.lead_id if lead is not None else None, "opp_id": opp_id, "title": title,
                 "body": body.strip(), "link": link, "channels": list(rule["channels"]), "deliveries": []}
            self.items.append(n)
            self.db.upsert("notifications", {**{k: v for k, v in n.items() if k != "deliveries"}, "ts": now})
            self.runtime.processor.outbox.append({"type": "notification.created",       # scope: for routing
                                                  "data": {**self.view(n), "scope_rep_id": n["scope_rep_id"]}})
            if self.wants_delivery(n):
                self.pending.put(nid)

    def wants_delivery(self, n: dict) -> bool:
        if not (self.live or self.channels.in_demo):
            return False                         # simulated leads never email or text real people
        return any(c in n["channels"] and self.channels.configured(c) for c in EXTERNAL)

    # ---------------------------------------------------------------- who sees what
    @staticmethod
    def addressed_to(p, n: dict) -> bool:
        """Sent to this person: their own rep notifications, or manager notifications within their scope."""
        if n["audience"] == "rep":
            return p.role == "rep" and p.rep_id is not None and n["rep_id"] == p.rep_id
        return p.role in ("admin", "manager") and p.can_see_owner(n.get("scope_rep_id"))

    def visible(self, p, n: dict) -> bool:
        """Addressed to them, or (managers and admins) sent to a rep they oversee."""
        if self.addressed_to(p, n):
            return True
        return n["audience"] == "rep" and p.role in ("admin", "manager") and p.can_see_rep(n["rep_id"])

    @staticmethod
    def user_key(p) -> str:
        return p.user_id or "local"

    def _is_read(self, key: str, n: dict) -> bool:
        r = self.reads.get(key)
        return bool(r) and (n["id"] <= r["last_read_id"] or n["id"] in r["read_ids"])

    def view(self, n: dict, read: bool | None = None, rep_name=None, deliveries: bool = False) -> dict:
        out = {k: v for k, v in n.items() if k not in ("deliveries", "scope_rep_id")}
        if read is not None:
            out["read"] = read
        if rep_name is not None:
            out["rep_name"] = rep_name(n["rep_id"]) if n["rep_id"] else None
        if deliveries:
            out["deliveries"] = list(n["deliveries"])
        return out

    def listing(self, p, mine: bool = True, unread_only: bool = False, rule: str | None = None,
                before: int | None = None, limit: int = 50) -> dict:
        key = self.user_key(p)
        rep_name = self.runtime.store.rep_name if self.runtime else (lambda r: r)
        items, unread = [], 0
        for n in reversed(self.items):
            to_me = self.addressed_to(p, n)
            if not (to_me or (not mine and self.visible(p, n))):
                continue
            read = self._is_read(key, n)
            if to_me and not read:
                unread += 1
            if (unread_only and read) or (rule and n["rule"] != rule) or (before is not None and n["id"] >= before):
                continue
            if len(items) < limit:
                items.append(self.view(n, read=read, rep_name=rep_name, deliveries=p.role == "admin"))
        return {"items": items, "unread": unread}

    def mark_read(self, p, ids: list[int] | None = None, everything: bool = False) -> dict:
        key = self.user_key(p)
        with self._lock:
            r = self.reads.setdefault(key, {"last_read_id": 0, "read_ids": set()})
            if everything:
                r["last_read_id"] = max((n["id"] for n in self.items), default=r["last_read_id"])
                r["read_ids"] = set()
            else:
                r["read_ids"] |= {int(i) for i in ids or [] if int(i) > r["last_read_id"]}
            row = {"user_key": key, "last_read_id": r["last_read_id"], "read_ids": sorted(r["read_ids"])[-2000:]}
        if getattr(self.db, "enabled", False):
            self.db.write_now("notification_reads", row)
        return row

    # ---------------------------------------------------------------- delivering (async loop)
    def recipients(self, n: dict) -> list[dict]:
        people = self.accounts.list_profiles() if self.accounts else []
        if n["audience"] == "rep":
            return [p for p in people if p.get("role") == "rep" and p.get("rep_id") == n["rep_id"]]
        scope = n.get("scope_rep_id")
        return [p for p in people if p.get("role") == "admin" or (
            p.get("role") == "manager" and (p.get("team_rep_ids") is None or scope is None
                                            or scope in (p.get("team_rep_ids") or [])))]

    @staticmethod
    def prefs(profile: dict) -> dict:
        notify = profile.get("notify") or {}
        return {"email": notify.get("email", True), "sms": notify.get("sms", False)}

    async def deliver(self, n: dict, client) -> list[dict]:
        """Send `n` on every configured external channel it asks for, to every recipient who wants it."""
        out = []
        ch = self.channels
        for channel in (c for c in n["channels"] if c in EXTERNAL and ch.configured(c)):
            if channel == "slack":
                out.append({"channel": "slack", "target": "team channel", **await ch.send(client, "slack", None, n)})
                continue
            for person in self.recipients(n):
                pref = self.prefs(person)
                to = person.get("email") if channel == "email" else person.get("phone")
                label = to if channel == "email" else mask_phone(to)
                if not pref[channel]:
                    out.append({"channel": channel, "target": label or person.get("name"), "status": "skipped",
                                "detail": f"{channel} switched off by the recipient"})
                elif not to:
                    out.append({"channel": channel, "target": person.get("email") or person.get("name"), "status": "skipped",
                                "detail": "no phone number saved" if channel == "sms" else "no email address"})
                else:
                    out.append({"channel": channel, "target": label, **await ch.send(client, channel, to, n)})
        if not out:
            out.append({"channel": "-", "target": None, "status": "skipped", "detail": "nobody to send to on the "
                        "configured channels (link a signed-in user to this rep or manager)"})
        return out

    async def deliver_pending(self, client) -> int:
        done = 0
        by_id = {n["id"]: n for n in list(self.items)}
        while True:
            try:
                nid = self.pending.get_nowait()
            except queue.Empty:
                return done
            n = by_id.get(nid)
            if n is None:
                continue
            results = await self.deliver(n, client)
            ts = _now()
            rows = [{"notification_id": nid, "ts": ts, **r} for r in results]
            n["deliveries"] = [self._delivery_view(r) for r in rows]
            if getattr(self.db, "enabled", False):
                await asyncio.to_thread(self.db.write_rows, "notification_deliveries",
                                        [{"id": f"{nid}:{i}", **r} for i, r in enumerate(rows)])
            done += 1

    @staticmethod
    def _delivery_view(r: dict) -> dict:
        return {"channel": r["channel"], "target": r.get("target"), "status": r["status"], "detail": r.get("detail"),
                "ts": iso(r["ts"]) if isinstance(r.get("ts"), datetime) else r.get("ts")}

    async def run(self, every: float = 1.0) -> None:
        """Background delivery loop (started by main)."""
        async with self.channels.client() as client:
            while True:
                await asyncio.sleep(every)
                try:
                    await self.deliver_pending(client)
                except Exception:  # noqa: BLE001 - keep delivering
                    log.exception("notification delivery failed")

    async def send_test(self, channel: str, profile: dict | None, p) -> dict:
        """An admin's test message on one channel, to themselves (Slack: to the team channel)."""
        if not self.channels.configured(channel):
            return {"channel": channel, "status": "failed", "detail": "this channel has no keys yet"}
        n = {"title": "LeadPilot test notification", "body": f"Sent by {p.email or p.name or 'an admin'} to check "
             f"the {channel} channel.", "link": "/notifications"}
        to = None
        if channel == "email":
            to = (profile or {}).get("email") or p.email
        elif channel == "sms":
            to = (profile or {}).get("phone")
        if channel != "slack" and not to:
            return {"channel": channel, "status": "failed",
                    "detail": "save your phone number first" if channel == "sms" else "your account has no email"}
        async with self.channels.client() as client:
            r = await self.channels.send(client, channel, to, n)
        return {"channel": channel, "target": mask_phone(to) if channel == "sms" else to or "team channel", **r}


def _who(lead) -> dict:
    p = lead.profile if lead is not None else None
    return {"name": (p.name if p and p.name else None) or (lead.lead_id if lead is not None else "A lead"),
            "company": p.company if p else None}
