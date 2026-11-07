"""The gene log over the web: every gene in this Rouh, its family, its use, its mark and evaluation,
and taking it out as its contract says (`rouh/genelog.py`, `rouh/geneuse.py`, `evolutionpage.js`).

    GET  /api/genes/log                    every family, newest change first, with this person's uses
    POST /api/genes/log/read               read what landed now, and ask the gene writer (administrators)
    GET  /api/genes/log/<id>               one gene: its node, family, history, use, mark, evaluation
    POST /api/genes/log/<id>/mark          {mark}: essential, useful, not_for_me, or "" for none
    POST /api/genes/log/<id>/evaluate      the model's evaluation of it, now
    POST /api/genes/log/<id>/turn          {on}: its switch (administrators)
    POST /api/genes/log/<id>/remove        {confirm}: take it out as its contract says (administrators)
    POST /api/genes/log/<id>/draft         {action: grow|night|back|drop|revise, ...}: a gene drafted on the fly
    POST /api/genes/drafts/propose         {value: asked|offer}: may Rouh offer to draft a gene

Every query names the signed-in person's organisation, and their own account for use and marks, so
an id of anybody else's is "not found".
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponseNotAllowed

from rouh import genelog, genepool, geneuse

from .comments import NO_STORE
from .common import answer, body_of, refuse, who

log = logging.getLogger("rouh.web.genelog")


async def _me(request: HttpRequest):
    return await sync_to_async(who)(request)


async def listing(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method not in ("GET", "HEAD"):
        return HttpResponseNotAllowed(["GET"])
    return answer(await sync_to_async(genelog.listing)(me), headers=NO_STORE)


async def gene(request: HttpRequest, gene_id: int):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    got = await sync_to_async(genelog.page)(me, gene_id)
    if got is None:
        return refuse("There is no such gene in this Rouh's gene log.", 404)
    return answer(got, headers=NO_STORE)


async def _post(request: HttpRequest, act):
    me = await _me(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    try:
        return answer(await act(me, body_of(request)), headers=NO_STORE)
    except genelog.Refused as exc:
        return refuse(str(exc), 400)


async def read(request: HttpRequest):
    async def act(me, body):
        if not getattr(me, "is_admin", False):
            raise genelog.Refused("Only an administrator of this Rouh reads its changes into the log.")
        if not await sync_to_async(genelog.on)(str(me.org_id)):
            raise genelog.Refused("The gene log is switched off (gene_log, under Other switches in Evolution, Mutations).")
        got = await sync_to_async(genelog.tick)(me)
        wrote = await genelog.write(me)
        if await sync_to_async(geneuse.on)(str(me.org_id)):
            await sync_to_async(geneuse.rollup)(str(me.org_id))
        # And the genes chosen for the Gene Pool sent, where this Rouh has joined it.
        pooled = await sync_to_async(genepool.tick)(me)
        scan = got.get("scan") or {}
        parts = [f"Read {scan.get('read', 0)} new change" + ("" if scan.get("read") == 1 else "s")]
        if wrote.get("read"):
            parts.append(f"the gene writer put {wrote['read']} to genes ({wrote.get('new', 0)} new, "
                         f"{wrote.get('none', 0)} no gene's)")
        if wrote.get("failed"):
            parts.append(f"{wrote['failed']} wait for the gene writer")
        sent = (pooled.get("sync") or {}) if isinstance(pooled, dict) else {}
        if sent.get("sent"):
            parts.append(f"sent {sent['sent']} to the {genepool.NAME}")
        if sent.get("held"):
            parts.append(f"{sent['held']} node{'s wait' if sent['held'] != 1 else ' waits'} for your review in Your genes for the {genepool.NAME}")
        return {"ok": True, "said": ", ".join(parts) + "."}
    return await _post(request, act)


async def mark(request: HttpRequest, gene_id: int):
    async def act(me, body):
        return await sync_to_async(geneuse.set_mark)(me, gene_id, str(body.get("mark") or ""))
    return await _post(request, act)


async def evaluate(request: HttpRequest, gene_id: int):
    async def act(me, body):
        n = await sync_to_async(genelog._node)(me, gene_id)
        root = await sync_to_async(genelog.root_of)(n)
        try:
            got = await geneuse.evaluate(me, [root.key])
        except Exception as exc:  # noqa: BLE001 - said on the page, in words
            log.exception("gene %s could not be evaluated", gene_id)
            raise genelog.Refused(f"No evaluation came back: {type(exc).__name__}. Try again in a moment.") from None
        if not got.get("scored"):
            raise genelog.Refused(got.get("said") or "No evaluation came back. Try again in a moment.")
        return {"ok": True, "said": f"{root.name} is evaluated for this month."}
    return await _post(request, act)


async def turn(request: HttpRequest, gene_id: int):
    async def act(me, body):
        return await sync_to_async(genelog.turn)(me, gene_id, bool(body.get("on")))
    return await _post(request, act)


async def remove(request: HttpRequest, gene_id: int):
    async def act(me, body):
        if not body.get("confirm"):
            raise genelog.Refused("Confirm it: this starts a run that takes the gene's code out and deploys.")
        return await genelog.remove(me, gene_id)
    return await _post(request, act)


async def draft(request: HttpRequest, gene_id: int):
    """A draft's own actions from its page: grow, night (leave it for the nightly run), back (take it
    back), drop, or revise with the fields changed (`rouh/genedraft.py`)."""
    from rouh import genedraft

    async def act(me, body):
        what = str(body.get("action") or "")
        try:
            if what == "grow":
                if not body.get("confirm"):
                    raise genelog.Refused("Confirm it: this starts a run that builds the gene into Rouh.")
                return await genedraft.grow(me, gene_id)
            if what in ("night", "back"):
                return await sync_to_async(genedraft.leave_for_night)(me, gene_id, what == "night")
            if what == "drop":
                return await sync_to_async(genedraft.drop)(me, gene_id)
            if what == "revise":
                fields = {k: body[k] for k in ("name", "what", "where", "remove") if isinstance(body.get(k), str)}
                return await sync_to_async(genedraft.revise)(me, gene_id, {**fields, "why": "Changed on its page."})
        except genedraft.Refused as exc:
            raise genelog.Refused(str(exc)) from None
        raise genelog.Refused("That is not something a draft does.")
    return await _post(request, act)


async def propose(request: HttpRequest):
    """Genes on the fly: whether Rouh may offer to draft one ({value: asked|offer})."""
    from rouh import genedraft

    async def act(me, body):
        try:
            return await sync_to_async(genedraft.set_propose)(
                me, str(body.get("value") or ""), by=(getattr(me, "name", "") or "you") + ", in Parameters")
        except genedraft.Refused as exc:
            raise genelog.Refused(str(exc)) from None
    return await _post(request, act)


__all__ = ["draft", "evaluate", "gene", "listing", "mark", "propose", "read", "remove", "turn"]
