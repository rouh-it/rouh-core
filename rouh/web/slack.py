"""Settings, Connections, Slack, at /anatomy/connections/slack (`rouh/slack.py`).

    GET  /api/settings/slack           whether Slack is connected, to which workspace and for whom,
                                       each token's last four, how listening and reading back go,
                                       and the address that creates the app in Slack
    POST /api/settings/slack/tokens    {bot, user, app}: each one given checked with Slack, then
                                       sealed; never echoed
    POST /api/settings/slack/check     every kept token asked of Slack again
    POST /api/settings/slack/remove    forget every token

Petar, 16 October 2026: Rouh's own Slack app, made from its manifest in one press. A token typed
here goes straight to the server and never through a chat or a model: it is in no answer, no log
line and no error message. Every query names the signed-in person's organisation, and only its
administrators change anything.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.slack")
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


async def _page(me) -> dict:
    from rouh import slack

    return await asyncio.to_thread(slack.public, me)


def _poke() -> None:
    """The listener looks again at once: tokens came or went."""
    from rouh import runtime

    listener = getattr(runtime, "slack_listener", None)
    if listener is not None:
        listener.poke()


async def _do(request, work):
    from rouh import slack
    from rouh.encryption import NotEncryptable

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        got, said = await work(me, body)
    except slack.Refused as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except NotEncryptable:
        return refuse("Tokens cannot be kept safely on this machine yet, so none was kept.", 500,
                      **(await _page(me)))
    except Exception:  # noqa: BLE001 - never says what was typed
        log.exception("a Slack settings change failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(me)))
    finally:
        for k in ("bot", "user", "app"):
            body.pop(k, None)
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
async def tokens(request: HttpRequest):
    from rouh import slack

    async def go(me, body):
        got = await asyncio.to_thread(slack.save, me, bot_token=body.pop("bot", ""),
                                      user_token=body.pop("user", ""), app_token=body.pop("app", ""))
        _poke()
        kept = [slack.TOKEN_WORDS[k] for k, v in got["tokens"].items() if v]
        said = "Saved. Slack accepted " + slack._and(kept) + "."
        if got["connected"]:
            said += " Rouh is connecting now."
        return got, said[0].upper() + said[1:]
    return await _do(request, go)


@only("POST")
@their_clock
async def check(request: HttpRequest):
    from rouh import slack

    async def go(me, body):
        got, wrong = await asyncio.to_thread(slack.check, me)
        if wrong:
            raise slack.Refused(wrong)
        _poke()
        return got, "Slack accepted every kept token."
    return await _do(request, go)


@only("POST")
@their_clock
async def remove(request: HttpRequest):
    from rouh import slack

    async def go(me, body):
        got = await asyncio.to_thread(slack.remove, me)
        _poke()
        return got, ("Rouh has forgotten the Slack tokens and stopped listening. The app stays in "
                     "your workspace until you remove it in Slack; what Rouh kept stays here.")
    return await _do(request, go)
