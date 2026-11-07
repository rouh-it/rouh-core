"""A trusted contact writing to Rouh on Telegram, held to exactly what they may do by email.

Petar, 5 October 2026: "Enable [a trusted contact] to use Rouh over Telegram by extending the
existing trusted-contact and permission-guardrail system to Telegram, rather
than inventing a separate authorization model." So there is no new permission
here at all. A Telegram account is one more way a trusted contact is
recognised, beside the exact addresses Petar ticked (`trusted.Trusted.telegram`),
and every message from it is a case like an email from them
(`rouh/mail_cases.py`): read by a turn that may only read, routed by the code
ask by ask against the grants they hold (`mail_ledger.judge`), carried out with
only their grants' tools or after Petar's approval, verified, and only then
answered - on Telegram instead of by email, through the one outbox
(`rouh/mail_outbox.py`).

**Linking is three presses, and nobody's but theirs and his.**

1. Petar makes a one-time code on their page in Settings > Trusted contacts
   (`Links.make_code`). Only the person whose phone the bot reaches can,
   because the bot is his and so are the cases it opens. The code is shown
   once, as a t.me link and as "/start <code>"; only its sha256 is kept, and
   it lapses after `CODE_HOURS`.
2. They send it to the bot from their own Telegram account, in a private chat
   (`Links.claim`). Telegram vouches for which account sent it - the `from` of
   a message a bot reads is Telegram's, not the sender's - so that account's
   id is what is written down. The code is spent on the spot. Petar's own
   account can never claim one, and an account already linked to somebody
   else cannot claim another.
3. Petar sees which account it was - its name, its @username, its id - and
   confirms it on their page, or refuses it (`Links.confirm`). Only then is it
   "linked", and only then does a message from it reach anything.

Nothing in this file ever links an account on its own, and nothing guesses one.

**Who is let through.** A message from Petar's own chat is his, and goes the
way it always has (`telegram_chat.PhoneChat.mine`); nothing here changes it.
Anybody else is passed here only from a private chat with the bot, from a
person and not a bot (`shaped`), and here:

- a /start with a code is a claim, answered with one fixed sentence;
- a message from an account linked and confirmed is a case of the contact it
  is linked to, opened under Petar's account, in a conversation of its own -
  never General, never his phone turn, never his identity;
- anything else is written in the log, as who it was and never what it said,
  and dropped: not answered, not stored, not put in front of the model.

A contact switched off, or one whose link was undone, is the same as on email:
switched off, everything from them waits for Petar; unlinked, their account is
nobody again. Making, confirming or undoing a link moves the contact's
revision, so an approval asked under the old trust lapses and the case is read
again (`mail_cases.CaseDesk.reread_for`).
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import re
import secrets
import time
from email.utils import formatdate

log = logging.getLogger("rouh.telegram_guests")

#: How long a link code holds.
CODE_HOURS = 48

WAITING, CLAIMED, LINKED = "waiting", "claimed", "linked"

#: How a case names a sender who wrote on Telegram (`trusted.Trusted.recognises`).
SENDER = "telegram:"

#: A case's message id and conversation for a Telegram message: never a Gmail id.
CASE_PREFIX = "tg:"

#: How many wrong codes one Telegram account may send in `TRIES_WINDOW` seconds
#: before it is not answered at all.
TRIES = 5
TRIES_WINDOW = 3600.0

#: How long before "still waiting for the owner to confirm" is said to the same account again.
WAITING_SAID_EVERY = 600.0

_START = re.compile(r"^/start(?:@\w+)?(?:\s+(\S+))?\s*$", re.IGNORECASE)
_HELP = re.compile(r"^/help(?:@\w+)?\s*$", re.IGNORECASE)
_CODE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def code_hash(code: str) -> str:
    return hashlib.sha256(str(code or "").strip().encode()).hexdigest()


def sender_of(tg_user_id) -> str:
    return f"{SENDER}{str(tg_user_id).strip()}"


def on_telegram(case_or_message_id) -> bool:
    """Whether a case (or its message id) came on Telegram, not by email."""
    mid = case_or_message_id if isinstance(case_or_message_id, str) else \
        str(getattr(case_or_message_id, "message_id", "") or "")
    return mid.startswith(CASE_PREFIX)


def account_said(name: str, username: str, tg_user_id) -> str:
    """A Telegram account in words: its name, its @username, its id."""
    bits = [name.strip() or "no name"]
    if username:
        bits.append("@" + username.lstrip("@"))
    return f"{', '.join(bits)} (Telegram id {tg_user_id})"


def linked_senders(user_id: str, org_id: str, contact_id) -> list[str]:
    """The Telegram accounts linked and confirmed for one contact, as case senders."""
    from .models import TelegramLink

    if not user_id or not org_id or not contact_id:
        return []
    return [sender_of(x) for x in TelegramLink.objects.filter(
        user_id=user_id, org_id=org_id, contact_id=contact_id, state=LINKED)
        .exclude(tg_user_id="").values_list("tg_user_id", flat=True)]


def _bump(user_id: str, org_id: str, contact_id) -> None:
    """A change of who the contact is recognised as: their revision moves."""
    from django.db.models import F

    from .models import TrustedContact

    TrustedContact.objects.filter(user_id=user_id, org_id=org_id, id=contact_id).update(
        revision=F("revision") + 1, updated_at=time.time())


class Links:
    """The links between trusted contacts and their own Telegram accounts, for one person.

    Every query names the person and the organisation (`AGENTS.md`, "Whose data is it").
    """

    @staticmethod
    def _q(user_id: str, org_id: str):
        from .models import TelegramLink

        if not user_id or not org_id:
            raise ValueError("a link belongs to a person in an organisation")
        return TelegramLink.objects.filter(user_id=user_id, org_id=org_id)

    def state(self, user_id: str, org_id: str, contact_id) -> dict:
        """What their page shows: the state, the account, and when, or {} for none."""
        row = self._q(user_id, org_id).filter(contact_id=contact_id).first()
        if row is None:
            return {}
        now = time.time()
        if row.state == WAITING and row.code_expires_at <= now:
            return {"state": "lapsed", "made_at": row.made_at,
                    "expires_at": row.code_expires_at}
        return {"state": row.state, "tg_user_id": row.tg_user_id, "tg_name": row.tg_name,
                "tg_username": row.tg_username, "made_at": row.made_at,
                "expires_at": row.code_expires_at if row.state == WAITING else 0,
                "claimed_at": row.claimed_at, "linked_at": row.linked_at,
                "account": account_said(row.tg_name, row.tg_username, row.tg_user_id)
                if row.tg_user_id else ""}

    def make_code(self, user_id: str, org_id: str, contact_id) -> tuple[str, float]:
        """A fresh one-time code for this contact: (the code, when it lapses).

        Any earlier code, claim or link of theirs is replaced, so a new code is
        also how Petar starts again. The code is returned once and never kept.
        """
        from django.db import transaction

        from .models import TelegramLink, TrustedContact

        if not TrustedContact.objects.filter(user_id=user_id, org_id=org_id,
                                             id=contact_id).exists():
            raise ValueError("That contact is not one of yours.")
        code = secrets.token_urlsafe(18)
        now = time.time()
        until = now + CODE_HOURS * 3600
        with transaction.atomic():
            had = self._q(user_id, org_id).filter(contact_id=contact_id).first()
            was_linked = had is not None and had.state == LINKED
            self._q(user_id, org_id).filter(contact_id=contact_id).delete()
            TelegramLink.objects.create(user_id=user_id, org_id=org_id, contact_id=contact_id,
                                        state=WAITING, code_hash=code_hash(code),
                                        code_expires_at=until, made_at=now, updated_at=now)
            if was_linked:
                _bump(user_id, org_id, contact_id)
        return code, until

    def claim(self, user_id: str, org_id: str, code: str, *, tg_user_id, name: str,
              username: str, owner_chat: str) -> tuple[str, int, str]:
        """A Telegram account sent a code. (outcome, contact id, contact name).

        Outcomes: "claimed" (the code was good, and is spent), "bad" (no such
        code, or it lapsed), "own" (Petar's own account, which never claims),
        "taken" (this account is already some contact's).
        """
        from django.db import IntegrityError, transaction

        from .models import TrustedContact

        tg = str(tg_user_id or "").strip()
        if not tg or not _CODE.match(str(code or "")):
            return "bad", 0, ""
        if owner_chat and tg == str(owner_chat).strip():
            return "own", 0, ""
        now = time.time()
        try:
            with transaction.atomic():
                row = (self._q(user_id, org_id).select_for_update()
                       .filter(state=WAITING, code_hash=code_hash(code),
                               code_expires_at__gt=now).first())
                if row is None:
                    return "bad", 0, ""
                if self._q(user_id, org_id).filter(tg_user_id=tg).exclude(id=row.id).exists():
                    return "taken", 0, ""
                row.state, row.code_hash, row.code_expires_at = CLAIMED, "", 0
                row.tg_user_id, row.tg_name, row.tg_username = tg, name[:200], username[:100]
                row.claimed_at = row.updated_at = now
                row.save()
        except IntegrityError:
            return "taken", 0, ""
        contact = TrustedContact.objects.filter(user_id=user_id, org_id=org_id,
                                                id=row.contact_id).values("name").first()
        return "claimed", row.contact_id, (contact or {}).get("name") or "them"

    def confirm(self, user_id: str, org_id: str, contact_id, tg_user_id) -> dict:
        """Petar's yes: the account that claimed their code is theirs. The row, as `state`.

        Bound to the account he was shown: if another claim replaced it, or it
        is not waiting for him, nothing is linked.
        """
        from django.db import transaction

        tg = str(tg_user_id or "").strip()
        with transaction.atomic():
            row = (self._q(user_id, org_id).select_for_update()
                   .filter(contact_id=contact_id).first())
            if row is None or row.state != CLAIMED or not tg or row.tg_user_id != tg:
                raise ValueError("That Telegram account is not waiting to be confirmed for "
                                 "them any more. Nothing was linked.")
            now = time.time()
            row.state, row.linked_at, row.updated_at = LINKED, now, now
            row.save()
            _bump(user_id, org_id, contact_id)
        return self.state(user_id, org_id, contact_id)

    def drop(self, user_id: str, org_id: str, contact_id) -> dict:
        """Undo whatever is there - a code, a claim or a link. What it was, as `state`."""
        from django.db import transaction

        with transaction.atomic():
            was = self.state(user_id, org_id, contact_id)
            gone = self._q(user_id, org_id).filter(contact_id=contact_id).delete()[0]
            if gone and was.get("state") == LINKED:
                _bump(user_id, org_id, contact_id)
        return was if gone else {}

    def of_account(self, user_id: str, org_id: str, tg_user_id) -> dict | None:
        """Whose this Telegram account is, if anybody's: {"contact_id", "state", "linked_at"}."""
        tg = str(tg_user_id or "").strip()
        if not tg:
            return None
        return (self._q(user_id, org_id).filter(tg_user_id=tg)
                .values("contact_id", "state", "linked_at", "tg_name", "tg_username").first())


def chat_of_thread(user_id: str, org_id: str, thread_id: str) -> str:
    """The conversation the last case of this Telegram chat was handled in, or ""."""
    from .models import MailCase

    if not thread_id:
        return ""
    return (MailCase.objects.filter(user_id=user_id, org_id=org_id, thread_id=thread_id)
            .exclude(chat_id="").order_by("-id").values_list("chat_id", flat=True).first()
            or "")


# --- what the bot says to them -------------------------------------------------------

CLAIMED_SAID = ("Thank you, {first}. {owner} will now confirm that this Telegram account is "
                "yours. I will tell you here once that is done, and until then I cannot take "
                "requests here.")
#: Said to whoever sent it, who may be anybody: so it names nobody.
BAD_CODE = ("That link code is not valid. It may have been used already or have lapsed. "
            "Ask for a new one.")
TAKEN = "This Telegram account is already linked. Nothing was changed."
STILL_WAITING = ("{owner} has not confirmed this Telegram account yet, so I cannot take "
                 "requests here. I will tell you here once it is done.")
LINKED_SAID = ("{owner} confirmed this Telegram account. You can write to me here now, and I "
               "will help with what {owner} has allowed, as I do by email. Anything that "
               "needs {owner} waits for ‹him› first.")
UNLINKED_SAID = "This Telegram account is no longer linked, so I will not take requests here."
HELP_SAID = ("Write to me here and I will answer, within what {owner} has allowed you, as I "
             "do by email. Anything that needs {owner} waits for ‹him› first, and I answer "
             "here once it is done.")
TEXT_ONLY = ("I can only read typed messages here so far. Write it out here, or send it by "
             "email.")
NOT_HERE = ("I cannot take requests on Telegram on this server right now. Write by email "
            "instead.")


class Guests:
    """Messages to the bot from anybody but Petar: a code, a linked contact, or nobody.

    Handed Rouh's running pieces by runtime.py, like `telegram_chat.PhoneChat`:
    the bot, whose phone it is (`owner`), the case desk while there is one
    (`desk`, None where there is no mail), and the public address for links.
    """

    def __init__(self, telegram, *, owner, desk, public_url: str = "",
                 links: Links | None = None) -> None:
        self.telegram = telegram
        self.owner = owner
        self.desk = desk
        self.public_url = (public_url or "").rstrip("/")
        self.links = links or Links()
        self._tries: dict[str, list[float]] = {}
        self._waiting_said: dict[str, float] = {}

    # --- who may be passed here ------------------------------------------------

    def shaped(self, message) -> bool:
        """A message a guest could have sent: a person, not a bot, in their private
        chat with the bot, and not Petar. Everything else is never looked at here."""
        if not isinstance(message, dict):
            return False
        chat = message.get("chat") or {}
        person = message.get("from") or {}
        sender = str(person.get("id") or "").strip()
        return (bool(sender) and not person.get("is_bot") and chat.get("type") == "private"
                and str(chat.get("id") or "").strip() == sender
                and sender != str(self.telegram.chat() or "").strip())

    @staticmethod
    def _owner_name(who) -> str:
        """What a guest is told the owner is called: their name, never anybody else's."""
        from . import owner

        found = owner.resolve(who)
        first = (found.name if found is not None else "") or \
            ((getattr(who, "name", "") or "").split() or [""])[0]
        return first[:1].upper() + first[1:] if first else owner.NOBODY

    async def _say(self, tg_user_id: str, text: str, why: str = "note") -> bool:
        """One of the code's own fixed notes to a Telegram account about its link: through the
        one outbox, written down whole like every message to somebody other than Petar
        (`rouh/mail_outbox.py`). True when it went."""
        from . import mail_outbox

        who = await asyncio.to_thread(self.owner)
        if who is None:
            return False
        ok = await mail_outbox.link_note(self.telegram, who.user_id, who.org_id,
                                         str(tg_user_id), text, why=why)
        if not ok:
            log.warning("telegram: could not answer Telegram account %s", tg_user_id)
        return ok

    def _too_many(self, tg_user_id: str) -> bool:
        now = time.monotonic()
        tries = [t for t in self._tries.get(tg_user_id, []) if now - t < TRIES_WINDOW]
        tries.append(now)
        self._tries[tg_user_id] = tries
        return len(tries) > TRIES

    # --- one message -----------------------------------------------------------------

    async def take(self, message: dict) -> None:
        """One message from somebody who is not Petar, in a private chat with the bot."""
        person = message.get("from") or {}
        tg_id = str(person.get("id") or "").strip()
        name = " ".join(filter(None, [str(person.get("first_name") or "").strip(),
                                      str(person.get("last_name") or "").strip()]))
        username = str(person.get("username") or "").strip()
        who = await asyncio.to_thread(self.owner)
        if who is None or not tg_id:
            log.warning("telegram: a message from Telegram account %s was ignored: there is "
                        "no owner account", tg_id)
            return
        owner_name = self._owner_name(who)
        text = str(message.get("text") or "").strip()
        found = await asyncio.to_thread(self.links.of_account, who.user_id, who.org_id, tg_id)
        start = _START.match(text) if text else None
        if start and start.group(1):
            if found and found.get("state") == LINKED:
                await self._say(tg_id, TAKEN)
                return
            await self._claim(who, owner_name, start.group(1), tg_id, name, username)
            return
        if found and found.get("state") == LINKED:
            await self._from_linked(who, owner_name, message, found, tg_id, text)
            return
        if found and found.get("state") == CLAIMED:
            now = time.monotonic()
            if now - self._waiting_said.get(tg_id, -1e9) >= WAITING_SAID_EVERY:
                self._waiting_said[tg_id] = now
                await self._say(tg_id, STILL_WAITING.format(owner=owner_name))
            return
        # Nobody: who it was, so a person setting a link up can be found in the
        # log, and never what it said.
        log.warning("telegram: a message from Telegram account %s (%s) was ignored: it is "
                    "not linked to any trusted contact", tg_id,
                    "@" + username if username else name or "no name")

    async def _claim(self, who, owner_name: str, code: str, tg_id: str, name: str,
                     username: str) -> None:
        if self._too_many(tg_id):
            log.warning("telegram: Telegram account %s sent too many link codes; not answered",
                        tg_id)
            return
        outcome, contact_id, contact_name = await asyncio.to_thread(
            self.links.claim, who.user_id, who.org_id, code, tg_user_id=tg_id, name=name,
            username=username, owner_chat=self.telegram.chat())
        log.info("telegram: Telegram account %s sent a link code: %s", tg_id, outcome)
        if outcome == "own":
            return
        if outcome == "taken":
            await self._say(tg_id, TAKEN)
            return
        if outcome != "claimed":
            await self._say(tg_id, BAD_CODE)
            return
        first = (name.split() or ["there"])[0]
        await self._say(tg_id, CLAIMED_SAID.format(first=first, owner=owner_name))
        from . import genes

        page = f"{self.public_url}{genes.BY_ID['trusted-contacts']['route']}/{contact_id}"
        note = (f"A Telegram account used {contact_name}'s link code: "
                f"{account_said(name, username, tg_id)}. Nothing reaches Rouh from it until "
                f"you confirm it is theirs, on their page:\n{page}")
        from . import telegram as tg

        try:
            await self.telegram.send(note, remember=False, who=who)
        except (tg.NotSetUp, tg.NotSent) as exc:
            log.warning("telegram: the owner could not be told of a link claim: %s", exc)

    async def _from_linked(self, who, owner_name: str, message: dict, found: dict, tg_id: str,
                           text: str) -> None:
        if not text:
            await self._say(tg_id, TEXT_ONLY)
            return
        if _START.match(text) or _HELP.match(text):
            await self._say(tg_id, HELP_SAID.format(owner=owner_name))
            return
        desk = self.desk()
        if desk is None:
            log.warning("telegram: a message from linked Telegram account %s was not taken: "
                        "there is no case desk on this server (no Google)", tg_id)
            await self._say(tg_id, NOT_HERE)
            return
        contact = await asyncio.to_thread(desk.trust.get, who.user_id, who.org_id,
                                          found["contact_id"])
        if contact is None:
            return
        person = message.get("from") or {}
        sent = float(message.get("date") or time.time())
        thread = f"{CASE_PREFIX}{tg_id}"
        shown = f"{contact.name} (on Telegram)"
        email = {"id": f"{thread}:{message.get('message_id')}", "thread_id": thread,
                 "from": shown, "to": "Rouh, on Telegram", "cc": "",
                 "subject": "Telegram message", "body": text,
                 "date": formatdate(sent, localtime=True), "attachments": [],
                 "channel": "telegram", "telegram_id": tg_id,
                 "telegram_account": account_said(
                     " ".join(filter(None, [str(person.get("first_name") or ""),
                                            str(person.get("last_name") or "")])).strip(),
                     str(person.get("username") or ""), tg_id)}
        when = time.strftime("%-d %B %Y", time.localtime(found.get("linked_at") or 0))
        said = (f"it came from Telegram account {tg_id}, which {contact.name} linked "
                f"themselves and you confirmed on {when}")
        open_chat = getattr(desk.alerts, "open_chat", None)
        chat = ""
        if open_chat is not None:
            was = await asyncio.to_thread(chat_of_thread, who.user_id, who.org_id, thread)
            title = f"✈️ {contact.name}: {' '.join(text.split())[:50]}"
            chat = await open_chat(was, title)
        with contextlib.suppress(Exception):
            await self.telegram.typing(int(tg_id))
        await desk.take(who, email, contact=contact, chat=chat, identity_ok=True,
                        identity_said=said, sender=sender_of(tg_id), sender_name=contact.name,
                        soon=True)
        log.info("telegram: a message from linked Telegram account %s is a case of trusted "
                 "contact %s", tg_id, contact.id)

    # --- from Petar's page -------------------------------------------------------------

    async def tell(self, tg_user_id: str, text: str) -> None:
        """One fixed sentence to a contact's Telegram account: linked, or not any more."""
        if tg_user_id:
            await self._say(str(tg_user_id), text)

    async def bot_link(self, code: str) -> str:
        """The t.me address that opens the bot with this code, or "" if the bot has no name."""
        with contextlib.suppress(Exception):
            me = await self.telegram.me()
            name = str((me or {}).get("username") or "")
            if name:
                return f"https://t.me/{name}?start={code}"
        return ""
