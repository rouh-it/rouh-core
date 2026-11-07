"""Who opened it: beside each person a page or task is shared with, when they last opened it.

Built by the nightly feature run, night 18, 21 October 2026 (task 94, idea I-111). Petar shares
his Work tasks and pages with people by email: every Work task is shared with the people ticked
for it in Trusted contacts (296 task shares by 20 October 2026), and pages go to clients and
colleagues before a meeting. The Share panel said who each one was shared with and whether the
invitation went, and nothing about whether they had looked. So "did you get a chance to read
it?" was a question he asked, or a meeting he started not knowing. Google Docs' activity
dashboard, Notion's page views and DocSend answer it with "viewed on ...", which is the pattern
this copies, at its smallest.

**What is kept.** When a person opens a page or a task shared with them (`/shared/<token>`,
`rouh/web/guests.py`), one `share.opened` row goes into the event log (`rouh/events.py`), under
the ids of the owner whose share it is, never the reader's: the owner's `org_id` and `user_id`,
the actor `delegate`, and as its object a short hash of the share's token, never the token, so
the log holds no way into the page. Nothing of what they read or did there.

**What is shown.** The Share panel's row for each person says "Opened" and when they last did,
or "Not opened yet", after what it already said (`_share_state` in `rouh/web/views.py`,
`sharePerson` in `rouh/static/app/runs.js`). A visitor to the page's public link is nobody in
particular, so links are not counted.

**Whose.** Read only by the owner, by `org_id` and `user_id`, for their own shares.

**Its switch** is `share_opens` (`rouh/switches.py`): off, nothing is kept and the panel is as it
was.
"""
from __future__ import annotations

import hashlib
import logging
import time

log = logging.getLogger("rouh.share_opens")

SWITCH = "share_opens"
#: How far back an open is looked for.
LOOK_BACK_DAYS = 365


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def key(token: str) -> str:
    """What the log keeps for a share: a short hash of its token, never the token."""
    return "s-" + hashlib.sha256(str(token or "").encode()).hexdigest()[:20]


def opened(share: dict | None, reader_id: str = "") -> None:
    """A person opened what was shared with them: kept under the owner's ids. Never raises."""
    try:
        if not share or not share.get("token") or not on(share.get("org_id")):
            return
        owner = str(share.get("owner_id") or share.get("user_id") or "")
        if not owner or str(reader_id) == owner:
            return
        from . import evolution, events

        events.emit("share.opened", user_id=owner, org_id=str(share.get("org_id") or ""),
                    actor="delegate", source="web", object_type="share",
                    object_id=key(share["token"]))
        evolution.used(SWITCH, "opened_by_them", who=_owner(share),
                       detail="a person opened something shared with them")
    except Exception:  # noqa: BLE001 - keeping an open is never worth breaking the page
        log.warning("an open of a shared page could not be kept", exc_info=True)


def _owner(share: dict):
    from .tenancy import Identity

    return Identity(user_id=str(share.get("owner_id") or share.get("user_id") or ""),
                    org_id=str(share.get("org_id") or ""), name="")


def last_opens(who, tokens: list[str]) -> dict[str, float]:
    """When each share was last opened by its reader, by token, for the owner `who`."""
    keys = {key(t): t for t in tokens if t}
    if not keys:
        return {}
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT object_id, extract(epoch FROM max(occurred_at)) FROM analytics.event "
            "WHERE org_id = %s AND user_id = %s AND name = 'share.opened' "
            "AND object_type = 'share' AND object_id = ANY(%s) "
            "AND occurred_at > to_timestamp(%s) GROUP BY object_id",
            [str(who.org_id), str(who.user_id), list(keys),
             time.time() - LOOK_BACK_DAYS * 86400])
        return {keys[row[0]]: float(row[1]) for row in cur.fetchall() if row[0] in keys}


def with_opens(who, people: list[dict]) -> list[dict]:
    """The Share panel's people, each with `opened` (seconds, or 0 for not yet) while it is on."""
    try:
        if who is None or not on(getattr(who, "org_id", None)) or not people:
            return people
        found = last_opens(who, [p.get("token") or "" for p in people])
    except Exception:  # noqa: BLE001 - the panel is drawn as it was
        log.warning("when shared pages were opened could not be read", exc_info=True)
        return people
    if found:
        from . import evolution

        evolution.used(SWITCH, "seen", who=who,
                       detail=f"{len(found)} of {len(people)} opened what was shared")
    return [dict(p, opened=found.get(p.get("token") or "", 0)) for p in people]


__all__ = ["SWITCH", "key", "last_opens", "on", "opened", "with_opens"]
