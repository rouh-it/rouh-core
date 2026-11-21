"""What you were looking at goes with a change you ask for: a job to change Rouh is told the screen.

Built by the nightly feature run, night 50 of the ledger (21 November 2026, task 94), for the
person's guidance that half of what is built helps build Rouh faster.

The person asks Rouh to change itself while looking at the thing to change: "this button is in
the wrong place", "the count here is wrong", "make this page say when it last changed". The job
that does it (`improve_myself`) was handed only the brief Rouh's model wrote, and the model had to
remember to say which screen "this" was and copy the conversation into it. When it did not, the
job spent its first minutes finding the screen, or asked, or changed the wrong one.

So, while its switch is on, every message from the page carries the address of the screen it
was sent from (`where`, `app/controls.js`): only Rouh's own address, such as
`/anatomy/connections/email` or `/task/rouh/assistant/94`, never anything on it. A job started to
change Rouh in that turn gets two short sections added to its brief by code: the address the
person had open, and the conversation's last few messages, newest last, each cut short. No
model, nothing kept beyond the run's own brief.

**Whose.** The person whose turn it is, and their own conversation.

**Its switch** is `fix_context` (`rouh/switches.py`): off, the brief is the model's alone, as before.
"""
from __future__ import annotations

import contextvars
import logging
import re

log = logging.getLogger("rouh.fix_context")

SWITCH = "fix_context"
TITLE = "What you were looking at goes with a change you ask for: the screen and the last messages"

#: The address of the screen the turn's message was sent from, set around the turn (`runtime`).
WHERE: contextvars.ContextVar[str] = contextvars.ContextVar("fix_context_where", default="")

#: How many of the conversation's messages go with it, and how much of each.
MESSAGES = 6
EACH = 600

_ADDRESS = re.compile(r"^/[A-Za-z0-9/_.\-~%]*(\?[A-Za-z0-9=&_.\-~%/:+]*)?$")


def take(sent) -> str:
    """The address a message said it was sent from, checked: Rouh's own path, or ""."""
    text = str(sent or "").strip()[:300]
    if not text or not _ADDRESS.match(text) or text.startswith("//"):
        return ""
    return text


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _line(row: dict) -> str:
    role = "You" if row.get("role") == "user" else "Rouh"
    words = " ".join(str(row.get("text") or "").split())
    if len(words) > EACH:
        words = words[:EACH].rstrip() + " ..."
    return f"- {role}: {words}" if words else ""


def added(who, memory, chat: str) -> str:
    """The sections added to a brief to change Rouh, or "" when there is nothing to add."""
    if who is None or not on(who):
        return ""
    where = WHERE.get()
    lines: list[str] = []
    if chat and memory is not None:
        try:
            rows = memory.transcript(chat, limit=MESSAGES + 1) or []
        except Exception:  # noqa: BLE001 - the screen alone is still worth telling
            log.warning("fix_context: the conversation could not be read", exc_info=True)
            rows = []
        rows = [r for r in rows if r.get("role") in ("user", "assistant") and not r.get("notice")]
        lines = [x for x in (_line(r) for r in rows[-MESSAGES:]) if x]
    if not where and not lines:
        return ""
    out = ["", "Where the person was when they asked for this change (added by Rouh's code, not "
           "written by the model):"]
    if where:
        out.append(f"- They had this screen of Rouh open: {where}. When the brief says \"this\" or "
                   "\"here\", it is most likely that screen.")
    if lines:
        out.append("- The conversation just before, newest last:")
        out.extend("  " + x for x in lines)
    return "\n".join(out)


def told(who, where: str) -> None:
    """A job to change Rouh was told the screen and the conversation: its use."""
    from . import evolution

    evolution.used("fix_context", "told", who=who, detail=str(where or "")[:60])
