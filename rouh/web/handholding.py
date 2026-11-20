"""Handholding, at /handholding: the guided way into Rouh (`rouh/handholding.py`).

    GET  /api/handholding            the words, the signed-in person's ticks, what Rouh saw for
                                     itself, and each connection's badge
    POST /api/handholding/progress   {step, done, skip?}: tick a step, or take the tick off; skip marks
                                     an optional step not for this person; answers the
                                     ticks as they now are, or 400 with the words to show
    GET  /handholding/<page>         one of the section's sub-pages (the data file's `pages`), and
    GET  /handholding/<page>/<id>    one lesson, under the page that holds the lessons; not found otherwise

Only the signed-in person's own ticks are read or written: every query names their user and
organisation.
"""
from __future__ import annotations

import asyncio

from django.http import HttpRequest

from .clock import _signed_in
from .common import answer, body_of, only, refuse

NO_STORE = {"Cache-Control": "no-store"}


@only("GET")
async def page(request: HttpRequest):
    from rouh import handholding

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    got = await asyncio.to_thread(handholding.page, me)
    return answer(got, headers=NO_STORE)


@only("POST")
async def progress(request: HttpRequest):
    from rouh import handholding

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    step = str(body.get("step") or "")
    try:
        got = await asyncio.to_thread(handholding.mark, me, step, bool(body.get("done")), bool(body.get("skip")))
    except ValueError as exc:
        return refuse(str(exc), 400)
    return answer({"progress": got}, headers=NO_STORE)


async def address(request: HttpRequest, page: str):
    """A sub-page of the section by its address; one the data file does not have is not found."""
    from django.http import Http404

    from rouh import handholding

    from .views import index

    if page not in {p["id"] for p in handholding.pages()}:
        raise Http404("There is no such page in Handholding.")
    return await index(request)


async def lesson_address(request: HttpRequest, page: str, lesson: str):
    """One lesson, under the page that holds the lessons: `/handholding/learn/<lesson>`."""
    from django.http import Http404

    from rouh import handholding

    from .views import index

    if page != handholding.lessons_page() or \
            lesson not in {x.get("id") for x in handholding.content().get("lessons", [])}:
        raise Http404("There is no such lesson.")
    return await index(request)
