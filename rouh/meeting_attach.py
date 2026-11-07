"""Attach to a meeting: a task's document attached to the invitation of a meeting about it, in one press.

Built by the nightly feature run, night 31, 3 November 2026 (task 94, idea I-179). The papers for
a meeting (the proposal to go through, the agenda, the deck) are made in a task, and the people
coming look for them in the invitation, where Google Calendar keeps a meeting's attached files.
Putting one there meant opening the event in Google Calendar on a computer (the phone apps cannot
attach a file), Add attachment, finding the document in Drive again and saving; Rouh's calendar
tools could not attach anything at all. Google's own answer is in Drive's share menu ("Attach to
calendar event"), far from where the work is.

So, while its switch is on, every Google Doc, Sheet or deck under a task's **Documents** (and a
step's) has **Attach to a meeting**. Pressed, it lists, under the document's line, up to `MOST`
meetings on ‹his› calendar from today to `LOOK_AHEAD_DAYS` ahead that ‹he› organises and whose
title shares a word with the task or the document (the closest in words first, then the
soonest), each with **Attach**, or "attached already". Attach puts the document on the event's
invitation through Calendar's own attachments (`Calendar.attach`), beside what it has, and says
so in place, in plain words: the guests see it in the invitation;
nobody is emailed; and attaching never shares it, so whoever cannot open the document still
cannot (night 30's With a meeting's guests, in Share, does that).

Only meetings ‹he› organises are offered: a guest's copy of somebody else's event cannot carry an
attachment the others see. No model is asked.

**Whose.** The task's own notes link the document (`task_docs.linked`); the meetings are ‹his›
own calendar's, as Synapse keeps them (`org_id` and `user_id`); the event is changed with the
connected Google account.

**Its switch** is `meeting_attach` (`rouh/switches.py`): off, no button is drawn and nothing is
read or written. It is drawn in the task's Documents section (`task_docs`), which is drawn for it
even while The task's documents is off, then with only each document's link and this button.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta

log = logging.getLogger("rouh.meeting_attach")

SWITCH = "meeting_attach"
TITLE = ("Attach to a meeting: a task's document attached to the invitation of a meeting about it, "
         "in one press")
LOOK_AHEAD_DAYS = 14
MOST = 3
MIMES = {"Google Doc": "application/vnd.google-apps.document",
         "Google Sheet": "application/vnd.google-apps.spreadsheet",
         "Google Slides": "application/vnd.google-apps.presentation"}


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def button(person, one: dict) -> str:
    """Attach to a meeting on a document's line in Documents, while the switch is on."""
    try:
        if not on(getattr(person, "org_id", None)):
            return ""
    except Exception:  # noqa: BLE001 - the line is drawn without it
        log.exception("the switch meeting_attach could not be read")
        return ""
    return '<button type="button" class="obtn odoc-attach" hidden>Attach to a meeting</button>'


def _key(calendar_id: str, event_id: str) -> str:
    return "a-" + hashlib.sha256(f"{calendar_id}|{event_id}".encode()).hexdigest()[:16]


def _task_words(root, folder: str) -> set[str]:
    """The words of the task's folder name and of its notes' first heading."""
    from pathlib import Path

    from .share_meeting import words

    parts = [p for p in str(folder or "").split("/") if p][-2:]
    heading = ""
    try:
        notes = Path(root) / folder / "AGENTS.md"
        if notes.is_file():
            for line in notes.read_text(encoding="utf-8", errors="replace").splitlines()[:5]:
                if line.startswith("# "):
                    heading = line[2:]
                    break
    except OSError:
        pass
    return words(*parts, heading)


def meetings(who, root, folder: str, doc: dict, *, now: datetime | None = None) -> list[dict]:
    """Up to `MOST` meetings he organises, today to `LOOK_AHEAD_DAYS` ahead, about the task or the
    document: [{key, title, when, calendar_id, event_id, attached}]."""
    from . import clock
    from .notes_missing import _meta, _rows, _when
    from .share_meeting import words

    about = _task_words(root, folder) | words(doc.get("title") or "")
    if not about:
        return []
    zone = clock.zone_of(who)
    now = (now or datetime.now().astimezone()).astimezone(zone)
    since, until = now - timedelta(hours=1), now + timedelta(days=LOOK_AHEAD_DAYS)
    seen, out = set(), []
    for r in _rows(who, "event", since - timedelta(days=1), 800):
        meta = _meta(r.get("meta"))
        gcal = meta.get("gcal") if isinstance(meta.get("gcal"), dict) else {}
        start = _when(meta.get("start"))
        if start is None or gcal.get("all_day") or gcal.get("status") == "cancelled":
            continue
        if meta.get("from"):
            # Somebody else organises it: his copy cannot carry an attachment the others see.
            continue
        if not gcal.get("calendar_id") or not gcal.get("event_id"):
            continue
        start = start.astimezone(zone)
        if start < since or start > until:
            continue
        name = str(r.get("title") or "").strip()
        shared = about & words(name)
        if not shared:
            continue
        key = _key(gcal["calendar_id"], gcal["event_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append({"key": key, "title": name or "a meeting", "start": start.timestamp(),
                    "calendar_id": gcal["calendar_id"], "event_id": gcal["event_id"],
                    "when": ("today " if start.date() == now.date() else
                             "tomorrow " if start.date() == (now + timedelta(days=1)).date() else
                             start.strftime("%a %-d %b ")) + start.strftime("%H:%M"),
                    "match": len(shared)})
    out.sort(key=lambda m: (-m["match"], m["start"]))
    return out[:MOST]


async def _doc(root, folder: str, doc_id: str) -> dict | None:
    from . import task_docs

    docs = await asyncio.to_thread(task_docs.linked, root, folder)
    return next((d for d in docs if d["id"] == doc_id), None)


def _title(who, doc: dict) -> str:
    from . import task_docs

    try:
        return task_docs.kept_names(who).get(doc["id"]) or doc.get("title") or doc.get("kind") or "the document"
    except Exception:  # noqa: BLE001 - named by the notes' words
        return doc.get("title") or doc.get("kind") or "the document"


async def offer(who, google, root, folder: str, doc_id: str) -> dict:
    """{ok, meetings: [{key, title, when, attached}], doc} for the meetings it could go on."""
    from asgiref.sync import sync_to_async

    if not await sync_to_async(on)(getattr(who, "org_id", None)):
        return {"ok": False, "error": "Attach to a meeting is switched off."}
    doc = await _doc(root, folder, doc_id)
    if doc is None:
        return {"ok": False, "error": "That document is not linked in this task's notes."}
    title = await sync_to_async(_title)(who, doc)
    doc = {**doc, "title": title}
    found = await sync_to_async(meetings)(who, root, folder, doc)
    shown = []
    if found and google is not None:
        services = google(who)

        async def has_it(m: dict) -> bool:
            try:
                event = await services.calendar.event(m["calendar_id"], m["event_id"])
            except Exception:  # noqa: BLE001 - offered all the same
                return False
            return any(a.get("file_id") == doc_id for a in event.get("attachments") or [])

        had = await asyncio.gather(*(has_it(m) for m in found))
        shown = [{"key": m["key"], "title": m["title"], "when": m["when"], "attached": h}
                 for m, h in zip(found, had)]
    from . import evolution

    await sync_to_async(evolution.used)(SWITCH, "opened", who=who,
                                        detail=f"{title[:60]}: {len(shown)} meetings offered")
    return {"ok": True, "doc": title, "meetings": shown}


async def attach(who, google, root, folder: str, doc_id: str, key: str) -> dict:
    """{ok, said} once the document is on the meeting's invitation."""
    from asgiref.sync import sync_to_async

    from . import evolution

    if not await sync_to_async(on)(getattr(who, "org_id", None)):
        return {"ok": False, "error": "Attach to a meeting is switched off."}
    if google is None:
        return {"ok": False, "error": "Google is not set up here, so no meeting can be changed."}
    doc = await _doc(root, folder, doc_id)
    if doc is None:
        return {"ok": False, "error": "That document is not linked in this task's notes."}
    title = await sync_to_async(_title)(who, doc)
    found = await sync_to_async(meetings)(who, root, folder, {**doc, "title": title})
    meeting = next((m for m in found if m["key"] == key), None)
    if meeting is None:
        return {"ok": False, "error": "That meeting is no longer one this document can go on: "
                                      "press Attach to a meeting again."}
    try:
        got = await google(who).calendar.attach(
            meeting["calendar_id"], meeting["event_id"], file_id=doc_id, title=title,
            link=doc["url"], mime_type=MIMES.get(doc.get("kind") or "", ""))
    except Exception as exc:  # noqa: BLE001 - said in words, nothing changed
        log.info("the document %s could not be attached to %s: %r", doc_id, meeting["event_id"], exc)
        return {"ok": False, "error": "Google would not change that meeting: " + str(exc)[:200]}
    if got.get("already"):
        return {"ok": True, "already": True,
                "said": f"It is attached to {meeting['title']}, {meeting['when']}, already."}
    await sync_to_async(evolution.used)(SWITCH, "attached", who=who,
                                        detail=f"{title[:60]} on {meeting['title'][:60]}")
    return {"ok": True, "said": (f"Attached to {meeting['title']}, {meeting['when']}. The guests find it "
                                 f"in the invitation; nobody was emailed, and it is shared with nobody "
                                 f"new, so whoever cannot open {title} still cannot.")}


__all__ = ["SWITCH", "TITLE", "attach", "button", "meetings", "offer", "on"]
