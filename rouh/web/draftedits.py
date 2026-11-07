"""Anatomy, Behaviour, Draft edits: the emails the person changed before Send (`rouh/draft_edits.py`).

``GET /api/settings/draft-edits`` is the signed-in person's recorded edits, newest first, a page
at a time, with whether the gene's switch is on; ``?before=<id>`` is the page older than that row.
Read only: nothing is changed here.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import draft_edits

from .comments import NO_STORE
from .common import answer, refuse, who


async def page(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET", "HEAD"])
    try:
        before = max(0, int(request.GET.get("before") or 0))
    except ValueError:
        return refuse("before is a row's number.", 400)
    return answer(await sync_to_async(draft_edits.listing)(me, before), headers=NO_STORE)


__all__ = ["page"]
