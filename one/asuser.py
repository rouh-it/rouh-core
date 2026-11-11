"""Everything the program does as the user a run works as, in one small command.

The program runs as its own Linux user, ``one``, and never as root. A run in
the person's workspace works as the ``assistant`` user, who owns that copy of
the workspace and its GitHub key. Rouh's jobs on the server and its changes
to itself work as the ``rouh`` user, who may use sudo (D41). The one place
they meet is this file: the server's sudo rule lets ``one`` run exactly this
command as those two users, and nothing else.

    sudo -n -u assistant /usr/bin/python3 -I /srv/one/app/one/asuser.py <what> ...

What it can be asked to do:

    worktree-add     make a run's own checkout, on its own branch
    worktree-remove  take a finished run's checkout away
    write            write a file inside a run's checkout, from stdin
    drop             write a file dropped on a run's terminal into its own
                     folder, from stdin, under a name nothing else has
    seed-trust       tell the run's agent the checkout is trusted, so it
                     starts straight away and loads the run's hooks
    land             put a run's commits on main and push them, or push its
                     own branch for a pull request. On main it is land.sh that
                     does the replaying and the pushing: see the note on land()
    clone            make a space: one clone of a repository
    inspect          what a path on this server is: a folder, a bare repository
    link             make a space of a folder already on this server
    agent            start the run's agent, Claude Code or Codex, in its
                     checkout, with a clean
                     environment
    shell            start a login shell in a folder, for a person's run
    transcript       read the transcript the run's agent writes, and with
                     --follow go on reading it as it grows (the Read tab)

It prints one line of JSON for everything but ``agent`` and ``shell``, which
become the program they start, and ``transcript``, which prints the
transcript's own lines.

It uses only the standard library and runs on the server's system Python,
which is 3.10, so it does not depend on the program's own environment.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import pwd
import re
import select
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


# The sudo command also runs directly under python3 -I, without a package path.
if __package__:
    from . import agent_trust as _agent_trust
    from . import agent_mcp as _agent_mcp
    from . import agent_environment as _agent_environment
    from . import sealed as _sealed
else:
    import importlib.util

    _trust_spec = importlib.util.spec_from_file_location(
        "one.agent_trust", os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_trust.py"))
    _agent_trust = importlib.util.module_from_spec(_trust_spec)
    _trust_spec.loader.exec_module(_agent_trust)
    _mcp_spec = importlib.util.spec_from_file_location(
        "one.agent_mcp", os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_mcp.py"))
    _agent_mcp = importlib.util.module_from_spec(_mcp_spec)
    _mcp_spec.loader.exec_module(_agent_mcp)
    _environment_spec = importlib.util.spec_from_file_location(
        "one.agent_environment", os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_environment.py"))
    _agent_environment = importlib.util.module_from_spec(_environment_spec)
    _environment_spec.loader.exec_module(_agent_environment)
    _sealed_spec = importlib.util.spec_from_file_location(
        "one.sealed", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sealed.py"))
    _sealed = importlib.util.module_from_spec(_sealed_spec)
    _sealed_spec.loader.exec_module(_sealed)

SAFE_PATH = _agent_environment.SAFE_PATH
PASSED_ON = _agent_environment.PASSED_ON
GUARD_BIN = _agent_environment.GUARD_BIN
OWN_BIN = _agent_environment.OWN_BIN

#: The files the program writes into a run's checkout. They are never part of
#: the run's work and never reach the repository.
#: ``.secrets`` is where a box handed to a run is put (``sealed.py``): never committed, whatever
#: the run does, and shredded when it ends.
OWN_FILES = (".one", ".secrets")

MACHINE_MCP_SERVERS = _agent_mcp.MACHINE_MCP_SERVERS


def _mcp_servers(path: str) -> dict:
    return _agent_mcp._mcp_servers(path)


def _machine_mcp_servers() -> dict:
    return _agent_mcp._machine_mcp_servers(sys.modules[__name__])


def _pinned_browser(servers: dict) -> dict:
    return _agent_mcp._pinned_browser(servers)


def _check_playwright(servers: dict, env: dict, *, cwd: str) -> None:
    _agent_mcp.check_playwright(servers, env, cwd=cwd)


CODEX_PASSES_ON = _agent_mcp.CODEX_PASSES_ON


def _write_merged_mcp(cwd: str) -> str:
    return _agent_mcp._write_merged_mcp(cwd, sys.modules[__name__])


def _out(data: dict) -> int:
    sys.stdout.write(json.dumps(data) + "\n")
    sys.stdout.flush()
    return 0 if data.get("ok", True) else 1


def _home() -> str:
    return _agent_environment._home(sys.modules[__name__])


def _clean_env(extra: dict | None = None) -> dict:
    return _agent_environment._clean_env(extra, sys.modules[__name__])


def _git(*args: str, cwd: str | None = None, timeout: float = 120.0) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=_clean_env({"GIT_TERMINAL_PROMPT": "0"}))
    return proc.returncode, proc.stdout, proc.stderr


def _inside(path: str, root: str) -> bool:
    path = os.path.realpath(path)
    root = os.path.realpath(root)
    return path == root or path.startswith(root.rstrip("/") + "/")


# -- the checkout --------------------------------------------------------------


#: A repository with one of these branches follows its own path to main: a
#: run's work goes up on a branch of its own, for a pull request into it, and
#: never straight to main (D42, the person's rule of 15 September).
DEVELOPMENT = ("develop", "development")


def _default_branch(repo: str) -> str:
    """The branch the remote calls its own; main when it does not say."""
    rc, out, _ = _git("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD", cwd=repo)
    name = out.strip()
    return name.split("/", 1)[1] if rc == 0 and "/" in name else "main"


def _where_from(repo: str) -> tuple[str, str]:
    """The branch a run starts from, and how its work is saved: "main" or "branch"."""
    for name in DEVELOPMENT:
        rc, _, _ = _git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{name}", cwd=repo)
        if rc == 0:
            return name, "branch"
    return _default_branch(repo), "main"


@contextlib.contextmanager
def _repo_lock(repo: str):
    """One change at a time to a repository's shared records.

    A new checkout writes its branch's upstream into the repository's own
    config, and removing one deletes it again. On 15 September two runs
    started at the same moment collided on .git/config.lock, and the second
    could not start. The lock goes when the process ends, however it ends.
    """
    code, gitdir, _ = _git("rev-parse", "--absolute-git-dir", cwd=repo)
    if code:
        yield
        return
    with open(os.path.join(gitdir.strip(), "one-checkouts.lock"), "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def worktree_add(args) -> int:
    if not _inside(args.path, args.runs):
        return _out({"ok": False, "reason": f"{args.path} is not inside {args.runs}"})
    if args.fetch:
        rc, _, err = _git("fetch", "-q", "origin", cwd=args.repo)
        if rc != 0:
            # Not fatal: the base may still be there from the last fetch.
            sys.stderr.write(f"fetch failed: {err.strip()}\n")
    if args.base == "auto":
        target, flow = _where_from(args.repo)
        base = f"origin/{target}"
    else:
        target, flow, base = args.base.split("/", 1)[-1], "main", args.base
    with _repo_lock(args.repo):
        rc, _, err = _git("worktree", "add", "-q", "-b", args.branch, args.path, base, cwd=args.repo)
    if rc != 0:
        return _out({"ok": False, "reason": err.strip()[:500]})
    rc, sha, _ = _git("rev-parse", "HEAD", cwd=args.path)
    return _out({"ok": True, "path": args.path, "branch": args.branch, "base_sha": sha.strip(),
                 "target": target, "flow": flow})


def _a_run_folder(path: str, runs: str) -> bool:
    """Inside the runs folder, and never the runs folder itself or its scratch area."""
    real, root = os.path.realpath(path), os.path.realpath(runs)
    return _inside(real, root) and real not in (root, os.path.join(root, "scratch"))


def worktree_remove(args) -> int:
    if not _a_run_folder(args.path, args.runs):
        return _out({"ok": False, "reason": f"{args.path} is not a run's folder inside {args.runs}"})
    with _repo_lock(args.repo):
        rc, _, err = _git("worktree", "remove", "--force", args.path, cwd=args.repo)
        if rc != 0 and os.path.isdir(args.path):
            shutil.rmtree(args.path, ignore_errors=True)
            _git("worktree", "prune", cwd=args.repo)
        if args.branch:
            _git("branch", "-D", args.branch, cwd=args.repo)
    return _out({"ok": True, "removed": not os.path.exists(args.path)})


def status(args) -> int:
    """Whether a run's checkout holds anything not yet on the remote's main.

    ``dirty`` is changed files never committed, the program's own .one folder
    left out; ``unsaved`` is commits whose change is not on origin/main.

    Since the move into the containers a run's commits reach main through the
    protected core, which pushes from somewhere else and often replays them
    under new ids, so this checkout's origin/main is neither brought up to
    date nor holds the run's own commit ids. On 31 October 2026 that made
    every run that had landed and deployed end "unfinished: it left 1 commit
    that never reached main" (1d79af90, 2d6c494e, f2f3d5ad, 9cac1ec6,
    f18345b8). So the target is fetched first, and a commit counts as unsaved
    only when no commit on the target carries the same patch, which is how
    land.sh itself decides what is already landed (git cherry).

    Since 3 November 2026 it reads the landing's own record first
    (``--landed-head``, the run's commit the last landing took), and only a
    run with no record is compared by patch; see ``_unsaved``.

    A fetch that fails leaves the last copy of the target to compare with, as
    before, and a count that cannot be made is ``None``, never 0: not knowing
    is never nothing to lose.
    """
    if not os.path.isdir(args.path):
        return _out({"ok": True, "exists": False})
    own = [f":(exclude){name}" for name in OWN_FILES]
    rc, porcelain, _ = _git("status", "--porcelain", "--", ".", *own, cwd=args.path)
    branches = [args.target] + ([args.also] if args.also else [])
    for name in branches:
        # Bring the remote's copy up to date; on failure the last one stands.
        try:
            _git("fetch", "-q", "origin", f"+refs/heads/{name}:refs/remotes/origin/{name}",
                 cwd=args.path, timeout=60.0)
        except (OSError, subprocess.SubprocessError):
            pass
    against = f"origin/{args.target}"
    if args.also:
        # A run whose work goes up on its own branch: once pushed, that is where it is saved.
        pushed, _, _ = _git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{args.also}",
                            cwd=args.path)
        if pushed == 0:
            against = f"origin/{args.also}"
    unsaved = _unsaved(args.path, against, getattr(args, "landed_head", "") or "")
    return _out({"ok": rc == 0 and unsaved is not None, "exists": True,
                 "dirty": bool(porcelain.strip()), "unsaved": unsaved})


def _unsaved(path: str, against: str, landed_head: str) -> int | None:
    """How many of the checkout's commits are not on ``against``; None when it cannot be told.

    Read from the landing's own record first: ``landed_head`` is the run's
    commit the last landing took (`_with_head`), so only what was committed
    after it can be left, whatever ids or shape the replay gave the rest. A
    run with no such record (one that never landed, or one from before 3
    November 2026) is compared by patch, as before.

    Either way a commit still counted is then looked at once more: when the
    target holds every file it touched byte for byte as the commit left it,
    its change is there. That is exactly run 5979a8ce, whose commit added a
    file Rouh had already saved to main and so landed one file smaller, with
    another patch (docs/landing-architecture.md). It can only ever say a
    commit is saved when the target really has what it wrote.
    """
    if landed_head and _git("merge-base", "--is-ancestor", landed_head, "HEAD",
                            cwd=path)[0] == 0:
        rc, listed, _ = _git("rev-list", f"{landed_head}..HEAD", cwd=path)
    else:
        rc, listed, _ = _git("rev-list", "--right-only", "--cherry-pick",
                             f"{against}...HEAD", cwd=path)
    if rc != 0:
        return None
    commits = [line.strip() for line in listed.splitlines() if line.strip()]
    if commits:
        # Those whose patch the target has are there too (a run that ran ./land.sh itself).
        rc, patched, _ = _git("rev-list", "--right-only", "--cherry-pick",
                              f"{against}...HEAD", cwd=path)
        if rc == 0:
            still = {line.strip() for line in patched.splitlines() if line.strip()}
            commits = [c for c in commits if c in still]
    return sum(1 for c in commits if not _on_target(path, c, against))


def _on_target(path: str, commit: str, against: str) -> bool:
    """Whether ``against`` holds every file ``commit`` touched exactly as it left them."""
    rc, files, _ = _git("diff-tree", "--no-commit-id", "--name-only", "-r", "-m",
                        "--first-parent", commit, cwd=path)
    names = sorted({line.strip() for line in files.splitlines() if line.strip()})
    if rc != 0 or not names:
        return False
    rc, _, _ = _git("diff", "--quiet", commit, against, "--", *names, cwd=path)
    return rc == 0


def rmtree(args) -> int:
    """Remove a run's folder that is not a git checkout: a scratch run's."""
    if not _a_run_folder(args.path, args.runs):
        return _out({"ok": False, "reason": f"{args.path} is not a run's folder inside {args.runs}"})
    shutil.rmtree(args.path, ignore_errors=True)
    return _out({"ok": True, "removed": not os.path.exists(args.path)})


def sweep_scratch(args) -> int:
    """Delete the leftover worlds in the scratch filesystem, as their owner.

    The other half of ``reaper.py``, and it is here rather than there because
    of who owns what. The program runs as ``one``; everything a run makes
    belongs to the run's own user, mode 0700, in a sticky ``/tmp`` where only
    the owner may unlink. So the program can see a leftover world and can
    neither measure nor delete it: on 22 September 2026 its sweep reported
    "7 loose folders, 0 MB" and freed nothing, which is exactly that.

    Processes needed no such help - a cgroup ends those whoever owns them - so
    this is the only part of the sweep that has to change hands, and the sudo
    rule that already lets the program run this file covers it with no new
    privilege of any kind.

    **What may be deleted is decided here, not by the caller.** The caller
    hands over a root and an age and nothing else; the rules are read from
    ``reaper.py``, the same ones the sweep and Jarvis's orb use, so there is
    one definition of a leftover and no list of paths that a mistake upstream
    could widen. A folder goes only when it is directly under the root, is
    named by one of the prefixes this repository's own tooling makes, is older
    than the age, and no live process is holding it open.
    """
    root = Path(args.root)
    older = max(float(args.older_than), 60.0)
    if not root.is_dir():
        return _out({"ok": False, "reason": f"{args.root} is not a folder"})
    reaper = _reaper()
    if reaper is None:
        return _out({"ok": False, "reason": "reaper.py could not be imported"})
    busy = reaper.folders_in_use()
    now = time.time()
    gone, freed, kept = [], 0, 0
    for folder in reaper.leftover_folders(root):
        try:
            if now - folder.stat().st_mtime < older:
                kept += 1
                continue
        except OSError:
            continue
        if any(where == folder or folder in where.parents for where in busy):
            kept += 1
            continue
        size = reaper.folder_bytes(folder)
        shutil.rmtree(folder, ignore_errors=True)
        if folder.exists():
            kept += 1
            continue
        gone.append(str(folder))
        freed += size
    return _out({"ok": True, "folders": len(gone), "bytes": freed,
                 "kept": kept, "removed": gone[:50]})


def _reaper():
    """``one.reaper``, for the rules about what a leftover is.

    This file is run as a script under ``python3 -I``, so its own folder is on
    the path and the package above it is not. The package is what holds the
    rules, and they are not written twice.
    """
    above = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if above not in sys.path:
        sys.path.insert(0, above)
    try:
        from one import reaper
        return reaper
    except Exception:
        return None


def write(args) -> int:
    if not _inside(args.path, args.runs):
        return _out({"ok": False, "reason": f"{args.path} is not inside {args.runs}"})
    data = sys.stdin.buffer.read()
    folder = os.path.dirname(args.path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".write-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, int(args.mode, 8))
    os.replace(tmp, args.path)
    return _out({"ok": True, "bytes": len(data)})


def drop(args) -> int:
    """Write a file dropped on a run's terminal into its own folder (D52).

    Unlike ``write`` it never overwrites: a second screenshot.png lands beside
    the first as screenshot-2.png. The name is chosen here, as the run's own
    user, because that user is the one who can read the folder; the program
    cannot, and would be guessing.
    """
    if not _inside(args.path, args.runs):
        return _out({"ok": False, "reason": f"{args.path} is not inside {args.runs}"})
    data = sys.stdin.buffer.read()
    folder = os.path.dirname(args.path)
    os.makedirs(folder, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(args.path))
    mode = int(args.mode, 8)
    for nth in range(1, 1000):
        path = os.path.join(folder, stem + ("" if nth == 1 else f"-{nth}") + ext)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        except FileExistsError:
            continue
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return _out({"ok": True, "path": path, "bytes": len(data)})
    return _out({"ok": False, "reason": f"there are already a thousand files called {stem}{ext}"})


def secrets_put(args) -> int:
    """Put the boxes handed to a run in ``<cwd>/.secrets``, as the run's own user (``sealed.py``).

    What goes in comes on stdin, as JSON, and never on a command line; nothing of it is printed.
    """
    if not _inside(args.cwd, args.runs) or os.path.realpath(args.cwd) == os.path.realpath(args.runs):
        return _out({"ok": False, "reason": f"{args.cwd} is not a run's folder inside {args.runs}"})
    try:
        given = json.loads(sys.stdin.buffer.read() or b"{}").get("boxes") or []
        written = _sealed.put(args.cwd, given)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return _out({"ok": False, "reason": f"the boxes could not be written: {type(exc).__name__}"})
    return _out({"ok": True, "written": len(written)})


def _transcript_files(path: str) -> list[str]:
    """An agent's own transcript and its sub-agents', when ``path`` is one this user's agent wrote."""
    home = _home()
    real = os.path.realpath(path)
    if not real.endswith(".jsonl") or not any(_inside(real, os.path.join(home, where))
                                              for where in TRANSCRIPTS):
        return []
    out = [real]
    subagents = os.path.join(real[:-len(".jsonl")], "subagents")
    with contextlib.suppress(OSError):
        out += [os.path.join(subagents, n) for n in os.listdir(subagents) if n.endswith(".jsonl")]
    return out


def secrets_read(args) -> int:
    """What a run's boxes hold, on stdout to the program alone, so it can scrub its own record of
    the run's terminal (``tty.log``, which the run's user cannot write) before they are shredded."""
    if not _inside(args.cwd, args.runs) or os.path.realpath(args.cwd) == os.path.realpath(args.runs):
        return _out({"ok": False, "reason": f"{args.cwd} is not a run's folder inside {args.runs}"})
    held = _sealed.read(_sealed.folder(args.cwd))
    return _out({"ok": True, "boxes": [{"number": n, "content": c} for n, c in held]})


def secrets_shred(args) -> int:
    """Scrub a run's transcript of what its boxes held, then shred them (``sealed.shred``)."""
    if not _inside(args.cwd, args.runs) or os.path.realpath(args.cwd) == os.path.realpath(args.runs):
        return _out({"ok": False, "reason": f"{args.cwd} is not a run's folder inside {args.runs}"})
    scrub = [f for path in (args.scrub or []) for f in _transcript_files(path)]
    scrub.append(os.path.join(args.cwd, ".one", "claude-debug.log"))
    got = _sealed.shred(args.cwd, scrub)
    return _out({"ok": True, **got})


def seed_trust(args) -> int:
    """Answer the agent's first-run questions for this checkout before it starts."""
    if args.engine == "codex":
        return _seed_codex_trust(args)
    return _seed_claude_trust(args)


def _toml_str(text: str) -> str:
    return _agent_trust._toml_str(text)


def _codex_home() -> str:
    return _agent_trust._codex_home(sys.modules[__name__])


def _seed_codex_trust(args) -> int:
    return _agent_trust._seed_codex_trust(args, sys.modules[__name__])


def _claude_project_root(folder: str) -> str | None:
    return _agent_trust._claude_project_root(folder)


def _seed_claude_trust(args) -> int:
    return _agent_trust._seed_claude_trust(args, sys.modules[__name__])


# -- landing -------------------------------------------------------------------


def land(args) -> int:
    """Put a run's commits where they belong, through the one thing that may push.

    What is still this file's: anything the run left uncommitted is committed
    first, so nothing it made is lost; the program's own per-run files are
    refused outright, because they hold the run's hook key; and a repository
    with a development branch has its work pushed on the run's own branch for a
    pull request, which never touches main and so can never collide with it.

    What is not: the replaying and the pushing onto main. That is ``land.sh``
    at the root of this repository, and it is the only thing anywhere allowed
    to push to main (cards 488 and 489). It compares by patch rather than by
    text, so work already on main is reported as landed instead of colliding
    with itself; it takes an exclusive lock, so two runs never land in the same
    moment; it turns rerere on, so a conflict resolved once resolves itself; it
    keeps the work exactly as the run wrote it on a branch of its own before
    anything is resolved; and when it does collide it writes one record and
    hands the run a brief telling it to reconcile the intent rather than the
    text. See ``_land_sh`` below and ``rouh/conflicts.py``.

    With ``--leave-uncommitted``, what the run left uncommitted stays out of
    main and stays in the checkout, which is then kept for a person: Rouh's
    own code, where a change whose tests failed is left uncommitted on purpose.
    """
    path, target = args.path, args.target
    if not _inside(path, args.runs):
        return _out({"ok": False, "landed": False, "reason": f"{path} is not inside {args.runs}"})
    own = [f":(exclude){name}" for name in OWN_FILES]
    rc, gitdir, _ = _git("rev-parse", "--absolute-git-dir", cwd=path)
    mid_rebase = rc == 0 and any(
        os.path.isdir(os.path.join(gitdir.strip(), name))
        for name in ("rebase-merge", "rebase-apply"))
    if mid_rebase:
        # Half of a replay somebody is in the middle of. What `git status` calls
        # changes here are conflict markers, and committing those would put
        # `<<<<<<<` on main.
        return _out({"ok": True, "landed": False, "clash": False,
                     "reason": "a replay is half done in its checkout, so nothing was "
                               "committed or pushed. Finish or abort the rebase first"})
    rc, status, _ = _git("status", "--porcelain", "--", ".", *own, cwd=path)
    left = False
    if rc == 0 and status.strip() and not args.leave_uncommitted:
        _git("add", "-A", "--", ".", *own, cwd=path)
        rc, _, _ = _git("commit", "-q", "-m", args.leftover_message, cwd=path)
        left = rc == 0
    rc, base, _ = _git("merge-base", "HEAD", f"origin/{target}", cwd=path)
    base = base.strip()
    if rc != 0 or not base:
        return _out({"ok": True, "landed": False, "committed_leftovers": left,
                     "reason": f"its branch shares no history with {target}"})
    rc, count, _ = _git("rev-list", "--count", f"{base}..HEAD", cwd=path)
    commits = int((count or "0").strip() or 0) if rc == 0 else 0
    if commits == 0:
        if not args.push_branch and _own_commits_on_target(path, args.base):
            # Nothing to replay because the run pushed its own commits already,
            # with `./land.sh` inside its turn, which is what a run in Rouh's
            # own code is told to do. That is work on main, not a run that
            # saved nothing, and it used to be answered here as "nothing new"
            # before land.sh was ever asked: every change that landed itself
            # from 20 September 2026 on was put in front of the person as
            # "Not saved", 3de0fe3 and 1bff291 among them. land.sh's `--from`
            # is written for exactly this, and says whether it is live too.
            got = _land_sh(args, path)
            if got.get("landed"):
                got["pushed_itself"] = True
                # What its own commits changed, which land.sh does not say on
                # this path and the card lists, and which Rouh reads as what
                # the run made (`conversations.adopt_made_task`). Only the
                # commits made in this checkout: when its land.sh replayed it
                # over something that landed meanwhile, `base..HEAD` holds
                # that too, and on 30 October 2026 a list like it gave task
                # 163 a chat that was never its own.
                got.setdefault("files", _own_files(path, args.base))
            got["committed_leftovers"] = left
            return _out(_with_head(got, path))
        return _out({"ok": True, "landed": False, "committed_leftovers": left,
                     "reason": "nothing new to land"})
    _, files, _ = _git("diff", "--name-only", f"{base}..HEAD", cwd=path)
    files_list = [line for line in files.splitlines() if line.strip()]
    own = [f for f in files_list if f.split("/", 1)[0] in OWN_FILES]
    if own:
        # The program's own files hold the run's hook key. They never leave.
        return _out({"ok": True, "landed": False, "files": files_list, "commits": commits,
                     "reason": "its commits include the program's own files "
                               f"({', '.join(own[:3])}), so nothing was pushed"})
    if args.push_branch:
        # A repository with a development branch (D42): the work goes up on
        # the run's own branch, for a pull request into it; nothing else moves.
        _, head, _ = _git("rev-parse", "HEAD", cwd=path)
        found, there, _ = _git("rev-parse", "--verify", "-q",
                               f"refs/remotes/origin/{args.push_branch}", cwd=path)
        if found == 0 and there.strip() == head.strip():
            return _out({"ok": True, "landed": False, "committed_leftovers": left,
                         "reason": "nothing new to land"})
        rc, _, err = _git("push", "-q", "origin", f"HEAD:refs/heads/{args.push_branch}", cwd=path)
        if rc != 0:
            return _out({"ok": True, "landed": False, "files": files_list, "commits": commits,
                         "reason": f"the push was refused: {err.strip()[:200]}"})
        return _out({"ok": True, "landed": True, "sha": head.strip(), "files": files_list,
                     "commits": commits, "branch": args.push_branch,
                     "compare": _compare_url(path, target, args.push_branch),
                     "landed_head": head.strip()})
    if args.no_push:
        rc, sha, _ = _git("rev-parse", "HEAD", cwd=path)
        return _out({"ok": True, "landed": False, "reason": "not pushed, as asked",
                     "sha": sha.strip(), "files": files_list, "commits": commits})
    got = _land_sh(args, path)
    got.setdefault("files", files_list)
    got.setdefault("commits", commits)
    got["committed_leftovers"] = left
    return _out(_with_head(got, path))


def _with_head(got: dict, path: str) -> dict:
    """A landing's answer with ``landed_head``: the run's own commit it took, when it landed.

    The landing knows exactly which of the run's commits it put on the target,
    and it is the only one that does: ``land.sh`` and the protected core often
    replay them under new ids, and a replay that meets a file the target already
    has makes a smaller commit with a different patch. Until 3 November 2026
    nothing wrote this down, so the run's end guessed by comparing patches, and
    run 5979a8ce, whose task's ``.object.json`` Rouh had saved to main a few
    minutes before the run's commit landed without it, was told to the person
    as "1 commit that never reached main" though every byte of it was there
    (docs/landing-architecture.md). The run is at its prompt while it lands,
    so its HEAD now is what was handed over; whatever it commits after this is
    what is left (``status --landed-head``).
    """
    if got.get("landed"):
        rc, head, _ = _git("rev-parse", "HEAD", cwd=path)
        if rc == 0 and head.strip():
            got["landed_head"] = head.strip()
    return got


#: Where ``land.sh`` is, from here: the root of this repository, which holds
#: both services. A deployment that keeps it somewhere else names it in the
#: environment; nothing on the server does.
LAND_SH = os.environ.get("ONE_LAND_SCRIPT") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "land.sh")


#: What a reflog entry of a commit made in this checkout starts with: one it
#: committed, or one of its own it replayed, picked or reverted. The start,
#: finish and abort of a replay, a reset, a checkout and a pull's fast-forward
#: are left out, because the commit they name is somebody else's.
_MADE_HERE = re.compile(r"^(commit\b|cherry-pick\b|revert\b|"
                        r"[\w -]*rebase[\w -]*\((pick|continue|reword|edit|squash|fixup)\))")


def _own_files(path: str, base: str) -> list[str]:
    """The files the checkout's own commits since ``base`` changed, in the order git names them.

    A commit counts when the checkout's reflog says it was made here and it
    is in ``base..HEAD`` now; a merge is never one, since what it brings in is
    the other side's. With no reflog to read, every commit since ``base``
    counts, which is what this answered before.
    """
    rc, listed, _ = _git("rev-list", "--no-merges", f"{base}..HEAD", cwd=path)
    since = [line.strip() for line in listed.splitlines() if line.strip()] if rc == 0 else []
    rc, log, _ = _git("reflog", "--format=%H %gs", "HEAD", cwd=path)
    read = rc == 0 and bool(log.strip())
    made = {line.split(" ", 1)[0] for line in log.splitlines()
            if read and " " in line and _MADE_HERE.match(line.split(" ", 1)[1])}
    mine = [sha for sha in since if sha in made]
    if not read:
        # No reflog to read at all. A reflog that names none of these commits
        # means none of them are the checkout's own, and their files are
        # somebody else's landing, which is how a new task was handed another
        # task's fork on 30 October 2026.
        _, files, _ = _git("diff", "--name-only", f"{base}..HEAD", cwd=path)
        return [line for line in files.splitlines() if line.strip()]
    seen: dict[str, None] = {}
    for sha in reversed(mine):
        _, files, _ = _git("diff-tree", "--no-commit-id", "--name-only", "-r", sha, cwd=path)
        for line in files.splitlines():
            if line.strip():
                seen.setdefault(line.strip(), None)
    return list(seen)


def _own_commits_on_target(path: str, base: str) -> bool:
    """Whether the run committed anything since ``base``, the commit its branch was made from.

    Asked only once HEAD is known to be on the target already, so a yes means
    the run's own commits reached it: it landed them itself. No base, or a base
    this checkout does not hold, is a no, and the run is answered as having
    nothing new, the way it always was.
    """
    if not base:
        return False
    rc, _, _ = _git("rev-parse", "--verify", "-q", f"{base}^{{commit}}", cwd=path)
    if rc != 0:
        return False
    rc, count, _ = _git("rev-list", "--count", f"{base}..HEAD", cwd=path)
    return rc == 0 and int((count or "0").strip() or 0) > 0


def _land_sh(args, path: str) -> dict:
    """Hand the replay and the push to ``land.sh``, and read its answer.

    Everything the ladder does lives there and not here: the patch-id check that
    catches work already on main, the lock that stops two jobs landing in the
    same moment, rerere, the branch that keeps the work as the job wrote it, the
    conflict record and the brief a worker is handed back. This turns its JSON
    into the answer ``Documents.land`` has always given, with these fields added:
    ``already`` when the work was on main before this ran, ``conflict`` naming the
    record, ``handback`` holding what to tell the run, and ``deployed`` with
    ``deploy_reason`` saying whether the commit it pushed is what this machine is
    now serving. A landing is not finished until it is, so the ``reason`` it
    gives already says which of the two happened, in the words a person hears.

    A failure to run it at all is a clash rather than a landing, because the one
    thing that must never happen here is reporting work as saved when it is not.
    """
    argv = [LAND_SH, "--path", path, "--target", args.target, "--quiet"]
    if getattr(args, "run", ""):
        argv += ["--run", args.run]
    if getattr(args, "title", ""):
        argv += ["--title", args.title]
    if getattr(args, "base", ""):
        argv += ["--from", args.base]
    if getattr(args, "land_dir", ""):
        argv += ["--land-dir", args.land_dir]
    if args.leave_uncommitted:
        # A change left uncommitted on purpose is put aside for the replay and
        # put back after it; git refuses to replay over it otherwise.
        argv += ["--autostash"]
    if getattr(args, "merge", False):
        argv += ["--merge"]
    if os.path.isdir(os.path.join(path, ".one")):
        argv += ["--beside", os.path.join(path, ".one")]
    extra = {"GIT_TERMINAL_PROMPT": "0"}
    if getattr(args, "claude", ""):
        # The Claude Code land.sh's merge pass runs (`rouh/merge_pass.py`): the
        # program's own, which in a test world is its stand-in.
        extra["ROUH_MERGE_CLAUDE"] = args.claude
    try:
        # land.sh itself is bash; the containers' own (bin/rouh-land) runs as what it is.
        proc = subprocess.run(["bash", *argv] if LAND_SH.endswith(".sh") else argv, capture_output=True, text=True,
                              timeout=1800, env=_clean_env(extra))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": True, "landed": False, "clash": False,
                "reason": f"land.sh could not be run: {type(exc).__name__}: {exc}"}
    said = [line for line in proc.stdout.splitlines() if line.strip()]
    try:
        out = json.loads(said[-1]) if said else {}
    except ValueError:
        out = {}
    if not isinstance(out, dict) or "state" not in out:
        tail = (proc.stderr or proc.stdout).strip()[-300:]
        return {"ok": True, "landed": False, "clash": False,
                "reason": f"land.sh said nothing readable (exit {proc.returncode}): {tail}"}
    state = str(out.get("state") or "")
    answer: dict = {"ok": True, "landed": bool(out.get("landed")),
                    "sha": out.get("sha"), "reason": out.get("reason") or ""}
    for key in ("already", "conflict", "pre_branch", "question", "attempt", "handback",
                "both_rewrote", "dropped", "files", "commits",
                # Since 21 September 2026 landing includes deploying, and these
                # three are that half of the answer: whether the commit is being
                # served, one word for what happened, and the sentence saying it.
                "deployed", "deploy", "deploy_reason"):
        if out.get(key) not in (None, "", []):
            answer[key] = out[key]
    if state in ("handback", "needs-person"):
        # The same word ``runs.py`` has always read to send a run back to fix a
        # clash itself, so nothing downstream had to learn a new one. Which rung
        # of the ladder it is is in ``conflict`` and ``handback``.
        answer["clash"] = True
        answer["needs_person"] = state == "needs-person"
    elif state == "nothing":
        answer["reason"] = "nothing new to land"
    elif state == "parked":
        answer["parked"] = True
    return answer


def _compare_url(path: str, target: str, branch: str) -> str | None:
    """Where on GitHub the pull request of a branch into the target is opened."""
    rc, url, _ = _git("remote", "get-url", "origin", cwd=path)
    found = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url.strip()) if rc == 0 else None
    return f"https://github.com/{found.group(1)}/compare/{target}...{branch}?expand=1" if found else None


def clone(args) -> int:
    """Make a space: one clone of a repository, directly inside the spaces folder."""
    real, root = os.path.realpath(args.path), os.path.realpath(args.root)
    if os.path.dirname(real) != root:
        return _out({"ok": False, "reason": f"{args.path} is not directly inside {args.root}"})
    if os.path.exists(real):
        return _out({"ok": False, "reason": f"there is already a space called {os.path.basename(real)}"})
    os.makedirs(root, exist_ok=True)
    rc, _, err = _git("clone", "-q", args.url, real, timeout=1800)
    if rc != 0:
        shutil.rmtree(real, ignore_errors=True)
        return _out({"ok": False, "reason": err.strip()[:400] or "git clone failed"})
    target, flow = _where_from(real)
    return _out({"ok": True, "path": real, "target": target, "flow": flow})


def inspect(args) -> int:
    """What a path on this server is, as the run's user sees it."""
    path = args.path
    bare = (os.path.isfile(os.path.join(path, "HEAD")) and os.path.isdir(os.path.join(path, "objects"))
            and not os.path.exists(os.path.join(path, ".git")))
    return _out({"ok": True, "exists": os.path.exists(path), "dir": os.path.isdir(path),
                 "bare": bare, "git": os.path.exists(os.path.join(path, ".git"))})


def link(args) -> int:
    """Make a space of a folder already on this server: a link to it in the spaces folder.

    Runs in it work in the folder itself, so it is never a folder the
    program keeps for itself, and never the whole machine.
    """
    real, root = os.path.realpath(args.path), os.path.realpath(args.root)
    here = os.path.join(root, args.name)
    if real == "/" or _inside(real, root) or _inside(real, os.path.realpath(args.runs)):
        return _out({"ok": False, "reason": f"{real} cannot be a space"})
    if os.path.dirname(here) != root or os.path.lexists(here):
        return _out({"ok": False, "reason": f"there is already a space called {args.name}"})
    made = False
    if args.create and not os.path.exists(real):
        # A new project: its folder, and any folder above it, is made (D44).
        try:
            os.makedirs(real)
            made = True
        except OSError as exc:
            return _out({"ok": False,
                         "reason": f"could not make the folder {real} on the server: {exc.strerror}"})
    if not os.path.isdir(real):
        return _out({"ok": False, "reason": f"{args.path} is not a folder on the server"})
    os.makedirs(root, exist_ok=True)
    os.symlink(real, here)
    return _out({"ok": True, "path": real, "name": args.name, "made": made})


def follow(args) -> int:
    """Bring a copy of the workspace up to main, and do nothing else.

    The server's own copy is the one everything on the server reads (stage 4).
    Only a fast-forward is ever made, so nothing in that copy is merged away.

    It takes `sync.lock` in the git directory before it touches anything, so
    two of these can never run at once. That lock was shared with the
    workspace's own `bin/sync`, which fetched and pushed the same checkout on a
    30-second timer until the separate workspace was retired on 22 September
    2026; the script is gone and this is the only thing that takes the lock
    now, which is why a name that says "sync" is kept rather than invented
    again: a copy of this program from before that day is still held off by it.
    """
    repo = args.repo
    code, gitdir, err = _git("rev-parse", "--absolute-git-dir", cwd=repo)
    if code:
        return _out({"ok": False, "reason": err.strip() or "not a git repository"})
    gitdir = gitdir.strip()
    code, branch, _ = _git("symbolic-ref", "--short", "-q", "HEAD", cwd=repo)
    if code or branch.strip() != args.target:
        return _out({"ok": False, "reason": f"the copy is not on {args.target}"})
    lock = os.path.join(gitdir, "sync.lock")
    try:
        os.mkdir(lock)
    except FileExistsError:
        with contextlib.suppress(OSError):
            if time.time() - os.stat(lock).st_mtime > 300:  # left by a follow that was killed
                os.rmdir(lock)
        try:
            os.mkdir(lock)
        except OSError:
            return _out({"ok": True, "skipped": "another follow is running"})
    try:
        for busy in ("index.lock", "MERGE_HEAD", "rebase-merge", "rebase-apply"):
            if os.path.exists(os.path.join(gitdir, busy)):
                return _out({"ok": True, "skipped": f"git is busy ({busy})"})
        code, _, err = _git("fetch", "-q", "origin", args.target, cwd=repo)
        if code:
            return _out({"ok": False, "reason": err.strip()[:300]})
        kept = None
        code, ahead, _ = _git("rev-list", "--count", f"origin/{args.target}..HEAD", cwd=repo)
        if code == 0 and int(ahead.strip() or 0):
            kept, why = _keep_aside(repo, args.target)
            if not kept:
                return _out({"ok": False, "reason": why})
        else:
            code, _, err = _git("merge", "--ff-only", "-q", f"origin/{args.target}", cwd=repo)
            if code:
                return _out({"ok": False, "reason": err.strip()[:300]})
        code, sha, _ = _git("rev-parse", "HEAD", cwd=repo)
        return _out({"ok": True, "sha": sha.strip(), **({"kept": kept} if kept else {})})
    finally:
        with contextlib.suppress(OSError):
            os.rmdir(lock)


def _keep_aside(repo: str, target: str) -> tuple[dict | None, str]:
    """Commits made straight on the copy's own main: put them on a branch, and follow main.

    Nothing may commit there, but on 27 October 2026 run e9df64d0, working
    in Rouh's code, wrote step 139-06 into this copy and committed it on its
    main three times. Main moved on, a fast-forward was no longer possible,
    and the copy stopped following for eleven hours, saying so to the
    person every half hour. So the commits are kept on a branch of their
    own, ``kept/<target>-<when>-<commit>``, which is never deleted here, and
    main is moved onto the remote's with ``reset --keep``, which carries
    every uncommitted change and leaves every untracked file where it is,
    and refuses rather than overwrite one. The branch is then landed like
    any other work (``land_kept``). Returns what was kept, or why not.
    """
    _, head, _ = _git("rev-parse", "HEAD", cwd=repo)
    head = head.strip()
    _, there, _ = _git("for-each-ref", "--format=%(refname:short)", "--points-at", head,
                       "refs/heads/kept/", cwd=repo)
    branch = there.split()[0] if there.split() else \
        f"kept/{target}-{time.strftime('%Y-%m-%d-%H%M')}-{head[:8]}"
    if not there.split():
        code, _, err = _git("branch", branch, head, cwd=repo)
        if code:
            return None, f"could not keep its own commits on a branch: {err.strip()[:200]}"
    _, log, _ = _git("log", "--format=%h %s", f"origin/{target}..{head}", cwd=repo)
    commits = [line for line in log.splitlines() if line.strip()]
    code, _, err = _git("reset", "-q", "--keep", f"origin/{target}", cwd=repo)
    if code:
        return None, (f"its own {len(commits)} commit(s) are kept on {branch}, but it could not "
                      f"move onto {target} without touching a file changed there: "
                      f"{err.strip()[:200]}")
    return {"branch": branch, "sha": head, "commits": commits}, ""


def land_kept(args) -> int:
    """Land a branch ``_keep_aside`` made, through land.sh, from a checkout of its own.

    There is no run behind these commits to hand a clash back to, so a
    collision goes straight to Rouh's merge pass (``--merge``). The branch
    stays whatever happens; the checkout goes once the work is on main.
    """
    repo, branch = args.repo, args.branch
    code, sha, _ = _git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", cwd=repo)
    if code:
        return _out({"ok": False, "landed": False, "reason": f"there is no branch {branch}"})
    path = os.path.join(args.runs, f"kept-{sha.strip()[:8]}")
    if not os.path.isdir(path):
        code, _, err = _git("worktree", "add", "-q", path, branch, cwd=repo)
        if code:
            return _out({"ok": False, "landed": False,
                         "reason": f"could not check {branch} out: {err.strip()[:200]}"})
    _, base, _ = _git("merge-base", branch, f"origin/{args.target}", cwd=repo)
    got = _land_sh(argparse.Namespace(
        target=args.target, run=f"kept-{sha.strip()[:8]}", base=base.strip(),
        title=f"Commits made straight on the server's copy of {args.target}",
        land_dir=args.land_dir, leave_uncommitted=True, claude=args.claude, merge=True), path)
    got["branch"] = branch
    if got.get("landed"):
        _git("worktree", "remove", "--force", path, cwd=repo)
    return _out(got)


# -- starting things -------------------------------------------------------------


def agent(args) -> int:
    return _agent_environment.agent(args, sys.modules[__name__])


API_KEY_VAR = _agent_environment.API_KEY_VAR

BROWSER_CONFIG_VAR = _agent_mcp.BROWSER_CONFIG_VAR


def _browser_config(cwd: str, port: int) -> str:
    return _agent_mcp._browser_config(cwd, port)


def _take_api_key(path: str, cwd: str) -> tuple[str, str]:
    return _agent_environment._take_api_key(path, cwd, sys.modules[__name__])


def _run_tmp(cwd: str) -> str:
    return _agent_environment._run_tmp(cwd, sys.modules[__name__])


def shell(args) -> int:
    return _agent_environment.shell(args, sys.modules[__name__])


# -- reading a transcript -------------------------------------------------------

#: The folders an agent keeps its transcripts in, under this user's home:
#: Claude Code's projects, and Codex's sessions.
TRANSCRIPTS = (os.path.join(".claude", "projects"), os.path.join(".codex", "sessions"))
#: How long a reader that follows stays, at most. The program starts another if
#: somebody is still reading.
FOLLOW_FOR = 12 * 3600


def transcript(args) -> int:
    """Hand the program a run's transcript, line by line, as the agent writes it.

    The agent writes its transcript in this user's home, readable by this user
    only, and the program runs as another user; this is how the Read tab reads
    it (one/transcripts.py). Only an agent's own transcript is read: a
    ``.jsonl`` under ``~/.claude/projects`` or ``~/.codex/sessions``, so no
    other file of this user's can be asked for this way.

    It prints the file's complete lines from ``--from`` onwards, exactly as
    they are, and then a line of its own, ``#at <offset>``, each time it has
    caught up: where a reader should start again from. A line the agent is
    still writing waits until it is whole. ``#refused <why>`` means it will not
    read the path at all, and ``#reset`` that the file was cut back and is
    being read again from the start.

    With ``--follow`` it stays and hands on every line the agent adds, looking
    four times a second, until the program closes its input or stops reading
    what it prints.
    """
    out = sys.stdout.buffer
    home = _home()
    path = os.path.realpath(args.path)
    allowed = any(_inside(path, os.path.join(home, where)) for where in TRANSCRIPTS)
    if not allowed or not path.endswith(".jsonl"):
        out.write(b"#refused that is not a transcript an agent of this user wrote\n")
        out.flush()
        return 1
    offset = max(0, int(args.start or 0))
    # A run handed boxes: what they hold is taken out of every line before the program sees it.
    sealed = _sealed.read(args.secrets) if getattr(args, "secrets", "") else []
    pending = b""
    said = None
    fh = None
    until = time.monotonic() + FOLLOW_FOR
    try:
        while True:
            if fh is None:
                with contextlib.suppress(FileNotFoundError):
                    fh = open(path, "rb")  # noqa: SIM115 - held open while it follows
                    fh.seek(offset)
            if fh is not None:
                if os.fstat(fh.fileno()).st_size < offset:
                    offset, pending = 0, b""
                    fh.seek(0)
                    out.write(b"#reset\n")
                while True:
                    chunk = fh.read(1 << 20)
                    if not chunk:
                        break
                    offset += len(chunk)
                    pending += chunk
                    cut = pending.rfind(b"\n")
                    if cut >= 0:
                        out.write(_sealed.redact_bytes(pending[:cut + 1], sealed))
                        pending = pending[cut + 1:]
            whole = offset - len(pending)
            if whole != said:
                out.write(f"#at {whole}\n".encode())
                out.flush()
                said = whole
            if not args.follow or time.monotonic() > until:
                return 0
            ready, _, _ = select.select([sys.stdin], [], [], 0.25)
            if ready and not os.read(sys.stdin.fileno(), 4096):
                return 0
    except (BrokenPipeError, ConnectionResetError):
        return 0
    finally:
        if fh is not None:
            fh.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)

    p = sub.add_parser("worktree-add")
    p.add_argument("--repo", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--base", default="origin/main")
    p.add_argument("--runs", required=True)
    p.add_argument("--fetch", action="store_true")
    p.set_defaults(fn=worktree_add)

    p = sub.add_parser("worktree-remove")
    p.add_argument("--repo", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--branch", default="")
    p.add_argument("--runs", required=True)
    p.set_defaults(fn=worktree_remove)

    p = sub.add_parser("write")
    p.add_argument("--path", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--mode", default="600")
    p.set_defaults(fn=write)

    p = sub.add_parser("drop")
    p.add_argument("--path", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--mode", default="600")
    p.set_defaults(fn=drop)

    p = sub.add_parser("seed-trust")
    p.add_argument("--path", required=True)
    p.add_argument("--bypass", action="store_true")
    p.add_argument("--engine", default="claude")
    p.set_defaults(fn=seed_trust)

    p = sub.add_parser("follow")
    p.add_argument("--repo", required=True)
    p.add_argument("--target", default="main")
    p.set_defaults(fn=follow)

    p = sub.add_parser("land-kept")
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--target", default="main")
    p.add_argument("--land-dir", default="")
    p.add_argument("--claude", default="")
    p.set_defaults(fn=land_kept)

    p = sub.add_parser("land")
    p.add_argument("--leave-uncommitted", action="store_true")
    p.add_argument("--push-branch", default="")
    p.add_argument("--path", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--target", default="main")
    p.add_argument("--leftover-message", default="Work left uncommitted when the run stopped")
    p.add_argument("--no-push", action="store_true")
    # Passed straight through to land.sh: which run this is, what it is called,
    # what its branch was made from, and where the lock and the records live.
    p.add_argument("--run", default="")
    p.add_argument("--title", default="")
    p.add_argument("--base", default="")
    p.add_argument("--land-dir", default="")
    p.add_argument("--claude", default="")
    p.set_defaults(fn=land)

    p = sub.add_parser("status")
    p.add_argument("--path", required=True)
    p.add_argument("--target", default="main")
    p.add_argument("--also", default="")
    p.add_argument("--landed-head", default="")
    p.set_defaults(fn=status)

    p = sub.add_parser("clone")
    p.add_argument("--url", required=True)
    p.add_argument("--path", required=True)
    p.add_argument("--root", required=True)
    p.set_defaults(fn=clone)

    p = sub.add_parser("inspect")
    p.add_argument("--path", required=True)
    p.set_defaults(fn=inspect)

    p = sub.add_parser("link")
    p.add_argument("--path", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--create", action="store_true")
    p.set_defaults(fn=link)

    p = sub.add_parser("rmtree")
    p.add_argument("--path", required=True)
    p.add_argument("--runs", required=True)
    p.set_defaults(fn=rmtree)

    p = sub.add_parser("sweep-scratch")
    p.add_argument("--root", required=True)
    p.add_argument("--older-than", type=float, required=True)
    p.set_defaults(fn=sweep_scratch)

    p = sub.add_parser("agent")
    p.add_argument("--cwd", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--term", default="xterm-256color")
    p.add_argument("--binary", default="claude")
    p.add_argument("--engine", default="claude")
    #: Only a Codex run needs this: its hooks read it out of the environment.
    p.add_argument("--hook-key", default="")
    #: Only a run of Codex billed to the OpenAI API key: the file its key is
    #: in, read and deleted before the run starts. Never the key itself.
    p.add_argument("--api-key-file", default="")
    #: Only a run Rouh fills the vault's card into (the nightly feature run,
    #: `rouh/nightly_feature.py`): the port its browser opens DevTools on.
    p.add_argument("--browser-port", type=int, default=0)
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(fn=agent)

    p = sub.add_parser("shell")
    p.add_argument("--cwd", required=True)
    p.add_argument("--run", required=True)
    p.add_argument("--term", default="xterm-256color")
    p.set_defaults(fn=shell)

    p = sub.add_parser("transcript")
    p.add_argument("--path", required=True)
    p.add_argument("--from", dest="start", type=int, default=0)
    p.add_argument("--follow", action="store_true")
    #: A run handed boxes: its ``.secrets`` folder, whose contents are redacted from every line.
    p.add_argument("--secrets", default="")
    p.set_defaults(fn=transcript)

    p = sub.add_parser("secrets-put")
    p.add_argument("--cwd", required=True)
    p.add_argument("--runs", required=True)
    p.set_defaults(fn=secrets_put)

    p = sub.add_parser("secrets-read")
    p.add_argument("--cwd", required=True)
    p.add_argument("--runs", required=True)
    p.set_defaults(fn=secrets_read)

    p = sub.add_parser("secrets-shred")
    p.add_argument("--cwd", required=True)
    p.add_argument("--runs", required=True)
    p.add_argument("--scrub", action="append", default=[])
    p.set_defaults(fn=secrets_shred)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
