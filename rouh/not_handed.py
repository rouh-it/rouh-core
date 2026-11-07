"""Made, not handed over: work a task made for a named person, never shared with them, in the
morning brief.

Built by the nightly feature run, night 28, 31 October 2026 (task 94, idea I-167). ‹His› Work
tasks often end with something made for somebody else: an explainer and a specification for a
developer to build from (task 150, "Hand it to Ivo", open since 27 October 2026, "Ivo has not been
given it yet"), a deck to send to a client, a page for a colleague to read. The job that made it
writes that in the task's notes and stops there, because handing it over is ‹his›: it goes in
‹his› name. Then nothing says it is still waiting; Not opened yet (`rouh/not_opened.py`) speaks
only once a page was shared, and this never was.

So, while its switch is on, the morning brief has a section **Made, not handed over**: each open
item in a task's Where this stands (`rouh/open_items.py`) that says to hand, send, give, share,
show or forward something to a person by name, whose task has not been shared with anybody of
that name, nor with anybody at all since the line was written (a name in the notes is often what
people call them, not what their account says), and that has stood in the notes for at least `AFTER_DAYS` days (by `git blame` of the
line, or when the notes were written for a line not committed yet). It says the task, what is to be handed to whom, in the notes' own words, and since when;
**Open the task** opens it, where Share is; **Handed over** puts it away (when it went another way,
by email or in a meeting), with Undo. No model is asked.

**Whose.** The owner's own workspace and the owner's own shares (`page_guests`, by `org_id` and
`user_id`); what ‹he› put away is ‹his› own setting (`user_settings`, `not_handed`).

**Its switch** is `not_handed` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

log = logging.getLogger("rouh.not_handed")

SWITCH = "not_handed"
TITLE = ("Made, not handed over: work a task made for a named person that was never shared with "
         "them, in the morning brief, with Open the task and Handed over")
KEPT = "not_handed"
#: How long an item stands in the notes before it is said, and the most lines a morning.
AFTER_DAYS = 2
MOST = 5
#: "Hand it to Ivo", "send the deck to Maria", "share the page with Tom": the verb, a few words, then
#: to or with and a capitalised name.
_HANDING = re.compile(
    r"\b(?:hand|send|give|share|show|forward|pass)\b(?:\s+(?!to\b|with\b)[\w'-]+){0,4}?\s+"
    r"(?:to|with)\s+(?P<name>[A-Z][\w-]+(?:\s+[A-Z][\w-]+)?)", re.IGNORECASE)
_NOT_PEOPLE = {"Rouh", "Drive", "Google", "Slack", "Telegram", "Gmail", "GitHub", "The", "A", "An",
               "It", "This", "Them", "Everyone", "Everybody", "Main", "Sopharma"}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def to_whom(text: str) -> str:
    """The person an item says to hand something to, or ""."""
    plain = re.sub(r"(\*\*|__|`)", "", text)
    for found in _HANDING.finditer(plain):
        name = found.group("name")
        first = name.split()[0]
        if first[0].isupper() and first not in _NOT_PEOPLE:
            return name
    return ""


def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _shared_with(who, folder: str) -> list[tuple[str, float]]:
    """Everybody any page of the task, or the task itself, was shared with: (names and address,
    when it was shared)."""
    from .models import PageGuest, User

    rows = list(PageGuest.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "")
                .values("rel", "email", "guest_id", "created_at"))
    mine = [r for r in rows if r["rel"].startswith(folder + "/") or r["rel"] == folder
            or r["rel"].startswith("_task/" + folder)]
    names = {str(u.pk): f"{u.first_name} {u.last_name}".strip()
             for u in User.objects.filter(pk__in=[int(r["guest_id"]) for r in mine
                                                  if str(r["guest_id"]).isdigit()])}
    return [(f"{names.get(str(r['guest_id']), '')} {r['email']}".strip(), float(r["created_at"] or 0))
            for r in mine]


def _since(root, rel: str, line: int) -> float:
    """When the item's line was written: by `git blame`, or, for a line not committed yet or a
    workspace with no history, when the notes were last written."""
    notes = Path(str(root)) / rel / "AGENTS.md"
    try:
        done = subprocess.run(
            ["git", "blame", "--porcelain", "-L", f"{line + 1},{line + 1}", "--",
             f"{rel}/AGENTS.md"], cwd=str(root), capture_output=True, text=True, timeout=10)
        said = done.stdout or ""
    except (OSError, subprocess.SubprocessError):
        said = ""
    found = re.search(r"^author-time (\d+)$", said, re.MULTILINE)
    if found and "\nauthor Not Committed Yet\n" not in said:
        return float(found.group(1))
    try:
        return notes.stat().st_mtime
    except OSError:
        return 0.0


def found(who, root, now: float | None = None) -> dict | None:
    """{items: [...]} for the brief, or None when nothing made for somebody waits to be handed over."""
    from . import clock, comments_by, open_items
    from .models import Task

    now = now or time.time()
    put_away = kept(who)
    out = []
    tasks = Task.objects.exclude(state="done").exclude(archived_at__isnull=False).order_by("number")
    for task in tasks.values("number", "folder", "title"):
        folder = str(task["folder"] or "")
        if not folder:
            continue
        got = open_items.read(root, folder)
        if got is None:
            continue
        for item in open_items.items(got[1]):
            name = to_whom(item["text"])
            if not name:
                continue
            key = f"{folder}:{item['key']}"
            if key in put_away:
                continue
            since = _since(root, folder, item["line"])
            if not since or now - since < AFTER_DAYS * 86400:
                continue
            # Shared with them, or with anybody since the line was written: a name in the notes is
            # often what people call them ("Ivo"), not what their account says ("Ivaylo").
            shared = _shared_with(who, folder)
            if any(comments_by.matches(name, one) or at >= since for one, at in shared):
                continue
            day = datetime.fromtimestamp(since, clock.zone_of(who))
            out.append({"key": key, "number": task["number"], "title": task["title"] or folder,
                        "link": "/task/" + folder, "person": name,
                        "words": open_items._plain(item["text"])[:600],
                        "since": f"{day.day} {day.strftime('%B')}",
                        "days": int((now - since) // 86400)})
    out.sort(key=lambda one: -one["days"])
    return {"items": out[:MOST], "count": len(out)} if out else None


async def again(who, brief: dict, root) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("not_handed", None)
    try:
        if who is None or not root or not await sync_to_async(on)(who):
            return
        got = await sync_to_async(found)(who, root)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("what was made and not handed over could not be read")
        return
    if got:
        from . import evolution

        brief["not_handed"] = {"ok": True, "source": "Your tasks' notes and your shares", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} things made and not handed over")


class Refused(ValueError):
    """What cannot be done with a line, in a sentence."""


def act(who, key: str, what: str) -> dict:
    """Open the task (kept as a use), Handed over, or Undo it."""
    from . import evolution

    if what == "task":
        evolution.used(SWITCH, "task", who=who, detail="opened a task whose work is not handed over")
        return {"ok": True}
    held = kept(who)
    if what == "handed":
        held[key] = {"at": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "handed", who=who, detail="said a task's work was handed over")
        return {"ok": True}
    if what == "undo":
        held.pop(key, None)
        _keep(who, held)
        return {"ok": True}
    raise Refused("Open the task, Handed over, or Undo.")


__all__ = ["KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found", "on", "to_whom"]
