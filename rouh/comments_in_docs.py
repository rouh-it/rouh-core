"""Comments in the Google documents ‹his› tasks link to: found, read and told apart.

Built by the nightly feature run, night 26, 29 October 2026 (task 94), for three genes that read
the same comments, each behind its own switch: Every point accounted for does not need it, but
Their comments (`rouh/comments_by.py`), New comments on your documents (`rouh/new_comments.py`)
and the comments under a task's Documents (`rouh/task_comments.py`) do.

On 28 October 2026 ‹he› asked for an explainer to be updated "as per all comments of my brother
nikola". Rouh looked in its inbox, in Slack and in the task, found none of them, and guessed;
the job it started later found three of his comments, six days old, on a colleague's Google Doc
that another task's notes link to. Nothing in Rouh could look across the documents ‹his› tasks
link to for the comments on them: `read_doc` reads one document's comments, when it is asked
for that one document.

This module is the one place that does it, with no model:

- `linked_docs`: every Google Doc, Sheet and Slides deck linked in any task's notes, with the
  tasks that link it, the most recently mentioned first (`task_docs.linked`, per task).
- `read_all`: the comments on each of them, a few at a time, with the documents that could not
  be read counted rather than failing the rest.
- `last_word`, `by_owner`, `link_to`: who spoke last on a comment, whether a name is the owner's,
  and the address that opens one comment in its document.

**Whose.** The workspace's own task notes, and the documents the connected Google account can
open (`org_id` and `user_id`, `rouh/tenancy.py`); nothing is written anywhere.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rouh.comments_in_docs")

#: How long the list of linked documents is kept before the notes are read again.
FRESH = 600.0
#: The most documents read at one go, and how many at a time.
MOST_DOCS = 60
AT_ONCE = 6
#: The address part of each kind of document, for a link to one comment.
PATHS = {"Google Doc": "document", "Google Sheet": "spreadsheets", "Google Slides": "presentation"}
_index: dict[str, tuple[float, list[dict]]] = {}


def _title(folder: Path) -> str:
    try:
        head = (folder / "AGENTS.md").read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
    except OSError:
        head = ""
    return re.sub(r"^#\s*\d+[.)]?\s*", "", head).strip() or folder.name.split(".", 1)[-1].replace("-", " ")


def linked_docs(root) -> list[dict]:
    """Every Google document linked in any task's notes, the most recently mentioned first:
    [{id, kind, url, title, at, tasks: [{rel, number, title}]}]. Kept for `FRESH` seconds."""
    from . import steps
    from .task_docs import linked

    key = str(root)
    held = _index.get(key)
    if held and time.time() - held[0] < FRESH:
        return held[1]
    base = Path(root)
    found: dict[str, dict] = {}

    def walk(folder: Path, depth: int) -> None:
        try:
            kids = sorted(p for p in folder.iterdir() if p.is_dir())
        except OSError:
            return
        for kid in kids:
            if kid.name.startswith(".") or kid.name in ("node_modules", "temp", "source-code"):
                continue
            if steps._TASK_NAME.match(kid.name) and (kid / "AGENTS.md").is_file():
                rel = str(kid.relative_to(base))
                task = {"rel": rel, "number": kid.name.split(".", 1)[0], "title": _title(kid)}
                for doc in linked(base, rel):
                    one = found.get(doc["id"])
                    if one is None:
                        found[doc["id"]] = {**doc, "tasks": [task]}
                        continue
                    one["tasks"].append(task)
                    one["at"] = max(one["at"], doc["at"])
                    if not one["title"] and doc["title"]:
                        one["title"] = doc["title"]
            elif depth < 4:
                walk(kid, depth + 1)

    walk(base, 0)
    out = sorted(found.values(), key=lambda d: d["at"], reverse=True)
    _index[key] = (time.time(), out)
    return out


def forget() -> None:
    """The next read looks at the notes again (a test world's notes changed)."""
    _index.clear()


async def read_all(drive, docs: list[dict], *, most: int = MOST_DOCS) -> tuple[list[tuple[dict, list[dict]]], int]:
    """The comments on each document, as `Drive.comments` gives them, and how many could not be
    read: ([(doc, comments)], failed)."""
    gate = asyncio.Semaphore(AT_ONCE)

    async def one(doc: dict):
        async with gate:
            try:
                return doc, await drive.comments(doc["id"])
            except Exception as exc:  # noqa: BLE001 - one it cannot open is counted, not fatal
                log.info("the comments on %s could not be read: %r", doc["id"], exc)
                return doc, None

    got = await asyncio.gather(*(one(d) for d in docs[:most]))
    read = [(d, c) for d, c in got if c is not None]
    return read, len(got) - len(read)


async def names(who, drive, docs: list[dict]) -> dict[str, str]:
    """The documents' own names from Drive, kept for the next time (`task_docs.kept_names`)."""
    from asgiref.sync import sync_to_async

    from . import task_docs

    known = await sync_to_async(task_docs.kept_names)(who)
    out = {d["id"]: known[d["id"]] for d in docs if known.get(d["id"])}

    async def one(doc: dict):
        try:
            return doc["id"], str((await drive.metadata(doc["id"])).get("name") or "")
        except Exception as exc:  # noqa: BLE001 - the notes' name stays
            log.info("the name of %s could not be read: %r", doc["id"], exc)
            return doc["id"], ""

    fresh = dict(x for x in await asyncio.gather(*(one(d) for d in docs if d["id"] not in out)) if x[1])
    if fresh:
        await sync_to_async(task_docs._keep_names)(who, fresh)
    return {**out, **fresh}


def moment(text) -> float:
    """Drive's RFC 3339 time as seconds, or 0."""
    try:
        got = datetime.fromisoformat(str(text or "").replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (got if got.tzinfo else got.replace(tzinfo=timezone.utc)).timestamp()


def day(at: float) -> str:
    """A moment as a day on the person's clock: Thursday 22 October."""
    from . import clock

    here = datetime.fromtimestamp(at, clock.zone())
    return f"{here:%A} {here.day} {here:%B}"


def last_word(comment: dict) -> dict:
    """Who spoke last on a comment, and when: its last answer, or the comment itself."""
    replies = [r for r in comment.get("replies") or [] if (r.get("words") or "").strip()]
    one = replies[-1] if replies else comment
    return {"who": one.get("who") or "", "me": bool(one.get("me")), "at": moment(one.get("at")),
            "answer": bool(replies)}


def _plain(name) -> str:
    return " ".join(str(name or "").lower().split())


def by_owner(name: str, who) -> bool:
    """Whether a comment's author is the owner, by their name as Rouh knows it."""
    from . import owner

    held = owner.resolve(who)
    if held is None:
        return False
    said = _plain(name)
    return bool(said) and said in {_plain(held.full_name), _plain(held.name)} - {""}


def link_to(doc: dict, comment_id: str) -> str:
    """The address that opens one comment in its document."""
    path = PATHS.get(doc.get("kind") or "", "document")
    return f"https://docs.google.com/{path}/d/{doc['id']}/edit?disco={comment_id}"


def clip(text, most: int = 400) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


__all__ = ["by_owner", "clip", "day", "forget", "last_word", "link_to", "linked_docs", "moment",
           "names", "read_all"]
