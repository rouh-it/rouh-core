"""Newsletters you never open: asked in words, the lists whose mail is left unread, each stopped in a word.

Built by the nightly feature run, night 31 (the ledger's night 35), 6 November 2026 (task 94).
Night 34's Unsubscribe in the inbox card stops one newsletter, once it is open on the card. What it
could not say is which lists to stop: the ones whose every email of the last two months is still
unread. Asked "which newsletters do I never read?", Rouh could list recent mail, and could not count,
per sender, how much of it was ever opened.

So the tool `unread_lists`, while its switch is on, reads every mailbox the person has given Rouh
(its own connection and each read-only one, `ghosts.sources`), in plain rules and no model:

1. The mail of the last `DAYS` days (or as many as asked, at most `MOST_DAYS`) that says how to leave
   it (`List-Unsubscribe` or `List-Id`), at most `MOST_MESSAGES` a mailbox, headers only.
2. Grouped by list (its `List-Id`, else its sender), each counted: how many came, how many are still
   unread (Gmail's UNREAD label), the newest's subject and date.
3. **Never opened**: at least `AT_LEAST` came and none was opened. **Hardly opened**: at least
   `AT_LEAST` came and at most one in five was opened, said shorter after. A list the person
   unsubscribed from before (`inbox_unsubscribed`) says so, and when.

`stop` (the lists' names or addresses, as the person says them: "stop Harbor Deals and Packin News")
unsubscribes from each, through night 34's one press (`inbox_unsubscribe.press`, RFC 8058's POST
from the server to a public https address only, or the sender's page to open, or an address to
write to), and says what each answered. Nothing in the mailbox is changed: it reads with GET alone.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`. Refused in a contact's case.

**Its switch** is `unread_lists` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
import re
import urllib.parse

log = logging.getLogger("rouh.unread_lists")

SWITCH = "unread_lists"
TITLE = ("Newsletters you never open: asked in words, the lists whose mail you have left unread for two "
         "months, each stopped in one word")
TOOL_NAME = "unread_lists"

DAYS = 60
MOST_DAYS = 120
MOST_MESSAGES = 300
AT_LEAST = 3
HARDLY = 0.2
MOST_SAID = 25

DESCRIPTION = (
    "The newsletters and lists the person never opens: in every mailbox they gave Rouh (its own and their "
    "read-only ones), the mail of the last 60 days that can be unsubscribed from, counted list by list, "
    "with how many came and how many are still unread, the ones never opened first. Use it when they ask "
    "which newsletters they never read, what mail to stop or unsubscribe from, or to clean up their inbox. "
    "`stop` unsubscribes from the lists they name (by the names or addresses this tool gave), in one go, "
    "and says what each sender answered: use it only when they say to stop or unsubscribe.")
SCHEMA = {
    "type": "object",
    "properties": {
        "days": {"type": "integer", "description": "How many days back to count, 14 to 120. 60 unless asked."},
        "stop": {"type": "array", "items": {"type": "string"},
                 "description": "Lists to unsubscribe from now, by the name or address this tool said."},
    },
}

_ID = re.compile(r"<([^>]+)>")
_HEADERS = ["From", "Subject", "Date", "List-Id", "List-Unsubscribe", "List-Unsubscribe-Post"]


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def list_key(named: dict) -> str:
    """The list one email belongs to: its List-Id, else its sender's address, lower case."""
    from . import ghosts

    found = _ID.search(named.get("list-id") or "")
    if found:
        return found.group(1).strip().lower()
    sender = ghosts.people(named.get("from", ""))
    return sender[0][1] if sender else ""


def counted(messages: list[dict]) -> list[dict]:
    """Each list's count, from its emails' metadata, never-opened first, then by how many came."""
    from . import ghosts

    lists: dict[str, dict] = {}
    for message in messages:
        named = ghosts._named(message)
        if not (named.get("list-unsubscribe") or named.get("list-id")):
            continue
        key = list_key(named)
        if not key:
            continue
        sender = (ghosts.people(named.get("from", "")) or [("", "")])[0]
        one = lists.setdefault(key, {"key": key, "name": "", "address": sender[1], "came": 0,
                                     "unread": 0, "newest": 0.0, "subject": "", "found": {}})
        one["came"] += 1
        if "UNREAD" in (message.get("labelIds") or []):
            one["unread"] += 1
        at = ghosts._at(message)
        if at >= one["newest"]:
            one.update(newest=at, subject=(named.get("subject") or "")[:120],
                       name=(sender[0] or one["name"] or sender[1])[:80], address=sender[1],
                       found={"from": named.get("from", ""),
                              "list_unsubscribe": named.get("list-unsubscribe", ""),
                              "list_unsubscribe_post": named.get("list-unsubscribe-post", "")})
    out = [one for one in lists.values() if one["came"] >= AT_LEAST and one["unread"] >= one["came"] * (1 - HARDLY)]
    out.sort(key=lambda one: (one["unread"] < one["came"], -one["came"], one["name"].lower()))
    return out


async def scan(reader, *, days: int) -> list[dict]:
    """One mailbox's lists that are hardly or never opened."""
    from . import ghosts

    found = await reader.search(f"newer_than:{days}d unsubscribe -in:sent -in:chats", MOST_MESSAGES)
    calls = [reader.get(f"/messages/{urllib.parse.quote(one['id'], safe='')}",
                        {"format": "metadata", "metadataHeaders": _HEADERS}) for one in found[:MOST_MESSAGES]]
    got = [one for one in await ghosts._gathered(calls) if isinstance(one, dict)]
    return counted(got)


def said(found: dict[str, list[dict]], zone, *, days: int, troubles: list[str], before: dict) -> str:
    from datetime import datetime

    total = sum(len(v) for v in found.values())
    lines = [f"Newsletters and lists you hardly or never open, from the last {days} days: {total}"
             + (" (none)." if not total else ".")]
    for mailbox, items in found.items():
        never = [one for one in items if one["unread"] == one["came"]]
        hardly = [one for one in items if one["unread"] < one["came"]]
        if not items:
            lines.append(f"\nIn {mailbox}: none; every list sending there gets opened.")
            continue
        lines.append(f"\nIn {mailbox}: {len(never)} never opened" + (f", {len(hardly)} hardly opened" if hardly else "") + ".")
        for one in (never + hardly)[:MOST_SAID]:
            how = {"one-click": "stops in one press", "link": "stops on its own page",
                   "mail": "stops only by an email from you"}
            from . import inbox_unsubscribe

            offer = inbox_unsubscribe.offer(one["found"]) or {}
            newest = datetime.fromtimestamp(one["newest"], zone).strftime("%-d %B") if one["newest"] else ""
            line = (f"- {one['name']} <{one['address']}>: {one['came']} came, "
                    + ("none opened" if one["unread"] == one["came"] else f"{one['came'] - one['unread']} opened")
                    + (f"; the newest {newest}, {one['subject']!r}" if newest else "")
                    + (f"; {how.get(offer.get('how'), 'says no way to stop it')}" if offer else "; says no way to stop it"))
            was = before.get(one["address"].lower())
            if was and was.get("at"):
                line += (f"; you unsubscribed on {datetime.fromtimestamp(was['at'], zone).strftime('%-d %B')}"
                         " and it still sends")
            lines.append(line)
    for one in troubles:
        lines.append(f"\nNot read: {one}")
    lines.append("\nOpened means read in Gmail, on any device. To stop some, say which: they are unsubscribed "
                 "with `stop`, and nothing in the mailbox is changed.")
    return "\n".join(lines)


def _match(wanted: str, items: list[dict]) -> dict | None:
    low = " ".join(wanted.lower().split())
    if not low:
        return None
    for one in items:
        if low in (one["address"].lower(), one["key"], one["name"].lower()):
            return one
    for one in items:
        if low in one["name"].lower() or low in one["address"].lower():
            return one
    return None


async def answer(who, args: dict, zone) -> tuple[str, int, list[str]]:
    """(the words for the model, how many lists were found, the lists stopped)."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import ghosts, inbox_unsubscribe, runtime

    try:
        days = max(14, min(MOST_DAYS, int(args.get("days") or DAYS)))
    except (TypeError, ValueError):
        days = DAYS
    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return "No mailbox is connected on this Rouh.", 0, []
    sources = await sync_to_async(ghosts.sources)(who, auth)
    if not sources:
        return "No mailbox is connected: connect Google, or a read-only mailbox, in Settings.", 0, []
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
            found[label] = await scan(reader, days=days)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            troubles.append(ghosts._say_trouble(exc, source.email))
    before = await asyncio.to_thread(inbox_unsubscribe.kept, who)
    total = sum(len(v) for v in found.values())
    words = said(found, zone, days=days, troubles=troubles, before=before)
    stop = [str(one) for one in (args.get("stop") or []) if str(one).strip()][:MOST_SAID]
    if not stop:
        return words, total, []
    every = [one for items in found.values() for one in items]
    done: list[str] = []
    lines = ["Unsubscribing, as asked:"]
    for wanted in stop:
        one = _match(wanted, every)
        if one is None:
            lines.append(f"- {wanted}: not among the lists found here, so nothing was sent.")
            continue
        got = await inbox_unsubscribe.press(who, one["found"], by=SWITCH)
        if got.get("ok"):
            done.append(one["address"])
            lines.append(f"- {one['name']}: {got.get('said')}" + (f" Its page: {got['open']}" if got.get("open") else ""))
        else:
            lines.append(f"- {one['name']}: {got.get('why')}")
    return "\n".join(lines), total, done


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "counted", "list_key", "on", "scan"]
