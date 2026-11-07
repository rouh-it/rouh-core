"""Show me where: every change Ask AI made to a page has Show me, which brings that part of the page
into view and lights it up for a moment.

Built by the nightly feature run, night 24, 27 October 2026 (task 94, idea I-146). A change Ask
AI makes is a line in the conversation, "Changed the page: ...", with Undo; on a long page, or on
a site of several pages in one file like task 61's, finding where it landed is scrolling and
reading. On 26 October 2026 the writer of that site read "The four process boxes are now about
half as tall", could not find them, and asked "Wait what did you change? ... not sure what
section you changed": the change was on another page of the site.

So, while its switch is on, each change line still standing has **Show me** beside Undo, in Rouh's
column and in the drawer of a page opened on its own. A press asks Rouh where the change is
(`place`, from `rouh/askai_follow.where`: the element it touched, its own words, and the heading
above it), and the page finds that element by its words, scrolls it to the middle of the screen
and lights it for two seconds. When it is on a part of the page that is not showing (another page
of a site drawn one page at a time), the line says so, with the heading it is under.

**No model call.** Where is read from the change as it was kept.

**Whose.** Only a change the reader made themselves, on the page they are on (`AskEdit`, by
`user_id` and `org_id`), read only.

**Its switch** is `askai_show` (`rouh/switches.py`): off, there is no Show me.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.askai_show")

SWITCH = "askai_show"
TITLE = ("Show me where: each change Ask AI made to a page has Show me, which brings that part of "
         "the page into view and lights it up")


class Refused(ValueError):
    """What cannot be shown, in the words the page puts in front of the reader."""


def on(who) -> bool:
    from . import switches

    return who is not None and switches.on(SWITCH, getattr(who, "org_id", None) or None)


def place(who, doc: str, edit) -> dict:
    """Where change ``edit`` is on page ``doc``, for the reader who made it.

    ``{"tag", "text", "nth", "heading"}`` (`askai_follow.where`). Refused when the switch is off,
    or the change is not this reader's, not on this page, or was put back."""
    from . import askai_follow, evolution
    from .models import AskEdit

    if not on(who):
        raise Refused("Show me is switched off (Show me where, in Evolution, Mutations).")
    try:
        ident = int(edit)
    except (TypeError, ValueError):
        raise Refused("That is not a change to this page.") from None
    row = (AskEdit.objects.filter(id=ident, user_id=who.user_id, org_id=who.org_id, doc=str(doc or ""))
           .values("before", "after", "parts", "undone_at").first())
    if not row:
        raise Refused("That change is not one of yours on this page.")
    if row["undone_at"]:
        raise Refused("That change was put back, so it is not on the page.")
    got = askai_follow.where(row["before"], row["after"], row["parts"])
    if not (got["text"] or got["heading"]):
        raise Refused("Where that change is could not be read from the page.")
    evolution.used(SWITCH, "shown", who=who, detail=f"Show me on a change under {got['heading'] or 'the page'}")
    return got


__all__ = ["Refused", "SWITCH", "TITLE", "on", "place"]
