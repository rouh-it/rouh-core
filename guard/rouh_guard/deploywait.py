"""A deploy waits while Rouh is answering: no restart cuts a chat answer.

Part of the protected core (guard/README.md). Petar, 3 November 2026: "make sure it doesn't cut a
chat answer. so restart only if a chat answer is not in progress." Every restart a deploy makes
asks this first: ``rouh-guard-run`` when the protected core moves a restart number (a change, an
undo, the doctor; every landing in the containers comes through it), and ``update-all.sh`` before
it restarts Rouh on a server. Deploys are not grouped: each one waits only for the answers that
are in progress when it comes.

The two sides talk through two small files in one folder, ``DIR`` (Rouh's data folder,
``deploy-wait/``), so neither imports the other and either can be replaced:

- ``ask.json``, written here: ``{"id", "at", "who", "why"}``. A deploy wants to restart.
- ``state.json``, written by Rouh about every second (``rouh/answers_now.py``): ``{"pid", "at",
  "answers": [{"id", "kind", "where", "since", "beat"}], "holding", "ready_for"}``. ``answers``
  are the answers in progress, each released in a ``finally`` and dropped once it stops beating
  (``ROUH_ANSWER_EXPIRE``), so a crashed turn cannot hold a deploy. Once a deploy has asked, new
  answers may still start for a short grace period; after it Rouh holds new turns back (kept, not
  refused: a typed message is kept on disk and answered after the restart), the last answers
  finish, and ``ready_for`` names the ask.

This waits until ``ready_for`` is its own ask, or at once when there is no fresh ``state.json``
(Rouh is not running, is not answering at all, or is a Rouh from before this, which keeps no
count), or until ``CAP`` seconds: then it goes anyway, writes ``cut.json`` naming each answer it
cut, and the Rouh that starts next puts an honest sentence under each of them instead of a silently
cut message. Every wait is one line of ``waits.log``: who, how long, for which answers, and how it
ended. Standard library only.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Callable

#: The longest a deploy waits for answers in progress, in seconds.
CAP = float(os.environ.get("ROUH_DEPLOY_WAIT_CAP", "600"))
#: A state.json older than this is a Rouh that is not answering, and nothing is waited for.
STALE = float(os.environ.get("ROUH_DEPLOY_WAIT_STALE", "15"))
#: How often it looks.
EVERY = float(os.environ.get("ROUH_DEPLOY_WAIT_EVERY", "1"))


def _read(path: Path) -> dict | None:
    try:
        got = json.loads(path.read_text())
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def _write(path: Path, data: dict) -> None:
    # Never makes the folder: it is Rouh's, made by Rouh as its own user, and one made here (as
    # root, on a server) would be a folder Rouh could not write its count into.
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    try:
        os.chmod(tmp, 0o664)
    except OSError:
        pass
    tmp.replace(path)


def _append(path: Path, line: dict) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def _say(text: str) -> None:
    print(f"rouh-deploy-wait: {text}", flush=True)


def wait(folder: str | os.PathLike, who: str, *, why: str = "", ask: bool = True, cap: float | None = None,
         stopped: Callable[[], bool] | None = None, every: float | None = None,
         stale: float | None = None) -> dict:
    """Wait until no chat answer is in progress, and say how it went.

    ``ask`` False only watches (the worker, which may not ask the core to hold anything): it goes
    when the answers in progress are none. ``stopped`` ends the wait early (a stop from Docker).
    Answers ``{"outcome", "waited", "answers", "cut"}``; outcome is ``idle`` (nothing in progress
    when it came), ``ready`` (it waited for answers that finished), ``no-app``, ``cap``, ``stopped``.
    """
    folder = Path(folder)
    cap = CAP if cap is None else cap
    every = EVERY if every is None else every
    stale = STALE if stale is None else stale
    began = time.time()
    me = {"id": uuid.uuid4().hex[:12], "at": began, "who": who, "why": why[:200]}
    st = _read(folder / "state.json") if folder.is_dir() else None
    if st is None or began - float(st.get("at") or 0) > stale:
        # Nothing keeps the count: Rouh is not running, not answering, or from before this.
        _say(f"{who}: Rouh keeps no count of its answers now (not running, or not answering); going on")
        line = {"at": round(began, 3), "who": who, "why": why[:200], "outcome": "no-app", "waited": 0.0,
                "answers": [], "cut": []}
        if folder.is_dir():
            _append(folder / "waits.log", line)
        return {"outcome": "no-app", "waited": 0.0, "answers": [], "cut": []}
    if ask:
        try:
            _write(folder / "ask.json", me)
        except OSError as exc:
            _say(f"could not ask Rouh to finish its answers ({exc}); going on")
            ask = False
    seen: dict[str, dict] = {}
    outcome, last = "", None
    first = True
    while True:
        now = time.time()
        st = _read(folder / "state.json")
        fresh = st is not None and now - float(st.get("at") or 0) <= stale
        answers = list(st.get("answers") or []) if fresh else []
        for a in answers:
            seen.setdefault(str(a.get("id")), {k: a.get(k) for k in ("id", "kind", "where", "since")})
        if not fresh:
            outcome = "no-app"
            break
        if ask:
            mine = _read(folder / "ask.json")
            if not mine or mine.get("id") != me["id"]:
                # Taken away by a Rouh that started after an older ask, or by another deploy: put back.
                try:
                    _write(folder / "ask.json", me)
                except OSError:
                    outcome = "no-app"
                    break
            if st.get("ready_for") == me["id"]:
                outcome = "ready" if seen else "idle"
                break
        elif not answers:
            outcome = "ready" if seen else "idle"
            break
        if now - began >= cap:
            outcome = "cap"
            last = answers
            break
        if stopped is not None and stopped():
            outcome = "stopped"
            last = answers
            break
        if first and answers:
            _say(f"{who}: waiting for {len(answers)} answer(s) in progress: "
                 + ", ".join(f"{a.get('kind')} in {a.get('where')}" for a in answers[:5]))
        first = False
        time.sleep(every)
    waited = round(time.time() - began, 1)
    cut = [{k: a.get(k) for k in ("id", "kind", "where", "since")} for a in (last or [])]
    if outcome == "cap" and cut and ask:
        # The Rouh that starts next says, under each, that it was cut by an update, and why.
        try:
            _write(folder / "cut.json", {"at": time.time(), "who": who, "waited": waited, "answers": cut})
        except OSError:
            pass
    line = {"at": round(began, 3), "who": who, "why": why[:200], "outcome": outcome, "waited": waited,
            "answers": list(seen.values()), "cut": cut}
    _append(folder / "waits.log", line)
    if outcome == "cap":
        _say(f"{who}: waited the most there is ({int(cap)} s) and goes anyway; cut: "
             + (", ".join(f"{a.get('kind')} in {a.get('where')}" for a in cut) or "nothing"))
    elif outcome == "ready":
        _say(f"{who}: waited {waited} s for {len(seen)} answer(s) to finish")
    elif outcome == "no-app":
        _say(f"{who}: Rouh keeps no count of its answers now (not running, or not answering); going on")
    return {"outcome": outcome, "waited": waited, "answers": list(seen.values()), "cut": cut}
