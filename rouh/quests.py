"""Quests: the long-running work the heartbeat carries, each a numbered task of its own.

Petar, 5 October 2026: "Heartbeat is the functionality you have to have in general. It
has nothing to do with the money project/experiment. ... Experiment is yet another thing
I am testing you with that uses the full arsenal. But those two are separate." And later
the same day: long-running work becomes **Quests**, and a quest becomes part of the task
model, the same way a goal is a task tagged Goal (`rouh/goals.py`).

So a quest is two things, joined by its task's number:

- **A numbered task, tagged.** Its meta (`rouh/taskmeta.py`) carries `"tags": ["quest"]` and a
  `"quest"` block naming its record. It is filed under a project like any task, found in
  the task browser like any task, and its plan's steps may be real numbered steps of it.
  What it is for and how it is worked on are files in its folder (`FILES`): the goal and
  the rules, which are the owner's, and the plan and the notebook, which the beats on it keep
  (`heartbeat_brief`). They are in git and in grep, and on the task's own page.
- **A record** (`LongWork`, the table `long_work`), keyed and queried by `org_id` and
  `user_id`, with everything that must not live in git: its money (the budget, the card
  cap per purchase, its ledger and its spend, which are only ever here), its start and
  end dates, paused or on, whether the heartbeat carries it, the events waiting for a
  beat on it, its next beat, the runs, threads and files that are its own, and its chat.

The record also keeps a copy of the four files' words, written whenever Rouh writes a
file, so a file lost to a deploy before it was saved (`rouh/saving.py`) is written back
at the next start (`adopt`). The file is always the one read.

Its page is `/quests/<task number>`, and every quest is on `/quests`
(`rouh/web/quests.py`, `questspage.js`); the `quest` tool reads and changes them in
conversation. The money experiment, "Can Rouh earn more than it spends?" and since the
evening of 5 October 2026 "AI with Rouh", is the first:
record 1, task 89.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import clock, owner, workspace_repo

log = logging.getLogger("rouh.quests")

#: The tag that makes a task a quest. Written into its meta as `tags`.
TAG = "quest"
#: The emoji in front of a quest's own chat: crossed swords, the sign for a quest
#: (a lone dagger, U+1F5E1, draws as a plain text glyph in Chromium without its selector).
CHAT_MARK = "\u2694\ufe0f"
#: The marks its chat had before: the flask of long-running work, and the first compass.
OLD_MARKS = ("\U0001f9ea", "\U0001f9ed")
#: The most each part of the brief may hold.
BRIEF_MOST = 8000
PARTS = ("title", "goal", "rules", "plan", "notebook")
#: The four parts that are files in the quest's task, and the files' names.
FILES = {"goal": "quest-goal.md", "rules": "quest-rules.md", "plan": "quest-plan.md",
         "notebook": "quest-notebook.md"}
#: What heads each file, above the words, so a person opening one knows what it is.
FILE_HEADS = {"goal": "Goal", "rules": "Rules", "plan": "Plan", "notebook": "Notebook"}
#: Filled in for the quest's owner as the file is written (`_write_file`).
FILE_SAYS = {"goal": "‹owner›'s: what this quest is for.",
             "rules": "‹owner›'s: what every beat on this quest must keep to.",
             "plan": "Kept by the heartbeat's beats on this quest.",
             "notebook": "Kept by the heartbeat's beats on this quest: what was found, "
                         "decided and tried, with dates."}
#: The most events kept waiting for a beat on one quest.
PENDING_MOST = 40


class Refused(ValueError):
    """A sentence to say back, rather than a quest half made."""


def _models():
    from . import models

    return models


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def address(row=None) -> str:
    """A quest's own page, or the page of every quest."""
    from .addressing import QUESTS

    number = getattr(row, "task_number", 0) if row is not None else 0
    return f"{QUESTS}/{number}" if number else QUESTS


def name(row) -> str:
    """"quest 89 “Can Rouh earn more than it spends?”", the way it is said everywhere."""
    return (f"quest {row.task_number} “{row.title}”" if row.task_number
            else f"quest “{row.title}”")


def dollars(value) -> str:
    try:
        value = Decimal(value or 0)
    except (InvalidOperation, TypeError):
        value = Decimal(0)
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def money_of(value, what: str = "amount", *, least: str = "0") -> Decimal:
    """A number of dollars, as it was typed or said, or a ValueError that says so."""
    try:
        amount = Decimal(str(value).strip().lstrip("$").replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{what} has to be a number of dollars, such as 12.50.") from None
    if amount < Decimal(least) or amount > Decimal("1000000"):
        raise ValueError(f"{what} has to be from ${Decimal(least)} to $1,000,000.")
    return amount


# --- its task -------------------------------------------------------------------------


def _store():
    from . import owning

    return owning.store()


def _root() -> str:
    from . import owning

    return owning._workspace()


def task_of(row):
    """The quest's task, or None where there is no store or it has none."""
    if row is None or not getattr(row, "task_id", ""):
        return None
    st = _store()
    return st.get_task(row.task_id) if st is not None else None


def folder_of(row) -> Path | None:
    """The quest's task's folder, where its files are, or None."""
    task = task_of(row)
    root = _root()
    if task is None or not task.folder or not root:
        return None
    folder = Path(root) / task.folder
    return folder if folder.is_dir() else None


def _meta(folder: Path) -> dict:
    """The task's meta: what was its meta (`rouh/taskmeta.py`)."""
    from . import taskmeta

    return taskmeta.get(folder, _root() or None)


def _write_meta(folder: Path, meta: dict) -> None:
    from . import taskmeta

    # Never a status or a summary: those are the row's (`rouh/taskrecord.py`).
    taskmeta.write(folder, meta, _root() or None)


def _tag(folder: Path, row) -> bool:
    """Tag its task a quest and name the record in it. True when that changed anything."""
    meta = _meta(folder)
    tags = [t for t in meta.get("tags") or [] if isinstance(t, str)]
    # What else the block holds stays: its goals (`GOALS`), which a permission on the quest
    # reaches (`rouh/task_access.py`).
    was = meta.get("quest") if isinstance(meta.get("quest"), dict) else {}
    block = {**was, "record": row.id}
    if TAG in [t.strip().lower() for t in tags] and meta.get("quest") == block:
        return False
    if TAG not in [t.strip().lower() for t in tags]:
        tags.append(TAG)
    meta["tags"] = tags
    meta["quest"] = block
    _write_meta(folder, meta)
    return True


def set_goals(row, numbers) -> str:
    """The goals this quest is for, by their numbers, kept in its task's meta quest block
    ("goals", their task ids): a permission on the quest reaches them and everything under them
    (`rouh/task_access.py`). Replaces the list; an empty one leaves the quest its own task alone.
    The sentence of what it is now; ValueError says what is not a goal."""
    from . import goals as goal_mod
    from .models import Task

    folder = folder_of(row)
    if folder is None:
        raise ValueError("The quest has no task folder on this machine.")
    ids, named = [], []
    for raw in numbers or []:
        said = str(raw or "").strip().lstrip("#")
        task = Task.objects.filter(number=int(said)).first() if said.isdigit() else None
        if task is None:
            raise ValueError(f"There is no task {said}.")
        place = goal_mod._folder(task)
        if place is None or not goal_mod.is_goal(goal_mod._meta(place)):
            raise ValueError(f"Task {said} is not a goal.")
        if task.id == row.task_id:
            continue
        if task.id not in ids:
            ids.append(task.id)
            named.append(str(task.number))
    meta = _meta(folder)
    block = meta.get("quest") if isinstance(meta.get("quest"), dict) else {"record": row.id}
    if ids:
        block["goals"] = ids
    else:
        block.pop("goals", None)
    meta["quest"] = block
    _write_meta(folder, meta)
    return (f"Quest {row.task_number} is for goals {', '.join(named)}: whoever may read, edit or "
            "decide for the quest may do the same with them." if ids else
            f"Quest {row.task_number} names no goals of its own now.")


def add_goal(row, number) -> str:
    """One more goal this quest is for, kept with the ones it names already (`set_goals`)."""
    from . import task_access
    from .models import Task

    folder = folder_of(row)
    have = task_access.quest_goals(_meta(folder)) if folder is not None else []
    numbers = [str(n) for n in Task.objects.filter(id__in=have).values_list("number", flat=True)
               if n is not None]
    return set_goals(row, [*numbers, str(number)])


def _untag(folder: Path) -> None:
    meta = _meta(folder)
    if not meta:
        return
    meta["tags"] = [t for t in meta.get("tags") or []
                    if isinstance(t, str) and t.strip().lower() != TAG]
    if not meta["tags"]:
        meta.pop("tags")
    meta.pop("quest", None)
    _write_meta(folder, meta)


def _file_text(part: str, text: str) -> str:
    return f"# {FILE_HEADS[part]}\n\n_{FILE_SAYS[part]}_\n\n{text.strip()}\n" if text.strip() \
        else f"# {FILE_HEADS[part]}\n\n_{FILE_SAYS[part]}_\n"


def _from_file(raw: str) -> str:
    """The words of a quest file, without the heading and the line under it."""
    lines = raw.replace("\r\n", "\n").split("\n")
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
        while lines and not lines[0].strip():
            lines = lines[1:]
        if lines and lines[0].startswith("_") and lines[0].rstrip().endswith("_"):
            lines = lines[1:]
    return "\n".join(lines).strip()


def _write_file(folder: Path, part: str, text: str, who=None) -> None:
    from . import saving, steps

    path = folder / FILES[part]
    path.write_text(owner.say(_file_text(part, text), who), encoding="utf-8")
    steps.own_as_workspace(path, Path(_root()))
    saving.poke()


def part_of(row, part: str) -> str:
    """One part of its brief: from its file in the task, or the record's copy without one."""
    if part == "title":
        return row.title
    folder = folder_of(row)
    if folder is not None:
        try:
            return _from_file((folder / FILES[part]).read_text(encoding="utf-8"))
        except OSError:
            pass
    return getattr(row, part) or ""


def brief(row) -> dict:
    """Its goal, rules, plan and notebook, read once."""
    folder = folder_of(row)
    out = {}
    for part in FILES:
        text = None
        if folder is not None:
            try:
                text = _from_file((folder / FILES[part]).read_text(encoding="utf-8"))
            except OSError:
                text = None
        out[part] = text if text is not None else (getattr(row, part) or "")
    return out


def steps_of(row) -> list[dict]:
    """Its task's own numbered steps, as its meta lists them, each with its
    status as its own row says it (`rouh/taskrecord.py`)."""
    from . import taskrecord

    folder = folder_of(row)
    if folder is None:
        return []
    listed = _meta(folder).get("steps")
    if not isinstance(listed, dict):
        return []
    root = _root()
    out = []
    for slug, step in listed.items():
        step = step if isinstance(step, dict) else {}
        said = taskrecord.status_at(folder / slug, root) if root else ""
        out.append({"number": slug.split(".", 1)[0], "title": str(step.get("title") or slug),
                    "status": said or "not-started"})
    out.sort(key=lambda s: s["number"])
    return out


# --- numbers, said or typed ----------------------------------------------------------

_ONES = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
         "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}
_NOISE = {"quest", "quests", "task", "number", "no", "the", "and", "a", "#"}


def number_in(said) -> int | None:
    """The number in "89", "#89", "task 89", "eighty-nine" or "quest eighty nine", or None."""
    text = str(said or "").strip().lower()
    if not text:
        return None
    digits = re.fullmatch(r"(?:quest|task|number|no\.?)?\s*#?\s*(\d{1,4})", text)
    if digits:
        return int(digits.group(1))
    words = [w for w in re.split(r"[\s\-]+", text.replace("#", " ")) if w]
    words = [w for w in words if w not in _NOISE]
    if not words:
        return None
    total, current, seen = 0, 0, False
    for w in words:
        if w in _ONES:
            current += _ONES[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w == "thousand":
            total += (current or 1) * 1000
            current = 0
        else:
            return None
        seen = True
    return total + current if seen else None


# --- reading -------------------------------------------------------------------------


def all_of(who) -> list:
    return list(_models().LongWork.objects.filter(**_whose(who)).order_by("id"))


def get(who, record_id):
    """A quest by its record's id, which only the code uses."""
    try:
        ident = int(str(record_id).strip().lstrip("#"))
    except (TypeError, ValueError):
        return None
    return _models().LongWork.objects.filter(**_whose(who), id=ident).first()


def by_number(who, number):
    """A quest by its task's number, which is how a person names it."""
    try:
        n = int(str(number).strip().lstrip("#"))
    except (TypeError, ValueError):
        return None
    return _models().LongWork.objects.filter(**_whose(who), task_number=n).first()


def by_id(user_id: str, org_id: str, record_id):
    if record_id is None:
        return None
    return _models().LongWork.objects.filter(user_id=user_id, org_id=org_id, id=record_id).first()


def find(who, said) -> "object | None":
    """A quest by its task number, said or typed, or by words of its title; None if not
    exactly one. A number that is no quest's task is tried as a record's id, which is how
    the tools named one before quests were tasks."""
    if said in (None, ""):
        rows = all_of(who)
        return rows[0] if len(rows) == 1 else None
    n = number_in(said)
    if n is not None:
        row = by_number(who, n)
        if row is not None:
            return row
        row = get(who, n)
        if row is not None:
            return row
    words = str(said).strip().lower()
    hits = [w for w in all_of(who) if words in (w.title or "").lower()]
    return hits[0] if len(hits) == 1 else None


def same(row, said) -> bool:
    """Whether what a tool was handed names this quest: its number, or its record's id."""
    n = number_in(said)
    return n is not None and n in (row.task_number, row.id)


def chats() -> set[str]:
    """Every quest's own chat, on every account."""
    return set(_models().LongWork.objects.exclude(chat_id="").values_list("chat_id", flat=True))


def last_day(row) -> str:
    """Its last day, "3 November 2026": the day before it ends at midnight."""
    if not row.ends_at:
        return ""
    return clock.moment(row.ends_at - 1).strftime("%-d %B %Y")


def period(row) -> str:
    start = clock.moment(row.started_at) if row.started_at else None
    if start and row.ends_at:
        return f"{start.strftime('%-d %b')} to {last_day(row)}"
    if start:
        return f"since {start.strftime('%-d %b %Y')}"
    return ""


def running(row, now: float | None = None) -> str:
    """Why it is not being worked on now, or "" when it is."""
    now = time.time() if now is None else now
    if not row.carried:
        return "The heartbeat does not carry it."
    if row.state == "paused":
        return "It is paused."
    if row.started_at and now < row.started_at:
        return "It has not started yet."
    if row.ends_at and now > row.ends_at:
        return f"It has ended: its last day was {last_day(row)}."
    return ""


def state_of(row, now: float | None = None) -> str:
    """One word for where it stands: on, paused, ended, not carried, or not started."""
    now = time.time() if now is None else now
    if not row.carried:
        return "not carried"
    if row.state == "paused":
        return "paused"
    if row.ends_at and now > row.ends_at:
        return "ended"
    if row.started_at and now < row.started_at:
        return "not started"
    return "on"


# --- money --------------------------------------------------------------------------


def spend(row, since: float = 0.0) -> Decimal:
    """What the turns in its own chat cost since then, from the log of every model request."""
    if not row.chat_id:
        return Decimal("0")
    from django.db.models import Sum

    found = _models().LLMRequest.objects.filter(
        session_id=row.chat_id, started_at__gte=since, user_id=row.user_id,
        org_id=row.org_id).aggregate(n=Sum("cost_usd"))["n"]
    return Decimal(found or 0)


def money(row) -> dict:
    """Its money: in, out (its ledger's and its own model spend), and what is left of its budget."""
    from django.db.models import Sum

    entries = _models().LongWorkLedger.objects.filter(user_id=row.user_id, org_id=row.org_id,
                                                       work_id=row.id)
    took = Decimal(entries.filter(direction="in").aggregate(n=Sum("amount"))["n"] or 0)
    paid = Decimal(entries.filter(direction="out").aggregate(n=Sum("amount"))["n"] or 0)
    cards = Decimal(entries.filter(direction="out", by="card").aggregate(n=Sum("amount"))["n"] or 0)
    models_spent = Decimal(row.spent_before or 0) + spend(row, since=row.started_at or 0)
    out = paid + models_spent
    budget = Decimal(row.budget or 0)
    return {"in": took, "out": out, "paid": paid, "cards": cards, "models": models_spent,
            "net": took - out, "budget": budget, "left": budget - out if budget else Decimal(0)}


def ledger_add(who, record_id, *, direction: str, amount, currency: str, what: str, by: str,
               ref: str = ""):
    direction = str(direction or "").strip().lower()
    if direction not in ("in", "out"):
        raise ValueError("direction is in or out.")
    amount = money_of(amount, least="0.01")
    what = " ".join(str(what or "").split())[:300]
    if not what:
        raise ValueError("Say what the money was for.")
    currency = (str(currency or "USD").strip().upper() or "USD")[:8]
    return _models().LongWorkLedger.objects.create(
        **_whose(who), work_id=record_id, direction=direction, amount=amount, currency=currency,
        what=what, by=by, ref=ref or "", at=time.time())


# --- making one, and changing it ------------------------------------------------------


def _date(text: str, what: str) -> float:
    """"2026-11-03" as midnight at the start of that day on the owner's clock."""
    try:
        day = datetime.strptime(str(text).strip(), "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{what} is a date, such as 2026-11-03.") from None
    return day.replace(tzinfo=clock.zone()).timestamp()


def _put_in_task(row, task) -> None:
    """Link the record to its task, tag the task, and write the four files into it from the
    record's copy, where the task has not got them yet."""
    fields = {}
    if row.task_id != task.id:
        fields["task_id"] = task.id
    if task.number is not None and row.task_number != task.number:
        fields["task_number"] = int(task.number)
    if fields:
        save(row, **fields)
    folder = folder_of(row)
    if folder is None:
        return
    if _tag(folder, row) and (task.title or "") != row.title:
        # Its task is named as the quest is now: the quest's title is the newer word
        # (the money experiment was renamed "AI with Rouh" after task 89 was made).
        import contextlib

        from . import owning

        with contextlib.suppress(Exception):
            owning.rename("task", task.id, row.title)
    for part in FILES:
        if not (folder / FILES[part]).exists():
            _write_file(folder, part, getattr(row, part) or "", row.user_id)


def create(who, *, title: str, goal: str = "", rules: str = "", plan: str = "",
           start: str = "", end: str = "", budget=None, spend_cap=None, carried=True):
    """A quest: a numbered task tagged Quest with its four files, and its record.

    Its chat is made by the heartbeat, owned by the task (`Heartbeat.quest_made`), which
    also files the new task under the project it belongs in.
    """
    from . import owning

    title = " ".join(str(title or "").split())[:200]
    if not title:
        raise ValueError("Give it a title.")
    now = time.time()
    started = _date(start, "The start") if start else clock.now().replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()
    ends = _date(end, "The last day") + 86400 if end else 0
    if ends and ends <= started:
        raise ValueError("It has to end after it starts.")
    for part, text in (("goal", goal), ("rules", rules), ("plan", plan)):
        if len(str(text or "")) > BRIEF_MOST:
            raise ValueError(f"The {part} holds at most {BRIEF_MOST} characters.")
    budget = money_of(budget, "The budget") if budget not in (None, "") else Decimal(0)
    cap = money_of(spend_cap, "The card cap") if spend_cap not in (None, "") else Decimal(50)
    task = owning.new_task(title)
    if task is None:
        raise Refused("There is no task store on this machine to keep a quest in.")
    row = _models().LongWork.objects.create(
        **_whose(who), title=title, goal=str(goal or "").strip(), rules=str(rules or "").strip(),
        plan=str(plan or "").strip(), notebook="", state="on", carried=bool(carried),
        started_at=started, ends_at=ends, budget=budget, spend_cap=cap, pending=[], own={},
        task_id=task.id, task_number=int(task.number or 0), created_at=now, updated_at=now)
    _put_in_task(row, task)
    return row


def save(row, **fields) -> None:
    fields["updated_at"] = time.time()
    _models().LongWork.objects.filter(id=row.id).update(**fields)
    for key, value in fields.items():
        setattr(row, key, value)


def write_brief(row, part: str, text: str, mode: str = "replace") -> str:
    """Write one part of its brief: its file in the task, and the record's copy."""
    part = str(part or "").strip().lower()
    if part not in PARTS:
        raise ValueError("part is title, goal, rules, plan or notebook.")
    text = str(text or "").strip()
    if mode == "append" and part in ("plan", "notebook", "rules"):
        stamp = clock.now().strftime("%d %b %H:%M")
        joined = part_of(row, part).rstrip() + f"\n{stamp}: {text}"
        if len(joined) > BRIEF_MOST:
            joined = "...\n" + joined[-(BRIEF_MOST - 4):]
        text = joined.strip()
    if not text and part in ("title", "goal"):
        return f"The {part} cannot be empty."
    most = 200 if part == "title" else BRIEF_MOST
    if len(text) > most:
        return (f"That is {len(text)} characters, and the {part} holds {most}. Shorten it: keep "
                "what the next beat needs.")
    if part == "title":
        return retitle(row, text)
    folder = folder_of(row)
    if folder is not None:
        _write_file(folder, part, text, row.user_id)
    save(row, **{part: text})
    return f"The {part} of {name(row)} is saved ({len(text)} characters)."


def retitle(row, title: str) -> str:
    """A new title: the record's, its task's, and its chat's."""
    import contextlib

    from . import owning

    title = " ".join(str(title or "").split())[:200]
    if not title:
        raise ValueError("Give it a title.")
    save(row, title=title)
    if row.task_id:
        with contextlib.suppress(Exception):
            owning.rename("task", row.task_id, title)
    _rename_chat(row.chat_id, f"{CHAT_MARK} {title}")
    return f"Quest {row.task_number} is now called “{title}”."


def settings(row, *, budget=None, spend_cap=None, end=None, extend_days=None,
             carried=None, start=None) -> str:
    fields, said = {}, []
    if budget not in (None, ""):
        fields["budget"] = money_of(budget, "The budget")
        said.append(f"a budget of {dollars(fields['budget'])}")
    if spend_cap not in (None, ""):
        cap = money_of(spend_cap, "The card cap")
        fields["spend_cap"] = cap
        said.append(f"at most {dollars(cap)} a card purchase")
    if start not in (None, ""):
        fields["started_at"] = _date(start, "The start")
        said.append("its start " + clock.moment(fields["started_at"]).strftime("%-d %B %Y"))
    if end not in (None, ""):
        if str(end).strip().lower() in ("none", "never", "0"):
            fields["ends_at"] = 0
            said.append("no end date")
        else:
            fields["ends_at"] = _date(end, "The last day") + 86400
    if extend_days not in (None, ""):
        try:
            days = int(float(extend_days))
        except (TypeError, ValueError):
            raise ValueError("extend_days is a number of days.") from None
        if not -60 <= days <= 365:
            raise ValueError("extend_days is a number of days, up to a year.")
        fields["ends_at"] = (fields.get("ends_at") or row.ends_at or time.time()) + days * 86400
    if fields.get("ends_at"):
        starts = fields.get("started_at", row.started_at)
        if starts and fields["ends_at"] <= starts:
            raise ValueError("It has to end after it starts.")
        said.append("its last day " + clock.moment(fields["ends_at"] - 1).strftime("%-d %B %Y"))
    if carried is not None:
        fields["carried"] = bool(carried)
        said.append("carried by the heartbeat" if carried else "left alone by the heartbeat")
    if not fields:
        raise ValueError("Say what to change: budget, spend_cap, start, end, extend_days or "
                         "carried.")
    save(row, **fields)
    return f"Quest {row.task_number} “{row.title}” now has " + ", ".join(said) + "."


# --- starting again, and taking it away -------------------------------------------------
#
# Petar, 5 October 2026: every quest gets a Delete, which takes it and everything that
# belongs to it away, and a Reset, which keeps it, its goal and its rules and starts it
# again from beat 1. Neither touches a run of the one program it started, and neither
# touches the Payments page's record of a card charge. A delete asks what becomes of its
# task: kept, archived with its files, or deleted with them (`remove`).
#
# Its money is read from its ledger and from the log of every model request in its own
# chat (`money`). So both give it a fresh chat (made at its next beat) and leave the old
# one as a chat with its history, renamed to say so; the old chat is kept on the
# heartbeat's list of retired chats, so what its beats cost today still counts against the
# heartbeat's daily cap (`heartbeat.beat_chats`), because that money was really spent.

_STAMPED = re.compile(r"^\d{2} [A-Z][a-z]{2} \d{2}:\d{2}: ", re.M)


def notebook_entries(text: str) -> int:
    """How many entries a notebook holds: its dated lines, or its paragraphs if none."""
    text = str(text or "").strip()
    if not text:
        return 0
    stamped = len(_STAMPED.findall(text))
    return stamped or len([p for p in re.split(r"\n\s*\n", text) if p.strip()])


def tally(row) -> dict:
    """What goes with it: its beats, notebook entries, ledger lines and waiting approvals."""
    m = _models()
    whose = {"user_id": row.user_id, "org_id": row.org_id}
    return {
        "beats": m.HeartbeatBeat.objects.filter(**whose, work_id=row.id).count(),
        "notebook": notebook_entries(part_of(row, "notebook")),
        "ledger": m.LongWorkLedger.objects.filter(**whose, work_id=row.id).count(),
        "approvals": m.HeartbeatApproval.objects.filter(**whose, work_id=row.id,
                                                        state="waiting").count(),
    }


def _n(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def tally_words(t: dict) -> str:
    """"4 beats, 2 notebook entries, 1 ledger line and no pending approvals"."""
    parts = [_n(t["beats"], "beat"), _n(t["notebook"], "notebook entry", "notebook entries"),
             _n(t["ledger"], "ledger line")]
    last = _n(t["approvals"], "pending approval") if t["approvals"] else "no pending approvals"
    return ", ".join(parts) + " and " + last


def _clearing(row, *, every_approval: bool) -> dict:
    """Take away its beats, their notes, its ledger and its approvals; what went.

    Inside the caller's transaction. Refused while a beat on it is running, which would
    write into what was just cleared.
    """
    from . import beatlog

    m = _models()
    whose = {"user_id": row.user_id, "org_id": row.org_id}
    beats = m.HeartbeatBeat.objects.filter(**whose, work_id=row.id)
    if beats.filter(status="running").exists():
        raise ValueError(f"A beat on {name(row)} is running now. Try again once it has ended.")
    went = tally(row)
    state = m.HeartbeatState.objects.select_for_update().filter(**whose).first()
    beatlog.drop_notes(state, list(beats))
    beatlog.drop_work_notes(state, row)
    beats.delete()
    m.LongWorkLedger.objects.filter(**whose, work_id=row.id).delete()
    asks = m.HeartbeatApproval.objects.filter(**whose, work_id=row.id)
    (asks if every_approval else asks.filter(state="waiting")).delete()
    if state is not None and row.chat_id:
        own = dict(state.own or {})
        kept = [c for c in own.get("retired_chats", []) if c != row.chat_id][-49:]
        own["retired_chats"] = kept + [row.chat_id]
        m.HeartbeatState.objects.filter(id=state.id).update(own=own, updated_at=time.time())
    return went


def _rename_chat(chat: str, title: str) -> None:
    if not chat:
        return
    import contextlib

    from . import conversations

    with contextlib.suppress(Exception):
        conversations.rename(chat, title[:120])


def _detach_chat(chat: str) -> None:
    """Its old chat out of its task, so a task deleted with its files does not take it."""
    if not chat:
        return
    import contextlib

    from . import owning

    with contextlib.suppress(Exception):
        owning.detach("chat", chat)


def reset(row) -> str:
    """Start it again from beat 1: its goal, rules, dates, budget and switches kept; its
    beats, their notes, plan, notebook, ledger, waiting approvals, next beat and money
    cleared."""
    from django.db import transaction

    old_chat = row.chat_id
    with transaction.atomic():
        fresh = _models().LongWork.objects.select_for_update().filter(id=row.id).first()
        if fresh is None:
            raise ValueError("There is no such quest.")
        went = _clearing(fresh, every_approval=False)
        # The timer goes on at its own pace: its first beat again is an interval from now.
        save(row, plan="", notebook="", pending=[], due_at=0, due_what="",
             last_beat_at=time.time(), last_full_at=0, spent_before=Decimal(0), chat_id="",
             earlier_chat_id="")
    folder = folder_of(row)
    if folder is not None:
        for part in ("plan", "notebook"):
            _write_file(folder, part, "", row.user_id)
    _rename_chat(old_chat, f"{CHAT_MARK} {row.title} (before its reset, "
                           f"{clock.now().strftime('%-d %b %H:%M')})")
    return (f"Quest {row.task_number} “{row.title}” starts again from beat 1. Cleared "
            f"{tally_words(went)}, its plan, its notebook and its next beat; its goal, rules, "
            "dates and budget are kept, and its money starts again from nothing. Its next beat "
            "runs in a new chat of its own.")


#: What becomes of a deleted quest's task: kept as a task with its files, archived with
#: them, or deleted with everything in it.
TASK_FATES = ("keep", "archive", "delete")


def remove(row, task: str = "archive") -> str:
    """Delete the quest and everything that is only its: its record, beats, ledger,
    approvals and next beat. Its task is kept, archived (the default: its files are kept,
    out of the live lists) or deleted with its files, as the owner chose. Runs it started are
    left as they are."""
    from django.db import transaction

    from . import archiving, owning

    task = str(task or "archive").strip().lower()
    if task not in TASK_FATES:
        raise ValueError("task is keep, archive or delete.")
    old_chat, title, number, task_id = row.chat_id, row.title, row.task_number, row.task_id
    folder = folder_of(row)
    with transaction.atomic():
        fresh = _models().LongWork.objects.select_for_update().filter(id=row.id).first()
        if fresh is None:
            raise ValueError("There is no such quest.")
        went = _clearing(fresh, every_approval=True)
        _models().LongWork.objects.filter(id=row.id).delete()
    _rename_chat(old_chat, f"{CHAT_MARK} {title} (deleted quest)")
    said = f"Deleted quest {number} “{title}” with {tally_words(went)}."
    if not task_id or task_of(row) is None:
        return said + " Runs it started are left as they are."
    if task == "delete":
        _detach_chat(old_chat)
        gone = owning.remove("task", task_id)
        if gone.get("ok"):
            return said + f" Its task {number} is deleted with its files. Runs it started " \
                          "are left as they are, and so is its old chat."
        return said + f" Its task {number} could not be deleted: {gone.get('why')}"
    if folder is not None:
        _untag(folder)
    if task == "archive":
        done = archiving.archive(task_id, True)
        return said + (f" Its task {number} is archived with its files: open it from the "
                       "task browser's Archive." if done.get("ok") else
                       f" Its task {number} is kept, with its files: {done.get('why')}")
    return said + f" Its task {number} is kept as a task, with its files."


# --- the quests made before they were tasks ----------------------------------------------


def _task_named(title: str):
    """The one numbered task with exactly this title, or None."""
    st = _store()
    if st is None:
        return None
    hits = [t for t in st.list_tasks(limit=None)
            if t.number is not None and t.folder and (t.title or "").strip() == title.strip()]
    return hits[0] if len(hits) == 1 else None


def adopt() -> list[str]:
    """Make every record a quest with a task, at start.

    A record with no task yet (each made before 5 October 2026, when long-running work
    became quests) takes the numbered task with exactly its title, if there is one, or a
    new task of its own; the money experiment was joined to task 89 by migration 0094. Either way its task is tagged
    and its goal, rules, plan and notebook are written into it from the record, unless it
    already has them. A file lost since (a deploy that reset it before it was saved) is
    written back from the record's copy. What was done, in words, for the log.
    """
    from . import owning

    said = []
    for row in _models().LongWork.objects.all().order_by("id"):
        try:
            task = task_of(row)
            if task is None:
                task = _task_named(row.title) or owning.new_task(row.title)
                if task is None:
                    continue
                said.append(f"record {row.id} “{row.title}” is quest {task.number}")
            _put_in_task(row, task)
            if _remark_chat(row):
                said.append(f"quest {row.task_number}'s chat wears the sword")
        except Exception:
            log.exception("record %s could not be made a quest", row.id)
    return said


def _remark_chat(row) -> bool:
    """Its chat's title with the sword in front, where it still has an old mark. True when
    it was changed."""
    if not row.chat_id:
        return False
    from . import conversations

    st = conversations.store()
    chat = st.get_chat(row.chat_id) if st is not None else None
    title = (getattr(chat, "title", "") or "") if chat is not None else ""
    for mark in OLD_MARKS:
        if title.startswith(mark):
            _rename_chat(row.chat_id, CHAT_MARK + title[len(mark):])
            return True
    return False


# --- what wakes a beat on it ----------------------------------------------------------


def owning_of(who, kind: str, value: str):
    """The quest whose own run, thread or file this is, or None."""
    for row in all_of(who):
        if value and value in (row.own or {}).get(kind, []):
            return row
    return None


def own_add(user_id: str, org_id: str, record_id, kind: str, value: str) -> None:
    from django.db import transaction

    m = _models()
    with transaction.atomic():
        row = (m.LongWork.objects.select_for_update()
               .filter(user_id=user_id, org_id=org_id, id=record_id).first())
        if row is None:
            return
        own = dict(row.own or {})
        listed = [v for v in own.get(kind, []) if v != value][-199:]
        own[kind] = listed + [value]
        m.LongWork.objects.filter(id=row.id).update(own=own, updated_at=time.time())


def add_event(row, event: dict) -> None:
    from django.db import transaction

    m = _models()
    with transaction.atomic():
        fresh = m.LongWork.objects.select_for_update().get(id=row.id)
        pending = (list(fresh.pending or []) + [event])[-PENDING_MOST:]
        m.LongWork.objects.filter(id=row.id).update(pending=pending, updated_at=time.time())


def take_events(row) -> list:
    from django.db import transaction

    m = _models()
    with transaction.atomic():
        fresh = m.LongWork.objects.select_for_update().get(id=row.id)
        events = list(fresh.pending or [])
        m.LongWork.objects.filter(id=row.id).update(pending=[], updated_at=time.time())
    row.pending = []
    return events


def put_back(row, events: list) -> None:
    from django.db import transaction

    if not events:
        return
    m = _models()
    with transaction.atomic():
        fresh = m.LongWork.objects.select_for_update().get(id=row.id)
        merged = (events + list(fresh.pending or []))[-PENDING_MOST:]
        m.LongWork.objects.filter(id=row.id).update(pending=merged, updated_at=time.time())


# --- what is said and drawn -------------------------------------------------------------


def line(row) -> str:
    """One line about it, for the heartbeat's status and the tool's list."""
    cash = money(row)
    state = running(row) or "being worked on"
    bits = [f"Quest {row.task_number} “{row.title}”"]
    if period(row):
        bits.append(period(row))
    bits.append(state.rstrip(".").lower() if state != "being worked on" else state)
    if row.budget:
        bits.append(f"{dollars(cash['left'])} of {dollars(cash['budget'])} left")
    bits.append(f"net {dollars(cash['net'])}")
    return ", ".join(bits) + "."


def status(row) -> str:
    cash = money(row)
    b = brief(row)
    lines = [f"Quest {row.task_number} “{row.title}”, {period(row) or 'no dates'}. "
             + (running(row) or "The heartbeat works on it.")]
    lines.append(f"Money in {dollars(cash['in'])}, out {dollars(cash['out'])} (model and tool "
                 f"spend {dollars(cash['models'])}, card {dollars(cash['cards'])}, other "
                 f"{dollars(cash['paid'] - cash['cards'])}), net {dollars(cash['net'])}"
                 + (f"; {dollars(cash['left'])} of its {dollars(cash['budget'])} budget left."
                    if row.budget else "; no budget set."))
    lines.append(f"At most {dollars(row.spend_cap)} a card purchase. Its page is "
                 f"{address(row)}.")
    lines.append(f"GOAL\n{b['goal'] or '(empty)'}")
    lines.append(f"RULES\n{b['rules'] or '(empty)'}")
    lines.append(f"PLAN\n{b['plan'] or '(empty)'}")
    lines.append(f"NOTEBOOK\n{b['notebook'] or '(empty)'}")
    return "\n\n".join(lines)


def ledger_lines(row, most: int = 30) -> str:
    entries = list(_models().LongWorkLedger.objects.filter(
        user_id=row.user_id, org_id=row.org_id, work_id=row.id).order_by("-at")[:most])
    if not entries:
        return f"{name(row).capitalize()} has nothing in its ledger yet."
    return "\n".join(f"{clock.clock(e.at)} {'+' if e.direction == 'in' else '-'}{e.amount} "
                     f"{e.currency} {e.what} ({owner.word(e.by)})" for e in entries)


def summary(row) -> dict:
    """What a short list of them draws: the Heartbeat page."""
    return {"id": row.id, "number": row.task_number, "title": row.title,
            "carried": bool(row.carried), "paused": row.state == "paused",
            "why_not": running(row), "period": period(row), "href": address(row)}


def _when(ts, now: float) -> str:
    if not ts:
        return ""
    moment = clock.moment(ts)
    today = clock.moment(now)
    if moment.date() == today.date():
        return moment.strftime("%H:%M")
    if moment.date() == (today - timedelta(days=1)).date():
        return "Yesterday " + moment.strftime("%H:%M")
    if moment.date() == (today + timedelta(days=1)).date():
        return "Tomorrow " + moment.strftime("%H:%M")
    return moment.strftime("%d %b %H:%M")


def _heart(who) -> tuple[int, bool]:
    """The heartbeat's interval in minutes, and whether it is paused, which stops every quest."""
    row = _models().HeartbeatState.objects.filter(**_whose(who)).first()
    return int(getattr(row, "interval_minutes", 0) or 30), getattr(row, "state", "on") == "paused"


def card(who, row, *, heart: tuple[int, bool] | None = None) -> dict:
    """One quest as the Quests page lists it."""
    from . import questcheck

    m = _models()
    now = time.time()
    cash = money(row)
    _interval, hb_paused = heart or _heart(who)
    asks = m.HeartbeatApproval.objects.filter(**_whose(who), work_id=row.id,
                                              state="waiting").count()
    # What happens next is worked out in one place, for this list, its page and the goal
    # map alike (`rouh/questcheck.py`).
    st = questcheck.state(who, row, with_steps=False)
    return {
        **summary(row), "state": state_of(row, now), "task": row.task_id,
        "start": clock.moment(row.started_at).strftime("%-d %b %Y") if row.started_at else "",
        "end": last_day(row),
        "spent": dollars(cash["out"]), "budget": dollars(cash["budget"]) if row.budget else "",
        "left": dollars(cash["left"]) if row.budget else "",
        "over": bool(row.budget and cash["left"] < 0),
        "income": dollars(cash["in"]), "net": dollars(cash["net"]),
        "net_down": cash["net"] < 0, "approvals": asks,
        "last_beat": _when(row.last_full_at, now),
        "next_beat": _next_words(st),
        "exec_label": st["label"], "exec_state": st["state"],
        "tally": tally(row), "heartbeat_paused": hb_paused,
    }


def _next_words(st: dict) -> str:
    """When its next automatic check may come, as the lists say it, or ""."""
    nxt = st.get("next") or {}
    if not nxt:
        return ""
    return nxt["when"] if nxt.get("soon") else f"{nxt['when']} at the earliest"


def listing(who) -> list[dict]:
    heart = _heart(who)
    return [card(who, row, heart=heart) for row in all_of(who)]


def view(who, row) -> dict:
    """Everything its page shows."""
    m = _models()
    now = time.time()
    cash = money(row)
    b = brief(row)
    task = task_of(row)
    entries = list(m.LongWorkLedger.objects.filter(**_whose(who), work_id=row.id)
                   .order_by("-at")[:200])
    beats = list(m.HeartbeatBeat.objects.filter(**_whose(who), work_id=row.id)
                 .order_by("-id")[:40])
    asks = list(m.HeartbeatApproval.objects.filter(**_whose(who), work_id=row.id)
                .order_by("-id")[:40])
    from . import questcheck
    from .heartbeat import decision_numbers_of

    decided = decision_numbers_of(asks)

    _interval, hb_paused = _heart(who)
    # What happens next, worked out once (`rouh/questcheck.py`): the goal map's steps say
    # the same.
    st = questcheck.state(who, row)
    return {
        "tally": tally(row), "next": st,
        "work": {
            **summary(row), **b, "chat": row.chat_id or "",
            "earlier_chat": row.earlier_chat_id or "",
            "state": state_of(row, now), "heartbeat_paused": hb_paused,
            "task_folder": task.folder if task is not None and task.folder else "",
            "task_files": {part: FILES[part] for part in FILES},
            "steps": steps_of(row),
            "start": clock.moment(row.started_at).strftime("%Y-%m-%d") if row.started_at else "",
            "end": clock.moment(row.ends_at - 1).strftime("%Y-%m-%d") if row.ends_at else "",
            "budget": str(row.budget), "spend_cap": str(row.spend_cap),
            "last_beat": _when(row.last_full_at, now),
            "next_beat": _next_words(st),
            "due": (clock.clock(row.due_at) + (f": {row.due_what}" if row.due_what else "")
                    if row.due_at else ""),
        },
        "money": {k: dollars(v) for k, v in cash.items()},
        "ledger": [{"id": e.id, "direction": e.direction, "amount": f"{e.amount:,.2f}",
                    "currency": e.currency, "what": e.what, "by": owner.word(e.by), "when": _when(e.at, now)}
                   for e in entries],
        "beats": [{"id": b.id, "trigger": b.trigger, "status": b.status, "reason": b.reason,
                   "outcome": b.outcome, "said": b.said, "when": _when(b.started_at, now),
                   "cost": dollars(b.cost) if b.cost is not None else ""} for b in beats],
        "approvals": [{"id": a.id, "what": a.what, "state": a.state,
                       "decision": decided.get(a.id),
                       "when": _when(a.asked_at, now)} for a in asks],
    }


def goal_lines(task, row=None) -> str:
    """What a beat is told when its quest's task is also a goal (`rouh/goals.py`), or "".

    Petar asked for a goal for his quest on 6 October 2026, to follow and support it.
    The goal lays the quest's work out beside the owner's decisions; its steps marked as the
    quest's are the beats' to do and to mark done, and never a run of the goal's."""
    from . import goals

    folder = goals._folder(task) if task is not None else None
    try:
        if folder is None or not goals.is_goal(goals._meta(folder)):
            return ""
        v = goals.view(task)
    except Exception:
        log.exception("the goal of task %s could not be read for its quest",
                      getattr(task, "number", None))
        return ""
    steps = goals._flat(v["steps"])
    mine = [s for s in steps if s["who"] == goals.QUEST]
    his = [s for s in steps if s["who"] in (goals.OWNER, "together") and s["status"] != "done"]

    def one(s: dict) -> str:
        state = "complete" if s["status"] == "done" else s["status"]
        picked = f", ‹he› chose: {s['choice']}" if s.get("choice") else ""
        return f"{s['n']} {s['title']} ({state}{picked})"

    out = (f"ITS GOAL: this task is also goal {v['number']} on the Goals page, which lays "
           "the quest's work out beside ‹owner›'s decisions so ‹he› can follow it.")
    if mine:
        out += (" The steps there that are the quest's are yours, done in your beats: "
                + "; ".join(one(s) for s in mine) + ". When one is complete, mark it done "
                f"with goal_step (goal {v['number']}, its step number), so the page stays "
                "true. Never start a step of the goal as a run.")
    if his:
        out += " Waiting on ‹owner› there: " + "; ".join(one(s) for s in his) + "."
    # A step of the quest's made ready by one before it: what was handed on, and whether
    # it came after the last full beat, so a notebook saying it is missing is not believed.
    from . import questcheck

    if row is not None:
        try:
            news = questcheck.news_lines(row, v)
        except Exception:
            log.exception("what is new on goal %s could not be read", v["number"])
            news = []
        if news:
            out += "\n" + "\n".join(news)
    return out


def note_block(row, cash: dict) -> list[str]:
    """The quest's standing brief, as a beat on it is handed it."""
    b = brief(row)
    task = task_of(row)
    where = (f"{workspace_repo.in_run(task.folder)}/" if task is not None and task.folder else "")
    parts = [f"GOAL (‹owner›'s)\n{b['goal'] or '(empty)'}",
             f"RULES (‹owner›'s; you cannot change them)\n{b['rules'] or '(empty)'}",
             f"PLAN (yours to keep current with heartbeat_brief)\n{b['plan'] or '(empty)'}",
             f"NOTEBOOK (yours: what was found, decided and tried, with dates)\n"
             f"{b['notebook'] or '(empty)'}"]
    if where:
        steps = steps_of(row)
        lines = [f"ITS TASK: task {row.task_number}, {where}. The goal, rules, plan and "
                 f"notebook above are its files {', '.join(FILES.values())}; heartbeat_brief "
                 "writes them. A part of the plan big enough for a run of its own can be a "
                 "numbered step of this task, which a run you start makes in this folder."]
        if steps:
            lines.append("Its steps: " + "; ".join(
                f"{s['number']} {s['title']} ({s['status']})" for s in steps[:30]) + ".")
        said = goal_lines(task, row)
        if said:
            lines.append(said)
        parts.append("\n".join(lines))
    money_line = (f"MONEY: in {dollars(cash['in'])}, out {dollars(cash['out'])} (of which its "
                  f"model and tool spend {dollars(cash['models'])} and card charges "
                  f"{dollars(cash['cards'])}), net {dollars(cash['net'])}")
    if row.budget:
        money_line += f"; {dollars(cash['left'])} of its {dollars(cash['budget'])} budget left"
    money_line += f". At most {dollars(row.spend_cap)} a card purchase, under the card's own caps."
    if row.ends_at:
        money_line += f" Its last day is {last_day(row)}."
    parts.append(money_line)
    return parts
