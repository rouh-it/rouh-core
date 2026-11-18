"""Drilling into what the models cost: from the month's total down to one call.

Petar, 12 November 2026 (task 182, step 182-01): "I have great charts but drill down is not
possible." And on 15 November 2026: "build the drilldowns so I can try to understand through
them what is going on."

So the orb's stats screen (`rouh/static/app/orb_costs.js`) can be pressed: from the total to a
company, a model, a use, a day, the chat, run or page that started the calls, the calls
themselves, and one call with why it cost what it did. Every level is a question to the log of
every request made of a model (`llm_requests`, `rouh/llmlog.py`), added up in the database
rather than here, because a month is about 600,000 rows.

What a level is
---------------

A level is a period and a list of choices made on the way down (`filters`), and it is split by
one more thing (`by`): the company, the model, the use, the day, or what started the call
("origin"). The screen asks for the next split in `ORDER` unless the person picks another, so
any order down is allowed and the trail says which was taken.

Every level comes with the same period before it (`previous`), so each row can say what grew:
this month so far against the same days of last month, a week against the week before, a day
against the day before, a range against as many days before it.

Pay per use and the subscriptions
---------------------------------

Every row of `llm_requests` was paid per use, at list price: it was sent with one of Rouh's
own API keys. The Claude Code and Codex runs of the one program are on the subscriptions, and
their tokens are not in this log at all; what Rouh knows of them is that they ran (`run`). So
the top levels count them beside the money, as runs, and never as dollars. A Codex run billed
to the OpenAI key is counted apart, because its cost is per use and is not in this log either.

Whose it is (`AGENTS.md`, "Whose data is it"): the same as `rouh/usage.py`, an administrator
sees the organisation's calls and anybody else their own. The runs table has neither, so only
an administrator is told about runs.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from django.db import connection

from . import clock, costs
from .usage import _money, named

#: What a level may be split by, in the order the screen goes down unless told otherwise.
ORDER = ("provider", "model", "purpose", "day", "origin")

#: Every one of them as the screen says it.
DIMS = {"provider": "Company", "model": "Model", "purpose": "Use", "day": "Day",
        "origin": "Chat, job or page", "hour": "Hour"}

#: The periods the screen offers. A range is any two days, both included. "days30" is the
#: rolling 30 days ending on a day, today included (Petar, 18 November 2026: "a 30 day
#: running cost, not just day/week/month").
PERIODS = ("day", "week", "month", "days30", "range")

#: How many days the rolling total adds up, and how far back its line reaches at least.
ROLLING = 30
ROLLING_SPAN = 90

#: How many rows a level lists before it adds the rest up in one line.
ROWS = 40
#: How many calls one page of the list of calls has.
CALLS = 50
#: The longest range that may be asked for.
MOST_DAYS = 400

#: The companies, as a person knows them.
PROVIDERS = {"anthropic": "Anthropic", "openai": "OpenAI", "voyage": "Voyage AI",
             "google": "Google", "xai": "xAI"}

#: Every use the log writes down, in the words the person would use (`purpose`). Anything not
#: here is said from its own name with its underscores gone, so a new use is never hidden.
USES = {
    "turn": "Rouh's chat replies",
    "subagent": "Helpers inside a chat",
    "router": "Choosing the model for a message",
    "router_decisions": "Choosing the model for a message",
    "router_question": "Choosing the model for a message",
    "chat_title": "Naming chats",
    "filing": "Filing new tasks",
    "task_icon": "Task icons",
    "picture": "Drawing pictures",
    "picture_prompt": "Describing pictures to draw",
    "reminder_title": "Naming reminders",
    "reminder_words": "Reading reminders",
    "heartbeat_check": "Rouh's wake-up check",
    "askai": "Ask AI on pages",
    "comment_pass": "Answering page comments",
    "page_define": "Explaining a passage on a page",
    "page_listen": "Reading a page aloud",
    "source_check": "Checking a page's sources",
    "triage": "Reading Gene therapy reports",
    "run_summary": "Summing up runs",
    "job_request": "Jobs asking Rouh for things",
    "his_word": "Checking whether you already asked",
    "case_ask": "Questions about a mail case",
    "case_read": "Reading mail from other people",
    "reply_check": "Checking replies before sending",
    "reply_status": "Checking whether mail was answered",
    "mail_look": "Looking through mail",
    "slack_promises": "Finding promises in Slack",
    "slack_decisions": "Finding decisions in Slack",
    "brief_world": "Morning brief: the world",
    "brief_ai": "Morning brief: AI news",
    "brief_history": "Morning brief: this day in history",
    "brief_slack": "Morning brief: Slack",
    "meeting_brief": "Preparing for meetings",
    "meeting_slack": "Preparing for meetings: Slack",
    "meeting_next": "Work to start after a meeting",
    "meeting_pick_words": "Recognising meeting guests",
    "answered_in_chat": "Questions you already answered",
    "decision_gate": "Whether a question needs you",
    "action_reader": "Whether only you can do something",
    "action_ask": "Questions about your to-dos",
    "goal_split": "Splitting goals into steps",
    "goal_step_revise": "Rewriting goal steps",
    "control_room": "Control Room headlines",
    "gene_question": "Questions about a gene",
    "gene_writer": "Writing the gene log",
    "gene_eval": "Judging how useful a gene is",
    "gene_match": "Matching genes from the Gene Pool",
    "incubator_score": "Scoring Incubator ideas",
    "incubator_gist": "Summing up Incubator ideas",
    "trial_tester": "Trials: the tester",
    "trial_matcher": "Trials: spotting repeated problems",
    "trial_writer": "Trials: writing testers",
    "trial_discuss": "Trials: talking problems over",
    "second_name": "Naming a Rouh",
    "double_call": "Judging double calls",
    "provider_check_anthropic": "Checking Anthropic is back",
    "provider_check_openai": "Checking OpenAI is back",
    "key_check_anthropic": "Checking a new Anthropic key",
    "key_check_openai": "Checking a new OpenAI key",
    "synapse_xray": "Memory: reading new items (X-ray)",
    "synapse_xray_section": "Memory: reading long items in parts",
    "synapse_tier": "Memory: sorting items",
    "synapse_map_areas": "Memory: mapping areas",
    "synapse_layer_thread": "Memory: following threads",
    "synapse_layer_topic": "Memory: finding topics",
    "synapse_layer_person": "Memory: profiles of people",
    "synapse_layer_profile": "Memory: profiles of people",
    "synapse_explain": "Memory: explaining a link",
    "synapse_test_data": "Memory: making test data",
    "synapse_understand": "Memory: understanding a question",
    "synapse_answer": "Memory: answering a question",
    "synapse_judge": "Memory self-test judge",
    "synapse_chat_recall_judge": "Memory self-test judge: chat recall",
    "synapse_chat_recall_answer": "Memory self-test: chat recall answers",
    "synapse_bench_facts": "Memory self-test: facts",
    "synapse_recall_pick": "Memory: recalling for a chat",
    "synapse_dream": "Memory: dreaming at night",
    "synapse_embed_passages": "Memory: search fingerprints of items",
    "synapse_embed_xray": "Memory: search fingerprints of X-rays",
    "synapse_embed_layer": "Memory: search fingerprints of threads",
    "synapse_embed_query": "Memory: search fingerprints of questions",
    "synapse_message_seeds": "Memory: search fingerprints of messages",
    "synapse_topic_match": "Memory: matching topics",
    "synapse_decide_tier": "Memory decisions: sorting",
    "synapse_decide_sensitivity": "Memory decisions: how private",
    "synapse_decide_seed_rerank": "Memory decisions: ranking",
    "synapse_decide_link_screen": "Memory decisions: links",
    "synapse_decide_contradiction_screen": "Memory decisions: contradictions",
    "synapse_decide_checkpoint_shadow": "Memory decisions: checkpoints",
    "synapse_decisions_probe": "Memory decisions: testing the service",
}


def use_named(purpose: str) -> str:
    """A use as the person says it: "Rouh's chat replies", never "turn"."""
    if not purpose:
        return "Not named by the code that sent it"
    if purpose in USES:
        return USES[purpose]
    words = purpose.replace("_", " ").strip()
    if words.startswith("synapse "):
        words = "Memory: " + words[len("synapse "):]
    return words[:1].upper() + words[1:]


def provider_named(provider: str) -> str:
    return PROVIDERS.get(provider or "", (provider or "Not said").capitalize())


# --- what started a call --------------------------------------------------------------------

#: What started a call, worked out in the database from what the log keeps: the chat it was
#: made in, else the job, run, page, memory item or thing it was about, else nothing.
ORIGIN_SQL = r"""(CASE
  WHEN session_id <> '' THEN 'chat:' || session_id
  WHEN subject ~ '^job [0-9a-f]{6,}$' THEN 'run:' || substr(subject, 5)
  WHEN purpose = 'run_summary' AND subject ~ '^[0-9a-f]{8}$' THEN 'run:' || subject
  WHEN subject = 'synapse' THEN ''
  WHEN subject ~ '^synapse/[0-9a-f-]{36}' THEN substring(subject from '^synapse/[0-9a-f-]{36}')
  WHEN subject ~ '^trial [0-9]+' THEN substring(subject from '^trial [0-9]+')
  ELSE regexp_replace(subject, ' [(]thread [0-9]+[)]$', '') END)"""

_PAGE = re.compile(r"^[a-z0-9_-]+(/[^/\s]+){2,}$")
_MEMORY = re.compile(r"^synapse/[0-9a-f-]{36}$")


def _page_name(path: str) -> str:
    """A workspace page as the person knows it: its task's or step's number and name."""
    parts = [p for p in path.split("/") if p]
    folders = [p for p in parts if re.match(r"^\d+(-\d+)?\.", p)]
    last = folders[-1] if folders else re.sub(r"\.(html|md)$", "", parts[-1] if parts else path)
    m = re.match(r"^(\d+(?:-\d+)?)\.(.*)$", last)
    if m:
        name = f"Page {m.group(1)}: {m.group(2).replace('-', ' ')}"
    else:
        name = "Page: " + last.replace("-", " ")
    page = parts[-1] if parts else ""
    if page.endswith((".html", ".md")) and page not in ("index.html", "index.md"):
        name += f" ({re.sub(r'[.](html|md)$', '', page).replace('-', ' ')})"
    return name


def origin_named(key: str, known: dict) -> dict:
    """What started a call, as the screen says it, and where it is when it has an address.
    `known` holds the titles of the chats, runs and memories among the keys (`_titles`)."""
    if not key:
        return {"name": "Not linked to a chat, job or page", "kind": "none", "link": ""}
    title = known.get(key)
    if key.startswith("chat:"):
        cid = key[5:]
        return {"name": f"Chat: {title}" if title else "A chat with no title", "kind": "chat",
                "link": f"/chat/{cid}"}
    if key.startswith("run:"):
        rid = key[4:]
        return {"name": f"Job: {title}" if title else f"Job {rid}", "kind": "run",
                "link": f"/run/{rid}"}
    if _MEMORY.match(key):
        return {"name": f"Memory: {title}" if title else "A memory no longer there", "kind": "memory",
                "link": "/" + key}
    if _PAGE.match(key):
        return {"name": _page_name(key), "kind": "page",
                "link": "/task/" + re.sub(r"/index(\.html)?$", "", key)}
    m = re.match(r"^task-(\d+)$", key)
    if m:
        return {"name": f"Task {m.group(1)}", "kind": "task", "link": ""}
    m = re.match(r"^INC-(\d+)$", key)
    if m:
        return {"name": f"Incubator idea {m.group(1)}", "kind": "idea", "link": ""}
    if key.startswith("feedback "):
        return {"name": "A Gene therapy report", "kind": "feedback", "link": ""}
    m = re.match(r"^(decision|gene|trial) (\d+)", key)
    if m:
        return {"name": f"{m.group(1).capitalize()} {m.group(2)}", "kind": m.group(1), "link": ""}
    return {"name": key[:1].upper() + key[1:80], "kind": "other", "link": ""}


#: A title's leading emoji or symbols, which chats are given: the screen names the chat in words.
_LEADING = re.compile(r"^[^\w(\[\"'«]+", re.UNICODE)


def _plain(title: str) -> str:
    return _LEADING.sub("", title or "").strip() or (title or "")


def _titles(keys, org_id: str) -> dict:
    """The titles of the chats, runs and memories among these keys, by key, in three queries."""
    from .models import Chat, Run

    keys = [k for k in keys if k]
    chat_ids = [k[5:] for k in keys if k.startswith("chat:")]
    run_ids = [k[4:] for k in keys if k.startswith("run:")]
    set_ids = [k[8:] for k in keys if _MEMORY.match(k)]
    out = {}
    if chat_ids:
        chats = Chat.objects.filter(id__in=chat_ids).values_list("id", "title")
        out.update({f"chat:{i}": _plain(t) for i, t in chats if t})
    if run_ids:
        out.update({f"run:{i}": t for i, t in Run.objects.filter(id__in=run_ids).values_list("id", "title") if t})
    if set_ids:
        for i, name, owner in _rows("SELECT id::text, name, owner_name FROM synapse.dataset"
                                    " WHERE id::text = ANY(%s) AND org_id = %s", [set_ids, org_id]):
            out[f"synapse/{i}"] = f"{name} ({owner})" if owner and owner not in (name or "") else name
    return out


# --- the period -----------------------------------------------------------------------------

def _day(text: str | None, fallback: date) -> date:
    try:
        return date.fromisoformat(str(text)) if text else fallback
    except ValueError:
        raise Refused("a day is written 2026-11-15")


class Refused(ValueError):
    """A question the screen should not have asked, said in words."""


def period_of(kind: str, at: str | None, start: str | None, end: str | None, zone) -> dict:
    """The period asked for and the one before it, as days on the person's clock.

    A period that reaches past today stops at today, and the one before it is then as long as
    what is left of it, so this month so far is set against the same days of last month.
    """
    today = datetime.now(zone).date()
    kind = kind if kind in PERIODS else "month"
    if kind == "range":
        first, last = _day(start, today - timedelta(days=29)), _day(end, today)
        if last < first:
            first, last = last, first
        if (last - first).days >= MOST_DAYS:
            raise Refused(f"a range is at most {MOST_DAYS} days")
        length = (last - first).days + 1
        before_last = first - timedelta(days=1)
        before_first = before_last - timedelta(days=length - 1)
        return _said(kind, first, last, before_first, before_last, today)
    pivot = _day(at, today)
    if kind == "days30":
        # The 30 days ending on the day asked for, against the 30 just before them.
        last = min(pivot, today)
        first = last - timedelta(days=ROLLING - 1)
        before_last = first - timedelta(days=1)
        before_first = before_last - timedelta(days=ROLLING - 1)
        return _said(kind, first, last, before_first, before_last, today)
    if kind == "day":
        first = last = pivot
        before_first = before_last = pivot - timedelta(days=1)
    elif kind == "week":
        first = pivot - timedelta(days=pivot.weekday())
        last = first + timedelta(days=6)
        before_first = first - timedelta(days=7)
        before_last = before_first + timedelta(days=6)
    else:
        first = pivot.replace(day=1)
        last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        before_last = first - timedelta(days=1)
        before_first = before_last.replace(day=1)
    if last > today >= first:
        # So far: the period before it is cut to the same number of days.
        last = today
        if kind != "day":
            before_last = min(before_last, before_first + (last - first))
    return _said(kind, first, last, before_first, before_last, today)


def _words(first: date, last: date) -> str:
    def one(d: date, year: bool) -> str:
        return d.strftime("%a %-d %b") + (d.strftime(" %Y") if year else "")
    if first == last:
        return one(first, first.year != date.today().year)
    if first.day == 1 and (last + timedelta(days=1)).day == 1 and first.month == last.month:
        return first.strftime("%B %Y")
    same_year = first.year == last.year
    return f"{first.strftime('%-d %b') + ('' if same_year else first.strftime(' %Y'))} to {last.strftime('%-d %b %Y')}"


def _short(first: date, last: date) -> str:
    """Two days without their year when both are this year: "19 Oct to 18 Nov"."""
    if first.year == last.year == date.today().year:
        return f"{first.strftime('%-d %b')} to {last.strftime('%-d %b')}"
    return _words(first, last)


def _said(kind, first, last, before_first, before_last, today) -> dict:
    said = _words(first, last)
    if kind == "month" and last == today and first.day == 1 and first != today:
        said = first.strftime("%B %Y") + " so far"
    elif kind == "week" and last == today:
        said = f"This week so far, {_words(first, last)}"
    elif kind == "day" and first == today:
        said = "Today, " + _words(first, last)
    elif kind == "days30":
        said = (f"The last {ROLLING} days ({_short(first, last)})" if last == today
                else f"The {ROLLING} days from {_words(first, last)}")
    return {"kind": kind, "from": first.isoformat(), "to": last.isoformat(), "said": said,
            "before_from": before_first.isoformat(), "before_to": before_last.isoformat(),
            "before_said": _words(before_first, before_last),
            "days": (last - first).days + 1, "today": today.isoformat(),
            "is_now": last == today}


def _bounds(first: str, last: str, zone) -> tuple[float, float]:
    a = datetime.combine(date.fromisoformat(first), datetime.min.time(), zone)
    b = datetime.combine(date.fromisoformat(last) + timedelta(days=1), datetime.min.time(), zone)
    return a.timestamp(), b.timestamp()


# --- the question to the log ----------------------------------------------------------------

def _expr(dim: str, zone_name: str) -> tuple[str, list]:
    """The SQL for one thing a level can be split by, and its parameters."""
    if dim == "provider":
        return "provider", []
    if dim == "model":
        return "(CASE WHEN model <> '' THEN model ELSE served_model END)", []
    if dim == "purpose":
        return "purpose", []
    if dim == "day":
        return "to_char(to_timestamp(started_at) AT TIME ZONE %s, 'YYYY-MM-DD')", [zone_name]
    if dim == "hour":
        return "to_char(to_timestamp(started_at) AT TIME ZONE %s, 'HH24')", [zone_name]
    if dim == "origin":
        return ORIGIN_SQL, []
    raise Refused(f"a level is split by one of {', '.join(ORDER)}")


def _where(who, windows, filters: dict, zone_name: str) -> tuple[str, list]:
    """The rows of this person's in these stretches of time, `(start, end)` in epoch seconds,
    that match every choice made on the way down."""
    sql = ["org_id = %s", "(" + " OR ".join(["(started_at >= %s AND started_at < %s)"] * len(windows)) + ")"]
    args: list = [who.org_id] + [t for w in windows for t in w]
    if not who.is_admin:
        sql.append("user_id = %s")
        args.append(who.user_id)
    for dim, value in filters.items():
        if dim == "day":
            continue  # the day is the period itself
        expr, more = _expr(dim, zone_name)
        sql.append(f"{expr} = %s")
        args += more + [value]
    return " AND ".join(sql), args


def _rows(sql: str, args: list) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def _filters_of(asked: dict) -> dict:
    # In the order they were made, which is the order of the trail.
    out = {}
    for dim, value in asked.items():
        if dim in (*ORDER, "hour") and value is not None and value != "":
            out[dim] = str(value)
    if "hour" in out and "day" not in out:
        raise Refused("an hour is always of a day")
    return out


def _zone_name(zone) -> str:
    return getattr(zone, "key", None) or str(zone)


def _sum(cost) -> float:
    return float(cost or 0)


def _change(now: float, before: float, began_after: bool) -> dict:
    """What grew, in words and in dollars, or nothing to say when there was no before."""
    if began_after:
        return {"said": "no log before this", "delta": None, "pct": None, "dir": "none"}
    delta = now - before
    if abs(delta) < 0.005:
        return {"said": "about the same", "delta": 0.0, "pct": 0, "dir": "same"}
    pct = None if before <= 0 else round(delta / before * 100)
    arrow = "up" if delta > 0 else "down"
    said = f"{arrow} {costs.money(abs(delta))}"
    if pct is not None and abs(pct) < 1000:
        said += f" ({abs(pct)}%)"
    elif before <= 0:
        said = f"new, {costs.money(abs(delta))}"
    return {"said": said, "delta": delta, "pct": pct, "dir": arrow}


def _began(who) -> float | None:
    from .usage import everything

    first = everything(who).order_by("started_at").values_list("started_at", flat=True).first()
    return first


def _plans(who, lo: float, hi: float) -> dict | None:
    """The runs the subscriptions paid for in the period: counted, never priced."""
    if not who.is_admin:
        return None
    from .models import Run

    runs = Run.objects.filter(started_at__gte=lo, started_at__lt=hi)
    claude = runs.filter(agent="claude").count()
    codex = runs.filter(agent="codex").count()
    keyed = runs.filter(agent="codex", detail__startswith="Codex, billed to the OpenAI API key").count()
    return {"claude": claude, "codex": codex - keyed, "codex_on_key": keyed}


def level(who, *, period: str = "month", at: str | None = None, start: str | None = None,
          end: str | None = None, by: str | None = None, **asked) -> dict:
    """One level of the drill-down: the period, the trail, the total against the period before,
    a row for each thing it splits into, the chart by day (or by hour, for one day), and on the
    top levels the runs the subscriptions paid for."""
    zone = clock.zone_of(who)
    zone_name = _zone_name(zone)
    filters = _filters_of(asked)
    if "day" in filters:
        span = period_of("day", filters["day"], None, None, zone)
    else:
        span = period_of(period, at, start, end, zone)
    chosen = set(filters)
    left = [d for d in ORDER if d not in chosen and not (d == "day" and span["days"] == 1)]
    if by is None or by == "":
        by = left[0] if left else ""
    if by and by not in left:
        raise Refused(f"this level cannot be split by {by}")

    lo, hi = _bounds(span["from"], span["to"], zone)
    if "hour" in filters:
        h = int(filters["hour"])
        lo, hi = lo + h * 3600, lo + (h + 1) * 3600
    blo, bhi = _bounds(span["before_from"], span["before_to"], zone)
    if "hour" in filters:
        h = int(filters["hour"])
        blo, bhi = blo + h * 3600, blo + (h + 1) * 3600
    # The period and the one before it, in one question: everything before `lo` is the before.
    where, args = _where(who, [(blo, bhi), (lo, hi)], filters, zone_name)
    began = _began(who)
    # Nothing was logged in the period before, so there is nothing to compare with; or the log
    # began part way through it, which the screen says.
    began_after = began is None or began >= bhi
    before_partial = not began_after and began > blo

    rows: list[dict] = []
    more = None
    if by:
        expr, eargs = _expr(by, zone_name)
        got = _rows(
            f"SELECT {expr} AS k,"
            " SUM(CASE WHEN started_at >= %s THEN cost_usd END),"
            " COUNT(*) FILTER (WHERE started_at >= %s),"
            " COUNT(*) FILTER (WHERE started_at >= %s AND cost_usd IS NULL),"
            " SUM(CASE WHEN started_at < %s THEN cost_usd END),"
            " COUNT(*) FILTER (WHERE started_at < %s)"
            f" FROM llm_requests WHERE {where} GROUP BY 1",
            eargs + [lo, lo, lo, lo, lo] + args)
        got = [g for g in got if g[2]]  # in the period itself, not only the one before
        got.sort(key=lambda g: (-_sum(g[1]), -g[2], str(g[0])))
        keys = [g[0] for g in got[:ROWS]]
        known = _titles(keys, who.org_id) if by == "origin" else {}
        for k, cost, calls, unpriced, bcost, bcalls in got[:ROWS]:
            k = k or ""
            cost, bcost = _sum(cost), _sum(bcost)
            row = {"key": k, "cost": cost, "said": _money(cost) if calls > unpriced else "not priced",
                   "calls": calls, "unpriced": unpriced, "before": bcost, "before_calls": bcalls,
                   "change": _change(cost, bcost, began_after),
                   **_per_call(cost, calls - unpriced)}
            row.update(_row_name(by, k, known))
            rows.append(row)
        rest = got[ROWS:]
        if rest:
            cost = sum(_sum(g[1]) for g in rest)
            more = {"count": len(rest), "cost": cost, "said": _money(cost),
                    "calls": sum(g[2] for g in rest)}

    total_cost, total_calls, total_unpriced, before_cost, before_calls = _rows(
        "SELECT SUM(CASE WHEN started_at >= %s THEN cost_usd END),"
        " COUNT(*) FILTER (WHERE started_at >= %s),"
        " COUNT(*) FILTER (WHERE started_at >= %s AND cost_usd IS NULL),"
        " SUM(CASE WHEN started_at < %s THEN cost_usd END),"
        " COUNT(*) FILTER (WHERE started_at < %s)"
        f" FROM llm_requests WHERE {where}", [lo, lo, lo, lo, lo] + args)[0]
    total_cost, before_cost = _sum(total_cost), _sum(before_cost)

    series = _series(who, span, filters, by, rows, zone, zone_name)
    rolling = None
    if span["kind"] in ("days30", "month") and not ({"day", "hour"} & chosen):
        rolling = _rolling(who, span, filters, zone, zone_name, began)
    plans = _plans(who, lo, hi) if not ({"model", "purpose", "origin", "hour"} & chosen) else None
    if plans is not None and filters.get("provider") not in (None, "anthropic", "openai"):
        plans = None
    if plans is not None and filters.get("provider") == "anthropic":
        plans = {"claude": plans["claude"], "codex": 0, "codex_on_key": 0}
    elif plans is not None and filters.get("provider") == "openai":
        plans = {"claude": 0, "codex": plans["codex"], "codex_on_key": plans["codex_on_key"]}

    trail = []
    for dim, value in filters.items():
        named_ = _row_name(dim, value, _titles([value], who.org_id) if dim == "origin" else {})
        trail.append({"dim": dim, "value": value, "name": named_["name"], "what": DIMS[dim],
                      "link": named_.get("link", "")})

    return {
        "period": span,
        "trail": trail,
        "by": by,
        "by_said": DIMS.get(by, ""),
        "can_split": [{"dim": d, "said": DIMS[d]} for d in left],
        "total": {"cost": total_cost, "said": _money(total_cost) if total_calls > total_unpriced or not total_calls
                  else "not priced",
                  "calls": total_calls, "unpriced": total_unpriced,
                  **_per_call(total_cost, total_calls - total_unpriced)},
        "before": {"cost": before_cost, "said": _money(before_cost), "calls": before_calls,
                   "partial": before_partial, "none": began_after},
        "change": _change(total_cost, before_cost, began_after),
        "rows": rows,
        "more": more,
        "series": series,
        "rolling": rolling,
        "plans": plans,
        "began": datetime.fromtimestamp(began, zone).date().isoformat() if began else None,
        "whose": "organisation" if who.is_admin else "yours",
        "currency": "USD",
    }


def _per_call(cost: float, priced: int) -> dict:
    if not priced:
        return {"per_call": None, "per_call_said": "not priced"}
    return {"per_call": cost / priced, "per_call_said": _money(cost / priced)}


def _row_name(dim: str, key: str, known: dict) -> dict:
    if dim == "provider":
        return {"name": provider_named(key), "link": ""}
    if dim == "model":
        return {"name": named(key), "link": ""}
    if dim == "purpose":
        return {"name": use_named(key), "link": ""}
    if dim == "day":
        d = date.fromisoformat(key)
        return {"name": d.strftime("%a %-d %b"), "link": ""}
    if dim == "hour":
        return {"name": f"{int(key):02d}:00 to {int(key) + 1:02d}:00", "link": ""}
    if dim == "origin":
        got = origin_named(key, known)
        return {"name": got["name"], "link": got["link"], "kind": got["kind"]}
    return {"name": key, "link": ""}


#: How many of a level's rows the chart colours one by one; the rest are one grey "Other".
SEGMENTS = 6


def _series(who, span: dict, filters: dict, by: str, rows: list[dict], zone, zone_name: str) -> dict:
    """The chart: one bar a day, or one an hour for a single day, each split into the level's
    largest rows."""
    unit = "hour" if span["days"] == 1 else "day"
    lo, hi = _bounds(span["from"], span["to"], zone)
    where, args = _where(who, [(lo, hi)], {k: v for k, v in filters.items() if k != "hour"}, zone_name)
    when, wargs = _expr(unit, zone_name)
    split = by if by and by not in ("day",) else ""
    top = [r["key"] for r in rows[:SEGMENTS] if r["cost"] > 0] if split else []
    if split:
        expr, eargs = _expr(split, zone_name)
        got = _rows(f"SELECT {when}, {expr}, SUM(cost_usd), COUNT(*) FROM llm_requests"
                    f" WHERE {where} GROUP BY 1, 2", wargs + eargs + args)
    else:
        got = [(w, "", c, n) for w, c, n in _rows(
            f"SELECT {when}, SUM(cost_usd), COUNT(*) FROM llm_requests WHERE {where} GROUP BY 1",
            wargs + args)]
    points: dict[str, dict] = {}
    for at, key, cost, calls in got:
        p = points.setdefault(at, {"at": at, "cost": 0.0, "calls": 0, "segs": {}})
        p["cost"] += _sum(cost)
        p["calls"] += calls
        seg = (key or "") if (key or "") in top else "__other__"
        p["segs"][seg] = p["segs"].get(seg, 0.0) + _sum(cost)
    out = []
    if unit == "hour":
        slots = [f"{h:02d}" for h in range(24)]
    else:
        first, last = date.fromisoformat(span["from"]), date.fromisoformat(span["to"])
        slots = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    for at in slots:
        p = points.get(at, {"at": at, "cost": 0.0, "calls": 0, "segs": {}})
        out.append({"at": at, "cost": p["cost"], "said": _money(p["cost"]), "calls": p["calls"],
                    "segs": [{"key": k, "cost": v, "said": _money(v)}
                             for k, v in sorted(p["segs"].items(),
                                                key=lambda kv: (top.index(kv[0]) if kv[0] in top else 99))
                             if v > 0]})
    return {"unit": unit, "split": split, "keys": top, "points": out}


def _rolling(who, span: dict, filters: dict, zone, zone_name: str, began: float | None) -> dict | None:
    """The running 30-day cost: for each day, what was paid per use in the 30 days ending
    that day. It ends today and reaches back at least `ROLLING_SPAN` days, or to the shown
    window if that is older, never before the log began nor past `MOST_DAYS`. A point whose
    30 days begin before the log is marked `partial`, because fewer days are in it."""
    if began is None:
        return None
    today = date.fromisoformat(span["today"])
    began_day = datetime.fromtimestamp(began, zone).date()
    first = min(today - timedelta(days=ROLLING_SPAN - 1), date.fromisoformat(span["to"]))
    first = max(first, began_day, today - timedelta(days=MOST_DAYS - 1))
    if first > today:
        return None
    lo, hi = _bounds((first - timedelta(days=ROLLING - 1)).isoformat(), today.isoformat(), zone)
    where, args = _where(who, [(lo, hi)], filters, zone_name)
    when, wargs = _expr("day", zone_name)
    daily = {d: (_sum(c), n) for d, c, n in _rows(
        f"SELECT {when}, SUM(cost_usd), COUNT(*) FROM llm_requests WHERE {where} GROUP BY 1",
        wargs + args)}
    points = []
    day = first - timedelta(days=ROLLING - 1)
    window: list[tuple[float, int]] = []
    while day <= today:
        window.append(daily.get(day.isoformat(), (0.0, 0)))
        if len(window) > ROLLING:
            window.pop(0)
        if day >= first:
            cost = sum(c for c, _ in window)
            start = day - timedelta(days=ROLLING - 1)
            points.append({"at": day.isoformat(), "from": start.isoformat(), "cost": cost,
                           "said": _money(cost), "calls": sum(n for _, n in window),
                           "partial": start < began_day,
                           "days": (day - max(start, began_day)).days + 1})
        day += timedelta(days=1)
    return {"days": ROLLING, "points": points,
            "chosen": span["to"] if span["kind"] == "days30" else None}


# --- the calls ------------------------------------------------------------------------------

_CALL_FIELDS = ("id", "started_at", "provider", "model", "served_model", "purpose", "session_id",
                "subject", "status", "input_tokens", "output_tokens", "cache_read_tokens",
                "cache_write_tokens", "web_searches", "cost_usd", "duration_ms", "attempt",
                "turn_id", "stop_reason")


def calls(who, *, period: str = "month", at: str | None = None, start: str | None = None,
          end: str | None = None, order: str = "cost", offset: int = 0, **asked) -> dict:
    """The calls of a level, dearest or newest first, a page at a time."""
    zone = clock.zone_of(who)
    zone_name = _zone_name(zone)
    filters = _filters_of(asked)
    span = period_of("day", filters["day"], None, None, zone) if "day" in filters else \
        period_of(period, at, start, end, zone)
    lo, hi = _bounds(span["from"], span["to"], zone)
    if "hour" in filters:
        h = int(filters["hour"])
        lo, hi = lo + h * 3600, lo + (h + 1) * 3600
    where, args = _where(who, [(lo, hi)], filters, zone_name)
    offset = max(0, int(offset or 0))
    order = order if order in ("cost", "time", "failed") else "cost"
    if order == "failed":
        # Calls that failed, were stopped half way or never heard back, newest first: each
        # one was sent and may have been paid for.
        where += " AND status IN ('error', 'stopped', 'sent')"
    sort = "cost_usd DESC NULLS LAST, started_at DESC" if order == "cost" else "started_at DESC"
    got = _rows(f"SELECT {', '.join(_CALL_FIELDS)}, {ORIGIN_SQL} FROM llm_requests WHERE {where}"
                f" ORDER BY {sort} LIMIT %s OFFSET %s", args + [CALLS + 1, offset])
    count = _rows(f"SELECT COUNT(*) FROM llm_requests WHERE {where}", args)[0][0]
    known = _titles([g[-1] for g in got], who.org_id)
    out = [_call_row(dict(zip(_CALL_FIELDS + ("origin",), g)), zone, known) for g in got[:CALLS]]
    trail = []
    for dim, value in filters.items():
        named_ = _row_name(dim, value, _titles([value], who.org_id) if dim == "origin" else {})
        trail.append({"dim": dim, "value": value, "name": named_["name"], "what": DIMS[dim],
                      "link": named_.get("link", "")})
    return {"period": span, "trail": trail, "calls": out, "count": count, "offset": offset,
            "more": len(got) > CALLS, "order": order}


def _call_row(r: dict, zone, known: dict) -> dict:
    started = datetime.fromtimestamp(r["started_at"], zone)
    cost = r["cost_usd"]
    origin = origin_named(r.get("origin") or "", known)
    return {
        "id": r["id"],
        "when": started.strftime("%a %-d %b, %H:%M:%S"),
        "time": started.strftime("%H:%M"),
        "company": provider_named(r["provider"]),
        "model": named(r["model"] or r["served_model"]),
        "use": use_named(r["purpose"]),
        "fresh": r["input_tokens"], "cache_read": r["cache_read_tokens"],
        "cache_write": r["cache_write_tokens"], "output": r["output_tokens"],
        "cost": None if cost is None else float(cost),
        "said": costs.money(None if cost is None else float(cost)),
        "took": _took(r["duration_ms"]),
        "status": r["status"],
        "status_said": _status(r["status"], r.get("stop_reason") or ""),
        "attempt": r["attempt"],
        "origin": origin,
    }


def _took(ms) -> str:
    if ms is None:
        return "not logged"
    if ms < 1000:
        return f"{ms} ms"
    s = ms / 1000
    return f"{s:.1f} s" if s < 60 else f"{int(s // 60)} min {int(s % 60)} s"


def _status(status: str, stop: str) -> str:
    if status == "ok":
        return "cut off at its length limit" if stop in ("max_tokens", "length") else "answered"
    if status == "error":
        return "failed"
    if status == "stopped":
        return "stopped before it finished"
    if status == "sent":
        return "never heard back"
    return status


#: How a call was told to think, in words.
THINKING = {"adaptive": "on, as much as it needed", "adaptive/summarized": "on, as much as it needed",
            "disabled": "off", "reasoning": "on"}


# --- one call -------------------------------------------------------------------------------

def one_call(who, call_id: int) -> dict:
    """Why one call cost what it did: the cost split into what it is made of, what the prompt
    was made of, and everything else the log knows about it."""
    from django.db import models

    from .models import LLMPiece
    from .usage import everything

    try:
        r = everything(who).filter(pk=int(call_id)).values().first()
    except (TypeError, ValueError):
        raise Refused("a call is a number")
    if not r:
        raise Refused("there is no such call")
    zone = clock.zone_of(who)
    origin_key = _rows(f"SELECT {ORIGIN_SQL} FROM llm_requests WHERE id = %s", [r["id"]])[0][0]
    row = _call_row({**r, "origin": origin_key}, zone, _titles([origin_key], who.org_id))

    model = r["model"] or r["served_model"]
    usage = r["usage"] or {}
    split = costs.tokens_of(usage) if usage else {
        "input": r["input_tokens"], "output": r["output_tokens"],
        "cache_read": r["cache_read_tokens"], "cache_write": r["cache_write_tokens"], "cache_write_1h": 0}
    price = costs.price_of(model)
    parts = []
    if price and r["cost_usd"] is not None:
        per_in, per_out = price
        hour = min(split["cache_write_1h"], split["cache_write"])
        read_rate = per_in * costs.cache_read_of(model)

        def part(name, tokens, rate, said):
            if tokens or name == "Output":
                parts.append({"name": name, "tokens": tokens, "per_million": rate,
                              "cost": tokens * rate / costs.PER, "said": said})
        part("Fresh input", split["input"], per_in, "sent at the full input price")
        part("Read from the cache", split["cache_read"], read_rate,
             f"sent before and read back cheaply, at {round(costs.cache_read_of(model) * 100)}% of the input price")
        part("Written to the cache", split["cache_write"] - hour, per_in * costs.CACHE_WRITE,
             "kept for 5 minutes, at 125% of the input price")
        part("Written to the cache for an hour", hour, per_in * costs.CACHE_WRITE_HOUR,
             "kept for an hour, at twice the input price")
        part("Output", split["output"], per_out, "the answer and its thinking")
        if r["web_searches"]:
            parts.append({"name": "Web searches", "tokens": None, "count": r["web_searches"],
                          "cost": r["web_searches"] * costs.WEB_SEARCH, "said": "1 cent each"})
    worked = sum(p["cost"] for p in parts)
    logged = None if r["cost_usd"] is None else float(r["cost_usd"])
    for p in parts:
        p["money"] = _money(p["cost"])
        p["share"] = (p["cost"] / worked) if worked else 0
    # The log's own cost is the one that counts; a call priced by a rate of its own (OpenAI's
    # Decisions API, a picture) is said as that rather than by a sum that does not match it.
    matches = logged is not None and parts and abs(worked - logged) <= max(0.0005, logged * 0.02)

    pieces = []
    ids = [h for h in [r["system_piece"], r["tools_piece"]] if h] + [h for h in (r["message_pieces"] or []) if h]
    sizes = dict(LLMPiece.objects.filter(hash__in=ids).values_list("hash", "size")) if ids else {}
    if r["system_piece"]:
        pieces.append({"name": "Instructions", "chars": sizes.get(r["system_piece"])})
    if r["tools_piece"]:
        pieces.append({"name": "The list of tools it could use", "chars": sizes.get(r["tools_piece"])})
    msgs = [h for h in (r["message_pieces"] or []) if h]
    if msgs:
        known = [sizes[h] for h in msgs if h in sizes]
        pieces.append({"name": f"The conversation, {len(msgs)} message{'s' if len(msgs) != 1 else ''}",
                       "chars": sum(known) if known else None,
                       "last": sizes.get(msgs[-1])})
    sent_total = split["input"] + split["cache_read"] + split["cache_write"]
    same_turn = None
    if r["turn_id"]:
        n, c = everything(who).filter(turn_id=r["turn_id"]).aggregate(
            n=models.Count("id"), c=models.Sum("cost_usd")).values()
        same_turn = {"calls": n, "cost": _sum(c), "said": _money(_sum(c))}
    retries = 0
    if r["request_hash"]:
        retries = everything(who).filter(request_hash=r["request_hash"]).count() - 1

    return {
        **row,
        "why": _why(row, split, sent_total, parts, logged),
        "parts": parts,
        "parts_match": bool(matches),
        "sent": sent_total,
        "cached_share": (split["cache_read"] / sent_total) if sent_total else 0,
        "pieces": pieces,
        "request_bytes": r["request_bytes"],
        "max_tokens": r["max_tokens"],
        "effort": r["effort"] or "",
        "thinking": THINKING.get(r["thinking"] or "", r["thinking"] or ""),
        "first_word": _took(r["first_token_ms"]),
        "error": (r["error"] or "").strip().rstrip(":").strip()[:300],
        "same_turn": same_turn,
        "same_request": retries,
        "price": {"input": price[0], "output": price[1]} if price else None,
    }


def _why(row: dict, split: dict, sent: int, parts: list[dict], logged: float | None) -> str:
    """The one sentence that says why it cost what it did."""
    if logged is None:
        if row["status"] != "ok":
            after = f" after {row['took']}" if row["took"] != "not logged" else ""
            return (f"This call {row['status_said']}{after}, before it said what it used, "
                    "so it has no price.")
        return f"This call has no price: Rouh has no price for {row['model']}."
    if not parts:
        return f"This call cost {row['said']}, at {row['model']}'s own rate."
    # The two kinds of cache write are one cause, so they are added together before the largest
    # is picked and its share said.
    whole = sum(p["cost"] for p in parts)
    causes: dict[str, float] = {}
    for p in parts:
        name = "Written to the cache" if p["name"].startswith("Written to the cache") else p["name"]
        causes[name] = causes.get(name, 0.0) + p["cost"]
    big_name = max(causes, key=causes.get)
    big = {"name": big_name, "cost": causes[big_name]}
    share = round(big["cost"] / whole * 100) if whole else 0
    if big["name"] == "Output":
        cause = f"its answer was {split['output']:,} tokens long"
    elif big["name"] == "Read from the cache":
        cause = f"it sent {sent:,} tokens, most of them read back from the cache"
    elif big["name"].startswith("Written to the cache"):
        cause = (f"it wrote {split['cache_write']:,} tokens to the cache, which costs more than sending them"
                 + (", and read nothing back from it" if not split["cache_read"] else ""))
    elif big["name"] == "Web searches":
        cause = "it searched the web"
    else:
        cause = f"it sent {split['input']:,} tokens that were not in the cache"
    part = "nearly all of it" if share >= 99 else f"{share}% of it"
    return f"This call cost {row['said']} on {row['model']}, {part} because {cause}."
