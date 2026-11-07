"""The Vocabulary page of the Synapse lab, `/synapse/vocabulary`: every entry of the person's vocabulary, to search,
add, change and delete (`rouh/vocabulary.py`).

    GET  /api/vocabulary            {"entries": [...], "master", "silos"}
    POST /api/vocabulary/add        {"term", "meaning", "aliases"?, "context"?, "silos"?}: a new entry (the same
                                    word again changes the one there is)
    POST /api/vocabulary/edit       {"id", "term", "meaning", "aliases"?, "context"?, "silos"?}
    POST /api/vocabulary/delete     {"id"}

`aliases` is a list of other names, or one text with commas between them; `context` is [{type, id, name}], what
the entry is about (`/api/rules/targets` finds them); `silos` the silos it is in, by key. Every write answers
with the whole page again, so what is drawn is what is kept. Whose: the signed-in person's Master
(`Tenancy.current`, via `who`).
"""
from __future__ import annotations

import logging
import time

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from .common import answer, body_of, only, refuse, who

log = logging.getLogger(__name__)

NO_STORE = {"Cache-Control": "no-store"}


def _page(me) -> dict:
    from rouh import rules, silos, vocabulary

    ds = rules.master(me.user_id, me.org_id)
    # What is left of the person's old words on the Rules page comes here first (`vocabulary.settle`).
    vocabulary.settle(ds)
    return {"entries": vocabulary.entries(ds), "master": ds["name"],
            "silos": [s.chip() for s in silos.of(me.user_id, me.org_id)], "definition": vocabulary.DEFINITION}


def _do(me, what: str, body: dict, by: str):
    from rouh import rules, vocabulary

    ds = rules.master(me.user_id, me.org_id)
    silos = body.get("silos") if isinstance(body.get("silos"), list) else None
    context = body.get("context") if isinstance(body.get("context"), list) else None
    if what == "add":
        here = rules.origin_of("you", f"Added by you on the Vocabulary page, {rules._day(time.time())}.")
        return vocabulary.add(ds, body.get("term") or "", body.get("meaning") or "", aliases=body.get("aliases") or [],
                              context=context or [], silos=silos, by=by, origin=here)
    if what == "edit":
        return vocabulary.edit(ds, str(body.get("id") or ""), body.get("term") or "", body.get("meaning") or "",
                               aliases=body.get("aliases") or [], context=context, silos=silos, by=by)
    if what == "delete":
        return vocabulary.delete(ds, str(body.get("id") or ""), by=by)
    raise ValueError(what)


def _by(request) -> str:
    name = getattr(getattr(request, "user", None), "username", "") or "someone"
    return f"{name} on the Vocabulary page"


@only("GET")
async def page(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    return answer(await sync_to_async(_page)(me), headers=NO_STORE)


def _post(what: str):
    @only("POST")
    async def view(request: HttpRequest):
        me = await sync_to_async(who)(request)
        if me is None:
            return refuse("sign in", 401)
        try:
            got = await sync_to_async(_do)(me, what, body_of(request), _by(request))
        except (ValueError, LookupError) as exc:
            return refuse(str(exc), 400, **(await sync_to_async(_page)(me)))
        if got is None or got is False:
            return refuse("That entry is not there any more.", 404, **(await sync_to_async(_page)(me)))
        return answer({"ok": True, "entry": got if isinstance(got, dict) else None,
                       **(await sync_to_async(_page)(me))}, headers=NO_STORE)
    return view


add = _post("add")
edit = _post("edit")
delete = _post("delete")
