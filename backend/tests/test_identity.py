from app.engine.identity import blocking_keys, match_confidence, resolve
from app.engine.normalize import normalize_capture


def ident(cfg, **payload):
    return normalize_capture(payload, cfg)


def test_same_normalized_email_is_certain_match(cfg):
    a = ident(cfg, name="Rahul K", email="rahul.k@acme.io", company="Acme")
    b = ident(cfg, name="Rahul Kumar", email="rahul.k+ads@acme.io", phone="+91 98201 23456", country="IN")
    conf, keys = match_confidence(a, b, cfg)
    assert conf == 1.0 and keys == ["email_norm"]
    r = resolve(b, [("L-1001", a)], cfg)
    assert r.action == "merge" and r.lead_id == "L-1001"


def test_phone_and_similar_name(cfg):
    a = ident(cfg, name="Rahul Kumar", email="rahul@foo.com", phone="+91 98201 23456", country="IN")
    b = ident(cfg, name="Rahul Kumarr", email="rk@bar.com", phone="098201 23456", country="IN")
    assert match_confidence(a, b, cfg)[0] == 0.95
    assert resolve(b, [("L-1", a)], cfg).action == "merge"


def test_same_domain_and_name(cfg):
    a = ident(cfg, name="Rahul Kumar", email="r.kumar@acme.io")
    b = ident(cfg, name="Rahul Kumar", email="rahul.kumar@acme.io")
    assert match_confidence(a, b, cfg)[0] == 0.92


def test_same_company_and_name_goes_to_review(cfg):
    a = ident(cfg, name="Rahul Kumar", email="rahulk@gmail.com", company="Acme Inc")
    b = ident(cfg, name="Rahul Kumar", email="rahul.kumar99@yahoo.com", company="ACME")
    assert match_confidence(a, b, cfg)[0] == 0.85
    assert resolve(b, [("L-1", a)], cfg).action == "review"


def test_phone_only_goes_to_review(cfg):
    a = ident(cfg, name="Rahul Kumar", email="rahul@foo.com", phone="+91 98201 23456", country="IN")
    b = ident(cfg, name="Anita Shah", email="anita@bar.com", phone="+91 98201 23456", country="IN")
    assert match_confidence(a, b, cfg)[0] == 0.75
    assert resolve(b, [("L-1", a)], cfg).action == "review"


def test_unrelated_is_new(cfg):
    a = ident(cfg, name="Rahul Kumar", email="rahul@foo.com")
    b = ident(cfg, name="Jane Doe", email="jane@bar.com")
    assert resolve(b, [("L-1", a)], cfg).action == "new"


def test_blocking_keys(cfg):
    keys = blocking_keys(ident(cfg, name="Rahul Kumar", email="rahul@acme.io", phone="+91 98201 23456",
                               country="IN", company="Acme Inc"))
    kinds = {k[0] for k in keys}
    assert kinds == {"email", "phone", "domain_last", "company_name"}


def test_oldest_lead_survives_on_tie(cfg):
    a = ident(cfg, name="Rahul Kumar", email="rahul@acme.io")
    r = resolve(a, [("L-1010", a), ("L-1002", a)], cfg)
    assert r.lead_id == "L-1002"
