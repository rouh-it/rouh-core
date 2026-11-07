"""Drafts learn your edits: how Petar rewrote the emails Rouh drafted, recorded for a later look.

Built by the nightly feature run, night 11, 14 October 2026 (task 94, idea I-052, "drafts that
sound like him"). Rouh drafts an email as a card he can write in (`rouh/composing.py`): the
fields, the body, and Send. When he changes the draft before he presses Send, what he changed is
the plainest lesson there is about how he writes - the greeting he uses instead of Rouh's, the
sentence he cut, the sign-off.

**Recorded only, since mutation request 2** (16 October 2026). Petar: "We keep only the
recording part of this feature. Don't modify responses. For now we will log changes and one day
when we have hundreds of changes we can run an analysis and consider how writing should
improve. So logging also and this gene should be accessible somewhere and I should be able to
click somewhere and see the logs". So when he sends a draft card he changed, the draft as Rouh
wrote it, the email as it went and each place they differ are kept as a row of `draft_edits`
(`keep`), every one, and nothing reads them back into a turn's prompt: the first version's block
beside the clock is gone. He reads them in Anatomy, Behaviour, Draft edits
(`/anatomy/behaviour/draft-edits`, `draftedits.js`, `listing`). A draft he sends unchanged has
nothing to record.

**No model call of its own.** The changed lines are found by code (`difflib`, line by line, the
quoted earlier message left out); nothing is sent anywhere.

**Whose.** Kept under the user and organisation the card was sealed for, and listed for the
signed-in person only, both ids in every query.

**Its switch** is `draft_edits` (`rouh/switches.py`), off until Petar keeps it in Mutations: off,
nothing is recorded; what was recorded is still listed.
"""
from __future__ import annotations

import difflib
import logging
import time

log = logging.getLogger("rouh.draft_edits")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "draft_edits"
TITLE = "Draft edits: every change you make to an email Rouh drafted, recorded before it is sent"
#: The compose action this records: an email's Send (`tools.py`, `_mail_block`).
ACTION = "send_mail"
#: How much of each side of a change, and of a whole draft's body, is kept.
SIDE_CHARS = 2000
BODY_CHARS = 20000
#: How many a page of the listing holds.
PAGE = 50


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def _lines(markup: str) -> list[str]:
    """The body as plain lines, without the quoted earlier message or blank lines."""
    from .composing import as_text

    out = []
    for line in as_text(markup).split("\n"):
        line = " ".join(line.split())
        if line and not line.startswith(">"):
            out.append(line)
    return out


def _field(block_: dict, name: str) -> str:
    for one in block_.get("fields") or []:
        if str(one.get("name") or "") == name:
            return " ".join(str(one.get("value") or "").split())
    return ""


def drafted(block_: dict) -> dict:
    """The draft as Rouh first wrote it: the card's `first`, kept when it was drawn, since the
    card itself keeps what he types as he goes (`composing.block`); the block itself without one."""
    first = block_.get("first")
    if not isinstance(first, dict):
        return block_
    return {"fields": [{"name": k, "value": v} for k, v in (first.get("fields") or {}).items()],
            "body": first.get("body") or ""}


def changes(was: dict, sent: dict) -> list[dict]:
    """Each place the sent email differs from the draft: {part, was, now}, the lines Rouh wrote
    and the lines he sent instead (either may be empty), in order. The subject is one of them."""
    out = []
    before, after = _field(was, "subject"), _field(sent, "subject")
    if before != after:
        out.append({"part": "subject", "was": before, "now": after})
    a, b = _lines(was.get("body") or ""), _lines(sent.get("body") or "")
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        out.append({"part": "body", "was": "\n".join(a[i1:i2])[:SIDE_CHARS],
                    "now": "\n".join(b[j1:j2])[:SIDE_CHARS]})
    return out


def _whole(block_: dict) -> dict:
    """A draft or a sent email as it is kept: its fields by name, and its body as plain text."""
    from .composing import as_text

    return {"fields": {str(f.get("name") or ""): str(f.get("value") or "")
                       for f in block_.get("fields") or [] if f.get("name")},
            "body": as_text(block_.get("body") or "")[:BODY_CHARS]}


def keep(user_id: str, org_id: str, action: str, was: dict, sent: dict, *, card: str = "",
         chat: str = "") -> bool:
    """Record what he changed in a draft he has just sent from its card. True when something was
    recorded; nothing when the switch is off, it is not an email, or he changed nothing. Never
    raises."""
    try:
        if action != ACTION or not user_id or not on(org_id):
            return False
        first = drafted(was)
        found = changes(first, sent)
        if not found:
            return False
        from .models import DraftEdit

        DraftEdit.objects.create(user_id=str(user_id), org_id=str(org_id or ""), at=time.time(),
                                 card=str(card or ""), chat=str(chat or ""),
                                 to=_field(sent, "to")[:500], subject=_field(sent, "subject")[:500],
                                 drafted=_whole(first), sent=_whole(sent), changes=found)
        from . import evolution
        from .tenancy import Identity

        evolution.used(SWITCH, "edits_learned", who=Identity(user_id=str(user_id), org_id=str(org_id or "")),
                       detail=f"recorded {len(found)} edits to the draft to {_field(sent, 'to')[:80]}")
        log.info("draft edits: recorded %d changes to a draft to %s", len(found), _field(sent, "to")[:80])
        return True
    except Exception:  # noqa: BLE001 - recording a send is never worth the send
        log.exception("the edits to a sent draft could not be recorded")
        return False


def listing(me, before: int = 0) -> dict:
    """The signed-in person's recorded edits, newest first, a page at a time: those older than
    the row `before` when it is given. `more` says whether older ones are left."""
    from .models import DraftEdit

    rows = DraftEdit.objects.filter(org_id=str(me.org_id), user_id=str(me.user_id))
    total = rows.count()
    if before:
        rows = rows.filter(id__lt=int(before))
    got = list(rows.order_by("-id")[:PAGE + 1])
    return {"on": on(me.org_id), "total": total, "more": len(got) > PAGE,
            "edits": [{"id": r.id, "at": r.at, "card": r.card, "chat": r.chat, "to": r.to,
                       "subject": r.subject, "changes": r.changes, "drafted": r.drafted, "sent": r.sent}
                      for r in got[:PAGE]]}


__all__ = ["ACTION", "SWITCH", "TITLE", "changes", "keep", "listing", "on"]
