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
be put back in words.

**Slides added, copied, moved and deleted** (20 November 2026, task 191: "Rouh's tools for jobs can
copy a deck and change words, not add, delete or move slides", so a deck assembled from ‹his›
decks went back to ‹him›): `add_slides` makes a slide (`createSlide`, on one of Google's own
layouts, with its title and words put in its placeholders) or copies one of the deck's own
(`duplicateObject`); `move_slides` puts slides after another (`updateSlidesPosition`);
`delete_slides` takes slides out (`deleteObject`). Every number in a call is the slide's number in
the deck as it was read before the call, whatever else the call does, and everything goes in one
batch, so either all of it happens or none. A deck is never left with no slide, and the answer
names each deleted slide by its title, so one deleted by mistake can be found in the deck's own
version history. A slide is taken from another deck by copying that deck (copy_drive_file) and
deleting the rest, since Google's API copies slides within one deck only.

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
    "`add` true to put them under what the notes say now rather than in their place. "
    "`add_slides` is a list of {after, layout, title, text, copy_of}: a new slide after slide "
    "`after` (0 for the very first place, the end when left out), on the layout TITLE_AND_BODY "
    "(the default when it has words), TITLE_ONLY or BLANK, with its title and words; or, with "
    "`copy_of`, a copy of that slide of the deck (right after it unless `after` says). "
    "`move_slides` is a list of {slides, after}: those slides put, in their order, after slide "
    "`after` (0 for the start). `delete_slides` is the numbers of the slides to take out. Every "
    "number is the slide's number before the call, and everything happens at once or not at all. "
    "To take slides from another deck, copy that deck with copy_drive_file and delete the rest. "
    "Say back what changed, and what the notes said before.")
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
        "add_slides": {"type": "array", "description": "Slides to add, or copies of the deck's own.",
                       "items": {"type": "object",
                                 "properties": {"after": {"type": "integer",
                                                          "description": "The slide it comes after; 0 for the first place; the end when left out."},
                                                "layout": {"type": "string", "enum": ["TITLE_AND_BODY", "TITLE_ONLY", "BLANK"]},
                                                "title": {"type": "string"},
                                                "text": {"type": "string"},
                                                "copy_of": {"type": "integer",
                                                            "description": "Copy this slide of the deck instead of making a new one."}}}},
        "move_slides": {"type": "array", "description": "Slides to move.",
                        "items": {"type": "object",
                                  "properties": {"slides": {"type": "array", "items": {"type": "integer"}},
                                                 "after": {"type": "integer",
                                                           "description": "The slide they go after; 0 for the start."}},
                                  "required": ["slides", "after"]}},
        "delete_slides": {"type": "array", "items": {"type": "integer"},
                          "description": "The numbers of the slides to take out."},
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
    shaping = any(args.get(k) for k in ("add_slides", "move_slides", "delete_slides"))
    if not replace and not notes and not shaping:
        return [], [], ("Say what to change: words to replace (replace), speaker notes (notes), or "
                        "slides to add, move or delete (add_slides, move_slides, delete_slides).")
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
    if shaping:
        more, said, why_not = shape(read, args)
        if why_not:
            return [], [], why_not
        requests += more
        lines += said
    return requests, lines, ""


#: The layouts a new slide may be made on, and the placeholders its title and words go into.
LAYOUTS = {"TITLE_AND_BODY": ("TITLE", "BODY"), "TITLE_ONLY": ("TITLE", ""), "BLANK": ("", "")}


def _new_id(taken: set) -> str:
    import secrets

    while True:
        made = "rouh_" + secrets.token_hex(6)
        if made not in taken:
            taken.add(made)
            return made


def _named(slide: dict) -> str:
    return f"slide {slide['n']}" + (f" («{_clip(slide.get('title'), 60)}»)" if slide.get("title") else "")


def _moved(order: list, ids: list, at: int) -> None:
    """`order` as Google leaves it after updateSlidesPosition puts `ids` at `at`, an index counted
    on the order before the move, with the slides still in it."""
    before = sum(1 for i in ids if order.index(i) < at)
    rest = [i for i in order if i not in ids]
    order[:] = rest[:at - before] + list(ids) + rest[at - before:]


def _said_after(after) -> bool:
    return after is not None and after != ""


def shape(read: dict, args: dict) -> tuple[list[dict], list[str], str]:
    """(the Slides requests, the lines saying what each does, why not) for slides added, copied,
    moved and deleted. Every number is the slide's number in the deck as read; the deck's order is
    followed here as each request changes it, so each request's index is right for the deck as it
    is when Google reaches it. Adds go first, then moves, then deletes."""
    slides = read.get("slides") or []
    by_n = {s["n"]: s for s in slides}
    count = len(slides)
    order = [s["id"] for s in slides]
    taken = set(order)
    adds = [a for a in (args.get("add_slides") or []) if isinstance(a, dict)]
    moves = [m for m in (args.get("move_slides") or []) if isinstance(m, dict)]
    deletes = sorted(set(_numbers(args.get("delete_slides"))))
    if len(adds) > MOST or len(moves) > MOST:
        return [], [], f"At most {MOST} slides added and {MOST} moves in one go."

    def no_slide(ns) -> str:
        missing = [n for n in ns if n not in by_n]
        return ("" if not missing else f"The deck has {count} slide{'s' if count != 1 else ''}; there is no slide "
                + ", ".join(str(n) for n in missing) + ".")

    def place(after) -> tuple[int, str]:
        """Where "after slide n" is in the deck's order now, or why that is no place."""
        if not _said_after(after):
            return len(order), ""
        try:
            after = int(after)
        except (TypeError, ValueError):
            return 0, "Say after which slide, by its number (0 for the very first place)."
        if after == 0:
            return 0, ""
        if after not in by_n:
            return 0, no_slide([after])
        return order.index(by_n[after]["id"]) + 1, ""

    requests: list[dict] = []
    lines: list[str] = []
    why = no_slide(deletes)
    if why:
        return [], [], why
    for one in adds:
        after = one.get("after")
        if _said_after(one.get("copy_of")):
            try:
                src = by_n.get(int(one.get("copy_of")))
            except (TypeError, ValueError):
                src = None
            if src is None:
                return [], [], no_slide([one.get("copy_of")]) or "Say which slide to copy, by its number."
            made = _new_id(taken)
            requests.append({"duplicateObject": {"objectId": src["id"], "objectIds": {src["id"]: made}}})
            order.insert(order.index(src["id"]) + 1, made)
            if _said_after(after):
                at, why = place(after)
                if why:
                    return [], [], why
                requests.append({"updateSlidesPosition": {"slideObjectIds": [made], "insertionIndex": at}})
                _moved(order, [made], at)
            lines.append(f"a copy of {_named(src)} added "
                         + ((f"after slide {after}" if int(after or 0) else "at the start")
                            if _said_after(after) else "after it"))
            continue
        title, text = str(one.get("title") or "").strip(), str(one.get("text") or "").strip()
        layout = str(one.get("layout") or "").strip().upper() or (
            "TITLE_AND_BODY" if text else "TITLE_ONLY" if title else "BLANK")
        if layout not in LAYOUTS:
            return [], [], f"A new slide's layout is one of {', '.join(LAYOUTS)}, not {layout}."
        title_box, body_box = LAYOUTS[layout]
        if (title and not title_box) or (text and not body_box):
            return [], [], (f"A {layout} slide has no place for " + ("a title" if title and not title_box
                                                                     else "words") + "; use TITLE_AND_BODY.")
        at, why = place(after)
        if why:
            return [], [], why
        made = _new_id(taken)
        ask = {"objectId": made, "insertionIndex": at, "slideLayoutReference": {"predefinedLayout": layout}}
        maps, fill = [], []
        for kind, words in ((title_box, title), (body_box, text)):
            if kind:
                box = _new_id(taken)
                maps.append({"layoutPlaceholder": {"type": kind, "index": 0}, "objectId": box})
                if words:
                    fill.append({"insertText": {"objectId": box, "insertionIndex": 0, "text": words}})
        if maps:
            ask["placeholderIdMappings"] = maps
        requests.append({"createSlide": ask})
        requests += fill
        order.insert(at, made)
        lines.append(f"a new {layout.lower().replace('_', ' ')} slide added "
                     + ((f"after slide {after}" if int(after or 0) else "at the start") if _said_after(after)
                        else "at the end")
                     + (f", titled «{_clip(title, 60)}»" if title else ""))
    for one in moves:
        ns = _numbers(one.get("slides"))
        if not ns:
            return [], [], "Each move needs the numbers of the slides to move (slides)."
        why = no_slide(ns)
        if why:
            return [], [], why
        if any(n in deletes for n in ns):
            return [], [], "A slide cannot be moved and deleted in the same call."
        if one.get("after") in ns:
            return [], [], "Slides cannot be moved after one of themselves."
        at, why = place(one.get("after"))
        if why:
            return [], [], why
        ids = sorted({by_n[n]["id"] for n in ns}, key=order.index)    # Google wants the deck's order
        requests.append({"updateSlidesPosition": {"slideObjectIds": ids, "insertionIndex": at}})
        _moved(order, ids, at)
        lines.append(("slides " if len(ns) > 1 else "slide ") + ", ".join(str(n) for n in ns) + " moved "
                     + ("to the end" if not _said_after(one.get("after")) else
                        f"after slide {one.get('after')}" if int(one.get("after") or 0) else "to the start"))
    if deletes:
        gone = {by_n[n]["id"] for n in deletes}
        if all(i in gone for i in order):
            return [], [], "That would leave the deck with no slide, so nothing was changed."
        requests += [{"deleteObject": {"objectId": by_n[n]["id"]}} for n in deletes]
        order[:] = [i for i in order if i not in gone]
        lines.append("deleted " + ", ".join(_named(by_n[n]) for n in deletes))
    lines.append(f"the deck now has {len(order)} slide{'s' if len(order) != 1 else ''}")
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
