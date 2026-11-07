"""Rehearse: a talk's Google Slides deck, gone through one slide at a time on the task's page, its
speaker notes large under a picture of the slide, with a clock, and at the end how long it took
and how long the whole talk would take at that pace.

Built by the nightly feature run, night 27, 30 October 2026 (task 94). ‹His› talks are made in
Google Slides now, every slide with speaker notes ("2026-10-28 Sopharma": 163 slides, six parts of
fifteen minutes each), and the notes are what ‹he› says. Going over them meant Google Slides'
presenter view on a computer, or the phone app, where the notes are a small panel under the
slide, and nothing said whether the talk fitted its time.

So, while its switch is on, a Google Slides deck under a task's Documents has **Rehearse**, and
only a deck has it. Pressing it reads the deck slide by slide (`rouh/decks.py`) and opens it over
the task's page: the slide's number, its picture (Google's own, asked one slide at a time, the
next one ahead), its speaker notes in large type, Previous and Next within reach of a thumb (and
the arrow keys), a clock that starts with the first slide, Stop, and Escape to close. At the end,
or on Finish, it says how long it took, how long each slide took on average, how long the whole
deck would take at that pace when not every slide was gone through, and the slides that took
longest, each a press back to it. The time is counted on the page; nothing is kept but the use.

**Whose.** The deck must be one the task's own notes link (`task_docs.linked`), read with the
connected Google account (`org_id` and `user_id`); nothing is written anywhere. No model call.

**Its switch** is `rehearse` (`rouh/switches.py`): off, no Rehearse is drawn and nothing is read.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.rehearse")

SWITCH = "rehearse"
TITLE = ("Rehearse: a deck under a task's Documents gone through one slide at a time, its speaker "
         "notes large, with a clock and the pace of the whole talk")


def on(org_id=None) -> bool:
    from . import switches, task_docs

    return switches.on(SWITCH, org_id or None) and task_docs.on(org_id)


def button(person, one: dict) -> str:
    """Rehearse on a document's line in Documents, for a Google Slides deck while the switch is on."""
    try:
        if one.get("kind") != "Google Slides" or not on(getattr(person, "org_id", None)):
            return ""
    except Exception:  # noqa: BLE001 - the line is drawn without it
        log.exception("the switch rehearse could not be read")
        return ""
    return '<button type="button" class="obtn odoc-rehearse" hidden>Rehearse</button>'


async def _linked(who, root, folder: str, doc: str) -> dict | None:
    from . import task_docs

    docs = await asyncio.to_thread(task_docs.linked, root, folder)
    return next((d for d in docs if d["id"] == doc and d["kind"] == "Google Slides"), None)


async def deck(who, google, root, folder: str, doc: str) -> dict:
    """{ok, deck: {id, title, count, slides: [{n, id, title, text, notes, link}]}} for one deck."""
    from asgiref.sync import sync_to_async

    from . import decks, evolution
    from .google_api import slide_link

    if not await sync_to_async(on)(getattr(who, "org_id", None)):
        return {"ok": False, "error": "Rehearse is switched off."}
    if google is None:
        return {"ok": False, "error": "Google is not set up here, so the deck cannot be read."}
    if await _linked(who, root, folder, doc) is None:
        return {"ok": False, "error": "That deck is not linked in this task's notes."}
    try:
        services = google(who)
        # Kept a few minutes (`decks.FRESH`), so pressing Rehearse again opens at once.
        read = await decks.deck(services, who, doc)
    except Exception as exc:  # noqa: BLE001 - said in words
        log.info("the deck %s could not be read to rehearse: %r", doc, exc)
        return {"ok": False, "error": "The deck could not be read: Rouh's Google account may not "
                                      "be able to open it."}
    slides = [{**s, "link": slide_link(doc, s.get("id") or "")} for s in read.get("slides") or []]
    if not slides:
        return {"ok": False, "error": "The deck has no slides."}
    await sync_to_async(evolution.used)(SWITCH, "opened", who=who,
                                        detail=f"rehearsing a deck of {len(slides)} slides")
    return {"ok": True, "deck": {"id": doc, "title": read.get("title") or "", "count": len(slides),
                                 "link": slide_link(doc), "slides": slides}}


async def picture(who, google, root, folder: str, doc: str, slide: str) -> dict:
    """{ok, url}: where Google keeps a picture of one slide of the deck, for about half an hour."""
    from asgiref.sync import sync_to_async

    if not await sync_to_async(on)(getattr(who, "org_id", None)):
        return {"ok": False, "error": "Rehearse is switched off."}
    if google is None or not slide:
        return {"ok": False, "error": "No picture of that slide."}
    if await _linked(who, root, folder, doc) is None:
        return {"ok": False, "error": "That deck is not linked in this task's notes."}
    try:
        url = await google(who).slides.thumbnail(doc, slide)
    except Exception as exc:  # noqa: BLE001 - the notes are shown without it
        log.info("no picture of slide %s of %s: %r", slide, doc, exc)
        return {"ok": False, "error": "No picture of that slide."}
    return {"ok": bool(url), "url": url} if url else {"ok": False, "error": "No picture of that slide."}


def rehearsed(who, seconds: float, seen: int, count: int) -> dict:
    """A rehearsal that reached its end, kept as a use: nothing else is kept."""
    from . import evolution

    evolution.used(SWITCH, "finished", who=who,
                   detail=f"rehearsed {seen} of {count} slides in {round(float(seconds) / 60, 1)} minutes")
    return {"ok": True}


__all__ = ["SWITCH", "TITLE", "button", "deck", "on", "picture", "rehearsed"]
