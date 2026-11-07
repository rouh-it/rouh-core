"""What happens next on a quest, worked out in one place, and Check now: one beat on it.

Petar, 6 October 2026, looking at goal 89 the night he handed Rouh the content for it:
step 9 was complete with his Drive link, step 10 was the quest's and still said Not
started, and the quest's notebook still said the content was missing. "nothing makes that
obivous for me. what would be the best place to know that in terms of UI. has to be on
hte goals map. but also on the quest I guess. and I have to have an option to 'heartbeat'
once, no?"

So this is the one calculation of a quest's execution, read from the state the heartbeat
itself acts on (`heartbeat.Heartbeat._tick` and `_skip_because`), and never from what a
beat once wrote in the notebook:

- `state`: who executes it (its beats, never a goal run), a check queued or running now,
  what stops automatic checks (the heartbeat or the quest paused, its budget, the daily
  cap), what only delays them (quiet hours, working hours, a next look the quest set
  itself, a full beat less than `skip.nothing_new_hours` ago), its last check and what it
  found, and the earliest time an automatic check may run, which is never a promise. The
  quest's page draws its What happens next from it, and the goal map its steps.
- `steps`: each goal step that is the quest's, as the goal map draws it: blocked on a
  step before it in its stream, or ready and waiting on the quest's beats, and whether a
  step before it was completed after the quest's last full check, which makes what that
  check found out of date (`news`). The same words go into every beat's note
  (`quests.goal_lines`), so the next check sees the new evidence too.
- `ask`: Check now. One beat on the quest, asked for by the owner: a row of `heartbeat_beats`
  with status queued, made under a lock on the quest's record, so a double press or a
  second tab gets the check already asked for rather than a second one. The heartbeat's
  loop runs it (`Heartbeat._tick`), as trigger "now", even in quiet hours, with the
  quest's budget, the daily cap, the approval queue and every other rule of a beat as
  they are. A paused quest, or a paused heartbeat, is checked once only when he says so
  (`while_paused`), and stays paused.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from decimal import Decimal

from . import clock, owner

log = logging.getLogger("rouh.questcheck")

#: A check asked for and not started within this long has failed: Rouh was busy all along.
QUEUE_MOST = 30 * 60
#: The states of a beat row that mean a check is asked for or under way.
LIVE = ("queued", "running")
#: The most of the last full check's words, and of the owner's words on a step before it.
SAID_MOST = 600
NOTE_MOST = 1200


class Refused(ValueError):
    """Why a check cannot be asked for now, in a sentence."""


class NeedsYes(Refused):
    """The quest or the heartbeat is paused: a check runs only if the owner says to check it once."""


def _models():
    from . import models

    return models


def _whose(row) -> dict:
    return {"user_id": str(row.user_id), "org_id": str(row.org_id)}


# --- times, said ------------------------------------------------------------------------


def at_words(ts: float, now: float | None = None) -> str:
    """"today 08:00", "tomorrow 06:12" or "Wed 7 Oct 06:12", on the person's clock."""
    if not ts:
        return ""
    now = time.time() if now is None else now
    moment, today = clock.moment(ts), clock.moment(now)
    hhmm = moment.strftime("%H:%M")
    if moment.date() == today.date():
        return f"today {hhmm}"
    if moment.date() == (today + timedelta(days=1)).date():
        return f"tomorrow {hhmm}"
    if moment.date() == (today - timedelta(days=1)).date():
        return f"yesterday {hhmm}"
    return moment.strftime("%a %-d %b ") + hhmm


def full_words(ts: float, now: float | None = None) -> str:
    """"Tue 6 Oct, 08:00": a real date and time, for a time that matters."""
    if not ts:
        return ""
    moment = clock.moment(ts)
    return moment.strftime("%a %-d %b, %H:%M")


def _span(seconds: float) -> str:
    minutes = max(0, int(round(seconds / 60)))
    if minutes < 1:
        return "under a minute"
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    return f"{hours // 24} days"


def _clean(text: str, most: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


# --- the heartbeat's own rules, read once ------------------------------------------------


def _heart(who):
    """The heartbeat's row (never None once asked) and its settings."""
    from . import heartbeat

    row = heartbeat.ensure(who)
    return row, heartbeat.config_of(row)


def _local_from(ts: float):
    return clock.moment(ts)


def _push_out_of_quiet(ts: float, cfg: dict) -> float:
    """The first moment from `ts` that is not in quiet hours, in which nothing beats."""
    from . import heartbeat

    hours = cfg["hours"]
    if not hours["quiet_on"]:
        return ts
    local = _local_from(ts)
    if heartbeat.within(local, hours["quiet_from"], hours["quiet_to"]):
        return ts + heartbeat.until(local, hours["quiet_to"])
    return ts


def _push_into_work(ts: float, cfg: dict) -> float:
    """The first moment from `ts` inside working hours, where the timer beats."""
    from . import heartbeat

    hours = cfg["hours"]
    local = _local_from(ts)
    if heartbeat.within(local, hours["work_from"], hours["work_to"]):
        return ts
    return ts + heartbeat.until(local, hours["work_from"])


def _timer_at(work, cfg: dict, interval: float, now: float, waiting: bool) -> float:
    """When the regular timer may next give the quest a full beat, as `_tick` and
    `_skip_because` would: inside working hours, out of quiet hours, and, with nothing new
    and nothing due, not until `nothing_new_hours` after its last full beat."""
    at = (work.last_beat_at or work.created_at or now) + interval
    if not work.last_beat_at:
        at = (work.created_at or now) + 60
    at = max(at, now)
    skip = cfg["skip"]
    quiet_until = (work.last_full_at + skip["nothing_new_hours"] * 3600
                   if skip["nothing_new"] and work.last_full_at and not waiting else 0)
    for _ in range(400):
        moved = _push_out_of_quiet(_push_into_work(at, cfg), cfg)
        if moved != at:
            at = moved
            continue
        if quiet_until and at < quiet_until:
            # Each look before then is skipped as "nothing new", one interval apart.
            at += interval * max(1, int((quiet_until - at) // interval))
            if at < quiet_until:
                at += interval
            continue
        break
    return at


def _midnight_after(now: float) -> float:
    local = clock.moment(now)
    return (local.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)).timestamp() + 5


# --- the beats on it ----------------------------------------------------------------------


def _beat_view(b, now: float) -> dict:
    """One beat on the quest as both pages say it."""
    took = (b.finished_at or now) - (b.started_at or now)
    asked = next((e for e in (b.events or []) if isinstance(e, dict) and e.get("kind") == "asked"),
                 None)
    if b.status == "queued":
        words = "Queued: it starts within a minute, or as soon as Rouh's current turn ends."
    elif b.status == "running":
        words = f"Checking now, for {_span(took)} so far."
    elif b.status == "skipped":
        words = "Not run: " + (b.reason or "skipped.")
    elif b.status == "failed":
        words = "Failed: " + (b.reason or "it did not finish.")
    else:
        words = {"nothing": "Checked, and ended with nothing to do",
                 "note": "Checked, and left a note", "telegram": "Checked, and messaged you"
                 }.get(b.outcome or "", "Checked")
        words += (": " + _clean(b.said, SAID_MOST)) if b.said else "."
    return {"id": b.id, "status": b.status, "trigger": b.trigger, "asked": asked is not None,
            "at": b.started_at, "when": at_words(b.started_at, now),
            "full_when": full_words(b.started_at, now),
            "ended": at_words(b.finished_at, now) if b.finished_at else "",
            "words": words, "said": _clean(b.said, SAID_MOST),
            "cost": f"${Decimal(b.cost):,.2f}" if b.cost is not None else ""}


def _beats(work) -> dict:
    m = _models()
    rows = m.HeartbeatBeat.objects.filter(**_whose(work), work_id=work.id)
    live = rows.filter(status__in=LIVE).order_by("-id").first()
    last = rows.exclude(status__in=LIVE).order_by("-id").first()
    full = rows.filter(status__in=("done", "failed")).order_by("-id").first()
    # The last check that finished: only it can have seen what came before it.
    done = rows.filter(status="done").order_by("-id").first()
    costs = [c for c in rows.filter(status="done").exclude(cost=None).order_by("-id")
             .values_list("cost", flat=True)[:5]]
    # The beat that set its own next look last (`heartbeat_next`), and when it ran.
    setter = next((b for b in rows.filter(status__in=("done", "failed")).order_by("-id")[:20]
                   if any(isinstance(t, dict) and t.get("name") == "heartbeat_next"
                          for t in (b.tools or []))), None)
    return {"live": live, "last": last, "full": full, "done": done,
            "deferred_at": setter.started_at if setter is not None else 0.0,
            "cost": (sum(costs, Decimal(0)) / len(costs)) if costs else None}


# --- the quest's goal steps -----------------------------------------------------------------


def _goal_of(work):
    """The quest's task when it is also a goal (`rouh/goals.py`), else None."""
    from . import goals, quests

    task = quests.task_of(work)
    folder = goals._folder(task) if task is not None else None
    if folder is None or not goals.is_goal(goals._meta(folder)):
        return None
    return task


def _done_at(step_id: str) -> tuple[float, str]:
    """When a step was last made complete, and by whom, from its record of changes."""
    from . import taskrecord

    try:
        for change in taskrecord.history(step_id, limit=20):
            if change["field"] == "status" and change["new"] == "done":
                return float(change["at"] or 0), str(change["by"] or "")
    except Exception:
        log.exception("when step %s was completed could not be read", step_id)
    return 0.0, ""


_LINK = re.compile(r"https?://[^\s<>\"')\]]+")


def _evidence(s: dict) -> dict:
    """What a completed step before a quest step handed on: the owner's words on it, their choice,
    the links in them, and the files made in it."""
    note = str(s.get("note") or "").strip()
    links = _LINK.findall(note + " " + str(s.get("choice") or ""))
    files = [f["name"] for f in (s.get("prepared") or {}).get("files", [])][:6]
    return {"note": note[:NOTE_MOST] + ("…" if len(note) > NOTE_MOST else ""),
            "choice": str(s.get("choice") or ""), "links": links[:6], "files": files}


def steps(work, v: dict | None = None, *, last_full_at: float = 0.0,
          now: float | None = None) -> list[dict]:
    """Each goal step that is the quest's and not complete: blocked on a step before it,
    or ready for the quest's beats, with what a completed step before it handed on and
    whether that came after the quest's last full check."""
    from . import goals

    now = time.time() if now is None else now
    if v is None:
        task = _goal_of(work)
        if task is None:
            return []
        try:
            v = goals.view(task)
        except Exception:
            log.exception("the goal of quest %s could not be read", work.task_number)
            return []
    flat = goals._flat(v["steps"])
    by_id = {s["id"]: s for s in flat}
    out = []
    for lane in v["streams"]:
        order = [by_id[i] for i in lane["steps"] if i in by_id]
        for at, top in enumerate(order):
            for s in [top, *goals._flat(top["parts"])]:
                if s["who"] != goals.QUEST or (s["status"] == "done" and not s["hollow"]):
                    continue
                before = order[:at]
                open_before = [b for b in before if b["status"] != "done" or b["hollow"]]
                run = s.get("run") or {}
                after = by_id.get(run.get("after") or "") if run.get("mode") == "after" else None
                if after is not None and (after["status"] != "done" or after["hollow"]):
                    open_before = [after] + [b for b in open_before if b is not after]
                done_before = next((b for b in reversed(before)
                                    if b["status"] == "done" and not b["hollow"]), None)
                one = {"id": s["id"], "n": s["n"], "title": s["title"], "status": s["status"],
                       "stream": lane["name"], "goal_page": v["address"],
                       "href": v["address"] + "#step-" + s["id"]}
                if open_before:
                    b = open_before[0]
                    one["blocked_by"] = {"id": b["id"], "n": b["n"], "title": b["title"],
                                         "who_words": b["who_words"],
                                         "label": (b.get("needs") or {}).get("label") or "",
                                         "href": v["address"] + "#step-" + b["id"]}
                if done_before is not None:
                    when, by = _done_at(done_before["id"])
                    one["after"] = {"id": done_before["id"], "n": done_before["n"],
                                    "title": done_before["title"], "at": when,
                                    "when": full_words(when, now) if when else "",
                                    "by": "you" if done_before.get("done_by") == "person"
                                    else "Rouh",
                                    "changed_by": by,
                                    **_evidence(done_before)}
                    one["news"] = bool(when and when > (last_full_at or 0)) and not open_before
                out.append(one)
    return out


def news_lines(work, v: dict | None = None) -> list[str]:
    """What a beat on the quest is told about its goal steps that a step before them made
    ready, in words (`quests.goal_lines`): which step was completed, when, by whom, and
    what was handed on there."""
    lines = []
    for one in steps(work, v, last_full_at=work.last_full_at or 0):
        after = one.get("after")
        if one.get("blocked_by") or not after:
            continue
        said = (f"Step {one['n']} “{one['title']}” is yours and ready: step {after['n']} "
                f"“{after['title']}” before it was completed"
                + (f" on {after['when']}" if after["when"] else "")
                + f" by {'‹owner›' if after['by'] == 'you' else 'Rouh'}.")
        if after["note"]:
            said += f" What ‹owner› wrote there: “{after['note']}”"
        if after["choice"]:
            said += f" ‹He› chose: {after['choice']}."
        if after["files"]:
            said += " Files in that step: " + ", ".join(after["files"]) + "."
        if one.get("news"):
            said += (" This came after the last full beat on the quest, so anything the "
                     "notebook says about it being missing or waiting is out of date: "
                     "start from it.")
        lines.append(said)
    return lines


# --- the state ----------------------------------------------------------------------------


def state(who, work, *, now: float | None = None, v: dict | None = None,
          with_steps: bool = True) -> dict:
    """Where the quest's work stands and what happens next: see the module's words.
    `with_steps` False leaves its goal steps out, for a list of quests."""
    with clock.person(who):
        return _state(who, work, time.time() if now is None else now, v, with_steps)


def _blockers(who, work, now: float) -> dict:
    """What stops the quest's automatic checks (`held`), what Check now runs past only
    when he says to check it once anyway (`once_ok`), and what stops even that (`stop`),
    with the heartbeat's row, settings and today's spend they were read from."""
    from . import heartbeat, quests

    hb, cfg = _heart(who)
    cash = quests.money(work)
    spent = heartbeat.spend(hb, heartbeat._midnight())
    cap = Decimal(hb.daily_cap or 0)
    held: list[dict] = []        # what stops automatic checks altogether
    once_ok: list[str] = []      # what Check now asks him to say yes to, once
    stop = ""                    # what stops even Check now
    if hb.state == "paused":
        held.append({"key": "heartbeat_paused",
                     "words": "The heartbeat is paused, so nothing beats on its own until it "
                              "is resumed."})
        once_ok.append("the heartbeat is paused")
    if not heartbeat.duty_on(cfg, heartbeat.WORK_DUTY):
        held.append({"key": "duty_off",
                     "words": "The heartbeat's quests duty is off, so it works on no quest by "
                              "itself."})
        once_ok.append("the heartbeat's quests duty is off")
    q_state = quests.state_of(work, now)
    if q_state == "paused":
        held.append({"key": "paused", "words": f"Quest {work.task_number} is paused."})
        once_ok.append(f"quest {work.task_number} is paused")
    elif q_state == "not carried":
        held.append({"key": "not_carried",
                     "words": "The heartbeat does not carry this quest."})
        once_ok.append("the heartbeat does not carry it")
    elif q_state == "ended":
        held.append({"key": "ended", "words": quests.running(work, now)})
        stop = quests.running(work, now)
    elif q_state == "not started":
        held.append({"key": "not_started",
                     "words": f"It starts on {clock.moment(work.started_at).strftime('%-d %B')}."})
        stop = "It has not started yet."
    if work.budget and cash["left"] <= 0:
        words = (f"Its {quests.dollars(cash['budget'])} budget is spent "
                 f"({quests.dollars(cash['out'])} out).")
        held.append({"key": "budget", "words": words})
        stop = stop or words + " Raise the budget to let it work again."
    if spent >= cap:
        words = (f"Today's heartbeat spend, {quests.dollars(spent)}, has reached the "
                 f"{quests.dollars(cap)} daily cap.")
        held.append({"key": "cap", "words": words + " Checks start again after midnight."})
        stop = stop or words

    return {"hb": hb, "cfg": cfg, "cash": cash, "spent": spent, "cap": cap, "held": held,
            "once_ok": once_ok, "stop": stop}


def _state(who, work, now: float, v: dict | None, with_steps: bool = True) -> dict:
    from . import heartbeat, quests

    got = _blockers(who, work, now)
    hb, cfg, cash, spent, cap = got["hb"], got["cfg"], got["cash"], got["spent"], got["cap"]
    held, once_ok, stop = got["held"], got["once_ok"], got["stop"]
    interval = max(1, hb.interval_minutes or heartbeat.DEFAULT_INTERVAL) * 60
    beats = _beats(work)
    live = beats["live"]
    last = beats["last"]
    full = beats["full"]
    seen_at = beats["done"].started_at if beats["done"] is not None else 0
    steps_now = (steps(work, v, last_full_at=seen_at, now=now)
                 if with_steps else [])

    # What only delays an automatic check, and when it may come.
    waits: list[dict] = []
    hours = cfg["hours"]
    local = clock.moment(now)
    if hours["quiet_on"] and heartbeat.within(local, hours["quiet_from"], hours["quiet_to"]):
        waits.append({"key": "quiet",
                      "words": f"Quiet hours, {hours['quiet_from']} to {hours['quiet_to']}: "
                               "nothing beats on its own until they end."})
    working = heartbeat.within(local, hours["work_from"], hours["work_to"])
    if not working and cfg["wakes"]["timer"]:
        waits.append({"key": "hours",
                      "words": f"The regular timer runs from {hours['work_from']} to "
                               f"{hours['work_to']}, every {hb.interval_minutes} minutes."})
    pending = [e for e in (work.pending or []) if heartbeat.Heartbeat._wakes(e, cfg)]
    candidates: list[tuple[float, str]] = []
    if pending:
        at = heartbeat.Heartbeat._guard_at(hb, now, cfg)
        candidates.append((_push_out_of_quiet(max(at, now), cfg), "event"))
    if work.due_at:
        candidates.append((_push_out_of_quiet(max(work.due_at, now), cfg), "due"))
    if cfg["wakes"]["timer"]:
        candidates.append((_timer_at(work, cfg, interval, now, bool(pending)), "timer"))
    nxt, how = (min(candidates) if candidates else (0.0, ""))
    if nxt and spent >= cap:
        nxt = max(nxt, _midnight_after(now))
    if work.due_at and work.due_at > now:
        what = _clean(work.due_what, 300)
        line = (f"Its last beat set its own next look for {full_words(work.due_at)}"
                + (f": “{what}”" if what else "")
                + ("" if what.endswith((".", "!", "?", "…")) else "."))
        if how == "timer" and nxt < work.due_at:
            line += " The regular timer may still look before then."
        # Its reason was a beat's, at that beat: a step made ready since says it no
        # longer stands, rather than leaving it to read as the blocker now.
        set_at = beats["deferred_at"]
        newer = next((one for one in steps_now if not one.get("blocked_by")
                      and (one.get("after") or {}).get("at", 0) > set_at), None) if set_at else None
        if newer is not None:
            line += (f" That was set before step {newer['after']['n']} was completed "
                     f"({newer['after']['when']}), so its reason no longer stands.")
        waits.append({"key": "deferred_outdated" if newer else "deferred", "words": line})
    if how == "timer" and not pending and nxt > _timer_at(work, cfg, interval, now, True):
        lapse = work.last_full_at + cfg["skip"]["nothing_new_hours"] * 3600
        waits.append({"key": "nothing_new",
                      "words": f"Its last full beat was {at_words(work.last_full_at, now)}; with "
                               "nothing new, the timer skips it until "
                               f"{cfg['skip']['nothing_new_hours']} h after that "
                               f"({at_words(lapse, now)})."})
    if pending:
        waits.append({"key": "events",
                      "words": (f"{len(pending)} new things wait" if len(pending) != 1
                                else "1 new thing waits") + " for its next check: "
                               + "; ".join(_clean(e.get("what") or e.get("kind"), 160)
                                           for e in pending[-3:])})
    automatic = not held
    next_view = {}
    if automatic and nxt:
        soon = nxt <= now + 90
        next_view = {
            "at": nxt, "how": how, "soon": soon,
            "when": "any moment now" if soon else full_words(nxt),
            "in": "" if soon else _span(nxt - now),
            "zone": clock.place(),
            "words": ("The earliest an automatic check may run"
                      + {"timer": ", on the regular timer", "event": ", for what is waiting",
                         "due": ", at the time it set itself"}.get(how, "")
                      + ". It is not a promise: Rouh being busy, the daily cap or its "
                        "wake-up check finding nothing new can still move or skip it."),
        }

    news = [s for s in steps_now if s.get("news")]
    last_view = _beat_view(last, now) if last is not None else None
    full_view = _beat_view(full, now) if full is not None else None
    if full_view is not None and news:
        first = news[0]
        step = f"step {first['after']['n']} “{first['after']['title']}”"
        full_view["outdated"] = (
            f"Out of date: {step} was completed {first['after']['when']}, after this check, "
            "so what it found then no longer stands." if full.status == "done" else
            f"No check has finished since {step} was completed {first['after']['when']}, so "
            "it has not been looked at yet.")
    live_view = _beat_view(live, now) if live is not None else None

    if live is not None and live.status == "running":
        st, label = "checking", "Checking now"
    elif live is not None:
        st, label = "queued", "Check queued"
    elif stop:
        st = next((h["key"] for h in held if h["key"] in ("ended", "not_started", "budget",
                                                           "cap")), "held")
        label = {"ended": "Ended", "not_started": "Not started", "budget": "Budget spent",
                 "cap": "Daily cap reached"}.get(st, "Held")
    elif held:
        st, label = "paused", "Paused"
        if held[0]["key"] == "heartbeat_paused":
            label = "Heartbeat paused"
        elif held[0]["key"] in ("duty_off", "not_carried"):
            label = "Not carried"
    elif waits and any(w["key"] == "quiet" for w in waits):
        st, label = "quiet", "Quiet hours"
    else:
        st, label = "waiting", "Waiting for its next check"

    cost = beats["cost"]
    check = {
        "can": live is None and not stop,
        "already": live_view,
        "refused": stop,
        "needs_yes": bool(once_ok) and live is None and not stop,
        "paused": once_ok,
        "yes_words": ("Check it once even though " + " and ".join(once_ok)
                      + ". It stays paused afterwards.") if once_ok else "",
        "help": (f"Runs one heartbeat check of quest {work.task_number} now, in its own chat, "
                 "even outside its hours. It is not a resume and runs none of the heartbeat's "
                 "other duties. It may do the quest's own allowed work, such as reading and "
                 "drafting, and costs what a beat costs"
                 + (f" (lately about ${cost:,.2f} a check)" if cost is not None else "")
                 + f", counted against its budget and the heartbeat's {quests.dollars(cap)} "
                   "daily cap. Anything that needs your yes still waits for it. One check "
                   "may not finish a whole step."),
    }
    return {
        "number": work.task_number, "title": work.title, "href": quests.address(work),
        "state": st, "label": label,
        "executor": f"Quest {work.task_number}'s own beats, run by the heartbeat in its chat. "
                    "A goal run never starts the quest's steps.",
        "held": held, "waits": waits, "next": next_view, "automatic": automatic,
        "live": live_view, "last": last_view, "last_full": full_view,
        "steps": steps_now, "news": bool(news), "check": check,
        "spent_today": quests.dollars(spent), "cap": quests.dollars(cap),
        "budget_left": quests.dollars(cash["left"]) if work.budget else "",
        "zone": clock.place(),
    }


def step_label(st: dict, one: dict) -> tuple[str, str]:
    """A quest step's state on the goal map, from the quest's: a key and the words."""
    if one.get("blocked_by"):
        b = one["blocked_by"]
        return "blocked", f"Blocked: waits for step {b['n']}"
    if st["state"] == "checking":
        return "checking", "Quest check running now"
    if st["state"] == "queued":
        return "queued", "Quest check queued"
    if st["state"] in ("paused", "held", "ended", "not_started", "budget", "cap"):
        return st["state"], "Ready · " + st["label"].lower()
    if st["state"] == "quiet":
        return "quiet", "Ready · quiet hours"
    return "ready", "Ready · waits for the quest's next check"


def for_goal(who, v: dict) -> dict:
    """The goal's view with its quest's state on it, and on each step that is the quest's
    (`exec`), for the goal map. The goal unchanged when it is no quest's."""
    from . import quests

    try:
        row = next((w for w in quests.all_of(who) if w.task_id == v["id"]), None)
        if row is None:
            return v
        st = state(who, row, v=v)
    except Exception:
        log.exception("the quest of goal %s could not be read", v.get("number"))
        return v
    v["quest"] = st
    from . import goals

    mine = {one["id"]: one for one in st["steps"]}
    for s in goals._flat(v["steps"]):
        one = mine.get(s["id"])
        if one is None:
            continue
        key, label = step_label(st, one)
        s["exec"] = {**one, "state": key, "label": label}
    return v


# --- Check now ------------------------------------------------------------------------------


def ask(who, work, *, while_paused: bool = False, where: str = "") -> dict:
    """Queue one check of the quest, or hand back the one already asked for.

    Under a lock on the quest's record, so two presses at once make one check. Refused
    with the reason when nothing could run it (ended, its budget spent, the daily cap
    reached), and asks first (`NeedsYes`) when it or the heartbeat is paused."""
    from django.db import transaction

    from . import quests

    m = _models()
    now = time.time()
    with clock.person(who), transaction.atomic():
        fresh = (m.LongWork.objects.select_for_update()
                 .filter(user_id=str(who.user_id), org_id=str(who.org_id), id=work.id).first())
        if fresh is None:
            raise Refused("There is no such quest.")
        live = (m.HeartbeatBeat.objects.filter(**_whose(fresh), work_id=fresh.id,
                                               status__in=LIVE).order_by("-id").first())
        if live is not None:
            words = ("A check of it is already running" if live.status == "running"
                     else "A check of it is already queued")
            return {"beat": live.id, "status": live.status, "already": True,
                    "said": f"{words}, so nothing more was asked for. "
                            f"{_beat_view(live, now)['words']}"}
        st = _state(who, fresh, now, None, False)
        if st["check"]["refused"]:
            raise Refused("Nothing was asked for: " + st["check"]["refused"])
        if st["check"]["needs_yes"] and not while_paused:
            raise NeedsYes(f"Nothing was asked for, because {' and '.join(st['check']['paused'])}. "
                           "Tick “Check it once anyway” to run a single check; it stays "
                           "paused.")
        place = {"goal": "on the goal map", "quest": "on the quest's page",
                 "chat": "in conversation"}.get(where, "")
        event = {"kind": "asked", "at": now, "while_paused": bool(while_paused and
                                                                   st["check"]["needs_yes"]),
                 # Kept on the beat's row, so the name is written in, not a mark.
                 "what": owner.say(f"‹owner› pressed Check now{(' ' + place) if place else ''}: one check "
                                   f"of {quests.name(fresh)}, asked for now. Look at what is new since "
                                   "the last beat, above all the goal steps below that are ready, do "
                                   "what this beat can, and keep the notebook and plan current.",
                                   str(fresh.user_id))}
        beat = m.HeartbeatBeat.objects.create(
            **_whose(fresh), trigger="now", work_id=fresh.id, events=[event], status="queued",
            reason="", started_at=now)
    log.info("check %s of quest %s asked for%s", beat.id, fresh.task_number,
             " while paused" if event["while_paused"] else "")
    return {"beat": beat.id, "status": "queued", "already": False,
            "said": f"Check queued for quest {fresh.task_number}: one beat on it starts within "
                    "a minute, or once Rouh's current turn ends. It is one check, not a resume."}


def next_asked(who):
    """The oldest check asked for and not started, after failing any that waited too long."""
    m = _models()
    now = time.time()
    rows = m.HeartbeatBeat.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id),
                                          status="queued").order_by("id")
    stale = [b.id for b in rows if now - (b.started_at or now) > QUEUE_MOST]
    if stale:
        m.HeartbeatBeat.objects.filter(id__in=stale, status="queued").update(
            status="failed", finished_at=now,
            reason=f"Rouh was busy for {QUEUE_MOST // 60} minutes after you asked, so it never "
                   "started. Nothing ran and nothing was spent; press Check now again.")
    return rows.exclude(id__in=stale).first()


def still_allowed(who, work, asked) -> str:
    """Why a queued check may not run after all, or "": what stops even Check now came
    about after he asked, or the quest or the heartbeat was paused after he asked without
    his saying to check it once anyway."""
    with clock.person(who):
        got = _blockers(who, work, time.time())
    if got["stop"]:
        return "Nothing ran: " + got["stop"]
    yes = any(isinstance(e, dict) and e.get("while_paused") for e in (asked.events or []))
    if got["once_ok"] and not yes:
        return ("It was paused after you asked (" + " and ".join(got["once_ok"]) + "), so it "
                "was not checked. Press Check now again and tick “Check it once anyway” to "
                "check it while paused.")
    return ""


def left_over() -> int:
    """Beats left queued or running by a Rouh that stopped, failed with the reason, at start."""
    m = _models()
    now = time.time()
    queued = m.HeartbeatBeat.objects.filter(status="queued").update(
        status="failed", finished_at=now,
        reason="Rouh restarted before this check started. Nothing ran; press Check now again.")
    running = m.HeartbeatBeat.objects.filter(status="running").update(
        status="failed", finished_at=now,
        reason="Rouh restarted while this beat was running, so it did not finish.")
    return queued + running


def step_completed(goal, step) -> list[tuple[object, str, dict]]:
    """A goal step is complete: for each quest step that it makes ready, the quest's record,
    the words of the event that wakes a beat on it, and the event's own fields.

    A dependency's completion is not a job launch: nothing here starts anything. It is an
    event on the quest (`Heartbeat.event`), which wakes its next beat under every rule a
    beat keeps - quiet hours, pause, budget, the daily cap and the flood guard."""
    from . import goals, models

    folder = goals._folder(goal)
    meta = goals._meta(folder) if folder is not None else {}
    record = (meta.get("quest") or {}).get("record") if isinstance(meta.get("quest"), dict) else None
    if record is None:
        return []
    work = models.LongWork.objects.filter(id=record, task_id=goal.id).first()
    if work is None:
        return []
    try:
        v = goals.view(goal)
    except Exception:
        log.exception("goal %s could not be read for its quest", goal.id)
        return []
    out = []
    for one in steps(work, v):
        after = one.get("after") or {}
        if one.get("blocked_by") or after.get("id") != step.id:
            continue
        words = (f"Goal step {after['n']} “{after['title']}” was completed by "
                 f"{'‹owner›' if after['by'] == 'you' else 'Rouh'}, so step {one['n']} "
                 f"“{one['title']}”, which is the quest's, is ready.")
        if after["note"]:
            words += f" What ‹he› wrote there: “{_clean(after['note'], 280)}”"
        # The event is kept on the quest's beat, so the name is written in, not a mark.
        out.append((work, owner.say(words, str(work.user_id)), {"step": one["id"]}))
    return out
