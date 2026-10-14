"""Field mapping shared by every connector: whatever a form, CRM or spreadsheet calls its columns
("Email Address", "FirstName", "properties.company.value"...) becomes a LeadPilot `lead_created` payload.

Pure functions only: no I/O, no clock.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..engine.types import iso

# canonical field -> names other tools use for it (compared after `norm_key`)
ALIASES: dict[str, tuple[str, ...]] = {
    "email": ("email", "e mail", "email address", "emailaddress", "work email", "business email", "mail",
              "contact email", "your email", "email id", "primary email"),
    "first_name": ("first name", "firstname", "given name", "fname", "first"),
    "last_name": ("last name", "lastname", "surname", "family name", "lname", "last"),
    "name": ("name", "full name", "fullname", "your name", "contact name", "contact", "person name", "lead name"),
    "company": ("company", "company name", "companyname", "organization", "organisation", "org", "org name",
                "organization name", "account", "account name", "business", "business name", "employer"),
    "title": ("title", "job title", "jobtitle", "role", "position", "designation", "job role"),
    "phone": ("phone", "phone number", "phonenumber", "mobile", "mobilephone", "mobile phone", "mobile number",
              "telephone", "tel", "cell", "contact number", "work phone", "whatsapp"),
    "country": ("country", "country code", "countrycode", "country region", "nation", "country name"),
    "website": ("website", "company website", "web site", "url", "company url", "domain", "company domain", "site"),
    "message": ("message", "comments", "comment", "notes", "note", "details", "how can we help", "description",
                "enquiry", "inquiry", "your message", "question", "requirements"),
    "form_type": ("form type", "form", "form name", "intent", "interest", "request type", "inquiry type",
                  "enquiry type", "reason", "topic", "subject", "i am interested in", "what are you looking for"),
    "lead_source": ("lead source", "leadsource", "source", "original source", "hs analytics source", "channel"),
    "created_at": ("created at", "created", "create date", "createdate", "created date", "date created",
                   "submitted at", "submitted", "submission date", "timestamp", "date", "created time"),
}
_LOOKUP = {}
for _field, _names in ALIASES.items():
    for _n in _names:
        _LOOKUP.setdefault(_n, _field)

_KEY_JUNK = re.compile(r"[^a-z0-9]+")
_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")

COUNTRY_NAMES = {
    "india": "IN", "united states": "US", "united states of america": "US", "usa": "US", "us": "US",
    "america": "US", "united kingdom": "GB", "uk": "GB", "great britain": "GB", "england": "GB", "canada": "CA",
    "australia": "AU", "germany": "DE", "deutschland": "DE", "france": "FR", "spain": "ES", "italy": "IT",
    "netherlands": "NL", "singapore": "SG", "malaysia": "MY", "indonesia": "ID", "philippines": "PH",
    "thailand": "TH", "vietnam": "VN", "japan": "JP", "china": "CN", "hong kong": "HK", "south korea": "KR",
    "korea": "KR", "united arab emirates": "AE", "uae": "AE", "saudi arabia": "SA", "qatar": "QA",
    "israel": "IL", "south africa": "ZA", "nigeria": "NG", "kenya": "KE", "egypt": "EG", "brazil": "BR",
    "mexico": "MX", "argentina": "AR", "chile": "CL", "colombia": "CO", "ireland": "IE", "sweden": "SE",
    "norway": "NO", "denmark": "DK", "finland": "FI", "switzerland": "CH", "austria": "AT", "belgium": "BE",
    "poland": "PL", "portugal": "PT", "new zealand": "NZ", "sri lanka": "LK", "bangladesh": "BD",
    "pakistan": "PK", "nepal": "NP",
}

INTENT_WORDS = (   # first match wins; checked against the form's type / name, never the free-text message
    ("demo_request", ("demo", "walkthrough", "book a call", "see it in action")),
    ("trial_signup", ("trial", "sign up", "signup", "get started", "start free", "free account")),
    ("contact_sales", ("sales", "pricing", "quote", "contact", "talk to", "enterprise", "consultation")),
)
FORM_KINDS = ("auto", "none", "demo_request", "contact_sales", "trial_signup")
CAPTURE_METHODS = ("form_submit", "ad_lead", "referral", "badge_scan", "partner_lead", "cold_import")

# (category, pattern on the lower-cased URL path) - first match wins. Categories the scoring rules know:
# pricing, enterprise_plan, competitor_compare, case_study, roi (intent) and anything else (engagement only).
PAGE_RULES: tuple[tuple[str, str], ...] = (
    ("enterprise_plan", r"enterprise"),
    ("pricing", r"(^|/)(pricing|plans?|prices?|buy)(/|$|[-.?])"),
    ("competitor_compare", r"(^|/)vs[-/]|-vs-|compar|alternative"),
    ("case_study", r"case-?stud|customers?(/|$)|success-stor"),
    ("roi", r"(^|/|-)roi(/|$|-)|calculator"),
    ("docs", r"(^|/)(docs|documentation|help|support|guides?|api)(/|$)"),
    ("blog", r"(^|/)(blog|news|articles?|resources|insights)(/|$)"),
    ("product", r"(^|/)(product|features?|platform|solutions?|integrations?|how-it-works)(/|$)"),
)


def norm_key(key) -> str:
    return _KEY_JUNK.sub(" ", str(key).lower()).strip()


def clean(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = ", ".join(str(v) for v in value if v not in (None, ""))
    s = str(value).strip()
    return s or None


# ------------------------------------------------------------------------------------------------ flattening
def flatten(obj) -> dict[str, str]:
    """Collapse the shapes CRMs and form tools send into one flat {field: text} dict.

    Handles HubSpot ({"properties": {"email": {"value": ...}}} and v3 {"properties": {"email": ...}}),
    Pipedrive ({"email": [{"value": ..., "primary": true}]}), Webflow ({"data": {...}}), Typeform
    ({"form_response": {"answers": [...]}}), Salesforce field names, and plain flat JSON. Shallower keys win.
    """
    out: dict[str, str] = {}
    if isinstance(obj, dict) and isinstance(obj.get("form_response"), dict):
        out.update(_typeform(obj["form_response"]))
    level = [obj]
    for _ in range(4):                       # breadth first, a few levels deep
        nxt = []
        for node in level:
            if not isinstance(node, dict):
                continue
            for k, v in node.items():
                if isinstance(v, dict) and "value" in v and not isinstance(v["value"], (dict, list)):
                    v = v["value"]           # HubSpot v1 property
                elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                    if all("value" in x for x in v):     # Pipedrive multi-value field
                        primary = next((x for x in v if x.get("primary")), v[0])
                        v = primary.get("value")
                    else:
                        nxt.extend(v)
                        continue
                if isinstance(v, dict):
                    nxt.append(v)
                    continue
                text = clean(v)
                if text is not None and str(k) not in out:
                    out[str(k)] = text
        level = nxt
        if not level:
            break
    return out


def _typeform(resp: dict) -> dict[str, str]:
    titles = {f.get("id"): f.get("title") or f.get("ref") for f in (resp.get("definition") or {}).get("fields", [])}
    out = {}
    for a in resp.get("answers") or []:
        field = a.get("field") or {}
        key = titles.get(field.get("id")) or field.get("ref") or a.get("type")
        val = a.get(a.get("type"))
        if isinstance(val, dict):            # choice answers
            val = val.get("label") or val.get("labels")
        if key and clean(val):
            out[str(key)] = clean(val)
    return out


# ------------------------------------------------------------------------------------------------ mapping
def canonical(fields: dict, column_map: dict | None = None) -> tuple[dict, dict]:
    """Return ({canonical field: value}, {original key: canonical field}) for the keys we recognise.

    `column_map` (original key -> canonical field, or "" to ignore) overrides the automatic aliases.
    Unrecognised utm_* keys are kept as-is; other unrecognised keys are dropped.
    """
    column_map = column_map or {}
    out: dict[str, str] = {}
    used: dict[str, str] = {}
    for key, raw in fields.items():
        val = clean(raw)
        if val is None:
            continue
        if key in column_map:
            target = column_map[key] or None
        else:
            nk = norm_key(key)
            target = _LOOKUP.get(nk) or _LOOKUP.get(nk.replace(" ", ""))
            if target is None and nk.startswith("utm "):
                target = nk.replace(" ", "_")
            if target is None and "email" in nk and _EMAIL.fullmatch(val):
                target = "email"
        if target and target not in out:
            out[target] = val
            used[key] = target
    return out, used


def country_code(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if len(v) == 2 and v.isalpha():
        return v.upper()
    return COUNTRY_NAMES.get(norm_key(v))


def intent_for(*texts: str | None) -> str | None:
    blob = " ".join(norm_key(t) for t in texts if t)
    if not blob:
        return None
    for event_type, words in INTENT_WORDS:
        if any(w in blob for w in words):
            return event_type
    return None


def source_key(value: str | None) -> str | None:
    s = norm_key(value or "").replace(" ", "_")
    return s[:40] or None


def parse_when(value: str | None) -> datetime | None:
    """ISO 8601, epoch seconds / milliseconds (HubSpot), or common spreadsheet dates. Naive times are UTC."""
    if not value:
        return None
    v = value.strip()
    if re.fullmatch(r"\d{10}(\d{3})?(\.\d+)?", v):
        n = float(v)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?", v)
    if m:
        a, b, year = int(m[1]), int(m[2]), int(m[3])
        day, month = (b, a) if b > 12 else (a, b)        # day first unless that is impossible
        try:
            return datetime(year, month, day, int(m[4] or 0), int(m[5] or 0), int(m[6] or 0), tzinfo=timezone.utc)
        except ValueError:
            return None
    for fmt in ("%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y"):
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def lead_from_fields(fields: dict, *, source: str, capture_method: str = "form_submit", form_name: str | None = None,
                     form_kind: str = "auto", column_map: dict | None = None, use_record_source: bool = False,
                     ip: str | None = None) -> dict:
    """Map one submission / record. Returns {"ok", "error", "payload", "source", "intent", "ts", "lead_ref", "used"}.

    `payload` is a lead_created payload; `intent` is demo_request / contact_sales / trial_signup or None.
    A record needs an email or a phone number, or LeadPilot cannot identify the person later.
    """
    c, used = canonical(fields, column_map)
    email = c.get("email")
    if email and not _EMAIL.fullmatch(email):
        found = _EMAIL.search(email)
        email = found.group(0) if found else None
    phone = c.get("phone")
    if not email and not phone:
        return {"ok": False, "error": "no email address or phone number", "used": used}
    name = c.get("name") or " ".join(x for x in (c.get("first_name"), c.get("last_name")) if x) or None
    payload = {"name": name, "email": email, "phone": phone, "company": c.get("company"), "title": c.get("title"),
               "country": country_code(c.get("country")), "website": c.get("website"),
               "capture_method": capture_method}
    if c.get("country") and not payload["country"]:
        payload["country_name"] = c["country"]
    if c.get("message"):
        payload["message"] = c["message"][:2000]
    if form_name or c.get("form_type"):
        payload["form_name"] = (form_name or c.get("form_type"))[:120]
    if ip:
        payload["ip"] = ip
    payload.update({k: v[:200] for k, v in c.items() if k.startswith("utm_")})
    payload = {k: v for k, v in payload.items() if v is not None}
    if form_kind == "auto":
        intent = intent_for(c.get("form_type"), form_name) if capture_method == "form_submit" else None
    else:
        intent = None if form_kind == "none" else form_kind
    when = parse_when(c.get("created_at"))
    rec_source = source_key(c.get("lead_source")) if use_record_source else None
    ref = {"email": email} if email else {"phone": phone, **({"country": payload["country"]} if "country" in payload else {})}
    return {"ok": True, "error": None, "payload": payload, "source": rec_source or source, "intent": intent,
            "ts": iso(when) if when else None, "lead_ref": ref, "used": used}


def lead_events(mapped: dict, event_id: str, ts: str | None = None, history: bool = False) -> list[dict]:
    """The events for one mapped record: lead_created, then the form's intent event if it has one."""
    when = mapped.get("ts") or ts
    created = {"event_id": event_id, "type": "lead_created", "source": mapped["source"], "payload": mapped["payload"]}
    if when:
        created["ts"] = when
    if history:
        created["import"] = True
    out = [created]
    if mapped.get("intent"):
        ev = {"event_id": f"{event_id}.i", "type": mapped["intent"], "source": mapped["source"],
              "lead_ref": mapped["lead_ref"], "payload": {"form_name": mapped["payload"].get("form_name")}}
        if when:
            ev["ts"] = when
        if history:
            ev["import"] = True
        out.append(ev)
    return out


def page_category(path: str | None, extra_rules: list | None = None) -> str:
    p = (path or "/").lower().split("?", 1)[0].split("#", 1)[0] or "/"
    for rule in extra_rules or []:
        try:
            if re.search(rule["pattern"], p):
                return str(rule["category"])
        except (re.error, KeyError, TypeError):
            continue
    if p in ("/", "/index.html", "/home"):
        return "home"
    for category, pattern in PAGE_RULES:
        if re.search(pattern, p):
            return category
    return "other"
