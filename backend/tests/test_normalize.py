from app.engine.normalize import (normalize_capture, normalize_company, normalize_email, normalize_name,
                                  normalize_phone, region_for_country, seniority_from_title)


def test_email_gmail_strips_dots_and_plus_tag(cfg):
    assert normalize_email("  John.Doe+promo@GoogleMail.com ", cfg) == ("johndoe@gmail.com", "gmail.com", True)


def test_email_plus_tag_stripped_for_business_domains(cfg):
    norm, domain, free = normalize_email("rahul.k+ads@acme.io", cfg)
    assert norm == "rahul.k@acme.io" and domain == "acme.io" and not free


def test_email_invalid(cfg):
    assert normalize_email("not-an-email", cfg) == (None, None, False)
    assert normalize_email(None, cfg) == (None, None, False)


def test_phone_e164_with_country():
    assert normalize_phone("+91 98201 23456", "IN") == ("+919820123456", True)
    assert normalize_phone("(415) 555-2671", "US")[1] in (True, False)  # parses without raising


def test_phone_invalid_returns_none():
    assert normalize_phone("12345", "US") == (None, False)
    assert normalize_phone("abc", "US") == (None, False)


def test_name_title_case_and_split():
    assert normalize_name("  priya   NAIR ") == ("Priya Nair", "Priya", "Nair")
    assert normalize_name("Madonna") == ("Madonna", "Madonna", None)


def test_company_strips_punctuation_and_legal_suffixes(cfg):
    assert normalize_company("Acme, Inc.", cfg) == "acme"
    assert normalize_company("FinNova Payments Pte. Ltd.", cfg) == "finnova payments"
    assert normalize_company("Globex GmbH", cfg) == "globex"


def test_domain_from_email_unless_free_mail(cfg):
    assert normalize_capture({"email": "a@acme.io"}, cfg)["domain"] == "acme.io"
    ident = normalize_capture({"email": "a.b@gmail.com", "website": "https://www.acme.io/about"}, cfg)
    assert ident["domain"] == "acme.io" and ident["is_free_mail"]
    assert normalize_capture({"email": "a.b@gmail.com"}, cfg)["domain"] is None


def test_seniority_mapping(cfg):
    assert seniority_from_title("CEO & Co-Founder", cfg) == "c_level"
    assert seniority_from_title("VP Sales", cfg) == "vp"
    assert seniority_from_title("Head of Operations", cfg) == "director"
    assert seniority_from_title("Engineering Manager", cfg) == "manager"
    assert seniority_from_title("Data Analyst", cfg) == "ic"
    assert seniority_from_title("", cfg) == "unknown"
    assert seniority_from_title("Wizard", cfg) == "unknown"


def test_region_lookup(cfg):
    assert region_for_country("IN", cfg) == "India"
    assert region_for_country("sg", cfg) == "APAC"
    assert region_for_country("BR", cfg) == "LATAM"
    assert region_for_country(None, cfg) is None
