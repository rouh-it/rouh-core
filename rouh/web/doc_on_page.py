"""On the page yet?, over the web (`rouh/doc_on_page.py`, night 21's gene `doc_on_page`).

``POST /api/task-docs/on-page`` ``{folder, doc}`` says which paragraphs of one Google Doc the
task's notes link to are on the task's pages word for word, and answers ``{ok, text}``.
``folder`` is the task's folder as Rouh framed its page (`taskPageFolder` in cards.js), and
``doc`` the document's id, which has to be one the task's own notes link.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import doc_on_page
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, only, refuse, who


@only("POST")
async def on_page(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    sent = body_of(request)
    folder = str(sent.get("folder") or "").strip("/")
    doc = str(sent.get("doc") or "")[:200]
    if (not folder or not doc
            or any(p in ("", ".", "..") for p in folder.split("/"))):
        return refuse("Which task, and which of its documents.", 400)
    from rouh import runtime

    done = await doc_on_page.check(me, getattr(runtime, "brief_google", None),
                                   config.assistant_repo, folder, doc)
    if not done.get("ok"):
        return refuse(done.get("error") or "That could not be read.", 400)
    return answer(done, headers=NO_STORE)


__all__ = ["on_page"]
