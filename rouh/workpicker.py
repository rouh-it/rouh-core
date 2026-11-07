"""The search behind Give authority over, under a trusted contact in Settings.

Petar, 10 October 2026, from his phone: "The task picker should be a search, not a
dropdown, because I have way too many already. I should be able to search tasks and
their subtasks by name or number." So the picker is a box and a short list, and what
it searches is every task, every step inside one, every goal and every quest, by the
number as it is said and by the words of the name (`find`).

A number is matched the way it is said out loud: "98" is task 98, "98-03", "98 03",
"98.03" and "9803" are its step 03, and "98-03-01" a step inside that one
(`number_forms`). Nothing is sent to the page but what one search found, at most
`LIMIT`, ranked exact number first, then the name starting with what was typed,
then the name containing every word of it (`ranked`).
"""
from __future__ import annotations

import logging
import re
import unicodedata

log = logging.getLogger("rouh.workpicker")

#: The most one search answers with.
LIMIT = 20

#: Words said in front of a number that only say what kind it is: "task 98", "step 98-03".
_LEAD = re.compile(r"^(?:sub-?task|task|step|goal|quest|number|no\.?|#)\s*", re.IGNORECASE)
#: A number as typed: parts split by a dash, a dot or spaces.
_NUMBER = re.compile(r"^#?\s*(\d+(?:\s*[-.\s]\s*\d+)*)$")
#: The parts of a code as written: 98, 98-03, 98-03-01.
_CODE = re.compile(r"^\d+(?:-\d+)*$")

#: The order kinds come in when they rank the same.
_KIND_ORDER = {"goal": 0, "quest": 1, "task": 2, "step": 3}


def fold(text) -> str:
    """Text as compared: case folded, accents taken off, spaces made single."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.casefold().split())


def number_forms(query) -> list[tuple[int, ...]]:
    """Every number a query can be, as parts: [] when it is words.

    "98" is (98,). "98-03", "98 03" and "98.03" are (98, 3). "9803" is (9803,) and
    also (98, 3), because a step's own part is always two digits, so a run of digits
    can be read as a task's number of one to three digits and then steps of two."""
    said = _LEAD.sub("", str(query or "").strip()).strip()
    found = _NUMBER.match(said)
    if not found:
        return []
    parts = [p for p in re.split(r"[-.\s]+", found.group(1)) if p]
    if len(parts) > 1:
        return [tuple(int(p) for p in parts)]
    digits = parts[0]
    forms = [(int(digits),)]
    for head in (1, 2, 3):
        rest = digits[head:]
        if rest and len(rest) % 2 == 0:
            form = (int(digits[:head]),) + tuple(int(rest[i:i + 2])
                                                 for i in range(0, len(rest), 2))
            if form not in forms:
                forms.append(form)
    return forms


def code_parts(code) -> tuple[int, ...]:
    """(98, 3) out of "98-03"; () for no code."""
    code = str(code or "").strip()
    return tuple(int(p) for p in code.split("-")) if _CODE.match(code) else ()


def rank_of(item: dict, query: str) -> int | None:
    """Where one item ranks for a query, lower first, or None when it does not match.

    0 its number is the one asked, 1 it is a step inside that one, 2 its name starts
    with what was typed, 3 its number and name hold every word typed."""
    forms = number_forms(query)
    parts = code_parts(item.get("code"))
    if forms and parts:
        if parts in forms:
            return 0
        if any(len(parts) > len(f) and parts[:len(f)] == f for f in forms):
            return 1
    q = fold(query)
    if not q:
        return None
    title = fold(item.get("title"))
    if title.startswith(q):
        return 2
    # A number typed is matched on numbers above, never inside another: 98 is not 980.
    hay = title if forms else fold(f"{item.get('code') or ''} {item.get('title') or ''}")
    words = q.split()
    if all(w in hay for w in words):
        return 3
    return None


def _sort_key(item: dict, rank: int) -> tuple:
    parts = code_parts(item.get("code"))
    return (rank, bool(item.get("archived")), _KIND_ORDER.get(item.get("kind"), 9),
            parts or (10 ** 9,), fold(item.get("title")))


def ranked(items: list[dict], query: str, *, archived: bool = False,
           limit: int = LIMIT) -> tuple[list[dict], int]:
    """The items a query finds, best first and at most `limit`, and how many it found.

    Archived ones only with `archived`. An empty query finds the goals and quests,
    then the newest tasks, so the list is not blank before anything is typed."""
    pool = [i for i in items if archived or not i.get("archived")]
    if not str(query or "").strip():
        start = [i for i in pool if i["kind"] in ("goal", "quest")]
        start.sort(key=lambda i: (_KIND_ORDER[i["kind"]], -(code_parts(i["code"]) or (0,))[0]))
        tasks = [i for i in pool if i["kind"] == "task"]
        tasks.sort(key=lambda i: -(code_parts(i["code"]) or (0,))[0])
        both = start + tasks
        return both[:limit], len(both)
    hits = []
    for item in pool:
        r = rank_of(item, query)
        if r is not None:
            hits.append((_sort_key(item, r), item))
    hits.sort(key=lambda h: h[0])
    return [h[1] for h in hits[:limit]], len(hits)


# --- what there is to find ----------------------------------------------------------------


def items(who) -> list[dict]:
    """Every task, step, goal and quest a grant can be over, as the picker shows them.

    Each is {kind, ref, code, title, project, parent, archived}: `ref` is what
    `delegation.grant` takes for it, `code` its number as said ("98", "98-03"),
    `project` the projects it is in, and `parent` the task or step a step is in."""
    from . import archiving, goals, owning, quests, searching, trusted

    st = owning.store()
    if st is None:
        return []
    tree = trusted.Tree(st)
    kept = archiving.archived(st)
    try:
        goal_ids = {g.id for g in goals._goal_tasks()}
    except Exception:  # noqa: BLE001 - tasks are still found, as tasks
        log.exception("the goals could not be read for the picker")
        goal_ids = set()

    def owner_row(ident):
        return tree.rows.get(tree.owner.get(ident, ""))

    def code_of(row) -> str:
        if row.get("number") is not None:
            return str(row["number"])
        return searching.number_of_folder(row.get("folder") or "")

    def projects_of(ident) -> str:
        names, seen, at = [], set(), ident
        while at in tree.owner and at not in seen:
            seen.add(at)
            at = tree.owner[at]
            row = tree.rows.get(at) or {}
            if row.get("type") == "project":
                names.append(row.get("title") or row.get("slug") or "")
        return " › ".join(reversed([n for n in names if n]))

    out: list[dict] = []
    for ident, row in tree.rows.items():
        if row.get("type") != "task" or tree.column_of(ident) not in trusted.COLUMNS:
            continue
        above = owner_row(ident)
        step = bool(above) and above.get("type") == "task"
        kind = "step" if step else ("goal" if ident in goal_ids else "task")
        out.append({
            "kind": kind, "ref": ident, "code": code_of(row),
            "title": row.get("title") or row.get("slug") or ident,
            "project": projects_of(ident),
            "parent": ({"code": code_of(above), "title": above.get("title") or ""}
                       if step else None),
            "archived": ident in kept})
    try:
        for q in quests.all_of(who):
            task_id = str(getattr(q, "task_id", "") or "")
            out.append({
                "kind": "quest",
                "ref": str(q.task_number) if q.task_number else f"record:{q.id}",
                "code": str(q.task_number) if q.task_number else "",
                "title": q.title, "project": projects_of(task_id) if task_id else "",
                "parent": None, "archived": task_id in kept})
    except Exception:  # noqa: BLE001 - the tasks are still found
        log.exception("the quests could not be read for the picker")
    return out


def find(who, query: str, *, archived: bool = False, limit: int = LIMIT) -> dict:
    """One search, as the page draws it: {query, results, found}."""
    query = str(query or "")[:100]
    results, found = ranked(items(who), query, archived=archived, limit=limit)
    return {"query": query, "results": results, "found": found}
