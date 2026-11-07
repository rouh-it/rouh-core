"""Comments pinned to a page, over the web (`rouh/comments.py`).

Two doors onto the same threads, one for each kind of person who can open the
page as themselves:

- **The owner**, on Rouh's canvas: ``/api/comments?doc=<page>``. The page in
  the frame cannot call out, so Rouh's own page carries what it asks
  (``askRelay`` in app.js) and decides which page it is about from the frame
  it is showing, never from anything the page says.
- **A person the page was shared with**, on their reader's page:
  ``/shared/<token>/comments``. The token names the page and is held to the
  person signed in (`guests._reader`); the threads are the owner's, because a
  shared page's comments are one conversation, and the person is who they are.

Both answer a GET with what the page draws (the threads, the people who can be
tagged, who is looking, and Ask AI's pass over them when there is one) and a
POST with one thing done, named by ``do``: ``start``, ``reply``, ``edit``,
``delete``, ``resolve``, ``reopen``, ``move``, ``snapshot``, and ``ai_pass``, which has
Ask AI answer every open thread (`rouh/commentpass.py`). What a message that
tags people did about their letters comes back with it, so the page can say
who was emailed and who was not.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import askai, commentpass, comments, pages
from rouh.config import config

from .common import answer, body_of, refuse, who

NO_STORE = {"Cache-Control": "no-store, private"}


@dataclass(frozen=True)
class Asking:
    """Whether this reader may have Ask AI answer the page's comments, and on
    what terms: whose chat its report goes into (``who``), how many questions
    a day they may ask (0 for no limit), and whether it reads the whole
    folder and project (``wide``, the owner's)."""

    who: object
    allowed: bool
    most_a_day: int = 0
    wide: bool = False


def _rt():
    from rouh import runtime

    return runtime


async def _letters(place, me, said) -> list[dict]:
    return await comments.send_letters(config, place, me, said)


async def _do(place: comments.Place, me: comments.Person, asked: dict,
              asking: Asking) -> dict:
    """One thing done to the page's comments, as the page asked for it."""
    do = str(asked.get("do") or "")
    if do == "ai_pass":
        if not asking.allowed:
            raise comments.Refused("Only somebody who may change this page can have Ask AI "
                                   "answer its comments.", 403)
        return {"pass": await commentpass.start(
            config, _rt().ask_threads, place, me, asking.who, asked, wide=asking.wide,
            most_a_day=asking.most_a_day)}
    if do == "start":
        thread, said = await asyncio.to_thread(
            comments.start, place, me, asked.get("anchor"), asked.get("snapshot"),
            asked.get("body"), asked.get("mentions"))
        return {"thread": thread, "letters": await _letters(place, me, said)}
    if do in ("reply", "edit"):
        if do == "reply":
            message, said = await asyncio.to_thread(
                comments.reply, place, me, asked.get("thread"), asked.get("body"),
                asked.get("mentions"))
        else:
            message, said = await asyncio.to_thread(
                comments.edit, place, me, asked.get("message"), asked.get("body"),
                asked.get("mentions"))
        return {"message": message, "thread": said["thread"],
                "letters": await _letters(place, me, said)}
    if do == "move":
        return await asyncio.to_thread(comments.move, place, me, asked.get("thread"),
                                       asked.get("anchor"), asked.get("snapshot"))
    if do in ("resolve", "reopen"):
        return await asyncio.to_thread(comments.resolve, place, me, asked.get("thread"),
                                       do == "resolve")
    if do == "delete":
        if asked.get("message") is not None:
            return await asyncio.to_thread(comments.remove_message, place, me,
                                           asked.get("message"))
        return await asyncio.to_thread(comments.remove_thread, place, me, asked.get("thread"))
    if do == "snapshot":
        return {"thread": asked.get("thread"),
                "snapshot": await asyncio.to_thread(comments.snapshot, place,
                                                    asked.get("thread"))}
    raise comments.Refused("That is not something a comment can have done to it.")


async def _answer(request: HttpRequest, place: comments.Place, me: comments.Person,
                  asking: Asking):
    if request.method in ("GET", "HEAD"):
        listed = await asyncio.to_thread(comments.listing, place, me)
        listed["pass"] = commentpass.status(place, me)
        return answer(listed, headers=NO_STORE)
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    try:
        return answer(await _do(place, me, body_of(request), asking), headers=NO_STORE)
    except comments.Refused as exc:
        return refuse(str(exc), exc.status)


def _owner_place(me, doc: str) -> comments.Place:
    """The owner's own page, or Unavailable when `doc` is not one of their pages."""
    from rouh import pageplaces

    page = askai.resolve(config.assistant_repo, doc)
    # Comments made before its folder moved are this page's too.
    pageplaces.follow()
    return comments.Place(org_id=me.org_id, owner_id=me.user_id, rel=doc,
                          title=pages.title_of(page))


async def for_owner(request: HttpRequest):
    """The comments on one of the signed-in person's own pages."""
    me = await sync_to_async(who)(request)
    person = comments.person_of(getattr(request, "user", None), owner=True)
    if me is None or person is None:
        return refuse("Sign in to Rouh first.", 401)
    doc = str(request.GET.get("doc") or body_of(request).get("doc") or "")
    try:
        place = await asyncio.to_thread(_owner_place, me, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    return await _answer(request, place, person, Asking(who=me, allowed=True, wide=True))


async def for_reader(request: HttpRequest, kind: str, token: str):
    """The comments on a page shared with the person signed in."""
    from .guests import _reader

    reader = await _reader(request, kind, token)
    if reader is None or not reader.comments:
        return refuse("That page is not shared with you.", 404)
    person = comments.person_of(request.user, owner=False)
    if person is None:
        return refuse("That page is not shared with you.", 404)
    place = comments.Place(org_id=reader.org_id, owner_id=reader.owner_id, rel=reader.rel,
                           title=reader.title)
    return await _answer(request, place, person,
                         Asking(who=reader.who, allowed=reader.can_edit,
                                most_a_day=reader.most_a_day))


async def for_shared(request: HttpRequest, token: str):
    """`/shared/<token>/comments`."""
    return await for_reader(request, "shared", token)


__all__ = ["for_owner", "for_reader", "for_shared"]
