"""Copies kept in step: a change to one form of a piece of work is made to its other forms too.

Built by the nightly feature run, night 14, 17 October 2026 (task 94, idea I-061). On 16 October
2026 Petar had nine slides added to task 119's deck. The deck is in two forms, the HTML slides of
step 119-04 and the same deck in Google Slides, step 119-05, and the task's own meta says
so: its arrow from 119-04 to 119-05 reads "makes it in Google Slides, as confirmed". The run put
the slides in the Google Slides copy only, said "No. I only added them to the Google Slides deck"
when he asked, and he had to ask again: "Can you please add them to the HTML to?".

So, while its switch is on, every run Rouh starts is told two things, and nothing is drawn on any
screen:

- **The rule** (`RULE`, after the agent instructions, from `agent_instructions.block`): a change to
  one form of a piece of work is made to every other form of it in the same run, unless the person
  named only one, and the run's last message names each form it changed and any it left.
- **The copies in its own task** (`for_task`, after the task in play, from
  `agent_instructions.task_block`), found by code in the task's files: each arrow of the task's
  meta whose label says a step is the same work in another form (Google Slides or Docs, a
  PDF, Word, PowerPoint, typeset for paper), and each step that keeps a PDF, a .pptx or a .docx
  beside its page, which is what the PDF button leaves there.

**No model call.** The copies are read from the task's files; the rule is words in the
instructions the run was given anyway.

**Whose.** The rule is the organisation's runs'; the copies are the run's own task's.

**Its switch** is `copies_in_step` (`rouh/switches.py`), off until Petar keeps it in Mutations: off,
no run is told either.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger("rouh.copies")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "copies_in_step"
TITLE = ("Copies kept in step: a change to one form of a piece of work, such as the deck's HTML "
         "slides, is made to its other forms too, such as the same deck in Google Slides")

RULE = (
    "Some work exists in more than one form: a page and the same deck in "
    "Google Slides, a review and its print-ready PDF, a page and the PDF made from it. When you "
    "change one form, make the same change to every other form of that work in the same run, "
    "unless the person named only one of them. Find the other forms in the task's meta "
    "(`rouh-task meta <task>`: an arrow whose label says a step makes the same work in another form, such as \"makes it in "
    "Google Slides\") and among the files of the step you change (a PDF, a .pptx or a .docx beside "
    "its page; make a PDF again from the changed page). In your last message, name each form you "
    "changed, and any form you left as it was and why."
)

#: What an arrow's label says when its step is the same work in another form.
FORM = re.compile(
    r"google\s+(?:slides|docs?|sheets?)|\bpdfs?\b|\bword\b|\bdocx\b|powerpoint|\bpptx\b|keynote|"
    r"\bexcel\b|\bxlsx\b|typeset|print[- ]ready|for paper|printable",
    re.I)
#: The files beside a step's page that are another form of it.
KEPT_FORMS = (".pdf", ".pptx", ".docx", ".xlsx", ".key")
#: A file kept only as an earlier version, which is no form to change.
OLD = re.compile(r"supersed|\bold\b|previous|earlier|first[- ]version", re.I)
#: The most copies named for one task, and files named for one step.
MOST = 12
MOST_FILES = 6


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def _task_file(folder: Path) -> tuple[Path, dict] | None:
    """The meta that lists `folder`'s steps (`rouh/taskmeta.py`): its own, when it has steps,
    else the one of the task it is a step of."""
    from . import taskmeta

    for at in (folder, folder.parent):
        got = taskmeta.read(at)
        if isinstance(got, dict) and (got.get("steps") or got.get("arrows")):
            return at, got
    return None


def _step_title(steps: dict, key: str) -> str:
    step = steps.get(key) if isinstance(steps, dict) else None
    return str((step or {}).get("title") or "").strip() if isinstance(step, dict) else ""


def found(folder: Path) -> list[str]:
    """The copies in the task `folder` is, or is a step of, one line each: the arrows that say a
    step is the same work in another form, then the steps that keep another form of their page."""
    got = _task_file(folder)
    if got is None:
        return []
    root, data = got
    steps = data.get("steps") or {}
    lines: list[str] = []
    for arrow in data.get("arrows") or []:
        if not isinstance(arrow, dict):
            continue
        a, b = str(arrow.get("from") or ""), str(arrow.get("to") or "")
        label = str(arrow.get("label") or "").strip()
        if not a or not b or not FORM.search(label):
            continue
        names = [f"`{k}`" + (f" ({t})" if (t := _step_title(steps, k)) else "") for k in (a, b)]
        lines.append(f"- {names[0]} and {names[1]} are the same work: the second "
                     f"“{label}”.")
    keys = list(steps) if isinstance(steps, dict) else []
    for key in keys:
        step = root / key
        try:
            if not (step / "index.html").is_file():
                continue
            files = sorted(p.name for p in step.iterdir()
                           if p.is_file() and p.suffix.lower() in KEPT_FORMS
                           and not OLD.search(p.stem.replace("-", " ").replace("_", " ")))
        except OSError:
            continue
        if files:
            more = len(files) - MOST_FILES
            listed = ", ".join(f"`{n}`" for n in files[:MOST_FILES]) + (f" and {more} more" if more > 0 else "")
            lines.append(f"- `{key}` keeps its page and also {listed}: another form of the same "
                         "work, made again when the page changes.")
    return lines[:MOST]


def for_runs(org: str) -> str:
    """The section every run of this organisation is given after its agent instructions, or ""
    (off)."""
    try:
        if not org or not on(org):
            return ""
        return "## Copies kept in step\n\n" + RULE
    except Exception:  # noqa: BLE001 - a run starts whatever this says
        log.exception("copies kept in step could not be put in a run's instructions")
        return ""


def for_task(folder: str, org: str = "") -> str:
    """The copies in the run's own task, for after the task in play, or "" (off, or none)."""
    try:
        if not folder or not on(org or None):
            return ""
        from .config import config

        root = str(getattr(config, "assistant_repo", "") or "")
        if not root:
            return ""
        lines = found(Path(root) / folder)
        if not lines:
            return ""
        from . import evolution

        evolution.used(SWITCH, "copies_named", detail=f"{len(lines)} in workspace/{folder}")
        return ("Copies of the same work in this task. A change you make to one of these is made to "
                "the other too, unless the person named only one:\n\n" + "\n".join(lines))
    except Exception:  # noqa: BLE001 - a run starts whatever this says
        log.exception("the copies in %s could not be read", folder)
        return ""


__all__ = ["FORM", "RULE", "SWITCH", "TITLE", "for_runs", "for_task", "found", "on"]
