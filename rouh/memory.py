"""What Rouh remembers between one conversation and the next.

Two different things share this file, because they have the same lifetime and
the same backup story:

- **Transcript.** Every turn of every chat - see CONVERSATION below - so a
  reload does not lose the thread, so a browser that has never been opened
  before shows the same history as every other one, and so there is something to
  read back when a delegated job finishes. There is more than one chat now: each
  is its own history and its own context window, one of them is the active one,
  and the live voice session works against whichever that is.
- **Facts.** Short standing statements the assistant chose to keep: "the bank's
  contact is Sam", "prefers metric". These are injected into the
  system prompt, so they are deliberately capped - an unbounded memory becomes
  an unbounded prompt, and then every turn gets slower and more expensive
  forever.

PostgreSQL, through Django, since 23 September 2026 (`rouh/models/memory.py`).
Until then this was SQLite in WAL mode, a file of its own beside the data,
chosen because one process wrote it and a file is easy to back up. The
database is Rouh's one database now, backed up and inspected with everything
else, and every table kept the name it had. One process still writes, and the
lock below is still what keeps a read-then-write in this module from crossing
another one.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import threading
import time
from typing import Callable

from django.contrib.postgres.aggregates import BoolOr
from django.db import transaction
from django.db.models import (BigIntegerField, Case, Count, Max, Min, OuterRef, Q, Subquery,
                              Sum, TextField, Value, When)
from django.db.models.functions import Coalesce

from . import attachments, citing, conversations, forks, servercalls, turnmarks, turnrecords
from .models.memory import (AppState, ChatFolder, Event, Fact, LegacySession, OpenTurn, RecallTimeline,
                            RouteTimeline,
                            ScreenCard, Spend, ToolLine, TranscriptMessage)
from .models.objects import ChatFork
from .stopping import STOP_NOTE

log = logging.getLogger("rouh.memory")

# --- the tables, and what each one is for ---------------------------------
#
# They are the models in `rouh/models/memory.py`, made and changed by
# Django's migrations in PostgreSQL. Until 23 September 2026 they were SQLite
# tables this module made for itself with `CREATE TABLE IF NOT EXISTS` and
# grew with `ALTER TABLE` whenever it found a column missing, and the notes
# below were written beside those statements. The tables kept their names
# across the move, so every note still reads true.
#
# None of them has a foreign key the database enforces, on purpose. SQLite
# never enforced the ones they declared - this module never switched
# `foreign_keys` on - and the code below was written against that: a
# transcript row outlives the legacy `sessions` row it names.
#
# `sessions`:
#
# What a chat was until 21 September 2026, when the conversations moved onto
# `objects.chat` and the task that owns one became a row in the link table
# rather than a folder name written into this one.
#
# Nothing reads it now. It is kept, unwritten, as what the move was made from:
# every row of it was taken in with its id, its title and its turns, and a
# file that has been through that move still holds the before as well as the
# after. Every row of `messages` below still names one of its ids, which is
# why the table itself stays rather than being dropped.
#
# **Nothing may start writing it again.** A chat is a row of `objects.chat`,
# `rouh/conversations.py` is the only module that writes one, and what a
# chat drew is an `artifact` its id owns (`rouh/artifacts.py`).
#
# `task` (a column of the table above):
#
# The workspace task this chat is, as a folder under the workspace root:
# "tasks/30.jarvis". Empty for a chat that is about nothing filed yet.
#
# A chat with one of these is not a chat *about* that task, it is that
# task: picking it in the rail is picking the task, the canvas opens on
# it, and a card drawn by a turn asked in it is written into that task
# folder as its next numbered step. There is no second object to
# drift from the first, which is the whole reason the column is here.
#
# `unread` (a column of the table above):
#
# Whether this thread has something in it the person has not seen.
#
# A turn is answered by the server and belongs to the thread it was asked
# in, not to whatever the screen happens to be showing, so an answer can
# land in a thread nobody is looking at. This is the quiet sign that it
# did: set when a turn finishes anywhere but the thread on screen, and
# cleared the moment that thread is opened. It is never spoken and it
# never takes the view back; it is a dot in the rail and nothing more.
#
# `chat_folders`:
#
# A chat's folder, and the folders themselves, as they were before step three.
# Nothing writes either any more: a project is a row of `project` and which
# one a chat is in is an `owns` link (`conversations.py`). This is read once,
# by the migration that takes them over, and is kept only for a database that
# has not been through it.
#
# `app_state`:
#
# Small standing facts about the page itself rather than about the person:
# which chat is the active one, and whether the one-time fold below has run.
#
# `messages`: every turn of every chat, as the Anthropic content blocks it was
# sent as, JSON in a text column.
#
# `root` (a column of the table above):
#
# Which exchange of the conversation this row belongs to, and which try.
#
# An exchange is one question and the answer to it, and it can be asked
# more than once: the person presses retry, or edits what they asked and
# sends it again. `root` is the id of the question the exchange began
# with, and every row written while answering it - the question, the
# answer, the tool calls and their results - carries the same one. Each
# try is a `version`, and exactly one version of an exchange is `live`:
# the one the conversation is, the one the page draws and the one the
# model is sent. The others are kept, and stepping back to one is what
# the arrows under a message do (`pick_version`).
#
# Since 4 November 2026 a try is also a branch of the conversation:
# `follows` on a try's first row is the first row of the try of the
# exchange before it that it was asked after, and `picked` is the try the
# person chose. `live` is the path through that tree the choices pick, so
# what was said after an old try stays with it (`_relive`).
#
# Null for every row written before the column existed. A null means
# "this row is its own exchange", which is exactly what the conversation
# was before there was anything to version, so nothing has to be
# rewritten: `COALESCE(root, id)` is the exchange of any row, and it is
# what everything here orders by.
#
# `facts`: short standing statements, capped at `MAX_FACTS` (`remember`).
#
# `screen_cards`:
#
# **The screen, as it was kept before the object model.** Every row here was
# migrated into an `artifact` with its number - card 37 became `card-37` -
# and `rouh/artifacts.py` is what writes and reads the screen now. The table
# is left exactly as it was found: it is what the migration reads, once, on
# each start, and a record nobody has to trust to nothing having gone wrong.
# With `object_model_enabled` off, this is the screen again and everything
# below works as it always did.
#
# `after_message_id` (a column of the table above):
#
# The message this card came after: the assistant turn whose tool call
# drew it. The transcript is one stream of messages and cards in the
# order they happened, and this is what puts a card back in its place in
# that stream after a reload. It is an ordering fact and nothing more:
# what the card holds is in `spec` and is never copied into `messages`.
#
# Null for every card drawn before this column existed, and for a card
# drawn in a chat that has nothing said in it yet. A null falls back to
# ordering by `ts`, which is what the page did before there was a column
# to ask.
#
# `events`: something worth a line in the record that is not a turn (`log`).
#
# `spend`:
#
# What each turn cost, in tokens and in money. One row per turn, written when
# it ends (`rouh/costs.py`).
#
# Kept rather than counted in memory because the question people ask is "what
# has this been costing me", which is a question about last week as much as
# about this minute, and because a restart must not make the answer zero.
#
# `open_turns`:
#
# A turn that has started and has not finished. One row per chat, written the
# moment a turn begins and deleted the moment it ends, however it ends.
#
# It exists for the restart. A turn cut short by the process going away used
# to leave nothing at all: the half-written answer was never stored, the
# dangling tool call was quietly dropped on the next read of the history, and
# what the person saw was a question they had asked and no reply, ever, with
# nothing anywhere saying why. A row left here after a restart is that turn,
# and `mark_interrupted` turns it into a sentence in the transcript.

MAX_FACTS = 120
MAX_FACT_CHARS = 400

#: The first chat, and the one every device was in before there were chats.
#:
#: Until 16 September 2026 each browser made up an id of its own and kept it in
#: its local storage, which meant the phone and the desktop each had a
#: transcript of their own and neither could see what had been said to the
#: other. Everything was then folded into this one row, and for a while it was
#: the only conversation there was.
#:
#: It is now the first of many. A chat is a row of `objects.chat`, with its own
#: messages, its own cards and its own title; this one is the chat every
#: earlier turn was migrated into, so nothing that was ever said is lost. What
#: has not changed is that a page does not decide which chat it is in: the
#: server holds one active chat for the person, so the phone, the desktop and a
#: browser opened for the first time are all looking at the same one.
#:
#: Named by `conversations.GENERAL`, because which chat that is decides what
#: is never numbered, and two of that constant is one too many.
CONVERSATION = conversations.GENERAL

#: Where the active chat is remembered, in `app_state`.
ACTIVE_CHAT = "active_chat"

#: Set once the chats have been moved onto `objects.chat`, so the move never
#: runs a second time. It does nothing the second time in any case - every part
#: of it asks whether the row is already there - and the mark is what says
#: plainly that the move is behind us.
#:
#: The number on the end is how a fixed move is run again over a database that
#: has already been through the old one. It went to 2 the same evening: the
#: first move gave a thread to its task only where nothing owned the chat yet,
#: and on the live database every chat had been put under its folder's project
#: an hour earlier, so the nine threads that were numbered work stayed filed as
#: loose chats. Running it again is what repairs them, and it costs nothing
#: where there is nothing to repair.
MOVED = "chats_onto_the_object_model_2"

#: Set once the fold below has run, so it never runs again. Without it, the
#: fold's "delete every session that is not the one conversation" would throw
#: away every chat made since, on the next restart.
FOLDED = "folded_into_one_conversation"

#: What a chat is called before the model has read its first exchange, how long
#: a title may be, and how long a project's name may be. All three belong to
#: the module that keeps the chats now, and are named here because the rest of
#: Rouh has always asked this one for them.
UNTITLED = conversations.UNTITLED
MAX_TITLE = conversations.MAX_TITLE
MAX_FOLDER_NAME = conversations.MAX_PROJECT_NAME

#: Which chat the turn now running is answering into.
#:
#: A turn belongs to the thread it was asked in and goes on to the end whether
#: or not that thread is on the screen, so "the chat this belongs to" and "the
#: chat the person is looking at" are two different questions and the code that
#: writes something down must ask the first. Most of it is told which chat it
#: is writing into; a card is not, because it is drawn from inside a tool that
#: knows nothing about chats, and this is how it finds out (`add_card`, and
#: `tools._file_into_the_thread`).
#:
#: A context variable rather than a global: a task carries a copy of the
#: context it was created in, so a turn started in one thread cannot be read
#: back by a turn running beside it in another. Empty means nobody is
#: answering anything, and then the active chat is the right answer.
ANSWERING = contextvars.ContextVar("rouh_answering_in", default="")


@contextlib.contextmanager
def answering_in(chat_id: str):
    """Everything written inside this block belongs to that conversation.

    The other half of `ANSWERING`. A turn sets it once and runs to its end
    inside a task of its own; a job's report is not a turn and has no task to
    speak of, so it says where it belongs around the few lines that write
    something down - the card, the note handed to Rouh - and puts it back
    afterwards.

    An empty id says nothing, which is what it always meant: the chat the
    person is looking at is the right answer when nothing knows better. A
    run's report never passes one: a run nobody started from a conversation
    reports in General (`runs.reports_to`), because the chat on the screen is
    the one answer that is always wrong for it.
    """
    token = ANSWERING.set(chat_id or "")
    try:
        yield
    finally:
        ANSWERING.reset(token)


def his_own_words(chat_id: str, *, until: float | None = None, most: int = 500) -> list[str]:
    """What the person themselves said in a chat, newest first.

    Their own messages, typed, said or sent from their phone, and nothing else
    a `user` row can hold: never a tool's result, a note of Rouh's software,
    the note left where they pressed Stop, an attachment, or the passage of a
    page an Ask AI question was about (only the question is theirs). `until`
    leaves out what they said after that moment.

    It is where `his_words` is checked for giving or taking a trusted contact's
    authority (`tools.ToolRegistry._delegate`) and what a Clockwork row keeps
    of what asked for it (`reminders.asked_of`): authority comes from the
    person's own words and never from mail, a page, a file or a job's output.
    """
    if not chat_id:
        return []
    rows = TranscriptMessage.objects.filter(session_id=chat_id, role="user", live=True,
                                            note=False)
    if until is not None:
        rows = rows.filter(ts__lte=until)
    out = []
    for content in rows.order_by("-id").values_list("content", flat=True)[:most]:
        if _is_a_reply_to_a_tool(content):
            continue
        try:
            blocks = json.loads(content)
        except (TypeError, ValueError):
            blocks = content
        if isinstance(blocks, list):
            blocks = [b for b in blocks if not (
                isinstance(b, dict) and str(b.get("text") or "").lstrip().startswith(turnmarks.NOTE))]
        text = _words("user", blocks).strip()
        if text and text != STOP_NOTE and not text.startswith(turnmarks.NOTE):
            out.append(text)
    return out


# --- Ask AI, in the conversation ---------------------------------------------
#
# Petar, 27 September 2026 (fr_dd4ac24658fa): "ask ai doesn't get included in
# the orb and it should". Ask AI kept its exchanges in rows of its own
# (`askai.Threads`), so the chat on the screen - the one the orb and the Rouh
# tab talk in - had never heard of them, and a follow-up said to the orb
# started from nothing. Each exchange the owner has in Ask AI is now written
# into that chat as well (`add_askai`), as one of their questions and its
# answer: they are drawn there, marked as Ask AI's, and the model reads them
# like any other turn.
#
# Which page it was about travels in the question's first block, in words the
# model reads as they are, and in the passage block after it when one was
# selected. `askai_of` is what takes them back off for the screen, so the
# person sees their own question under a small label rather than the note.

#: The first words of the block that says a question was asked in Ask AI.
ASKAI_MARK = "[Asked in Ask AI, the side of the conversation column that answers about the page on the canvas."
#: The first words of the block holding the passage selected on the page.
ASKAI_PASSAGE = "[The passage they selected on the page:"


def _askai_head(doc: str, title: str) -> str:
    return (f"{ASKAI_MARK}\npage: {title or doc}\naddress: {doc}\n"
            "The answer after this came from Ask AI, with the page and its working notes in "
            "front of it. If the person follows it up here, carry on from it.]")


def askai_of(content) -> dict | None:
    """What an Ask AI question was about, and the question itself, or None.

    ``{"title", "doc", "passage", "question"}`` for a row `add_askai` wrote,
    and None for every other row.
    """
    if isinstance(content, str) or not isinstance(content, list) or not content:
        return None
    first = content[0]
    if not (isinstance(first, dict) and first.get("type") == "text"
            and str(first.get("text", "")).startswith(ASKAI_MARK)):
        return None
    out = {"title": "", "doc": "", "passage": ""}
    for line in str(first.get("text", "")).splitlines():
        if line.startswith("page: "):
            out["title"] = line[len("page: "):].strip()
        elif line.startswith("address: "):
            out["doc"] = line[len("address: "):].strip()
    rest = list(content[1:])
    if (rest and isinstance(rest[0], dict)
            and str(rest[0].get("text", "")).startswith(ASKAI_PASSAGE)):
        passage = str(rest.pop(0).get("text", ""))[len(ASKAI_PASSAGE):]
        out["passage"] = passage.strip().removesuffix("]").strip()
    out["question"] = _plain(rest)
    return out


def _blocks_of_type(content, kind: str) -> list[dict]:
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == kind]


def repair_history(msgs: list[dict]) -> list[dict]:
    """Make a slice of a conversation into one the API will accept.

    Pure and side-effect free so it can be tested without a database.
    """
    msgs = _history_from_user(msgs)
    msgs = _history_without_unanswered_tail(msgs)
    out = _history_without_broken_tool_pairs(msgs)

    # Dropping a pair in the middle can leave the front invalid again.
    out = _history_from_user(out)
    out = _history_without_empty_text(out)

    # 5. A call of Anthropic's own (web search, web fetch, the tool search,
    #    code execution) whose result is not where the API looks for it. A
    #    turn that failed after the model asked for one of those beside one of
    #    Rouh's tools left the reply holding it stored, waiting on a result
    #    the API never gave; the next question after it is refused, and so is
    #    every one after that (`rouh/servercalls.py`). Taken out on the way,
    #    like the empty text above, with nothing deleted from the database.
    out = servercalls.repair(out, where="a chat's history")
    return out


def drop_carried_stops(msgs: list[dict]) -> list[dict]:
    """What a fork carries of the chat it came off, without any turn stopped there.

    A stopped turn is stored with `stopping.STOP_NOTE` in the person's place,
    which tells the model to carry on from what they say next: right in the
    chat it was stopped in, and wrong in a fork, where what they say next is
    about something else. On 3 November 2026 forks of General read a request
    stopped there as still open and kept saying it was on hold, and a note of
    any kind in its place was asked away the same day (‹owner›: "Just remove
    the rule/note altogether"). Leaving only the note out was not enough: the
    stopped request then sat right above the fork's first words, read as one
    message with them, and on 4 November 2026 a fork about something else
    entirely started a job for the request stopped in General.

    So a fork carries no stopped exchange at all: the request the person
    stopped, whatever was said or called of it before the stop, and the note.
    It is still in the chat it was asked in, which reads it as before; in a
    fork it is asked again if it is wanted. Pure: the parent's rows, and the
    caller's list, are left as they were.
    """
    out: list[dict] = []
    for m in msgs:
        if m.get("role") == "user" and _plain(m.get("content")) == STOP_NOTE:
            # Back to the person's own words that began the stopped exchange,
            # and those words with it: what the model had said or called
            # after them was part of the turn that was stopped.
            while out:
                gone = out.pop()
                if gone.get("role") == "user" and not _blocks_of_type(gone.get("content"), "tool_result"):
                    break
            continue
        out.append(m)
    return out


def _history_from_user(msgs: list[dict]) -> list[dict]:
    """Drop the unusable prefix without changing the caller's list."""
    msgs = list(msgs)

    # Front: drop until a user message that is not a set of tool results.
    while msgs:
        first = msgs[0]
        if first.get("role") != "user":
            msgs.pop(0)
            continue
        if _blocks_of_type(first.get("content"), "tool_result"):
            msgs.pop(0)
            continue
        break
    return msgs


def _history_without_unanswered_tail(msgs: list[dict]) -> list[dict]:
    """Drop trailing unanswered tool calls from a copy of the list."""
    msgs = list(msgs)

    # Back: drop an assistant turn that asked for a tool nobody answered.
    while msgs:
        last = msgs[-1]
        if last.get("role") != "assistant":
            break
        asked = {b.get("id") for b in _blocks_of_type(last.get("content"), "tool_use")}
        if not asked:
            break
        msgs.pop()
        # Whatever came before it may now be dangling in the same way.
    return msgs


def _history_without_broken_tool_pairs(msgs: list[dict]) -> list[dict]:
    """Keep complete tool pairs and other messages in their original order."""
    # Middle: a tool call whose answer is missing breaks the pair, so drop both
    # sides rather than guess at a result that was never produced.
    out: list[dict] = []
    i = 0
    while i < len(msgs):
        msg = msgs[i]
        asked = {b.get("id") for b in _blocks_of_type(msg.get("content"), "tool_use")}
        if msg.get("role") == "assistant" and asked:
            nxt = msgs[i + 1] if i + 1 < len(msgs) else None
            answered = set()
            if nxt is not None and nxt.get("role") == "user":
                answered = {
                    b.get("tool_use_id")
                    for b in _blocks_of_type(nxt.get("content"), "tool_result")
                }
            if not asked.issubset(answered):
                i += 2 if nxt is not None and answered else 1
                continue
        out.append(msg)
        i += 1
    return out


def _history_without_empty_text(msgs: list[dict]) -> list[dict]:
    """Remove empty text blocks without dropping whole messages."""
    # 4. A text block with nothing in it is refused outright, with no index to
    #    say which message it came from ("messages: text content blocks must be
    #    non-empty"). One of those was stored on 2026-09-20 by the turn-mark
    #    stripping in brain.py, which is fixed now, and it killed the chat it
    #    was in for every later turn. This is the same fault as the three
    #    above and gets the same treatment, because the one that matters is
    #    whichever one nobody has thought of yet: a window is repaired on its
    #    way out, so a chat already holding a bad block answers again without
    #    anything being deleted from the database.
    return [_without_empty_text(m) for m in msgs]


def _without_empty_text(msg: dict) -> dict:
    """The message with any text block that holds no text taken out.

    Whitespace counts as empty: the API strips it and then refuses what is
    left. A message whose blocks all go is kept with none, which the API
    accepts, rather than dropped, because dropping it could break the
    tool_use/tool_result pairing the passes above have just settled.
    """
    blocks = msg.get("content")
    if not isinstance(blocks, list):
        return msg
    kept = [
        b for b in blocks
        if not (isinstance(b, dict) and b.get("type") == "text"
                and not str(b.get("text") or "").strip())
    ]
    return msg if len(kept) == len(blocks) else dict(msg, content=kept)


#: How any row says which exchange it belongs to. A row written before there
#: were exchanges has no root and is its own, which is what the conversation
#: was: read it this way and the old rows and the new ones sort and group
#: together with nothing rewritten. `_exchange` below is the same thing said to
#: the ORM, and `_in_exchange` the same test written so an index can serve it.
EXCHANGE = "COALESCE(root, id)"


def _exchange():
    """`COALESCE(root, id)`, as an expression to annotate, order or group by."""
    return Coalesce("root", "id", output_field=BigIntegerField())


def _in_exchange(root) -> Q:
    """Rows of one exchange: `COALESCE(root, id) = root`, spelled out.

    Spelled out rather than compared through the expression, because the two
    halves are each something an index answers (`messages_root` and the
    primary key) and an UPDATE or DELETE can be filtered on them directly.
    """
    return Q(root=root) | Q(root__isnull=True, id=root)


def _row_id(value) -> int | None:
    """A message or card number from outside, or None when it is not one.

    SQLite compared whatever it was handed against an integer column and
    simply found nothing when it was not a number. PostgreSQL refuses the
    query instead, so a number that is not one is answered here the way it
    always was: with nothing.
    """
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            as_float = float(value)
        except (TypeError, ValueError):
            return None
        return int(as_float) if as_float.is_integer() else None


def _limited(queryset, limit):
    """`LIMIT ?` as SQLite read it: a negative limit is no limit at all."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return queryset
    return queryset if limit < 0 else queryset[:limit]


def _room(limit, used: int):
    """What is left of a `_limited` limit once `used` rows have been taken.

    No limit leaves no limit, which is what a negative one means above.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return -1
    return -1 if limit < 0 else max(0, limit - used)


def _least(one, other) -> int:
    """The smaller of two `_limited` limits, where below zero is no limit."""
    one, other = int(one), int(other)
    if one < 0:
        return other
    if other < 0:
        return one
    return min(one, other)


class Slot:
    """Which exchange a turn is writing into, and which try it is.

    A turn started by the person asking something new carries an empty one:
    the question becomes the exchange, and its own id becomes the root the
    moment it is written down. A turn started by retry or by an edited question
    carries the exchange it is answering again, and the number of the try, so
    everything it writes is a version of that exchange rather than a new one at
    the end of the conversation.
    """

    __slots__ = ("root", "version")

    def __init__(self, root: int | None = None, version: int = 1):
        self.root = root
        self.version = version

    @property
    def again(self) -> bool:
        """Whether this is an exchange being answered again."""
        return self.root is not None

    def __repr__(self) -> str:                              # pragma: no cover
        return f"Slot(root={self.root}, version={self.version})"



def _on_stage(rows, session_id: str):
    """A conversation as a turn on the stage in demo mode may read it: what was said on the stage,
    and what of the chat was approved for the demo, and nothing else of it (`rouh/demo.py`)."""
    from . import demo

    lens = demo.STAGE_LENS.get() if demo.on_stage() else None
    if lens is None or session_id in lens.stage_chats:
        return rows
    said = Q(ts__gte=lens.since - 1, notice=False)
    cutoff = lens.chats.get(session_id)
    if cutoff is None:
        return rows.filter(said)
    if cutoff:
        return rows.filter(Q(id__lte=cutoff) | said)
    return rows

class Memory:
    def __init__(self, path: str | None = None):
        """The transcript, the facts and the rest, in Rouh's one database.

        `path` was the SQLite file until 23 September 2026. It is accepted and
        ignored, so a caller written before the move still works while it is
        changed: the database is Django's to open now, and the schema is its
        migrations' to make, so there is nothing here to create or to grow.
        """
        self._lock = threading.Lock()
        #: What answering an exchange again changed, by (chat, exchange), until the
        #: turn doing it is over (`took_branch`).
        self._branched: dict = {}
        self._fold_into_one_conversation()
        self._move_the_chats_onto_the_object_model()

    # --- sessions -----------------------------------------------------------

    def ensure_session(self, session_id: str | None = None) -> str:
        """The chat a page that names none of its own opens on.

        `session_id` is ignored: a chat a page names is checked and taken by
        the socket's `hello`, and this is only the fallback: the chat the
        person opened last (:meth:`active_chat`).
        """
        return self.active_chat()

    def _fold_into_one_conversation(self) -> None:
        """Move everything that was ever said into the first chat. Once, ever.

        Nothing is dropped and nothing is reordered. `messages` is one table
        with one autoincrementing id, so its id order is the order the rows
        were written whatever session they were written under, and that is the
        order they are read back in - moving them all under one id leaves them
        in the order they were said, the phone's turns and the desktop's turns
        interleaved as they happened.

        Attachments are untouched on purpose: a stored file is found by the
        session id written into the marker beside it in the message, not by the
        conversation's id, so a picture sent from a browser that had its own id
        still opens from its own folder.

        **It runs once and is then marked done.** This used to run on every
        start, because there was one conversation and any other row was a
        leftover. There are chats now, and every one of them is a row in
        `sessions`: running this a second time would delete every chat the
        person had made and move its messages into the first one. The mark in
        `app_state` is what stops that, and it is why a database that has
        already been folded is left alone.
        """
        if self._state(FOLDED):
            return
        now = time.time()
        with self._lock, transaction.atomic():
            first = LegacySession.objects.aggregate(first=Min("created_at"))["first"] or now
            LegacySession.objects.bulk_create(
                [LegacySession(id=CONVERSATION, created_at=first, updated_at=now, title=None)],
                ignore_conflicts=True)
            moved = (TranscriptMessage.objects.exclude(session_id=CONVERSATION)
                     .update(session_id=CONVERSATION))
            # Every card drawn before there were chats belongs to the chat every
            # turn before there were chats belongs to, whether it was written
            # with a session id or without one. A card with no chat would show
            # on no canvas at all.
            (ScreenCard.objects.filter(Q(session_id__isnull=True) | ~Q(session_id=CONVERSATION))
             .update(session_id=CONVERSATION))
            folded, _ = LegacySession.objects.exclude(id=CONVERSATION).delete()
        self._set_state(FOLDED, "1")
        if folded:
            log.info("folded %d earlier session(s), %d message(s), into the first chat",
                     folded, moved)

    def _move_the_chats_onto_the_object_model(self) -> None:
        """Take every thread there is onto `objects.chat`. Once, ever.

        A chat was a row of `sessions` with a folder name written into it, and
        the thread called "30 Rouh" was the task `tasks/30.jarvis` because
        the two names happened to line up. This is the move off that, and it is
        the reason nothing the person can open breaks:

        - every thread becomes a chat row **with the id it already had**, so
          every turn already written against it, every attachment stored under
          it and every tab holding it still finds it;
        - its turns become that chat's own record, in the order they were said;
        - a thread that was matched to a numbered task is given to that task to
          own, which is the link that replaces the matching;
        - every other thread is loose, which is what most of them were: no
          number, no owner, and nothing written out to disk for it;
        - a chat folder becomes a project, and what was filed under one stays
          filed under it.

        The workspace is read first, so the tasks exist as rows before anything
        is handed to one (`conversations.reconcile`).

        It runs once and is then marked done, the way the fold above is. Run
        again it would do nothing anyway - every step of it asks whether the
        row is already there - but the mark says plainly that the move is
        behind us and makes the second start cost nothing.
        """
        if self._state(MOVED):
            return
        try:
            conversations.reconcile()
        except Exception:
            log.exception("the workspace could not be read while moving the chats")
        with self._lock:
            rows = list(LegacySession.objects.order_by("created_at").values(
                "id", "created_at", "updated_at", "title", "folder_id", "task", "unread"))
            folders = list(ChatFolder.objects.values("id", "name", "created_at"))
        for folder in folders:
            with contextlib.suppress(Exception):
                conversations.take_in_project(folder["id"], folder["name"],
                                              folder["created_at"])
        moved = turns = 0
        for row in rows:
            with self._lock:
                said = list(TranscriptMessage.objects
                            .filter(session_id=row["id"], live=True, note=False)
                            .order_by(_exchange(), "id").values("role", "content"))
            spoken: list[tuple[str, str]] = []
            for one in said:
                try:
                    words = _plain(json.loads(one["content"]))
                except (TypeError, ValueError):
                    words = ""
                if words and words != STOP_NOTE:
                    spoken.append((one["role"], words))
            try:
                conversations.take_in_chat(
                    row["id"], title=row["title"], created_at=row["created_at"],
                    last_spoke=row["updated_at"], unread=bool(row["unread"]),
                    # The one thread that is always there is loose and has to
                    # stay, so it is pinned rather than left to the clock.
                    pinned=row["id"] == CONVERSATION,
                    task=(row["task"] or ""), project_id=(row["folder_id"] or ""),
                    said=spoken)
            except Exception:
                log.exception("the thread %s could not be moved", row["id"])
                continue
            moved += 1
            turns += len(spoken)
        self._set_state(MOVED, "1")
        if moved:
            log.info("moved %d thread(s) and %d turn(s) onto the object model",
                     moved, turns)

    # --- chats ---------------------------------------------------------------
    #
    # One endless conversation is one context window, and a context window that
    # only grows is one that eventually has to be cut. So what the person says
    # is split into chats: each has its own history, its own title and its own
    # cards, and exactly one of them is active. The voice answers into the
    # active one, whichever device switched it, for the same reason there was
    # one conversation before - the phone and the desktop are the same person.
    #
    # **A chat is not a row here any more.** It is a row of `objects.chat`,
    # with the task that owns it and the project it is filed under, and
    # `rouh/conversations.py` is the whole of that. These methods are the
    # face the rest of Rouh already calls, kept exactly as it
    # was, so moving the conversations onto the object model changed one module
    # rather than twenty call sites. What is still this module's own is the
    # transcript: the blocks, the tool calls and the tries behind a question
    # that was asked four times, which a record of what was said has no
    # business holding.

    def _state(self, key: str) -> str:
        with self._lock:
            value = AppState.objects.filter(key=key).values_list("value", flat=True).first()
        return value if value is not None else ""

    def _set_state(self, key: str, value: str) -> None:
        with self._lock:
            # One statement, INSERT ... ON CONFLICT DO UPDATE, as it always was.
            AppState.objects.bulk_create(
                [AppState(key=key, value=value)], update_conflicts=True,
                unique_fields=["key"], update_fields=["value"])

    def active_chat(self) -> str:
        """The chat the person opened last, in any tab.

        Each tab is in a chat of its own (`runtime.switch_chat`), since 29
        September 2026, so this is no longer the chat every screen shows. It
        is where a tab that names no chat opens, and what code with no tab and
        no turn in hand falls back to.

        It answers with a chat that exists, or with a draft of one: a task
        opened and not yet talked about, or New chat pressed and nothing said
        yet (`conversations.open_draft`). A pointer at a chat that has been
        deleted, and a first run with nothing in the database at all, both come
        back as the first chat, which is made here if it is not there.
        """
        wanted = self._state(ACTIVE_CHAT)
        if wanted and (conversations.chat(wanted) is not None
                       or conversations.draft(wanted) is not None):
            return wanted
        self.ensure_general()
        self._set_state(ACTIVE_CHAT, CONVERSATION)
        return CONVERSATION

    def set_active_chat(self, chat_id: str) -> str:
        """Make this the chat everything said next belongs to.

        A chat that is not there leaves the active one where it was: a stale
        button in a tab that has been open for a day must not be able to move
        the person into a conversation that does not exist. A draft is let in,
        because a draft is exactly a conversation the person is in before it is
        written down.
        """
        if conversations.chat(chat_id) is None:
            if conversations.draft(chat_id) is None:
                return self.active_chat()
            self._set_state(ACTIVE_CHAT, chat_id)
            return chat_id
        self._set_state(ACTIVE_CHAT, chat_id)
        # Opening a thread is reading it, so the dot in the rail goes.
        self.mark_unread(chat_id, False)
        return chat_id

    def mark_unread(self, chat_id: str, unread: bool = True) -> None:
        """Say whether this thread has something in it nobody has seen yet.

        Set when a turn finishes in a thread that is not the one on screen: a
        turn belongs to the thread it was asked in and runs to the end whatever
        the person went off to look at, so its answer can land somewhere nobody
        is looking. Cleared by `set_active_chat`, which is the only way a
        thread gets looked at.

        Deliberately a flag and not a count. The question it answers is "is
        there anything new in here", which is the question a dot in a list
        answers; a number invites a badge, and a badge invites being cleared by
        something other than reading it.
        """
        conversations.mark_unread(chat_id, unread)

    def new_chat(self, title: str | None = None, folder_id: str | None = None) -> str:
        """An empty chat, made active, and its id.

        Loose, because that is the only thing a new conversation can be: no
        number, no owner and no folder on disk until something says otherwise.
        Most chats are one question and stay that way, and a new numbered task
        for each of them is exactly the pollution this model exists to stop.

        The id is random rather than counted: it becomes a directory name for
        anything attached in it (`attachments.py`), and it is in the open in a
        page's markup, so it says nothing about how many chats there are.
        """
        chat_id = conversations.new_chat(title, folder_id or None)
        self._set_state(ACTIVE_CHAT, chat_id)
        return chat_id

    def draft_chat(self, folder_id: str | None = None) -> str:
        """A new chat to talk in, made active, and not written down yet.

        What New chat is, since 23 September 2026: the person is put in a
        conversation of their own at once, and the row is written by the first
        thing said in it (`conversations.make`). Pressing New chat and walking
        away leaves nothing behind, where it used to leave an empty chat at the
        top of the list. `folder_id` is the project it was started in, from a
        project's own page, and is where the chat goes once it is made.

        `new_chat` above is still the one that writes a row at once, for a
        branch, which carries its messages with it from the start.
        """
        chat_id = conversations.open_draft(project_id=folder_id or "")
        self._set_state(ACTIVE_CHAT, chat_id)
        return chat_id

    def chat(self, chat_id: str) -> dict | None:
        """One chat, with its message count and what it was last called.

        Or a draft of one, marked `draft`, which is what the page is standing in
        until something is said there. Nothing may write to what this hands
        back for a draft: there is no row under it yet.
        """
        return conversations.chat(chat_id) or conversations.draft_row(chat_id)

    def chats(self) -> list[dict]:
        """Every chat, the one with the newest activity first.

        Newest first because that is the order they are looked for in: the chat
        somebody was in a minute ago is the one they want back, and the one
        from last month is the one they are willing to scroll for.
        """
        return conversations.all_chats()

    def rename_chat(self, chat_id: str, title: str) -> dict | None:
        """Give a chat a title, by hand or from the model.

        Every title starts with an emoji, the person's own as much as the
        model's: the list is scanned rather than read, and the picture is what
        the eye lands on before any of the words (`chats.ensure_emoji`).
        Somebody who wants a particular one types it and it is kept.

        An empty title puts the chat back to untitled, which is also what puts
        it back in the way of the automatic one.
        """
        return conversations.rename(chat_id, title)

    def pin_chat(self, chat_id: str, on: bool = True) -> dict | None:
        """Mark this conversation as one to keep in view, or take the mark off.

        What a person does to a loose chat to say "this one matters". It is a
        mark and nothing more: no chat is archived or deleted on a clock, so
        there is nothing for it to be kept from.
        """
        return conversations.pin(chat_id, on)

    # --- a chat that is a workspace task -------------------------------------
    #
    # A thread whose subject is a numbered task of the person's workspace is
    # that task. Not a chat about it and not a copy of it: one object, so there
    # is nothing for the two to drift apart about.
    #
    # What says so is a row in the link table - the task owns the chat - and
    # not, as it was until 21 September 2026, a folder name written into the
    # chat and matched against the workspace. That matching is deleted. The
    # three methods below all ask the link.

    def promote_chat(self, chat_id: str, *, title: str = "",
                     project: str = "") -> dict | None:
        """Make a loose chat a numbered task, and hand back the task.

        It takes the next free number, keeps every message it already has -
        it is the same chat, nothing is copied - and carries what it owns with
        it. A chat that is already a task is handed back its own. `project` is
        the id of the project the person said it belongs in, which it is then
        made inside.
        """
        return conversations.promote(chat_id, title=title, project=project)

    def task_of(self, chat_id: str) -> str:
        """Which workspace task a chat is, as its folder, or an empty string."""
        return conversations.folder_of(chat_id)

    def ensure_general(self) -> str:
        """The thread that is always there, and its id.

        Notifications, job results, loose talk, anything with no home yet. It
        exists so the person is never made to file something before they can
        say it, and it is the one conversation everything was folded into on
        16 September, so a year of history is in it.

        General is a *role* rather than a name written into the row. The rail
        calls this thread General because of which thread it is, and the chat
        keeps its own title, which the model still writes from what is said in
        it. Writing the name into the row was tried first and was wrong: it
        stops the automatic naming reaching this chat at all, and the automatic
        naming is not this feature's to take away.

        It is marked as kept, because it is the one thread that is always
        there and the rail says so.
        """
        conversations.ensure_chat(CONVERSATION, pinned=True)
        return CONVERSATION

    def move_chat(self, chat_id: str, folder_id: str | None) -> dict | None:
        """Into a project, or out of every project when `folder_id` is empty."""
        return conversations.set_project(chat_id, folder_id or None)

    # --- projects ------------------------------------------------------------
    #
    # A project is the thing that holds chats together, and it is a row of
    # `objects.project` which owns whatever is filed under it. The wire still
    # says `folder`, which is what these methods are still called: that is a
    # wire and not an interface, and renaming it would move rows for nothing.

    def folders(self) -> list[dict]:
        """Every project, by name. Alphabetical, because a project is looked
        for by what it is called and not by when it was made."""
        return conversations.projects()

    def folder(self, folder_id: str) -> dict | None:
        return conversations.project(folder_id)

    def new_folder(self, name: str, owner_id: str = "") -> dict:
        """A project, on its own or inside another project.

        A project may own a project, so one can be made where it belongs
        rather than made loose and moved afterwards.
        """
        return conversations.new_project(name, owner_id=owner_id or None)

    def rename_folder(self, folder_id: str, name: str) -> dict | None:
        return conversations.rename_project(folder_id, name)

    # Deleting a chat or a project is not here and must not come back here.
    # There is one delete for all five types, it cascades, and it is
    # `owning.remove`: a chat deleted through a second path would take its
    # messages and leave its cards, its runs and its steps in the database
    # with nothing above them, and a project deleted through a second one
    # would walk the tree a second way and get a different amount of it right.
    # What is still this module's is `forget_chat` below, the model's own
    # tape, which the one path calls once the rows have gone.

    def add_message(self, session_id: str, role: str, content, spoken: bool = False,
                    *, root: int | None = None, version: int = 1,
                    supersede: bool = False, note: bool = False,
                    notice: bool = False) -> int:
        """Write one turn down, and say which row it became.

        The id is what a card drawn during that turn is filed against, so the
        transcript can put the two back in the order they happened. See
        :meth:`add_card`.

        `root` and `version` are the exchange this row belongs to and the try
        it is part of. Left alone, the row is its own exchange, first try,
        which is every row written by a question asked for the first time.

        `supersede` is the one moment a version takes over: the question of a
        retry is written with it, and in the same breath every other version of
        that exchange stops being live. Both in one transaction on purpose - an
        exchange with no live version at all, even for an instant, is a
        question that has vanished from the conversation.

        `note` is a `user` row that Rouh's own software wrote rather than the
        person: a finished job's report, a run's question, a press on a card
        (`runtime.announce`). The model reads it like any other; the page is
        never sent it and the chat's own record never holds it, because
        whatever is drawn under the person's name has to be something they
        said (feedback fr_2f27e92125ba).

        `notice` is the other way round: an `assistant` row that is a notice's
        words, kept in the chat the notice leads to (`add_notice`). The page
        draws it; the model is never sent it (`_window`).

        A draft becomes a chat here if nothing has made it one yet. A turn has
        already done it on the way in (`Turns.start`); this is the same doorway
        for anything that writes a turn by another road, so no turn is ever
        written against an id with no chat behind it.
        """
        conversations.make(session_id)
        new_id = self._write_transcript_message(
            session_id, role, content, spoken, root=root, version=version,
            supersede=supersede, note=note, notice=notice)
        self._record_chat_turn(session_id, role, content, note=note)
        return new_id

    def _write_transcript_message(self, session_id: str, role: str, content,
                                   spoken: bool, *, root: int | None,
                                   version: int, supersede: bool, note: bool,
                                   notice: bool) -> int:
        """Keep the message and its live version under one lock and transaction."""
        with self._lock, transaction.atomic():
            follows = None
            again = bool(supersede and root is not None)
            if again:
                # A later try of an exchange comes off where the try it replaces
                # did, and is a branch of the conversation from there: whatever was
                # said after the old try stays on the old branch (`_relive`).
                self._materialize(session_id)
                follows = self._follows_of(root)
                TranscriptMessage.objects.filter(_in_exchange(root)).exclude(
                    version=version).update(picked=False)
            elif root is None and not notice:
                # A new exchange follows whatever the conversation being read
                # ends on now. A notice follows nothing and is on every branch.
                follows = self._tail(session_id)
            made = TranscriptMessage.objects.create(
                session_id=session_id, ts=time.time(), role=role,
                content=json.dumps(content), spoken=bool(spoken), root=root,
                version=int(version), live=True, note=bool(note), notice=bool(notice),
                follows=follows, picked=True)
            new_id = int(made.id)
            if root is None:
                # Its own exchange: the row that began it is the root. Written
                # rather than left null so that a later try of this exchange
                # has something to point at.
                TranscriptMessage.objects.filter(id=new_id).update(root=new_id)
            if again:
                changed = self._relive(session_id)
                # Whether anything but this exchange came on or off the screen,
                # and which tries did: what the page is told once the turn is
                # over (`branched`), so it draws the branch it is on.
                self._branched[(session_id, int(root))] = changed
        return new_id

    # --- branches ------------------------------------------------------------
    #
    # Petar, 4 November 2026: "I wanted a second answer by pressing the smart
    # model. but it kept the message below instead of forking the conversation
    # from that point on." An exchange answered again - retry, Smart or Cheaper,
    # an edited question - is a branch of the conversation at that point. Each
    # try's first row says which try of the exchange before it it was asked
    # after (`follows`), so the conversation is a tree of tries, and the one
    # being read is the path through it that the person's choices pick
    # (`picked`): `live` is that path, kept on the rows so that every reader of
    # the conversation - the model's window, the page, search - reads it
    # without knowing there is a tree at all. Nothing is ever deleted: going
    # back to the first answer with the arrows under it brings back everything
    # that followed it.

    def _tries(self, session_id: str) -> list[list[dict]]:
        """This chat's exchanges in the order of the conversation, each a list of its
        tries: their rows, their first row, what the first row follows and whether it
        was the try picked. Under the caller's lock."""
        rows = (TranscriptMessage.objects.filter(session_id=session_id)
                .annotate(exchange=_exchange())
                .values("id", "exchange", "version", "follows", "picked", "live", "notice")
                .order_by("exchange", "id"))
        out: list[list[dict]] = []
        at: dict[tuple, dict] = {}
        last = None
        for r in rows:
            key = (int(r["exchange"]), int(r["version"]))
            if r["exchange"] != last:
                out.append([])
                last = r["exchange"]
            node = at.get(key)
            if node is None:
                node = {"key": key, "first": int(r["id"]), "follows": r["follows"],
                        "picked": bool(r["picked"]), "notice": bool(r["notice"]), "rows": []}
                at[key] = node
                out[-1].append(node)
            node["rows"].append((int(r["id"]), bool(r["live"])))
        return out

    @staticmethod
    def _chosen(tries: list[dict], seen: set) -> dict | None:
        """Which try of one exchange is on the branch being read: of the tries asked
        after something on it (or after nothing written down, which is every row
        from before branches), the one picked, else the newest of them."""
        fits = [t for t in tries if t["follows"] is None or t["follows"] in seen]
        if not fits:
            return None
        return next((t for t in reversed(fits) if t["picked"]), fits[-1])

    def _relive(self, session_id: str) -> set:
        """Put `live` on the rows of the branch being read and take it off every
        other, and say which tries changed. Under the caller's lock and transaction."""
        seen: set = set()
        on, off, changed = [], [], set()
        for tries in self._tries(session_id):
            chosen = self._chosen(tries, seen)
            for t in tries:
                want = t is chosen
                moved = [i for i, live in t["rows"] if live != want]
                if moved:
                    changed.add(t["key"])
                    (on if want else off).extend(moved)
            if chosen is not None and not chosen["notice"]:
                seen.add(chosen["first"])
        if on:
            TranscriptMessage.objects.filter(id__in=on).update(live=True)
        if off:
            TranscriptMessage.objects.filter(id__in=off).update(live=False)
        return changed

    def _materialize(self, session_id: str) -> None:
        """Write down what each try follows where nothing says it yet, which is a
        chat from before branches: the line it was read as. Done the first time one
        of its exchanges is answered again, so the branch starts from the line on the
        screen. Under the caller's lock and transaction."""
        seen: set = set()
        tail = None
        fill: dict = {}
        for tries in self._tries(session_id):
            for t in tries:
                if t["follows"] is None and not t["notice"] and tail is not None:
                    t["follows"] = tail
                    fill.setdefault(tail, []).append(t["first"])
            chosen = self._chosen(tries, seen)
            if chosen is not None and not chosen["notice"]:
                seen.add(chosen["first"])
                tail = chosen["first"]
        for follows, firsts in fill.items():
            TranscriptMessage.objects.filter(id__in=firsts).update(follows=follows)

    def _tail(self, session_id: str) -> int | None:
        """The first row of the try the conversation being read ends on: what a new
        exchange follows. Notices are on every branch and are never followed."""
        last = (TranscriptMessage.objects.filter(session_id=session_id, live=True, notice=False)
                .annotate(exchange=_exchange()).order_by("-exchange", "-id")
                .values("exchange", "version").first())
        if last is None:
            return None
        return (TranscriptMessage.objects.filter(_in_exchange(last["exchange"]),
                                                 version=last["version"])
                .aggregate(first=Min("id"))["first"])

    def _follows_of(self, root: int):
        """What the try of an exchange being answered again follows: what the try it
        replaces did, the one picked, so the new one is its sibling."""
        rows = TranscriptMessage.objects.filter(_in_exchange(root))
        row = (rows.order_by("-picked", "-live", "id").values("follows").first())
        return row["follows"] if row else None

    def current_try(self, session_id: str) -> int | None:
        """The first row of the try of the exchange a chat's conversation ends on: the
        one a turn running in it is writing, once its question is written down."""
        if not session_id:
            return None
        with self._lock:
            return self._tail(session_id)

    def took_branch(self, session_id: str, root: int) -> set | None:
        """Which tries came on or off the screen when this exchange was last answered
        again, once: None when nothing has been written since it was asked about."""
        return self._branched.pop((session_id, int(root)), None)

    def tries_of(self, session_id: str, keys) -> list[int]:
        """The first row of each of these tries, by (exchange, version)."""
        keys = list(keys or [])
        if not keys:
            return []
        q = Q()
        for ex, version in keys:
            q |= (_in_exchange(int(ex)) & Q(version=int(version)))
        with self._lock:
            got = (TranscriptMessage.objects.filter(q, session_id=session_id)
                   .annotate(exchange=_exchange()).values("exchange", "version")
                   .annotate(first=Min("id")))
            return [int(g["first"]) for g in got]

    def _record_chat_turn(self, session_id: str, role: str, content, *, note: bool) -> None:
        """Keep the spoken words after the transcript transaction has finished."""
        # The same turn into the chat's own record, which is what travels with
        # the chat and goes when it goes (`conversations.add_turn`). One call
        # writes both, so the record cannot drift from the transcript; what is
        # here and not there is everything a record has no business holding -
        # the tool calls, their results, the tries behind a question that was
        # asked four times, and Rouh's own notes, which nobody said.
        said = "" if note else _words(role, content)
        conversations.add_turn(session_id, role, "" if said == STOP_NOTE else said)

    def add_askai(self, session_id: str, doc: str, title: str, question: str,
                  passage: str, answer: str) -> list[dict]:
        """One Ask AI exchange, written into a chat as a question and its answer.

        One exchange: the answer's row belongs to the question's, the way every
        turn's answer does. Handed back as the page draws the two rows, for the
        tabs standing in that chat (`runtime.askai_said`).
        """
        asked = [{"type": "text", "text": _askai_head(doc, title)}]
        if passage:
            asked.append({"type": "text", "text": f"{ASKAI_PASSAGE}\n{passage}]"})
        asked.append({"type": "text", "text": question})
        first = self.add_message(session_id, "user", asked)
        second = self.add_message(session_id, "assistant", [{"type": "text", "text": answer}],
                                  root=first)
        with self._lock:
            rows = _drawn(TranscriptMessage.objects.filter(session_id=session_id,
                                                           id__in=(first, second))
                          .order_by("id"))
        out: list[dict] = []
        for r in rows:
            said = self._said(r)
            if said is not None:
                _askai_answer(out[-1] if out else None, said)
                out.append(said)
        return out

    # --- asking the same thing again ----------------------------------------
    #
    # Re-asking used to mean sending the same words a second time, which left
    # the conversation holding two identical questions one above the other and
    # the answer to the first still in between them. An exchange is now a thing
    # with tries: the new answer takes the old one's place, the old one is kept,
    # and the arrows under the message step between them.

    def adopt(self, session_id: str, message_id: int) -> int | None:
        """Give an exchange written before there were exchanges a root.

        Everything from `message_id` up to the next question is one exchange,
        and this is what says so, once, the first time somebody retries one of
        them. The walk forward stops at the next row that begins a question of
        its own: a `user` row that is not a tool result and is not the note
        written when a turn is stopped.

        Returns the root, or None when there is no such message in this chat.
        """
        message_id = _row_id(message_id)
        if message_id is None:
            return None
        with self._lock, transaction.atomic():
            row = (TranscriptMessage.objects.filter(id=message_id, session_id=session_id)
                   .values("id", "role", "root").first())
            if row is None or row["role"] != "user":
                return None
            if row["root"] is not None:
                return int(row["root"])
            after = (TranscriptMessage.objects
                     .filter(session_id=session_id, id__gte=message_id)
                     .order_by("id").values("id", "role", "content", "root"))
            mine = []
            for i, r in enumerate(after):
                if r["root"] is not None:
                    break
                if i and _begins_a_question(r["role"], r["content"]):
                    break
                mine.append(int(r["id"]))
            TranscriptMessage.objects.filter(id__in=mine).update(
                root=message_id, version=1, live=True)
        return int(message_id)

    def _question_row(self, session_id: str, message_id: int) -> int | None:
        """Which question begins the exchange this message is part of.

        A message written since exchanges existed carries its root and says so
        outright. One written before them does not, and the answer is found by
        walking back to the nearest thing the person actually asked - which is
        what the retry button on an old reply needs, because the id it sends is
        the reply's own.
        """
        message_id = _row_id(message_id)
        if message_id is None:
            return None
        with self._lock:
            row = (TranscriptMessage.objects.filter(id=message_id, session_id=session_id)
                   .values("id", "role", "content", "root").first())
            if row is None:
                return None
            if row["root"] is not None:
                return int(row["root"])
            if _begins_a_question(row["role"], row["content"]):
                return int(row["id"])
            back = list(TranscriptMessage.objects
                        .filter(session_id=session_id, id__lt=message_id)
                        .order_by("-id").values("id", "role", "content", "root"))
        for r in back:
            if r["root"] is not None:
                return int(r["root"])
            if _begins_a_question(r["role"], r["content"]):
                return int(r["id"])
        return None

    def _question_of(self, root: int, version: int | None = None):
        """The words an exchange was asked with, as they were stored, and
        whether they were a note of Rouh's own rather than the person's
        (`add_message`)."""
        with self._lock:
            rows = TranscriptMessage.objects.filter(_in_exchange(root))
            rows = rows.filter(live=True) if version is None else rows.filter(version=version)
            row = rows.order_by("id").values("content", "note").first()
        if row is None:
            return None, False
        return json.loads(row["content"]), bool(row["note"])

    def another_try(self, session_id: str, message_id: int,
                    text: str | None = None) -> dict | None:
        """Get an exchange ready to be answered again, and say how to do it.

        `message_id` is any message of the exchange - the question itself, or
        the answer under it, which is what the retry button on Rouh's own
        reply sends. `text` is the person's edited wording, or None to ask the
        same thing again.

        Nothing is superseded here: the old version stays live until the new
        question is actually written down, so a retry that is cancelled before
        the model answers leaves the conversation exactly as it was.

        Returns `{"root", "version", "content", "note"}`, or None when there is
        no such exchange. `note` is an answer to one of Rouh's own notes being
        asked for again, whose question is that note again and still not the
        person's words.
        """
        root = self._question_row(session_id, message_id)
        if root is None:
            return None
        with self._lock:
            # A notice kept in the chat was asked by nobody (`add_notice`).
            if TranscriptMessage.objects.filter(id=root, notice=True).exists():
                return None
        if self.adopt(session_id, root) is None:
            return None
        with self._lock:
            top = (TranscriptMessage.objects.filter(_in_exchange(root))
                   .aggregate(v=Max("version"))["v"])
        version = int(top or 1) + 1
        was, note = self._question_of(root)
        if text is None:
            if was is None:
                return None
            content = was
        elif isinstance(was, list) and any(
                isinstance(b, dict) and b.get("type") != "text" for b in was):
            # The words change; what they attached does not. A question edited
            # into one that had lost the screenshot it was asked about would be
            # a different question, about nothing.
            kept = [b for b in was if not (isinstance(b, dict) and b.get("type") == "text")]
            content = kept + [{"type": "text", "text": text}]
        else:
            content = text
        return {"root": root, "version": version, "content": content,
                "note": note and text is None}

    def fork_point(self, session_id: str, message_id: int) -> dict | None:
        """Where a fork taken from a message being edited comes off, and its files.

        Fork on the box a message is edited in asks the new words in a fork
        rather than here (`rouh/forks.py`). As with an edit asked again in
        place (`another_try`), the words change and the files do not: `root`
        is the exchange the fork comes off just above, `files` the ids of what
        the question was asked with, and `uploaded_in` the chat they are kept
        under. None when there is no such message in this chat.
        """
        root = self._question_row(session_id, message_id)
        if root is None:
            return None
        was, _note = self._question_of(root)
        marks = attachments.markers_in(was)
        return {"root": root, "files": [m["id"] for m in marks if m.get("id")],
                "uploaded_in": next((m["session_id"] for m in marks if m.get("session_id")), "")}

    def versions(self, root: int) -> list[dict]:
        """Every try of this exchange, oldest first: its number and its question."""
        root = _row_id(root)
        if root is None:
            return []
        with self._lock:
            # One row per try: its number, the first row it wrote (which is the
            # question it was asked with), and whether any of it is live.
            rows = list(TranscriptMessage.objects.filter(_in_exchange(root))
                        .values("version").annotate(first=Min("id"), live=BoolOr("live"))
                        .order_by("version"))
            asked = {}
            for r in rows:
                one = (TranscriptMessage.objects.filter(id=r["first"])
                       .values_list("content", flat=True).first())
                asked[int(r["version"])] = _plain(json.loads(one)) if one is not None else ""
        return [{"version": int(r["version"]), "ask": asked[int(r["version"])],
                 "live": bool(r["live"])} for r in rows]

    def exchange(self, root: int) -> dict:
        """What the arrows under a message have to say: which try, of how many.

        `edited` is true when the tries were not all asked with the same words,
        which is the difference between retrying an answer and rewriting the
        question. The page draws the counter under the question only when it is
        true, because a counter under words that never changed says nothing.
        """
        tries = self.versions(root)
        live = next((t["version"] for t in tries if t["live"]), 1)
        asks = {t["ask"] for t in tries}
        return {"root": int(root), "version": live, "versions": len(tries),
                "edited": len(asks) > 1}

    def pick_version(self, session_id: str, root: int, version: int) -> dict | None:
        """Step the conversation to one of an exchange's tries.

        What this changes is the conversation itself, not just the picture of
        it: the version chosen is what the page draws and what the model is
        sent from here on. Nothing is deleted either way.
        """
        root, version = _row_id(root), _row_id(version)
        if root is None or version is None:
            return None
        with self._lock, transaction.atomic():
            has = TranscriptMessage.objects.filter(
                _in_exchange(root), session_id=session_id, version=version).exists()
            if not has:
                return None
            # The try chosen, and with it the branch it is on: what followed that
            # try, the last time it was the one being read, comes back with it.
            self._materialize(session_id)
            TranscriptMessage.objects.filter(_in_exchange(root)).update(
                picked=Case(When(version=int(version), then=Value(True)), default=Value(False)))
            changed = self._relive(session_id)
        out = self.exchange(root)
        out["messages"] = self.exchange_transcript(session_id, root)
        # Whether anything but this exchange came on or off the screen, which the
        # page answers by drawing the conversation again rather than one exchange.
        out["branched"] = any(key[0] != int(root) for key in changed)
        out["changed"] = sorted(changed)
        return out

    def exchange_transcript(self, session_id: str, root: int) -> list[dict]:
        """The live rows of one exchange, drawn the way the transcript is."""
        with self._lock:
            rows = _drawn(TranscriptMessage.objects
                          .filter(_in_exchange(root), session_id=session_id, live=True)
                          .order_by("id"))
        return self._told(session_id, rows)

    # --- the lines tool calls drew (fr_3f1814427840) --------------------------
    #
    # "I would like in chat when I see the tool usage to also be saved in chat
    # history. Currently after refresh we no longer see old tool usage." Petar,
    # 30 September 2026. The lines were never kept: they were drawn from the
    # messages a turn sends the page and from nothing else, so a chat read back
    # was its words alone. What those messages said is kept now, as they went
    # past (`runtime.Turn.emit`), and the page is handed each line in the place
    # it had among the words.

    def add_notice(self, session_id: str, text: str) -> int | None:
        """Keep a notice's words in the chat it leads to, as one of Rouh's messages.

        Petar, 12 October 2026 (fr_c8fb46a5a132): "when a run completes and
        the notification pops, the is a link go to chat. And I go there but
        there is no message. That same content in the notification needs to be
        posted in the chat for permanence. Otherwise notifications disappear
        and I can never reread then". A notice is dismissed the moment it is
        followed, so the chat it opens is where its words stay.

        Its own exchange, so it is drawn after whatever turn is being answered
        in that chat as it is written, and never inside one. Not sent to the
        model, which was handed the same words in the note its report turn
        answered: twice would be a whole report said again in every request.
        Nor answered again, edited or forked from, because nobody asked it.
        The row's id, or None when there was nothing to keep.
        """
        text = str(text or "").strip()
        if not session_id or not text:
            return None
        return self.add_message(session_id, "assistant", [{"type": "text", "text": text}],
                                notice=True)

    def note_tool(self, session_id: str, message: dict) -> None:
        """Keep what one `tool_start`, `tool_update` or `tool_end` told the page.

        Only what the page draws the line from, and read as the page reads it
        (`onToolStart`, `onToolUpdate`, `onToolEnd` in app.js), so the line read
        back is the line that was on the screen. Never raises: a line that
        could not be kept must not end the turn it belongs to.
        """
        kind = message.get("type")
        call = str(message.get("id") or message.get("name") or "")
        if not session_id or not call:
            return
        try:
            with self._lock:
                if kind == "tool_start":
                    # Never on a notice kept in the chat (`add_notice`): it is
                    # nobody's answer, and a line drawn under it would be lost.
                    after = (TranscriptMessage.objects.filter(session_id=session_id, live=True,
                                                              notice=False)
                             .aggregate(last=Max("id"))["last"])
                    ToolLine.objects.create(
                        session_id=session_id, call_id=call, after_message_id=after,
                        ts=time.time(), name=str(message.get("name") or ""),
                        input=_input_text(message.get("input")))
                    return
                line = (ToolLine.objects.filter(session_id=session_id, call_id=call)
                        .order_by("-id").first())
                if line is None:
                    return
                if kind == "tool_update":
                    if message.get("input") is None:
                        return
                    line.input = _input_text(message.get("input"))
                    if message.get("name"):
                        line.name = str(message["name"])
                elif kind == "tool_end":
                    results = message.get("results")
                    line.done = True
                    line.ok = message.get("ok") is not False
                    line.summary = str(message.get("summary") or "")
                    line.results = results if isinstance(results, list) else []
                    output = message.get("output")
                    line.output = None if output is None else str(output)
                else:
                    return
                line.save()
        except Exception:
            log.warning("a tool line of %s could not be kept", session_id, exc_info=True)

    def _told(self, session_id: str, rows: list[dict]) -> list[dict]:
        """Rows as the page draws them, each answer with the tool lines it drew.

        A line goes in the answer whose row holds its call, among the words
        where the call was: an answer written either side of a search has the
        search between its two paragraphs. A line no row names - a helper's
        call, made inside one of Rouh's own - goes with the row that was the
        newest when it started, after that row's own calls. An answer that
        called tools and said nothing is drawn too, as its lines, which is
        what was on the screen. A chat from before the lines were kept has
        none, and reads back as it always did.
        """
        answers = {int(r["id"]): json.loads(r["content"]) for r in rows
                   if r["role"] == "assistant" and not r.get("note") and not r.get("notice")}
        calls = {cid: rid for rid, blocks in answers.items() for cid in _call_ids(blocks)}
        root_of = {int(r["id"]): r.get("root") for r in rows}
        lines: list[dict] = []
        if answers:
            with self._lock:
                lines = list(ToolLine.objects
                             .filter(Q(call_id__in=list(calls))
                                     | Q(after_message_id__gte=min(root_of),
                                         after_message_id__lte=max(answers)),
                                     session_id=session_id)
                             .order_by("id").values())
        by_call = {line["call_id"]: line for line in lines if line["call_id"] in calls}
        loose_first, loose_last = self._place_transcript_tool_lines(answers, calls, root_of, lines)
        out = self._draw_transcript_messages(rows, answers, lines, by_call, loose_first, loose_last)
        self._add_recall_to_transcript(session_id, out)
        self._add_routes_to_transcript(session_id, out)
        return out

    @staticmethod
    def _place_transcript_tool_lines(answers: dict, calls: dict, root_of: dict,
                                     lines: list[dict]) -> tuple[dict, dict]:
        """Place calls without a named block before or after their answer."""
        # The lines no block names, by the answer they are drawn in: the one
        # that was newest when they started, or, when that was not an answer,
        # the next answer of the same exchange. One whose turn wrote no answer
        # at all is drawn nowhere, rather than in the next exchange's.
        order = sorted(answers)
        # The rows that are the last of their exchange, with a later exchange
        # after them: a line started after one of those is the next one's.
        newest: dict = {}
        for rid in sorted(root_of):
            newest[root_of[rid]] = rid
        ended = {rid for rid in newest.values() if rid < max(root_of)}
        loose_first: dict[int, list] = {}
        loose_last: dict[int, list] = {}
        for line in lines:
            after = line["after_message_id"]
            if line["call_id"] in calls or after not in root_of:
                continue
            if after in answers and after in ended:
                # Newest when it started was the answer that ended its
                # exchange, so nothing of that answer's ran it: it is the next
                # question's, started before that question was written down,
                # which is how a search run ahead of any words was kept until
                # 30 September 2026 (fr_f8a1bebc7237). It goes at the top of
                # the next exchange's answer, under the question, as live.
                owner = next((rid for rid in order
                              if rid > after and root_of[rid] != root_of[after]), None)
                if owner is not None:
                    loose_first.setdefault(owner, []).append(line)
                continue
            if after in answers:
                loose_last.setdefault(after, []).append(line)
                continue
            owner = next((rid for rid in order
                          if rid > after and root_of[rid] == root_of[after]), None)
            if owner is not None:
                loose_first.setdefault(owner, []).append(line)
        return loose_first, loose_last

    def _draw_transcript_messages(self, rows: list[dict], answers: dict, lines: list[dict],
                                  by_call: dict, loose_first: dict, loose_last: dict) -> list[dict]:
        """Draw visible messages with their tool parts and steering marks."""
        out = []
        # The exchanges whose question has gone past. A message of the person's
        # after it, in the same exchange, is one they sent while the answer was
        # being written and the model read part way through it
        # (`brain.Brain._take_steer`): drawn as theirs, where it was read, and
        # never offered to be asked again or edited as though it were the
        # question.
        asked: set = set()
        for r in rows:
            said = self._said(r)
            if r["role"] == "user":
                if (said is not None and r.get("root") in asked
                        and not said.get("stopped")):
                    said["steered"] = True
                asked.add(r.get("root"))
            blocks = answers.get(int(r["id"]))
            if blocks is not None and lines:
                parts = _parts(blocks, by_call, loose_first.get(int(r["id"]), []),
                               loose_last.get(int(r["id"]), []))
                if parts is not None:
                    if said is None:
                        said = {"id": r["id"], "ts": r["ts"], "role": r["role"], "text": "",
                                "root": int(r["root"]) if r.get("root") is not None else None}
                    said["parts"] = parts
            if said is not None:
                out.append(said)
        return out

    def _add_recall_to_transcript(self, session_id: str, out: list[dict]) -> None:
        """Attach the kept look-up timeline to each visible user message."""
        # Under each of the person's messages, what Master's look-ups did for it (`rouh/recalling.py`).
        mine = [int(row["id"]) for row in out if row.get("role") == "user"]
        if mine:
            with self._lock:
                drawn = dict(RecallTimeline.objects.filter(session_id=session_id, message_id__in=mine)
                             .values_list("message_id", "data"))
            for row in out:
                if row.get("role") == "user" and int(row["id"]) in drawn:
                    row["recall"] = drawn[int(row["id"])]

    def _add_routes_to_transcript(self, session_id: str, out: list[dict]) -> None:
        """Attach each answer's model decision, including older decisions."""
        # Under each answer, how its model was decided (`rouh/modelrouter.py`, the "Model decision" line).
        theirs = {row.get("root") for row in out if row.get("role") == "assistant"} - {None}
        if theirs:
            routes: dict = {}
            # Each try of an exchange keeps its own decision, by `version` (a tier
            # pressed for a redo, 21 October 2026); one from before that, the newest.
            tries: dict = {}
            live: dict = {}
            try:
                with self._lock:
                    live = dict(TranscriptMessage.objects.filter(
                        session_id=session_id, id__in=[int(row["id"]) for row in out
                                                       if row.get("role") == "assistant"])
                        .values_list("id", "version"))
                    kept = list(RouteTimeline.objects.filter(session_id=session_id, root__in=list(theirs))
                                .order_by("ts").values("call", "root", "data"))
                    # Each turn's timeline is its record's (`rouh/turnrecords.py`); a fork's copy of the
                    # line is named after the turn it copied (`call@chat`). Older lines carry their own.
                    traces = turnrecords.traces_of(r["call"] for r in kept)
                    for r in kept:
                        data = r["data"] if isinstance(r["data"], dict) else {}
                        trace = traces.get(str(r["call"]).split("@", 1)[0])
                        if trace and not data.get("trace"):
                            data = dict(data, trace=trace)
                        routes[int(r["root"])] = data
                        if data.get("version") is not None:
                            tries[(int(r["root"]), int(data["version"]))] = data
            except Exception:
                log.warning("how the models in %s were decided could not be read", session_id, exc_info=True)
            if theirs - set(routes):
                # Answers from before the line was kept (21 October 2026): what Auto wrote down.
                from . import modeloutcomes

                try:
                    for root, said in modeloutcomes.routes_of(session_id, theirs - set(routes)).items():
                        routes.setdefault(root, said)
                except Exception:
                    log.warning("what Auto decided in %s could not be read", session_id, exc_info=True)
            for row in out:
                if row.get("role") == "assistant" and row.get("root") in routes:
                    row["route"] = tries.get((row["root"], live.get(int(row["id"])) or 1),
                                             routes[row["root"]])

    def note_recall(self, message_id: int, session_id: str, data: dict) -> None:
        """Keep a message's recall timeline with it (`recalling.MessageMemory.publish`), the newest whole."""
        with self._lock:
            RecallTimeline.objects.update_or_create(
                message_id=int(message_id),
                defaults={"session_id": session_id, "ts": time.time(), "data": data})

    def note_route(self, call: str, session_id: str, data: dict, root: int | None = None) -> None:
        """Keep how a turn's model was decided with it (`modelrouter.timeline`), and its exchange once known."""
        with self._lock:
            defaults = {"session_id": session_id, "ts": time.time(), "data": data}
            if root is not None:
                defaults["root"] = int(root)
            RouteTimeline.objects.update_or_create(call=call, defaults=defaults)

    def history(self, session_id: str, limit: int = 40,
                before: int | None = None, *,
                limit_of: Callable[[str], int] | None = None) -> list[dict]:
        """The last `limit` messages, oldest first, in Anthropic message shape.

        A `limit` below zero is every message the chat has, which is how every
        chat but General is sent (`rouh/chatkinds.py`).

        Only the live version of each exchange, which is the conversation as it
        stands: a try the person has stepped away from is kept on disk and is
        not part of what the model is asked.

        `before` is the root of an exchange being answered again, and it cuts
        the history off in front of it. A retry is that question asked again
        from where it was asked, so the window it goes out in is the one it had
        the first time - not one with its own old answer in it.

        A tail slice of a conversation is not automatically a valid conversation,
        and an invalid one is rejected outright with a 400 that never mentions
        which turn caused it. Three things have to be true, and each was learned
        by breaking:

        1. It starts with a user message. A leading assistant turn is rejected.
        2. That first user message is not a set of tool results. Tool results
           must follow the tool call they answer, and the call is on the
           assistant turn just before - which a tail slice may have cut off.
           This is what a live session actually hit: "messages.0.content.0:
           unexpected tool_use_id found in tool_result blocks".
        3. It does not end on an assistant turn that asked for a tool and never
           got an answer. That happens whenever a turn is cancelled between the
           model asking and the tool replying, which barge-in does routinely.
           Appending the next question after it is rejected the same way.

        Once any of these is wrong the session stays broken for every later
        turn, because the same bad prefix is replayed each time.

        A fork is asked with what it came off in front of its own words: the
        chat it was forked from, up to the message it was forked after, and
        that chat's own parent before it if it is a fork too (`rouh/forks.py`).
        The fork's own turns come first out of the `limit`, because they are
        what is being talked about, and what is left of it is filled from the
        parent. `limit_of` says, of a chat a fork came off, the most of it the
        fork may carry: what that chat is sent with itself. A fork of General,
        which is sent its newest messages and never the months behind them,
        carries that much of General and no more, however whole the fork's own
        conversation is. The joins are repaired with the rest.
        """
        return repair_history(self._window(session_id, limit, before=before,
                                           limit_of=limit_of))

    def _window(self, session_id: str, limit, *, before: int | None = None,
                upto: int | None = None, depth: int = 0,
                limit_of: Callable[[str], int] | None = None) -> list[dict]:
        """`history` before it is repaired: this chat's turns, and what it carries.

        `upto` is a message of this chat, and cuts it off after the exchange
        that message is part of: how much of a parent a fork of it carries.
        The exchange and not the id, so a question the parent asked again
        after the fork was taken still reaches the fork with its live answer.
        """
        with self._lock:
            # A notice kept in the chat is the page's alone (`add_notice`).
            rows = (TranscriptMessage.objects.filter(session_id=session_id, live=True,
                                                     notice=False)
                    .annotate(exchange=_exchange()))
            if before is not None:
                rows = rows.filter(exchange__lt=before)
            rows = _on_stage(rows, session_id)
            if upto is not None:
                edge = (TranscriptMessage.objects.filter(id=upto).annotate(ex=_exchange())
                        .values_list("ex", flat=True).first())
                rows = (rows.filter(exchange__lte=edge) if edge is not None
                        else rows.filter(id__lte=upto))
            rows = list(_limited(rows.order_by("-exchange", "-id").values("role", "content"),
                                 limit))
            fork = (ChatFork.objects.filter(chat_id=session_id)
                    .values("parent_id", "at").first())
        msgs = [{"role": r["role"], "content": json.loads(r["content"])} for r in reversed(rows)]
        room = _room(limit, len(rows))
        if fork and limit_of is not None:
            room = _least(room, limit_of(fork["parent_id"]))
        if fork and fork["at"] is not None and room != 0 and depth < forks.DEEP:
            msgs = drop_carried_stops(self._window(fork["parent_id"], room, upto=int(fork["at"]),
                                                   depth=depth + 1, limit_of=limit_of)) + msgs
        return msgs

    # --- forking, and turns cut short ---------------------------------------
    #
    # Two halves of one idea: a conversation is a thing with a history, so it
    # can be copied from a point and it can be interrupted. Neither was true
    # before. A restart mid-turn left no trace at all, and there was no way to
    # try a conversation two ways from where it got interesting.

    #: What a branched chat is called: the original's name with this after it.
    BRANCH_SUFFIX = " (branch)"

    #: What is written into a chat whose turn was cut short by a restart.
    #: Said in the first person, because it is Rouh's turn that was lost and
    #: the person is owed the sentence rather than a gap.
    INTERRUPTED = ("That answer was cut short: I was restarted while I was "
                   "writing it. Ask me again and I will pick it up.")

    def fork_chat(self, chat_id: str, *, upto: int | None = None,
                  title: str | None = None) -> dict | None:
        """Copy a chat into a new one, up to a point, and make the copy active.

        `upto` is the id of the last message to carry over; leaving it out
        copies the whole thing. What is copied is the messages and the cards
        that were drawn with them, so the branch opens looking exactly like
        the moment it was taken from.

        The original is untouched, which is the whole point: a branch is for
        trying the other way without losing this one. Returns the new chat, or
        None if there was no such chat to copy.
        """
        source = self.chat(chat_id)
        if source is None:
            return None
        named = (title or "").strip()
        if not named:
            was = (source.get("title") or "").strip()
            named = (was + self.BRANCH_SUFFIX) if was and was != UNTITLED else "Branch"
        new_id = self.new_chat(named[:MAX_TITLE], folder_id=source.get("folder_id"))
        with self._lock, transaction.atomic():
            rows, became = self._copy_branch_messages(chat_id, new_id, upto=upto)
            until = rows[-1]["ts"] if rows else 0.0
            self._copy_branch_context(chat_id, new_id, became, until)
        self._record_branch_turns(new_id, rows)
        log.info("chat %s branched into %s at message %s",
                 chat_id, new_id, upto if upto is not None else "the end")
        made = self.chat(new_id)
        if made is not None:
            made["branched_from"] = chat_id
            made["branched_at"] = upto
            # Which copy each message became. The canvas is copied from the
            # artifact rows now (`rouh/artifacts.fork`), and a card's anchor
            # has to be translated the same way the messages above were or the
            # branch's transcript puts it nowhere.
            made["became"] = became
            # How far the copy goes, in time. The canvas is carried over up to
            # the same moment, which is what `until` above means for the cards
            # this method used to copy itself.
            made["branched_ts"] = until
        return made

    def _copy_branch_messages(self, chat_id: str, new_id: str, *,
                              upto: int | None) -> tuple[list[dict], dict[int, int]]:
        """Copy the live rows and map their ids, under the caller's lock and transaction."""
        # The live conversation and not the tries behind it: a branch is
        # this conversation carried on another way, and the ways it was
        # already tried belong to the chat they were tried in.
        rows = TranscriptMessage.objects.filter(session_id=chat_id, live=True)
        if upto is not None:
            rows = rows.filter(id__lte=upto)
        rows = [dict(r, root=r.pop("exchange")) for r in
                rows.annotate(exchange=_exchange()).order_by("id")
                .values("id", "ts", "role", "content", "spoken", "exchange", "note",
                        "notice")]
        became: dict[int, int] = {}
        for row in rows:
            copy = TranscriptMessage.objects.create(
                session_id=new_id, ts=row["ts"], role=row["role"],
                content=row["content"], spoken=row["spoken"],
                root=(became.get(int(row["root"])) if row["root"] is not None
                      else None),
                version=1, live=True, note=row["note"], notice=row["notice"])
            became[int(row["id"])] = int(copy.id)
            if row["root"] is None or int(row["root"]) == int(row["id"]):
                TranscriptMessage.objects.filter(id=copy.id).update(root=copy.id)
        return rows, became

    def _copy_branch_context(self, chat_id: str, new_id: str, became: dict[int, int],
                             until: float) -> None:
        """Copy the canvas and timelines, under the caller's lock and transaction."""
        # The canvas too, up to the same moment. A branch whose screen is
        # empty is not the same conversation seen again, it is a new one
        # with somebody else's words in it.
        #
        # Each card's anchor is translated to the copy of the message it
        # pointed at. Carried over untranslated it would name a row in the
        # chat this was branched from, and the branch's own transcript
        # would put the card nowhere; a card whose message was not carried
        # over keeps no anchor at all and falls back to its timestamp.
        drawn = (ScreenCard.objects.filter(session_id=chat_id, ts__lte=until)
                 .order_by("id")
                 .values("ts", "title", "description", "spec", "after_message_id"))
        for card in drawn:
            was = card["after_message_id"]
            ScreenCard.objects.create(
                ts=card["ts"], session_id=new_id, title=card["title"],
                description=card["description"], spec=card["spec"],
                after_message_id=became.get(int(was)) if was is not None else None)
        # And the lines its tool calls drew, under the copies of the
        # messages they were drawn among. A call keeps its id, which is
        # also the id of its block in the copied row.
        for line in (ToolLine.objects.filter(session_id=chat_id,
                                             after_message_id__in=list(became))
                     .order_by("id").values()):
            line.pop("id")
            line.update(session_id=new_id,
                        after_message_id=became[int(line["after_message_id"])])
            ToolLine.objects.create(**line)
        # And what Master's look-ups did for each of the person's messages.
        for kept in RecallTimeline.objects.filter(session_id=chat_id, message_id__in=list(became)):
            RecallTimeline.objects.create(message_id=became[int(kept.message_id)], session_id=new_id,
                                          ts=kept.ts, data={**kept.data, "msg": became[int(kept.message_id)]})
        # And how the model of each answer was decided, under the copy of its exchange.
        for kept in RouteTimeline.objects.filter(session_id=chat_id, root__in=list(became)):
            RouteTimeline.objects.create(call=f"{kept.call}@{new_id}", session_id=new_id,
                                         root=became[int(kept.root)], ts=kept.ts, data=kept.data)

    def _record_branch_turns(self, new_id: str, rows: list[dict]) -> None:
        """Write the branch's spoken record after the transcript transaction has ended."""
        # The branch's own record of what was said, the same words in the same
        # order. A branch is this conversation carried on another way, so it
        # opens holding what this one held; without this the copy would show
        # every turn on screen and say it had none.
        for row in rows:
            if row["note"]:
                continue
            try:
                said = _words(row["role"], json.loads(row["content"]))
            except (TypeError, ValueError):
                said = ""
            if said and said != STOP_NOTE:
                conversations.add_turn(new_id, row["role"], said)

    def forget_chat(self, chat_id: str) -> int:
        """Throw away the transcript of a chat that has been deleted.

        The chat itself and its record of what was said are the object store's,
        and deleting one takes the other with it. What is here is the model's
        own tape and the cards drawn on the way past, and neither has anything
        to belong to once the chat is gone, so whoever deletes a chat hands the
        id here in the same breath. Only a person ever does: nothing deletes a
        chat on a clock.

        Never call this for a chat that still exists.
        """
        with self._lock, transaction.atomic():
            gone, _ = TranscriptMessage.objects.filter(session_id=chat_id).delete()
            ScreenCard.objects.filter(session_id=chat_id).delete()
            ToolLine.objects.filter(session_id=chat_id).delete()
            RecallTimeline.objects.filter(session_id=chat_id).delete()
            RouteTimeline.objects.filter(session_id=chat_id).delete()
            OpenTurn.objects.filter(session_id=chat_id).delete()
        return gone

    def drop_what_was_written(self, session_id: str, since: float) -> int:
        """Take back the words of an answer the person talked over.

        Talking over an answer that has not finished is carrying the question
        on, not interrupting it (`rouh/turnmarks.py`). The words the model
        had written were written before the person had finished asking, so they
        are dropped rather than kept: left in, the next turn reads a half
        answer and treats what the person went on to say as a follow-up to it,
        which is the thing that made one request into six on 13 September 2026.

        What is NOT dropped, and the rules are exact:

        - Anything with a tool call or a tool result in it. The API requires
          every call to keep its result, and a call that reached a background
          worker really did happen. The walk back stops at the first of those.
        - Anything the person said. Their question stands; it is the question
          whatever they add to it next.
        - Anything older than `since`, which is when this turn started. The
          finished answer of the turn before is not this turn's to take back.

        Most of the time there is nothing to do at all, and that is by design:
        what is streaming is not written down until the response it belongs to
        has finished arriving, so an answer abandoned mid-sentence has left
        nothing behind. This is for the rest of it - a turn parked by a
        server-side tool and picked up again, which stores what it had written
        before it goes back for more.

        Returns how many messages were taken back.
        """
        with self._lock, transaction.atomic():
            rows = (TranscriptMessage.objects
                    .filter(session_id=session_id, ts__gte=since, live=True, notice=False)
                    .order_by("-id").values("id", "role", "content"))
            gone = []
            for row in rows:
                if row["role"] != "assistant":
                    break
                content = json.loads(row["content"])
                if _blocks_of_type(content, "tool_use"):
                    break
                gone.append(row["id"])
            if not gone:
                return 0
            TranscriptMessage.objects.filter(id__in=gone).delete()
        log.info("took back %d message(s) of an answer that was talked over", len(gone))
        return len(gone)

    def begin_turn(self, session_id: str, said=None, *, note: bool = False) -> None:
        """Write down that a turn has started in this chat, and what was asked.

        `said` is the person's own words. They are deliberately not in the
        conversation yet: a turn does not write them down until the model has
        read the mark and said the question was finished
        (`rouh/turnmarks.py`), because a question stored before that is a
        fragment stored for ever. So they are kept here instead, and
        `mark_interrupted` puts them in if the process goes away first - which
        is the very thing this row exists to prevent.

        `note` says `said` is not their words at all but a note of Rouh's own
        (`add_message`), so it goes back in as one.
        """
        with self._lock:
            # INSERT ... ON CONFLICT DO UPDATE: the whole row is this turn's,
            # which is what INSERT OR REPLACE said to SQLite.
            OpenTurn.objects.bulk_create(
                [OpenTurn(session_id=session_id, started_at=time.time(),
                          said=json.dumps(said) if said is not None else "",
                          note=bool(note))],
                update_conflicts=True, unique_fields=["session_id"],
                update_fields=["started_at", "said", "note"])

    def end_turn(self, session_id: str) -> None:
        """And that it has finished, however it finished.

        Called from a `finally`, so an abandoned turn, a failed turn and a
        finished one all clear the row. Only a turn whose process went away
        leaves one behind, which is exactly the case this is for.
        """
        with self._lock:
            OpenTurn.objects.filter(session_id=session_id).delete()

    def open_turns(self) -> list[dict]:
        with self._lock:
            rows = list(OpenTurn.objects.order_by("started_at")
                        .values("session_id", "started_at", "said", "note"))
        out = []
        for r in rows:
            try:
                said = json.loads(r["said"]) if r["said"] else None
            except ValueError:                    # written before `said` was used
                said = None
            out.append({"session_id": r["session_id"],
                        "started_at": r["started_at"], "said": said,
                        "note": bool(r["note"])})
        return out

    def _asked_in_turn(self, session_id: str, asked, since: float):
        """The exchange and try a turn's question was written into, if it was.

        Looked for among what this turn wrote, not only at the last row: a
        turn that had called a tool before the restart has its results after
        the question, and on 19 October 2026 a check of the last row alone
        wrote the question a second time (chat-bd77233cdec5, feedback
        fr_433563836c27). Returns (root, version), or None.
        """
        with self._lock:
            rows = (TranscriptMessage.objects
                    .filter(session_id=session_id, role="user", live=True,
                            notice=False, ts__gte=since)
                    .annotate(exchange=_exchange()).order_by("-id")
                    .values("content", "exchange", "version"))
            for row in rows:
                try:
                    if json.loads(row["content"]) == asked:
                        return int(row["exchange"]), int(row["version"])
                except ValueError:
                    continue
        return None

    #: Said instead under an answer a deploy cut after waiting the most it may for it to finish
    #: (`rouh/answers_now.py`, `guard/rouh_guard/deploywait.py`).
    CUT_BY_DEPLOY = ("That answer was cut short: I was updated after waiting {minutes} for it "
                     "to finish, the longest an update waits. Ask me again and I will pick it up.")

    def mark_interrupted(self, cut_by_deploy: dict | None = None) -> list[str]:
        """Turn every turn left open by a restart into a sentence, and return
        the chats that had one.

        Written as an assistant message, because it is the assistant's own
        turn that was lost. `repair_history` then does the rest on the next
        read: the dangling tool call in front of it is dropped, because its
        answer never came, and the sentence stays.

        The question goes in first when it is not there already. A turn writes
        the person's words down only once the model has said they had finished
        asking, so one that died before that has a sentence about an answer and
        nothing above it saying what was asked; `begin_turn` kept the words for
        exactly this moment.

        Nothing here guesses at what the answer would have been.
        """
        marked = []
        for row in self.open_turns():
            session_id = row["session_id"]
            asked = row.get("said")
            root = None
            version = 1
            if asked is not None:
                written = self._asked_in_turn(session_id, asked, row["started_at"])
                if written is not None:
                    # The question reached the conversation before the process
                    # went away, so the sentence about the answer belongs to
                    # that same exchange rather than starting one of its own.
                    root, version = written
                else:
                    root = self.add_message(session_id, "user", asked,
                                            note=bool(row.get("note")))
            said = self.INTERRUPTED
            cut = (cut_by_deploy or {}).get(session_id)
            if cut is not None:
                mins = max(1, round(float(cut.get("waited") or 600) / 60))
                said = self.CUT_BY_DEPLOY.format(minutes=f"{mins} minute{'s' if mins != 1 else ''}")
            self.add_message(session_id, "assistant",
                             [{"type": "text", "text": said}], root=root,
                             version=version)
            marked.append(session_id)
        if marked:
            with self._lock:
                OpenTurn.objects.all().delete()
            log.warning("%d turn(s) were cut short by a restart: %s",
                        len(marked), ", ".join(marked))
        return marked

    # --- what it cost (rouh/costs.py) -------------------------------------

    def note_spend(self, session_id: str, summary: dict) -> None:
        """Write down what one turn cost. Never raises: it is a number on a
        screen, and a turn must not fail because it could not be counted."""
        try:
            with self._lock:
                Spend.objects.create(
                    ts=time.time(), session_id=session_id,
                    model=str(summary.get("model") or ""),
                    input_tokens=int(summary.get("input") or 0),
                    output_tokens=int(summary.get("output") or 0),
                    cache_read=int(summary.get("cache_read") or 0),
                    cache_write=int(summary.get("cache_write") or 0),
                    cost=summary.get("cost"),
                    calls=list(summary.get("calls") or []),
                    first_token_ms=summary.get("first_token_ms"),
                    first_text_ms=summary.get("first_text_ms"),
                    first_word_ms=summary.get("first_word_ms"),
                    tool_search=str(summary.get("tool_search") or ""),
                    tools_loaded=",".join(summary.get("tools_loaded") or []))
        except Exception:
            log.warning("a turn's cost could not be written down", exc_info=True)

    def spend(self, *, session_id: str = "", since: float = 0.0) -> dict:
        """What has been spent, added up.

        `session_id` narrows it to one chat and `since` to a stretch of time;
        neither narrows it by default, which is the whole-of-it answer.

        `priced` is how many of the turns had a price, so a person can tell
        "this cost nothing" from "nobody knows what this cost".
        """
        rows = Spend.objects.all()
        if session_id:
            rows = rows.filter(session_id=session_id)
        if since:
            rows = rows.filter(ts__gte=since)
        with self._lock:
            # Named with a prefix, because an aggregate may not share its name
            # with a column another aggregate in the same query reads.
            row = rows.aggregate(
                n_turns=Count("id"),
                n_input_tokens=Coalesce(Sum("input_tokens"), 0),
                n_output_tokens=Coalesce(Sum("output_tokens"), 0),
                n_cache_read=Coalesce(Sum("cache_read"), 0),
                n_cache_write=Coalesce(Sum("cache_write"), 0),
                n_cost=Coalesce(Sum("cost"), 0.0),
                n_priced=Count("cost"))
        out = {k: row["n_" + k] for k in ("turns", "input_tokens", "output_tokens", "cache_read",
                                          "cache_write", "cost", "priced")}
        out["turns"] = int(out["turns"])
        out["priced"] = int(out["priced"])
        for key in ("input_tokens", "output_tokens", "cache_read", "cache_write"):
            out[key] = int(out[key])
        out["cost"] = float(out["cost"] or 0.0)
        sent = out["input_tokens"] + out["cache_read"] + out["cache_write"]
        out["sent"] = sent
        out["cached"] = round(out["cache_read"] / sent, 3) if sent else 0.0
        return out

    @staticmethod
    def _said(r) -> dict | None:
        """One stored row as the page draws it, or None when it draws nothing."""
        # A note Rouh's own software handed the model in the person's place
        # (`add_message`). It was never on the screen while it was being
        # answered, and reading the chat back must not put it there either,
        # under their name: "There is a message under my name that I never
        # wrote - instructions to the robot" (feedback fr_2f27e92125ba).
        if r.get("note"):
            return None
        content = json.loads(r["content"])
        text = _words(r["role"], content)
        files = attachments.markers_in(content)
        if not text and not files:
            return None
        # The id goes with it because a card says which message it came
        # after, and the page cannot put the two in one stream without
        # being able to match the two numbers up.
        row = {"id": r["id"], "ts": r["ts"], "role": r["role"], "text": text}
        # A question asked in Ask AI, or the answer it had there: drawn with
        # the page it was about, and never offered to be asked again here.
        asked = askai_of(content) if r["role"] == "user" else None
        if asked is not None:
            row["askai"] = {k: asked[k] for k in ("title", "doc", "passage")}
        if r.get("root") is not None:
            row["root"] = int(r["root"])
        if files:
            row["attachments"] = files
        # The note written in the person's place when they pressed Stop
        # (`stopping.STOP_NOTE`). It is stored as one of their messages
        # because that is what the model has to read, and it is marked
        # here because on screen it is not a message at all: it is the
        # line under a half-finished answer saying why it stops there.
        if text == STOP_NOTE:
            row["stopped"] = True
        # A notice's words kept in its chat (`add_notice`): drawn as Rouh's,
        # with nothing under it that would ask it again.
        if r.get("notice"):
            row["notice"] = True
        return row

    def transcript(self, session_id: str, limit: int = 200) -> list[dict]:
        """Plain text for the UI, not for the model.

        Files the person attached come back beside the words rather than inside
        them, so a reloaded page can draw the same chips and thumbnails it drew
        when they were sent. A message that is nothing but a screenshot has no
        text at all and still has to appear, or reloading loses it.

        Only the live version of each exchange is here. The tries behind it are
        kept and are reached with the arrows under the message, which ask for
        one by number (`pick_version`); reading them all back would draw the
        same question four times.
        """
        return self.transcript_page(session_id, limit)[0]

    def transcript_page(self, session_id: str, limit: int = 200,
                        before: tuple[int, int] | None = None) -> tuple[list[dict], str]:
        """`transcript`, a page at a time: the `limit` rows before `before`, and where the
        page before this one ends, or "" when there is nothing older.

        `before` is that mark as it was handed out, (exchange, id) of the oldest row read:
        the rows are read newest exchange first, so the next page is every row that comes
        after it in that order. The page reads the last page of a chat with the handshake and
        each page before it as the person scrolls up to it (`/api/transcript`); until 23
        October 2026 it had the last forty rows and nothing older could be read back at all.
        """
        found = TranscriptMessage.objects.filter(session_id=session_id, live=True)
        if before is not None:
            exchange, row = before
            found = found.alias(ex=_exchange()).filter(Q(ex__lt=exchange) | Q(ex=exchange, id__lt=row))
        with self._lock:
            rows = _drawn(found.order_by(_exchange().desc(), "-id"), limit)
        older = f"{rows[-1]['root']}.{rows[-1]['id']}" if rows and limit and len(rows) >= limit else ""
        out = []
        for said in self._told(session_id, list(reversed(rows))):
            _askai_answer(out[-1] if out else None, said)
            out.append(said)
        # And how many tries each of those exchanges has behind it, which is
        # what the counter under a message says. Only the ones with more than
        # one are looked up: most exchanges were asked once and have nothing to
        # step through.
        oldest = min((row["root"] for row in out if row.get("root")), default=None)
        if oldest is not None:
            more = self._many_tries(session_id, oldest)
            for row in out:
                spread = more.get(row.get("root"))
                if spread:
                    row.update(spread)
        return out, older

    def _many_tries(self, session_id: str, since_root: int) -> dict[int, dict]:
        """The exchanges of this chat that were asked more than once.

        `{root: {"version", "versions", "edited"}}`, and nothing at all for the
        exchanges with one try, which is nearly all of them.
        """
        with self._lock:
            # `id>=?` as well as the exchange, and it is not redundant: an
            # exchange's root is the id of the row that began it, so a row can
            # never belong to an exchange newer than itself. That makes the
            # extra condition true wherever the first one is, and it is the one
            # of the two an index can be read with.
            rows = (TranscriptMessage.objects
                    .filter(session_id=session_id, id__gte=since_root)
                    .annotate(exchange=_exchange()).filter(exchange__gte=since_root)
                    .values("exchange", "version")
                    .annotate(first=Min("id"), live=BoolOr("live"))
                    .order_by("exchange", "version"))
            by_root: dict[int, list] = {}
            for r in rows:
                by_root.setdefault(int(r["exchange"]), []).append(r)
            out: dict[int, dict] = {}
            for root, tries in by_root.items():
                if len(tries) < 2:
                    continue
                asks = set()
                for t in tries:
                    one = (TranscriptMessage.objects.filter(id=t["first"])
                           .values_list("content", flat=True).first())
                    asks.add(_plain(json.loads(one)) if one is not None else "")
                live = next((int(t["version"]) for t in tries if t["live"]),
                            int(tries[-1]["version"]))
                out[root] = {"version": live, "versions": len(tries),
                             "edited": len(asks) > 1}
        return out

    # --- facts --------------------------------------------------------------
    #
    # A fact belongs to a project or to the general memory, and the `facts`
    # table says which (`project_id`, "" for the general one). Petar asked for
    # exactly that on 24 September 2026, after Rouh said "Kept" and the note
    # was not in the project he opened: "that should be either different than
    # projects memory or the setup should be such that a column in the
    # database says for which project that is."
    #
    # Nothing here knows what a project is called or which one a conversation
    # is in: that is `rouh/keeping.py`, which is the one place those two
    # questions are answered and the one caller that passes a project in here.

    #: The marks the model starts its replies with, saying whether the person
    #: had finished asking (`rouh/turnmarks.py`). Never kept.
    TURN_MARKS = turnmarks.MARKS

    def remember(self, key: str, value: str, project_id: str = "") -> str:
        """Keep one fact, in a project or in the general memory.

        The same label in two projects is two facts, which is why the label is
        no longer this table's primary key: it is unique inside a project and
        nowhere else, so keeping "deposit" under Kvadrat cannot rewrite
        "deposit" under Vitosha.
        """
        for mark in self.TURN_MARKS:
            key, value = key.replace(mark, ""), value.replace(mark, "")
        key = key.strip().lower()[:80]
        value = value.strip()[:MAX_FACT_CHARS]
        project_id = (project_id or "").strip()
        if not key or not value:
            return "Nothing to remember - the key or the value was empty."
        now = time.time()
        with self._lock, transaction.atomic():
            # A fact said again keeps when it was first said and moves its
            # value and its time on: INSERT ... ON CONFLICT DO UPDATE.
            Fact.objects.bulk_create(
                [Fact(key=key, project_id=project_id, value=value,
                      created_at=now, updated_at=now)],
                update_conflicts=True, unique_fields=["project_id", "key"],
                update_fields=["value", "updated_at"])
            # Keep the prompt bounded: drop the least recently updated beyond
            # the cap. The cap is over every fact there is, a project's
            # included, because the prompt holds every fact there is.
            keep = Fact.objects.order_by("-updated_at").values("id")[:MAX_FACTS]
            Fact.objects.exclude(id__in=Subquery(keep)).delete()
        return f"Remembered {key}."

    def forget(self, key: str, project_id: str = "") -> str:
        """Forget one fact of one project. "" is the general memory."""
        with self._lock:
            gone, _ = Fact.objects.filter(key=key.strip().lower(),
                                          project_id=(project_id or "").strip()).delete()
        return "Forgotten." if gone else "There was nothing stored under that."

    def facts(self, project_id: str | None = None) -> list[tuple[str, str]]:
        """Key and value, newest change first. None is every fact there is.

        `project_id` of "" is the general memory alone, which is what it meant
        before there were projects.
        """
        rows = Fact.objects.all()
        if project_id is not None:
            rows = rows.filter(project_id=project_id.strip())
        with self._lock:
            found = list(rows.order_by("-updated_at").values_list("key", "value"))
        return [(k, v) for k, v in found]

    # The Rules page, under the person's name (`rouh/web/rules.py`), reads
    # and changes the same rows the three tools above do, so what the page
    # says and what Rouh answers to "what do you remember" are never two lists.
    # It works on a row's id rather than on its label, because a label is only
    # unique inside one project now and the page shows every project at once.

    def fact_rows(self, project_id: str | None = None) -> list[dict]:
        """Every fact, with its id, its project, and its two times.

        Newest first by when it was first remembered rather than by when it was
        last changed, which is what the model is given: an edit made on the
        page moves the time it was changed on, and a row that jumped to the top
        of the list the moment it was saved would leave the person looking at
        a different memory from the one they had just corrected.
        """
        rows = Fact.objects.all()
        if project_id is not None:
            rows = rows.filter(project_id=project_id.strip())
        with self._lock:
            return list(rows.order_by("-created_at", "key")
                        .values("id", "key", "project_id", "value",
                                "created_at", "updated_at"))

    def unfile_facts(self, project_id: str, label: str = "") -> int:
        """Give a project's notes back to the general memory. How many moved.

        What a deleted project leaves behind. Nothing Rouh was told is thrown
        away because a project went: the note is still there, and the Memory
        page has it under the general memory the next time it is read.

        A label already taken in the general memory keeps its project's note
        beside that one rather than over it, by putting the project's name
        after it: "deposit" coming out of Acme becomes "deposit (Acme)". The
        name is passed in because by now there is no project row to read it
        from, and a number is used when nobody said what it was called.
        """
        project_id = (project_id or "").strip()
        if not project_id:
            return 0
        with self._lock, transaction.atomic():
            taken = set(Fact.objects.filter(project_id="").values_list("key", flat=True))
            moved = 0
            for row in Fact.objects.filter(project_id=project_id).order_by("id"):
                key, at = row.key, 1
                while key in taken:
                    key = f"{row.key} ({label})" if label and at == 1 else f"{row.key} ({at})"
                    at += 1
                taken.add(key)
                Fact.objects.filter(id=row.id).update(key=key[:80], project_id="")
                moved += 1
        return moved

    def facts_block(self, titles=None) -> str:
        """Every fact, for the system prompt, with each project's own together.

        `titles` maps a project's id to its name (`keeping.project_names`).
        The general memory comes first and is named as what it is, and each
        project's notes follow under that project's name, so the model can
        always say where something it repeats was kept. A fact whose project is
        gone reads as a general one.
        """
        titles = dict(titles or {})
        general: list[str] = []
        grouped: dict[str, list[str]] = {}
        for row in self.fact_rows():
            line = f"- {row['key']}: {row['value']}"
            name = titles.get(row["project_id"] or "", "")
            if not row["project_id"] or not name:
                general.append(line)
            else:
                grouped.setdefault(name, []).append(line)
        if not general and not grouped:
            return ""
        if not grouped:
            # Nothing is filed under a project, so there is nothing to tell
            # apart and no heading worth the words.
            return "\n\nWhat you have been told to remember:\n" + "\n".join(general)
        out = ["\n\nWhat you have been told to remember, and where each of it is kept.",
               "In the general memory, which is what belongs to no one project:",
               "\n".join(general) if general else "- nothing"]
        for name in sorted(grouped):
            out.append(f"In the project {name}:")
            out.append("\n".join(grouped[name]))
        return "\n".join(out)

    # --- what has been on the screen ----------------------------------------
    #
    # Everything put on the screen is kept, with a sentence saying what it was.
    # This is a voice-first tool: the screen scrolls away and cannot be pointed
    # at, so "show me that table of jobs again" has to be answerable. Without a
    # description there is nothing to match those words against, which is why
    # the description is stored beside the card rather than derived from it.

    def add_card(self, title: str, description: str, spec, session_id: str | None = None,
                 after_message_id: int | None = None) -> int:
        """Keep a card, against the chat it was drawn in and the turn that drew it.

        Cards belong to a chat for the same reason messages do: the canvas is
        what was shown while that conversation was being had, and switching to
        another one has to show that one's screen rather than everything ever
        drawn. A caller that does not say which chat means the one the turn
        now running is answering into (`ANSWERING`), and the active chat when
        nothing is being answered. Not simply the active chat: a turn runs to
        the end in the thread it was asked in even after the person has gone
        off to look at another one, and a card it draws on the way belongs
        under that question rather than wherever they happen to be standing.

        `after_message_id` is the message this card came after. A caller that
        does not say means the newest message in that chat, which during a turn
        is the assistant turn whose tool call is drawing this card: it asked
        for the card, so the card belongs under it. That is an ordering fact
        and nothing else - what the card holds stays in `spec` and is never
        copied into `messages` - and it is what lets the transcript put
        messages and cards back in the order they happened.

        Null is a real answer and always has been: a chat with nothing said in
        it yet has no message to come after, and every card drawn before this
        column existed has none either. Both fall back to ordering by `ts`.
        """
        session_id = session_id or self.answering_chat()
        if after_message_id is None:
            after_message_id = self.last_message_id(session_id)
        with self._lock:
            made = ScreenCard.objects.create(
                ts=time.time(), session_id=session_id, title=title[:200],
                description=(description or "")[:400], spec=json.dumps(spec),
                after_message_id=after_message_id)
        return int(made.id)

    def answering_chat(self) -> str:
        """The chat being written into right now: the turn's, or the active one.

        See `ANSWERING`. This is the answer to "which conversation does what I
        am about to store belong to" for code that was never told.
        """
        return ANSWERING.get() or self.active_chat()

    def last_message_id(self, session_id: str) -> int | None:
        """The newest message in a chat, or None when nothing has been said."""
        with self._lock:
            last = (TranscriptMessage.objects.filter(session_id=session_id, live=True)
                    .aggregate(last=Max("id"))["last"])
        return int(last) if last is not None else None

    def holds_message(self, session_id: str, message_id: int) -> bool:
        """Whether a message is one of this chat's."""
        with self._lock:
            return TranscriptMessage.objects.filter(session_id=session_id,
                                                    id=message_id).exists()

    def cards(self, limit: int = 20, query: str = "") -> list[dict]:
        """Newest first. `query` matches the title and the description.

        Matched without regard to case, as SQLite's LIKE did. What is typed is
        matched as it is: a per-cent sign or an underscore in it is that
        character and not a wildcard, which is the one way this is stricter
        than the LIKE it replaced.
        """
        rows = ScreenCard.objects.all()
        said = query.strip()
        if said:
            rows = rows.filter(Q(title__icontains=said) | Q(description__icontains=said))
        with self._lock:
            return list(_limited(rows.order_by("-id")
                                 .values("id", "ts", "title", "description"), limit))

    def card_history(self, before: int | None = None, limit: int = 10,
                     session_id: str | None = None) -> list[dict]:
        """A page of the canvas, newest first, each card whole.

        This is what the page draws when it opens, and again each time the
        reader scrolls back past the oldest card it holds. `before` is the
        number of the oldest card already on the page, so a page asks for what
        comes before what it has rather than for "page 3": cards are only ever
        added at the top, so a numbered page would shift under the reader
        every time the assistant drew something new.
        """
        rows = ScreenCard.objects.all()
        if before is not None:
            rows = rows.filter(id__lt=int(before))
        # None means every card there has ever been, which is what the tools
        # that search the whole history want. A chat id means that chat's
        # canvas, which is what the page wants.
        if session_id is not None:
            rows = rows.filter(session_id=session_id)
        with self._lock:
            rows = list(rows.order_by("-id").values(
                "id", "ts", "title", "description", "spec", "after_message_id")
                [:max(1, int(limit))])
        out = []
        for row in rows:
            card = dict(row)
            try:
                card["spec"] = json.loads(card["spec"])
            except (TypeError, ValueError):
                # One unreadable row must not take the whole history with it.
                card["spec"] = {"blocks": []}
            out.append(card)
        return out

    def all_cards(self) -> list[dict]:
        """Every card there has ever been, oldest first, with where it was drawn.

        The one read the artifact model's migration does. It carries the chat
        each card was drawn in and that chat's task, because who owns a card is
        decided from those two and asking again per card would be a query a
        card. Oldest first so the numbers go into the new table in the order
        they were handed out.
        """
        # The legacy `sessions` row a card was drawn in, if it is still there:
        # the LEFT JOIN this read always was, said as two small subqueries
        # because nothing in the database ties a card to a session.
        session = LegacySession.objects.filter(id=OuterRef("session_id"))
        with self._lock:
            rows = list(ScreenCard.objects.order_by("id").annotate(
                task=Coalesce(Subquery(session.values("task")[:1]), Value(""),
                              output_field=TextField()),
                chat_title=Subquery(session.values("title")[:1]),
            ).values("id", "ts", "session_id", "title", "description", "spec",
                     "after_message_id", "task", "chat_title"))
        out = []
        for row in rows:
            card = dict(row)
            try:
                card["spec"] = json.loads(card["spec"])
            except (TypeError, ValueError):
                card["spec"] = {"blocks": []}
            out.append(card)
        return out

    def card(self, card_id: int) -> dict | None:
        card_id = _row_id(card_id)
        if card_id is None:
            return None
        with self._lock:
            row = (ScreenCard.objects.filter(id=card_id)
                   .values("id", "ts", "title", "description", "spec", "after_message_id")
                   .first())
        if row is None:
            return None
        out = dict(row)
        out["spec"] = json.loads(out["spec"])
        return out

    # --- events -------------------------------------------------------------

    def log(self, kind: str, detail) -> None:
        with self._lock:
            Event.objects.create(
                ts=time.time(), kind=kind,
                detail=json.dumps(detail) if not isinstance(detail, str) else detail)


def _askai_answer(before: dict | None, row: dict) -> None:
    """Mark an answer as Ask AI's when the question it answers was asked there."""
    if (row["role"] == "assistant" and before is not None and before.get("askai")
            and before.get("root") == row.get("root")):
        row["askai"] = {"answer": True}


#: The blocks of an answer that are a tool being called, whoever ran it.
_CALLS = ("tool_use", "server_tool_use", "mcp_tool_use")


def _call_ids(blocks) -> list[str]:
    """The ids of the calls a stored answer made, in the order it made them."""
    if not isinstance(blocks, list):
        return []
    return [str(b["id"]) for b in blocks
            if isinstance(b, dict) and b.get("type") in _CALLS and b.get("id")]


def _input_text(value) -> str:
    """What a call was sent, as the text the page read it from (`toolInput`)."""
    if value is None:
        return ""
    return value if isinstance(value, str) else json.dumps(value)


def _line(row: dict) -> dict:
    """One kept tool line, in the fields `tool_start` and `tool_end` carry."""
    line = {"id": row["call_id"], "name": row["name"], "input": row["input"],
            "done": row["done"], "ok": row["ok"], "summary": row["summary"],
            "results": row["results"] or []}
    if row["output"] is not None:
        line["output"] = row["output"]
    return line


def _parts(blocks, by_call: dict, first: list, last: list) -> list[dict] | None:
    """One answer as the page drew it live: its words and the rows of tool
    lines between them, `[{"text"} | {"tools": [...]}]` in order, or None when
    it drew no line at all.

    `by_call` is every kept line by the id of its call, and a call of this
    answer that has one is where its line goes. `first` are lines that started
    before this answer was written and that no block of it names (Luna's own
    web search), and go at the top; `last` are lines started inside its calls
    (a helper's), and go with its own calls. Lines next to each other with no
    words between are one row, in the order they started, as they were live.
    """
    if isinstance(blocks, str):
        blocks = [{"type": "text", "text": blocks}]
    blocks = blocks if isinstance(blocks, list) else []
    cuts = [i for i, b in enumerate(blocks)
            if isinstance(b, dict) and b.get("type") in _CALLS and str(b.get("id")) in by_call]
    if not cuts and not first and not last:
        return None
    pieces = citing.footnoted_pieces(blocks, cuts)
    parts: list[dict] = []

    def tools(lines):
        if not lines:
            return
        if parts and "tools" in parts[-1]:
            parts[-1]["tools"].extend(lines)
        else:
            parts.append({"tools": list(lines)})

    def words(text):
        if text:
            parts.append({"text": text})

    tools(first)
    for k, cut in enumerate(cuts):
        words(pieces[k])
        tools([by_call[str(blocks[cut]["id"])]])
    if last:
        # With the answer's own calls, the row the helper's call is in.
        rows = [p for p in parts if "tools" in p]
        if rows:
            rows[-1]["tools"].extend(last)
            last = []
    words(pieces[-1])
    tools(last)
    for part in parts:
        if "tools" in part:
            part["tools"] = [_line(row) for row in sorted(part["tools"], key=lambda r: r["id"])]
    return parts


def _drawn(rows, limit=None) -> list[dict]:
    """Transcript rows as `Memory._said` reads them: with `root` as the exchange.

    The exchange a row belongs to is `COALESCE(root, id)`, and it is handed
    back under the name `root` because that is what the page has always been
    sent. It is read under another name, because the ORM will not let an
    expression share a name with a column.
    """
    picked = rows.annotate(exchange=_exchange()).values("id", "ts", "role", "content",
                                                        "exchange", "note", "notice")
    if limit is not None:
        picked = _limited(picked, limit)
    return [{"id": r["id"], "ts": r["ts"], "role": r["role"], "content": r["content"],
             "root": r["exchange"], "note": r["note"], "notice": r["notice"]}
            for r in picked]


def _begins_a_question(role: str, content: str) -> bool:
    """Whether a stored row is the person starting an exchange.

    Not every `user` row is. A turn writes its tool results down as user
    messages because that is the shape the API wants, and the note written when
    the person presses Stop (`stopping.STOP_NOTE`) is stored in their place so
    the next turn can read it. Neither is somebody asking something.
    """
    if role != "user":
        return False
    if _is_a_reply_to_a_tool(content):
        return False
    try:
        blocks = json.loads(content)
    except (TypeError, ValueError):
        return True
    return _plain(blocks) != STOP_NOTE


def _is_a_reply_to_a_tool(content: str) -> bool:
    """Whether a `user` row is the answer to a tool call rather than a question.

    A turn writes its tool results down as user messages, because that is the
    shape the API wants. They are not the person speaking, and an exchange does
    not end at one.
    """
    try:
        blocks = json.loads(content)
    except (TypeError, ValueError):
        return False
    return bool(_blocks_of_type(blocks, "tool_result"))


def _words(role: str, content) -> str:
    """A stored message as it is read on screen and kept in the chat's record.

    Rouh's own answers carry the numbers of the pages they were written from
    and the list of those pages under them, worked out from the citations the
    API hung on the text (`rouh/citing.py`), the same way the live stream
    wrote them. Everything else is its plain words.
    """
    if role == "assistant" and not isinstance(content, str):
        return citing.footnoted(content)
    asked = askai_of(content) if role == "user" else None
    if asked is not None:
        return asked["question"]
    return _plain(content)


def _plain(blocks) -> str:
    if isinstance(blocks, str):
        return blocks
    parts = []
    for b in blocks or []:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return " ".join(p for p in parts if p).strip()
