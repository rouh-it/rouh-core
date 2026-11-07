"""Which git repository holds the person's workspace, and where in it.

The workspace is wherever the installation's setting says (`ROUH_WORKSPACE`,
`rouh/config.py`), and it is a git repository of its own: on the server
`/var/www/rouh/workspace`, a checkout of the person's own private repository,
beside Rouh's code and never inside it (21 October 2026). Until that day it was
`workspace/` inside Rouh's code repository, and every git question about it was
asked of that repository with `workspace/` in front of every path.

Nothing that saves, numbers or reads the history of the workspace assumes
either any more. It asks here: the repository's own top folder, and the path
of the workspace inside it, which is "" when the workspace is the whole
repository. So the same code is right for a workspace of its own, for a copy a
test world stands up, and for a workspace that is still a folder of a bigger
repository, and the answer comes from git rather than from a name written down.
"""
from __future__ import annotations

import os
import posixpath
from functools import lru_cache

from . import gitutil


@lru_cache(maxsize=32)
def locate(root: str) -> tuple[str, str]:
    """The top of the repository that holds `root`, and `root`'s path inside it.

    The path is "" when `root` is the top itself, and uses forward slashes with
    no trailing one otherwise (`workspace`). A folder no repository holds is
    its own top, with nothing in front of its paths.
    """
    root = os.path.realpath(root or "")
    if not root or not os.path.isdir(root):
        return root, ""
    try:
        done = gitutil.run(root, "rev-parse", "--show-toplevel", "--show-prefix", timeout=30)
    except (OSError, ValueError):
        return root, ""
    if done.returncode != 0:
        return root, ""
    lines = done.stdout.splitlines()
    top = os.path.realpath(lines[0].strip()) if lines else root
    prefix = (lines[1].strip() if len(lines) > 1 else "").strip("/")
    return top, prefix


def top(root: str) -> str:
    return locate(root)[0]


def prefix(root: str) -> str:
    return locate(root)[1]


def path(prefix_: str, *parts: str) -> str:
    """A path in the repository, from the workspace's prefix and a path in the workspace."""
    return posixpath.join(prefix_, *parts) if prefix_ else posixpath.join(*parts)


def spec(prefix_: str) -> str:
    """The pathspec that means the whole workspace: its folder, or the whole repository."""
    return prefix_ or "."


def inside(prefix_: str, repo_path: str) -> str:
    """A path in the repository as a path in the workspace."""
    if prefix_ and repo_path.startswith(prefix_ + "/"):
        return repo_path[len(prefix_) + 1:]
    return repo_path


# --- what a run is told --------------------------------------------------------

#: How a run in a checkout of Rouh's code is told to reach the workspace, when
#: the workspace is a repository of its own. `{space}` is the checkout runs of
#: the workspace are made from (`config.workspace_space`).
CODE_RUN_NOTE = (
    "The person's workspace is not in this checkout: it is a repository of its own. "
    "Make a checkout of it beside this one - `git -C {space} fetch -q origin main && "
    "git -C {space} worktree add -b <your branch>-workspace \"$PWD-workspace\" origin/main` - "
    "and every path below written `<workspace>/...` is in that checkout. Commit the "
    "workspace's files there, never here, and land them with `./land.sh --path "
    "\"$PWD-workspace\"` from this checkout, which moves the live workspace onto them; "
    "say what it said.")


def run_prefix() -> str:
    """The workspace's path inside a run's checkout of the repository that holds it:
    "" when the workspace is that whole repository, as it is since 21 October 2026,
    else its folder (`workspace`)."""
    from .config import config

    return prefix(config.assistant_repo) if config.assistant_repo else ""


def in_run(folder: str = "") -> str:
    """A path in the workspace as a run working in a checkout of the workspace writes it."""
    pre = run_prefix()
    if not folder:
        return f"{pre}/" if pre else ""
    return path(pre, folder)


def for_code_run(folder: str = "") -> str:
    """A path in the workspace as a run in a checkout of Rouh's code writes it: in its
    own checkout while the workspace is a folder of the code, else in the workspace
    checkout `code_run_note` tells it to make."""
    pre = run_prefix()
    if pre:
        return path(pre, folder) if folder else f"{pre}/"
    return f"<workspace>/{folder}" if folder else "<workspace>/"


def code_run_note() -> str:
    """What a run in a checkout of Rouh's code is told about the workspace, or "" while the
    workspace is a folder of the code."""
    from .config import config

    if run_prefix():
        return ""
    return CODE_RUN_NOTE.format(space=config.workspace_space)
