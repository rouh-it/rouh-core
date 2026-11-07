"""What to raise reads what is attached: the documents attached to a meeting's invitation are read
with the mail, the meetings and Slack before What to raise is worked out.

Built by the nightly feature run, night 31, 3 November 2026 (task 94, idea I-178). A meeting with
people from outside often comes with its papers attached to the invitation: the agenda, the deck
to be gone through, the proposal or the contract to be discussed, put there by whoever sent it.
What to raise (`rouh/meeting_brief.py`, kept by ‹him› on 19 October 2026) read the event's title
and description, the mail with its guests, the earlier meetings and Slack, and never what was
attached, so it could tell ‹him› what to raise at a meeting without having read the very agenda
the other side had sent for it, and point the wrong way where the agenda said otherwise.

So, while its switch is on, the brief's What to raise for a meeting with up to `MOST` files
attached to its invitation reads each one the connected Google account can open (a Google Doc,
Sheet or deck, and a PDF or an Office file too while Files in Drive read is on,
`rouh/drive_files.py`), the first `MOST_CHARS` characters of each, and gives them to the model
with the rest, as the words of whoever wrote them. It is the same one model call, not a second.
A file Rouh's account cannot open is named, never guessed at. What was read is kept with the
reading (`fingerprint`), so a document changed since is read again and the reading made again.

Under What to raise, **The documents attached to the invitation it read** lists them, closed at
first, each a link to the document; one Rouh could not open says so.

**Whose.** The meeting is on ‹his› own calendar and the documents are read with the connected
Google account (`org_id` and `user_id`); nothing is written anywhere but What to raise kept.

**Its switch** is `raise_attached` (`rouh/switches.py`): off, nothing attached is read, as before.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.raise_attached")

SWITCH = "raise_attached"
TITLE = ("What to raise reads what is attached: the documents attached to a meeting's invitation "
         "read with its mail")
#: The most files read for one meeting, the most characters of each, and how long they may take.
MOST = 3
MOST_CHARS = 6000
SECONDS = 25


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


async def read(who, event: dict, services) -> list[dict]:
    """[{title, link, file_id, modified, text}] for the files attached to the event, "" text and
    `unread` with the reason for one that could not be read; [] when off or there are none."""
    from asgiref.sync import sync_to_async

    from . import drive_files

    attached = [one for one in (event.get("attachments") or []) if one.get("file_id")][:MOST]
    if not attached or services is None or getattr(services, "drive", None) is None:
        return []
    if not await sync_to_async(on)(who):
        return []
    files = await sync_to_async(drive_files.on)(who)

    async def one(found: dict) -> dict:
        out = {"title": found["title"], "link": found["link"], "file_id": found["file_id"],
               "modified": "", "text": ""}
        try:
            got = await services.drive.read(found["file_id"], files=files)
        except Exception as exc:  # noqa: BLE001 - named as unread, never guessed at
            log.info("an attached file of %r could not be read: %r", event.get("title"), exc)
            out["unread"] = ("Rouh's Google account cannot open it or read its words"
                             if "found" in str(exc).lower() or "permission" in str(exc).lower()
                             else "it could not be read: " + str(exc)[:160])
            return out
        out["title"] = got.get("name") or found["title"]
        out["modified"] = got.get("modified") or ""
        out["text"] = str(got.get("text") or "")[:MOST_CHARS]
        if not out["text"].strip():
            out["unread"] = "it has no words to read"
        return out

    try:
        return list(await asyncio.wait_for(asyncio.gather(*(one(f) for f in attached)), SECONDS))
    except asyncio.TimeoutError:
        return [{"title": f["title"], "link": f["link"], "file_id": f["file_id"], "modified": "",
                 "text": "", "unread": "it took too long to read"} for f in attached]


def fingerprinted(attached: list[dict]) -> str:
    """What makes a reading of these files a different one: which, and when each last changed."""
    if not attached:
        return ""
    return "|attached:" + "|".join(sorted(f"{a['file_id']}:{a.get('modified')}:{bool(a.get('text'))}"
                                          for a in attached))


def question_lines(attached: list[dict]) -> list[str]:
    """The part of What to raise's question that gives the model the attached files."""
    from . import untrusted

    readable = [a for a in attached if a.get("text")]
    if not readable:
        return []
    lines = [f"\nThe documents attached to the meeting's invitation ({len(readable)}); what they "
             f"say about this meeting (its agenda, what is proposed, what is to be decided) counts "
             f"as much as the mail:"]
    for number, one in enumerate(readable, 1):
        lines.append(f"\n=== Attached document {number}: “{one['title']}”")
        lines.append(untrusted.wrap(one["text"], "a document attached to the invitation"))
    return lines


def shown(attached: list[dict]) -> list[dict]:
    """What the page lists under What to raise: each file's name, its link, and why one was not read."""
    return [{"title": a["title"], "link": a["link"], "unread": a.get("unread") or ""} for a in attached]


__all__ = ["MOST", "SWITCH", "TITLE", "fingerprinted", "on", "question_lines", "read", "shown"]
