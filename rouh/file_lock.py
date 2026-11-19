"""Lock a Drive file: asked, Rouh locks a file so nobody can change it, and unlocks it again.

Built by the nightly feature run, night 48 of the ledger (19 November 2026, task 94).
A signed contract, a proposal already sent, the price list that went out: once it is final, a file
in Drive stays as editable as the day it was shared, by everybody it was shared with as an editor,
and by Rouh. Google Drive has had a lock for this since 2022 (a content restriction): while it
stands, nobody can change the file's content, whatever their access, until somebody who may edit
it unlocks it. Only Drive's own page could set it; asking Rouh could rename, move or share a file,
never lock it.

So, while its switch is on, `manage_drive_file` takes `lock`: "on" locks the file, with the reason
said beside it in Drive ("Signed on 19 November 2026" when the person gives none), and "off"
unlocks it. Rouh says what it did in the person's words: that nobody can change it now, who can
still open and comment, and how to unlock it. A file already locked or already open is said so, and
nothing changes. A file the person may not lock (they can only view or comment) is refused with why.
No model is asked, and the file's content and sharing are never touched.

**Whose.** The person's own Google connection, by `org_id` and `user_id`.

**Its switch** is `file_lock` (`rouh/switches.py`): off, `lock` is refused, and nothing changes.
"""
from __future__ import annotations

from datetime import date

SWITCH = "file_lock"
TITLE = "Lock a Drive file: asked, Rouh locks a file so nobody can change it, and unlocks it again"

FIELD = {"type": "string", "enum": ["on", "off"],
         "description": "Lock the file so nobody, the person included, can change its content until it is "
                        "unlocked (on), or unlock it (off). Its sharing and its comments are unchanged. Use it for "
                        "'lock the signed contract', 'make it read-only for everybody', 'unlock the price list'."}
REASON = {"type": "string",
          "description": "With lock on: why, shown beside the lock in Drive, such as 'Signed by both sides'. "
                         "Left out, it says the day it was locked."}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def wanted(value) -> bool | None:
    """True to lock, False to unlock, None when nothing was asked."""
    low = str(value or "").strip().lower()
    if low in ("on", "lock", "locked", "true", "yes"):
        return True
    if low in ("off", "unlock", "unlocked", "false", "no"):
        return False
    return None


def default_reason(today: date) -> str:
    return f"Locked by Rouh on {today.day} {today.strftime('%B %Y')}, asked by its owner"


def said(name: str, file_id: str, *, locked: bool, was: bool, reason: str = "", by: str = "") -> str:
    """What Rouh tells the person, from what Drive says now."""
    shown = repr(name or file_id)
    if locked and was:
        return (f"{shown} was already locked" + (f" ({reason})" if reason else "")
                + (f", by {by}" if by else "") + ": nobody can change it, and nothing was changed - "
                f"file id {file_id}")
    if not locked and not was:
        return f"{shown} was not locked, so anybody who may edit it still can; nothing was changed - file id {file_id}"
    if locked:
        return (f"Locked {shown} in Drive" + (f" ({reason})" if reason else "")
                + ": nobody can change its content now, you included, whatever their access; "
                  "everybody it is shared with can still open it, and comment where they could. "
                  f"Say unlock it to open it for changes again - file id {file_id}")
    return (f"Unlocked {shown} in Drive: whoever may edit it can change it again - file id {file_id}")


__all__ = ["FIELD", "REASON", "SWITCH", "TITLE", "default_reason", "on", "said", "wanted"]
