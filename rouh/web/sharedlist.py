"""A page's shared list over the web (`rouh/sharedlist.py`), and a name's checks for a guest.

- ``/api/page-list?doc=<page>``: the owner's organisation, carried by Rouh's own page
  (``askRelay`` in cards.js, the page's ``/api/list``). A guest's account is refused here.
- ``/shared/<token>/list``: a person the page, or the task it is in, is shared with
  (``reader.js``). They read it; they change it only when they may change the page.
- ``/shared/<token>/checks``: the same person's domain checks (``do: domains``) when they may
  change the page, and the trade mark state the owner's runs left (``do: trademark_status``).
  Starting a trade mark run spends the owner's model, so it stays the owner's own.

GET (or a POST with ``op: get``) reads, with ``since`` the version the page already has;
a POST with ``op`` add, remove or edit changes one entry. Which page and which organisation
it is are Rouh's answer, never the page's: the frame Rouh loaded, or the share's own token.
"""
from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import askai, name_checks, sharedlist

from .comments import NO_STORE
from .common import answer, body_of, refuse, who

BODY_MOST = 16 * 1024


def _since(raw):
    try:
        return int(str(raw))
    except (TypeError, ValueError):
        return None


def _page(rel: str):
    from rouh import pageplaces
    from rouh.config import config

    page = askai.resolve(config.assistant_repo, rel)
    pageplaces.follow()
    return page


async def _serve(request: HttpRequest, org_id: str, rel: str, page, person, may_change: bool):
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])
    if len(request.body or b"") > BODY_MOST:
        return refuse("That is more than one entry.", 413)
    body = body_of(request) if request.method == "POST" else {}
    key = str(request.GET.get("key") or body.get("key") or "")
    if key not in await asyncio.to_thread(sharedlist.lists_of, page):
        return refuse("This page keeps no shared list of that name.", 404)
    op = str(body.get("op") or "get")
    try:
        if op == "get":
            said = await asyncio.to_thread(sharedlist.read, org_id, rel, key,
                                           _since(request.GET.get("since", body.get("since"))))
        elif not may_change:
            return refuse("This page is shared with you to read: the list cannot be changed here.", 403)
        else:
            said = await asyncio.to_thread(sharedlist.change, org_id, rel, key, body, person)
            said["file"] = await asyncio.to_thread(sharedlist.beside, page, org_id, rel)
    except sharedlist.Refused as exc:
        return refuse(str(exc), exc.status)
    return answer(said, headers=NO_STORE)


async def for_owner(request: HttpRequest):
    from rouh.tenancy import GUEST_ORG

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if me.org_id == GUEST_ORG:
        return refuse("That page is not yours: open it from what is shared with you.", 404)
    doc = str(request.GET.get("doc") or "")
    if not doc and request.method == "POST":
        doc = str(body_of(request).get("doc") or "")
    try:
        page = await asyncio.to_thread(_page, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    return await _serve(request, me.org_id, doc, page, me, True)


async def for_shared(request: HttpRequest, token: str):
    from .guests import _reader

    reader = await _reader(request, "shared", token)
    if reader is None:
        return refuse("That page is not shared with you.", 404)
    try:
        page = await asyncio.to_thread(_page, reader.rel)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    return await _serve(request, reader.org_id, reader.rel, page, reader.who, reader.can_edit)


async def checks_shared(request: HttpRequest, token: str):
    from rouh.config import config
    from rouh.tenancy import Identity

    from .guests import _reader

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    reader = await _reader(request, "shared", token)
    if reader is None:
        return refuse("That page is not shared with you.", 404)
    try:
        page = await asyncio.to_thread(_page, reader.rel)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    asked = body_of(request)
    what = str(asked.get("do") or "")
    try:
        if what == "domains":
            if not reader.can_edit:
                return refuse("This page is shared with you to read: names are checked by "
                              "whoever may change it.", 403)
            said = await name_checks.domains(asked.get("spellings"))
            await asyncio.to_thread(sharedlist.record_domains, reader.org_id, reader.rel, page, said)
        elif what == "trademark_status":
            owner = Identity(user_id=reader.owner_id, org_id=reader.org_id)
            said = await name_checks.trademark_status(owner, str(config.assistant_repo),
                                                      reader.rel, asked.get("words"))
        elif what == "trademark":
            return refuse("Only the page's owner can start a trade mark check: it starts a run "
                          "on their account.", 403)
        else:
            return refuse("That is not a check this page can ask for.", 400)
    except name_checks.Refused as exc:
        return refuse(str(exc), exc.status)
    return answer(said, headers=NO_STORE)


__all__ = ["checks_shared", "for_owner", "for_shared"]
