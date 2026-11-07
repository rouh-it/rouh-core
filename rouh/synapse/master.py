"""Synapse Master: the one dataset Rouh itself reads and writes, for each person.

Petar, 4 October 2026, by voice: "Let's duplicate the people set, call it Synapse Master and let's
ingest all tasks into it. And hook it up to Rouh. Rouh needs to have the tools to operate it and
use it." So:

- **Its own people.** The first Master was a copy of the person's people set, made that night; the
  people set is gone since, and `make` now makes an empty one with only its owner in it. It is marked
  the person's master (`synapse.dataset.master`, one per person, migration 0079) and keeps its own
  people, who are Rouh's contacts (`contacts.py`).
- **Every task in it.** `sync_tasks` stores each of Rouh's tasks (the `task` rows, archived and done
  ones too) as one item of kind task: its number, title, status, project, its summary (both the
  row's, which is the only place they are kept, and what `_tasks.md` is generated from), the
  step's ask and outcome from its meta, and its notes (`AGENTS.md`, then every other .md in its folder), keyed by the
  task's id, readable by its owner.
  A task whose text has not changed is left alone; one that changed is stored again, which is an
  edit (its old version is kept and its links checked again). The worker runs it every ten minutes
  (`worker`), so new tasks and new notes reach Master by themselves.
- **Whatever is inside a task** (Petar, the same night: "By all tasks I mean all md files, chats and
  html files and whatever is inside"). `sync_files` stores every file in the workspace as an item of
  its own, attached to the task whose folder holds it (the deepest task folder): text
  files as they are, pages, PDFs and office files read by Rouh's own extractor, pictures and other
  binaries as a file described by its name, type and size. `sync_chats` stores every chat, the whole
  conversation, attached to the task that owns it (or the one the chat it was forked from belongs to),
  and `sync_cards` every card a task or a chat owns. A file is read again only when its size or time
  changed; one that is gone is deleted from Master.
- **And every chat that is in no task** (Petar, 5 October 2026: "Include chats that don't belong to
  tasks please"): General, each email's chat, a chat started on its own, and their cards. A chat longer
  than `SPLIT_AT` is kept one item a day (the installation's own day), so General's thousands of messages are each found
  by their date and nothing in the middle is cut out; a day is stored again only when it grew.
- **iCloud's contacts are its people** (Petar, the same night: "Since all of the contacts are in the
  synapse, can you make sure that the iCloud sync syncs with them instead now", and then "I need it to be
  both ways ... Rouh's contacts should not exist"). The iCloud sync writes each card onto its person here,
  and an edit of a contact here is written to iCloud (`contacts.py`). Rouh keeps no copy of its own.
- **Rouh's tools.** The Synapse chat's tools work in every chat of Rouh's, on Master unless a
  dataset is named (`chat.py`); in the Synapse chat they still act on the dataset on the screen.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from . import datasets, db, people

log = logging.getLogger("rouh.synapse.master")

NAME = "Synapse Master"
SOURCE = "rouh-task"
#: How often the worker brings tasks in again (seconds).
SYNC_EVERY = 600.0
#: A task's notes, at most this many characters (the biggest task's notes are about 60,000).
NOTES_MAX = 120_000


def of(org_id: str, user_id: str) -> dict | None:
    """The person's master dataset, or None."""
    if not db.value("SELECT to_regclass('synapse.dataset') IS NOT NULL"):
        return None
    if not db.value("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'synapse' "
                    "AND table_name = 'dataset' AND column_name = 'master')"):
        return None
    return db.row("SELECT * FROM synapse.dataset WHERE org_id = %s AND user_id = %s AND master",
                  (str(org_id), str(user_id)))


def make(org_id: str, user_id: str, name: str = NAME) -> dict:
    """The person's master dataset, made empty with its owner in it the first time (the iCloud sync and the
    task sync fill it); the existing one after that. Returns `{"dataset": row, "made": bool, "people": n}`.
    The first one, on 4 October 2026, was a copy of the people set, which is gone since."""
    got = of(org_id, user_id)
    if got:
        return {"dataset": got, "made": False, "people": int(db.value(
            "SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND kind = 'person'", (got["id"],)) or 0)}
    ds = db.row(
        "INSERT INTO synapse.dataset (org_id, user_id, name, about, owner_name, role, master) "
        "VALUES (%s, %s, %s, %s, %s, 'data', true) RETURNING *",
        (str(org_id), str(user_id), name, "The memory Rouh reads and writes: the person's contacts, kept two ways "
         "with iCloud, and every task, kept in step with them.", _owner_name(user_id)))
    people.me(ds)
    log.info("Synapse Master made for %s/%s", org_id, user_id)
    return {"dataset": datasets.by_id(ds["id"]), "made": True, "people": 1}


def _owner_name(user_id: str) -> str:
    try:
        from rouh.models.accounts import User

        user = User.objects.filter(id=user_id).first()
        return (getattr(user, "first_name", "") or getattr(user, "username", "") or "").strip() or "the owner"
    except Exception:  # noqa: BLE001 - a name is only how the owner is shown
        return "the owner"


# ---------------------------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------------------------

def _workspace() -> str:
    from ..config import config

    return getattr(config, "assistant_repo", "") or ""


def _read(path: str, most: int) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(most)
    except OSError:
        return ""


def _when(ts) -> str | None:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts))) if ts else None
    except (TypeError, ValueError):
        return None


def _notes(path: str) -> str:
    """A task's own words: its AGENTS.md, then every other .md directly in its folder (a step's notes
    and reports), by name, each under its name, to `NOTES_MAX` characters in all, cut said so."""
    try:
        names = sorted(n for n in os.listdir(path) if n.endswith(".md") and n != "AGENTS.md")
    except OSError:
        return ""
    parts, used = [], 0
    for name in ["AGENTS.md", *names]:
        text = _read(os.path.join(path, name), NOTES_MAX + 1).strip()
        if not text:
            continue
        room = NOTES_MAX - used
        if room <= 0:
            parts.append(f"({name} and what follows are not included: the task's notes are over {NOTES_MAX:,} characters)")
            break
        piece = text if len(text) <= room else text[:room] + f"\n(cut at {NOTES_MAX:,} characters of notes)"
        parts.append((piece if name == "AGENTS.md" else f"== {name} ==\n{piece}"))
        used += len(piece)
    return "\n\n".join(parts)


def _is_task(path: str) -> bool:
    """Whether the folder is a task's, as its `.object.json` says."""
    try:
        said = json.loads(_read(os.path.join(path, ".object.json"), 20_000) or "{}")
    except ValueError:
        return False
    return isinstance(said, dict) and said.get("type") == "task"


def task_payload(row: dict, root: str, me: str = "the owner") -> dict:
    """One task as a Synapse item: its own words, nothing guessed. `me` is what the owner is called."""
    folder = str(row.get("folder") or "").strip("/")
    path = os.path.join(root, folder) if root and folder else ""
    # What was its meta, kept in its row since 22 October 2026 (`rouh/taskmeta.py`).
    from .. import taskmeta

    info: dict = taskmeta.of(str(row.get("id") or "")) or {}
    notes = _notes(path) if path else ""
    parts = folder.split("/")
    project = " / ".join(parts[:-1]) if len(parts) > 1 else ""
    # The row's own five words, never the file's: a task's status and summary are kept
    # in the database and nowhere else since 6 October 2026 (`rouh/taskrecord.py`).
    state = str(row.get("status") or row.get("state") or "")
    if row.get("archived_at"):
        state += ", archived"
    head = [f"Task {row['number']}: {row['title']}" if row.get("number") else f"Task: {row['title']}",
            f"State: {state}"]
    if project:
        head.append(f"Project: {project}")
    if folder:
        head.append(f"Folder: {folder}")
    summary = " ".join(str(row.get("summary") or "").split())
    if summary:
        head.append(f"Summary: {summary}")
    step = info.get("goal_step") if isinstance(info.get("goal_step"), dict) else {}
    for key, label in (("ask", f"Asked of {me}"), ("prep", "Prepared"), ("outcome", "Outcome"),
                       ("challenge", "Challenge"), ("solution", "Solution")):
        if str(step.get(key) or "").strip():
            head.append(f"{label}: {str(step[key]).strip()}")
    if str(info.get("question") or "").strip():
        head.append(f"Waiting on: {str(info['question']).strip()}")
    text = "\n".join(head) + ("\n\nNotes:\n" + notes.strip() if notes.strip() else "")
    meta = {"status": str(row.get("state") or ""), "task": str(row["id"])}
    if project:
        meta["project"] = project
    if folder:
        # A task and its steps are one thread, so link candidates find them first: a step's thread is
        # the task folder it sits in, a task's its own.
        parent = "/".join(parts[:-1])
        is_step = bool(parent and root and _is_task(os.path.join(root, parent)))
        meta["thread"] = "task:" + (parent if is_step else folder)
    return {"kind": "task", "title": str(row["title"])[:300], "text": text, "source": SOURCE,
            "source_key": f"task:{row['id']}", "said_at": _when(row.get("created_at")), **meta}


#: Read as text, as they are.
TEXT_EXT = {".md", ".markdown", ".txt", ".json", ".jsonl", ".csv", ".tsv", ".py", ".mjs", ".js", ".ts", ".sh",
            ".css", ".lua", ".conf", ".service", ".yml", ".yaml", ".toml", ".ini", ".log", ".sql", ".xml", ".eml"}
#: Never stored: Rouh's own bookkeeping, tooling, fonts and databases.
SKIP_NAMES = {".gitkeep", ".gitignore", ".DS_Store", "_migration-map.json"}
SKIP_EXT = {".ttf", ".otf", ".woff", ".woff2", ".db", ".sqlite", ".pyc", ".lock"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".claude"}
#: One file's words, at most this many characters (the extractor stops at 2,000,000 itself).
FILE_MAX = 300_000
FILE_SOURCE = "rouh-file"
CHAT_SOURCE = "rouh-chat"
CARD_SOURCE = "rouh-card"


def _task_folders() -> dict[str, dict]:
    """Each task's folder, with the task's key and thread, by folder."""
    out = {}
    for r in db.rows("SELECT id, folder, title FROM task WHERE folder <> ''"):
        out[str(r["folder"]).strip("/")] = {"key": f"task:{r['id']}", "id": str(r["id"]), "title": str(r["title"])}
    return out


def _owner_task(rel: str, folders: dict[str, dict]) -> tuple[str, dict | None]:
    """The deepest task folder holding a file, and its task."""
    parts = rel.split("/")[:-1]
    while parts:
        f = "/".join(parts)
        if f in folders:
            return f, folders[f]
        parts.pop()
    return "", None


def _file_words(path: str, name: str) -> tuple[str, str]:
    """(kind, text): a document's words, or a file described. Never raises."""
    import mimetypes

    ext = os.path.splitext(name)[1].lower()
    mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if ext in TEXT_EXT:
        text = _read(path, FILE_MAX + 1)
        return "doc", (text if len(text) <= FILE_MAX else text[:FILE_MAX] + f"\n(cut at {FILE_MAX:,} characters)")
    try:
        from .. import extracting, uploads

        if extracting.can_read(name, mime):
            words = uploads.words_in(path, mime, name)
            if words:
                return "doc", (words if len(words) <= FILE_MAX else words[:FILE_MAX] + f"\n(cut at {FILE_MAX:,} characters)")
    except Exception:  # noqa: BLE001 - described below instead
        log.exception("Synapse Master could not read %s", path)
    what = "A picture" if mime.startswith("image/") else "A file"
    return "file", f"{what}: {name} ({mime}, {size:,} bytes). Its contents are not read as words."


def _gone(ds: dict, source: str, keep: set[str], by: str, moved: set[str] | None = None) -> int:
    """Items of a source whose thing is gone, deleted from Master (with all derived from them). One whose key is
    in `moved` is still in Master under another key, so its words are not scrubbed (`ingest.delete`)."""
    from . import ingest

    n = 0
    for r in db.rows("SELECT id, source_key FROM synapse.item WHERE dataset_id = %s AND source = %s "
                     "AND deleted_at IS NULL", (ds["id"], source)):
        if r["source_key"] not in keep:
            try:
                ingest.delete(ds, r["id"], by=by, scrub=r["source_key"] not in (moved or ()))
                # Its key freed: the file is gone from the workspace, not deleted by a person (D60's kept
                # key is for those), so if it comes back it is stored again.
                db.run("UPDATE synapse.item SET source_key = source_key || '#gone-' || floor(extract(epoch FROM now())) "
                       "WHERE id = %s", (r["id"],))
                n += 1
            except Exception:  # noqa: BLE001
                log.exception("Synapse Master could not delete %s", r["source_key"])
    return n


def _put(ds: dict, payload: dict, old: dict | None, out: dict, by: str, lane: str) -> None:
    """Stored new, or the item it already is edited (its old version kept); never stored over a deletion."""
    from . import ingest

    if old and old.get("deleted_at") is not None:
        out["deleted_kept_out"] += 1
        return
    me = datasets.me(ds)
    try:
        if old:
            # An edit, not `store`: a file attached to a task would be taken for the same file on another email.
            got = ingest.edit(ds, old["id"], {k: v for k, v in payload.items() if k not in ("kind", "source", "source_key")},
                              by=by)
        else:
            got = ingest.store(ds, {**payload, "readers": [me], "owner": me}, by=by, lane=lane)
    except Exception:  # noqa: BLE001 - one never stops the others
        log.exception("Synapse Master could not store %s", payload.get("source_key"))
        got = {"ok": False}
    if got.get("ok"):
        out["changed" if old else "stored"] += 1
    else:
        out["failed"] += 1


def _walk(root: str):
    """The workspace's folders, and through each task's `files` link its files in the one store
    (`rouh/filestore.py`), so they are read and attached to their task like every other file of
    it. No other link is followed."""
    from rouh import filestore

    for top, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        yield top, dirs, files
        for d in list(dirs):
            link = os.path.join(top, d)
            if filestore.is_files_link(link):
                for inner, inner_dirs, inner_files in os.walk(link):
                    inner_dirs[:] = sorted(x for x in inner_dirs if x not in SKIP_DIRS
                                           and not x.startswith("."))
                    yield inner, inner_dirs, inner_files


def sync_files(ds: dict, *, by: str = "worker", lane: str = "backfill", limit: int | None = None) -> dict:
    """Every file of the workspace, each attached to its task; read again only when it changed."""
    root = _workspace()
    out = {"files": 0, "stored": 0, "changed": 0, "same": 0, "failed": 0, "deleted_kept_out": 0, "gone": 0}
    if not root or not os.path.isdir(root):
        return out
    folders = _task_folders()
    have = {r["source_key"]: r for r in db.rows(
        "SELECT id, source_key, deleted_at, meta->>'file_mtime' AS mtime, meta->>'file_size' AS size FROM synapse.item "
        "WHERE dataset_id = %s AND source = %s", (ds["id"], FILE_SOURCE))}
    seen: set[str] = set()
    here: set[tuple[str, int]] = set()  # (file name, size) of every file there now, to tell a move from a deletion
    done = 0
    for top, dirs, files in _walk(root):
        for name in sorted(files):
            if name in SKIP_NAMES or os.path.splitext(name)[1].lower() in SKIP_EXT:
                continue
            path = os.path.join(top, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            key = f"file:{rel}"
            seen.add(key)
            out["files"] += 1
            try:
                st = os.stat(path)
            except OSError:
                continue
            here.add((name, st.st_size))
            old = have.get(key)
            if old and old.get("deleted_at") is None and old.get("mtime") == str(int(st.st_mtime)) \
                    and old.get("size") == str(st.st_size):
                out["same"] += 1
                continue
            if limit and done >= limit:
                continue
            done += 1
            kind, text = _file_words(path, name)
            folder, task = _owner_task(rel, folders)
            # Named with its task, since many files share a name (index.html, AGENTS.md).
            title = f"{task['title']}: {name}" if task else rel
            payload = {"kind": kind, "title": title[:300], "text": f"{rel}\n\n{text}", "source": FILE_SOURCE,
                       "source_key": key, "said_at": _when(st.st_mtime), "file_name": name,
                       "file_size": st.st_size, "file_type": os.path.splitext(name)[1].lower().lstrip("."),
                       "file_mtime": str(int(st.st_mtime))}
            if task:
                payload.update({"attached_to": [task["key"]], "task": task["id"],
                                "thread": "task:" + folder, "project": " / ".join(folder.split("/")[:-1])})
            _put(ds, payload, old, out, by, lane)
    if not limit:
        # A file with the same name and size elsewhere moved there with its task (13 October 2026: tasks 89 and
        # 98 moved project, 874 files), and its words are already stored again under the new key.
        moved = {k for k, r in have.items() if k not in seen and r.get("deleted_at") is None
                 and (k.removeprefix("file:").rsplit("/", 1)[-1], int(r.get("size") or -1)) in here}
        out["gone"] = _gone(ds, FILE_SOURCE, seen, by, moved)
    return out


#: A chat longer than this is stored a day at a time (General is thousands of messages), so nothing in its
#: middle is cut out and each day is found by its own date.
SPLIT_AT = 100_000


def _chats() -> list[dict]:
    """Every chat, with what owns it: a task, a project, or nothing (General, an email's chat, a chat started
    on its own; Petar, 5 October 2026: "Include chats that don't belong to tasks"). A chat forked from
    another belongs to whatever the one it came from belongs to. Synapse's own chats are among them (Petar,
    10 October 2026: "I have chats everywhere, and they all should be in the Synapse memory"): automatic recall
    skips them, but what was said in them is in Master like everything else (checked on the live database
    that day: all 12 with messages were there)."""
    rank = {"task": 0, "project": 1, "chat": 2}
    owner: dict[str, tuple[str, str]] = {}
    for r in db.rows("SELECT src_type, src_id, dst_id FROM link WHERE rel = 'owns' AND dst_type = 'chat' "
                     "AND src_type IN ('task', 'project', 'chat')"):
        had = owner.get(r["dst_id"])
        if had is None or rank[r["src_type"]] < rank[had[0]]:
            owner[r["dst_id"]] = (r["src_type"], str(r["src_id"]))
    out = []
    for c in db.rows("SELECT id, title, created_at FROM chat ORDER BY created_at"):
        kind, oid, hops = None, None, 0
        at = owner.get(c["id"])
        while at and at[0] == "chat" and hops < 10:
            at, hops = owner.get(at[1]), hops + 1
        if at and at[0] != "chat":
            kind, oid = at
        out.append({**c, "src_type": kind, "src_id": oid})
    return out


def _said(text) -> str:
    return " ".join(str(text or "").split())[:80]


def _times(chat_id: str, msgs: list[dict], start: float) -> list[float]:
    """When each message was said. `message` keeps no time, so each of Petar's turns is found among the
    model's own record of the chat (`messages`, which has one) by its first words, in order, and the
    replies after it take its time."""
    typed = []
    for r in db.rows("SELECT ts, content FROM messages WHERE session_id = %s AND role = 'user' ORDER BY ts, id",
                     (chat_id,)):
        try:
            v = json.loads(r["content"])
        except (TypeError, ValueError):
            v = r["content"]
        if isinstance(v, str) and v.strip():
            typed.append((float(r["ts"]), _said(v)))
    out, j, t = [], 0, float(start or 0)
    for m in msgs:
        if m["role"] == "user":
            want = _said(m["body"])
            for k in range(j, min(j + 40, len(typed))):
                if typed[k][1] == want:
                    t, j = typed[k][0], k + 1
                    break
        out.append(t)
    return out


def _chat_text(msgs: list[dict], me: str = "the owner") -> str:
    lines = [f"{me if m['role'] == 'user' else 'Rouh' if m['role'] == 'assistant' else m['role']}: "
             f"{str(m['body'] or '').strip()}" for m in msgs if str(m["body"] or "").strip()]
    text = "\n\n".join(lines)
    if len(text) > FILE_MAX:
        # The newest part, which a long chat is about now, and where it began.
        text = text[:FILE_MAX // 3] + "\n\n(... the middle of the chat is not included ...)\n\n" + text[-2 * FILE_MAX // 3:]
    return text


def _chat_parts(c: dict, msgs: list[dict], me: str = "the owner") -> list[dict]:
    """The items a chat is stored as: the whole of it, or one a day when it is long. `me` is what the
    owner is called in it."""
    from datetime import datetime

    from .. import clock

    from ..conversations import GENERAL

    # General's row carries whatever title it was once given; it is General to everybody.
    name = "General" if c["id"] == GENERAL else (c["title"] or c["id"])
    base = {"kind": "doc", "source": CHAT_SOURCE}
    if c["src_type"] == "task":
        base.update({"attached_to": [f"task:{c['src_id']}"], "task": str(c["src_id"])})
    elif c["src_type"] == "project":
        base["project"] = str(c["src_id"])
    if sum(len(str(m["body"] or "")) for m in msgs) <= SPLIT_AT:
        return [{**base, "title": f"Chat: {name}"[:300], "text": _chat_text(msgs, me), "source_key": f"chat:{c['id']}",
                 "said_at": _when(c.get("created_at")), "messages": str(len(msgs))}]
    # The installation's own day (`clock.DEFAULT`), never a person's clock of the moment, so a chat's
    # days do not move when they travel.
    zone = clock.DEFAULT
    days: dict[str, list] = {}
    for m, t in zip(msgs, _times(c["id"], msgs, c.get("created_at") or 0)):
        days.setdefault(datetime.fromtimestamp(t, zone).date().isoformat() if t else "undated", []).append((m, t))
    return [{**base, "title": f"Chat: {name}, {day}"[:300], "text": _chat_text([m for m, _ in got], me),
             "source_key": f"chat:{c['id']}:{day}", "said_at": _when(got[0][1] or c.get("created_at")),
             "messages": str(len(got)), "chat_day": day} for day, got in sorted(days.items())]


def sync_chats(ds: dict, *, by: str = "worker", lane: str = "backfill", limit: int | None = None) -> dict:
    """Every chat, the whole conversation (a day at a time when it is long), stored again when it grew; a
    chat gone from Rouh is deleted from Master."""
    out = {"chats": 0, "stored": 0, "changed": 0, "same": 0, "failed": 0, "deleted_kept_out": 0, "gone": 0}
    have = {r["source_key"]: r for r in db.rows(
        "SELECT id, source_key, deleted_at, meta->>'messages' AS n FROM synapse.item WHERE dataset_id = %s AND source = %s",
        (ds["id"], CHAT_SOURCE))}
    keep: set[str] = set()
    done, cut_short = 0, False
    me = people.owner_name_of(ds) or "the owner"
    for c in _chats():
        out["chats"] += 1
        msgs = db.rows("SELECT seq, role, body FROM message WHERE chat_id = %s ORDER BY seq", (c["id"],))
        if not msgs:
            continue
        for payload in _chat_parts(c, msgs, me):
            key = payload["source_key"]
            keep.add(key)
            old = have.get(key)
            if old and old.get("deleted_at") is None and old.get("n") == payload["messages"]:
                out["same"] += 1
                continue
            if limit and done >= limit:
                cut_short = True
                continue
            done += 1
            _put(ds, payload, old, out, by, lane)
    if not cut_short:
        # A chat deleted from Rouh, and a long chat's whole item once it is kept a day at a time.
        out["gone"] = _gone(ds, CHAT_SOURCE, keep | {k for k, r in have.items() if r.get("deleted_at") is not None}, by)
    return out


#: When each Master's Slack members were last put on their contacts (`_tie_slack`), and how often.
_TIED: dict[str, float] = {}
TIE_EVERY = 3600.0


def _tie_slack(ds: dict, out: dict, *, now: bool = False) -> None:
    """Every Slack member on their contact (`slack.tie_all`), once an hour, and the people once made of a list
    of a Slack day's names taken away (`people.repair_list_people`) whenever there are any."""
    from rouh import slack

    try:
        conn = slack.connection(str(ds["org_id"]))
        if conn is not None and conn.team_id and str(conn.user_id) == str(ds["user_id"]) and \
                (now or time.time() - _TIED.get(str(ds["id"]), 0) > TIE_EVERY):
            out["members"] = slack.tie_all(conn)
            _TIED[str(ds["id"])] = time.time()
        if people.list_people(ds):
            out["list_people"] = people.repair_list_people(ds, by="slack sync")
    except Exception:  # noqa: BLE001 - the days are still kept
        log.exception("Synapse Master could not tie Slack's members to their contacts")


def sync_slack(ds: dict, *, by: str = "worker", lane: str = "backfill", limit: int | None = None) -> dict:
    """Every Slack conversation Rouh's app keeps, one item a day (`slack.master_items`), stored again when
    that day changed - a message added, edited or deleted - and deleted from Master when its day holds no
    message any more. Readable by the owner only; the owner's own direct messages are special."""
    from rouh import slack

    out = {"days": 0, "stored": 0, "changed": 0, "same": 0, "failed": 0, "deleted_kept_out": 0, "gone": 0}
    if not db.value("SELECT to_regclass('public.slack_messages') IS NOT NULL"):
        return out
    # Before the days, so a member already known is written into them with their address, never as a
    # bare name (`slack._senders`).
    _tie_slack(ds, out)
    try:
        items = slack.master_items(str(ds["user_id"]), str(ds["org_id"]))
    except Exception:  # noqa: BLE001 - next time
        log.exception("Synapse Master could not read what Slack keeps")
        out["failed"] += 1
        return out
    have = {r["source_key"]: r for r in db.rows(
        "SELECT id, source_key, deleted_at, meta->'slack'->>'digest' AS digest FROM synapse.item "
        "WHERE dataset_id = %s AND source = %s", (ds["id"], slack.SOURCE))}
    keep: set[str] = set()
    done, cut_short = 0, False
    for payload in items:
        out["days"] += 1
        key = payload["source_key"]
        keep.add(key)
        old = have.get(key)
        if old and old.get("deleted_at") is None and old.get("digest") == payload["slack"]["digest"]:
            out["same"] += 1
            continue
        if limit and done >= limit:
            cut_short = True
            continue
        done += 1
        _put(ds, payload, old, out, by, lane)
    if not cut_short:
        out["gone"] = _gone(ds, slack.SOURCE, keep | {k for k, r in have.items() if r.get("deleted_at") is not None},
                            by)
    # And after them, when one was stored, so somebody first met in one of them is tied too.
    if out["stored"] or out["changed"]:
        _tie_slack(ds, out, now=True)
    return out


def _card_text(body) -> str:
    """A card's words: its title, description and every block's text, pages' markup taken out."""
    import re

    try:
        d = json.loads(body) if isinstance(body, str) else (body or {})
    except ValueError:
        return str(body or "")
    out: list[str] = []

    def walk(v):
        if isinstance(v, str):
            t = re.sub(r"<style.*?</style>|<script.*?</script>", " ", v, flags=re.S | re.I)
            t = re.sub(r"<[^>]+>", " ", t)
            t = " ".join(t.split())
            if t:
                out.append(t)
        elif isinstance(v, dict):
            for k, x in v.items():
                if k not in ("block", "height", "after_message_id", "kind", "id"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(d)
    return "\n".join(out)


def sync_cards(ds: dict, *, by: str = "worker", lane: str = "backfill", limit: int | None = None) -> dict:
    """Each card a task owns, or any chat (a task's, or one of its own), at its newest version; attached to the
    task when there is one."""
    out = {"cards": 0, "stored": 0, "changed": 0, "same": 0, "failed": 0, "deleted_kept_out": 0}
    task_of_chat = {c["id"]: c["src_id"] for c in _chats() if c["src_type"] == "task"}
    found = db.rows(
        "SELECT DISTINCT ON (a.id) a.id, a.title, a.head_version, a.created_at, l.src_type, l.src_id, v.body "
        "FROM link l JOIN artifact a ON a.id = l.dst_id AND a.kind = 'card' "
        "JOIN artifact_version v ON v.artifact_id = a.id AND v.version = a.head_version "
        "WHERE l.rel = 'owns' AND l.dst_type = 'artifact' AND l.src_type IN ('task', 'chat') "
        "ORDER BY a.id, l.src_type DESC")
    rows = [{**r, "task": r["src_id"] if r["src_type"] == "task" else task_of_chat.get(r["src_id"])} for r in found]
    have = {r["source_key"]: r for r in db.rows(
        "SELECT id, source_key, deleted_at, meta->>'card_version' AS v FROM synapse.item WHERE dataset_id = %s AND source = %s",
        (ds["id"], CARD_SOURCE))}
    done = 0
    for c in rows:
        out["cards"] += 1
        key = f"card:{c['id']}"
        old = have.get(key)
        if old and old.get("deleted_at") is None and old.get("v") == str(c["head_version"]):
            out["same"] += 1
            continue
        if limit and done >= limit:
            continue
        done += 1
        text = _card_text(c["body"])[:FILE_MAX]
        if not text.strip():
            out["same"] += 1
            continue
        _put(ds, {"kind": "doc", "title": f"Card: {c['title']}"[:300], "text": text, "source": CARD_SOURCE,
                  "source_key": key, "said_at": _when(c.get("created_at")), "card_version": str(c["head_version"]),
                  **({"attached_to": [f"task:{c['task']}"], "task": str(c["task"])} if c["task"] else {})},
             old, out, by, lane)
    return out


def sync_everything(ds: dict, *, by: str = "worker", lane: str = "backfill", limit: int | None = None) -> dict:
    """The person's thoughts first, each copied in the moment it is kept and here again for any copy that
    missed (`rouh/thoughts.py`): a handful, and never kept waiting behind a first import of the files. Then
    tasks, so files, chats and cards find the task they are attached to."""
    from rouh import thoughts

    return {"thoughts": thoughts.sync_master(ds),
            "tasks": sync_tasks(ds, by=by, lane=lane, limit=limit),
            "files": sync_files(ds, by=by, lane=lane, limit=limit),
            "chats": sync_chats(ds, by=by, lane=lane, limit=limit),
            "cards": sync_cards(ds, by=by, lane=lane, limit=limit),
            "slack": sync_slack(ds, by=by, lane=lane, limit=limit)}


def sync_tasks(ds: dict, *, by: str = "worker", lane: str = "backfill", limit: int | None = None) -> dict:
    """Every task stored, or stored again where its text changed. Returns counts."""
    from . import ingest

    root = _workspace()
    rows = db.rows("SELECT id, number, title, state, status, folder, summary, created_at, updated_at, closed_at, "
                   "archived_at FROM task ORDER BY created_at, id")
    have = {r["source_key"]: r for r in db.rows(
        "SELECT source_key, raw, deleted_at FROM synapse.item WHERE dataset_id = %s AND source = %s",
        (ds["id"], SOURCE))}
    me = datasets.me(ds)
    out = {"tasks": len(rows), "stored": 0, "changed": 0, "same": 0, "failed": 0, "deleted_kept_out": 0}
    for row in rows[:limit] if limit else rows:
        p = task_payload(row, root, people.owner_name_of(ds) or "the owner")
        old = have.get(p["source_key"])
        if old and old.get("deleted_at") is not None:
            out["deleted_kept_out"] += 1   # deleted in Synapse on purpose: never brought back (D60)
            continue
        if old and old["raw"] == p["text"].replace("\x00", ""):
            out["same"] += 1
            continue
        try:
            got = ingest.store(ds, {**p, "readers": [me], "owner": me}, by=by, lane=lane)
        except Exception:  # noqa: BLE001 - one task never stops the others
            log.exception("Synapse Master could not store task %s", row["id"])
            got = {"ok": False}
        if got.get("ok"):
            out["changed" if old else "stored"] += 1
        else:
            out["failed"] += 1
    return out


_synced = 0.0


def sync_all() -> None:
    """Every person's master dataset brought up to date with the tasks; the worker calls this."""
    global _synced
    _synced = time.time()
    try:
        if not db.value("SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'synapse' "
                        "AND table_name = 'dataset' AND column_name = 'master')"):
            return
        if not db.value("SELECT to_regclass('public.task') IS NOT NULL"):
            return
        from .. import silos

        for ds in db.rows("SELECT * FROM synapse.dataset WHERE master"):
            got = sync_everything(ds)
            # The silos, wherever the source decides them (`rouh/silos.py`): each task's project, and what is
            # inside it, every event's calendar, the meetings, the contacts, the email, the layers.
            got["silos"] = {"labelled": silos.fill(ds)}
            if any(v.get("stored") or v.get("changed") or v.get("failed") or v.get("gone") or v.get("labelled")
                   for v in got.values()):
                log.info("Synapse Master %s: %s", ds["id"], got)
    except Exception:  # noqa: BLE001 - next time
        log.exception("Synapse Master could not bring the tasks in")


_running = threading.Lock()


def due() -> bool:
    return time.time() - _synced > SYNC_EVERY


def start_sync() -> None:
    """`sync_all` on a thread of its own, one at a time, so a big first import never holds the worker's loop."""
    global _synced
    _synced = time.time()
    if not _running.acquire(blocking=False):
        return

    def run():
        from django.db import connection

        try:
            sync_all()
        finally:
            connection.close()
            _running.release()

    threading.Thread(target=run, name="synapse-master-sync", daemon=True).start()
