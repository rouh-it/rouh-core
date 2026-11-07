"""Pinning a task or a step: a small lift on Petar's Control Room.

Petar, 29 September 2026, by voice: there are far too many tasks and subtasks,
and the Control Room flooded him, so from 30 September the room showed only
what he pinned. On 9 October 2026 he turned that down - his work moves too
fast to pin - and the room became a map of clusters sized by what he does
(`controlroom.py`). A pin is still his, everywhere it was, and on the map it
lifts the cluster its task is in a little (`controlroom.PIN_BOOST`), never so
much that it overrides everything else or keeps a quiet cluster on the map.

**A pin is the `pinned` mark every task row already has** (`owning.pin`), the
one the rail's Pinned section is drawn from, so pinning 19 from the Control
Room's side and from the rail's three dots is one mark and not two that could
disagree. It is kept in the objects database, which is the source of truth on
the laptop and on the server alike.

**A pin can be at any depth, and each one stands on its own.** A task, a step,
or a step within a step: he pins exactly the thing he cares about and never
has to pin the parent as well. Pinning or unpinning one row never touches any
other row, so unpinning task 19 leaves its step 19-04 pinned if it was, which
is how he narrows the room down to the page he wants.

Three ways in, all through `pin` here:

* the pin in the header of every task's and step's own page,
* the pin on each row of the task browser (both through
  `objectindex.change`, action ``pin``),
* Rouh, by voice or text: "pin 58", "prioritise 62 dash 18", "unpin 19",
  "what is pinned" (the ``pin`` tool in `tools.py`, which reads a reference
  with `find`).
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from . import archiving, objects, owning

log = logging.getLogger(__name__)

#: A reference the way it is said: "58", "62-18", "62 dash 18", "19.4",
#: "19-04-1", "task 19 step 4". Only the numbers matter, in order.
_NUMBERS = re.compile(r"\d+")
#: What a spoken reference may hold besides its numbers.
_REF_WORDS = re.compile(r"^(?:pin|unpin|prioriti[sz]e|task|step|subtask|number|no\.?|#|dash|"
                        r"minus|point|dot|hyphen|slash|and|[-./\s,])*$", re.I)
#: The leading number of a step folder: `19-04` of `19-04.packages`, `01` of
#: `01-gather-data`, which is where a step's number is written.
_LEADING = re.compile(r"^(\d+(?:-\d+)*)")


def _store() -> objects.ObjectStore | None:
    return objects.shared_store(even_when_off=True)


def _label(row, number: str = "") -> str:
    shown = number or (str(row.number) if getattr(row, "number", None) is not None else "")
    return f"{shown} {row.title}".strip() if shown else row.title


def number_of(slug: str, number=None) -> str:
    """What a task or step is called by: its own number, or the one in its folder."""
    if number is not None:
        return str(number)
    found = _LEADING.match(str(slug or ""))
    return found.group(1) if found else ""


def pin(task_id: str, on: bool = True) -> dict:
    """Pin one task or step, or unpin it, and nothing else.

    ``ok``, and ``did`` or ``why`` in words for the person, as the task
    browser's `change` answers. ``pinned`` is what it is now.
    """
    st = _store()
    row = st.get_task(task_id) if st is not None and task_id else None
    if row is None:
        return {"ok": False, "why": "There is no task or step here with that id."}
    name = _label(row, number_of(row.slug, row.number))
    if bool(row.pinned) == bool(on):
        return {"ok": True, "pinned": bool(on),
                "did": f"{name} was already {'pinned' if on else 'not pinned'}"}
    done = owning.pin("task", row.id, bool(on))
    if not done.get("ok"):
        return {"ok": False, "why": done.get("why") or "The pin could not be written down."}
    return {"ok": True, "pinned": bool(on), "did": f"{'Pinned' if on else 'Unpinned'} {name}"}


def find(said: str) -> dict:
    """The task or step a reference names, the way the person says it.

    ``{"ok": True, "id", "name"}``, or ``{"ok": False, "why"}`` with the words
    to say back, and ``choices`` when a name fits more than one. Numbers first:
    "58" is task 58, "62-18" and "62 dash 18" its step 18, "19-4-1" step 1
    inside step 19-04. Anything else is read as words of a name, and has to
    fit one live task or step and no other.
    """
    text = str(said or "").strip()
    if not text:
        return {"ok": False, "why": "No task or step was named."}
    st = _store()
    if st is None:
        return {"ok": False, "why": "Rouh's register of tasks is not open on this machine."}
    numbers = [int(n) for n in _NUMBERS.findall(text)]
    if numbers and _REF_WORDS.match(_NUMBERS.sub(" ", text)):
        return _by_numbers(st, numbers)
    return _by_name(st, text)


def _by_numbers(st: objects.ObjectStore, numbers: list[int]) -> dict:
    task = st.numbered_task(numbers[0])
    if task is None:
        return {"ok": False, "why": f"There is no task {numbers[0]}."}
    at, shown = task, str(task.number)
    rest = numbers[1:]
    # "62-18" is said with the task's number again in front of the step's, and
    # so is written in its folder; "62-18-2" goes one deeper.
    for part in rest:
        kid = _kid_numbered(st, at, part)
        if kid is None:
            return {"ok": False, "why": f"{shown} {at.title} has no step {shown}-{part:02d}."}
        at = kid
        shown = number_of(kid.slug) or f"{shown}-{part:02d}"
    return {"ok": True, "id": at.id, "name": _label(at, shown)}


def _kid_numbered(st: objects.ObjectStore, parent, part: int):
    """The step under `parent` whose number ends in `part`, or None.

    Its row when it has one; a step folder a job wrote by hand that the rows
    have not taken in yet is taken in here (`owning.task_at`), because the
    person can see it on the page and pins what they see."""
    for _kind, ident in st.children_of("task", parent.id, "task"):
        row = st.get_task(ident)
        if row is not None and _ends_in(row.slug, part):
            return row
    root = owning._workspace()
    if not root or not parent.folder:
        return None
    try:
        names = sorted(os.listdir(Path(root) / parent.folder))
    except OSError:
        return None
    for name in names:
        if _ends_in(name, part) and (Path(root) / parent.folder / name).is_dir():
            ident = owning.task_at(f"{parent.folder}/{name}")
            return st.get_task(ident) if ident else None
    return None


def _ends_in(slug: str, part: int) -> bool:
    found = _LEADING.match(str(slug or ""))
    return bool(found) and int(found.group(1).split("-")[-1]) == part


def _by_name(st: objects.ObjectStore, text: str) -> dict:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in ("the", "task", "step")]
    if not words:
        return {"ok": False, "why": "No task or step was named."}
    kept = archiving.archived(st)
    hits = []
    for row in st.list_tasks(limit=None):
        if row.id in kept or row.state == "done":
            continue
        hay = f"{row.title} {row.slug}".lower()
        if all(w in hay for w in words):
            hits.append(row)
    exact = [r for r in hits if r.title.strip().lower() == text.lower()]
    if len(exact) == 1:
        hits = exact
    if len(hits) == 1:
        row = hits[0]
        return {"ok": True, "id": row.id, "name": _label(row, number_of(row.slug, row.number))}
    if not hits:
        return {"ok": False, "why": f"No open task or step is called “{text}”."}
    return {"ok": False, "why": f"“{text}” fits {len(hits)} tasks and steps: say which by number.",
            "choices": [_label(r, number_of(r.slug, r.number)) for r in hits[:12]]}


def listing() -> list[dict]:
    """Everything pinned now, archived ones left out: each with its number,
    its name, and the task it is in when it is a step."""
    st = _store()
    if st is None:
        return []
    kept = archiving.archived(st)
    out = []
    for row in st.list_tasks(limit=None):
        if not row.pinned or row.id in kept:
            continue
        one = {"id": row.id, "number": number_of(row.slug, row.number), "title": row.title,
               "state": row.state}
        owner = st.owner_of("task", row.id)
        if owner and owner[0] == "task":
            up = st.get_task(owner[1])
            while up is not None:
                above = st.owner_of("task", up.id)
                if not above or above[0] != "task":
                    break
                up = st.get_task(above[1])
            if up is not None:
                one["in"] = _label(up, number_of(up.slug, up.number))
        out.append(one)
    out.sort(key=lambda o: [int(n) for n in _NUMBERS.findall(o["number"])] or [10 ** 6])
    return out
