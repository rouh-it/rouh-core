"""The Quests page, at /quests, and each quest's own page, at /quests/<task number>
(`rouh/quests.py`).

    GET  /api/quests                    every quest, with its state, dates, money,
                                        approvals and beats (`quests.listing`)
    POST /api/quests                    {title, goal?, rules?, plan?, start?, end?, budget?,
                                        spend_cap?, carried?}: a new quest, its task and its
                                        chat; answers {quest: <number>}
    GET  /api/quests/<n>                everything its page draws (`quests.view`)
    POST /api/quests/<n>/act            {act: pause | resume | now | set | brief | reset |
                                        delete, budget?, spend_cap?, start?, end?, carried?,
                                        part?, text?, task?, while_paused?, where?}; now is
                                        Check now, one beat on it (`questcheck.ask`): it
                                        answers {check: {beat, status, already}}, and a
                                        paused quest is checked once only with
                                        while_paused true; a delete answers
                                        {deleted: true}, and its `task` is keep, archive or
                                        delete (`quests.remove`)
    POST /api/quests/<n>/ledger         {direction: in | out, amount, currency?, what}:
                                        money Petar reports, written as his
    GET  /work/<id>                     the old address of a quest's page, by its record:
                                        sent on to /quests/<n>

A quest is named by its task's number everywhere a person sees it. Every query names the
signed-in person's user and organisation, and a number that is not theirs is not found.
"""
from __future__ import annotations

import asyncio

from django.http import HttpRequest, HttpResponseRedirect

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

NO_STORE = {"Cache-Control": "no-store"}


def _pulse():
    from rouh import runtime

    return runtime.pulse


async def _changed() -> None:
    pulse = _pulse()
    pulse.poke()
    await pulse._changed()


@only("GET", "POST")
@their_clock
async def listing(request: HttpRequest):
    from rouh import quests

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if request.method == "POST":
        body = body_of(request)
        carried = body.get("carried")
        try:
            row = await asyncio.to_thread(
                lambda: quests.create(me, title=body.get("title"), goal=body.get("goal"),
                                      rules=body.get("rules"), plan=body.get("plan"),
                                      start=body.get("start") or "", end=body.get("end") or "",
                                      budget=body.get("budget"), spend_cap=body.get("spend_cap"),
                                      carried=carried is None or bool(carried)))
        except ValueError as exc:
            return refuse(str(exc), 400)
        await _pulse().quest_made(me, row)
        return answer({"ok": True, "quest": row.task_number, "href": quests.address(row),
                       "said": f"Made quest {row.task_number} “{row.title}”, with its task "
                               "and its own chat."}, headers=NO_STORE)
    rows = await asyncio.to_thread(quests.listing, me)
    return answer({"quests": rows}, headers=NO_STORE)


async def _page(me, number):
    from rouh import quests

    row = await asyncio.to_thread(quests.by_number, me, number)
    if row is None:
        return None
    got = await asyncio.to_thread(quests.view, me, row)
    pulse = _pulse()
    got["telegram"] = bool(pulse.phone and pulse.phone.configured())
    from .heartbeat import asking

    got["decisions"] = await asking(me, got.get("approvals") or [])
    from rouh import delegation

    got["delegates"] = await asyncio.to_thread(delegation.on_work, me.user_id, me.org_id,
                                               quest_id=str(row.id))
    return got


@only("GET")
@their_clock
async def page(request: HttpRequest, number: int):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    got = await _page(me, number)
    if got is None:
        return refuse("There is no such quest.", 404)
    return answer(got, headers=NO_STORE)


@only("POST")
@their_clock
async def act(request: HttpRequest, number: int):
    from rouh import quests

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    row = await asyncio.to_thread(quests.by_number, me, number)
    if row is None:
        return refuse("There is no such quest.", 404)
    body = body_of(request)
    what = str(body.get("act") or "")
    pulse = _pulse()
    try:
        if what in ("pause", "resume"):
            said = await pulse.work_state(me, row.id, paused=what == "pause")
        elif what == "now":
            said = await pulse.work_now(me, row.id, while_paused=body.get("while_paused") is True,
                                        where=str(body.get("where") or "quest")[:10])
        elif what == "set":
            carried = body.get("carried")
            said = await asyncio.to_thread(
                lambda: quests.settings(row, budget=body.get("budget"),
                                        spend_cap=body.get("spend_cap"),
                                        start=body.get("start"), end=body.get("end"),
                                        carried=None if carried is None else bool(carried)))
            await _changed()
        elif what == "brief":
            said = await asyncio.to_thread(quests.write_brief, row, body.get("part"),
                                           body.get("text"), "replace")
            await _changed()
        elif what in ("reset", "delete"):
            from .heartbeat import clear_work

            said = await clear_work(me, row.id, what, task=body.get("task") or "archive")
            if what == "delete":
                return answer({"ok": True, "said": said, "deleted": True}, headers=NO_STORE)
        else:
            return refuse("act is pause, resume, now, set, brief, reset or delete.", 400)
    except LookupError as exc:
        return refuse(str(exc), 404)
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _page(me, row.task_number) or {}))
    return answer({"ok": True, "said": said, **(await _page(me, row.task_number) or {})},
                  headers=NO_STORE)


@only("POST")
@their_clock
async def ledger(request: HttpRequest, number: int):
    from rouh import quests

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    row = await asyncio.to_thread(quests.by_number, me, number)
    if row is None:
        return refuse("There is no such quest.", 404)
    body = body_of(request)
    try:
        await asyncio.to_thread(
            lambda: quests.ledger_add(me, row.id, direction=body.get("direction"),
                                      amount=body.get("amount"),
                                      currency=body.get("currency") or "USD",
                                      what=body.get("what"), by="owner"))
    except ValueError as exc:
        return refuse(str(exc), 400)
    await _changed()
    return answer({"ok": True, **(await _page(me, row.task_number) or {})}, headers=NO_STORE)


@only("GET")
async def old_address(request: HttpRequest, ident: int):
    """/work/<id>, which the first Telegrams and pages linked to: its quest's page now, or
    the Quests page when the record is gone or not the signed-in person's."""
    from rouh import quests

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        from urllib.parse import urlencode

        return HttpResponseRedirect("/login?" + urlencode({"next": request.path}), status=303)
    row = await asyncio.to_thread(quests.get, me, ident)
    return HttpResponseRedirect(quests.address(row))
