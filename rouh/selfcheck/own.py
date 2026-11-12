"""Rouh's own checks: this code runs on this base (`rouh/selfcheck/__init__.py`).

Each proves one thing a person would notice if it broke after a base update: the code no longer
imports (a library moved), Django or the migrations disagree with the code, a model call slipped
past the LLM service, the database cannot be made, or the server does not come up.
"""
from __future__ import annotations

import importlib
import os
import pkgutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import check, expect

CODE = Path(__file__).resolve().parent.parent.parent

#: Never imported by the import check: the test worlds' stand-ins (not in a release), the
#: migrations (Django loads them itself), this package, and modules that are scripts.
SKIP = ("rouh.testing", "rouh.migrations", "rouh.selfcheck", "one.tests")


def _modules(package: str) -> list[str]:
    root = CODE / package
    out = [package]
    for info in pkgutil.walk_packages([str(root)], prefix=package + "."):
        name = info.name
        if name.startswith(SKIP) or name.endswith(".__main__") or ".migrations" in name:
            continue
        out.append(name)
    return sorted(out)


@check("own", "the code imports on this base",
       "every module of Rouh and of the one program imports with this base's libraries", needs_db=True)
def imports() -> None:
    broken = []
    for package in ("rouh", "one"):
        if not (CODE / package).is_dir():
            continue
        for name in _modules(package):
            try:
                importlib.import_module(name)
            except SystemExit:
                continue
            except Exception as e:  # noqa: BLE001 - every one is a finding
                broken.append(f"{name} ({type(e).__name__}: {str(e)[:160]})")
    expect(not broken, f"{len(broken)} modules do not import: " + "; ".join(broken[:8]))


@check("own", "Django's own checks pass", "Django finds nothing wrong with the project's settings and models")
def django_check() -> None:
    from django.core.management import call_command

    call_command("check", verbosity=0)


@check("own", "the models and the migrations agree",
       "no model has a change its migrations do not have", needs_db=True)
def migrations_agree() -> None:
    from django.core.management import call_command

    try:
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)
    except SystemExit as e:
        expect(not e.code, "a model has changes no migration makes (makemigrations --check)")


@check("own", "every model call goes through the LLM service",
       "nothing asks a model past rouh/llm.py, so every call is written down and picked on the Models page")
def llm_service() -> None:
    from rouh import llmguard

    strays = llmguard.strays()
    expect(not strays, "; ".join(strays[:6]))


@check("own", "no code is tied to the old server without saying why",
       "every mention of systemd, /var/www/rouh or with-rouh-env.sh in Rouh's code is listed with why it is "
       "right in the containers too (rouh/hostguard.py)")
def host_layout() -> None:
    from rouh import hostguard

    bad = hostguard.problems()
    expect(not bad, "; ".join(bad[:4]))


@check("own", "a new Rouh hands research and real work to a job",
       "the rules a Rouh starts with when rouh.land has none to give (rouh/rule_defaults_fallback.json) "
       "tell a chat with assistant_job to hand research and longer work to it, and one without it to say "
       "plainly that such work cannot be started here")
def new_rouh_routes_work() -> None:
    """11 November 2026 (task 140): a freshly installed Rouh answered "research the best robot vacuums"
    in the chat, and still did when asked for a new task.

    Since 30 October 2026 the rules that say where work goes are the person's own, and a new Rouh gets
    them from rouh.land (`rouh/ruledefaults.py`). rouh.land has never served that document, so a new Rouh
    had only the few rules of its fallback, none of them about jobs, and its model saw assistant_job only
    as one line of the tool catalogue. This holds the fallback to the rules that route the work.
    """
    from rouh import prompting, rules, ruledefaults

    doc = ruledefaults.fallback()
    by = {r["key"]: r for r in doc["rules"]}
    for key in ("where-work-goes", "research", "no-workspace", "untrusted", "turn-marks",
                "house:written-replies", "house:spoken-replies"):
        expect(key in by, f"the fallback has no rule {key}")
    with_jobs = prompting.Situation(tools=frozenset({"assistant_job", "make_a_task", "web_search"}))
    without = prompting.Situation(tools=frozenset({"web_search"}))
    told = {k for k, r in by.items() if "chats" in rules.reach(r) and prompting.applies(rules.when_of(r), with_jobs)}
    expect({"where-work-goes", "research"} <= told, f"a chat with assistant_job is not told where work goes: {told}")
    expect("no-workspace" not in told, "a chat with assistant_job is told it has no workspace")
    expect("assistant_job" in by["research"]["text"] and "make_a_task" in by["research"]["text"],
           "the research rule no longer names assistant_job and make_a_task")
    told = {k for k, r in by.items() if "chats" in rules.reach(r) and prompting.applies(rules.when_of(r), without)}
    expect("no-workspace" in told and "where-work-goes" not in told,
           "a chat with no assistant_job is not told plainly that work cannot be started here")


@check("own", "a fork does not take up a turn stopped in the chat it came off",
       "what a fork carries of its parent has no stopped exchange in it - not the request, not what was said "
       "of it, not the stop note - and the parent's own messages keep all three")
def fork_drops_carried_stops() -> None:
    from rouh import memory
    from rouh.stopping import STOP_NOTE

    def said(text):
        return [{"type": "text", "text": text}]

    parent = [{"role": "user", "content": said("What is the weather like?")},
              {"role": "assistant", "content": said("Sunny.")},
              {"role": "user", "content": said("Move this chat under the other task.")},
              {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "look", "input": {}}]},
              {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
              {"role": "assistant", "content": said("Moving it now")},
              {"role": "user", "content": said(STOP_NOTE)}]
    before = [dict(m) for m in parent]
    carried = memory.drop_carried_stops(parent)
    words = [memory._plain(m["content"]) for m in carried]
    expect(words == ["What is the weather like?", "Sunny."],
           f"a fork carries a turn stopped in its parent: {words}")
    expect(parent == before, "the parent's own messages were changed")
    expect(memory.drop_carried_stops(parent[:2]) == parent[:2], "a fork lost words of its parent with no stop in them")


@check("own", "a change that went live quietly is not told, and one that did not go live is",
       "a change of Rouh's code that passed its checks and is an undo point makes no notification, and one "
       "the checks refused, or that failed, or that waits for a Rouh update still does")
def undo_points_are_quiet() -> None:
    import asyncio

    from rouh import codechanges, notices

    told: list[dict] = []

    async def notify(**kw):
        told.append(kw)

    def tell(got: dict) -> list[dict]:
        told.clear()
        asyncio.run(codechanges.Watch()._tell(got))
        return list(told)

    real = notices.notify
    notices.notify = notify
    try:
        live = tell({"ok": True, "commit": "a" * 40, "point": {"n": 41, "why": "a run's change"}})
        expect(not live, f"a change that went live was still told: {live}")
        again = tell({"ok": True, "commit": "b" * 40, "point": {"n": 41}, "said": "It is already in the code that runs."})
        expect(not again, f"a change already running was told: {again}")
        refused = tell({"ok": False, "commit": "c" * 40, "refused": "the checks failed: rouh.selfcheck own"})
        expect(len(refused) == 1 and refused[0]["title"] == "A change of Rouh's code did not go live"
               and "checks failed" in refused[0]["body"], f"a refused change was not told: {refused}")
        broke = tell({"ok": False, "commit": "d" * 40, "error": "the protected core did not answer"})
        expect(len(broke) == 1 and "did not answer" in broke[0]["body"], f"a change that broke was not told: {broke}")
        waits = tell({"ok": False, "commit": "e" * 40, "refused": "Waiting for a Rouh update to core 1.1"})
        expect(len(waits) == 1 and "waits for a Rouh update" in waits[0]["title"],
               f"a change waiting for an update was not told: {waits}")
    finally:
        notices.notify = real


@check("own", "the database migrates from empty", "every migration runs on an empty PostgreSQL", needs_db=True)
def migrate() -> None:
    from django.core.management import call_command

    call_command("migrate", "--noinput", verbosity=0)


@check("own", "a new task never takes another task's chat",
       "a job asked for in a fork of one task's chat leaves that fork where it is when its landing "
       "names a newer task, by its record file or by its own files, and a loose chat that asked "
       "for a task still becomes that task's chat", needs_db=True)
def made_task_keeps_other_tasks_chats() -> None:
    """30 October 2026: a fork of one task's chat became a newer task's main chat.

    A run was asked for in that fork. Its landing listed the newer task's `.object.json`,
    which Rouh had saved to main meanwhile, and `conversations.adopt_made_task` read the run
    as having made that task: the fork was cut from the older task's chat and put first in the
    newer one. This builds that shape and asks the same function.
    """
    import uuid

    from rouh import conversations
    from rouh.models.objects import Chat, ChatFork, Link, Run, Task

    st = conversations.store()
    tag = uuid.uuid4().hex[:8]
    now = time.time()
    folder = f"selfcheck-{tag}/990002.made-by-another"
    made: dict[str, list[str]] = {"task": [], "chat": [], "run": []}

    def chat(title: str) -> str:
        row = st.create_chat(title=f"{title} {tag}", created_at=now - 600)
        made["chat"].append(row.id)
        st.add_message(row.id, "user", f"words in {title}")
        return row.id

    def run(from_chat: str) -> str:
        row = st.create_run(f"selfcheck run {tag}", started_at=now - 300)
        made["run"].append(row.id)
        st.add_ref("from", "run", row.id, "chat", from_chat)
        return row.id

    try:
        old = st.create_task(f"selfcheck old task {tag}", created_at=now - 900,
                             folder=f"selfcheck-{tag}/990001.the-old-one")
        made["task"].append(old.id)
        new = st.create_task(f"selfcheck new task {tag}", created_at=now - 60, folder=folder)
        made["task"].append(new.id)
        old_chat = chat("the old task's chat")
        st.attach("task", old.id, "chat", old_chat)
        new_chat = chat("the new task's own chat")
        st.attach("task", new.id, "chat", new_chat)
        fork = chat("a fork of the old task's chat")
        ChatFork.objects.create(chat_id=fork, parent_id=old_chat, at=None, created_at=now - 500)
        asked = run(fork)

        def unmoved(why: str) -> None:
            expect(st.owner_of("chat", fork) is None, f"{why}: the fork was given to a task")
            expect(ChatFork.objects.filter(chat_id=fork, cut_at__isnull=True).exists(),
                   f"{why}: the fork was cut from the old task's chat")
            mains = [c for _k, c in st.children_of("task", new.id, "chat")]
            expect(mains == [new_chat], f"{why}: the new task's chats are now {mains}")

        # The landing named only the new task's record file, which Rouh saves itself.
        got = conversations.adopt_made_task(asked, [f"workspace/{folder}/.object.json"])
        expect(got is None, "a landing that names only a task's .object.json was read as making it")
        unmoved("after a landing naming the new task's record file")
        # Even a landing with real files in the new task: the fork stays the old task's.
        got = conversations.adopt_made_task(asked, [f"{folder}/AGENTS.md"])
        expect(got is None, "a fork of another task's chat was adopted by a task the job made")
        unmoved("after a landing with files in the new task")

        # And the behaviour this must not stop: a loose chat that asked for a task is its chat.
        loose = chat("a loose chat that asked for a task")
        got = conversations.adopt_made_task(run(loose), [f"{folder}/AGENTS.md"])
        expect(got is not None and got.id == new.id,
               "a loose chat that asked for a task did not become that task's chat")
        expect(st.owner_of("chat", loose) == ("task", new.id), "the loose chat is not the new task's")
    finally:
        every = [i for ids in made.values() for i in ids]
        Link.objects.filter(src_id__in=every).delete()
        Link.objects.filter(dst_id__in=every).delete()
        ChatFork.objects.filter(chat_id__in=made["chat"]).delete()
        Chat.objects.filter(id__in=made["chat"]).delete()
        Run.objects.filter(id__in=made["run"]).delete()
        Task.objects.filter(id__in=made["task"]).delete()


@check("own", "an old goal is still a goal after many newer tasks",
       "a task tagged a goal is on the goals list however many tasks and steps were made after "
       "it, so the Goals page and the goals tool never go empty because the workspace grew",
       needs_db=True)
def old_goal_still_listed() -> None:
    """4 November 2026: every goal disappeared from the Goals page and the goals tool.

    The goals were found by reading "every task" with `list_tasks()`, which stops at the 200
    newest rows unless told otherwise, and a goal's steps and every other task's steps are rows
    too. Once more than 200 had been made after the newest goal, none was read, and Rouh said
    the person had no goals. This makes one goal and more than 200 newer tasks after it, and
    asks the same function the page and the tool ask.
    """
    import tempfile
    import uuid

    from rouh import goals
    from rouh.models.objects import Task

    st = goals._store()
    tag = uuid.uuid4().hex[:8]
    now = time.time()
    made: list[str] = []
    real_root = goals._root
    with tempfile.TemporaryDirectory() as root:
        goals._root = lambda: root
        try:
            goal = st.create_task(f"selfcheck goal {tag}", number=990300, created_at=now - 86400,
                                  folder=f"selfcheck-{tag}/990300.an-old-goal")
            made.append(goal.id)
            Task.objects.filter(id=goal.id).update(
                meta={"tags": ["goal"], "goal": {"stage": "planned", "why": "", "chat": ""}})
            for i in range(250):
                row = st.create_task(f"selfcheck newer {tag} {i}", created_at=now - 3600 + i,
                                     folder=f"selfcheck-{tag}/990300.an-old-goal/990300-{i:03d}.s")
                made.append(row.id)
            found = {t.id for t in goals._goal_tasks()}
            expect(goal.id in found,
                   "a goal with 250 newer tasks after it is not on the goals list")
            got, why = goals.find("990300")
            expect(got is not None and got.id == goal.id,
                   f"the goal with 250 newer tasks after it cannot be found by its number: {why}")
        finally:
            goals._root = real_root
            Task.objects.filter(id__in=made).delete()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@check("own", "the count on Now is the real count, and never left behind",
       "every decision waiting is counted, however many, and when the count moves without the "
       "desk saying so, the next sync tells every tab of the person's the new one", needs_db=True)
def decisions_count_is_level() -> None:
    """4 November 2026: the count on the navigation's Now tab looked stuck at 55 or 56.

    A tab was told the count only when the desk itself moved it, and never again on connect,
    so a count told while a phone's socket was away, or a `tell` whose read failed, stayed on
    the screen for good. This writes more decisions than any page holds, moves the count behind
    the desk's back, and asks the desk's own sync step what it tells."""
    import asyncio
    import uuid
    from types import SimpleNamespace

    from rouh import decision_desk, decisions
    from rouh.models import Decision

    who = SimpleNamespace(user_id=f"selfcheck-{uuid.uuid4().hex[:8]}", org_id="")
    told: list[dict] = []

    async def push(_who, message):
        told.append(message)

    desk = decision_desk.Desk(owner=lambda: who, push=push)
    now = time.time()

    def made(n: int, start: int = 0) -> None:
        Decision.objects.bulk_create([Decision(
            user_id=who.user_id, org_id=who.org_id, source="selfcheck", source_id=str(i),
            key=f"k{i}", title=f"Question {i}", question=f"Question {i}?", status=decisions.OPEN,
            created_at=now, updated_at=now) for i in range(start, start + n)])

    try:
        made(120)
        got = decisions.counts(who)
        expect(got["open"] == 120, f"120 decisions wait and the count says {got['open']}")
        asyncio.run(desk.tell(who))
        expect(told and told[-1]["open"] == 120, f"the tabs were told {told[-1:]}")
        told.clear()
        expect(not asyncio.run(desk.level(who)) and not told,
               f"a count nothing moved was told again: {told}")
        # Two more arrive, and one is answered, with nobody telling the desk.
        made(2, start=120)
        Decision.objects.filter(user_id=who.user_id, key="k0").update(status=decisions.APPLIED)
        expect(asyncio.run(desk.level(who)) and told and told[-1]["open"] == 121,
               f"a count that moved behind the desk's back was not told: {told}")
    finally:
        Decision.objects.filter(user_id=who.user_id).delete()


@check("own", "the count on the notifications bell is every one still to read",
       "the bell counts every notification of the week still to read, not only those among the "
       "newest the list sends, and a notice asking a decision answered elsewhere is not counted",
       needs_db=True)
def notices_bell_counts_all() -> None:
    """4 November 2026: the bell looked stuck at 55 or 56. Its number was the unread among the
    60 newest notices sent to the page, so it could never pass that share, and stayed put as
    each new one pushed an old one out of the 60. This writes more than the list holds."""
    import uuid
    from types import SimpleNamespace

    from rouh import notices
    from rouh.models import Decision, Notice

    who = SimpleNamespace(user_id=f"selfcheck-{uuid.uuid4().hex[:8]}", org_id="")
    now = time.time()

    def made(n: int, state: str, at: float, **more) -> None:
        Notice.objects.bulk_create([Notice(
            user_id=who.user_id, org_id=who.org_id, kind="job", title=f"Notice {i}", state=state,
            created_at=at + i, **more) for i in range(n)])

    try:
        made(70, notices.LATER, now - 7200)     # to read, older
        made(8, notices.READ, now - 600)        # read, newest
        got = notices.listing(who)
        expect(len(got["items"]) == notices.LISTED, f"{len(got['items'])} listed")
        expect(got["unread"] == 70, f"70 wait to be read and the bell says {got['unread']}")
        # One asks a decision that was answered somewhere else: it is read, and not counted.
        d = Decision.objects.create(user_id=who.user_id, org_id=who.org_id, source="selfcheck",
                                    source_id="n", key="n", title="Q", question="Q?",
                                    status="applied", created_at=now, updated_at=now)
        made(1, notices.NEW, now - 30000, decision_id=d.id)
        expect(notices.listing(who)["unread"] == 70, "a settled decision's notice was counted")
        # A week and a day old is out of the bell, as it is out of the list.
        made(3, notices.LATER, now - (notices.KEEP_DAYS + 1) * 86400)
        expect(notices.listing(who)["unread"] == 70, "notices older than the week were counted")
    finally:
        Notice.objects.filter(user_id=who.user_id).delete()
        Decision.objects.filter(user_id=who.user_id).delete()


@check("own", "the Beats page reads beats that asked for a yes, and says when the cap stops them",
       "a beat with an approval is listed with its decision, a day spent past the daily cap says "
       "plainly that beats are paused until tomorrow, and a beat is not started with too little "
       "of the cap left to finish", needs_db=True)
def beats_page_reads_approvals_and_cap() -> None:
    """4 November 2026: the Beats page answered "Something went wrong on the server".

    From 29 October `beatlog._row` took each approval's decision number as `decided` and then
    reused the name for whether the beat reached a decision, so any beat that asked for a yes
    raised AttributeError and the whole listing failed. The same day the spend went to $6.70
    against a $6.00 cap, because a beat was started with a few cents of it left. This builds
    both shapes and asks the page's own functions."""
    import uuid
    from decimal import Decimal
    from types import SimpleNamespace

    from rouh import beatlog, heartbeat
    from rouh.models import HeartbeatApproval, HeartbeatBeat, HeartbeatState, LLMRequest

    who = SimpleNamespace(user_id=f"selfcheck-{uuid.uuid4().hex[:8]}", org_id="")
    now = time.time()
    try:
        row = heartbeat.ensure(who)
        HeartbeatState.objects.filter(id=row.id).update(daily_cap=Decimal("6.00"),
                                                        chat_id=f"{who.user_id}-chat")
        row.refresh_from_db()
        beat = HeartbeatBeat.objects.create(
            user_id=who.user_id, org_id=who.org_id, trigger="timer", status="done",
            outcome="nothing", cost=Decimal("0.80"), started_at=now - 120, finished_at=now - 60)
        HeartbeatApproval.objects.create(
            user_id=who.user_id, org_id=who.org_id, beat_id=beat.id, what="Send a mail",
            tool="send_mail", asked_at=now - 90)
        got = beatlog.listing(who)
        expect([b["id"] for b in got["beats"]] == [beat.id], f"the listing has {got['beats']}")
        expect(len(got["beats"][0]["approvals"]) == 1, "the beat's approval is not listed")
        expect(got["cap_paused"] == "", f"nothing is spent and it says {got['cap_paused']!r}")

        # $5.90 spent: a beat that may cost $0.80 is not started.
        LLMRequest.objects.create(user_id=who.user_id, org_id=who.org_id,
                                  session_id=row.chat_id, started_at=now - 30,
                                  purpose="heartbeat_decide", cost_usd=Decimal("5.90"))
        expect(heartbeat.beat_reserve(row) == Decimal("0.80"),
               f"the reserve is {heartbeat.beat_reserve(row)}, not the dearest beat's $0.80")
        said = beatlog.listing(who)["cap_paused"]
        expect(said.startswith("Paused for today: $0.10 of the $6.00 daily cap is left"),
               f"with $0.10 left it says {said!r}")
        # $6.70 spent: the cap is reached, and the page says so and when it beats again.
        LLMRequest.objects.create(user_id=who.user_id, org_id=who.org_id,
                                  session_id=row.chat_id, started_at=now - 20,
                                  purpose="heartbeat_decide", cost_usd=Decimal("0.80"))
        said = beatlog.listing(who)["cap_paused"]
        expect(said == "Paused for today: daily cap of $6.00 reached ($6.70 spent, $0.70 over, "
                       "by the beat that was running when it was reached); beats again "
                       "tomorrow at 08:00.", f"past the cap it says {said!r}")
        expect(heartbeat.view(who)["state"]["capped"] == said, "the Heartbeat page says otherwise")
    finally:
        LLMRequest.objects.filter(user_id=who.user_id).delete()
        HeartbeatApproval.objects.filter(user_id=who.user_id).delete()
        HeartbeatBeat.objects.filter(user_id=who.user_id).delete()
        HeartbeatState.objects.filter(user_id=who.user_id).delete()


@check("own", "the morning brief's focus picker is offered the projects",
       "the one thing's picker is handed every category, task and step at any depth out of the "
       "task browser's own rows, rather than told the projects could not be read", needs_db=True)
def one_thing_picker_reads() -> None:
    """8 November 2026: the focus picker on the brief had no categories, again (fr_7bfe96b7672b).

    `objectindex.index_data` reads `demo.browser_marks(person)["demo"]`, and with nobody
    reading it, as the picker asks (`one_thing.options`), the answer had no `demo` key: every
    call raised KeyError and the picker said "Your projects could not be read just now". This
    asks the task browser's data the way the picker does, and checks that a step under a step
    reaches the picker with the step above it named.
    """
    import tempfile

    from rouh import demo, objectindex, one_thing

    marks = demo.browser_marks(None)
    expect({"on", "demo", "shown"} <= set(marks),
           f"demo.browser_marks(None) answers {sorted(marks)}, without every key index_data reads")
    with tempfile.TemporaryDirectory() as root:
        data = objectindex.index_data(objectindex._store(), root)
    offered = one_thing.from_index(data)
    expect(offered.get("ok") and isinstance(offered.get("categories"), list)
           and isinstance(offered.get("tasks"), list), "the picker was not offered lists of projects")
    shaped = {"sides": [{"id": "w", "name": "Work"}],
              "categories": [{"id": "c", "name": "A project", "side": "w"}],
              "tasks": [{"id": "t", "name": "A task", "n": 7, "href": "/workspace/_task/w/7.t/", "category": "c",
                         "status": "open", "archived": False, "made": None,
                         "steps": [{"href": "/workspace/_task/w/7.t/7-01.a/", "title": "A step", "num": "7-01", "made": None,
                                    "kids": [{"href": "/workspace/_task/w/7.t/7-01.a/7-01-01.b/", "title": "A deeper step",
                                              "num": "7-01-01", "made": None, "kids": []}]}]}]}
    subs = one_thing.from_index(shaped)["tasks"][0]["subs"]
    expect([s["name"] for s in subs] == ["A step", "A deeper step"],
           f"the picker's sub tasks are {[s['name'] for s in subs]}, not every step at every depth")
    expect(subs[1]["path"] == ["A step"] and subs[1]["href"] == "/task/w/7.t/7-01.a/7-01-01.b",
           "a step under a step does not name the step above it or keep its address")


@check("own", "Rouh's server starts and answers",
       "Rouh's server comes up on this base and its health page says ok", needs_db=True)
def server_starts() -> None:
    port = _free_port()
    env = dict(os.environ, ROUH_HOST="127.0.0.1", ROUH_PORT=str(port), PYTHONDONTWRITEBYTECODE="1")
    log = Path(os.environ.get("ROUH_DATA_DIR", "/tmp")) / "server.log"
    with open(log, "wb") as out:
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "rouh.server:app", "--host", "127.0.0.1",
                                 "--port", str(port)], cwd=str(CODE), env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        body, end = b"", time.monotonic() + 180
        while time.monotonic() < end:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as r:
                    body = r.read()
                if b'"ok":true' in body.replace(b" ", b""):
                    return
            except OSError:
                pass
            time.sleep(1)
        tail = log.read_text(errors="replace")[-600:].strip().replace("\n", " | ")
        expect(False, f"the server did not answer ok in 3 minutes ({'it stopped' if proc.poll() is not None else 'still not up'}): {tail}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


@check("own", "the one program starts its parts",
       "the one program's own modules and its page's Django application load")
def one_program() -> None:
    if not (CODE / "one").is_dir():
        return
    r = subprocess.run([sys.executable, "-c", "import one.program, one.asuser, one.cli"], cwd=str(CODE),
                       capture_output=True, text=True, timeout=120,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", DJANGO_SETTINGS_MODULE=""))
    expect(r.returncode == 0, (r.stderr or r.stdout).strip()[-400:])


@check("own", "a page's pictures are not sent inside it on the canvas",
       "a page Rouh frames names its pictures by signed addresses of their own, fetched as they come into "
       "view, so a page of many screenshots stays small and draws at once (rouh/picturelinks.py); the "
       "address reads only pictures of the page's own task, for the day, and the copy kept for offline "
       "still has its pictures put in")
def page_pictures_linked() -> None:
    import tempfile
    from types import SimpleNamespace

    from rouh import pages, picturelinks

    task = "work/acme/19.pricing"
    page = f"{task}/19-04.packages/index.html"
    picture = b"\x89PNG\r\n\x1a\n" + b"\0" * 2_000_000
    markup = ("<!doctype html><html><head><title>Packages</title></head><body>"
              + "".join(f'<img src="shots/{n}.png" alt="Shot {n}">' for n in range(6))
              + '<img src="shots/0.png" loading="eager" alt="First"/>'
              + '<div style="background:url(shots/bg.png)"></div></body></html>')
    with tempfile.TemporaryDirectory() as root:
        shots = Path(root, task, "19-04.packages", "shots")
        shots.mkdir(parents=True)
        for n in range(6):
            (shots / f"{n}.png").write_bytes(picture)
        (shots / "bg.png").write_bytes(picture[:2000])
        Path(root, page).write_text(markup)
        who = SimpleNamespace(user_id=7, org_id="org-a")
        at = pages.ROUTE + page
        linked, _ = pages.read(root, page, page, at, pictures=picturelinks.linker(who, page))
        whole, _ = pages.read(root, page, page, at)
    text = linked.decode("utf-8", "surrogateescape")
    expect(len(linked) < 200_000,
           f"the framed page is {len(linked) / 1e6:.1f} MB with six 2 MB pictures: they were put in, not linked")
    expect(text.count(f'src="{picturelinks.ROUTE}') == 7, "not every <img> names its picture by its own address")
    expect(text.count('loading="lazy"') == 6 and 'loading="eager"' in text,
           "a linked picture is not lazy, or a page's own loading= was overridden")
    expect("url(&quot;data:image/png;base64," in text or 'url("data:image/png;base64,' in text,
           "a picture a style names is no longer put in")
    expect(len(whole) > 12_000_000, "without a linker (the offline copy) the pictures are no longer put in")
    signed = text.split(f'src="{picturelinks.ROUTE}', 1)[1].split("/", 1)[0]
    said = picturelinks.read(signed)
    expect(said["u"] == "7" and said["o"] == "org-a" and said["t"] == task, f"the token says {said}")
    expect(picturelinks.inside(said, f"{task}/19-04.packages/shots/1.png"), "the page's own picture is refused")
    expect(not picturelinks.inside(said, "work/acme/20.other/a.png")
           and not picturelinks.inside(said, task + "x/a.png"), "a picture of another task is let through")
    for bad in (picturelinks.token(7, "org-a", task, day=picturelinks._today() - picturelinks.DAYS - 1),
                signed[:-2] + ("AA" if signed[-2:] != "AA" else "BB")):
        try:
            picturelinks.read(bad)
        except picturelinks.Refused:
            continue
        expect(False, "a token that ran out, or was changed, was taken")


@check("own", "a paused tester still runs a review the owner asked for",
       "pausing a tester, or all testing, holds back only the automatic tries a build or a nightly run "
       "starts: a review the owner asked for still starts, and the pause stays exactly as it was",
       needs_db=True)
def trials_pause_holds_back_only_automatic() -> None:
    """7 November 2026: Petar paused Vesela so builds stop trying every change on her, then asked for
    her to test one page, and the review was refused because she was paused. His words: "the pause is
    for automatically running her on all various developments. That should be separate from times I
    ask you specifically". This pauses a tester, then all testing, and asks `trials.start` for both
    kinds of try each time."""
    import uuid

    from rouh import models, trials

    who = trials._Whose("selfcheck-org", f"selfcheck-{uuid.uuid4().hex[:8]}")
    mine = {"org_id": who.org_id, "user_id": who.user_id}
    goal = "You want to see what your testers found."
    try:
        tester = trials.default_persona(who)
        for everyone in (False, True):
            if everyone:
                trials.set_paused(who, tester, False)
                trials.set_paused(who, "", True)
            else:
                trials.set_paused(who, tester, True)
            how = "all testing paused" if everyone else f"{tester} paused"
            try:
                trials.start(who, persona_id=tester, goal=goal, job_name="Pause check", by="selfcheck")
                expect(False, f"{how}: an automatic try was started")
            except trials.Paused:
                pass
            t = trials.start(who, persona_id=tester, goal=goal, job_name="Pause check", by="selfcheck", mode="review")
            expect(t["mode"] == "review" and t["state"] == "running",
                   f"{how}: the review the owner asked for came back {t['mode']}, {t['state']}")
            paused, by_all = trials.is_paused(who, tester)
            expect(paused and by_all == everyone, f"{how}: starting the review changed the pause")
    finally:
        models.Trial.objects.filter(**mine).delete()
        models.TrialJob.objects.filter(**mine).delete()
        models.TrialTester.objects.filter(**mine).delete()
        models.UserSetting.objects.filter(user_id=who.user_id).delete()


@check("own", "a job is Codex only when the person's own words ask for it",
       "the brief Rouh writes never makes a job Codex: a file name, a quoted run history or a model bar in "
       "it is not a request (Petar, 11 November 2026), while the person saying \"with openai astra\" or "
       "\"do this with Codex\" still starts Codex with that model, and agent claude said on purpose wins")
def codex_only_on_their_words() -> None:
    from rouh import codex_route, starting, tools, turntrace

    # The models by family, from the Models page's list, newest first, as the routing reads them.
    newest: dict[str, str] = {}
    for model, family, _ in codex_route._models():
        newest.setdefault(family, model)
    astra, sol, luna = newest["astra"], newest["sol"], newest["luna"]
    not_asked = [
        "Redo readable reasoning, safely: update the docstrings in luna.py and llmlog.py.",
        "Jobs get their own tools. History: Codex run e32c0ff3 (11 Nov, 09:27, " + luna + ") failed.",
        "Each Rouh adapts master's changes with the best model, e.g. Claude Opus or the top GPT on Codex.",
        "update luna.py", "look at rouh/luna.py", "fix the Codex sign-in", "Luna's voice is bad",
        f"`{luna}`", "there is a bug with the Codex sign-in", "don't use Codex", f"the {astra} model is slow",
    ]
    for text in not_asked:
        got = codex_route.named(text)
        expect(got is None, f"{text!r} made a job Codex on {got}")
    asked = {"with openai astra": astra, "do this with Codex": "", f"use {astra} for this": astra,
             "run it on Sol": sol, f"run it on {sol.replace('-', ' ')}": sol, "have Codex do it": ""}
    for text, model in asked.items():
        got = codex_route.named(text)
        expect(got is not None and got.model == model, f"{text!r} came back {got}, not Codex on {model or 'its pick'}")
    token = turntrace.CURRENT.set(turntrace.Trace("selfcheck", "t", None, asked="Make jobs get their own tools"))
    try:
        words = tools._their_words()
        expect(words == "Make jobs get their own tools", f"the person's words were read as {words!r}")
        expect(starting.route_to_codex(words) is None, "words with no model in them made a job Codex")
        turntrace.CURRENT.set(turntrace.Trace("selfcheck", "t", None, asked="do it with openai astra"))
        expect(starting.route_to_codex(tools._their_words(), agent="claude", agent_chosen=True) is None,
               "agent claude said on purpose did not win over the person's words")
        turntrace.CURRENT.set(None)
        expect(tools._their_words() == "", "a start with no turn read words from somewhere")
    finally:
        turntrace.CURRENT.reset(token)


#: Letters with every kind of address that opens only on the computer or network that sent them.
_LOCAL_SAMPLES = (
    "Press http://127.0.0.1:8420/login/link/abc to sign in.",
    "Open https://localhost:8420/chat/7, then come back.",
    "<a href=\"http://192.168.1.4:8420/x\">open</a> or <a href='http://10.0.0.7/y'>this</a>",
    "http://172.20.3.4:8420/a http://[::1]:8420/b http://169.254.1.1/c http://100.64.0.9/d",
    "http://mozart.local:8420/e http://0.0.0.0:8420/f http://rouh:8420/g",
    "Or type 127.0.0.1:8420/login/link/abc into the browser; localhost:8420 also works.",
)


@check("own", "no letter leaves with an address that opens only on this computer",
       "every way Rouh sends email moves or takes out links to 127.0.0.1, localhost and private networks, "
       "and refuses to send a letter that still holds one", needs_db=True)
def no_local_addresses_in_mail() -> None:
    """Petar, 11 and 12 November 2026 (task 140, step 140-14): a sign-in email reached Maria with a
    http://127.0.0.1 link, which opens nothing on her phone. This holds every mail exit to the guard."""
    import asyncio
    import re as _re

    from rouh import mailer, outside_links, signin

    for sample in _LOCAL_SAMPLES:
        expect(outside_links.local_left(sample), f"the check does not see the local address in: {sample}")
        for base in ("", "https://cherry-kelp.rouh.page"):
            for html in (False, True):
                out = outside_links.guard(sample, base=base, html=html)
                expect(not outside_links.local_left(out), f"a local address is left in {out!r}")
        expect("https://cherry-kelp.rouh.page/login/link/abc" in outside_links.clean(
            sample, base="https://cherry-kelp.rouh.page") or "login/link" not in sample,
            "a sign-in link is not moved onto the Rouh's outside address")
    kept = "See https://rouh.land/mac/ and https://cherry-kelp.rouh.page/chat/7."
    expect(outside_links.guard(kept) == kept, "a link the world can reach was changed")

    subject, text = signin.letter("Cherry Kelp", "http://127.0.0.1:8420/login/link/abc", "296883")
    expect("296883" in text and not outside_links.local_left(text), "the sign-in letter carries a local link")

    # The Brevo exit, end to end, with the mail service stood in for.
    sent: list[dict] = []

    class _Answer:
        status_code = 201

        @staticmethod
        def json():
            return {"messageId": "x"}

    async def _post(self, url, json=None, headers=None):  # noqa: A002 - httpx's own name
        sent.append(json)
        return _Answer()

    import httpx

    real_key, real_post = mailer._key, httpx.AsyncClient.post
    mailer._key, httpx.AsyncClient.post = (lambda path: "k"), _post
    try:
        cfg = type("Cfg", (), {"brevo_file": "/nonexistent", "brevo_url": "http://brevo.invalid",
                                "mail_from": "rouh@example.test", "mail_from_name": "Rouh"})()
        letter = mailer.Letter(to="someone@example.test", subject="Sign in", text=_LOCAL_SAMPLES[0] + " "
                               + _LOCAL_SAMPLES[5], html=_LOCAL_SAMPLES[2])
        asyncio.run(mailer.Mailer(cfg).send(letter))
    finally:
        mailer._key, httpx.AsyncClient.post = real_key, real_post
    expect(sent, "the mail service was never asked")
    for field in ("textContent", "htmlContent"):
        expect(not outside_links.local_left(sent[0].get(field, "")), f"Brevo was handed a local address in {field}")

    # Every place in the code that hands a letter to a mail service goes through the guard.
    exits = {"/v3/smtp/email": "outside_links.guard", "/messages/send": "outside_links.guard",
             "api/sign-in-letter": "outside_links.is_local"}
    # Passes on a message another module made and guarded: a forward `google_api/gmail.py` composed.
    passes_on = {"rouh/inboxes.py", "rouh/mailboxes.py"}
    for path in (CODE / "rouh").rglob("*.py"):
        rel = path.relative_to(CODE).as_posix()
        if rel.startswith(("rouh/testing/", "rouh/selfcheck/", "rouh/migrations/")) or rel in passes_on:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        for marker, needs in exits.items():
            if _re.search(r"[\"']" + _re.escape(marker), src):
                expect(needs in src, f"{rel} sends mail ({marker}) without {needs}")
