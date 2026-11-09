"""Away, after Rouh wrote: an out-of-office reply to Rouh's email is told to the person, with when
they are back and whom they say to write to instead.

Built by the nightly feature run, night 38 of the ledger (9 November 2026, task 94).
Rouh sends mail for ‹owner› from its own inbox: an answer, an introduction, a document asked for.
When the person it wrote to is away, their mail program answers at once ("I am out of the office
until Monday 16 November; for anything urgent write to Owen"), and that answer lands in Rouh's inbox,
which ‹he› never reads, and where Rouh passes over every automatic message as junk
(`mail_alerts.junk_because`). So ‹he› believed it had been read, waited a week for an answer, and
never learnt there was a colleague to write to. Away, said their automatic reply (`away_replies`)
reads such a reply before Rouh writes again; nothing said it when it came.

So, while its switch is on, when an automatic reply that says somebody is away arrives in Rouh's
inbox (`seen`, from `mail_alerts`, before it is passed over as junk), it is read in plain rules, no
model: who it is from, which email of Rouh's it answers (the conversation Did not arrive keeps,
`not_arrived.kept`), the words that say until when (`back_when`) and any other address it names
(`instead`). A notice says it at once (`rouh/notices.py`): who is away, until when in their own
words, whom they name, and which email it was, with Open the chat it was sent from (or the
conversation in Gmail). Left alone, it goes to the phone, as every notice does. The same person's
reply is told once a day at most, so ten emails to one person away make one notice.

An automatic reply that does not say anybody is away ("we received your ticket") says nothing.

**Whose.** Rouh's own connected inbox and the person it belongs to, by `org_id` and `user_id`.

**Its switch** is `away_after` (`rouh/switches.py`): off, the reply stays junk and nothing is told.
"""
from __future__ import annotations

import email.utils
import hashlib
import logging
import re
import time

log = logging.getLogger("rouh.away_after")

SWITCH = "away_after"
TITLE = ("Away, after Rouh wrote: an out-of-office reply to Rouh's email is told to you, with when they "
         "are back and whom to write to")

OPENS = "away_after_opens"
#: The same person's reply is told once in this many hours.
HOURS = 20

#: The words that say until when, in the reply's own words: "until Monday 16 November", "back on the
#: 16th", "returning 2026-11-16", "до 16 ноември", "bis zum 16.11.".
_UNTIL = re.compile(
    r"\b(?:until|till|through|thru|back (?:in the office |at my desk |at work )?(?:on|from|by)?|return(?:ing)?"
    r"(?: to the office)?(?: on)?|returns?(?: on)?|away from)\s+((?:the\s+)?[^.\n;!?()]{3,60})"
    r"|\b(?:до|след)\s+([^.\n;!?()]{3,40})"
    r"|\b(?:bis(?: zum| einschließlich)?|zurück am|jusqu'au|hasta el|fino al)\s+([^.\n;!?()]{3,40})", re.I)
_ADDRESS = re.compile(r"[\w.+'-]+@[\w-]+(?:\.[\w-]+)+")
#: The words before an address in "please contact Owen Marsh (owen@...)" that are a name.
_NAME_BEFORE = re.compile(r"((?:[A-ZА-Я][\w'-]+\s){1,3})\s*[(<]?\s*$")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def address_of(header: str) -> str:
    return (email.utils.parseaddr(header or "")[1] or "").strip().lower()


def is_away_reply(message: dict) -> bool:
    """An automatic reply from a person's mailbox that says they are away."""
    from . import away_replies, ghosts

    named = {"auto-submitted": message.get("auto_submitted") or "",
             "precedence": message.get("precedence") or "",
             "subject": message.get("subject") or ""}
    if not ghosts.is_auto_reply(named):
        return False
    sender = address_of(message.get("from", ""))
    if not sender or ghosts.is_machine(sender):
        return False
    return away_replies.is_away(message.get("subject") or "", message.get("body") or "")


def _plain(text: str) -> str:
    return " ".join(str(text or "").split())


def back_when(body: str) -> str:
    """Their own words for until when they are away, or "" when the reply does not say."""
    text = _plain(body)[:1500]
    for found in _UNTIL.finditer(text):
        words = next((g for g in found.groups() if g), "").strip(" ,:-")
        # A date has a number in it, or a weekday or a month name.
        if re.search(r"\d|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april"
                     r"|may|june|july|august|september|october|november|december|понеделник|вторник|сряда"
                     r"|четвъртък|петък|януари|февруари|март|април|май|юни|юли|август|септември|октомври"
                     r"|ноември|декември", words, re.I):
            whole = text[found.start():found.end()].strip(" ,:-")
            # "until Monday 16 November with limited access to email": only the part that says when.
            whole = re.split(r"\s(?:with|and|but|so|for|during|when|while|и|с)\s", whole, maxsplit=1)[0]
            return whole.strip(" ,:-")[:90]
    return ""


def instead(body: str, *, sender: str, own: list[str]) -> list[str]:
    """The other people the reply names to write to, as 'Name <address>' or an address, at most two."""
    mine = {str(a or "").lower() for a in own if a} | {sender.lower()}
    text = _plain(body)[:2000]
    out: list[str] = []
    for found in _ADDRESS.finditer(text):
        address = found.group(0).strip(".").lower()
        if address in mine or any(address == o.split("<")[-1].rstrip(">") for o in out):
            continue
        # "write to Mira Sol at mira.sol@...": the words before the address, "at" and brackets aside.
        lead = re.sub(r"\s+(?:at|on|via|-|:)\s*$", " ", text[max(0, found.start() - 40):found.start()])
        before = _NAME_BEFORE.search(lead)
        name = (before.group(1).strip() if before else "")
        if name.lower() in ("please contact", "contact", "please", "email", "write to"):
            name = ""
        out.append(f"{name} <{address}>" if name else address)
        if len(out) == 2:
            break
    return out


def key_of(message_id: str) -> str:
    return "aa-" + hashlib.sha256(str(message_id).encode()).hexdigest()[:16]


def _setting(who, name: str) -> dict:
    import json

    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=name)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _put(who, name: str, held: dict) -> None:
    import json

    from .models import UserSetting

    user_id, org_id = _ids(who)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=name, value=json.dumps(held),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def remember(who, key: str, where: dict) -> None:
    """Where Open goes for this notice, and when this sender was last told, by the notice's key."""
    held = _setting(who, OPENS)
    held[key] = dict(where, at=time.time())
    if len(held) > 100:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-100:])
    _put(who, OPENS, held)


def told_lately(who, sender: str, now: float | None = None) -> bool:
    now = now or time.time()
    return any(one.get("sender") == sender and now - float(one.get("at") or 0) < HOURS * 3600
               for one in _setting(who, OPENS).values() if isinstance(one, dict))


def opens(who, key: str) -> dict | None:
    one = _setting(who, OPENS).get(key)
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


def what_was_sent(who, message: dict, sender: str) -> dict:
    """The email of Rouh's this reply answers, as Did not arrive kept it: {subject, chat, at} or {}."""
    from . import not_arrived

    try:
        held = not_arrived.kept(who)
    except Exception:  # noqa: BLE001 - told all the same, without the chat
        return {}
    thread = str(message.get("thread_id") or "")
    if thread in held:
        return held[thread]
    for one in sorted(held.values(), key=lambda v: v.get("at") or 0, reverse=True):
        if sender in str(one.get("to") or "").lower():
            return one
    return {}


async def seen(who, message: dict, *, mailbox: str = "", own: list[str] = ()) -> str:
    """An away reply in Rouh's inbox told to the person: the sentence for the mail log, or "" when it is
    not one, or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution, notices

    if not is_away_reply(message) or not await asyncio.to_thread(on, who):
        return ""
    sender = address_of(message.get("from", ""))
    name = (email.utils.parseaddr(message.get("from", ""))[0] or "").strip() or sender
    if await sync_to_async(told_lately)(who, sender):
        return f"An automatic reply from {sender} saying they are away: told already today, not told again."
    sent = await sync_to_async(what_was_sent)(who, message, sender)
    body = message.get("body") or ""
    until = back_when(body)
    others = instead(body, sender=sender, own=list(own) + [mailbox])
    about = f"“{sent['subject']}”" if sent.get("subject") else "Rouh's email"
    when = ""
    if sent.get("at"):
        from datetime import datetime

        when = datetime.fromtimestamp(float(sent["at"]), clock.zone_of(who)).strftime(", sent %A %-d %B at %H:%M,")
    # What matters first, as a notice shows its first lines: until when, and whom to write to instead.
    if until and re.match(r"(?:until|till|through|thru|до|bis)\b", until, re.I):
        text = f"{name} is away {until}."
    elif until:
        text = f"{name} is away; their reply says “{until}”."
    else:
        text = f"{name} is away, and their reply gives no date."
    if others:
        text += f" For anything urgent: {' or '.join(others)}."
    text += f" It was their automatic reply to {about}{when.rstrip(',')}."
    key = key_of(message.get("id") or "")
    label = "Open the chat it was sent from" if sent.get("chat") else "Open it in Gmail"
    link = f"/mail/away-after/{key}"
    title = f"Away: {name}, who Rouh wrote to"
    said = await notices.notify(
        title=title, body=text, link=link, link_label=label,
        links=[{"label": label, "href": link}], kind="mail", key=key, who=who,
        phone_text=f"{title}. {text}")
    if said is None:
        return f"An automatic reply from {sender} saying they are away: told before, not told again."
    await sync_to_async(remember)(who, key, {
        "chat": sent.get("chat") or "", "thread": str(message.get("thread_id") or ""), "mailbox": mailbox,
        "sender": sender})
    await sync_to_async(evolution.used)(SWITCH, "told", who=who,
                                        detail=f"{sender}, {'until said' if until else 'no date'}"[:200])
    return f"An automatic reply: {name} is away{(' (' + until + ')') if until else ''}. You were told in a notice."


__all__ = ["OPENS", "SWITCH", "TITLE", "back_when", "instead", "is_away_reply", "on", "opens", "seen",
           "where_to"]
