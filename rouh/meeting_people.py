"""Who is coming: every guest of the week's meetings, looked up on LinkedIn before the meeting.

Petar, by voice, 7 October 2026: "Can you make a feature where every person that is in the
meeting invited will be researched on LinkedIn and data will be saved in his profile in
synapse. In advance, so if I ask you about a future meeting you can with people's background
information. For example - Sam Rivera was in my meeting and I should have been able to learn
about who he is and what he does. Including a picture profile from LinkedIn, if the contact
doesn't have one."

So a pass runs over his calendar, by itself, and again whenever the calendar changes:

1. **The meetings.** Every event from now to `DAYS` ahead on every calendar Rouh's Google
   account reads (his own is shared with it), nearest first, read from Google itself
   (`google_api.Calendar.events`), because only Google gives each occurrence of a repeating
   meeting and each guest's name, answer and whether they are a room. An event he declined,
   or one that was cancelled, is passed over. So is a large group meeting - Petar, 8 October
   2026: "if there are more than twenty people, don't research them, obviously that is not
   personal and it must be some kind of training or seminar." More than `LARGE` people invited,
   him included and rooms left out, or a group or list address whose size Google does not give,
   and nobody on it is looked up or asked about (`headcount`); somebody also at a smaller
   meeting is still looked up for that one.
2. **The guests.** Everybody invited except him (`meeting_prep.own_addresses`: his account,
   the card he picked as his, his inboxes) and Rouh's own addresses, rooms and resources, group
   and list addresses, and anybody who declined (`guests_of`). Each guest is a person of his
   Synapse Master, found by address first (`People.by_address`), or made the way the calendar
   sync makes people it meets, readable by him alone.
3. **Who is left.** Nobody whose research is filled and recent (`FRESH_DAYS`), and nobody
   tried lately (`AGAIN_DAYS` for somebody unresolved or not found, `FAILED_AGAIN` after
   LinkedIn failed): the person's own record is the cache, so the same person in five
   meetings is looked up once (`due`).
4. **Found on LinkedIn**, through the same HarvestAPI search the `linkedin_search` tool uses:
   their first and last name with the organisation behind their email's domain (`org_names`:
   what his contacts at that domain say, what LinkedIn said of somebody there before, and the
   name the domain's own home page gives itself), then the name alone if that found nobody.
5. **Harvested only when sure.** Exactly one person with that name whose headline names that
   organisation, or a company the invitation names; or the one person LinkedIn itself lists
   by that name as working there now. Anything else - two people, nobody at that company, a
   name LinkedIn spells differently - harvests nobody: the person is left unresolved, with
   the candidates numbered, on their contact card with a Research button each
   (`candidates_block`), and as one question per meeting in Decisions when the meeting is
   within a day (`decision_sources.MeetingPeopleSource`). The one harvested is checked again
   against the whole profile before anything is kept (`_still_them`).
6. **Kept on the person.** A short, sourced section of the person's online research, the
   field `show_contact` and `update_contact_profile` read and write (`section_text`): their
   role and company now, where they were before, their education, where they are, what they
   are good at, the profile's address, the day and how sure the match was. Research somebody
   else wrote is never changed: the section is added below it, and a section Petar edited is
   left as he left it (`save_match`). Who they are to him is never touched. What LinkedIn said
   besides is kept in `meta.linkedin`, short, for the meeting card; no raw harvest is kept,
   because nothing else in Rouh keeps one.
7. **Their face.** When the person has no picture of their own (none on their iCloud card),
   their LinkedIn photo is fetched once and kept on this machine, under the data directory
   (`keep_photo`), because LinkedIn's picture addresses stop working within weeks. It is
   Rouh's alone: never written to iCloud, and never put over a photo the card has. The
   contact card and the meeting card draw it from `/api/people/<id>/photo`.
8. **What it costs.** HarvestAPI charges for every run of a scraper: a search is three runs
   at $0.004 each, a profile one more. At most `DAILY_CALLS` runs a day are spent (the
   setting `ROUH_MEETING_PEOPLE_DAILY_CALLS`), each one written down with what it was for in
   the `meeting_people_calls` setting and the log (`Budget`), and a person is never looked up
   twice for the same meeting.

**Whose.** Everything is read and written as the person whose calendar it is, with both ids,
in his own Master; the research and the face are his alone, and nothing here is ever sent to
anybody, put into an invitation or written to iCloud.

**Its switch** is `meeting_people` (`rouh/switches.py`): off, the pass does nothing.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import html
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin, urlsplit

from . import linkedin, owner

log = logging.getLogger("rouh.meeting_people")

#: The feature's switch (`rouh/switches.py`).
SWITCH = "meeting_people"
TITLE = ("Who is coming: the guests of the next week's meetings looked up on LinkedIn ahead of "
         "time and kept on their contact")

#: How far ahead the meetings are read, in days.
DAYS = 7
#: Research this recent is left alone, whoever wrote it.
FRESH_DAYS = 90
#: Somebody unresolved or not found is searched for again after this many days.
AGAIN_DAYS = 30
#: Somebody LinkedIn could not be asked about is tried again after this, in seconds.
FAILED_AGAIN = 6 * 3600
#: The most HarvestAPI runs spent in a day (a UTC day).
DAILY_CALLS = int(os.environ.get("ROUH_MEETING_PEOPLE_DAILY_CALLS") or 200)
#: What one run of each scraper costs, in dollars (HarvestAPI on Apify, 5 October 2026).
PRICE = {linkedin.SEARCH_ACTOR: 0.004, linkedin.PROFILE_ACTOR: 0.004}
#: How often the pass runs by itself, in seconds, and how soon after the calendar changed.
BEAT = 60 * 60
SOON = 120
#: A meeting with more people invited than this is a training or a seminar, not a meeting to
#: know the people of: nobody on it is looked up (Petar, 8 October 2026). The setting
#: `ROUH_MEETING_PEOPLE_LARGE` changes it.
LARGE = int(os.environ.get("ROUH_MEETING_PEOPLE_LARGE") or 20)
#: A meeting this close with somebody unresolved asks Petar in Decisions.
ASK_WITHIN = 24 * 3600
#: How many people are looked up at once.
AT_ONCE = 3
#: How many candidates are kept for a pick.
MOST_CANDIDATES = 8
#: A picture bigger than this is not a face.
PHOTO_MAX = 3 * 1024 * 1024

#: The settings this keeps, per person (`user_settings`).
CALLS, MEETINGS, DOMAINS = "meeting_people_calls", "meeting_people_meetings", "meeting_people_domains"
#: How many calls the log keeps.
LOG_KEPT = 400
#: How long a domain's own name is believed, in seconds.
DOMAIN_FRESH = 30 * 24 * 3600

#: Where each person stands with LinkedIn (`meta.linkedin.status`).
MATCHED, UNRESOLVED, NOBODY, NO_NAME, FAILED, NONE_OF_THEM = (
    "matched", "unresolved", "nobody", "no_name", "failed", "none_of_them")
#: Somebody met only at a large group meeting, never asked about: looked up afresh when they are
#: at a smaller one.
LARGE_MEETING = "large_meeting"

#: How a profile the owner picked is kept (`meta.linkedin.confidence`). Rows kept before
#: 20 October 2026 say "picked by Petar", read as the same.
PICKED = "picked by the owner"
PICKED_ALL = (PICKED, "picked by Petar")

#: The first line of the section this writes into the research, which is how it is found again.
SECTION_HEAD = "### LinkedIn"

#: Mail services anybody can have an address at: the domain says nothing of their company.
PUBLIC_MAIL = {
    "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
    "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "aol.com", "msn.com",
    "abv.bg", "mail.bg", "gmx.com", "gmx.net", "gmx.de", "web.de", "yandex.com", "yandex.ru",
    "zoho.com", "hey.com", "fastmail.com", "qq.com", "163.com",
}
#: A guest whose name says it is a room, a resource or equipment.
ROOM = re.compile(r"^resource\b|\b(?:resource|room|conference|boardroom|huddle|projector|"
                  r"meeting\s+space|zoom\s+room|teams\s+room)\b", re.I)
#: An address that is a calendar or a room, not a person (Google's own).
NOT_A_PERSON = re.compile(r"@(?:group|resource|import)\.calendar\.google\.com$|"
                          r"@group\.v\.calendar\.google\.com$|calendar\.google\.com$", re.I)
#: A shared mailbox rather than one person, by its part before the @: never looked up, and, unlike
#: a group or a list, no sign the meeting is large (somebody from sales@ at a call of three).
MAILBOX_LOCAL = re.compile(
    r"^(?:info|hello|contact|support|noreply|no-reply|donotreply|do-not-reply|calendar|events?|"
    r"helpdesk|help|service|services|press|careers|jobs|invoices?|payments?|billing)$", re.I)
#: An address that is a group or a list rather than one person, by its part before the @.
LIST_LOCAL = re.compile(
    r"^(?:all|team|staff|everyone|info|hello|contact|sales|support|admin|office|hr|it|ops|"
    r"marketing|finance|accounts?|accounting|billing|legal|noreply|no-reply|donotreply|"
    r"do-not-reply|calendar|events?|group|groups|list|lists|dl|distro|members|board|"
    r"management|leadership|security|helpdesk|help|service|services|press|media|careers|jobs|"
    r"partners|invoices?|payments?)$|"
    r"^(?:dl|grp|group|list|team|all|ml|everyone|staff)[._-]|[._-](?:team|group|list|all|staff|dl|everyone)$",
    re.I)
#: Words that are no part of a name to search by.
NOT_NAME = re.compile(r"^(?:mr|mrs|ms|miss|dr|prof|sir|jr|sr|ii|iii|iv|phd|mba|cpa|esq)\.?$", re.I)
#: Words that belong to the surname after them.
PARTICLES = {"van", "von", "de", "der", "den", "da", "di", "du", "le", "la", "del", "della", "dos",
             "das", "ter", "ten", "bin", "al", "el"}


# --- small things ------------------------------------------------------------------------


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _addr(value) -> str:
    return str(value or "").strip().strip("<>").lower()


def _domain(address: str) -> str:
    return address.rsplit("@", 1)[-1] if "@" in address else ""


def _fold(text) -> str:
    return linkedin._folded(str(text or "").replace("'", "").replace("’", ""))


def _compact(text) -> str:
    return _fold(text).replace(" ", "")


def _start_of(event: dict) -> datetime | None:
    start = event.get("start")
    if isinstance(start, datetime):
        return start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    if isinstance(start, date):
        return datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    return None


def event_key(event: dict) -> str:
    """One meeting, whichever calendar it was read from: its own id and when it starts."""
    start = _start_of(event)
    return f"{event.get('id') or ''}@{int(start.timestamp()) if start else ''}"


def _setting(who, name: str) -> dict:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=name)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _put(who, name: str, value: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=name,
                     value=json.dumps(value), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _today(who) -> str:
    """The day the daily limit counts, in UTC: the same day in Rouh and in a command run beside
    it, whatever time zone each believes the person is in."""
    return datetime.now(timezone.utc).date().isoformat()


def _day_said(ts: float) -> str:
    from . import clock

    when = clock.moment(ts) if ts else None
    return f"{when.day} {when:%B %Y}" if when else ""


# --- the guests ----------------------------------------------------------------------------


def skip_why(guest: dict, own: set[str]) -> str:
    """Why a guest is not looked up, or "" for one who is."""
    address = _addr(guest.get("email"))
    name = " ".join(str(guest.get("name") or "").split())
    if not address or "@" not in address:
        return "no address"
    if address in own or guest.get("this_calendar") or guest.get("me"):
        return "yours"
    if guest.get("resource") or NOT_A_PERSON.search(address) or ROOM.search(name):
        return "a room or resource"
    if MAILBOX_LOCAL.search(address.split("@", 1)[0]):
        return "a shared mailbox"
    if is_group(address, name):
        return "a group or list"
    if guest.get("response") == "declined":
        return "declined"
    return ""


def guests_of(event: dict, own: set[str]) -> tuple[list[dict], list[dict]]:
    """The guests to look up, and the ones passed over with why, each address once."""
    keep, passed, seen = [], [], set()
    for guest in event.get("guests") or []:
        address = _addr(guest.get("email"))
        if address in seen:
            continue
        seen.add(address)
        one = {"email": address, "name": " ".join(str(guest.get("name") or "").split()),
               "response": guest.get("response") or "needsAction",
               "organiser": bool(guest.get("organiser"))}
        why = skip_why(guest, own)
        (passed if why else keep).append({**one, "skip": why} if why else one)
    return keep, passed


def is_group(address: str, name: str = "") -> bool:
    """Whether an address is a group or a list rather than one person. A shared mailbox, such as
    info@, is neither (`MAILBOX_LOCAL`)."""
    local = address.split("@", 1)[0]
    if MAILBOX_LOCAL.search(local):
        return False
    return bool(LIST_LOCAL.search(local)) or address.endswith(
        ("@googlegroups.com", "@groups.google.com"))


def headcount(event: dict) -> tuple[int, str]:
    """How many people are invited, Petar included and rooms left out, and why the meeting is
    too large to look anybody up on, or "" when it is not.

    A group or list address is many people, not one: counted by the size Google gives for it
    (`additionalGuests`, `guests_omitted`), and taken as large when Google gives none.
    """
    count, why = 0, ""
    if event.get("guests_omitted"):
        why = "Google left part of the guest list out, so it is longer than it shows"
    seen = set()
    for guest in event.get("guests") or []:
        address = _addr(guest.get("email"))
        name = " ".join(str(guest.get("name") or "").split())
        if not address or address in seen:
            continue
        seen.add(address)
        if guest.get("resource") or NOT_A_PERSON.search(address) or ROOM.search(name):
            continue
        extra = max(0, int(guest.get("additional") or 0))
        if is_group(address, name):
            if extra:
                count += extra
            elif not why:
                why = f"it is sent to a group or list, {address}"
            continue
        count += 1 + extra
    if count > LARGE and not why:
        why = f"{count} people are invited"
    return count, why


def split_name(said: str) -> tuple[str, str]:
    """(first, last) out of a name as an invitation or a contact writes it, or ("", "").

    "Rivera, Sam" and "Sam Rivera" are both ("Sam", "Rivera"); a middle initial, a title
    and anything in brackets are left out; "Jan van der Berg" is ("Jan", "van der Berg").
    """
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]|<[^>]*>", " ", str(said or ""))
    text = " ".join(text.split()).strip(" ,;-|")
    if not text or "@" in text:
        return "", ""
    if text.count(",") == 1:
        last, first = (part.strip() for part in text.split(","))
        if first and last and not NOT_NAME.match(first):
            text = f"{first} {last}"
    words = [w.strip(",.") for w in text.split() if not NOT_NAME.match(w.strip(","))]
    words = [w for w in words if w]
    if len(words) > 2:
        words = [words[0]] + [w for w in words[1:-1] if len(w.rstrip(".")) > 1] + [words[-1]]
    if len(words) < 2 or not any(c.isalpha() for c in words[0] + words[-1]):
        return (words[0] if words else ""), ""
    at = len(words) - 1
    while at > 1 and words[at - 1].lower() in PARTICLES:
        at -= 1
    return words[0], " ".join(words[at:])


def name_from_address(address: str) -> tuple[str, str]:
    """(first, last) out of an address like kevin.byrne@ or kevin_byrne@, or ("", "")."""
    local = address.split("@", 1)[0]
    parts = [p for p in re.split(r"[._-]+", local) if p]
    if len(parts) < 2 or not all(p.isalpha() and len(p) > 1 for p in (parts[0], parts[-1])):
        return "", ""
    return parts[0].title(), parts[-1].title()


@dataclass
class Name:
    first: str
    last: str
    #: Other first names they may go by (the address's "donald" for "Donny").
    firsts: list[str] = field(default_factory=list)

    @property
    def whole(self) -> str:
        return f"{self.first} {self.last}".strip()


def name_of(guest: dict, person_name: str = "") -> Name:
    """The name to search LinkedIn by: the invitation's, the contact's, then the address's."""
    by_address = name_from_address(guest.get("email") or "")
    first = last = ""
    for said in (guest.get("name"), person_name):
        first, last = split_name(said or "")
        if last:
            break
    if not last:
        first, last = by_address
    if not last:
        return Name(first, "")
    firsts = [first]
    if by_address[0] and _fold(by_address[1]) in _fold(last).split() + [_compact(last)] \
            and _fold(by_address[0]) != _fold(first):
        firsts.append(by_address[0])
    return Name(first, last, firsts)


def name_matches(found: str, name: Name) -> bool:
    """Whether a name LinkedIn gave is this name: the surname whole, and a first name that is
    one of theirs or the start of one ("Bri" and "Briony", "Matt" and "Matthew")."""
    words = _fold(found).split()
    if len(words) < 2:
        return False
    last = _fold(name.last)
    if not last or not (last in " ".join(words[1:]) or _compact(name.last) in "".join(words[1:])):
        return False
    for first in name.firsts or [name.first]:
        f = _fold(first).split()[0] if _fold(first) else ""
        if not f:
            continue
        for w in words[:-1]:
            if w == f or (min(len(w), len(f)) >= 3 and (w.startswith(f) or f.startswith(w))):
                return True
    return False


# --- whose company a domain is ---------------------------------------------------------------


def mentions(text: str, names) -> str:
    """The first of `names` that `text` says, as a whole phrase, or ""."""
    hay = f" {_fold(text)} "
    tight = hay.replace(" ", "")
    for name in names:
        f = _fold(name)
        if len(f) < 3:
            continue
        if f" {f} " in hay:
            return name
        c = f.replace(" ", "")
        if len(c) >= 6 and c in tight:
            return name
    return ""


def _initials(text: str) -> str:
    return "".join(w[0] for w in _fold(text).split() if w)


def best_title_part(title: str, domain: str) -> str:
    """The part of a page's title that is the organisation's name, judged by its domain:
    "Serving Our Community for 125 Years - Example Bank" is "Example Bank" for examplebank.com."""
    label = _compact(domain.split(".")[0])
    best, score = "", 0
    for part in re.split(r"\s+[|\-\u2013\u2014:\u00b7\u2022]\s+", html.unescape(title or "")):
        part = " ".join(part.split()).strip()
        c = _compact(part.replace("&", " and "))
        if not c or len(part) > 60:
            continue
        mark = (3 if c == label or _initials(part) == label else
                2 if (len(label) >= 4 and label in c) or (len(c) >= 4 and c in label) else 0)
        if mark > score:
            best, score = part, mark
    return best


_META = r'<meta\b[^>]*?(?:property|name)\s*=\s*["\']{}["\'][^>]*?content\s*=\s*["\']([^"\']+)["\']'
_META_BACK = r'<meta\b[^>]*?content\s*=\s*["\']([^"\']+)["\'][^>]*?(?:property|name)\s*=\s*["\']{}["\']'


def name_in_page(page: str, domain: str) -> str:
    """The organisation's name as its home page gives it: og:site_name, then the title."""
    for key in ("og:site_name", "application-name"):
        for pattern in (_META, _META_BACK):
            got = re.search(pattern.format(re.escape(key)), page, re.I)
            if got:
                said = " ".join(html.unescape(got.group(1)).split())
                if 1 < len(said) <= 60:
                    return said
    title = re.search(r"<title[^>]*>([^<]{1,300})", page, re.I)
    return best_title_part(title.group(1), domain) if title else ""


async def site_name(domain: str) -> str:
    """What the home page at the domain calls itself, or "" (`name_in_page`).

    Only public addresses, every hop of a redirect checked (`picture._address_is_public`), and
    no more than the first part of the page read: a domain in an invitation is anybody's.
    """
    import httpx

    from . import picture

    for start in (f"https://{domain}/", f"https://www.{domain}/"):
        url = start
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False,
                                         headers={"User-Agent": picture.USER_AGENT,
                                                  "Accept": "text/html"}) as client:
                for _hop in range(4):
                    picture._address_is_public(urlsplit(url).hostname or "")
                    async with client.stream("GET", url) as answer:
                        if answer.status_code in (301, 302, 303, 307, 308) and \
                                answer.headers.get("location"):
                            url = urljoin(url, answer.headers["location"])
                            continue
                        if answer.status_code >= 400:
                            break
                        body = b""
                        async for chunk in answer.aiter_bytes():
                            body += chunk
                            if len(body) > 300_000:
                                break
                        said = name_in_page(body.decode("utf-8", "replace"), domain)
                        if said:
                            return said
                        break
        except Exception as exc:  # noqa: BLE001 - a home page that cannot be read names nobody
            log.info("meeting people: %s could not be read for its name: %s", start,
                     type(exc).__name__)
    return ""


def _contact_orgs(ds: dict, domain: str) -> list[str]:
    """The organisations his contacts at this domain are with, most common first."""
    from .synapse import db

    rows = db.rows(
        "SELECT meta->>'organisation' AS org, count(*) AS n FROM synapse.item WHERE dataset_id = %s "
        "AND kind = 'person' AND deleted_at IS NULL AND coalesce(meta->>'organisation', '') <> '' "
        "AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(meta->'emails', '[]'::jsonb)) e "
        "WHERE e LIKE %s) GROUP BY 1 ORDER BY 2 DESC LIMIT 5", (ds["id"], "%@" + domain))
    return [r["org"] for r in rows if r.get("org")]


async def org_names(who, ds: dict, domain: str) -> list[str]:
    """Every name the organisation behind an email domain goes by, the likeliest first.

    What LinkedIn said of somebody at the domain who was matched before, what his contacts
    there say, and what the domain's home page calls itself. Nothing for a public mail service.
    """
    if not domain or domain in PUBLIC_MAIL:
        return []
    held = await asyncio.to_thread(_setting, who, DOMAINS)
    mine = dict(held.get(domain) or {})
    if not mine.get("at") or time.time() - float(mine.get("at") or 0) > DOMAIN_FRESH:
        site = await site_name(domain)
        mine = await asyncio.to_thread(_domain_update, who, domain, {"site": site, "at": time.time()})
    contacts = await asyncio.to_thread(_contact_orgs, ds, domain)
    names = list(mine.get("learned") or []) + contacts + ([mine["site"]] if mine.get("site") else [])
    out: list[str] = []
    for one in names:
        if one and _fold(one) not in [_fold(o) for o in out]:
            out.append(one)
    return out


_domains_lock = threading.Lock()


def _domain_update(who, domain: str, fields: dict) -> dict:
    """One domain's entry with these fields changed, read and written under one lock, so two
    guests looked up at once never write over each other. The entry as it now is."""
    with _domains_lock:
        held = _setting(who, DOMAINS)
        mine = {**dict(held.get(domain) or {}), **fields}
        held[domain] = mine
        _put(who, DOMAINS, held)
    return mine


def _learn(who, domain: str, company: str) -> None:
    """The company LinkedIn gave for somebody matched at a domain, for the next one there."""
    if not domain or domain in PUBLIC_MAIL or not company:
        return
    with _domains_lock:
        held = _setting(who, DOMAINS)
        mine = dict(held.get(domain) or {})
        learned = [c for c in mine.get("learned") or [] if _fold(c) != _fold(company)]
        mine["learned"] = [company] + learned[:4]
        held[domain] = mine
        _put(who, DOMAINS, held)


def aliases(names: list[str], domain: str) -> list[str]:
    """What a headline may call the organisation: its names, and the domain's own word."""
    out = list(names)
    label = domain.split(".")[0] if domain and domain not in PUBLIC_MAIL else ""
    if len(label) >= 3 and label not in ("mail", "email", "web", "www", "info"):
        out.append(label)
    return out


def headline_company(headline: str) -> str:
    """The company a headline names after "at" or "@": "SVP at Example Bank" is Example Bank."""
    parts = re.split(r"\s+(?:at|@)\s+", str(headline or ""), flags=re.I)
    if len(parts) < 2:
        return ""
    return re.split(r"\s*[|,·•(]\s*", parts[-1])[0].strip()


def company_why(candidate: dict, names: list[str], event_text: str) -> str:
    """Why a candidate's headline puts them at the guest's organisation, or ""."""
    headline = candidate.get("headline") or ""
    hit = mentions(headline, names)
    if hit:
        company = headline_company(headline)
        return company if company and mentions(company, names) else hit
    company = headline_company(headline)
    if len(_fold(company)) >= 4 and f" {_fold(company)} " in f" {_fold(event_text)} ":
        return f"{company}, named in the invitation"
    return ""


# --- the budget ------------------------------------------------------------------------------


class Budget:
    """HarvestAPI runs spent today, and what each one was for (`DAILY_CALLS`, `CALLS`)."""

    def __init__(self, who, most: int | None = None, setting: str = CALLS) -> None:
        self.who = who
        self.most = DAILY_CALLS if most is None else int(most)
        #: Where the day's count and the log are kept: this pass's own, or another's that spends
        #: through the same lookup with an allowance of its own (`meeting_contacts`).
        self.setting = setting
        self.calls = 0
        self.cost = 0.0
        #: Everything this budget spent, saved or not.
        self.spent_calls = 0
        self.spent_cost = 0.0
        self._entries: list[dict] = []
        self._held = _setting(who, setting)
        self._day = _today(who)
        if self._held.get("day") != self._day:
            self._held = {"day": self._day, "calls": 0, "cost": 0.0,
                          "log": list(self._held.get("log") or [])}

    def left(self) -> int:
        return max(0, self.most - int(self._held.get("calls") or 0) - self.calls)

    def can(self, n: int) -> bool:
        return self.left() >= n

    def spend(self, actor: str, n: int, *, person: str, name: str, why: str) -> None:
        cost = round(PRICE.get(actor, 0.004) * n, 4)
        self.calls += n
        self.cost = round(self.cost + cost, 4)
        self.spent_calls += n
        self.spent_cost = round(self.spent_cost + cost, 4)
        entry = {"at": round(time.time(), 1), "actor": actor.split("/")[-1], "runs": n,
                 "cost": cost, "person": person, "name": name, "why": why[:160]}
        self._entries.append(entry)
        log.info("meeting people: %d HarvestAPI run(s) of %s ($%.3f) for %s: %s", n, entry["actor"],
                 cost, name, why)

    def save(self) -> None:
        """What was spent, added to the day's count and the log, read again first."""
        if not self._entries:
            return
        held = _setting(self.who, self.setting)
        if held.get("day") != self._day:
            held = {"day": self._day, "calls": 0, "cost": 0.0, "log": list(held.get("log") or [])}
        held["calls"] = int(held.get("calls") or 0) + sum(e["runs"] for e in self._entries)
        held["cost"] = round(float(held.get("cost") or 0) + sum(e["cost"] for e in self._entries), 4)
        held["log"] = (list(held.get("log") or []) + self._entries)[-LOG_KEPT:]
        _put(self.who, self.setting, held)
        self._held = held
        self.calls, self._entries = 0, []


def spent_today(who) -> dict:
    held = _setting(who, CALLS)
    if held.get("day") != _today(who):
        return {"day": _today(who), "calls": 0, "cost": 0.0, "most": DAILY_CALLS}
    return {"day": held["day"], "calls": int(held.get("calls") or 0),
            "cost": float(held.get("cost") or 0), "most": DAILY_CALLS}


# --- the person ------------------------------------------------------------------------------


def _ds(who) -> dict:
    from .synapse import contacts

    return contacts.master_of(str(who.user_id), str(who.org_id))


def _row(ds: dict, pid: str, *, lock: bool = False) -> dict | None:
    from .synapse import db

    return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND kind = 'person' "
                  "AND deleted_at IS NULL" + (" FOR UPDATE" if lock else ""), (ds["id"], str(pid)))


def person_for(who, ds: dict, guest: dict, *, make: bool = True) -> dict | None:
    """The guest's person in his Master: found by their address, or made the way the calendar
    sync makes somebody it meets, readable by him alone. None for himself, and with `make` false
    a stand-in row for somebody not there yet, so a dry run makes nobody."""
    from .people import People
    from .synapse import datasets, people as synapse_people

    found = People().by_address(str(who.user_id), str(who.org_id), guest["email"])
    if any(p.is_me for p in found):
        return None
    if found:
        return _row(ds, found[0].id)
    if not make:
        return {"id": f"new:{guest['email']}", "title": guest.get("name") or guest["email"], "meta": {}}
    me = datasets.me(ds)
    first, last = split_name(guest.get("name") or "")
    name = f"{first} {last}".strip() if last else (guest.get("name") or guest["email"])
    return synapse_people.create(ds, name=name, origin="synapse", emails=[guest["email"]],
                                 readers=[me] if me else None, owner=me or "",
                                 why="a guest of a meeting on the calendar")


def due(meta: dict, now: float | None = None) -> str:
    """Why the person is not looked up now, or "" when they are."""
    now = time.time() if now is None else now
    li = meta.get("linkedin") or {}
    status = li.get("status") or ""
    at = float(li.get("at") or 0)
    if (meta.get("research") or "").strip() and \
            now - float(meta.get("researched_at") or 0) < FRESH_DAYS * 86400:
        return "researched lately"
    if status == MATCHED and now - float(li.get("harvested") or at) < FRESH_DAYS * 86400:
        return "found on LinkedIn lately"
    if status in (UNRESOLVED, NOBODY, NONE_OF_THEM) and now - at < AGAIN_DAYS * 86400:
        return {UNRESOLVED: "waiting for a pick", NOBODY: "not found lately",
                NONE_OF_THEM: "none of them, said ‹owner›"}[status]
    if status == FAILED and now - at < FAILED_AGAIN:
        return "LinkedIn failed lately"
    return ""


def has_own_photo(meta: dict) -> bool:
    """Whether the person has a picture of their own that Rouh can draw: their iCloud card's, kept
    (`contact_photos`) or carried in the card whole, or one not LinkedIn's. A card whose picture is at an
    address not fetched yet is not one, so the LinkedIn photo is still kept to fall back on."""
    if _icloud_kept(meta) or _icloud_inline(meta):
        return True
    photo = meta.get("photo") or {}
    return bool(photo.get("file")) and photo.get("source") != "linkedin"


def _icloud_inline(meta: dict) -> bool:
    vcard = str((meta.get("icloud") or {}).get("vcard") or "")
    return bool(re.search(r"(?im)^PHOTO(?:;[^:\r\n]*(?:encoding=b|base64)[^:\r\n]*:|[^:\r\n]*:data:image/)", vcard))


def _icloud_kept(meta: dict) -> str:
    """Where the face kept from the person's iCloud card is on disk (`contact_photos`), or ""."""
    return photo_path({"photo": meta.get("icloud_photo") or {}})


def icloud_photo(meta: dict) -> tuple[bytes, str] | None:
    """The picture on the person's iCloud card, when the card carries it whole, as (bytes, type)."""
    vcard = str((meta.get("icloud") or {}).get("vcard") or "")
    if not vcard:
        return None
    unfolded = re.sub(r"\r?\n[ \t]", "", vcard)
    got = re.search(r"(?im)^PHOTO((?:;[^:\r\n]*)?):(.+)$", unfolded)
    if not got:
        return None
    params, value = got.group(1).lower(), got.group(2).strip()
    kind = "image/jpeg"
    if value.lower().startswith("data:"):
        head, _, value = value.partition(",")
        kind = head[5:].split(";")[0] or kind
    elif "encoding=b" in params or "base64" in params:
        found = re.search(r"type=([a-z]+)", params)
        if found:
            kind = {"jpeg": "image/jpeg", "jpg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif"}.get(found.group(1), "image/jpeg")
    else:
        return None  # an address of a picture somewhere else, which this cannot fetch for him
    try:
        body = base64.b64decode(value, validate=False)
    except (ValueError, TypeError):
        return None
    return (body, kind) if body and kind.startswith("image/") else None


def photo_dir() -> str:
    from .config import config

    return os.path.join(config.data_dir, "people-photos")


def photo_path(meta: dict) -> str:
    """Where the face Rouh kept for the person is on disk, or "" (always under `photo_dir`)."""
    rel = str((meta.get("photo") or {}).get("file") or "")
    if not rel or ".." in rel.split("/") or rel.startswith("/"):
        return ""
    root = os.path.realpath(photo_dir())
    path = os.path.realpath(os.path.join(root, rel))
    return path if path.startswith(root + os.sep) and os.path.isfile(path) else ""


def photo_url(pid: str, meta: dict) -> str:
    """The address the person's face is drawn from, or "" when there is none: their iCloud card's
    picture first, then the LinkedIn photo research kept for them; the page draws initials otherwise."""
    kept = meta.get("icloud_photo") or {}
    if kept.get("file") and _icloud_kept(meta):
        return f"/api/people/{pid}/photo?v=i{int(float(kept.get('at') or 0))}"
    if _icloud_inline(meta):
        etag = re.sub(r"[^A-Za-z0-9]", "", str((meta.get("icloud") or {}).get("etag") or ""))[:12]
        return f"/api/people/{pid}/photo?v={etag}"
    photo = meta.get("photo") or {}
    if photo.get("file"):
        return f"/api/people/{pid}/photo?v={int(float(photo.get('at') or 0))}"
    return ""


def photo_of(who, pid: str) -> tuple[bytes, str] | None:
    """The person's face, theirs from iCloud first, else the one Rouh kept: (bytes, type)."""
    ds = _ds(who)
    row = _row(ds, pid)
    if row is None:
        return None
    meta = row.get("meta") or {}
    kept = _icloud_kept(meta)
    if kept:
        with open(kept, "rb") as fh:
            return fh.read(), "image/jpeg"
    own = icloud_photo(meta)
    if own is not None:
        return own
    path = photo_path(meta)
    if not path:
        return None
    with open(path, "rb") as fh:
        return fh.read(), str((meta.get("photo") or {}).get("type") or "image/jpeg")


async def _fetch_face(url: str) -> tuple[bytes, str]:
    """A photo's bytes and type, through `picture.fetch`, which only reaches public addresses.

    A test world's stand-in for Apify (`ROUH_APIFY_URL`, `rouh/testing/fake_apify.py`) draws its
    made-up faces itself, on this machine; a face from there is fetched as it is. On the server
    that address is Apify's own and LinkedIn's photos are on its public image host.
    """
    import httpx

    from . import picture
    from .config import config

    stand_in = str(getattr(config, "apify_url", "") or "").rstrip("/")
    if stand_in and stand_in != linkedin.APIFY_URL and url.startswith(stand_in + "/"):
        async with httpx.AsyncClient(timeout=picture.TIMEOUT) as client:
            answer = await client.get(url)
        answer.raise_for_status()
        return answer.content, (answer.headers.get("content-type") or "").split(";")[0].strip()
    return await picture.fetch(url)


async def keep_photo(who, ds: dict, pid: str, url: str) -> bool:
    """Fetch their LinkedIn photo once and keep it here, when they have no picture of their own.
    Never written to iCloud."""
    from .synapse import people as synapse_people

    if not url:
        return False
    row = await asyncio.to_thread(_row, ds, pid)
    if row is None or has_own_photo(row.get("meta") or {}):
        return False
    try:
        body, media = await _fetch_face(url)
    except Exception as exc:  # noqa: BLE001 - no face is no harm
        log.info("meeting people: a LinkedIn photo could not be fetched: %s", exc)
        return False
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif",
           "image/svg+xml": "svg"}.get(media.split(";")[0].strip().lower())
    if not ext or not body or len(body) > PHOTO_MAX:
        return False
    rel = f"{who.org_id}/{who.user_id}/{pid}-{hashlib.sha256(body).hexdigest()[:16]}.{ext}"
    path = os.path.join(photo_dir(), rel)

    def write() -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".part", "wb") as fh:
            fh.write(body)
        os.replace(path + ".part", path)
        before = photo_path(row.get("meta") or {})
        synapse_people.set_meta(str(pid), {"photo": {
            "source": "linkedin", "file": rel, "type": media.split(";")[0].strip().lower(),
            "at": time.time(), "profile": ((row.get("meta") or {}).get("linkedin") or {}).get("url", "")}})
        if before and before != os.path.realpath(path):
            with contextlib.suppress(OSError):
                os.remove(before)

    await asyncio.to_thread(write)
    return True


# --- what is written on the person -------------------------------------------------------------


def _current(data: dict) -> list[dict]:
    return [j for j in data.get("experience") or []
            if str(j.get("dates") or "").lower().endswith("present")]


def section_text(data: dict, *, confidence: str, when: float, meeting: str = "") -> str:
    """The section of the research written from a harvested profile: short, and sourced."""
    lines = [SECTION_HEAD, ""]
    if data.get("headline"):
        lines.append(f"**{linkedin._one_line(data['headline'])}**")
        lines.append("")

    def job(j: dict) -> str:
        line = ", ".join(v for v in (j.get("title"), j.get("company")) if v)
        if j.get("dates"):
            line += f" ({j['dates']})"
        return line

    now = _current(data)
    before = [j for j in data.get("experience") or [] if j not in now]
    if now:
        lines.append("- Now: " + "; ".join(job(j) for j in now[:3]))
    if before:
        lines.append("- Before: " + "; ".join(job(j) for j in before[:4]))
    if data.get("education"):
        lines.append("- Education: " + "; ".join(
            ", ".join(v for v in (s.get("degree"), s.get("school"), s.get("dates")) if v)
            for s in data["education"][:3]))
    if data.get("location"):
        lines.append(f"- Based in: {data['location']}")
    if data.get("skills"):
        lines.append("- Expertise: " + ", ".join(data["skills"][:10]))
    if data.get("about"):
        lines.append("- About, in their words: " + linkedin._shorter(linkedin._one_line(data["about"]), 400))
    lines.append("")
    source = f"Source: their public LinkedIn profile, {data.get('url') or ''}, read {_day_said(when)}"
    lines.append(source + f". Match: {confidence}." + (f" Looked up as a guest of “{meeting}”." if meeting else ""))
    return "\n".join(lines).strip()


def _readers_his(ds: dict, pid: str) -> None:
    """The person readable by him alone, when they were anybody's: their research is his."""
    from .synapse import datasets, ingest

    me = datasets.me(ds)
    if me and "everyone" in ingest.readers_of(ds["id"], pid):
        ingest.set_readers(ds["id"], pid, [me])


def save_match(who, pid: str, data: dict, *, confidence: str, meeting: str = "",
               picked: bool = False, domain: str = "") -> dict:
    """A harvested profile kept on the person: their research, and what the meeting card shows.

    Research somebody else wrote stays word for word, with this section added below it; a
    section written here before is replaced only while it reads as it was written, so one
    Petar edited, or took out, is left as he left it. Answers {"research": what became of it}.
    """
    from .people import MAX_RESEARCH
    from .synapse import contacts, db

    ds = _ds(who)
    now = time.time()
    with db.atomic():
        row = _row(ds, pid, lock=True)
        if row is None:
            return {"research": "gone"}
        meta = dict(row.get("meta") or {})
        li = dict(meta.get("linkedin") or {})
        old = str(meta.get("research") or "").strip()
        section = section_text(data, confidence=confidence, when=now, meeting=meeting)
        prev = str(li.get("section") or "")
        research, said = None, ""
        if not old:
            research, said = section, "written"
        elif prev and prev in old:
            research, said = old.replace(prev, section), "brought up to date"
        elif li.get("saved_at"):
            said = owner.say("left as ‹owner› edited it", who)
        else:
            research, said = old + "\n\n" + section, "added below what was there"
        if research is not None and len(research) > MAX_RESEARCH:
            research, said = None, "too long to add to"
        current = _current(data)
        li.update({"status": MATCHED, "url": data.get("url") or "", "slug": data.get("slug") or "",
                   "name": data.get("name") or "", "headline": data.get("headline") or "",
                   "location": data.get("location") or "",
                   "company": (current[0].get("company") if current else "") or "",
                   "title": (current[0].get("title") if current else "") or "",
                   "background": background_of(data), "confidence": confidence,
                   "picked": bool(picked), "at": now, "harvested": now, "candidates": [],
                   "why": "", "saved_at": now})
        if research is not None:
            li["section"] = section
            meta["research"] = research
            meta["researched_at"] = now
            if research == section:
                meta["research_confirmed"] = True
        meta["linkedin"] = li
        title = row["title"]
        # A name only filled in where there was none to speak of: an address, or a first name
        # alone. A full name somebody wrote is left as it is (LinkedIn's carries ", Ph.D." and the like).
        if not meta.get("icloud") and data.get("name") and ("@" in title or len(title.split()) < 2):
            title = meta["name"] = linkedin._one_line(data["name"])[:200]
        contacts.write(ds, row, meta, title, by="rouh",
                       why="LinkedIn research of a meeting guest" if not picked else
                       owner.say("LinkedIn research ‹owner› picked", who))
        _readers_his(ds, pid)
    return {"research": said}


def background_of(data: dict) -> str:
    """One line on who they are, for the meeting card: now, before, and where they studied."""
    bits = []
    now = _current(data)
    before = [j for j in data.get("experience") or [] if j not in now]
    if before:
        j = before[0]
        bits.append("before: " + ", ".join(v for v in (j.get("title"), j.get("company")) if v))
    if data.get("education"):
        s = data["education"][0]
        bits.append("studied " + ", ".join(v for v in (s.get("degree"), s.get("school")) if v))
    if data.get("skills"):
        bits.append("good at " + ", ".join(data["skills"][:3]))
    said = "; ".join(b for b in bits if b)
    return linkedin._shorter(said[:1].upper() + said[1:], 220)


def mark(who, pid: str, status: str, **fields) -> None:
    """Where the person stands with LinkedIn, without a new version of them: the cache."""
    from .synapse import people as synapse_people

    ds = _ds(who)
    row = _row(ds, pid)
    if row is None:
        return
    li = dict((row.get("meta") or {}).get("linkedin") or {})
    if li.get("status") == MATCHED and status != MATCHED:
        # Found before, and only not found again: what was found stays.
        li.update({"at": time.time(), "why": fields.get("why", "")})
    else:
        li.update({"status": status, "at": time.time(), **fields})
    synapse_people.set_meta(str(pid), {"linkedin": li})
    if status == UNRESOLVED:
        _readers_his(ds, pid)


# --- one person --------------------------------------------------------------------------------


def _still_them(data: dict, name: Name, names: list[str], event_text: str, basis: str) -> str:
    """Why the whole profile is still the person the search picked, or "" when it is not."""
    if not name_matches(data.get("name") or "", name):
        return ""
    companies = [j.get("company") or "" for j in _current(data)]
    companies += [linkedin.slug_of(j.get("company_url") or "") or "" for j in _current(data)]
    hit = next((mentions(c, names) for c in companies if c and mentions(c, names)), "")
    if not hit:
        hit = next((c for c in companies if c and len(_fold(c)) >= 4
                    and f" {_fold(c)} " in f" {_fold(event_text)} "), "")
    if hit:
        return hit
    if basis == "headline" and not _current(data) and mentions(data.get("headline") or "", names):
        return mentions(data.get("headline") or "", names)
    return ""


async def research(who, apify, budget: Budget, *, ds: dict, pid: str, guest: dict, event: dict,
                   person_name: str = "", dry: bool = False) -> dict:
    """Find one guest on LinkedIn and keep them if, and only if, it is surely them."""
    name = name_of(guest, person_name)
    out = {"pid": pid, "email": guest["email"], "name": name.whole or guest.get("name") or guest["email"]}
    if dry:
        return {**out, "status": "would look up" if name.last else NO_NAME,
                "company": (await org_names(who, ds, _domain(guest["email"])) or [""])[0]}
    if not name.last:
        await asyncio.to_thread(mark, who, pid, NO_NAME, why="no first and last name to search by")
        return {**out, "status": NO_NAME}
    domain = _domain(guest["email"])
    names = await org_names(who, ds, domain)
    known = aliases(names, domain)
    event_text = " ".join(str(event.get(k) or "") for k in ("title", "description", "where"))[:4000]
    meeting = event.get("title") or ""
    people: list[dict] = []
    filtered: set[str] = set()
    asked = name.whole

    async def ask(first: str, company: str = "") -> bool:
        nonlocal asked
        if not budget.can(linkedin.TRIES):
            return False
        try:
            found = await linkedin.search(apify, first, name.last, company=company, limit=linkedin.MOST)
        finally:
            budget.spend(linkedin.SEARCH_ACTOR, linkedin.TRIES, person=pid, name=out["name"],
                         why=f"search {first} {name.last}" + (f" at {company}" if company else ""))
        asked = found.asked
        for p in found.people:
            if p["slug"] not in {q["slug"] for q in people}:
                people.append(p)
            if company:
                filtered.add(p["slug"])
        return True

    try:
        if names and not await ask(name.first, names[0]):
            return {**out, "status": "capped"}
        if not any(name_matches(p["name"], name) for p in people):
            for first in dict.fromkeys(name.firsts):
                if not await ask(first):
                    return {**out, "status": "capped"}
                if any(name_matches(p["name"], name) for p in people):
                    break
    except linkedin.Trouble as exc:
        await asyncio.to_thread(mark, who, pid, FAILED, why=str(exc))
        return {**out, "status": FAILED, "why": str(exc)}
    named = [p for p in people if name_matches(p["name"], name)]
    hits = [(p, company_why(p, known, event_text)) for p in named]
    hits = [(p, why) for p, why in hits if why]
    chosen, basis, confidence = None, "", ""
    if len(hits) == 1:
        chosen, why = hits[0]
        basis = "headline"
        confidence = (f"confident - the name, and the headline names {why}"
                      + (f" ({domain})" if domain and domain not in PUBLIC_MAIL else ""))
    elif not hits and len(named) == 1 and named[0]["slug"] in filtered and names:
        chosen, basis = named[0], "filter"
        confidence = f"confident - the name, and LinkedIn lists {names[0]} as where they work now"
    if chosen is None:
        if not people:
            await asyncio.to_thread(mark, who, pid, NOBODY, asked=asked, candidates=[],
                                    why=f"nobody on LinkedIn by the name {name.whole}")
            return {**out, "status": NOBODY}
        why = (f"{len(hits)} people named {name.whole} whose headline names "
               f"{hits[0][1]}" if len(hits) > 1 else
               f"{len(named)} people named {name.whole}, none of them sure to be at "
               f"{names[0] if names else 'their company'}" if named else
               f"nobody named exactly {name.whole}")
        ranked = [p for p, _ in hits] + [p for p in named if p not in [h for h, _ in hits]] + \
                 [p for p in people if p not in named]
        await asyncio.to_thread(mark, who, pid, UNRESOLVED, asked=asked, why=why,
                                candidates=ranked[:MOST_CANDIDATES], meeting=meeting)
        return {**out, "status": UNRESOLVED, "why": why, "candidates": len(ranked[:MOST_CANDIDATES])}
    if not budget.can(1):
        return {**out, "status": "capped"}
    try:
        data = await linkedin.harvest(apify, chosen["url"], posts=False)
    except linkedin.NotFound as exc:
        await asyncio.to_thread(mark, who, pid, UNRESOLVED, asked=asked, why=str(exc),
                                candidates=named[:MOST_CANDIDATES], meeting=meeting)
        return {**out, "status": UNRESOLVED, "why": str(exc)}
    except linkedin.Trouble as exc:
        await asyncio.to_thread(mark, who, pid, FAILED, why=str(exc))
        return {**out, "status": FAILED, "why": str(exc)}
    finally:
        budget.spend(linkedin.PROFILE_ACTOR, 1, person=pid, name=out["name"],
                     why=f"profile {chosen['url']}")
    still = _still_them(data, name, known, event_text, basis)
    if not still:
        why = (f"the profile at {chosen['url']} did not say they work at "
               f"{names[0] if names else 'their company'} now")
        await asyncio.to_thread(mark, who, pid, UNRESOLVED, asked=asked, why=why,
                                candidates=named[:MOST_CANDIDATES] or people[:MOST_CANDIDATES],
                                meeting=meeting)
        return {**out, "status": UNRESOLVED, "why": why}
    if not data.get("photo") and chosen.get("photo"):
        data["photo"] = chosen["photo"]
    said = await asyncio.to_thread(save_match, who, pid, data, confidence=confidence,
                                   meeting=meeting, domain=domain)
    current = _current(data)
    if current and domain:
        await asyncio.to_thread(_learn, who, domain, current[0].get("company") or "")
    face = await keep_photo(who, ds, pid, data.get("photo") or "")
    return {**out, "status": MATCHED, "url": data.get("url"), "headline": data.get("headline"),
            "confidence": confidence, "research": said.get("research"), "photo": face}


# --- the pass ----------------------------------------------------------------------------------


@dataclass
class Report:
    """What one pass did, for the log, the command and the tool."""

    meetings: int = 0
    guests: int = 0
    passed: dict = field(default_factory=dict)
    left: dict = field(default_factory=dict)
    done: list = field(default_factory=list)
    #: The meetings passed over as large group meetings: {title, invited, why}.
    large: list = field(default_factory=list)
    capped: bool = False
    calls: int = 0
    cost: float = 0.0
    trouble: str = ""

    def count(self, status: str) -> int:
        return sum(1 for d in self.done if d.get("status") == status)

    def said(self) -> str:
        if self.trouble:
            return self.trouble
        bits = [f"{self.meetings} meeting{'s' if self.meetings != 1 else ''}, {self.guests} guest"
                f"{'s' if self.guests != 1 else ''} to know"]
        for status, words in ((MATCHED, "found on LinkedIn and kept"),
                              (UNRESOLVED, "need ‹owner›'s pick"), (NOBODY, "not found"),
                              (NO_NAME, "with no name to search by"), (FAILED, "failed")):
            n = self.count(status)
            if n:
                bits.append(f"{n} {words}")
        if self.left:
            bits.append(", ".join(f"{n} {why}" for why, n in sorted(self.left.items())))
        for one in self.large:
            bits.append(f"“{one['title']}” skipped as a large group meeting ({one['why']})")
        if self.capped:
            bits.append("stopped at the day's limit of HarvestAPI runs")
        bits.append(f"{self.calls} HarvestAPI runs, ${self.cost:.3f}")
        return "; ".join(bits) + "."


def _dedupe(events: list[dict]) -> list[dict]:
    """Each meeting once, nearest first, however many calendars it is on."""
    seen, out = set(), []
    for event in sorted(events, key=lambda e: (_start_of(e) or datetime.max.replace(tzinfo=timezone.utc))):
        key = event_key(event)
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return out


_running = threading.Lock()


async def run(who, *, calendar, apify, start: datetime | None = None, end: datetime | None = None,
              events: list[dict] | None = None, most: int | None = None, dry: bool = False,
              keep_meetings: bool = True, wait: bool = False) -> Report:
    """One pass over the meetings between `start` and `end` (now to `DAYS` ahead), or `events`.
    One pass at a time: with `wait`, until the one running has finished (a few minutes at most),
    else it says so and does nothing."""
    from . import meeting_prep

    report = Report()
    deadline = time.monotonic() + (300 if wait else 0)
    while not _running.acquire(blocking=False):
        if time.monotonic() >= deadline:
            report.trouble = "A pass over the meetings is already running."
            return report
        await asyncio.sleep(1)
    budget = Budget(who, most)
    try:
        if events is None:
            start = start or datetime.now(timezone.utc)
            end = end or start + timedelta(days=DAYS)
            got = await calendar.events(start, end, limit=500)
            events = got.get("events") or []
        events = [e for e in _dedupe(events) if e.get("status") != "cancelled"
                  and e.get("my_response") != "declined"]
        if not dry and (apify is None or not apify.ready()):
            report.trouble = "LinkedIn research is not set up on this machine: there is no Apify key."
            return report
        own = await asyncio.to_thread(meeting_prep.own_addresses, who)
        ds = await asyncio.to_thread(_ds, who)
        work: list[tuple[dict, dict, dict]] = []
        meetings: list[dict] = []
        taken: set[str] = set()
        for event in events:
            start_at = _start_of(event)
            count, large = headcount(event)
            if large:
                # A training or a seminar: nobody on it is looked up, nobody is asked about, and
                # whoever is also at a smaller meeting is looked up for that one.
                report.large.append({"title": event.get("title") or "", "invited": count, "why": large})
                meetings.append({"key": event_key(event), "title": event.get("title") or "",
                                 "start": start_at.timestamp() if start_at else 0,
                                 "calendar_id": event.get("calendar_id") or "",
                                 "event_id": event.get("id") or "", "people": [],
                                 "skipped": "a large group meeting", "invited": count, "why": large})
                log.info("meeting people: “%s” passed over as a large group meeting: %s",
                         event.get("title") or "", large)
                continue
            keep, passed = guests_of(event, own)
            for one in passed:
                report.passed[one["skip"]] = report.passed.get(one["skip"], 0) + 1
            if not keep:
                continue
            report.meetings += 1
            pids = []
            for guest in keep:
                row = await asyncio.to_thread(person_for, who, ds, guest, make=not dry)
                if row is None:
                    report.passed["yours"] = report.passed.get("yours", 0) + 1
                    continue
                pid = str(row["id"])
                pids.append(pid)
                if pid in taken:
                    continue
                taken.add(pid)
                report.guests += 1
                why = due(row.get("meta") or {})
                if why:
                    report.left[why] = report.left.get(why, 0) + 1
                    continue
                work.append((row, guest, event))
            meetings.append({"key": event_key(event), "title": event.get("title") or "",
                             "start": start_at.timestamp() if start_at else 0,
                             "calendar_id": event.get("calendar_id") or "", "event_id": event.get("id") or "",
                             "people": pids})
        gate = asyncio.Semaphore(AT_ONCE)

        async def one(row: dict, guest: dict, event: dict) -> dict:
            async with gate:
                if budget.left() < linkedin.TRIES:
                    return {"pid": str(row["id"]), "email": guest["email"], "status": "capped"}
                try:
                    return await research(who, apify, budget, ds=ds, pid=str(row["id"]), guest=guest,
                                          event=event, person_name=row.get("title") or "", dry=dry)
                except Exception as exc:  # noqa: BLE001 - one guest never stops the others
                    log.exception("meeting people: %s could not be looked up", guest["email"])
                    return {"pid": str(row["id"]), "email": guest["email"], "status": FAILED,
                            "why": f"{type(exc).__name__}: {exc}"}
                finally:
                    await asyncio.to_thread(budget.save)

        report.done = list(await asyncio.gather(*(one(*w) for w in work)))
        report.capped = any(d.get("status") == "capped" for d in report.done)
        report.calls, report.cost = budget.spent_calls, budget.spent_cost
        if keep_meetings and not dry:
            await asyncio.to_thread(_keep_meetings, who, meetings)
        log.info("meeting people: %s", report.said())
        return report
    finally:
        _running.release()


def _keep_meetings(who, meetings: list[dict]) -> None:
    """The coming meetings and who is at each, for Decisions (`MeetingPeopleSource`)."""
    now = time.time()
    held = _setting(who, MEETINGS).get("meetings") or []
    by_key = {m["key"]: m for m in held if float(m.get("start") or 0) > now - 3600}
    for m in meetings:
        by_key[m["key"]] = m
    _put(who, MEETINGS, {"at": now, "meetings": sorted(by_key.values(), key=lambda m: m.get("start") or 0)})


def meetings_waiting(who, now: float | None = None) -> list[dict]:
    """Each meeting within `ASK_WITHIN` that has guests waiting for Petar's pick, with them."""
    now = time.time() if now is None else now
    ds = _ds(who)
    out = []
    for m in _setting(who, MEETINGS).get("meetings") or []:
        start = float(m.get("start") or 0)
        if not (now < start <= now + ASK_WITHIN) or m.get("skipped"):
            continue
        waiting = []
        for pid in m.get("people") or []:
            row = _row(ds, pid)
            li = ((row or {}).get("meta") or {}).get("linkedin") or {}
            if row is not None and li.get("status") == UNRESOLVED and li.get("candidates"):
                waiting.append({"pid": pid, "name": row.get("title") or "", "linkedin": li,
                                "email": next(iter((row.get("meta") or {}).get("emails") or []), "")})
        if waiting:
            out.append({**m, "waiting": waiting})
    return out


# --- what is known of a meeting's guests --------------------------------------------------------


def attendee_view(who, event: dict) -> list[dict]:
    """Each guest of a meeting worth knowing, with what is kept on them: for the meeting card and
    for the model. Reads only; nobody is made or looked up here."""
    from . import meeting_prep
    from .people import People

    _count, large = headcount(event)

    own = meeting_prep.own_addresses(who)
    keep, _passed = guests_of(event, own)
    out = []
    for guest in keep:
        found = [p for p in People().by_address(str(who.user_id), str(who.org_id), guest["email"])]
        if any(p.is_me for p in found):
            continue
        person = found[0] if found else None
        li = person.linkedin if person else {}
        status = li.get("status") or ""
        name = (person.name if person else "") or name_of(guest).whole or guest["name"] or guest["email"]
        one = {"email": guest["email"], "name": name, "response": guest["response"],
               "organiser": guest["organiser"], "contact": person.id if person else "",
               "status": status, "url": li.get("url") or "", "photo": person.photo if person else "",
               "headline": li.get("headline") or (person.organisation if person else "") or "",
               "location": li.get("location") or "", "background": li.get("background") or "",
               "confidence": li.get("confidence") or "", "why": li.get("why") or "",
               "candidates": len(li.get("candidates") or []) if status == UNRESOLVED else 0,
               "relationship": person.relationship if person else "",
               "research": person.research if person else "",
               "researched": person.research_said() if person else "Not researched yet.",
               "large": bool(large)}
        out.append(one)
    return out


def note_of(one: dict) -> str:
    """The short line under a guest on the meeting card about where Rouh stands with them."""
    status = one.get("status")
    if one.get("large") and status != MATCHED and not one.get("research"):
        return "Not looked up: a large group meeting"
    if status == UNRESOLVED:
        return (f"Not sure which LinkedIn profile is theirs: {one['candidates']} to pick from on "
                "their contact")
    if status == NOBODY:
        return "Not found on LinkedIn"
    if status == NONE_OF_THEM:
        return "None of the LinkedIn profiles, you said"
    if status == NO_NAME:
        return "No full name to look them up by"
    if status == FAILED and not one.get("research"):
        return "LinkedIn could not be asked yet; tried again soon"
    if not status and not one.get("research"):
        return "Not looked up yet"
    if status == MATCHED and one.get("confidence") in PICKED_ALL:
        return "The profile you picked"
    return ""


def meeting_card(event: dict, people: list[dict], when: str = "") -> dict:
    """The card of who is coming to a meeting: a row a guest, with their face, their role and
    company, a line of background and where Rouh stands with them. No buttons: a pick is made on
    the guest's own contact card, where it is kept."""
    title = event.get("title") or "the meeting"
    rows = []
    for one in people:
        about = one.get("background") or ""
        if not about and one.get("research") and one.get("status") != MATCHED:
            about = linkedin._shorter(" ".join(one["research"].replace("#", " ").split()), 200)
        rows.append({"name": one["name"], "headline": one.get("headline") or one["email"],
                     "location": one.get("location") or "", "photo": one.get("photo") or "",
                     "url": one.get("url") or "", "about": about, "note": note_of(one),
                     "contact": one.get("contact") or ""})
    count = len(rows)
    return {"title": f"Who is coming: {title}",
            "description": (f"the {count} guest{'s' if count != 1 else ''} of {title}"
                            + (f", {when}" if when else "")
                            + ", with what their public LinkedIn profiles say"),
            "blocks": [{"block": linkedin.PEOPLE, "source": "meeting", "people": rows, "picked": {}}]}


def meeting_text(event: dict, people: list[dict]) -> str:
    """The guests as the model is told them, numbered as the card numbers them."""
    lines = []
    for n, one in enumerate(people, 1):
        head = f"{n}. {one['name']} <{one['email']}>, {one['response']}"
        if one.get("organiser"):
            head += ", organiser"
        if one.get("contact"):
            head += f" (contact {one['contact']})"
        lines.append(head)
        if one.get("relationship"):
            lines.append(f"   who they are to the person, in their words: {one['relationship']}")
        status = one.get("status")
        if status == MATCHED:
            lines.append(f"   LinkedIn: {one.get('headline') or ''} - {one.get('url') or ''} "
                         f"(match: {'picked by ‹owner›' if one.get('confidence') in PICKED_ALL else one.get('confidence') or 'kept'})")
        elif note_of(one):
            lines.append(f"   {note_of(one)}" + (f" ({one['why']})" if one.get("why") else ""))
        if one.get("research"):
            lines.append(f"   online research ({one['researched']}):")
            lines += ["     " + line for line in linkedin._shorter(one["research"], 1500).split("\n")]
        if one.get("slack"):
            # Only ever put there for his own turns (`tools._meeting_people`, `rouh/meeting_slack.py`).
            lines.append("   where ‹owner› and they left things in Slack, for ‹him› alone:")
            lines += ["     " + line for line in one["slack"].split("\n")]
    return "\n".join(lines)


# --- a pick --------------------------------------------------------------------------------------


async def harvest_pick(who, apify, pid: str, url: str, *, meeting: str = "") -> dict:
    """Harvest the candidate Petar picked for a person, and keep it on them. Spent within the day's
    limit like the pass, and saved the same way, as his pick."""
    budget = await asyncio.to_thread(Budget, who)
    if not budget.can(1):
        return {"ok": False, "why": "The day's limit of LinkedIn lookups is spent; it can be done tomorrow."}
    try:
        data = await linkedin.harvest(apify, url, posts=False)
    except linkedin.Trouble as exc:
        return {"ok": False, "why": str(exc)}
    finally:
        budget.spend(linkedin.PROFILE_ACTOR, 1, person=pid, name=url, why="profile the owner picked")
        await asyncio.to_thread(budget.save)
    return {"ok": True, **await keep_picked(who, pid, data, meeting=meeting), "data": data}


async def keep_picked(who, pid: str, data: dict, *, meeting: str = "") -> dict:
    """A profile Petar picked, harvested already, kept on the person with their face."""
    said = await asyncio.to_thread(save_match, who, pid, data, confidence=PICKED,
                                   meeting=meeting, picked=True)
    ds = await asyncio.to_thread(_ds, who)
    face = await keep_photo(who, ds, pid, data.get("photo") or "")
    return {"research": said.get("research"), "photo": face}


def none_of_them(who, pid: str) -> None:
    mark(who, pid, NONE_OF_THEM, candidates=[], why=owner.say("‹owner› said none of them is this person", who))


def candidates_block(who, pid: str, li: dict, chat: str) -> dict | None:
    """The numbered candidates for an unresolved person, as the LinkedIn picker block, signed for
    `who` and for this person, so a Research press keeps what it harvests on them."""
    people = [p for p in li.get("candidates") or [] if isinstance(p, dict) and p.get("url")]
    if li.get("status") != UNRESOLVED or not people:
        return None
    found = linkedin.Found(people, li.get("asked") or "", linkedin.TRIES)
    card = linkedin.picker_card(found, who, chat, person=pid)
    block = card["blocks"][0]
    block["label"] = (f"Which one on LinkedIn? {li.get('why') or ''}".strip()
                      + " Research keeps the one you pick on this contact.")
    return block


def answer_words(who, meeting: dict, words: str) -> tuple[list[tuple[dict, int]], list[dict], str]:
    """Petar's answer to a meeting's question, read: [(person, the number he picked)], the people he
    said were none of them, and what could not be read. "Sam 2, Elena none", "2", "none"."""
    waiting = meeting.get("waiting") or []
    text = " ".join(str(words or "").split())
    picks: list[tuple[dict, int]] = []
    nones: list[dict] = []
    if not text:
        return picks, nones, "No answer was given."
    chunks = [c.strip() for c in re.split(r"[;,\n]|\band\b", text) if c.strip()]
    unread = []
    for chunk in chunks:
        folded = _fold(chunk)
        who_is = [w for w in waiting if any(
            part and f" {part} " in f" {folded} " for part in _fold(w["name"]).split())]
        if not who_is and len(waiting) == 1:
            who_is = waiting
        number = re.search(r"\b(\d{1,2})\b", chunk)
        nothing = re.search(r"\b(none|nobody|neither|no one|skip)\b", folded)
        if len(who_is) != 1 or not (number or nothing):
            unread.append(chunk)
            continue
        if nothing:
            nones.append(who_is[0])
        else:
            n = int(number.group(1))
            if not 1 <= n <= len(who_is[0]["linkedin"].get("candidates") or []):
                unread.append(chunk)
                continue
            picks.append((who_is[0], n))
    return picks, nones, ("; ".join(unread) if unread else "")


# --- his words, when they are not a name and a number ---------------------------------------------
#
# Petar, 9 October 2026, of a guest with two profiles one capital letter apart: "It is the one
# where the 'o' is capitalized if Example Bank, which also has more connections, if you see the
# connections at all." That names one of them plainly, and `answer_words` could only fail it,
# because it reads a name and a number and nothing else. So whatever it cannot read whole is
# read by a model against the candidates, letter by letter, and when the words truly fit more
# than one, the model writes the one short question Rouh asks back instead of failing.

#: Its model pick (`modeldefaults.USES`) and what its requests are written down under.
WORDS_USE = WORDS_PURPOSE = "meeting_pick_words"
WORDS_SECONDS = 90.0

WORDS_SYSTEM = (
    "You read ‹owner›'s written answer to a question Rouh asked ‹him›: which LinkedIn profile belongs "
    "to a guest of one of ‹his› meetings. You are given each guest waiting for ‹his› pick, numbered, "
    "with their candidate profiles, numbered, exactly as LinkedIn's search gave them, and then ‹his› "
    "answer in ‹his› own words.\n\n"
    "‹His› answer may name a profile by its number, or describe it: a word in its headline, a "
    "place, a job, or the way something in it is spelled or capitalised. When ‹he› points at a "
    "difference like that, compare the candidates letter by letter, capitals included. Only "
    "then: when ‹he› does not point at a spelling or a capital ‹himself›, the way ‹he› happens to type "
    "a word tells nothing, so two candidates that differ only in that are not told apart by it.\n"
    "Pick a profile for a guest only when ‹his› words fit exactly one of that guest's candidates "
    "and no other. Anything ‹he› mentions that the candidates do not show (connections, followers, "
    "a photo) neither helps nor hurts: decide from what is shown.\n"
    "‹He› may say that none of a guest's candidates is them.\n"
    "A guest ‹his› answer says nothing about is left out, neither picked nor none.\n"
    "When ‹his› words could mean more than one candidate, or you cannot tell which guest ‹he› means, "
    "pick nothing for that guest and write one short question to ‹him› that names the candidates "
    "it could be, by number and by what tells them apart, so ‹he› can say which.\n\n"
    "Answer with one JSON object and nothing else:\n"
    '{"picks": [{"guest": <guest number>, "profile": <profile number>}], '
    '"none": [<guest number>], "ask": "<your one question to ‹him›, or empty>"}'
)


@dataclass
class Read:
    """His words as the model read them: [(person, number)], the people none of them is, and
    the question to ask him back when they fit more than one."""

    picks: list = field(default_factory=list)
    nones: list = field(default_factory=list)
    ask: str = ""


def words_question(meeting: dict, words: str) -> str:
    """What the model is told: the guests and their candidates, as LinkedIn's words, then his."""
    from . import untrusted

    lines = []
    for g, w in enumerate(meeting.get("waiting") or [], 1):
        lines.append(f"Guest {g}: {w['name']}" + (f" <{w['email']}>" if w.get("email") else ""))
        found = "\n".join(
            f"Profile {n}: " + " | ".join(f"{k}: {c[k]}" for k in ("name", "headline", "location", "url")
                                         if c.get(k))
            for n, c in enumerate(w["linkedin"].get("candidates") or [], 1))
        lines.append(untrusted.wrap(found, f"LinkedIn's search results for {w['name']}"))
        lines.append("")
    lines += ["‹Owner›'s answer, in ‹his› own words:", " ".join(str(words or "").split())]
    return "\n".join(lines)


def read_words(meeting: dict, said: str) -> Read | None:
    """The model's answer as picks for the guests waiting, or None when it gave none."""
    found = re.search(r"\{.*\}", said or "", re.S)
    try:
        got = json.loads(found.group(0)) if found else None
    except ValueError:
        got = None
    if not isinstance(got, dict):
        return None
    waiting = meeting.get("waiting") or []

    def guest(n):
        try:
            n = int(n)
        except (TypeError, ValueError):
            return None
        return waiting[n - 1] if 1 <= n <= len(waiting) else None

    out, seen = Read(), set()
    for one in got.get("picks") or []:
        w = guest(one.get("guest")) if isinstance(one, dict) else None
        try:
            n = int(one.get("profile"))
        except (TypeError, ValueError, AttributeError):
            continue
        if w is None or w["pid"] in seen or not 1 <= n <= len(w["linkedin"].get("candidates") or []):
            continue
        seen.add(w["pid"])
        out.picks.append((w, n))
    for g in got.get("none") or []:
        w = guest(g)
        if w is not None and w["pid"] not in seen:
            seen.add(w["pid"])
            out.nones.append(w)
    out.ask = " ".join(str(got.get("ask") or "").split())[:600]
    if not (out.picks or out.nones or out.ask):
        return None
    return out


async def read_with_model(who, meeting: dict, words: str) -> Read | None:
    """His words read by the model `WORDS_USE` is set to, or None when it could not be asked or
    gave no answer."""
    from . import llm

    try:
        got = await llm.ask(WORDS_USE, system=WORDS_SYSTEM,
                            messages=[{"role": "user", "content": words_question(meeting, words)}],
                            max_tokens=4000, who=who, org_id=str(who.org_id) or None,
                            purpose=WORDS_PURPOSE, timeout=WORDS_SECONDS, read_only=True)
    except Exception:
        log.warning("a written pick of a meeting guest's profile could not be read",
                    exc_info=True)
        return None
    return read_words(meeting, got.text)


# --- the beat --------------------------------------------------------------------------------------


_poke = threading.Event()


def poke() -> None:
    """The calendar changed: run the pass soon rather than at the next hour."""
    _poke.set()


class Researcher:
    """The pass, run by itself every `BEAT` and `SOON` after the calendar changed, for the person
    the install belongs to, with the switch on, Google connected and an Apify key."""

    def __init__(self, *, tenancy, google, apify) -> None:
        self.tenancy = tenancy
        self.google = google
        self.apify = apify
        self._task: asyncio.Task | None = None
        self.last: Report | None = None

    def start(self) -> None:
        if self._task is None and self.google is not None and self.apify is not None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(90)
        last = 0.0
        while True:
            poked = _poke.is_set()
            if time.time() - last >= BEAT or poked:
                if poked:
                    await asyncio.sleep(SOON)
                    _poke.clear()
                last = time.time()
                try:
                    await self.beat()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("the meeting people's beat failed")
            await asyncio.sleep(30)

    def _owner(self):
        from . import switches
        from .telegram import phone_owner

        owner = phone_owner(self.tenancy)
        if owner is None:
            return None
        with contextlib.suppress(Exception):
            switches.register(SWITCH, TITLE, org_id=str(owner.org_id))
        return owner if on(owner) else None

    async def beat(self) -> Report | None:
        from . import clock

        who = await asyncio.to_thread(self._owner)
        if who is None:
            return None
        with clock.person(who, clock.zone_of(who)):
            try:
                calendar = self.google(who).calendar
                self.last = await run(who, calendar=calendar, apify=self.apify)
            except Exception as exc:  # noqa: BLE001 - not connected, or Google said no
                log.info("meeting people: the calendar could not be read: %s", exc)
                return None
        return self.last


__all__ = ["LARGE", "headcount", "is_group", "attendee_view", "meeting_card", "meeting_text", "note_of", "DAILY_CALLS", "MATCHED", "NOBODY", "NO_NAME", "Report", "Researcher", "SWITCH", "UNRESOLVED",
           "answer_words", "candidates_block", "due", "guests_of", "harvest_pick", "keep_picked",
           "meetings_waiting", "name_matches", "name_of", "none_of_them", "on", "photo_of", "photo_url",
           "poke", "run", "save_match", "section_text", "spent_today", "split_name"]
