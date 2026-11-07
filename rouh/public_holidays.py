"""Public holidays read from Google: which days are public holidays in a country, from Google's own
holiday calendars, rather than from what a model remembers.

Built by the nightly feature run, night 34, 6 November 2026 (task 94). Planning with people in
another country, or around Bulgaria's own moving days (Orthodox Easter, a holiday that falls on a
weekend and moves to the Monday), Rouh answered "is the 24th a holiday in Poland?" or "what
holidays does Germany have in December?" from the model's memory, which can be a year out of date
and does not know a day a government moved. Google keeps a public holiday calendar for every
country, the one Google Calendar shows under "Holidays in ...", at
`<language>.<country>#holiday@group.v.calendar.google.com`; Rouh's Google connection can read it.

So, while its switch is on, the tool `public_holidays` takes a country (a name, in English or
Bulgarian, or its two-letter code) and a day or a span of days, and says each holiday in it on that
day, marking the days that are public holidays apart from the ones Google lists only as
observances (a day marked but not off work), and, given one day, whether it is a holiday there.
Nothing is added to ‹his› calendar list, nothing is kept, and no model is asked.

**Whose.** Read with the person's own Google connection (`org_id` and `user_id`); a holiday
calendar is public, the same for everybody.

**Its switch** is `public_holidays` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

log = logging.getLogger("rouh.public_holidays")

SWITCH = "public_holidays"
TITLE = "Public holidays read from Google: a country's public holidays from Google's own holiday calendars"
TOOL_NAME = "public_holidays"
#: The longest span read at once, in days.
MOST_DAYS = 400

DESCRIPTION = (
    "Which days are public holidays in a country, read from Google's own public holiday calendar "
    "for it (the one Google Calendar shows as Holidays in ...), never from memory. Give `country` "
    "(a name or its two-letter code) and either `date` (one day: is it a holiday there?) or "
    "`from` and `to` (every holiday in that span, at most about a year). Use it before proposing "
    "or booking a date with people in another country, or when asked whether a day is a holiday "
    "or a working day. It says public holidays apart from observances, which are marked but are "
    "not days off. Dates are YYYY-MM-DD.")

SCHEMA = {
    "type": "object",
    "properties": {
        "country": {"type": "string", "description": "The country: a name (Poland, Германия) or a "
                                                     "two-letter code (PL)."},
        "date": {"type": "string", "description": "One day, YYYY-MM-DD: is it a holiday there?"},
        "from": {"type": "string", "description": "The first day of a span, YYYY-MM-DD."},
        "to": {"type": "string", "description": "The last day of a span, YYYY-MM-DD."},
    },
    "required": ["country"],
}

#: Two-letter code -> the older name Google's holiday calendars also go by, and other names for it.
COUNTRIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "bg": ("bulgarian", ("bulgaria", "българия")),
    "pl": ("polish", ("poland", "полша")),
    "de": ("german", ("germany", "германия", "deutschland")),
    "gb": ("uk", ("united kingdom", "uk", "britain", "great britain", "england", "великобритания",
                  "англия")),
    "us": ("usa", ("united states", "usa", "us", "america", "сащ", "америка")),
    "fr": ("french", ("france", "франция")),
    "it": ("italian", ("italy", "италия")),
    "es": ("spain", ("spain", "испания")),
    "pt": ("portuguese", ("portugal", "португалия")),
    "nl": ("dutch", ("netherlands", "holland", "the netherlands", "нидерландия", "холандия")),
    "be": ("be", ("belgium", "белгия")),
    "at": ("austrian", ("austria", "австрия")),
    "ch": ("ch", ("switzerland", "швейцария")),
    "ie": ("irish", ("ireland", "ирландия")),
    "dk": ("danish", ("denmark", "дания")),
    "se": ("swedish", ("sweden", "швеция")),
    "no": ("norwegian", ("norway", "норвегия")),
    "fi": ("finnish", ("finland", "финландия")),
    "cz": ("czech", ("czechia", "czech republic", "чехия")),
    "sk": ("slovak", ("slovakia", "словакия")),
    "hu": ("hungarian", ("hungary", "унгария")),
    "ro": ("romanian", ("romania", "румъния")),
    "gr": ("greek", ("greece", "гърция")),
    "tr": ("turkish", ("turkey", "türkiye", "турция")),
    "rs": ("rs", ("serbia", "сърбия")),
    "mk": ("mk", ("north macedonia", "macedonia", "северна македония", "македония")),
    "hr": ("croatian", ("croatia", "хърватия")),
    "si": ("slovenian", ("slovenia", "словения")),
    "ua": ("ukrainian", ("ukraine", "украйна")),
    "lt": ("lithuanian", ("lithuania", "литва")),
    "lv": ("latvian", ("latvia", "латвия")),
    "ee": ("ee", ("estonia", "естония")),
    "cy": ("cy", ("cyprus", "кипър")),
    "mt": ("mt", ("malta", "малта")),
    "ca": ("canadian", ("canada", "канада")),
    "mx": ("mexican", ("mexico", "мексико")),
    "br": ("brazilian", ("brazil", "бразилия")),
    "au": ("australian", ("australia", "австралия")),
    "nz": ("new_zealand", ("new zealand", "нова зеландия")),
    "in": ("indian", ("india", "индия")),
    "jp": ("japanese", ("japan", "япония")),
    "cn": ("china", ("china", "китай")),
    "kr": ("south_korea", ("south korea", "korea", "южна корея")),
    "sg": ("singapore", ("singapore", "сингапур")),
    "ae": ("ae", ("united arab emirates", "uae", "emirates", "оае", "обединени арабски емирства")),
    "il": ("jewish", ("israel", "израел")),
    "za": ("sa", ("south africa", "южна африка")),
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def country_of(said: str) -> tuple[str, str] | None:
    """(two-letter code, the name it is said by) for what was said, or None."""
    text = " ".join(str(said or "").strip().lower().replace(".", " ").split())
    if not text:
        return None
    if text in COUNTRIES:
        return text, COUNTRIES[text][1][0].title()
    for code, (_old, names) in COUNTRIES.items():
        if text in names:
            return code, names[0].title() if names[0] not in ("uk", "usa") else names[0].upper()
    return None


def calendar_ids(code: str) -> list[str]:
    """The ids Google's holiday calendar for a country goes by, the current one first."""
    old = COUNTRIES[code][0]
    out = [f"en.{code}#holiday@group.v.calendar.google.com"]
    if old != code:
        out.append(f"en.{old}#holiday@group.v.calendar.google.com")
    return out


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def span_of(args: dict, today: date) -> tuple[date, date] | str:
    """The first and last day asked about, or why the dates cannot be read."""
    one = _day(args.get("date"))
    if args.get("date") and one is None:
        return "The date has to be written YYYY-MM-DD."
    if one:
        return one, one
    start, end = _day(args.get("from")), _day(args.get("to"))
    if (args.get("from") and start is None) or (args.get("to") and end is None):
        return "The dates have to be written YYYY-MM-DD."
    start = start or today
    end = end or (start + timedelta(days=30))
    if end < start:
        return "The last day is before the first."
    if (end - start).days > MOST_DAYS:
        return f"That is more than {MOST_DAYS} days: ask for about a year at a time."
    return start, end


def holidays_of(items: list[dict]) -> list[dict]:
    """Google's events of a holiday calendar as {day, last, name, public}, by day, once each."""
    out: dict[tuple[str, str], dict] = {}
    for raw in items:
        if raw.get("status") == "cancelled":
            continue
        start = _day((raw.get("start") or {}).get("date") or (raw.get("start") or {}).get("dateTime"))
        if start is None:
            continue
        end = _day((raw.get("end") or {}).get("date")) or start + timedelta(days=1)
        last = max(start, end - timedelta(days=1))
        name = str(raw.get("summary") or "").strip() or "A holiday"
        public = "observance" not in str(raw.get("description") or "").lower()
        out.setdefault((start.isoformat(), name), {"day": start, "last": last, "name": name,
                                                   "public": public})
    return sorted(out.values(), key=lambda h: (h["day"], not h["public"], h["name"]))


def _said(day: date) -> str:
    return f"{day:%A} {day.day} {day:%B %Y}"


def words(country: str, start: date, end: date, found: list[dict]) -> str:
    """What is said back."""
    inside = [h for h in found if h["last"] >= start and h["day"] <= end]
    if start == end:
        on_day = [h for h in inside]
        public = [h for h in on_day if h["public"]]
        weekend = start.weekday() >= 5
        if public:
            names = "; ".join(h["name"] for h in public)
            return (f"{_said(start)} is a public holiday in {country}: {names}. "
                    "(From Google's public holiday calendar.)")
        lines = [f"{_said(start)} is not a public holiday in {country}"
                 + (", though it is a weekend day" if weekend else "") + "."]
        for h in on_day:
            lines.append(f"Google marks it as an observance, not a day off: {h['name']}.")
        return " ".join(lines) + " (From Google's public holiday calendar.)"
    if not inside:
        return (f"No public holidays in {country} from {_said(start)} to {_said(end)}, by Google's "
                "public holiday calendar.")
    lines = [f"Holidays in {country} from {_said(start)} to {_said(end)}, from Google's public "
             "holiday calendar:"]
    for h in inside:
        span = _said(h["day"]) + (f" to {_said(h['last'])}" if h["last"] != h["day"] else "")
        kind = "public holiday" if h["public"] else "observance, not a day off"
        weekend = " (a weekend day)" if h["day"] == h["last"] and h["day"].weekday() >= 5 else ""
        lines.append(f"- {span}{weekend}: {h['name']}, {kind}")
    public = sum(1 for h in inside if h["public"])
    lines.append(f"{public} public holiday{'s' if public != 1 else ''} in all.")
    return "\n".join(lines)


async def answer(google, args: dict, today: date) -> tuple[str, dict]:
    """(what to say, {read: bool, holidays: n}) for one call of the tool."""
    picked = country_of(args.get("country") or "")
    if picked is None:
        return (f"Rouh does not know Google's holiday calendar for {str(args.get('country') or '')!r}. "
                "Name the country in English, or by its two-letter code."), {}
    code, country = picked
    span = span_of(args, today)
    if isinstance(span, str):
        return span, {}
    start, end = span
    calendar = google.services().calendar
    items = None
    last_error: Exception | None = None
    for one in calendar_ids(code):
        try:
            items = await calendar.holiday_events(one, start, end + timedelta(days=1))
            break
        except Exception as exc:  # noqa: BLE001 - the next id it goes by is tried
            last_error = exc
            log.info("the holiday calendar %s could not be read: %s", one, exc)
    if items is None:
        return (f"Google's holiday calendar for {country} could not be read: {last_error}"), {}
    found = holidays_of(items)
    return words(country, start, end, found), {"read": True, "holidays": len(found)}


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "calendar_ids",
           "country_of", "holidays_of", "on", "span_of", "words"]
