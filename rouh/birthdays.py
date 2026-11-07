"""The morning brief's Birthdays: who had one yesterday, who has one today and tomorrow.

Petar, 30 September 2026 (fr_d3ea4a374d50): "in my morning brief, add a
section right before the doodle, "Birthdays" and display birthday people from
my contacts for three clearly visible and separate sections: yesterday, today,
tomorrow, and I want to have tomorrow be bigger and different, the other two
more indented and maybe slightly darker. Also if the people having birthdays
are not linked to contacts, give me a button to a modal that picks the right
person so you can link them. Once linked, replace the generic contactless
birthday event with the full name and company of the contact."

Today is the one made most of, bigger and on a card of its own, with yesterday
and tomorrow indented and quieter either side of it: Petar first asked for
tomorrow to be the big one, then the same day, once he saw it, "today needs to
be highlighted not tomorrow" (`briefpage.js`).

A birthday is found in two places, and each person is said once:

1. **His contacts.** Every iCloud card with a birthday on it (`synapse/contacts.py`,
   the `birthday` column), shown as the contact: the full name and the company.
2. **His calendars.** Every all-day event on a calendar named for birthdays
   (his is "Bdays", some sixty years' worth of "Sam Bday"), every event Google
   itself marks as a birthday, and an all-day event anywhere else whose title
   says birthday. An event is tied to a contact when he linked it here
   (`BirthdayLink`), or when Rouh put it there from the contact
   (`rouhContactUid` in the event's private properties), or when its title,
   less the word birthday, is the name of a contact whose card has a birthday
   on the same day. A tied event is the contact; the rest are shown as the
   event says it, with Link contact beside them.

A contact and an event that are the same person on the same day are one line.

**Whose.** Every contact and every link is read with both the person's
`user_id` and `org_id` (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime, timedelta

from . import vcard

log = logging.getLogger("rouh.birthdays")

#: What the section's source is called at the right of its heading.
SOURCE = "Your contacts and Google Calendar"

#: The three days, in the order the page draws them.
DAYS = (("yesterday", "Yesterday", -1), ("today", "Today", 0), ("tomorrow", "Tomorrow", 1))

#: A calendar kept for birthdays, by its name: every all-day event on it is one.
BIRTHDAY_CALENDAR = re.compile(r"(?i)(b-?days?\b|birth ?days?|рожден)")

#: The words in an event's title that say it is a birthday, taken off to leave the name.
BIRTHDAY_WORDS = re.compile(
    r"(?i)(?:'s)?\s*(?:\b(?:b-?day|birth ?day)\b!*|\b(?:рожден(?:ия)?|rozhden)\s+den\b"
    r"|\bрожден(?:ия)?\s+ден\b|\b(?:rd|рд)\b)")

#: The most contacts a search in the picker answers with.
MOST_FOUND = 20

#: The most events three days of calendars are asked for.
MOST_EVENTS = 200


class Refused(ValueError):
    """Something the person asked for that cannot be done, said in their words."""


# --- days and ages ---------------------------------------------------------------------------


def month_day(birthday: str) -> tuple[int, int] | None:
    """The month and day of "1985-03-12" or "--03-12", or None."""
    found = re.match(r"^(?:\d{4}|-)-(\d{2})-(\d{2})$", (birthday or "").strip())
    if not found:
        return None
    month, day = int(found.group(1)), int(found.group(2))
    return (month, day) if 1 <= month <= 12 and 1 <= day <= 31 else None


def falls_on(birthday: str, day: date) -> bool:
    """Whether a birthday is on this day this year. The 29th of February is the 28th in
    a year without one."""
    md = month_day(birthday)
    if md is None:
        return False
    if md == (2, 29) and not _leap(day.year):
        md = (2, 28)
    return md == (day.month, day.day)


def _leap(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def age_on(birthday: str, day: date) -> int | None:
    """How old somebody born on that birthday is on that day, when the year is known."""
    found = re.match(r"^(\d{4})-", (birthday or "").strip())
    if not found:
        return None
    age = day.year - int(found.group(1))
    return age if 0 < age < 130 else None


def name_in(title: str) -> str:
    """The name in a birthday event's title: "Sam Rivera Bday" is "Sam Rivera"."""
    name = BIRTHDAY_WORDS.sub(" ", title or "")
    return " ".join(name.replace("’s ", " ").split()).strip(" -–:,!")


def is_birthday(event: dict) -> bool:
    """Whether a calendar event is somebody's birthday."""
    if event.get("kind") == "birthday":
        return True
    if not event.get("all_day"):
        return False
    return bool(BIRTHDAY_CALENDAR.search(event.get("calendar") or "")
                or BIRTHDAY_WORDS.search(event.get("title") or ""))


def event_key(event: dict) -> str:
    """What a birthday event is linked by: its series, so every year is the one link."""
    return str(event.get("series") or event.get("id") or "")


# --- contacts --------------------------------------------------------------------------------


def _contacts_with_birthdays(who) -> list[dict]:
    from .synapse import contacts

    return contacts.all_cards(str(who.user_id), who.org_id or "", with_birthday=True)


def _contacts_by_uid(who, uids) -> dict[str, dict]:
    from .synapse import contacts

    uids = {u for u in uids if u}
    if not uids:
        return {}
    return {row["uid"]: row for row in contacts.all_cards(str(who.user_id), who.org_id or "")
            if row["uid"] in uids}


def _connected(who) -> bool:
    from .models import AppleConnection

    return AppleConnection.objects.filter(user_id=str(who.user_id),
                                          org_id=who.org_id or "").exists()


def _links(who) -> dict[tuple[str, str], str]:
    from .models import BirthdayLink

    rows = BirthdayLink.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "")
    return {(row.calendar_id, row.event_key): row.contact_uid for row in rows}


def find_contacts(who, query: str) -> list[dict]:
    """The contacts the picker offers for a few words, best first."""
    from .synapse import contacts

    found = contacts.search(str(who.user_id), who.org_id or "", query or "", limit=MOST_FOUND)
    return [{"id": row["id"], "name": row["name"], "company": row["organisation"],
             "birthday": vcard.birthday_words(row["birthday"]) if row["birthday"] else "",
             "email": (row["emails"][0]["address"] if row["emails"] else "")}
            for row in found]


# --- linking ---------------------------------------------------------------------------------


def link(who, *, calendar_id, event_key, contact_id, title: str = "") -> dict:
    """Tie a birthday event to one of the person's contacts, for this year and every other.

    The contact is looked up with both ids, so a contact of somebody else's is
    "not found" rather than linked. Returns the contact it was tied to.
    """
    from .models import BirthdayLink
    from .synapse import contacts

    calendar_id, event_key = _ids(calendar_id, event_key)
    if not str(contact_id or "").strip():
        raise Refused("Pick one of your contacts to link it to.")
    contact = contacts.one(str(who.user_id), who.org_id or "", contact_id)
    if contact is None or not contact["uid"]:
        raise Refused("That contact is not in your contacts any more. Pick another.")
    BirthdayLink.objects.update_or_create(
        user_id=str(who.user_id), org_id=who.org_id or "", calendar_id=calendar_id,
        event_key=event_key,
        defaults={"contact_uid": contact["uid"], "title": str(title or "")[:300],
                  "linked_at": time.time()})
    log.info("user %s linked a birthday on their calendar to a contact", who.user_id)
    return contact


def unlink(who, *, calendar_id, event_key) -> bool:
    """Take a link away, so the event is shown as it says itself again."""
    from .models import BirthdayLink

    calendar_id, event_key = _ids(calendar_id, event_key)
    gone, _ = BirthdayLink.objects.filter(
        user_id=str(who.user_id), org_id=who.org_id or "", calendar_id=calendar_id,
        event_key=event_key).delete()
    return bool(gone)


def _ids(calendar_id, event_key) -> tuple[str, str]:
    calendar_id, event_key = str(calendar_id or "").strip(), str(event_key or "").strip()
    if not calendar_id or not event_key or len(calendar_id) > 300 or len(event_key) > 300:
        raise Refused("That birthday is not one the brief can find.")
    return calendar_id, event_key


# --- the section -----------------------------------------------------------------------------


def _from_contact(row: dict, day: date) -> dict:
    return {"name": row["name"], "company": row["organisation"],
            "age": age_on(row["birthday"], day), "contact_id": row["id"],
            "contact_uid": row["uid"], "linked": "contact", "guess": "",
            "title": "", "calendar": "", "calendar_id": "", "event_key": "", "link": ""}


def _from_event(event: dict) -> dict:
    return {"name": "", "company": "", "age": None, "contact_id": None, "contact_uid": "",
            "linked": "", "title": event.get("title") or "", "guess": name_in(event.get("title")),
            "calendar": event.get("calendar") or "", "calendar_id": event.get("calendar_id") or "",
            "event_key": event_key(event), "link": event.get("link") or ""}


def _event_day(event: dict, zone) -> date | None:
    start = event.get("start")
    if isinstance(start, datetime):
        return start.astimezone(zone).date()
    return start if isinstance(start, date) else None


def gather(who, today: date, events: list[dict] | None, zone=None) -> dict:
    """The three days' birthdays out of the contacts and the calendar events given.

    `events` is what Google gave for yesterday to tomorrow (`google_api`'s
    shape, with `start` a date or a moment), or None when the calendar could
    not be read. `zone` is the clock a moment's day is read on.
    """
    days = {key: today + timedelta(days=gap) for key, _words, gap in DAYS}
    contacts = _contacts_with_birthdays(who)
    links = _links(who)
    found: dict[str, list[dict]] = {key: [] for key in days}

    # The contacts first: each is the whole of what is known of that person.
    for key, day in days.items():
        for row in contacts:
            if falls_on(row["birthday"], day):
                found[key].append(_from_contact(row, day))

    birthdays = [one for one in events or [] if is_birthday(one)]
    wanted = [links.get((one.get("calendar_id") or "", event_key(one)))
              or one.get("contact_uid") or "" for one in birthdays]
    tied = _contacts_by_uid(who, wanted)
    for one, uid in zip(birthdays, wanted):
        day = _event_day(one, zone)
        key = next((k for k, d in days.items() if d == day), None)
        if key is None:
            continue
        entry = _from_event(one)
        people = found[key]
        contact = tied.get(uid)
        how = "you" if (one.get("calendar_id") or "", event_key(one)) in links else "rouh"
        if contact is None:
            # Its title, less "Bday", is the name of a contact whose card says
            # it is their birthday today: the same person, said once.
            guess = vcard.normalise(entry["guess"])
            same = [p for p in people if p["contact_uid"] and guess
                    and vcard.normalise(p["name"]) == guess]
            if len(same) == 1:
                contact = {"uid": same[0]["contact_uid"]}
                how = "name"
        if contact is not None:
            already = next((p for p in people if p["contact_uid"] == contact["uid"]), None)
            if already is None:
                already = _from_contact(contact, days[key])
                people.append(already)
            # The event stays behind it, so a link he made can be changed.
            already.update({"title": entry["title"], "calendar": entry["calendar"],
                            "calendar_id": entry["calendar_id"], "event_key": entry["event_key"],
                            "link": entry["link"]})
            if how == "you":
                already["linked"] = "you"
            continue
        # The same untied event twice (one calendar shared twice) is one line.
        if any(not p["contact_uid"] and p["title"].lower() == entry["title"].lower()
               for p in people):
            continue
        people.append(entry)

    out = []
    for key, words, _gap in DAYS:
        day = days[key]
        # The people he has as contacts first, then the events still to link.
        people = sorted(found[key], key=lambda p: (not p["contact_uid"],
                                                   vcard.normalise(p["name"] or p["guess"])))
        out.append({"key": key, "words": words, "date": day.isoformat(),
                    "date_words": f"{day.strftime('%A')} {day.day} {day.strftime('%B')}",
                    "people": people})
    return {"ok": True, "days": out}


async def make(who, services, today: date, zone) -> dict:
    """The brief's Birthdays part: the contacts, and the calendar when it can be read."""
    from asgiref.sync import sync_to_async

    notes: list[str] = []
    events: list[dict] | None = None
    if services is None:
        notes.append("Google is not connected, so only the birthdays on your contacts are here.")
    else:
        first = datetime(today.year, today.month, today.day, tzinfo=zone) - timedelta(days=1)
        try:
            got = await services.calendar.events(first, first + timedelta(days=3),
                                                 limit=MOST_EVENTS)
            events = list(got.get("events") or [])
        except Exception as exc:
            from .morning_brief import _google_trouble

            notes.append(_google_trouble(exc, "calendar's birthdays"))

    def work() -> dict:
        part = gather(who, today, events, zone)
        part["contacts"] = _connected(who)
        return part

    part = await sync_to_async(work)()
    if not part["contacts"]:
        notes.append("Apple Contacts is not connected, so birthdays are only read from your "
                     "calendar. Connect it in Settings to link them to people.")
    part["notes"] = notes
    part["source"] = SOURCE
    return part
