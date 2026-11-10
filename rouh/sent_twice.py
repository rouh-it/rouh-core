"""Not sent twice: an email Rouh already sent to the same people, with the same subject and words, in
the last day, is not sent again.

Built by the nightly feature run, night 39 of the ledger (10 November 2026, task 94).
Rouh sends mail for ‹owner› from its own inbox, from a chat, from a job, from a turn carried on after
a deploy cut it short (INC-464), from a reminder that fires while ‹he› already asked for the same by
hand. Each of those can send what has already gone: the job that was stopped half way sends its
email again, the same follow-up goes out from two chats. The other side then gets the same email
twice, and ‹he› looks careless, or as if a machine wrote it, which it did.

So, while its switch is on, before send_mail sends a new email (not a draft, and not a draft named
by its id, which Gmail sends only once anyway), Rouh reads its own Sent mail of the last `HOURS`
hours to the first person it goes to (Gmail's search, GET only). An email there is the same one when
its subject is the same (with "Re:" and "Fwd:" aside), every address of the new one was on it, and
its words are the same, or nearly (`SAME` of the words shared, the quoted part and the signature
aside). Then nothing is sent: Rouh is told when it went, to whom, and its message id, and says so.
Sending it again on purpose is `even_if_sent`.

No model is asked, nothing is kept and nothing is changed.

**Whose.** The person's own Google connection, by `org_id` and `user_id`.

**Its switch** is `sent_twice` (`rouh/switches.py`): off, an email is sent as asked.
"""
from __future__ import annotations

import email.utils
import logging
import re
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger("rouh.sent_twice")

SWITCH = "sent_twice"
TITLE = "Not sent twice: an email already sent to the same people with the same words is not sent again"

#: How far back the Sent mail is read, in hours.
HOURS = 24
#: Share of the words two emails must have in common to be the same email.
SAME = 0.9
#: How many sent emails to the same person are compared.
LOOK = 10

FIELD = {"type": "boolean",
         "description": "Send it although the same email (same people, subject and words) was already sent in the "
                        "last day: only when the person says they want it sent again, after being told."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def addresses(*headers: str) -> set[str]:
    return {a.strip().lower() for _n, a in email.utils.getaddresses([h for h in headers if h]) if "@" in a}


def subject_of(subject: str) -> str:
    """A subject without its Re:, Fwd: and spacing."""
    s = " ".join(str(subject or "").split()).lower()
    while True:
        cut = re.sub(r"^(?:re|fw|fwd|aw|sv|отг|пр)\s*(?:\[\d+\])?\s*:\s*", "", s)
        if cut == s:
            return s
        s = cut


def words_of(body: str) -> list[str]:
    """The words of an email's own part: above anything quoted, with markup taken out."""
    from .sig_phones import own_words

    text = re.sub(r"<[^>]+>", " ", str(body or ""))
    return re.findall(r"\w+", own_words(text).lower())


def same_words(one: str, other: str) -> bool:
    a, b = words_of(one), words_of(other)
    if not a or not b:
        return not a and not b
    if a == b:
        return True
    sa, sb = set(a), set(b)
    shared = len(sa & sb) / max(len(sa), len(sb))
    # Nearly the same words, and nearly as many of them: a greeting or a full stop changed.
    return shared >= SAME and min(len(a), len(b)) / max(len(a), len(b)) >= SAME


def same_email(sent: dict, *, to: set[str], subject: str, body: str) -> bool:
    if subject_of(sent.get("subject") or "") != subject_of(subject):
        return False
    if not to or not to <= addresses(sent.get("to") or "", sent.get("cc") or "", sent.get("bcc") or ""):
        return False
    return same_words(sent.get("body") or "", body)


def said(sent: dict, zone) -> str:
    at = float(sent.get("at") or 0)
    when = datetime.fromtimestamp(at, zone).strftime("%A %-d %B at %H:%M") if at else "earlier today"
    ago = int((time.time() - at) // 60) if at else 0
    lately = (f", {ago} minutes ago" if 0 < ago < 120 else "")
    return ("Not sent: the same email already went. "
            f"{sent.get('subject') or '(no subject)'!r} was sent from Rouh's inbox on {when}{lately}, "
            f"to {sent.get('to') or 'the same people'}, with the same words (message id {sent.get('id')}). "
            "Tell the person it already went and when. Only if they say to send it again, call send_mail "
            "again with even_if_sent.")


async def check(gmail, *, to: str, cc: str, bcc: str, subject: str, body: str, zone) -> tuple[str, dict | None]:
    """(what to tell the model, the email already sent) or ("", None) when it is new."""
    wanted = addresses(to, cc, bcc)
    if not wanted:
        return "", None
    first = sorted(addresses(to) or wanted)[0]
    since = (datetime.now(timezone.utc) - timedelta(hours=HOURS)).strftime("%Y/%m/%d")
    listed = await gmail.recent(LOOK, f"in:sent to:{first} after:{since}", most=LOOK)
    for one in listed:
        if float(one.get("at") or 0) < time.time() - HOURS * 3600:
            continue
        if subject_of(one.get("subject") or "") != subject_of(subject):
            continue
        whole = await gmail.message(one["id"])
        if same_email(whole, to=wanted, subject=subject, body=body):
            return said(whole, zone), whole
    return "", None


__all__ = ["FIELD", "HOURS", "SWITCH", "TITLE", "check", "on", "same_email", "same_words", "subject_of"]
