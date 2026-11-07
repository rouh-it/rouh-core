"""The one thing: the single task that makes today a win if nothing else happens.

Petar, 29 September 2026 (fr_8435b9dc8732): "I would like my morning brief to
have 'The one thing': the single task that makes today a win if nothing else
happens. But since it wouldn't know what it is, I want a picker. Category,
task and sub task maybe."

So it is the first section of the brief (`briefpage.js`), and the person picks
it; nothing here guesses or suggests one. The picker goes a level at a time:

    category    a project inside Work or Personal, the task browser's own
                category buttons (`objectindex.index_data`)
    task        a task filed under that project and not archived; a done one
                too, after the live ones and marked Done
    sub task    one of that task's steps, or none: it is optional

Those are Rouh's own, read from the same rows the task browser draws, so the
picker never keeps a second list of anything. At every level the person may
also type an entry of their own instead, so a category with no tasks in it, or
a machine with no workspace at all, never leaves them stuck. A typed entry is
only words on today's choice: it does not make a project or a task.

**Whose, and for how long.** One person's, kept as a `UserSetting` row keyed on
`user_id` and `org_id` like the brief's own settings. The choice carries the day
it was made for, on the person's own clock, and is only handed back on that day,
so each morning starts with nothing chosen.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger("rouh.one_thing")

#: The person's own settings row (`models.UserSetting`) the choice is kept in.
SETTING = "morning_brief_one_thing"

#: How long a name at any level may be.
LONGEST = 200

LEVELS = ("category", "task", "sub")


class Refused(ValueError):
    """A choice that cannot be kept, in words the page shows as they are."""


def _today(who) -> str:
    from . import morning_brief

    return morning_brief.today_of(who)


def chosen(who) -> dict | None:
    """Today's one thing for this person, or None when nothing is chosen today."""
    from .models import UserSetting

    value = (UserSetting.objects
             .filter(user_id=str(who.user_id), org_id=who.org_id or "", name=SETTING)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else None
    except (TypeError, ValueError):
        return None
    if not isinstance(held, dict) or held.get("day") != _today(who):
        return None
    if not (isinstance(held.get("category"), dict) and isinstance(held.get("task"), dict)):
        return None
    return held


def _level(sent, what: str, required: bool) -> dict | None:
    if sent in (None, "", {}):
        if required:
            raise Refused(f"Pick or type a {what} first.")
        return None
    if isinstance(sent, str):
        sent = {"name": sent}
    if not isinstance(sent, dict):
        raise Refused(f"The {what} is a name.")
    name = " ".join(str(sent.get("name") or "").split())
    if not name:
        if required:
            raise Refused(f"Pick or type a {what} first.")
        return None
    if len(name) > LONGEST:
        raise Refused(f"The {what} is at most {LONGEST} characters.")
    ident = str(sent.get("id") or "")[:120]
    return {"id": ident, "name": name, "typed": not ident}


def choose(who, sent: dict) -> dict:
    """Keep what the picker sent, {category, task, sub}, as today's one thing."""
    from .models import UserSetting

    kept = {"day": _today(who),
            "category": _level(sent.get("category"), "category", True),
            "task": _level(sent.get("task"), "task", True),
            "sub": _level(sent.get("sub"), "sub task", False),
            "chosen_at": time.time()}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=SETTING,
                     value=json.dumps(kept, ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])
    return kept


def clear(who) -> None:
    """Nothing chosen for today any more."""
    from .models import UserSetting

    UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "",
                               name=SETTING).delete()


def options() -> dict:
    """Every category, the live tasks in each, and each task's steps, for the picker.

    From the task browser's own rows (`objectindex.index_data`). A machine with
    no workspace Rouh can draw has none of them, and says so in `note`: the
    picker then takes typed entries only.
    """
    from . import objectindex, pages
    from .config import config

    root = config.assistant_repo or ""
    if not root or not os.path.isdir(root) or not objectindex.has_tree(root):
        return {"ok": True, "categories": [], "tasks": [],
                "note": "There are no projects on this machine yet, so type your own."}
    try:
        data = objectindex.index_data(objectindex._ready(root), root)
    except pages.Refused as exc:
        return {"ok": True, "categories": [], "tasks": [], "note": str(exc)}
    sides = {side["id"]: side["name"] for side in data["sides"]}
    categories = [{"id": cat["id"], "name": cat["name"], "side": sides.get(cat["side"], "")}
                  for cat in data["categories"]]
    # A done task is offered too, after the live ones. Until 1 October 2026 it
    # was left out, and Done is only what its last job said: task 74 was
    # marked Done when its first explainer was delivered, Petar asked for a
    # second subtask in it the next day, and then could not find it here to
    # make it his one thing (fr_76280d8ad25c). Archived is the person's own
    # "put away", and that keeps a task out; so does one made for somebody else
    # (`rouh/task_origin.py`), which is not his one thing to do.
    tasks = []
    for task in data["tasks"]:
        if task["archived"] or not task["category"] or (task.get("made") or {}).get("kind") == "other":
            continue
        subs = [{"id": step["href"], "name": step["title"], "n": step["num"]}
                for step in task["steps"]]
        tasks.append({"id": task["id"], "name": task["name"], "n": task["n"],
                      "category": task["category"], "done": task["status"] == "done",
                      "subs": subs})
    tasks.sort(key=lambda t: t["done"])
    return {"ok": True, "categories": categories, "tasks": tasks, "note": ""}
