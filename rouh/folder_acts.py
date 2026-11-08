"""What the three dots on a folder inside a task do: a new folder in it, files uploaded into it,
the folder or one of its items renamed, or taken away.

Petar, 8 November 2026 (fr_b89a4b1770d4), on the `scans` folder of a task: "The folder of a task
is missing the context menu with three dots that has the standard meaningful options like rename,
delete, make new folder, upload etc". So a folder read on a task's page (`objectindex.build_doc`)
has three dots beside its name, and every line of its listing has its own
(`objectindex_panels._folder_listing`); each press is handed up to Rouh (`folderpage.js`,
`taskFolderAct` in cards.js) and done here.

Everything here is a plain working folder or file inside one object's folder, and nothing more:
``rel`` is the object Rouh framed (it has an `.object.json`), ``doc`` a path inside it, with no
part empty, starting with a dot or an underscore, or a name secrets are kept under, and where it
resolves to still inside that folder. A folder that holds an object anywhere inside it - a task or
a step - is never renamed or deleted from here: that is the object's own three dots, which keep
Rouh's rows and the folders together (`rouh/owning.py`, `rouh/moving.py`). The object's own notes
(`AGENTS.md`, `CLAUDE.md`, `step.md`) are left alone for the same reason.

What changed is handed to the save (`saving.touched`), so it reaches the workspace's main and a
job working from main sees it, as a page Ask AI changed does.
"""
from __future__ import annotations

import logging
import os
import shutil
import unicodedata
from pathlib import Path

from . import workspace

log = logging.getLogger("rouh.folder_acts")

#: An object's own folder is one with this file in it (`objecttree`).
SIDECAR = ".object.json"
#: An object's own notes, which only its own page changes.
NOTES = {"agents.md", "claude.md", "step.md"}
#: The biggest file put into a folder. The workspace is a git repository, and a file much bigger
#: than this does not belong in one (GitHub refuses one over 100 MB).
MOST_BYTES = 50 * 1024 * 1024
#: The longest name a folder or a file is given here.
LONGEST = 120


class Refused(ValueError):
    """What cannot be done, in words the person reads."""


def _human(n: int) -> str:
    from . import attachments

    return attachments.human_size(n)


def _base(root, rel: str) -> Path:
    """The object's own folder, or Refused."""
    parts = [p for p in str(rel or "").split("/") if p]
    if not parts or any(p in (".", "..") or p.startswith(".") for p in parts):
        raise Refused("That is not a task's folder.")
    base = (Path(str(root)) / "/".join(parts)).resolve()
    try:
        base.relative_to(Path(str(root)).resolve())
    except ValueError:
        raise Refused("That is not a task's folder.") from None
    if not (base / SIDECAR).is_file():
        raise Refused("That is not a task's folder.")
    return base


def _inside(root, rel: str, doc: str) -> tuple[Path, Path]:
    """The object's folder and the existing folder or file ``doc`` names in it, or Refused."""
    base = _base(root, rel)
    name = str(doc or "")
    parts = name.split("/")
    if (not name or "\\" in name or "\x00" in name
            or any(not p or p.startswith((".", "_")) or workspace.is_secret_name(p) for p in parts)):
        raise Refused(f"{name or 'Nothing'} is not a working folder or file of this task.")
    path = base / name
    if path.is_symlink() or not path.exists():
        raise Refused(f"There is no {parts[-1]} here any more.")
    if base not in path.resolve().parents:
        raise Refused(f"{parts[-1]} is not inside this task.")
    return base, path


def clean_name(raw: str) -> str:
    """A name the person typed, as a folder or a file may be called, or Refused."""
    name = unicodedata.normalize("NFC", " ".join(str(raw or "").split()))
    if not name:
        raise Refused("A name cannot be empty.")
    if len(name) > LONGEST:
        raise Refused(f"A name can be at most {LONGEST} characters.")
    if "/" in name or "\\" in name or any(unicodedata.category(c).startswith("C") for c in name):
        raise Refused("A name cannot have a slash in it.")
    if name in (".", "..") or name.startswith((".", "_")):
        raise Refused("A name cannot start with a dot or an underscore: it would be hidden.")
    if workspace.is_secret_name(name):
        raise Refused(f"{name} is a name secrets are kept under, so it is not used here.")
    if name.lower() in NOTES:
        raise Refused(f"{name} is the name of a task's own notes.")
    return name


def _holds_object(path: Path) -> bool:
    if not path.is_dir():
        return False
    for _dirpath, dirnames, filenames in os.walk(path):
        if SIDECAR in filenames:
            return True
        dirnames[:] = [d for d in dirnames if d != ".git"]
    return False


def _guard_item(path: Path) -> None:
    """Refused for what is not this menu's to rename or take away."""
    if path.is_file() and path.name.lower() in NOTES:
        raise Refused(f"{path.name} is the task's own notes, and stays.")
    if _holds_object(path):
        raise Refused(f"{path.name} holds a task or a step. Use its own three dots to move or "
                      "delete it.")


def _rel_of(root, path: Path) -> str:
    return path.resolve().relative_to(Path(str(root)).resolve()).as_posix()


def _saved(root, *paths: Path) -> None:
    from . import saving

    saving.touched(*(_rel_of(root, p) for p in paths))


def _doc_of(base: Path, path: Path) -> str:
    return path.relative_to(base).as_posix()


def make_folder(root, rel: str, doc: str, name: str) -> dict:
    """A new, empty folder called ``name`` inside the folder ``doc``."""
    base, here = _inside(root, rel, doc)
    if not here.is_dir():
        raise Refused(f"{here.name} is a file, and a folder goes inside a folder.")
    called = clean_name(name)
    made = here / called
    if made.exists():
        raise Refused(f"There is already something called {called} in {here.name}.")
    made.mkdir()
    # Git keeps no empty folder, so the new one holds a file nobody sees until something is in it
    # (`_listed` hides a name that starts with a dot).
    (made / ".gitkeep").write_bytes(b"")
    _saved(root, made)
    log.info("made the folder %s in %s", called, _rel_of(root, here))
    return {"ok": True, "doc": _doc_of(base, made), "name": called}


def upload(root, rel: str, doc: str, filename: str, data: bytes) -> dict:
    """One file put into the folder ``doc``, under its own name made safe; a name already taken
    gets a number, as a browser's downloads do, so nothing there is written over."""
    from . import attachments

    base, here = _inside(root, rel, doc)
    if not here.is_dir():
        raise Refused(f"{here.name} is a file, and files are uploaded into a folder.")
    if len(data) > MOST_BYTES:
        raise Refused(f"{attachments.safe_name(filename) or 'That file'} is "
                      f"{_human(len(data))}, and a file put into a task's folder can be at most "
                      f"{_human(MOST_BYTES)}.")
    called = attachments.safe_name(filename).lstrip("._") or "file"
    try:
        called = clean_name(called)
    except Refused:
        called = "file"
    stem, ext = os.path.splitext(called)
    target, n = here / called, 1
    while target.exists() or target.is_symlink():
        n += 1
        target = here / f"{stem} ({n}){ext}"
    target.write_bytes(data)
    keep = here / ".gitkeep"
    if keep.is_file():
        keep.unlink()
    _saved(root, here)
    log.info("put %s (%s) into %s", target.name, _human(len(data)), _rel_of(root, here))
    return {"ok": True, "doc": _doc_of(base, target), "name": target.name}


def rename(root, rel: str, doc: str, name: str) -> dict:
    """The folder or file ``doc`` called ``name``, where it is."""
    base, path = _inside(root, rel, doc)
    _guard_item(path)
    called = clean_name(name)
    if called == path.name:
        return {"ok": True, "doc": _doc_of(base, path), "name": called}
    target = path.parent / called
    # Only the case of a name changed is the same entry on a disk that ignores case.
    if target.exists() and called.lower() != path.name.lower():
        raise Refused(f"There is already something called {called} here.")
    old = _rel_of(root, path)
    os.rename(path, target)
    from . import saving

    saving.touched(old, _rel_of(root, target))
    log.info("renamed %s to %s", old, called)
    return {"ok": True, "doc": _doc_of(base, target), "name": called}


def delete(root, rel: str, doc: str) -> dict:
    """The folder ``doc``, with everything in it, or the file ``doc``, taken away. Kept in the
    workspace's history, where a job can bring it back."""
    base, path = _inside(root, rel, doc)
    _guard_item(path)
    old = _rel_of(root, path)
    parent = path.parent
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    from . import saving

    saving.touched(old)
    log.info("took %s away", old)
    up = "" if parent == base else _doc_of(base, parent)
    return {"ok": True, "doc": up, "name": path.name}


def act(root, rel: str, doc: str, what: str, name: str = "") -> dict:
    """One press of the menu: ``what`` is new_folder, rename or delete."""
    if what == "new_folder":
        return make_folder(root, rel, doc, name)
    if what == "rename":
        return rename(root, rel, doc, name)
    if what == "delete":
        return delete(root, rel, doc)
    raise Refused("That cannot be done to a folder from here.")
