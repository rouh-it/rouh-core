"""Dates your tasks wait on: a date an open task's notes say something is due by, passed or close,
in the morning brief.

Built by the nightly feature run, night 29, 1 November 2026 (task 94, idea I-172). ‹His› tasks'
notes say what each waits on and by when: a policy a partner is to send "due by 16 October", a
form whose "deadline is still 30 November", a launch "by 17 November", a report "by 31
December". A job writes the date down once, in Where this stands, and nothing reads it again:
the day passes and the task still says it waits, and the date coming up is seen only by
opening the task. ‹His› calendar has meetings, not these.

So, while its switch is on, the morning brief has a section **Dates your tasks wait on**: each
line of an open task's Where this stands that ties a date to a deadline ("due", "deadline",
"by", "before", "until", "expires", "closes", "no later than"), when that date passed in the
last `PAST_DAYS` days or comes in the next `AHEAD_DAYS`. Passed ones first, the oldest first,
each saying how long ago it was and that the task still says it waits; then the ones coming
up, the nearest first. A line struck through or labelled Replaced, Overtaken, Done or Cleared is
not read, nor one that says a thing already happened by that date ("finished by", "done by").
Each line carries, closed at first, the whole of the line in the notes and when it was written
(**What it says**); **Open the task** opens it; **Done** puts the line away (the date is no
longer waited on, or it was met), with Undo. No model is asked.

**Whose.** The owner's own workspace (`Task` rows not done, their `AGENTS.md`); what ‹he› put away
is ‹his› own setting (`user_settings`, `task_dates`).

**Its switch** is `task_dates` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import date, datetime

log = logging.getLogger("rouh.task_dates")

SWITCH = "task_dates"
TITLE = ("Dates your tasks wait on: a date an open task's notes say something is due by, passed "
         "or in the coming week, in the morning brief, with Open the task and Done")
KEPT = "task_dates"
#: How far back a passed date is still said, and how far ahead a coming one; the most lines.
PAST_DAYS = 45
AHEAD_DAYS = 7
MOST = 6

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september",
     "october", "november", "december"], start=1)}
_MONTHS.update({m[:3]: i for m, i in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_MONTH = r"(?P<mon>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE = re.compile(
    r"(?:(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+" + _MONTH + r"\.?(?:,?\s+(?P<year>20\d\d))?"
    r"|" + _MONTH.replace("mon>", "mon2>") + r"\.?\s+(?P<day2>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<year2>20\d\d))?"
    r"|(?P<iso>20\d\d-\d\d-\d\d))\b", re.IGNORECASE)
#: The words that make a date one something waits on: just before the date, within a few words.
_DUE = re.compile(
    r"\b(?:due|deadlines?|by|until|till|expires?|expiry|closes?|closing|no\s+later\s+than|"
    r"submit|submission|launch(?:es)?|valid|ends?|latest)\b(?:\s+(?:is|on|at|date|still|about|"
    r"around|the|of|by|end|its))*\s*[:\-]?\s*$", re.IGNORECASE)
#: Words that say a thing already happened by the date, so nothing waits on it.
_HAPPENED = re.compile(
    r"\b(?:finished|done|delivered|sent|made|written|built|cleared|decided|agreed|signed|"
    r"announced|checked|recorded|run|answered|paid|booked|published|landed|deployed|"
    r"rechecked|added|filed)\s+(?:\w+\s+){0,2}$", re.IGNORECASE)
_SHUT = re.compile(r"^\s*(?:[-*]\s*)?(?:~~|\*\*(?:Replaced|Overtaken|Done|Cleared|Superseded)\b|"
                   r"(?:Replaced|Overtaken|Done|Cleared|Superseded)\b)", re.IGNORECASE)
_WHERE = re.compile(r"^(#{2,3})\s+Where (?:this|it) stands\b", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s")


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _key(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def _where(lines: list[str]) -> tuple[int, int]:
    for n, line in enumerate(lines):
        found = _WHERE.match(line.strip())
        if found:
            level = len(found.group(1))
            for m in range(n + 1, len(lines)):
                head = _HEADING.match(lines[m])
                if head and len(head.group(1)) <= level:
                    return n + 1, m
            return n + 1, len(lines)
    return 0, 0


def _plain(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"(\*\*|__|`)", "", text).strip().lstrip("-* ").strip()


def _when(found: re.Match, today: date) -> date | None:
    if found.group("iso"):
        try:
            return date.fromisoformat(found.group("iso"))
        except ValueError:
            return None
    mon = (found.group("mon") or found.group("mon2") or "").lower().rstrip(".")
    day = int(found.group("day") or found.group("day2") or 0)
    year = found.group("year") or found.group("year2")
    month = _MONTHS.get(mon) or _MONTHS.get(mon[:3])
    if not month or not day:
        return None
    if year:
        y = int(year)
    else:
        # A date with no year is the nearest one to today, ahead or behind.
        y = today.year
        try:
            if (date(y, month, day) - today).days > 183:
                y -= 1
            elif (today - date(y, month, day)).days > 183:
                y += 1
        except ValueError:
            return None
    try:
        return date(y, month, day)
    except ValueError:
        return None


def _sentence(text: str, start: int, end: int) -> str:
    """The sentence of `text` the span is in: from the last full stop before it to the next after."""
    stops = [m.end() for m in re.finditer(r"[.!?:]\s+(?=[A-Z\"“(])", text[:start])]
    head = stops[-1] if stops else 0
    tail = re.search(r"[.!?](?:\s|$)", text[end:])
    said = text[head:end + (tail.end() if tail else len(text) - end)].strip()
    return said if len(said) <= 240 else said[:239].rstrip() + "…"


def dates_in(line: str, today: date) -> list[dict]:
    """Each date in one line of notes that something waits on: {on, words}."""
    if _SHUT.match(line):
        return []
    plain = _plain(line)
    out = []
    for found in _DATE.finditer(plain):
        before = plain[max(0, found.start() - 48):found.start()]
        if not _DUE.search(before) or _HAPPENED.search(before):
            continue
        when = _when(found, today)
        if when is None:
            continue
        out.append({"on": when, "words": _sentence(plain, found.start(), found.end())})
    return out


def found_in(text: str, today: date) -> list[dict]:
    """{key, line, text, on, words} for every date the notes' Where this stands waits on."""
    lines = text.splitlines()
    start, end = _where(lines)
    out = []
    for n in range(start, end):
        line = lines[n]
        if not line.strip() or "~~" in line:
            continue
        for one in dates_in(line, today):
            out.append({"key": _key(line + "|" + one["on"].isoformat()), "line": n,
                        "text": _plain(line), **one})
    return out


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

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _said_day(d: date) -> str:
    return f"{d.strftime('%A')} {d.day} {d.strftime('%B')}"


def _how_far(days: int) -> str:
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    return f"in {days} days" if days > 0 else f"{-days} days ago"


def found(who, root, today: date | None = None) -> dict | None:
    """{items, count} for the brief, or None when no open task waits on a date that is close."""
    from . import clock, not_handed, open_items
    from .models import Task

    zone = clock.zone_of(who)
    today = today or datetime.now(zone).date()
    put_away = kept(who)
    passed, coming = [], []
    tasks = Task.objects.exclude(state="done").exclude(archived_at__isnull=False).order_by("number")
    for task in tasks.values("number", "folder", "title"):
        folder = str(task["folder"] or "")
        if not folder:
            continue
        got = open_items.read(root, folder)
        if got is None:
            continue
        said_on: set[date] = set()
        for one in found_in(got[1], today):
            # One line a date a task: the notes often say the same date in several places.
            if one["on"] in said_on:
                continue
            said_on.add(one["on"])
            key = f"{folder}:{one['key']}"
            if key in put_away:
                continue
            days = (one["on"] - today).days
            if days < -PAST_DAYS or days > AHEAD_DAYS:
                continue
            since = not_handed._since(root, folder, one["line"])
            written = datetime.fromtimestamp(since, zone) if since else None
            item = {"key": key, "number": task["number"], "title": task["title"] or folder,
                    "link": "/task/" + folder, "on": _said_day(one["on"]), "days": days,
                    "when": _how_far(days), "words": one["words"][:200], "line": one["text"][:900],
                    "written": f"{written.day} {written.strftime('%B')}" if written else ""}
            (passed if days < 0 else coming).append(item)
    passed.sort(key=lambda i: i["days"])
    coming.sort(key=lambda i: i["days"])
    out = passed + coming
    return {"items": out[:MOST], "count": len(out), "passed": len(passed)} if out else None


async def again(who, brief: dict, root) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("task_dates", None)
    try:
        if who is None or not root or not await sync_to_async(on)(who):
            return
        got = await sync_to_async(found)(who, root)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the dates the tasks wait on could not be read")
        return
    if got:
        from . import evolution

        brief["task_dates"] = {"ok": True, "source": "Your tasks' notes", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} dates the tasks wait on")


class Refused(ValueError):
    """What cannot be done with a line, in a sentence."""


def act(who, key: str, what: str) -> dict:
    """Open the task, What it says (each kept as a use), Done, or Undo it."""
    from . import evolution

    if what == "task":
        evolution.used(SWITCH, "task", who=who, detail="opened a task waiting on a date")
        return {"ok": True}
    if what == "context":
        evolution.used(SWITCH, "context", who=who, detail="opened what a task's notes say about a date")
        return {"ok": True}
    held = kept(who)
    if what == "done":
        held[key] = {"at": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "done", who=who, detail="put away a date a task waited on")
        return {"ok": True}
    if what == "undo":
        held.pop(key, None)
        _keep(who, held)
        return {"ok": True}
    raise Refused("Open the task, Done, or Undo.")


__all__ = ["AHEAD_DAYS", "KEPT", "PAST_DAYS", "SWITCH", "TITLE", "Refused", "act", "again",
           "dates_in", "found", "found_in", "on"]
