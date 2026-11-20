"""Handholding, at /handholding: the guided way into Rouh (`rouh/handholding.py`).

    GET  /api/handholding            the words, the signed-in person's ticks, what Rouh saw for
                                     itself, and each connection's badge
    POST /api/handholding/progress   {step, done, skip?}: tick a step, or take the tick off; skip marks
                                     an optional step not for this person; answers the
                                     ticks as they now are, or 400 with the words to show
    GET  /handholding/<page>         one of the section's sub-pages (the data file's `pages`); a page's
                                     old id (`old_pages`: next, learn) is sent on to the page it is now
    GET  /handholding/lesson/<id>    one lesson, its full page; an old id is sent on to the lesson it is now
    GET  /handholding/learn/<id>     the first version's lesson library: sent on to the lesson holding it

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


def _moved(request: HttpRequest, to: str):
    """Sent on to where a place is now, with the query it came with (`?from=`, `?chat=`)."""
    from django.http import HttpResponseRedirect

    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(to + (("?" + query) if query else ""))


async def address(request: HttpRequest, page: str):
    """A sub-page of the section by its address; one the data file does not have is not found."""
    from django.http import Http404

    from rouh import handholding

    from .views import index

    now = handholding.page_now(page)
    if not now:
        raise Http404("There is no such page in Handholding.")
    if now != page:
        return _moved(request, handholding.page_route(now))
    return await index(request)


async def lesson_address(request: HttpRequest, page: str, lesson: str):
    """One lesson's own page, `/handholding/lesson/<id>`; and the first version's addresses of a lesson
    (`/handholding/learn/<id>`, a lesson of its library), sent on to the lesson that holds it now."""
    from django.http import Http404

    from rouh import handholding

    from .views import index

    if page == handholding.LESSON:
        now = handholding.lesson_now(lesson)
    elif handholding.page_now(page):
        now = handholding.lesson_now(lesson, old_library=True)
    else:
        now = ""
    if not now and page == handholding.LESSON:
        # The page draws its own "There is no such lesson", with the way to the path.
        return await index(request)
    if not now:
        raise Http404("There is no such lesson.")
    if page != handholding.LESSON or now != lesson:
        return _moved(request, handholding.lesson_route(now))
    return await index(request)
