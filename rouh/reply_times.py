"""Reply times with a company, both ways: asked in words, how quickly ‹he› answers a company's (or a
person's) email, and they ‹his›, counted from the mail itself.

Built by the nightly feature run, night 36 (8 November 2026, task 94), from INC-513. Before a client
review, or when a deal feels slow, "how quickly do we answer each other?" is a count over dozens of
conversations: Rouh could read a few threads and guess, and nothing counted them.

So the tool `reply_times`, while its switch is on, reads every mailbox the person has given Rouh
(its own connection and each read-only one, `ghosts.sources`) for the conversations of the last
`DAYS` days (at most `MOST_DAYS`) with the company or the person named, at most `MOST_THREADS` a
mailbox, and walks each one in time order, in plain rules and no model:

- **Theirs** is a message from an address of that company (its domain, or the person's address);
  **his** is one from the mailbox's own addresses; anybody else's, drafts and automatic replies are
  passed over.
- **His reply time** is from the first of their messages after his last word to his next message;
  **theirs** is the same the other way. Each is counted once per answer.
- It says, for each side, the middle time (the median) and how many answers it is from, the
  slowest few of his own answers with their subject, and the conversations whose last word is still
  theirs (waiting on him) or his (waiting on them), with how long.

Nothing is kept, changed or sent: it reads with GET alone.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`. Refused in a contact's case.

**Its switch** is `reply_times` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
import statistics
import time

log = logging.getLogger("rouh.reply_times")

SWITCH = "reply_times"
TITLE = "Reply times: asked in words, how fast you answer a company's email, and they yours"
TOOL_NAME = "reply_times"

DAYS = 90
MOST_DAYS = 365
MOST_THREADS = 60
#: How many of his slowest answers, and of the conversations still waiting, are said.
SLOWEST = 3
WAITING = 5

DESCRIPTION = (
    "How quickly the person answers a company's (or one person's) email, and how quickly they answer "
    "the person's, counted from the conversations themselves in every mailbox the person gave Rouh: the "
    "usual time each side takes, how many answers that is from, the person's slowest answers, and the "
    "conversations still waiting on either side. Use it for 'how fast do I answer Northwind', 'who is "
    "slow, us or them', 'how quickly does Dana reply to me'. `who` is a company's name or domain, or a "
    "person's address; `days` how far back (90 unless asked).")
SCHEMA = {
    "type": "object",
    "properties": {
        "who": {"type": "string", "description": "A company's name or email domain, or a person's address."},
        "days": {"type": "integer", "description": "How many days back to look, 7 to 365. 90 unless asked."},
    },
    "required": ["who"],
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def matcher(who: str):
    """A test for an address: is it the company's (or the person's)?"""
    want = who.strip().lower()
    if "@" in want:
        return lambda address: address == want
    if "." in want:
        return lambda address: address.rpartition("@")[2] == want or address.rpartition("@")[2].endswith("." + want)
    stem = "".join(ch for ch in want if ch.isalnum())
    return lambda address: bool(stem) and stem in "".join(
        ch for ch in address.rpartition("@")[2].rsplit(".", 1)[0] if ch.isalnum())


def walk(thread: dict, own: set[str], theirs, mailbox: str = "") -> dict:
    """One conversation: {mine: [seconds], theirs: [seconds], slow: [...], last: side, at, subject}."""
    from . import ghosts

    messages = sorted(thread.get("messages") or [], key=ghosts._at)
    out = {"mine": [], "theirs": [], "slow": [], "last": "", "at": 0.0, "subject": "",
           "thread_id": thread.get("id") or "", "mailbox": mailbox, "with": ""}
    waiting_since = {"mine": None, "theirs": None}   # who owes the answer: since when
    for message in messages:
        labels = set(message.get("labelIds") or [])
        if labels & {"DRAFT", "CHAT", "SPAM", "TRASH"}:
            continue
        named = ghosts._named(message)
        if ghosts.is_auto_reply(named):
            continue
        sender = (ghosts.people(named.get("from", "")) or [("", "")])[0]
        address = sender[1]
        at = ghosts._at(message)
        out["subject"] = out["subject"] or (named.get("subject") or "(no subject)")[:160]
        if address in own:
            side = "mine"
        elif address and theirs(address):
            side = "theirs"
            out["with"] = sender[0] or address
        else:
            continue
        other = "theirs" if side == "mine" else "mine"
        # Whoever writes answers what the other side wrote since this side's last word.
        if waiting_since[side] is not None:
            took = max(0.0, at - waiting_since[side])
            out[side].append(took)
            if side == "mine":
                out["slow"].append({"took": took, "subject": out["subject"], "at": at})
            waiting_since[side] = None
        if waiting_since[other] is None:
            waiting_since[other] = at
        out["last"], out["at"] = side, at
    return out


def _took(seconds: float) -> str:
    hours = seconds / 3600
    if hours < 1:
        minutes = max(1, round(seconds / 60))
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    if hours < 36:
        whole = round(hours)
        return f"{whole} hour{'s' if whole != 1 else ''}"
    days = round(hours / 24, 1)
    days = int(days) if days == int(days) else days
    return f"{days} days"


def said(who: str, walked: list[dict], *, days: int, troubles: list[str], zone, now: float | None = None) -> str:
    from datetime import datetime

    from . import ghosts

    now = now or time.time()
    talked = [w for w in walked if w["last"]]
    if not talked:
        lines = [f"No conversations with {who} in the last {days} days in the mailboxes Rouh reads."]
    else:
        mine = [t for w in talked for t in w["mine"]]
        theirs = [t for w in talked for t in w["theirs"]]
        lines = [f"Reply times with {who}, the last {days} days, from {len(talked)} conversation"
                 f"{'s' if len(talked) != 1 else ''}:"]
        lines.append(f"- You answer them in {_took(statistics.median(mine))} usually ({len(mine)} answers)."
                     if mine else "- You have not answered them in a conversation yet.")
        lines.append(f"- They answer you in {_took(statistics.median(theirs))} usually ({len(theirs)} answers)."
                     if theirs else "- They have not answered you in a conversation yet.")
        if mine and theirs:
            a, b = statistics.median(mine), statistics.median(theirs)
            if a > 1.5 * b:
                lines.append("So you are the slower side.")
            elif b > 1.5 * a:
                lines.append("So they are the slower side.")
            else:
                lines.append("About the same both ways.")
        slow = sorted((s for w in talked for s in w["slow"]), key=lambda s: -s["took"])[:SLOWEST]
        if slow and len(mine) > 1:
            lines.append("Your slowest answers:")
            for s in slow:
                when = datetime.fromtimestamp(s["at"], zone)
                lines.append(f"- {_took(s['took'])}: {s['subject']!r}, answered {when:%-d %B}")
        on_him = sorted((w for w in talked if w["last"] == "theirs"), key=lambda w: w["at"])
        on_them = sorted((w for w in talked if w["last"] == "mine"), key=lambda w: w["at"])
        if on_him:
            lines.append(f"Still waiting on you ({len(on_him)}):")
            for w in on_him[:WAITING]:
                lines.append(f"- {w['subject']!r}, from {w['with']}, {_took(now - w['at'])} ago. "
                             f"Open: {ghosts.link_to(w['mailbox'], w['thread_id'])}")
        if on_them:
            lines.append(f"Waiting on them ({len(on_them)}):")
            for w in on_them[:WAITING]:
                lines.append(f"- {w['subject']!r}, your last word {_took(now - w['at'])} ago.")
    for one in troubles:
        lines.append(f"Not read: {one}")
    lines.append("Counted from who wrote last in each conversation: an answer given by phone or in a meeting "
                 "is not seen.")
    return "\n".join(lines)


async def scan(reader, who: str, *, days: int, mailbox: str = "") -> list[dict]:
    from . import ghosts

    own = await reader.addresses()
    if not own:
        return []
    want = who.strip().lower()
    term = want if ("@" in want or "." in want) else want.split()[0] if want.split() else ""
    if not term:
        return []
    # A bare word, which Gmail matches in the senders and the people written to as well as the words.
    query = f"{term} newer_than:{days}d"
    found = await reader.search(query, 100)
    threads: list[str] = []
    for one in found:
        tid = one.get("threadId") or one.get("id")
        if tid and tid not in threads:
            threads.append(tid)
    theirs = matcher(want)
    out = []
    for got in await ghosts._gathered([reader.thread(t) for t in threads[:MOST_THREADS]]):
        if isinstance(got, BaseException) or not isinstance(got, dict):
            continue
        out.append(walk(got, own, theirs, mailbox))
    return out


async def answer(who, args: dict, zone) -> tuple[str, int]:
    """(the words for the model, how many conversations were counted)."""
    from asgiref.sync import sync_to_async

    from . import ghosts, runtime

    name = " ".join(str(args.get("who") or "").replace("(", " ").replace(")", " ").split())[:80]
    if not name:
        return "Say whose reply times: a company's name or domain, or a person's address.", 0
    try:
        days = max(7, min(MOST_DAYS, int(args.get("days") or DAYS)))
    except (TypeError, ValueError):
        days = DAYS
    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return "No mailbox is connected on this Rouh.", 0
    sources = await sync_to_async(ghosts.sources)(who, auth)
    if not sources:
        return "No mailbox is connected: connect Google, or a read-only mailbox, in Settings.", 0
    walked: list[dict] = []
    troubles: list[str] = []
    for source in sources:
        if source.needs_reconnect:
            troubles.append(f"{source.email} needs connecting again in Settings.")
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
            if reader is None:
                continue
            walked += await scan(reader, name, days=days, mailbox=source.email)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            troubles.append(ghosts._say_trouble(exc, source.email))
    # A conversation in two mailboxes (Rouh's own and one of the person's) is counted once.
    once: dict[tuple, dict] = {}
    for w in walked:
        once.setdefault((w["subject"], int(w["at"])), w)
    walked = list(once.values())
    counted = len([w for w in walked if w["last"]])
    return said(name, walked, days=days, troubles=troubles, zone=zone), counted


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "matcher", "on", "said",
           "scan", "walk"]
