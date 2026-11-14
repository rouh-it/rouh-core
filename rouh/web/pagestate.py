"""A page's own settings, over the web (`rouh/pagestate.py`).

``/api/page-state?doc=<page>``, for the signed-in person, carried by Rouh's own
page (``stateRelay`` in cards.js), which says which page it is. A GET answers
with their settings on the page, a POST changes them.
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import askai, pagestate

from .comments import NO_STORE
from .common import answer, body_of, refuse, who


def _page(doc: str) -> str:
    """The page, checked the way opening it is (`askai.resolve`), after any move."""
    from rouh import pageplaces
    from rouh.config import config

    askai.resolve(config.assistant_repo, doc)
    pageplaces.follow()
    return doc


async def for_owner(request: HttpRequest):
    """The signed-in person's settings on one page of the workspace."""
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    body = body_of(request) if request.method == "POST" else {}
    if len(request.body or b"") > pagestate.MOST + 4096:
        return refuse("A page's settings may take %d KB at most." % (pagestate.MOST // 1024), 413)
    doc = str(request.GET.get("doc") or body.get("doc") or "")
    try:
        rel = await asyncio.to_thread(_page, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    if request.method != "POST":
        return answer(await asyncio.to_thread(pagestate.read, me.org_id, me.user_id, rel),
                      headers=NO_STORE)
    from rouh.config import config

    page = await asyncio.to_thread(askai.resolve, config.assistant_repo, rel)
    asks = await asyncio.to_thread(pagestate.saves_beside, page)
    before = (await asyncio.to_thread(pagestate.read, me.org_id, me.user_id, rel))["settings"] if asks else {}
    try:
        saved = await asyncio.to_thread(pagestate.write, me.org_id, me.user_id, rel, body)
    except pagestate.Refused as exc:
        return refuse(str(exc), exc.status)
    if asks:
        # A page that keeps its choices where a job can read them (`pagestate.beside`).
        try:
            saved["file"] = await asyncio.to_thread(pagestate.beside, page, saved["settings"],
                                                    saved["updated_at"], me)
        except OSError as exc:
            saved["file_error"] = f"Saved in Rouh, but the file beside the page was not written: {exc}"
        done = saved["settings"].get(pagestate.DONE)
        if done and done != before.get(pagestate.DONE):
            saved["picked"] = await pagestate.picked(me, config.assistant_repo, rel)
    return answer(saved, headers=NO_STORE)


__all__ = ["for_owner"]
