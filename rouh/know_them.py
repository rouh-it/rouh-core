"""How you know them: an email from somebody back after months says when you last and first wrote,
and who was on that first email.

Built by the nightly feature run, night 38 of the ledger (9 November 2026, task 94).
Somebody ‹owner› has not heard from in half a year writes as if they spoke yesterday: "Following up on
our talk about the pilot". Gmail shows the one conversation; who they are, what the last thing between
them was, and who brought them to ‹him› in the first place are months down the mailbox, in another
inbox, or in an introduction somebody else wrote. So ‹he› searched, or answered without knowing.

So, while its switch is on, a message opened on the inbox card (Rouh's own inbox or ‹his› read-only
one) from a person, not a machine, who has not written to ‹him› or been written to in the last `QUIET`
days (from, to or copied) in any mailbox Rouh reads (`ghosts.sources`), gets one quiet line under its headers:

    Dana Reed last wrote with you 8 months ago: "Pilot pricing", 12 March 2026. You first wrote on
    3 February 2025, when Owen Marsh introduced you: "Meet Dana from Northwind". 6 conversations in all.

with **Open the last** and **Open the first**, each opening that conversation in Gmail in its own
mailbox. It is a link to the mail where it is, never a copy of it. Somebody written to lately has no
line (‹he› knows them), and nor does somebody writing for the first time. Nothing is kept but a few
hours' memory of the answer, nobody is told, and no model is asked: the first conversation's first
email says who introduced them, by who sent it.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`.

**Its switch** is `know_them` (`rouh/switches.py`): off, the line is not there.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("rouh.know_them")

SWITCH = "know_them"
TITLE = ("How you know them: an email from somebody back after months says when you last and first wrote, "
         "and who was on that first email")

#: Somebody is back when nothing went either way for this many days.
QUIET = 90
#: At most this many messages are listed each way, in each mailbox, to find the first.
MOST = 1500
#: How long an answer is kept, in seconds, so opening the same email again is instant.
KEEP = 6 * 3600

_KEPT: dict[tuple, tuple[float, dict | None]] = {}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def ago(at: float, now: float) -> str:
    days = int((now - at) // 86400)
    if days >= 60:
        months = round(days / 30.4)
        return f"{months} months ago" if months < 24 else f"{round(days / 365)} years ago"
    if days >= 14:
        return f"{days // 7} weeks ago"
    return f"{days} days ago"


def day(at: float, zone) -> str:
    return datetime.fromtimestamp(at, zone).strftime("%-d %B %Y")


async def _listed(reader, query: str) -> list[dict]:
    """Every message a search finds, newest first, page after page, at most `MOST`."""
    out: list[dict] = []
    token = ""
    while len(out) < MOST:
        params = {"q": query, "maxResults": 500}
        if token:
            params["pageToken"] = token
        got = await reader.get("/messages", params)
        out += [one for one in got.get("messages") or [] if one.get("id")]
        token = got.get("nextPageToken") or ""
        if not token:
            break
    return out[:MOST]


async def _at(reader, message_id: str) -> tuple[float, str]:
    """When a message came, and its subject."""
    from . import ghosts

    head = await reader.headers(message_id)
    return ghosts._at(head), ghosts._named(head).get("subject", "")


def sentence(*, name: str, last: dict, first: dict, introducer: str, with_them: list[str],
             conversations: int, now: float, zone) -> str:
    said = (f"{name} last wrote with you {ago(last['at'], now)}: “{last['subject'] or 'no subject'}”, "
            f"{day(last['at'], zone)}.")
    if first["thread"] != last["thread"]:
        said += f" You first wrote on {day(first['at'], zone)}"
        if introducer:
            said += f", when {introducer} introduced you"
        elif with_them:
            said += f", with {' and '.join(with_them[:2])} on it"
        said += f": “{first['subject'] or 'no subject'}”."
    elif introducer:
        said += f" {introducer} introduced you in it."
    if conversations > 1:
        said += f" {conversations} conversations in all."
    return said


async def _read(who, sender: str, open_thread: str, own: list[str]) -> dict | None:
    from asgiref.sync import sync_to_async

    from . import clock, ghosts, runtime

    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return None
    mine = {str(a or "").lower() for a in own if a}
    since = (datetime.now(timezone.utc) - timedelta(days=QUIET)).strftime("%Y/%m/%d")
    readers = []
    for source in await sync_to_async(ghosts.sources)(who, auth):
        if source.needs_reconnect:
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("know them: %s could not be opened: %s", source.email, exc)
            continue
        if reader is not None:
            readers.append((source.email, reader))
    # Written lately, either way, anywhere but the conversation open: no line.
    for _box, reader in readers:
        for query in (f"from:{sender} after:{since}", f"to:{sender} after:{since}", f"cc:{sender} after:{since}"):
            for one in await reader.search(query, 20):
                if (one.get("threadId") or one.get("id")) != open_thread:
                    return None
    found: list[tuple[str, object, dict]] = []
    for box, reader in readers:
        for query in (f"from:{sender}", f"to:{sender}", f"cc:{sender}"):
            got = [one for one in await _listed(reader, query)
                   if (one.get("threadId") or one.get("id")) != open_thread]
            if got:
                found.append((box, reader, {"newest": got[0], "oldest": got[-1], "all": got}))
    if not found:
        return None
    threads = {(one.get("threadId") or one.get("id")) for _b, _r, f in found for one in f["all"]}
    last = first = None
    for box, reader, f in found:
        for which in ("newest", "oldest"):
            one = f[which]
            at, subject = await _at(reader, one["id"])
            item = {"at": at, "subject": subject, "thread": one.get("threadId") or one["id"],
                    "box": box, "reader": reader}
            if which == "newest" and (last is None or at > last["at"]):
                last = item
            if which == "oldest" and (first is None or at < first["at"]):
                first = item
    if last is None or first is None or time.time() - last["at"] < QUIET * 86400:
        return None
    # Who brought them in: whoever sent the first email of the first conversation, when it was not
    # one of the two of them; else whoever else was on it.
    introducer, with_them, name = "", [], ""
    try:
        whole = await first["reader"].thread(first["thread"])
        messages = sorted(whole.get("messages") or [], key=ghosts._at)
        if messages:
            head = ghosts._named(messages[0])
            # The conversation as it began: its first email's day and subject, the introduction itself.
            first["at"] = ghosts._at(messages[0]) or first["at"]
            first["subject"] = head.get("subject", "") or first["subject"]
            frm = ghosts.people(head.get("from", ""))
            if frm and frm[0][1] not in mine and frm[0][1] != sender:
                introducer = frm[0][0] or frm[0][1]
            else:
                for nm, addr in ghosts.people(head.get("to", "") + ", " + head.get("cc", "")):
                    if addr not in mine and addr != sender:
                        with_them.append(nm or addr)
        for message in messages:
            for nm, addr in ghosts.people(ghosts._named(message).get("from", "")):
                if addr == sender and nm:
                    name = nm
    except Exception as exc:  # noqa: BLE001 - said without who introduced them
        log.info("know them: the first conversation could not be read: %s", exc)
    zone = clock.zone_of(who)
    return {"said": sentence(name=name or sender, last=last, first=first, introducer=introducer,
                             with_them=with_them, conversations=len(threads), now=time.time(), zone=zone),
            "last": ghosts.link_to(last["box"], last["thread"]),
            "first": ghosts.link_to(first["box"], first["thread"]) if first["thread"] != last["thread"] else ""}


async def shown(who, found: dict, *, own: list[str]) -> dict | None:
    """What an opened message offers: {said, last, first}, or None (off, a machine, known lately, new)."""
    import asyncio

    from . import ghosts

    if not await asyncio.to_thread(on, who):
        return None
    sender = (ghosts.people(str(found.get("from") or "")) or [("", "")])[0][1]
    mine = {str(a or "").lower() for a in own if a}
    if not sender or sender in mine or ghosts.is_machine(sender):
        return None
    open_thread = str(found.get("thread_id") or "")
    key = (str(getattr(who, "org_id", "")), str(getattr(who, "user_id", "")), sender, open_thread)
    kept = _KEPT.get(key)
    if kept and time.time() - kept[0] < KEEP:
        got = kept[1]
    else:
        got = await _read(who, sender, open_thread, list(mine))
        _KEPT[key] = (time.time(), got)
        while len(_KEPT) > 500:
            _KEPT.pop(next(iter(_KEPT)))
    if not got:
        return None
    from . import evolution

    await asyncio.to_thread(evolution.used, SWITCH, "shown", who=who, detail="a sender back after months")
    return got


def opened(who, which: str) -> None:
    """Open the last or Open the first was pressed on a How you know them line."""
    from . import evolution

    evolution.used(SWITCH, "opened", who=who,
                   detail=f"opened the {'first' if which == 'first' else 'last'} conversation with a sender back after months")


__all__ = ["MOST", "QUIET", "SWITCH", "TITLE", "ago", "on", "opened", "sentence", "shown"]
