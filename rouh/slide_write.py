"""Written into a deck: asked in words, Rouh changes words on a deck's slides and writes their
speaker notes, and says what each held before.

Built by the nightly feature run, night 30, 2 November 2026 (task 94, idea I-165, widened). Since
night 27 Rouh reads a Google Slides deck slide by slide, with its speaker notes (`rouh/decks.py`),
and since night 29 it writes into a Google Sheet (`rouh/sheet_write.py`), but it could not change
one word of a deck: "make it €39 on slide 12", "the client is Northwind now, change it everywhere
in the deck" or "put this into slide 4's speaker notes" had no tool, and the 163-slide talk of
28 October (task 154) was built and corrected by jobs writing scripts, or by ‹him› in Google
Slides. So asking for it was a manual step left to ‹him›.

So, while its switch is on, the tool **edit_slides** changes a Google Slides deck the connected
Google account can edit, through the Slides API (`google_api/slides.py`, one `batchUpdate`):

- **Words replaced**: `{find, put, slides?}`, every place the words stand, on the slides named
  (by number) or on all of them, matched exactly with case, through `replaceAllText`, so a
  word's style and the slide's layout stay as they were.
- **Speaker notes written**: `{slide, text, add?}`, the notes of one slide put in (or added
  under what they say), through `deleteText` and `insertText` on its notes shape.

Before it writes it reads the deck (`decks.deck`) and refuses what would do nothing: a slide the
deck does not have (saying how many it has), words found on none of the slides asked about. Its
answer says, for each slide, what changed and what the notes said before, so a wrong change can
be put back in words. Nothing else is touched: no slide is added, moved or deleted.

**Whose.** The decks the connected Google account can edit (`org_id` and `user_id`). It writes
only what ‹he› asked for in words, in a chat or a job of ‹his›; a deck's own words never ask for
a write.

**Its switch** is `slide_write` (`rouh/switches.py`): off, the tool says so and writes nothing.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.slide_write")

SWITCH = "slide_write"
TITLE = ("Written into a deck: asked in words, Rouh changes words on a Google Slides deck's slides "
         "and writes their speaker notes, and says what each held before")
TOOL_NAME = "edit_slides"
#: The most changes of each kind one call may make.
MOST = 40
DESCRIPTION = (
    "Change a Google Slides deck: replace words on its slides, and write a slide's speaker notes. "
    "Use it when the person asks for words on a deck to change ('make it €39 on slide 12', 'the "
    "client is Northwind now, change it everywhere in the deck') or for speaker notes to be put "
    "in ('put this into slide 4's notes', 'write notes for slides 3 to 5'). Read the deck with "
    "read_doc first, so you know its slides' numbers and their exact words. `replace` is a list "
    "of {find, put, slides}: `find` the exact words as they stand on the slide, with their case, "
    "`put` what goes in their place, and `slides` the slide numbers to change, or left out for "
    "every slide. `notes` is a list of {slide, text, add}: the slide's number, the notes, and "
    "`add` true to put them under what the notes say now rather than in their place. It never "
    "adds, moves or deletes a slide. Say back what changed, and what the notes said before.")
SCHEMA = {
    "type": "object",
    "properties": {
        "deck": {"type": "string", "description": "The Google Slides deck: its link, its id or its name."},
        "replace": {"type": "array", "description": "Words to replace on the slides.",
                    "items": {"type": "object",
                              "properties": {"find": {"type": "string"},
                                             "put": {"type": "string"},
                                             "slides": {"type": "array", "items": {"type": "integer"},
                                                        "description": "Slide numbers; every slide when left out."}},
                              "required": ["find", "put"]}},
        "notes": {"type": "array", "description": "Speaker notes to write.",
                  "items": {"type": "object",
                            "properties": {"slide": {"type": "integer"},
                                           "text": {"type": "string"},
                                           "add": {"type": "boolean"}},
                            "required": ["slide", "text"]}},
    },
    "required": ["deck"],
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _clip(text: str, most: int = 160) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def _numbers(value) -> list[int]:
    out = []
    for one in value or []:
        try:
            out.append(int(one))
        except (TypeError, ValueError):
            continue
    return out


def plan(read: dict, args: dict) -> tuple[list[dict], list[str], str]:
    """(the Slides requests, the lines saying what each does, why not) for what was asked.

    Refuses what would do nothing or what the deck does not have, before anything is written.
    """
    slides = read.get("slides") or []
    by_n = {s["n"]: s for s in slides}
    count = len(slides)
    replace = [r for r in (args.get("replace") or []) if isinstance(r, dict)]
    notes = [n for n in (args.get("notes") or []) if isinstance(n, dict)]
    if not replace and not notes:
        return [], [], "Say what to change: words to replace (replace), or speaker notes (notes)."
    if len(replace) > MOST or len(notes) > MOST:
        return [], [], f"At most {MOST} replacements and {MOST} notes in one go."
    requests: list[dict] = []
    lines: list[str] = []
    for one in replace:
        find, put = str(one.get("find") or ""), str(one.get("put") or "")
        if not find.strip():
            return [], [], "Each replacement needs the words to find."
        if find == put:
            continue
        wanted = _numbers(one.get("slides"))
        missing = [n for n in wanted if n not in by_n]
        if missing:
            return [], [], (f"The deck has {count} slide{'s' if count != 1 else ''}; there is no slide "
                            + ", ".join(str(n) for n in missing) + ".")
        looked = [by_n[n] for n in wanted] if wanted else slides
        hits = [(s, (s.get("title", "") + "\n" + s.get("text", "")).count(find)) for s in looked]
        hits = [(s, k) for s, k in hits if k]
        if not hits:
            where = ("slide " + ", ".join(str(n) for n in wanted)) if wanted else "any slide"
            return [], [], (f"«{_clip(find, 80)}» is not on {where} as written (the match is exact, "
                            "with case). Read the deck with read_doc for its exact words.")
        ask = {"containsText": {"text": find, "matchCase": True}, "replaceText": put}
        ask["pageObjectIds"] = [s["id"] for s, _ in hits]
        requests.append({"replaceAllText": ask})
        lines.append(f"«{_clip(find, 80)}» → «{_clip(put, 80)}» on slide"
                     + ("s " if len(hits) != 1 else " ")
                     + ", ".join(f"{s['n']}" + (f" ({k} places)" if k > 1 else "") for s, k in hits))
    for one in notes:
        try:
            n = int(one.get("slide"))
        except (TypeError, ValueError):
            return [], [], "Each note needs its slide's number."
        slide = by_n.get(n)
        if slide is None:
            return [], [], f"The deck has {count} slide{'s' if count != 1 else ''}; there is no slide {n}."
        if not slide.get("notes_id"):
            return [], [], f"Slide {n} has no speaker notes box Google lets Rouh write in."
        text = str(one.get("text") or "").strip()
        if not text:
            return [], [], f"Say what the notes of slide {n} should say."
        before = slide.get("notes") or ""
        after = (before.rstrip() + "\n" + text) if (one.get("add") and before.strip()) else text
        if after == before:
            continue
        if before:
            requests.append({"deleteText": {"objectId": slide["notes_id"], "textRange": {"type": "ALL"}}})
        requests.append({"insertText": {"objectId": slide["notes_id"], "insertionIndex": 0, "text": after}})
        lines.append(f"slide {n}'s notes " + ("added to" if one.get("add") and before.strip() else "written")
                     + (f" (they said «{_clip(before)}»)" if before.strip() else " (they were empty)"))
    return requests, lines, ""


async def answer(google, args: dict) -> str:
    """What edit_slides says, having written what was asked for."""
    from . import decks, evolution
    from .google_api.slides import slide_link

    blocked = google.not_ready_because()
    if blocked:
        return blocked
    who = google.person()
    if who is None or not await asyncio.to_thread(on, who):
        return "Writing into a Google Slides deck is switched off (Evolution, Mutations: Written into a deck)."
    named = str((args or {}).get("deck") or "").strip()
    if not named:
        return "Say which deck, by its link, its id or its name."
    services = google.services()
    if getattr(services, "slides", None) is None:
        return "Google Slides is not connected here."
    from .tools import _find_doc, _google_trouble

    try:
        deck_id, kind = await _find_doc(services.drive, named)
        if kind and kind != decks.PRESENTATION:
            return f"{named!r} is not a Google Slides deck, so it has no slides to change."
        read = await decks.deck(services, who, deck_id, fresh=True)
    except Exception as exc:  # noqa: BLE001 - said in Google's words
        return _google_trouble(exc)
    requests, lines, why_not = plan(read, args or {})
    if why_not:
        return why_not
    if not requests:
        return "Nothing to change: the deck already says that."
    try:
        got = await services.slides.batch_update(deck_id, requests)
    except Exception as exc:  # noqa: BLE001 - nothing was written: a batch is all or nothing
        return _google_trouble(exc) + " Nothing was changed: Google makes a batch all or none."
    decks.forget()
    replaced = sum(int((r.get("replaceAllText") or {}).get("occurrencesChanged") or 0)
                   for r in (got or {}).get("replies") or [])
    said = (f"In {read.get('title') or 'the deck'!r}: " + "; ".join(lines) + "."
            + (f" {replaced} place{'s' if replaced != 1 else ''} changed in all." if replaced else "")
            + f" It opens at {slide_link(deck_id)}.")
    wrote = getattr(google, "wrote", None)
    if callable(wrote):
        wrote(TOOL_NAME, deck_id, said)
    await asyncio.to_thread(evolution.used, SWITCH, "written", who=who,
                            detail=f"{len(lines)} change{'s' if len(lines) != 1 else ''} written into a deck")
    return said


__all__ = ["DESCRIPTION", "MOST", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "on", "plan"]
