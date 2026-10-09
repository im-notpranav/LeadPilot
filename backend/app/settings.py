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
    warmup_days: int | None

    @property
    def live(self) -> bool:
        return self.mode == "live"


def get_settings() -> Settings:
    load_dotenv()
    mode = os.environ.get("LEADPILOT_MODE", "demo").strip().lower()
    if mode not in MODES:
        raise ValueError(f"LEADPILOT_MODE must be one of {MODES}, got {mode!r}")
    warmup = os.environ.get("LEADPILOT_WARMUP_DAYS")
    return Settings(
        mode=mode,
        persist=os.environ.get("LEADPILOT_PERSIST", "1") != "0",
        db_url=os.environ.get("LEADPILOT_DB_URL") or None,
        warmup_days=int(warmup) if warmup else None,
    )
