"""What-if testing: a scratch replay under draft rules, compared with the outcome of the rules in force."""
import pytest

from app.config_versions import ConfigStore, to_yaml
from app.persistence import NullPersistence
from app.runtime import Runtime
from app.whatif import compare, replay_under, snapshot

FAST = {"simulator": {"warmup_days": 4}}


def edited(cs: ConfigStore, change) -> dict[str, str]:
    eff = cs.effective(cs.active()["overrides"])
    change(eff)
    return {k: to_yaml(v) for k, v in eff.items()}


@pytest.fixture(scope="module")
def world():
    cs = ConfigStore(NullPersistence(), base_overrides=FAST)
    v1 = cs.ensure_initial()
    rt = Runtime(cs.build(v1["overrides"]))
    rt.apply_config(rt.cfg, v1["id"], replay=False)
    rt.reset(warmup=True)
    return cs, rt


def what_if(rt, cfg) -> dict:
    run = lambda c: replay_under(c, rt.store.raw_log, rt.store.historical, rt.clock.now())   # noqa: E731
    return compare(run(rt.cfg), run(cfg))


def test_a_scratch_replay_matches_the_live_engine(world):
    cs, rt = world
    live = snapshot(rt.store)
    scratch = replay_under(rt.cfg, rt.store.raw_log, rt.store.historical, rt.clock.now())
    assert live["leads"] == scratch["leads"]                       # every grade, score, stage, owner and action
    assert {k: v["stage"] for k, v in live["deals"].items()} == {k: v["stage"] for k, v in scratch["deals"].items()}


def test_the_rules_in_force_change_nothing(world):
    cs, rt = world
    r = what_if(rt, rt.cfg)
    assert r["unchanged"] and not any(r["changes"].values())
    assert r["grades"]["before"] == r["grades"]["after"] and r["deals"]["before"] == r["deals"]["after"]
    assert r["leads"]["before"]["leads"] > 20


def test_a_lower_grade_bar_only_moves_grades_up(world):
    cs, rt = world
    _, cfg = cs.validate(edited(cs, lambda e: e["scoring"]["grades"].update(A=60, B=45)))
    r = what_if(rt, cfg)
    assert not r["unchanged"] and r["counts"]["grade"] == r["counts"]["grade_up"] > 0
    assert r["counts"]["grade_down"] == 0
    assert all(c["score_before"] == c["score_after"] for c in r["changes"]["grade"])   # same scores, new labels
    assert all(c["after"] == "A" for c in r["changes"]["grade"] if c["score_after"] >= 60)
    assert r["grades"]["after"].get("A", 0) > r["grades"]["before"].get("A", 0)
    assert sum(r["grades"]["before"].values()) == sum(r["grades"]["after"].values())


def test_what_if_predicts_activation_exactly(world):          # last: it switches the shared runtime
    cs, rt = world
    overrides, cfg = cs.validate(edited(cs, lambda e: (e["scoring"]["grades"].update(A=65),
                                                         e["pipeline"]["stall"]["sla_days"].update(engaged=3))))
    predicted = replay_under(cfg, rt.store.raw_log, rt.store.historical, rt.clock.now())
    row = cs.create(overrides, "what-if check", "test", cfg.fingerprint)
    rt.apply_config(cfg, row["id"])
    assert compare(predicted, snapshot(rt.store))["unchanged"]
