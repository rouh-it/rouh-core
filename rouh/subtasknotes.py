"""A subtask's own chat, the parent task it sits in, and what is sent up to it.

Petar, 29 September 2026 (fr_3113364c29fa): "While I am on the control room
screen I press the new chat [button] and I go to the parents chat", and with it
the recommendation he asked to be built: "make the new chat belong to the
subtask, but give it the parent task's relevant context as background. Keep the
conversation local by default, and provide a clear link or action to bring
important decisions back to the parent."

A subtask is a task row owned by its task (`objects.NESTS`), so a chat can
belong to it like to any task, and Start chat on its page now asks for one
(`taskChat` in app.js). This module is the rest of the recommendation:

- **Which parent.** `parent_of` and `describe_parent`, which the head of the
  conversation draws as the way up a level (`owning.describe`).
- **The background.** `prompt_block` puts the parent in front of Rouh in every
  turn of a subtask's chat: its number and name, where it is, what its
  `AGENTS.md` says, what its meta says the subtask is, and what the
  other subtasks have sent up. The parent's own chats are not copied in: they
  are long, and the parent's notes file is where the task already keeps what
  matters, which is what the person asked for as "relevant context".
- **Sending up.** `send` writes a note from a subtask's chat against the parent
  (`SubtaskNote`). It is listed on the parent's page under From its subtasks
  (`objectindex._level`), and `prompt_block` puts it in front of Rouh in the
  parent's chats and its other subtasks' too. Written by the person pressing
  Send to the task, never by the model on its own.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import clock, conversations, instructions, objects
from .models.objects import SubtaskNote

log = logging.getLogger("rouh.subtasknotes")

#: The longest note kept. A decision is a few sentences; a whole reply pasted
#: in is still taken, up to this.
MAX_NOTE = 4000

#: How much of the parent's `AGENTS.md` goes into a subtask's prompt. Its head
#: is what the task is and where it stands; the rest is history, and the model
#: can read the whole file from where the block says it is.
MAX_BACKGROUND = 3000

#: How many notes are put in front of the model, newest first.
NOTES_IN_PROMPT = 8


def _store() -> objects.ObjectStore:
    return conversations.store()


def parent_of(task_id: str) -> objects.Task | None:
    """The task this one is a subtask of, or None for a top-level task."""
    if not task_id:
        return None
    st = _store()
    owner = st.owner_of("task", task_id)
    if owner is None or owner[0] != "task":
        return None
    return st.get_task(owner[1])


def step_number(task: objects.Task) -> str:
    """What a subtask is called on its line: `68-01` out of `68-01.offer...`."""
    return step_of_folder(task.folder)


def step_of_folder(folder: str | None) -> str:
    """`68-01` out of `work/sales/68.bluf-proposal/68-01.offer...`, or ""."""
    head = (folder or "").rstrip("/").rsplit("/", 1)[-1].split(".", 1)[0]
    return head if head and "-" in head and head.replace("-", "").isdigit() else ""


def label(task: objects.Task) -> str:
    """A task's number, or a subtask's, and its name: "68 · Bluf Proposal"."""
    number = str(task.number) if task.number is not None else step_number(task)
    name = task.title or task.slug or task.folder or task.id
    return f"{number} · {name}" if number else name


def describe_parent(task_id: str) -> dict | None:
    """The parent of a subtask as the page draws a task: type, id, name, number
    and folder. None for a task that is under no task."""
    parent = parent_of(task_id)
    if parent is None:
        return None
    return {"type": "task", "id": parent.id, "label": parent.title or parent.id,
            "number": parent.number if parent.number is not None else None,
            "step": step_number(parent) if parent.number is None else "",
            "folder": parent.folder or ""}


def subtask_of(chat_id: str) -> tuple[objects.Task, objects.Task] | None:
    """(the subtask, its parent) when this chat is a subtask's, or None."""
    task = conversations.task_of(chat_id)
    if task is None:
        return None
    parent = parent_of(task.id)
    return (task, parent) if parent is not None else None


# ---------------------------------------------------------------------------
# Sending a note up
# ---------------------------------------------------------------------------


def send(chat_id: str, text: str) -> dict:
    """Send a decision or a note from a subtask's chat up to its parent task.

    `{"ok": True, "parent": {...}, "note": {...}}`, or `{"ok": False, "why"}`
    in words the person can act on.
    """
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return {"ok": False, "why": "There is nothing to send: write the decision first."}
    found = subtask_of(chat_id)
    if found is None:
        return {"ok": False, "why": "This chat is not a subtask's, so there is no task"
                                    " above it to send this to."}
    sub, parent = found
    row = SubtaskNote.objects.create(task_id=parent.id, subtask_id=sub.id, chat_id=chat_id,
                                     text=text[:MAX_NOTE], created_at=time.time())
    log.info("a note from subtask %s (%s) was sent up to task %s", sub.folder, chat_id,
             parent.number if parent.number is not None else parent.folder)
    return {"ok": True, "parent": describe_parent(sub.id), "note": _as_dict(row, sub)}


def _as_dict(row: SubtaskNote, sub: objects.Task | None) -> dict:
    return {"id": int(row.id), "text": row.text, "at": float(row.created_at),
            "chat": row.chat_id, "subtask": row.subtask_id,
            "from": label(sub) if sub is not None else "",
            "folder": sub.folder if sub is not None else ""}


def notes_for(task_id: str, *, limit: int = 50) -> list[dict]:
    """What the subtasks of this task have sent up to it, newest first."""
    if not task_id:
        return []
    rows = list(SubtaskNote.objects.filter(task_id=task_id)
                .order_by("-created_at", "-id")[:limit])
    st = _store()
    subs: dict[str, objects.Task | None] = {}
    out = []
    for row in rows:
        if row.subtask_id not in subs:
            subs[row.subtask_id] = st.get_task(row.subtask_id)
        out.append(_as_dict(row, subs[row.subtask_id]))
    return out


# ---------------------------------------------------------------------------
# What Rouh is told
# ---------------------------------------------------------------------------


def _read_head(path: Path, most: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) <= most:
        return text
    return text[:most].rsplit("\n", 1)[0].rstrip() + "\n[... the rest is in the file]"


def _what_the_parent_says_of(parent: objects.Task, sub: objects.Task, root: str) -> str:
    """The subtask's own entry in its parent's list of steps: title and line."""
    from . import taskmeta

    if not root or not parent.folder:
        return ""
    steps = (taskmeta.of(parent.id) or {}).get("steps")
    name = (sub.folder or "").rstrip("/").rsplit("/", 1)[-1]
    one = steps.get(name) if isinstance(steps, dict) else None
    if not isinstance(one, dict):
        return ""
    bits = []
    for key in ("title", "description"):
        said = str(one.get(key) or "").strip()
        if said and said not in bits:
            bits.append(said)
    return " - ".join(bits)


def _notes_lines(notes: list[dict], *, skip_subtask: str = "") -> str:
    lines = []
    for note in notes:
        if skip_subtask and note["subtask"] == skip_subtask:
            continue
        at = clock.moment(note["at"])
        when = at.strftime("%d %b %H:%M") if at else ""
        text = " ".join(note["text"].split())
        if len(text) > 600:
            text = text[:600].rstrip() + "..."
        lines.append(f"- {note['from'] or 'a subtask'} ({when}): {text}")
        if len(lines) >= NOTES_IN_PROMPT:
            break
    return "\n".join(lines)


def prompt_block(chat_id: str) -> str:
    """For the part of the system prompt that changes every turn, or "".

    In a subtask's chat: this chat is the subtask's, the parent's background,
    and what its other subtasks sent up, plus a word on what this chat itself
    sent. In a chat of a task that has subtask notes: those notes.
    """
    if not chat_id:
        return ""
    try:
        return _prompt_block(chat_id)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the subtask context for %s could not be read", chat_id)
        return ""


def _prompt_block(chat_id: str) -> str:
    task = conversations.task_of(chat_id)
    if task is None:
        return ""
    parent = parent_of(task.id)
    if parent is None:
        notes = _notes_lines(notes_for(task.id, limit=NOTES_IN_PROMPT))
        if not notes:
            return ""
        return (f"Sent up to this task ({label(task)}) from its subtasks' own chats,"
                f" newest first:\n{notes}")
    root = conversations._root()
    parts = [
        f"This conversation is the chat of subtask {label(task)} (folder {task.folder}),"
        f" which is a step of task {label(parent)} (folder {parent.folder}). Keep to the"
        " subtask: this chat is local to it. The parent task is background, so the person"
        " does not have to repeat what it is about. When something decided here matters"
        " to the whole task, the person can send it up with Send to the task at the top"
        " of this chat; say so when a decision like that is made."]
    about = _what_the_parent_says_of(parent, task, root)
    if about:
        parts.append(f"What the parent task says this subtask is: {about}")
    if root and parent.folder:
        head = _read_head(instructions.in_folder(Path(root) / parent.folder), MAX_BACKGROUND)
        if head:
            parts.append(f"The parent task's own notes ({parent.folder}/"
                         f"{instructions.NAME}), from the top:\n{head}")
    notes = notes_for(parent.id, limit=NOTES_IN_PROMPT * 2)
    others = _notes_lines(notes, skip_subtask=task.id)
    if others:
        parts.append("Sent up to the parent task from its other subtasks, newest first:\n"
                     + others)
    mine = _notes_lines([n for n in notes if n["subtask"] == task.id])
    if mine:
        parts.append("Already sent up to the parent task from this subtask:\n" + mine)
    return "\n\n".join(parts)
