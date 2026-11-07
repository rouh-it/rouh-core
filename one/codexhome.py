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
