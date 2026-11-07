"""Your part, at /actions: the hands-on things only the person can do (`rouh/actions.py`).

    GET  /api/actions               every action of the signed-in person's: open (grouped by the
                                    work each unblocks, then oldest first), put off, on their way
                                    back, and done lately, as the desk last made them level
    GET  /api/actions/at/<number>   one, by its number (Action 430), with its history
    POST /api/actions/<id>/act      {act: done | not_doing | another | tick | ask | snooze | wake
                                    | undo | reopen, text?, step?, on?, until?, confirm?}: what the
                                    person pressed; a refusal answers 400 with the words to show,
                                    and a gated Done given without its risk confirmed 409

Only the signed-in person's own actions are read or answered here: every query names their user
and organisation, and a number that is not theirs is not found. An answer from here is recorded
as given on the screen.
"""
from __future__ import annotations

import asyncio

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

NO_STORE = {"Cache-Control": "no-store"}


def _desk():
    from rouh import runtime

    return runtime.desk


@only("GET")
@their_clock
async def listing(request: HttpRequest):
    from rouh import actions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    # Read at once, never after a sync of every source: the desk keeps the record level every
    # 30 seconds and at once when a source moves, and a page that waited on the sync could sit
    # on "Reading" for as long as the slowest source took.
    got = await asyncio.to_thread(actions.listing, me)
    return answer(got, headers=NO_STORE)


@only("GET")
@their_clock
async def at(request: HttpRequest, ref: str):
    from rouh import actions, decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if decisions.ref_of(str(ref)) is None:
        return refuse("There is no such action.", 404)
    got = await asyncio.to_thread(actions.get, me, str(ref))
    if got is None:
        return refuse("There is no such action.", 404)
    return answer({"action": got}, headers=NO_STORE)


@only("POST")
@their_clock
async def act(request: HttpRequest, ident: int):
    from rouh import actions, decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    what = str(body.get("act") or "")
    try:
        got = await _desk().act_on_action(me, ident, what, body, channel="screen")
    except decisions.NeedsConfirm as exc:
        return refuse(str(exc), 409, confirm=exc.risk, risk_note=exc.note,
                      action=await asyncio.to_thread(actions.get, me, ident))
    except decisions.Refused as exc:
        return refuse(str(exc), 400, action=await asyncio.to_thread(actions.get, me, ident))
    if isinstance(got, dict) and isinstance(got.get("decision"), dict):
        got["action"] = actions.drawn(got.pop("decision"))
    return answer(got, headers=NO_STORE)
