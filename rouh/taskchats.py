"""Which chats a task owns, and which tasks' chats look as if they belong to another task.

3 and 4 November 2026: twice a chat was given to a task it was never about, and twice
the run that went to repair it had no way to read, from its own seat, which chats a task owned
and in what order: the database is Rouh's, and a run reaches it only through Rouh. So this is
that read, for `rouh-task show` and `rouh-task chats-check` (`rouh/web/taskapi.py`), and it
changes nothing.

A task's main chat is its oldest owning link (`conversations._chat_of`). A chat looks mis-bound
(`misbound`) when it is owned by one task and:

- it is a fork (`chat_fork`, cut or not) of a chat another task owns: the shape seen on
  30 October 2026, a fork of one task's chat adopted by a task a landing was misread as having
  made (`conversations.adopt_made_task`); or
- every run started from it that is filed under a task is filed under one other task: the
  conversation's work went somewhere else.

Neither is proof - the person can move a chat on purpose (`promote`, `owning.detach_fork_into`)
- so the check only lists, with the reason, and a repair is somebody's deliberate act.
"""
from __future__ import annotations

from collections import defaultdict


def _tasks(ids) -> dict[str, dict]:
    from .models.objects import Task

    return {row["id"]: row for row in Task.objects.filter(id__in=set(ids))
            .values("id", "number", "title", "folder", "created_at")}


def _label(task: dict | None) -> str:
    if task is None:
        return "a task that is gone"
    number = task.get("number")
    return f"task {number}" if number is not None else f"step {task.get('folder')}"


def of_task(task_id: str) -> list[dict]:
    """The chats this task owns, main first (oldest link), each with what it hangs off."""
    from .models.memory import TranscriptMessage
    from .models.objects import Chat, ChatFork, Link

    links = list(Link.objects.filter(rel="owns", src_type="task", src_id=task_id,
                                     dst_type="chat").order_by("created_at", "id")
                 .values_list("dst_id", "created_at"))
    ids = [chat for chat, _ in links]
    chats = {row["id"]: row for row in Chat.objects.filter(id__in=ids)
             .values("id", "title", "created_at")}
    forks = {row["chat_id"]: row for row in ChatFork.objects.filter(chat_id__in=ids)
             .values("chat_id", "parent_id", "cut_at")}
    parents = {row["dst_id"]: row["src_id"] for row in Link.objects.filter(
        rel="owns", src_type="task", dst_type="chat",
        dst_id__in={f["parent_id"] for f in forks.values()}).values("dst_id", "src_id")}
    owners = _tasks(parents.values())
    said: dict[str, int] = defaultdict(int)
    for session in TranscriptMessage.objects.filter(session_id__in=ids) \
            .values_list("session_id", flat=True):
        said[session] += 1
    # The forks hanging off each (uncut), which are the task's conversation too, though no
    # task owns them: the 30 October repair laid 139's security fork out this way.
    under: dict[str, list[dict]] = defaultdict(list)
    hanging = list(ChatFork.objects.filter(parent_id__in=ids, cut_at__isnull=True)
                   .values_list("parent_id", "chat_id"))
    named = dict(Chat.objects.filter(id__in={c for _, c in hanging}).values_list("id", "title"))
    for parent, child in hanging:
        if child in named:
            under[parent].append({"id": child, "title": named[child] or ""})
    out = []
    for chat_id, linked_at in links:
        if chat_id not in chats:
            continue
        fork = forks.get(chat_id)
        parent_task = parents.get(fork["parent_id"]) if fork else None
        out.append({
            "id": chat_id, "title": chats[chat_id]["title"] or "",
            "main": not any(o["main"] for o in out),
            "messages": said[chat_id], "created_at": chats[chat_id]["created_at"],
            "linked_at": linked_at,
            "fork_of": fork["parent_id"] if fork else "",
            "fork_cut": bool(fork and fork["cut_at"]),
            "fork_of_task": (_label(owners.get(parent_task))
                             if parent_task and parent_task != task_id else ""),
            "forks": under[chat_id],
        })
    return out


def misbound() -> list[dict]:
    """Every task-owned chat that looks as if it belongs to another task, with why."""
    from .models.objects import Chat, ChatFork, Link

    owned = dict(Link.objects.filter(rel="owns", src_type="task", dst_type="chat")
                 .values_list("dst_id", "src_id"))
    titles = dict(Chat.objects.filter(id__in=owned).values_list("id", "title"))
    found: dict[str, dict] = {}

    def note(chat_id: str, why: str, other: str) -> None:
        one = found.setdefault(chat_id, {"chat": chat_id, "title": titles.get(chat_id) or "",
                                         "task_id": owned[chat_id], "why": [], "others": []})
        one["why"].append(why)
        one["others"].append(other)

    for chat_id, parent in ChatFork.objects.filter(chat_id__in=owned) \
            .values_list("chat_id", "parent_id"):
        there = owned.get(parent)
        if there and there != owned[chat_id]:
            note(chat_id, "a fork of a chat another task owns", there)

    started = defaultdict(set)
    for run, chat in Link.objects.filter(rel="from", src_type="run", dst_type="chat",
                                         dst_id__in=owned).values_list("src_id", "dst_id"):
        started[chat].add(run)
    homes = dict(Link.objects.filter(rel="owns", src_type="task", dst_type="run",
                                     dst_id__in={r for rs in started.values() for r in rs})
                 .values_list("dst_id", "src_id"))
    for chat_id, runs in started.items():
        filed = {homes[r] for r in runs if r in homes}
        if len(filed) == 1 and owned[chat_id] not in filed:
            note(chat_id, "every run started in it is filed under another task", filed.pop())

    tasks = _tasks({*owned.values(), *(o for f in found.values() for o in f["others"])})
    mains = {}
    for chat_id, task_id in Link.objects.filter(rel="owns", src_type="task", dst_type="chat",
                                                src_id__in={f["task_id"] for f in found.values()}) \
            .order_by("created_at", "id").values_list("dst_id", "src_id"):
        mains.setdefault(task_id, chat_id)
    out = []
    for one in found.values():
        one["task"] = _label(tasks.get(one["task_id"]))
        one["main"] = mains.get(one["task_id"]) == one["chat"]
        one["belongs_to"] = sorted({_label(tasks.get(o)) for o in one.pop("others")})
        out.append(one)
    return sorted(out, key=lambda o: (not o["main"], o["task"]))
