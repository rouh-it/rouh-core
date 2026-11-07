"""The Control Room: a map of what is on the owner's mind.

Petar, 9 October 2026, by voice, turning down the room of pins he had since
30 September: "all the projects and things going on are way too dynamic for me
to manually pin, so this entire concept does not work". He wants clusters - a
cluster for a client, a Rouh improvements cluster - "managed somehow by
recency, sentiment, or repeated visits", and "a map of what's going on in my
brain, with big cards that contain lots of data, while very useful at a
glance". Step 62-21 proposed how; this is it built, with his decisions of the
same day:

* **Mosaic and Front page**, one switch at the top, the Mosaic first
  (`controlroom.js`). No calendar strip across the top, as 62-21 drew: a
  cluster's next date is on its own card.
* **Rouh's own work never makes a cluster bigger.** 62-21 gave the runs
  started from a cluster's chats a tenth of the score; here they have none.
  What Rouh is running is still said on the card, as a fact, and never counts.
  The rest of what counts is his alone: his own words (`note` rows, which
  are Rouh's software speaking in his place, and tool results are left out),
  what waits on his answer, his returns, his dates and his tone.
* **A pin is a small lift, never a seat** (`PIN_BOOST`): a cluster with
  something pinned in it gets a few points added, the same however many pins
  it holds, so a pinned cluster can still be outgrown, sit on the quiet edge
  or leave the map.
* **Seven days**: a cluster with no new sign of him for `QUIET_DAYS` leaves
  the map, quiet edge and all.
* **Opus 5.5 names the clusters and writes the headlines** (the
  `control_room` use in `modeldefaults.USES`), never at the moment the room
  opens: once a night (`ensure`, a row on his Reminders page), and in the
  background after an opening that finds it due (`due`). The room always
  opens at once on what was written last.

How a card forms (`_graph`, `_cards`)
------------------------------------

No model, and subject first. Petar, 9 October 2026, after a card named for a
personal task held a client's meetings and a purchase, and another named for
a contact's errand held a sports contact, Gmail Team and the client's
presentation: a card is one of two things, and its name and what is in
it always agree.

* A **work** card is one task (its own chats, files, cards and steps), one
  Clockwork job (the chat its runs are in, nothing else) or one recurring
  meeting series, with the loose chats, mail and meetings tied to that task or
  those meetings themselves. It is called what the task or job is called.
* A **topic** card is a subject - a client's project such as Acme (named for an
  outside domain, acme.example), a person such as Sam, an outside organisation -
  with the tasks, jobs, chats and meetings that are about it as its rows.

Every subject is decided first, and each thing is then checked against it,
never against its neighbours (`_subject`): a task is about its project when
the project is a client's, a task, job or chat about the person its title
names, a mail thread about who it is with, a meeting about its guests'
organisation. Ties come only from direct evidence - a task and its own things,
one mail thread, one meeting (a recurring one's instances, his own copy of an
invitation), and Synapse Master's links between two things themselves,
weighing `MIN_TIE` together; one "about" link never does. People and topics
never tie anything: the people on a card are those who took part, by mail or
at a meeting, never him, Rouh, a machine or a shared inbox. Work, Personal and
Rouh never share a card, and a health task is always alone with its chats
(`_home`). A busy chat or a question waiting on him with nothing to belong to
is a small work card of its own.

The naming pass (`name`) is told the cards and names the topics (a work card
keeps its task's or job's own name, with the task's number in front of it),
gives a side to a card that has none, and writes each card's headline, which
the page calls "Where it stands". A card's key is its subject, so a name is
only ever kept for the subject it was given to. Every row on an opened card
says why it is there.

Petar, 13 October 2026, on a card he could not read (fr_691311644626): no key
numbers, since a figure that changes every time cannot be learned; Rouh's runs
and the pages he opened each a section of their own on an opened card, beside
its chats; a sub-chat under the chat it came off; and every line that names a
task says what it is, its number and its whole title ("Step 98-07 Fresh naming
strategies is now done"), never a bare code.

How big a cluster is (`_score`)
-------------------------------

    score = 0.33 his messages + 0.28 waiting on him + 0.17 his returns
          + 0.17 next date + 0.05 tone            (+ PIN_BOOST if pinned)

each part between 0 and 1, as in 62-21 with the runs' tenth shared out among
the rest in proportion. Large from 0.55, medium from 0.33, small from 0.18,
and below that the quiet edge. A cluster keeps the size it had when he last
looked unless its score is past the boundary by more than 0.05, so it does
not flick between two sizes. The layout is worked out once per opening.

It mirrors, it does not advise. The room never says what to do next, as Petar
had the room's "What's next" taken out on 29 September 2026; a headline says
where a cluster stands, never what he should do. Every line opens the task,
chat, run or question it came from, and that page is where anything is done.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

from . import addressing, task_origin

log = logging.getLogger("rouh.controlroom")

#: What each part of the score weighs. Rouh's runs are not among them.
WEIGHTS = {"activity": 0.33, "waiting": 0.28, "returns": 0.17, "date": 0.17, "tone": 0.05}
#: What something pinned in a cluster adds to its score: one boundary's worth
#: at most, never enough on its own to make a quiet cluster large.
PIN_BOOST = 0.06
#: A cluster with no new sign of him for this many days leaves the map.
QUIET_DAYS = 7
#: Where each size starts.
SIZES = (("large", 0.55), ("medium", 0.33), ("small", 0.18))
#: How far past a boundary a score must go before a card changes size.
STICK = 0.05
#: How far back the graph and the signals read.
LOOK_BACK = 35 * 86400
#: His messages count half as much every this many days.
HALF_LIFE = 3.0
#: How long one graph pass is kept before it is worked out again.
GRAPH_EVERY = 600.0
#: How a Synapse link's kind weighs, times its strength. "About" is a topic
#: two things share, not one carrying the other on, so it takes three strong
#: ones between the same two things to tie them (`MIN_TIE`).
LINK_WEIGHT = {"attached": 1.0, "in_thread": 1.0, "in": 1.0, "continues": 0.8, "follows_up": 0.8,
               "updates": 0.8, "about": 0.35, "to": 0.4, "from": 0.4, "cc": 0.3}
#: A task's own chat, tied to it.
OWNS_WEIGHT = 4.0
#: Two meetings that are one: the same series, or one meeting on the calendar twice.
SAME_MEETING = 1.0
#: What the direct links between two pieces of work must weigh together before
#: they are tied at all. One "about" link, 0.35 x 0.9 at its strongest, never
#: is: a chat that mentions padel does not pull a padel task in.
MIN_TIE = 0.7
#: What each person or topic two tied pieces of work share adds to their tie,
#: and the most it adds. Only to a tie there already is: never one of its own.
SHARED_EACH, SHARED_MOST = 0.1, 0.4
#: People and topics linked to more than this many things say nothing about
#: any of them, and are neither shown nor counted.
HUB_PERSON, HUB_TOPIC = 40, 30
#: How many more of his messages this week than the week before (and the
#: other way round) make a card say it is busier or quieter.
PACE_MORE, PACE_RATIO = 3, 1.5
#: What waiting on him weighs, by how soon it is wanted.
URGENCY = {"now": 1.0, "today": 1.0, "soon": 0.6, "whenever": 0.25}
#: A task marked waiting on him with no question written for it.
MARKED_WAITING = 0.4
#: Where his settings for the room are kept (`user_settings`).
NAMED, SEEN = "control_room_named", "control_room_seen"
#: The use the naming pass asks (`modeldefaults.USES`), and what its requests are logged under.
USE = PURPOSE = "control_room"
#: The nightly naming pass, a row on his Reminders page.
JOB, AT = "control_room_names", "04:30"
JOB_TITLE = "Control Room names and headlines"
JOB_WHAT = "Name the Control Room's clusters and write their headlines"
MODEL_SECONDS = 600.0
#: What the naming pass may write, its thinking included. At 8,000 the
#: thinking left too little for the map, which came back cut off.
MODEL_TOKENS = 32000
#: The most cards the naming pass is told about, busiest first.
GROUPS_MOST = 40

_URGENT = re.compile(r"\b(urgent|asap|today|tonight|tomorrow|now|deadline|right away|quickly|"
                     r"immediately|before the meeting)\b", re.I)
_UNHAPPY = re.compile(r"(doesn'?t work|does not work|not working|broken|wrong|terrible|annoying|"
                      r"again\b|still\b|why (is|does|did)|confus|frustrat|hate|useless)", re.I)

_graphs: dict[str, tuple[float, dict]] = {}
_naming: set[str] = set()
_running: set = set()


# ---------------------------------------------------------------------------
# The room, as /api/control answers it
# ---------------------------------------------------------------------------


def room(who, *, remember: bool = True, now: float | None = None) -> dict:
    """Everything the room draws, as one object, read afresh.

    ``remember`` writes down that he looked, which is what "since you last
    looked" and a card keeping its size are measured from; a read on his
    behalf by anything but the room itself passes False.
    """
    now = time.time() if now is None else now
    partial: list[str] = []
    facts = _Facts(who, now, partial)
    if facts.empty:
        return {"ok": False, "at": now, "clusters": [],
                "why": "There is no work on this machine for Rouh to read."}
    graph = _graph_of(facts)
    named = _setting(who, NAMED)
    seen = _setting(who, SEEN)
    placed = _place(graph, named)
    # Others' tasks: his own switch, the one the task browser has (`rouh/task_origin.py`).
    show = task_origin.showing(who.user_id, who.org_id)
    clusters = _score(facts, graph, placed, seen, show_others=show)
    gone = sum(1 for c in clusters if c["gone"])
    shown = [c for c in clusters if not c["gone"]]
    for c in shown:
        c.pop("gone", None)
    shown.sort(key=lambda c: -c["score"])
    if remember:
        _remember(who, seen, shown, now)
    from . import modeldefaults

    model = ""
    try:
        model = modeldefaults.use_model(USE, str(who.org_id) or None)
    except Exception:
        log.exception("the control room's model could not be read")
    return {
        "ok": True,
        "at": now,
        "clusters": shown,
        "gone": gone,
        "named_at": named.get("named_at"),
        "looked": _looked(seen, now),
        "model": model,
        "model_name": _model_name(model),
        "weights": WEIGHTS,
        "pin_boost": PIN_BOOST,
        "quiet_days": QUIET_DAYS,
        "naming": "",
        "partial": partial,
        "show_others": show,
        # How many numbered tasks on this map were made for somebody else, so the
        # switch can say what it keeps out.
        "others": sum(1 for ident in facts.made_for
                      if (facts.tree.rows.get(ident) or {}).get("number") is not None),
    }


def _model_name(model: str) -> str:
    try:
        from . import modeldefaults

        return modeldefaults.model_name(model) or model
    except Exception:
        return model


# ---------------------------------------------------------------------------
# What is read
# ---------------------------------------------------------------------------


class _Facts:
    """Every row the graph and the score are made from, read once."""

    def __init__(self, who, now: float, partial: list[str]) -> None:
        from . import archiving, objectindex, owning

        self.who, self.now = who, now
        self.since = now - LOOK_BACK
        st = owning.store()
        self.empty = st is None
        if st is None:
            return
        self.tree = objectindex._Tree(st)
        self._numbered: dict | None = None
        self.kept = archiving.archived(st)
        # The tasks and steps made for somebody else, and everything under one
        # (`rouh/task_origin.py`): off the room unless he shows others' tasks.
        self.made_for = task_origin.hidden(st, self.tree)
        rows = self.tree.rows
        self.by_folder = {r["folder"].strip("/"): i for i, r in rows.items()
                          if r["type"] == "task" and r.get("folder")}
        self.chats = {r["id"]: r for r in _rows(
            "SELECT id, title, last_activity FROM chat WHERE last_activity > %s", (self.since,))}
        # A sub-chat, by the chat it hangs off, and that chat's title: one cut
        # off to be a task's own chat says nothing of where it came from.
        self.forks = {r["chat_id"]: (r["parent_id"], r["title"] or "") for r in _rows(
            "SELECT f.chat_id, f.parent_id, c.title FROM chat_fork f LEFT JOIN chat c ON c.id = f.parent_id "
            "WHERE f.cut_at IS NULL", ())}
        self.chat_task: dict[str, str] = {}
        for task, chats in self.tree.chats.items():
            for c in chats:
                self.chat_task[c] = task
        self.summaries = {r["id"]: r["summary"] or "" for r in _rows(
            "SELECT id, summary FROM task WHERE number IS NOT NULL", ())}
        self.status = {r["id"]: r["status"] or "" for r in _rows("SELECT id, status FROM task", ())}
        self.messages = self._messages()
        self.items, self.links = self._synapse(partial)
        self.card_owner = {r["dst_id"]: (r["src_type"], r["src_id"]) for r in _rows(
            "SELECT src_type, src_id, dst_id FROM link WHERE rel = 'owns' AND dst_type = 'artifact'", ())}
        self.opens = _rows("SELECT rel, object_id, opened_at FROM page_places "
                           "WHERE opened_at > %s", (self.since,))
        self.decisions = self._decisions(partial)
        self.jobs = self._jobs()
        self.own = self._own()
        self.runs = _rows("SELECT id, title, state, started_at, updated_at, ended_at FROM run "
                          "WHERE length(id) = 8 AND (started_at > %s OR ended_at > %s OR state = 'running')",
                          (now - 7 * 86400, now - 7 * 86400))
        self.run_chat = {r["src_id"]: r["dst_id"] for r in _rows(
            "SELECT src_id, dst_id FROM link WHERE rel = 'from' AND src_type = 'run' AND dst_type = 'chat'", ())}
        self.run_task = {r["dst_id"]: r["src_id"] for r in _rows(
            "SELECT src_id, dst_id FROM link WHERE rel = 'owns' AND src_type = 'task' AND dst_type = 'run'", ())}
        try:
            self.changes = _rows("SELECT task_id, field, old, new, at FROM task_change "
                                 "WHERE at > %s AND field = 'status'", (now - 7 * 86400,))
        except Exception:
            self.changes = []

    # --- the numbered task over anything --------------------------------

    def top(self, ident: str | None) -> str | None:
        """``T<number>`` of the numbered task over a task or step, or None."""
        at, seen = ident, 0
        while at and seen < 12:
            row = self.tree.rows.get(at)
            if row is None or row["type"] != "task":
                return None
            if row.get("number") is not None:
                return f"T{row['number']}"
            at, seen = self.tree.owner.get(at), seen + 1
        return None

    def top_of_path(self, path: str) -> str | None:
        """The numbered task a workspace path is in: a folder, or a file in one."""
        p = str(path or "").strip("/")
        while p:
            if p in self.by_folder:
                return self.top(self.by_folder[p])
            p = p.rsplit("/", 1)[0] if "/" in p else ""
        return None

    def task_row(self, node: str) -> dict | None:
        """The row of ``T<number>``."""
        if self._numbered is None:
            self._numbered = {row["number"]: row for row in self.tree.rows.values()
                              if row["type"] == "task" and row.get("number") is not None}
        try:
            return self._numbered.get(int(node[1:]))
        except ValueError:
            return None

    def called(self, ident: str | None) -> str:
        """A task or step as a sentence names it: what it is, its number and its
        whole title, "task 98 Open-sourcing Rouh" or "step 98-07
        Fresh naming strategies". "" when it is neither."""
        from . import searching

        row = self.tree.rows.get(ident or "")
        if row is None or row["type"] != "task":
            return ""
        title = _plain(row.get("title") or row.get("slug") or "")
        if row.get("number") is not None:
            return f"task {row['number']} {title}"
        code = searching.number_of_folder(row.get("folder") or "")
        return f"step {code} {title}" if code else f"step {title}"

    # --- his own words --------------------------------------------------

    def _messages(self) -> list[dict]:
        """His own messages: never a tool's result, Rouh's note in his place, or Stop."""
        from . import memory

        out = []
        for r in _rows("SELECT session_id, ts, content FROM messages WHERE role = 'user' AND NOT note "
                       "AND live AND ts > %s AND content NOT LIKE %s",
                       (self.since, '[{"type": "tool_result%')):
            content = r["content"] or ""
            if not memory._begins_a_question("user", content):
                continue
            try:
                text = memory._plain(json.loads(content))
            except (TypeError, ValueError):
                text = content
            if not text or text.startswith("["):
                continue
            out.append({"chat": r["session_id"], "ts": float(r["ts"]), "text": text})
        return out

    # --- Synapse Master ---------------------------------------------------

    def _synapse(self, partial: list[str]) -> tuple[list[dict], list[dict]]:
        try:
            from .synapse import db, master

            if not db.ready():
                return [], []
            ds = master.of(str(self.who.org_id), str(self.who.user_id))
            if not ds:
                return [], []
            picked = ("dataset_id = %s AND deleted_at IS NULL AND kind <> 'layer' "
                      "AND source_key NOT LIKE '%%#gone-%%' "
                      "AND (kind IN ('task', 'topic', 'person') OR said_at > now() - interval '35 days')")
            items = db.rows("SELECT id::text AS id, kind, source, source_key, title, said_at, "
                            "meta->>'task' AS task, meta->>'end' AS ends, meta->>'from' AS organiser, "
                            "meta->'gcal'->>'calendar_id' AS calendar, alias_of::text AS alias_of, "
                            "CASE WHEN kind = 'person' THEN meta->'emails' END AS emails, "
                            "CASE WHEN kind = 'event' THEN meta->'attendees' END AS attendees, "
                            "coalesce(meta->'gcal'->>'all_day', '') = 'true' AS all_day, "
                            "coalesce(jsonb_array_length(CASE WHEN jsonb_typeof(meta->'attendees') = 'array' "
                            "THEN meta->'attendees' END), 0) AS guests "
                            "FROM synapse.item WHERE " + picked, (ds["id"],))
            links = db.rows(
                "WITH i AS (SELECT id FROM synapse.item WHERE " + picked + ") "
                "SELECT l.src::text AS src, l.dst::text AS dst, l.type, l.strength FROM synapse.link l "
                "JOIN i a ON a.id = l.src JOIN i b ON b.id = l.dst WHERE l.dataset_id = %s",
                (ds["id"], ds["id"]))
            for it in items:
                it["at"] = _epoch(it.get("said_at"))
                it["ends_at"] = _epoch(it.get("ends"))
            return items, links
        except Exception:
            log.exception("Synapse Master could not be read for the control room")
            partial.append("Synapse Master could not be read, so mail, meetings and people are missing.")
            return [], []

    # --- what waits on him ------------------------------------------------

    def _decisions(self, partial: list[str]) -> list[dict]:
        try:
            got = _rows("SELECT id, source, source_id, link, title, question, urgency, due_at, created_at "
                        "FROM decisions WHERE org_id = %s AND user_id = %s AND (status = 'open' OR "
                        "(status = 'snoozed' AND coalesce(snoozed_until, 0) < %s))",
                        (str(self.who.org_id), str(self.who.user_id), self.now))
            mail = {str(r["id"]): r["chat_id"] for r in _rows(
                "SELECT a.id, c.chat_id FROM mail_approvals a JOIN mail_cases c ON c.id = a.case_id "
                "WHERE a.org_id = %s AND a.user_id = %s", (str(self.who.org_id), str(self.who.user_id)))}
            for d in got:
                d["chat"] = mail.get(str(d["source_id"])) if d["source"] in ("mail", "approval") else None
            return got
        except Exception:
            log.exception("what waits on the person could not be read for the control room")
            partial.append("What waits on your answer could not be read.")
            return []


    # --- his Clockwork jobs, and who he is ---------------------------------

    def _jobs(self) -> list[dict]:
        """His Clockwork jobs that run in a chat of their own: the job is a
        piece of work, and that chat is where its runs are."""
        try:
            return _rows("SELECT id, title, what, chat_id, state FROM reminders WHERE org_id = %s "
                         "AND user_id = %s AND coalesce(chat_id, '') NOT IN ('', 'conversation')",
                         (str(self.who.org_id), str(self.who.user_id)))
        except Exception:
            log.exception("his Clockwork jobs could not be read for the control room")
            return []

    def _own(self) -> set[str]:
        """His own addresses and Rouh's: never somebody a card is about."""
        try:
            from . import meeting_prep

            return {a.lower() for a in meeting_prep.own_addresses(self.who)}
        except Exception:
            log.exception("his own addresses could not be read for the control room")
            return set()


def _rows(sql: str, params) -> list[dict]:
    from .synapse import db

    return db.rows(sql, params)


def _epoch(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


# ---------------------------------------------------------------------------
# The graph pass
# ---------------------------------------------------------------------------


def _graph_of(facts: _Facts) -> dict:
    """The groups, kept for `GRAPH_EVERY` per person: the room opens often."""
    key = f"{facts.who.org_id}/{facts.who.user_id}"
    kept = _graphs.get(key)
    if kept and facts.now - kept[0] < GRAPH_EVERY:
        return kept[1]
    got = _graph(facts)
    _graphs[key] = (facts.now, got)
    return got


def _graph(facts: _Facts) -> dict:
    """The direct ties between pieces of work, who each is with, and the cards
    made from them (`_cards`).

    Node names: ``T92`` a numbered task, ``C:<chat>`` a chat, and Synapse's
    ``M:`` mail and ``E:`` calendar events, by their item ids.

    Petar, 9 October 2026, on a card named for a personal task that held a
    client's meetings and a purchase: a cluster is one piece of work,
    never what a chain of people and topics happens to reach. So:

    * Two pieces of work are tied only on direct evidence: a task and its own
      chat, file or card, the same mail thread, the same meeting, or Synapse
      linking the two themselves, weighing `MIN_TIE` or more together.
    * People and topics are not in the graph. A person or topic two tied
      pieces of work share makes the tie stronger (`SHARED_EACH`); it never
      makes one. They are put on a card afterwards, from what is in it.
    * Work, Personal and Rouh are never tied, and a health task only ever to
      its own chats (`_home`).
    """
    direct: dict[tuple[str, str], float] = defaultdict(float)
    best: dict[tuple[str, str], tuple[float, str]] = {}

    def tie(a, b, w, kind):
        if not a or not b or a == b or w <= 0:
            return
        k = (a, b) if a < b else (b, a)
        direct[k] += w
        if w > best.get(k, (0.0, ""))[0]:
            best[k] = (w, kind)

    for chat, task in facts.chat_task.items():
        tie(f"C:{chat}", facts.top(task), OWNS_WEIGHT, "owns")

    item_node: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for it in facts.items:
        kind, src, skey = it["kind"], it["source"], it.get("source_key") or ""
        node = None
        if kind == "task" and skey.startswith("task:"):
            node = facts.top(skey[5:])
        elif src == "rouh-chat" and skey.startswith("chat:"):
            node = f"C:{skey[5:].split(':')[0]}"
        elif src == "rouh-card" and skey.startswith("card:"):
            owner = facts.card_owner.get(skey[5:])
            if owner:
                node = f"C:{owner[1]}" if owner[0] == "chat" else facts.top(owner[1])
        elif src == "rouh-file":
            node = facts.top(it.get("task"))
        elif kind == "mail":
            node = f"M:{it['id']}"
        elif kind == "event":
            node = f"E:{it['id']}"
        elif kind == "person":
            node = f"P:{it['id']}"
        elif kind == "topic":
            node = f"O:{it['id']}"
        if node:
            item_node[it["id"]] = node
            meta.setdefault(node, it)

    # Who each piece of work is linked to, kept beside the graph: everybody
    # it names (`around`), and those who took part, by mail or at a meeting
    # (`involved`). Neither ever ties two pieces of work together.
    around: dict[str, Counter] = defaultdict(Counter)
    involved: dict[str, Counter] = defaultdict(Counter)
    for link in facts.links:
        a, b = item_node.get(link["src"]), item_node.get(link["dst"])
        if not a or not b or a == b:
            continue
        if _side_node(a) or _side_node(b):
            work, other = (b, a) if _side_node(a) else (a, b)
            if _side_node(work):
                continue
            around[work][other] += 1.0
            if link["type"] in _INVOLVED:
                involved[work][other] += 1.0
            continue
        tie(a, b, LINK_WEIGHT.get(link["type"], 0.3) * float(link.get("strength") or 0.5), link["type"])
    for a, b, kind in _same_meetings(meta):
        tie(a, b, SAME_MEETING, kind)

    reach: Counter = Counter()
    for got in around.values():
        reach.update(got.keys())
    hubs = {n for n, k in reach.items()
            if k > (HUB_PERSON if n.startswith("P:") else HUB_TOPIC)}
    people = _people(facts, meta, reach)
    for table in (around, involved):
        for node in table:
            for n in [p for p in table[node] if p in hubs or (people.get(p) or {}).get("skip")]:
                del table[node][n]

    said14 = Counter(m["chat"] for m in facts.messages if m["ts"] > facts.now - 14 * 86400)
    asked = {n for n in (_decision_node(facts, {"meta": meta}, d) for d in facts.decisions) if n}
    opened = {n for n in (facts.top(p.get("object_id")) or facts.top_of_path(p.get("rel") or "")
                          for p in facts.opens if float(p["opened_at"]) > facts.now - QUIET_DAYS * 86400) if n}
    meetings = {n for n, it in meta.items() if n.startswith("E:") and it.get("at")
                and facts.now - LOOK_BACK < it["at"] < facts.now + 21 * 86400}
    nodes = ({n for pair in direct for n in pair} | asked | opened | meetings
             | {f"C:{ch}" for ch in said14}) - {"C:conversation"}
    nodes = {n for n in nodes if not _side_node(n)}
    home = {n: _home(facts, n) for n in nodes}
    edges: dict[tuple[str, str], float] = {}
    for (a, b), w in direct.items():
        if w < MIN_TIE or a not in nodes or b not in nodes or not _may_tie(home[a], home[b]):
            continue
        shared = len(set(around.get(a, ())) & set(around.get(b, ())))
        edges[(a, b)] = w + min(SHARED_EACH * shared, SHARED_MOST)
    graph = {"edges": edges, "meta": meta, "at": facts.now, "home": home,
             "why": {k: best[k][1] for k in edges},
             "around": {n: dict(c) for n, c in around.items()},
             "involved": {n: dict(c) for n, c in involved.items()}, "people": people}
    cards, node_card, why_node = _cards(facts, graph, nodes, said14, asked)
    graph.update(cards=cards, node_card=node_card, why_node=why_node)
    return graph


#: Kinds of link that say somebody took part, not only that they were named.
_INVOLVED = {"from", "to", "cc", "attended", "invited", "spoke", "recorded"}
#: Senders that are a machine or a shared inbox, not a person in the work.
_AUTOMATED = re.compile(r"^(.*[._-])?(no-?reply|do-?not-?reply|mailer-daemon|postmaster|bounces?|notifications?|"
                        r"notify|alerts?|updates|news(letter)?|support|billing|receipts?|invoices?|hello|info|"
                        r"team|calendar-notification)([._-].*)?$", re.I)
_SYSTEM_NAME = re.compile(r"(^|\s|\()(team|support|mail delivery subsystem|no-?reply)\)?\s*$", re.I)
#: How much of a mail thread's or a meeting's people one person or one
#: organisation must be, and at least how many, for it to be mainly theirs.
MAINLY, MAINLY_LINKS = 0.5, 2.0


def _local(address: str) -> str:
    """An address without its +tag: rouh+stripe@x is rouh@x."""
    name, _, domain = str(address or "").strip().lower().partition("@")
    return name.split("+")[0] + "@" + domain


def _people(facts: _Facts, meta: dict[str, dict], reach: Counter) -> dict[str, dict]:
    """Each person a card could name: their name, addresses, outside domains,
    how much they are linked to, and whether to leave them out (`skip`): him,
    Rouh in any of its addresses, and machines and shared inboxes such as
    Gmail Team or a company's notifications."""
    from .meeting_prep import PUBLIC_MAIL, own_domains

    own = {_local(a) for a in facts.own}
    mine = own_domains(own) if own else set()
    out = {}
    for node, it in meta.items():
        if not node.startswith("P:"):
            continue
        emails = [_local(e) for e in (it.get("emails") or []) if "@" in str(e)]
        title = str(it.get("title") or "").strip()
        machine = bool(emails) and all(_AUTOMATED.match(e.split("@")[0]) for e in emails)
        out[node] = {"name": title, "emails": emails, "reach": reach.get(node, 0),
                     "domains": {e.split("@")[1] for e in emails} - PUBLIC_MAIL - mine,
                     "skip": (not title or machine or bool(_SYSTEM_NAME.search(title))
                              or any(e in own for e in emails) or title.lower().split("+")[0] in ("rou", "rouh"))}
    return out


def _cards(facts: _Facts, graph: dict, nodes: set[str], said14: Counter,
           asked: set[str]) -> tuple[list[dict], dict[str, str], dict[str, str]]:
    """The cards, subject first.

    Petar, 9 October 2026, after a card named for a contact's errand held a
    sports contact, Gmail Team and a client's presentation: a card is one
    of two things. A **work** card is one task, one Clockwork job or one
    recurring meeting series, and holds only what belongs to it directly. A
    **topic** card is a subject - an outside organisation's project such as
    Acme, a person such as Sam, an organisation - and holds the tasks, jobs,
    chats and meetings that are about it, as rows. The subject is decided
    first, and then each thing is checked against it, never against its
    neighbours.

    1. The work: each task with its own chats, files, cards and steps; each
       Clockwork job with the chat its runs are in, and nothing else; each
       recurring meeting series.
    2. A loose chat, mail thread or meeting joins a task when it is tied to
       the task itself directly (`MIN_TIE`), or a series when it is tied to
       one of its meetings: never through the task's chats or a neighbour.
    3. What each is about (`_subject`): a task its project, when the project is
       an outside organisation's; a task, job or chat the person its title
       names; a mail thread the person or organisation it is with; a meeting
       the organisation of its guests.
    4. A subject with two things or more is a topic card. Anything else is a
       card of its own: a task, a job or a series always, a loose chat when he
       is talking in it, a meeting or thread when something waits on him.
    Health is always on its own, and nothing crosses the wall (`_home`).
    """
    edges, meta, home = graph["edges"], graph["meta"], graph["home"]
    kinds = graph["why"]
    why: dict[str, str] = {}

    # 1. The work.
    units: dict[str, dict] = {}
    owner: dict[str, str] = {}

    def unit(key, type_, title, core, anchors, side):
        units[key] = {"key": key, "type": type_, "title": title, "core": set(core), "nodes": set(core),
                      "anchors": set(anchors), "home": side}
        for n in core:
            owner[n] = key

    tasks = {n for n in nodes if n.startswith("T")}
    tasks |= {facts.top(t) for c, t in facts.chat_task.items() if f"C:{c}" in nodes} - {None}
    for t in sorted(tasks):
        row = facts.task_row(t)
        if row is None:
            continue
        own = {f"C:{c}": task for c, task in facts.chat_task.items() if facts.top(task) == t}
        for c, task in own.items():
            why[c] = "a chat of " + (facts.called(task) or f"task {row.get('number')}")
        unit(t, "task", row["title"] or t, {t} | set(own), {t}, _home(facts, t))
    for job in facts.jobs:
        chat = f"C:{job['chat_id']}"
        if chat in owner:
            continue
        why[chat] = "the chat this Clockwork job runs in"
        unit(f"job:{job['id']}", "job", str(job.get("title") or job.get("what") or "A Clockwork job"),
             {chat}, set(), home.get(chat))
    series: dict[str, list[str]] = defaultdict(list)
    for n, it in meta.items():
        if n.startswith("E:") and n in nodes:
            event = str(it.get("source_key") or "").rsplit(":", 1)[-1]
            base = _SERIES_TAIL.sub("", event)
            if base != event:
                series[base].append(n)
    for base, evs in sorted(series.items()):
        if len(evs) >= 2:
            evs.sort(key=lambda n: (meta[n].get("at") or 0.0))
            title = str(meta[evs[-1]].get("title") or "A meeting")
            for n in evs:
                why[n] = f"one of the recurring “{_short(title, 60)}”"
            unit(f"series:{base}", "series", title, evs, evs, None)

    # 2. Loose things join the work whose subject item they are tied to.
    loose: dict[str, dict] = {}
    for n in sorted(nodes):
        if n in owner or n.startswith(("T", "M:")):
            continue
        if n.startswith("C:"):
            loose[f"chat:{n[2:]}"] = {"key": f"chat:{n[2:]}", "type": "chat", "nodes": {n},
                                      "title": _title_of(facts, graph, n), "home": home.get(n)}
        elif n.startswith("E:"):
            loose[f"event:{n[2:]}"] = {"key": f"event:{n[2:]}", "type": "meeting", "nodes": {n},
                                       "title": _title_of(facts, graph, n), "home": home.get(n)}
    for thread in _threads({n for n in nodes if n.startswith("M:") and n not in owner}, edges):
        first = min(thread, key=lambda n: ((meta.get(n) or {}).get("at") or 0.0, n))
        loose[f"thread:{first[2:]}"] = {"key": f"thread:{first[2:]}", "type": "mail", "nodes": set(thread),
                                        "title": _title_of(facts, graph, first), "home": None}
    adj: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for (a, b), w in edges.items():
        adj[a].append((w, b))
        adj[b].append((w, a))
    for key in list(loose):
        lu = loose[key]
        pull: Counter = Counter()
        best_tie: dict[tuple[str, str], tuple[float, str, str]] = {}
        for n in lu["nodes"]:
            for w, o in adj.get(n, ()):
                to = owner.get(o)
                if not to or o not in units[to]["anchors"] or str(units[to]["home"] or "").startswith("health:"):
                    continue
                pull[to] += w
                if w > best_tie.get((to, n), (0.0, "", ""))[0]:
                    best_tie[(to, n)] = (w, o, kinds.get((n, o) if n < o else (o, n), ""))
        if not pull:
            continue
        to, w = max(pull.items(), key=lambda x: (x[1], x[0]))
        if w < MIN_TIE:
            continue
        units[to]["nodes"] |= lu["nodes"]
        for n in lu["nodes"]:
            owner[n] = to
            tie_ = best_tie.get((to, n))
            why[n] = _tie_words(facts, graph, tie_[2], tie_[1]) if tie_ else "in the same mail thread"
        del loose[key]

    # 3. What each is about.
    graph["_clients"] = _clients(facts, graph)
    graph["_projects"] = {r["id"]: r for r in facts.tree.rows.values() if r["type"] == "project"}
    subject: dict[str, tuple[str, str, str, str]] = {}
    for key, u in list(units.items()) + list(loose.items()):
        if not str(u.get("home") or "").startswith("health:"):
            got = _subject(facts, graph, u)
            if got:
                subject[key] = got

    # 4. The cards.
    groups: dict[tuple, list[str]] = defaultdict(list)
    for key, sub in subject.items():
        groups[(sub[0], sub[1])].append(key)
    cards: list[dict] = []
    carded: set[str] = set()
    for (stype, sid), keys in sorted(groups.items()):
        sides: dict[str | None, list[str]] = defaultdict(list)
        for k in keys:
            sides[(units.get(k) or loose.get(k)).get("home")].append(k)
        named = [s for s in sides if s]
        if None in sides and named:
            sides[max(named, key=lambda s: (len(sides[s]), s))] += sides.pop(None)
        label = subject[keys[0]][2]
        for side, ks in sorted(sides.items(), key=lambda x: str(x[0])):
            if len(ks) < 2:
                continue
            ns: set[str] = set()
            for k in sorted(ks):
                u = units.get(k) or loose.get(k)
                ns |= u["nodes"]
                if k in loose:
                    for n in u["nodes"]:
                        why[n] = subject[k][3]
                else:
                    why[k] = subject[k][3]
                carded.add(k)
            cards.append({"key": f"topic:{stype}:{sid}:{side or 'none'}", "kind": "topic", "type": stype,
                          "title": label, "nodes": ns, "home": side, "units": sorted(ks)})
    for key, u in sorted(units.items()):
        if key in carded:
            continue
        if u["type"] == "series" and sum(1 for n in u["nodes"] if (meta.get(n) or {}).get("guests")) < 2:
            continue
        cards.append({"key": f"work:{key}", "kind": "work", "type": u["type"], "title": u["title"],
                      "nodes": set(u["nodes"]), "home": u["home"], "units": [key]})
    for key, u in sorted(loose.items()):
        if key in carded:
            continue
        busy = sum(said14[n[2:]] for n in u["nodes"] if n.startswith("C:")) >= 3
        if busy or (u["nodes"] & asked):
            cards.append({"key": f"work:{key}", "kind": "work", "type": u["type"], "title": u["title"],
                          "nodes": set(u["nodes"]), "home": u["home"], "units": [key]})
    node_card = {n: c["key"] for c in cards for n in c["nodes"]}
    return cards, node_card, why


def _subject(facts: _Facts, graph: dict, u: dict) -> tuple[str, str, str, str] | None:
    """What one piece of work is about, as (kind, id, name, why in words), or None.

    Only what the work itself says: its project's own organisation, the person
    its title names, who a mail thread is with, whose organisation a
    meeting's guests are. Never the people a chat happens to mention."""
    meta, people = graph["meta"], graph["people"]
    if u["type"] == "task":
        proj = _client_project(facts, graph, u["key"])
        if proj:
            return ("project", proj["id"], proj["title"] or proj["slug"], f"in the {proj['title'] or proj['slug']} project")
    if u["type"] in ("task", "job", "chat"):
        linked: Counter = Counter()
        for n in u["nodes"]:
            linked.update((graph["around"].get(n) or {}))
        p = _named_in(graph, u["title"], linked)
        if p:
            return ("person", p[2:], people[p]["name"], f"about {people[p]['name']}")
        return None
    if u["type"] == "mail":
        with_: Counter = Counter()
        for n in u["nodes"]:
            with_.update((graph["involved"].get(n) or {}))
        return _mostly(graph, with_, Counter())
    # A meeting, or a series of them: the organisation its guests are from.
    domains: Counter = Counter()
    for n in u["nodes"]:
        domains.update(_guest_domains(meta.get(n) or {}, facts.own))
    got = _mostly(graph, Counter(), domains, least=1.0)
    if got:
        return got
    p = _named_in(graph, u["title"], Counter())
    return ("person", p[2:], people[p]["name"], f"with {people[p]['name']}") if p else None


def _mostly(graph: dict, persons: Counter, domains: Counter,
            least: float = MAINLY_LINKS) -> tuple[str, str, str, str] | None:
    """The one person, else the one outside organisation, that most of these
    people are (`MAINLY`), with at least `MAINLY_LINKS` behind it."""
    people = graph["people"]
    for p, w in persons.items():
        for d in (people.get(p) or {}).get("domains") or ():
            domains[d] += w
    if persons:
        p, w = max(persons.items(), key=lambda x: (x[1], x[0]))
        if w >= MAINLY_LINKS and w >= MAINLY * sum(persons.values()):
            return ("person", p[2:], people[p]["name"], f"with {people[p]['name']}")
    if domains:
        d, w = max(domains.items(), key=lambda x: (x[1], x[0]))
        if w >= least and w >= MAINLY * sum(domains.values()):
            org = _org_project(graph, d)
            if org:
                return ("project", org["id"], org["title"] or org["slug"], f"with people at {d}")
            return ("org", d, d, f"with people at {d}")
    return None


def _client_project(facts: _Facts, graph: dict, task: str) -> dict | None:
    """The project a task is in, when that project is an outside
    organisation's: one named for a domain its meetings or mail come from, as
    Acme is acme.example's. Misc, Sales or the owner's own company's are drawers, not subjects."""
    row = facts.task_row(task)
    at, seen = facts.tree.owner.get(row["id"]) if row else None, 0
    clients = graph.get("_clients") or {}
    while at and seen < 12:
        up = facts.tree.rows.get(at)
        if up and up["type"] == "project" and up["id"] in clients.values():
            return up
        at, seen = facts.tree.owner.get(at), seen + 1
    return None


def _clients(facts: _Facts, graph: dict) -> dict[str, str]:
    """Outside domains that have a project of their own, by the project's
    name: {"acme.example": <the Acme project's id>}."""
    from .meeting_prep import own_domains

    seen: set[str] = set()
    for p in graph["people"].values():
        if not p["skip"]:
            seen |= p["domains"]
    for it in graph["meta"].values():
        if it.get("kind") == "event":
            seen |= set(_guest_domains(it, facts.own))
    mine = {d.split(".")[0] for d in own_domains({_local(a) for a in facts.own})}
    by_label: dict[str, str] = {}
    for row in facts.tree.rows.values():
        slug = str(row.get("slug") or "").lower()
        if row["type"] == "project" and facts.tree.owner.get(row["id"]) and slug and slug not in mine:
            by_label[slug] = row["id"]
    return {d: by_label[d.split(".")[0]] for d in seen if d.split(".")[0] in by_label}


def _org_project(graph: dict, domain: str) -> dict | None:
    """The project an outside organisation has, if it has one."""
    pid = (graph.get("_clients") or {}).get(domain)
    return graph.get("_projects", {}).get(pid) if pid else None


def _named_in(graph: dict, title: str, linked: Counter) -> str | None:
    """The person a title names: their whole name anywhere in it, or their
    first name when they are linked to the work too; the fullest match wins."""
    words = set(re.findall(r"\w+", str(title or "").lower()))
    best, got = (0, 0.0), None
    for p, info in (graph.get("people") or {}).items():
        if info["skip"]:
            continue
        parts = re.findall(r"\w+", info["name"].lower())
        if not parts or len(parts[0]) < 3 or parts[0] not in words:
            continue
        whole = len(parts) >= 2 and all(x in words for x in parts)
        if not whole and not linked.get(p):
            continue
        rank = (len(parts) if whole else 1, linked.get(p, 0.0) + 0.001 * info.get("reach", 0))
        if rank > best:
            best, got = rank, p
    return got


def _threads(mails: set[str], edges: dict[tuple[str, str], float]) -> list[set[str]]:
    """Mail tied to mail directly (one thread, one reply to another) as one thing."""
    up = {m: m for m in mails}

    def root(m):
        while up[m] != m:
            up[m] = up[up[m]]
            m = up[m]
        return m

    for a, b in edges:
        if a in up and b in up:
            up[root(a)] = root(b)
    got: dict[str, set[str]] = defaultdict(set)
    for m in mails:
        got[root(m)].add(m)
    return list(got.values())


def _guest_domains(it: dict, own: set[str]) -> Counter:
    """The outside organisations at a meeting, by its guests' and organiser's
    addresses: how many of its people come from each."""
    from .meeting_prep import PUBLIC_MAIL, own_domains

    mine = own_domains(own) if own else set()
    who = [str(a).lower() for a in (it.get("attendees") or []) if "@" in str(a)]
    if "@" in str(it.get("organiser") or ""):
        who.append(str(it["organiser"]).lower())
    cal = str(it.get("calendar") or "").lower()
    if "@" in cal:
        mine = mine | {cal.split("@")[1]}
    out: Counter = Counter()
    for a in set(who):
        d = a.split("@")[1]
        if a not in own and d not in PUBLIC_MAIL and d not in mine and not _AUTOMATED.match(a.split("@")[0]):
            out[d] += 1
    return out


def _tie_words(facts: _Facts, graph: dict, kind: str, other: str) -> str:
    """Why a loose chat, mail or meeting is with a piece of work: its tie to it."""
    name = _short(_title_of(facts, graph, other), 60)
    if other.startswith("T"):
        what = "task " + str((facts.task_row(other) or {}).get("number")) + " "
    elif kind in ("series", "slot"):
        what = ""
    else:
        what = "the meeting " if other.startswith("E:") else "the mail " if other.startswith("M:") else "the chat "
    return f"{_WHY_WORDS.get(kind, 'linked to')} {what}“{name}”"


def _side_node(node: str) -> bool:
    """A person or a topic, which the graph is never made of."""
    return node.startswith(("P:", "O:"))


def _home(facts: _Facts, node: str) -> str | None:
    """Which side of the wall a piece of work is on: the column its task is in
    (``work``, ``private``, ``rouh``), ``health:T38`` for a health task and
    its own chats, and None for mail, meetings and chats no task holds."""
    if node.startswith("C:"):
        task = facts.chat_task.get(node[2:])
        node = facts.top(task) if task else None
    if not node or not node.startswith("T"):
        return None
    row = facts.task_row(node)
    if row is None:
        return None
    slugs, at, seen = [], facts.tree.owner.get(row["id"]), 0
    while at and seen < 12:
        up = facts.tree.rows.get(at)
        if up is None:
            break
        slugs.append(str(up.get("slug") or "").lower())
        at, seen = facts.tree.owner.get(at), seen + 1
    if "health" in slugs:
        return f"health:{node}"
    return slugs[-1] if slugs and slugs[-1] else None


def _may_tie(a: str | None, b: str | None) -> bool:
    """Whether two pieces of work on these sides may ever share a cluster."""
    if a and b:
        return a == b
    return not str(a or b or "").startswith("health:")


_SERIES_TAIL = re.compile(r"_R?\d{8}(T\d{6}Z?)?$")


def _same_meetings(meta: dict[str, dict]) -> list[tuple[str, str, str]]:
    """Pairs of meetings that are one: the instances of one recurring event,
    and a meeting he put in his calendar himself, with no guests, at exactly
    the time of one he was invited to."""
    series: dict[str, list[tuple[float, str]]] = defaultdict(list)
    slots: dict[tuple[float, float], list[tuple[int, str]]] = defaultdict(list)
    for node, it in meta.items():
        if not node.startswith("E:"):
            continue
        event = str(it.get("source_key") or "").rsplit(":", 1)[-1]
        base = _SERIES_TAIL.sub("", event)
        if base and base != event:
            series[base].append((it.get("at") or 0.0, node))
        if it.get("at") and it.get("ends_at") and not it.get("all_day"):
            slots[(it["at"], it["ends_at"])].append((int(it.get("guests") or 0), node))
    out = []
    for got in series.values():
        got.sort()
        out += [(a[1], b[1], "series") for a, b in zip(got, got[1:])]
    for got in slots.values():
        mine = [n for g, n in got if g == 0]
        theirs = [n for g, n in got if g > 0]
        if len(got) == 2 and mine:
            out.append((got[0][1], got[1][1], "slot"))
        elif len(mine) == 1 and len(theirs) == 1:
            out.append((mine[0], theirs[0], "slot"))
    return out


# ---------------------------------------------------------------------------
# Cards and their names
# ---------------------------------------------------------------------------


def _place(graph: dict, named: dict) -> dict:
    """Which card each node is on, and what the naming pass said of each card.

    A card's key is its subject (`_cards`), so it is the same card from one
    opening to the next whatever else moves, and a name is only ever kept for
    the subject it was given to: never for whatever a group of links happens
    to hold next time."""
    before = {c["key"]: c for c in named.get("clusters") or [] if isinstance(c, dict) and c.get("key")}
    return {"node_cluster": dict(graph.get("node_card") or {}), "named": before,
            "cards": {c["key"]: c for c in graph.get("cards") or []}}


# ---------------------------------------------------------------------------
# The score, and each card
# ---------------------------------------------------------------------------


def _sat(x: float, k: float) -> float:
    return x / (x + k) if x > 0 else 0.0


def _size(score: float, was: str | None = None) -> str:
    plain = next((name for name, start in SIZES if score >= start), "quiet")
    if not was or was == plain:
        return plain
    bounds = dict(SIZES)
    bounds["quiet"] = 0.0
    order = [name for name, _ in SIZES] + ["quiet"]
    if was not in order:
        return plain
    lo = bounds[was]
    hi = bounds[order[order.index(was) - 1]] if order.index(was) > 0 else 9.0
    return was if lo - STICK <= score < hi + STICK else plain


def _score(facts: _Facts, graph: dict, placed: dict, seen: dict, *,
           show_others: bool = False) -> list[dict]:
    """Every card, scored and filled in. A task made for somebody else
    (`rouh/task_origin.py`) is marked with who it was for; with `show_others`
    off it is left off, and so are its card, its chats and the lines that
    point at it, and a card it leaves with nothing in it is not drawn."""
    now = facts.now
    others = facts.made_for
    others_at = {addressing.url_for("task", ident, (facts.tree.rows.get(ident) or {}).get("folder") or ""): ident
                 for ident in others}
    nc = placed["node_cluster"]
    C: dict[str, dict] = defaultdict(lambda: {
        "msgs": [], "days": set(), "opens": [], "waiting": [], "events": [], "runs7": 0,
        "running": 0, "done": [], "tasks": set(), "chats": Counter(), "urgent": 0, "unhappy": 0,
        "msgs7": 0, "people": Counter(), "fresh": 0.0, "pinned": 0, "news": [], "last_you": 0.0,
        "meetings": [], "nodes": set(), "runs": [], "pages": {}})

    involved = graph.get("involved") or {}
    for n, key in nc.items():
        c = C[key]
        c["nodes"].add(n)
        meta = graph["meta"].get(n) or {}
        # The people on a card are the ones its own work is linked to, put
        # there after the clusters are made: they never made one.
        for p, k in (involved.get(n) or {}).items():
            if p.startswith("P:"):
                c["people"][p] += k
        if n.startswith("T"):
            c["tasks"].add(n)
        elif n.startswith("E:") and meta.get("at"):
            at = meta["at"]
            c["meetings"].append((at, meta.get("title") or "A meeting", n))
            if now - 2 * 3600 < at < now + 21 * 86400:
                c["events"].append((at, meta.get("title") or "A meeting", n))
            if now - QUIET_DAYS * 86400 < at <= now + QUIET_DAYS * 86400:
                c["fresh"] = max(c["fresh"], min(at, now))
        elif n.startswith("M:") and meta.get("at") and meta["at"] <= now:
            c["fresh"] = max(c["fresh"], meta["at"])

    try:
        from . import clock

        zone = clock.zone_of(facts.who)
    except Exception:
        zone = None
    for m in facts.messages:
        key = nc.get(f"C:{m['chat']}")
        if not key:
            continue
        c = C[key]
        age = (now - m["ts"]) / 86400
        c["msgs"].append(age)
        c["last_you"] = max(c["last_you"], m["ts"])
        if age <= 14:
            c["chats"][m["chat"]] += 1
        if age <= 7:
            c["days"].add(datetime.fromtimestamp(m["ts"], zone).date())
            c["msgs7"] += 1
            if _URGENT.search(m["text"]):
                c["urgent"] += 1
            if _UNHAPPY.search(m["text"]):
                c["unhappy"] += 1

    for p in facts.opens:
        node = facts.top(p.get("object_id")) or facts.top_of_path(p.get("rel") or "")
        key = nc.get(node) if node else None
        if key:
            at = float(p["opened_at"])
            C[key]["opens"].append(at)
            C[key]["last_you"] = max(C[key]["last_you"], at)
            if at > C[key]["pages"].get(p["rel"], (0.0, ""))[0]:
                C[key]["pages"][p["rel"]] = (at, p.get("object_id") or "")

    asked: set[str] = set()
    for d in facts.decisions:
        node = _decision_node(facts, graph, d)
        key = nc.get(node) if node else None
        if not key:
            continue
        if node and node.startswith("T"):
            asked.add(node)
        due = float(d["due_at"]) if d.get("due_at") else None
        C[key]["waiting"].append({
            "text": _first_sentence(d.get("question") or d.get("title") or "A question"),
            "when": _urgency_words(d.get("urgency"), due),
            "href": d.get("link") or "/decisions",
            "w": URGENCY.get(d.get("urgency") or "soon", 0.6),
            "at": float(d.get("created_at") or 0.0)})
        if float(d.get("created_at") or 0.0) > C[key]["fresh"]:
            C[key]["fresh"] = float(d["created_at"])
        if due and due <= now + QUIET_DAYS * 86400:
            C[key]["fresh"] = max(C[key]["fresh"], min(due, now))

    # A task marked waiting on him with no question written for it.
    for ident, row in facts.tree.rows.items():
        if row["type"] != "task" or ident in facts.kept or facts.status.get(ident) != "waiting":
            continue
        node = facts.top(ident)
        key = nc.get(node) if node else None
        if not key or node in asked:
            continue
        C[key]["waiting"].append({
            "text": f"{_upper(facts.called(ident))} is marked waiting on you, with no question written",
            "when": "", "href": addressing.url_for("task", ident, row.get("folder") or ""),
            "w": MARKED_WAITING, "at": 0.0})
        asked.add(node)

    # A pin anywhere under a numbered task counts for the task's cluster, once.
    pinned_in: Counter = Counter()
    for ident, row in facts.tree.rows.items():
        if row["type"] == "task" and row.get("pinned") and ident not in facts.kept:
            node = facts.top(ident)
            key = nc.get(node) if node else None
            if key:
                pinned_in[key] += 1

    # Rouh's own work: said on the card, never counted in its size.
    for r in facts.runs:
        chat = facts.run_chat.get(r["id"])
        node = f"C:{chat}" if chat else facts.top(facts.run_task.get(r["id"]))
        key = nc.get(node) if node else None
        if not key:
            continue
        moved = float(r.get("updated_at") or r.get("started_at") or 0.0)
        if float(r.get("started_at") or 0.0) > now - 7 * 86400:
            C[key]["runs7"] += 1
        if r["state"] == "running" and now - moved < 3600:
            C[key]["running"] += 1
        # Each run its own line in the opened card's Runs: what it is called,
        # how it stands, and what it was started for.
        owner = facts.called(facts.run_task.get(r["id"]))
        title = (facts.chats.get(chat) or {}).get("title") if chat else ""
        C[key]["runs"].append({
            "title": _short(r["title"] or "A run", 110),
            "href": f"/run/{r['id']}",
            "state": _RUN_WORDS.get(r["state"], r["state"]),
            "running": r["state"] == "running",
            "at": float(r.get("ended_at") or moved),
            "why": f"for {owner}" if owner else f"from the chat “{_short(_plain(title), 60)}”" if title else ""})
    for ch in facts.changes:
        node = facts.top(ch["task_id"])
        key = nc.get(node) if node else None
        row = facts.tree.rows.get(ch["task_id"])
        if not key or row is None or ch.get("new") not in ("done", "waiting", "stopped"):
            continue
        said = f"{_upper(facts.called(ch['task_id']))} is now {_STATE_WORDS[ch['new']]}"
        C[key]["news"].append((float(ch["at"]), said,
                               addressing.url_for("task", ch["task_id"], row.get("folder") or "")))

    total7 = sum(c["msgs7"] for c in C.values()) or 1
    base = (sum(c["urgent"] + c["unhappy"] for c in C.values()) / total7) or 1.0
    looked = _looked(seen, now)
    sizes = seen.get("sizes") or {}
    named = placed["named"]
    whys = graph.get("why_node") or {}
    jobs = {f"job:{j['id']}": j for j in facts.jobs}

    out = []
    for key, c in C.items():
        act = sum(0.5 ** (a / HALF_LIFE) for a in c["msgs"])
        opens7 = [t for t in c["opens"] if t > now - 7 * 86400]
        nxt = min(c["events"]) if c["events"] else None
        days_to = (nxt[0] - now) / 86400 if nxt else None
        parts = {
            "activity": _sat(act, 8),
            "waiting": _sat(sum(w["w"] for w in c["waiting"]), 1.5),
            "returns": _sat(len(c["days"]) + len(opens7), 4),
            "date": math.exp(-max(days_to, 0) / 3) if days_to is not None else 0.0,
            "tone": (min(max(((c["urgent"] + c["unhappy"]) / c["msgs7"]) / base - 1, 0), 1)
                     * min(c["msgs7"] / 5, 1)) if c["msgs7"] else 0.0,
        }
        boost = PIN_BOOST if pinned_in[key] else 0.0
        score = sum(WEIGHTS[k] * v for k, v in parts.items()) + boost
        fresh = max(c["fresh"], c["last_you"])
        tasks = _tasks(facts, c["tasks"], whys)
        card = placed["cards"].get(key) or {}
        # A work card that is one task made for somebody else is theirs, whole.
        made_for = None
        if card.get("kind") != "topic" and card.get("type") == "task":
            own = facts.task_row(str((card.get("units") or [""])[0])) or {}
            made_for = task_origin.public(others.get(own.get("id") or ""))
        if made_for and not show_others:
            continue
        waiting = sorted(c["waiting"], key=lambda w: (-w["w"], -w["at"]))
        news = sorted(c["news"], reverse=True)
        chats = _chats(facts, c["chats"], whys)
        if not show_others:
            tasks = [t for t in tasks if not t.get("made_for")]
            waiting = [w for w in waiting if w.get("href") not in others_at]
            news = [n for n in news if n[2] not in others_at]
            chats = [ch for ch in chats if facts.chat_task.get(ch["id"]) not in others]
            if not (tasks or chats or waiting or c["events"]) and \
                    not any(u in jobs for u in card.get("units") or []):
                continue
        rows = [{"title": str(jobs[u].get("title") or jobs[u].get("what") or "A Clockwork job"),
                 "href": "/clockwork", "state": "paused" if jobs[u].get("state") == "paused" else "",
                 "why": whys.get(u, "")} for u in card.get("units") or [] if u in jobs]
        if not tasks and not rows and not chats and not waiting and not c["events"]:
            continue
        info = named.get(key) or {}
        # A work card is called what its task, job or series is called, so its
        # name and what is in it never disagree; a topic card is the naming
        # pass's, or its subject's own name until then.
        name = (str(info.get("name") or "") if card.get("kind") == "topic" else "") \
            or _short(_plain(str(card.get("title") or "")), 80) or "Something new"
        if card.get("kind") != "topic" and card.get("type") == "task":
            number = (facts.task_row(str((card.get("units") or [""])[0])) or {}).get("number")
            if number is not None:
                name = f"{number} {name}"
        out.append({
            "key": key,
            "name": name,
            "kind": card.get("kind") or "work",
            "type": card.get("type") or "",
            "provisional": not info,
            "side": _card_side(facts, card, c["tasks"], info),
            "headline": str(info.get("headline") or ""),
            "score": round(score, 3),
            "size": _size(score, sizes.get(key)),
            "parts": {k: round(v, 3) for k, v in parts.items()},
            "boost": boost,
            "pinned": pinned_in[key],
            "made_for": made_for,
            "pace": _pace(c["msgs"]),
            "waiting": [{k: w[k] for k in ("text", "when", "href")} for w in waiting],
            "dates": [{"at": at, "what": what, "why": whys.get(n, "")}
                      for at, what, n in sorted(c["events"])[:4]],
            "meetings": [{"at": at, "what": what, "why": whys.get(n, "")}
                         for at, what, n in sorted(c["meetings"], key=lambda m: abs(m[0] - now))[:8]],
            "since": [{"at": at, "text": text, "href": href}
                      for at, text, href in news if at > looked][:6],
            "tasks": tasks,
            "jobs": rows,
            "chats": chats,
            "runs": sorted(c["runs"], key=lambda r: (not r["running"], -r["at"]))[:6],
            "pages": _pages(facts, c["pages"]),
            "people": _card_people(graph, card, c["people"]),
            "rouh": {"runs_7d": c["runs7"], "running": c["running"]},
            "evidence": {
                "messages_14d": sum(1 for a in c["msgs"] if a <= 14),
                "messages_48h": sum(1 for a in c["msgs"] if a <= 2),
                "days_7d": len(c["days"]),
                "opened_7d": len(opens7),
                "last_you": c["last_you"] or None,
            },
            "fresh": fresh or None,
            "gone": not fresh or fresh < now - QUIET_DAYS * 86400,
        })
    return out


def _decision_node(facts: _Facts, graph: dict, d: dict) -> str | None:
    """What a question waiting on him is about, as a node of the graph."""
    link = str(d.get("link") or "")
    if link.startswith("/task/"):
        got = facts.top_of_path(link[len("/task/"):])
        if got:
            return got
    if d.get("source") == "task":
        got = facts.top(str(d.get("source_id") or ""))
        if got:
            return got
    if d.get("chat"):
        return f"C:{d['chat']}"
    if d.get("source") == "meeting":
        event = str(d.get("source_id") or "").split("@")[0]
        for node, meta in graph["meta"].items():
            if node.startswith("E:") and str(meta.get("source_key") or "").endswith(":" + event):
                return node
    return None


def _chats(facts: _Facts, said: Counter, whys: dict[str, str]) -> list[dict]:
    """The chats he talked in most these two weeks. A sub-chat says which chat
    it came off (`parent`), so the page sets it in under that chat when both
    are listed, and names the chat when it is not."""
    out = []
    for ch, _n in said.most_common(8):
        row = facts.chats.get(ch) or {}
        parent, parent_title = facts.forks.get(ch, ("", ""))
        out.append({"id": ch, "title": row.get("title") or "A chat",
                    "href": addressing.url_for("chat", ch), "at": row.get("last_activity"),
                    "why": whys.get(f"C:{ch}", ""), "parent": parent or "",
                    "parent_title": _short(_plain(parent_title), 80) if parent else ""})
    return out


def _pages(facts: _Facts, opened: dict[str, tuple[float, str]]) -> list[dict]:
    """The pages he opened here in the last two weeks, the latest first, each
    called what its own title says, with the task or step it is in."""
    from . import pageplaces, pages

    base = pageplaces._root()
    out = []
    for rel, (at, ident) in sorted(opened.items(), key=lambda x: -x[1][0]):
        if at < facts.now - 14 * 86400 or len(out) >= 6:
            break
        title = (pages.title_of(base / rel) if base else "") or rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        where = facts.called(ident) or facts.called(facts.by_folder.get(rel.rsplit("/", 1)[0]))
        out.append({"title": _short(title, 110), "href": pages.url_for(rel), "at": at,
                    "why": f"in {where}" if where else ""})
    return out


def _tasks(facts: _Facts, nodes: set[str], whys: dict[str, str] | None = None) -> list[dict]:
    """Its live numbered tasks, the ones worked on last first."""
    out = []
    for node in nodes:
        row = facts.task_row(node)
        if row is None or row["id"] in facts.kept:
            continue
        pinned = bool(row.get("pinned")) or any(
            facts.tree.rows[k].get("pinned") for k in _under(facts, row["id"]) if k not in facts.kept)
        state = facts.status.get(row["id"]) or ""
        out.append({"n": row.get("number"), "title": row["title"] or row.get("slug") or row["id"],
                    "href": addressing.url_for("task", row["id"], row.get("folder") or ""),
                    "state": _STATE_WORDS.get(state, ""), "pinned": pinned,
                    "why": (whys or {}).get(node, ""), "order": _STATE_ORDER.get(state, 2),
                    # Made for somebody else (`rouh/task_origin.py`), or None.
                    "made_for": task_origin.public(facts.made_for.get(row["id"]))})
    # What waits on him first, done last, and the newest tasks first within each.
    out.sort(key=lambda t: (t.pop("order"), -(t["n"] or 0)))
    return out


def _under(facts: _Facts, ident: str) -> list[str]:
    out, stack = [], list(facts.tree.under.get(ident, []))
    while stack and len(out) < 500:
        k = stack.pop()
        out.append(k)
        stack.extend(facts.tree.under.get(k, []))
    return out


_STATE_ORDER = {"waiting": 0, "in-progress": 1, "not-started": 2, "stopped": 3, "done": 4}
_STATE_WORDS = {"waiting": "waiting on you", "in-progress": "in progress", "not-started": "not started",
                "stopped": "stopped", "done": "done"}
#: How a run stands, in words.
_RUN_WORDS = {"running": "running", "waiting": "waiting on you", "done": "finished", "failed": "failed",
              "conflict": "stopped on a conflict"}


def _upper(text: str) -> str:
    return text[:1].upper() + text[1:]


def _looked(seen: dict, now: float) -> float:
    """When he looked before, which a card's Task changes are counted from: a
    day ago when he never has."""
    return float(seen.get("prev") or 0.0) or now - 86400


def _side(facts: _Facts, nodes: set[str], info: dict) -> str:
    """Work, Personal or Rouh: the column most of its tasks are in, else what the naming pass said."""
    votes: Counter = Counter()
    for node in nodes:
        row = facts.task_row(node)
        if row is None:
            continue
        at, seen = facts.tree.owner.get(row["id"]), 0
        top = None
        while at and seen < 10:
            top = facts.tree.rows.get(at)
            at, seen = facts.tree.owner.get(at), seen + 1
        name = str((top or {}).get("slug") or (top or {}).get("title") or "").lower()
        name = "personal" if name == "private" else name
        if name in ("work", "personal", "rouh"):
            votes[name] += 0.5 if row["id"] in facts.kept else 1.0
    if votes:
        return votes.most_common(1)[0][0]
    said = str(info.get("side") or "").lower()
    return said if said in ("work", "personal", "rouh") else "work"


def _card_side(facts: _Facts, card: dict, tasks: set[str], info: dict) -> str:
    """Work, Personal or Rouh: the side of the wall the card is on."""
    home = str(card.get("home") or "")
    if home.startswith("health:") or home == "private":
        return "personal"
    if home in ("work", "rouh"):
        return home
    if tasks:
        return _side(facts, tasks, info)
    said = str(info.get("side") or "").lower()
    if said in ("work", "personal", "rouh"):
        return said
    return "personal" if card.get("type") in ("person", "job") else "work"


def _card_people(graph: dict, card: dict, counted: Counter) -> list[str]:
    """The people actually in a card's subject: never him, Rouh, a machine or
    a shared inbox (`_people`), and never somebody only named once in passing.
    On a person's card they come first; on an organisation's, its own people."""
    people = graph.get("people") or {}
    first = f"P:{card['key'].split(':')[2]}" if card.get("type") == "person" else ""
    org = card["key"].split(":")[2] if card.get("type") == "org" else ""
    if card.get("type") == "project":
        org = next((d for d, pid in (graph.get("_clients") or {}).items() if pid == card["key"].split(":")[2]), "")
    out = []
    if first in people and not people[first]["skip"]:
        out.append(people[first]["name"])
    for p, w in sorted(counted.items(), key=lambda x: (x[0] != first, -x[1], x[0])):
        info = people.get(p) or {}
        if info.get("skip") or not info.get("name"):
            continue
        if p != first and w < 1.0:
            continue
        if org and p != first and org not in info.get("domains", ()) and w < 2.0:
            continue
        if info["name"] not in out:
            out.append(info["name"])
    return out[:8]


def _title_of(facts: _Facts, graph: dict, node: str) -> str:
    """What a task, chat or meeting is called, as words: no number, no emoji."""
    if node.startswith("T"):
        row = facts.task_row(node)
        return str((row or {}).get("title") or "")
    if node.startswith("C:"):
        title = (facts.chats.get(node[2:]) or {}).get("title") or ""
    else:
        title = (graph["meta"].get(node) or {}).get("title") or ""
    return re.sub(r"^[^\w(\"“'‘]+", "", str(title)).strip()


#: Why a piece of work is in its cluster, by the kind of its strongest tie there.
_WHY_WORDS = {"in_thread": "same mail thread as", "attached": "attached to", "in": "in",
              "continues": "carries on from", "follows_up": "follows up on", "updates": "updates",
              "contradicts": "argues with", "about": "linked several times to",
              "series": "same recurring meeting as", "slot": "same meeting as"}


def _pace(msgs: list[float]) -> dict:
    """His messages this week against the week before, and the words for it
    when they differ enough to say: busier or quieter this week."""
    now7 = sum(1 for a in msgs if a <= 7)
    before = sum(1 for a in msgs if 7 < a <= 14)
    says = ""
    if now7 >= before + PACE_MORE and now7 >= PACE_RATIO * before:
        says = "busier this week"
    elif before >= now7 + PACE_MORE and before >= PACE_RATIO * now7:
        says = "quieter this week"
    return {"this_week": now7, "week_before": before, "says": says}


def _urgency_words(urgency, due: float | None) -> str:
    if urgency in ("now", "today"):
        return "today"
    if due:
        return "by " + datetime.fromtimestamp(due).strftime("%-d %B")
    return ""


def _plain(text: str) -> str:
    return " ".join(str(text or "").replace("**", "").split())


def _first_sentence(text: str, most: int = 150) -> str:
    """A question as a line: its first sentence when that is a whole question."""
    text = _plain(text)
    first = re.match(r"^(.{12,}?[?.!])(\s|$)", text)
    return _short(first.group(1) if first else text, most)


def _short(text: str, most: int) -> str:
    text = _plain(text)
    return text if len(text) <= most else text[:most - 1].rsplit(" ", 1)[0] + "…"


# ---------------------------------------------------------------------------
# What is kept for him
# ---------------------------------------------------------------------------


def _setting(who, name: str) -> dict:
    from .models import UserSetting

    try:
        value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "",
                                            name=name).values_list("value", flat=True).first())
        held = json.loads(value) if value else {}
    except Exception:
        log.exception("%s could not be read", name)
        held = {}
    return held if isinstance(held, dict) else {}


def _put(who, name: str, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=name,
                     value=json.dumps(held, ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _remember(who, seen: dict, shown: list[dict], now: float) -> None:
    """That he looked, and the size each card had. Two openings within half
    an hour are one look, so "since you last looked" does not empty itself on
    a second glance."""
    last = float(seen.get("last") or 0.0)
    held = {"prev": seen.get("prev") if now - last < 1800 else (last or None), "last": now,
            "sizes": {c["key"]: c["size"] for c in shown}}
    try:
        _put(who, SEEN, held)
    except Exception:
        log.exception("when the control room was looked at could not be written down")


# ---------------------------------------------------------------------------
# The naming pass
# ---------------------------------------------------------------------------

SYSTEM = """You name the cards on the Control Room's map of what ‹owner› is working on.

Rouh has already decided every card, subject first, and you do not change what is on one. Each card is one of two kinds:
- A topic card: a subject - a project, a person, an outside organisation - with the tasks, Clockwork jobs, chats and meetings that are mainly about it as its rows.
- A work card: one task, one Clockwork job, one recurring meeting series or one chat, holding only what belongs to it directly. It is called what that task or job is called, and you never rename it.

For each card:
- A name, for a topic card only: what ‹owner› would call the subject ‹himself›, one to four words, such as "Acme Bank", "Sam", "Northwind". Name the subject, never one of its rows. When a card says the name it had, keep it unless it is now wrong.
- A side, only for a card whose side is "unknown": "work" for ‹his› company and clients, "personal" for ‹his› life, "rouh" for building Rouh itself.
- A headline: one line, at most 110 characters, of where it stands now, from the facts given: the next meeting, what waits on ‹him›, what changed. ‹Owner› reads it under the words "Where it stands", so write it to ‹him›, as "you", in plain words, no hype, no advice and nothing ‹he› should do: the map mirrors, it never recommends. Name a task with its number and its title, never by a code alone.

Answer with one JSON object and nothing else:
{"cards": [{"key": "<the card's key, as given>", "name": "<topic cards only>", "side": "<only when unknown>", "headline": "..."}]}"""


def due(who, *, now: float | None = None) -> str:
    """Why the naming pass should run now, or "" when it need not."""
    now = time.time() if now is None else now
    named = _setting(who, NAMED)
    at = float(named.get("named_at") or 0.0)
    if not at:
        return "never named"
    if now - at > 20 * 3600:
        return "a day old"
    if now - at > 3600:
        seen = _setting(who, SEEN)
        known = {c.get("key") for c in named.get("clusters") or [] if isinstance(c, dict)}
        if any(k not in known and v != "quiet" for k, v in (seen.get("sizes") or {}).items()):
            return "new clusters"
    return ""


def kick(who, why: str = "") -> bool:
    """Start the naming pass in the background, unless it is already running."""
    key = f"{who.org_id}/{who.user_id}"
    if key in _naming:
        return False
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    task = loop.create_task(name(who, why=why or "asked"))
    # Held until it ends: a task nothing refers to may be collected half way.
    _running.add(task)
    task.add_done_callback(_running.discard)
    return True


async def name(who, *, why: str = "", cfg=None) -> dict:
    """Ask the model to name the clusters, write the headlines, and keep what it said.

    ``{"ok": bool, "said": str, "clusters": n}``. Never raises: the room keeps
    what was named last time whatever happens here.
    """
    key = f"{who.org_id}/{who.user_id}"
    if key in _naming:
        return {"ok": False, "said": "already naming", "clusters": 0}
    _naming.add(key)
    try:
        return await _name(who, why, cfg)
    except Exception as exc:
        log.exception("the control room's naming pass failed")
        return {"ok": False, "said": f"failed: {exc.__class__.__name__}", "clusters": 0}
    finally:
        _naming.discard(key)


async def _name(who, why: str, cfg) -> dict:
    from . import llm
    from .config import config

    cfg = cfg or config
    asked, groups, graph = await asyncio.to_thread(_asked, who)
    if not groups:
        return {"ok": True, "said": "nothing to name", "clusters": 0}
    try:
        got = await llm.ask(USE, system=SYSTEM, messages=[{"role": "user", "content": asked}],
                            max_tokens=MODEL_TOKENS, who=who, org_id=str(who.org_id) or None, cfg=cfg,
                            purpose=PURPOSE, timeout=MODEL_SECONDS, read_only=True)
    except llm.Cannot:
        return {"ok": False, "said": "no model is picked for it", "clusters": 0}
    answer = read_answer(got.text)
    if answer is None:
        return {"ok": False, "said": "the answer was not a map", "clusters": 0}
    kept = await asyncio.to_thread(_keep, who, answer, groups, graph, got.model, why)
    return {"ok": True, "said": f"named {kept} cards", "clusters": kept}


def _asked(who) -> tuple[str, dict[str, dict], dict]:
    """What the model is told: each card on the map, busiest first, with its
    subject, its kind and its rows, as JSON, in his own time."""
    from . import clock

    now = time.time()
    zone = clock.zone_of(who)

    def local(at: float, shape: str) -> str:
        return datetime.fromtimestamp(at, zone).strftime(shape)

    facts = _Facts(who, now, [])
    if facts.empty:
        return "", {}, {}
    graph = _graph(facts)
    _graphs[f"{who.org_id}/{who.user_id}"] = (now, graph)
    placed = _place(graph, _setting(who, NAMED))
    scored = sorted((c for c in _score(facts, graph, placed, {}) if not c["gone"]), key=lambda c: -c["score"])
    recent: dict[str, list[str]] = defaultdict(list)
    for m in sorted(facts.messages, key=lambda m: -m["ts"]):
        if len(recent[m["chat"]]) < 3:
            recent[m["chat"]].append(_short(m["text"], 220))
    cards: dict[str, dict] = {}
    out = []
    for c in scored[:GROUPS_MOST]:
        card = placed["cards"][c["key"]]
        cards[c["key"]] = card
        info = placed["named"].get(c["key"]) or {}
        tasks = []
        for t in c["tasks"]:
            row = facts.task_row(f"T{t['n']}") if t.get("n") is not None else None
            tasks.append({"title": t["title"], "status": t["state"],
                          "summary": _short(facts.summaries.get((row or {}).get("id")) or "", 300)})
        out.append({
            "key": c["key"],
            "kind": c["kind"],
            "subject": f"{card.get('type')}: {card.get('title')}",
            "name_it_had": info.get("name") or None,
            "side": c["side"] if card.get("home") else "unknown",
            "tasks": tasks,
            "clockwork_jobs": [j["title"] for j in c["jobs"]],
            "chats": [{"title": ch["title"], "his_latest": recent.get(ch["href"].rsplit("/", 1)[-1], [])}
                      for ch in c["chats"]][:6],
            "meetings": [f"{local(m['at'], '%a %-d %b %H:%M')}: {m['what']}" for m in c["meetings"]][:6],
            "people": c["people"],
            "waiting_on_him": [w["text"] for w in c["waiting"]][:5],
            "lately": [x["text"] for x in c["since"]][:4],
            "rouh_runs": [f"{r['title']}: {r['state']}" for r in c["runs"]][:4],
        })
    told = {"now": local(now, "%A %-d %B %Y, %H:%M") + f" ({zone.key})", "cards": out}
    return ("The cards Rouh made, with what is in each, as JSON:\n\n"
            + json.dumps(told, ensure_ascii=False, indent=1)), cards, graph


def read_answer(text: str) -> dict | None:
    """The model's map, or None when it answered with something else."""
    text = str(text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        got = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(got, dict) or not isinstance(got.get("cards"), list):
        return None
    return got


def _keep(who, got: dict, cards: dict[str, dict], graph: dict, model: str, why: str) -> int:
    """What the model said of each card, by the card's key. A card it was not
    told about this time keeps what it was told last; a card that is gone is
    forgotten."""
    named = _setting(who, NAMED)
    live = {c["key"] for c in graph.get("cards") or []}
    held = {c["key"]: c for c in named.get("clusters") or [] if isinstance(c, dict) and c.get("key") in live}
    kept = 0
    for c in got.get("cards") or []:
        if not isinstance(c, dict) or str(c.get("key") or "") not in cards:
            continue
        key = str(c["key"])
        topic = cards[key].get("kind") == "topic"
        held[key] = {
            "key": key, "kind": cards[key].get("kind"),
            "name": _short(str(c.get("name") or ""), 60) if topic else "",
            "side": (str(c.get("side") or "").lower() if not cards[key].get("home")
                     and str(c.get("side") or "").lower() in ("work", "personal", "rouh") else ""),
            "headline": _short(str(c.get("headline") or ""), 140)}
        kept += 1
    _put(who, NAMED, {"named_at": time.time(), "model": model, "why": why, "clusters": list(held.values())})
    log.info("the control room's cards were named for %s/%s (%s): %d cards with %s",
             who.org_id, who.user_id, why, kept, model)
    return kept


# ---------------------------------------------------------------------------
# Each night
# ---------------------------------------------------------------------------


def ensure(who):
    """His nightly naming pass, a row on his Reminders page, made once.

    A row he paused or moved stays as he left it, as the other nightly rows do."""
    from . import clock, reminders

    got = reminders.server_row(who, JOB)
    if got is not None:
        return got
    with clock.person(who):
        first = reminders.moment_of(AT)
    row = reminders.add_server(who, job=JOB, title=JOB_TITLE, what=JOB_WHAT, first=first, repeat="daily")
    log.info("the control room's nightly naming is scheduled for %s/%s at %s (reminder %s)",
             who.org_id, who.user_id, AT, row.id)
    return row


async def nightly(who, trying: bool = False) -> str:
    """The nightly pass, as the Reminders page says what it did."""
    got = await name(who, why="tried now" if trying else "nightly")
    return got["said"]
