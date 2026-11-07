"""The replay of real cases, and the guard on the one outbox: what lands mail code (D5, D9).

Petar, 11 October 2026: "Test grants, Redo and a regression replay share one engine ... Make
land.sh, or the mail code's test step, fail when a case regresses." And: "add a test that fails
if any code sends contact mail outside the outbox."

So this runs, with no database, no model and nothing sent:

- **The replay** (`rouh/testing/mail_replay.json`): every mail and Telegram case from 30
  September to 11 October 2026 - the ten of task 74-03 among them, and a contact's itinerary
  as it stood before and after the owner gave her Memory, Clockwork and Shared task - each with
  its
  asks as the reading maps them, through `mail_ledger.judge`, the very judge a run, Redo and
  Test grants use. Each ask must come out as written. For the itinerary, the status part of
  the answer the code would write is checked line by line too. Then the guardrails that task
  74's guards.py held - paying, booking, sending as the owner, forwarding their mail, sharing
  with somebody else, publishing, deleting, committing their time, somebody not trusted, a
  contact switched off, an unconfirmed sender - which must still wait, and the owner's own
  choices, which are the only refusal there is. The people, addresses and places in the set
  are invented stand-ins for the real ones (the owner is "Alex"), each the same throughout, so
  every case judges as it did.
- **One case per request**: a forward of a message already in a case is that case
  (`mail_ledger.forward_key`, case 11 forwarding case 10).
- **Where a case says it is** (MAIL.md D14 to D17): the itinerary as it rests on 12 October
  2026, and guards, through `case_state.of` - its words, whether it is running, its next
  action and which failed asks are possible now - and no case waiting with nothing to press.
- **The gate** (MAIL.md D18): a case is an entry gate only. The itinerary as it arrived
  before her grants: one first message listing what was allowed and started and what needs
  the owner and waits; one batch of their decisions, one message, and none again while nothing
  changed; a started job that fails, which raises no decision and sends nothing; a job that
  needs what was not decided, which puts it on the ask it stopped and makes a decision, never
  a new ask; two results that finish together, one message.
- **Case 51 as it stood on 16 October 2026** (MAIL.md D29): a blocker is never an ask, a run
  that finds nothing left to do is done and never failed, and no permission is asked for, and
  no decision put to the owner, when the contact holds what every ask needs.
- **Case 53 as it was read and run three times** (MAIL.md D34, `readings`): the same message
  read twice gives the same reading, "talk to you in the interface" is never a hard limit, a
  covered ask that fails is tried again and is never a decision, and the reader is given the
  sender's permissions.
- **The outbox guard**: no module but `rouh/mail_outbox.py` sends to anybody who is not
  the owner - no Gmail send, forward or draft send in the mail-case modules, no Telegram send
  to another chat anywhere but the owner's own (`ALLOWED_CHAT_SENDS`), and no Slack post anywhere
  but the outbox, the Slack client, its answers to the owner's own messages, the slack_send tool
  the owner says yes to, and a late promise's nudge they say yes to (`ALLOWED_SLACK_SENDS`).

`python -m rouh.mail_replay` prints each check and exits 1 when any fails. `land.sh` runs it
before it pushes anything that touches the mail code (`mail_guard`), and refuses to land work
that does not pass.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

#: The owner and the contact the set's letters are written for and to: invented stand-ins.
OWNER, FIRST = "Alex", "Sam"
FIXTURES = HERE / "testing" / "mail_replay.json"

#: The modules whose job is somebody else's mail and messages: none may send itself.
GUARDED = ("mail_cases.py", "telegram_guests.py", "mail_alerts.py", "mail_ledger.py",
           "case_dry_run.py", "case_fixes.py", "case_trace.py", "decision_sources.py",
           "mail_turn.py", "management/commands/case_follow_up.py", "timekeeper.py",
           "reminders.py", "clockwork_grants.py", "slack_listen.py")
#: The calls that put a message in front of somebody, by their name.
SENDS = {"send", "send_parts", "send_draft", "send_draft_as_it_is", "forward",
         "forward_thread", "send_message", "post_message"}
#: Where a Telegram message may go to a chat that is not the bot's own (the owner's): the
#: outbox, and the owner's own fork groups (`telegram_chat`).
ALLOWED_CHAT_SENDS = ("mail_outbox.py", "telegram_chat.py")
#: Where a Slack message may be posted (`rouh/slack.py`): the outbox, for a case's answer and for the
#: one answer somebody not set up gets (`slack_not_set_up`); the client
#: itself; the listener, for the answer to the owner's own message to Rouh; and the slack_send tool,
#: which posts only on their yes. A case's turn is never offered slack_send (`mail_turn.NEVER_IN_CASE`).
#: And the nudge for a late promise in Slack, posted only on their yes to its decision's "sending"
#: (`slack_promises.remind`, through `decisions`).
ALLOWED_SLACK_SENDS = ("mail_outbox.py", "slack.py", "slack_listen.py", "slack_promises.py", "tools.py")


def _contact(raw: dict):
    from . import trusted as trust

    if raw.get("implicit"):
        return trust.implicit((raw.get("addresses") or ["somebody@example.com"])[0],
                              raw.get("name") or "")
    return trust.Trusted(id=int(raw.get("id") or 1), name=raw["name"], contact_id="",
                         trusted=bool(raw.get("trusted")),
                         levels=trust.with_lower(raw.get("levels") or []),
                         addresses=list(raw.get("addresses") or []),
                         inbox_scope=raw.get("inbox_scope") or trust.INBOX_NONE,
                         beyond=raw.get("beyond") or "ask",
                         telegram=list(raw.get("telegram") or []),
                         extra_grants=list(raw.get("extra_grants") or []),
                         zone=raw.get("zone") or "")


def _asks(raw: list[dict]):
    from . import mail_ledger as ledger

    out = []
    for n, one in enumerate(raw, start=1):
        out.append(ledger.Ask(ident=ledger.ident_of(one["ask"]), quote=one["ask"], n=n,
                              label=one.get("label") or "", grant=one.get("grant") or "",
                              new_grant=dict(one.get("new_grant") or {}),
                              also=list(one.get("also") or []),
                              hard_limit=one.get("hard_limit") or "",
                              task=str(one.get("task") or ""),
                              task_needs=str(one.get("task_needs") or ""),
                              choice=one.get("choice") or "",
                              choice_grant=one.get("choice_grant") or "",
                              status=ledger.status_of(one.get("status"))))
    return out


def judge_one(case: dict, contacts: dict, tree) -> list[str]:
    """What went wrong with one case's asks, as lines; none when every ask came out right."""
    from . import mail_ledger as ledger

    contact = _contact(contacts[case["who"]])
    asks = _asks(case.get("asks") or [])
    # What the work stopped at, as `CaseDesk._block` takes it: put on the very ask it stopped,
    # never a new ask (D29), and "task 90" is letting them edit that task, never a grant (D28).
    for one in case.get("blocked") or []:
        at = next(i for i, a in enumerate(asks) if a.quote == one["ask"])
        asks[at] = ledger.blocked(asks[at], one["what"], need=one.get("need") or "")
        if asks[at].new_grant:
            return [f"the need \"{one['what'][:60]}\" was proposed as a grant, "
                    f"{asks[at].new_grant.get('name')}, not as letting them edit a task"]
    if len(asks) != len(case.get("asks") or []):
        return ["what the work stopped at became an ask of its own"]
    if case.get("lift_grants"):
        # Grants the owner made from a proposal that lifts a hard limit (`grants.LIFTS`), with the
        # code's own tools for it.
        from . import grants

        tree = grants.Tree.of(list(tree.nodes.values()) + [
            {"key": one["key"], "name": grants.LIFTS[one["lifts"]]["name"],
             "prompt": grants.LIFTS[one["lifts"]]["prompt"],
             "tools": grants.LIFTS[one["lifts"]]["tools"], "holding": grants.GRANT}
            for one in case["lift_grants"]])
    inbox = ledger.Inbox(reach=getattr(contact, "inbox_scope", "none"),
                         needed=case.get("inbox_needed") or "")
    # What the sender, deciding for the work, already had done in the same message
    # (`delegation.done_in_case`), by the words of the ask it did.
    done_by = {ledger.ident_of(q): said for q, said in (case.get("done_by") or {}).items()}
    judged = ledger.judge(asks, contact, tree, identity_ok=case.get("identity_ok", True),
                          inbox=inbox, tasks=case.get("tasks") or {}, done_by=done_by)
    bad = []
    for raw, got in zip(case.get("asks") or [], judged):
        if got.status != raw["expect"]:
            bad.append(f"\"{raw['ask'][:70]}\" came out {got.status}, not {raw['expect']}: "
                       f"{got.why}")
        if raw.get("need") and ledger.need_named(got) != raw["need"]:
            bad.append(f"\"{raw['ask'][:70]}\" needs {ledger.need_named(got)!r}, not "
                       f"{raw['need']!r}")
    want = case.get("reply_done")
    if want:
        # The gate starts what is allowed or approved, as work of its own, and an answer is
        # done by the message itself (D18); then the code writes the status part.
        for a in judged:
            if a.status in (ledger.ALLOWED, ledger.APPROVED):
                a.status = ledger.DONE if a.answer_only or a.access else ledger.STARTED
        lines = [line[2:] for line in ledger.status_lines(judged, language=case.get(
            "language") or "en", owner=OWNER)]
        if lines != want:
            bad.append("the status part would say " + json.dumps(lines) + ", not "
                       + json.dumps(want))
        text = ledger.compose("Hi Sam,\n\nYour plans are in.\n\nBest regards,\nRouh",
                              judged, language="en", owner=OWNER)
        if not text.rstrip().endswith("Rouh"):
            bad.append("the sign-off is not last: " + json.dumps(text))
        if ledger.all_approved(judged):
            # Every ask allowed and started: she is not told which checks passed (D20).
            if "Where your requests stand:" in text:
                bad.append("every ask was allowed and started, and the reply still lists "
                           "where they stand: " + json.dumps(text))
        elif "Where your requests stand:" not in text:
            bad.append("the status part was not put above the sign-off: " + json.dumps(text))
    return bad


def replay() -> list[tuple[str, list[str]]]:
    """Every case and guard of the replay set: (its name, what went wrong)."""
    from . import grants

    data = json.loads(FIXTURES.read_text())
    tree = grants.seed_tree()
    out = []
    for case in data["cases"]:
        out.append((f"case {case['case']}: {case['what']}", judge_one(case, data["contacts"],
                                                                      tree)))
    for guard in data["guards"]:
        out.append((f"guard: {guard['name']}", judge_one(guard, data["contacts"], tree)))
    return out


def same_request() -> list[tuple[str, list[str]]]:
    """One case per request (D7): a forward of a message already in a case is that case."""
    from . import mail_ledger as ledger

    original = ("Hello Rouh,\n\nI hope you are well. I would like your help with something.\n\nSome "
                "background: the studio I run (Fernwood Studio) is having its workshop refitted "
                "by a firm called Brightline.")
    forward = ("I forgot to ask: could you confirm the email below reached you?\n\n"
               "---------- Forwarded message ---------\n"
               "From: SAM Rivera <sam@example.org>\n"
               "Date: Fri, Oct 2, 2026 at 9:15 AM\n"
               "Subject: could you look over the Brightline quote\n"
               "To: rouh@example.com <rouh@example.com>\n\n\n" + original)
    other = "Hey Rouh, a different request altogether: what is the weather like in Eastmere now?"
    own = ledger.message_key("sam@example.org",
                             "could you look over the Brightline quote", original)
    bad = []
    if not own or ledger.forward_key(forward) != own:
        bad.append("case 11's forward of case 10's email is not found to be the same request")
    if ledger.message_key("sam@example.org", "Re: weather", other) == own:
        bad.append("a different request was taken for the same one")
    if ledger.forward_key(original):
        bad.append("a message that forwards nothing was taken for a forward")
    return [("one case per request: case 11 forwards case 10", bad)]


def clockwork_items() -> list[tuple[str, list[str]]]:
    """A contact's Clockwork item is checked when it runs, against what they hold then (Petar,
    12 October 2026): it runs while they hold every grant it needs, and stops, saying why, once
    one is taken away. Telling the owner needs Clockwork alone; anything to them, Communication."""
    from types import SimpleNamespace

    from . import clockwork_grants as cw
    from . import grants

    data = json.loads(FIXTURES.read_text())
    tree = grants.seed_tree()
    sam = _contact(data["contacts"]["sam"])
    bad = []
    rows = {
        "a reminder to the owner": SimpleNamespace(goes_to="", uses=[]),
        "a reminder to both of them": SimpleNamespace(goes_to=cw.BOTH, uses=[]),
        "a note in the owner's memory every Friday": SimpleNamespace(goes_to="", uses=["memory"]),
    }
    for name, row in rows.items():
        why = cw.refusal(sam, tree, cw.needs(row), now=True)
        if why:
            bad.append(f"{name} would not run for Sam with her grants: {why}")
    without = _contact({**data["contacts"]["sam"],
                        "extra_grants": ["clockwork", "shared_task"]})
    why = cw.refusal(without, tree, cw.needs(rows["a note in the owner's memory every Friday"]),
                     now=True)
    if "no longer holds Memory" not in why:
        bad.append("a note in the owner's memory still runs once Memory was taken away: "
                   + (why or "it would run"))
    if cw.refusal(without, tree, cw.needs(rows["a reminder to both of them"]), now=True):
        bad.append("a reminder to both of them stopped although only Memory was taken away")
    alone = _contact(data["contacts"]["clockwork_only"])
    if cw.refusal(alone, tree, cw.needs(rows["a reminder to the owner"]), now=True):
        bad.append("telling the owner at a time needs more than Clockwork")
    if not cw.refusal(alone, tree, cw.needs(rows["a reminder to both of them"]), now=True):
        bad.append("a reminder to them runs without Communication")
    return [("Clockwork: an item runs on the grants held when it runs, and stops without them",
             bad)]


def states() -> list[tuple[str, list[str]]]:
    """Where a case says it is (MAIL.md, D14 to D17), through `case_state.of`, the one function
    its page, the link Rouh reads and the list of cases call: its words, whether it is running,
    its next action - the main option of the decision `case_state` makes for it, or Redo - and
    which failed asks a run would do now. And that no case waiting for the owner is without an
    action (`case_state.unactionable`)."""
    from . import case_state, grants
    from . import mail_ledger as ledger

    data = json.loads(FIXTURES.read_text())
    tree = grants.seed_tree()
    out = []
    for one in data.get("states") or []:
        contact = _contact(data["contacts"][one["who"]])
        asks = _asks(one["asks"])
        for a, raw in zip(asks, one["asks"]):
            a.why = raw.get("why") or ""
        judged = ledger.rejudge(asks, contact, tree)
        decision = None
        if one.get("decision") == "open":
            items = case_state.decision_items(judged, listed=True, tree=tree,
                                              name=contact.name)
            decision = {"id": 1, "number": 1, "status": "open",
                        "options": case_state.decision_options(items, link="/mail/case/x")}
        live = case_state.Live(turn=bool(one.get("turn")), jobs=dict(one.get("jobs") or {}))
        state = case_state.of(one["stage"], judged, live=live, decision=decision,
                              redo_refusal=one.get("redo_refusal") or "", tree=tree,
                              contact_name=contact.name)
        want, bad = one["expect"], []
        if state.words != want["words"]:
            bad.append(f"it says {state.words!r}, not {want['words']!r}")
        if state.working != want["working"]:
            bad.append("it says it is running" if state.working else
                       "it says it is not running")
        got = (state.action or {}).get("label")
        if got != want.get("action"):
            bad.append(f"its next action is {got!r}, not {want.get('action')!r}")
        if "possible" in want and [a.quote for a in state.possible] != want["possible"]:
            bad.append("possible now: " + json.dumps([a.quote for a in state.possible])
                       + ", not " + json.dumps(want["possible"]))
        if want.get("line") and state.line != want["line"]:
            bad.append(f"its line is {state.line!r}, not {want['line']!r}")
        why = case_state.unactionable(state)
        if why:
            bad.append(f"it waits with nothing to press: {why}")
        if decision is not None:
            why = case_state.decision_unactionable(decision["options"])
            if why:
                bad.append(f"its decision has nothing to press: {why}")
        out.append((f"state: {one['name']}", bad))
    return out


def _start(asks, started: dict, attempt: int = 1):
    """What the start does to the asks it is given (`mail_cases.CaseDesk._started`): each with
    work started, with its handle; an answer done by the message itself."""
    from . import mail_ledger as ledger

    for a in asks:
        if a.status not in (ledger.ALLOWED, ledger.APPROVED):
            continue
        if a.answer_only:
            a.status = ledger.DONE
        elif a.quote in started:
            a.status, a.work, a.attempt = ledger.STARTED, [dict(started[a.quote])], attempt
        else:
            a.status, a.why = ledger.FAILED, "The start did not say what became of it."
    return asks


def gate() -> list[tuple[str, list[str]]]:
    """The case is an entry gate only (Petar, 11 October 2026, MAIL.md D18): what it sends and
    what it asks the owner, for the itinerary as it arrived before her grants, with the very
    functions a run uses."""
    from . import case_state, grants
    from . import mail_ledger as ledger

    data = json.loads(FIXTURES.read_text())
    g = data["gate"]
    tree = grants.seed_tree()
    raw = next(c for c in data["cases"] if str(c["case"]) == g["case"])
    before = _contact(data["contacts"][raw["who"]])
    out = []

    # 1. A message with mixed asks: one first message, started and waiting, and a decision
    #    listing exactly what waits.
    asks = _start(ledger.judge(_asks(raw["asks"]), before, tree), g["started"])
    for a, one in zip(asks, raw["asks"]):
        a.label = one.get("label") or ""
    text = ledger.first_email(g["content"], asks, language="en", owner=OWNER, first=FIRST)
    bad = []
    lines = [x[2:] for x in text.splitlines() if x.startswith("- ")]
    if lines != g["first_email"]:
        bad.append("the first message says " + json.dumps(lines) + ", not "
                   + json.dumps(g["first_email"]))
    for tail in (f"I'll write again once {OWNER} has decided.",
                 "What each started one brings reaches you from it, as it is ready."):
        if tail not in text:
            bad.append(f"the first message does not say {tail!r}")
    if not text.rstrip().endswith("Rouh") or text.count("Where your requests stand:") != 1:
        bad.append("the first message is not one message with its status part above the "
                   "sign-off: " + json.dumps(text))
    items = case_state.decision_items(asks, listed=True, tree=tree, name=before.name)
    if [i["ask"] for i in items] != g["decision_waits"]:
        bad.append("its decision lists " + json.dumps([i["ask"] for i in items]) + ", not "
                   + json.dumps(g["decision_waits"]))
    if ledger.rest_stage(asks) != ledger.AWAITING:
        bad.append(f"it rests {ledger.rest_stage(asks)}, not waiting for the owner")
    out.append(("gate: a message with mixed asks sends one first message, started and waiting",
                bad))
    first_said = ledger.said_state(asks)

    # 1b. Every ask allowed and started: the first message is the content alone, with no list of
    #     which checks passed (D20).
    whole = next(c for c in data["cases"] if str(c["case"]) == "42")
    all_in = ledger.judge(_asks(whole["asks"]), _contact(data["contacts"][whole["who"]]), tree)
    all_in = _start(all_in, {a.quote: {"kind": "job", "ref": f"j{n}", "title": f"Job j{n}"}
                             for n, a in enumerate(all_in)})
    text = ledger.first_email(g["content"], all_in, language="en", owner=OWNER,
                              first=FIRST)
    bad = []
    if not ledger.all_approved(all_in):
        bad.append("not every ask of case 42 came out started")
    if "Where your requests stand:" in text or any(x.startswith("- ") for x in
                                                   text.splitlines()):
        bad.append("the first message lists where the asks stand: " + json.dumps(text))
    if "your Oslo tickets and your plans are in hand" not in text or \
            not text.rstrip().endswith("Rouh"):
        bad.append("the first message lost its content or sign-off: " + json.dumps(text))
    out.append(("gate: a message with every ask allowed sends no list of where they stand",
                bad))

    # 2. One batch of the owner's decisions: one message, and nothing more while nothing changed.
    b = g["batch"]
    after = _contact(data["contacts"][b["who"]])
    for a in asks:
        a.choice = b["choices"].get(a.quote, a.choice)
    asks = _start(ledger.judge(asks, after, tree), b["started"], attempt=2)
    text = ledger.decided_email(asks, first_said, language="en", owner=OWNER, first=FIRST)
    bad = []
    lines = [x for x in text.splitlines() if x.startswith("- ")]
    if lines != b["lines"]:
        bad.append("the batch's message says " + json.dumps(lines) + ", not "
                   + json.dumps(b["lines"]))
    if f"{OWNER} wrote" in text:
        bad.append("a decline carries a reason the owner did not write")
    with_reason = ledger.decided_email(asks, first_said, language="en", owner=OWNER,
                                       first=FIRST, reason=b["reason"])
    if b["reason_line"] not in with_reason:
        bad.append("his own reason is not beside the decline: " + json.dumps(with_reason))
    if ledger.decided_email(asks, ledger.said_state(asks), language="en", owner=OWNER,
                            first=FIRST):
        bad.append("a second message would go for the same batch")
    if ledger.needs_owner(asks) or ledger.rest_stage(asks) != ledger.DONE_STAGE:
        bad.append("after the batch something still waits for the owner: "
                   + json.dumps([a.quote for a in ledger.needs_owner(asks)]))
    out.append(("gate: one batch of the owner's decisions sends one message", bad))
    batch_said = ledger.said_state(asks)

    # 3. A started job fails: the case raises no decision, and nothing goes.
    f = g["failure"]
    result, needs, _paths = ledger.job_result(f["report"], after.name)
    judged = ledger.rejudge(asks, after, tree)
    bad = []
    if result or needs:
        bad.append(f"a failed job's report gave {result!r} and {needs!r}")
    job = [a for a in judged if any(w.get("ref") == f["job"] for w in a.work)]
    if not job or any(a.status != ledger.STARTED for a in job):
        bad.append("the ask its job was started for is no longer started")
    if case_state.decision_items(judged, listed=True, tree=tree, name=after.name):
        bad.append("a failed job made a decision for the owner")
    if ledger.decided_email(judged, batch_said, language="en", owner=OWNER, first=FIRST) or \
            ledger.blocked_email([], first=FIRST):
        bad.append("a failed job made the gate send something")
    out.append(("gate: a work failure raises no decision and sends nothing", bad))

    # 4. A job needs what the gate did not decide: what it needs is put on the ask it was
    #    started for, which waits in a decision, and the contact is told that ask waits; no
    #    new ask is made (D29); its result for her is its own.
    r = g["raised"]
    result, needs, _paths = ledger.job_result(r["report"], after.name)
    bad = []
    if result != r["result"]:
        bad.append(f"the job's words for her came out {result!r}, not {r['result']!r}")
    at = next(i for i, a in enumerate(asks) if any(w.get("ref") == r["job"] for w in a.work))
    stopped = asks[at]
    for one in needs:
        stopped = ledger.blocked(stopped, one["what"], need=one["need"], attempt=2)
    stopped = ledger.judge([stopped], after, tree,
                           inbox=ledger.Inbox(reach=after.inbox_scope))[0]
    now = asks[:at] + [stopped] + asks[at + 1:]
    if len(now) != len(asks) or stopped.quote != asks[at].quote:
        bad.append("what the job needs became an ask of its own")
    if stopped.status != r["expect"]:
        bad.append(f"the ask the job stopped came out {stopped.status}, not {r['expect']}: "
                   f"{stopped.why}")
    items = case_state.decision_items(now, listed=True, tree=tree, name=after.name)
    if [i["id"] for i in items] != [stopped.ident]:
        bad.append("the decision does not list exactly the ask the job stopped: "
                   + json.dumps([i["ask"] for i in items]))
    told = ledger.blocked_email([stopped], language="en", owner=OWNER, first=FIRST)
    if not told or ledger._label(stopped) not in told:
        bad.append("she is not told her ask waits: " + json.dumps(told))
    out.append(("gate: work that needs a grant or a hard limit puts it on the ask it stopped, "
                "never a new ask", bad))

    # 5. Results that finish together go in one message.
    text = ledger.results_email(g["grouped"], language="en", owner=OWNER, first=FIRST)
    bad = []
    if any(one["text"] not in text for one in g["grouped"]) or \
            text.count("here is what came of your request") != 1:
        bad.append("two results that finished together are not one message: "
                   + json.dumps(text))
    out.append(("gate: results that finish together go in one message", bad))
    return out


def _ledger_of(raw: list[dict]):
    """Asks as a case's rows hold them, statuses and all, for `phantoms`."""
    from . import mail_ledger as ledger

    asks = _asks(raw)
    for a, one in zip(asks, raw):
        a.source = one.get("source") or "reading"
        a.why = one.get("why") or ""
        a.blocker = one.get("blocker") or ""
        a.attempt = int(one.get("attempt") or 1)
        if one.get("serves"):
            a.serves = asks[int(one["serves"]) - 1].ident
        if one.get("status") == ledger.DONE:
            a.evidence = [ledger.evidence_line("done", attempt=a.attempt)]
    return asks


def phantoms() -> list[tuple[str, list[str]]]:
    """Case 51 as it stood on 16 October 2026 (MAIL.md D29), and the three rules it
    broke: a blocker is never an ask, a run that finds nothing left to do is done and never
    failed, and a permission she holds is never asked for, nor a decision put to the owner when
    every ask goes as it is."""
    from . import case_state, grants
    from . import mail_ledger as ledger

    data = json.loads(FIXTURES.read_text())
    p = data["phantoms"]
    tree = grants.seed_tree()
    sam = _contact(data["contacts"][p["who"]])
    out = []

    # 1. The ask the work made up of a tool's refusal is folded away: the ask it served is
    #    done and she may edit task 90 now, so nothing is left of it. Every real ask is done,
    #    the case rests done, and nothing is put to the owner.
    asks = _ledger_of(p["asks"])
    every = ledger.rejudge(asks, sam, tree, tasks=p["tasks"])
    now = ledger.live(every)
    bad = []
    if len(every) != len(asks) or [a.ident for a in every] != [a.ident for a in asks]:
        bad.append("judging again changed which asks there are, not only what became of them")
    if [a.quote for a in now] != [a.quote for a in asks if a.source != "work"]:
        bad.append("the asks left are not her own: " + json.dumps([a.quote for a in now]))
    if any(a.status != ledger.DONE for a in now):
        bad.append("not every ask of hers is done: " + json.dumps([a.status for a in now]))
    if ledger.rest_stage(now) != ledger.DONE_STAGE:
        bad.append(f"it rests {ledger.rest_stage(now)}, not done")
    if case_state.decision_items(now, listed=True, tree=tree, name=sam.name):
        bad.append("a decision is still put to the owner")
    gone = every[-1]
    if not gone.gone or gone.status != ledger.DONE:
        bad.append(f"the made-up ask came out {gone.status}, gone {gone.gone}, not done and gone")
    out.append(("case 51: the ask the work made up is cleared, and her three asks are done",
                bad))

    # 2. A blocker is never an ask: one that is not met yet goes onto the ask it served, which
    #    waits for her task's edit permission.
    read = {k: {**v, "level": "view"} for k, v in p["tasks"].items()}
    raw = [dict(one) for one in p["asks"]]
    raw[2]["status"] = ledger.FAILED
    asks = _ledger_of(raw)
    now = ledger.live(ledger.rejudge(asks, sam, tree, tasks=read))
    bad = []
    if len(now) != 3:
        bad.append(f"{len(now)} asks are left, not her 3")
    served = now[2]
    if served.status != ledger.WAITING or ledger.need_named(served) != \
            "permission to edit task 90":
        bad.append(f"the ask it served came out {served.status}, needing "
                   f"{ledger.need_named(served)!r}: {served.why}")
    items = case_state.decision_items(now, listed=True, tree=tree, name=sam.name)
    if [i["id"] for i in items] != [served.ident] or items[0]["task"] != "90" or \
            ledger.GRANT not in items[0]["options"]:
        bad.append("the decision does not offer letting her edit task 90 for that one ask: "
                   + json.dumps(items))
    out.append(("case 51: a blocker not met yet waits on her own ask, never as an ask of its "
                "own", bad))

    # 3. A run that finds the work done already is done, never failed.
    again = ledger.started_as(_ledger_of(p["asks"])[2], p["retry"], [], attempt=4)
    bad = []
    if again.status != ledger.DONE or "could not be started" in again.why.lower():
        bad.append(f"a run that found it done already came out {again.status}: {again.why}")
    if not again.evidence or "already succeeded" not in again.evidence[-1]["said"]:
        bad.append("what showed it done is not kept as its evidence")
    out.append(("a run that finds nothing left to do is done, never failed", bad))

    # 4. A permission she holds is never asked for: no task permission and no grant to give,
    #    and with nothing to choose there is no decision - it runs as it is, a failure of the
    #    run that ended last included, until it has failed MAX_TRIES times (D34).
    held = _ledger_of([p["held"]])
    now = ledger.rejudge(held, sam, tree, tasks=p["tasks"])
    bad = []
    if not now[0].possible or not case_state.goes_as_it_is(now[0]):
        bad.append(f"a failed ask she holds what it needs for is not one a run does: "
                   f"{now[0].why}")
    items = case_state.decision_items(now, listed=True, tree=tree, name=sam.name)
    if any(i.get("task") or ledger.GRANT in i["options"] or ledger.ONCE in i["options"]
           for i in items):
        bad.append("a permission she holds is offered to her again: " + json.dumps(items))
    if not case_state.runs_itself(now, p["attempt"]):
        bad.append("with nothing to choose it does not run as it is")
    # Since 21 October 2026 (D34) a covered ask that failed is tried again by itself, as
    # ordinary work, until it has failed `ledger.MAX_TRIES` times: then it stops.
    if not case_state.runs_itself(now, now[0].attempt):
        bad.append("a covered ask the last run failed is not tried again by itself")
    spent = [ledger.failed_as(now[0], "The tool refused it.", attempt=k)
             for k in range(ledger.MAX_TRIES)][-1]
    spent = ledger.Ask(**{**spent.as_dict(), "evidence": [
        {"failed": True, "said": "The tool refused it.", "attempt": k}
        for k in range(ledger.MAX_TRIES)]})
    spent = ledger.rejudge([spent], sam, tree, tasks=p["tasks"])
    if case_state.runs_itself(spent, 9) or case_state.tries_again(spent):
        bad.append(f"an ask that failed {ledger.MAX_TRIES} times is tried again by itself")
    waiting = ledger.judge(_ledger_of([p["read_only"]]), sam, tree,
                           tasks={k: {**v, "level": "view"} for k, v in p["tasks"].items()})
    items = case_state.decision_items(waiting, listed=True, tree=tree, name=sam.name)
    if not items or items[0]["task"] != "90" or case_state.runs_itself(waiting, 1):
        bad.append("a task she may only read is not put to the owner as letting her edit it")
    out.append(("a permission she holds is never asked for, and nothing to choose is no "
                "decision", bad))
    return out


def _read(raw: list[dict], message: str):
    """A reading as the code keeps it: each ask through its action (`case_actions.apply`), as
    `mail_cases.clean_asks` does, with what is wrong when the reading is refused."""
    from . import case_actions
    from . import mail_ledger as ledger

    out, wrong = [], []
    for n, one in enumerate(raw, start=1):
        got, why = case_actions.apply(one, n, message=message)
        if why:
            wrong.append(why)
            continue
        out.append(ledger.Ask(ident=ledger.ident_of(got["ask"]), quote=got["ask"], n=n,
                              action=got.get("action") or "", label=got.get("label") or "",
                              do=got.get("do") or "", grant=got.get("grant") or "",
                              hard_limit=got.get("hard_limit") or "", task=got.get("task") or "",
                              task_needs=ledger.needs_of(got.get("task_needs"))))
    return out, wrong


def readings() -> list[tuple[str, list[str]]]:
    """Case 53 as it was read and run three times (MAIL.md D34, Petar, 21 October
    2026): her ask for edit rights was labelled three ways, the last a hard limit on the owner's
    accounts and passwords inferred from "talk to you in the interface"."""
    from . import case_actions, case_state, grants
    from . import mail_ledger as ledger

    data = json.loads(FIXTURES.read_text())
    r = data["readings"]
    tree = grants.seed_tree()
    sam = _contact(data["contacts"][r["who"]])
    out = []

    # 1. The same message read twice gives the same reading: what the second reading makes of
    #    an ask already understood is replaced by the first's, while the words are the same.
    first, wrong = _read(r["first"], r["message"])
    second, wrong2 = _read(r["second"], r["message"])
    bad = [f"the reading was refused: {w}" for w in wrong + wrong2]
    settled = ledger.settled_of(first)
    kept = ledger.keep_settled(second, settled)
    for a, b in zip(first, kept):
        diff = [k for k in ("ident", "quote", *ledger.READING) if getattr(a, k) != getattr(b, k)]
        if diff:
            bad.append(f"\"{a.quote[:50]}\" read again differs in {', '.join(diff)}")
    if ledger.reading_key("s", r["message"]) == ledger.reading_key("s", r["message"], "do it"):
        bad.append("the owner's own words do not make a new reading")
    judged = ledger.judge(kept, sam, tree, tasks=r["tasks"])
    access = next((a for a in judged if a.access), None)
    if access is None or access.status != ledger.ALLOWED:
        bad.append("her ask for edit rights, which her decide on 128 covers, does not go")
    out.append(("the same message read twice gives the same reading", bad))

    # 2. "Talk to you in the interface" is never a hard limit: not at the reading, not as a
    #    run's need, and not kept when the case is judged again; words that ask for an effect
    #    still name one.
    bad = []
    for n, one in enumerate(r["not_limits"], start=1):
        got, why = case_actions.apply(one, n, message=r["message"])
        if not why:
            bad.append(f"{one.get('hard_limit')} was taken from "
                       f"\"{one.get('effect_words') or one['ask'][:60]}\"")
    if case_actions.asks_for("accounts", r["not_limits"][0]["ask"]):
        bad.append("a run's need for accounts on her ask would be put to the owner")
    for one in r["limits"]:
        got, why = case_actions.apply(one, 1, message=one["message"])
        if why or got.get("hard_limit") != one["hard_limit"]:
            bad.append(f"\"{one['effect_words']}\" no longer names {one['hard_limit']}: {why}")
        if not case_actions.asks_for(one["hard_limit"], one["ask"]):
            bad.append(f"a run's need for {one['hard_limit']} on \"{one['ask']}\" is dropped")
    inferred = _ledger_of([r["run_inferred"]])
    back = ledger.settle(inferred, settled)[0]
    if back.hard_limit or back.task != "128" or back.choice or back.blocker:
        bad.append(f"judged again, the run's hard limit stays: {back.hard_limit or ''} task "
                   f"{back.task}, choice {back.choice or 'none'}")
    now = ledger.judge([back], sam, tree, tasks=r["tasks"])[0]
    if now.status != ledger.ALLOWED or not now.access:
        bad.append(f"judged again, her ask is {now.status}: {now.why}")
    if ledger.need_named(now).startswith("a hard limit"):
        bad.append("what it needs is said as a hard limit")
    out.append(("\"talk to you in the workspace\" never becomes a hard limit", bad))

    # 3. A covered ask that fails is tried again by itself, as ordinary work, and never becomes
    #    a decision, even while something else waits for the owner; after MAX_TRIES failures it
    #    stops and the contact is told, still with no decision.
    bad = []
    failed = ledger.failed_as(_ledger_of([r["covered_failed"]])[0], "The job could not be "
                              "started.", attempt=1)
    asks = ledger.rejudge([failed, *_ledger_of([r["waiting"]])], sam, tree)
    items = case_state.decision_items(asks, listed=True, tree=tree, name=sam.name)
    if any(i["id"] == failed.ident for i in items):
        bad.append("the covered failure is put to the owner as a decision")
    if [i["status"] for i in items] != [ledger.WAITING]:
        bad.append(f"what waits for the owner is not the one decision: {items}")
    if not case_state.tries_again(asks):
        bad.append("the covered failure is not tried again by itself")
    if not asks[0].possible:
        bad.append("the covered failure is not said to be one a run does")
    retried = ledger.judge(asks, sam, tree)
    if retried[0].status != ledger.ALLOWED or retried[1].status != ledger.WAITING:
        bad.append("trying it again does not start it, or starts what waits")
    spent = failed
    for k in range(2, ledger.MAX_TRIES + 1):
        spent = ledger.failed_as(ledger.Ask(**{**spent.as_dict(), "status": ledger.ALLOWED}),
                                 "The job could not be started.", attempt=k)
    spent = ledger.rejudge([spent], sam, tree)
    if case_state.tries_again(spent) or case_state.runs_itself(spent, 9):
        bad.append(f"it is still tried after {ledger.MAX_TRIES} failures")
    if case_state.decision_items(spent, listed=True, tree=tree, name=sam.name):
        bad.append("after its last failure it becomes a decision")
    told = ledger.decided_email(spent, [[failed.ident, ledger.ALLOWED]], owner=OWNER,
                                first=FIRST)
    if "could not be done" not in told:
        bad.append(f"the contact is not told it could not be done: {told!r}")
    out.append(("a covered ask that fails is tried again and makes no decision", bad))

    # 4. The reader is given the sender's permissions: every task by its level, the inherited
    #    ones with the task they come through, and what each level lets them do.
    said = "\n".join(case_actions.tasks_said(r["tasks"], FIRST, OWNER))
    bad = []
    for want in ("decides for", "128 Open-source legal and foundation",
                 "129 Foundation and ownership (through 128)", "may only read: 98 Open-sourcing",
                 "use Ask AI"):
        if want not in said:
            bad.append(f"the reader is not told \"{want}\": {said!r}")
    source = (HERE / "mail_cases.py").read_text()
    tree_ = ast.parse(source)
    for name in ("brief_assess", "brief_carry_out"):
        fn = next((n for n in ast.walk(tree_) if isinstance(n, ast.FunctionDef)
                   and n.name == name), None)
        if fn is None or "tasks_said(" not in ast.unparse(fn):
            bad.append(f"{name} does not give the turn the sender's permissions")
    if "for_judge" not in ast.unparse(next(n for n in ast.walk(tree_) if isinstance(
            n, ast.AsyncFunctionDef) and n.name == "_start_turn")).split("brief_carry_out")[1]:
        bad.append("the start is not given the permission record's levels")
    line = ledger.access_line("128", r["tasks"])
    if "128, 129, 130 and 131" not in line or "Ask AI" not in line:
        bad.append(f"what she may do now is not said whole: {line!r}")
    out.append(("the sender's permissions are given to the reader", bad))
    return out


def outbox_guard() -> list[tuple[str, list[str]]]:
    """No module but the outbox sends to somebody who is not the owner (D5)."""
    bad = []
    for path in sorted(HERE.rglob("*.py")):
        rel = path.relative_to(HERE).as_posix()
        if rel.startswith(("migrations/", "testing/")) or rel == "mail_outbox.py":
            continue
        try:
            tree = ast.parse(path.read_text(), filename=rel)
        except SyntaxError as exc:
            bad.append(f"{rel} does not parse: {exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            name = node.func.attr
            if name not in SENDS:
                continue
            target = ast.unparse(node.func.value).lower()
            chat = any(k.arg == "chat" and not (isinstance(k.value, ast.Constant)
                                                and k.value.value is None)
                       for k in node.keywords)
            if name == "post_message" and "slack" in target and rel not in ALLOWED_SLACK_SENDS:
                bad.append(f"{rel}:{node.lineno} posts a Slack message "
                           f"({ast.unparse(node)[:90]}): only rouh/mail_outbox.py may, for a case")
            if chat and "telegram" in target and rel not in ALLOWED_CHAT_SENDS:
                bad.append(f"{rel}:{node.lineno} sends a Telegram message to another chat "
                           f"({ast.unparse(node)[:90]}): only rouh/mail_outbox.py may")
            if rel in GUARDED and ("gmail" in target or name in ("forward", "forward_thread",
                                                                   "send_draft")):
                bad.append(f"{rel}:{node.lineno} sends mail itself "
                           f"({ast.unparse(node)[:90]}): only rouh/mail_outbox.py may")
    return [("the one outbox: nothing else sends to a contact", bad)]


def grants_as_data() -> list[tuple[str, list[str]]]:
    """Grants as data (MAIL.md D35, CAPABILITIES.md, Petar, 21 October 2026): what code decides
    about a grant, the same way every time. Every capability's contract is locked; a grant covers
    its own contact, scope, limits and lifetime and nothing else; a proposal is never a wildcard;
    a contract that grew suspends what was given for it; a call the catalogue does not declare,
    or whose arguments go beyond what was allowed, does not run; and a reading may not write a
    grant."""
    import datetime as dt
    import time as clock
    from types import SimpleNamespace

    from . import capabilities as caps
    from . import case_actions

    found = caps.catalogue()
    out = []
    out.append(("every capability's contract is locked",
                caps.lock_problems(found, caps.read_lock())))

    bad = []
    lock = caps.read_lock()
    note = found.caps["memory.note"]
    cal = found.caps["calendar.write"]
    cw = found.caps["clockwork.item"]
    sam = SimpleNamespace(id=4, name="Sam Rivera", trusted=True, implicit=False)
    elena = SimpleNamespace(id=1, name="Elena P", trusted=True, implicit=False)
    p = caps.propose(note, sam.id)
    row = {**p, "id": 7, "contact": 4, "state": caps.ACTIVE, "wording": "", "used": 0}
    if not caps.authorize(note, sam, rows=[row], lock=lock).ok:
        bad.append("a grant given to Sam does not cover her")
    if caps.authorize(note, elena, rows=[row], lock=lock).ok:
        bad.append("Sam's grant covers Elena")
    if caps.authorize(note, sam, rows=[{**row, "state": caps.REVOKED}], lock=lock).ok:
        bad.append("a grant taken back still covers")
    gone = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    if caps.authorize(note, sam, rows=[{**row, "lifetime": caps.UNTIL, "until": gone,
                                          "expires_at": caps.ends_at(gone)}], lock=lock).ok:
        bad.append("a grant past its last day still covers")
    if caps.authorize(note, sam, rows=[row], lock=lock,
                      used_today={7: p["limits"]["per_day"]}).ok:
        bad.append("a grant used as often as it allows a day still covers that day")
    once = {**row, "lifetime": caps.ONCE, "case_key": "caseA", "ask_ident": "a1", "max_uses": 1}
    if caps.authorize(note, sam, rows=[once], lock=lock, case_key="caseB", ask="a1").ok:
        bad.append("a grant allowed once for one message covers another")
    if caps.authorize(note, sam, rows=[once], lock=lock, case_key="", ask="a1").ok:
        bad.append("a grant allowed once covers a judgement that names no message")
    calp = caps.propose(cal, sam.id, ["family@group"])
    calrow = {**calp, "id": 8, "contact": 4, "state": caps.ACTIVE}
    if caps.authorize(cal, sam, scope=["work@group"], rows=[calrow], lock=lock).ok:
        bad.append("a calendar grant reaches a calendar it does not name")
    if not caps.authorize(cal, sam, scope=["family@group"], rows=[calrow], lock=lock).ok:
        bad.append("a calendar grant does not reach the calendar it names")
    if not caps.validate(caps.propose(cal, 4, []), cal):
        bad.append("a calendar grant with no calendars is a grant")
    if not caps.validate({**calp, "scope": ["*"]}, cal):
        bad.append("a wildcard is a scope")
    if not caps.validate({**p, "limits": {}}, note):
        bad.append("a grant that leaves out a limit is a grant")
    if not caps.validate({**p, "limits": {"per_day": 999}}, note):
        bad.append("a limit beyond its bounds is a grant")
    if not caps.validate(caps.propose(found.caps["tasks.change"], 4, ["128"]),
                         found.caps["tasks.change"]):
        bad.append("a task's own permission is given as a grant")
    if caps.digest(p) == caps.digest({**p, "limits": {"per_day": 2}}):
        bad.append("a narrowed grant has the digest of the one shown before")
    if "Sam" not in caps.wording(p, note, "Sam") or "3 a day" not in caps.wording(p, note, "Sam"):
        bad.append("the sentence does not say who and how many: " + caps.wording(p, note, "Sam"))
    out.append(("a grant covers its own contact, scope, limits and lifetime, and nothing else",
                bad))

    bad = []
    old = caps.contract(note)
    grown = {**old, "effects": sorted(old["effects"] + ["third_party"])}
    if caps.compatible(old, grown)[0]:
        bad.append("a capability that gained an effect is compatible")
    fewer = {**old, "tools": []}
    if not caps.compatible(old, fewer)[0]:
        bad.append("a capability that lost a tool is not compatible")
    wider = json.loads(json.dumps(old))
    wider["constraints"]["per_day"]["max"] = 99
    if caps.compatible(old, wider)[0]:
        bad.append("a capability whose limit widened is compatible")
    fake = {"memory.note": {"1": {"hash": "x", "contract": old},
                            "2": {"hash": "y", "contract": grown}}}
    later = caps.Capability(**{**note.__dict__, "version": 2})
    if caps.version_state(later, 1, fake)[0] != "suspended":
        bad.append("a grant made before its capability grew is not suspended")
    if caps.version_state(note, 9, lock)[0] != "unknown":
        bad.append("a grant for a version Rouh does not know is not refused")
    out.append(("a capability that grows never grows what was given for it", bad))

    bad = []
    authorized = [{"capability": "clockwork.item", "scope": None, "values": {"to": "them"},
                   "limits": {"to": ["them"], "per_day": 2}, "ref": "row:9", "ask": "a1"},
                  {"capability": "tasks.change", "scope": ["128"], "values": {}, "limits": {},
                   "ref": "level:128", "ask": "a2"}]
    reads = {"web_search", "case_report"}
    if caps.check_call(found, "clockwork_for_contact", {"action": "add", "to": "owner"},
                       authorized, reads=reads).ok:
        bad.append("a Clockwork item to the owner runs under a grant for items to them")
    if not caps.check_call(found, "clockwork_for_contact", {"action": "add", "to": "them"},
                           authorized, reads=reads).ok:
        bad.append("a Clockwork item to them does not run under a grant for exactly that")
    if caps.check_call(found, "shared_task", {"action": "add", "task": "98"}, authorized,
                       reads=reads).ok:
        bad.append("adding to task 98 runs for an ask about task 128")
    if caps.check_call(found, "shared_task", {"action": "create", "title": "x"}, authorized,
                       reads=reads).ok:
        bad.append("making a task runs where only changing one was allowed")
    if caps.check_call(found, "payments", {"amount": 5}, authorized, reads=reads,
                       limit_of_tool="money").ok:
        bad.append("a tool no capability declares runs")
    if not caps.check_call(found, "web_search", {}, authorized, reads=reads).ok:
        bad.append("a reading tool is refused")
    if caps.call_key("c", "t", {"a": 1}) != caps.call_key("c", "t", {"a": 1}):
        bad.append("the same call of the same case is not the same use")
    out.append(("a call runs only as far as what was allowed, on its own arguments", bad))

    bad = []
    _, why = case_actions.apply({"ask": "keep my plans", "new_grant": {"name": "Plans", "prompt":
                                                                         "anything"}}, 1)
    if not why:
        bad.append("a reading that writes a grant in words is kept")
    _, why = case_actions.apply({"ask": "keep my plans", "capability": "plans.anything"}, 1)
    if not why:
        bad.append("a capability no gene declares is kept")
    got, why = case_actions.apply({"ask": "remind me", "capability": "clockwork.item",
                                   "values": {"to": "them"}}, 1)
    if why or got.get("grant") != "clockwork" or got.get("values") != {"to": "them"}:
        bad.append(f"a Clockwork ask is not read as one: {why or got}")
    _, why = case_actions.apply({"ask": "block my dates", "capability": "calendar.write",
                                 "resource": ["*"]}, 1, message="block my dates")
    if not why:
        bad.append("an ask for every calendar is kept")
    out.append(("a reading names capabilities, never grants in words", bad))
    del clock
    return out


def main(argv=None) -> int:
    rows = [*replay(), *same_request(), *clockwork_items(), *states(), *gate(), *phantoms(),
            *readings(), *grants_as_data(), *outbox_guard()]
    failed = [(name, bad) for name, bad in rows if bad]
    for name, bad in rows:
        print(("FAIL " if bad else "ok   ") + name)
        for line in bad:
            print("     " + line)
    print()
    print(f"{len(rows) - len(failed)} of {len(rows)} passed" + (
        "" if not failed else f"; {len(failed)} failed: the mail code changed an outcome, or "
                               "something sends outside the outbox."))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
