"""The owner's own Telegram account, connected to Rouh: what makes a group for each fork.

Petar, 27 September 2026, of forks made on Telegram: "it forks a conversation
indeed but does not open the forked conversation in a new group chat in
telegram. please check on the server how my other project does that when i add new
idea and choose to talk about that idea only."

A bot cannot make a group: no method of the Bot API does. That project makes one for each
idea with his own account, through Telethon (MTProto, the protocol the apps
speak), and puts its bot in it (its own Telethon service,
on the same server). Rouh does the same, with a session of its own: that project's is not read,
and one session used from two servers at once is one Telegram ends for both.

**What the account is used for, and nothing else.** Opening a group for a fork,
with Rouh's bot in it; making the bot its admin, so it hears everything
written there whatever its privacy setting; and posting the fork's first
message there as him, so the group starts with his own words. Nothing in his
account is read: no chat, no contact, no message but the ones it posts.

**Connecting.** In Settings (`rouh/web/telegram_account.py`), once: the API id
and hash of the app he registered at my.telegram.org (another project's are the same kind,
and may be the same pair), his phone number, the code Telegram sends to his
Telegram, and his password when he has two-step verification. The code and the
password are passed to Telegram and never kept. Between the steps, the
half-made session and what the next step needs are kept sealed
(`TelegramAccount.pending_sealed`); once he is in, the session is kept sealed
(`encryption.SecretBox`), keyed by user and organisation, never in a log line,
a response or the repository. Disconnect logs the session out at Telegram and
forgets it.

**Who speaks to Telegram.** Telethon, in the service, for as long as each step
takes (`Telethon`). A test world is pointed at the stand-in instead
(`StandIn`, `ROUH_TELEGRAM_ACCOUNT_URL`, `rouh/testing/fake_telegram.py`),
which answers the same questions over HTTP, so nothing in a world reaches
Telegram or can sign anybody in.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from .encryption import CannotOpen, SecretBox

log = logging.getLogger("rouh.telegram_account")
# Telethon says which data centre it is connecting to at INFO, on every step;
# nothing a person reading Rouh's log needs, and never anything secret.
logging.getLogger("telethon").setLevel(logging.WARNING)

#: A group's name: the fork's, after a fork mark, as short as Telegram lists it.
TITLE_CHARS = 64

REVOKED = ("Telegram no longer accepts Rouh's session: it was logged out, perhaps from the "
           "list of devices in Telegram's settings. Connect the account again in Rouh's "
           "Settings.")
UNREADABLE = ("Rouh cannot open the stored Telegram session with this server's encryption "
              "key, so the account has to be connected again.")


class NotConnected(RuntimeError):
    """There is no Telegram account connected for this person."""


class Refused(RuntimeError):
    """Telegram, or the stand-in, said no; the words are for the person."""


class PasswordNeeded(Exception):
    """The code was right, and the account has two-step verification on."""

    def __init__(self, session: str) -> None:
        super().__init__("password needed")
        self.session = session


@dataclass(frozen=True)
class Creds:
    api_id: int
    api_hash: str
    session: str


def phone_hint(phone: str) -> str:
    digits = "".join(c for c in str(phone or "") if c.isdigit())
    return "…" + digits[-3:] if len(digits) >= 3 else ""


def clean_phone(phone: str) -> str:
    """A phone number as Telegram takes it: +, then digits, nothing else."""
    digits = "".join(c for c in str(phone or "") if c.isdigit())
    if str(phone or "").strip().startswith("00"):
        digits = digits[2:]
    return "+" + digits if digits else ""


def group_title(name: str) -> str:
    """A fork's group name: a fork mark and what the fork is about."""
    name = " ".join(str(name or "").split()) or "A fork"
    if len(name) > TITLE_CHARS:
        name = name[:TITLE_CHARS - 1].rstrip(" ,.;:-") + "…"
    return "🍴 " + name


# --- who speaks to Telegram -----------------------------------------------------------


def _words(exc: Exception) -> str:
    """A Telethon error as a sentence for the person, never with a secret in it."""
    from telethon import errors

    if isinstance(exc, errors.ApiIdInvalidError):
        return ("Telegram does not know that API id and hash. Copy them again from "
                "my.telegram.org, under API development tools.")
    if isinstance(exc, errors.PhoneNumberInvalidError):
        return "Telegram says that phone number is not valid. Write it with the country code."
    if isinstance(exc, (errors.PhoneNumberBannedError, errors.PhoneNumberUnoccupiedError)):
        return "Telegram will not sign in that phone number."
    if isinstance(exc, errors.PhoneCodeInvalidError):
        return "That code is not right. Check it in Telegram and type it again."
    if isinstance(exc, errors.PhoneCodeExpiredError):
        return "That code has expired. Start again for a new one."
    if isinstance(exc, errors.PasswordHashInvalidError):
        return "That is not your Telegram password."
    if isinstance(exc, errors.FloodWaitError):
        minutes = max(1, round(int(getattr(exc, "seconds", 60) or 60) / 60))
        return f"Telegram says to wait {minutes} minute{'s' if minutes != 1 else ''} first."
    if isinstance(exc, (errors.AuthKeyUnregisteredError, errors.SessionRevokedError,
                        errors.SessionExpiredError, errors.UserDeactivatedError)):
        return REVOKED
    if isinstance(exc, errors.RPCError):
        return f"Telegram said no ({type(exc).__name__})."
    if isinstance(exc, (ConnectionError, OSError, TimeoutError)):
        return "Telegram could not be reached."
    return f"That did not work ({type(exc).__name__})."


class Telethon:
    """Telegram itself, through Telethon: one connection for each thing asked."""

    def _client(self, api_id: int, api_hash: str, session: str = ""):
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        return TelegramClient(StringSession(session or ""), int(api_id), api_hash,
                              device_model="Rouh", app_version="rouh", system_version="server",
                              receive_updates=False)

    async def _run(self, client, work):
        try:
            await client.connect()
            return await work(client)
        except (Refused, PasswordNeeded, NotConnected):
            raise
        except Exception as exc:
            raise Refused(_words(exc)) from None
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def send_code(self, api_id: int, api_hash: str, phone: str) -> tuple[str, str]:
        client = self._client(api_id, api_hash)

        async def work(c):
            sent = await c.send_code_request(phone)
            return c.session.save(), sent.phone_code_hash

        return await self._run(client, work)

    async def sign_in(self, api_id: int, api_hash: str, session: str, phone: str, code: str,
                      phone_code_hash: str) -> tuple[str, str]:
        from telethon import errors

        client = self._client(api_id, api_hash, session)

        async def work(c):
            try:
                me = await c.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            except errors.SessionPasswordNeededError:
                raise PasswordNeeded(c.session.save()) from None
            return c.session.save(), _name_of(me)

        return await self._run(client, work)

    async def password(self, api_id: int, api_hash: str, session: str,
                       password: str) -> tuple[str, str]:
        client = self._client(api_id, api_hash, session)

        async def work(c):
            me = await c.sign_in(password=password)
            return c.session.save(), _name_of(me)

        return await self._run(client, work)

    async def open_group(self, creds: Creds, title: str, bot_username: str,
                         then: Callable[[int], Awaitable] | None, first: str) -> int:
        """Make the group with the bot in it, make the bot its admin, let `then`
        say what it says first, and post `first` there as him. The group's id as
        the Bot API knows it."""
        from telethon.tl import types
        from telethon.tl.functions.messages import CreateChatRequest, EditChatAdminRequest

        client = self._client(creds.api_id, creds.api_hash, creds.session)

        async def work(c):
            if not await c.is_user_authorized():
                raise Refused(REVOKED)
            result = await c(CreateChatRequest(users=[bot_username], title=title))
            updates = getattr(result, "updates", result)
            chats = [ch for ch in (getattr(updates, "chats", None) or [])
                     if isinstance(ch, types.Chat)]
            if not chats:
                raise Refused("Telegram made no group.")
            chat = chats[0]
            if getattr(result, "missing_invitees", None):
                raise Refused("Rouh's bot could not be added to the group. In @BotFather, "
                              "allow it to be added to groups.")
            await c(EditChatAdminRequest(chat_id=chat.id, user_id=bot_username, is_admin=True))
            group = -int(chat.id)
            if then is not None:
                await then(group)
            if first:
                await c.send_message(types.PeerChat(chat.id), first, link_preview=False)
            return group

        return await self._run(client, work)

    async def log_out(self, creds: Creds) -> None:
        client = self._client(creds.api_id, creds.api_hash, creds.session)

        async def work(c):
            await c.log_out()

        await self._run(client, work)


def _name_of(me) -> str:
    first = str(getattr(me, "first_name", "") or "")
    last = str(getattr(me, "last_name", "") or "")
    user = str(getattr(me, "username", "") or "")
    return " ".join(p for p in (first, last) if p) or (("@" + user) if user else "")


class StandIn:
    """The stand-in for Telegram's user side, over HTTP (`rouh/testing/fake_telegram.py`).

    The same questions `Telethon` asks, of a test world's stand-in, so a world
    can connect an account and open a group for a fork without a real account,
    a real code or the network.
    """

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    async def _ask(self, what: str, body: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(f"{self.base}/_account/{what}", json=body)
            got = response.json()
        except (httpx.HTTPError, ValueError):
            raise Refused("Telegram could not be reached.") from None
        if got.get("password_needed"):
            raise PasswordNeeded(str(got.get("session") or ""))
        if got.get("error"):
            raise Refused(str(got["error"]))
        return got

    async def send_code(self, api_id, api_hash, phone):
        got = await self._ask("send_code", {"api_id": api_id, "api_hash": api_hash,
                                            "phone": phone})
        return got["session"], got["phone_code_hash"]

    async def sign_in(self, api_id, api_hash, session, phone, code, phone_code_hash):
        got = await self._ask("sign_in", {"api_id": api_id, "api_hash": api_hash,
                                          "session": session, "phone": phone, "code": code,
                                          "phone_code_hash": phone_code_hash})
        return got["session"], got.get("name") or ""

    async def password(self, api_id, api_hash, session, password):
        got = await self._ask("password", {"api_id": api_id, "api_hash": api_hash,
                                           "session": session, "password": password})
        return got["session"], got.get("name") or ""

    async def open_group(self, creds, title, bot_username, then, first):
        body = {"api_id": creds.api_id, "session": creds.session}
        got = await self._ask("create_group", dict(body, title=title, users=[bot_username]))
        group = int(got["chat_id"])
        await self._ask("make_admin", dict(body, chat_id=group, user=bot_username))
        if then is not None:
            await then(group)
        if first:
            await self._ask("send", dict(body, chat_id=group, text=first))
        return group

    async def log_out(self, creds):
        await self._ask("log_out", {"api_id": creds.api_id, "session": creds.session})


def backend():
    """Telegram, or the stand-in a test world names."""
    base = os.environ.get("ROUH_TELEGRAM_ACCOUNT_URL", "").strip()
    return StandIn(base) if base else Telethon()


# --- what is kept -----------------------------------------------------------------------


class AccountStore:
    """The connections. Every method takes both ids it is asking about."""

    def __init__(self, box: SecretBox) -> None:
        self._box = box

    def _row(self, user_id: str, org_id: str):
        from .models import TelegramAccount

        if not user_id or not org_id:
            return None
        return TelegramAccount.objects.filter(user_id=user_id, org_id=org_id).first()

    def begin(self, user_id: str, org_id: str, api_id: int, api_hash: str,
              pending: dict) -> None:
        """A login has started: the app, and what the code step needs, sealed."""
        from .models import TelegramAccount

        if not user_id or not org_id:
            raise ValueError("a Telegram account belongs to a user in an organisation")
        TelegramAccount.objects.update_or_create(
            user_id=user_id, org_id=org_id,
            defaults={"api_id": int(api_id), "api_hash_sealed": self._box.seal(api_hash),
                      "state": "code", "pending_sealed": self._box.seal(json.dumps(pending)),
                      "updated_at": time.time(), "last_error": ""})

    def waiting(self, user_id: str, org_id: str, state: str, pending: dict) -> None:
        from .models import TelegramAccount

        TelegramAccount.objects.filter(user_id=user_id, org_id=org_id).update(
            state=state, pending_sealed=self._box.seal(json.dumps(pending)),
            updated_at=time.time(), last_error="")

    def pending(self, user_id: str, org_id: str) -> tuple[Creds, dict] | None:
        """The app and the step a login is waiting on, or None."""
        row = self._row(user_id, org_id)
        if row is None or row.state not in ("code", "password") or not row.pending_sealed:
            return None
        try:
            api_hash = self._box.open_(row.api_hash_sealed)
            pending = json.loads(self._box.open_(row.pending_sealed))
        except (CannotOpen, ValueError):
            return None
        return Creds(int(row.api_id), api_hash, str(pending.get("session") or "")), pending

    def connected(self, user_id: str, org_id: str, session: str, name: str,
                  hint: str) -> None:
        from .models import TelegramAccount

        now = time.time()
        TelegramAccount.objects.filter(user_id=user_id, org_id=org_id).update(
            state="connected", pending_sealed="", session_sealed=self._box.seal(session),
            name=name, phone_hint=hint, connected_at=now, updated_at=now, last_error="")

    def creds(self, user_id: str, org_id: str) -> Creds | None:
        """The signed-in session, or None when there is none that opens."""
        row = self._row(user_id, org_id)
        if row is None or row.state != "connected" or not row.session_sealed:
            return None
        try:
            return Creds(int(row.api_id), self._box.open_(row.api_hash_sealed),
                         self._box.open_(row.session_sealed))
        except CannotOpen:
            return None

    def failed(self, user_id: str, org_id: str, words: str) -> None:
        from .models import TelegramAccount

        TelegramAccount.objects.filter(user_id=user_id, org_id=org_id).update(
            last_error=str(words or "")[:300], updated_at=time.time())

    def forget(self, user_id: str, org_id: str) -> bool:
        from .models import TelegramAccount

        if not user_id or not org_id:
            return False
        gone, _ = TelegramAccount.objects.filter(user_id=user_id, org_id=org_id).delete()
        return bool(gone)

    def summary(self, user_id: str, org_id: str) -> dict:
        """What Settings shows: never the hash, the session or the phone number."""
        row = self._row(user_id, org_id)
        if row is None:
            return {"connected": False, "state": "", "name": "", "phone_hint": "",
                    "connected_at": 0, "api_id": 0, "last_error": "", "unreadable": False}
        unreadable = False
        if row.state == "connected":
            try:
                self._box.open_(row.session_sealed)
            except CannotOpen:
                unreadable = True
        return {"connected": row.state == "connected" and not unreadable, "state": row.state,
                "name": row.name, "phone_hint": row.phone_hint,
                "connected_at": row.connected_at, "api_id": int(row.api_id or 0),
                "last_error": row.last_error, "unreadable": unreadable}


# --- the desk the pages and the phone use ---------------------------------------------------


class TelegramAccounts:
    """Connecting an account, and using it to open a group for a fork."""

    def __init__(self, store: AccountStore, speaker=None) -> None:
        self.store = store
        self.speaker = speaker if speaker is not None else backend()

    # --- connecting ----------------------------------------------------------

    async def start(self, who, api_id, api_hash: str, phone: str) -> str:
        """Ask Telegram to send the code. What to tell the person."""
        import asyncio

        try:
            api_id = int(str(api_id).strip())
        except (TypeError, ValueError):
            raise ValueError("The API id is a number, from my.telegram.org.") from None
        api_hash = str(api_hash or "").strip()
        if api_id <= 0 or len(api_hash) < 16:
            raise ValueError("Enter the API id and API hash from my.telegram.org, under API "
                             "development tools.")
        phone = clean_phone(phone)
        if len(phone) < 8:
            raise ValueError("Enter your phone number with its country code, like +44 7700 900123.")
        try:
            session, code_hash = await self.speaker.send_code(api_id, api_hash, phone)
        except Refused as exc:
            raise ValueError(str(exc)) from None
        await asyncio.to_thread(self.store.begin, who.user_id, who.org_id, api_id, api_hash,
                                {"session": session, "phone": phone,
                                 "phone_code_hash": code_hash})
        return ("Telegram sent you a code: it is in your Telegram app, in a message from "
                "Telegram. Type it here.")

    async def code(self, who, code: str) -> str:
        """The code from Telegram: signed in, or a password is still wanted."""
        import asyncio

        waiting = await asyncio.to_thread(self.store.pending, who.user_id, who.org_id)
        if waiting is None or waiting[1].get("phone_code_hash") is None:
            raise ValueError("There is no login waiting for a code. Start again.")
        creds, pending = waiting
        code = "".join(c for c in str(code or "") if c.isdigit())
        if not code:
            raise ValueError("Type the code Telegram sent you.")
        try:
            session, name = await self.speaker.sign_in(
                creds.api_id, creds.api_hash, creds.session, pending["phone"], code,
                pending["phone_code_hash"])
        except PasswordNeeded as more:
            await asyncio.to_thread(self.store.waiting, who.user_id, who.org_id, "password",
                                    {"session": more.session, "phone": pending["phone"]})
            return "password"
        except Refused as exc:
            await asyncio.to_thread(self.store.failed, who.user_id, who.org_id, str(exc))
            raise ValueError(str(exc)) from None
        await asyncio.to_thread(self.store.connected, who.user_id, who.org_id, session, name,
                                phone_hint(pending["phone"]))
        log.info("telegram account: connected for user %s", who.user_id)
        return "connected"

    async def password(self, who, password: str) -> str:
        import asyncio

        waiting = await asyncio.to_thread(self.store.pending, who.user_id, who.org_id)
        if waiting is None or waiting[1].get("phone_code_hash") is not None:
            raise ValueError("There is no login waiting for a password. Start again.")
        creds, pending = waiting
        if not password:
            raise ValueError("Type your Telegram password.")
        try:
            session, name = await self.speaker.password(creds.api_id, creds.api_hash,
                                                        creds.session, password)
        except Refused as exc:
            await asyncio.to_thread(self.store.failed, who.user_id, who.org_id, str(exc))
            raise ValueError(str(exc)) from None
        await asyncio.to_thread(self.store.connected, who.user_id, who.org_id, session, name,
                                phone_hint(pending["phone"]))
        log.info("telegram account: connected for user %s", who.user_id)
        return "connected"

    async def disconnect(self, who) -> bool:
        """Log Rouh's session out at Telegram, and forget it whatever Telegram said."""
        import asyncio

        creds = await asyncio.to_thread(self.store.creds, who.user_id, who.org_id)
        if creds is not None:
            try:
                await self.speaker.log_out(creds)
            except Refused as exc:
                log.warning("telegram account: logging out at Telegram did not work: %s", exc)
        return await asyncio.to_thread(self.store.forget, who.user_id, who.org_id)

    def summary(self, who) -> dict:
        return self.store.summary(who.user_id, who.org_id)

    def ready(self, who) -> bool:
        return who is not None and self.store.creds(who.user_id, who.org_id) is not None

    # --- using it -------------------------------------------------------------

    async def open_group(self, who, title: str, bot_username: str,
                         then: Callable[[int], Awaitable] | None = None, first: str = "") -> int:
        """A new group, made as him with the bot in it as its admin; its Bot API id."""
        import asyncio

        creds = await asyncio.to_thread(self.store.creds, who.user_id, who.org_id)
        if creds is None:
            raise NotConnected("no Telegram account is connected")
        try:
            return await self.speaker.open_group(creds, title, bot_username, then, first)
        except Refused as exc:
            await asyncio.to_thread(self.store.failed, who.user_id, who.org_id, str(exc))
            raise
