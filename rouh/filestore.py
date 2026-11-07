"""One home for every file: where each file Rouh is handed lives, and the one list that says so.

Petar, 4 November 2026. That evening a zip he attached in a chat, "Heartbeat Redesign Test.zip",
was kept at `/data/rouh/attachments/chat-d6c834153344/d88ee51fa1af41bc/`, and Rouh handed that
path to a job (step 169-04). In the containers every Rouh runs (deploy/stack/compose.yml) a job
runs in the worker, which has no `/data` at all, so the job could not open it; nor could any job
since the move to Docker on 31 October. Copying files into a job was rejected, and so was giving
jobs a read-only view: a job must be able to change, fix, unzip and rename a file, and see the
rest of the files of the same chat or task.

So:

1. **One home per file, where its work lives.** A file of a task's chat, or uploaded to a task,
   lives in that task's folder of the store, `tasks/<task id>/`; a file of a chat with no task in
   `chats/<chat id>/`; a project's in `projects/<project id>/`. The task's folder in the
   workspace gets `files`, a link to its folder here, so the file is also in the task's own
   folder, in every checkout (`link_task_folder`). When a chat becomes a task's, its files move
   (`move_owner`). Nothing is ever copied.
2. **The same path everywhere.** The store is one folder that Rouh, its jobs, the one program's
   runs and helpers all see read and write at the identical path (`root`). In the containers that
   is `/run/one/files`, in the volume Rouh's core and the worker already both mount at
   `/run/one` (one-run, a named volume that outlives every restart), so it needs nothing changed
   on the machine; `ROUH_FILES_DIR` names another. On one machine without containers it is
   `files` in the data directory, in the group the attachments are in.
3. **One list.** `File` (rouh/models/files.py) is the only authority on where a file is. Every
   path Rouh tells a model or a job is read from it.

What is kept beside a file - the record the attachment store writes, the words read out of it,
the picture the model is shown, the original of a converted photo - is in `.rouh/<file id>/`,
not beside the file, so a task's folder holds only the person's files and what jobs made of them.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import logging
import os
import re
import shutil
import time

from .config import config

log = logging.getLogger("rouh.filestore")

#: Directories and files in the store: written so the app and every job can change them
#: (jobs run as the same user in the containers, and in the attachments group on one machine),
#: and nobody else on the machine can read them.
DIR_MODE = 0o2770
FILE_MODE = 0o660

#: What is kept beside each file, out of the owners' folders.
SIDE = ".rouh"
#: Files put in the bin, until the bin is emptied (`rouh/filebin.py`).
BIN = ".bin"
#: Earlier versions of files, by file id.
VERSIONS = ".versions"

#: The link in a task's folder of the workspace to that task's folder here.
LINK = "files"

#: What an owner's folder is called, by kind.
FOLDERS = {"chat": "chats", "task": "tasks", "project": "projects"}

_ID = re.compile(r"[^A-Za-z0-9._-]")


def root() -> str:
    """The folder every file lives in, the same path for Rouh and for every job."""
    if config.files_dir:
        return config.files_dir
    shared = os.environ.get("ROUH_WORKER_KEY_FILE", "").strip()
    if shared:
        folder = os.path.dirname(shared)
        if os.path.isdir(folder):
            return os.path.join(folder, "files")
    return os.path.join(config.data_dir, "files")


def safe_id(raw) -> str:
    return _ID.sub("", str(raw or ""))[:120].lstrip(".")


def _gid() -> int | None:
    from . import attachments

    return attachments._gid_of(config.crew_user or None, config.attachments_group) \
        if (config.crew_user or config.attachments_group) else None


def _close_up(path: str, mode: int) -> None:
    gid = _gid()
    if gid is not None:
        try:
            os.chown(path, -1, gid)
        except OSError:
            pass
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def make_dir(path: str) -> str:
    """A folder of the store and every level above it inside the store, each one closed up."""
    made = []
    while path and not os.path.isdir(path):
        made.append(path)
        path = os.path.dirname(path)
    for one in reversed(made):
        os.makedirs(one, exist_ok=True)
        _close_up(one, DIR_MODE)
    return made[0] if made else path


def inside(path: str) -> bool:
    """Whether a path is really in the store, links followed: a file a job swapped for a link
    to something of Rouh's own is not."""
    try:
        real = os.path.realpath(path)
        top = os.path.realpath(root())
    except OSError:
        return False
    return real == top or real.startswith(top + os.sep)


def folder_of(kind: str, ident: str) -> str:
    sid = safe_id(ident)
    if kind not in FOLDERS or not sid:
        raise ValueError(f"no folder for {kind} {ident!r}")
    return os.path.join(root(), FOLDERS[kind], sid)


def side_of(file_id: str) -> str:
    return os.path.join(root(), SIDE, safe_id(file_id))


def free_name(folder: str, name: str) -> str:
    """`name` in `folder`, or `name (2)`, `name (3)` ... when that is taken."""
    stem, ext = os.path.splitext(name)
    for double in (".tar.gz", ".tar.bz2", ".tar.xz"):
        if name.lower().endswith(double) and len(name) > len(double):
            stem, ext = name[:-len(double)], name[-len(double):]
    path = os.path.join(folder, name)
    n = 2
    while os.path.lexists(path):
        path = os.path.join(folder, f"{stem} ({n}){ext}")
        n += 1
    return path


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


# --- whose a file is ---------------------------------------------------------------------------


def task_of_chat(chat_id: str) -> str:
    """The task (or step) that owns this chat, or ""."""
    try:
        from .models.objects import Link

        row = Link.objects.filter(rel="owns", src_type="task", dst_type="chat",
                                  dst_id=chat_id).values_list("src_id", flat=True).first()
        return str(row or "")
    except Exception:  # noqa: BLE001 - no database is no task, and the chat keeps the file
        log.debug("could not ask which task owns %s", chat_id, exc_info=True)
        return ""


def owner_of_key(session: str) -> tuple[str, str]:
    """What the key a file is given under names: ("task", id), ("project", id) or ("chat", id).

    A chat that belongs to a task gives its files to the task, so they live where its work does.
    """
    sid = safe_id(session)
    if sid.startswith("task-") and len(sid) > 5:
        return "task", sid[5:]
    if sid.startswith("project-") and len(sid) > 8:
        return "project", sid[8:]
    task = task_of_chat(sid)
    if task:
        return "task", task
    return "chat", sid


def home_of_key(session: str) -> str:
    kind, ident = owner_of_key(session)
    return folder_of(kind, ident)


def who() -> tuple[str, str]:
    """(org_id, user_id) of the person a file is kept for: the one speaking, else the only one."""
    try:
        from . import tenancy

        person = tenancy.speaker() or tenancy.Tenancy().only_person()
        if person is not None:
            return str(person.org_id or ""), str(person.user_id or "")
    except Exception:  # noqa: BLE001 - a file is kept whoever it is for
        log.debug("could not tell whose a file is", exc_info=True)
    return "", ""


# --- the list ----------------------------------------------------------------------------------


def register(record: dict, *, source: str, owners: list[tuple[str, str]] | None = None,
             source_ref: dict | None = None, sha256: str = "") -> None:
    """Put one file the attachment store has just written on the list, with its owners."""
    from .models.files import File, FileOwner

    now = time.time()
    org, user = who()
    meta = {k: v for k, v in record.items()
            if k not in ("id", "session_id", "name", "media_type", "kind", "size", "ts", "path")}
    try:
        meta["inode"] = os.stat(record["path"]).st_ino
    except OSError:
        pass
    File.objects.update_or_create(id=record["id"], defaults={
        "org_id": org, "user_id": user, "name": record.get("name") or "file",
        "media_type": record.get("media_type") or "", "kind": record.get("kind") or "file",
        "size": int(record.get("size") or 0),
        "sha256": sha256 or _sha_or_blank(record["path"]),
        "path": record["path"], "session": record.get("session_id") or "",
        "source": source, "source_ref": source_ref or {}, "meta": meta,
        "created_at": float(record.get("ts") or now), "updated_at": now,
    })
    for kind, ident in owners or [owner_of_key(record.get("session_id") or "")]:
        FileOwner.objects.get_or_create(file_id=record["id"], kind=kind, owner_id=ident,
                                        defaults={"created_at": now})
    # The state it was given in, kept as its first version: whatever a job does to it later,
    # the original can be had back.
    try:
        keep_version(File.objects.get(id=record["id"]), by=f"given ({source})")
    except Exception:  # noqa: BLE001 - the file is kept either way
        log.exception("the first version of %s could not be kept", record["id"])


def _sha_or_blank(path: str) -> str:
    try:
        return sha256_of(path)
    except OSError:
        return ""


def record_of(row) -> dict:
    """A row as the attachment store's record: what every caller of it already reads."""
    out = dict(row.meta or {})
    out.pop("inode", None)
    out.update({"id": row.id, "session_id": row.session, "name": row.name,
                "media_type": row.media_type, "kind": row.kind, "size": row.size,
                "ts": row.created_at, "path": row.path})
    return out


def row(file_id: str):
    try:
        from .models.files import File

        return File.objects.filter(id=safe_id(file_id), deleted_at__isnull=True).first()
    except Exception:  # noqa: BLE001 - no list to ask is the old layout's answer
        log.debug("could not read the file list", exc_info=True)
        return None


def owners(file_id: str) -> list[tuple[str, str]]:
    from .models.files import FileOwner

    return list(FileOwner.objects.filter(file_id=file_id).order_by("id")
                .values_list("kind", "owner_id"))


def find(session: str, file_id: str) -> dict | None:
    """The record of one file given under `session`, or None.

    A file belongs to the key it was given under, and to every owner on its list: a file of a
    chat that has since moved to its task is still found by that chat.
    """
    got = row(file_id)
    if got is None:
        return None
    sid = safe_id(session)
    if got.session != sid:
        kind, ident = owner_of_key(sid)
        mine = set(owners(got.id))
        if (kind, ident) not in mine and ("chat", sid) not in mine:
            return None
    if not os.path.isfile(got.path) and not relocate(got):
        return None
    if not inside(got.path):
        log.warning("file %s points outside the store, at %s; not opened", got.id, got.path)
        return None
    return record_of(got)


def listing(session: str) -> list[dict]:
    """Every live file given under one key, oldest first."""
    try:
        from .models.files import File

        rows = list(File.objects.filter(session=safe_id(session), deleted_at__isnull=True)
                    .order_by("created_at"))
    except Exception:  # noqa: BLE001
        return []
    return [record_of(r) for r in rows if os.path.isfile(r.path) or relocate(r)]


def files_of(kind: str, ident: str) -> list[dict]:
    """Every live file one chat, task or project owns, oldest first."""
    from .models.files import File

    rows = File.objects.filter(owners__kind=kind, owners__owner_id=ident,
                               deleted_at__isnull=True).order_by("created_at").distinct()
    return [record_of(r) for r in rows if os.path.isfile(r.path) or relocate(r)]


def relocate(got) -> bool:
    """A file a job renamed or moved inside its owner's folder, found again by what it is.

    The list stays the authority: the new place is written into it.
    """
    inode = (got.meta or {}).get("inode")
    places = {os.path.dirname(got.path)}
    try:
        for kind, ident in owners(got.id):
            places.add(folder_of(kind, ident))
    except Exception:  # noqa: BLE001
        pass
    for place in places:
        if not os.path.isdir(place) or not inside(place):
            continue
        for top, dirs, names in os.walk(place):
            if top.count(os.sep) - place.count(os.sep) > 3:
                dirs[:] = []
                continue
            for name in names:
                path = os.path.join(top, name)
                try:
                    st = os.lstat(path)
                except OSError:
                    continue
                if inode and st.st_ino == inode or (
                        not inode and st.st_size == got.size and got.sha256
                        and sha256_of(path) == got.sha256):
                    log.info("file %s was moved to %s; the list says so now", got.id, path)
                    got.path, got.name, got.updated_at = path, name, time.time()
                    got.save(update_fields=["path", "name", "updated_at"])
                    return True
    return False


# --- moving a file to where its work is ---------------------------------------------------------


def _move(src: str, folder: str, name: str) -> str:
    make_dir(folder)
    dest = free_name(folder, name)
    try:
        os.rename(src, dest)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        # Another volume (the attachments folder of before): moved, not copied - the copy is
        # made, checked and the original taken away.
        shutil.copy2(src, dest)
        if os.path.getsize(dest) != os.path.getsize(src):
            os.unlink(dest)
            raise OSError(f"the move of {src} to {dest} came out short")
        os.unlink(src)
    _close_up(dest, FILE_MODE)
    return dest


def place(file_id: str, kind: str, ident: str, *, keep_owners: bool = True) -> dict:
    """Move one file on the list into the folder of `kind` `ident`, which becomes an owner.

    The bytes move and the list changes in the same step, so the path on the list is always
    where the file is. A file that is already there only gains the owner.
    """
    from .models.files import FileOwner

    got = row(file_id)
    if got is None:
        raise LookupError(f"There is no file {file_id} on the list.")
    if not os.path.isfile(got.path) and not relocate(got):
        raise LookupError(f"File {file_id} is on the list at {got.path}, and is not there.")
    folder = folder_of(kind, ident)
    if os.path.dirname(os.path.realpath(got.path)) != os.path.realpath(folder):
        got.path = _move(got.path, folder, os.path.basename(got.path))
        got.name = os.path.basename(got.path)
        meta = dict(got.meta or {})
        try:
            meta["inode"] = os.stat(got.path).st_ino
        except OSError:
            pass
        got.meta = meta
    got.updated_at = time.time()
    got.save()
    if not keep_owners:
        FileOwner.objects.filter(file_id=got.id).exclude(kind=kind, owner_id=ident).delete()
    FileOwner.objects.get_or_create(file_id=got.id, kind=kind, owner_id=ident,
                                    defaults={"created_at": time.time()})
    _write_side_record(got)
    if kind == "task":
        link_task_folder(ident)
    return record_of(got)


def move_owner(from_kind: str, from_id: str, to_kind: str, to_id: str) -> int:
    """Every file one owner has moves to another: a chat that became a task's, or was filed
    under one. Returns how many moved."""
    from .models.files import File, FileOwner

    ids = list(File.objects.filter(owners__kind=from_kind, owners__owner_id=from_id,
                                   deleted_at__isnull=True).values_list("id", flat=True))
    moved = 0
    for one in ids:
        try:
            place(one, to_kind, to_id)
            FileOwner.objects.filter(file_id=one, kind=from_kind, owner_id=from_id).delete()
            # The chat it was given in still finds it (`find`): the key it was given under is
            # kept on the row.
            moved += 1
        except (LookupError, OSError):
            log.exception("file %s could not move from %s %s to %s %s", one, from_kind,
                          from_id, to_kind, to_id)
    return moved


def _write_side_record(got) -> None:
    """The record beside the file, kept level with the list."""
    side = side_of(got.id)
    if not os.path.isdir(side):
        return
    path = os.path.join(side, "meta.json")
    data = json.dumps(record_of(got)).encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


# --- the task's folder in the workspace ---------------------------------------------------------


def link_task_folder(task_id: str) -> str:
    """`files` in the task's folder of the workspace, a link to its folder in the store.

    So the file is in the task's own folder too, in Rouh's checkout and in every job's, and
    git keeps only the link. A `files` that is already something else is left alone.
    Returns the link's path, or "" when there is none.
    """
    ws = config.assistant_repo
    if not ws:
        return ""
    try:
        from .models.objects import Task

        folder = Task.objects.filter(id=task_id).values_list("folder", flat=True).first()
    except Exception:  # noqa: BLE001
        return ""
    if not folder:
        return ""
    task_dir = os.path.join(ws, folder)
    if not os.path.isdir(task_dir):
        return ""
    target = folder_of("task", task_id)
    make_dir(target)
    link = os.path.join(task_dir, LINK)
    if os.path.islink(link):
        if os.readlink(link) == target:
            return link
        os.unlink(link)
    elif os.path.lexists(link):
        log.info("%s is already there and is not Rouh's link; the task's files stay at %s",
                 link, target)
        return ""
    os.symlink(target, link)
    try:
        from . import saving

        saving.poke()
    except Exception:  # noqa: BLE001
        pass
    return link


def is_files_link(path: str) -> bool:
    """Whether `path` is one of Rouh's links from a task's folder into the store."""
    if os.path.basename(path) != LINK or not os.path.islink(path):
        return False
    target = os.readlink(path)
    tasks = os.path.join(root(), FOLDERS["task"]) + os.sep
    return target.startswith(tasks)


def describe(record: dict) -> str:
    """One line for a model or a job: where the file is, which is the same for every job."""
    return record.get("path") or ""


# --- the bin -----------------------------------------------------------------------------------


def to_bin(file_id: str, *, by: str = "") -> dict | None:
    """Put one file in the bin: out of its owner's folder, kept whole until the bin is emptied.

    Nothing Rouh or a job does deletes a file for good at once; `rouh/filebin.py` empties the bin
    on the schedule in Settings.
    """
    got = row(file_id)
    if got is None:
        return None
    was = got.path
    keep = os.path.join(root(), BIN, safe_id(got.id))
    make_dir(keep)
    if os.path.isfile(was):
        got.path = _move(was, keep, os.path.basename(was))
    side = side_of(got.id)
    if os.path.isdir(side):
        try:
            os.replace(side, os.path.join(keep, SIDE))
        except OSError:
            log.warning("what is kept beside %s stayed at %s", got.id, side)
    got.meta = {**(got.meta or {}), "was_at": was}
    got.deleted_at = time.time()
    got.deleted_by = by[:120]
    got.updated_at = time.time()
    got.save()
    return record_of(got)


# --- files kept before the list ----------------------------------------------------------------


def adopt(legacy_root: str, session: str, att_id: str, *,
          to: tuple[str, str] | None = None, source: str = "") -> dict:
    """Move one file kept before the list (`{data dir}/attachments/{session}/{id}/`) into its
    home, and put it on the list.

    `to` is the owner it goes to; left out, the one its key names (a chat's task when the chat
    has one). What was kept beside it goes to `.rouh/<id>/`. The old path is left as a link to
    the new one, so anything still holding it opens the file while the change settles.
    """
    sid, aid = safe_id(session), safe_id(att_id)
    folder = os.path.join(legacy_root, sid, aid)
    meta_path = os.path.join(folder, "meta.json")
    with open(meta_path, encoding="utf-8") as fh:
        record = json.load(fh)
    if not isinstance(record, dict) or record.get("id") != aid:
        raise LookupError(f"{meta_path} does not describe file {aid}")
    old = str(record.get("path") or "")
    if os.path.islink(old):
        got = row(aid)
        if got is not None:
            return record_of(got)
    if os.path.dirname(os.path.realpath(old)) != os.path.realpath(folder) or not os.path.isfile(old):
        raise LookupError(f"file {aid} is not in its folder {folder}")
    kind, ident = to or owner_of_key(sid)
    name = os.path.basename(old)
    if name == "_meta.json":
        name = "meta.json"
    new = _move(old, folder_of(kind, ident), name)
    side = side_of(aid)
    make_dir(side)
    for extra in os.listdir(folder):
        if extra in ("meta.json",):
            continue
        src = os.path.join(folder, extra)
        if os.path.isfile(src) and not os.path.islink(src):
            _move(src, side, extra)
    record.update({"path": new, "name": os.path.basename(new), "session_id": sid})
    data = json.dumps(record).encode("utf-8")
    fd = os.open(os.path.join(side, "meta.json"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    from . import attachments

    ref = {"chat": sid} if not sid.startswith(("task-", "project-")) else {}
    register(record, source=source or attachments._source_of(sid, record.get("made")),
             owners=[(kind, ident)], source_ref={**ref, "was_at": old})
    try:
        os.symlink(new, old)
    except OSError:
        log.info("could not leave a link at %s", old)
    if kind == "task":
        link_task_folder(ident)
    return record_of(row(aid))


def legacy_folders(legacy_root: str):
    """Every (session, id) still kept the old way."""
    try:
        sessions = sorted(os.listdir(legacy_root))
    except OSError:
        return
    for sid in sessions:
        here = os.path.join(legacy_root, sid)
        if not os.path.isdir(here):
            continue
        for aid in sorted(os.listdir(here)):
            meta = os.path.join(here, aid, "meta.json")
            if os.path.isfile(meta):
                yield sid, aid


def find_legacy(legacy_root: str, att_id: str) -> str:
    """The key a file kept the old way is under, found by its id alone, or ""."""
    aid = safe_id(att_id)
    try:
        sessions = os.listdir(legacy_root)
    except OSError:
        return ""
    for sid in sessions:
        if os.path.isfile(os.path.join(legacy_root, sid, aid, "meta.json")):
            return sid
    return ""


def legacy_root() -> str:
    return os.path.join(config.data_dir, "attachments")


def follow_chat(chat_id: str, task_id: str) -> int:
    """A chat that became a task's, or was filed under one: every file given in it moves into
    the task's folder, and the list changes in the same step. Nothing is copied.

    Files of the chat still kept the old way are put on the list on the way. Returns how many
    moved.
    """
    from django.db.models import Q

    from .models.files import File, FileOwner

    chat = safe_id(chat_id)
    if not chat or not task_id:
        return 0
    moved = 0
    for sid, aid in list(legacy_folders(legacy_root())):
        if sid == chat and row(aid) is None:
            try:
                adopt(legacy_root(), sid, aid, to=("task", task_id))
                moved += 1
            except (LookupError, OSError, ValueError):
                log.exception("file %s of chat %s could not be moved to its task", aid, chat)
    ids = list(File.objects.filter(Q(session=chat) | Q(owners__kind="chat", owners__owner_id=chat),
                                   deleted_at__isnull=True).values_list("id", flat=True).distinct())
    for one in ids:
        try:
            place(one, "task", task_id)
        except (LookupError, OSError):
            log.exception("file %s could not follow chat %s to task %s", one, chat, task_id)
            continue
        FileOwner.objects.filter(file_id=one, kind="chat", owner_id=chat).delete()
        if File.objects.filter(id=one, session=chat).exists():
            # The task the chat belonged to before, if any, lets its files go with it.
            FileOwner.objects.filter(file_id=one, kind="task").exclude(owner_id=task_id).delete()
        moved += 1
    if moved:
        log.info("%d files of chat %s moved to task %s", moved, chat, task_id)
    return moved


# --- the same content once -----------------------------------------------------------------------


def same_content(sha256: str, size: int):
    """A live file on the list with exactly these bytes, or None."""
    if not sha256:
        return None
    try:
        from .models.files import File

        for got in File.objects.filter(sha256=sha256, size=size, deleted_at__isnull=True) \
                .order_by("created_at"):
            if not (os.path.isfile(got.path) and inside(got.path)):
                continue
            if os.path.getsize(got.path) == size and sha256_of(got.path) == sha256:
                return got
            # Changed since it was put on the list (a job worked on it): the list catches up.
            got.size = os.path.getsize(got.path)
            got.sha256 = sha256_of(got.path)
            got.save(update_fields=["size", "sha256"])
    except Exception:  # noqa: BLE001
        log.debug("could not look for the same content", exc_info=True)
    return None


def add_owner(file_id: str, kind: str, ident: str) -> None:
    from .models.files import FileOwner

    FileOwner.objects.get_or_create(file_id=file_id, kind=kind, owner_id=ident,
                                    defaults={"created_at": time.time()})


def task_of_run(run_id: str) -> str:
    """The task (or step) a run's work belongs to, walking up who owns what, or ""."""
    if not run_id:
        return ""
    try:
        from .models.objects import Link

        kind, ident = "run", str(run_id)
        for _ in range(6):
            up = Link.objects.filter(rel="owns", dst_type=kind, dst_id=ident) \
                .values_list("src_type", "src_id").first()
            if up is None:
                return ""
            kind, ident = up
            if kind == "task":
                return str(ident)
    except Exception:  # noqa: BLE001
        log.debug("could not tell whose run %s is", run_id, exc_info=True)
    return ""


# --- moving everything kept the old way, and emptying the bin -------------------------------------

#: Written in the store once every file kept the old way has been moved.
MIGRATED = "migrated"
_started = False


def migrate(*, limit: int = 0) -> dict:
    """Move every file still kept the old way into its chat's, task's or project's folder and
    put it on the list. Moved, never copied, with a link left at the old path. Returns counts."""
    moved, failed = 0, 0
    for sid, aid in list(legacy_folders(legacy_root())):
        if limit and moved >= limit:
            break
        folder = os.path.join(legacy_root(), sid, aid)
        try:
            with open(os.path.join(folder, "meta.json"), encoding="utf-8") as fh:
                was = str((json.load(fh) or {}).get("path") or "")
        except (OSError, ValueError):
            continue
        if os.path.islink(was) and row(aid) is not None:
            continue
        try:
            adopt(legacy_root(), sid, aid, source="migrated" if not sid.startswith(
                ("task-", "project-")) else "")
            moved += 1
        except Exception:  # noqa: BLE001 - one file that will not move leaves the rest to go
            failed += 1
            log.exception("file %s of %s could not be moved into its home", aid, sid)
    return {"moved": moved, "failed": failed}


def empty_bin(days: float | None = None) -> int:
    """Files in the bin longer than the setting (`config.files_bin_days`) are deleted for good,
    with their row. Returns how many."""
    from .models.files import File

    keep = (days if days is not None else config.files_bin_days) * 86400
    gone = 0
    for got in File.objects.filter(deleted_at__isnull=False, deleted_at__lt=time.time() - keep):
        place = os.path.join(root(), BIN, safe_id(got.id))
        if os.path.isdir(place) and inside(place):
            shutil.rmtree(place, ignore_errors=True)
        got.delete()
        gone += 1
    if gone:
        log.info("the bin was emptied of %d files kept longer than %s days", gone,
                 keep / 86400)
    return gone


def _keep_up() -> None:
    from . import dbwork

    time.sleep(30)
    marker = os.path.join(root(), SIDE, MIGRATED)
    last = 0.0
    while True:
        try:
            if not os.path.exists(marker) and os.path.isdir(legacy_root()):
                done = migrate()
                log.info("files kept the old way moved into their homes: %s", done)
                if not done["failed"]:
                    make_dir(os.path.dirname(marker))
                    with open(marker, "w", encoding="utf-8") as fh:
                        fh.write(json.dumps({**done, "at": time.time()}))
            if time.time() - last >= 6 * 3600:
                empty_bin()
                said = sync_r2()
                if said.get("sent") or said.get("full"):
                    log.info("files copied to R2: %s", said)
                last = time.time()
            changes = check_changes()
            if changes:
                log.info("%d files changed on disk; each new state is kept as a version", changes)
        except Exception:  # noqa: BLE001 - tried again on the next round
            log.exception("the files could not be kept up")
        finally:
            dbwork.release()
        time.sleep(600)


def start() -> None:
    """The thread that moves files kept the old way once and empties the bin every few hours."""
    global _started
    if _started:
        return
    _started = True
    import threading

    threading.Thread(target=_keep_up, name="files-keep-up", daemon=True).start()


def let_go(file_id: str, session: str) -> bool:
    """The owner `session` names lets go of a file other owners still have. True when others
    keep it (and it stays where it is); False when this was its only owner."""
    from .models.files import FileOwner

    sid = safe_id(session)
    mine = {owner_of_key(sid), ("chat", sid)}
    have = set(owners(file_id))
    if not (have - mine):
        return False
    for kind, ident in mine:
        FileOwner.objects.filter(file_id=file_id, kind=kind, owner_id=ident).delete()
    return True


# --- versions, and the copy in R2 ----------------------------------------------------------------

#: Kinds that never belong in git, whatever their size: kept on disk, with a copy in R2.
NEVER_GIT_TYPES = ("video/", "audio/")
NEVER_GIT_EXT = (".sqlite", ".sqlite3", ".db", ".iso", ".img", ".dmg", ".vmdk", ".qcow2", ".vdi",
                 ".vhd", ".vhdx")
MB = 1024 * 1024


def large(got) -> bool:
    """Past the cut-off in config (`files_git_max_mb`, about 10 MB), or a kind that never belongs
    in git: such a file's earlier versions are kept in R2 rather than on this disk."""
    return (int(got.size or 0) > config.files_git_max_mb * MB
            or str(got.media_type or "").startswith(NEVER_GIT_TYPES)
            or os.path.splitext(str(got.name or "").lower())[1] in NEVER_GIT_EXT)


def keep_version(got, *, by: str = "") -> bool:
    """Keep the file as it is now as a version, once per content. A small file's bytes are copied
    into `.versions/<id>/`; a large one's are kept by its copy in R2 (`sync_r2`). True when a new
    version was written down."""
    from django.db.models import Max

    from .models.files import FileVersion

    if not os.path.isfile(got.path):
        return False
    sha = got.sha256 or sha256_of(got.path)
    if FileVersion.objects.filter(file_id=got.id, sha256=sha).exists():
        return False
    n = (FileVersion.objects.filter(file_id=got.id).aggregate(m=Max("number"))["m"] or 0) + 1
    kept_at = ""
    if not large(got):
        folder = os.path.join(root(), VERSIONS, safe_id(got.id))
        make_dir(folder)
        kept_at = os.path.join(folder, f"{n}-{sha[:12]}{os.path.splitext(got.name)[1]}")
        shutil.copyfile(got.path, kept_at)
        _close_up(kept_at, 0o440)
    FileVersion.objects.create(file_id=got.id, number=n, sha256=sha, size=os.path.getsize(got.path),
                               kept_at=kept_at, made_at=time.time(), by=by[:120])
    return True


def check_changes() -> int:
    """Every live file whose bytes changed since the list last looked (a job worked on it): its
    fingerprint and size are brought up to date, and the new state kept as a version. The state it
    was given in was kept when it was put on the list, so the original is always there."""
    from .models.files import File

    changed = 0
    for got in File.objects.filter(deleted_at__isnull=True).iterator():
        try:
            st = os.stat(got.path)
        except OSError:
            if not relocate(got):
                continue
            st = os.stat(got.path)
        meta = dict(got.meta or {})
        if meta.get("mtime") == int(st.st_mtime) and got.size == st.st_size:
            continue
        sha = sha256_of(got.path)
        meta["mtime"] = int(st.st_mtime)
        if sha != got.sha256 or got.size != st.st_size:
            got.sha256, got.size = sha, st.st_size
            if got.storage == "disk+r2":
                got.storage = "disk"          # the copy in R2 is of the state before
            got.meta, got.updated_at = meta, time.time()
            got.save()
            keep_version(got, by="a change on disk")
            changed += 1
        else:
            got.meta = meta
            got.save(update_fields=["meta"])
    return changed


def _r2_skipped_silos() -> set[str]:
    return {s.strip() for s in os.environ.get("ROUH_FILES_R2_SKIP_SILOS", "").split(",") if s.strip()}


def sync_r2() -> dict:
    """Large files, and every version of them, copied to R2 encrypted (age, for the off-site
    copy's recipient or passphrase, `rouh/offsite.py`), as the shared copy and backup. Work stays
    on this disk. Files labelled with a silo in ROUH_FILES_R2_SKIP_SILOS are not sent. Held under
    ROUH_FILES_R2_MAX_GB (8, inside Cloudflare's free 10 GB): past it nothing more is sent and it
    is said, rather than spending."""
    from . import agefile, offsite
    from .models.files import File, FileVersion

    try:
        s = offsite.settings()
    except offsite.NotSetUp as exc:
        return {"on": False, "why": str(exc)}
    most = float(os.environ.get("ROUH_FILES_R2_MAX_GB") or 8) * 1024 * MB
    sent_bytes = sum(int(v.size or 0) for v in FileVersion.objects.exclude(r2_key=""))
    skip = _r2_skipped_silos()
    s3 = offsite.client(s)
    out = {"on": True, "sent": 0, "skipped": 0, "full": False}
    work = offsite.work_dir()
    os.makedirs(work, exist_ok=True)
    for got in File.objects.filter(deleted_at__isnull=True, storage="disk").iterator():
        if not large(got) or not os.path.isfile(got.path):
            continue
        if skip and skip & set(got.silos or []):
            out["skipped"] += 1
            continue
        if sent_bytes + int(got.size or 0) > most:
            out["full"] = True
            log.warning("R2 holds %.1f GB of files; %s is not sent, to stay inside the free tier",
                        sent_bytes / 1024 / MB, got.name)
            break
        keep_version(got, by="the copy in R2")
        key = f"{s['prefix']}files/{got.sha256}.age"
        sealed = os.path.join(work, f"{got.id}.age")
        try:
            with open(got.path, "rb") as src, open(sealed, "wb") as dst:
                agefile.encrypt(src, dst, recipients=[s["recipient"]] if s["recipient"] else (),
                                passphrase=s["passphrase"])
            s3.upload_file(sealed, s["bucket"], key)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(sealed)
        got.r2_key, got.storage, got.updated_at = key, "disk+r2", time.time()
        got.save(update_fields=["r2_key", "storage", "updated_at"])
        FileVersion.objects.filter(file_id=got.id, sha256=got.sha256).update(r2_key=key)
        sent_bytes += int(got.size or 0)
        out["sent"] += 1
    return out


def versions(file_id: str) -> list[dict]:
    from .models.files import FileVersion

    return [{"number": v.number, "sha256": v.sha256, "size": v.size, "on_disk": bool(v.kept_at),
             "in_r2": bool(v.r2_key), "made_at": v.made_at, "by": v.by}
            for v in FileVersion.objects.filter(file_id=safe_id(file_id)).order_by("number")]


def restore(file_id: str, number: int, *, by: str = "") -> dict:
    """Put an earlier version back where the file is. The state it replaces is kept as a version
    first, so a restore can itself be undone."""
    from .models.files import FileVersion

    got = row(file_id)
    if got is None:
        raise LookupError(f"There is no file {file_id} on the list.")
    v = FileVersion.objects.filter(file_id=got.id, number=int(number)).first()
    if v is None:
        raise LookupError(f"File {file_id} has no version {number}.")
    if not v.kept_at or not os.path.isfile(v.kept_at):
        raise LookupError(f"Version {number} of {got.name} is kept only in R2 ({v.r2_key}); it is "
                          "fetched with the off-site copy's private key, which is not on this machine.")
    if os.path.isfile(got.path):
        got.sha256 = sha256_of(got.path)
        keep_version(got, by=f"before version {number} was put back")
    shutil.copyfile(v.kept_at, got.path)
    _close_up(got.path, FILE_MODE)
    got.sha256, got.size, got.updated_at = v.sha256, v.size, time.time()
    got.meta = {**(got.meta or {}), "mtime": int(os.stat(got.path).st_mtime)}
    got.save()
    return record_of(got)


def from_bin(file_id: str) -> dict:
    """A file taken back out of the bin, to where it was."""
    from .models.files import File

    got = File.objects.filter(id=safe_id(file_id), deleted_at__isnull=False).first()
    if got is None:
        raise LookupError(f"File {file_id} is not in the bin.")
    was = str((got.meta or {}).get("was_at") or "")
    folder = os.path.dirname(was) if was else folder_of(*owners(got.id)[0])
    got.path = _move(got.path, folder, os.path.basename(was or got.path))
    side = os.path.join(root(), BIN, safe_id(got.id), SIDE)
    if os.path.isdir(side) and not os.path.exists(side_of(got.id)):
        make_dir(os.path.dirname(side_of(got.id)))
        os.replace(side, side_of(got.id))
    got.deleted_at, got.deleted_by, got.updated_at = None, "", time.time()
    got.save()
    return record_of(got)
