"""Time before its date, over the web (`rouh/task_time.py`, night 32's gene `task_time`).

``POST /api/task-time`` ``{folder, act}``: with ``act`` "find", the free working hours left on the
main calendar before the date the task's notes say it is due, and up to three two-hour gaps; with
``act`` "block" and ``start``, focus time put in one of them. ``folder`` is the task's folder as
Rouh framed its page (`taskPageFolder` in cards.js).
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import task_time
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.web.task_time")


@only("POST")
async def press(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    sent = body_of(request)
    folder = str(sent.get("folder") or "").strip("/")
    act = str(sent.get("act") or "")
    if not folder or any(p in ("", ".", "..") for p in folder.split("/")) or act not in ("find", "block"):
        return refuse("Which task, and what to do.", 400)
    if not await sync_to_async(task_time.on)(me):
        return refuse("Time before its date is switched off.", 400)
    from rouh import runtime

    google = getattr(runtime, "brief_google", None)
    try:
        if act == "find":
            done = await task_time.find(me, google, config.assistant_repo, folder)
        else:
            done = await task_time.block(me, google, config.assistant_repo, folder,
                                         str(sent.get("start") or "")[:40])
    except Exception as exc:  # noqa: BLE001 - said in Google's words
        log.warning("time before its date failed: %r", exc)
        return refuse("Google would not do it: " + str(exc)[:200], 502)
    if not done.get("ok"):
        return refuse(done.get("error") or "That could not be done.", 400)
    return answer(done, headers=NO_STORE)


__all__ = ["press"]
