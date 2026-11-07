"""The Heartbeat page, at /settings/heartbeat: the heartbeat's settings, duties, beats and queue.

    GET  /api/heartbeat           everything the page draws (`heartbeat.view`)
    POST /api/heartbeat/act       {act: pause | resume | now | set, interval_minutes?,
                                   daily_cap?, hours?, wakes?, flood?, skip?, messages?,
                                   duties?, extra?}
    POST /api/heartbeat/answer    {id, answer: yes | no}: Petar's answer to one entry of
                                  the queue; on a yes exactly the queued action runs
    POST /api/heartbeat/approvals {act: delete, ids}: delete waiting entries of the queue
                                  for good, neither a yes nor a no (`heartbeat.delete_approvals`)
    POST /api/heartbeat/work      {id, act: carry | drop | reset | delete, task?}: whether
                                  the heartbeat carries one quest (by its record's id), or
                                  start it again from beat 1, or delete it, its task kept,
                                  archived or deleted (`quests.reset`, `quests.remove`)
    GET  /api/heartbeat/beats     ?work=all|heartbeat|<quest number>&from=&to=: the beats as a table
                                  (`beatlog.listing`), for the Beats page
    POST /api/heartbeat/beats     {act: delete | clear_notes, ids, work?, from?, to?}: done
                                  to the selected beats; the answer is the table again
    GET  /api/heartbeat/beats/<id> one beat opened: the note it was handed, every model request
                                  it made, every tool its decision called (`beatlog.detail`)

Only the heartbeat: nothing of any quest's goal, money, brief or ledger, which are on
that quest's own page (`rouh/web/quests.py`), nor the card or Stripe
(`rouh/web/payments.py`). Everything goes through the heartbeat running in this process
(`runtime.pulse`), the very object the `heartbeat` tool and Telegram use. Every answer is
the whole page again, read from the database, and every query names the signed-in
person's user and organisation.
"""
from __future__ import annotations

import asyncio

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

NO_STORE = {"Cache-Control": "no-store"}
SETTING_PARTS = ("interval_minutes", "daily_cap", "hours", "wakes", "flood", "skip",
                 "messages", "duties", "extra")


def _pulse():
    from rouh import runtime

    return runtime.pulse


async def _page(me) -> dict:
    from rouh import heartbeat

    got = await asyncio.to_thread(heartbeat.view, me)
    pulse = _pulse()
    got["telegram"] = bool(pulse.phone and pulse.phone.configured())
    got["decisions"] = await asking(me, got.get("approvals") or [])
    # Each one waiting goes to its own decision on the one Decisions list, where it is answered.
    from rouh import decisions

    for a in got.get("approvals") or []:
        d = got["decisions"].get(str(a["id"]))
        if d:
            a["href"] = decisions.page_of(d)
    return got


async def asking(me, approvals: list) -> dict:
    """The decision of each waiting approval (`rouh/decisions.py`), by its number, which the
    page draws it with: the one drawing of a question, answered the one way."""
    from rouh import decisions, runtime

    waiting = [a["id"] for a in approvals if a.get("state") == "waiting"]
    if not waiting:
        return {}
    await runtime.desk.sync(me, kinds={"approval"})
    return await asyncio.to_thread(decisions.of_sources, me, "approval", waiting)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


@only("POST")
@their_clock
async def act(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    pulse = _pulse()
    what = str(body.get("act") or "")
    try:
        if what == "pause":
            said = await pulse.pause(me)
        elif what == "resume":
            said = await pulse.resume(me)
        elif what == "now":
            said = await pulse.now(me)
        elif what == "set":
            said = await pulse.settings(me, {k: body[k] for k in SETTING_PARTS if k in body})
        else:
            return refuse("act is pause, resume, now or set.", 400)
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


@only("POST")
@their_clock
async def answer_one(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    word = str(body.get("answer") or "").strip().lower()
    if word not in ("yes", "no"):
        return refuse("answer is yes or no.", 400)
    said = await _pulse().answer(me, body.get("id"), word == "yes", on="screen")
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


@only("POST")
@their_clock
async def approvals(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    if str(body.get("act") or "") != "delete":
        return refuse("act is delete.", 400)
    try:
        said = await _pulse().delete_approvals(me, body.get("ids"))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


@only("POST")
@their_clock
async def work(request: HttpRequest):
    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    what = str(body.get("act") or "")
    if what not in ("carry", "drop", "reset", "delete"):
        return refuse("act is carry, drop, reset or delete.", 400)
    try:
        if what in ("reset", "delete"):
            said = await clear_work(me, body.get("id"), what, task=body.get("task") or "archive")
        else:
            said = await _pulse().work_state(me, body.get("id"), carried=what == "carry")
    except LookupError as exc:
        return refuse(str(exc), 404)
    except ValueError as exc:
        return refuse(str(exc), 409, **(await _page(me)))
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


async def clear_work(me, ident, what: str, *, task: str = "archive") -> str:
    """Reset or delete one quest, by its record's id, and tell the heartbeat and the open
    pages. A delete keeps, archives or deletes its task (`quests.remove`).

    A LookupError when it is not this person's; a ValueError when it cannot be done now."""
    from rouh import quests

    row = await asyncio.to_thread(quests.get, me, ident)
    if row is None:
        raise LookupError("There is no such quest.")
    said = await asyncio.to_thread(
        (lambda: quests.reset(row)) if what == "reset" else (lambda: quests.remove(row, task)))
    pulse = _pulse()
    pulse.poke()
    await pulse._changed()
    return said


def _filter(source) -> dict:
    return {"work": str(source.get("work") or "all"), "start": str(source.get("from") or ""),
            "end": str(source.get("to") or "")}


@only("GET", "POST")
@their_clock
async def beats(request: HttpRequest):
    from rouh import beatlog

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    said = ""
    if request.method == "POST":
        body = body_of(request)
        what = str(body.get("act") or "")
        if what not in ("delete", "clear_notes"):
            return refuse("act is delete or clear_notes.", 400)
        try:
            said = await asyncio.to_thread(
                beatlog.delete if what == "delete" else beatlog.clear_notes, me, body.get("ids"))
        except ValueError as exc:
            return refuse(str(exc), 400)
        await _pulse()._changed()
        picked = _filter(body)
    else:
        picked = _filter(request.GET)
    try:
        got = await asyncio.to_thread(lambda: beatlog.listing(me, **picked))
    except ValueError as exc:
        return refuse(str(exc), 400)
    if said:
        got.update(ok=True, said=said)
    return answer(got, headers=NO_STORE)


@only("GET")
@their_clock
async def one_beat(request: HttpRequest, ident: int):
    from rouh import beatlog, decisions

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        got = await asyncio.to_thread(beatlog.detail, me, ident)
    except LookupError as exc:
        return refuse(str(exc), 404)
    except ValueError as exc:
        return refuse(str(exc), 400)
    # What it waits on is answered where the beat is opened, as on the Heartbeat page, and
    # its Answer it goes to the decision's own page.
    got["decisions"] = await asking(me, got.get("approvals") or [])
    for a in got.get("approvals") or []:
        d = got["decisions"].get(str(a["id"]))
        if d:
            a["href"] = decisions.page_of(d)
    return answer(got, headers=NO_STORE)
