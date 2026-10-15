"""Call payloads in, one common call record out: the Retell webhook, LeadPilot's own generic call format, and a
rep's own call notes. Also Retell's webhook signature and the rule-based analysis used when Gemini is not set up.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone

from ..engine.intent import classify_reply
from ..engine.types import iso, parse_ts
from .gemini import clean

RETELL_TOLERANCE_MS = 5 * 60 * 1000
VOICEMAIL_REASONS = {"voicemail_reached", "machine_detected"}
NO_ANSWER_REASONS = {"dial_no_answer", "dial_busy", "dial_failed", "invalid_destination", "registered_call_timeout"}
MAX_TRANSCRIPT = 200_000


class CallParseError(ValueError):
    pass


def _ms(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc) if v not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None


def _ts(v) -> datetime | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return _ms(v) if v > 10**11 else datetime.fromtimestamp(v, tz=timezone.utc)
    try:
        return parse_ts(str(v))
    except (TypeError, ValueError):
        return None


def _base(provider: str, call_id: str, **kw) -> dict:
    call = {"provider": provider, "provider_call_id": str(call_id), "direction": "outbound", "from_number": None,
            "to_number": None, "started_at": None, "ended_at": None, "duration_s": None, "transcript": "",
            "recording_url": None, "lead_ref": {}, "provider_analysis": {}, "disconnection_reason": None,
            "rep_id": None, "outcome_hint": None}
    call.update(kw)
    call["transcript"] = (call["transcript"] or "")[:MAX_TRANSCRIPT]
    call["direction"] = "inbound" if str(call["direction"] or "").lower() == "inbound" else "outbound"
    if call["duration_s"] is None and call["started_at"] and call["ended_at"]:
        call["duration_s"] = max(0.0, (call["ended_at"] - call["started_at"]).total_seconds())
    if not call["lead_ref"]:
        phone = call["to_number"] if call["direction"] == "outbound" else call["from_number"]
        if phone:
            call["lead_ref"] = {"phone": phone}
    return call


def _lead_ref(meta: dict) -> dict:
    ref = {}
    for k in ("lead_id", "email", "phone"):
        v = meta.get("lead_id") if k == "lead_id" else (meta.get(k) or meta.get(f"lead_{k}"))
        if v:
            ref[k] = str(v)
    return ref


# ================================================================================================ Retell
def parse_retell(body: dict) -> tuple[str, dict | None]:
    """(event name, call or None). Retell sends call_started, call_ended and call_analyzed for every call."""
    if not isinstance(body, dict) or not isinstance(body.get("call"), dict):
        raise CallParseError("expected a Retell webhook: {\"event\": ..., \"call\": {...}}")
    event, c = str(body.get("event") or ""), body["call"]
    if not c.get("call_id"):
        raise CallParseError("the Retell call has no call_id")
    meta = {**(c.get("retell_llm_dynamic_variables") or {}), **(c.get("metadata") or {})}
    analysis = c.get("call_analysis") or {}
    call = _base("retell", c["call_id"], direction=c.get("direction") or ("outbound" if c.get("to_number") else "inbound"),
                 from_number=c.get("from_number"), to_number=c.get("to_number"),
                 started_at=_ms(c.get("start_timestamp")), ended_at=_ms(c.get("end_timestamp")),
                 duration_s=(c["duration_ms"] / 1000) if isinstance(c.get("duration_ms"), (int, float)) else None,
                 transcript=c.get("transcript") or "", recording_url=c.get("recording_url"),
                 lead_ref=_lead_ref(meta), rep_id=meta.get("rep_id"),
                 disconnection_reason=c.get("disconnection_reason"),
                 provider_analysis={"summary": analysis.get("call_summary"),
                                    "sentiment": str(analysis.get("user_sentiment") or "").lower() or None,
                                    "in_voicemail": analysis.get("in_voicemail"),
                                    "successful": analysis.get("call_successful")})
    return event, call


def retell_signature_ok(api_key: str, raw: bytes, header: str | None, now_ms: int | None = None) -> bool:
    """Retell signs each webhook with your Retell API key: x-retell-signature: v=<ms timestamp>,d=<hex HMAC-SHA256
    of body + timestamp>. Checked against the raw body, then its compact JSON form (what Retell's SDK signs)."""
    m = re.fullmatch(r"v=(\d+),d=([0-9a-fA-F]+)", (header or "").strip())
    if not m or not api_key:
        return False
    stamp, digest = m.group(1), m.group(2).lower()
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    if abs(now_ms - int(stamp)) > RETELL_TOLERANCE_MS:
        return False
    bodies = [raw.decode("utf-8", "replace")]
    try:
        bodies.append(json.dumps(json.loads(raw), separators=(",", ":"), ensure_ascii=False))
    except ValueError:
        pass
    for b in bodies:
        mac = hmac.new(api_key.encode(), (b + stamp).encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(mac, digest):
            return True
    return False


def retell_sign(api_key: str, body: str, now_ms: int | None = None) -> str:
    """What Retell puts in x-retell-signature (used by tests and for trying the endpoint by hand)."""
    stamp = str(int(time.time() * 1000) if now_ms is None else now_ms)
    return f"v={stamp},d={hmac.new(api_key.encode(), (body + stamp).encode(), hashlib.sha256).hexdigest()}"


# ================================================================================================ generic + manual
def parse_generic(body: dict) -> dict:
    """LeadPilot's own call format, for any other phone system (or Zapier): one JSON object per call."""
    if not isinstance(body, dict):
        raise CallParseError("send one call as a JSON object")
    cid = body.get("call_id") or body.get("id")
    if not cid:
        raise CallParseError("each call needs a call_id")
    ref = {k: str(body[k]) for k in ("lead_id", "email", "phone") if body.get(k)}
    return _base(str(body.get("provider") or "generic")[:40], cid, direction=body.get("direction") or "outbound",
                 from_number=body.get("from") or body.get("from_number"), to_number=body.get("to") or body.get("to_number"),
                 started_at=_ts(body.get("started_at")), ended_at=_ts(body.get("ended_at")),
                 duration_s=float(body["duration_s"]) if isinstance(body.get("duration_s"), (int, float)) else None,
                 transcript=str(body.get("transcript") or ""), recording_url=body.get("recording_url"),
                 lead_ref=ref, rep_id=body.get("rep_id"),
                 outcome_hint=body.get("outcome") if body.get("outcome") in ("connected", "voicemail", "no_answer") else None,
                 provider_analysis={"summary": body.get("summary"), "sentiment": body.get("sentiment")})


def manual_call(lead_id: str, rep_id: str | None, body: dict, now: datetime) -> dict:
    """A call a rep logs by hand from the lead page: their notes (or a pasted transcript) and, optionally, the outcome."""
    notes = str(body.get("notes") or "").strip()
    minutes = body.get("duration_minutes")
    duration = float(minutes) * 60 if isinstance(minutes, (int, float)) and minutes >= 0 else None
    outcome = body.get("outcome") if body.get("outcome") in ("connected", "voicemail", "no_answer") else None
    if not notes and outcome is None:
        raise CallParseError("add your notes or pick how the call went")
    cid = "manual-" + hashlib.sha256(f"{lead_id}|{iso(now)}|{notes}".encode()).hexdigest()[:16]
    return _base("manual", cid, direction=body.get("direction") or "outbound", ended_at=now,
                 started_at=now, duration_s=duration, transcript=notes, lead_ref={"lead_id": lead_id},
                 rep_id=rep_id, outcome_hint=outcome)


# ================================================================================================ rule-based analysis
def prospect_text(transcript: str) -> str:
    """The prospect's side of a transcript ('User:' / 'Customer:' / 'Prospect:' lines), or all of it."""
    lines = [ln.split(":", 1)[1] for ln in transcript.splitlines()
             if re.match(r"\s*(user|customer|prospect|caller|lead)\s*:", ln, re.I)]
    return " ".join(lines) if lines else transcript


def rule_analysis(call: dict, cfg) -> dict:
    """No Gemini: the provider's own analysis where it has one, keywords for intent, the hang-up reason for the
    outcome. Deterministic, so it can be tested and is honest about being rough."""
    pa = call.get("provider_analysis") or {}
    reason = call.get("disconnection_reason")
    talk = prospect_text(call.get("transcript") or "").strip()
    if call.get("outcome_hint"):
        outcome = call["outcome_hint"]
    elif reason in VOICEMAIL_REASONS or pa.get("in_voicemail"):
        outcome = "voicemail"
    elif reason in NO_ANSWER_REASONS or (not talk and (call.get("duration_s") or 0) < 15):
        outcome = "no_answer"
    else:
        outcome = "connected"
    cls = classify_reply(talk, cfg) if talk else "neutral"
    intent = cls if cls in ("positive_intent", "objection", "negative") else "neutral"
    result = {"positive_intent": "interested", "negative": "not_interested"}.get(intent, "needs_info")
    sentiment = pa.get("sentiment") if pa.get("sentiment") in ("positive", "neutral", "negative") else (
        "positive" if intent == "positive_intent" else "negative" if intent == "negative" else "neutral")
    summary = pa.get("summary") or ""
    if not summary and call.get("provider") == "manual" and call.get("transcript"):     # a rep's notes are the summary
        notes = " ".join(call["transcript"].split())
        summary = notes if len(notes) <= 400 else notes[:380].rsplit(" ", 1)[0] + " …"
    return clean({"summary": summary, "outcome": outcome, "result": result, "sentiment": sentiment,
                  "call_intent": intent, "meeting_booked": False, "next_step": "", "buying_signals": [],
                  "objections": [], "competitors": []})
