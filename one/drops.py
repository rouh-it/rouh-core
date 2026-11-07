"""A file dropped on a run's terminal, and where it lands.

Claude Code in a terminal turns a file's path pasted at its prompt into an
attachment, and shows it as ``[Image #1]``. So a screenshot dropped on a run's
terminal in a browser never travels down that terminal as bytes: it is written
into a folder the run can read, and its whole path is put in at the run's
prompt as one paste, with no Enter, so the person can add words before sending
it. A paste and not keystrokes: Claude Code attaches the picture only when the
path arrives as a paste, and typed key by key it stays a path on the screen
(measured against Claude Code 2.1.263, 16 September).

Where it lands is ``drops`` inside the run's own folder, which is ``.one``
inside its checkout. That folder already holds the run's brief and its hooks'
key, and git is already told to ignore all of it
(``documents._hide_own_files``), so a dropped screenshot never reaches main
with the run's work. It is inside the run's working directory, so both
``.one/drops/shot.png`` and the whole path find it. And a run working in a
folder the person added as it is (D43) keeps its own folder elsewhere, under
the runs folder, so nothing of ours is written into that person's folder.

What may be dropped is what a chat box takes: pictures, and the documents a
person reads. Anything else is refused by name, so the person is told why.
The names and the joining live here, in one place, so a chat upload can use
the same rules.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Any, Iterable, Sequence

#: The folder a run's dropped files go in, inside the run's own folder.
FOLDER = "drops"

#: The extensions taken, by the type a browser gives a file. A file whose type
#: the browser does not know (it sends application/octet-stream) is taken on
#: its own extension instead.
KINDS: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
    "application/json": ".json",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}

#: Every extension taken, including the spellings of the same kind that a
#: person's own files carry.
EXTENSIONS = frozenset(KINDS.values()) | {".jpeg", ".markdown"}

#: Said whenever a file is refused, so the answer names what would work.
TAKEN = ("png, jpg, gif and webp pictures, and pdf, txt, md, csv, json, docx "
         "and xlsx files, up to 20 MB each")

#: The most one file may be: the same as a chat box takes.
MOST_BYTES = 20 * 1024 * 1024
#: The most files one drop may carry at once.
MOST_FILES = 10

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MORE_DASHES = re.compile(r"-{2,}")


class DropRefused(ValueError):
    """A file that will not be taken, said in words a person can act on."""


def extension(name: str, content_type: str = "") -> str:
    """The extension the file is saved with: its own when that is one we take.

    Its own comes first, because it is the one the person sees: a browser
    calls a .md file text/plain, and saving it as .txt would rename their
    file for them.
    """
    ext = os.path.splitext((name or "").strip())[1].lower()
    if ext in EXTENSIONS:
        return ext
    by_type = KINDS.get((content_type or "").split(";")[0].strip().lower())
    if by_type:
        return by_type
    return ""


def safe_name(name: str, ext: str) -> str:
    """The file's own name with nothing in it that a folder or a shell reads.

    Anything that is not a letter, a digit, a dot, a dash or an underscore
    becomes a dash, so no name can climb out of the folder it goes in or mean
    something to a shell. The extension is the one :func:`extension` worked out.
    """
    stem = os.path.basename((name or "").replace("\\", "/")).strip()
    stem = _MORE_DASHES.sub("-", _UNSAFE.sub("-", os.path.splitext(stem)[0])).strip("-._")[:60]
    return (stem or "drop") + ext


def folder_for(run: dict[str, Any]) -> str:
    """Where that run's dropped files go. Refused when it has no folder yet."""
    own = str(run.get("own") or "").rstrip("/")
    if not own and run.get("cwd"):
        own = str(run["cwd"]).rstrip("/") + "/.one"
    if not own:
        raise DropRefused("that run has no folder of its own yet, so there is nowhere "
                          "to put a file; try again once it has started")
    return f"{own}/{FOLDER}"


def check(name: str, content_type: str, size: int) -> str:
    """The extension to save this file with, or a refusal saying why not."""
    called = (name or "").strip() or "that file"
    if size <= 0:
        raise DropRefused(f"{called} is empty")
    if size > MOST_BYTES:
        raise DropRefused(f"{called} is {size / 1_000_000:.1f} MB, and the most one file "
                          f"may be is 20 MB")
    ext = extension(name, content_type)
    if not ext:
        raise DropRefused(f"{called} is not a kind a run takes. It takes {TAKEN}.")
    return ext


def too_many(count: int) -> None:
    if count > MOST_FILES:
        raise DropRefused(f"{count} files at once is more than the {MOST_FILES} a drop takes")
    if count <= 0:
        raise DropRefused("that drop carried no file")


def quote(path: str) -> str:
    """A path as it is typed at a prompt: quoted only when it needs to be."""
    return shlex.quote(path)


def typed(paths: Sequence[str] | Iterable[str]) -> str:
    """What is put at the run's prompt for these files, as one paste.

    One space between the paths, and one at the end so the person's next word
    does not stick to the last path. No Enter: they send it themselves.
    """
    return " ".join(quote(p) for p in paths) + " "
