"""Reading the person's assistant workspace, for answers that take seconds.

The workspace is where the person's company, people, tasks and decisions are
written down: the organisation's background in ``_context/``, one summary per
task in ``_tasks.md`` (generated out of Rouh's database since 6 October 2026,
`rouh/tasklist.py`), and one record per task in that task's own
``AGENTS.md``. Since 21 September 2026 it is
``workspace/`` in Rouh's own checkout, reshaped into a tree: a task sits
under the project that owns it, at whatever depth, so the records are found by
walking that tree rather than by globbing one folder.

Two things, both read-only:

- ``search`` looks through exactly those record files for lines holding every
  word of a query, case-insensitive, and returns each with its file and line
  number. A single word behaves like ``grep -in``.
- ``read`` returns one text file from anywhere in the repository.

Refused whatever is asked: anything that resolves outside the repository
(symbolic links are followed before the check, not after), anything inside
``.git``, and anything whose name looks like a secret. The files search looks
through pass the same checks, so a key someone drops into ``_context/`` is not
searched either.

Earlier the same day this was written, asked about a colleague, Rouh grepped
an old copy of some of these files elsewhere on the server and found almost
nothing. This reads the live copy.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

#: Names never read or searched, at any depth. Matched case-insensitively
#: against every part of the path, both as asked and after links are followed.
SECRET_NAMES = (
    ".env*", "*.pem", "*.key", ".passphrase", "*.sqlite3", "*.sqlite3-*",
    "id_rsa*", "id_ed25519*", "*.p12", "*.pfx", ".netrc",
)

SEARCH_MAX_LINES = 60       # matching lines returned in all
SEARCH_MAX_PER_FILE = 10    # so one long record cannot crowd out every other file
SEARCH_MAX_CHARS = 9000
LINE_MAX_CHARS = 300
READ_MAX_CHARS = 30000
FILE_MAX_BYTES = 2_000_000  # a larger file is read only this far

_PUNCTUATION = ".,;:!?\"'()[]{}"


class Refused(ValueError):
    """A path that must not be read, with the reason in words."""


def is_secret_name(name: str) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, pattern) for pattern in SECRET_NAMES)


def _check_names(parts) -> None:
    for part in parts:
        if part == ".git":
            raise Refused("That is inside .git, git's own files, which are never read.")
        if is_secret_name(part):
            raise Refused(f"{part} is a name secrets are kept under, so it is never read.")


def resolve(root: str | os.PathLike, path: str) -> Path:
    """The file ``path`` names inside the repository at ``root``, or Refused.

    The names are checked twice: as asked, so ``.env`` is refused even where it
    is a link to something harmless, and after every link is followed, so a
    harmless name that leads to ``.passphrase`` or out of the folder is refused
    too.
    """
    base = Path(root).resolve()
    asked = str(path or "").strip()
    if not asked:
        raise Refused("No path was given.")
    _check_names(Path(asked).parts)
    candidate = Path(asked) if Path(asked).is_absolute() else base / asked
    target = candidate.resolve()
    try:
        inside = target.relative_to(base)
    except ValueError:
        raise Refused(
            f"{asked} is outside the workspace, and only the workspace is read."
        ) from None
    _check_names(inside.parts)
    return target


def _text_of(path: Path) -> str | None:
    """A file's text, or None for anything that is not text."""
    try:
        with path.open("rb") as fh:
            data = fh.read(FILE_MAX_BYTES)
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", "replace")


def read(root: str | os.PathLike, path: str, start_line: int = 1) -> str:
    """One text file, from ``start_line`` on, cut off at READ_MAX_CHARS."""
    base = Path(root).resolve()
    target = resolve(base, path)
    rel = target.relative_to(base).as_posix()
    if target.is_dir():
        raise Refused(f"{rel} is a folder. Name one file in it, or search instead.")
    if not target.is_file():
        raise Refused(f"There is no file at {rel} in the workspace.")
    text = _text_of(target)
    if text is None:
        raise Refused(f"{rel} is not a text file.")
    lines = text.splitlines()
    total = len(lines)
    try:
        start = max(1, int(start_line or 1))
    except (TypeError, ValueError):
        start = 1
    if total == 0:
        return f"{rel} is empty."
    if start > total:
        return f"{rel} has {total} lines, so there is nothing from line {start} on."

    out: list[str] = []
    used = 0
    end = start - 1
    for line in lines[start - 1:]:
        cost = len(line) + 1
        if out and used + cost > READ_MAX_CHARS:
            break
        out.append(line[:READ_MAX_CHARS])
        used += cost
        end += 1
    head = f"{rel}, lines {start}-{end} of {total}"
    if target.stat().st_size > FILE_MAX_BYTES:
        head += f" (only its first {FILE_MAX_BYTES // 1_000_000} MB are read)"
    if end < total:
        head += f". Cut off here to keep it short; call again with start_line {end + 1} to read on"
    return head + ":\n\n" + "\n".join(out)


def search_files(root: str | os.PathLike) -> list[tuple[str, Path]]:
    """The record files search looks through, as (name in the workspace, file).

    Every task's own ``AGENTS.md``, wherever the task sits. It used to be
    ``tasks/*/CLAUDE.md``, one glob of one folder, which found nothing at all
    once a task moved under the project that owns it; ``steps.task_folders``
    walks the tree for the same set and is the one place that rule is written.
    A project's own ``AGENTS.md`` is read too - the categories are projects now
    and some of them say what they hold. The file was ``CLAUDE.md`` until 26
    September 2026, and a folder that still has only that is read by that
    name (`rouh/instructions.py`).
    """
    from . import instructions, steps

    base = Path(root).resolve()
    found: list[Path] = []
    context = base / "_context"
    if context.is_dir():
        # os.walk does not follow links to folders, so a linked folder is
        # never searched; a linked file still passes through resolve() below.
        for dirpath, dirnames, filenames in os.walk(context):
            dirnames[:] = sorted(d for d in dirnames if d != ".git" and not is_secret_name(d))
            found.extend(Path(dirpath) / name for name in sorted(filenames))
    found.append(base / "_tasks.md")
    records: set[Path] = set()
    for folder in steps.task_folders(base):
        records.add(instructions.in_folder(folder))
        records.add(instructions.in_folder(folder.parent))
    found += sorted(records)

    out: list[tuple[str, Path]] = []
    for path in found:
        try:
            rel = path.relative_to(base).as_posix()
            target = resolve(base, rel)
        except (Refused, ValueError, OSError):
            continue
        if target.is_file():
            out.append((rel, target))
    return out


def search(root: str | os.PathLike, query: str) -> str:
    """Lines in the records holding every word of ``query``, with file and line."""
    words = [w.strip(_PUNCTUATION).casefold() for w in str(query or "").split()]
    words = [w for w in words if w][:8]
    phrase = " ".join(str(query or "").split())
    if not words:
        return "There was nothing to search for."

    shown: list[str] = []
    left_out: dict[str, int] = {}
    total = 0
    used = 0
    for rel, path in search_files(root):
        text = _text_of(path)
        if text is None:
            continue
        in_file = 0
        for number, line in enumerate(text.splitlines(), 1):
            folded = line.casefold()
            if not all(w in folded for w in words):
                continue
            total += 1
            in_file += 1
            clipped = " ".join(line.split())
            if len(clipped) > LINE_MAX_CHARS:
                clipped = clipped[: LINE_MAX_CHARS - 3] + "..."
            entry = f"{rel}:{number}: {clipped}"
            if (in_file > SEARCH_MAX_PER_FILE or len(shown) >= SEARCH_MAX_LINES
                    or used + len(entry) > SEARCH_MAX_CHARS):
                left_out[rel] = left_out.get(rel, 0) + 1
                continue
            shown.append(entry)
            used += len(entry) + 1

    if not total:
        return (
            f'No line in the workspace\'s records mentions "{phrase}". Searched: '
            "_context/, _tasks.md and every task's own AGENTS.md."
        )
    head = f'{total} matching line{"" if total == 1 else "s"} for "{phrase}"'
    if left_out:
        head += f", {len(shown)} shown"
    parts = [head + ":", *shown]
    if left_out:
        more = "; ".join(f"{n} more in {rel}" for rel, n in left_out.items())
        parts += ["", f"Not shown: {more}. Read a file with path to see all of it."]
    return "\n".join(parts)
