"""The Gene Pool over the web (`rouh/genepool.py`, `genepoolpage.js`), and choosing a gene of the log
for it.

    GET  /api/genes/pool                   the membership, the catalogue, this person's matches, what
                                           this Rouh gave and installed
    POST /api/genes/pool/refresh           read the catalogue again
    POST /api/genes/pool/match             {words?}: the model's picks for this person
    POST /api/genes/pool/install           {node, how: as_is|fork, words?, confirm}
    POST /api/genes/pool/thanks            {node}
    POST /api/genes/pool/update            {gene, confirm}: an installed gene to its giver's newer version
    POST /api/genes/pool/mode              {mode: manual|preselect|auto, confirm}: outgoing, how genes leave
    POST /api/genes/pool/incoming          {mode: manual|off}: incoming, whether the Pool's genes come in
    GET  /api/genes/pool/out               the review list: every gene of the log on its way to the Pool
    GET  /api/genes/pool/out/<id>          one family as it would leave: each node's exact body and checks
    POST /api/genes/pool/out/<id>/approve  {shas: {node id: body hash}}: approved as the page showed it
    POST /api/genes/pool/out/<id>/decline  never sent, and withdrawn if it was
    POST /api/genes/pool/out/<id>/edit     {name?, sentence?, brief?}: what one node sends, edited
    POST /api/genes/log/<id>/share         {share: true|false}: approved, or taken out of the Pool
    POST /api/genes/log/<id>/allow         one sub-gene approved on its own

Everything but reading is an administrator's; the Pool's own answers are checked in genepool. There is
no join and no leave: a Rouh joins at its birth, by itself (`genepool.join_at_birth`; task 141, step
141-15), and what it exchanges is the two settings.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import genelab, genelog, genepool

from .comments import NO_STORE
from .common import _text, answer, body_of, refuse, who

log = logging.getLogger("rouh.web.genepool")
REFUSED = (genepool.Refused, genelog.Refused, genelab.Refused)


async def _me(request: HttpRequest):
    return await sync_to_async(who)(request)


async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET"])
    return answer(await sync_to_async(genepool.public)(me), headers=NO_STORE)


async def _post(request: HttpRequest, act):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        return answer(await act(me, body_of(request)), headers=NO_STORE)
    except REFUSED as exc:
        return refuse(str(exc), 400)


async def refresh(request: HttpRequest):
    async def act(me, body):
        got = await sync_to_async(genepool.refresh)(str(me.org_id))
        n = len(got.get("families") or [])
        return {"ok": True, "said": f"Read the {genepool.NAME}: {n} gene{'s' if n != 1 else ''}."}
    return await _post(request, act)


async def match(request: HttpRequest):
    async def act(me, body):
        try:
            return await genepool.match(me, _text(body, "words", 400))
        except REFUSED:
            raise
        except Exception as exc:  # noqa: BLE001 - said on the page, in words
            log.exception("matching the pool failed")
            raise genepool.Refused(f"No picks came back: {type(exc).__name__}. Ask again in a moment.") from None
    return await _post(request, act)


async def install(request: HttpRequest):
    async def act(me, body):
        if not body.get("confirm"):
            raise genepool.Refused("Confirm it: this starts a run that builds the gene into this Rouh.")
        return await genepool.install(me, _text(body, "node", 40), _text(body, "how", 10),
                                      _text(body, "words", 2000))
    return await _post(request, act)


async def update(request: HttpRequest):
    async def act(me, body):
        if not body.get("confirm"):
            raise genepool.Refused("Confirm it: this starts a run that changes the gene in this Rouh.")
        return await genepool.update(me, body.get("gene"))
    return await _post(request, act)


async def mode(request: HttpRequest):
    async def act(me, body):
        return await sync_to_async(genepool.set_mode)(me, _text(body, "mode", 20), confirm=bool(body.get("confirm")))
    return await _post(request, act)


async def incoming(request: HttpRequest):
    async def act(me, body):
        return await sync_to_async(genepool.set_incoming)(me, _text(body, "mode", 20))
    return await _post(request, act)


async def out(request: HttpRequest, gene_id: int | None = None):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET"])
    try:
        got = await sync_to_async(genepool.review_list if gene_id is None else genepool.review_one)(
            *((me,) if gene_id is None else (me, gene_id)))
    except REFUSED as exc:
        return refuse(str(exc), 404)
    return answer(got, headers=NO_STORE)


async def approve(request: HttpRequest, gene_id: int):
    async def act(me, body):
        shas = body.get("shas")
        return await sync_to_async(genepool.approve)(me, gene_id, shas=shas if isinstance(shas, dict) else None)
    return await _post(request, act)


async def decline(request: HttpRequest, gene_id: int):
    async def act(me, body):
        return await sync_to_async(genepool.decline)(me, gene_id)
    return await _post(request, act)


async def edit(request: HttpRequest, gene_id: int):
    async def act(me, body):
        def one(k):
            return str(body[k]) if isinstance(body.get(k), str) else None
        return await sync_to_async(genepool.edit)(me, gene_id, name=one("name"), sentence=one("sentence"),
                                                  brief=one("brief"))
    return await _post(request, act)


async def thanks(request: HttpRequest):
    async def act(me, body):
        return await sync_to_async(genepool.thanks)(me, _text(body, "node", 40))
    return await _post(request, act)


async def share(request: HttpRequest, gene_id: int):
    async def act(me, body):
        return await sync_to_async(genepool.share)(me, gene_id, bool(body.get("share")))
    return await _post(request, act)


async def allow(request: HttpRequest, gene_id: int):
    async def act(me, body):
        return await sync_to_async(genepool.allow)(me, gene_id)
    return await _post(request, act)


__all__ = ["allow", "approve", "decline", "edit", "incoming", "install", "match", "mode", "out", "page",
           "refresh", "share", "thanks", "update"]
