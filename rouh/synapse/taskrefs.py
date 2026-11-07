"""Tasks named by their number in a question, found before anything is searched (attempt 21, 6 October 2026).

The owner names their tasks by number, and by voice the number comes spelled out: "what's going on with 58",
"where are we with seventy", "twenty nine dash three, is blender on the studio machine now?". Neither the words list nor
the vector can match "seventy" to "Task 70: Invoice export", so those questions found almost none of
what they were about. Here plain code reads the numbers and finds each task or step in the dataset by its
number, and `recall.run` adds its number and title to the search query ("where are we with seventy (task
70: Invoice export)"), so its files, steps, cards and chats are found by words and meaning like
anything else. Seeding the task first and preferring its own items in the walk, measured the same night,
added nothing over that, so neither is done.

What counts as a task number, so that a date, an amount or a time is never read as one:

- digits standing alone, 1 to 999: not part of a word ("gpt-4", "v2", "24th"), a decimal, a time ("10:30"),
  an amount ("$58", "58%"), a date ("24 September", "Sept 24", "2026-10-06") or a count ("58 emails");
- spelled numbers from ten up ("seventy", "forty three", "seventy-six"): one to nine alone are ordinary
  words ("one sentence"), and are read only as a step's second part ("twenty nine dash three");
- a step as two of those joined by a dash, "dash" or "step": "29-3", "29-03", "twenty nine dash three".

A number is only a task when the dataset has a task of that number the asker may read; nothing else is
guessed. Steps carry no number of their own in Synapse, only their folder (`29-03.blender-on-the-studio-machine`), so a
step is found among its task's thread by that folder.
"""
from __future__ import annotations

import re

from . import db, search

UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
}
TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90}

MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov",
          "dec"}

#: Words after a number that make it a count or a measure, not a task.
COUNTED = {
    "am", "pm", "h", "hr", "hrs", "hour", "hours", "min", "mins", "minute", "minutes", "sec", "secs", "second",
    "seconds", "ms", "day", "days", "week", "weeks", "month", "months", "year", "years", "yr", "yrs", "night",
    "nights", "times", "time", "x", "k", "m", "gb", "mb", "kb", "tb", "kg", "g", "km", "cm", "mm", "percent",
    "per", "euro", "euros", "eur", "dollar", "dollars", "usd", "bgn", "lev", "leva", "pounds", "gbp", "people",
    "person", "items", "item", "emails", "email", "mails", "mail", "messages", "message", "questions",
    "question", "pages", "page", "words", "word", "tokens", "files", "file", "lines", "line", "points", "point",
    "of", "out", "st", "nd", "rd", "th", "o'clock", "oclock", "tasks", "steps", "chats", "cards", "seats",
    "rooms", "nights", "kids", "adults", "inch", "inches", "degrees", "steps", "more", "less", "or", "to",
    "and", "plus", "minus", "times", "dpi", "fps", "mph", "kmh", "%",
}
#: Words before a number that make it a measure or a date, not a task.
BEFORE = {"$", "€", "£", "at", "by", "around", "version", "v", "gpt", "iphone", "ios",
          "macos", "python", "node", "top", "first", "last", "next", "past", "every", "under", "over",
          "than", "within", "after", "before", "in", "on", "since", "until", "till", "from", "page", "room",
          "seat", "row", "flight", "gate", "pin", "code", "number", "no", "nr"}
#: ...but these before a number say outright that it is a task or a step.
NAMING = {"task", "step", "card", "project", "with", "about", "on"}

STEP_JOINS = {"-", "–", "dash", "step", "point", "."}

#: A word with digits in it or glued to them by a dash ("o3", "gpt-4", "v2") is one token, never a number.
TOKEN = re.compile(r"\$|€|£|%|[–-]|\d+(?:[.:,/]\d+)*[A-Za-z]*|[A-Za-z][A-Za-z'\d]*(?:-\d\w*)*|[^\sA-Za-z\d]")

MOST = 3


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN.findall(text or "")]


def _spelled(toks: list[str], i: int) -> tuple[int | None, int, bool]:
    """A spelled number starting at i: (value, tokens used, whether it may stand alone as a task)."""
    t = toks[i]
    if t in TEENS:
        return TEENS[t], 1, True
    if t in TENS:
        j = i + 1
        if j < len(toks) and toks[j] == "-" and j + 1 < len(toks) and toks[j + 1] in UNITS:
            return TENS[t] + UNITS[toks[j + 1]], 3, True
        if j < len(toks) and toks[j] in UNITS:
            return TENS[t] + UNITS[toks[j]], 2, True
        return TENS[t], 1, True
    if t in UNITS:
        return UNITS[t], 1, False
    return None, 0, False


def _number(toks: list[str], i: int) -> tuple[int | None, int, bool, bool]:
    """A number at i: (value, tokens used, may stand alone, was digits)."""
    t = toks[i]
    if t.isdigit():
        return int(t), 1, True, True
    v, used, alone = _spelled(toks, i)
    return v, used, alone, False


def find_numbers(question: str) -> list[dict]:
    """Every task or step number the question names, in order: `{"task": 58}` or `{"task": 29, "step": 3}`,
    each with the words it was read from."""
    toks = _tokens(question)
    out, seen, i = [], set(), 0
    while i < len(toks):
        t = toks[i]
        # A token that holds digits but is not plain digits (24th, 10:30, 1.5, gpt4, 2026-10-06 cut as one) is
        # never a task number.
        if any(c.isdigit() for c in t) and not t.isdigit():
            i += 1
            continue
        v, used, alone, digits = _number(toks, i)
        if v is None:
            i += 1
            continue
        prev = toks[i - 1] if i > 0 else ""
        prev2 = toks[i - 2] if i > 1 else ""
        j = i + used
        nxt = toks[j] if j < len(toks) else ""
        # A step: number, join, number.
        step = None
        if nxt in STEP_JOINS and j + 1 < len(toks):
            v2, used2, _alone2, digits2 = _number(toks, j + 1)
            after2 = toks[j + 1 + used2] if j + 1 + used2 < len(toks) else ""
            if v2 is not None and 1 <= v2 <= 99 and not (digits and digits2 and nxt == ".") and \
                    not (after2 in MONTHS or after2 in COUNTED and after2 not in ("of", "to", "and", "or", "more", "less")):
                step = v2
                j = j + 1 + used2
                nxt = toks[j] if j < len(toks) else ""
        named = prev in NAMING or (prev == "#")
        ok = (alone or step is not None) and 1 <= v <= 999
        if ok and (prev in MONTHS or nxt in MONTHS or prev2 in MONTHS and prev in (",", "the")):
            ok = False
        if ok and step is None and nxt in COUNTED and not named:
            ok = False
        if ok and step is None and nxt in ("-", "–", "/", ":", ".") and j + 1 < len(toks) and \
                toks[j + 1][:1].isdigit():
            ok = False
        if ok and prev in ("-", "–", "/", ":", ".") and prev2[:1].isdigit():
            ok = False
        if ok and prev in BEFORE and prev not in NAMING:
            ok = False
        if ok and (prev in ("$", "€", "£") or nxt == "%"):
            ok = False
        if ok:
            key = (v, step)
            if key not in seen:
                seen.add(key)
                words = " ".join(toks[i:j])
                out.append({"task": v, "step": step, "words": words} if step is not None else
                           {"task": v, "words": words})
        i = max(j, i + 1)
    return out[:MOST]


def resolve(ds: dict, question: str, asker_readers: list[str]) -> list[dict]:
    """The tasks and steps the question names that the dataset has and the asker may read, each
    `{"id", "title", "kind", "number", "words", "thread"}`; a step comes with its task's thread."""
    nums = find_numbers(question)
    if not nums:
        return []
    keys = sorted({f"task:task-{n['task']}" for n in nums})
    rows = db.rows(
        "SELECT i.id, i.title, i.source_key, i.meta->>'thread' AS thread FROM synapse.item i "
        "WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.kind = 'task' AND i.source_key = ANY(%s) "
        "AND i.deleted_at IS NULL AND " + search.readable_sql("i"),
        (ds["id"], keys, asker_readers))
    by_key = {r["source_key"]: r for r in rows}
    out, have = [], set()
    for n in nums:
        top = by_key.get(f"task:task-{n['task']}")
        if not top:
            continue
        if n.get("step") is None:
            if top["id"] not in have:
                have.add(top["id"])
                out.append({"id": top["id"], "title": top["title"], "number": str(n["task"]),
                            "words": n["words"], "thread": top["thread"]})
            continue
        if not top["thread"]:
            continue
        # A step's folder is "<task>-<step, two digits>.<slug>" under its task's folder.
        folder = rf"Folder: \S*/0*{n['task']}-0*{n['step']}\.[^/\s]*(\s|$)"
        step = db.row(
            "SELECT i.id, i.title FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.kind = 'task' "
            "AND i.meta->>'thread' = %s AND i.deleted_at IS NULL AND i.body ~ %s AND " + search.readable_sql("i") +
            " ORDER BY i.stored_at DESC LIMIT 1", (ds["id"], top["thread"], folder, asker_readers))
        if step and step["id"] not in have:
            have.add(step["id"])
            out.append({"id": step["id"], "title": step["title"], "number": f"{n['task']}-{n['step']}",
                        "words": n["words"], "thread": top["thread"]})
    return out


def label(found: dict) -> str:
    """How a named task joins the search query: its number and its title, as its own item says them."""
    return f"task {found['number']}: {found['title']}"
