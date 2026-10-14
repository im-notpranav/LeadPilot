"""Authentication, roles and per-role scope through the real FastAPI app (auth on, in memory, test-signed tokens)."""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth import Principal, TokenVerifier

SECRET = "test-only-secret-not-used-anywhere-else-0123456789"
SUPA = "https://test-project.supabase.co"
ENV = {"LEADPILOT_MODE": "demo", "LEADPILOT_PERSIST": "0", "LEADPILOT_WARMUP_DAYS": "2", "LEADPILOT_AUTH": "on",
       "SUPABASE_URL": SUPA, "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_ANON_KEY": "sb_publishable_test",
       "LEADPILOT_ADMIN_EMAILS": "boss@test.dev"}
USERS = {name: str(uuid.uuid4()) for name in ("boss", "rita", "max", "newbie")}


def token(name: str, *, secret: str = SECRET, exp_minutes: int = 60, email: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": USERS[name], "email": email or f"{name}@test.dev", "aud": "authenticated",
                       "iss": f"{SUPA}/auth/v1", "role": "authenticated", "iat": now,
                       "exp": now + timedelta(minutes=exp_minutes)}, secret, algorithm="HS256")


def h(name: str) -> dict:
    return {"Authorization": f"Bearer {token(name)}"}


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
            yield c
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture(scope="module")
def roles(client):
    """boss = admin (bootstrap email), rita = rep for R-ANANYA, max = manager of two reps, newbie = pending."""
    for name in USERS:
        assert client.get("/api/me", headers=h(name)).status_code == 200      # first sign-in creates the profile
    r = client.patch(f"/api/admin/users/{USERS['rita']}", headers=h("boss"), json={"role": "rep", "rep_id": "R-ANANYA"})
    assert r.status_code == 200 and r.json()["rep_id"] == "R-ANANYA"
    team = ["R-ANANYA", "R-MARCUS"]
    r = client.patch(f"/api/admin/users/{USERS['max']}", headers=h("boss"), json={"role": "manager", "team_rep_ids": team})
    assert r.status_code == 200 and r.json()["team_rep_ids"] == team
    return team


def test_public_endpoints_need_no_login(client):
    assert client.get("/api/health").json()["auth"] is True
    cfg = client.get("/api/auth/config").json()
    assert cfg == {"enabled": True, "supabase_url": SUPA, "anon_key": "sb_publishable_test", "login_ready": True}


@pytest.mark.parametrize("headers,detail", [
    ({}, "sign in required"),
    ({"Authorization": "Bearer not-a-jwt"}, "invalid session"),
    ({"Authorization": f"Bearer {token('boss', secret='wrong-secret-wrong-secret-wrong-secret-x')}"}, "invalid session"),
    ({"Authorization": f"Bearer {token('boss', exp_minutes=-5)}"}, "invalid session"),
    ({"X-API-Key": "lp_made_up_key"}, "invalid or revoked API key"),
])
def test_bad_credentials_are_rejected(client, headers, detail):
    r = client.get("/api/leads", headers=headers)
    assert r.status_code == 401 and detail in r.json()["detail"]


def test_new_sign_up_is_pending_and_bootstrap_email_is_admin(client, roles):
    me = client.get("/api/me", headers=h("newbie")).json()
    assert me["role"] == "pending" and me["email"] == "newbie@test.dev"
    r = client.get("/api/leads", headers=h("newbie"))
    assert r.status_code == 403 and "waiting for an admin" in r.json()["detail"]
    assert client.get("/api/me", headers=h("boss")).json()["role"] == "admin"
    users = client.get("/api/admin/users", headers=h("boss")).json()
    assert users["admin_emails"] == ["boss@test.dev"] and len(users["items"]) == 4
    assert client.get("/api/admin/users", headers=h("max")).status_code == 403


def test_rep_sees_only_their_own_leads(client, roles):
    all_leads = client.get("/api/leads", headers=h("boss"), params={"limit": 1000}).json()["items"]
    mine = client.get("/api/leads", headers=h("rita"), params={"limit": 1000}).json()["items"]
    assert mine and {l["owner_rep_id"] for l in mine} == {"R-ANANYA"}
    assert len(mine) < len(all_leads)
    other = next(l for l in all_leads if l["owner_rep_id"] not in (None, "R-ANANYA"))
    for path in (f"/api/leads/{other['lead_id']}", f"/api/leads/{other['lead_id']}/timeline",
                 f"/api/leads/{other['lead_id']}/score-history"):
        assert client.get(path, headers=h("rita")).status_code == 404          # existence not revealed
    assert client.get(f"/api/leads/{mine[0]['lead_id']}", headers=h("rita")).status_code == 200
    q = client.get("/api/queue/all", headers=h("rita")).json()                # "all" is narrowed to her own
    assert q["rep_id"] == "R-ANANYA" and {i["owner_rep_id"] for i in q["items"]} <= {"R-ANANYA"}
    cards = [c for col in client.get("/api/pipeline", headers=h("rita")).json()["columns"] for c in col["cards"]]
    assert {c["owner_rep_id"] for c in cards} == {"R-ANANYA"}
    assert [r["rep_id"] for r in client.get("/api/reps", headers=h("rita")).json()["items"]] == ["R-ANANYA"]
    feed = client.get("/api/feed", headers=h("rita"), params={"limit": 400}).json()["items"]
    assert all(client.get(f"/api/leads/{i['lead_id']}", headers=h("rita")).status_code == 200 for i in feed[:10])
    for method, path in (("GET", "/api/analytics/funnel"), ("GET", "/api/quality/review-queue"),
                         ("POST", "/api/sim/start"), ("POST", "/api/replay"), ("POST", "/api/events"),
                         ("GET", "/api/admin/api-keys")):
        assert client.request(method, path, headers=h("rita"), json={"type": "page_view"}).status_code == 403, path
    r = client.post(f"/api/leads/{other['lead_id']}/disqualify", headers=h("rita"), json={})
    assert r.status_code == 404


def test_manager_sees_their_team_and_unassigned(client, roles):
    leads = client.get("/api/leads", headers=h("max"), params={"limit": 1000}).json()["items"]
    assert leads and {l["owner_rep_id"] for l in leads} <= set(roles) | {None}
    assert client.get("/api/analytics/funnel", headers=h("max")).status_code == 200
    assert {r["rep_id"] for r in client.get("/api/reps", headers=h("max")).json()["items"]} == set(roles)
    r = client.post(f"/api/leads/{leads[0]['lead_id']}/assign", headers=h("max"), json={"rep_id": "R-VICTOR"})
    assert r.status_code == 403 and "your team" in r.json()["detail"]
    assert client.get("/api/queue/R-VICTOR", headers=h("max")).status_code == 403


def test_api_keys_ingest_only_and_can_be_revoked(client, roles):
    created = client.post("/api/admin/api-keys", headers=h("boss"), json={"name": "Website forms"}).json()
    secret = created["secret"]
    assert secret.startswith("lp_") and created["prefix"] == secret[:10] and "key_hash" not in created
    listed = client.get("/api/admin/api-keys", headers=h("boss")).json()["items"]
    assert [k["id"] for k in listed] == [created["id"]] and "secret" not in listed[0]
    lead = client.get("/api/leads", headers=h("boss"), params={"limit": 1}).json()["items"][0]
    body = {"type": "page_view", "lead_ref": {"lead_id": lead["lead_id"]}, "payload": {"page_category": "pricing"}}
    r = client.post("/api/events", headers={"X-API-Key": secret}, json=body)
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "processed"
    from app.api.deps import state
    assert state.runtime.store.raw_log[-1]["ingested_via"] == f"key:{created['id']}"
    assert client.post("/api/events", headers={"Authorization": f"Bearer {secret}"}, json=body).status_code == 200
    assert client.get("/api/leads", headers={"X-API-Key": secret}).status_code == 403      # ingest only
    assert client.delete(f"/api/admin/api-keys/{created['id']}", headers=h("boss")).json()["revoked_at"]
    assert client.post("/api/events", headers={"X-API-Key": secret}, json=body).status_code == 401


def test_admin_rules(client, roles):
    r = client.patch(f"/api/admin/users/{USERS['boss']}", headers=h("boss"), json={"role": "rep"})
    assert r.status_code == 409
    assert client.patch(f"/api/admin/users/{USERS['rita']}", headers=h("boss"), json={"role": "owner"}).status_code == 422
    assert client.patch(f"/api/admin/users/{USERS['rita']}", headers=h("boss"),
                        json={"rep_id": "R-NOBODY"}).status_code == 422


def test_every_private_route_rejects_anonymous_and_pending(client, roles):
    public = {"/api/health", "/api/auth/config",
              "/api/hooks/{cid}", "/api/track/{key}"}        # connectors: authenticated by their own secret
    checked = 0
    for route_path, ops in client.get("/openapi.json").json()["paths"].items():   # every HTTP endpoint
        if route_path in public:
            continue
        path = route_path.replace("{", "").replace("}", "")      # any placeholder value: auth runs first
        for method in ops:
            assert client.request(method, path, json={}).status_code == 401, (method, route_path)
            if route_path != "/api/me":
                assert client.request(method, path, headers=h("newbie"), json={}).status_code == 403, route_path
            checked += 1
    assert checked > 30


def test_websocket_needs_a_token_and_filters_by_scope(client, roles):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
    assert exc.value.code == 4401
    with client.websocket_connect(f"/ws?token={token('rita')}") as ws:
        assert "sim.clock" in ws.receive_text()
    from app.api.deps import state
    from app.api.ws import visible
    rita = Principal(kind="user", role="rep", rep_id="R-ANANYA")
    leads = list(state.runtime.store.leads.values())
    mine = next(l for l in leads if l.owner == "R-ANANYA")
    theirs = next(l for l in leads if l.owner not in (None, "R-ANANYA"))
    assert visible(rita, {"type": "score.changed", "data": {"lead_id": mine.lead_id}})
    assert not visible(rita, {"type": "score.changed", "data": {"lead_id": theirs.lead_id}})
    assert visible(rita, {"type": "sim.clock", "data": {}})
    assert not visible(rita, {"type": "source.flagged", "data": {"source_id": "x"}})


def test_es256_tokens_verify_against_the_project_jwks():
    """New Supabase projects sign with ES256 and publish the public key; no secret is needed."""
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True) | {"kid": "k1", "alg": "ES256", "use": "sig"}
    v = TokenVerifier(SUPA)
    v.jwks.fetch_data = lambda: {"keys": [jwk]}
    now = datetime.now(timezone.utc)
    claims = {"sub": "u-1", "email": "a@test.dev", "aud": "authenticated", "iss": f"{SUPA}/auth/v1",
              "exp": now + timedelta(minutes=5)}
    good = jwt.encode(claims, key, algorithm="ES256", headers={"kid": "k1"})
    assert v.verify(good)["sub"] == "u-1"
    other = ec.generate_private_key(ec.SECP256R1())
    forged = jwt.encode(claims, other, algorithm="ES256", headers={"kid": "k1"})
    with pytest.raises(Exception, match="Signature verification failed"):
        v.verify(forged)
    wrong_iss = jwt.encode({**claims, "iss": "https://evil.example/auth/v1"}, key, algorithm="ES256", headers={"kid": "k1"})
    with pytest.raises(Exception, match="issuer"):
        v.verify(wrong_iss)


def test_accounts_survive_demo_resets_and_replays(tmp_path):
    from app.auth import AccountStore
    from app.persistence import Persistence
    db = Persistence(f"sqlite:///{tmp_path / 'acc.db'}")
    accounts = AccountStore(db, frozenset({"boss@test.dev"}))
    accounts.ensure_profile("u-boss", "Boss@Test.dev")
    _, secret = accounts.create_key("CRM sync", "boss@test.dev")
    db.reset()                          # what a demo-mode start does
    db.clear_projections()              # what /api/replay does
    reloaded = AccountStore(db, frozenset({"boss@test.dev"}))
    assert reloaded.profiles["u-boss"]["role"] == "admin" and reloaded.profiles["u-boss"]["email"] == "boss@test.dev"
    assert reloaded.verify_key(secret)["name"] == "CRM sync"
