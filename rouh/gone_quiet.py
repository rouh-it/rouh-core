"""Gone quiet: the companies and people ‹he› met regularly who have stopped meeting ‹him›, with nothing
booked, said in the morning brief.

Built by the nightly feature run, night 36 (8 November 2026, task 94), from INC-512. A client met
every week or two who has had no meeting for twice as long, with nothing in the calendar ahead, is a
relationship cooling, and nothing says so: the calendar shows the meetings there are, never the ones
that stopped happening, and nobody tells ‹him› a meeting did not happen. Finding it meant reading
months of calendar back, company by company, which nobody does.

So, while its switch is on, the morning brief has a section **Gone quiet**, worked out afresh from
Google each time the page opens, with no model:

- **Who.** ‹His› main calendar's meetings of the last `DAYS` days (timed, somebody else on them, not
  declined: `meeting_hours.meetings`), by company: a guest's address's domain, or the address itself
  for free mail, ‹his› own company left out. A company is regular when ‹he› met it on at least
  `LEAST` different days and its usual gap (the middle of the gaps between those days) is at most
  `MOST_GAP` days.
- **Gone quiet.** Its last meeting is longer ago than twice its usual gap, and at least `LEAST_QUIET`
  days, and nothing with anybody of it is in the calendar in the next `AHEAD` days, invitations not
  yet answered included.
- **What it says.** "Lumen: you met every 11 days, 9 times since 12 May; the last was 52 days ago, on
  Friday 18 September, with Kai Novak." The meetings themselves, newest first, are
  in a toggle closed at first (When you met).
- **Write to them** opens ‹his› own Gmail with a new email to the people ‹he› last met there, nothing
  written in it; **Not now** puts the line away, with Undo, until a new meeting with them happens.

**Whose.** The connected Google account's main calendar (`org_id` and `user_id`) and ‹his› own
settings (`user_settings`, `gone_quiet`).

**Its switch** is `gone_quiet` (`rouh/switches.py`): off, the section is not there and the route
refuses.
"""
from __future__ import annotations

import json
import logging
import statistics
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

log = logging.getLogger("rouh.gone_quiet")

SWITCH = "gone_quiet"
TITLE = ("Gone quiet: the morning brief names the companies and people you met regularly who have "
         "stopped meeting you, with nothing booked")
#: The person's own setting: {line key: {"put": seconds}}.
KEPT = "gone_quiet"
#: How far back the calendar is read, and how far ahead a booking counts, in days.
DAYS = 180
AHEAD = 60
#: Met on at least this many different days, and usually no more than this many days apart.
LEAST = 3
MOST_GAP = 45
#: Never quiet before this many days, whatever its rhythm.
LEAST_QUIET = 21
#: How many lines are said, and how many meetings each toggle lists.
MOST = 5
LISTED = 6
ACTS = ("put", "undo", "wrote")


class Refused(ValueError):
    """What cannot be done with a line, in a sentence."""


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


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

    # A line put away longer ago than the calendar is read is let go, so the setting never grows.
    cut = time.time() - DAYS * 86400
    held = {k: v for k, v in held.items() if float(v.get("put") or 0) > cut}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def key_of(company: str, last: date) -> str:
    """A line's key: the company and its last meeting, so a new meeting brings a put line back."""
    return f"q-{company}|{last.isoformat()}"[:120]


def _gap_words(days: float) -> str:
    whole = int(round(days))
    if whole == 7:
        return "every week"
    if whole == 14:
        return "every two weeks"
    if whole % 7 == 0 and whole <= 42:
        return f"every {whole // 7} weeks"
    return f"every {whole} days"


def quiet(past: list[dict], ahead: list[dict], own: set[str], today: date, zone) -> list[dict]:
    """The companies gone quiet, the longest past their rhythm first.

    `past` and `ahead` are meetings as `meeting_hours.meetings` gives them."""
    from .meeting_hours import company_of

    booked: set[str] = set()
    for one in ahead:
        for g in one["guests"]:
            booked.add(company_of(g["email"]))
    seen: dict[str, dict] = {}
    for one in past:
        day = one["start"].astimezone(zone).date()
        if day >= today:
            continue
        for company in {company_of(g["email"]) for g in one["guests"]}:
            if company in own:
                continue
            row = seen.setdefault(company, {"days": set(), "meetings": [], "people": {}})
            row["days"].add(day)
            row["meetings"].append(one)
    out = []
    for company, row in seen.items():
        days = sorted(row["days"])
        if len(days) < LEAST or company in booked:
            continue
        gaps = [(b - a).days for a, b in zip(days, days[1:])]
        usual = statistics.median(gaps)
        if usual > MOST_GAP:
            continue
        silent = (today - days[-1]).days
        if silent < max(2 * usual, LEAST_QUIET):
            continue
        meetings = sorted(row["meetings"], key=lambda m: m["start"], reverse=True)
        last = meetings[0]
        last_people = [g for g in last["guests"] if company_of(g["email"]) == company]
        listed = []
        for m in meetings[:LISTED]:
            local = m["start"].astimezone(zone)
            names = [g.get("name") or g["email"] for g in m["guests"] if company_of(g["email"]) == company]
            listed.append({"when": f"{local:%a} {local.day} {local:%b}", "title": m["title"],
                           "people": names})
        first = days[0]
        out.append({
            "key": key_of(company, days[-1]),
            "company": company,
            "times": len(days),
            "usual": usual,
            "rhythm": _gap_words(usual),
            "since": f"{first.day} {first:%B}",
            "silent": silent,
            "last": f"{days[-1]:%A} {days[-1].day} {days[-1]:%B}",
            "last_title": last["title"],
            "people": [g.get("name") or g["email"] for g in last_people],
            "write": "https://mail.google.com/mail/?view=cm&fs=1&to="
                     + quote(",".join(g["email"] for g in last_people), safe="@,"),
            "meetings": listed,
            "over": silent / usual if usual else silent,
        })
    out.sort(key=lambda r: -r["over"])
    return out


def said(row: dict) -> str:
    """One line, in plain words."""
    people = row["people"]
    who = people[0] if len(people) == 1 else (", ".join(people[:-1]) + " and " + people[-1]) if people else ""
    return (f"You met {row['rhythm']}, {row['times']} times since {row['since']}; the last was "
            f"{row['silent']} days ago, on {row['last']}" + (f", with {who}" if who else "")
            + ".")


async def found(who, google, *, now: datetime | None = None) -> dict | None:
    """{items, count} for the brief, or None when there is nothing to say."""
    from asgiref.sync import sync_to_async

    from . import clock, meeting_hours

    if google is None:
        return None
    services = google(who)
    if services is None:
        return None
    calendar = services.calendar
    zone = clock.zone_of(who)
    now = (now or datetime.now().astimezone()).astimezone(zone)
    today = now.date()
    past = await meeting_hours.read(calendar, today - timedelta(days=DAYS), today - timedelta(days=1), zone)
    ahead = await meeting_hours.read(calendar, today, today + timedelta(days=AHEAD), zone)
    me = str((await calendar.about("primary")).get("id") or getattr(who, "email", "") or "")
    mine = meeting_hours.company_of(me) if "@" in me else ""
    own = {mine} if mine and mine != me.lower() else set()
    rows = quiet(past, ahead, own, today, zone)
    held = await sync_to_async(kept)(who)
    rows = [r for r in rows if not held.get(r["key"])]
    if not rows:
        return None
    return {"items": [dict(r, said=said(r)) for r in rows[:MOST]], "count": len(rows)}


async def again(who, brief: dict, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("gone_quiet", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("who has gone quiet could not be worked out")
        return
    if got:
        from . import evolution

        brief["gone_quiet"] = {"ok": True, "source": "Calendar", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} gone quiet")


def act(who, key: str, what: str) -> dict:
    """Not now (put away), Undo, or Write to them pressed (counted; the page opens Gmail itself)."""
    from . import evolution

    if what not in ACTS or not key.startswith("q-"):
        raise Refused("Which line, and what to do with it.")
    held = kept(who)
    if what == "put":
        held[key] = {"put": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "put", who=who, detail="put a company that has gone quiet away")
    elif what == "undo":
        if held.pop(key, None) is not None:
            _keep(who, held)
    else:
        evolution.used(SWITCH, "wrote", who=who, detail="opened an email to a company that has gone quiet")
    return {"ok": True}


__all__ = ["ACTS", "KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found", "key_of", "on", "quiet",
           "said"]
