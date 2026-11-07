"""Meta, Gene registry, at /anatomy/meta/gene-pool: shared genes from a registry, and
the lab (`rouh/genelab.py`). Meta, Genes until 4 November 2026.

    GET  /api/settings/genes                    the registry, its genes, the lab, its history
    POST /api/settings/genes/registry           {url, public_key}: point at a registry, pin its key
    POST /api/settings/genes/registry/forget    off again: no registry is asked anything
    POST /api/settings/genes/check              fetch the blocklist and the index now
    POST /api/settings/genes/install            {gene, version, contract_sha256}: into the lab, off
    POST /api/settings/genes/switch             {gene, on}: a gene's own switch
    POST /api/settings/genes/update             {gene, version, contract_sha256}: to a newer version
    POST /api/settings/genes/remove             {gene}: out, and checked
    POST /api/settings/genes/lab                {on}: the whole lab at once
    GET  /api/settings/genes/file?gene=&path=   one of an installed gene's files, as text
    GET  /api/settings/genes/nav                the navigation's links again, after a switch

Every query names the signed-in person's organisation, and only its administrators change
anything. What a gene says comes back as data for the page to draw as text; nothing here
does what a gene's text says.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest
from django.template.loader import render_to_string

from .clock import _signed_in, their_clock
from .common import _text, answer, body_of, only, refuse

log = logging.getLogger("rouh.web.genes")
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import genelab

    return await asyncio.to_thread(genelab.public, me)


async def _do(request, work):
    from rouh import genelab

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        said, found = await asyncio.to_thread(work, me, body)
    except genelab.Refused as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except Exception:  # noqa: BLE001
        log.exception("a change to the gene lab failed")
        return refuse("That could not be done. Nothing was changed; try again.", 500, **(await _page(me)))
    if found:
        # A block or an update the registry has just said is told now, not at the next beat.
        await genelab.tell(me.org_id, found)
    return answer({"ok": True, **said, **(await _page(me))}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


@only("POST")
@their_clock
async def registry(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        found = genelab.point(me, _text(body, "url", 2000), _text(body, "public_key", 4000))
        said = (f"Saved, and nothing was taken from it. {found['error']}" if found.get("error") else
                "Pointed at the registry and pinned its key. Its index and blocklist were fetched, and "
                "both signatures hold.")
        return {"said": said}, found
    return await _do(request, go)


@only("POST")
@their_clock
async def registry_forget(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        genelab.forget(me)
        return {"said": "Rouh asks no registry now. Genes already in the lab stay there."}, None
    return await _do(request, go)


@only("POST")
@their_clock
async def check(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        if not getattr(me, "is_admin", False):
            raise genelab.Refused("Only an administrator of this organisation changes its genes.")
        found = genelab.refresh(me.org_id)
        if found.get("off"):
            raise genelab.Refused("Rouh is not pointed at a gene registry yet.")
        parts = [found["error"]] if found.get("error") else ["Fetched the index and the blocklist; both signatures hold."]
        if found["blocked"]:
            parts.append("Switched off, blocklisted: " + ", ".join(b["name"] for b in found["blocked"]) + ".")
        if found["updates"]:
            parts.append("Updates waiting: " + ", ".join(f"{u['name']} {u['to']}" for u in found["updates"]) + ".")
        return {"said": " ".join(parts)}, found
    return await _do(request, go)


@only("POST")
@their_clock
async def install(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        got = genelab.install(me, _text(body, "gene", 130), _text(body, "version", 40),
                              _text(body, "contract_sha256", 64))
        return {"said": got["said"], "gene": got["gene"]}, None
    return await _do(request, go)


@only("POST")
@their_clock
async def switch(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        return genelab.set_switch(me, _text(body, "gene", 130), bool(body.get("on"))), None
    return await _do(request, go)


@only("POST")
@their_clock
async def update(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        return genelab.update(me, _text(body, "gene", 130), _text(body, "version", 40),
                              _text(body, "contract_sha256", 64)), None
    return await _do(request, go)


@only("POST")
@their_clock
async def remove(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        return genelab.remove(me, _text(body, "gene", 130)), None
    return await _do(request, go)


@only("POST")
@their_clock
async def lab(request: HttpRequest):
    from rouh import genelab

    def go(me, body):
        return genelab.set_lab(me, bool(body.get("on"))), None
    return await _do(request, go)


@only("GET")
@their_clock
async def file(request: HttpRequest):
    from rouh import genelab

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        got = await asyncio.to_thread(genelab.read_file, me, request.GET.get("gene", "")[:130],
                                      request.GET.get("path", "")[:300])
    except genelab.Refused as exc:
        return refuse(str(exc), 404)
    return answer(got, headers=NO_STORE)


def _nav(me) -> dict:
    from rouh import genelab, genes, switches

    org = getattr(me, "org_id", None) or None
    shared = genelab.shared_manifests(org)

    def on(name: str) -> bool:
        return switches.on(name, org)
    # Only the shared genes' rows: they stand last in their groups, and Rouh's own rows keep
    # what the page's code has bound to them.
    groups = {g["id"]: "".join(render_to_string("rouh/_nav_row.html", {"f": f}) for f in g["genes"]
                               if f["shared"])
              for g in genes.nav_groups(on, shared)}
    return {"groups": groups, "genes": genes.for_page(on, shared)}


@only("GET")
@their_clock
async def nav(request: HttpRequest):
    """The navigation's links as the page is drawn with them, so a gene switched on or off
    is there, or gone, without a reload."""
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(_nav, me), headers=NO_STORE)
