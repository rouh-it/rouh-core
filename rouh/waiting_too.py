"""Also waiting on you: an email opened on the inbox card names that sender's other conversations whose
last word is still theirs, with Open.

Built by the nightly feature run, night 36 (8 November 2026, task 94), from INC-514. Answering the
email in front of ‹him›, ‹he› had no way to see that the same person wrote about something else last
week and is still waiting on that one too: Gmail shows one conversation at a time, and the other is
far down the inbox. So the second one waits on, and the person has to ask again.

So, while its switch is on, a message opened on the inbox card (Rouh's own inbox or ‹his› read-only
one) from a person, not a machine or a list, is checked against the person's mailboxes (Rouh's
own and each read-only one, `ghosts.sources`) for the last `DAYS` days with Waiting on your answer's
own rules (`to_answer.verdict`: the conversation's last word is that sender's, a person writing to
‹him›, not a list, not an invitation). Each such conversation other than the one open is said in one
quiet line under the message, oldest first, at most `MOST`: "Dana Reed is also waiting on you:
'Seat numbers before Tuesday', 6 days", with **Open**, which opens it in Gmail in its own mailbox.
It is a link to the conversation where it is, never a copy of it. Nothing is kept, nobody is told,
and no model is asked.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`.

**Its switch** is `waiting_too` (`rouh/switches.py`): off, the line is not there.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("rouh.waiting_too")

SWITCH = "waiting_too"
TITLE = ("Also waiting on you: an email opened on the inbox card names that sender's other emails you "
         "have not answered")
DAYS = 60
MOST = 3


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _waited(at: float, now: float) -> str:
    days = int((now - at) // 86400)
    if days <= 0:
        hours = max(1, int((now - at) // 3600))
        return f"{hours} hour{'s' if hours != 1 else ''}"
    return f"{days} day{'s' if days != 1 else ''}"


def lines(found: list[dict], *, open_thread: str, open_subject: str, now: float | None = None) -> list[dict]:
    """The other conversations, oldest first, each as the card draws it."""
    from . import ghosts

    now = now or time.time()
    seen, out = set(), []
    for one in sorted(found, key=lambda f: f["at"]):
        if one["thread_id"] == open_thread:
            continue
        # The same conversation in two mailboxes, or the open one seen from the other mailbox.
        same = (one["subject"].lower(), int(one["at"]))
        if same in seen or (one["subject"].strip().lower() == open_subject.strip().lower()):
            continue
        seen.add(same)
        who = one["name"] or one["email"]
        out.append({"said": f"{who} is also waiting on you: “{one['subject']}”, {_waited(one['at'], now)}",
                    "link": ghosts.link_to(one.get("mailbox") or "", one["thread_id"]),
                    "ask": one.get("ask") or ""})
    return out[:MOST]


async def _scan(reader, sender: str) -> list[dict]:
    """This sender's conversations in one mailbox's inbox whose last word is theirs, by Waiting on
    your answer's own rules (`to_answer.verdict`)."""
    from . import ghosts, to_answer

    own = await reader.addresses()
    if not own:
        return []
    found = await reader.search(f"in:inbox newer_than:{DAYS}d -in:sent from:{sender}", 50)
    threads: list[str] = []
    for one in found:
        tid = one.get("threadId") or one.get("id")
        if tid and tid not in threads:
            threads.append(tid)
    now, out = time.time(), []
    for got in await ghosts._gathered([reader.thread(t) for t in threads[:to_answer.MOST_THREADS]]):
        if isinstance(got, BaseException) or not isinstance(got, dict):
            continue
        item = to_answer.verdict(got, own, now)
        if item:
            out.append(item)
    return out


async def shown(who, found: dict, *, own: list[str]) -> dict | None:
    """What an opened message offers: {others: [{said, link}]}, or None (off, a machine, or none)."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import ghosts, runtime

    if not await asyncio.to_thread(on, who):
        return None
    sender = (ghosts.people(str(found.get("from") or "")) or [("", "")])[0][1]
    mine = {str(a or "").lower() for a in own if a}
    if not sender or sender in mine or ghosts.is_machine(sender):
        return None
    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return None
    gathered: list[dict] = []
    for source in await sync_to_async(ghosts.sources)(who, auth):
        if source.needs_reconnect:
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
            if reader is None:
                continue
            gathered += [dict(one, mailbox=source.email) for one in await _scan(reader, sender)]
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("waiting too: %s could not be read: %s", source.email, exc)
    others = lines([g for g in gathered if g["email"] == sender],
                   open_thread=str(found.get("thread_id") or ""),
                   open_subject=str(found.get("subject") or ""))
    if not others:
        return None
    from . import evolution

    await asyncio.to_thread(evolution.used, SWITCH, "shown", who=who,
                            detail=f"{len(others)} other emails from the sender waiting")
    return {"others": others}


def opened(who) -> None:
    """Open was pressed on an Also waiting on you line."""
    from . import evolution

    evolution.used(SWITCH, "opened", who=who, detail="opened another email of the sender's waiting on an answer")


__all__ = ["DAYS", "MOST", "SWITCH", "TITLE", "lines", "on", "opened", "shown"]
