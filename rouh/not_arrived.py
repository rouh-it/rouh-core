"""Did not arrive: an email Rouh sent that bounced is told to the person at once.

Built by the nightly feature run, night 30 (the ledger's night 34), 5 November 2026 (task 94).
Rouh sends mail for the person from its own inbox: an answer, an introduction, a document asked for.
When an address is wrong, the mailbox full or the far server refuses it, the far side's mail system
answers with a bounce ("Delivery Status Notification (Failure)", "Undeliverable: ...") from
mailer-daemon or postmaster, into Rouh's inbox, and Rouh skipped it as junk, as it must skip every
machine's mail (`mail_alerts.junk_because`). Nobody saw it: the person believed the email had gone,
and the other side never had it.

So, while its switch is on:

- when Rouh sends an email (`send_mail`, or Send on a draft card), the conversation it is in, the
  chat that sent it, who it went to and its subject are kept (`sent`, the user setting
  `not_arrived_sent`, the newest `KEEP`, for `DAYS` days);
- when a bounce arrives in Rouh's inbox (`seen`, from `mail_alerts`, before it is passed over as
  junk), it is read in plain rules, no model: which address failed (`X-Failed-Recipients`, the
  report's `Final-Recipient`, or the words "wasn't delivered to"), and the reason the far server gave
  (`Diagnostic-Code`, "The response was"), said in plain words where it is a common one;
- a notice says it at once (`rouh/notices.py`): which email, to whom, sent when, and why it did not
  arrive, with Open the chat it was sent from (or the conversation in Gmail when no chat sent it).
  Left alone, it goes to the phone, as every notice does.

A delay ("will retry") is not a failure, and says nothing. A bounce of mail Rouh did not send (not in
a conversation it kept, and not to an address it wrote to) is told too, as it is still mail from
Rouh's inbox that did not arrive.

**Whose.** Rouh's own connected inbox and the person it belongs to, by `org_id` and `user_id`.

**Its switch** is `not_arrived` (`rouh/switches.py`): off, nothing is kept and bounces stay junk.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time

log = logging.getLogger("rouh.not_arrived")

SWITCH = "not_arrived"
TITLE = ("Did not arrive: an email Rouh sent that bounced is told to you at once, with who, why, "
         "and the chat it was sent from")

KEPT = "not_arrived_sent"
#: How many sent conversations are kept, and for how long, in days.
KEEP = 300
DAYS = 30

_MACHINE = re.compile(r"^(?:mailer-daemon|postmaster|mail-?daemon|bounces?)(?:[+._-].*)?@", re.I)
_SUBJECT = re.compile(
    r"delivery status notification|undeliver|delivery (?:has )?failed|delivery failure"
    r"|mail delivery (?:failed|subsystem)|returned mail|failure notice|not delivered|could not be delivered"
    r"|недоставено|не беше доставено|unzustellbar|non remis", re.I)
_DELAY = re.compile(r"\(delay\)|delayed|will (?:keep )?(?:re)?try|has not yet been delivered|temporar", re.I)
_TO = re.compile(r"(?:wasn't|was not|could not be|couldn't be) delivered to\s+<?([^\s<>@]+@[^\s<>,;]+)", re.I)
_FINAL = re.compile(r"^(?:Final|Original)-Recipient:\s*rfc822;\s*<?([^\s<>]+@[^\s<>]+)>?", re.I | re.M)
_DIAG = re.compile(r"^Diagnostic-Code:\s*smtp;\s*(.+(?:\n[ \t]+.+)*)", re.I | re.M)
_RESPONSE = re.compile(r"(?:the response (?:from the remote server )?was|remote server returned)[:\s]*\n?\s*(.+)", re.I)
_SUBJECT_LINE = re.compile(r"^Subject:\s*(.+)$", re.I | re.M)

#: The common reasons, in plain words, by the SMTP code or the words the far server uses.
PLAIN = [
    (re.compile(r"5\.1\.1|user unknown|no such user|address not found|does not exist|recipient .*rejected|"
                r"mailbox unavailable|invalid recipient|unknown recipient", re.I),
     "the address does not exist at that company: it is probably misspelt, or the person has left"),
    (re.compile(r"5\.1\.2|host not found|domain not found|no mx|name or service not known|"
                r"dns error|nxdomain", re.I),
     "the domain after the @ does not receive mail: it is probably misspelt"),
    (re.compile(r"5\.2\.2|mailbox full|quota|over quota|insufficient storage", re.I),
     "their mailbox is full, so it may work later or at another address"),
    (re.compile(r"5\.3\.4|message (?:size|too (?:big|large))|exceeds .*size", re.I),
     "it was too big for their mail server: send the files as a link instead"),
    (re.compile(r"5\.7\.\d|spam|blocked|policy|not authori[sz]ed|access denied|rejected by|blacklist|"
                r"dmarc|spf", re.I),
     "their mail server refused it on its own rules (filtering, or mail only from known senders)"),
]


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=KEPT, value=json.dumps(held),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def sent(who, *, thread_id: str, chat: str, to: str, subject: str, now: float | None = None) -> None:
    """Keep one email Rouh sent, by its conversation, so its bounce can say where it came from."""
    if not thread_id or not on(who):
        return
    now = now or time.time()
    held = {k: v for k, v in kept(who).items() if now - float(v.get("at") or 0) < DAYS * 86400}
    held[str(thread_id)] = {"chat": str(chat or ""), "to": str(to or "")[:500],
                            "subject": str(subject or "")[:300], "at": now}
    if len(held) > KEEP:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-KEEP:])
    _keep(who, held)


def address_of(header: str) -> str:
    return (email.utils.parseaddr(header or "")[1] or "").strip().lower()


def is_bounce(message: dict) -> bool:
    """A failure report from a mail system: from its machine, with a failure's subject or a failed address."""
    sender = address_of(message.get("from", ""))
    if not _MACHINE.match(sender):
        return False
    return bool(_SUBJECT.search(message.get("subject") or "") or message.get("failed_recipients"))


def is_delay(message: dict) -> bool:
    subject = message.get("subject") or ""
    if re.search(r"\(failure\)|undeliverable|failed", subject, re.I):
        return False
    return bool(_DELAY.search(subject) or _DELAY.search((message.get("body") or "")[:600]))


def failed(message: dict) -> list[str]:
    """Every address the report says failed, lower case, once each."""
    out: list[str] = []
    for one in re.split(r"[,\s]+", message.get("failed_recipients") or ""):
        if "@" in one and one.lower() not in out:
            out.append(one.strip("<>").lower())
    body = message.get("body") or ""
    for pattern in (_FINAL, _TO):
        for found in pattern.findall(body + " "):
            found = found.strip("<>.").lower()
            if "@" in found and found not in out and not _MACHINE.match(found):
                out.append(found)
    return out


def reason(message: dict) -> tuple[str, str]:
    """(the far server's own words, the same in plain words or "")."""
    body = message.get("body") or ""
    found = _DIAG.search(body) or _RESPONSE.search(body)
    words = " ".join(found.group(1).split())[:300] if found else ""
    look = words or body[:1500]
    for pattern, plain in PLAIN:
        if pattern.search(look):
            return words, plain
    return words, ""


def what_failed(message: dict, held: dict) -> dict:
    """Everything the notice says, read from the bounce and the email Rouh kept."""
    thread = str(message.get("thread_id") or "")
    mine = held.get(thread) or {}
    addresses = failed(message)
    if not mine and addresses:
        # Not threaded with what Rouh sent: the newest kept email to the failed address.
        for one in sorted(held.values(), key=lambda v: v.get("at") or 0, reverse=True):
            if any(a in (one.get("to") or "").lower() for a in addresses):
                mine = one
                break
    subject = mine.get("subject") or ""
    if not subject:
        line = _SUBJECT_LINE.search(message.get("body") or "")
        subject = line.group(1).strip()[:300] if line else ""
    words, plain = reason(message)
    return {"addresses": addresses, "subject": subject, "chat": mine.get("chat") or "",
            "sent_at": mine.get("at") or 0, "words": words, "plain": plain, "thread": thread}


def key_of(message_id: str) -> str:
    return "na-" + hashlib.sha256(str(message_id).encode()).hexdigest()[:16]


async def seen(who, message: dict, *, mailbox: str = "") -> str:
    """A bounce in Rouh's inbox told to the person: the sentence for the mail log, or "" when it is
    not a bounce, is only a delay, or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution, notices

    if not is_bounce(message) or not await asyncio.to_thread(on, who):
        return ""
    if is_delay(message):
        return "A delivery delay, which says the far server will try again: not told."
    held = await sync_to_async(kept)(who)
    got = what_failed(message, held)
    to = ", ".join(got["addresses"]) or "somebody"
    title = f"Did not arrive: the email to {to}"
    when = ""
    if got["sent_at"]:
        from datetime import datetime

        when = datetime.fromtimestamp(got["sent_at"], clock.zone_of(who)).strftime(" sent %A %-d %B at %H:%M")
    about = f"“{got['subject']}”" if got["subject"] else "The email"
    why = got["plain"] or "their mail server refused it"
    body = f"{about}{when} came back from {to}: {why}."
    if got["words"]:
        body += f" Their server said: {got['words']}"
    link = f"/mail/not-arrived/{key_of(message.get('id') or '')}"
    label = "Open the chat it was sent from" if got["chat"] else "Open it in Gmail"
    said = await notices.notify(
        title=title, body=body, link=link, link_label=label,
        links=[{"label": label, "href": link}], kind="mail",
        key=key_of(message.get("id") or ""), who=who,
        phone_text=f"{title}. {body}")
    if said is None:
        return f"A bounce of an email to {to}: told before, not told again."
    # Where Open goes, kept by the notice's key, so the link needs no message id in it.
    await sync_to_async(_remember_open)(who, key_of(message.get("id") or ""), {
        "chat": got["chat"], "thread": got["thread"], "mailbox": mailbox, "to": to})
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"to {to}"[:200])
    return f"A bounce: the email to {to} did not arrive ({why}). You were told in a notice."


OPENS = "not_arrived_opens"


def _remember_open(who, key: str, where: dict) -> None:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=OPENS)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    held = held if isinstance(held, dict) else {}
    held[key] = dict(where, at=time.time())
    if len(held) > 100:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-100:])
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=OPENS, value=json.dumps(held),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def opens(who, key: str) -> dict | None:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=OPENS)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return None
    one = held.get(key) if isinstance(held, dict) else None
    return one if isinstance(one, dict) else None


def where_to(who, key: str) -> str:
    """Where Open on the notice goes: the chat that sent it, else the conversation in Gmail, else Rouh."""
    from . import ghosts

    one = opens(who, key) or {}
    if one.get("chat"):
        return f"/chat/{one['chat']}"
    if one.get("thread"):
        return ghosts.link_to(one.get("mailbox") or "", one["thread"])
    return "/"


__all__ = ["KEPT", "SWITCH", "TITLE", "failed", "is_bounce", "is_delay", "on", "reason", "seen",
           "sent", "what_failed", "where_to"]
