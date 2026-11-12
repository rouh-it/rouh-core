"""Rouh's own Telegram bot, set up by its owner on a page, never in a chat or a file by hand.

Petar, 12 November 2026: somebody setting up their new Rouh on a Mac was told by Rouh that the
bot token "has to be typed into the file by you", that its commands "can only read files", and that
they had to open ``stack.env``, add two lines and press Stop and Start. "That shouldn't be the case."

So the owner sets the bot in Anatomy, Connections, Telegram, on the card Rouh's Telegram bot:

- **The token goes one way.** It is typed into a password field on the page and posted once, over
  the page's own connection, to Rouh's core (`rouh/web/telegram_bot.py`). It is never in a
  conversation, a turn, a model's prompt, a tool result, an event or a log line, and no answer
  ever carries it back: the page is told the bot's @username and the chat, and nothing else.
- **Checked before it is kept.** Telegram is asked who the bot is (``getMe``), so a token copied
  wrong is refused with words, and the bot writes one short message to the chat, so a chat id
  that is wrong, or a bot nobody has pressed Start on, is refused too. A chat id left empty is
  found from the last private message the bot was sent.
- **Written by the core alone, to the one file the bot is read from.** `telegram.Telegram` reads
  ``ROUH_TELEGRAM_FILE`` on every call and a file there wins over the settings file
  (``stack.env``), so writing it is the whole of applying it: mail alerts and `send_telegram`
  use it on their next message, and the phone's chat (`telegram_chat.PhoneChat`) starts reading
  within `telegram_chat.IDLE_SECONDS`, with no restart. In the containers that file is in the
  core's own volume (``/data/secrets/rouh_telegram.json``), which the worker - where the model's
  commands and every job run - cannot reach at all. Nothing here gives the worker, a job or the
  model any way to write anything: this is one form, for one setting, for the owner only.
- **The owner only.** The bot reaches one person's phone (`telegram.phone_owner`), so only that
  person may set or remove it.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import secrets
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


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def state(bot: telegram.Telegram) -> dict:
    """What the card draws: whether there is a bot, from where, its @username and chat. Never the token."""
    found = bot._settings()
    data = _read(bot.path)
    if found is None:
        return {"configured": False, "source": "", "writable": _writable(bot.path)}
    from_file = bool(data and str(data.get("bot_token") or "").strip())
    return {
        "configured": True,
        "source": "page" if from_file else "settings_file",
        "bot": str((data or {}).get("bot_username") or "") if from_file else "",
        "bot_id": found[0].split(":", 1)[0],
        "chat": str(found[1]),
        "saved_at": (data or {}).get("saved_at") if from_file else None,
        "writable": _writable(bot.path),
    }


def _writable(path: Path) -> bool:
    folder = path.parent
    while not folder.exists() and folder != folder.parent:
        folder = folder.parent
    return os.access(folder, os.W_OK)


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


def write(path: Path, doc: dict) -> None:
    """The file, whole or not at all, readable by the core's own user and nobody else."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{secrets.token_hex(6)}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(doc, out)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    os.chmod(path, 0o600)


def _applied(bot: telegram.Telegram, old_bot_id: str, new_bot_id: str) -> None:
    """What this process held about the bot before, forgotten, so the new one is used at once."""
    from . import telegram_chat

    for held in {id(bot): bot, **_running()}.values():
        held._me = None
    if old_bot_id and old_bot_id != new_bot_id:
        # Where the old bot's messages had got to means nothing to another bot's.
        with contextlib.suppress(Exception):
            telegram_chat._set_state(telegram_chat.OFFSET, None)


def _running() -> dict:
    try:
        from . import runtime
    except Exception:  # noqa: BLE001 - outside the server there is nothing running
        return {}
    got = getattr(getattr(runtime, "tools", None), "telegram", None)
    return {id(got): got} if got is not None else {}


async def save(bot: telegram.Telegram, token: str, chat) -> dict:
    """Check the bot with Telegram and keep it, in the one file it is read from. What the card draws."""
    username, chat = await check(token, chat, bot.api_base)
    before = bot._settings()
    old_id = before[0].split(":", 1)[0] if before else ""
    token = _clean(token)
    try:
        write(bot.path, {"bot_token": token, "chat_id": int(chat), "bot_username": username,
                         "saved_at": int(time.time())})
    except OSError as exc:
        log.warning("Rouh's Telegram bot could not be saved: %s", type(exc).__name__)
        raise Refused("Rouh could not save the bot on this computer. Nothing was changed.") from None
    await asyncio.to_thread(_applied, bot, old_id, token.split(":", 1)[0])
    log.info("Rouh's Telegram bot was set from Anatomy (bot %s)", token.split(":", 1)[0])
    return state(bot)


def remove(bot: telegram.Telegram) -> dict:
    """The bot set on this page taken away. One from the settings file stays: it is the installer's.
    Synchronous: it touches the database, so an async caller runs it in a thread."""
    before = bot._settings()
    try:
        os.unlink(bot.path)
    except FileNotFoundError:
        pass
    after = bot._settings()
    _applied(bot, before[0].split(":", 1)[0] if before else "", after[0].split(":", 1)[0] if after else "")
    log.info("Rouh's Telegram bot set from Anatomy was removed")
    return state(bot)
