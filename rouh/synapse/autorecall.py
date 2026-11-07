"""Automatic recall: what Synapse Master holds about what Petar's message is about, before Rouh answers it.

Petar, by voice, 6 October 2026: before the model answers a message of his, Rouh looks up in Master the
people, tasks, projects and topics the message is about, and puts what it finds into that turn as quiet
background, so Rouh remembers everything without talking about everything. Until 10 October code picked them.

Petar, by voice, 10 October 2026: "I definitely don't want answers to be limited to 2.5 seconds. At the very
least, we can do better than that ... I want you to visualize the background calls and the parallel calls,
and see in 2.5 seconds whether they returned results or timed out." And: "I think Clockwork should also use
the synapse and consider the fact that I may be emailing you and asking you for a task myself." So since that
day nothing a look-up finds is dropped at a deadline: the turn's first request waits for it up to
`recall_wait_ms`, the look-ups run on to `CEILING_S`, and what comes back later goes into the turn's next
request or the next message in the chat (`rouh/recalling.py`, which also draws each message's timeline).

Petar, 10 October 2026, after a screenshot of recall on "Add to the open source ideas the following: we should
define our own term for living software. That would help vitality", where the code had picked "define" and
"vitality", missed "living software", "open source ideas" and task 98, and the connection walk brought 24 items,
"Canine reshaping" and an unrelated person among them: "It really has no concept what I am trying to do and what it
relates to. I feel like it is useless adds noise and we should have an LLM call instead." Then: "I see no reason
to leave code - it contributes nothing if we have an LLM call... skip it." So since that day a model, not code,
reads the message, and there is no code to fall back on: when both models fail or are late, nothing is looked
up.

- **What it is about** (`ask`, `resolve`), read by two small models of two companies at the same moment, the
  first answer in the right shape used: Synapse's decision backend's model and automatic recall's second reader,
  each the one the Models page has for it (GPT-4.1 Mini and Haiku 4.5 to start with), each with structured
  output, the same prompt, and `PICK_TIMEOUT_S` to answer. Petar, 10 October 2026: "Make a backup call ...
  switching providers is good option", then "If the cost is like a fraction of a cent, let's always make both
  calls and take the first's results"; both together cost under a cent a message (below), so `RACE` is on, and
  off the second is asked only once the first has failed or been silent `HEDGE_S`. The slower is never waited
  for, and never stopped: Petar, 14 October 2026, "don't stop the second one, let it finish even if the rest of
  the flow is triggered. We want to keep the logs and later do evaluations." It runs on to its own end, and
  only then is the recall recorded, with both readings whole, which came first, and how long each took
  (`record`). Each reader is given
  the message; the chat's title, its task when it is a task's, and its last `TURNS_SHOWN` turns, so it
  knows what the message relates to; Master's `PEOPLE_SHOWN` people who matter most, with Petar's own words for
  them from the Rules page (a nickname for a family member, say); the projects; and the open and waiting tasks and
  steps, and those done in the last `DONE_DAYS`, by code and title (`_lists`, the same for a minute, so the
  provider's prompt cache holds it). It answers with people (a ref and the name, the ref taken only with its
  name), people it heard named who are not on the list, task codes, project folders, at most three topics
  as the phrases the person is talking about ("living software", "open source ideas"), and whether two or
  more of them bear on each other. Nothing at all for a greeting, a timer, the time, yes, go ahead. A project
  counts only when the message names it.
- **What is run**, in parallel: one find per thing picked, each holding what was picked (`search.mentioning`
  for a person, their name or address or a link to them; a task's own item and files and a project's tasks
  by folder; `search.containing` for a topic's whole phrase), and, only when the model says they bear on
  each other, one background-mode `synapse_query` asking how they connect, with no answer model, of whose
  pack only `CONNECT_MOST` items count, each scored at least `CONNECT_FROM` and holding one of the things
  picked.

- **As whom**: the asker is the dataset's own person, Petar, and only on his own words: a turn he started
  with them (`signups.PERSON_TURN`, typed, spoken or sent from his own Telegram); a Clockwork reminder or
  scheduled work of his coming due, on its title and words (`WORDS`, set by `timekeeper.deliver`); and an
  email from one of his own addresses that Gmail's Authentication-Results passed (SPF, DKIM or DMARC), on its
  subject and body (`mail_turn.MailTurn.recall_words`, set by `mail_alerts.MailAlerts.handle`). Never in a
  turn a job's report, the heartbeat or anybody else's email started, so never with the permissions of
  somebody whose mail is being handled.
- **How long**: the two models have `PICK_TIMEOUT_S` (the ceiling) to read the message, and the look-ups
  start the moment the first answers, however long it took; a reading not back by then has failed, and with
  neither back nothing is looked up (2 s until 14 October 2026). The turn's first request waits
  for the look-ups at most `recall_wait_ms` (a number of Master's, `WAIT_S` to start with) from the moment the
  message came; they run on to `CEILING_S`, and one not back by then is failed. Nothing that fails ever
  reaches the turn as an error.
- **How much**: at most `TOKENS` tokens of lines, best first (an item two things picked share, then what the
  connection walk found, then each thing's own nearest to now), near-duplicates dropped (the same item twice,
  a forward of an email already in, a calendar series' other days).
- **Where it goes**: one labelled block after the clock (`brain.Brain._system`), its lines in the untrusted
  box (`untrusted.wrap`) because they quote mail and pages; the standing rule about using it is the built-in rule "background-memory" on the Rules page.
  What comes back after the first request goes after the tool results of the turn's next request, or into
  the next message's block, labelled as such (`LATE_LABEL`, `CARRIED_LABEL`).
- **What is kept**: a `recall` trace in Master's Activity (the lab's first tab) with the model's reading (what
  it answered, its time and cost) and every look-up, when it started and ended, what it found and where that
  went; a line in Rouh's log; on the orb a twig for each model's reading (the one used ends "answered first")
  and one per look-up on the turn's line; and under the message in the chat, its timeline, with what was
  picked, who answered first and how long each took (`rouh/recalling.py`).
- **Its switch** is `memory_recall` (`rouh/switches.py`, Evolution, Mutations, under Other switches).

Measured before it landed (10 October 2026), on a copy of live Master with the real model and Voyage: the
48 recall traces in Master's Activity, 9 to 10 October, replayed through the model with each message's own
chat as it stood before it, two passes:

- **What it picked** for the screenshot's message: task 98-04 Ideas and "living software", against "define"
  and "vitality"; 5 items in the turn (the Ideas step and its notes, the "Living software naming" chat, the
  task above it, and one chat about recall itself) against 10 that were not about it. Over the 48: 261 items
  against 410 (5.4 against 8.5 a message), 43,430 tokens against 59,333, the connection walk adding at most 3
  where it added up to 24. "hi", "set a timer for ten minutes", "yes go ahead", "what time is it" and
  "thanks" picked nothing.
- **How long**: the model's own time p50 1.29 s, p95 1.62 s, over 2 s in 1 of 96 calls (3.1 s; the first of
  a cold cache 2.0 s), against about 0.1 s for the code; the finds after it 0.13 s at most; the connection
  walk p50 1.7 s. The whole recall, to its last look-up, p50 2.9 s and p95 3.6 s, against 1.6 s and 2.5 s,
  all inside the first request's wait (`recall_wait_ms`, then 6 s), so the first request goes about 1.3 s later
  at the median than it did.
- **What it costs**, gpt-4.1-mini alone: about 4,400 tokens in and 40 out a message, 84% of them read from
  OpenAI's prompt cache (`prompt_cache_key`), $0.67 a thousand messages ($1.80 a thousand with no cache).

Then both readers, raced, on the same 49 messages twice against live Master, read-only (98 readings):

- **gpt-4.1-mini (OpenAI)**: p50 1.28 s, p95 1.77 s, over 2 s 4 times (5.2 s at worst); $0.00059 a message
  on average, $0.00071 at the 95th ($0.59 a thousand), 94% of its input from the cache; answered first 91
  times.
- **Haiku 4.5 (Anthropic)**: p50 1.88 s, p95 2.36 s, over 2 s 26 times; $0.00115 a message on average,
  $0.00151 at the 95th ($1.15 a thousand), 93% from the cache (marked `cache_control`; its prompt of about
  6,000 tokens is over Haiku's 4,096-token minimum), $0.0071 for the one that writes the cache; answered first
  7 times.
- **Both**: $0.0017 a message on average, $0.0022 at the 95th ($1.73 a thousand). At list prices and the 95th
  percentile prompt (4,774 and 6,038 tokens) with no cache at all, and Haiku writing its cache, $0.0020 +
  $0.0079 = $0.0099: under a cent even then, so `RACE`, both at once on every message.
- **The first answer**: p50 1.28 s, p95 1.69 s, over 2 s once in 98 (2.2 s), against 4 for gpt-4.1-mini
  alone. A hedge at 0.9 s would have asked Haiku for 94 of the 98 anyway.
- **Agreement**: the two picked the same people, tasks and projects 35 times in 98; topics are phrased freely
  and not compared. The answer used is whichever came first.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field

from .. import dbwork
from . import ai, db, numbers, people, search, text as tx

log = logging.getLogger("rouh.synapse.autorecall")

SWITCH = "memory_recall"
TITLE = ("Automatic memory recall: before Rouh answers you, a small model reads what your message is about, "
         "and the people, tasks and topics it picks are looked up in Synapse Master")

#: How long the turn's first request waits for the look-ups at most, from the moment the message came, in
#: seconds, until a dataset says otherwise (`recall_wait_ms`, `wait_seconds`).
WAIT_S = int(numbers.BY_KEY["recall_wait_ms"].value) / 1000.0
#: Where recall used to be cut off, until 10 October 2026: a marker on each message's timeline.
OLD_BUDGET_S = 2.5
#: The longest a look-up is let run, in seconds; one not back by then has failed.
CEILING_S = 30.0
#: Words to recall on in a turn a note of Rouh's started, as the person's own: a Clockwork reminder or
#: scheduled work of theirs coming due (`timekeeper.deliver`). Empty everywhere else.
WORDS: contextvars.ContextVar[str] = contextvars.ContextVar("recall_words", default="")
#: The most its lines may cost, in tokens.
TOKENS = 1500
#: Things looked up on one message, at most, and items kept from each look-up.
MOST_ENTITIES = 6
PER_ENTITY = 4
#: What the connection walk may add, at most, and only items it scored at least `CONNECT_FROM` (its pack's
#: scores run from 1 for its best seed down to a few hundredths for what it wandered to): on 10 October 2026
#: it brought 24 items for "define and vitality", and "Canine reshaping" and an unrelated person went into the turn.
CONNECT_MOST = 3
CONNECT_FROM = 0.6
#: How much of an item a line shows when no model has read it into a gist yet, in characters.
SNIPPET_CHARS = 220
#: The longest message read, in characters.
MOST_CHARS = 2000
#: The models reading the message are given as long as a look-up, in seconds: a reading not back by then has
#: failed, and with neither back nothing is looked up. 2 s until 14 October 2026, when Petar said: "there seems
#: to be a time limit of 2s and then calls are failed/stop and the synapse search does not continue. Remove the
#: 2 second limit." A slow reading now only goes into the turn later (`recall_wait_ms`, `rouh/recalling.py`).
PICK_TIMEOUT_S = CEILING_S
#: Petar, 10 October 2026: "If the cost is like a fraction of a cent, let's always make both calls and take the
#: first's results." Both readers together cost well under a cent a message (measured below), so both are asked
#: at the same moment on every message. Off, the second is asked only once the first has failed or been silent
#: `HEDGE_S` ("Make a backup call ... switching providers is good option").
RACE = True
HEDGE_S = 0.9
#: People the model is shown by name, at most: those who matter most to Petar (`people.value`), with anybody
#: he has a word for. Somebody else it hears named is found by their whole name or address.
PEOPLE_SHOWN = 150
#: Turns of the conversation before the message the model reads, at most, and how much of each.
TURNS_SHOWN = 6
TURN_CHARS = 500
#: Done tasks and steps are shown to the model for this many days after they were done, beside the open ones.
DONE_DAYS = 21
#: How much somebody matters before anything links to them (`people.value`): a word of Petar's whose meaning
#: only names such people is not taken for one of them.
UNLINKED = 0.3

#: What the turn is told about the block, in the cached part of the system prompt (`brain.SYSTEM`).
# What the turn is told about the block is the rule "background-memory" on the Rules page, a rule of the
# person's like any (`rouh/rules.py`), while recall is on. Until 21 October 2026 it was `PROMPT`, here.

LABEL = ("Background memory - retrieved automatically from Synapse Master for this message, before you read "
         "it. It may or may not be relevant.")
LATE_LABEL = ("More background memory - retrieved automatically from Synapse Master for the person's last message, "
              "back after your reply to it had begun. It may or may not be relevant.")
CARRIED_LABEL = ("Background memory for the person's previous message in this chat - retrieved automatically from "
                 "Synapse Master, back only after that answer had ended. It may or may not be relevant.")
SOURCE = "Synapse Master, Rouh's memory, which quotes mail, pages, chats and calendar invitations written by others"

@dataclass
class Entity:
    """One thing the message is about, as the model picked it, and how it is looked up."""
    kind: str                     # person, task, project or topic
    label: str                    # how it is said, in the trace, the timeline and the block: Bo (Robert Smith)
    name: str                     # what the connection question calls it: Robert Smith
    words: list[str] = field(default_factory=list)      # a topic's phrase, held whole
    phrases: list[str] = field(default_factory=list)    # any one may be held (a person's name, address)
    person: str | None = None     # a person item's id
    item: str | None = None       # the thing's own item (a person, a task), first in its list
    said: str = ""                # what the model or the message called it
    folder: str = ""              # a task's or a project's folder in the workspace


# --- what the message is about: one model call ----------------------------------------------------------------

PICK_INSTRUCTIONS = """You read one message ‹owner› sent to Rouh, ‹his› assistant, and say what in ‹his› memory
(Synapse Master: ‹his› mail, meetings, calendar, notes, tasks and chats) is worth looking up before Rouh
answers it: the people, tasks, projects and topics the message is actually about.

Read the message with the conversation before it and the chat it is in, so you know what it relates to.

- people: each person on the list the message means, as their ref and their name exactly as the list has
  them ("P7 Robert Smith"): by name, by ‹owner›'s own word for them, or because the conversation makes plain
  who "she" or "him" is. Somebody named who is not on the list goes in other_people, as the message writes
  them (a name or an email address); never guess a different person for them. Never ‹owner› ‹himself›.
- tasks: the code alone (98, 98-04) of each task or step on the list the message is about: by its number,
  by its title, or by what ‹owner› calls it ("the open source ideas" is a step called Ideas under a task about
  open-sourcing). The chat's own task only when the message is about its work, not for every message in it.
- projects: almost always empty. The folder of a project on the list only when the message names that
  project and is about everything in it ("what is open in Acme"). Never because a task you picked is in it.
- Rouh is the assistant the message is written to: never a person, a topic or a project because the
  message mentions Rouh or is about Rouh's own screens and features.
- topics: at most three phrases the message is about, in the message's own words or the name the thing is
  known by, two to four words where it can ("living software", "open source ideas", "speaker diarisation").
  One word only when it is a distinctive name: a product, a company, a place ("Traxxas", "Soniox",
  "Camden Market"), never a common noun ("beach", "transcription"). Never an ordinary word, a verb, words
  about the conversation itself ("define", "useless",
  "corrections", "screenshot", "noise"), or a phrase of your own making that the message does not say.
  Never a person, task or project you already picked.
- related: true only when two or more of what you picked bear on each other in this message, so that how
  they connect is worth asking. Otherwise false.

A message that needs nothing from memory (a greeting, a timer, the time, thanks, yes, go ahead, a
correction to wording or layout with nothing to look up) gets every list empty. Fewer and right is better
than more: when unsure, leave it out."""

#: The answer's shape, held by structured output.
PICK_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["people", "other_people", "tasks", "projects", "topics", "related"],
    "properties": {
        "people": {"type": "array", "items": {"type": "string"}},
        "other_people": {"type": "array", "items": {"type": "string"}},
        "tasks": {"type": "array", "items": {"type": "string"}},
        "projects": {"type": "array", "items": {"type": "string"}},
        "topics": {"type": "array", "items": {"type": "string"}},
        "related": {"type": "boolean"},
    },
}

@dataclass
class Reader:
    """One model asked to read the message: each of the two companies' (`ask`)."""
    model: str
    provider: str                                   # openai or anthropic
    call: "Call"                                    # its twig on the orb and its bar on the timeline
    asked: float = 0.0                              # time.monotonic()
    ms: int | None = None
    ok: bool = False
    valid: bool = False                             # back with an answer in the shape asked for
    error: str = ""
    cost: float = 0.0
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    served: str = ""                                # the model's own dated name, as it answered
    said: dict = field(default_factory=dict)
    won: bool = False                               # its answer is the one used
    agreed: bool | None = None                      # the other's answer picked the same people, tasks, projects

    def shown(self) -> dict:
        return {"model": self.model, "provider": self.provider, "ms": self.ms, "ok": self.ok and self.valid,
                "error": self.error, "won": self.won, "agreed": self.agreed, "cost": round(self.cost, 6)}


@dataclass
class Pick:
    """The models' reading of one message, for the trace, the timeline and the log: who answered first, and
    what each of them took and cost."""
    model: str = ""                                 # the one whose answer is used, or the first asked
    provider: str = ""
    ms: int = 0                                     # from asking to the answer used
    ok: bool = True
    error: str = ""
    said: dict = field(default_factory=dict)        # the answer used, as it was given
    related: bool = False
    context_ms: int = 0
    prompt_tokens: int = 0                          # the prompt's size, on the safe side (`_tokens_of`)
    mode: str = ""                                  # race (both at once) or hedge (the second when the first is slow)
    readers: list = field(default_factory=list)
    pending: list = field(default_factory=list, repr=False)   # the readers' futures, the slower still running

    @property
    def cost(self) -> float:
        return sum(r.cost for r in self.readers)

    def when_settled(self, fn) -> None:
        """Call `fn()` once every reader asked has ended, on the thread the last one ended on, or now when
        they all have: so the slower is waited for without anything being held up by it."""
        pending = list(self.pending)
        left = [len(pending)]
        lock = threading.Lock()

        def one(_f) -> None:
            with lock:
                left[0] -= 1
                last = left[0] == 0
            if last:
                fn()

        if not pending:
            fn()
        for f in pending:
            f.add_done_callback(one)

    def settle(self, until: float) -> None:
        """Wait, at most until `until` (time.monotonic()), for the slower reader, and say whether it agreed."""
        concurrent.futures.wait(self.pending, timeout=max(0.0, until - time.monotonic()))
        winner = next((r for r in self.readers if r.won), None)
        for r in self.readers:
            if winner is not None and r is not winner and r.valid:
                r.agreed = _same(r.said, winner.said)

    def shown(self) -> dict:
        return {"model": self.model, "provider": self.provider, "ms": self.ms, "ok": self.ok, "error": self.error,
                "cost": round(self.cost, 6), "related": self.related, "mode": self.mode,
                "readers": [r.shown() for r in self.readers]}


def _things(got: dict) -> tuple:
    people_ = sorted(str(p).split(" ", 1)[0] for p in got.get("people") or [])
    tasks = sorted(m.group(0) for m in (re.search(r"\d+(?:-\d+)*", str(t)) for t in got.get("tasks") or []) if m)
    return (people_, sorted(people.norm_name(p) for p in got.get("other_people") or []), tasks,
            sorted(str(p).strip("/") for p in got.get("projects") or []))


def _same(a: dict, b: dict) -> bool:
    """Whether two readings looked up the same people, tasks and projects (topics are phrased freely)."""
    return _things(a) == _things(b)


def _valid(got) -> bool:
    return isinstance(got, dict) and all(isinstance(got.get(k), list) for k in
                                         ("people", "other_people", "tasks", "projects", "topics")) \
        and isinstance(got.get("related"), bool)


_LISTS: dict[str, tuple[float, dict]] = {}


def _word_person(scope: str, w: dict) -> str | None:
    """Who an entry of the owner's vocabulary means: the person it is about, else a person called by the word
    itself (a family nickname), else one
    whose address the meaning holds (Bo's bo@example.com), else the one called by the meaning's first name, when
    there is one who matters more than a contact nothing links to."""
    own = next((str(c["id"]) for c in w.get("context") or [] if c.get("type") == "person" and c.get("id")), "")
    if own:
        return own
    term, meaning = str(w.get("term") or "").strip(), str(w.get("meaning") or "")
    pid = _best(scope, people.find_all(scope, "name", people.norm_name(term)))
    for e in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", meaning):
        pid = pid or people.find(scope, "email", e.lower())
    if not pid:
        head = re.split(r"[,;(]", meaning, maxsplit=1)[0]
        pid = _best(scope, people.find_all(scope, "name", people.norm_name(head)), sure=False)
    return pid


def _best(scope: str, pids: list[str], *, sure: bool = True) -> str | None:
    """Of several people a name could be, the one who matters most (`people.value`); with `sure` off, nobody
    who matters no more than a contact nothing links to."""
    if not pids:
        return None
    rows = db.rows("SELECT id, meta FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[])", (scope, pids))
    if not rows:
        return None
    value = lambda r: float((r["meta"] if isinstance(r["meta"], dict) else {}).get("value") or 0)  # noqa: E731
    best = max(rows, key=value)
    if not sure and value(best) <= UNLINKED:
        return None
    return best["id"]


def _code_key(code: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in code.split("-"))


def _tasks_listed() -> list[dict]:
    """Rouh's open and waiting tasks and steps, and those done in the last `DONE_DAYS`, each with its code
    (98, 98-04) and title, in the order of their codes. A task that has no code cannot be named by one."""
    from .. import searching
    from ..models import Task

    since = time.time() - DONE_DAYS * 86400
    out = []
    for t in Task.objects.filter(archived_at__isnull=True).values("id", "number", "title", "state", "folder",
                                                                   "closed_at"):
        if t["state"] == "done" and (t["closed_at"] or 0) < since:
            continue
        code = str(t["number"]) if t["number"] is not None else searching.number_of_folder(t["folder"] or "")
        if code:
            out.append({**t, "code": code})
    return sorted(out, key=lambda t: _code_key(t["code"]))


def _lists(ds: dict, me: str) -> dict:
    """What the model is shown of Master and the workspace, the same for every message for a minute, so
    the provider's prompt cache holds it: the people who matter most with the owner's words for them, the
    projects, and the tasks. `{"text", "people": {ref: id}, "tasks": {code: row}, "projects": {folder: name}}`."""
    key = str(ds["id"])
    got = _LISTS.get(key)
    if got and time.time() - got[0] < 60:
        return got[1]
    from .. import keeping, vocabulary

    scope = people.home_id(ds)
    rows = db.rows("SELECT id, title, meta->>'organisation' AS org FROM synapse.item WHERE dataset_id = %s "
                   "AND kind = 'person' AND deleted_at IS NULL AND id <> %s::uuid "
                   "ORDER BY coalesce((meta->>'value')::float, 0) DESC, id LIMIT %s", (scope, me, PEOPLE_SHOWN))
    calls: dict[str, list[str]] = {}
    words = []
    for w in vocabulary.entries(ds):
        pid = _word_person(scope, w)
        if pid and pid != me:
            calls.setdefault(pid, []).extend(vocabulary.names(w))
            if all(r["id"] != pid for r in rows):
                row = _person_row(scope, pid)
                if row:
                    rows.append({"id": row["id"], "title": row["title"], "org": (row["meta"] or {}).get("organisation")})
            words.append(vocabulary.line(w))
    refs, names, lines = {}, {}, []
    for n, r in enumerate(rows, 1):
        ref = f"P{n}"
        refs[ref] = r["id"]
        names[r["id"]] = " ".join(str(r["title"] or "").split())
        line = f"{ref} {names[r['id']]}"
        if r.get("org"):
            line += f" ({' '.join(str(r['org']).split())[:60]})"
        if calls.get(r["id"]):
            line += " - ‹owner› calls them " + " and ".join(f"\"{c}\"" for c in calls[r["id"]])
        lines.append(line)
    projects = {p["folder"]: p["name"] for p in keeping.projects_now().values() if p.get("folder") and p.get("name")}
    tasks = {t["code"]: t for t in _tasks_listed()}
    task_lines = [f"{c} {' '.join(str(t['title']).split())}" + (" (done)" if t["state"] == "done" else
                                                               " (waiting)" if t["state"] == "waiting" else "")
                  for c, t in tasks.items()]
    text = ("\n\nPEOPLE (the ones who matter most to ‹owner›; ref, name, organisation):\n" + "\n".join(lines) +
            ("\n\n‹owner›'S OWN WORDS FOR PEOPLE (‹his› vocabulary):\n" + "\n".join(words) if words else "") +
            "\n\nPROJECTS (folder: name):\n" + "\n".join(f"{f}: {n}" for f, n in sorted(projects.items())) +
            "\n\nTASKS AND STEPS (code, title; open unless it says otherwise):\n" + "\n".join(task_lines))
    out = {"text": text, "people": refs, "names": names, "calls": calls, "tasks": tasks, "projects": projects}
    _LISTS[key] = (time.time(), out)
    return out


def _chat_said(chat_id: str, text: str) -> str:
    """The chat the message is in, for the model: its title, its task, and the turns before the message."""
    if not chat_id:
        return ""
    from .. import conversations, searching
    from ..models import objects as tables

    parts = []
    try:
        chat = conversations.store().get_chat(chat_id)
        task = conversations.task_of(chat_id)
    except Exception:  # noqa: BLE001 - a chat that cannot be read is a message read alone
        log.exception("recall: the chat %s could not be read", chat_id)
        return ""
    if chat is not None and chat.title:
        parts.append(f"THE CHAT: \"{chat.title}\"")
    if task is not None:
        code = str(task.number) if task.number is not None else searching.number_of_folder(task.folder or "")
        parts.append(f"THE CHAT IS THE TASK'S: {code} {task.title}".strip())
    rows = list(tables.ChatMessage.objects.filter(chat_id=chat_id).order_by("-seq")
                .values("role", "body")[:TURNS_SHOWN + 1])[::-1]
    if rows and rows[-1]["role"] == "user" and " ".join(str(rows[-1]["body"]).split()) == " ".join(text.split()):
        rows = rows[:-1]
    rows = rows[-TURNS_SHOWN:]
    if rows:
        turns = []
        for r in rows:
            body = " ".join(str(r["body"] or "").split())
            body = body[:TURN_CHARS] + ("..." if len(body) > TURN_CHARS else "")
            turns.append(f"{'‹owner›' if r['role'] == 'user' else 'Rouh'}: {body}")
        parts.append("THE CONVERSATION BEFORE THE MESSAGE (oldest first):\n" + "\n".join(turns))
    return "\n\n".join(parts)


_ASKERS = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="recall-pick")

def readers_of(s) -> list[tuple[str, str]]:
    """The two models asked to read a message, `(model, provider)`: automatic recall's first and second
    readers, each the one the Models page has for it (`numbers.MODEL_USES`).
    Until 18 October 2026 a second reader of the same company as the first was swapped for the other
    company's; nothing is swapped now (Petar: "Whatever we select here should be the one called"), and
    the Models page says the two are best of two companies."""
    first, second = str(s.recall_first_model), str(s.recall_second_model)
    return [(first, ai.backend_of(first)), (second, ai.backend_of(second))]


def ask(ds: dict, text: str, *, chat_id: str = "", me: str, timeout: float | None = None, say=None,
        calls: list | None = None, race: bool | None = None) -> tuple[dict, dict, Pick]:
    """The models' reading of the message: `(the answer used, the lists they were shown, the Pick)`.

    Two models of two companies are asked the same thing (`readers_of`). With `race` (`RACE`, since both
    together cost well under a cent a message), both at the same moment; otherwise the second only once the
    first has failed or been silent `HEDGE_S`. The first answer in the right shape is used; the other is never
    stopped, and runs on to its own end or `timeout`, so the trace and the log keep its answer too, how long it
    took and whether it agreed (`Pick.settle`, `record`). Each is a twig and a
    bar (`say`, and `calls`, where their `Call`s are kept). Raises PickFailed when neither has answered by
    `timeout`; the Pick says how each went either way."""
    from . import datasets

    began = time.monotonic()
    timeout = PICK_TIMEOUT_S if timeout is None else timeout
    race = RACE if race is None else race
    s = datasets.settings(ds)
    pick = Pick(mode="race" if race else "hedge")
    lists = _lists(ds, me)
    said = _chat_said(chat_id, text)
    pick.context_ms = int((time.monotonic() - began) * 1000)
    instructions = PICK_INSTRUCTIONS + lists["text"]
    words = (said + "\n\n" if said else "") + "THE MESSAGE:\n" + text[:MOST_CHARS]
    pick.prompt_tokens = _tokens_of(instructions + words)
    asked = time.monotonic()
    deadline = asked + timeout
    owner = datasets.owner_of(ds)
    for n, (model, provider) in enumerate(readers_of(s)):
        call = Call(f"pick{n}", "recall_pick", f"Reading the message with {model}", 0.0)
        pick.readers.append(Reader(model=model, provider=provider, call=call))
        if calls is not None:
            calls.append(call)
    pick.model, pick.provider = pick.readers[0].model, pick.readers[0].provider
    done = threading.Event()
    claim = threading.Lock()
    closed = []                       # set once the answer is chosen, or none came in time

    def read(r: Reader) -> None:
        try:
            got = ai.generate(model=r.model, instructions=instructions, text=words, schema=PICK_SCHEMA,
                              name="recall_pick", purpose="recall_pick", owner=owner, max_tokens=400,
                              cache_key=f"recall-pick-{ds['id']}", timeout=max(0.05, deadline - time.monotonic()))
        except Exception as exc:  # noqa: BLE001 - the other reader may still answer
            r.ms = int((time.monotonic() - r.asked) * 1000)
            r.error = (f"not back in {timeout:g} s" if isinstance(exc, TimeoutError)
                       else f"{type(exc).__name__}: {exc}"[:300])
            r.call.end(say, False, r.error)
            done.set()
            return
        r.ms = int((time.monotonic() - r.asked) * 1000)
        usage = got.pop("_usage", {}) or {}
        r.cost = float(got.pop("_cost", 0) or 0)
        r.served = str(got.pop("_model", "") or r.model)
        got.pop("_ms", None)
        r.tokens_in = sum(int(usage.get(k, 0) or 0) for k in
                          ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        r.tokens_cached = int(usage.get("cache_read_input_tokens", 0) or 0)
        r.tokens_out = int(usage.get("output_tokens", 0) or 0)
        r.ok, r.said, r.valid = True, got, _valid(got)
        if not r.valid:
            r.error = "its answer was not in the shape asked for"
        r.call.count = sum(len(got.get(k) or []) for k in ("people", "other_people", "tasks", "projects", "topics")) \
            if r.valid else 0
        # The first answer in the right shape is the one used, claimed the moment it is back, so its twig says so.
        with claim:
            if r.valid and not closed:
                closed.append(r)
                r.won = r.call.won = True
        r.call.end(say, r.valid, r.error)
        done.set()

    def start(r: Reader) -> None:
        r.asked = r.call.started = time.monotonic()
        if say:
            say("start", r.call)
        pick.pending.append(_ASKERS.submit(read, r))

    start(pick.readers[0])
    if race:
        start(pick.readers[1])
    winner = None
    while winner is None:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        second_waiting = not pick.readers[1].asked
        first = pick.readers[0]
        if second_waiting and (first.call.ended and not first.valid
                               or time.monotonic() - asked >= HEDGE_S):
            start(pick.readers[1])
            continue
        done.wait(min(left, max(0.01, asked + HEDGE_S - time.monotonic())) if second_waiting else left)
        done.clear()
        winner = next((r for r in pick.readers if r.won), None)
        if winner is None and all(r.call.ended for r in pick.readers if r.asked) and not second_waiting:
            break
    with claim:
        winner = next((r for r in pick.readers if r.won), None)
        closed.append(None)
    for r in pick.readers:
        if r.asked and not r.call.ended and winner is None:
            r.error = f"not back in {timeout:g} s"
            r.call.end(say, False, r.error)
    if winner is None:
        pick.ok = False
        pick.ms = int((time.monotonic() - asked) * 1000)
        pick.error = "; ".join(f"{r.model}: {r.error or 'not asked'}" for r in pick.readers)
        raise PickFailed(pick)
    pick.model, pick.provider, pick.ms, pick.said = winner.model, winner.provider, winner.ms or 0, winner.said
    return dict(winner.said), lists, pick


class PickFailed(RuntimeError):
    def __init__(self, pick: Pick) -> None:
        super().__init__(pick.error)
        self.pick = pick


def _person_named(scope: str, said: str, me: str) -> str | None:
    """Somebody the model heard named who is not on its list: by address, else by whole name."""
    said = said.strip()
    if "@" in said:
        return people.find(scope, "email", said.lower())
    norm = people.norm_name(said)
    pid = _best(scope, [p for p in people.find_all(scope, "name", norm) if p != me])
    if pid or not norm or " " in norm:
        return pid
    # A first name alone: whoever of those who have it matters more than a contact nothing links to.
    rows = db.rows("SELECT DISTINCT x.item_id FROM synapse.identity x JOIN synapse.item i ON i.dataset_id = x.scope_id "
                   "AND i.id = x.item_id WHERE x.scope_id = %s AND x.type = 'name' AND x.value LIKE %s AND "
                   "i.kind = 'person' AND i.deleted_at IS NULL LIMIT 60", (scope, norm.replace("%", "") + " %"))
    return _best(scope, [r["item_id"] for r in rows if r["item_id"] != me], sure=False)


def _task_item(ds: dict, row: dict, readers: list[str]) -> str | None:
    """A Rouh task's own item in Master."""
    keys = [f"task:{row['id']}"] + ([f"task:task-{row['number']}"] if row.get("number") is not None else [])
    got = db.row("SELECT i.id FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.kind = 'task' "
                 "AND i.source_key = ANY(%s) AND i.deleted_at IS NULL AND " + search.readable_sql("i") +
                 " ORDER BY i.stored_at DESC LIMIT 1", (ds["id"], keys, readers))
    return got["id"] if got else None


def resolve(ds: dict, got: dict, lists: dict, *, text: str = "", me: str, readers: list[str]) -> list[Entity]:
    """What the model picked, as things to look up, people first, at most `MOST_ENTITIES`. A ref, code or
    folder the lists do not have is something the model made up, and is left out."""
    scope = people.home_id(ds)
    out: list[Entity] = []
    seen: set[str] = set()

    def person(pid: str | None, said: str = "") -> None:
        if pid and pid != me and pid not in seen:
            e = _person_entity(scope, pid, said)
            if e:
                seen.add(pid)
                out.append(e)

    for picked in got.get("people") or []:
        ref, _, name = str(picked).strip().partition(" ")
        pid = lists["people"].get(ref)
        # A ref is taken only with the name the list gave it: a model can copy the number of the line beside the
        # right one ("Nicole" came back as Maria's ref, 10 October 2026). Otherwise the name is looked up alone.
        if pid and name and people.norm_name(name) not in {people.norm_name(n) for n in
                                                            [lists["names"].get(pid, ""), *lists["calls"].get(pid, [])]}:
            pid = None
        if not pid:
            person(_person_named(scope, name or ref, me), name or ref)
            continue
        # Called by the owner's own word for them in the message, they are labelled by it: Bo (Robert Smith).
        said = next((w for w in lists["calls"].get(pid, []) if w and re.search(
            rf"(?<!\w){re.escape(w)}(?!\w)", text, re.I)), "")
        person(pid, said)
    for said in got.get("other_people") or []:
        person(_person_named(scope, str(said), me), str(said).strip())
    for code in got.get("tasks") or []:
        # The code, wherever the model put its title too: "98-04 Ideas", "task 98".
        found = re.search(r"\d+(?:-\d+)*", str(code))
        row = lists["tasks"].get(found.group(0)) if found else None
        if found and row is None:     # 98-4 for 98-04
            row = next((t for c, t in lists["tasks"].items() if _code_key(c) == _code_key(found.group(0))), None)
        if not row or row["id"] in seen:
            continue
        seen.add(row["id"])
        title = " ".join(str(row["title"]).split())
        out.append(Entity("task", f"{row['code']} {title}", f"task {row['code']}: {title}",
                          item=_task_item(ds, row, readers), said=row["code"], folder=row["folder"] or ""))
    for folder in got.get("projects") or []:
        folder = str(folder).strip().strip("/")
        name = lists["projects"].get(folder)
        # Only a project the message names: picked for a task in it, or for the name the person is talking to
        # (Rouh), it brought that project's newest tasks, which were about something else (10 October 2026).
        if name and not re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text, re.I):
            continue
        if name and folder not in seen:
            seen.add(folder)
            out.append(Entity("project", name, f"the {name} project", said=name, folder=folder))
    for phrase in (got.get("topics") or [])[:3]:
        phrase = " ".join(str(phrase).split()).strip(" \"'.,;:")
        if len(phrase) >= 3 and phrase.lower() not in seen:
            seen.add(phrase.lower())
            out.append(Entity("topic", f"\"{phrase}\"", phrase, words=[phrase], said=phrase))
    return out[:MOST_ENTITIES]


def _person_row(scope: str, pid: str) -> dict | None:
    return db.row("SELECT id, title, meta FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid "
                  "AND kind = 'person' AND deleted_at IS NULL", (scope, pid))


def _emails(scope: str, pids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    if pids:
        for r in db.rows("SELECT item_id, value FROM synapse.identity WHERE scope_id = %s AND type = 'email' "
                         "AND item_id = ANY(%s::uuid[]) ORDER BY made_at", (scope, pids)):
            out.setdefault(r["item_id"], []).append(r["value"])
    return out


def _person_entity(scope: str, pid: str, said: str = "") -> Entity | None:
    row = _person_row(scope, pid)
    if not row:
        return None
    name = " ".join(str(row["title"] or "").split())
    emails = _emails(scope, [pid]).get(pid, [])
    phrases = ([name] if len(name.split()) >= 2 else []) + emails[:3]
    said = said or name
    label = said if people.norm_name(said) == people.norm_name(name) else f"{said} ({name})"
    return Entity("person", label, name, phrases=phrases, person=pid, item=pid, said=said)


# --- looking them up -----------------------------------------------------------------------------------------

#: Which items say most for their tokens, first: what happened (a meeting, an email, an event, a task, a note),
#: then a profile, then a chat or a card, then a file. Within a rank, nearest to now first.
KIND_RANK = {"vocabulary": 0, "meeting": 0, "mail": 0, "event": 1, "task": 1, "note": 1, "layer": 2, "doc": 3, "file": 4}
#: Never brought in: the task list Rouh writes out of its database, which names every task there is, so it
#: matches every name and says nothing about any of them; and a workspace file that is code or data (the
#: Control Room's cards.json, a page's index.html, a script), which names everything it lists and reads as
#: nothing a person said. Notes, documents and the rest of a task's files still come in.
NOISE = re.compile(r"(^file:|/)_tasks\.md$|^file:.*\.(json|jsonl|html?|css|m?js|ts|py|sh|csv|tsv|xml|ya?ml|svg|map|lock|"
                   r"jpe?g|png|gif|webp|heic)$", re.I)


def rank_of(row: dict) -> int:
    kind = str(row.get("kind") or "")
    key = str(row.get("source_key") or "")
    if kind == "doc" and key.startswith(("chat:", "card:")):
        return 2
    if kind == "doc" and key.startswith("file:"):
        return 4
    return KIND_RANK.get(kind, 3)


def _under(ds: dict, e: Entity, readers: list[str], limit: int) -> list[dict]:
    """A task's own files, the newest first; or a project's tasks and steps, the most recently said first."""
    prefix = e.folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    if e.kind == "task":
        where, arg, order = "i.source_key LIKE %s", f"file:{prefix}/%", search.NEAREST
    else:
        where, arg, order = "i.kind = 'task' AND i.meta->>'thread' LIKE %s", f"task:{prefix}/%", "i.said_at DESC"
    return db.rows("SELECT i.id, i.kind, i.title, i.source_key, i.said_at, i.tier, i.meta FROM synapse.item i "
                   "WHERE i.dataset_id = %s AND i.deleted_at IS NULL AND " + where + " AND " +
                   search.readable_sql("i") + f" ORDER BY {order} NULLS LAST LIMIT %s",
                   (ds["id"], arg, list(readers), int(limit)))


def _look_up(ds: dict, e: Entity, readers: list[str]) -> list[dict]:
    """One thing's items: twice as many as are kept read, the best kinds kept (`rank_of`), nearest first.
    Everything found holds what was picked: a person's name or address or a link to them, a topic's whole
    phrase, or a place in a task's or a project's folder."""
    if e.kind == "person":
        rows = search.mentioning(ds["id"], e.phrases, person=e.person, readers=readers, limit=PER_ENTITY * 2)
    elif e.kind in ("task", "project") and e.folder:
        rows = _under(ds, e, readers, PER_ENTITY * 2)
    else:
        rows = search.containing(ds["id"], e.words, readers=readers, limit=PER_ENTITY * 2, kinds_out=("rule",),
                                 nearest=True) if e.words else []
    rows = sorted((r for r in rows if not NOISE.search(str(r.get("source_key") or ""))), key=rank_of)[:PER_ENTITY]
    if e.item and e.kind == "task" and all(r["id"] != e.item for r in rows):
        rows = [{"id": e.item, "kind": "task"}] + rows
    return rows


def question(ents: list[Entity]) -> str:
    names = [e.name for e in ents]
    joined = ", ".join(names[:-1]) + " and " + names[-1] if len(names) > 1 else names[0]
    return f"{joined}: how they connect"


def _holding(ds: dict, ids: list[str], ents: list[Entity], readers: list[str]) -> set[str]:
    """Of these items, those that hold one of the things picked, as their own look-ups would have found them:
    a person's name or address or a link to them, a topic's phrase, a place in a task's or a project's folder."""
    if not ids:
        return set()
    conds, params = [], []
    for e in ents:
        for p in (e.phrases if e.kind == "person" else e.words):
            if len(p) >= 3:
                conds.append("i.title ILIKE %s OR EXISTS (SELECT 1 FROM synapse.passage p WHERE p.dataset_id = "
                             "i.dataset_id AND p.item_id = i.id AND NOT p.from_xray AND p.text ILIKE %s)")
                params += [search._like(p), search._like(p)]
        if e.person:
            conds.append("EXISTS (SELECT 1 FROM synapse.link l WHERE l.dataset_id = i.dataset_id AND l.src = i.id "
                         "AND l.dst = %s::uuid AND l.type = ANY(%s::text[]))")
            params += [e.person, search.PERSON_LINKS]
        if e.folder:
            prefix = e.folder.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conds.append("i.source_key LIKE %s OR i.meta->>'thread' LIKE %s OR i.meta->>'thread' = %s")
            params += [f"file:{prefix}/%", f"task:{prefix}/%", f"task:{e.folder}"]
    if not conds:
        return set()
    rows = db.rows("SELECT i.id FROM synapse.item i WHERE i.dataset_id = %s AND i.id = ANY(%s::uuid[]) AND (" +
                   " OR ".join(f"({c})" for c in conds) + ") AND " + search.readable_sql("i"),
                   [ds["id"], list(ids), *params, list(readers)])
    return {str(r["id"]) for r in rows}


def _connect(ds: dict, ents: list[Entity], me: str) -> dict:
    from . import recall

    got = recall.run(ds, question(ents), asker=me, mode="background", by="rouh", label="automatic recall",
                     answer=False, engaged=False)
    pack = list((got.get("pack") or {}).get("items") or [])
    # Only what it scored highly, the best first, and only what holds one of the things picked: its scores are
    # its own, its best seed always 1, so a meeting that shares only vague words with the question scored 0.9
    # (10 October 2026), and further down its pack it wanders further still.
    strong = sorted((it for it in pack if float(it.get("score") or 0) >= CONNECT_FROM), key=lambda it: -float(it["score"]))
    holding = _holding(ds, [str(it["id"]) for it in strong], ents, search.readers_for(me))
    kept = [str(it["id"]) for it in strong if str(it["id"]) in holding]
    return {"query": got.get("query"), "trace": got.get("trace"), "ms": got.get("ms_total"), "walked": len(pack),
            "ids": kept[:CONNECT_MOST]}


#: Each look-up gives its database connection back to the pool when it is done (`rouh/dbwork.py`).
_POOL = dbwork.Executor(max_workers=8, thread_name_prefix="recall")


@dataclass
class Call:
    """One look-up, for the trace, the log, its twig on the orb and its bar on the message's timeline."""
    id: str
    tool: str                     # recall_pick (the model reading the message), synapse_find or synapse_query
    what: str
    started: float                # time.monotonic()
    ms: int | None = None
    count: int = 0
    ok: bool = True
    error: str = ""
    ended: bool = False
    ended_at: float | None = None
    won: bool = False             # a reader's answer was the one used
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def end(self, say, ok: bool, error: str = "") -> bool:
        """Mark it ended, once: by its own thread when it is back, or by `run` at the ceiling when it is not."""
        with self.lock:
            if self.ended:
                return False
            self.ended = True
            self.ended_at = time.monotonic()
            self.ms = int((self.ended_at - self.started) * 1000)
            self.ok, self.error = ok, error
        if say:
            say("end", self)
        return True


class Lookups:
    """One message's look-ups as they go, shared by the thread running them (`run`) and the turn reading them
    (`rouh/recalling.py`): what the message named, each look-up, and what each one brought back, readable at
    any moment, so the first request takes what is back by its wait and a later one the rest."""

    def __init__(self) -> None:
        self.entities: list[Entity] = []
        self.named = False            # the message has been read, and `entities` is what it is about
        self.names_ms = 0             # from the start to the model's answer, its lists and the chat read too
        self.pick: Pick | None = None
        self.pick_calls: list[Call] = []     # each model's reading, as a bar and a twig of its own
        self.why = ""
        self.calls: list[Call] = []
        self.results: dict[str, object] = {}
        # The entries of the person's vocabulary the message uses (`rouh/vocabulary.py`), matched before anything
        # is read or searched, and first in every block.
        self.vocabulary: list[dict] = []
        self.lock = threading.Lock()

    def back(self) -> list[Call]:
        """The look-ups that are back with something to read, in the order they were started."""
        with self.lock:
            calls = list(self.calls)
        return [c for c in calls if c.ended and c.ok and c.id in self.results]

    def found(self, ids=None) -> dict:
        """What the look-ups named by `ids` found (every one back, when None), best first, in `run`'s shape."""
        wanted = None if ids is None else set(ids)
        ents = list(self.entities)
        found: dict[int, list[str]] = {}
        ranks: dict[str, int] = {}
        connect = None
        for c in self.back():
            if wanted is not None and c.id not in wanted:
                continue
            got = self.results.get(c.id)
            if c.id == VOCABULARY_CALL:
                continue
            if isinstance(got, dict):
                connect = got
            elif got is not None:
                n = int(c.id)
                found[n] = [str(r["id"]) for r in got]
                ranks.update({str(r["id"]): rank_of(r) for r in got})
        items, hits = _rank(ents, found, (connect or {}).get("ids") or [], ranks)
        # The vocabulary the message uses goes first, whichever look-ups are asked for: matched, not searched.
        said = [e["id"] for e in self.vocabulary]
        items = said + [i for i in items if i not in said]
        return {"entities": ents, "calls": list(self.calls), "items": items, "hits": hits, "connect": connect,
                "why": self.why, "names_ms": self.names_ms, "pick": self.pick, "vocabulary": list(self.vocabulary)}


def _in_thread(call: Call, say, look: Lookups, fn, *args):
    """One look-up on the pool's thread (a connection lent for the look-up: `db` is Django's), ending its
    own twig the moment it is back."""
    try:
        got = fn(*args)
    except Exception as exc:  # noqa: BLE001 - one look-up failing leaves the others
        if call.end(say, False, f"{type(exc).__name__}: {exc}"[:300]):
            log.warning("recall: %s failed: %s", call.what, call.error)
        raise
    call.count = len(got["ids"]) if isinstance(got, dict) else len(got)
    look.results[call.id] = got
    if not call.end(say, True):
        log.info("recall: %s came back %d ms after it started, after it had been given up", call.what,
                 int((time.monotonic() - call.started) * 1000))
    return got


def run(ds: dict, text: str, *, chat_id: str = "", look: Lookups | None = None, say=None,
        ceiling: float = CEILING_S, timeout: float | None = None) -> dict:
    """The model's reading of one message, then its look-ups, every one run to its end or to `ceiling` seconds,
    with everything measured.

    `chat_id` is the chat the message is in, whose title, task and last turns the model reads it with. `look`
    is where it is all kept as it goes, for whoever reads it before this returns. `say(event, call)` is told as
    the model's reading and each look-up starts and ends, and `say("named", None)` once the model has answered.
    Returns `{"entities", "calls", "items": [ids best first], "hits", "connect", "ms", "names_ms", "why",
    "pick"}`. When both models fail or are not back in `PICK_TIMEOUT_S` (`timeout`), nothing is looked up. A
    look-up not back by the ceiling has failed, and its call says so."""
    began = time.monotonic()
    look = look if look is not None else Lookups()
    me = people.me(ds)
    # Somebody limited to some of the person's silos reads only those (`rouh/silos.py`).
    from .. import silos

    asked_as = silos.asker(silos.limit_now(), me)
    readers = search.readers_for(asked_as)
    _vocabulary(ds, text, look, say, readers)
    from . import datasets

    model = str(datasets.settings(ds).recall_first_model)
    ents: list[Entity] = []
    try:
        got, lists, look.pick = ask(ds, text, chat_id=chat_id, me=me, timeout=timeout, say=say,
                                    calls=look.pick_calls)
        look.pick.related = bool(got.get("related"))
        ents = resolve(ds, got, lists, text=text, me=me, readers=readers)
        if not ents:
            look.why = "the message is about nothing to look up"
    except PickFailed as exc:
        look.pick = exc.pick
        look.why = "neither model could read the message, so nothing was looked up"
        log.info("recall: %s (%s)", look.why, exc.pick.error)
    except Exception as exc:  # noqa: BLE001 - a reading that cannot be used looks nothing up
        log.exception("recall: the models' reading could not be used")
        look.pick = look.pick or Pick(model=model, ok=False, error=f"{type(exc).__name__}: {exc}"[:300])
        look.why = "the models' reading could not be used, so nothing was looked up"
    look.names_ms = int((time.monotonic() - began) * 1000)
    look.entities = ents
    look.named = True
    if say:
        say("named", None)
    if not ents:
        out = look.found()
        out["ms"] = look.names_ms
        return out
    jobs: list[concurrent.futures.Future] = []

    def start(call: Call, fn, *args) -> None:
        with look.lock:
            look.calls.append(call)
        if say:
            say("start", call)
        jobs.append(_POOL.submit(_in_thread, call, say, look, fn, *args))

    for n, e in enumerate(ents):
        start(Call(f"{n}", "synapse_find", f"Recalling {e.label}", time.monotonic()), _look_up, ds, e, readers)
    # How they connect only when the model says they bear on each other: a walk between unrelated things
    # wanders, and what it wanders to is noise in the turn.
    if len(ents) >= 2 and look.pick is not None and look.pick.related:
        start(Call(f"{len(ents)}", "synapse_query", f"Recalling how {question(ents).rsplit(':', 1)[0]} connect",
                   time.monotonic()), _connect, ds, ents, asked_as)
    concurrent.futures.wait(jobs, timeout=max(0.0, began + ceiling - time.monotonic()))
    for call in list(look.calls):
        if not call.ended:
            call.end(say, False, f"not back in {ceiling:g} s")
    out = look.found()
    out["ms"] = int((time.monotonic() - began) * 1000)
    return out


#: The look-up that matches the person's vocabulary, by its id.
VOCABULARY_CALL = "v"


def _vocabulary(ds: dict, text: str, look: Lookups, say, readers: list[str]) -> None:
    """The entries of the person's vocabulary the message uses, by their term or another name, whole and in any
    case (`vocabulary.matches`): before any model reads the message, so an entry is in the block even when
    neither model answers, and never left out for scoring low on meaning, as a short nickname would."""
    from .. import vocabulary

    call = Call(VOCABULARY_CALL, "vocabulary", "Matching your vocabulary", time.monotonic())
    try:
        got = vocabulary.matches(ds, text, readers=readers)
    except Exception as exc:  # noqa: BLE001 - the rest of recall goes on without it
        log.exception("recall: the vocabulary could not be matched")
        with look.lock:
            look.calls.append(call)
        call.end(say, False, f"{type(exc).__name__}: {exc}"[:300])
        return
    if not got:
        return
    with look.lock:
        look.calls.append(call)
        look.vocabulary = got
    if say:
        say("start", call)
    call.count = len(got)
    look.results[call.id] = [{"id": e["id"], "kind": "vocabulary"} for e in got]
    call.end(say, True)


def _rank(ents: list[Entity], found: dict[int, list[str]], connected: list[str],
          ranks: dict[str, int] | None = None) -> tuple[list[str], dict]:
    """Best first: the named people's own cards and the named tasks, then what two or more named things share
    (the most first, then by `rank_of`; never a workspace file), then the best of what the connection walk found, in its order, then
    each thing's own, in turn."""
    ranks = ranks or {}
    hits: dict[str, set[int]] = {}
    for n, ids in found.items():
        for i in ids:
            hits.setdefault(i, set()).add(n)
    order: list[str] = []

    def put(i: str) -> None:
        if i not in order:
            order.append(i)

    for e in ents:
        if e.item and e.kind in ("person", "task"):
            put(str(e.item))
    # A workspace file is never put first for holding several named things: notes written about a meeting name
    # everybody in it, and it is the meeting that was asked about. It keeps its place among each thing's own.
    shared = [i for n in sorted(found) for i in found[n] if len(hits[i]) >= 2 and ranks.get(i, 3) < 4]
    for i in sorted(dict.fromkeys(shared), key=lambda i: (-len(hits[i]), ranks.get(i, 3))):
        put(i)
    for i in connected:
        put(i)
    rounds = max((len(v) for v in found.values()), default=0)
    for k in range(rounds):
        for n in sorted(found):
            if k < len(found[n]):
                put(found[n][k])
    return order, {i: sorted(v) for i, v in hits.items()}


# --- the block ------------------------------------------------------------------------------------------------

def _dupe_key(item: dict) -> str:
    """Two items a reader would call the same thing: the same title once Re:, Fwd: and the like are off it
    (an email and its forward, a calendar series' other days, a chat and the card it drew)."""
    title = re.sub(r"^\s*((re|fwd?|fw|aw|tr|chat|card)\s*:\s*)+", "", str(item.get("title") or ""), flags=re.I)
    # A task's notes file is the task, as its own item already says it.
    title = re.sub(r":\s*AGENTS\.md$", "", title)
    return tx.norm(title)


def _tokens_of(text: str) -> int:
    """Tokens a line costs, on the safe side: two characters a token. Synapse's word rule (`text.tokens`) counted
    a block of these lines at 1,200 where Anthropic's own counter said 2,281 (9 October 2026): an item's id, an
    address or a date is one word and a dozen tokens, and these lines are full of them."""
    return max(tx.tokens(text), (len(text) + 1) // 2)


def _line(item: dict) -> str:
    meta = item.get("meta") or {}
    if item.get("kind") == "vocabulary":
        from .. import vocabulary

        return (f"- vocabulary, {vocabulary.DEFINITION}: "
                + vocabulary.line({"term": meta.get("term") or item.get("title") or "",
                                   "meaning": meta.get("meaning") or "", "aliases": meta.get("aliases") or []})[2:]
                + f" (id {item['id']})")
    head = f"{item.get('kind') or 'item'}, {tx.item_date(item) or 'no date'}"
    who = tx._people(meta)
    if who:
        head += f", {who}"
    gist = str((item.get("xray") or {}).get("gist") or "").strip()
    if not gist:
        words = " ".join(str(item.get("start") or "").split())
        if item.get("kind") == "person":
            # Who somebody is, without their phone numbers or what research found on the web about them.
            words = re.sub(r"\bPhone:\s*[^A-Za-z]*", "", words.split("Online research:")[0]).strip()
        title = str(item.get("title") or "")
        if words.startswith(title):
            words = words[len(title):].strip()
        gist = words[:SNIPPET_CHARS] + ("..." if len(words) > SNIPPET_CHARS else "")
    line = f"- {head}: \"{item.get('title') or '(untitled)'}\" (id {item['id']})"
    return line + (f": {gist}" if gist else "")


def lines(ds: dict, ids: list[str], *, skip=(), budget: int = TOKENS,
          about: list | None = None) -> tuple[list[str], list[str], int]:
    """The lines for these items, best first, while they fit `budget` tokens, near-duplicates and `skip` left
    out. Returns the lines, the ids they are for, and the tokens they cost; `about`, when given, is filled with
    each shown item's id, kind and title, for the message's timeline."""
    ids = [i for i in ids if i not in set(skip)]
    if not ids:
        return [], [], 0
    rows = {r["id"]: r for r in db.rows(
        "SELECT id, kind, title, source_key, said_at, meta, xray, left(coalesce(body, raw, ''), 600) AS start "
        "FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) AND id = ANY(%s::uuid[]) AND deleted_at IS NULL",
        (ds["id"], ids))}
    out, shown, used, keys = [], [], 0, set()
    for i in ids:
        item = rows.get(i)
        if not item or NOISE.search(str(item.get("source_key") or "")):
            continue
        key = _dupe_key(item)
        if key and key in keys:
            continue
        line = _line(item)
        cost = _tokens_of(line)
        if used + cost > budget:
            if out:
                break
            continue
        keys.add(key)
        out.append(line)
        shown.append(i)
        used += cost
        if about is not None:
            about.append({"id": i, "kind": item.get("kind") or "", "title": str(item.get("title") or "")[:160]})
    return out, shown, used


def block(ds: dict, got: dict, *, skip=(), label: str = LABEL, budget: int = TOKENS) -> dict:
    """The block for the turn, `{"text", "shown", "items", "tokens"}`, at most `budget` with its label and its
    box; text "" when nothing came back. `items` is each shown item's id, kind and title."""
    from .. import untrusted

    said = got.get("vocabulary") or []
    looked = "; ".join(([("your vocabulary: " + ", ".join(f'"{e["term"]}"' for e in said))] if said else [])
                       + [e.label for e in got["entities"]])
    connect = " and how they connect" if got.get("connect") else ""
    head = f"{label} Looked up: {looked}{connect}.\n"
    frame = _tokens_of(head + untrusted.wrap("x", SOURCE))
    about: list[dict] = []
    found, shown, used = lines(ds, got.get("items") or [], skip=skip, budget=budget - frame, about=about)
    if not found:
        return {"text": "", "shown": [], "items": [], "tokens": 0}
    text = head + untrusted.wrap("\n".join(found), SOURCE)
    return {"text": text, "shown": shown, "items": about, "tokens": _tokens_of(text)}


def record(ds: dict, text: str, got: dict, made: dict, *, chat_id: str = "", bars: list[dict] | None = None,
           why: str = "") -> str | None:
    """The recall in Master's Activity, as a trace of its own, and one line in Rouh's log. Written once the
    turn is over and every look-up has ended, never in anybody's way. The trace's id back, or None.

    `made` is what went into the turns: `{"shown": [ids], "tokens", "text", "items": [{"id", "title", "when"}]}`.
    `bars` is each look-up as the message's timeline draws it (`recalling.MessageMemory.timeline`): its start
    and end from the moment the message came, its items, and its outcome - `in_time` (back for the turn's first
    request), `empty` (back with nothing), `late` (into the turn's next request), `carried` (kept for the next
    message in the chat) or `failed`."""
    from .trace import Trace

    calls = got.get("calls") or []
    bars = bars or []
    outcome = {b["id"]: b.get("outcome") for b in bars}
    pick: Pick | None = got.get("pick")
    if pick is not None:
        # The slower reader is never waited for by the turn; here, after it, for whether it agreed. It has
        # `PICK_TIMEOUT_S` from when it was asked; `recalling.MessageMemory` calls this once it has ended
        # (`Pick.when_settled`), so this wait is for anybody else calling it.
        asked = [r.asked for r in pick.readers if r.asked]
        pick.settle((max(asked) if asked else time.monotonic()) + PICK_TIMEOUT_S + 0.5)
    readers = "; ".join(f"{r.model} {r.ms if r.ms is not None else '-'} ms"
                        + (" first" if r.won else "") + ("" if r.valid else f" failed ({r.error})")
                        + ("" if r.agreed is None else " agreed" if r.agreed else " disagreed")
                        + f" ${r.cost:.5f}" for r in (pick.readers if pick else []))
    log.info("recall for %s: %d ms (read by %s in %d ms: %s), %d looked up (%s); %d items, %d tokens%s", chat_id,
             got.get("ms", 0), pick.model if pick and pick.ok else "nobody", pick.ms if pick else 0, readers or "-",
             len(got.get("entities") or []),
             "; ".join(f"{c.what[len('Recalling '):]}: {c.ms if c.ms is not None else '-'} ms, {c.count}, "
                       f"{outcome.get(c.id) or ('ok' if c.ok else 'failed')}"
                       + ("" if c.ok else f" ({c.error})") for c in calls) or got.get("why", ""),
             len(made.get("shown") or []), made.get("tokens", 0), f" ({why})" if why else "")
    if pick is None:
        return None
    # Each reading whole, the slower too, for evaluating the two readers against each other later.
    first = min((r.asked for r in pick.readers if r.asked), default=0.0)
    for r in pick.readers:
        if not r.asked:
            continue
        log.info("recall reading for %s by %s (%s, %s): %s, started at %d ms, %s ms, $%.5f%s, answer %s", chat_id,
                 r.model, r.provider, r.call.id,
                 "used, answered first" if r.won else "not used, answered second" if r.valid else "failed",
                 int((r.asked - first) * 1000), r.ms if r.ms is not None else "-", r.cost,
                 f" ({r.error})" if not r.valid else " agreed" if r.agreed else " disagreed" if r.agreed is False else "",
                 json.dumps(r.said, ensure_ascii=False, separators=(",", ":")) if r.said else "-")
    try:
        t = Trace(ds["id"], "recall", f"Automatic recall: {text[:110]}", by="rouh")
        with t.step("picked", "What the message is about, read by two models of two companies at once, the first "
                              "answer used: people, tasks, projects, topics, and whether they bear on each other") as st:
            st.data.update({"message": text[:MOST_CHARS], "ms": got.get("names_ms"), "model": pick.model,
                            "provider": pick.provider, "model_ms": pick.ms, "mode": pick.mode,
                            "context_ms": pick.context_ms, "ok": pick.ok, "error": pick.error,
                            "prompt_tokens": pick.prompt_tokens, "answer": pick.said, "related": pick.related,
                            "readers": [{**r.shown(), "call": r.call.id, "served": r.served, "answer": r.said,
                                         "tokens_in": r.tokens_in,
                                         "tokens_cached": r.tokens_cached, "tokens_out": r.tokens_out,
                                         "start_ms": None if not r.asked else int((r.asked - min(
                                             x.asked for x in pick.readers if x.asked)) * 1000)}
                                        for r in pick.readers],
                            "chat": chat_id, "entities": [
                {"kind": e.kind, "label": e.label, "words": e.words, "phrases": e.phrases, "person": e.person,
                 "item": e.item, "folder": e.folder} for e in got.get("entities") or []]})
            for r in pick.readers:
                if r.asked:
                    t.call(kind="generate", purpose="recall_pick", backend=r.provider, model=r.model,
                           version=r.served, ms=r.ms, tokens_in=r.tokens_in, tokens_out=r.tokens_out, cost=r.cost,
                           ok=r.valid, error=r.error)
        with t.step("look_ups", "One find per thing named, and how they connect, in parallel, each to its end") as st:
            st.data.update({"calls": [{"tool": c.tool, "what": c.what, "ms": c.ms, "items": c.count, "ok": c.ok,
                                       "error": c.error, **{k: b[k] for b in bars if b["id"] == c.id
                                                            for k in ("start_ms", "end_ms", "outcome")}}
                                      for c in calls],
                            "seeds": [b for b in bars if b["id"] == "seeds"],
                            "connect_query": (got.get("connect") or {}).get("query"),
                            "connect_trace": (got.get("connect") or {}).get("trace"),
                            "connect_walked": (got.get("connect") or {}).get("walked"),
                            "connect_kept": (got.get("connect") or {}).get("ids"),
                            "connect_from": CONNECT_FROM})
        with t.step("block", "What went into the turns, best first, near-duplicates out: in the first request, "
                             "after the tools of a later one, or with the next message") as st:
            st.data.update({"items": made.get("shown") or [], "tokens": made.get("tokens", 0),
                            "budget": TOKENS, "used": bool(made.get("shown")), "text": made.get("text", ""),
                            "where": made.get("items") or []})
        t.finish("done", ms_total=got.get("ms"), items=len(made.get("shown") or []), tokens=made.get("tokens", 0))
        # The recall's own time, not the few milliseconds writing it down took.
        db.run("UPDATE synapse.trace SET ms = %s WHERE id = %s", (int(got.get("ms") or 0), t.id))
        return str(t.id)
    except Exception:  # noqa: BLE001 - the record is never worth a failure anywhere else
        log.exception("recall: its trace could not be written")
        return None


#: `recall_wait_ms` as the last recall read it, for a turn whose recall has not read its dataset yet.
_wait = {"s": WAIT_S}


def wait_seconds(ds: dict | None = None) -> float:
    """How long the turn's first request waits for recall: the dataset's `recall_wait_ms`, remembered for the
    next turn, or the last one read when no dataset is given."""
    if ds is not None:
        from . import datasets

        try:
            _wait["s"] = max(0, int(datasets.settings(ds).recall_wait_ms)) / 1000.0
        except Exception:  # noqa: BLE001 - a number that cannot be read is the last one that could
            log.exception("recall: its wait could not be read")
    return _wait["s"]


def on(org_id) -> bool:
    from .. import switches

    return switches.on(SWITCH, org_id)


_registered: set[str] = set()
_lock = threading.Lock()


def register(org_id: str) -> None:
    """The switch, under Other switches in Evolution, Mutations, the first time this process recalls for an organisation."""
    with _lock:
        if org_id in _registered:
            return
        _registered.add(org_id)
    try:
        from .. import switches

        switches.register(SWITCH, TITLE, org_id=org_id)
    except Exception:  # noqa: BLE001
        log.exception("recall: its switch could not be registered")
