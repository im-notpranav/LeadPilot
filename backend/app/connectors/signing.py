"""Webhook signatures, in the style of Stripe and Slack.

The sender sends two headers:

    X-LeadPilot-Timestamp: 1760086800                     (unix seconds)
    X-LeadPilot-Signature: v1=<hex HMAC-SHA256 of "{timestamp}.{raw body}" keyed with the connector secret>

LeadPilot rejects a bad signature, a timestamp more than TOLERANCE seconds away from now, and the exact same
signed request seen twice (a replay). Several `v1=` values may be sent, comma separated, while rotating secrets.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import time

TOLERANCE = 300            # seconds either side of now
SCHEME = "v1"


class SignatureError(Exception):
    def __init__(self, reason: str, status: int = 401):
        super().__init__(reason)
        self.reason = reason
        self.status = status


def sign(secret: str, timestamp: int | str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"{SCHEME}={mac.hexdigest()}"


def signed_headers(secret: str, body: bytes, timestamp: int | None = None) -> dict:
    """What a sender (or a test) puts on the request."""
    ts = int(time.time()) if timestamp is None else timestamp
    return {"X-LeadPilot-Timestamp": str(ts), "X-LeadPilot-Signature": sign(secret, ts, body)}


class ReplayGuard:
    """Remembers signatures seen inside the tolerance window. In memory: after a restart the timestamp check
    still bounds replays to the window, and event ids make re-delivered events no-ops anyway."""

    def __init__(self, window: int = 2 * TOLERANCE):
        self.window = window
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_remember(self, key: str, now: float) -> bool:
        """True the first time `key` is seen inside the window."""
        with self._lock:
            if len(self._seen) > 10_000:
                cutoff = now - self.window
                self._seen = {k: t for k, t in self._seen.items() if t > cutoff}
            seen = self._seen.get(key)
            if seen is not None and now - seen < self.window:
                return False
            self._seen[key] = now
            return True


def verify(secret: str, headers, body: bytes, guard: ReplayGuard | None = None, now: float | None = None) -> None:
    """Raise SignatureError unless the request carries a fresh, valid, never-seen signature for `secret`."""
    now = time.time() if now is None else now
    ts_raw = headers.get("x-leadpilot-timestamp")
    sig_raw = headers.get("x-leadpilot-signature")
    if not ts_raw or not sig_raw:
        raise SignatureError("missing X-LeadPilot-Timestamp / X-LeadPilot-Signature headers")
    try:
        ts = int(ts_raw)
    except ValueError:
        raise SignatureError("X-LeadPilot-Timestamp must be unix seconds") from None
    if abs(now - ts) > TOLERANCE:
        raise SignatureError(f"timestamp is more than {TOLERANCE}s from server time (clock skew or an old request)")
    expected = sign(secret, ts, body)
    offered = [s.strip() for s in sig_raw.split(",") if s.strip().startswith(f"{SCHEME}=")]
    if not any(hmac.compare_digest(expected, s) for s in offered):
        raise SignatureError("signature does not match: check the secret and sign the exact raw body")
    if guard is not None and not guard.check_and_remember(expected, now):
        raise SignatureError("this exact signed request was already received (replay)", status=409)


def token_matches(secret: str, offered: str | None) -> bool:
    return bool(offered) and hmac.compare_digest(secret.encode(), offered.encode())
