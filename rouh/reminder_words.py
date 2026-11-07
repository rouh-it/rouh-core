"""A reminder in the person's own words, read into its parts by a model.

Petar, 27 September 2026, on the Reminders page (fr_07085c53b032): "I should
not have to fill those, they should be extracted from my text. alarm in 1h to
do something. should extact that." And the same day, of the first version of
this file, which read the words with rules and lists of phrases: "do not do it
with logic and premade words and programming. this should be determined by a
luna model call. as i stop typing (debounce)".

So when the person stops typing in the page's box, the sentence goes to the
model the Models page has for "Reading Clockwork's words" (`rouh/llm.py`, either
company's since the evening of 18 October 2026; Luna, on Cheaper, by the
standard), with the time it is now on the person's own clock (`clock.zone`), and
it answers in a fixed JSON shape: a one-line title, the rest of what they wrote
as its description, when it first happens, how it repeats, and whether it is a
job for Rouh to do. The title is the line Petar scans the list and the morning
brief by, and has to make sense on its own a month later (fr_b6dabdcc28e2,
`reminder_titles.py`). Nothing here reads the words itself. What is done here is
only what a model's answer always needs: the shape is checked, the local time is
put on the person's clock, and the day and time are said back in the same words
the list uses (`reminders.spoken`).

What the model could not find in the words is named in `missing`, and only that
is left for the person to fill in. When the model cannot be asked here (no key
for its company) or cannot be reached, it says so and the fields are the
person's, as they were before.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

from . import clock
from .reminders import (DAYS, DAY_NAMES, MAX_TITLE, MAX_WHAT, REPEATS, Rule, parts_of_day,
                        plan, repeat_words, spoken)

log = logging.getLogger("rouh.reminder_words")

#: The most the answer may write, reasoning included (`config.luna_max_tokens`
#: says why reasoning counts).
MAX_OUTPUT = 4000

INSTRUCTIONS = """\
You read one reminder or piece of scheduled work that a person typed into the \
Clockwork form of Rouh, their assistant, and give back its parts, so they do not \
have to fill in the form.

It is {now} on the person's own clock ({zone} time, UTC{offset}). Every time you give \
is on that clock.

- title: the thing itself in one line of at most 60 characters, without the when and \
without words like "alarm", "reminder", "remind me to", "don't forget to", and without \
the word that joins it to them ("to", "да"). It is what they scan their list by, so it \
must make sense on its own a month from now, when they have forgotten all about it: \
name the person, the thing and the action, never shorthand, a fragment, or a link. \
First letter capital, no full stop, in the language they wrote in. "alarm in 1h to do \
something" is "Do something"; "напомни ми в петък да купя цветя" is "Купи цветя". \
Empty if the words say only when.
- details: everything else they wrote that the title does not already say - links, \
names, numbers, conditions, what to do in each case - in their own words, without the \
when. Empty when the title says it all, as it does for most short reminders.
- kind: "do" when it is a piece of work for Rouh to do at that time and report on \
(look through the inbox, check the calendar, find out, summarise); otherwise "remind".
- first: the first time it happens, "YYYY-MM-DDTHH:MM". Work out relative words from \
now: "in 1h" is exactly one hour from now, "in 20 min" twenty minutes. "tomorrow at 9" \
is 09:00 tomorrow; a bare "at 5" means the next 5 o'clock that makes sense. A rough \
part of the day with no clock time is that part's usual time: {parts}, in any \
language ("следобед" is afternoon); with no day, the next one still to come, so \
"in the afternoon" is today at 15:00 when it is not yet 15:00, else tomorrow. Empty \
when the words give no time of day, no part of the day and no delay: never make a \
time up.
- date: the day, "YYYY-MM-DD", when the words give a day but no time; the first day \
for a repeat with no time. Empty otherwise.
- repeat: "once", "daily", "weekdays", "weekly" or "monthly".
- days: for weekly, the days as "mon".."sun"; otherwise empty.
- about_rouh: true when it is about Rouh itself - its code, features, genes, tests or \
upkeep - rather than the person's own life and work; otherwise false.
"""

#: The shape of the answer, said in the instructions, so either company's model gives it.
#: (`SCHEMA` was OpenAI's strict schema; it is kept as the reference of the fields.)
ANSWER = """
Answer with one JSON object alone, with exactly these keys: "title" (string), "details" \
(string), "kind" ("remind" or "do"), "first" (string), "date" (string), "repeat" ("once", \
"daily", "weekdays", "weekly" or "monthly"), "days" (a list of "mon".."sun"), "about_rouh" \
(true or false). Empty strings and an empty list where there is nothing."""

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "details", "kind", "first", "date", "repeat", "days", "about_rouh"],
    "properties": {
        "title": {"type": "string"},
        "details": {"type": "string"},
        "kind": {"type": "string", "enum": ["remind", "do"]},
        "first": {"type": "string"},
        "date": {"type": "string"},
        "repeat": {"type": "string", "enum": list(REPEATS)},
        "days": {"type": "array", "items": {"type": "string", "enum": list(DAYS)}},
        "about_rouh": {"type": "boolean"},
    },
}


class CannotRead(Exception):
    """The model could not be asked, or did not answer; the words say why."""


@dataclass
class Read:
    """What the words were read as, for the page and for `reminders.add`."""

    title: str                    # the one line
    details: str                  # the description: everything else, or ""
    kind: str                     # "remind" or "do"
    first: datetime | None        # the first time, on the person's clock
    repeat: str                   # once, daily, weekdays, weekly or monthly
    days: list[str]
    missing: list[str]            # "title", "day", "time": what is still to be given
    date: str = ""                # "2026-09-27", for the form, even with no time
    problem: str = ""             # a time that has passed, in words
    about_rouh: bool = False      # about Rouh itself (`Reminder.about_rouh`)

    def view(self, now: datetime | None = None) -> dict:
        now = (now or clock.now()).astimezone(clock.zone())
        when = ""
        if self.first is not None:
            when = spoken(self.first, now)
            if self.repeat != "once":
                try:
                    cols = plan(self.first, self.repeat, self.days, now=now)
                    rule = Rule(repeat=cols["repeat"], at_time=cols["at_time"],
                                days=tuple(d for d in cols["days"].split(",") if d),
                                month_day=cols["month_day"])
                    said = repeat_words(rule)
                    when = said[:1].lower() + said[1:] + ", first " + spoken(
                        clock.moment(cols["next_at"]), now)
                except ValueError as exc:
                    when, self.problem = "", str(exc)
        return {
            "title": self.title, "details": self.details, "kind": self.kind, "repeat": self.repeat, "days": self.days,
            "date": self.first.strftime("%Y-%m-%d") if self.first else self.date,
            "time": self.first.strftime("%H:%M") if self.first else "",
            "when": when, "missing": self.missing, "problem": self.problem,
            "about_rouh": self.about_rouh,
            "day": self._day(now) if self.first is None else "",
            "zone": clock.place(), "offset": clock.offset(),
        }

    def _day(self, now: datetime) -> str:
        """The day or the repeat the words gave with no time: "tomorrow", "every Monday"."""
        if self.repeat == "weekly" and self.days:
            names = [DAY_NAMES[DAYS.index(d)] for d in DAYS if d in self.days]
            return "every " + (names[0] if len(names) == 1
                               else ", ".join(names[:-1]) + " and " + names[-1])
        if self.repeat != "once":
            return {"daily": "every day", "weekdays": "every weekday", "weekly": "every week",
                    "monthly": "every month"}.get(self.repeat, "")
        if not self.date:
            return ""
        day = date.fromisoformat(self.date)
        gap = (day - now.date()).days
        return ("today" if gap == 0 else "tomorrow" if gap == 1
                else f"{DAY_NAMES[day.weekday()]} {day.day} {day.strftime('%B')}")


async def read(text: str, who=None, now: datetime | None = None) -> Read:
    """Ask the model the Models page has for this, whichever company's it is
    (`rouh/llm.py`), what the words say, on the person's clock. Raises CannotRead.

    It was OpenAI's Responses API alone, with its strict JSON schema, until the
    evening of 18 October 2026; now the shape is in the instructions and the
    answer's JSON is read out of whatever it said, the same way for either company."""
    from . import llm

    now = (now or clock.now()).astimezone(clock.zone())
    words = " ".join(str(text or "").split())[:MAX_WHAT * 2]
    instructions = INSTRUCTIONS.format(
        now=now.strftime("%A %d %B %Y, %H:%M"), zone=clock.place(), offset=clock.offset(now),
        parts=parts_of_day()) + ANSWER
    try:
        got = await llm.ask("reminder_words", system=instructions, messages=words,
                            max_tokens=MAX_OUTPUT, who=who)
    except llm.Cannot as exc:
        raise CannotRead(f"Your words cannot be read here ({exc}): pick the day and the time "
                         "below.") from None
    except Exception as exc:
        log.warning("a reminder's words could not be read: %s", exc)
        raise CannotRead("The model could not be reached just now, so your words were not "
                         "read: try again, or pick the day and the time below.") from None
    said = got.text
    found = re.search(r"\{.*\}", said or "", re.S)
    try:
        parsed = json.loads(found.group(0)) if found else None
    except ValueError:
        parsed = None
    if not isinstance(parsed, dict):
        log.warning("a reminder was answered with something that is not JSON: %.200s", said)
        raise CannotRead("The model's answer could not be used: try again, or pick the day "
                         "and the time below.") from None
    return _taken(parsed, now)


def _taken(got: dict, now: datetime) -> Read:
    """The model's answer, checked, with its local time put on the person's clock."""
    title = " ".join(str(got.get("title") or "").split()).rstrip(".")[:MAX_TITLE]
    details = " ".join(str(got.get("details") or "").split())[:MAX_WHAT]
    kind = "do" if got.get("kind") == "do" else "remind"
    repeat = got.get("repeat") if got.get("repeat") in REPEATS else "once"
    days = [d for d in DAYS if d in (got.get("days") or [])] if repeat == "weekly" else []
    first = _local(got.get("first"), now)
    day = ""
    try:
        day = date.fromisoformat(str(got.get("date") or "")[:10]).isoformat()
    except ValueError:
        pass
    missing = [] if title else ["title"]
    if first is None:
        missing += ["time"] if day or repeat != "once" else ["day", "time"]
    problem = ""
    if first is not None and repeat == "once" and (first - now).total_seconds() < -30:
        when = spoken(first, now)
        problem = f"{when[:1].upper()}{when[1:]} has already passed."
    return Read(title, details, kind, first, repeat, days, missing, date=day, problem=problem,
                about_rouh=got.get("about_rouh") is True)


def _local(value, now: datetime) -> datetime | None:
    try:
        found = datetime.fromisoformat(str(value or "").strip())
    except ValueError:
        return None
    if found.tzinfo is None:
        found = found.replace(tzinfo=now.tzinfo)
    return found.astimezone(now.tzinfo).replace(second=0, microsecond=0)
