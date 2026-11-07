"""Away, said their automatic reply: Rouh reads somebody's out-of-office before it writes to them.

Built by the nightly feature run, night 30 (the ledger's night 34), 5 November 2026 (task 94).
When somebody is away, their mail program answers every email with an automatic reply: "I am out of
the office until 14 November; for anything urgent write to Maria". Those replies land in the inbox
of whoever wrote, and every part of Rouh passes over them on purpose: they are not a person writing
(`mail_alerts.junk_because`, `ghosts.is_auto_reply`). So the one thing they say was lost: Rouh drafted
the next email to that person, or booked them into a meeting, as if they were at their desk, and the
person found out from a second automatic reply, or from silence.

So, while its switch is on, when Rouh drafts or sends an email (`draft_mail`, `send_mail`) or books
a meeting with guests (`create_calendar_event`), it looks in every inbox the person has given it
(Rouh's own connection and each read-only mailbox, `ghosts.sources`) for an automatic reply from
each person it is writing to, in the last `DAYS` days, that says they are away, and tells the model
the newest one's date and its words. The model then says it, and does what fits: waits, writes to the
colleague named, or asks the person. A meeting is held before any invitation goes, and nobody is
emailed, until the dates in the reply are read: booked as asked with `even_if_away` when the guest is
back by then, or another time offered.

No model is asked here. Nothing is kept, changed or sent: it only reads, with GET alone.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`, through the same readers the
Waiting on others list uses.

**Its switch** is `away_replies` (`rouh/switches.py`): off, nothing is looked for and nothing said.
"""
from __future__ import annotations

import asyncio
import email.utils
import logging
import re
import time

log = logging.getLogger("rouh.away_replies")

SWITCH = "away_replies"
TITLE = ("Away, said their automatic reply: before Rouh writes to or books with somebody, it reads "
         "their recent out-of-office reply and says when they are back")

#: How far back an automatic reply still says something about today, in days.
DAYS = 21
#: At most this many people are looked up for one email or meeting.
MOST_PEOPLE = 8
#: How long the whole look may take before the email goes without it, in seconds.
SECONDS = 10.0
#: How many of the person's words from the reply are told.
WORDS = 700

#: What an automatic reply that says somebody is away has in it, in English, Bulgarian, German,
#: French, Spanish and Italian. An automatic reply that only says "we received your ticket" says
#: nothing about anybody being away, and is not told.
AWAY = re.compile(
    r"out of (?:the )?office|\booo\b|\baway\b|on (?:annual |parental |sick |maternity |paternity )?leave"
    r"|vacation|holiday|time off|travell?ing|limited access|back (?:on|in|at|from)\b|return(?:ing)? (?:on|to)"
    r"|извън офиса|отпуск|отсъств|няма да съм|ще се върна|abwesend|urlaub|absent|cong[ée]s?"
    r"|fuera de la oficina|vacaciones|fuori ufficio|ferie", re.I)


#: Said to the model beside create_calendar_event's other fields.
FIELD = {"type": "boolean",
         "description": "Book it although a guest's automatic reply said they are away: when the meeting is "
                        "after the date they are back, or the person says so, after being told."}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def people(*lines: str, own=()) -> list[str]:
    """Every address on these To, Cc or guest lines, lower case, once each, the person's own left out."""
    mine = {one.lower() for one in own}
    out: list[str] = []
    for line in lines:
        if isinstance(line, (list, tuple)):
            line = ", ".join(str(x) for x in line)
        for _name, addr in email.utils.getaddresses([str(line or "")]):
            addr = addr.strip().lower()
            if "@" in addr and addr not in mine and addr not in out:
                out.append(addr)
    return out[:MOST_PEOPLE]


def is_away(subject: str, words: str) -> bool:
    return bool(AWAY.search(subject or "") or AWAY.search((words or "")[:2000]))


def _cut(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= WORDS else text[:WORDS - 1].rstrip() + "…"


async def _newest_in(reader, address: str, after: float) -> dict | None:
    """The newest automatic reply from `address` in this mailbox that says they are away."""
    from . import ghosts

    found = await reader.search(f"from:{address} newer_than:{DAYS}d", 6)
    for one in found:
        head = await reader.headers(one["id"])
        named = ghosts._named(head)
        at = ghosts._at(head)
        if at and at < after:
            continue
        sender = ghosts.people(named.get("from", ""))
        if not sender or sender[0][1] != address or not ghosts.is_auto_reply(named):
            continue
        whole = await reader.message(one["id"])
        words = ghosts.own_words(ghosts._body_text(whole)) or ghosts._body_text(whole)
        subject = named.get("subject", "")
        if not is_away(subject, words):
            continue
        return {"address": address, "name": sender[0][0], "subject": subject, "at": at,
                "words": _cut(words)}
    return None


async def find(who, addresses: list[str]) -> list[dict]:
    """For each address, the newest away reply found in any of the person's mailboxes."""
    from asgiref.sync import sync_to_async

    from . import ghosts, runtime

    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None or not addresses:
        return []
    sources = await sync_to_async(ghosts.sources)(who, auth)
    after = time.time() - DAYS * 86400
    best: dict[str, dict] = {}
    for source in sources:
        if source.needs_reconnect:
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("away replies: %s could not be opened: %s", source.email, exc)
            continue
        if reader is None:
            continue
        for address in addresses:
            try:
                got = await _newest_in(reader, address, after)
            except Exception as exc:  # noqa: BLE001
                log.info("away replies: %s in %s could not be read: %s", address, source.email, exc)
                continue
            if got and got["at"] >= (best.get(address) or {}).get("at", 0):
                best[address] = dict(got, inbox=source.email)
    return [best[a] for a in addresses if a in best]


def said(found: list[dict], zone, *, booking: bool = False) -> str:
    """The words told to the model after the tool's own answer, or "" when nobody is away."""
    if not found:
        return ""
    from datetime import datetime

    lines = []
    for one in found:
        when = datetime.fromtimestamp(one["at"], zone).strftime("%A %-d %B") if one.get("at") else "lately"
        who = f"{one['name']} <{one['address']}>" if one.get("name") else one["address"]
        lines.append(f"- {who} sent an automatic reply on {when} (in {one.get('inbox') or 'a mailbox'}), "
                     f"subject {one.get('subject')!r}: \"{one['words']}\"")
    head = ("A guest's automatic reply says they may be away. Read the dates in it against the meeting's: "
            "if they are back by then, book it as asked with even_if_away; if not, tell the person when "
            "they are back and offer a later time, or the colleague it names."
            if booking else
            "Their automatic reply says they may be away. Read the dates in it; if they are still away, "
            "tell the person when they are back and whom it says to write to instead, and offer that.")
    from . import untrusted

    return ("\n\nAway, said their automatic reply (read from the person's own mail). " + head
            + " Their words:\n" + untrusted.wrap("\n".join(lines), untrusted.SOURCES["read_recent_mail"]))


async def note(who, addresses: list[str], zone, *, booking: bool = False) -> str:
    """Everything in one call, never longer than `SECONDS`, never raising: "" when there is nothing."""
    from asgiref.sync import sync_to_async

    from . import evolution

    if not addresses or not await asyncio.to_thread(on, who):
        return ""
    try:
        found = await asyncio.wait_for(find(who, addresses), SECONDS)
    except Exception as exc:  # noqa: BLE001 - the email or the meeting goes on without it
        log.info("away replies: the look did not finish: %s", exc)
        return ""
    text = said(found, zone, booking=booking)
    if not text:
        return ""
    await sync_to_async(evolution.used)(
        SWITCH, "told", who=who,
        detail=("booking: " if booking else "writing: ") + ", ".join(one["address"] for one in found)[:200])
    return text


__all__ = ["AWAY", "DAYS", "FIELD", "SWITCH", "TITLE", "find", "is_away", "note", "on", "people", "said"]
