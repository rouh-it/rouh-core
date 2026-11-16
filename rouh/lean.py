"""What this Rouh keeps and runs: the one place a job asks whether it runs and a record whether it
is kept, and for how long (task 185, Lean Rouh).

Petar, 15 November 2026: "I think those options should have the defaults you have assigned. and I
think those should be available to change through your own instance settings. so we provide
default behavior. anyone can go in anatomy and change them to something else. days should include
a keep forever behavior."

**The items.** `ITEMS` is every job and step only the Creator Rouh or a developer needs, and every
record Rouh used to keep forever (step 185-01), each with its modes. A job is off, on, or one of
its own modes (only in the Synapse lab by hand, follows the nightly feature run, ...). A record is
off, kept for a number of days, or kept forever; the nightly database copies are counted in copies,
and the old versions of memory items, contacts, workspace pages, cards and files are kept for a number
of days or as the newest number of versions, never off, since Undo reads them.

**Where a value comes from.** A Rouh's own choice (`LeanChoice`, written on Anatomy, Meta, What
Rouh keeps and runs) wins, then its preset (`PRESETS`, chosen on the same page), then the item's
code default (the Installed preset's). Only a Rouh's own choices are rows, so when an update
changes a default it reaches every Rouh that has not changed that item itself. A Rouh with no
preset row is Installed, or Creator on the Rouh that makes Rouh's releases (`_detected`); while
that cannot be told it behaves as today, everything on and kept, and writes nothing.

**Asking.** A job asks `runs(item)` where it starts and does nothing when it is False; a record
asks `keeps(item)` before it writes. `mode(item)` is the raw mode for the rare caller that needs
it. None of them raises: a setting that cannot be read is today's behaviour (on, kept).

**Deleting is never silent.** Lowering a limit or switching a record off removes old rows, which
cannot be undone. So the daily sweep (`sweep`) deletes only beyond `LeanApplied`, the limit last
confirmed: a raise is applied at once, a lowering only once the owner pressed to confirm on the
page what would go (`preview`), or when nothing would go at all (a fresh install). An update that
lowers a default therefore waits on the page too. Floors: at least one database copy, and the
newest versions of every memory item, contact, workspace page, card and file are always kept,
whatever the limit, with a card's and a file's first version, so Undo always has what it needs.

**Outside the database.** Two records are not rows Rouh deletes itself. The nightly copies are
made and removed by the protected core's copy part (`guard/bin/rouh-backup`), which keeps the
number confirmed here (`LeanApplied` for `nightly_copies`) and reads nothing else of Rouh's; the
core only reads the copies, to say what a lower number would remove. The run logs are the one
program's files: Rouh asks it over its socket (`run_logs`, `one/runs.py` `trim_logs`) to count them,
and to remove them once the limit is confirmed. When the program does not answer, what would go
cannot be counted, so nothing is confirmed and nothing is removed.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import threading
import time
from typing import Any

log = logging.getLogger("rouh.lean")

PRESET_NAMES = ("installed", "developer", "creator")
PRESET_SAID = {"installed": "Installed", "developer": "Developer", "creator": "Creator Rouh"}
PRESET_ABOUT = {
    "installed": "Every new install: the nightly feature run on, the creator's other night jobs and test tools off, "
                 "records kept for a while.",
    "developer": "Someone who builds Rouh: test tools, the nightly feature run and Synapse's nightly try on, "
                 "records kept longer.",
    "creator": "The Rouh that makes Rouh's releases: everything on and every record kept.",
}
#: The days a kept record offers, besides its preset's own value.
DAYS = (7, 14, 30, 90)
#: The copies the nightly database copies offer; never fewer than one (the floor).
COPIES = (1, 2, 3, 5, 7)
#: The newest versions a version record offers to keep of each thing; never fewer than UNDO_FLOOR.
VERSIONS = (20, 50, 100, 200)
#: The newest versions of each memory item, contact, page, card and file always kept, whatever the limit (Undo's floor).
UNDO_FLOOR = 20
#: How long a value read is kept before it is read again, in seconds.
FRESH = 5.0
#: How often the sweep runs, in seconds.
SWEEP_EVERY = 23 * 3600
#: How many rows one statement of the sweep deletes, so no statement holds a table for long.
BATCH = 5000

MODE_SAID = {
    "off": "Off", "on": "On", "lab": "Only in the Synapse lab, by hand", "later": "On once its test passes (D86)",
    "follow": "Follows the nightly feature run", "list": "Only the list of installed genes",
    "trigger": "On, as a trigger at landing", "forever": "Keep forever", "keep": "Keep",
    "versions": "Keep the newest",
}


@dataclasses.dataclass(frozen=True)
class Part:
    """One table a record's sweep works on."""
    table: str
    pk: str
    when: str
    #: "epoch" (seconds since 1970) or "ts" (timestamptz).
    kind: str = "epoch"
    #: "org" (an org_id column, `org_col`), "dataset" (a Synapse dataset_id), "file" (a file_id of the
    #: organisation's files), "install" (no owner column: only the install's own organisation sweeps it)
    #: or "all".
    scope: str = "org"
    org_col: str = "org_id"
    #: More of the WHERE clause, already safe SQL.
    extra: str = ""
    #: Columns set to blank instead of deleting the row; empty means delete.
    blank: str = ""
    #: The newest N of each group kept whatever their age (Undo's floor): (group by, order by).
    floor: tuple[str, str] | None = None
    #: For a part that blanks: the rows that still hold something, so a row already blank is never counted.
    full: str = ""
    #: A column naming a file on disk that goes with the row (a file version's kept copy).
    unlink: str = ""


@dataclasses.dataclass(frozen=True)
class Item:
    id: str
    kind: str                # "job" or "record"
    name: str
    what: str
    modes: tuple[str, ...]
    wave: int = 1
    #: Measured on the Creator Rouh (185-01), GB a day of growth when kept forever.
    rate: float | None = None
    #: The money line for a job, as measured or capped.
    money: str = ""
    #: Copies rather than days.
    copies: bool = False
    #: What off means, for a record whose rows Rouh reads while it works.
    off_means: str = ""
    parts: tuple[Part, ...] = ()
    #: Tables whose size is shown, when not the parts' own.
    sized: tuple[str, ...] = ()
    #: Why the sweep does not act on it yet, when it does not.
    not_yet: str = ""
    #: The question and answer of the item's choice that a setting off loses.
    note: str = ""
    #: Earlier versions, which Undo reads: never off, and kept by days or as the newest number of each.
    versions: bool = False
    #: Removed outside Rouh's database: "copies" (the protected core's copy part) or "run_logs" (the one program).
    outside: str = ""
    #: The page where the same setting is also changed, and the words of the link to it.
    link: str = ""
    link_said: str = ""


_OLD_ROWS = "status <> 'running'"
#: The memory items that are people: their versions are contacts' (`synapse/sources/contacts.write`).
_PERSON = "item_id IN (SELECT id FROM synapse.item WHERE kind = 'person')"

#: What an Off heartbeat stops, said on its row here and on the Heartbeat page (`rouh/heartbeat.py`).
HEARTBEAT_OFF = ("Off: nothing beats by itself. Quests don't advance by themselves, its duties (waiting "
                 "work, unreported runs, Rouh's inbox, the calendar, goal steps) are not looked at, no "
                 "Telegram comes from it, and mail, finished runs and completed steps don't wake it. A yes "
                 "you give in Decisions still runs exactly what was queued, and jobs' requests still reach "
                 "you; Beat now and a quest's Check now still run one beat when you press them.")

ITEMS: tuple[Item, ...] = (
    # ---- night and background jobs ----
    Item("heartbeat", "job", "The heartbeat",
         "Rouh's own turn nobody asked for: every half hour or so in working hours, and when a run ends or "
         "mail arrives, it works on its duties and carries the quests.",
         ("off", "on"), money="its daily cap, $3 a day unless you set another", note=HEARTBEAT_OFF,
         link="/anatomy/behaviour/heartbeat/settings", link_said="Heartbeat settings"),
    Item("synapse_nightly", "job", "Synapse's nightly improvement try (02:00)",
         "Each night an Opus coding run tries to make Synapse, Rouh's memory search, better.",
         ("off", "on"), money="one Opus coding run a night; not measured"),
    Item("synapse_tests", "job", "Synapse's test runs and benchmark",
         "Test runs of Synapse against a frozen set of questions, started in the lab, the chat or a command.",
         ("off", "lab", "on"), money="only when started; 5.0 of the 5.66 GB of saved searches were October's test runs"),
    Item("memory_judge", "job", "The memory judge",
         "A second model that grades Synapse's answers in judged test runs, never on a normal question.",
         ("off", "lab", "on"), money="$99.58 in October on Opus 5.5, about $3.51 a judged run"),
    Item("nightly_refactor", "job", "Nightly refactoring run (03:00)",
         "A run each night that tidies Rouh's code.",
         ("off", "on"), money="a paid run some nights; not measured"),
    Item("nightly_feature", "job", "Nightly feature run (04:30)",
         "Builds new Rouh features each night and ships them.",
         ("off", "on"), money="up to $100 a night, $3,000 a month"),
    Item("gene_log", "job", "Gene log of what lands",
         "Writes each change of Rouh's code into the gene log when it lands, with a daily catch-up.",
         ("off", "list", "on", "trigger"), money="a model call only for a change with no gene label"),
    Item("trial_stage", "job", "Tester stage in gene-therapy briefs",
         "When Rouh changes its own code, a made-up tester tries each new screen on a phone.",
         ("off", "on"), money="extra model calls each run; not measured"),
    Item("tester_problems", "job", "Tester problems from the owner's messages",
         "Turns what the owner says is confusing into problems on the testers' list.",
         ("off", "on"), money="none"),
    Item("gap_tracker", "job", "The gap tracker",
         "A tool that lists the gaps between Rouh's own turn loop and the Claude Agent SDK.",
         ("off", "on"), money="its words in every turn"),
    Item("dreaming", "job", "Synapse dreaming (01:00)",
         "A nightly tidy of memory, started from its Clockwork row.",
         ("off", "later", "on"), wave=3, money="up to $2 a night"),
    Item("mutations", "job", "Mutations upkeep",
         "Every 15 minutes brings in the genes the nightly feature run built, starts and decides their trials.",
         ("off", "follow", "on"), wave=3, money="none"),
    # ---- records ----
    Item("model_words", "record", "Model calls: their full words",
         "Every word sent to a model and back, with its reasoning. Cost and tokens are kept apart, below.",
         ("off", "keep", "forever"), rate=0.9,
         parts=(Part("llm_requests", "id", "started_at",
                     blank="text = '', reasoning = '', response = NULL, settings = '{}'::jsonb, "
                           "message_pieces = '[]'::jsonb, system_piece = '', tools_piece = ''",
                     full="(text <> '' OR reasoning <> '' OR response IS NOT NULL OR system_piece <> '' "
                          "OR message_pieces <> '[]'::jsonb)"),),
         sized=("llm_requests", "llm_pieces")),
    Item("synapse_working", "record", "Synapse searches: their working",
         "For each memory search, the path it took and the passages handed to the model.",
         ("off", "keep", "forever"), rate=0.007,
         off_means="Off keeps a day: an answer's sources are opened from it while its chat is fresh.",
         parts=(Part("synapse.query", "id", "created_at", kind="ts", scope="dataset", extra=_OLD_ROWS,
                     blank="walk = '{}'::jsonb, pack = '{}'::jsonb",
                     full="(walk <> '{}'::jsonb OR pack <> '{}'::jsonb)"),),
         sized=("synapse.query",)),
    Item("synapse_steps", "record", "Synapse step logs",
         "A log of every step and call of every search; each search's cost total is kept.",
         ("off", "keep", "forever"), rate=0.08,
         off_means="Off keeps a day: Rouh reads a search's steps while it runs.",
         parts=(Part("synapse.trace_step", "id", "started_at", kind="ts", scope="dataset"),
                Part("synapse.call", "id", "at", kind="ts", scope="dataset"))),
    Item("nightly_copies", "record", "Nightly database copies",
         "A whole copy of the database each night, in case it is lost. Counted in copies.",
         ("keep",), copies=True, outside="copies",
         note="The protected core's copy part keeps this many. A lower number removes the oldest copies "
              "at the next night's copy, and only after you pressed to remove them here."),
    Item("turn_records", "record", "Turn records and recall timelines",
         "What happened in each turn of a conversation, and how memory and the model were picked for it.",
         ("off", "keep", "forever"), wave=2, rate=0.0002,
         off_means="Off keeps a day: the line under a fresh answer is drawn from it.",
         parts=(Part("turn_records", "turn_id", "started_at"),
                Part("recall_timelines", "message_id", "ts", scope="all"),
                Part("route_timelines", "call", "ts", scope="all"))),
    Item("model_outcome", "record", "How each model call turned out",
         "Whether a model call worked, which is how Rouh compares models.",
         ("off", "keep", "forever"), wave=2, rate=0.0022,
         off_means="Off keeps a day: Rouh counts each day's outcomes.",
         parts=(Part("model_outcome", "id", "started_at"),)),
    Item("usage_events", "record", "Usage events",
         "Each press and opening, for the Stats page. The hourly totals are always kept.",
         ("off", "keep", "forever"), wave=2, rate=0.00042,
         off_means="Off keeps a day: the totals are counted from it first.",
         parts=(Part("analytics.event", "id, occurred_at", "occurred_at", kind="ts"),)),
    Item("synapse_jobs", "record", "Finished memory-import jobs",
         "The rows of memory imports that have finished. Nothing reads them afterwards.",
         ("off", "keep", "forever"), wave=2, rate=0.0018,
         off_means="Off keeps a day after a job finishes.",
         parts=(Part("synapse.job", "id", "done_at", kind="ts", scope="dataset", extra="done_at IS NOT NULL"),)),
    Item("audit_trails", "record", "Debug and audit trails",
         "How each email case was handled, problems with agent instructions, and the heartbeat's beats.",
         ("off", "keep", "forever"), wave=2, rate=0.0008,
         off_means="Off keeps a day: a case being handled reads its own trail.",
         parts=(Part("mail_case_traces", "id", "at"),
                Part("agent_instruction_issue", "id", "at"),
                Part("heartbeat_beats", "id", "started_at", extra="finished_at IS NOT NULL"))),
    Item("old_versions", "record", "Old versions of memory items",
         f"Earlier versions of what memory holds, besides contacts. The newest {UNDO_FLOOR} of each are "
         "always kept, so Undo always works.",
         ("keep", "versions", "forever"), wave=2, versions=True,
         parts=(Part("synapse.item_version", "id", "made_at", kind="ts", scope="dataset",
                     extra=f"(keep_until IS NULL OR keep_until < now()) AND NOT {_PERSON}",
                     floor=("dataset_id, item_id", "version")),)),
    Item("contact_versions", "record", "Old versions of contacts",
         f"Each contact as it was before a change, which 'what changed on a contact' reads and puts back. "
         f"The newest {UNDO_FLOOR} of each are always kept.",
         ("keep", "versions", "forever"), wave=2, versions=True,
         parts=(Part("synapse.item_version", "id", "made_at", kind="ts", scope="dataset",
                     extra=f"(keep_until IS NULL OR keep_until < now()) AND {_PERSON}",
                     floor=("dataset_id, item_id", "version")),)),
    Item("page_versions", "record", "Old versions of workspace pages",
         f"Each change Ask AI or a comment made to a page, whole, for its history and Undo. The newest "
         f"{UNDO_FLOOR} of each page, and every version you kept as an option, are always kept.",
         ("keep", "versions", "forever"), wave=2, versions=True,
         parts=(Part("askai_edits", "id", "created_at", org_col="page_org_id", extra="keep = ''",
                     floor=("page_org_id, doc", "id")),)),
    Item("card_versions", "record", "Old versions of cards",
         f"Each earlier version of a card, page or document on the canvas. Its first version, the one shown "
         f"and the newest {UNDO_FLOOR} are always kept. Versions carry no date, so they are counted.",
         ("versions", "forever"), wave=2, versions=True,
         parts=(Part("artifact_version", "artifact_id, version", "", scope="install",
                     extra="version > 1 AND (artifact_id, version) NOT IN (SELECT id, head_version FROM artifact)",
                     floor=("artifact_id", "version")),)),
    Item("file_versions", "record", "Old versions of files",
         f"Each earlier state of a file on the list, with its copy on this disk. Its first state and the "
         f"newest {UNDO_FLOOR} are always kept, and so is every version kept in the weekly copy's store.",
         ("keep", "versions", "forever"), wave=2, versions=True,
         parts=(Part("file_version", "id", "made_at", scope="file", extra="number > 1 AND r2_key = ''",
                     floor=("file_id", "number"), unlink="kept_at"),)),
    Item("run_logs", "record", "Run logs on disk",
         "The terminal log of each job, removed once the job ended that long ago. The job and its report stay.",
         ("off", "keep", "forever"), wave=2, outside="run_logs",
         off_means="Off keeps a day after a job ends."),
    Item("model_costs", "record", "Model calls: cost, tokens and time",
         "What each model call cost and how long it took. Rouh's budgets read it.",
         ("off", "keep", "forever"),
         off_means="Off keeps a day: budgets read today's spending from it.",
         parts=(Part("llm_requests", "id", "started_at"),), sized=("-",),
         note="Removing a call's row removes its words too."),
)
BY_ID: dict[str, Item] = {i.id: i for i in ITEMS}
JOBS = tuple(i.id for i in ITEMS if i.kind == "job")
RECORDS = tuple(i.id for i in ITEMS if i.kind == "record")

#: Each preset's values: Petar's own picks in step 185-02 (`choices.json`, `by: "petar"`) where he made
#: one, else Rouh's suggestions there; database copies at 3 on every preset he did not pick otherwise
#: (Installed: 1, his pick, which is the floor). A record "on" there is "forever" here. The old versions
#: of contacts, pages, cards and files came after 185-02 (step 185-04) and are Rouh's suggestions.
#: The heartbeat came 16 November 2026 (185-05, Petar: "heartbeat should be off by default"): Off on
#: Installed and Developer, On on the Creator Rouh; a Rouh that had one running kept it on as its own
#: choice (migration 0257).
#: Changed 15 November 2026 (185-04): Installed got the nightly feature run on, the gene log as a
#: trigger, dreaming on, model-call words 14 days, Synapse searches 14 days and 1 copy; Developer got
#: Synapse's 02:00 try on, the nightly feature run on, the gene log as a trigger, the gap tracker on,
#: dreaming on and Synapse searches 30 days.
PRESETS: dict[str, dict[str, tuple[str, int | None]]] = {
    "installed": {
        "heartbeat": ("off", None),
        "synapse_nightly": ("off", None), "synapse_tests": ("off", None), "memory_judge": ("off", None),
        "nightly_refactor": ("off", None), "nightly_feature": ("on", None), "gene_log": ("trigger", None),
        "trial_stage": ("off", None), "tester_problems": ("off", None), "gap_tracker": ("off", None),
        "dreaming": ("on", None), "mutations": ("follow", None),
        "model_words": ("keep", 14), "synapse_working": ("keep", 14), "synapse_steps": ("keep", 14),
        "nightly_copies": ("keep", 1), "turn_records": ("keep", 30), "model_outcome": ("keep", 90),
        "usage_events": ("keep", 90), "synapse_jobs": ("keep", 30), "audit_trails": ("keep", 90),
        "old_versions": ("keep", 90), "contact_versions": ("keep", 90), "page_versions": ("keep", 90),
        "card_versions": ("versions", 50), "file_versions": ("keep", 90),
        "run_logs": ("keep", 30), "model_costs": ("keep", 400),
    },
    "developer": {
        "heartbeat": ("off", None),
        "synapse_nightly": ("on", None), "synapse_tests": ("lab", None), "memory_judge": ("lab", None),
        "nightly_refactor": ("off", None), "nightly_feature": ("on", None), "gene_log": ("trigger", None),
        "trial_stage": ("on", None), "tester_problems": ("on", None), "gap_tracker": ("on", None),
        "dreaming": ("on", None), "mutations": ("follow", None),
        "model_words": ("keep", 30), "synapse_working": ("keep", 30), "synapse_steps": ("keep", 30),
        "nightly_copies": ("keep", 3), "turn_records": ("keep", 90), "model_outcome": ("keep", 90),
        "usage_events": ("keep", 90), "synapse_jobs": ("keep", 30), "audit_trails": ("keep", 90),
        "old_versions": ("keep", 90), "contact_versions": ("keep", 90), "page_versions": ("keep", 90),
        "card_versions": ("versions", 100), "file_versions": ("keep", 90),
        "run_logs": ("keep", 30), "model_costs": ("keep", 400),
    },
    "creator": {
        **{j: ("on", None) for j in JOBS}, "dreaming": ("later", None),
        **{r: ("forever", None) for r in RECORDS}, "nightly_copies": ("keep", 3),
    },
}
#: Petar's own picks for the Creator Rouh where they differ from its preset (185-02, `choices.json`,
#: creator column, `by: "petar"`), written as his own choices when the Creator Rouh is first set up.
CREATOR_PICKS: dict[str, tuple[str, int | None]] = {"gene_log": ("trigger", None), "dreaming": ("on", None)}
PICKS_BY = "Petar's pick in 185-02"

_seen: dict[tuple, tuple[float, Any]] = {}
#: Every mode last read, by organisation and item, never expired: what a caller that may not touch the
#: database (the event loop's thread) reads (`peek`), kept fresh by `refresh` once a minute.
_last: dict[tuple[str, str], str] = {}
_lock = threading.Lock()
_detect: list = []


class Refused(ValueError):
    """A choice that cannot be made, with the reason."""


class Off(RuntimeError):
    """A job asked to start while its item is off, with the words to say."""


def _org(org_id=None) -> str:
    if org_id:
        return str(org_id)
    from .modeldefaults import org_now

    return str(org_now())


def _m():
    from . import models

    return models


def _now() -> float:
    return time.time()


def forget() -> None:
    """Every value read is read again."""
    with _lock:
        _seen.clear()


# --- which preset ----------------------------------------------------------------------------------

def _detected() -> str | None:
    """creator on the Rouh that makes Rouh's releases, installed on any other, None when it cannot
    be told now (its protected core did not answer). Kept for the process once told."""
    if _detect:
        return _detect[0]
    said = (os.environ.get("ROUH_LEAN_PRESET") or "").strip().lower()
    if said in PRESET_NAMES:
        _detect.append(said)
        return said
    from . import base_patches

    flag = (os.environ.get("ROUH_MAKES_RELEASES") or "").strip()
    if flag:
        got = "installed" if flag in ("0", "no", "false") else "creator"
    else:
        try:
            from . import guardface

            if guardface.here():
                try:
                    answer = guardface.ask("upstream", timeout=30)
                except (guardface.Refused, guardface.Unavailable):
                    return None
                got = "creator" if (answer.get("on") and answer.get("ready")) else (
                    "creator" if base_patches.RELEASE_REPO.search(base_patches.origin_url()) else "installed")
            else:
                got = "creator" if base_patches.RELEASE_REPO.search(base_patches.origin_url()) else "installed"
        except Exception:  # noqa: BLE001 - cannot be told now: behave as today, write nothing
            log.exception("lean: could not tell whether this Rouh makes releases")
            return None
    _detect.append(got)
    return got


def ensure(org_id=None) -> str | None:
    """The organisation's preset row, made once: Creator (with Petar's picks over it, as his own
    choices) on the Rouh that makes releases, Installed on every other. None while that cannot be
    told. Never changes a row that is there."""
    org = _org(org_id)
    M = _m()
    row = M.LeanState.objects.filter(org_id=org).first()
    if row is not None:
        return row.preset
    found = _detected()
    if found is None:
        return None
    now = _now()
    _, made = M.LeanState.objects.get_or_create(org_id=org, defaults={
        "preset": found, "changed_by": "set up by Rouh" + (" (the Rouh that makes releases)" if found == "creator" else ""),
        "updated_at": now})
    if made and found == "creator":
        for item, (mode, days) in CREATOR_PICKS.items():
            M.LeanChoice.objects.get_or_create(org_id=org, item=item, defaults={
                "mode": mode, "days": days, "by": PICKS_BY, "updated_at": now})
    if made:
        log.info("lean: %s set up on the %s preset", org, found)
    forget()
    return found


def preset(org_id=None) -> str | None:
    """The organisation's preset; None while it cannot be told (today's behaviour holds then)."""
    org = _org(org_id)
    key = ("preset", org)
    got = _cached(key)
    if got is not _MISS:
        return got
    try:
        value = ensure(org)
    except Exception:  # noqa: BLE001 - today's behaviour, and the log says why
        log.exception("lean: the preset of %s could not be read", org)
        value = None
    _keep(key, value)
    return value


_MISS = object()


def _cached(key):
    now = time.monotonic()
    with _lock:
        got = _seen.get(key)
        if got is not None and now - got[0] < FRESH:
            return got[1]
    return _MISS


def _keep(key, value) -> None:
    with _lock:
        _seen[key] = (time.monotonic(), value)


# --- one item's value --------------------------------------------------------------------------------

def _today(item: Item) -> tuple[str, int | None]:
    """What the item did before it had a setting: on, kept forever."""
    if item.copies:
        return ("keep", 3)
    return ("on", None) if item.kind == "job" else ("forever", None)


def preset_value(item_id: str, name: str | None) -> tuple[str, int | None]:
    item = BY_ID[item_id]
    if name is None:
        return _today(item)
    return PRESETS.get(name, {}).get(item_id) or PRESETS["installed"].get(item_id) or _today(item)


def choice(item_id: str, org_id=None) -> dict:
    """The item's value here, and where it comes from: yours, the preset's, or today's (while the
    preset cannot be told)."""
    item = BY_ID[item_id]
    org = _org(org_id)
    key = ("choice", org, item_id)
    got = _cached(key)
    if got is not _MISS:
        return got
    name = preset(org)
    base_mode, base_days = preset_value(item_id, name)
    value = {"mode": base_mode, "days": base_days, "from": "preset" if name else "today", "by": ""}
    if name is not None:
        try:
            row = _m().LeanChoice.objects.filter(org_id=org, item=item_id).first()
        except Exception:  # noqa: BLE001 - the preset's value, and the log says why
            log.exception("lean: the choice %s of %s could not be read", item_id, org)
            row = None
        if row is not None and row.mode in item.modes:
            value = {"mode": row.mode, "days": row.days, "from": "yours", "by": row.by or ""}
    _keep(key, value)
    with _lock:
        _last[(org, item_id)] = value["mode"]
    return value


def refresh(org_id=None) -> None:
    """Every item read again, so `peek` has it."""
    org = _org(org_id)
    for item in ITEMS:
        choice(item.id, org)


def peek_runs(item_id: str, org_id: str = "") -> bool:
    """`runs` from the last values read, without the database: today's behaviour (on) until a value
    was read. For the event loop's own thread, which may not ask the database."""
    def got(i: str) -> str:
        with _lock:
            if org_id:
                return _last.get((org_id, i), "on")
            seen = [m for (o, it), m in _last.items() if it == i]
        return seen[0] if len(seen) == 1 else (seen[0] if seen and len(set(seen)) == 1 else "on")
    m = got(item_id)
    if m in ("off", "list"):
        return False
    if m == "follow":
        return got("nightly_feature") != "off"
    return True


def mode(item_id: str, org_id=None) -> str:
    try:
        return choice(item_id, org_id)["mode"]
    except Exception:  # noqa: BLE001 - today's behaviour
        log.exception("lean: %s could not be read", item_id)
        return _today(BY_ID[item_id])[0] if item_id in BY_ID else "on"


def runs(item_id: str, org_id=None) -> bool:
    """Whether a job runs here. Off is off; "follow" is the nightly feature run's answer; "list" (the gene
    log) writes nothing but keeps the list of installed genes; every other mode runs, "lab" only when
    started by hand, which is the only way such a job starts."""
    got = mode(item_id, org_id)
    if got == "off" or got == "list":
        return False
    if got == "follow":
        return mode("nightly_feature", org_id) != "off"
    return True


def require(item_id: str, org_id=None) -> None:
    """Off, with the words to say, when the job is off here."""
    if not runs(item_id, org_id):
        raise Off(f"{BY_ID[item_id].name} is off on this Rouh. Turn it on in Anatomy, Meta, "
                  "What Rouh keeps and runs.")


def setting(item_id: str, org_id=None) -> dict:
    """One job's value as another page draws its own switch for it (the Heartbeat page's On / Off):
    the same value and the same source as its row here, never a second value."""
    item = BY_ID[item_id]
    org = _org(org_id)
    try:
        got = choice(item_id, org)
        name = preset(org)
    except Exception:  # noqa: BLE001 - today's behaviour, and the log says why
        log.exception("lean: %s could not be read", item_id)
        got, name = {"mode": _today(item)[0], "days": None, "from": "today", "by": ""}, None
    base = preset_value(item_id, name)
    return {"item": item_id, "mode": got["mode"], "on": runs(item_id, org), "from": got["from"],
            "changed": got["from"] == "yours", "by": got["by"], "preset": name or "",
            "preset_said": PRESET_SAID.get(name or "", ""), "default_mode": base[0],
            "default_said": MODE_SAID.get(base[0], base[0]), "off_means": item.note,
            "anatomy": "/anatomy/meta/keeps"}


def keeps(item_id: str, org_id=None) -> bool:
    """Whether a record is written at all here."""
    return mode(item_id, org_id) != "off"


def skipped_line(item_id: str) -> str:
    """What a scheduled row says it did when its job is off."""
    return f"skipped: {BY_ID[item_id].name} is off in Anatomy, Meta, What Rouh keeps and runs"


# --- ordering limits ---------------------------------------------------------------------------------

def _span(mode_: str, days: int | None) -> float:
    """How much a record's value keeps, to compare two: off keeps a day at most, forever everything."""
    if mode_ == "forever" or mode_ == "on":
        return float("inf")
    if mode_ == "keep":
        return float(days or 0)
    return 0.0


def _removes(item: Item) -> bool:
    """Whether a record's value can remove anything: rows of Rouh's database, or what is outside it."""
    return item.kind == "record" and bool(item.parts or item.outside)


def cut_days(item: Item, mode_: str, days: int | None) -> float | None:
    """The age in days beyond which a record's rows go, or None for never (or, for "versions", not by
    age). For the nightly copies, the number of copies kept."""
    if item.copies:
        return float(days or 1) if mode_ == "keep" else None
    if not _removes(item) or mode_ == "versions":
        return None
    span = _span(mode_, days)
    if span == float("inf"):
        return None
    if mode_ == "off":
        return 1.0
    return max(1.0, span)


def _looser_or_same(item: Item, new_mode: str, new_days, old_mode: str, old_days) -> bool:
    """Whether `new` never removes anything `old` keeps. Keeping by days and keeping the newest number
    of versions cannot be compared, so between those two it is False and what would go is counted."""
    if new_mode in ("forever", "on"):
        return True
    if old_mode in ("forever", "on"):
        return False
    if item.copies:
        return int(new_days or 1) >= int(old_days or 1)
    if new_mode == "versions" or old_mode == "versions":
        return new_mode == old_mode and int(new_days or 0) >= int(old_days or 0)
    new, old = cut_days(item, new_mode, new_days), cut_days(item, old_mode, old_days)
    return new is None or (old is not None and new >= old)


# --- sizes and previews ------------------------------------------------------------------------------

def _sql(query: str, params=(), *, timeout_ms: int = 0):
    from django.db import connection

    with connection.cursor() as cur:
        if timeout_ms:
            cur.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        cur.execute(query, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001 - a statement that returns no rows
            return []


def _size(table: str) -> int:
    """A table's bytes on disk with its indexes, and its partitions' for a partitioned one."""
    try:
        got = _sql("SELECT coalesce(pg_total_relation_size(%s::regclass), 0) + coalesce(("
                   "SELECT sum(pg_total_relation_size(inhrelid)) FROM pg_inherits WHERE inhparent = %s::regclass), 0)",
                   (table, table))
        return int(got[0][0] or 0)
    except Exception:  # noqa: BLE001 - a table this Rouh does not have yet
        return 0


def _rows_estimate(table: str) -> int:
    try:
        got = _sql("SELECT coalesce(sum(reltuples), 0) FROM pg_class WHERE oid = %s::regclass "
                   "OR oid IN (SELECT inhrelid FROM pg_inherits WHERE inhparent = %s::regclass)", (table, table))
        return max(0, int(got[0][0] or 0))
    except Exception:  # noqa: BLE001
        return 0


def _install_org() -> str:
    from .modeldefaults import org_now

    return str(org_now())


def _bounds(item: Item, mode_: str, days: int | None) -> tuple[float | None, int] | None:
    """What a value removes, as (rows older than this time or None for any age, beyond the newest this
    many of each); None when it removes nothing."""
    if mode_ == "versions":
        return None, max(UNDO_FLOOR, int(days or UNDO_FLOOR))
    cut = cut_days(item, mode_, days)
    if cut is None:
        return None
    return _now() - cut * 86400, UNDO_FLOOR


def _where(part: Part, org: str, cut: float | None, since: float) -> tuple[str, list]:
    """The rows of `part` this organisation's sweep removes: older than `cut` (any age when None), not
    older than `since` (already swept) when the part blanks columns rather than deleting rows."""
    clauses, params = [], []
    if cut is not None:
        if not part.when:
            return "FALSE", []
        if part.kind == "ts":
            clauses.append(f"{part.when} < to_timestamp(%s)")
            params.append(cut)
            if part.blank and since:
                clauses.append(f"{part.when} >= to_timestamp(%s)")
                params.append(since)
        else:
            clauses.append(f"{part.when} < %s")
            params.append(cut)
            if part.blank and since:
                clauses.append(f"{part.when} >= %s")
                params.append(since)
    elif not part.floor:
        return "FALSE", []
    if part.scope == "org":
        if org == _install_org():
            clauses.append(f"({part.org_col} = %s OR {part.org_col} = '')")
        else:
            clauses.append(f"{part.org_col} = %s")
        params.append(org)
    elif part.scope == "dataset":
        clauses.append("dataset_id IN (SELECT id FROM synapse.dataset WHERE org_id = %s)")
        params.append(org)
    elif part.scope == "file":
        clauses.append("file_id IN (SELECT id FROM file WHERE org_id = %s" +
                       (" OR org_id = ''" if org == _install_org() else "") + ")")
        params.append(org)
    elif part.scope == "install" and org != _install_org():
        return "FALSE", []
    if part.extra:
        clauses.append(part.extra)
    if part.full:
        clauses.append(part.full)
    return " AND ".join(clauses) or "TRUE", params


def _floored(part: Part, where: str, newest: int = UNDO_FLOOR) -> str:
    """The rows of `where` that are past the newest `newest` of each group (Undo's floor at least), as
    a sub-select of their keys."""
    group, order = part.floor
    newest = max(UNDO_FLOOR, int(newest))
    return (f"SELECT {part.pk} FROM (SELECT *, row_number() OVER (PARTITION BY {group} ORDER BY {order} DESC) "
            f"AS lean_rank FROM {part.table}) v WHERE lean_rank > {newest} AND {where}")


def _picked(part: Part, where: str, newest: int) -> str:
    return _floored(part, where, newest) if part.floor else f"SELECT {part.pk} FROM {part.table} WHERE {where}"


def _count(part: Part, where: str, params: list, newest: int = UNDO_FLOOR) -> tuple[int, bool]:
    """How many rows, and whether that is exact (a count that takes too long is the planner's estimate)."""
    inner = _picked(part, where, newest)
    try:
        from django.db import transaction

        with transaction.atomic():
            got = _sql(f"SELECT count(*) FROM ({inner}) c", params, timeout_ms=8000)
        return int(got[0][0] or 0), True
    except Exception:  # noqa: BLE001 - too slow on a big table: the planner's estimate
        try:
            got = _sql(f"EXPLAIN (FORMAT JSON) {inner}", params)
            plan = got[0][0]
            plan = plan[0] if isinstance(plan, list) else plan
            if isinstance(plan, str):
                import json

                plan = json.loads(plan)[0]
            return int(plan["Plan"].get("Plan Rows") or 0), False
        except Exception:  # noqa: BLE001
            log.exception("lean: could not count %s", part.table)
            return 0, False


# --- outside the database: the nightly copies and the run logs ---------------------------------------

def copies_here() -> list[dict] | None:
    """The nightly copies there are, oldest first, with their bytes; None when this Rouh has none of
    its own here (no backups volume: a server's own backups are the server's)."""
    from . import offsite

    root = offsite.backup_dir()
    if not root:
        return None
    daily = os.path.join(root, "daily")
    try:
        names = sorted(n for n in os.listdir(daily) if offsite.NIGHTLY.fullmatch(n))
    except OSError:
        return []
    out = []
    for n in names:
        try:
            out.append({"name": n, "bytes": os.path.getsize(os.path.join(daily, n))})
        except OSError:
            continue
    return out


#: How long an answer of the one program about its run logs is kept, in seconds.
ONE_FRESH = 60.0


def _one_logs(days: float, *, dry: bool) -> dict | None:
    """The one program's answer about the logs of runs ended more than `days` ago (`one/runs.py`
    `trim_logs`), or None when it does not answer. A count is kept a minute; a removal never is."""
    key = ("one_logs", float(days))
    if dry:
        now = time.monotonic()
        with _lock:
            got = _seen.get(key)
            if got is not None and now - got[0] < ONE_FRESH:
                return got[1]
    import asyncio

    from .one_client import OneClient

    async def ask():
        return await OneClient(timeout=120).ask("run_logs", days=float(days), dry=bool(dry))

    try:
        got = asyncio.run(ask())
    except Exception as exc:  # noqa: BLE001 - not there, not paired, or it said no: cannot be counted
        log.info("lean: the one program did not answer about its run logs: %s", exc)
        return None
    if not dry:
        with _lock:
            for k in [k for k in _seen if k[0] == "one_logs"]:
                _seen.pop(k, None)
    else:
        with _lock:
            _seen[key] = (time.monotonic(), got)
    return got


def _preview_outside(item: Item, mode_: str, days: int | None) -> dict:
    if item.outside == "copies":
        have = copies_here()
        if have is None:
            return {"rows": 0, "bytes": 0, "exact": True, "cut_days": None,
                    "said": "This Rouh keeps no nightly copies of its own here, so nothing would go."}
        keep = max(1, int(days or 1))
        gone = have[:-keep] if len(have) > keep else []
        n, b = len(gone), sum(g["bytes"] for g in gone)
        said = ("Nothing would go." if not n else
                f"The oldest {n} of the {len(have)} nightly copies, about {said_bytes(b)}, would go at the next night's copy.")
        return {"rows": n, "bytes": b, "exact": True, "said": said, "cut_days": float(keep)}
    cut = cut_days(item, mode_, days)
    if cut is None:
        return {"rows": 0, "bytes": 0, "exact": True, "said": "Nothing would go.", "cut_days": None}
    got = _one_logs(cut, dry=True)
    if got is None:
        return {"rows": 0, "bytes": 0, "exact": False, "unknown": True, "cut_days": cut,
                "said": "The one program did not answer, so what would go cannot be counted; nothing is removed."}
    n, b, jobs = int(got.get("files") or 0), int(got.get("bytes") or 0), int(got.get("runs") or 0)
    said = ("Nothing would go." if not n else
            f"{n:,} log {'file' if n == 1 else 'files'} of {jobs:,} {'job' if jobs == 1 else 'jobs'}, about {said_bytes(b)}, "
            f"of jobs that ended more than {said_days(cut)} ago would go.")
    return {"rows": n, "bytes": b, "exact": True, "said": said, "cut_days": cut}


def preview(item_id: str, mode_: str, days: int | None, org_id=None) -> dict:
    """What a value would remove that the confirmed limit keeps: rows (or copies, or log files), about
    how many bytes, and the words to say it. `unknown` when it cannot be counted now."""
    item = BY_ID[item_id]
    org = _org(org_id)
    applied = applied_value(item_id, org)
    nothing = {"rows": 0, "bytes": 0, "exact": True, "said": "Nothing would go.", "cut_days": None}
    if not _removes(item) or _bounds(item, mode_, days) is None and not item.copies:
        return nothing
    if _looser_or_same(item, mode_, days, applied["mode"], applied["days"]):
        return {**nothing, "said": "Nothing more would go.", "cut_days": cut_days(item, mode_, days)}
    if item.outside:
        return _preview_outside(item, mode_, days)
    cutoff, newest = _bounds(item, mode_, days)
    rows, nbytes, exact = 0, 0, True
    for part in item.parts:
        where, params = _where(part, org, cutoff, applied["done_before"])
        n, sure = _count(part, where, params, newest)
        exact = exact and sure
        rows += n
        total = _rows_estimate(part.table)
        if n and total <= n:
            total = _exact_rows(part.table)  # a table never analysed has no estimate yet
        size = _size(part.table)
        if n and size:
            nbytes += int(size * min(1.0, n / max(total, n)))
    cut = cut_days(item, mode_, days)
    if rows == 0:
        said = "Nothing would go."
    else:
        which = (f"beyond the newest {newest} of each" if mode_ == "versions" else f"everything older than {said_days(cut)}"
                 + (f" beyond the newest {UNDO_FLOOR} of each" if all(p.floor for p in item.parts) else ""))
        said = (f"{'About ' if not exact else ''}{rows:,} {'row' if rows == 1 else 'rows'}, about {said_bytes(nbytes)}, "
                f"{which}" + (" (blanked, the rows kept)" if all(p.blank for p in item.parts) else "") + " would go.")
    return {"rows": rows, "bytes": nbytes, "exact": exact, "said": said, "cut_days": cut}


def said_bytes(n: float) -> str:
    n = float(n or 0)
    if n >= 1e9:
        return f"{n / 1e9:.1f} GB"
    if n >= 1e6:
        return f"{n / 1e6:.0f} MB"
    if n >= 1e3:
        return f"{n / 1e3:.0f} KB"
    return f"{int(n)} bytes"


def said_days(d: float) -> str:
    d = int(round(d))
    return "1 day" if d == 1 else f"{d} days"


# --- the confirmed limit -----------------------------------------------------------------------------

def applied_value(item_id: str, org_id=None) -> dict:
    """The limit the sweep deletes beyond; forever (nothing deleted) when none was ever confirmed. For
    the nightly copies, forever means the copy part keeps its own number (ROUH_BACKUP_KEEP)."""
    org = _org(org_id)
    row = _m().LeanApplied.objects.filter(org_id=org, item=item_id).first()
    if row is None:
        return {"mode": "forever", "days": None, "done_before": 0.0, "by": "", "at": 0}
    return {"mode": row.mode, "days": row.days, "done_before": float(row.done_before or 0), "by": row.by,
            "at": row.updated_at}


def _apply(item_id: str, org: str, mode_: str, days: int | None, by: str) -> None:
    """The confirmed limit set. Raising it forgets how far the sweep had got, so that whatever is kept
    meanwhile, however old it says it is, is counted again before any later lowering removes it."""
    M = _m()
    row = M.LeanApplied.objects.filter(org_id=org, item=item_id).first()
    if row is None:
        M.LeanApplied.objects.create(org_id=org, item=item_id, mode=mode_, days=days, by=by[:120],
                                     updated_at=_now())
        return
    item = BY_ID[item_id]
    raised = ((mode_, days) != (row.mode, row.days)
              and _looser_or_same(item, mode_, days, row.mode, row.days))
    fields = {"mode": mode_, "days": days, "by": by[:120], "updated_at": _now()}
    if raised:
        fields["done_before"] = 0
    M.LeanApplied.objects.filter(org_id=org, item=item_id).update(**fields)


def _instead(item: Item, now: dict) -> dict:
    """What the page offers in place of removing: as many copies as there are, or keep forever."""
    if item.copies:
        n = max(int(now["days"] or 1), len(copies_here() or []))
        return {"mode": "keep", "days": n, "label": f"Keep {n} {'copy' if n == 1 else 'copies'} instead"}
    return {"mode": "forever", "days": None, "label": "Keep forever instead"}


def waiting(item_id: str, org_id=None, *, look: bool = True) -> dict | None:
    """A lowering that waits for the owner's press: the value now is stricter than the confirmed limit
    and would remove something. None when nothing waits, or when what would go cannot be counted now."""
    item = BY_ID[item_id]
    if not _removes(item):
        return None
    org = _org(org_id)
    now = choice(item_id, org)
    app = applied_value(item_id, org)
    if _looser_or_same(item, now["mode"], now["days"], app["mode"], app["days"]):
        return None
    if not look:
        return {"mode": now["mode"], "days": now["days"]}
    got = preview(item_id, now["mode"], now["days"], org)
    if got.get("unknown") or not got["rows"]:
        return None
    return {"mode": now["mode"], "days": now["days"], **got, "instead": _instead(item, now)}


def settle(org_id=None, by: str = "the sweep") -> dict:
    """Every record's confirmed limit brought to its value where that removes nothing more: a raise at
    once, a lowering that would remove nothing (a fresh install). A lowering that would remove
    something, or whose removal cannot be counted now, waits."""
    org = _org(org_id)
    if preset(org) is None:
        return {"waiting": [], "moved": []}
    moved, held = [], []
    for item in ITEMS:
        if not _removes(item):
            continue
        now = choice(item.id, org)
        app = applied_value(item.id, org)
        if (now["mode"], now["days"]) == (app["mode"], app["days"]):
            continue
        if _looser_or_same(item, now["mode"], now["days"], app["mode"], app["days"]):
            _apply(item.id, org, now["mode"], now["days"], by)
            moved.append(item.id)
            continue
        got = preview(item.id, now["mode"], now["days"], org)
        if got["rows"] == 0 and not got.get("unknown"):
            _apply(item.id, org, now["mode"], now["days"], by + ", nothing to remove")
            moved.append(item.id)
        else:
            held.append(item.id)
    return {"waiting": held, "moved": moved}


# --- changing it -------------------------------------------------------------------------------------

def _clean_value(item: Item, mode_: str, days) -> tuple[str, int | None]:
    mode_ = str(mode_ or "").strip().lower()
    if mode_ == "on" and item.kind == "record":
        mode_ = "forever"
    if mode_ == "off" and item.versions:
        raise Refused(f"{item.name} cannot be off: Undo reads them. Keep the newest {UNDO_FLOOR} of each instead.")
    if mode_ not in item.modes:
        raise Refused(f"{item.name} cannot be {MODE_SAID.get(mode_, mode_)!r} here.")
    if mode_ not in ("keep", "versions"):
        return mode_, None
    try:
        n = int(days)
    except (TypeError, ValueError):
        raise Refused("Say how many " + ("copies" if item.copies else "versions" if mode_ == "versions" else "days")
                      + " to keep.") from None
    if item.copies:
        if n < 1:
            raise Refused("At least one nightly copy is always kept: without one a lost database cannot be brought back.")
        return mode_, min(n, 30)
    if mode_ == "versions":
        if n < UNDO_FLOOR:
            raise Refused(f"At least the newest {UNDO_FLOOR} versions of each are always kept, so Undo always works.")
        return mode_, min(n, 10000)
    if n < 1 or n > 3650:
        raise Refused("Keep between 1 and 3,650 days, or choose Keep forever.")
    return mode_, n


def set_choice(item_id: str, mode_: str, days=None, *, by: str, org_id=None, confirm: bool = False) -> dict:
    """The owner's own value for one item. A value that would remove old rows is not saved until it is
    confirmed: the answer then says what would go (`needs_confirm`). A raise, keep forever or on is
    saved and applied at once. A lowering whose removal cannot be counted now (the one program did not
    answer) is saved and waits, removing nothing, until it can be counted and the owner presses."""
    if item_id not in BY_ID:
        raise Refused("There is no such item.")
    item = BY_ID[item_id]
    org = _org(org_id)
    if preset(org) is None:
        raise Refused("Rouh cannot tell yet which kind of Rouh this is, so nothing can be changed. Try again in a minute.")
    mode_, days = _clean_value(item, mode_, days)
    held = ""
    if _removes(item):
        would = preview(item_id, mode_, days, org)
        if would["rows"] and not confirm:
            return {"needs_confirm": True, "item": item_id, "mode": mode_, "days": days, "preview": would}
        if would.get("unknown"):
            held = would["said"]
    _write_choice(item, org, mode_, days, by)
    if _removes(item) and not held:
        _apply(item_id, org, mode_, days, by + (", confirmed on the page" if confirm else ""))
    out = {"saved": True, "item": item_id, "mode": mode_, "days": days, "swept": bool(confirm) and not held}
    if held:
        out["held"] = held
    return out


def _write_choice(item: Item, org: str, mode_: str, days: int | None, by: str) -> None:
    M = _m()
    base = preset_value(item.id, preset(org))
    if (mode_, days) == base:
        M.LeanChoice.objects.filter(org_id=org, item=item.id).delete()
    else:
        row = M.LeanChoice.objects.filter(org_id=org, item=item.id)
        if row.exists():
            row.update(mode=mode_, days=days, by=by[:120], updated_at=_now())
        else:
            M.LeanChoice.objects.create(org_id=org, item=item.id, mode=mode_, days=days, by=by[:120],
                                        updated_at=_now())
    forget()


def back_to_default(item_id: str, *, by: str, org_id=None, confirm: bool = False) -> dict:
    """The owner's own value taken away: the item follows its preset again (with the same confirm)."""
    org = _org(org_id)
    mode_, days = preset_value(item_id, preset(org))
    return set_choice(item_id, mode_, days, by=by, org_id=org, confirm=confirm)


def confirm_waiting(item_id: str, *, by: str, org_id=None) -> dict:
    """The owner pressed to remove what a lowered value (an update's or the preset's) removes."""
    org = _org(org_id)
    now = choice(item_id, org)
    _apply(item_id, org, now["mode"], now["days"], by + ", confirmed on the page")
    return {"saved": True, "item": item_id, "swept": True}


def set_preset(name: str, *, by: str, org_id=None, confirm: bool = False) -> dict:
    """Another preset. The owner's own choices stay theirs. Records the new preset keeps for less
    are listed first, with what would go, and wait for the press like a single row. One whose removal
    cannot be counted now waits on its own, with nothing removed."""
    name = str(name or "").strip().lower()
    if name not in PRESET_NAMES:
        raise Refused("There is no such preset.")
    org = _org(org_id)
    old = preset(org)
    if old is None:
        raise Refused("Rouh cannot tell yet which kind of Rouh this is, so nothing can be changed. Try again in a minute.")
    M = _m()
    mine = set(M.LeanChoice.objects.filter(org_id=org).values_list("item", flat=True))
    would, counted = [], {}
    for item in ITEMS:
        if not _removes(item) or item.id in mine:
            continue
        mode_, days = preset_value(item.id, name)
        got = preview(item.id, mode_, days, org)
        counted[item.id] = got
        if got["rows"]:
            would.append({"item": item.id, "name": item.name, **got})
    if would and not confirm:
        return {"needs_confirm": True, "preset": name, "would": would}
    M.LeanState.objects.filter(org_id=org).update(preset=name, changed_by=by[:120], updated_at=_now())
    forget()
    for item in ITEMS:
        if _removes(item) and item.id not in mine:
            mode_, days = preset_value(item.id, name)
            got = counted.get(item.id) or preview(item.id, mode_, days, org)
            if got.get("unknown"):
                continue
            if confirm or not got["rows"]:
                _apply(item.id, org, mode_, days, by + (", confirmed on the page" if confirm else ""))
    return {"saved": True, "preset": name, "swept": bool(would)}


# --- the sweep -----------------------------------------------------------------------------------------

def _unlink_kept(paths) -> None:
    """The copies on disk of removed file versions, only inside the file store's version folder."""
    from . import filestore

    try:
        inside = os.path.realpath(os.path.join(filestore.root(), filestore.VERSIONS)) + os.sep
    except Exception:  # noqa: BLE001 - no file store here: nothing of it to remove
        return
    for p in paths:
        if not p:
            continue
        real = os.path.realpath(p)
        if not real.startswith(inside):
            log.warning("lean: a removed file version named %s, outside the version folder; left alone", p)
            continue
        try:
            os.unlink(real)
        except FileNotFoundError:
            pass
        except OSError:
            log.exception("lean: the kept copy %s could not be removed", p)


def _sweep_part(part: Part, org: str, cutoff: float | None, since: float, stop_at: float,
                newest: int = UNDO_FLOOR) -> int:
    """One part's old rows removed (or blanked), a batch at a time. The rows touched."""
    where, params = _where(part, org, cutoff, since)
    if where == "FALSE":
        return 0
    touched = 0
    if part.blank:
        last = None
        while _now() < stop_at:
            more = f" AND {part.pk} > %s" if last is not None else ""
            got = _sql(f"SELECT {part.pk} FROM {part.table} WHERE {where}{more} ORDER BY {part.pk} LIMIT {BATCH}",
                       params + ([last] if last is not None else []))
            keys = [r[0] for r in got]
            if not keys:
                break
            _sql(f"UPDATE {part.table} SET {part.blank} WHERE {part.pk} = ANY(%s)", (keys,))
            touched += len(keys)
            last = keys[-1]
            time.sleep(0.05)
        return touched
    pick = _picked(part, where, newest)
    back = part.unlink or "1"
    while _now() < stop_at:
        got = _sql(f"WITH gone AS (DELETE FROM {part.table} WHERE ({part.pk}) IN ({pick} LIMIT {BATCH}) "
                   f"RETURNING {back} AS back) SELECT back FROM gone", params)
        n = len(got)
        if part.unlink:
            _unlink_kept(r[0] for r in got)
        touched += n
        if n < BATCH:
            break
        time.sleep(0.05)
    return touched


def _orphan_pieces(stop_at: float) -> int:
    """Pieces of model calls no row names any more (their rows' words were removed)."""
    touched = 0
    _sql("CREATE TEMP TABLE IF NOT EXISTS lean_keep_pieces (h text PRIMARY KEY)")
    try:
        _sql("TRUNCATE lean_keep_pieces")
        _sql("INSERT INTO lean_keep_pieces SELECT DISTINCT h FROM ("
             "SELECT system_piece AS h FROM llm_requests WHERE system_piece <> '' UNION ALL "
             "SELECT tools_piece FROM llm_requests WHERE tools_piece <> '' UNION ALL "
             "SELECT jsonb_array_elements_text(message_pieces) FROM llm_requests "
             "WHERE jsonb_typeof(message_pieces) = 'array') k ON CONFLICT DO NOTHING")
        while _now() < stop_at:
            got = _sql("WITH gone AS (DELETE FROM llm_pieces WHERE hash IN (SELECT p.hash FROM llm_pieces p "
                       "WHERE NOT EXISTS (SELECT 1 FROM lean_keep_pieces k WHERE k.h = p.hash) "
                       f"AND p.created_at < %s LIMIT {BATCH}) RETURNING 1) SELECT count(*) FROM gone",
                       (_now() - 3600,))
            n = int(got[0][0] or 0) if got else 0
            touched += n
            if n < BATCH:
                break
            time.sleep(0.05)
    finally:
        _sql("DROP TABLE IF EXISTS lean_keep_pieces")
    return touched


def sweep_item(item_id: str, org_id=None, *, budget: float = 1800.0) -> dict:
    """One record's rows removed beyond its confirmed limit. Never beyond it, never raises. The nightly
    copies are the protected core's copy part's to remove, at its next copy; the run logs are the one
    program's, asked here."""
    item = BY_ID[item_id]
    org = _org(org_id)
    app = applied_value(item_id, org)
    if not _removes(item) or item.copies:
        return {"item": item_id, "touched": 0}
    if item.outside == "run_logs":
        cut = cut_days(item, app["mode"], app["days"])
        if cut is None or org != _install_org():
            return {"item": item_id, "touched": 0}
        got = _one_logs(cut, dry=False)
        touched = int((got or {}).get("files") or 0)
        if touched:
            log.info("lean: %s removed %s run log files of jobs ended more than %s ago", org, touched, said_days(cut))
        return {"item": item_id, "touched": touched}
    bounds = _bounds(item, app["mode"], app["days"])
    if bounds is None:
        return {"item": item_id, "touched": 0}
    cutoff, newest = bounds
    stop_at = _now() + budget
    touched = 0
    try:
        for part in item.parts:
            touched += _sweep_part(part, org, cutoff, app["done_before"], stop_at, newest)
        if item_id == "model_words" and touched:
            touched += _orphan_pieces(stop_at)
        if _now() < stop_at and cutoff is not None and any(p.blank for p in item.parts):
            # A day's margin, so a row still running at this sweep is looked at again by the next.
            _m().LeanApplied.objects.filter(org_id=org, item=item_id).update(done_before=cutoff - 86400)
    except Exception:  # noqa: BLE001 - tried again on the next sweep
        log.exception("lean: the sweep of %s failed", item_id)
    if touched:
        log.info("lean: %s removed %s old rows of %s (%s)", org, touched, item_id,
                 _value_said(item, app["mode"], app["days"]))
    return {"item": item_id, "touched": touched}


def sweep(org_id=None, *, force: bool = False) -> dict:
    """The daily sweep: limits settled, then every record's rows beyond its confirmed limit removed.
    Runs at most once in SWEEP_EVERY unless forced."""
    org = _org(org_id)
    M = _m()
    if preset(org) is None:
        return {"skipped": "the preset cannot be told yet"}
    state = M.LeanState.objects.filter(org_id=org).first()
    if state is None:
        return {"skipped": "no preset"}
    if not force and _now() - float(state.swept_at or 0) < SWEEP_EVERY:
        return {"skipped": "swept already"}
    M.LeanState.objects.filter(org_id=org).update(swept_at=_now())
    settled = settle(org)
    done = [sweep_item(i.id, org) for i in ITEMS if _removes(i)]
    return {"settled": settled, "swept": [d for d in done if d["touched"]]}


def orgs() -> list[str]:
    """Every organisation with a preset row, and the install's own."""
    out = {_install_org()}
    out.update(_m().LeanState.objects.values_list("org_id", flat=True))
    return sorted(out)


# --- the page ------------------------------------------------------------------------------------------

def _money(item: Item) -> str:
    return item.money


def _option_list(item: Item, value: dict, base: tuple[str, int | None]) -> list[dict]:
    out = []
    if item.kind == "job":
        for m in item.modes:
            out.append({"mode": m, "days": None, "label": MODE_SAID[m]})
        return out
    if item.copies:
        counts = sorted(set(COPIES) | {base[1] or 3} | ({value["days"]} if value["days"] else set()))
        return [{"mode": "keep", "days": n, "label": f"Keep {n} {'copy' if n == 1 else 'copies'}"} for n in counts]
    if "off" in item.modes:
        out.append({"mode": "off", "days": None, "label": "Off"})
    if "keep" in item.modes:
        days = set(DAYS)
        if base[0] == "keep" and base[1]:
            days.add(base[1])
        if value["mode"] == "keep" and value["days"]:
            days.add(value["days"])
        for d in sorted(days):
            out.append({"mode": "keep", "days": d, "label": f"Keep {said_days(d)}"})
    if "versions" in item.modes:
        counts = set(VERSIONS)
        for m, n in ((base[0], base[1]), (value["mode"], value["days"])):
            if m == "versions" and n:
                counts.add(n)
        for n in sorted(counts):
            out.append({"mode": "versions", "days": n, "label": f"Keep the newest {n}"})
    out.append({"mode": "forever", "days": None, "label": "Keep forever"})
    return out


def _exact_rows(table: str) -> int:
    """A table's rows counted, for the small version tables; the planner's estimate when that is slow."""
    try:
        from django.db import transaction

        with transaction.atomic():
            got = _sql(f"SELECT count(*) FROM {table}", timeout_ms=4000)
        return int(got[0][0] or 0)
    except Exception:  # noqa: BLE001
        return _rows_estimate(table)


def _kept_bytes(item: Item, org: str, mode_: str, days: int | None) -> int | None:
    """Roughly the bytes a version record would hold at this value, counted on this Rouh's own rows
    (they are small tables); None when it could not be counted."""
    key = ("kept", org, item.id, mode_, days)
    got = _cached(key)
    if got is not _MISS:
        return got
    total = 0
    try:
        bounds = _bounds(item, mode_, days)
        for part in item.parts:
            size = _size(part.table)
            if bounds is None or not size:
                total += size
                continue
            rows = _exact_rows(part.table)
            where, params = _where(part, org, bounds[0], 0)
            n, _ = _count(part, where, params, bounds[1])
            total += int(size * max(0.0, 1 - n / max(rows, n, 1)))
    except Exception:  # noqa: BLE001 - said as not measured
        log.exception("lean: could not size %s", item.id)
        total = None
    with _lock:
        _seen[key] = (time.monotonic() + 55, total)  # kept a minute: a page draws every option
    return total


def _disk_for(item: Item, mode_: str, days: int | None, org: str = "") -> str:
    """Roughly the disk a value holds: measured on this Rouh where it can be, else at the Creator
    Rouh's measured growth."""
    if item.copies:
        have = copies_here()
        if have is None:
            return ""
        one = (have[-1]["bytes"] if have else 0)
        if one:
            return f"about {said_bytes(one * (days or 0))}"
        return f"about {10.9 * (days or 0):.0f} GB, as on the Creator Rouh" if days else ""
    if item.outside == "run_logs":
        if mode_ == "off":
            return "about a day's worth"
        got = _one_logs(cut_days(item, mode_, days) or 36500, dry=True)
        if got is None:
            return "not measured"
        total = int(got.get("total_bytes") or 0)
        if mode_ == "forever":
            return f"about {said_bytes(total)} now, growing"
        return f"about {said_bytes(max(0, total - int(got.get('bytes') or 0)))}"
    if item.versions:
        got = _kept_bytes(item, org or _install_org(), mode_, days)
        if got is None:
            return "not measured"
        return f"about {said_bytes(got)}" + (", growing" if mode_ == "forever" else "")
    if item.rate is None:
        return "small" if item.id == "model_costs" else "not measured"
    if mode_ == "off":
        return "about a day's worth" if item.off_means else "nothing"
    if mode_ == "forever":
        return f"+{said_bytes(item.rate * 30e9)} a month"
    return f"about {said_bytes(item.rate * (days or 0) * 1e9)}"


def _size_of(item: Item, sizes: dict[str, int]) -> tuple[int | None, str, str]:
    """What a record holds now: (bytes counted in the page's total, the words to say it, or the words
    for a table it shares with a row above)."""
    if item.copies:
        have = copies_here()
        if not have:
            return None, "", ""
        b = sum(h["bytes"] for h in have)
        return None, f"{said_bytes(b)} in {len(have)} {'copy' if len(have) == 1 else 'copies'}", ""
    if item.outside == "run_logs":
        got = _one_logs(36500, dry=True)
        if got is None:
            return None, "", ""
        b = int(got.get("total_bytes") or 0)
        return b, said_bytes(b), ""
    tables = tuple(t for t in (item.sized or tuple(dict.fromkeys(p.table for p in item.parts))) if t != "-")
    if not tables:
        return None, "", ""
    size = 0
    for t in tables:
        if t not in sizes:
            sizes[t] = _size(t)
        size += sizes[t]
    # Two rows on one table (memory items and contacts) would count it twice: said, counted once.
    shared = [i for i in ITEMS if i is not item and i.kind == "record" and set(p.table for p in i.parts) == set(tables)]
    if shared and ITEMS.index(shared[0]) < ITEMS.index(item):
        return None, "", f"Shares its table, {said_bytes(size)} now, with {shared[0].name.lower()}"
    return size, said_bytes(size), ""


def page(org_id=None, *, look: bool = True) -> dict:
    """Everything Anatomy, Meta, What Rouh keeps and runs draws."""
    org = _org(org_id)
    name = preset(org)
    rows = []
    sizes: dict[str, int] = {}
    for item in ITEMS:
        value = choice(item.id, org)
        base = preset_value(item.id, name)
        size, size_said, shares = _size_of(item, sizes) if item.kind == "record" else (None, "", "")
        options = []
        for o in _option_list(item, value, base):
            o = dict(o)
            if item.kind == "record":
                o["disk"] = _disk_for(item, o["mode"], o["days"], org)
            o["chosen"] = (o["mode"], o["days"]) == (value["mode"], value["days"])
            o["preset"] = (o["mode"], o["days"]) == base
            options.append(o)
        wait = waiting(item.id, org, look=look) if (name is not None and look) else None
        rows.append({
            "id": item.id, "kind": item.kind, "name": item.name, "what": item.what, "wave": item.wave,
            "mode": value["mode"], "days": value["days"], "from": value["from"], "by": value["by"],
            "changed": value["from"] == "yours", "preset_mode": base[0], "preset_days": base[1],
            "said": _value_said(item, value["mode"], value["days"]),
            "preset_said": _value_said(item, base[0], base[1]),
            "money": _money(item) if item.kind == "job" else "", "size_bytes": size,
            "size_said": size_said, "off_means": item.off_means, "not_yet": item.not_yet,
            "note": item.note, "copies": item.copies, "versions": item.versions,
            "link": item.link, "link_said": item.link_said,
            "shares": "Shares the model calls' table with the row above" if item.id == "model_costs" else shares,
            "options": options, "runs": runs(item.id, org)
            if item.kind == "job" else None, "waiting": wait,
        })
    state = _m().LeanState.objects.filter(org_id=org).first()
    return {"preset": name, "preset_said": PRESET_SAID.get(name or "", "Not set yet"),
            "presets": [{"id": p, "name": PRESET_SAID[p], "about": PRESET_ABOUT[p]} for p in PRESET_NAMES],
            "changed": sum(1 for r in rows if r["changed"]),
            "waiting": sum(1 for r in rows if r["waiting"]),
            "swept_at": float(state.swept_at or 0) if state else 0,
            "items": rows}


def _value_said(item: Item, mode_: str, days: int | None) -> str:
    if mode_ == "keep":
        if item.copies:
            return f"Keep {days} {'copy' if days == 1 else 'copies'}"
        return f"Keep {said_days(days or 0)}"
    if mode_ == "versions":
        return f"Keep the newest {days} of each"
    return MODE_SAID.get(mode_, mode_)
