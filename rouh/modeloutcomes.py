"""How each call to a model went, from what the person did next, kept here, and counted
once a day as anonymous totals for rouh.land.

Petar, 24 October 2026, the privacy fixes agreed that day, and what they decided here:

- **"Nothing happened within 5 minutes" is no longer a success.** Until then a call
  nothing was said against within `WINDOW` was counted `one_shot`, a success, and the
  success rates ranked models. Silence is not praise: a person who stops reading says
  nothing too. A call nobody did anything about is now only settled (`QUIET`), and
  counts as nothing either way.
- **The signals are kept as measurements for troubleshooting and reliability, apart
  from each other and from any ranking**: asked again (`repeated`), Redo, Stop
  (`stopped`), said it was wrong (`corrected`), rejected with a reason (`rejected`), a
  run that failed (`run_failed`), and beside them each call's cost, how long it took and
  how many of its requests the provider refused (`errors`). None of them ranks a model.
  What ranks models is the person's own vote in a blind comparison (`rouh/modelvotes.py`),
  which goes in the same daily payload (`votes`).
- **Sharing is its own toggle**, "Share anonymous totals with rouh.land" in Settings,
  Models (`modeldefaults.shares`), no longer part of Auto, and "See exactly what was
  sent" shows the payload as it was kept (`SENT`, `last_sent`), word for word.
- **rouh.land drops any model or use from fewer than 20 different installs** before it
  uses or shows it. So each payload carries one word that tells installs apart and says
  nothing else (`install`): a hash of a random secret this Rouh keeps, its organisation
  and the month, so it changes every month and cannot be followed from one to the next,
  and cannot be tied to a name, an address or anything rouh.land holds. rouh.land keeps no
  address of the sender for this route, and logs none (its `rouhit/outcomes_views.py`).
- **Sending stays a dry run** (`config.model_outcomes_send`, off) until Petar switches it
  on: every day the payload is made and kept as what would have been sent, and nothing
  leaves.

What follows is how calls are written down, unchanged since 18 October 2026.

Petar, 18 October 2026: "Record outcomes locally for every model call, keyed by
use, tier, model and effort. Use signals the system already has, with no extra
work for the user ... Store a small conclusion per call: use, model, effort,
outcome, cost, latency. Never store the request or the answer."

**A call** is what a person sees as one (`ModelOutcome`): a turn, with every
request it made to answer (`turn_id`), a run of the one program (`run-<id>`),
or one request of anything else (`req-<row>`). It is written from the log of
requests as each one ends (`request_done`, called by `llmlog`), so every call
Rouh makes is one, with its cost and how long it took, and none of its words.

**Its signals** come from what already happens: within `WINDOW` of it, the person
asks the same thing again in other words or the same (`heard`, `repeated`), presses
Redo (`redo`) or Stop (a request that ended "stopped"), says it was wrong (`heard`,
`corrected`), or rejects what a model made with a reason (`rejected`, Mutations'
Reject); and a run ends failed, unfinished, lost or refused (`run_ended`, `run_failed`).

Nothing the person said is kept: a new message is compared with the one before
it in the same chat while both are in memory, and only the signal is written.

**What leaves** (`payload`) is the day's totals per use, tier, model and level: how
many calls, how many of each signal, how many errors, the cost and the time; the
double calls' counts; and the votes. No words, no names, and nothing that says whose
Rouh it was. It goes to `config.model_outcomes_url` once a day for each organisation
that shares.

A turn on Auto (`rouh/modelrouter.py`) is written down before it starts, with the
tier the router picked, its reason, how long it took and what it cost (`note_route`),
and its counts are kept apart from a fixed tier's (`auto`), so the data shows how
Auto does. The reason stays here: what leaves is counts.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone

from .config import config as _config

log = logging.getLogger("rouh.modeloutcomes")

#: How long a call stays open to being found wanting: a question asked again,
#: Redo, Stop or a correction later than this is a new matter.
WINDOW = 5 * 60

#: How far back Redo reaches for the call it is about.
REDO_REACH = 60 * 60

#: The shape of what leaves, and how many days of counts it may carry at once. 3 since 24
#: October 2026: no success, no success rate, signals and errors as measurements, the votes,
#: and the month's install word.
PAYLOAD_SCHEMA = 3
#: What rouh.land takes as a model's name in the counts (rouhit/outcomes_views.py, _WORD): one
#: word that is not, and rouh.land refuses the whole day's counts.
MODEL_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
DAYS_KEPT = 7

#: What the last send said, kept for the Models page.
SENT = "model_outcomes_sent"

#: A call is pending while something may still be said against it, a failure once something
#: was, and quiet once the window passed with nothing: quiet is not a success. `SUCCESS` is
#: what a quiet call was called until 24 October 2026, and is read as quiet.
PENDING, SUCCESS, FAILURE, QUIET = "pending", "success", "failure", "quiet"
SIGNALS = ("repeated", "redo", "stopped", "corrected", "rejected", "run_failed")

#: A message that opens like this says the answer before it was wrong.
CORRECTION = re.compile(
    r"^\s*(no\b|nope\b|wrong\b|incorrect\b|that'?s (not|wrong|incorrect)\b|that is (not|wrong)\b|"
    r"not (what|right|correct|quite)\b|you (misunderstood|got (it|that) wrong|are wrong)\b|"
    r"actually,? (no|that'?s)\b|i (said|meant|asked for)\b|не\b|грешно\b|не е\b)",
    re.IGNORECASE)

#: The person's last words in each chat, and when, held in memory only.
_LAST: dict[str, tuple[str, float]] = {}
_LOCK = threading.Lock()


def _m():
    from .models import ModelOutcome

    return ModelOutcome


# --- writing calls down ---------------------------------------------------------------------

def request_done(fields: dict, done: dict, row_id, *, use: str = "") -> None:
    """One request to a model has ended: add it to its call. From the log's own
    thread (`llmlog.Entry._finish`); never raises into it."""
    try:
        _request_done(fields, done, row_id, use=use)
    except Exception:
        log.warning("a call's outcome could not be written down", exc_info=True)


#: The router's cost for a turn whose call is not written down yet, by the turn.
_ROUTER_COST: dict[str, float] = {}


def _router_done(fields: dict, done: dict) -> None:
    """The router's own request has ended: its cost goes on the call of the turn it
    chose for (`subject`), now or when that call is written (`note_route`)."""
    turn = str(fields.get("subject") or "")
    cost = done.get("cost_usd")
    cost = float(cost) if cost is not None else 0.0
    if not turn:
        return
    with _LOCK:
        M = _m()
        row = M.objects.filter(call=turn).first()
        if row is None:
            _ROUTER_COST[turn] = _ROUTER_COST.get(turn, 0.0) + cost
            return
        M.objects.filter(pk=row.pk).update(router_cost_usd=(row.router_cost_usd or 0.0) + cost)


def note_route(turn_id: str, *, session_id: str, use: str, org_id: str, decision) -> None:
    """A turn on Auto is about to start on the router's tier: its call is written
    down now, with what the router decided, before any of its requests. Never raises."""
    try:
        now = time.time()
        with _LOCK:
            cost = _ROUTER_COST.pop(turn_id, None)
            _m().objects.update_or_create(call=turn_id, defaults=dict(
                org_id=org_id, session_id=session_id, use=use, tier=decision.tier,
                model=decision.model, effort=decision.effort, started_at=now, auto=True,
                router_ok=bool(decision.ok), route_reason=decision.reason[:400],
                router_ms=int(decision.ms), router_cost_usd=cost))
    except Exception:
        log.warning("what the router decided could not be written down", exc_info=True)


def note_root(turn_id: str, root) -> None:
    """The exchange a turn is answering, once its question is written (`runtime.Turn`)."""
    try:
        if turn_id and root is not None:
            _m().objects.filter(call=turn_id).update(root=int(root))
    except Exception:
        log.warning("a call's exchange could not be written down", exc_info=True)


def last_tier(session_id: str) -> str:
    """The tier the last routed turn of this chat answered on, or ""."""
    try:
        row = (_m().objects.filter(session_id=session_id, auto=True)
               .order_by("-started_at").values_list("tier", flat=True).first())
        from .modelstandard import tier_id

        return tier_id(row)
    except Exception:
        return ""


def routes_of(session_id: str, roots) -> dict[int, dict]:
    """What Auto decided for each of these exchanges of a chat, the latest try's,
    for an answer from before its "Model decision" line was kept whole (`RouteTimeline`,
    `memory.Memory.transcript`)."""
    from .config import model_name
    from .modeldefaults import TIER_NAMES

    roots = [int(r) for r in roots if r is not None]
    if not roots:
        return {}
    out: dict[int, dict] = {}
    rows = (_m().objects.filter(session_id=session_id, auto=True, root__in=roots)
            .order_by("started_at").values("root", "tier", "model", "route_reason", "router_ok",
                                           "router_ms"))
    for r in rows:
        timed_out = not r["router_ok"] and "too long" in (r["route_reason"] or "")
        out[int(r["root"])] = {"tier": r["tier"], "tier_name": TIER_NAMES.get(r["tier"], r["tier"]),
                               "model": r["model"], "model_name": model_name(r["model"]),
                               "reason": r["route_reason"], "auto": True,
                               "outcome": "picked" if r["router_ok"] else "timeout" if timed_out else "error",
                               "decided_ms": r["router_ms"]}
    return out


def _request_done(fields: dict, done: dict, row_id, *, use: str = "") -> None:
    from . import modeldefaults

    purpose = str(fields.get("purpose") or "")
    if purpose in ("router", "router_decisions", "router_question"):
        _router_done(fields, done)
        return
    session = str(fields.get("session_id") or "")
    # A turn knows its own use when it is a case's, read where it asked (`llmlog._case_use`).
    use = (use if purpose == "turn" and use else "") or modeldefaults.use_of(purpose, session)
    if not use or done.get("status") not in ("ok", "stopped", "error"):
        return
    failed = done.get("status") == "error"
    org = str(fields.get("org_id") or "") or modeldefaults.org_now()
    turn = str(fields.get("turn_id") or "")
    call = turn or f"req-{row_id}"
    started = float(fields.get("started_at") or time.time())
    ended = float(done.get("finished_at") or time.time())
    cost = done.get("cost_usd")
    cost = float(cost) if cost is not None else 0.0
    model = str(done.get("served_model") or fields.get("model") or "")
    M = _m()
    got = M.objects.filter(call=call).first()
    if got is None:
        try:
            tier = modeldefaults.use_tier(use, org)
            if purpose == "turn":
                # A chat set to Cheap, Smart or Auto beside the composer is on that, whatever
                # the Models page says (`chatkinds.own_choice`).
                from . import chatkinds

                own = chatkinds.own_choice(session)
                if own:
                    tier = chatkinds.CHOICE_TIER.get(own, modeldefaults.AUTO)
        except Exception:
            tier = ""
        got = M.objects.create(
            org_id=org, user_id=str(fields.get("user_id") or ""), call=call, session_id=session,
            use=use, tier=tier if tier != modeldefaults.OFF else "", model=str(fields.get("model") or model),
            effort=str(fields.get("effort") or ""), requests=1, cost_usd=cost,
            latency_ms=max(0, int((ended - started) * 1000)), started_at=started, ended_at=ended,
            errors=1 if failed else 0)
    else:
        first = min(got.started_at, started)
        last = max(got.ended_at or ended, ended)
        M.objects.filter(pk=got.pk).update(
            requests=got.requests + 1, cost_usd=(got.cost_usd or 0.0) + cost,
            started_at=first, ended_at=last, latency_ms=max(0, int((last - first) * 1000)),
            errors=(got.errors or 0) + (1 if failed else 0))
    # An answer cut off before it ended was stopped by the person: Stop, or talking
    # over it (`llmlog.Entry.end`, "stopped").
    if done.get("status") == "stopped" and got.outcome == PENDING:
        _fail(got, "stopped")


def _fail(row, signal: str) -> bool:
    if row is None:
        return False
    _m().objects.filter(pk=row.pk).update(outcome=FAILURE, signal=signal, settled_at=time.time())
    log.info("call %s on %s (%s) counted a failure: %s", row.call, row.model, row.use, signal)
    return True


def _latest_turn(session_id: str, reach: float):
    if not session_id:
        return None
    since = time.time() - reach
    return (_m().objects.filter(session_id=session_id, use__in=("general", "chats", "heartbeat_decide", "case_read"),
                                started_at__gte=since)
            .exclude(call__startswith="req-").order_by("-started_at").first())


# --- the signals ----------------------------------------------------------------------------

def _words(value) -> str:
    """The text of what was said, from a string or a list of content blocks."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(str(b.get("text") or "") for b in value
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def same_ask(before: str, now: str) -> bool:
    """Whether two messages ask the same thing: the same words, or nearly."""
    a, b = _tokens(before), _tokens(now)
    if len(a) < 3 or len(b) < 3:
        return False
    if difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() >= 0.75:
        return True
    shared = len(set(a) & set(b)) / max(1, len(set(a) | set(b)))
    return shared >= 0.6


def heard(session_id: str, said) -> str:
    """The person said something in this chat: the call before it is a failure if
    this asks it again or says it was wrong. Gives back the signal, or "".
    Never raises."""
    text = _words(said).strip()
    now = time.time()
    with _LOCK:
        before = _LAST.get(session_id)
        _LAST[session_id] = (text, now)
        if len(_LAST) > 500:
            for key in sorted(_LAST, key=lambda k: _LAST[k][1])[:100]:
                _LAST.pop(key, None)
    if not text:
        return ""
    try:
        row = _latest_turn(session_id, WINDOW)
        if row is None or row.outcome != PENDING or (row.ended_at or now) < now - WINDOW:
            return ""
        if CORRECTION.match(text):
            return "corrected" if _fail(row, "corrected") else ""
        if before is not None and now - before[1] <= WINDOW + 600 and same_ask(before[0], text):
            return "repeated" if _fail(row, "repeated") else ""
    except Exception:
        log.warning("what was said after a call could not be weighed", exc_info=True)
    return ""


def redo(session_id: str) -> bool:
    """Redo was pressed on an answer in this chat."""
    try:
        return _fail(_latest_turn(session_id, REDO_REACH), "redo")
    except Exception:
        log.warning("a Redo could not be counted", exc_info=True)
        return False


def rejected(call: str, *, org_id: str, use: str, model: str = "", effort: str = "") -> bool:
    """A result of a model's was rejected with a reason (principle C1): its call is a
    failure, written down now if it was not yet."""
    try:
        M = _m()
        row = M.objects.filter(call=call).first()
        if row is None:
            now = time.time()
            M.objects.create(org_id=org_id, call=call, use=use, model=model or "", effort=effort,
                             outcome=FAILURE, signal="rejected", started_at=now, ended_at=now,
                             settled_at=now)
            return True
        return _fail(row, "rejected")
    except Exception:
        log.warning("a rejection could not be counted", exc_info=True)
        return False


#: A run's end, by the one program's word for it: one that ended done is only quiet.
RUN_ENDS = {"done": QUIET, "failed": FAILURE, "unfinished": FAILURE, "lost": FAILURE,
            "refused": FAILURE}


def run_ended(run: dict) -> None:
    """A run of the one program changed: once it has ended, it is a call of its own,
    a success or a failure by how it ended. Never raises."""
    state = str(run.get("state") or "").strip().lower()
    outcome = RUN_ENDS.get(state)
    run_id = str(run.get("id") or "")
    if outcome is None or not run_id:
        return
    try:
        from . import modeldefaults, modelstandard

        M = _m()
        call = f"run-{run_id}"
        row = M.objects.filter(call=call).first()
        if row is not None and row.outcome != PENDING:
            return
        use = _run_use(run_id, str(run.get("engine") or "") == "codex")
        org = modeldefaults.org_now()
        # The run's own model when it says one plainly; a run record once said "claude [cut]",
        # which made rouh.land refuse every day's counts after it (23 October 2026).
        model = str(run.get("model") or "").strip()
        if not MODEL_ID.match(model):
            model = modeldefaults.use_model(use, org)
        effort = str(run.get("effort") or "") or modelstandard.effort(model)
        started = _epoch(run.get("requested_at")) or time.time()
        ended = _epoch(run.get("ended_at")) or time.time()
        fields = dict(outcome=outcome, signal="" if outcome == QUIET else "run_failed",
                      settled_at=time.time(), ended_at=ended)
        if row is None:
            M.objects.create(org_id=org, call=call, use=use, tier=modeldefaults.use_tier(use, org),
                             model=model, effort=effort, requests=0, started_at=started,
                             latency_ms=max(0, int((ended - started) * 1000)), **fields)
        else:
            M.objects.filter(pk=row.pk).update(**fields)
    except Exception:
        log.warning("a run's outcome could not be written down", exc_info=True)


def _run_use(run_id: str, codex: bool) -> str:
    """Which use a run was started for: a night's own, or a code run of either engine."""
    from .models import NightlyFeatureNight, NightlyRefactorNight

    if NightlyFeatureNight.objects.filter(run_id=run_id).exists():
        return "nightly_feature_run"
    if NightlyRefactorNight.objects.filter(run_id=run_id).exists():
        return "nightly_refactor_run"
    return "codex_runs" if codex else "code_runs"


def _epoch(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def settle(now: float | None = None) -> int:
    """Every call that nothing found wanting within the window is settled as quiet: counted,
    and never as a success (Petar, 24 October 2026)."""
    now = time.time() if now is None else now
    return _m().objects.filter(outcome=PENDING, ended_at__lt=now - WINDOW).exclude(
        call__startswith="run-").update(outcome=QUIET, signal="", settled_at=now)


# --- what leaves ----------------------------------------------------------------------------

def _day(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d")


#: Where this Rouh's secret for the install word is kept (`install_word`).
INSTALL = "model_outcomes_install"


def install_word(org_id: str, now: float | None = None) -> str:
    """The one word in the payload that tells installs apart, so rouh.land can leave out what
    fewer than 20 of them sent: a hash of a random secret kept here, the organisation and the
    month (UTC). It changes every month, so two months cannot be put together, and it is tied
    to nothing rouh.land knows."""
    import hashlib
    import secrets as _secrets

    from .models.memory import AppState

    now = time.time() if now is None else now
    try:
        raw = AppState.objects.filter(key=INSTALL).values_list("value", flat=True).first()
        secret = (json.loads(raw) or {}).get("secret") if raw else ""
        if not secret:
            secret = _secrets.token_hex(32)
            AppState.objects.update_or_create(key=INSTALL, defaults={"value": json.dumps({"secret": secret})})
    except Exception:
        log.warning("the install word's secret could not be kept", exc_info=True)
        return ""
    month = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")
    return hashlib.sha256(f"{secret}:{org_id}:{month}".encode()).hexdigest()[:32]


def payload(org_id: str, cfg=None, *, now: float | None = None) -> dict:
    """The totals that would leave for this organisation now: every settled call of the
    last `DAYS_KEPT` days not yet sent, as counts per day, use, tier, model and level, the
    double calls and the votes. Nothing anybody said, and nothing that says whose."""
    from . import modelstandard, modelvotes

    now = time.time() if now is None else now
    since = now - DAYS_KEPT * 86400
    rows = (_m().objects.filter(org_id=org_id, counted_on="", settled_at__isnull=False,
                                started_at__gte=since).exclude(outcome=PENDING)
            .values("use", "tier", "model", "effort", "outcome", "signal", "cost_usd",
                    "latency_ms", "started_at", "auto", "router_ok", "router_ms",
                    "router_cost_usd", "errors"))
    groups: dict[tuple, dict] = {}
    for r in rows:
        # Today's tier names (Daily and Best are Smart since 23 October 2026), and a model
        # written down as something that is not a model's id counted as "unknown", so one
        # such call never stops the rest of the day's counts from being taken.
        model = r["model"] if MODEL_ID.match(r["model"] or "") else "unknown"
        key = (_day(r["started_at"]), r["use"], modelstandard.tier_id(r["tier"]), model, r["effort"],
               bool(r["auto"]))
        g = groups.setdefault(key, {"calls": 0, "signals": {}, "errors": 0, "cost": 0.0,
                                    "latencies": [], "router_cost": 0.0, "router_ms": [],
                                    "fallbacks": 0})
        if r["auto"]:
            g["router_cost"] += float(r["router_cost_usd"] or 0.0)
            if r["router_ms"] is not None:
                g["router_ms"].append(int(r["router_ms"]))
            if not r["router_ok"]:
                g["fallbacks"] += 1
        g["calls"] += 1
        if r["outcome"] == FAILURE and r["signal"] in SIGNALS:
            g["signals"][r["signal"]] = g["signals"].get(r["signal"], 0) + 1
        g["errors"] += int(r["errors"] or 0)
        g["cost"] += float(r["cost_usd"] or 0.0)
        if r["latency_ms"] is not None:
            g["latencies"].append(int(r["latency_ms"]))
    out = []
    for (day, use, tier, model, effort, auto), g in sorted(groups.items()):
        lat = sorted(g["latencies"])
        row = {"day": day, "use": use, "tier": tier, "model": model, "effort": effort,
               "auto": auto, "calls": g["calls"],
               "signals": dict(sorted(g["signals"].items())), "errors": g["errors"],
               "cost_usd": round(g["cost"], 4),
               "cost_per_call_usd": round(g["cost"] / g["calls"], 5),
               "latency_ms_median": lat[len(lat) // 2] if lat else None}
        if auto:
            # The router's own part, so Auto's cost is whole: what choosing cost, how
            # long it took, and how often it fell back to Smart.
            ms = sorted(g["router_ms"])
            row.update(router_cost_usd=round(g["router_cost"], 5),
                       router_ms_median=ms[len(ms) // 2] if ms else None,
                       router_fallbacks=g["fallbacks"])
        out.append(row)
    return {"schema": PAYLOAD_SCHEMA, "kind": "rouh.model-outcomes",
            "standard": modelstandard.current().get("revision"),
            "made": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "install": install_word(org_id, now),
            "rows": out, "doubles": doubles(org_id, since), "votes": modelvotes.totals(org_id, since)}


# --- double calls ------------------------------------------------------------------------------

def _d():
    from .models import ModelDouble

    return ModelDouble


def note_double(use: str, first, second, judge, winner: str, org_id: str | None) -> None:
    """Keep one double call's conclusion (`rouh/llm.py`): the use, both models and levels,
    which won, and what each part cost and took. Never what was asked or answered."""
    from . import costs, modeldefaults

    def cost(answer) -> float | None:
        return costs.request_cost(answer.usage, answer.model) if answer.usage else None

    _d().objects.create(org_id=org_id or modeldefaults.org_now(), use=use,
                        first_model=first.model, first_effort=first.effort or "",
                        second_model=second.model, second_effort=second.effort or "",
                        winner=winner, first_cost_usd=cost(first), second_cost_usd=cost(second),
                        judge_cost_usd=cost(judge), first_ms=first.ms, second_ms=second.ms,
                        at=time.time())


def doubles(org_id: str, since: float) -> list[dict]:
    """Double calls not yet sent, as counts per day, use and pair of models."""
    groups: dict[tuple, dict] = {}
    for r in (_d().objects.filter(org_id=org_id, counted_on="", at__gte=since)
              .values("use", "first_model", "first_effort", "second_model", "second_effort",
                      "winner", "first_cost_usd", "second_cost_usd", "judge_cost_usd",
                      "first_ms", "second_ms", "at")):
        key = (_day(r["at"]), r["use"], r["first_model"], r["first_effort"], r["second_model"],
               r["second_effort"])
        g = groups.setdefault(key, {"calls": 0, "first": 0, "second": 0, "same": 0, "c1": 0.0,
                                    "c2": 0.0, "cj": 0.0, "m1": [], "m2": []})
        g["calls"] += 1
        g[r["winner"] if r["winner"] in ("first", "second", "same") else "same"] += 1
        g["c1"] += float(r["first_cost_usd"] or 0)
        g["c2"] += float(r["second_cost_usd"] or 0)
        g["cj"] += float(r["judge_cost_usd"] or 0)
        for k, f in (("m1", "first_ms"), ("m2", "second_ms")):
            if r[f] is not None:
                g[k].append(int(r[f]))
    out = []
    for (day, use, m1, e1, m2, e2), g in sorted(groups.items()):
        def median(xs):
            xs = sorted(xs)
            return xs[len(xs) // 2] if xs else None
        out.append({"day": day, "use": use, "first_model": m1, "first_effort": e1,
                    "second_model": m2, "second_effort": e2, "calls": g["calls"],
                    "first_won": g["first"], "second_won": g["second"], "same": g["same"],
                    "first_cost_usd": round(g["c1"], 5), "second_cost_usd": round(g["c2"], 5),
                    "judge_cost_usd": round(g["cj"], 5),
                    "first_ms_median": median(g["m1"]), "second_ms_median": median(g["m2"])})
    return out


def double_spend(org_id: str, now: float | None = None) -> dict:
    """What double calls added this calendar month (UTC): the second answers and the judge."""
    now = time.time() if now is None else now
    month = datetime.fromtimestamp(now, timezone.utc).replace(day=1, hour=0, minute=0, second=0,
                                                              microsecond=0).timestamp()
    rows = _d().objects.filter(org_id=org_id, at__gte=month).values_list(
        "second_cost_usd", "judge_cost_usd")
    calls, spent = 0, 0.0
    for second, judge in rows:
        calls += 1
        spent += float(second or 0) + float(judge or 0)
    return {"calls": calls, "usd": round(spent, 4)}


def preview(org_id: str, cfg=None) -> dict:
    """What the Models page shows behind the (i) beside the switch: exactly what
    would leave today, where to, whether it would really be sent, and the last send."""
    cfg = cfg or _config
    settle()
    from . import modeldefaults

    return {"payload": payload(org_id, cfg), "url": cfg.model_outcomes_url,
            "sending": bool(cfg.model_outcomes_send), "on": modeldefaults.shares(org_id),
            "compare": modeldefaults.compares(org_id),
            "last": _sent_state().get(org_id) or None,
            "double_rate": modeldefaults.double_rate(org_id),
            "double_spend": double_spend(org_id)}


def _sent_state() -> dict:
    try:
        from .models.memory import AppState

        raw = AppState.objects.filter(key=SENT).values_list("value", flat=True).first()
        got = json.loads(raw) if raw else {}
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}


def last_sent(org_id: str) -> dict:
    """Exactly what this organisation last sent, or kept as what would have been sent: the
    payload as it was made, word for word, and when; nothing added to it."""
    last = _sent_state().get(org_id) or {}
    if not last:
        return {"said": "Nothing has been made yet: the first day's totals are made once a day.",
                "payload": None}
    mode = last.get("mode") or ""
    said = {"sent": "Sent to rouh.land", "dry-run": "Made and kept here, not sent: sending is not on yet",
            "off": "Not made: sharing the totals is off", "nothing": "Nothing to send that day",
            "failed": "Made, and the send did not reach rouh.land"}.get(mode, mode)
    when = datetime.fromtimestamp(float(last.get("at") or 0), timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return {"said": f"{said}, {when}.", "url": last.get("url") or "", "payload": last.get("payload")}


def _keep_sent(org_id: str, said: dict) -> None:
    from .models.memory import AppState

    state = _sent_state()
    state[org_id] = said
    AppState.objects.update_or_create(key=SENT, defaults={"value": json.dumps(state)})


def due(org_id: str, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    last = _sent_state().get(org_id) or {}
    return now - float(last.get("at") or 0) >= 23.5 * 3600


#: The most one post may weigh: rouh.land's front door takes 64 KB a request.
MOST_BYTES = 60 * 1024


def parts(body: dict) -> list[dict]:
    """The payload as posts of at most `MOST_BYTES` each, rows, double calls and votes split
    between them; each is a whole payload of its own."""
    def size(b: dict) -> int:
        return len(json.dumps(b).encode())

    if size(body) <= MOST_BYTES:
        return [body]
    head = {k: v for k, v in body.items() if k not in ("rows", "doubles", "votes")}
    out, now = [], {**head, "rows": [], "doubles": [], "votes": []}
    for key in ("rows", "doubles", "votes"):
        for row in body.get(key) or []:
            now[key].append(row)
            if size(now) > MOST_BYTES and (len(now["rows"]) + len(now["doubles"]) + len(now["votes"])) > 1:
                now[key].pop()
                out.append(now)
                now = {**head, "rows": [], "doubles": [], "votes": []}
                now[key].append(row)
    out.append(now)
    return out


def send(org_id: str, cfg=None, *, now: float | None = None) -> dict:
    """Send the day's counts for this organisation, or, while sending is off, make
    them and keep them as what would have been sent. Never raises; gives back what
    was written down about it."""
    import httpx

    from . import modeldefaults

    cfg = cfg or _config
    now = time.time() if now is None else now
    settle(now)
    said: dict = {"at": now, "url": cfg.model_outcomes_url}
    if not modeldefaults.shares(org_id):
        said.update(mode="off")
        _keep_sent(org_id, said)
        return said
    body = payload(org_id, cfg, now=now)
    said["rows"] = len(body["rows"])
    if not cfg.model_outcomes_send or not cfg.model_outcomes_url:
        said.update(mode="dry-run", payload=body)
        _keep_sent(org_id, said)
        log.info("model outcomes for %s: a dry run, %d row(s) kept as what would have been sent",
                 org_id, said["rows"])
        return said
    if not body["rows"] and not body["doubles"] and not body["votes"]:
        said.update(mode="nothing")
        _keep_sent(org_id, said)
        return said
    try:
        with httpx.Client(timeout=20.0) as client:
            for part in parts(body):
                r = client.post(cfg.model_outcomes_url, json=part,
                                headers={"User-Agent": "Rouh model outcomes/3"})
                if r.status_code >= 300:
                    raise RuntimeError(f"HTTP {r.status_code}")
    except Exception as exc:
        said.update(mode="failed", error=f"{type(exc).__name__}: {exc}"[:300])
        _keep_sent(org_id, said)
        log.info("model outcomes for %s could not be sent: %s", org_id, said["error"])
        return said
    since = now - DAYS_KEPT * 86400
    _m().objects.filter(org_id=org_id, counted_on="", settled_at__isnull=False,
                        started_at__gte=since).exclude(outcome=PENDING).update(counted_on=_day(now))
    _d().objects.filter(org_id=org_id, counted_on="", at__gte=since).update(counted_on=_day(now))
    from . import modelvotes

    modelvotes.counted(org_id, since, _day(now))
    # Kept whole, so "See exactly what was sent" shows what left, word for word.
    said.update(mode="sent", payload=body)
    _keep_sent(org_id, said)
    log.info("model outcomes for %s sent: %d row(s)", org_id, said["rows"])
    return said


def orgs() -> list[str]:
    """Every organisation with calls written down."""
    return list(_m().objects.values_list("org_id", flat=True).distinct())


def tick(cfg=None) -> None:
    """The daily beat (`runtime._model_standard_loop`): the standard fetched when it
    is due, calls settled, and each organisation's counts sent when they are due."""
    from . import modeldefaults, modelstandard

    cfg = cfg or _config
    if modelstandard.due():
        before = modelstandard.current().get("revision")
        modelstandard.fetch(cfg)
        if modelstandard.current().get("revision") != before:
            modeldefaults.publish_merge_pick(None, cfg)
    settle()
    for org in orgs():
        if due(org):
            send(org, cfg)
