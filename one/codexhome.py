"""Where Codex keeps its sign-in: the one rule, for everything in this program that starts Codex.

Codex keeps its ChatGPT sign-in in ``$CODEX_HOME/auth.json``, and ``CODEX_HOME`` is
``~/.codex`` unless the environment says otherwise. Nothing here sets it: every place that
starts Codex - a run of the one program (``asuser.py agent``), the nightly refactoring run,
which is one of those runs, Codex runs started from Rouh, and the sign-in page
(``codex_signin.py``) - runs as the same user with the same home, so they all read the one
folder this returns.

In the containers (``deploy/stack/compose.yml``) that is ``/home/rouh/.codex`` in the worker,
and ``/home/rouh`` is the ``worker-home`` volume, which a rebuilt or redeployed worker mounts
again unchanged: a sign-in made once is kept until somebody signs out. Until 31 October 2026
Codex was signed in on the old server, in a home that did not come with the move.

Since 10 November 2026 a sign-in through Anatomy Connections is also copied into the home of
the user runs work as, when that is another user (``run_homes`` and ``spread``), so the account
signed in is the one every run uses; in the containers there is no other home to copy to.

``agent_trust._codex_home`` is the same rule for ``asuser.py``, which loads its helpers by
path and so cannot import this module; the two must say the same thing.
"""
from __future__ import annotations

import os
from pathlib import Path


def folder(home: str | None = None) -> str:
    """Codex's folder for the user whose home this is, this process's own when none is given."""
    own = str(Path.home())
    if (home is None or os.path.normpath(home) == os.path.normpath(own)) and os.environ.get("CODEX_HOME"):
        return os.environ["CODEX_HOME"]
    return os.path.join(home or own, ".codex")


def auth_file(home: str | None = None) -> str:
    return os.path.join(folder(home), "auth.json")


def run_homes(settings) -> list[str]:
    """The homes a run reads Codex's sign-in from, other than this process's own.

    In the containers every run works as the worker's own user, so this is empty and the one
    ``auth.json`` the sign-in writes is the one every run reads. Where runs work as another user
    (``ONE_RUN_AS``, on a server), that user's home is here too.
    """
    import pwd

    user = getattr(settings, "run_as", "") if settings is not None else ""
    if not user:
        return []
    try:
        home = pwd.getpwnam(user).pw_dir
    except KeyError:
        return []
    return [] if os.path.normpath(folder(home)) == os.path.normpath(folder()) else [home]


def spread(homes: list[str], *, remove: bool = False) -> None:
    """Put this process's sign-in into each of those homes, or take it out of them.

    A new sign-in replaces whatever login was there; a sign-out removes it, so no run is
    left on an older account. A home this process may not write is left alone, and never
    read: the file is copied byte for byte and its contents are never looked at or logged.
    """
    import contextlib
    import shutil

    source = auth_file()
    for home in homes:
        target = auth_file(home)
        if not os.access(os.path.dirname(target) if os.path.isdir(os.path.dirname(target)) else home, os.W_OK):
            continue
        with contextlib.suppress(OSError):
            if remove or not os.path.exists(source):
                os.unlink(target)
                continue
            os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
            tmp = target + ".new"
            shutil.copyfile(source, tmp)
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
