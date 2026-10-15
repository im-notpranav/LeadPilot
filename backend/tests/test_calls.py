"""Call intelligence: Gemini analysis (mocked), the Retell webhook and its signature, the rule-based fallback,
calls becoming events (replays never call Gemini again), recordings in Supabase Storage, and the API."""
import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from app.calls.center import CallCenter, event_id_for
from app.calls.gemini import Gemini, GeminiError, clean
from app.calls.parse import manual_call, parse_generic, parse_retell, retell_sign, retell_signature_ok, rule_analysis
from app.calls.storage import RecordingStore
from app.config import load_config
from app.persistence import NullPersistence
from app.runtime import Runtime

PHONE = "+14155552671"
TRANSCRIPT = ("Agent: Hi Nora, this is Sam from LeadPilot, thanks for taking the call.\n"
              "User: Sure. We are looking at tools for this quarter, what does pricing look like for 40 seats?\n"
              "Agent: It depends on the plan. Shall we book a demo on Thursday at 2pm?\n"
              "User: Yes, Thursday 2pm works. We currently use Acme CRM and the contract ends in March.")
ANALYSIS = {"summary": "Nora wants pricing for 40 seats this quarter and agreed to a demo on Thursday at 2pm.",
            "outcome": "connected", "result": "meeting_booked", "sentiment": "positive", "call_intent": "positive_intent",
            "meeting_booked": True, "next_step": "Send the demo invite for Thursday 2pm.",
            "buying_signals": ["pricing for 40 seats", "this quarter"], "objections": [], "competitors": ["Acme CRM"]}


def gemini_reply(analysis: dict) -> httpx.Response:
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(analysis)}]}}]})


class FakeGemini:
    def __init__(self, response):
        self.requests = []
        self.response = response

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response if isinstance(self.response, httpx.Response) else self.response(request)


def retell_body(event="call_ended", call_id="call_abc123", to=PHONE, **extra) -> dict:
    now = int(time.time() * 1000)
    call = {"call_type": "phone_call", "call_id": call_id, "agent_id": "agent_1", "direction": "outbound",
            "from_number": "+15005550006", "to_number": to, "call_status": "ended",
            "start_timestamp": now - 185_000, "end_timestamp": now - 5_000, "duration_ms": 180_000,
            "disconnection_reason": "user_hangup", "transcript": TRANSCRIPT,
            "recording_url": "https://recordings.retell.test/call_abc123.wav", "metadata": {}, **extra}
    return {"event": event, "call": call}


# ================================================================================================ pieces
def test_clean_keeps_the_shape_and_drops_what_cannot_be_true():
    a = clean({"summary": "  Two\nlines  ", "outcome": "VOICEMAIL", "result": "meeting_booked", "sentiment": "angry",
               "call_intent": "positive_intent", "meeting_booked": True, "buying_signals": ["a", "a", "b"] + ["x"] * 9})
    assert a["summary"] == "Two lines" and a["outcome"] == "voicemail" and a["sentiment"] == "neutral"
    assert (a["call_intent"], a["result"], a["meeting_booked"]) == ("neutral", "no_conversation", False)
    assert a["buying_signals"] == ["a", "b", "x"] and a["objections"] == [] and a["next_step"] == ""


def test_gemini_request_and_errors():
    fake = FakeGemini(gemini_reply(ANALYSIS))
    g = Gemini({"GEMINI_API_KEY": "gk-test", "GEMINI_MODEL": "gemini-test"}, httpx.MockTransport(fake))
    out = asyncio.run(g.analyze_call(TRANSCRIPT, "outbound", "Nora North", 180))
    assert out == clean(ANALYSIS)
    req = fake.requests[0]
    assert req.url.path.endswith("/models/gemini-test:generateContent") and req.headers["x-goog-api-key"] == "gk-test"
    body = json.loads(req.content)
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseSchema"]["properties"]["outcome"]["enum"] == ["connected", "voicemail", "no_answer"]
    assert "Nora North" in body["contents"][0]["parts"][0]["text"] and "pricing look like" in body["contents"][0]["parts"][0]["text"]

    assert not Gemini({}).configured and Gemini({}).model == "gemini-2.5-flash"
    for bad, msg in ((httpx.Response(429, text="quota"), "HTTP 429"),
                     (httpx.Response(200, json={"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}), "blocked: SAFETY"),
                     (httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}), "no usable")):
        with pytest.raises(GeminiError, match=msg):
            asyncio.run(Gemini({"GEMINI_API_KEY": "k"}, httpx.MockTransport(FakeGemini(bad))).analyze_call("User: hi"))


def test_retell_payload_and_signature():
    body = retell_body(metadata={"lead_email": "nora@northwind.io"})
    event, call = parse_retell(body)
    assert event == "call_ended" and call["provider"] == "retell" and call["direction"] == "outbound"
    assert call["lead_ref"] == {"email": "nora@northwind.io"} and call["duration_s"] == 180
    assert parse_retell(retell_body())[1]["lead_ref"] == {"phone": PHONE}           # outbound: the number we called

    raw = json.dumps(body, separators=(",", ":")).encode()
    sig = retell_sign("key_retell", raw.decode())
    assert retell_signature_ok("key_retell", raw, sig)
    pretty = json.dumps(body, indent=2).encode()                     # same JSON, other spacing: compact form matches
    assert retell_signature_ok("key_retell", pretty, sig)
    assert not retell_signature_ok("other_key", raw, sig)
    old = retell_sign("key_retell", raw.decode(), now_ms=int(time.time() * 1000) - 10 * 60 * 1000)
    assert not retell_signature_ok("key_retell", raw, old) and not retell_signature_ok("key_retell", raw, "v=1,d=zz")


def test_rules_analysis_without_gemini(cfg):
    _, vm = parse_retell(retell_body(disconnection_reason="voicemail_reached", transcript="Agent: Hi, leaving a message"))
    assert rule_analysis(vm, cfg)["outcome"] == "voicemail"
    _, none = parse_retell(retell_body(disconnection_reason="dial_no_answer", transcript=""))
    assert rule_analysis(none, cfg)["outcome"] == "no_answer"
    _, talk = parse_retell(retell_body(call_analysis={"call_summary": "Asked for pricing.", "user_sentiment": "Positive"}))
    a = rule_analysis(talk, cfg)
    assert (a["outcome"], a["call_intent"], a["sentiment"], a["summary"]) == ("connected", "positive_intent", "positive", "Asked for pricing.")
    gen = parse_generic({"call_id": "x1", "email": "a@b.io", "transcript": "Customer: not interested, remove me", "outcome": "connected"})
    assert gen["lead_ref"] == {"email": "a@b.io"} and rule_analysis(gen, cfg)["call_intent"] == "negative"
    m = manual_call("L-1", "R-ANANYA", {"notes": "Left a voicemail", "outcome": "voicemail", "duration_minutes": 1},
                    datetime(2026, 10, 5, tzinfo=timezone.utc))
    assert m["provider"] == "manual" and m["duration_s"] == 60 and rule_analysis(m, cfg)["outcome"] == "voicemail"


# ================================================================================================ calls → events
def world(gemini_response=None, recordings=None):
    rt = Runtime(load_config(overrides={"simulator": {"warmup_days": 2}}))
    rt.reset(warmup=True)
    fake = FakeGemini(gemini_response or gemini_reply(ANALYSIS))
    center = CallCenter(NullPersistence(), Gemini({"GEMINI_API_KEY": "gk"}, httpx.MockTransport(fake)),
                        recordings or RecordingStore(None))

    async def publish(events):
        return [rt.processor.handle(e) for e in events]
    center.attach(rt, publish, live=False)
    r = rt.processor.handle({"type": "lead_created", "source": "website", "payload": {
        "name": "Nora North", "email": "nora@northwind.io", "phone": PHONE, "title": "Head of Operations",
        "company": "Northwind", "country": "US", "form_fill_seconds": 40}})
    return rt, center, fake, r["lead_id"]


def test_an_ai_analysed_call_becomes_events_and_replays_without_gemini():
    rt, center, fake, lid = world()
    before = rt.store.leads[lid].ev.score.score
    _, call = parse_retell(retell_body())
    rec, new = center.receive(call, "con_1")
    assert new and rec["status"] == "queued" and center.receive(call)[1] is False         # same call twice: once
    asyncio.run(center.process(rec["id"]))
    assert rec["status"] == "done" and rec["lead_id"] == lid and rec["analyzed_by"] == "gemini:gemini-2.5-flash"
    eid = event_id_for(rec["id"])
    assert rec["event_ids"] == [eid, f"{eid}.m"]
    ev = rt.store.events[eid]
    assert ev.type == "call_logged" and ev.actor == "rep" and ev.payload["outcome"] == "connected"
    assert ev.payload["summary"] == ANALYSIS["summary"] and ev.payload["competitors"] == ["Acme CRM"]
    assert rt.store.events[f"{eid}.m"].type == "meeting_scheduled"
    lead = rt.store.leads[lid]
    assert lead.ev.score.score > before and "intent.positive_call_intent" in lead.ev.score.factors
    assert "positive_call" in lead.ev.score.active_signals and lead.ev.stage == "engaged"

    calls_made = len(fake.requests)
    snapshot = (lead.ev.score.score, lead.ev.stage)
    rt.processor.replay(write=False)
    lead = rt.store.leads[lid]
    assert (lead.ev.score.score, lead.ev.stage) == snapshot and len(fake.requests) == calls_made == 1


def test_unmatched_calls_wait_for_a_lead_and_gemini_failures_fall_back_to_rules():
    rt, center, fake, lid = world(httpx.Response(500, text="boom"))
    _, call = parse_retell(retell_body(call_id="call_lost", to="+14155550199"))
    rec, _ = center.receive(call)
    asyncio.run(center.process(rec["id"]))
    assert rec["status"] == "unmatched" and rec["event_ids"] == [] and "Link the call" in rec["error"]
    asyncio.run(center.link(rec["id"], lid))
    assert rec["status"] == "done" and rec["lead_id"] == lid and rec["analyzed_by"] == "rules"
    assert "Gemini analysis failed" in rec["error"] and rec["analysis"]["call_intent"] == "positive_intent"
    assert rt.store.events[event_id_for(rec["id"])].payload["analyzed_by"] == "rules"


def test_voicemails_skip_gemini_and_a_rep_note_keeps_the_reps_outcome():
    rt, center, fake, lid = world()
    m = manual_call(lid, "R-ANANYA", {"notes": "Left a voicemail about the pricing sheet", "outcome": "voicemail"},
                    rt.clock.now())
    rec, _ = center.receive(m)
    asyncio.run(center.process(rec["id"]))
    assert fake.requests == [] and rec["analysis"]["outcome"] == "voicemail" and rec["analyzed_by"] == "rules"
    ev = rt.store.events[event_id_for(rec["id"])]
    assert ev.rep_id == "R-ANANYA" and ev.ts == rt.clock.now()


def test_recordings_are_copied_to_a_private_bucket_and_played_through_signed_links():
    seen = []

    def storage(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.host == "recordings.retell.test":
            return httpx.Response(200, content=b"RIFFfake", headers={"content-type": "audio/wav"})
        if request.url.path == "/storage/v1/bucket":
            return httpx.Response(200, json={"name": "call-recordings"})
        if "/object/sign/" in request.url.path:
            return httpx.Response(200, json={"signedURL": "/object/sign/call-recordings/retell/call_abc123.wav?token=t"})
        return httpx.Response(200, json={"Key": "ok"})

    store = RecordingStore("https://proj.supabase.co", {"SUPABASE_SERVICE_ROLE_KEY": "srv"}, httpx.MockTransport(storage))
    rt, center, fake, lid = world(recordings=store)
    _, call = parse_retell(retell_body())
    rec, _ = center.receive(call)
    asyncio.run(center.process(rec["id"]))
    assert rec["recording_path"] == "retell/call_abc123.wav"
    assert ("POST", "/storage/v1/object/call-recordings/retell/call_abc123.wav") in seen
    url = asyncio.run(center.recording_link(rec))
    assert url == "https://proj.supabase.co/storage/v1/object/sign/call-recordings/retell/call_abc123.wav?token=t"
    assert center.view(rec)["recording_stored"] is True


# ================================================================================================ API
SECRET = "test-only-secret-not-used-anywhere-else-0123456789"
SUPA = "https://test-project.supabase.co"
ENV = {"LEADPILOT_MODE": "demo", "LEADPILOT_PERSIST": "0", "LEADPILOT_WARMUP_DAYS": "2", "LEADPILOT_AUTH": "on",
       "SUPABASE_URL": SUPA, "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_ANON_KEY": "sb_publishable_test",
       "LEADPILOT_ADMIN_EMAILS": "boss@test.dev", "RETELL_API_KEY": "key_retell_test", "GEMINI_API_KEY": ""}
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


def wait_done(c, lid: str, n: int) -> list[dict]:
    for _ in range(200):
        items = c.get(f"/api/leads/{lid}/calls", headers=h("boss")).json()["items"]
        if len(items) >= n and all(i["status"] not in ("queued", "analyzing") for i in items):
            return items
        time.sleep(0.05)
    raise AssertionError("calls were not processed")


def test_api_retell_webhook_manual_calls_and_scope(client):
    r = client.post("/api/events", headers=h("boss"), json={"type": "lead_created", "source": "website", "payload": {
        "name": "Api Caller", "email": "api@callers.io", "phone": "+14155552690", "title": "CTO", "company": "Callers",
        "country": "US", "form_fill_seconds": 30}}).json()["results"][0]
    lid = r["lead_id"]
    con = client.post("/api/connectors", headers=h("boss"), json={"kind": "call", "name": "Retell"}).json()
    assert con["kind"] == "call" and con["settings"]["provider"] == "retell"

    def hook(body: dict, key: str = "key_retell_test"):
        raw = json.dumps(body, separators=(",", ":"))
        return client.post(f"/api/hooks/{con['id']}", content=raw,
                           headers={"content-type": "application/json", "x-retell-signature": retell_sign(key, raw)})

    assert hook(retell_body(to="+14155552690"), key="wrong").status_code == 401
    ended = hook(retell_body(call_id="call_api_1", to="+14155552690")).json()
    assert ended["status"] == "ignored" and "call_analyzed" in ended["results"][0]["reason"]   # no Gemini: wait
    body = retell_body(event="call_analyzed", call_id="call_api_1", to="+14155552690",
                       call_analysis={"call_summary": "Wants a quote for 20 seats.", "user_sentiment": "Positive"})
    assert hook(body).json()["status"] == "accepted"
    assert hook(body).json()["status"] == "duplicate"
    [call] = wait_done(client, lid, 1)
    assert call["status"] == "done" and call["analyzed_by"] == "provider" and call["has_recording"]
    assert call["analysis"]["summary"] == "Wants a quote for 20 seats." and "pricing look like" in call["transcript"]
    rec = client.get(f"/api/calls/{call['id']}/recording", headers=h("boss")).json()
    assert rec == {"url": "https://recordings.retell.test/call_abc123.wav", "stored": False}
    timeline = client.get(f"/api/leads/{lid}/timeline", headers=h("boss")).json()
    assert any(e["type"] == "call_logged" for e in (timeline.get("items") or timeline.get("events") or []))

    bad = client.post(f"/api/leads/{lid}/calls", headers=h("boss"), json={})
    assert bad.status_code == 422
    logged = client.post(f"/api/leads/{lid}/calls", headers=h("boss"),
                         json={"notes": "Customer: we need a proposal by Friday", "outcome": "connected",
                               "duration_minutes": 12})
    assert logged.status_code == 202 and logged.json()["provider"] == "manual"
    calls = wait_done(client, lid, 2)
    assert calls[0]["provider"] == "manual" and calls[0]["analysis"]["call_intent"] == "positive_intent"

    owner = client.get(f"/api/leads/{lid}", headers=h("boss")).json()["owner_rep_id"]
    other = "R-KENJI" if owner != "R-KENJI" else "R-ANANYA"
    client.patch(f"/api/admin/users/{USERS['rita']}", headers=h("boss"), json={"role": "rep", "rep_id": other})
    assert client.get(f"/api/leads/{lid}/calls", headers=h("rita")).status_code == 404
    assert client.get(f"/api/calls/{call['id']}", headers=h("rita")).status_code == 404
    assert client.get("/api/calls", headers=h("rita")).status_code == 403

    lost = hook(retell_body(event="call_analyzed", call_id="call_api_2", to="+14155550111")).json()
    assert lost["status"] == "accepted"
    for _ in range(200):
        unmatched = client.get("/api/calls?status=unmatched", headers=h("boss")).json()["items"]
        if unmatched:
            break
        time.sleep(0.05)
    assert unmatched[0]["id"] == "retell:call_api_2" and unmatched[0]["lead_name"] is None
    linked = client.post("/api/calls/retell:call_api_2/link", headers=h("boss"), json={"lead_id": lid}).json()
    assert linked["status"] == "done" and linked["lead_id"] == lid
    st = client.get("/api/calls/status", headers=h("boss")).json()
    assert st == {"gemini": {"configured": False, "model": "gemini-2.5-flash"},
                  "recordings": {"configured": False, "bucket": "call-recordings"}}
