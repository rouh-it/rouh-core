"""Open on this task, over the web (`rouh/open_items.py`, night 28's gene `open_items`).

``POST /api/open-items`` ``{folder, key, do}``: Done on one open item of a task's Where this
stands, or its Undo. ``folder`` is the task's folder as Rouh framed its page (`taskPageFolder` in
cards.js), ``key`` the item's key as the page drew it.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import open_items
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, only, refuse, who


@only("POST")
async def press(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    sent = body_of(request)
    folder = str(sent.get("folder") or "").strip("/")
    if not folder or any(p in ("", ".", "..") for p in folder.split("/")):
        return refuse("Which task.", 400)
    try:
        done = await sync_to_async(open_items.act)(me, config.assistant_repo, folder,
                                                   str(sent.get("key") or "")[:40],
                                                   str(sent.get("do") or ""))
    except open_items.Refused as exc:
        return refuse(str(exc), 409)
    return answer(done, headers=NO_STORE)


__all__ = ["press"]
