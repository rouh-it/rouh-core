"""Nothing a test starts is left running once the test is over.

The program starts every run's terminal in a process of its own and lets go of
it: ``Terminals.start`` passes ``start_new_session=True``, so a holder is the
leader of a session of its own. That is the point of a holder. A deploy
restarts the program, the holders carry on, and the new program connects to
each one again.

In a test it is a leak. A fixture stops the program it started; the holders are
in sessions of their own, so nothing stops them; the kernel hands them to PID 1
and they stay. The agent inside is worse: the stand-in for Claude Code does its
scripted lines and then sits at its prompt reading the terminal, exactly as the
real one does, so it never ends by itself either. Then pytest deletes the
temporary folder underneath both of them, and with it the last sign of which
test session they belonged to.

On 18 September 2026 that had left 155 processes on this server, the oldest 6
hours 28 minutes old, from pytest sessions whose folders pytest had already
rotated away. This file is what a fixture calls to put it right.

Two rules run through it.

**A process is named by a path it really holds, never by prose.** A run's brief
is one of the run's own arguments, and a brief about stray processes quotes the
very paths this file looks for - the run that wrote this file had
``/tmp/pytest-of-rouh`` inside its own command line, and a pattern match would
have killed it. So an argument counts only when it *is* a path under the folder,
and from those the rest of the tree is followed by parentage, which nothing
anybody types can fake.

**Politely, then not.** SIGTERM first: a holder passes it to its agent and
writes its ``exit.json``, so the run ends the way it would if a person had ended
it. Whatever is still there ``GRACE`` seconds later gets SIGKILL.
"""
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

#: Seconds between the polite signal and the one that cannot be refused. Long
#: enough for a holder to pass SIGTERM on, write exit.json and go; short enough
#: that a suite does not wait on it.
GRACE = 5.0

#: Every folder a fixture has said it owns, in the order they were claimed.
#: The session's backstop sweeps all of them at the end, so a fixture that
#: forgot to reap, or a test that died before its teardown ran, still leaves
#: nothing behind.
_WATCHED: list[str] = []


def watch(folder: str | os.PathLike[str]) -> Path:
    """Claim a folder: whatever is found running under it later is a stray."""
    path = Path(folder).resolve()
    if str(path) not in _WATCHED:
        _WATCHED.append(str(path))
    return path


def watched() -> list[str]:
    return list(_WATCHED)


# ---------------------------------------------------------------------------
# Reading the process table
# ---------------------------------------------------------------------------


def _argv(pid: str) -> list[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return [a for a in fh.read().decode("utf-8", "replace").split("\0") if a]
    except OSError:
        return []


def _link(pid: str, name: str) -> str:
    try:
        return os.readlink(f"/proc/{pid}/{name}")
    except OSError:
        return ""


def _parent(pid: str) -> str:
    try:
        with open(f"/proc/{pid}/status") as fh:
            for line in fh:
                if line.startswith("PPid:"):
                    return line.split()[1]
    except OSError:
        pass
    return "0"


def _under(text: str, roots: tuple[str, ...]) -> bool:
    return any(text == root or text.startswith(root + os.sep) for root in roots)


def _paths_in(argv: list[str]) -> list[str]:
    """The arguments that are themselves paths, and nothing else.

    ``--dir /tmp/x`` gives "/tmp/x" and ``ONE_DATA=/tmp/x`` gives "/tmp/x". A
    paragraph that mentions /tmp/x gives nothing: it does not begin with a
    slash, and a path has no spaces in it.
    """
    found = []
    for arg in argv:
        for token in (arg, arg.split("=", 1)[1] if "=" in arg else ""):
            if token.startswith("/") and not any(c.isspace() for c in token):
                found.append(token)
    return found


def _ours(pid: str) -> set[str]:
    """This process and everything it descends from, which is never a stray."""
    mine, at = {pid}, pid
    while at not in ("0", "1", ""):
        at = _parent(at)
        mine.add(at)
    return mine


# ---------------------------------------------------------------------------
# Finding what is still running
# ---------------------------------------------------------------------------


def running_under(*roots: str | os.PathLike[str]) -> list[tuple[int, str]]:
    """Every process still running that belongs to one of these folders.

    A process belongs to a folder when it works in it, runs a program from it,
    or was given a path under it as one of its arguments - and then so does
    everything descended from it, however it was started. The agent inside a
    holder is found that way: the holder is named by its ``--dir``, and the
    agent is the holder's child.
    """
    wanted = tuple(str(Path(r).resolve()) for r in roots)
    if not wanted:
        return []
    pids = [p for p in os.listdir("/proc") if p.isdigit()]
    mine = _ours(str(os.getpid()))
    argvs = {p: _argv(p) for p in pids}
    seeds = set()
    for pid in pids:
        if pid in mine or not argvs[pid]:
            continue
        if (_under(_link(pid, "cwd"), wanted) or _under(_link(pid, "exe"), wanted)
                or any(_under(t, wanted) for t in _paths_in(argvs[pid]))):
            seeds.add(pid)
    children: dict[str, list[str]] = {}
    for pid in pids:
        children.setdefault(_parent(pid), []).append(pid)
    queue = list(seeds)
    while queue:
        for child in children.get(queue.pop(), ()):
            if child not in seeds and child not in mine:
                seeds.add(child)
                queue.append(child)
    return sorted(((int(p), " ".join(argvs.get(p) or _argv(p))) for p in seeds),
                  key=lambda row: row[0])


def _from_holder_files(roots: tuple[str, ...]) -> set[int]:
    """The pids the holders wrote down, while their folders are still there.

    Every holder writes ``holder.json`` with its own pid and its agent's the
    moment it starts, so this is the exact answer whenever the folder survives
    long enough to be read. It costs one glob and needs no guessing.
    """
    found: set[int] = set()
    for root in roots:
        for path in Path(root).glob("**/holder.json"):
            try:
                said = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            for key in ("pid", "child"):
                try:
                    found.add(int(said[key]))
                except (KeyError, TypeError, ValueError):
                    pass
    return {pid for pid in found if pid > 1 and Path(f"/proc/{pid}").exists()}


# ---------------------------------------------------------------------------
# Stopping it
# ---------------------------------------------------------------------------


def _signal(pid: int, sig: int) -> None:
    """Signal a process, and its whole group when it leads one.

    A holder is a session leader, so its group is itself; a command that made
    children of its own - a shell, a test's own subprocess - has them in its
    group, and they go together.
    """
    try:
        if os.getpgid(pid) == pid:
            os.killpg(pid, sig)
            return
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def reap(*roots: str | os.PathLike[str], grace: float = GRACE) -> list[tuple[int, str]]:
    """Stop everything still running under these folders. Returns what it stopped.

    Nothing to stop is the ordinary case and costs one pass over /proc.
    """
    wanted = tuple(str(Path(r).resolve()) for r in roots)
    if not wanted:
        return []
    known = dict(running_under(*wanted))
    mine = _ours(str(os.getpid()))
    for pid in _from_holder_files(wanted):
        if str(pid) not in mine:
            known.setdefault(pid, " ".join(_argv(str(pid))))
    if not known:
        return []
    for pid in known:
        _signal(pid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid in known):
            break
        time.sleep(0.05)
    for pid in known:
        if Path(f"/proc/{pid}").exists():
            _signal(pid, signal.SIGKILL)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid in known):
            break
        time.sleep(0.05)
    return sorted(known.items())


def report(stopped: list[tuple[int, str]], where: str) -> str:
    """One line per process, for a fixture that had to step in."""
    lines = [f"{len(stopped)} process(es) were still running under {where} "
             f"and had to be stopped:"]
    lines += [f"  {pid}  {cmd[:120]}" for pid, cmd in stopped]
    return "\n".join(lines)
