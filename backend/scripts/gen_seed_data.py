"""Generate deterministic seed data: data/companies.json (~300 companies keyed by domain).

Run: python backend/scripts/gen_seed_data.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

PREFIXES = ["Acme", "Zenith", "Nimbus", "Vertex", "Quantum", "Lumen", "Orbit", "Cobalt", "Apex", "Nova", "Helix",
            "Summit", "Atlas", "Pioneer", "Beacon", "Crest", "Ember", "Falcon", "Granite", "Harbor", "Ion", "Juniper",
            "Kestrel", "Lattice", "Meridian", "Northwind", "Onyx", "Prism", "Quill", "Redwood", "Sable", "Tidal",
            "Umbra", "Vantage", "Willow", "Xenon", "Yarrow", "Zephyr", "Aurora", "Bluepeak", "Cascade", "Delta",
            "Evergreen", "Fusion", "Glacier", "Horizon", "Indigo", "Jade", "Keystone", "Lighthouse"]
SUFFIX_BY_INDUSTRY = {
    "saas": ["Cloud", "Labs", "Software", "Systems", "Stack", "AI"],
    "fintech": ["Pay", "Payments", "Capital", "Finance", "Ledger", "Money"],
    "healthcare_it": ["Health", "Care", "Medical", "Clinic Systems", "Bio IT"],
    "ecommerce": ["Commerce", "Shop", "Retail Tech", "Market", "Cart"],
    "logistics": ["Logistics", "Freight", "Shipping", "Transit", "Supply"],
    "manufacturing": ["Industries", "Manufacturing", "Works", "Fabrication", "Robotics"],
    "retail": ["Stores", "Retail", "Brands", "Outfitters"],
    "education": ["Learning", "Academy", "EdTech", "Schools"],
    "media": ["Media", "Studios", "Publishing", "Broadcast"],
    "consulting": ["Consulting", "Partners", "Advisory", "Group"],
    "real_estate": ["Realty", "Properties", "Estates"],
}
INDUSTRY_WEIGHTS = {"saas": 0.22, "fintech": 0.14, "healthcare_it": 0.10, "ecommerce": 0.11, "logistics": 0.08,
                    "manufacturing": 0.09, "retail": 0.07, "education": 0.06, "media": 0.05, "consulting": 0.05,
                    "real_estate": 0.03}
COUNTRY_WEIGHTS = {"US": 0.28, "CA": 0.04, "GB": 0.09, "DE": 0.06, "FR": 0.04, "NL": 0.03, "AE": 0.02, "SG": 0.07,
                   "AU": 0.05, "JP": 0.03, "ID": 0.02, "IN": 0.18, "BR": 0.04, "MX": 0.02, "SE": 0.02, "ZA": 0.01}
TLD_BY_COUNTRY = {"US": [".com", ".io", ".ai"], "CA": [".ca", ".com"], "GB": [".co.uk", ".com"], "DE": [".de", ".com"],
                  "FR": [".fr", ".com"], "NL": [".nl", ".io"], "AE": [".ae", ".com"], "SG": [".sg", ".com", ".io"],
                  "AU": [".com.au", ".io"], "JP": [".jp", ".com"], "ID": [".co.id", ".com"], "IN": [".in", ".io", ".com"],
                  "BR": [".com.br", ".io"], "MX": [".mx", ".com"], "SE": [".se", ".io"], "ZA": [".co.za", ".com"]}
TECH = ["salesforce", "hubspot", "aws", "gcp", "azure", "snowflake", "stripe", "shopify", "zendesk", "slack",
        "segment", "marketo", "sap", "oracle", "kubernetes", "postgres"]
FUNDING = ["bootstrapped", "seed", "series_a", "series_b", "series_c", "growth", "public"]

# Fixed companies used by the scripted demo scenarios.
FIXED = [
    {"domain": "acme.io", "name": "Acme Inc", "employees": 120, "industry": "saas", "country": "IN"},
    {"domain": "finnova.sg", "name": "FinNova Payments Pte Ltd", "employees": 300, "industry": "fintech", "country": "SG"},
    {"domain": "northwindlogistics.com", "name": "Northwind Logistics", "employees": 650, "industry": "logistics", "country": "US"},
    {"domain": "helixhealth.com", "name": "Helix Health Systems", "employees": 1500, "industry": "healthcare_it", "country": "US"},
    {"domain": "brightcart.co.uk", "name": "BrightCart Ltd", "employees": 85, "industry": "ecommerce", "country": "GB"},
]


def employee_count(rng: random.Random) -> int:
    band = rng.choices([(2, 10), (11, 50), (51, 200), (201, 1000), (1001, 8000)], weights=[0.12, 0.28, 0.30, 0.20, 0.10])[0]
    return rng.randint(*band)


def revenue_band(employees: int) -> str:
    if employees <= 10:
        return "<1M"
    if employees <= 50:
        return "1-10M"
    if employees <= 200:
        return "10-50M"
    if employees <= 1000:
        return "50-250M"
    return "250M+"


def finish(c: dict, rng: random.Random) -> dict:
    c.setdefault("revenue_band", revenue_band(c["employees"]))
    c.setdefault("tech_stack", sorted(rng.sample(TECH, rng.randint(2, 5))))
    c.setdefault("funding_stage", rng.choice(FUNDING))
    c.setdefault("mx_valid", True)
    return c


def main() -> None:
    rng = random.Random(7)
    companies = {}
    for c in FIXED:
        companies[c["domain"]] = finish(dict(c), rng)
    industries, iw = zip(*INDUSTRY_WEIGHTS.items())
    countries, cw = zip(*COUNTRY_WEIGHTS.items())
    while len(companies) < 300:
        industry = rng.choices(industries, iw)[0]
        country = rng.choices(countries, cw)[0]
        prefix = rng.choice(PREFIXES)
        suffix = rng.choice(SUFFIX_BY_INDUSTRY[industry])
        name = f"{prefix} {suffix}"
        slug = (prefix + suffix.split()[0]).lower()
        domain = slug + rng.choice(TLD_BY_COUNTRY[country])
        if domain in companies:
            continue
        legal = rng.choice(["", " Inc", " Ltd", " LLC", " GmbH", " Pvt Ltd", " Corp"])
        companies[domain] = finish({"domain": domain, "name": name + legal, "employees": employee_count(rng),
                                    "industry": industry, "country": country}, rng)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "companies.json").write_text(json.dumps(sorted(companies.values(), key=lambda c: c["domain"]), indent=1))
    (DATA / "reps.json").write_text(json.dumps(REPS, indent=1))
    (DATA / "sources.json").write_text(json.dumps(SOURCES, indent=1))
    (DATA / "disposable_domains.txt").write_text("\n".join(DISPOSABLE) + "\n")
    (DATA / "no_mx_domains.txt").write_text("\n".join(NO_MX) + "\n")
    (DATA / "ip_geo.json").write_text(json.dumps(IP_GEO, indent=1))
    print(f"wrote {len(companies)} companies, {len(REPS)} reps, {len(SOURCES)} sources")


# 8 reps across territories with different specialisms and response-delay profiles.
REPS = [
    {"rep_id": "R-ANANYA", "name": "Ananya Rao", "territories": ["APAC", "India"], "industries": ["fintech", "saas"],
     "segments": ["mid_market", "enterprise"], "languages": ["en", "hi"], "tz": 8, "capacity_points": 40,
     "tags": ["enterprise"], "profile": "fast", "base_win_rate": 0.31, "active": True},
    {"rep_id": "R-MARCUS", "name": "Marcus Chen", "territories": ["NA"], "industries": ["saas", "healthcare_it"],
     "segments": ["mid_market", "enterprise"], "languages": ["en"], "tz": -8, "capacity_points": 40,
     "tags": ["enterprise"], "profile": "average", "base_win_rate": 0.28, "active": True},
    {"rep_id": "R-SOPHIE", "name": "Sophie Laurent", "territories": ["EMEA"], "industries": ["fintech", "ecommerce"],
     "segments": ["smb", "mid_market"], "languages": ["en", "fr", "de"], "tz": 1, "capacity_points": 36,
     "tags": [], "profile": "fast", "base_win_rate": 0.27, "active": True},
    {"rep_id": "R-DANIEL", "name": "Daniel Okafor", "territories": ["EMEA"], "industries": ["manufacturing", "logistics"],
     "segments": ["mid_market", "enterprise"], "languages": ["en"], "tz": 0, "capacity_points": 36,
     "tags": ["enterprise"], "profile": "average", "base_win_rate": 0.24, "active": True},
    {"rep_id": "R-ROHAN", "name": "Rohan Mehta", "territories": ["India"], "industries": ["saas", "ecommerce", "education"],
     "segments": ["smb", "mid_market"], "languages": ["en", "hi"], "tz": 5.5, "capacity_points": 40,
     "tags": [], "profile": "average", "base_win_rate": 0.22, "active": True},
    {"rep_id": "R-EMILY", "name": "Emily Carter", "territories": ["NA", "LATAM"], "industries": ["ecommerce", "retail", "media"],
     "segments": ["smb"], "languages": ["en", "es"], "tz": -5, "capacity_points": 32,
     "tags": [], "profile": "slow", "base_win_rate": 0.18, "active": True},
    {"rep_id": "R-VICTOR", "name": "Victor Hale", "territories": ["NA"], "industries": ["healthcare_it", "saas", "logistics"],
     "segments": ["smb", "mid_market"], "languages": ["en"], "tz": -6, "capacity_points": 32,
     "tags": [], "profile": "neglectful", "base_win_rate": 0.12, "active": True},
    {"rep_id": "R-KENJI", "name": "Kenji Tanaka", "territories": ["global"], "industries": ["manufacturing", "logistics", "consulting"],
     "segments": ["smb", "mid_market", "enterprise"], "languages": ["en", "ja"], "tz": 9, "capacity_points": 30,
     "tags": ["enterprise"], "profile": "slow", "base_win_rate": 0.20, "active": True},
]

SOURCES = [
    {"source_id": "website", "name": "Website forms", "channel": "inbound", "cost_per_lead": 40},
    {"source_id": "google_ads", "name": "Google Ads", "channel": "paid", "cost_per_lead": 85},
    {"source_id": "referral", "name": "Customer referrals", "channel": "referral", "cost_per_lead": 20},
    {"source_id": "trade_show", "name": "Trade shows", "channel": "event", "cost_per_lead": 120},
    {"source_id": "partner", "name": "Partner network", "channel": "partner", "cost_per_lead": 60},
    {"source_id": "webinar", "name": "Webinars", "channel": "inbound", "cost_per_lead": 30},
    {"source_id": "cold_outreach", "name": "Cold outreach lists", "channel": "outbound", "cost_per_lead": 15},
    {"source_id": "list_vendor_x", "name": "List vendor X", "channel": "purchased", "cost_per_lead": 8},
]

DISPOSABLE = ["mailinator.com", "10minutemail.com", "guerrillamail.com", "tempmail.com", "temp-mail.org", "trashmail.com",
              "yopmail.com", "throwawaymail.com", "getnada.com", "dispostable.com", "fakeinbox.com", "sharklasers.com",
              "maildrop.cc", "mintemail.com", "mohmal.com", "emailondeck.com", "burnermail.io", "tempinbox.com"]

# Domains whose MX lookup "fails" in the mocked DNS (used by bot leads).
NO_MX = ["xqzvb.biz", "qwrtpl.net", "lkjhgf.info", "zzcorp.xyz", "mnbvc.top", "asdfgh.click", "bizleadz.online",
         "promo-leads.site", "corp-mail.shop", "datafeedz.xyz"]

# Mocked IP geolocation: first octet -> country.
IP_GEO = {"23": "US", "34": "US", "52": "US", "24": "CA", "81": "GB", "86": "GB", "84": "DE", "91": "DE", "90": "FR",
          "77": "NL", "94": "AE", "103": "IN", "106": "IN", "117": "IN", "112": "SG", "116": "SG", "101": "AU",
          "126": "JP", "36": "ID", "177": "BR", "187": "MX", "78": "SE", "41": "ZA", "185": "RU", "45": "VN",
          "5": "RU", "46": "UA"}


if __name__ == "__main__":
    main()
