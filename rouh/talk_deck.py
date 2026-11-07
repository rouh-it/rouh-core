"""The deck for your talk: on the morning of a talk and the day before, the morning brief says what
is still open in its Google Slides deck.

Built by the nightly feature run, night 27, 30 October 2026 (task 94). ‹He› gives a talk every
week or two, each from a Google Slides deck named with its day first ("2026-10-28 Sopharma",
"2026-10-16 Spanish Embassy"), made with others: a colleague adds slides, a reviewer comments, a
job writes the speaker notes. What is still open in it on the day was found by opening it and
paging through: a slide nobody wrote notes for, a comment nobody answered, a change somebody
else made the night before.

So, while its switch is on, the morning brief has a section **The deck for your talk** for every
deck in Drive whose name starts with today's or tomorrow's date on ‹his› clock, read as the page
opens, with no model, and only when something in it is open:

- the slides that have no speaker notes, by number, the first one a link that opens the deck on it;
- each open comment on it that neither ‹he› nor Rouh answered, with the slide it is on
  (`rouh/decks.py`) and **Open the comment**;
- who changed it last, when that was somebody else in the last three days.

**Open the deck** opens it in Google Slides; **Let it be** puts that version of it away, with
Undo, and it comes back once the deck changes again.

**Whose.** The decks the connected Google account can open (`org_id` and `user_id`), read only;
what ‹he› put away is ‹his› own setting (`user_settings`, `talk_deck`). Nothing is written in any
deck.

**Its switch** is `talk_deck` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta

log = logging.getLogger("rouh.talk_deck")

SWITCH = "talk_deck"
TITLE = ("The deck for your talk: on the day of a talk and the day before, what is still open in "
         "its deck, in the morning brief")
#: The person's own setting: {"<deck>:<modified>": {"at"}}.
KEPT = "talk_deck"
#: The most decks a day, the most comments listed on one, how recent another person's change is
#: told, and how long a reading is kept.
MOST_DECKS = 3
COMMENTS = 6
CHANGED_DAYS = 3
FRESH = 600.0
_held: dict[str, tuple[float, list[dict]]] = {}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def forget() -> None:
    _held.clear()


def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    month = time.time() - 31 * 86400
    held = {k: v for k, v in held.items() if float(v.get("at") or 0) > month}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def days(who, now: float | None = None) -> list[tuple[str, str]]:
    """[(YYYY-MM-DD, "today"), (..., "tomorrow")] on the person's own clock."""
    from . import clock

    here = datetime.fromtimestamp(now or time.time(), clock.zone_of(who))
    return [(here.date().isoformat(), "today"),
            ((here + timedelta(days=1)).date().isoformat(), "tomorrow")]


def unanswered(comment: dict, who) -> bool:
    """Open, not by the owner or Rouh, and nobody of theirs answered it."""
    from . import comments_in_docs as cid

    if comment.get("resolved") or comment.get("me") or cid.by_owner(comment.get("who") or "", who):
        return False
    return not any(r.get("me") or cid.by_owner(r.get("who") or "", who)
                   for r in comment.get("replies") or [])


def _numbers(ns: list[int]) -> str:
    from .decks import _numbers as said

    return said(ns)


async def _deck_line(services, who, found: dict, when: str, now: float) -> dict | None:
    """What is open in one deck, or None when nothing is."""
    from . import comments_in_docs as cid
    from . import decks
    from .google_api import slide_link

    read = await decks.deck(services, who, found["id"], fresh=True)
    slides = read.get("slides") or []
    try:
        comments = await services.drive.comments(found["id"])
    except Exception as exc:  # noqa: BLE001 - the notes are told whether or not the comments are
        log.info("the comments of the deck %s could not be read: %r", found["id"], exc)
        comments = []
    try:
        change = await services.drive.last_change(found["id"])
    except Exception as exc:  # noqa: BLE001 - told without it
        log.info("who last changed the deck %s could not be read: %r", found["id"], exc)
        change = {}
    no_notes = [s for s in slides if not (s.get("notes") or "").strip()]
    open_ = [c for c in comments if await asyncio.to_thread(unanswered, c, who)]
    on_slide, _nowhere = decks.placed(read, open_)
    slide_of = {id(c): n for n, cs in on_slide.items() for c in cs}
    doc = {"id": found["id"], "kind": "Google Slides"}
    lines = []
    for c in sorted(open_, key=lambda c: (slide_of.get(id(c)) or 10 ** 6, cid.moment(c.get("at"))))[:COMMENTS]:
        lines.append({"who": c.get("who") or "Somebody", "slide": slide_of.get(id(c)) or 0,
                      "on": cid.clip(c.get("on"), 160), "words": cid.clip(c.get("words"), 400),
                      "day": cid.day(cid.moment(c.get("at"))), "link": cid.link_to(doc, c.get("id") or "")})
    changed = ""
    at = cid.moment(change.get("at"))
    if (change.get("who") and not change.get("me") and not cid.by_owner(change["who"], who)
            and at and now - at < CHANGED_DAYS * 86400):
        changed = f"{change['who']} changed it last, {cid.day(at)}."
    if not no_notes and not open_ and not changed:
        return None
    return {"key": f"{found['id']}:{found.get('modified') or read.get('revision') or ''}",
            "id": found["id"], "name": read.get("title") or found["name"], "when": when,
            "link": slide_link(found["id"]), "slides": len(slides),
            "no_notes": [s["n"] for s in no_notes], "no_notes_said": _numbers([s["n"] for s in no_notes]),
            "first_no_notes": slide_link(found["id"], no_notes[0]["id"]) if no_notes else "",
            "comments": lines, "open": len(open_), "changed": changed}


async def found(who, google, now: float | None = None) -> dict | None:
    """{decks: [...]} for the brief, or None when no talk's deck has anything open."""
    from asgiref.sync import sync_to_async

    from .decks import PRESENTATION

    if google is None:
        return None
    now = now or time.time()
    key = f"{who.org_id}:{who.user_id}"
    held = _held.get(key)
    if held and now - held[0] < FRESH:
        out = held[1]
    else:
        services = google(who)
        if getattr(services, "slides", None) is None:
            return None
        out = []
        for day, when in days(who, now):
            try:
                listed = await services.drive.search(day, limit=10, only_type=PRESENTATION)
            except Exception as exc:  # noqa: BLE001 - nothing to say for that day
                log.info("the decks for %s could not be looked for: %r", day, exc)
                continue
            for f in listed:
                if not str(f.get("name") or "").startswith(day) or len(out) >= MOST_DECKS:
                    continue
                try:
                    line = await _deck_line(services, who, f, when, now)
                except Exception as exc:  # noqa: BLE001 - the other decks are told
                    log.info("the deck %s could not be read: %r", f.get("id"), exc)
                    continue
                if line:
                    out.append(line)
        # Only a reading that found something is kept: a deck made or renamed for a talk shows
        # on the next look rather than ten minutes later.
        if out:
            _held[key] = (now, out)
        else:
            _held.pop(key, None)
    put_away = await sync_to_async(kept)(who)
    shown = [d for d in out if d["key"] not in put_away]
    return {"decks": shown} if shown else None


async def again(who, brief: dict, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("talk_deck", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the decks for today's and tomorrow's talks could not be read")
        return
    if got:
        from . import evolution

        brief["talk_deck"] = {"ok": True, "source": "Your decks in Google Slides", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{len(got['decks'])} talk decks with something open")


class Refused(ValueError):
    """What cannot be done with a deck's line, in a sentence."""


def act(who, key: str, what: str) -> dict:
    """Open the deck, a slide or a comment (kept as a use), Let it be, or Undo it."""
    from . import evolution

    if what == "opened":
        evolution.used("talk_deck", "opened", who=who, detail="opened the deck for a talk")
        return {"ok": True}
    if what == "slide":
        evolution.used("talk_deck", "slide", who=who, detail="opened a slide with no speaker notes")
        return {"ok": True}
    if what == "comment":
        evolution.used("talk_deck", "comment", who=who,
                       detail="opened an open comment on the deck for a talk")
        return {"ok": True}
    held = kept(who)
    if what == "seen":
        held[key] = {"at": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "let_be", who=who, detail="let the deck for a talk be")
        return {"ok": True}
    if what == "undo":
        held.pop(key, None)
        _keep(who, held)
        return {"ok": True}
    raise Refused("Open the deck, Open the comment, Let it be, or Undo.")


__all__ = ["KEPT", "SWITCH", "Refused", "act", "again", "days", "found", "on", "unanswered"]
