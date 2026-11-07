"""Settings, Connections, Philips Hue, at /anatomy/connections/hue (`rouh/hue.py`).

    GET  /api/settings/hue              the Hue app (its client id, the secret's last four and its
                                        app id), the callback address to register, and this
                                        person's connection: the bridge, when it was last reached,
                                        and whether the sign-in has lapsed
    POST /api/settings/hue/app          {client_id, client_secret, app_id}: an administrator keeps
                                        the organisation's Hue app; the secret is sealed, never echoed
    POST /api/settings/hue/app/remove
    GET  /auth/hue/start                off to Hue's own sign-in
    GET  /auth/hue/callback             back from it: tokens kept, the bridge linked
    POST /api/settings/hue/check        reach the bridge now
    POST /api/settings/hue/link         Try again: signed in, and the link button could not be pressed
                                        through the cloud, so ask the bridge for a key for up to 30
                                        seconds while the person presses its own button
    POST /api/settings/hue/disconnect   forget this person's tokens and the bridge's key

The state of a sign-in is kept in the browser's own session, so it can be finished only in the
browser that started it, by the person who started it, once, within `hue.STATE_LIFE`. A secret
typed here goes straight to the server and never through a chat or a model.
"""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse

from django.http import HttpRequest, HttpResponseRedirect

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, public_base, refuse
from .google import Meter

log = logging.getLogger("rouh.web.hue")
NO_STORE = {"Cache-Control": "no-store"}
SESSION_KEY = "hue_consent"
meter = Meter()
TOO_MANY = "That is too many attempts. Wait a minute."


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(request, me) -> dict:
    from rouh import hue

    return await asyncio.to_thread(hue.public, me, public_base(request))


def _back(said: str = "", *, bad: bool = False) -> HttpResponseRedirect:
    """To the Hue section of Settings, with what happened to say there once."""
    from rouh import hue

    q = urllib.parse.urlencode({"hue": "error" if bad else "said", "say": said[:400]}) if said else ""
    return HttpResponseRedirect(hue.PAGE + ("?" + q if q else ""), status=303)


async def _do(request, work):
    from rouh import hue
    from rouh.encryption import NotEncryptable

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        said = await work(me, body)
    except hue.Refused as exc:
        return refuse(str(exc), 400, **(await _page(request, me)))
    except hue.Lapsed:
        # The card says why, beside Connect again.
        return refuse("Philips Hue needs connecting again.", 409, **(await _page(request, me)))
    except (hue.NotSetUp, hue.HueError) as exc:
        return refuse(str(exc), 409, **(await _page(request, me)))
    except NotEncryptable:
        return refuse("Secrets cannot be kept safely on this machine yet, so nothing was kept.", 500,
                      **(await _page(request, me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("a Hue settings change failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(request, me)))
    finally:
        body.pop("client_secret", None)
    return answer({"ok": True, "said": said, **(await _page(request, me))}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(request, me), headers=NO_STORE)


@only("POST")
@their_clock
async def save_app(request: HttpRequest):
    from rouh import hue

    async def go(me, body):
        await asyncio.to_thread(hue.save_app, me, client_id=body.get("client_id") or "",
                                client_secret=body.pop("client_secret", "") or "",
                                app_id=body.get("app_id") or "")
        return "Saved. Now press Connect to sign in to your Hue account."
    return await _do(request, go)


@only("POST")
@their_clock
async def remove_app(request: HttpRequest):
    from rouh import hue

    async def go(me, body):
        await asyncio.to_thread(hue.remove_app, me)
        return "Rouh has forgotten the Hue app."
    return await _do(request, go)


@only("POST")
@their_clock
async def check(request: HttpRequest):
    from rouh import hue

    async def go(me, body):
        return await asyncio.to_thread(hue.check, me)
    return await _do(request, go)


@only("POST")
@their_clock
async def link(request: HttpRequest):
    from rouh import hue

    async def go(me, body):
        if meter.too_many("link:" + str(me.user_id)):
            raise hue.Refused(TOO_MANY)
        return await asyncio.to_thread(hue.link_button, me)
    return await _do(request, go)


@only("POST")
@their_clock
async def disconnect(request: HttpRequest):
    from rouh import hue

    async def go(me, body):
        if meter.too_many("disconnect:" + str(me.user_id)):
            raise hue.Refused(TOO_MANY)
        await asyncio.to_thread(hue.disconnect, me)
        return ("Rouh has forgotten your Hue sign-in and its key to the bridge. To take Rouh off your "
                "Hue account entirely, remove it from the apps your Hue account lists.")
    return await _do(request, go)


@only("GET")
async def start(request: HttpRequest):
    """Off to Hue's own sign-in page, with a state of this browser's own."""
    from rouh import hue

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if meter.too_many("start:" + str(me.user_id)):
        return _back(TOO_MANY, bad=True)
    app = await asyncio.to_thread(hue.app_of, me.org_id)
    if app is None or not (app.client_id and app.secret_sealed):
        return _back("The Hue app is not set up yet: its client id and secret come first.", bad=True)
    state = hue.new_state()
    await request.session.aset(SESSION_KEY, {"state": state, "user_id": str(me.user_id),
                                             "org_id": str(me.org_id), "at": time.time()})
    return HttpResponseRedirect(hue.consent_url(app, state, public_base(request)), status=303)


@only("GET")
async def callback(request: HttpRequest):
    """Back from Hue: the state checked and spent, the code changed for tokens, the bridge linked."""
    from rouh import hue

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if meter.too_many("callback:" + str(me.user_id)):
        return _back(TOO_MANY, bad=True)
    # Spent whatever happens, so a cancelled sign-in cannot be finished later with the same one.
    issued = await request.session.apop(SESSION_KEY, None) or {}
    state = request.GET.get("state") or ""
    if not state or state != issued.get("state") or time.time() - float(issued.get("at") or 0) > hue.STATE_LIFE:
        return _back("That Hue sign-in was not started here, or took too long, so it was not used.", bad=True)
    if issued.get("user_id") != str(me.user_id) or issued.get("org_id") != str(me.org_id):
        return _back("That Hue sign-in was started by somebody else, so it was refused.", bad=True)
    refused = request.GET.get("error") or ""
    if refused:
        said = ("You did not give Rouh permission, so nothing was connected." if refused == "access_denied"
                else "Hue refused the sign-in, so nothing was connected.")
        return _back(said, bad=True)
    code = request.GET.get("code") or ""
    if not code:
        return _back("Hue came back without a sign-in code. Press Connect again.", bad=True)
    try:
        conn = await asyncio.to_thread(hue.finish, me, code, public_base(request))
    except hue.Lapsed:
        return _back("Hue did not accept that sign-in. Check the app's client id, secret and callback "
                     "address, then press Connect again.", bad=True)
    except (hue.NotSetUp, hue.HueError) as exc:
        return _back(str(exc), bad=True)
    except Exception:  # noqa: BLE001
        log.exception("hue: finishing the sign-in failed")
        return _back("The sign-in with Hue did not finish. Press Connect again.", bad=True)
    return _back(f"Connected to {conn.bridge_name or 'your Hue Bridge'}.")
