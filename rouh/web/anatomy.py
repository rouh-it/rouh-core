"""Anatomy, at /anatomy (`rouh/anatomy.py`, `genes.ANATOMY`).

    GET  /api/anatomy               the status board: Anatomy's groups in order, each with
                                    what needs attention in its sections
    GET  /settings[/<section>...]   Settings' old addresses, sent on to the group page that has
    GET  /heartbeat                 that section now, at the section (`old_address`), except a
                                    section moved on 4 November 2026, which is not found
    GET  /anatomy/meta/birthday     rouh.land's return address, with ?birth= or ?recovery= only
                                    (`rouh_land_return`)

Petar, 14 October 2026 (card 1554): Settings is Anatomy's groups, You, Connections, Behaviour,
Money and Meta, each a page of its own that stacks its sections; the links that repeated Settings'
pages are gone, and an old address lands on the section it named. Rouh Land Account joined them
on 4 November 2026, and what moved that day was moved, not forwarded: "when I say move, don't
leave backup forwarding links" (`genes.MOVED`). Every query names the signed-in person's user and
organisation.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import Http404, HttpRequest, HttpResponseRedirect

from rouh import addressing, genes

from .clock import _signed_in, their_clock
from .common import answer, only, refuse

log = logging.getLogger("rouh.web.anatomy")
NO_STORE = {"Cache-Control": "no-store"}


@only("GET")
@their_clock
async def board(request: HttpRequest):
    from rouh import anatomy, switches

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    org = getattr(me, "org_id", None) or None
    return answer(await asyncio.to_thread(anatomy.board, me, lambda name: switches.on(name, org)),
                  headers=NO_STORE)


def old_address(request: HttpRequest, rest: str = ""):
    """A Settings address from before Anatomy: `/settings` lands on the status board, and
    `/settings/<section>` and anything under it (`/settings/beats/12`) on the group page that
    holds that section now, at the section. `/heartbeat`, the heartbeat's own page for a day,
    lands on its section too. Anything after the `?` is kept."""
    query = request.META.get("QUERY_STRING", "")
    if request.path.rstrip("/") == addressing.HEARTBEAT:
        rest = "heartbeat"
    where = addressing.anatomy_address(rest)
    if where is None:
        raise Http404("That section moved, and its old address goes nowhere.")
    return HttpResponseRedirect(where + ("?" + query if query else ""))


def rouh_land_return(request: HttpRequest):
    """rouh.land sending the person back with a code (`addressing.ROUH_LAND_RETURN`): on to Your
    Rouh with the query as it came, which `birthpage.js` reads once and shows in its rouh.land card
    (141-17). Without a code it is the old Birthday address, and that is not found."""
    if not any(request.GET.get(k) for k in addressing.ROUH_LAND_CARRIES):
        raise Http404("Birthday is Your Rouh now.")
    query = request.META.get("QUERY_STRING", "")
    return HttpResponseRedirect(genes.ANATOMY_ROOT + "/" + genes.SECTIONS["this-rouh"] + "?" + query)
