"""Who made a task: the person, somebody else on whose behalf it was made, or one of Rouh's
own processes.

Petar, 15 October 2026: "When other people create tasks through email and telegram. Can we
please separate them from my tasks somehow? I don't want those to pollute my workspace. Maybe
like a toggle similar to Archive?" And the next day, of everything Rouh's processes make on
their own: "I don't want to be deciding. Whatever any process is doing should be created
without me being the gate. I just don't want to see it by default in the task browser."

**What is kept.** `task.origin`, beside the task's status in Rouh's database, and its `made`,
which is one of three:

- `"person"` - his own. `{}` is this too: nothing said is his. Every task he made, and every
  task Rouh or a job made because he asked, in his own words, is his.
- `"other"` - made for somebody else: `{"made": "other", "for": "Sam Rivera", "email":
  ..., "telegram": ..., "channel": "email" or "telegram", "by": "rouh", "why": ..., "at": ...}`.
  `why` is the signal it was read from, in words.
- `"process:<name>"` - made by one of Rouh's processes on its own: `{"made":
  "process:thoughts", "process": "thoughts", "by": "rouh", "why": ..., "at": ...}`. The name is
  a gene's id where the process is a gene's (`rouh/genes/manifests`), or one of `PROCESSES`.

`"by": "owner"` on any of them is his own word, from a task's menu, and nothing marks it again
(`"petar"`, which rows written before 20 October 2026 say, is read as the same).

Every change is a row of `task_change` (field `origin`), as a status or a summary is, with who
made it, so what was marked can be read back: `python manage.py task_origin list`.

**When it is set.** As the row is made (`at_birth`, from `ObjectStore.create_owned`): what the
code making it says (`making`, a context every process wraps its own work in), else the task
it is a step of, else his. A run a process starts carries the process with it
(`starting.start`'s `made_by`, kept on the run), and the steps its checkout brings in when it
lands are that process's (`by_run`). Nothing is asked or held: a process makes its tasks
exactly as before, and they are only kept out of his default view.

**Made for somebody else.** A task made for somebody outside is filed as the owner's own work and
labelled Guest: its meta has the tag `guest` and `"guest": "<their address>"` or
`"telegram:<id>"`, written by the job a mail or Telegram case starts (`mail_cases.work_brief`)
and by the `shared_task` tool. Besides that tag, `requested_by` in the same file, a case's own
chat that became the task (`make_a_task`), and the line "A guest task for <name> (<address>)"
its notes open with all say who asked. An address that is the person's own or Rouh's is never
somebody else, and a Telegram account no contact or case puts a name to is left alone: when
unsure, the task stays his, because hiding one of his is the worse mistake. `sweep` marks
them: at Rouh's start, as a task or a step is taken in (`conversations.reconcile`), as a job's
landed work is (`assistant_job`), when the `shared_task` tool makes one, and every few minutes
besides, all beside `requester_share`, which shares the same tasks with whoever asked. Made
for somebody else wins over made by a process: a mail case's task is the person's it was for.

**What it changes.** Only what his own views show by default. The task browser shows his own
tasks, and beside the Archive it has "Others' tasks" and "Made by Rouh", each of which works
as the Archive does: a press shows only those tasks, instead of his, and a second press comes
back (fr_e06a8342488e). Anything pinned, or waiting on him, is in his own list whoever made it,
so nothing that needs him is out of sight. The Control Room and the task list Rouh reads
(`_tasks.md`) leave out the tasks made for other people, or put them under a heading of their
own, until "Others' tasks" is switched on there (`showing`, a setting of his kept here). Their
numbers, folders, sharing and the people they were made for are untouched; a task opened by
its number or its link opens, and search and Synapse find them as before. No folder is moved.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("rouh.task_origin")

#: The person's setting: whether his views show the tasks made for other people.
SHOW = "tasks_show_others"

#: The three kinds of maker. A process's is `PROCESS` and its name.
PERSON, OTHER, PROCESS = "person", "other", "process:"

#: How a channel is said on a task's line.
CHANNEL_WORDS = {"email": "by email", "telegram": "on Telegram"}

#: Rouh's processes that are not one gene's, by the name their tasks are marked with, and what
#: each is called on the screen. A gene's process is called what its manifest calls it.
PROCESSES = {
    "nightly-feature-run": "Nightly feature run",
    "nightly-refactor": "Nightly refactoring run",
    "meeting-next": "After a meeting",
    "case-fixes": "Mail case fixes",
    "mail": "Mail cases",
    "dreaming": "Dreaming",
    "rouh": "Rouh",
}

#: What a process said it is making, for the tasks made while it works (`making`).
_MAKING: contextvars.ContextVar[dict | None] = contextvars.ContextVar("rouh_task_making",
                                                                      default=None)

#: The same, for a process of its own on this machine, such as a job's: `process:<name>`.
ENV = "ROUH_MADE_BY"

#: The line a guest task's notes open with (`mail_cases.work_brief` asks for it).
_GUEST_NOTE = re.compile(r"\bA guest task for ([^\n(]{2,80}?) \(([^\s()]+@[^\s()]+)\)")

#: How much of a task's notes is read for that line.
NOTES_HEAD = 4000


# --- reading ------------------------------------------------------------------------------


def made(origin) -> str:
    """Who made it: "person", "other" or "process:<name>"."""
    if not isinstance(origin, dict) or not origin:
        return PERSON
    said = str(origin.get("made") or "")
    if said == OTHER or (said.startswith(PROCESS) and len(said) > len(PROCESS)):
        return said
    if said == PERSON or origin.get("mine"):
        return PERSON
    # Marked before 16 October 2026, when somebody else was the only other maker.
    return OTHER if origin.get("for") else PERSON


def others(origin) -> bool:
    """Whether an origin says the task was made for somebody else."""
    return made(origin) == OTHER and bool(origin.get("for"))


def by_process(origin) -> bool:
    """Whether one of Rouh's processes made it on its own."""
    return made(origin).startswith(PROCESS)


def process_of(origin) -> str:
    """The name of the process that made it, or ""."""
    kind = made(origin)
    return kind[len(PROCESS):] if kind.startswith(PROCESS) else ""


def mine(origin) -> bool:
    """Whether it is his own: nothing said, or said to be."""
    return made(origin) == PERSON


def said_by_person(origin) -> bool:
    """Whether he said himself who made it, which nothing marks again."""
    from . import owner

    return isinstance(origin, dict) and owner.word(origin.get("by")) == "owner"


def process_words(name: str) -> str:
    """What a process is called on the screen: "Thoughts", "Nightly feature run"."""
    name = str(name or "").strip()
    if not name:
        return "Rouh"
    if name in PROCESSES:
        return PROCESSES[name]
    try:
        from . import genes

        for one in genes.GENES:
            if one.get("id") == name:
                return str(one.get("name") or name)
    except Exception:  # noqa: BLE001 - the name itself still says it
        log.debug("the genes could not be read for %s", name, exc_info=True)
    return name.replace("-", " ").replace("_", " ").strip().capitalize()


def words(origin) -> str:
    """"Made for Sam Rivera, by email", "Made by Thoughts", or "" for his own."""
    if others(origin):
        how = CHANNEL_WORDS.get(str(origin.get("channel") or ""), "")
        return f"Made for {origin['for']}" + (f", {how}" if how else "")
    if by_process(origin):
        return f"Made by {process_words(process_of(origin))}"
    return ""


def public(origin) -> dict | None:
    """What a page of his is given about who made it, or None for his own: `kind` ("other"
    or "process"), who it was for or which process, and the words."""
    if others(origin):
        return {"kind": OTHER, "for": str(origin["for"]),
                "channel": str(origin.get("channel") or ""),
                "words": words(origin), "by": str(origin.get("by") or "")}
    if by_process(origin):
        name = process_of(origin)
        return {"kind": "process", "process": name, "name": process_words(name),
                "words": words(origin), "by": str(origin.get("by") or "")}
    return None


def origins(store=None) -> dict[str, dict]:
    """Every task and step something is said about, by id, with its origin."""
    from . import objects

    st = store if store is not None else objects.shared_store(even_when_off=True)
    if st is None:
        return {}
    try:
        return st.task_origins()
    except Exception:                        # pragma: no cover - reported
        log.exception("who made the tasks could not be read")
        return {}


def made_for(store=None) -> dict[str, dict]:
    """Every task and step made for somebody else, by id, with its origin."""
    return {k: v for k, v in origins(store).items() if others(v)}


def hidden(store=None, tree=None) -> dict[str, dict]:
    """Every task and step his views leave out while others' tasks are hidden, by id, with
    the origin it is hidden under: those made for somebody else and everything under one.

    `tree` is anything with `rows` and `owner` (id -> owning id), such as
    `objectindex._Tree` or `trusted.Tree`, when the caller has one already.
    """
    marked = made_for(store)
    if not marked or tree is None:
        return marked
    out: dict[str, dict] = {}
    for ident, row in tree.rows.items():
        if row.get("type") != "task":
            continue
        at, seen = ident, 0
        while at and seen < 32:
            if at in marked:
                out[ident] = marked[at]
                break
            at, seen = tree.owner.get(at), seen + 1
    return out


# --- made as it is made -------------------------------------------------------------------


def process(name: str, why: str = "") -> dict:
    """The origin a task made by process `name` is born with."""
    name = str(name or "").strip().lower() or "rouh"
    return {"made": PROCESS + name, "process": name, "by": "rouh",
            "why": why or f"{process_words(name)} made it"}


@contextlib.contextmanager
def making(name: str, why: str = ""):
    """Every task or step made inside this is made by process `name`:

        with task_origin.making("thoughts", "from thought 4"):
            objecttree.create(...)

    It follows the work into `asyncio.to_thread` and the tasks it starts, as a context does.
    """
    token = _MAKING.set(process(name, why))
    try:
        yield
    finally:
        _MAKING.reset(token)


def his() -> None:
    """From here on in this context, what is made is the person's own: a process's mark is
    dropped, as a beat's is when he said yes to one of its actions."""
    _MAKING.set(None)


@contextlib.contextmanager
def as_found():
    """Every task or step made inside this is a folder something else made, taken in as it is
    found (`conversations.reconcile`, the map's import): whatever is running meanwhile did not
    make it, so it is born with the task above it, and the landing of the run that made it
    says the rest (`mark_run_work`)."""
    token = _MAKING.set({"found": True})
    try:
        yield
    finally:
        _MAKING.reset(token)


def current() -> dict | None:
    """What the code running now says is making tasks, or None for nothing said."""
    said = _MAKING.get()
    if said and said.get("found"):
        return None
    if said:
        return dict(said)
    env = str(os.environ.get(ENV) or "").strip()
    if env.startswith(PROCESS) and len(env) > len(PROCESS):
        return process(env[len(PROCESS):], "the process it ran in made it")
    return None


def inherited(parent: dict | None, parent_id: str = "") -> dict:
    """What a step is born with under a task whose origin is `parent`: the same maker."""
    kind = made(parent)
    if kind == PERSON:
        return {}
    out = {k: v for k, v in (parent or {}).items() if k not in ("at", "by", "why", "mine")}
    said = words(parent)
    out.update(made=kind, by="rouh",
               why=f"a step of {parent_id or 'a task'}" + (f", {said[0].lower()}{said[1:]}" if said else ""))
    return out


def under(task_id: str) -> dict:
    """What a step taken in under task `task_id` is born with: the same maker as the task."""
    from .models import Task

    above = Task.objects.filter(id=str(task_id)).values_list("origin", flat=True).first()
    got = inherited(above, str(task_id))
    return dict(got, at=time.time()) if got else {}


def at_birth(owner_origin: dict | None = None, owner_id: str = "",
             owned_by_task: bool = False) -> dict:
    """The origin a new task or step is born with: what the code making it says, else the
    task it is a step of, else his own ({})."""
    said = current()
    if said:
        return dict(said, at=time.time())
    if owned_by_task:
        got = inherited(owner_origin, owner_id)
        return dict(got, at=time.time()) if got else {}
    return {}


def run_maker(said: str | None = None) -> str:
    """What a run starting now is made by, for `run.made_by`: `said` when the caller says
    ("" or "person" for the person's own), else what the code starting it is making."""
    if said is not None:
        said = str(said or "").strip()
        return said if said.startswith(PROCESS) and len(said) > len(PROCESS) else ""
    now = current()
    return str(now["made"]) if now else ""


def by_run(run_id: str) -> dict | None:
    """What a run's work is made by: the process that started it, or None for the person's."""
    from .models import Run

    if not run_id:
        return None
    said = (Run.objects.filter(id=str(run_id)).values_list("made_by", flat=True).first()
            or "")
    if said.startswith(PROCESS) and len(said) > len(PROCESS):
        return process(said[len(PROCESS):], f"run {run_id}, which {process_words(said[len(PROCESS):])} "
                                            "started, made it")
    return None


def same_maker(was_run: str, new_run: str) -> bool:
    """A run started again to redo another's work is made by whoever made the first: its
    `made_by` copied over. True when there was one to copy."""
    from .models import Run

    said = Run.objects.filter(id=str(was_run)).values_list("made_by", flat=True).first() or ""
    if not said or not new_run:
        return False
    return bool(Run.objects.filter(id=str(new_run)).update(made_by=said))


# --- the person's setting -----------------------------------------------------------------


def showing(user_id, org_id) -> bool:
    """Whether he has others' tasks switched on in his views. Off until he switches it."""
    from .models import UserSetting

    if not user_id:
        return False
    value = (UserSetting.objects.filter(user_id=str(user_id), org_id=str(org_id or ""), name=SHOW)
             .values_list("value", flat=True).first())
    try:
        return bool(json.loads(value)) if value else False
    except (TypeError, ValueError):
        return False


def show(user_id, org_id, on: bool) -> bool:
    """Switch others' tasks on or off in his views, and answer what it is now."""
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(user_id), org_id=str(org_id or ""), name=SHOW,
                     value=json.dumps(bool(on)), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])
    return bool(on)


# --- telling who asked --------------------------------------------------------------------


def _root() -> str:
    from .config import config

    return getattr(config, "assistant_repo", "") or ""


def _owner():
    from .tenancy import Tenancy

    return Tenancy().only_person()


def _ours(owner, address: str) -> bool:
    """Whether an address is the person's own or Rouh's: never somebody else."""
    from . import my_card

    return my_card.never_mine(address) or my_card.is_own(owner.user_id, owner.org_id, address)


def _clean(address: str) -> str:
    from . import sharing

    return sharing.clean_email(str(address or "").strip().lower())


def _case_chats(owner, store) -> dict[str, dict]:
    """The mail or Telegram case whose own chat became each task, by task id."""
    from . import objects
    from .models import MailCase

    cases = {}
    for row in (MailCase.objects.filter(user_id=owner.user_id, org_id=owner.org_id)
                .exclude(chat_id="").order_by("id")
                .values("id", "chat_id", "sender", "sender_name")):
        cases.setdefault(row["chat_id"], row)
    if not cases:
        return {}
    out: dict[str, dict] = {}
    for link in store.refs(objects.OWNS, src_type="task", dst_type="chat"):
        if link.dst_id in cases:
            out.setdefault(link.src_id, cases[link.dst_id])
    return out


def _notes_name(root: str, folder: str) -> tuple[str, str]:
    """(name, address) from the line "A guest task for <name> (<address>)" in its notes."""
    try:
        with open(Path(root) / folder / "AGENTS.md", encoding="utf-8") as f:
            head = f.read(NOTES_HEAD)
    except OSError:
        return "", ""
    found = _GUEST_NOTE.search(head)
    return (found.group(1).strip(), found.group(2).strip().lower()) if found else ("", "")


def _case_name(owner, sender: str) -> str:
    """What the newest mail or Telegram case from this sender calls them, or ""."""
    from .models import MailCase

    return str(MailCase.objects.filter(user_id=owner.user_id, org_id=owner.org_id, sender=sender)
               .exclude(sender_name="").order_by("-id").values_list("sender_name", flat=True)
               .first() or "")


def requester(owner, root: str, row: dict, *, contacts=(), case: dict | None = None) -> dict | None:
    """Who a task was made for, read off what made it, or None when it is the person's own
    or it cannot be told for sure.

    `row` is the task's row (`id`, `folder`); `contacts` the person's trusted contacts
    (`trusted.TrustStore.all`); `case` the mail or Telegram case whose chat became it.
    """
    from . import trusted as trust

    folder = str(row.get("folder") or "")
    meta = trust.task_meta(root, folder) if folder else {}
    tags = {str(t).strip().lower() for t in meta.get("tags") or [] if isinstance(t, str)}
    asked = meta.get("requested_by") if isinstance(meta.get("requested_by"), dict) else {}
    raw, name, why = "", "", ""
    if trust.GUEST_TAG in tags:
        raw = str(meta.get("guest") or asked.get("contact") or "").strip().lower()
        name = str(asked.get("name") or "").strip()
        why = f"it is labelled Guest, for {raw}"
    if not raw and asked.get("contact"):
        raw = str(asked.get("contact") or "").strip().lower()
        name = str(asked.get("name") or "").strip()
        why = f"its meta says {name or raw} asked for it"
    if not raw and case:
        raw = str(case.get("sender") or "").strip().lower()
        name = str(case.get("sender_name") or "").strip()
        why = f"it is the chat of case {case.get('id')}, from {raw}"
    if not raw and folder and root:
        name, raw = _notes_name(root, folder)
        if raw:
            why = f"its notes say it is a guest task for {name}"
    if not raw:
        return None
    contact = next((c for c in contacts if c.recognises(raw)), None)
    if not name and contact is None:
        name = _case_name(owner, raw)
        if not name and folder and root:
            said, address = _notes_name(root, folder)
            name = said if address and address == _clean(raw) else ""
    if raw.startswith("telegram:"):
        channel, telegram = "telegram", raw.split(":", 1)[1]
        email = (contact.addresses or [""])[0] if contact is not None else ""
        if case is None and contact is None and not name:
            # A Telegram account nothing puts a name to: not sure, so it stays his.
            return None
    else:
        channel, telegram = "email", ""
        email = _clean(raw)
        if not email:
            return None
    if email and _ours(owner, email):
        return None
    if contact is not None and contact.name:
        name = contact.name
    if case is not None and case.get("sender", "").startswith("telegram:"):
        channel = "telegram"
    name = " ".join((name or email or f"Telegram {telegram}").split())[:120]
    return {"for": name, "email": email, "telegram": telegram, "channel": channel,
            "by": "rouh", "why": why}


# --- telling which process made it, from its record -------------------------------------


#: A run named in a step's own notes: "run 6ddd664c".
_RUN_NAMED = re.compile(r"\brun ([0-9a-f]{8})\b", re.I)


def _notes_runs(root: str, folder: str) -> set[str]:
    """Every run a folder's own notes name, read from its top `.md` files."""
    out: set[str] = set()
    try:
        files = sorted(Path(root, folder).glob("*.md"))
    except OSError:
        return out
    for one in files[:12]:
        try:
            with open(one, encoding="utf-8") as f:
                out.update(_RUN_NAMED.findall(f.read(NOTES_HEAD)))
        except OSError:
            continue
    return out


def _records(root: str) -> dict:
    """What the processes' own tables say they made: each thought's task, and each night's
    run, with the folder of the task the nights work in."""
    from . import nightly_feature, nightly_refactor
    from .models import NightlyFeatureNight, NightlyRefactorNight, Thought

    def runs_of(model) -> dict[str, int]:
        return {str(r)[:8]: n for r, n in model.objects.exclude(run_id="")
                .values_list("run_id", "number")}

    return {
        "thoughts": {str(t): i for i, t in Thought.objects.exclude(enrich_task="")
                     .values_list("id", "enrich_task")},
        "nights": [(nightly_feature.task_folder(root), "nightly-feature-run",
                    runs_of(NightlyFeatureNight)),
                   (nightly_refactor.task_folder(root), "nightly-refactor",
                    runs_of(NightlyRefactorNight))],
    }


def classify(root: str, row: dict, records: dict | None = None) -> dict | None:
    """The process a task or a step was made by, read off what the process itself recorded,
    or None when nothing says so for sure: then it is his, because hiding one of his is the
    worse mistake.

    - a thought's own task (`thoughts.enrich_task`, `rouh/thought_enrich.py`) is Thoughts';
    - a step of the nightly feature run's task, or the nightly refactoring run's, whose own
      notes name the run one of its nights was, is that night's run's.

    A step inside a task a process made is that process's too (`backfill`)."""
    records = records if records is not None else _records(root)
    ident, folder = str(row.get("id") or ""), str(row.get("folder") or "")
    if ident in records["thoughts"]:
        return process("thoughts", f"the task of thought {records['thoughts'][ident]}")
    for home, name, nights in records["nights"]:
        if not home or row.get("number") is not None or folder.rsplit("/", 1)[0] != home:
            continue
        named = sorted(r for r in _notes_runs(root, folder) if r in nights)
        if named:
            return process(name, f"night {nights[named[0]]}'s step, by run {named[0]}")
    return None


def backfill(root: str | None = None, *, write: bool = False) -> dict:
    """Every task and step nothing is said about yet, read for the process that made it
    (`classify`), and the steps under one marked with it. Only a dry run unless `write`.
    Counts by origin of every task and step afterwards, and a line for each one marked."""
    from .models import Link, Task

    root = _root() if root is None else root
    records = _records(root) if root else {"thoughts": {}, "nights": []}
    rows = {r["id"]: r for r in Task.objects.values("id", "number", "folder", "origin")}
    above = {dst: src for src, dst in Link.objects.filter(rel="owns", src_type="task",
                                                           dst_type="task")
             .values_list("src_id", "dst_id")}
    now = {ident: (r["origin"] or {}) for ident, r in rows.items()}
    lines = []

    def depth(ident: str) -> int:
        n, at = 0, above.get(ident)
        while at and n < 32:
            n, at = n + 1, above.get(at)
        return n

    for ident in sorted(rows, key=lambda i: (depth(i), rows[i]["folder"] or "")):
        if now[ident]:
            continue
        row = rows[ident]
        found = classify(root, row, records) if root else None
        if found is None and above.get(ident) in now and not mine(now[above[ident]]):
            found = inherited(now[above[ident]], _called(rows[above[ident]]))
            if not by_process(found):
                found = None        # under a task made for somebody else: the sweep's
        if found is None:
            continue
        now[ident] = found
        lines.append(f"{_called(row)}{' (' + row['folder'] + ')' if row.get('number') is not None else ''}"
                     f": {words(found).lower()}, {found['why']}")
        if write:
            _write(ident, found, by="rouh, from what made it (16 October 2026)",
                   only_if_unsaid=True)
    counts: dict[str, int] = {}
    for origin in now.values():
        counts[made(origin)] = counts.get(made(origin), 0) + 1
    if write and lines:
        log.info("task origin: %d tasks and steps marked as made by Rouh", len(lines))
    return {"counts": dict(sorted(counts.items())), "marked": lines, "written": bool(write)}


# --- writing ------------------------------------------------------------------------------


def _write(task_id: str, origin: dict, *, by: str, only_if_unsaid: bool) -> bool:
    """Keep an origin on a task, and the change in `task_change`. False when nothing changed:
    no such task, or (with `only_if_unsaid`) he has said who made it meanwhile, or it is
    marked as made for somebody else already."""
    from django.db import transaction

    from .models import Task, TaskChange

    origin = dict(origin, at=time.time())
    with transaction.atomic():
        rows = Task.objects.select_for_update().filter(id=task_id)
        was = rows.values_list("origin", flat=True).first()
        if was is None:
            return False
        if only_if_unsaid and (said_by_person(was) or others(was)):
            return False
        rows.update(origin=origin)
        TaskChange.objects.create(task_id=task_id, field="origin",
                                  old=json.dumps(was or {}, ensure_ascii=False),
                                  new=json.dumps(origin, ensure_ascii=False),
                                  at=origin["at"], by=by)
    from . import tasklist

    tasklist.changed()
    return True


def _called(row: dict) -> str:
    return f"task {row['number']}" if row.get("number") is not None else str(row.get("folder") or row["id"])


def sweep(root: str | None = None, owner=None) -> list[str]:
    """Every task and step made for somebody else that is not marked so yet, marked so. What
    was marked, a sentence each, each also in the log and in `task_change`.

    A task a process made can be one made for somebody else as well - a mail case's - and
    then it is theirs: made for somebody else wins. Nothing he said himself is touched."""
    from . import objects
    from . import trusted as trust
    from .models import Task

    root = _root() if root is None else root
    owner = _owner() if owner is None else owner
    store = objects.shared_store(even_when_off=True)
    if not root or owner is None or store is None:
        return []
    rows = [row for row in Task.objects.exclude(folder="").order_by("created_at")
            .values("id", "number", "folder", "origin")
            if not said_by_person(row["origin"]) and not others(row["origin"])]
    if not rows:
        return []
    contacts = trust.TrustStore().all(owner.user_id, owner.org_id)
    cases = _case_chats(owner, store)
    out = []
    for row in rows:
        found = requester(owner, root, row, contacts=contacts, case=cases.get(row["id"]))
        if found is None:
            continue
        found = dict(found, made=OTHER)
        if not _write(row["id"], found, by="rouh, from what made it", only_if_unsaid=True):
            continue
        said = (f"{_called(row)} ({row['folder']}) marked as made for {found['for']}"
                f"{' <' + found['email'] + '>' if found['email'] else ''}"
                f"{' (Telegram ' + found['telegram'] + ')' if found['telegram'] else ''}"
                f", {found['channel']}: {found['why']}")
        log.info("task origin: %s", said)
        out.append(said)
    return out


def sweep_quietly() -> list[str]:
    """`sweep`, for a caller that must never stop because of it."""
    try:
        return sweep()
    except Exception:  # noqa: BLE001 - marked on the next pass
        log.exception("task origin: a pass stumbled")
        return []


def mark_made_by(task_ids, origin: dict, *, by: str) -> list[str]:
    """Tasks and steps a process made, marked so where nothing else is said about them yet:
    the steps a run brought in when it landed (`by_run`). The ids marked."""
    from .models import Task

    out = []
    for ident in [str(i) for i in task_ids if i]:
        was = Task.objects.filter(id=ident).values_list("origin", flat=True).first()
        if was is None or said_by_person(was) or not mine(was):
            continue
        if _write(ident, origin, by=by, only_if_unsaid=True):
            out.append(ident)
    if out:
        log.info("task origin: %s marked as %s", ", ".join(out), words(origin).lower())
    return out


#: How long before a run began a task may have been made and still count as the run's.
RUN_SLACK = 5.0


def _first_added(root: str, folder: str) -> float | None:
    """When the first of a folder's files reached the workspace's history, or None."""
    import subprocess

    try:
        out = subprocess.run(["git", "-C", root, "log", "--diff-filter=A", "--format=%at", "--",
                              folder], capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    times = [float(x) for x in out.stdout.split() if x.strip().isdigit()]
    return min(times) if times else None


def mark_run_work(run_id: str, files, root: str | None = None) -> list[str]:
    """The tasks and steps a process's run made, marked as that process's as its work lands:
    every one whose folder its landed files are in and whose first file reached the
    workspace after the run began. None for a run started from the person's own words, whose
    work is born with the task it is in. The ids marked."""
    from .models import Run, Task

    origin = by_run(run_id)
    if origin is None:
        return []
    root = _root() if root is None else root
    began = Run.objects.filter(id=str(run_id)).values_list("started_at", flat=True).first()
    folders: set[str] = set()
    for path in files or []:
        path = str(path or "").strip().strip("/")
        if path.startswith("workspace/"):
            path = path[len("workspace/"):]
        parts = path.split("/")[:-1]
        folders.update("/".join(parts[:n]) for n in range(1, len(parts) + 1))
    if not folders or began is None or not root:
        return []
    made = []
    for ident, folder in Task.objects.filter(folder__in=folders).values_list("id", "folder"):
        first = _first_added(root, folder)
        if first is not None and first >= float(began) - RUN_SLACK:
            made.append(ident)
    return mark_made_by(made, origin, by=f"rouh, as run {run_id} landed")


def set_by_person(task_id: str, to, *, root: str | None = None, owner=None) -> dict:
    """The person saying who made a task: "person" (his own; True does too), "other"
    (somebody else's; False does too) or "process" (one of Rouh's processes). What the task
    browser's `change` answers: ``ok``, and ``did`` or ``why`` in words for him. Nothing marks
    it again afterwards."""
    from . import objects
    from . import trusted as trust

    to = PERSON if to is True else OTHER if to is False else str(to or "")
    if to not in (PERSON, OTHER, "process"):
        return {"ok": False, "why": "A task is yours, made for someone else, or made by Rouh."}
    store = objects.shared_store(even_when_off=True)
    row = store.get_task(task_id) if store is not None and task_id else None
    if row is None:
        return {"ok": False, "why": "There is no task here with that id."}
    name = f"{row.number} · {row.title}" if row.number is not None else row.title
    if to == PERSON:
        origin = {"made": PERSON, "mine": True, "by": "owner"}
        did = f"{name} is yours: it shows with your own tasks"
    elif to == "process":
        # The process that made it, where that is known; Rouh where it is not.
        was = origins(store).get(row.id) or {}
        named = process_of(was) or process_of(classify(root if root is not None else _root(),
                                                       {"id": row.id, "folder": row.folder,
                                                        "number": row.number}) or {})
        origin = dict(process(named or "rouh", "The owner said so"), by="owner")
        said = words(origin)
        did = f"{name} is marked as {said[:1].lower() + said[1:]}: it is with Made by Rouh now"
    else:
        root = _root() if root is None else root
        owner = _owner() if owner is None else owner
        found = None
        if owner is not None and root:
            contacts = trust.TrustStore().all(owner.user_id, owner.org_id)
            found = requester(owner, root, {"id": row.id, "folder": row.folder},
                              contacts=contacts, case=_case_chats(owner, store).get(row.id))
        origin = dict(found or {"for": "someone else", "email": "", "telegram": "",
                                "channel": "", "why": "The owner said so"}, made=OTHER, by="owner")
        did = (f"{name} is marked as made for {origin['for']}: it is with others' tasks now")
    was = made(origins(store).get(row.id))
    _write(row.id, origin, by="owner", only_if_unsaid=False)
    # And the steps under it that were only its maker's because it was: what he said of the
    # task he said of them. A step he has said something of himself is left as he said.
    for step in _steps_under(row.id):
        now = origins(store).get(step) or {}
        if made(now) == was and not said_by_person(now):
            called = _called({"id": row.id, "number": row.number, "folder": row.folder})
            _write(step, dict(origin, why=f"The owner said so of its task, {called}"),
                   by="owner", only_if_unsaid=False)
    log.info("task origin: the owner said %s (%s) is %s", name, row.folder,
             "his own" if to == PERSON else words(origin).lower())
    return {"ok": True, "did": did, "origin": public(origin)}


def _steps_under(task_id: str) -> list[str]:
    """Every step under a task, however deep, by id."""
    from .models import Link

    under: dict[str, list[str]] = {}
    for src, dst in Link.objects.filter(rel="owns", src_type="task", dst_type="task") \
            .values_list("src_id", "dst_id"):
        under.setdefault(src, []).append(dst)
    out, stack = [], list(under.get(task_id, []))
    while stack and len(out) < 2000:
        one = stack.pop()
        out.append(one)
        stack.extend(under.get(one, []))
    return out




__all__ = ["CHANNEL_WORDS", "ENV", "OTHER", "PERSON", "PROCESS", "PROCESSES", "SHOW", "as_found",
           "at_birth", "backfill", "by_process", "by_run", "classify", "current", "hidden", "his",
           "inherited", "made", "made_for", "making", "mark_made_by", "mark_run_work", "mine",
           "origins", "others", "process", "process_of", "process_words", "public", "requester",
           "run_maker", "said_by_person", "same_maker", "set_by_person", "show", "showing", "sweep",
           "sweep_quietly", "under", "words"]
