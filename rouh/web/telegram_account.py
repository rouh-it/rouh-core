"""Settings for a Telegram account: each person's own, which opens a group for each fork.

    GET  /api/settings/telegram-account             what Settings draws
    POST /api/settings/telegram-account             the app and the phone: send a code
    POST /api/settings/telegram-account/code        the code Telegram sent
    POST /api/settings/telegram-account/password    the two-step verification password
    POST /api/settings/telegram-account/disconnect  log Rouh's session out and forget it

Like Apple Contacts, one level only: each person connects their own account,
keyed by user and organisation (`rouh/telegram_account.py`), and who is asking
is `Tenancy.current`, through `common.who`.

Everything secret goes one way. The API hash, the code and the password each
arrive in one POST; the hash and the session are sealed, the code and the
password are handed to Telegram and dropped. None of them is in any answer,
any log line or anything the page is sent afterwards.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from .common import answer, body_of, only, refuse, who
from .google import Meter

#: How often one person may try: each try is a request to Telegram, and
#: Telegram locks an account out for a while after too many wrong codes.
meter = Meter(6, 60.0)

TOO_MANY = "That is too many attempts. Wait a minute."


def _desk():
    from rouh import runtime

    return runtime.telegram_accounts


def _off():
    return refuse("A Telegram account cannot be connected on this server: its session "
                  "could not be encrypted here.", 503)


async def _state(desk, me) -> dict:
    return {"account": await sync_to_async(desk.summary)(me)}


async def _asked(request: HttpRequest, meter_key: str):
    """The desk and who is asking, or the refusal to send instead."""
    desk = _desk()
    if desk is None:
        return None, None, _off()
    me = await sync_to_async(who)(request)
    if me is None:
        return None, None, refuse("sign in", 401)
    if meter_key and meter.too_many(meter_key + ":" + me.user_id):
        return None, None, refuse(TOO_MANY, 429)
    return desk, me, None


@only("GET", "POST")
async def settings_telegram_account(request: HttpRequest):
    desk, me, no = await _asked(request, "start" if request.method == "POST" else "")
    if no is not None:
        return no
    if request.method == "GET":
        return answer(await _state(desk, me))
    body = body_of(request)
    try:
        said = await desk.start(me, body.get("api_id"), str(body.get("api_hash") or ""),
                                str(body.get("phone") or ""))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _state(desk, me)))
    return answer({"ok": True, "said": said, **(await _state(desk, me))})


@only("POST")
async def code(request: HttpRequest):
    desk, me, no = await _asked(request, "code")
    if no is not None:
        return no
    try:
        got = await desk.code(me, str(body_of(request).get("code") or ""))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _state(desk, me)))
    said = ("Your account has two-step verification: type your Telegram password."
            if got == "password" else "Your Telegram account is connected.")
    return answer({"ok": True, "said": said, **(await _state(desk, me))})


@only("POST")
async def password(request: HttpRequest):
    desk, me, no = await _asked(request, "password")
    if no is not None:
        return no
    try:
        await desk.password(me, str(body_of(request).get("password") or ""))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _state(desk, me)))
    return answer({"ok": True, "said": "Your Telegram account is connected.",
                   **(await _state(desk, me))})


@only("POST")
async def disconnect(request: HttpRequest):
    desk, me, no = await _asked(request, "")
    if no is not None:
        return no
    gone = await desk.disconnect(me)
    return answer({"ok": True, "removed": gone, **(await _state(desk, me))})
