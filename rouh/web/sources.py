"""The Sources page's data, over the web (`rouh/source_check.py`, `sourcespage.js`).

``GET /api/sources?task=<folder>`` lists every page checked for the signed-in person inside one
task's or step's folder, newest first, with how many of its sources to look at (with no folder,
none: Sources belongs to a task); ``GET /api/sources?doc=<page>`` is one page's sources; and
``POST /api/sources`` ``{doc, key, holds}`` keeps his word that a flagged source does hold for
what the page says (or takes it back), and answers with that page's sources as they are now.
``POST /api/sources`` ``{doc, check: true}`` is his press on Check sources: that page, and only
that page, is checked from now (`source_check.ask_for`), and the answer is the page as the list
draws it. Nothing is checked unless he presses it (fr_563bcb1bdb26, 17 October 2026).
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import askai, source_check
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, refuse, who


async def for_owner(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    body = body_of(request) if request.method == "POST" else {}
    doc = str(request.GET.get("doc") or body.get("doc") or "")
    if request.method != "POST" and not doc:
        task = str(request.GET.get("task") or "")
        listed = await sync_to_async(source_check.listing)(me, config.assistant_repo, task)
        if listed.get("pages"):
            # The Sources page is the gene: opening it to look at what its pages cite is its use
            # (GENES.md, "How a gene says it was used"). A refresh while it reads is the same use.
            from rouh import evolution

            await asyncio.to_thread(evolution.used, source_check.SWITCH, "sources_opened", who=me,
                                    detail=f"{task}: {len(listed['pages'])} pages")
        return answer(listed, headers=NO_STORE)
    try:
        await asyncio.to_thread(askai.resolve, config.assistant_repo, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    if request.method != "POST":
        if not await sync_to_async(source_check.on)(me.org_id):
            return answer({"off": True}, headers=NO_STORE)
        said = await sync_to_async(source_check.for_page)(me, doc)
        return answer(said or {"doc": doc, "sources": []}, headers=NO_STORE)
    if body.get("check"):
        try:
            said = await sync_to_async(source_check.ask_for)(me, config.assistant_repo, doc)
        except PermissionError as exc:
            return refuse(str(exc), 403)
        except LookupError as exc:
            return refuse(str(exc), 404)
        source_check.wake()
        return answer(said, headers=NO_STORE)
    try:
        said = await sync_to_async(source_check.hold)(me, doc, str(body.get("key") or ""),
                                                      bool(body.get("holds", True)))
    except PermissionError as exc:
        return refuse(str(exc), 403)
    except LookupError as exc:
        return refuse(str(exc), 404)
    return answer(said, headers=NO_STORE)


__all__ = ["for_owner"]
