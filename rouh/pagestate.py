"""A page's own settings, kept on the server for the person who chose them.

A workspace page is shown sandboxed (`pages.py`): it has no storage that lasts
past its closing and it cannot reach Rouh. So a page that wants to remember
what its reader chose - a part hidden, a tab picked - hands it to Rouh's page
around it, which saves it here, signed in, and hands it back the next time the
page opens, on any device (``stateRelay`` in cards.js).

Built 29 October 2026 for 158-05's hide and show buttons, and for any page:
Petar, "everything should be persistent storage ... for this page". He said
SQLite; it is Rouh's own PostgreSQL, so it is backed up with everything else.

**Whose.** One row a person a page (`models.PageState`): their org, their
account and the page's path. Nobody reads or writes another person's. Whoever
may open the page may keep settings on it, and the page is checked the way
Ask AI checks it (`askai.resolve`).

**What.** ``settings`` is one JSON object of the page's own keys. A write names
one key and its new value, and replaces that key's value; a value of null
removes the key. Or it hands the whole object, which replaces all of it.
Never more than `MOST` bytes for one page.

**Choices a job can read** (14 November 2026, task 185, step 185-02). Petar, on
the page where he picks what a Rouh instance has off: "I want you to make the
list with changeable options stored/saved so I can pick ... then I will pick and
choose and we will replan". A row here is in Rouh's database, which no job can
read. So a page that says so in its head, with
``<meta name="rouh-saves-choices" content="choices.json">``, has its settings
written beside it as well, whole, as ``choices.json`` in its own folder, every
time they change (`beside`), and saved into the workspace like a page Ask AI
changed (`saving._kept_in_place`). Only that one name, only in the page's own
folder, only JSON, only for the owner's organisation (never a guest), and never
more than `MOST` bytes.

**Done picking.** On such a page, setting the key ``done`` to a new value is the
person saying the choices are made: the step is marked in progress (the next
move is Rouh's) and a job is started in the task's chat to replan from the file
(`picked`). The job's brief is Rouh's own words and names only the page and the
file; nothing the page says goes into it.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rouh.pagestate")

#: The most one person's settings for one page may take, as JSON.
MOST = 64 * 1024
#: The longest key.
KEY_MOST = 200


class Refused(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _size(settings: dict) -> int:
    return len(json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode())


def read(org_id: str, user_id: str, rel: str) -> dict:
    """The person's settings on the page, ``{}`` when they have none."""
    from .models import PageState

    row = PageState.objects.filter(org_id=org_id, user_id=user_id, rel=rel).first()
    return {"settings": row.settings if row else {}, "updated_at": row.updated_at if row else None}


def write(org_id: str, user_id: str, rel: str, body: dict) -> dict:
    """One key set (``{"key", "value"}``) or the whole of it replaced (``{"settings"}``)."""
    from django.db import transaction

    from .models import PageState

    if "settings" in body:
        settings = body["settings"]
        if not isinstance(settings, dict):
            raise Refused("settings must be an object.")
        key = None
    else:
        key = body.get("key")
        if not isinstance(key, str) or not key or len(key) > KEY_MOST:
            raise Refused("Say which setting: a key of 1 to %d characters." % KEY_MOST)
        if "value" not in body:
            raise Refused("Say its value, or null to remove it.")
    now = time.time()
    with transaction.atomic():
        row = (PageState.objects.select_for_update()
               .filter(org_id=org_id, user_id=user_id, rel=rel).first())
        if key is not None:
            settings = dict(row.settings) if row else {}
            if body["value"] is None:
                settings.pop(key, None)
            else:
                settings[key] = body["value"]
        if _size(settings) > MOST:
            raise Refused("A page's settings may take %d KB at most." % (MOST // 1024), 413)
        if row is None:
            PageState.objects.create(org_id=org_id, user_id=user_id, rel=rel,
                                     settings=settings, updated_at=now)
        else:
            row.settings, row.updated_at = settings, now
            row.save(update_fields=["settings", "updated_at"])
    return {"settings": settings, "updated_at": now}


#: The one file a page may have its settings written to, beside it.
CHOICES = "choices.json"
#: The key that says the choices are made.
DONE = "done"
_ASKS = re.compile(r"""<meta\s[^>]*name\s*=\s*["']rouh-saves-choices["'][^>]*>""", re.I)
#: How much of the page is looked at for that line: it is in the head.
HEAD = 16 * 1024


class Hooks:
    """What the runtime lends: starting a run (`starting.start`). None until it is set."""

    start = None


hooks = Hooks()


def saves_beside(page: Path) -> bool:
    """Whether the page asks for its settings to be written beside it."""
    try:
        with open(page, "rb") as fh:
            head = fh.read(HEAD).decode("utf-8", "replace")
    except OSError:
        return False
    found = _ASKS.search(head)
    return bool(found) and CHOICES in found.group(0)


def beside(page: Path, settings: dict, updated_at: float, who) -> str:
    """Write the settings as `CHOICES` beside the page; its path, or "" when not asked for."""
    from .tenancy import GUEST_ORG

    if not getattr(who, "org_id", "") or who.org_id == GUEST_ORG or not saves_beside(page):
        return ""
    target = page.parent / CHOICES
    if target.is_symlink():
        log.warning("pagestate: %s is a link, not written", target)
        return ""
    data = dict(settings)
    data["saved_at"] = datetime.fromtimestamp(updated_at, timezone.utc).isoformat(timespec="seconds")
    data["saved_by"] = getattr(who, "name", "") or getattr(who, "email", "") or str(who.user_id)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    spare = target.with_name(f".{CHOICES}.{os.getpid()}.rouh-edit")
    was = page.stat()
    with open(spare, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(spare, 0o644)
    try:
        os.chown(spare, was.st_uid, was.st_gid)
    except OSError:
        pass
    os.replace(spare, target)
    from . import saving

    saving.poke()
    return str(target)


async def picked(who, root, doc: str) -> dict:
    """Done picking: the step in progress, and a job to replan from its choices."""
    from asgiref.sync import sync_to_async

    from . import conversations, steps, taskrecord

    folder = os.path.dirname(doc.strip("/"))
    task = steps.task_part(folder)
    number = task.rsplit("/", 1)[-1].split(".", 1)[0]
    try:
        await sync_to_async(taskrecord.change)(folder, status="in-progress", by="rouh", folder=folder)
    except Exception as exc:  # noqa: BLE001 - a step Rouh has no row for is said, not fatal
        log.warning("pagestate: %s could not be marked in progress: %s", folder, exc)
    if hooks.start is None:
        return {"ok": False, "error": "Jobs cannot be started from here."}
    brief = (
        f"The owner pressed Done picking on the page {doc}. Their choices are saved beside it "
        f"in {folder}/{CHOICES}: for each item, what it is on an installed Rouh, on a developer's "
        f"Rouh and on the Creator Rouh (off, on, or on and kept for a number of days), whether "
        f"each is still Rouh's suggestion or their own, their notes, and the history of their "
        f"changes. Replan task {number} from that file: read it and the task's AGENTS.md and "
        f"earlier steps, then make the task's next step with the plan of action that follows "
        f"from those choices (what changes in Rouh's code, in which waves, and what each saves), "
        f"with its page. Mark the step {os.path.basename(folder)} done, take the task's question "
        f"off, and update its AGENTS.md, status and summary. Do not change Rouh's code in that job.")
    chat = await sync_to_async(conversations.answer_for_task)(task)
    try:
        started = await hooks.start(brief=brief, title=f"Replan task {number} from the choices"[:120],
                                    preset="assistant_job", chat=chat or "",
                                    owner=(str(who.user_id), str(who.org_id)), org_id=str(who.org_id))
    except Exception as exc:  # noqa: BLE001 - CannotStart says why in words
        log.warning("pagestate: the replanning job could not be started: %s", exc)
        return {"ok": False, "error": str(exc) or "The job could not be started."}
    return {"ok": True, "run": str((started or {}).get("id") or (started or {}).get("run") or "")}


__all__ = ["CHOICES", "DONE", "MOST", "Refused", "beside", "hooks", "picked", "read",
           "saves_beside", "write"]
