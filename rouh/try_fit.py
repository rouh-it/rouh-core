"""Things to try that fit what you have: an empty conversation offers what your connections can do.

Built by the nightly feature run, night 50 of the ledger (21 November 2026, task 94), for the
person's guidance that half of what is built makes Rouh easier for somebody using it for the
first time, technical or not.

An empty conversation says hello and offers things to try (`app/welcome.js`). They were the same
four for everybody, about Lisbon and a four-day week, because they had to work with nothing
connected; and for two weeks after the first run, the first four were the steps of setting up,
"Connect my Gmail and calendar" and "Talk to me on Telegram", still offered after both were
connected. Somebody new who had just connected Google was offered to connect it again, and never
shown what it now lets them do.

So, while its switch is on, the page is told what is connected (`fit`): a setting-up step already
done is left out, and with Google connected the first two things to try are the person's own,
"What is on my calendar this week" and "Go through my inbox". Read from the connections Rouh
already keeps (`connection_status`), by `org_id` and `user_id`; no model, nothing written. A
press of one of those is its use (`POST /api/try-fit`).

**Its switch** is `try_fit` (`rouh/switches.py`): off, the same cards as before.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.try_fit")

SWITCH = "try_fit"
TITLE = "Things to try that fit what you have: an empty conversation offers what your connections can do"

#: The connections that change what is offered, as `connection_status` names them.
KEYS = ("google", "telegram")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def fit(who) -> dict:
    """{connection: True when it is live} for the page, or {} while the switch is off."""
    if who is None or not on(who):
        return {}
    out = {k: False for k in KEYS}
    try:
        from . import handholding

        found = handholding.status(who) or {}
    except Exception:  # noqa: BLE001 - nothing known is nothing changed on the page
        log.warning("try_fit: the connections could not be read", exc_info=True)
        return {}
    for key in KEYS:
        out[key] = (found.get(key) or {}).get("kind") == "live"
    return out


def pressed(who, kind: str) -> None:
    """A thing to try that uses what is connected, pressed: its use."""
    from . import evolution

    evolution.used("try_fit", "pressed", who=who, detail=str(kind or "")[:40])
