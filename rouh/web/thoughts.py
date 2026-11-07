"""The Thoughts page, at /thoughts: the person's own thoughts, in their words (`rouh/thoughts.py`).

    GET  /api/thoughts                  newest first, with every topic and the counts:
                                        ?q= words to find, &tag= one topic, &archived=1 the archived ones
    GET  /api/thoughts/<id>             one, whole
    POST /api/thoughts/new              {"words", "title"?, "tags"?, "follows"?}: a new one, or a follow-up
    POST /api/thoughts/<id>             {"words"?, "title"?, "tags"?, "status"?}: change one
    POST /api/thoughts/<id>/archive     {"back"?}: archive one, or bring it back
    POST /api/thoughts/<id>/link        {"follows"}: a follow-up of an earlier one; null takes the link away
    POST /api/thoughts/<id>/enrich      research it again (`rouh/thought_enrich.py`): a fresh run in its task,
                                        or its first one for a thought kept before there were any

A new thought is enriched by itself: a task of its own, and a run that researches it and writes its
enriched page with a visual explainer (`thought_enrich.begin`), which each thought then carries as
`enriched`.

Only the signed-in person's own thoughts, always asked for by their organisation and account together
(`Tenancy.current`, via `who`). Every change is copied into their Synapse Master before it answers, so a
question finds it at once, and every tab of theirs hears that the list moved (`thoughts.tell`).
"""
from __future__ import annotations

import asyncio

from django.http import HttpRequest

from rouh import thought_enrich

from .common import answer, body_of, only, refuse, who

NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(who, request)


@only("GET")
async def listing(request: HttpRequest):
    from rouh import thoughts

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    got = await asyncio.to_thread(lambda: thoughts.listing(
        me, q=request.GET.get("q", ""), tag=request.GET.get("tag", ""),
        archived=request.GET.get("archived") in ("1", "true", "yes")))
    return answer(got, headers=NO_STORE)


async def _changed(me, v: dict):
    from rouh import thoughts

    await asyncio.to_thread(thoughts.mirror_now, v["id"])
    await thoughts.tell(me)
    return answer({"ok": True, "thought": await asyncio.to_thread(thoughts.one, me, v["id"])}, headers=NO_STORE)


@only("POST")
async def add(request: HttpRequest):
    from rouh import thoughts

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        v, _new = await asyncio.to_thread(lambda: thoughts.capture(
            me, str(body.get("words") or ""), title=str(body.get("title") or ""), tags=body.get("tags") or [],
            source="typed", follows=body.get("follows")))
    except thoughts.NotFound as exc:
        return refuse(str(exc), 404)
    except ValueError as exc:
        return refuse(str(exc), 400)
    if _new:
        # Typed here, its title is the one it keeps, so the run need not wait for one.
        await thought_enrich.begin(me, v["id"], delay=0)
    return await _changed(me, v)


async def one(request: HttpRequest, ident: int):
    """GET reads one; POST changes it."""
    from rouh import thoughts

    if request.method not in ("GET", "HEAD", "POST"):
        return refuse("Not allowed.", 405)
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        if request.method == "POST":
            body = body_of(request)
            v = await asyncio.to_thread(lambda: thoughts.edit(
                me, ident, words=body.get("words"), title=body.get("title"), tags=body.get("tags"),
                status=body.get("status")))
            return await _changed(me, v)
        return answer({"thought": await asyncio.to_thread(thoughts.one, me, ident)}, headers=NO_STORE)
    except thoughts.NotFound as exc:
        return refuse(str(exc), 404)
    except ValueError as exc:
        return refuse(str(exc), 400)


@only("POST")
async def archive(request: HttpRequest, ident: int):
    from rouh import thoughts

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    back = bool(body_of(request).get("back"))
    try:
        v = await asyncio.to_thread(lambda: thoughts.archive(me, ident, back=back))
    except thoughts.NotFound as exc:
        return refuse(str(exc), 404)
    return await _changed(me, v)


@only("POST")
async def link(request: HttpRequest, ident: int):
    from rouh import thoughts

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    follows = body_of(request).get("follows")
    try:
        v = await asyncio.to_thread(lambda: thoughts.link(me, ident, follows))
    except thoughts.NotFound as exc:
        return refuse(str(exc), 404)
    except ValueError as exc:
        return refuse(str(exc), 400)
    return await _changed(me, v)


@only("POST")
async def enrich(request: HttpRequest, ident: int):
    """Research a thought again, in the task it already has: Research again on the page, Try again
    after a failure, and Research it on a thought kept before there was any of this."""
    from rouh import thoughts

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        v = await asyncio.to_thread(thoughts.one, me, ident)
    except thoughts.NotFound as exc:
        return refuse(str(exc), 404)
    state = (v.get("enriched") or {}).get("state", "")
    if state in ("starting", "running") or not await thought_enrich.begin(me, v["id"], delay=0, again=True):
        return refuse("It is being researched already.", 409)
    await thoughts.tell(me)
    return answer({"ok": True, "thought": await asyncio.to_thread(thoughts.one, me, v["id"])}, headers=NO_STORE)
