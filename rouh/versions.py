"""Reading a commit out of a checkout, once, for both version marks.

Two services are deployed out of this one repository, from two different
checkouts, and each has a mark of its own in the top bar:

* **rouh** - the Rouh server itself, the systemd unit ``rouh``, deployed
  from ``/var/www/rouh/app``. Its mark is `rouh_version.py`.
* **one** - the one program, the systemd unit ``one``, deployed from
  ``/srv/one/app``. Its mark is `one_version.py`.

Both marks ask the same two questions - which commit is this service running,
and which commit is waiting for it - and the second question is the same piece
of work either way: open a checkout and read the commit ``origin/main`` is at.
That work is here, written once, so the two marks cannot drift apart in how they
read a repository.

What must never happen again is the thing this file was split out of. The top
bar used to hold a single "Running now / Available" pair, and it compared the one
program's running commit against the newest commit in *Rouh's* checkout. Those
are two programs in two checkouts, so the two commits were never commits of the
same thing and could never agree: every deploy of Rouh moved the second number
and the panel then announced an update for a program that had not changed at all.
Each mark now reads both of its halves out of one checkout - the one its own
service is deployed from.

The comparison is the commit and only the commit. A version number is written by
hand and a fix that forgot to bump it is invisible, which is exactly the failure
these marks exist to catch; two commits either are the same commit or they are
not, and nothing can be forgotten. The version a person says out loud is still
on the screen, in Settings.

The one thing looked at past the commit is which files differ. This repository
holds the person's workspace as well as the code, and a commit that moves only
``workspace/`` is moved onto without restarting either service, so the service
goes on answering from the older commit with nothing left to deploy. Two
commits like that are the same code, and the mark says so (`only_content`).
"""
from __future__ import annotations

import logging
import subprocess

from . import gitutil

log = logging.getLogger("rouh.versions")

#: The refs to try, in order, for "the commit waiting for this service".
#: ``origin/main`` first, because that is what a deploy fetches and
#: fast-forwards onto. ``main`` next, for a checkout with no remote, and then
#: ``HEAD`` for one standing off a branch: on such a machine what it is standing
#: on is the whole of what a deploy could take.
REFS = ("origin/main", "main", "HEAD")

#: How long a mark gets before the page is sent without it. A page load must
#: never wait on a socket or on git, and a mark that is missing for one
#: connection costs nothing. Each mark is held to this on its own and the two
#: are read at the same time, so one that cannot be read never delays the other.
SECONDS = 4.0

#: How much of a commit is shown. Seven characters is what git itself abbreviates
#: to and what a person compares by eye.
SHORT = 7


def git(where: str, *args: str) -> str:
    """One git command against the checkout. "" means it did not work.

    ``safe.directory`` is set because Rouh runs as root out of a checkout
    owned by another user, and git refuses to answer at all unless it is told
    that this path is expected.
    """
    return _git(where, *args) or ""


def _git(where: str, *args: str) -> str | None:
    """`git`, for a caller to whom "" is an answer: None is what did not work."""
    if not (where or "").strip():
        return None
    try:
        done = gitutil.run(where, *args, timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("versions: git %s in %s failed: %s", " ".join(args), where, exc)
        return None
    return done.stdout if done.returncode == 0 else None


def short(sha: str) -> str:
    """A commit as it is shown, or "" for anything that is not one.

    Only a hash ever gets past here. These end up in a served page, and a branch
    name or an error message would have no business being there.
    """
    sha = (sha or "").strip()
    if len(sha) < SHORT or any(c not in "0123456789abcdef" for c in sha):
        return ""
    return sha[:SHORT]


def head_commit(where: str) -> str:
    """The commit a checkout is standing on, or "" if it cannot be read."""
    return short(git(where, "rev-parse", "HEAD"))


def available(where: str) -> dict[str, str]:
    """The commit waiting in that checkout, and the ref it was read from.

    The ref is carried so a person reading the panel knows which of `REFS`
    answered: "origin/main" is the usual one and means a fetch has happened,
    and anything else is a machine set up differently.
    """
    for ref in REFS:
        if commit := short(git(where, "rev-parse", ref)):
            return {"commit": commit, "ref": ref}
    return {"commit": "", "ref": ""}


def content_paths() -> tuple[str, ...]:
    """What in this repository is content rather than code: ``workspace/``.

    Read from the setting `land.sh` and `update-all.sh` read,
    ``ROUH_CONTENT_PATHS``, so a mark can never call a service behind for a
    commit those two moved onto without restarting it.
    """
    from .config import config

    return tuple(p for p in (config.content_paths or "").split() if p)


def only_content(where: str, running: str, ready: str,
                 paths: tuple[str, ...] | None = None) -> int:
    """How many commits ``ready`` is ahead of ``running`` when nothing
    between the two is code, and 0 when anything is or when it cannot be told.

    Since the assistant workspace was merged in at ``workspace/``, main moves
    many times a day with the person's tasks, notes and pages, and neither
    service runs any of it. A deploy of such a commit moves the files and
    restarts nothing (`land.sh`, "the content guard"), so the process keeps
    answering from the last commit that was code. Comparing commits alone then
    called every service behind, with a Deploy button that had nothing to
    deploy, almost all the time.

    It fails towards "behind", every way it can: a running commit that is not
    an ancestor of the waiting one, a checkout that does not have one of them,
    git not answering, or one single path outside ``paths`` that differs. Both
    sides of a rename are counted, so moving a file out of ``rouh/`` into
    ``workspace/`` is a change to code.
    """
    paths = content_paths() if paths is None else tuple(p for p in paths if p)
    running, ready = short(running), short(ready)
    if not paths or not running or not ready or running == ready:
        return 0
    # Left is what the running commit has that the waiting one has not, right
    # is how far the waiting one is ahead. Anything on the left means main no
    # longer holds what is running, which is a deploy whatever the files say.
    counts = (_git(where, "rev-list", "--left-right", "--count",
                   f"{running}...{ready}") or "").split()
    if len(counts) != 2 or not all(c.isdigit() for c in counts):
        return 0
    behind, ahead = int(counts[0]), int(counts[1])
    if behind or not ahead:
        return 0
    changed = _git(where, "diff", "--no-renames", "--name-only", "-z",
                   running, ready, "--")
    if changed is None:
        return 0
    for path in changed.split("\0"):
        if path and not path.startswith(paths):
            return 0
    return ahead


def compare(now: dict[str, str] | None, ready: dict[str, str], service: str,
            where: str = "") -> dict:
    """The two commits, the service they are about, and the word the page acts on.

    ``state`` is that word:

    ``update``   the waiting commit changes code the service is not running,
                 so a deploy is outstanding.
    ``same``     the same commit, or one that is newer only in content
                 (`only_content`). The mark says it and nothing else.
    ``off``      the service did not answer, so there is nothing to compare.
    ``unknown``  one of the two commits could not be read.

    ``where`` is the checkout both commits were read out of, and it is what
    lets a commit that moved only ``workspace/`` count as current. When it is
    newer only in content, ``available`` names the running commit, because
    that is the newest code there is, and ``content`` carries what main is
    really at: ``{commit, commits, paths}``. Without ``where`` two different
    commits are an update, which is what they always were.
    """
    if now is None:
        return {"service": service, "state": "off", "running": None, "available": ready}
    here, there = (now.get("commit") or "").strip(), (ready.get("commit") or "").strip()
    if not here or not there:
        state = "unknown"
    elif here == there:
        state = "same"
    elif where and (ahead := only_content(where, here, there)):
        return {"service": service, "state": "same", "running": now,
                "available": {**ready, "commit": here},
                "content": {"commit": there, "commits": ahead,
                            "paths": list(content_paths())}}
    else:
        state = "update"
    return {"service": service, "state": state, "running": now, "available": ready}
