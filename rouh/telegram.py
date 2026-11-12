"""Rouh's own Telegram bot: messages to the owner's phone, and their messages back.

This is the one way Rouh can reach the person when he is not at the screen, and
since 26 September 2026 it is also a way for him to reach Rouh: he writes to
the same bot from his phone, the message is a turn in General - or in a fork
he made there with /fork, which has a topic of its own in his forks group
(`rouh/telegram_forks.py`) - as if he had typed it into the box, and the
answer goes back to where he wrote it (`rouh/telegram_chat.py`, which is the
conversation; this file is only the bot). Petar asked for it in those words:
"two-way Telegram communication".

Until that day this file sent and never read, and said so as a rule: there was
no reading endpoint, no webhook and no polling loop, so nothing anybody typed
at the bot could reach the model. The rule is replaced rather than dropped, and
what replaces it is as strict:

* **Only the owner is read.** A message counts only when it comes from the person
  whose id is the chat id in :data:`SECRETS_FILE`: in his private chat with the
  bot, or in a group made as him for one of his forks (below). Anything else - another person who found the bot, anybody else in
  one of his forks' groups, a group somebody else added it to, a channel,
  another bot - is
  written in the log and dropped: never answered, never stored and never put
  in front of the model (`telegram_chat.PhoneChat.mine`). A press on a button under one of the bot's
  messages is held to the same rule (`PhoneChat._press`).
* **One reader.** Telegram hands each update to whoever asks for it first and
  then forgets it, so exactly one process may read this bot: the Rouh service
  on the server. A test world is pointed at a file that is not there and an
  address that answers nothing (`tests/e2e/conftest.py`,
  `rouh/testing/browser.py`), and reads nothing. Long polling, not a webhook:
  nothing on this machine has to be reachable from Telegram.
* **It is a different bot from the one on the laptop.** ``tg-ask`` and the one
  program's phone share the "Clauder" bot, and its own file under ``/etc/one``
  is named by ``ONE_TELEGRAM`` and read by ``one/phone.py``, which still only
  sends. This one is @rouh_telegram_bot and its file is :data:`SECRETS_FILE`.
  Nothing here opens the other bot's file, and reading this bot's updates
  cannot take any of the other bot's.
* **Where it may speak.** His private chat with the bot, and the group of each
  fork made on Telegram, which is made as him, with his own account, because a
  bot cannot make a group (`rouh/telegram_account.py`). In those groups too,
  only his own messages are read.
* **The token never leaves this process.** Telegram puts the bot's key in the
  address rather than in a header, so every URL built below is itself a
  secret: it is never logged, never put in an exception and never handed to the
  model. ``rouh/redaction.py`` knows the shape of one as the net under that.

The file it reads is JSON, with the same two fields the one program uses, so
anybody who has seen one has seen both::

    {"bot_token": "123456789:AA...", "chat_id": 987654321}

Written by hand on the server, owned by the user Rouh runs as, mode 0600, and
outside the repository. If it is not there the tool says so in a sentence,
nothing pretends to have sent anything, and nothing is read.

Recovering the chat id, if this ever has to be set up again: stop Rouh, send
the bot a message from the phone it should reach, ask the Bot API once by hand
with curl for the updates it is holding, copy the ``message.chat.id`` out of
what comes back into the file, and start Rouh again. Or, with Rouh running and
a chat id of any kind in the file, send the message anyway: Rouh takes it, and
since it is not from the chat in the file, drops it and writes in its log the
chat id it came from (`telegram_chat`).
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from . import owner

log = logging.getLogger("rouh.telegram")


class _NotTheBot(logging.Filter):
    """Leave httpx's line about each request out when the request was the bot's.

    httpx writes every address it calls into the log at INFO, and a Telegram
    address holds the bot's key. `rouh/redaction.py` masks a key of the real
    shape, and this is the rule over that net rather than a second net: the
    line is not written at all. It would otherwise be written once a long
    poll, every fifty seconds for as long as Rouh runs, and every four while
    "typing..." is shown.
    """

    BOT = re.compile(r"/(?:file/)?bot\d+:[^/\s]+/")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return not self.BOT.search(record.getMessage())
        except Exception:      # a record that cannot be formatted is not ours to judge
            return True


if not any(isinstance(f, _NotTheBot) for f in logging.getLogger("httpx").filters):
    logging.getLogger("httpx").addFilter(_NotTheBot())

#: Where the bot's token and the chat to send to live on the server. Outside
#: the repository, outside the workspace, and readable only by the user the
#: service runs as, which is what `/var/www/rouh/one-voice.json` already does
#: for the one program's device token.
SECRETS_FILE = "/var/www/rouh/.secrets/rouh_telegram.json"

#: Telegram's own address. A setting only so a test can stand in for it, the
#: way `ANTHROPIC_BASE_URL` and `ELEVENLABS_BASE_URL` already do for the model
#: and the voice. Nothing on the server ever sets it.
API_BASE = "https://api.telegram.org"

#: The whole of the Bot API this module uses. Sending a message, saying Rouh
#: is typing, reading the updates, finding the file a photo, a document or a
#: voice note is kept in, and - since 27 September 2026, for /fork
#: (`rouh/telegram_forks.py`) - answering a press on a button under a message,
#: changing the buttons under one, the bot's own name, a link into a fork's
#: group, and putting the commands in the menu of the chat. The menu is the one
#: thing here that changes the bot itself, and only for Petar: Petar, 27
#: September 2026, "fork is not appearing as a command in the menu of the chat
#: and it should" (`set_commands`). Its webhook and its name are never
#: touched. The groups themselves are made as him, not by the bot, which
#: cannot (`rouh/telegram_account.py`).
SEND = "sendMessage"
TYPING = "sendChatAction"
UPDATES = "getUpdates"
FILE = "getFile"
PRESSED = "answerCallbackQuery"
REBUTTON = "editMessageReplyMarkup"
ME = "getMe"
LINK = "createChatInviteLink"
COMMANDS = "setMyCommands"
#: A reaction on one of his messages: Got it (`rouh/got_it.py`, night 36 of the nightly run).
REACT = "setMessageReaction"

#: What is read off the bot: a message written to it, a press on one of the
#: buttons under a message it sent, and the bot being added to a group, made
#: an admin there or taken out of it. An edited message, a reaction and the
#: rest never arrive.
READ = ["message", "callback_query", "my_chat_member"]

#: The most a button may carry back when it is pressed, in bytes: Telegram's
#: own limit on `callback_data`.
BUTTON_DATA = 64

#: Telegram refuses a message longer than this, counted in UTF-16 code units
#: the way Telegram counts it, so an emoji is two. A longer message goes in
#: parts rather than being cut (`split`).
LIMIT = 4096

#: The most parts one message is sent in. Forty thousand characters is far
#: more than anything worth reading on a phone; past that the rest is left out
#: with a line saying so, rather than twenty messages arriving at once.
MOST_PARTS = 10

#: The biggest file the Bot API hands over. Anything bigger is refused by
#: Telegram itself ("file is too big"), so it is said before it is asked for.
MOST_FILE_BYTES = 20 * 1024 * 1024

#: How long one long poll waits for a message before asking again. Telegram
#: holds the request open that long and answers the moment one arrives.
POLL_SECONDS = 50

#: How many messages sent to the phone are remembered, for the turn that
#: reads the owner's answer to one of them (`recent`).
REMEMBERED = 8


class NotSetUp(RuntimeError):
    """No bot token or no chat id on this machine, so there is nowhere to send."""


class NotSent(RuntimeError):
    """Telegram was asked and the message did not go."""


class Unreachable(NotSent):
    """Telegram could not be reached at all: the network, a timeout, DNS."""


class Refused(NotSent):
    """Telegram answered, and said no. `status` and `retry_after` say how."""

    def __init__(self, words: str, status: int = 0, retry_after: float = 0.0):
        super().__init__(words)
        self.status = status
        self.retry_after = retry_after


def units(text: str) -> int:
    """How long Telegram thinks this text is: UTF-16 code units, not characters."""
    return len(text.encode("utf-16-le")) // 2


def _cut_at(text: str, limit: int) -> int:
    """The number of characters of `text` that fit in `limit` units."""
    used = 0
    for i, ch in enumerate(text):
        used += 2 if ord(ch) > 0xFFFF else 1
        if used > limit:
            return i
    return len(text)


def split(text: str, limit: int = LIMIT) -> list[str]:
    """A message in parts Telegram will take, each at most `limit` long.

    Cut where a reader would expect a break: at a blank line when there is one
    in the second half of the part, else at the end of a line, else after a
    sentence, else at a space, and only as a last resort in the middle of a
    word. Nothing is lost between two parts and nothing is repeated.
    """
    text = (text or "").strip()
    parts: list[str] = []
    while text:
        if units(text) <= limit:
            parts.append(text)
            break
        fits = _cut_at(text, limit)
        window = text[:fits]
        cut = 0
        for sep in ("\n\n", "\n", ". ", " "):
            at = window.rfind(sep, fits // 2)
            if at > 0:
                if sep == "\n\n":
                    # A short last paragraph with no full stop is a heading
                    # ("Part 11"), and goes with what it heads.
                    before = window.rfind("\n\n", fits // 2, at)
                    last = window[before + 2:at].strip() if before > 0 else ""
                    if last and "\n" not in last and len(last) < 60 and last[-1] not in ".!?:;,)":
                        at = before
                cut = at + len(sep)
                break
        if cut <= 0:
            cut = fits
        parts.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return [p for p in parts if p]


class Telegram:
    """The bot, as far as Rouh is concerned: one address and one chat."""

    def __init__(self, path: str | Path | None = None, *, api_base: str | None = None,
                 timeout: float = 15.0) -> None:
        self.path = Path(path or os.environ.get("ROUH_TELEGRAM_FILE") or SECRETS_FILE)
        base = api_base or os.environ.get("ROUH_TELEGRAM_API_BASE") or API_BASE
        self.api_base = base.rstrip("/")
        self.timeout = timeout
        #: What was sent to the phone lately, newest last, as (when, words):
        #: the notes Rouh wrote there, never its answers to what the owner wrote,
        #: which are in General already. Kept for the turn that answers what
        #: he writes back, which is otherwise a "yes" with nothing in front of
        #: it (`telegram_chat.PhoneChat`). Written through to `app_state`
        #: (`SENT_STATE`) as well: Rouh is deployed many times a day, and a
        #: note sent before a deploy is still on his phone after it, waiting
        #: for the answer he writes to it.
        self.sent: collections.deque[tuple[float, str]] = collections.deque(maxlen=REMEMBERED)

    # --- what is configured -------------------------------------------------

    def _settings(self) -> tuple[str, Any] | None:
        """The token and the chat, or None when either is missing.

        Read on every call rather than held in memory. It is one small file,
        and reading it each time is what lets the file be written on a running
        server without a restart.
        """
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if not isinstance(data, dict):
            # An installation that sets its bot in its settings file instead (the containers'
            # stack.env or .env, deploy/stack/settings.env.example): a file written there wins.
            data = {"bot_token": os.environ.get("ROUH_TELEGRAM_BOT_TOKEN", ""),
                    "chat_id": os.environ.get("ROUH_TELEGRAM_CHAT_ID", "")}
        token = str(data.get("bot_token") or "").strip()
        chat = data.get("chat_id")
        if isinstance(chat, str):
            chat = chat.strip()
        if not token or chat in (None, "", 0):
            return None
        return token, chat

    def configured(self) -> bool:
        """There is a bot and a chat to send to on this machine."""
        return self._settings() is not None

    def chat(self) -> str:
        """The one chat this bot talks to, as text, or "" when there is none."""
        found = self._settings()
        return str(found[1]).strip() if found is not None else ""

    def bot_id(self) -> str:
        """The bot's own user id, which is the part of its token before the colon."""
        found = self._settings()
        return found[0].split(":", 1)[0] if found is not None else ""

    def _needed(self) -> tuple[str, Any]:
        found = self._settings()
        if found is None:
            raise NotSetUp(
                "Telegram is not set up on this machine: there is no bot yet. The owner sets "
                "it in Anatomy, Connections, Telegram.")
        return found

    # --- the one way anything reaches Telegram -------------------------------

    async def _call(self, method: str, payload: dict, *, timeout: float | None = None) -> Any:
        """Ask the Bot API once and give back its `result`.

        Raises :class:`Unreachable` when Telegram could not be reached and
        :class:`Refused` when it answered no. Neither carries the address,
        because the address holds the key.
        """
        token, _ = self._needed()
        url = f"{self.api_base}/bot{token}/{method}"
        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            # Only the kind of failure, never the exception itself: httpx puts
            # the address it was calling into the text of most of them.
            raise Unreachable(f"Telegram could not be reached ({type(exc).__name__}).") from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200 or not (isinstance(body, dict) and body.get("ok")):
            # Telegram's own words, capped: they are useful in the sentence the
            # person hears, and they are not this conversation's to be long.
            because = str((body or {}).get("description") or "").strip()[:200]
            wait = ((body or {}).get("parameters") or {}).get("retry_after") or 0
            try:
                wait = float(wait)
            except (TypeError, ValueError):
                wait = 0.0
            raise Refused("Telegram refused it" + (f": {because}." if because
                                                   else f" ({response.status_code})."),
                          status=response.status_code, retry_after=wait)
        return body.get("result")

    # --- sending ------------------------------------------------------------

    async def send(self, text: str, *, remember: bool = True, who=None) -> int:
        """Send one plain message, in as many parts as it takes. Returns
        Telegram's id for the first part.

        Plain on purpose: no `parse_mode`, so nothing in it is ever read as
        markup and a stray star or underscore cannot make Telegram refuse the
        whole message. `remember` is False for Rouh's answer to something
        the owner wrote, which the chat it was asked in already holds (`sent`).

        Raises :class:`NotSetUp` when there is nothing configured and
        :class:`NotSent` when Telegram was asked and said no or could not be
        reached. A message cut off part way says so in the log.
        """
        return (await self.send_parts(text, remember=remember, who=who))[0]

    async def send_parts(self, text: str, *, remember: bool = True,
                         buttons: list[list[dict]] | None = None,
                         reply_to: int | None = None, chat=None,
                         thread: int | None = None, who=None) -> list[int]:
        """`send`, with buttons under the message, and Telegram's id for every part.

        `buttons` are rows of inline buttons, each ``{"text", "callback_data"}``,
        and go under the last part, which is where the message ends on the
        phone. `reply_to` is a message in the chat this one answers, which the
        phone draws quoted above it; one that has gone is not a reason to
        refuse the message. `chat` and `thread` send it somewhere other than
        the private chat: the forks group, and a fork's topic in it. `who` is
        the person it is for, whose name fills in its marks; by default the
        owner of the phone this bot reaches (`phone_owner`). Every
        part's id comes back, first to last, so what a message answered can be
        written down against each of them (`telegram_forks`). A part Telegram
        gave no id for is a 0.
        """
        said = (text or "").strip()
        if not said:
            raise NotSent("There was nothing to send.")
        _, own = self._needed()
        chat = own if chat in (None, "") else chat
        # The boundary: every mark for the owner (`rouh/owner.py`) is filled in
        # here, for the person whose phone this bot reaches, right before it goes.
        if owner.has_marks(said) or (buttons and owner.OPEN in json.dumps(buttons,
                                                                          ensure_ascii=False)):
            whose = who if who is not None else await asyncio.to_thread(_phone_owner_id)
            said = owner.say(said, whose)
            if buttons:
                buttons = owner.say_all(buttons, whose)
        parts = split(said)
        if len(parts) > MOST_PARTS:
            parts = parts[:MOST_PARTS]
            parts[-1] = parts[-1][:_cut_at(parts[-1], LIMIT - 80)].rstrip() + (
                "\n\n(Cut short here: the rest is in Rouh.)")
        ids: list[int] = []
        for n, part in enumerate(parts):
            payload = {
                "chat_id": chat,
                "text": part,
                # A link in a message would otherwise drag a preview card of
                # somebody else's page in under it.
                "link_preview_options": {"is_disabled": True},
                "disable_web_page_preview": True,
            }
            if thread:
                payload["message_thread_id"] = int(thread)
            if buttons and n == len(parts) - 1:
                payload["reply_markup"] = {"inline_keyboard": buttons}
            if reply_to and n == 0:
                payload["reply_parameters"] = {"message_id": int(reply_to),
                                               "allow_sending_without_reply": True}
            try:
                result = await self._one(payload)
            except NotSent as exc:
                log.warning("a Telegram message was not sent (part %d of %d): %s",
                            n + 1, len(parts), exc)
                if n == 0:
                    raise
                raise NotSent(f"Only {n} of its {len(parts)} parts went: {exc}") from None
            message_id = (result or {}).get("message_id") if isinstance(result, dict) else None
            try:
                ids.append(int(message_id))
            except (TypeError, ValueError):
                ids.append(0)
        if remember:
            await asyncio.to_thread(self._remember, said)
        return ids

    def _remember(self, said: str) -> None:
        """Written down beside every other note, whichever part of Rouh sent
        it: the mail alerts, the tools and the phone chat each hold a client of
        their own, and the answer to any of them is read from one list."""
        self.sent.append((time.time(), said))
        try:
            _set_sent(sorted(set(_get_sent()) | {self.sent[-1]})[-REMEMBERED:])
        except Exception:
            log.exception("what was sent to the phone could not be written down")

    async def _one(self, payload: dict) -> Any:
        """One part, and one more try when Telegram says to slow down."""
        try:
            return await self._call(SEND, payload)
        except Refused as exc:
            if exc.status != 429 or not exc.retry_after or exc.retry_after > 30:
                raise
            await asyncio.sleep(exc.retry_after)
            return await self._call(SEND, payload)

    async def typing(self, chat=None, thread: int | None = None) -> bool:
        """Show "typing..." at the top of the chat, for about five seconds.

        In the private chat, or in `chat` and its topic `thread` when given.
        A nicety, so every way it can fail is swallowed and only answered with
        False: a turn is never held up or failed by the dots.
        """
        try:
            _, own = self._needed()
            payload = {"chat_id": own if chat in (None, "") else chat, "action": "typing"}
            if thread:
                payload["message_thread_id"] = int(thread)
            await self._call(TYPING, payload, timeout=8.0)
            return True
        except NotSetUp:
            return False
        except NotSent as exc:
            log.debug("the typing dots were not shown: %s", exc)
            return False

    async def react(self, chat, message_id: int, emoji: str) -> bool:
        """Put one emoji reaction on a message: Got it (`rouh/got_it.py`).

        A nicety like the typing dots, so every way it can fail is swallowed
        and only answered with False: nothing is ever held up by it.
        """
        try:
            _, own = self._needed()
            await self._call(REACT, {"chat_id": own if chat in (None, "") else chat,
                                     "message_id": int(message_id),
                                     "reaction": [{"type": "emoji", "emoji": emoji}]},
                             timeout=8.0)
            return True
        except NotSetUp:
            return False
        except (NotSent, TypeError, ValueError) as exc:
            log.debug("the reaction was not put: %s", exc)
            return False

    # --- buttons --------------------------------------------------------------

    async def pressed(self, query_id: str, text: str = "") -> bool:
        """Answer a press on a button: the spinner on it stops, and `text`, if
        any, shows for a moment at the top of the chat.

        Telegram wants every press answered, and keeps the button spinning
        until it is. A nicety past that, so a failure is only answered with
        False: what the press does is never held up by it.
        """
        payload: dict = {"callback_query_id": str(query_id)}
        if text:
            if owner.has_marks(text):
                text = owner.say(text, await asyncio.to_thread(_phone_owner_id))
            payload["text"] = text[:200]
        try:
            await self._call(PRESSED, payload, timeout=8.0)
            return True
        except (NotSetUp, NotSent) as exc:
            log.debug("a press on a button was not answered: %s", exc)
            return False

    async def rebutton(self, message_id: int, buttons: list[list[dict]] | None) -> bool:
        """Put these buttons under a message sent earlier, or take them all off.

        For a question that has been answered - the fork cancelled, the chat
        moved to - so what is left under it says what is true now. The same
        nicety as `pressed`: False, and nothing else, when it did not work,
        which it will not for a message older than Telegram lets a bot edit.
        """
        try:
            _, chat = self._needed()
            if buttons and owner.OPEN in json.dumps(buttons, ensure_ascii=False):
                buttons = owner.say_all(buttons, await asyncio.to_thread(_phone_owner_id))
            await self._call(REBUTTON, {"chat_id": chat, "message_id": int(message_id),
                                        "reply_markup": {"inline_keyboard": buttons or []}},
                             timeout=8.0)
            return True
        except (NotSetUp, NotSent, TypeError, ValueError) as exc:
            log.debug("the buttons under a message were not changed: %s", exc)
            return False

    # --- a fork's group, and the menu -----------------------------------------

    async def me(self) -> dict:
        """Who the bot is (getMe): its id, its @username. Asked once a process."""
        if not getattr(self, "_me", None):
            got = await self._call(ME, {}, timeout=8.0)
            self._me = got if isinstance(got, dict) else {}
        return self._me

    async def invite_link(self, chat) -> str:
        """A link that opens a group the bot is an admin of, or "" when there is none.

        For the private chat to point at a fork's group, which has no address
        of its own: a group made by a person is private, and only an invite
        link opens it. A member following it is simply taken there.
        """
        try:
            got = await self._call(LINK, {"chat_id": chat, "name": "Rouh"}, timeout=8.0)
        except (NotSetUp, NotSent) as exc:
            log.debug("no link into a group: %s", exc)
            return ""
        return str((got or {}).get("invite_link") or "") if isinstance(got, dict) else ""

    async def set_commands(self, commands: list[tuple[str, str]], scope: dict) -> bool:
        """Put these commands in the menu of the chat for `scope`, and nobody else.

        `commands` are (command, what it does) pairs. The scope is always one
        chat, or one person in one chat - the owner's - so nobody who finds the bot
        is shown what it can do for him. False, and a line in the log, when it
        did not work: the commands still work typed, and the next start tries
        again.
        """
        try:
            if any(owner.has_marks(d) for _, d in commands):
                whose = await asyncio.to_thread(_phone_owner_id)
                commands = [(c, owner.say(d, whose)) for c, d in commands]
            await self._call(COMMANDS, {"commands": [{"command": c, "description": d}
                                                     for c, d in commands],
                                        "scope": scope}, timeout=10.0)
            return True
        except (NotSetUp, NotSent) as exc:
            log.warning("the commands were not put in the chat's menu: %s", exc)
            return False

    # --- reading ------------------------------------------------------------

    async def updates(self, offset: int | None, wait: float = POLL_SECONDS) -> list[dict]:
        """The messages waiting at Telegram, from `offset` on.

        A long poll: Telegram holds the request open for up to `wait` seconds
        and answers the moment something arrives. Asking with an offset tells
        Telegram every update before it has been dealt with, and it forgets
        them; that is the only thing that ever tells it so, which is why
        `telegram_chat` asks for the next one only once the last is safely
        taken. Only messages and presses on the bot's own buttons are asked
        for (`READ`): an edited message, a reaction and the rest never arrive.
        """
        payload: dict = {"timeout": int(max(0, wait)), "allowed_updates": list(READ)}
        if offset is not None:
            payload["offset"] = int(offset)
        result = await self._call(UPDATES, payload, timeout=max(0, wait) + 15)
        return [u for u in (result or []) if isinstance(u, dict) and "update_id" in u]

    async def download(self, file_id: str, size: int | None = None) -> bytes:
        """The bytes of a file somebody sent: a photo, a document, a voice note.

        Two requests, the way the Bot API has it: which path Telegram keeps
        the file at, then the file itself from its own address, which carries
        the token as well. Raises :class:`NotSent` in a sentence the person
        can be told.
        """
        if size and size > MOST_FILE_BYTES:
            raise NotSent("it is bigger than the 20 MB a bot is allowed to download")
        token, _ = self._needed()
        found = await self._call(FILE, {"file_id": str(file_id)})
        path = (found or {}).get("file_path") if isinstance(found, dict) else None
        if not path:
            raise NotSent("Telegram did not say where the file is")
        if int((found or {}).get("file_size") or 0) > MOST_FILE_BYTES:
            raise NotSent("it is bigger than the 20 MB a bot is allowed to download")
        url = f"{self.api_base}/file/bot{token}/{path}"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.get(url)
        except httpx.HTTPError as exc:
            raise Unreachable(f"Telegram could not be reached ({type(exc).__name__}).") from None
        if response.status_code != 200:
            raise NotSent(f"Telegram would not hand the file over ({response.status_code})")
        return response.content

    # --- whose phone ---------------------------------------------------------

    def recent(self, within: float = 24 * 3600) -> list[tuple[float, str]]:
        """What was sent to the phone in the last day, oldest first, by any
        part of Rouh and before any restart. Reads the database, so call it
        off the event loop; what this client sent is the answer when the
        database cannot be read."""
        try:
            sent = _get_sent()
        except Exception:
            log.exception("what was sent to the phone could not be read")
            sent = list(self.sent)
        now = time.time()
        return [(at, words) for at, words in sent if now - at <= within]


#: Where `Telegram.sent` is written down, in `app_state`: the bot's, like the
#: offset `telegram_chat` keeps there, and nobody's row.
SENT_STATE = "telegram_sent"


def _get_sent() -> list[tuple[float, str]]:
    from .models import AppState

    value = AppState.objects.filter(key=SENT_STATE).values_list("value", flat=True).first()
    try:
        got = json.loads(value or "[]")
    except ValueError:
        return []
    return [(float(at), str(words)) for at, words in got
            if isinstance(words, str)] if isinstance(got, list) else []


def _set_sent(sent: list[tuple[float, str]]) -> None:
    from .models import AppState

    AppState.objects.bulk_create([AppState(key=SENT_STATE, value=json.dumps(sent))],
                                 update_conflicts=True, unique_fields=["key"],
                                 update_fields=["value"])


def phone_owner(tenancy):
    """Whose phone the bot on this machine reaches: the person who owns the install.

    The first administrator of the default organisation, which is the first
    account there ever was. One answer for everything that asks: mail alerts
    about whose inbox may go to the phone (`mail_alerts.phone_owner`), and
    whose turn a message from the phone is (`telegram_chat`).
    """
    from .models import User
    from .tenancy import DEFAULT_ORG_ID

    user = (User.objects.filter(is_active=True, is_org_admin=True, org_id=DEFAULT_ORG_ID)
            .order_by("id").first())
    return tenancy.identity_of(str(user.pk)) if user is not None else None


def _phone_owner_id() -> str:
    """The account id of the person whose phone this bot reaches, or "" when
    there is none: whose name a message's marks are filled in with."""
    try:
        from .tenancy import Tenancy

        found = phone_owner(Tenancy())
    except Exception:                               # noqa: BLE001 - text must still go out
        log.exception("whose phone the bot reaches could not be read")
        return ""
    return str(found.user_id) if found is not None else ""
