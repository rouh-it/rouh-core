"""A heartbeat's beat as a background job: code decides, the job acts.

Petar, 18 November 2026 (task 182, step 182-08 found why): every beat was a turn in one
Heartbeat chat that was never cleared and was sent whole, so each beat re-sent every beat
before it - 37,000 tokens on 5 October, 641,000 on 17 November, about $3 a beat on Opus - and
a blank Rouh beat about four times a day with nothing to do. "Rebuild Rouh's heartbeat so each
beat runs as a background job in Claude Code or Codex ... not as a turn in a single,
ever-growing Heartbeat chat on the per-token API." So, here:

**Code decides** (`rouh/heartbeat.py`, `Heartbeat._tick` and `_skip_because`): off, paused,
quiet hours, a turn already running, the daily cap, and whether there is anything at all to do:
an event that is the heartbeat's own business, a time it set itself, Beat now, the owner's
answer, the daily summary, or something a duty finds in code (`probe`). A beat with nothing to
do never starts a job, and the timer's look with nothing found leaves no row at all.

**The job acts.** A beat with something to do starts one background job (`start`), through the
one start path every job takes (`starting.start`, preset "heartbeat_beat"), on the agent and
model the Models page has for it (`USE`, the Smart tier unless given its own): Claude Code or Codex, on the subscription or, for a
person with none, on an API key. Its brief is written fresh every time (`heartbeat.note_for_duties`,
`note_for_work`): what happened, what it already told the owner, what waits on them, its duties
and quests, what it may do. It carries no chat: the Heartbeat chat is kept as history and is
never sent anywhere again. Anything else the job reads itself, from the workspace and from Rouh
through the `rouh` MCP server every job has, where a beat's job is given the heartbeat's own
tools and held to exactly the heartbeat's rules (`job_gateway`, scope `beat`).

**Context by topic.** What a beat did about a task, a step, a run, a quest or a mail thread is
written to that subject's own record (`HeartbeatSubject`, `write_record`, the job's
heartbeat_record), and the next beat about that subject is handed that record, a few lines, and
no other subject's (`records_for`). A beat about task 1 never carries task 2.

**One shared ledger** of what the owner was told: one line per Telegram or note, when and about
what (`told`), in every brief, so nobody is told the same thing twice. It is the only thing every
beat shares.

**What wakes it** (`run_wakes`): runs the heartbeat or a quest started, runs waiting on the
owner, runs nobody has reported, mail in Rouh's own inbox, the owner's answers, times it set
itself, and Beat now. Never a run the owner started, which is reported to them in its own chat,
and never a beat's own job, which would wake the heartbeat for ever.
"""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("rouh.heartbeat_jobs")

#: The Models page's pick for a beat's job (`modeldefaults.USES`, "Beat job"): the Smart model and
#: its level, as every background job resolves it, unless the page gives it a model of its own.
#: Claude Code on a Claude model, Codex on an OpenAI one.
USE = "heartbeat_decide"
#: What a beat's job is made by, on its run (`task_origin.run_maker`), the heartbeat's own duties'
#: and a quest's.
MADE_BY = "process:heartbeat"
MADE_BY_QUEST = "process:quests"
#: How a beat's job is named on the orb and the run lists.
TITLE = "\U0001f493 Heartbeat beat"
#: How long a beat's job may run before it is stopped.
LIMIT = 15 * 60.0
#: How often a running beat's job is looked at, for its end and the daily cap.
LOOK = 10.0
#: The most lines a subject's record keeps, and hands a beat.
SUBJECT_LINES = 8
LINE_MOST = 400
#: The most a brief is handed of the ledger of what the owner was told, and how far back.
TOLD_MOST, TOLD_DAYS = 40, 7
#: How long ago a run may have stopped and still be news for the probes.
RECENT = 2 * 86400
#: How many keys of what a probe found are remembered as handled.
HANDLED_MOST = 400
#: The subject kinds a record is kept for.
KINDS = ("task", "step", "run", "quest", "mail")
#: A beat that costs this many times its usual is warned about on the Heartbeat page.
DEAR = 2


def _models():
    from . import models

    return models


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


# --- subjects and their records -----------------------------------------------------------


def subject(kind: str, ref) -> str:
    """One subject as it is written on a beat and in a tool call: "task:182", "run:abc"."""
    return f"{kind}:{str(ref).strip()}"


def parse_subject(text: str) -> tuple[str, str] | None:
    """("task", "182") from "task:182", "task 182" or "Task 182"; None for anything else."""
    text = " ".join(str(text or "").split()).strip()
    for sep in (":", " "):
        if sep in text:
            kind, _, ref = text.partition(sep)
            kind, ref = kind.strip().lower(), ref.strip().lstrip("#")
            if kind in KINDS and ref and len(ref) <= 200:
                return kind, ref
    return None


def _task_of_run(run_id: str) -> str:
    """The task a run is filed under, as its id, or "" (`owning.owner_of`)."""
    try:
        from . import owning

        st = owning.store()
        found = st.owner_of("run", run_id) if st is not None else None
        if found and found[0] == "task":
            return str(found[1])
    except Exception:  # noqa: BLE001 - a run with no task known is a run on its own
        log.debug("the task of run %s could not be read", run_id, exc_info=True)
    return ""


def subjects_of(events: list, items: list, work=None) -> list[str]:
    """What a beat is about: the quest it is on, every run, task and mail thread its events and
    what its duties found name, each once, in the order they came."""
    out: list[str] = []

    def add(s: str) -> None:
        if s and s not in out:
            out.append(s)

    if work is not None:
        add(subject("quest", work.id))
    for e in events or []:
        if not isinstance(e, dict):
            continue
        if e.get("run"):
            add(subject("run", e["run"]))
            if e.get("task"):
                add(subject("task", e["task"]))
        if e.get("thread"):
            add(subject("mail", e["thread"]))
        if e.get("subject"):
            add(str(e["subject"]))
    for it in items or []:
        add(str(it.get("subject") or ""))
        if it.get("task"):
            add(subject("task", it["task"]))
    return out[:20]


def records_for(user_id: str, org_id: str, subjects: list[str]) -> list[dict]:
    """Each of these subjects' record, and nobody else's: [{"subject", "title", "lines"}]."""
    wanted = [p for p in (parse_subject(s) for s in subjects) if p]
    if not wanted:
        return []
    from django.db.models import Q

    q = Q()
    for kind, ref in wanted:
        q |= Q(kind=kind, ref=ref)
    rows = {(r.kind, r.ref): r for r in _models().HeartbeatSubject.objects.filter(
        q, user_id=user_id, org_id=org_id)}
    out = []
    for kind, ref in wanted:
        r = rows.get((kind, ref))
        if r is not None and r.lines:
            out.append({"subject": subject(kind, ref), "title": r.title,
                        "lines": list(r.lines)[-SUBJECT_LINES:]})
    return out


def write_record(user_id: str, org_id: str, subject_said: str, text: str, *,
                 beat_id: int | None = None, title: str = "") -> str:
    """One line onto a subject's record; what to say back. Kept to `SUBJECT_LINES`."""
    from django.db import transaction

    got = parse_subject(subject_said)
    if got is None:
        return ("subject is one of task, step, run, quest or mail and its id, such as "
                "\"task:182\", \"run:3e003932\" or \"mail:<thread id>\".")
    text = " ".join(str(text or "").split())[:LINE_MOST]
    if not text:
        return "The text was empty."
    kind, ref = got
    m = _models()
    now = time.time()
    with transaction.atomic():
        row, _ = m.HeartbeatSubject.objects.select_for_update().get_or_create(
            user_id=user_id, org_id=org_id, kind=kind, ref=ref,
            defaults={"title": title[:200], "lines": [], "updated_at": now})
        line = {"at": now, "text": text}
        if beat_id is not None:
            line["beat"] = beat_id
        lines = (list(row.lines or []) + [line])[-SUBJECT_LINES:]
        fields = {"lines": lines, "updated_at": now}
        if title and not row.title:
            fields["title"] = title[:200]
        m.HeartbeatSubject.objects.filter(id=row.id).update(**fields)
    return f"Written to {subject(kind, ref)}'s record; the next beat about it is handed it."


def record_lines(records: list[dict]) -> str:
    """The records as a brief says them, or ""."""
    from . import clock

    if not records:
        return ""
    parts = []
    for r in records:
        head = r["subject"] + (f" ({r['title']})" if r.get("title") else "")
        parts.append(head + ":\n" + "\n".join(
            f"  - {clock.clock(x.get('at'))}: {x.get('text')}" for x in r["lines"]))
    return "\n".join(parts)


# --- the one ledger every beat shares: what the owner was told ---------------------------------


def told(row) -> list[dict]:
    """The ledger of what the owner was told, newest last: [{"at", "how", "about", "what"}]."""
    own = row.own if isinstance(getattr(row, "own", None), dict) else {}
    return [t for t in (own.get("told_ledger") or []) if isinstance(t, dict)]


def told_lines(row, now: float | None = None) -> str:
    """The ledger as a brief says it: one line each, the last `TOLD_DAYS` days, or ""."""
    from . import clock

    now = now or time.time()
    lines = [t for t in told(row) if now - float(t.get("at") or 0) < TOLD_DAYS * 86400]
    lines = lines[-TOLD_MOST:]
    out = []
    for t in lines:
        about = ", ".join(t.get("about") or []) or "no subject named"
        out.append(f"- {clock.clock(t.get('at'))}, {t.get('how') or 'note'} about {about}: "
                   f"{t.get('what') or ''}")
    # What earlier beats listed as told before the ledger came (`heartbeat_end`'s told).
    old = [x for x in ((row.own or {}).get("told") or [])][-10:] if not lines else []
    out += [f"- earlier: {x}" for x in old]
    return "\n".join(out)


def add_told(user_id: str, org_id: str, *, how: str, about: list[str], what: str) -> None:
    """One line onto the ledger, for a Telegram or a note the owner was given."""
    from django.db import transaction

    m = _models()
    with transaction.atomic():
        row = (m.HeartbeatState.objects.select_for_update()
               .filter(user_id=user_id, org_id=org_id).first())
        if row is None:
            return
        own = dict(row.own or {})
        entry = {"at": time.time(), "how": how, "about": [str(a)[:120] for a in about][:8],
                 "what": " ".join(str(what or "").split())[:200]}
        own["told_ledger"] = (list(own.get("told_ledger") or []) + [entry])[-200:]
        m.HeartbeatState.objects.filter(id=row.id).update(own=own, updated_at=time.time())


# --- which beat a job is ---------------------------------------------------------------------


def beat_of_run(run_id: str):
    """The beat whose own job this run is, or None. Read from the beats, so it holds across a
    restart, and never woken for (`run_wakes`)."""
    run_id = str(run_id or "").strip()
    if not run_id:
        return None
    m = _models()
    row = m.HeartbeatBeat.objects.filter(run_id=run_id).order_by("-id").first()
    if row is not None:
        return row
    # Its job may speak before its beat has written down its id: a run titled and made as a
    # beat's is the one beat running that has no job yet (one at a time, under the beat lock).
    run = m.Run.objects.filter(id=run_id).values_list("title", "made_by", "parent_run_id").first()
    if run is None or run[1] not in (MADE_BY, MADE_BY_QUEST) or run[2] \
            or not str(run[0] or "").startswith(TITLE):
        return None
    return (m.HeartbeatBeat.objects.filter(kind="job", status="running", run_id="")
            .order_by("-id").first())


def is_beat_job(run_id: str) -> bool:
    """Whether this run is a beat's own job by its record alone: made by the heartbeat, titled as
    a beat, started by no other run. Holds even when no beat row names it."""
    run = (_models().Run.objects.filter(id=str(run_id or ""))
           .values_list("title", "made_by", "parent_run_id").first())
    return bool(run and run[1] in (MADE_BY, MADE_BY_QUEST) and not run[2]
                and str(run[0] or "").startswith(TITLE))


#: What a run's end is to the heartbeat (`run_wakes`).
BEAT, OWN, QUEST, UNREPORTED, PERSON = "beat", "own", "quest", "unreported", "person"


def run_wakes(who, run_id: str) -> tuple[str, object]:
    """What a run that ended is to the heartbeat, and the beat or quest it belongs to:

    - `BEAT`: a beat's own job. Never an event: it would wake the heartbeat for ever.
    - `QUEST`: a quest started it. An event on that quest.
    - `OWN`: the heartbeat started it, or one of its runs did. An event.
    - `UNREPORTED`: one of Rouh's own processes started it with no conversation to report in,
      so nobody has been told. An event.
    - `PERSON`: the owner started it, from a chat, the Start box or the one program, and it is
      reported to them there. Not an event.
    """
    from . import quests

    run_id = str(run_id or "").strip()
    beat = beat_of_run(run_id)
    if beat is not None or is_beat_job(run_id):
        return BEAT, beat
    work = quests.owning_of(who, "runs", run_id) if who is not None else None
    if work is not None:
        return QUEST, work
    from .models import HeartbeatState, Run

    state = HeartbeatState.objects.filter(**_whose(who)).first() if who is not None else None
    mine = set((state.own or {}).get("runs") or []) if state is not None else set()
    chain, at = [], run_id
    while at and at not in chain and len(chain) < 8:
        chain.append(at)
        at = Run.objects.filter(id=at).values_list("parent_run_id", flat=True).first() or ""
    if mine & set(chain):
        return OWN, None
    made = (Run.objects.filter(id=run_id).values_list("made_by", flat=True).first() or "")
    if made in (MADE_BY, MADE_BY_QUEST):
        return OWN, None
    if made.startswith("process:"):
        from . import runs

        if runs.report_stays(run_id):
            return UNREPORTED, None
    return PERSON, None


# --- what the duties find, in code -------------------------------------------------------------


def handled(row) -> set[str]:
    """The keys of what a probe found that a beat was already handed (`mark_handled`)."""
    return set((row.own or {}).get("handled") or []) if isinstance(row.own, dict) else set()


def mark_handled(row, keys: list[str]) -> None:
    from django.db import transaction

    if not keys:
        return
    m = _models()
    with transaction.atomic():
        fresh = m.HeartbeatState.objects.select_for_update().filter(id=row.id).first()
        if fresh is None:
            return
        own = dict(fresh.own or {})
        kept = [k for k in (own.get("handled") or []) if k not in keys]
        own["handled"] = (kept + list(keys))[-HANDLED_MOST:]
        m.HeartbeatState.objects.filter(id=row.id).update(own=own, updated_at=time.time())
    row.own = own


def _beat_runs() -> set[str]:
    return set(_models().HeartbeatBeat.objects.exclude(run_id="").values_list("run_id", flat=True)
               .order_by("-id")[:2000])


def probe(who, row, cfg: dict, *, now: float | None = None,
          calendar: list | None = None) -> list[dict]:
    """What the duties that are on find to do, in code, with no model asked, each not handed to a
    beat before: [{"duty", "key", "subject", "what"}]. Empty is a beat with nothing to look at.

    - waiting: a run waiting on the owner that they have not looked at (`Run.state` "waiting",
      its question or a LIVE BROWSER NEEDED hand-off).
    - unreported: a run of Rouh's own processes that ended with no conversation to report in, in
      the last two days, that the owner has not opened.
    - calendar: an event in the next three hours (`calendar`, read by the caller).
    - mail and goals have nothing to look for here: new mail in Rouh's own inbox wakes a beat by
      itself (`Heartbeat.mail_arrived`), and a goal's steps are run by Clockwork.
    A duty that is off finds nothing, and a beat's own job is never one of them."""
    from . import heartbeat, runs
    from .models import Run

    now = now or time.time()
    done = handled(row)
    beats = _beat_runs()
    found: list[dict] = []
    if heartbeat.duty_on(cfg, "waiting"):
        for r in Run.objects.filter(state="waiting", seen_at=0,
                                    updated_at__gte=now - RECENT).order_by("started_at")[:20]:
            if r.id in beats or str(r.title or "").startswith(TITLE):
                continue
            key = f"waiting:{r.id}:{int(r.updated_at or 0)}"
            if key in done:
                continue
            found.append({"duty": "waiting", "key": key, "subject": subject("run", r.id),
                          "task": _task_of_run(r.id),
                          "what": f"Run {r.id} “{r.title[:100]}” is waiting on ‹owner›"
                                  + (f": {' '.join(str(r.question).split())[:200]}"
                                     if r.question else ".")})
    if heartbeat.duty_on(cfg, "unreported"):
        for r in (Run.objects.filter(state__in=("done", "failed"), seen_at=0,
                                     ended_at__gte=now - RECENT)
                  .exclude(made_by="").exclude(made_by__in=(MADE_BY,)).order_by("ended_at")[:40]):
            if r.id in beats or not str(r.made_by).startswith("process:"):
                continue
            key = f"unreported:{r.id}"
            if key in done or not runs.report_stays(r.id):
                continue
            found.append({"duty": "unreported", "key": key, "subject": subject("run", r.id),
                          "task": _task_of_run(r.id),
                          "what": f"Run {r.id} “{r.title[:100]}”, started by "
                                  f"{str(r.made_by).removeprefix('process:')}, {r.state} and "
                                  "nobody has reported it."})
    if heartbeat.duty_on(cfg, "calendar"):
        for e in calendar or []:
            ident = str(e.get("id") or "")
            if not ident:
                continue
            key = f"calendar:{ident}:{e.get('start') or ''}"
            if key in done:
                continue
            found.append({"duty": "calendar", "key": key, "subject": "",
                          "what": f"In the calendar soon: {e.get('start') or ''} "
                                  f"“{str(e.get('summary') or 'an event')[:120]}”."})
    return found[:20]


# --- the job -----------------------------------------------------------------------------------


def engine(who) -> tuple[str, str]:
    """(agent, model) a beat's job is: Codex for an OpenAI model on the Models page, else Claude
    Code; the model the page has for it (`USE`)."""
    from . import modeldefaults
    from .config import is_openai

    model = modeldefaults.use_model(USE, str(getattr(who, "org_id", "") or "") or None) or ""
    if model == modeldefaults.OFF:
        model = ""
    return ("codex" if model and is_openai(model) else "claude"), model


class Hooks:
    """What the runtime lends this module. None until it sets it."""

    #: (**fields) -> awaitable dict: `starting.start` with the runtime's config, crew and program.
    start = None
    #: (run_id) -> awaitable: stops a run, a worker's or the one program's.
    stop = None
    #: (who) -> awaitable list of {"id", "summary", "start"}: the calendar's next few hours.
    calendar = None


hooks = Hooks()


async def start(who, *, brief: str, title: str, work_id: int | None = None) -> dict:
    """Start one beat's job; what `starting.start` answers. Raises when nothing took it."""
    if hooks.start is None:
        raise RuntimeError("background jobs cannot be started here")
    # Only the agent is worked out here; the model and its level are the use's own, resolved by
    # the one start path exactly as for any job (`starting.start`, `modeldefaults.use_pair`).
    agent, _model = await asyncio.to_thread(engine, who)
    return await hooks.start(
        brief=brief, title=title, preset="heartbeat_beat", agent=agent, use=USE,
        org_id=str(who.org_id), made_by=MADE_BY_QUEST if work_id is not None else MADE_BY,
        standing_rules=False)


def run_state(run_id: str) -> tuple[str, float | None]:
    """A run's state in the register, and what it is known to have cost per use."""
    row = _models().Run.objects.filter(id=run_id).values_list("state", "cost_usd").first()
    return (row[0], row[1]) if row else ("", None)


ENDED = ("done", "failed")


async def wait(run_id: str, ended: asyncio.Event, *, limit: float = LIMIT,
               over_cap=None) -> tuple[str, str]:
    """Wait for a beat's job: ("done" | "failed" | "waiting" | "limit" | "cap", why).

    Ends when the run says it ended (`ended`, set by `Heartbeat.run_finished`) or its row does;
    a job that stops on a question of its own is let go, since a beat never answers one."""
    until = time.monotonic() + limit
    while True:
        state, _cost = await asyncio.to_thread(run_state, run_id)
        if state in ENDED:
            return state, ""
        if state == "waiting":
            return "waiting", "It stopped on a question of its own, which no beat answers."
        left = until - time.monotonic()
        if left <= 0:
            return "limit", f"It ran past {int(limit // 60)} minutes and was stopped."
        if over_cap is not None:
            why = await over_cap()
            if why:
                return "cap", why
        try:
            await asyncio.wait_for(ended.wait(), timeout=min(LOOK, left))
        except asyncio.TimeoutError:
            pass


def mark_seen(run_id: str) -> None:
    """A beat's job is read by the heartbeat, so it leaves no dot on the run lists."""
    from . import owning

    if run_id:
        owning.mark_runs_seen([run_id])


def usual_cost(user_id: str, org_id: str, before_id: int | None = None):
    """What a beat's job usually costs: the median of the last ten that cost anything."""
    from decimal import Decimal

    rows = _models().HeartbeatBeat.objects.filter(user_id=user_id, org_id=org_id, kind="job",
                                                  cost__gt=0).exclude(status="skipped")
    if before_id is not None:
        rows = rows.filter(id__lt=before_id)
    costs = sorted(Decimal(c) for c in rows.order_by("-id").values_list("cost", flat=True)[:10])
    if len(costs) < 3:
        return None
    return costs[len(costs) // 2]


def dear_beat(user_id: str, org_id: str) -> dict | None:
    """The newest beat that cost at least `DEAR` times its usual, in the last day, or None."""
    from decimal import Decimal

    m = _models()
    last = (m.HeartbeatBeat.objects.filter(user_id=user_id, org_id=org_id, kind="job",
                                           started_at__gte=time.time() - 86400, cost__gt=0)
            .order_by("-id").first())
    if last is None:
        return None
    usual = usual_cost(user_id, org_id, last.id)
    if usual is None or usual <= 0 or Decimal(last.cost) < usual * DEAR:
        return None
    return {"beat": last.id, "cost": Decimal(last.cost), "usual": usual}
