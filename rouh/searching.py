"""Search over everything, as one question and one list.

The person asked for it on 22 September 2026: a box over the whole screen, a
row of pills under it - All, Chats, Tasks, Projects, Artifacts, Runs - and
one line per result with the type, the name, a little of what matched and the
date it was last worked on. On 24 September 2026 a seventh pill joined them,
Files: "the files I give it are not searchable ... show original file".

**One list, not five.** Somebody looking for "laptop" wants the chat, the task
and the run called that, ranked against each other. So there is one query,
`ObjectStore.find` in `rouh/objects.py`, which asks all five tables at once
and hands back rows in one shape; the pills narrow what is already found
rather than asking a different question, which is why pressing one is instant
and never turns up something All did not have.

**Nothing is indexed here.** The words already exist: a chat is its messages,
a run is its brief and the line it is showing, an artifact is the body of its
head version, and a project and a task are the files in their folders, which
`objecttree.reindex` already keeps in the derived content index the object
index is drawn from (`content_file`, and the full-text vector PostgreSQL keeps
of it). Adding a sixth copy of the same words would be one more thing to drift.

**A file the person uploaded is the one exception, and not a copy made here.**
Its words are locked inside a PDF or a .docx until something reads them out,
so `rouh/uploads.py` does that once, keeps the Markdown beside the file, and
indexes it (`uploaded_file`). `uploads.find` hands its hits back in the same
shape as the store's, and they are ranked in with them (`objects.ranked`). A
file is not one of the five objects: it has no address of its own and no row
menu beyond opening it, and opening it is the file itself, never its words.

What this module adds on top of that one query is the three things a row on the
screen needs and the database has no opinion about:

* **a snippet**, cut around the first word that matched, with an ellipsis
  either side, and readable rather than raw - a card's body is the JSON spec it
  is drawn from, and the person wants the description, not the braces;
* **how to open it**, which is different for each of the five and is decided
  here rather than in the browser, so the page has no copy of the rules to fall
  behind: a chat is opened, a task is its folder on the canvas, an artifact is
  the step it was filed as or the card itself;
* **an address**, so "open in new tab" is a real link. The scheme is
  `rouh/addressing.py` - `/chat/<id>`, `/task/<its folder>` and so on - and
  `find_one` below is what the page asks to turn one back into the same open
  instruction it would have had from a result row. It is the same call for a
  row's own menu, for a link somebody was sent, and for Back.

The rows and the actions on them
--------------------------------

Pin, rename and delete are in `rouh/owning.py` with the rest of what the
program does to the five objects, and a chat's three are the ones
`rouh/runtime.py` already had, because a chat's writer is `conversations.py`
and it stays the only one. Nothing about a row's menu is decided here.
"""
from __future__ import annotations

import json
import logging
import os
import re

from . import addressing, genes, objects, objectindex, pages, steps, uploads

log = logging.getLogger("rouh.searching")

#: The five objects, in the order the pills are drawn in, which is the order
#: the person said them in: Chats, Tasks, Projects, Artifacts, Runs.
OBJECTS: tuple[str, ...] = ("chat", "task", "project", "artifact", "run")

#: The pill for the HTML pages alone, right after Tasks: Petar, 12 October
#: 2026 (fr_af4df21c8894), "Filter for search should have a pages item
#: immediately after tasks". A page is not an object of its own but an
#: artifact, or a page in a task's folder (`is_page`), so it is still under
#: Artifacts as well and is counted there too.
PAGE = "page"

#: Every pill but All, in the order they are drawn: the five with Pages after
#: Tasks, and the files the person uploaded after them.
KINDS: tuple[str, ...] = (*OBJECTS[:2], PAGE, *OBJECTS[2:], "file")

#: What may be done to a file from its row: open it, here or in a tab of its
#: own. It is not one of the five, so it has no pin, no name of Rouh's to
#: change, and no delete from a search.
FILE_ACTIONS: tuple[str, ...] = ("open", "tab")

#: What the pill that is not one of the five is called.
ALL = "all"

#: How many rows come back. A search box is scanned, not paged: more than this
#: on the screen is a list nobody reads to the end of, and the answer to too
#: many results is another word rather than more scrolling.
LIMIT = 30

#: How wide a snippet is, in characters. About two lines on a phone and one on
#: a desk, which is "a little bit of the content" and not a paragraph.
SNIPPET = 120

#: How much of a body is looked at when cutting a snippet out of it. A card
#: with a megabyte of table in it is not a better snippet for being read whole.
BODY = 4000


def _store() -> objects.ObjectStore | None:
    """The store, open even where the object model is switched off.

    The same `even_when_off` the task browser and the conversations ask for
    (`rouh/objects.py`): the flag is a way back to the paths the runs and the
    artifacts had before the model, and a chat has had none since step three.
    Hiding the store from search would hide the person's own conversations
    rather than fall back to anything.
    """
    return objects.shared_store(even_when_off=True)


def words_of(query: str) -> list[str]:
    """The words of a query, as the store matches them.

    Cut to a sane number and a sane length: a search box is typed into, and
    what arrives over a socket is never trusted to be small.
    """
    return [word[:64] for word in str(query or "").split()[:8] if word]


#: A query that is nothing but a task's number: 62, 62-16, and 62.16 read the
#: same way, because a subtask's folder is `62-16.name` and its task's is
#: `62.name`, and either mark is what a thumb reaches for on a phone.
_ASKED = re.compile(r"^\d+(?:[-.]\d+)*$")

#: The number at the start of one folder's name: `62` of `62.rouh`, `62-16`
#: of `62-16.sharing-changes`, and `01` of a step written the older way,
#: `01-price-comparison`.
_CALLED = re.compile(r"^(\d+(?:-\d+)*)(?=[.-]|$)")

#: A task's number said in words: 62-16 on its own, which nothing else is
#: written like, or 62 with "task" in front of it. Only ever believed when a
#: task is really called that (`_said_in`). "Step 4" is never a task: a step's
#: own number has a dash, and a bare one after "step" is the fourth of some
#: steps being talked through (fr_2849579ed226, 28 October 2026).
_SAID = re.compile(r"(?<![\w.:/-])(\d{1,3}-\d{2}(?:-\d{2})*)(?![\w-])"
                   r"|\b(?:sub-?task|task|step)\s+(\d{1,3}-\d{2}(?:-\d{2})*|(?<![\w-]task\s)(?<=task\s)\d{1,3})\b", re.IGNORECASE)


def number_asked(query: str) -> tuple[int, ...] | None:
    """The task number a query is, as its parts, or None when it is words."""
    said = str(query or "").strip()
    if not _ASKED.match(said):
        return None
    return tuple(int(part) for part in re.split(r"[-.]", said))


def number_of_folder(folder: str) -> str:
    """What a task with no number of its own is called, out of its folder.

    `62-16` out of `rouh/assistant/62.rouh/62-16.sharing...`, whose name
    says the whole of it. A step written the older way says only its own
    place, `private/buy/11.winter-jacket/01-price-comparison`, and
    is called by its task's number in front of it: 11-01. "" when no folder
    on the way has a number.
    """
    said = [found.group(1) for found in
            (_CALLED.match(part) for part in str(folder or "").strip("/").split("/"))
            if found]
    if not said:
        return ""
    name = said[-1]
    for above in reversed(said[:-1]):
        if name.startswith(above + "-"):
            break
        name = f"{above}-{name}"
    return name


def search(query: str, *, kind: str = ALL, limit: int = LIMIT, places=None, shared=()) -> dict:
    """Everything that matches, as the row of lines the page draws.

    `kind` is one of `KINDS` or "all". The counts come back for every pill
    whatever the pill says, because the pills show how many are behind each of
    them and a count that only appeared once you pressed one would be useless.

    `places`, when given, is whether a feature switch is on, and asks for Rouh's
    own pages as well - Decisions, Clockwork, Payments - found by their names and
    the words people use for them in the gene registry (`gene_lines`).
    They come first, on All alone: there is no pill of their own. `shared` is the shared
    genes in the organisation's lab (`rouh/genelab.py`), found the same way.
    """
    kind = kind if kind in KINDS else ALL
    limit = max(1, min(int(limit or LIMIT), 100))
    words = words_of(query)
    out = {"query": str(query or ""), "kind": kind, "results": [],
           "counts": {name: 0 for name in (ALL, *KINDS)}}
    found_places = gene_lines(query, places, shared) if places is not None and words else []
    out["counts"][ALL] = len(found_places)
    if kind == ALL:
        out["results"] = found_places
    store = _store()
    if store is None or not words:
        return out
    try:
        # More than one screenful, because the pills narrow this list rather
        # than asking again: a search with forty chats and two runs in it has
        # to still have the two runs behind the Runs pill.
        found = store.find(words, limit=limit * 8)
    except Exception:
        log.exception("the search for %r could not be answered", query)
        return out
    try:
        files = uploads.find(words, limit=limit * 8)
    except Exception:
        # The files are one pill of seven, and a search that finds the chats
        # and not the files is better than one that finds nothing.
        log.exception("the uploaded files could not be searched for %r", query)
        files = []
    if files:
        found = objects.ranked(found + files)[:limit * 8]
    asked = number_asked(query)
    if asked:
        try:
            found = _number_first(store, asked, found)
        except Exception:
            # The words were still found; only the order is what it was.
            log.exception("the task numbered %r could not be put first", query)
    try:
        found = _fold_forks(store, found)
    except Exception:
        # The forks are still found, each as a chat of its own, which is
        # how they were drawn before they were folded.
        log.exception("the forks found for %r could not be folded", query)
    for hit in found:
        out["counts"][hit["type"]] = out["counts"].get(hit["type"], 0) + 1
        if _is_page_hit(hit):
            out["counts"][PAGE] += 1
    out["counts"][ALL] = len(found_places) + len(found)
    wanted = [hit for hit in found
              if kind in (ALL, hit["type"]) or (kind == PAGE and _is_page_hit(hit))]
    wanted = wanted[:max(0, limit - len(out["results"]))]
    _label(store, wanted)
    out["results"] = out["results"] + [_line(store, hit, words) for hit in wanted]
    return out


def gene_lines(query: str, switch_on, shared=()) -> list[dict]:
    """Rouh's own pages a search names, as rows: "payments" finds Payments, "inbox"
    finds Decisions. Every word typed has to begin a word of the gene's name or of
    one of its aliases (`genes.find`). A row opens the gene as its link in the
    navigation would (`geneGo` in app/navgroups.js), and a gene with an address
    of its own can open in a tab of its own too."""
    try:
        found = genes.find(re.findall(r"[a-z0-9]+", str(query or "").lower()), switch_on, extra=shared)
    except Exception:
        log.exception("the genes could not be searched for %r", query)
        return []
    out = []
    for m in found:
        # Which tab it is under, and what it is, without its name said twice:
        # "Anatomy - The card vault, the spending caps and Stripe".
        group = dict(genes.GROUPS)[m["group"]] + (", shared" if m.get("shared") else "")
        what = m["title"][len(m["name"]) + 2:] if m["title"].startswith(m["name"] + ": ") else m["title"]
        what = what[:1].upper() + what[1:]
        out.append({
            "type": "gene", "id": m["id"], "title": m["name"], "label": "",
            "snippet": f"{group} - {what}" if what != m["name"] else group,
            "at": 0, "open": {"how": "gene", "id": m["id"]},
            "url": m["route"] or "", "actions": ["open", "tab"] if m["route"] else ["open"],
        })
    return out


# ---------------------------------------------------------------------------
# Forks, under the chat they hang off
# ---------------------------------------------------------------------------


def _fold_forks(store: objects.ObjectStore, found: list[dict]) -> list[dict]:
    """Every fork found, as a line under the chat it all started in.

    Petar, 5 October 2026: a fork is a side question asked of one chat, not
    a chat of its own (`rouh/forks.py`), so a search that finds words said in
    one draws the chat it came off, and the fork under it, rather than a row
    called "New chat" nobody recognises among the real ones. The chat stands
    where the best of it and its forks was ranked, and each fork is kept on
    it, in the order they were found, under `forks`: pressing one opens the
    fork itself, on its strip, at the message that matched (`_line`).

    The chat it started in is put in even when only a fork matched, by name
    (`rows_of`), with `matched` saying so. A fork whose chat has gone - which
    the database's cascade makes nearly impossible - is left as it was found.
    A fork detached from its chat, or made a task, is no longer laid out as
    one and stays a row of its own (`forks.ids`).
    """
    from . import forks

    laid = forks.ids()
    hits = [hit for hit in found if hit["type"] == "chat" and hit["id"] in laid]
    if not hits:
        return found
    root = {hit["id"]: forks.root_of(hit["id"]) for hit in hits}
    have = {hit["id"]: hit for hit in found if hit["type"] == "chat"}
    wanting = sorted({r for r in root.values() if r and r not in have and r not in laid})
    for row in store.rows_of([("chat", r) for r in wanting]) if wanting else []:
        row["matched"] = "fork"
        have[row["id"]] = row
    out: list[dict] = []
    placed: set[str] = set()
    for hit in found:
        if hit["type"] != "chat":
            out.append(hit)
            continue
        top = root.get(hit["id"]) or hit["id"]
        holder = have.get(top)
        if holder is None or (holder is hit and hit["id"] in laid):
            out.append(hit)
            continue
        if top not in placed:
            placed.add(top)
            out.append(holder)
        if holder is not hit:
            holder.setdefault("forks", []).append(hit)
    return out


#: How many of a chat's messages are read, newest first, for the one that
#: matched. A chat is a few dozen; a page pasted in is one.
MESSAGES_READ = 400


def _message_of(chat_id: str, words: list[str]) -> tuple[int, int] | None:
    """The newest message of this chat that says every one of these words,
    as (its id, its exchange).

    What the search matched is the chat's record (`ObjectStore.find`), one
    line per turn with no number the page knows; the page draws the chat
    from the transcript, whose rows are what a turn on screen is numbered by
    (`data-msg`). So the same words are looked for in the transcript, as the
    page draws each message (`Memory._said`), and the newest first, which is
    the turn the search took its snippet from. None when no message says
    them all - a match in a tool's output, say - and the chat opens as usual.
    The exchange is for a turn the page drew live and has kept since, which
    carries only that (`data-root`).
    """
    from .memory import Memory, _exchange
    from .models.memory import TranscriptMessage

    low = [word.lower() for word in words if word]
    if not chat_id or not low:
        return None
    rows = (TranscriptMessage.objects
            .filter(session_id=chat_id, live=True, note=False)
            .annotate(ex=_exchange()).order_by("-ex", "-id")
            .values("id", "ts", "role", "content", "note", "root", "ex")[:MESSAGES_READ])
    for row in rows:
        try:
            said = Memory._said(row)
        except Exception:
            continue
        text = str((said or {}).get("text") or "").lower()
        if text and all(word in text for word in low):
            return int(row["id"]), int(row["ex"])
    return None


# ---------------------------------------------------------------------------
# A task's number, typed
# ---------------------------------------------------------------------------


def _number_first(store: objects.ObjectStore, asked: tuple[int, ...],
                  found: list[dict]) -> list[dict]:
    """The task a number names, and what is its, ahead of everything else found.

    The person asked for it on 30 September 2026, after typing 62-16 and not
    finding the task on the first page: "If I type a specific number, and
    such a task exists (even if archived) it should immediately be at the
    very top", and then in this order -

    1. the task itself, archived or not;
    2. the chats that belong to it;
    3. its pages: the `.html` it built, and the cards Rouh filed as pages;
    4. the task it is a subtask of;
    5. its other documents - its `.md` files - and its other artifacts and runs.

    What the words found follows as it always did, without the rows already
    placed above it. The pages and documents are the task's own files, which
    are not rows of any table, so they are only ever found this way; each is
    an artifact on the screen, and opens exactly as a press on its line on
    the task's page does.
    """
    from .config import config

    task = store.task_called(asked)
    if task is None:
        return found
    have = {(hit["type"], hit["id"]): hit for hit in found}
    kids = store.children_of("task", task.id)
    chats = [key for key in kids if key[0] == "chat"]
    runs = [key for key in kids if key[0] == "run"]
    cards = [key for key in kids if key[0] == "artifact"]
    for holder in chats + runs:
        cards += [key for key in store.children_of(*holder, "artifact") if key not in cards]
    over = store.owner_of("task", task.id)
    parent = [over] if over and over[0] == "task" else []

    keys = [("task", task.id), *chats, *runs, *cards, *parent]
    rows = {(hit["type"], hit["id"]): hit
            for hit in store.rows_of([key for key in keys if key not in have])}
    rows.update(have)

    def newest(hits):
        return sorted(hits, key=lambda hit: -(hit.get("at") or 0.0))

    def these(wanted):
        return [rows[key] for key in wanted if key in rows]

    docs = _documents(config.assistant_repo, task)
    # Never a run's "What it changed": every run has one, they all carry the
    # same name, and none has anything to open (`objects.UNSEARCHED`).
    card_rows = [hit for hit in these(cards) if hit.get("kind") not in objects.UNSEARCHED]
    first = [
        *these([("task", task.id)]),
        *newest(these(chats)),
        *[doc for doc in docs if doc["doc"] == "page"],
        *newest([hit for hit in card_rows if hit.get("kind") == "page"]),
        *these(parent),
        *[doc for doc in docs if doc["doc"] != "page"],
        *newest([hit for hit in card_rows if hit.get("kind") != "page"] + these(runs)),
    ]
    placed = {(hit["type"], hit["id"]) for hit in first}
    for hit in first:
        # Put here by the number rather than by the words, which is what the
        # row says it matched on.
        if (hit["type"], hit["id"]) not in have:
            hit["matched"] = "number"
    return first + [hit for hit in found if (hit["type"], hit["id"]) not in placed]


def _documents(root, task: objects.Task) -> list[dict]:
    """A task's own pages and `.md` files, each as a search hit.

    The ones directly in its folder and not a subtask's, the same list its
    own page draws (`objectindex.documents`). Each is an artifact on the
    screen, with the task as the place it lives, which is what gives it its
    number (`_label`).
    """
    folder = str(task.folder or "").strip("/")
    if not root or not folder:
        return []
    out = []
    for one in objectindex.documents(root, folder):
        path = os.path.join(str(root), folder, one["name"])
        try:
            at = os.path.getmtime(path)
        except OSError:
            at = None
        body = ""
        if one["kind"] == "md":
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    body = fh.read(BODY)
            except OSError:
                body = ""
        out.append({"type": "artifact", "id": f"{folder}/{one['name']}",
                    "doc": one["kind"], "title": one["title"] or one["name"],
                    "matched": "number", "body": body, "at": at, "pinned": False,
                    "home": ("task", task.id), "folder": folder, "name": one["name"],
                    "href": one["href"]})
    return out


# ---------------------------------------------------------------------------
# The number in front of every row
# ---------------------------------------------------------------------------


def _label(store: objects.ObjectStore, hits: list[dict]) -> None:
    """Put on every hit the number of the task it is, or is in.

    The person asked for it on 30 September 2026: "Nothing should be
    numberless, because nothing is sitting essentially outside of the task
    browser", and again the same day when many rows still had none. A task
    wears its own number, and a subtask the start of its folder's name,
    62-16 (`number_of_folder`). Anything else wears the number of the task
    it is tied to, in this order, each only believed if it reaches a task
    that is really there:

    1. what it is filed under, or came from, climbed up (`ObjectStore.homes`);
    2. for a card, the task folder its file is in;
    3. for a chat, the task most of its cards and jobs are about - never for
       General, which is about everything;
    4. a task's number said in its own name, or its name being exactly one
       task's name ("📋 Waiting on you screen" is 62-11's chat).

    Something none of that reaches is in no task, and has no number to wear
    rather than one made up.
    """
    keys: dict[int, tuple[str, str]] = {}
    for at, hit in enumerate(hits):
        if hit.get("home"):
            keys[at] = tuple(hit["home"])
        elif hit.get("type") == "file":
            if hit.get("given_in"):
                keys[at] = tuple(hit["given_in"])
        elif hit.get("type") and hit.get("id"):
            keys[at] = (hit["type"], hit["id"])
    names = _Names(store)
    try:
        homes = store.homes(set(keys.values()))
    except Exception:
        log.exception("could not work out which task each result is in")
        homes = {}
    for at, hit in enumerate(hits):
        key = keys.get(at)
        label = names.of(homes.get(key)) if key else ""
        if not label and hit.get("type") == "task":
            label = number_of_folder(hit.get("folder") or "")
        if not label and key:
            try:
                label = _told_by(store, names, key, hit)
            except Exception:
                log.exception("could not read which task %s %s is about", *key)
        hit["label"] = label


class _Names:
    """What each task is called by its number, read once for one list of hits."""

    def __init__(self, store: objects.ObjectStore):
        self.by_id: dict[str, str] = {}
        self.by_folder: dict[str, str] = {}
        try:
            rows = store.task_numbers()
        except Exception:
            log.exception("could not read the tasks' numbers")
            rows = []
        for ident, number, folder in rows:
            name = str(number) if number is not None else number_of_folder(folder or "")
            self.by_id[ident] = name
            if folder and name:
                self.by_folder[str(folder).strip("/")] = name
        self.said = set(self.by_id.values()) - {""}
        # By name, for a chat or a job called exactly what one task is
        # called. A name two tasks share says nothing.
        self.by_name: dict[str, str] = {}
        shared: set[str] = set()
        try:
            titles = store.task_titles()
        except Exception:
            log.exception("could not read the tasks' names")
            titles = []
        for ident, title in titles:
            name = _bare(title)
            if not name or not self.by_id.get(ident):
                continue
            if name in self.by_name and self.by_name[name] != self.by_id[ident]:
                shared.add(name)
            self.by_name[name] = self.by_id[ident]
        for name in shared:
            self.by_name.pop(name, None)

    def of(self, home) -> str:
        """The number of a home `ObjectStore.homes` found: a task's, never a project's."""
        return self.by_id.get(home[1], "") if home and home[0] == "task" else ""

    def at_path(self, path: str) -> str:
        """The number of the deepest task whose folder this path is in."""
        path = str(path or "").strip("/")
        while path:
            if path in self.by_folder:
                return self.by_folder[path]
            path = path.rsplit("/", 1)[0] if "/" in path else ""
        return ""

    def named(self, title: str) -> str:
        """The number of the one task called exactly this, or ""."""
        return self.by_name.get(_bare(title), "")

    def said_in(self, text: str) -> str:
        """The first number in these words that a task is really called."""
        for found in _SAID.finditer(str(text or "")[:BODY]):
            name = found.group(1) or found.group(2)
            if name in self.said:
                return name
        return ""


def _bare(title: str) -> str:
    """A name as two names are compared: no emoji or mark in front, no case.

    "📋 Waiting on you screen", "Done: Waiting on you screen" and "Waiting on
    you screen" are one name. Short names are nobody's: "Research" is half
    the steps there are.
    """
    name = str(title or "").strip()
    name = re.sub(r"^[^\w]+", "", name)
    name = re.sub(r"^(?:done|answer|re|fwd?)\s*:\s*", "", name, flags=re.IGNORECASE)
    name = " ".join(name.lower().split())
    return name if len(name) >= 12 and " " in name else ""


def _told_by(store: objects.ObjectStore, names: _Names, key: tuple[str, str],
             hit: dict) -> str:
    """The number of the task something with no home is about, or ""."""
    kind, ident = key
    if kind == "artifact":
        found = names.at_path(hit.get("path") or "")
        if found:
            return found
    if kind == "chat":
        found = _chat_is_about(store, names, ident)
        if found:
            return found
    # Only its own name, and never a job's brief or a chat's words: a brief
    # quotes whatever it is about ("typed 62-16 into search") as readily as
    # the task it is for.
    return names.said_in(hit.get("title") or "") or names.named(hit.get("title") or "")


def _chat_is_about(store: objects.ObjectStore, names: _Names, chat_id: str) -> str:
    """The task most of what a loose chat drew and started belongs to, or ""."""
    from . import conversations

    if chat_id == conversations.GENERAL:
        return ""
    made = store.children_of("chat", chat_id, "artifact")
    runs = [("run", link.src_id) for link in store.refs("from", dst_type="chat", dst_id=chat_id)]
    homes = store.homes(set(made + runs)) if made or runs else {}
    votes: dict[str, int] = {}
    for key in made + runs:
        found = names.of(homes.get(key))
        if not found and key[0] == "artifact":
            row = store.get_artifact(key[1])
            found = names.at_path(getattr(row, "path", "") if row else "")
        if found:
            votes[found] = votes.get(found, 0) + 1
    return max(votes, key=lambda name: votes[name]) if votes else ""


def find_one(kind: str, name: str) -> dict | None:
    """One object, as a result row, for a page that arrived at its address.

    `name` is whatever the address held after the kind: a folder for a task or
    a project, an id for the other three, and `rouh/addressing.py` is what
    knows which. None when there is no such thing, which is what a link to
    something since deleted comes back as.
    """
    store = _store()
    if store is None or kind not in OBJECTS or not name:
        return None
    row = addressing.at(kind, name)
    if row is None and kind == "chat":
        # A draft: New chat pressed and nothing said yet, which has an address
        # like any chat and no row until something is said in it. Reloading
        # the page is coming back to it, not following a link to something
        # deleted.
        from . import conversations

        drafted = conversations.draft_row(name)
        if drafted is not None:
            return {"type": "chat", "id": drafted["id"],
                    "title": _title({"title": drafted["title"]}), "number": None,
                    "snippet": "", "at": drafted["updated_at"], "pinned": False,
                    "state": "", "why": "title",
                    "open": {"how": "chat", "id": drafted["id"]},
                    "url": addressing.url_for("chat", drafted["id"])}
    if row is None and kind in objects.NESTS:
        # Something inside a task or a project: one of its notes, a folder of
        # a step, the page a step built (`addressing.inside`).
        found = addressing.inside(kind, name)
        if found is not None:
            return _inside_line(store, *found)
    if row is None:
        return None
    hit = _hit_of(kind, row)
    _label(store, [hit])
    return _line(store, hit, [])


def labels(kind: str, ids: list[str]) -> dict[str, str]:
    """The task number each of these objects wears, by id, as a result row would.

    For the list the search box shows before anything is typed, which the page
    draws from the chats it already holds (`findRecent` in app.js) and so had
    no number on a single row until 4 October 2026, when Petar opened search
    and did not see one (fr_a898cf088d57). The same `_label` the answer to a
    search uses, so a chat wears the same number either way. One that reaches
    no task, or is not there, is left out rather than given one made up.
    """
    store = _store()
    if store is None or kind not in OBJECTS:
        return {}
    hits = []
    for ident in list(dict.fromkeys(str(i or "") for i in ids if i))[:200]:
        try:
            row = addressing.at(kind, ident)
        except Exception:
            log.exception("could not read the %s %s for its number", kind, ident)
            row = None
        if row is not None:
            hits.append(_hit_of(kind, row))
    if not hits:
        return {}
    _label(store, hits)
    return {hit["id"]: hit["label"] for hit in hits if hit.get("label")}


# --- a task's number in an answer, as its name ----------------------------------------------

#: How many numbers one answer may ask about at a time.
REFS_MOST = 60

#: Words after a number that make it an amount and not a task: "10-15 minutes".
_AMOUNT = re.compile(r"^\s*(?:%|percent|min|mins|minutes?|hours?|hrs?|days?|weeks?|months?|years?|"
                     r"seconds?|secs?|people|persons?|euros?|eur|lev|leva|usd|dollars?|pages?|"
                     r"items?|times?|km|kg|m|cm)\b", re.IGNORECASE)


def refs(numbers) -> dict[str, dict]:
    """What each of these task numbers is, for an answer that names it: its name, its icon and
    its address, by the number as it was asked ("98-23", "98-23-01", "140").

    Petar, 24 October 2026 (fr_493a5928008e): "I have no idea what 98-23 is. I would like all
    such references to be in their full name and also with their icon and a link, so I can
    click it and see." The page asks for the numbers it found in an answer (`taskRefs` in
    app/transcript.js) and draws each one this finds as its icon and name, a link to the task;
    a number no task is called is left out, and stays plain text on the page. Found the way
    search finds a number typed into it (`ObjectStore.task_called`), so a number a move took
    away still names the task that had it.
    """
    store = _store()
    if store is None:
        return {}
    out: dict[str, dict] = {}
    for said in list(dict.fromkeys(str(n or "").strip() for n in numbers or ()))[:REFS_MOST]:
        parts = number_asked(said)
        if not parts or len(said) > 20:
            continue
        try:
            row = store.task_called(parts)
        except Exception:
            log.exception("could not look up task %s", said)
            row = None
        if row is None or not row.title:
            continue
        from . import taskicons

        number = str(row.number) if row.number is not None else number_of_folder(row.folder or "")
        out[said] = dict(taskicons.shown(row.icon, row.title), title=row.title,
                         number=number or said,
                         url=addressing.url_for("task", row.id, row.folder or ""))
    return out


def spoken(sentence: str) -> str:
    """A sentence about to be said aloud, with every task number in it said as the task's name.

    The same request as `refs` above, for the voice: "98-23" means nothing heard either. A
    number no task is called, or one that is an amount ("10-15 minutes"), is said as written.
    """
    text = str(sentence or "")
    if not re.search(r"\d", text):
        return text
    found = [(m, m.group(1) or m.group(2)) for m in _SAID.finditer(text[:BODY])]
    found = [(m, n) for m, n in found if not _AMOUNT.match(text[m.end():])]
    if not found:
        return text
    names = refs([n for _, n in found])
    out, last = [], 0
    for m, n in found:
        info = names.get(n)
        if not info:
            continue
        start = m.start(1) if m.group(1) else m.start(2)
        out.append(text[last:start])
        out.append(re.sub(r"^[^\w]+", "", info["title"]).strip() or info["title"])
        last = m.end()
    out.append(text[last:])
    return "".join(out)


def _hit_of(kind: str, row) -> dict:
    """One object's row as the search query hands one back, for `_line`."""
    return {"type": kind, "id": row.id, "matched": "title", "body": "",
            "title": getattr(row, "title", "") or "",
            "number": getattr(row, "number", None),
            "folder": getattr(row, "folder", "") or "",
            "path": getattr(row, "path", "") or "",
            "kind": getattr(row, "kind", "") or "",
            "pinned": bool(getattr(row, "pinned", False)),
            "state": getattr(row, "state", None) or getattr(row, "status", "") or "",
            # The same "last worked on" every other row carries, off whichever
            # column this type keeps it in (`objects._SEARCH_ROW`).
            "at": objects._at(getattr(row, "updated_at", None),
                              getattr(row, "last_spoke", None),
                              getattr(row, "ended_at", None),
                              getattr(row, "started_at", None),
                              getattr(row, "created_at", None))}


def _inside_line(store: objects.ObjectStore, kind: str, row, rest: str) -> dict:
    """What is inside one object, as the line its address is opened from.

    The object's own line, because that is what the thing belongs to and
    what the rail and the conversation follow, with the one instruction
    changed: `page` puts exactly this on the canvas, the same address a press
    on its line in the object's page loads. A page is itself; anything else -
    notes, a folder, a code file - is read on the object's own page
    (`objectindex.build_doc`).
    """
    from .config import config

    folder = str(getattr(row, "folder", "") or "").strip("/")
    hit = _hit_of(kind, row)
    _label(store, [hit])
    line = _line(store, hit, [])
    # A subtask a job wrote as a folder has no row, and has a page of its own
    # all the same, which is where a press on its line went: so the address
    # of it, or of anything in it, opens there, and a reload lands where the
    # press did (`objectindex.subtask_within`).
    at, inside = ((folder, rest) if kind != "task"
                  else objectindex.subtask_within(config.assistant_repo, folder, rest))
    if not inside:
        page = pages.url_for(objectindex.TASK_PREFIX + at) + "/"
    elif inside.lower().endswith((".html", ".htm")):
        page = pages.url_for(f"{at}/{inside}")
    else:
        page = objectindex.doc_url(at, inside)
    line["open"] = {"how": "page", "task": folder, "page": page}
    line["url"] = addressing.url_for(kind, row.id, f"{folder}/{rest}")
    return line


# ---------------------------------------------------------------------------
# One line on the screen
# ---------------------------------------------------------------------------


def is_page(hit: dict) -> bool:
    """Whether a row is an HTML page, which the page draws with an icon of its
    own and ahead of the other artifacts in weight: Petar, 1 October 2026
    (fr_c72cbb0c4149), "HTML pages are more important and should be more
    visible". A card whose kind is `page`, or one that names an HTML file."""
    if hit.get("type") != "artifact":
        return False
    return (hit.get("kind") == "page"
            or str(hit.get("path") or "").lower().endswith((".html", ".htm")))


def _is_page_hit(hit: dict) -> bool:
    """Whether a hit belongs behind the Pages pill: a page among the artifacts
    (`is_page`), or a page in a task's folder found by the task's number
    (`_documents`), which is drawn as a page too (`_doc_line`)."""
    return hit.get("doc") == "page" if hit.get("doc") else is_page(hit)


def _line(store: objects.ObjectStore, hit: dict, words: list[str]) -> dict:
    """One result, as the page draws it: what it is, what it says, and when."""
    if hit.get("type") == "file":
        return _file_line(hit, words)
    if hit.get("doc"):
        return _doc_line(hit, words)
    body = _readable(hit.get("type", ""), hit.get("body") or "")
    if not body:
        try:
            body = _readable(hit["type"],
                             store.first_words(hit["type"], hit["id"], BODY))
        except Exception:
            body = ""
    where = _open(store, hit)
    # Whatever it matched on: a chat named for what was asked in it says
    # the same words in that message, and that is where it opens.
    if hit["type"] == "chat" and hit.get("matched") != "fork":
        msg = _message_of(hit["id"], words)
        if msg is not None:
            where = dict(where, msg=msg[0], ex=msg[1])
    line = {
        "type": hit["type"],
        "id": hit["id"],
        "title": _title(hit),
        "number": hit.get("number"),
        # The number the row is drawn with, in front of its name: its own, or
        # the task's it is in (`_label`).
        "label": hit.get("label") or "",
        "archived": bool(hit.get("archived")),
        "snippet": _snippet(body, words),
        "at": hit.get("at"),
        "pinned": bool(hit.get("pinned")),
        "state": hit.get("state") or "",
        "why": hit.get("matched") or "title",
        "page": is_page(hit),
        "open": where,
        # Where this row lives, as an address a person can be handed
        # (`rouh/addressing.py`). It is what "open in new tab" opens, and it
        # is what the address bar says once the row has been pressed.
        "url": addressing.url_for(hit["type"], hit["id"], hit.get("folder") or ""),
    }
    if hit.get("forks"):
        line["forks"] = [_fork_line(store, fork, words) for fork in hit["forks"]]
    return line


def _fork_line(store: objects.ObjectStore, hit: dict, words: list[str]) -> dict:
    """One fork found, as the line under its chat (`_fold_forks`): its name,
    what matched in it, and how to open it, at the message that matched."""
    body = _readable("chat", hit.get("body") or "")
    if not body:
        try:
            body = _readable("chat", store.first_words("chat", hit["id"], BODY))
        except Exception:
            body = ""
    where = {"how": "chat", "id": hit["id"]}
    msg = _message_of(hit["id"], words)
    if msg is not None:
        where["msg"], where["ex"] = msg
    return {
        "type": "chat",
        "id": hit["id"],
        "title": _title(hit),
        "snippet": _snippet(body, words),
        "at": hit.get("at"),
        "why": hit.get("matched") or "title",
        "open": where,
        "url": addressing.url_for("chat", hit["id"]),
    }


def _file_line(hit: dict, words: list[str]) -> dict:
    """One uploaded file, as the page draws it: its own name, never its Markdown.

    What it says is a few of its words round the match; a picture has none,
    and says where it was given instead. `where` goes on the row's tooltip
    either way, because two files called "Contract.pdf" are told apart by it.
    How it opens and its address came with the hit (`uploads.find`).
    """
    snippet = _snippet(_readable("file", hit.get("body") or ""), words)
    return {
        "type": "file",
        "id": hit["id"],
        "title": _title(hit),
        "number": None,
        "label": hit.get("label") or "",
        "snippet": snippet or hit.get("where") or "",
        "where": hit.get("where") or "",
        "at": hit.get("at"),
        "pinned": False,
        "state": "",
        "why": hit.get("matched") or "title",
        "open": hit["open"],
        "url": hit["url"],
        "actions": list(FILE_ACTIONS),
    }


def _doc_line(hit: dict, words: list[str]) -> dict:
    """One of a task's own pages or `.md` files, as the page draws it.

    An artifact on the screen, opened exactly as a press on its line on the
    task's own page opens it (`objectindex.documents`), and addressed as
    anything inside a task is (`_inside_line`). It is a file of the task's
    folder rather than a row, so there is nothing of its own to pin, rename
    or delete from here.
    """
    folder, name = hit["folder"], hit["name"]
    return {
        "type": "artifact",
        "id": hit["id"],
        "title": _title(hit),
        "number": None,
        "label": hit.get("label") or "",
        "archived": False,
        "snippet": (_snippet(_readable("artifact", hit.get("body") or ""), words)
                    or ("A page of this task" if hit["doc"] == "page" else name)),
        "at": hit.get("at"),
        "pinned": False,
        "state": "",
        "why": hit.get("matched") or "number",
        "page": hit["doc"] == "page",
        "open": {"how": "page", "task": folder, "page": hit["href"], "kind": "task"},
        "url": addressing.url_for("task", hit["home"][1], f"{folder}/{name}"),
        "actions": list(FILE_ACTIONS),
    }


def _title(hit: dict) -> str:
    """What the row is called: the name alone, and never the number with it.

    The number people say out loud comes back in its own field and the page
    puts it in front. Keeping them apart is what lets Rename hand the person
    the name they are changing rather than "30 Jarvis", which would be written
    back into the title as if the number were part of it.
    """
    title = str(hit.get("title") or "").strip()
    if not title:
        title = {"chat": "New chat"}.get(hit["type"], hit["id"])
    return title


def _readable(kind: str, body: str) -> str:
    """A body as words, which for a card means the card rather than its JSON.

    Everything Rouh draws on the canvas is an artifact whose body is the spec
    it was drawn from (`rouh/artifacts.py`). A person searching for what was
    on a card wants the card's own description, so that is what is shown; the
    braces are not a snippet of anything.
    """
    body = str(body or "")[:BODY]
    if kind != "artifact" or not body.lstrip().startswith("{"):
        return " ".join(body.split())
    try:
        spec = json.loads(body)
    except ValueError:
        return " ".join(body.split())
    if not isinstance(spec, dict):
        return " ".join(body.split())
    said = [str(spec.get("description") or ""), str(spec.get("text") or "")]
    for block in (spec.get("blocks") or [])[:6]:
        if isinstance(block, dict):
            said.append(str(block.get("text") or ""))
    return " ".join(" ".join(said).split())


def _snippet(body: str, words: list[str]) -> str:
    """A little of the body, cut around the first word that matched.

    With an ellipsis on whichever side has something cut off it, and never in
    the middle of a word where there is a space to cut at instead.
    """
    body = " ".join(str(body or "").split())
    if not body:
        return ""
    at = -1
    low = body.lower()
    for word in words:
        found = low.find(word.lower())
        if found >= 0 and (at < 0 or found < at):
            at = found
    if at < 0 or at <= SNIPPET // 3:
        cut = body[:SNIPPET]
        return cut + ("…" if len(body) > SNIPPET else "")
    start = at - SNIPPET // 3
    space = body.rfind(" ", start, at)
    if space > start:
        start = space + 1
    end = start + SNIPPET
    return ("…" + body[start:end].rstrip()
            + ("…" if end < len(body) else ""))


# ---------------------------------------------------------------------------
# How each of the five is opened
# ---------------------------------------------------------------------------


def _open(store: objects.ObjectStore, hit: dict) -> dict:
    """What the page should do to open this row, decided here and not there.

    One of four instructions, and never an address the page invented:

    * `chat` - make that conversation the active one, which is what opening a
      chat has always been;
    * `task` - the object's folder on the canvas, which is the task browser's
      own page for it and picks its thread at the same time;
    * `step` - one step of a task, for an artifact that was filed as one;
    * `page` - something inside a task's or a project's folder, which only an
      address asks for (`_inside_line`): the canvas loads `page` as it is;
    * `card` - the artifact itself, in the viewer that opens over the canvas;
    * `projects` - the projects dashboard, for one of the person's own
      projects, which is a row holding chats and has no folder to open;
    * `none` - there is nothing built to open yet, and the page says so rather
      than opening something else.
    """
    kind = hit["type"]
    if kind == "chat":
        return {"how": "chat", "id": hit["id"]}
    if kind == "run":
        return {"how": "run", "id": hit["id"]}
    if kind in objects.NESTS:
        folder = hit.get("folder") or ""
        if folder:
            # A step is a task inside a task, and what opens a step is the
            # page it built - which is what clicking it in the task browser
            # does, and so is what its own address has to do. Opening the
            # browser's listing of it instead would land a link somewhere the
            # person cannot get to by clicking.
            if kind == "task" and steps.is_step(folder):
                return {"how": "step", "step": folder}
            return {"how": "task", "task": folder,
                    "page": pages.url_for(objectindex.TASK_PREFIX + folder + "/")}
        # No folder. A project is one of the person's own, made to hold chats,
        # and the dashboard is where those are; a task without one is a task
        # made on its own, and what there is to open is its conversation.
        if kind == "project":
            return {"how": "projects", "id": hit["id"]}
        chat = _chat_under(store, kind, hit["id"])
        return {"how": "chat", "id": chat} if chat else {"how": "none"}
    # An artifact. The step it was filed as, where the folder is really there,
    # and otherwise the artifact itself.
    #
    # It used to be whatever owned it, and that is the bug the person reported
    # on 22 September 2026: "when I click on any of the artifacts. nothing
    # happens. just blinks and nothing happens." Every card on a task's page is
    # owned by that task, so the answer to "open this card" was "open the page
    # you are already looking at", and the blink was that page being fetched
    # and framed a second time. A card is a thing in its own right, it has an
    # address of its own, and opening it opens it.
    step = _step_of(hit.get("path") or "")
    if step:
        return {"how": "step", "step": step}
    return {"how": "card", "id": hit["id"]}


def _step_of(path: str) -> str:
    """The step folder an artifact's path is in, when that folder is on disk.

    A path is only ever trusted this far: it has to sit under the workspace and
    the folder has to be there. A row whose folder was moved or deleted comes
    back empty and the artifact is opened by whatever owns it instead, which is
    how the two the old layout left behind are still reachable.
    """
    from .config import config

    rel = str(path or "").strip().strip("/")
    root = config.assistant_repo or ""
    if not rel or not root:
        return ""
    folder = rel.rsplit("/", 1)[0] if "." in rel.rsplit("/", 1)[-1] else rel
    try:
        here = steps._step_folder(root, folder)
    except Exception:
        return ""
    return folder if os.path.isdir(here) else ""


def _chat_under(store: objects.ObjectStore, kind: str, ident: str) -> str:
    """The conversation that object owns, or an empty string."""
    try:
        for link in store.refs(objects.OWNS, src_type=kind, src_id=ident,
                               dst_type="chat"):
            return link.dst_id
    except Exception:
        log.debug("could not read what %s %s owns", kind, ident, exc_info=True)
    return ""
