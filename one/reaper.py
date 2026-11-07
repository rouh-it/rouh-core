"""Nothing a run starts outlives the run, and nothing grows without a ceiling.

A run of Claude Code starts things: a copy of Rouh on a free port, a stand-in
for a model, a browser over Playwright MCP with eight Chromium processes behind
it, a tmux server, a folder in ``/tmp`` with a world in it. Every one of those
is started to prove a change and is finished with the moment the change is
proved. None of them ends by itself.

``holder.py`` already puts a run's command in a cgroup of its own and empties
that box when the run ends, which is the one shutdown a process cannot escape
by cutting itself loose from its parent. This file is the other half: what
happens when the box was never made, or was made and never emptied, or when
what leaked was never a process at all.

**What this was measured against.** On 22 September 2026 this machine was
holding 14.82 GB of the 20 GB the one program's service may use, and had been
pushed against that ceiling 4,972 times. Two things were nearly all of it, and
neither had an owner:

- **2.25 GB in 28 orphaned processes.** Run ``aa36c208`` finished on the
  evening of 19 September and left thirteen pairs behind it - a Rouh and a
  stand-in model for each world it stood up to prove its work - still running
  2.7 days later, on thirteen ports, with their checkout long deleted. Its
  holder started before the box landed that same evening, so nothing it started
  was ever in one, and nothing anywhere swept.
- **7.9 GB in ``/tmp``.** On this machine ``/tmp`` is a tmpfs: a filesystem
  that lives in memory and nowhere else. A folder left there is memory left
  held, and it is not given back by closing a run. ``scheduler.py`` says so at
  the top of itself and stops there, because closing runs is all it can do.

So, three sweeps and a picture.

**The boxes.** A ``run-<id>`` cgroup whose run the program no longer has open
is emptied and taken away. This is the case ``holder.py`` cannot cover by
itself: a holder killed outright never reaches its own shutdown, and the box it
made then sits there full.

**The strays.** A process in the service's own cgroup, not in any box, whose
parent is init, older than ``ONE_STRAY_AFTER``. Orphaned and unboxed is the whole
definition of having no owner, and it is what the 28 were. The test is
deliberately narrow: parentage is the one thing a leak cannot fake, because a
process is handed to init only when whoever started it is already gone. From
each of those, the whole tree below it goes too, which is how eight Chromium
processes under a leaked Playwright MCP are reached.

**The scratch.** Folders under the tmpfs, made by the harness and by the tools
a run proves its work with, older than ``ONE_SCRATCH_AFTER`` and held open by
nobody. Named by prefix rather than by age alone, because ``/tmp`` is shared
with tmux, PostgreSQL and systemd, and none of those are ours to delete.

**The ceiling.** Sweeping is the backstop, not the design. The design is that a
run's temp files are in the run's own folder on disk (``asuser.py`` sets
``TMPDIR``) and its processes are in the run's own box with a memory limit on
it (``holder.py``). What reaches this file is what got past both.

Two rules run through all of it, and they are the same two ``one/tests/strays.py``
holds for a test session.

**A process is named by what it really is, never by prose.** A run's brief is
one of the run's own arguments, and the brief that asked for this file quotes
the very paths it sweeps. So nothing is matched on a command line: a process is
swept for the cgroup it is in, the parent it has and its age, and a folder is
swept for where it is and how old it is.

**Politely, then not.** SIGTERM first, so a server closes its port and a holder
writes its ``exit.json``; whatever is still there ``GRACE`` seconds later gets
SIGKILL.

Nothing here ever raises. A sweep that cannot read ``/proc`` on a laptop, or
that races a process out of existence, does less that round and says so in the
log; the program must not stop scheduling because a sweep went wrong.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from . import runprocs

log = logging.getLogger("one.reaper")

#: Where cgroup v2 is mounted.
CGROUP_ROOT = Path("/sys/fs/cgroup")

# The two ceilings this file sweeps on are settings and live in `config.py`
# with the rest of them, as `stray_after` and `scratch_after`. They were once
# written here as well, as constants nothing ever read, which is how a number
# on a screen comes to disagree with the number being acted on. There is one
# of each, and it is the setting.

#: Seconds between the polite signal and the one that cannot be refused.
GRACE = 5.0

#: Folders in the tmpfs that belong to this repository's own tooling, by the
#: prefix each one is made with. Named rather than inferred: ``/tmp`` holds
#: tmux's sockets, PostgreSQL's shared memory and systemd's private folders,
#: and a sweep that took everything old would take those too. Every prefix
#: here is made by something in this repository - the harness in
#: ``tests/e2e/``, the stand-ins in ``rouh/testing/``, Playwright, and the
#: temporary worlds a check of one's own builds.
SCRATCH_PREFIXES = (
    "e2e-serve-",                 # tests/e2e/serve.py, a world held for a browser
    "playwright-artifacts-",
    "playwright-pytest-",
    "playwright_",                # the browser profiles Playwright MCP leaves
    "rouh-test-data-",
    "rouh-objects-check-",
    # The same two under the name they had before 22 September 2026, for
    # anything still on disk from before the rename (RENAME.md).
    "jarvis-test-data-",
    "jarvis-objects-check-",
    "context-editing-",
    "tree-check-",
    "one-dev-",
    "yt-",                        # what the YouTube tool unpacks into
)

#: Folders that are not leftovers themselves but hold one per session, so it is
#: their children that are swept and never the folder itself.
#:
#: ``pytest-of-<user>`` is the one that matters and the one that taught this.
#: pytest makes it once and then a numbered folder inside it for every session,
#: keeping the last three and deleting the rest - except that a session killed
#: part way never deletes anything, so they pile up. On 22 September 2026 it
#: held 2.9 GB in sessions up to three days old while its own modification time
#: was eleven minutes old, because a new session had just made a folder inside
#: it. Swept by its own age it would never go at all; swept by its children's
#: it empties correctly and the folder itself is left for pytest to keep using.
SCRATCH_CONTAINERS = (
    "pytest-of-",
)


# ---------------------------------------------------------------------------
# Reading the process table
# ---------------------------------------------------------------------------

def _pids() -> list[str]:
    try:
        return [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError:
        return []


def _status(pid: str) -> tuple[int, int]:
    """(parent, resident bytes) for one process, out of /proc/<pid>/status.

    One file for both, so a process that exits between two reads is a process
    left out rather than one counted with somebody else's parent.
    """
    parent = resident = 0
    with open(f"/proc/{pid}/status") as fh:
        for line in fh:
            if line.startswith("PPid:"):
                parent = int(line.split()[1])
            elif line.startswith("VmRSS:"):
                resident = int(line.split()[1]) * 1024      # the file is in kB
                break
    return parent, resident


def _cgroup(pid: str) -> str:
    """The cgroup path one process is in, or "" if it cannot be read."""
    try:
        with open(f"/proc/{pid}/cgroup") as fh:
            for line in fh:
                if line.startswith("0::"):
                    return line.strip()[3:]
    except OSError:
        pass
    return ""


def _age(pid: str, boot: float) -> float:
    """How many seconds ago this process started.

    Field 22 of /proc/<pid>/stat is when it started, in clock ticks since the
    machine came up. The command name is field 2 and may itself hold spaces
    and brackets, so the line is cut after its last ``)`` before it is split.
    """
    try:
        with open(f"/proc/{pid}/stat") as fh:
            rest = fh.read().rpartition(")")[2].split()
        return max(0.0, time.time() - (boot + int(rest[19]) / os.sysconf("SC_CLK_TCK")))
    except (OSError, ValueError, IndexError):
        return 0.0


def _boot_time() -> float:
    try:
        with open("/proc/stat") as fh:
            for line in fh:
                if line.startswith("btime "):
                    return float(line.split()[1])
    except OSError:
        pass
    return time.time()


def _command(pid: str, limit: int = 120) -> str:
    """What a process is, for the log and the picture. Never for deciding."""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            argv = [a for a in fh.read().decode("utf-8", "replace").split("\0") if a]
    except OSError:
        return ""
    text = " ".join(argv)
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Table:
    """One photograph of the process table, read once and asked many times.

    Every sweep and the picture want the same four things about the same
    processes, and reading /proc four times would be four different machines.
    A process that exits while this is being taken is left out rather than
    raised over.
    """

    def __init__(self) -> None:
        boot = _boot_time()
        self.parent: dict[int, int] = {}
        self.resident: dict[int, int] = {}
        self.cgroup: dict[int, str] = {}
        self.age: dict[int, float] = {}
        self.children: dict[int, list[int]] = {}
        for name in _pids():
            try:
                parent, resident = _status(name)
            except (OSError, ValueError, IndexError):
                continue                  # gone between the listing and the read
            pid = int(name)
            self.parent[pid] = parent
            self.resident[pid] = resident
            self.cgroup[pid] = _cgroup(name)
            self.age[pid] = _age(name, boot)
            self.children.setdefault(parent, []).append(pid)

    def tree(self, *roots: int) -> list[int]:
        """Every root and everything below it, each pid once.

        Walked rather than recursed, and every pid visited once: a process
        table read a row at a time off a live machine can name a parent that
        has already been reused, and a walk that trusted it would go round for
        ever.
        """
        found: list[int] = []
        seen: set[int] = set()
        stack = list(roots)
        while stack:
            pid = stack.pop()
            if pid in seen or pid not in self.parent:
                continue
            seen.add(pid)
            found.append(pid)
            stack.extend(self.children.get(pid, ()))
        return found

    def held(self, pids) -> int:
        """Resident bytes across a set of processes."""
        return sum(self.resident.get(pid, 0) for pid in pids)


# ---------------------------------------------------------------------------
# Stopping things
# ---------------------------------------------------------------------------

def _signal(pids, sig: int) -> int:
    sent = 0
    for pid in pids:
        try:
            os.kill(pid, sig)
            sent += 1
        except (ProcessLookupError, PermissionError):
            continue
    return sent


def _stop(pids: list[int], *, grace: float = GRACE) -> int:
    """SIGTERM, a moment, then SIGKILL to whatever is left. How many were there.

    Only works on processes this user is allowed to signal, which on the server
    is not the ones that matter: the program runs as ``one`` and everything a
    run starts belongs to the run's own user. ``stop_by_box`` is what is really
    used there, and this is the fallback for a machine where both are the same
    user - a laptop - and for anything a box cannot be made for.
    """
    if not pids:
        return 0
    _signal(pids, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not any(os.path.exists(f"/proc/{pid}") for pid in pids):
            return len(pids)
        time.sleep(0.1)
    _signal([pid for pid in pids if os.path.exists(f"/proc/{pid}")], signal.SIGKILL)
    return len(pids)


def stop_by_box(service: Path, pids: list[int], *, grace: float = GRACE) -> int:
    """Stop processes by putting them in a cgroup and emptying it. How many went.

    A signal is refused across users: the program runs as ``one``, a run's
    processes belong to the run's own user, and ``kill`` from one to the other
    is EPERM. That is why the leak this file was written for could be found and
    not swept.

    A cgroup does not work that way. The service's tree is delegated to this
    user, so it may make a cgroup and move any process into it that it can
    reach by path, whatever that process's owner; and ``cgroup.kill`` ends
    everything inside at once without a signal being sent to anything.
    Measured on this machine on 22 September 2026, as user ``one`` against a
    process owned by ``assistant``:

        os.kill(pid, 0)                  ->  PermissionError, operation not permitted
        write pid to <box>/cgroup.procs  ->  moved
        write 1 to <box>/cgroup.kill     ->  dead

    So this is how a stray is stopped, and it is the same mechanism that ends a
    run: ``holder._empty_the_box`` and ``empty_box`` above. One box for the
    whole sweep, taken away afterwards.

    A process is moved one at a time and one that will not move is left where
    it is rather than taken for stopped: what is reported is what really went
    into the box, so a sweep that could do nothing says nothing rather than
    claiming a gigabyte it never freed.
    """
    if not pids:
        return 0
    box = service / ("swept-" + str(os.getpid()))
    try:
        box.mkdir(exist_ok=True)
    except OSError:
        return _stop(pids, grace=grace)          # no box to be had: try signals
    moved = 0
    try:
        for pid in pids:
            try:
                (box / "cgroup.procs").write_text(str(pid))
                moved += 1
            except OSError:
                continue          # gone, or not ours to move: left where it is
        if moved:
            empty_box(box)
        return moved
    finally:
        with contextlib.suppress(OSError):
            box.rmdir()


# ---------------------------------------------------------------------------
# The boxes
# ---------------------------------------------------------------------------

def own_cgroup() -> Path | None:
    """The cgroup this process is in, or None where there is none to read."""
    path = _cgroup("self")
    if not path:
        return None
    here = CGROUP_ROOT / path.lstrip("/")
    return here if here.is_dir() else None


def service_root(here: Path | None) -> Path | None:
    """The service's own cgroup, from anywhere inside it.

    ``main`` and ``runs`` are the two rooms ``settle`` makes, and ``run-<id>``
    is one run's box in either layout. Anything else is the service itself, and
    the walk stops there rather than climbing out into ``system.slice``, which
    is somebody else's.
    """
    while here is not None and (here.name in ("main", "runs")
                                or here.name.startswith("run-")):
        here = here.parent
    return here


def the_service_or_none(named: str = "") -> Path | None:
    """The cgroup this reaper may sweep, or None, which means it sweeps nothing.

    Getting this wrong is the one way this file could do real harm, so it says
    no in every case it is not certain.

    **A world in a test is never the machine.** ``one/tests/dev_server.py``
    stands a whole program up in a throwaway folder and points its ``cgroup``
    setting at that folder, which has no ``cpu.stat`` in it, so the processor
    and memory gates read nothing and the program is not told what the rest of
    the machine is doing. The reaper reads the same setting the same way: a
    ``cgroup`` that is said by hand and is not a cgroup means there is nothing
    here to sweep.

    Measured on 22 September 2026, and the reason this function exists: a
    program stood up by ``./e2e.sh serve one_app`` inside a run's own box
    walked up from its own cgroup and found ``/system.slice/one.service``, the
    real one, with thirteen real runs in it and an empty run list of its own.
    A sweep from there would have emptied every one of their boxes. What it
    did instead was print ``<- run is over`` beside all of them in
    ``one processes``, which is how it was caught.

    **A program inside a run's box is never the service either.** The real
    program is started by systemd and is in the service's own cgroup or in the
    ``main`` room of it; it is never underneath a ``run-<id>``. Anything that
    is, is a copy of the program being driven by hand inside somebody else's
    run, and it owns nothing on this machine.
    """
    if named:
        path = Path(named)
        return path if (path / "cpu.stat").exists() else None
    here = own_cgroup()
    if here is None:
        return None
    # **A container's own cgroup is never the service.** In a container with
    # a cgroup namespace of its own - the worker of every Rouh instance's stack
    # - the program sees itself in the root, ``0::/``. That root is read-only
    # there, so no box can be made or emptied, and its pid 1 is the container's
    # init, so being orphaned says nothing: the worker's own start script is an
    # orphan by that test. On a machine run by systemd nothing is ever in the
    # root. The runs there are kept by their holders instead (runprocs.py), and
    # what an ended run left behind by ``sweep_marked``.
    if here == CGROUP_ROOT:
        return None
    for part in here.parts:
        if part.startswith("run-"):
            return None
    return service_root(here)


def boxes(service: Path | None) -> list[Path]:
    """Every run's box, whether or not its run is alive.

    Both places one can be. A box normally sits in the service's own cgroup,
    beside the holder that made it. For about ninety minutes on 22 September
    2026 the service was laid out with the boxes under ``runs/`` instead; that
    layout is gone (see "Why there is no per-run memory ceiling" above), and
    this still looks there so that anything left in it is swept rather than
    stranded.
    """
    found: list[Path] = []
    if service is None:
        return found
    root = service.parent if service.name == "main" else service
    for where in (root, root / "runs"):
        try:
            found += [p for p in where.iterdir()
                      if p.is_dir() and p.name.startswith("run-")]
        except OSError:
            continue
    return sorted(found)


def empty_box(box: Path) -> bool:
    """Kill everything in one box and take the folder away. Whether it was there.

    The same two steps as ``holder.Holder._empty_the_box``, from the outside,
    for a box whose holder is not around to empty it.
    """
    try:
        (box / "cgroup.kill").write_text("1")
    except OSError:
        return False
    deadline = time.monotonic() + 1.0
    while True:
        try:
            box.rmdir()
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return True         # killed, even if the folder will not go yet
            time.sleep(0.02)


# ---------------------------------------------------------------------------
# The scratch filesystem
# ---------------------------------------------------------------------------
#
# Module functions rather than methods, because two very different callers ask
# the same question and neither should answer it its own way: the sweep below,
# which deletes what it finds, and Rouh's orb, which only draws it
# (`rouh/machine_load.py`). A rule written twice is a rule that drifts, and
# the number on the screen has to be the number the sweep acts on or the screen
# is lying.


def leftover_folders(root: Path) -> list[Path]:
    """Every folder under ``root`` this repository's own tooling left behind.

    A container's children rather than the container, so that a folder whose
    own modification time is refreshed by every new session is still emptied of
    the sessions nobody wants.
    """
    found: list[Path] = []
    try:
        here = sorted(root.iterdir())
    except OSError:
        return found
    for path in here:
        if not path.is_dir():
            continue
        if path.name.startswith(SCRATCH_PREFIXES):
            found.append(path)
        elif path.name.startswith(SCRATCH_CONTAINERS):
            try:
                found += [child for child in path.iterdir() if child.is_dir()]
            except OSError:
                continue
    return found


def folders_in_use() -> set[Path]:
    """Every folder a live process is standing in or holding a file open in.

    Its working directory and its open files both count: a world whose server
    has a log open inside it is in use even when nothing stands in the folder.
    """
    busy: set[Path] = set()
    for name in _pids():
        try:
            busy.add(Path(os.readlink(f"/proc/{name}/cwd")))
        except OSError:
            pass
        try:
            fds = os.listdir(f"/proc/{name}/fd")
        except OSError:
            continue
        for fd in fds:
            try:
                busy.add(Path(os.readlink(f"/proc/{name}/fd/{fd}")))
            except OSError:
                continue
    return busy


def scratch_report(root: Path, older_than: float, *, busy: set[Path] | None = None) -> dict:
    """What the scratch filesystem is holding, and how much of it has no owner.

    ``bytes`` is the whole filesystem, ``leftover_bytes`` is what our own
    tooling left in it, and ``loose_bytes`` is the part of that which is old
    enough and unheld enough for the sweep to delete. Only the last of those is
    a number to act on; the first two are what it is a share of.
    """
    found: dict = {"path": str(root), "tmpfs": False, "bytes": 0, "total_bytes": 0,
                   "folders": 0, "leftover_bytes": 0, "loose": 0, "loose_bytes": 0,
                   "unreadable": 0}
    if not root.is_dir():
        return found
    try:
        stat = os.statvfs(root)
        found["bytes"] = (stat.f_blocks - stat.f_bfree) * stat.f_frsize
        found["total_bytes"] = stat.f_blocks * stat.f_frsize
        found["tmpfs"] = _is_tmpfs(root)
    except OSError:
        pass
    held = folders_in_use() if busy is None else busy
    now = time.time()
    for folder in leftover_folders(root):
        found["folders"] += 1
        if not readable(folder):
            # Somebody else's, and not to be reported as empty. The sweep hands
            # these to `asuser.py sweep-scratch`, which is that somebody.
            found["unreadable"] += 1
            continue
        size = folder_bytes(folder)
        found["leftover_bytes"] += size
        try:
            stale = now - folder.stat().st_mtime >= older_than
        except OSError:
            continue
        if stale and not any(where == folder or folder in where.parents for where in held):
            found["loose"] += 1
            found["loose_bytes"] += size
    return found


# ---------------------------------------------------------------------------
# Why there is no per-run memory ceiling
# ---------------------------------------------------------------------------
#
# There should be one. A run that leaks ought to be the thing that dies for it,
# inside its own box, rather than the service filling up and the scheduler
# closing somebody else's run to make room. It is not here, and this is the
# record of why, so that the next person to try it starts where this stopped
# rather than where it started.
#
# The kernel will only account a cgroup whose parent has the memory controller
# turned on for its children, and cgroup v2 refuses to turn a controller on for
# the children of a cgroup that holds processes of its own - the "no internal
# processes" rule. The service holds forty-odd: the program, and a holder for
# every run. So the obvious move is the one systemd's own delegation pattern
# makes: put the program and its holders in `one.service/main`, the boxes in
# `one.service/runs`, and turn the controller on at `one.service`.
#
# That was written, and deployed, on 22 September 2026, and it took the service
# down.
#
#     systemd[1]: one.service: Failed to spawn executor: Device or resource busy
#     systemd[1]: one.service: Failed with result 'resources'.
#
# The same rule that made the layout necessary forbids the result. systemd
# starts a service by forking into that service's own cgroup, and a cgroup with
# controllers enabled for its children may not hold a process. Moving the
# program out of `one.service` does not help: systemd puts the next one back.
# So `one.service` cannot have `subtree_control` set and also be restartable,
# and a deploy restarts it every time. The program came up because it had
# already started before the layout was made; the next restart, two minutes
# later, could not, and went round its restart loop until the setting was taken
# off by hand.
#
# Nothing in this file writes to `cgroup.subtree_control` any more, and nothing
# should, at this or any level of the service's own tree.
#
# What would work is a cgroup systemd never starts anything in: a slice of its
# own beside the service, made and handed to this user by the unit at install
# time, with the controller turned on there and the boxes made underneath it.
# That is a change to `deploy/one.service` and to how the machine is set up,
# not a change this file can make on its own, and it is worth doing.
#
# Until then a run's box still ends the run completely, which is the part that
# keeps processes from leaking, and the service's own MemoryMax still bounds
# the lot. What is missing is only the per-run share of it.


# ---------------------------------------------------------------------------
# The sweeps
# ---------------------------------------------------------------------------

class Reaper:
    """What owns whatever a run left behind.

    It is the program's, and the program outlives every run it starts: that is
    the whole reason the sweeping is here and not in the holder, which dies
    with its run, nor in a test fixture, which dies with its session.
    """

    def __init__(self, program) -> None:
        self.p = program
        self.s = program.settings
        #: The service this reaper is allowed to sweep, or None for none at
        #: all, which is a reaper that does nothing. See `the_service_or_none`.
        self.service = the_service_or_none(getattr(self.s, "cgroup", ""))
        #: What the last sweep found, for the picture and the log.
        self.last: dict = {}

    def _under_service(self, path: str) -> bool:
        if self.service is None:
            return False
        mine = str(self.service).replace(str(CGROUP_ROOT), "", 1) or "/"
        return path == mine or path.startswith(mine.rstrip("/") + "/")

    @staticmethod
    def _box_of(path: str) -> str:
        """The run id whose box this cgroup path is, or "" for anywhere else."""
        name = path.rsplit("/", 1)[-1]
        return name[len("run-"):] if name.startswith("run-") else ""

    # -- who is allowed to be here ------------------------------------------

    def _live_runs(self) -> set[str]:
        """The run ids the program still has open. Anything else is nobody's."""
        try:
            from .views import ENDED
            return {r["id"] for r in self.p.views.runs.values() if r["state"] not in ENDED}
        except Exception:
            log.exception("the reaper could not read the run list; sweeping nothing")
            raise

    def _protected(self, table: Table) -> set[int]:
        """Every process that must survive a sweep, whatever its age.

        This process and everything under it - which is the program, its
        holders, and whatever any of them shells out to - and, separately,
        every live run's holder and the tree below it. The holder is named
        because it is not underneath the program: ``Terminals.start`` starts it
        with ``start_new_session=True`` on purpose, so that a deploy can
        restart the program and every run carry on. That is exactly what makes
        a holder look like an orphan, and a holder of a live run is the one
        orphan that is not a stray.
        """
        roots = [os.getpid()]
        for terminal in getattr(self.p.terminals, "by_run", {}).values():
            pid = getattr(terminal, "holder_pid", None)
            if pid:
                roots.append(int(pid))
        return set(table.tree(*roots))

    # -- the three sweeps ---------------------------------------------------

    def sweep_boxes(self, table: Table) -> dict:
        """Empty every run box whose run the program no longer has open.

        The case the holder cannot cover: a holder killed outright never
        reaches its own shutdown, so its box stays, full, for as long as the
        machine is up.
        """
        if self.service is None:
            return {"boxes": 0, "processes": 0, "bytes": 0}
        live = self._live_runs()
        emptied = processes = held = 0
        for box in boxes(self.service):
            if box.name[len("run-"):] in live:
                continue
            inside = [pid for pid, path in table.cgroup.items()
                      if path.endswith("/" + box.name)]
            its_own = table.held(inside)
            held += its_own
            processes += len(inside)
            if empty_box(box):
                emptied += 1
                if inside:
                    log.warning("reaper: emptied %s, which held %d processes and %.0f MB "
                                "after its run was over", box.name, len(inside),
                                its_own / 1048576)
        return {"boxes": emptied, "processes": processes, "bytes": held}

    def sweep_strays(self, table: Table) -> dict:
        """Stop every orphaned, unboxed process in the service, and its tree.

        Orphaned and unboxed is the whole definition of having no owner. A
        process is handed to init only when whoever started it is gone, and
        everything a live run starts is in that run's box, so neither half of
        the test can be true of anything that is still somebody's.
        """
        if self.service is None:
            return {"processes": 0, "bytes": 0, "oldest": 0.0}
        safe = self._protected(table)
        # A second net under the first, and the one that does not depend on the
        # program remembering anything. A holder sits outside every box by
        # design - `Terminals.start` gives it a session of its own so that a
        # deploy can restart the program and every run carry on - and it is
        # orphaned for the same reason, so by cgroup and parentage alone a
        # holder is indistinguishable from a leak. What tells them apart is
        # that a holder has the run's own command underneath it, inside that
        # run's box. Anything with a descendant in a box is therefore somebody
        # working, whatever the program does or does not have in `by_run`, and
        # is never swept.
        boxed = {pid for pid, path in table.cgroup.items() if self._box_of(path)}
        roots = []
        for pid, path in table.cgroup.items():
            if not self._under_service(path):      # another service entirely
                continue
            if self._box_of(path):                 # inside a run's own box
                continue
            if table.parent.get(pid) != 1:         # somebody still owns it
                continue
            if pid in safe:                        # a holder the program knows
                continue
            if table.age.get(pid, 0.0) < self.s.stray_after:
                continue
            if boxed.intersection(table.tree(pid)):   # a holder, by what it holds
                continue
            roots.append(pid)
        if not roots:
            return {"processes": 0, "bytes": 0, "oldest": 0.0}
        family = [pid for pid in table.tree(*roots) if pid not in safe]
        held = table.held(family)
        oldest = max(table.age.get(pid, 0.0) for pid in roots)
        for pid in roots:
            log.warning("reaper: stopping stray %d, %.1f h old, %.0f MB with its tree: %s",
                        pid, table.age.get(pid, 0.0) / 3600,
                        table.held(table.tree(pid)) / 1048576, _command(str(pid)))
        # By the box, not by signal: a signal does not cross users and these
        # never belong to the user the program runs as. `stop_by_box` says why.
        went = stop_by_box(self.service, family)
        if went < len(family):
            log.warning("reaper: %d of %d strays would not move into a box and are "
                        "still running", len(family) - went, len(family))
        # Only what really went is reported freed. A sweep that could not move
        # anything must not claim the memory it did not give back.
        freed = held if went == len(family) else table.held(
            [pid for pid in family if not os.path.exists(f"/proc/{pid}")])
        return {"processes": went, "bytes": freed, "oldest": oldest}

    def sweep_marked(self) -> dict:
        """Where there is no service to sweep: end what this program's ended runs left.

        A holder ends everything its run has when the run ends (runprocs.py),
        so this is only ever a holder that was killed outright and never got
        there. Found by the ``ONE_RUN`` mark every run's processes carry, and
        only for runs this program itself has and has seen end: run ids are
        this program's own, so a world in a test can never reach the real
        program's runs, nor they a world's.
        """
        from .views import ENDED

        ended = {r["id"] for r in self.p.views.runs.values() if r["state"] in ENDED}
        live = {r["id"] for r in self.p.views.runs.values() if r["state"] not in ENDED}
        found = runprocs.ended_runs_processes(ended - live)
        stopped = 0
        for run_id, pids in found.items():
            log.warning("reaper: ending %d process(es) run %s left behind after it ended: %s",
                        len(pids), run_id, ", ".join(_command(str(p), 60) for p in pids[:3]))
            stopped += _stop(pids)
        return {"processes": stopped}

    def _sweep_scratch_as_owner(self) -> dict | None:
        """Ask the run's own user to delete the leftovers, and what it freed.

        None where there is nobody to ask - a laptop, where the program and the
        runs are the same user and the direct path below already worked.

        It is the same sudo rule that starts every run (`asuser.py`), so this
        needs no new privilege, and the rules about what a leftover is travel
        with the code rather than with the arguments: only a root and an age
        are passed.
        """
        docs = getattr(self.p, "documents", None)
        if docs is None or not getattr(self.s, "run_as", ""):
            return None
        argv = docs.asuser_argv("sweep-scratch", "--root", str(self.s.scratch_tmp),
                                "--older-than", str(self.s.scratch_after),
                                user=self.s.run_as)
        try:
            done = subprocess.run(argv, capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("reaper: could not ask %s to sweep the scratch: %s",
                        self.s.run_as, exc)
            return None
        lines = [line for line in done.stdout.splitlines() if line.strip()]
        if not lines:
            log.warning("reaper: the scratch sweep said nothing (exit %s): %s",
                        done.returncode, done.stderr.strip()[:300])
            return None
        try:
            return json.loads(lines[-1])
        except ValueError:
            log.warning("reaper: the scratch sweep said something that is not JSON: %s",
                        lines[-1][:200])
            return None

    def sweep_scratch(self, table: Table) -> dict:
        """Delete the harness's leftovers in the tmpfs that nobody is holding.

        On this machine ``/tmp`` is memory, so a folder left there is memory
        left held, and closing runs never gives it back. Only the prefixes this
        repository's own tooling makes are considered, and only when no process
        has its working directory inside one: a world being driven by a browser
        right now is not old, and a check that is between two commands has its
        files open.
        """
        root = Path(self.s.scratch_tmp)
        if not root.is_dir():
            return {"folders": 0, "bytes": 0}
        # Anything not ours to look inside is not ours to delete either, and on
        # the server that is all of them: the program runs as `one`, a leftover
        # world belongs to the run's own user. Hand those to that user.
        if any(not readable(folder) for folder in leftover_folders(root)):
            done = self._sweep_scratch_as_owner()
            if done is not None and done.get("ok"):
                if done.get("folders"):
                    log.warning("reaper: %s deleted %d leftover folders, %.0f MB of memory",
                                self.s.run_as, done["folders"], done.get("bytes", 0) / 1048576)
                return {"folders": done.get("folders", 0), "bytes": done.get("bytes", 0)}
            if done is not None:
                log.warning("reaper: the scratch sweep refused: %s", done.get("reason"))
        busy = folders_in_use()
        gone = freed = 0
        now = time.time()
        for folder in leftover_folders(root):
            try:
                if now - folder.stat().st_mtime < self.s.scratch_after:
                    continue
            except OSError:
                continue
            if any(held == folder or folder in held.parents for held in busy):
                continue
            size = folder_bytes(folder)
            try:
                shutil.rmtree(folder, ignore_errors=True)
            except Exception:
                continue
            if not folder.exists():
                gone += 1
                freed += size
                log.warning("reaper: deleted %s, %.0f MB of memory nothing was holding",
                            folder, size / 1048576)
        return {"folders": gone, "bytes": freed}

    # -- all three, on the scheduler's tick ---------------------------------

    def sweep(self) -> dict:
        """One round. Never raises: the program must go on scheduling."""
        done: dict = {"at": time.time()}
        if self.service is None:
            # Not the machine's own service: a world in a test, a checkout
            # being driven by hand, or a container. It owns nothing here but
            # its own runs, so it sweeps nothing here - including the scratch,
            # which needs no cgroup to find and would otherwise reach the real
            # /tmp from inside a throwaway world - but what its own ended runs
            # left behind, which carries their own ids.
            done["skipped"] = "this program is not the machine's service"
            try:
                done["marked"] = self.sweep_marked()
            except Exception:
                log.exception("the reaper's sweep of ended runs' processes went wrong")
            self.last = done
            return done
        try:
            table = Table()
        except Exception:
            log.exception("the reaper could not read the process table; nothing swept")
            return done
        for name, run in (("boxes", self.sweep_boxes), ("strays", self.sweep_strays),
                          ("scratch", self.sweep_scratch)):
            try:
                done[name] = run(table)
            except Exception:
                log.exception("the reaper's %s sweep went wrong; carrying on", name)
                done[name] = {"error": True}
        freed = sum(part.get("bytes", 0) for part in done.values() if isinstance(part, dict))
        done["bytes"] = freed
        if freed:
            log.warning("reaper: gave back %.0f MB", freed / 1048576)
        self.last = done
        return done

    # -- the picture --------------------------------------------------------

    def picture(self, *, limit: int = 40) -> dict:
        """What this service is holding right now, process by process.

        Every process in the service's cgroup, largest first, with how old it
        is, how much it holds, which run's box it is in, and whether the next
        sweep would take it. The point of it is that growth is visible before
        it hurts: a list with six strays at the top of it is a different
        machine from the same total with none.
        """
        out: dict = {"at": time.time(), "service": str(self.service or ""),
                     "stray_after": self.s.stray_after,
                     "scratch_after": self.s.scratch_after,
                     "run_memory_max": self.s.run_memory_max}
        try:
            table = Table()
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out
        safe = self._protected(table) if self.service else set()
        try:
            live = self._live_runs()
        except Exception:
            live = set()
        boxed = {pid for pid, path in table.cgroup.items() if self._box_of(path)}
        rows = []
        for pid, path in table.cgroup.items():
            if not self._under_service(path):
                continue
            run = self._box_of(path)
            stray = (not run and table.parent.get(pid) == 1 and pid not in safe
                     and table.age.get(pid, 0.0) >= self.s.stray_after
                     and not boxed.intersection(table.tree(pid)))
            rows.append({
                "pid": pid,
                "run": run,
                "orphan": table.parent.get(pid) == 1,
                "stray": stray,
                "gone_run": bool(run) and run not in live,
                "age": round(table.age.get(pid, 0.0), 1),
                "rss_bytes": table.resident.get(pid, 0),
                "what": _command(str(pid)),
            })
        rows.sort(key=lambda r: r["rss_bytes"], reverse=True)
        out["processes"] = len(rows)
        out["rss_bytes"] = sum(r["rss_bytes"] for r in rows)
        out["strays"] = sum(1 for r in rows if r["stray"])
        out["stray_bytes"] = sum(r["rss_bytes"] for r in rows if r["stray"])
        out["top"] = rows[:limit]
        out["scratch"] = self.scratch_picture()
        return out

    def scratch_picture(self) -> dict:
        """How much memory the scratch filesystem holds, and how much has no owner."""
        return scratch_report(Path(self.s.scratch_tmp), self.s.scratch_after)


def _is_tmpfs(path: Path) -> bool:
    """Whether a folder is on a filesystem that lives in memory.

    It is the difference between a leftover folder costing disk, which is
    nothing on a machine with 395 GB of it, and costing memory, which is what
    made this file necessary.
    """
    try:
        target = os.path.realpath(path)
        with open("/proc/self/mounts") as fh:
            for line in fh:
                fields = line.split()
                if len(fields) > 2 and fields[1] == target:
                    return fields[2] == "tmpfs"
    except OSError:
        pass
    return False


def folder_bytes(folder: Path) -> int:
    """How much a folder holds, following nothing and counting each file once."""
    total = 0
    for here, _, files in os.walk(folder, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(here, name)).st_size
            except OSError:
                continue
    return total


def readable(folder: Path) -> bool:
    """Whether this user can look inside a folder at all.

    The program runs as ``one`` and a leftover world belongs to the run's own
    user, mode 0700, so the answer on the server is no - and a walk of it
    returns zero bytes rather than an error. Zero is the dangerous answer: it
    reads as "nothing there" on a screen and as "nothing freed" in a sweep. So
    it is asked directly and reported as its own number.
    """
    try:
        os.listdir(folder)
        return True
    except OSError:
        return False
