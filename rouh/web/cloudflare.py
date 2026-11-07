"""Settings, Cloudflare, at /settings/cloudflare (`rouh/cloudflare.py`).

    GET  /api/settings/cloudflare               each zone: whether a token is set, its last
                                                four, when it was saved and last checked
    POST /api/settings/cloudflare/token         {zone, token, account_id?}: checked with
                                                Cloudflare, then sealed; never echoed. The zone's
                                                id and account are found with the token. One that
                                                lacks only a permission is kept, marked failing
                                                (`kept_failing`), to be checked again once fixed
    POST /api/settings/cloudflare/check         {zone}: check the kept token again
    POST /api/settings/cloudflare/remove        {zone}: forget the zone's token
    POST /api/settings/cloudflare/zone          {zone, account_id?}: add a zone, by its domain
                                                name, and the account it is in if given
    POST /api/settings/cloudflare/zone/forget   {zone}: take an added zone off the list

Petar, 12 October 2026: a token typed here goes straight to the server and never through a
chat or a model. It is in no answer, no log line and no error message, which say what is
wrong with it and never what was typed. Every query names the signed-in person's
organisation, and only its administrators change anything.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.cloudflare")
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import cloudflare

    return await asyncio.to_thread(cloudflare.public, me)


async def _do(request, work):
    from rouh import cloudflare
    from rouh.encryption import NotEncryptable

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        got, said = await work(me, body)
    except cloudflare.Refused as exc:
        more = {"tried": exc.tried} if exc.tried else {}
        return refuse(str(exc), 400, **(await _page(me)), **more)
    except cloudflare.CFError as exc:
        return refuse(f"Cloudflare could not be asked: {exc}. Nothing was changed.", 502, **(await _page(me)))
    except NotEncryptable:
        return refuse("Tokens cannot be kept safely on this machine yet, so none was kept.", 500,
                      **(await _page(me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("a Cloudflare settings change failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(me)))
    finally:
        body.pop("token", None)
    return answer({"ok": True, "said": said, **got}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


@only("POST")
@their_clock
async def token(request: HttpRequest):
    from rouh import cloudflare

    async def go(me, body):
        zone = cloudflare.domain_of(body.get("zone"))
        got = await asyncio.to_thread(cloudflare.save, me, zone, body.pop("token", ""),
                                      body.get("account_id") or "")
        last4 = next((z["token"]["last4"] for z in got["zones"] if z["zone"] == zone and z["token"]), "")
        why = got.pop("why", "")
        if got.get("kept_failing"):
            return got, f"Kept the {zone} token ending {last4}, sealed, but {why}"
        return got, f"Saved the {zone} token ending {last4}: it passed every check."
    return await _do(request, go)


@only("POST")
@their_clock
async def check(request: HttpRequest):
    from rouh import cloudflare

    async def go(me, body):
        zone = cloudflare.domain_of(body.get("zone"))
        got = await asyncio.to_thread(cloudflare.check, me, zone)
        if got.pop("passed"):
            got.pop("why", None)
            return got, f"The {zone} token passed every check."
        raise cloudflare.Refused(got.pop("why").replace("Not saved: ", f"The {zone} token is kept, but "),
                                 got.get("tried"))
    return await _do(request, go)


@only("POST")
@their_clock
async def remove(request: HttpRequest):
    from rouh import cloudflare

    async def go(me, body):
        zone = cloudflare.domain_of(body.get("zone"))
        got = await asyncio.to_thread(cloudflare.remove, me, zone)
        return got, (f"Rouh has forgotten the {zone} token. It still works at Cloudflare until "
                     f"you delete it there.")
    return await _do(request, go)


@only("POST")
@their_clock
async def zone(request: HttpRequest):
    from rouh import cloudflare

    async def go(me, body):
        got = await asyncio.to_thread(cloudflare.add_zone, me, body.get("zone"), body.get("account_id") or "")
        return got, f"Added {cloudflare.domain_of(body.get('zone'))}. Save its token below."
    return await _do(request, go)


@only("POST")
@their_clock
async def zone_forget(request: HttpRequest):
    from rouh import cloudflare

    async def go(me, body):
        got = await asyncio.to_thread(cloudflare.forget_zone, me, body.get("zone"))
        return got, f"{cloudflare.domain_of(body.get('zone'))} is off the list."
    return await _do(request, go)
