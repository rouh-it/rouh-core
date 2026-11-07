"""A Google Doc of this page, over the web (`rouh/page_gdoc.py`, night 21's gene `page_gdoc`).

``GET /api/page-gdoc?at=<page>`` says whether the share icon's menu offers Google Doc for one page,
and the document made of it before, if any. ``POST /api/page-gdoc`` ``{at}`` makes the page into its
Google Doc, or puts it into the one made before, and answers ``{ok, made: {id, link, at, title}}``;
``{at, act: "opened"}`` says Open the Google Doc was pressed, which counts as a use. ``at`` is
Share's own word for what the canvas holds (`shareRel` in runs.js), read the way the PDF of a page is.
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import page_gdoc, page_pdf
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
        said = await asyncio.to_thread(page_gdoc.state, me, config.assistant_repo,
                                       str(request.GET.get("at") or ""))
        return answer(said, headers=NO_STORE)
    sent = body_of(request)
    at = str(sent.get("at") or "")
    if sent.get("act") == "opened":
        try:
            await asyncio.to_thread(page_gdoc.opened, me, config.assistant_repo, at)
        except page_pdf.Refused as exc:
            return refuse(str(exc), 409)
        return answer({"ok": True}, headers=NO_STORE)
    from rouh import runtime

    done = await page_gdoc.make(me, getattr(runtime, "brief_google", None),
                                config.assistant_repo, at)
    if not done.get("ok"):
        return refuse(done.get("error") or "The Google Doc could not be made.", 409)
    return answer(done, headers=NO_STORE)


__all__ = ["for_owner"]
