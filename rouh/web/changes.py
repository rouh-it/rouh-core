"""Meta, Changes, at /anatomy/meta/changes (`rouh/codechanges.py`).

    GET  /api/settings/changes         the protected core, the undo point that runs, every undo
                                       point, changes waiting, what the doctor last did
    POST /api/settings/changes/undo    {point}: put the code back to that undo point; an
                                       administrator's press only
    /api/settings/updates...           Rouh's updates, below (`rouh/code_update.py`)

Task 98, step 98-23. Everything here is asked of the protected core over its socket
(`rouh/guardface.py`); a Rouh with none beside it says so.
"""
from __future__ import annotations

import asyncio

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

NO_STORE = {"Cache-Control": "no-store"}


@only("GET")
@their_clock
async def page(request: HttpRequest):
    from rouh import codechanges

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(codechanges.public, me), headers=NO_STORE)


@only("POST")
@their_clock
async def undo(request: HttpRequest):
    from rouh import codechanges

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        n = int(body.get("point"))
    except (TypeError, ValueError):
        return refuse("Say which undo point.", 400)
    try:
        got = await asyncio.to_thread(codechanges.undo, me, n)
    except codechanges.Refused as exc:
        return refuse(str(exc), 400, **(await asyncio.to_thread(codechanges.public, me)))
    return answer({"ok": True, **got, **(await asyncio.to_thread(codechanges.public, me))}, headers=NO_STORE)


# --- Rouh's updates (task 140, step 140-18, `rouh/code_update.py`) -------------------------------
#
#     GET  /api/settings/updates          the choice, the version here, the newest, what is new
#                                         (?look=1 asks rouh.land now, also for a Rouh on its own)
#     POST /api/settings/updates/mode     {mode}: ride, press or own; an administrator's press only
#     POST /api/settings/updates/now      update to the newest release now; an administrator's only


@only("GET")
@their_clock
async def updates(request: HttpRequest):
    from rouh import code_update

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    look = request.GET.get("look") == "1"
    return answer(await asyncio.to_thread(code_update.public, me, look=look), headers=NO_STORE)


@only("POST")
@their_clock
async def updates_mode(request: HttpRequest):
    from rouh import code_update

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        await asyncio.to_thread(code_update.set_mode, me, str(body_of(request).get("mode") or ""))
    except code_update.Refused as exc:
        return refuse(str(exc), 400, **(await asyncio.to_thread(code_update.public, me)))
    got = await asyncio.to_thread(code_update.public, me)
    return answer({"ok": True, "said": f"Saved: {code_update.MODES[got['mode']]}.", **got}, headers=NO_STORE)


@only("POST")
@their_clock
async def updates_now(request: HttpRequest):
    from rouh import code_update

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        started = await code_update.update(me, by="a press on Changes")
    except code_update.Refused as exc:
        return refuse(str(exc), 400, **(await asyncio.to_thread(code_update.public, me)))
    return answer({"ok": True, **started, **(await asyncio.to_thread(code_update.public, me))}, headers=NO_STORE)
