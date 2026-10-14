"""Notifications: rules, never on replays, who sees what, read state, delivery on each channel, storage, API."""
import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import AccountStore, Principal
from app.config import load_config
from app.notifications import Channels, NotificationCenter, load_rules
from app.persistence import NullPersistence, Persistence
from app.runtime import Runtime

KEYS = {"RESEND_API_KEY": "re_test", "LEADPILOT_EMAIL_FROM": "LeadPilot <pilot@example.com>",
        "SLACK_WEBHOOK_URL": "https://hooks.slack.test/T1/B1/x", "TWILIO_ACCOUNT_SID": "AC1",
        "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM_NUMBER": "+15005550006", "LEADPILOT_PUBLIC_URL": "https://pilot.example.com"}


def rules(**changes) -> dict:
    r = load_rules()
    for name, values in changes.items():
        r["rules"][name].update(values)
    return r


def world(center_kwargs=None, db=None):
    cfg = load_config(overrides={"simulator": {"warmup_days": 2}})
    rt = Runtime(cfg)
    rt.reset(warmup=True)
    nc = NotificationCenter(db or NullPersistence(), None, **(center_kwargs or {}))
    nc.attach(rt)
    return rt, nc


def new_lead(rt, email: str, title: str = "VP Operations") -> str:
    r = rt.processor.handle({"type": "lead_created", "source": "website", "payload": {
        "name": "Nina Notify", "email": email, "title": title, "company": "Notify Labs", "country": "US",
        "form_fill_seconds": 40}})
    assert r["status"] == "processed"
    return r["lead_id"]


REP = Principal(kind="user", role="rep", user_id="u-rep", rep_id="R-ANANYA")
OTHER_REP = Principal(kind="user", role="rep", user_id="u-other", rep_id="R-KENJI")
MANAGER = Principal(kind="user", role="manager", user_id="u-mgr", team=frozenset({"R-ANANYA"}))
ADMIN = Principal(kind="user", role="admin", user_id="u-admin")


# ================================================================================================ rules
def test_new_leads_replies_and_meetings_notify_the_owner():
    rt, nc = world()
    lid = new_lead(rt, "nina@notifylabs.io")
    owner = rt.store.leads[lid].owner
    got = [n for n in nc.items if n["lead_id"] == lid]
    assert [(n["rule"], n["audience"], n["rep_id"]) for n in got] == [("lead_assigned", "rep", owner)]
    assert got[0]["title"] == "New lead for you: Nina Notify" and got[0]["link"] == f"/leads/{lid}"

    rt.processor.handle({"type": "email_replied", "lead_ref": {"email": "nina@notifylabs.io"},
                         "payload": {"body": "Yes, interested. Can we talk pricing?"}})
    rt.processor.handle({"type": "demo_request", "lead_ref": {"email": "nina@notifylabs.io"}})
    rules_seen = [n["rule"] for n in nc.items if n["lead_id"] == lid]
    assert rules_seen[1:] == ["reply_received", "meeting_booked"]
    assert nc.items[-1]["title"] == "Nina Notify requested a demo"
    msgs = [m for m in rt.processor.drain_outbox() if m["type"] == "notification.created"]
    assert len(msgs) == 3 and msgs[0]["data"]["scope_rep_id"] == owner


def test_hot_leads_are_urgent_and_rules_can_be_switched_off():
    rt, nc = world({"rules": rules(hot_lead={"grades": ["A", "B", "C", "D"]}, reply_received={"enabled": False})})
    lid = new_lead(rt, "hot@notifylabs.io")
    n = [x for x in nc.items if x["lead_id"] == lid]
    assert [x["rule"] for x in n] == ["hot_lead"] and n[0]["severity"] == "urgent"
    assert n[0]["title"] == "Hot lead for you: Nina Notify" and "email" in n[0]["channels"]
    rt.processor.handle({"type": "email_replied", "lead_ref": {"email": "hot@notifylabs.io"},
                         "payload": {"body": "Sounds good"}})
    assert [x["rule"] for x in nc.items if x["lead_id"] == lid] == ["hot_lead"]


def test_missed_first_touch_tells_the_old_owner_and_managers():
    rt, nc = world()
    lid = new_lead(rt, "slow@notifylabs.io")
    first = rt.store.leads[lid].owner
    rt.run_until(rt.clock.now() + timedelta(days=4))              # the SLA check fires and moves the lead
    lead = rt.store.leads[lid]
    assert lead.owner != first
    moved = [n for n in nc.items if n["lead_id"] == lid and n["rule"] == "lead_reassigned"]
    assert {(n["audience"], n["rep_id"]) for n in moved} == {("rep", first), ("managers", None)}
    assert moved[0]["body"].startswith("R1: No first touch") and "Reassigned to" not in moved[0]["body"]
    assert lead.assignments[-1]["reason"].count(". Reassigned to ") == 1               # not "ReAssigned"
    assert any(n["rule"] == "lead_assigned" and n["rep_id"] == lead.owner for n in nc.items if n["lead_id"] == lid)


def test_replays_restarts_and_warmups_never_notify():
    rt, nc = world()
    assert len(nc.items) == 0                                        # the warm-up processed with broadcasting off
    new_lead(rt, "once@notifylabs.io")
    count = len(nc.items)
    rt.processor.replay(write=False)
    rt.apply_config(rt.cfg, 1)
    assert len(nc.items) == count


# ================================================================================================ who sees what
def test_visibility_and_read_state():
    rt, nc = world()
    lid = new_lead(rt, "seen@notifylabs.io")
    rt.processor.handle({"type": "manual_assign", "lead_ref": {"lead_id": lid}, "payload": {"rep_id": "R-ANANYA"}})
    nc._make("source_flagged", {}, "Source flagged: x", "junk", "/quality#sources")
    mine = nc.listing(REP)
    assert mine["items"] and all(n["audience"] == "rep" and n["rep_id"] == "R-ANANYA" for n in mine["items"])
    assert nc.listing(OTHER_REP)["unread"] == len([n for n in nc.items if n["rep_id"] == "R-KENJI"])
    assert [n["rule"] for n in nc.listing(ADMIN)["items"]] == ["source_flagged"]       # addressed to managers
    everyone = nc.listing(ADMIN, mine=False)["items"]
    assert len(everyone) == len(nc.items) and everyone[0]["id"] > everyone[-1]["id"]   # newest first
    team = nc.listing(MANAGER, mine=False)["items"]
    assert {n["rep_id"] for n in team if n["audience"] == "rep"} <= {"R-ANANYA"}

    before = nc.listing(REP)["unread"]
    nc.mark_read(REP, [mine["items"][0]["id"]])
    assert nc.listing(REP)["unread"] == before - 1 and nc.listing(REP)["items"][0]["read"] is True
    assert mine["items"][0]["id"] not in [n["id"] for n in nc.listing(REP, unread_only=True)["items"]]
    nc.mark_read(REP, everything=True)
    assert nc.listing(REP)["unread"] == 0 and nc.listing(ADMIN)["unread"] == 1     # read state is per person


# ================================================================================================ delivery
class Recorder:
    def __init__(self, fail: str | None = None):
        self.calls, self.fail = [], fail

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail and self.fail in str(request.url):
            return httpx.Response(500, text="provider down")
        return httpx.Response(200, json={"id": "ok"})


def people() -> AccountStore:
    acc = AccountStore(NullPersistence(), frozenset({"boss@test.dev"}))
    for uid, email in (("u-rep", "ana@test.dev"), ("u-mgr", "max@test.dev"), ("u-boss", "boss@test.dev")):
        acc.ensure_profile(uid, email)
    acc.update_profile("u-rep", {"role": "rep", "rep_id": "R-ANANYA"})
    acc.update_profile("u-mgr", {"role": "manager", "team_rep_ids": ["R-KENJI"]})
    return acc


def deliver(nc) -> None:
    async def go():
        async with nc.channels.client() as client:
            await nc.deliver_pending(client)
    asyncio.run(go())


def test_each_channel_delivers_to_the_right_people_and_records_the_outcome():
    rec = Recorder()
    rt, nc = world({"channels": Channels(KEYS, httpx.MockTransport(rec)), "live": True,
                    "rules": rules(hot_lead={"grades": ["A", "B", "C", "D"]})})
    nc.accounts = people()
    nc.accounts.update_notify("u-rep", "+447700900123", {"email": True, "sms": True})
    lid = new_lead(rt, "deliver@notifylabs.io")
    rt.processor.handle({"type": "manual_assign", "lead_ref": {"lead_id": lid}, "payload": {"rep_id": "R-ANANYA"}})
    deliver(nc)
    hot = [n for n in nc.items if n["rule"] == "hot_lead" and n["rep_id"] == "R-ANANYA"][-1]
    by = {(d["channel"], d["status"]) for d in hot["deliveries"]}
    assert by == {("email", "sent"), ("sms", "sent"), ("slack", "sent")}
    email = next(json.loads(c.content) for c in rec.calls if c.url.host == "api.resend.com")
    assert email["to"] == ["ana@test.dev"] and email["subject"] == hot["title"]
    assert f"https://pilot.example.com/leads/{lid}" in email["text"]
    sms = next(parse_qs(c.content.decode()) for c in rec.calls if c.url.host == "api.twilio.com")
    assert sms["To"] == ["+447700900123"] and sms["From"] == ["+15005550006"]
    assert next(d for d in hot["deliveries"] if d["channel"] == "sms")["target"] == "…0123"   # masked

    nc.accounts.update_notify("u-rep", None, {"email": False, "sms": False})
    rec.fail = "slack"
    rt.processor.handle({"type": "email_replied", "lead_ref": {"lead_id": lid}, "payload": {"body": "Hi"}})
    rt.processor.handle({"type": "manual_assign", "lead_ref": {"lead_id": lid}, "payload": {"rep_id": "R-KENJI"}})
    rt.processor.handle({"type": "manual_assign", "lead_ref": {"lead_id": lid}, "payload": {"rep_id": "R-ANANYA"}})
    deliver(nc)
    reply = [n for n in nc.items if n["rule"] == "reply_received"][-1]
    assert reply["deliveries"][0]["status"] == "skipped" and "switched off" in reply["deliveries"][0]["detail"]
    again = [n for n in nc.items if n["rule"] == "hot_lead" and n["rep_id"] == "R-ANANYA"][-1]
    slack = next(d for d in again["deliveries"] if d["channel"] == "slack")
    assert slack["status"] == "failed" and "HTTP 500" in slack["detail"]


def test_demo_mode_and_missing_keys_send_nothing_outside_the_app():
    rec = Recorder()
    rt, nc = world({"channels": Channels(KEYS, httpx.MockTransport(rec)), "live": False})
    nc.accounts = people()
    new_lead(rt, "demo@notifylabs.io")
    deliver(nc)
    assert rec.calls == [] and all(n["deliveries"] == [] for n in nc.items)
    off = Channels({})
    assert [c["configured"] for c in off.status()] == [True, False, False, False]
    assert Channels({**KEYS, "LEADPILOT_NOTIFY_IN_DEMO": "1"}).in_demo


# ================================================================================================ storage
def test_notifications_survive_replays_and_restarts_but_not_demo_resets(tmp_path):
    url = f"sqlite:///{tmp_path / 'n.db'}"
    db = Persistence(url)
    rt, nc = world({"live": True, "channels": Channels({**KEYS}, httpx.MockTransport(Recorder()))}, db=db)
    rt.db = rt.processor.db = db
    nc.accounts = people()
    new_lead(rt, "kept@notifylabs.io")
    deliver(nc)
    nc.mark_read(REP, everything=True)
    db.flush()
    db.clear_projections()                                         # what a replay does to the tables
    count, last = len(nc.items), nc.items[-1]
    again = NotificationCenter(Persistence(url), None)
    assert len(again.items) == count and again.items[-1]["title"] == last["title"]
    assert again.items[-1]["deliveries"] == last["deliveries"] and again._next == last["id"] + 1
    assert again.reads["u-rep"]["last_read_id"] == last["id"]
    db.reset()
    assert len(NotificationCenter(Persistence(url), None).items) == 0


# ================================================================================================ API
SECRET = "test-only-secret-not-used-anywhere-else-0123456789"
SUPA = "https://test-project.supabase.co"
ENV = {"LEADPILOT_MODE": "demo", "LEADPILOT_PERSIST": "0", "LEADPILOT_WARMUP_DAYS": "2", "LEADPILOT_AUTH": "on",
       "SUPABASE_URL": SUPA, "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_ANON_KEY": "sb_publishable_test",
       "LEADPILOT_ADMIN_EMAILS": "boss@test.dev"}
USERS = {name: str(uuid.uuid4()) for name in ("boss", "rita")}


def h(name: str) -> dict:
    now = datetime.now(timezone.utc)
    tok = jwt.encode({"sub": USERS[name], "email": f"{name}@test.dev", "aud": "authenticated",
                      "iss": f"{SUPA}/auth/v1", "role": "authenticated", "iat": now,
                      "exp": now + timedelta(minutes=60)}, SECRET, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def client():
    saved = {k: os.environ.get(k) for k in ENV}
    os.environ.update(ENV)
    from app.main import app
    try:
        with TestClient(app) as c:
            for _ in range(240):
                if c.get("/api/health").json()["status"] == "ready":
                    break
                time.sleep(0.25)
            c.post("/api/sim/pause", headers=h("boss"))
            for name in USERS:
                assert c.get("/api/me", headers=h(name)).status_code == 200
            yield c
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_api_inbox_read_state_and_personal_settings(client):
    r = client.post("/api/events", headers=h("boss"), json={"type": "lead_created", "source": "website", "payload": {
        "name": "Api Notify", "email": "api@notifyapi.io", "title": "CEO", "company": "Notify API", "country": "US",
        "form_fill_seconds": 30}}).json()["results"][0]
    owner = client.get(f"/api/leads/{r['lead_id']}", headers=h("boss")).json()["owner_rep_id"]
    assert client.patch(f"/api/admin/users/{USERS['rita']}", headers=h("boss"),
                        json={"role": "rep", "rep_id": owner}).status_code == 200
    inbox = client.get("/api/notifications", headers=h("rita")).json()
    mine = [n for n in inbox["items"] if n["lead_id"] == r["lead_id"]]
    assert mine and mine[0]["rule"] in ("hot_lead", "lead_assigned") and inbox["unread"] >= 1
    assert all(n["rep_id"] == owner for n in inbox["items"]) and "deliveries" not in mine[0]
    everyone = client.get("/api/notifications?mine=false", headers=h("boss")).json()["items"]
    assert any(n["lead_id"] == r["lead_id"] for n in everyone) and "deliveries" in everyone[0]

    assert client.post("/api/notifications/read", headers=h("rita"), json={"ids": ["x"]}).status_code == 422
    left = client.post("/api/notifications/read", headers=h("rita"), json={"ids": [mine[0]["id"]]}).json()["unread"]
    assert left == inbox["unread"] - 1
    assert client.post("/api/notifications/read", headers=h("rita"), json={"all": True}).json()["unread"] == 0

    s = client.get("/api/notifications/settings", headers=h("rita")).json()
    assert s["me"] == {"email_address": "rita@test.dev", "phone": None, "email": True, "sms": False}
    assert s["rules"] == [] and s["delivers"] is False and s["channels"][0]["channel"] == "in_app"
    assert client.get("/api/notifications/settings", headers=h("boss")).json()["rules"]
    bad = client.put("/api/notifications/settings", headers=h("rita"), json={"phone": "12345", "sms": True})
    assert bad.status_code == 422
    need = client.put("/api/notifications/settings", headers=h("rita"), json={"sms": True})
    assert need.status_code == 422 and "phone number" in need.json()["detail"]
    ok = client.put("/api/notifications/settings", headers=h("rita"),
                    json={"phone": "+44 7911 123456", "email": False, "sms": True}).json()
    assert ok == {"email_address": "rita@test.dev", "phone": "+447911123456", "email": False, "sms": True}

    assert client.post("/api/notifications/test", headers=h("rita"), json={"channel": "email"}).status_code == 403
    t = client.post("/api/notifications/test", headers=h("boss"), json={"channel": "slack"}).json()
    assert t["status"] == "failed" and "no keys" in t["detail"]
