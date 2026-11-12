"""Settings, Keys, at /anatomy/connections/keys (`rouh/service_keys.py`), built the way Cloudflare's is.

    GET  /api/settings/keys           every service: whether each value is set, from where, a secret's
                                      last four, a plain value itself, and how its last check went
    POST /api/settings/keys/save      {service, values: {NAME: text}}: checked with the service, then
                                      sealed and taken up at once; a secret left empty keeps the kept one
    POST /api/settings/keys/check     {service}: ask the service again with what is used now
    POST /api/settings/keys/remove    {service}: forget what was kept here; the settings file's comes back

A value typed here goes straight to the core and never through a chat or a model. It is in no
answer, no log line and no error message, which say what is wrong and never what was typed. Only
an administrator of this Rouh's own organisation changes anything.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse
from .google import Meter

log = logging.getLogger("rouh.web.service_keys")
NO_STORE = {"Cache-Control": "no-store"}
#: Each save and check asks a service; a few a minute is plenty for a person typing.
meter = Meter(10, 60.0)


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import service_keys

    return await asyncio.to_thread(service_keys.public, me)


async def _do(request, work):
    from rouh import service_keys
    from rouh.encryption import NotEncryptable

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if meter.too_many("keys:" + str(me.user_id)):
        return refuse("That is too many tries. Wait a minute.", 429, **(await _page(me)))
    body = body_of(request)
    try:
        got = await work(me, body)
    except service_keys.Refused as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except NotEncryptable:
        return refuse("Keys cannot be kept safely on this machine yet, so none was kept.", 500, **(await _page(me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("a change to the service keys failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(me)))
    finally:
        body.pop("values", None)
    return answer({"ok": True, **got}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


@only("POST")
@their_clock
async def save(request: HttpRequest):
    from rouh import service_keys

    return await _do(request, lambda me, b: service_keys.save(me, str(b.get("service") or ""), b.get("values")))


@only("POST")
@their_clock
async def check(request: HttpRequest):
    from rouh import service_keys

    return await _do(request, lambda me, b: service_keys.check_again(me, str(b.get("service") or "")))


@only("POST")
@their_clock
async def remove(request: HttpRequest):
    from rouh import service_keys

    async def work(me, b):
        return await asyncio.to_thread(service_keys.remove, me, str(b.get("service") or ""))

    return await _do(request, work)
