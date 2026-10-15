"""Quotes on deals: lines and totals, the fold (every quote event, out-of-state events ignored), the processor
projection and replay, and the API: drafting, approval, sending, the buyer's link, and role scope."""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import load_config
from app.engine.opportunity import fold_opportunities
from app.engine.quotes import QuoteError, clean_lines, display_status, totals
from app.persistence import NullPersistence
from app.runtime import Runtime
from helpers import Builder

ACC = "A-quoteco.io"
LINES = [{"sku": "LP-PRO", "qty": 20}, {"sku": "LP-ONBOARD", "qty": 1}]       # 24,000 recurring + 5,000 one-time


def deal_with(cfg, build):
    """One deal (opened by a demo request) plus whatever `build(b, oid)` adds; returns the folded deal."""
    b = Builder(lead_id="L-1", prefix="q")
    b.ev("lead_created", 0, name="Quinn", email="quinn@quoteco.io")
    b.ev("demo_request", 1)
    [o] = fold_opportunities(ACC, list(b.events), {"L-1"}, "QuoteCo", cfg)
    build(b, o.opp_id)
    events = sorted(b.events, key=lambda e: e.sort_key)
    [o] = fold_opportunities(ACC, events, {"L-1"}, "QuoteCo", cfg)
    return o


# ================================================================================================ lines and totals
def test_lines_take_catalog_defaults_and_bad_lines_are_refused_or_dropped(cfg):
    lines = clean_lines(LINES + [{"name": "Custom report", "qty": 2, "unit_price": 750, "billing": "one_time",
                                  "discount_pct": 10}], cfg)
    assert [(ln["name"], ln["unit_price"], ln["billing"]) for ln in lines] == [
        ("LeadPilot Pro", 1200, "recurring"), ("Onboarding and setup", 5000, "one_time"), ("Custom report", 750, "one_time")]
    assert lines[0]["unit"] == "seat" and lines[2]["discount_pct"] == 10
    for bad, msg in (([{"qty": 1}], "needs a name"), ([{"name": "X", "qty": 0, "unit_price": 1}], "quantity"),
                     ([{"name": "X", "unit_price": -5}], "unit price"), ([{"name": "X", "unit_price": 1, "discount_pct": 120}], "discount"),
                     ([{"name": "X", "unit_price": 1, "billing": "monthly"}], "billing"), ("nope", "must be a list")):
        with pytest.raises(QuoteError, match=msg):
            clean_lines(bad, cfg)
    assert clean_lines([{"qty": 1}, {"sku": "LP-CORE"}], cfg, strict=False)[0]["name"] == "LeadPilot Core"


def test_totals_apply_line_then_quote_discounts():
    lines = [{"qty": 10, "unit_price": 1000, "discount_pct": 10, "billing": "recurring"},
             {"qty": 1, "unit_price": 5000, "discount_pct": 0, "billing": "one_time"}]
    t = totals(lines, 5)
    assert t["list_total"] == 15000 and t["line_discounts"] == 1000 and t["subtotal"] == 14000
    assert t["recurring"] == 8550 and t["one_time"] == 4750 and t["total"] == 13300 and t["quote_discount"] == 700
    assert t["effective_discount_pct"] == round(1700 / 15000 * 100, 2) and t["line_totals"] == [9000, 5000]
    assert totals([], 50)["total"] == 0 and totals([], 50)["effective_discount_pct"] == 0


# ================================================================================================ fold
def test_an_approved_quote_is_sent_viewed_and_accepted(cfg):
    def build(b, oid):
        b.ev("quote_created", 2, actor="rep", opportunity_id=oid, quote_id="Q-1", title="Pro for 20", lines=LINES,
             discount_pct=20, valid_until="2026-11-30", token="t" * 32, by="rita@test.dev")
        b.ev("quote_revised", 4, actor="rep", opportunity_id=oid, quote_id="Q-1", discount_pct=18)
        b.ev("quote_approved", 5, actor="rep", opportunity_id=oid, quote_id="Q-1", rev=1, by="old rev")  # stale
        b.ev("quote_approved", 6, actor="rep", opportunity_id=oid, quote_id="Q-1", rev=2, by="boss@test.dev")
        b.ev("proposal_sent", 7, opportunity_id=oid, quote_id="Q-1", amount=23780)
        b.ev("proposal_viewed", 8, opportunity_id=oid, quote_id="Q-1")
        b.ev("proposal_viewed", 9, opportunity_id=oid, quote_id="Q-1")
        b.ev("deal_won", 10, opportunity_id=oid, quote_id="Q-1", amount=23780, accepted_by={"name": "Quinn"})

    o = deal_with(cfg, build)
    q = o.quotes["Q-1"]
    assert (q.rev, q.approved_rev, q.approved_by, q.needs_approval) == (2, 2, "boss@test.dev", True)
    assert q.totals["total"] == round(29000 * 0.82, 2) == 23780 and q.discount_pct == 18
    assert (q.status, q.views, q.accepted_by) == ("accepted", 2, {"name": "Quinn"})
    assert [t["rule_id"] for t in o.transitions] == ["O1", "O5", "O7"] and o.status == "won" and o.amount == 23780
    assert q.terms == cfg.quotes.terms                                  # not in the payload: the configured terms


def test_out_of_state_events_are_ignored(cfg):
    def build(b, oid):
        b.ev("quote_created", 2, actor="rep", opportunity_id=oid, quote_id="Q-1", lines=LINES, token="a" * 32)
        b.ev("quote_created", 2.5, actor="rep", opportunity_id=oid, quote_id="Q-1", lines=[])        # duplicate id
        b.ev("deal_won", 3, opportunity_id=oid, quote_id="Q-1", amount=99)          # a draft cannot be accepted
        b.ev("quote_declined", 3.5, opportunity_id=oid, quote_id="Q-1")             # nor declined
        b.ev("quote_revised", 4, actor="rep", opportunity_id=oid, quote_id="Q-NOPE", lines=[])
        b.ev("quote_created", 5, actor="rep", opportunity_id="O-elsewhere", quote_id="Q-2", lines=LINES)

    o = deal_with(cfg, build)
    assert list(o.quotes) == ["Q-1"] and o.quotes["Q-1"].status == "draft" and len(o.quotes["Q-1"].lines) == 2
    assert o.status == "won"                     # the deal_won itself still wins the deal; the quote stays a draft


def test_new_versions_supersede_and_declines_and_voids_close_quotes(cfg):
    def build(b, oid):
        b.ev("quote_created", 2, actor="rep", opportunity_id=oid, quote_id="Q-1", lines=LINES)
        b.ev("proposal_sent", 3, opportunity_id=oid, quote_id="Q-1", amount=29000)
        b.ev("quote_declined", 4, opportunity_id=oid, quote_id="Q-1", reason="Too pricey")
        b.ev("quote_revised", 4.5, actor="rep", opportunity_id=oid, quote_id="Q-1", discount_pct=5)  # not a draft
        b.ev("quote_created", 5, actor="rep", opportunity_id=oid, quote_id="Q-2", lines=LINES, discount_pct=10,
             supersedes="Q-1")
        b.ev("proposal_sent", 6, opportunity_id=oid, quote_id="Q-2", amount=26100)
        b.ev("quote_created", 7, actor="rep", opportunity_id=oid, quote_id="Q-3", lines=LINES, supersedes="Q-2")
        b.ev("quote_voided", 8, actor="rep", opportunity_id=oid, quote_id="Q-3", reason="Wrong contact")
        b.ev("quote_created", 9, actor="rep", opportunity_id=oid, quote_id="Q-4", lines=LINES)

    o = deal_with(cfg, build)
    st = {k: q.status for k, q in o.quotes.items()}
    assert st == {"Q-1": "declined", "Q-2": "superseded", "Q-3": "void", "Q-4": "draft"}
    assert o.quotes["Q-1"].decline_reason == "Too pricey" and o.quotes["Q-1"].discount_pct == 0
    assert o.quotes["Q-2"].superseded_by == "Q-3" and o.quotes["Q-3"].void_reason == "Wrong contact"
    assert o.stage == "proposal" and o.amount == 26100 and o.status == "open"


def test_display_status_expires_sent_quotes_and_flags_approval(cfg):
    def build(b, oid):
        b.ev("quote_created", 2, actor="rep", opportunity_id=oid, quote_id="Q-1", lines=LINES, valid_until="2026-10-20")
        b.ev("proposal_sent", 3, opportunity_id=oid, quote_id="Q-1", amount=29000)
        b.ev("quote_created", 4, actor="rep", opportunity_id=oid, quote_id="Q-2", lines=LINES, discount_pct=40)

    o = deal_with(cfg, build)
    q1, q2 = o.quotes["Q-1"], o.quotes["Q-2"]
    assert display_status(q1, "2026-10-20") == "sent" and display_status(q1, "2026-10-21") == "expired"
    assert display_status(q2, "2026-10-21") == "needs_approval" and not q2.ready and q1.ready is False


# ================================================================================================ processor
def _events() -> list[dict]:
    t = datetime(2026, 9, 1, 9, tzinfo=timezone.utc)
    iso = lambda h: (t + timedelta(hours=h)).isoformat()      # noqa: E731
    ref = {"email": "quinn@quoteproc.io"}
    return [
        {"event_id": "p-1", "type": "lead_created", "ts": iso(0), "source": "website",
         "payload": {"name": "Quinn Proc", "email": "quinn@quoteproc.io", "company": "QuoteProc", "title": "CFO",
                     "country": "US", "form_fill_seconds": 30}},
        {"event_id": "p-2", "type": "opportunity_created", "ts": iso(1), "actor": "rep", "lead_ref": ref,
         "payload": {"opportunity_id": "O-proc"}},
        {"event_id": "p-3", "type": "quote_created", "ts": iso(2), "actor": "rep", "lead_ref": ref,
         "payload": {"opportunity_id": "O-proc", "quote_id": "Q-P1", "lines": LINES, "token": "p" * 32}},
        {"event_id": "p-4", "type": "proposal_sent", "ts": iso(3), "actor": "rep", "lead_ref": ref,
         "payload": {"opportunity_id": "O-proc", "quote_id": "Q-P1", "amount": 29000}},
        {"event_id": "p-5", "type": "proposal_viewed", "ts": iso(4), "actor": "prospect", "lead_ref": ref,
         "payload": {"opportunity_id": "O-proc", "quote_id": "Q-P1"}},
    ]


def test_processor_projects_quotes_and_a_replay_rebuilds_them():
    cfg = load_config()
    rt = Runtime(cfg, NullPersistence(), live=True)
    rt.rebuild()
    seen = []
    rt.processor.listeners.append(lambda kind, d: seen.append(d) if kind == "quote.changed" else None)
    for e in _events():
        assert rt.emit(dict(e))["status"] == "processed", e
    o = rt.store.opps["O-proc"]
    row = rt.store.quote_rows["Q-P1"]
    assert (row["status"], row["total"], row["views"], o.stage, o.amount) == ("sent", 29000, 1, "proposal", 29000)
    assert rt.store.quote_tokens["p" * 32] == ("O-proc", "Q-P1")
    assert [(d["status"], d["from"], d["first_view"]) for d in seen] == [
        ("draft", None, False), ("sent", "draft", False), ("sent", "sent", True)]
    view = rt.store.opp_view(o, detail=True)
    assert view["quote"]["status"] == "sent" and view["quotes"][0]["link"] == "/q/" + "p" * 32
    before = dict(row)
    rt.processor.replay()
    assert rt.store.quote_rows["Q-P1"] == before and rt.store.opps["O-proc"].quotes["Q-P1"].views == 1


# ================================================================================================ API
SECRET = "test-only-secret-not-used-anywhere-else-0123456789"
SUPA = "https://test-project.supabase.co"
ENV = {"LEADPILOT_MODE": "demo", "LEADPILOT_PERSIST": "0", "LEADPILOT_WARMUP_DAYS": "2", "LEADPILOT_AUTH": "on",
       "SUPABASE_URL": SUPA, "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_ANON_KEY": "sb_publishable_test",
       "LEADPILOT_ADMIN_EMAILS": "boss@test.dev"}
USERS = {name: str(uuid.uuid4()) for name in ("boss", "rita", "max")}
RUN = uuid.uuid4().hex[:6]
DOMAIN = f"quote{RUN}.io"


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
            assert c.patch(f"/api/admin/users/{USERS['max']}", headers=h("boss"),
                           json={"role": "rep", "rep_id": "R-MARCUS"}).status_code == 200
            yield c
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(scope="module")
def deal(client):
    """A lead of rita's with a deal she created."""
    r = client.post("/api/events", headers=h("boss"), json={"type": "lead_created", "source": "website", "payload": {
        "name": "Quinn Buyer", "email": f"quinn@{DOMAIN}", "title": "CFO", "company": "Quote Co", "country": "US",
        "form_fill_seconds": 30}})
    lid = r.json()["results"][0]["lead_id"]
    assert client.post(f"/api/leads/{lid}/assign", headers=h("boss"), json={"rep_id": "R-ANANYA"}).status_code == 200
    d = client.post("/api/opportunities", headers=h("rita"), json={"lead_id": lid, "name": "Quote Co rollout"})
    assert d.status_code == 200, d.text
    return {"lead_id": lid, "opp_id": d.json()["opp_id"]}


def test_catalog(client):
    c = client.get("/api/quotes/catalog", headers=h("rita")).json()
    assert c["currency"] == "USD" and c["max_discount_pct"] == 15 and {p["sku"] for p in c["catalog"]} >= {"LP-PRO"}
    assert c["email"]["ready"] is False and "RESEND_API_KEY" in c["email"]["reason"]


def test_draft_approve_send_and_the_buyer_accepts(client, deal):
    oid = deal["opp_id"]
    bad = client.post(f"/api/opportunities/{oid}/quotes", headers=h("rita"), json={"lines": []})
    assert bad.status_code == 422 and "at least one line" in bad.text
    assert client.post(f"/api/opportunities/{oid}/quotes", headers=h("rita"),
                       json={"lines": LINES, "valid_until": "2020-01-01"}).status_code == 422
    q = client.post(f"/api/opportunities/{oid}/quotes", headers=h("rita"),
                    json={"lines": LINES, "discount_pct": 25, "notes": "Includes onboarding."}).json()
    qid = q["quote_id"]
    assert q["status"] == "needs_approval" and q["title"] == "Quote Co rollout quote" and q["totals"]["total"] == 21750
    assert q["recipient"]["lead_id"] == deal["lead_id"] and q["valid_until"] and q["terms"]
    assert client.post(f"/api/quotes/{qid}/send", headers=h("rita")).status_code == 409        # needs approval
    assert client.post(f"/api/quotes/{qid}/approve", headers=h("rita")).status_code == 403     # reps cannot approve
    assert client.get(f"/api/quotes/{qid}", headers=h("max")).status_code == 404               # not max's deal
    n = client.get("/api/notifications", headers=h("boss")).json()["items"]
    assert any(x["rule"] == "quote_approval" and x["opp_id"] == oid for x in n)

    token = q["link"].split("/q/")[1]
    assert client.get(f"/api/public/quotes/{token}").status_code == 404                        # drafts are private

    rev = client.patch(f"/api/quotes/{qid}", headers=h("rita"), json={"discount_pct": 20, "title": "Pro rollout"}).json()
    assert (rev["rev"], rev["status"], rev["totals"]["total"], rev["title"]) == (2, "needs_approval", 23200, "Pro rollout")
    ok = client.post(f"/api/quotes/{qid}/approve", headers=h("boss")).json()
    assert ok["status"] == "draft" and ok["approved"] and ok["approved_by"] == "boss@test.dev" and ok["ready"]
    assert client.post(f"/api/quotes/{qid}/approve", headers=h("boss")).status_code == 409
    assert client.post(f"/api/quotes/{qid}/send", headers=h("rita"), json={"email": True}).status_code == 409  # no Resend
    sent = client.post(f"/api/quotes/{qid}/send", headers=h("rita")).json()
    assert sent["status"] == "sent" and sent["emailed_to"] is None
    assert client.patch(f"/api/quotes/{qid}", headers=h("rita"), json={"discount_pct": 0}).status_code == 409
    d = client.get(f"/api/opportunities/{oid}", headers=h("rita")).json()
    assert d["stage"] == "proposal" and d["amount"] == 23200 and d["quote"] == {"quote_id": qid, "status": "sent", "total": 23200}

    pv = client.get(f"/api/public/quotes/{token}", params={"preview": "true"}).json()
    assert pv["status"] == "sent" and pv["answerable"] and pv["seller_name"] == "LeadPilot"
    assert "opp_id" not in pv and "lead_id" not in pv["recipient"] and "link" not in pv and "created_by" not in pv
    assert client.get(f"/api/quotes/{qid}", headers=h("rita")).json()["views"] == 0             # previews don't count
    client.get(f"/api/public/quotes/{token}")
    client.get(f"/api/public/quotes/{token}")                                                   # within 6h: one view
    assert client.get(f"/api/quotes/{qid}", headers=h("rita")).json()["views"] == 1
    assert client.get("/api/public/quotes/" + "x" * 32).status_code == 404
    assert client.get("/api/public/quotes/short").status_code == 404

    assert client.post(f"/api/public/quotes/{token}/accept", json={}).status_code == 422          # needs a name
    acc = client.post(f"/api/public/quotes/{token}/accept", json={"name": "Quinn Buyer", "title": "CFO"}).json()
    assert acc["status"] == "accepted" and acc["accepted_by"]["name"] == "Quinn Buyer" and not acc["answerable"]
    assert client.post(f"/api/public/quotes/{token}/decline", json={}).status_code == 409
    d = client.get(f"/api/opportunities/{oid}", headers=h("rita")).json()
    assert d["status"] == "won" and d["amount"] == 23200 and d["transitions"][-1]["rule_id"] == "O7"
    lead = client.get(f"/api/leads/{deal['lead_id']}", headers=h("rita")).json()
    assert lead["stage"] == "won"
    mine = client.get("/api/quotes", headers=h("rita")).json()["items"]
    assert [x["quote_id"] for x in mine if x["opp_id"] == oid] == [qid]
    assert client.get("/api/quotes", headers=h("max")).json()["total"] == 0


def test_a_buyer_declines_then_a_new_version_supersedes_and_voids(client):
    r = client.post("/api/events", headers=h("boss"), json={"type": "lead_created", "source": "website", "payload": {
        "name": "Dee Cline", "email": f"dee@d{DOMAIN}", "title": "VP Sales", "company": "Decline Co", "country": "US",
        "form_fill_seconds": 30}})
    lid = r.json()["results"][0]["lead_id"]
    client.post(f"/api/leads/{lid}/assign", headers=h("boss"), json={"rep_id": "R-ANANYA"})
    oid = client.post("/api/opportunities", headers=h("rita"), json={"lead_id": lid}).json()["opp_id"]
    q = client.post(f"/api/opportunities/{oid}/quotes", headers=h("rita"), json={"lines": LINES}).json()
    assert q["status"] == "draft" and q["ready"]
    client.post(f"/api/quotes/{q['quote_id']}/send", headers=h("rita"))
    token = q["link"].split("/q/")[1]
    dec = client.post(f"/api/public/quotes/{token}/decline", json={"reason": "Over budget"}).json()
    assert dec["status"] == "declined" and dec["decline_reason"] == "Over budget"
    n = client.get("/api/notifications", headers=h("rita")).json()["items"]
    assert any(x["rule"] == "quote_declined" and "Over budget" in x["body"] for x in n)
    d = client.get(f"/api/opportunities/{oid}", headers=h("rita")).json()
    assert d["status"] == "open" and d["stage"] == "proposal"

    v2 = client.post(f"/api/opportunities/{oid}/quotes", headers=h("rita"),
                     json={"lines": LINES, "discount_pct": 10, "supersedes": q["quote_id"]}).json()
    assert v2["supersedes"] == q["quote_id"] and v2["status"] == "draft"
    client.post(f"/api/quotes/{v2['quote_id']}/send", headers=h("rita"))
    rec = client.post(f"/api/quotes/{v2['quote_id']}/decline", headers=h("rita"), json={"reason": "Phone call"}).json()
    assert rec["status"] == "declined"
    v3 = client.post(f"/api/opportunities/{oid}/quotes", headers=h("rita"), json={"lines": LINES}).json()
    gone = client.post(f"/api/quotes/{v3['quote_id']}/void", headers=h("rita"), json={"reason": "Typo"}).json()
    assert gone["status"] == "void" and gone["void_reason"] == "Typo"
    assert client.get("/api/public/quotes/" + v3["link"].split("/q/")[1]).status_code == 404
    assert client.post(f"/api/quotes/{v3['quote_id']}/send", headers=h("rita")).status_code == 409
    statuses = [x["status"] for x in client.get(f"/api/opportunities/{oid}", headers=h("rita")).json()["quotes"]]
    assert statuses == ["void", "declined", "declined"]

    client.patch(f"/api/opportunities/{oid}", headers=h("rita"), json={"stage": "lost", "lost_reason": "Budget"})
    assert client.post(f"/api/opportunities/{oid}/quotes", headers=h("rita"), json={"lines": LINES}).status_code == 409
