"""The files the person uploads, found by what is written in them.

Petar, 24 September 2026, on the Gene therapy board: "the files I give it are not
searchable. The uploads that is. The should be extracted in Md and those mds
should be searchable but also not show Md, show original file".

So every file the person gives Rouh has its words read out of it once, as
Markdown, and kept beside it; those words are what the search box reads; and
what the search box shows, and opens, is the file itself.

**Which files.** The ones the person gave: a file sent in a chat message, a
file added to a project with its Add files button, and a file uploaded to a
task or a subtask with Upload on its own page. A file dropped on the
composer and taken off it again before Send was never given, so a chat's files
are taken in when the message carrying them is sent (`runtime.py`), not when
they are uploaded. The Gene therapy drawer's files belong to the Gene therapy board,
which is the organisation's and is read scoped to it (`rouh/gene_therapy.py`); the
search box is not, so they are never taken in here. They come up through the
same route as a chat's, so their words are read all the same, and kept beside
them, where a run handed one of them by its path can find them.

**Reading.** `rouh/extracting.py` does it, in a process of its own for each
file, for the reasons it gives: a PDF that never finishes, a spreadsheet that
unzips to gigabytes, a parser that falls over. Nothing here is on a request or
on the socket. One thread of its own takes the files one at a time, in the
order they came, so a hundred uploads at once are a queue rather than a
hundred processes. It starts reading a file the moment it is uploaded
(`read_soon`), because the person is usually still typing then, and a sent
message waits a few seconds at most for the words of a file the model cannot
open itself (`ready`), so "what does this say?" about a .docx is answered from
what it says.

**Where the words are kept.** Twice, for two reasons, the way the workspace's
own files are:

- beside the original, as `.extracted.md` in the attachment's own folder
  (`attachments.WORDS`): the searchable copy the person asked for, and what the
  model is handed for a format it cannot open itself;
- in `uploaded_file`, a row per file with PostgreSQL's full-text vector of
  those words, which is what makes a search one query rather than a read of
  every file. Derived: `catch_up` puts back any row that is missing, from the
  folder, which is also how the files uploaded before this existed came in.

**What is shown.** Never the Markdown. A search result is the file's own name,
a few words round the match, where it was given, and the date; opening it
opens the original the way a press on it in the conversation would: a picture
in the viewer, a PDF or plain text in a tab of its own, and anything else
downloaded (`attachments.serving`, which is the rule for every file served).

**Whose they are.** Exactly the chat's, the project's or the task's they were
given in. A row names that owner, and a file whose chat, project or task has
been deleted is never found: a delete takes what is in the thing with it.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import time
from functools import reduce
from operator import and_

from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.db.models.functions import Substr

from . import attachments, extracting, objects
from .config import config
from .models import memory as transcript
from .models import objects as tables

log = logging.getLogger("rouh.uploads")

#: How long one file may take to read before it is given up on. Two minutes
#: reads a few hundred pages of PDF on this machine; a file that needs longer
#: is still found by its name.
EXTRACT_SECONDS = 120

#: How long a message that has just been sent waits for the words of the files
#: in it that the model cannot open itself. They are almost always read by
#: then, since reading starts the moment a file lands; this is the ceiling for
#: the one that is not, after which the model is told where the file is.
WAIT_SECONDS = 8

#: How much of a file's words a row that matched on its name shows.
FIRST_WORDS = 400

#: The kinds the model reads for itself, so a message never waits on them.
_MODEL_READS = ("image", "pdf", "text")

#: Where `python -m rouh.extracting` is run from: the folder the package is in.
_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: A file is only ever found while what it was given to is still there. The
#: same rule twice, once for the ORM and once for the full-text query in
#: `objects.near_matches`, and the two are kept side by side for that reason.
_GIVEN_SQL = ("(owner_type = 'chat' AND owner_id IN (SELECT id FROM chat))"
              " OR (owner_type = 'project' AND owner_id IN (SELECT id FROM project))"
              " OR (owner_type = 'task' AND owner_id IN (SELECT id FROM task))")


def _given() -> Q:
    return (Q(owner_type="chat", owner_id__in=tables.Chat.objects.values("id"))
            | Q(owner_type="project", owner_id__in=tables.Project.objects.values("id"))
            | Q(owner_type="task", owner_id__in=tables.Task.objects.values("id")))


def _store() -> attachments.Attachments:
    """The attachment store, which is where every uploaded file already is."""
    return attachments.Attachments(config.data_dir, readable_by=config.crew_user or None,
                                   group=config.attachments_group)


def _key(record: dict) -> tuple[str, str]:
    return (str(record.get("session_id") or ""), str(record.get("id") or ""))


# ---------------------------------------------------------------------------
# The one thread that reads and indexes
# ---------------------------------------------------------------------------
#
# A plain daemon thread and a queue rather than an executor: an executor's
# threads are waited for when the process exits, and a restart that sat behind
# two minutes of somebody's PDF would be a deploy that timed out.

_jobs: queue.Queue = queue.Queue()
_lock = threading.Lock()
_worker: threading.Thread | None = None
#: The newest job queued for each file, so a sent message can wait for it.
_pending: dict[tuple[str, str], threading.Event] = {}
#: Files whose words this process has already tried to read, whether or not
#: there were any, so one that failed is not read twice.
_tried: set[tuple[str, str]] = set()


def _submit(key: tuple[str, str] | None, job, *args) -> threading.Event:
    global _worker
    done = threading.Event()
    with _lock:
        if key is not None:
            _pending[key] = done
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="uploads", daemon=True)
            _worker.start()
    _jobs.put((key, job, args, done))
    return done


def _work() -> None:
    while True:
        key, job, args, done = _jobs.get()
        try:
            job(*args)
        except Exception:
            log.exception("an uploaded file could not be read or indexed")
        finally:
            done.set()
            with _lock:
                if key is not None and _pending.get(key) is done:
                    del _pending[key]


def read_soon(record: dict) -> None:
    """Start reading the words out of a file that has just been uploaded."""
    _submit(_key(record), _read, dict(record))


def take_in(records, owner: tuple[str, str]) -> None:
    """These files were given to a chat or a project: make them searchable.

    `owner` is ("chat", its id) for the files sent in a message,
    ("project", its id) for a file added to a project, and ("task", its id)
    for a file uploaded on a task's own page.
    """
    for record in records or []:
        _submit(_key(record), _take_in, dict(record), (str(owner[0]), str(owner[1])))


def ready(records, seconds: float = WAIT_SECONDS) -> None:
    """Wait, a little, for the words of the files the model will read as words.

    A picture, a PDF and a text file are sent to the model as themselves and
    are never waited for. Blocks, so it is called off the event loop.
    """
    end = time.monotonic() + seconds
    for record in records or []:
        if record.get("kind") in _MODEL_READS:
            continue
        with _lock:
            done = _pending.get(_key(record))
        if done is not None:
            done.wait(max(0.0, end - time.monotonic()))


def forget(session: str, att_id: str) -> None:
    """A file taken off a project is not found any more.

    Queued behind whatever is already waiting, so a file added and taken off
    again before its words were read cannot come back as a row afterwards.
    """
    _submit(None, _forget, str(session), str(att_id))


def start() -> None:
    """Take in, once, every file given before this process started."""
    _submit(None, _catch_up)


# ---------------------------------------------------------------------------
# The jobs
# ---------------------------------------------------------------------------


def _extract(record: dict) -> str | None:
    """The words in one file as Markdown, "" when it has none, None when unread.

    Only asked about a file `extracting.can_read`: starting a process to be
    told a photograph has no words is a process for nothing.
    """
    return words_in(str(record.get("path") or ""), str(record.get("kind") or ""),
                    str(record.get("name") or ""))


def words_in(path: str, kind: str = "", name: str = "") -> str | None:
    """The words in the file at `path` as Markdown, "" when it has none, None when unread.

    Read by `rouh.extracting` in a process of its own, held to
    `EXTRACT_SECONDS`, for an upload and for a file an email brought
    (`rouh/mail_attachments.py`) alike.
    """
    name = name or os.path.basename(path)
    env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "TMPDIR")
           if key in os.environ}
    env.update(PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    # Files inside files read (`rouh/inside_files.py`): the process imports nothing from Django,
    # so it is told the switch rather than reading it.
    from . import inside_files

    env[inside_files.ENV] = "1" if inside_files.allowed() else "0"
    started = time.monotonic()
    try:
        done = subprocess.run([sys.executable, "-m", "rouh.extracting", path, kind],
                              cwd=_HERE, env=env, capture_output=True,
                              timeout=EXTRACT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        log.warning("the words in %s took longer than %ds to read", name, EXTRACT_SECONDS)
        return None
    except OSError as exc:
        log.warning("the words in %s could not be read: %s", name, exc)
        return None
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        log.warning("the words in %s could not be read: %s", name,
                    said[-1] if said else f"exit {done.returncode}")
        return None
    words = done.stdout.decode("utf-8", "replace")
    log.info("read %d characters of words out of %s in %.1fs", len(words), name,
             time.monotonic() - started)
    return words


def _read(record: dict) -> str | None:
    """The words of one file: kept beside it already, or read now and kept."""
    store = _store()
    words = store.words(record)
    if words is not None:
        return words
    if not extracting.can_read(str(record.get("path") or ""), str(record.get("kind") or "")):
        return ""
    key = _key(record)
    if key in _tried:
        return None
    _tried.add(key)
    words = _extract(record)
    if words is not None:
        try:
            store.keep_words(record, words)
        except OSError as exc:
            log.warning("the words in %s could not be kept beside it: %s",
                        record.get("name"), exc)
    return words


def _take_in(record: dict, owner: tuple[str, str]) -> None:
    words = _read(record)
    # Looked for again after reading, which can take a while: a file taken
    # off a project in the meantime is not written back as a row.
    if _store().get(*_key(record)) is None:
        return
    _put(record, owner, words or "")


#: One row of the index, written whole or brought up to date.
_UPSERT = (
    "INSERT INTO uploaded_file (session, att_id, owner_type, owner_id, name, media_type,"
    " kind, size, uploaded_at, body, indexed_at)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    " ON CONFLICT (session, att_id) DO UPDATE SET owner_type = EXCLUDED.owner_type,"
    " owner_id = EXCLUDED.owner_id, name = EXCLUDED.name,"
    " media_type = EXCLUDED.media_type, kind = EXCLUDED.kind, size = EXCLUDED.size,"
    " uploaded_at = EXCLUDED.uploaded_at, body = EXCLUDED.body,"
    " indexed_at = EXCLUDED.indexed_at")


def _put(record: dict, owner: tuple[str, str], words: str) -> None:
    """One file into the index, with as much of its words as PostgreSQL will take.

    The same two things `ObjectStore.put_content` puts right for the
    workspace's own files: a NUL, which PostgreSQL refuses in text, and a
    vector over its megabyte, which it refuses to make. The first becomes a
    space; for the second the row is written with the first tenth of the
    words, then the first hundredth, then none, so the file is still found
    by its name.
    """
    session, att_id = _key(record)
    body = str(words or "").replace("\x00", " ")
    head = (session, att_id, owner[0], owner[1], str(record.get("name") or "file"),
            str(record.get("media_type") or ""), str(record.get("kind") or "file"),
            int(record.get("size") or 0), float(record.get("ts") or time.time()))
    for keep in (len(body), len(body) // 10, len(body) // 100, 0):
        try:
            with transaction.atomic(), connection.cursor() as cur:
                cur.execute(_UPSERT, (*head, body[:keep], time.time()))
        except DatabaseError:
            if keep == 0:
                raise
            continue
        if keep < len(body):
            log.warning("%s is searchable by the first %d of its %d characters only:"
                        " PostgreSQL would not index more", record.get("name"), keep,
                        len(body))
        return


def _forget(session: str, att_id: str) -> None:
    tables.UploadedFile.objects.filter(session=session, att_id=att_id).delete()


def given_files() -> dict[tuple[str, str], tuple[str, str]]:
    """Every file ever given, and what it was given to: (session, id) -> owner.

    A chat's files are the attachment markers in its transcript, which is the
    record of what was really sent; the folder a marker names is the one the
    file is in (it is not always the chat's own id, `memory.py` says why), and
    the chat it is in is the one the message is in. A project's files are the
    folder of them (`objectindex.files_key`), and a task's likewise
    (`objectindex.task_files_key`). Only what belongs to a chat, a project or a
    task that still exists is given.
    """
    from .objectindex import files_key, task_files_key

    chats = set(tables.Chat.objects.values_list("id", flat=True))
    projects = set(tables.Project.objects.values_list("id", flat=True))
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for chat_id, content in (transcript.TranscriptMessage.objects
                             .filter(content__contains='"attachment"')
                             .order_by("id").values_list("session_id", "content")
                             .iterator()):
        if chat_id not in chats:
            continue
        try:
            blocks = json.loads(content)
        except ValueError:
            continue
        for marker in attachments.markers_in(blocks):
            key = (str(marker.get("session_id") or chat_id), str(marker.get("id") or ""))
            if all(key):
                out.setdefault(key, ("chat", chat_id))
    store = _store()
    for project_id in projects:
        for record in store.listing(files_key(project_id)):
            out.setdefault(_key(record), ("project", project_id))
    # Only the tasks that have a folder of files: there are far more tasks
    # than projects, and almost none of them has had a file uploaded to it.
    tasks = set(tables.Task.objects.values_list("id", flat=True))
    try:
        held = [name for name in os.listdir(store.root) if name.startswith("task-")]
    except OSError:
        held = []
    # And those on the list of files (`rouh/filestore.py`), where every new one is.
    from .models.files import File

    held = sorted(set(held) | set(File.objects.filter(session__startswith="task-")
                                  .values_list("session", flat=True).distinct()))
    for name in held:
        task_id = name[len("task-"):]
        if task_id in tasks:
            for record in store.listing(task_files_key(task_id)):
                out.setdefault(_key(record), ("task", task_id))
    return out


def _catch_up() -> None:
    """Make the index what was given: in if it is missing, out if it has gone.

    Once, when Rouh starts. The first time, that is every file uploaded before
    this existed; after that it is whatever a restart cut off half way, and a
    row for a file taken off a project, or given to a chat or a project that
    has since been deleted.
    """
    started = time.monotonic()
    have = set(tables.UploadedFile.objects.values_list("session", "att_id"))
    given = given_files()
    store = _store()
    taken = 0
    for key, owner in given.items():
        if key in have:
            continue
        record = store.get(*key)
        if record is None:
            continue
        _take_in(record, owner)
        taken += 1
    gone = [key for key in have if key not in given]
    for session, att_id in gone:
        _forget(session, att_id)
    log.info("uploaded files: %d searchable, %d taken in now, %d gone, in %.1fs",
             len(have) - len(gone) + taken, taken, len(gone), time.monotonic() - started)


# ---------------------------------------------------------------------------
# Finding them
# ---------------------------------------------------------------------------

#: The marks of Markdown that are not words: heading marks, list bullets, the
#: pipes of a table and the rules under its header and between pages. A
#: snippet is read by a person, and "| Pelican feed | 12 |" is braces again.
_MARKS = re.compile(r"(?m)^#{1,6}(?= )|^- (?=\S)|\\?\||(?<![^\s|])-{3,}(?![^\s|])")


def _plain(text: str) -> str:
    """Markdown without its marks, the same length, so a cut stays where it was."""
    return _MARKS.sub(lambda m: " " * len(m.group(0)), str(text or ""))


def _shown_as(row: dict) -> str:
    """How the page opens this file: `picture`, `tab` or `download`.

    `attachments.serving` decides what may be shown on Rouh's own address at
    all, and it is the only thing that decides it.
    """
    _, how = attachments.serving({"media_type": row.get("media_type") or ""})
    if how != "inline":
        return "download"
    return "picture" if row.get("kind") == "image" else "tab"


def _hit(row: dict, matched: str, body: str) -> dict:
    """One file, as a hit in the shape `ObjectStore.find` gives one."""
    session, att_id = row["session"], row["att_id"]
    url = f"/attachments/{session}/{att_id}"
    return {"type": "file", "id": f"{session}/{att_id}", "matched": matched,
            "body": body, "title": row["name"], "number": None, "pinned": False,
            "state": "", "at": float(row["uploaded_at"] or 0) or None,
            "owner": (row["owner_type"], row["owner_id"]),
            "open": {"how": "file", "url": url, "as": _shown_as(row)}, "url": url}


_COLUMNS = ("session", "att_id", "owner_type", "owner_id", "name", "media_type", "kind",
            "uploaded_at")


def _word_hits(words: list[str], limit: int) -> list[dict]:
    """Files whose words hold every one of these, best match first.

    A query with no letter or digit in it is answered by the names alone. The
    punctuation in these words is partly Markdown's rather than the file's -
    the rule between two slides, the pipes of a table - and a search for "---"
    is not a search for every deck with two slides in it.
    """
    if not objects.indexable(words):
        return []
    try:
        with transaction.atomic():
            rows = objects.near_matches(
                words, table="uploaded_file", keys=("session", "att_id"),
                columns=_COLUMNS[2:], where=_GIVEN_SQL, limit=limit)
        return [_hit(row, "body", objects.snippet_of(row, words, near=_plain(row["near"])))
                for row in rows]
    except DatabaseError:
        log.debug("the full-text index would not take %r; scanning instead", words)
    rows = (tables.UploadedFile.objects.filter(_given())
            .filter(reduce(and_, [Q(body__icontains=w) for w in words]))
            .annotate(start=Substr("body", 1, FIRST_WORDS))
            .order_by("-uploaded_at").values(*_COLUMNS, "start")[:limit])
    return [_hit(row, "body", _plain(row["start"])) for row in rows]


def _say_where(hits: list[dict]) -> None:
    """Which chat or project each file was given in, as the row's tooltip says it."""
    ids = {"chat": set(), "project": set(), "task": set()}
    for hit in hits:
        ids[hit["owner"][0]].add(hit["owner"][1])
    titles = {
        "chat": dict(tables.Chat.objects.filter(id__in=ids["chat"])
                     .values_list("id", "title")),
        "project": dict(tables.Project.objects.filter(id__in=ids["project"])
                        .values_list("id", "title")),
        "task": dict(tables.Task.objects.filter(id__in=ids["task"])
                     .values_list("id", "title")),
    }
    for hit in hits:
        # Kept, as what the file belongs to, for the number its row wears.
        kind, ident = hit["given_in"] = hit.pop("owner")
        title = str(titles[kind].get(ident) or "").strip()
        hit["where"] = (f"In the {kind} “{title}”" if title
                        else f"In a {kind}")


def find(words, *, limit: int = 200) -> list[dict]:
    """Every file given to a chat, a project or a task whose name or words hold these words.

    In the shape `ObjectStore.find` hands back its hits, so the search box
    ranks a file against a chat and a task as it ranks those against each
    other (`objects.ranked`), with `open` and `url` already on it because a
    file opens in a way none of the five does. A name that matches is the
    better hit, and shows the start of the file's words.
    """
    words = [str(w) for w in (words or []) if w]
    if not words:
        return []
    found: dict[str, dict] = {}
    for row in (tables.UploadedFile.objects.filter(_given())
                .filter(reduce(and_, [Q(name__icontains=w) for w in words]))
                .annotate(start=Substr("body", 1, FIRST_WORDS))
                .order_by("-uploaded_at").values(*_COLUMNS, "start")[:limit]):
        hit = _hit(row, "title", _plain(row["start"]))
        found[hit["id"]] = hit
    for hit in _word_hits(words, limit):
        found.setdefault(hit["id"], hit)
    hits = list(found.values())
    _say_where(hits)
    return objects.ranked(hits)[:limit]
