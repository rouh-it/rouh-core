"""Listen to this page, over the web (`rouh/page_listen.py`, the gene `page_listen`).

``POST /api/page-listen?doc=<page>``, carried from the page on the canvas by Rouh's own page
(``askRelay`` in cards.js, which says which page it is), for the page's owner only. The body names
what is wanted with ``do``:

- ``narrate`` with ``outline`` (the page's numbered elements) and ``title``: the narration,
  ``{key, parts, done}``, written once for the page as it is and kept, with the parts written so
  far while it is still being written.
- ``ready`` with ``key``: what there is so far of that narration, ``{key, parts, done}``.
- ``say`` with ``key`` and ``i``: part ``i`` of it in Rouh's voice, ``{rate, pcm}``; ``jump`` says
  the part was pressed on the page to listen from there.
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import askai, page_listen

from .comments import NO_STORE, _owner_place
from .common import answer, body_of, refuse, who


async def for_owner(request: HttpRequest):
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
    try:
        if what == "narrate":
            said = await page_listen.narrate(me, place.rel, str(asked.get("title") or place.title),
                                             asked.get("outline"))
        elif what == "ready":
            said = await page_listen.ready(me, place.rel, str(asked.get("key") or ""))
        elif what == "say":
            said = await page_listen.speak(me, place.rel, str(asked.get("key") or ""),
                                           asked.get("i"), jump=bool(asked.get("jump")))
        else:
            return refuse("That is not something Listen does.", 400)
    except page_listen.Refused as exc:
        return refuse(str(exc), exc.status)
    return answer(said, headers=NO_STORE)


__all__ = ["for_owner"]
