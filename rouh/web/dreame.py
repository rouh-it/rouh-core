"""A Dreame robot vacuum: Settings, Connections, Dreame, and the robot for the Home page (`rouh/dreame.py`).

    GET  /api/settings/dreame             this person's connection: the app, the account, its
                                          region, the robot, when it was last reached, whether it
                                          has lapsed, the apps and regions to choose from, and a
                                          Mi Home sign-in waiting for a code or a picture's letters
    POST /api/settings/dreame/connect     {account, email, password, region}: sign in to
                                          Dreamehome ("dreamehome") or Mi Home ("mi"); the
                                          password is never echoed. A Mi Home sign-in Xiaomi stops
                                          answers 200 with what it waits for, under "waiting"
    POST /api/settings/dreame/answer      {code} or {captcha} typed by the person, or {again: true}
                                          for a new code: carries the waiting sign-in on
    POST /api/settings/dreame/cancel      forget the waiting sign-in
    POST /api/settings/dreame/check       reach the cloud and the robot now
    POST /api/settings/dreame/disconnect  forget the account, its password and its tokens
    GET  /api/home/vacuum                 the robot's state and rooms, or why there is none
    POST /api/home/vacuum                 {action, rooms?, level?}: start (rooms are ids), pause,
                                          dock, locate, suction, mode, wetness, wash, dry, empty;
                                          what changed, and the state after it

The password is typed into the page by the person and goes straight to the server, never through
a chat or a model.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse
from .google import Meter

log = logging.getLogger("rouh.web.dreame")
NO_STORE = {"Cache-Control": "no-store"}
meter = Meter()
TOO_MANY = "That is too many attempts. Wait a minute."


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import dreame

    return await asyncio.to_thread(dreame.public, me)


async def _do(request, work):
    from rouh import dreame, dreame_mi
    from rouh.encryption import NotEncryptable

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        said = await work(me, body)
    except (dreame_mi.NeedsCode, dreame_mi.NeedsCaptcha):
        # Not a failure: the card shows what Xiaomi asked for, and its field, from "waiting".
        return answer({"ok": True, **(await _page(me))}, headers=NO_STORE)
    except (dreame.Refused, dreame.NeedsCheck) as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except dreame.Lapsed:
        # The card says why, beside Connect.
        return refuse("The Dreame robot needs connecting again.", 409, **(await _page(me)))
    except (dreame.NotSetUp, dreame.DreameError) as exc:
        return refuse(str(exc), 409, **(await _page(me)))
    except NotEncryptable:
        return refuse("Secrets cannot be kept safely on this machine yet, so nothing was kept.", 500,
                      **(await _page(me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("a Dreame settings change failed")
        return refuse("That did not work. Try again.", 500, **(await _page(me)))
    finally:
        body.pop("password", None)
        body.pop("code", None)
        body.pop("captcha", None)
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
async def connect(request: HttpRequest):
    from rouh import dreame

    async def go(me, body):
        if meter.too_many("connect:" + str(me.user_id)):
            raise dreame.Refused(TOO_MANY)
        conn = await asyncio.to_thread(dreame.connect, me, email=body.get("email") or "",
                                       password=body.pop("password", "") or "",
                                       region=body.get("region") or "auto",
                                       account=str(body.get("account") or "dreamehome"))
        return _connected(conn)
    return await _do(request, go)


def _connected(conn) -> str:
    from rouh import dreame

    if not conn.did:
        return ("Signed in, but there is no robot vacuum on this "
                f"{dreame.ACCOUNT_NAMES.get(conn.account, 'Dreamehome')} account.")
    return f"Connected to {conn.robot_name or 'your robot'}."


@only("POST")
@their_clock
async def answer_check(request: HttpRequest):
    """The code or the picture's letters the person typed, for a Mi Home sign-in that waits."""
    from rouh import dreame, dreame_mi

    async def go(me, body):
        if meter.too_many("answer:" + str(me.user_id)):
            raise dreame.Refused(TOO_MANY)
        conn = await asyncio.to_thread(dreame_mi.answer, me, code=str(body.pop("code", "") or ""),
                                       captcha=str(body.pop("captcha", "") or ""), again=bool(body.get("again")))
        return _connected(conn)
    return await _do(request, go)


@only("POST")
@their_clock
async def cancel(request: HttpRequest):
    from rouh import dreame_mi

    async def go(me, body):
        await asyncio.to_thread(dreame_mi.forget_waiting, me)
        return ""
    return await _do(request, go)


@only("POST")
@their_clock
async def check(request: HttpRequest):
    from rouh import dreame

    async def go(me, body):
        return await asyncio.to_thread(dreame.check, me)
    return await _do(request, go)


@only("POST")
@their_clock
async def disconnect(request: HttpRequest):
    from rouh import dreame

    async def go(me, body):
        if meter.too_many("disconnect:" + str(me.user_id)):
            raise dreame.Refused(TOO_MANY)
        await asyncio.to_thread(dreame.disconnect, me)
        return "Rouh has forgotten the account, its password and its sign-in."
    return await _do(request, go)


@only("GET", "POST")
@their_clock
async def vacuum(request: HttpRequest):
    """The robot for the Home page: read it, or ask it to do one thing and read it again."""
    from rouh import dreame

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    said = ""
    if request.method == "POST":
        body = body_of(request)
        conn = await asyncio.to_thread(dreame.connection, me.user_id, me.org_id)
        if conn is None or not conn.did or conn.lapsed_at:
            return refuse("The Dreame robot is not connected.", 409,
                          **(await asyncio.to_thread(dreame.view, me)))
        rooms = body.get("rooms")
        if rooms is not None and not (isinstance(rooms, list) and all(isinstance(x, int) for x in rooms)):
            return refuse("Rooms are the ids the page was given.", 400)
        try:
            said = await asyncio.to_thread(dreame.do, dreame.cloud_for(conn), str(body.get("action") or ""),
                                           rooms_said=rooms or None, level=body.get("level"))
        except dreame.Lapsed:
            return refuse("The Dreame robot needs connecting again.", 409,
                          **(await asyncio.to_thread(dreame.view, me)))
        except (dreame.DreameError, dreame.NotSetUp) as exc:
            return refuse(str(exc), 409, **(await asyncio.to_thread(dreame.view, me)))
    got = await asyncio.to_thread(dreame.view, me)
    return answer({**got, **({"said": said} if said else {})}, headers=NO_STORE)
