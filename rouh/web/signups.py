"""Settings, Sign-ups, at /settings/signups (`rouh/signups.py`).

    GET  /api/settings/signups            every sign-up the person authorized, its words and
                                          its state, and whether a password is set; never
                                          the password
    POST /api/settings/signups/allow      {service, site, email, password?}: allow one
    POST /api/settings/signups/password   {id, password}: the new account's password, sealed
                                          at once; never echoed
    POST /api/settings/signups/withdraw   {id}: take it back, and forget its password

Petar, 6 October 2026: a sign-up he had asked for stopped at its password and its Sign up
button. This is where he allows one himself, sets the password Rouh fills in for it, and
sees and withdraws every one. A password is in no answer, no log line and no error
message. Every query names the signed-in person's user and organisation.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.signups")
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import signups

    return await asyncio.to_thread(signups.public, me)


async def _do(request, work):
    from rouh import signups
    from rouh.encryption import NotEncryptable

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        said = await work(me, body)
    except signups.Refused as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except NotEncryptable:
        return refuse("Passwords cannot be kept safely on this machine yet, so none was "
                      "kept.", 500, **(await _page(me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("a sign-ups change failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(me)))
    finally:
        body.pop("password", None)
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


@only("POST")
@their_clock
async def allow(request: HttpRequest):
    from rouh import signups

    async def go(me, body):
        got = await asyncio.to_thread(signups.allow, me, body)
        return (f"Allowed: one new {got.service} account on {got.site}"
                + (f" with {got.email}" if got.email else "")
                + (", with its password." if got.has_password else
                   ". Set its password below, or Rouh hands you that one field."))
    return await _do(request, go)


@only("POST")
@their_clock
async def password(request: HttpRequest):
    from rouh import signups

    async def go(me, body):
        await asyncio.to_thread(signups.set_password, me, body.get("id"), body.get("password"))
        return "The password is kept, sealed. Rouh fills it in without seeing it."
    return await _do(request, go)


@only("POST")
@their_clock
async def withdraw(request: HttpRequest):
    from rouh import signups

    async def go(me, body):
        if not await asyncio.to_thread(signups.withdraw, me, body.get("id")):
            raise signups.Refused("That sign-up is not one that can be withdrawn.")
        return "Withdrawn, and its password forgotten."
    return await _do(request, go)
