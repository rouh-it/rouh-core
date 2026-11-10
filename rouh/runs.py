"""Every kind of running work, as one type: a row in `run`.

There were three notions of a running thing on this machine and they disagreed
with one another constantly, because each was kept somewhere else and read
somewhere else:

1. a **background worker** - `assistant_job`, `delegate_task`, `improve_myself`
   - which is a row of `crewmates` in `crew.py`, a tmux window and a worktree;
2. a **run of the one program** - `one_start`, `one_runs`, `one_say`,
   `one_stop`, `one_answer`, `one_take`, `one_give` - which is a run in that
   program's own list, on the other end of a socket;
3. a **sub-agent** inside either of those, which was not written down anywhere
   at all: it existed only as a node the work tree derived from a stream of
   hook events, so it was on the orb and on no list.

They are all the same thing - an agent doing something, once - and since this
module they are all one row in `objects.run`, told apart by two fields rather
than by being three separate models:

    workspace   where the work belongs: the checkout the job works in, or the
                space a run of the one program works in
    policy      under what rules it works: yolo, auto, safe, self, local-only,
                direct-pr, or "one" for the one program's own rules

and `state` is one of five words - running, waiting, done, failed, conflict -
with `question` set while it is waiting. A sub-agent is a run with
`parent_run_id` set, which is the only reason the orb can draw it as a branch
off its parent rather than as a spike of its own.

**The database is the source of truth.** The worktrees, the logs, the branches
and the tmux windows are a supportive structure written out from it, never read
back in as the truth. Where the two disagree the row wins, and what is on disk
is an inbound change to reconcile into the row rather than an override of it:
that is why reading a worker's screen writes what it found back here (`note`)
instead of being asked again by everybody who wants to know.

One register, read three ways
-----------------------------

`rows` answers the task list and `check_tasks`; `describe_one_runs` answers
`one_runs`; `tree` answers `what_is_running` and the orb. All three are the
same query, so they cannot disagree about what is running, which is the whole
point of this step. What each of them is allowed to ask somewhere else is
narrow and deliberate:

* **a worker's screen.** `check_tasks` still reads a running worker's terminal
  for the question it is asking, because a screen is not a fact of record.
  What it finds is written back here at once.
* **the tool calls inside a run.** A twig on the orb is a step within a run,
  not a run, and it comes from that run's own hooks (`tree.build_tree`). The
  shape of the tree - what is a spike, what is a branch, what hangs off what -
  comes from `parent_run_id` and nothing else.
* **whether a terminal has a run open.** That is a fact about a terminal, and
  the one program answers it live.

Everything here is behind `objects.enabled()`. There is no second
implementation behind that flag: the two lists the task list used to be
stitched together from went in step five, along with `one_client.one_task` and
the name-matching that guessed whether an id was the program's. Off means this
register does not answer, not that something else does.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping

from . import browser_handoff, objects

log = logging.getLogger("rouh.runs")

# ---------------------------------------------------------------------------
# The vocabularies, and the one they all become
# ---------------------------------------------------------------------------
#
# `state` is the five words the register keeps. `phase` beside it is the finer
# word the run's own machinery uses, which the task list has always shown and
# which the five have no room for: "starting", "queued", "killed", "lost". The
# two are written by the same statement, so a row can never say one thing in
# one column and something else in the other.

#: A crewmate's status (`crew.STATUSES`) as a run's state.
CREW_STATE = {
    "starting": "running",
    "running": "running",
    "waiting": "waiting",
    "done": "done",
    "failed": "failed",
    # Both of these are a run that will not be heard from again. `phase` is
    # what remembers which of the two it was.
    "lost": "failed",
    "killed": "failed",
}

#: A run of the one program's state (`one.views.STATES`) as a run's state.
ONE_STATE = {
    "queued": "running",
    "starting": "running",
    "working": "running",
    "saving": "running",
    "asking": "waiting",
    "idle": "done",
    "done": "done",
    "unfinished": "failed",
    "failed": "failed",
    "lost": "failed",
    "refused": "failed",
    # Stopped by the program at its time limit: over, and not a failure.
    # `phase` keeps the word, so the list never calls it done.
    "reaped": "done",
}

#: A run of the one program's state in the task list's own words. The one
#: table: `one_client` kept a second copy of it beside a `one_task` that built
#: a whole row to read one field off, and both went in step five when the task
#: list stopped being two lists added together.
#:
#: `idle` is its own word and is not `done`, which is what it said until
#: 22 September 2026. A run that has finished its turn is **open**: it is
#: sitting at its prompt with its terminal alive and its checkout in place,
#: waiting for the next thing to be said to it, and it stays that way until a
#: person closes it (D49). Six runs were in exactly that state on the morning
#: the list called every one of them Done, which is the word for a run that is
#: over. The two are different facts and the column has to be able to say
#: which.
ONE_WORD = {
    "queued": "starting", "starting": "starting", "working": "running",
    # Its Claude Code finished its turn and sits at its prompt while the program lands and
    # deploys its work: that is said, never "running" (Petar, 12 October 2026, D17).
    "saving": "saving", "asking": "waiting", "idle": "idle", "done": "done",
    "unfinished": "failed", "failed": "failed", "lost": "lost", "refused": "failed",
    "reaped": "reaped",
}

#: What the task list says when a row has no finer word to go on. A run stuck
#: on a merge conflict is waiting on a person, which is what the list and the
#: orb have always called it; `conflict` is the register being exact about why.
STATE_WORD = {"running": "running", "waiting": "waiting", "conflict": "waiting",
              "done": "done", "failed": "failed"}

#: How a run reads as a node of the work tree. The same mapping
#: `tree._WORKER_STATE` applies to a crewmate, moved here because the tree is
#: built from the register now and not from the rows it used to be built from.
#: `idle` is a finished node here and not a running one: a run at its prompt
#: is doing nothing, and the tree keeps a finished node only for a while
#: before it prunes it (`_node`). Left to fall through to the default it would
#: have been "running", and a run nobody ever closes would have sat on the orb
#: for ever saying it was working.
NODE_STATE = {"starting": "running", "running": "running", "saving": "running",
              "waiting": "waiting",
              "idle": "done", "done": "done", "failed": "failed", "lost": "lost",
              "killed": "lost", "reaped": "done"}

#: Who runs a run, from its policy. The same answer `tree._OWNER` gave.
OWNER = {"auto": "assistant", "self": "self", "one": "one"}

#: The policy of a run of the one program. Every tool call it makes is decided
#: by the program's own rules rather than by a Claude Code permission mode, so
#: this one word is the whole of it - and it is also how a row is known to be
#: the program's when it is read back.
ONE_POLICY = "one"

#: How long a finished run stays in the tree after it ended. The same
#: `tree.PRUNE_AFTER`: a finished node is sent at least once as finished so the
#: page can show it end, and the page fades it out from there.
PRUNE_AFTER = 2.0

#: How far back the tree looks. Nothing older than this is drawn even if it
#: never closed, which is `crew.tree_events`' own window.
WINDOW = 900.0

#: The most runs the register is asked for at once. The task list trims to
#: fourteen and the tree to what is open, so this is a ceiling on the read and
#: not on what anybody sees.
LIMIT = 300


#: The two halves of Metabolism, the page of runs (Petar, 14 October 2026: "use
#: metabolism. and within the runs page, split it in two types - mutations and
#: everyday work"). A mutation changes Rouh itself; everyday work is the rest.
MUTATION = "mutation"
EVERYDAY = "everyday"

#: The surface names whose runs change Rouh itself, or this server it runs on:
#: `improve_myself`, which the nightly feature run and every case fix start too,
#: and `delegate_task`, the job on this server. `assistant_job` and `one_start`
#: are the person's own work unless they were pointed at Rouh's code.
MUTATING_PRESETS = frozenset({"improve_myself", "delegate_task"})

#: The one program's spaces that are Rouh's own repository: `rouh`, and `jarvis`,
#: which it was called until 22 September 2026.
ROUH_SPACES = frozenset({"rouh", "jarvis"})

#: A path that is Rouh's own code: its deployment (`/var/www/rouh/app`, once
#: `/var/www/jarvis/app`) and the program's old space for it (`/srv/spaces/jarvis`).
#: `/srv/spaces/rouh` is not one of them, because the person's workspace is inside it.
_ROUH_PATH = re.compile(r"/(?:(?:rouh|jarvis)/app|spaces/jarvis)/?$")


def kind_of(*, preset: str = "", space: str = "", policy: str = "",
            workspace: str = "") -> str:
    """Which half of Metabolism a run is on, from what it carries when it starts.

    In this order: the tool that started it, the one program's space it is in,
    its policy, and the path it works in. The workspace alone cannot say it any
    more: since 22 September 2026 every run of the program works in Rouh's own
    checkout, because the person's workspace is `workspace/` inside it.
    """
    if preset in MUTATING_PRESETS:
        return MUTATION
    if preset == "assistant_job":
        return EVERYDAY
    if str(space or "").strip().lower() in ROUH_SPACES:
        return MUTATION
    if policy == "self":
        return MUTATION
    if _ROUH_PATH.search(str(workspace or "")):
        return MUTATION
    # A job of the crew with no preset to say: `auto` is the assistant's, and
    # every other mode of the crew's was a delegate_task (`starting.KIND_WORDS`).
    if policy and policy not in ("auto", ONE_POLICY):
        return MUTATION
    return EVERYDAY


def kind_of_row(row: objects.Run) -> str:
    """A run's half of Metabolism: what it was given, else what its row can say."""
    return row.kind or kind_of(policy=row.policy, workspace=row.workspace)


#: The runs already known to have a kind, so a feed that says the same run again
#: twice a second does not ask the database twice a second.
_kinded: set[str] = set()


def kind_if_unknown(run_id: str, kind: str) -> None:
    """Give a run its kind if nothing has yet: what a feed knows, under what its start said."""
    if not run_id or run_id in _kinded:
        return
    st = store()
    if st is None:
        return
    try:
        st.kind_if_unknown(run_id, kind)
    except Exception:
        log.exception("could not say which kind of run %s is", run_id)
        return
    row = st.get_run(run_id)
    if row is not None and row.kind:
        _kinded.add(run_id)


def kinds_from_program(run_list: Iterable[Mapping[str, Any]]) -> int:
    """Every run of the program the register has no kind for, from the space it was in.

    For the runs kept before runs had a kind (`0152_run_kind`): the program still
    knows each run's space. How many were written.
    """
    st = store()
    if st is None:
        return 0
    known = {r.id for r in st.list_runs(parent_run_id=None, limit=100000) if not r.kind}
    done = 0
    for run in run_list:
        rid = str(run.get("id") or "")
        if rid not in known:
            continue
        kind = MUTATION if str(run.get("space") or "").lower() in ROUH_SPACES else EVERYDAY
        try:
            if st.kind_if_unknown(rid, kind):
                done += 1
        except Exception:
            log.exception("could not say which kind of run %s is", rid)
    return done


def enabled() -> bool:
    """Whether the register answers. Off means every caller does what it did before."""
    return objects.enabled()


# ---------------------------------------------------------------------------
# The one store
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_seen: objects.ObjectStore | None = None

#: What was last written for each run, so a run that changes twice a second -
#: which a busy one does - is not written twice a second. The register is the
#: truth and this only skips a write that would change nothing.
_written: dict[str, tuple] = {}


def store() -> objects.ObjectStore | None:
    """The register, or None when it is off or the file will not open.

    The connection belongs to `objects.shared_store`: runs and artifacts are
    rows of the same five tables, and two connections to one file would be two
    locks that know nothing about each other. All this adds is the cache of
    what was last written, which has to be dropped when the store underneath
    it is a different one - a test world that moved the database, or a file
    that was closed and opened again.
    """
    global _seen
    st = objects.shared_store()
    with _lock:
        if st is not _seen:
            _written.clear()
            _seen = st
    return st


def close() -> None:
    """Let the file go, and forget what was written. Only a check of one's own needs this."""
    global _seen
    objects.close_shared()
    with _lock:
        _seen = None
        _written.clear()


# ---------------------------------------------------------------------------
# Writing: the three kinds of running work, as one row each
# ---------------------------------------------------------------------------


#: Told the id of every run written down with a brief, so it can be given its
#: sentence (`runtime.RunSummaries`, `rouh/runsummary.py`). Set at start; with
#: nothing set, nothing is written and nothing else changes.
on_brief: Callable[[str], None] | None = None


def request_of(brief: str) -> str:
    """What a run was asked, without the standing rules its start put in front
    of it (`rules.run_block`): the register keeps the request, which is what a
    run is searched and summed up by, and what fits in its 4000 characters."""
    from . import rules

    return rules.unruled(brief)


def record(run_id: str, *, make: bool = True, first: bool = False, **fields: Any) -> None:
    """Write one run: made if it is new, brought up to date if it is not.

    Everything goes through here, so there is one place that decides what a
    write costs and one place that refuses to write the same thing twice.

    `first` is a start writing down a run it has just asked for: its state and phase
    are written only when the row is new, never over what the program has said since.

    `make` is whether this write may be the one that makes the row, and only a
    write that says what the run *is* may: its title, what it was asked, where
    it works and under what rules. Those are the start (`starting`), a redo
    (`one_jobs`) and the three feeds, `crew_run`, `one_run` and `sub_run`.
    Everything else is news about a run that is already written down - it
    ended, it is stuck on a conflict, its screen said something - and passes
    False (`sub_done`, `in_conflict`, `out_of_conflict`, `note`), so news
    about a run the register has never heard of is dropped rather than made
    into one.

    Until 24 September 2026 it was made into one. A row made from nothing but
    "it ended" has no title but its id, no brief, no workspace, no parent, and
    `safe` for its policy only because that is the column's default: to the
    task list it is one of Rouh's own jobs that nobody started, and its page
    says "That job is not on record here." Petar found the first,
    abaa3d7103f5, in his runs list that afternoon (fr_1d8c9f71239b). It was
    the next prompt Claude Code suggests after a turn, which `sub_done`
    explains.
    """
    st = store()
    if st is None or not run_id:
        return
    fields = _no_question_unless_waiting(st, run_id, fields)
    signature = tuple(sorted((k, _plain(v)) for k, v in fields.items()))
    if _written.get(run_id) == signature:
        return
    try:
        existing = st.get_run(run_id)
        if existing is None:
            if not make:
                log.info("run %s is not in the register, so nothing was written about it (%s)",
                         run_id, ", ".join(sorted(fields)))
                return
            title = fields.pop("title", "") or run_id
            st.create_run(title, id=run_id, **fields)
        else:
            # Both were settled when the run began and are never rewritten by a
            # later message about it: which run a sub-agent is inside, and when
            # it started.
            fields.pop("parent_run_id", None)
            fields.pop("started_at", None)
            if first:
                # `first` is the start writing its row down, and its state is only for a row
                # nobody has written yet. The program can answer first: a run refused at its
                # launch (no sign-in, a bad space) is requested and ended in the same instant,
                # and its "failed" reached this register before the start wrote "starting"
                # over it, so check_tasks and one_runs said "starting" for good (runs 2b3c4962
                # and 480de3be, 10 November 2026). What the program said about the run stands.
                fields.pop("state", None)
                fields.pop("phase", None)
                if not fields:
                    return
            st.update_run(run_id, **fields)
    except objects.Refused:
        # A refusal is a bug in what was handed over, never a reason to lose
        # the run: it goes in the log with the fields that caused it.
        log.exception("the register would not take run %s (%s)", run_id, fields)
        return
    except Exception:
        log.exception("could not write run %s to the register", run_id)
        return
    _written[run_id] = signature
    if fields.get("brief") and on_brief is not None:
        try:
            on_brief(run_id)
        except Exception:
            log.exception("run %s could not be given its sentence", run_id)


def _no_question_unless_waiting(st: objects.ObjectStore, run_id: str,
                                fields: dict) -> dict:
    """A question belongs to a run that is waiting, and to no other.

    In one place rather than in every writer, because a question is written
    from several of them and read off a terminal by one, and they do not all
    know what the row says this instant. A question left on a run that has been
    answered and gone back to work is a lie the row tells until the next thing
    happens to correct it.
    """
    if not fields.get("question"):
        return fields
    state = fields.get("state")
    if state is None:
        row = st.get_run(run_id)
        state = row.state if row is not None else "running"
    if state not in ("waiting", "conflict"):
        return {**fields, "question": None}
    return fields


def _plain(value: Any) -> Any:
    """Something that can go in a signature tuple. A float is rounded to the second."""
    if isinstance(value, float):
        return round(value)
    if isinstance(value, (list, dict)):
        return repr(value)
    return value


def crew_run(mate: Any) -> None:
    """A background worker, as a row of the register.

    Called from `crew.CrewManager` on every write of a `crewmates` row, which
    is the one place that table changes, so the register cannot fall behind it.
    """
    if not enabled():
        return
    status = str(mate.get("status") or "running").strip().lower()
    state = CREW_STATE.get(status, "running")
    mode = str(mate.get("mode") or "safe").strip().lower()
    meta = mate.get("meta") or {}
    closing = meta.get("closing") if isinstance(meta, Mapping) else None
    fields: dict[str, Any] = {
        "title": str(mate.get("title") or "")[:200] or "A job",
        "brief": request_of(str(mate.get("task") or ""))[:4000],
        "policy": mode if mode in objects.POLICIES else "safe",
        "workspace": str(mate.get("repo") or ""),
        "worktree": str(mate.get("workdir") or "") or None,
        "branch": mate.get("branch"),
        "state": state,
        "phase": status,
        "archived": bool(mate.get("archived")),
        "exit_code": mate.get("exit_code"),
        "started_at": _epoch(mate.get("created_at")) or time.time(),
        "updated_at": _epoch(mate.get("updated_at")),
        "ended_at": _epoch(mate.get("finished_at")),
    }
    # A worker's own row says nothing about what it is doing this second; that
    # is on its screen, and `check_tasks` writes it back here when it reads one
    # (`note`). So the line is only ever set here, never blanked, or every hook
    # a busy job fires would wipe what was last learnt about it.
    if status == "done" and closing:
        fields["detail"] = str(closing)[:400]
    # A job that died says what of, in one line, when that is known
    # (`crew.death_of`), and nothing at all when it is not: its card says
    # "Died without a report" then, rather than whatever line it last had.
    if status == "lost":
        death = meta.get("death") if isinstance(meta, Mapping) else None
        line = death.get("line") if isinstance(death, Mapping) else ""
        fields["detail"] = str(line or "")[:400]
    # A worker that stopped by handing a step to the live browser has not
    # finished: it sits at its prompt until the person has done the step and
    # Rouh has told it what it needs (`browser_handoff`). Its report keeps the
    # hand-off on the job (`Lander`, `JobReporter`), and while the job is
    # stopped on it, its row waits on the person, with the step as its
    # question. It has not ended either, so the row does not say so.
    handoff = (browser_handoff.from_dict(meta.get("handoff"))
               if status == "done" and isinstance(meta, Mapping) else None)
    if handoff is not None:
        fields.update(state="waiting", phase="waiting", ended_at=None,
                      detail=handoff.line(), question=handoff.line(400))
    # A question, though, is cleared the moment the job is not waiting on one.
    # A question left on a row that has moved on is worse than no question.
    elif state != "waiting":
        fields["question"] = None
    record(str(mate.get("id") or ""), **fields)
    kind_if_unknown(str(mate.get("id") or ""),
                    kind_of(policy=fields["policy"], workspace=fields["workspace"]))


def one_run(run: Mapping[str, Any]) -> None:
    """A run of the one program, as a row of the register.

    Called for every run the program sends over the socket, on connecting and
    then whenever one changes, so the register holds the program's runs whether
    or not the program is reachable this instant.
    """
    if not enabled():
        return
    run_id = str(run.get("id") or "")
    if not run_id:
        return
    state = str(run.get("state") or "working").strip().lower()
    # The brief is only written when there is one. A list of runs deliberately
    # leaves it out to stay small (`one/protocol._LIST_SKIP`), and this used to
    # take that as "there is no brief" and write an empty one over the brief
    # `starting._write_it_down` had just recorded. Every run of the program
    # therefore lost, within a second of starting, the one field that says what
    # it was asked to do - which is what the search reads a run by
    # (`rouh/searching.py`), and which matters more now that a run can be
    # started by the Gene therapy board with nobody watching (`rouh/triage.py`).
    said = request_of(str(run.get("brief") or ""))[:4000]
    row_state = ONE_STATE.get(state, "running")
    detail, question = _one_detail(run, state), _one_question(run, state)
    # A run that finished its turn by handing a step to the live browser is
    # open at its prompt and waiting on the person until that step is done
    # and it has been told what it needs (`browser_handoff`). The program
    # calls it idle, which is true of the program; the register says who it
    # is waiting on. Worked out from its last message every time, so a
    # restart, a reconnect or a second tab can never read it differently.
    handoff = browser_handoff.find(run.get("last_message")) if state == "idle" else None
    if handoff is not None:
        row_state, detail, question = "waiting", handoff.line(), handoff.line(400)
    record(
        run_id,
        title=str(run.get("title") or "")[:200] or "A run",
        **({"brief": said} if said else {}),
        agent="codex" if str(run.get("engine") or "") == "codex" else "claude",
        policy=ONE_POLICY,
        workspace=str(run.get("repo") or run.get("space") or ""),
        worktree=run.get("cwd"),
        branch=run.get("branch"),
        state=row_state,
        phase=state,
        detail=detail,
        question=question,
        archived=bool(run.get("archived")),
        exit_code=run.get("exit_code"),
        started_at=_epoch(run.get("requested_at")) or time.time(),
        updated_at=_epoch(run.get("last_at")),
        ended_at=_epoch(run.get("ended_at")),
    )
    # Which half of Metabolism it is on, from the space it was started in, unless
    # its start already said (a delegate_task works in the person's space and is
    # still a mutation).
    kind_if_unknown(run_id, kind_of(space=str(run.get("space") or "")))
    # And how it ended, for which model succeeds (`rouh/modeloutcomes.py`).
    from . import modeloutcomes

    modeloutcomes.run_ended(run)
    if state in ("failed", "lost", "killed", "reaped"):
        # A nightly refactoring night keeps its run's whole reason (`nightly_refactor.run_ended`).
        from . import nightly_refactor

        try:
            nightly_refactor.run_ended(dict(run))
        except Exception:  # noqa: BLE001 - the register is written either way
            log.exception("the nightly refactoring night of run %s could not keep how it ended", run_id)


def _one_detail(run: Mapping[str, Any], state: str) -> str:
    """The one line under a run of the program's title, in the list's words.

    Worked out once here and kept on the row, so a tab that opens after the
    program has gone still reads it. A run of Codex says who pays for it at
    the front of the line, every time (one/billing.py): the OpenAI API key is
    billed per token, and that is never left for somebody to find out.
    """
    said = _one_line(run, state)
    if str(run.get("engine") or "") != "codex":
        return said
    paid = ("Codex, billed to the OpenAI API key" if run.get("billing") == "api"
            else "Codex, on the ChatGPT subscription")
    return f"{paid} · {said}"[:160] if said else paid


def _one_line(run: Mapping[str, Any], state: str) -> str:
    if state == "queued":
        why = run.get("queued_because")
        return f"Queued - {why}"[:160] if why else ""
    if state == "asking":
        return str(run.get("question_text") or run.get("waiting_on_terminal")
                   or "It is waiting for you.")[:160]
    if state == "reaped":
        # Not its last message, which would read as a finish: the program
        # stopped it at the time limit (one/scheduler.py, close_overdue).
        said = "Cleaned up: stopped at the time limit, with everything it started"
        return (f"{said}; {run['left']}" if run.get("left") else said)[:160]
    if state in ("lost", "failed") and run.get("ended_why"):
        # What ended it, as the program wrote it down (`one/runs.py`, `_end`):
        # without it a lost run's card said only "Died without a report".
        said = str(run["ended_why"]).strip()
        if state == "lost":
            return f"Lost: {said}"[:160]
        return (said[:1].upper() + said[1:])[:160]
    if ONE_WORD.get(state) in ("done", "idle"):
        return next((line.strip() for line in str(run.get("last_message") or "").splitlines()
                     if line.strip() and not line.strip().startswith("PAGE:")), "")[:160]
    return str(run.get("doing") or "")[:160]


def _one_question(run: Mapping[str, Any], state: str) -> str | None:
    """What a run of the program has stopped to ask, or nothing.

    `question` is set while a run is waiting and cleared the moment it is not,
    because a question left on a row that has moved on is worse than no
    question at all.
    """
    if ONE_STATE.get(state) != "waiting":
        return None
    # The question's words, which the program sends beside its id; the id
    # alone is a number nobody can answer.
    asked = run.get("question_text") or run.get("conflict_question")
    return str(asked or run.get("waiting_on_terminal") or "It is waiting for you.")[:400]


def sub_run(parent_id: str, agent_id: str, *, title: str = "sub-agent",
            at: float | None = None, workspace: str = "", policy: str = "",
            agent: str = "claude", fallback_parent: str = "") -> None:
    """A sub-agent inside a run, as a run of its own with its parent's id on it.

    This is the third kind of running work and until now it was written down
    nowhere: it lived only as a node derived from a stream of hook events, so
    it was on the orb and on no list, and nothing could be asked about it.

    The parent's workspace and policy are its own - a sub-agent works inside
    its parent's checkout under its parent's rules - so they are read off the
    parent rather than guessed.
    """
    st = store()
    if st is None or not agent_id or not parent_id:
        return
    if agent_id in _written:
        # Already written down. Which run it belongs to was settled when it
        # started and is never moved, and how it ended comes through `sub_done`,
        # so there is nothing here to say again - and this is read off a tree
        # that arrives several times a second.
        return
    parent = st.get_run(parent_id)
    if parent is None and fallback_parent:
        # The sub-agent that made this call has not been written down yet, so
        # the run it is inside takes it: one branch too near the trunk is a
        # small thing beside a helper that is not on the orb at all.
        parent_id = fallback_parent
        parent = st.get_run(parent_id)
    if parent is None:
        # A sub-agent whose parent the register has never heard of. Dropping it
        # would lose a branch off the orb; hanging it off nothing would make it
        # a spike of its own, which is the exact thing this step is fixing. So
        # it waits for its parent, which the same feed writes a moment later.
        return
    record(
        agent_id,
        parent_run_id=parent_id,
        title=str(title or "sub-agent")[:200],
        agent=agent if agent in objects.AGENTS else parent.agent,
        policy=policy or parent.policy,
        workspace=workspace or parent.workspace,
        worktree=parent.worktree,
        state="running",
        phase="running",
        started_at=at if at is not None else time.time(),
        updated_at=at if at is not None else time.time(),
    )


def sub_done(agent_id: str, *, at: float | None = None, state: str = "done") -> None:
    """A sub-agent that closed. Its parent goes on running without it.

    Only a sub-agent `sub_run` wrote down can close. A close for one that never
    started is not a sub-agent at all, and Claude Code sends one after every
    turn once its prompt suggestions are on, as they are for this machine's
    account since 24 September 2026: the grey next prompt it offers the person
    is worked out by a hidden fork of the conversation, and that fork ends with
    ``SubagentStop``, an empty ``agent_type`` and the suggestion as its last
    message, with no ``SubagentStart`` before it. Measured that day against
    Claude Code 2.1.280 and 2.1.281 alike. The work tree has always dropped
    such a close (`tree._apply_subagent_stop`); this used to make a job of it.
    """
    if not enabled() or not agent_id:
        return
    moment = at if at is not None else time.time()
    record(agent_id, make=False, state=state, phase=state, updated_at=moment,
           ended_at=moment)


def note(run_id: str, **fields: Any) -> None:
    """Write back what was found somewhere else: a screen, a terminal, a record.

    The database is the source of truth, so something learnt off a worker's
    terminal is an inbound change to reconcile into the row rather than a fact
    that lives on a screen for whoever looks next. It is news about a run that
    is already written down, and never what writes one (`record`).
    """
    if not enabled():
        return
    record(run_id, make=False, **fields)


def came_from(run_id: str, chat_id: str) -> bool:
    """Write down which conversation started this run. True when it was written.

    A `from` reference and never ownership: the run outlives the chat it came
    from, a person may file it under a task afterwards without moving where its
    report goes, and deleting the chat leaves the run and its diff exactly
    where they are. Which is why "who started this" is a link of its own and
    not the run's owner - they are two different questions and only one of them
    has an answer that may be changed later.

    Written once, as the run begins, because that is the only moment anybody
    knows: by the time it finishes the person is somewhere else entirely, which
    is the whole reason this exists. `chat_of` is the reading side.

    Never raises. A chat that is not there, a run the register has not got and
    a register that is switched off are each a false rather than a failed
    start: a run that reports in the wrong thread is a nuisance, and a run that
    would not start because of it is a bug.
    """
    st = store()
    if st is None or not run_id or not chat_id:
        return False
    try:
        if st.get_chat(chat_id) is None:
            return False
        st.add_ref("from", "run", run_id, "chat", chat_id)
        return True
    except objects.Refused:
        log.warning("run %s could not be marked as coming from chat %s", run_id, chat_id)
    except Exception:
        log.exception("could not write which chat started run %s", run_id)
    return False


def in_conflict(run_id: str, question: str) -> None:
    """This run's work will not go onto main and only a person can say what next.

    The fifth state. `phase` is left exactly as it was, so when the conflict is
    answered the row goes back to saying what it was saying before it without
    anybody having had to remember.
    """
    if not enabled() or not run_id:
        return
    record(run_id, make=False, state="conflict", question=str(question or "")[:400])


def conflicted(limit: int = LIMIT) -> list[str]:
    """Every run the register says is stuck on a conflict.

    Asked for rather than remembered, because the fifth state outlives the
    process that wrote it: a conflict answered while Rouh was not running, or
    answered by `land.sh` in the job's own checkout, is a row that says it
    needs a person and nothing left in memory to notice that it does not
    (`server.ConflictFeed.sweep`).
    """
    st = store()
    if st is None:
        return []
    try:
        return [r.id for r in st.newest_runs_where(lambda state, ended: state == "conflict", limit=limit)]
    except Exception:
        log.exception("could not read the run register")
        return []


def out_of_conflict(run_id: str) -> None:
    """Answered, parked or landed: put the row back to its own state."""
    st = store()
    if st is None or not run_id:
        return
    row = st.get_run(run_id)
    if row is None or row.state != "conflict":
        return
    record(run_id, make=False, state=_state_of_phase(row.phase, row.policy), question=None)


def _state_of_phase(phase: str, policy: str) -> str:
    table = ONE_STATE if policy == ONE_POLICY else CREW_STATE
    return table.get(str(phase or "").strip().lower(), "running")


def forget(run_id: str) -> bool:
    """Take a run out of the register. Its sub-agents become runs of their own."""
    st = store()
    if st is None or not run_id:
        return False
    _written.pop(run_id, None)
    try:
        return st.delete_run(run_id)
    except Exception:
        log.exception("could not take run %s out of the register", run_id)
        return False


# ---------------------------------------------------------------------------
# Reading: one query, three shapes
# ---------------------------------------------------------------------------


def chat_of(run_id: str, depth: int = 4) -> str:
    """The conversation a run was started from, or "" when none started it.

    The one question the report path asks. Rouh used to say what a job found
    in whichever thread the person happened to have open when it finished,
    which is almost never the thread they asked in: they ask for something,
    walk off to talk about something else, and the answer to the first arrives
    in the middle of the second. So a run carries the chat that started it
    (`came_from`), and its card, its spoken report, its question and its
    conflict all go there instead.

    A sub-agent was started by its parent and not by anybody's conversation, so
    it takes its parent's chat: a question from inside a run belongs in the
    thread that run came from. `depth` bounds that walk, because a parent chain
    that is somehow a circle must not hang a report.

    "" for a run no conversation started, for one whose chat has since been
    deleted, and when the register is off. Where such a run reports is
    `reports_to`'s answer, General, and never the thread the person happens to
    be looking at.
    """
    st = store()
    if st is None or not run_id:
        return ""
    ident, seen = str(run_id), set()
    for _ in range(max(1, depth)):
        if ident in seen:
            return ""
        seen.add(ident)
        try:
            links = st.refs("from", src_type="run", src_id=ident, dst_type="chat")
            # Newest first: a run is written down once and linked once, so
            # there is one of these, and reading the last of them is only how a
            # second one - a run redone, restarted - would answer.
            for link in reversed(links):
                if st.get_chat(link.dst_id) is not None:
                    return str(link.dst_id)
            row = st.get_run(ident)
        except Exception:
            log.exception("could not read which chat started run %s", ident)
            return ""
        parent = str(getattr(row, "parent_run_id", "") or "") if row is not None else ""
        if not parent:
            return ""
        ident = parent
    return ""


def reports_to(run_id: str) -> str:
    """The conversation a run reports in: the one that started it, or General.

    Everything a run puts in front of the person goes here - its card, what
    Rouh says about it, its questions and its conflicts - and never into the
    chat that happens to be open. That fallback was `chat_of`'s "" read as "the
    thread the person is looking at", and every run no conversation started
    went down it: the Gene therapy board's own builds, the Start box, a redo. On 23
    September 2026 a chat about weekend plans was filled with cards
    about a draggable divider and the Latest pill, because that was the chat on
    the screen when those builds finished (feedback fr_9e9cea243870).

    General is where a result with no conversation of its own has always been
    meant to go ("notifications, job results, loose talk, anything with no home
    yet", `conversations.GENERAL`), and it is always there. A finished run no
    conversation started still keeps its own report out of it
    (`report_stays`): this answers General all the same, so a run's question
    and its conflict go on reaching the person there, and the reporters ask
    `report_stays` before they draw or say anything.
    """
    from .conversations import GENERAL

    return chat_of(run_id) or GENERAL


def report_chat(run_id: str) -> str:
    """The conversation a finished run's report is put into, or "" for none.

    The chat the run was started from (`chat_of`), General included. Petar, 12
    October 2026: "A run that was started through a chat should pass the chat
    id. So that when the run completes the chat receives the report and the
    notification has a link to the chat too." So a run asked for in General
    reports in General again, as a run asked for in any other chat always has,
    and its notice and its row on the Runs list link to it.

    "" for a run no conversation started - the Start box, the Gene therapy board's
    own builds, a mail case's work, the nightly feature run - which keeps
    working as it did: its report stays on its own run, which the Runs list
    marks with a dot until it is opened, and a page it made is on its task's
    page. That rule was Petar's of 24 September 2026, for all of General then:
    "general should be only me and rouh communicating" - and what it was about
    was the stream of runs nobody had asked for there.

    And "" for the chats beats run in (`rouh/heartbeat.py`), since 5 October
    2026: the Heartbeat chat and each piece of long-running work's own. A run a
    beat started is the heartbeat's to read, at its next beat, which it is
    woken for. A report said there would be a turn in its chat that nobody
    asked for, and its work is read where the rest of it is.
    """
    chat = chat_of(run_id)
    return chat if hears_back(chat) else ""


def hears_back(chat: str) -> bool:
    """Whether a run started from `chat` reports back into it (`report_chat`).

    Every conversation does, General too, except the heartbeat's; "" is no
    conversation, and a run started from nowhere reports nowhere.
    """
    from . import heartbeat

    return bool(chat) and chat not in heartbeat.CHATS


def report_stays(run_id: str) -> bool:
    """Whether a finished run's report stays on the run, out of every chat.

    True when there is no chat to report into (`report_chat`). Two things that
    are not a report still reach General even then: a question a run is
    stopped on and a conflict waiting for a pick, which need the person to
    answer before any work goes on. And a report whose job queued a note to be
    emailed still asks about the note there, and says nothing else
    (`outbox.on_its_own`), because the person asked for that email and Rouh is
    the only one who can send it.
    """
    return not report_chat(run_id)


def chats_of(run_ids: Iterable[str]) -> dict[str, str]:
    """Which conversation each of these runs reports into, for the ones that have one.

    `report_chat` for many runs in two queries rather than two each, for the
    Runs list (`rows`). Only the runs' own links: a sub-agent is never a row.
    """
    st = store()
    ids = [str(i) for i in run_ids if i]
    if st is None or not ids:
        return {}
    try:
        from . import heartbeat
        from .models.objects import Chat, Link

        links = (Link.objects.filter(rel="from", src_type="run", dst_type="chat",
                                     src_id__in=ids)
                 .order_by("created_at", "id").values_list("src_id", "dst_id"))
        found = dict(links)
        there = set(Chat.objects.filter(id__in=set(found.values()))
                    .values_list("id", flat=True))
    except Exception:
        log.exception("could not read which chats the runs were started from")
        return {}
    return {run: chat for run, chat in found.items()
            if chat in there and chat not in heartbeat.CHATS}


def all_runs(limit: int = LIMIT, *, parent=objects.UNSET) -> list[objects.Run]:
    """Runs the register holds, newest first. The one query everything reads.

    `parent` left out means every run whatever it is inside; None means only
    the ones nobody started - the jobs a person asked for - and an id means
    that run's own sub-agents. The task list asks for None, so a machine full
    of helpers can never crowd the jobs off it.
    """
    st = store()
    if st is None:
        return []
    try:
        return st.list_runs(limit=limit, parent_run_id=parent)
    except Exception:
        log.exception("could not read the run register")
        return []


def _live_runs(since: float) -> list[objects.Run]:
    """The runs nobody started, among the newest `LIMIT`, that are not over or ended after
    `since`: the ones the tree can draw (`tree`), read without reading the rest whole."""
    st = store()
    if st is None:
        return []
    try:
        return st.newest_runs_where(lambda state, ended: ended is None or ended >= since, limit=LIMIT)
    except Exception:
        log.exception("could not read the run register")
        return []


def get(run_id: str) -> objects.Run | None:
    st = store()
    if st is None or not run_id:
        return None
    try:
        return st.get_run(run_id)
    except Exception:
        return None


def is_one_run(run_id: str) -> bool | None:
    """Whether that run is the one program's, or None when the register has no row."""
    row = get(run_id)
    return None if row is None else (row.policy == ONE_POLICY)


def status_of(row: objects.Run) -> str:
    """A run's state in the task list's own words, which have not changed.

    The list has always had seven words and the register has five states, so
    the finer word comes from `phase`, which is written beside `state` by the
    same statement. A row with no phase - nothing has written one yet - falls
    back to its state, which is never wrong, only less exact.
    """
    phase = str(row.phase or "").strip().lower()
    if row.state == "conflict":
        return "waiting"
    if row.state == "waiting" and row.ended_at is not None:
        # Its worker has exited. Whatever it had stopped to ask, nobody is
        # standing there waiting for the answer any more, and a row that says
        # NEEDS YOU about a job that is over is exactly the lie that put five
        # red spikes on the orb for three finished jobs.
        return "failed" if row.exit_code else "done"
    if row.policy == ONE_POLICY:
        if row.state == "waiting" and phase == "idle":
            # Finished its turn by handing a step to the live browser, and
            # waiting on the person for it (`one_run`, `browser_handoff`).
            return "waiting"
        return ONE_WORD.get(phase) or STATE_WORD.get(row.state, "running")
    if phase in ("starting", "running", "waiting", "done", "lost", "killed", "failed"):
        return phase
    return STATE_WORD.get(row.state, "running")


def _looked_at(row: objects.Run, since: float) -> bool:
    """Whether the person has looked at this run since it stopped, or it
    stopped before they were here to look. When a run that has not ended
    stopped is when it was last written: a run waiting on a question."""
    if row.seen_at:
        return True
    stopped = row.ended_at or row.updated_at or row.started_at
    return bool(since) and float(stopped or 0.0) <= since


def owner_of(row: objects.Run) -> str:
    """Who runs it: "assistant", "self", "one", or the server itself."""
    return OWNER.get(row.policy, "server")


def task_row(row: objects.Run, *, live: Mapping[str, Any] | None = None,
             since: float | None = None, chat: str | None = None) -> dict:
    """One run as a row of the task list, in exactly the shape it has always had.

    `live` is the handful of things that are not facts of record: whether a
    terminal has the run open this instant, which the one program answers and
    nothing here could.

    `since` is `objects.news_since`, asked once by a caller drawing many rows
    and here when it did not. `chat` is the conversation it reports into, the
    same way: asked once for many rows (`chats_of`), and here when it was not.
    """
    status = status_of(row)
    out = {
        "id": row.id,
        "title": row.title or "Untitled",
        "status": status,
        "mode": row.policy,
        "created_at": _iso(row.started_at),
        "updated_at": _iso(row.updated_at or row.started_at),
        "finished_at": _iso(row.ended_at),
        "exit_code": row.exit_code,
        "repo": row.workspace or None,
        "branch": row.branch,
        "detail": row.detail or "",
        # What it was for, in one sentence written from its brief as it began,
        # which its card shows in place of `detail` once it has finished well
        # (`rouh/runsummary.py`). "" until it has one.
        "summary": row.summary or "",
        # Which half of Metabolism it is on: "mutation", a run that changes
        # Rouh itself, or "everyday" (`kind_of`).
        "kind": kind_of_row(row),
        "archived": bool(row.archived),
        # The person's own mark, which the list is sorted by before anything
        # else. Archiving puts a run out of the way; this keeps one in view.
        "pinned": bool(row.pinned),
        # And whether they have looked at it since it stopped, which is what
        # the red dot on the Runs tab counts. Cleared by the register itself
        # every time the run stops again (`objects._unseen_again`). A run that
        # stopped before the person had an account is not news to them - it
        # came with the history of runs they were given - so it counts as
        # seen whether or not they have opened it (`objects.news_since`).
        "seen": _looked_at(row, objects.news_since() if since is None else since),
        "owner": owner_of(row),
        # The conversation it was started from and reports into, or "" for a
        # run no conversation started (`report_chat`). Its card links to it,
        # so the dot that says it has finished leads to the report as well as
        # to the run (Petar, 12 October 2026).
        "chat": report_chat(row.id) if chat is None else chat,
        "asking": status == "waiting",
        "options": [],
    }
    if row.policy == ONE_POLICY:
        # A run of the program says what it is doing itself, and whether a
        # terminal has it open is the program's to answer.
        out["terminal"] = (live or {}).get("terminal")
    return out


def rows(only: str | None = None, *, live: Mapping[str, Mapping[str, Any]] | None = None,
         limit: int = LIMIT) -> list[dict]:
    """The task list, and `check_tasks`, from the one register.

    Sub-agents are left off: the list is a list of jobs a person started, and a
    helper inside one of them is a branch on the orb and a line on its parent's
    card, never a row of its own. They are still runs, and `tree` draws them.
    """
    out = []
    since = objects.news_since()
    chosen = [row for row in all_runs(limit=limit, parent=None)
              if not only or str(row.id).startswith(str(only))]
    chats = chats_of(row.id for row in chosen)
    for row in chosen:
        out.append(task_row(row, live=(live or {}).get(row.id), since=since,
                            chat=chats.get(row.id, "")))
    return out


def row_for(run_id: str, *, live: Mapping[str, Any] | None = None) -> dict | None:
    """One run as a task row, or None when the register has never heard of it."""
    row = get(run_id)
    return task_row(row, live=live) if row is not None else None


def one_runs(limit: int = LIMIT) -> list[objects.Run]:
    """Every run of the one program the register holds, newest first."""
    return [r for r in all_runs(limit=limit, parent=None) if r.policy == ONE_POLICY]


def describe_one_runs(questions: Iterable[Mapping[str, Any]] = ()) -> str:
    """`one_runs`, answered from the register instead of from the program.

    The same words in the same shape: the renderer is
    `one_client.describe_runs`, handed the register's rows in the shape it
    reads. The questions are still the program's, because a question is a thing
    of its own there and Rouh holds none of them; a run's own row carries
    what it is waiting on either way.
    """
    from .one_client import describe_runs

    return describe_runs([_as_program_run(r) for r in one_runs()], list(questions))


def _as_program_run(row: objects.Run) -> dict:
    """A register row in the shape the program's own words are written from."""
    detail = row.detail or ""
    queued = detail[len("Queued - "):] if detail.startswith("Queued - ") else None
    return {
        "id": row.id,
        "title": row.title,
        "state": str(row.phase or "").strip().lower() or _program_word(row),
        "doing": detail,
        "last_message": detail,
        "queued_because": queued,
        "waiting_on_terminal": row.question if row.state == "waiting" else None,
        "driver": None,
        "left": "",
        "archived": bool(row.archived),
    }


def _program_word(row: objects.Run) -> str:
    """A row with no phase, in the program's vocabulary. Rare: a very old row."""
    return {"running": "working", "waiting": "asking", "conflict": "asking",
            "done": "done", "failed": "failed"}.get(row.state, "working")


# ---------------------------------------------------------------------------
# The tree: spikes are top-level runs, branches are runs with a parent
# ---------------------------------------------------------------------------


def tree(now: float | None = None, *, twigs: Mapping[str, list] | None = None,
         efforts: Mapping[str, str] | None = None,
         prune_after: float = PRUNE_AFTER, window: float = WINDOW) -> dict:
    """The work tree, built from `parent_run_id` and from nothing else.

    A top-level run is a spike off the core; a run with a parent is a branch
    off it, however deep; a run that is waiting is the red NEEDS YOU node. The
    tool calls inside a run are twigs, and they are the one thing here that is
    not a run: they come from that run's own hooks, handed in as `twigs`. How
    hard each run is thinking comes from the same hooks, as `efforts`.
    """
    moment = time.time() if now is None else now
    children = []
    for row in sorted(_live_runs(moment - window), key=lambda r: r.started_at):
        # Long over, and nothing inside it can still be going: a sub-agent
        # cannot outlive its parent by a quarter of an hour. Skipped without
        # asking for its children, so a machine with months of finished runs on
        # it costs one query rather than one per run.
        if row.ended_at is not None and moment - row.ended_at > window:
            continue
        node = _node(row, twigs or {}, moment, prune_after, window, efforts=efforts or {})
        if node is not None:
            children.append(node)
    waiting = any(_waiting_in(node) for node in children)
    return {"id": "root", "kind": "root",
            "state": "waiting" if waiting else "running", "children": children}


def _node(row: objects.Run, twigs: Mapping[str, list], now: float, prune_after: float,
          window: float, depth: int = 0, *, efforts: Mapping[str, str] | None = None
          ) -> dict | None:
    """One run as a node, with its sub-agents under it. None when it is over and gone."""
    state = NODE_STATE.get(status_of(row), "running")
    kids: list[dict] = []
    if depth < 6:      # a helper six deep is a loop, not a tree
        for child in sorted(all_runs(parent=row.id), key=lambda r: r.started_at):
            made = _node(child, twigs, now, prune_after, window, depth + 1, efforts=efforts)
            if made is not None:
                kids.append(made)
    open_below = any(kid["state"] in ("running", "waiting") for kid in kids)
    ended = row.ended_at
    if state not in ("running", "waiting"):
        # A run that finished a turn with a sub-agent still working is not
        # finished: nothing is, while something inside it is still going.
        if open_below:
            state, ended = "running", None
        elif ended is not None and now - ended > prune_after:
            return None
        elif ended is None and now - (row.updated_at or row.started_at) > window:
            return None
    elif now - (row.updated_at or row.started_at) > window and not open_below:
        # Open, and not heard from for a quarter of an hour. `crew.tree_events`
        # has always stopped drawing one of these rather than leaving a line on
        # the orb for ever.
        return None

    node: dict[str, Any] = {
        "id": row.id,
        "kind": "subagent" if row.parent_run_id else "worker",
        "label": row.title or row.id,
        "state": state,
        "owner": owner_of(row),
        "opened_at": row.started_at,
        "children": list(twigs.get(row.id) or []) + kids,
    }
    if row.policy:
        node["mode"] = row.policy
    if row.detail:
        node["doing"] = row.detail[:160]
    if (efforts or {}).get(row.id):
        node["effort"] = efforts[row.id]
    if ended is not None:
        node["closed_at"] = ended
        node["ms"] = int(max(0.0, ended - row.started_at) * 1000)
    if state == "waiting" and row.question:
        node["asking"] = row.question[:400]
    return node


def _waiting_in(node: Mapping[str, Any]) -> bool:
    if node.get("state") == "waiting":
        return True
    return any(_waiting_in(child) for child in node.get("children") or ())


def twigs_of(built: Mapping[str, Any]) -> dict[str, list]:
    """The tool calls in a tree built from hook events, by the run they were made in.

    The shape of the tree comes from the register; what a run did inside itself
    comes from its own hooks, and this is the join between the two. Everything
    that is not a tool call is dropped here, because a sub-agent is a run and
    the register already has it.
    """
    out: dict[str, list] = {}

    def walk(node: Mapping[str, Any]) -> None:
        kids = node.get("children") or ()
        if node.get("kind") in ("worker", "subagent"):
            calls = [c for c in kids if c.get("kind") == "tool"]
            if calls:
                out.setdefault(str(node.get("id")), []).extend(calls)
        for child in kids:
            walk(child)

    walk(built)
    return out


def efforts_of(built: Mapping[str, Any]) -> dict[str, str]:
    """How hard each run is thinking, by run, from a tree built from hook events.

    Claude Code says its level on every tool call (`rouh/tree.py`), and the
    card for a job shows it under Effort. Until 27 September 2026 it was lost
    here: the tree's shape came from the register and only the tool calls were
    carried across, so no card said how hard any run was thinking.
    """
    out: dict[str, str] = {}

    def walk(node: Mapping[str, Any]) -> None:
        if node.get("kind") in ("worker", "subagent") and node.get("effort"):
            out[str(node.get("id"))] = str(node["effort"])
        for child in node.get("children") or ():
            walk(child)

    walk(built)
    return out


# ---------------------------------------------------------------------------
# Times
# ---------------------------------------------------------------------------
#
# The register keeps seconds since 1970, and everything that reads a row wants
# the ISO string the two halves it replaced both wrote. One spelling, in UTC,
# because that is what every record on this machine is written in and what
# `clock.moment` assumes of a string with no zone on it.


def _epoch(value: Any) -> float | None:
    """Seconds since 1970, from a float, an ISO string, or nothing."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.timestamp()


def _iso(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), timezone.utc).isoformat(timespec="seconds")
