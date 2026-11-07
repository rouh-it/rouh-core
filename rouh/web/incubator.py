"""The Incubator's page, at /evolution/incubator, and `rouh-incubator`'s door (`rouh/incubator.py`).

    GET  /api/incubator                      every idea (without its whole text), the counts, the lists to
                                             choose from, and this person's own settings for the page
    GET  /api/incubator/<n>                  one idea whole: its text in sections, its history, what is merged in
    POST /api/incubator/new                  {"title", "text"?, "kind"?, "gene"?, "category"?, "tags"?}
    POST /api/incubator/<n>                  {"title"?, "kind"?, "gene"?, "category"?, "tags"?, "notes"?}
    POST /api/incubator/<n>/status           {"status", "note"?, "into"?}; Go hands it to Gene therapy
    POST /api/incubator/<n>/merge            {"into"}
    POST /api/incubator/<n>/link             {"kind", "label", "href"?}
    POST /api/incubator/<n>/score            {"stars": 1-3 or null} the person's stars; {"part", "value"} a part
                                             set by hand (null gives it back to Rouh); {"rescore": true}
    POST /api/incubator/scoring              {"force"?}: score every idea not scored yet (or every one) now
    POST /api/incubator/bulk                 {"ids": [n...], "status"? , "category"?, "into"?}
    POST /api/incubator/prefs                the page's own settings: columns, order, widths, sort, saved views,
                                             and the filters: labels chosen and hidden, dates, search, view
    POST /api/incubator/chat                 the Incubator's own chat, made if it is not there yet

    GET/POST /internal/incubator             the same from a job, a run or a terminal on this machine
                                             (`bin/rouh-incubator`), for the installation's one person

Only the signed-in person's own ideas, asked for by their organisation and account together.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from .common import answer, body_of, from_this_machine, only, refuse, who

log = logging.getLogger(__name__)
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(who, request)


def _refused(exc):
    from rouh import incubator

    if isinstance(exc, incubator.NotFound):
        return refuse(str(exc), 404)
    return refuse(str(exc), 400)


def _everything(me) -> dict:
    from rouh import incubator

    from rouh import incubator_score

    incubator.follow(me)
    return {"ok": True, "ideas": incubator.listing(me), "counts": incubator.counts(me),
            "facts": incubator.facts(), "prefs": incubator.prefs(me), "chat": incubator.chat_id_for(me),
            "scoring": incubator_score.progress_of(me)}


@only("GET")
async def listing(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(_everything, me), headers=NO_STORE)


async def _change(me, fn):
    from rouh import incubator

    try:
        got = await asyncio.to_thread(fn)
    except (incubator.NotFound, incubator.Refused) as exc:
        return _refused(exc)
    return answer({"ok": True, **(got if isinstance(got, dict) and "idea" in got else {"idea": got})},
                  headers=NO_STORE)


async def idea(request: HttpRequest, number: int):
    from rouh import incubator

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if request.method == "GET":
        try:
            got = await asyncio.to_thread(lambda: (incubator.follow(me), incubator.one(me, number))[1])
        except incubator.NotFound as exc:
            return refuse(str(exc), 404)
        return answer({"ok": True, "idea": got}, headers=NO_STORE)
    if request.method != "POST":
        return refuse("GET or POST.", 405)
    body = body_of(request)
    fields = {k: body.get(k) for k in incubator.EDITABLE if k in body}
    return await _change(me, lambda: incubator.edit(me, number, by="you", **fields))


@only("POST")
async def new(request: HttpRequest):
    from rouh import incubator

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    b = body_of(request)
    return await _change(me, lambda: incubator.add(
        me, title=str(b.get("title") or ""), text=str(b.get("text") or ""), kind=str(b.get("kind") or ""),
        gene=str(b.get("gene") or ""), category=str(b.get("category") or ""), tags=b.get("tags") or [],
        source="person", by="you"))


async def _status(me, number, status: str, *, note: str = "", into=None, by: str = "you"):
    from rouh import incubator

    if str(status).lower() == "go":
        try:
            got = await incubator.go(me, number, by=by, author=getattr(me, "name", "") or by)
        except (incubator.NotFound, incubator.Refused) as exc:
            return {"ok": False, "error": str(exc), "code": 404 if isinstance(exc, incubator.NotFound) else 400}
        return got
    try:
        return {"ok": True, "idea": await asyncio.to_thread(
            lambda: incubator.set_status(me, number, status, by=by, note=note, into=into))}
    except (incubator.NotFound, incubator.Refused) as exc:
        return {"ok": False, "error": str(exc), "code": 404 if isinstance(exc, incubator.NotFound) else 400}


@only("POST")
async def status(request: HttpRequest, number: int):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    b = body_of(request)
    got = await _status(me, number, str(b.get("status") or ""), note=str(b.get("note") or ""), into=b.get("into"))
    if got.get("error"):
        return refuse(got["error"], got.get("code", 400))
    return answer(got, headers=NO_STORE)


@only("POST")
async def score(request: HttpRequest, number: int):
    """One click on a star, or a part changed in place: saved at once, with no question asked."""
    from rouh import incubator, incubator_score

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    b = body_of(request)
    if b.get("rescore"):
        try:
            got = await incubator_score.rescore(me, number)
        except (incubator.NotFound, incubator.Refused) as exc:
            return _refused(exc)
        return answer({"ok": True, "idea": got}, headers=NO_STORE)
    if "stars" in b:
        return await _change(me, lambda: incubator_score.set_stars(me, number, b.get("stars"), by="you"))
    return await _change(me, lambda: incubator_score.set_part(me, number, str(b.get("part") or ""), b.get("value"),
                                                              by="you"))


@only("POST")
async def scoring(request: HttpRequest):
    from rouh import incubator_score

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    got = await incubator_score.start_all(me, force=bool(body_of(request).get("force")))
    return answer({"ok": True, "scoring": got}, headers=NO_STORE)


@only("POST")
async def merge(request: HttpRequest, number: int):
    from rouh import incubator

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    into = body_of(request).get("into")
    return await _change(me, lambda: incubator.merge(me, number, into, by="you"))


@only("POST")
async def link(request: HttpRequest, number: int):
    from rouh import incubator

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    b = body_of(request)
    return await _change(me, lambda: incubator.link(me, number, kind=str(b.get("kind") or "link"),
                                                    label=str(b.get("label") or ""), href=str(b.get("href") or ""),
                                                    by="you"))


async def _bulk(me, b: dict, by: str = "you") -> dict:
    from rouh import incubator

    ids = [i for i in (b.get("ids") or []) if i is not None][:1000]
    status_to = str(b.get("status") or "")
    if status_to == "merged" or b.get("into"):
        done, failed = [], []
        for i in ids:
            try:
                await asyncio.to_thread(incubator.merge, me, i, b.get("into"), by=by)
                done.append(str(i))
            except (incubator.NotFound, incubator.Refused) as exc:
                failed.append({"id": str(i), "why": str(exc)})
        return {"ok": True, "done": done, "failed": failed}
    if status_to == "go":
        done, failed = [], []
        for i in ids:
            got = await _status(me, i, "go", by=by)
            (done.append(str(i)) if got.get("ok") else failed.append({"id": str(i), "why": got.get("error") or got.get("said")}))
        return {"ok": True, "done": done, "failed": failed}
    got = await asyncio.to_thread(lambda: incubator.bulk(me, ids, status=status_to,
                                                         category=str(b.get("category") or ""), by=by))
    return {"ok": True, **got}


@only("POST")
async def bulk(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _bulk(me, body_of(request)), headers=NO_STORE)


@only("POST")
async def prefs(request: HttpRequest):
    from rouh import incubator

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        got = await asyncio.to_thread(incubator.put_prefs, me, body_of(request).get("prefs"))
    except incubator.Refused as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "prefs": got}, headers=NO_STORE)


@only("POST")
async def chat(request: HttpRequest):
    from rouh import incubator

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer({"ok": True, "chat": await asyncio.to_thread(incubator.ensure_chat, me)}, headers=NO_STORE)


# --- rouh-incubator, from this machine -----------------------------------------------------------


def _owner():
    from rouh.tenancy import Tenancy

    return Tenancy().only_person()


@csrf_exempt
@only("GET", "POST")
async def internal(request: HttpRequest):
    """`bin/rouh-incubator`: list, read, add, edit, status (Go too), merge, link, import, and the scores:
    score (read one), set (a part or the stars), rescore (one, or every idea) and scoring (how far)."""
    from rouh import incubator, incubator_score

    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."}, status=403)
    me = await asyncio.to_thread(_owner)
    if me is None:
        return answer({"ok": False, "error": "This Rouh has no one person to keep an Incubator for."}, status=400)
    b = body_of(request) if request.method == "POST" else dict(request.GET.items())
    action = str(b.get("action") or "list")
    by = " ".join(str(b.get("by") or "").split())[:120] or "a job on this machine"
    try:
        if action == "list":
            got = await asyncio.to_thread(lambda: incubator.listing(
                me, q=str(b.get("q") or ""), status=b.get("status") or None, category=b.get("category") or None,
                kind=b.get("kind") if b.get("kind") not in (None, "") else None, source=b.get("source") or None,
                tag=str(b.get("tag") or ""), sort=str(b.get("sort") or "number"), limit=int(b.get("limit") or 0)))
            return answer({"ok": True, "ideas": got, "lines": [incubator.line_for_model(v) for v in got]})
        if action == "read":
            got = await asyncio.to_thread(incubator.one, me, b.get("id"))
            return answer({"ok": True, "idea": got, "text": incubator.detail_for_model(got, most=10 ** 7)})
        if action == "add":
            got = await asyncio.to_thread(lambda: incubator.add(
                me, title=str(b.get("title") or ""), text=str(b.get("text") or ""), kind=str(b.get("kind") or ""),
                gene=str(b.get("gene") or ""), category=str(b.get("category") or ""), tags=b.get("tags") or [],
                source=str(b.get("source") or "nightly"), ref=str(b.get("ref") or ""),
                links=b.get("links") or [], by=by))
            return answer({"ok": True, "idea": got})
        if action == "edit":
            fields = {k: b.get(k) for k in incubator.EDITABLE if k in b}
            got = await asyncio.to_thread(lambda: incubator.edit(me, b.get("id"), by=by, **fields))
            return answer({"ok": True, "idea": got})
        if action == "status":
            got = await _status(me, b.get("id"), str(b.get("status") or ""), note=str(b.get("note") or ""),
                                into=b.get("into"), by=by)
            return answer(got, status=got.get("code", 200) if got.get("error") else 200)
        if action == "merge":
            got = await asyncio.to_thread(lambda: incubator.merge(me, b.get("id"), b.get("into"), by=by))
            return answer({"ok": True, "idea": got})
        if action == "link":
            got = await asyncio.to_thread(lambda: incubator.link(
                me, b.get("id"), kind=str(b.get("kind") or "link"), label=str(b.get("label") or ""),
                href=str(b.get("href") or ""), path=str(b.get("path") or ""), by=by))
            return answer({"ok": True, "idea": got})
        if action == "score":
            got = await asyncio.to_thread(incubator.one, me, b.get("id"))
            return answer({"ok": True, "idea": got, "text": incubator.line_for_model(got) + "\n" + incubator_score.explain(got)})
        if action == "set":
            part = str(b.get("part") or "")
            got = await asyncio.to_thread(lambda: incubator_score.set_part(me, b.get("id"), part, b.get("value"), by=by))
            return answer({"ok": True, "idea": got, "text": incubator.line_for_model(got)})
        if action == "rescore":
            if b.get("all"):
                state = await incubator_score.start_all(me, force=bool(b.get("force")))
                return answer({"ok": True, "scoring": state})
            got = await incubator_score.rescore(me, b.get("id"))
            return answer({"ok": True, "idea": got, "text": incubator.line_for_model(got) + "\n" + incubator_score.explain(got)})
        if action == "scoring":
            return answer({"ok": True, "scoring": await asyncio.to_thread(incubator_score.progress_of, me)})
        if action == "import":
            from rouh import incubator_import, owning

            root = owning._workspace()
            if not root:
                return answer({"ok": False, "error": "There is no workspace on this machine to import from."}, status=400)
            got = await asyncio.to_thread(lambda: incubator_import.run(
                me, root, project=str(b.get("project") or ""), nightly=str(b.get("nightly") or ""),
                nursery=str(b.get("nursery") or ""), mark=bool(b.get("mark")), by=by))
            try:
                from rouh import runtime

                await runtime.announce_objects()
            except Exception:  # noqa: BLE001 - every screen reads the rows on its next look
                log.exception("the renamed tasks could not be announced")
            return answer({"ok": True, "report": got})
    except (incubator.NotFound, incubator.Refused) as exc:
        return answer({"ok": False, "error": str(exc)}, status=404 if isinstance(exc, incubator.NotFound) else 400)
    return answer({"ok": False, "error": "action is list, read, add, edit, status, merge, link, import, score, set, "
                                         "rescore or scoring."}, status=400)
