"""Not shared twice: a file is not shared again with somebody who can already open it.

Built by the nightly feature run, night 46 of the ledger (17 November 2026, task 94).
"Share the deck with Dana" is said without remembering that Dana already has it. Rouh then gave the
same access again (`Drive.share_with_person`, a new permission for every name), and Google sent Dana
its invitation mail a second time from ‹his› account: a client reads "Alex shared a document with
you" for a document they have had for a month. Asked for less than they have ("let Dana read it"
when she can edit), the share could take her edit right down without anybody meaning it.

So, while its switch is on, before Rouh shares a file with named people (`share_drive_file`,
`create_doc` and every tool that shares through `ToolRegistry._share`), it reads who can already open
the file, once (`Drive.permissions`), and for each person named:

- somebody who can already do as much as asked, or more (read < comment < edit < owner), is not
  shared it again, and Google sends them nothing; the answer says so ("Dana could already edit it");
- everybody else is shared it as before, and a person asked to be given more than they have is given
  it (Drive changes their access in place).

Nothing is kept and no model is asked. A file whose sharing cannot be read is shared as asked.

**Whose.** The person's Google connection, by `org_id` and `user_id`.

**Its switch** is `share_twice` (`rouh/switches.py`): off, every name is shared as asked, as before.
"""
from __future__ import annotations

SWITCH = "share_twice"
TITLE = "Not shared twice: a file is not shared again with somebody who can already open it"

#: How much each role may do, so "as much as asked, or more" is one comparison.
RANK = {"reader": 1, "commenter": 2, "writer": 3, "fileOrganizer": 4, "organizer": 5, "owner": 6}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def already(held: list[dict], email: str, role: str) -> str:
    """The role a person named already has that is as much as `role` or more, or "".

    Only their own permission counts: a link anyone can open, or their company's, is not
    them being on the file, and sharing with them by name still adds what those do not
    (it shows in their Shared with me)."""
    address = (email or "").strip().lower()
    if not address:
        return ""
    wanted = RANK.get(role or "reader", 1)
    best = ""
    for one in held:
        if one.get("kind") not in ("user", "group") or str(one.get("email") or "").lower() != address:
            continue
        if RANK.get(one.get("role") or "", 0) >= wanted and RANK.get(one.get("role") or "", 0) > RANK.get(best, 0):
            best = one.get("role") or ""
    return best


def said(email: str, role: str) -> str:
    """The words for one person not shared again."""
    from .google_api import can

    if role == "owner":
        return f"{email} owns it, so it was not shared with them again"
    return f"{email} could already {can(role)} it, so it was not shared again and Google sent them nothing"


__all__ = ["RANK", "SWITCH", "TITLE", "already", "on", "said"]
