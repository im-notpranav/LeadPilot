"""Postgres schema migrations: plain SQL files in supabase/migrations/, applied in filename order on startup.

Applied versions are recorded in `leadpilot_migrations` inside the target schema. Files are written to be
idempotent (IF NOT EXISTS), so the Supabase CLI (`supabase db push`) can apply the same folder safely.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text

log = logging.getLogger("leadpilot.migrate")

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(directory.glob("*.sql"))


def apply_migrations(engine, schema: str = "public", directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in one transaction under an advisory lock. Returns the versions applied now."""
    applied: list[str] = []
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('leadpilot_migrations'))"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS leadpilot_migrations ("
                          "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"))
        done = {r[0] for r in conn.execute(text("SELECT version FROM leadpilot_migrations"))}
        for path in migration_files(directory):
            version = path.stem
            if version in done:
                continue
            cur = conn.connection.cursor()          # raw cursor: a file holds many statements, no parameters
            cur.execute(path.read_text(encoding="utf-8"))
            cur.close()
            conn.execute(text("INSERT INTO leadpilot_migrations (version) VALUES (:v)"), {"v": version})
            applied.append(version)
            log.info("applied migration %s to schema %s", version, schema)
    return applied
