"""A step of the person's workspace: one markdown file that is both faces.

The canvas used to be a stream of its own, kept in Rouh's database, beside a
workspace of numbered task folders kept on disk. Two permanent stores, and a
card that mattered had to be written out a second time by hand to reach the one
that survives. This module is the other half of the answer: a step is a single
plain-text file, and the page and the source are the same file read two ways.

The file
--------

A step folder may hold a ``step.md``:

    ---
    task: 30.jarvis
    step: 30-06
    title: Two permanent stores is the bug
    state: decided
    ---

    ## Decision

    The task folder is the record.

    :::stat
    label: Permanent stores
    value: one
    :::

Front matter between two lines of ``---`` carries ``task``, ``step``, ``title``
and ``state``. What follows is ordinary markdown, with blocks fenced by lines
of three colons, or more where a block's own body holds a line of them. The
block names are the ones the canvas already draws, so nothing new had to be
taught to the page: stat, table, list, text, code, chart, link, image, html,
contact and sources (``renderBlock`` in static/app.js). A ``sources`` block is
one page an item, its title and then its address after the last ``|``.

Inside a fence there are two shapes, and which one a block uses is fixed:

- ``code``, ``html`` and ``text`` take their body verbatim, because a line of
  code or of markup is not a field and must not be read as one. Anything after
  the block's name on the fence line is the language for ``code`` and the title
  for the other two.
- every other block takes ``key: value`` lines and ``- item`` lines. A row of a
  table or a bar of a chart is an item whose cells are split on ``|``. Anything
  after the block's name on the fence line is the block's title.
- ``contact`` is a person from the iCloud contacts as save_contact showed them
  (``apple_contacts.contact_card``): the name on the fence line, and one item
  per field, ``- kind | label | value | change | was``. Its values are anybody's
  words, so a ``|``, a backslash or a line break in one is written with a
  backslash before it, and read back as it was.

Prose between fences becomes a ``text`` block, which the page renders as
markdown. So a file with no fences at all is still a page, and a page is never
emptier than the file.

Why plain text is a hard requirement
------------------------------------

The record has to survive Rouh being off. A step is greppable with grep,
diffable with git, and readable in any editor with nothing running, which none
of a database row, a JSON payload or a built HTML page is. That is also why
nothing here writes HTML: the rendered page is made from the file on every
request and kept nowhere.

Where the truth is
------------------

**The row is the record and this file is written out from it.** Since
``rouh/artifacts.py`` a card, a numbered step and a built page are all one
``artifact`` row with its versions, and ``file_step`` and ``rewrite_step``
below are how such a row reaches the disk. Nothing here is read back in as the
truth: where the file and the row disagree the row wins, and a file somebody
edited by hand is an inbound change to reconcile rather than an override.

That is not a demotion of the file. It is still plain text, still greppable and
diffable, and still readable with nothing running, which is the whole reason
this format exists. It is a second face of the record rather than a second
record.

Living beside the pages that are already there
----------------------------------------------

Most steps in the workspace today are a folder holding ``index.html``, built by
the visual explainer. Those are not touched and not converted: ``index.html``
is served exactly as it always was, in its own sandboxed frame (``pages.py``),
and a step that has one is shown that way. ``step.md`` is what a step made from
now on is written as. A folder may hold both, and then the markdown is the page
and the HTML is still there to open full screen.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path

from . import instructions, objects, pages, taskrecord

log = logging.getLogger("rouh.steps")

#: The file inside a step folder that holds the step. One name, so finding a
#: step is a stat rather than a search.
STEP_FILE = "step.md"

#: The blocks a fence may name. The same set the canvas draws, in the same
#: order the tool that writes a card describes them.
BLOCKS = ("stat", "table", "list", "text", "code", "chart", "link", "image", "html",
          "contact", "sources")

#: The three whose body is taken verbatim. See the module docstring.
VERBATIM = ("code", "html", "text")

#: The fields front matter may carry. Anything else in it is kept and handed
#: back, so a file that says more than this module knows about is not thinned
#: out by being read.
FRONT = ("task", "step", "title", "state")

#: A fence is three or more colons, and a longer one is how a block whose body
#: contains a line of colons is written without the body closing it early. The
#: closing fence is at least as long as the opening one, which is the rule
#: markdown's own fenced blocks keep.
_FENCE = re.compile(r"^(:{3,})[ \t]*([A-Za-z][A-Za-z0-9_-]*)[ \t]*(.*?)[ \t]*$")
_COLONS = re.compile(r"^(:{3,})[ \t]*$")
_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.*)$")
_ITEM = re.compile(r"^-[ \t]+(.*)$")
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t]*#*$")

#: A step folder's numbers, the same shape pages.py already reads.
_STEP_FOLDER = re.compile(r"^(\d+)-(\d+)[.-](.+)$")
_TASK_FOLDER = re.compile(r"^(\d+)[.-](.+)$")

#: A task's own folder: a number, a dot, a name. `38-01.soil` is a step and
#: not this, because its third character is a dash.
_TASK_NAME = re.compile(r"^(\d+)\.(.+)$")

#: How deep inside the workspace anything here will reach. Two was the whole
#: answer while a task was `tasks/NN.name` and a step one folder inside it.
#: Since the tree was reshaped on 21 September 2026 a task is under whatever
#: projects own it - `work/acme/06.hiring-devs` - so the depth is a range
#: and what says whether a path names a task or a step is the shape of its
#: last folder's name rather than how many parts it has.
MAX_PARTS = 6


def task_part(rel: str) -> str:
    """The task a path is in: up to and including its numbered task folder.

    `work/acme/19.pricing/19-04.packages` is in `work/acme/19.pricing`,
    and so is every file under it. A path with no numbered folder in it at all
    falls back to its first two parts, which is what a flat workspace's paths
    are and what this always used to return.
    """
    parts = [p for p in str(rel or "").split("/") if p]
    for at, part in enumerate(parts):
        if _TASK_NAME.match(part):
            return "/".join(parts[:at + 1])
    return "/".join(parts[:2])


def is_step(rel: str) -> bool:
    """Whether this workspace path names a step of a task rather than a task.

    The shape of the last folder's name and nothing else: `19-04.packages` is
    a step because its number is followed by a dash, `19.pricing` is a task
    because it is followed by a dot. It is the rule `task_part` above already
    keeps, asked from the other end, and `rouh/searching.py` asks it so that a
    step reached by its own address opens the page it built rather than the
    browser's listing of what is under it.
    """
    parts = [p for p in str(rel or "").split("/") if p]
    return bool(parts) and bool(_STEP_FOLDER.match(parts[-1]))


class Refused(ValueError):
    """A step that may not be read or written, said in one sentence."""


# --- reading ---------------------------------------------------------------


def _front_matter(text: str) -> tuple[dict, str]:
    """The front matter and the rest, or an empty front matter and the whole.

    A file that does not open with ``---`` is not an error: it is a step
    somebody wrote by hand and it still renders. The front matter only ever
    adds what the folder's own name cannot say.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            front: dict = {}
            for line in lines[1:i]:
                found = _FIELD.match(line)
                if found:
                    front[found.group(1).lower()] = found.group(2).strip()
            return front, "\n".join(lines[i + 1:])
    # An opening fence with no closing one. Reading the whole file as front
    # matter would empty the page, so it is read as prose instead.
    return {}, text


def _fields(body: list[str]) -> tuple[dict, list[str]]:
    """The ``key: value`` lines and the ``- item`` lines of one fence."""
    fields: dict = {}
    items: list[str] = []
    for line in body:
        if not line.strip():
            continue
        item = _ITEM.match(line.strip())
        if item:
            items.append(item.group(1).strip())
            continue
        found = _FIELD.match(line.strip())
        if found:
            fields[found.group(1).lower()] = found.group(2).strip()
    return fields, items


def _cells(item: str) -> list[str]:
    """One row of a table or one bar of a chart, split on the pipe."""
    return [cell.strip() for cell in item.split("|")]


def _escaped(value) -> str:
    """One cell of a contact's field, safe to put between pipes on one line."""
    text = str("" if value is None else value).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n").strip()


def _escaped_cells(item: str) -> list[str]:
    """A contact's field split on the pipes `_escaped` did not write."""
    cells, cell, i = [], [], 0
    while i < len(item):
        char = item[i]
        if char == "\\" and i + 1 < len(item):
            nxt = item[i + 1]
            cell.append("\n" if nxt == "n" else nxt)
            i += 2
            continue
        if char == "|":
            cells.append("".join(cell).strip())
            cell = []
        else:
            cell.append(char)
        i += 1
    cells.append("".join(cell).strip())
    return cells


def _number(raw: str):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _block(name: str, info: str, body: list[str]) -> dict | None:
    """One fence as the block the canvas draws, or nothing if it is empty."""
    if name in VERBATIM:
        text = "\n".join(body).strip("\n")
        if not text.strip():
            return None
        if name == "code":
            out = {"block": "code", "text": text}
            if info:
                out["language"] = info
            return out
        if name == "html":
            out = {"block": "html", "html": text}
            if info:
                out["title"] = info
            return out
        return {"block": "text", "text": text}

    fields, items = _fields(body)
    if name == "stat":
        if not fields.get("label") and not fields.get("value"):
            return None
        out = {"block": "stat", "label": fields.get("label", ""),
               "value": fields.get("value", "")}
        if fields.get("hint"):
            out["hint"] = fields["hint"]
        return out
    if name == "list":
        if not items:
            return None
        return {"block": "list", "items": items}
    if name == "table":
        rows = [_cells(item) for item in items]
        columns = _cells(fields["columns"]) if fields.get("columns") else []
        if not rows and not columns:
            return None
        out = {"block": "table", "columns": columns, "rows": rows}
        if info or fields.get("title"):
            out["title"] = info or fields["title"]
        return out
    if name == "chart":
        points = []
        for item in items:
            cells = _cells(item)
            value = _number(cells[1]) if len(cells) > 1 else None
            points.append({"label": cells[0], "value": 0.0 if value is None else value})
        if not points:
            return None
        out = {"block": "chart", "points": points}
        if info or fields.get("title"):
            out["title"] = info or fields["title"]
        if fields.get("kind"):
            out["kind"] = fields["kind"]
        return out
    if name == "link":
        if not fields.get("href"):
            return None
        return {"block": "link", "href": fields["href"],
                "text": fields.get("text") or info or fields["href"]}
    if name == "image":
        if not fields.get("src"):
            return None
        out = {"block": "image", "src": fields["src"], "alt": fields.get("alt", "")}
        if fields.get("caption") or info:
            out["caption"] = fields.get("caption") or info
        return out
    if name == "contact":
        if not info and not items:
            return None
        rows = []
        for item in items:
            kind, label, value, change, was = (_escaped_cells(item) + [""] * 5)[:5]
            row = {"kind": kind, "label": label, "value": value}
            if change:
                row["change"] = change
            if was:
                row["was"] = was
            rows.append(row)
        out = {"block": "contact", "name": info, "state": fields.get("state", ""),
               "new": fields.get("new", "") == "yes", "status": fields.get("status", ""),
               "rows": rows, "foot": fields.get("foot", "")}
        for key, field in (("was", "was_name"), ("remark", "remark")):
            if fields.get(key):
                out[field] = fields[key]
        return out
    if name == "sources":
        # One page a line, its title and then its address after the last pipe,
        # because a title may have a pipe in it and an address never does.
        pages = []
        for item in items:
            title, _, url = item.rpartition("|")
            if url.strip():
                pages.append({"url": url.strip(), "title": title.strip()})
        return {"block": "sources", "sources": pages} if pages else None
    return None


def blocks(text: str) -> list[dict]:
    """Every block of a step's body, prose included, in the file's own order."""
    out: list[dict] = []
    prose: list[str] = []

    def flush() -> None:
        said = "\n".join(prose).strip("\n")
        prose.clear()
        if said.strip():
            out.append({"block": "text", "text": said})

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        found = _FENCE.match(lines[i])
        if not found or found.group(2).lower() not in BLOCKS:
            prose.append(lines[i])
            i += 1
            continue
        fence = len(found.group(1))
        name = found.group(2).lower()
        info = found.group(3).strip()
        body: list[str] = []
        i += 1
        while i < len(lines):
            shut = _COLONS.match(lines[i])
            if shut and len(shut.group(1)) >= fence:
                break
            body.append(lines[i])
            i += 1
        # A fence nobody closed runs to the end of the file rather than
        # swallowing the page into a block that is never drawn.
        i += 1
        flush()
        made = _block(name, info, body)
        if made is not None:
            out.append(made)
    flush()
    return out


def first_heading(text: str) -> str:
    """The first markdown heading of a body, for a step with no title."""
    for line in text.split("\n"):
        found = _HEADING.match(line.strip())
        if found:
            return found.group(1).strip()
    return ""


def parse(text: str) -> dict:
    """One step file, read: its front matter, its blocks and its own text."""
    front, body = _front_matter(text)
    known = {key: front.get(key, "") for key in FRONT}
    extra = {k: v for k, v in front.items() if k not in FRONT}
    return {
        **known,
        "extra": extra,
        "title": known["title"] or first_heading(body),
        "blocks": blocks(body),
        "source": text,
    }


# --- writing ---------------------------------------------------------------


def _fence_for(body: str) -> str:
    """A fence at least one colon longer than anything the body could close with.

    Three colons nearly always. A block holding a line of three colons of its
    own - a step file quoted inside a step file, which is exactly what a page
    about this format does - gets four, and the parser closes on a fence at
    least as long as the one it opened with.
    """
    longest = 0
    for line in body.split("\n"):
        found = _COLONS.match(line)
        if found:
            longest = max(longest, len(found.group(1)))
    return ":" * max(3, longest + 1)


def _line(value) -> str:
    """One value on one line, with the newlines a field may not carry taken out."""
    return re.sub(r"\s+", " ", str("" if value is None else value)).strip()


def block_text(block: dict) -> str:
    """One block of a card as the fence that reads back to the same block.

    The round trip is the point: a card filed as a step and read back has to
    draw the same thing, or the file has quietly become a lossy copy of the
    card rather than the card's only home.
    """
    if not isinstance(block, dict):
        return ""
    name = str(block.get("block") or "").lower()
    if name == "email":
        # An email as it arrived (`mail_alerts.email_card`). Filed, it is what
        # it said, kept word for word in a code fence, which a step reads back
        # as exactly those lines and never as markup: every word is the
        # sender's.
        head = [f"{label}: {_line(block.get(key))}"
                for label, key in (("From", "from"), ("To", "to"), ("Cc", "cc"),
                                   ("Date", "date"), ("Subject", "subject"))
                if _line(block.get(key))]
        body = ("\n".join(head) + "\n\n" + str(block.get("body") or "").strip("\n")).strip("\n")
        edge = _fence_for(body)
        return f"{edge}code email\n{body}\n{edge}\n"
    if name in ("people", "profile") and block.get("source") == "linkedin":
        # People found on LinkedIn, and one person's harvested profile
        # (`rouh/linkedin.py`). Filed, they are what they said: the people as
        # a list, the profile as prose. Imported here because linkedin reads
        # cards through artifacts, which imports this module.
        from . import linkedin

        return linkedin.block_text(block)
    if name not in BLOCKS:
        return ""
    if name == "text":
        said = str(block.get("text") or "").strip("\n")
        # Prose needs no fence: it is what everything between fences already is.
        return said + "\n" if said.strip() else ""
    if name == "code":
        info = _line(block.get("language"))
        body = str(block.get("text") or "").strip("\n")
        edge = _fence_for(body)
        return f"{edge}code{(' ' + info) if info else ''}\n{body}\n{edge}\n"
    if name == "html":
        info = _line(block.get("title"))
        body = str(block.get("html") or block.get("text") or "").strip("\n")
        edge = _fence_for(body)
        return f"{edge}html{(' ' + info) if info else ''}\n{body}\n{edge}\n"
    if name == "stat":
        out = [":::stat", f"label: {_line(block.get('label'))}",
               f"value: {_line(block.get('value'))}"]
        if block.get("hint"):
            out.append(f"hint: {_line(block['hint'])}")
        return "\n".join(out) + "\n:::\n"
    if name == "list":
        items = [i for i in (block.get("items") or []) if _line(i)]
        if not items:
            return ""
        return ":::list\n" + "".join(f"- {_line(i)}\n" for i in items) + ":::\n"
    if name == "table":
        info = _line(block.get("title"))
        out = [f":::table{(' ' + info) if info else ''}"]
        columns = [_line(c) for c in (block.get("columns") or [])]
        if columns:
            out.append("columns: " + " | ".join(columns))
        for row in block.get("rows") or []:
            cells = row if isinstance(row, list) else [row]
            out.append("- " + " | ".join(_line(c) for c in cells))
        return "\n".join(out) + "\n:::\n"
    if name == "chart":
        info = _line(block.get("title"))
        out = [f":::chart{(' ' + info) if info else ''}"]
        if block.get("kind"):
            out.append(f"kind: {_line(block['kind'])}")
        for point in block.get("points") or []:
            if isinstance(point, dict):
                out.append(f"- {_line(point.get('label'))} | {_line(point.get('value'))}")
        return "\n".join(out) + "\n:::\n"
    if name == "link":
        if not block.get("href"):
            return ""
        out = [":::link", f"href: {_line(block['href'])}"]
        if block.get("text"):
            out.append(f"text: {_line(block['text'])}")
        return "\n".join(out) + "\n:::\n"
    if name == "image":
        if not block.get("src"):
            return ""
        out = [":::image", f"src: {_line(block['src'])}"]
        if block.get("alt"):
            out.append(f"alt: {_line(block['alt'])}")
        if block.get("caption"):
            out.append(f"caption: {_line(block['caption'])}")
        return "\n".join(out) + "\n:::\n"
    if name == "contact":
        out = [f":::contact {_line(block.get('name'))}".rstrip()]
        for key, field in (("state", "state"), ("status", "status"), ("was", "was_name"),
                           ("remark", "remark"), ("foot", "foot")):
            if block.get(field):
                out.append(f"{key}: {_line(block[field])}")
        if block.get("new"):
            out.append("new: yes")
        for row in block.get("rows") or []:
            if isinstance(row, dict):
                cells = [_escaped(row.get(k)) for k in ("kind", "label", "value", "change",
                                                         "was")]
                while cells and not cells[-1]:
                    cells.pop()
                out.append("- " + " | ".join(cells))
        return "\n".join(out) + "\n:::\n"
    if name == "sources":
        rows = [f"- {_line(p.get('title'))} | {_line(p.get('url'))}"
                for p in (block.get("sources") or [])
                if isinstance(p, dict) and _line(p.get("url"))]
        return ":::sources\n" + "\n".join(rows) + "\n:::\n" if rows else ""
    return ""


def compose(task: str, step: str, title: str, block_list, state: str = "") -> str:
    """A whole step file from a card's blocks."""
    front = ["---", f"task: {_line(task)}", f"step: {_line(step)}",
             f"title: {_line(title)}"]
    if state:
        front.append(f"state: {_line(state)}")
    front.append("---")
    body = [block_text(b) for b in (block_list or [])]
    return "\n".join(front) + "\n\n" + "\n".join(part for part in body if part)


# --- the workspace ---------------------------------------------------------


def _words(folder: str) -> str:
    """A folder's name as words, the way the task list says them.

    A step folder is tried first: "30-37.one-way-to-deploy" matches the task
    pattern too, and taking that match leaves "37.one way to deploy".
    """
    found = _STEP_FOLDER.match(folder) or _TASK_FOLDER.match(folder)
    if found:
        raw = found.group(len(found.groups()))
    else:
        raw = folder
    raw = raw.replace("-", " ").replace("_", " ").strip()
    return raw[:1].upper() + raw[1:] if raw else folder


def _folder(root, rel: str, want: str) -> Path:
    """The folder ``rel`` names, if it may be read, or Refused saying why.

    This does not go through ``pages.check``, and the reason matters. That
    function serves files over ``/workspace/`` to a sandboxed frame, and it
    refuses every ``.md`` file outright, because a task's ``AGENTS.md`` is its
    whole internal record and must never leave as a page. A step's own file is
    markdown, so reading one here needs its own rules rather than a hole poked
    in those.

    The rules are these, and they are deliberately narrower than that route's:

    - ``workspace.resolve`` runs first, exactly as ``read_workspace`` runs it,
      so ``.git``, an ``.env``, a key and anything a link leads out of the
      workspace to are refused as asked and again after the links are followed
    - the top folder is one of ``pages.TOPS`` and nothing else
    - no part of the path starts with a dot, at any depth
    - it is between two and ``MAX_PARTS`` parts deep, so nothing here can be
      pointed at the workspace root or at ``_context/``
    - and its last folder is shaped like the thing being asked for: ``NN.name``
      for a task, ``NN-MM.name`` or ``NN-name`` for a step. That is what used
      to be said by counting the parts, and counting stopped saying it when a
      task moved under the projects that own it
    - and nothing here serves a file to anybody. What it reads goes back as
      JSON to Rouh's own signed-in page.
    """
    from . import workspace

    asked = str(rel or "").strip().strip("/")
    if not asked:
        raise Refused("No task was named.")
    if asked.startswith("/") or "\\" in asked or "\x00" in asked or "%" in asked:
        raise Refused(f"{asked} is not a plain path inside the workspace.")
    parts = asked.split("/")
    _check_shape(parts, asked, want)
    base = Path(root).resolve()
    try:
        target = workspace.resolve(base, asked)
    except workspace.Refused as exc:
        raise Refused(str(exc)) from exc
    inside = target.relative_to(base).parts
    _check_shape(list(inside), asked, want)
    if not target.is_dir():
        raise Refused(f"There is no folder at {asked} in the workspace.")
    return target


def _check_shape(parts: list[str], asked: str, want: str) -> None:
    """The rules above, on a path as asked and again on where its links led."""
    if not (2 <= len(parts) <= MAX_PARTS):
        raise Refused(f"{asked} is not a task or a step of one.")
    for part in parts:
        if not part or part.startswith("."):
            raise Refused(f"{asked} has an empty part or a hidden one in it.")
    if parts[0] not in pages.TOPS:
        raise Refused(
            f"{asked} is not under one of {', '.join(pages.TOPS)}, and only "
            "those are read.")
    last = parts[-1]
    if want == "task" and not _TASK_NAME.match(last):
        raise Refused(f"{asked} does not name a task: a task folder is NN.name.")
    if want == "step" and (_TASK_NAME.match(last) or not _TASK_FOLDER.match(last)):
        raise Refused(f"{asked} does not name a step of a task.")


def _task_folder(root, rel: str) -> Path:
    """The folder of ``work/acme/19.pricing``, or of ``tasks/30.jarvis``."""
    return _folder(root, rel, "task")


def _step_folder(root, rel: str) -> Path:
    """The folder of ``work/acme/19.pricing/19-04.packages``."""
    return _folder(root, rel, "step")


#: A step folder's name starts with its number. Which is also what says a
#: folder inside a task is **not** a step: `source-code`, `images`, `results`,
#: `context` and `vendor` hold something a step made, and listing them as
#: steps of the task put "Source code" in the canvas's step list beside the
#: real ones. `objecttree.STEP_NAME` is the same rule, said once there.
_STEP_NAME = re.compile(r"^\d+[-.]")


def _steps_of(folder: Path) -> list[str]:
    try:
        names = [s.name for s in folder.iterdir()
                 if s.is_dir() and not s.name.startswith(".")
                 and _STEP_NAME.match(s.name)]
    except OSError:
        return []
    return sorted(names, key=pages._step_key)


def _step_row(root: Path, task_rel: str, name: str, said: dict | None = None) -> dict:
    """One step of a task, as the canvas lists it.

    Its title is its `step.md`'s, else the one its task's meta gives
    it (``said``, by folder name), which is where the workspace writes a
    step's name and what the step's own page calls it
    (`objectindex._step_title`), else its page's `<title>`. The `<title>` came
    before the task's own word for it until 24 September 2026, and the breadcrumb over
    61-01's page said "Acme site and copy" while the page under it said
    "The site plan and Sam's copy, as a site to click through".
    """
    folder = root / task_rel / name
    has_md = (folder / STEP_FILE).is_file()
    has_html = (folder / "index.html").is_file()
    has_notes = any(not instructions.is_instructions(p.name)
                    and not p.name.startswith((".", "_"))
                    for p in folder.glob("*.md"))
    title = ""
    state = ""
    if has_md:
        try:
            read = parse((folder / STEP_FILE).read_text(encoding="utf-8", errors="replace"))
            title, state = read["title"], read["state"]
        except OSError:
            pass
    written = (said or {}).get(name)
    if not title and isinstance(written, dict):
        title = str(written.get("title") or "").strip()
    if not title and has_html:
        title = pages.title_of(folder / "index.html")
    kind = "markdown" if has_md else ("page" if has_html else
                                      ("notes" if has_notes else "empty"))
    return {
        "rel": f"{task_rel}/{name}",
        "folder": name,
        "number": number_of(name),
        "title": title or _words(name),
        "state": state,
        "kind": kind,
        "page": f"{task_rel}/{name}/index.html" if has_html else "",
    }


def listed_steps(folder: Path) -> dict:
    """What a task's meta says about each of its steps, by folder name (`rouh/taskmeta.py`)."""
    from . import taskmeta

    return taskmeta.steps_of(folder)


def _archived_folders() -> set[str]:
    """Where every archived task and step is (`rouh/archiving.py`); empty when that cannot be read."""
    from . import archiving

    try:
        return archiving.archived_folders()
    except Exception:                     # the lists are worth more than the mark
        log.exception("which folders are archived could not be read")
        return set()


def task_detail(root, rel: str) -> dict:
    """One task and its steps: the step level of the canvas's breadcrumb.

    The title, where it is on disk, how many steps it has and what state it is
    in, then every step newest first. Read off the workspace on every request,
    like everything else here, so a step written a minute ago is on the list.
    """
    base = Path(root).resolve()
    folder = _task_folder(base, rel)
    task_rel = str(folder.relative_to(base)).replace(os.sep, "/")
    names = _steps_of(folder)
    said = listed_steps(folder)
    steps = [_step_row(base, task_rel, name, said) for name in reversed(names)]
    # An archived step keeps its line, so the bar can still name it while it
    # is open, and says so: the menu of its siblings leaves it out (`runs.js`).
    shelved = _archived_folders()
    for step in steps:
        step["archived"] = step["rel"] in shelved
    found = _TASK_FOLDER.match(folder.name)
    return {
        "rel": task_rel,
        "number": int(found.group(1)) if found else None,
        "name": _title_of(base, folder),
        "path": str(folder),
        # The row's, in five words: never the file's (`rouh/taskrecord.py`).
        "status": taskrecord.status_at(folder, base),
        "steps": steps,
        "step_count": len(steps),
    }


def pages_in(root, rel: str) -> dict:
    """What a task, or one step of it, is, and every page it has.

    What "the whole task" is when it is made public (`sharing.py`)::

        {"kind": "task" or "step", "rel": its path, "task": the task's path,
         "number": "56" or "56-01", "name": its name in words,
         "pages": [{"rel", "step", "title"}, ...]}

    The pages are the built pages sitting in the task itself and in each of
    its steps, oldest step first, with ``step`` the step's number or "" for a
    page of the task's own. Within one place its ``index.html`` comes first,
    because that is the page the step built and anything beside it is a page
    it links to.

    Never what is inside a step's own folders - ``source-code``, ``images``
    and the rest hold what a step was made from, not what it made - and never
    a task inside this one, which is a task of its own and is published as
    one. A ``step.md`` is not here either: it has no built page on disk, and
    a page on disk is the only thing the public address serves.
    """
    base = Path(root).resolve()
    parts = [p for p in str(rel or "").split("/") if p]
    want = "task" if parts and _TASK_NAME.match(parts[-1]) else "step"
    folder = _folder(base, rel, want)
    own = str(folder.relative_to(base)).replace(os.sep, "/")
    if want == "task":
        # `_folder` has already said this name is NN.name.
        number = str(int(_TASK_NAME.match(folder.name).group(1)))
        places = [(own, "")] + [(f"{own}/{name}", number_of(name))
                                for name in _steps_of(folder)
                                if not _TASK_NAME.match(name)]
    else:
        number = number_of(folder.name)
        places = [(own, number)]
    out: list[dict] = []
    for place, step in places:
        try:
            names = [p.name for p in (base / place).iterdir()
                     if p.is_file() and p.name.lower().endswith(".html")
                     and not p.name.startswith((".", "_"))]
        except OSError:
            continue
        for name in sorted(names, key=lambda n: (n.lower() != "index.html", n.lower())):
            out.append({"rel": f"{place}/{name}", "step": step,
                        "title": pages.title_of(base / place / name) or _words(name[:-5])})
    return {
        "kind": want,
        "rel": own,
        "task": own if want == "task" else own.rsplit("/", 1)[0],
        "number": number,
        "name": _title_of(base, folder),
        "pages": out,
    }


def _title_of(base: Path, folder: Path) -> str:
    """A task's or a step's own title, as the task list shows it.

    The one written in its ``.object.json``, which keeps the capitals the
    person gave it - "Films this weekend" - where the folder's name has none
    to keep. The name in words when it has no sidecar, or one that cannot be
    read.
    """
    from . import objecttree

    try:
        said = (objecttree.read_sidecar(folder, base) or {}).get("title")
    except (OSError, ValueError):
        said = ""
    return said.strip() if isinstance(said, str) and said.strip() else _words(folder.name)


def number_of(name: str) -> str:
    """A step's number as the person says it, from its folder's name."""
    found = _STEP_FOLDER.match(name)
    return f"{found.group(1)}-{found.group(2)}" if found else name.split(".")[0]


def read_step(root, rel: str) -> dict:
    """One step: the page it has, and the text behind it.

    ``page`` decides how the canvas loads it. A step built the old way has an
    ``index.html`` and is framed; a step Rouh filed as a ``step.md`` has
    none, and the blocks here are what the canvas draws instead.
    """
    base = Path(root).resolve()
    folder = _step_folder(base, rel)
    step_rel = str(folder.relative_to(base)).replace(os.sep, "/")
    md = folder / STEP_FILE
    html = folder / "index.html"
    out = {
        "rel": step_rel,
        "task": task_part(step_rel),
        "folder": folder.name,
        "title": "",
        "state": "",
        "blocks": [],
        "source": "",
        "source_name": "",
        "page": f"{step_rel}/index.html" if html.is_file() else "",
    }
    if md.is_file():
        text = md.read_text(encoding="utf-8", errors="replace")
        read = parse(text)
        out.update(title=read["title"], state=read["state"], blocks=read["blocks"],
                   source=text, source_name=STEP_FILE, kind="markdown")
        return out

    # A step built the old way has no source of its own. Its notes are the
    # nearest thing, and saying which file is being read matters: what is
    # promised is the text behind the page, and for these it is the text
    # beside it.
    #
    # Never an AGENTS.md (or the CLAUDE.md it was called until 26 September
    # 2026) and never a name starting with a dot or an underscore.
    # A task's AGENTS.md is its whole internal record, and the rule that it is
    # not shown is the same one `pages.py` keeps: a step folder is not where
    # one lives, and this makes sure that stays true even if somebody puts one
    # there.
    notes = sorted(p for p in folder.glob("*.md")
                   if not instructions.is_instructions(p.name)
                   and not p.name.startswith((".", "_")))
    if notes:
        out["source"] = notes[0].read_text(encoding="utf-8", errors="replace")[:200_000]
        out["source_name"] = notes[0].name
    if html.is_file():
        out["kind"] = "page"
        out["title"] = pages.title_of(html) or _words(folder.name)
        return out
    out["kind"] = "notes" if notes else "empty"
    out["title"] = first_heading(out["source"]) or _words(folder.name)
    return out


# --- the index -------------------------------------------------------------

def summaries(root=None) -> dict[str, str]:
    """Every numbered task's summary, by folder name, out of the rows.

    The index is the person's own list of what each task is. Until 6 October
    2026 that was a paragraph each in `_tasks.md`, read back off the file here;
    the file is generated out of the rows since (`rouh/tasklist.py`), so the
    words are read where it reads them, from each task's `summary`, which the
    row takes in from its meta (`conversations.reconcile`).
    """
    store = objects.shared_store(even_when_off=True)
    if store is None:
        return {}
    try:
        rows = store.list_tasks(limit=1_000_000)
    except Exception:
        log.exception("the tasks' summaries could not be read")
        return {}
    return {row.folder.rsplit("/", 1)[-1]: row.summary for row in rows
            if row.folder and row.number is not None and row.summary}


def _changed(folder: Path) -> float:
    """When a task last changed: the newest of its folder and its own record.

    Two stats rather than a walk of every step. Adding a step changes the
    folder, and writing anything down in the task's record changes that file,
    so between them they catch what a person means by "last change" without
    reading sixty task folders through on every press of index.
    """
    newest = 0.0
    for path in (folder, instructions.in_folder(folder)):
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def task_folders(root) -> list[Path]:
    """Every numbered task folder in the workspace, wherever it sits.

    A task was `tasks/NN.name` and is now under the projects that own it, so
    this walks each of `pages.TOPS` down to `MAX_PARTS` looking for a folder
    named `NN.name`. A task is never inside another task's folder: what is in
    there is its steps, and the walk stops as soon as it has found one.
    """
    base = Path(root).resolve()
    out: list[Path] = []

    def walk(folder: Path, depth: int) -> None:
        if depth > MAX_PARTS:
            return
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if _TASK_NAME.match(child.name):
                out.append(child)
            else:
                walk(child, depth + 1)

    for top in pages.TOPS:
        if (base / top).is_dir():
            walk(base / top, 2)
    return out


def task_rows(root) -> list[dict]:
    """Every task row, with the tree taken in first if it has not been yet.

    The import is what makes a row's folder true. Until 21 September 2026 a row
    said `tasks/30.jarvis` and that is where the folder was; the tree moved it,
    and a row that has not been brought up to date names a folder that is not
    there. `objecttree.ensure_imported` is what brings it up to date, it costs
    one query once the rows are right, and this is where it belongs: every
    reader of a task by number comes through here, not only the task browser.

    An empty list means there is nothing to answer from - no store, no rows, or
    no folder where any row says - and every caller falls back to the folders.
    """
    from . import objecttree

    base = Path(root).resolve()
    store = objects.shared_store(even_when_off=True)
    if store is None:
        return []
    try:
        objecttree.ensure_imported(base, store)
    except Exception:                     # a workspace that cannot be read is not fatal
        log.exception("the workspace at %s could not be taken in", base)
    return [row for row in store.objects()
            if row["type"] == "task" and row.get("folder")
            and (base / row["folder"]).is_dir()]


def numbered(root) -> dict[int, str]:
    """Every numbered task's folder, by its number, out of the database.

    **This is how a number becomes a place, and it is the only way.** A number
    is what the person says out loud - "open thirty" - and until 21 September
    2026 it was answered by scanning folder names for one starting with it.
    That was the same question being answered twice, by a walk on disk and by a
    row, and they disagreed the moment a folder was renamed; the row is what
    every other part of Rouh joins on, so the row wins.

    The folder on disk is where the files are read from, and nothing here
    invents one: a row whose folder is not there answers nothing, which is what
    tells the caller the workspace and the rows have come apart rather than
    handing back a path that cannot be opened.

    A machine whose object store will not open, or has nothing in it yet,
    falls back to the walk, because a task list is better than an error.
    """
    base = Path(root).resolve()
    out = {int(row["number"]): row["folder"] for row in task_rows(base)
           if row.get("number") is not None}
    if out:
        return out
    return {int(found.group(1)): str(folder.relative_to(base)).replace(os.sep, "/")
            for folder in task_folders(base)
            if (found := _TASK_FOLDER.match(folder.name))}


def folder_of(root, number: int) -> str:
    """Where task ``number`` is, or "" when no row names a folder that is there."""
    try:
        return numbered(root).get(int(number), "")
    except (TypeError, ValueError):
        return ""


def step_named(root, task_rel: str, number: str) -> str:
    """The step of ``task_rel`` numbered ``number``, as a path, or "".

    "30-06" is what the person says, and the folder is `30-06.whatever-it-is`.
    A step's number is not unique across the workspace - there are two `30-12`
    folders and two `30-20` - so a step is never looked up by number on its
    own: it is looked up inside the task whose number it starts with, which is
    the only place it means one thing. Where a task really does hold two
    folders with the same number, the last of them wins, which is the newer.
    """
    base = Path(root).resolve()
    try:
        folder = _task_folder(base, task_rel)
    except Refused:
        return ""
    want = str(number or "").strip()
    found = ""
    for name in _steps_of(folder):
        if name.split(".")[0] == want:
            found = f"{task_rel}/{name}"
    return found


def index_rows(root) -> list[dict]:
    """Every task in the workspace, with its state, its line and when it moved.

    This is where the person goes when they do not know the number. Which tasks
    there are, what each is called and what state it is in come from the rows;
    and its summary come from the rows too; how many steps it has and when it
    last moved are read off the folder the row names, because those are facts
    about files.
    """
    base = Path(root).resolve()
    said = summaries(base)
    shelved = _archived_folders()
    out: list[dict] = []
    rows = [row for row in task_rows(base) if row.get("number") is not None]
    if not rows:
        # No store, or nothing in it yet: the folders are all there is to
        # answer from, and an answer off the disk beats no task list at all.
        for folder in task_folders(base):
            found = _TASK_FOLDER.match(folder.name)
            rows.append({
                "folder": str(folder.relative_to(base)).replace(os.sep, "/"),
                "number": int(found.group(1)) if found else None,
                "title": _words(folder.name),
                # No row, so nothing to say how far along it is: a status is
                # kept in the row and nowhere else (`rouh/taskrecord.py`).
                "status": "",
            })
    for row in rows:
        rel = row.get("folder") or ""
        folder = base / rel
        if not rel or not folder.is_dir():
            continue
        try:
            steps = len(_steps_of(folder))
        except OSError:
            steps = 0
        out.append({
            "rel": rel,
            "folder": folder.name,
            "number": row["number"],
            "name": row["title"] or _words(folder.name),
            "status": row.get("status") or "",
            "said": said.get(folder.name, ""),
            "steps": steps,
            "changed": _changed(folder),
            # Kept on the list, and said, so whoever reads it decides: the
            # breadcrumb's menu of tasks leaves it out (`runs.js`).
            "archived": rel in shelved,
        })
    out.sort(key=lambda t: (-(t["number"] if t["number"] is not None else -1), t["rel"]))
    return out


# --- filing ----------------------------------------------------------------


def own_as_workspace(path: Path, root: Path) -> None:
    """Give what was just written to whoever owns the workspace.

    Rouh runs as root and the workspace belongs to the person's assistant. A
    root-owned file inside it is not a tidiness problem: it is what stopped
    ``git fetch`` and ``git commit`` dead in /srv/spaces/rouh on 18 September,
    because this server forbids a hard link to a file you do not own. So
    anything filed here is handed over the moment it is written, and a machine
    where that is not allowed simply leaves the file as it is rather than
    failing the filing.
    """
    try:
        owner = os.stat(root)
    except OSError:
        return
    if os.geteuid() != 0:
        return
    try:
        os.chown(path, owner.st_uid, owner.st_gid)
    except OSError:
        pass


def file_step(root, task_rel: str, title: str, block_list, state: str = "") -> dict:
    """Write a card into a task as its next numbered step.

    **The number, the row, the owner link, the folder and the sidecar all come
    from one place**, `objecttree.create`, which is the one create path in this
    repository since stage four: the row is written first, inside the same
    transaction as the `owns` link that says which task holds the step, and the
    folder and its `.object.json` are written out of that row. Until then this
    read the folder names beside it for the highest number it could see and
    made a directory, so a step existed on disk and nowhere else and the number
    came from a walk that a rename could change under it.

    What it does not do is commit, and it used to say that a timer kept this
    checkout level with main and the person's assistant committed what was
    filed. That timer went with the workspace's own repository on 21 September
    2026 and nothing committed anything after it, so a step or a task made here
    lived on the server alone, and a job working from main made its own under
    the same number. The save is `rouh/saving.py` now, told by the same create
    this calls (`objecttree.WRITTEN`), on the server whose settings say so.
    """
    from . import artifacts, objecttree

    base = Path(root).resolve()
    folder = _task_folder(base, task_rel)
    task_rel = str(folder.relative_to(base)).replace(os.sep, "/")
    store = objects.shared_store(even_when_off=True)
    if store is None:
        raise Refused("There is no object store open, so a step cannot be numbered.")
    # Which task owns the step, out of the rows and not out of the path. The
    # tree is taken in first, so a task folder somebody made by hand is a row
    # by the time this asks; a folder no row knows about at all - a workspace
    # that was never reshaped - falls back to the row `artifacts` makes.
    objecttree.ensure_imported(base, store)
    owner = next((row["id"] for row in store.objects()
                  if row["type"] == "task" and row.get("folder") == task_rel), "")
    owner = owner or artifacts.ensure_task(task_rel) or ""
    if not owner:
        raise Refused(f"{task_rel} has no row, so nothing can be filed into it.")
    made = objecttree.create(base, store, type="task", title=title, owner=owner)
    name = made["name"]
    number = name.split(".")[0]
    target = base / made["rel"] / STEP_FILE
    target.write_text(compose(folder.name, number, title, block_list, state),
                      encoding="utf-8")
    own_as_workspace(target, base)
    # The step's own words are on disk now, and the index was rebuilt a moment
    # ago against a folder with nothing in it, so it is rebuilt again with them
    # in it. The task comes too, because its meta names the step: that
    # line was written by `objecttree.create`, which is where the workspace's
    # rule about a step being in that file is kept.
    objecttree.refresh(base, store, [made["id"], owner])
    return {"rel": made["rel"], "number": number, "folder": name,
            "task": task_rel, "path": str(target), "id": made["id"]}


def rewrite_step(root, step_rel: str, title: str, block_list, state: str = "") -> dict:
    """Write a step that is already there again, from what it now says.

    A revision of an artifact never overwrites its history - every version is a
    row of its own - but the file under ``tasks/`` is the derived half and has
    only ever said one thing at a time, so it is written again from the version
    that has just been added. Where the two disagree the row wins, which is
    what makes this a write and not a merge.

    Refuses a folder that is not there, because writing one from here would be
    this function deciding a step exists, which is ``file_step``'s job.
    """
    base = Path(root).resolve()
    folder = _step_folder(base, step_rel)
    name = folder.name
    found = _STEP_FOLDER.match(name)
    number = f"{found.group(1)}-{found.group(2)}" if found else name
    task = folder.parent.name
    target = folder / STEP_FILE
    target.write_text(compose(task, number, title, block_list, state), encoding="utf-8")
    own_as_workspace(target, base)
    step_rel = str(folder.relative_to(base)).replace(os.sep, "/")
    return {"rel": step_rel, "number": number, "folder": name,
            "task": str(folder.parent.relative_to(base)).replace(os.sep, "/"),
            "path": str(target)}


def note_step(folder: Path, name: str, title: str, root: Path,
              description: str | None = None) -> None:
    """Put the new step in its task's list of steps, where the task keeps one.

    The workspace's own rule is that a step missing from that list lands in a
    "Not in a group yet" column on the task's page. A task that keeps no list
    (its meta is None) is given none: making one
    here would be Rouh deciding a task should have the machinery, which is the
    person's call. ``description`` is what a step moved in from another task
    was said to be there. The list is the task's row's (`rouh/taskmeta.py`).
    """
    from . import taskmeta

    def put(meta):
        if meta is None:
            return None
        steps = meta.get("steps")
        if not isinstance(steps, dict):
            steps = {}
            meta["steps"] = steps
        steps[name] = {"title": title, "description": description or title}
        return meta

    taskmeta.change(folder, put, root)


def retitle_step(folder: Path, name: str, title: str, root: Path) -> bool:
    """A renamed step's new title, where its task's list of steps names it.

    Only a step the list already names: one it does not is drawn under its
    own folder's words, and a task with no list keeps none. True when the
    title was changed.
    """
    from . import taskmeta

    done = []

    def put(meta):
        steps = meta.get("steps") if isinstance(meta, dict) else None
        said = steps.get(name) if isinstance(steps, dict) else None
        if not isinstance(said, dict) or said.get("title") == title:
            return meta
        # A description that only repeated the old name (`note_step` writes it
        # so) would go on saying the old name under the new one.
        if said.get("description") == said.get("title"):
            said["description"] = title
        said["title"] = title
        done.append(True)
        return meta

    taskmeta.change(folder, put, root)
    return bool(done)


def rename_step(folder: Path, old: str, new: str, root: Path) -> None:
    """A step renumbered where it is, under its new name in its task's list
    of steps: what the list says about it, and its arrows, follow it
    (`objecttree.move`, when the task it is in took another number)."""
    from . import taskmeta

    def put(meta):
        if not isinstance(meta, dict) or not isinstance(meta.get("steps"), dict):
            return meta
        if old not in meta["steps"] or new in meta["steps"]:
            return meta
        # In the same place in the list, which is the order the page draws them.
        meta["steps"] = {(new if key == old else key): value
                         for key, value in meta["steps"].items()}
        arrows = meta.get("arrows")
        if isinstance(arrows, list):
            for arrow in arrows:
                if isinstance(arrow, dict):
                    for end in ("from", "to"):
                        if arrow.get(end) == old:
                            arrow[end] = new
        return meta

    taskmeta.change(folder, put, root)


def forget_step(folder: Path, name: str, root: Path) -> None:
    """Take a deleted step back out of its task's list of steps.

    The other half of `note_step`, and it is needed for the same reason that
    one is: a step named in that list with no folder behind it draws an empty
    column on the task's page, which is the deleted step still on the screen
    under a different name. A task with no list is left alone.
    """
    from . import taskmeta

    def put(meta):
        if not isinstance(meta, dict) or not isinstance(meta.get("steps"), dict):
            return meta
        if name not in meta["steps"]:
            return meta
        meta["steps"].pop(name)
        # And every arrow that pointed at it or came out of it, or the task's page
        # draws a line to a box that is not there.
        arrows = meta.get("arrows")
        if isinstance(arrows, list):
            meta["arrows"] = [a for a in arrows
                              if not (isinstance(a, dict)
                                      and name in (a.get("from"), a.get("to")))]
        return meta

    taskmeta.change(folder, put, root)
