"""The card for Rouh restarting onto its own new code, and how it ends.

``deploy_myself`` starts ``update-all.sh`` detached and then says "restarting
now". That script brings the one program up and then Rouh, so the process
that said it is the process about to be killed, which is the whole reason the
deploy is detached - but it also meant the card it put on the task list
belonged to nobody the moment the restart began.

That is the bug this file exists for. Until 19 September 2026 the card was an
event and nothing else: ``{"type": "task", "id": "self-update", ...}`` sent to
whichever tabs were open, with no row behind it anywhere. So

* the whole list (``server.task_list``) is read from the database and never
  carried it, so no snapshot could ever correct it;
* the job that owned it died in the restart without sending a finish;
* the page kept it, because a tab merges what it is told and drops nothing;
* and its button asked Rouh to archive a job Rouh had never heard of,
  which came back as an error and left the card exactly where it was.

Petar's screen had "Updating Rouh - WORKING - pulling and restarting" on it
for hours, and only a reload would clear it.

So the deploy has a record of its own, one small JSON file beside the database,
and that record is on the task list like anything else. It outlives the process
that started it on purpose: the next Rouh to start reads it, sees that the
process which owned it is gone, and finishes it. That is what ``reconcile``
does, and it is called once at startup before any tab can connect.

How it finishes:

* **done** - the commit answering now is not the commit the deploy started
  from, so the new build is up. "deployed 0cbfe0a".
* **done** - the commit is the same. Something restarted Rouh without moving
  it, which is what ``--no-pull`` does and what a deploy with nothing new to
  fetch does. "restarted on 0cbfe0a".
* **failed** - the deploy left an outcome behind saying it never got that far,
  or that it rolled back, or that one of the two services did not move. One
  line in ``self-update-outcome``, written before Rouh is restarted onto the
  old code again, and the sentence in it is what the card says. Both
  ``deploy/rouh.sh`` and ``update-all.sh`` write it: the second because a deploy
  where the one program failed and Rouh succeeded would otherwise come back
  up looking like a deploy that worked.

And if the update never restarts Rouh at all - a fetch that GitHub refuses,
a requirement that will not install - then nothing restarts and nothing
reconciles, so the process that started it watches instead: it reads the
outcome file every couple of seconds, and gives up after ``PATIENCE`` with a
card that says so. A card that lies for three minutes is a bug; a card that
lies for ever is the one that was reported.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from datetime import datetime, timezone

from . import fileutil
from .config import config
from .version import full_revision

log = logging.getLogger("rouh.self_update")

#: The id the card has carried since the first version of this, kept so a tab
#: left open across the deploy that ships this file recognises its own card.
ID = "self-update"
TITLE = "Updating Rouh"
#: What the card says while it is happening.
WORKING = "pulling and restarting"
#: On the card's meta line, where a background job says "self" and a run of the
#: one program says "one".
MODE = "deploy"

#: The statuses that mean it has not finished. The same words the rest of the
#: task list uses, so the column colours and labels it without knowing this
#: file exists.
OPEN = ("starting", "running")

#: How long an update gets to restart Rouh before the card stops believing
#: it will. Three minutes: each half allows twenty seconds for its own health
#: check, and a pip install of changed requirements before that.
PATIENCE = 180.0

#: How often the process that started the update looks for an outcome from it.
BEAT = 2.0

#: Called with no arguments whenever the record changes under its own steam -
#: the watchdog below giving up, or an outcome arriving. `server.startup` sets
#: it to the thing that pushes the task list to every tab. Awaited if it
#: returns something awaitable.
on_change = None

_watchdog: asyncio.Task | None = None


def _now() -> str:
    """A time written the way crew.py writes one, so one sort covers both."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path() -> str:
    """The record, beside the database rather than in it.

    A file because this has to be readable and writable by a process that is
    starting up and by one that is being killed, with no schema to migrate and
    nothing to lock. There is only ever one deploy, so there is only ever one
    record, and the next deploy replaces it.
    """
    return os.path.join(config.data_dir, "self-update.json")


def outcome_path() -> str:
    """Where the deploy says what became of it. See the module docstring."""
    return os.path.join(config.data_dir, "self-update-outcome")


def read() -> dict | None:
    """The record, or None when there has never been a deploy on this machine."""
    try:
        with open(path(), encoding="utf-8") as fh:
            got = json.load(fh)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) and got.get("id") == ID else None


def _write(rec: dict) -> dict:
    """The record, written whole and swapped into place.

    Through a temporary file and a rename because the process doing this is
    often seconds away from being killed, and half a record would read as no
    record at all.
    """
    with contextlib.suppress(OSError):
        os.makedirs(config.data_dir, exist_ok=True)
    tmp = path() + ".tmp"
    try:
        fileutil.write_json_atomic(path(), rec, spare=tmp, tidy=False)
    except OSError:
        log.exception("could not write the deploy record")
        with contextlib.suppress(OSError):
            os.remove(tmp)
    return rec


def forget() -> bool:
    """Drop the record for good. The card's own button, and nothing else.

    A deploy has no terminal to close and no checkout to leave alone, so there
    is nothing to archive: dismissing the card is the whole of what the person
    means, and the record goes with it.
    """
    try:
        os.remove(path())
    except OSError:
        return False
    with contextlib.suppress(OSError):
        os.remove(outcome_path())
    return True


def commit() -> str:
    """The short commit the checkout Rouh is deployed from is at, or "".

    Read off git's files every time rather than from `version.REVISION`, which
    is worked out once at import: this is asked either side of a restart and
    the point is to see it move.
    """
    return full_revision(config.app_dir)[:7]


def row() -> dict | None:
    """The deploy's line on the task list, in the same shape as every other.

    None when there has never been a deploy, which is every machine that has
    not deployed itself yet and every test that is not about this.
    """
    rec = read()
    if rec is None:
        return None
    return {
        "id": ID,
        "title": rec.get("title") or TITLE,
        "status": rec.get("status") or "running",
        "detail": rec.get("detail") or "",
        "mode": MODE,
        "created_at": rec.get("created_at"),
        "updated_at": rec.get("updated_at"),
        "finished_at": rec.get("finished_at"),
        "exit_code": rec.get("exit_code"),
        "repo": rec.get("repo"),
        "branch": None,
        "archived": False,
        # The button on this row is a dismissal, not an archiving: there is no
        # terminal behind it to close and no folder to leave alone, so the page
        # draws a bin and the click drops the record.
        "dismiss": True,
    }


def begin(to: str | None = None) -> dict:
    """Write the record for a deploy that is starting, and watch it.

    Returns the row to put on the task list, so the caller sends exactly what
    every tab will be sent again by the next snapshot.
    """
    token = time.time()
    now = _now()
    _write({
        "id": ID,
        "title": TITLE,
        "status": "running",
        "detail": WORKING,
        "created_at": now,
        "updated_at": now,
        "finished_at": None,
        "exit_code": None,
        "repo": config.app_dir,
        # Whose deploy this is. A record whose pid is not this process is one
        # left behind by a process that no longer exists, which is the whole
        # signal `reconcile` goes on.
        "pid": os.getpid(),
        "started": token,
        "from_commit": commit(),
        "to": to or "",
    })
    # The outcome of the deploy before this one must never be read as this
    # one's. It is written by the deploy after this point or not at all.
    with contextlib.suppress(OSError):
        os.remove(outcome_path())
    _watch(token)
    return row() or {}


def _finish(status: str, detail: str, token: float | None = None) -> dict | None:
    """Close the record, unless it is already closed or belongs to a newer deploy."""
    rec = read()
    if rec is None or rec.get("status") not in OPEN:
        return None
    if token is not None and rec.get("started") != token:
        return None
    now = _now()
    rec.update(status=status, detail=detail[:300], updated_at=now, finished_at=now,
               exit_code=0 if status == "done" else 1)
    _write(rec)
    log.info("the deploy card is %s: %s", status, detail)
    return row()


def _outcome(after: float) -> tuple[str, str] | None:
    """What ``deploy/rouh.sh`` left behind, if it left anything after `after`.

    One line: a word that is "done" or "failed", then the sentence the card
    should say. Anything else in the file is ignored rather than shown, because
    this ends up on the person's screen.
    """
    where = outcome_path()
    try:
        if os.path.getmtime(where) + 1.0 < after:
            return None                     # left over from an earlier deploy
        with open(where, encoding="utf-8") as fh:
            said = fh.readline().strip()
    except OSError:
        return None
    word, _, sentence = said.partition(" ")
    if word not in ("done", "failed") or not sentence.strip():
        return None
    return word, sentence.strip()


def reconcile() -> dict | None:
    """Finish a deploy whose process is gone. Called once, at startup.

    This process starting is the deploy's answer: either it is the new build,
    or it is the old one that `deploy/rouh.sh` put back. Either way the process that
    owned the card is not here, so nothing else will ever close it.

    Returns the finished row when it changed something, and None when there was
    nothing to finish, which is the ordinary case.
    """
    rec = read()
    if rec is None or rec.get("status") not in OPEN:
        return None
    if rec.get("pid") == os.getpid():
        return None                         # our own, still running
    said = _outcome(float(rec.get("started") or 0.0))
    if said is not None:
        with contextlib.suppress(OSError):
            os.remove(outcome_path())
        return _finish("failed" if said[0] == "failed" else "done", said[1])
    was, now = rec.get("from_commit") or "", commit()
    if now and now != was:
        return _finish("done", f"deployed {now}")
    return _finish("done", f"restarted on {now}" if now else "restarted")


async def push() -> None:
    """Tell every tab the list has changed, not only the one that asked.

    A tool's own `emit` reaches the tab the person spoke into. The phone in
    their other hand is looking at the same machine and should see the card
    go up at the same moment.
    """
    await _changed()


async def _changed() -> None:
    if on_change is None:
        return
    with contextlib.suppress(Exception):
        got = on_change()
        if asyncio.iscoroutine(got):
            await got


def _watch(token: float) -> None:
    """Watch this deploy from the process that started it, until it is killed.

    The restart is what normally ends this task, by ending the process. What it
    is here for is the update that never gets as far as a restart.
    """
    global _watchdog
    if _watchdog is not None and not _watchdog.done():
        _watchdog.cancel()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:                    # no loop: nothing to watch with
        _watchdog = None
        return
    _watchdog = loop.create_task(_watching(token))


async def _watching(token: float) -> None:
    until = time.monotonic() + PATIENCE
    while time.monotonic() < until:
        await asyncio.sleep(BEAT)
        rec = read()
        if rec is None or rec.get("started") != token or rec.get("status") not in OPEN:
            return
        said = _outcome(token)
        if said is not None:
            with contextlib.suppress(OSError):
                os.remove(outcome_path())
            if _finish("failed" if said[0] == "failed" else "done", said[1], token):
                await _changed()
            return
    if _finish("failed", "the update did not restart Rouh; see update.log", token):
        await _changed()
