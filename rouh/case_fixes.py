"""A false alarm, fixed by a run: what marking a step of a case starts (`MailCaseFix`).

Petar, 8 October 2026, by voice: telling a case's Fix that a step of a mail or
Telegram case was a false alarm should start a run that fixes the check, "like
the feedback feature", so he does not open separate chats or work across parallel
screens for every approval quirk. "Can you display status of the run there
while running and when done display summary of what was done, why and how it
will be different?"

    he tells Fix a step was a false alarm, with his reason
      -> the note is kept, as it always was (`CaseDesk.remark`)
      -> one run of the one program on Rouh's own code (`begin`, preset
         improve_myself), briefed with the case, the step as it ran, the
         diagnosis, his reason and every note on the case
      -> the run says where it is (`case_fix_status`) and what it did
         (`case_fix_done`), through the `rouh` MCP server every run has
         (`rouh/worker_mcp.py`, answered by `act`)
      -> it lands and deploys its commit itself, with `Case-fix: <token>` as
         the last line of the message, which is how Rouh finds it on main and
         in the code it is running (`landed`)
      -> once that commit is live, the case waits for the owner's own Redo, which
         runs it with the fix: nothing runs a case again by itself (`MAIL.md`, D6)
      -> one Telegram line when it lands or fails (`_tell`), and a decision
         with its decision's number when it failed or needs him (`decision_sources`)

**One run per case and step.** A row is `active` while its run goes, and the
database holds at most one active row for a case's step. Marking the step again,
or the same press twice, adds the reason to that row and hands it to the run
(`hooks.say`, and in the answer to its next tool call); it never starts a second.

**Where it shows.** In the case page's Fix (the form, and a line per step) and in its
section Sent back to be fixed (the status, then the summary with Undo), beside what a
check sent back to be fixed in the work; the decision box asks only for the decision.
"we already have fix! That should be merged as concept there" (Petar, the same day).

**Real problems start nothing.** A step marked a real problem is the note it
always was. Every fix proves itself on the replay of real cases
(`python -m rouh.mail_replay`), which land.sh runs too.

**Undo** reverts the fix's commit with a run of its own and redeploys
(`undo`); **Stop** stops whichever of the two runs is going (`stop`).

Every row carries `user_id` and `org_id`, and every query here names both.
"""
from __future__ import annotations

import asyncio
import os
import logging
import re
import time
from typing import Any

from . import owner

log = logging.getLogger("rouh.case_fixes")

#: The Models page pick the runs are started on (`modeldefaults.USES`).
USE = "case_fix_run"
#: The last line of a fix's commit message, and of the commit undoing it.
TRAILER = "Case-fix"
UNDO_TRAILER = "Case-fix-undo"

#: What a fix is doing, in the words the case page shows. The run says the middle five
#: itself; Rouh says the rest.
PHASES = {
    "queued": "Queued",
    "started": "Started",
    "reading": "Reading the step",
    "cause": "Found the cause",
    "fixing": "Fixing it",
    "testing": "Testing on earlier cases",
    "deploying": "Deploying",
    "live": "Waiting for the fix to go live",
    "rerunning": "Live: waiting for your Redo",
}
RUN_PHASES = ("reading", "cause", "fixing", "testing", "deploying")

#: The outcome of a fix only the owner can decide: "needs_petar" until 20 October 2026, which rows
#: kept before then (`MailCaseFix.outcome`, `summary.outcome`) and a run may still say.
NEEDS_OWNER, NEEDS_OWNER_BEFORE = "needs_owner", "needs_petar"


def outcome_of(value) -> str:
    """An outcome as it is now: the old word for NEEDS_OWNER is NEEDS_OWNER."""
    said = str(value or "").strip().lower()
    return NEEDS_OWNER if said == NEEDS_OWNER_BEFORE else said


#: How a fix ended, as the run says it (`case_fix_done`), and as Rouh does.
OUTCOMES = {
    "fixed": "Fixed",
    "nothing": "Nothing to change",
    NEEDS_OWNER: "Needs your decision",
    NEEDS_OWNER_BEFORE: "Needs your decision",
    "failed": "Did not work",
    "stopped": "Stopped",
}
SAID_BY_RUN = ("fixed", "nothing", NEEDS_OWNER, "failed")
#: The outcomes that ask the owner for an answer, kept before the rename or after.
ASKING = ("failed", NEEDS_OWNER, NEEDS_OWNER_BEFORE)

#: The run list's words for a run that has finished: a run of the one program that ended
#: its turn waits at its prompt, "idle", and is finished for a fix.
ENDED = ("idle", "done", "failed", "killed", "lost", "reaped")

#: How long a fix that says it landed may take to be found live before it is called not
#: live, and how long a finished case re-run is retried while the case is busy.
LIVE_WAIT = 3600.0
RERUN_WAIT = 3600.0

#: A reason given twice within this many seconds is one press, not two.
SAME_PRESS = 30.0

MOST_STEP_TEXT = 12000


class Refused(ValueError):
    """What cannot be done, as the sentence to say."""


class Hooks:
    """What the runtime lends this module. None until it sets them."""

    #: async (**starting.start kwargs) -> {"id", ...}
    start = None
    #: async (run id, words) -> str: words typed into a run's prompt.
    say = None
    #: async (run id) -> str: a run stopped.
    stop = None
    #: () -> the case desk (`mail_cases.CaseDesk`), or None where mail is off.
    desk = None


hooks = Hooks()


def _model():
    from .models import MailCaseFix

    return MailCaseFix


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(who.org_id)}


def _who_of(row):
    from .tenancy import Identity

    return Identity(user_id=str(row.user_id), org_id=str(row.org_id))


def token(row) -> str:
    """What names a fix in its commit: its id and the start of its case's key."""
    return f"{row.id}-{re.sub(r'[^A-Za-z0-9]', '', row.case.key)[:6]}"


def trailer_line(row, undo: bool = False) -> str:
    return f"{UNDO_TRAILER if undo else TRAILER}: {token(row)}"


def going(who, case_id: int, step: str):
    """The fix whose run is going for this case's step, or None."""
    return (_model().objects.filter(**_whose(who), case_id=case_id, step=step, active=True)
            .select_related("case").first())


def of_case(who, case_id: int) -> list:
    """Every fix of a case, newest first."""
    return list(_model().objects.filter(**_whose(who), case_id=case_id)
                .select_related("case").order_by("-id"))


def get(who, fix_id) -> Any | None:
    try:
        fix_id = int(fix_id)
    except (TypeError, ValueError):
        return None
    return _model().objects.filter(**_whose(who), id=fix_id).select_related("case").first()


def of_run(run_id: str):
    """The fix a run is the run of, or None. Only an id that could be one is looked up."""
    if not run_id or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", run_id):
        return None
    return _model().objects.filter(run_id=run_id).select_related("case").order_by("-id").first()


def _put(row, **fields) -> None:
    _model().objects.filter(id=row.id, user_id=row.user_id, org_id=row.org_id).update(**fields)
    for k, v in fields.items():
        setattr(row, k, v)


# --- marking a step a false alarm ------------------------------------------------------------


def _take(who, case, step: str, reason: str, note_id: int):
    """(the fix row, made): a new row for this step, or the one going, with the reason on it.

    The database refuses a second active row for a step (`mail_case_fixes_one_going`),
    so two presses at the same moment end here as one row and one reason.
    """
    from django.db import IntegrityError, transaction

    now = time.time()
    said = {"at": now, "text": reason, "note": note_id, "handed": False}
    try:
        with transaction.atomic():
            row = _model().objects.create(**_whose(who), case_id=case.id, step=step,
                                          active=True, state="queued", phase="queued",
                                          phase_said="", phase_at=now, reasons=[said],
                                          created_at=now)
        row = _model().objects.select_related("case").get(id=row.id)
        return row, True
    except IntegrityError:
        pass
    with transaction.atomic():
        row = (_model().objects.select_for_update().filter(
            **_whose(who), case_id=case.id, step=step, active=True).first())
        if row is None:          # it ended in between: make it again
            row = _model().objects.create(**_whose(who), case_id=case.id, step=step,
                                          active=True, state="queued", phase="queued",
                                          phase_at=now, reasons=[said], created_at=now)
            return _model().objects.select_related("case").get(id=row.id), True
        reasons = [r for r in row.reasons or [] if isinstance(r, dict)]
        same = any(" ".join(str(r.get("text") or "").split()) == " ".join(reason.split())
                   and now - float(r.get("at") or 0) < SAME_PRESS for r in reasons)
        if not same:
            reasons.append(said)
            _model().objects.filter(id=row.id).update(reasons=reasons)
            row.reasons = reasons
        row = _model().objects.select_related("case").get(id=row.id)
        row._same_press = same
        return row, False


async def begin(desk, who, case, step: str, reason: str, note_id: int = 0) -> str:
    """A false alarm marked: its run started, or the reason added to the one going.

    Returns the sentence the page shows. Never raises for a run that will not start:
    the row says why, and the owner is told as for any fix that failed.
    """
    step = (step or "").strip()[:80]
    if not step:
        return ""
    row, made = await asyncio.to_thread(_take, who, case, step, reason, note_id)
    if not made:
        if getattr(row, "_same_press", False):
            return f"A run is already fixing the check at {step}; that was the same press twice."
        handed = await _hand_reasons(row)
        return (f"A run is already fixing the check at {step}, so your reason was added to it"
                + (" and passed to it." if handed else "; it reads it at its next step."))
    try:
        brief = await asyncio.to_thread(brief_for, desk, who, row)
        if hooks.start is None:
            raise Refused("Rouh's runs are not ready yet.")
        got = await hooks.start(
            brief=await asyncio.to_thread(owner.say, brief, who), title=f"Fix the check: {case.sender_name or case.sender}, {step}",
            preset="improve_myself", use=USE, org_id=str(who.org_id))
    except Exception as exc:  # noqa: BLE001 - said on the page and to the phone
        log.exception("case %s: the fix run for %s could not be started", case.id, step)
        why = str(exc) or type(exc).__name__
        await asyncio.to_thread(_end, row, "failed", f"The run could not be started: {why}")
        await _tell(desk, row)
        _poke_decisions()
        return f"The run to fix it could not be started: {why}"
    run_id = str(got.get("id") or "")
    now = time.time()
    await asyncio.to_thread(_put, row, run_id=run_id, state="running", phase="started",
                            phase_said="", phase_at=now, started_at=now,
                            reasons=[{**r, "handed": True} for r in row.reasons or []])
    log.info("case %s: run %s is fixing the check at %s (fix %s)", case.id, run_id, step, row.id)
    return ("A run has started to fix the check. It is followed on the case's page, in Sent "
            "back to be fixed.")


async def _hand_reasons(row) -> bool:
    """Reasons the owner added while the run goes, typed into its prompt. True when they went."""
    fresh = [r for r in row.reasons or [] if isinstance(r, dict) and not r.get("handed")]
    if not fresh or not row.run_id or hooks.say is None or row.state != "running":
        return False
    text = ("‹owner› marked the same step a false alarm again while you work, and said: "
            + " / ".join(f"“{r['text']}”" for r in fresh)
            + " Take it into account, and carry on.")
    try:
        await hooks.say(row.run_id, await asyncio.to_thread(owner.say, text, row.user_id))
    except Exception:  # noqa: BLE001 - the next tool call carries it instead
        log.exception("fix %s: the new reason could not be typed into run %s", row.id, row.run_id)
        return False
    await asyncio.to_thread(_mark_handed, row)
    return True


def _mark_handed(row) -> None:
    reasons = [{**r, "handed": True} if isinstance(r, dict) else r for r in row.reasons or []]
    _put(row, reasons=reasons)


# --- the brief ----------------------------------------------------------------------------------


def _command(sub: str, *, here: bool, manage: bool = True) -> str:
    """A manage.py command against the live database: from the deployment, or from the run's
    own checkout so it runs the run's own code. Without `manage`, a command that needs no
    database at all, run in the checkout as it is."""
    if not manage:
        return f".venv-e2e/bin/{sub}" if sub.startswith("python ") else sub
    where = "$PWD" if here else "/var/www/rouh/app"
    return ("sudo -n systemd-run --quiet --wait --pipe --collect "
            f"-p EnvironmentFile=-/var/www/rouh/.env -p WorkingDirectory={where} "
            + (f"-E PYTHONPATH={where} " if here else "")
            + f"/var/www/rouh/.venv/bin/python manage.py {sub}")


def in_containers() -> bool:
    """Whether this Rouh runs in the containers, where a run is in the worker, which cannot reach the
    database (it is off the database network and holds no password), so a manage.py command against the
    live database is no way for it to read anything (deploy/stack/compose.yml)."""
    return bool(os.environ.get("ROUH_GUARD_SOCKET")) or os.environ.get("ROUH_SHELL") == "worker"


#: The most of the whole trace and of the notes put into a brief in the containers.
MOST_INLINE = 60000


def _notes_text(limit: int = 60) -> str:
    """Every false alarm and real problem the owner marked on any case, newest first, as case_notes says them."""
    from datetime import datetime

    from .models import MailCaseNote

    out = []
    for n in MailCaseNote.objects.select_related("case").order_by("-at")[:limit]:
        out.append(f"{datetime.fromtimestamp(n.at).isoformat(timespec='seconds')}  {n.kind} {n.step or '-'} "
                   f"case {n.case.key} ({n.case.sender}, {n.case.stage})\n    {n.text}"
                   + (f"\n    answer: {str(n.answer)[:400]}" if n.answer else ""))
    return "\n".join(out) or "No notes yet."


def _how_to_read(case, trace) -> list[str]:
    """Step 2 of the brief: how the run reads the whole trace and the owner's notes. On a server, the two
    commands against the live database; in the containers, both written out here, because the worker has
    no way to the database (Petar, 5 November 2026: what jobs are told must match the containers)."""
    from . import case_trace

    if not in_containers():
        return ["2. Find why the step stopped the case. The whole trace, every prompt as sent and "
                "every report, the routing rule by rule:",
                f"   `{_command('case_trace ' + case.key, here=False)}`",
                "   Every false alarm and real problem ‹he› has marked, with ‹his› reasons:",
                f"   `{_command('case_notes', here=False)}`"]
    whole = case_trace.trace_for_model(case, trace)
    if len(whole) > MOST_INLINE:
        whole = whole[:MOST_INLINE] + "\n[cut here: the rest of the trace is on the case's page]"
    try:
        notes = _notes_text()
    except Exception as exc:  # noqa: BLE001 - said in the brief rather than failing it
        notes = f"(the notes could not be read: {type(exc).__name__})"
    return ["2. Find why the step stopped the case. This Rouh runs in containers and your worker cannot reach "
            "its database, so `manage.py case_trace` and `case_notes` will not work from your checkout: the "
            "whole trace, every prompt as sent and every report, the routing rule by rule, is here instead:",
            "", "```", whole, "```", "",
            "   Every false alarm and real problem ‹he› has marked on any case, with ‹his› reasons, newest first:",
            "", "```", notes[:MOST_INLINE], "```", ""]


def _cut(text: str) -> str:
    if len(text) <= MOST_STEP_TEXT:
        return text
    return text[:MOST_STEP_TEXT] + "\n[cut here: the whole of it is in case_trace]"


def brief_for(desk, who, row) -> str:
    """What the run is told: the case, the step as it ran, his reasons, every note, and how
    to fix, prove, land and report."""
    from . import case_trace
    from . import mail_cases as mc

    case = desk.store.get(who.user_id, who.org_id, row.case_id)
    contact = desk.contact_of(who, case)
    trace = case_trace.build(case, desk.store, contact_now=contact)
    link = desk.page_link(case.key)
    steps = {s["id"]: s for s in trace["steps"]}
    step = steps.get(row.step)
    d = trace["diagnosis"]
    noun = mc._noun(case)
    kind = "Telegram message" if mc.channel_of(case) == "telegram" else noun
    reasons = [r for r in row.reasons or [] if isinstance(r, dict)]
    notes = trace["notes"]
    lines = [
        "‹owner› marked a step of one of Rouh's cases a false alarm, and you are the run that "
        "fixes the check behind it. Nobody is watching: work it through to the end. Speak to "
        "‹him› in plain words, never with an em dash.",
        "",
        "## The case",
        "",
        f"- {'An' if kind[:1].lower() in 'aeiou' else 'A'} {kind} from {case.sender_name} <{case.sender}>"
        + (f", “{case.subject}”" if case.subject else "") + f". Case key `{case.key}`.",
        f"- Its page: {link}",
        f"- The step ‹he› marked: `{row.step}`"
        + (f", {step['title']}" + (f" ({step['verdict']})" if step.get("verdict") else "")
           if step else "") + f". On the page: {link}#{row.step}",
        f"- Where the case is now: {mc.STAGE_WORDS.get(case.stage, case.stage)}.",
        "- ‹His› reason" + ("s" if len(reasons) > 1 else "") + ": "
        + " / ".join(f"“{r['text']}”" for r in reasons),
        "",
        "## What the page's diagnosis says",
        "",
        f"{d.get('headline', '')} {d.get('plain', '')}".strip() or "(nothing)",
    ]
    if d.get("false_alarm_words"):
        lines.append(f"{d['false_alarm_words']}. " + " ".join(d.get("false_alarm_why") or []))
    for c in [c for c in d.get("causes") or [] if c.get("likely")] or d.get("causes") or []:
        lines.append(f"- {c['kind_words']}: {c['title']}. {c['detail']}"
                     + (f" ({', '.join(c['files'])})" if c.get("files") else ""))
    lines += ["", f"## The step `{row.step}` as it ran", ""]
    if step is not None:
        lines.append(_cut(case_trace.step_text(case, step)))
        # A step that only says the case stopped (it asked the owner, it was blocked) was sent
        # there by the route before it, which is where the check that stopped it is.
        if step["kind"] not in case_trace.MODES and step["kind"] != "route":
            at = trace["steps"].index(step)
            route = next((s for s in reversed(trace["steps"][:at]) if s["kind"] == "route"
                          and not s.get("first_pass")), None)
            if route is not None:
                lines += ["", f"## The route that sent it there, `{route['id']}`", "",
                          _cut(case_trace.step_text(case, route))]
    else:
        lines.append("That step is not in the case's trace any more; read the whole trace.")
    if notes:
        lines += ["", "## Everything ‹owner› has said about this case", ""]
        for n in notes:
            what = {"false_alarm": "false alarm", "real_problem": "real problem",
                    "rerun": "re-ran", "question": "asked",
                    "fix": "a run fixing a check"}.get(n["kind"], n["kind"])
            lines.append(f"- {n['when']}, {what}" + (f" at {n['step']}" if n["step"] else "")
                         + f": {n['text']}" + (f" (answered: {case_trace._first(n['answer'], 400)})"
                                               if n.get("answer") else ""))
    lines += [
        "",
        "## What to do",
        "",
        "1. Say where you are, at every stage, with the `case_fix_status` tool of the `rouh` "
        "MCP server: `reading`, `cause`, `fixing`, `testing` (with `cases`, how many earlier "
        "cases you replay) and `deploying`, each with one plain sentence. ‹owner› watches it on "
        "the case page. Its answer may carry a reason ‹he› added while you work: take it in.",
        *_how_to_read(case, trace),
        "3. Fix the cause in general: a prompt, a rule, a threshold or code in Rouh. Never a "
        "special case for this one email, this sender or these words.",
        "4. Prove it.",
        "   - The replay of real cases and the outbox guard, with your checkout's code, before "
        "you change anything and again after; nothing may change for the worse, and land.sh "
        "refuses work that fails it:",
        f"     `{_command('python -m rouh.mail_replay', here=True, manage=False)}`",
        "     A case that should now come out differently gets its expected outcome changed in "
        "rouh/testing/mail_replay.json, in the same commit, with why in the message.",
        "   - When the fix is in a model's prompt (the reading, the work, the check), the replay "
        "cannot see it: rebuild the step's request (`case_trace <key> --request <id>`, "
        "`llmlog.request_of`), put your new prompt in, and ask the same model again, three "
        "times each with the old prompt and the new, for this case and for each marked case of "
        "the same kind.",
    ]
    lines += [
        "   - What changed on a screen, prove in a browser, as AGENTS.md says.",
        "5. Never loosen a hard limit (rouh/grants.py HARD_LIMITS and LIFTS, rouh/mail_turn.py EFFECTS), the "
        "one outbox (rouh/mail_outbox.py), or taking the text of a message as instructions; and "
        "never make words decide what waits for ‹owner›: what a contact may have done is decided "
        "from the grants they hold (MAIL.md). If the only fix would loosen one of these, change "
        "nothing and commit nothing: call "
        f"`case_fix_done` with outcome `{NEEDS_OWNER}` and put in `needs` the decision ‹owner› has to "
        "make, in one or two sentences.",
        f"6. Commit, with `{trailer_line(row)}` as the last line of the message, alone on it, "
        "and land it yourself with `./land.sh`, which deploys it. Read its last sentence.",
        "7. Call `case_fix_done`, once, at the end: outcome `fixed` (with `cause`, `changed`, "
        "`files`, `different`, `replayed`, `same`, `commit` and `deployed` from land.sh), "
        f"`nothing` when no change was needed, `{NEEDS_OWNER}`, or `failed` with `why`. Write it "
        "for ‹owner›: what was done, why, tied to ‹his› reason, and how this kind of message will "
        "be handled now.",
        "8. Do not press Redo or Approve, and send nothing to anybody: once your commit is "
        "live the case waits for ‹owner›'s own Redo.",
    ]
    return "\n".join(lines)


# --- what the run says --------------------------------------------------------------------------


def _clean(value, most: int) -> str:
    return " ".join(str(value or "").replace("—", "-").split())[:most]


def _fresh_reasons(row) -> list[str]:
    fresh = [r for r in row.reasons or [] if isinstance(r, dict) and not r.get("handed")]
    if fresh:
        _mark_handed(row)
    return [str(r.get("text") or "") for r in fresh]


def _with_reasons(text: str, row) -> str:
    fresh = _fresh_reasons(row)
    if not fresh:
        return text
    return (text + " ‹owner› added, while you work: " + " / ".join(f"“{t}”" for t in fresh)
            + " Take it into account.")


def status(row, args: dict) -> str:
    phase = str(args.get("phase") or "").strip().lower()
    if phase not in RUN_PHASES:
        raise Refused("phase is one of " + ", ".join(RUN_PHASES) + ".")
    said = _clean(args.get("said"), 300)
    try:
        cases = max(0, min(int(args.get("cases") or 0), 100000))
    except (TypeError, ValueError):
        cases = 0
    fields = {"phase": phase, "phase_said": said, "phase_at": time.time()}
    if phase == "testing" and cases:
        fields["replaying"] = cases
    _put(row, **fields)
    return owner.say(_with_reasons(f"Shown on the case page: {PHASES[phase]}"
                                   + (f", {said}" if said else "") + ".", row), row.user_id)


def done(row, args: dict) -> str:
    outcome = outcome_of(args.get("outcome"))
    if outcome not in SAID_BY_RUN:
        raise Refused("outcome is one of " + ", ".join(SAID_BY_RUN) + ".")
    if row.summary:
        raise Refused("This fix has already said how it ended.")
    files = [_clean(f, 200) for f in (args.get("files") or []) if str(f).strip()][:30] \
        if isinstance(args.get("files"), list) else []
    summary = {
        "outcome": outcome,
        "cause": _clean(args.get("cause"), 800),
        "changed": _clean(args.get("changed"), 800),
        "files": files,
        "different": _clean(args.get("different"), 800),
        "replayed": _int(args.get("replayed")),
        "same": _int(args.get("same")),
        "commit": re.sub(r"[^0-9a-f]", "", str(args.get("commit") or "").lower())[:40],
        "deployed_said": bool(args.get("deployed")),
        "needs": _clean(args.get("needs"), 800),
        "why": _clean(args.get("why"), 800),
        "at": time.time(),
    }
    if outcome == "fixed" and not (summary["cause"] and summary["changed"] and summary["different"]):
        raise Refused("A fix says its cause, what it changed and how it will be different.")
    if outcome == NEEDS_OWNER and not summary["needs"]:
        raise Refused(owner.say("needs is the decision ‹owner› has to make, in a sentence or two.",
                                row.user_id))
    if outcome == "failed" and not summary["why"]:
        raise Refused("why is what stopped it, plainly.")
    _put(row, summary=summary, phase="live" if outcome == "fixed" else row.phase,
         phase_at=time.time())
    return owner.say({
        "fixed": "Kept. Once your commit is live Rouh runs the case again itself, and the "
                 "case page shows your summary.",
        "nothing": "Kept: nothing needed changing.",
        NEEDS_OWNER: "Kept: ‹owner› is asked in ‹his› Decisions, with what you said ‹he› must "
                     "decide.",
        "failed": "Kept, and ‹owner› is told it did not work."}[outcome], row.user_id)


def _int(value) -> int:
    try:
        return max(0, min(int(value or 0), 100000))
    except (TypeError, ValueError):
        return 0


async def act(job: str, action: str, args: dict) -> dict:
    """One tool call from a run, answered {"ok", "text"}. Never raises."""
    row = await asyncio.to_thread(of_run, str(job or ""))
    if row is None:
        return {"ok": False, "fix": False,
                "text": "This run is not fixing a case's check, so these tools do nothing for it."}
    if action == "whoami":
        return {"ok": True, "fix": True, "actions": ["status", "done"],
                "text": f"The run fixing case {row.case.key}'s step {row.step}."}
    if action == "status" and (not row.active or row.summary):
        return {"ok": False, "text": "This fix has already said how it ended, so the case page "
                                     "no longer follows its stages."}
    args = args if isinstance(args, dict) else {}
    try:
        if action == "status":
            return {"ok": True, "text": await asyncio.to_thread(status, row, args)}
        if action == "done":
            said = await asyncio.to_thread(done, row, args)
            await settle_one(row.id)
            return {"ok": True, "text": said}
    except Refused as exc:
        return {"ok": False, "text": str(exc)}
    except Exception as exc:  # noqa: BLE001 - said to the run, never raised into Rouh
        log.exception("case fix %s for run %s failed", action, job)
        return {"ok": False, "text": f"That did not work: {type(exc).__name__}."}
    return {"ok": False, "text": f"There is no action {action!r}."}


# --- landed and live ------------------------------------------------------------------------------


def _code_root() -> str:
    from . import version

    return version._ROOT


def landed(row, *, undo: bool = False) -> tuple[str, bool]:
    """(the commit carrying the fix's line, whether it is in the code running now).

    Looked for in the history of the commit this process started from, which is the
    deployed one, and then on main: a commit found only there has landed and is not live.
    """
    from . import version, versions

    root = _code_root()
    want = trailer_line(row, undo=undo)
    for ref, live in ((version.REVISION, True), ("origin/main", False), ("main", False)):
        if not ref:
            continue
        out = versions.git(root, "log", "--format=%H%x1f%B%x1e", "-F", f"--grep={want}", ref,
                           "-n", "20")
        for entry in out.split("\x1e"):
            sha, _, body = entry.strip().partition("\x1f")
            lines = [ln.strip() for ln in body.splitlines()]
            if want in lines and (undo or not any(ln.startswith(UNDO_TRAILER + ":")
                                                  for ln in lines)):
                return sha.strip()[:40], live
    return "", False


def _end(row, outcome: str, why: str = "") -> None:
    """The run is over: the row says how, and the case keeps a note of it in its history."""
    now = time.time()
    was_active = row.active
    fields = {"active": False, "state": "ended", "ended_at": row.ended_at or now}
    if outcome:
        fields["outcome"] = outcome
    if why:
        fields["why"] = why[:800]
    _put(row, **fields)
    if was_active:
        _history(row)


def _history(row) -> None:
    """One note on the case, kept with the owner's own: what the fix's run did, in a line or two."""
    from .mail_cases import CaseStore

    s = row.summary or {}
    said = {
        "fixed": f"Fixed: {s.get('changed') or ''} Why: {s.get('cause') or ''}",
        "nothing": f"Nothing needed changing. {s.get('cause') or ''}",
        NEEDS_OWNER: f"Stopped: only loosening a safety rule would fix it. {s.get('needs') or ''}",
        "failed": f"Did not work: {row.why or s.get('why') or ''}",
        "stopped": "You stopped it.",
    }.get(outcome_of(row.outcome), row.outcome)
    try:
        CaseStore().note(row.user_id, row.org_id, row.case_id, "fix", step=row.step,
                         text=f"Run {row.run_id or '(none)'}. " + " ".join(said.split()),
                         fix=row.id, outcome=row.outcome)
    except Exception:  # noqa: BLE001 - the fix's own row keeps it anyway
        log.exception("fix %s: its note could not be kept on the case", row.id)


def _run_state(run_id: str) -> str:
    from . import runs

    row = runs.get(run_id) if run_id else None
    return runs.status_of(row) if row is not None else ""


def _settle_sync(row) -> list[str]:
    """Brings one fix up to date from its run and from git. Returns what to do next, out of
    the thread: "rerun", "tell", "decide"."""
    todo: list[str] = []
    now = time.time()
    if row.active and row.run_id:
        state = _run_state(row.run_id)
        if state in ENDED:
            said = (row.summary or {}).get("outcome")
            if said:
                _end(row, said, (row.summary or {}).get("why") or "")
            else:
                _end(row, "failed", "The run ended without saying what it did."
                     if state in ("idle", "done") else f"The run ended {state}.")
    if not row.active and row.outcome in ("fixed", "nothing") and (row.summary or {}).get("outcome") \
            and row.outcome != (row.summary or {}).get("outcome"):
        _put(row, outcome=row.summary["outcome"])
    if row.outcome == "fixed" or (row.summary or {}).get("outcome") == "fixed":
        if not row.deployed_at:
            sha, live = landed(row)
            if sha and sha != row.commit:
                _put(row, commit=sha)
            if live:
                _put(row, deployed_at=now, phase="rerunning", phase_at=now)
                todo.append("tell")
            elif not row.active and now - (row.ended_at or now) > LIVE_WAIT:
                _put(row, outcome="failed", phase="", phase_at=now,
                     why=(f"Its commit {sha[:7]} is on main and did not go live within the hour."
                          if sha else "Its commit never reached main, so it did not go live."))
                todo += ["tell", "decide"]
        if row.deployed_at and not row.rerun_at and row.outcome == "fixed":
            todo.append("rerun")
    elif row.outcome in ASKING and not row.told_at:
        todo += ["tell", "decide"]
    if row.undo_state == "running":
        sha, live = landed(row, undo=True)
        if live:
            _put(row, undo_state="done", undo_commit=sha, undo_at=now)
        elif _run_state(row.undo_run_id) in ENDED and now - (row.undo_at or now) > LIVE_WAIT:
            _put(row, undo_state="failed")
        elif _run_state(row.undo_run_id) in ENDED and not row.undo_at:
            _put(row, undo_at=now)    # its run ended: the hour it has to go live starts now
    return todo


def _open_rows() -> list:
    """Every fix that still has something to wait for."""
    from django.db.models import Q

    return list(_model().objects.filter(
        Q(active=True) | Q(outcome="fixed", rerun_at=0) | Q(undo_state="running")
        | Q(outcome__in=ASKING, told_at=0)
        | Q(active=False, outcome="", summary__outcome="fixed"))
        .select_related("case").order_by("id")[:200])


async def settle(desk=None) -> int:
    """Every fix brought up to date: on the case sweep, and on the case page's poll."""
    rows = await asyncio.to_thread(_open_rows)
    for row in rows:
        try:
            await _settle(row, desk)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - one fix never stops the others
            log.exception("case fix %s could not be brought up to date", row.id)
    return len(rows)


async def settle_one(fix_id: int, desk=None) -> None:
    row = await asyncio.to_thread(
        lambda: _model().objects.filter(id=fix_id).select_related("case").first())
    if row is not None:
        await _settle(row, desk)


#: One settling of a fix at a time, so the sweep and a page asking at the same moment never
#: run the case again twice or tell the phone twice.
_settling: dict[int, asyncio.Lock] = {}


async def _settle(row, desk=None) -> None:
    lock = _settling.setdefault(row.id, asyncio.Lock())
    async with lock:
        fresh = await asyncio.to_thread(
            lambda: _model().objects.filter(id=row.id).select_related("case").first())
        if fresh is not None:
            await _settle_now(fresh, desk)


async def _settle_now(row, desk=None) -> None:
    desk = desk or (hooks.desk() if hooks.desk is not None else None)
    todo = await asyncio.to_thread(_settle_sync, row)
    if "rerun" in todo and desk is not None:
        await _rerun(desk, row)
    if "tell" in todo and desk is not None:
        await _tell(desk, row)
    if "decide" in todo:
        _poke_decisions()


async def _rerun(desk, row) -> None:
    """The fix is live: the case is marked ready for the owner's Redo, and nothing more (D6).

    Until 11 October 2026 the case was run again here by itself. Nothing runs a case again
    now but the owner's own press, so this only says where it stands, on the fix and the case.
    """
    who = _who_of(row)
    case = await asyncio.to_thread(desk.store.get, who.user_id, who.org_id, row.case_id)
    now = time.time()
    said = ("not run again by itself: it is gone." if case is None else
            "live; the case waits for your Redo, which runs it with the fix.")
    await asyncio.to_thread(_put, row, rerun_at=now, rerun_said=said, phase="", phase_at=now)
    if case is not None:
        await asyncio.to_thread(desk.store.event, who.user_id, who.org_id, case.id, case.stage,
                                f"The fix of {row.step} (commit {row.commit[:7]}) is live. "
                                "Redo runs the case with it; nothing runs it by itself.")


async def _tell(desk, row) -> None:
    """The one Telegram line, when a fix lands or fails, with the case's link. Once."""
    if row.told_at:
        return
    who = _who_of(row)
    case = row.case
    name = case.sender_name or case.sender
    s = row.summary or {}
    keep = await asyncio.to_thread(_names, who)
    if row.outcome == "fixed" or s.get("outcome") == "fixed":
        line = (f"Fixed the check that stopped {name}'s {_noun(case)} at {row.step}"
                + (f": {_short(s.get('changed'), 140, keep=keep)}" if s.get("changed") else "")
                + ". It is live: Redo runs the case with it.")
    elif outcome_of(row.outcome) == NEEDS_OWNER:
        line = (f"The fix for {name}'s {_noun(case)} at {row.step} needs your decision: "
                f"{_short(s.get('needs'), 160, keep=keep)}")
    else:
        line = (f"The fix for {name}'s {_noun(case)} at {row.step} did not work: "
                f"{_short(row.why or s.get('why'), 160, keep=keep)}")
    said = await desk._telegram(who, f"{line}\n{desk.page_link(case.key)}")
    await asyncio.to_thread(_put, row, told_at=time.time())
    if said:
        log.info("fix %s: the phone was not told (%s)", row.id, said)


def _noun(case) -> str:
    from . import mail_cases as mc

    return mc._noun(case)


def _names(who) -> tuple[str, ...]:
    """The owner's name, as a sentence may begin with it, or nothing."""
    found = owner.resolve(who)
    return (found.name,) if found is not None and found.name else ()


def _short(text, most: int, keep: tuple = ()) -> str:
    """A sentence cut to fit after a colon: its first letter small, unless it is a name: Rouh,
    "I", or one in `keep` (the owner's)."""
    text = " ".join(str(text or "").split()).rstrip(".")
    if text[:2].istitle() and not text.startswith(("Rouh", "I ", *keep)):
        text = text[:1].lower() + text[1:]
    return text if len(text) <= most else text[:most - 1].rsplit(" ", 1)[0] + "…"


def _poke_decisions() -> None:
    try:
        from . import decision_desk

        if decision_desk.LIVE is not None:
            decision_desk.LIVE.poke()
    except Exception:  # noqa: BLE001 - the next sync takes it in anyway
        log.exception("the decisions desk could not be woken")


# --- Stop and Undo --------------------------------------------------------------------------------


async def stop(who, fix_id) -> str:
    """Stop whichever of the fix's runs is going: the fix itself, or its undo."""
    row = await asyncio.to_thread(get, who, fix_id)
    if row is None:
        raise LookupError("There is no such fix.")
    if row.undo_state == "running" and row.undo_run_id:
        run_id, undoing = row.undo_run_id, True
    elif row.active and row.run_id:
        run_id, undoing = row.run_id, False
    elif row.active:
        await asyncio.to_thread(_end, row, "stopped", "You stopped it before its run started.")
        return "Stopped."
    else:
        raise Refused("Nothing of this fix is running.")
    if hooks.stop is not None:
        try:
            await hooks.stop(run_id)
        except Exception as exc:  # noqa: BLE001 - said, and the row is left as it is
            log.exception("fix %s: run %s could not be stopped", row.id, run_id)
            raise Refused(f"The run could not be stopped: {exc}") from exc
    if undoing:
        await asyncio.to_thread(_put, row, undo_state="stopped")
        return f"Stopped the run undoing the fix ({run_id}). The fix is still in place."
    await asyncio.to_thread(_end, row, "stopped", "You stopped it.")
    return f"Stopped run {run_id}. Only that run was stopped."


def undo_brief(row, case) -> str:
    return "\n".join([
        f"‹owner› pressed Undo on the fix of the check at step {row.step} of case `{case.key}` "
        f"({case.sender_name} <{case.sender}>). Revert it and redeploy.",
        "",
        f"1. Revert commit {row.commit} (its message ends `{trailer_line(row)}`): "
        f"`git revert --no-edit {row.commit}`. If it does not revert cleanly, undo by hand "
        "exactly what that commit changed and nothing else.",
        f"2. Run the replay with your checkout's code to see it passes as before the fix: "
        f"`{_command('python -m rouh.mail_replay', here=True, manage=False)}`.",
        f"3. Commit, with `{trailer_line(row, undo=True)}` as the last line of the message, "
        "alone on it, and land it with `./land.sh`, which deploys it. Read its last sentence.",
        "Do not re-run the case, and send nothing to anybody.",
    ])


async def undo(who, fix_id) -> str:
    """Revert the fix's commit and redeploy, by a run of its own. A second press is told."""
    row = await asyncio.to_thread(get, who, fix_id)
    if row is None:
        raise LookupError("There is no such fix.")
    if row.undo_state in ("running", "done"):
        return ("It is already being undone." if row.undo_state == "running"
                else "It was already undone.")
    if not row.commit:
        raise Refused("This fix has no commit on main, so there is nothing to undo.")
    if hooks.start is None:
        raise Refused("Rouh's runs are not ready yet.")
    # Taken before anything is awaited further, so two presses start one run.
    taken = await asyncio.to_thread(
        lambda: _model().objects.filter(id=row.id, user_id=row.user_id, org_id=row.org_id)
        .exclude(undo_state__in=("running", "done")).update(undo_state="running", undo_at=0))
    if not taken:
        return "It is already being undone."
    try:
        got = await hooks.start(brief=await asyncio.to_thread(
                                    owner.say, undo_brief(row, row.case), who),
                                title=f"Undo the check fix: {row.case.sender_name}, {row.step}",
                                preset="improve_myself", use=USE, org_id=str(who.org_id))
    except Exception as exc:  # noqa: BLE001
        log.exception("fix %s: the undo run could not be started", row.id)
        await asyncio.to_thread(_put, row, undo_state="failed")
        raise Refused(f"The run to undo it could not be started: {exc}") from exc
    await asyncio.to_thread(_put, row, undo_run_id=str(got.get("id") or ""))
    return "Undoing it: a run is reverting the commit and redeploying."


# --- The owner's answer, from Decisions -------------------------------------------------------------


def waiting(who) -> list:
    """Every fix that failed or needs him and has no answer yet, newest first."""
    return list(_model().objects.filter(**_whose(who), active=False, verdict="",
                                        outcome__in=ASKING)
                .select_related("case").order_by("-id"))


async def answer(desk, who, row, choice: str, words: str) -> str:
    """His answer to a fix that failed or needs him: try again (with his words), or leave it."""
    await asyncio.to_thread(_put, row, verdict=choice, words=(words or "")[:4000])
    if choice == "leave":
        return f"Left as it is: the check at {row.step} keeps stopping messages like this one."
    case = await asyncio.to_thread(desk.store.get, who.user_id, who.org_id, row.case_id)
    name = await asyncio.to_thread(lambda: (_names(who) or ("The owner",))[0])
    reason = (f"{name}'s decision on the earlier fix: {words}" if words else
              f"{name} asked for another try after the earlier fix ended: "
              f"{OUTCOMES.get(row.outcome, row.outcome).lower()}"
              + (f" ({row.why or (row.summary or {}).get('needs') or ''})"))
    note = await asyncio.to_thread(desk.store.note, who.user_id, who.org_id, case.id,
                                   "false_alarm", step=row.step, text=reason, stage=case.stage)
    return await begin(desk, who, case, row.step, reason, note)


# --- the case page ----------------------------------------------------------------------------------


def _clock(ts: float) -> str:
    from . import case_trace

    return case_trace._clock(ts) if ts else ""


def outcome_said(row) -> str:
    return str((row.summary or {}).get("outcome") or "")


def live(row) -> bool:
    """Whether the page should keep asking about this fix."""
    return bool(row.active or row.undo_state == "running"
                or (row.outcome == "fixed" and not row.rerun_at)
                or (not row.active and not row.outcome and (row.summary or {}).get("outcome")))


#: The stages a fix goes through, in order, as the case page draws them.
TRACK = ("started", "reading", "cause", "fixing", "testing", "deploying", "rerunning")


def track(row, outcome: str) -> list[dict]:
    """Each stage of the fix, with whether it is done, going now, or still to come."""
    if row.active and outcome_said(row) != "fixed":
        now = row.phase if row.phase in TRACK else ""
    elif (outcome or outcome_said(row)) == "fixed" and not row.deployed_at:
        now = "deploying"
    elif outcome == "fixed" and not row.rerun_at:
        now = "rerunning"
    elif outcome == "fixed":
        now = "done"
    else:
        now = "stopped"
    at = TRACK.index(now) if now in TRACK else (len(TRACK) if now == "done" else -1)
    if now == "stopped":
        reached = TRACK.index(row.phase) if row.phase in TRACK else 0
        return [{"label": PHASES[k], "state": "done" if i < reached else
                 "stop" if i == reached else "todo"} for i, k in enumerate(TRACK)]
    return [{"label": PHASES[k], "state": "done" if i < at else "now" if i == at else "todo"}
            for i, k in enumerate(TRACK)]


def view(row, case, number: int | None = None) -> dict:
    """One fix as the case page draws it, in its panel and at its step."""
    from . import mail_cases as mc

    s = row.summary or {}
    outcome = outcome_of(row.outcome or ("" if row.active else s.get("outcome", "")))
    if row.active and outcome_said(row) == "fixed":
        doing, tone = PHASES["live"], "run"
    elif row.active:
        doing = PHASES.get(row.phase, "Started")
        tone = "run"
    elif outcome == "fixed" and not row.deployed_at:
        doing, tone = PHASES["live"], "run"
    elif outcome == "fixed" and not row.rerun_at:
        doing, tone = PHASES["rerunning"], "run"
    else:
        doing, tone = OUTCOMES.get(outcome, "Ended"), {"fixed": "good", "nothing": "good",
                                                       "stopped": ""}.get(outcome, "bad")
    rerun = ""
    following = False
    if row.rerun_attempt and case is not None and case.attempt_no >= row.rerun_attempt:
        now = mc.STAGE_WORDS.get(case.stage, case.stage)
        now = now if now.startswith("Rouh") else now[:1].lower() + now[1:]
        rerun = (f"run again as attempt {row.rerun_attempt}, "
                 + (f"now {now}" if case.attempt_no == row.rerun_attempt else
                    f"and attempt {case.attempt_no} came after it") + ".")
        # The page goes on following the re-run until it rests: done, blocked or waiting.
        following = (case.attempt_no == row.rerun_attempt and case.stage not in mc.CLOSED
                     and case.stage != mc.AWAITING and time.time() - row.rerun_at < RERUN_WAIT)
    elif row.rerun_said:
        rerun = row.rerun_said
    reasons = [r for r in row.reasons or [] if isinstance(r, dict)]
    return {
        "id": row.id, "step": row.step, "active": row.active, "live": live(row) or following,
        "track": track(row, outcome),
        "state": row.state, "outcome": outcome, "doing": doing, "tone": tone,
        "said": row.phase_said if row.active and row.phase in RUN_PHASES else "",
        "pill": (("Queued" if row.state == "queued" else "Running") if row.active else
                 "Undone" if row.undo_state == "done" else
                 "Going live" if doing == PHASES["live"] else
                 "Live" if doing == PHASES["rerunning"] else doing),
        "claimed": s.get("commit", "")[:7],
        "replaying": row.replaying,
        "since": _clock(row.started_at or row.created_at),
        "phase_when": _clock(row.phase_at),
        "ended": _clock(row.ended_at), "ended_at": row.ended_at,
        "run_id": row.run_id, "run_href": f"/run/{row.run_id}" if row.run_id else "",
        "reasons": [{"text": r.get("text") or "", "when": _clock(float(r.get("at") or 0))}
                    for r in reasons],
        "cause": s.get("cause") or "", "changed": s.get("changed") or "",
        "files": s.get("files") or [], "different": s.get("different") or "",
        "replayed": s.get("replayed") or 0, "same": s.get("same") or 0,
        "needs": s.get("needs") or "",
        "why": row.why or s.get("why") or "",
        "commit": (row.commit or s.get("commit") or "")[:7],
        "deployed": bool(row.deployed_at), "deployed_when": _clock(row.deployed_at),
        "rerun": rerun,
        "undo_state": row.undo_state, "undo_commit": row.undo_commit[:7],
        "undo_run_href": f"/run/{row.undo_run_id}" if row.undo_run_id else "",
        "undo_when": _clock(row.undo_at) if row.undo_state == "done" else "",
        "can_stop": bool((row.active and row.state in ("queued", "running"))
                         or row.undo_state == "running"),
        "can_undo": bool(row.commit and outcome == "fixed" and row.deployed_at
                         and row.undo_state not in ("running", "done")),
        "decision_number": number, "verdict": row.verdict,
    }


def views_for(who, case) -> list[dict]:
    """Every fix of a case, as the page draws them, with the numbers of their decisions."""
    rows = of_case(who, case.id)
    numbers: dict[str, int] = {}
    asking = [str(r.id) for r in rows if r.outcome in ASKING and not r.verdict]
    if asking:
        try:
            from . import decisions

            numbers = decisions.numbers_of_sources(who, "casefix", asking, take_in=False)
        except Exception:  # noqa: BLE001 - a number missing is only not shown
            log.exception("the decision numbers of case %s's fixes could not be read", case.id)
    return [view(r, case, numbers.get(str(r.id))) for r in rows]
