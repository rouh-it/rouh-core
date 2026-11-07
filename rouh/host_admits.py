"""Who lets the note-taker in: today's and tomorrow's calls somebody outside ‹his› company hosts,
said in the morning brief, with a note to the host ready in ‹his› own mail.

Built by the nightly feature run, night 30, 2 November 2026 (task 94, idea I-174). ‹His›
meetings are recorded by the meeting library's note-taker, which joins each call as a guest and
waits in the lobby until somebody in the call lets it in. In a call ‹he› hosts, ‹he› does; in a
call somebody from outside hosts, only that host or a co-host can, and ‹he› cannot even see it
knock. On 1 November 2026 (task 67, step 67-06) the library found that no note-taker had been let
into a Google Meet call since 23 October, eight in a row, and among the causes that ‹he› was a
guest in the calls that mattered ("I was in the meeting looking for him to let him in and none
were available"), and the recommendation for a series hosted outside was to ask its host once
to let it in, or to make ‹him› a co-host. Nothing tells ‹him› beforehand which calls those are.

So, while its switch is on, the morning brief has a section **Who lets the note-taker in**,
read afresh every time the page opens, with no model:

- **Which.** Events of ‹his› own calendars in ‹his› Master (`synapse.item`, kind `event`), from
  now to the end of tomorrow, that are not all day or cancelled, that ‹he› did not decline,
  that have a video call, and whose organiser is somebody outside ‹his› company (the calendar
  sync keeps the organiser as `from` when it is not ‹him›), one line a meeting.
- **Only when the library is in use**: it is set up here and has sent notes at least once.
- **What it says.** The day and time, the meeting, who hosts it (their name and address) and
  that only they or a co-host can let the note-taker in; **Who is in it**, closed at first,
  the guests; **Ask <host> to let it in** opens a new message to the host in ‹his› own Gmail,
  written for ‹him› to change and send (Rouh sends nothing), and marks the line asked; **No
  notes needed** puts the line away for good, with Undo.

**Whose.** ‹His› own Master and ‹his› own settings (`user_settings`, `host_admits`), by `org_id`
and `user_id`. Nothing is sent and nothing is changed anywhere but that setting.

**Its switch** is `host_admits` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

log = logging.getLogger("rouh.host_admits")

SWITCH = "host_admits"
TITLE = ("Who lets the note-taker in: today's and tomorrow's calls somebody outside your company "
         "hosts, in the morning brief, with a note to the host ready in your own mail")
#: The person's own setting: {line key: {"put": seconds} or {"asked": seconds}}.
KEPT = "host_admits"
MOST = 8


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _key(ident: str) -> str:
    return "h-" + hashlib.sha256(ident.encode()).hexdigest()[:16]


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


def _organiser(meta: dict, body: str) -> tuple[str, str]:
    """(name, address) of who organises it, when it is not the person, else ("", "")."""
    address = str(meta.get("from") or "").strip().lower()
    if not address:
        return "", ""
    name = ""
    for line in (body or "").splitlines():
        if line.startswith("Organiser:"):
            name = line[len("Organiser:"):].split("<")[0].strip()
            break
    return name, address


def _first_name(name: str, address: str) -> str:
    word = (name or "").split()
    if word:
        return word[0]
    return address.split("@")[0].split(".")[0].capitalize()


def _platform(link: str) -> str:
    low = (link or "").lower()
    if "meet.google.com" in low:
        return "Google Meet"
    if "zoom.us" in low:
        return "Zoom"
    if "teams." in low:
        return "Microsoft Teams"
    if "webex.com" in low:
        return "Webex"
    return "the call"


def _day_words(start: datetime, now: datetime) -> str:
    if start.date() == now.date():
        return "today"
    if start.date() == (now + timedelta(days=1)).date():
        return "tomorrow"
    return start.strftime("%A")


def note_to_host(*, host: str, title: str, start: datetime, now: datetime, mine: str) -> str:
    """Gmail's own new-message window, in the person's own mailbox, with a note to the host."""
    when = f"{_day_words(start, now)} at {start.strftime('%H:%M')}"
    body = (f"Hi {host},\n\n"
            f"A note-taker from our side will join {title!r} {when} and wait in the lobby until "
            "somebody lets it in. Could you let it in when it knocks, or make me a co-host so I can?\n\n"
            "Thank you.")
    asked = {"view": "cm", "fs": "1", "su": f"Our note-taker in {title}", "body": body}
    return asked if not mine else {"authuser": mine, **asked}


def compose_link(to: str, asked: dict) -> str:
    return "https://mail.google.com/mail/?" + urlencode({**asked, "to": to}, quote_via=quote)


def hosted_elsewhere(who, *, now: datetime | None = None) -> dict | None:
    """{items, count} for the brief, or None when there is nothing to say."""
    from . import clock, inboxes, meeting_prep, notes_missing
    from .notes_missing import _meta, _responses, _rows, _video, _when
    from .synapse.sources import meetings as library

    if not library.settings()["url"]:
        return None
    if notes_missing._last_notes(who) is None:
        return None
    zone = clock.zone_of(who)
    now = (now or datetime.now().astimezone()).astimezone(zone)
    until = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    own = {a.lower() for a in meeting_prep.own_addresses(who)}
    domains = meeting_prep.own_domains(own)
    mine = inboxes.account_address(who) or ""
    put_away = kept(who)
    seen, out = set(), []
    # Rows are kept by their start (`said_at`); reading from a day back takes in a call already on.
    for r in _rows(who, "event", now - timedelta(days=1), 600):
        meta = _meta(r.get("meta"))
        gcal = meta.get("gcal") if isinstance(meta.get("gcal"), dict) else {}
        start, end = _when(meta.get("start")), _when(meta.get("end"))
        if start is None or end is None or gcal.get("all_day") or gcal.get("status") == "cancelled":
            continue
        start, end = start.astimezone(zone), end.astimezone(zone)
        if end <= now or start >= until:
            continue
        body = str(r.get("body") or "")
        answers = _responses(body, meta.get("attendees"))
        if any(answers.get(a) == "declined" for a in own):
            continue
        video = _video(meta, body)
        if not video:
            continue
        name, host = _organiser(meta, body)
        if not host or host in own or not meeting_prep.outsiders([{"email": host}], own, domains):
            continue
        ident = str(gcal.get("ical_uid") or "") or f"{r.get('title')}|{start.isoformat()}"
        ident += "|" + str(meta.get("start") or "")
        if ident in seen:
            continue
        seen.add(ident)
        key = _key(ident)
        held = put_away.get(key) or {}
        if held.get("put"):
            continue
        title = str(r.get("title") or "a meeting")
        guests = [{"email": a, "response": answers.get(str(a).lower(), "")}
                  for a in (meta.get("attendees") or [])]
        host_name = name or host
        out.append({
            "key": key, "title": title, "start": start.timestamp(), "end": end.timestamp(),
            "day": _day_words(start, now), "time": start.strftime("%H:%M"),
            "host": host_name, "host_email": host, "platform": _platform(video),
            "link": str(gcal.get("link") or ""), "call": video,
            "guests": [g["email"] for g in guests
                       if g["email"].lower() != host and g["email"].lower() not in own][:12],
            "asked": float(held.get("asked") or 0) or None,
            "compose": compose_link(host, note_to_host(
                host=_first_name(name, host), title=title, start=start, now=now, mine=mine)),
        })
    if not out:
        return None
    out.sort(key=lambda i: i["start"])
    return {"items": out[:MOST], "count": len(out)}


async def again(who, brief: dict) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("host_admits", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        found = await sync_to_async(hosted_elsewhere)(who)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("who lets the note-taker in could not be read")
        return
    if found:
        from . import evolution

        brief["host_admits"] = {"ok": True, "source": "Calendar", **found}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                            detail=f"{found['count']} calls hosted by somebody outside")


ACTS = ("asked", "put", "undo", "guests")


def act(who, key: str, what: str) -> None:
    """Ask the host (marked asked), No notes needed (put away), Undo, or Who is in it (counted)."""
    from . import evolution

    if what == "guests":
        evolution.used(SWITCH, "guests", who=who, detail="opened who is in a call hosted outside")
        return
    held = kept(who)
    if what == "asked":
        held[key] = {**(held.get(key) or {}), "asked": time.time()}
    elif what == "put":
        held[key] = {**(held.get(key) or {}), "put": time.time()}
    else:
        line = dict(held.get(key) or {})
        line.pop("put", None)
        if line:
            held[key] = line
        else:
            held.pop(key, None)
    _keep(who, held)
    if what == "asked":
        evolution.used(SWITCH, "asked", who=who, detail="opened a note to a call's host in Gmail")
    elif what == "put":
        evolution.used(SWITCH, "put", who=who, detail="said a call hosted outside needs no notes")


__all__ = ["ACTS", "KEPT", "SWITCH", "TITLE", "act", "again", "hosted_elsewhere", "on"]
