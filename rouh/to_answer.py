"""Waiting on your answer: asked in words, the emails from people that the person has not answered.

Built by the nightly feature run, night 30 (the ledger's night 34), 5 November 2026 (task 94).
The morning brief's Waiting on others (`rouh/ghosts.py`) lists what the person asked and nobody
answered. The other side had no list: an email from a person, to them, that asked something, read
on a phone between two meetings, and then never answered, with the conversation's last word still
the other person's. Asked "what haven't I answered?", Rouh could only list recent mail: it could not
tell which conversations were still waiting on him without reading every one.

So the tool `to_answer`, while its switch is on, reads every mailbox the person has given Rouh (its
own connection and each read-only one, `ghosts.sources`), the inbox's conversations of the last
`DAYS` days (or as many as asked, at most `MOST_DAYS`), in plain rules and no model:

1. **The last word is somebody else's.** The newest message in the conversation, drafts and
   automatic replies left out, is from a person who is not the mailbox's own addresses.
2. **A person, writing to them.** Not a machine (no-reply, notifications), not a list or bulk mail,
   not a calendar invitation; the person is on its To line, and it went to at most `MOST_PEOPLE`.
3. **Asked something.** What the sender wrote themselves (quotes and signature cut off) has a question
   or a request in it (`ghosts.the_ask`): that sentence is said with it. The others, with no question,
   are named after, shorter.

Each comes with who, when, how long it has waited, its subject, the mailbox, and a link to it in Gmail.

Nothing is kept, changed or sent: it reads with GET alone.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`. Refused in a contact's case.

**Its switch** is `to_answer` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("rouh.to_answer")

SWITCH = "to_answer"
TITLE = "Waiting on your answer: the emails from people you have not answered, each with what they asked"
TOOL_NAME = "to_answer"

DAYS = 14
MOST_DAYS = 45
#: An email newer than this, in hours, is not waiting yet: it has only just come.
FRESH_HOURS = 3
MOST_PEOPLE = 8
#: At most this many conversations are read in each mailbox.
MOST_THREADS = 40
NO_QUESTION_SAID = 8

DESCRIPTION = (
    "The emails from people that the person has not answered: conversations in their inboxes (Rouh's own "
    "and the person's read-only ones) where the last word is somebody else's, a person writing to them, "
    "each with what that person asked, who, when, how long it has waited, and a link. Use it when they ask "
    "what they have not answered, what is waiting on their reply, or whom they owe an answer. "
    "`days` is how far back (14 unless asked), `person` narrows it to one sender's name or address.")
SCHEMA = {
    "type": "object",
    "properties": {
        "days": {"type": "integer", "description": "How many days back to look, 1 to 45. 14 unless asked."},
        "person": {"type": "string", "description": "Only emails from this person: a name or an address."},
    },
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def verdict(thread: dict, own: set[str], now: float) -> dict | None:
    """One conversation: the email waiting on the person's answer, or None."""
    from . import ghosts

    messages = sorted(thread.get("messages") or [], key=ghosts._at)
    last = None
    for message in reversed(messages):
        labels = set(message.get("labelIds") or [])
        if labels & {"DRAFT", "CHAT", "SPAM", "TRASH"}:
            continue
        named = ghosts._named(message)
        if ghosts.is_auto_reply(named):
            continue
        last = message
        break
    if last is None:
        return None
    labels = set(last.get("labelIds") or [])
    named = ghosts._named(last)
    sender = (ghosts.people(named.get("from", "")) or [("", "")])[0]
    if "SENT" in labels or not sender[1] or sender[1] in own or ghosts.is_machine(sender[1]):
        return None
    at = ghosts._at(last)
    if now - at < FRESH_HOURS * 3600:
        return None
    if (named.get("list-id") or named.get("list-unsubscribe")
            or (named.get("precedence") or "").lower() in ("bulk", "list", "junk")):
        return None
    subject = named.get("subject") or ""
    if ghosts._CALENDAR_SUBJECT.match(subject) or ghosts._has_calendar(last.get("payload") or {}):
        return None
    to, cc = ghosts.people(named.get("to", "")), ghosts.people(named.get("cc", ""))
    if len(to) + len(cc) > MOST_PEOPLE or not any(a in own for _n, a in to):
        return None
    text = ghosts._body_text(last)
    return {"thread_id": last.get("threadId") or thread.get("id") or "",
            "subject": subject[:200] or "(no subject)", "name": sender[0][:80], "email": sender[1],
            "at": at, "ask": ghosts.the_ask(text),
            "words": " ".join(ghosts.own_words(text).split())[:160],
            "others": len([1 for _n, a in to + cc if a not in own and a != sender[1]])}


async def scan(reader, *, days: int, person: str = "", now: float | None = None) -> list[dict]:
    """Every conversation in one mailbox's inbox that waits on the person's answer, oldest first."""
    from . import ghosts

    now = now or time.time()
    own = await reader.addresses()
    if not own:
        return []
    query = (f"in:inbox newer_than:{days}d -in:sent -category:promotions -category:social "
             f"-category:updates -category:forums")
    if person:
        query += f" from:({person})"
    found = await reader.search(query, 100)
    threads: list[str] = []
    for one in found:
        tid = one.get("threadId") or one.get("id")
        if tid and tid not in threads:
            threads.append(tid)
    out = []
    for got in await ghosts._gathered([reader.thread(t) for t in threads[:MOST_THREADS]]):
        if isinstance(got, BaseException) or not isinstance(got, dict):
            continue
        item = verdict(got, own, now)
        if item:
            out.append(item)
    out.sort(key=lambda one: one["at"])
    return out


def _waited(at: float, now: float) -> str:
    days = int((now - at) // 86400)
    if days <= 0:
        hours = max(1, int((now - at) // 3600))
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{days} day{'s' if days != 1 else ''}"


def said(found: dict[str, list[dict]], zone, *, days: int, troubles: list[str],
         now: float | None = None) -> str:
    """The answer, mailbox by mailbox: asks first, then the others, shorter."""
    from datetime import datetime

    from . import ghosts

    now = now or time.time()
    total = sum(len(v) for v in found.values())
    lines = [f"Emails from people waiting on your answer, from the last {days} days: {total}"
             + (" (none)." if not total else ".")]
    for mailbox, items in found.items():
        if not items:
            lines.append(f"\nIn {mailbox}: nothing waiting on you.")
            continue
        asks = [one for one in items if one["ask"]]
        rest = [one for one in items if not one["ask"]]
        lines.append(f"\nIn {mailbox}: {len(items)} waiting"
                     + (f", {len(asks)} of them asking you something" if asks else "") + ".")
        for one in asks:
            when = datetime.fromtimestamp(one["at"], zone).strftime("%A %-d %B")
            who = f"{one['name']} <{one['email']}>" if one["name"] else one["email"]
            lines.append(f"- {who}, {when} (waiting {_waited(one['at'], now)}): {one['subject']!r}"
                         + (f", with {one['others']} others on it" if one["others"] else "")
                         + f". They asked: \"{one['ask']}\" Open: {ghosts.link_to(one.get('mailbox') or '', one['thread_id'])}")
        if rest:
            lines.append("  With no question in them, also unanswered:")
            for one in rest[-NO_QUESTION_SAID:]:
                when = datetime.fromtimestamp(one["at"], zone).strftime("%-d %B")
                lines.append(f"  - {one['name'] or one['email']}, {when}: {one['subject']!r}"
                             + (f" (\"{one['words'][:100]}\")" if one["words"] else ""))
    for one in troubles:
        lines.append(f"\nNot read: {one}")
    lines.append("\nIt reads only whether the last message in each conversation is theirs: a reply sent "
                 "from another mailbox, or by phone, is not seen.")
    return "\n".join(lines)


async def answer(who, args: dict, zone) -> tuple[str, int]:
    """(the words for the model, how many emails were found)."""
    from asgiref.sync import sync_to_async

    from . import ghosts, runtime

    try:
        days = max(1, min(MOST_DAYS, int(args.get("days") or DAYS)))
    except (TypeError, ValueError):
        days = DAYS
    person = " ".join(str(args.get("person") or "").replace("(", " ").replace(")", " ").split())[:80]
    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return "No mailbox is connected on this Rouh.", 0
    sources = await sync_to_async(ghosts.sources)(who, auth)
    if not sources:
        return ("No mailbox is connected: connect Google, or a read-only mailbox, in Settings.", 0)
    found: dict[str, list[dict]] = {}
    troubles: list[str] = []
    for source in sources:
        label = source.email + (" (read-only)" if source.read_only else "")
        if source.needs_reconnect:
            troubles.append(f"{source.email} needs connecting again in Settings.")
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
            if reader is None:
                continue
            found[label] = [dict(one, mailbox=source.email)
                            for one in await scan(reader, days=days, person=person)]
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            troubles.append(ghosts._say_trouble(exc, source.email))
    total = sum(len(v) for v in found.values())
    return said(found, zone, days=days, troubles=troubles), total


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "on", "scan", "verdict"]
