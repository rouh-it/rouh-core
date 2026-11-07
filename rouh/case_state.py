"""Where a case is, said once: its stage, its words, its line, whether anything of it is really
working, and what the owner does next. All of it from the case's ledger and the live state of what
it started, and never from text an earlier step left behind.

Petar, 11 October 2026, on a contact's itinerary (case 42, decision a738): "It says
running but it is not running. It says waiting for me, but there is no obvious action. There is
a problem on the clockwork, but it says granted. Fix those inconsistencies so I don't incur
them next time." The case page said "Waiting for you" beside a stored route of "granted", a
diagnosis from attempt 1 said she did not hold grants she had held for hours, ask 6 showed
Failed beside the very grant that now covered it, and the one button that moved the case was
on another page. Each came from a different stored piece of text. So (MAIL.md, D14 to D17):

- **One state (D14).** `of` is the one function the case page, the link Rouh reads, the list of
  cases and the replay all call: it takes the asks judged now (`mail_ledger.rejudge`), the stage
  the case is at, what is live this instant (`Live`) and its open decision, and gives back the
  stage, its words, the D12 line, whether it waits for the owner, and their next action. The stage of
  a case at rest is `mail_ledger.rest_stage` of the asks as they are judged now.
- **Waiting names its action (D16).** A case that waits for the owner has an action: its open
  decision's main option, or their Redo when there is no decision. `unactionable` is the check
  that fails when one has none, run by `python -m rouh.mail_replay` and `manage.py
  waiting_check`.
- **Running is true (D17).** A case is working only while a turn of it is going in this process,
  or its steps are being carried out now (`Live`). A case whose step was cut short says so.
- **The gate, not the work (D18).** A case whose asks were started rests: the work they were
  started as is never the case's running, waiting or failing. Its page shows each one's own
  status, read from the work (`mail_cases.CaseDesk.work_view`).

Pure and standard library only, so `rouh/mail_replay.py` runs the very same code.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import mail_ledger as ledger

# --- stages ----------------------------------------------------------------------------------

#: What Rouh is doing with a case: the steps of one run.
NEW, ASSESSING, WORKING, WAITING_JOB, VERIFYING, REPLYING, NOTIFYING = (
    "new", "assessing", "working", "waiting_on_job", "verifying", "replying", "notifying")
#: Corrections the check named, handed to a job (`CaseDesk._hand_off`).
FOLLOW_UP = "following_up"
#: Where a case rests, from its ledger (`mail_ledger.rest_stage`): something waits for the owner,
#: everything is done, or every ask was declined by them; or it was attached to another case.
AWAITING, DONE, BLOCKED, MERGED = ledger.AWAITING, ledger.DONE_STAGE, ledger.BLOCKED, ledger.MERGED
#: Read as junk and closed (`CaseDesk._junk`): moved to Gmail's Spam, or left where it was.
JUNK_SPAM, JUNK_KEPT = "junk_spam", "junk_not_moved"
JUNKED = (JUNK_SPAM, JUNK_KEPT)

#: The steps of a run: the sweep carries these on, and only these.
IN_FLIGHT = (NEW, ASSESSING, WORKING, WAITING_JOB, FOLLOW_UP, VERIFYING, REPLYING, NOTIFYING)
#: Where nothing is done unless the owner does it (D6).
CLOSED = (AWAITING, DONE, BLOCKED, MERGED, *JUNKED)
RESTING = CLOSED
#: Where a case rests on its ledger alone, so its stage is the ledger's, judged now.
LEDGER_RESTS = (AWAITING, DONE, BLOCKED)
#: The steps that wait on a job rather than on a turn of Rouh's own.
JOB_STEPS = (WAITING_JOB, FOLLOW_UP)

#: What each stage is called on the page.
STAGE_WORDS = {
    NEW: "Received", ASSESSING: "Rouh is reading it", WORKING: "Rouh is starting the work",
    WAITING_JOB: "Waiting for a job to finish", FOLLOW_UP: "Being fixed",
    VERIFYING: "Rouh is checking the work", REPLYING: "Telling them",
    NOTIFYING: "Finishing", AWAITING: "Waiting for you", DONE: "Done",
    BLOCKED: "Declined by you", MERGED: "Part of another case",
    JUNK_SPAM: "Junk - moved to Gmail spam", JUNK_KEPT: "Junk - not moved",
}

#: What a step that was cut short is called: nothing is doing it this instant.
CUT_SHORT = "Cut short"
#: A case at rest whose asks were started: the gate is done, and the work has them (D18).
STARTED_WORDS = "Started"

# --- what is live ----------------------------------------------------------------------------

#: The run register's words (`runs.status_of`) for a job that is working this instant.
JOB_WORKING = ("starting", "running", "saving")
#: ... at its prompt, its turn finished, still open.
JOB_IDLE = ("idle",)
#: ... stopped to ask somebody something.
JOB_ASKING = ("waiting",)


def job_said(status: str | None) -> str:
    """A job's state as the case page says it, from the run register now (D17)."""
    status = str(status or "").strip().lower()
    if status == "saving":
        return "saving its work: at its prompt while its work is landed"
    if status in JOB_WORKING:
        return "running"
    if status in JOB_IDLE:
        return "idle, waiting at its prompt"
    if status in JOB_ASKING:
        return "stopped to ask a question"
    if not status:
        return "not in the run register"
    return "ended"


@dataclass
class Live:
    """What is really going on with one case this instant, read from the processes themselves:
    a turn of it going in this process, its steps being carried out now, and each job it
    started with its run register word (`runs.status_of`)."""

    turn: bool = False
    stepping: bool = False
    jobs: dict = field(default_factory=dict)

    @property
    def running_jobs(self) -> list[str]:
        return [j for j, s in self.jobs.items() if str(s or "") in JOB_WORKING]

    @property
    def working(self) -> bool:
        return bool(self.turn or self.stepping or self.running_jobs)


# --- the decision: what it lists and what it offers -----------------------------------------


def decision_items(asks: list[ledger.Ask], *, listed: bool, identity_ok: bool = True,
                   tree=None, name: str = "") -> list[dict]:
    """What a case's one decision lists (D8): every ask only the owner moves, judged now, with
    what it needs and what they can choose for it. A failed ask that a run would do now is
    listed as ready to run: there is nothing to choose for it."""
    from . import grants

    out = []
    for a in ledger.needs_owner(asks):
        if a.status == ledger.FAILED and a.possible:
            # Covered by what they hold, or approved by the owner, and failed: tried again by
            # itself as ordinary work, and said to them once it cannot be done - never the
            # owner's decision (MAIL.md D34).
            continue
        if a.status == ledger.WAITING and a.capability == ledger.UNSUPPORTED:
            # Nothing Rouh has does it: the owner sees to it, or declines it (CAPABILITIES.md).
            options = [ledger.DECLINE, ledger.MINE]
        elif a.status == ledger.WAITING:
            # A hard limit a grant can lift takes that grant, given for good (`grants.LIFTS`).
            # One case's sentence is no grant to give (fr_aa3ca23c06f7): here it is once, or not.
            # A grant Rouh's code proposes as data is given as it is shown (D35); one that
            # cannot be complete without the owner's own pick - which calendars - is given on
            # the case's page.
            options = ([ledger.GRANT] if listed and identity_ok and (
                not a.hard_limit or grants.liftable(a.hard_limit)) and not (
                not a.grant and not a.task and ledger.one_off(a.new_grant)) and not (
                a.proposal and _incomplete(a.proposal)) and a.task_needs != ledger.DECIDE and not (
                a.hard_limit and grants.liftable(a.hard_limit) and not a.proposal
                and not a.grant)
                       else []) + [ledger.ONCE, ledger.DECLINE, ledger.MINE]
        elif a.status == ledger.FAILED and not a.possible:
            options = [ledger.ONCE, ledger.DECLINE, ledger.MINE]
        else:
            # Allowed, approved, or failed and possible now: their run does it, or they say no.
            options = [ledger.DECLINE, ledger.MINE]
        out.append({"id": a.ident, "ask": a.quote, "label": a.label, "n": a.n,
                    "status": a.status, "why": a.why, "possible": a.possible,
                    "need": ledger.need_named(a, tree, "") if a.status == ledger.WAITING
                    else "A run does it: " + a.possible if a.possible
                    else "Not run yet" if a.status == ledger.ALLOWED
                    else ledger.WORDS[a.status],
                    "grant": a.grant if a.grant != ledger.NONE else "",
                    "grant_name": tree.name(a.grant) if tree is not None and a.grant
                    and a.grant != ledger.NONE else "",
                    "hard_limit": a.hard_limit, "new_grant": a.new_grant,
                    # Letting them edit the task is offered only while that is what it lacks:
                    # never for a task they may edit already (D29).
                    "task": a.task if a.status == ledger.WAITING and (
                        a.missing == "task" or not a.hard_limit and (
                            not a.grant or a.grant == ledger.NONE)) else "",
                    "options": options, "who": name,
                    **_proposed(a, name)})
    return out


def _incomplete(proposal: dict) -> bool:
    """Whether a proposed grant needs the owner's own pick before it is one: what it reaches."""
    from . import capabilities

    cap = capabilities.catalogue().caps.get(proposal.get("capability") or "")
    return cap is None or bool(capabilities.validate(proposal, cap))


def _proposed(a: ledger.Ask, name: str) -> dict:
    """A proposed grant as a decision lists it: its fields, the sentence made from them and the
    digest the owner's Give is bound to."""
    from . import capabilities

    if not a.proposal:
        return {}
    cap = capabilities.catalogue().caps.get(a.proposal.get("capability") or "")
    if cap is None:
        return {}
    first = (str(name or "").split() or ["them"])[0]
    return {"proposal": {**a.proposal, "wording": capabilities.wording(a.proposal, cap, first),
                         "name": cap.name},
            "digest": capabilities.digest(a.proposal),
            "capability": cap.id}


def goes_as_it_is(a: ledger.Ask) -> bool:
    """Whether an ask only the owner moves has nothing for them to choose now (D29): the contact
    holds what it needs - allowed, or given it for good by them - or it failed and a run does
    it now. One they allowed once, declined or see to themselves is their choice, never this."""
    if a.access and a.status in (ledger.ALLOWED, ledger.APPROVED):
        # The permission of a task they hold, which the gate does itself: whatever was chosen
        # for it before, there is nothing left to choose (MAIL.md D33).
        return True
    if a.choice in (ledger.DECLINE, ledger.MINE):
        return False
    if a.status == ledger.FAILED:
        # Covered, or approved by the owner (once included), and failed: tried again by itself
        # until it has failed `ledger.MAX_TRIES` times (D34).
        return bool(a.possible) and not ledger.gave_up(a)
    if a.choice == ledger.ONCE:
        return False
    return a.status in (ledger.ALLOWED, ledger.APPROVED)


def runs_itself(asks: list[ledger.Ask], attempt: int = 0) -> bool:
    """Whether a resting case has no decision to put to the owner and runs as it is (Petar, 16
    October 2026, D29: "If every ask is already allowed and the test says it goes, there is no
    decision to ask: run it"): every ask only the owner moves goes as it is. A covered ask that
    failed goes as it is too, until it has failed `ledger.MAX_TRIES` times (D34). `attempt` is
    kept for callers from before 21 October 2026."""
    # What failed as often as it is tried was told to them and holds nothing back (D34).
    mine = [a for a in ledger.needs_owner(asks) if not (ledger.gave_up(a) and a.possible)]
    return bool(mine) and all(goes_as_it_is(a) for a in mine)


def tries_again(asks: list[ledger.Ask]) -> bool:
    """Whether a resting case runs again by itself for what failed and is covered, whatever else
    in it waits for the owner (Petar, 21 October 2026, D34): that failure is ordinary work to try
    again, and never his decision. What waits keeps its decision meanwhile."""
    return bool(ledger.retries(asks))


def choosing(items: list[dict]) -> bool:
    """Whether the decision asks the owner to choose: something waits for their decision, or
    failed and would still not go. Otherwise it only asks them to run it. A decision's items
    kept before 20 October 2026 may say WAITING by its old word (`ledger.status_of`)."""
    return any(ledger.status_of(i.get("status")) == ledger.WAITING or
               (i.get("status") == ledger.FAILED and not i.get("possible")) for i in items)


def decision_options(items: list[dict], *, link: str = "") -> list[dict]:
    """The options of a case's one decision, main one first (D8, D16)."""
    open_case = {"id": "open", "label": "Open the case",
                 "detail": "Every ask, what it needs, and how to set a grant up.", "href": link}
    if choosing(items):
        return [
            {"id": "grant", "label": "Approve and run",
             "detail": "Gives what each needs, for good where it can, and starts it now.",
             "each": "Give permanently"},
            {"id": "once", "label": "Allow once and run",
             "detail": "Lets each go this once, grants nothing, and starts it now.",
             "each": "Allow once"},
            {"id": "decline", "label": "Decline", "detail": "Rouh does not do them.",
             "each": "Decline"},
            {"id": "mine", "label": "I'll see to it",
             "detail": "Rouh does not do them: you see to them.", "each": "I'll see to it"},
            open_case]
    return [{"id": "run", "label": "Run it now",
             "detail": "Starts what is allowed and approved, and tells them it has started."},
            open_case]


def main_option(options) -> dict | None:
    """A decision's main option: the first that answers it, never a link."""
    for one in options or []:
        if isinstance(one, dict) and one.get("id") and not one.get("href"):
            return one
    return None


# --- the state -------------------------------------------------------------------------------


@dataclass
class State:
    """Where a case is, as every place that shows it says it."""

    stage: str
    words: str
    tone: str
    line: str
    working: bool = False
    waiting: bool = False
    #: The owner's next action: {"kind": "decision"|"redo", "id", "label", "detail", "decision",
    #: "handle"}, or None when nothing waits for them.
    action: dict | None = None
    #: What it waits on, and who has it, when it is not the owner.
    waits_on: str = ""
    asks: list = field(default_factory=list)

    @property
    def possible(self) -> list:
        return [a for a in ledger.live(self.asks) if a.possible]


def of(stage: str, asks: list[ledger.Ask], *, live: Live | None = None,
       decision: dict | None = None, redo_refusal: str = "", tree=None,
       contact_name: str = "", outcome: str = "") -> State:
    """The one state of a case (D14). `asks` are its asks judged now (`ledger.rejudge`),
    `decision` its open decision as `decisions.as_dict` gives it (id, handle, status, options),
    `redo_refusal` why Redo is shut now, "" when it is open."""
    live = live or Live()
    if stage in JUNKED:
        return State(stage, STAGE_WORDS[stage], "good" if stage == JUNK_SPAM else "warn",
                     ledger.why_line(asks, stage=stage), asks=asks)
    if stage == MERGED:
        return State(stage, STAGE_WORDS[stage], "good",
                     outcome or ledger.why_line(asks, stage=stage), asks=asks)
    if stage in IN_FLIGHT:
        words = STAGE_WORDS.get(stage, stage)
        jobs = live.jobs
        if live.working:
            line = ledger.why_line(asks, stage=stage, step_words=words, tree=tree,
                                   contact_name=contact_name)
            running = live.running_jobs
            on = (f"job {running[0]}, which is {job_said(jobs[running[0]])}"
                  if stage in JOB_STEPS and running else "Rouh")
            return State(stage, words, "busy", line, working=True, waits_on=on, asks=asks)
        # The stage says a step, and nothing is doing it: say what is true.
        idle = [j for j, s in jobs.items() if str(s or "") in JOB_IDLE]
        if stage in JOB_STEPS and idle:
            said = (f"Job {idle[0]} finished its turn and is idle, waiting at its prompt; Rouh "
                    "takes what it reported and carries the case on within a minute.")
        else:
            said = (f"\"{words}\" was cut short: nothing is doing it now. Rouh carries it on by "
                    "itself within a minute, or fails it so your Redo can run it.")
        return State(stage, CUT_SHORT, "warn", said, waits_on="Rouh's sweep", asks=asks)
    rest = ledger.rest_stage(asks) if stage in LEDGER_RESTS else stage
    line = ledger.why_line(asks, tree=tree, contact_name=contact_name)
    if rest != AWAITING:
        words = STAGE_WORDS.get(rest, rest)
        if rest == DONE and any(a.status == ledger.STARTED for a in ledger.live(asks)):
            words = STARTED_WORDS
        return State(rest, words,
                     "good" if rest == DONE else "bad" if rest == BLOCKED else "", line,
                     asks=asks)
    open_ = decision is not None and decision.get("status") in ("open", "snoozed")
    main = main_option((decision or {}).get("options")) if open_ else None
    if main is not None:
        action = {"kind": "decision", "id": main["id"], "label": main["label"],
                  "detail": main.get("detail") or "", "decision": decision.get("id"),
                  "number": decision.get("number")}
    elif decision is not None and decision.get("status") in ("answered", "applying"):
        # Answered a moment ago: it goes in a few seconds, and nothing is the owner's meanwhile.
        return State(rest, "Your answer is going", "busy", line,
                     waits_on="your answer, which goes in a few seconds",
                     asks=asks)
    elif not redo_refusal:
        action = {"kind": "redo", "id": "redo", "label": "Redo",
                  "detail": "Runs it now with the grants and your choices as they are.",
                  "decision": None, "number": None}
    else:
        return State(rest, "Not running", "warn", line + " " + redo_refusal,
                     waits_on=redo_refusal, asks=asks)
    return State(rest, STAGE_WORDS[AWAITING], "warn", line, waiting=True, action=action,
                 asks=asks)


def unactionable(state: State) -> str:
    """Why a case that says it waits for the owner has nothing for them to press, or "" (D16)."""
    if state.waiting and not (state.action and state.action.get("label")):
        return f"it says \"{state.words}\" and offers no action"
    if state.words == STAGE_WORDS[AWAITING] and not state.waiting:
        return "it says it waits for you, and is not waiting"
    if not state.waiting and state.stage == AWAITING and not state.waits_on and \
            not state.working:
        return "it rests waiting, and says neither an action nor what it waits on"
    return ""


def decision_unactionable(options) -> str:
    """Why an open decision has nothing to press that answers it, or "" (D16)."""
    if main_option(options) is None:
        return "it has no option that answers it, only links or nothing"
    return ""


__all__ = ["AWAITING", "BLOCKED", "CLOSED", "CUT_SHORT", "DONE", "IN_FLIGHT", "JUNKED", "Live",
           "MERGED", "RESTING", "STAGE_WORDS", "STARTED_WORDS", "State", "choosing",
           "decision_items", "decision_options", "decision_unactionable", "goes_as_it_is",
           "job_said", "main_option", "of", "runs_itself", "tries_again", "unactionable"]
