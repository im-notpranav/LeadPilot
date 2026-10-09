"""REST + WebSocket smoke tests through the real FastAPI app (in-memory, short warm-up)."""
import os
import time

import pytest

os.environ["LEADPILOT_MODE"] = "demo"
os.environ["LEADPILOT_PERSIST"] = "0"
os.environ["LEADPILOT_WARMUP_DAYS"] = "2"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        for _ in range(240):
            if c.get("/api/sim/status").json()["status"] == "ready":
                break
            time.sleep(0.25)
        c.post("/api/sim/pause")
        yield c


def test_status_and_leads(client):
    s = client.get("/api/sim/status").json()
    assert s["status"] == "ready" and s["leads"] > 0
    items = client.get("/api/leads", params={"limit": 5, "sort": "score"}).json()["items"]
    assert items and items[0]["score"] >= items[-1]["score"]
    lid = items[0]["lead_id"]
    d = client.get(f"/api/leads/{lid}").json()
    assert d["lead_id"] == lid and "factors" in d and "transitions" in d
    tl = client.get(f"/api/leads/{lid}/timeline").json()["items"]
    assert {i["kind"] for i in tl} >= {"event", "score"}
    hist = client.get(f"/api/leads/{lid}/score-history").json()["points"]
    assert hist and "contributions" in hist[-1]


def test_ingest_event_rescoring(client):
    lead = client.get("/api/leads", params={"limit": 1, "include_closed": False}).json()["items"][0]
    r = client.post("/api/events", json={"type": "page_view", "lead_ref": {"lead_id": lead["lead_id"]},
                                         "payload": {"url": "/pricing", "page_category": "pricing"}}).json()
    res = r["results"][0]
    assert res["status"] == "processed" and res["lead_id"] == lead["lead_id"]
    again = client.post("/api/events", json={"event_id": "dup-check-1", "type": "page_view",
                                             "lead_ref": {"lead_id": lead["lead_id"]},
                                             "payload": {"page_category": "blog"}}).json()
    assert again["results"][0]["status"] == "processed"
    dup = client.post("/api/events", json={"event_id": "dup-check-1", "type": "page_view"}).json()
    assert dup["results"][0]["status"] == "duplicate"


def test_views(client):
    reps = client.get("/api/reps").json()["items"]
    assert len(reps) == 8
    q = client.get(f"/api/queue/{reps[0]['rep_id']}").json()
    assert q["items"] == sorted(q["items"], key=lambda v: -v["priority"])
    cols = client.get("/api/pipeline").json()["columns"]
    assert [c["stage"] for c in cols][:3] == ["new", "contacted", "engaged"]
    for path in ("funnel", "response-times", "rep-performance", "score-calibration", "source-quality"):
        assert client.get(f"/api/analytics/{path}").status_code == 200
    for path in ("review-queue", "quarantine", "merges"):
        assert client.get(f"/api/quality/{path}").status_code == 200
    assert client.get("/api/feed", params={"limit": 5}).json()["items"]


def test_scenario_step_and_action_done(client):
    info = client.post("/api/sim/scenario/reviver").json()
    lid = info["lead_id"]
    client.post("/api/sim/step", json={"minutes": 15 * 60})
    d = client.get(f"/api/leads/{lid}").json()
    assert d["stage"] in ("qualified", "meeting") and d["intent_level"] in ("hot", "high")
    act = d["primary_action"]
    assert act is not None
    r = client.post(f"/api/actions/{act['id']}/done").json()
    assert r["status"] == "processed"
    d2 = client.get(f"/api/leads/{lid}").json()
    assert d2["primary_action"] is None or d2["primary_action"]["id"] != act["id"]


def test_manual_actions(client):
    lead = client.get("/api/leads", params={"limit": 1, "include_closed": False}).json()["items"][0]
    lid = lead["lead_id"]
    r = client.post(f"/api/leads/{lid}/assign", json={"rep_id": "R-KENJI"}).json()
    assert client.get(f"/api/leads/{lid}").json()["owner_rep_id"] == "R-KENJI"
    client.post(f"/api/leads/{lid}/override-stage", json={"to_stage": "engaged", "reason": "test"})
    d = client.get(f"/api/leads/{lid}").json()
    assert d["stage"] == "engaged" and d["transitions"][-1]["mode"] == "manual"
    assert client.post(f"/api/leads/{lid}/override-stage", json={"to_stage": "bogus"}).status_code == 422


def test_replay_and_ws(client):
    before = client.get("/api/sim/status").json()
    r = client.post("/api/replay").json()
    assert r["leads"] >= 1
    after = client.get("/api/sim/status").json()
    assert after["leads"] == before["leads"]
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "batch" and msg["messages"][0]["type"] == "sim.clock"
