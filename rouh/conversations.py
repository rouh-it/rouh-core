"""A conversation is a row, a numbered task owns it, and the folder is written out.

A thread used to be matched to a piece of numbered work by its name. A chat
carried a string - `tasks/30.jarvis` - and thread "30 Rouh" and the folder
`tasks/30.jarvis` were secretly the same thing because the two names lined up.
Nothing joined them: rename the folder and the thread was about nothing,
number a second thread the same way and two rows both claimed to be task 30.

That is gone. A conversation is a row in `objects.chat`, a piece of numbered
work is a row in `objects.task`, and what ties the two together is one row in
`objects.link` with `rel='owns'` on it. There is no name matching left anywhere
in this repository, and none may come back: the database says which chat is
task 30, and the partial unique index `link_one_owner` says it can only ever be
one of them.

The two kinds of conversation
-----------------------------

**Owned.** A chat a task owns. It has a number, it is what the person means
when they say "thirty", and what is drawn in it belongs to that task. A card
becomes one of that task's numbered steps when the person asks for it and not
before (`artifacts.file_as_step`).

**Loose.** Everything else, and most conversations are this: one question, one
answer, done. A loose chat has no owner, no number and **no folder on disk at
all**. It lives in a plain list ordered by when it was last used, and it
never appears among the numbered work. That is the whole point of this step -
a person who asks fifty small questions a week must not end up with fifty
numbered tasks - and it is why nothing here writes a folder for a chat until
the moment it is promoted.

A loose chat is promoted when the person says so, and at no other moment.
Nothing on this machine numbers a conversation by itself: not the model, not a
run started in it, not a card drawn in it. Promotion takes the next number,
keeps every message, and carries what the chat owns with it.

That is the person's own rule, given on 22 September 2026: "tasks should be
created out of chats only when I ask for it, never automatically". Until then
a run started in a loose chat numbered it (`promote_for_run`, deleted with that
rule), and a card drawn in a chat a task owned was written into that task as
its next numbered step (`artifacts.draw`, which now files nothing). Both are
gone rather than made quieter, because a thing that numbers work without being
asked is the thing being removed. What is kept is every way of asking: the item
in the chat menu, the `make_a_task` tool when they say so out loud, and the
button on a card that is not on the record yet.

The two clocks
--------------

A chat carries two times, and they answer different questions.

`last_spoke` is when anything was last **said** here, and only a turn moves
it.

`last_activity` is when the person last **used** this chat, and it is the order
the list is drawn in. A turn moves it, and so does every edit to the chat:
giving it a title, filing it under a project, keeping it, making it a task.
Opening a chat and reading it moves neither. That is the whole of what was
asked for - "the last time I used (not just opened) should be on top" - and
`touched` is the one doorway that moves it.

They are two because they answer two questions. Renaming a chat is using it,
so it goes to the top of the list; it is not saying anything in it, so
`last_spoke` is untouched.

Nothing deletes a chat
----------------------

A conversation goes when a person deletes it, and at no other moment. There is
no expiry clock, no archiving on a clock and no sweep, and none is to come
back: the person decided this on 22 September 2026, in these words - "Remove
deleting chats at 90 days. No automatic removal."

What was here until then: a loose, unpinned chat carried an `expires_at`,
thirty days of quiet archived it and ninety deleted it, messages and all, and
`ChatSweep` in the server ran that every six hours. All of it is gone - the
column, the query behind it (`objects.expiring`), the sweep and its schedule -
rather than left switched off, because a clock that is only disabled is a clock
somebody turns back on.

Keeping a chat (`pin`) is still here and still means "this one matters"; what
it no longer means is protection from a clock, because there is nothing left to
be protected from.

The database is the source of truth
-----------------------------------

The person decided this on 21 September 2026 and it governs everything here.
A task's number, its slug, its title and its state are columns of its row. The
folder `tasks/NN.slug` in the workspace is **written out from that row**, the
way a worktree is written out from a run: it is a supportive structure for
everything that reads the workspace with grep and git, and it is never read
back in as the truth.

Where the two disagree the row wins, and what is on disk is an inbound change
to reconcile rather than an override:

- a folder that no row knows about is a task somebody made by hand, and it is
  **taken in** as a row of its own
- a folder somebody renamed hands its
  change to the row, which is then the truth again
- a row whose folder is missing has the folder written out again

`reconcile` is all three, it runs whenever the tasks are asked for, and it says
in the log what it took in.

Where the turns live
--------------------

A chat's own record of what was said is `objects.message`: one row per turn,
`(chat_id, seq, role, body)`, the words and nothing else. It belongs to the
chat, it travels with it when it is promoted, and it is deleted with it - that
is the only cascade a chat has.

That is not the same thing as the tape the model is replayed from, which stays
in `memory.messages` and holds what a record has no business holding: the tool
calls, the results, the tries behind a question that was asked four times, the
blocks a screenshot arrived as. One write path writes both (`memory.add_message`
calls `add_turn`), so the record cannot drift from the transcript.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path

from django.db import DatabaseError, IntegrityError

from . import chats as chat_titles
from . import objects
from .config import config
from .models.memory import AppState
from .models.objects import ChatFork

log = logging.getLogger("rouh.conversations")

#: The one thread that is always there: the person and Rouh talking, loose talk,
#: anything with no home yet. It is loose and stays loose however much work is
#: started in it - it is the place things are said before they are anything -
#: so it is the one conversation `promote` refuses. `memory.CONVERSATION` is
#: this, and there is one of it. A run asked for here reports here, like a run
#: asked for in any other chat; a run no conversation started keeps its report
#: on the run (`runs.report_chat`, `runs.report_stays`).
GENERAL = "conversation"

#: What a chat with no title of its own is called. The same standing title
#: `memory.py` has always handed the page.
UNTITLED = "\N{SPEECH BALLOON} New chat"


def is_untitled(title: str | None) -> bool:
    """Whether a title is really no title at all.

    Empty is, and so are the words of the standing title, with or without a
    picture in front of them. Those words were once written down as a chat's
    name - a run started in a chat before it had been named copied what the
    row showed into it, on 22 September 2026 - and a chat with a name is never
    named again (`ChatNames`), so that chat said "New chat" for good. The page
    also offers the name on screen to be typed over, and pressing OK on
    "💬 New chat" is not choosing it. So those words are read as untitled
    wherever they came from, and never stored as a name.
    """
    words = " ".join((title or "").split())
    while words and chat_titles.is_emoji(words[0]):
        words = words[1:].strip()
    return words.casefold() in ("", "new chat")


#: The longest a chat's title may be, and a project's name. The same two
#: numbers `memory.py` kept when these were its own rows.
MAX_TITLE = 60
MAX_PROJECT_NAME = 40

#: How deep the walk under a project goes before it stops. Deeper than anything
#: the hierarchy allows - project, project, task, task, chat, run, artifact -
#: so it is a guard against a ring somebody wrote by hand, not a limit on the
#: shape of anybody's work.
DEEP = 8

#: A task folder: a number, a separator, and the slug.
_FOLDER = re.compile(r"^(\d+)[.-](.+)$")

#: A task's five-word status as the three-word state the row also keeps.
#: Kept by this name for the callers that have always said it; the vocabulary
#: is the models' (`STATUS_STATE`), and both words are the row's alone since
#: 6 October 2026 (`rouh/taskrecord.py`).
DISK_STATE: dict[str, str] = {"": "open", **objects.STATUS_STATE}


# ---------------------------------------------------------------------------
# The one store
# ---------------------------------------------------------------------------


def store() -> objects.ObjectStore:
    """The store every one of these tables is read and written through.

    `objects.shared_store` is the one connection: runs, artifacts and
    conversations are rows of the same five tables, and two connections to one
    file would be two locks that know nothing about each other.

    This one raises rather than answering None, which is the difference between
    the conversations and the other two. A run register that cannot be opened
    costs a task list and a card falls back to the old screen; a conversation
    store that cannot be opened means there are no conversations, and drawing
    an empty page over a database that is perfectly fine is worse than saying
    so. It is also why this is not behind `objects.enabled()`: since step three
    there is nowhere else for a conversation to live.
    """
    st = objects.shared_store(even_when_off=True)
    if st is None:                                           # pragma: no cover
        raise RuntimeError("the object store could not be opened")
    return st


def close() -> None:
    """Let the file go. Only a check of somebody's own needs this."""
    objects.close_shared()


def _root() -> str:
    """The person's workspace, or "" when this machine has no copy of it."""
    root = config.assistant_repo or ""
    return root if root and os.path.isdir(root) else ""


# ---------------------------------------------------------------------------
# A chat, as the page reads one
# ---------------------------------------------------------------------------


def _as_row(chat: objects.Chat, *, task: objects.Task | None = None,
            project: str | None = None, said: int = 0,
            thread: bool = False) -> dict:
    """One chat, in the words the page and the rest of Rouh already use.

    `task` is the task that owns it, if one does, and is what makes the row a
    piece of numbered work: `task` carries the folder the person says out loud
    and `number` carries the number. A loose chat has neither and says so.

    `thread` is whether this is **the** conversation of that task, the one
    opening the task opens (`_chat_of`), rather than another chat somebody
    put under it with Move this chat. The page needs to know which: the
    task's own address brings back its own conversation, so any other chat
    under it has to be named in the address beside it (`addrIsTheChats`).
    """
    title = (chat.title or "").strip()
    if is_untitled(title):
        title = ""
    if task is not None:
        title = _unnumbered(title, task.number)
    return {
        "id": chat.id,
        "title": title or UNTITLED,
        "titled": bool(title),
        "folder_id": project,
        # The workspace folder this chat **is**, written out from the task row
        # that owns it rather than matched to it by name.
        "task": task.folder if task else "",
        # And that task's id, because a folder is an address and not a name to
        # act on: deleting a thread that is a task deletes the task, and the
        # one delete takes ids (`owning.remove`).
        "task_id": task.id if task else "",
        "number": task.number if task else None,
        "loose": task is None,
        "thread": bool(task is not None and thread),
        "pinned": bool(chat.pinned),
        "unread": bool(chat.unread),
        "created_at": chat.created_at,
        # What the page orders the list by and writes "3 min ago" from: when
        # the person last used this chat, which is speaking in it or editing
        # it and never opening it. `last_spoke` is the other clock and the
        # page has no use for it.
        "updated_at": chat.last_activity,
        "messages": said,
    }


def _unnumbered(title: str, number: int | None) -> str:
    """A task's chat's title without the task's number in front of it.

    Until 29 September 2026 the chat a task opened was titled "💬 3 Project
    documents", and every row that draws it puts the task's number at its end,
    so the Chats list read "💬 3 Project documents 3" (fr_056661da4c08). A chat
    is titled by its task's name alone now (`_drafted_title`); this is for the
    ones already written down with the number, and only takes it off when it
    is the number of the task that holds the chat.
    """
    if number is None or not title:
        return title
    head = ""
    if chat_titles.starts_with_emoji(title):
        head, _, rest = title.partition(" ")
        head += " "
    else:
        rest = title
    lead, _, name = rest.partition(" ")
    if lead != str(number) or not name.strip():
        return title
    return head + name.strip()


def _project_over(st: objects.ObjectStore, kind: str, obj_id: str) -> str | None:
    """Which project this is filed under, walking up whatever owns it.

    A chat a task owns is in the task's project, because ownership points down
    `project > task > chat` and a chat has one owner at most: filing the chat
    under a project would mean taking it away from its task. So the question is
    asked of whoever holds it.
    """
    seen = 0
    while seen < len(objects.KINDS):
        owner = st.owner_of(kind, obj_id)
        if owner is None:
            return None
        if owner[0] == "project":
            return owner[1]
        kind, obj_id = owner
        seen += 1
    return None


def project_of(kind: str, obj_id: str) -> str:
    """Which project this object is filed under, or "" for none.

    The public way to ask `_project_over`, for a caller that has an id and no
    store: a kept note wants the project the conversation is in
    (`rouh/keeping.py`), and reading the whole `chat` row to find it would be
    a page of work for one string.
    """
    return _project_over(store(), kind, obj_id) or ""


def chat(chat_id: str) -> dict | None:
    """One conversation, or None when there is no such conversation."""
    st = store()
    row = st.get_chat(chat_id)
    if row is None:
        return None
    task = task_of(chat_id)
    first = (next(iter(st.children_of("task", task.id, "chat")), None)
             if task is not None else None)
    out = _as_row(row, task=task,
                  project=_project_over(st, "chat", chat_id),
                  said=int(st.message_counts([chat_id]).get(chat_id, 0)),
                  thread=first == ("chat", chat_id))
    # The chat this one was forked from, or "" for a chat that is nobody's
    # fork (`rouh/forks.py`). Only on the one row: a fork is never in the list
    # `all_chats` draws, so nothing there has one to say. A fork that became
    # a task's chat was cut from where it came off, and says nothing of it: its
    # parent is the task (`forks.cut`).
    out["fork_of"] = (ChatFork.objects.filter(chat_id=chat_id, cut_at__isnull=True)
                      .values_list("parent_id", flat=True).first() or "")
    return out


def all_chats(*, limit: int = 300) -> list[dict]:
    """Every conversation, the one used most recently first.

    One read of each table rather than a query per row: the list is drawn again
    every time anything about any chat changes, which on a busy afternoon is
    several times a minute.
    """
    st = store()
    # A fork is laid out beside the chat it came off and is in no list: "I
    # don't think I want those subchats in the list anywhere. They're just
    # attachments to the main chat" (`rouh/forks.py`). Left out before the
    # limit is counted, so a busy afternoon of forks never pushes a real chat
    # off the end.
    forked = set(ChatFork.objects.filter(cut_at__isnull=True)
                 .values_list("chat_id", flat=True))
    # And a chat archived, which is kept and read where it belongs and is in
    # no list: the chats a goal's streams were worked in for an afternoon on
    # 27 September 2026, before a goal had exactly one chat
    # (`goals.retire_stream_chats`). Nothing archives a chat on a clock.
    forked |= {row.id for row in st.list_chats(state="archived", limit=None)}
    counted = bool(limit) and limit > 0
    wanted = limit + len(forked) if counted else limit
    rows = [row for row in st.list_chats(limit=wanted) if row.id not in forked]
    if counted:
        rows = rows[:limit]
    said = st.message_counts()
    tasks = {t.id: t for t in st.list_tasks(limit=limit * 2)}
    links = st.refs(objects.OWNS)
    owners = {(link.dst_type, link.dst_id): (link.src_type, link.src_id)
              for link in links}
    # Each task's own conversation: the oldest chat it owns, which is the one
    # `_chat_of` answers with. The links come oldest first.
    threads: dict[str, str] = {}
    for link in links:
        if link.src_type == "task" and link.dst_type == "chat":
            threads.setdefault(link.src_id, link.dst_id)
    out = []
    for row in rows:
        owner = owners.get(("chat", row.id))
        task = tasks.get(owner[1]) if owner and owner[0] == "task" else None
        project = None
        walk = owner
        while walk is not None:
            if walk[0] == "project":
                project = walk[1]
                break
            walk = owners.get(walk)
        out.append(_as_row(row, task=task, project=project,
                           said=int(said.get(row.id, 0)),
                           thread=task is not None and threads.get(task.id) == row.id))
    return out


def ensure_chat(chat_id: str, *, title: str | None = None,
                pinned: bool = False) -> dict:
    """The chat with that id, made if it is not there yet.

    How the one thread that is always there comes into being, and how a chat
    that something still points at - an active chat in `app_state`, an id in a
    tab that has been open since yesterday - is never allowed to be a dangling
    id.
    """
    st = store()
    row = st.get_chat(chat_id)
    if row is None:
        row = st.create_chat(id=chat_id, title=title, pinned=pinned)
    return chat(chat_id) or _as_row(row)


def new_chat(title: str | None = None, project_id: str | None = None) -> str:
    """An empty, loose conversation, and its id.

    Loose is the only thing a new chat can be: nothing has said it is a piece
    of numbered work, so it takes no number and no folder. `promote` is what
    changes that, and a run started here does it by itself.
    """
    st = store()
    named = ("" if is_untitled(title)
             else chat_titles.ensure_emoji(title or "")[:MAX_TITLE].strip())
    row = st.create_chat(id="chat-" + uuid.uuid4().hex[:12], title=named or None)
    if project_id and st.get_project(project_id) is not None:
        st.attach("project", project_id, "chat", row.id)
    return row.id


def rename(chat_id: str, title: str) -> dict | None:
    """Give a conversation a title, by hand or from the model.

    Every title starts with an emoji, the person's own as much as the model's,
    for the reason `rouh/chats.py` gives. An empty title puts the chat back
    to untitled, which also puts it back in the way of the automatic one, and
    so does the standing title's own "New chat" (`is_untitled`).

    Naming a chat is editing it, so it goes to the top of the list. The model's
    own naming lands there too and costs nothing: it runs in the breath after
    the first exchange, which had already put the chat at the top.
    """
    st = store()
    if st.get_chat(chat_id) is None:
        return None
    named = ("" if is_untitled(title)
             else chat_titles.ensure_emoji(title)[:MAX_TITLE].strip())
    st.update_chat(chat_id, title=named or None)
    touched(chat_id)
    return chat(chat_id)


def _arranged_in_the_workspace(st: objects.ObjectStore, task: objects.Task) -> bool:
    """Whether this task sits inside the workspace tree rather than loose.

    A task whose owner is one of the person's own projects, or nothing at all,
    has its folder in `unfiled/` - that is the rule `_new_numbered_task` keeps
    - so giving it to another such project is a link and nothing else, and the
    disk is right either way.

    A task inside a folder of the workspace, or inside another task, is a
    directory in a git repository with the person's work in it. Moving that is
    `objecttree.move`, which writes the link and then moves the folder with
    `git mv` so `git log --follow` goes on working. Writing the link here and
    leaving the folder where it was is the state stage four exists to make
    impossible: measured on 22 September 2026, filing the chat of task 49 into
    a project of the person's own left the row saying the task was in that
    project while `work/acme/49.vendor-proposal` sat untouched on disk, and
    nothing anywhere said so.
    """
    owner = st.owner_of("task", task.id)
    if owner is None:
        return False
    if owner[0] == "task":
        return True
    holder = st.get_project(owner[1]) if owner[0] == "project" else None
    return bool(holder is not None and holder.folder)


def set_project(chat_id: str, project_id: str | None) -> dict | None:
    """File a conversation under a project, or take it out of every project.

    A chat a task owns is filed by filing its task: ownership points down
    `project > task > chat` and a chat has one owner at most, so putting the
    chat itself under the project would be taking it away from its task.

    A task that is arranged in the workspace is refused, because moving one is
    moving a folder and this is not the path that moves folders
    (`_arranged_in_the_workspace`). The chat comes back unchanged, so the list
    redraws it where it really is; the page does not offer the move at all.

    Filing a chat is using it, so it goes to the top of the list.

    General is never filed. It is the one thread that is always there and
    loose (`GENERAL`), so putting it under a project would draw the place
    everything with no home is said as if it were a chat of that project -
    which is what the person saw on 29 September 2026, General sitting under
    Rouh (`let_general_go`).
    """
    st = store()
    if st.get_chat(chat_id) is None:
        return None
    if chat_id == GENERAL and project_id:
        log.info("General is not filed under a project (%s)", project_id)
        return chat(chat_id)
    task = task_of(chat_id)
    if task is not None and _arranged_in_the_workspace(st, task):
        log.info("chat %s is task %s, which is arranged in the workspace at %s,"
                 " so it is not filed from the chat list", chat_id,
                 task.number, task.folder)
        return chat(chat_id)
    kind, obj_id = ("task", task.id) if task is not None else ("chat", chat_id)
    if project_id:
        holder = st.get_project(project_id)
        if holder is None:
            return chat(chat_id)
        if task is not None and holder.folder:
            # The other way into the same fault: a task with a folder in
            # `unfiled/` given to a project that is a folder of the workspace
            # would be a row inside Work with its directory outside it.
            log.info("task %s is not put inside the workspace folder %s from"
                     " the chat list", task.number, holder.folder)
            return chat(chat_id)
        st.attach("project", project_id, kind, obj_id)
    else:
        owner = st.owner_of(kind, obj_id)
        if owner is not None and owner[0] == "project":
            st.detach(kind, obj_id)
    touched(chat_id)
    return chat(chat_id)


def pin(chat_id: str, on: bool = True) -> dict | None:
    """Mark a conversation as one to keep in view, or take the mark off.

    A mark and nothing more since the clock went: no chat is deleted or
    archived by anything but a person, so keeping one is the person saying
    "this one matters" rather than buying it a stay of execution. The rail
    draws it, and a chat a task owns carries no mark because its number is one.

    Keeping a chat is using it, so it goes to the top of the list.
    """
    st = store()
    if st.get_chat(chat_id) is None:
        return None
    st.update_chat(chat_id, pinned=bool(on))
    touched(chat_id)
    return chat(chat_id)


def mark_unread(chat_id: str, unread: bool = True) -> None:
    """Say whether this conversation has something in it nobody has seen.

    Set when a turn finishes in a chat that is not the one on screen, and
    cleared the moment that chat is opened. A flag rather than a count, for the
    reason it has always been one: the question is "is there anything new in
    here", which is what a dot answers.
    """
    st = store()
    if st.get_chat(chat_id) is not None:
        st.update_chat(chat_id, unread=bool(unread))


def touched(chat_id: str, at: float | None = None) -> None:
    """This chat was used just now: move the clock the list is ordered by.

    The one doorway for "the person did something to this chat". Speaking in it
    comes through `spoke`, which moves `last_spoke` as well as this one;
    everything else that is an edit - giving it a title, filing it under a
    project, keeping it, making it a task - calls this and nothing else.

    What is deliberately not here: opening a chat, reading it, and the unread
    dot being cleared because it was opened. That is the whole of the rule the
    person asked for - "the last time I used (not just opened) should be on
    top" - and the reason it is a clock of its own rather than `last_spoke`.
    """
    st = store()
    if st.get_chat(chat_id) is None:
        return
    st.update_chat(chat_id, last_activity=at if at is not None else time.time())


def spoke(chat_id: str, at: float | None = None) -> None:
    """Something was said here just now: move both clocks.

    `last_spoke` because a turn is the only thing that counts as speaking, and
    `last_activity` because speaking in a chat is the plainest way of using
    one.
    """
    st = store()
    row = st.get_chat(chat_id)
    if row is None:
        return
    now = at if at is not None else time.time()
    st.update_chat(chat_id, last_spoke=now, last_activity=now)


def add_turn(chat_id: str, role: str, text: str, *, at: float | None = None) -> None:
    """Write one turn into the chat's own record, and move its clock.

    The record is the words. A row with nothing to say in it - a tool result, a
    message that is only a screenshot - is not a turn and is not written here;
    it is in the transcript, which is where the model reads from.
    """
    said = " ".join((text or "").split())
    st = store()
    if st.get_chat(chat_id) is None:
        return
    if said:
        try:
            st.add_message(chat_id, role, said)
        except objects.Refused:
            log.exception("the chat %s would not take a turn", chat_id)
    spoke(chat_id, at)


def opening(chat_id: str, turns: int) -> list[dict]:
    """How a chat began: its first turns, oldest first, as `{role, text}`.

    Read from the chat's own record rather than from the transcript, because
    the record is the words and nothing else. The transcript is the model's
    tape, and a turn that called three tools is eight rows of it with the
    question at the top: asked for "four rows", the transcript hands back the
    newest four, which is the end of whatever was said last. That is what a
    chat was named from until 24 September 2026, so a busy first turn left the
    question out of it and the chat stayed "New chat", and a later quiet one
    named it after itself ("Send").
    """
    return [{"role": m.role, "text": m.body}
            for m in store().messages(chat_id, limit=max(1, int(turns)))]


# ---------------------------------------------------------------------------
# The numbered work
# ---------------------------------------------------------------------------


def task_of(chat_id: str) -> objects.Task | None:
    """The task that owns this conversation, or None when it is loose.

    A draft of a task's conversation has no owner yet, and is still that task's:
    a card drawn in it is the task's, and where it would be filed is the task's
    folder.
    """
    st = store()
    owner = st.owner_of("chat", chat_id)
    if owner is None:
        held = draft(chat_id)
        return st.get_task(held["task"]) if held and held.get("task") else None
    if owner[0] != "task":
        return None
    return st.get_task(owner[1])


def folder_of(chat_id: str) -> str:
    """The workspace folder this chat **is**, or "" when it is loose.

    Where a card of this chat goes when the person asks for it to be filed. It
    comes from the task row that owns the chat, so a folder somebody renamed is
    followed by the next read rather than leaving cards filed into a folder
    that is not there.
    """
    task = task_of(chat_id)
    return task.folder if task else ""


def task_by_folder(rel: str) -> objects.Task | None:
    """The task whose folder is `tasks/30.jarvis`, or None.

    A lookup on the task's own column, which is a different thing from the name
    matching this step deleted: the row owns the folder name and the folder is
    written out from it, so this asks the database what it called something
    rather than guessing from what a thread happens to be titled.
    """
    rel = (rel or "").strip().strip("/")
    if not rel:
        return None
    for row in store().list_tasks(folder=rel, limit=None):
        if row.folder == rel:
            return row
    return None


def _chat_of(st: objects.ObjectStore, task_id: str) -> dict | None:
    """The conversation a task owns, if it has one yet.

    A task owns one chat in practice and the store would allow several, so the
    oldest link wins and the rest are ignored rather than being an error: two
    rows both claiming to be task 30 is what this whole model exists to stop,
    and the way to stop it is to answer with one.
    """
    for _kind, obj_id in st.children_of("task", task_id, "chat"):
        found = chat(obj_id)
        if found is not None:
            return found
    return None


def _talked_about(st: objects.ObjectStore, task_id: str) -> bool:
    """Whether this task has a conversation written down yet.

    `_chat_of`'s question without the row it answers with, which counts every
    chat's messages to build: this is asked each time a draft is drawn.
    """
    return any(st.get_chat(obj_id) is not None
               for _kind, obj_id in st.children_of("task", task_id, "chat"))


def _task_at(rel: str) -> objects.Task | None:
    """The task at this folder, taking in a folder made by hand on the way."""
    rel = (rel or "").strip().strip("/")
    task = task_by_folder(rel)
    if task is None:
        reconcile()
        task = task_by_folder(rel)
    return task


def open_for_task(rel: str) -> dict | None:
    """The conversation that **is** this task: its own, or a draft of it.

    Opening a task is opening its conversation, but opening is not saying
    anything. A task that has a chat hands that chat back. A task that has
    none is handed a draft of one (`open_draft`): an id and a title and no
    row, so the page can stand in the task's conversation and say nothing in
    it, and nothing is left behind when it walks away. The chat is written the
    moment something is put in it (`make`), under the same id, owned by the
    task and titled by its name.

    Until 23 September 2026 the chat was made here, on the press. Every task
    the person ever clicked on was left owning an empty chat: fifteen of them
    on the live database that day, task 08 among them, which is how a task
    nobody had ever talked about came to say "1 chat" on its own page.

    None when there is no such task, which after a reconcile means there is no
    such folder either.
    """
    task = _task_at(rel)
    if task is None:
        return None
    st = store()
    found = _chat_of(st, task.id)
    if found is not None:
        return found
    return draft_row(open_draft(task_id=task.id))


def start_for_task(rel: str) -> str | None:
    """A new conversation about this task, not written down yet, and its id.

    The one chat button on a task's or a step's own page, **Start chat**
    (`taskpage.js`). Petar, 23 September 2026: "i don't need a button to
    continue chat, I need a button to start a chat". So the press always puts
    the person in an empty conversation about the task, never back into one
    with something in it:

    - A task nobody has talked about yet is handed the draft of its own
      conversation, the same draft opening the task hands out
      (`open_for_task`), and the first thing said makes it the task's own.
    - A task that has its conversation already is handed a draft of another
      one, which the first thing said files under the task as a chat of its
      own, named from what is said in it (`make`). The task's own is left
      where it is: opening the task, its line in the rail and its number said
      out loud all still go back to it, and the task's page lists every chat
      it holds under Chats.

    Pressed again before anything is said, it hands back the same draft
    (`open_draft`), so two presses are not two chats. None when there is no
    such task.
    """
    task = _task_at(rel)
    if task is None:
        return None
    return open_draft(task_id=task.id)


def answer_for_task(rel: str) -> str | None:
    """The conversation an answer from this task's question box goes into,
    and its id.

    Petar, 24 September 2026 (fr_d262eeec7d44): "when a decision is required
    of me, the cards provide choices, but that should go to the main chat,
    not opne a new chat. only open a new chat If there was no such chat
    before that." Until then an answer was Start chat with words on it
    (`start_for_task`), so a task that had its chat already was handed a
    second one for every answer: task 61 had "Acme website architecture
    review", and answering its question made "Website content integration
    task" beside it.

    So an answer goes into the chat the task already has (`answering_chat`),
    where what was said before it is, and a task that has none is handed the
    draft of its own conversation, which the answer makes the task's own
    (`open_draft`), exactly as opening the task would. None when there is no
    such task.
    """
    task = _task_at(rel)
    if task is None:
        return None
    found = answering_chat(task.id)
    return found.id if found is not None else open_draft(task_id=task.id)


def answering_chat(task_id: str) -> objects.Chat | None:
    """Of the chats this task holds, the one its question is answered in, or
    None when it holds none yet.

    The one the question was raised in: a task asks because a job working on
    it stopped to ask, and that job was started from a conversation (the
    `from` reference every job the voice starts carries), so of the task's
    own chats it is the one the newest job about it came from. Where no job
    was ever started from any of them, it is the task's own conversation,
    the oldest, which is the one opening the task brings back (`_chat_of`).
    A job started from a chat the task does not hold - General, a loose chat,
    a fork - says nothing about which of the task's is meant, and is not
    counted.
    """
    st = store()
    held = [row for row in (st.get_chat(obj_id) for _kind, obj_id
                            in st.children_of("task", task_id, "chat")) if row is not None]
    if not held:
        return None
    raised, newest = "", None
    for row in held:
        for link in st.refs("from", src_type="run", dst_type="chat", dst_id=row.id):
            run = st.get_run(link.src_id)
            if run is not None and (newest is None or run.started_at > newest):
                raised, newest = row.id, run.started_at
    return next((row for row in held if row.id == raised), held[0])


# ---------------------------------------------------------------------------
# A conversation that is not written down until something is said in it
# ---------------------------------------------------------------------------
#
# Opening a task and pressing New chat both put the person in a conversation
# before anything has been said, and neither may leave a row behind if nothing
# ever is. The person's rule, 23 September 2026: a chat is created on the first
# message, and never for a task until there is something to put in it.
#
# So both hand out a **draft**: the id the chat will have, and what it will
# belong to, remembered in `app_state` and nowhere else. The page stands in it
# exactly as it stands in a chat - the id is the one its turns, its uploads and
# its address are keyed by - and the chat is written, under that same id, by
# the first thing that puts something in it: a turn (`Turns.start`, and
# `memory.add_message` under it), or a card (`artifacts.ensure_chat`). Because
# the id does not change, nothing on the screen has to move when that happens.
#
# A draft is not a chat. It is in no list, it is under no task, it has no
# messages and nobody can rename, keep or delete it; `chat()` does not answer
# for it and `draft_row()` does.

#: Where the drafts are remembered, in `app_state`: a short list, newest last,
#: of `{"id", "task", "project", "at"}`.
DRAFTS = "draft_chats"

#: How many drafts are remembered. The active one is always the newest; the
#: few before it are kept so that a turn asked from a tab one switch behind the
#: others still finds the draft it was asked in rather than writing into an id
#: nothing will ever make.
DRAFTS_KEPT = 8

#: Two turns making the same draft at once, from two threads, must make one
#: chat. The store's own lock is per write; this one is around the whole of
#: "is it still a draft, then write it".
_MAKING = threading.Lock()


def _drafts() -> list[dict]:
    raw = AppState.objects.filter(key=DRAFTS).values_list("value", flat=True).first()
    try:
        got = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [d for d in got if isinstance(d, dict) and d.get("id")] if isinstance(got, list) else []


def _keep_drafts(rows: list[dict]) -> None:
    AppState.objects.bulk_create(
        [AppState(key=DRAFTS, value=json.dumps(rows[-DRAFTS_KEPT:]))],
        update_conflicts=True, unique_fields=["key"], update_fields=["value"])


def open_draft(*, task_id: str = "", project_id: str = "") -> str:
    """The id of a conversation that is not written down yet, and what it is for.

    About a task, when `task_id` is given: its own conversation while it has
    none, and another one beside it once it has (`start_for_task`). A loose
    chat filed under a project, when `project_id` is; a loose chat and nothing
    more when neither is. Opening the same task's draft again hands back the
    same id, so a file attached in it and a reload of the page both come back
    to the same place.
    """
    task_id = task_id or ""
    # A task's conversation is the task's, whatever project it sits in.
    project_id = "" if task_id else (project_id or "")
    rows = _drafts()
    for row in reversed(rows):
        if (row.get("task") or "") == task_id and (row.get("project") or "") == project_id \
                and store().get_chat(row["id"]) is None:
            rows.remove(row)
            rows.append(row)
            _keep_drafts(rows)
            return str(row["id"])
    made = {"id": "chat-" + uuid.uuid4().hex[:12], "task": task_id,
            "project": project_id, "at": time.time()}
    rows.append(made)
    _keep_drafts(rows)
    return made["id"]


def draft(chat_id: str) -> dict | None:
    """What this id was drafted for, while it is a draft and nothing more.

    None once the chat has been written, and None for a draft whose task has
    since been deleted: there is nothing left for it to be the conversation
    of, and the person is put back in General like anybody whose chat went.
    """
    chat_id = (chat_id or "").strip()
    if not chat_id:
        return None
    held = next((d for d in _drafts() if d.get("id") == chat_id), None)
    if held is None:
        return None
    st = store()
    if st.get_chat(chat_id) is not None:
        return None
    if held.get("task") and st.get_task(held["task"]) is None:
        return None
    return held


def _drafted_title(task: objects.Task | None) -> str:
    """What a draft will be called: its task's name, or nothing.

    The name alone. The number is the task's, and every place that draws the
    chat puts it beside the name rather than in it (`_unnumbered`).
    """
    if task is None:
        return ""
    return chat_titles.ensure_emoji(task.title or "")[:MAX_TITLE].strip()


def draft_row(chat_id: str) -> dict | None:
    """A draft, in the shape the page reads a chat in, or None.

    `draft` is what tells the two apart, and `messages` is 0 because a draft
    has none. `owned_by` is on it here rather than being worked out from the
    link table, because a draft has no link: it is what the chat will belong to
    once it is made, which is what the page names above the conversation.
    """
    held = draft(chat_id)
    if held is None:
        return None
    st = store()
    task = st.get_task(held["task"]) if held.get("task") else None
    project = (st.get_project(held["project"])
               if not task and held.get("project") else None)
    # The task's own conversation while the task has none, and then titled by
    # it; another one about it once it has, which is named by what is said in
    # it like any other chat (`start_for_task`).
    own = task is not None and not _talked_about(st, task.id)
    title = _drafted_title(task) if own else ""
    if task is not None:
        owner = {"type": "task", "id": task.id, "label": task.title,
                 "number": task.number, "folder": task.folder or ""}
        # A subtask's chat is the subtask's, and says which task is above it
        # (`rouh/subtasknotes.py`).
        from . import subtasknotes

        parent = subtasknotes.describe_parent(task.id)
        if parent is not None:
            owner["parent"] = parent
            owner["step"] = subtasknotes.step_number(task)
        over = _project_over(st, "task", task.id)
    elif project is not None:
        owner = {"type": "project", "id": project.id, "label": project.title,
                 "number": project.number}
        over = project.id
    else:
        owner, over = None, None
    at = float(held.get("at") or time.time())
    return {
        "id": held["id"],
        "title": title or UNTITLED,
        "titled": bool(title),
        "folder_id": over,
        "task": task.folder if task else "",
        "task_id": task.id if task else "",
        "number": task.number if task else None,
        "loose": task is None,
        "thread": own,
        "pinned": False,
        "unread": False,
        "created_at": at,
        "updated_at": at,
        "messages": 0,
        "draft": True,
        "owned_by": owner,
        "project_id": over or "",
    }


def make(chat_id: str) -> dict | None:
    """Write a draft down, because something is being put in it.

    The chat keeps the draft's id, takes the title the draft showed, and
    belongs to what the draft was for: its task, or the project a chat was
    started in. None when there was nothing to make - the id was never a draft,
    or it has already been made - which is every call after the first, so the
    doorways that call this on every turn cost one small read and nothing else.
    """
    chat_id = (chat_id or "").strip()
    if not chat_id:
        return None
    with _MAKING:
        held = draft(chat_id)
        if held is None:
            return None
        st = store()
        task = st.get_task(held["task"]) if held.get("task") else None
        # Titled by its task only when it is the task's own conversation: a
        # second one called "Jarvis" beside the first could not be told
        # apart from it, so it is left untitled and named from its first
        # exchange (`ChatNames`).
        own = task is not None and not _talked_about(st, task.id)
        title = _drafted_title(task) if own else ""
        try:
            st.create_chat(id=chat_id, title=title or None)
        except IntegrityError:
            # Made by another process in the same instant. It is there, and
            # that is all this was for.
            return None
        if task is not None:
            st.attach("task", task.id, "chat", chat_id)
        elif held.get("project") and st.get_project(held["project"]) is not None:
            st.attach("project", held["project"], "chat", chat_id)
        _keep_drafts([d for d in _drafts() if d.get("id") != chat_id])
    if task is not None:
        log.info("made the conversation for task %s (%s), on the first thing"
                 " put in it", task.number, task.folder)
    else:
        log.info("made the chat %s, on the first thing put in it", chat_id)
    return chat(chat_id)


def tasks(*, reconcile_first: bool = True) -> list[dict]:
    """Every piece of numbered work, highest number first.

    Answered from the rows, which are the truth. The workspace is read on the
    way past so that a folder somebody made by hand is taken in first: that is
    an inbound change, not an override, and after it the row is what this
    answers from.
    """
    if reconcile_first:
        reconcile()
    st = store()
    rows = [t for t in st.list_tasks(limit=None) if t.number is not None]
    rows.sort(key=lambda t: (-(t.number or 0), t.folder))
    mine: dict[str, str] = {}
    for link in st.refs(objects.OWNS, src_type="task", dst_type="chat"):
        mine.setdefault(link.src_id, link.dst_id)
    filed: dict[str, str] = {}
    for link in st.refs(objects.OWNS, src_type="project", dst_type="task"):
        filed[link.dst_id] = link.src_id
    return [{
        "rel": t.folder,
        "number": t.number,
        "name": t.title,
        "slug": t.slug,
        # The workspace's own word for the state, because this is what the
        # page colours a row by and what the workspace's index shows.
        "status": t.status,
        "state": t.state,
        "chat": mine.get(t.id, ""),
        "folder_id": filed.get(t.id),
    } for t in rows]


def slug_of(title: str) -> str:
    """A folder's slug from a title, which is `objecttree.slug_of` and nothing else.

    One rule for a folder name, in the module that writes folders.
    """
    from . import objecttree

    return objecttree.slug_of(title)


#: The task a chat was just promoted to, read once by whoever tells the page. A
#: promotion makes a task row, and the rail's Tasks list, the owner dialog and
#: what a run may be attached to are all drawn from that one message - so the
#: page has to be told. The press in the chat menu tells it itself
#: (`promote_thread` in the server); this is for the promotion that happens
#: inside a turn, when the person asks for a task out loud and the model calls
#: `make_a_task`. A flag rather than a callback because there is one reader and
#: the answer is "since you last asked".
#:
#: The task's id rather than a bare yes, because the reader does two things
#: with it now: it redraws the lists, and it files the new task under the
#: project it belongs in (`rouh/filing.py`). "" is no promotion, which reads
#: the same way the flag did.
_promoted = ""


def promotion_to_announce() -> str:
    """The task a chat was promoted to since this was last asked, or "". Clears it."""
    global _promoted
    was, _promoted = _promoted, ""
    return was


def _new_numbered_task(st: objects.ObjectStore, title: str, *,
                       project: str = "") -> objects.Task | None:
    """A numbered task, through the one create path, with its folder written out.

    `objecttree.create` is that path since stage four: it takes the next number
    off the object rows, writes the row and its owner link in one transaction,
    and then writes the folder, the `.object.json` sidecar and the AGENTS.md out
    of that row. Nothing here picks a number by looking at what is on disk.

    Where it goes. A project that is a folder in the workspace holds the new
    task inside it. One of the person's own projects for chats is not a folder
    at all, so it owns the task as a link and the folder goes to `unfiled/`,
    which is where a task nobody has filed belongs.

    A machine with no workspace on it still gets the row: a promoted
    conversation has a number whether or not there are folders anywhere.
    """
    from . import objecttree

    root = _root()
    holder = st.get_project(project) if project else None
    inside = project if holder is not None and holder.folder else ""
    if root and objecttree.has_map(root):
        try:
            made = objecttree.create(root, st, type="task", title=title, owner=inside)
        except (objecttree.Refused, OSError):
            log.exception("a task folder could not be made for %r", title)
            return None
        task = st.get_task(made["id"])
    else:
        log.info("no workspace on this machine, so %r is a row and no folder", title)
        task = None
        for _try in range(4):
            try:
                task = st.create_task(title, number=st.next_task_number(), state="open")
                break
            except IntegrityError:
                log.warning("that task number was taken; trying the next")
    if task is None:
        return None
    # Owned by the project whichever way it was made: `objecttree.create` has
    # written the link already when there was a folder to make, and a row made
    # without one - a project for chats, or no workspace on this machine - is
    # given it here.
    if project and holder is not None and st.owner_of("task", task.id) is None:
        st.attach("project", project, "task", task.id)
    return task


#: What a task made from a chat nobody has named yet is called, until it is.
UNTITLED_TASK = "Untitled task"


def promote(chat_id: str, *, title: str = "", why: str = "asked",
            project: str = "") -> dict | None:
    """Make a loose conversation a piece of numbered work. Its task, or None.

    What happens is one row and one link: a task takes the next number, and it
    is given this chat to own. Nothing is copied and nothing is moved - the
    messages are the chat's own and the chat is the same chat - so a promotion
    cannot lose a word of what was said.

    Whatever the chat owns stays the chat's, and therefore comes with it. What
    was filed under a project moves too: the project is given the task instead,
    because ownership points down `project > task > chat` and the chat's one
    owner is now the task.

    `project` is the id of a project the person named as they asked - "put
    those in a new task, part of Acme" - and it wins over whatever the chat
    was filed under, because it is the later and the plainer thing they said.
    The task is then made inside that project's folder from the first moment,
    `work/acme/61.team-messaging`, rather than in `unfiled/` and moved there
    afterwards (`filing.find` is how a name becomes the id).

    A chat that a task already owns is already promoted, and its task is
    handed back rather than a second one being made.
    """
    from . import artifacts

    st = store()
    row = st.get_chat(chat_id)
    if row is None:
        return None
    if chat_id == GENERAL:
        # The thread that is always there is where anything with no home yet is
        # said. Numbering it would file every loose remark under one task and
        # leave the person nowhere to say the next thing.
        log.info("the General thread is not promoted (%s)", why)
        return None
    already = task_of(chat_id)
    if already is not None:
        return _task_row(already)
    named = " ".join((title or ("" if is_untitled(row.title) else row.title)
                      or "").split())
    # The picture at the front of a chat's title is for a list to be scanned
    # by; a task is named by its number and its words.
    while named and chat_titles.is_emoji(named[0]):
        named = named[1:].strip()
    named = named or UNTITLED_TASK
    named_by_person = bool(project)
    project = project or _project_over(st, "chat", chat_id)
    task = _new_numbered_task(st, named[:MAX_TITLE], project=project or "")
    if task is None:
        log.error("no task could be made for chat %s", chat_id)
        return None
    if named_by_person:
        # Where it goes was said, so the model that files what nobody placed
        # is never asked about this one (`filing.placed_by_person`).
        from . import filing

        filing.placed_by_person(task.id)
    number = task.number
    st.attach("task", task.id, "chat", chat_id)
    # A fork asked to be a task stops being a fork: its head names the task
    # and not the chat it came off, and closing it can never leave that chat
    # beside the task's page. Petar, 4 October 2026 (fr_3702d01d197d): "where
    # I started this task from has little relevance or importance"
    # (`forks.cut`).
    from . import forks

    forks.cut(chat_id)
    # Saying a conversation is work is the largest edit there is to one, so it
    # goes to the top of the list like any other.
    touched(chat_id)
    root = _root()
    # And what it drew comes with it: every card the chat owned is given to the
    # task and written out as one of its numbered steps. That is the half of
    # "it keeps what it had" that lives in the other module, and it is why a
    # conversation that turns out to be work does not leave its cards behind
    # (`rouh/artifacts.py`).
    if artifacts.enabled():
        try:
            artifacts.promote(chat_id, task.folder, root)
        except Exception:
            log.exception("the cards of %s could not be moved to %s",
                          chat_id, task.folder)
    global _promoted
    _promoted = task.id
    log.info("chat %s promoted to task %s (%s), because the person %s",
             chat_id, number, task.folder, why)
    return _task_row(task)


#: How long before a run began a task may have been made and still count as
#: the run's: the run row is written a breath after the job is handed over.
_MADE_SLACK = 5.0

#: The files Rouh writes and saves into an object's folder itself, which say
#: nothing about who made what is in it (`adopt_made_task`).
_SIDECARS = frozenset({".object.json"})


def adopt_made_task(run_id: str, files) -> objects.Task | None:
    """The chat that asked for a job becomes the chat of the task the job made.

    Petar, 13 October 2026 (fr_b662c3fe9778): he forked General and asked
    "research that in a new acme task". Rouh started a job, the job made
    task 107, and the fork was left loose: task 107's page had no chat, and
    the chat he asked in was nowhere he could find it from the task. A chat
    that asks for a task is that task's chat, whether the chat is made the
    task (`promote`) or a job it started makes it, so this does what promote
    does with a task that already exists: the task owns the chat, and a fork
    is cut from the chat it came off (`forks.cut`). Its cards stay the
    chat's, so a job's report is never filed as one of the task's steps.

    Only a task the job made: a top-level task under a project, made after the
    job began, with a file of the job's landed work inside its folder. Exactly
    one such task, or nothing is done. It becomes the task's own conversation
    even when another chat was started in the task meanwhile. And only a chat
    that is nobody's yet and is the person's to ask in: never General, never a
    heartbeat's, never a chat an email was handled in. The task, or None when
    nothing changed.
    """
    from . import chatkinds, forks, runs
    from .models.rest import MailAlertSeen
    from .models.objects import Link as LinkRow
    from .models.objects import Task as TaskRow

    st = store()
    run = st.get_run(run_id) if run_id else None
    chat_id = runs.chat_of(run_id) if run is not None else ""
    if not chat_id or chat_id == GENERAL or chatkinds.of_heartbeat(chat_id):
        return None
    owner = st.owner_of("chat", chat_id)
    if owner is not None and owner[0] != "project":
        return None
    if MailAlertSeen.objects.filter(chat_id=chat_id).exists():
        return None
    # Every folder a landed file is inside, read as a task's folder. A run
    # in Rouh's own checkout writes `workspace/work/...`, one in the
    # workspace itself `work/...`.
    #
    # Not a sidecar, though. Every new task's `.object.json` is saved to main
    # by Rouh itself the moment the task is made (`saving`), so a list that
    # holds somebody else's landing as well as the run's own - land.sh's did,
    # for a run replayed over newer work, until 30 October 2026 - names the
    # folder of a task this run never touched. On 30 October 2026 a run asked
    # for in a fork of one task's chat was taken that way to have made a newer
    # task, and the fork became the newer task's chat. A task a run made has
    # the run's own files in it: its AGENTS.md, its first step.
    folders: set[str] = set()
    for path in files or []:
        path = str(path or "").strip().strip("/")
        if path.startswith("workspace/"):
            path = path[len("workspace/"):]
        if path.rsplit("/", 1)[-1] in _SIDECARS:
            continue
        parts = path.split("/")[:-1]
        folders.update("/".join(parts[:n]) for n in range(1, len(parts) + 1))
    if not folders:
        return None
    since = float(run.started_at or 0) - _MADE_SLACK

    def made() -> list[objects.Task]:
        ids = TaskRow.objects.filter(folder__in=folders, created_at__gte=since) \
            .values_list("id", flat=True)
        found = [st.get_task(i) for i in ids]
        return [t for t in found if t is not None and t.archived_at is None
                and (st.owner_of("task", t.id) or ("", ""))[0] != "task"]

    tasks = made()
    if not tasks:
        # The landed folder may not be taken in yet.
        reconcile()
        tasks = made()
    if len(tasks) != 1:
        if tasks:
            log.info("run %s made %d tasks; chat %s is left where it is",
                     run_id, len(tasks), chat_id)
        return None
    task = tasks[0]
    # A fork of a chat the task already owns is in the task already, through
    # that chat, and stays its fork. Petar, 28 October 2026 (fr_9e2edc201502):
    # he asked for task 154 in a fork, detached the chat above it into task 154
    # while the job ran, and when the job landed the fork was cut from it and
    # put first, so the task's own conversation, the one General links to,
    # was no longer its main chat. Only what the person moved is moved.
    above = [c for c in forks.came_from(chat_id) if c != chat_id]
    if any(st.owner_of("chat", c) == ("task", task.id) for c in above):
        log.info("chat %s asked for run %s, which made task %s, and is a fork of "
                 "a chat in that task already: it is left a fork", chat_id, run_id,
                 task.number)
        return None
    # And a fork of another task's chat is that task's conversation, never the
    # new one's. 3 November 2026: a run was asked for in a fork of one task's
    # chat; its landing was read as having made a newer task, and the fork
    # became the newer task's main chat, ahead of the chat that really asked
    # for it. Whatever a landing's list of files says, a
    # chat that hangs off a task's chat stays with that task: the person can
    # still move it on purpose (`promote`, `owning.detach_fork_into`).
    elsewhere = next((owner for owner in (st.owner_of("chat", c) for c in above)
                      if owner is not None and owner[0] == "task"), None)
    if elsewhere is not None:
        other = st.get_task(elsewhere[1])
        log.warning("chat %s asked for run %s, which seems to have made task %s, but it "
                    "is a fork of task %s's chat: it stays that task's fork", chat_id,
                    run_id, task.number, other.number if other is not None else elsewhere[1])
        return None
    st.attach("task", task.id, "chat", chat_id)
    # And it is the task's own conversation, the one opening the task brings
    # back (`_chat_of`, the oldest link), even when somebody has started
    # another in the task while the job ran: this one asked for the task.
    # Petar's task 107 had a second chat eight minutes after he asked.
    LinkRow.objects.filter(rel="owns", dst_type="chat", dst_id=chat_id) \
        .update(created_at=task.created_at)
    forks.cut(chat_id)
    touched(chat_id)
    log.info("chat %s asked for run %s, which made task %s (%s): it is that task's chat",
             chat_id, run_id, task.number, task.folder)
    return task


def name_untitled_task(chat_id: str, title: str) -> dict | None:
    """Give the task this chat is its chat's new name, if the task has none yet.

    A chat is named from its first exchange in the breath after that turn
    (`ChatNames`), and a turn can make its chat a task before that. On 28
    September 2026 Petar forked General, asked for the fork to be made a task,
    and the model did it at once: the fork had no name, so the task was
    "Untitled task" at `work/sales/68.untitled-task`, and four seconds later the
    chat was named "Company pricing offer" - but the task never heard, and stayed
    Untitled until a job was asked to rename it. So the chat's name becomes the
    task's, once, and only over the stand-in name: a task somebody named keeps
    its name. The folder keeps its own name, as any rename does (`owning.rename`).
    Answers what `owning.rename` answers, or None when nothing was renamed.
    """
    task = task_of(chat_id)
    if task is None or task.title != UNTITLED_TASK:
        return None
    named = " ".join(str(title or "").split())
    while named and chat_titles.is_emoji(named[0]):
        named = named[1:].strip()
    if not named or is_untitled(named):
        return None
    from . import owning

    done = owning.rename("task", task.id, named[:MAX_TITLE])
    if done.get("ok"):
        log.info("task %s was %s, and is named %r after its chat", task.number,
                 UNTITLED_TASK, named)
    return done


def _task_row(task: objects.Task) -> dict:
    return {"id": task.id, "rel": task.folder, "number": task.number,
            "name": task.title, "slug": task.slug, "state": task.state,
            "status": task.status}


# ---------------------------------------------------------------------------
# The folder on disk, written out from the row
# ---------------------------------------------------------------------------


def write_out(root: str, task: objects.Task) -> str:
    """Write this task's folder into the workspace. What it wrote, or "".

    The folder is a view of the row, for grep, for git and for the workspace's
    own index, and this is the only direction anything is written: the row
    first, the folder after it.

    It writes the folder and its `.object.json`, and nothing else: what the
    task is, its status, its summary and its meta, is the row's
    (`rouh/taskrecord.py`, `rouh/taskmeta.py`).
    """
    from . import objecttree, steps

    if not task.folder or task.number is None:
        return ""
    base = Path(root).resolve()
    folder = base / task.folder
    # A task that is its own git repository is never written into. That is the
    # workspace's own rule: task 08 is a submodule, and a file written into it
    # belongs to neither repository and goes the moment anybody runs
    # `git submodule update`.
    if objecttree.another_repo(folder, base):
        return task.folder
    try:
        if not folder.is_dir():
            folder.mkdir(parents=True, exist_ok=True)
            steps.own_as_workspace(folder, base)
            log.info("wrote out task %s as %s", task.number, task.folder)
        _write_object_json(folder, base, task)
    except OSError:
        log.exception("the folder for task %s could not be written", task.number)
        return ""
    return task.folder


def _write_object_json(folder: Path, base: Path, task: objects.Task) -> None:
    """The sidecar that makes the folder an object, where it has none yet.

    A folder with `.object.json` in it is an object and nothing else is
    (`objecttree.py`), so a task folder written out without one is a folder the
    tree cannot see: `map`, `import` and `verify` all walk for sidecars. The id
    in it is the row's own, which is what stops a later `sidecars` run minting a
    second identity for the same task.

    Only where there is none. The file on disk is the answer once it is written,
    and a task somebody has moved under a project has an owner this does not
    know about.
    """
    # `steps` as well as `objecttree`: the last line of this hands the new file
    # to `steps.own_as_workspace`, and this module has no `steps` at the top of
    # it, so a task folder written out with no sidecar raised NameError right
    # at the end of writing one.
    from . import objecttree, steps

    path = folder / objecttree.SIDECAR
    if path.is_file():
        return
    st = store()
    owner = st.owner_of("task", task.id)
    body = {"id": task.id, "type": "task", "title": task.title,
            "owner": owner[1] if owner else None}
    path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    steps.own_as_workspace(path, base)


def _sidecar(base: Path, path: Path) -> dict:
    """What a task folder's `.object.json` says it is, or {} when it says nothing."""
    from . import objecttree

    try:
        return objecttree.read_sidecar(path, base) or {}
    except (objecttree.Refused, OSError):
        return {}


def _take_in(st, path: Path, rel: str, number: int, slug: str, said: dict):
    """A numbered task folder no row knows about, made a row, as it says it is.

    Its `.object.json` names its id, its title and the project it belongs to,
    and until 24 September 2026 none of that was read: the row was named from
    the folder alone and owned by nothing. A task owned by nothing is filed
    into Misc by `objecttree.tidy`, with `git mv`, in this machine's checkout,
    and the next deploy put the committed files straight back where they were
    - which left task 02 under Misc as an empty folder and a row pointing at
    it, while what it was stayed a step of task 01. So a folder that says
    whose it is, is that project's from the first moment.

    The id it names is kept when no row has it already, and the one its
    number gives (`artifacts.task_id`) otherwise. None when neither is free,
    which is said in the log rather than raised: one folder that cannot be
    taken in is never a reason the rest are not.
    """
    from . import artifacts, steps, taskrecord

    ident = str(said.get("id") or "") if said.get("type") == "task" else ""
    if not ident or st.get_task(ident) is not None:
        ident = artifacts.task_id(rel)
    if st.get_task(ident) is not None:
        log.warning("the task folder %s could not be taken in: the row %s is "
                    "already another task's", rel, ident)
        return None
    # Whoever made it, the landing of the run that made it says (`rouh/task_origin.py`):
    # never whatever is running as it is found.
    made = st.create_task(str(said.get("title") or "").strip() or steps._words(path.name),
                          id=ident, number=number, slug=slug, state="not-started", folder=rel,
                          origin={})
    # What the job that made it said about it while it had no row (`rouh-task`).
    if taskrecord.apply_pending(st, made.id):
        made = st.get_task(made.id) or made
    owner = str(said.get("owner") or "")
    if owner and st.get_project(owner) is not None:
        try:
            st.attach("project", owner, "task", made.id)
        except Exception:
            log.exception("task %s says it is %s's, and could not be filed there",
                          number, owner)
    return made


#: The numbers already said to be in two folders, so the log says it once per
#: process rather than on every pass, which is several times a second.
_TWINS_SAID: set[tuple[int, tuple[str, ...]]] = set()


def _work_in(path: Path) -> tuple[int, int]:
    """How much work a task folder holds: its step folders, then its pages."""
    from . import steps

    try:
        held = [p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")
                and steps._STEP_NAME.match(p.name)]
    except OSError:
        return (0, 0)
    built = sum(1 for p in [path, *held] for _ in p.glob("*.html"))
    return (len(held), built)


def _the_folder(base: Path, number: int, paths: list[Path], row) -> Path:
    """Of the folders carrying one task's number, the one its row names.

    Nearly always there is one. Two is one task made twice: task 56 on 23
    September 2026 was a folder Rouh wrote under Misc when the task was made,
    empty and never committed, and a folder the job that did the work wrote
    and committed under Personal, with the step and its page in it, both
    `task-56`. Walked one at a time, each renamed the row to itself, so the
    row changed folder on every pass - 445 times on the live server that day -
    and the task's own page showed its page or did not depending on which
    folder the last pass had left it on.

    So one is chosen, and the same one every time: the one holding the most
    work (its steps, then its pages); between two that hold the same, the one
    the row names already; then the first by path. The others are left
    exactly as they are, and the log says so once: which of two tasks with
    one number is which is a person's to decide, not this.
    """
    if len(paths) == 1:
        return paths[0]
    names = [str(p.relative_to(base)).replace(os.sep, "/") for p in paths]
    now = getattr(row, "folder", "") or ""
    chosen = max(zip(paths, names), key=lambda pair: (_work_in(pair[0]), pair[1] == now))
    said = (number, tuple(names))
    if said not in _TWINS_SAID:
        _TWINS_SAID.add(said)
        log.warning("task %s is in %d folders (%s); its row names %s, which holds the "
                    "most work, and the others are left as they are", number,
                    len(paths), ", ".join(names), chosen[1])
    return chosen[0]


def let_general_go() -> bool:
    """Take General out of whatever project holds it. True when it was in one.

    General is loose and stays loose (`GENERAL`), and `set_project` refuses to
    file it, but one row got there before that rule was written down: the old
    chat folder 🪸Rouh held the thread that became General, and moving the
    chats onto the object model (`memory.py`, `take_in_chat`) carried the
    folder across with it. So General was drawn under Rouh in the chat list
    and its header read "Rouh" - Petar, 29 September 2026: "general chat seems
    to be located in Rouh". Asked on every reconcile, and one query when there
    is nothing to do.
    """
    try:
        st = store()
        owner = st.owner_of("chat", GENERAL)
        if owner is None or owner[0] != "project":
            return False
        st.detach("chat", GENERAL)
    except (RuntimeError, DatabaseError):
        log.exception("General could not be taken out of its project")
        return False
    log.info("General was filed under the project %s; it is loose again", owner[1])
    return True


def reconcile(root: str = "") -> dict:
    """Reconcile the rows with the workspace on disk. What changed, as counts.

    Three things, and the direction of each is the decision the person made:

    - **a folder no row knows about** is a task somebody made by hand, and it
      is taken in as a row. An addition is an inbound change: nothing in the
      database said it should not exist.
    - **a folder that was renamed** hands its new place to the row, which is
      the truth again afterwards.
    - **a task's status and summary are never read off the disk.** Since 6
      October 2026 they are kept in the row and nowhere else, changed through
      `rouh/taskrecord.py` (`rouh-task`), and nothing on disk is asked.
    - **a row whose folder is missing** has the folder written out again,
      because that is a disagreement and the database wins it.

    Quiet unless something actually changed, and it says in the log what it
    took in - a task appearing out of nowhere should be explainable.
    """
    from . import objecttree

    root = root or _root()
    out = {"took_in": 0, "renamed": 0, "written_out": 0, "steps": 0}
    let_general_go()
    if not root:
        return out
    base = Path(root).resolve()
    st = store()
    # The tree first, because it is the only thing that knows the projects and
    # which project owns which task. Taking the folders in without it would
    # give every task a row and no owner: "Nowhere" under a task the browser
    # shows under Personal and Assistant, and nothing to move it back with.
    # It costs one query once the rows are there (`objecttree.ensure_imported`).
    try:
        objecttree.ensure_imported(base, st)
    except Exception:
        log.exception("the workspace tree at %s could not be taken in", base)
    # And a column that is a row and nothing else is given its folder here as
    # well as when the browser is drawn, so the chat list says the same thing
    # about Rouh the task browser does from the first start after a deploy.
    objecttree.columns_are_folders(base, st)
    rows = {t.number: t for t in st.list_tasks(limit=None) if t.number is not None}
    seen: set[int] = set()
    from . import steps
    # Every numbered task folder wherever it sits, rather than the contents of
    # one top folder. A task is under the project that owns it since the tree
    # was reshaped on 21 September 2026, so a walk of `tasks/` found nothing at
    # all and this went on to write every row's folder out again.
    folders = sorted(steps.task_folders(base))
    # One folder for each number, the same one on every pass (`_the_folder`).
    # Walked one folder at a time, a number in two folders renamed its row to
    # each of them in turn, so the row ended on the other one every pass.
    by_number: dict[int, list[Path]] = {}
    for path in folders:
        found = _FOLDER.match(path.name)
        if found:
            by_number.setdefault(int(found.group(1)), []).append(path)
    for number, paths in sorted(by_number.items()):
        path = _the_folder(base, number, paths, rows.get(number))
        found = _FOLDER.match(path.name)
        rel = str(path.relative_to(base)).replace(os.sep, "/")
        slug = found.group(2)
        row = rows.get(number)
        said = _sidecar(base, path)
        if row is None:
            made = _take_in(st, path, rel, number, slug, said)
            seen.add(number)
            if made is None:
                continue
            rows[number] = made
            out["took_in"] += 1
            log.info("took in task %s from the workspace: %s", number, rel)
            continue
        seen.add(number)
        if row.folder != rel:
            st.update_task(row.id, folder=rel, slug=slug,
                           title=str(said.get("title") or "").strip()
                           or steps._words(path.name))
            out["renamed"] += 1
            log.info("task %s was renamed on disk to %s, and the row follows it",
                     number, rel)
            # Its steps are inside it, so they moved with it: a step row left
            # naming the old folder was a step that opened nothing, and one the
            # take-in below would have made a second row for.
            # So are the pages built in them, named by file: left at the old
            # path, the task's own page listed its step's page a second time,
            # as a loose page with that path written over its name.
            # `objecttree.move` has always carried both; a rename on disk is
            # the same move made by somebody else.
            if row.folder:
                for inner in st.list_tasks(limit=100000):
                    if (inner.folder or "").startswith(row.folder + "/"):
                        st.update_task(inner.id,
                                       folder=rel + inner.folder[len(row.folder):])
                for art in st.artifacts_under(row.folder):
                    here = str(art.path or "")
                    st.update_artifact(art.id, path=rel + here[len(row.folder):])
    for number, row in rows.items():
        if number in seen or not row.folder:
            continue
        if write_out(root, row):
            out["written_out"] += 1
    out["steps"] = _take_in_steps(st, base, [rows[n] for n in seen if n in rows])
    if out["took_in"] or out["steps"]:
        # One made for somebody outside is marked so now, which keeps it out of the
        # person's own views (`rouh/task_origin.py`), and shared with them
        # (`rouh/requester_share.py`).
        from . import requester_share, task_origin

        task_origin.sweep_quietly()
        requester_share.wake()
    if any(out.values()):
        # What a task's line in `_tasks.md` says may have changed with it.
        from . import tasklist

        tasklist.changed()
    return out


#: One take-in at a time. On 6 October 2026 a deploy that brought eleven new
#: steps of task 89 ran two reconciles in the same instant; each listed the rows
#: before the other had written any, and the second made a second row, under a
#: new id, for the two steps the first had just taken in.
_TAKING_IN = threading.Lock()


def _take_in_steps(st, base: Path, tasks) -> int:
    """The step folders under these tasks that no row knows about, made rows.

    One at a time (`_TAKING_IN`), so the rows are listed only once any other
    take-in has written its own.

    A step a background job builds is a folder, `61-04.every-document-in-the-
    site`, with its `.object.json` saying whose it is, and nothing else: a
    job's checkout has no database. Until 29 September 2026 the only road from
    such a folder to a row was a line in `_migration-map.json`, which a job is
    told not to touch, so 25 steps on the live server were pages on disk and
    nowhere in the task browser, the rail's Tasks list or search - task 61 had
    four subtasks and its row said it had none.

    Each is taken in as a step of the task whose folder it is in, which is the
    one thing the disk cannot be wrong about. The id its `.object.json` names
    is kept when no row has it. Quiet unless it made something.
    """
    with _TAKING_IN:
        return _take_in_steps_now(st, base, tasks)


def _take_in_steps_now(st, base: Path, tasks) -> int:
    from . import steps

    by_folder = {t.folder: t for t in st.list_tasks(limit=100000) if t.folder}
    # What is on disk and in no row, found with one query and a directory
    # listing a step: this runs every time the rows are reconciled, and
    # almost always finds nothing.
    #
    # All the way down. Until 10 October 2026 only the folders directly in
    # a numbered task were looked at, so a step of a step - 89-10-02 inside
    # 89-10 - was a page on disk with no row, and in no list at all: Petar
    # could not find it. A step inside a step is named after it, its own
    # number one place further on (`89-10-02.x` in `89-10.x`), and is that
    # step's, as a step is its task's.
    level = [(task, None) for task in tasks if task.folder and task.number is not None]
    made = 0
    mine: dict[str, dict] = {}
    depth = 0
    while level and depth < _STEP_DEPTH:
        depth += 1
        missing, deeper = [], []
        for holder, head in level:
            try:
                kids = sorted(p for p in (base / holder.folder).iterdir() if p.is_dir())
            except OSError:
                continue
            for path in kids:
                if head is None:
                    found = steps._STEP_FOLDER.match(path.name)
                    if not found or int(found.group(1)) != holder.number:
                        continue
                elif not re.match(re.escape(head) + r"-\d+[.-]", path.name):
                    continue
                row = by_folder.get(f"{holder.folder}/{path.name}")
                if row is None:
                    missing.append((holder, path))
                else:
                    deeper.append(row)
        for task, path in missing:
            row, changed = _take_in_step(st, base, task, path, by_folder, mine)
            made += changed
            if row is not None:
                deeper.append(row)
        level = [(row, _step_head(row)) for row in deeper if _step_head(row)]
    return made


#: How many steps deep the take-in looks, past the task itself.
_STEP_DEPTH = 8


def _step_head(row) -> str:
    """A step's own number, `89-10` out of `89-10.framework`, or "" for a
    folder not named that way, whose steps have nothing to be named after."""
    name = str(row.folder or "").rsplit("/", 1)[-1]
    head = name.split(".", 1)[0]
    return head if re.fullmatch(r"\d+(?:-\d+)+", head) else ""


def _take_in_step(st, base: Path, task, path: Path, by_folder: dict, mine: dict):
    """One step folder no row knows about, inside `task` (a task or a step),
    made a row or found to be one that moved: `(row, changed)`, row None when
    it could not be taken in, and changed False when nothing was written."""
    from . import steps, taskrecord

    rel = f"{task.folder}/{path.name}"
    # Its steps as rows, by the name of their folder: a step whose task
    # moved before steps moved with it (`reconcile`) still names the old
    # folder, as task 29's four did on the live server, and is that step.
    if task.id not in mine:
        mine[task.id] = {}
        for _kind, kid in st.children_of("task", task.id, "task"):
            got = st.get_task(kid)
            if got is not None and got.folder:
                mine[task.id][got.folder.rsplit("/", 1)[-1]] = got
    stale = mine[task.id].get(path.name)
    if stale is not None and not (base / stale.folder).is_dir():
        st.update_task(stale.id, folder=rel)
        log.info("step %s was at %s, and the row follows it", rel, stale.folder)
        row = st.get_task(stale.id)
        if row is not None:
            by_folder[rel] = row
        return row, True
    said = _sidecar(base, path)
    ident = str(said.get("id") or "") if said.get("type") == "task" else ""
    # A step moved here from another task: its `.object.json` names a
    # row whose folder is gone. That row is this step, so it follows the
    # folder, with its page and its owner, rather than a second row being
    # made beside it and the first left under the old task opening
    # nothing - which is what moving task 62's four logo rounds into
    # task 69 on disk would otherwise have done on 29 September 2026.
    was = st.get_task(ident) if ident else None
    if (was is not None and was.number is None and was.folder
            and was.folder != rel and not (base / was.folder).is_dir()):
        _carry_step(st, was, rel, path.name, task)
        row = st.get_task(was.id)
        if row is not None:
            by_folder[rel] = row
        return row, True
    if was is not None and was.folder == rel:
        # Already this step: taken in a moment ago by another pass.
        by_folder[rel] = was
        return was, False
    if ident and was is not None:
        ident = ""
    try:
        # Made when its task was, never now: the rail orders by when a
        # thing itself was last worked on (`owning.snapshot`), which
        # for a step is when its page was written, and a row born
        # this second would put every step taken in at the top.
        # And made by whoever made its task, until the landing of the run that
        # made it says otherwise (`rouh/task_origin.py`).
        from . import task_origin

        row = st.create_task(str(said.get("title") or "").strip()
                             or steps._words(path.name), id=ident or None,
                             slug=path.name, state="not-started", folder=rel,
                             created_at=task.created_at, origin=task_origin.under(task.id))
        st.attach("task", task.id, "task", row.id)
        taskrecord.apply_pending(st, row.id)
        # And seen when its task was last opened, so its red dot says
        # what it always says: written since the person last looked.
        if task.seen_at:
            st.update_task(row.id, seen_at=task.seen_at)
    except Exception:
        log.exception("the step folder %s could not be taken in", rel)
        return None, False
    by_folder[rel] = row
    log.info("took in step %s from the workspace, under %s", rel,
             f"task {task.number}" if task.number is not None
             else f"step {_step_head(task) or task.folder}")
    return row, True


def _carry_step(st, row, rel: str, name: str, task) -> None:
    """A step row whose folder moved on disk into another task, moved with it.

    What `objecttree.move` does for a move made through Rouh, done afterwards
    for one made in the files: the row and anything nested in it name the new
    folder, the pages built in it name their new paths, and the new task owns
    the step and every page of it the old task owned.
    """
    was = row.folder
    before = st.owner_of("task", row.id)
    st.update_task(row.id, folder=rel, slug=name)
    for inner in st.list_tasks(limit=100000):
        if (inner.folder or "").startswith(was + "/"):
            st.update_task(inner.id, folder=rel + inner.folder[len(was):])
    st.attach("task", task.id, "task", row.id)
    for art in st.artifacts_under(was):
        here = str(art.path or "")
        st.update_artifact(art.id, path=rel + here[len(was):])
        if before is not None and st.owner_of("artifact", art.id) == before:
            st.attach("task", task.id, "artifact", art.id)
    log.info("step %s moved on disk to %s, under task %s, and its row follows it",
             was, rel, task.number)


# ---------------------------------------------------------------------------
# The projects a conversation is filed under
# ---------------------------------------------------------------------------


def projects() -> list[dict]:
    """Every project, by name, and where it is in the workspace where it is there.

    Two kinds of row come back, and `folder` is the whole of what tells them
    apart. One of the person's own projects, made in the rail to hold chats, is
    a row and nothing else: its folder is "". A project of the workspace - Work,
    Personal, Acme, Research - is a folder in the tree, and its folder says
    where. They were indistinguishable here until stage four, which is how ten
    workspace projects came to be listed in the rail beside the person's own
    with nothing to say which was which and a rename button on every one of
    them.

    Each row also carries `owner` - the project it is inside, or "" for one at
    the top, which is what the projects dashboard draws the nesting from - and
    `has`, what is under it all the way down as counts by kind. `has` is what
    a row says under a project's name at rest; what a delete would take is
    asked for on its own when the cross is pressed, so the sentence somebody
    agrees to is the walk that is about to happen (`owning.plan`).
    """
    st = store()
    rows = st.list_projects(limit=500)
    rows.sort(key=lambda p: (p.title.lower(), p.id))
    under: dict[tuple[str, str], list[tuple[str, str]]] = {}
    inside: dict[str, str] = {}
    # One read of the link table for the whole answer rather than a query per
    # project: the projects dashboard draws the tree and what is in every one
    # of them at once, and a walk per row is how a list gets slow without
    # anybody noticing which change did it.
    for link in st.refs(objects.OWNS):
        under.setdefault((link.src_type, link.src_id), []).append(
            (link.dst_type, link.dst_id))
        if link.dst_type == "project" and link.src_type == "project":
            inside[link.dst_id] = link.src_id

    def has(kind: str, obj_id: str, depth: int = 0) -> dict[str, int]:
        """What is inside this, all the way down, by kind.

        Everything, with nothing left out. It is what the row says under a
        project's name at rest. What a delete would take is a walk of its own,
        made when the cross is pressed and with General left out of it, and it
        is `owning.plan` that answers it.
        """
        out: dict[str, int] = {}
        if depth > DEEP:
            return out
        for child_kind, child_id in under.get((kind, obj_id), ()):
            out[child_kind] = out.get(child_kind, 0) + 1
            for k, n in has(child_kind, child_id, depth + 1).items():
                out[k] = out.get(k, 0) + n
        return out

    return [{"id": p.id, "name": p.title, "folder": p.folder,
             "owner": inside.get(p.id, ""), "has": has("project", p.id),
             # The person's own mark. A pinned project is drawn under All
             # projects on all three of the sidebar's lists, whichever kind
             # of project it is.
             "pinned": bool(p.pinned),
             "created_at": p.created_at} for p in rows]


def project(project_id: str) -> dict | None:
    row = store().get_project(project_id)
    return ({"id": row.id, "name": row.title, "folder": row.folder,
             "created_at": row.created_at} if row else None)


def new_project(name: str, *, project_id: str | None = None,
                owner_id: str | None = None) -> dict:
    """A project of the person's own, and the project it is inside, if any.

    A project may own a project, which is half of the nesting the hierarchy is
    made of, so a new one can be made inside another from the start rather than
    made loose and moved afterwards. The owner has to be a project that is
    there: a task may never own a project, and `objects.attach` refuses that
    pair whatever is asked of it here.

    One made at the top is a column, beside Work and Personal, and a column is
    a folder of the workspace, so it is given its folder at once
    (`objecttree.columns_are_folders`). That is the rule Rouh broke until 29
    September 2026, when a sidebar project at the top was a column in the task
    browser that nothing could be filed into.
    """
    from . import objecttree

    name = " ".join((name or "").split())[:MAX_PROJECT_NAME] or "New project"
    st = store()
    row = st.create_project(
        name, id=project_id or "folder-" + uuid.uuid4().hex[:12])
    holder = st.get_project(owner_id) if owner_id else None
    if holder is not None:
        st.attach("project", owner_id, "project", row.id)
    else:
        root = _root()
        if root and objecttree.columns_are_folders(root, st):
            row = st.get_project(row.id) or row
    return {"id": row.id, "name": row.title, "created_at": row.created_at}


def rename_project(project_id: str, name: str) -> dict | None:
    """Give a project another name, down the one rename in the program.

    `owning.rename` is that one. For a project of the person's own it is the
    row and nothing else; for one that is a folder of the workspace it also
    writes the new title into the folder's `.object.json`, so the row and the
    folder never disagree about what the thing is called. The folder keeps its
    own name either way: that name is the address of every page under it, and
    moving it is `objecttree.move`, which is what the task browser's filing
    calls.

    This wrote the row alone until 22 September 2026, so renaming Work from
    the rail left its sidecar saying the old title and the next read of the
    tree took it back.
    """
    from . import owning

    name = " ".join((name or "").split())[:MAX_PROJECT_NAME]
    if not name or store().get_project(project_id) is None:
        return None
    if not owning.rename("project", project_id, name).get("ok"):
        return None
    return project(project_id)


# ---------------------------------------------------------------------------
# Taking in what was there before
# ---------------------------------------------------------------------------
#
# `memory.py` owns the tables the conversations used to live in and hands their
# rows over here one at a time, so this module never has to know what a
# `sessions` row looked like and that module never has to know what a link is.


def take_in_project(project_id: str, name: str, created_at: float) -> None:
    """One of the old chat folders, as a project."""
    st = store()
    if st.get_project(project_id) is None:
        st.create_project(" ".join((name or "").split())[:MAX_PROJECT_NAME]
                          or "Project", id=project_id, created_at=created_at)


def take_in_chat(chat_id: str, *, title: str | None, created_at: float,
                 last_spoke: float, unread: bool, pinned: bool,
                 task: str = "", project_id: str = "",
                 said: list[tuple[str, str]] = ()) -> dict:
    """One thread as it was, as a chat row, with its turns and its links.

    Everything the person could open before must open afterwards, so the chat
    keeps the id it already had: the id in a tab's markup, the folder anything
    attached in it was stored under, the id every turn of it was written
    against. Nothing is renumbered and nothing is copied.

    `task` is the folder string the thread used to be matched to a task by. It
    is used exactly once, here, to find the task row that folder belongs to and
    write the `owns` link that replaces it, and then it is gone for good.

    A thread whose folder is not there any more - somebody renamed it, or the
    workspace on this machine is not the one it was written against - is
    marked as one to keep: it was numbered work once, so it is pinned and said
    so in the log.
    """
    st = store()
    row = st.get_chat(chat_id)
    if row is None:
        # `last_activity` is left to follow `last_spoke`, which is what a
        # thread moved from the old model has instead of a record of when it
        # was last used: it lands in the list where its own history puts it.
        row = st.create_chat(id=chat_id, title=title, created_at=created_at,
                             last_spoke=last_spoke, unread=unread, pinned=pinned)
    elif not st.messages(chat_id):
        # The row is already here because something else needed one to point at
        # - `artifacts.ensure_chat` makes one the moment a card is drawn in a
        # conversation - and it carries an id and a title and nothing else. The
        # move is what fills it in, so the chat has the times it really had and
        # the one that is always there carries its mark.
        st.update_chat(chat_id, title=title or row.title, created_at=created_at,
                       last_spoke=last_spoke, last_activity=last_spoke,
                       unread=unread, pinned=pinned or row.pinned)
        row = st.get_chat(chat_id) or row
    if not st.messages(chat_id):
        for seq, (role, text) in enumerate(said, start=1):
            words = " ".join((text or "").split())
            if words:
                st.add_message(chat_id, role, words, seq=seq)
    owner = st.owner_of("chat", chat_id)
    found = task_by_folder(task) if task else None
    if found is not None and (owner is None or owner[0] == "project"):
        # The thread **is** that task, which is a stronger fact than the folder
        # it was filed in, and an object has one owner: being a task's is what
        # takes a chat out of a project. The project keeps it one level up, by
        # holding the task instead.
        #
        # A chat already put under a project is the live database exactly: by
        # the time this ran there, every chat had been given its folder's
        # project by the step that landed before this one, and the nine threads
        # that were numbered work would have stayed filed as loose chats.
        st.attach("task", found.id, "chat", chat_id)
        if project_id and st.get_project(project_id) is not None \
                and st.owner_of("task", found.id) is None:
            st.attach("project", project_id, "task", found.id)
    elif owner is None:
        if task:
            st.update_chat(chat_id, pinned=True)
            log.warning("the thread %s was %s, which is not in the workspace any"
                        " more; it is kept and marked so",
                        chat_id, task)
        if project_id and st.get_project(project_id) is not None:
            st.attach("project", project_id, "chat", chat_id)
    return chat(chat_id) or _as_row(row)
