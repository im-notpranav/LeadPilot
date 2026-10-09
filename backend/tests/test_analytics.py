"""Analytics return correct numbers on a hand-built fixture (M8)."""
from datetime import timedelta

import pytest

from app.analytics.calibration import score_calibration
from app.analytics.funnel import funnel
from app.analytics.rep_performance import rep_performance
from app.analytics.response_time import response_times
from app.analytics.source_quality import compute_source_quality
from app.engine.types import iso
from app.runtime import Runtime


@pytest.fixture(scope="module")
def world(cfg):
    rt = Runtime(cfg)
    rt.reset(warmup=False, background=False, rep_actions=False)
    t0 = rt.clock.now()
    n = [0]

    def emit(type_, minutes, lead=None, actor="prospect", rep=None, source=None, **payload):
        n[0] += 1
        return rt.processor.handle({"event_id": f"f{n[0]:03d}", "type": type_, "ts": iso(t0 + timedelta(minutes=minutes)),
                                    "ingested_at": iso(t0 + timedelta(minutes=minutes)), "actor": actor, "rep_id": rep,
                                    "source": source, "lead_ref": {"lead_id": lead} if lead else {}, "payload": payload})

    def owner(lid):
        return rt.store.leads[lid].owner

    l1 = emit("lead_created", 0, source="website", name="Priya Nair", email="priya@finnova.sg", company="FinNova",
              title="Head of Operations", country="SG", capture_method="form_submit", ip="112.1.1.1")["lead_id"]
    emit("email_sent", 30, l1, "rep", owner(l1))
    emit("lead_created", 40, source="website", name="Priya Nair", email="PRIYA@finnova.sg", country="SG",
         capture_method="form_submit")                                                     # duplicate capture
    emit("lead_created", 50, source="list_vendor_x", name="Xkcd Qwrtz", email="asdf@mailinator.com",
         company="Test Co", phone="9999999999", capture_method="cold_import", form_fill_seconds=1)   # fake
    l4 = emit("lead_created", 60, source="list_vendor_x", name="Arjun Patel", email="arjun@acme.io", company="Acme",
              title="CTO", country="IN", capture_method="cold_import")["lead_id"]
    emit("email_sent", 180, l4, "rep", owner(l4))
    emit("bant_qualified", 200, l4, "rep", owner(l4))
    l5 = emit("lead_created", 70, source="website", name="Dana Wells", email="dana@helixhealth.com",
              company="Helix Health", title="VP Operations", country="US", capture_method="form_submit")["lead_id"]
    emit("demo_request", 80, l5)
    emit("email_sent", 90, l5, "rep", owner(l5))
    emit("meeting_held", 300, l5, "rep", owner(l5), meeting_type="demo")
    emit("proposal_sent", 400, l5, "rep", owner(l5), amount=90000)
    emit("deal_won", 500, l5, "rep", owner(l5), amount=90000)
    rt.clock.set(t0 + timedelta(minutes=600))
    return rt, {"l1": l1, "l4": l4, "l5": l5}


def test_funnel_counts(world, cfg):
    rt, ids = world
    f = funnel(rt.store, cfg)
    assert f["total"] == 3                              # duplicate merged away, fake excluded
    reached = {s["stage"]: s["reached"] for s in f["stages"]}
    assert reached["new"] == 3 and reached["contacted"] == 3 and reached["qualified"] == 2 and reached["won"] == 1
    conv = {(c["from"], c["to"]): c["rate"] for c in f["conversions"]}
    assert conv[("contacted", "engaged")] == pytest.approx(2 / 3, abs=1e-3)


def test_source_quality_rates(world, cfg):
    rt, _ = world
    sq = compute_source_quality(rt.store, cfg, rt.clock.now(), window_days=30)
    web, vendor = sq["website"], sq["list_vendor_x"]
    assert web["volume"] == 3 and web["duplicates"] == 1 and web["dup_rate"] == pytest.approx(1 / 3)
    assert web["won"] == 1 and web["revenue"] == pytest.approx(90000)
    assert vendor["volume"] == 2 and vendor["fake_rate"] == pytest.approx(0.5)
    assert vendor["sql_rate"] == pytest.approx(1.0)       # the one real vendor lead qualified
    assert 0 < vendor["quality_index"] <= 1


def test_response_times(world, cfg):
    rt, ids = world
    r = response_times(rt.store, cfg, rt.clock.now())
    assert r["overall"]["n"] == 3
    assert r["overall"]["median_first_response_min"] == pytest.approx(30)
    by_rep = {x["rep_id"]: x for x in r["reps"]}
    rep = rt.store.leads[ids["l1"]].owner
    assert by_rep[rep]["n"] >= 1


def test_rep_performance_counts_live_win(world, cfg):
    rt, ids = world
    rows = {r["rep_id"]: r for r in rep_performance(rt.store, cfg, rt.clock.now())}
    winner = rt.store.leads[ids["l5"]].owner
    assert rows[winner]["won_live"] == 1 and rows[winner]["revenue"] > 0


def test_score_calibration(world):
    rt, _ = world
    c = score_calibration(rt.store)
    grades = {g["grade"]: g for g in c["grades"]}
    assert grades["A"]["historical_win_rate"] > grades["D"]["historical_win_rate"]
    assert len(c["score_distribution"]) == 10
    assert len(c["model"]["coefficients"]) == 5 and len(c["model"]["calibration"]) == 10
    coef = {x["feature"]: x["coef"] for x in c["model"]["coefficients"]}
    assert coef["score"] > 0 and coef["stalled"] < 0
