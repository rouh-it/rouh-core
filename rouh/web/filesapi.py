"""The list of files from a job, a run or a terminal on this machine: `rouh-files`' door.

`/internal/files` answers only a caller on this machine, or a worker showing the key Rouh gave it
(`from_this_machine`), the way `/internal/task` does.

GET ``?id=<file id>``                 one file: its record, its owners and the path it is at.
GET ``?task=<ref>`` or ``?chat=<id>``  every live file a task (a step too) or a chat owns, and the
                                       task's folder in the store.
POST ``{"action": "place", "id", "task" | "chat"}``  move one file into that task's or chat's
                                       folder; a file kept before the list is put on it first.
POST ``{"action": "add", "path", "task" | "chat"}``  put a file a job made on the list. The path
                                       must already be in the store (`rouh-files add` moves it
                                       there from the job's checkout first, since Rouh cannot see
                                       a job's checkout).
POST ``{"action": "bin", "id"}``       put one file in the bin (`filestore.to_bin`).

Every path answered is the path of the file in the store, which is the same for Rouh and every job
(`rouh/filestore.py`).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from rouh import filestore, taskrecord

from .common import answer, body_of, from_this_machine, only

log = logging.getLogger(__name__)


class Refused(ValueError):
    pass


def _task(ref: str):
    row = taskrecord.find(taskrecord._store(), ref)
    if row is None:
        raise Refused(f"Rouh has no task {ref}.")
    return row


def _owner(said: dict) -> tuple[str, str, str]:
    """(kind, id, label) from {"task": ref} or {"chat": id}."""
    if said.get("task"):
        row = _task(str(said["task"]))
        return "task", row.id, row.folder or row.id
    if said.get("chat"):
        chat = filestore.safe_id(said["chat"])
        if not chat:
            raise Refused("That is not a chat's id.")
        task = filestore.task_of_chat(chat)
        if task:
            return "task", task, f"the task of chat {chat}"
        return "chat", chat, f"chat {chat}"
    raise Refused("Say which task (task=58 or 58-03) or which chat (chat=<id>).")


def _legacy_root() -> str:
    from rouh.config import config

    return os.path.join(config.data_dir, "attachments")


def _one(file_id: str) -> dict:
    got = filestore.row(file_id)
    if got is None:
        raise Refused(f"There is no file {file_id} on the list.")
    record = filestore.find(got.session, got.id)
    if record is None:
        raise Refused(f"File {file_id} is on the list, and is not where the list says.")
    return {**record, "owners": [{"kind": k, "id": i} for k, i in filestore.owners(got.id)],
            "sha256": got.sha256, "source": got.source, "storage": got.storage,
            "versions": filestore.versions(got.id)}


def _list(said: dict) -> dict:
    kind, ident, label = _owner(said)
    return {"owner": {"kind": kind, "id": ident, "label": label},
            "folder": filestore.folder_of(kind, ident),
            "files": filestore.files_of(kind, ident)}


def _place(said: dict, run: str) -> dict:
    file_id = filestore.safe_id(said.get("id"))
    if not file_id:
        raise Refused("Say which file, by its id.")
    kind, ident, label = _owner(said)
    if filestore.row(file_id) is None:
        session = filestore.find_legacy(_legacy_root(), file_id)
        if not session:
            raise Refused(f"There is no file {file_id}, on the list or kept the old way.")
        record = filestore.adopt(_legacy_root(), session, file_id, to=(kind, ident))
    else:
        record = filestore.place(file_id, kind, ident)
    log.info("%s placed file %s in %s: %s", run or "this machine", file_id, label, record["path"])
    return {"file": record, "did": f"{record['name']} is in {label}, at {record['path']}"}


def _add(said: dict, run: str) -> dict:
    from rouh import attachments

    path = str(said.get("path") or "")
    if not os.path.isabs(path) or not os.path.isfile(path) or not filestore.inside(path):
        raise Refused(f"{path or 'That'} is not a file in the store ({filestore.root()}). Move it "
                      "into the task's folder there first; rouh-files add does that.")
    kind, ident, label = _owner(said)
    folder = filestore.folder_of(kind, ident)
    if os.path.dirname(os.path.realpath(path)) != os.path.realpath(folder):
        raise Refused(f"{path} is not in {label}'s folder, {folder}.")
    for r in filestore.files_of(kind, ident):
        if os.path.realpath(r["path"]) == os.path.realpath(path):
            return {"file": r, "did": f"{r['name']} was already on the list"}
    with open(path, "rb") as fh:
        head = fh.read(attachments.HEAD_BYTES)
    name = os.path.basename(path)
    _ext, media, kind_of = attachments.classify(name, head)
    from rouh.objectindex import task_files_key

    record = {"id": uuid.uuid4().hex[:16],
              "session_id": task_files_key(ident) if kind == "task" else
              (f"project-{ident}" if kind == "project" else ident),
              "name": name, "media_type": media, "kind": kind_of,
              "size": os.path.getsize(path), "ts": time.time(), "path": path}
    source = str(said.get("source") or "job")
    if source not in ("job", "gene_therapy", "email", "slack", "telegram", "chat"):
        source = "job"
    filestore.register(record, source=source, owners=[(kind, ident)],
                       source_ref={"run": run} if run else {})
    log.info("%s added %s to %s", run or "this machine", path, label)
    return {"file": record, "did": f"{name} is on the list, in {label}"}


@csrf_exempt
@only("GET", "POST")
async def internal_files(request: HttpRequest):
    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."},
                      status=403)
    try:
        if request.method == "GET":
            said = {k: request.GET.get(k) for k in ("id", "task", "chat") if request.GET.get(k)}
            if said.get("id"):
                got = await asyncio.to_thread(_one, said["id"])
                return answer({"ok": True, "file": got})
            got = await asyncio.to_thread(_list, said)
            return answer({"ok": True, **got})
        body = body_of(request)
        run = str(body.get("run") or "")[:80]
        action = str(body.get("action") or "")
        if action == "place":
            done = await asyncio.to_thread(_place, body, run)
        elif action == "add":
            done = await asyncio.to_thread(_add, body, run)
        elif action == "bin":
            got = await asyncio.to_thread(
                filestore.to_bin, str(body.get("id") or ""), by=f"run {run}" if run else "this machine")
            if got is None:
                raise Refused("There is no such file on the list.")
            done = {"file": got, "did": f"{got['name']} is in the bin"}
        elif action == "restore":
            got = await asyncio.to_thread(filestore.restore, str(body.get("id") or ""),
                                          int(body.get("version") or 0), by=f"run {run}")
            done = {"file": got, "did": f"version {body.get('version')} of {got['name']} is back"}
        elif action == "unbin":
            got = await asyncio.to_thread(filestore.from_bin, str(body.get("id") or ""))
            done = {"file": got, "did": f"{got['name']} is out of the bin, at {got['path']}"}
        else:
            raise Refused("The action is place, add, bin, unbin or restore.")
    except ValueError as exc:  # Refused, and a job's file that is a program (AttachmentError)
        return answer({"ok": False, "error": str(exc)}, status=400)
    except (LookupError, OSError) as exc:
        log.exception("a file could not be handled")
        return answer({"ok": False, "error": str(exc)}, status=400)
    return answer({"ok": True, **done})
