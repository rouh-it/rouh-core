"""Everything Rouh puts out, as one thing: a row in `artifact`.

Three things on this machine were really the same thing, and each was kept
somewhere else:

1. a **card** put on the screen by `show_on_screen`, which was a row of
   `screen_cards` in `memory.py`, numbered, with its blocks as JSON;
2. a **numbered step** in the person's workspace - `tasks/30.jarvis/30-07.x/` -
   which was a folder on disk and nothing else;
3. an **index.html page** built by a background job, which was a file on disk
   and nothing else.

All three are something a person ends up looking at, all three have a title, a
body and a history, and all three belonged to something. Since this module they
are all one row in `objects.artifact`, told apart by `kind` - card, page, doc,
diff, file, image - with every revision a row of `artifact_version` and the
bytes on disk named by `path` when there are any.

**The database is the source of truth.** The step folders and the `index.html`
files under `tasks/NN.slug` are a supportive structure written out from these
rows, never read back in as the truth. Where the two disagree the row wins, and
a hand-edited file is an inbound change to reconcile into the row rather than
an override of it. That is why `revise` writes the file again from the version
it has just added, and why nothing here ever reads a step folder to find out
what a card says.

An owner on purpose
-------------------

What a card belonged to used to be a rule about which thread the person
happened to be standing in, applied at the moment it was drawn and never again.
Here it is one `owns` row, decided on purpose and changeable:

* a card drawn in a chat **that a task owns** is owned by that task, which is
  what puts it on that task's canvas;
* a card drawn in a **loose chat** is owned by that chat, and has no folder and
  no number of its own. If that chat is later promoted to a task, its cards
  move with it and are written out then (`promote`);
* an artifact may be **loose**, owned by nobody at all, like a file in Drive
  that sits in no folder (`loose`). It is a first-class state, not a mistake.

Owning is not filing
--------------------

Being owned by a task is a row. Being a numbered step of that task is a folder
in the person's workspace with a number of its own, and a numbered step **is a
task**: `steps.file_step` makes it through `objecttree.create`, the same call
that makes any other.

So filing is asked for. Until 22 September 2026 `draw` filed every card drawn
in a chat that a task owned, which meant a conversation about a piece of work
quietly made numbered work of its own, nobody having asked for any of it. The
person's rule is that a task is made out of a chat when they ask for one and at
no other moment, so `file_as_step` is the only thing here that writes a step,
and something the person did is the only thing that calls it: the button on the
card, or the `make_a_task` tool when they say so out loud. The one filing that
still happens in a breath of its own is `promote`, where a chat they have just
asked to become a task takes what it drew in with it as its steps - which is
the same asking, carried through.

Deleting an owner deletes what it owned, since 22 September 2026: a card goes
with the chat, the task or the run it belongs to, and its bytes go with it
(`owning.remove`). That reverses what this module said for its first four
days, and the reason is the person's own - a delete that leaves forty cards
loose in the database is not a delete. A card owned by nobody is still legal
and still ordinary; it is simply not what a deleted owner leaves behind.

Which run drew it
-----------------

The run that produced a revision is written twice, because the two answer
different questions: `made_by_run` on the version says who wrote *this body*,
and a `rel='made'` link from the run to the artifact says this run had a hand
in this thing at all. The link is many to many on purpose - several runs revise
one page over the weeks - and the column is one per version.

Numbers
-------

A card keeps the number the person says out loud, and it is the number it had
in the screen history this table was migrated from: card 37 is `artifact` row
`card-37`, before and after the move. Nothing already shown was allowed to
lose its name, so the id carries it rather than a column.

Everything here is behind `objects.enabled()`. With the flag off nothing in
this module answers, and every caller does what it did before, out of
`memory.screen_cards`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time

from . import objects, steps

log = logging.getLogger("rouh.artifacts")

#: What a card's artifact id looks like. The number after the dash is the one
#: the person says out loud, and the one the row had in `screen_cards`.
CARD = "card-"

#: What a card is, as a media type: the blocks the canvas draws, as JSON.
CARD_MIME = "application/vnd.rouh.card+json"

#: A task's folder, `tasks/30.jarvis`, and the number in front of it.
_TASK_FOLDER = re.compile(r"^(\d+)[.-](.+)$")

#: How many cards at most are scanned to find the highest number in use. The
#: screen is a long history and this is a ceiling, not a page size.
_MOST_CARDS = 1_000_000


def enabled() -> bool:
    """Whether artifacts answer. Off means every caller does what it did before."""
    return objects.enabled()


def store() -> objects.ObjectStore | None:
    """The one store, or None when the model is off or the file will not open."""
    return objects.shared_store()


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
#
# A card's number is in its id, so allocating one is finding the highest there
# is and adding one. That is done once per process and then counted in memory,
# under this lock: two turns can draw at the same moment, and two cards with
# the same number would be one card with the other's body written over it.

_lock = threading.Lock()
_next: int | None = None
_counting: objects.ObjectStore | None = None


def forget_numbers() -> None:
    """Count again from what is in the store. A test world that moved needs this."""
    global _next, _counting
    with _lock:
        _next, _counting = None, None


def number_of(artifact_id: str) -> int | None:
    """The number in a card's id, or None for anything that is not a card."""
    if not artifact_id.startswith(CARD):
        return None
    try:
        return int(artifact_id[len(CARD):])
    except ValueError:
        return None


def _highest(st: objects.ObjectStore) -> int:
    """The highest card number in the store, or zero."""
    best = 0
    for row in st.list_artifacts(kind="card", limit=_MOST_CARDS):
        got = number_of(row.id)
        if got is not None and got > best:
            best = got
    return best


def _allocate(st: objects.ObjectStore) -> int:
    global _next, _counting
    with _lock:
        if _next is None or _counting is not st:
            _next, _counting = _highest(st) + 1, st
        number = _next
        _next += 1
    return number


# ---------------------------------------------------------------------------
# Who owns what is drawn
# ---------------------------------------------------------------------------


def task_id(task_rel: str) -> str:
    """The id of a workspace task, from its folder.

    `tasks/30.jarvis` is `task-30`, because 30 is what the person says out
    loud and a second identity for it would be one more thing to drift. A
    folder with no number in front of it is named by its folder instead.
    """
    name = (task_rel or "").strip().strip("/").split("/")[-1]
    found = _TASK_FOLDER.match(name)
    return f"task-{found.group(1)}" if found else f"task-{name}"


def object_at(task_rel: str) -> tuple[str, str] | None:
    """Whatever object already holds this folder, as (type, id). None for none.

    **One folder, one object.** A folder in the workspace belongs to exactly
    one row - that is what `.object.json` says about it - so anything asking
    "whose folder is this" has to ask the rows rather than guess from the name,
    and `ensure_task` below has to ask this before it mints anything.
    """
    st = store()
    task_rel = (task_rel or "").strip().strip("/")
    if st is None or not task_rel:
        return None
    for kind in ("project", "task"):
        row = st.by_folder(kind, task_rel)
        if row is not None:
            return (kind, row.id)
    return None


def ensure_task(task_rel: str) -> str | None:
    """The task row for a workspace folder, made if it is not here yet.

    The folder on disk is the supportive structure and this row is the truth,
    so a folder Rouh meets for the first time becomes a row rather than the
    other way round. Its number, slug and folder come off the folder's name,
    which is the only place they have ever been written down.

    **It never mints a second row for a folder that is already something.**
    The folder is asked about first, by folder and not by the id this would
    mint, and two answers come back that both used to end in a duplicate:

    * a **task** already there under another id - a step imported from the
      map as a uuid - is that folder's task, and its id is the answer;
    * a **project** already there is not a task at all, and the answer is
      None. `private/research` is a project; `register_step` used to hand it
      here as the parent of `private/research/03.market-research` and get
      back a brand new `task-research` row pointing at the project's own
      folder. Two rows for one folder is two of everything after it: the task
      browser drew Research and Personal as tasks nobody had filed, under
      "Not sorted", beside the projects of the same name and the same
      contents, and nothing could be done to either of them.
    """
    st = store()
    task_rel = (task_rel or "").strip().strip("/")
    if st is None or not task_rel:
        return None
    already = object_at(task_rel)
    if already is not None:
        if already[0] == "project":
            log.debug("%s is a project's folder, so no task row is made for it",
                      task_rel)
            return None
        return already[1]
    ident = task_id(task_rel)
    name = task_rel.split("/")[-1]
    found = _TASK_FOLDER.match(name)
    number = int(found.group(1)) if found else None
    slug = found.group(2) if found else name
    row = st.get_task(ident)
    if row is None:
        try:
            st.create_task(steps._words(name) or name, id=ident, number=number,
                           slug=slug, folder=task_rel)
        except Exception:
            # Two turns meeting the same task at once, or a number already
            # taken by a folder that was renamed. Either way the row that is
            # there is the one to use.
            log.debug("the task row %s was already there", ident, exc_info=True)
            row = st.get_task(ident)
            if row is None:
                return None
    elif row.folder != task_rel:
        # The folder moved on disk. The row wins on identity; what it says
        # about where the folder is follows the disk, because that is a fact
        # about the disk.
        st.update_task(ident, folder=task_rel, slug=slug)
    return ident


def ensure_chat(chat_id: str, title: str | None = None) -> str | None:
    """The chat row for a conversation, made if it is not here yet.

    Chats still live in `memory.py`; this is the row an `owns` link needs at
    the other end, keyed by the same id so there is one conversation and not
    two. When chats themselves move into this model the row is already here
    and already owns what was drawn in it.
    """
    st = store()
    chat_id = (chat_id or "").strip()
    if st is None or not chat_id:
        return None
    if st.get_chat(chat_id) is None:
        # A draft - a task opened, or New chat pressed, with nothing said yet -
        # is made the way the first turn would have made it: under its own id,
        # owned by what it was for. A bare row here would be a chat that
        # belongs to nothing, which is the state drafts exist to prevent.
        from . import conversations

        if conversations.make(chat_id) is not None:
            if title:
                st.update_chat(chat_id, title=title)
            return chat_id
        try:
            st.create_chat(id=chat_id, title=title)
        except Exception:
            log.debug("the chat row %s was already there", chat_id, exc_info=True)
            if st.get_chat(chat_id) is None:
                return None
    elif title:
        st.update_chat(chat_id, title=title)
    return chat_id


def owner_for(chat_id: str = "", task_rel: str = "",
              chat_title: str | None = None) -> tuple[str, str] | None:
    """Who owns what is drawn in this conversation. None means nobody.

    The task if the chat is one, the chat if it is loose, and nobody at all
    when there is no conversation behind it - a page written by a job that
    nobody was talking to is a real thing and is allowed to sit in no folder.

    A folder is answered by whatever object holds it, whichever of the two
    types that is. A numbered task sits straight inside a project, so the
    folder above one of its pages is a **project** as often as it is a task,
    and a project may own an artifact perfectly well (`objects.may_own`).
    Insisting on a task there is what used to mint one.
    """
    if task_rel:
        found = object_at(task_rel)
        if found is not None:
            return found
        ident = ensure_task(task_rel)
        if ident:
            return ("task", ident)
    if chat_id:
        ident = ensure_chat(chat_id, chat_title)
        if ident:
            return ("chat", ident)
    return None


def owner_now(chat_id: str = "", task_rel: str = "") -> tuple[str, str] | None:
    """Who owns what is drawn in this conversation as things stand, making nothing.

    `owner_for`'s question, asked by something that is only reading. Reading a
    canvas is not drawing on one, and until 23 September 2026 it went through
    `owner_for` and wrote down whatever it was reading: the page asking what
    was on the screen of a chat nobody had said anything in yet - New chat just
    pressed, a draft (`conversations.open_draft`) - made that chat, empty, on
    the spot. None when there is nothing yet, which has no cards.
    """
    if task_rel:
        found = object_at(task_rel)
        if found is not None:
            return found
    st = store()
    chat_id = (chat_id or "").strip()
    if chat_id and st is not None and st.get_chat(chat_id) is not None:
        return ("chat", chat_id)
    return None


# ---------------------------------------------------------------------------
# Drawing, revising and reading a card
# ---------------------------------------------------------------------------


def _body(spec: dict, after_message_id: int | None) -> str:
    """What a version holds: the card as the page draws it, and where it sits.

    The anchor travels with the body rather than in a column of its own: it is
    part of where this card belongs in the one stream of messages and cards,
    and it is the same answer for every revision of it.
    """
    return json.dumps(dict(spec, after_message_id=after_message_id))


def _spec_of(version: objects.ArtifactVersion | None) -> dict:
    if version is None or not version.body:
        return {"blocks": []}
    try:
        got = json.loads(version.body)
    except (TypeError, ValueError):
        # One unreadable row must not take the whole screen with it.
        return {"blocks": []}
    return got if isinstance(got, dict) else {"blocks": []}


def _filing_of(row: objects.Artifact) -> dict:
    """Where this card sits in the workspace, out of the one place it is written.

    `path` on the row is `<the task>/<the step>/step.md`, so the step's folder
    and the number the person says out loud are both already in it. Reading
    them off it rather than writing them into the body means filing a card is
    a row changing and not a version being added: a card that has been put on
    the record has not been revised, and the screen would otherwise say
    "v2 of 2" about a card whose words nobody touched.

    An old row that carries them in its body still answers, because the body
    is read first and this only writes over what it found.
    """
    if not row.path:
        return {}
    rel = os.path.dirname(row.path)
    number = rel.split("/")[-1].split(".")[0]
    return {"filed": number, "filed_rel": rel} if rel and number else {}


def _as_card(row: objects.Artifact, head: objects.ArtifactVersion | None) -> dict:
    """One artifact as the page and the tools want a card: spec, number, when."""
    spec = _spec_of(head)
    anchor = spec.pop("after_message_id", None)
    spec.pop("made_in", None)
    number = number_of(row.id)
    out = dict(spec,
               card_id=number if number is not None else row.id,
               at=row.created_at,
               after_message_id=anchor,
               title=spec.get("title") or row.title,
               description=spec.get("description") or "",
               version=head.version if head else row.head_version,
               versions=row.head_version)
    out.update(_filing_of(row))
    return out


def draw(spec: dict, *, chat_id: str = "", task_rel: str = "",
         chat_title: str | None = None, after_message_id: int | None = None,
         made_by_run: str | None = None) -> dict | None:
    """Put a card on the screen: one artifact, one version, one owner.

    `spec` is the card as the page draws it - title, description, blocks, and
    whatever else the thing that drew it put there, which is kept whole: a
    conflict card carries the id of the conflict it is about, and a card that
    loses it is a card whose buttons answer nothing.

    The owner is decided here and written down, rather than being a rule about
    which thread the person was standing in that nothing could revisit later.
    A card drawn in a chat a task owns belongs to that task, which is what puts
    it on that task's canvas.

    **What it does not do is write anything into the workspace.** A numbered
    step is a task of its own, and a task is made out of a chat when the person
    asks for one and at no other moment (`file_as_step`).
    """
    st = store()
    if st is None:
        return None
    owner = owner_for(chat_id, task_rel, chat_title)
    spec = dict(spec)
    title = spec.get("title") or "Rouh"
    spec["title"] = title
    spec.setdefault("description", "")
    spec["blocks"] = list(spec.get("blocks") or [])
    for _ in range(3):
        number = _allocate(st)
        try:
            row = st.create_artifact("card", title, id=f"{CARD}{number}", mime=CARD_MIME)
            break
        except Exception:
            # Somebody else has that number: a second process, or a count made
            # before a migration. Count again and take the next one.
            log.debug("card %s was taken; counting again", number, exc_info=True)
            forget_numbers()
    else:                                                    # pragma: no cover
        log.error("no free card number could be found; the card was not stored")
        return None
    if owner is not None:
        st.attach(owner[0], owner[1], "artifact", row.id)
    st.add_version(row.id, body=_body(spec, after_message_id),
                   made_by_run=_known_run(st, made_by_run))
    _made_by(st, row.id, made_by_run)
    # `filed_into` is on every card this module hands back, and it is None
    # here: drawing files nothing. `file_as_step` is the only thing that fills
    # it in, and only because somebody asked.
    return dict(_as_card(st.get_artifact(row.id) or row, st.version(row.id)),
                filed_into=None)


def keep(memory, spec: dict, *, made_by_run: str | None = None) -> tuple:
    """Store a card and give back its number and what to draw.

    The one door every card in Rouh goes through: the tool the model calls,
    a job's result, a conflict that needs a person, the gaps table, a workspace
    page put on the screen. All of them are the same thing - an output, with a
    number the person says out loud - and all of them are kept in the same
    place, or the canvas shows a card once and loses it on the next reload.

    A card and nothing else. Whether it becomes a numbered step of the task
    this thread is, is a separate question with a separate answer, and the
    person is the one who answers it (`file_as_step`).

    `memory` is handed in rather than imported, so nothing in this module
    depends on the conversation store and the two cannot import each other.
    With the object model off this falls straight through to `memory.add_card`
    and everything is exactly as it was.
    """
    title = spec.get("title") or "Rouh"
    description = spec.get("description") or ""
    if enabled():
        chat_id = memory.answering_chat()
        chat = memory.chat(chat_id) or {}
        drawn = draw(spec, chat_id=chat_id, task_rel=chat.get("task") or "",
                     chat_title=chat.get("title") if chat.get("titled") else None,
                     after_message_id=memory.last_message_id(chat_id),
                     made_by_run=made_by_run)
        if drawn is not None:
            drawn.pop("filed_into", None)
            return drawn["card_id"], drawn
    card_id = memory.add_card(title, description, spec)
    return card_id, dict(spec, card_id=card_id, at=time.time())


def revise(which, *, title: str | None = None, description: str | None = None,
           blocks=None, made_by_run: str | None = None, root: str = "",
           made_in: int | None = None) -> dict | None:
    """Add a version to an artifact and move its head to it.

    History is never overwritten: every revision is a row of its own, the one
    before it stays readable by asking for it by number, and what is on disk is
    written again from the version that has just been added. Returns None when
    there is no such artifact.
    """
    st = store()
    if st is None:
        return None
    ident = _ident(which)
    row = st.get_artifact(ident)
    if row is None:
        return None
    was = _spec_of(st.version(ident))
    anchor = was.get("after_message_id")
    spec = {
        "title": title if title is not None else (was.get("title") or row.title),
        "description": description if description is not None
        else (was.get("description") or ""),
        "blocks": list(blocks) if blocks is not None else (was.get("blocks") or []),
    }
    spec.update(_place_of(was))
    if made_in is not None:
        # The try of the exchange that revised it, so a branch of the
        # conversation that does not hold that try shows the card as it was
        # before (`on_branch`).
        spec["made_in"] = int(made_in)
    made = st.add_version(ident, body=_body(spec, anchor),
                          made_by_run=_known_run(st, made_by_run))
    _made_by(st, ident, made_by_run)
    if title is not None and title != row.title:
        st.update_artifact(ident, title=title)
    # The file on disk is derived, so it is written again from what the row now
    # says rather than being left saying what it used to.
    if row.path and root:
        try:
            steps.rewrite_step(root, os.path.dirname(row.path), spec["title"],
                               spec["blocks"])
        except (steps.Refused, OSError):
            log.exception("the step behind %s could not be written again", ident)
    return _as_card(st.get_artifact(ident) or row, made)


def _place_of(spec: dict) -> dict:
    """Where a card sits, besides the message it came after (`place`), to be
    carried over to a new version of it: a card changed where it stands keeps
    its place under the call that drew it."""
    return {key: spec[key] for key in ("after_call", "in_answer", "placed_at")
            if key in spec}


def place(which, *, after_message_id: int | None, after_call: str | None = None,
          in_answer: bool = False, held_by=None) -> bool:
    """Write down where a card now sits in its conversation: where it was just
    put on the screen, at the end of it.

    Petar, 5 October 2026 (fr_6b1852e8f32e): "everything is recorded
    chronologically in chat. The later it comes the later it appears", and
    "everything we see in the chat during chatting should appear the same way
    when we refresh the page". A card revised, or asked for again, is drawn at
    the end of the conversation (`renderCard` in the page), and until then a
    reload put it back where it was first drawn - a whole exchange up, above
    the words that were written under it. So every time a card is put at the
    end, its place is moved there too.

    `after_call` is the call whose line it sits under, inside the answer that
    drew it: the words written after it are below it, on the screen and read
    back. `in_answer` is a card a turn put inside its answer with no call to
    go by, which sits after what `after_message_id` drew. Its head version is written over rather than added to, because
    where a card sits is an ordering fact and not a change to what it says.

    `held_by(message_id)` says whether a message is one of this chat's. A
    card that was drawn in another chat stays that chat's: moving its anchor
    would take it out of the conversation it was drawn in.
    """
    st = store()
    if st is None:
        return False
    ident = _ident(which)
    head = st.version(ident)
    if head is None:
        return False
    spec = _spec_of(head)
    was = spec.pop("after_message_id", None)
    if was is not None and held_by is not None and not held_by(int(was)):
        return False
    if was is None and held_by is not None:
        return False
    spec.pop("after_call", None)
    spec.pop("in_answer", None)
    if after_call:
        spec["after_call"] = str(after_call)
    elif in_answer:
        spec["in_answer"] = True
    spec["placed_at"] = time.time()
    return st.rewrite_version(ident, body=_body(spec, after_message_id),
                              version=head.version) is not None


def amend(which, *, title: str | None = None, description: str | None = None,
          blocks=None, root: str = "") -> dict | None:
    """Write over the card where it stands, adding no version to it.

    `revise` above is what almost everything wants: a change to a card is a
    new version of it and the one before stays readable. This is for the one
    case where it is not - a card the person is typing into
    (`rouh/composing.py`), whose every saved keystroke would otherwise be a
    version - and it is deliberately the narrow door: same number, same place
    in the conversation, same version number, different words.
    """
    st = store()
    if st is None:
        return None
    ident = _ident(which)
    row = st.get_artifact(ident)
    if row is None:
        return None
    was = _spec_of(st.version(ident))
    anchor = was.get("after_message_id")
    spec = {
        "title": title if title is not None else (was.get("title") or row.title),
        "description": description if description is not None
        else (was.get("description") or ""),
        "blocks": list(blocks) if blocks is not None else (was.get("blocks") or []),
    }
    spec.update(_place_of(was))
    made = st.rewrite_version(ident, body=_body(spec, anchor))
    if made is None:
        return None
    if title is not None and title != row.title:
        st.update_artifact(ident, title=title)
    if row.path and root:
        try:
            steps.rewrite_step(root, os.path.dirname(row.path), spec["title"],
                               spec["blocks"])
        except (steps.Refused, OSError):
            log.exception("the step behind %s could not be written again", ident)
    return _as_card(st.get_artifact(ident) or row, made)


def read(which, version: int | None = None) -> dict | None:
    """One artifact as a card, at its head or at a version asked for by number."""
    st = store()
    if st is None:
        return None
    ident = _ident(which)
    row = st.get_artifact(ident)
    if row is None:
        return None
    got = st.version(ident, version)
    if got is None:
        return None
    return _as_card(row, got)


def about(which, *, root: str = "") -> dict | None:
    """One artifact as the viewer that opens it needs it.

    `read` above answers the card and nothing else, which is everything for a
    card and not enough for the rest of the table. A page, a document, a file
    or a picture is bytes on disk named by `path`, and its version carries no
    blocks at all, so a viewer handed only the card would draw an empty box and
    say nothing about why. Here the row comes with it - what kind of thing it
    is, where its bytes are, and whether they are still there - so the screen
    can either draw the thing or say in a sentence what it is instead.

    None when there is no such artifact, which is what a link to one since
    deleted comes back as.
    """
    st = store()
    if st is None:
        return None
    ident = _ident(which)
    row = st.get_artifact(ident)
    if row is None:
        return None
    head = st.version(ident)
    rel = str(row.path or "")
    where = os.path.join(root, *rel.split("/")) if root and rel else ""
    return {"id": row.id, "kind": row.kind, "title": row.title,
            "path": rel, "mime": row.mime or "",
            # Whether the bytes are really there. A row whose folder was moved
            # or deleted still names where it used to be, and "it is not there
            # any more" is a different sentence from "Rouh keeps this one as a
            # file", so the screen is told which of the two this is.
            "on_disk": bool(where) and os.path.isfile(where),
            # A run's "What it changed" is plain text - its commits and the
            # files it touched (`owning.record_diff`) - with no blocks and no
            # file, so its words are what there is to show.
            "text": (head.body or "") if row.kind == "diff" and head else "",
            "card": _as_card(row, head)}


def history(chat_id: str = "", task_rel: str = "", before=None,
            limit: int = 10) -> list[dict]:
    """A page of one conversation's canvas, newest first, each card whole.

    Which cards a conversation shows is the same question as who owns them: a
    chat that is a task shows what that task owns, and a loose chat shows its
    own. Nothing has to be filtered twice or kept in step, because there is
    only one answer to who a card belongs to.
    """
    st = store()
    if st is None:
        return []
    owner = owner_now(chat_id, task_rel)
    if owner is None:
        return []
    edge = _ident(before) if before not in (None, "") else None
    rows = st.heads(kind="card", owner=owner, before=edge, limit=max(1, int(limit)))
    return [on_branch(row, head) for row, head in rows]


# ---------------------------------------------------------------------------
# A card on a branch of its conversation, and its versions one at a time
# ---------------------------------------------------------------------------
#
# Petar, 4 November 2026: "the canvas block changed from one thing to another
# as a result. now I see v2 of 2, but it is not a separate canvas so I can
# click the previous number". A card revised by a turn that is later answered
# again, or whose question is edited, was left at the revision on every branch
# of the conversation. Each version a turn made now says which try made it
# (`revise`, `made_in`), and a card is drawn as the newest version whose try is
# on the branch being read: the branch that never revised it shows it as it was
# before. Nothing is written by reading it so, and every version stays.

#: What says where a card is and what it is, from its head, whichever version is read.
_HEAD_KEYS = ("card_id", "at", "after_message_id", "after_call", "in_answer", "placed_at",
              "versions", "filed", "filed_rel")


def _made_in(body: str | None) -> int | None:
    """The try that made a version, or None for one made by nothing of a chat's."""
    try:
        spec = json.loads(body) if body else None
        got = spec.get("made_in") if isinstance(spec, dict) else None
        return int(got) if got is not None else None
    except (TypeError, ValueError):
        return None


def _reading_as(card: dict, version: objects.ArtifactVersion) -> dict:
    """`card`, its head as `_as_card` gives it, reading as another of its versions: that
    version's words, and the head's number, place and count."""
    spec = _spec_of(version)
    for key in ("after_message_id", "made_in", "after_call", "in_answer", "placed_at"):
        spec.pop(key, None)
    out = dict(spec, title=spec.get("title") or card.get("title"),
               description=spec.get("description") or "")
    out.update({k: card[k] for k in _HEAD_KEYS if k in card})
    out["version"] = version.version
    return out


def _placed_on_branch(card: dict) -> dict:
    """A card whose message is on a branch of the conversation not being read, put after
    the last message of the branch being read that comes before it: where it would be had
    the conversation always been this branch, rather than above everything."""
    at = card.get("after_message_id")
    if at is None:
        return card
    from .models.memory import TranscriptMessage
    from .memory import _exchange

    try:
        row = (TranscriptMessage.objects.filter(id=int(at)).annotate(exchange=_exchange())
               .values("live", "session_id", "exchange").first())
    except (TypeError, ValueError):
        return card
    if row is None or row["live"]:
        return card
    near = (TranscriptMessage.objects.filter(session_id=row["session_id"], live=True)
            .annotate(exchange=_exchange()).filter(exchange__lte=row["exchange"])
            .order_by("-exchange", "-id").values_list("id", flat=True).first())
    out = dict(card, after_message_id=near)
    out.pop("after_call", None)
    out.pop("in_answer", None)
    return out


def on_branch(row: objects.Artifact, head: objects.ArtifactVersion | None) -> dict:
    """A card as the branch of its conversation being read has it: the newest version
    made on that branch, or by nothing of a chat's, else the first, in its place on it."""
    return _placed_on_branch(_version_on_branch(row, head))


def _version_on_branch(row: objects.Artifact, head: objects.ArtifactVersion | None) -> dict:
    card = _as_card(row, head)
    st = store()
    if st is None or row.head_version <= 1 or head is None:
        return card
    versions = st.versions(row.id)
    made = {v.version: _made_in(v.body) for v in versions}
    tries = {m for m in made.values() if m is not None}
    if not tries:
        return card
    from .models.memory import TranscriptMessage

    live = set(TranscriptMessage.objects.filter(id__in=tries, live=True)
               .values_list("id", flat=True))
    for v in reversed(versions):
        if v.version > head.version:
            continue
        if v.version == 1 or made[v.version] is None or made[v.version] in live:
            return card if v.version == head.version else _reading_as(card, v)
    return card


def made_in_any(tries, chat_id: str = "") -> list[dict]:
    """Every card with a version made by one of these tries, as the branch being read has
    it now: what a tab is sent again when those tries came on or off the screen."""
    tries = [int(t) for t in (tries or [])]
    st = store()
    if st is None or not tries:
        return []
    from django.db.models import Q

    q = Q()
    for t in tries:
        q |= Q(body__contains=f'"made_in": {t},') | Q(body__contains=f'"made_in": {t}}}')
    from .models.objects import ArtifactVersion

    ids = sorted(set(ArtifactVersion.objects.filter(q).values_list("artifact_id", flat=True)))
    out = []
    for ident in ids:
        row = st.get_artifact(ident)
        if row is None or row.kind != "card":
            continue
        out.append(on_branch(row, st.version(ident)))
    return out


def at_version(which, version: int) -> dict | None:
    """One card reading as one of its versions, in its place, for the arrows on its head.
    Only read: the head stays where it is and every version is kept."""
    st = store()
    if st is None:
        return None
    ident = _ident(which)
    row = st.get_artifact(ident)
    if row is None or row.kind != "card":
        return None
    got = st.version(ident, int(version))
    if got is None:
        return None
    head = st.version(ident)
    return _reading_as(_as_card(row, head), got)


# ---------------------------------------------------------------------------
# Which chat a card was drawn in
# ---------------------------------------------------------------------------
#
# Owning a card and having drawn it are two different facts. A card drawn in a
# chat a task owns is the task's (`owner_for`), which is what puts it on the
# task's canvas and on its page, and the task may hold several chats. Which of
# them drew it is written down all the same: every version carries the message
# it came after (`_body`), and that message is a row of exactly one chat's
# transcript. That, and nothing guessed from a clock, is how a card is found
# in its chat again.

#: The most cards one chat's Cards lays out. A long conversation can have drawn
#: hundreds, and every one is drawn in full; past this it shows the newest.
MOST_DRAWN = 100


def _anchor(body: str | None) -> int | None:
    """The message a card's version says it came after, or None."""
    try:
        spec = json.loads(body) if body else None
    except (TypeError, ValueError):
        return None
    at = spec.get("after_message_id") if isinstance(spec, dict) else None
    try:
        return int(at) if at is not None else None
    except (TypeError, ValueError):
        return None


def chats_drawn_in(bodies: dict[str, str | None]) -> dict[str, str]:
    """Which chat each of these cards was drawn in, where that is written down.

    `bodies` is each card's head version by its id. A card with no anchor, or
    whose message is gone, is left out rather than guessed at: a card a job
    drew with nobody talking, or one drawn before anchors were kept, was
    drawn in no chat anybody can open. One query for all of them.
    """
    anchors = {ident: at for ident, body in bodies.items()
               if (at := _anchor(body)) is not None}
    if not anchors:
        return {}
    from .models.memory import TranscriptMessage

    said = dict(TranscriptMessage.objects.filter(id__in=set(anchors.values()))
                .values_list("id", "session_id"))
    return {ident: str(said[at]) for ident, at in anchors.items() if said.get(at)}


def mark_drawn_here(cards: list[dict], chat_id: str) -> list[dict]:
    """Each card marked `here` when it was drawn in this chat.

    A task's chat reads back every card its task owns, and most of those may
    have been drawn in another of its chats; the page opens the canvas by
    itself only for a chat that drew cards of its own. One query for the page.
    """
    chat_id = (chat_id or "").strip()
    anchors = {}
    for card in cards:
        try:
            anchors[id(card)] = int(card.get("after_message_id"))
        except (TypeError, ValueError):
            continue
    said = {}
    if chat_id and anchors:
        from .models.memory import TranscriptMessage

        said = dict(TranscriptMessage.objects.filter(id__in=set(anchors.values()))
                    .values_list("id", "session_id"))
    for card in cards:
        at = anchors.get(id(card))
        card["here"] = bool(chat_id and at is not None and str(said.get(at) or "") == chat_id)
    return cards


def drawn_in(chat_id: str, task_rel: str = "") -> dict:
    """Every card drawn in one chat, oldest first, each whole: its Cards.

    Petar, 24 September 2026, about the cards on task 61's page: "those cards
    - do they belong to a chat? if so, remove them from the directly in this
    task. they will be found in the chat. the chat three dots can have an
    extra option "Artifacts" or "Cards" and when I click it, I see the
    rendering of all the artifacts in that chat ever lined up in the canvas."

    So this is what that item lays out: the cards the chat owns itself (a
    loose chat's, and one filed under a task after it had drawn them), and
    the cards its task owns whose anchor is one of this chat's messages. A
    card another chat of the same task drew is that chat's, not this one's.

    `{"cards": [...], "total": n}`: at most `MOST_DRAWN` of them, the newest,
    and how many there are in all.
    """
    st = store()
    chat_id = (chat_id or "").strip()
    if st is None or not chat_id:
        return {"cards": [], "total": 0}
    found = {row.id: (row, head)
             for row, head in st.heads(kind="card", owner=("chat", chat_id),
                                       limit=_MOST_CARDS)}
    owner = owner_now(chat_id, task_rel)
    if owner is not None and owner != ("chat", chat_id):
        rows = st.heads(kind="card", owner=owner, limit=_MOST_CARDS)
        where = chats_drawn_in({row.id: head.body if head else None for row, head in rows})
        found.update((row.id, (row, head)) for row, head in rows
                     if where.get(row.id) == chat_id)
    ordered = sorted(found.values(), key=lambda pair: (pair[0].created_at, pair[0].id))
    return {"cards": [_as_card(row, head) for row, head in ordered[-MOST_DRAWN:]],
            "total": len(ordered)}


def find(query: str = "", limit: int = 20) -> list[dict]:
    """Every card there has ever been, newest first, narrowed by words in it.

    The whole screen and not one chat's: the person asking about "that table of
    jobs" is not necessarily standing where it was drawn, and the number is
    what brings it back wherever they are.
    """
    st = store()
    if st is None:
        return []
    rows = st.heads(kind="card", matching=query or None, limit=max(1, int(limit)))
    return [_as_card(row, head) for row, head in rows]


# ---------------------------------------------------------------------------
# Reading anything back, whole
# ---------------------------------------------------------------------------
#
# `read` above answers a card. These answer everything in the table - a card,
# a page or a document a job wrote into the workspace, a run's changes - for a
# turn that has to know what something said rather than show it. Nothing here
# writes: no version is added, no head moves and nothing is sent to a page.

#: Files whose bytes are words, and so are read out rather than described.
_TEXT_TYPES = ("text/", "application/json", "application/xml", "image/svg+xml",
               "application/javascript")
_TEXT_ENDINGS = (".html", ".htm", ".md", ".txt", ".json", ".csv", ".tsv", ".xml",
                 ".svg", ".yml", ".yaml", ".py", ".js", ".css")


def _owner_said(st: objects.ObjectStore, artifact_id: str) -> str:
    """What it belongs to, by the name the person knows it by: 'task 74 Email'."""
    owner = st.owner_of("artifact", artifact_id)
    if not owner:
        return ""
    kind, ident = owner
    got = {"task": st.get_task, "project": st.get_project, "chat": st.get_chat,
           "run": st.get_run}.get(kind, lambda _: None)(ident)
    if got is None:
        return f"{kind} {ident}"
    number = getattr(got, "number", None)
    title = getattr(got, "title", None) or getattr(got, "folder", "") or ""
    name = " ".join(str(bit) for bit in (number, title) if bit)
    if kind in ("chat", "run"):
        return f'{kind} {ident} "{title}"' if title else f"{kind} {ident}"
    return f"{kind} {name}" if name else f"{kind} {ident}"


def handle_of(row: objects.Artifact) -> str:
    """What to ask for it by: a card's number, anything else's id."""
    number = number_of(row.id) if row.kind == "card" else None
    return str(number) if number is not None else row.id


def find_any(query: str = "", kind: str | None = None, limit: int = 20) -> list[dict]:
    """Everything Rouh has produced, newest first, narrowed by words and kind.

    The words match the title, the head's body (a card's blocks, a run's
    changes) and where its file is in the workspace.
    """
    st = store()
    if st is None:
        return []
    kind = kind if kind in objects.ARTIFACT_KINDS else None
    top = max(1, int(limit))
    rows = st.heads(kind=kind, matching=query or None, limit=top)
    said = (query or "").strip().lower()
    if said and len(rows) < top:
        seen = {row.id for row, _ in rows}
        for row in st.list_artifacts(kind=kind, limit=_MOST_CARDS):
            if len(rows) >= top:
                break
            if row.id not in seen and said in str(row.path or "").lower():
                rows.append((row, st.version(row.id)))
        rows.sort(key=lambda pair: pair[0].created_at, reverse=True)
    out = []
    for row, head in rows:
        description = _spec_of(head).get("description", "") if row.kind == "card" else ""
        out.append({"handle": handle_of(row), "id": row.id, "kind": row.kind,
                    "title": row.title, "description": description,
                    "path": row.path or "", "at": row.created_at,
                    "versions": row.head_version, "owner": _owner_said(st, row.id)})
    return out


def by_path(rel: str) -> str | None:
    """The artifact whose file is at this workspace path, or in this folder."""
    st = store()
    if st is None:
        return None
    rel = str(rel or "").strip().strip("/")
    if rel.startswith("workspace/"):
        rel = rel[len("workspace/"):]
    if not rel:
        return None
    best = None
    for row in st.list_artifacts(limit=_MOST_CARDS):
        path = str(row.path or "")
        if path == rel:
            return row.id
        if best is None and os.path.dirname(path) == rel:
            best = row.id
    return best


def _inside(root: str, rel: str) -> str:
    """The file `rel` names under `root`, or "" when it would leave it."""
    if not root or not rel:
        return ""
    base = os.path.realpath(root)
    where = os.path.realpath(os.path.join(base, *rel.split("/")))
    return where if where.startswith(base + os.sep) else ""


def _is_text(path: str, mime: str) -> bool:
    return (mime or "").startswith(_TEXT_TYPES) or path.lower().endswith(_TEXT_ENDINGS)


def contents(which, version: int | None = None, *, root: str = "") -> dict | None:
    """Everything one artifact holds, at its head or at a version asked for.

    None when there is no such artifact. A version that does not exist comes
    back with `missing_version` set, so the caller can say which it has.

    `card` is a card's spec, whole. `text` is a run's changes, or the words of
    a page or a document as its file holds them now. A picture or any other
    file that is not words is described by `size` and `mime` instead.
    """
    st = store()
    if st is None:
        return None
    ident = _ident(which)
    row = st.get_artifact(ident)
    if row is None:
        return None
    out = {"id": row.id, "handle": handle_of(row), "kind": row.kind, "title": row.title,
           "path": row.path or "", "mime": row.mime or "", "at": row.created_at,
           "versions": row.head_version, "version": version or row.head_version,
           "owner": _owner_said(st, row.id), "card": None, "text": None,
           "size": None, "note": "", "missing_version": False}
    got = st.version(ident, version)
    if got is None and version is not None:
        out["missing_version"] = True
        return out
    if row.kind == "card":
        out["card"] = _as_card(row, got)
        return out
    if got is not None and got.body:
        out["text"] = got.body
        return out
    rel = str(row.path or "")
    if version is not None and version != row.head_version:
        out["note"] = (f"Version {version} kept no words of its own: only the file "
                       "on disk is kept, and it holds the newest version.")
        return out
    where = _inside(root, rel)
    if not where or not os.path.isfile(where):
        out["note"] = ("Its file is not in the workspace any more" if rel else
                       "It has no file and no words were kept for it") + "."
        return out
    out["size"] = os.path.getsize(where)
    if _is_text(rel, row.mime or ""):
        with open(where, encoding="utf-8", errors="replace") as fh:
            out["text"] = fh.read()
    else:
        out["note"] = "It is not words: a file of this type is described, not read out."
    return out


# ---------------------------------------------------------------------------
# Filing, when the person asks for it
# ---------------------------------------------------------------------------


def file_as_step(which, *, root: str = "") -> dict | None:
    """Write a card into the task that owns it, as that task's next numbered step.

    The one door for "put that on the record", and it is only ever opened by
    something the person did: the button on the card, or the `make_a_task`
    tool when they ask out loud. Nothing on this machine calls it by itself.

    Where it goes is the card's own owner and not a folder handed in, so a card
    cannot be filed into a task that does not own it. The step's number, its
    row, its folder and its sidecar all come from `steps.file_step`, which is
    the one create path; the card then carries the number it was given, so the
    card on screen says `Filed as 19-17` and opens it.

    None when there is no such card. A card that is already filed is handed
    back as it is rather than written a second time, and a card no task owns
    comes back with `filed_into` empty: there is nowhere to put it, which is
    not an error and is what a loose chat's cards are.
    """
    st = store()
    if st is None:
        return None
    ident = _ident(which)
    row = st.get_artifact(ident)
    if row is None:
        return None
    head = st.version(ident)
    spec = _spec_of(head)
    if spec.get("filed") or row.path:
        return dict(_as_card(row, head), filed_into=None)
    owner = st.owner_of("artifact", ident)
    task = st.get_task(owner[1]) if owner is not None and owner[0] == "task" else None
    if task is None or not task.folder:
        return dict(_as_card(row, head), filed_into=None)
    filed = _write_out(st, row, task.folder, spec.get("title") or row.title,
                       spec.get("blocks") or [], root)
    if not filed:
        return dict(_as_card(row, head), filed_into=None)
    # Nothing is added to the card's history: it says what it always said, and
    # where it now sits is read off the row it was written on (`_filing_of`).
    return dict(_as_card(st.get_artifact(ident) or row, head), filed_into=filed)


# ---------------------------------------------------------------------------
# Ownership, changed afterwards
# ---------------------------------------------------------------------------


def promote(chat_id: str, task_rel: str, root: str = "") -> int:
    """A loose chat became a task: its cards move with it, and are filed.

    This is the thing the old model could not do. What a card belonged to was
    decided the moment it was drawn and was a rule rather than a row, so a
    conversation that turned out to be task 41 left everything drawn in it
    behind. Here it is one `owns` row per card, taken from the chat and given
    to the task, and the numbered steps are then written out from the rows,
    oldest first, because the folders are the derived half.
    """
    st = store()
    if st is None or not chat_id or not task_rel:
        return 0
    into = ensure_task(task_rel)
    if into is None:
        return 0
    moved = 0
    for row, head in reversed(st.heads(kind="card", owner=("chat", chat_id),
                                       limit=_MOST_CARDS)):
        st.attach("task", into, "artifact", row.id)
        moved += 1
        if row.path or not root:
            continue
        spec = _spec_of(head)
        _write_out(st, row, task_rel, spec.get("title") or row.title,
                   spec.get("blocks") or [], root)
    if moved:
        log.info("%d card(s) moved from chat %s to %s", moved, chat_id, task_rel)
    return moved


def fork(from_chat: str, from_task: str, into_chat: str, *, until: float = 0.0,
         became: dict | None = None) -> int:
    """Copy a chat's canvas into the branch taken off it.

    A branch whose screen is empty is not the same conversation seen again. The
    copies are artifacts of their own, owned by the new chat, each with the one
    version the original's head had: a branch is a place to go another way, not
    a second name for the same rows.
    """
    st = store()
    if st is None or not into_chat:
        return 0
    owner = owner_now(from_chat, from_task)
    if owner is None:
        return 0
    into = ensure_chat(into_chat)
    if into is None:
        return 0
    became = became or {}
    made = 0
    for row, head in reversed(st.heads(kind="card", owner=owner, limit=_MOST_CARDS)):
        # Up to the moment the copy goes to, which is the timestamp of the last
        # message carried over. A chat with nothing said in it carries nothing,
        # which is what the transcript does too.
        if row.created_at > until:
            continue
        spec = _spec_of(head)
        anchor = spec.pop("after_message_id", None)
        # The anchor names a row of the chat this was branched from, so it is
        # translated to the copy of that message. One that was not carried over
        # keeps no anchor and falls back to its timestamp, which is what the
        # transcript did before there were anchors at all.
        anchor = became.get(int(anchor)) if anchor is not None else None
        # Filed into a task is a fact about the original, not about the copy:
        # the branch has no folder of its own until it becomes something.
        spec.pop("filed", None)
        spec.pop("filed_rel", None)
        number = _allocate(st)
        try:
            copy = st.create_artifact("card", row.title, id=f"{CARD}{number}",
                                      mime=CARD_MIME, created_at=row.created_at)
        except Exception:
            forget_numbers()
            log.debug("a card number was taken while branching", exc_info=True)
            continue
        st.attach("chat", into, "artifact", copy.id)
        st.add_version(copy.id, body=_body(spec, anchor))
        made += 1
    return made


# ---------------------------------------------------------------------------
# The other kinds: a page, a document, anything loose
# ---------------------------------------------------------------------------


def loose(kind: str, title: str, *, body: str | None = None, path: str | None = None,
          mime: str | None = None, made_by_run: str | None = None
          ) -> objects.Artifact | None:
    """An artifact owned by nobody, like a file in Drive that sits in no folder.

    A first-class state and not a mistake: something is made before anybody has
    decided where it belongs, and being made to file it first is how things
    end up in the wrong place. `attach` gives it an owner later, whenever
    somebody decides.
    """
    st = store()
    if st is None:
        return None
    row = st.create_artifact(kind, title, path=path, mime=mime)
    st.add_version(row.id, body=body, made_by_run=_known_run(st, made_by_run))
    _made_by(st, row.id, made_by_run)
    return row


def register_step(root: str, step_rel: str, *, task_rel: str = "",
                  title: str = "", made_by_run: str | None = None) -> str | None:
    """A step folder already on disk becomes the artifact row it always was.

    The pages a background job built - one `index.html` per step - were a file
    and nothing else, so nothing could say who made one, what it belonged to or
    what it said last week. This is how one of them joins the model without
    being rewritten: the row is made, the task owns it, and `path` names the
    bytes that are already there. The file is not touched.

    Idempotent: a step that is already a row is left exactly as it is, so this
    can be called from wherever a step is served or listed.
    """
    st = store()
    step_rel = (step_rel or "").strip().strip("/")
    if st is None or not step_rel:
        return None
    base = os.path.join(root, *step_rel.split("/")) if root else ""
    page = os.path.join(base, "index.html")
    doc = os.path.join(base, steps.STEP_FILE)
    if os.path.isfile(doc):
        kind, rel, mime = "doc", f"{step_rel}/{steps.STEP_FILE}", "text/markdown"
    elif os.path.isfile(page):
        kind, rel, mime = "page", f"{step_rel}/index.html", "text/html"
    else:
        return None
    # The bytes may already be an artifact's: a card filed into this task was
    # written out into this very folder, and that card is the row those bytes
    # belong to. One file, one row.
    already = st.artifact_at(rel)
    if already is not None:
        return already.id
    ident = "step-" + step_rel.replace("/", ":")
    if st.get_artifact(ident) is not None:
        return ident
    if not task_rel:
        task_rel = "/".join(step_rel.split("/")[:-1])
    try:
        st.create_artifact(kind, title or step_rel.split("/")[-1], id=ident,
                           path=rel, mime=mime)
    except Exception:
        log.debug("the step row %s was already there", ident, exc_info=True)
        return ident if st.get_artifact(ident) is not None else None
    owner = owner_for(task_rel=task_rel)
    if owner is not None:
        st.attach(owner[0], owner[1], "artifact", ident)
    # The bytes are on disk and `path` names them, so the version records that
    # this is where this revision was, rather than copying a page into a row.
    st.add_version(ident, body=None, made_by_run=_known_run(st, made_by_run))
    _made_by(st, ident, made_by_run)
    return ident


def register_tree_pages(root: str) -> dict:
    """Every page the workspace has built, taken in as the artifact it is.

    **The answer to "are the html visual explainers artifacts, or just html
    files".** They are artifacts, and they always were as far as this module is
    concerned: `register_step` above has made one an `artifact` row of kind
    `page` since step four, with `path` naming the bytes already on disk and
    the task that owns the folder owning the row. What was missing is that
    nothing ever called it except a reader opening one, so on 22 September 2026
    this machine had 145 `index.html` pages in the workspace and **nought**
    rows of kind `page` to show for them - which is why a project's own page
    could list its chats and its runs and had nothing to say about the twenty
    pages built inside it.

    So they take themselves in, the same way the rows and the content index do
    (`objecttree.ensure_imported`, `ensure_indexed`): once, on a thread at
    start-up, never on a request. Idempotent - `register_step` leaves a folder
    that is already a row exactly as it is - and it never writes a file or
    rewrites one. A page is a file in git and stays one; the row is how the
    rest of Rouh can find it.
    """
    st = store()
    counts = {"looked": 0, "kept": 0}
    if st is None or not root or not os.path.isdir(root):
        return counts
    for row in st.objects():
        folder = str(row.get("folder") or "").strip("/")
        if not folder:
            continue
        counts["looked"] += 1
        try:
            if register_step(root, folder, title=str(row.get("title") or "")):
                counts["kept"] += 1
        except Exception:
            # One unreadable folder is never a reason to stop: this is derived
            # and the next start-up tries it again.
            log.debug("the page under %s could not be taken in", folder, exc_info=True)
    return counts


# ---------------------------------------------------------------------------
# The migration
# ---------------------------------------------------------------------------


def migrate(rows) -> int:
    """Bring the screen history into this table, keeping every number.

    `rows` are `memory.all_cards()`: every card there has ever been, oldest
    first, with the chat it was drawn in and that chat's task. Each becomes an
    artifact whose id carries the number it already had, one version holding
    exactly what was drawn, and an owner - the task if its chat is one, the
    chat if not.

    Nothing already shown may be lost, so this never writes a step folder: a
    card that was filed when it was drawn says so in its spec, and that folder
    is where it has been all along. It only records the path.

    Idempotent, and resumable: a card that is already here is skipped, so a
    migration cut off half way finishes on the next start.
    """
    st = store()
    if st is None:
        return 0
    done = 0
    for row in rows:
        ident = f"{CARD}{int(row['id'])}"
        if st.get_artifact(ident) is not None:
            continue
        spec = row.get("spec")
        if not isinstance(spec, dict):
            spec = {"blocks": []}
        title = spec.get("title") or row.get("title") or "Rouh"
        spec = dict(spec, title=title,
                    description=spec.get("description") or row.get("description") or "")
        rel = spec.get("filed_rel") or ""
        try:
            made = st.create_artifact(
                "card", title, id=ident, mime=CARD_MIME,
                path=f"{rel}/{steps.STEP_FILE}" if rel else None,
                created_at=float(row.get("ts") or time.time()))
        except Exception:
            log.exception("card %s could not be migrated", row.get("id"))
            continue
        owner = owner_for(str(row.get("session_id") or ""),
                          str(row.get("task") or ""),
                          row.get("chat_title"))
        if owner is not None:
            st.attach(owner[0], owner[1], "artifact", made.id)
        st.add_version(made.id, body=_body(spec, row.get("after_message_id")))
        done += 1
    if done:
        forget_numbers()
        log.info("%d card(s) of the screen history became artifacts", done)
    return done


# ---------------------------------------------------------------------------
# The plumbing
# ---------------------------------------------------------------------------


def _ident(which) -> str:
    """A card number, or an artifact id, as an artifact id."""
    if isinstance(which, int):
        return f"{CARD}{which}"
    text = str(which or "").strip()
    return f"{CARD}{text}" if text.isdigit() else text


def _known_run(st: objects.ObjectStore, run_id: str | None) -> str | None:
    """A run id the register has heard of, or None.

    A version must not fail to be written because the run that wrote it was
    never registered: what is lost then is the body, and what is gained is a
    name against it.
    """
    if not run_id:
        return None
    return run_id if st.get_run(run_id) is not None else None


def _made_by(st: objects.ObjectStore, artifact_id: str, run_id: str | None) -> None:
    """Record that this run had a hand in this artifact. Many to many."""
    if not run_id:
        return
    try:
        st.add_ref("made", "run", run_id, "artifact", artifact_id)
    except objects.Refused:
        # A run nobody registered. The version still has its body, which is
        # what matters; the link is a note about who drew it.
        log.debug("no run %s to link to %s", run_id, artifact_id)


def _write_out(st: objects.ObjectStore, row: objects.Artifact, task_rel: str,
               title: str, blocks, root: str) -> dict | None:
    """Write a card into its task as the next numbered step, and remember where.

    The folder is the derived half and this row is the truth, so the path goes
    on the row the moment the bytes exist. A workspace that is not here means
    no folder and no number, and never means no card.

    Its two callers are `file_as_step` and `promote`, and both of them are the
    person asking for numbered work. Nothing else may call it.
    """
    if not root or not task_rel or not os.path.isdir(root):
        return None
    try:
        filed = steps.file_step(root, task_rel, title, blocks)
    except (steps.Refused, OSError):
        log.exception("the card could not be filed into %s", task_rel)
        return None
    st.update_artifact(row.id, path=f"{filed['rel']}/{steps.STEP_FILE}")
    return filed
