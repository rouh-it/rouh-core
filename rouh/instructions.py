"""What an object's own instruction file is called, in one place.

Every task and project folder of the workspace carries one file of standing
instructions - where the work stands, what was decided, how to carry on - and
the repository itself carries one at its root. Until 26 September 2026 each was
a `CLAUDE.md`, the name Claude Code reads. Petar, that day: "Please replace all
Claude.md files ... to AGENTS.md or whatever the standard is for OpenAI.
Anthropic now supports this and we want to be vendor agnostic for our
instruction files." So each is an `AGENTS.md` now, the name OpenAI's Codex and
the other agents read, and which Claude Code reads too since 2.1.277 whenever
a folder and the folders above it hold no `CLAUDE.md` (checked on this machine
against 2.1.280 and 2.1.283: the root file, a task's own file when a file in it
is opened, and `@` imports inside it are all loaded).

A `CLAUDE.md` is still read where a folder has nothing else, because a job
started before the rename, or a copy that has not caught up with it, can still
write one. It is never written by Rouh any more.
"""
from __future__ import annotations

from pathlib import Path

#: The name every instruction file has now.
NAME = "AGENTS.md"

#: The name it had until 26 September 2026, read where there is nothing newer.
OLD_NAME = "CLAUDE.md"

#: Both, the one written first.
NAMES = (NAME, OLD_NAME)


def is_instructions(name: str) -> bool:
    """Whether a file name is an instruction file, in any capitalisation."""
    return str(name or "").upper() in {n.upper() for n in NAMES}


def in_folder(folder) -> Path:
    """The instruction file of one folder: AGENTS.md, or CLAUDE.md if that is
    all the folder has. AGENTS.md when it has neither, which is the one to
    write."""
    here = Path(str(folder))
    for name in NAMES:
        path = here / name
        if path.is_file():
            return path
    return here / NAME
