"""Rouh's own Telegram bot, set up by its owner on a page, never in a chat or a file by hand.

Petar, 12 November 2026: somebody setting up their new Rouh on a Mac was told by Rouh that the
bot token "has to be typed into the file by you", that its commands "can only read files", and that
they had to open ``stack.env``, add two lines and press Stop and Start. "That shouldn't be the case."

So the owner sets the bot in Anatomy, Connections, Telegram, on the card Rouh's Telegram bot:

- **The token goes one way.** It is typed into a password field on the page and posted once, over
  the page's own connection, to Rouh's core (`rouh/web/service_keys.py`). It is never in a
  conversation, a turn, a model's prompt, a tool result, an event or a log line, and no answer
  ever carries it back: the page is told the bot's @username and the chat, and nothing else.
- **Checked before it is kept.** Telegram is asked who the bot is (``getMe``), so a token copied
  wrong is refused with words, and the bot writes one short message to the chat, so a chat id
  that is wrong, or a bot nobody has pressed Start on, is refused too. A chat id left empty is
  found from the last private message the bot was sent.
- **Kept the way every other key is** (`rouh/service_keys.py`, Petar the same day: "this should be
  done for all such integrations"): sealed in the database, and taken up at once. `telegram.Telegram`
  asks Settings first on every call, so mail alerts and `send_telegram` use it on their next message,
  and the phone's chat (`telegram_chat.PhoneChat`) starts reading within `telegram_chat.IDLE_SECONDS`,
  with no restart. Nothing here gives the worker, a job or the model any way to read or write it.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
from pathlib import Path

from . import telegram

log = logging.getLogger("rouh.telegram_bot")

#: A bot token as BotFather gives it: the bot's id, a colon, and its secret.
TOKEN = re.compile(r"^\d{5,15}:[A-Za-z0-9_-]{30,64}$")
#: A chat id: the private chat's is the person's own id; a group's is negative.
CHAT = re.compile(r"^-?\d{1,20}$")
#: The message the bot writes to prove it can reach the chat.
HELLO = "Rouh is connected to this chat. Write here any time and Rouh answers."


class Refused(ValueError):
    """What was typed cannot be the bot, in words the page shows under the form."""


class _Candidate(telegram.Telegram):
    """The bot as typed, asked before anything is kept: never written anywhere, never logged."""

    def __init__(self, token: str, chat, api_base: str | None) -> None:
        super().__init__(os.devnull, api_base=api_base, timeout=10.0)
        self._pair = (token, chat)

    def _settings(self):
        return self._pair


def _clean(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


async def _find_chat(cand: _Candidate) -> str:
    """The private chat that last wrote to the bot, read without confirming anything."""
    try:
        got = await cand._call("getUpdates", {"timeout": 0, "limit": 100}, timeout=10.0)
    except telegram.Refused:
        raise Refused("Rouh could not look for your chat, because this bot is already being read. "
                      "Type the chat id instead.") from None
    for update in reversed(got if isinstance(got, list) else []):
        message = update.get("message") or update.get("edited_message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") == "private" and chat.get("id") is not None:
            return str(chat["id"])
    raise Refused("Rouh could not find your chat yet. Open your bot in Telegram, press Start or "
                  "send it any message, then press Save again. Or type the chat id.")


async def check(token: str, chat, api_base: str | None) -> tuple[str, str]:
    """Ask Telegram whether this token is a bot that can write to this chat: its @username and the chat."""
    token = _clean(token)
    chat = _clean(chat)
    if not token:
        raise Refused("Paste the bot's token, from BotFather.")
    if not TOKEN.match(token):
        raise Refused("That does not look like a bot token. BotFather gives one like "
                      "123456789:AAH... - copy all of it, the numbers, the colon and the rest.")
    if chat and not CHAT.match(chat):
        raise Refused("A chat id is only digits, with a minus in front for a group.")
    cand = _Candidate(token, chat or "0", api_base)
    try:
        me = await cand._call(telegram.ME, {}, timeout=10.0)
    except telegram.Refused:
        raise Refused("Telegram did not accept that token. Copy it again from BotFather "
                      "(/mybots, your bot, API Token).") from None
    except telegram.Unreachable:
        raise Refused("Telegram could not be reached from this Rouh. Try again in a moment.") from None
    if not chat:
        chat = await _find_chat(cand)
        cand._pair = (token, chat)
    try:
        await cand._call("sendMessage", {"chat_id": int(chat), "text": HELLO}, timeout=10.0)
    except telegram.Refused:
        raise Refused(f"The bot could not write to chat {chat}. Open your bot in Telegram and press "
                      "Start, check the chat id, then press Save again.") from None
    except telegram.Unreachable:
        raise Refused("Telegram could not be reached from this Rouh. Try again in a moment.") from None
    return str((me or {}).get("username") or ""), chat


def _bot_id(token: str) -> str:
    return token.split(":", 1)[0] if token else ""


#: The bot this process last used, so a different one is noticed (`forget_held`).
_LAST = {"bot": ""}


def forget_held() -> None:
    """After the bot is set or removed in Settings: what this process held about the old bot
    forgotten - who it is, and where its messages had got to, which mean nothing to another bot."""
    from . import telegram_chat

    now = _bot_id(_effective_token())
    for held in _running().values():
        held._me = None
    if _LAST["bot"] and now != _LAST["bot"]:
        with contextlib.suppress(Exception):
            telegram_chat._set_state(telegram_chat.OFFSET, None)
    _LAST["bot"] = now


def _effective_token() -> str:
    found = telegram.Telegram()._settings()
    return found[0] if found else ""


def _running() -> dict:
    try:
        from . import runtime
    except Exception:  # noqa: BLE001 - outside the server there is nothing running
        return {}
    got = getattr(getattr(runtime, "tools", None), "telegram", None)
    return {id(got): got} if got is not None else {}


def carry_over() -> None:
    """The bot this card wrote to the core's secrets file on 12 November 2026, before it was kept in
    Settings like every other key, carried into Settings once and the file deleted. A file written by
    hand (an old server's) is left as it is: it is beneath what Settings keeps."""
    from . import service_keys
    from .config import config
    from .encryption import box
    from .models import ServiceKey

    path = Path(config.telegram_file)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict) or "saved_at" not in data or "bot_username" not in data:
        return
    token = str(data.get("bot_token") or "").strip()
    chat = str(data.get("chat_id") or "").strip()
    if token and not ServiceKey.objects.filter(org_id=service_keys._org(), name="ROUH_TELEGRAM_BOT_TOKEN").exists():
        now = time.time()
        for name, v, last4 in (("ROUH_TELEGRAM_BOT_TOKEN", token, token[-4:]), ("ROUH_TELEGRAM_CHAT_ID", chat, "")):
            if v:
                ServiceKey.objects.update_or_create(org_id=service_keys._org(), name=name, defaults={
                    "value_sealed": box().seal(v), "last4": last4, "saved_by": "", "saved_at": now})
    with contextlib.suppress(OSError):
        os.unlink(path)
    log.info("the Telegram bot set on 12 November was carried into Settings, Keys")
