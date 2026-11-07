"""Which version of the program is running, and which commit it was built from.

Two halves, and they answer different questions.

``one.__version__`` is the number a person says out loud: ``MAJOR.MINOR.PATCH``,
written by hand in ``one/__init__.py`` and moved by the rule in ``one/README.md``
- patch for a fix, minor for a new feature, major for a break. It is what the
program answers when asked what it is, in the health check and in the hello.

``COMMIT`` is read at import, which is once per process, which is once per
restart. Nobody has to remember to bump it and it cannot disagree with the code
it was read from, and that is why it rather than the number above is what the
chip in Rouh's top bar compares: a version somebody forgot to move would hide
exactly the failure that chip is for. It is also what turns "1.0.0" into
something you can go and look at, because a version repeated across two commits
says nothing about which of them is running.

The commit is read out of git's own files rather than by running git, for the
same two reasons Rouh reads it that way (see ``rouh/version.py``). The
service runs out of a checkout owned by another user, and git refuses to read a
repository it thinks belongs to somebody else unless the path is listed in a
personal config file that is not in this repository. And this runs during
startup, where a subprocess that hangs is worse than a commit that is missing.

This file is deliberately a copy of the same few lines in ``rouh/version.py``
rather than a shared import. Rouh and this program are two services, deployed
from two checkouts, restarted on two schedules, with two sets of Python
packages; each one has to be able to say what it is without the other being
installed. Fifty lines of pure function is a cheaper price than that coupling.
"""
from __future__ import annotations

import os

from . import __version__

#: The checkout this package was imported from. Taken from ``__file__`` rather
#: than the working directory so it is right whoever started the process.
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

    Usually ``.git/``. In a worktree ``.git`` is a file holding the path to a
    per-worktree directory instead, which is how every run's checkout looks.
    """
    dot = os.path.join(root, ".git")
    if os.path.isdir(dot):
        return dot
    pointer = _read(dot)
    if pointer.startswith("gitdir:"):
        return _resolve(root, pointer[len("gitdir:"):].strip())
    return ""


def _head_sha(root: str) -> str:
    """The commit `root` is checked out at, read from git's plain files."""
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


def full_commit(root: str = _ROOT) -> str:
    """The whole commit `root` is checked out at, or "" if it cannot be read.

    Never raises. No git, no repository, a repository with no commits yet and a
    layout this does not understand all mean the same thing: there is no commit
    to show, which is not a reason to refuse to start.
    """
    sha = _head_sha(root)
    # Only a hash ever gets past here. This ends up in a served page, and a
    # branch name or an error message would have no business being there.
    if len(sha) < _SHORT or any(c not in "0123456789abcdef" for c in sha):
        return ""
    return sha


def commit(root: str = _ROOT) -> str:
    """The short commit `root` is checked out at, or "" if it cannot be read."""
    return full_commit(root)[:_SHORT]


# Read once, at import. Re-reading per request would put file I/O in the path of
# a health check to learn something that cannot change while the process is alive.
COMMIT = commit()

#: Version and commit together, e.g. ``1.0.0+0cbfe0a``.
BUILD = f"{__version__}+{COMMIT}" if COMMIT else __version__


def describe() -> dict[str, str]:
    """What the program says about itself when asked: the same three fields
    everywhere, so the health check, the hello and the list entry cannot drift
    apart."""
    return {"version": __version__, "commit": COMMIT, "build": BUILD}
