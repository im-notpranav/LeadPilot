"""Config loader: every weight, threshold, half-life and SLA lives in backend/config/*.yaml."""
from __future__ import annotations

import copy
import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml

BACKEND_DIR = Path(__file__).resolve().parents[1]
CONFIG_DIR = BACKEND_DIR / "config"
DATA_DIR = BACKEND_DIR / "data"
CONFIG_FILES = ("scoring", "pipeline", "assignment", "quality", "nba", "quotes", "simulator")
# What the settings console may change. The simulator only drives demo mode, so it stays file-only.
EDITABLE_SECTIONS = ("scoring", "pipeline", "assignment", "quality", "nba", "quotes")


class Cfg(dict):
    """dict with attribute access (cfg.scoring.fit). Nested dicts are converted once at load time."""

    __slots__ = ()

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @classmethod
    def wrap(cls, obj):
        if isinstance(obj, dict) and not isinstance(obj, Cfg):
            return cls({k: cls.wrap(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [cls.wrap(v) for v in obj]
        return obj


def _read_lines(path: Path) -> list[str]:
    return [ln.strip().lower() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]


def read_sections(config_dir: Path = CONFIG_DIR) -> dict:
    """The YAML files as plain dicts (fresh copies: callers may change them)."""
    return {name: yaml.safe_load((config_dir / f"{name}.yaml").read_text()) or {} for name in CONFIG_FILES}


def merge_overrides(*layers: dict | None) -> dict:
    """Combine override layers (later wins), e.g. environment overrides then a settings version."""
    out: dict = {}
    for layer in layers:
        for section, values in (layer or {}).items():
            _deep_update(out.setdefault(section, {}), copy.deepcopy(values))
    return out


def load_config(config_dir: Path = CONFIG_DIR, data_dir: Path = DATA_DIR, overrides: dict | None = None) -> Cfg:
    raw: dict = read_sections(config_dir)
    companies = json.loads((data_dir / "companies.json").read_text())
    raw["data"] = {
        "companies": {c["domain"]: c for c in companies},
        "reps": json.loads((data_dir / "reps.json").read_text()),
        "sources": json.loads((data_dir / "sources.json").read_text()),
        "disposable_domains": set(_read_lines(data_dir / "disposable_domains.txt")),
        "no_mx_domains": set(_read_lines(data_dir / "no_mx_domains.txt")),
        "ip_geo": json.loads((data_dir / "ip_geo.json").read_text()),
    }
    for section, values in (overrides or {}).items():
        _deep_update(raw.setdefault(section, {}), copy.deepcopy(values))
    fingerprint = hashlib.sha256(json.dumps(raw, sort_keys=True, default=_jsonable).encode()).hexdigest()[:16]
    cfg = Cfg.wrap(raw)
    cfg["fingerprint"] = fingerprint          # identifies the rules + reference data that produce projections
    _derive(cfg)
    return cfg


def _jsonable(obj):
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(type(obj).__name__)


def _deep_update(dst: dict, src: dict) -> None:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_update(dst[k], v)
        else:
            dst[k] = v


def _derive(cfg: Cfg) -> None:
    """Precompute lookup tables (still pure config, just indexed)."""
    country_region = {}
    for region, countries in cfg.assignment.regions.items():
        for c in countries:
            country_region[c] = region
    cfg["derived"] = Cfg(
        country_region=country_region,
        free_mail=set(cfg.quality.free_mail_domains),
        gmail=set(cfg.quality.gmail_domains),
        legal_suffixes=set(cfg.quality.legal_suffixes),
        forward_rank={s: i for i, s in enumerate(cfg.pipeline.forward_order)},
        inbound_types=set(cfg.pipeline.inbound_types),
        response_types=set(cfg.pipeline.response_types),
        rep_outbound_types=set(cfg.pipeline.rep_outbound_types),
        rep_activity_types=set(cfg.pipeline.rep_activity_types),
        terminal=set(cfg.pipeline.terminal),
        high_intent=set(cfg.scoring.high_intent_signals),
        nba_rules={r["id"]: r for r in cfg.nba.rules},
    )


@lru_cache(maxsize=1)
def default_config() -> Cfg:
    return load_config()
