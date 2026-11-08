"""Their other questions: an email Rouh writes to somebody is told what else they asked ‹him›, still unanswered.

Built by the nightly feature run, night 33 of this Rouh (the ledger's night 37), 8 November 2026
(task 94), from the Incubator's INC-199. When Rouh writes to somebody for ‹owner›, it reads the
conversation it is in and nothing else. A question the same person asked ‹him› in another email,
a day or a week before, and never answered, stays unanswered: they write again to ask, and ‹he›
writes a second email that one would have covered. Night 34's Waiting on your answer
(`rouh/to_answer.py`) knows which conversations wait on ‹him›; nothing told the email being written.

So, while its switch is on, when Rouh drafts or sends an email in ‹his› own turn, it reads, for each
person it goes to (at most `MOST_PEOPLE`), the conversations of the last `DAYS` days in every inbox
‹he› gave Rouh whose last word is that person's and that asked ‹him› something
(`to_answer.scan`, plain rules, no model), leaving out the conversation this email answers:

- **Sending.** When one is found, nothing is sent the first time: Rouh is told each question, who
  asked it, when and in which email, to answer it in this email where it fits or to say it will be
  answered apart, and to send again with `asks_checked`; or as it is, when the person says so.
- **Drafting.** The draft is made as asked, and Rouh is told the same, to add what fits and say so.

**Whose.** The person's own mailboxes, read with GET alone, by `org_id` and `user_id`, in ‹his› own
turns only. Nothing is kept, changed or sent.

**Its switch** is `their_questions` (`rouh/switches.py`): off, an email is written as it was.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

log = logging.getLogger("rouh.their_questions")

SWITCH = "their_questions"
TITLE = ("Their other questions: an email Rouh writes to somebody is told what else they asked you, in other "
         "emails, that is still unanswered")
DAYS = 14
MOST_PEOPLE = 4
MOST_SAID = 5
SECONDS = 8.0

FIELD = {"type": "boolean",
         "description": "Send it although somebody it goes to has other questions to the person still "
                        "unanswered in other emails: once you have answered them in it where it fits, or the "
                        "person says it goes as it is."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


async def _thread_of(reader, message_id: str) -> str:
    if not message_id:
        return ""
    try:
        head = await reader.headers(message_id)
    except Exception:  # noqa: BLE001 - not in this mailbox
        return ""
    return str(head.get("threadId") or "")


async def find(who, addresses: list[str], reply_to: str = "") -> list[dict]:
    """The open questions from these people, every mailbox, oldest first, the answered email's own left out."""
    from asgiref.sync import sync_to_async

    from . import ghosts, runtime, to_answer

    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None or not addresses:
        return []
    out: list[dict] = []
    for source in await sync_to_async(ghosts.sources)(who, auth):
        if source.needs_reconnect:
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("their questions: %s could not be opened: %s", source.email, exc)
            continue
        if reader is None:
            continue
        skip = await _thread_of(reader, reply_to)
        for address in addresses[:MOST_PEOPLE]:
            try:
                found = await to_answer.scan(reader, days=DAYS, person=address)
            except Exception as exc:  # noqa: BLE001
                log.info("their questions: %s in %s could not be read: %s", address, source.email, exc)
                continue
            for one in found:
                if one.get("ask") and one.get("email", "").lower() == address.lower() \
                        and one.get("thread_id") != skip:
                    out.append(dict(one, mailbox=source.email))
    out.sort(key=lambda one: one["at"])
    return out


def said(found: list[dict], zone, *, sending: bool, now: float | None = None) -> str:
    """The words for the model, or "" when nobody it goes to has another question open."""
    from . import ghosts

    if not found:
        return ""
    now = now or time.time()
    lines = []
    for one in found[:MOST_SAID]:
        who = f"{one['name']} <{one['email']}>" if one.get("name") else one["email"]
        at = datetime.fromtimestamp(one["at"], zone)
        # Days on the person's calendar: written Saturday evening, read Sunday, is yesterday.
        days = (datetime.fromtimestamp(now, zone).date() - at.date()).days
        ago = "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"
        lines.append(f"- {who} asked on {at:%A} {at.day} {at:%B} ({ago}), in {one['subject']!r}: "
                     f"\"{one['ask']}\" Open: {ghosts.link_to(one['mailbox'], one['thread_id'])}")
    head = ("Their other questions (read from the inboxes: still the last word in those emails, nobody "
            "answered). Somebody this email goes to asked the person something else that is still unanswered:\n"
            + "\n".join(lines) + "\n")
    if sending:
        return ("Not sent yet, and nobody was emailed. " + head
                + "Answer each in this email where you know the answer from what the person said or what Rouh "
                  "holds, or say it will be answered apart; ask the person what you do not know. Then send it "
                  "again with asks_checked; if the person says it goes as it is, send it with asks_checked.")
    return ("\n\n" + head + "Add a line for each to the draft where you know the answer, or ask the person, and "
            "say what you added.")


async def note(who, addresses: list[str], zone, *, reply_to: str = "", sending: bool) -> str:
    """Everything in one call, never longer than `SECONDS`, never raising: "" when there is nothing."""
    from asgiref.sync import sync_to_async

    from . import evolution

    try:
        if not addresses or not await asyncio.to_thread(on, who):
            return ""
        found = await asyncio.wait_for(find(who, addresses, reply_to), SECONDS)
        text = said(found, zone, sending=sending)
    except Exception as exc:  # noqa: BLE001 - the email goes on without it
        log.info("their questions: the look did not finish: %s", exc)
        return ""
    if not text:
        return ""
    detail = ", ".join(sorted({one["email"] for one in found}))[:200]
    if sending:
        await sync_to_async(evolution.used)(SWITCH, "held", who=who, detail=f"sending: {detail}")
    else:
        await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"drafting: {detail}")
    return text


__all__ = ["FIELD", "SWITCH", "TITLE", "find", "note", "on", "said"]
