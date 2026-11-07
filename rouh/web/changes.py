"""Meta, Changes, at /anatomy/meta/changes (`rouh/codechanges.py`).

    GET  /api/settings/changes         the protected core, the undo point that runs, every undo
                                       point, changes waiting, what the doctor last did
    POST /api/settings/changes/undo    {point}: put the code back to that undo point; an
                                       administrator's press only

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
