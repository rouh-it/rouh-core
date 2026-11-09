"""Forks: a side conversation that hangs off a point in another one.

Petar, 24 September 2026 (fr_6fd33e631405): "anytime I'm in a conversation
and don't understand something, I would like to ask for clarification. That
might trigger an entirely new conversation, but at the same time, I don't want
to lose where we are in the main thread." And: "I don't think I want those
subchats in the list anywhere. They're just attachments to the main chat."

So a fork is three things at once, and this module is the whole of each.

**It is a chat.** Its own row, its own messages, its own turns and its own
title, written from its own first exchange like any other chat's. Nothing
about answering in one is different, which is why nothing in the turn loop
knows forks exist.

**It knows where it came off.** One row of `chat_fork` says which chat it was
forked from and that chat's last message at that moment (`at`). The model is
shown the parent's conversation up to there before the fork's own words
(`memory.Memory.history`), so a question asked in a fork is asked of somebody
who has read everything above it - and nothing said in the fork is carried
back, which is what keeps the main thread from being "diluted". A fork of a
fork carries its parent's, which carries its own parent's, all the way up.

**It is laid out beside its parent, and in no list.** The chats a person is
looking at are a strip: the chat they started in on the left, the fork they
opened from it to its right, the fork of that fork to the right of that, and
the canvas after all of them. The strip is always one line of descent, so
everything to the left of a chat is where it came from, and moving back and
forth along it never loses the thread. Forking again from a chat that already
has a fork open lays the new one in its place; the one it replaced is not
lost: every fork is marked in its parent's conversation at the point it came
off, and pressing the mark opens it again. Closing a fork takes it and every
fork below it off the strip, and nothing else.

**Which forks are laid out is the tab's, and nothing here keeps it.** A strip
is named by its two ends: the chat in the middle of the screen and the deepest
fork open to its right, the `tip` (`strip`). The tab holds both, its address
says both, and the page sends both when it connects (`switch_chat` and
`hello` in rouh/runtime.py). Until 22 October 2026 it was a flag on each row
of `chat_fork`, `open`, which every tab set on its way into a chat and every
tab was then told: a fork closed on the desk came back by itself the moment
the phone woke at its address, and a reload read the same flags back (task 62,
step 62-23). The column is still in the table, unread and unwritten: dropping
it would make a deploy impossible to roll back.

What it is not: in the sidebar's lists, pinned, filed under a project or
numbered as a task. `conversations.all_chats` leaves every chat named here
out, and deleting a chat takes its forks with it (`under`).

**Until it is made a task, and then it is cut.** Petar, 4 October 2026
(fr_3702d01d197d): he starts most tasks by forking General, or another task's
chat, and asking for one, and the fork becomes the task's chat
(`conversations.promote`). Left a fork, its head named the chat it came off
instead of the task, and closing it left that chat - General, or task 20's -
beside task 24's page. "Where I started this task from has little relevance or
importance", so a fork made a task is cut (`cut`): it is laid out on its own
like every task's chat, the task is its parent, and nothing here but `carried`,
`came_from` and the parent's mark knows it was ever a fork. What it carried is
still read to the model above its first words (`Memory._window`), because the
words that asked for the task can lean on what was said above them, and the
parent keeps its mark, which opens the task now (`children`).

**Or until the person detaches it.** Petar, 5 October 2026: a fork that grew
into work of its own can be detached, from the unlinked-chain button on its
card ("Detach from parent chat"). That is the same cut (`detach`): it is a
chat of its own in every list and search from then on, with every message it
had, and the parent's mark opens it as one. Since 6 October 2026 it is always
detached into a task the person picks, in the same step, so it is never left
loose (`owning.detach_fork_into`, fr_efa418fa7e82).

**In search it is found under the chat it hangs off.** A search that matches
words said in a fork draws the chat it all started in, with the fork as a
line under it that opens the fork, at the message that matched
(`searching._fold_forks`); a task's page lists a chat's forks under it the
same way (`objectindex._chat_rows`).
"""
from __future__ import annotations

import logging
import time

from django.db import transaction

from . import chatkinds, conversations
from .models.memory import TranscriptMessage
from .models.objects import Chat, ChatFork

log = logging.getLogger("rouh.forks")

#: How far up or down a strip is walked before the walk stops. Far past any
#: strip a person lays out by hand; a guard against a ring written at a psql
#: prompt, not a limit on how deep anybody digs.
DEEP = 32


def _laid():
    """Every fork that is still one: laid out beside its parent, in no list.
    A fork cut from its parent by becoming a task's chat is not (`cut`)."""
    return ChatFork.objects.filter(cut_at__isnull=True)


def ids() -> set[str]:
    """Every chat that is a fork, which is every chat the lists leave out."""
    return set(_laid().values_list("chat_id", flat=True))


def parent_of(chat_id: str) -> str:
    """The chat this one was forked from, or "" when it is not a fork."""
    if not chat_id:
        return ""
    return _laid().filter(chat_id=chat_id).values_list(
        "parent_id", flat=True).first() or ""


def carried(chat_id: str) -> tuple[str, int] | None:
    """(parent, the parent's last message it carries), or None for a chat.
    A fork that was cut still carries it (`cut`)."""
    row = ChatFork.objects.filter(chat_id=chat_id).values("parent_id", "at").first()
    if row is None or row["at"] is None:
        return None
    return row["parent_id"], int(row["at"])


def lineage(chat_id: str) -> list[str]:
    """This chat and every chat above it, the one it all started in first."""
    return _line(chat_id, parent_of)


def came_from(chat_id: str) -> list[str]:
    """`lineage` through cuts as well: every chat this one carries, which is
    where the files of a fork's first question are kept (`mailfiles.chats_of`)."""
    def up(chat: str) -> str:
        return ChatFork.objects.filter(chat_id=chat).values_list(
            "parent_id", flat=True).first() or ""

    return _line(chat_id, up)


def _line(chat_id: str, up) -> list[str]:
    line = [chat_id] if chat_id else []
    seen = set(line)
    while line and len(line) < DEEP:
        above = up(line[0])
        if not above or above in seen:
            break
        line.insert(0, above)
        seen.add(above)
    return line


def cut(chat_id: str) -> bool:
    """Make a fork a chat of its own, because it has become a task's chat.

    Its head names the task rather than the chat it came off, it is laid out
    alone, and closing it can never leave that chat beside the task's page
    (see the module's docstring). Nothing is deleted: the model still reads
    what it carried, and the parent's mark opens the task. Whether there was
    a fork to cut.
    """
    if not chat_id:
        return False
    done = _laid().filter(chat_id=chat_id).update(cut_at=time.time())
    if done:
        log.info("fork %s is a task's chat now, and is cut from the chat it came off",
                 chat_id)
    return bool(done)


def detach(chat_id: str) -> str:
    """Make a fork a chat of its own because the person asked to. The chat it
    came off, or "" when it was not a fork laid out beside one.

    Petar, 5 October 2026: a fork can turn into a piece of work in its own
    right, and then it should stop hanging off the chat it came off and be
    found like any other chat. It is the same cut a fork made a task gets
    (`cut`) and nothing more: the chat keeps its id, every message and every
    try of every message, its cards and its own forks, and nothing is copied
    or deleted. The model still reads what it carried above its first words
    (`carried`), so what was asked in it still makes sense, and the parent
    keeps its mark, which now opens it as a chat of its own (`children`).
    It is in the chat lists and searched as itself from now on, because
    every list leaves out only the forks still laid out (`ids`).
    """
    parent = parent_of(chat_id)
    if not parent:
        return ""
    # Off the parent's strip with it go its own forks, which were beside it
    # there: being cut, it is the top of their strip now.
    _laid().filter(chat_id=chat_id).update(cut_at=time.time())
    log.info("fork %s of %s is detached and is a chat of its own", chat_id, parent)
    return parent


def root_of(chat_id: str) -> str:
    line = lineage(chat_id)
    return line[0] if line else ""


def _last_message(chat_id: str, before: int | None = None,
                  through: int | None = None) -> int | None:
    """The chat's last message in the order it reads, or the last one above
    the exchange `before`, or the last one of the exchange `through`, when
    either is given.

    The order it reads and not the order the rows were written: a question
    edited after later ones were asked writes its new try with the newest
    ids in the chat, in its old place (`Memory.another_try`). Its answer was
    taken for the chat's last message, and a fork of the whole chat was
    handed only the conversation up to that edited question.
    """
    from .memory import _exchange

    rows = (TranscriptMessage.objects.filter(session_id=chat_id, live=True)
            .annotate(ex=_exchange()))
    if before is not None:
        rows = rows.filter(ex__lt=before)
    if through is not None:
        rows = rows.filter(ex__lte=through)
    return rows.order_by("-ex", "-id").values_list("id", flat=True).first()


def comes_off(parent_id: str, *, through: int | None = None) -> int | None:
    """The parent's message a fork made now would come off after, or None
    when there is nothing for it to carry (`make`)."""
    return _last_message(parent_id, through=through)


def bare(chat_id: str) -> bool:
    """Whether this chat may be forked with nothing said in it yet.

    A fork of nothing is a new chat, except in two places.

    Synapse: a fork of the Synapse chat stays on the dataset that was open
    when it was made (`rouh/synapse/chat.py`), which a new chat would not, so
    it carries something even when it carries no words. Petar, 4 October 2026
    (fr_c933c22b9bef): "I am missing the fork button on this chat for the
    synapse" - the Synapse chat, open and empty beside a dataset, had no Fork.

    And a task's chat, or the draft of one that nothing has been said in yet.
    Petar asked twice: on 29 October 2026 (fr_8ac43a9d12f1), "I am missing the
    fork button here", which was answered then by saying why not, and on
    7 November 2026 (fr_e42a59f37d17): "I imagine I can fork even the first
    message, because it will keep the main thread clean from the very
    beginning". The reason it was not was that a fork is owned by nothing, so
    the task came along only in the words it carried. It now comes along
    without them: a fork knows the task its line of chats hangs off
    (`task_above`), and the model in it is told so (`task_block`). So the
    first message goes into a fork, and the task's own chat is left with
    nothing in it, made from its draft if it was one (`make`).
    """
    if not chat_id:
        return False
    from .synapse import chat as synapse_chat

    if synapse_chat.place_of_chat(chat_id) is not None:
        return True
    try:
        return conversations.task_of(chat_id) is not None
    except Exception:  # noqa: BLE001 - no Fork on an empty chat is the old answer, never a broken page
        log.debug("which task chat %s is could not be read", chat_id, exc_info=True)
        return False


def task_above(chat_id: str):
    """The task a fork's line of chats belongs to, or None.

    A fork is owned by nothing (a task owns its chat, and the fork hangs off
    that chat), so the task is the first chat above it that a task owns. None
    for a chat that is not a fork, which is asked its own task instead.
    """
    line = lineage(chat_id)
    if len(line) < 2:
        return None
    for above in reversed(line[:-1]):
        task = conversations.task_of(above)
        if task is not None:
            return task
    return None


def task_block(chat_id: str) -> str:
    """What the model in a fork of a task's chat is told about the task, or "".

    The words a fork carries say what the task is about most of the time; a
    fork of a task's chat with nothing said in it yet carries none, and is
    told here which task it is part of instead.
    """
    if not chat_id:
        return ""
    try:
        task = task_above(chat_id)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the task above fork %s could not be read", chat_id)
        return ""
    if task is None:
        return ""
    name = f"task {task.number}, {task.title}" if task.number is not None else task.title
    where = f" (folder {task.folder})" if task.folder else ""
    return (f"This conversation is a side chat, a fork, of the conversation of {name}{where}. "
            "It is part of that task's work: what the person asks here is about that task "
            "unless they say otherwise, and the task already exists.")


def make(parent_id: str, before: int | None = None, *,
         through: int | None = None) -> str | None:
    """A new fork of this chat, laid out beside it, and its id.

    It carries the parent as it stands this instant: everything said in it so
    far, and nothing said after. None when there is nothing to carry - a chat
    with nothing in it, or a draft that is not a chat yet - because a fork of
    nothing is a new chat, and New chat is already a button. A Synapse chat
    and a task's chat are the exceptions (`bare`): their fork comes off
    before anything, carrying no words (`at` is None) and the dataset it was
    made over, or the task it is part of (`task_above`). The draft of a
    task's chat is made a chat first, empty.

    `before` is an exchange of the parent, and the fork comes off just above
    it: Fork on the box a message is being edited in, which asks the new
    words in a fork of the chat as it stood when the message was first asked.
    Petar, 26 September 2026 (fr_16b9bf1db8db): "When I edit a message I
    should have a fork and submit buttons the same as in my main input". The
    first message of a chat has nothing above it, and is None the same way.

    `through` is an exchange of the parent too, and the fork comes off just
    below it, carrying it and everything above it and nothing said since:
    /fork written on Telegram as a reply to one of Rouh's answers, which is
    that exact point in the conversation however much has been said there
    after it (`rouh/telegram_forks.py`).

    The tab that made it lays it out as the end of its strip, in the place of
    any other fork of the same parent it had open (`strip`): that one is only
    off the strip, and its mark in the parent still opens it.

    A fork of General answers on General's tier, and a fork of any other chat
    on the tier every other chat is on (`chatkinds.use_for`), unless the parent was
    set to Cheap, Smart or Auto by hand, which the fork is set to as well.
    """
    if not parent_id:
        return None
    if conversations.chat(parent_id) is None:
        # The draft of a task's chat is made a chat, with nothing in it, so
        # the first message can go into a fork of it and leave it clean
        # (`bare`). Any other draft is still a new chat, and has no fork.
        held = conversations.draft(parent_id)
        if not (held and held.get("task")) or before is not None or through is not None:
            return None
        conversations.make(parent_id)
        if conversations.chat(parent_id) is None:
            return None
    at = _last_message(parent_id, before, through)
    if at is None and (through is not None or not bare(parent_id)):
        return None
    # One transaction for the chat and the row that makes it a fork, so there
    # is never a moment - nor, after a failure, a leftover - where it is an
    # ordinary chat at the top of the list.
    # The model the person picked by hand beside the composer goes with it (Petar,
    # 9 November 2026, fr_433a35305d4e: Cheap chosen in General, and a hard message in
    # its fork was answered on Smart by the router): a fork is the same conversation
    # carried on, and a choice made by hand holds until they change it. A parent that
    # follows the Models page leaves the fork following it too.
    chosen = chatkinds.stored_choice(parent_id)
    with transaction.atomic():
        chat_id = conversations.new_chat()
        ChatFork.objects.create(chat_id=chat_id, parent_id=parent_id, at=at,
                                created_at=time.time())
        if chosen:
            Chat.objects.filter(id=chat_id).update(model_choice=chosen)
    log.info("chat %s forked into %s after message %s%s", parent_id, chat_id, at,
             f", above exchange {before}" if before is not None else
             f", through exchange {through}" if through is not None else "")
    return chat_id


def close(chat_id: str) -> str:
    """The chat a fork came off, which is where closing it puts a tab, or ""
    when it is not a fork laid out beside one.

    Petar, 26 September 2026 (fr_a3aadda7007c): "each of the nested chats has
    its own close button that closes this chat and all its children". Closing
    is the tab's own strip ending at that chat (`strip`), so the forks to its
    right go too. Nothing is written and nothing is deleted: each one is
    still marked in the chat it came off, and its mark opens it again.
    """
    return parent_of(chat_id)


def strip(chat_id: str, tip: str = "") -> list[str]:
    """The chats laid out left to right with this one among them.

    `tip` is the far end of the tab's strip: the deepest fork it has open to
    the right of this chat. The strip is every chat from the one it all
    started in down to the tip, when this chat is one of them; otherwise it
    ends at this chat. A chat with no parent and no tip below it is a strip
    of one, which is to say no strip at all, and the page draws nothing extra.
    """
    if tip and tip != chat_id:
        line = lineage(tip)
        if chat_id in line:
            return line
    return lineage(chat_id)


def tip_for(chat_id: str, tip: str = "") -> str:
    """The end of the strip a tab showing `chat_id` lays out, as asked: `tip`
    when it is this chat or a fork below it, and this chat otherwise."""
    if tip and tip != chat_id and chat_id in lineage(tip):
        return tip
    return chat_id


#: How much of the question a fork was opened with its mark carries. The whole
#: of anything a person types to ask about one answer; a cut only for a page
#: pasted in, which would otherwise be a second copy of the page in the chat.
ASKED_CHARS = 2000


def asked(chat_id: str) -> str:
    """What the person asked in this fork to open it: its first message, whole.

    Read from the transcript and drawn the way the page draws that message in
    the fork itself (`Memory._said`), line breaks and all. The chat's own
    record would be simpler to ask, but it folds every run of whitespace into
    one space (`conversations.add_turn`). Empty when it opened with a file and
    no words.
    """
    return asked_of([chat_id]).get(chat_id, "")


#: How many of a fork's first rows of the person's are read to find the question it opened with.
ASKED_ROWS = 12


def asked_of(chat_ids) -> dict[str, str]:
    """`asked` for many forks at once, in one query: each fork's first few rows of the person's,
    numbered within the fork by the database. Until 23 October 2026 this was a query per fork,
    and General had 243 of them: the list of its forks was 566 queries on every connect and every
    list of the chats, which was most of the 17 seconds the conversation took to appear."""
    from django.db.models import F, Window
    from django.db.models.functions import RowNumber

    from .memory import Memory, _begins_a_question

    ids = [c for c in dict.fromkeys(chat_ids) if c]
    if not ids:
        return {}
    rows = (TranscriptMessage.objects
            .filter(session_id__in=ids, live=True, role="user", note=False)
            .annotate(nth=Window(RowNumber(), partition_by=[F("session_id")], order_by=F("id").asc()))
            .filter(nth__lte=ASKED_ROWS)
            .order_by("session_id", "id")
            .values("id", "ts", "role", "content", "note", "session_id"))
    out: dict[str, str] = {}
    for row in rows:
        chat = row.pop("session_id")
        if chat in out or not _begins_a_question(row["role"], row["content"]):
            continue
        said = Memory._said(row)
        if said is None or said.get("stopped"):
            continue
        text = (said.get("text") or "").strip()
        out[chat] = text if len(text) <= ASKED_CHARS else text[:ASKED_CHARS].rstrip() + "\u2026"
    return out


def children(chat_id: str) -> list[dict]:
    """Every fork of this chat, oldest first: what its conversation marks.

    `at` is the parent's message each came off after, and `ex` the exchange
    that message is part of, which is where the page puts the mark: under
    the last message of that exchange, wherever an exchange edited since has
    written its rows. Whether it is on the strip is the tab's to say. `asked`
    is the question the fork was opened with, which the mark shows whole:
    Petar, 26 September 2026 (fr_a3aadda7007c), "I would like to see the full
    original message, not just the first few words of a summary" - the title
    being that summary.

    A fork that was cut, because it became a task's chat, keeps its mark and
    the mark says so: `task` is that task's number, name and folder, which the
    mark opens instead of laying the fork out beside this chat (`cut`). A cut
    fork's task may have been deleted since; its mark goes with it.

    A fork the person detached (`detach`) is cut with no task: its mark stays
    too, with `detached` set, and opens it as the chat of its own it is now.

    A handful of queries whatever the number of forks: the chats, their
    questions and their message counts are each read for all of them at once.
    """
    rows = list(ChatFork.objects.filter(parent_id=chat_id)
                .order_by("created_at").values("chat_id", "at", "cut_at"))
    if not rows:
        return []
    from .memory import _exchange

    exchange = dict(TranscriptMessage.objects.filter(id__in=[r["at"] for r in rows if r["at"]])
                    .annotate(ex=_exchange()).values_list("id", "ex"))
    st = conversations.store()
    ids = [r["chat_id"] for r in rows]
    chats = st.get_chats(ids)
    said = st.message_counts(ids)
    questions = asked_of(ids)
    owners = st.tasks_owning_chats([r["chat_id"] for r in rows if r["cut_at"] is not None])
    # Each task a fork became, as it looks everywhere else: its icon and its project's colour.
    faces = {}
    if any(owner is not None for owner in owners.values()):
        from .objectindex import task_faces

        faces = task_faces(st, [owner.id for owner in owners.values() if owner is not None])
    out = []
    for row in rows:
        chat = chats.get(row["chat_id"])
        if chat is None:
            continue
        task = None
        detached = False
        if row["cut_at"] is not None:
            # Owned by a link, read for them all above; with none, it may still be a draft's.
            owner = owners[chat.id] if chat.id in owners else conversations.task_of(chat.id)
            if owner is None:
                detached = True
            else:
                face = faces.get(owner.id) or {}
                task = {"number": owner.number, "name": owner.title, "folder": owner.folder,
                        "icon": face.get("icon", ""), "img": face.get("img", ""),
                        "color": face.get("color", "")}
        title = (chat.title or "").strip()
        titled = not conversations.is_untitled(title)
        out.append({"id": chat.id, "title": title if titled else conversations.UNTITLED,
                    "titled": titled, "messages": int(said.get(chat.id, 0)),
                    "asked": questions.get(chat.id, ""),
                    "at": row["at"], "ex": exchange.get(row["at"], row["at"]),
                    "task": task,
                    "detached": detached})
    return out


def family(chat_id: str) -> list[tuple[str, int]]:
    """Every fork still laid out off this chat, however deep, as (chat, depth):
    each fork straight after the chat it came off, oldest first, the way a
    task's page lists them under the chat (`objectindex._chat_rows`)."""
    out: list[tuple[str, int]] = []
    seen = {chat_id}

    def down(parent: str, depth: int) -> None:
        if depth > DEEP:
            return
        for kid in (_laid().filter(parent_id=parent).order_by("created_at")
                    .values_list("chat_id", flat=True)):
            if kid in seen:
                continue
            seen.add(kid)
            out.append((kid, depth))
            down(kid, depth + 1)

    if chat_id:
        down(chat_id, 1)
    return out


def under(chat_ids) -> list[str]:
    """Every fork below these chats, however deep, the deepest first.

    Asked before the chats are deleted, because the database drops a fork's
    row the moment its parent goes and what hung there could not be found
    afterwards.
    """
    found: list[str] = []
    level = [c for c in chat_ids or [] if c]
    seen = set(level)
    while level and len(seen) < 10_000:
        below = list(_laid().filter(parent_id__in=level)
                     .values_list("chat_id", flat=True))
        below = [c for c in below if c not in seen]
        seen.update(below)
        found.extend(below)
        level = below
    found.reverse()
    return found
