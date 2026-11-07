"""The Decisions page, at /decisions, and every page that draws a decision in place
(`rouh/decisions.py`).

    GET  /api/decisions             every decision of the signed-in person's: open, snoozed,
                                    on their way and the recent history, read level with
                                    their sources first (`decisions.sync`)
    GET  /api/decisions/<id>        one, by its row's own id, with its history
    GET  /api/decisions/at/<ref>    one, by what the person calls it: its number (42)
    GET  /api/decisions/of/<source>/<source id>
                                    the newest one a source asked under that id, for the
                                    source's own page to draw in place
    POST /api/decisions/<id>/act    {act: answer | delegate | snooze | wake | undo | dismiss
                                    | reopen (undo what its source closed by itself)
                                    | not_this (what he said in a chat does not answer it),
                                    choice?: [option ids], items?: {item id: option id} to
                                    answer the items a decision holds one by one,
                                    text?, confirm?: the risk, until?:
                                    seconds, from_page?: the task or step folder whose page
                                    it was pressed on, which must be this decision's own}:
                                    what the person pressed; a refusal answers 400
                                    with the words to show, and a gated answer given without
                                    its risk confirmed answers 409 with `confirm` naming it

Only the signed-in person's own decisions are read or answered here: every query names their
user and organisation, and a number that is not theirs is not found. An answer from here is
recorded as given on the screen.
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
    from rouh import decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    await _desk().sync(me)
    got = await asyncio.to_thread(decisions.lines, me)
    return answer(got, headers=NO_STORE)


@only("GET")
@their_clock
async def one(request: HttpRequest, ident: int):
    from rouh import decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    page = request.GET.get("from_page")
    if page is not None and not await asyncio.to_thread(decisions.of_page, me, ident, page):
        return refuse("That is not this page's question.", 403)
    got = await asyncio.to_thread(decisions.get, me, ident)
    if got is None:
        return refuse("There is no such question.", 404)
    return answer({"decision": got}, headers=NO_STORE)


@only("GET")
@their_clock
async def at(request: HttpRequest, ref: str):
    """One decision by the person's own reference, for its page at /decisions/<number>."""
    from rouh import decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if decisions.ref_of(str(ref)) is None:
        return refuse("There is no such question.", 404)
    got = await asyncio.to_thread(decisions.get, me, str(ref))
    if got is None:
        return refuse("There is no such question.", 404)
    return answer({"decision": got}, headers=NO_STORE)


@only("GET")
@their_clock
async def of_source(request: HttpRequest, source: str, source_id: str):
    from rouh import decision_sources, decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if source not in decision_sources.sources():
        return refuse("There is no such kind of question.", 404)
    await _desk().sync(me, kinds={source})
    got = await asyncio.to_thread(decisions.for_source, me, source, source_id)
    return answer({"decision": got}, headers=NO_STORE)


@only("POST")
@their_clock
async def act(request: HttpRequest, ident: int):
    from rouh import decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    what = str(body.get("act") or "")
    # From a task's or a goal step's own page: only that page's own question.
    if "from_page" in body and not await asyncio.to_thread(
            decisions.of_page, me, ident, str(body.get("from_page") or "")):
        return refuse("That is not this page's question.", 403)
    try:
        got = await _desk().act(me, ident, what, body, channel="screen")
    except decisions.NeedsConfirm as exc:
        return refuse(str(exc), 409, confirm=exc.risk, risk_note=exc.note,
                      decision=await asyncio.to_thread(decisions.get, me, ident))
    except decisions.Refused as exc:
        return refuse(str(exc), 400, decision=await asyncio.to_thread(decisions.get, me, ident))
    return answer(got, headers=NO_STORE)
