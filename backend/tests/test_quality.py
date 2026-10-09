from app.engine.enrich import MockEnrichmentProvider, enrich
from app.engine.normalize import normalize_capture
from app.engine.quality import assess, is_gibberish


def run(cfg, payload, ip_count=1):
    prov = MockEnrichmentProvider(cfg)
    ident = normalize_capture(payload, cfg)
    ctx = {"ip_submissions_last_hour": ip_count, "mx_valid": prov.mx_valid(ident["email_domain"]),
           "ip_country": prov.ip_country(payload.get("ip")), "disposable": prov.is_disposable(ident["email_domain"])}
    return assess(ident, payload, ctx, cfg)


def test_clean_lead(cfg):
    r = run(cfg, {"name": "Priya Nair", "email": "priya.nair@finnova.sg", "company": "FinNova", "country": "SG",
                  "phone": "+65 8123 4567", "ip": "112.1.2.3", "form_fill_seconds": 40})
    assert r["status"] == "clean" and r["fake_score"] == 0


def test_bot_is_fake_with_signals(cfg):
    r = run(cfg, {"name": "Xkcd Qwrtz", "email": "asdf@mailinator.com", "company": "Test Co", "country": "US",
                  "phone": "9999999999", "ip": "185.3.3.3", "form_fill_seconds": 1}, ip_count=12)
    keys = {s["key"] for s in r["signals"]}
    assert r["status"] == "fake" and r["fake_score"] >= 70
    assert {"disposable_email", "test_pattern", "ip_velocity", "gibberish_name", "fast_form",
            "invalid_phone", "ip_country_mismatch"} <= keys


def test_suspicious_band(cfg):
    r = run(cfg, {"name": "Maria Lopez", "email": "info@yopmail.com", "country": "US", "ip": "23.1.1.1"})
    assert r["fake_score"] == 45 and r["status"] == "suspicious"


def test_no_mx_domain(cfg):
    r = run(cfg, {"name": "Dana Smith", "email": "dana@zzcorp.xyz", "country": "US", "ip": "23.1.1.1"})
    assert any(s["key"] == "no_mx" for s in r["signals"])


def test_free_mail_is_not_a_fake_signal(cfg):
    r = run(cfg, {"name": "Arjun Patel", "email": "arjun.patel@gmail.com", "country": "IN", "ip": "103.2.2.2"})
    assert r["fake_score"] == 0


def test_gibberish_detection(cfg):
    assert is_gibberish("Xkcd Qwrtz", cfg)
    assert is_gibberish("Aaaaron", cfg)
    assert not is_gibberish("Priya Nair", cfg)


def test_mock_enrichment(cfg):
    prov = MockEnrichmentProvider(cfg)
    e = enrich(normalize_capture({"email": "p@finnova.sg"}, cfg), prov, cfg)
    assert e["found"] and e["employees"] == 300 and e["employee_band"] == "201-1000" and e["industry"] == "fintech"
    assert enrich(normalize_capture({"email": "p@gmail.com"}, cfg), prov, cfg) is None
    unknown = enrich(normalize_capture({"email": "p@unknown-startup.dev"}, cfg), prov, cfg)
    assert unknown == {"account_id": "A-unknown-startup.dev", "domain": "unknown-startup.dev", "found": False}
