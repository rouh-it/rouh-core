"""Rouh's Telegram bot, set by its owner in Anatomy, Connections, Telegram (`rouh/telegram_bot.py`).

    GET  /api/settings/telegram-bot          whether there is a bot, from where, its @username and chat
    POST /api/settings/telegram-bot          {token, chat?}: checked with Telegram, then kept
    POST /api/settings/telegram-bot/remove   the bot set here taken away

The token arrives in one POST and goes one way: into the core's own secrets file, never into an
answer, a log line, an event or anything the conversation can read. Only the person whose phone
the bot reaches (`telegram.phone_owner`) may set it or see it.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from .common import answer, body_of, only, refuse, who
from .google import Meter

log = logging.getLogger("rouh.web.telegram_bot")

#: Each save asks Telegram twice; a few a minute is plenty for a person typing.
meter = Meter(6, 60.0)
NO_STORE = {"Cache-Control": "no-store"}


def _bot():
    from rouh import telegram
    from rouh.config import config

    return telegram.Telegram(config.telegram_file, api_base=config.telegram_api_base)


def _owner_of_phone(me) -> bool:
    from rouh import runtime, telegram

    owner = telegram.phone_owner(runtime.tenancy)
    return owner is not None and str(owner.user_id) == str(me.user_id) \
        and str(owner.org_id) == str(me.org_id)


async def _asked(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return None, refuse("sign in", 401)
    if not await sync_to_async(_owner_of_phone)(me):
        return None, refuse("Only the person whose phone Rouh's bot reaches can set it.", 403)
    return me, None


@only("GET", "POST")
async def settings_telegram_bot(request: HttpRequest):
    from rouh import telegram_bot

    me, no = await _asked(request)
    if no is not None:
        return no
    bot = _bot()
    if request.method == "GET":
        return answer({"bot": telegram_bot.state(bot)}, headers=NO_STORE)
    if meter.too_many("bot:" + str(me.user_id)):
        return refuse("That is too many attempts. Wait a minute.", 429, bot=telegram_bot.state(bot))
    body = body_of(request)
    try:
        got = await telegram_bot.save(bot, str(body.get("token") or ""), body.get("chat"))
    except telegram_bot.Refused as exc:
        return refuse(str(exc), 400, bot=telegram_bot.state(bot))
    said = (f"Rouh's bot{' @' + got['bot'] if got.get('bot') else ''} is set, and wrote to your chat to "
            "prove it. Rouh reads what you write there within half a minute, with nothing to restart.")
    return answer({"ok": True, "said": said, "bot": got}, headers=NO_STORE)


@only("POST")
async def remove(request: HttpRequest):
    from rouh import telegram_bot

    _me, no = await _asked(request)
    if no is not None:
        return no
    got = await sync_to_async(telegram_bot.remove)(_bot())
    return answer({"ok": True, "bot": got}, headers=NO_STORE)
