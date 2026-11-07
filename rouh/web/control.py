"""The Control Room's two endpoints (`rouh/controlroom.py`).

    GET /api/control         the map: every cluster on Petar's mind, how big it is
                             and why, and what is on its card
    POST /api/control/others {"on": true|false}: Others' tasks shown on the map, or
                             not, which is his one switch for every view
                             (`rouh/task_origin.py`)

Read only, like the room itself: nothing here answers, clears or changes
anything but that one switch. Two things are written down on the way: that
he looked (what "since you last looked" is measured from), and, when the
names are due, the naming pass is started after the answer is made, so the
room never waits on a model (`controlroom.kick`).
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.web.control")

NO_STORE = {"Cache-Control": "no-store"}


@only("GET")
async def control_room(request: HttpRequest):
    """Everything the Control Room draws, read afresh on every request."""
    from rouh import controlroom

    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        got = await asyncio.to_thread(controlroom.room, me)
    except Exception:
        log.exception("the control room could not be read")
        return answer({"ok": False, "clusters": [],
                       "why": "Rouh could not read the map just now."},
                      status=500, headers=NO_STORE)
    if got.get("ok"):
        try:
            why = await asyncio.to_thread(controlroom.due, me)
            if why and controlroom.kick(me, why):
                got["naming"] = (f"{got.get('model_name') or 'The model'} is naming the clusters "
                                 "and writing their headlines now; they are here the next time you open the room."
                                 if why == "never named" else
                                 "New names and headlines are being written; they are here the next time you "
                                 "open the room.")
        except Exception:
            log.exception("the control room's naming pass could not be started")
    return answer(got, status=200 if got.get("ok") else 503, headers=NO_STORE)


@only("POST")
async def control_others(request: HttpRequest):
    """Others' tasks on or off: the tasks made for somebody else, shown on the map and in the
    task browser, each marked with who it was for, or left out of both (`rouh/task_origin.py`)."""
    from rouh import task_origin

    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    on = body_of(request).get("on") is True
    now = await asyncio.to_thread(task_origin.show, me.user_id, me.org_id, on)
    return answer({"ok": True, "show_others": now}, headers=NO_STORE)
