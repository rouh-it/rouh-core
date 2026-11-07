"""An email case, step by step, for debugging and tuning the pipeline that carried it.

Petar, 1 October 2026, about the case page: "I want to understand each check
that is executed, what was passed to it, what was decided, and why ... I want
to be able to read original prompts ... Most of the time it is not about
making a decision, it is about debugging the workflow and improving it. Most
will be false alarms, and fine tuning is the goal. So how do we understand
what went wrong, how do we fix it, and what do I tell another run to do."

So this module puts together, for one case (`rouh/mail_cases.py`):

- **Steps.** What happened, in order: the email received, every turn of the
  model (read, do the work, check the work) with what went in and what came
  out, the code's routing of each reading rule by rule, every approval, the
  reply, the note to the owner, the re-reads and the block. Each turn is matched
  to its model requests in `llm_requests` (the case has a chat of its own, and
  every request a turn makes carries that chat and the turn's id), so the
  prompts as sent - system prompt, brief, tools - are one press away, and
  every tool the model called is listed with what came back.
- **Where it is from.** Since 1 October 2026 each turn's brief, tools and
  levels, its report and the routing are kept as they happen
  (`MailCaseTrace`). Older cases have no such rows: their turns are read back
  from the request log and their reports from the model's own `case_report`
  calls in it, which is the same thing, said so on the page.
- **A diagnosis.** Which step stopped the case, in plain words, whether it
  looks like a false alarm and why, the likely causes - a prompt too strict, a
  tool or permission missing for the level, a code bug, a data problem - with
  the files and functions behind each (`diagnose`). Since 8 October 2026 a
  false alarm told to Fix starts the run that makes the change itself
  (`rouh/case_fixes.py`).
- **The owner's notes.** False alarms and real problems with their reasons, re-runs
  and their notes, questions and answers (`MailCaseNote`), kept for tuning and
  read by `manage.py case_notes`.

Every query names the case's person and organisation (`AGENTS.md`, "Whose data
is it"); a request row is only ever read under the case's own chat.
"""
from __future__ import annotations

import json
import logging
import re
import time

from . import case_files, grants, mail_attachments, mail_turn
from . import mail_cases as mc
from . import trusted as trust
from . import case_history as old

log = logging.getLogger("rouh.case_trace")

#: What each mode of a turn is called on the page, and what it is for.
MODES = {
    "assess": ("Read", "Rouh reads the message, splits it into its asks, maps each to a grant, "
                       "a proposed grant or a hard limit, and writes the friendly words of the "
                       "answer. It may only read and look things up, and decides nothing."),
    "carry_out": ("Start the work", "Rouh starts each ask that is allowed or that you approved "
                                    "as ordinary work - a job, a Clockwork item, a task, a note "
                                    "kept - with only the tools of their grants, and says what "
                                    "each was started as. It never sends anything, and nothing "
                                    "after it is the case's (since 12 October 2026, MAIL.md "
                                    "D18; before that, Do the work)."),
    "verify": ("Check the work", "Until 12 October 2026, the verifier: a fresh turn that checked "
                                 "each ask really was done before the answer went. The gate no "
                                 "longer checks the work (MAIL.md D18)."),
}

#: The stages a case can pass through, in order, one lane each in the page's
#: chart (`_flow`): (key, name, what it is).
PIPELINE = (
    ("received", "Received", "The message arrived and its case was opened, keyed by its own id: "
                                  "Gmail's for an email, Telegram's for a Telegram message."),
    ("assess", "Read", MODES["assess"][1]),
    ("route", "Ledger", "Rouh's code, not the model, judges each ask the reading found from the "
                        "grants the contact holds: allowed, or waiting for you on its own "
                        "(mail_ledger.judge). Cases before 11 October 2026 show the old route "
                        "here, as it ran."),
    ("word_review", "Word review", "Only when the route stopped on flags the word check alone "
                                   "raised: one model call judges all of them against the "
                                   "whole message, and the case goes back to the route with its "
                                   "verdicts, where a false alarm is overruled "
                                   "(rouh/word_review.py)."),
    ("approval", "Your decision", "Only when the route says so: the case waits for you to "
                                  "approve, decline or instruct."),
    ("carry_out", "Work", MODES["carry_out"][1]),
    ("job", "Job", "Until 12 October 2026, when the work was handed to a background job: the "
                   "case waited for it to end. Now the job is the ask's work, and the case does "
                   "not wait."),
    ("verify", "Verify", MODES["verify"][1]),
    ("handoff", "Sent back", "Until 12 October 2026, what the check found wrong or missing, "
                            "sent back to be fixed by a job, up to two rounds. Nothing is sent "
                            "back now: fixing is the work's own."),
    ("reply", "Told them", "The gate's message goes from Rouh's code, once, in the thread: what "
                           "is allowed and started and what waits for you, or what you decided. "
                           "Each started ask's work sends its own result when it is done."),
)

#: The rail under the chart: every note Rouh sent you about the case.
TOLD_WHAT = ("Every note Rouh sent your phone about this case, by Telegram: when it asked for "
             "your decision, when it finished, and when it stopped. Each sits under the step "
             "it was about.")

#: The three things a step's icon can be, by its shape, and the three colours,
#: by what was decided about it. Grey is neither: nothing to approve yet.
RUN_ICONS = {
    "pending": "Empty circle: this step has not run yet.",
    "running": "Turning ring: this step is running now.",
    "done": "Check mark: this step already ran.",
}
TONES = {
    "good": "Green: it passed.",
    "warn": "Orange: it needs your approval, or is waiting on you.",
    "bad": "Red: it was declined, refused or stopped.",
    "info": "Blue: you told Rouh to do something else instead.",
    "": "Grey: nothing to pass or stop yet.",
}

#: Every term the page explains on hover or tap.
GLOSSARY = {
    "levels": "What you granted a trusted contact on the Trusted contacts page. Communication: "
              "Rouh answers them. Your tasks: Rouh reads the tasks you ticked and may share their "
              "pages. Rouh for themselves: Rouh does work for them in your workspace, filed as "
              "your task with a Guest label. Each level includes the ones before it.",
    "communicate": trust.LEVELS["communicate"][1],
    "tasks": trust.LEVELS["tasks"][1],
    "use": trust.LEVELS["use"][1],
    "other": "The reading's oldest word for something none of the three levels covered; it "
             "is read as the old catch-all.",
    "inbox": old.NEEDS["inbox"][1],
    "inbox_write": old.NEEDS["inbox_write"][1],
    old.AS_OWNER: old.NEEDS[old.AS_OWNER][1],
    "outside_grant": "Old catch-all: until 11 October 2026 the reading's word for anything "
                     "none of the grants covered, which nothing could grant, so the whole "
                     "message waited for you. Since then the reading splits a message into its "
                     "asks, names the grants that cover each, or proposes a new grant, and only "
                     "the asks outside what they hold wait.",
    "asks": "Since 11 October 2026 the reading splits a message into what it asks, each in "
            "their own words, and names the grants that cover each - whether or not they hold "
            "them - or proposes a new grant, or names a hard limit no grant covers. Rouh's code "
            "routes each ask on its own: the asks inside grants they hold are done now, and "
            "only the rest wait for you, each with what stopped it.",
    "inside": "Inside what you granted: every grant the reading says answering takes is one you "
              "gave them, and no risk is touched except sharing a page of a task granted to them, "
              "which their levels cover, or a topic you allowed for this contact when it is "
              "only answered or only prepared - research, analysis, comparisons, drafts, "
              "summaries, pages in the workspace and the reply to them - and nothing about it "
              "is in doubt. Then Rouh does it without asking you, with only the tools of those "
              "levels. Any decision on your behalf - choosing or engaging a provider, filing, "
              "signing, agreeing terms, paying, committing your time, sending to anybody else, "
              "publishing, or anything that cannot be undone - waits for you.",
    "route": "The code's decision after a reading (route_for in rouh/mail_cases.py): direct (only "
             "an answer, sent now), status (only where their own requests stand, answered "
             "from Rouh's records), granted (work inside your grant, done without asking), "
             "approval (waits for you), nothing (nothing to do), junk, or blocked.",
    "direct": "Only an answer, every rule passed: the reply goes now, nothing is changed.",
    "status": "They asked only where their own requests stand, and you let them be told: the "
              "answer is Rouh's own, read from their cases and approvals, with only the state "
              "of each. Nothing they ask is done and nothing the model drafted goes.",
    "granted": "Work to do, all of it inside what you granted: done at once by a turn that has "
               "only those levels' tools, then checked by the verifier.",
    "approval": "At least one rule failed, so the case waits for you on this page.",
    "nothing": "Nothing to do and nothing to answer: you are told what arrived.",
    "needs_approval": "The model's verdict that something has to be decided or changed that it "
                      "may not do alone. It always sends the case to you.",
    "needs_work": "The model's verdict that something has to be done before the reply goes. "
                  "Done without you only if it is inside what you granted.",
    "done": "For a reading: only an answer is needed. For the work: the model says it did it. "
            "For a check: it saw the work done.",
    "no_action": "The model's verdict that there is nothing to do or answer.",
    "blocked": "The model or the code could not go on. The case stops, says precisely why, and "
               "you are told. Nothing more happens until you re-run a step or try again.",
    "waiting_on_job": "The work was handed to a background job; the case follows the job to its "
                      "end and only then has it checked.",
    "verified": "The verifier's answer: true means it saw the work done, false means it did not, "
                "and no reply goes.",
    "verifier": "The check before the reply: a fresh turn of Rouh, in the case's own "
                "conversation, told what was approved and what the work reported, and asked to "
                "see it done the way the sender would. It has the same tools as the work: for a "
                "case inside a grant, only the tools of the contact's levels.",
    "superseded": "An approval that no longer counts and can never be acted on: Rouh asked again "
                  "with a new proposal, a newer message came in the same thread or chat, or the "
                  "contact's permissions changed so the message was read again.",
    "expired": "Ran out of time under the 48-hour limit approvals had until 8 October 2026, "
               "so nothing was done on it. Approvals no longer run out of time.",
    "dismissed": "Closed without a decision: nothing was done on it and nothing was sent. "
                 "Approvals that had run out of time under the old 48-hour limit were "
                 "dismissed on 8 October 2026. Redo still starts the case again.",
    "redo": "Redo starts the whole case again as a fresh attempt, from the message, with your "
            "instructions. The attempt before it is kept as it was, superseded. What it made "
            "in your workspace - a task, a finished research job - is reused, never made "
            "again. Only what reached somebody - a reply that went or may have gone, a "
            "message, a payment, a booking, a share - waits for your approval, and only when "
            "the new attempt would do it again.",
    "reread": "When you change what a contact may do, a case of theirs waiting for you is read "
              "again with the new permissions, and its old approval is superseded.",
    "sweep": f"Every {mc.SWEEP_SECONDS} seconds Rouh looks at every unfinished case and carries "
             "it on from its stage: it retries a turn that never reported (up to "
             f"{mc.MAX_ATTEMPTS} times, then blocks), follows jobs, reminds you once of a decision "
             "left waiting and re-reads cases whose contact changed. It never lapses an "
             "approval because time passed. It is the only clock this mail runs on.",
    # The pipeline header's (?): the route, then the sweep said plainly, since
    # a tip cannot hold another (?) (Petar, 2 October 2026).
    "pipeline": "The code's decision after a reading (route_for in rouh/mail_cases.py): direct (only "
                "an answer, sent now), granted (work inside your grant, done without asking), "
                "approval (waits for you), nothing (nothing to do), junk, or blocked. "
                f"Every {mc.SWEEP_SECONDS} seconds the sweep carries unfinished cases on. "
                "The model reports; Rouh's code decides the route. The sweep is Rouh's own "
                "clock for this mail: it retries a turn that never reported, follows jobs, "
                "reminds you once of a decision left waiting and re-reads cases whose contact "
                "changed. An approval never lapses because time passed.",
    "word_check": "A plain word check over the message's words, an email's subject and body "
                  "(risk_floor in "
                  "rouh/trusted.py). It flags a risk whatever the model thought, so a false alarm "
                  "costs a press and a miss is avoided. Words like access or share trip it. "
                  "Until 2 October 2026 it ran over the proposed reply too.",
    "word_review": "A model call of its own, Luna unless you changed it, that gets every flag "
                   "the plain word check alone raised on this message, with the whole message, "
                   "and says for each whether the message really touches that risk. A flag it calls a "
                   "false alarm is overruled; one it upholds, or any answer it could not give, "
                   "still waits for you. Its model, reasoning and instructions are set on its "
                   "step, and every later message uses them (rouh/word_review.py).",
    "reply_check": "A model call of its own that reads only the drafted reply, with who it goes "
                   "to for context, and says what the reply gives away or commits you to, with "
                   "the sentence that shows it (check_reply in rouh/mail_cases.py). It runs "
                   "only when there is a reply to send.",
    "identity": "How Rouh knows who sent it: for an email, Gmail's own authentication of the "
                "From address (DMARC, SPF, DKIM); for a Telegram message, the account the contact "
                "linked and you confirmed. If it cannot be confirmed, the case always waits for "
                "you.",
    "attempt": f"A turn that ends without a report is tried again by the sweep, up to "
               f"{mc.MAX_ATTEMPTS} times.",
    "brief": "The note Rouh's code writes for the turn: what the turn is for, what it may do, "
             "and the message. It is the last user message of the turn's first request.",
    "system_prompt": "Rouh's whole system prompt for that turn, as sent to the model.",
    "tools": "The tools the model was offered in that turn. A case's turn is only ever offered "
             "what its mode and the contact's levels allow (MailTurn.may_use).",
    "replayed": "The same reading put through today's routing code with the contact's "
                "permissions as they are now. It shows whether this would still stop today.",
    **{f"run_{k}": v for k, v in RUN_ICONS.items()},
    **{f"tone_{k or 'none'}": v for k, v in TONES.items()},
    "prepare": "When all the work does is make what the reply sends - a document, a file - "
               "and it changes nothing outside, Rouh makes it before asking you, so you "
               "approve the finished file rather than a promise of it.",
    "loop_review": "Green or orange dashes: the word review's verdicts going back to the "
                   "route, which runs again with them. Green when it overruled every flag the "
                   "word check raised, orange when it upheld one.",
    "loop_back": "Red dashes: the line climbs back because a check failed in that pass - the "
                 "verifier could not see the work done, making it first failed, or the server "
                 "job did not do it - and the case went back.",
    "loop_restart": "Blue dashes: the case started again as a new pass - Redo, Try again, your "
                    "instructions, a step you ran again, or a re-read when what the contact may "
                    "do changed. The pass's heading says which, and when.",
    "told_wait": "Amber dots, flat in Your decision: the case waited on you, from when Rouh "
                 "asked to when you decided, or until now while you have not.",
    "dec_wait": "Amber, pulsing: Rouh asked for your decision and it still waits on you.",
    "dec_approved": "Green: you approved.",
    "dec_declined": "Red: you declined.",
    "dec_instructed": "Blue: you told Rouh to do something else instead.",
    "dec_void": "Grey: the decision stopped holding before you made it - a newer message or a "
                "new proposal took its place, a file or what the contact may do changed, or you "
                "pressed Redo. Its hover says which.",
    "bell": "A message Rouh sent you about the case, by Telegram: when it asked for your "
            "decision, when it finished, and when it stopped. Tap it to read it.",
    "false_alarm": "A stop that should not have happened: the work was fine, or the risk was not "
                   "real. Marking it with a reason is how the pipeline gets tuned.",
}

#: Rules of `route_for`, named for the page.
RULES = {
    "sender": "Exact address",
    "identity": "Sender confirmed",
    "levels": "Inside what you granted",
    old.AS_OWNER: "Acting as you",
    "inbox_write": "Your inbox can be changed",
    "to_rouh": "Written to Rouh",
    "outcome": "Model's verdict",
    "commitment": "Commits you",
    "show_first": "You asked to see it first",
    # Only in routes kept from before 6 October 2026 (card 1303), when every
    # case with an instruction of the owner's waited for them.
    "instructed": "Your instruction (a rule removed on 6 October)",
    "redo": "Done before the redo",
    "junk": "Junk",
    "route": "Route",
    "status": "Where their requests stand",
    "reply:net": "Never sent without you",
    "reply:check": "Reply check",
    "reply:attached": "Says a file is attached",
}

#: The three groups the Route card shows its rules in, in order (Petar, 2
#: October 2026): who the email is from, what it asks, and what Rouh's reply
#: gives away. Every rule not named here is about what they ask.
GROUPS = (("from", "Who it is from"), ("asks", "What they ask, ask by ask"),
          ("ask", "What they ask"), ("reply", "What the reply gives away"))
GROUP_OF = {"sender": "from", "identity": "from", "to_rouh": "from"}


def _group_of(rule: dict) -> str:
    key = str(rule.get("rule") or "")
    if key.startswith("ask#"):
        return "asks"
    if key.startswith("reply:") or rule.get("old_reply"):
        return "reply"
    return GROUP_OF.get(key, "ask")


#: When a reply began to be judged by a check of its own (2490f26), for a
#: route kept with nothing else in it to say which way it was read.
REPLY_CHECK_SINCE = 1790953757.0


def _clean(rule: str, name: str, lead: str, tip: str, **more) -> dict:
    """A row for a check nothing raised, muted beside the ones that did."""
    return {"rule": rule, "ok": True, "said": lead, "lead": lead, "finds": [], "then": "",
            "tip": tip, "clean": True, "name": name, "mark": "pass", **more}


def _ask_tip(risk: str) -> str:
    return old.RISKS[risk] + (" Raised by Rouh's reading of the message, or by the plain word "
                                "check over it; each row says which." if risk in
                                old.WORD_CHECKED else " Only Rouh's reading can raise it.")


#: Which check raised a risk of what they ask, as the row's badge says it.
_BY = {("Rouh's reading",): "Rouh's reading", ("words in the email",): "Word check",
       ("Rouh's reading", "words in the email"): "Rouh's reading and word check"}


def _not_allowed_then(risk: str, contact_name: str, implicit: bool, *,
                      reply: bool = False, granted=None, blocked_by: str = "") -> str:
    """What the owner did not allow that would cover a stopped risk, for the row's last line.

    Never that a level is missing when the contact holds it (Petar, 11 October 2026: the
    page told him a contact lacked Your tasks, which she had): then it names what they hold
    and the rule that really held it, `blocked_by`."""
    if not reply and granted:
        held = [trust.LEVELS[x][0] for x in old.GRANT_COVERS.get(risk, ()) if x in granted]
        if held:
            return (f"{contact_name} holds " + " and ".join(held) + ", which cover"
                    + ("s" if len(held) == 1 else "") + " it; it waited only because "
                    + (f"of another rule: {blocked_by}." if blocked_by else
                       "another rule failed above."))
    topics = (old.REPLY_COVERS.get(risk, {}).get("topics", ()) if reply else
              ((risk,) if risk in old.TOPICS else ()))
    levels = (old.REPLY_COVERS.get(risk, {}).get("levels", ()) if reply else
              old.GRANT_COVERS.get(risk, ()))
    if topics:
        said = " or ".join(old.TOPICS[t][0] for t in topics)
        if implicit:
            return (f"Not allowed: {said}. {contact_name} is not on your Trusted contacts, "
                    "where it can be allowed, so it waits for you.")
        return f"Not allowed: {said}, for {contact_name}, so it waits for you."
    if levels:
        said = " or ".join(trust.LEVELS[x][0] for x in levels)
        return f"Not granted: {said}, which would cover it, so it waits for you."
    return "Nothing you allowed covers it: it is not something you can allow, so it always " \
           "waits for you."


def every_check(rules: list, report: dict, *, at: float = 0) -> list:
    """The rules of one route with a row for every check, raised or not, for the Route card.

    `route_for` keeps only the risks something raised, though it judged them
    all (Petar, 2 October 2026: he could not see that legal, money, health or
    private data were checked at all). So what they ask gets every risk of
    `trusted.RISKS`, in that order, and what the reply gives away every risk
    the reply check judges and the net; a check nothing raised is a muted
    row that says so. Display only: the rules given are not changed, and
    neither is the conclusion drawn from them. A route that never reached
    the risks (junk from a stranger) is left as it is.
    """
    if not any(r.get("rule") == "levels" for r in rules):
        return list(rules)
    keys = [str(r.get("rule") or "") for r in rules]
    before_split = any(k.startswith("risk:") for k in keys) or (
        not any(k.startswith(("ask:", "reply:")) for k in keys) and 0 < at < REPLY_CHECK_SINCE)

    def risk_of(r: dict) -> str:
        return str(r.get("rule") or "").split(":", 1)[1]

    asks = [r for r in rules if str(r.get("rule") or "").startswith(("risk:", "ask:"))
            and not r.get("old_reply")]
    known = {k for r in asks for k in old.RISK_ALIASES.get(risk_of(r), (risk_of(r),))}
    ask_rows: list = []
    for risk in old.RISKS:
        mine = [r for r in asks if risk in old.RISK_ALIASES.get(risk_of(r), (risk_of(r),))
                and r not in ask_rows]
        if mine:
            ask_rows += mine
        elif risk not in known:
            lead = ("Not raised: no word in the message matched and Rouh's reading did not "
                    "name it." if risk in old.WORD_CHECKED else
                    "Not raised: Rouh's reading did not name it.")
            ask_rows.append(_clean(f"ask:{risk}", _risk_name(risk), lead, _ask_tip(risk)))
    ask_rows += [r for r in asks if r not in ask_rows]      # a risk Rouh does not know

    reply = str(report.get("reply") or "").strip()
    outcome = str(report.get("outcome") or "")
    sending = bool(reply) and bool(report.get("addressed_to_rouh")) and \
        outcome not in ("blocked", "no_action", "junk")
    replies = [r for r in rules if _group_of(r) == "reply"]
    reply_rows: list = []
    if not reply:
        reply_rows.append(_clean("reply:none", "No reply", "There is no reply to send, so "
                                 "there is nothing it could give away.", ""))
    elif before_split:
        olds = [r for r in replies if r.get("old_reply")]
        for risk in old.RISKS:
            mine = [r for r in olds if risk in old.RISK_ALIASES.get(risk_of(r),
                                                                       (risk_of(r),))
                    and r not in reply_rows]
            if mine:
                reply_rows += mine
            elif risk in old.WORD_CHECKED and not any(
                    risk in old.RISK_ALIASES.get(risk_of(r), ()) for r in olds):
                reply_rows.append(_clean(
                    f"risk:{risk}", _risk_name(risk), "Not raised: no word in the proposed "
                    "reply matched.", old.RISKS[risk] + " Until 2 October 2026 the message's "
                    "word check ran over the proposed reply too.", old="old word check",
                    old_reply=True))
        reply_rows += [r for r in replies if r not in reply_rows]
    else:
        by_key = {str(r.get("rule")): r for r in replies}
        check = by_key.get("reply:check")
        if not sending:
            why = ("the message was not written to Rouh, so nothing goes to them from Rouh"
                   if not report.get("addressed_to_rouh") else
                   "Rouh's reading reported it blocked" if outcome == "blocked" else
                   "Rouh's reading found nothing to do")
            reply_rows.append(_clean("reply:none", "Reply check",
                                     f"Not run: {why}. A reply was drafted, but it is not "
                                     "sent on its own.", RULE_TIPS["reply:check"]))
        elif check is not None and check.get("ok") is not True:
            reply_rows.append(check)             # not checked, or a replay from before it
        else:
            for risk in old.REPLY_RISKS:
                got = by_key.get(f"reply:{risk}")
                reply_rows.append(got or _clean(
                    f"reply:{risk}", _risk_name(risk), "Not raised: the reply check found "
                    "nothing of this in the reply.", old.REPLY_RISKS[risk] +
                    " Judged by a model call that read only the reply."))
        reply_rows.append(by_key.get("reply:net") or _clean(
            "reply:net", RULES["reply:net"], "Not raised: no IBAN, card number, password, "
            "code or somebody else's phone number in the reply.", RULE_TIPS["reply:net"]))
        reply_rows += [r for r in replies if r not in reply_rows and r is not check]

    out, placed = [], False
    for r in rules:
        if r in asks or _group_of(r) == "reply":
            continue
        out.append(r)
        if r.get("rule") == "levels" and not placed:
            out += ask_rows
            placed = True
    return out + reply_rows


def _knock_ons(rules: list) -> list:
    """The rules with knock-ons folded under their causes: a rule that failed only because
    another did (`caused_by`, Petar, 11 October 2026) is listed under that rule, so "why it
    was held" leads with the real causes. A cause the trail does not hold leaves it standing."""
    by_rule = {str(r.get("rule") or ""): r for r in rules}
    for r in rules:
        r.pop("knock_ons", None)
    out = []
    for r in rules:
        cause = by_rule.get(str(r.get("caused_by") or ""))
        if cause is not None and cause is not r:
            cause.setdefault("knock_ons", []).append(r)
            r["knocked"] = True
            continue
        out.append(r)
    return out


def grouped(rules: list) -> list[dict]:
    """The rules of one route in the card's groups, empty groups left out, each knock-on
    under the rule it follows from."""
    rules = _knock_ons(rules)
    out = []
    for key, title in GROUPS:
        mine = [r for r in rules if _group_of(r) == key]
        if mine:
            out.append({"key": key, "title": title, "rules": mine})
    return out

#: What each rule is, for the (?) beside its name. A row itself says what the
#: rule found in this email; how the rule works is only ever here.
RULE_TIPS = {
    "status": old.STATUS_OPTION[1] + " Only when the reading says that is all they ask, "
              "the sender passes as for any reply, and you did not ask to see it first.",
    "reply:attached": "A reply that says something is attached (attached, enclosed, "
                      "приложен and the like) goes only with a file the work made, and that "
                      "you see before it goes. With no work to make one, it waits for you; "
                      "the reply cannot be approved claiming a file that is not there.",
    "sender": "The From address has to be exactly one of the addresses you trusted for this "
              "contact. Somebody not on your Trusted contacts has Communication only, which "
              "everybody has.",
    "identity": GLOSSARY["identity"],
    "levels": GLOSSARY["inside"],
    old.AS_OWNER: old.NEEDS[old.AS_OWNER][1],
    "inbox_write": old.NEEDS["inbox_write"][1],
    "to_rouh": "Whether the message was written to Rouh itself, as Rouh's reading reported it. "
               "Yes: Rouh may answer them once the other rules pass. No: Rouh sends them "
               "nothing on its own, so a reading that drafted a reply anyway waits for your "
               "approval, and one with no reply is not held up by it.",
    "outcome": "Rouh's reading said this is a decision only you can make (needs_approval). "
               "That sends the case to you when anything else is in the way, when the sender "
               "is not on your Trusted contacts, and when nothing is to be done but a message. "
               "Since 8 October 2026 it does not on its own for a trusted contact whose work "
               "every other rule found inside their levels: that is done as granted work, with "
               "only their levels' tools, and checked before any reply.",
    "commitment": "What Rouh's reading proposes to do, read for what would commit you rather "
                  "than prepare: " + ", ".join(old.COMMITMENTS[k].format(name="them") for k in
                                              old.COMMITMENTS) + ". Since 8 October 2026 "
                  "anything else - " + old.PREPARATORY.format(name="them") + " - is "
                  "preparatory, and a topic you allowed covers it as it covers an answer. "
                  "Only what it asks to be done counts: what it forbids (\"do not file or pay\") "
                  "and what it says somebody else does are left out.",
    "show_first": "Your instruction on this message asked to see what Rouh made of it before "
                  "anything happens: a draft, show me first, don't send yet, or the same in "
                  "Bulgarian, found by a plain check of your words or by Rouh's reading of "
                  "them. Nothing else about an instruction of yours holds a case; it is "
                  "routed like any other.",
    "redo": GLOSSARY["redo"],
    "junk": "Rouh's reading said it is a newsletter, marketing, bulk mail or an automated "
            "notification. Only mail from somebody not on your Trusted contacts goes to Gmail "
            "spam; for a contact it is nothing to do.",
    "reply:net": "A short word check over the reply for what is never fine to send, whatever "
                 "the model says: " + ", ".join(old.NET.values()) + ". A phone number the "
                 "message itself gave is theirs and is left alone. A hit always waits for you.",
    "reply:check": GLOSSARY["reply_check"],
}

#: Cases kept before 20 October 2026 name acting as the owner by its old word, as a rule and a
#: need: each table reads it as the word it is now.
for _table in (GLOSSARY, RULES, RULE_TIPS):
    _table[old.AS_OWNER_BEFORE] = _table[old.AS_OWNER]

#: The route as the page concludes it: (value, what it means, colour).
CONCLUSIONS = {
    "direct": ("Pass", "answered now", "good"),
    "status": ("Pass", "told where their requests stand", "good"),
    "granted": ("Pass", "done inside what you granted", "good"),
    "approval": ("For approval", "", "warn"),
    "declined": ("Declined", "", "bad"),
    "declined_quiet": ("Declined", "", "bad"),
    "blocked": ("Stopped", "", "bad"),
    "refused": ("Stopped", "", "bad"),
    "junk": ("Junk", "", "good"),
    "nothing": ("Nothing to do", "", "good"),
}

#: Where the word check found a risk's words, as the rule kept it.
_WHERE = {"words in the email": "The message", "words in the proposed reply": "The proposed reply"}


def _risk_name(key: str) -> str:
    """A risk as the conclusion names it: Money, Private data, Legal or health."""
    key = key.split(":", 1)[-1]
    if key in old.RISK_ALIASES:
        return " or ".join(_risk_name(k) for k in old.RISK_ALIASES[key]).capitalize()
    return (old.TOPICS.get(key) or (key.replace("_", " ").capitalize(),))[0]


#: Where a sentence ends: a stop before a space, or a line's end. Not 8.3.
_SENTENCE_END = re.compile(r"[.!?](?=\s)|\n")


def _snippet(word: str, text: str, most: int = 70) -> dict | None:
    """The piece of the sentence a word was found in: before, the word, after."""
    found = re.search(r"(?<![\w])" + re.escape(word) + r"(?![\w])", text or "", re.IGNORECASE)
    if found is None:
        return None
    stops = [m.end() for m in _SENTENCE_END.finditer(text)]
    start = max((i for i in stops if i <= found.start()), default=0)
    end = min((i for i in stops if i >= found.end()), default=len(text))
    before = " ".join(text[start:found.start()].split()).lstrip("-•* ")
    after = " ".join(text[found.end():end].split())
    if len(before) > most:
        before = "…" + before[-most:].split(" ", 1)[-1]
    if len(after) > most:
        after = after[:most].rsplit(" ", 1)[0] + "…"
    return {"before": before + (" " if text[found.start() - 1:found.start()].isspace() and
                                before else ""),
            "word": found.group(0),
            "after": (" " if text[found.end():found.end() + 1].isspace() and after else "")
            + after}


def _explain_levels(r: dict) -> None:
    """The levels needed, held and left uncovered, as one rule row."""
    needs, granted = r.get("needs") or [], r.get("granted") or []
    outside = r.get("outside") or []
    have = ", ".join(trust.LEVELS.get(x, (x,))[0] for x in granted) or "nothing"
    if needs:
        r["lead"] = ("Needed: " + ", ".join(old.need_name(x) for x in needs)
                     + f". They have: {have}.")
        if r.get("inbox") and {"inbox", "inbox_write"} & set(needs):
            r["lead"] += " Your inbox, for them: " + trust.inbox_said(
                r["inbox"], []) + "."
        if outside:
            r["then"] = "Not covered: " + ", ".join(
                old.need_name(x) for x in outside) + "."
    elif r.get("ok") is False:
        r["lead"] = f"Rouh named nothing that answering takes. They have: {have}."
        r["then"] = "So what they want is taken as unclear."
    else:
        r["lead"] = f"Nothing has to be done, so nothing is needed. They have: {have}."


def _explain_reply_risk(r: dict, key: str, said: str, contact_name: str,
                        implicit: bool) -> None:
    """The reply check's sentence, permission and consequence for one risk."""
    risk = key.split(":", 1)[1]
    meaning = old.REPLY_RISKS.get(risk, "")
    r["tip"] = (meaning + " Judged by a model call that read only the reply.").strip()
    sentence = " ".join(str(r.get("sentence") or "").split())
    if sentence:
        r["quote"] = sentence
        r["lead"] = sentence
        if r.get("found") is False:
            r["note"] = "Not word for word in the reply."
    else:
        r["lead"] = "The reply check said so, without naming a sentence."
    name = _risk_name(risk)
    if r.get("ok") and r.get("topic"):
        r["then"] = f"You allowed {name} for {contact_name}; " + (
            "the reply to work that only prepares" if r.get("prep") else
            "only an answer") + ", so it does not wait."
    elif r.get("ok") and r.get("lifted"):
        r["then"] = str(r["lifted"]) + " So it does not wait."
    elif r.get("ok"):
        r["then"] = "Inside what you granted them, so it does not wait."
    elif "but it does not count here: " in said:
        r["then"] = f"You allowed {name} for {contact_name}, but it does not count " \
                    "here: " + said.split("but it does not count here: ", 1)[1]
    else:
        r["then"] = _not_allowed_then(risk, contact_name, implicit, reply=True)
    r["by"] = "Reply check"


def _explain_message_risk(r: dict, rules: list, key: str, said: str, texts: dict,
                          granted_all, contact_name: str, implicit: bool) -> None:
    """The message's matched words, word review and grant coverage for one risk."""
    risk = key.split(":", 1)[1]
    meaning = old.RISKS.get(risk) or " ".join(
        old.RISKS.get(p, "") for p in old.RISK_ALIASES.get(risk, ()))
    if not meaning:
        return                         # a risk Rouh does not know: its own words
    r["tip"] = meaning + " Rouh's reading is the model that read the whole message; the " \
                         "word check looks only for plain words in it."
    if r.get("old_reply"):
        r["old"] = "old word check"
        r["tip"] = meaning + " Until 2 October 2026 the message's word check ran over " \
                             "the proposed reply too, and this was flagged that way."
    where = r.get("where") or []
    words = [str(w) for w in r.get("words") or []]
    leads = []
    for place in where:
        source = _WHERE.get(place)
        if source is None:
            continue
        seen, snips = set(), []
        for w in words:
            if w.lower() in seen:
                continue
            snip = _snippet(w, texts[source])
            if snip is not None:
                seen.add(w.lower())
                snips.append(snip)
        if snips:
            r["finds"].append({"source": source, "snips": snips[:4],
                               "words": [s["word"] for s in snips]})
            leads.append(f"{source} says " + ", ".join(f'"{s["word"]}"'
                                                       for s in snips))
        elif words:
            leads.append(f"{source} says " + ", ".join(f'"{w}"' for w in words))
    if "Rouh's reading" in where:
        leads.append("Rouh's reading named it" + (
            "; no word in the message did" if not leads else ""))
    r["lead"] = ". ".join(leads) + "." if leads else said
    r["by"] = _BY.get(tuple(w for w in ("Rouh's reading", "words in the email")
                            if w in where), "")
    review = r.get("review") if isinstance(r.get("review"), dict) else None
    if review is not None:
        verdict = ("false alarm" if review.get("risky") is False else
                   "still risky" if review.get("risky") else "could not decide")
        r["review_said"] = {"by": review.get("by") or "The word review",
                            "verdict": verdict, "why": review.get("why") or "",
                            "tone": {"false alarm": "good", "still risky": "bad"}
                            .get(verdict, "warn")}
    name = _risk_name(risk)
    if r.get("old_reply") and r.get("ok") is False:
        r["then"] = "The old word check over the reply stopped it. Since 2 October " \
                    "2026 a reply is judged by a check of its own instead."
    elif r.get("ok") and r.get("topic"):
        r["then"] = f"You allowed {name} for {contact_name}; " + (
            "it only prepares work for them and commits you to nothing" if r.get("prep")
            else "only an answer") + ", so it does not wait."
    elif r.get("ok") and r.get("unread"):
        r["then"] = ("Only Rouh's reading named it, with no word in the email for it, and "
                     f"it only prepares work for {contact_name}, whom you trust: a guess "
                     "about the subject holds nothing on its own, so it does not wait.")
    elif r.get("ok") and r.get("overruled"):
        r["then"] = "The word review overruled the word check, so it does not wait."
    elif r.get("ok") and r.get("research"):
        r["then"] = ("Only Rouh's reading named it, and what is to be done pays, buys, "
                     "books or moves nothing: research or costing, which Rouh for "
                     "themselves covers, so it does not wait.")
    elif r.get("ok"):
        levels = [trust.LEVELS[x][0] for x in old.GRANT_COVERS.get(risk, ())
                  if x in (granted_all or ())]
        r["then"] = ("Covered by " + " and ".join(levels) + ", which you granted them, "
                     "so it does not wait." if levels else
                     "Inside what you granted them, so it does not wait.")
    elif "but it does not count here: " in said:
        r["then"] = f"You allowed {name} for {contact_name}, but it does not count " \
                    "here: " + said.split("but it does not count here: ", 1)[1]
    else:
        others = [RULES.get(str(o.get("rule") or ""), str(o.get("rule") or ""))
                  for o in rules if o.get("ok") is False and o is not r and not str(
                      o.get("rule") or "").startswith(("ask:", "risk:", "reply:",
                                                        "ask#", "route"))]
        r["then"] = _not_allowed_then(risk, contact_name, implicit,
                                      granted=granted_all or (),
                                      blocked_by=", ".join(others))


def _explain(rules: list, case, report: dict, contact_name: str,
             implicit: bool = False) -> None:
    """Give every rule a lead that says what it found in this email, and its (?) text.

    Built from the rule's key and the fields it kept (words, where, needs,
    granted), so a case kept before this read the same; a row with nothing
    specific kept leads with its own words.
    """
    email = case.email or {}
    texts = {"The message": (email.get("subject") or "") + "\n" + mc.unquoted(email.get("body")
                                                                             or ""),
             "The proposed reply": str(report.get("reply") or "")}
    granted_all = next((r.get("granted") for r in rules if r.get("rule") == "levels" and
                        r.get("granted") is not None), None)
    # A trail kept before 2 October 2026 ran the email's word check over the
    # reply too, in one rule. Its reply part is shown with what the reply
    # gives away, marked as the old word check, and the rest where it was.
    split: list = []
    for r in rules:
        where = r.get("where") or []
        if str(r.get("rule") or "").startswith("risk:") and \
                "words in the proposed reply" in where:
            asked = [w for w in where if w != "words in the proposed reply"]
            if asked:
                split.append({**r, "where": asked})
            split.append({**r, "where": ["words in the proposed reply"], "old_reply": True})
        else:
            split.append(r)
    rules[:] = split
    for r in rules:
        key = str(r.get("rule") or "")
        said = str(r.get("said") or "")
        r["lead"], r["finds"], r["then"] = said, [], ""
        r["tip"] = RULE_TIPS.get(key, "")
        if key.startswith("ask#"):
            _explain_ask(r)
            continue
        if key == "identity":
            r["lead"] = said.removeprefix("Gmail confirmed it came from that address: ")
        elif key == "to_rouh":
            r["lead"] = "Yes" if said.lower().startswith("written to rouh: yes") else "No"
        elif key == "levels" and "needs" in r:
            _explain_levels(r)
        elif key in (old.AS_OWNER, old.AS_OWNER_BEFORE):
            r["lead"] = "Rouh's reading says answering needs Acting as you."
        elif key == "commitment":
            held = [c for c in r.get("commitments") or [] if isinstance(c, dict)]
            if held:
                r["lead"] = "Proposed: " + old.commitments_said(held) + "."
            r["then"] = "That commits you, not only prepares, so it waits for your yes."
        elif key == "outcome":
            action = " ".join(str(report.get("proposed_action") or "").split())
            r["lead"] = "Rouh's reading says this is a decision only you can make."
            if action:
                r["then"] = "Proposed: " + _first(action, 220)
            if r.get("ok") is True:
                r["lead"] = ("Rouh's reading asked for a decision, but every other rule found "
                             "the work inside their levels.")
                r["then"] = "So it is done as granted work. " + r["then"]
        elif key == "show_first" and case.instruction:
            r["lead"] = "You instructed: " + _first(" ".join(case.instruction.split()), 220)
            r["then"] = (f"Your words \u201c{r['words']}\u201d ask to see it first."
                         if r.get("words") else
                         "Rouh's reading took them as asking to see it first.")
        elif key == "reply:net":
            reply = texts["The proposed reply"]
            nets = [n for n in r.get("net") or [] if isinstance(n, dict)]
            r["lead"] = "The reply holds " + ", ".join(dict.fromkeys(
                old.NET.get(n.get("net"), n.get("net") or "") for n in nets)) + "." \
                if nets else said
            snips = [x for x in (_snippet(str(n.get("found") or ""), reply) for n in nets) if x]
            if snips:
                r["finds"].append({"source": "The proposed reply", "snips": snips[:4],
                                   "words": [x["word"] for x in snips]})
            r["then"] = "Never sent without you, whatever else passed."
        elif key == "reply:check":
            if r.get("ok") is True:
                r["lead"] = "Nothing: it found nothing the reply gives away."
            elif r.get("ok") is False:
                r["lead"] = "It could not be checked: " + str(r.get("error") or "no answer") \
                    .rstrip(".") + "."
                r["then"] = "A reply nobody checked never goes alone, so it waits for you."
        elif key.startswith("reply:"):
            _explain_reply_risk(r, key, said, contact_name, implicit)
        elif key.startswith(("risk:", "ask:")) and r.get("where") is not None:
            _explain_message_risk(r, rules, key, said, texts, granted_all,
                                  contact_name, implicit)


#: Who stopped an ask, as its row's badge says it.
_STOPPED_BY = {"model": "Rouh's reading", "code rule": "Code rule", "word check": "Word check"}


def _grant_name(key: str) -> str:
    """A grant as the owner knows it, by its id, from the organisation's grants when they read."""
    if key in (old.OLD_CATCH_ALL, "other"):
        return "Old catch-all"
    try:
        from . import grants

        return grants.seed_tree().name(key) if key in grants.seed_tree().nodes else             _grant_names.get(key) or key
    except Exception:  # noqa: BLE001 - a name is only a help
        return key


#: Names of grants made since seeding, filled per page by `_name_grants`.
_grant_names: dict[str, str] = {}


def _name_grants(org_id: str) -> None:
    """Read the organisation's grant names once for this page, for `_grant_name`."""
    _grant_names.clear()
    try:
        from . import grants

        tree = grants.tree(org_id)
        _grant_names.update({k: tree.name(k) for k in tree.nodes})
    except Exception:  # noqa: BLE001 - the ids stand in for the names
        log.debug("grant names could not be read for %s", org_id, exc_info=True)


def _explain_ask(r: dict) -> None:
    """One ask of the message, as its row says it: their words, whether it goes now or waits,
    who stopped it and why, and the grant proposed for it."""
    quote = " ".join(str(r.get("ask") or "").split())
    r["quote"] = quote or None
    r["lead"] = quote or str(r.get("said") or "")
    waits = r.get("ok") is False
    names = [_grant_name(k) for k in r.get("grants") or []]
    missing = [_grant_name(k) for k in r.get("missing") or []]
    parts = []
    decided = str(r.get("decided") or "")
    if decided:
        parts.append({"pass": "You let it go just this time.", "reject": "You rejected it.",
                      "grant": "You granted what it needs.", "wrong": "You said holding it was "
                      "wrong: it went, and the false alarm went to be fixed."}.get(
            decided, f"You decided: {decided}."))
    if not waits:
        parts.append("Goes now" + (": inside " + ", ".join(names) if names else "") + ".")
    else:
        parts.append("Waits for you" + (f": {r['cause']}" if r.get("cause") else "")
                     + ("" if str(r.get("cause") or "").endswith(".") else "."))
        if missing:
            parts.append("Not held: " + ", ".join(missing) + ".")
        if r.get("hard_limit"):
            parts.append("A hard limit, which no grant can cover.")
    grant = r.get("new_grant") if isinstance(r.get("new_grant"), dict) else None
    if grant:
        how = {"merge_into": "widen " + _grant_name(str(grant.get("target") or "")),
               "sub_grant_of": "a sub grant of " + _grant_name(str(grant.get("target") or "")),
               "independent": "a grant of its own"}.get(str(grant.get("suggestion") or ""), "")
        parts.append(f"Proposed grant: {grant.get('name') or 'unnamed'}"
                     + (f" ({how})" if how else "") + (f" - {grant['description']}"
                                                      if grant.get("description") else ""))
        if grant.get("nearest"):
            parts.append("Nearest now: " + _grant_name(str(grant["nearest"]))
                         + (f", which does not cover it: {grant['why_not']}"
                            if grant.get("why_not") else "") + ".")
    r["then"] = " ".join(parts)
    if r.get("do"):
        r["note"] = "Rouh would: " + _first(" ".join(str(r["do"]).split()), 240)
    r["by"] = _STOPPED_BY.get(str(r.get("stopped_by") or ""), "") if waits else ""
    r["tip"] = GLOSSARY["asks"]


def _why_short(r: dict) -> str:
    """What one failed rule found, in a few words, for the conclusion."""
    key = str(r.get("rule") or "")
    if key.startswith("ask#"):
        quote = " ".join(str(r.get("ask") or "").split())
        return (f"\u201c{_first(quote, 80)}\u201d" if quote else "an ask") + (
            " (" + ({"model": "Rouh's reading", "code rule": "a code rule",
                     "word check": "the word check"}.get(str(r.get("stopped_by") or ""))
                    or "held") + ")")
    if r.get("old_reply"):
        return "the old word check over the reply"
    if key == "reply:net":
        return ", ".join(dict.fromkeys(old.NET.get(n.get("net"), "") for n in
                                       r.get("net") or [] if isinstance(n, dict))) \
            or "the net"
    if key == "reply:check":
        return "the reply could not be checked"
    if key == "show_first":
        return (f"your words \u201c{r['words']}\u201d" if r.get("words") else
                "Rouh's reading of your words")
    if key.startswith("reply:"):
        sentence = " ".join(str(r.get("sentence") or "").split())
        return f"\u201c{_first(sentence, 90)}\u201d" if sentence else "the reply check"
    if key.startswith(("risk:", "ask:")):
        review = r.get("review") if isinstance(r.get("review"), dict) else None
        if review is not None:
            return ("the word check, upheld by the word review" if review.get("risky") else
                    "the word check; the word review could not decide")
        where = [w for w in r.get("where") or []]
        return " and ".join(where) if where else "flagged"
    if key == "levels":
        outside = r.get("outside") or []
        named = [old.need_name(x) for x in outside if old.NEED_ALIASES.get(x, x) !=
                 old.OLD_CATCH_ALL]
        if outside and not named:
            return "the old catch-all: something no grant covered"
        if not outside:
            return "nothing named that answering takes"
        return "needs " + ", ".join(named) + (", and the old catch-all"
                                              if len(named) < len(outside) else "")
    return {"sender": "the From address", "identity": "the sender could not be confirmed",
            old.AS_OWNER: "it needs acting as you", old.AS_OWNER_BEFORE: "it needs acting as you",
            "inbox_write": "your inbox is read-only",
            "outcome": "Rouh's reading asked for a decision",
            "commitment": "it would commit you: " + ", ".join(dict.fromkeys(
                str(c.get("said") or "") for c in r.get("commitments") or []
                if isinstance(c, dict))),
            "redo": "it would repeat what already reached somebody"}.get(key, _first(r.get("said") or "", 120))


def _conclude(rules: list, route: str, report: dict, *, declined_why: str = "") -> dict:
    """Take the route's own row out of the rules, and say the outcome it reached."""
    row = next((r for r in rules if r.get("rule") == "route"), None)
    if row is not None:
        rules.remove(row)
    route = declined_why and "declined" or route or (row or {}).get("route") or ""
    if not route:
        return {}
    value, means, tone = CONCLUSIONS.get(route, (route, "", ""))
    caused = {str(r.get("rule") or "") for r in rules if r.get("ok") is False}
    knocked = [r for r in rules if r.get("ok") is False and r.get("caused_by")
               and str(r.get("caused_by")) in caused and r.get("caused_by") != r.get("rule")]
    failed = [r for r in rules if r.get("ok") is False and r not in knocked]
    waiting = [r for r in rules if str(r.get("rule") or "").startswith("ask#")
               and r.get("ok") is False]
    by = ""
    if declined_why:
        why = declined_why
        by = "What they ask"
    elif route == "approval" and failed:
        parts, titles = [], []
        for gkey, title in GROUPS:
            mine = [r for r in failed if _group_of(r) == gkey]
            if not mine:
                continue
            titles.append(title)
            groups: list[tuple[str, list[str]]] = []
            for r in mine:
                short = _why_short(r)
                rkey = str(r.get("rule", ""))
                name = RULES.get(rkey) or (_risk_name(rkey) if rkey.startswith(
                    ("risk:", "ask:", "reply:")) else "Ask " + rkey[4:]
                    if rkey.startswith("ask#") else rkey)
                if groups and groups[-1][0] == short:
                    groups[-1][1].append(name)
                else:
                    groups.append((short, [name]))
            parts.append(title + " - " + "; ".join(
                " and ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]
                + ": " + short for short, names in groups))
        why = ". ".join(p.rstrip(".") if not p.endswith(".\u201d") else p for p in parts)
        why += "" if why.endswith((".", ".\u201d")) else "."
        if knocked:
            why += " Following from those: " + ", ".join(
                RULES.get(str(r.get("rule"))) or _risk_name(str(r.get("rule") or ""))
                for r in knocked) + "."
        by = " and ".join(titles)
    elif route == "approval" and row is not None and \
            row.get("said", "").startswith("It was not written to Rouh"):
        why = "Written to Rouh: No, and a reply was drafted."
        by = "Who it is from"
    elif route == "direct":
        why = "Every rule passed, and it is only an answer."
        by = "all three groups passing"
    elif route == "status":
        why = ("They asked only where their own requests stand, and you let them be told, so "
               "Rouh answered from its records.")
        by = "Who it is from passing"
    elif route == "granted":
        by = "all three groups passing"
        levels = next((r for r in rules if r.get("rule") == "levels"), {})
        why = "Every rule passed, and the work is inside what you granted" + (
            ": " + ", ".join(old.need_name(x) for x in levels["needs"])
            if levels.get("needs") else "") + "."
    elif route == "blocked":
        blocker = " ".join(str(report.get("blocker") or "").split())
        why = "Rouh's reading reported it blocked" + (": " + _first(blocker, 200)
                                                     if blocker else ".")
    elif route == "nothing":
        why = "Rouh's reading found nothing to do or answer."
    else:
        why = (row or {}).get("said", "")
    if by == "all three groups passing" and any(
            r.get("rule") == "reply:check" and r.get("ok") is None for r in rules):
        by = "Who it is from and What they ask passing; the reply was not judged"
    if waiting and route in ("direct", "granted"):
        # Petar, 11 October 2026: one message can be partly done now and partly waiting.
        value, tone = "Partly", "warn"
        means = "what is inside their grants goes now; the rest waits for you"
        why = (why.removeprefix("Every rule passed, and ").rstrip(".") + ". "
               if why else "") + f"{len(waiting)} ask{'s' if len(waiting) != 1 else ''} " \
            f"wait{'s' if len(waiting) == 1 else ''} for you: " + "; ".join(
                _why_short(r) for r in waiting) + "."
        why = why[:1].upper() + why[1:]
    if route in ("blocked", "nothing", "junk") and not by:
        by = "What they ask"
    return {"route": route, "value": value, "means": means, "tone": tone, "why": why,
            "by": by}


# --- reading the request log --------------------------------------------------------------


def _requests(case) -> list:
    """Every model request the case's own chat made, oldest first, for its own person."""
    from .models import LLMRequest

    if not case.chat_id:
        return []
    return list(LLMRequest.objects.filter(user_id=case.user_id, org_id=case.org_id,
                                          session_id=case.chat_id).order_by("id"))


def _bodies(hashes) -> dict:
    from .models import LLMPiece

    wanted = [h for h in dict.fromkeys(hashes) if h]
    if not wanted:
        return {}
    out = {}
    for digest, body in LLMPiece.objects.filter(hash__in=wanted).values_list("hash", "body"):
        try:
            out[digest] = json.loads(body)
        except ValueError:
            out[digest] = body
    return out


def _text_of(message) -> str:
    """The words of one message as the model got it."""
    if isinstance(message, str):
        return message
    content = (message or {}).get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
    return "\n".join(parts)


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(str(b.get("text") or "") for b in content or []
                     if isinstance(b, dict) and b.get("type") == "text")


def _money(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def turns_of(case) -> list[dict]:
    """The case's model turns from the request log, each with its calls and transcript."""
    rows = _requests(case)
    groups: dict[str, list] = {}
    for row in rows:
        groups.setdefault(row.turn_id or f"request-{row.id}", []).append(row)
    lasts = [h for row in rows for h in (row.message_pieces or [])[-3:]]
    bodies = _bodies(lasts)
    out = []
    for turn_id, reqs in groups.items():
        calls, transcript, tools_called = [], [], []
        report_call = None
        for i, row in enumerate(reqs):
            calls.append({
                "id": row.id, "model": row.served_model or row.model, "status": row.status,
                "attempt": row.attempt, "effort": row.effort, "thinking": row.thinking,
                "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
                "cache_read_tokens": row.cache_read_tokens,
                "cache_write_tokens": row.cache_write_tokens,
                "cost": _money(row.cost_usd), "ms": row.duration_ms or 0,
                "stop_reason": row.stop_reason, "error": row.error,
                "at": row.started_at, "when": _clock(row.started_at),
            })
            content = ((row.response or {}).get("content") or []) if row.response else []
            for block in content:
                kind = block.get("type") if isinstance(block, dict) else ""
                if kind == "thinking" and block.get("thinking"):
                    transcript.append({"kind": "thinking", "text": block["thinking"],
                                       "request": row.id})
                elif kind == "text" and block.get("text"):
                    transcript.append({"kind": "said", "text": block["text"],
                                       "request": row.id})
                elif kind in ("tool_use", "server_tool_use"):
                    entry = {"kind": "call", "name": block.get("name") or "",
                             "input": block.get("input") or {}, "request": row.id,
                             "id": block.get("id") or ""}
                    entry["input_json"] = json.dumps(entry["input"], indent=2,
                                                     ensure_ascii=False)
                    transcript.append(entry)
                    tools_called.append(entry["name"])
                    if entry["name"] == "case_report" and isinstance(entry["input"], dict):
                        report_call = entry["input"]
                elif kind.endswith("_tool_result"):
                    # A server tool's answer (web_fetch, web_search) comes back
                    # inside the same response as its call.
                    inner = block.get("content")
                    said = json.dumps(inner, ensure_ascii=False)[:6000] \
                        if not isinstance(inner, str) else inner[:6000]
                    if isinstance(inner, dict) and inner.get("type", "").endswith("_error"):
                        said = f"Error: {inner.get('error_code') or inner}"
                    for entry in reversed(transcript):
                        if entry.get("kind") == "call" and \
                                entry.get("id") == block.get("tool_use_id"):
                            entry["result"] = said
                            entry["error"] = "error" in str(inner)[:200].lower()
                            break
            if row.status != "ok" and not content:
                transcript.append({"kind": "error", "request": row.id,
                                   "text": f"Request {row.id} ended {row.status}"
                                           + (f": {row.error}" if row.error else ".")})
            nxt = reqs[i + 1] if i + 1 < len(reqs) else None
            if nxt is not None:
                last = bodies.get((nxt.message_pieces or [None])[-1])
                blocks = (last or {}).get("content") if isinstance(last, dict) else None
                for block in blocks if isinstance(blocks, list) else []:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        for entry in reversed(transcript):
                            if entry.get("kind") == "call" and \
                                    entry.get("id") == block.get("tool_use_id"):
                                entry["result"] = _result_text(block)[:6000]
                                entry["error"] = bool(block.get("is_error"))
                                break
        first = reqs[0]
        # The brief is the turn's own note, the last user message of a request
        # that is not a tool's result. A first request can be cut short and
        # sent again with a pause note in its place, so the longest wins.
        brief = max((_text_of(bodies.get(h)) for r in reqs
                     for h in (r.message_pieces or [])[-3:]
                     if isinstance(bodies.get(h), dict) and bodies[h].get("role") == "user"),
                    key=len, default="")
        out.append({
            "turn_id": turn_id, "started": first.started_at,
            "ended": max((r.finished_at or r.started_at) for r in reqs),
            "calls": calls, "transcript": transcript, "tools_called": tools_called,
            "report_call": report_call, "brief": brief,
            "cost": round(sum(c["cost"] for c in calls), 6),
            "ms": sum(c["ms"] for c in calls),
            "model": calls[-1]["model"] if calls else "",
            "first_request": first.id, "tools_piece": first.tools_piece,
            "system_piece": first.system_piece, "purpose": first.purpose or "",
        })
    out.sort(key=lambda t: t["started"])
    return out


def tool_names(tools_piece: str) -> list[str]:
    """The names of the tools a request offered, from its tools piece."""
    if not tools_piece:
        return []
    tools = _bodies([tools_piece]).get(tools_piece)
    names = []
    for tool in tools if isinstance(tools, list) else []:
        if isinstance(tool, dict):
            names.append(str(tool.get("name") or tool.get("type") or ""))
    return [n for n in names if n]


def request_for(case, request_id: int) -> dict | None:
    """One request of this case's chat, rebuilt whole as it was sent, with its answer."""
    from . import llmlog
    from .models import LLMRequest

    row = LLMRequest.objects.filter(id=request_id, user_id=case.user_id, org_id=case.org_id,
                                    session_id=case.chat_id).first() if case.chat_id else None
    if row is None:
        return None
    asked = llmlog.request_of(row)
    return {"id": row.id, "model": row.served_model or row.model, "status": row.status,
            "when": _clock(row.started_at), "request": asked,
            "response": row.response or {}, "reasoning": row.reasoning or "",
            "text": row.text or "", "cost": _money(row.cost_usd),
            "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
            "cache_read_tokens": row.cache_read_tokens, "ms": row.duration_ms or 0}


# --- steps ------------------------------------------------------------------------------


def _clock(ts: float) -> str:
    return mc._stamp(ts) if ts else ""


def _secs(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0))
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


_TURN_STAGES = {"assessing": "assess", "working": "carry_out", "verifying": "verify"}


def _stage_at(events: list[dict], at: float) -> str:
    stage = ""
    for e in events:
        if e["at"] <= at:
            stage = e["stage"]
        else:
            break
    return stage


def _verdict(mode: str, report: dict | None) -> tuple[str, str]:
    """A turn's verdict in a word, and its colour on the page."""
    if not report:
        return "no report", "bad"
    outcome = str(report.get("outcome") or "")
    if mode == "verify":
        if report.get("verified") is True and outcome != "blocked":
            return "verified", "good"
        return f"{outcome or 'not'} · verified false", "bad"
    colour = {"done": "good", "needs_work": "good", "no_action": "good", "junk": "good",
              "waiting_on_job": RUNNING, "needs_approval": "warn", "blocked": "bad"}
    return outcome or "?", colour.get(outcome, "")


#: A step's status while it is still going: it has no verdict yet, so no colour.
#: `_runs` settles it into `run` ("running", or "done" once a later step followed).
RUNNING = "running"

#: The case's own stage while one of its turns is going, by the turn's mode.
_GOING = {"assess": mc.ASSESSING, "carry_out": mc.WORKING, "verify": mc.VERIFYING}


def _icon_tip(run: str, status: str) -> str:
    return f"{RUN_ICONS.get(run, '')} {TONES.get(status, TONES[''])}".strip()


def _identity_line(ok: bool, said: str) -> str:
    """Gmail's check on the sender in one line: "DMARC passed", or what it saw instead."""
    said = (said or "").strip()
    if ok:
        return said[:1].upper() + said[1:] if said else "Confirmed"
    seen = re.search(r"\(([^()]*)\)\s*$", said)
    return "Not confirmed: " + (seen.group(1) if seen else said or "nothing was recorded")


def _runs(case, steps: list[dict], working: bool = False) -> None:
    """Each step's run state (not run, running, ran), and a colour only once it has a verdict.

    A step that was still going when it was written down (a re-read, a redo, your
    instruction, a job) is running only while it is the latest step and something of the
    case is really working now (D17): a case waiting for the owner, or one whose step was cut
    short, has nothing running, whatever its last step said when it was written. A turn with
    no report yet is running on the same terms, while the case is still in that turn's stage.
    """
    for i, step in enumerate(steps):
        last = i == len(steps) - 1
        step["run"] = "done"
        if step["status"] == RUNNING:
            if last and working:
                step["run"], step["status"] = "running", ""
            else:
                step["status"] = "good"
        elif (step["kind"] in _GOING and not step.get("report") and last and working
              and case.stage == _GOING[step["kind"]]):
            step["run"], step["status"], step["verdict"] = "running", "", "running"


def _event_kind(e: dict) -> str:
    """What one timeline event is, for grouping it into steps."""
    said, stage = e["said"], e["stage"]
    if said.startswith(mc.CaseDesk.FILES_SAID):
        return "files"
    if said.startswith(old.PREPARE_SAID):
        return "prepare"
    if said.startswith("Making it first did not get there"):
        return "prepare_failed"
    if stage == mc.NEW and said.startswith(("Email from", "Telegram message from",
                                            "Message from")):
        return "received"
    if said.startswith((old.REREAD_SAID, old.REPREPARE_SAID)):
        return "reread"
    if said.startswith(mc.REDO_SAID):
        return "redo"
    if stage == mc.NEW:
        return "instruction"
    if (stage == mc.AWAITING and said.startswith("Waiting for your decision")) or \
            said.startswith("Your decision:"):
        return "asked"
    if said.startswith(("You approved", "You declined", "You decided")):
        return "decided"
    if said.startswith("Failed:"):
        return "failed"
    if stage == mc.BLOCKED or said.startswith(old.STOP_SAID):
        # Rouh stopping where it cannot go on is drawn where it stopped, as a block was; it
        # waits for the owner since 11 October 2026 (`CaseDesk._stop`).
        return "blocked"
    if said.startswith(("Replied", "The reply had already gone", "Answered on")):
        return "reply"
    if said.startswith((mc.FOLLOW_UP_SENT_SAID, mc.FOLLOW_UP_FAILED_SAID)):
        return "followup"
    if said.startswith("You were told") or said.startswith("Done; no note") or \
            said.startswith("You were sent a note") or said.startswith("No note could go"):
        return "told"
    if said.startswith("Inside what you granted") or said.startswith("Routine and inside"):
        return "routed"
    if said.startswith(("Handed to a server job", "Handed to you to decide",
                        "Sent back to be fixed", mc.LOOK_SAID)):
        return "handoff"
    if stage == mc.FOLLOW_UP or said.startswith(("Waiting for server job",
                                                 "Waiting for assistant job",
                                                 "The server job for it could not",
                                                 "The job to fix it could not")):
        return "followjob"
    if said.startswith("Only part of it could be proven"):
        return "honest"
    if said.startswith("Waiting for job") or (stage == mc.WAITING_JOB):
        return "job"
    if said.startswith("Verified:"):
        return "verified"
    if said.startswith("You asked Rouh to"):
        return "instruction"
    return ""


def _case_rounds(case, events: list, turns: list, turn_rows: list, report_rows: list,
                 trouble_rows: list, kept_since) -> list[dict]:
    """Match each kept or recovered round to its route, requests and report."""
    # Rounds: one per turn of the model. A kept turn row where there is one;
    # before those, a turn read back from the request log.
    rounds: list[dict] = []
    for i, row in enumerate(turn_rows):
        until = turn_rows[i + 1]["at"] if i + 1 < len(turn_rows) else float("inf")
        rounds.append({"mode": row["mode"], "attempt": row["attempt"], "at": row["at"],
                       "until": until, "kept": row["data"], "source": "kept"})
    for turn in turns:
        if kept_since is not None and turn["started"] >= kept_since - 1:
            continue
        stage = _stage_at(events, turn["started"])
        mode = _TURN_STAGES.get(stage, "")
        if not mode:
            continue
        rounds.append({"mode": mode, "attempt": 0, "at": turn["started"],
                       "until": float("inf"), "kept": None, "source": "log"})
    rounds.sort(key=lambda r: r["at"])
    # What an earlier reading was routed to, from what the case wrote down then.
    for r in rounds:
        if r["mode"] != "assess":
            continue
        for e in events:
            if not (r["at"] <= e["at"] < r["until"]):
                continue
            said = e["said"]
            got = ("approval" if said.startswith("Waiting for your decision") else
                   "granted" if said.startswith("Inside what you granted") else
                   "direct" if said.startswith("Routine and inside") else
                   "status" if said.startswith(old.STATUS_SAID) else
                   "nothing" if said.startswith("Nothing to do") else
                   "blocked" if e["stage"] == mc.BLOCKED else "")
            if got:
                r["route_then"] = got
                if got == "approval":
                    r["reasons_then"] = [said.removeprefix("Waiting for your decision: ")]
                break
    for r in reversed(rounds):
        if r["mode"] == "assess":
            r["last_assess"] = True
            break
    for i, r in enumerate(rounds):
        if r["source"] == "log":
            r["until"] = rounds[i + 1]["at"] if i + 1 < len(rounds) else float("inf")
    used_turns: set[str] = set()
    for r in rounds:
        r["turns"] = []
        for turn in turns:
            if turn["turn_id"] in used_turns:
                continue
            if r["at"] - 1 <= turn["started"] < r["until"]:
                r["turns"].append(turn)
                used_turns.add(turn["turn_id"])
        rep = next((t for t in report_rows if t["mode"] == r["mode"] and
                    r["at"] - 1 <= t["at"] < r["until"]), None)
        if rep is not None:
            r["report"], r["report_from"] = rep["data"].get("report"), "kept"
        else:
            kept = (case.assessment or {}).get(r["mode"])
            if kept and r["at"] - 1 <= float(kept.get("at") or 0) < r["until"]:
                r["report"], r["report_from"] = kept, "case"
            else:
                call = next((t["report_call"] for t in reversed(r["turns"])
                             if t["report_call"]), None)
                r["report"], r["report_from"] = (call, "model") if call else (None, "")
        r["trouble"] = [t["data"].get("trouble") for t in trouble_rows
                        if t["mode"] == r["mode"] and r["at"] - 1 <= t["at"] < r["until"]]

    return rounds


def _add_event_steps(case, events: list, approvals: list, file_rows: list,
                     sent_rows: list, steps: list, add) -> None:
    """Render the approvals and events between model rounds as their own steps."""
    # Approvals, and the events between the turns, as steps of their own.
    by_asked = {round(a.asked_at): a for a in approvals}
    for e in events:
        kind = _event_kind(e)
        if kind == "received":
            continue
        if kind == "asked":
            approval = next((a for a in approvals if abs(a.asked_at - e["at"]) < 5), None) \
                or by_asked.get(round(e["at"]))
            add("approval", e["at"], stage="approval", title="Asked you",
                status={"pending": "warn", "approved": "good", "declined": "bad",
                        "instructed": "info"}.get(getattr(approval, "status", ""), ""),
                summary=e["said"].removeprefix("Waiting for your decision: "),
                approval=_approval(approval, case.key) if approval else None,
                files=_approval(approval, case.key)["files"] if approval else [])
        elif kind == "files":
            row = min((t for t in file_rows), key=lambda t: abs(t["at"] - e["at"]),
                      default=None)
            add("files", e["at"], stage="carry_out", title="Files for the reply",
                status="good", summary=e["said"].removeprefix(mc.CaseDesk.FILES_SAID)
                .lstrip(", ").capitalize().rstrip("."),
                files=files_shown((row or {}).get("data", {}).get("files") or [], case.key))
        elif kind == "prepare":
            add("prepare", e["at"], stage="carry_out", title="Made first, then asked",
                status=RUNNING, summary=_sentence(e["said"].removeprefix(old.PREPARE_SAID)))
        elif kind == "prepare_failed":
            add("prepare_failed", e["at"], stage="carry_out", title="Making it first failed",
                status="bad", summary=e["said"])
        elif kind == "reread":
            add("reread", e["at"], stage="reread", title="Re-read", status=RUNNING,
                summary=e["said"])
        elif kind == "redo":
            add("redo", e["at"], stage="redo", title="Redo: a fresh attempt", status=RUNNING,
                summary=e["said"].removeprefix(mc.REDO_SAID).strip())
        elif kind == "instruction":
            add("instruction", e["at"], stage="instruction", title="You asked again",
                status=RUNNING, summary=e["said"])
        elif kind == "decided":
            add("decided", e["at"], stage="approval", title="You decided", status="good",
                summary=e["said"])
        elif kind == "job":
            add("job", e["at"], stage="job", title="Job", status=RUNNING, summary=e["said"])
        elif kind == "handoff":
            add("handoff", e["at"], stage="handoff", title="Handed on", status="warn",
                summary=e["said"])
        elif kind == "followjob":
            bad = "not done" in e["said"] or "could not be started" in e["said"]
            add("followjob", e["at"], stage="handoff",
                title="Read-back job" if "reads the work back" in e["said"] else
                "Fix job" if "assistant job" in e["said"] or "to fix it" in e["said"]
                else "Server job",
                status="bad" if bad else RUNNING, summary=e["said"])
        elif kind == "honest":
            add("honest", e["at"], stage="reply", title="Only what was proven",
                status="warn", summary=e["said"])
        elif kind == "reply":
            add("reply", e["at"], stage="reply", title="Reply", status="good",
                summary=e["said"], files=files_shown(case.approved_files or [], case.key),
                sent=_reply_sent(case, e, sent_rows))
        elif kind == "followup":
            add("followup", e["at"], stage="reply", title="Follow-up",
                status="bad" if e["said"].startswith(mc.FOLLOW_UP_FAILED_SAID) else "good",
                summary=e["said"].split(": \"", 1)[0] + ".")
        elif kind == "told":
            add("notify", e["at"], stage="notify", title="Told you",
                status="good" if not e["said"].startswith(("Done; no note", "No note")) else
                "warn", summary=e["said"])
        elif kind == "failed":
            add("failed", e["at"], stage="blocked", title="Failed, waits for your Redo",
                status="bad", summary=e["said"].removeprefix("Failed:").strip())
        elif kind == "blocked":
            held = e["said"].startswith(old.STOP_SAID)
            add("blocked", e["at"], stage="blocked",
                title="Stopped, waits for you" if held else "Blocked",
                status="warn" if held else "bad",
                summary=e["said"].removeprefix(old.STOP_SAID).removeprefix("Blocked: ").strip())
        else:
            steps.append({"kind": "_event", "at": e["at"], "event": e})


def build(case, store: mc.CaseStore | None = None, contact_now=None,
          working: bool | None = None, state=None) -> dict:
    """Every step of one case, matched to its model calls, with a diagnosis. For the page.
    `working` is whether anything of the case is really working this instant
    (`CaseDesk.live_of`); without it, only a case at a step in flight can be. `state` is the
    case's one state (`CaseDesk.state_of`), which the diagnosis says when it is given."""
    store = store or mc.CaseStore()
    uid, oid = case.user_id, case.org_id
    _name_grants(oid)
    events = store.events(uid, oid, case.id)
    traces = store.traces(uid, oid, case.id)
    approvals = store.approvals(uid, oid, case.id)
    notes = store.notes(uid, oid, case.id)
    every_turn = turns_of(case)
    # Taken first, from a copy: the steps below explain the kept rows in place, and the
    # Step by step table shows them only as they were kept.
    import copy

    kept_steps = timeline(copy.deepcopy(traces), every_turn)
    # The reply check is a model call of its own, not a turn: shown in the
    # route it fed (`_route_step`), never taken for a round's turn.
    turns = [t for t in every_turn if t["purpose"] not in ("reply_check", old.REVIEW_PURPOSE)]
    check_turns = [t for t in every_turn if t["purpose"] == "reply_check"]
    check_rows = [t for t in traces if t["kind"] == "reply_check"]
    # The word review is a model call of its own too, and a step of its own.
    review_turns = [t for t in every_turn if t["purpose"] == old.REVIEW_PURPOSE]
    review_rows = [t for t in traces if t["kind"] == "word_review" and t["mode"] != "trial"]
    first_rows = [t for t in traces if t["kind"] == "route_first"]
    trial_rows = [t for t in traces if t["kind"] == "word_review" and t["mode"] == "trial"]
    turn_rows = [t for t in traces if t["kind"] == "turn"]
    report_rows = [t for t in traces if t["kind"] == "report"]
    route_rows = [t for t in traces if t["kind"] == "route"]
    trouble_rows = [t for t in traces if t["kind"] == "trouble"]
    file_rows = [t for t in traces if t["kind"] == "files"]
    sent_rows = [t for t in traces if t["kind"] == "sent"]
    ledger_rows = [t for t in traces if t["kind"] == "ledger"]
    kept_since = turn_rows[0]["at"] if turn_rows else None

    rounds = _case_rounds(case, events, turns, turn_rows, report_rows, trouble_rows,
                          kept_since)

    steps: list[dict] = []
    counts: dict[str, int] = {}

    def add(kind: str, at: float, **fields) -> dict:
        counts[kind] = counts.get(kind, 0) + 1
        step = {"id": f"{kind}-{counts[kind]}", "kind": kind, "at": at, "when": _clock(at),
                "log": [], **fields}
        steps.append(step)
        return step

    email = case.email or {}
    add("received", case.created_at - 0.01, stage="received", title="Received",
        status=("good" if case.identity_ok else "bad" if case.route == "refused" else "warn"),
        email=email, channel=mc.channel_of(case), identity_ok=case.identity_ok,
        identity_said=case.identity_said, identity_line=_identity_line(case.identity_ok, case.identity_said))

    for r in rounds:
        mode = r["mode"]
        name, what = MODES.get(mode, (mode, ""))
        verdict, colour = _verdict(mode, r.get("report"))
        turn0 = r["turns"][0] if r["turns"] else None
        kept = r.get("kept") or {}
        brief = kept.get("brief") or (turn0["brief"] if turn0 else "")
        ended = max((t["ended"] for t in r["turns"]), default=r["at"])
        tools_offered = tool_names(turn0["tools_piece"]) if turn0 else []
        report = r.get("report") or {}
        step = add(mode, r["at"], stage=mode, title=name, what=what, status=colour,
                   verdict=verdict, attempt=r.get("attempt") or 0, source=r["source"],
                   brief=brief, kept=kept, report=report, report_from=r.get("report_from"),
                   turns=r["turns"], tools_offered=tools_offered,
                   took=_secs(ended - (turn0["started"] if turn0 else r["at"])),
                   cost=round(sum(t["cost"] for t in r["turns"]), 4),
                   model=(turn0 or {}).get("model", ""),
                   trouble=r.get("trouble") or [],
                   summary=str(report.get("summary") or "").strip())
        step["said_out"] = (str(report.get("blocker") or "") if report.get("outcome") ==
                            "blocked" or report.get("verified") is False else
                            str(report.get("evidence") or report.get("checked") or ""))
        if mode == "assess" and report:
            route_row = next((t for t in route_rows if r["at"] - 1 <= t["at"] < r["until"]),
                             None)
            # Routed the moment the report came: kept with it, or else just after
            # the request that made it, which is the turn's last.
            last_call = (r["turns"][-1]["calls"][-1]["at"] if r["turns"] and
                         r["turns"][-1]["calls"] else ended)
            check_row = next((t for t in check_rows if t["mode"] == "assess" and
                              r["at"] - 1 <= t["at"] < r["until"]), None)
            review_row = next((t for t in review_rows if t["mode"] == "assess" and
                               r["at"] - 1 <= t["at"] < r["until"]), None)
            first_row = next((t for t in first_rows if t["mode"] == "assess" and
                              r["at"] - 1 <= t["at"] < r["until"]), None)
            route_at = float(report.get("at") or last_call) + 0.001
            # With a word review: the route's first pass, the review, and the
            # route it went back to, each a step (Petar, 3 October 2026).
            if review_row is not None and first_row is not None:
                add("route", route_at - 0.0008, stage="route", title="Route",
                    **_first_route_step(case, report, first_row, contact_now,
                                        check_row=check_row, check_turns=check_turns))
            if review_row is not None:
                add("word_review", route_at - 0.0005, stage="word_review", title="Word review",
                    **_review_step(review_row, review_turns, trial_rows))
            final = _route_step(case, report, route_row, contact_now, r,
                                check_row=check_row, check_turns=check_turns,
                                review_row=review_row)
            if review_row is not None and first_row is not None:
                final["summary"] = final["summary"] or ("Back from the word review: the "
                                                        "route again, with its verdicts.")
                final["reply_check"] = None     # shown on the first pass, where it ran
                final["second_pass"] = True
            add("route", route_at, stage="route", title="Route", **final)
        if mode == "assess":
            row = next((t for t in ledger_rows if r["at"] - 1 <= t["at"] < r["until"]), None)
            if row is not None:
                add("ledger", float(row["at"]), stage="route", title="The ledger",
                    **_ledger_step(row, case))

    _add_event_steps(case, events, approvals, file_rows, sent_rows, steps, add)
    steps.sort(key=lambda s: (s["at"], 0 if s["kind"] != "_event" else 1))
    # Loose events belong to the step they happened in.
    out: list[dict] = []
    for step in steps:
        if step["kind"] == "_event":
            # A line its step's head already says word for word is not said twice.
            if out and " ".join(step["event"]["said"].split()) != " ".join(
                    str(out[-1].get("summary") or "").split()):
                out[-1]["log"].append({"when": _clock(step["event"]["at"]),
                                       "said": step["event"]["said"]})
            continue
        out.append(step)
    for step in out:
        step["note_count"] = sum(1 for n in notes if n["step"] == step["id"])
    # Every other message to the sender, word for word, on the step it went in.
    shown = {(one["message_id"], one["text"]) for step in out for one in step.get("sent") or []}
    for row in sent_rows:
        d = row.get("data") or {}
        if d.get("message_id") and (d.get("message_id"), d.get("text") or "") in shown:
            continue
        held = [step for step in out if step["at"] <= row["at"] + 0.5]
        if held:
            held[-1].setdefault("sent", []).append(_sent_view(row))

    _runs(case, out, case.stage in mc.IN_FLIGHT if working is None else working)
    for step in out:
        _annotate(step)
    anomalies = _anomalies(case, out)
    for step in out:
        step["icon_tip"] = _icon_tip(step["run"], step["status"])
    flow = _flow(case, out)
    diagnosis = diagnose(case, out, notes, state)
    diagnosis["anomalies"] = anomalies
    if anomalies and not diagnosis.get("step"):
        diagnosis["step"] = anomalies[0]["step"]
        diagnosis["headline"] = ("It ended, but a step went wrong on the way: "
                                 + anomalies[0]["title"].rstrip(".").lower() + ".")
        diagnosis["causes"] = anomalies[0]["causes"] + diagnosis["causes"]
    return {"steps": out, "flow": flow, "diagnosis": diagnosis,
            "timeline": kept_steps,
            "notes": [{**n, "when": _clock(n["at"])} for n in notes],
            "kept_since": _clock(kept_since) if kept_since else "",
            "cost": round(sum(t["cost"] for t in every_turn), 4),
            "requests": sum(len(t["calls"]) for t in every_turn)}


# --- step by step: what each step was given, decided and put out, as kept ----------------------

#: Who does each kind of step, when the row itself does not say.
_WHO = {"route": "Rouh's code", "route_first": "Rouh's code", "files": "Rouh's code",
        "ledger": "Rouh's code", "decided": "You", "merged": "Rouh's code",
        "sent": "Rouh's code", "trouble": "Rouh's code", "word_check": "Word check"}

#: What each kind of kept row is called in the table.
_STEP_NAMES = {"reply_check": "Reply check", "status_check": "Reply status check",
               "word_review": "Word review", "route_first": "Route, first pass",
               "route": "Route", "files": "Files for the reply", "trouble": "Trouble",
               "sent": "Sent", "word_check": "Word check on the message",
               "ledger": "The ledger, ask by ask", "decided": "Your choices",
               "merged": "The same request again",
               "authorised": "What code allowed, ask by ask", "authority": "A call, checked"}


#: The purposes of the model calls that are checks, not a case's own turns.
_CHECKS = ("reply_check", "reply_status", old.REVIEW_PURPOSE)


def _model_at(turns: list, at: float, purposes=(), *, before: float = 1200) -> str:
    """The model of the request log's turn that ran just before `at`: of these purposes, or
    with none named, one of the case's own turns (not a check)."""
    got = [t for t in turns if (t.get("purpose") in purposes if purposes else
                                t.get("purpose") not in _CHECKS)
           and t["started"] <= at + 1 and at - t["started"] <= before]
    return max(got, key=lambda t: t["started"])["model"] if got else ""


def _decided_of_report(report: dict) -> dict:
    """What a report decided, in its own fields: the verdict and what it said came of it."""
    keep = ("outcome", "verified", "summary", "needs", "asks", "risks", "blocker")
    return {k: report[k] for k in keep if report.get(k) not in (None, "", [])}


def _word_check_rows(trail: list) -> dict:
    """The word check's matched words in one route's trail, by risk: {risk: [words]}."""
    out: dict = {}
    for t in trail or []:
        key = str(t.get("rule") or "")
        if key.startswith(("ask:", "risk:")) and "words in the email" in (t.get("where") or []):
            out[key.split(":", 1)[1]] = list(t.get("words") or [])
    return out


def timeline(traces: list, turns: list = ()) -> list[dict]:
    """Every step a case kept, in order, one row each: {at, who, step, given, decided, raw}.

    Petar, 11 October 2026: the case page shows, verbatim, what each step was
    given, what it decided and what it put out - the model's case_report input as
    it called the tool, the reply check's and the status check's answers, the word
    check's matched words and the word review's verdict, the route rule by rule -
    read from `mail_case_traces` alone, never rebuilt. A turn is one row with the
    report it made; a report with no turn kept is a row of its own.
    """
    rows: list[dict] = []
    traces = sorted(traces or [], key=lambda t: t["at"])
    turn_rows = [t for t in traces if t["kind"] == "turn"]
    used: set[int] = set()
    for t in traces:
        kind, data, at = t["kind"], t.get("data") or {}, float(t["at"] or 0)
        mode = t.get("mode") or ""
        if kind == "turn":
            nxt = next((u["at"] for u in turn_rows if u["at"] > t["at"]), float("inf"))
            rep = next((r for r in traces if r["kind"] == "report" and r.get("mode") == mode
                        and t["at"] - 1 <= r["at"] < nxt and id(r) not in used), None)
            if rep is not None:
                used.add(id(rep))
            report = ((rep or {}).get("data") or {}).get("report") or {}
            name = MODES.get(mode, (mode or "Turn", ""))[0]
            rows.append({
                "at": at, "step": f"{name}" + (f" (try {t.get('attempt')})"
                                               if (t.get("attempt") or 0) > 1 else ""),
                "who": _model_at(turns, float((rep or t)["at"])) or "Rouh's reading",
                "given": data.get("brief") or "",
                "decided": _decided_of_report(report) if report else
                "It never called case_report.",
                "raw": ((rep or {}).get("data") or {}).get("raw") or report or ""})
            continue
        if kind == "report":
            if id(t) in used:
                continue
            report = data.get("report") or {}
            rows.append({"at": at, "step": MODES.get(mode, (mode, ""))[0] + " report",
                         "who": _model_at(turns, at) or "Rouh's reading", "given": "",
                         "decided": _decided_of_report(report), "raw": data.get("raw") or report})
        elif kind == "reply_check":
            check = data.get("check") or {}
            applied = {k: v.get("sentence") or True for k, v in (check.get("risks") or {}).items()
                       if isinstance(v, dict) and v.get("applies")}
            rows.append({"at": at, "step": _STEP_NAMES[kind],
                         "who": check.get("model") or _model_at(turns, at, ("reply_check",))
                         or "Reply check",
                         "given": data.get("reply") or "",
                         "decided": ("Could not be checked: " + check["error"]
                                     if check.get("error") else applied or
                                     "Nothing the reply gives away."),
                         "raw": check.get("raw") or check})
        elif kind == "status_check":
            check = data.get("check") or {}
            rows.append({"at": at, "step": _STEP_NAMES[kind] + (" (corrected reply)"
                                                                 if mode.endswith("_corrected")
                                                                 else ""),
                         "who": check.get("model") or "Status check",
                         "given": {"reply": data.get("reply") or "",
                                   "records": data.get("facts") or {}},
                         "decided": {"claims": check.get("claims"),
                                     "by_words": data.get("floor") or [],
                                     "against_the_records": data.get("wrong") or [],
                                     **({"corrected": check["corrected"]}
                                        if check.get("corrected") else {})}
                         if not check.get("error") else "Could not be checked: " + check["error"],
                         "raw": check.get("raw") or check})
        elif kind == "word_review":
            review = data.get("review") or {}
            rows.append({"at": at, "step": _STEP_NAMES[kind] + (" (a try)" if mode == "trial"
                                                                 else ""),
                         "who": review.get("model_name") or review.get("model") or "Word review",
                         "given": data.get("flags") or [],
                         "decided": review.get("flags") if review.get("flags") is not None
                         else "Could not decide: " + str(review.get("error") or "no answer"),
                         "raw": review.get("raw") or review})
        elif kind in ("route", "route_first"):
            trail = data.get("trail") or []
            words = _word_check_rows(trail)
            if words and kind == "route_first" or (words and not any(
                    r["step"] == _STEP_NAMES["word_check"] and abs(r["at"] - at) < 30
                    for r in rows)):
                rows.append({"at": at - 0.001, "step": _STEP_NAMES["word_check"],
                             "who": "Word check",
                             "given": "The message's subject and body, outside what it quotes.",
                             "decided": {k: f"flagged: {', '.join(v)}" if v else
                                         "flagged by Rouh's reading too" for k, v in words.items()},
                             "raw": words})
            rows.append({"at": at, "step": _STEP_NAMES[kind], "who": "Rouh's code",
                         "given": {k: data[k] for k in ("contact", "inbox_once", "flags")
                                   if data.get(k) not in (None, "", [])},
                         "decided": {"route": data.get("route") or "",
                                     "reasons": data.get("reasons") or []},
                         "raw": trail})
        elif kind == "files":
            rows.append({"at": at, "step": _STEP_NAMES[kind], "who": f"Rouh's code, from {mode}"
                         if mode else "Rouh's code", "given": "",
                         "decided": ", ".join(str(f.get("name") or f.get("path") or "")
                                              for f in data.get("files") or []
                                              if isinstance(f, dict)),
                         "raw": data.get("files") or []})
        elif kind == "authorised":
            # What code authorised for each ask before the start ran (CAPABILITIES.md): their
            # words, the model that read them, what they were read as, and the authority.
            reading = data.get("reading") or {}
            rows.append({"at": at, "step": _STEP_NAMES[kind], "who": "Rouh's code",
                         "given": {"read by": reading.get("served_model") or
                                   reading.get("model") or "",
                                   "asks": [{"words": a.get("quote"),
                                             "read as": a.get("capability"),
                                             "on": a.get("scope") or [],
                                             "values": a.get("values") or {}}
                                            for a in data.get("asks") or []]},
                         "decided": [{"capability": x.get("capability"),
                                      "version": x.get("version"),
                                      "authority": x.get("ref"),
                                      "scope": x.get("scope"), "limits": x.get("limits"),
                                      "why": x.get("reason")}
                                     for x in data.get("authorized") or []] or
                         "Nothing: no ask of it was allowed.",
                         "raw": data})
        elif kind == "authority":
            rows.append({"at": at, "step": _STEP_NAMES[kind] + f": {data.get('tool')}",
                         "who": "Rouh's code",
                         "given": {"arguments": data.get("args") or {},
                                   "capability": data.get("capability") or "",
                                   "authority": data.get("ref") or ""},
                         "decided": ("allowed" if data.get("allowed") else "refused")
                         + (f", {data.get('claim')}" if data.get("claim") else "")
                         + f": {data.get('reason') or ''}",
                         "raw": data})
        elif kind == "trouble":
            rows.append({"at": at, "step": _STEP_NAMES[kind] + (f" in {mode}" if mode else ""),
                         "who": "Rouh's code", "given": "",
                         "decided": data.get("trouble") or "", "raw": data})
        elif kind == "ledger":
            asks = [a for a in data.get("asks") or [] if isinstance(a, dict) and not a.get("gone")]
            rows.append({"at": at, "step": _STEP_NAMES[kind], "who": "Rouh's code",
                         "given": {"grants held": data.get("held") or [],
                                   "asks": [{"ask": a.get("quote"), "grant": a.get("grant"),
                                             "new_grant": (a.get("new_grant") or {}).get("name"),
                                             "hard_limit": a.get("hard_limit"),
                                             "your choice": a.get("choice")} for a in asks]},
                         "decided": {a.get("quote", "")[:120]: f"{a.get('status')}: {a.get('why')}"
                                     for a in asks},
                         "raw": data})
        elif kind == "decided":
            rows.append({"at": at, "step": _STEP_NAMES[kind], "who": "You",
                         "given": data.get("choices") or {},
                         "decided": "Run now" if data.get("run") else "Saved; Redo runs it",
                         "raw": data})
        elif kind == "merged":
            rows.append({"at": at, "step": _STEP_NAMES[kind], "who": "Rouh's code",
                         "given": data.get("why") or "", "decided": f"Part of {data.get('into')}",
                         "raw": data})
        elif kind == "sent":
            rows.append({"at": at, "step": _STEP_NAMES[kind] + (f": {mode}" if mode else ""),
                         "who": "Rouh's code",
                         "given": data.get("text") or "",
                         "decided": (f"Sent to {data.get('to_name') or data.get('to') or 'them'}"
                                     f" by {data.get('channel') or 'email'}" if data.get("ok")
                                     else "Not sent: " + str(data.get("error") or "")),
                         "raw": data})
        else:
            rows.append({"at": at, "step": kind.replace("_", " ").capitalize()
                         + (f" ({mode})" if mode else ""),
                         "who": _WHO.get(kind, "Rouh's code"), "given": "", "decided": "",
                         "raw": data})
    rows.sort(key=lambda r: r["at"])
    return rows


#: A report's fields, in the order the page shows them, with what each is.
REPORT_FIELDS = (
    ("outcome", "Verdict", ""),
    ("verified", "Verified", "verified"),
    ("summary", "What they want, as read", ""),
    ("needs", "What it takes", "levels"),
    ("inbox_scope", "How far into your inbox", ""),
    ("inbox_from", "Senders or labels", ""),
    ("inbox_search", "The search it needs", ""),
    ("risks", "Risks it named", ""),
    ("addressed_to_rouh", "Written to Rouh", ""),
    ("checked", "What it looked at", ""),
    ("evidence", "Evidence", ""),
    ("blocker", "What stops it", "blocked"),
    ("proposed_action", "Proposed action", ""),
    ("job_id", "Job", ""),
    ("reply", "The reply", ""),
    ("decline_reply", "The polite decline", ""),
    ("prepares", "Make it first", ""),
    ("reply_files", "Files for the reply", ""),
)


def _need_said(need) -> dict:
    """One of a report's needs as the page shows it.

    Until 11 October 2026 a need was a grant's word ("inbox"); since the mail ledger a work
    report's need is {"what", "ask", "need"}: a sentence, the ask it serves, and the grant or
    hard limit it needs, empty for the owner's own decision (`mail_cases.CaseDesk._report_of`).
    """
    if isinstance(need, str):
        return {"key": need, "name": old.need_name(need), "tip": GLOSSARY.get(need, "")}
    key = str(need.get("need") or "")
    return {"key": key, "what": " ".join(str(need.get("what") or "").split()),
            "name": (f"Hard limit: {key}" if key in grants.HARD_LIMITS else
                     old.need_name(key) if key else "Your own decision"),
            "tip": grants.HARD_LIMITS.get(key) or GLOSSARY.get(key, "")}


def _annotate(step: dict) -> None:
    """Names and explanations the page shows beside a step's raw values."""
    report = step.get("report")
    if isinstance(report, dict) and report:
        rows = []
        for key, label, tip in REPORT_FIELDS:
            value = report.get(key)
            if value in (None, "", []) and key not in ("outcome",):
                continue
            if key == "needs":
                value = [_need_said(v) for v in value or [] if isinstance(v, (str, dict))]
            elif key == "risks":
                value = [{"key": v, "name": v.replace("_", " "),
                          "tip": old.RISKS.get(v, "") or ", ".join(
                              old.RISKS.get(p, p) for p in old.RISK_ALIASES.get(v, ()))}
                         for v in value or []]
            elif key == "inbox_scope":
                value = trust.INBOX_SCOPES.get(value, (value,))[0]
            elif key == "inbox_from":
                value = ", ".join(value or [])
            elif key == "reply_files":
                value = [{"key": v.get("sha256", ""), "name": v.get("name") or v.get("path"),
                          "tip": v.get("rel") or v.get("path") or ""}
                         for v in value or [] if isinstance(v, dict)]
            elif isinstance(value, bool):
                value = "yes" if value else "no"
            if key == "outcome":
                tip = str(value or "")
            rows.append({"key": key, "label": label, "value": value,
                         "tip": GLOSSARY.get(tip, "") if tip else "", "tip_key": tip,
                         "list": isinstance(value, list),
                         "lines": isinstance(value, list) and any(v.get("what") for v in value),
                         "long": key in (
                             "checked", "evidence", "blocker", "proposed_action", "reply",
                             "decline_reply")})
        step["report_rows"] = rows
        step["report_json"] = json.dumps(report, indent=2, ensure_ascii=False)
    outcome = str((report or {}).get("outcome") or "") if isinstance(report, dict) else ""
    step["verdict_key"] = "verified" if step.get("kind") == "verify" else outcome
    step["verdict_tip"] = GLOSSARY.get(step["verdict_key"], "")
    for key in ("trail", "replay"):
        for rule in step.get(key) or []:
            name = str(rule.get("rule") or "")
            rule["name"] = (RULES.get(name) or
                            (_risk_name(name) if name.startswith(("risk:", "ask:", "reply:"))
                             else "Ask " + name[4:] if name.startswith("ask#") else name))
            rule["mark"] = {True: "pass", False: "stop", None: "note"}[rule.get("ok")]
    if step.get("kind") == "route":
        step["route_tip"] = GLOSSARY.get(step.get("route") or "", "")
    kept = step.get("kept") or {}
    contact = kept.get("contact") or {}
    if contact:
        step["levels_then"] = [{"key": k, "name": trust.LEVELS.get(k, (k,))[0],
                                "tip": GLOSSARY.get(k, "")} for k in contact.get("levels") or []]
    level_tools = set(kept.get("level_tools") or [])
    step["tools"] = [{"name": n, "level": n in level_tools,
                      "case": n in mail_turn.CASE_ONLY}
                     for n in step.get("tools_offered") or []]
    if step.get("approval"):
        step["approval"]["tip"] = GLOSSARY.get(step["approval"]["status"], "")


def _anomalies(case, steps: list[dict]) -> list[dict]:
    """Things in the steps that should not have happened, even in a case that ended well."""
    out = []
    since_route = None
    worked = False
    for step in steps:
        if step["kind"] == "route" and step.get("route") in ("granted",):
            since_route, worked = step, False
        elif step["kind"] == "decided" and "Rouh is doing it" in step.get("summary", ""):
            since_route, worked = step, False
        elif step["kind"] == "carry_out":
            worked = True
        elif step["kind"] == "verify" and since_route is not None and not worked:
            step["status"] = "warn" if step["status"] == "good" else step["status"]
            step["anomaly"] = ("No work turn ran in this round: the check was handed the work "
                               "report of an earlier round.")
            out.append({"step": step["id"], "title": "The work was skipped in this round",
                        "plain": step["anomaly"],
                        "causes": [_cause(
                            "code", "An earlier round's report was taken as this round's",
                            "_after_turn takes a report already on the case as this turn's. A "
                            "case read again from the start has to forget every turn's report "
                            "(_FRESH, fixed on 1 October 2026 in 1e6ba3bb). If this happened "
                            "after that fix, look for another path that moves a case back "
                            "without clearing assessment and work_report.", ["desk"],
                            likely=True)]})
            since_route = None
    for step in steps:
        if step["kind"] in MODES and not step.get("report") and step.get("turns"):
            out.append({"step": step["id"], "title": "A turn ended without a report",
                        "plain": "The model never called case_report in this turn.",
                        "causes": [_cause("prompt", "The turn did not report",
                                          "Read its transcript for why it stopped.",
                                          ["case_report", "desk"], likely=True)]})
    return out


def _approval(a, key: str = "") -> dict:
    return {"id": a.id, "status": a.status, "asked": _clock(a.asked_at),
            "decided": _clock(a.decided_at), "asked_at": a.asked_at, "decided_at": a.decided_at, "why_invalid": a.why_invalid,
            "instruction": a.instruction, "action": a.proposed_action,
            "reply": a.decided_reply or a.proposed_reply, "edited": a.edited,
            "immediate": getattr(a, "immediate_reply", "") or "",
            "files": files_shown(a.files or [], key)}


def _sentence(text: str) -> str:
    text = text.strip()
    return text[:1].upper() + text[1:]


def files_shown(files, key: str) -> list[dict]:
    """A step's files as one line each, with a link that opens the file while it is the same."""
    out = []
    for one in case_files.now([f for f in files or [] if isinstance(f, dict)]):
        out.append({"name": one.get("name"), "path": one.get("rel") or one.get("path"),
                    "kind_said": mail_attachments.kind_said(one.get("type"), one.get("name")),
                    "size_said": mail_attachments.size_said(one.get("size")),
                    "url": case_files.link(key, one), "removed": bool(one.get("removed")),
                    "gone": one["missing"] or one["changed"]})
    return out


def _reply_check_view(row: dict | None, check_turns: list) -> dict | None:
    """The reply check that fed a route, with its model call, for the Route card."""
    if row is None:
        return None
    check = (row.get("data") or {}).get("check") or {}
    turn = max((t for t in check_turns if t["started"] <= row["at"] + 1),
               key=lambda t: t["started"], default=None)
    if turn is not None and row["at"] - turn["started"] > old.REPLY_CHECK_SECONDS + 30:
        turn = None
    return {"model": (turn or {}).get("model") or check.get("model") or "",
            "effort": check.get("effort") or "", "error": check.get("error") or "",
            "calls": (turn or {}).get("calls") or [], "cost": (turn or {}).get("cost") or 0,
            "applied": [k for k, v in (check.get("risks") or {}).items()
                        if isinstance(v, dict) and v.get("applies")]}


def _review_call(row: dict, turns: list) -> dict | None:
    """The model call one word review made, from the request log."""
    turn = max((t for t in turns if t["started"] <= row["at"] + 1),
               key=lambda t: t["started"], default=None)
    if turn is not None and row["at"] - turn["started"] > old.REVIEW_SECONDS + 30:
        return None
    return turn


def _review_view(row: dict, turns: list) -> dict:
    """One word review as its step shows it: each flag with its verdict, and its call."""
    data = row.get("data") or {}
    review = data.get("review") or {}
    verdicts = review.get("flags") if isinstance(review.get("flags"), dict) else None
    flags = []
    for f in data.get("flags") or []:
        risk = str(f.get("risk") or "")
        got = (verdicts or {}).get(risk) if verdicts is not None else None
        risky = got.get("risky") if isinstance(got, dict) else None
        flags.append({"risk": risk, "name": _risk_name(risk), "words": f.get("words") or [],
                      "sentences": f.get("sentences") or [],
                      "verdict": ("false alarm" if risky is False else "still risky" if risky
                                  else "not judged"),
                      "tone": "good" if risky is False else "bad" if risky else "warn",
                      "why": str((got or {}).get("why") or "")})
    turn = _review_call(row, turns)
    upheld = [f for f in flags if f["tone"] != "good"]
    return {"flags": flags, "upheld": upheld, "overruled": len(flags) - len(upheld),
            "model": review.get("model") or "", "model_name": review.get("model_name") or "",
            "effort": review.get("effort") or "", "custom": bool(review.get("custom")),
            "prompt": review.get("prompt") or "", "error": review.get("error") or "",
            "raw": review.get("raw") or "", "calls": (turn or {}).get("calls") or [],
            "cost": (turn or {}).get("cost") or 0, "when": _clock(row["at"]),
            "ms": (turn or {}).get("ms") or 0}


def _review_step(row: dict, turns: list, trials: list) -> dict:
    """The word review's step: what it was given, what it decided, its call, and the tries
    made since with the settings of the day."""
    view = _review_view(row, turns)
    flags, upheld = view["flags"], view["upheld"]
    if view["error"] and not any(f["tone"] != "warn" for f in flags):
        summary, status = "Could not decide, so every flag stands: " + view["error"], "warn"
    elif not upheld:
        summary, status = (f"{view['model_name']}: every flag a false alarm, so the word "
                           "check was overruled."), "good"
    else:
        summary = (f"{view['model_name']} upheld " + ", ".join(f["name"] for f in upheld)
                   + ("; overruled " + ", ".join(f["name"] for f in flags if f["tone"] ==
                                                  "good") if view["overruled"] else "") + ".")
        status = "warn"
    return {"status": status, "summary": summary, "review": view,
            "what": PIPELINE[[k for k, _n, _w in PIPELINE].index("word_review")][2],
            # A review costs a fraction of a cent, which the head's three places
            # would show as nothing; the call's own panel has it to five.
            "cost": round(view["cost"], 4) if view["cost"] >= 0.001 else 0,
            "trials": [_review_view(t, turns) for t in trials if t["at"] > row["at"]]}


def _first_route_step(case, report: dict, row: dict, contact_now, *,
                      check_row: dict | None = None, check_turns: list = ()) -> dict:
    """The route's first pass, with the word check's flags standing: what went to the word
    review. Kept as it ran; the route it went back to is the step after the review."""
    data = row.get("data") or {}
    trail = [dict(t) for t in data.get("trail") or []]
    flags = [str(f) for f in data.get("flags") or []]
    name = case.sender_name or case.sender
    implicit = contact_now.implicit if contact_now is not None else not case.contact_id
    _explain(trail, case, report, name, implicit)
    _conclude(trail, data.get("route") or "", report)          # takes its route row out
    for t in trail:
        if str(t.get("rule") or "").split(":", 1)[-1] in flags and \
                str(t.get("rule") or "").startswith("ask:") and t.get("ok") is False:
            t["then"] = "Raised by the word check alone, so the word review judges it next."
    others = [t for t in trail if t.get("ok") is False and not (
        str(t.get("rule") or "").startswith("ask:")
        and str(t.get("rule")).split(":", 1)[1] in flags)]
    names = ", ".join(_risk_name(f) for f in flags)
    conclusion = {
        "route": "word_review", "value": "To the word review", "means": "", "tone": "warn",
        "by": "What they ask",
        "why": (f"Only the word check flagged {names}, so the word review judges "
                f"{'them' if len(flags) > 1 else 'it'} and the route runs again with its "
                "verdicts.") + (" Other rules stopped it too, so it waits for you whatever the "
                                "review says." if others else "")}
    return {"status": "warn", "route": "word_review", "reasons": data.get("reasons") or [],
            "checks": data.get("checks") or [], "trail": trail, "replay": [],
            "route_now": "", "source": "kept", "first_pass": True,
            "trail_groups": grouped(every_check(trail, report, at=float(row.get("at") or 0))),
            "replay_groups": [], "reply_check": _reply_check_view(check_row, check_turns),
            "conclusion": conclusion, "conclusion_now": {},
            "summary": "First pass: the word check's own flags go to the word review."}


def _ledger_step(row: dict, case) -> dict:
    """The ledger as a reading left it, ask by ask (`mail_ledger`): each ask's words, the grant
    the reading mapped it to, and the status Rouh's code gave it from the grants, with why."""
    from . import mail_ledger as ledger

    asks = [ledger.Ask.of(a) for a in (row.get("data") or {}).get("asks") or []
            if isinstance(a, dict)]
    live = ledger.live(asks)
    waits = [a for a in live if a.status == ledger.WAITING]
    return {"status": "warn" if waits else "good", "route": "ledger",
            "summary": ledger.why_line(live),
            "asks": [{**a.as_dict(), "words": ledger.WORDS.get(a.status, a.status),
                      "tone": ledger.TONES.get(a.status, "")} for a in live],
            "held_grants": (row.get("data") or {}).get("held") or []}


def _route_step(case, report: dict, row: dict | None, contact_now, r: dict, *,
                check_row: dict | None = None, check_turns: list = (),
                review_row: dict | None = None) -> dict:
    """The route a reading got before 11 October 2026, rule by rule, as kept or as stored on the
    case. Since then a case is judged from its ledger (`mail_ledger`), and these old rules are
    shown as they ran, never run again."""
    replay: list = []
    route_now = ""
    if row is not None:
        data = row["data"]
        route, reasons, checks, trail, source = (data.get("route"), data.get("reasons") or [],
                                                 data.get("checks") or [],
                                                 data.get("trail") or [], "kept")
    elif r.get("last_assess"):
        route, reasons, checks, trail, source = case.route, case.reasons or [], \
            case.checks or [], [], "case"
    else:
        route, reasons, checks, trail, source = (r.get("route_then", ""),
                                                 r.get("reasons_then") or [], [], [], "events")
    if not route and route_now:
        route = route_now
    # A request only beyond the grant, from a contact set to have those
    # declined, was declined after this route (`CaseDesk._decline`).
    declined_then = ((case.reasons or [""])[0] or "Beyond what you granted, and you set such "
                     "requests to be declined politely.") \
        if r.get("last_assess") and case.route in ("declined", "declined_quiet") else ""
    declined_now = ""
    name = case.sender_name or case.sender
    implicit = contact_now.implicit if contact_now is not None else not case.contact_id
    trail = trail or []
    _explain(trail, case, report, name, implicit)
    _explain(replay, case, report, name, implicit)
    conclusion = _conclude(trail, route or "", report, declined_why=declined_then)
    conclusion_now = _conclude(replay, route_now, report, declined_why=declined_now)
    status = conclusion.get("tone", "")
    return {"status": status, "route": route or "?", "reasons": reasons, "checks": checks,
            "trail": trail, "replay": replay, "route_now": route_now, "source": source,
            "trail_groups": grouped(every_check(trail, report, at=float(
                (row or {}).get("at") or report.get("at") or case.created_at or 0))),
            "replay_groups": grouped(every_check(replay, report)),
            "reply_check": _reply_check_view(check_row, check_turns),
            "conclusion": conclusion, "conclusion_now": conclusion_now,
            "summary": "" if route else "The route this reading got was not kept."}


#: Steps that start the case over rather than run in a stage: each begins a pass.
RESTARTS = ("reread", "redo", "instruction")

#: The chart's geometry, in pixels: a lane's height, the pass headers above the
#: lanes, a step's column, the column of a step that waited on the owner, a pass's
#: narrowest band, the gap between bands, and the rail of notes under the lanes.
LANE_H, HEAD_H, COL_W, WAIT_W, BAND_MIN, BAND_GAP, RAIL_H = 30, 58, 30, 96, 132, 6, 66


def _words(text: str, most: int = 6) -> str:
    words = " ".join(str(text or "").split()).split(" ")
    out = " ".join(words[:most]).rstrip(".,;:")
    return out + ("\u2026" if len(words) > most else "")


def _when_short(ts: float) -> str:
    from . import clock

    if not ts:
        return ""
    moment = clock.moment(ts)
    return f"{moment.day} {moment:%b %H:%M}"


def _pass_start(step: dict, before: list[dict]) -> tuple[str, str]:
    """What started a pass, in a few words, and in full, from the step that started it."""
    said = " ".join(str(step.get("summary") or "").split())
    kind = step["kind"]
    if kind == "received":
        what = mc.CHANNELS.get(step.get("channel") or "email", ("Message",))[0]
        return f"{what} arrived", f"The {what.lower()} arrived, and its case was opened."
    if kind == "redo":
        lapsed = any(str(l.get("said", "")).startswith("The approval expired")
                     for s in before[-1:] for l in s.get("log") or [])
        said = said if said.startswith("Redo") else "Redo: " + said
        told = re.search(r"with your instructions: (.+?)\. Attempt \d+ is kept", said)
        short = "Redo after your decision lapsed" if lapsed else "Redo"
        if told:
            short += ": " + _words(told.group(1))
        return short, said
    if said.startswith(old.REREAD_SAID):
        who = re.search(r"what (.+?) may do", said)
        return f"You changed what {who.group(1) if who else 'they'} may do", said
    if said.startswith(old.REPREPARE_SAID):
        return "Read again to make it first", said
    told = re.match(r"You gave Rouh further instructions: (.+)", said)
    if told:
        return "You told Rouh: " + _words(told.group(1)), said
    again = re.match(r"You asked Rouh to ([^:.(]+)(.*)$", said)
    if again:
        what, note = again.group(1).strip(), again.group(2).strip().removeprefix(":").strip()
        note = note.removesuffix(".").removeprefix("(").removesuffix(")")
        what = "Try again" if what == "look at it again" else "You asked Rouh to " + what
        return what + (": " + _words(note) if note else ""), said
    if said.startswith("You let Rouh read your inbox"):
        return "You let Rouh read your inbox", said
    return _words(said, 8) or step.get("title") or "Started again", said


def _outcome(step: dict) -> str:
    """A step's outcome in a few words, for its dot's hover."""
    kind = step["kind"]
    if kind == "received":
        return step.get("identity_line") or "received"
    if kind in MODES:
        return step.get("verdict") or "no report"
    if kind == "word_review":
        return _words(step.get("summary") or "word review", 10)
    if kind == "route":
        c = step.get("conclusion") or {}
        return (c.get("value") or step.get("route") or "?").lower()
    if kind == "approval":
        a = step.get("approval") or {}
        return {"pending": "waiting on you", "approved": "approved", "declined": "declined",
                "instructed": "you gave instructions", "superseded": "withdrawn",
                "dismissed": "dismissed",
                "expired": "lapsed"}.get(a.get("status", ""), a.get("status") or "asked you")
    return _words(step.get("summary") or step.get("title") or "", 8)


def _span(seconds: float) -> str:
    """How long, the way a person says it: 12m, 5h 40m, 2d 3h."""
    minutes = max(1, round(float(seconds or 0) / 60))
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def _hm(ts: float) -> str:
    from . import clock

    return f"{clock.moment(ts):%H:%M}" if ts else ""


#: What became of a decision Rouh asked for, by its approval's status
#: (`CaseStore.settle` and `CaseStore.void` are the only writers): the bell's
#: colour, and what it says. Superseded and expired were never decided by
#: the owner: a newer email in the thread, a new proposal, the contact's permissions
#: or a file changing, or Redo; why_invalid says which. Expired is history only:
#: the 48-hour limit approvals had until 8 October 2026, whose lapses were all
#: dismissed that day (migration 0106).
DECIDED = {
    "pending": ("wait", "Waiting on you"),
    "approved": ("approved", "You approved it"),
    "declined": ("declined", "You declined it"),
    "instructed": ("instructed", "You told Rouh to do something else"),
    "superseded": ("void", "It stopped holding before you decided"),
    "expired": ("void", "It ran out of time, under the old 48-hour limit"),
    "dismissed": ("void", "Dismissed"),
}


def _notes_sent(case) -> list[str]:
    """Every note that reached the owner's phone about this email, word for word, oldest first.

    The mail log keeps them one after another (`CaseDesk._seen`, `MailAlerts.happened`).
    """
    from .models import MailAlertSeen

    row = (MailAlertSeen.objects.filter(user_id=case.user_id, org_id=case.org_id,
                                        message_id=case.message_id).values("note").first())
    return [n.strip() for n in ((row or {}).get("note") or "").split("\n\n") if n.strip()]


def _told(case, steps: list[dict]) -> list[dict]:
    """The notes Rouh sent the owner about the case, as the case wrote them down.

    It asks him by Telegram when a decision waits (`CaseDesk._awaiting`), tells
    him once at the end (`_notify`), and when the case stops (`_block`, which
    writes no event of its own: its note is found in the mail log). A note that
    could not go is kept too, with why.
    """
    notes = _notes_sent(case)
    asks = [n for n in notes if n.startswith("Rouh needs your decision")]
    ends = [n for n in notes if n.startswith("Rouh finished")]
    stops = [n for n in notes if n.startswith("Rouh could not finish")]
    out: list[dict] = []
    approval = None
    for step in steps:
        kind, said = step["kind"], " ".join(str(step.get("summary") or "").split())
        if kind == "approval":
            approval = step
        if kind == "notify":
            ask = said.startswith(("You were sent a note with the link to decide",
                                   "No note could go to your phone"))
            if not ask and not said.startswith(("You were told", "Done; no note")):
                continue
            went = said.startswith(("You were sent a note", "You were told"))
            pool = asks if ask else ends
            text = pool.pop(0) if went and pool else (
                case.notified_text if went and not ask and not pool else "")
            out.append({"id": step["id"], "kind": "ask" if ask else "done", "at": step["at"],
                        "went": went, "why_not": "" if went else said.split(": ", 1)[-1],
                        "text": text, "approval": approval if ask else None,
                        "step": step["id"], "mark": True})
        elif kind == "blocked":
            why = said[:100]
            text = next((n for n in stops if n.split("'s email: ", 1)[-1][:100] == why[:100]
                         or n.split("'s email: ", 1)[-1].startswith(why[:60])), None)
            if text is None:
                continue
            stops.remove(text)
            out.append({"id": "told-" + step["id"], "kind": "stop", "at": step["at"],
                        "went": True, "why_not": "", "text": text, "approval": None,
                        "step": step["id"], "about": step["id"], "mark": False})
    return out


def _bell(note: dict, now: float) -> dict:
    """One note as its bell: status, the words under it, its hover and its card."""
    title = {"ask": "Asked you", "done": "Done", "stop": "Stopped"}[note["kind"]]
    step = note["approval"] or {}
    a = step.get("approval") or {}
    status, decision = ("told", "")
    decided, why, waited = "", "", ""
    if note["kind"] == "ask":
        status, decision = DECIDED.get(a.get("status", ""), ("void", a.get("status") or ""))
        if a.get("status") in ("approved", "declined", "instructed") and a.get("decided_at"):
            decided = a.get("decided") or ""
            waited = _span(a["decided_at"] - (a.get("asked_at") or note["at"]))
        elif a.get("status") == "pending":
            waited = _span(now - (a.get("asked_at") or note["at"]))
        why = a.get("why_invalid") or ""
    where = ("Your phone, by Telegram" if note["went"] else
             "Nothing reached your phone: " + (note["why_not"] or "it could not be sent"))
    line = f"{title}, {_when_short(note['at'])}, " + ("by Telegram" if note["went"] else
                                                       "not sent: " + note["why_not"])
    if decision:
        line += ". " + decision + (f" {_hm(a.get('decided_at'))}" if decided else "") + \
            (f", after {waited}" if decided and waited else "") + \
            (f", {waited} so far" if status == "wait" and waited else "") + \
            (f": {why}" if status == "void" and why else "")
    return {"id": note["id"], "kind": note["kind"], "status": status, "title": title,
            "label": f"{title}, {_hm(note['at'])}", "hover": line, "when": _clock(note["at"]),
            "went": note["went"], "where": where, "text": note["text"],
            "decision": decision, "decided": decided, "why": why, "waited": waited,
            "instruction": a.get("instruction") or "", "ask_step": step.get("id", ""),
            "step": note["step"], "mark": note["mark"],
            "title_long": {"ask": "Asked you to decide", "done": "Told you it was done",
                           "stop": "Told you it stopped"}[note["kind"]]}


def _position_passes(passes: list, waiting: bool, current: str) -> float:
    """Place each pass and its dots, allowing a wider column for a wait."""
    x = 0
    for p in passes:
        offsets, inner = [], 0.0
        for dot in p["dots"]:
            offsets.append(inner)
            inner += WAIT_W if dot.get("wait") else COL_W
        width = max(inner + 2 * 10 + (12 if p["dots"] and p["dots"][-1].get("wait") else 0),
                    BAND_MIN)
        first = x + (width - inner) / 2
        for dot, off in zip(p["dots"], offsets):
            dot["x"] = round(first + off + COL_W / 2, 1)
            dot["y"] = HEAD_H + dot["lane"] * LANE_H + LANE_H / 2
            dot["slot_end"] = round(first + off + (WAIT_W if dot.get("wait") else COL_W), 1)
        p.update(x=x, width=width, right=x + width, now=p is passes[-1],
                 waiting=waiting and p is passes[-1], current=p["start"] == current)
        x += width + BAND_GAP
    width = max(x - BAND_GAP, 0)

    return width


def _flow_links(steps: list, passes: list, dots: list) -> tuple[list, list, dict]:
    """Draw waits and the links that explain restarts, reviews and failed checks."""
    segs, waits = [], []
    by_step = {s["id"]: s for s in steps}

    def curve(x1, y1, x2, y2) -> str:
        mid = round((x1 + x2) / 2, 1)
        return f"M{x1} {y1} C{mid} {y1} {mid} {y2} {x2} {y2}"

    for i, a in enumerate(dots):
        b = dots[i + 1] if i + 1 < len(dots) else None
        start = a["x"]
        if a.get("wait"):
            if b is None or a["wait"]["open"]:
                end = passes[a["pass"] - 1]["right"] - 6
            elif b["pass"] == a["pass"] and b["lane"] == a["lane"]:
                end = b["x"] - 10
            else:
                end = a["slot_end"] - 8
            waits.append({"d": f"M{a['x'] + 10} {a['y']} H{end}", "open": a["wait"]["open"],
                          "label": a["wait"]["label"], "x": a["x"] + 12,
                          "y": a["y"] - 9})
            start = end
        if b is None:
            continue
        kind, why = "", ""
        if b["pass"] != a["pass"]:
            kind, why = "restart", passes[b["pass"] - 1]["said"]
        elif b["lane"] < a["lane"] and by_step[a["step"]]["kind"] == "word_review":
            # The word review's verdicts go back to the route, which runs again.
            kind = "review " + (by_step[a["step"]].get("status") or "warn")
            why = "Back to the route with the word review's verdicts: " + _words(
                by_step[a["step"]].get("summary") or "", 14)
        elif b["lane"] < a["lane"]:
            # Sent back: a check in this pass failed before the climb.
            mine = [by_step[d["step"]] for d in passes[a["pass"] - 1]["dots"]
                    if d["n"] <= a["n"]]
            failed = next((s for s in reversed(mine) if s["status"] == "bad" and
                           s["kind"] in ("verify", "prepare_failed", "followjob")), None)
            if failed is not None:
                kind = "back"
                if by_step[a["step"]]["kind"] in ("handoff", "followjob"):
                    why = "Checked again after it was handed on, because the check failed"
                elif failed["kind"] == "verify":
                    why = "The check sent it back: " + _words(
                        failed.get("said_out") or failed.get("verdict"), 14)
                elif failed["kind"] == "prepare_failed":
                    why = "Making it first failed, so it came back to you"
                else:
                    why = "The server job did not do it"
        if start != a["x"] and b["y"] == a["y"] and not kind:
            continue  # The wait itself reaches the next dot.
        segs.append({"d": curve(start, a["y"], b["x"], b["y"]), "kind": kind, "why": why})

    return segs, waits, by_step


def _flow_bells(case, steps: list, dots: list, before: dict, by_step: dict,
                now: float) -> tuple[float, list]:
    """Place each notification under its step and mark the card that belongs to it."""
    # The rail: a bell for every note, under the step it was about.
    rail_top = HEAD_H + len(PIPELINE) * LANE_H + 8
    bell_y = rail_top + 20
    dot_of = {d["step"]: d for d in dots}
    bells, taken, ends = [], {}, [-1e9, -1e9]
    for note in _told(case, steps):
        about = note.get("about") or (note["approval"] or {}).get("id") or \
            before.get(note["id"], "")
        dot = dot_of.get(about) or (dots[-1] if dots else None)
        if dot is None:
            continue
        bell = _bell(note, now)
        nudge = taken.get(dot["step"], 0)
        taken[dot["step"]] = nudge + 1
        bell.update(x=round(dot["x"] + nudge * 14, 1), y=bell_y, about=dot["step"],
                    from_y=dot["y"] + 10, current=False)
        half = len(bell["label"]) * 2.9 + 4
        row = 0 if bell["x"] - half > ends[0] + 4 else 1 if bell["x"] - half > ends[1] + 4 else 0
        ends[row] = bell["x"] + half
        bell["label_y"] = bell_y + 24 + row * 13
        bells.append(bell)
        if bell["id"] in by_step:
            by_step[bell["id"]]["bell"] = True  # Its card is the bell's, not a step's.

    return rail_top, bells


def _flow(case, steps: list[dict]) -> dict:
    """The swim-lane chart: one lane per stage, one dot per step, the passes behind them.

    Time runs left to right, one column per step in the order they happened.
    A step that starts the case over (`RESTARTS`) is no dot but the head of a
    new pass. A line joins the dots; where it climbs back to an earlier lane
    the case looped, and the segment says why: started over (a restart), or
    sent back by a check that failed in that pass. A climb with neither is the
    case's ordinary path (made first, then asked), drawn plain. A wait on
    the owner is a flat dotted stretch in Your decision, as long as it waited, and
    every note sent to them is a bell on the rail under the lanes, under the
    step it was about (Petar, 2 October 2026: a note is not a stage, and a
    lane for them made the case look as if it told him before it worked).
    """
    now = time.time()
    order = [key for key, _n, _w in PIPELINE]
    lane_of = {key: i for i, key in enumerate(order)}
    passes: list[dict] = []
    dots: list[dict] = []
    before: dict[str, str] = {}
    by_id = {s["id"]: s for s in steps}
    for n, step in enumerate(steps, 1):
        step["n"] = n
        if step["kind"] in RESTARTS or not passes:
            short, full = _pass_start(step, steps[:n - 1])
            passes.append({"n": len(passes) + 1, "start": step["id"], "label": short,
                           "said": full, "when": _when_short(step["at"]), "dots": []})
            if step["kind"] in RESTARTS:
                continue
        if step["kind"] == "notify":
            before[step["id"]] = dots[-1]["step"] if dots else ""
            continue
        if step["kind"] == "decided":
            # One dot per decision (Petar, 2 October 2026): his answer is the ask's
            # own dot, its card holds both, and the wait runs on from it.
            ask = next((d for d in reversed(passes[-1]["dots"]) if d.get("approval")), None)
            if ask is not None and not ask.get("decided"):
                ask["decided"] = step["id"]
                by_id[ask["step"]]["decision_step"] = step
                step["merged_into"] = ask["step"]
                continue
        lane = lane_of.get(step["stage"])
        if step["kind"] == "files" and dots and dots[-1]["lane"] == lane_of["verify"]:
            lane = lane_of["verify"]
        if lane is None:  # Blocked, and anything else with no stage: where it stopped.
            lane = dots[-1]["lane"] if dots else 0
        dot = {"step": step["id"], "n": n, "lane": lane, "pass": len(passes),
               "run": step["run"], "status": step["status"], "at": step["at"],
               "counts": step["kind"] != "blocked", "tip": step.get("icon_tip", ""),
               "label": f"{n} {'Blocked' if step['kind'] == 'blocked' else PIPELINE[lane][1]}: "
                        f"{_outcome(step)}"}
        if step["kind"] == "approval" and step.get("approval"):
            a = step["approval"]
            dot["approval"] = a
            tone, words = DECIDED.get(a["status"], ("void", a["status"]))
            dot["status"] = {"wait": "warn", "approved": "good", "declined": "bad",
                             "instructed": "info"}.get(tone, "")
            dot["asking"] = tone == "wait"
            dot["label"] = f"{n} Your decision: {words}" + (
                f": {a['why_invalid'].rstrip('.')}" if tone == "void" and a.get("why_invalid")
                else "")
            dot["tip"] = _icon_tip(step["run"], dot["status"])
        dots.append(dot)
        passes[-1]["dots"].append(dot)

    # How long each ask waited on the owner: to their decision, to whatever took its
    # place, or, while they have not decided, until now.
    for i, dot in enumerate(dots):
        a = dot.get("approval")
        if not a:
            continue
        asked = a.get("asked_at") or dot["at"]
        nxt = dots[i + 1] if i + 1 < len(dots) else None
        if a["status"] == "pending":
            dot["wait"] = {"open": True, "label": f"waiting {_span(now - asked)}"}
        else:
            end = a.get("decided_at") or (nxt["at"] if nxt else 0)
            if end and end > asked:
                dot["wait"] = {"open": False, "label": f"waited {_span(end - asked)}"}

    # Where the case is now: the decision it waits on, or else its latest step.
    waiting = case.stage == mc.AWAITING
    current = dots[-1]["step"] if dots else ""
    if waiting:
        current = next((d["step"] for d in reversed(dots) if d.get("approval")), current)

    width = _position_passes(passes, waiting, current)

    segs, waits, by_step = _flow_links(steps, passes, dots)

    rail_top, bells = _flow_bells(case, steps, dots, before, by_step, now)

    lanes = []
    for i, (key, name, what) in enumerate(PIPELINE):
        mine = [d for d in dots if d["lane"] == i]
        lanes.append({"key": key, "name": name, "what": what,
                      "count": sum(1 for d in mine if d["counts"]),
                      "step": mine[-1]["step"] if mine else "",
                      "y": HEAD_H + i * LANE_H, "mid": HEAD_H + i * LANE_H + LANE_H / 2})
    return {"lanes": lanes, "passes": passes, "dots": dots, "segs": segs, "waits": waits,
            "bells": bells, "told_what": TOLD_WHAT, "rail_top": rail_top,
            "current": current, "waiting": waiting, "width": width,
            "height": rail_top + RAIL_H, "head": HEAD_H, "lane_h": LANE_H}


def attempts_on_passes(flow: dict, steps: list[dict], earlier: list[dict], attempt_no: int,
                       events: list[dict]) -> list[dict]:
    """Each pass of the chart told which attempt it belongs to, and the events grouped by pass.

    Petar, 2 October 2026: the Earlier attempts section is gone, and what only
    it showed - how an attempt ended, the instructions it carried and was
    redone with, and what reached anybody outside - is a pass's summary, opened
    from its header on the chart (`pass-<n>`, and `attempt-<n>` for the first
    pass of an attempt, so old links still land). An attempt ends when Redo
    starts the next, so a pass belongs to the attempt that was open when it
    began; Redo's own pass starts the new one. Returns the events in their
    order, in runs of one pass each, for the Logs section.
    """
    by_id = {s["id"]: s for s in steps}
    ends = sorted(float(a.get("ended_at") or 0) for a in earlier)
    info = {a["number"]: a for a in earlier}

    def attempt_at(at: float, redo: bool = False) -> int:
        # Redo's step is written as the attempt it ends is frozen: it opens the next.
        return 1 + sum(1 for end in ends if end and at >= end - (1.0 if redo else 0.0))

    passes = flow.get("passes") or []
    for i, p in enumerate(passes):
        start = by_id.get(p["start"]) or {}
        n = min(attempt_at(start.get("at") or 0, start.get("kind") == "redo"), attempt_no)
        before = passes[i - 1]["attempt"] if i else 0
        p.update(attempt=n, card=f"pass-{p['n']}", first_of_attempt=n != before,
                 anchor=f"attempt-{n}" if n != before else "", earlier=info.get(n),
                 steps_n=len(p["dots"]),
                 span=(_when_short(p["dots"][0]["at"]) + (
                     f" - {_when_short(p['dots'][-1]['at'])}" if len(p["dots"]) > 1 else "")
                       if p["dots"] else ""))
    for i, p in enumerate(passes):
        nxt = passes[i + 1] if i + 1 < len(passes) else None
        p["last_of_attempt"] = nxt is None or nxt["attempt"] != p["attempt"]
        a = p["earlier"]
        hover = f"Pass {p['n']}, attempt {p['attempt']}: {p['label']}"
        if a and p["last_of_attempt"]:
            hover += f". Attempt {a['number']} ended: {attempt_end(a, short=True)}"
        elif not a:
            hover += ". The current attempt"
        p["hover"] = hover + ". Tap for its summary."

    groups: list[dict] = []
    starts = [((by_id.get(p["start"]) or {}).get("at") or 0, p) for p in passes]
    for e in events:
        at = e.get("at") or 0
        mine = next((p for t, p in reversed(starts) if at >= t - 0.001), None) or \
            (passes[0] if passes else None)
        key = mine["n"] if mine else 0
        if not groups or groups[-1]["pass"] != key:
            groups.append({"pass": key, "card": mine["card"] if mine else "",
                           "label": mine["label"] if mine else "",
                           "attempt": mine["attempt"] if mine else attempt_no,
                           "superseded": bool(mine and mine["earlier"]), "events": []})
        groups[-1]["events"].append(e)
    return groups


def attempt_end(a: dict, short: bool = False) -> str:
    """How an earlier attempt ended, in words, as the old Earlier attempts section said it."""
    if a.get("blocker"):
        return "blocked" if short else a["blocker"]
    if a.get("lapsed"):
        return "decision lapsed" if short else \
            "Waiting for your decision, which was not made in time."
    if a.get("withdrawn"):
        return "decision withdrawn by Redo" if short else \
            "Waiting for your decision, which you withdrew by pressing Redo; nothing was done on it."
    words = a.get("outcome") or a.get("end_words") or ""
    return str(a.get("end_words") or words).lower() if short else words


# --- what went wrong ------------------------------------------------------------------------


_BLIND = re.compile(
    r"could(?: not|n't) (?:see|check|confirm|open|verify|look|load|reach)|"
    r"(?:not|never) (?:been )?(?:seen|proven|confirmed|checked)|nobody has seen|"
    r"sign(?:ed)?[- ]?in|log(?:ged)?[- ]?in|sign-in page|no (?:database|signed-in|tool|access)|"
    r"unable to|cannot (?:see|check|confirm|verify)|redirect", re.I)
_UNDONE = re.compile(r"was not done|not done|did not (?:move|do|check)|"
                     r"left for (?:you|the owner|(?-i:[A-Z][a-z]+))\b|"
                     r"outside (?:her|his|their) levels|none of the tools|no tool|"
                     r"database (?:write|change)", re.I)

#: Where each part of the pipeline is, for the brief and the causes.
FILES = {
    "brief_assess": "rouh/mail_cases.py: brief_assess (what a reading is told)",
    "brief_carry_out": "rouh/mail_cases.py: brief_carry_out (what the start is told)",
    "brief_verify": "rouh/mail_cases.py: brief_verify, until 12 October 2026 (what the verifier "
                    "was told; the gate no longer checks the work)",
    "route_for": "rouh/mail_cases.py: route_for (the code's routing, rule by rule)",
    "may_use": "rouh/mail_turn.py: MailTurn.may_use, MAY_USE, ASSESS_READS (the tools per mode)",
    "level_tools": "rouh/trusted.py: LEVEL_TOOLS, LEVELS, GRANT_COVERS (what each level adds)",
    "risk_floor": "rouh/trusted.py: _FLOOR and risk_floor (the word check on the email)",
    "word_review": "rouh/word_review.py: DEFAULT_PROMPT, flags_of, review (the model call on "
                   "the word check's flags); its saved settings are on its step",
    "reply_check": "rouh/mail_cases.py: check_reply, REPLY_CHECK_SYSTEM (the model call on the "
                   "reply); rouh/trusted.py: REPLY_RISKS, REPLY_COVERS, reply_net",
    "share_tool": "rouh/tools.py: ToolRegistry._share_granted_page and _read_granted_tasks",
    "case_reader": "rouh/mail_cases.py: case_reader, until 12 October 2026 (the check's reader "
                   "of the case's own task; gone with the check)",
    "case_report": "rouh/tools.py: ToolRegistry._case_report (the report's schema)",
    "desk": "rouh/mail_cases.py: CaseDesk (stages, retries, the sweep, the reply)",
    "trace": "rouh/case_trace.py (this page's steps and diagnosis)",
    "grants": "rouh/grants.py: the grants, the prompts the reading is given, the hard limits; "
              "Settings > Trusted contacts changes them",
}


def _cause(kind: str, title: str, detail: str, files: list[str], likely: bool = False) -> dict:
    return {"kind": kind, "kind_words": {"prompt": "Prompt", "tool": "Tool or permission",
                                         "code": "Code", "data": "Data"}[kind],
            "title": title, "detail": detail, "files": [FILES[f] for f in files],
            "likely": likely}


def _verifier_stop(case, steps: list, blocked: dict, cause: dict, work, why: str,
                   out: dict) -> dict:
    """Explain what the verifier found, and whether that finding stopped the case."""
    out["step"], out["rerun"] = cause["id"], "verify"
    text = " ".join(str((cause["report"] or {}).get(k) or "")
                    for k in ("blocker", "checked", "evidence"))
    blind = bool(_BLIND.search(text))
    work_said = " ".join(str(((work or {}).get("report") or {}).get(k) or "")
                         for k in ("evidence", "checked", "proposed_action"))
    work_done = bool(work and (work["report"] or {}).get("outcome") == "done")
    undone = bool(_UNDONE.search(work_said + " " + text))
    # Petar, 6 October 2026: a contact's case page said the check failed
    # because of a message that came eleven hours later. What the check
    # found is its own report, and why the case stopped is the block's,
    # and the two are said apart. Something that happened between them -
    # a question to him, the work sent back - means the check did not stop
    # it: it was stopped later, for the block's own reason.
    finding = mc.findings_of(cause["report"] or {}) or _first(
        str((cause["report"] or {}).get("checked") or ""), 400)
    between = [s for s in steps if cause["at"] < s["at"] < blocked["at"]
               and s["kind"] in ("approval", "handoff", "followjob", "decided", "honest")]
    out["finding"], out["finding_step"] = _first(finding, 900), cause["id"]
    out["block_reason"] = _first(why, 900)
    if between:
        out["headline"] = ("The check found mistakes, and the case was stopped later, "
                           "for another reason.")
        out["plain"] = ("The check, a fresh turn that has to see the result before any "
                        "reply goes, said verified false, and what it found went on to "
                        f"be dealt with ({between[0]['title'].lower()}, "
                        f"{between[0]['when']}). The case was blocked after that, and "
                        "not by the check.")
    else:
        out["headline"] = "The verifier stopped it: it did not see the work done."
        out["plain"] = (
            "The work reported done" if work_done else "The work reported") + \
            ", then the verifier, a fresh turn that has to see the result before any " \
            "reply goes, said verified false. " + (
            "It could not look, rather than saw something wrong." if blind else
            "What it found is below, apart from why the case was blocked.")
    if between:
        lapsed = "lapsed" in why or "expired" in why
        out["false_alarm"] = "unlikely"
        out["signals"] = [s for s in (
            ("The check said verified false", True),
            ("What it found was sent on before the case stopped", True),
            ("An approval lapsed before you decided", lapsed)) if s[1]]
        out["causes"].append(_cause(
            "code", "It stopped after the check, not because of it",
            "Why it was blocked is the block's own reason, below what the check found. "
            "If the block was a question that lapsed, read the approvals for why.",
            ["desk"], likely=True))
        out["false_alarm_words"] = _FALSE_WORDS.get(out["false_alarm"], "")
        return out
    if blind and work_done:
        out["false_alarm"] = "partly" if undone else "likely"
        out["false_alarm_why"].append(
            "The work turn had already confirmed the result with its own tool "
            f"({_tools_said(work)}), and the verifier could not open the result "
            "the way the sender sees it, so it could not agree.")
    elif blind:
        out["false_alarm"] = "possible"
    else:
        out["false_alarm"] = "unlikely"
    if undone:
        out["false_alarm_why"].append(
            "But part of the approved action really was not done: the work said a "
            "step needed a tool its levels do not have. That part is a real gap, in "
            "the reading that proposed it.")
    out["signals"] = [s for s in (
        ("The verifier could not see the result as the sender would", blind),
        ("The work reported done", work_done),
        ("Part of the action needed a tool the levels do not have", undone),
        ("The case was inside a grant, so the verifier had only the levels' tools",
         case.route == "granted")) if s[1]]
    if blind:
        out["causes"].append(_cause(
            "tool", "The verifier has no way to see the result as the sender sees it",
            "In a case inside a grant the verifier has only the tools of the contact's "
            "levels (plus reading and web_fetch). A shared page sits behind the guest's "
            "sign-in, so web_fetch lands on the sign-in page, and nothing lets it read "
            "the share row or the page's comments. Give the verify mode a read-only "
            "check of a guest share (the share row, the page it resolves to, its "
            "comments) or count share_granted_page's own confirmation as evidence.",
            ["may_use", "level_tools", "share_tool"], likely=True))
        out["causes"].append(_cause(
            "prompt", "The verifier is asked for a check it cannot make",
            "brief_verify says to check it 'the way they would find it: open the "
            "page...'. For a signed-in guest page that is impossible with its tools, so "
            "a careful model blocks. Say which evidence is enough when the result is "
            "behind the guest's sign-in, and that a tool's own confirmation counts.",
            ["brief_verify"], likely=True))
    if undone:
        out["causes"].append(_cause(
            "prompt", "The reading proposed an action no tool of the levels can do",
            "brief_assess lets a reading propose any action under needs_work, and "
            "route_for checks only the levels it names, not whether the tools of "
            "those levels can do the action. A step like a database change then "
            "passes as granted, the work cannot do it, and the verifier blocks. Tell "
            "the reading the tools each level has, and to report needs_approval for "
            "anything beyond them.", ["brief_assess", "route_for", "level_tools"],
            likely=True))
    out["causes"].append(_cause(
        "data", "The result really is not there",
        "Read the work turn's tool results below: if a tool said it was done but the "
        "data says otherwise, the bug is in that tool or in the data it read.",
        ["share_tool"]))
    out["causes"].append(_cause(
        "code", "The report or its routing was read wrongly",
        "If the verifier's report says verified true and the case still blocked, or "
        "the wrong turn's report was taken, the bug is in the desk.",
        ["desk", "case_report"]))
    out["false_alarm_words"] = _FALSE_WORDS.get(out["false_alarm"], "")
    return out


def _stop(case, steps: list[dict], blocked: dict, *, current: bool = False) -> dict:
    """Why one block happened: the step behind it, false alarm or not, and the causes."""
    steps = [s for s in steps if s["at"] <= blocked["at"]]
    rounds = [s for s in steps if s["kind"] in MODES]
    last = {m: next((s for s in reversed(rounds) if s["kind"] == m), None) for m in MODES}
    out = {"step": "", "headline": "", "plain": "", "false_alarm": "", "false_alarm_why": [],
           "causes": [], "rerun": "", "signals": [], "blocked": blocked["id"],
           "when": blocked["when"]}
    why = ((case.blocker or str(((case.follow_up or {}).get("stop") or {}).get("why") or ""))
           if current else "") or blocked.get("summary", "")
    work = last["carry_out"]
    cause = rounds[-1] if rounds and blocked and rounds[-1]["at"] <= blocked["at"] else None
    # A decision that ended without the owner deciding it, after the last turn: the stop is the
    # decision's, not that turn's. Dismissed is what became of the ones that had run out of
    # time under the old 48-hour limit (migration 0106).
    asked = next((s for s in reversed(steps) if s["kind"] == "approval"), None)
    ended = (asked or {}).get("approval") or {}
    if asked is not None and (cause is None or asked["at"] >= cause["at"]) and \
            ended.get("status") in ("dismissed", "expired", "superseded"):
        out["step"], out["rerun"] = asked["id"], "assess"
        if ended["status"] == "superseded":
            out["headline"] = "Your decision lapsed before you made it."
            out["plain"] = _first(ended.get("why_invalid") or why, 500)
            out["causes"].append(_cause("code", "Something the decision was for changed",
                                        "A newer message, a new proposal, a file or what the "
                                        "contact may do. Redo starts it again.", ["desk"],
                                        likely=True))
        else:
            out["headline"] = "Your decision was dismissed."
            out["plain"] = ("It had run out of time under the old 48-hour limit, and on 8 "
                            "October 2026 the ones that had were closed rather than brought "
                            "back. Nothing was done and nothing was sent. Redo starts it again "
                            "if you want it.")
            out["causes"].append(_cause("code", "Closed without a decision",
                                        "Approvals no longer run out of time; this one had, "
                                        "before that changed.", ["desk"], likely=True))
        out["false_alarm_words"] = _FALSE_WORDS.get(out["false_alarm"], "")
        return out
    if cause is not None and cause["kind"] == "verify" and \
            (cause["report"] or {}).get("verified") is not True:
        return _verifier_stop(case, steps, blocked, cause, work, why, out)
    elif cause is not None and cause["kind"] == "carry_out":
        out["step"], out["rerun"] = cause["id"], "carry_out"
        out["headline"] = "The work could not be done."
        out["plain"] = "The turn doing the work reported blocked: " + _first(why, 400)
        text = str((cause["report"] or {}).get("blocker") or "")
        missing = bool(_UNDONE.search(text) or _BLIND.search(text))
        out["false_alarm"] = "possible" if missing else "unlikely"
        if missing:
            out["false_alarm_why"].append("It says it lacked a tool or a way to see, not "
                                          "that the thing asked for is wrong.")
        out["causes"] += [
            _cause("tool", "A tool or permission is missing for this level",
                   "Compare the tools offered to this turn (below) with what the action "
                   "needs.", ["may_use", "level_tools"], likely=missing),
            _cause("prompt", "The reading proposed more than the work may do",
                   "The action was proposed by the reading and routed as granted or "
                   "approved; the work turn is held to it exactly.",
                   ["brief_assess", "brief_carry_out"]),
            _cause("data", "What the action needed was not there",
                   "Read the tool results in the work turn.", ["share_tool"])]
    elif cause is not None and cause["kind"] == "assess":
        out["step"], out["rerun"] = cause["id"], "assess"
        out["headline"] = "The reading said it cannot go on."
        out["plain"] = "Rouh read the message and reported blocked: " + _first(why, 400)
        out["false_alarm"] = "possible"
        out["causes"] += [_cause("prompt", "The reading was too careful",
                                 "Read its brief and report below.", ["brief_assess"]),
                          _cause("data", "Something it needed to read was missing",
                                 "See its tool calls below.", ["share_tool"])]
    else:
        out["step"] = (blocked or {}).get("id", "")
        out["rerun"] = "assess"
        out["headline"] = "Rouh's code stopped it."
        out["plain"] = _first(why, 500)
        lapsed = "lapsed" in why or "expired" in why
        tries = "tried" in why and "never reported" in why
        out["false_alarm"] = "possible" if lapsed else "unlikely"
        if tries:
            out["causes"].append(_cause("code", "The turn never reported",
                                        f"{mc.MAX_ATTEMPTS} turns ended without "
                                        "case_report: read their transcripts below for "
                                        "an error or a turn that ran out of time.",
                                        ["desk", "case_report"], likely=True))
        if lapsed:
            out["causes"].append(_cause("code", "The approval lapsed before you decided",
                                        "Read the approvals below for why.", ["desk"],
                                        likely=True))
        if not out["causes"]:
            out["causes"].append(_cause("code", "A stage of the desk could not go on",
                                        "The block's own words say which.", ["desk"]))
    out["false_alarm_words"] = _FALSE_WORDS.get(out["false_alarm"], "")
    return out


_FALSE_WORDS = {"likely": "Looks like a false alarm", "partly": "Partly a false alarm",
                "possible": "Possibly a false alarm", "unlikely": "Looks like a real stop"}


def diagnose(case, steps: list[dict], notes: list[dict], state=None) -> dict:
    """Which step stopped the case, in plain words, whether it looks like a false alarm,
    the likely causes, and the step to mark and re-run. Earlier stops of the same case,
    each with its own reading, are in `earlier`.

    A case with a ledger is diagnosed from its ledger as it is judged now, and its headline is
    the case's one line (`case_state`, D14): never what an earlier route said of grants it may
    have been given since. `state` is that state when the caller has it."""
    blocks = [s for s in steps if s["kind"] == "blocked"]
    now_blocked = (case.stage == mc.BLOCKED or old.stopped(case)) and bool(blocks)
    out = {"state": case.stage, "step": "", "headline": "", "plain": "", "false_alarm": "",
           "false_alarm_why": [], "causes": [], "rerun": "", "signals": [],
           "earlier": [_stop(case, steps, b) for b in (blocks[:-1] if now_blocked else blocks)]}
    marked = [n for n in notes if n["kind"] in ("false_alarm", "real_problem")]
    if marked:
        out["marked"] = marked[-1]["kind"]

    from . import mail_ledger as ledger

    ledger_steps = [s for s in steps if s["kind"] == "ledger"]
    asks = list(state.asks) if state is not None else \
        ledger.rows(case.user_id, case.org_id, case.id)
    if ledger_steps or asks:
        out["step"] = (ledger_steps[-1]["id"] if ledger_steps else
                       next((s["id"] for s in reversed(steps)
                             if s["kind"] in ("route", "assess")), ""))
        out["headline"] = state.line if state is not None else ledger.why_line(
            asks, stage=case.stage, step_words=(
                mc.STAGE_WORDS.get(case.stage, case.stage) if case.stage in mc.IN_FLIGHT
                else ""))
        failed = [a for a in asks if a.status == ledger.FAILED and not a.possible]
        ready = [a for a in asks if a.possible]
        if ready and not failed:
            out["plain"] = "Ready to run: " + "; ".join(
                f"\u201c{a.named[:100]}\u201d failed, and a run does it: "
                f"{a.possible}" for a in ready[:3]) + "."
        if failed:
            out["plain"] = "What failed: " + "; ".join(f"\u201c{a.named[:100]}\u201d: {a.why}"
                                                      for a in failed[:3])
            out["causes"].append(_cause("tool", "The work or its check did not get there",
                                        "The work and the check are steps of their own below, "
                                        "with what each was given and said.",
                                        ["brief_carry_out", "brief_verify"], likely=True))
        elif any(a.status == ledger.WAITING for a in asks):
            out["plain"] = ("What waits needs a grant they do not hold, one there is not yet, "
                            "or a hard limit: only you decide it. If the reading mapped an ask "
                            "to the wrong grant, that is the step to mark.")
        out["false_alarm"] = "unlikely"
    elif now_blocked:
        out.update(_stop(case, steps, blocks[-1], current=True))
    elif case.stage == mc.AWAITING:
        route = next((s for s in reversed(steps) if s["kind"] == "route"), None)
        out["step"] = (route or {}).get("id", "")
        out["headline"] = "It is waiting for your decision."
        trail = (route or {}).get("trail") or (route or {}).get("replay") or []
        failed = [t for t in trail if t.get("ok") is False and t.get("rule") != "route"]
        words_only = [t for t in failed if str(t.get("rule", "")).startswith(("risk:", "ask:"))
                      and t.get("where") and "Rouh's reading" not in t.get("where")]
        by_reply = [t for t in failed if str(t.get("rule", "")).startswith("reply:")
                    and t.get("rule") not in ("reply:net", "reply:check")]
        other = [t for t in failed if t.get("rule") == "levels" and
                 {"other", old.OLD_CATCH_ALL} & set(t.get("outside") or [])]
        held_asks = [t for t in failed if str(t.get("rule") or "").startswith("ask#")]
        out["plain"] = "The route stopped at: " + "; ".join(
            _first(t["said"], 160) for t in failed[:4]) if failed else \
            "The route sent it to you: " + "; ".join(case.reasons or [])[:400]
        if words_only:
            out["false_alarm"] = "likely" if len(words_only) == len(failed) else "possible"
            out["false_alarm_why"].append(
                "A risk was flagged only by the word check, not by Rouh's reading, and the "
                "word review did not overrule it: "
                + ", ".join(f"{t['risk']} ({', '.join(t.get('words') or [])})"
                            for t in words_only) + ".")
            out["causes"].append(_cause(
                "prompt", "The word check is too broad, and the word review agreed with it",
                "The words that tripped it are listed in the route step, and what the word "
                "review said of each on its own step, where its model, reasoning and "
                "instructions can be changed and tried again. Or narrow the pattern, let a "
                "level cover the risk (GRANT_COVERS), or allow the topic for this contact on "
                "the Trusted contacts page (TOPICS).", ["word_review", "risk_floor",
                                                        "level_tools"], likely=True))
        if by_reply:
            out["false_alarm"] = out["false_alarm"] or "possible"
            out["causes"].append(_cause(
                "prompt", "The reply check says the reply gives something away",
                "Its sentence is in the route step, under What the reply gives away. If the "
                "reply only explains or quotes, tune REPLY_CHECK_SYSTEM; if it really gives "
                "it away, allow the topic for this contact (REPLY_COVERS) or edit the reply.",
                ["reply_check"], likely=len(by_reply) == len(failed)))
        if other:
            out["causes"].append(_cause(
                "prompt", "The reading used the old catch-all",
                "Until 11 October 2026 the reading could say answering takes something no grant "
                "covers, which nothing could grant, so the whole message waited. Read it again: "
                "it is now split into asks, and only those outside what they hold wait.",
                ["brief_assess"], likely=True))
            out["false_alarm"] = out["false_alarm"] or "possible"
        if held_asks:
            out["causes"].append(_cause(
                "tool", "Some of what they ask needs a grant they do not hold",
                "Each held ask is in the route step, under What they ask, ask by ask, with who "
                "stopped it and the grant proposed. Give or set up the grant in your decision, "
                "let it go just this time, or reject it. If they already hold a grant that "
                "covers it, say That was wrong.", ["grants", "route_for"],
                likely=False))
        if not out["causes"]:
            out["causes"].append(_cause("prompt", "It really needs you",
                                        "Every failing rule is in the route step.",
                                        ["route_for"]))
        out["false_alarm"] = out["false_alarm"] or "unlikely"
    elif case.stage in mc.CLOSED:
        out["headline"] = {mc.DONE: "Nothing went wrong: it was carried to its end.",
                           mc.JUNK_SPAM: "Read as junk and moved to Gmail spam.",
                           mc.JUNK_KEPT: "Read as junk; Gmail would not move it."}.get(
            case.stage, "Closed.")
        out["plain"] = case.outcome or ""
        if case.stage in mc.JUNKED:
            out["causes"].append(_cause("prompt", "If it was not junk",
                                        "The reading decides junk; see its report.",
                                        ["brief_assess"]))
    else:
        out["headline"] = f"In progress: {mc.STAGE_WORDS.get(case.stage, case.stage)}."
        out["plain"] = "This page follows it as it goes."
    out["false_alarm_words"] = _FALSE_WORDS.get(out["false_alarm"], "")
    return out


def _first(text: str, most: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[:most - 1].rsplit(" ", 1)[0] + "…"


def _tools_said(step) -> str:
    names = [n for t in (step or {}).get("turns") or [] for n in t["tools_called"]
             if n != "case_report" and not n.startswith("tool_search")]
    return ", ".join(dict.fromkeys(names)) or "its report"


def files_read(case, trace: dict) -> list[dict]:
    """The email's files for the case page, each with whether Rouh opened it and how that went.

    Read off the trace's own tool calls (`read_mail_attachment`), so what the
    page says is what the model really did, not what it reported.
    """
    opened: dict[str, str] = {}
    for step in trace.get("steps") or []:
        for turn in step.get("turns") or []:
            for e in turn.get("transcript") or []:
                if e.get("kind") != "call" or e.get("name") != "read_mail_attachment":
                    continue
                part = str((e.get("input") or {}).get("part") or "")
                result = str(e.get("result") or "")
                went = ("error" if e.get("error") else "unread" if
                        "is attached to the email, but" in result else "read")
                if opened.get(part) != "read":
                    opened[part] = went
    out = []
    for one in mail_attachments.kept((case.email or {}).get("attachments")):
        went = opened.get(one["part"], "")
        out.append({**one, "kind": mail_attachments.kind_said(one["type"], one["name"]),
                    "size_said": mail_attachments.size_said(one["size"]),
                    "readable": mail_attachments.readable(one),
                    "went": went,
                    "went_said": {"read": "Rouh read it",
                                  "unread": "Rouh opened it and could not read its words",
                                  "error": "Rouh tried to open it and Gmail would not give it",
                                  }.get(went, "Rouh did not open it")})
    return out


def files_went_said(files: list[dict]) -> str:
    """What Rouh did with all of an email's files, when it did the same with each."""
    if len(files) == 1:
        return files[0]["went_said"]
    return {"read": "Rouh read them",
            "unread": "Rouh opened them and could not read their words",
            "error": "Rouh tried to open them and Gmail would not give them",
            }.get(files[0]["went"], "Rouh did not open them")


# --- the Ask box ------------------------------------------------------------------------------


ASK_SYSTEM = """You help ‹owner› debug and tune Rouh's email case pipeline, from the page of one case.

How the pipeline works (rouh/mail_cases.py, MAIL.md, since 11 October 2026): every message from somebody other than ‹owner› is a case, and a case runs on its ledger (rouh/mail_ledger.py): one row per ask, each with the sender's quoted words, the grant it needs ("none" for an answer alone), a hard limit it touches, its status (allowed, waiting_for_owner, approved, declined, done, failed) and its evidence. A turn reads the message (assess) and reports with case_report: each ask mapped to exactly one existing grant, a proposed new grant, or a hard limit, and the friendly words of the answer. The model decides nothing: Rouh's code judges each ask from the grants the contact holds (mail_ledger.judge): held is allowed, not held, new or a hard limit waits for ‹owner› on its own; only ‹owner› declines. No word list, topic or model check decides anything any more (the old route, word check, word review, reply check and status check are gone; old cases still show them as they ran). Since 12 October 2026 the case is an entry gate only (MAIL.md D18): the start (carry_out) starts each allowed or approved ask as ordinary work - an assistant job, a Clockwork item, a task, a note kept - with only their grants' tools, a tool with a hard-limit effect (mail_turn.EFFECTS) only for an ask ‹owner› approved with that limit, and marks it started with its handle (MailAsk.work), or done when it was done at once. The gate then sends one message through the one outbox (rouh/mail_outbox.py): the model's answer and a status part the code writes from the ledger (mail_ledger.first_email) saying what is allowed and started and what needs ‹owner› and waits; one more per batch of ‹his› decisions (mail_ledger.decided_email). After the start the case never watches, checks, fixes or follows the work: each job sends its own result for the contact (its "For <name>:" part), grouped when several finish within minutes, and a Clockwork item sends at its time. Only a need nobody decided (a grant, a hard limit, a task they may not change) comes back, onto the very ask it stopped, which then waits for ‹owner›; it is never an ask of its own (MAIL.md D29). Older cases show the old check (verify) and its fix rounds as they ran. A case at rest (done, waiting for ‹owner›, declined) is never run again by itself: only ‹owner›'s Redo, or Approve and run on Decisions, runs it. Each case has one decision listing what waits, made again whenever the ledger changes. The same request on another channel within minutes, or a forward of a message already in a case, is attached to that case.

Answer from the trace below, which is the whole record of this case: each step's brief as sent, the tools offered, every tool call and its result, every report, the routing rule by rule. Be concrete: name the step, quote the words that matter, and when ‹he› asks how to fix something name the file and function and say what to change. Most stops ‹he› looks at are false alarms; help ‹him› tell which, and why. Plain words, short paragraphs, no em dashes. If the trace does not say, say so."""


def _sent_view(row: dict) -> dict:
    """One message to the sender as it went, from its trace row (`CaseDesk._sent`)."""
    d = row.get("data") or {}
    return {"kind": row.get("mode") or "", "kind_said": SENT_KINDS.get(row.get("mode") or "",
                                                                        row.get("mode") or ""),
            "channel": d.get("channel") or "", "to": d.get("to") or "",
            "to_name": d.get("to_name") or "", "text": d.get("text") or "",
            "message_id": d.get("message_id") or "", "ok": d.get("ok", True) is not False,
            "error": d.get("error") or "", "when": _clock(row["at"]), "log": d.get("log") or "",
            "source": "sent"}


#: What each kind of message to the sender is called on the page.
SENT_KINDS = {"reply": "The reply", "ack": "Accepted, being worked on",
              "waiting": "Waiting for your sign-off", "status": "Where their requests stand",
              "follow_up": "A follow-up"}


def _reply_sent(case, e: dict, sent_rows: list[dict]) -> list[dict]:
    """The reply as it went, word for word, with the id its provider gave it.

    From the message's own trace row, written as it went (since card 1315).
    Before those, from the case's row, which keeps the last reply's words and
    id: only for the reply step that wrote them.
    """
    rows = [r for r in sent_rows if r.get("mode") == "reply" and r["at"] <= e["at"] + 1
            and e["at"] - r["at"] < 600 and (r.get("data") or {}).get("ok", True) is not False]
    if rows:
        return [_sent_view(rows[-1])]
    if case.replied_at and abs(case.replied_at - e["at"]) < 5 and (case.sent_reply or "").strip():
        on_tg = str(case.message_id or "").startswith("tg:")
        return [{"kind": "reply", "kind_said": SENT_KINDS["reply"],
                 "channel": "telegram" if on_tg else "email", "to": case.sender,
                 "to_name": case.sender_name, "text": case.sent_reply,
                 "message_id": case.reply_message_id or "", "ok": True, "error": "",
                 "when": _clock(case.replied_at), "log": "", "source": "case"}]
    return []


def step_text(case, s: dict) -> str:
    """One step of a case's trace as text: for the Ask box, and for a link to the step read
    inside Rouh (`rouh/rouhlinks.py`)."""
    out = [f"## {s['id']}: {s['title']} at {s['when']} [{s.get('run')}, "
           f"{s.get('status') or 'no verdict'}]"
           + (f" verdict {s['verdict']}" if s.get("verdict") else "")]
    if s["kind"] == "received":
        out.append(f"From {case.sender_name} <{case.sender}>. Gmail's check: "
                   f"{s.get('identity_line')} ({s.get('identity_said') or '?'}).")
    if s.get("summary"):
        out.append(f"Summary: {s['summary']}")
    if s["kind"] in MODES:
        out.append(f"Model: {s.get('model')}, took {s.get('took')}, cost ${s.get('cost')}")
        if s.get("tools_offered"):
            out.append("Tools offered: " + ", ".join(s["tools_offered"]))
        if s.get("brief"):
            out.append("Brief as sent:\n" + s["brief"][:12000])
        for t in s.get("turns") or []:
            for e in t["transcript"]:
                if e["kind"] == "call":
                    out.append(f"Tool call {e['name']}: {json.dumps(e['input'])[:3000]}")
                    if e.get("result"):
                        out.append(f"  result: {e['result'][:3000]}")
                elif e["kind"] == "said":
                    out.append(f"Said: {e['text'][:2000]}")
                elif e["kind"] == "thinking":
                    out.append(f"Thought: {e['text'][:1500]}")
        if s.get("report"):
            out.append("Report: " + json.dumps(s["report"], ensure_ascii=False)[:8000])
    if s["kind"] == "route":
        out.append(f"Route: {s.get('route')} (source {s.get('source')})")
        if s.get("conclusion"):
            out.append(f"Conclusion: {s['conclusion']['value']}. {s['conclusion']['why']}")
        for t in s.get("trail") or []:
            out.append(f"  rule {t.get('rule')} ok={t.get('ok')}: {t.get('said')}")
        for c in s.get("checks") or []:
            out.append(f"  check: {c}")
        for c in s.get("reasons") or []:
            out.append(f"  reason: {c}")
        if s.get("replay"):
            out.append(f"Replayed today: {s.get('route_now')}"
                       + (f" ({s['conclusion_now']['value']}. "
                          f"{s['conclusion_now']['why']})" if s.get("conclusion_now")
                          else ""))
            for t in s["replay"]:
                out.append(f"  rule {t.get('rule')} ok={t.get('ok')}: {t.get('said')}")
    if s.get("approval"):
        out.append("Approval: " + json.dumps(s["approval"], ensure_ascii=False)[:3000])
    for one in s.get("sent") or []:
        out.append(f"{one['kind_said']}, sent {one['when']} on {one['channel']} to "
                   f"{one['to_name'] or one['to']} <{one['to']}>, "
                   + (f"message id {one['message_id']}" if one["message_id"] else "no message id")
                   + ("" if one["ok"] else f", NOT sent: {one['error']}")
                   + (f"; written down in {one['log']}" if one.get("log") else
                      "; as the case's row keeps it" if one["source"] == "case" else "")
                   + ". Word for word:\n" + one["text"])
    for line in s.get("log") or []:
        out.append(f"  {line['when']}: {line['said']}")
    return "\n".join(out)


def trace_for_model(case, trace: dict) -> str:
    """The case's trace as text for the Ask box: everything but the system prompt itself."""
    email = case.email or {}
    head = [f"Case {case.key}: email from {case.sender_name} <{case.sender}>.",
            "Where it is now, from its ledger judged now: "
            + str(trace["diagnosis"].get("headline") or case.stage),
            f"Subject: {email.get('subject') or ''}", "Email body:",
            (email.get("body") or "")[:8000],
            "Files attached: " + ("; ".join(mail_attachments.line(f) for f in mail_attachments
                                            .kept(email.get("attachments")))
                                 or ("none" if "attachments" in email else
                                     "not recorded (a case from before 2 October 2026)")),
            "",
            "Diagnosis drawn by the page: " + json.dumps(
                {k: trace["diagnosis"].get(k) for k in ("headline", "plain", "false_alarm",
                                                        "false_alarm_why")},
                ensure_ascii=False)]
    notes = [f"- {n['when']} {n['kind']} {n['step']}: {n['text']}"
             + (f"\n  answer: {n['answer'][:1500]}" if n.get("answer") else "")
             for n in trace["notes"]]
    return "\n".join(head + ["", "# Steps"] + [step_text(case, s) for s in trace["steps"]]
                     + (["", "# ‹owner›'s notes on this case"] + notes if notes else []))


async def answer(cfg, who, case, trace: dict, question: str) -> str:
    """The owner's question about the case, answered with its whole trace in front of the model."""
    from . import llm

    body = trace_for_model(case, trace)
    earlier = [n for n in trace["notes"] if n["kind"] == "question" and n.get("answer")][-4:]
    messages = []
    for n in earlier:
        messages += [{"role": "user", "content": n["text"]},
                     {"role": "assistant", "content": n["answer"]}]
    messages.append({"role": "user", "content": question})
    # The trace rides in front of the first question, kept in the prompt cache,
    # so a second question about the same case is cheap.
    messages[0] = {"role": "user", "content": [
        {"type": "text", "text": "The case's trace:\n\n" + body,
         "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": messages[0]["content"]}]}
    # Either company's model, the one the Models page has for this (`rouh/llm.py`).
    try:
        got = await llm.ask("case_ask", system=ASK_SYSTEM, messages=messages, max_tokens=4000,
                            who=who, org_id=case.org_id, cfg=cfg, subject=f"mail case {case.id}",
                            read_only=True)
    except llm.Cannot as exc:
        raise RuntimeError(f"Rouh cannot answer here: {exc}.") from None
    return got.text.strip().replace("\u2014", "-") or "(no answer came back)"
