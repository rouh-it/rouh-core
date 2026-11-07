"""Every beat of the heartbeat, on a page of its own: listed, opened, analysed, deleted, notes cleared.

Petar, 5 October 2026: "Make a separate page, linked from the heartbeat page and from each
long-running work item, that lists beats as a table." And 20 October 2026: "please make the
beats list in a separate page. that should be a huge table with search, filter, analysis
etc". The page is Anatomy's `/anatomy/behaviour/beats` (`beatspage.js`), and
`/anatomy/behaviour/beats/<work>` opens it filtered to one piece of work (`heartbeat` for the
heartbeat's own duties); the Heartbeat page lists no beats any more, it links here.

Each beat is read with the model requests it made (`llm_requests`, those in the chat it ran
in between its start and its end, `_requests`): the wake-up check's (`heartbeat_check`) and
the decision's, so the table says how far it got, which models it asked, its tokens, cost
and errors. `detail` opens one: the note it was handed, every request, every tool call and
what came back, and the runs, tasks and approvals it made.

What a beat is, is `HeartbeatBeat` (`rouh/heartbeat.py`). Two things are done to many at once:

- **Deleting beats** takes the rows away, from the table and from the history the work's
  page and the next beat's number count. What they cost is not taken away: a piece of
  work's money and today's heartbeat spend are read from the log of every model request in
  its chat (`quests.money`, `heartbeat.spend`), never from these rows, so the money that
  was really spent stays counted. Only deleting or resetting the work itself clears it
  (`quests.remove`, `quests.reset`).
- **Clearing their notes** takes the silent notes those beats left for Rouh's next
  conversation with Petar out of `HeartbeatState.notes`, so they are never said. A note
  knows its beat since this change (`heartbeat._keep_note`); an older one is found by its
  words. Which beats had theirs cleared is kept in the heartbeat's `own["cleared_notes"]`,
  so the table can say so.

Every query names the signed-in person's user and organisation.
"""
from __future__ import annotations

import time
from decimal import Decimal

from . import clock, quests

#: The most rows one listing sends; the rest are said to be there. A year of beats every
#: half hour in working hours is about ten thousand.
MOST = 12000
#: The most beats one mass action takes.
PICK_MOST = 5000
#: How many cleared beats are remembered as cleared.
CLEARED_MOST = 500

#: What woke a beat, as the table says it.
WOKE = {"timer": "Timer", "event": "Event", "due": "Its own time", "now": "Asked now",
        "answer": "Your answer", "summary": "Daily summary"}


def _models():
    from . import models

    return models


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def _state(who):
    return _models().HeartbeatState.objects.filter(**_whose(who)).first()


# --- the notes a beat left -------------------------------------------------------------


def _plain(text: str, most: int) -> str:
    return " ".join(str(text or "").split())[:most]


def note_at(beat, notes: list) -> int:
    """Where in the heartbeat's notes this beat's silent note is, or -1."""
    for i, n in enumerate(notes):
        if n.get("beat") == beat.id:
            return i
    if beat.outcome != "note" or not beat.said:
        return -1
    from .heartbeat import NOTE_EACH

    want = _plain(beat.said, NOTE_EACH)
    for i, n in enumerate(notes):
        if n.get("beat") is not None:
            continue
        text = n.get("text") or ""
        if text == want or text.endswith("”) " + want):
            return i
    return -1


def drop_notes(state, beats: list) -> int:
    """Take these beats' notes out of the heartbeat's notes; how many went. Saves the row."""
    if state is None or not beats:
        return 0
    notes = list(state.notes or [])
    gone = 0
    for beat in beats:
        at = note_at(beat, notes)
        if at >= 0:
            notes.pop(at)
            gone += 1
    if gone:
        _models().HeartbeatState.objects.filter(id=state.id).update(notes=notes,
                                                                    updated_at=time.time())
        state.notes = notes
    return gone


def drop_work_notes(state, work) -> int:
    """Take every note a quest's beats left out of the heartbeat's notes, those of
    beats deleted before as well; how many went. Saves the row."""
    if state is None:
        return 0
    head = f"(“{work.title}”) "
    notes = list(state.notes or [])
    kept = [n for n in notes if not (n.get("work") == work.id or (
        n.get("work") is None and (n.get("text") or "").startswith(head)))]
    if len(kept) != len(notes):
        _models().HeartbeatState.objects.filter(id=state.id).update(notes=kept,
                                                                    updated_at=time.time())
        state.notes = kept
    return len(notes) - len(kept)


# --- the table ---------------------------------------------------------------------------


def _numbers(who) -> dict:
    """Each beat that ran, by id: its number among the beats on the same work (or the
    heartbeat's own), as the beat itself was told it ("This is beat 3")."""
    seen: dict = {}
    out = {}
    rows = (_models().HeartbeatBeat.objects.filter(**_whose(who)).exclude(status="skipped")
            .order_by("started_at", "id").values_list("id", "work_id"))
    for ident, work_id in rows:
        seen[work_id] = seen.get(work_id, 0) + 1
        out[ident] = seen[work_id]
    return out


def _ended(beat, notes: list, cleared: set) -> tuple[str, str]:
    """How it ended, as a word for sorting and the words the table shows."""
    if beat.status == "skipped":
        return "skipped", "Skipped"
    if beat.status == "running":
        return "running", "Running"
    if beat.status == "queued":
        return "running", "Queued"
    if beat.status == "failed":
        return "failed", "Failed"
    if beat.outcome == "telegram":
        return "telegram", "Telegram"
    if beat.outcome == "note":
        if beat.id in cleared:
            return "note", "Note, cleared"
        at = note_at(beat, notes)
        if at < 0:
            return "note", "Note"
        return "note", "Note, said" if notes[at].get("seen") else "Note, not yet said"
    return "nothing", "Nothing"


#: Where a beat stopped on its way to a decision, as the table says it. `code`: skipped
#: by the rules in code before any model was asked (`Heartbeat._skip_because`); `slept`:
#: the wake-up check found nothing to decide; `woke`: the check passed it on to the
#: decision; `direct`: no check was asked (a beat Petar asked for, his answer, its own
#: time, the summary, or the check is off), so the decision ran at once.
STAGES = {"code": "Skipped in code", "slept": "Check: nothing to do",
          "woke": "Check: passed on", "direct": "Not checked", "running": "Running"}
#: What a decision did, as the table says it.
KINDS = {"nothing": "Nothing", "note": "Note", "telegram": "Message", "work": "Started work",
         "approval": "Approval asked", "failed": "Failed"}
#: What a request in a beat was for.
PURPOSES = {"heartbeat_check": "Wake-up check", "turn": "Decision", "subagent": "Decision, a look-up"}
_CHECK_HEAD = "The wake-up check"
#: The heartbeat's duties by a short name, for a column; the whole duty is in the beat's detail.
DUTY_WORDS = {"waiting": "Waiting on you", "unreported": "Unreported runs", "mail": "Mail",
              "calendar": "Calendar", "goals": "Goals", "work": "Quests", "payments": "Payments"}


def _chats_of(state, works: list) -> tuple[dict, list]:
    """The chats each quest's beats ran in, by its record's id, and those of the heartbeat's
    own duties and of quests deleted or reset (`heartbeat.beat_chats`)."""
    per_work = {w.id: [c for c in (w.chat_id, w.earlier_chat_id) if c] for w in works}
    own = [state.chat_id] if state is not None and state.chat_id else []
    retired = [c for c in ((state.own or {}).get("retired_chats") or [])] if state is not None else []
    return per_work, own + [c for c in retired if c and c not in own]


def _requests(who, beats: list, per_work: dict, own: list, *, more: tuple = ()) -> dict:
    """The model requests each beat made, by beat id: those in the chat it ran in, made
    between its start and its end, read from the log of every model request."""
    from bisect import bisect_left, bisect_right

    ran = [b for b in beats if b.status != "skipped" or (b.reason or "").startswith(_CHECK_HEAD)]
    if not ran:
        return {}
    now = time.time()
    chats = set(own)
    for b in ran:
        chats.update(per_work.get(b.work_id, []) if b.work_id is not None else [])
    if not chats:
        return {}
    first = min(b.started_at for b in ran) - 2
    last = max((b.finished_at or now) for b in ran) + 2
    cols = ("id", "session_id", "started_at", "purpose", "model", "status", "error_type",
            "error", "input_tokens", "output_tokens", "cache_read_tokens",
            "cache_write_tokens", "cost_usd", "duration_ms") + more
    rows = (_models().LLMRequest.objects.filter(
        **_whose(who), session_id__in=chats, started_at__gte=first, started_at__lte=last)
        .order_by("started_at", "id").values(*cols))
    by_chat: dict = {}
    for r in rows:
        by_chat.setdefault(r["session_id"], []).append(r)
    starts = {c: [r["started_at"] for r in rs] for c, rs in by_chat.items()}
    out = {}
    for b in ran:
        if b.work_id is None:
            mine = own[:1]
        else:
            mine = per_work.get(b.work_id) or own[1:]
        got = []
        for c in mine:
            if c not in by_chat:
                continue
            lo = bisect_left(starts[c], b.started_at - 1)
            hi = bisect_right(starts[c], (b.finished_at or now) + 1)
            got += by_chat[c][lo:hi]
        out[b.id] = got
    return out


def _tokens_in(r) -> int:
    return int(r["input_tokens"] or 0) + int(r["cache_read_tokens"] or 0) + int(r["cache_write_tokens"] or 0)


def _model_words(model: str) -> str:
    from .config import model_name

    return model_name(model) if model else ""


def _row(b, *, w, chat: str, number, reqs: list, approvals: list, numbers_of: dict,
         cfg: dict, notes: list, cleared: set, year: int, now: float) -> dict:
    """One beat as the table draws it. `numbers_of` is each approval's decision number, by
    its id; `decided` below is whether the beat reached a decision, and the two were one
    name from 29 October to 4 November 2026, which broke the page on any beat that asked."""
    from .heartbeat import STARTS

    ended, ended_words = _ended(b, notes, cleared)
    moment = clock.moment(b.started_at)
    checks = [r for r in reqs if r["purpose"] == "heartbeat_check"]
    decides = [r for r in reqs if r["purpose"] != "heartbeat_check"]
    reason = b.reason or ""
    if b.status in ("running", "queued"):
        stage = "running"
    elif b.status == "skipped":
        stage = "slept" if reason.startswith(_CHECK_HEAD) else "code"
    else:
        stage = "woke" if checks else "direct"
    decided = stage in ("woke", "direct") and b.status not in ("running", "queued")
    started = sum(1 for t in (b.tools or []) if t.get("name") in STARTS and not t.get("held"))
    kinds = []
    if decided:
        if b.status == "failed":
            kinds.append("failed")
        else:
            kinds.append({"telegram": "telegram", "note": "note"}.get(b.outcome or "", "nothing"))
        if started:
            kinds.append("work")
        if approvals:
            kinds.append("approval")
        if len(kinds) > 1 and kinds[0] == "nothing":
            kinds.pop(0)
    errors = []
    if b.status == "failed" and reason:
        errors.append(reason)
    for r in reqs:
        if r["status"] == "error":
            errors.append(f"{PURPOSES.get(r['purpose'], r['purpose'])}, {_model_words(r['model'])}: "
                          f"{r['error_type'] or 'error'} {(r['error'] or '')[:200]}".strip())
    cost = b.cost
    if cost is None and reqs:
        cost = sum((Decimal(r["cost_usd"]) for r in reqs if r["cost_usd"] is not None), Decimal(0))
    took = (b.finished_at - b.started_at) if b.finished_at else None
    return {
        "id": b.id, "number": number, "at": b.started_at,
        "day": moment.strftime("%Y-%m-%d"), "stamp": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "when": moment.strftime("%-d %b %H:%M" if moment.year == year else "%-d %b %Y %H:%M"),
        "work": ({"id": w.task_number, "title": f"{w.task_number} {w.title}",
                  "href": quests.address(w)} if w is not None
                 else {"id": None, "title": "Heartbeat" if b.work_id is None
                       else "A deleted quest", "href": ""}),
        "woke": b.trigger, "woke_words": WOKE.get(b.trigger, b.trigger),
        "events": len(b.events or []),
        "stage": stage, "stage_words": STAGES[stage],
        "why": reason if stage in ("code", "slept") else "",
        "decided": decided, "kinds": kinds,
        "decision_words": ", ".join(KINDS[k] for k in kinds),
        "ended": ended, "ended_words": ended_words,
        "duties": [DUTY_WORDS.get(d, d) for d in (b.duties or [])],
        "said": (b.said or "") if b.status != "skipped" else "",
        "messages": 1 if decided and b.outcome == "telegram" else 0,
        "approvals": [{"id": a.id, "what": a.what, "state": a.state,
                       "decision": numbers_of.get(a.id)} for a in approvals],
        "started": started,
        "tools": [t.get("name") for t in (b.tools or [])],
        "check_model": _model_words(checks[0]["model"]) if checks else "",
        "decide_models": sorted({_model_words(r["model"]) for r in decides if r["model"]}),
        "requests": len(reqs),
        "tokens_in": sum(_tokens_in(r) for r in reqs),
        "tokens_out": sum(int(r["output_tokens"] or 0) for r in reqs),
        "check_cost": float(sum((Decimal(r["cost_usd"]) for r in checks if r["cost_usd"] is not None), Decimal(0))),
        "cost": float(cost) if cost is not None else None,
        "took": round(took, 1) if took is not None else None,
        "errors": errors,
        "chat": f"/chat/{chat}" if chat else "",
        "has_note": ended == "note" and b.id not in cleared,
    }


def _beats_in(who, work: str, start: str, end: str):
    rows = _models().HeartbeatBeat.objects.filter(**_whose(who))
    work = str(work or "all").strip().lower()
    if work == "heartbeat":
        rows = rows.filter(work_id__isnull=True)
    elif work != "all":
        row = quests.by_number(who, work)
        if row is None:
            raise ValueError("There is no such quest.")
        rows = rows.filter(work_id=row.id)
    if start:
        rows = rows.filter(started_at__gte=quests._date(start, "From"))
    if end:
        rows = rows.filter(started_at__lt=quests._date(end, "To") + 86400)
    return rows, work


def listing(who, *, work: str = "all", start: str = "", end: str = "") -> dict:
    """The beats this filter picks, newest first, each with what it cost, the models it
    asked and what its decision did, and what the page needs to judge them against.

    `work` is "all", "heartbeat" (its own duties) or a quest's number (its task's); `start` and
    `end` are days, "2026-10-05", on Petar's clock, both counted in. Searching, the other
    filters and the analysis are the page's, over these rows (`beatspage.js`).
    """
    from .heartbeat import cap_state, config_of, decision_numbers_of

    m = _models()
    rows, work = _beats_in(who, work, start, end)
    total = rows.count()
    beats = list(rows.order_by("-started_at", "-id")[:MOST])
    works = quests.all_of(who)
    titles = {w.id: w for w in works}
    state = _state(who)
    cfg = config_of(state)
    notes = list(state.notes or []) if state else []
    cleared = set((state.own or {}).get("cleared_notes", [])) if state else set()
    per_work, own = _chats_of(state, works)
    reqs = _requests(who, beats, per_work, own)
    asked: dict = {}
    for a in (m.HeartbeatApproval.objects.filter(**_whose(who), beat_id__in=[b.id for b in beats])
              .order_by("id")):
        asked.setdefault(a.beat_id, []).append(a)
    numbers = _numbers(who)
    # Each approval by its decision's number, the only name it is shown with (`heartbeat`).
    decided = decision_numbers_of([a for some in asked.values() for a in some])
    now = time.time()
    year = clock.moment(now).year
    out = []
    for b in beats:
        w = titles.get(b.work_id) if b.work_id is not None else None
        chat = (w.chat_id or w.earlier_chat_id) if w is not None else (
            own[0] if b.work_id is None and own else "")
        out.append(_row(b, w=w, chat=chat, number=numbers.get(b.id), reqs=reqs.get(b.id, []),
                        approvals=asked.get(b.id, []), numbers_of=decided, cfg=cfg, notes=notes,
                        cleared=cleared,
                        year=year, now=now))
    shown_cost = sum((Decimal(b.cost) for b in beats if b.cost is not None), Decimal(0))
    messages = cfg.get("messages") or {}
    return {
        "beats": out, "total": total, "capped": total > len(out),
        "cost": quests.dollars(shown_cost),
        "limits": {"daily_cap": float(state.daily_cap) if state and state.daily_cap is not None else None,
                   "per_day": messages.get("per_day"), "per_hour": messages.get("per_hour")},
        "today": clock.moment(now).strftime("%Y-%m-%d"),
        # Why no full beat runs again today, when the daily cap stops them, or "".
        "cap_paused": cap_state(state, cfg) if state is not None else "",
        "works": [{"id": w.task_number, "title": f"Quest {w.task_number} {w.title}"}
                  for w in works],
        "filter": {"work": work, "start": start, "end": end},
    }


# --- one beat, opened ---------------------------------------------------------------------

#: The most of any one text a beat's detail sends.
TEXT_MOST = 6000
NOTE_MOST = 40000


def _words_in(value, out: list) -> None:
    """Every text in a message, whichever company's shape it is in."""
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for v in value:
            _words_in(v, out)
    elif isinstance(value, dict):
        kind = value.get("type") or ""
        if kind in ("reasoning", "thinking", "redacted_thinking"):
            return
        for key in ("text", "content", "output"):
            if key in value:
                _words_in(value[key], out)


def _pieces(row) -> list:
    """A request's messages, in order, as JSON."""
    import json

    from .models import LLMPiece

    hashes = list(row.message_pieces or [])
    bodies = dict(LLMPiece.objects.filter(hash__in=hashes).values_list("hash", "body"))
    out = []
    for h in hashes:
        try:
            out.append(json.loads(bodies[h]))
        except (KeyError, ValueError):
            out.append({})
    return out


def _handed(rows) -> str:
    """The note the beat was handed: the last message of its first request that opens with
    the heartbeat's own first words."""
    from .heartbeat import NOTE_HEAD

    for row in rows[:1]:
        for msg in reversed(_pieces(row)):
            words: list = []
            _words_in(msg, words)
            text = "\n".join(w for w in words if w)
            if NOTE_HEAD in text:
                return text[text.index(NOTE_HEAD):][:NOTE_MOST]
    return ""


def _calls(rows) -> list:
    """Every tool the decision called, in order, with what it was asked and what came back."""
    import json

    calls = []
    for row in rows:
        for block in ((row.response or {}).get("content") or []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "function_call":
                calls.append({"id": block.get("call_id") or "", "name": block.get("name") or "",
                              "args": str(block.get("arguments") or "")[:TEXT_MOST]})
            elif block.get("type") in ("tool_use", "server_tool_use"):
                calls.append({"id": block.get("id") or "", "name": block.get("name") or "",
                              "args": json.dumps(block.get("input") or {}, ensure_ascii=False)[:TEXT_MOST]})
    if not calls or not rows:
        return calls
    results = {}
    for msg in _pieces(rows[-1]):
        items = msg.get("content") if isinstance(msg.get("content"), list) else [msg]
        for item in items:
            if not isinstance(item, dict):
                continue
            ident = item.get("call_id") if item.get("type") == "function_call_output" else (
                item.get("tool_use_id") if item.get("type") in ("tool_result", "web_search_tool_result",
                                                                 "web_fetch_tool_result") else None)
            if ident:
                words: list = []
                _words_in(item.get("output") if "output" in item else item.get("content"), words)
                results[ident] = "\n".join(w for w in words if w)[:TEXT_MOST]
    for c in calls:
        c["result"] = results.get(c["id"], "")
    return calls


def _runs_started(calls: list) -> list:
    import json

    from .heartbeat import STARTS

    out = []
    for c in calls:
        if c["name"] not in STARTS or not c.get("result", "").strip().startswith("{"):
            continue
        try:
            got = json.loads(c["result"])
        except ValueError:
            continue
        if isinstance(got, dict) and got.get("id"):
            out.append({"id": str(got["id"]), "title": str(got.get("title") or got.get("brief") or "")[:200],
                        "href": f"/run/{got['id']}"})
    return out


def detail(who, ident) -> dict:
    """Everything of one beat: what woke it, the note it was handed, every model request it
    made and what each answered, every tool its decision called, and what it made."""
    import re as _re

    from .heartbeat import _event_line, config_of, decision_numbers_of, duty_label

    m = _models()
    try:
        ident = int(str(ident).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise ValueError("A beat is named by its number.") from None
    b = m.HeartbeatBeat.objects.filter(**_whose(who), id=ident).first()
    if b is None:
        raise LookupError("There is no such beat.")
    works = quests.all_of(who)
    state = _state(who)
    per_work, own = _chats_of(state, works)
    found = _requests(who, [b], per_work, own).get(b.id, [])
    rows = list(m.LLMRequest.objects.filter(id__in=[r["id"] for r in found]).order_by("started_at", "id"))
    decides = [r for r in rows if r.purpose != "heartbeat_check"]
    calls = _calls(decides)
    tasks = [{"number": t.number, "title": t.title, "href": f"/task/{t.number}"}
             for t in m.Task.objects.filter(origin__why__regex=rf"^beat {b.id}( |$)").order_by("number")
             if t.number]
    approvals = list(m.HeartbeatApproval.objects.filter(**_whose(who), beat_id=b.id).order_by("id"))
    decided = decision_numbers_of(approvals)
    cfg = config_of(state)
    moment = clock.moment(b.started_at)
    return {
        "id": b.id, "day": moment.strftime("%Y-%m-%d"),
        "events": [_event_line(e).lstrip("- ") for e in (b.events or []) if isinstance(e, dict)],
        "reason": b.reason or "", "said": b.said or "",
        "duties": [{"name": DUTY_WORDS.get(d, d), "text": _re.sub(r"\s+", " ", duty_label(cfg, d))}
                   for d in (b.duties or [])],
        "note": _handed(rows),
        "requests": [{
            "id": r.id, "purpose": PURPOSES.get(r.purpose, r.purpose), "model": _model_words(r.model),
            "status": r.status, "error": f"{r.error_type} {r.error}".strip()[:600],
            "tokens_in": int(r.input_tokens or 0) + int(r.cache_read_tokens or 0) + int(r.cache_write_tokens or 0),
            "cached": int(r.cache_read_tokens or 0),
            "tokens_out": int(r.output_tokens or 0),
            "cost": float(r.cost_usd) if r.cost_usd is not None else None,
            "ms": r.duration_ms, "text": (r.text or "")[:TEXT_MOST],
        } for r in rows],
        "calls": [{"name": c["name"], "args": c["args"], "result": c.get("result", ""),
                   "held": any(t.get("name") == c["name"] and t.get("held") for t in (b.tools or []))}
                  for c in calls] or [{"name": t.get("name"), "args": "", "result": "", "held": bool(t.get("held"))}
                                      for t in (b.tools or [])],
        "runs": _runs_started(calls),
        "tasks": tasks,
        "approvals": [{"id": a.id, "what": a.what, "to_whom": a.to_whom, "why": a.why, "cost": a.cost,
                       "state": a.state, "href": "/settings/heartbeat",
                       "decision": decided.get(a.id)} for a in approvals],
    }


# --- what is done to many at once ----------------------------------------------------------


def _picked(who, ids) -> list:
    if not isinstance(ids, list) or not ids:
        raise ValueError("Pick at least one beat.")
    try:
        wanted = sorted({int(str(i).strip().lstrip("#")) for i in ids})[:PICK_MOST]
    except (TypeError, ValueError):
        raise ValueError("ids are the beats' numbers.") from None
    return list(_models().HeartbeatBeat.objects.filter(**_whose(who), id__in=wanted))


def _count(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def delete(who, ids) -> str:
    """Delete these beats. What they cost stays counted, because it was really spent."""
    from django.db import transaction

    beats = _picked(who, ids)
    running = [b for b in beats if b.status == "running"]
    beats = [b for b in beats if b.status != "running"]
    if not beats:
        if running:
            raise ValueError("That beat is running now. Delete it once it has ended.")
        raise ValueError("None of those beats is there any more.")
    with transaction.atomic():
        _models().HeartbeatBeat.objects.filter(**_whose(who), id__in=[b.id for b in beats]).delete()
    said = (f"Deleted {_count(len(beats), 'beat')}. What they cost stays in the money "
            "totals, because it was really spent.")
    if running:
        said += f" {_count(len(running), 'beat')} still running was left alone."
    return said


def clear_notes(who, ids) -> str:
    """Take the selected beats' silent notes out, so Rouh never brings them up."""
    from django.db import transaction

    m = _models()
    beats = [b for b in _picked(who, ids) if b.outcome == "note"]
    if not beats:
        return "None of the selected beats left a note."
    with transaction.atomic():
        state = m.HeartbeatState.objects.select_for_update().filter(**_whose(who)).first()
        if state is None:
            return "None of the selected beats left a note."
        drop_notes(state, beats)
        own = dict(state.own or {})
        cleared = [i for i in own.get("cleared_notes", []) if i not in {b.id for b in beats}]
        own["cleared_notes"] = (cleared + [b.id for b in beats])[-CLEARED_MOST:]
        m.HeartbeatState.objects.filter(id=state.id).update(own=own, updated_at=time.time())
    return (f"Cleared the notes of {_count(len(beats), 'beat')}. Rouh will not bring "
            f"{'it' if len(beats) == 1 else 'them'} up.")
