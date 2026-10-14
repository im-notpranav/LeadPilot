"""Notifications: the bell and the Notifications page, each person's own channel settings, and channel tests.

Everyone sees what is addressed to them (reps: their own leads; managers and admins: their team's escalations,
reassignments, deals and quality alerts). Managers and admins can also look at what their reps were sent.
"""
from __future__ import annotations

import asyncio

import phonenumbers
from fastapi import APIRouter, Body, Depends, HTTPException

from ..auth import Principal
from .deps import state
from .security import admin, user

router = APIRouter(prefix="/api/notifications")


@router.get("")
async def listing(mine: bool = True, unread: bool = False, rule: str | None = None, before: int | None = None,
                  limit: int = 50, p: Principal = Depends(user)):
    return state.notifications.listing(p, mine=mine or p.role == "rep", unread_only=unread, rule=rule,
                                       before=before, limit=max(1, min(limit, 200)))


@router.post("/read")
async def mark_read(body: dict = Body(...), p: Principal = Depends(user)):
    ids = body.get("ids") or []
    if not body.get("all") and (not isinstance(ids, list) or not all(isinstance(i, int) for i in ids)):
        raise HTTPException(422, 'send {"ids": [1, 2]} or {"all": true}')
    await asyncio.to_thread(state.notifications.mark_read, p, ids, bool(body.get("all")))
    return {"unread": state.notifications.listing(p, limit=1)["unread"]}


@router.get("/settings")
async def settings(p: Principal = Depends(user)):
    nc = state.notifications
    prof = state.accounts.get_profile(p.user_id) if p.user_id else None
    out = {
        "channels": nc.channels.status(),
        "delivers": nc.live or nc.channels.in_demo,
        "me": None if prof is None else _me(prof),
        "rules": [{"name": k, **{f: r.get(f) for f in ("enabled", "to", "channels", "severity")}}
                  for k, r in nc.rules.items()] if p.role in ("admin", "manager") else [],
    }
    return out


@router.put("/settings")
async def save_settings(body: dict = Body(...), p: Principal = Depends(user)):
    if not p.user_id:
        raise HTTPException(409, "sign-in is off, so there is no personal profile to save settings on")
    phone = (body.get("phone") or "").strip() or None
    if phone:
        try:
            num = phonenumbers.parse(phone, None)
        except phonenumbers.NumberParseException:
            raise HTTPException(422, "enter the phone number with its country code, e.g. +44 7700 900123") from None
        if not phonenumbers.is_valid_number(num):
            raise HTTPException(422, "that phone number is not valid")
        phone = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    notify = {"email": bool(body.get("email", True)), "sms": bool(body.get("sms", False))}
    if notify["sms"] and not phone:
        raise HTTPException(422, "add a phone number to get SMS notifications")
    try:
        prof = await asyncio.to_thread(state.accounts.update_notify, p.user_id, phone, notify)
    except KeyError:
        raise HTTPException(404, "profile not found") from None
    return _me(prof)


def _me(prof: dict) -> dict:
    return {"email_address": prof.get("email"), "phone": prof.get("phone"), **state.notifications.prefs(prof)}


@router.post("/test", dependencies=[Depends(admin)])
async def test(body: dict = Body(...), p: Principal = Depends(admin)):
    channel = body.get("channel")
    if channel not in ("email", "slack", "sms"):
        raise HTTPException(422, "channel must be email, slack or sms")
    prof = state.accounts.get_profile(p.user_id) if p.user_id else None
    return await state.notifications.send_test(channel, prof, p)
