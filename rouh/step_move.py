"""Move a step: asked in words, Rouh moves a step into another task, or out into a task of its own.

Built by the nightly feature run, night 25, 28 October 2026 (task 94, idea I-155). A step can be
moved by hand: dragged onto another task in the task browser, or Move, Promote to task and Move
to new task in its three dots (`rouh/moving.py`, asked for on 29 September and 22 October 2026).
Asked in words, Rouh could move only a whole task into another project (`move_task`); a step it
could not move at all. Jobs keep putting work where it does not belong and then cannot put it
right: on 26 and 27 October 2026 five jobs asked Rouh to make or change steps they could not, one
to take work out of task 148 that was not about it, and a drafted email ended up where it could
not be found.

So, while its switch is on, the tool `move_step` moves the step the person names, by its number
("93-07", "93 dash 7"), by words of its name, or the step the chat is in: into another task
("move 93-07 into 148"), out as a task of its own ("make 98-24 its own task"), or out as the first
step of a new task ("move 150-02 to a new task called CCE pilot"). It is the very move the three
dots make (`moving.move`), renumbered to fit where it lands, with the number it had kept so
searching the old number still finds it. A job may use it too (it changes the person's own
workspace, so it goes through the approval queue like `move_task`).

**No model call of its own.** It is a tool in the turn already being taken.

**Whose.** The workspace's own register of tasks (`objects`), as Move by hand writes it.

**Its switch** is `step_move` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.step_move")

SWITCH = "step_move"
TITLE = ("Move a step: asked in words, Rouh moves a step into another task, or out into a task "
         "of its own")
TOOL_NAME = "move_step"
#: Where a step goes when it is not another task.
OWN, NEW = "own task", "new task"
DESCRIPTION = (
    "Move a step (a numbered subtask such as 93-07) because the person has just asked: 'move "
    "93-07 into 148', 'put this step under task 61', 'make 98-24 its own task', 'move 150-02 to a "
    "new task called CCE pilot'. It is the same move as Move in the step's three dots: its "
    "folder, chats, files and pages go with it, and it takes the next number where it lands. "
    "Give `what` the way they said it (a number such as 93-07 or '93 dash 7', or words of its "
    "name), or leave it out for the step this chat is in. Give `to` a task or step the same way, "
    "or 'own task' to make it a task of its own in the same project, or 'new task' with `name` "
    "for a new task it becomes the first step of. To move a whole task into another project, use "
    "move_task instead. If a name fits several, nothing moves and you are told which: ask them "
    "which one. Only on the person's own words. Say its number before and after, in a few words.")
SCHEMA = {
    "type": "object",
    "properties": {
        "what": {"type": "string",
                 "description": "The step: its number (93-07) or words of its name. Left out, "
                                "the step this chat is in."},
        "to": {"type": "string",
               "description": "Where it goes: a task or step (148, 61-04, or words of its name), "
                              "'own task', or 'new task'."},
        "name": {"type": "string",
                 "description": "For 'new task': what the new task is called, as they said it."},
    },
    "required": ["to"],
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _where(to: str) -> str:
    """`OWN`, `NEW`, or "" for a task named some other way."""
    said = " ".join(str(to or "").lower().replace("-", " ").split())
    if said in ("own task", "its own task", "a task of its own", "task of its own", "promote",
                "own", "a task"):
        return OWN
    if said in ("new task", "a new task", "new"):
        return NEW
    return ""


def move(who, ident: str, to: str, name: str = "") -> dict:
    """Move step ``ident`` to ``to``: ``{"ok", "was", "now", "into", "did"}`` or ``{"ok": False,
    "why"}``."""
    from . import evolution, moving, objecttree, owning, pinning

    st = owning.store()
    row = st.get_task(ident) if st is not None else None
    if row is None or not row.folder:
        return {"ok": False, "why": "There is no such step. Nothing was moved."}
    was = pinning.number_of(row.slug, getattr(row, "number", None))
    if getattr(row, "number", None) is not None:
        return {"ok": False, "why": f"{was} is a task, not a step. To move a task into another "
                                    "project, use move_task. Nothing was moved."}
    kind = _where(to)
    if kind == OWN:
        where, into = moving.PROMOTE, "a task of its own"
    elif kind == NEW:
        where, into = moving.NEW_TASK, "a new task"
    else:
        found = pinning.find(to)
        if not found.get("ok"):
            more = found.get("choices") or []
            return {"ok": False, "why": (found.get("why") or "Where it should go could not be found.")
                    + (" It could be: " + "; ".join(more) + "." if more else "")
                    + " Nothing was moved."}
        if found["id"] == ident:
            return {"ok": False, "why": "A step cannot go into itself. Nothing was moved."}
        rows, owners, _under = objecttree.tree_now(st)
        if owners.get(ident) == found["id"]:
            return {"ok": False, "why": f"{was} is already in {found['name']}. Nothing was moved."}
        where, into = found["id"], found["name"]
    done = moving.move(row.folder, where, " ".join(str(name or "").split())[:200])
    if not done.get("ok"):
        return {"ok": False, "why": (done.get("why") or "It could not be moved.") + " Nothing was moved."}
    now = str(done.get("number") or "")
    if kind == NEW:
        into = f"a new task called {' '.join(str(name or '').split())[:200] or row.title}"
    evolution.used(SWITCH, "moved", who=who, detail=f"{was} -> {now} ({into})")
    return {"ok": True, "was": was, "now": now, "into": into, "did": done.get("did") or "",
            "title": row.title or ""}


__all__ = ["DESCRIPTION", "NEW", "OWN", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "move", "on"]
