"""Settings versions: shape checks, overrides and diffs, the dry run, storage, the engine switch, and the API."""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.config import load_config
from app.config_versions import ConfigError, ConfigStore, check_shape, diff, dry_run, to_yaml
from app.persistence import NullPersistence, Persistence
from app.runtime import Runtime

FAST = {"simulator": {"warmup_days": 2}}


def edited(cs: ConfigStore, change) -> dict[str, str]:
    """Every section as YAML text after `change(effective)` (what the settings page sends)."""
    eff = cs.effective(cs.active()["overrides"])
    change(eff)
    return {k: to_yaml(v) for k, v in eff.items()}


# ================================================================================================ pure helpers
def test_shape_check_names_every_problem():
    default = {"grades": {"A": 80, "B": 60}, "on": True, "label": "x", "list": [1, 2], "rules": [{"id": "N1"}]}
    errors: list[str] = []
    check_shape({"grades": {"A": "high", "C": 40}, "on": 1, "label": "x", "list": [1, "two"], "rules": ["N1"]},
                default, "scoring", errors)
    text_ = "\n".join(errors)
    assert "scoring.grades.B: is missing" in text_
    assert "scoring.grades.C: is not a known setting" in text_
    assert "scoring.grades.A: must be a number, not text" in text_
    assert "scoring.on: must be true or false, not a number" in text_
    assert "scoring.list[1]: must be a number, not text" in text_
    assert "scoring.rules[0]: must be a group of settings, not text" in text_
    ok: list[str] = []
    check_shape({"grades": {"A": 75.5, "B": 60}, "on": False, "label": "y", "list": [], "rules": [{"id": "N9"}]},
                default, "scoring", ok)
    assert ok == []


def test_overrides_keep_only_what_changed_and_diff_lists_it():
    cs = ConfigStore(NullPersistence())
    cs.ensure_initial()
    overrides, cfg = cs.validate(edited(cs, lambda e: e["scoring"]["grades"].update(A=75)))
    assert overrides == {"scoring": {"grades": {"A": 75}}}
    assert cfg.scoring.grades.A == 75 and cfg.scoring.grades.B == 60
    assert cfg.fingerprint != load_config().fingerprint
    assert diff(cs.effective({}), cs.effective(overrides)) == [{"path": "scoring.grades.A", "before": 80, "after": 75}]
    same, _ = cs.validate(edited(cs, lambda e: None))           # dumping and parsing YAML changes nothing
    assert same == {}


def test_invalid_yaml_and_bad_values_are_refused_with_reasons():
    cs = ConfigStore(NullPersistence())
    cs.ensure_initial()
    with pytest.raises(ConfigError, match="not valid YAML at line"):
        cs.validate({"scoring": "grades:\n  A: [80\n"})
    with pytest.raises(ConfigError, match="expected a list of settings"):
        cs.validate({"scoring": "- just a list"})
    with pytest.raises(ConfigError, match="is not an editable section"):
        cs.validate({"simulator": "seed: 1"})
    with pytest.raises(ConfigError, match="scoring.grades.A: must be a number"):
        cs.validate(edited(cs, lambda e: e["scoring"]["grades"].update(A="eighty")))


def test_dry_run_catches_rules_that_break_processing():
    cs = ConfigStore(NullPersistence())
    cs.ensure_initial()
    _, good = cs.validate(edited(cs, lambda e: e["scoring"]["grades"].update(A=70)))
    assert dry_run(good, [], []) == 8                             # the built-in sample journey
    _, broken = cs.validate(edited(cs, lambda e: e["pipeline"].update(forward_order=[])))
    with pytest.raises(ConfigError, match="fail when processing events"):
        dry_run(broken, [], [])


# ================================================================================================ storage
def test_versions_survive_a_restart_and_a_demo_reset(tmp_path):
    url = f"sqlite:///{tmp_path / 'cfg.db'}"
    db = Persistence(url)
    cs = ConfigStore(db)
    assert cs.ensure_initial()["id"] == 1
    overrides, cfg = cs.validate(edited(cs, lambda e: e["assignment"]["reassignment"]["first_touch_sla_minutes"]
                                        .update(A=30)))
    row = cs.create(overrides, "Faster first touch", "boss@test.dev", cfg.fingerprint)
    assert row["status"] == "draft"
    cs.mark_active(row["id"], "boss@test.dev")
    db.reset()                                                     # demo reset wipes projections only
    db.close()

    again = ConfigStore(Persistence(url))
    assert again.ensure_initial()["id"] == 2
    assert {v["id"]: v["status"] for v in again.versions.values()} == {1: "retired", 2: "active"}
    assert again.active()["overrides"] == {"assignment": {"reassignment": {"first_touch_sla_minutes": {"A": 30}}}}
    assert again.active()["note"] == "Faster first touch"
    assert again.build(again.active()["overrides"]).assignment.reassignment.first_touch_sla_minutes.A == 30


def test_an_older_sqlite_file_gets_the_new_columns(tmp_path):
    path = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE events (event_id VARCHAR PRIMARY KEY, type VARCHAR)"))
    eng.dispose()
    db = Persistence(f"sqlite:///{path}")
    with db.engine.connect() as conn:
        cols = {r[1] for r in conn.execute(text('PRAGMA table_info("events")'))}
    db.close()
    assert {"config_version", "lead_id", "ingested_at"} <= cols


# ================================================================================================ engine switch
def test_activating_a_version_rescores_everything_and_stamps_it():
    cs = ConfigStore(NullPersistence(), base_overrides=FAST)
    v1 = cs.ensure_initial()
    rt = Runtime(cs.build(v1["overrides"]))
    rt.apply_config(rt.cfg, v1["id"], replay=False)
    rt.reset(warmup=True)
    leads = [l for l in rt.store.leads.values() if l.ev is not None and l.status == "active"]
    assert all(r["config_version"] == 1 for l in leads for r in l.score_history)
    before = {l.lead_id: l.ev.score.grade for l in leads}

    overrides, cfg = cs.validate(edited(cs, lambda e: e["scoring"]["grades"].update(A=40, B=30, C=20)))
    row = cs.create(overrides, "Generous grades", "test", cfg.fingerprint)
    result = rt.apply_config(cfg, row["id"])
    assert result["replayed_events"] == len(rt.store.raw_log) > 0
    leads = {l.lead_id: l for l in rt.store.leads.values() if l.ev is not None and l.status == "active"}
    assert all(l.ev.score.grade == "A" for l in leads.values() if l.ev.score.score >= 40)
    assert sum(g != leads[i].ev.score.grade for i, g in before.items() if i in leads) > 0
    assert all(r["config_version"] == row["id"] for l in leads.values() for r in l.score_history)
    assert rt.stats()["config_version"] == row["id"] and rt.status == "ready"


# ================================================================================================ API
SECRET = "test-only-secret-not-used-anywhere-else-0123456789"
SUPA = "https://test-project.supabase.co"
ENV = {"LEADPILOT_MODE": "demo", "LEADPILOT_PERSIST": "0", "LEADPILOT_WARMUP_DAYS": "2", "LEADPILOT_AUTH": "on",
       "SUPABASE_URL": SUPA, "SUPABASE_JWT_SECRET": SECRET, "SUPABASE_ANON_KEY": "sb_publishable_test",
       "LEADPILOT_ADMIN_EMAILS": "boss@test.dev"}
USERS = {name: str(uuid.uuid4()) for name in ("boss", "max", "rita")}


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
            for name, body in (("max", {"role": "manager"}), ("rita", {"role": "rep", "rep_id": "R-ANANYA"})):
                assert c.patch(f"/api/admin/users/{USERS[name]}", headers=h("boss"), json=body).status_code == 200
            yield c
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def sections(c, change) -> dict[str, str]:
    cur = {s["name"]: yaml.safe_load(s["yaml"]) for s in c.get("/api/config", headers=h("boss")).json()["sections"]}
    change(cur)
    return {k: to_yaml(v) for k, v in cur.items()}


def test_settings_are_visible_to_managers_and_changeable_by_admins_only(client):
    cur = client.get("/api/config", headers=h("boss")).json()
    assert cur["active"]["id"] == 1 and cur["engine_version"] == 1 and cur["can_edit"] is True
    assert [s["name"] for s in cur["sections"]] == ["scoring", "pipeline", "assignment", "quality", "nba", "quotes"]
    assert "#" in cur["sections"][0]["file"]                       # the documented YAML file, comments included
    assert client.get("/api/config", headers=h("max")).json()["can_edit"] is False
    assert client.get("/api/config", headers=h("rita")).status_code == 403
    body = {"sections": sections(client, lambda s: s["scoring"]["grades"].update(A=70))}
    assert client.post("/api/config/check", headers=h("max"), json=body).status_code == 403
    assert client.post("/api/config/versions", headers=h("max"), json=body).status_code == 403


def test_check_explains_problems_and_lists_changes(client):
    bad = client.post("/api/config/check", headers=h("boss"), json={"sections": {"scoring": "grades: [\n"}})
    assert bad.status_code == 422 and "not valid YAML" in bad.json()["detail"]
    typo = client.post("/api/config/check", headers=h("boss"),
                       json={"sections": sections(client, lambda s: s["scoring"]["grades"].update(AA=1))})
    assert typo.status_code == 422 and "scoring.grades.AA: is not a known setting" in typo.json()["detail"]
    ok = client.post("/api/config/check", headers=h("boss"),
                     json={"sections": sections(client, lambda s: s["scoring"]["grades"].update(A=70))}).json()
    assert ok["ok"] and ok["events_checked"] > 8
    assert ok["changes"] == [{"path": "scoring.grades.A", "before": 80, "after": 70}]


def test_save_activate_and_roll_back(client):
    same = client.post("/api/config/versions", headers=h("boss"), json={"sections": sections(client, lambda s: None)})
    assert same.status_code == 422 and "nothing changed" in same.json()["detail"]

    body = {"sections": sections(client, lambda s: s["scoring"]["grades"].update(A=70)), "note": "Easier A grade"}
    v2 = client.post("/api/config/versions", headers=h("boss"), json=body).json()["version"]
    assert (v2["id"], v2["status"], v2["note"], v2["created_by"]) == (2, "draft", "Easier A grade", "boss@test.dev")
    detail = client.get("/api/config/versions/2", headers=h("max")).json()
    assert detail["changes"] == [{"path": "scoring.grades.A", "before": 80, "after": 70}]
    assert client.get("/api/config", headers=h("boss")).json()["active"]["id"] == 1   # a draft changes nothing yet

    act = client.post("/api/config/versions/2/activate", headers=h("boss")).json()
    assert act["version"]["status"] == "active" and act["replayed_events"] > 0
    assert client.get("/api/sim/status", headers=h("boss")).json()["config_version"] == 2
    leads = client.get("/api/leads?limit=500", headers=h("boss")).json()["items"]
    assert all(l["grade"] == "A" for l in leads if l["score"] >= 70)
    pts = client.get(f"/api/leads/{leads[0]['lead_id']}/score-history", headers=h("boss")).json()["points"]
    assert pts and all(p["config_version"] == 2 for p in pts)

    back = client.post("/api/config/versions/1/restore", headers=h("boss"), json={}).json()["version"]
    assert (back["id"], back["status"], back["restored_from"]) == (3, "active", 1)
    assert back["note"] == "Rolled back to version 1" and back["changes_from_defaults"] == 0
    hist = client.get("/api/config/versions", headers=h("boss")).json()["items"]
    assert [(v["id"], v["status"]) for v in hist] == [(3, "active"), (2, "retired"), (1, "retired")]
    assert client.post("/api/config/versions/2/activate", headers=h("boss")).status_code == 409
    assert client.post("/api/config/versions/3/activate", headers=h("boss")).status_code == 409
    assert client.get("/api/config/versions/99", headers=h("boss")).status_code == 404


# ================================================================================================ what-if
def wait_for(c, rid: int) -> dict:
    for _ in range(400):
        run = c.get(f"/api/config/whatif/{rid}", headers=h("max")).json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    raise AssertionError("what-if run did not finish")


def test_what_if_compares_draft_rules_with_the_rules_in_force(client):
    active = client.get("/api/config", headers=h("boss")).json()["active"]["id"]
    body = {"sections": sections(client, lambda s: s["scoring"]["grades"].update(A=50, B=35))}
    assert client.post("/api/config/whatif", headers=h("max"), json=body).status_code == 403
    assert client.get("/api/config/whatif", headers=h("rita")).status_code == 403
    same = client.post("/api/config/whatif", headers=h("boss"), json={"sections": sections(client, lambda s: None)})
    assert same.status_code == 422 and "nothing changed" in same.json()["detail"]
    bad = client.post("/api/config/whatif", headers=h("boss"), json={"sections": {"scoring": "grades: [\n"}})
    assert bad.status_code == 422 and "not valid YAML" in bad.json()["detail"]

    started = client.post("/api/config/whatif", headers=h("boss"), json=body)
    assert started.status_code == 202
    run = started.json()
    assert run["label"] == "Unsaved edits" and run["against"]["id"] == active and run["events"] > 0
    assert run["settings_changes"] == [{"path": "scoring.grades.A", "before": 80, "after": 50},
                                       {"path": "scoring.grades.B", "before": 60, "after": 35}]
    done = wait_for(client, run["id"])                              # managers can read the result
    assert done["status"] == "done" and done["progress"] == 1.0 and not done["stale"]
    r = done["result"]
    assert r["counts"]["grade"] == r["counts"]["grade_up"] > 0 and r["counts"]["grade_down"] == 0
    assert r["grades"]["after"]["A"] > r["grades"]["before"].get("A", 0)
    assert client.get("/api/config", headers=h("boss")).json()["active"]["id"] == active   # nothing switched
    assert [x["id"] for x in client.get("/api/config/whatif", headers=h("max")).json()["items"]][0] == run["id"]
    assert client.get("/api/config/whatif/999", headers=h("max")).status_code == 404


def test_what_if_runs_on_a_saved_version(client):
    active = client.get("/api/config", headers=h("boss")).json()["active"]["id"]
    body = {"sections": sections(client, lambda s: s["scoring"]["grades"].update(A=95)), "note": "Strict A"}
    draft = client.post("/api/config/versions", headers=h("boss"), json=body).json()["version"]
    run = client.post("/api/config/whatif", headers=h("boss"), json={"version_id": draft["id"]}).json()
    assert run["label"] == f"Version {draft['id']}"
    r = wait_for(client, run["id"])["result"]
    assert r["counts"]["grade_up"] == 0 and r["counts"]["grade_down"] == r["counts"]["grade"]
    in_force = client.post("/api/config/whatif", headers=h("boss"), json={"version_id": active})
    assert in_force.status_code == 409 and "already in force" in in_force.json()["detail"]
    assert client.post("/api/config/whatif", headers=h("boss"), json={"version_id": 999}).status_code == 404
