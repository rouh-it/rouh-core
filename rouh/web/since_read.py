"""Since you last read it, over the web (`rouh/since_read.py`, version 2).

``GET /api/since-read?doc=<page>`` is said by the canvas each time the owner opens a page of the
workspace on it: the visit is kept, and the answer says whether the page's words changed since the
visit before, which is what puts What changed on the canvas bar. Nothing is kept, and the answer
is ``{"on": false}``, while the switch is off. ``doc`` is the page as Ask AI names it (`askDoc` in
runs.js), found the way Ask AI finds it (`askai.resolve`).
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import askai, since_read
from rouh.config import config

from .comments import NO_STORE
from .common import answer, only, refuse, who


@only("GET")
async def for_owner(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    doc = str(request.GET.get("doc") or "")
    try:
        page = await asyncio.to_thread(askai.resolve, config.assistant_repo, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    said = await asyncio.to_thread(since_read.seen, me, page, doc)
    return answer(said, headers=NO_STORE)


__all__ = ["for_owner"]
