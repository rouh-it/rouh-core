"""Attach to a meeting, over the web (`rouh/meeting_attach.py`, night 31's gene `meeting_attach`).

``POST /api/task-docs/attach`` ``{folder, doc}`` answers ``{ok, doc, meetings: [{key, title, when,
attached}]}``, the meetings one of the task's documents could go on; with ``key`` as well it
attaches the document to that meeting's invitation and answers ``{ok, said}``. ``folder`` is the
task's folder as Rouh framed its page (`taskPageFolder` in cards.js), and ``doc`` the document's
id, which has to be one the task's own notes link.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import meeting_attach
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, only, refuse, who


@only("POST")
async def attach(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    sent = body_of(request)
    folder = str(sent.get("folder") or "").strip("/")
    doc = str(sent.get("doc") or "")[:200]
    key = str(sent.get("key") or "")[:40]
    if (not folder or not doc
            or any(p in ("", ".", "..") for p in folder.split("/"))):
        return refuse("Which task, and which of its documents.", 400)
    from rouh import runtime

    google = getattr(runtime, "brief_google", None)
    if key:
        done = await meeting_attach.attach(me, google, config.assistant_repo, folder, doc, key)
    else:
        done = await meeting_attach.offer(me, google, config.assistant_repo, folder, doc)
    if not done.get("ok"):
        return refuse(done.get("error") or "That could not be done.", 400)
    return answer(done, headers=NO_STORE)


__all__ = ["attach"]
