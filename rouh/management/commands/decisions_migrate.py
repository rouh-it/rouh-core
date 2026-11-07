"""``python manage.py decisions_migrate``: every open ask, from every source, into Decisions.

Petar, 5 October 2026: "also migrate the current decisions to the new decision platform".
So every question or decision open anywhere in Rouh the day Decisions shipped - a task's
question in its meta, the heartbeat's and the quests' approvals, the goal steps
waiting on him, the one program's run questions, the jobs stopped at a prompt or on a step
for the live browser, the landings that collided, and what Synapse's dreaming left for his
Approve or Reject - is taken into the one model (`rouh/decisions.py`), with its own words,
its options, the address of its context and its history, and stays answerable at its
source and through Decisions alike: one row each, answered once.

It is the same taking-in Rouh does every thirty seconds while it runs (`decisions.sync`),
run here by itself so it can be counted: before and after, how many asks each source has
open, counted at the source itself, and how many open decisions each has; and every ask
the source has that has no open decision, with the reason. Run it as many times as you
like: what is already in is never made twice (one row per question, by its source and its
words), and nothing is answered, dismissed or changed at any source.

The deploy runs it (`manage.py predeploy`), so it runs on the live data with every deploy;
what it cannot reach there - the one program, when it is not answering - Rouh takes in at
start, and the next run counts it.

    python manage.py decisions_migrate
    python manage.py decisions_migrate --json
    python manage.py decisions_migrate --dry-run     # only count; take nothing in
"""
from __future__ import annotations

import asyncio
import json
import os

from django.core.management.base import BaseCommand, CommandError


def _one_questions():
    """The one program's open questions over its socket, or None when it does not answer."""
    from rouh.one_client import OneClient

    async def ask():
        return await asyncio.wait_for(OneClient().ask("questions"), timeout=5)

    try:
        got = asyncio.run(ask())
    except Exception:
        return None
    return [q for q in (got or {}).get("questions") or [] if isinstance(q, dict)]


def migrate(who, *, dry_run: bool = False) -> dict:
    """Count, take in, count again. The report, as a dict."""
    from rouh import decision_sources, decisions
    from rouh.config import config
    from rouh.models import Decision

    hooks = decision_sources.hooks
    if hooks.one_questions is None:
        asked = _one_questions()
        hooks.one_questions = lambda: asked
    if hooks.cfg is None:
        hooks.cfg = config

    def open_decisions() -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for source, sid in (Decision.objects.filter(
                user_id=str(who.user_id), org_id=str(who.org_id),
                status__in=decisions.ANSWERABLE + (decisions.ANSWERED, decisions.APPLYING))
                .values_list("source", "source_id")):
            out.setdefault(source, set()).add(sid)
        return out

    def census() -> dict[str, dict[str, str] | None]:
        out = {}
        for kind, source in decision_sources.sources().items():
            try:
                out[kind] = source.census(who)
            except Exception as exc:  # noqa: BLE001 - said in the report
                out[kind] = None
                out[f"{kind}:error"] = f"{type(exc).__name__}: {exc}"
        return out

    before_at, before_in = census(), open_decisions()
    synced = None
    if not dry_run:
        synced = decisions.sync(who, by="migration")
    after_at, after_in = census(), open_decisions()
    sources, missing, unread = {}, [], []
    gate_of = None
    for kind, source in decision_sources.sources().items():
        at = after_at.get(kind)
        sources[kind] = {
            "at_source_before": None if before_at.get(kind) is None else len(before_at[kind]),
            "decisions_before": len(before_in.get(kind, ())),
            "at_source_after": None if at is None else len(at),
            "decisions_after": len(after_in.get(kind, ())),
        }
        if at is None:
            unread.append({"source": kind, "why": after_at.get(f"{kind}:error")
                           or "it could not be read from here; Rouh takes it in at start"})
            continue
        for sid, line in at.items():
            if sid in after_in.get(kind, ()):
                continue
            if gate_of is None:
                # What the gate in front of the decisions said (`rouh/decision_gate.py`), newest
                # first, so the newest word on each question is the one kept.
                from rouh.models import DecisionGate

                gate_of = {}
                for g in DecisionGate.objects.filter(user_id=str(who.user_id),
                                                     org_id=str(who.org_id)).order_by("created_at"):
                    gate_of[(g.source, g.source_id)] = g
            gated = gate_of.get((kind, str(sid)))
            try:
                why = ("not taken in yet: this was a dry run" if dry_run
                       else f"kept from the owner by the gate ({gated.by}): {gated.reason}"
                       if gated is not None and gated.verdict == "clear"
                       else "still to be judged by the gate" if gated is not None
                       and gated.verdict == "pending"
                       else source.why_not(who, sid))
            except Exception as exc:  # noqa: BLE001
                why = f"{type(exc).__name__}: {exc}"
            missing.append({"source": kind, "id": sid, "what": line, "why": why})
    return {"sources": sources, "new": len(synced.new) if synced else 0,
            "not_taken_in": missing, "not_read": unread, "dry_run": dry_run}


class Command(BaseCommand):
    help = "Take every open ask from every source into Decisions, counting before and after."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="the report as JSON")
        parser.add_argument("--dry-run", action="store_true", help="only count")

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
        from rouh import telegram
        from rouh.tenancy import Tenancy

        who = telegram.phone_owner(Tenancy())
        if who is None:
            raise CommandError("There is no owner account, so there is nobody to ask.")
        got = migrate(who, dry_run=bool(options.get("dry_run")))
        if options.get("json"):
            self.stdout.write(json.dumps(got, ensure_ascii=False, indent=1))
            return
        self.stdout.write(report(got))


def report(got: dict) -> str:
    lines = ["source      open at source (before -> after)   open decisions (before -> after)"]
    for kind, n in got["sources"].items():
        def num(v):
            return "?" if v is None else str(v)
        lines.append(f"{kind:<11} {num(n['at_source_before']):>6} -> {num(n['at_source_after']):<23}"
                     f"{n['decisions_before']:>6} -> {n['decisions_after']}")
    lines.append(("Counted only (dry run). " if got["dry_run"] else "")
                 + f"{got['new']} new decision(s) taken in.")
    for u in got["not_read"]:
        lines.append(f"not read: {u['source']}: {u['why']}")
    if got["not_taken_in"]:
        lines.append(f"{len(got['not_taken_in'])} open at their source with no open decision:")
        for m in got["not_taken_in"]:
            lines.append(f"  {m['source']} {m['id']}: {m['what'][:90]} - {m['why']}")
    else:
        lines.append("Every ask open at its source has its open decision.")
    return "\n".join(lines)
