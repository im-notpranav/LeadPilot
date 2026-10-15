"""Connectors: field mapping, signatures, email parsing, CSV import (pure), then every inbound path through the
real FastAPI app with auth on (test-signed tokens, in memory)."""
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.connectors import signing
from app.connectors.csv_import import CsvImportError, map_rows
from app.connectors.email_parse import email_event, strip_quoted
from app.connectors.fields import flatten, lead_events, lead_from_fields, page_category, parse_when
from app.engine.intent import reply_class

UTC = timezone.utc


# ================================================================================================ field mapping
def test_flatten_understands_crm_and_form_shapes():
    hubspot_v1 = {"vid": 51, "properties": {"email": {"value": "ann@acme.io"}, "firstname": {"value": "Ann"}}}
    assert flatten(hubspot_v1) == {"vid": "51", "email": "ann@acme.io", "firstname": "Ann"}
    hubspot_v3 = {"id": "9", "properties": {"email": "bo@beta.io", "company": "Beta"}}
    assert flatten(hubspot_v3)["company"] == "Beta"
    pipedrive = {"name": "Cy", "email": [{"value": "old@c.io"}, {"value": "cy@c.io", "primary": True}],
                 "phone": [{"value": "+1 555 0100", "primary": True}]}
    flat = flatten(pipedrive)
    assert flat["email"] == "cy@c.io" and flat["phone"] == "+1 555 0100"
    typeform = {"form_response": {
        "definition": {"fields": [{"id": "f1", "title": "Work email"}, {"id": "f2", "title": "Interest"}]},
        "answers": [{"type": "email", "email": "di@d.io", "field": {"id": "f1"}},
                    {"type": "choice", "choice": {"label": "Book a demo"}, "field": {"id": "f2"}}]}}
    flat = flatten(typeform)
    assert flat["Work email"] == "di@d.io" and flat["Interest"] == "Book a demo"
    assert flatten({"data": {"Email": "w@f.io"}, "name": "Webflow form"})["Email"] == "w@f.io"


def test_lead_from_fields_maps_aliases_and_intent():
    m = lead_from_fields({"Email Address": "Ann Lee <ann@acme.io>", "First Name": "Ann", "Last Name": "Lee",
                          "Organisation": "Acme", "Country": "United Kingdom", "utm_campaign": "q4",
                          "Secret thing": "dropped"}, source="website", form_name="Request a demo", ip="1.2.3.4")
    assert m["ok"] and m["intent"] == "demo_request" and m["source"] == "website"
    pl = m["payload"]
    assert pl["email"] == "ann@acme.io" and pl["name"] == "Ann Lee" and pl["company"] == "Acme"
    assert pl["country"] == "GB" and pl["utm_campaign"] == "q4" and pl["ip"] == "1.2.3.4"
    assert "Secret thing" not in m["used"] and m["lead_ref"] == {"email": "ann@acme.io"}

    phone_only = lead_from_fields({"mobile": "+44 7700 900123", "country": "GB"}, source="crm")
    assert phone_only["ok"] and phone_only["lead_ref"] == {"phone": "+44 7700 900123", "country": "GB"}
    assert lead_from_fields({"name": "Nobody"}, source="x") == {"ok": False, "error": "no email address or phone number",
                                                                "used": {"name": "name"}}
    # a fixed form kind wins over the form name; non-form capture never implies intent
    assert lead_from_fields({"email": "a@b.io"}, source="s", form_name="Demo", form_kind="contact_sales")["intent"] \
        == "contact_sales"
    assert lead_from_fields({"email": "a@b.io", "form": "demo"}, source="s", capture_method="ad_lead")["intent"] is None
    # the record's own lead source only when asked for; explicit column map overrides aliases
    rec = {"email": "a@b.io", "Lead Source": "Organic Search", "company": "Ignored Inc"}
    assert lead_from_fields(rec, source="crm", use_record_source=True)["source"] == "organic_search"
    assert lead_from_fields(rec, source="crm")["source"] == "crm"
    assert "company" not in lead_from_fields(rec, source="crm", column_map={"company": ""})["payload"]


def test_lead_events_add_the_intent_event_and_history_flag():
    m = lead_from_fields({"email": "a@b.io", "form type": "Free trial", "created": "2026-01-05"}, source="web")
    evs = lead_events(m, "frm_1", history=True)
    assert [e["type"] for e in evs] == ["lead_created", "trial_signup"]
    assert evs[1]["event_id"] == "frm_1.i" and evs[1]["lead_ref"] == {"email": "a@b.io"}
    assert all(e["import"] and e["ts"].startswith("2026-01-05") for e in evs)
    assert [e["type"] for e in lead_events(lead_from_fields({"email": "a@b.io"}, source="w"), "x")] == ["lead_created"]


@pytest.mark.parametrize("raw,expected", [
    ("1760086800", datetime(2025, 10, 10, 9, 0, tzinfo=UTC)),
    ("1760086800000", datetime(2025, 10, 10, 9, 0, tzinfo=UTC)),
    ("2026-02-13T10:30:00Z", datetime(2026, 2, 13, 10, 30, tzinfo=UTC)),
    ("13/02/2026", datetime(2026, 2, 13, tzinfo=UTC)),
    ("02/03/2026 14:05", datetime(2026, 3, 2, 14, 5, tzinfo=UTC)),
    ("Jan 5, 2026", datetime(2026, 1, 5, tzinfo=UTC)),
    ("not a date", None),
    ("31/31/2026", None),
])
def test_parse_when(raw, expected):
    assert parse_when(raw) == expected


@pytest.mark.parametrize("path,category", [
    ("/", "home"), ("/pricing", "pricing"), ("/plans/team?x=1", "pricing"), ("/enterprise", "enterprise_plan"),
    ("/compare/acme-vs-us", "competitor_compare"), ("/customers/", "case_study"), ("/roi-calculator", "roi"),
    ("/blog/how-to", "blog"), ("/docs/api", "docs"), ("/features", "product"), ("/careers", "other"),
])
def test_page_category(path, category):
    assert page_category(path) == category


def test_page_rules_override_the_defaults():
    rules = [{"pattern": r"^/book", "category": "pricing"}, {"pattern": "(", "category": "broken"}]
    assert page_category("/book-a-call", rules) == "pricing"
    assert page_category("/blog", rules) == "blog"


# ================================================================================================ signatures
def test_signature_round_trip_and_failures():
    body, secret, now = b'{"type":"page_view"}', "whsec_test", 1_760_000_000
    headers = {k.lower(): v for k, v in signing.signed_headers(secret, body, now).items()}
    signing.verify(secret, headers, body, now=now)                                     # valid
    signing.verify(secret, headers, body, now=now + signing.TOLERANCE)                 # edge of the window
    cases = [
        ({}, body, now, "missing"),
        ({**headers, "x-leadpilot-timestamp": "soon"}, body, now, "unix seconds"),
        (headers, body, now + signing.TOLERANCE + 1, "timestamp"),
        (headers, body + b" ", now, "does not match"),
        ({**headers, "x-leadpilot-signature": "v0=" + headers["x-leadpilot-signature"][3:]}, body, now, "does not match"),
    ]
    for hdrs, b, t, reason in cases:
        with pytest.raises(signing.SignatureError, match=reason) as exc:
            signing.verify(secret, hdrs, b, now=t)
        assert exc.value.status == 401
    # several signatures while rotating: any match is enough
    rotating = {**headers, "x-leadpilot-signature": "v1=deadbeef, " + headers["x-leadpilot-signature"]}
    signing.verify(secret, rotating, body, now=now)


def test_replay_guard_rejects_the_same_signed_request():
    guard, body, now = signing.ReplayGuard(), b"{}", 1_760_000_000
    headers = {k.lower(): v for k, v in signing.signed_headers("s", body, now).items()}
    signing.verify("s", headers, body, guard, now=now)
    with pytest.raises(signing.SignatureError) as exc:
        signing.verify("s", headers, body, guard, now=now + 1)
    assert exc.value.status == 409
    assert signing.token_matches("abc", "abc") and not signing.token_matches("abc", "abd")
    assert not signing.token_matches("abc", None)


# ================================================================================================ email
def test_strip_quoted_keeps_only_the_new_text():
    gmail = "Sounds good, Tuesday works.\n\nOn Mon, Oct 12, 2026 at 9:00 AM Rita <rita@lp.io>\nwrote:\n> Old text"
    assert strip_quoted(gmail) == "Sounds good, Tuesday works."
    outlook = "Please send pricing.\n\nFrom: Rita\nSent: Monday\nTo: Ann\nSubject: Hello\n\nOld"
    assert strip_quoted(outlook) == "Please send pricing."
    assert strip_quoted("Yes.\n-- \nAnn Lee\nCEO") == "Yes."
    assert strip_quoted("Hi\n> quoted\nThanks\nSent from my iPhone") == "Hi\nThanks"


def test_email_reply_bounce_and_auto_reply():
    reply = email_event({"From": "Ann Lee <Ann@Acme.io>", "Subject": "Re: demo", "MessageID": "<m1@acme.io>",
                         "TextBody": "Yes please.\n\nOn Mon, Rita <r@lp.io> wrote:\n> hi"})
    ev = reply["event"]
    assert reply["kind"] == "reply" and ev["type"] == "email_replied" and ev["lead_ref"] == {"email": "ann@acme.io"}
    assert ev["payload"]["body"] == "Yes please." and "auto_reply" not in ev["payload"]
    assert ev["event_id"] == email_event({"MessageID": "<m1@acme.io>", "From": "x@y.io"})["event"]["event_id"]

    bounce = email_event({"from": "MAILER-DAEMON@mx.lp.io", "subject": "Undelivered Mail Returned to Sender",
                          "to": "rita@lp.io", "text": "Final-Recipient: rfc822; gone@acme.io\nStatus: 5.1.1\n"
                                                      "Diagnostic-Code: smtp; 550 5.1.1 user unknown"})
    assert bounce["kind"] == "bounce" and bounce["event"]["type"] == "email_bounced"
    assert bounce["event"]["lead_ref"] == {"email": "gone@acme.io"}
    assert bounce["event"]["payload"] == {"reason": "smtp; 550 5.1.1 user unknown", "bounce_type": "hard"}
    assert not email_event({"from": "postmaster@mx.io", "subject": "Undeliverable", "text": "no address"})["ok"]

    ooo = email_event({"from": "ann@acme.io", "subject": "Automatic reply: Re: demo", "text": "I am away"})
    assert ooo["event"]["payload"]["auto_reply"] is True
    by_header = email_event({"from": "ann@acme.io", "subject": "Re: demo", "text": "Away",
                             "headers": "Auto-Submitted: auto-replied\nX-Other: 1"})
    assert by_header["event"]["payload"]["auto_reply"] is True
    assert email_event({"subject": "hi", "text": "x"}) == {"ok": False, "kind": "reply", "error": "no sender address"}


def test_auto_replies_never_count_as_real_replies(cfg):
    body = "Yes, let's book a demo next week."
    assert reply_class({"body": body, "auto_reply": True}, cfg) == "out_of_office"
    assert reply_class({"body": body}, cfg) != "out_of_office"


# ================================================================================================ CSV
CSV = ("Email Address,First Name,Last Name,Company Name,Lead Source,Create Date\n"
       "ann@csv.io,Ann,Lee,Acme,Referral,2020-01-05\n"
       "bob@csv.io,Bob,Ray,Beta,,2099-01-01\n"
       "ANN@csv.io,Ann,Again,Acme,,\n"
       ",No,Contact,Gamma,,\n")
NOW = datetime(2026, 10, 10, tzinfo=UTC)


def test_csv_mapping_dedupes_and_loads_history():
    plan = map_rows(CSV, source="csv_import", now=NOW)
    assert plan["counts"] == {"rows": 4, "ok": 2, "skipped": 2}
    assert plan["columns"]["Email Address"] == "email" and plan["columns"]["Create Date"] == "created_at"
    ok = [r for r in plan["rows"] if r["ok"]]
    assert [r["email"] for r in ok] == ["ann@csv.io", "bob@csv.io"]
    assert ok[0]["source"] == "referral" and ok[0]["created_at"].startswith("2020-01-05")
    assert ok[1]["created_at"] is None                                           # future date = typo
    errors = {r["line"]: r["error"] for r in plan["rows"] if not r["ok"]}
    assert "same person" in errors[4] and "no email" in errors[5]
    ann, bob = plan["events"]
    assert ann["import"] is True and "import" not in bob
    assert ann["event_id"] == f"imp_{plan['batch_id']}_00002"
    assert map_rows(CSV, source="csv_import", now=NOW)["batch_id"] == plan["batch_id"]          # stable ids
    assert map_rows(CSV, source="other", now=NOW)["batch_id"] != plan["batch_id"]
    ignored = map_rows(CSV, source="csv_import", column_map={"Company Name": ""}, use_record_source=False, now=NOW)
    assert ignored["rows"][0]["company"] is None and ignored["rows"][0]["source"] == "csv_import"


def test_csv_semicolons_and_bad_files():
    plan = map_rows("email;name\nx@semi.io;Xi\n", source="s", now=NOW)
    assert plan["counts"]["ok"] == 1 and plan["rows"][0]["name"] == "Xi"
    for text, msg in (("", "empty"), ("name,company\nA,B\n", "no email or phone")):
        with pytest.raises(CsvImportError, match=msg):
            map_rows(text, source="s", now=NOW)
    with pytest.raises(CsvImportError, match="capture_method"):
        map_rows(CSV, source="s", capture_method="telepathy", now=NOW)


# ================================================================================================ through the API
SECRET = "test-only-secret-not-used-anywhere-else-0123456789"
SUPA = "https://test-project.supabase.co"
ENV = {"LEADPILOT_MODE": "demo", "LEADPILOT_PERSIST": "0", "LEADPILOT_WARMUP_DAYS": "2", "LEADPILOT_AUTH": "on",
       "SUPABASE_URL": SUPA, "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_ANON_KEY": "sb_publishable_test",
       "LEADPILOT_ADMIN_EMAILS": "boss@test.dev"}
USERS = {name: str(uuid.uuid4()) for name in ("boss", "max", "rita")}
RUN = uuid.uuid4().hex[:6]                      # unique emails per run


def h(name: str) -> dict:
    now = datetime.now(UTC)
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
            assert c.patch(f"/api/admin/users/{USERS['max']}", headers=h("boss"),
                           json={"role": "manager", "team_rep_ids": ["R-ANANYA"]}).status_code == 200
            assert c.patch(f"/api/admin/users/{USERS['rita']}", headers=h("boss"),
                           json={"role": "rep", "rep_id": "R-ANANYA"}).status_code == 200
            yield c
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def make(client, kind: str, name: str, **extra) -> dict:
    r = client.post("/api/connectors", headers=h("boss"), json={"kind": kind, "name": name, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def signed_post(client, con: dict, payload, secret: str | None = None, ts: int | None = None):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", **signing.signed_headers(secret or con["secret"], body, ts)}
    return client.post(f"/api/hooks/{con['id']}", content=body, headers=headers)


def timeline_types(client, lead_id: str) -> list[dict]:
    r = client.get(f"/api/leads/{lead_id}/timeline", headers=h("boss"))
    assert r.status_code == 200
    return [i for i in r.json()["items"] if i["kind"] == "event"]


def test_connectors_are_admin_only(client):
    assert client.get("/api/connectors").status_code == 401
    for who in ("max", "rita"):
        assert client.get("/api/connectors", headers=h(who)).status_code == 403
        assert client.post("/api/connectors", headers=h(who), json={"kind": "webhook", "name": "x"}).status_code == 403
    listing = client.get("/api/connectors", headers=h("boss")).json()
    assert listing["kinds"] == ["webhook", "form", "crm", "email", "tracker", "call"]
    for body, msg in (({"kind": "fax", "name": "x"}, "kind"), ({"kind": "webhook", "name": " "}, "name"),
                      ({"kind": "form", "name": "f", "settings": {"form_kind": "psychic"}}, "form_kind"),
                      ({"kind": "tracker", "name": "t", "settings": {"page_rules": [{"pattern": "("}]}}, "page rule")):
        r = client.post("/api/connectors", headers=h("boss"), json=body)
        assert r.status_code == 422 and msg in r.json()["detail"]


def test_signed_webhook(client):
    con = make(client, "webhook", "Backend events", source="partner_api")
    assert con["secret"].startswith("whsec_") and con["endpoint"] == f"/api/hooks/{con['id']}"
    listed = next(c for c in client.get("/api/connectors", headers=h("boss")).json()["items"] if c["id"] == con["id"])
    assert "secret" not in listed and listed["secret_hint"].endswith("…") and listed["status"] == "active"

    email = f"hook-{RUN}@acme.io"
    batch = {"events": [
        {"event_id": f"ext-{RUN}-1", "type": "lead_created", "payload": {"name": "Hook Lead", "email": email,
                                                                           "company": "Acme"}},
        {"event_id": f"ext-{RUN}-2", "type": "page_view", "lead_ref": {"email": email},
         "payload": {"page_category": "pricing", "url": "/pricing"}},
    ]}
    r = signed_post(client, con, batch)
    assert r.status_code == 200 and r.json()["status"] == "accepted", r.text
    results = r.json()["results"]
    lead_id = results[0]["lead_id"]
    assert lead_id and results[1]["lead_id"] == lead_id
    events = timeline_types(client, lead_id)
    assert {e["type"] for e in events} >= {"lead_created", "page_view"}
    assert next(e for e in events if e["type"] == "lead_created")["source"] == "partner_api"

    # the very same signed request again: replay; same events freshly signed: idempotent duplicates
    body = json.dumps(batch).encode()
    headers = {"Content-Type": "application/json", **signing.signed_headers(con["secret"], body, int(time.time()) - 5)}
    assert client.post(f"/api/hooks/{con['id']}", content=body, headers=headers).status_code == 200
    replay = client.post(f"/api/hooks/{con['id']}", content=body, headers=headers)
    assert replay.status_code == 409 and "replay" in replay.json()["detail"]
    assert signed_post(client, con, batch, ts=int(time.time()) + 3).json()["status"] == "duplicate"

    unsigned = client.post(f"/api/hooks/{con['id']}", json=batch)
    assert unsigned.status_code == 401 and "signed" in unsigned.json()["detail"]
    assert client.post(f"/api/hooks/{con['id']}?token={con['secret']}", json=batch).status_code == 401
    assert signed_post(client, con, batch, ts=int(time.time()) - 3600).status_code == 401
    assert signed_post(client, con, batch, secret="whsec_wrong").status_code == 401
    blocked = signed_post(client, con, {"type": "time_tick"})
    assert blocked.status_code == 422 and "written by LeadPilot" in blocked.json()["detail"]
    assert signed_post(client, con, [{"payload": {}}]).status_code == 422
    assert client.post("/api/hooks/con_nope", json={}).status_code == 404

    log = client.get(f"/api/connectors/{con['id']}/deliveries", headers=h("boss")).json()["items"]
    assert log[0]["status"] == "rejected" and log[0]["http_status"] == 422
    assert {d["http_status"] for d in log} >= {200, 401, 409, 422}
    assert any(d["status"] == "accepted" and d["events"] == 2 for d in log)


def test_form_connector_with_url_token(client):
    con = make(client, "form", "Website demo form")
    assert con["source"] == "website" and con["settings"]["allow_token"] is True
    email = f"form-{RUN}@formco.io"
    body = f"email={email}&first_name=Fay&last_name=Orm&company=FormCo&form_type=Book+a+demo&password=hunter2"
    url = f"/api/hooks/{con['id']}?token={con['secret']}"
    r = client.post(url, content=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["type"] for x in results] == ["lead_created", "demo_request"]
    assert all(x["status"] == "processed" for x in results)
    created = next(e for e in timeline_types(client, results[0]["lead_id"]) if e["type"] == "lead_created")
    assert created["payload"]["name"] == "Fay Orm" and created["payload"]["company"] == "FormCo"
    assert "password" not in created["payload"]
    # the same submission posted twice (form tools retry) is a duplicate, not a second lead
    again = client.post(url, content=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert again.json()["status"] == "duplicate"
    bad = client.post(f"/api/hooks/{con['id']}?token=wrong", json={"email": "x@y.io"})
    assert bad.status_code == 401 and "token" in bad.json()["detail"]
    via_header = client.post(f"/api/hooks/{con['id']}", json={"phone": "+1 555 0199", "name": "Header Tok"},
                             headers={"X-LeadPilot-Token": con["secret"]})
    assert via_header.json()["status"] == "accepted"
    no_contact = client.post(url, json={"name": "Nobody"})
    assert no_contact.json()["status"] == "rejected" and "no email" in no_contact.json()["results"][0]["reason"]


def test_crm_connector_maps_hubspot_records(client):
    con = make(client, "crm", "HubSpot", settings={"field_map": {"jobtitle": "title"}})
    email = f"crm-{RUN}@hub.io"
    record = {"vid": f"hs-{RUN}", "properties": {
        "email": {"value": email}, "firstname": {"value": "Hu"}, "lastname": {"value": "Bert"},
        "company": {"value": "HubCo"}, "jobtitle": {"value": "VP Sales"},
        "hs_analytics_source": {"value": "ORGANIC_SEARCH"}}}
    r = signed_post(client, con, {"records": [record, {"properties": {"firstname": {"value": "No contact"}}}]})
    assert r.status_code == 200 and r.json()["status"] == "partial", r.text
    results = r.json()["results"]
    assert results[0]["status"] == "processed" and results[-1]["status"] == "rejected"
    created = next(e for e in timeline_types(client, results[0]["lead_id"]) if e["type"] == "lead_created")
    assert created["source"] == "organic_search"
    assert created["payload"]["title"] == "VP Sales" and created["payload"]["name"] == "Hu Bert"
    record["properties"]["company"] = {"value": "HubCo (renamed)"}      # same record id: still a duplicate
    assert signed_post(client, con, record).json()["status"] == "duplicate"
    assert signed_post(client, con, {"records": [{}] * 501}).status_code == 413


def test_email_connector_replies_bounces_and_unknown_senders(client):
    form = make(client, "form", "Mail test form")
    email = f"mail-{RUN}@acme.io"
    created = client.post(f"/api/hooks/{form['id']}?token={form['secret']}", json={"email": email, "name": "Mae"})
    lead_id = created.json()["results"][0]["lead_id"]

    con = make(client, "email", "Inbound replies")
    url = f"/api/hooks/{con['id']}?token={con['secret']}"
    reply = client.post(url, json={"From": f"Mae <{email}>", "Subject": "Re: LeadPilot", "MessageID": f"<{RUN}@acme>",
                                   "TextBody": "Can we see pricing?\n\nOn Mon, Rita <r@lp.io> wrote:\n> hello"})
    assert reply.status_code == 200 and reply.json()["status"] == "accepted", reply.text
    assert reply.json()["results"][0]["lead_id"] == lead_id
    ev = next(e for e in timeline_types(client, lead_id) if e["type"] == "email_replied")
    assert ev["payload"]["body"] == "Can we see pricing?" and ev["actor"] == "prospect"

    ooo = client.post(url, json={"from": email, "subject": "Out of office", "text": "Back Monday"})
    assert ooo.json()["status"] == "accepted"
    assert any(e["payload"].get("auto_reply") for e in timeline_types(client, lead_id) if e["type"] == "email_replied")

    bounce = client.post(url, data={"from": "MAILER-DAEMON@mx.lp.io", "subject": "Undelivered Mail Returned to Sender",
                                    "to": "rita@lp.io", "text": f"Final-Recipient: rfc822; {email}\nStatus: 4.2.2\n"},
                         files={"attachment1": ("report.txt", b"delivery report", "text/plain")})
    assert bounce.status_code == 200 and bounce.json()["status"] == "accepted", bounce.text
    ev = next(e for e in timeline_types(client, lead_id) if e["type"] == "email_bounced")
    assert ev["payload"]["bounce_type"] == "soft"

    stranger = client.post(url, json={"from": f"nobody-{RUN}@nowhere.io", "subject": "hi", "text": "who is this"})
    assert stranger.json()["status"] == "unresolved"
    assert client.post(url, json={"subject": "no sender"}).status_code == 422
    assert client.post(url, json=["not", "an", "object"]).status_code == 422


def test_tracker_stitches_anonymous_visits_to_the_lead(client):
    con = make(client, "tracker", "Marketing site", settings={"allowed_origins": "https://www.example.com, example.org",
                                                              "page_rules": [{"pattern": "^/book", "category": "pricing"}]})
    key = con["site_key"]
    assert key.startswith("lpk_") and con["settings"]["allowed_origins"] == ["example.org", "www.example.com"]
    script = client.get("/api/t.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert "window.leadpilot" in script.text

    vid = f"visitor{RUN}abc"
    site = {"Origin": "https://www.example.com", "Content-Type": "text/plain"}

    def send(data, headers=site):
        return client.post(f"/api/track/{key}", content=json.dumps(data), headers=headers)

    for path in ("/", "/pricing", "/book-a-call"):
        assert send({"v": 1, "type": "page_view", "vid": vid, "path": path, "url": f"https://www.example.com{path}"}) \
            .status_code == 204
    stats = next(c for c in client.get("/api/connectors", headers=h("boss")).json()["items"] if c["id"] == con["id"])
    assert stats["stats"] == {"visitors": 1, "identified": 0, "page_views": 3}

    email = f"visitor-{RUN}@example.com"
    assert send({"type": "identify", "vid": vid, "form_name": "Book a demo",
                 "fields": {"your-email": email, "your-name": "Vic Itor", "card_number": "4111"}}).status_code == 204
    assert send({"type": "page_view", "vid": vid, "path": "/enterprise"}).status_code == 204       # now known

    log = client.get(f"/api/connectors/{con['id']}/deliveries", headers=h("boss")).json()["items"]
    lead_id = next(r["lead_id"] for r in log[0]["results"] if r["type"] == "lead_created")
    assert json.loads(log[0]["sample"])["page_views_linked"] == 3
    events = timeline_types(client, lead_id)
    views = [e["payload"]["page_category"] for e in events if e["type"] == "page_view"]
    assert sorted(views) == ["enterprise_plan", "home", "pricing", "pricing"]
    assert any(e["type"] == "demo_request" for e in events)
    created = next(e for e in events if e["type"] == "lead_created")
    assert "card_number" not in created["payload"] and created["payload"]["name"] == "Vic Itor"

    assert send({"type": "page_view", "vid": vid}, {"Origin": "https://evil.io"}).status_code == 403
    assert send({"type": "page_view", "vid": vid}, {"Referer": "https://shop.example.org/x"}).status_code == 204
    assert send({"type": "page_view", "vid": "x"}).status_code == 400
    assert send({"type": "bogus", "vid": vid}).status_code == 400
    bot = send({"type": "page_view", "vid": "botvisitor123"}, {**site, "User-Agent": "Googlebot/2.1"})
    assert bot.status_code == 204
    assert client.post("/api/track/lpk_unknown", content="{}").status_code == 404
    final = next(c for c in client.get("/api/connectors", headers=h("boss")).json()["items"] if c["id"] == con["id"])
    assert final["stats"]["visitors"] == 1 and final["stats"]["identified"] == 1


def test_csv_import_preview_and_commit(client):
    csv_text = CSV.replace("@csv.io", f"-{RUN}@csv.io").replace("@CSV.io", f"-{RUN}@csv.io")
    assert client.post("/api/import/preview", headers=h("rita"), json={"csv": csv_text}).status_code == 403
    preview = client.post("/api/import/preview", headers=h("max"), json={"csv": csv_text, "source": "Trade Show"})
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["counts"] == {"rows": 4, "ok": 2, "skipped": 2} and p["events"] == 2
    assert len(p["sample"]) == 2 and len(p["errors"]) == 2 and "rows" not in p

    commit = client.post("/api/import/commit", headers=h("max"), json={"csv": csv_text, "source": "Trade Show"})
    assert commit.status_code == 200 and commit.json()["leads"] == {"processed": 2}, commit.text
    assert commit.json()["batch_id"] == p["batch_id"] and len(commit.json()["lead_ids"]) == 2
    again = client.post("/api/import/commit", headers=h("max"), json={"csv": csv_text, "source": "Trade Show"})
    assert again.json()["leads"] == {"duplicate": 2}

    lead_id = commit.json()["lead_ids"][0]
    sources = {e["source"] for e in timeline_types(client, lead_id) if e["type"] == "lead_created"}
    assert sources <= {"referral", "trade_show"}
    for body, msg in (({"csv": "name\nA\n"}, "no email"), ({}, "csv"),
                      ({"csv": csv_text, "column_map": {"Email Address": "shoe_size"}}, "column_map")):
        r = client.post("/api/import/preview", headers=h("max"), json=body)
        assert r.status_code == 422 and msg in r.json()["detail"]


def test_rotate_and_disable(client):
    con = make(client, "webhook", "Rotating")
    old = con["secret"]
    ok = {"type": "lead_created", "payload": {"email": f"rot-{RUN}@r.io"}}
    assert signed_post(client, con, ok).status_code == 200
    rotated = client.post(f"/api/connectors/{con['id']}/rotate", headers=h("boss")).json()
    assert rotated["secret"] != old
    assert signed_post(client, con, ok, secret=old).status_code == 401
    assert signed_post(client, rotated, ok).status_code == 200
    revealed = client.post(f"/api/connectors/{con['id']}/reveal", headers=h("boss")).json()
    assert revealed["secret"] == rotated["secret"]
    renamed = client.patch(f"/api/connectors/{con['id']}", headers=h("boss"), json={"name": "Renamed", "source": ""})
    assert renamed.json()["name"] == "Renamed" and renamed.json()["source"] is None
    disabled = client.delete(f"/api/connectors/{con['id']}", headers=h("boss")).json()
    assert disabled["status"] == "disabled"
    assert signed_post(client, rotated, ok).status_code == 410
    assert client.post(f"/api/connectors/con_missing/rotate", headers=h("boss")).status_code == 404
