"""Highlighted passages of a page, over the web (`rouh/highlights.py`).

Two doors, the same two comments have (`rouh/web/comments.py`), for the same
two kinds of reader:

- **The owner**, on Rouh's canvas: ``/api/highlights?doc=<page>``, carried
  by Rouh's own page (``askRelay`` in app.js), which says which page it is.
- **A person the page was shared with**: ``/shared/<token>/highlights``,
  carried by their reader's page (reader.js). A public link has none.

A GET answers with every highlight on the page, everybody's, each with who
made it, a POST with one
thing done, named by ``do``: ``add``, ``colour`` or ``remove``.
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import askai, comments, highlights

from .comments import NO_STORE, _owner_place
from .common import answer, body_of, refuse, who


async def _answer(request: HttpRequest, place: comments.Place, me: comments.Person):
    if request.method in ("GET", "HEAD"):
        return answer(await asyncio.to_thread(highlights.listing, place, me), headers=NO_STORE)
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    try:
        return answer(await asyncio.to_thread(highlights.do, place, me, body_of(request)),
                      headers=NO_STORE)
    except comments.Refused as exc:
        return refuse(str(exc), exc.status)


async def for_owner(request: HttpRequest):
    """The signed-in person's highlights on one of their own pages."""
    me = await sync_to_async(who)(request)
    person = comments.person_of(getattr(request, "user", None), owner=True)
    if me is None or person is None:
        return refuse("Sign in to Rouh first.", 401)
    doc = str(request.GET.get("doc") or body_of(request).get("doc") or "")
    try:
        place = await asyncio.to_thread(_owner_place, me, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    return await _answer(request, place, person)


async def for_shared(request: HttpRequest, token: str):
    """`/shared/<token>/highlights`: the highlights on a page shared with the
    reader, theirs and everybody else's."""
    from .guests import _reader

    reader = await _reader(request, "shared", token)
    if reader is None or not reader.comments:
        return refuse("That page is not shared with you.", 404)
    person = comments.person_of(request.user, owner=False)
    if person is None:
        return refuse("That page is not shared with you.", 404)
    place = comments.Place(org_id=reader.org_id, owner_id=reader.owner_id, rel=reader.rel,
                           title=reader.title)
    return await _answer(request, place, person)


__all__ = ["for_owner", "for_shared"]
