"""The one outbox: every message Rouh sends to somebody other than the owner about a case (D5).

Petar, 11 October 2026: a contact got the same holding note and status note twice, and an automatic
re-read of a case from 2 October sent her a reply without him. Until then six places in
`mail_cases` sent to a contact, each with a guard of its own. Now this module is the only one
that calls Gmail's send or Telegram's send for somebody who is not the owner, and every message
goes through `send`:

- **Keyed, so once.** Each message is a `models.MailOutbox` row, keyed by case, attempt, kind and
  channel, claimed before it goes and marked sent, failed or unknown after. A second call with
  the same key finds the row and sends nothing.
- **The gate's messages (D18)**: the first, once the asks are sorted, which says what is
  allowed and started and what needs the owner and waits (`GATE`); one for each batch of their
  decisions (`DECIDED`); and nothing else from the case. Each only when the ledger changed
  since the last one that went on that channel (`mail_ledger.said_state`), or the owner's own words
  started the attempt.
- **The work's own results (`RESULT`)**: what a started ask's work sends back for the contact,
  several that finished close together in one message, each once.
- **At most one acknowledgement per case**, and none once anything else went: only cases from
  before 12 October 2026 ever sent one.
- **What is never sent.** A message holding a bank account number, a card number, a password or
  a one-time code is refused here, whatever wrote it (`secrets_in`): sending those is a hard
  limit by what it does, not by what anything says.
- **Said as the owner's**: the code's words name the owner with marks (`rouh/owner.py`), and
  they are filled in here, for the person the case belongs to, before anything is kept or sent:
  a letter goes through Gmail, not `rouh/mailer.py`, so nothing else would fill them.
- **Written down whole**: the row, the sent log (`rouh/sentlog.py`) and the case's trace.
  What went before the outbox is in it as history (migration 0123), so these rules hold for
  cases opened before it too.

Nothing here decides whether a message should go: the case does (`mail_cases.CaseDesk`). This
decides only that it goes once, on the right channels, and is recorded. `rouh/mail_replay.py`
fails the landing if any other code sends to a contact.

Channels: a case's own (its email thread, the Telegram account that wrote, or the Slack
conversation and thread it was asked in, as Rouh's bot), each channel the same request also came
on (`MailCase.arrivals`), and the contact's own address when they asked on Telegram for it by
email. One message per channel.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
import time

from . import mail_ledger as ledger
from . import owner

log = logging.getLogger("rouh.mail_outbox")

ACK, REPLY, STATUS, FOLLOW_UP, LINK = "ack", "reply", "status", "follow_up", "link"
#: A Clockwork item of theirs, due (`send_item`, Petar, 12 October 2026).
CLOCKWORK = "clockwork"
#: The gate's messages (D18): what was started and what waits, and a batch of the owner's
#: decisions; and what a started ask's work sent back for them.
GATE, DECIDED, RESULT = "gate", "decided", "result"
KINDS = (ACK, REPLY, STATUS, FOLLOW_UP, LINK, CLOCKWORK, GATE, DECIDED, RESULT)
#: What a case may send through `send`.
CASE_KINDS = (ACK, REPLY, STATUS, FOLLOW_UP, GATE, DECIDED, RESULT)
#: The messages that say where the asks stand: a new one goes only when that changed.
STATED = (REPLY, STATUS, GATE, DECIDED)
#: Anything that answered them: no acknowledgement after one.
ANSWERED = (REPLY, STATUS, FOLLOW_UP, GATE, DECIDED, RESULT)

#: What each kind is called on the case page.
KIND_WORDS = {ACK: "Acknowledgement", REPLY: "Reply", STATUS: "Where their requests stand",
              FOLLOW_UP: "Follow-up, at your word", LINK: "Telegram link note",
              CLOCKWORK: "Clockwork item, at its time",
              GATE: "The gate: what started and what waits",
              DECIDED: "The gate: your decisions", RESULT: "The work's result"}


# --- what is never sent ----------------------------------------------------------------------

#: What a message to a contact may never carry, and what each is called.
NEVER: dict[str, str] = {
    "iban": "a bank account number (IBAN)",
    "card": "a payment card number",
    "password": "a password",
    "code": "a one-time or verification code",
}

_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?"
                   r"(?![A-Za-z0-9])")
_CARD = re.compile(r"(?<![\d.,])\d(?:[ -]?\d){12,18}(?![\d])")
_PASSWORD = re.compile(
    r"(?:\bpass(?:word|code|phrase)|\bpwd|\bparola|парола(?:та)?)\s*(?:is|was|:|=|-|е)\s*"
    r"[\"'“]?[^\s\"'”]{4,}", re.IGNORECASE)
_CODE = re.compile(
    r"(?:\b(?:verification|one[-\s]time|otp|2fa|security|login|sign[-\s]?in|access|"
    r"confirmation|auth\w*|reset|backup)\s+code\s*(?:is|:|=|-)?"
    r"|(?:\bcode|\botp|\bpin|код(?:ът)?)\s*(?:is|:|=|е))\s*"
    r"(?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{3,9}(?![\w])", re.IGNORECASE)


def _iban_ok(raw: str) -> bool:
    text = raw.replace(" ", "")
    if not 15 <= len(text) <= 34:
        return False
    moved = text[4:] + text[:4]
    try:
        digits = "".join(str(int(c, 36)) for c in moved)
    except ValueError:
        return False
    return int(digits) % 97 == 1


def _luhn_ok(raw: str) -> bool:
    digits = [int(c) for c in raw if c.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    for n, d in enumerate(reversed(digits)):
        if n % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def secrets_in(text: str, theirs: str = "") -> list[str]:
    """What in a message may never be sent: each as "a payment card number: 4111 ...", or [].

    Checked by what the characters are - an IBAN by its own sum, a card by Luhn, a password or a
    code written out - never by what the message talks about. What the contact wrote themselves
    (`theirs`) is theirs to be told back.
    """
    text = str(text or "")
    mine = " ".join(str(theirs or "").split())
    out: list[str] = []
    for net, pattern, ok in (("iban", _IBAN, _iban_ok), ("card", _CARD, _luhn_ok),
                             ("password", _PASSWORD, None), ("code", _CODE, None)):
        for m in pattern.finditer(text):
            found = " ".join(m.group(0).split())
            if (ok is None or ok(m.group(0))) and found not in mine:
                said = f"{NEVER[net]}: {found}"
                if said not in out:
                    out.append(said)
    return out[:8]


# --- the channels a case answers on ----------------------------------------------------------


def channels(case, contact, *, by_email: str = "") -> list[dict]:
    """Where a message about this case goes, one entry per channel: its own, each other channel
    the same request came on, and the contact's own address when they asked by email.

    Each is {"channel", "to", "thread", "reply_to", "subject", "chat"}. A Telegram account that is
    no longer linked to them, or an address that is not theirs, is left out.
    """
    from . import telegram_guests as tgg

    email = case.email or {}
    out: list[dict] = []

    def add(one: dict) -> None:
        if not any(o["channel"] == one["channel"] for o in out):
            out.append(one)

    def telegram_to(chat: str) -> None:
        if chat and contact is not None and contact.recognises(tgg.sender_of(chat)):
            add({"channel": "telegram", "to": tgg.sender_of(chat), "chat": chat, "thread": "",
                 "reply_to": "", "subject": ""})

    if tgg.on_telegram(case):
        telegram_to(str(email.get("telegram_id") or ""))
    elif str(email.get("channel") or "") == "slack":
        # Where it was asked: the conversation, and the thread, as Rouh's bot (`rouh/slack.py`).
        if email.get("slack_channel") and contact is not None and \
                (contact.implicit or contact.recognises(case.sender)):
            add({"channel": "slack", "to": case.sender, "chat": str(email["slack_channel"]),
                 "slack_thread": str(email.get("slack_thread") or ""), "thread": "", "reply_to": "",
                 "subject": "", "where": str(email.get("slack_where") or "")})
    else:
        add({"channel": "email", "to": case.sender, "thread": case.thread_id,
             "reply_to": case.message_id, "subject": "", "chat": ""})
    for one in case.arrivals or []:
        if not isinstance(one, dict):
            continue
        if one.get("channel") == "telegram":
            telegram_to(str(one.get("telegram_id") or ""))
        elif one.get("message_id") and contact is not None and \
                str(one.get("sender") or "") in (contact.addresses or []):
            add({"channel": "email", "to": str(one.get("sender")), "thread": "",
                 "reply_to": str(one["message_id"]), "subject": "", "chat": ""})
    if by_email:
        add({"channel": "email", "to": by_email, "thread": "", "reply_to": "",
             "subject": str((case.assessment or {}).get("assess", {}).get("reply_subject") or "")
             or "Your message to Rouh on Telegram", "chat": ""})
    return out


# --- the rows ----------------------------------------------------------------------------------


def _model():
    from .models import MailOutbox

    return MailOutbox


def rows(user_id: str, org_id: str, case_id: int) -> list:
    """Every message of a case, oldest first."""
    return list(_model().objects.filter(user_id=str(user_id), org_id=str(org_id),
                                        case_id=case_id).order_by("claimed_at", "id"))


def went(user_id: str, org_id: str, case_id: int, *kinds: str) -> list:
    """The messages of a case that went (or may have), of these kinds."""
    found = _model().objects.filter(user_id=str(user_id), org_id=str(org_id), case_id=case_id,
                                    state__in=("sent", "unknown"))
    if kinds:
        found = found.filter(kind__in=kinds)
    return list(found.order_by("claimed_at", "id"))


def _claim(user_id: str, org_id: str, case_id, *, key: str, attempt: int, kind: str,
           channel: str, to: str, text: str, files: list, said: list,
           thread_before: list | None = None) -> object | None:
    """The row for this message, made now: None when its key was claimed before."""
    from django.db import IntegrityError, transaction

    try:
        with transaction.atomic():
            return _model().objects.create(
                user_id=str(user_id), org_id=str(org_id), case_id=case_id, key=key[:300],
                attempt=attempt, kind=kind, channel=channel, to=to[:300], text=text,
                files=list(files or []), ledger=said, state="claimed",
                thread_before=list(thread_before or []), claimed_at=time.time())
    except IntegrityError:
        return None


def _mark(row, **fields) -> None:
    _model().objects.filter(id=row.id).update(**fields)


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


# --- sending ------------------------------------------------------------------------------------


class Sent:
    """What became of one message on one channel."""

    def __init__(self, channel: str, to: str, *, state: str, message_id: str = "",
                 error: str = "", key: str = "", before: bool = False, logged: bool = False) -> None:
        self.channel, self.to, self.state = channel, to, state
        self.message_id, self.error, self.key = message_id, error, key
        #: Already in the sent log, written by what posted it (`slack.post_message`).
        self.logged = logged
        #: What became of a message claimed earlier, found again: not sent now, so never
        #: written down again.
        self.before = before

    @property
    def ok(self) -> bool:
        return self.state == "sent"

    def __repr__(self) -> str:
        return f"Sent({self.channel}, {self.state}, {self.message_id or self.error})"


async def send(desk, who, case, *, kind: str, text: str, asks: list | None = None,
               files: list | None = None, contact=None, by_email: str = "",
               started_by_owner: bool = False) -> list[Sent]:
    """One message about a case, to every channel it answers on, each once. Never raises.

    `asks` is the ledger as the message says it (its status part, D4), kept on the row, so
    the next reply can tell whether anything changed. `started_by_owner`: the attempt began with
    the owner's own words, so a reply goes even when the ledger stands as it did.
    """
    if kind not in CASE_KINDS:
        raise ValueError(f"not a case message: {kind}")
    text = str(text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    text = await asyncio.to_thread(owner.say, text, who)
    said = ledger.said_state(asks or [])
    theirs = (case.email or {}).get("body") or ""
    held = secrets_in(text, theirs)
    out: list[Sent] = []
    every = await asyncio.to_thread(rows, who.user_id, who.org_id, case.id)
    answered = [r for r in every if r.kind in ANSWERED and r.state in ("sent", "unknown")]
    for ch in channels(case, contact, by_email=by_email):
        if kind == ACK:
            key = f"{case.id}:ack:{ch['channel']}"
            if answered:
                out.append(Sent(ch["channel"], ch["to"], state="refused", key=key,
                                error="An answer already went, so no acknowledgement does."))
                continue
            if any(r.kind == ACK and r.channel == ch["channel"] and
                   r.state in ("sent", "unknown") for r in every):
                out.append(Sent(ch["channel"], ch["to"], state="refused", key=key,
                                error="They were told it is in hand already."))
                continue
        elif kind in (FOLLOW_UP, RESULT):
            key = f"{case.id}:{kind}:{hashlib.sha256(_norm(text).encode()).hexdigest()[:16]}" \
                  f":{ch['channel']}"
        else:
            # The gate's messages are keyed on what they say of the asks too: a raised ask or
            # a second batch of decisions in the same attempt is a message of its own.
            key = f"{case.id}:{case.attempt_no}:{kind}:{ch['channel']}" + (
                f":{ledger.signature(asks or [])}" if kind in (GATE, DECIDED) else "")
            before = [r for r in answered if r.channel == ch["channel"] and r.kind in STATED]
            last = before[-1] if before else None
            if last is not None and _norm(last.text) == _norm(text):
                out.append(Sent(ch["channel"], ch["to"], state="refused", key=key,
                                error="The very same words already went."))
                continue
            if last is not None and ledger.said_of(last.ledger) == said and said \
                    and not started_by_owner:
                out.append(Sent(ch["channel"], ch["to"], state="refused", key=key,
                                error="Nothing changed since the last message that went, so "
                                      "nothing more goes."))
                continue
        if held:
            row = await asyncio.to_thread(
                _claim, who.user_id, who.org_id, case.id, key=key, attempt=case.attempt_no,
                kind=kind, channel=ch["channel"], to=ch["to"], text=text, files=files or [],
                said=said)
            why = "It holds what is never sent: " + "; ".join(held) + "."
            if row is not None:
                await asyncio.to_thread(_mark, row, state="refused", error=why)
            out.append(Sent(ch["channel"], ch["to"], state="refused", error=why, key=key))
            continue
        out.append(await _one(desk, who, case, ch, kind=kind, key=key, text=text,
                              files=files or [], said=said))
    await _recorded(desk, who, case, out, kind=kind, text=text, said=said)
    return out


async def _recorded(desk, who, case, out: list, *, kind: str, text: str, said: list) -> None:
    """Every message that went, or tried to, in the sent log and on the case's trace; a message
    found from an earlier claim is not written down again."""
    from . import sentlog

    for one in out:
        if one.before:
            continue
        if one.state in ("sent", "failed", "unknown") and not one.logged:
            await asyncio.to_thread(
                sentlog.record, channel=one.channel, to=one.to, text=text,
                message_id=one.message_id, case_key=case.key, kind=kind, parts=None,
                user_id=who.user_id, org_id=who.org_id, ok=one.ok, error=one.error)
        await asyncio.to_thread(
            desk.store.trace, who.user_id, who.org_id, case.id, "sent", mode=kind,
            attempt=case.attempts, channel=one.channel, to=one.to, to_name=case.sender_name,
            text=text, message_id=one.message_id, ok=one.ok, state=one.state,
            error=one.error, key=one.key, ledger=said, log=sentlog.path())


def item_channel(row, case, contact) -> dict:
    """Where a contact's Clockwork item goes to them: their own email, as an email of its own,
    or the Telegram account linked to them. ValueError when they have neither that way."""
    from . import telegram_guests as tgg

    wanted = str(getattr(row, "channel", "") or "")
    if not wanted:
        wanted = "telegram" if case is not None and tgg.on_telegram(case) else "email"
    title = " ".join(str(getattr(row, "title", "") or "").split())[:120]
    if wanted == "telegram":
        linked = [t for t in (contact.telegram or []) if str(t).startswith(tgg.SENDER)]
        if not linked:
            raise ValueError(f"{contact.name} has no Telegram account linked, so it cannot go "
                             "there.")
        chat = str(linked[0])[len(tgg.SENDER):]
        return {"channel": "telegram", "to": linked[0], "chat": chat, "thread": "",
                "reply_to": "", "subject": ""}
    sender = str(getattr(case, "sender", "") or "") if case is not None else ""
    to = sender if sender in (contact.addresses or []) else \
        (contact.addresses[0] if contact.addresses else "")
    if not to:
        raise ValueError(f"{contact.name} has no email address on your Trusted contacts.")
    return {"channel": "email", "to": to, "chat": "", "thread": "", "reply_to": "",
            "subject": title or "A reminder from Rouh"}


async def send_item(desk, who, case, row, contact, *, text: str, due_at: float) -> Sent:
    """A contact's Clockwork item, due now, to them (Petar, 12 October 2026: what goes to the
    contact goes through the one outbox). Once per item and time it was due; never what may not
    be sent (`secrets_in`). Whether they may have it at all is the caller's
    (`clockwork_grants.refusal`)."""
    text = str(text or "").replace("\r\n", "\n").strip()
    if not text:
        return Sent("", "", state="refused", error="It has no words for them.")
    text = await asyncio.to_thread(owner.say, text, who)
    try:
        ch = item_channel(row, case, contact)
    except ValueError as exc:
        return Sent("", "", state="refused", error=str(exc))
    key = f"{case.id}:{CLOCKWORK}:{row.id}:{int(due_at or 0)}"
    held = secrets_in(text)
    if held:
        why = "It holds what is never sent: " + "; ".join(held) + "."
        claimed = await asyncio.to_thread(
            _claim, who.user_id, who.org_id, case.id, key=key, attempt=case.attempt_no,
            kind=CLOCKWORK, channel=ch["channel"], to=ch["to"], text=text, files=[], said=[])
        if claimed is not None:
            await asyncio.to_thread(_mark, claimed, state="refused", error=why)
        one = Sent(ch["channel"], ch["to"], state="refused", error=why, key=key)
    else:
        try:
            one = await _one(desk, who, case, ch, kind=CLOCKWORK, key=key, text=text, files=[],
                             said=[])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - not set up here: said on the row, never raised
            log.warning("a Clockwork item of case %s could not be sent: %s", case.id, exc)
            one = Sent(ch["channel"], ch["to"], state="failed", key=key,
                       error=f"{'Gmail' if ch['channel'] == 'email' else 'Telegram'} could not "
                             f"be used here: {exc}")
    await _recorded(desk, who, case, [one], kind=CLOCKWORK, text=text, said=[])
    return one


async def _one(desk, who, case, ch: dict, *, kind: str, key: str, text: str, files: list,
               said: list) -> Sent:
    """One message on one channel: claimed, sent, and marked."""
    from . import case_files
    from . import telegram as tg
    from .google_api import GoogleSaidNo

    if ch["channel"] == "slack":
        return await _slack(who, case, ch, kind=kind, key=key, text=text, said=said)
    if ch["channel"] == "telegram":
        row = await asyncio.to_thread(
            _claim, who.user_id, who.org_id, case.id, key=key, attempt=case.attempt_no,
            kind=kind, channel="telegram", to=ch["to"], text=text, files=[], said=said)
        if row is None:
            return await _again(who, key, ch)
        try:
            parts = await desk.alerts.telegram.send_parts(text, remember=False,
                                                          chat=int(ch["chat"]))
        except (tg.NotSetUp, tg.NotSent, ValueError) as exc:
            await asyncio.to_thread(_mark, row, state="failed", error=str(exc)[:600])
            return Sent("telegram", ch["to"], state="failed", error=f"Telegram would not send "
                                                                      f"it: {exc}", key=key)
        sent_id = f"telegram:{ch['chat']}:{parts[-1] if parts else 0}"
        await asyncio.to_thread(_mark, row, state="sent", message_id=sent_id, sent_at=time.time())
        return Sent("telegram", ch["to"], state="sent", message_id=sent_id, key=key)
    gmail = desk.alerts._clients.for_user(who).gmail
    before: list = []
    if ch.get("thread"):
        try:
            before = list(await gmail.thread_sent(ch["thread"]) or [])
        except Exception as exc:  # noqa: BLE001 - not knowing what went before stops it here
            return Sent("email", ch["to"], state="failed", key=key,
                        error=f"Gmail could not read the thread first: {exc}")
    row = await asyncio.to_thread(
        _claim, who.user_id, who.org_id, case.id, key=key, attempt=case.attempt_no, kind=kind,
        channel="email", to=ch["to"], text=text, files=files, said=said, thread_before=before)
    if row is None:
        return await _again(who, key, ch, gmail=gmail)
    try:
        carried = await asyncio.to_thread(case_files.read_for_send, files, case.key) \
            if files else None
        wrote = await gmail.send(ch["to"], ch.get("subject") or "", text,
                                 reply_to_message_id=ch.get("reply_to") or None,
                                 attachments=carried or None)
    except (case_files.Changed, case_files.Refused) as exc:
        await asyncio.to_thread(_mark, row, state="failed", error=str(exc)[:600])
        return Sent("email", ch["to"], state="failed", error=str(exc), key=key)
    except GoogleSaidNo as exc:
        await asyncio.to_thread(_mark, row, state="failed", error=str(exc)[:600])
        return Sent("email", ch["to"], state="failed", error=f"Gmail would not send it: {exc}",
                    key=key)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - claimed and maybe gone: the thread says, later
        await asyncio.to_thread(_mark, row, state="unknown", error=str(exc)[:600])
        return Sent("email", ch["to"], state="unknown", error=str(exc), key=key)
    sent_id = str((wrote or {}).get("id") or "") if isinstance(wrote, dict) else ""
    await asyncio.to_thread(_mark, row, state="sent", message_id=sent_id, sent_at=time.time())
    return Sent("email", ch["to"], state="sent", message_id=sent_id, key=key)


async def _slack(who, case, ch: dict, *, kind: str, key: str, text: str, said: list) -> Sent:
    """One message about a case posted in Slack as Rouh's bot, where it was asked: claimed, posted
    and marked. The sent log has it from `slack.post_message`, so `_recorded` does not write it
    again."""
    from . import slack

    row = await asyncio.to_thread(
        _claim, who.user_id, who.org_id, case.id, key=key, attempt=case.attempt_no, kind=kind,
        channel="slack", to=ch["to"], text=text, files=[], said=said)
    if row is None:
        return await _again(who, key, ch)
    conn = await asyncio.to_thread(slack.connection, who.org_id)
    if conn is None:
        await asyncio.to_thread(_mark, row, state="failed", error="Slack is not connected.")
        return Sent("slack", ch["to"], state="failed", error="Slack is not connected.", key=key)
    try:
        got = await asyncio.to_thread(
            slack.post_message, conn, channel=ch["chat"], text=text, thread_ts=ch.get("slack_thread") or "",
            kind=kind, case_key=case.key, to_said=f"{case.sender_name} <{ch['to']}> in {ch.get('where') or 'Slack'}")
    except (slack.SlackError, slack.NotSetUp, ValueError) as exc:
        await asyncio.to_thread(_mark, row, state="failed", error=str(exc)[:600])
        return Sent("slack", ch["to"], state="failed", error=f"Slack would not post it: {exc}", key=key,
                    logged=isinstance(exc, slack.SlackError))
    sent_id = f"slack:{got['channel']}:{got['ts']}"
    await asyncio.to_thread(_mark, row, state="sent", message_id=sent_id, sent_at=time.time())
    return Sent("slack", ch["to"], state="sent", message_id=sent_id, key=key, logged=True)


async def slack_not_set_up(who, conn, *, channel: str, thread: str, to: str, to_said: str,
                           text: str) -> Sent:
    """The one answer somebody the owner has not set up gets when they write to Rouh on Slack
    (`rouh/slack_team.py`), posted as Rouh's bot where they asked. There is no case behind it, so
    it is not a row here; the sent log has it from `slack.post_message`, and the message it answers
    is handed over once (`SlackMessage.handed`), so it goes once. Never raises."""
    from . import slack

    text = await asyncio.to_thread(owner.say, text, who)
    held = secrets_in(text)
    if held:
        return Sent("slack", to, state="refused", error="It holds what is never sent: " + "; ".join(held) + ".")
    try:
        got = await asyncio.to_thread(slack.post_message, conn, channel=channel, text=text, thread_ts=thread,
                                      kind="not_set_up", to_said=to_said)
    except (slack.SlackError, slack.NotSetUp, ValueError) as exc:
        return Sent("slack", to, state="failed", error=f"Slack would not post it: {exc}",
                    logged=isinstance(exc, slack.SlackError))
    return Sent("slack", to, state="sent", message_id=f"slack:{got['channel']}:{got['ts']}", logged=True)


async def _again(who, key: str, ch: dict, *, gmail=None) -> Sent:
    """A key claimed before: what became of that message. A claim never marked - a restart in
    the middle of sending - is looked for in the email thread; on Telegram, which keeps nothing
    to look in, it is said as unknown and never sent again."""
    row = await asyncio.to_thread(lambda: _model().objects.filter(
        user_id=str(who.user_id), org_id=str(who.org_id), key=key[:300]).first())
    if row is None:
        return Sent(ch["channel"], ch["to"], state="failed", key=key, error="lost its claim")
    if row.state == "claimed" and gmail is not None and ch.get("thread") and \
            time.time() - row.claimed_at > 120:
        try:
            now = list(await gmail.thread_sent(ch["thread"]) or [])
        except Exception:  # noqa: BLE001 - not known, so not sent again
            now = []
        new = [m for m in now if m not in (row.thread_before or [])]
        if new:
            await asyncio.to_thread(_mark, row, state="sent", message_id=new[-1],
                                    sent_at=time.time(), error="found in the thread after a "
                                                               "restart")
            return Sent(row.channel, row.to, state="sent", message_id=new[-1], key=key)
    if row.state == "claimed" and time.time() - row.claimed_at > 120:
        await asyncio.to_thread(_mark, row, state="unknown",
                                error="A restart came while it was being sent; it may or may "
                                      "not have gone, so it is not sent again.")
        return Sent(row.channel, row.to, state="unknown", key=key,
                    error="it may or may not have gone before a restart")
    return Sent(row.channel, row.to, state=("refused" if row.state == "claimed" else row.state),
                message_id=row.message_id, error=row.error or "It went already.", key=key,
                before=True)


async def link_note(telegram, user_id: str, org_id: str, tg_user_id: str, text: str, *,
                    why: str) -> bool:
    """A note to a Telegram account about linking it to a trusted contact, which has no case
    yet (`rouh/telegram_guests.py`): the code's own words, written down like every other
    message. True when it went."""
    from . import sentlog
    from . import telegram as tg

    key = f"link:{tg_user_id}:{why}:{secrets.token_hex(4)}"
    text = await asyncio.to_thread(owner.say, text, user_id)
    row = await asyncio.to_thread(
        _claim, user_id, org_id, None, key=key, attempt=0, kind=LINK, channel="telegram",
        to=f"telegram:{tg_user_id}", text=text, files=[], said=[])
    ok, error, sent_id = True, "", ""
    try:
        parts = await telegram.send_parts(text, remember=False, chat=int(tg_user_id))
        sent_id = f"telegram:{tg_user_id}:{parts[-1] if parts else 0}"
    except (tg.NotSetUp, tg.NotSent, ValueError) as exc:
        ok, error = False, str(exc)
    if row is not None:
        await asyncio.to_thread(_mark, row, state="sent" if ok else "failed", error=error[:600],
                                message_id=sent_id, sent_at=time.time() if ok else 0)
    await asyncio.to_thread(sentlog.record, channel="telegram", to=f"telegram:{tg_user_id}",
                            text=text, message_id=sent_id, case_key="", kind="guest_answer",
                            parts=None, user_id=user_id, org_id=org_id, ok=ok, error=error)
    return ok


def last_said(user_id: str, org_id: str, case_id: int) -> list:
    """The ledger as the last message that told them where their asks stand said it, on any
    channel, or [] when none went: what a batch of the owner's decisions is told against (D18)."""
    found = [r for r in went(user_id, org_id, case_id, *STATED) if r.ledger]
    return ledger.said_of(found[-1].ledger) if found else []


def views(user_id: str, org_id: str, case_id: int) -> list[dict]:
    """A case's messages for its page: what went, to whom, when, and what it said."""
    out = []
    for r in rows(user_id, org_id, case_id):
        out.append({"kind": r.kind, "kind_said": KIND_WORDS.get(r.kind, r.kind),
                    "channel": r.channel, "to": r.to, "text": r.text, "state": r.state,
                    "message_id": r.message_id, "error": r.error, "attempt": r.attempt,
                    "at": r.sent_at or r.claimed_at, "files": list(r.files or [])})
    return out


__all__ = ["ACK", "ANSWERED", "CASE_KINDS", "CLOCKWORK", "DECIDED", "FOLLOW_UP", "GATE", "KINDS",
           "KIND_WORDS", "LINK", "NEVER", "REPLY", "RESULT", "STATED", "STATUS", "Sent",
           "channels", "item_channel", "last_said", "link_note", "rows", "secrets_in", "send",
           "send_item", "views", "went"]
