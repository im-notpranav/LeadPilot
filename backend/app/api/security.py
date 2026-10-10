"""FastAPI dependencies for authentication and per-role access.

Every router except the public one (health, auth config) is mounted behind `user`, which rejects API keys and
pending accounts. Ingestion has its own router behind `ingest`. Endpoints that return leads filter them with the
principal's scope, and a lead outside it answers 404 rather than 403 so its existence is not revealed.
"""
from __future__ import annotations

import asyncio

from fastapi import Depends, HTTPException, Request, WebSocket

from ..auth import DEV, AuthError, Principal, principal_for
from .deps import lead_or_404, state

PUBLIC_PATHS = {"/api/health", "/api/auth/config"}


def _token_from(headers, query_token: str | None = None) -> str | None:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return headers.get("x-api-key") or query_token or None


async def resolve(token: str | None) -> Principal:
    """Turn a bearer token or API key into a Principal, or raise 401."""
    if not state.settings.auth:
        return DEV
    if not token:
        raise HTTPException(401, "sign in required", headers={"WWW-Authenticate": "Bearer"})
    if token.startswith("lp_"):
        row = await asyncio.to_thread(state.accounts.verify_key, token)
        if row is None:
            raise HTTPException(401, "invalid or revoked API key")
        return Principal(kind="api_key", role="ingest", key_id=row["id"], name=row["name"])
    try:
        claims = await asyncio.to_thread(state.verifier.verify, token)
    except AuthError as exc:
        raise HTTPException(401, f"invalid session: {exc}", headers={"WWW-Authenticate": "Bearer"}) from exc
    meta = claims.get("user_metadata") or {}
    prof = await asyncio.to_thread(state.accounts.ensure_profile, claims["sub"], claims.get("email"),
                                   meta.get("full_name") or meta.get("name"))
    return principal_for(prof)


async def current_principal(request: Request) -> Principal:
    cached = getattr(request.state, "principal", None)
    if cached is None:
        cached = request.state.principal = await resolve(_token_from(request.headers))
    return cached


async def any_user(p: Principal = Depends(current_principal)) -> Principal:
    """A signed-in person, including pending accounts (used by /api/me)."""
    if p.kind == "api_key":
        raise HTTPException(403, "API keys can only ingest events")
    return p


async def user(p: Principal = Depends(any_user)) -> Principal:
    """A signed-in person with an approved role."""
    if p.role == "pending":
        raise HTTPException(403, "your account is waiting for an admin to grant access")
    return p


def roles(*allowed: str):
    async def dep(p: Principal = Depends(user)) -> Principal:
        if p.role not in allowed:
            raise HTTPException(403, f"requires role: {' or '.join(allowed)}")
        return p
    return dep


manager = roles("admin", "manager")
admin = roles("admin")


async def ingest(p: Principal = Depends(current_principal)) -> Principal:
    """Event ingestion: API keys, admins and managers (reps act through lead actions instead)."""
    if p.kind == "api_key" or p.role in ("admin", "manager"):
        return p
    raise HTTPException(403, "event ingestion needs an API key or a manager / admin account")


async def ws_principal(ws: WebSocket) -> Principal | None:
    """WebSockets cannot send headers from the browser, so the token comes as ?token=. None = reject."""
    try:
        p = await resolve(_token_from(ws.headers, ws.query_params.get("token")))
    except HTTPException:
        return None
    return p if p.kind != "api_key" and p.role != "pending" else None


def visible_lead(p: Principal, lead_id: str):
    """lead_or_404 that also answers 404 for leads outside the caller's scope."""
    lead = lead_or_404(lead_id)
    if not p.can_see(lead):
        raise HTTPException(404, f"lead {lead_id} not found")
    return lead
