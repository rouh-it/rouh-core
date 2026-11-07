"""A stand-in for Google, so the whole consent round trip can be driven for real.

Rouh's side of OAuth is only worth testing if the browser really leaves the
page, really lands on a consent screen, and really comes back to
``/auth/google/callback`` with a code that is really exchanged over HTTP. A
mock inside the process proves none of that.

So this is a real HTTP server that speaks the four addresses Google speaks:

    GET  /o/oauth2/v2/auth   the consent screen, with Allow and Cancel on it
    POST /token              the code and refresh exchanges
    POST /revoke             disconnecting
    GET  /userinfo           whose account it is

plus enough of Gmail, Drive, Docs and Calendar to answer every tool, reading
and writing both. Point Rouh's four Google settings and ``ROUH_GOOGLE_API_BASE`` at it
and nothing in Rouh knows the difference.

It is also the Google Cloud project's Pub/Sub, as far as Gmail push is
concerned (`rouh/mail_alerts.py`). ``POST /_pubsub`` is the console: it makes a
topic, says whether Gmail's own account may publish to it, and gives it a push
subscription's address. Gmail's ``watch`` then refuses exactly where the real
one does - a topic in another project, a topic that is not there, a topic
Gmail may not publish to - and ``POST /_deliver`` puts a new message in the
inbox and, when the inbox is watched, posts Pub/Sub's note about it to that
address, the envelope and the base64 exactly as Pub/Sub sends them.

It is strict on purpose, because the two things that go wrong in real life are
the two things it checks:

- the **redirect URI** in the consent request has to be exactly the one it was
  started with, which is how a test proves that the address Settings tells an
  administrator to register is the address the callback actually serves;
- the **client id and secret** in the token exchange have to be exactly the
  pair it was started with, which is how a test proves the organisation's own
  credentials were used and not something server-wide.

It also grants exactly the scopes the consent screen was asked for, and no
others. ``POST /_grant`` narrows what the next Allow will hand back, which is
the only way to stand a person in front of a consent screen holding an older,
narrower grant - the state the owner's own account is in the moment Rouh starts
asking to send mail as well as read it.

    python -m rouh.testing.fake_google --port 8099 \
        --redirect http://127.0.0.1:8021/auth/google/callback \
        --client-id ... --client-secret ...
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import email
import hashlib
import html
import json
import re
import time
import urllib.parse
from datetime import datetime

import httpx

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

# Keep these aliases as the service import boundary: a patch here before a
# lazy service import must be captured by that service, as before.
from . import fixtures as _fixtures
from .fixtures import (
    ACCOUNT_EMAIL,
    ACCOUNT_ID,
    ACCESS_TOKEN,
    REFRESH_TOKEN,
    RENEWED_ACCESS_TOKEN,
    MESSAGES,
    INBOX_MESSAGES,
    FOLDER_TYPE,
    DRIVES,
    FILES,
    LABELS,
    HARBOR_PLAN_LINK,
    BUDGET_LINK,
    PRICING_LINK,
    ALL_SCOPES,
    BEFORE_CALENDAR_SCOPES,
    OLD_SCOPES,
    PUBSUB_PROJECT,
    FIRST_HISTORY_ID,
    FIRST_MADE_ID,
    READONLY_SCOPE,
    READ_ONLY_ACCOUNTS,
    RO_ACCESS,
    RO_REFRESH,
    SIGN_IN_SCOPES,
    AS_ACCESS,
    CALENDAR_SCOPE,
    CALENDAR_ZONE,
    PERSONS_CALENDAR,
    INJECTED,
)


#: What every file starts with: its owner, and nobody else. Drive really does
#: list the owner as a permission, so "who can see this" has a row to show
#: before anything has been shared.
def _owner_permission() -> dict:
    return {"id": "owner", "type": "user", "role": "owner",
            "emailAddress": ACCOUNT_EMAIL, "displayName": "Alex Morgan"}


def _said(*elements, style: str = "NORMAL_TEXT", heading: str = "") -> dict:
    """One paragraph, its elements given as plain strings or as whole elements."""
    return {"paragraph": {
        "paragraphStyle": {"namedStyleType": style, **({"headingId": heading} if heading else {})},
        "elements": [{"textRun": {"content": one}} if isinstance(one, str) else one
                     for one in elements]}}


def _link(words: str, **target) -> dict:
    """A run of words that links somewhere: `url=`, `tabId=`, or `heading=`."""
    return {"textRun": {"content": words, "textStyle": {"link": target}}}


def _tab(tab_id: str, title: str, index: int, *paragraphs, children=()) -> dict:
    """One tab the way the Docs API sends it with `includeTabsContent`."""
    return {"tabProperties": {"tabId": tab_id, "title": title, "index": index},
            "documentTab": {"body": {"content": [{"endIndex": 1, "sectionBreak": {}},
                                                 *paragraphs]}},
            # Google leaves out what is empty, so a tab with nothing nested
            # under it has no `childTabs` at all.
            **({"childTabs": list(children)} if children else {})}


DOCUMENTS = _fixtures.documents(_said, _link, _tab)


def build(redirect: str, client_id: str, client_secret: str) -> FastAPI:
    from .console import _console_routes
    from .docs import _docs_routes
    from .drive import _drive_routes
    from .gmail import _gmail_routes
    from .oauth import _oauth_routes
    from .sheets import _sheets_routes
    from .slides import _slides_routes
    from .world import create_context

    app = FastAPI(title="Not Google", docs_url=None, redoc_url=None)
    context = create_context(app)
    world, seen = context.world, context.seen
    note, made_up = context.note, context.made_up
    changed = _console_routes(app, world, seen, context.reset, note, made_up)
    _oauth_routes(app, world, seen, context.codes, redirect, client_id, client_secret)
    _gmail_routes(app, world, seen, note, made_up, changed)
    _drive_routes(app, world, seen, note, made_up, context.file_named,
                  context.drive_named, context.holding_permissions)
    _docs_routes(app, world, seen, note, made_up, context.file_named)
    _slides_routes(app, world, seen, note, context.file_named)
    _sheets_routes(app, world, seen, note, context.file_named)
    _calendar_routes(app, world, seen, note, made_up)
    return app


def _asks_read_only(scope: str) -> bool:
    """A mailbox's consent: reading, and at most sending as well, which is what a
    mailbox the person allows forwarding from asks for (`mailboxes.FORWARD_SCOPES`)."""
    asked = set(scope.split())
    return READONLY_SCOPE in asked and not any(
        "gmail.modify" in one or "gmail.compose" in one or one.endswith("/drive")
        for one in asked)


def _read_only_chooser(state: str, scope: str) -> str:
    rows = "".join(
        f'<p><a id="account-{key}" href="/decide?'
        + html.escape(urllib.parse.urlencode({"answer": "allow", "state": state, "scope": scope,
                                              "account": key}))
        + f'">{html.escape(one["email"])}</a></p>' for key, one in READ_ONLY_ACCOUNTS.items())
    cancel = "/decide?" + urllib.parse.urlencode({"answer": "cancel", "state": state})
    sends = any(one.endswith("/gmail.send") for one in scope.split())
    return _page("Choose an account",
                 "<p>to continue to Rouh. Rouh will be able to <strong>view your email "
                 "messages and settings</strong>"
                 + (" and <strong>send email on your behalf</strong>" if sends else "")
                 + ".</p>"
                 f"<p class=\"scopes\">{html.escape(scope)}</p>{rows}"
                 f'<a id="cancel" href="{html.escape(cancel)}">Cancel</a>')


def _asks_sign_in(scope: str) -> bool:
    asked = set(scope.split())
    return bool(asked) and asked <= set(SIGN_IN_SCOPES)


def _sign_in_chooser(state: str, scope: str, hint: str = "") -> str:
    """Google's account chooser, for signing in: the connected account, or any
    other address typed in, with whether Google has verified it (a real
    Google account made for an address outside Gmail can have it unverified).
    `login_hint` fills the address in, as Google puts the hinted account first."""
    allow = "/decide?" + urllib.parse.urlencode({"answer": "allow", "state": state,
                                                 "scope": scope})
    cancel = "/decide?" + urllib.parse.urlencode({"answer": "cancel", "state": state})
    e = html.escape
    return _page(
        "Choose an account",
        "<p>to continue to Rouh</p>"
        f"<p class=\"scopes\">{e(scope)}</p>"
        f'<a id="allow" href="{e(allow)}">{e(ACCOUNT_EMAIL)}</a>'
        '<form id="another" method="get" action="/decide" style="margin-top:22px;'
        'display:grid;gap:8px">'
        '<input type="hidden" name="answer" value="allow">'
        f'<input type="hidden" name="state" value="{e(state)}">'
        f'<input type="hidden" name="scope" value="{e(scope)}">'
        '<label>Use another account<br><input name="as_email" type="email" '
        f'aria-label="Email" value="{e(hint)}"></label>'
        '<label>Name<br><input name="as_name" type="text" aria-label="Name"></label>'
        '<label><input name="as_verified" type="checkbox" value="1" checked> '
        "Google has verified this address</label>"
        '<button type="submit">Next</button></form>'
        f'<a id="cancel" href="{e(cancel)}">Cancel</a>')


def _read_only_account(request: Request) -> str:
    token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not token.startswith(RO_ACCESS):
        return ""
    account = token[len(RO_ACCESS):].removesuffix("-renewed")
    return account if account in READ_ONLY_ACCOUNTS else ""


def _read_only_mail() -> dict[str, list[dict]]:
    """Each account's mail, dated from now, in the shapes the ghost list has to tell apart.

    `days` is how long ago. `labels` SENT marks the person's own. The work
    mailbox has three emails still waiting (Anna, Ivan and Elena, whose only
    answer is an out-of-office), and around them everything that must not be
    listed: one answered in its thread, one whose recipient wrote since in
    another, a thanks with a question only in the quote, one too fresh, one to
    themselves, an invitation, one to a no-reply address, an FYI and a
    courtesy "let me know if you have questions". The home mailbox has two
    waiting, one of them in Bulgarian, and one answered.
    """
    now = time.time()
    day = 86400

    def one(account: str, ident: str, thread: str, days: float, sender: str, to: str,
            subject: str, text: str, *, sent: bool = True, cc: str = "", **more) -> dict:
        return {"id": f"{account}-{ident}", "thread_id": f"{account}-{thread}",
                "from": sender, "to": to, "cc": cc, "subject": subject, "text": text,
                "at": now - days * day, "labels": (["SENT"] if sent else ["INBOX"]),
                "message_id": f"<{account}-{ident}@mail.test>", **more}

    me_work = "Alex Morgan <a@example.com>"
    me_home = "Alex Morgan <alex.morgan@gmail.test>"
    work = [
        one("work", "w12", "t12", 9.2, me_work,
            "Anna Kovacs <anna@partner.test>", "Partnership proposal",
            "Hi Anna,\n\nThanks for the deck. Would you be open to a 30 minute call next "
            "week to go over it?\n\nBest,\nAlex", cc="Tom Weber <tom@partner.test>"),
        one("work", "w1", "t1", 6.1, me_work, "Ivan Dimitrov <ivan@lexfirm.test>",
            "Contract redline",
            "Hi Ivan,\n\nCould you send me the redlined contract by Friday? We need it "
            "before the board meeting.\n\nThanks,\nAlex\n-- \nAlex Morgan\nExample Co"),
        one("work", "w5", "t5", 5.3, me_work, "Elena Novak <elena@accounting.test>",
            "September invoice", "Elena, when will the September invoice arrive?\n\nAlex"),
        one("work", "w5r", "t5", 5.29, "Elena Novak <elena@accounting.test>", me_work,
            "Automatic reply: September invoice",
            "I am out of the office until 5 October with limited access to email.",
            sent=False, headers={"Auto-Submitted": "auto-replied"}),
        one("work", "w2", "t2", 5.0, me_work, "Maria Ivanova <maria@kvadrat.test>",
            "Lighting budget", "Maria, can you confirm the budget for the warm cove?"),
        one("work", "w2r", "t2", 3.0, "Maria Ivanova <maria@kvadrat.test>", me_work,
            "Re: Lighting budget", "Confirmed, it fits. Maria", sent=False),
        one("work", "w3", "t3", 7.0, me_work, "Georgi Petkov <georgi@studio.test>",
            "Shoot photos", "Georgi, could you share the photos from Tuesday's shoot?"),
        one("work", "w3n", "t3n", 2.0, "Georgi Petkov <georgi@studio.test>", me_work,
            "Photos are up", "All the photos are in the shared folder now.", sent=False),
        one("work", "w4", "t4", 4.0, me_work,
            "Maria Ivanova <maria@kvadrat.test>, Georgi Petkov <georgi@studio.test>, "
            "Elena Novak <elena@accounting.test>, Chris <chris@harbor.test>",
            "Re: Launch dinner",
            "Thanks, sounds good! See you there.\n\nOn Mon, Maria Ivanova wrote:\n"
            "> Can everyone make it on Thursday at 8?"),
        one("work", "w6", "t6", 1.0, me_work, "Chris <chris@harbor.test>",
            "Quote for the stands", "Chris, can you send the quote for the stands?"),
        one("work", "w7", "t7", 3.0, me_work, me_work, "Notes to self",
            "Remember to ask about the Harbor venue deposit?"),
        one("work", "w8", "t8", 4.0, me_work, "Nina <nina@paywell.test>",
            "Invitation: Weekly sync @ Mon 5 Oct 10:00",
            "You have been invited. Can you attend?", calendar=True),
        one("work", "w9", "t9", 3.0, me_work, "no-reply@service.test", "Unsubscribe",
            "Please remove me from this list."),
        one("work", "w10", "t10", 10.0, me_work, "Chris <chris@harbor.test>", "Harbor plan",
            "Here is the plan we discussed. FYI, the numbers are in the attached sheet."),
        one("work", "w11", "t11", 12.0, me_work, "Noah <noah@office.test>",
            "Office keys", "I left the keys at reception. Please let me know if you have "
                           "any questions."),
    ]
    home = [
        one("home", "h1", "t1", 8.0, me_home,
            "Димитър Стоянов <dimitar@domoupravitel.test>", "Ремонт на парното",
            "Здравей, Димитър,\n\nМоже ли да ми кажеш кога ще дойде техникът за "
            "парното?\n\nБлагодаря,\nАлекс"),
        one("home", "h2", "t2", 4.0, me_home, "AutoPlus Service <service@autoplus.test>",
            "Car service", "Could you tell me when the car will be ready?"),
        one("home", "h2r", "t2", 2.5, "AutoPlus Service <service@autoplus.test>", me_home,
            "Re: Car service", "It will be ready on Thursday.", sent=False),
        one("home", "h3", "t3", 3.0, me_home, "Lina Georgieva <lina@homes.test>",
            "Flat viewing", "Hi Lina,\n\nIs the flat in Alfama still available? I'd "
                            "like to see it this week.\n\nAlex"),
    ]
    return {"work": work, "home": home}


def _read_only_full(message: dict) -> dict:
    """One read-only mailbox's message as Gmail's `format=full` has it."""
    if message.get("calendar"):
        encoded = base64.urlsafe_b64encode(message["text"].encode()).decode().rstrip("=")
        cal = base64.urlsafe_b64encode(b"BEGIN:VCALENDAR\r\nEND:VCALENDAR").decode()
        payload = {"mimeType": "multipart/alternative", "body": {"size": 0}, "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"data": encoded}},
            {"mimeType": "text/calendar", "filename": "", "body": {"data": cal}}]}
    elif message.get("raw"):
        payload = _full_of_raw(message)
    else:
        payload = _payload(message)
    headers = [{"name": "From", "value": message["from"]},
               {"name": "To", "value": message["to"]},
               {"name": "Subject", "value": message["subject"]},
               {"name": "Date", "value": time.strftime("%a, %d %b %Y %H:%M:%S +0000",
                                                       time.gmtime(message["at"]))},
               {"name": "Message-ID", "value": message["message_id"]}]
    if message.get("cc"):
        headers.append({"name": "Cc", "value": message["cc"]})
    for name, value in (message.get("headers") or {}).items():
        headers.append({"name": name, "value": value})
    if not message.get("raw"):
        payload["headers"] = headers
    return {"id": message["id"], "threadId": message["thread_id"], "labelIds": message["labels"],
            "snippet": html.escape(" ".join(message["text"].split())[:100], quote=True),
            "internalDate": str(int(message["at"] * 1000)), "payload": payload}


#: Gmail's inbox tabs other than Primary, as the labels that put a message in one.
_OTHER_TABS = {"social": "CATEGORY_SOCIAL", "promotions": "CATEGORY_PROMOTIONS",
               "updates": "CATEGORY_UPDATES", "forums": "CATEGORY_FORUMS"}


def _in_category(labels, value: str) -> bool:
    """Gmail's `category:`: Primary is whatever no other tab has claimed."""
    held = set(labels or [])
    value = value.lower()
    if value in ("primary", "personal"):
        return not (held & set(_OTHER_TABS.values()))
    return _OTHER_TABS.get(value, "CATEGORY_" + value.upper()) in held


def _within_dates(at: float, op: str, value: str) -> bool:
    """Gmail's `after:` and `before:`, in seconds since 1970 or as 2026/09/01."""
    value = value.strip('"')
    try:
        mark = float(value)
    except ValueError:
        try:
            mark = datetime.strptime(value.replace("-", "/"), "%Y/%m/%d").timestamp()
        except ValueError:
            return True
    return at > mark if op == "after" else at < mark


def _read_only_matches(message: dict, query: str) -> bool:
    """As much of Gmail's search as the ghost list uses: in:, -in:, is:unread,
    newer_than:, older_than:, after: (seconds) and from:(a OR b)."""
    now = time.time()
    rest = query or ""
    wanted = re.search(r"from:\(([^)]*)\)", rest)
    if wanted:
        rest = rest.replace(wanted.group(0), " ")
        who = [one.strip().lower() for one in wanted.group(1).split(" OR ") if one.strip()]
        if not any(one in message["from"].lower() for one in who):
            return False
    # Bare words, as Gmail reads them: each somewhere in who, the subject or the text.
    for minus, word in re.findall(r"(?:^|\s)(-?)([^\s:()\-][^\s:()]*)(?=\s|$)", rest):
        if word in ("OR", "AND"):
            continue
        hay = " ".join((message["from"], message["to"], message["subject"],
                        message["text"])).lower()
        if bool(minus) == (word.lower() in hay):
            return False
    for minus, op, value in re.findall(r"(-?)(\w+):(\S+)", rest):
        if op == "in":
            label = {"sent": "SENT", "inbox": "INBOX", "chats": "CHAT"}.get(value, value.upper())
            hit = label in message["labels"]
        elif op in ("newer_than", "older_than"):
            days = int(value.rstrip("d"))
            hit = (message["at"] > now - days * 86400) == (op == "newer_than")
        elif op in ("after", "before"):
            hit = _within_dates(message["at"], op, value)
        elif op == "from":
            hit = value.lower() in message["from"].lower()
        elif op == "subject":
            hit = value.lower() in message["subject"].lower()
        elif op == "is" and value == "unread":
            hit = "UNREAD" in message["labels"]
        elif op == "category":
            hit = _in_category(message["labels"], value)
        else:
            hit = True
        if bool(minus) == hit:
            return False
    return True


def _calendars_at_start() -> tuple[list[dict], dict]:
    """The account's calendar list, and what is shared with it but not on it.

    Its own main calendar; one it may write to; a holiday calendar it may only
    read; and Chris's, which shows only when he is busy.
    """
    listed = [
        {"id": ACCOUNT_EMAIL, "summary": ACCOUNT_EMAIL, "primary": True,
         "accessRole": "owner", "timeZone": CALENDAR_ZONE},
        {"id": "c_paywell_team@group.calendar.google.com", "summary": "Paywell team",
         "accessRole": "writer", "timeZone": CALENDAR_ZONE},
        {"id": "en.greek#holiday@group.v.calendar.google.com",
         "summary": "Holidays in Greece", "accessRole": "reader", "timeZone": CALENDAR_ZONE},
        {"id": "chris@harbor.test", "summary": "Chris", "accessRole": "freeBusyReader",
         "timeZone": CALENDAR_ZONE},
    ]
    shared = {
        PERSONS_CALENDAR: {"id": PERSONS_CALENDAR, "summary": "Alex Morgan",
                           "accessRole": "writer", "timeZone": CALENDAR_ZONE},
    }
    return listed, shared


def _events_at_start(today) -> dict[str, list[dict]]:
    """What is on each calendar, counted from today so "tomorrow" always has something."""
    from datetime import timedelta

    def at(days: int, hour: int, minute: int = 0) -> dict:
        from datetime import datetime
        from zoneinfo import ZoneInfo

        day = today + timedelta(days=days)
        moment = datetime(day.year, day.month, day.day, hour, minute,
                          tzinfo=ZoneInfo(CALENDAR_ZONE))
        return {"dateTime": moment.isoformat(timespec="seconds"), "timeZone": CALENDAR_ZONE}

    def whole(days: int) -> dict:
        return {"date": (today + timedelta(days=days)).isoformat()}

    def link(event_id: str) -> str:
        return f"https://www.google.com/calendar/event?eid={event_id}"

    persons = [
        {"id": "ev-sync", "summary": "Paywell sync", "start": at(1, 15), "end": at(1, 16),
         "location": "Paywell office, Lisbon",
         "description": "Agenda: the Q3 numbers.\n" + INJECTED,
         "organizer": {"email": "nina@paywell.test", "displayName": "Nina Park"},
         "attendees": [
             {"email": "nina@paywell.test", "displayName": "Nina Park", "organizer": True,
              "responseStatus": "accepted"},
             {"email": PERSONS_CALENDAR, "displayName": "Alex Morgan", "self": True,
              "responseStatus": "needsAction"},
             {"email": "chris@harbor.test", "responseStatus": "tentative"}],
         "hangoutLink": "https://meet.google.com/pay-well-syn"},
        {"id": "ev-lunch", "summary": "Lunch with Chris", "start": at(2, 12),
         "end": at(2, 13), "location": "The Corner Bistro",
         "organizer": {"email": PERSONS_CALENDAR, "self": True},
         "attendees": [
             {"email": PERSONS_CALENDAR, "self": True, "organizer": True,
              "responseStatus": "accepted"},
             {"email": "chris@harbor.test", "responseStatus": "accepted"}]},
        {"id": "ev-dentist", "summary": "Dentist", "start": at(5, 10),
         "end": at(5, 10, 45), "location": "Dr Hale, 12 Elm Street",
         "organizer": {"email": PERSONS_CALENDAR, "self": True}},
        {"id": "standup", "summary": "Standup", "start": at(1, 9), "end": at(1, 9, 30),
         "recurrence": ["RRULE:FREQ=DAILY;COUNT=5"],
         "organizer": {"email": PERSONS_CALENDAR, "self": True}},
    ]
    # The series above as the occurrences a listing with singleEvents is
    # answered with, each carrying the series it belongs to.
    for day in range(1, 6):
        start = at(day, 9)
        persons.append({
            "id": f"standup_{start['dateTime'][:10].replace('-', '')}T060000Z",
            "summary": "Standup", "start": start, "end": at(day, 9, 30),
            "recurringEventId": "standup", "originalStartTime": start,
            "organizer": {"email": PERSONS_CALENDAR, "self": True}})
    own = [
        {"id": "ev-rouh", "summary": "Rouh maintenance window", "start": at(1, 22),
         "end": at(1, 23), "organizer": {"email": ACCOUNT_EMAIL, "self": True}},
    ]
    team = [
        {"id": "ev-offsite", "summary": "Paywell offsite", "start": whole(3), "end": whole(5),
         "location": "Mountain lodge", "organizer": {"email": "nina@paywell.test"}},
    ]
    holidays = [
        {"id": "ev-holiday", "summary": "Ochi Day (observed)", "start": whole(4),
         "end": whole(5), "transparency": "transparent",
         "organizer": {"email": "en.greek#holiday@group.v.calendar.google.com"}},
    ]
    events = {PERSONS_CALENDAR: persons, ACCOUNT_EMAIL: own,
              "c_paywell_team@group.calendar.google.com": team,
              "en.greek#holiday@group.v.calendar.google.com": holidays}
    for calendar_id, found in events.items():
        for one in found:
            one.setdefault("status", "confirmed")
            one.setdefault("htmlLink", link(one["id"]))
    return events


#: When Chris is busy, counted from today like the events are. His calendar
#: shows nothing else.
def _chris_busy(today) -> list[tuple[int, int, int]]:
    return [(1, 11, 12)]


def _moment_of(part: dict):
    """One end of a stored event as an aware moment, a whole day from its midnight."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if part.get("dateTime"):
        return datetime.fromisoformat(part["dateTime"].replace("Z", "+00:00"))
    day = datetime.fromisoformat(part["date"])
    return day.replace(tzinfo=ZoneInfo(CALENDAR_ZONE))


def _refused(message: str, status: int, reason: str = "") -> JSONResponse:
    error: dict = {"code": status, "message": message}
    if reason:
        error["errors"] = [{"reason": reason, "message": message}]
        error["details"] = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo",
                             "reason": reason}]
    return JSONResponse({"error": error}, status_code=status)


# --------------------------------------------------------------------------
# The mailbox
# --------------------------------------------------------------------------


def _dated(messages: list[dict]) -> list[dict]:
    """The inbox card's mail, dated from now, in Athens, with `date` written out."""
    from datetime import datetime, timedelta
    from email.utils import format_datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(CALENDAR_ZONE))
    out = []
    for one in messages:
        one = dict(one)
        if "minutes_ago" in one:
            at = now - timedelta(minutes=int(one.pop("minutes_ago")))
        else:
            days, clock = one.pop("ago")
            hour, minute = (int(x) for x in clock.split(":"))
            at = (now - timedelta(days=days)).replace(hour=hour, minute=minute, second=0,
                                                      microsecond=0)
        one["date"] = format_datetime(at)
        one["at"] = at.timestamp()
        out.append(one)
    return out


def _without_bytes(message: dict) -> dict:
    """A message as `/_seen` reports it: its files named and counted, not carried."""
    if message.get("raw"):
        message = dict(message, raw=len(message["raw"]))
    if not message.get("files") and not message.get("inline"):
        return message
    return dict(message, files=[{"name": one["name"], "type": one["type"],
                                 "size": len(one["data"])} for one in message.get("files") or []],
                inline=[{"cid": one["cid"], "type": one["type"], "size": len(one["data"])}
                        for one in message.get("inline") or []])


def _arrived_at(message: dict) -> float:
    """When a message reached the mailbox: its own `at`, or its Date line."""
    if message.get("at"):
        return float(message["at"])
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(message.get("date") or "").timestamp()
    except (TypeError, ValueError, IndexError):
        return 0.0


def _thread_of(message: dict) -> str:
    return message.get("thread_id") or "thread-" + message["id"]


def _payload(message: dict) -> dict:
    """A message's body as Gmail sends it: one part, or a tree of them.

    Plain text alone, markup alone, or either with files beside it as a
    multipart/mixed, each file a part of its own with a file name and an
    attachment id to fetch its bytes by.
    """
    def encoded(text: str) -> str:
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

    def text_part(kind: str, words: str) -> dict:
        return {"mimeType": kind, "filename": "", "body": {"data": encoded(words)},
                "headers": [{"name": "Content-Type",
                             "value": f"{kind}; charset=\"UTF-8\""}]}

    # A message with both halves is a multipart/alternative, the way nearly
    # every mailer sends one; pictures drawn inside the markup by `cid:` sit
    # beside it in a multipart/related, each under its Content-ID.
    if message.get("html") and message.get("text"):
        markup = text_part("text/html", message["html"])
        if message.get("inline"):
            markup = {"mimeType": "multipart/related", "filename": "", "body": {"size": 0},
                      "parts": [markup] + [
                          {"mimeType": one["type"], "filename": one.get("name") or "",
                           "headers": [{"name": "Content-ID", "value": f"<{one['cid']}>"},
                                       {"name": "Content-Disposition", "value": "inline"}],
                           "body": {"attachmentId": f"inl-{message['id']}-{n}",
                                    "size": len(one["data"])}}
                          for n, one in enumerate(message["inline"])]}
        body = {"mimeType": "multipart/alternative", "filename": "", "body": {"size": 0},
                "parts": [text_part("text/plain", message["text"]), markup]}
    elif message.get("html"):
        body = {"mimeType": "text/html", "body": {"data": encoded(message["html"])}}
    else:
        body = {"mimeType": "text/plain",
                "body": {"data": encoded(message.get("text") or "")}}
    files = message.get("files") or []
    if not files:
        return _numbered(dict(body), "")
    parts = [dict(body, filename="")]
    for n, one in enumerate(files):
        parts.append({"mimeType": one["type"],
                      "filename": one["name"],
                      "body": {"attachmentId": f"att-{message['id']}-{n}",
                               "size": len(one["data"])}})
    return _numbered({"mimeType": "multipart/mixed", "body": {"size": 0}, "parts": parts}, "")


def _numbered(part: dict, number: str) -> dict:
    """Part numbers as Gmail gives them: "" at the top, then "0", "1", "1.0", ..."""
    part["partId"] = number
    for n, child in enumerate(part.get("parts") or []):
        _numbered(child, f"{number}.{n}" if number else str(n))
    return part


def _raw_of(message: dict) -> bytes:
    """A message as Gmail's `format=raw` has it: every byte, as it was sent.

    One delivered as `raw` is exactly that. Any other is written out here from
    its fields, part for part as `_payload` lays it out, so a part number means
    the same file in both.
    """
    if message.get("raw"):
        return message["raw"]
    from email.message import EmailMessage, MIMEPart

    def text_part(kind: str, words: str) -> MIMEPart:
        part = MIMEPart()
        part.set_content(words, subtype=kind)
        return part

    if message.get("html") and message.get("text"):
        body = MIMEPart()
        body.make_alternative()
        body.attach(text_part("plain", message["text"]))
        markup = text_part("html", message["html"])
        if message.get("inline"):
            related = MIMEPart()
            related.make_related()
            related.attach(markup)
            for one in message["inline"]:
                main, _, sub = one["type"].partition("/")
                picture = MIMEPart()
                picture.set_content(one["data"], maintype=main, subtype=sub,
                                    disposition="inline", filename=one.get("name") or None,
                                    cid=f"<{one['cid']}>")
                related.attach(picture)
            markup = related
        body.attach(markup)
    elif message.get("html"):
        body = text_part("html", message["html"])
    else:
        body = text_part("plain", message.get("text") or "")
    note = EmailMessage()
    for name, key in (("From", "from"), ("To", "to"), ("Cc", "cc"), ("Subject", "subject"),
                      ("Date", "date"), ("Message-ID", "message_id")):
        if message.get(key):
            note[name] = message[key]
    if not message.get("date") and message.get("at"):
        note["Date"] = time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(message["at"]))
    files = message.get("files") or []
    if files:
        note.make_mixed()
        note.attach(body)
        for one in files:
            main, _, sub = one["type"].partition("/")
            held = MIMEPart()
            held.set_content(one["data"], maintype=main, subtype=sub,
                             disposition="attachment", filename=one["name"])
            note.attach(held)
    else:
        for name, value in body.items():
            note[name] = value
        note.set_payload(body.get_payload())
    return note.as_bytes()


def _full_of_raw(message: dict) -> dict:
    """A message delivered `raw`, as Gmail's `format=full` hands it back.

    Including Gmail's own habit, measured on Paola's Outlook mail on 4 October
    2026: a text part's words come back already turned into UTF-8 while its
    Content-Type still names the charset it was sent in (koi8-r). Its files
    are fetched by attachment id, `raw-<message>-<part>`.
    """
    from email import policy

    parsed = email.message_from_bytes(message["raw"], policy=policy.default)

    def part_of(part, number: str) -> dict:
        out = {"partId": number, "mimeType": part.get_content_type(),
               "filename": part.get_filename() or "",
               "headers": [{"name": k, "value": str(v)} for k, v in part.items()]}
        if part.is_multipart() and part.get_content_type() != "message/rfc822":
            out["body"] = {"size": 0}
            out["parts"] = [part_of(child, f"{number}.{n}" if number else str(n))
                            for n, child in enumerate(part.iter_parts())]
            return out
        data = part.get_payload(decode=True) or b""
        if part.get_content_maintype() == "text" and not out["filename"]:
            data = data.decode(part.get_content_charset() or "utf-8", "replace").encode()
            out["body"] = {"size": len(data),
                           "data": base64.urlsafe_b64encode(data).decode().rstrip("=")}
        else:
            out["body"] = {"size": len(data),
                           "attachmentId": f"raw-{message['id']}-{number}"}
        return out

    return part_of(parsed, "")


def _raw_attachment(message: dict, attachment_id: str):
    """A file of a message delivered `raw`, by the attachment id `_full_of_raw` gave it."""
    from email import policy

    if not message.get("raw") or not attachment_id.startswith(f"raw-{message['id']}-"):
        return None
    number = attachment_id.removeprefix(f"raw-{message['id']}-")
    part = email.message_from_bytes(message["raw"], policy=policy.default)
    for step in [n for n in number.split(".") if n]:
        part = list(part.iter_parts())[int(step)]
    data = part.get_payload(decode=True) or b""
    return JSONResponse({"size": len(data),
                         "data": base64.urlsafe_b64encode(data).decode().rstrip("=")})


def _raw_fields(raw: bytes) -> dict:
    """Who, to whom, about what and its words, out of a raw message, for search and lists."""
    from email import policy

    parsed = email.message_from_bytes(raw, policy=policy.default)
    text = next((p for p in parsed.walk() if p.get_content_type() == "text/plain"), None)
    markup = next((p for p in parsed.walk() if p.get_content_type() == "text/html"), None)

    def words(part) -> str:
        if part is None:
            return ""
        data = part.get_payload(decode=True) or b""
        return data.decode(part.get_content_charset() or "utf-8", "replace")

    return {"from": str(parsed.get("from") or ""), "to": str(parsed.get("to") or ""),
            "cc": str(parsed.get("cc") or ""), "subject": str(parsed.get("subject") or ""),
            "text": words(text), "html": words(markup)}


def _raw_delivered(body: dict) -> bytes:
    """`"raw"` on a delivery: a whole message, base64, exactly as some mailer sent it.

    Its From, To, Subject and words are read out of it into the delivery, so
    search and the inbox find it by them, and it is handed back byte for byte
    for `format=raw` and as Gmail transcodes it for `format=full`.
    """
    if not body.get("raw"):
        return b""
    raw = base64.b64decode(body["raw"])
    for key, value in _raw_fields(raw).items():
        if value and not body.get(key):
            body[key] = value
    return raw


def _raw_answer(message: dict, thread_id: str) -> JSONResponse:
    at = message.get("at") or _arrived_at(message)
    return JSONResponse({"id": message["id"], "threadId": thread_id,
                         "labelIds": message.get("labels") or [],
                         "internalDate": str(int(at * 1000)),
                         "raw": base64.urlsafe_b64encode(_raw_of(message)).decode()})


#: One term of a Gmail search: an operator and its value, or a bare word,
#: either possibly in quotes and possibly with a minus in front.
_TERM = re.compile(r'(-?)(?:(\w+):)?("[^"]*"|\S+)')

#: The labels Gmail's search names by a word of its own.
_IN = {"inbox": "INBOX", "sent": "SENT", "trash": "TRASH", "bin": "TRASH",
       "spam": "SPAM", "starred": "STARRED", "important": "IMPORTANT",
       "drafts": "DRAFT", "unread": "UNREAD"}


def _matches(message: dict, query: str, labels: list[dict], *, anywhere: bool = False) -> bool:
    """Whether a message is one a Gmail search would find. `anywhere` is the
    list's `includeSpamTrash`, which `in:anywhere` asks for in the search."""
    held = set(message.get("labels") or [])
    wants_bin = anywhere
    for minus, op, value in _TERM.findall(query or ""):
        value = value.strip('"').lower()
        op = (op or "").lower()
        if op == "in" and value == "anywhere":
            wants_bin = wants_bin or not minus
            continue
        if op in ("in", "label"):
            wanted = _IN.get(value) or next(
                (one["id"] for one in labels if one["name"].lower() == value), value.upper())
            wants_bin = wants_bin or wanted == "TRASH"
            hit = wanted in held
        elif op == "is":
            hit = {"unread": "UNREAD" in held, "read": "UNREAD" not in held,
                   "starred": "STARRED" in held}.get(value, True)
        elif op in ("from", "to", "cc", "subject"):
            hit = value in str(message.get(op) or "").lower()
        elif op == "category":
            hit = _in_category(held, value)
        elif op in ("after", "before"):
            hit = _within_dates(message.get("at") or _arrived_at(message), op, value)
        elif op:
            hit = True
        else:
            words = " ".join(str(message.get(k) or "") for k in
                             ("from", "to", "subject", "text", "html")).lower()
            hit = value in words
        if bool(minus) == hit:
            return False
    return wants_bin or not (held & {"TRASH", "SPAM"})


# --------------------------------------------------------------------------
# Reading what arrived
# --------------------------------------------------------------------------


def _read_rfc2822(raw: str) -> dict:
    """The message Rouh actually put on the wire, as headers and a body.

    Gmail is handed base64url of a whole RFC 2822 message, so this is where a
    test finds out whether the reply carried In-Reply-To, whether the subject
    survived a comma, and whether the body arrived as the person wrote it.
    """
    try:
        decoded = base64.urlsafe_b64decode((raw or "") + "=" * (-len(raw or "") % 4))
    except Exception:
        return {"to": "", "subject": "", "body": "", "raw": raw}
    note = email.message_from_bytes(decoded)
    body = note
    if note.is_multipart():
        body = next((p for p in note.walk() if p.get_content_type() == "text/plain"), note)
    try:
        text = body.get_payload(decode=True).decode("utf-8", "replace")
    except Exception:
        text = str(body.get_payload())
    markup = next((p for p in note.walk() if p.get_content_type() == "text/html"
                   and not p.get_filename()), None)
    try:
        markup = markup.get_payload(decode=True).decode(
            markup.get_content_charset() or "utf-8", "replace") if markup else ""
    except Exception:
        markup = ""

    def drawn(part) -> bool:
        return bool(part.get("Content-ID")) and \
            (part.get_content_disposition() or "inline") == "inline"

    files = [{"name": part.get_filename(), "type": part.get_content_type(),
              "size": len(part.get_payload(decode=True) or b""),
              "sha256": hashlib.sha256(part.get_payload(decode=True) or b"").hexdigest()}
             for part in note.walk() if part.get_filename() and not drawn(part)]
    inline = [{"cid": part.get("Content-ID"), "type": part.get_content_type(),
               "sha256": hashlib.sha256(part.get_payload(decode=True) or b"").hexdigest()}
              for part in note.walk() if drawn(part)]
    return {
        "to": note.get("To", ""), "cc": note.get("Cc", ""), "bcc": note.get("Bcc", ""),
        "subject": note.get("Subject", ""),
        "in_reply_to": note.get("In-Reply-To", ""),
        "references": note.get("References", ""),
        "body": text.strip(),
        "html": markup,
        "files": files,
        "inline": inline,
        "structure": [part.get_content_type() for part in note.walk()],
        "raw_text": decoded.decode("utf-8", "replace"),
    }


def _read_multipart(raw: bytes) -> tuple[dict, bytes, str]:
    """A Drive upload: the JSON part, the file's own bytes, and what it says it is.

    The bytes are handed back as bytes, never decoded on the way through. A PNG
    that arrives here and is turned into a string with `errors="replace"` comes
    out a different file, and a test that then compared it would be comparing
    the damage rather than the upload.
    """
    pieces = raw.split(b"\r\n\r\n")
    metadata: dict = {}
    data = b""
    media_type = "application/octet-stream"
    if len(pieces) >= 2:
        try:
            metadata = json.loads(pieces[1].split(b"\r\n--")[0].decode())
        except Exception:
            metadata = {}
        head = pieces[1].rsplit(b"\r\n--", 1)[-1]
        for line in head.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("content-type:"):
                media_type = line.split(":", 1)[1].strip()
    if len(pieces) >= 3:
        # Joined back up first: a blank line inside a file's own bytes is not a
        # part boundary, and splitting on it would truncate every binary upload
        # that happened to contain one.
        data = b"\r\n\r\n".join(pieces[2:]).rsplit(b"\r\n--", 1)[0]
    return metadata, data, media_type


def _what_arrived(data: bytes) -> dict:
    """What a test can check an upload by, without holding the bytes as JSON.

    The size and the SHA-256 are the proof that exactly what was on disk is
    what arrived: a file the model retyped, or one mangled by a decode, has a
    different digest. `content` is there as well for the text files that were
    the only thing Drive uploads used to carry, and is empty for anything that
    is not text.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = ""
    return {"content": text, "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def _a_file(file_id: str, name: str, mime_type: str, parents: list) -> dict:
    """One file in this Drive, the shape Drive's own answers have."""
    return {"id": file_id, "name": name, "mimeType": mime_type,
            "content": "", "size": 0, "sha256": hashlib.sha256(b"").hexdigest(),
            "modifiedTime": "2026-09-16T12:00:00Z",
            "parents": list(parents), "trashed": False,
            "webViewLink": "https://drive.example.test/" + urllib.parse.quote(name),
            "owners": [{"displayName": "Alex Morgan", "emailAddress": ACCOUNT_EMAIL}],
            "permissions": [_owner_permission()]}


# --------------------------------------------------------------------------
# A document that can really be changed
# --------------------------------------------------------------------------


def _tabs(document: dict) -> list[dict]:
    """A document's tabs, and a document made before tabs as the one it has."""
    if document.get("tabs"):
        return document["tabs"]
    return [{"tabProperties": {"tabId": "t.0", "title": "Tab 1", "index": 0},
             "documentTab": {"body": _body(document)}}]


def _every_tab(document: dict) -> list[dict]:
    """Every tab, each nested one after its parent, the order the sidebar has."""
    out: list[dict] = []

    def walk(tabs) -> None:
        for one in tabs or []:
            out.append(one)
            walk(one.get("childTabs"))

    walk(_tabs(document))
    return out


def _body(document: dict) -> dict:
    """The first tab's body, which is where an edit with no tab named goes."""
    if document.get("tabs"):
        return document["tabs"][0]["documentTab"].setdefault("body", {"content": []})
    return document.setdefault("body", {"content": []})


def _paragraphs(body: dict) -> list[dict]:
    return [one for one in (body or {}).get("content") or [] if one.get("paragraph")]


def _document_text(document: dict) -> str:
    """The document as Drive exports it as plain text.

    With more than one tab, Drive puts each tab's title on a line of its own
    above its words, which is how it was measured on a client's homepage copy on 24
    September 2026. Only the words of runs: an export has no links in it.
    """
    tabs = _every_tab(document)
    out = []
    for tab in tabs:
        if len(tabs) > 1:
            out.append((tab["tabProperties"].get("title") or "") + "\n")
        for one in _paragraphs(tab["documentTab"].get("body")):
            for piece in one["paragraph"].get("elements") or []:
                out.append((piece.get("textRun") or {}).get("content") or "")
    return "".join(out)


def _renumber(document: dict) -> None:
    """Indices, redone from the start, the way Docs keeps them."""
    at = 1
    for one in _body(document).get("content") or []:
        if not one.get("paragraph"):
            one["endIndex"] = at
            continue
        text = "".join((piece.get("textRun") or {}).get("content") or ""
                       for piece in one["paragraph"].get("elements") or [])
        one["startIndex"] = at
        at += len(text)
        one["endIndex"] = at


def _insert_text(document: dict, request: dict) -> None:
    """Text put in at an index, split into paragraphs on its newlines."""
    at = int((request.get("location") or {}).get("index") or 1)
    text = request.get("text") or ""
    content = _body(document).setdefault("content", [])
    for one in content:
        if not one.get("paragraph"):
            continue
        start, end = int(one.get("startIndex") or 1), int(one.get("endIndex") or 1)
        if start <= at <= end:
            was = "".join((piece.get("textRun") or {}).get("content") or ""
                          for piece in one["paragraph"].get("elements") or [])
            cut = min(max(at - start, 0), len(was))
            one["paragraph"]["elements"] = [
                {"textRun": {"content": was[:cut] + text + was[cut:]}}]
            _renumber(document)
            return
    # Past the end of everything there is: a new paragraph of its own.
    content.append({"paragraph": {"paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                                  "elements": [{"textRun": {"content": text}}]}})
    _renumber(document)


def _replace_text(document: dict, request: dict) -> int:
    find = ((request.get("containsText") or {}).get("text")) or ""
    put = request.get("replaceText") or ""
    if not find:
        return 0
    changed = 0
    # Every tab, the way replaceAllText goes when it is not told which.
    for one in (paragraph for tab in _every_tab(document)
                for paragraph in _paragraphs(tab["documentTab"].get("body"))):
        for piece in one["paragraph"].get("elements") or []:
            run = piece.get("textRun")
            if not run:
                continue
            was = run.get("content") or ""
            changed += was.count(find)
            run["content"] = was.replace(find, put)
    _renumber(document)
    return changed


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font:15px/1.5 system-ui,sans-serif;margin:60px auto;max-width:34rem;color:#202124}}
h1{{font-size:22px;font-weight:400}} a{{display:inline-block;margin-top:18px;padding:9px 18px;
border-radius:4px;background:#1a73e8;color:#fff;text-decoration:none}}
a#cancel{{background:#fff;color:#1a73e8;border:1px solid #dadce0}}
.scopes{{font-size:12px;color:#5f6368;word-break:break-all}}</style>
<h1>{html.escape(title)}</h1>
{body}
"""


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--redirect", required=True)
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    args = ap.parse_args()
    uvicorn.run(build(args.redirect, args.client_id, args.client_secret),
                host="127.0.0.1", port=args.port, log_level="warning")


from .calendar import _calendar_routes
from .readonly import _read_only_routes
