"""What this Rouh keeps and runs: the one place a job asks whether it runs and a record whether it
is kept, and for how long (task 185, Lean Rouh).

Petar, 15 November 2026: "I think those options should have the defaults you have assigned. and I
think those should be available to change through your own instance settings. so we provide
default behavior. anyone can go in anatomy and change them to something else. days should include
a keep forever behavior."

**The items.** `ITEMS` is every job and step only the Creator Rouh or a developer needs, and every
record Rouh used to keep forever (step 185-01), each with its modes. A job is off, on, or one of
its own modes (only in the Synapse lab by hand, follows the nightly feature run, ...). A record is
off, kept for a number of days, or kept forever; the nightly database copies are counted in copies.

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
newest versions of every memory item and Ask AI page are always kept, whatever the limit, so Undo
always has what it needs.
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
    "installed": "Every new install: the creator's night jobs and test tools off, records kept for a while.",
    "developer": "Someone who builds Rouh: test tools on, the paid night runs off, records kept longer.",
    "creator": "The Rouh that makes Rouh's releases: everything on and every record kept.",
}
#: The days a kept record offers, besides its preset's own value.
DAYS = (7, 14, 30, 90)
#: The copies the nightly database copies offer; never fewer than one (the floor).
COPIES = (1, 2, 3, 5, 7)
#: The newest versions of each memory item and Ask AI page always kept, whatever the limit (Undo's floor).
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
}


@dataclasses.dataclass(frozen=True)
class Part:
    """One table a record's sweep works on."""
    table: str
    pk: str
    when: str
    #: "epoch" (seconds since 1970) or "ts" (timestamptz).
    kind: str = "epoch"
    #: "org" (an org_id column), "dataset" (a Synapse dataset_id) or "all".
    scope: str = "org"
    #: More of the WHERE clause, already safe SQL.
    extra: str = ""
    #: Columns set to blank instead of deleting the row; empty means delete.
    blank: str = ""
    #: The newest N of each group kept whatever their age (Undo's floor): (group by, order by).
    floor: tuple[str, str] | None = None
    #: For a part that blanks: the rows that still hold something, so a row already blank is never counted.
    full: str = ""


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


_OLD_ROWS = "status <> 'running'"

ITEMS: tuple[Item, ...] = (
    # ---- night and background jobs ----
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
         ("keep",), copies=True,
         not_yet="Not yet in force: the copy part of the protected core keeps its own number, "
                 "ROUH_BACKUP_KEEP in the machine's settings file. Rouh keeps this choice for when it reads it."),
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
    Item("old_versions", "record", "Old versions of memory items and Ask AI pages",
         f"Earlier versions. The newest {UNDO_FLOOR} of each are always kept, so Undo always works.",
         ("off", "keep", "forever"), wave=2, rate=0.0087,
         off_means=f"Off keeps the newest {UNDO_FLOOR} of each, for Undo.",
         parts=(Part("synapse.item_version", "id", "made_at", kind="ts", scope="dataset",
                     extra="(keep_until IS NULL OR keep_until < now())", floor=("dataset_id, item_id", "version")),
                Part("askai_edits", "id", "created_at", floor=("doc", "created_at")))),
    Item("run_logs", "record", "Run logs on disk",
         "The terminal log of each job and the update log.",
         ("off", "keep", "forever"), wave=2,
         not_yet="Not yet in force: the logs are the one program's files on disk, which this sweep does not reach yet."),
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

#: Each preset's values: Rouh's suggestions in step 185-02 (`choices.json`, its `suggested` fields), with
#: database copies at 3 on every preset. A record "on" there is "forever" here.
PRESETS: dict[str, dict[str, tuple[str, int | None]]] = {
    "installed": {
        "synapse_nightly": ("off", None), "synapse_tests": ("off", None), "memory_judge": ("off", None),
        "nightly_refactor": ("off", None), "nightly_feature": ("off", None), "gene_log": ("list", None),
        "trial_stage": ("off", None), "tester_problems": ("off", None), "gap_tracker": ("off", None),
        "dreaming": ("later", None), "mutations": ("follow", None),
        "model_words": ("keep", 7), "synapse_working": ("keep", 1), "synapse_steps": ("keep", 14),
        "nightly_copies": ("keep", 3), "turn_records": ("keep", 30), "model_outcome": ("keep", 90),
        "usage_events": ("keep", 90), "synapse_jobs": ("keep", 30), "audit_trails": ("keep", 90),
        "old_versions": ("keep", 90), "run_logs": ("keep", 30), "model_costs": ("keep", 400),
    },
    "developer": {
        "synapse_nightly": ("off", None), "synapse_tests": ("lab", None), "memory_judge": ("lab", None),
        "nightly_refactor": ("off", None), "nightly_feature": ("off", None), "gene_log": ("on", None),
        "trial_stage": ("on", None), "tester_problems": ("on", None), "gap_tracker": ("off", None),
        "dreaming": ("later", None), "mutations": ("follow", None),
        "model_words": ("keep", 30), "synapse_working": ("keep", 7), "synapse_steps": ("keep", 30),
        "nightly_copies": ("keep", 3), "turn_records": ("keep", 90), "model_outcome": ("keep", 90),
        "usage_events": ("keep", 90), "synapse_jobs": ("keep", 30), "audit_trails": ("keep", 90),
        "old_versions": ("keep", 90), "run_logs": ("keep", 30), "model_costs": ("keep", 400),
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


def cut_days(item: Item, mode_: str, days: int | None) -> float | None:
    """The age in days beyond which a record's rows go, or None for never."""
    if item.copies or not item.parts:
        return None
    span = _span(mode_, days)
    if span == float("inf"):
        return None
    if mode_ == "off":
        return 1.0
    return max(1.0, span)


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


def _where(part: Part, org: str, cut: float, since: float) -> tuple[str, list]:
    """The rows of `part` this organisation's sweep removes: older than `cut`, not older than `since`
    (already swept) when the part blanks columns rather than deleting rows."""
    clauses, params = [], []
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
    if part.scope == "org":
        if org == _install_org():
            clauses.append("(org_id = %s OR org_id = '')")
        else:
            clauses.append("org_id = %s")
        params.append(org)
    elif part.scope == "dataset":
        clauses.append("dataset_id IN (SELECT id FROM synapse.dataset WHERE org_id = %s)")
        params.append(org)
    if part.extra:
        clauses.append(part.extra)
    if part.full:
        clauses.append(part.full)
    return " AND ".join(clauses), params


def _floored(part: Part, where: str) -> str:
    """The rows of `where` that are past Undo's floor, as a sub-select of their keys."""
    group, order = part.floor
    return (f"SELECT {part.pk} FROM (SELECT *, row_number() OVER (PARTITION BY {group} ORDER BY {order} DESC) "
            f"AS lean_rank FROM {part.table}) v WHERE lean_rank > {UNDO_FLOOR} AND {where}")


def _count(part: Part, where: str, params: list) -> tuple[int, bool]:
    """How many rows, and whether that is exact (a count that takes too long is the planner's estimate)."""
    inner = _floored(part, where) if part.floor else f"SELECT 1 FROM {part.table} WHERE {where}"
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


def preview(item_id: str, mode_: str, days: int | None, org_id=None) -> dict:
    """What a value would remove that the confirmed limit keeps: rows, about how many bytes, and
    the words to say it."""
    item = BY_ID[item_id]
    org = _org(org_id)
    cut = cut_days(item, mode_, days)
    applied = applied_value(item_id, org)
    if cut is None or not item.parts:
        return {"rows": 0, "bytes": 0, "exact": True, "said": "Nothing would go.", "cut_days": None}
    old = cut_days(item, applied["mode"], applied["days"])
    if old is not None and old <= cut:
        return {"rows": 0, "bytes": 0, "exact": True, "said": "Nothing more would go.", "cut_days": cut}
    cutoff = _now() - cut * 86400
    rows, nbytes, exact = 0, 0, True
    for part in item.parts:
        where, params = _where(part, org, cutoff, applied["done_before"])
        n, sure = _count(part, where, params)
        exact = exact and sure
        rows += n
        total = _rows_estimate(part.table)
        size = _size(part.table)
        if n and size:
            nbytes += int(size * min(1.0, n / max(total, n)))
    said = ("Nothing would go." if rows == 0 else
            f"{'About ' if not exact else ''}{rows:,} {'row' if rows == 1 else 'rows'}, about {said_bytes(nbytes)}, "
            f"everything older than {said_days(cut)}" + (" (blanked, the rows kept)" if all(p.blank for p in item.parts) else "")
            + " would go.")
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
    """The limit the sweep deletes beyond; forever (nothing deleted) when none was ever confirmed."""
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
    old, new = cut_days(item, row.mode, row.days), cut_days(item, mode_, days)
    raised = old is not None and (new is None or new > old)
    fields = {"mode": mode_, "days": days, "by": by[:120], "updated_at": _now()}
    if raised:
        fields["done_before"] = 0
    M.LeanApplied.objects.filter(org_id=org, item=item_id).update(**fields)


def waiting(item_id: str, org_id=None, *, look: bool = True) -> dict | None:
    """A lowering that waits for the owner's press: the value now is stricter than the confirmed limit
    and would remove something. None when nothing waits."""
    item = BY_ID[item_id]
    if item.kind != "record" or not item.parts:
        return None
    org = _org(org_id)
    now = choice(item_id, org)
    app = applied_value(item_id, org)
    new, old = cut_days(item, now["mode"], now["days"]), cut_days(item, app["mode"], app["days"])
    if new is None or (old is not None and old <= new):
        return None
    if not look:
        return {"mode": now["mode"], "days": now["days"]}
    got = preview(item_id, now["mode"], now["days"], org)
    return {"mode": now["mode"], "days": now["days"], **got} if got["rows"] else None


def settle(org_id=None, by: str = "the sweep") -> dict:
    """Every record's confirmed limit brought to its value where that removes nothing more: a raise at
    once, a lowering that would remove nothing (a fresh install). A lowering that would remove
    something waits for the owner's press."""
    org = _org(org_id)
    if preset(org) is None:
        return {"waiting": [], "moved": []}
    moved, held = [], []
    for item in ITEMS:
        if item.kind != "record" or not item.parts:
            continue
        now = choice(item.id, org)
        app = applied_value(item.id, org)
        new, old = cut_days(item, now["mode"], now["days"]), cut_days(item, app["mode"], app["days"])
        if (now["mode"], now["days"]) == (app["mode"], app["days"]):
            continue
        if new is None or (old is not None and new >= old):
            _apply(item.id, org, now["mode"], now["days"], by)
            moved.append(item.id)
            continue
        if preview(item.id, now["mode"], now["days"], org)["rows"] == 0:
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
    if mode_ not in item.modes:
        raise Refused(f"{item.name} cannot be {MODE_SAID.get(mode_, mode_)!r} here.")
    if mode_ != "keep":
        return mode_, None
    try:
        n = int(days)
    except (TypeError, ValueError):
        raise Refused("Say how many " + ("copies" if item.copies else "days") + " to keep.") from None
    if item.copies:
        if n < 1:
            raise Refused("At least one nightly copy is always kept: without one a lost database cannot be brought back.")
        return mode_, min(n, 30)
    if n < 1 or n > 3650:
        raise Refused("Keep between 1 and 3,650 days, or choose Keep forever.")
    return mode_, n


def set_choice(item_id: str, mode_: str, days=None, *, by: str, org_id=None, confirm: bool = False) -> dict:
    """The owner's own value for one item. A value that would remove old rows is not saved until it is
    confirmed: the answer then says what would go (`needs_confirm`). A raise, keep forever or on is
    saved and applied at once."""
    if item_id not in BY_ID:
        raise Refused("There is no such item.")
    item = BY_ID[item_id]
    org = _org(org_id)
    if preset(org) is None:
        raise Refused("Rouh cannot tell yet which kind of Rouh this is, so nothing can be changed. Try again in a minute.")
    mode_, days = _clean_value(item, mode_, days)
    if item.kind == "record" and item.parts:
        would = preview(item_id, mode_, days, org)
        if would["rows"] and not confirm:
            return {"needs_confirm": True, "item": item_id, "mode": mode_, "days": days, "preview": would}
    _write_choice(item, org, mode_, days, by)
    if item.kind == "record" and item.parts:
        _apply(item_id, org, mode_, days, by + (", confirmed on the page" if confirm else ""))
    return {"saved": True, "item": item_id, "mode": mode_, "days": days, "swept": bool(confirm)}


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
    are listed first, with what would go, and wait for the press like a single row."""
    name = str(name or "").strip().lower()
    if name not in PRESET_NAMES:
        raise Refused("There is no such preset.")
    org = _org(org_id)
    old = preset(org)
    if old is None:
        raise Refused("Rouh cannot tell yet which kind of Rouh this is, so nothing can be changed. Try again in a minute.")
    M = _m()
    mine = set(M.LeanChoice.objects.filter(org_id=org).values_list("item", flat=True))
    would = []
    for item in ITEMS:
        if item.kind != "record" or not item.parts or item.id in mine:
            continue
        mode_, days = preset_value(item.id, name)
        got = preview(item.id, mode_, days, org)
        if got["rows"]:
            would.append({"item": item.id, "name": item.name, **got})
    if would and not confirm:
        return {"needs_confirm": True, "preset": name, "would": would}
    M.LeanState.objects.filter(org_id=org).update(preset=name, changed_by=by[:120], updated_at=_now())
    forget()
    for item in ITEMS:
        if item.kind == "record" and item.parts and item.id not in mine:
            mode_, days = preset_value(item.id, name)
            if confirm or not preview(item.id, mode_, days, org)["rows"]:
                _apply(item.id, org, mode_, days, by + (", confirmed on the page" if confirm else ""))
    return {"saved": True, "preset": name, "swept": bool(would)}


# --- the sweep -----------------------------------------------------------------------------------------

def _sweep_part(part: Part, org: str, cutoff: float, since: float, stop_at: float) -> int:
    """One part's old rows removed (or blanked), a batch at a time. The rows touched."""
    where, params = _where(part, org, cutoff, since)
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
    pick = _floored(part, where) if part.floor else f"SELECT {part.pk} FROM {part.table} WHERE {where}"
    while _now() < stop_at:
        got = _sql(f"WITH gone AS (DELETE FROM {part.table} WHERE ({part.pk}) IN ({pick} LIMIT {BATCH}) RETURNING 1) "
                   "SELECT count(*) FROM gone", params)
        n = int(got[0][0] or 0) if got else 0
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
    """One record's rows removed beyond its confirmed limit. Never beyond it, never raises."""
    item = BY_ID[item_id]
    org = _org(org_id)
    app = applied_value(item_id, org)
    cut = cut_days(item, app["mode"], app["days"])
    if cut is None or not item.parts:
        return {"item": item_id, "touched": 0}
    cutoff = _now() - cut * 86400
    stop_at = _now() + budget
    touched = 0
    try:
        for part in item.parts:
            touched += _sweep_part(part, org, cutoff, app["done_before"], stop_at)
        if item_id == "model_words" and touched:
            touched += _orphan_pieces(stop_at)
        if _now() < stop_at and any(p.blank for p in item.parts):
            # A day's margin, so a row still running at this sweep is looked at again by the next.
            _m().LeanApplied.objects.filter(org_id=org, item=item_id).update(done_before=cutoff - 86400)
    except Exception:  # noqa: BLE001 - tried again on the next sweep
        log.exception("lean: the sweep of %s failed", item_id)
    if touched:
        log.info("lean: %s removed %s old rows of %s, older than %s", org, touched, item_id, said_days(cut))
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
    done = [sweep_item(i.id, org) for i in ITEMS if i.kind == "record" and i.parts]
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
    days = set(DAYS)
    if base[0] == "keep" and base[1]:
        days.add(base[1])
    if value["mode"] == "keep" and value["days"]:
        days.add(value["days"])
    for d in sorted(days):
        out.append({"mode": "keep", "days": d, "label": f"Keep {said_days(d)}"})
    out.append({"mode": "forever", "days": None, "label": "Keep forever"})
    return out


def _disk_for(item: Item, mode_: str, days: int | None) -> str:
    """Roughly the disk a value holds, at the Creator Rouh's measured growth."""
    if item.copies:
        return f"about {10.9 * (days or 0):.0f} GB" if days else ""
    if item.rate is None:
        return "small" if item.id == "model_costs" else "not measured"
    if mode_ == "off":
        return "about a day's worth" if item.off_means else "nothing"
    if mode_ == "forever":
        return f"+{said_bytes(item.rate * 30e9)} a month"
    return f"about {said_bytes(item.rate * (days or 0) * 1e9)}"


def page(org_id=None, *, look: bool = True) -> dict:
    """Everything Anatomy, Meta, What Rouh keeps and runs draws."""
    org = _org(org_id)
    name = preset(org)
    rows = []
    sizes: dict[str, int] = {}
    for item in ITEMS:
        value = choice(item.id, org)
        base = preset_value(item.id, name)
        tables = tuple(t for t in (item.sized or tuple(dict.fromkeys(p.table for p in item.parts))) if t != "-")
        size = 0
        for t in tables:
            if t not in sizes:
                sizes[t] = _size(t)
            size += sizes[t]
        options = []
        for o in _option_list(item, value, base):
            o = dict(o)
            if item.kind == "record":
                o["disk"] = _disk_for(item, o["mode"], o["days"])
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
            "money": _money(item) if item.kind == "job" else "", "size_bytes": size if tables else None,
            "size_said": said_bytes(size) if tables else "", "off_means": item.off_means, "not_yet": item.not_yet,
            "note": item.note, "copies": item.copies,
            "shares": "Shares the model calls' table with the row above" if item.id == "model_costs" else "", "options": options, "runs": runs(item.id, org)
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
    return MODE_SAID.get(mode_, mode_)
