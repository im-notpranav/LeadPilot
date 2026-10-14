"""Inbound email -> LeadPilot event. Pure.

Point a mail provider's inbound route (Postmark inbound, SendGrid Inbound Parse, Mailgun routes, or anything
that posts JSON / form fields) at an `email` connector. A prospect's reply becomes `email_replied` with only the
new text (quoted history and signatures removed); a delivery failure becomes `email_bounced` for the address
that bounced; out-of-office auto-replies are marked so they never count as engagement.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import re
from email.utils import parseaddr

_EMAIL = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_BR = re.compile(r"<\s*(br|/p|/div|/li|/tr)\s*/?>", re.I)

BOUNCE_SENDERS = ("mailer-daemon", "postmaster", "mail-daemon", "bounce", "bounces")
BOUNCE_SUBJECT = re.compile(r"undeliver|delivery (status )?notification|delivery has failed|mail delivery (failed|"
                            r"subsystem)|returned mail|failure notice|could not be delivered|delivery failure", re.I)
AUTO_SUBJECT = re.compile(r"^\s*(auto(matic)?[ -]?reply|auto:|out of (the )?office|ooo\b|away from|on leave|"
                          r"vacation)", re.I)
QUOTE_START = (
    re.compile(r"^\s*On\b.{0,200}\bwrote:\s*$", re.I),                     # Gmail / Apple Mail
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.I),             # Outlook (old)
    re.compile(r"^\s*_{10,}\s*$"),                                         # Outlook separator
    re.compile(r"^\s*Le .{0,200} a écrit\s*:\s*$", re.I),                  # French clients
    re.compile(r"^\s*Am .{0,200} schrieb .{0,200}:\s*$", re.I),            # German clients
)
SIGNATURE_START = (
    re.compile(r"^--\s*$"),
    re.compile(r"^\s*Sent from my (iPhone|iPad|Android|mobile|Galaxy|phone)", re.I),
    re.compile(r"^\s*Get Outlook for (iOS|Android)", re.I),
)
_HEADER_BLOCK = re.compile(r"^\s*(From|Sent|Date|To|Subject|Cc)\s*:", re.I)


def _headers(raw) -> dict[str, str]:
    """Headers as {lower-case name: value} from a dict, a [{Name, Value}] / [[name, value]] list, or raw text."""
    out: dict[str, str] = {}
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith(("[", "{")):
            try:
                raw = json.loads(raw)
            except ValueError:
                pass
    if isinstance(raw, str):
        for line in re.split(r"\r?\n(?![ \t])", raw):
            name, sep, value = line.partition(":")
            if sep:
                out.setdefault(name.strip().lower(), value.strip())
    elif isinstance(raw, dict):
        out = {str(k).lower(): str(v) for k, v in raw.items()}
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                out.setdefault(str(item.get("Name") or item.get("name")).lower(),
                               str(item.get("Value") or item.get("value")))
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                out.setdefault(str(item[0]).lower(), str(item[1]))
    return out


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    return html_lib.unescape(_TAGS.sub("", _BR.sub("\n", html)))


def _first(data: dict, *keys):
    for k in keys:
        v = data.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def normalize_message(data: dict) -> dict:
    """One shape for Postmark, SendGrid, Mailgun and plain JSON payloads."""
    headers = _headers(_first(data, "Headers", "headers", "message-headers") or {})
    full = data.get("FromFull") if isinstance(data.get("FromFull"), dict) else None
    from_raw = _first(data, "From", "from", "sender", "Sender") or headers.get("from") or ""
    name, addr = parseaddr(str(from_raw))
    if full:
        addr, name = full.get("Email") or addr, full.get("Name") or name
    text = _first(data, "TextBody", "text", "body-plain", "body_plain", "plain", "body", "Text")
    html = _first(data, "HtmlBody", "html", "body-html", "body_html", "Html")
    stripped = _first(data, "StrippedTextReply", "stripped-text", "stripped_text", "reply_text")
    return {
        "from_email": (addr or "").strip().lower() or None,
        "from_name": (name or "").strip() or None,
        "to": str(_first(data, "To", "to", "recipient") or headers.get("to") or ""),
        "subject": str(_first(data, "Subject", "subject") or headers.get("subject") or "").strip(),
        "text": str(text) if text else html_to_text(html),
        "stripped": str(stripped) if stripped else None,
        "headers": headers,
        "message_id": str(_first(data, "MessageID", "message_id", "Message-Id", "message-id")
                          or headers.get("message-id") or "").strip() or None,
        "in_reply_to": headers.get("in-reply-to") or data.get("in_reply_to"),
    }


def strip_quoted(text: str) -> str:
    """The new part of a reply: cut at the quoted-history marker or signature; drop "> " lines."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kept: list[str] = []
    for i, line in enumerate(lines):
        joined = line + " " + (lines[i + 1] if i + 1 < len(lines) else "")
        if any(p.match(line) for p in QUOTE_START):
            break
        if line.strip().startswith("On ") and QUOTE_START[0].match(joined):     # "On ... <x@y>\nwrote:"
            break
        if any(p.match(line) for p in SIGNATURE_START):
            break
        if (line.strip().lower().startswith("from:") and (i == 0 or not lines[i - 1].strip())
                and sum(bool(_HEADER_BLOCK.match(x)) for x in lines[i:i + 5]) >= 2):
            break                                        # Outlook "From: / Sent: / To:" header block
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    out = "\n".join(kept).strip()
    return re.sub(r"\n{3,}", "\n\n", out)[:5000]


def is_auto_reply(msg: dict) -> bool:
    h = msg["headers"]
    auto = h.get("auto-submitted", "").lower()
    if auto and auto != "no":
        return True
    if any(k in h for k in ("x-autoreply", "x-autorespond", "x-autoresponse")):
        return True
    if h.get("precedence", "").lower() in ("auto_reply", "bulk", "junk"):
        return True
    return bool(AUTO_SUBJECT.match(msg["subject"]))


def is_bounce(msg: dict) -> bool:
    local = (msg["from_email"] or "").split("@", 1)[0]
    ctype = msg["headers"].get("content-type", "").lower()
    return (local in BOUNCE_SENDERS or "report-type=delivery-status" in ctype
            or (bool(BOUNCE_SUBJECT.search(msg["subject"])) and local.startswith(("mailer", "postmaster", "bounce"))))


def bounced_recipient(msg: dict) -> str | None:
    text = msg["text"] or ""
    m = re.search(r"(?:Final|Original)-Recipient:\s*(?:rfc822;)?\s*<?([^\s>;]+@[^\s>;]+)>?", text, re.I)
    if m:
        return m.group(1).lower()
    ours = {msg["from_email"]} | {a.lower() for a in _EMAIL.findall(msg["to"])}
    for addr in _EMAIL.findall(text):
        if addr.lower() not in ours:
            return addr.lower()
    return None


def _event_id(msg: dict) -> str:
    basis = msg["message_id"] or f"{msg['from_email']}|{msg['subject']}|{msg['text'][:500]}"
    return "eml_" + hashlib.sha256(basis.encode()).hexdigest()[:24]


def email_event(data: dict, source: str | None = "email") -> dict:
    """Return {"ok", "error", "kind": reply|bounce, "event"} for one inbound message."""
    msg = normalize_message(data)
    if is_bounce(msg):
        rcpt = bounced_recipient(msg)
        if not rcpt:
            return {"ok": False, "kind": "bounce", "error": "bounce message without a recognisable recipient"}
        diag = re.search(r"Diagnostic-Code:\s*(.+)", msg["text"] or "", re.I)
        status = re.search(r"Status:\s*([245])\.\d+\.\d+", msg["text"] or "", re.I)
        payload = {"reason": (diag.group(1).strip() if diag else msg["subject"])[:300],
                   "bounce_type": "soft" if status and status.group(1) == "4" else "hard"}
        return {"ok": True, "kind": "bounce", "error": None,
                "event": {"event_id": _event_id(msg), "type": "email_bounced", "actor": "system", "source": source,
                          "lead_ref": {"email": rcpt}, "payload": payload}}
    if not msg["from_email"]:
        return {"ok": False, "kind": "reply", "error": "no sender address"}
    body = strip_quoted(msg["stripped"] or msg["text"] or "")
    payload = {"body": body, "subject": msg["subject"][:300] or None, "message_id": msg["message_id"],
               "in_reply_to": msg["in_reply_to"], "channel": "email"}
    if is_auto_reply(msg):
        payload["auto_reply"] = True
    return {"ok": True, "kind": "reply", "error": None,
            "event": {"event_id": _event_id(msg), "type": "email_replied", "actor": "prospect", "source": source,
                      "lead_ref": {"email": msg["from_email"]},
                      "payload": {k: v for k, v in payload.items() if v is not None}}}
