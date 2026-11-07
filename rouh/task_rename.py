"""Rename a task: asked in words to rename a task or a step, Rouh renames it.

Built by the nightly feature run, night 24, 27 October 2026 (task 94, idea I-147). A task's name
could be changed only by hand: its own Rename, in the three dots on its line in the task browser
or at the head of its page (`owning.rename`). Asked in words, Rouh had no way to do it. On 26
October 2026 a job writing the company's explainer (task 148) asked Rouh to rename the task from
"Northwind One-Pager..." to "Northwind Explainer" and was told "None of the available tools can
... rename task 148"; it wrote the new title into the folder's `.object.json` by hand, which the
task's row, and so every screen, did not follow.

So, while its switch is on, the tool `rename_task` renames a task or a step the person names, by
its number ("148", "93-07", "93 dash 7"), by words of its name, or the task the chat is in: its
row, which every screen draws from, its folder's `.object.json` (`owning.rename`), and, for a
step, the title its task's meta gives it, so the two never disagree. The folder keeps its name,
as it does for Rename by hand, so every link to it still works. A job may use it too (it changes
the person's own workspace, so it goes through the approval queue like `move_task`).

**No model call of its own.** It is a tool in the turn already being taken.

**Whose.** The workspace's own register of tasks (`objects`), as Rename by hand writes it.

**Its switch** is `task_rename` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
from pathlib import PurePosixPath

log = logging.getLogger("rouh.task_rename")

SWITCH = "task_rename"
TITLE = "Rename a task: asked in words, Rouh renames a task or a step, everywhere it is shown"
TOOL_NAME = "rename_task"
DESCRIPTION = (
    "Give a task or a step a new name, because the person has just asked: 'rename 148 to "
    "Northwind Explainer', 'call this task Launch plan', 'rename 93-07 to Email to Jason'. Its "
    "name changes everywhere it is shown; its folder and every link to it stay as they are. "
    "Give `what` the way they said it: a number such as 148, 93-07 or '93 dash 7', or words of "
    "its present name, or leave it out for the task this chat is in. If a name fits several, "
    "nothing changes and you are told which: ask them which one. Only on the person's own "
    "words. Say the old name and the new one, in a few words.")
SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "The new name, as they said it."},
        "what": {"type": "string",
                 "description": "The task or step: its number (148, 93-07) or words of its "
                                "name. Left out, the task this chat is in."},
    },
    "required": ["name"],
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _step_title(folder: str, title: str) -> None:
    """A step's title in its task's meta, where the meta has one, made the new name too."""
    from . import taskmeta

    path = PurePosixPath(folder)
    parent, own = str(path.parent), path.name
    if not folder or parent in ("", "."):
        return

    def how(data):
        steps = (data or {}).get("steps")
        if not isinstance(steps, dict) or not isinstance(steps.get(own), dict):
            return data
        if steps[own].get("title") == title:
            return data
        steps[own] = dict(steps[own], title=title)
        data["steps"] = steps
        return data

    try:
        taskmeta.change(parent, how, by="Rouh, renaming a step")
    except Exception:  # noqa: BLE001 - the row is the name; the meta follows when it can
        log.warning("the meta of %s kept the old name of %s", parent, own, exc_info=True)


def rename(who, ident: str, name: str) -> dict:
    """Rename task or step ``ident`` to ``name``: ``{"ok", "was", "now", "number", "step"}`` or
    ``{"ok": False, "why"}``."""
    from . import evolution, owning, pinning

    name = " ".join(str(name or "").split())[:200]
    if not name:
        return {"ok": False, "why": "A name cannot be empty. Nothing was renamed."}
    st = owning.store()
    row = st.get_task(ident) if st is not None else None
    if row is None:
        return {"ok": False, "why": "There is no such task. Nothing was renamed."}
    was = row.title or row.slug or ""
    number = pinning.number_of(row.slug, getattr(row, "number", None))
    if was == name:
        return {"ok": False, "why": f"{number} is already called {name}. Nothing was renamed."}
    done = owning.rename("task", ident, name)
    if not done.get("ok"):
        return {"ok": False, "why": (done.get("why") or "It could not be renamed.") + " Nothing was renamed."}
    step = getattr(row, "number", None) is None
    if step:
        _step_title(row.folder or "", name)
    evolution.used(SWITCH, "renamed", who=who, detail=f"{number}: {was} -> {name}")
    return {"ok": True, "was": was, "now": name, "number": number, "step": step}


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "on", "rename"]
