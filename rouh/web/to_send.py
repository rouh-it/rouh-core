"""To send from your mail, over the web (`rouh/to_send.py`, night 24's gene `to_send`).

``POST /api/to-send`` ``{folder, n, do, subject}``: one press on a reply waiting on a task's page,
``opened`` (Write it in Gmail was pressed), ``let_go`` (Not sending) or ``undo``. ``folder`` is
the task's folder as Rouh framed its page (`taskPageFolder` in cards.js), ``n`` the reply's place
in the task's `sends_himself` list and ``subject`` its subject, which has to match.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import to_send
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
        done = await sync_to_async(to_send.act)(me, config.assistant_repo, folder, sent.get("n"),
                                                str(sent.get("do") or ""),
                                                str(sent.get("subject") or ""))
    except to_send.Refused as exc:
        return refuse(str(exc), 409)
    return answer(done, headers=NO_STORE)


__all__ = ["press"]
