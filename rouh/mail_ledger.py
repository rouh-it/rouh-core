"""The ledger of a case: every ask of a message, and where each stands. The one source of truth.

Petar, 11 October 2026, after two weeks in which every fix patched one gate and the next case
failed at another: words decided risk, a catch-all held whole emails, six model checks judged
free text and contradicted each other, status lived in the case's stage, its decisions, its
reply and its trace at once, and replies could say a false status. "Consider the entire
situation ... and make a meaningful set of decisions to fix those problems in a long term
well architected way." These are those decisions, in code.

**One ledger of asks per case (D1).** Reading a message gives a list of asks
(`models.MailAsk`), each with an id, the sender's quoted words, the grant it needs ("none" for
an answer alone), any hard limit it touches, its status and its evidence. The status is one of

    allowed            the contact holds what it needs: the gate starts it now
    waiting_for_owner  it needs a grant they do not hold, one there is not yet, or a hard limit
                       (`waiting_for_petar` before 20 October 2026, still read as this)
    approved           the owner said yes to it: once, or by giving the grant
    declined           the owner said no; the only refusal there is (D11)
    started            the gate started it as ordinary work, and the work owns it now (D18):
                       a job, a Clockwork item, a task; its handle is on the ask (`work`)
    done               done at once when it was started (an answer, a note kept), with what
                       shows it
    failed             it could not be started, with why; his Redo tries again

The route, the case page, Decisions, Test grants, the acknowledgement, the reply and the case's
stage all read these rows (`rest_stage`, `why_line`, `status_section`), and nothing else holds
status.

**Permission is code, from grants (D2).** The model's one job is to map each ask to a grant
key, or to propose a new grant when none fits, or to name a hard limit. `judge` then decides,
the same way every time, from what the contact holds (`grants.Tree.held`): held is allowed, not
held is waiting for the owner for that ask alone. No word list, no topic, no model's opinion and no
catch-all decides anything here.

**Hard limits by what is done (D3).** A hard limit an ask names waits for the owner. What a turn may
actually do is held where it acts: each tool that has an effect declares it
(`mail_turn.EFFECTS`), and a case's turn may use one only for an ask the owner approved with that
limit. A reply, a link or a file to the very contact who asked, on their own channel, is never
a hard limit.

**The gate starts, the work finishes (D18).** Petar, 11 October 2026: approval "is responsible
for letting tasks start, not monitoring their responses and status and completion". An ask the
gate lets through is started as ordinary work and marked started with its handle; from then on
its status is the work's own, read from the work wherever it is shown, never kept here. A
failure of the work never comes back to the ledger. Only a need the gate did not decide - a
grant they do not hold, a hard limit, a task they may not change - comes back, and it comes
back onto the very ask it stopped, as what that ask waits for (`blocked`). It is never an ask
of its own: asks come only from the sender's own words (Petar, 16 October 2026, D29).

**The status is the code's (D4).** What a message says about where their requests stand is
written here, from the rows (`status_section`), never by a model, so it cannot be false.

`judge`, `status_section`, `rest_stage` and `why_line` are pure: they take plain values and
read no database, so Test grants, Redo and the replay of real cases (`rouh/mail_replay.py`) run
the very same code.
"""
from __future__ import annotations

import difflib
import re
import time
from dataclasses import asdict, dataclass, field

ALLOWED, WAITING, APPROVED, DECLINED, DONE, FAILED = (
    "allowed", "waiting_for_owner", "approved", "declined", "done", "failed")
#: What WAITING was called before 20 October 2026, when it named the owner of the first
#: installation. Rows, decisions and outbox entries written before then may still say it: it is
#: read as WAITING (`status_of`), and the hashes kept beside them are taken with it, so a
#: signature made before the rename is the same one now (`signature`).
WAITING_BEFORE = "waiting_for_petar"
#: The hard limit of acting as the owner, by the word it had before 20 October 2026, which rows
#: and a model may still say (`grants.HARD_LIMITS` has "as_owner").
AS_OWNER, AS_OWNER_BEFORE = "as_owner", "as_petar"
#: Started as ordinary work, which owns it from then on (D18).
STARTED = "started"
STATUSES = (ALLOWED, WAITING, APPROVED, DECLINED, STARTED, DONE, FAILED)
#: What the gate has finished with: it let it go, and it went, or it was done at once.
GONE_ON = (STARTED, DONE)

#: An answer alone: covered by Communication, which every contact who is not switched off has.
NONE = "none"
#: What an ask is when no capability Rouh has does it (CAPABILITIES.md): it waits, and the owner
#: sees to it or declines it. Nothing is granted for it, because nothing could do it.
UNSUPPORTED = "unsupported"
#: The capability that lifts each hard limit a grant may lift (`grants.LIFTS`).
LIFTED_BY = {"time": "calendar.write"}

#: What the owner can choose for an ask: give the grant it needs for good, allow it this once,
#: decline it, or see to it himself.
GRANT, ONCE, DECLINE, MINE = "grant", "once", "decline", "mine"
CHOICES = {
    GRANT: ("Give permanently", "They get the grant it needs, for this and every later ask it "
                                "covers. A new grant is set up as Rouh proposed it."),
    ONCE: ("Allow once", "Rouh does it this once; nothing is granted."),
    DECLINE: ("Decline", "Rouh does not do it, and the message says you decided not to."),
    MINE: ("I'll see to it", "Rouh does not do it: you see to it yourself."),
}

#: Where a case rests when nothing runs, derived from its ledger (`rest_stage`). The case's
#: stage while Rouh works on it is the step it is at (`mail_cases`).
AWAITING, DONE_STAGE, BLOCKED, MERGED = "awaiting_approval", "done", "blocked", "merged"

#: How each status is named on the owner's pages.
WORDS = {ALLOWED: "Allowed", WAITING: "Waits for you", APPROVED: "Approved by you",
         DECLINED: "Declined by you", STARTED: "Started", DONE: "Done", FAILED: "Failed"}
#: The pill each status is drawn with.
TONES = {ALLOWED: "busy", WAITING: "warn", APPROVED: "busy", DECLINED: "bad", STARTED: "good",
         DONE: "good", FAILED: "bad"}


@dataclass
class Ask:
    """One ask, as the ledger holds it (`models.MailAsk`)."""

    ident: str
    quote: str
    n: int = 0
    #: The concrete action the reading made of it (`case_actions.ACTIONS`), kept with the case's
    #: settled reading and never on the row: what it needs is in the fields below (D34).
    action: str = ""
    label: str = ""
    do: str = ""
    grant: str = ""
    new_grant: dict = field(default_factory=dict)
    #: Other grants it needs as well (Petar, 12 October 2026): Clockwork does at a time what
    #: these allow, so "remind both of us" is clockwork with also communicate.
    also: list = field(default_factory=list)
    hard_limit: str = ""
    #: The number of the task of the owner's it adds to or changes ("90"), or "": what it needs then
    #: is to be allowed to edit that task, which is the task's permission and never a grant
    #: (Petar, 16 October 2026, fr_5825d8e52d0a, D28; `rouh/task_access.py`).
    task: str = ""
    #: What it needs on that task (Petar, 21 October 2026): "read" for research, a timeline, a
    #: plan or an answer about it - research only ever needs reading - and "" for adding to or
    #: changing it, which needs edit. Deciding for it includes both (`rouh/task_access.py`).
    #: "access" when what they ask is that permission itself - to be let in to the task, to
    #: change it, to talk to Rouh in it - which the gate does by itself when they hold it
    #: (`ACCESS`, Petar, 21 October 2026).
    task_needs: str = ""
    #: The capability the reading named for it (`rouh/capabilities.py`, CAPABILITIES.md), the
    #: resources it names - task numbers, calendar ids - and the values it asks within the
    #: capability's limits ({"to": "them"}). "unsupported" when no capability does it.
    capability: str = ""
    scope: list = field(default_factory=list)
    values: dict = field(default_factory=dict)
    status: str = WAITING
    why: str = ""
    choice: str = ""
    choice_grant: str = ""
    evidence: list = field(default_factory=list)
    #: The work it was started as (D18): [{"kind": job|clockwork|task|memory|page|answer,
    #: "ref", "title", "at"}]. Where it stands is read from the work itself, never kept here.
    work: list = field(default_factory=list)
    source: str = "reading"
    #: Raised by the work before 16 October 2026: the id of the ask it serves, in the sender's
    #: own words, or "". Nothing is raised as an ask now (D29): `fold` puts each onto its ask.
    serves: str = ""
    #: What stopped its work, in the work's own words, when the work met a need the gate had
    #: not decided: what it waits for is then on this ask (its task, hard limit or grant), and
    #: the start is told that only that part is left (D29). "" when nothing stopped it.
    blocker: str = ""
    gone: bool = False
    attempt: int = 1
    #: A failed ask that a run would do now, and why: worked out by `rejudge` from the grants
    #: as they are, never kept on the row (Petar, 12 October 2026, D15).
    possible: str = ""
    #: What a waiting ask lacks, when it is the edit permission of its task ("task"): worked
    #: out by `judge`, never kept, so its box asks for that permission and nothing else.
    missing: str = ""
    #: Worked out by `judge`, never kept: the grant as data Rouh's code proposes for it when
    #: nothing covers it (`capabilities.propose`), and what covers it when something does - "held:
    #: memory", "row:12", "level:128" - with the grant's row.
    proposal: dict = field(default_factory=dict)
    via: str = ""
    cap_grant: int = 0

    @classmethod
    def of(cls, row) -> "Ask":
        """From a `MailAsk` row or a dict."""
        get = row.get if isinstance(row, dict) else (lambda k, d=None: getattr(row, k, d))
        return cls(ident=str(get("ident") or ""), quote=str(get("quote") or ""),
                   n=int(get("n") or 0), action=str(get("action") or ""),
                   label=str(get("label") or ""),
                   do=str(get("do") or ""), grant=str(get("grant") or ""),
                   new_grant=dict(get("new_grant") or {}),
                   also=[str(k) for k in (get("also") or []) if k],
                   hard_limit=limit_of(get("hard_limit")),
                   task=str(get("task") or ""),
                   task_needs=needs_of(get("task_needs")),
                   capability=str(get("capability") or ""),
                   scope=[str(x) for x in (get("scope") or []) if str(x)],
                   values=dict(get("values") or {}),
                   status=status_of(get("status")), why=str(get("why") or ""),
                   choice=str(get("choice") or ""), choice_grant=str(get("choice_grant") or ""),
                   evidence=list(get("evidence") or []),
                   work=[w for w in (get("work") or []) if isinstance(w, dict)],
                   source=str(get("source") or "reading"),
                   serves=str(get("serves") or ""), blocker=str(get("blocker") or ""),
                   gone=bool(get("gone")), attempt=int(get("attempt") or 1),
                   possible=str(get("possible") or ""))

    def as_dict(self) -> dict:
        return asdict(self)

    @property
    def named(self) -> str:
        """How the sender would know it: its label, else their own words."""
        return self.label or self.quote

    @property
    def access(self) -> bool:
        """Only the permission of its task: done by the gate itself when they hold it (`ACCESS`)."""
        return bool(self.task) and self.task_needs == ACCESS

    @property
    def answer_only(self) -> bool:
        """Only an answer, which the reply itself does."""
        return self.grant == NONE and not self.hard_limit and not self.task


#: What an ask needs on its task, besides edit (""): "read" for research about it, and "access"
#: for an ask whose whole substance is the permission - "I need edit rights in the tasks", "let
#: me talk to Rouh there". Petar, 21 October 2026, after a contact asked for edit rights she held
#: through her Decide on quest 128 and the gate handed the ask to a run as work: the run found
#: nothing to do but the permission, said twice that she needed it, and put a decision to him
#: each time. An ask for a permission held is done by the gate, at once, with no run and no
#: decision; one not held waits for that permission alone.
READ_ONLY, ACCESS = "read", "access"
#: What an ask needs on its task when it is deciding for the owner there (`tasks.decide`, D35):
#: their Decide, which is given on their page and never from a case.
DECIDE = "decide"

#: How an ask read before "access" existed says it asks for the permission itself: edit rights,
#: edit access, the right to make changes (`asks_for_access`).
_ACCESS_WORDS = re.compile(
    r"\b(?:edit(?:ing)?|write|change)\s+(?:access|rights?|permissions?)\b"
    r"|\b(?:access|rights?|permissions?)\s+to\s+(?:edit|change|make\s+changes)\b"
    r"|\bright\s+to\s+(?:edit|change|make\s+changes)\b", re.I)


def needs_of(value) -> str:
    said = str(value or "").strip().lower()
    return said if said in (READ_ONLY, ACCESS, DECIDE) else ""


def asks_for_access(a: "Ask") -> bool:
    """Whether an ask about a task asks only for the permission of it. Said so by the reading
    (`ACCESS`); an ask read before 21 October 2026 that needs no grant says it in its own words or
    in what the reading said Rouh would do ("give Sam edit access to tasks 98 and 128")."""
    if not a.task:
        return False
    if a.task_needs:
        return a.task_needs == ACCESS
    if a.grant not in ("", NONE) or a.also or a.source != "reading":
        return False
    return bool(_ACCESS_WORDS.search(" ".join([a.quote, a.label, a.do])))


def status_of(value) -> str:
    """A stored or reported status as it is now: the old word for WAITING is WAITING."""
    said = str(value or "").strip()
    return WAITING if not said or said == WAITING_BEFORE else said


def limit_of(value) -> str:
    """A stored or reported hard limit as it is now: the old word for acting as the owner is
    "as_owner"."""
    said = str(value or "").strip()
    return AS_OWNER if said == AS_OWNER_BEFORE else said


def said_of(state) -> list[list[str]]:
    """A ledger as a message said it (`said_state`), kept before or after the rename, as it is now."""
    return [[str(p[0]), status_of(p[1])] for p in (state or [])
            if isinstance(p, (list, tuple)) and len(p) >= 2]


def ident_of(quote: str) -> str:
    """An ask's id: the same words are the same ask, read again or not."""
    import hashlib

    norm = " ".join(re.sub(r"[^\w]+", " ", str(quote or "").lower()).split())
    return "a" + hashlib.sha256(norm.encode()).hexdigest()[:10]


def same(a: str, b: str) -> bool:
    """Whether two quotes are the same ask: a reading again may quote a few words more or less."""
    x = " ".join(re.sub(r"[^\w]+", " ", str(a or "").lower()).split())
    y = " ".join(re.sub(r"[^\w]+", " ", str(b or "").lower()).split())
    if not x or not y:
        return False
    return x == y or (min(len(x), len(y)) >= 12 and (x in y or y in x)) or \
        difflib.SequenceMatcher(None, x, y).ratio() >= 0.8


# --- the judge: code, from grants -----------------------------------------------------------


@dataclass
class Inbox:
    """The owner's own inbox, for asks that need it: how far it is open to the contact, how far
    the reading says the ask needs it, whether the owner allowed it once for this case, and whether
    the inbox can be written at all (`rouh/inbox_grants.py`)."""

    reach: str = "none"
    entries: list = field(default_factory=list)
    needed: str = ""
    wanted_from: list = field(default_factory=list)
    once: bool = False
    writable: bool = True


def _first(name: str) -> str:
    return (str(name or "").split() or ["them"])[0]


def judge(asks: list[Ask], contact, tree, *, identity_ok: bool = True,
          identity_said: str = "", inbox: Inbox | None = None,
          tasks: dict | None = None, done_by: dict | None = None,
          case_key: str = "") -> list[Ask]:
    """Each ask's status as code decides it from the grants, with why. Pure; returns new asks.

    Done and started asks stay as they are - what was started is its work's now (D18) - and
    gone ones too. A failed ask is judged again, as the next run would take it. Nothing but these decides: what the owner chose for the ask, who it is
    from, the hard limit it names, and whether the contact holds the grant it needs. A contact
    is a `trusted.Trusted` (None when they were removed), `tree` a `grants.Tree`.

    `tasks` is what the contact may do with each task, by number (`task_access.for_judge`):
    an ask that adds to or changes a task (`Ask.task`) goes when they may edit it - deciding for
    it includes editing - and one that only reads it (`Ask.task_needs` "read": research, a
    timeline, priorities) goes when they may read it; otherwise it waits for the owner to let
    them, which is a permission of that task and never a grant (D28). None is that it cannot be
    told here, and such an ask waits.

    `done_by` names asks a trusted contact who decides for the work already had done in this
    same message, through their own authority (`delegation.done_in_case`): {ident: what was
    done}. Such an ask is done, and says so, rather than waiting for the owner or being done
    twice (Petar, 21 October 2026: one ask, one decision).

    Grants as data (CAPABILITIES.md): what the contact page gives counts only where a capability
    in code names it (`capabilities.Capability.legacy_grant`), so a grant made from words alone
    allows nothing; an ask a page grant does not cover is covered by a grant of the contact's own
    (`contact.cap_grants`) only as `capabilities.authorize` finds, on its exact scope and limits,
    and otherwise waits with the grant Rouh's code proposes for it (`capabilities.propose`).
    `case_key` binds a grant allowed once to the message it was allowed for.
    """
    from . import capabilities as caps
    from . import grants as grant_rows

    inbox = inbox or Inbox()
    name = contact.name if contact is not None else "they"
    first = _first(name)
    implicit = contact is not None and contact.implicit
    switched_off = contact is not None and not implicit and not contact.trusted
    listed = contact is not None and not implicit and contact.trusted
    held = tree.held(contact) if contact is not None else set()
    found, lock = caps.catalogue(), caps.read_lock()
    rows = list(getattr(contact, "cap_grants", None) or []) if contact is not None else []
    # What the contact page gives, as capabilities name it: only grants code stands behind.
    keys = {k for k in held if found.by_legacy(k)}
    if any(tree.lifts(k) & set(LIFTED_BY) for k in held):
        keys.add("lift:time")
    backed = {k for k in held if found.by_legacy(k) or tree.lifts(k)}

    def cap_of(a: Ask):
        """The capability an ask is: the one the reading named, else the one its grant names."""
        got = found.get(a.capability) if a.capability and a.capability != UNSUPPORTED else None
        if got is None and a.grant and a.grant != NONE:
            named = found.by_legacy(tree.resolve(a.grant) or a.grant)
            got = named[0] if len(named) == 1 else next(
                (c for c in named if c.action == a.action), named[0] if named else None)
        return got

    def by_rows(a: Ask, cap):
        return caps.authorize(cap, contact, scope=a.scope, values=a.values, held=set(),
                              rows=rows, tasks=tasks, lock=lock, case_key=case_key, ask=a.ident)

    def propose(a: Ask, cap) -> dict:
        if cap is None or not cap.grantable or not listed:
            return {}
        return caps.propose(cap, contact.id, a.scope, a.values)

    out = []
    for one in asks:
        a = Ask(**{**one.as_dict(), "missing": ""})
        out.append(a)
        tasked = found.get(a.capability) if a.capability else None
        if tasked is not None and tasked.authority == "task_level" and a.task:
            # What a task's capability needs is the capability's, never what was stored with it.
            a.task_needs = {"view": READ_ONLY, "edit": "", "decide": DECIDE}[tasked.level] \
                if tasked.action != "access" else ACCESS
        if a.gone or a.status in GONE_ON:
            continue
        if (done_by or {}).get(a.ident):
            said = " ".join(str(done_by[a.ident]).split())
            a.status = DONE
            a.why = f"Done already: {said.rstrip('.')}." if said else "Done already."
            if not any(e.get("said") == said for e in a.evidence if isinstance(e, dict)):
                a.evidence = [*a.evidence, evidence_line(said or "done", attempt=a.attempt)]
            continue
        if a.choice in (DECLINE, MINE):
            a.status = DECLINED
            a.why = ("You declined it." if a.choice == DECLINE else
                     "You said you see to it yourself, so Rouh does not.")
            continue
        limit = a.hard_limit if a.hard_limit in grant_rows.HARD_LIMITS else ""
        if a.choice == GRANT and a.choice_grant and not a.grant and \
                tree.resolve(a.choice_grant):
            # The grant the owner set up for it and gave is the grant it needs from now on.
            a.grant = tree.resolve(a.choice_grant)
        if contact is None:
            a.status, a.why = WAITING, "The contact behind it was removed from your Trusted contacts."
            continue
        if not identity_ok and a.choice != ONCE:
            a.status = WAITING
            a.why = ("It is not certain who sent it" + (f" ({identity_said})" if identity_said
                                                         else "")
                     + ", so nothing of it is done without you.")
            continue
        if asks_for_access(a) and not switched_off:
            a.task_needs = ACCESS
            ok, why = _task_holds(a, tasks, first)
            if ok:
                # The permission is what they asked for, and they hold it: the gate does it by
                # itself (`access_done`), with no run, so nothing a run said it needed - a hard
                # limit included - is touched by it.
                a.status = APPROVED if a.choice == GRANT else ALLOWED
                a.why = why
                continue
        if limit:
            said = grant_rows.limits_said([limit])
            lifter = found.get(LIFTED_BY.get(limit, "")) if grant_rows.liftable(limit) else None
            if lifter is not None:
                # A grant can lift it (Petar, 15 October 2026, fr_0cefb1d3ed8a): one on their
                # page that lifts it, or one of their own as data, on its exact calendars.
                a.capability = lifter.id
                a.new_grant = {}
            if a.choice == ONCE:
                a.status, a.why = APPROVED, "You allowed it once, hard limit and all."
            elif lifter is not None:
                v = caps.authorize(lifter, contact, scope=a.scope, values=a.values, held=keys,
                                   rows=rows, tasks=tasks, lock=lock, case_key=case_key,
                                   ask=a.ident) if not switched_off and listed else None
                if v is not None and v.ok:
                    gave = a.choice == GRANT
                    a.status = APPROVED if gave else ALLOWED
                    a.via, a.cap_grant = v.ref, v.grant_id
                    a.grant = tree.lifting(limit, contact) if v.via == "held" else ""
                    what = tree.path_said(a.grant) if a.grant else f"grant {v.grant_id}"
                    a.why = ((f"You gave {first} {what}" if gave else f"{first} holds {what}")
                             + f", which lifts this hard limit for them: {said}.")
                else:
                    a.status = WAITING
                    a.grant = ""
                    a.proposal = propose(a, lifter)
                    a.why = (f"It touches a hard limit, {said}. A grant can lift it for {first}"
                             + (": give it as Rouh proposes, or allow it once." if a.proposal
                                else "; allow it once, or not."))
            else:
                a.status = WAITING
                a.why = f"It touches a hard limit, {said}, which only you ever decide."
            continue
        if a.choice == ONCE:
            a.status, a.why = APPROVED, "You allowed it once."
            continue
        if switched_off:
            a.status, a.why = WAITING, f"{name} is switched off on your Trusted contacts."
            continue
        if a.task:
            ok, why = _task_holds(a, tasks, first)
            if not ok:
                a.status, a.why, a.missing = WAITING, why, "task"
                continue
            if not a.grant or a.grant in (NONE, "communicate"):
                a.status, a.why = (APPROVED if a.choice == GRANT else ALLOWED), why
                continue
            # It needs a grant as well, as work for them does: judged by it below.
        if a.grant in (NONE, "communicate"):
            key = tree.resolve("communicate") or "communicate"
            if key in held:
                a.status, a.why = ALLOWED, "Only an answer, which Communication covers."
            else:
                a.status, a.why = WAITING, f"Even an answer needs Communication, which {name} does not hold."
            continue
        if a.capability == UNSUPPORTED:
            a.status = WAITING
            a.why = ("Rouh has no way to do this: nothing it can be given does it. See to it "
                     "yourself, or decline it.")
            continue
        if not a.grant and _own_decision((a.new_grant or {}).get("name")):
            # Raised before 15 October 2026 as the owner's own decision, which offered nothing
            # to grant: proposed as a grant now, from what the work said it needs.
            a.new_grant = proposal_from(a.do or a.label or a.quote)
        if not a.grant and cap_of(a) is not None and not a.new_grant:
            # A capability no grant on their page names - one a gene brought since, say: only a
            # grant of their own covers it, on its exact scope and limits (CAPABILITIES.md).
            cap = cap_of(a)
            v = by_rows(a, cap) if listed and cap.authority == "grant" else None
            if v is not None and v.ok:
                gave = a.choice == GRANT
                a.status = APPROVED if gave else ALLOWED
                a.via, a.cap_grant = v.ref, v.grant_id
                a.why = ("You gave " if gave else "") + v.reason
                continue
            a.status = WAITING
            a.proposal = propose(a, cap)
            a.why = (f"{first} holds no grant for {cap.name}"
                     + (": Rouh proposes one of its own for it." if a.proposal else
                        ": allow it once, or not."))
            continue
        if not a.grant:
            a.status = WAITING
            if one_off(a.new_grant):
                a.why = ("The work needed something nothing they hold names: allow it once, or "
                         "decline it.")
                continue
            # Read before grants were data, as a grant a model wrote in words: words allow
            # nothing now (CAPABILITIES.md), so it is once, or not - or Redo to read it again.
            a.why = ("It was read as a grant written in words, and words allow nothing now: "
                     "allow it once, decline it, or Redo to have it read again.")
            continue
        key = tree.resolve(a.grant)
        if not key:
            a.status, a.why = WAITING, f"It names a grant, {a.grant}, that is not there."
            continue
        gave = a.choice == GRANT
        if key in ("inbox", "inbox_write"):
            ok, why = _inbox_holds(key, inbox, first)
            if ok:
                a.status, a.why = (APPROVED if gave else ALLOWED), why
            else:
                a.status, a.why = WAITING, why
            continue
        cap = cap_of(a)
        if not found.by_legacy(key) and not tree.lifts(key):
            # Made from words alone, with no capability behind it: it allows nothing now
            # (CAPABILITIES.md, Migration). Kept, and listed for review.
            a.status = WAITING
            a.why = (f"{tree.path_said(key)} was made from words alone, and words allow nothing "
                     "now: give a grant Rouh proposes, or allow it once.")
            continue
        covered = None
        if key not in backed and not switched_off:
            covered = by_rows(a, cap) if cap is not None and cap.rows else None
            if covered is None or not covered.ok:
                a.status = WAITING
                a.proposal = propose(a, cap)
                a.why = (f"It needs {tree.path_said(key)}, which {first} does not hold"
                         + (": Rouh proposes a grant of its own for it." if a.proposal else "."))
                continue
            a.via, a.cap_grant = covered.ref, covered.grant_id
        elif cap is not None:
            a.via = f"held:{key}"
        # What it needs as well: Clockwork does at a time only what their other grants allow.
        lacking = ""
        for other in a.also:
            got = tree.resolve("communicate" if other == NONE else other)
            if not got:
                lacking = f"It needs {other} as well, a grant that is not there."
                break
            if got not in backed and not any(
                    caps.authorize(c, contact, held=set(), rows=rows, lock=lock,
                                   case_key=case_key, ask=a.ident).ok
                    for c in found.by_legacy(got) if c.rows):
                lacking = (f"It needs {tree.path_said(got)} as well, which {first} does not "
                           "hold.")
                break
        if lacking:
            a.status, a.why = WAITING, lacking
            continue
        also = [tree.path_said(tree.resolve("communicate" if o == NONE else o)) for o in a.also]
        a.status = APPROVED if gave else ALLOWED
        if covered is not None:
            a.why = (("You gave " if gave else "") + covered.reason.rstrip(".")
                     + (" and " + " and ".join(also) if also else "") + ".")
            continue
        a.why = ((f"You gave {first} {tree.path_said(key)}" if gave else
                  f"{first} holds {tree.path_said(key)}")
                 + (" and " + " and ".join(also) if also else "")
                 + ("." if gave else ", which cover it." if also else ", which covers it."))
    # The owner set what goes beyond a contact's grants to be declined: that is their standing no.
    if contact is not None and not implicit and contact.trusted and \
            getattr(contact, "beyond", "ask") in ("decline", "decline_tell"):
        for a in out:
            if a.status == WAITING and not a.hard_limit and identity_ok and not a.choice:
                a.status = DECLINED
                a.why = f"You set what goes beyond {first}'s grants to be declined."
    return out


def task_said(number: str, tasks: dict | None) -> str:
    """A task as an ask names it: "task 90, Garden shed plans ..."."""
    one = (tasks or {}).get(str(number or "").lstrip("#")) or {}
    title = " ".join(str(one.get("title") or "").split())
    return f"task {number}" + (f", {title}" if title else "")


#: The levels of the one permission, lowest first (`rouh/task_access.py`), here without it so
#: the replay needs nothing but the standard library.
_LEVEL_RANK = {"": 0, "view": 1, "edit": 2, "decide": 3}


def _task_holds(a: Ask, tasks: dict | None, first: str) -> tuple[bool, str]:
    """Whether the contact may do with every task the ask names - its own, and any its work
    found it needs as well (`Ask.scope`) - what it needs: read it, or change it; and why (D28)."""
    others = [n for n in a.scope if n != a.task and TASK_NUMBER.match(n)]
    for other in others:
        ok, why = _one_task_holds(Ask(**{**a.as_dict(), "task": other, "scope": []}), tasks,
                                  first)
        if not ok:
            return ok, why
    ok, why = _one_task_holds(a, tasks, first)
    if ok and others:
        why = why.rstrip(".") + f", and the work needs task {', '.join(others)} as well, which " \
                                "they may."
    return ok, why


#: A task's number as an ask names it.
TASK_NUMBER = re.compile(r"^\d{1,6}(?:-\d{1,3})?$")


def _one_task_holds(a: Ask, tasks: dict | None, first: str) -> tuple[bool, str]:
    number = str(a.task or "").lstrip("#")
    if tasks is None:
        return False, (f"Whether {first} may change task {number} cannot be told on this "
                       "machine, so it waits for you.")
    one = tasks.get(number)
    if one is None:
        return False, f"It names task {number}, which is not there."
    named = task_said(number, tasks)
    level = one.get("level") or ""
    rank = _LEVEL_RANK.get(level, 0)
    may = {"decide": "decides for", "edit": "may edit", "view": "may read"}.get(level, "")
    if a.task_needs == DECIDE:
        if rank >= _LEVEL_RANK["decide"]:
            return True, f"{first} decides for {named}, which covers it."
        return False, (f"{first} does not decide for {named}: Decide is given on their page, "
                       "never from a message. Allow it once, or not.")
    if a.task_needs == "read":
        if rank >= _LEVEL_RANK["view"]:
            return True, (f"You let {first} read {named}." if a.choice == GRANT else
                          f"{first} {may} {named}, and this only reads it.")
        return False, f"{first} may not open {named}: let them read it, or allow it once."
    if rank >= _LEVEL_RANK["edit"]:
        if a.task_needs == ACCESS:
            return True, (f"You let {first} edit {named}." if a.choice == GRANT else
                          f"{first} {may} {named}, which already lets them change it and talk "
                          "to Rouh in it: what they asked for is theirs.")
        return True, (f"You let {first} edit {named}." if a.choice == GRANT else
                      f"{first} {may} {named}, which covers it.")
    if rank == _LEVEL_RANK["view"]:
        return False, f"{first} may only read {named}: let them edit it, or allow it once."
    return False, f"{first} may not open {named}: let them edit it, or allow it once."


def _own_decision(name) -> bool:
    """Whether a proposed grant's name is what a need the work raised was called before 15
    October 2026, when no grant was named: "<the owner's name>'s own decision", kept so on rows
    of then. It proposed nothing."""
    return str(name or "").endswith("'s own decision")


def proposal_from(what: str) -> dict:
    """A grant proposed from the words of what is needed, when the work named none (Petar, 15
    October 2026, fr_0cefb1d3ed8a: "The correct behavior was that I get another grant creation
    that I can grant the person"). A grant of its own, with no tools: nothing new is done by it
    without code that does it, but the ask is covered once he gives it. Pure."""
    text = " ".join(str(what or "").split())
    text = re.sub(r"^Needed by [^:]{1,80}:\s*", "", text)
    clause = re.split(r"(?<=[a-z])[.;:]\s|\s(?:so|so that|because)\s", text, maxsplit=1)[0]
    words = clause.split()
    name = " ".join(words[:7]).rstrip(",.;:") + ("…" if len(words) > 7 else "")
    name = (name[:1].upper() + name[1:]) if name else "What the work needs"
    # One case's sentence is no grant (Petar, 18 October 2026, fr_aa3ca23c06f7: "a
    # [contact]-specific, situation-specific item that is not worth it a place in settings page"):
    # it is put to him as allow it once, or give them a grant there is or a new category.
    return {"name": name[:80], "title": text[:200], "description": text[:1500],
            "prompt": text[:2000], "suggestion": "independent", "target": "",
            "why_not": "The work needed it, and no grant there is covers it.", "one_off": True}


def one_off(proposal: dict | None) -> bool:
    """Whether a proposed grant is only one case's sentence (`proposal_from`), never a grant to
    create as it stands: those made before 18 October 2026 are told by the name cut short."""
    proposal = proposal or {}
    if proposal.get("lifts"):
        return False
    return bool(proposal.get("one_off")) or str(proposal.get("name") or "").endswith("…")


def _inbox_holds(key: str, inbox: Inbox, first: str) -> tuple[bool, str]:
    """Whether the contact's inbox reach covers an ask that needs the owner's inbox, and why."""
    from . import trusted as trust

    if key == "inbox_write":
        if inbox.reach != trust.INBOX_WRITE and not inbox.once:
            return False, f"It needs changing your inbox, which {first} may not have done."
        if not inbox.writable:
            return False, ("It needs changing your inbox, and your inbox is connected read-only "
                           "until Gmail is connected again with write access.")
        return True, f"{first} may have your inbox changed for them."
    if inbox.once:
        return True, "You let Rouh read your inbox for this message once."
    needed = inbox.needed if inbox.needed in trust.INBOX_SCOPES else trust.INBOX_SEARCH
    if inbox.reach == trust.INBOX_NONE or \
            trust.INBOX_RANK.get(inbox.reach, 0) < trust.INBOX_RANK[needed]:
        return False, (f"It needs your inbox ({trust.INBOX_SCOPES[needed][0]}), and for {first} "
                       f"it is {trust.inbox_said(inbox.reach, inbox.entries).lower()}.")
    if needed == trust.INBOX_SENDERS and inbox.reach == trust.INBOX_SENDERS:
        wanted = {str(e).strip().lower() for e in inbox.wanted_from}
        if not wanted <= {str(e).lower() for e in inbox.entries}:
            return False, "It needs mail from senders their inbox reach does not name."
    return True, f"{first} may have your inbox read that far."


def rejudge(asks: list[Ask], contact, tree, **judging) -> list[Ask]:
    """The ledger judged again as a dry run (Petar, 12 October 2026, D15): what every place
    that shows a case reads, and what is written back whenever something that can change an
    outcome changed. Pure; nothing runs and nothing is sent.

    Each ask takes `judge`'s status and why, except a failed one, which stays failed - it was
    tried and did not get done, and only a run changes that - and is marked `possible`, with
    the reason, when a run would do it now: "Sam holds Clockwork and Communication, which
    cover it". A failed
    ask the owner has since declined, or said they see to themselves, is declined, as his choice says.
    """
    asks = fold(asks, contact, tree, **judging)
    judged = judge(asks, contact, tree, **judging)
    first = _first(contact.name if contact is not None else "they")
    out = []
    for was, now in zip(asks, judged):
        if was.status != FAILED or was.gone:
            out.append(now)
            continue
        if now.status == DECLINED and was.choice in (DECLINE, MINE):
            out.append(now)
            continue
        kept = Ask(**{**was.as_dict(), "possible": ""})
        if now.status in (ALLOWED, APPROVED):
            # One about a task goes by what they may do with it, said as the judge said it.
            kept.possible = now.why.rstrip(".") if was.task and was.choice != ONCE and (
                not was.grant or was.grant == NONE) else _possible_said(was, tree, first)
        out.append(kept)
    return out


def _possible_said(a: Ask, tree, first: str) -> str:
    """Why a failed ask would go now, as a run would judge it: "Sam holds Clockwork and
    Communication, which cover it". Not why it failed, which may have been the work."""
    if a.choice == ONCE:
        return "you allowed it once"
    if a.grant in (NONE, "communicate") and not a.also:
        return f"{first} holds Communication, which covers it"
    keys = [k for k in [a.grant, *a.also] if k]
    names = list(dict.fromkeys(tree.name(tree.resolve("communicate" if k == NONE else k) or k)
                               for k in keys))
    return (f"{first} holds " + " and ".join(names)
            + (", which cover it" if len(names) > 1 else ", which covers it"))


# --- what the ledger says -------------------------------------------------------------------


def live(asks: list[Ask]) -> list[Ask]:
    return [a for a in asks if not a.gone]


def counts(asks: list[Ask]) -> dict[str, int]:
    out = {s: 0 for s in STATUSES}
    for a in live(asks):
        out[a.status] = out.get(a.status, 0) + 1
    return out


def to_do(asks: list[Ask]) -> list[Ask]:
    """What the next run does: allowed or approved, and not done."""
    return [a for a in live(asks) if a.status in (ALLOWED, APPROVED)]


def waiting(asks: list[Ask]) -> list[Ask]:
    """What waits for the owner's decision."""
    return [a for a in live(asks) if a.status == WAITING]


def needs_owner(asks: list[Ask]) -> list[Ask]:
    """What only the owner moves on once the case rests: waiting for their decision, failed
    (their Redo tries again), or approved or allowed and waiting for their run."""
    return [a for a in live(asks) if a.status in (WAITING, FAILED, APPROVED, ALLOWED)]


#: The name `needs_owner` had before 20 October 2026, which migration 0121 still calls.
needs_petar = needs_owner


def said_state(asks: list[Ask]) -> list[list[str]]:
    """The ledger as a message says it: each ask's id and status, in order. Two messages that
    would say the same are one (`mail_outbox`)."""
    return [[a.ident, a.status] for a in sorted(live(asks), key=lambda a: (a.n, a.ident))
            if not a.answer_only]


def _signed(status: str) -> str:
    """A status as the hashes kept on rows were taken with it: WAITING by its word of before
    the rename, so a signature or a decision's print made then is the same one now."""
    return WAITING_BEFORE if status == WAITING else status


def signature(asks: list[Ask]) -> str:
    import hashlib
    import json

    state = [[i, _signed(s)] for i, s in said_state(asks)]
    return hashlib.sha256(json.dumps(state).encode()).hexdigest()[:16]


def decision_signature(asks: list[Ask]) -> str:
    """What one decision about a case is bound to: the asks it puts to the owner, each with what it
    needs. A change to any makes a new decision, and the old one is withdrawn (D8)."""
    import hashlib
    import json

    parts = [[a.ident, _signed(a.status), a.grant, a.hard_limit, (a.new_grant or {}).get("name") or "",
              a.choice] + (["possible"] if a.possible else []) + ([a.task] if a.task else [])
             # A grant Rouh proposes is bound by what it would give: a change to it is a new
             # decision, so an answer to the old one is never an approval of the new.
             + ([a.capability, _proposal_digest(a)] if a.proposal else [])
             for a in sorted(needs_owner(asks), key=lambda a: (a.n, a.ident))]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:16]


def _proposal_digest(a: Ask) -> str:
    from . import capabilities

    return capabilities.digest(a.proposal) if a.proposal else ""


def rest_stage(asks: list[Ask]) -> str:
    """Where a case rests when nothing runs, from its ledger alone (D1).

    Anything the owner has to move - waiting for their decision, failed, or allowed or approved
    and not yet run - waits for them. Every ask declined by them is a case declined; the rest is done:
    started or done, which is all the gate does (D18).
    """
    now = live(asks)
    if any(a.status in (WAITING, FAILED, APPROVED, ALLOWED) for a in now):
        return AWAITING
    if now and all(a.status == DECLINED for a in now):
        return BLOCKED
    return DONE_STAGE


def need_named(a: Ask, tree=None, contact_name: str = "") -> str:
    """What a waiting ask needs, in a few words: "Clockwork for Sam", "a new grant, Shopping
    lists", "a hard limit: committing your time"."""
    from . import grants as grant_rows

    first = _first(contact_name) if contact_name else ""
    if a.capability == UNSUPPORTED:
        return "you: Rouh has no way to do it"
    if a.proposal:
        from . import capabilities

        cap = capabilities.catalogue().caps.get(a.proposal.get("capability") or "")
        name = cap.name if cap is not None else a.proposal.get("capability")
        return f"a grant: {name}" + (f", for {first}" if first else "") + (
            ", which lifts " + grant_rows.limits_said([a.hard_limit]) if a.hard_limit else "")
    if a.task and a.task_needs == DECIDE and a.status == WAITING:
        return f"deciding for task {a.task}" + (f", for {first}" if first else "")
    if a.task and (a.missing == "task" or not a.hard_limit and (not a.grant or a.grant == NONE)):
        return f"permission to edit task {a.task}" + (f", for {first}" if first else "")
    if a.hard_limit:
        limit = "a hard limit: " + grant_rows.limits_said([a.hard_limit])
        if grant_rows.liftable(a.hard_limit) and (a.grant or (a.new_grant or {}).get("lifts")):
            name = (tree.name(a.grant) if tree is not None and a.grant else
                    a.grant or (a.new_grant or {}).get("name"))
            new = "" if a.grant else "a new grant, "
            return f"{new}{name}" + (f", for {first}" if first else "") + f", which lifts {limit}"
        return limit
    if not a.grant and one_off(a.new_grant):
        return "your approval, once or with a grant" + (f", for {first}" if first else "")
    if not a.grant:
        name = (a.new_grant or {}).get("name") or "a grant there is not yet"
        return f"a new grant, {name}" + (f", for {first}" if first else "")
    if tree is not None:
        name = tree.name(a.grant)
    else:
        name = a.grant
    if a.grant == NONE:
        name = "Communication"
    return f"{name} for {first}" if first else name


def why_line(asks: list[Ask], *, stage: str = "", step_words: str = "", tree=None,
             contact_name: str = "") -> str:
    """One plain line on why a case is where it is (D12), from the ledger alone: "2 of 3 asks
    done, 1 waits for you: Clockwork for Sam." While Rouh works on it, `step_words` says what
    it is doing first."""
    now = live(asks)
    if stage == "junk_spam":
        return "It was read as junk and moved to Gmail's Spam, where it can be recovered."
    if stage == "junk_not_moved":
        return "It was read as junk; Gmail would not move it, so it was left where it is."
    if stage == MERGED:
        return "The same request came again here: it is part of the earlier case, and goes with it."
    if not now:
        if step_words:
            return step_words.rstrip(".") + "."
        return "Nothing in it asked for anything, so nothing was done or sent."
    c = counts(now)
    total = len(now)
    one = total == 1
    to_run = c[ALLOWED] + c[APPROVED]
    wait = [a for a in now if a.status == WAITING]
    # Failed, and a run would do it now (`rejudge`): tried again by itself, never his choice
    # (D34), until it has failed `MAX_TRIES` times.
    ready = [a for a in now if a.status == FAILED and a.possible and not gave_up(a)]
    failed = [a for a in now if a.status == FAILED and a not in ready]
    parts = []
    if c[STARTED] and c[DONE]:
        parts.append(f"{c[STARTED]} of {total} asks started, {c[DONE]} done")
    elif c[STARTED]:
        parts.append("started" if one else f"{c[STARTED]} of {total} asks started")
    elif c[DONE]:
        parts.append("done" if one else f"{c[DONE]} of {total} asks done")
    if to_run:
        parts.append(("being done" if one else f"{to_run} being done") if step_words else
                     ("it waits for your Redo" if one else
                      f"{to_run} wait{'s' if to_run == 1 else ''} for your Redo"))
    if wait:
        needs = list(dict.fromkeys(need_named(a, tree, contact_name) for a in wait))
        parts.append(("it waits for you: " if one else
                      f"{len(wait)} wait{'s' if len(wait) == 1 else ''} for you: ")
                     + "; ".join(needs[:3]) + ("" if len(needs) <= 3 else
                                               f" and {len(needs) - 3} more"))
    if ready:
        said = "; ".join(f"{_short(a.named, 80).rstrip('.')} ({a.possible})" for a in ready[:3])
        parts.append(("failed, and is tried again by itself: " if one else
                      f"{len(ready)} failed and {'is' if len(ready) == 1 else 'are'} tried again "
                      "by itself: ") + said)
    if c[DECLINED]:
        parts.append("declined by you" if one else f"{c[DECLINED]} declined by you")
    if failed:
        parts.append(("failed" if one else f"{len(failed)} failed")
                     + (f" {tries(failed[0])} times" if gave_up(failed[0]) else "") + ": "
                     + _short(failed[0].why, 90).rstrip("."))
    line = ", ".join(parts)
    if step_words:
        line = step_words.rstrip(".") + (": " + line if line else "")
    line = line or "Nothing to do."
    return line[:1].upper() + line[1:].rstrip(".") + "."


def _short(text: str, most: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


# --- what the contact is told: the code's own words (D4, D18) ------------------------------

#: The gate's words, in each language the code writes them in. The gate says only what it
#: decided itself - started, done at once, waiting for the owner, declined - so nothing in them
#: needs checking against the work (D18).
SAID = {
    "en": {"head": "Where your requests stand:",
           DONE: "Done: {label}.",
           STARTED: "Allowed, and started: {label}.",
           WAITING: "Needs {owner}'s permission first, so it waits: {label}.",
           DECLINED: "Will not be done: {label}.",
           "mine": "{owner} is seeing to it himself: {label}.",
           FAILED: "Could not be started yet: {label}.",
           "doing": "Being started now: {label}.",
           "got": "Got it, {first}.",
           "tail_waiting": "I'll write again once {owner} has decided.",
           "tail_started": "What each started one brings reaches you from it, as it is ready.",
           "decided": "{first}, {owner} has decided on your request:",
           "approved": "Approved, and started: {label}.",
           "approved_done": "Approved, and done: {label}.",
           "corrected": "{first}, a correction to my last message: these did not need to wait "
                        "for {owner} after all. What {owner} has already let you do covers "
                        "them, so they go ahead now. I am sorry for the confusion.",
           "covered": "Covered by what you may already do, and started: {label}.",
           "covered_done": "Covered by what you may already do, and already done: {label}.",
           "still": "Still waiting for {owner}: {label}.",
           "gave_up": "Tried {n} times, and it could not be done: {label}. {owner} can see why.",
           "reason": "{owner} wrote: “{reason}”",
           "blocked": "{first}, part of your request needs {owner}'s permission first, so "
                      "it waits:",
           "results": "{first}, here is what came of your request:",
           "result": "About {label}:",
           "sign": "Rouh, {owner}'s assistant"},
    "bg": {"head": "Докъде стигнаха молбите ти:",
           DONE: "Готово: {label}.",
           STARTED: "Разрешено и започнато: {label}.",
           WAITING: "Първо трябва разрешение от {owner}, затова чака: {label}.",
           DECLINED: "Няма да бъде направено: {label}.",
           "mine": "{owner} ще се погрижи сам: {label}.",
           FAILED: "Още не можа да започне: {label}.",
           "doing": "Започва сега: {label}.",
           "got": "Получих го, {first}.",
           "tail_waiting": "Ще ти пиша отново, щом {owner} реши.",
           "tail_started": "Каквото донесе всяко започнато, ще стигне до теб от него, щом е "
                           "готово.",
           "decided": "{first}, {owner} реши за молбата ти:",
           "approved": "Одобрено и започнато: {label}.",
           "approved_done": "Одобрено и готово: {label}.",
           "corrected": "{first}, поправка към предишното ми писмо: тези неща всъщност не "
                        "трябваше да чакат {owner}. Това, което {owner} вече ти е позволил, "
                        "ги покрива, така че продължават сега. Извинявай за объркването.",
           "covered": "Покрито от това, което вече можеш, и започнато: {label}.",
           "covered_done": "Покрито от това, което вече можеш, и вече готово: {label}.",
           "still": "Още чака {owner}: {label}.",
           "gave_up": "Опитах {n} пъти и не стана: {label}. {owner} може да види защо.",
           "reason": "{owner} написа: „{reason}“",
           "blocked": "{first}, една част от молбата ти първо има нужда от разрешение от "
                      "{owner}, затова чака:",
           "results": "{first}, ето какво излезе от молбата ти:",
           "result": "За {label}:",
           "sign": "Rouh, асистентът на {owner}"},
}

#: The languages the owner's name is written in its own way in, each with the setting that
#: says how: pairs of "<name>=<how this language writes it>", separated by commas, such as
#: ROUH_OWNER_NAMES_BG="Alex=Алекс". Nobody's name is written here: a name with no pair is
#: written as it is.
OWNER_NAMES_SETTING = {"bg": "ROUH_OWNER_NAMES_BG"}


def owner_in(lang: str, owner: str) -> str:
    """The owner's name as a language writes it, from the installation's setting, else as it is."""
    setting = OWNER_NAMES_SETTING.get(lang)
    if not setting or not owner:
        return owner
    from .config import _env

    for pair in _env(setting).split(","):
        name, eq, said = pair.partition("=")
        if eq and name.strip() == owner and said.strip():
            return said.strip()
    return owner


def language_of(code: str) -> str:
    code = str(code or "").strip().lower()[:2]
    return code if code in SAID else "en"


def _label(a: Ask) -> str:
    return " ".join(a.named.split()).rstrip(".")


def status_lines(asks: list[Ask], *, language: str = "en", owner: str = "‹owner›",
                 doing: bool = False) -> list[str]:
    """Each ask that is not only an answer, as one line in the contact's language.

    `doing` says asks allowed or approved and not started yet as being started now. Once the
    gate has run each is started, done, waiting, declined or failed.
    """
    lang = language_of(language)
    words = SAID[lang]
    who = owner_in(lang, owner)
    out = []
    for a in sorted(live(asks), key=lambda a: (a.n, a.ident)):
        if a.answer_only:
            continue
        if a.status in (DONE, STARTED, WAITING, FAILED):
            line = words[a.status]
        elif a.status == DECLINED:
            line = words["mine"] if a.choice == MINE else words[DECLINED]
        elif doing:
            line = words["doing"]
        else:
            line = words[FAILED]
        out.append("- " + line.format(label=_label(a), owner=who)
                   + (" " + to_them(a) if to_them(a) else ""))
    return out


def all_approved(asks: list[Ask]) -> bool:
    """Every ask that is not only an answer was allowed and started, or done (D20)."""
    listed = [a for a in live(asks) if not a.answer_only]
    return bool(listed) and all(a.status in (STARTED, DONE) for a in listed)


def status_section(asks: list[Ask], *, language: str = "en", owner: str = "‹owner›",
                   doing: bool = False) -> str:
    """The status part of a message to the contact, written by code from the ledger (D4), or ""
    when the message answers one question and nothing else stands open, since then the answer
    says it all, or when every ask was allowed and started or done: they need not be told which
    checks passed (D20)."""
    lines = status_lines(asks, language=language, owner=owner, doing=doing)
    if not lines or all_approved(asks):
        return ""
    return SAID[language_of(language)]["head"] + "\n" + "\n".join(lines)


#: A closing of a reply the model wrote: the lines from here down are its sign-off, and the
#: status part goes above them.
_SIGN = re.compile(r"(?:^|\n)\s*(?:best(?: regards)?|kind regards|regards|thanks|thank you|"
                   r"warm(?:ly| regards)|cheers|all the best|с уважение|поздрави|благодаря|"
                   r"хубав ден)[^\n]{0,40}\n(?:[^\n]{0,60}\n?){0,3}\s*$|"
                   r"(?:^|\n)\s*(?:\u2014|-)?\s*rouh\b[^\n]{0,60}(?:\n[^\n]{0,60}){0,2}\s*$",
                   re.IGNORECASE)


def compose(content: str, asks: list[Ask], *, language: str = "en", owner: str = "‹owner›",
            first: str = "", doing: bool = False) -> str:
    """A message to the contact: the model's friendly content, and the code's status part.

    The status part goes above the content's own sign-off when it has one, and at the end
    otherwise. The content is never read for what it says about status (D4): it was written
    not to say any, and what is true is below it.
    """
    content = str(content or "").replace("\r\n", "\n").strip()
    section = status_section(asks, language=language, owner=owner, doing=doing)
    if not section:
        # Every ask went: what a permission they asked for lets them do is still theirs to know.
        section = "\n".join(dict.fromkeys(x for x in (to_them(a) for a in live(asks)) if x))
    if not section:
        return content
    found = _SIGN.search(content)
    if found and found.start() > 0:
        body, sign = content[:found.start()].rstrip(), content[found.start():].strip()
        return f"{body}\n\n{section}\n\n{sign}".strip()
    return f"{content}\n\n{section}".strip() if content else section


def _tails(asks: list[Ask], words: dict, who: str) -> list[str]:
    """What the contact can expect next: the owner's word for what waits, and each started one's
    own result (D18)."""
    now = live(asks)
    out = []
    if any(a.status == WAITING for a in now):
        out.append(words["tail_waiting"].format(owner=who))
    if any(a.status == STARTED for a in now):
        out.append(words["tail_started"])
    return out


def first_email(content: str, asks: list[Ask], *, language: str = "en", owner: str = "‹owner›",
                first: str = "") -> str:
    """The gate's first message, sent as soon as the asks are sorted (D18, 2a): the model's
    answer and any quick result, then which asks are allowed and started, done at once, or need
    the owner's permission and wait, all of that the code's, and what comes next."""
    lang = language_of(language)
    words = SAID[lang]
    who = owner_in(lang, owner)
    content = str(content or "").replace("\r\n", "\n").strip()
    if not content and not status_lines(asks, language=lang, owner=owner):
        return ""
    body = compose(content or words["got"].format(first=first or "there"), asks,
                   language=lang, owner=owner, first=first)
    tails = "\n".join(_tails(asks, words, who))
    if not tails:
        return body
    found = _SIGN.search(body)
    if found and found.start() > 0:
        return f"{body[:found.start()].rstrip()}\n\n{tails}\n\n{body[found.start():].strip()}"
    return f"{body}\n\n{tails}\n\n{words['sign'].format(owner=who)}"


def decided_email(asks: list[Ask], said_before, *, language: str = "en", owner: str = "‹owner›",
                  first: str = "", reason: str = "") -> str:
    """One message for one batch of the owner's decisions (D18, 2b), or "" when nothing they
    decided changed what they were last told: what they approved, and has started or is done;
    one plain line for each they declined, with their reason only when they wrote one; what
    still waits for them. `said_before` is the ledger as the last message said it (`said_state`)."""
    lang = language_of(language)
    words = SAID[lang]
    who = owner_in(lang, owner)
    was = {i: s for i, s in said_of(said_before)}
    lines, still = [], []
    # Told it waited for the owner, and then let go with no choice of theirs: what the contact
    # holds covered it all along (a permission they were given, deciding included), so the
    # message says that, and corrects the last one, rather than that the owner decided.
    corrected = False
    for a in sorted(live(asks), key=lambda a: (a.n, a.ident)):
        if a.answer_only or was.get(a.ident) == a.status:
            continue
        # Approved when the owner chose it or it was waiting for them; otherwise it was allowed all
        # along and only started now.
        covered = was.get(a.ident) == WAITING and a.choice not in (GRANT, ONCE, DECLINE, MINE)
        approved = a.choice in (GRANT, ONCE) or was.get(a.ident) == WAITING
        corrected = corrected or covered and a.status in GONE_ON
        if a.status == STARTED:
            lines.append(words["covered" if covered else "approved" if approved else STARTED]
                         .format(label=_label(a)))
        elif a.status == DONE:
            lines.append(words["covered_done" if covered else "approved_done" if approved
                               else DONE].format(label=_label(a))
                         + (" " + to_them(a) if to_them(a) else ""))
        elif a.status == DECLINED:
            lines.append((words["mine"] if a.choice == MINE else words[DECLINED])
                         .format(label=_label(a), owner=who))
        elif gave_up(a):
            # Covered, tried again by itself, and still not possible: said once, as it is (D34).
            lines.append(words["gave_up"].format(label=_label(a), owner=who, n=tries(a)))
    if not lines:
        return ""
    for a in sorted(live(asks), key=lambda a: (a.n, a.ident)):
        if a.status == WAITING and not a.answer_only:
            still.append(words["still"].format(label=_label(a), owner=who))
    by_owner = any(a.choice in (GRANT, ONCE, DECLINE, MINE) for a in live(asks)
                   if was.get(a.ident) != a.status)
    head = "corrected" if corrected and not by_owner else "decided"
    out = [words[head].format(first=first or "there", owner=who),
           "\n".join("- " + x for x in lines + still)]
    reason = " ".join(str(reason or "").split())
    if reason:
        out.append(words["reason"].format(owner=who, reason=reason))
    out += _tails([a for a in asks if was.get(a.ident) != a.status or a.status == WAITING],
                  words, who)
    out.append(words["sign"].format(owner=who))
    return "\n\n".join(x for x in out if x)


def blocked_email(blocked: list[Ask], *, language: str = "en", owner: str = "‹owner›",
                  first: str = "") -> str:
    """What the contact is told when the work of their request stopped at something the gate
    had not decided (D18, 4; D29): the asks it stopped, in their words, each now waiting for
    the owner's permission. "" when none waits."""
    lang = language_of(language)
    words = SAID[lang]
    who = owner_in(lang, owner)
    lines = status_lines([a for a in live(blocked) if a.status == WAITING], language=lang,
                         owner=owner)
    if not lines:
        return ""
    head = words["blocked"].format(first=first or "there", owner=who)
    return "\n\n".join([head, "\n".join(lines), words["tail_waiting"].format(owner=who),
                         words["sign"].format(owner=who)])


def results_email(results: list[dict], *, language: str = "en", owner: str = "‹owner›",
                  first: str = "") -> str:
    """What the work sent back for the contact (D18, 3 and 6): each started ask's result in the
    work's own words, several that finished close together in one message. `results` are
    {"label", "text"}."""
    lang = language_of(language)
    words = SAID[lang]
    who = owner_in(lang, owner)
    got = [r for r in results if str(r.get("text") or "").strip()]
    if not got:
        return ""
    if len(got) == 1:
        body = [str(got[0]["text"]).strip()]
    else:
        body = [words["result"].format(label=" ".join(str(r.get("label") or "").split())
                                       .rstrip(".") or "it") + "\n" + str(r["text"]).strip()
                for r in got]
    return "\n\n".join([words["results"].format(first=first or "there"), *body,
                        words["sign"].format(owner=who)])


# --- what a started ask's work sends back (D18) -----------------------------------------------

#: A "Needs <the owner> (<grant or hard limit>): <what>" line. The brief names the owner by
#: their name (`mail_cases.work_brief`), which this cannot look up, so it takes any name written
#: with capitals, one word or two, or "you" or "the owner" (`_NEEDS_WHO`).
_NEEDS = re.compile(r"^\s*[-*]?\s*Needs\s+(you|the owner|[^\W\d_][\w'’.-]*(?:[ \t][^\W\d_][\w'’.-]*)?)"
                    r"\s*(?:\(([^)]*)\))?\s*:\s*(.+?)\s*$", re.I | re.M)


def _needs_who(said: str) -> bool:
    """Whether the words after "Needs" name the owner: "you", "the owner", or a name, each of
    its words beginning with a capital."""
    said = " ".join(str(said or "").split())
    return said.lower() in ("you", "the owner") or \
        all(w[:1].isupper() for w in said.split()) and bool(said)


def _needs_lines(text: str) -> list:
    return [m for m in _NEEDS.finditer(text) if _needs_who(m.group(1))]
_REPLY_FILE = re.compile(r"^\s*[-*]?\s*Reply file\s*:.*$", re.I | re.M)


def job_result(report: str, name: str) -> tuple[str, list[dict], list[str]]:
    """What a job's report gives the contact and asks of the owner (`mail_cases.work_brief`):
    the words after "For <their first name>:" (or "For them:") to the end, less the lines below;
    each "Needs <the owner's name> (<grant or hard limit>): <what>" line; and each "Reply file: <path>".
    ("", [], []) when it gives none of them. Pure: how the job went is never read here."""
    from . import case_files

    text = str(report or "").replace("\r\n", "\n")
    needs = [{"what": m.group(3).strip()[:600], "need": (m.group(2) or "").strip().lower()}
             for m in _needs_lines(text)]
    paths = case_files.from_report(text)
    first = re.escape(_first(name) if name else "them")
    found = re.search(rf"^\s*\**\s*For (?:{first}|them)\s*\**\s*:\s*", text, re.I | re.M)
    result = ""
    if found:
        result = _NEEDS.sub(lambda m: "" if _needs_who(m.group(1)) else m.group(0),
                            _REPLY_FILE.sub("", text[found.end():])).strip()
        result = re.sub(r"\n{3,}", "\n\n", result)
    return result, needs, paths


# --- one case per request (D7) ---------------------------------------------------------------

#: Where a forwarded message begins, in the forms Gmail, Outlook and Apple write.
_FORWARD = re.compile(r"^\s*-{2,}\s*(?:Forwarded message|Original Message|Препратено писмо)"
                      r"\s*-{2,}\s*$|^\s*Begin forwarded message:\s*$", re.I | re.M)
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _subject_norm(subject: str) -> str:
    text = " ".join(str(subject or "").split()).lower()
    while True:
        cut = re.sub(r"^(?:re|fwd?|aw|wg|отг|пр)\s*:\s*", "", text)
        if cut == text:
            return text
        text = cut


def _words(body: str, most: int = 160) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(body or "").lower()).split())[:most]


def message_key(sender: str, subject: str, body: str) -> str:
    """What makes a message the same request when it comes again: who wrote it, its subject
    without Re: and Fwd:, and its first words. "" when there is too little to tell."""
    import hashlib

    words = _words(body)
    found = _ADDRESS.search(str(sender or "").lower())
    if not found or len(words) < 24:
        return ""
    raw = "|".join([found.group(0), _subject_norm(subject), words])
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def forward_key(body: str) -> str:
    """The `message_key` of the message a body forwards, read from the forward's own header and
    words, or "" when it forwards nothing. A forward of a message already in a case is that case
    again."""
    text = str(body or "")
    m = _FORWARD.search(text)
    if m is None:
        return ""
    rest = text[m.end():]
    head, _, after = rest.lstrip("\n").partition("\n\n")
    found = {}
    for key, words in (("from", "from|от"), ("subject", "subject|тема")):
        got = re.search(rf"^\s*\*?(?:{words})\*?\s*:\s*(.+)$", head, re.I | re.M)
        found[key] = got.group(1).strip() if got else ""
    # The forwarded words end where a forward or a quote inside them begins.
    inner = _FORWARD.split(after, maxsplit=1)[0]
    inner = re.split(r"^\s*On .{3,200} wrote:\s*$", inner, maxsplit=1, flags=re.M)[0]
    return message_key(found["from"], found["subject"], inner)


# --- the rows -------------------------------------------------------------------------------


def _model():
    from .models import MailAsk

    return MailAsk


def _q(user_id: str, org_id: str, case_id: int):
    if not user_id or not org_id:
        raise ValueError("a ledger belongs to a person in an organisation")
    return _model().objects.filter(user_id=str(user_id), org_id=str(org_id), case_id=case_id)


def rows(user_id: str, org_id: str, case_id: int, *, every: bool = False) -> list[Ask]:
    """A case's asks, in their order. Gone ones only with `every`."""
    found = _q(user_id, org_id, case_id).order_by("n", "id")
    if not every:
        found = found.filter(gone=False)
    return [Ask.of(r) for r in found]


def write(user_id: str, org_id: str, case_id: int, asks: list[Ask]) -> None:
    """These asks onto the case, as they are: made, or changed where they differ."""
    from django.db import transaction

    now = time.time()
    with transaction.atomic():
        have = {r.ident: r for r in _q(user_id, org_id, case_id).select_for_update()}
        for a in asks:
            fields = {k: v for k, v in a.as_dict().items()
                      if k not in ("ident", "possible", "missing", "action", "proposal", "via",
                                   "cap_grant")}
            row = have.get(a.ident)
            if row is None:
                _model().objects.create(user_id=str(user_id), org_id=str(org_id),
                                        case_id=case_id, ident=a.ident, created_at=now,
                                        updated_at=now, **fields)
                continue
            changed = [k for k, v in fields.items() if getattr(row, k) != v]
            if changed:
                for k in changed:
                    setattr(row, k, fields[k])
                row.updated_at = now
                row.save(update_fields=[*changed, "updated_at"])


def merge_reading(old: list[Ask], read: list[Ask], *, attempt: int) -> list[Ask]:
    """A new reading laid over the ledger: an ask read again keeps its status where it is done,
    its evidence and the owner's choice; a new one is new; one the new reading does not have is gone
    unless it was done, which stays done. Pure."""
    out: list[Ask] = []
    used: set[str] = set()
    for n, a in enumerate(read, start=1):
        was = next((o for o in old if o.ident not in used and
                    (o.ident == a.ident or same(o.quote, a.quote))), None)
        a = Ask(**{**a.as_dict(), "n": n, "attempt": attempt})
        if was is not None:
            used.add(was.ident)
            a.ident = was.ident
            a.choice, a.choice_grant, a.evidence = was.choice, was.choice_grant, was.evidence
            a.work = was.work
            if was.status in GONE_ON:
                # Started or done stays so: what was started is its work's (D18).
                a.status, a.why = was.status, was.why
        out.append(a)
    for o in old:
        if o.ident in used:
            continue
        if o.source == "whole":
            # A message read before asks were kept, or never read: what the owner chose for it
            # carries to every ask the reading found, except a hard limit, which is theirs alone.
            if o.choice == ONCE:
                for a in out:
                    if not a.choice and not a.hard_limit:
                        a.choice = ONCE
            elif o.choice in (DECLINE, MINE):
                for a in out:
                    a.choice = a.choice or o.choice
            out.append(Ask(**{**o.as_dict(), "gone": True}))
            continue
        out.append(Ask(**{**o.as_dict(), "gone": o.status not in GONE_ON}))
    return out


# --- a settled reading (D34) ----------------------------------------------------------------

#: What a reading says of an ask, which is kept as the case's settled reading and given back to
#: every later reading of the same words.
READING = ("action", "label", "do", "grant", "new_grant", "also", "hard_limit", "task", "task_needs",
           "capability", "scope", "values")


def reading_key(subject: str, body: str, instruction: str = "") -> str:
    """What a reading was of: the message's words and the owner's own words for it. While it is
    the same, an ask already understood is read as it was (`keep_settled`)."""
    import hashlib

    raw = "\n".join(" ".join(str(x or "").split()) for x in (subject, body, instruction))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def settled_of(asks: list[Ask]) -> list[dict]:
    """The reading of each ask the sender wrote, as it is kept: its id, their words and what the
    reading made of it."""
    return [{"ident": a.ident, "quote": a.quote,
             **{k: getattr(a, k) for k in READING}}
            for a in asks if not a.gone and a.source == "reading"]


def _settled_for(a: Ask, settled: list[dict], used: set) -> dict | None:
    return next((one for one in settled or [] if isinstance(one, dict)
                 and str(one.get("ident") or "") not in used
                 and (one.get("ident") == a.ident or same(str(one.get("quote") or ""), a.quote))),
                None)


def keep_settled(read: list[Ask], settled: list[dict]) -> list[Ask]:
    """A new reading of the same words, with every ask already understood read exactly as it
    was: its id, its words, its action and what it needs (Petar, 21 October 2026: the same
    sentence was labelled three ways on three runs). An ask the new reading finds that was not
    there before is taken as read. Pure."""
    import copy

    out, used = [], set()
    for a in read:
        was = _settled_for(a, settled, used)
        if was is None:
            out.append(a)
            continue
        used.add(str(was.get("ident") or ""))
        kept = {k: copy.deepcopy(was[k]) for k in READING if k in was}
        out.append(Ask(**{**a.as_dict(), **kept, "ident": str(was.get("ident") or a.ident),
                          "quote": str(was.get("quote") or a.quote)}))
    return out


def settle(asks: list[Ask], settled: list[dict]) -> list[Ask]:
    """Each ask a run since put a hard limit on that no words of theirs ask for, put back to its
    settled reading (D34): the limit, and what the run's need changed with it, go, and so does an
    "allow once" the owner gave that limit, which was a yes to something never asked. Every other
    ask is as it was. Pure; the same asks, in the same order."""
    from . import case_actions

    out, used = [], set()
    for a in asks:
        was = None if a.gone or a.status in GONE_ON or not a.hard_limit else \
            _settled_for(a, settled, used)
        if was is None or limit_of(was.get("hard_limit")) == a.hard_limit or \
                case_actions.asks_for(a.hard_limit, a.quote):
            out.append(a)
            continue
        used.add(str(was.get("ident") or ""))
        b = Ask(**{**a.as_dict(), **{k: was[k] for k in READING if k in was},
                   "blocker": "", "possible": "", "missing": ""})
        b.hard_limit = limit_of(b.hard_limit)
        b.task_needs = needs_of(b.task_needs)
        if b.choice == ONCE:
            b.choice, b.choice_grant = "", ""
        out.append(b)
    return out


# --- a failure, and trying again (D34) ------------------------------------------------------

#: How many times an ask that the sender's permissions cover, or that the owner approved, is tried
#: before it is said to them as not possible: it is tried again by itself, as ordinary work, and
#: never put to the owner as a decision.
MAX_TRIES = 3


def failed_as(a: Ask, why: str, *, attempt: int) -> Ask:
    """An ask whose work could not be started or done, with why, counted (`tries`). Pure."""
    b = Ask(**{**a.as_dict(), "possible": "", "missing": ""})
    b.status, b.attempt = FAILED, attempt
    b.why = (" ".join(str(why or "").split()) or "It could not be started.")[:600]
    b.evidence = [*a.evidence, {**evidence_line(b.why, attempt=attempt), "failed": True}]
    return b


def tries(a: Ask) -> int:
    """How many times this ask failed."""
    return sum(1 for e in a.evidence or [] if isinstance(e, dict) and e.get("failed"))


def gave_up(a: Ask) -> bool:
    """Failed as often as an ask is tried: it is not tried again by itself."""
    return a.status == FAILED and tries(a) >= MAX_TRIES


def retries(asks: list[Ask]) -> list[Ask]:
    """What is tried again by itself, as ordinary work and never as a decision for the owner: each
    ask that failed, that a run would do now - what they hold covers it, or the owner approved it -
    and that has not failed `MAX_TRIES` times."""
    return [a for a in live(asks) if a.status == FAILED and a.possible and not gave_up(a)
            and a.choice not in (DECLINE, MINE)]


#: A need the work names as a task of the owner's it may not change: "task 90", "task #90".
TASK_NEED = re.compile(r"^\s*task\s*#?\s*(\d{1,5}(?:-\d{1,3})?)\s*$", re.I)


def blocked(a: Ask, what: str, *, need: str = "", attempt: int = 1) -> Ask:
    """The ask whose work stopped at something the gate had not decided, with that need put on
    it (D18, 4; D29): a task of the owner's they may not change ("task 90"), a hard limit
    (`grants.HARD_LIMITS`), a grant key, or with none of these the work's own words, kept as an
    explanation and never as a grant to make (`proposal_from`, D35). It waits for the owner
    as that ask, in the sender's own words, and is judged like every other ask; never a new
    ask (Petar, 16 October 2026: "Asks come only from the sender's own words"). `what` is the
    work's sentence, kept as the ask's `blocker`. Pure; returns a new ask."""
    from . import grants as grant_rows

    b = Ask(**{**a.as_dict(), "possible": "", "missing": ""})
    what = " ".join(str(what or "").split())[:600]
    need = limit_of(str(need or "").strip().lower())
    b.blocker = what or b.blocker
    b.status, b.attempt = WAITING, attempt
    if b.choice == ONCE:
        # Allowed once was for what it needed then; what it needs now is theirs to decide again.
        b.choice = ""
    own = b.grant if b.grant and b.grant not in (NONE, "communicate") else ""
    task = TASK_NEED.match(need)
    if task:
        # Permission to change one of the owner's tasks: the task's, never a grant (D28). Adding to
        # a task they may edit needs no grant, so Shared task is not what it waits for. The task
        # the sender named stays the ask's own: the run's task is added beside it, and never
        # takes its place (21 October 2026, Elena's "128" read back as "131").
        number = task.group(1)
        if not b.task:
            b.task = number
        elif number != b.task:
            b.scope = sorted(set([*b.scope, b.task, number]), key=lambda x: (len(x), x))
        if own == "shared_task":
            b.grant = NONE
    elif need in grant_rows.HARD_LIMITS:
        b.hard_limit = need
    elif need and need != NONE:
        if not own:
            b.grant = need
        elif need != own and need not in b.also:
            b.also = [*b.also, need]
    else:
        # What the work said it needs, in its own words: an explanation for the owner, never a
        # grant to make (CAPABILITIES.md). It waits to be allowed once, or not.
        b.new_grant = proposal_from(what)
        if own and own not in b.also:
            b.also = [*b.also, own]
        b.grant = ""
    return b


def access_done(a: Ask, *, attempt: int, tasks: dict | None = None,
                language: str = "en") -> Ask:
    """An ask for the permission of a task they hold, done by the gate itself (`ACCESS`): the
    permission is in place, so nothing is run and nothing is changed. With `tasks`, what they
    may do now is kept with it in their language (`access_line`), and every message that says it
    done says that too (D34). Pure."""
    b = Ask(**{**a.as_dict(), "possible": "", "missing": ""})
    b.status, b.attempt, b.blocker = DONE, attempt, ""
    said = (a.why or f"They hold the permission of task {a.task}").rstrip(".")
    b.why = f"Done by the gate: {said}."
    line = {"to_them": access_line(a.task, tasks, language)} if tasks else {}
    b.evidence = [*a.evidence, {**evidence_line(said, ids=[f"task {a.task}"], attempt=attempt),
                                **line}]
    return b


#: What a contact is told they may do now, once a permission they asked for is theirs (D34).
ACCESS_SAID = {
    "en": ("You can already change task {tasks} and use Ask AI on its pages.",
           "You can already change tasks {tasks} and use Ask AI on their pages."),
    "bg": ("Вече можеш да променяш задача {tasks} и да ползваш Ask AI на страниците ѝ.",
           "Вече можеш да променяш задачи {tasks} и да ползваш Ask AI на страниците им."),
}
_AND = {"en": "and", "bg": "и"}


def access_reach(task: str, tasks: dict | None) -> list[str]:
    """The task an access ask names and each task that is theirs to edit through it (a quest's
    goals), by number, in order."""
    task = str(task or "").lstrip("#")
    rows = tasks or {}
    got = [task] + [n for n, t in rows.items() if n != task and "-" not in n
                    and str(t.get("from") or "") == task
                    and _LEVEL_RANK.get(t.get("level") or "", 0) >= _LEVEL_RANK["edit"]]
    return sorted(dict.fromkeys(got), key=lambda n: (int(n) if n.isdigit() else 0, n))


def access_line(task: str, tasks: dict | None, language: str = "en") -> str:
    """"You can already change tasks 128, 129, 130 and 131 and use Ask AI on their pages."."""
    lang = language_of(language)
    lang = lang if lang in ACCESS_SAID else "en"
    reach = access_reach(task, tasks)
    listed = reach[0] if len(reach) == 1 else \
        ", ".join(reach[:-1]) + f" {_AND[lang]} " + reach[-1]
    return ACCESS_SAID[lang][len(reach) > 1].format(tasks=listed)


def to_them(a: Ask) -> str:
    """What an ask done by the gate lets them do now, as it was kept for them, or ""."""
    if a.status != DONE:
        return ""
    for e in reversed(a.evidence or []):
        if isinstance(e, dict) and e.get("to_them"):
            return str(e["to_them"])
    return ""


def started_as(a: Ask, got: dict, work: list[dict], *, attempt: int,
               ids: list | None = None) -> Ask:
    """What the start's report makes of one ask it was given (D18): done, started as the work
    it names, or failed with why it could not start. `got` is the report's entry for it
    ({"started", "done", "evidence", "why", "work"}), `work` the handles found for it, `ids`
    those its evidence names.

    Done is done whether or not anything was started now: a run that finds the result there
    already, or what stopped it gone and the work done by an earlier attempt, has nothing left
    to do, and that is done, never failed (Petar, 16 October 2026, D29). Pure."""
    b = Ask(**{**a.as_dict(), "possible": "", "missing": ""})
    b.attempt = attempt
    got = got or {}
    if got.get("done") and not got.get("started"):
        b.status, b.blocker = DONE, ""
        b.work = _work_with(a.work, work)
        b.why = ("Done when it was started." if work else
                 "Done: the start found nothing left to do.")
        said = got.get("evidence") or "; ".join(h.get("title") or "" for h in work) or "done"
        b.evidence = [*a.evidence, evidence_line(said, ids=ids or [], attempt=attempt)]
    elif got.get("started") or work:
        b.status, b.blocker = STARTED, ""
        b.work = _work_with(a.work, work or [{"kind": "note", "ref": "", "at": time.time(),
                                              "title": got.get("work") or "Started"}])
        b.why = "Started. The work has it now, and where it stands is its own."
    else:
        b = failed_as(b, "The start did not say what became of it, so it was not started."
                      if not got else (got.get("why") or "It could not be started."),
                      attempt=attempt)
    return b


def _work_with(was: list, now: list) -> list:
    """The work an ask was started as, earlier and now, each piece once."""
    out, seen = [], set()
    for h in [*(was or []), *(now or [])]:
        if not isinstance(h, dict):
            continue
        key = (h.get("kind"), h.get("ref")) if h.get("ref") else (h.get("kind"), h.get("title"))
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    return out


def need_of(a: Ask) -> str:
    """What an ask raised before 16 October 2026 needed, as `blocked` takes it."""
    if a.task:
        return f"task {a.task}"
    if a.hard_limit:
        return a.hard_limit
    return a.grant if a.grant and a.grant != NONE else ""


def fold(asks: list[Ask], contact, tree, **judging) -> list[Ask]:
    """The asks the work raised before 16 October 2026, each put back onto the ask it served
    (D29): what it needed becomes what that ask waits for, and the raised one is gone, since
    it was never asked. When the ask it served is done or started and what it needed is
    there now, nothing is left of it: it is gone as done. One the ledger cannot tie to an ask
    is left as it was. Pure; the same asks, in the same order."""
    out = list(asks)
    for i, r in enumerate(out):
        if r.gone or r.source != "work" or not r.serves:
            continue
        at = next((j for j, x in enumerate(out) if x.ident == r.serves and not x.gone
                   and x.source != "work"), None)
        if at is None:
            continue
        served = out[at]
        now = judge([r], contact, tree, **judging)[0]
        if served.status in GONE_ON and now.status in (ALLOWED, APPROVED):
            out[i] = Ask(**{**r.as_dict(), "gone": True, "status": DONE, "possible": "",
                            "why": f"Nothing was left to do: \"{_label(served)}\" is "
                                   f"{'done' if served.status == DONE else 'started'}, and "
                                   "what stopped it is there now."})
            continue
        b = blocked(served, r.do or r.label or r.quote, need=need_of(r), attempt=r.attempt)
        if r.choice:
            b.choice, b.choice_grant = r.choice, r.choice_grant or b.choice_grant
        out[at] = b
        out[i] = Ask(**{**r.as_dict(), "gone": True, "possible": "",
                        "why": f"What it needs is on \"{_label(served)}\" now, the ask it "
                               "served."})
    return out


def whole(quote: str, *, label: str = "", status: str = WAITING, why: str = "",
          evidence: list | None = None) -> Ask:
    """The whole message as one ask: one read before asks were kept, or never read at all."""
    return Ask(ident="whole", quote=quote or "(the whole message)", n=1, label=label,
               status=status, why=why, evidence=list(evidence or []), source="whole")


def evidence_line(said: str, ids=(), *, attempt: int = 1) -> dict:
    return {"at": time.time(), "attempt": attempt, "said": " ".join(str(said or "").split())[:1500],
            "ids": [str(i) for i in ids or [] if str(i)][:20]}


__all__ = ["MAX_TRIES", "READING", "failed_as", "gave_up", "keep_settled", "reading_key", "retries",
           "settle", "settled_of", "tries",
           "ACCESS", "access_done", "asks_for_access", "ALLOWED", "APPROVED", "AWAITING", "all_approved", "Ask", "BLOCKED", "CHOICES", "DECLINE", "DECLINED",
           "DONE", "DONE_STAGE", "FAILED", "GONE_ON", "GRANT", "Inbox", "MERGED", "MINE", "NONE",
           "ONCE", "STARTED", "STATUSES", "TONES", "WAITING", "WORDS", "compose", "counts",
           "decided_email", "decision_signature", "evidence_line", "first_email", "forward_key",
           "ident_of", "job_result", "judge", "merge_reading", "message_key", "blocked_email",
           "rejudge", "blocked", "fold", "need_of", "started_as", "results_email",
           "limit_of", "need_named", "needs_owner", "owner_in", "rest_stage", "rows", "said_of", "said_state",
           "same", "status_of",
           "signature", "status_lines", "status_section", "to_do", "waiting", "whole",
           "why_line", "write"]
