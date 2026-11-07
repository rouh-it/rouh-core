"""The answers Rouh is giving right now, so that no deploy cuts one.

Petar, 3 November 2026: "lets wait if a chat answer is in progress. make sure it doesn't cut a chat
answer. so restart only if a chat answer is not in progress." Deploys are not grouped; each one
waits for the answers in progress when it comes, and goes the moment there are none.

The other side is the protected core's waiter (guard/rouh_guard/deploywait.py), which every
restart a deploy makes asks first: ``rouh-guard-run`` in the containers, ``update-all.sh`` on a
server. The two talk through files in ``DIR`` (the data folder's ``deploy-wait/``); its docstring
has the shape of each.

- **The count.** Every turn of Rouh's (`runtime.Turn`: General, task chats, forks, mail cases,
  Telegram and Slack answers, scheduled turns, all of which start through `runtime.Turns.start`)
  is one entry from the moment it starts until both its answer and its speaking are over, taken
  off by the tasks' own done callbacks, which run however a task ends. Each entry beats whenever
  the turn sends anything, and one that has not beaten for ``EXPIRE`` seconds, or whose tasks
  are gone, is not counted: a turn that crashed in a way nothing noticed cannot hold a deploy.
- **A deploy asks** (``ask.json``). With nothing in progress Rouh says so at once (``ready_for``).
  With answers in progress, new turns still start for ``GRACE`` seconds, so a busy chat is not
  made to wait for nothing; after that new turns are held back, the last answers finish, and Rouh
  says it is ready. From then until it is stopped, nothing new starts.
- **Held, not refused.** A turn held back waits where it is. What the person typed or said on a
  screen is also written down (``held.json``), so if the restart comes first the Rouh that starts
  next answers it, in the same chat, as the same person. Turns of Rouh's own software (an email, a
  reminder, a job's report) are never replayed that way: they ride on context a fresh process does
  not have - which email's limits hold, whether anybody is there - and their sources hand them
  over again (Telegram is not even read while Rouh holds, so its messages wait at Telegram).
- **The cap** is the waiter's (ten minutes). An answer it then cuts is named in ``cut.json``, and
  the next start writes under it that an update cut it, after how long, instead of the plain
  "cut short" sentence (`memory.Memory.mark_interrupted`).
- If the restart never comes (``HOLD_MAX`` after ready, or the ask taken away), Rouh lets the held
  turns go and carries on.
"""
from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path

log = logging.getLogger("rouh.answers_now")

#: An answer that has sent nothing for this long is not waited for.
EXPIRE = float(os.environ.get("ROUH_ANSWER_EXPIRE", "300"))
#: How long new answers may still start once a deploy has asked.
GRACE = float(os.environ.get("ROUH_DEPLOY_GRACE", "20"))
#: How long Rouh holds new turns after saying it is ready, if the restart never comes.
HOLD_MAX = float(os.environ.get("ROUH_DEPLOY_HOLD_MAX", "300"))
#: The longest the deploy's waiter waits (guard/rouh_guard/deploywait.py, the same setting).
CAP = float(os.environ.get("ROUH_DEPLOY_WAIT_CAP", "600"))
#: How often the state is written.
EVERY = 1.0

#: When this process started, wall clock: an ask older than this was for the restart that made it.
STARTED = time.time()

#: What this start found: the turns the restart before it cut short, and which of them a deploy
#: cut at its cap (`runtime.startup`). In the state, so whoever deployed can read it afterwards.
LAST_START: dict = {}

_lock = threading.Lock()
_answers: dict[str, dict] = {}
_dropped: set[str] = set()
_state = {"ask": "", "asked_at": 0.0, "holding": False, "hold_since": 0.0, "ready_for": "", "ready_at": 0.0,
          "stopping": False}


def folder() -> Path:
    from .config import config

    return Path(os.environ.get("ROUH_DEPLOY_WAIT_DIR") or os.path.join(config.data_dir, "deploy-wait"))


def mirror() -> Path | None:
    """Where the worker reads the same count (it shares the runs' folder with the core, and may
    not read the core's data folder). None off the containers."""
    given = os.environ.get("ROUH_DEPLOY_WAIT_MIRROR")
    if given:
        return Path(given)
    key = os.environ.get("ROUH_WORKER_KEY_FILE")
    if key and os.path.isdir(os.path.dirname(key)):
        return Path(os.path.dirname(key)) / "deploy-wait"
    return None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    with contextlib.suppress(OSError):
        os.chmod(tmp, 0o664)
    tmp.replace(path)


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# --- the count -------------------------------------------------------------------------------------

def begin(kind: str, where: str, tasks=()) -> str:
    """One answer in progress; ended by `end`, or by its tasks' done callbacks when given."""
    ident = uuid.uuid4().hex[:12]
    now = time.time()
    entry = {"id": ident, "kind": kind, "where": str(where or ""), "since": now, "beat": now,
             "tasks": [t for t in tasks if t is not None]}
    with _lock:
        _answers[ident] = entry
    for task in entry["tasks"]:
        task.add_done_callback(lambda _t, ident=ident: _task_done(ident))
    return ident


def _task_done(ident: str) -> None:
    with _lock:
        entry = _answers.get(ident)
        if entry is None:
            return
        if all(t.done() for t in entry["tasks"]):
            _answers.pop(ident, None)


def beat(ident: str) -> None:
    if not ident:
        return
    with _lock:
        entry = _answers.get(ident)
        if entry is not None:
            entry["beat"] = time.time()


def end(ident: str) -> None:
    with _lock:
        _answers.pop(ident, None)


@contextlib.contextmanager
def track(kind: str, where: str):
    """An answer in progress for the length of the block, whatever way it is left."""
    ident = begin(kind, where)
    try:
        yield ident
    finally:
        end(ident)


def in_progress(now: float | None = None) -> list[dict]:
    """The answers in progress that count: beating, and with their work still running."""
    with _lock:
        return _in_progress(time.time() if now is None else now)


def _in_progress(now: float) -> list[dict]:
    out = []
    for ident, e in list(_answers.items()):
        tasks = e["tasks"]
        if tasks and all(t.done() for t in tasks):
            _answers.pop(ident, None)
            continue
        if now - e["beat"] > EXPIRE:
            if ident not in _dropped:
                _dropped.add(ident)
                log.warning("an answer in %s (%s) has sent nothing for %d s; a deploy no longer waits for it",
                            e["where"], e["kind"], int(now - e["beat"]))
            continue
        out.append({k: e[k] for k in ("id", "kind", "where", "since", "beat")})
    return out


def enter(kind: str, where: str) -> str:
    """An answer about to start, counted at once - or "" when a deploy holds new ones back. The
    look and the count are one step, so a deploy is never told "ready" in between."""
    with _lock:
        if _state["holding"]:
            return ""
        ident = uuid.uuid4().hex[:12]
        now = time.time()
        _answers[ident] = {"id": ident, "kind": kind, "where": str(where or ""), "since": now, "beat": now,
                           "tasks": []}
        return ident


# --- holding new turns back ------------------------------------------------------------------------

def holding() -> bool:
    return bool(_state["holding"])


def _held_path() -> Path:
    return folder() / "held.json"


_held_lock = threading.Lock()


def _held_rows() -> list[dict]:
    rows = _read(_held_path())
    return rows if isinstance(rows, list) else []


def _keep(row: dict) -> str:
    row = {**row, "id": uuid.uuid4().hex[:12], "at": time.time()}
    with _held_lock:
        rows = _held_rows()
        rows.append(row)
        _write(_held_path(), rows)  # type: ignore[arg-type]
    return row["id"]


def _take(ident: str) -> bool:
    """Take a kept turn off the list; False when it was not there any more."""
    with _held_lock:
        rows = _held_rows()
        left = [r for r in rows if r.get("id") != ident]
        if len(left) == len(rows):
            return False
        if left:
            _write(_held_path(), left)  # type: ignore[arg-type]
        else:
            with contextlib.suppress(OSError):
                _held_path().unlink()
        return True


def person_turn(chat: str, content, *, note: bool, heard: str, who) -> dict | None:
    """What a turn the person asked for on a screen needs to be answered after a restart."""
    try:
        json.dumps(content)
    except (TypeError, ValueError):
        return None
    ident = dataclasses.asdict(who) if dataclasses.is_dataclass(who) else None
    return {"chat": chat, "content": content, "note": bool(note), "heard": heard or "", "who": ident}


async def admit(kind: str, where: str, *, keep: dict | None = None) -> bool:
    """Wait while a deploy holds new turns back. True: go on. False: the turn was already taken
    by somebody else (it is not to be started here)."""
    if not holding():
        return True
    kept = ""
    if keep is not None:
        try:
            kept = await asyncio.to_thread(_keep, keep)
        except Exception:  # noqa: BLE001 - still held, only not kept on disk
            log.exception("a held turn could not be written down")
    log.info("a %s turn in %s is held while Rouh is about to be updated", kind, where)
    since = time.monotonic()
    while holding():
        if _state["stopping"]:
            # Rouh is going: the turn goes no further here, so nothing holds the server's stop
            # open. What the person asked is on disk, for the next Rouh to answer.
            log.info("the held %s turn in %s is left to the next Rouh", kind, where)
            raise asyncio.CancelledError
        await asyncio.sleep(0.5)
    log.info("the held %s turn in %s goes on, after %.1f s", kind, where, time.monotonic() - since)
    if kept:
        return await asyncio.to_thread(_take, kept)
    return True


async def until_free() -> None:
    """For a source that can leave its messages where they are (Telegram): wait while holding."""
    while holding():
        await asyncio.sleep(1.0)


# --- the deploy's side -----------------------------------------------------------------------------

def _hold(now: float, why: str) -> None:
    if not _state["holding"]:
        _state["holding"], _state["hold_since"] = True, now
        log.info("new turns are held back: %s", why)


def stopping() -> None:
    """Rouh is going (its shutdown has begun): whatever is held stays held, for the next Rouh."""
    with _lock:
        _state["stopping"] = True
        if _state["ready_for"] or _state["ask"]:
            _hold(time.time(), "Rouh is stopping")


def catch_stop() -> None:
    """Know a stop the moment it is asked for, before the server waits for its connections: the
    server's own handler for SIGTERM and SIGINT is wrapped, and still called (uvicorn installs
    its handlers with signal.signal before Rouh starts). A turn waiting on a hold would otherwise
    keep its connection - and so the whole stop - open until the process is killed."""
    import signal

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            before = signal.getsignal(sig)
            if not callable(before) or getattr(before, "_answers_now", False):
                continue

            def on_stop(signum, frame, before=before):
                _state["stopping"] = True
                before(signum, frame)

            on_stop._answers_now = True  # type: ignore[attr-defined]
            signal.signal(sig, on_stop)
        except (ValueError, OSError):  # not the main thread, or not a signal this has
            pass


def _release(now: float, why: str) -> None:
    if _state["holding"]:
        log.info("new turns go on again after %.1f s: %s", now - _state["hold_since"], why)
    _state.update(holding=False, hold_since=0.0, ready_for="", ready_at=0.0, ask="", asked_at=0.0)


def step(now: float | None = None) -> dict:
    """One look at the ask and one state written. What `watch` does every second."""
    now = time.time() if now is None else now
    here = folder()
    ask = _read(here / "ask.json")
    if isinstance(ask, dict) and float(ask.get("at") or 0) < STARTED:
        # The ask of the deploy that started this very process; it is over.
        with contextlib.suppress(OSError):
            (here / "ask.json").unlink()
        ask = None
    ident = str(ask.get("id") or "") if isinstance(ask, dict) else ""
    spent = False
    with _lock:
        answers = _in_progress(now)
        if ident:
            if ident != _state["ask"]:
                _state.update(ask=ident, asked_at=now, ready_for="", ready_at=0.0)
                log.info("a deploy asks to restart Rouh (%s); answers in progress: %d",
                         ask.get("why") or ask.get("who") or "", len(answers))
            if _state["ready_for"] == ident:
                if now - _state["ready_at"] > HOLD_MAX and not _state["stopping"]:
                    log.warning("Rouh said it was ready to be restarted %d s ago and nothing restarted it",
                                int(now - _state["ready_at"]))
                    spent = True
                    _release(now, "the restart never came")
            elif not answers:
                _hold(now, "ready to be restarted")
                _state.update(ready_for=ident, ready_at=now)
                log.info("no answer in progress: ready to be restarted, %.1f s after the ask",
                         now - _state["asked_at"])
            elif now - _state["asked_at"] >= GRACE:
                _hold(now, f"{len(answers)} answer(s) still in progress after {int(GRACE)} s")
        elif _state["stopping"]:
            pass
        elif _state["ready_for"] and now - _state["ready_at"] > HOLD_MAX:
            _release(now, "the restart never came")
        elif not _state["ready_for"] and _state["ask"] and now - _state["asked_at"] > CAP + GRACE:
            _release(now, "the deploy that asked is gone")
        # Otherwise the ask was taken away by a Rouh started after it - this one is on its way
        # out - so nothing held here is let go: the next Rouh answers it.
    if spent:
        with contextlib.suppress(OSError):
            (here / "ask.json").unlink()
    state = {"pid": os.getpid(), "started": STARTED, "at": now, "answers": answers,
             "holding": _state["holding"], "ready_for": _state["ready_for"], "ask": _state["ask"],
             "held": len(_held_rows()) if _state["holding"] else 0, "this_start": LAST_START}
    for where in (here, mirror()):
        if where is None:
            continue
        try:
            _write(where / "state.json", state)
        except OSError:
            if where is here:
                log.warning("could not write %s", where / "state.json", exc_info=True)
    return state


async def watch() -> None:
    """Every second, for as long as Rouh runs."""
    while True:
        try:
            await asyncio.to_thread(step)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - never in the way of Rouh
            log.exception("the count of answers in progress could not be written")
        await asyncio.sleep(EVERY)


# --- after a restart -------------------------------------------------------------------------------

def cut_by_deploy() -> dict[str, dict]:
    """The chats whose answer the last deploy cut at its cap, read once and taken away."""
    path = folder() / "cut.json"
    got = _read(path)
    with contextlib.suppress(OSError):
        path.unlink()
    if not isinstance(got, dict):
        return {}
    out = {}
    for a in got.get("answers") or []:
        if a.get("where"):
            out[str(a["where"])] = {**a, "waited": got.get("waited")}
    if out:
        log.warning("the last deploy cut %d answer(s) after waiting %s s: %s", len(out), got.get("waited"),
                    ", ".join(f"{a.get('kind')} in {w}" for w, a in out.items()))
    return out


def take_held() -> list[dict]:
    """The turns held over the restart, taken off the list to be answered now."""
    with _held_lock:
        rows = _held_rows()
        with contextlib.suppress(OSError):
            _held_path().unlink()
    return rows
