"""Accounts and deals: the pure fold and evaluation, the processor projection (order independence, replay),
and the API with role scoping."""
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.engine.opportunity import committee, deal_stall, evaluate_opportunity, fold_opportunities, opp_id_for
from app.engine.scoring import compute_score
from app.engine.types import LeadContext
from app.persistence import NullPersistence
from app.runtime import Runtime
from helpers import Builder, at, fold

ACC = "A-finnova.sg"


def lead(lead_id: str, prefix: str) -> Builder:
    return Builder(lead_id=lead_id, prefix=prefix)


def deals(cfg, *builders, eligible=None, company="FinNova"):
    events = sorted((e for b in builders for e in b.events), key=lambda e: e.sort_key)
    ids = eligible if eligible is not None else {b.lead_id for b in builders}
    return fold_opportunities(ACC, events, ids, company, cfg)


# ================================================================================================ fold
def test_buying_signal_opens_a_deal_that_moves_on_evidence_and_closes(cfg):
    a = lead("L-1", "a")
    a.ev("lead_created", 0, name="Priya", email="priya@finnova.sg")
    a.page("pricing", 1)                                            # browsing alone opens nothing
    assert deals(cfg, a) == []
    demo = a.ev("demo_request", 2)
    a.ev("meeting_held", 30, meeting_type="demo")
    a.ev("proposal_sent", 50, amount=42000)
    a.ev("deal_won", 90, amount=45000)
    [o] = deals(cfg, a)
    assert o.opp_id == opp_id_for(ACC, demo.event_id) and o.open_rule == "O1" and o.kind == "new_business"
    assert o.name == "FinNova · New business" and o.primary_lead_id == "L-1"
    assert [(t["from"], t["to"], t["rule_id"]) for t in o.transitions] == [
        (None, "qualified", "O1"), ("qualified", "meeting", "O4"), ("meeting", "proposal", "O5"), ("proposal", "won", "O7")]
    assert o.status == "won" and o.amount == 45000 and o.closed_at == at(90)


def test_after_a_win_a_new_signal_opens_an_expansion_deal(cfg):
    a = lead("L-1", "a")
    a.ev("lead_created", 0)
    a.ev("contact_sales", 1)
    a.ev("deal_won", 10, amount=20000)
    a.ev("page_view", 200, page_category="pricing")
    a.ev("demo_request", 400)
    first, second = deals(cfg, a)
    assert (first.status, second.status, second.kind) == ("won", "open", "expansion")
    assert second.name.endswith("Expansion") and second.opened_at == at(400)


def test_several_contacts_feed_one_deal_and_only_eligible_ones_open_it(cfg):
    a, b, c = lead("L-1", "a"), lead("L-2", "b"), lead("L-3", "c")
    a.ev("lead_created", 0)
    b.ev("lead_created", 1)
    c.ev("lead_created", 2)
    c.ev("demo_request", 3)                                         # c is fake: cannot open a deal
    assert deals(cfg, a, b, c, eligible={"L-1", "L-2"}) == []
    a.ev("demo_request", 5)
    b.ev("meeting_held", 20, meeting_type="discovery")
    c.ev("email_clicked", 21)                                       # ...but can join an open one
    [o] = deals(cfg, a, b, c, eligible={"L-1", "L-2"})
    assert o.contact_ids == ["L-1", "L-2", "L-3"] and o.stage == "meeting" and o.primary_lead_id == "L-1"


def test_explicit_deals_routing_and_manual_moves(cfg):
    a = lead("L-1", "a")
    a.ev("lead_created", 0)
    a.ev("demo_request", 1)
    a.ev("opportunity_created", 2, opportunity_id="O-team", name="Team plan", amount=9000, close_date="2026-12-31",
         kind="expansion", by="rita@x")
    a.ev("proposal_sent", 3, amount=12000, opportunity_id="O-team")
    a.ev("proposal_sent", 4, amount=30000)                          # no id: the newest open deal (O-team)
    a.ev("opportunity_updated", 5, opportunity_id=opp_id_for(ACC, "a00002"), stage="lost", lost_reason="budget")
    a.ev("meeting_held", 6, meeting_type="demo", opportunity_id=opp_id_for(ACC, "a00002"))  # closed: ignored
    auto, team = deals(cfg, a)
    assert team.opp_id == "O-team" and team.open_rule == "O0" and team.kind == "expansion"
    assert (team.name, team.amount, team.close_date, team.stage, team.created_by) == \
        ("Team plan", 30000, "2026-12-31", "proposal", "rita@x")
    assert auto.stage == "lost" and auto.lost_reason == "budget" and auto.transitions[-1]["mode"] == "manual"
    a.ev("opportunity_updated", 7, opportunity_id=auto.opp_id, stage="negotiation", reason="they came back")
    auto, _ = deals(cfg, a)
    assert auto.status == "open" and auto.lost_reason is None and auto.closed_at is None


def test_negotiating_reply_after_a_proposal_moves_to_negotiation(cfg):
    a = lead("L-1", "a")
    a.ev("lead_created", 0)
    a.ev("contact_sales", 1)
    a.reply("Looks good, can you do a discount on the annual contract?", 2)  # before any proposal: no move
    assert deals(cfg, a)[0].stage == "qualified"
    a.ev("proposal_sent", 3)
    a.reply("Looks good, can you do a discount on the annual contract?", 4)
    assert deals(cfg, a)[0].stage == "negotiation"


# ================================================================================================ evaluation
def test_committee_value_and_close_probability(cfg):
    a = lead("L-1", "a")
    a.capture(cfg)
    a.ev("demo_request", 1)
    a.ev("proposal_sent", 2, amount=50000)
    [o] = deals(cfg, a)
    profile = fold(cfg, a.sorted())[0].profile
    score = compute_score(profile, a.sorted(), at(3), LeadContext(), cfg)
    one = [{"lead_id": "L-1", "seniority": "manager"}]
    three = one + [{"lead_id": "L-2", "seniority": "c_level"}, {"lead_id": "L-3", "seniority": "ic"}]
    e1 = evaluate_opportunity(o, profile, a.sorted(), score, one, at(3), LeadContext(), cfg)
    e3 = evaluate_opportunity(o, profile, a.sorted(), score, three, at(3), LeadContext(), cfg)
    assert e1["acv"]["acv"] == 50000 and e1["acv"]["factors"][-1]["key"] == "deal_amount"
    assert e3["close"]["p"] > e1["close"]["p"] and e3["committee"]["missing"] == []
    assert committee(one, cfg)["covered"] == ["manager"]
    assert e1["expected_value"] == pytest.approx(50000 * e1["close"]["p"])


def test_a_quiet_deal_stalls_after_its_stage_sla(cfg):
    a = lead("L-1", "a")
    a.ev("lead_created", 0)
    a.ev("demo_request", 1)
    a.ev("proposal_sent", 2)
    [o] = deals(cfg, a)
    sla = cfg.pipeline.stall.sla_days["proposal"]
    assert not deal_stall(o, at(2 + 24 * sla - 1), cfg)["is_stalled"]
    st = deal_stall(o, at(2 + 24 * (sla + 3)), cfg)
    assert st["is_stalled"] and st["days_over_sla"] == pytest.approx(3) and "No activity" in st["details"][0]


# ================================================================================================ processor projection
def _account_events(domain: str, start: datetime):
    t = lambda h: (start + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
    people = [("Ada Chief", f"ada@{domain}", "CEO"), ("Ben Lead", f"ben@{domain}", "Director of Ops"),
              ("Cy Dev", f"cy@{domain}", "Engineer")]
    out = [{"event_id": f"c{i}", "type": "lead_created", "ts": t(i), "source": "website",
            "payload": {"name": n, "email": e, "title": ti, "company": "Deal Co", "country": "US",
                        "form_fill_seconds": 30}} for i, (n, e, ti) in enumerate(people)]
    rest = [
        {"event_id": "x1", "type": "demo_request", "ts": t(5), "lead_ref": {"email": people[1][1]}},
        {"event_id": "x2", "type": "meeting_held", "ts": t(30), "actor": "rep", "rep_id": "R-ANANYA",
         "lead_ref": {"email": people[0][1]}, "payload": {"meeting_type": "demo"}},
        {"event_id": "x3", "type": "page_view", "ts": t(31), "lead_ref": {"email": people[2][1]},
         "payload": {"page_category": "pricing"}},
        {"event_id": "x4", "type": "proposal_sent", "ts": t(40), "actor": "rep", "rep_id": "R-ANANYA",
         "lead_ref": {"email": people[1][1]}, "payload": {"amount": 64000}},
        {"event_id": "x5", "type": "deal_won", "ts": t(60), "actor": "rep", "rep_id": "R-ANANYA",
         "lead_ref": {"email": people[1][1]}, "payload": {"amount": 70000}},
        {"event_id": "x6", "type": "contact_sales", "ts": t(200), "lead_ref": {"email": people[2][1]}},
    ]
    return out, rest


def _deal_state(rt):
    return sorted((o.opp_id, o.kind, o.stage, tuple(sorted(o.contact_ids)), o.amount) for o in rt.store.opps.values())


def test_processor_builds_account_deals_independent_of_arrival_order_and_on_replay():
    cfg = load_config()
    created, rest = _account_events("dealco.io", datetime(2026, 9, 1, tzinfo=timezone.utc))
    runs = []
    for seed in (None, 1, 2):
        rt = Runtime(cfg, NullPersistence(), live=True)
        rt.rebuild()
        order = list(rest)
        if seed is not None:
            random.Random(seed).shuffle(order)
        for e in created + order:
            assert rt.emit(dict(e))["status"] == "processed", e
        runs.append(rt)
    first = _deal_state(runs[0])
    assert all(_deal_state(r) == first for r in runs[1:])
    won, expansion = sorted(runs[0].store.opps.values(), key=lambda o: o.opened_at)
    assert (won.stage, won.amount, won.kind, expansion.kind, expansion.stage) == \
        ("won", 70000, "new_business", "expansion", "qualified")
    assert len(won.contact_ids) == 3                                 # all three people fed the first deal
    view = runs[0].store.opp_view(won, detail=True)
    assert view["account_id"] == "A-dealco.io" and set(view["committee"]["covered"]) == \
        {"decision_maker", "manager", "practitioner"}
    cy = runs[0].store.lead_view(runs[0].store.leads[expansion.primary_lead_id], detail=True)
    assert {o["opp_id"] for o in cy["opportunities"]} == {won.opp_id, expansion.opp_id}
    rt = runs[0]
    rt.processor.replay(write=False)
    assert _deal_state(rt) == first


# ================================================================================================ API
SECRET = "test-only-secret-not-used-anywhere-else-0123456789"
SUPA = "https://test-project.supabase.co"
ENV = {"LEADPILOT_MODE": "demo", "LEADPILOT_PERSIST": "0", "LEADPILOT_WARMUP_DAYS": "2", "LEADPILOT_AUTH": "on",
       "SUPABASE_URL": SUPA, "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_ANON_KEY": "sb_publishable_test",
       "LEADPILOT_ADMIN_EMAILS": "boss@test.dev"}
USERS = {name: str(uuid.uuid4()) for name in ("boss", "rita")}
RUN = uuid.uuid4().hex[:6]
DOMAIN = f"deal{RUN}.io"
ACCOUNT = f"A-{DOMAIN}"


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
            assert c.patch(f"/api/admin/users/{USERS['rita']}", headers=h("boss"),
                           json={"role": "rep", "rep_id": "R-ANANYA"}).status_code == 200
            yield c
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(scope="module")
def account(client):
    """Three people at one company: Ada (rita's), Ben and Cy (another rep's). Ben asks for a demo."""
    ids = {}
    for n, email, title in (("Ada Chief", f"ada@{DOMAIN}", "CEO"), ("Ben Lead", f"ben@{DOMAIN}", "Director of Ops"),
                            ("Cy Dev", f"cy@{DOMAIN}", "Engineer")):
        r = client.post("/api/events", headers=h("boss"), json={"type": "lead_created", "source": "website", "payload": {
            "name": n, "email": email, "title": title, "company": "Deal Co", "country": "US", "form_fill_seconds": 30}})
        assert r.status_code == 200, r.text
        ids[n.split()[0]] = r.json()["results"][0]["lead_id"]
    for who, rep in (("Ada", "R-ANANYA"), ("Ben", "R-MARCUS"), ("Cy", "R-MARCUS")):
        assert client.post(f"/api/leads/{ids[who]}/assign", headers=h("boss"), json={"rep_id": rep}).status_code == 200
    r = client.post("/api/events", headers=h("boss"), json={"type": "demo_request", "lead_ref": {"email": f"ben@{DOMAIN}"}})
    assert r.json()["results"][0]["status"] == "processed"
    return ids


def test_accounts_list_and_detail(client, account):
    rows = client.get("/api/accounts", headers=h("boss"), params={"q": DOMAIN}).json()["items"]
    [row] = rows
    assert row["account_id"] == ACCOUNT and row["contacts"] == 3 and row["open_deals"] == 1 and row["pipeline_ev"] > 0
    assert row["committee_covered"] == ["decision_maker", "manager", "practitioner"]
    d = client.get(f"/api/accounts/{ACCOUNT}", headers=h("boss")).json()
    assert [p["name"] for p in d["people"]] and {p["role"] for p in d["people"]} == set(row["committee_covered"])
    [deal] = d["opportunities"]
    assert deal["stage"] == "qualified" and deal["primary_lead_id"] == account["Ben"]
    assert client.get("/api/accounts/A-nope.example", headers=h("boss")).status_code == 404


def test_a_rep_sees_an_account_through_their_contact_only(client, account):
    d = client.get(f"/api/accounts/{ACCOUNT}", headers=h("rita")).json()
    others = [p for p in d["people"] if not p["visible"]]
    assert len(others) == 2 and all("email" not in p and "score" not in p for p in others)
    assert d["opportunities"] == []                                  # Ben's deal has no contact of hers yet
    assert client.get("/api/opportunities", headers=h("rita"), params={"account_id": ACCOUNT}).json()["open_deals"] == 0


def test_deal_lifecycle_through_the_api(client, account):
    board = client.get("/api/opportunities", headers=h("boss"), params={"account_id": ACCOUNT}).json()
    [deal] = [c for col in board["columns"] for c in col["cards"]]
    oid = deal["opp_id"]
    # Ada (rita's contact) attends the demo: she joins the deal, so rita can now see and work it
    r = client.post("/api/events", headers=h("boss"), json={"type": "meeting_held", "actor": "rep", "rep_id": "R-ANANYA",
                                                           "lead_ref": {"email": f"ada@{DOMAIN}"},
                                                           "payload": {"meeting_type": "demo"}})
    assert r.json()["results"][0]["status"] == "processed"
    d = client.get(f"/api/opportunities/{oid}", headers=h("rita")).json()
    assert d["stage"] == "meeting" and {c["lead_id"] for c in d["contacts_detail"]} == {account["Ben"], account["Ada"]}
    assert [t["rule_id"] for t in d["transitions"]] == ["O1", "O4"]

    for body, msg in (({"amount": -5}, "above zero"), ({"close_date": "31/12/2026"}, "YYYY-MM-DD"),
                      ({"close_date": "2026-02-30"}, "real date"), ({"stage": "dreaming"}, "stage"), ({}, "nothing"),
                      ({"name": " "}, "name")):
        r = client.patch(f"/api/opportunities/{oid}", headers=h("rita"), json=body)
        assert r.status_code == 422 and msg in r.json()["detail"], body
    d = client.patch(f"/api/opportunities/{oid}", headers=h("rita"),
                     json={"amount": 55000, "close_date": "2026-12-15", "name": "Deal Co platform"}).json()
    assert (d["amount"], d["acv"], d["close_date"], d["name"]) == (55000, 55000, "2026-12-15", "Deal Co platform")
    d = client.patch(f"/api/opportunities/{oid}", headers=h("rita"), json={"stage": "proposal"}).json()
    assert d["stage"] == "proposal" and d["transitions"][-1]["rule_id"] == "OM"
    d = client.patch(f"/api/opportunities/{oid}", headers=h("rita"), json={"stage": "won"}).json()
    assert d["status"] == "won" and d["close_prob"] == 1 and d["expected_value"] == 55000
    ada = client.get(f"/api/leads/{account['Ada']}", headers=h("rita")).json()     # won through her contact
    assert ada["stage"] == "won" and [o["opp_id"] for o in ada["opportunities"]] == [oid]
    ben = client.get(f"/api/leads/{account['Ben']}", headers=h("boss")).json()
    assert [o["status"] for o in ben["opportunities"]] == ["won"]

    # a second deal for the same company: rep-created, linked to Ada
    new = client.post("/api/opportunities", headers=h("rita"),
                      json={"lead_id": account["Ada"], "name": "Deal Co · EU rollout", "amount": 30000})
    assert new.status_code == 200, new.text
    n = new.json()
    assert n["kind"] == "expansion" and n["open_rule"] == "O0" and n["created_by"] == "rita@test.dev"
    acc = client.get(f"/api/accounts/{ACCOUNT}", headers=h("boss")).json()
    assert acc["deals"] == 2 and acc["open_deals"] == 1 and acc["won_revenue"] == 55000
    lost = client.patch(f"/api/opportunities/{n['opp_id']}", headers=h("rita"),
                        json={"stage": "lost", "lost_reason": "no budget this year"}).json()
    assert lost["status"] == "lost" and lost["lost_reason"] == "no budget this year"

    assert client.post("/api/opportunities", headers=h("rita"), json={"lead_id": account["Ben"]}).status_code == 404
    assert client.post("/api/opportunities", headers=h("boss"),
                       json={"lead_id": account["Ada"], "kind": "upsell"}).status_code == 422
    assert client.get("/api/opportunities/O-missing", headers=h("boss")).status_code == 404
