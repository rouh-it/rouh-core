"""Google Slides decks, read slide by slide: the part four genes of night 27 share, and the first
of them, **Decks read slide by slide**.

Built by the nightly feature run, night 27, 30 October 2026 (task 94). ‹His› talks are Google
Slides decks, one per talk, each named with the talk's day first ("2026-10-28 Sopharma"), and
since 28 October a whole talk is made there: 163 slides, every one with speaker notes. Until
tonight Rouh read a deck only through Drive's export, which runs every slide's words and every
speaker note into one text with no slide numbers, so "what does slide 40 say", "change the notes
on the robots slide" or "which slide did Nikola comment on" had no answer.

The Slides API sends each slide on its own (`google_api/slides.py`). This module:

- `deck`: one deck read slide by slide, kept a few minutes, so the genes that read the same deck
  in one turn ask Google once.
- `placed`: the comments on a deck, each put on its slide, by the slide's id in Google's anchor
  for it, else by the words it is on.
- **Decks read slide by slide** (switch `deck_slides`, invisible): while it is on, `read_doc` on a
  deck gives each slide by its number, with its title, its words, its speaker notes and the open
  comments on it, and how to open any one slide, to a chat, a job and Ask AI alike. One Slides
  call and one Drive call, made only for a deck; no model.

**Whose.** The decks the connected Google account can open (`org_id` and `user_id`); nothing is
written in any deck.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata

log = logging.getLogger("rouh.decks")

SWITCH = "deck_slides"
TITLE = ("Decks read slide by slide: a Google Slides deck is read by its numbered slides, each with "
         "its speaker notes and the comments on it")
PRESENTATION = "application/vnd.google-apps.presentation"
#: How long a deck read is kept for the next read of it.
FRESH = 300.0
#: The most of a deck said to the model.
MOST_CHARS = 200_000
_held: dict[tuple, tuple[float, dict]] = {}


def on(who, switch: str = SWITCH) -> bool:
    from . import switches

    return switches.on(switch, getattr(who, "org_id", None) or None)


def forget() -> None:
    _held.clear()


async def deck(services, who, deck_id: str, *, fresh: bool = False) -> dict:
    """The deck read slide by slide (`google_api.deck_of`), kept for `FRESH` seconds."""
    key = (getattr(who, "org_id", ""), getattr(who, "user_id", ""), deck_id)
    held = _held.get(key)
    if held and not fresh and time.time() - held[0] < FRESH:
        return held[1]
    got = await services.slides.deck(deck_id)
    _held[key] = (time.time(), got)
    return got


def plain(text) -> str:
    """Words compared without case, accents or spacing."""
    text = unicodedata.normalize("NFKD", str(text or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^\w]+", " ", text).split())


def placed(deck_read: dict, comments: list[dict]) -> tuple[dict[int, list[dict]], list[dict]]:
    """({slide number: [comment]}, [comment on no slide that could be told]).

    Google keeps where a comment in a deck is pinned in its anchor, which names the slide's id;
    a comment whose anchor names none is put on the one slide whose words hold the words it is on.
    """
    slides = deck_read.get("slides") or []
    on_slide: dict[int, list[dict]] = {}
    nowhere: list[dict] = []
    for c in comments:
        anchor = str(c.get("anchor") or "")
        n = next((s["n"] for s in slides if s.get("id") and s["id"] in anchor), 0)
        if not n and plain(c.get("on")):
            quoted = plain(c.get("on"))
            hits = [s["n"] for s in slides
                    if quoted in plain(" ".join((s.get("title") or "", s.get("text") or "",
                                                 s.get("notes") or "")))]
            n = hits[0] if len(hits) == 1 else 0
        if n:
            on_slide.setdefault(n, []).append(c)
        else:
            nowhere.append(c)
    return on_slide, nowhere


def _clip(text, most: int = 600) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def _comment_line(c: dict) -> str:
    line = f"  Comment [{c.get('id') or '?'}] by {c.get('who') or 'Somebody'}"
    if c.get("on"):
        line += f" on «{_clip(c['on'], 200)}»"
    line += f": «{_clip(c.get('words'))}»"
    for r in c.get("replies") or []:
        line += f"; {r.get('who') or 'somebody'} answered «{_clip(r.get('words'), 300)}»"
    return line


def said(deck_read: dict, comments: list[dict] | None = None, changed: str = "") -> str:
    """A deck as `read_doc` gives it: slide by slide, with notes and open comments."""
    from .google_api import slide_link

    slides = deck_read.get("slides") or []
    open_ = [c for c in comments or [] if not c.get("resolved")]
    resolved = len(comments or []) - len(open_)
    on_slide, nowhere = placed(deck_read, open_)
    head = (f"{deck_read.get('title') or 'A deck'} - Google Slides deck, id {deck_read.get('id')}, "
            f"{len(slides)} slides")
    lines = [head]
    if changed:
        lines.append(changed)
    no_notes = [s["n"] for s in slides if not s.get("notes")]
    lines.append(
        f"Read slide by slide: each slide's words, then its speaker notes (what is said over it, "
        f"not on it), then the open comments on it, the readers' words. A slide opens at "
        f"{slide_link(deck_read.get('id') or '', '<its id>')}. "
        + (f"Slides with no speaker notes: {_numbers(no_notes)}. " if no_notes
           else "Every slide has speaker notes. ")
        + ("No open comments." if not open_ else f"Open comments: {len(open_)}.")
        + (f" {resolved} resolved, left out." if resolved else ""))
    for s in slides:
        lines.append("")
        lines.append(f"=== Slide {s['n']} of {len(slides)}: {s.get('title') or '(no title)'} "
                     f"(id {s.get('id')}) ===")
        if s.get("text"):
            lines.append(s["text"])
        lines.append("Speaker notes: " + (s["notes"] if s.get("notes") else "(none)"))
        lines.extend(_comment_line(c) for c in on_slide.get(s["n"], []))
    if nowhere:
        lines.append("")
        lines.append("Open comments that could not be told to a slide:")
        lines.extend(_comment_line(c) for c in nowhere)
    text = "\n".join(lines)
    if len(text) > MOST_CHARS:
        text = text[:MOST_CHARS].rstrip() + "\n… the rest of the deck is cut here."
    return text


def _numbers(ns: list[int]) -> str:
    """1, 2, 3, 5, 9 as "1 to 3, 5 and 9"."""
    runs: list[list[int]] = []
    for n in ns:
        if runs and n == runs[-1][-1] + 1:
            runs[-1].append(n)
        else:
            runs.append([n])
    words = [f"{r[0]} to {r[-1]}" if len(r) > 2 else ", ".join(map(str, r)) for r in runs]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


async def read_doc_text(google, deck_id: str, changed: str = "") -> str:
    """What read_doc says of a deck while the switch is on, or "" to read it as before."""
    who = google.person()
    if who is None or not await asyncio.to_thread(on, who):
        return ""
    services = google.services()
    if getattr(services, "slides", None) is None:
        return ""
    try:
        read = await deck(services, who, deck_id, fresh=True)
    except Exception as exc:  # noqa: BLE001 - Drive's export is read instead
        log.info("the deck %s could not be read slide by slide: %r", deck_id, exc)
        return ""
    try:
        comments = await services.drive.comments(deck_id)
    except Exception as exc:  # noqa: BLE001 - the slides are read whether or not the comments are
        log.info("the comments of the deck %s could not be read: %r", deck_id, exc)
        comments = []
    from . import evolution

    await asyncio.to_thread(evolution.used, SWITCH, "read", who=who,
                            detail=f"a deck of {len(read.get('slides') or [])} slides read slide by slide")
    return said(read, comments, changed)


__all__ = ["PRESENTATION", "SWITCH", "TITLE", "deck", "forget", "on", "placed", "plain",
           "read_doc_text", "said"]
