"""Connect Google where it is needed: Settings, Google, opened the moment a tool finds it missing.

Built by the nightly feature run, night 50 of the ledger (21 November 2026, task 94), for the
person's guidance that half of what is built makes Rouh easier for somebody using it for the
first time, technical or not.

Somebody new asks "what is on my calendar tomorrow?" before they have connected Google. The tool
answers "No Google account is connected yet. Open Settings and press Connect Google.", Rouh says
so, and the person has to find Settings, then the right group in it, then the button. For
somebody who has never seen Rouh that is three things to look for, at the moment they wanted an
answer.

So, while its switch is on, a tool result of a turn somebody is watching that says Google is not
set up or not connected, was withdrawn, or lacks the access asked for (`missing`) opens Settings at
Google (Connections, Email, where the client is registered and Connect Google is) on its
own, once a turn: a desk opens it beside the conversation, and a phone, or a desk with a page in
front, gets a note with Open (`settings_shown`, `why` "google_needed"). The Connect Google button
is then the one thing to press. Nothing is kept and no model is asked; a press of Connect Google
on Settings opened this way is counted as its use (`/auth/google/start?from=needed`).

**Whose.** The person whose turn it is; their own Settings, in their own tab.

**Its switch** is `google_needed` (`rouh/switches.py`): off, the reply only says it in words, as
before.
"""
from __future__ import annotations

import re

SWITCH = "google_needed"
TITLE = "Connect Google where it is needed: Settings opened at Google when a tool finds it missing"

#: The sentences Rouh's own tools say when Google is the missing piece (`tools._google_trouble`,
#: `google_oauth.NeedsMoreAccess`, the mailbox tools' "No mailbox is connected"). Only Rouh's own
#: words are read: an email or a page that says "connect Google" is somebody else's (`missing`).
_SAYS = re.compile(
    r"No Google account is connected yet"
    r"|Google has withdrawn this connection"
    r"|press Connect Google"
    r"|No mailbox is connected: connect Google"
    r"|Google is not set up for this organisation yet", re.I)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def missing(name: str, out) -> bool:
    """Whether a tool's own result says Google has to be connected, or connected again.

    Only Rouh's own words count: a result the tool fetched from somebody else (an email, a page)
    is never read for it, unless the handler marked it as Rouh's own (`untrusted.ours`)."""
    from . import untrusted

    if not isinstance(out, untrusted.Ours) and untrusted.source_for(name):
        return False
    text = str(out or "")
    return bool(text) and bool(_SAYS.search(text[:2000]))


#: Seconds in which Settings is not opened again for the same person: a turn that tries three
#: Google tools, or a reply that tries again, opens it once.
QUIET = 120
_LAST: dict[str, float] = {}


def due(who) -> bool:
    """Whether it may be opened now for this person, and if so, that it was."""
    import time

    key = f"{getattr(who, 'org_id', '')}:{getattr(who, 'user_id', '')}"
    now = time.monotonic()
    if now - _LAST.get(key, -QUIET - 1) < QUIET:
        return False
    _LAST[key] = now
    return True


def connected_from_here(who) -> None:
    """Connect Google was pressed on Settings this gene opened: its use."""
    from . import evolution

    evolution.used("google_needed", "connect", who=who, detail="")


def opened(who, tool: str) -> None:
    """Settings was opened at Google because `tool` found it missing: its moment came."""
    from . import evolution

    evolution.used("google_needed", "opened", who=who, detail=str(tool or "")[:60])
