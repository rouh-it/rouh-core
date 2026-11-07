"""Test a case: what a run would do now, with the grants as they are, and nothing sent or changed.

Petar, 11 October 2026 (D9): "Test grants, Redo and a regression replay share one engine: a dry
run of the case against the current grants that returns each ask's status with reasons and
sends, writes and schedules nothing."

**Test grants** is that engine itself, with nothing else around it: the case's ledger judged
again with the grants as they are now and the choices the owner saved on the page
(`mail_cases.CaseDesk.test_grants`, `mail_ledger.judge`), the very judge their Redo runs and the
replay of real cases runs (`rouh/mail_replay.py`). No model is asked; it answers at once, ask
by ask, with why. It is kept here as the case's latest test (`keep_grants_test`).

**Test** goes on from there as far as a run would: the reading again when a run would read
first (a case with no asks yet, or the owner's words), the start of what is allowed or approved,
and the gate's message the code would write, word for word, with its status part. Like a run,
it stops at the start: what a started ask's work does after that is the work's (D18). The models
are really asked, and that costs: the timeline says how much. Nothing is sent to anybody and
nothing lasting changes: every tool a turn calls that would send, write, schedule, edit a
calendar, add to memory, or make or share a task is recorded instead of called
(`mail_turn.MailTurn.dry`, `mail_turn.DRY_READS`), and this module never moves the case, never
writes its ledger, never makes a decision and never answers one.

The test runs on a copy of the case held in memory, in a conversation of its own that is
archived when it ends. Each step is a row of the timeline, the same shape as the case page's
Step by step: time, who, what it was given, what it decided, and the raw output, kept on a
`models.MailCaseDryRun`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace

log = logging.getLogger("rouh.case_dry_run")

#: How long one test may run before it is said to have stopped.
MOST_SECONDS = 40 * 60

#: Tests of one case kept on its page, newest first.
SHOWN = 5

#: The step of a test that carries its answer, ask by ask.
ASKS_STEP = "Ask by ask"


def _store():
    from .models import MailCaseDryRun

    return MailCaseDryRun.objects


def start_row(who, case, setup: dict) -> int:
    """A test written down as running; one at a time per case."""
    rows = _store().filter(user_id=who.user_id, org_id=who.org_id, case_id=case.id)
    running = rows.filter(state="running").first()
    if running is not None and time.time() - running.started_at < MOST_SECONDS:
        raise ValueError("A test of this case is already running: its steps show below as "
                         "they come in.")
    if running is not None:
        rows.filter(id=running.id).update(state="failed", ended_at=time.time(),
                                          said="It stopped without finishing.")
    row = _store().create(user_id=who.user_id, org_id=who.org_id, case_id=case.id,
                          state="running", started_at=time.time(), setup=setup, steps=[])
    return row.id


def _add(run_id: int, step: dict) -> None:
    row = _store().filter(id=run_id).first()
    if row is None:
        return
    row.steps = [*(row.steps or []), {"at": time.time(), **step}]
    row.save(update_fields=["steps"])


def _end(run_id: int, state: str, said: str, chat_id: str) -> None:
    from django.db.models import Sum

    from .models import LLMRequest

    cost = 0.0
    if chat_id:
        got = LLMRequest.objects.filter(session_id=chat_id).aggregate(total=Sum("cost_usd"))
        cost = float(got.get("total") or 0)
    _store().filter(id=run_id).update(state=state, said=said[:4000], ended_at=time.time(),
                                      cost=cost)


def views(who, case) -> list[dict]:
    """The case's latest tests, for its page."""
    out = []
    for row in _store().filter(user_id=who.user_id, org_id=who.org_id,
                               case_id=case.id).order_by("-id")[:SHOWN]:
        out.append({"id": row.id, "state": row.state, "said": row.said, "cost": row.cost,
                    "started": row.started_at, "ended": row.ended_at, "steps": row.steps or [],
                    "setup": row.setup or {},
                    "minutes": round(((row.ended_at or time.time()) - row.started_at) / 60, 1)})
    return out


def keep_grants_test(who, case, rows: list[dict], said: str, *, held: list[str]) -> int:
    """A Test grants kept as the case's latest test: it ran at once, with no model."""
    now = time.time()
    row = _store().create(user_id=who.user_id, org_id=who.org_id, case_id=case.id,
                          state="done", started_at=now, ended_at=now, said=said[:4000],
                          setup={"grants_only": True, "held": held},
                          steps=[{"at": now, "who": "Rouh's code", "step": ASKS_STEP,
                                  "given": {"grants held": held}, "decided": said,
                                  "raw": rows, "asks": rows}])
    return row.id


def grants_test(who, case) -> dict | None:
    """The latest Test grants of a case: {"id", "state", "said", "asks", "started", "ended"}."""
    for row in _store().filter(user_id=who.user_id, org_id=who.org_id,
                               case_id=case.id).order_by("-id")[:SHOWN]:
        if not (row.setup or {}).get("grants_only"):
            continue
        step = next((one for one in reversed(row.steps or []) if one.get("step") == ASKS_STEP),
                    {})
        from . import mail_ledger as ledger
        from .mail_cases import _stamp

        return {"id": row.id, "state": row.state, "said": row.said,
                "asks": [{**one, "said": _row_said(one),
                          **({"status": ledger.status_of(one["status"])} if one.get("status")
                             else {})} for one in step.get("asks") or []],
                "started": row.started_at, "ended": row.ended_at,
                "when": _stamp(row.ended_at or row.started_at)}
    return None


def _row_said(one: dict) -> str:
    """Where one ask would stand and why, said once: "Done, and the check saw it.", not
    "Done. Done, and the check saw it."."""
    words, why = str(one.get("words") or ""), str(one.get("why") or "")
    if not why or why.lower().startswith(words.lower()):
        return why or words
    return f"{words}. {why}"


def _shadow(case):
    """The case as the test reads it: a copy in memory."""
    from .models import MailCase

    fields = {f.attname: getattr(case, f.attname) for f in MailCase._meta.concrete_fields}
    return SimpleNamespace(**fields)


async def run(desk, who, key: str) -> int:
    """Start a Test of one case, in the background. Returns its id; ValueError says why not."""
    from . import grants

    case = await asyncio.to_thread(desk.store.by_key, who.user_id, who.org_id, key)
    if case is None:
        raise LookupError("There is no such case.")
    if getattr(desk.alerts, "converse", None) is None or \
            getattr(desk.alerts, "open_chat", None) is None:
        raise ValueError("Rouh cannot run a turn here, so nothing could be tested.")
    tree = await asyncio.to_thread(grants.tree, who.org_id)
    contact = await asyncio.to_thread(desk.contact_of, who, case)
    held = sorted(tree.held(contact)) if contact is not None else []
    setup = {"held": held, "held_names": [tree.path_said(k) for k in held]}
    run_id = await asyncio.to_thread(start_row, who, case, setup)
    task = asyncio.get_running_loop().create_task(_run(desk, who, case.id, run_id, setup))
    desk._keep(task)
    return run_id


async def _run(desk, who, case_id: int, run_id: int, setup: dict) -> None:
    chat = ""
    try:
        chat = await desk.alerts.open_chat("", "Test of an email case")
        said = await asyncio.wait_for(_steps(desk, who, case_id, run_id, chat), MOST_SECONDS)
        await asyncio.to_thread(_end, run_id, "done", said, chat)
    except asyncio.CancelledError:
        await asyncio.to_thread(_end, run_id, "failed", "It was stopped.", chat)
        raise
    except asyncio.TimeoutError:
        await asyncio.to_thread(_end, run_id, "failed",
                                f"It ran longer than {MOST_SECONDS // 60} minutes and was "
                                "stopped there.", chat)
    except Exception as exc:  # noqa: BLE001 - a test never moves the case; it says what broke
        log.exception("test %s of case %s stumbled", run_id, case_id)
        await asyncio.to_thread(_add, run_id, {"who": "Rouh's code", "step": "Stopped",
                                               "given": "", "decided": f"It stumbled: {exc}",
                                               "raw": repr(exc)[:2000]})
        await asyncio.to_thread(_end, run_id, "failed", f"It stumbled: {exc}", chat)
    finally:
        if chat:
            await asyncio.to_thread(_archive_chat, chat)


def _archive_chat(chat: str) -> None:
    from . import objects

    try:
        objects.shared_store().update_chat(chat, state="archived")
    except Exception:  # noqa: BLE001 - only where it is listed
        log.exception("the test's conversation %s could not be archived", chat)


async def _turn(desk, who, shadow, contact, tree, chat: str, mode: str, text: str,
                asks: list) -> tuple[dict | None, list[dict], str]:
    """One turn of the test: (its report or None, the tools it would have called, trouble)."""
    from . import delegation, mail_cases, mail_turn

    got: dict = {}

    def take(args: dict) -> str:
        report = desk._clean_report(args, mode, tree, message=mail_cases.message_text(shadow))
        if isinstance(report, str):
            return report
        got["report"], got["raw"] = report, args
        return ("Kept. This is a test: nothing is sent or changed. Say here in one or two "
                "sentences what you did, and stop.")

    tools, limits = desk._turn_tools(who, shadow, contact, tree, mode, asks)
    extra = tools + tuple(await asyncio.to_thread(delegation.case_tools, who, contact)) \
        if contact is not None and contact.trusted else tools
    turn = mail_turn.MailTurn(
        user_id=who.user_id, org_id=who.org_id, message_id=shadow.message_id,
        thread_id=shadow.thread_id, sender=shadow.sender, on_it=(shadow.sender,),
        sender_contact=contact.contact_id if contact is not None else "",
        relationship_known=True, chat_id=chat, link=desk.page_link(shadow.key), mode=mode,
        case_id=shadow.id, trusted_id=contact.id if contact is not None else 0,
        extra_tools=extra, granted=True, limits=limits, on_outcome=take, dry=True,
        task_edits=desk.turn_tasks(mode, asks),
        sees=getattr(contact, "sees", None) if contact is not None else None)
    limit = float(getattr(desk.alerts, "turn_minutes", 8) or 8) * 60
    finished, _said, trouble = await desk.alerts.converse(who, chat, None, text, turn, limit)
    if not finished and not got:
        trouble = trouble or "the turn did not finish"
    return got or None, list(turn.recorded), trouble or ""


def _model_of(chat: str) -> str:
    from .models import LLMRequest

    return str(LLMRequest.objects.filter(session_id=chat).order_by("-id")
               .values_list("model", flat=True).first() or "")


async def _steps(desk, who, case_id: int, run_id: int, chat: str) -> str:
    """The test itself, step by step, each written to the timeline as it ends."""
    from . import delegation, grants, mail_cases, task_access
    from . import mail_ledger as ledger

    def add(**step) -> asyncio.Future:
        return asyncio.to_thread(_add, run_id, step)

    case = await asyncio.to_thread(desk.store.get, who.user_id, who.org_id, case_id)
    contact = await asyncio.to_thread(desk.contact_of, who, case)
    if contact is None:
        await add(who="Rouh's code", step="Stopped", given="",
                  decided="The trusted contact behind this case was removed.", raw="")
        return "The trusted contact behind it was removed, so nothing could be tested."
    tree = await asyncio.to_thread(grants.tree, who.org_id)
    owner = await asyncio.to_thread(desk._owner, who)
    shadow = _shadow(case)
    asks = await asyncio.to_thread(desk._asks, who, case.id, every=True)
    reread = not ledger.live(asks) or any(a.source == "whole" and not a.gone for a in asks) \
        or bool(case.instruction)
    await add(who="Rouh's code", step="Set up",
              given={"grants held": sorted(tree.held(contact))},
              decided="A test of what a run would do now: every model is really asked, and "
                      "nothing is sent or changed.", raw={"reread": reread})
    if reread:
        text = mail_cases.brief_assess(
            shadow, contact, mailbox=await asyncio.to_thread(desk._mailbox, who), owner=owner,
            relationship=await asyncio.to_thread(desk._relationship, who, contact),
            instruction=shadow.instruction or "", tree=tree,
            authority=await asyncio.to_thread(delegation.case_paragraph, who, contact, owner),
            zone=getattr(contact, "zone", "") or "",
            tasks=await asyncio.to_thread(task_access.for_judge, who, contact))
        if mail_cases.by_message(shadow):
            head, _, rest = text.partition("\n")
            text = head + "\n\n" + mail_cases.channel_said(shadow, owner) + "\n" + rest
        got, calls, trouble = await _turn(desk, who, shadow, contact, tree, chat, "assess",
                                          text, [])
        await add(who=_model_of(chat) or "the model", step="Read", given=text,
                  decided=(got or {}).get("report", {}).get("outcome") or f"No report: {trouble}",
                  raw=(got or {}).get("raw") or trouble, recorded=calls)
        if got is None:
            return f"The reading never reported ({trouble or 'no report'}): it would stop there."
        report = got["report"]
        shadow.assessment = {"assess": report}
        shadow.approved_reply = str(report.get("reply") or "")
        read = [ledger.Ask.of(a) for a in report.get("asks") or []]
        asks = ledger.merge_reading(asks, read, attempt=case.attempt_no + 1)
    judged = await asyncio.to_thread(desk._judged, who, shadow, contact,
                                     [a for a in asks if not a.gone], tree)
    rows = [{"id": a.ident, "ask": a.quote, "label": a.label,
             "goes": a.status in (ledger.ALLOWED, ledger.APPROVED, *ledger.GONE_ON),
             "status": a.status, "words": ledger.WORDS[a.status], "why": a.why} for a in judged]
    todo = ledger.to_do(judged)
    work = [a for a in todo if not a.answer_only and not a.access]
    said = ledger.why_line(judged, tree=tree, contact_name=contact.name)
    await add(who="Rouh's code", step=ASKS_STEP, given={"grants held": sorted(tree.held(contact))},
              decided=said, raw=rows, asks=rows)
    if work:
        text = mail_cases.brief_carry_out(
            shadow, todo, owner=owner, tree=tree, others=[a for a in judged if a not in todo],
            tasks=await asyncio.to_thread(task_access.for_judge, who, contact),
            held=[tree.path_said(k) for k in sorted(tree.held(contact))])
        got, calls, trouble = await _turn(desk, who, shadow, contact, tree, chat, "carry_out",
                                          text, judged)
        await add(who=_model_of(chat) or "the model", step="Start", given=text,
                  decided=(got or {}).get("report", {}).get("outcome") or f"No report: {trouble}",
                  raw=(got or {}).get("raw") or trouble, recorded=calls)
        if got is None:
            return (f"The start never reported ({trouble or 'no report'}): its asks would fail "
                    "there.")
        started = {r["id"]: r for r in got["report"].get("asks") or []}
        for a in work:
            r = started.get(a.ident) or {}
            a.status = (ledger.DONE if r.get("done") and not r.get("started") else
                        ledger.STARTED if r.get("started") else ledger.FAILED)
        if str(got["report"].get("reply") or "").strip():
            shadow.approved_reply = str(got["report"]["reply"])
    for a in todo:
        if a.answer_only or a.access:
            a.status = ledger.DONE
    report = (shadow.assessment or {}).get("assess") or {}
    reply = ledger.first_email(shadow.approved_reply or "", judged,
                               language=ledger.language_of(report.get("language")),
                               owner=owner, first=mail_cases.first_name(contact.name))
    if reply:
        await add(who="Rouh's code", step="Would tell them",
                  given={"to": contact.name, "channel": mail_cases.channel_of(shadow)},
                  decided=f"This would go to {contact.name}, through the outbox, only if the "
                          "ledger changed since the last message that went. Nothing was sent.",
                  raw=reply)
    return ledger.why_line(judged, tree=tree, contact_name=contact.name) + \
        " Nothing was sent and nothing changed: this was a test."
