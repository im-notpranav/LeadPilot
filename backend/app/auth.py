"""Authentication and authorization: who is calling, and which leads they may see.

* People sign in with Supabase Auth; the dashboard sends the access token (a JWT). New Supabase projects sign
  tokens with ES256 keys published at /auth/v1/.well-known/jwks.json; legacy projects use an HS256 secret.
* LeadPilot keeps its own role for each person in `profiles` (admin | manager | rep | pending). New sign-ups are
  pending until an admin approves them; emails in LEADPILOT_ADMIN_EMAILS are always admins.
* Machines ingest events with API keys (`lp_…`); only a SHA-256 hash is stored.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

from .models import tables as T

log = logging.getLogger("leadpilot.auth")

ROLES = ("admin", "manager", "rep", "pending")
TOUCH_EVERY = timedelta(minutes=5)       # how often last_seen_at / last_used_at are written


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ====================================================================== principal
@dataclass(frozen=True)
class Principal:
    kind: str                            # user | api_key | dev
    role: str                            # admin | manager | rep | pending | ingest
    user_id: str | None = None
    email: str | None = None
    name: str | None = None
    rep_id: str | None = None
    team: frozenset | None = None        # managers: reps they oversee; None = all reps
    key_id: str | None = None

    @property
    def sees_all(self) -> bool:
        return self.role == "admin" or (self.role == "manager" and self.team is None)

    def can_see_owner(self, owner: str | None) -> bool:
        if self.sees_all:
            return True
        if self.role == "manager":
            return owner is None or owner in self.team
        if self.role == "rep":
            return self.rep_id is not None and owner == self.rep_id
        return False

    def can_see(self, lead) -> bool:
        return lead is not None and self.can_see_owner(lead.owner)

    def can_see_rep(self, rep_id: str | None) -> bool:
        if self.sees_all:
            return True
        if self.role == "manager":
            return rep_id in self.team
        return self.role == "rep" and rep_id == self.rep_id

    def to_dict(self) -> dict:
        return {"kind": self.kind, "role": self.role, "user_id": self.user_id, "email": self.email,
                "name": self.name, "rep_id": self.rep_id,
                "team_rep_ids": sorted(self.team) if self.team is not None else None}


DEV = Principal(kind="dev", role="admin", email=None, name="Local access (auth off)")


def principal_for(profile: dict) -> Principal:
    team = profile.get("team_rep_ids")
    return Principal(kind="user", role=profile["role"], user_id=profile["user_id"], email=profile.get("email"),
                     name=profile.get("name"), rep_id=profile.get("rep_id"),
                     team=frozenset(team) if team is not None else None)


# ====================================================================== tokens
class AuthError(Exception):
    pass


class TokenVerifier:
    def __init__(self, supabase_url: str | None, jwt_secret: str | None = None):
        self.issuer = f"{supabase_url}/auth/v1" if supabase_url else None
        self.secret = jwt_secret
        self.jwks = jwt.PyJWKClient(f"{supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True,
                                    lifespan=600) if supabase_url else None

    def verify(self, token: str) -> dict:
        """Return the token's claims, or raise AuthError. May fetch the JWKS (blocking): call off the event loop."""
        try:
            alg = jwt.get_unverified_header(token).get("alg")
            if alg == "HS256":
                if not self.secret:
                    raise AuthError("HS256 tokens need SUPABASE_JWT_SECRET")
                key = self.secret
            elif alg in ("ES256", "RS256", "EdDSA"):
                if self.jwks is None:
                    raise AuthError("asymmetric tokens need SUPABASE_URL")
                key = self.jwks.get_signing_key_from_jwt(token).key
            else:
                raise AuthError(f"unsupported token algorithm {alg!r}")
            return jwt.decode(token, key, algorithms=[alg], audience="authenticated", issuer=self.issuer,
                              options={"require": ["exp", "sub"], "verify_iss": self.issuer is not None})
        except AuthError:
            raise
        except jwt.PyJWTError as exc:
            raise AuthError(str(exc)) from exc


# ====================================================================== accounts
def hash_key(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


@dataclass
class AccountStore:
    """Profiles and API keys, cached in memory and written straight through to the database.

    These are low-volume writes that must be durable immediately, so they bypass the batched event writer.
    With persistence off they live in memory only.
    """
    db: object
    admin_emails: frozenset = frozenset()
    profiles: dict = field(default_factory=dict)
    keys: dict = field(default_factory=dict)

    def __post_init__(self):
        self._lock = threading.Lock()
        if getattr(self.db, "enabled", False):
            with self.db.engine.connect() as conn:
                self.profiles = {r["user_id"]: dict(r) for r in conn.execute(select(T.profiles)).mappings()}
                self.keys = {r["id"]: dict(r) for r in conn.execute(select(T.api_keys)).mappings()}
        self.by_hash: dict[str, dict] = {k["key_hash"]: k for k in self.keys.values()}

    def _save(self, table: str, row: dict) -> None:
        if getattr(self.db, "enabled", False):
            self.db.write_now(table, row)

    # ------------------------------------------------------------------ people
    def ensure_profile(self, user_id: str, email: str | None, name: str | None = None) -> dict:
        """The caller's profile, created on first sign-in (pending, or admin for bootstrap emails)."""
        email_l = (email or "").lower()
        with self._lock:
            prof = self.profiles.get(user_id)
            now = _now()
            dirty = False
            if prof is None:
                prof = {"user_id": user_id, "email": email_l or None, "name": name, "rep_id": None,
                        "team_rep_ids": None, "role": "admin" if email_l in self.admin_emails else "pending",
                        "created_at": now, "updated_at": now, "last_seen_at": now}
                self.profiles[user_id] = prof
                log.info("new %s profile for %s", prof["role"], email_l)
                dirty = True
            else:
                if email_l in self.admin_emails and prof["role"] != "admin":
                    prof.update(role="admin", updated_at=now)
                    dirty = True
                if email_l and prof.get("email") != email_l:
                    prof["email"] = email_l
                    dirty = True
                seen = prof.get("last_seen_at")
                if seen is None or now - _aware(seen) > TOUCH_EVERY:
                    prof["last_seen_at"] = now
                    dirty = True
            snapshot = dict(prof)
        if dirty:
            self._save("profiles", snapshot)
        return snapshot

    def update_profile(self, user_id: str, changes: dict) -> dict:
        allowed = {"role", "rep_id", "team_rep_ids", "name"}
        with self._lock:
            prof = self.profiles.get(user_id)
            if prof is None:
                raise KeyError(user_id)
            prof.update({k: v for k, v in changes.items() if k in allowed})
            if prof.get("email") in self.admin_emails:
                prof["role"] = "admin"          # bootstrap admins cannot be demoted from the UI
            if prof["role"] != "manager":
                prof["team_rep_ids"] = None
            if prof["role"] != "rep":
                prof["rep_id"] = None
            prof["updated_at"] = _now()
            snapshot = dict(prof)
        self._save("profiles", snapshot)
        return snapshot

    def list_profiles(self) -> list[dict]:
        with self._lock:
            return sorted((dict(p) for p in self.profiles.values()), key=lambda p: (p.get("email") or ""))

    # ------------------------------------------------------------------ API keys
    def create_key(self, name: str, created_by: str | None) -> tuple[dict, str]:
        secret = "lp_" + secrets.token_urlsafe(32)
        row = {"id": "key_" + secrets.token_hex(6), "name": name, "prefix": secret[:10], "key_hash": hash_key(secret),
               "created_by": created_by, "created_at": _now(), "last_used_at": None, "revoked_at": None}
        with self._lock:
            self.keys[row["id"]] = row
            self.by_hash[row["key_hash"]] = row
        self._save("api_keys", row)
        return dict(row), secret

    def revoke_key(self, key_id: str) -> dict:
        with self._lock:
            row = self.keys.get(key_id)
            if row is None:
                raise KeyError(key_id)
            row["revoked_at"] = row["revoked_at"] or _now()
            snapshot = dict(row)
        self._save("api_keys", snapshot)
        return snapshot

    def verify_key(self, secret: str) -> dict | None:
        with self._lock:
            row = self.by_hash.get(hash_key(secret))
            if row is None or row["revoked_at"] is not None:
                return None
            now = _now()
            touch = row["last_used_at"] is None or now - _aware(row["last_used_at"]) > TOUCH_EVERY
            if touch:
                row["last_used_at"] = now
            snapshot = dict(row)
        if touch:
            self._save("api_keys", snapshot)
        return snapshot

    def list_keys(self) -> list[dict]:
        with self._lock:
            return sorted(({k: v for k, v in r.items() if k != "key_hash"} for r in self.keys.values()),
                          key=lambda r: r["created_at"], reverse=True)


def _aware(ts: datetime) -> datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
