"""The PDF button beside Share, over the web (`rouh/page_pdf.py`, version 2 of the gene `page_pdf`).

``GET /api/page-pdf?at=<page>`` says what the button shows for one page: nothing while the switch
is off or there is no page to print, else whether a PDF of it is already kept and still as new as
the page, and whether one is being made. ``POST /api/page-pdf`` ``{at, paper}`` starts the making
and answers at once; Rouh's notifications say when it is ready (`page_pdf.make_and_tell`).
``at`` is Share's own word for what the canvas holds (`shareRel` in runs.js).
``{chat, at, paper}`` makes a chat's PDF instead, kept in the task at ``at`` (`page_pdf.make_chat`).
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import page_pdf
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, refuse, who


async def for_owner(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    if request.method != "POST":
        said = await asyncio.to_thread(page_pdf.state, me, config.assistant_repo,
                                       str(request.GET.get("at") or ""))
        return answer(said, headers=NO_STORE)
    body = body_of(request)
    try:
        if body.get("chat"):
            # A chat, from its own three dots on its task's page: ``at`` is that task's folder.
            said = await page_pdf.make_chat_and_tell(me, config.assistant_repo, str(body["chat"]),
                                                     str(body.get("at") or ""),
                                                     str(body.get("paper") or "letter"))
        else:
            said = await page_pdf.make_and_tell(me, config.assistant_repo, str(body.get("at") or ""),
                                                str(body.get("paper") or "letter"))
    except page_pdf.Refused as exc:
        return refuse(str(exc), 409)
    return answer(said, status=202, headers=NO_STORE)


__all__ = ["for_owner"]
