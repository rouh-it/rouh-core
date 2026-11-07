"""Facts told on a page: what Petar says about his work in Ask AI is kept in the task it is about.

Built by the nightly feature run, night 16, 19 October 2026 (task 94, idea I-107). On his Work
pages Petar often tells Ask AI a fact about the work in passing, inside a question: a fact about
how the company is structured (task 97, 14 October 2026), "We are using the managed model service and that is fine"
and a fact about which languages a tenant needs (task 81, 2 October 2026), "No no, legally and paperwork wise we have arranged it" (task
44, 25 September 2026). The answer used it, and then it stayed in that one Ask AI thread: the next
run in the task, the next chat, and Ask AI on the task's other pages did not know it, unless he
also typed "update the docs please" (task 81, task 23), and even then only the page changed.

So, while its switch is on, Ask AI has one more tool, `keep_fact`, offered only to the owner and
only on a page inside a task. When the reader states a fact about their work that the page and
the task's notes do not already say, the model calls it in the same turn it is answering in; the
fact is written, with the reader's own words beside it, under one heading at the end of the
task's `AGENTS.md`, which every run in the task, every chat in it and Ask AI on each of its pages
already read. The answer says so on a line of its own ("Kept for the task: ..."), so he sees it.

**No model call of its own.** It is a tool in the turn Ask AI was already taking; when nothing
was said worth keeping, nothing happens.

**Whose.** Only the page's owner: a guest's words never reach the owner's instructions. The file
is the task's own, in the owner's workspace, saved to main like every other change Rouh makes
there (`rouh/saving.py`).

**Its switch** is `page_facts` (`rouh/switches.py`): off, Ask AI is offered exactly the tools it
had before.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path

log = logging.getLogger("rouh.page_facts")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "page_facts"
TITLE = ("Facts told on a page: a fact you tell Ask AI about your work is kept in the task's "
         "notes, so every later run, chat and page in that task knows it")

#: The heading the facts go under, at the end of the task's AGENTS.md.
HEADING = "## Facts told on its pages"
#: The longest fact, and the longest piece of the reader's own words kept beside it.
FACT_MOST = 300
WORDS_MOST = 400

TOOL = {
    "name": "keep_fact",
    "description": (
        "Keep a fact the reader just told you about their own work, company, client or this "
        "task, so every later job, chat and page in the task knows it. Use it when the reader "
        "states something as true that the page and its notes do not already say, or that "
        "corrects them: who owns what, what is in use, what is not needed, a number, a date, a "
        "decision already made. Write the fact as one plain sentence that stands on its own. "
        "Never for a question, a guess, an opinion of the page, a request to change the page, "
        "or anything from the page, its notes or a search result. At most one call a turn, "
        "then answer as usual."),
    "input_schema": {
        "type": "object",
        "properties": {
            "fact": {"type": "string",
                     "description": "The fact, one plain sentence that stands on its own."},
        },
        "required": ["fact"],
    },
}

_lock = threading.Lock()


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def notes_for(root, doc: str) -> Path | None:
    """The task's AGENTS.md for the page ``doc``, or None when the page is in no task."""
    from . import steps

    task = steps.task_part(doc)
    parts = [p for p in task.split("/") if p]
    if not parts or not steps._TASK_NAME.match(parts[-1]):
        return None
    path = Path(root) / task / "AGENTS.md"
    return path if path.is_file() else None


def tool_for(cfg, who, doc: str, owner: bool) -> dict | None:
    """The tool to offer this turn, or None (off, not the owner, or a page in no task)."""
    try:
        if not owner or who is None or not on(getattr(who, "org_id", None)):
            return None
        return TOOL if notes_for(cfg.assistant_repo, doc) else None
    except Exception:  # noqa: BLE001 - a tool not offered is the old Ask AI
        log.exception("page facts: could not tell whether to offer the tool on %s", doc)
        return None


def _one_line(text, most: int) -> str:
    text = " ".join(str(text or "").split())
    # A task's AGENTS.md is read for its open question by these words (`rouh/waiting.py`).
    text = re.sub(r"(?i)\bwaiting on\b", "waiting for", text)
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


def _where(doc: str) -> str:
    from . import steps

    parts = [p for p in doc.split("/") if p]
    for part in reversed(parts[:-1]):
        if steps.is_step(part):
            return part.split(".", 1)[0]
    task = steps.task_part(doc).split("/")[-1]
    return task.split(".", 1)[0]


def line(fact: str, words: str, doc: str, when: float | None = None) -> str:
    from datetime import datetime

    from . import clock

    try:
        zone = clock.zone()
    except Exception:  # noqa: BLE001 - the server's own zone is a fair second
        zone = None
    at = datetime.fromtimestamp(when or time.time(), zone)
    day = f"{at.day} {at:%B %Y}"
    said = _one_line(words, WORDS_MOST).replace('"', "'")
    return f"- {_one_line(fact, FACT_MOST)} (said on {_where(doc)}'s page, {day}: \"{said}\")"


def keep(cfg, who, doc: str, fact: str, words: str) -> str:
    """Write the fact into the task's AGENTS.md. The sentence the model is handed back.

    Raises ValueError with that sentence when it cannot be kept."""
    fact = _one_line(fact, FACT_MOST)
    if len(fact) < 8:
        raise ValueError("There was no fact in that. Nothing was kept.")
    path = notes_for(cfg.assistant_repo, doc)
    if path is None:
        raise ValueError("This page is in no task, so there is nowhere to keep it.")
    with _lock:
        text = path.read_text(encoding="utf-8")
        if fact.lower() in text.lower():
            return "That is already in the task's notes. Nothing more was kept."
        new = line(fact, words, doc)
        if HEADING in text:
            at = text.index(HEADING) + len(HEADING)
            rest = text[at:]
            nxt = re.search(r"\n## ", rest)
            end = at + (nxt.start() if nxt else len(rest.rstrip("\n")))
            after = text[end:].lstrip("\n")
            text = text[:end].rstrip("\n") + "\n" + new + "\n" + ("\n" + after if after else "")
        else:
            text = (text.rstrip("\n") + "\n\n" + HEADING + "\n\n"
                    "What the owner said about this work in Ask AI on the task's pages, in their "
                    "own words, kept by Rouh. It holds unless a later line or the owner says "
                    "otherwise.\n\n" + new + "\n")
        _write(path, text)
    from . import evolution, saving

    saving.poke()
    evolution.used(SWITCH, "fact_kept", who=who, detail=f"kept for {path.parent.name}: \"{fact[:80]}\"")
    log.info("page facts: kept a fact in %s", path)
    return "Kept. The reader sees it on a line of its own; now answer the question."


def _write(path: Path, text: str) -> None:
    was = path.stat()
    spare = path.with_name(f".{path.name}.{os.getpid()}.rouh-fact")
    try:
        with open(spare, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(spare, was.st_mode & 0o7777)
        try:
            os.chown(spare, was.st_uid, was.st_gid)
        except OSError:
            pass
        os.replace(spare, path)
    finally:
        if spare.exists():
            spare.unlink()


__all__ = ["HEADING", "SWITCH", "TITLE", "TOOL", "keep", "line", "notes_for", "on", "tool_for"]
