"""A name's .ai and .com now, and its trade mark screening, over the web (`rouh/name_checks.py`).

``POST /api/name-checks?doc=<page>``, carried from the page on the canvas by Rouh's own page
(``askRelay`` in cards.js, ``/api/checks``), for the page's owner only. ``do`` is ``domains``,
``trademark`` or ``trademark_status``; which page it is about is Rouh's answer, never the page's.
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import askai, name_checks

from .comments import NO_STORE, _owner_place
from .common import answer, body_of, refuse, who


async def for_owner(request: HttpRequest):
    from rouh.config import config

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    asked = body_of(request)
    doc = str(request.GET.get("doc") or asked.get("doc") or "")
    try:
        place = await asyncio.to_thread(_owner_place, me, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    what = str(asked.get("do") or "")
    root = str(config.assistant_repo)
    try:
        if what == "domains":
            said = await name_checks.domains(asked.get("spellings"))
        elif what == "trademark":
            said = await name_checks.trademark(me, root, place.rel, asked.get("word"),
                                               asked.get("spellings"))
        elif what == "trademark_status":
            said = await name_checks.trademark_status(me, root, place.rel, asked.get("words"))
        else:
            return refuse("That is not a check this page can ask for.", 400)
    except name_checks.Refused as exc:
        return refuse(str(exc), exc.status)
    return answer(said, headers=NO_STORE)


__all__ = ["for_owner"]
