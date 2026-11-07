"""Decisions: everything waiting on the person's answer, as one record, in one place.

Petar, 5 October 2026: "I feel like questions/answers should be a system unified thing. we
have it with tasks, we have it with quests, but somehow it is hooked to beats also. I think it
should be one model, one design, one place to look at them and make decisions. they can also
be appearing contextually in their places but also in this one place."

Until then five parts of Rouh asked him things, each in its own shape and its own place: a
task's question in its meta and its notes, answered on the task's page into its chat
(`waiting.py`, `answering.py`); the heartbeat's and the quests' approvals in their own table,
answered on the Heartbeat page or with "yes 12" on Telegram (`heartbeat.py`); a goal step's
decision in its meta, answered on its How to do it page (`goals.py`); a run of the one
program asking leave, answered on its card or its terminal (`one/questions.py`); and a landing
that collided, answered by voice with one of four choices (`conflicts.py`). `DECISIONS.md` at
the top of the repository is the audit of all of them.

**One record.** Each of those is still asked and kept by its own source, which knows what an
answer does. What is new is one row per question here (`models.Decision`), in one shape: what
it is, the question in plain words, why it matters and what happens next, the options with
what each one means, Rouh's recommendation and why, whether he may answer in his own words,
how urgent it is and how risky, where it stands, the answer, who gave it, where, and its whole
history (`models.DecisionEvent`). Every place that shows a question draws this row with the
same component (`static/decision.js`): the Decisions page, the task's page, the Heartbeat and
quest pages, a run's card.

**Taken in, not copied by hand.** `sync` asks every source what it asks now
(`decision_sources`), adds a row for anything new, keeps the words of the open ones up to
date, and closes the ones the source no longer asks: answered somewhere else, which it reads
back from the source (`settled`), or withdrawn when the source simply stopped asking. So
nothing is migrated by a script and nothing waiting is lost: the first sync after this ships
takes in everything open, and every sync after keeps it true.

**One way back.** An answer, from any screen, from Telegram or from Rouh's tool with his own
words, goes through `answer`, which checks it, writes it down and gives it a short window to
be undone (`UNDO_SECONDS`); then the desk hands it to its source (`apply_due`), once, and
writes down what the source said. Answering anywhere answers it everywhere, because there is
only the one row and the one way back. A second answer to a question already answered is
refused, and the same answer again is a no-op.

**A number to say.** Every decision is numbered, Decision 1, Decision 2, each person's in the
order asked (`decision_numbers`, Petar, 18 October 2026, in place of the a482 handles): given
when it is first taken in, never given twice, and shown wherever it is drawn as "Decision 42"
(or "#42" where there is little room). What the person says or types for one is read
tolerantly (`ref_of`), so "forty-two" and "decision 42" are 42. The number is the only name a
decision has: an old handle (a482) or a job's old id for its ask (r24) names none (Petar, 29
October 2026: "if we don't need the r24 format, just get rid of it altogether"). In code, an int is a row's own id (`Decision.id`), which
the pages' presses and Telegram's buttons carry; words are the person's reference.

**The safety rules are the same as everywhere else in Rouh, and are kept here in code.**

- A question that spends money, sends something to someone, publishes, or cannot be undone
  (`GATED`) needs that risk itself confirmed, by its own words, before an option that carries
  it out is accepted (`confirm`). On the screen that is a second press that names the risk; on
  Telegram a second button; from Rouh's tool, his own yes to that risk, passed as such.
- Rouh's recommendation is drawn, never picked: nothing here answers a question without an
  answer given. "Rouh, decide this one" (`delegate`) is his own press or words, and is offered
  only on a reversible question with a recommendation.
- Only the person answers. The page is his signed-in session, Telegram his own chat
  (`telegram_chat._press`), and the tool his own words in the turn (`tools._decisions`); a
  turn nobody asked for - a heartbeat, a reminder, an email being handled - may read the list
  and never answer from it. Nothing in a mail, a page or a tool's output answers a question.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

from . import answered_in_chat, decision_gate

log = logging.getLogger("rouh.decisions")

#: Where a decision stands.
OPEN, SNOOZED, ANSWERED, APPLYING, APPLIED, FAILED = (
    "open", "snoozed", "answered", "applying", "applied", "failed")
EXPIRED, WITHDRAWN, DISMISSED = "expired", "withdrawn", "dismissed"
#: Closed by Rouh because it never needed him (`rouh/decision_gate.py`): kept, with why and what
#: Rouh recommends, and opened again with one press on its own page (`reopen`).
CLEARED = "cleared"
STATUSES = (OPEN, SNOOZED, ANSWERED, APPLYING, APPLIED, FAILED, EXPIRED, WITHDRAWN, DISMISSED,
            CLEARED)
#: Still waiting on him: a snoozed one too, only out of sight until its time.
WAITING = (OPEN, SNOOZED)
#: Answerable now: a failed one may be answered again.
ANSWERABLE = (OPEN, SNOOZED, FAILED)
#: Finished one way or another.
DONE = (APPLIED, EXPIRED, WITHDRAWN, DISMISSED, CLEARED)

#: How an answer is given.
TYPES = ("choice", "multi", "yes_no", "text", "date", "approval")
#: How soon it matters, most urgent first.
URGENCY = ("now", "today", "soon", "whenever")
URGENCY_WORDS = {"now": "Now", "today": "Today", "soon": "Soon", "whenever": "Whenever"}
#: What answering it may do that cannot be taken back.
RISKS = ("reversible", "money", "sending", "publishing", "irreversible")
GATED = frozenset({"money", "sending", "publishing", "irreversible"})
RISK_WORDS = {"reversible": "Can be changed later", "money": "Spends money",
              "sending": "Sends something to someone", "publishing": "Publishes something",
              "irreversible": "Cannot be undone"}
#: Where an answer was given. A source answered on its own page says its own name. "offline" is
#: an answer given on a device with no connection, carried out from its outbox (`rouh/offline.py`).
CHANNELS = ("screen", "telegram", "voice", "email", "offline")

#: How long an answer waits before it goes back to its source, so it can be undone.
UNDO_SECONDS = 8.0
#: The longest anything kept here may be.
QUESTION_MOST = 1200
TEXT_MOST = 4000
LABEL_MOST = 140
DETAIL_MOST = 400
OPTIONS_MOST = 8
#: How many lines of what there is to read about one option (`more_of`).
MORE_FACTS = 12
#: How many finished ones the history shows.
HISTORY_MOST = 200
#: How many small questions one decision may hold (`items`).
ITEMS_MOST = 400
ITEM_TEXT_MOST = 600

#: What a decision folded into a grouped one says, so the history can leave it out: it was
#: never answered, its question goes on in the group.
FOLDED = "Folded into #"


class Refused(ValueError):
    """An answer, a snooze or an undo that is not accepted, with the words that say why."""


class NeedsConfirm(Refused):
    """An answer that carries a gated risk, given without that risk confirmed."""

    def __init__(self, risk: str, note: str):
        self.risk, self.note = risk, note
        said = (note or "confirm it first").strip().rstrip(".")
        super().__init__(f"{RISK_WORDS.get(risk, risk)}: {said}. Confirm that itself before "
                         "it goes.")


@dataclass
class Ask:
    """What a source asks now, in the one shape (`decision_sources`)."""

    source_id: str
    #: Which question of that source; a new question is a new key.
    key: str
    title: str
    question: str
    why: str = ""
    then: str = ""
    link: str = ""
    context: str = ""
    project: str = ""
    batch: str = ""
    #: [{"id", "label", "detail", "go", "more"?}], `more` what there is to read about it
    #: before picking it (`more_of`).
    options: list = field(default_factory=list)
    recommended: str = ""
    recommended_why: str = ""
    allow_other: bool = True
    answer_type: str = "choice"
    urgency: str = "soon"
    due_at: float | None = None
    risk: str = "reversible"
    risk_note: str = ""
    prepared: list = field(default_factory=list)
    #: The small questions it holds, each answered with its options, all at once or one by
    #: one: [{"id", "label", "text"?, "href"?, "detail"?, "why"?, "sides"?}].
    items: list = field(default_factory=list)
    asked_at: float | None = None
    #: What happened to it at its source before it was taken in, kept as its first events:
    #: [{"at", "kind", "detail"}].
    history: list = field(default_factory=list)
    #: Its line on the Decisions page and in the tool's list (`line_of`), Petar, 18 October
    #: 2026: what a yes would do, concretely ("Sends one email to Sam"), and what waiting
    #: costs ("Task 90 is stopped until you answer", or "Nothing waits on it"). Both are
    #: required: a source that cannot say them honestly is refused by the gate
    #: (`missing_line`), never shown with an empty field.
    yes_does: str = ""
    wait_cost: str = ""
    #: Whether something is held up until he answers, which puts it first with the dated ones.
    blocks: bool = False
    #: A few words each, drawn as chips after the source's own: its project, its silo.
    tags: list = field(default_factory=list)
    #: Rouh's recommendation in a few words when it is not one of the options.
    advice: str = ""
    #: One sentence on what it is for him, under what it is, when its title alone does not say
    #: (a gene: what it does).
    about: str = ""
    #: "action" when the source knows it is a hands-on step only he can do (`rouh/actions.py`),
    #: "decision" when it knows it is a choice, "" to have it read once (`actions.read_pending`).
    kind: str = ""
    #: What an action's own page shows, where the source can say it: {"do", "minutes", "steps":
    #: [{"text", "href"?}], "after", "check", "story", "work": [{"label", "href"}]}.
    action: dict = field(default_factory=dict)


@dataclass
class Settled:
    """What became of a question its source no longer asks."""

    status: str
    #: The answer, as words, when it was answered at the source.
    said: str = ""
    channel: str = ""
    result: str = ""
    #: Who answered it, when it was not the person: "itself" for one that closed by itself at
    #: its source (a promise a later Slack message showed kept, `rouh/slack_promises.py`).
    by: str = ""


@dataclass
class Applied:
    """What the source said when an answer went back to it."""

    ok: bool
    result: str = ""
    #: Some of its items still wait (answered one by one, or one that could not be carried
    #: out): the decision is open again for the rest, rather than finished.
    reopen: bool = False


def key_of(*parts) -> str:
    """A question's key: its source's id and the words it asked, hashed, so the same words
    asked again are the same question and new words are a new one."""
    text = "\x1f".join(" ".join(str(p or "").split()) for p in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _cut(value, most: int) -> str:
    return " ".join(str(value or "").split())[:most] if most < 600 else str(value or "").strip()[:most]


def options_of(raw) -> list[dict]:
    """Options as the record keeps them: each an id, a label, a line saying what it means,
    and whether picking it carries out the question's risk. Labels are unique."""
    out, seen = [], set()
    for i, one in enumerate(raw or []):
        if isinstance(one, str):
            one = {"label": one}
        if not isinstance(one, dict):
            continue
        label = _cut(one.get("label"), LABEL_MOST)
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        out.append({"id": _cut(one.get("id"), 40) or f"o{i + 1}", "label": label,
                    "detail": _cut(one.get("detail"), DETAIL_MOST),
                    "go": bool(one.get("go"))})
        href = _cut(one.get("href"), 600)
        if href and (href.startswith("/") and not href.startswith("//") or _web(href)):
            # A link, not an answer: it opens a page, such as a mail case's own (Petar, 11
            # October 2026: "Open the case"). It is never taken as an answer (`_check`).
            out[-1]["href"] = href
        if one.get("each"):
            # What it is called on one of the items it holds: "Approve", for "Approve all 32".
            out[-1]["each"] = _cut(one.get("each"), 40)
        more = more_of(one.get("more"))
        if more:
            out[-1]["more"] = more
        if len(out) == OPTIONS_MOST:
            break
    return out


def _web(value) -> str:
    said = _cut(value, 600)
    return said if re.match(r"https?://", said) else ""


def more_of(raw) -> dict:
    """What there is to read about one option before picking it, folded under it on the card
    until it is opened: {"facts": [[label, value]], "photo"?, "href"?, "href_label"?}. Petar,
    9 October 2026, of two LinkedIn profiles to pick between: "I should be able to expand them
    and see the rest of the information you have on them"."""
    if not isinstance(raw, dict):
        return {}
    facts = [[_cut(f[0], 40), _cut(f[1], DETAIL_MOST)] for f in raw.get("facts") or []
             if isinstance(f, (list, tuple)) and len(f) == 2 and _cut(f[0], 40) and _cut(f[1], 40)]
    out = {"facts": facts[:MORE_FACTS]} if facts else {}
    for name in ("photo", "href"):
        if _web(raw.get(name)):
            out[name] = _web(raw.get(name))
    if out.get("href"):
        out["href_label"] = _cut(raw.get("href_label"), 60) or "Open it"
    return out


# --- who ---------------------------------------------------------------------------------------


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def _models():
    from . import models

    return models


def _event(row, kind: str, *, by: str = "", channel: str = "", detail: str = "",
           at: float | None = None) -> None:
    _models().DecisionEvent.objects.create(
        decision_id=row.id, user_id=row.user_id, org_id=row.org_id, kind=kind,
        by=str(by or "")[:120], channel=str(channel or "")[:40], detail=str(detail or "")[:2000],
        at=at or time.time())


# --- taking them in from their sources -----------------------------------------------------------


@dataclass
class Synced:
    """What a sync changed: new questions, and whether anything at all moved."""

    new: list = field(default_factory=list)
    changed: bool = False


_FIELDS = ("title", "question", "why", "then", "link", "context", "project", "batch", "options",
           "recommended", "recommended_why", "allow_other", "answer_type", "urgency", "due_at",
           "risk", "risk_note", "prepared", "items", "line")


def _fields_of(ask: Ask) -> dict:
    options = options_of(ask.options)
    ids = {o["id"] for o in options}
    return {
        "title": _cut(ask.title, 300) or "A question",
        "question": _cut(ask.question, QUESTION_MOST) or _cut(ask.title, 300),
        "why": _cut(ask.why, 2000), "then": _cut(ask.then, 600),
        "link": _cut(ask.link, 600), "context": _cut(ask.context, 200),
        "project": _cut(ask.project, 80), "batch": _cut(ask.batch, 200),
        "options": options,
        "recommended": ask.recommended if ask.recommended in ids else "",
        "recommended_why": _cut(ask.recommended_why, 600) if ask.recommended in ids else "",
        "allow_other": bool(ask.allow_other),
        "answer_type": ask.answer_type if ask.answer_type in TYPES else "choice",
        "urgency": ask.urgency if ask.urgency in URGENCY else "soon",
        "due_at": ask.due_at,
        "risk": ask.risk if ask.risk in RISKS else "irreversible",
        "risk_note": _cut(ask.risk_note, 600),
        "prepared": [p for p in (ask.prepared or []) if isinstance(p, dict)][:12],
        "items": items_of(ask.items),
        "line": {"yes": _cut(ask.yes_does, 400), "wait": _cut(ask.wait_cost, 300),
                 "blocks": bool(ask.blocks), "advice": _cut(ask.advice, 120),
                 "about": _cut(ask.about, 400),
                 "tags": [t for t in (_cut(x, 40) for x in ask.tags or []) if t][:4]},
    }


def missing_line(ask: Ask) -> str:
    """Why this question cannot be put to him as a line, or "": a source must say what a yes
    does and what waiting costs (Petar, 18 October 2026), and one that cannot is refused
    rather than shown with an empty field."""
    gone = [what for what, said in (("what a yes would do", ask.yes_does),
                                    ("what waiting costs", ask.wait_cost))
            if not " ".join(str(said or "").split())]
    return ("Its source could not say " + " or ".join(gone) + ".") if gone else ""


def items_of(raw) -> list[dict]:
    """A decision's small questions as the record keeps them: each an id, a label, and what
    there is to read about it. Ids are unique."""
    out, seen = [], set()
    for one in raw or []:
        if not isinstance(one, dict):
            continue
        ident = _cut(one.get("id"), 80)
        if not ident or ident in seen:
            continue
        seen.add(ident)
        item = {"id": ident, "label": _cut(one.get("label"), 300) or ident}
        for name, most in (("text", ITEM_TEXT_MOST), ("href", 600), ("detail", DETAIL_MOST),
                           ("why", ITEM_TEXT_MOST)):
            if one.get(name):
                item[name] = _cut(one.get(name), most)
        sides = [{k: _cut(v, ITEM_TEXT_MOST if k == "text" else 300) for k, v in side.items()
                  if k in ("label", "text", "href") and v}
                 for side in one.get("sides") or [] if isinstance(side, dict)][:3]
        if sides:
            item["sides"] = sides
        # Which of the question's answers this item may take, when not every one: a hard limit
        # of a mail case is never given for good, only allowed once or declined.
        if isinstance(one.get("options"), list):
            item["options"] = [_cut(o, 40) for o in one["options"] if _cut(o, 40)][:OPTIONS_MOST]
        # What an answer is called for this item when it is not what it is called for the rest:
        # for an ask about one of Petar's tasks, giving it what it needs is letting them edit
        # that task, never a grant (MAIL.md D28).
        if isinstance(one.get("names"), dict):
            names = {_cut(k, 40): _cut(v, 80) for k, v in one["names"].items()
                     if _cut(k, 40) and _cut(v, 80)}
            if names:
                item["names"] = names
        out.append(item)
        if len(out) == ITEMS_MOST:
            break
    return out


def sync(who, kinds=None, *, by: str = "") -> Synced:
    """Bring the record level with what every source asks now (or only `kinds`).

    A source that cannot be read this time (the one program not connected, the workspace not
    there) answers None, and nothing of it is changed: a question is only closed because its
    source said it no longer asks it, never because the source could not be reached."""
    from . import decision_sources

    work = _Synchronization(who, by)
    # A row made by code older than numbers, during a deploy, is given one now.
    work.numbers.fill()
    work._wake_snoozed()
    for kind, source in decision_sources.sources().items():
        if kinds is not None and kind not in kinds:
            continue
        work._sync_source(kind, source)
    return work.out


class _Synchronization:
    """One sync's state, shared by its wake, intake, write and settlement stages."""

    def __init__(self, who, by: str):
        self.models = _models()
        self.out = Synced()
        self.now = time.time()
        self.whose = _whose(who)
        self.numbers = _Numbers(who)
        self.who = who
        self.by = by

    def _wake_snoozed(self) -> None:
        """Wake only the snoozes due at this sync's time."""
        # Snoozed ones whose time has come are waiting again.
        for row in self.models.Decision.objects.filter(
                **self.whose, status=SNOOZED, snoozed_until__lte=self.now):
            if self.models.Decision.objects.filter(id=row.id, status=SNOOZED).update(
                    status=OPEN, snoozed_until=None, updated_at=self.now):
                _event(row, "woke", detail="Its snooze ran out.")
                self.out.changed = True

    def _sync_source(self, kind, source) -> None:
        """Read and gate one source, then settle what it no longer asks."""
        try:
            asks = source.collect(self.who)
        except Exception:
            log.exception("decisions: %s could not be read; its questions are left as they were",
                          kind)
            return
        if asks is None:
            return
        seen = set()
        rows = {r.key: r for r in self.models.Decision.objects.filter(**self.whose, source=kind)
                .exclude(status__in=(APPLIED, DISMISSED))}
        judged = decision_gate.known(self.who, kind)
        for ask in asks:
            if not ask.key or ask.key in seen:
                continue
            seen.add(ask.key)
            row = rows.get(ask.key)
            if row is not None and row.status == CLEARED:
                continue
            # The gate: only what truly needs him becomes a decision, and what was already
            # waiting is judged the same way the first time it is seen (`decision_gate`).
            verdict = decision_gate.verdict_for(self.who, source, ask, judged)
            if verdict is None:
                continue              # still to be judged; the desk asks between syncs
            if not verdict.asks:
                if row is not None and row.status in ANSWERABLE:
                    _clear(row, verdict)
                    self.out.changed = True
                elif row is not None:
                    continue          # an answer on its way goes on its way
                try:
                    source.on_cleared(self.who, ask, verdict)
                except Exception:
                    log.exception("decisions: %s could not let go of %s", kind, ask.source_id)
                continue
            self._receive(kind, ask, row)
        self._settle_missing(kind, source, rows, seen)

    def _receive(self, kind, ask, row) -> None:
        """Create or refresh a question that passed the gate, with its events."""
        fields = _fields_of(ask)
        from . import actions

        if row is None:
            row = self.numbers.create(source=kind, source_id=_cut(ask.source_id, 300),
                                      key=ask.key, status=OPEN, created_at=ask.asked_at or self.now,
                                      updated_at=self.now,
                                      kind=ask.kind if ask.kind in actions.KINDS else "",
                                      action=actions.content_of(ask.action), **fields)
            if row is None:
                # Answered or dismissed before, under the same words: not asked again.
                return
            for h in ask.history or []:
                if isinstance(h, dict) and h.get("detail"):
                    _event(row, str(h.get("kind") or "history")[:40], by=kind,
                           detail=str(h["detail"]), at=float(h.get("at") or 0) or self.now)
            _event(row, "asked", by=kind, detail=row.question[:600], at=ask.asked_at or self.now)
            if self.by:
                _event(row, "taken in", by=self.by, detail=f"Taken in from its {kind} as it stood.")
            self.out.new.append(row.id)
            self.out.changed = True
            return
        changes = {k: v for k, v in fields.items() if getattr(row, k) != v}
        if ask.kind in actions.KINDS and ask.kind != row.kind:
            changes["kind"] = ask.kind
        merged = actions.merged(row.action, ask.action)
        if merged != (row.action or {}):
            changes["action"] = merged
        if row.status == WITHDRAWN and actions.closed_by_itself(row):
            # An action withdrawn by itself because its work was finished or put away is not
            # asked again by a source that has not noticed yet (`actions.withdraw_stale`).
            if changes.get("action"):
                self.models.Decision.objects.filter(id=row.id).update(
                    action=changes["action"], updated_at=self.now)
            return
        if row.status in (WITHDRAWN, EXPIRED):
            # The source asks it again, in the same words.
            changes.update(status=OPEN, resolved_at=None, result="")
            _event(row, "asked", by=kind, detail="Asked again.")
        if changes:
            self.models.Decision.objects.filter(id=row.id).update(updated_at=self.now, **changes)
            self.out.changed = True

    def _settle_missing(self, kind, source, rows, seen) -> None:
        """Close waiting questions only after their source was read successfully."""
        for key, row in rows.items():
            if key in seen or row.status not in WAITING:
                continue
            try:
                got = source.settled(self.who, row)
            except Exception:
                log.exception("decisions: what became of %s %s could not be read", kind, row.id)
                got = None
            got = got or Settled(WITHDRAWN, result="It no longer asks this.")
            if got.status not in DONE:
                got.status = WITHDRAWN
            answer = dict(row.answer or {})
            if got.said:
                answer = {"choice": [], "text": "", "said": _cut(got.said, TEXT_MOST)}
            done = self.models.Decision.objects.filter(id=row.id, status__in=WAITING).update(
                status=got.status, answer=answer, channel=_cut(got.channel, 40),
                result=_cut(got.result, 2000), resolved_at=self.now, updated_at=self.now,
                answered_at=self.now if got.said else row.answered_at,
                **({"answered_by": _cut(got.by, 120)} if got.by else {}))
            if done:
                _event(row, got.status if got.status != APPLIED else "answered",
                       channel=got.channel, detail=got.said or got.result)
                self.out.changed = True


def _clear(row, verdict) -> None:
    """Closed by Rouh, because the gate found it never needed him (`decision_gate`): kept, with
    why and what Rouh recommends instead, and opened again from its own page (`reopen`)."""
    now = time.time()
    said = verdict.reason.rstrip(".") + "."
    if verdict.recommendation:
        said += " Rouh recommends: " + verdict.recommendation.rstrip(".") + "."
    done = _models().Decision.objects.filter(id=row.id, status__in=ANSWERABLE).update(
        status=CLEARED, resolved_at=now, updated_at=now, answered_by="rouh", channel="gate",
        result=_cut(f"Cleared by Rouh: {said}", 2000))
    if done:
        _event(row, "cleared", by="rouh", channel="gate", detail=said)


def waiting_for(who, source: str, source_id: str) -> bool:
    """Whether a decision of this source under this id still waits on the person."""
    return _models().Decision.objects.filter(**_whose(who), source=source, source_id=str(source_id),
                                             status__in=ANSWERABLE).exists()


def record_closed(who, source: str, *, source_id: str, key: str, title: str, question: str,
                  context: str = "", link: str = "", said: str = "", channel: str = "", by: str = "",
                  result: str = "") -> int | None:
    """Something its source closed by itself while it was not a decision of its own (a late
    promise made to him in Slack that he chased or waited on, kept by a later message), written
    into the history as one answered, so it is seen there and can be undone (`reopen`). The new
    row's id; None when it was written before."""
    now = time.time()
    row = _Numbers(who).create(
        source=source, source_id=_cut(source_id, 300), key=key, status=APPLIED, created_at=now,
        updated_at=now, title=_cut(title, 300) or "A question", question=_cut(question, QUESTION_MOST),
        context=_cut(context, 200), link=_cut(link, 600), options=[], allow_other=False,
        answer={"choice": [], "text": "", "said": _cut(said, TEXT_MOST)}, answered_by=_cut(by, 120),
        channel=_cut(channel, 40), result=_cut(result, 2000), answered_at=now, resolved_at=now)
    if row is None:
        return None
    _event(row, "asked", by=source, detail=row.question[:600], at=now)
    _event(row, "answered", by=by or source, channel=channel, detail=result or said, at=now)
    return row.id


class _Numbers:
    """Numbering one person's decisions: the next is one more than the highest they were
    ever given, so they go 1, 2, 3 with no gaps (`decision_numbers`)."""

    def __init__(self, who):
        self.whose = _whose(who)

    def next(self) -> int:
        from django.db.models import Max

        got = _models().Decision.objects.filter(**self.whose).aggregate(n=Max("number"))["n"]
        return (got or 0) + 1

    def create(self, **fields):
        """A new decision with the next number; None when the question is already a row."""
        from django.db import IntegrityError, transaction

        m = _models()
        for _ in range(8):
            try:
                with transaction.atomic():
                    return m.Decision.objects.create(**self.whose, number=self.next(), **fields)
            except IntegrityError:
                if m.Decision.objects.filter(**self.whose, source=fields["source"],
                                             key=fields["key"]).exists():
                    return None
                # Another process took that number at the same moment: the next one, then.
        raise RuntimeError("no number could be given to a new decision")

    def fill(self) -> None:
        from django.db import IntegrityError, transaction

        m = _models()
        for row_id in m.Decision.objects.filter(**self.whose, number__isnull=True).order_by(
                "id").values_list("id", flat=True):
            for _ in range(8):
                try:
                    with transaction.atomic():
                        m.Decision.objects.filter(id=row_id, number__isnull=True).update(
                            number=self.next())
                    break
                except IntegrityError:
                    continue


def numbers_of_sources(who, source: str, source_ids, *, take_in: bool = True) -> dict[str, int]:
    """The numbers of the decisions a source asks under these ids, for a message or a page
    that source draws by itself (the heartbeat's Telegram, a landing's conflict, the Dreams
    tab): its questions are taken in first (`take_in`), so the numbers are there to say.
    {source id: number}, the newest one still waiting first; one that is not a decision
    (yet) is left out."""
    ids = [str(i) for i in source_ids or []]
    if not ids:
        return {}
    if take_in:
        try:
            sync(who, kinds={source})
        except Exception:
            log.exception("decisions: %s could not be taken in for its numbers", source)
    out: dict[str, int] = {}
    rows = (_models().Decision.objects.filter(**_whose(who), source=source, source_id__in=ids,
                                             number__isnull=False)
            .values_list("source_id", "number", "status", "created_at", "id"))
    for sid, number, _status, _at, _id in sorted(
            rows, key=lambda r: (r[2] in DONE, -(r[3] or 0), -r[4])):
        out.setdefault(sid, number)
    return out


def source_of_ref(who, text, source: str) -> str | None:
    """The source id the person's reference names, when it is a decision of that source still
    waiting: "yes decision 42" on Telegram, for the approval it is. None otherwise."""
    ref = ref_of(str(text or ""))
    if ref is None:
        return None
    row = (_models().Decision.objects.filter(**_whose(who), **ref, source=source,
                                            status__in=WAITING).first())
    return row.source_id if row is not None else None


# --- reading them -------------------------------------------------------------------------------


def as_dict(row, *, events: list | None = None) -> dict:
    """One decision as every place draws it."""
    from . import decision_sources

    source = decision_sources.sources().get(row.source)
    now = time.time()
    gated = row.risk in GATED
    rec = next((o for o in row.options or [] if o.get("id") == row.recommended), None)
    out = {
        "id": row.id, "number": row.number, "name": name_of(row), "source": row.source,
        "source_label": source.label if source else row.source.title(),
        "source_id": row.source_id, "link": row.link, "context": row.context,
        "project": row.project, "batch": row.batch, "title": row.title,
        "question": row.question, "why": row.why, "then": row.then,
        "prepared": row.prepared or [], "options": row.options or [],
        "items": row.items or [],
        "recommended": row.recommended, "recommended_why": row.recommended_why,
        "allow_other": row.allow_other, "answer_type": row.answer_type,
        "urgency": row.urgency, "urgency_words": URGENCY_WORDS.get(row.urgency, row.urgency),
        "due_at": row.due_at, "risk": row.risk, "risk_words": RISK_WORDS.get(row.risk, row.risk),
        "risk_note": row.risk_note, "gated": gated,
        "status": row.status, "snoozed_until": row.snoozed_until,
        "answer": row.answer or {}, "answered_by": row.answered_by, "channel": row.channel,
        "result": row.result, "apply_at": row.apply_at,
        "undo_left": max(0.0, (row.apply_at or 0) - now) if row.status == ANSWERED else 0.0,
        "created_at": row.created_at, "updated_at": row.updated_at,
        "answered_at": row.answered_at, "resolved_at": row.resolved_at,
        "can_dismiss": bool(source and source.can_dismiss) and row.status in ANSWERABLE,
        # Closed by itself at its source, and can be opened again there (`reopen`).
        "by_itself": str(row.answered_by or "") == "itself",
        "can_reopen": bool(source and (row.status == CLEARED or (
            row.status == APPLIED and source.can_reopen(row)))),
        # Closed by Rouh because it never needed him (`decision_gate`).
        "cleared": row.status == CLEARED,
        # "Rouh, decide this one": only what can be changed later, with a recommendation.
        "can_delegate": (not gated and row.risk == "reversible" and rec is not None
                         and row.status in ANSWERABLE),
        "text_acts": bool(source and source.text_acts),
        "stale": "",
        # Decided by a trusted contact Petar gave authority over this (`rouh/delegation.py`).
        "decided_by": ((row.answer or {}).get("by_name") or "Their delegate")
        if str(row.answered_by or "").startswith("delegate:") else "",
        "decided_words": (row.answer or {}).get("words") or ""
        if str(row.answered_by or "").startswith("delegate:") else "",
        "decider": "", "decider_told": False, "delegate_notes": [],
        "kind": row.kind or "", "action": getattr(row, "action", None) or {},
    }
    out["line"] = line_of(row, source, rec)
    if events is not None:
        out["events"] = events
    return out


def line_of(row, source=None, rec: dict | None = None) -> dict:
    """A decision as one line, the same on the Decisions page and in Rouh's tool (Petar, 18
    October 2026): only what he needs to tell whether this one needs him now.

    - `what`: what it is, in plain words, with its task or step number where there is one;
    - `yes`: what a yes would do, concretely; `wait`: what waiting costs, after its due date
      when it has one (`due`); `blocks`: something is held up until he answers;
    - `tags`: where it came from, its project, and what the source adds;
    - `rec`: Rouh's recommendation in a few words; `number`, to answer it by voice;
    - `href`: the item's own page, where the decision is made: the task, the step, the mail
      case, the gene in Mutations, the run. A source whose own page cannot answer it opens
      the decision's own page, `/decisions/<number>`, which draws it in full."""
    from . import clock

    line = row.line if isinstance(row.line, dict) else {}
    own = bool(source is not None and source.own_page and row.link)
    # What kind of thing it is, drawn as the line's badge with its icon and colour; the tags
    # are the rest (its project, what the source adds).
    kind = (source.tag or source.label) if source else row.source.title()
    tags = []
    for t in [row.project, *(line.get("tags") or [])]:
        t = " ".join(str(t or "").split())
        if t and t.lower() not in [x.lower() for x in tags + [kind]]:
            tags.append(t)
    due = ""
    if row.due_at:
        when = clock.moment(row.due_at)
        if when is not None:
            day = f"{when:%a} {when.day} {when:%b}" + (f", {when:%H:%M}" if (when.hour, when.minute) != (0, 0) else "")
            due = ("Was due " if row.due_at < time.time() else "Due ") + day
    if rec is None:
        rec = next((o for o in row.options or [] if o.get("id") == row.recommended), None)
    return {"what": row.title, "about": line.get("about") or "",
            "yes": line.get("yes") or "", "wait": line.get("wait") or "",
            "due": due, "blocks": bool(line.get("blocks")), "tags": tags,
            "rec": (rec or {}).get("label") or line.get("advice") or "",
            "kind": kind, "source": row.source, "number": row.number,
            "href": row.link if own else page_of(row),
            "own_page": own}


def line_order(d: dict) -> tuple:
    """The order of the lines: what is dated or holds something up first, soonest first; then
    the rest, newest first."""
    line = d.get("line") or {}
    first = bool(d.get("due_at") or line.get("blocks"))
    return (0 if first else 1, (d.get("due_at") or float("inf")) if first else 0,
            -(d.get("created_at") or 0))


def lines(who) -> dict:
    """The Decisions page and the tool's list: every decision waiting on him as a line, in
    `line_order`; those he put off till later; and the recent ones finished, newest first."""
    got = listing(who)
    waiting = sorted(got["open"], key=line_order)
    return {"open": waiting, "snoozed": got["snoozed"], "going": got["going"],
            "history": got["history"][:40], "counts": got["counts"], "now": got["now"],
            "theirs": got["theirs"]}


def _events_of(ids) -> dict[int, list]:
    out: dict[int, list] = {}
    for e in (_models().DecisionEvent.objects.filter(decision_id__in=list(ids))
              .order_by("at", "id")):
        out.setdefault(e.decision_id, []).append(
            {"kind": e.kind, "by": e.by, "channel": e.channel, "detail": e.detail, "at": e.at})
    return out


def _order(row) -> tuple:
    urgency = URGENCY.index(row.urgency) if row.urgency in URGENCY else len(URGENCY)
    return (urgency, row.due_at or float("inf"), -(row.created_at or 0))


def delegated(who, rows=None) -> dict[int, str]:
    """The open decisions a trusted contact decides by the owner's grant, {id: their name}: kept
    off his list, his count and his phone, and on theirs (Petar, 21 October 2026). They stay in
    the record, at their own address, and in what the delegate is emailed (`rouh/delegation.py`)."""
    from . import delegation

    try:
        scopes = delegation.deciders(who.user_id, who.org_id)
        if not scopes:
            return {}
        if rows is None:
            rows = list(_models().Decision.objects.filter(
                **_whose(who), status__in=ANSWERABLE, source__in=delegation.DECISION_SOURCES))
        out = {}
        for r in rows:
            if r.status in ANSWERABLE:
                c = delegation.decider_of(r, scopes)
                if c is not None:
                    out[r.id] = c.name
        return out
    except Exception:
        log.exception("decisions: who decides them could not be read")
        return {}


def counts(who, skip=None) -> dict:
    """How many wait on him now, and how many of those are urgent. What a delegate decides is
    not his to count (`delegated`)."""
    m = _models()
    now = time.time()
    skip = delegated(who) if skip is None else skip
    rows = m.Decision.objects.filter(**_whose(who), status__in=ANSWERABLE).values_list(
        "id", "status", "snoozed_until", "urgency", "kind", "line")
    rows = [r[1:] for r in rows if r[0] not in skip]
    # An action is counted on its own row, Your part (`rouh/actions.py`), never as a decision.
    acts = [r for r in rows if r[3] == "action"]
    rows = [r for r in rows if r[3] != "action"]
    waiting = [r for r in rows if r[0] != SNOOZED or (r[1] or 0) <= now]
    doing = [r for r in acts if r[0] != SNOOZED or (r[1] or 0) <= now]
    return {"open": len(waiting), "now": sum(1 for r in waiting if r[2] == "now"),
            "snoozed": len(rows) - len(waiting),
            "actions": len(doing),
            "actions_blocking": sum(1 for r in doing if (r[4] or {}).get("blocks"))}


def listing(who, *, history: bool = True) -> dict:
    """Everything open, snoozed and on its way, most urgent first, and the recent history;
    and the open ones arranged the way the page and Rouh's tool both say them (`arrange`)."""
    m = _models()
    # Actions are drawn on their own page, Your part (`rouh/actions.py`), and never here.
    rows = list(m.Decision.objects.filter(**_whose(who)).exclude(status__in=DONE)
                .exclude(kind="action"))
    # What was folded into a grouped decision was never answered: its question goes on in
    # the group, so it is not history.
    done = list(m.Decision.objects.filter(**_whose(who), status__in=DONE)
                .exclude(status=WITHDRAWN, result__startswith=FOLDED).exclude(kind="action")
                .order_by("-resolved_at", "-id")[:HISTORY_MOST]) if history else []
    # What a trusted contact decides is theirs, not his (`delegated`).
    theirs = delegated(who, rows)
    # Drawn for the page's "Your delegates decide" fold, each with whose it is: shown, never
    # counted as his (the owner, 7 November 2026, task 62, step 62-27).
    theirs_drawn = []
    for r in rows:
        if r.id in theirs and r.status in ANSWERABLE:
            d = as_dict(r)
            d["decider"] = theirs[r.id]
            theirs_drawn.append(d)
    rows = [r for r in rows if r.id not in theirs]
    events = _events_of([r.id for r in rows + done])
    now = time.time()
    open_, snoozed, going = _draw_listing_rows(rows, events, now)
    history = [as_dict(r, events=events.get(r.id, [])) for r in done]
    with_delegates(who, rows, open_ + snoozed + going)
    # What he already said in a chat that answers one, behind its switch (`rouh/answered_in_chat.py`).
    answered_in_chat.attach(who, open_ + snoozed)
    return {"open": open_, "snoozed": snoozed, "going": going,
            "history": history, "sources": source_names(),
            "arranged": arrange(open_), "counts": counts(who, theirs), "now": now,
            "delegated": len(theirs), "theirs": theirs_drawn}


def _draw_listing_rows(rows, events: dict[int, list], now: float) -> tuple[list, list, list]:
    """Sort and draw the unfinished rows into open, snoozed and on-the-way lists."""
    rows.sort(key=_order)
    stale = stale_reasons(rows, now)
    open_, snoozed, going = [], [], []
    for r in rows:
        d = as_dict(r, events=events.get(r.id, []))
        d["stale"] = stale.get(r.id, "")
        if r.status == SNOOZED and (r.snoozed_until or 0) > now:
            snoozed.append(d)
        elif r.status in ANSWERABLE:
            open_.append(d)
        else:
            going.append(d)
    return open_, snoozed, going


def with_delegates(who, rows, drawn: list[dict]) -> None:
    """Who decides each open one, when Petar gave somebody authority over it, and what a
    delegate recommended on one that stays his (`rouh/delegation.py`)."""
    from . import delegation

    try:
        scopes = delegation.deciders(who.user_id, who.org_id)
        notes = delegation.notes_on_decisions(who.user_id, who.org_id, [d["id"] for d in drawn])
        told = delegation.briefed_decisions(who.user_id, who.org_id, [d["id"] for d in drawn])
    except Exception:
        log.exception("decisions: who decides them could not be read")
        return
    by_id = {r.id: r for r in rows}
    for d in drawn:
        row = by_id.get(d["id"])
        if row is not None and scopes and row.status in ANSWERABLE:
            c = delegation.decider_of(row, scopes)
            d["decider"] = c.name if c is not None else ""
            d["decider_told"] = d["id"] in told
        d["delegate_notes"] = notes.get(d["id"], [])


# --- what matters first, and what is probably stale ---------------------------------------------
#
# Petar, 8 October 2026, by voice: "Decisions is overflowing, needs a fix." 155 waited, most
# of them small Synapse changes, and what mattered (a SOC 2 window that sends a message, the
# night's feature to accept or undo, a meeting's guests) was buried among them. So the open
# ones are arranged, the one way the page draws them and Rouh's tool says them:
#
# - first, always in sight, whatever else is true of them: what spends money, sends,
#   publishes or cannot be undone (`GATED`);
# - then by how soon (now, today, soon), and inside that by where they came from, each with
#   its count;
# - below the fold, folded: whatever can wait ("whenever") and the low-stakes sources;
# - and last, folded, what is probably stale: its own deadline has passed, or the task it
#   belongs to is done or archived. Nothing is closed for him: each has a one-press Dismiss
#   (where its source has the idea) and stays until he presses it.

#: Sources whose questions are small, reversible and many, and wait below the fold.
LOW_STAKES = frozenset({"dream"})

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december)"
#: A deadline said in a question's own words: "by 2 October", "before October 2nd",
#: "no later than 2 Oct 2026", "deadline: 2 October".
_DEADLINE = None


def _deadline_words():
    global _DEADLINE
    if _DEADLINE is None:
        import re

        lead = r"\b(?:by|before|until|till|no later than|deadline(?: is| of)?:?|due(?: on| by)?:?)\s+(?:about\s+|around\s+|the\s+)?"
        _DEADLINE = re.compile(
            lead + r"(?:(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+" + _MONTH + r"|" + _MONTH
            + r"\s+(\d{1,2})(?:st|nd|rd|th)?)(?:,?\s+(\d{4}))?\b", re.IGNORECASE)
    return _DEADLINE


def deadline_in_words(row):
    """The latest deadline its own words give (the question, why, what happens next, the
    options), as a date, or None. A date with no year is the one on or after the day it was
    asked, give or take four months."""
    import datetime as dt

    from . import clock

    texts = [row.question or "", row.why or "", row.then or ""] + [
        f"{o.get('label') or ''} {o.get('detail') or ''}" for o in row.options or []
        if isinstance(o, dict)]
    asked = clock.moment(row.created_at or time.time())
    asked_day = asked.date() if asked else dt.date.today()
    latest = None
    for text in texts:
        for m in _deadline_words().finditer(text):
            day = m.group(1) or m.group(4)
            month = (m.group(2) or m.group(3) or "").lower()
            try:
                n_month = _MONTHS.index(month) + 1
                year = int(m.group(5)) if m.group(5) else asked_day.year
                when = dt.date(year, n_month, int(day))
                if not m.group(5) and when < asked_day - dt.timedelta(days=120):
                    when = dt.date(year + 1, n_month, int(day))
            except (ValueError, TypeError):
                continue
            if latest is None or when > latest:
                latest = when
    return latest


def _said_day(when) -> str:
    return f"{when.day} {when:%B}"


def stale_reasons(rows, now: float | None = None) -> dict[int, str]:
    """Why each of these is probably stale, {id: the reason in words}, for those that are:
    its own deadline has passed, or the task it belongs to (a goal step's goal too) is done
    or archived. Only ever said; nothing here closes anything."""
    from . import clock

    now = now or time.time()
    tasks = {}
    for r in rows:
        if r.source == "task" and r.source_id:
            tasks[r.id] = r.source_id
        elif (r.batch or "").startswith("goal:"):
            tasks[r.id] = r.batch[len("goal:"):]
    known = {}
    if tasks:
        from .models import Task

        known = {t["id"]: t for t in Task.objects.filter(id__in=set(tasks.values())).values(
            "id", "number", "state", "archived_at")}
    from . import decision_sources

    srcs = decision_sources.sources()
    today = clock.now().date()
    out: dict[int, str] = {}
    for r in rows:
        if getattr(srcs.get(r.source), "dated", False):
            # Its date is what it is about - a promise that is late - never a sign it is stale.
            continue
        t = known.get(tasks.get(r.id))
        if r.due_at and r.due_at < now:
            when = clock.moment(r.due_at)
            out[r.id] = (f"Its own time, {_said_day(when)} {when:%H:%M}, has passed." if when
                         else "Its own time has passed.")
        elif t is not None and t.get("archived_at"):
            out[r.id] = f"Task {t['number']} is archived." if t.get("number") else "Its task is archived."
        elif t is not None and t.get("state") == "done":
            out[r.id] = f"Task {t['number']} is done." if t.get("number") else "Its task is done."
        else:
            when = deadline_in_words(r)
            if when is not None and when < today:
                out[r.id] = f"It depends on a date that has passed: {_said_day(when)}."
    return out


def arrange(open_: list[dict]) -> dict:
    """The open decisions in the order they matter, as the page draws them and the tool says
    them: {"top": [ids], "sections": [{"urgency", "label", "folded", "count", "groups":
    [{"source", "label", "ids", "count", "items"}]}], "stale": [ids]}. `top` is everything
    gated, always in sight; a folded section is below the fold; `stale` is last, folded."""
    from . import decision_sources

    order = list(decision_sources.sources())
    top = [d for d in open_ if d.get("gated")]
    stale = [d for d in open_ if not d.get("gated") and d.get("stale")]
    rest = [d for d in open_ if not d.get("gated") and not d.get("stale")]
    sections = _arrangement_sections(rest, order)
    return {"top": [d["id"] for d in top], "sections": sections,
            "stale": [d["id"] for d in stale]}


def _folded_decision(d: dict) -> bool:
    """Whether an otherwise current decision belongs below the fold."""
    return d.get("urgency") == "whenever" or (
        d.get("source") in LOW_STAKES and d.get("risk") == "reversible")


def _arrangement_groups(these, order: list[str]) -> list[dict]:
    """Group a section by source, keeping source order and the decisions inside each."""
    by: dict[str, list] = {}
    for d in these:
        by.setdefault(d["source"], []).append(d)
    out = []
    for kind in sorted(by, key=lambda k: order.index(k) if k in order else len(order)):
        ds = by[kind]
        out.append({"source": kind, "label": plural(kind),
                    "ids": [d["id"] for d in ds], "count": len(ds),
                    "items": sum(len(d.get("items") or []) or 1 for d in ds)})
    return out


def _arrangement_sections(rest: list[dict], order: list[str]) -> list[dict]:
    """Build the urgency sections, followed by the folded low-stakes section."""
    sections = []
    for u in URGENCY[:-1]:
        these = [d for d in rest if d.get("urgency") == u and not _folded_decision(d)]
        if these:
            sections.append({"urgency": u, "label": URGENCY_WORDS[u], "folded": False,
                             "count": len(these), "groups": _arrangement_groups(these, order)})
    low = [d for d in rest if _folded_decision(d)]
    if low:
        sections.append({"urgency": "whenever", "label": "Whenever, and low stakes",
                         "folded": True, "count": len(low), "groups": _arrangement_groups(low, order)})
    return sections


#: What each source's decisions are called, many at once.
#: "approval" is the heartbeat's and a quest's, and "mail" is an email's or a Telegram message's,
#: trusted contacts' included. Until 15 October 2026 they were "Approvals" and "Messages", and
#: Petar pressed Approvals looking for the approvals his trusted contacts' emails wait on
#: (fr_93833fb07db1): each name says where its decisions come from.
SOURCE_PLURAL = {"task": "Tasks", "goal": "Goal steps", "approval": "Heartbeat and quests",
                 "run": "Runs",
                 "job": "Jobs", "conflict": "Conflicts", "dream": "Synapse",
                 "nightly": "Nightly feature", "meeting": "Meeting guests",
                 "contact_picks": "Contacts to pick on LinkedIn",
                 "after_meeting": "After meetings",
                 "mail": "Emails and messages", "casefix": "Check fixes", "delegate": "For you, from a delegate",
                 "offline": "Done offline", "promise": "Promises in Slack"}


def plural(kind: str) -> str:
    """What a source's decisions are called, many at once: SOURCE_PLURAL, else the source's
    own label, else its kind, so a source nobody named yet still has a name."""
    from . import decision_sources

    src = decision_sources.sources().get(kind)
    return SOURCE_PLURAL.get(kind) or (src.label if src else "") or kind


def source_names() -> list[list[str]]:
    """Every source's [kind, plural name], in the order `arrange` groups them, for the
    Decisions page's "Show only" filter. The page has no list of its own, so a new source
    is in the filter the day it starts asking (Petar, 9 October 2026: "after meetings is
    missing as a filter in decisions")."""
    from . import decision_sources

    return [[kind, plural(kind)] for kind in decision_sources.sources()]


def get(who, ident) -> dict | None:
    row = _row(who, ident)
    if row is None:
        return None
    d = as_dict(row, events=_events_of([row.id]).get(row.id, []))
    with_delegates(who, [row], [d])
    answered_in_chat.attach(who, [d])
    return d


def for_source(who, source: str, source_id: str) -> dict | None:
    """The newest decision a source asked under this id, for its own page to draw: the open
    one if there is one, else the last one answered."""
    m = _models()
    rows = list(m.Decision.objects.filter(**_whose(who), source=source,
                                          source_id=str(source_id)).order_by("-created_at", "-id")[:8])
    if not rows:
        return None
    live = [r for r in rows if r.status not in DONE]
    row = live[0] if live else rows[0]
    return as_dict(row, events=_events_of([row.id]).get(row.id, []))


def newest_waiting(who, source: str) -> dict | None:
    """The newest question of this source still waiting on the person, for a place that
    draws it in passing (the morning brief's Report, for the night's feature)."""
    row = (_models().Decision.objects.filter(**_whose(who), source=source,
                                            status__in=ANSWERABLE)
           .order_by("-created_at", "-id").first())
    return as_dict(row) if row is not None else None


def of_sources(who, source: str, ids) -> dict[str, dict]:
    """The newest decision of each of these source ids, for a source's own page to draw its
    questions with (the Heartbeat page's approvals, a quest's): {source id: decision}."""
    ids = [str(i) for i in ids or []]
    if not ids:
        return {}
    out: dict[str, dict] = {}
    rows = (_models().Decision.objects.filter(**_whose(who), source=source, source_id__in=ids)
            .order_by("source_id", "-created_at", "-id"))
    for row in rows:
        if row.source_id not in out:
            out[row.source_id] = as_dict(row)
    return out


def of_page(who, ident, folder: str) -> bool:
    """Whether this decision is the one a task's or a goal step's own page at `folder` asks:
    a page in a frame may act on its own question and no other (`taskDecision` in
    app/cards.js)."""
    from .models import Task

    row = _row(who, ident)
    folder = str(folder or "").strip().strip("/")
    if row is None or not folder:
        return False
    if row.source == "goal":
        return row.source_id.strip("/") == folder
    if row.source == "task":
        task = Task.objects.filter(id=row.source_id).first()
        return task is not None and str(task.folder or "").strip("/") == folder
    return False


def ref_of(ident) -> dict | None:
    """What a reference to a decision names, as a filter, or None for nothing.

    An int is a row's own id, {"id": 12}: what the pages' presses, Telegram's buttons and the
    code carry. Words are the person's own reference, its number however it was said or typed
    ("42", "#42", "decision 42", "forty-two"): {"number": 42}. Anything else, an old handle
    (a482) or a job's old id (r24) among it, names none."""
    from . import decision_numbers

    if isinstance(ident, bool):
        return None
    if isinstance(ident, int):
        return {"id": ident}
    number = decision_numbers.read(str(ident or "").strip())
    return {"number": number} if number else None


def _row(who, ident, *, lock: bool = False):
    ref = ref_of(ident)
    if ref is None:
        return None
    rows = _models().Decision.objects
    if lock:
        rows = rows.select_for_update()
    return rows.filter(**_whose(who), **ref).first()


def name_of(d) -> str:
    """How a decision is named to the person: "Decision 42" (`decision_numbers.called`)."""
    from . import decision_numbers

    number = d.get("number") if isinstance(d, dict) else getattr(d, "number", None)
    kind = d.get("kind") if isinstance(d, dict) else getattr(d, "kind", "")
    return decision_numbers.called(number, kind or "")


def page_of(d) -> str:
    """A decision's own page: /decisions/<its number>."""
    number = d.get("number") if isinstance(d, dict) else getattr(d, "number", None)
    if (d.get("kind") if isinstance(d, dict) else getattr(d, "kind", "")) == "action":
        # An action's own page, on Your part (`rouh/actions.py`).
        return f"/actions/{number}" if number else "/actions"
    return f"/decisions/{number}" if number else "/decisions"


# --- answering ----------------------------------------------------------------------------------


def said_of(row, choice: list[str], text: str, items: dict | None = None) -> str:
    """The answer as one sentence: the options picked, then his own words. Items answered
    one by one are counted by answer: "Approve 3 and Reject 2, of 32"."""
    if items and not choice:
        many = len(row.items or [])
        parts = [f"{o.get('each') or o['label']} {sum(1 for v in items.values() if v == o['id'])}"
                 for o in row.options or [] if any(v == o["id"] for v in items.values())]
        picked = " and ".join(parts) + (f", of {many}" if many else "")
        return f"{picked}. {text}" if text else picked
    labels = [o["label"] for o in row.options or [] if o.get("id") in choice]
    picked = (labels[0] if len(labels) == 1 else
              ", ".join(labels[:-1]) + " and " + labels[-1] if labels else "")
    if picked and text:
        return f"{picked}. {text}"
    return picked or text


def _items_checked(row, items) -> dict:
    """Items answered one by one, {item id: option id}, checked against the decision's own
    items and options. Items given no answer are left waiting."""
    if not items:
        return {}
    if not isinstance(items, dict):
        raise Refused("Answer the items as item and answer pairs.")
    have = {i.get("id") for i in row.items or []}
    ids = {o["id"] for o in row.options or []}
    out = {}
    for item, verdict in items.items():
        item, verdict = str(item or "").strip(), str(verdict or "").strip()
        if not verdict:
            continue
        if item not in have:
            raise Refused("That item is not one this question holds any more. Read it again.")
        if verdict not in ids or verdict in _links(row):
            raise Refused("That is not one of its answers.")
        allowed = next((i.get("options") for i in row.items or [] if i.get("id") == item), None)
        if allowed is not None and verdict not in allowed:
            raise Refused("That answer is not open for that item.")
        out[item] = verdict
    return out


def _links(row) -> set[str]:
    """The options of a question that are links, which open a page and answer nothing."""
    return {o["id"] for o in row.options or [] if o.get("href")}


def _check(row, choice, text: str, confirm: str, items=None) -> tuple[list[str], str, dict]:
    """The answer, checked against what the question allows and against its risk."""
    from . import decision_sources

    if row.status not in ANSWERABLE:
        raise Refused(_already(row))
    each = _items_checked(row, items)
    ids = [o["id"] for o in row.options or []]
    if isinstance(choice, str):
        choice = [choice]
    picked = []
    for c in choice or []:
        c = str(c or "").strip()
        if c and c not in picked:
            if c not in ids:
                raise Refused("That is not one of its answers.")
            if c in _links(row):
                raise Refused("That one opens a page; it answers nothing.")
            picked.append(c)
    text = str(text or "").strip()[:TEXT_MOST]
    if len(picked) > 1 and row.answer_type != "multi":
        raise Refused("Pick one.")
    if text and not (row.allow_other or row.answer_type in ("text", "date")):
        raise Refused("This one is answered with one of its answers, not in words.")
    if each and picked:
        raise Refused("Answer it all at once, or item by item, not both.")
    if not picked and not text and not each:
        raise Refused("Pick an answer, or say it in your own words.")
    if row.items and picked and not each:
        # One answer for all of them: each item it holds now, as he saw them.
        each = {i["id"]: picked[0] for i in row.items if i.get("id")}
    if row.risk in GATED:
        source = decision_sources.sources().get(row.source)
        chosen = set(picked) | set(each.values())
        goes = any(o.get("go") for o in row.options or [] if o["id"] in chosen) or (
            bool(text) and bool(source and source.text_acts))
        if goes and str(confirm or "").strip().lower() != row.risk:
            raise NeedsConfirm(row.risk, row.risk_note)
    return picked, text, each


def _already(row) -> str:
    said = (row.answer or {}).get("said") or ""
    where = f" on {row.channel}" if row.channel else ""
    if row.status in (ANSWERED, APPLYING, APPLIED):
        return f"Already answered{where}: {said}." if said else f"Already answered{where}."
    if row.status == DISMISSED:
        return "That question was dismissed."
    if row.status == EXPIRED:
        return "That question ran out of time before it was answered."
    if row.status == WITHDRAWN:
        return "That question is not asked any more."
    if row.status == CLEARED:
        return "Rouh cleared that question: it did not need you. Open it again to answer it."
    return "That question cannot be answered now."


def answer(who, ident, *, choice=None, text: str = "", confirm: str = "", channel: str = "screen",
           by: str = "", delegated: bool = False, items: dict | None = None,
           by_name: str = "", their_words: str = "") -> dict:
    """The person's answer: checked, written down, and given its window to be undone before
    it goes back to the source (`apply_due`). The same answer twice is a no-op.

    A decision that holds items (`Decision.items`) is answered all at once, with one of its
    options for every item it holds, or item by item, `items` {item id: option id}; the
    items left without an answer wait on, and the decision is open again for them once the
    rest have gone back to the source (`Applied.reopen`)."""
    from django.db import transaction

    channel = channel if channel in CHANNELS else "screen"
    with transaction.atomic():
        if ref_of(ident) is None:
            raise Refused("Which question? Give its number, such as Decision 42.")
        row = _row(who, ident, lock=True)
        if row is None:
            raise Refused("There is no such question.")
        if row.status in (ANSWERED, APPLYING, APPLIED):
            got = row.answer or {}
            again = [str(c) for c in (choice if isinstance(choice, list) else [choice] if choice
                                      else [])]
            same_items = ((got.get("items") or {}) == {str(k): str(v) for k, v in items.items() if v}
                          if isinstance(items, dict) and items else bool(again) or not got.get("items"))
            if (got.get("choice") == again and same_items
                    and (got.get("text") or "") == str(text or "").strip()):
                return {"ok": True, "again": True, "said": _already(row),
                        "decision": as_dict(row)}
            raise Refused(_already(row))
        picked, words, each = _check(row, choice, text, confirm, items)
        now = time.time()
        said = said_of(row, picked, words, each if not picked else None)
        if picked and row.items and len(picked) == 1 and not words:
            said = next((o["label"] for o in row.options or [] if o["id"] == picked[0]), said)
        row.answer = {"choice": picked, "text": words, "said": said}
        if each:
            row.answer["items"] = each
        # A trusted contact deciding for Petar (`rouh/delegation.py`): who, and their own
        # words exactly as they wrote them, kept on the answer.
        delegate = str(by or "").startswith("delegate:")
        if delegate:
            row.answer["by_name"] = str(by_name or "")[:200]
            row.answer["words"] = str(their_words or "")[:TEXT_MOST]
        row.status = ANSWERED
        row.answered_by = "rouh" if delegated else str(by or who.user_id)
        row.channel = channel
        row.answered_at = now
        row.apply_at = now + UNDO_SECONDS
        row.snoozed_until = None
        row.result = ""
        row.updated_at = now
        row.save()
        _event(row, "answered", by="rouh" if delegated else "delegate" if delegate else "person",
               channel=channel,
               detail=("Rouh decided, as you asked: " if delegated else
                       f"{by_name} decided: " if delegate else "") + said
               + (f" Their words: \u201c{their_words}\u201d" if delegate and their_words else ""))
    from . import events

    # Who answered which, and how long it had waited; never the answer's words.
    events.emit("decision.answered", who=who,
                actor="rouh" if delegated else "delegate" if delegate else "person",
                source={"telegram": "telegram", "voice": "voice", "email": "mail"}.get(channel, "web"),
                object_type="decision", object_id=row.id,
                duration_ms=(now - row.created_at) * 1000 if getattr(row, "created_at", None) else None,
                props={"channel": channel, "picked_n": len(picked or []), "from": str(row.source or "")[:40]})
    answered_in_chat.answered(who, row.id, picked)
    return {"ok": True, "said": f"Answered: {said}. It goes in {int(UNDO_SECONDS)} seconds; "
                                "Undo until then.", "decision": as_dict(row)}


def delegate(who, ident, *, channel: str = "screen") -> dict:
    """"Rouh, decide this one": the recommended answer, given because he asked for it, and only
    on a question that can be changed later."""
    row = _row(who, ident)
    if row is None:
        raise Refused("There is no such question.")
    if row.risk != "reversible" or row.risk in GATED:
        raise Refused("Rouh does not decide this one for you: " + RISK_WORDS.get(row.risk, row.risk)
                      .lower() + ". It needs your own answer.")
    if not row.recommended:
        raise Refused("Rouh has no recommendation for this one, so it is yours to answer.")
    return answer(who, ident, choice=[row.recommended], channel=channel, delegated=True)


def undo(who, ident) -> dict:
    """Take an answer back while it has not gone to its source yet."""
    m = _models()
    row = _row(who, ident)
    if row is None:
        raise Refused("There is no such question.")
    now = time.time()
    done = m.Decision.objects.filter(id=row.id, status=ANSWERED, apply_at__gt=now).update(
        status=OPEN, answer={}, answered_by="", channel="", answered_at=None, apply_at=None,
        updated_at=now)
    if not done:
        raise Refused("Too late to undo: the answer has gone." if row.status != OPEN
                      else "There is no answer to undo.")
    _event(row, "undone", by="person")
    return {"ok": True, "said": "Undone. It is waiting on you again.", "decision": get(who, row.id)}


def reopen(who, ident, *, channel: str = "screen") -> dict:
    """Undo what its source closed by itself (`Settled.by` "itself"): the source opens it again,
    and it waits on the person once more, under a new question at the next sync."""
    from . import decision_sources

    m = _models()
    row = _row(who, ident)
    if row is None:
        raise Refused("There is no such question.")
    source = decision_sources.sources().get(row.source)
    if source is not None and row.status == CLEARED:
        return _reopen_cleared(who, row, source, channel)
    if source is None or row.status != APPLIED or not source.can_reopen(row):
        raise Refused("That cannot be undone now.")
    said = source.reopen(who, row) or "Open again."
    now = time.time()
    got = dict(row.answer or {})
    got["said"] = _cut(f"{got.get('said') or 'Closed'}, then undone", TEXT_MOST)
    m.Decision.objects.filter(id=row.id, status=APPLIED).update(
        answer=got, result=_cut(f"{row.result} You pressed Undo: {said}".strip(), 2000), updated_at=now)
    _event(row, "undone", by="person", channel=channel, detail=said)
    return {"ok": True, "said": said, "decision": get(who, row.id)}


def _reopen_cleared(who, row, source, channel: str) -> dict:
    """Open again what Rouh cleared: waiting on him once more, his for good (the gate is told,
    `decision_gate.mine`), and asked at its source again where clearing took it out of there
    (`Source.on_reopened`: a task's question back in its meta, and the task waiting)."""
    said = source.on_reopened(who, row) or "Open again, and waiting on you."
    decision_gate.mine(who, row.source, row.key, row.source_id)
    now = time.time()
    _models().Decision.objects.filter(id=row.id, status=CLEARED).update(
        status=OPEN, resolved_at=None, answered_by="", channel="", result="", updated_at=now)
    _event(row, "reopened", by="person", channel=channel, detail=said)
    return {"ok": True, "said": said, "decision": get(who, row.id)}


def snooze(who, ident, until: float, *, channel: str = "screen") -> dict:
    """"I'll decide later": out of the way until `until`, then waiting again."""
    m = _models()
    row = _row(who, ident)
    if row is None:
        raise Refused("There is no such question.")
    now = time.time()
    try:
        until = float(until)
    except (TypeError, ValueError):
        raise Refused("Until when?") from None
    if until <= now + 30:
        raise Refused("Pick a time later than now.")
    until = min(until, now + 60 * 86400)
    done = m.Decision.objects.filter(id=row.id, status__in=WAITING).update(
        status=SNOOZED, snoozed_until=until, updated_at=now)
    if not done:
        raise Refused(_already(row))
    _event(row, "snoozed", by="person", channel=channel, detail=f"until {until:.0f}")
    return {"ok": True, "said": "Later, then.", "decision": get(who, row.id)}


def wake(who, ident) -> dict:
    m = _models()
    row = _row(who, ident)
    if row is None:
        raise Refused("There is no such question.")
    now = time.time()
    if m.Decision.objects.filter(id=row.id, status=SNOOZED).update(
            status=OPEN, snoozed_until=None, updated_at=now):
        _event(row, "woke", by="person")
    return {"ok": True, "decision": get(who, row.id)}


def dismiss(who, ident, *, channel: str = "screen") -> dict:
    """Close it without an answer, where its source allows that: nothing it asks about is
    done, and the source is told it was closed (`Source.dismiss`)."""
    from . import decision_sources

    m = _models()
    row = _row(who, ident)
    if row is None:
        raise Refused("There is no such question.")
    source = decision_sources.sources().get(row.source)
    if source is None or not source.can_dismiss:
        raise Refused("This one cannot be dismissed: answer it, or leave it for later.")
    if row.status not in ANSWERABLE:
        raise Refused(_already(row))
    said = source.dismiss(who, row) or "Dismissed: nothing was done."
    now = time.time()
    m.Decision.objects.filter(id=row.id, status__in=ANSWERABLE).update(
        status=DISMISSED, resolved_at=now, updated_at=now, channel=channel, result=said[:2000])
    _event(row, "dismissed", by="person", channel=channel, detail=said)
    return {"ok": True, "said": said, "decision": get(who, row.id)}


# --- going back to the source ------------------------------------------------------------------


def due(now: float | None = None) -> list:
    """Answers whose window to undo has passed, for every person: the desk's work."""
    now = now or time.time()
    return list(_models().Decision.objects.filter(status=ANSWERED, apply_at__lte=now)
                .order_by("apply_at", "id")[:50])


def take(row_id: int) -> bool:
    """Claim an answer for going back to its source: True for exactly one caller."""
    now = time.time()
    return bool(_models().Decision.objects.filter(id=row_id, status=ANSWERED).update(
        status=APPLYING, updated_at=now))


def finished(row_id: int, got: Applied) -> None:
    """What the source said, written down: applied, or failed and answerable again."""
    m = _models()
    row = m.Decision.objects.filter(id=row_id).first()
    if row is None:
        return
    now = time.time()
    if got.reopen:
        # Part of it went back; the rest of its items still wait, so it is open again for
        # them, with what was done said on it.
        m.Decision.objects.filter(id=row_id, status=APPLYING).update(
            status=OPEN, result=_cut(got.result, 2000), answer={}, answered_by="", channel="",
            answered_at=None, apply_at=None, resolved_at=None, updated_at=now)
        _event(row, "applied" if got.ok else "failed", channel=row.channel,
               detail=f"{(row.answer or {}).get('said') or ''}: {got.result}".strip(": "))
        return
    status = APPLIED if got.ok else FAILED
    m.Decision.objects.filter(id=row_id, status=APPLYING).update(
        status=status, result=_cut(got.result, 2000), resolved_at=now if got.ok else None,
        updated_at=now)
    _event(row, "applied" if got.ok else "failed", channel=row.channel, detail=got.result)


# --- what Rouh is told -------------------------------------------------------------------------


def line_for_model(d: dict) -> str:
    """One decision as Rouh reads it in its `decisions` tool."""
    out = _model_question(d)
    out = _model_delegation(d, out)
    out = _model_prepared(d, out)
    out = _model_answer_state(d, out)
    # What he already said in a chat that answers it (`rouh/answered_in_chat.py`).
    out += answered_in_chat.line_for_model(d)
    return out


def _model_question(d: dict) -> str:
    """Render the question, its options and Rouh's recommendation."""
    opts = "; ".join(f'{o["id"]} "{o["label"]}"' + (f" ({o['detail']})" if o.get("detail") else "")
                     for o in d["options"])
    out = (f'{name_of(d)} [{d["source_label"]}'
           f'{", " + d["context"] if d["context"] else ""}] {d["question"]}')
    if opts:
        out += f" Options: {opts}."
    if d["recommended"]:
        rec = next((o["label"] for o in d["options"] if o["id"] == d["recommended"]), "")
        out += f' Rouh recommends "{rec}"' + (f": {d['recommended_why']}" if d["recommended_why"]
                                              else "") + "."
    return out


def _model_delegation(d: dict, out: str) -> str:
    """Append who decides and what their delegates recommended."""
    if d.get("decider"):
        out += (f" {d['decider']} decides this, by the person's grant, and "
                + ("was emailed it" if d.get("decider_told") else "is emailed it")
                + "; do not ask the person for it.")
    for n in d.get("delegate_notes") or []:
        out += f" {n['name']} recommends: {n['said']} (their words: \u201c{n['words'][:300]}\u201d)."
    return out


def _model_prepared(d: dict, out: str) -> str:
    """Append grouped items, what was sent and what a yes does, in order."""
    if d.get("items"):
        out += (f" It holds {len(d['items'])} of these, answered all at once with an option, or "
                "one by one on the Decisions page.")
    sent = [p for p in parts_of(d) if p["part"] == "sent"]
    if sent:
        # What the sender already had, before he says anything (a message's waiting note).
        out += f" {sent[0]['label']}: " + " ".join(
            f'{n}. "{" ".join(str(p["text"]).split())}" ({p["when"]}).'
            for n, p in enumerate(sent, 1))
    parts = [p for p in parts_of(d) if p["part"] != "sent"]
    if parts:
        # What a yes does, in the order it happens (a message's A, B and C).
        out += " What a yes does: " + " ".join(
            f"{p['label']}: " + (f'"{p["text"]}"' if p.get("text") else "none written")
            + (f" ({p['when'].rstrip('.')})" if p.get("when") else "")
            + (f" with {', '.join(p['files'])}" if p.get("files") else "") + "."
            for p in parts)
    return out


def _model_answer_state(d: dict, out: str) -> str:
    """Append the answer rules, urgency, risk and current state."""
    if d["allow_other"]:
        out += " Own words allowed."
    out += f" Urgency: {d['urgency']}. Risk: {d['risk']}"
    if d["gated"]:
        out += f" ({(d['risk_note'] or d['risk_words']).rstrip('.')}; needs ‹his› yes to that risk itself)"
    out += "."
    if d["status"] not in WAITING:
        out += f" Status: {d['status']}"
        if (d.get("answer") or {}).get("said"):
            out += f", answered: {d['answer']['said']}"
        out += "."
    elif d["status"] == SNOOZED:
        out += " Snoozed."
    if d.get("stale"):
        out += f" Probably stale: {d['stale']}"
    return out


def parts_of(d: dict) -> list[dict]:
    """The parts of what a yes does that a decision's prepared list holds, in order: what
    the sender already had ("sent": a mail case's messages from its outbox,
    `decision_sources.MailSource`), then any part a source names, each `{"part", "label",
    "text", "when", "hint"?}`. Each drawn in a fold of its own under the answers on its card."""
    return [p for p in d.get("prepared") or [] if isinstance(p, dict) and p.get("part")]



def line_words(d: dict) -> str:
    """One decision's line as the tool says it: the same fields as its line on the page."""
    line = d.get("line") or line_of_dict(d)
    out = (f"{name_of(d)}"
           + (f" ({line['kind']})" if line.get("kind") else "") + f": {line['what'].rstrip('.')}.")
    out += f" {line['about'].rstrip('.')}." if line.get("about") else ""
    out += f" A yes: {line['yes'].rstrip('.')}." if line.get("yes") else ""
    wait = "; ".join(x.rstrip(".") for x in (line.get("due"), line.get("wait")) if x)
    out += f" Waiting: {wait}." if wait else ""
    out += f" Tags: {', '.join(line['tags'])}." if line.get("tags") else ""
    out += f" Rouh recommends: {line['rec'].rstrip('.')}." if line.get("rec") else ""
    if d.get("decider"):
        out += f" {d['decider']} decides this by the person's grant; do not ask the person for it."
    if d.get("status") == SNOOZED:
        out += " Put off till later."
    return out


def line_of_dict(d: dict) -> dict:
    """A line for a decision drawn before lines existed (an offline copy): its title alone."""
    return {"what": d.get("title") or "", "yes": "", "wait": "", "due": "", "tags": [],
            "rec": "", "number": d.get("number")}


def listing_for_model(got: dict) -> str:
    """The open decisions as Rouh's tool says them: one line each, the same lines in the same
    order as the Decisions page (`lines`), so what is read out matches what he sees. Read one
    with its number for the whole of it."""
    waiting = got.get("open") or []
    if not waiting:
        return "Nothing is waiting on them."
    out = [f"{len(waiting)} waiting on them, one line each, in the Decisions page's order "
           "(dated or holding something up first, then newest first):"]
    out += ["- " + line_words(d) for d in sorted(waiting, key=line_order)]
    return "\n".join(out)


# --- Telegram ----------------------------------------------------------------------------------

#: Button data: "dq:<id>:<option>" answers, "dc:<id>:<option>" confirms a gated one,
#: "dz:<id>" is later, "dx:<id>" cancels a confirmation. Telegram allows 64 bytes.
TG_ANSWER, TG_CONFIRM, TG_LATER, TG_CANCEL = "dq:", "dc:", "dz:", "dx:"


def telegram_text(d: dict, public_url: str = "") -> str:
    lines = [f"{name_of(d)} · {d['source_label']}{' · ' + d['context'] if d['context'] else ''}",
             "", d["question"]]
    if d["why"]:
        lines += ["", d["why"][:500]]
    for o in d["options"]:
        lines.append(f"• {o['label']}" + (f": {o['detail']}" if o.get("detail") else ""))
    if d["recommended"]:
        rec = next((o["label"] for o in d["options"] if o["id"] == d["recommended"]), "")
        lines += ["", f"Rouh recommends: {rec}" + (f", {d['recommended_why']}"
                                                   if d["recommended_why"] else "")]
    if d["gated"]:
        lines += ["", f"⚠ {d['risk_words']}: {d['risk_note']}" if d["risk_note"]
                  else f"⚠ {d['risk_words']}"]
    lines += ["", f"Answer with the buttons, or tell Rouh: {name_of(d)}, and your answer."]
    if public_url:
        lines += ["", public_url.rstrip("/") + page_of(d)]
    return "\n".join(lines).strip()


def telegram_buttons(d: dict) -> list[list[dict]]:
    """One button per option, when there are few enough to press, and Later."""
    answers = [o for o in d["options"] if not o.get("href")]
    opts = [o for o in answers if len(o["label"]) <= 40][:4]
    if len(opts) != len(answers) or not opts:
        return [[{"text": "Later", "callback_data": f"{TG_LATER}{d['id']}"}]]
    rows = [[{"text": ("★ " if o["id"] == d["recommended"] else "") + o["label"],
              "callback_data": f"{TG_ANSWER}{d['id']}:{o['id']}"[:64]}] for o in opts]
    rows.append([{"text": "Later", "callback_data": f"{TG_LATER}{d['id']}"}])
    return rows


def confirm_buttons(d: dict, option: str) -> list[list[dict]]:
    label = next((o["label"] for o in d["options"] if o["id"] == option), option)
    return [[{"text": f"Yes: {label}"[:60], "callback_data": f"{TG_CONFIRM}{d['id']}:{option}"[:64]}],
            [{"text": "Cancel", "callback_data": f"{TG_CANCEL}{d['id']}"}]]


def read_press(data: str) -> tuple[str, int, str] | None:
    """A press on a decision's button: (what, id, option), or None for any other button."""
    for prefix, what in ((TG_ANSWER, "answer"), (TG_CONFIRM, "confirm"), (TG_LATER, "later"),
                         (TG_CANCEL, "cancel")):
        if data.startswith(prefix):
            rest = data[len(prefix):]
            ident, _, option = rest.partition(":")
            try:
                return what, int(ident), option
            except ValueError:
                return None
    return None


def set_telegram(row_id: int, message_id: int) -> None:
    _models().Decision.objects.filter(id=row_id).update(telegram_message=int(message_id))


def told(row_id: int, how: str) -> None:
    row = _models().Decision.objects.filter(id=row_id).first()
    if row is not None:
        _event(row, "told", channel="telegram", detail=how)
