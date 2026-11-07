"""Booked with a call link: a meeting Rouh books with guests, and no place, gets a Google Meet link.

Built by the nightly feature run, night 33 (second run), 5 November 2026 (task 94). "Book a call
with Dana on Thursday at three" was booked as said: an invitation with a time and nothing else, no
room and no link, because the call link is a separate thing Rouh adds only when told to. The
guests then write back "where do we meet?", or everybody waits on the call at three while somebody
makes a link and pastes it into the chat.

So, while its switch is on, when create_calendar_event makes an event that has guests (somebody
other than the person), is at a time (not a whole day), names no place, carries no call link in its
description and was not told `video_call: false`, Google is asked for a Meet link with it, the way
the Add Google Meet button does. The answer says so, so the model can tell the person, and the
person can still say "no link" (video_call false) or name a place, and nothing is added.

`has_place` is also how Meetings with nowhere to meet (`rouh/no_place.py`) tells a meeting that
has somewhere to be from one that has not.

No model is asked; nothing is read but the call's own arguments.

**Whose.** The connected Google account's calendar, by `org_id` and `user_id`, as every
create_calendar_event is.

**Its switch** is `meet_link` (`rouh/switches.py`): off, a meeting is booked with a link only when
the model asks for one, as before.
"""
from __future__ import annotations

import re

SWITCH = "meet_link"
TITLE = "Booked with a call link: a meeting Rouh books with guests and no place gets a Google Meet link"

#: A call link written into a place or a description: the services people meet on.
CALL = re.compile(r"https?://(?:[\w.-]*\.)?(?:meet\.google\.com|zoom\.us|zoom\.com|teams\.microsoft\.com|"
                  r"teams\.live\.com|webex\.com|whereby\.com|gotomeeting\.com|meet\.jit\.si|"
                  r"chime\.aws|meet\.goto\.com|bluejeans\.com|skype\.com|around\.co|"
                  r"discord\.gg|slack\.com/huddle|app\.slack\.com/huddle)\S*", re.I)

#: Said to the model beside create_calendar_event's other fields.
VIDEO_FIELD = {"type": "boolean",
               "description": ("Give it a Google Meet link. A meeting with guests and no place may "
                               "be given one anyway, and the answer then says so; pass false only "
                               "when the person says there should be no call link.")}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def has_place(where: str = "", description: str = "", video: str = "") -> bool:
    """Whether a meeting has somewhere to be: a place, a call made with it, or a call link in its words."""
    if (where or "").strip() or (video or "").strip():
        return True
    return bool(CALL.search(description or ""))


def wanted(args: dict, guests, *, me: str = "", all_day: bool = False) -> bool:
    """Whether a booking with these arguments should be given a Meet link that it was not asked for."""
    if "video_call" in args and args.get("video_call") is not None:
        return False  # the model said yes or no itself
    if all_day:
        return False
    people = [g for g in guests or [] if "@" in str(g) and str(g).lower() != (me or "").lower()]
    if not people:
        return False
    return not has_place(str(args.get("where") or ""), str(args.get("description") or ""))


NOTE = ("It was given a Google Meet link because it has guests and no place (Booked with a call "
        "link): say so in a few words.")


__all__ = ["CALL", "NOTE", "SWITCH", "TITLE", "VIDEO_FIELD", "has_place", "on", "wanted"]
