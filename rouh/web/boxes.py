"""The Box page's API, at /box: what the person keeps from the model (`rouh/boxes.py`).

    GET  /api/box                    every box of theirs, highest number first, none of them opened
    POST /api/box/new                {"content", "label"?, "kind"?}: a new box, sealed
    GET  /api/box/<id>               one box, opened: what is in it, for this page alone
    POST /api/box/<id>               {"label"?, "kind"?, "content"?}: change one
    POST /api/box/<id>/delete        delete one for good

    POST /internal/boxes/collect     {"key", "run"}: this machine only, the one program collecting the
                                     boxes handed to a run as it starts, once (`boxes.collect`)
    POST /internal/boxes/shredded    {"run"}: this machine only, a run's boxes were shredded

What is in a box comes in here and goes out of here and nowhere else (and, for a job it was
handed to, out of `/internal/boxes/collect` to the code that writes it into the job's folder): never over the
conversation's socket, never into a turn or a log line. Only the signed-in person's own
boxes, always asked for by their organisation and account together (`Tenancy.current`, via
`who`), and nothing here is ever stored by a browser (`no-store`).
"""
from __future__ import annotations

import asyncio

import logging

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from .common import answer, body_of, from_this_machine, only, refuse, who

log = logging.getLogger("rouh.web.boxes")

NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(who, request)


@only("GET")
async def listing(request: HttpRequest):
    from rouh import boxes

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(boxes.listing, me), headers=NO_STORE)


@only("POST")
async def add(request: HttpRequest):
    from rouh import boxes

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        b = await asyncio.to_thread(lambda: boxes.add(
            me, body.get("content"), label=body.get("label") or "", kind=body.get("kind") or "secret"))
    except ValueError as exc:
        return refuse(str(exc), 400)
    await boxes.tell(me)
    return answer({"ok": True, "box": b}, headers=NO_STORE)


async def one(request: HttpRequest, ident: int):
    """GET opens one; POST changes it."""
    from rouh import boxes

    if request.method not in ("GET", "HEAD", "POST"):
        return refuse("Not allowed.", 405)
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        if request.method == "POST":
            body = body_of(request)
            b = await asyncio.to_thread(lambda: boxes.change(
                me, ident, label=body.get("label"), kind=body.get("kind"), content=body.get("content")))
            await boxes.tell(me)
            return answer({"ok": True, "box": b}, headers=NO_STORE)
        return answer({"box": await asyncio.to_thread(boxes.opened, me, ident)}, headers=NO_STORE)
    except boxes.NotFound as exc:
        return refuse(str(exc), 404)
    except ValueError as exc:
        return refuse(str(exc), 400)


@only("POST")
async def delete(request: HttpRequest, ident: int):
    from rouh import boxes

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        await asyncio.to_thread(boxes.delete, me, ident)
    except boxes.NotFound as exc:
        return refuse(str(exc), 404)
    await boxes.tell(me)
    return answer({"ok": True}, headers=NO_STORE)


@csrf_exempt
@only("POST")
async def collect(request: HttpRequest):
    """The boxes handed to a run, for the one program to write into its folder: once, by its key."""
    from rouh import boxes

    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."}, status=403)
    body = body_of(request)
    key, run = str(body.get("key") or "")[:300], str(body.get("run") or "")[:80]
    try:
        got = await asyncio.to_thread(boxes.collect, key, run)
    except boxes.NotCollected as exc:
        return answer({"ok": False, "error": str(exc)}, status=404, headers=NO_STORE)
    except Exception:  # noqa: BLE001 - said to the program, which does not start the run
        log.exception("the boxes for run %s could not be collected", run)
        return answer({"ok": False, "error": "The boxes could not be opened."}, status=500,
                      headers=NO_STORE)
    return answer({"ok": True, "boxes": [{"number": b["number"], "content": b["content"]} for b in got]},
                  headers=NO_STORE)


@csrf_exempt
@only("POST")
async def shredded(request: HttpRequest):
    """A run's boxes were shredded: each hand-over's record says so."""
    from rouh import boxes

    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."}, status=403)
    run = str(body_of(request).get("run") or "")[:80]
    n = await asyncio.to_thread(boxes.ended, run) if run else 0
    return answer({"ok": True, "ended": n}, headers=NO_STORE)
