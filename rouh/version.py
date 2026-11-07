"""Which build of Rouh is running.

There is one reason this file exists: after a deploy, somebody has to be able to
look at the screen and know whether the new code is the code answering them. A
restart that quietly kept the old bundle looks exactly like a restart that
worked, and the only way to tell them apart used to be reading the log.

The version has two halves, bumped by different things:

* ``VERSION`` is written by hand, and only when the shape of the thing changes
  enough to be worth saying out loud.
* the commit is read at import, which is once per process, which is once per
  restart. Nobody has to remember to bump it and it cannot disagree with the
  code it was read from.

The commit half is the useful one: it moves on its own with every deploy, so a
number that did not change after a deploy means the deploy did not land.

The commit is read out of git's own files rather than by running git, for two
reasons. The service runs as root out of a checkout owned by another user, and
git refuses to read a repository it thinks belongs to somebody else unless that
path is listed in root's personal config - a file that is not in this repository
and that nobody would think to restore. And this runs during startup, where a
subprocess that hangs is worse than a version that is missing. Running git is
kept only as a fallback for layouts this does not understand.

`get_version()`, at the bottom, is the same question asked out loud rather than
glanced at: it adds the commit date, the branch and whether the working tree has
been edited, which are the things somebody actually says back when asked what
version is running. Those cannot be read out of git's plain files, so that half
does run git, once, behind a cache.
"""
from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime

from . import gitutil
from .config import config

log = logging.getLogger("rouh.version")

VERSION = "1.0.0"

# The checkout this package was imported from. Taken from __file__ rather than
# the working directory so it is right whoever started the process and from
# wherever.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SHORT = 7


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _resolve(base: str, path: str) -> str:
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


def _git_dir(root: str) -> str:
    """Where git keeps HEAD for `root`.

    Usually `.git/`. In a worktree `.git` is a file holding the path to a
    per-worktree directory instead, which is how the crew's worktrees look.
    """
    dot = os.path.join(root, ".git")
    if os.path.isdir(dot):
        return dot
    pointer = _read(dot)
    if pointer.startswith("gitdir:"):
        return _resolve(root, pointer[len("gitdir:"):].strip())
    return ""


def _head_sha(root: str) -> str:
    """The full commit `root` is checked out at, read from git's files."""
    gitdir = _git_dir(root)
    if not gitdir:
        return ""
    head = _read(os.path.join(gitdir, "HEAD"))
    if not head:
        return ""
    if not head.startswith("ref:"):
        return head  # detached HEAD: the commit is written out in full
    ref = head[len("ref:"):].strip()

    # HEAD is per-worktree but the branches it points at are shared, so a
    # worktree has to look in the main checkout's directory as well as its own.
    common = _read(os.path.join(gitdir, "commondir"))
    bases = [gitdir] + ([_resolve(gitdir, common)] if common else [])

    for base in bases:
        if sha := _read(os.path.join(base, *ref.split("/"))):
            return sha
    # A branch that has not moved in a while gets packed into one file with all
    # the others, and then it has no file of its own to read.
    for base in bases:
        for line in _read(os.path.join(base, "packed-refs")).splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == ref:
                return parts[0]
    return ""


def _git_sha(root: str) -> str:
    """Ask git. Only used when reading the files got nowhere."""
    try:
        # safe.directory is set (`gitutil.run`) for the same reason the files
        # are read first: as root in a checkout owned by another user, git
        # refuses to answer at all unless it is told that this path is expected.
        done = gitutil.run(root, "rev-parse", "HEAD", timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def full_revision(root: str = _ROOT) -> str:
    """The whole commit `root` is checked out at, or "" if it cannot be read.

    Never raises. No git, no repository, a repository with no commits yet, and a
    layout this does not understand all mean the same thing: there is no commit
    to show, which is not a reason to refuse to start.
    """
    sha = _head_sha(root) or _git_sha(root)
    # Only a hash ever gets past here. This ends up in a served page, and a
    # branch name or an error message would have no business being there.
    if len(sha) < _SHORT or any(c not in "0123456789abcdef" for c in sha):
        return ""
    return sha


def git_revision(root: str = _ROOT) -> str:
    """The short commit `root` is checked out at, or "" if it cannot be read."""
    return full_revision(root)[:_SHORT]


# Read once, at import. Re-reading per request would put file I/O in the path of
# a page load to learn something that cannot change while the process is alive.
REVISION = git_revision()
BUILD = f"{VERSION}+{REVISION}" if REVISION else VERSION


# --- the fuller answer ------------------------------------------------------
#
# Everything above is deliberately cheap: file reads, no subprocess, because it
# runs at import and ends up in every page load. It is also not quite enough to
# answer out loud. "0cbfe0a" tells you whether the deploy landed only if you
# already know what the last commit was; "0cbfe0a, committed 8 Sep 2026" tells
# you on its own.
#
# The commit date and the dirty flag cannot come out of git's plain files. The
# date lives inside the commit object, which is compressed and often packed,
# and whether the working tree has been edited is a comparison only git can
# make. So this half does run git, once, and keeps the answer: a spoken turn
# must not shell out three times to say one sentence, and nothing it reads can
# change while the process is alive.

UNKNOWN = "unknown"

# The answer about the deployed checkout, computed on the first call and handed
# out from here afterwards. Only that one is remembered: asking about some other
# directory is a question about that directory, and must not be answered out of
# a cache filled in by a different one.
_cached: dict | None = None


def _git(app_dir: str, *args: str) -> str | None:
    """One git command against the checkout. None means it did not work.

    None rather than an empty string because `status --porcelain` says nothing
    at all about a clean tree, and "clean" and "could not ask" have to be told
    apart.
    """
    try:
        done = gitutil.run(app_dir, *args, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("version: git %s failed: %s", " ".join(args), exc)
        return None
    if done.returncode != 0:
        log.warning("version: git %s failed: %s", " ".join(args), done.stderr.strip())
        return None
    return done.stdout.strip()


def _spoken_date(iso: str) -> str:
    """An ISO commit date as something sayable: "8 Sep 2026"."""
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    # The day is assembled by hand because the format code that prints it with
    # no leading zero is a GNU extension, and this has to be safe wherever it
    # runs.
    return f"{when.day} {when.strftime('%b')} {when.year}"


def _unknown() -> dict:
    return {
        "sha": UNKNOWN,
        "short_sha": UNKNOWN,
        "commit_date": UNKNOWN,
        "branch": UNKNOWN,
        "dirty": False,
        "human_readable": "unknown version",
    }


def _compute(app_dir: str) -> dict:
    # The sha comes from the file reader above, so this and the marker on the
    # page cannot disagree about which commit it is.
    sha = full_revision(app_dir)
    if not sha:
        return _unknown()

    commit_date = _git(app_dir, "show", "-s", "--format=%cI", "HEAD") or UNKNOWN
    branch = _git(app_dir, "rev-parse", "--abbrev-ref", "HEAD") or UNKNOWN
    # A failed status check reads as clean. Announcing local changes that may
    # not exist is worse than staying quiet about ones that do.
    dirty = bool(_git(app_dir, "status", "--porcelain"))

    short_sha = sha[:_SHORT]
    said = short_sha
    day = _spoken_date(commit_date)
    if day:
        said += f", committed {day}"
    if dirty:
        said += ", with uncommitted changes"

    return {
        "sha": sha,
        "short_sha": short_sha,
        "commit_date": commit_date,
        "branch": branch,
        "dirty": dirty,
        "human_readable": said,
    }


def get_version(app_dir: str | None = None, refresh: bool = False) -> dict:
    """The running build: sha, short_sha, commit_date, branch, dirty, human_readable.

    Reads the deployed checkout named in the config rather than `_ROOT`, because
    the question this answers is which build is live. On the server those are
    the same directory, so it agrees with `REVISION` above; in a worktree they
    do not have to, and the deployed one is the honest answer.

    A copy is returned every time, so a caller dropping it into a JSON payload
    cannot edit the cached answer for everybody else.
    """
    global _cached
    if app_dir is not None:
        # A named directory is read every time. Tests and anything asking about
        # a second checkout want the truth about that one, not whatever the
        # first caller happened to look at.
        return _compute(app_dir)
    if _cached is None or refresh:
        _cached = _compute(config.app_dir)
    return dict(_cached)
