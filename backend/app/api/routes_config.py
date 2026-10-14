"""Settings console: view the rules in force, save edited rules as a new version, activate it, roll back.

Managers can look; only admins change anything. Activating a version replays the whole event log under it,
so the API is busy (requests wait) for as long as a replay takes.
"""
from __future__ import annotations

import asyncio
import logging
import time

from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import Principal
from ..config import EDITABLE_SECTIONS
from ..config_versions import SECTION_LABELS, ConfigError, diff, dry_run, to_yaml
from ..engine.types import iso
from .deps import state
from .security import admin, manager

log = logging.getLogger("leadpilot.config")

router = APIRouter(prefix="/api/config", dependencies=[Depends(manager)])


def _who(p: Principal) -> str | None:
    return p.email or p.name or p.kind


def _view(row: dict) -> dict:
    cs = state.config
    prev = cs.previous(row["id"])
    return {
        "id": row["id"], "note": row["note"], "status": row["status"], "restored_from": row["restored_from"],
        "created_by": row["created_by"], "created_at": iso(row["created_at"]),
        "activated_by": row["activated_by"], "activated_at": iso(row["activated_at"]),
        "retired_at": iso(row["retired_at"]), "fingerprint": row["fingerprint"],
        "sections_changed": [s for s in EDITABLE_SECTIONS if row["overrides"].get(s)],
        "changes_from_defaults": len(cs.changes(row, None)),
        "changes_from_previous": len(cs.changes(row, prev)) if prev else None,
    }


def _sections(overrides: dict) -> list[dict]:
    cs = state.config
    eff = cs.effective(overrides)
    return [{"name": s, "label": SECTION_LABELS[s], "yaml": to_yaml(eff[s]), "changed": bool(overrides.get(s)),
             "file": (cs.config_dir / f"{s}.yaml").read_text(encoding="utf-8")} for s in EDITABLE_SECTIONS]


def _row_or_404(vid: int) -> dict:
    row = state.config.get(vid)
    if row is None:
        raise HTTPException(404, f"settings version {vid} not found")
    return row


def _bad(e: ConfigError) -> HTTPException:
    return HTTPException(422, "\n".join(e.errors))


async def _check(texts: dict[str, str]) -> tuple[dict, object, int]:
    """Validate edited sections and dry-run them on sample events. Returns (overrides, cfg, events checked)."""
    if not isinstance(texts, dict) or not texts:
        raise HTTPException(422, "send the edited sections as {\"sections\": {\"scoring\": \"<yaml>\", ...}}")
    try:
        overrides, cfg = state.config.validate({str(k): str(v) for k, v in texts.items()})
    except ConfigError as e:
        raise _bad(e) from None
    async with state.lock:                        # a consistent snapshot; the dry run itself runs outside the lock
        raw, hist = list(state.runtime.store.raw_log), list(state.runtime.store.historical)
    try:
        checked = await asyncio.to_thread(dry_run, cfg, raw, hist)
    except ConfigError as e:
        raise _bad(e) from None
    return overrides, cfg, checked


async def _activate(row: dict, p: Principal) -> dict:
    cs, rt = state.config, state.runtime
    if row["status"] == "active":
        raise HTTPException(409, f"version {row['id']} is already active")
    cfg = cs.build(row["overrides"])
    t0 = time.monotonic()
    async with state.lock:
        old_cfg, old_version = rt.cfg, rt.processor.config_version
        try:
            result = await asyncio.to_thread(rt.apply_config, cfg, row["id"])
        except Exception:  # noqa: BLE001 - put the previous rules back so the engine keeps a consistent state
            log.exception("activating settings version %s failed; restoring version %s", row["id"], old_version)
            await asyncio.to_thread(rt.apply_config, old_cfg, old_version)
            raise HTTPException(500, f"activating version {row['id']} failed, so version {old_version} is "
                                     "still in force. The server log has the details.") from None
        rt.processor.drain_outbox()
        cs.mark_active(row["id"], _who(p))
    await state.ws.broadcast([{"type": "sim.reset", "data": {"reason": "settings", "version": row["id"]}}])
    log.info("settings version %s activated by %s", row["id"], _who(p))
    return {"version": _view(row), "replayed_events": result.get("replayed_events", 0),
            "seconds": round(time.monotonic() - t0, 1)}


# ================================================================================================ reading
@router.get("")
async def current(p: Principal = Depends(manager)):
    cs = state.config
    row = cs.active()
    return {"active": _view(row), "sections": _sections(row["overrides"]), "can_edit": p.role == "admin",
            "engine_version": state.runtime.processor.config_version, "versions": len(cs.versions)}


@router.get("/versions")
async def versions():
    return {"items": [_view(r) for r in sorted(state.config.versions.values(), key=lambda r: -r["id"])]}


@router.get("/versions/{vid}")
async def version(vid: int):
    cs = state.config
    row = _row_or_404(vid)
    prev, active = cs.previous(vid), cs.active()
    return {**_view(row), "sections": _sections(row["overrides"]),
            "changes": cs.changes(row, prev), "changes_vs_active": cs.changes(row, active),
            "previous_id": prev["id"] if prev else None}


# ================================================================================================ changing
@router.post("/check", dependencies=[Depends(admin)])
async def check(body: dict = Body(...)):
    overrides, _, checked = await _check(body.get("sections"))
    cs = state.config
    return {"ok": True, "events_checked": checked,
            "changes": diff(cs.effective(cs.active()["overrides"]), cs.effective(overrides))}


@router.post("/versions")
async def create(body: dict = Body(...), p: Principal = Depends(admin)):
    cs = state.config
    overrides, cfg, _ = await _check(body.get("sections"))
    if not diff(cs.effective(cs.active()["overrides"]), cs.effective(overrides)):
        raise HTTPException(422, "nothing changed compared with the active version")
    row = cs.create(overrides, body.get("note"), _who(p), cfg.fingerprint)
    if body.get("activate"):
        return await _activate(row, p)
    return {"version": _view(row)}


@router.post("/versions/{vid}/activate")
async def activate(vid: int, p: Principal = Depends(admin)):
    row = _row_or_404(vid)
    if row["status"] == "retired":
        raise HTTPException(409, "this version was in force before; roll back to it instead, which saves it as a "
                                 "new version so the history stays in order")
    return await _activate(row, p)


@router.post("/versions/{vid}/restore")
async def restore(vid: int, body: dict = Body(default={}), p: Principal = Depends(admin)):
    """Roll back: save an older version's rules as a new version (and, by default, activate it)."""
    cs = state.config
    old = _row_or_404(vid)
    if old["status"] == "active":
        raise HTTPException(409, f"version {vid} is already active")
    texts = {s: to_yaml(sec) for s, sec in cs.effective(old["overrides"]).items()}
    overrides, cfg, _ = await _check(texts)
    row = cs.create(overrides, body.get("note") or f"Rolled back to version {vid}", _who(p), cfg.fingerprint,
                    restored_from=vid)
    if body.get("activate", True):
        return await _activate(row, p)
    return {"version": _view(row)}
