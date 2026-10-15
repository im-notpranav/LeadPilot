"""Health, auth configuration, the signed-in user, and admin management of people and API keys."""
from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import ROLES, Principal
from ..engine.types import iso
from .deps import state
from .security import admin, any_user

public = APIRouter(prefix="/api")
me_router = APIRouter(prefix="/api")
admin_router = APIRouter(prefix="/api/admin", dependencies=[Depends(admin)])


@public.get("/health")
async def health():
    rt = state.runtime
    # ok: the process is up (platform health checks); ready: the world is built (demo reset / live rebuild done)
    return {"ok": True, "ready": bool(rt and rt.status == "ready"), "status": rt.status if rt else "starting",
            "mode": ("live" if rt.live else "demo") if rt else None,
            "auth": bool(state.settings and state.settings.auth), "db": rt.db.status() if rt else None}


@public.get("/auth/config")
async def auth_config():
    """What the dashboard needs to show a login screen. The anon key is public by design (RLS guards data)."""
    s = state.settings
    return {"enabled": s.auth, "supabase_url": s.supabase_url if s.auth else None,
            "anon_key": s.supabase_anon_key if s.auth else None,
            "login_ready": bool(s.auth and s.supabase_url and s.supabase_anon_key)}


@me_router.get("/me")
async def me(p: Principal = Depends(any_user)):
    rep = state.runtime.store.reps.get(p.rep_id) if p.rep_id else None
    return {**p.to_dict(), "rep_name": rep["name"] if rep else None, "auth": state.settings.auth}


# ---------------------------------------------------------------------------------------------- people
def _profile_view(prof: dict) -> dict:
    return {k: (iso(v) if isinstance(v, datetime) else v) for k, v in prof.items()}


@admin_router.get("/users")
async def list_users():
    return {"items": [_profile_view(p) for p in state.accounts.list_profiles()],
            "admin_emails": sorted(state.settings.admin_emails)}


@admin_router.patch("/users/{user_id}")
async def update_user(user_id: str, body: dict = Body(...), p: Principal = Depends(admin)):
    changes = {k: body[k] for k in ("role", "rep_id", "team_rep_ids", "name") if k in body}
    if "role" in changes and changes["role"] not in ROLES:
        raise HTTPException(422, f"role must be one of {ROLES}")
    reps = state.runtime.store.reps
    if changes.get("rep_id") is not None and changes["rep_id"] not in reps:
        raise HTTPException(422, "unknown rep_id")
    team = changes.get("team_rep_ids")
    if team is not None and (not isinstance(team, list) or any(r not in reps for r in team)):
        raise HTTPException(422, "team_rep_ids must be a list of known rep ids, or null for all reps")
    if user_id == p.user_id and changes.get("role", "admin") != "admin":
        raise HTTPException(409, "you cannot remove your own admin role")
    try:
        prof = await asyncio.to_thread(state.accounts.update_profile, user_id, changes)
    except KeyError:
        raise HTTPException(404, "user not found") from None
    return _profile_view(prof)


# ---------------------------------------------------------------------------------------------- API keys
@admin_router.get("/api-keys")
async def list_keys():
    return {"items": [_profile_view(k) for k in state.accounts.list_keys()]}


@admin_router.post("/api-keys")
async def create_key(body: dict = Body(...), p: Principal = Depends(admin)):
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "give the key a name, e.g. 'Website forms'")
    row, secret = await asyncio.to_thread(state.accounts.create_key, name[:80], p.email or p.name)
    view = _profile_view({k: v for k, v in row.items() if k != "key_hash"})
    return {**view, "secret": secret, "note": "Copy this key now. It is stored hashed and cannot be shown again."}


@admin_router.delete("/api-keys/{key_id}")
async def revoke_key(key_id: str):
    try:
        row = await asyncio.to_thread(state.accounts.revoke_key, key_id)
    except KeyError:
        raise HTTPException(404, "API key not found") from None
    return _profile_view({k: v for k, v in row.items() if k != "key_hash"})
