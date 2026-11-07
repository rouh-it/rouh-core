"""Remind them: beside a person in the Share panel who has not opened what was shared with them, a
button that opens a new email to them in Gmail, with their link.

Built by the nightly feature run, night 25, 28 October 2026 (task 94, idea I-156). Who opened it
(`rouh/share_opens.py`, kept on 27 October 2026) says "Not opened yet" beside a person in the Share
panel, and stops there: the next step, asking them to look, was a new email ‹he› wrote by hand,
finding their address and the page's link again. ‹He› shares Work pages with clients and
colleagues before a meeting or a decision (task 150's explainer and spec, 27 October 2026; task
148's explainer, 26 October), and the one who has not opened it is the one to write to.

So, while its switch is on, the Share panel's row for each person shared with by hand whose
invitation went out at least `AFTER_HOURS` ago and who has not opened it since has **Remind
them**. It opens Gmail's own new-message window in ‹his› own mailbox, to them, with the page's
name as the subject and a short note with their own link (`not_opened.compose_link`, the same
note the morning brief's Not opened yet writes), so the reminder is in ‹his› words once ‹he› has
read it, and Rouh sends nothing. A share a trusted contact's tick keeps has no button: it was
never sent to be read.

**Whose.** The owner's own shares, as the panel already reads them (`share_opens.with_opens`).

**Its switch** is `share_remind` (`rouh/switches.py`), and it needs `share_opens` on, since without
it nothing says who has not opened it: off, the row is as it was.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("rouh.share_remind")

SWITCH = "share_remind"
TITLE = ("Remind them: beside a person who has not opened what you shared, a button that opens a "
         "new email to them in Gmail with their link")
#: How long after the invitation the button is offered.
AFTER_HOURS = 24


def on(who) -> bool:
    from . import share_opens, switches

    org = getattr(who, "org_id", None) or None
    return switches.on(SWITCH, org) and share_opens.on(org)


def with_remind(who, people: list[dict], rel: str) -> list[dict]:
    """The panel's people, each who may be reminded with `remind`, the Gmail address to open."""
    try:
        if who is None or not people or not on(who):
            return people
        from . import inboxes, not_opened
        from .web import guests

        shares = {p["token"]: p for p in guests._store().people(who, rel)} if rel else {}
        mine = inboxes.theirs(who)
        inbox = mine[0].email if mine else ""
        base = not_opened._base()
        now = time.time()
        out = []
        for p in people:
            row = shares.get(p.get("token") or "") or {}
            made = float(row.get("created_at") or 0)
            if (p.get("token") and "opened" in p and not p["opened"] and p.get("via") != "tick"
                    and p.get("mailed") and not p.get("mail_error") and not row.get("pending")
                    and made and now - made >= AFTER_HOURS * 3600):
                link = (base + "/shared/" + p["token"]) if base else ""
                p = dict(p, remind=not_opened.compose_link(inbox, p.get("email") or "",
                                                           row.get("title") or "the page", link))
            out.append(p)
        return out
    except Exception:  # noqa: BLE001 - the panel is drawn as it was
        log.warning("Remind them could not be worked out for the Share panel", exc_info=True)
        return people


def pressed(who) -> None:
    """The press on Remind them, kept as its use."""
    from . import evolution

    evolution.used(SWITCH, "reminded", who=who,
                   detail="opened a reminder to somebody who had not opened a shared page")


__all__ = ["AFTER_HOURS", "SWITCH", "TITLE", "on", "pressed", "with_remind"]
