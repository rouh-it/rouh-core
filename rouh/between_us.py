"""Between you and them: asked in words, what is open between the person and one person, by mail, both ways.

Built by the nightly feature run, night 33 of this Rouh (the ledger's night 37), 8 November 2026
(task 94). Before a call or a meeting with somebody, ‹owner› wants to know where things stand with
them: did they ask ‹him› something ‹he› never answered, did ‹he› promise them something, did they
promise ‹him› something that is late. Each side had its own reader (night 34's `rouh/to_answer.py`,
night 36's `rouh/promised_to_you.py`), and what ‹he› promised them was in the brief only on its day
(`rouh/my_word.py`), so the answer took three questions and still missed a part.

So the tool `between_us`, while its switch is on, takes one person (a name or an address) and reads
every mailbox ‹he› gave Rouh (its own connection and each read-only one, `ghosts.sources`), the last
`DAYS` days (or as many as asked, at most `MOST_DAYS`), in plain rules and no model, and says:

1. **They asked you, not answered:** conversations whose last word is theirs and asked something
   (`to_answer.scan`, narrowed to them), with what they asked and how long it has waited.
2. **You promised them:** every promise with a day in ‹his› sent mail to them
   (`mail_promises.scan_sent`, narrowed to them), late or coming, and whether ‹he› wrote to them
   since, so may have kept it.
3. **They promised you:** the same from their mail to ‹him› (`mail_promises.scan_received`).
4. **When each last wrote:** their newest email to ‹him›, and ‹his› newest to them, with subjects.

Each item has its conversation's link in Gmail. Nothing is kept, changed or sent: it reads with GET
alone.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`. Refused in a contact's case.

**Its switch** is `between_us` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

log = logging.getLogger("rouh.between_us")

SWITCH = "between_us"
TITLE = "Between you and them: asked in words, what is open between you and one person by mail, both ways"
TOOL_NAME = "between_us"
DAYS = 45
MOST_DAYS = 90
MOST_SAID = 8

DESCRIPTION = (
    "What is open between the person and ONE other person by email, both ways, from every inbox they gave "
    "Rouh: what that person asked them that they have not answered, what they promised that person by a day "
    "(late or coming, and whether they wrote to them since), what that person promised them, and when each "
    "of them last wrote. Use it when the person asks where things stand with somebody, what is open with "
    "them, or to catch them up before a call or a meeting with them. `person` is a name or an address; "
    "`days` is how far back (45 unless asked).")
SCHEMA = {
    "type": "object",
    "properties": {
        "person": {"type": "string", "description": "The other person: a name or an email address."},
        "days": {"type": "integer", "description": "How many days back to look, 1 to 90. 45 unless asked."},
    },
    "required": ["person"],
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _matches(person: str, name: str, email: str) -> bool:
    """Whether a name or address said by the person is this one."""
    want = person.lower().strip()
    if not want:
        return False
    if "@" in want:
        return want == (email or "").lower()
    words = (name or "").lower().split() + [(email or "").lower().split("@")[0]]
    return all(any(w.startswith(part) for w in words) for part in want.split())


async def _newest(reader, query: str) -> dict | None:
    """The newest email a search finds: {at, subject, thread_id, name, email}, or None."""
    from . import ghosts

    try:
        found = await reader.search(query, 3)
    except Exception as exc:  # noqa: BLE001 - not known is said as not found
        log.info("between us: could not search: %s", exc)
        return None
    best = None
    for one in found[:3]:
        try:
            head = await reader.headers(one["id"])
        except Exception:  # noqa: BLE001
            continue
        named = ghosts._named(head)
        if ghosts.is_auto_reply(named):
            continue
        at = ghosts._at(head)
        if best is None or at > best["at"]:
            sender = (ghosts.people(named.get("from", "")) or [("", "")])[0]
            best = {"at": at, "subject": (named.get("subject") or "(no subject)")[:200],
                    "thread_id": head.get("threadId") or one.get("threadId") or "",
                    "name": sender[0], "email": sender[1]}
    return best


async def address_of(reader, person: str, *, days: int) -> str:
    """The address of a person named by their name, from the mail with them in it; "" when none is."""
    from . import ghosts

    if "@" in person:
        return person.lower()
    try:
        found = await reader.search(f'"{person}" newer_than:{days}d', 10)
    except Exception as exc:  # noqa: BLE001 - not known is said as not found
        log.info("between us: could not search for %s: %s", person, exc)
        return ""
    for one in found[:10]:
        try:
            head = ghosts._named(await reader.headers(one["id"]))
        except Exception:  # noqa: BLE001
            continue
        for field in ("from", "to", "cc"):
            for name, address in ghosts.people(head.get(field, "")):
                if address and _matches(person, name, address):
                    return address.lower()
    return ""


async def read(reader, zone, person: str, *, days: int, mailbox: str) -> dict:
    """One mailbox: {asked, mine, theirs, last_theirs, last_mine, name, email}."""
    from . import mail_promises, to_answer

    person = await address_of(reader, person, days=days) or person
    query_person = person if "@" in person or " " not in person else f"({person})"
    asked = [dict(one, mailbox=mailbox) for one in await to_answer.scan(reader, days=days, person=person)]
    mine = [dict(one, mailbox=mailbox)
            for one in await mail_promises.scan_sent(reader, zone, days=days, mailbox=mailbox, person=person)
            if any(_matches(person, p["name"], p["email"]) for p in one["to"])]
    theirs = [dict(one, mailbox=mailbox)
              for one in await mail_promises.scan_received(reader, zone, days=days, person=person, mailbox=mailbox)]
    last_theirs = await _newest(reader, f"from:{query_person} -in:sent newer_than:{days}d")
    last_mine = await _newest(reader, f"in:sent to:{query_person} newer_than:{days}d")
    name = email = ""
    for one in asked + theirs:
        name, email = one.get("name") or name, one.get("email") or email
    if not email and last_theirs:
        name, email = last_theirs["name"], last_theirs["email"]
    if not email:
        for one in mine:
            for p in one["to"]:
                if _matches(person, p["name"], p["email"]):
                    name, email = p["name"], p["email"]
    for one in (last_theirs, last_mine):
        if one:
            one["mailbox"] = mailbox
    return {"asked": asked, "mine": mine, "theirs": theirs, "last_theirs": last_theirs,
            "last_mine": last_mine, "name": name, "email": email}


def said(person: str, got: dict, zone, *, days: int, troubles: list[str], now: float | None = None) -> str:
    """The answer: what they asked, what was promised each way, and when each last wrote."""
    from . import ghosts, mail_promises

    now = now or time.time()
    today = datetime.fromtimestamp(now, zone).date()
    who = got.get("name") or person
    if got.get("email"):
        who = f"{who} <{got['email']}>"

    def when(at: float) -> str:
        d = datetime.fromtimestamp(at, zone)
        return f"{d:%A} {d.day} {d:%B}"

    def link(one: dict) -> str:
        return ghosts.link_to(one.get("mailbox") or "", one.get("thread_id") or "")

    lines = [f"Between the person and {who}, by email, the last {days} days (every inbox they gave Rouh)."]
    asked = [one for one in got["asked"] if one.get("ask")]
    lines.append(f"\nThey asked, and the person has not answered: {len(asked) or 'nothing'}.")
    for one in asked[:MOST_SAID]:
        waited = max(0, int((now - one["at"]) // 86400))
        lines.append(f"- {when(one['at'])} (waiting {waited} day{'s' if waited != 1 else ''}), "
                     f"{one['subject']!r}: \"{one['ask']}\" Open: {link(one)}")
    others = [one for one in got["asked"] if not one.get("ask")]
    if others:
        lines.append(f"  Also unanswered, with no question in it: "
                     + "; ".join(f"{one['subject']!r} ({when(one['at'])})" for one in others[:4]) + ".")
    for title, items, maker in (("The person promised them", got["mine"], "the person"),
                                ("They promised the person", got["theirs"], "they")):
        late = [one for one in items if one["due"] < today]
        coming = [one for one in items if one["due"] >= today]
        lines.append(f"\n{title}: {len(items) or 'nothing with a day'}.")
        for one in sorted(late, key=lambda i: i["due"]) + sorted(coming, key=lambda i: i["due"]):
            state = ("due " + mail_promises.day_words(one["due"], today)) if one["due"] >= today else \
                ("late, " + mail_promises.day_words(one["due"], today))
            since = ""
            if one["due"] < today:
                since = (f"; {maker} wrote again since, so it may have been done" if one.get("wrote_since")
                         else f"; {maker} have not written since" if maker == "they"
                         else "; the person has not written to them since")
            lines.append(f"- {state}{since}: \"{one['sentence']}\" ({one['subject']!r}, {when(one['at'])}) "
                         f"Open: {link(one)}")
    lines.append("")
    for label, one in (("Their newest email to the person", got.get("last_theirs")),
                       ("The person's newest email to them", got.get("last_mine"))):
        lines.append(f"{label}: " + (f"{when(one['at'])}, {one['subject']!r}. Open: {link(one)}" if one
                                     else f"none in the last {days} days."))
    for one in troubles:
        lines.append(f"Not read: {one}")
    lines.append("Read by plain rules from the emails' own words, with no model: say only what is open, "
                 "shortest first, and offer to draft an answer or a follow-up; send nothing unless asked.")
    return "\n".join(lines)


async def answer(who, args: dict, zone) -> tuple[str, int]:
    """(the words for the model, how many open items were found)."""
    from asgiref.sync import sync_to_async

    from . import ghosts, runtime

    person = " ".join(str(args.get("person") or "").replace("(", " ").replace(")", " ").split())[:80]
    if not person:
        return "Say whom: a name or an email address.", 0
    try:
        days = max(1, min(MOST_DAYS, int(args.get("days") or DAYS)))
    except (TypeError, ValueError):
        days = DAYS
    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return "No mailbox is connected on this Rouh.", 0
    sources = await sync_to_async(ghosts.sources)(who, auth)
    if not sources:
        return ("No mailbox is connected: connect Google, or a read-only mailbox, in Settings.", 0)
    got: dict = {"asked": [], "mine": [], "theirs": [], "last_theirs": None, "last_mine": None,
                 "name": "", "email": ""}
    troubles: list[str] = []
    for source in sources:
        if source.needs_reconnect:
            troubles.append(f"{source.email} needs connecting again in Settings.")
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
            if reader is None:
                continue
            one = await read(reader, zone, person, days=days, mailbox=source.email)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            troubles.append(ghosts._say_trouble(exc, source.email))
            continue
        for part in ("asked", "mine", "theirs"):
            got[part] += one[part]
        for part in ("last_theirs", "last_mine"):
            if one[part] and (got[part] is None or one[part]["at"] > got[part]["at"]):
                got[part] = one[part]
        got["name"] = got["name"] or one["name"]
        got["email"] = got["email"] or one["email"]
    count = len(got["asked"]) + len(got["mine"]) + len(got["theirs"])
    return said(person, got, zone, days=days, troubles=troubles), count


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "on", "read", "said"]
