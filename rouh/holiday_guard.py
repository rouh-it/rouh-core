"""Not booked on a guest's public holiday: a meeting with a guest abroad is not booked on a day that is
a public holiday in their country without saying so.

Built by the nightly feature run, night 36 (Rouh's brief called it night 35), 7 November 2026 (task
94). "Book a call with Marta on the 11th" was booked as said: the invitation went out, and the 11th
of November is Poland's Independence Day, a day off there. The first anybody knew was her decline,
or no answer at all, and a second round of invitations. Rouh already checks a guest's busy times,
their automatic reply and their night before it books (`busy_guard`, `away_replies`,
`their_hours`); it never checked their holidays, though night 34 gave it Google's own holiday
calendars (`rouh/public_holidays.py`).

So, while its switch is on, before create_calendar_event books an event with guests, each guest's
country is read from their address's country domain (`marta@firma.pl` is Poland, `x@agency.de`
Germany, `.co.uk` and `.uk` the United Kingdom), and Google's public holiday calendar for that
country is read for the day of the meeting. When it is a public holiday there, nothing is booked and
nobody is emailed: Rouh says whose holiday it is and its name, so the person picks another day in a
word, or says to book it anyway (`even_on_holiday`). An observance, a day Google marks that is not a
day off, does not stop it.

A guest at a domain with no country (.com, .org, .io), or in the person's own company's domain, is
not checked. No model is asked; nothing is kept.

**Whose.** Read with the person's own Google connection (`org_id` and `user_id`); a holiday
calendar is public, the same for everybody.

**Its switch** is `holiday_guard` (`rouh/switches.py`): off, a meeting is booked as asked.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from . import public_holidays

log = logging.getLogger("rouh.holiday_guard")

SWITCH = "holiday_guard"
TITLE = "Not booked on a guest's public holiday: a meeting is not booked on a day off in a guest's country"

FIELD = {"type": "boolean",
         "description": "Book it on the day asked although it is a public holiday in a guest's country: only "
                        "when the person says so after being told."}

#: Country domains that are not the country's two-letter code.
DOMAINS = {"uk": "gb"}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def country_of(address: str) -> str:
    """The two-letter code of the country an address's domain belongs to, or ""."""
    domain = str(address or "").rpartition("@")[2].strip().lower().rstrip(".")
    if "." not in domain:
        return ""
    last = domain.rsplit(".", 1)[1]
    code = DOMAINS.get(last, last)
    return code if code in public_holidays.COUNTRIES else ""


def countries(guests, own: list[str]) -> dict[str, list[str]]:
    """{country code: [guests]} for the guests whose domain says a country, the person's own
    domains and their own addresses aside."""
    mine = {str(a or "").lower() for a in own if a}
    domains = {a.rpartition("@")[2] for a in mine if "@" in a}
    out: dict[str, list[str]] = {}
    for one in guests or []:
        address = str(one or "").strip()
        low = address.lower()
        if "@" not in low or low in mine or low.rpartition("@")[2] in domains:
            continue
        code = country_of(low)
        if code:
            out.setdefault(code, []).append(address)
    return out


def _name(code: str) -> str:
    names = public_holidays.COUNTRIES[code][1]
    first = names[0]
    return first.upper() if first in ("uk", "usa") else first.title()


async def read(calendar, code: str, day: date) -> list[dict]:
    """The public holidays of one country on one day, from Google's calendar for it."""
    for one in public_holidays.calendar_ids(code):
        try:
            items = await calendar.holiday_events(one, day, day + timedelta(days=1))
        except Exception as exc:  # noqa: BLE001 - the next id it goes by is tried
            log.info("the holiday calendar %s could not be read: %s", one, exc)
            continue
        return [h for h in public_holidays.holidays_of(items)
                if h["public"] and h["day"] <= day <= h["last"]]
    return []


async def check(calendar, guests, start, zone, *, own: list[str]) -> str:
    """Why not, when the meeting's day is a public holiday in a guest's country; "" otherwise."""
    if isinstance(start, datetime):
        day = start.astimezone(zone).date() if start.tzinfo else start.date()
    elif isinstance(start, date):
        day = start
    else:
        return ""
    found = []
    for code, people in countries(guests, own).items():
        days = await read(calendar, code, day)
        if days:
            found.append((code, people, days))
    if not found:
        return ""
    when = f"{day:%A} {day.day} {day:%B}"
    said = "; ".join(
        f"{when} is {', '.join(h['name'] for h in days)}, a public holiday in "
        f"{_name(code)}, where {', '.join(people)} {'is' if len(people) == 1 else 'are'}"
        for code, people, days in found)
    return (f"Not booked, and nobody was emailed: {said} (read from Google's public holiday calendar, "
            "and from the country of each address's domain). Ask the person for another day, or book "
            "it on this day with even_on_holiday if they say so.")


__all__ = ["FIELD", "SWITCH", "TITLE", "check", "countries", "country_of", "on", "read"]
