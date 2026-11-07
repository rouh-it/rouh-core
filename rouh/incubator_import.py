"""Every idea already written down, brought into the Incubator word for word, with its source marked.

Petar, 3 November 2026: import every idea from the Ideas project - every task and every step in
it, with the pages and files in them - the nightly run's own list, and task 166's Gene Nursery,
without duplicating anything; "Copy all text exactly as written. Nothing skipped, shortened,
summarised or reworded"; and mark every extracted source so he can check nothing was missed.

Three sources, each read off the workspace:

- **A project** (`project`, its object id): every task and every step under it is one idea. Its
  words are every Markdown and text file in its own folder (and in plain folders under it, never in
  a step's folder, which is its own idea, or in `temp/` or `node_modules/`), each whole, as one
  section. Its pages are linked and open in place; its other files are linked; its chat, when it
  has one, is linked.
- **The nightly run's list** (`nightly`, the `ideas.md` of its task): every `### I-nnn` entry is
  one idea, the entry whole as its words, its own status word kept beside the Incubator's.
- **The Gene Nursery** (`nursery`, its `gene-nursery.md`): every `### N-nnn` entry likewise. One
  that names a nightly idea is merged into it; one whose only source is a single task or step of
  the project, which no other nursery entry shares, is merged into that one; the rest stay ideas of
  their own, linked to the step they came from, because one step often holds several ideas.

**Importing again changes nothing**: each idea is keyed by its source (`source_key`), and one
already there is left as it is. Nothing is ever deleted or moved.

**Marking** (`mark`): every imported task and step renamed with " [in incubator]" at the end, by
the same rename a person's own uses (`task_rename.rename`: its row, its `.object.json`, a step's
title in its task's meta); the same marker at the end of the `<title>` of every page linked, and of
every entry's heading in the nightly list and the nursery. Rouh saves the workspace by itself.

The report says what was found and imported from each source, every merge, everything marked,
and everything not imported or not marked, with why, item by item.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path, PurePosixPath

from . import incubator

log = logging.getLogger("rouh.incubator_import")

MARK = " [in incubator]"
SKIP_DIRS = {"temp", "node_modules", ".git", "__pycache__", ".venv"}
TEXT_FILES = (".md", ".txt")
#: Statuses in each list, as the Incubator says them.
NIGHTLY_STATUS = {"new": "new", "picked": "in_build", "built": "built", "accepted": "built",
                  "rejected": "rejected", "other": "triaged", "parked": "parked",
                  "waiting-on-decision": "triaged", "technical-not-implemented": "parked",
                  "already-built": "built", "dropped": "rejected"}
NURSERY_STATUS = {"new": "new", "looked at": "triaged", "ready": "triaged", "handed to build": "in_build",
                  "built": "built", "parked": "parked", "dropped": "rejected"}


def _sidecar(folder: Path) -> dict:
    import json

    try:
        got = json.loads((folder / ".object.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _own_files(folder: Path):
    """Every file of this object's own: in its folder and in plain folders under it, never in another
    object's folder (a step is its own idea) or in temp/ and node_modules/."""
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        if entry.is_dir():
            if entry.name in SKIP_DIRS or entry.name.startswith(".") or (entry / ".object.json").is_file():
                continue
            yield from _own_files(entry)
        elif entry.is_file() and entry.name != ".object.json":
            yield entry


def _objects_under(folder: Path):
    """Every task and step folder under a project, parents before their children."""
    for entry in sorted(folder.iterdir(), key=lambda p: _order(p.name)):
        if not entry.is_dir() or entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        said = _sidecar(entry)
        if said.get("type") == "task":
            yield entry, said
            yield from _objects_under(entry)


def _order(name: str):
    nums = [int(n) for n in re.findall(r"\d+", name.split(".", 1)[0])]
    return (nums or [10 ** 6], name)


def _ref_of(folder: Path) -> str:
    head = folder.name.split(".", 1)[0]
    return head if re.fullmatch(r"\d+(-\d+)*", head) else folder.name


def _text_order(path: Path, folder: Path):
    first = {"AGENTS.md": 0, "step.md": 1, "README.md": 2}
    return (first.get(path.name, 3) if path.parent == folder else 4, _rel(folder, path))


def _project_items(root: Path, project: Path, report: dict) -> list[dict]:
    from . import pages

    items = []
    for folder, said in _objects_under(project):
        rel = _rel(root, folder)
        step = _sidecar(folder.parent).get("type") == "task"
        files = list(_own_files(folder))
        texts = sorted([f for f in files if f.suffix.lower() in TEXT_FILES], key=lambda p: _text_order(p, folder))
        html = [f for f in files if f.suffix.lower() in (".html", ".htm")]
        other = [f for f in files if f not in texts and f not in html]
        sections, unreadable = [], []
        for f in texts:
            try:
                sections.append({"title": _rel(folder, f), "path": _rel(root, f), "text": _read(f)})
            except OSError as exc:
                unreadable.append(f"{_rel(root, f)}: {exc}")
        title = str(said.get("title") or folder.name)
        if title.endswith(MARK):
            title = title[: -len(MARK)]
        links = [{"kind": "step" if step else "task", "label": f"{'Step' if step else 'Task'} {_ref_of(folder)}: {title}",
                  "href": "/task/" + rel, "path": rel}]
        links += [{"kind": "page", "label": _rel(folder, f), "href": pages.url_for(_rel(root, f)),
                   "path": _rel(root, f)} for f in html]
        links += [{"kind": "file", "label": _rel(folder, f), "href": pages.url_for(_rel(root, f)),
                   "path": _rel(root, f)} for f in other]
        original = "\n\n".join(f"===== {s['title']} =====\n\n{s['text']}" for s in sections)
        items.append({
            "source": "ideas_project", "source_key": f"ws:{said.get('id') or rel}", "ref": _ref_of(folder),
            "title": title, "text": original, "sections": sections, "links": links, "object_id": said.get("id"),
            "folder": rel, "step": step, "pages": [_rel(root, f) for f in html], "texts": len(sections),
            "files": len(other), "unreadable": unreadable,
        })
    report["ideas_project"]["found"] = len(items)
    report["ideas_project"]["tasks"] = sum(1 for i in items if not i["step"])
    report["ideas_project"]["steps"] = sum(1 for i in items if i["step"])
    return items


_ENTRY = re.compile(r"^### ([IN])-(\d{3,4}) · (.+?)\s*$", re.M)
_FIELD = re.compile(r"^- \*\*([^*:]+):\*\*\s*(.*)$", re.M)


def _entries(text: str, letter: str) -> list[dict]:
    """Every `### X-nnn · Title` entry of a list, whole, from its heading to the next heading."""
    heads = [m for m in _ENTRY.finditer(text) if m.group(1) == letter]
    out = []
    for i, m in enumerate(heads):
        end = len(text)
        nxt = re.compile(r"^#{1,3} ", re.M).search(text, m.end())
        if nxt:
            end = nxt.start()
        whole = text[m.start():end].rstrip("\n")
        fields = {}
        for f in _FIELD.finditer(whole):
            fields.setdefault(f.group(1).strip().lower(), f.group(2).strip())
        title = m.group(3)
        if title.endswith(MARK.strip()):
            title = title[: -len(MARK.strip())].rstrip()
        out.append({"ref": f"{letter}-{m.group(2)}", "title": title, "text": whole, "fields": fields,
                    "line": text.count("\n", 0, m.start()) + 1})
    return out


def _status_word(said: str) -> str:
    return re.split(r"\s+[-\u2013\u2014]\s+|\s*\(|:", str(said or "").strip(), maxsplit=1)[0].strip().lower()


def _kind_of(said: str) -> tuple[str, str]:
    s = str(said or "").strip().strip("`").strip()
    low = s.lower()
    if low.startswith("new gene"):
        return "gene", ""
    if low.startswith("mutation"):
        return "mutation", re.sub(r"^mutations?\s+of\s+", "", s, flags=re.I).strip()
    if low == "feature":
        return "gene", ""
    return "", ""


_STEP_REF = re.compile(r"\bstep (\d{1,4}-\d{1,3})\b")
_TASK_REF = re.compile(r"\btasks? (\d{1,4})\b")


def _refs_in(source: str, by_ref: dict) -> list[dict]:
    """The project's tasks and steps a nightly entry's Source names, as links."""
    links, seen = [], set()
    for m in _STEP_REF.finditer(source or ""):
        a, b = m.group(1).split("-")
        ref = f"{int(a):02d}-{int(b):02d}" if len(a) < 3 else f"{a}-{int(b):02d}"
        item = by_ref.get(ref) or by_ref.get(m.group(1))
        if item and item["source_key"] not in seen:
            seen.add(item["source_key"])
            links.append(item["links"][0])
    for m in _TASK_REF.finditer(source or ""):
        item = by_ref.get(m.group(1))
        if item and not item["step"] and item["source_key"] not in seen:
            seen.add(item["source_key"])
            links.append(item["links"][0])
    return links


def _list_items(path: Path, root: Path, source: str, letter: str, statuses: dict, by_ref: dict,
                report: dict) -> list[dict]:
    from . import pages

    text = _read(path)
    rel = _rel(root, path)
    items = []
    for e in _entries(text, letter):
        f = e["fields"]
        word = _status_word(f.get("status", ""))
        kind, gene = _kind_of(f.get("kind", ""))
        links = [{"kind": "file", "label": f"{path.name}, {e['ref']} (line {e['line']})",
                  "href": pages.url_for(rel), "path": rel}]
        html = path.with_suffix(".html")
        if html.is_file():
            links.append({"kind": "page", "label": f"{html.name} (the list as a page)",
                          "href": pages.url_for(_rel(root, html)), "path": _rel(root, html)})
        links += _refs_in(f.get("source", ""), by_ref)
        items.append({
            "source": source, "source_key": f"{source}:{e['ref']}", "ref": e["ref"], "title": e["title"],
            "text": e["text"], "sections": [{"title": f"{path.name}, {e['ref']}", "path": rel, "text": e["text"]}],
            "links": links, "status": statuses.get(word, "new"), "source_status": f.get("status", ""),
            "kind": kind, "gene": gene, "fields": f, "unknown_status": word not in statuses,
            "technical": f.get("kind", "").strip().lower() == "technical",
        })
    report[source]["found"] = len(items)
    report[source]["file"] = rel
    return items


def _nursery_targets(item: dict, nursery_file: Path, root: Path, by_folder: dict) -> list[dict]:
    """The project's tasks and steps a nursery entry's links point into, deepest object first."""
    out, item["outside"] = [], 0
    for target in re.findall(r"\]\(([^)\s]+)\)", item["fields"].get("source", "")):
        if re.match(r"^[a-z]+:", target):
            item["outside"] += 1
            continue
        p = os.path.normpath(os.path.join(_rel(root, nursery_file.parent), target.split("#")[0]))
        parts = PurePosixPath(p).parts
        for n in range(len(parts), 0, -1):
            hit = by_folder.get("/".join(parts[:n]))
            if hit is not None:
                if hit not in out:
                    out.append(hit)
                break
        else:
            item["outside"] += 1
    return out


def collect(root: str, *, project: str, nightly: str = "", nursery: str = "") -> tuple[list[dict], dict]:
    """Everything to import, in order, and the report so far. `project` is the project's object id or
    folder; `nightly` and `nursery` are the two lists' files, relative to the workspace."""
    base = Path(root)
    report = {"ideas_project": {}, "nightly": {}, "nursery": {}, "merges": [], "not_imported": [],
              "linked": []}
    folder = None
    if (base / project).is_dir():
        folder = base / project
    else:
        for path in base.rglob(".object.json"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            said = _sidecar(path.parent)
            if said.get("id") == project and said.get("type") == "project":
                folder = path.parent
                break
    if folder is None:
        raise incubator.Refused(f"There is no project {project} in the workspace.")
    report["ideas_project"]["folder"] = _rel(base, folder)
    report["ideas_project"]["title"] = _sidecar(folder).get("title", "")
    items = _project_items(base, folder, report)
    by_ref = {i["ref"]: i for i in items}
    by_folder = {i["folder"]: i for i in items}
    if nightly:
        night = _list_items(base / nightly, base, "nightly", "I", NIGHTLY_STATUS, by_ref, report)
        items += night
    else:
        night = []
    by_nightly = {i["ref"]: i for i in night}
    if nursery:
        nurse = _list_items(base / nursery, base, "nursery", "N", NURSERY_STATUS, by_ref, report)
        shared: dict[str, int] = {}
        targets = {}
        for item in nurse:
            targets[item["ref"]] = _nursery_targets(item, base / nursery, base, by_folder)
            for t in targets[item["ref"]][:1]:
                shared[t["source_key"]] = shared.get(t["source_key"], 0) + 1
        for item in nurse:
            named = re.findall(r"\bI-(\d{3})\b", item["fields"].get("source", ""))
            mine = targets[item["ref"]]
            item["links"] += [t["links"][0] for t in mine]
            if named and f"I-{named[0]}" in by_nightly:
                item["merge_into"] = by_nightly[f"I-{named[0]}"]["source_key"]
                item["merge_why"] = f"its Source names I-{named[0]} in the nightly list, the same idea"
            elif len(mine) == 1 and not item["outside"] and shared.get(mine[0]["source_key"]) == 1:
                item["merge_into"] = mine[0]["source_key"]
                item["merge_why"] = (f"its source is the whole of {'step' if mine[0]['step'] else 'task'} "
                                     f"{mine[0]['ref']}, which no other nursery entry shares")
            elif mine:
                why = ("kept as an idea of its own: the step it came from holds "
                       f"{shared.get(mine[0]['source_key'], 0)} nursery ideas") if shared.get(mine[0]["source_key"], 0) > 1 \
                    else "kept as an idea of its own: it has sources beyond one task or step of the project"
                report["linked"].append({"ref": item["ref"], "to": [t["ref"] for t in mine], "why": why})
        items += nurse
    return items, report


def run(who, root: str, *, project: str, nightly: str = "", nursery: str = "", mark: bool = False,
        by: str = "the import") -> dict:
    """Import, merge and, with `mark`, mark. Returns the report."""
    items, report = collect(root, project=project, nightly=nightly, nursery=nursery)
    rows = incubator._rows(who)
    have = {k: n for k, n in rows.exclude(source_key="").values_list("source_key", "number")}
    numbers = {}
    for src in ("ideas_project", "nightly", "nursery"):
        report[src].setdefault("imported", 0)
        report[src].setdefault("already", 0)
    for item in items:
        src = item["source"]
        if item["source_key"] in have:
            numbers[item["source_key"]] = have[item["source_key"]]
            report[src]["already"] += 1
            continue
        made = put_in(who, item, by=by)
        numbers[item["source_key"]] = made["number"]
        report[src]["imported"] += 1
    for item in items:
        into = item.get("merge_into")
        if not into or into not in numbers:
            continue
        mine = incubator.find(who, numbers[item["source_key"]])
        if mine.status == "merged":
            continue
        incubator.merge(who, mine.number, numbers[into], by=by)
        report["merges"].append({"ref": item["ref"], "code": incubator.code(mine.number),
                                 "into": incubator.code(numbers[into]),
                                 "into_ref": next((i["ref"] for i in items if i["source_key"] == into), ""),
                                 "why": item["merge_why"]})
    for item in items:
        for bad in item.get("unreadable") or []:
            report["not_imported"].append({"ref": item["ref"], "what": bad, "why": "the file could not be read"})
    report["items"] = [{"source": i["source"], "ref": i["ref"], "title": i["title"],
                        "code": incubator.code(numbers[i["source_key"]]) if i["source_key"] in numbers else "",
                        "folder": i.get("folder", ""), "texts": i.get("texts", 0), "pages": len(i.get("pages") or []),
                        "files": i.get("files", 0), "chars": len(i["text"])} for i in items]
    _chats(who, items, numbers)
    if mark:
        report["marked"] = _rename(who, items)
    return report


def put_in(who, item: dict, *, by: str = "the import") -> dict:
    """One collected item added to the Incubator as it was found, its words whole. Returns it as
    `incubator.view` draws it. Used by `run` and by the nightly run's own import (`nightly_ideas`)."""
    tags = []
    if item.get("technical"):
        tags.append("technical")
    if item.get("unknown_status"):
        tags.append("status to check")
    return incubator.add(
        who, title=item["title"], text=item["text"], sections=item["sections"], links=item["links"],
        source=item["source"], ref=item["ref"], source_key=item["source_key"], status=item.get("status", "new"),
        source_status=item.get("source_status", ""), kind=item.get("kind", ""), gene=item.get("gene", ""),
        category="stability" if item.get("technical") else "", tags=tags, by=by, what="imported")


def _chats(who, items: list[dict], numbers: dict) -> None:
    """Each imported task's or step's own chat, linked, when it has one."""
    try:
        from . import conversations

        st = conversations.store()
    except Exception:  # noqa: BLE001 - the ideas stand without their chats
        log.exception("the chats could not be read for the import")
        return
    for item in items:
        if item["source"] != "ideas_project" or not item.get("object_id"):
            continue
        try:
            got = conversations._chat_of(st, item["object_id"])
        except Exception:  # noqa: BLE001
            got = None
        if got:
            incubator.link(who, numbers[item["source_key"]], kind="chat",
                           label=f"Chat: {got.get('title') or got.get('id')}",
                           href=f"/task/{item['folder']}?chat={got.get('id')}", by="the import")


_TITLE = re.compile(r"(<title[^>]*>)(.*?)(</title>)", re.I | re.S)


def _rename(who, items: list[dict]) -> dict:
    """Every imported task and step renamed with the marker, through the rename a person's own uses:
    its row, its `.object.json` (which Rouh saves to main by itself) and a step's title in its task's meta."""
    from . import owning, task_rename

    out = {"renamed": [], "already_renamed": [], "rename_failed": []}
    st = owning.store()
    for item in items:
        if item["source"] != "ideas_project":
            continue
        row = st.get_task(item["object_id"]) if st is not None and item.get("object_id") else None
        if row is None:
            out["rename_failed"].append({"ref": item["ref"], "why": "Rouh has no row for it"})
            continue
        now = row.title or item["title"]
        if now.endswith(MARK):
            out["already_renamed"].append(item["ref"])
            continue
        done = task_rename.rename(who, item["object_id"], now + MARK)
        if done.get("ok"):
            out["renamed"].append({"ref": item["ref"], "now": done["now"]})
        else:
            out["rename_failed"].append({"ref": item["ref"], "why": done.get("why")})
    return out


def mark_files(root: str, items: list[dict], nightly: str = "", nursery: str = "") -> dict:
    """The marker at the end of the <title> of every page an imported task or step has, and of every
    entry's heading in the two lists, written into a checkout of the workspace, which is landed like any
    change to it. Pages and lists are not what Rouh's own save of the workspace carries."""
    root = Path(root)
    out = {"pages": [], "pages_already": [], "pages_failed": [], "entries": 0, "entries_already": 0}
    for item in items:
        for rel in item.get("pages") or []:
            path = root / rel
            try:
                text = _read(path)
            except OSError as exc:
                out["pages_failed"].append({"page": rel, "why": str(exc)})
                continue
            m = _TITLE.search(text)
            if m is None:
                head = re.search(r"<head[^>]*>", text, re.I)
                if head is None:
                    out["pages_failed"].append({"page": rel, "why": "it has no <head> to put a title in"})
                    continue
                new = text[:head.end()] + f"\n<title>{path.stem}{MARK}</title>" + text[head.end():]
            elif m.group(2).rstrip().endswith(MARK.strip()):
                out["pages_already"].append(rel)
                continue
            else:
                new = text[:m.start(2)] + m.group(2).rstrip() + MARK + text[m.end(2):]
            path.write_text(new, encoding="utf-8")
            out["pages"].append(rel)
    for rel in (nightly, nursery):
        if not rel:
            continue
        path = root / rel
        text = _read(path)

        def heading(m):
            if m.group(0).rstrip().endswith(MARK.strip()):
                out["entries_already"] += 1
                return m.group(0)
            out["entries"] += 1
            return m.group(0).rstrip() + MARK

        new = _ENTRY.sub(heading, text)
        if new != text:
            path.write_text(new, encoding="utf-8")
    return out


if __name__ == "__main__":  # python -m rouh.incubator_import ROOT PROJECT NIGHTLY NURSERY [--mark-files]
    import json
    import sys

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    got, rep = collect(args[0], project=args[1], nightly=args[2], nursery=args[3])
    if "--mark-files" in sys.argv:
        rep["files_marked"] = mark_files(args[0], got, args[2], args[3])
    rep["items"] = [{k: i.get(k) for k in ("source", "ref", "title", "folder", "texts", "files")}
                    | {"pages": len(i.get("pages") or []), "chars": len(i["text"]),
                       "merge_into": i.get("merge_into", "")} for i in got]
    json.dump(rep, sys.stdout, ensure_ascii=False, indent=1)
