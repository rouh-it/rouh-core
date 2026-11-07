"""Find a slide: asked in words, Rouh finds the slides themselves in ‹his› Google Slides decks, by
their words and speaker notes, each with its number and a link that opens the deck on it.

Built by the nightly feature run, night 27, 30 October 2026 (task 94). ‹He› builds each talk out
of the slides of earlier ones: on 28 October the Sopharma talk was planned as "take this from
dreamwall presentation" and "pick out the slides we have for that specific thing", out of decks
of 63 to 440 slides. Rouh could find which deck held some words (Drive's search, `search_drive`),
never which slide, so finding them was ‹his› scrolling, or a job exporting whole decks.

So, while its switch is on, the tool `find_slides` searches ‹his› decks in Drive for the words,
reads each deck that matches slide by slide (`rouh/decks.py`) together with the decks changed
most lately, and answers with every slide whose title, words or speaker notes hold all the words:
the deck, the slide's number and title, a few words of it and of its notes, and the link that
opens the deck on that slide. When no slide holds all of them, the slides holding most of them are
given, said as partly. No model call.

**Whose.** The decks the connected Google account can open (`org_id` and `user_id`); nothing is
written in any deck.

**Its switch** is `find_slides` (`rouh/switches.py`): off, the tool says so and reads nothing.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.find_slides")

SWITCH = "find_slides"
TITLE = ("Find a slide: asked in words, Rouh finds the slides themselves in your decks, each with "
         "its number and a link that opens the deck on it")
TOOL_NAME = "find_slides"
#: The decks Drive's search names that are read, the decks changed lately read besides, how many
#: are read at a time, and the most slides said.
SEARCHED = 10
RECENT = 6
AT_ONCE = 4
SHOWN = 15
DESCRIPTION = (
    "Find slides in the person's Google Slides decks by what is on them or in their speaker "
    "notes, when they look for a slide rather than a file: 'which slide has the robots "
    "benchmark?', 'find the slides on shadow AI in my decks', 'where did I talk about Klarna?', "
    "'pick out the slides we have on trends'. It answers with each slide that holds all the "
    "words: the deck, the slide's number and title, a few of its words and notes, and a link that "
    "opens the deck on that slide. Give `words` as the few words that would be on the slide; "
    "`deck` narrows it to one deck, by its name or link. Use it before saying a slide cannot be "
    "found, and give a job that reuses slides the decks and slide numbers it found.")
SCHEMA = {
    "type": "object",
    "properties": {
        "words": {"type": "string", "description": "What would be on the slide: a few words."},
        "deck": {"type": "string",
                 "description": "Only this deck: its name, its id or its link. Every deck when left out."},
    },
    "required": ["words"],
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def terms(words: str) -> list[str]:
    from .decks import plain

    seen: list[str] = []
    for w in plain(words).split():
        if len(w) > 1 and w not in seen:
            seen.append(w)
    return seen


def matching(deck_read: dict, wanted: list[str]) -> list[dict]:
    """[{slide, hits}] for every slide holding at least one of the words, most words first."""
    from .decks import plain

    out = []
    for s in deck_read.get("slides") or []:
        held = plain(" ".join((s.get("title") or "", s.get("text") or "", s.get("notes") or "")))
        words = set(held.split())
        hits = sum(1 for w in wanted if w in words or (len(w) > 3 and w in held))
        if hits:
            title = plain(s.get("title"))
            out.append({"slide": s, "hits": hits,
                        "in_title": sum(1 for w in wanted if w in title)})
    out.sort(key=lambda m: (-m["hits"], -m["in_title"], m["slide"]["n"]))
    return out


async def _decks(services, words: str, deck: str) -> list[dict]:
    """The decks to read: [{id, name, modified}], one when `deck` names it."""
    from .decks import PRESENTATION
    from .google_api import linked_file

    drive = services.drive
    if deck:
        link = linked_file(deck)
        if link:
            about = await drive.metadata(link["id"])
            return [{"id": about["id"], "name": about["name"], "modified": about["modified"]}]
        found = await drive.search(deck, limit=1, only_type=PRESENTATION)
        if not found and " " not in deck.strip() and len(deck.strip()) > 24:
            about = await drive.metadata(deck.strip())
            return [{"id": about["id"], "name": about["name"], "modified": about["modified"]}]
        return [{"id": f["id"], "name": f["name"], "modified": f.get("modified") or ""} for f in found]
    out: dict[str, dict] = {}
    for text, most in ((words, SEARCHED), ("", RECENT)):
        try:
            found = await drive.search(text, limit=most, only_type=PRESENTATION)
        except Exception as exc:  # noqa: BLE001 - the other look still counts
            log.info("Drive's decks could not be searched: %r", exc)
            continue
        for f in found:
            if f.get("id") and f["id"] not in out:
                out[f["id"]] = {"id": f["id"], "name": f.get("name") or "", "modified": f.get("modified") or ""}
    return list(out.values())


async def find(google, who, words: str, deck: str = "") -> dict:
    """{items: [{deck, slide, hits}], all: bool, read, failed, wanted} for the words."""
    from . import decks

    services = google.services()
    wanted = terms(words)
    listed = await _decks(services, words, deck)
    gate = asyncio.Semaphore(AT_ONCE)

    async def one(d):
        async with gate:
            try:
                return d, await decks.deck(services, who, d["id"])
            except Exception as exc:  # noqa: BLE001 - counted, the rest are read
                log.info("the deck %s could not be read: %r", d["id"], exc)
                return d, None

    read = await asyncio.gather(*(one(d) for d in listed))
    items = []
    for d, got in read:
        if got is None:
            continue
        for m in matching(got, wanted):
            items.append({"deck": {**d, "name": got.get("title") or d["name"], "count": len(got["slides"])},
                          "slide": m["slide"], "hits": m["hits"], "in_title": m["in_title"]})
    whole = [i for i in items if i["hits"] == len(wanted)]
    if whole:
        items, every = whole, True
    else:
        best = max((i["hits"] for i in items), default=0)
        items = [i for i in items if best and i["hits"] == best and best * 2 >= len(wanted)]
        every = False
    # The newest deck first, its slides in order; those with the words in their title first of all.
    items.sort(key=lambda i: i["slide"]["n"])
    items.sort(key=lambda i: i["deck"]["modified"], reverse=True)
    items.sort(key=lambda i: -i["in_title"])
    return {"items": items, "all": every, "read": sum(1 for _d, g in read if g is not None),
            "failed": sum(1 for _d, g in read if g is None), "wanted": wanted}


def _bit(text, most: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def said(words: str, got: dict) -> str:
    from .google_api import slide_link

    where = (f"Read {got['read']} decks slide by slide"
             + (f"; {got['failed']} could not be opened by Rouh's Google account" if got["failed"] else "")
             + ".")
    if not got["items"]:
        return (f"No slide holds «{words}» in the decks Rouh's Google account can open. {where} "
                "Try fewer or other words, or name the deck.")
    head = (f"Slides holding «{words}»: {len(got['items'])}." if got["all"] else
            f"No slide holds every word of «{words}»; these hold most of them "
            f"({got['items'][0]['hits']} of {len(got['wanted'])}).")
    lines = [f"{head} {where}"]
    by_deck: dict[str, list[dict]] = {}
    for i in got["items"][:SHOWN]:
        by_deck.setdefault(i["deck"]["id"], []).append(i)
    for deck_id, mine in by_deck.items():
        d = mine[0]["deck"]
        lines.append(f"\n{d['name']} ({d['count']} slides)")
        for i in mine:
            s = i["slide"]
            line = f"- Slide {s['n']}: {s.get('title') or '(no title)'}"
            if s.get("text"):
                line += f" - «{_bit(s['text'], 220)}»"
            if s.get("notes"):
                line += f" Notes: «{_bit(s['notes'], 220)}»"
            lines.append(line + f" Opens at {slide_link(deck_id, s.get('id') or '')}")
    if len(got["items"]) > SHOWN:
        lines.append(f"\nAnd {len(got['items']) - SHOWN} more slides; name the deck or add words to narrow it.")
    return "\n".join(lines)


async def answer(google, who, args: dict) -> str:
    """The tool: the slides, or why not, in words."""
    from . import evolution, untrusted

    if who is None or not await asyncio.to_thread(on, who):
        return untrusted.ours("Finding slides is switched off (Find a slide, in Evolution, Mutations).")
    words = " ".join(str(args.get("words") or "").split())
    if not terms(words):
        return untrusted.ours("Say what would be on the slide: a few words.")
    blocked = google.not_ready_because()
    if blocked:
        return blocked
    if getattr(google.services(), "slides", None) is None:
        return untrusted.ours("Decks cannot be read here.")
    try:
        got = await find(google, who, words, str(args.get("deck") or "").strip())
    except Exception as exc:  # noqa: BLE001 - said in Google's words
        from .tools import _google_trouble

        return _google_trouble(exc)
    await asyncio.to_thread(evolution.used, SWITCH, "found", who=who,
                            detail=f"{len(got['items'])} slides found in {got['read']} decks")
    return said(words, got)


__all__ = ["SWITCH", "TITLE", "TOOL_NAME", "answer", "find", "matching", "said", "terms"]
