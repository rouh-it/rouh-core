"""The gate in front of the decisions: what may be put to the person at all.

Petar, 18 October 2026: "his decisions list is flooded with decisions nobody needed, and even
dismissing them costs him energy, which is unacceptable." That morning 41 waited on him: eight
meetings' worth of work Rouh could start, three nights of Synapse's housekeeping, ten genes to
review, and two dozen tasks whose research had ended with a question - "which pair do you want
to buy?", "which idea should a job build first?", "which next step, if any?".

So one gate stands in front of every source (`decision_sources`), and a question becomes a
decision only when both of these are true:

1. **Work he asked for has truly stopped, and cannot go on without him.** Finished work is not
   stopped: research ends with Rouh's recommendation on its page, never with a follow-up
   question.
2. **The answer is his to give**: it spends money, sends, publishes or commits something in his
   name, cannot be undone, needs a fact only he has, or is a choice that really changes what
   happens next and that Rouh cannot sensibly make itself.

Everything else is not created at all. Nothing of what the gate refused is shown to him: it is
written down here (`models.DecisionGate`, and a line in the log) for whoever debugs it.

**Who judges.** Each source says what its own questions are (`Source.gate`), where code can
tell: a run of the one program held on a hook is stopped and asks his leave, so it passes; a
night of Synapse's changes is Rouh's own housekeeping, kept on the Dreams page, so it does not.
Only a task's question, a goal step's decision and a job's call that spends, sends, publishes
and deletes nothing cannot be told apart by code - a purchase
the research was for and a purchase nobody asked about look the same - and those are read by a
model, once per question (its words hashed into its key), under its own pick on the Models
page, "Whether a question needs you" (`USE`). The sync never waits for it: a question still to
be judged is held back (pending), the desk asks the model between syncs (`judge_pending`), and
the next sync makes the decision or does not. When the model cannot be asked, it is tried again
later, and after a few tries a plain rule stands in (`fallback`): what spends, sends, publishes
or cannot be undone gets through, the rest does not.

**An approval is judged like any other question.** Petar, 2 November 2026, after a DNS change and
a certificate for the rouh.land move he had already asked for reached him as Decisions 385 and
386, each labelled "Cannot be undone": "I want ot undrstand what caused it and to change so
tomorrow I don't get a decision but whatever the new thing gets done". The label was the whole
of why they passed: `decision_sources.risk_of_tool` called anything it did not recognise
irreversible, and an approval's risk let it straight through. Now unknown is reversible, and
"irreversible" is kept for what deletes for good. A job's call his own words for the job already
asked for never reaches the queue at all (`rouh/his_word.py`); of what a job did queue, what
spends, sends, publishes or truly cannot be undone is his by what it is, and the rest is read by
the judge here like a task's question, told why Rouh's check of his words did not cover it
(`ApprovalSource.background`). One that is kept back is let go of at the source, so it never
waits in the queue for an answer nobody asked him for (`ApprovalSource.on_cleared`).

**A line it can say.** Every source must say what a yes would do and what waiting costs, the
two things each line on the Decisions page shows (`decisions.line_of`). A question that cannot
say them honestly is kept back by code, before anything else is asked of it (`verdict_for`),
rather than shown with an empty field.

**What was already waiting** is judged the same way, the first time each open decision is
seen after this shipped. One that fails is closed as cleared by Rouh (`decisions.CLEARED`),
never deleted: its own page says why and what Rouh recommends, and Open again puts it back
(`decisions.reopen`), with the gate told it is his (`by` "person") so it is never cleared
again. For a task, clearing also takes the question out of its meta (kept beside it as
`question_cleared`, which is what Open again puts back), labels the mark in its notes, and
takes the task out of waiting (`TaskSource.on_cleared`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass

from . import owner

log = logging.getLogger("rouh.decision_gate")

ASK, CLEAR, PENDING = "ask", "clear", "pending"

#: The Models page's pick for the judge (`modeldefaults.USES`), and its requests' purpose.
USE = PURPOSE = "decision_gate"
#: How long the judge has for one question.
MODEL_SECONDS = 90.0
#: How many questions are judged in one pass of the desk, so a backlog never holds it long.
PER_PASS = 8
#: After the judge could not answer: how long before it is asked again, times the tries.
RETRY_SECONDS = 300.0
#: After this many tries the plain rule stands in (`fallback`).
MOST_TRIES = 3

#: The risks that are his by what they are (`decisions.GATED`).
GATED = frozenset({"money", "sending", "publishing", "irreversible"})


@dataclass
class Verdict:
    verdict: str
    reason: str
    by: str = "code"
    recommendation: str = ""
    work: str = ""

    @property
    def asks(self) -> bool:
        return self.verdict == ASK


def let_through(reason: str) -> Verdict:
    return Verdict(ASK, reason)


def keep_back(reason: str, recommendation: str = "") -> Verdict:
    return Verdict(CLEAR, reason, recommendation=recommendation)


def _model():
    from .models import DecisionGate

    return DecisionGate


def _whose(who) -> dict:
    return {"org_id": str(who.org_id or ""), "user_id": str(who.user_id)}


def _cut(value, most: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def _of(row) -> Verdict:
    return Verdict(row.verdict, row.reason, by=row.by, recommendation=row.recommendation,
                   work=row.work)


def known(who, kind: str) -> dict:
    """Every judgement of this source's questions, by key: one read for a whole sync."""
    return {r.key: r for r in _model().objects.filter(**_whose(who), source=kind)}


def facts_of(source, who, ask) -> dict:
    """What the judge is given of a question: its own words, and what its source knows about
    the work it came from (`Source.background`)."""
    options = [{"label": _cut(o.get("label"), 140), "detail": _cut(o.get("detail"), 300)}
               for o in (ask.options or []) if isinstance(o, dict) and o.get("label")]
    rec = next((o.get("label") for o in ask.options or []
                if isinstance(o, dict) and o.get("id") == ask.recommended), "")
    try:
        background = source.background(who, ask) or ""
    except Exception:
        log.exception("decision gate: what %s knows about %s could not be read", source.kind,
                      ask.source_id)
        background = ""
    return {"source": source.kind, "label": source.label, "title": _cut(ask.title, 300),
            "question": _cut(ask.question, 1200), "why": _cut(ask.why, 800),
            "then": _cut(ask.then, 400), "context": _cut(ask.context, 200), "options": options,
            "recommended": _cut(rec, 140), "recommended_why": _cut(ask.recommended_why, 400),
            "risk": ask.risk or "reversible", "risk_note": _cut(ask.risk_note, 400),
            "urgency": ask.urgency or "soon", "background": str(background)[:6000]}


def verdict_for(who, source, ask, seen: dict | None = None) -> Verdict | None:
    """What the gate says of this question: let through, kept back, or None while it is still
    to be judged. Judged once under its key; never by a model here, which the desk does
    between syncs (`judge_pending`)."""
    from .decisions import missing_line

    m = _model()
    row = (seen.get(ask.key) if seen is not None
           else m.objects.filter(**_whose(who), source=source.kind, key=ask.key).first())
    # A question whose source cannot say what a yes would do or what waiting costs is never put
    # to him, whatever else is true of it (Petar, 18 October 2026: the Decisions page is a line
    # each, and no line shows an empty field). Asked of every sync, so a source that comes to
    # say both is judged as usual.
    lacking = missing_line(ask)
    if lacking:
        got = Verdict(CLEAR, lacking, by="code")
        if row is None or row.verdict != CLEAR or row.reason != lacking:
            _write(who, source.kind, ask, got, row=row, now=time.time())
        return got
    if row is not None and row.verdict == CLEAR and row.by == "code" and \
            row.reason.startswith("Its source could not say"):
        # It says both now: judged afresh, like a question seen for the first time.
        m.objects.filter(id=row.id).update(verdict=PENDING, by="", reason="", tries=0,
                                           facts=facts_of(source, who, ask))
        row.verdict = PENDING
    if row is not None and row.verdict in (ASK, CLEAR):
        return _of(row)
    try:
        got = source.gate(who, ask)
    except Exception:
        log.exception("decision gate: %s could not judge its own question %s", source.kind,
                      ask.source_id)
        got = None
    now = time.time()
    if got is not None:
        got.by = got.by or "code"
        _write(who, source.kind, ask, got, row=row, now=now)
        return got
    if row is None:
        try:
            m.objects.create(**_whose(who), source=source.kind, source_id=_cut(ask.source_id, 300),
                             key=ask.key, verdict=PENDING, title=_cut(ask.title, 300),
                             question=_cut(ask.question, 1200), facts=facts_of(source, who, ask),
                             created_at=now)
        except Exception:
            # Made by another pass a moment ago: it is pending either way.
            pass
    return None


def _write(who, kind: str, ask, got: Verdict, *, row=None, now: float) -> None:
    m = _model()
    # Kept as words, with the owner's marks filled in for whose decisions these are.
    fields = dict(verdict=got.verdict, by=got.by, reason=_cut(owner.say(got.reason, who), 600),
                  recommendation=_cut(owner.say(got.recommendation, who), 600), work=_cut(got.work, 20),
                  judged_at=now, title=_cut(ask.title, 300), question=_cut(ask.question, 1200))
    if row is not None:
        m.objects.filter(id=row.id).update(**fields)
    else:
        try:
            m.objects.create(**_whose(who), source=kind, source_id=_cut(ask.source_id, 300),
                             key=ask.key, created_at=now, **fields)
        except Exception:
            m.objects.filter(**_whose(who), source=kind, key=ask.key).update(**fields)
    if got.verdict == CLEAR:
        log.info("decision gate: kept %s %s from the person (%s): %s", kind, ask.source_id,
                 got.by, got.reason)


def mine(who, kind: str, key: str, source_id: str = "") -> None:
    """He opened it again himself: it is his, and never judged again (`decisions.reopen`)."""
    m = _model()
    now = time.time()
    reason = owner.say("‹Owner› opened it again ‹himself›.", who)
    done = m.objects.filter(**_whose(who), source=kind, key=key).update(
        verdict=ASK, by="person", reason=reason, judged_at=now)
    if not done:
        m.objects.create(**_whose(who), source=kind, source_id=_cut(source_id, 300), key=key,
                         verdict=ASK, by="person", reason=reason,
                         created_at=now, judged_at=now)


def fallback(facts: dict) -> Verdict:
    """The plain rule, when the judge cannot be asked: what is his by its risk gets through."""
    if (facts.get("risk") or "reversible") in GATED:
        return Verdict(ASK, "The judge could not be asked, and the answer "
                            + {"money": "spends money", "sending": "sends something",
                               "publishing": "publishes something",
                               "irreversible": "cannot be undone"}[facts["risk"]] + ".",
                       by="fallback")
    return Verdict(CLEAR, "The judge could not be asked, and the answer can be changed later.",
                   by="fallback", recommendation=facts.get("recommended") or "")


# --- the judge ---------------------------------------------------------------------------------

SYSTEM = """You are the gate in front of ‹owner›'s decisions list in Rouh, ‹his› assistant.

A part of Rouh wants to put a question to ‹owner›. ‹Owner›'s rule, 18 October 2026: a question reaches ‹him› only when BOTH of these are true.

1. Work ‹he› asked for has truly stopped and cannot go on without ‹him›. Finished work has not stopped. Research that is delivered, a page that is written, a plan that is laid out, an idea that is noted: a follow-up question at its end does not pass. Examples that do not pass: "buy now or later?", "which pair do you want to buy?" after a comparison ‹he› asked for, "which direction next?", "which idea should a job build first?", "which next step, if any, should a job take?", "what would you like done with this?", "did these messages lose you?", "is my reading right?".
2. The answer is ‹his› to give: it spends money, sends, publishes or commits something in ‹his› name, cannot be undone, needs a fact only ‹he› has (a person's name, an address, an account of ‹his›, a date ‹he› set), or is a choice between paths that really changes what happens next and that Rouh cannot sensibly make from what it knows.

A question that Rouh could settle with its own recommendation, and that can be changed later, does not pass: Rouh's recommendation stands on the work's page instead.
When the work really is stopped on something that spends money, sends or publishes in ‹his› name or cannot be undone, let it through.

Answer with exactly one JSON object and nothing else:
{"verdict": "ask" or "clear", "work": "stopped" or "finished" or "going", "reason": "<one plain sentence saying why>", "recommendation": "<when clear: Rouh's recommendation, in one sentence; empty when ask>"}"""


def prompt_for(facts: dict) -> str:
    lines = [f"Where it comes from: {facts.get('label') or facts.get('source')}"
             + (f" - {facts['context']}" if facts.get("context") else "")]
    if facts.get("title") and facts.get("title") != facts.get("question"):
        lines.append(f"Title: {facts['title']}")
    lines.append(f"Question: {facts.get('question') or ''}")
    for name, label in (("why", "Why it says it matters"), ("then", "What an answer does")):
        if facts.get(name):
            lines.append(f"{label}: {facts[name]}")
    if facts.get("options"):
        lines.append("The answers it offers:")
        lines += [f"- {o['label']}" + (f": {o['detail']}" if o.get("detail") else "")
                  for o in facts["options"]]
    if facts.get("recommended"):
        lines.append(f"Rouh's recommendation: {facts['recommended']}"
                     + (f" - {facts['recommended_why']}" if facts.get("recommended_why") else ""))
    lines.append(f"Risk: {facts.get('risk') or 'reversible'}"
                 + (f" - {facts['risk_note']}" if facts.get("risk_note") else ""))
    lines.append(f"Urgency: {facts.get('urgency') or 'soon'}")
    if facts.get("background"):
        lines += ["", "What is known about the work it came from:", facts["background"]]
    return "\n".join(lines)


def read_verdict(said: str) -> Verdict | None:
    hit = re.search(r"\{.*\}", said or "", re.S)
    try:
        got = json.loads(hit.group(0)) if hit else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or got.get("verdict") not in (ASK, CLEAR):
        return None
    work = str(got.get("work") or "")
    return Verdict(got["verdict"], _cut(got.get("reason"), 600) or "The judge gave no reason.",
                   by="model", recommendation=_cut(got.get("recommendation"), 600) if
                   got["verdict"] == CLEAR else "",
                   work=work if work in ("stopped", "finished", "going") else "")


async def ask_model(who, text: str) -> tuple[str, str]:
    """One question to the model the gate's pick is set to: (what it said, the model)."""
    from . import llm

    try:
        got = await llm.ask(USE, system=SYSTEM, messages=[{"role": "user", "content": text}],
                            max_tokens=2000, who=who, org_id=str(who.org_id) or None,
                            purpose=PURPOSE, timeout=MODEL_SECONDS, read_only=True)
    except llm.Cannot:
        return "", ""
    return got.text, got.model


async def judge_pending(who, most: int = PER_PASS) -> int:
    """Ask the judge about the questions still to be judged, oldest first: how many it decided.
    The desk syncs again when any was."""
    m = _model()
    now = time.time()

    def waiting():
        return list(m.objects.filter(**_whose(who), verdict=PENDING)
                    .exclude(retry_at__gt=now).order_by("created_at", "id")[:most])

    rows = await asyncio.to_thread(waiting)
    decided = 0
    for row in rows:
        got, model, why, unset = None, "", "", False
        try:
            said, model = await ask_model(who, prompt_for(row.facts or {}))
            unset = not model
            got = read_verdict(said) if model else None
            why = "no model is set for it" if unset else "its answer could not be read"
        except Exception as exc:
            why = f"{type(exc).__name__}: {str(exc)[:200]}"
        if got is None:
            tries = row.tries + 1
            if tries < MOST_TRIES and not unset:
                await asyncio.to_thread(lambda: m.objects.filter(id=row.id).update(
                    tries=tries, retry_at=time.time() + RETRY_SECONDS * tries,
                    reason=_cut(f"The judge could not answer: {why}", 600)))
                log.warning("decision gate: the judge could not answer about %s %s (%s); "
                            "asked again later", row.source, row.source_id, why)
                continue
            got = fallback(row.facts or {})
        await asyncio.to_thread(lambda: m.objects.filter(id=row.id, verdict=PENDING).update(
            verdict=got.verdict, by=got.by, reason=_cut(got.reason, 600),
            recommendation=_cut(got.recommendation, 600), work=got.work, model=model,
            tries=row.tries + 1, judged_at=time.time()))
        if got.verdict == CLEAR:
            log.info("decision gate: kept %s %s from the person (%s): %s", row.source,
                     row.source_id, got.by, got.reason)
        decided += 1
    return decided


def refused(who, limit: int = 100) -> list[dict]:
    """What the gate kept from him, newest first, for whoever debugs it
    (`manage.py decisions_gate`). Never drawn for him."""
    return [{"source": r.source, "source_id": r.source_id, "title": r.title,
             "question": r.question, "by": r.by, "reason": r.reason,
             "recommendation": r.recommendation, "work": r.work, "at": r.judged_at}
            for r in _model().objects.filter(**_whose(who), verdict=CLEAR)
            .order_by("-judged_at", "-id")[:limit]]
