"""What the models cost, day by day and model by model, out of the log.

Petar, 29 September 2026 (fr_f861da23d084): "On the full screen of the orb, I
would like an icon button next to volume that will give me a screen with
[stats] on LLM usage instead of orb. Pull from our log and give me a day by
day cost split in models".

The log is `llm_requests` (`rouh/llmlog.py`): one row for every request sent
to a model, each with its cost in dollars at list price (`rouh/costs.py`), so
this adds those up and invents nothing. A request whose model nobody has
priced has no cost, which is not the same as free: it is counted apart, as
`unpriced`, and the screen says how many there were rather than calling them
nothing.

Whose it is (`AGENTS.md`, "Whose data is it"): an administrator sees what their
organisation spent, because the organisation pays for it; anybody else sees
what they spent themselves. Either way the query names both the organisation
and, for a member, the person.

A day is a day on the person's own clock (`rouh/clock.py`), because "what did
Tuesday cost" means their Tuesday, not the server's.

Petar, 3 October 2026 (fr_f318d715a378): "I also want to see the number of
calls, not only the cost. Also, put somewhere: average cost per call for each
model. I'd like a separate table that shows me what type of calls are made".
So each model carries its calls and what one priced call cost on average, and
`purposes` adds the same up by the log's own `purpose` column, which every
request carries (the code that sent it names it, or it is named after that
code). The types are the log's, never a grouping made up here.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal

from . import clock, costs
from .config import model_name

#: How far back the screen looks unless it asks for another stretch, and the
#: most it may ask for.
DAYS = 30
MOST_DAYS = 366

_IMAGE = re.compile(r"^gpt-image-(\d+(?:\.\d+)?)-([a-z]+)$")

#: A few of the log's purposes in plain words. Anything not here is shown by
#: its own name, and the log's own name is always shown beside the words.
PURPOSES = {
    "turn": "Chat turns",
    "askai": "Ask AI on a page",
    "triage": "Mail triage",
    "run_summary": "Run summaries",
    "chat_title": "Chat titles",
    "reminder_title": "Reminder titles",
    "picture": "Pictures",
    "brief_world": "Morning brief: the world",
    "brief_ai": "Morning brief: AI news",
    "brief_history": "Morning brief: history",
    "case_ask": "Mail case questions",
    "gene_question": "Questions about a gene",
    "reply_check": "Reply checks",
    "reminder_words": "Reminder wording",
    "filing": "Filing",
    "subagent": "Sub-agents",
    "comment_pass": "Page comment answers",
    "word_review": "Word review",
    "meeting_pick_words": "Meeting guest profile picks",
    "meeting_slack": "Meetings: last said in Slack",
}


def purpose_named(purpose: str) -> str:
    """A purpose as a person reads it: "Chat turns", or "synapse explain"."""
    if not purpose:
        return "not said"
    return PURPOSES.get(purpose) or purpose.replace("_", " ")


def _money(cost: float) -> str:
    """`costs.money`, except that an amount under a hundredth of a cent - an
    embedding costs a thousandth - is said as that, not rounded to "0.00c"
    and so called free."""
    return "<0.01c" if 0 < cost < 0.0001 else costs.money(cost)


def _per_call(cost: Decimal, priced: int) -> dict:
    """What one priced call cost on average. Calls with no price are left out
    of it, because counting them as free would make every call look cheaper."""
    if not priced:
        return {"per_call": None, "per_call_said": "not priced"}
    each = float(cost) / priced
    return {"per_call": each, "per_call_said": _money(each)}


def named(model: str) -> str:
    """A model as a person says it: "Opus 5.5", "GPT Image 2.5 Flare"."""
    picture = _IMAGE.match(model or "")
    if picture:
        return f"GPT Image {picture.group(1)} {picture.group(2).capitalize()}"
    return model_name(model) or "unnamed model"


def everything(who):
    """Every row of the log this person may add up: their organisation's for an
    administrator, their own for anybody else."""
    from .models import LLMRequest

    rows = LLMRequest.objects.filter(org_id=who.org_id)
    if not who.is_admin:
        rows = rows.filter(user_id=who.user_id)
    return rows


def daily(who, days: int = DAYS, zone=None) -> dict:
    """Cost per day, split by model, for the last `days` days, newest first.

    Days with nothing on them are left out: a month of empty rows says less
    than the few that were spent. `models` lists every model in the stretch,
    dearest first, which is the order the screen gives them their colours in.
    """
    days = max(1, min(int(days or DAYS), MOST_DAYS))
    zone = zone or clock.zone_of(who)
    today = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    first = today - timedelta(days=days - 1)

    rows = everything(who).filter(started_at__gte=first.timestamp())

    by_day: dict[str, dict[str, dict]] = {}
    by_purpose: dict[str, dict] = {}
    for started, model, served, cost, purpose in rows.values_list(
            "started_at", "model", "served_model", "cost_usd", "purpose").iterator():
        day = datetime.fromtimestamp(started, zone).date().isoformat()
        kind = by_purpose.setdefault(purpose or "", {"cost": Decimal(0), "requests": 0, "unpriced": 0})
        kind["requests"] += 1
        if cost is None:
            kind["unpriced"] += 1
        else:
            kind["cost"] += cost
        one = by_day.setdefault(day, {}).setdefault(
            model or served or "", {"cost": Decimal(0), "requests": 0, "unpriced": 0})
        one["requests"] += 1
        if cost is None:
            one["unpriced"] += 1
        else:
            one["cost"] += cost

    totals: dict[str, dict] = {}
    out_days = []
    for day in sorted(by_day, reverse=True):
        models = sorted(by_day[day].items(), key=lambda kv: -kv[1]["cost"])
        for model, one in models:
            whole = totals.setdefault(model, {"cost": Decimal(0), "requests": 0, "unpriced": 0})
            for key in whole:
                whole[key] += one[key]
        cost = sum((one["cost"] for _, one in models), Decimal(0))
        out_days.append({
            "day": day,
            "cost": float(cost),
            "said": _money(float(cost)),
            "requests": sum(one["requests"] for _, one in models),
            "unpriced": sum(one["unpriced"] for _, one in models),
            "models": [{"model": model, "name": named(model), "cost": float(one["cost"]),
                        "said": _money(float(one["cost"])), "requests": one["requests"],
                        "unpriced": one["unpriced"]} for model, one in models],
        })

    total = sum((one["cost"] for one in totals.values()), Decimal(0))
    # The log was only started on 26 September 2026, so a month back may reach
    # to before it: the screen says where it begins rather than letting the
    # empty days before it read as days nothing was spent.
    began = everything(who).order_by("started_at").values_list("started_at", flat=True).first()
    return {
        "days": out_days,
        "models": [{"model": model, "name": named(model), "cost": float(one["cost"]),
                    "said": _money(float(one["cost"])), "requests": one["requests"],
                    "unpriced": one["unpriced"],
                    **_per_call(one["cost"], one["requests"] - one["unpriced"])}
                   for model, one in sorted(totals.items(), key=lambda kv: -kv[1]["cost"])],
        # Dearest first, then the busiest, so the types that cost nothing are
        # still in the order of how much they were used.
        "purposes": [{"purpose": purpose, "name": purpose_named(purpose),
                      "cost": float(one["cost"]), "said": _money(float(one["cost"])),
                      "requests": one["requests"], "unpriced": one["unpriced"],
                      **_per_call(one["cost"], one["requests"] - one["unpriced"])}
                     for purpose, one in sorted(by_purpose.items(),
                                                key=lambda kv: (-kv[1]["cost"], -kv[1]["requests"]))],
        "cost": float(total),
        "said": _money(float(total)),
        "requests": sum(d["requests"] for d in out_days),
        "unpriced": sum(d["unpriced"] for d in out_days),
        "from": first.date().isoformat(),
        "to": today.date().isoformat(),
        "stretch": days,
        "currency": "USD",
        "began": datetime.fromtimestamp(began, zone).date().isoformat() if began else None,
        "whose": "organisation" if who.is_admin else "yours",
    }
