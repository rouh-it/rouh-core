"""A meeting's guest list hidden from its guests, and guests kept from inviting others.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
An event with guests from several companies (a demo for prospects, a webinar, interviews of several
candidates, a dinner for investors) shows every guest everybody else's name and address by default,
and lets each invite more people. Google Calendar has two boxes for it, under Guest permissions:
"See guest list" and "Invite others". Asked "make it so they can't see each other", Rouh could not.

So, while its switch is on, `create_calendar_event` and `update_calendar_event` take two more
settings: `guests_see_guests` false hides the guest list from the guests (Google's
guestsCanSeeOtherGuests; the organiser still sees it), true shows it again; `guests_invite_others`
false keeps guests from inviting anybody, true lets them again (guestsCanInviteOthers). It is
changed quietly, with no email to the guests, and what it was already is said and not changed
again. Only the event's organiser's calendar may change it. No model is asked.

**Whose.** The person's own Google connection (`org_id` and `user_id`), one event at a time.

**Its switch** is `guest_list` (`rouh/switches.py`): off, the two settings are refused and nothing
changes.
"""
from __future__ import annotations

SWITCH = "guest_list"
TITLE = "A meeting's guest list hidden from its guests, and guests kept from inviting others"

SEE = {"type": "boolean",
       "description": "false: the guests cannot see who else is invited (the organiser still can); true shows the "
                      "guest list again. For an event with guests from several companies, or 'so they can't see "
                      "each other'. No email goes to the guests for it."}
INVITE = {"type": "boolean",
          "description": "false: the guests cannot invite anybody else; true lets them again. No email goes to "
                         "the guests for it."}

OFF = ("Hiding a meeting's guest list, or keeping its guests from inviting others, is switched off (A "
       "meeting's guest list hidden, in Mutations), so nothing was changed. Ask again without it.")

_GOOGLE = {"guests_see_guests": "guestsCanSeeOtherGuests", "guests_invite_others": "guestsCanInviteOthers"}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def wanted(args) -> dict:
    """The settings asked for, by Google's own names: {"guestsCanSeeOtherGuests": bool, ...}."""
    out = {}
    for ours, google in _GOOGLE.items():
        value = args.get(ours)
        if isinstance(value, bool):
            out[google] = value
        elif isinstance(value, str) and value.strip().lower() in ("true", "false", "yes", "no"):
            out[google] = value.strip().lower() in ("true", "yes")
    return out


def state_of(raw: dict) -> dict:
    """What the event is set to, by Google's names: both are true when Google leaves them out."""
    return {"guestsCanSeeOtherGuests": raw.get("guestsCanSeeOtherGuests") is not False,
            "guestsCanInviteOthers": raw.get("guestsCanInviteOthers") is not False}


def words(state: dict) -> str:
    see = ("the guests can see who else is invited" if state["guestsCanSeeOtherGuests"]
           else "the guests cannot see who else is invited (you still can)")
    invite = ("they can invite others" if state["guestsCanInviteOthers"] else "they cannot invite anybody else")
    return f"{see}, and {invite}"


__all__ = ["INVITE", "OFF", "SEE", "SWITCH", "TITLE", "on", "state_of", "wanted", "words"]
