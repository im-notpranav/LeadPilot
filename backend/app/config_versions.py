"""Settings versions: rule changes stored on top of backend/config/*.yaml.

A version holds only what differs from the YAML defaults, so the files stay the documented baseline and a code
update that adds a new default reaches every version. Exactly one version is active. Activating one swaps the
rules everywhere and replays the raw event log, so every score, stage, assignment and deal is a function of
(event log, active version). Nothing is ever edited in place: a rollback restores an old version as a new one.

Before a version is saved it must (1) keep the shape of the defaults (no typos, no deleted settings, numbers stay
numbers), (2) load (derived tables build), and (3) process sample events in a scratch engine without errors.
"""
from __future__ import annotations

import copy
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlalchemy import select

from .config import CONFIG_DIR, EDITABLE_SECTIONS, load_config, merge_overrides, read_sections
from .models import tables as T

log = logging.getLogger("leadpilot.config")

SECTION_LABELS = {"scoring": "Scoring", "pipeline": "Pipeline and deals", "assignment": "Assignment",
                  "quality": "Quality and duplicates", "nba": "Next best actions", "quotes": "Quotes"}
DRY_RUN_EVENTS = 400
_SAME = object()


class ConfigError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ================================================================================================ YAML in and out
def to_yaml(section: dict) -> str:
    return yaml.safe_dump(section, sort_keys=False, allow_unicode=True, default_flow_style=None, width=110)


def parse_yaml(name: str, text: str) -> dict:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise ConfigError([f"{name}: this is not valid YAML{where} ({getattr(e, 'problem', None) or e})"]) from None
    if not isinstance(data, dict):
        raise ConfigError([f"{name}: expected a list of settings (key: value lines)"])
    return data


# ================================================================================================ shape checks
def _kind(v) -> str:
    if isinstance(v, bool):
        return "true or false"
    if isinstance(v, (int, float)):
        return "a number"
    if isinstance(v, str):
        return "text"
    if isinstance(v, list):
        return "a list"
    if isinstance(v, dict):
        return "a group of settings"
    return "empty" if v is None else type(v).__name__


def check_shape(new, default, path: str, errors: list[str]) -> None:
    """`new` must look like `default`: same keys (none missing, none unknown) and the same kind of value."""
    if default is None:
        return
    if isinstance(default, dict):
        if not isinstance(new, dict):
            errors.append(f"{path}: must be {_kind(default)}, not {_kind(new)}")
            return
        for k in default:
            if k not in new:
                errors.append(f"{path}.{k}: is missing (settings cannot be deleted; set it to 0, false or [] instead)")
        for k in new:
            if k not in default:
                errors.append(f"{path}.{k}: is not a known setting (check the spelling)")
            else:
                check_shape(new[k], default[k], f"{path}.{k}", errors)
        return
    if isinstance(default, bool):
        ok = isinstance(new, bool)
    elif isinstance(default, (int, float)):
        ok = isinstance(new, (int, float)) and not isinstance(new, bool)
    elif isinstance(default, str):
        ok = isinstance(new, str)
    elif isinstance(default, list):
        ok = isinstance(new, list)
        if ok and default and all(isinstance(x, dict) for x in default):
            for i, item in enumerate(new):
                if not isinstance(item, dict):
                    errors.append(f"{path}[{i}]: must be {_kind(default[0])}, not {_kind(item)}")
        elif ok and default:
            want = {_kind(x) for x in default}
            for i, item in enumerate(new):
                if _kind(item) not in want:
                    errors.append(f"{path}[{i}]: must be {' or '.join(sorted(want))}, not {_kind(item)}")
    else:
        ok = True
    if not ok:
        errors.append(f"{path}: must be {_kind(default)}, not {_kind(new)}")


# ================================================================================================ diffs
def overrides_between(default, new):
    """What `new` changes relative to `default`: nested groups recurse, anything else is replaced whole."""
    if isinstance(default, dict) and isinstance(new, dict):
        out = {}
        for k, v in new.items():
            d = overrides_between(default[k], v) if k in default else copy.deepcopy(v)
            if d is not _SAME:
                out[k] = d
        return out if out else _SAME
    return _SAME if new == default else copy.deepcopy(new)


def diff(before: dict, after: dict, path: str = "") -> list[dict]:
    """Every setting that differs, as {path, before, after}. Lists are compared whole."""
    rows: list[dict] = []
    for k in list(before) + [k for k in after if k not in before]:
        p = f"{path}.{k}" if path else str(k)
        b, a = before.get(k, _SAME), after.get(k, _SAME)
        if isinstance(b, dict) and isinstance(a, dict):
            rows += diff(b, a, p)
        elif b != a:
            rows.append({"path": p, "before": None if b is _SAME else b, "after": None if a is _SAME else a})
    return rows


# ================================================================================================ dry run
def _sample_events() -> list[dict]:
    """A short, complete journey: new lead, engagement, demo, reply, meeting, proposal, a tick, and a duplicate."""
    lead = {"email": "dry.run@settings-check.example"}
    t = lambda h: f"2026-01-05T{h:02d}:00:00Z"   # noqa: E731
    return [
        {"event_id": "dry-1", "type": "lead_created", "ts": t(9), "source": "website", "payload": {
            "name": "Dry Run", "email": lead["email"], "title": "VP Operations", "company": "Settings Check",
            "country": "US", "form_fill_seconds": 40}},
        {"event_id": "dry-2", "type": "page_view", "ts": t(10), "lead_ref": lead, "payload": {"page_category": "pricing"}},
        {"event_id": "dry-3", "type": "demo_request", "ts": t(11), "lead_ref": lead},
        {"event_id": "dry-4", "type": "email_replied", "ts": t(12), "lead_ref": lead,
         "payload": {"body": "Yes, interested. What does pricing look like?"}},
        {"event_id": "dry-5", "type": "meeting_held", "ts": t(13), "actor": "rep", "lead_ref": lead,
         "payload": {"meeting_type": "demo"}},
        {"event_id": "dry-6", "type": "proposal_sent", "ts": t(14), "actor": "rep", "lead_ref": lead,
         "payload": {"amount": 30000}},
        {"event_id": "dry-7", "type": "time_tick", "ts": t(20), "actor": "system"},
        {"event_id": "dry-8", "type": "lead_created", "ts": t(21), "source": "referral", "payload": {
            "name": "Dry Run", "email": lead["email"], "company": "Settings Check", "country": "US",
            "form_fill_seconds": 30}},
    ]


def dry_run(cfg, raw_events: list[dict], historical: list[dict], limit: int = DRY_RUN_EVENTS) -> int:
    """Process sample events with `cfg` in a scratch engine (nothing shared, nothing written). Raises ConfigError."""
    from .persistence import NullPersistence
    from .processor import Processor
    from .store import Store
    done = 0
    for sample in (_sample_events(), [dict(r) for r in raw_events[:limit]]):
        if not sample:
            continue
        store = Store(cfg)
        store.historical = list(historical)
        store.raw_log = sample
        try:
            Processor(cfg, store, None, NullPersistence()).replay(write=False)
        except Exception as e:  # noqa: BLE001 - any failure means these rules cannot run
            log.info("settings dry run failed", exc_info=True)
            raise ConfigError([f"these settings fail when processing events: {type(e).__name__}: {e}"]) from None
        done += len(sample)
    return done


# ================================================================================================ store
class ConfigStore:
    """The versions, cached in memory and written straight to the database (they change rarely)."""

    def __init__(self, db, base_overrides: dict | None = None, config_dir: Path = CONFIG_DIR):
        self.db = db
        self.base = base_overrides or {}
        self.config_dir = config_dir
        files = read_sections(config_dir)
        self.defaults = {k: files[k] for k in EDITABLE_SECTIONS}
        self.versions: dict[int, dict] = {}
        self._lock = threading.Lock()
        if getattr(db, "enabled", False):
            with db.engine.connect() as conn:
                self.versions = {r["id"]: dict(r) for r in conn.execute(select(T.config_versions)).mappings()}

    # ---------------------------------------------------------------- persistence
    def _save(self, *rows: dict) -> None:
        if getattr(self.db, "enabled", False):
            self.db.write_rows("config_versions", [dict(r) for r in rows])

    def ensure_initial(self) -> dict:
        """First start: version 1 is the YAML files as they are. Always leaves exactly one active version."""
        with self._lock:
            if not self.versions:
                row = {"id": 1, "note": "Starting rules from the YAML files", "overrides": {},
                       "fingerprint": self.build({}).fingerprint, "status": "active", "restored_from": None,
                       "created_by": "system", "created_at": _now(), "activated_by": "system",
                       "activated_at": _now(), "retired_at": None}
                self.versions[1] = row
                self._save(row)
            if not any(v["status"] == "active" for v in self.versions.values()):
                row = self.versions[max(self.versions)]
                row.update(status="active", activated_by="system", activated_at=_now())
                self._save(row)
            return self.active()

    # ---------------------------------------------------------------- reading
    def active(self) -> dict:
        return next(v for v in self.versions.values() if v["status"] == "active")

    def get(self, vid: int) -> dict | None:
        return self.versions.get(vid)

    def previous(self, vid: int) -> dict | None:
        older = [i for i in self.versions if i < vid]
        return self.versions[max(older)] if older else None

    def effective(self, overrides: dict) -> dict:
        """The editable sections with `overrides` applied (fresh copies)."""
        merged = merge_overrides(self.defaults, {k: v for k, v in (overrides or {}).items() if k in self.defaults})
        return {k: merged.get(k, {}) for k in EDITABLE_SECTIONS}

    def build(self, overrides: dict):
        return load_config(self.config_dir, overrides=merge_overrides(self.base, overrides))

    def changes(self, row: dict, against: dict | None) -> list[dict]:
        before = self.effective(against["overrides"] if against else {})
        return diff(before, self.effective(row["overrides"]))

    # ---------------------------------------------------------------- writing
    def validate(self, texts: dict[str, str], base: dict | None = None) -> tuple[dict, object]:
        """Parse edited sections (YAML text) on top of `base` overrides (default: the active version).
        Returns (overrides, cfg). Raises ConfigError with every problem found."""
        base = self.active()["overrides"] if base is None else base
        effective = self.effective(base)
        errors: list[str] = []
        for name, text in texts.items():
            if name not in self.defaults:
                errors.append(f"{name}: is not an editable section ({', '.join(EDITABLE_SECTIONS)})")
                continue
            try:
                data = parse_yaml(name, text)
            except ConfigError as e:
                errors += e.errors
                continue
            check_shape(data, self.defaults[name], name, errors)
            effective[name] = data
        if errors:
            raise ConfigError(errors)
        overrides = {}
        for name in EDITABLE_SECTIONS:
            d = overrides_between(self.defaults[name], effective[name])
            if d is not _SAME:
                overrides[name] = d
        try:
            cfg = self.build(overrides)
        except Exception as e:  # noqa: BLE001 - a derived table could not be built from these values
            raise ConfigError([f"these settings cannot be loaded: {type(e).__name__}: {e}"]) from None
        return overrides, cfg

    def create(self, overrides: dict, note: str | None, by: str | None, fingerprint: str,
               restored_from: int | None = None) -> dict:
        with self._lock:
            vid = max(self.versions, default=0) + 1
            row = {"id": vid, "note": (note or "").strip()[:500] or None, "overrides": copy.deepcopy(overrides),
                   "fingerprint": fingerprint, "status": "draft", "restored_from": restored_from,
                   "created_by": by, "created_at": _now(), "activated_by": None, "activated_at": None,
                   "retired_at": None}
            self.versions[vid] = row
            self._save(row)
            return row

    def mark_active(self, vid: int, by: str | None) -> dict | None:
        """Record that `vid` is now the active version (call after the runtime switched). Returns the old one."""
        with self._lock:
            old = self.active()
            if old["id"] == vid:
                return None
            now = _now()
            old.update(status="retired", retired_at=now)
            new = self.versions[vid]
            new.update(status="active", activated_by=by, activated_at=now, retired_at=None)
            self._save(old, new)
            return old
