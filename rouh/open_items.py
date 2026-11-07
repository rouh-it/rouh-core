"""Open on this task: what a task's notes say is still open, listed on its page, each closed with
Done.

Built by the nightly feature run, night 28, 31 October 2026 (task 94, idea I-169). Every task's
`AGENTS.md` starts with Where this stands: where it is, then what is open, written by the job
that did the last step ("Open: Petar's own edits, a timed run, and the PDF and PowerPoint exports
after the last change", task 154, 28 October 2026, about a talk given that afternoon). Only a job
or a chat ever changes those lines, so an item ‹he› has done stays open in the notes until ‹he›
asks somebody to close it, and every later run, chat and Ask AI in the task reads it as still to
do: the agent instructions say it plainly, "an agent obeys a stale conclusion that looks
current".

So, while its switch is on, a task's own page has a section **Open on this task**, near the end,
with each open item of its Where this stands as the notes word it, and **Done** beside each. Done
strikes the item through in the notes and labels it, "~~...~~ **Done (31 October 2026, marked done
by ‹owner› on the task's page).**", kept rather than deleted as the agent instructions ask, and
saved to the workspace like every change Rouh makes there (`rouh/saving.py`); Undo puts the line
back as it was. Nothing is decided for ‹him› and no model is asked.

`items` is also what Made, not handed over reads (`rouh/not_handed.py`).

**Whose.** The task's own notes in the owner's workspace; only the owner signed in sees or
changes them.

**Its switch** is `open_items` (`rouh/switches.py`): off, no section is drawn and the press is
refused.
"""
from __future__ import annotations

import hashlib
import html
import logging
import re
import threading
from datetime import date
from pathlib import Path

log = logging.getLogger("rouh.open_items")

SWITCH = "open_items"
TITLE = ("Open on this task: the open items in a task's Where this stands listed on its page, "
         "each closed with Done, kept and labelled in its notes")
NOTES = "AGENTS.md"
#: The most items listed on a page.
MOST = 12
_lock = threading.Lock()

_WHERE = re.compile(r"^(#{1,6})\s*Where this stands\s*$", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s")
_OPEN = re.compile(r"^\s*(?:\*\*)?Open(?: items)?(?:\*\*)?\s*:\s*(?:\*\*)?\s*(.*)$", re.IGNORECASE)
_BULLET = re.compile(r"^- (.+)$")
#: An item already closed, or a line kept only to say what replaced it.
_SHUT = re.compile(r"^(~~|\*\*(Replaced|Overtaken|Done|Closed)\b)", re.IGNORECASE)
_DONE = re.compile(r"^~~(?P<was>.+)~~ \*\*Done \([^)]*on the task's page\)\.\*\*$")


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _key(text: str) -> str:
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def _where_lines(lines: list[str]) -> tuple[int, int]:
    """[start, end) of the Where this stands section's lines, or (0, 0) when there is none."""
    for n, line in enumerate(lines):
        found = _WHERE.match(line.strip())
        if found:
            level = len(found.group(1))
            for m in range(n + 1, len(lines)):
                head = _HEADING.match(lines[m])
                if head and len(head.group(1)) <= level:
                    return n + 1, m
            return n + 1, len(lines)
    return 0, 0


def items(text: str) -> list[dict]:
    """Each open item of the notes' Where this stands: {key, text, line, inline}, in order.

    An item is a top-level "- " line under a line that opens "Open:", or the rest of that line
    when it says the item itself ("Open: a timed run."). A line struck through or labelled
    Replaced, Overtaken or Done is not open."""
    lines = text.splitlines()
    start, end = _where_lines(lines)
    out: list[dict] = []
    n = start
    while n < end:
        found = _OPEN.match(lines[n])
        if not found:
            n += 1
            continue
        rest = found.group(1).strip().strip("*").strip()
        if rest and not _SHUT.match(rest):
            out.append({"key": _key(lines[n]), "text": rest, "line": n, "inline": True})
        m = n + 1
        while m < end and not lines[m].strip():
            m += 1
        while m < end:
            line = lines[m]
            bullet = _BULLET.match(line)
            if bullet:
                said = bullet.group(1).strip()
                if not _SHUT.match(said):
                    out.append({"key": _key(line), "text": said, "line": m, "inline": False})
            elif line.startswith(("  ", "\t")) and line.strip():
                pass  # a line of the item above, or a list under it
            else:
                break
            m += 1
        n = m
    return out


def read(root, rel: str) -> tuple[Path, str] | None:
    path = Path(str(root)) / rel / NOTES
    try:
        return path, path.read_text(encoding="utf-8")
    except OSError:
        return None


def _plain(text: str) -> str:
    """An item's words as a person reads them: the Markdown marks taken off, links as their words."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"(\*\*|__|`)", "", text).strip()


def section(person, root, rel: str) -> str:
    """The section on a task's own page; "" when off, nobody is signed in, or nothing is open."""
    from . import steps

    if person is None or not rel or steps.is_step(rel):
        return ""
    try:
        if not on(person):
            return ""
        got = read(root, rel)
        found = items(got[1]) if got else []
    except Exception:  # noqa: BLE001 - the page is drawn without it
        log.exception("the open items of %s could not be read", rel)
        return ""
    if not found:
        return ""
    rows = []
    for one in found[:MOST]:
        rows.append(
            f'<div class="oopen" data-key="{one["key"]}">'
            f'<p class="oopen-what">{html.escape(_plain(one["text"]))}</p>'
            f'<p class="oopen-acts"><button type="button" class="obtn oopen-done" hidden>Done</button>'
            f'<span class="oopen-said" role="status"></span></p></div>')
    more = (f'<p class="omore">and {len(found) - MOST} more in the notes</p>'
            if len(found) > MOST else "")
    return (f'<section class="oset oopens" id="tkOpen" aria-label="Open on this task">'
            f'<h2 class="divider">Open on this task<span class="c">{len(found)}</span></h2>'
            f'<p class="oopen-note">From the notes\' Where this stands. Done marks it done there, '
            f'so every job and chat in this task knows.</p>'
            f'<div class="rows">{"".join(rows)}</div>{more}</section>')


class Refused(ValueError):
    """What cannot be done with an item, in a sentence."""


def _owner_name(person) -> str:
    from . import owner

    found = owner.resolve(person)
    return (found.name if found else "") or "the owner"


def closed_line(line: str, item: dict, person, today: date | None = None) -> str:
    day = today or date.today()
    mark = (f"**Done ({day.day} {day.strftime('%B')} {day.year}, marked done by "
            f"{_owner_name(person)} on the task's page).**")
    text = item["text"]
    at = line.rfind(text)
    if at < 0:
        raise Refused("That item is not in the notes as it was. Reload the page.")
    return line[:at] + f"~~{text}~~ {mark}" + line[at + len(text):]


def act(person, root, rel: str, key: str, do: str) -> dict:
    """Done on an item, or Undo of it: the notes' line changed, kept and labelled."""
    from . import evolution, page_facts, saving, steps

    if person is None or not on(person):
        raise Refused("Open on this task is switched off.")
    if not rel or steps.is_step(rel):
        raise Refused("That is not a task's page.")
    if do not in ("done", "undo"):
        raise Refused("Done, or Undo.")
    with _lock:
        got = read(root, rel)
        if got is None:
            raise Refused("This task has no notes.")
        path, text = got
        lines = text.split("\n")
        if do == "done":
            item = next((i for i in items(text) if i["key"] == key), None)
            if item is None:
                raise Refused("That item is not open in the notes any more. Reload the page.")
            lines[item["line"]] = closed_line(lines[item["line"]], item, person)
        else:
            for n, line in enumerate(lines):
                body = line[2:] if line.startswith("- ") else line
                head = line[:len(line) - len(body)]
                found = None
                for m in re.finditer(r"~~(?P<was>.+?)~~ \*\*Done \([^)]*on the task's page\)\.\*\*", body):
                    found = m
                if found is None:
                    continue
                back = head + body[:found.start()] + found.group("was") + body[found.end():]
                if _key(back) == key:
                    lines[n] = back
                    break
            else:
                raise Refused("That item is not marked done in the notes. Reload the page.")
        page_facts._write(path, "\n".join(lines))
    saving.poke()
    if do == "done":
        evolution.used(SWITCH, "done", who=person, detail=f"marked an open item done in {rel}")
    return {"ok": True}


__all__ = ["SWITCH", "TITLE", "Refused", "act", "items", "on", "read", "section"]
