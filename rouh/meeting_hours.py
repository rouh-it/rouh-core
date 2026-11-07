"""Where your meeting time went, by company: an exact count of ‹his› hours in meetings over a span, by
company and by person, with the span before beside it.

Built by the nightly feature run, night 36 (Rouh's brief called it night 35), 7 November 2026 (task
94). Asked "how much time did I spend with Northwind this quarter?" or "who took my time last
month?", Rouh could only list calendar events (at most 250 at a time) and add them up in the model,
which drops events past the cut and miscounts hours. Nothing counted them.

So, while its switch is on, the tool `meeting_hours` reads ‹his› main calendar over a span (by
default the last 30 days), two weeks at a time so nothing is cut, and counts the timed meetings with
at least one guest that ‹he› did not decline: the hours and the meetings in all, with ‹his› own
company apart from the outside ones; then by company (a guest's address's domain; a free-mail
address such as gmail.com counts as the person), the largest first, with the people met in each;
and, for each, the same span just before it, so a company that took more or less of ‹his› time
than before says so. Given `company` or `person`, it keeps to them and lists each meeting.

A meeting with several companies counts once for each of them, and once in the total. All-day
events, events with nobody else, and the ones ‹he› declined are not meetings here. No model is
asked; nothing is kept.

**Whose.** Read with the person's own Google connection (`org_id` and `user_id`).

**Its switch** is `meeting_hours` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

log = logging.getLogger("rouh.meeting_hours")

SWITCH = "meeting_hours"
TITLE = "Where your meeting time went, by company: your hours in meetings over a span, counted exactly"
TOOL_NAME = "meeting_hours"
#: The longest span read at once, in days, and the piece read at a time.
MOST_DAYS = 370
PIECE = 14
#: How many companies and people are said.
SHOWN = 12

#: Mail that is a person's own, not a company's.
FREE_MAIL = ("gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
             "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "abv.bg", "mail.bg",
             "yandex.ru", "gmx.de", "gmx.net", "web.de", "aol.com")

DESCRIPTION = (
    "How much of the person's time went into meetings over a span, counted exactly from their main "
    "Google calendar (never from a listing added up by hand): hours and meetings in all, their own "
    "company apart from outside ones, then by company (a guest's email domain) with the people met, "
    "the largest first, each against the same span just before. Give `from` and `to` (YYYY-MM-DD; "
    "by default the last 30 days), and `company` (a name or a domain) or `person` (a name or an "
    "address) to keep to them, which lists each meeting. Use it for 'how much time did I spend with "
    "X', 'who takes most of my meeting time', 'how many hours of meetings did I have last month'.")

SCHEMA = {
    "type": "object",
    "properties": {
        "from": {"type": "string", "description": "The first day, YYYY-MM-DD."},
        "to": {"type": "string", "description": "The last day, YYYY-MM-DD."},
        "company": {"type": "string", "description": "Keep to one company: a name or its domain."},
        "person": {"type": "string", "description": "Keep to one person: a name or an address."},
    },
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def span_of(args: dict, today: date) -> tuple[date, date] | str:
    start, end = _day(args.get("from")), _day(args.get("to"))
    if (args.get("from") and start is None) or (args.get("to") and end is None):
        return "The dates have to be written YYYY-MM-DD."
    end = end or (today if not start else min(today, start + timedelta(days=29)))
    start = start or (end - timedelta(days=29))
    if end < start:
        return "The last day is before the first."
    if (end - start).days > MOST_DAYS:
        return f"That is more than {MOST_DAYS} days: ask for about a year at a time."
    return start, end


def company_of(address: str) -> str:
    """What a guest is counted under: their domain, or their address for free mail."""
    low = str(address or "").strip().lower()
    domain = low.rpartition("@")[2]
    return low if domain in FREE_MAIL else domain


def meetings(events: list[dict]) -> list[dict]:
    """The meetings among a calendar's events: timed, somebody else on it, not declined, once each."""
    seen, out = set(), []
    for one in events:
        if one.get("all_day") or not isinstance(one.get("start"), datetime) \
                or not isinstance(one.get("end"), datetime):
            continue
        if one.get("status") == "cancelled" or one.get("kind") not in ("default", "", None):
            continue
        if one.get("my_response") == "declined":
            continue
        guests = [g for g in one.get("guests") or []
                  if not g.get("this_calendar") and not g.get("resource") and g.get("email")
                  and g.get("response") != "declined"]
        if not guests:
            continue
        key = (one.get("id"), one["start"].isoformat())
        if key in seen:
            continue
        seen.add(key)
        hours = max(0.0, (one["end"] - one["start"]).total_seconds() / 3600)
        out.append({"title": one.get("title") or "(no title)", "start": one["start"], "hours": hours,
                    "guests": guests})
    return out


def tally(found: list[dict], own: set[str]) -> dict:
    """{hours, count, inside_hours, inside_count, companies: {name: {hours, count, people}}}."""
    total = {"hours": 0.0, "count": 0, "inside_hours": 0.0, "inside_count": 0, "companies": {}}
    for one in found:
        total["hours"] += one["hours"]
        total["count"] += 1
        names = {}
        for g in one["guests"]:
            company = company_of(g["email"])
            names.setdefault(company, []).append(g.get("name") or g["email"])
        if names and all(c in own for c in names):
            total["inside_hours"] += one["hours"]
            total["inside_count"] += 1
        for company, people in names.items():
            if company in own:
                continue
            row = total["companies"].setdefault(company, {"hours": 0.0, "count": 0, "people": {}})
            row["hours"] += one["hours"]
            row["count"] += 1
            for p in people:
                row["people"][p] = row["people"].get(p, 0) + 1
    return total


def _h(hours: float) -> str:
    whole = round(hours * 4) / 4
    return (f"{whole:g} hour" + ("" if whole == 1 else "s")) if whole >= 1 else f"{round(hours * 60)} minutes"


def _n(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


def _span(start: date, end: date) -> str:
    return f"{start:%A} {start.day} {start:%B %Y} to {end:%A} {end.day} {end:%B %Y}"


def _against(now: float, before: float) -> str:
    if before <= 0:
        return "none the span before" if now else ""
    change = (now - before) / before
    if abs(change) < 0.15:
        return f"about the same as the span before ({_h(before)})"
    return f"{'up' if change > 0 else 'down'} from {_h(before)} the span before"


def _matches(one: dict, company: str, person: str) -> bool:
    for g in one["guests"]:
        address, name = g["email"].lower(), str(g.get("name") or "").lower()
        if company and (company in company_of(address) or company in address.rpartition("@")[2].split(".")[0]):
            return True
        if person and (person == address or person in name or person in address.partition("@")[0]):
            return True
    return False


def words(start: date, end: date, now: list[dict], before: list[dict], own: set[str], *,
          company: str = "", person: str = "") -> str:
    if company or person:
        mine = [m for m in now if _matches(m, company, person)]
        then = [m for m in before if _matches(m, company, person)]
        who = company or person
        if not mine:
            return (f"No meetings with {who} on the main calendar from {_span(start, end)}"
                    + (f" ({len(then)} the span before, {_h(sum(m['hours'] for m in then))})." if then else "."))
        hours = sum(m["hours"] for m in mine)
        lines = [f"With {who}, {_span(start, end)}: {len(mine)} meeting{'s' if len(mine) != 1 else ''}, "
                 f"{_h(hours)}"
                 + (f", {_against(hours, sum(m['hours'] for m in then))}" if then else ", none the span before")
                 + " (counted from the main calendar):"]
        for m in mine:
            lines.append(f"- {m['start']:%a} {m['start'].day} {m['start']:%b} {m['start']:%H:%M}, "
                         f"{_h(m['hours'])}: {m['title']}")
        return "\n".join(lines)
    got, was = tally(now, own), tally(before, own)
    if not got["count"]:
        return f"No meetings with anybody else on the main calendar from {_span(start, end)}."
    outside = got["hours"] - got["inside_hours"]
    lines = [f"Meetings, {_span(start, end)} (counted from the main calendar): {got['count']} meetings, "
             f"{_h(got['hours'])} in all, {_against(got['hours'], was['hours'])}.",
             f"Inside your own company: {_n(got['inside_count'], 'meeting')}, {_h(got['inside_hours'])}. "
             f"With people outside it: {_n(got['count'] - got['inside_count'], 'meeting')}, {_h(outside)}."]
    rows = sorted(got["companies"].items(), key=lambda kv: (-kv[1]["hours"], kv[0]))
    if rows:
        lines.append("By company, the most time first:")
    for name, row in rows[:SHOWN]:
        people = sorted(row["people"].items(), key=lambda kv: -kv[1])
        then = was["companies"].get(name, {}).get("hours", 0.0)
        lines.append(f"- {name}: {_h(row['hours'])} in {row['count']} meeting{'s' if row['count'] != 1 else ''}"
                     f" ({_against(row['hours'], then)}), with "
                     + ", ".join(p for p, _n in people[:5]) + (" and others" if len(people) > 5 else ""))
    if len(rows) > SHOWN:
        rest = sum(r["hours"] for _n, r in rows[SHOWN:])
        lines.append(f"- {len(rows) - SHOWN} other companies: {_h(rest)} in all")
    gone = [n for n in was["companies"] if n not in got["companies"] and was["companies"][n]["hours"] >= 1]
    if gone:
        lines.append("Met the span before, and not in this one: " + ", ".join(sorted(gone)[:8]) + ".")
    return "\n".join(lines)


async def read(calendar, start: date, end: date, zone) -> list[dict]:
    """Every meeting from the start of one day to the end of another, two weeks at a time."""
    out: list[dict] = []
    day = start
    while day <= end:
        last = min(end, day + timedelta(days=PIECE - 1))
        a = datetime.combine(day, time(0), zone)
        b = datetime.combine(last + timedelta(days=1), time(0), zone)
        got = await calendar.events(a, b, calendar_ids=["primary"], limit=250)
        out.extend(got.get("events") or [])
        day = last + timedelta(days=1)
    return meetings(out)


async def answer(google, args: dict, today: date, zone, own_address: str) -> tuple[str, dict]:
    """(what to say, {read, meetings}) for one call of the tool."""
    span = span_of(args or {}, today)
    if isinstance(span, str):
        return span, {}
    start, end = span
    length = (end - start).days + 1
    calendar = google.services().calendar
    now = await read(calendar, start, end, zone)
    before = await read(calendar, start - timedelta(days=length), start - timedelta(days=1), zone)
    own = {company_of(own_address)} if own_address and company_of(own_address) != own_address.lower() else set()
    company = str(args.get("company") or "").strip().lower()
    person = str(args.get("person") or "").strip().lower()
    return words(start, end, now, before, own, company=company, person=person), \
        {"read": True, "meetings": len(now)}


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "company_of", "meetings",
           "on", "span_of", "tally", "words"]
