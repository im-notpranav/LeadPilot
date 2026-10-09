"""Synthetic identities, titles and reply texts for simulated prospects."""
from __future__ import annotations

import random
import string

FIRST = {
    "India": ["Priya", "Rahul", "Ananya", "Arjun", "Sneha", "Vikram", "Kavya", "Rohit", "Neha", "Aditya", "Isha", "Karan"],
    "APAC": ["Wei", "Mei", "Hiro", "Yuki", "Jun", "Siti", "Ravi", "Grace", "Daniel", "Hana", "Liam", "Chloe"],
    "NA": ["Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Mia", "Lucas", "Sophia", "Mason", "Harper", "James"],
    "EMEA": ["Lukas", "Sofia", "Hugo", "Elena", "Max", "Chloe", "Omar", "Freya", "Mateo", "Nina", "Felix", "Amira"],
    "LATAM": ["Lucas", "Valentina", "Mateo", "Camila", "Santiago", "Isabella", "Diego", "Mariana"],
}
LAST = {
    "India": ["Nair", "Sharma", "Iyer", "Patel", "Reddy", "Gupta", "Menon", "Kumar", "Shah", "Rao", "Das", "Joshi"],
    "APAC": ["Tan", "Lim", "Sato", "Tanaka", "Wong", "Lee", "Ng", "Chen", "Nguyen", "Santos", "Kim", "Park"],
    "NA": ["Smith", "Johnson", "Brown", "Miller", "Davis", "Wilson", "Moore", "Taylor", "Clark", "Lewis", "Walker"],
    "EMEA": ["Muller", "Schmidt", "Dubois", "Rossi", "Garcia", "Jansen", "Novak", "Andersson", "Haddad", "Fischer"],
    "LATAM": ["Silva", "Santos", "Oliveira", "Gomez", "Fernandez", "Lopez", "Ramirez", "Costa"],
}
TITLES = {
    "senior": ["CEO", "CTO", "COO", "VP Sales", "VP Operations", "Head of Revenue", "Director of Engineering",
               "Head of Operations", "Chief Revenue Officer", "VP Marketing", "Director of IT"],
    "mid": ["Sales Manager", "Operations Manager", "Product Manager", "Engineering Manager", "Marketing Manager",
            "Team Lead", "Program Manager"],
    "junior": ["Analyst", "Sales Associate", "Software Engineer", "Marketing Specialist", "Coordinator",
               "Business Analyst", "Student", "Intern"],
}
IP_PREFIX = {"US": "23", "CA": "24", "GB": "81", "DE": "84", "FR": "90", "NL": "77", "AE": "94", "IN": "103",
             "SG": "112", "AU": "101", "JP": "126", "ID": "36", "BR": "177", "MX": "187", "SE": "78", "ZA": "41"}
PHONE_FMT = {"IN": ("+91 9{}", 9), "US": ("+1 415 {}", 7), "CA": ("+1 416 {}", 7), "GB": ("+44 7700 {}", 6),
             "SG": ("+65 8{}", 7), "AU": ("+61 4{}", 8), "DE": ("+49 151 {}", 8), "FR": ("+33 6{}", 8),
             "NL": ("+31 6{}", 8), "AE": ("+971 50 {}", 7), "JP": ("+81 90 {}", 8), "BR": ("+55 11 9{}", 8)}

REPLIES = {
    "positive_intent": [
        "Thanks - can you send pricing for {seats} seats? We would like to decide this quarter.",
        "Interested. What does the timeline look like, and can we book a demo next week?",
        "This looks relevant. Our budget is around ${budget}k - could you share a proposal?",
        "Good timing. Can you walk us through pricing and next steps?",
    ],
    "negotiation": [
        "The proposal looks good. Can we discuss a discount and the contract terms?",
        "We are aligned internally - please send the contract and we will loop in procurement.",
        "Legal has a couple of redlines on the MSA, otherwise ready to sign.",
    ],
    "neutral": [
        "Thanks for the note, I will take a look.",
        "Got it - circling back with the team.",
        "Appreciate it. Let me review and get back to you.",
    ],
    "objection": [
        "Honestly this looks too expensive for us right now.",
        "We already use a competitor and are locked in until next year.",
        "Not a priority this quarter - bad timing.",
    ],
    "negative": [
        "Not interested, please remove me from your list.",
        "Wrong person - please stop emailing me.",
    ],
    "out_of_office": ["I am out of office until next week with limited access to email."],
}


def pick(rng: random.Random, weights: dict) -> str:
    keys = sorted(weights)
    return rng.choices(keys, [weights[k] for k in keys])[0]


def region_of(country: str, cfg) -> str:
    return cfg.derived.country_region.get(country, "NA")


def ip_for(rng: random.Random, country: str) -> str:
    return f"{IP_PREFIX.get(country, '23')}.{rng.randint(1, 254)}.{rng.randint(1, 254)}.{rng.randint(1, 254)}"


def phone_for(rng: random.Random, country: str) -> str | None:
    fmt = PHONE_FMT.get(country)
    if not fmt:
        return None
    pattern, n = fmt
    return pattern.format("".join(rng.choice(string.digits[1:]) for _ in range(n)))


def make_identity(rng: random.Random, cfg, company: dict, seniority_mix: dict, capture: str,
                  free_mail: bool = False) -> dict:
    country = company.get("country", "US")
    region = region_of(country, cfg)
    first = rng.choice(FIRST.get(region, FIRST["NA"]))
    last = rng.choice(LAST.get(region, LAST["NA"]))
    title = rng.choice(TITLES[pick(rng, seniority_mix)])
    local = rng.choice([f"{first}.{last}", f"{first[0]}{last}", f"{first}"]).lower()
    email = f"{local}@{rng.choice(['gmail.com', 'yahoo.com', 'outlook.com'])}" if free_mail else f"{local}@{company['domain']}"
    payload = {
        "name": f"{first} {last}", "email": email, "company": company["name"], "title": title, "country": country,
        "phone": phone_for(rng, country) if rng.random() < 0.7 else None, "ip": ip_for(rng, country),
        "capture_method": capture, "form_fill_seconds": rng.randint(12, 140),
        "utm": {"campaign": rng.choice(["q4-launch", "pricing-guide", "webinar-series", "brand"])},
    }
    if free_mail:
        payload["website"] = company["domain"] if rng.random() < 0.5 else None
    if rng.random() < 0.15:
        payload["seats"] = rng.choice([10, 25, 50, 100, 250])
    if rng.random() < 0.1:
        payload["budget"] = rng.choice([15000, 30000, 60000, 120000])
    return payload


def variant_identity(rng: random.Random, payload: dict, capture: str) -> dict:
    """Same person, different form: plus-tag / case / name / phone formatting variants."""
    v = dict(payload)
    local, _, domain = payload["email"].partition("@")
    choice = rng.random()
    if domain in ("gmail.com", "googlemail.com") and choice < 0.5:
        v["email"] = f"{local.replace('.', '')[:3]}.{local.replace('.', '')[3:]}@googlemail.com"
    elif choice < 0.8:
        v["email"] = f"{local}+{rng.choice(['ads', 'list', 'promo', 'events'])}@{domain}".upper() if rng.random() < 0.3 \
            else f"{local}+{rng.choice(['ads', 'list', 'promo', 'events'])}@{domain}"
    else:
        v["email"] = f" {payload['email'].upper()} "
    v["name"] = payload["name"].upper() if rng.random() < 0.3 else payload["name"]
    if payload.get("phone") and rng.random() < 0.5:
        v["phone"] = payload["phone"].replace(" ", "-")
    v["capture_method"] = capture
    v["form_fill_seconds"] = rng.randint(10, 90)
    return v


def bot_identity(rng: random.Random, cfg, ip: str) -> dict:
    letters = "bcdfghjklmnpqrstvwxz"
    gib = "".join(rng.choice(letters) for _ in range(rng.randint(5, 8))).title()
    domain = rng.choice(sorted(cfg.data.disposable_domains | cfg.data.no_mx_domains))
    local = rng.choice(["asdf", "test", "qwerty", gib.lower(), "info", "xyz" + str(rng.randint(1, 99))])
    return {"name": f"{gib} {rng.choice(['Xyz', 'Qwrtz', 'Asdf', gib[::-1].title()])}",
            "email": f"{local}@{domain}", "company": rng.choice(["Test Co", "Asdf Ltd", "", "Xyz Corp"]),
            "title": rng.choice(["", "Manager", "CEO"]), "country": rng.choice(["US", "GB", "IN"]),
            "phone": rng.choice(["9999999999", "1234567890", "0000000000", None]), "ip": ip,
            "capture_method": "cold_import", "form_fill_seconds": rng.choice([0, 1, 2])}


def reply_text(rng: random.Random, cls: str, seats: int | None = None) -> str:
    tmpl = rng.choice(REPLIES[cls])
    return tmpl.format(seats=seats or rng.choice([20, 40, 75, 150]), budget=rng.choice([25, 40, 60, 90]))
