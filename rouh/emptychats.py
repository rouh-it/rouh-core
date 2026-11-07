"""The empty chats that opening a task left behind: found, and taken away once.

What happened
-------------

Until 23 September 2026, opening a task made its conversation on the spot.
The page sends `open_thread` whenever a task is picked - from the task browser,
the rail, the breadcrumb, a step - and the server answered a task with no chat
by making one, titled with the task's number and name and owned by the task
(`conversations.open_for_task`, and `open_thread` in the server before it). So
every task the person had ever clicked on owned a chat with nothing in it, and
its own page said "1 chat" about a conversation nobody had started. Petar found
it on task 08, which predates Rouh being an assistant at all.

It was not the import. `sqlite_import.py` copied the rows it was given and the
earlier move onto the object model (`conversations.take_in_chat`) carried each
thread once; both only carried along what opening had already made. Rouh's own
log says which press made each one: "made the conversation for task 8
(private/misc/08.garden-project)" at the minute the row was created.

Opening a task makes nothing now: it hands the page a draft, and the chat is
written by the first thing said in it (`conversations.open_draft`). What is
here is the clean-up of the ones already made, and nothing else.

What is taken away, and what is left
------------------------------------

Only a chat that is **provably** one of those, which is every one of these:

- nothing was ever said in it: no row in `message` and none in the model's own
  tape (`messages`);
- nothing else was ever put in it or hung off it: no card (`screen_cards`), no
  cost (`spend`), no turn in flight (`open_turns`), no file on disk under its id,
  no file on a piece of feedback, no worker, and no link at all but the one
  `owns` link from its task or project - so it owns nothing and no run came
  from it;
- it is owned by a task or a project, and is still called what opening named
  it: the speech balloon, then that owner's number and name, or its name;
- nobody ever did anything to it: never pinned, never marked unread, and both
  of its clocks still where they were the instant it was made - renaming,
  filing, keeping or saying anything would have moved one;
- it is not the chat anybody is in right now, it is not General, and it was
  made more than `QUIET` seconds ago, so a conversation somebody opened a
  moment ago on the old code and is about to type into is not pulled out from
  under them.

Anything with no messages that fails even one of those is **left alone** and
reported with the reasons, because a chat that might be somebody's is not this
module's to decide about. `manage.py empty_chats` prints both lists and deletes
nothing; `rouh/migrations/0004_remove_empty_task_chats.py` is the one place the
removal runs, once, in the deploy.

The models are handed in rather than imported, so the migration can run this
against the historical models of the schema it is at.
"""
from __future__ import annotations

import os
import time

#: What `chats.FALLBACK_EMOJI` put in front of every title opening gave a chat.
BALLOON = "\N{SPEECH BALLOON}"

#: How long a chat must have been left before it can be called abandoned: a
#: chat made in the last ten minutes may be one somebody has just opened and
#: is about to speak into.
QUIET = 600.0

#: How far apart two clocks may be and still be the same instant. They are
#: written from one `time.time()` when a chat is made.
SAME = 1.0

#: The one thread that is always there (`conversations.GENERAL`).
GENERAL = "conversation"


def _attachments_of(data_dir: str, chat_id: str) -> str:
    """"" when nothing was ever attached in this chat, otherwise why not sure.

    A directory under the chat's id is a file somebody put there. A directory
    that cannot be looked at is treated the same way: not knowing is not
    permission.
    """
    if not data_dir:
        return "no data directory to look for its files in"
    try:
        os.lstat(os.path.join(data_dir, "attachments", chat_id))
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return f"its attachments could not be looked at ({exc.strerror or exc})"
    return "files were attached in it"


def survey(get, *, data_dir: str, now: float | None = None) -> dict:
    """Every chat with nothing said in it, sorted into what may go and what stays.

    `get(name)` hands back a model by its class name: `apps.get_model("rouh",
    name)` in a migration, the same through `django.apps` everywhere else.
    Answers `{"remove": [...], "keep": [...]}`, each a list of
    `{id, title, created_at, owner, owner_title, why}`, oldest first; `why` is
    empty for a chat that may go and says every reason for one that stays.
    """
    Chat, ChatMessage = get("Chat"), get("ChatMessage")
    TranscriptMessage, ScreenCard = get("TranscriptMessage"), get("ScreenCard")
    Spend, OpenTurn, AppState = get("Spend"), get("OpenTurn"), get("AppState")
    Link, Task, Project = get("Link"), get("Task"), get("Project")
    FeedbackFile, Crewmate = get("FeedbackFile"), get("Crewmate")
    now = time.time() if now is None else now

    said = set(ChatMessage.objects.values_list("chat_id", flat=True).distinct())
    empty = list(Chat.objects.exclude(id__in=said).order_by("created_at", "id"))
    if not empty:
        return {"remove": [], "keep": []}
    ids = [c.id for c in empty]
    taped = set(TranscriptMessage.objects.filter(session_id__in=ids)
                .values_list("session_id", flat=True))
    carded = set(ScreenCard.objects.filter(session_id__in=ids)
                 .values_list("session_id", flat=True))
    spent = set(Spend.objects.filter(session_id__in=ids).values_list("session_id", flat=True))
    turning = set(OpenTurn.objects.filter(session_id__in=ids)
                  .values_list("session_id", flat=True))
    filed = set(FeedbackFile.objects.filter(session__in=ids).values_list("session", flat=True))
    crewed = set(Crewmate.objects.filter(session__in=ids).values_list("session", flat=True))
    active = AppState.objects.filter(key="active_chat").values_list("value", flat=True).first()

    owners: dict[str, tuple[str, str]] = {}
    others: dict[str, int] = {}
    for link in Link.objects.filter(dst_type="chat", dst_id__in=ids):
        if link.rel == "owns":
            owners[link.dst_id] = (link.src_type, link.src_id)
        else:
            others[link.dst_id] = others.get(link.dst_id, 0) + 1
    for link in Link.objects.filter(src_type="chat", src_id__in=ids):
        others[link.src_id] = others.get(link.src_id, 0) + 1

    tasks = {t.id: t for t in Task.objects.filter(
        id__in=[o[1] for o in owners.values() if o[0] == "task"])}
    projects = {p.id: p for p in Project.objects.filter(
        id__in=[o[1] for o in owners.values() if o[0] == "project"])}

    going, staying = [], []
    for chat in empty:
        why = []
        owner = owners.get(chat.id)
        holder = None
        if owner is None:
            why.append("it belongs to no task or project, so opening a task did not make it")
        elif owner[0] == "task":
            holder = tasks.get(owner[1])
        elif owner[0] == "project":
            holder = projects.get(owner[1])
        else:
            why.append(f"it is owned by a {owner[0]}")
        if owner is not None and owner[0] in ("task", "project") and holder is None:
            why.append(f"the {owner[0]} that owns it is not there")
        if chat.id in taped:
            why.append("the model's own tape has turns in it")
        if chat.id in carded:
            why.append("cards were drawn in it")
        if chat.id in spent:
            why.append("a turn was paid for in it")
        if chat.id in turning:
            why.append("a turn is in flight in it")
        if chat.id in filed:
            why.append("a piece of feedback carries a file from it")
        if chat.id in crewed:
            why.append("a worker was started from it")
        if others.get(chat.id):
            why.append("it owns something, or something was made from it")
        if chat.pinned:
            why.append("somebody pinned it")
        if chat.unread:
            why.append("it is marked as having something unread")
        if (abs(float(chat.last_activity or 0) - float(chat.created_at or 0)) > SAME
                or abs(float(chat.last_spoke or 0) - float(chat.created_at or 0)) > SAME):
            why.append("it was used after it was made")
        if chat.id == GENERAL:
            why.append("it is General")
        if active and chat.id == active:
            why.append("it is the chat open right now")
        if now - float(chat.created_at or 0) < QUIET:
            why.append("it was made in the last ten minutes")
        title = (chat.title or "").strip()
        if holder is not None:
            named = str(getattr(holder, "title", "") or "")
            number = getattr(holder, "number", None)
            given = {f"{BALLOON} {named}".strip()}
            if number is not None:
                given.add(f"{BALLOON} {number} {named}".strip())
            if title not in given:
                why.append("it is not called what opening its "
                           f"{owner[0]} named it, so somebody may have named it")
        on_disk = _attachments_of(data_dir, chat.id)
        if on_disk:
            why.append(on_disk)
        called = ""
        if holder is not None:
            number = getattr(holder, "number", None)
            called = (f"{number} " if number is not None else "") + str(holder.title or "")
        (staying if why else going).append({
            "id": chat.id, "title": title, "created_at": float(chat.created_at or 0),
            "owner": f"{owner[0]}:{owner[1]}" if owner else "",
            "owner_title": called, "why": "; ".join(why)})
    return {"remove": going, "keep": staying}


def remove(get, ids: list[str]) -> int:
    """Delete these chats and the one `owns` link each hangs by. How many went.

    Only ever handed what `survey` put in its `remove` list, in the same
    transaction it was surveyed in. A chat's own messages would go with it
    (`message` is its only cascade); these have none, which is why they are
    here.
    """
    if not ids:
        return 0
    Chat, ChatMessage, Link = get("Chat"), get("ChatMessage"), get("Link")
    chats = Chat.objects.filter(id__in=ids)
    gone = chats.count()
    ChatMessage.objects.filter(chat_id__in=ids).delete()
    Link.objects.filter(dst_type="chat", dst_id__in=ids).delete()
    chats.delete()
    return int(gone)
