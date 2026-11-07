"""Anatomy, Money, Services, at /anatomy/money/services (`rouh/services.py`).

    GET  /api/settings/services          every service paid for again and again, what the
                                         active ones cost a month, and the vault's cards to
                                         pick what pays for one
    POST /api/settings/services          {id?, name, what_for?, amount?, currency?, period?,
                                         renews_on?, trial_ends?, paid_with?, account?,
                                         cancel_how?, state?}: a service added, or changed
    POST /api/settings/services/state    {id, state}: marked cancelled, or active again
    POST /api/settings/services/delete   {id}: taken out of the list

Petar, 15 October 2026: "Services are things we purchase and we need to track and maybe
unsubscribe", beside Payments in Anatomy's Money, and nothing to do with the nightly feature
run. A refusal is ``{"error": ...}``, with ``"fields": {name: what is wrong}`` when it is in
fields of the form sent. Every query names the signed-in person's user and organisation.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.services")
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _do(request, work):
    from rouh import services

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    try:
        said = await asyncio.to_thread(work, me, body_of(request))
    except services.Refused as exc:
        more = {"fields": exc.fields} if exc.fields else {}
        return refuse(str(exc), 400, **more, **(await asyncio.to_thread(services.listing, me)))
    except Exception:  # noqa: BLE001 - said plainly, and the log has why
        log.exception("a services change failed")
        return refuse("That could not be saved. Try again.", 500,
                      **(await asyncio.to_thread(services.listing, me)))
    return answer({"ok": True, "said": said, **(await asyncio.to_thread(services.listing, me))},
                  headers=NO_STORE)


@only("GET", "POST")
@their_clock
async def page(request: HttpRequest):
    from rouh import services

    if request.method == "POST":
        def go(me, body):
            row = services.save(me, body)
            return f"Saved {row.name}." if body.get("id") else f"Added {row.name}."
        return await _do(request, go)
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(services.listing, me), headers=NO_STORE)


@only("POST")
@their_clock
async def state(request: HttpRequest):
    from rouh import services

    def go(me, body):
        row = services.set_state(me, body.get("id"), str(body.get("state") or ""))
        return (f"{row.name} is marked cancelled." if row.state == "cancelled"
                else f"{row.name} is {services.STATES[row.state].lower()} again.")
    return await _do(request, go)


@only("POST")
@their_clock
async def delete(request: HttpRequest):
    from rouh import services

    def go(me, body):
        return f"Took {services.delete(me, body.get('id')).name} out of the list."
    return await _do(request, go)
