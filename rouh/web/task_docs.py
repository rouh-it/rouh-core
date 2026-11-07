"""The task's documents, over the web (`rouh/task_docs.py`, night 20's gene `task_docs`).

``POST /api/task-docs/changes`` ``{folder, doc}`` reads what changed in one Google document a
task's notes link to, since the person last opened the task's page, and answers ``{ok, text}``.
``folder`` is the task's folder as Rouh framed its page (`taskPageFolder` in cards.js), and
``doc`` the document's id, which has to be one the task's own notes link.
``POST /api/task-docs/names`` ``{folder}`` answers ``{ok, names: {id: name}}``, every linked
document's own name from Drive, kept for the next time the page is drawn.
``POST /api/task-docs/add`` ``{folder, link}`` keeps a pasted Google Doc, Sheet or Slides link in
the task's notes and answers ``{ok, doc: {id, kind, url, title}, readable}`` (Add a document,
night 23's gene `doc_add`).
``POST /api/task-docs/comments`` ``{folder, doc?}`` answers ``{ok, docs: {id: [comment]}}``, the open
comments on the task's documents, or on one when ``doc`` is given, which counts as opening them;
``POST /api/task-docs/apply-comments`` ``{folder, doc}`` starts a job that applies one document's
open comments to the task's work (night 26's gene `task_comments`, `rouh/task_comments.py`).
``POST /api/task-docs/rehearse`` ``{folder, doc}`` reads one of its decks slide by slide to rehearse,
``POST /api/task-docs/slide-picture`` ``{folder, doc, slide}`` answers ``{ok, url}``, a picture of one
slide, and ``POST /api/task-docs/rehearsed`` ``{seconds, seen, count}`` keeps a rehearsal that reached
its end as a use (night 27's gene `rehearse`, `rouh/rehearse.py`).
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import rehearse, task_comments, task_docs
from rouh.config import config

from .comments import NO_STORE
from .common import answer, body_of, only, refuse, who


@only("POST")
async def changes(request: HttpRequest):
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

    done = await task_docs.changes(me, getattr(runtime, "brief_google", None),
                                   config.assistant_repo, folder, doc)
    if not done.get("ok"):
        return refuse(done.get("error") or "That could not be read.", 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def names(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    folder = str(body_of(request).get("folder") or "").strip("/")
    if not folder or any(p in ("", ".", "..") for p in folder.split("/")):
        return refuse("Which task.", 400)
    from rouh import runtime

    done = await task_docs.names(me, getattr(runtime, "brief_google", None),
                                 config.assistant_repo, folder)
    if not done.get("ok"):
        return refuse(done.get("error") or "The names could not be read.", 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def add(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    sent = body_of(request)
    folder = str(sent.get("folder") or "").strip("/")
    link = str(sent.get("link") or "")[:2000]
    if not folder or not link or any(p in ("", ".", "..") for p in folder.split("/")):
        return refuse("Which task, and which document.", 400)
    from rouh import runtime

    done = await task_docs.add(me, getattr(runtime, "brief_google", None),
                               config.assistant_repo, folder, link)
    if not done.get("ok"):
        return refuse(done.get("error") or "That could not be added.", 400)
    return answer(done, headers=NO_STORE)


def _folder_and_doc(request: HttpRequest, need_doc: bool) -> tuple[str, str] | None:
    sent = body_of(request)
    folder = str(sent.get("folder") or "").strip("/")
    doc = str(sent.get("doc") or "")[:200]
    if (not folder or (need_doc and not doc)
            or any(p in ("", ".", "..") for p in folder.split("/"))):
        return None
    return folder, doc


@only("POST")
async def comments(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = _folder_and_doc(request, False)
    if asked is None:
        return refuse("Which task.", 400)
    from rouh import runtime

    done = await task_comments.open_comments(me, getattr(runtime, "brief_google", None),
                                             config.assistant_repo, *asked)
    if not done.get("ok"):
        return refuse(done.get("error") or "The comments could not be read.", 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def apply_comments(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = _folder_and_doc(request, True)
    if asked is None:
        return refuse("Which task, and which of its documents.", 400)
    from rouh import runtime

    done = await task_comments.apply(me, getattr(runtime, "brief_google", None),
                                     config.assistant_repo, *asked)
    if not done.get("ok"):
        return refuse(done.get("error") or "The job could not be started.", 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def rehearse_deck(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = _folder_and_doc(request, True)
    if asked is None:
        return refuse("Which task, and which of its decks.", 400)
    from rouh import runtime

    done = await rehearse.deck(me, getattr(runtime, "brief_google", None), config.assistant_repo, *asked)
    if not done.get("ok"):
        return refuse(done.get("error") or "The deck could not be read.", 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def slide_picture(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = _folder_and_doc(request, True)
    slide = str(body_of(request).get("slide") or "")[:200]
    if asked is None or not slide:
        return refuse("Which task, which deck and which slide.", 400)
    from rouh import runtime

    done = await rehearse.picture(me, getattr(runtime, "brief_google", None), config.assistant_repo,
                                  *asked, slide)
    if not done.get("ok"):
        return refuse(done.get("error") or "No picture of that slide.", 400)
    return answer(done, headers=NO_STORE)


@only("POST")
async def rehearsed(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    sent = body_of(request)
    try:
        seconds, seen, count = float(sent.get("seconds") or 0), int(sent.get("seen") or 0), int(sent.get("count") or 0)
    except (TypeError, ValueError):
        return refuse("How long, and how many slides.", 400)
    if not await sync_to_async(rehearse.on)(me.org_id):
        return refuse("Rehearse is switched off.", 400)
    done = await sync_to_async(rehearse.rehearsed)(me, max(0.0, seconds), max(0, seen), max(0, count))
    return answer(done, headers=NO_STORE)


__all__ = ["add", "apply_comments", "changes", "comments", "names", "rehearse_deck", "rehearsed",
           "slide_picture"]
