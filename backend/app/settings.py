"""Process settings from the environment (and an optional backend/.env file).

Business rules live in config/*.yaml; this file only holds deployment knobs: run mode, database, secrets.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODES = ("demo", "live")


def load_dotenv(path: Path = BACKEND_DIR / ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines, # comments. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    mode: str                 # demo: seeded simulator on a SimClock · live: wall clock, real events only
    persist: bool
    db_url: str | None        # None → SQLite file at LEADPILOT_DB (default backend/var/leadpilot.db)
    db_schema: str            # Postgres schema for LeadPilot's tables (tests use their own)
    warmup_days: int | None
    allow_mode_switch: bool   # override the demo/live database guard (runtime.ensure_mode)
    auth: bool                # require a login / API key on every endpoint except health and auth config
    supabase_url: str | None
    supabase_anon_key: str | None
    jwt_secret: str | None    # legacy HS256 projects (and tests); new projects verify via the JWKS endpoint
    admin_emails: frozenset   # these users are always admins (bootstraps the first admin)

    @property
    def live(self) -> bool:
        return self.mode == "live"


def supabase_url_from_db(db_url: str | None) -> str | None:
    """Supabase pooler usernames are postgres.<project-ref>: that ref names the project's API URL."""
    if not db_url or "supabase.com" not in db_url:
        return None
    from sqlalchemy.engine import make_url
    user = make_url(db_url.replace("postgres://", "postgresql://", 1)).username or ""
    ref = user.split(".", 1)[1] if "." in user else None
    return f"https://{ref}.supabase.co" if ref else None


def _real(value: str | None) -> str | None:
    """Ignore unset values and untouched .env.example placeholders like https://<project-ref>.supabase.co."""
    return value.strip() if value and value.strip() and "<" not in value else None


def get_settings() -> Settings:
    load_dotenv()
    mode = os.environ.get("LEADPILOT_MODE", "demo").strip().lower()
    if mode not in MODES:
        raise ValueError(f"LEADPILOT_MODE must be one of {MODES}, got {mode!r}")
    warmup = os.environ.get("LEADPILOT_WARMUP_DAYS")
    db_url = os.environ.get("LEADPILOT_DB_URL") or None
    supabase_url = _real(os.environ.get("SUPABASE_URL")) or supabase_url_from_db(db_url)
    jwt_secret = _real(os.environ.get("SUPABASE_JWT_SECRET"))
    auth_env = os.environ.get("LEADPILOT_AUTH", "auto").strip().lower()
    if auth_env not in ("auto", "on", "off"):
        raise ValueError("LEADPILOT_AUTH must be auto, on or off")
    auth = auth_env == "on" or (auth_env == "auto" and bool(supabase_url or jwt_secret))
    if mode == "live" and not auth and auth_env != "off":
        raise ValueError("Live mode needs authentication: configure Supabase (SUPABASE_URL / LEADPILOT_DB_URL) "
                         "or set LEADPILOT_AUTH=off explicitly for a private network.")
    if auth and not (supabase_url or jwt_secret):
        raise ValueError("LEADPILOT_AUTH=on needs SUPABASE_URL (or SUPABASE_JWT_SECRET) to verify logins")
    return Settings(
        mode=mode,
        persist=os.environ.get("LEADPILOT_PERSIST", "1") != "0",
        db_url=db_url,
        db_schema=os.environ.get("LEADPILOT_DB_SCHEMA", "public"),
        warmup_days=int(warmup) if warmup else None,
        allow_mode_switch=os.environ.get("LEADPILOT_ALLOW_MODE_SWITCH") == "1",
        auth=auth,
        supabase_url=supabase_url.rstrip("/") if supabase_url else None,
        supabase_anon_key=_real(os.environ.get("SUPABASE_ANON_KEY")),
        jwt_secret=jwt_secret,
        admin_emails=frozenset(e.strip().lower() for e in os.environ.get("LEADPILOT_ADMIN_EMAILS", "").split(",")
                               if e.strip()),
    )
