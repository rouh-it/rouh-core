"""Not forwarded twice: an email Rouh already forwarded to the same people in the last day is not
forwarded again.

Built by the nightly feature run, night 41 of the ledger (12 November 2026, task 94).
Night 39 stopped the same email being sent twice (`rouh/sent_twice.py`) and night 40 the same draft
being made twice (`rouh/draft_twice.py`). A forward had neither check: `forward_mail` and
`forward_thread` read nothing before they send, so the same request asked in two chats, a job run
again, or a turn carried on after a deploy cut it short forwards the same email again, and the other
side gets the flight receipt, the contract or the whole thread twice.

So, while its switch is on, before a forward goes, Rouh reads the Sent mail of the inbox it goes
from, for the last `HOURS` hours, to the first person it goes to (Gmail's search, GET only, at most
`LOOK`). A sent email there is the same forward when every address of the new one was on it, its
subject is the original's (with "Re:" and "Fwd:" aside), and its words carry Gmail's forwarded
message header with the original's sender. Then nothing is sent: Rouh is told when it went, to whom,
and its message id, and says so. Forwarding it again on purpose is `even_if_forwarded`.

No model is asked, nothing is kept and nothing is changed.

**Whose.** The person's own Google connection, by `org_id` and `user_id`.

**Its switch** is `forward_twice` (`rouh/switches.py`): off, a forward goes as asked.
"""
from __future__ import annotations

import email.utils
import logging
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("rouh.forward_twice")

SWITCH = "forward_twice"
TITLE = "Not forwarded twice: the same email already forwarded to the same people is not forwarded again"

#: How far back the Sent mail is read, in hours.
HOURS = 24
#: How many sent emails to the same person are compared.
LOOK = 10

FIELD = {"type": "boolean",
         "description": "Forward it although the same email was already forwarded to the same people in the last "
                        "day: only when the person says they want it forwarded again, after being told."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def sender_of(original: dict) -> str:
    return (email.utils.parseaddr(original.get("from") or "")[1] or "").strip().lower()


def same_forward(sent: dict, *, to: set[str], original: dict) -> bool:
    """Whether an email in the Sent mail is this original, forwarded to these people already."""
    from .forwarding import RULE
    from .sent_twice import addresses, subject_of

    if not to or not to <= addresses(sent.get("to") or "", sent.get("cc") or "", sent.get("bcc") or ""):
        return False
    if subject_of(sent.get("subject") or "") != subject_of(original.get("subject") or ""):
        return False
    words = str(sent.get("body") or "") + "\n" + str(sent.get("html") or "")
    if RULE not in words and "Forwarded message" not in words:
        return False
    sender = sender_of(original)
    return not sender or sender in words.lower()


def said(sent: dict, zone, *, whole_thread: bool) -> str:
    at = float(sent.get("at") or 0)
    when = datetime.fromtimestamp(at, zone).strftime("%A %-d %B at %H:%M") if at else "earlier today"
    ago = int((time.time() - at) // 60) if at else 0
    lately = f", {ago} minutes ago" if 0 < ago < 120 else ""
    what = "conversation" if whole_thread else "email"
    tool = "forward_thread" if whole_thread else "forward_mail"
    return (f"Not forwarded: the same {what} was already forwarded to {sent.get('to') or 'the same people'} "
            f"on {when}{lately}, as {sent.get('subject') or '(no subject)'!r} (message id {sent.get('id')}). "
            f"Tell the person it already went and when. Only if they say to forward it again, call {tool} "
            "again with even_if_forwarded.")


async def check(gmail, message_id: str, *, to: str, cc: str, bcc: str, zone,
                whole_thread: bool = False) -> tuple[str, dict | None]:
    """(what to tell the model, the forward already sent) or ("", None) when it is new."""
    from .sent_twice import addresses

    wanted = addresses(to, cc, bcc)
    if not wanted or not message_id:
        return "", None
    original = await gmail.message(message_id)
    first = sorted(addresses(to) or wanted)[0]
    since = (datetime.now(timezone.utc) - timedelta(hours=HOURS)).strftime("%Y/%m/%d")
    listed = await gmail.recent(LOOK, f"in:sent to:{first} after:{since}", most=LOOK)
    for one in listed:
        if float(one.get("at") or 0) < time.time() - HOURS * 3600:
            continue
        if str(one.get("id")) == str(message_id):
            continue
        whole = await gmail.message(one["id"])
        if same_forward(whole, to=wanted, original=original):
            return said(whole, zone, whole_thread=whole_thread), whole
    return "", None


__all__ = ["FIELD", "HOURS", "LOOK", "SWITCH", "TITLE", "check", "on", "same_forward"]
