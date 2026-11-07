"""With a meeting's guests: the Share panel offers the guests of a meeting about this page or task,
shared with in one press.

Built by the nightly feature run, night 30, 2 November 2026 (task 94, idea I-175). ‹He› shares
Work pages and tasks with people from outside for a meeting with them: before a call, so they can
read it, or after, as what was agreed. Each one is typed into the Share panel's address box by
hand, one after the other, copied from the invitation, and somebody is left out when the
invitation has five guests. Rouh already holds every meeting of ‹his› calendars with its guests
(Synapse, kind `event`, kept by the calendar sync), so the addresses are known.

So, while its switch is on, the Share panel shows **With a meeting's guests** under the address
box: up to three of ‹his› meetings from three days ago to a week ahead, whose title shares a word
with the page's or the task's own name or its folder's, each with its day, time and how many of
its guests are not on the page yet. Pressing one says who they are; **Share with them** shares
with every one of them at the level picked beside the address box, with the letter and its
message as Notify by email says, exactly as typing each address and pressing Send would
(`web/guests.share_and_tell`), and says who it went to. A meeting none of whose guests is left to
add, ‹his› own addresses and ‹his› company's colleagues are not offered: only guests from outside.

**Whose.** ‹His› own Master (`synapse.item`, `org_id` and `user_id`) and ‹his› own shares
(`sharing.Guests`), as the Share panel already is. Rouh sends the same letter Send sends, only
when ‹he› presses Share with them.

**Its switch** is `share_meeting` (`rouh/switches.py`): off, the panel has no such line and the
route refuses.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta

log = logging.getLogger("rouh.share_meeting")

SWITCH = "share_meeting"
TITLE = ("With a meeting's guests: the Share panel offers the guests of a meeting about this page "
         "or task, shared with in one press")
LOOK_BACK_DAYS = 3
LOOK_AHEAD_DAYS = 7
MOST = 3
MOST_GUESTS = 12
#: Words that say nothing about what a meeting or a page is about.
_PLAIN = {
    "the", "and", "for", "with", "from", "into", "about", "this", "that", "call", "meeting", "sync",
    "weekly", "daily", "catch", "catchup", "chat", "review", "plan", "notes", "page", "task", "step",
    "index", "html", "work", "update", "follow", "next", "first", "second", "what", "where", "how",
    "our", "your", "new", "draft", "final", "v1", "v2", "v3", "intro", "online", "team",
}
_WORD = re.compile(r"[^\W\d_]{3,}", re.U)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def words(*texts: str) -> set[str]:
    out = set()
    for text in texts:
        for w in _WORD.findall(str(text or "").replace("-", " ").replace(".", " ").replace("_", " ")):
            low = w.lower()
            if low not in _PLAIN:
                out.add(low)
    return out


def _key(ident: str) -> str:
    return "m-" + hashlib.sha256(ident.encode()).hexdigest()[:16]


def meetings(who, rel: str, title: str, *, already: set[str] | None = None,
             now: datetime | None = None) -> list[dict]:
    """Up to `MOST` meetings about this page or task, each with its guests from outside not on it yet."""
    from . import clock, meeting_prep
    from .notes_missing import _meta, _responses, _rows, _when

    about = words(title, *str(rel or "").split("/")[-3:])
    if not about:
        return []
    zone = clock.zone_of(who)
    now = (now or datetime.now().astimezone()).astimezone(zone)
    since, until = now - timedelta(days=LOOK_BACK_DAYS), now + timedelta(days=LOOK_AHEAD_DAYS)
    own = {a.lower() for a in meeting_prep.own_addresses(who)}
    domains = meeting_prep.own_domains(own)
    taken = {a.lower() for a in (already or set())}
    seen, out = set(), []
    for r in _rows(who, "event", since - timedelta(days=1), 800):
        meta = _meta(r.get("meta"))
        gcal = meta.get("gcal") if isinstance(meta.get("gcal"), dict) else {}
        start = _when(meta.get("start"))
        if start is None or gcal.get("all_day") or gcal.get("status") == "cancelled":
            continue
        start = start.astimezone(zone)
        if start < since or start > until:
            continue
        name = str(r.get("title") or "").strip()
        shared = about & words(name)
        if not shared:
            continue
        body = str(r.get("body") or "")
        answers = _responses(body, meta.get("attendees"))
        if any(answers.get(a) == "declined" for a in own):
            continue
        ident = str(gcal.get("ical_uid") or "") + "|" + str(meta.get("start") or "")
        if ident in seen:
            continue
        seen.add(ident)
        guests = [{"email": a} for a in (meta.get("attendees") or [])]
        host = str(meta.get("from") or "").strip().lower()
        if host:
            guests.append({"email": host})
        outside = [g["email"].lower() for g in meeting_prep.outsiders(guests, own, domains)]
        left = [a for a in outside if a not in taken][:MOST_GUESTS]
        if not left:
            continue
        out.append({"key": _key(ident), "title": name or "a meeting", "start": start.timestamp(),
                    "when": ("today " if start.date() == now.date() else
                             "tomorrow " if start.date() == (now + timedelta(days=1)).date() else
                             "yesterday " if start.date() == (now - timedelta(days=1)).date() else
                             start.strftime("%a %-d %b ")) + start.strftime("%H:%M"),
                    "guests": left, "match": len(shared),
                    "past": start < now})
    # The closest in words first, then the nearest in time, coming before past.
    out.sort(key=lambda m: (-m["match"], m["past"], abs(m["start"] - now.timestamp())))
    return out[:MOST]


def one(who, rel: str, title: str, key: str, already: set[str]) -> dict | None:
    for m in meetings(who, rel, title, already=already):
        if m["key"] == key:
            return m
    return None


__all__ = ["SWITCH", "TITLE", "meetings", "on", "one", "words"]
