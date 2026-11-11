"""Not drafted twice: a draft Rouh is about to write that is already in its Drafts, to the same people,
with the same subject and words, is not written again.

Built by the nightly feature run, night 40 of the ledger (11 November 2026, task 94).
Night 39 stopped the same email being sent twice (`rouh/sent_twice.py`). A draft had no such check:
the same request asked in two chats, a job run again, a turn carried on after a deploy cut it short,
each writes the same draft again. Rouh's Drafts then hold two copies of one email, one of them is
sent and the other stays behind, which is exactly what ‹owner› found on 24 September 2026 ("later
the draft was still in my Gmail drafts next to the sent reply"), or the older one is sent later by
mistake.

So, while its switch is on, before draft_mail writes a new draft, Rouh reads its own Drafts to the
first person it goes to (Gmail's drafts list with its search, GET only, at most `LOOK`). A draft
there is the same one when its subject is the same (with "Re:" and "Fwd:" aside), every address of
the new one is on it, and its words are the same or nearly (`sent_twice.same_words`). Then nothing is
written: Rouh is told the draft's id, so "send it" sends that one, and says it was already there.
Writing a second one on purpose is `even_if_drafted`.

No model is asked, nothing is kept and nothing is changed.

**Whose.** The person's own Google connection, by `org_id` and `user_id`.

**Its switch** is `draft_twice` (`rouh/switches.py`): off, a draft is written as asked.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

log = logging.getLogger("rouh.draft_twice")

SWITCH = "draft_twice"
TITLE = "Not drafted twice: the same draft already in Drafts is not made again"

#: How many drafts to the same person are compared.
LOOK = 10

FIELD = {"type": "boolean",
         "description": "Write the draft although the same one (same people, subject and words) is already in "
                        "Rouh's Drafts: only when the person says they want a second copy, after being told."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def said(draft: dict, zone) -> str:
    at = float(draft.get("at") or 0)
    when = (" since " + datetime.fromtimestamp(at, zone).strftime("%A %-d %B at %H:%M")) if at else ""
    ago = int((time.time() - at) // 60) if at else 0
    lately = f", {ago} minutes ago" if 0 < ago < 120 else ""
    return ("Not drafted again: the same draft is already in Rouh's Drafts"
            f"{when}{lately}: {draft.get('subject') or '(no subject)'!r} to {draft.get('to') or 'the same people'}, "
            f"with the same words (draft id {draft.get('draft_id')}). Tell the person it is already there. "
            "To send it, call send_mail with that draft_id. Only if they say they want a second copy, call "
            "draft_mail again with even_if_drafted.")


async def check(gmail, *, to: str, cc: str, bcc: str, subject: str, body: str, zone) -> tuple[str, dict | None]:
    """(what to tell the model, the draft already there) or ("", None) when it is new."""
    from .sent_twice import addresses, same_email, subject_of

    wanted = addresses(to, cc, bcc)
    if not wanted:
        return "", None
    first = sorted(addresses(to) or wanted)[0]
    for one in await gmail.drafts_like(f"to:{first}", LOOK):
        if subject_of(one.get("subject") or "") != subject_of(subject):
            continue
        if same_email(one, to=wanted, subject=subject, body=body):
            return said(one, zone), one
    return "", None


__all__ = ["FIELD", "LOOK", "SWITCH", "TITLE", "check", "on", "said"]
