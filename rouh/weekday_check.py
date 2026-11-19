"""A day and its date that disagree: an email that names a weekday its date does not fall on is held.

Built by the nightly feature run, night 48 of the ledger (19 November 2026, task 94).
Rouh writes most of the times and dates that leave ‹owner›'s side: a meeting offered, a deadline
agreed, a call confirmed. A model names the weekday of a date from memory, and gets it wrong often
enough: "Tuesday 25 November" when the 25th is a Wednesday. The other side then does not know which
of the two was meant, writes back to ask or turns up on the wrong day, and a second email has to say
"sorry, I meant Wednesday".

So, while its switch is on, before send_mail sends an email or draft_mail drafts one (the person's
own turns and Rouh's jobs alike), its subject and words are read in plain rules, no model, for a
weekday written beside a date: "Tuesday 25 November", "Tue, 25 Nov 2026", "Tuesday, November 25th",
"Tuesday 25.11", "вторник, 25 ноември". A date with its year is read as written; one without is the
nearest such date from a month ago on. When the weekday is not that date's, nothing is sent or
drafted: Rouh is told each one, the day the date really is, and the two ways to put it right
(the date's own weekday, or the date of the named weekday nearest it), and writes it again.
`days_checked` sends it as written, when the person says it is right.

The quoted part of a reply (the lines after "On ... wrote:" and lines starting ">") is not read:
those are somebody else's words, already sent. Nothing is kept and nothing is changed.

**Whose.** Nothing of anybody's is read but the email being written.

**Its switch** is `weekday_check` (`rouh/switches.py`): off, an email goes as written.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

SWITCH = "weekday_check"
TITLE = ("A day and its date that disagree: an email naming a weekday that is not its date's is held "
         "before it goes")

FIELD = {"type": "boolean",
         "description": "Send or draft it although a weekday in it is not the weekday of the date beside it: "
                        "only when the person says the words are right as written, after being told."}

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_EN_DAYS = {d.lower(): i for i, d in enumerate(DAYS)}
_EN_SHORT = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4,
             "sat": 5, "sun": 6}
_BG_DAYS = {"понеделник": 0, "вторник": 1, "сряда": 2, "четвъртък": 3, "петък": 4, "събота": 5,
            "неделя": 6}
_BG_SHORT = {"пон": 0, "вт": 1, "ср": 2, "чет": 3, "пет": 4, "съб": 5, "нед": 6}
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December")
_EN_MONTHS = {m.lower(): i for i, m in enumerate(MONTHS, 1)}
_EN_MONTHS.update({m[:3]: i for m, i in list(_EN_MONTHS.items())})
_EN_MONTHS["sept"] = 9
_BG_MONTHS = {m: i for i, m in enumerate(
    ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
     "ноември", "декември"], 1)}


def _alt(names) -> str:
    return "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))


# A short English day ("Tue") counts only capitalised, so "sun" and "sat" in a sentence are not days.
_DAY = (r"(?P<day>(?i:" + _alt(list(_EN_DAYS) + list(_BG_DAYS)) + r")|"
        + _alt([s.capitalize() for s in _EN_SHORT] + list(_BG_SHORT)) + r")\.?")
_MONTH = r"(?P<{n}>(?i:" + _alt(list(_EN_MONTHS) + list(_BG_MONTHS)) + r"))\.?"
_SEP = r"[,\s]*(?:the\s+)?"
_YEAR = r"(?:[,\s]+(?P<{n}>20\d\d)(?:\s*г\.?)?)?"
_FOUND = re.compile(
    r"(?<![\w-])" + _DAY + _SEP + r"(?:"
    # Tuesday 25 November (2026), Tuesday the 25th of November
    r"(?P<d1>[0-3]?\d)(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH.format(n="m1") + _YEAR.format(n="y1")
    # Tuesday, November 25(th)(, 2026)
    + r"|" + _MONTH.format(n="m2") + r"\s+(?P<d2>[0-3]?\d)(?:st|nd|rd|th)?\b" + _YEAR.format(n="y2")
    # Tuesday 25.11(.2026), Tuesday 25/11
    + r"|(?P<d3>[0-3]?\d)[./](?P<m3>[01]?\d)(?:[./](?P<y3>20\d\d))?(?![\d./])"
    # Tuesday 2026-11-25
    + r"|(?P<y4>20\d\d)-(?P<m4>[01]?\d)-(?P<d4>[0-3]?\d)\b"
    + r")")

#: Where somebody else's words start in a reply: they are not read.
_QUOTED = re.compile(r"^\s*(?:On .{4,200}wrote:|На .{4,200}написа:|-{2,}\s*Original Message|"
                     r"-{2,}\s*Forwarded message|From: .+@)", re.M | re.I)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def own_part(text: str) -> str:
    """The words being written, without the quoted reply under them."""
    text = text or ""
    cut = _QUOTED.search(text)
    if cut:
        text = text[: cut.start()]
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def _weekday(word: str) -> int:
    low = word.lower().rstrip(".")
    for table in (_EN_DAYS, _BG_DAYS, _EN_SHORT, _BG_SHORT):
        if low in table:
            return table[low]
    return -1


def _month(word: str) -> int:
    low = (word or "").lower().rstrip(".")
    return _EN_MONTHS.get(low) or _BG_MONTHS.get(low) or 0


def _nearest(day: int, month: int, today: date) -> date | None:
    """A date with no year: the first one from a month ago on."""
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            got = date(year, month, day)
        except ValueError:
            continue
        if got >= today - timedelta(days=30):
            return got
    return None


def _swapped_fits(day: int, month: int, year, named: int, today: date) -> bool:
    try:
        when = date(int(year), day, month) if year else _nearest(month, day, today)
    except ValueError:
        return False
    return when is not None and when.weekday() == named


def found(text: str, today: date) -> list[dict]:
    """Every weekday written beside a date it is not, in the order they come."""
    out, seen = [], set()
    for hit in _FOUND.finditer(own_part(text)):
        g = hit.groupdict()
        named = _weekday(g["day"])
        if named < 0:
            continue
        if g["d1"]:
            day, month, year = g["d1"], _month(g["m1"]), g["y1"]
        elif g["d2"]:
            day, month, year = g["d2"], _month(g["m2"]), g["y2"]
        elif g["d3"]:
            day, month, year = g["d3"], int(g["m3"]), g["y3"]
        else:
            day, month, year = g["d4"], int(g["m4"]), g["y4"]
        if not month:
            continue
        try:
            when = date(int(year), month, int(day)) if year else _nearest(int(day), month, today)
        except ValueError:
            continue
        if when is None or when.weekday() == named:
            continue
        if g["d3"] and "/" in hit.group(0) and _swapped_fits(int(g["d3"]), int(g["m3"]), g["y3"], named, today):
            # 1/12 is the 1st of December here and the 12th of January in America: either fits, so it is left.
            continue
        words = re.sub(r"\s+", " ", hit.group(0)).strip().rstrip(".,")
        if words.lower() in seen:
            continue
        seen.add(words.lower())
        # The named weekday nearest the date: within three days either side.
        shift = (named - when.weekday()) % 7
        other = when + timedelta(days=shift if shift <= 3 else shift - 7)
        out.append({"words": words, "date": when, "is": DAYS[when.weekday()], "named": DAYS[named],
                    "or": other, "year_given": bool(year)})
    return out


def said(day: date, today: date) -> str:
    out = f"{DAYS[day.weekday()]} {day.day} {MONTHS[day.month - 1]}"
    return out + (f" {day.year}" if day.year != today.year else "")


def check(subject: str, body: str, today: date, *, verb: str = "sent") -> str:
    """Why it is held, for the model, or "" when every weekday is its date's."""
    wrong = found(f"{subject or ''}\n{body or ''}", today)
    if not wrong:
        return ""
    lines = []
    for one in wrong[:5]:
        lines.append(f"\"{one['words']}\": {one['date'].day} {MONTHS[one['date'].month - 1]} "
                     f"{one['date'].year} is a {one['is']}, not a {one['named']}. Either "
                     f"{said(one['date'], today)}, or {said(one['or'], today)}.")
    return ("A day and its date that disagree, so nothing was " + verb + ". " + " ".join(lines)
            + " Write it again with the day that was meant, and say which you chose in one short line; "
              "if you cannot tell which was meant, ask the person. Only if the person says the words "
              "are right as written, call again with days_checked.")


__all__ = ["DAYS", "FIELD", "SWITCH", "TITLE", "check", "found", "on", "own_part", "said"]
