"""The process. One WebSocket per browser tab, and one turn at a time per thread.

A turn belongs to the thread it was asked in and not to the tab that asked
(`Turn`, `Turns`). Everything a turn sends goes to whichever tabs are looking
at that thread when it is sent, which may be none: leaving the thread, opening
a task and reloading the page do not stop an answer, and what it writes is in
the thread when the person comes back.

Three things run concurrently for a single spoken reply and they must be able to
stop independently:

1. the model writing the answer,
2. the voice turning finished sentences into audio,
3. the browser playing that audio.

They are joined by a queue rather than by awaiting each other, so the voice can
be a sentence behind the model without holding it up, and a barge-in can cancel
all three at once without waiting for any of them to finish what they were doing.

**What this module is since 23 September 2026.** It was `rouh/server.py`, the
FastAPI application, with every route written into it beside the process's
state. Rouh is a Django project now: the addresses are in
`rouh/project/urls.py`, the views that answer them are in `rouh/web/`, the
websocket is a Channels consumer (`rouh/web/consumers.py`), and the sign-in
is Django's. What is left here is what the process *is* - the stores it holds
open, the voice, the one program, the tabs (`Hub`), the turns (`Turn`,
`Turns`), the feeds that push the task list and the work tree, and what
happens when it starts and stops (`startup`, `shutdown`, which the ASGI
lifespan in `rouh/project/asgi.py` calls). A view asks this module; nothing
here knows it is being asked over HTTP.

The stores are Django models in PostgreSQL. They are called straight from the
event loop, as the SQLite stores always were: each call is one short query
on this machine, none of them awaits anything in the middle of a transaction,
and the slow ones were already handed to a thread with `asyncio.to_thread`.
That is why `DJANGO_ALLOW_ASYNC_UNSAFE` is set for this process; see
`rouh/project/asgi.py`.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
import uuid
from pathlib import Path

from . import (accounts as auth, addressing, answered_in_chat, answering, artifacts, askai, asking, attachments,
               boxes, browsing, chatkinds, clock, codechanges, composing, conflicts, conversations, costs,
               decision_desk, decision_sources, decisions, events,
               gene_therapy as gene_therapy_mod, genelab, filing, forks, heartbeat, imaging, inbox, inboxes, linkedin,
               llmlog, location, meeting_brief, meeting_contacts, meeting_next, meeting_people, meeting_prep, modeldefaults, modeloutcomes, morning_brief, notices, owning,
               pageplaces, protected,
               redaction, reminder_titles, replymode, reminders, runs, runsummary,
               sandbox, searching, self_update, sharing, sent_by_you, signups, source_check, starting, stopping,
               subtasknotes, task_origin, telegram,
               telegram_account, telegram_chat, thoughts, triage, turnmarks, uploads)
from .config import config, luna_ready, model_name
from .encryption import NotEncryptable, SecretBox
from .apple_contacts import AppleStore, ContactDesk
from .mail_alerts import AlertStore, MailAlerts
from .google_api import GoogleClients, GoogleDesk
from .google_audit import WriteLog
from .google_oauth import GoogleAuth
from .google_store import GoogleStore
from .mailboxes import MailboxAuth, MailboxStore
from . import dbwork
from . import modelstandard, turntrace
from . import settings as settings_mod
from . import telegram_guests as telegram_guests_mod
from .settings import Settings
from .tenancy import Identity, Tenancy
from .version import BUILD, get_version
from .brain import Brain
from . import memory as memory_mod
from .memory import Memory
from . import chats as chatnames
from . import rouh_version, one_deploy, one_version
from .one_client import OneClient
from .speech import Ears, LiveEars, SpeechError, Voice
from .timekeeper import Timekeeper
from .tools import ToolRegistry
from .tree import build_tree, empty_tree

# Named separately from the manager because the callback endpoint has to know
# whether an incoming hook is telemetry before it decides how much work to do,
# and that is true even on a machine where delegation could not be loaded.
try:
    from .crew import (TELEMETRY_KINDS, UnknownCrewmate, is_late_news,
                       normalise_kind as crew_kind)
except Exception:  # pragma: no cover - only reachable if crew.py itself is broken
    TELEMETRY_KINDS: frozenset[str] = frozenset()

    class UnknownCrewmate(Exception):
        pass

    def crew_kind(raw: str) -> str:
        return (raw or "").strip().lower()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("rouh")

# Nothing in this repository logs a credential. This is the net under that: it
# masks anything Google-credential-shaped on its way to a handler, including a
# line written by a library that has never heard of any of this.
redaction.guard_logging()

#: The front end's stamp, which the page is told on `hello` so an open tab
#: knows when it is older than the server (`rouh/web/assets.py`).
from .web.assets import ASSETS  # noqa: E402
from . import restarts  # noqa: E402
memory = Memory()
voice = Voice(config)
ears = Ears(config)

def _agent_instructions(job: str, task: str) -> str:
    from . import agent_instructions

    return agent_instructions.issue(modeldefaults.org_now(), run_id=job, via="the crew", task=task)


crew = None
if config.enable_delegate:
    try:
        from .crew import CrewManager

        crew = CrewManager(
            workspace=config.crew_workspace,
            session=config.crew_session,
            socket=config.crew_tmux_socket or None,
            allow_yolo=config.allow_yolo,
            # A worker is Claude Code in a terminal, and it needs its own
            # credentials. root on this box has no subscription login, so the
            # API key is what makes it run. tmux keeps its own environment
            # from whenever its server started, so inheriting ours is not
            # enough - it has to be set on the session explicitly.
            default_env={"ANTHROPIC_API_KEY": config.anthropic_api_key},
            # Which model a worker is, and how deeply it thinks: the default
            # pair, asked for at every start, so a change in Settings reaches
            # the next worker (`rouh/modeldefaults.py`).
            defaults=lambda: modeldefaults.use_pair("workers", cfg=config),
            # What every worker is told before anything else, read from the
            # database at every start and written down against the job
            # (`rouh/agent_instructions.py`).
            instructions=lambda job, task: _agent_instructions(job, task),
            hook_transport=config.crew_hook_transport,
            run_as=config.crew_user,
            run_home=config.crew_home,
        )
        # Jobs in the person's assistant workspace, when this machine has a
        # copy of it. They run as that workspace's own user, on the person's
        # subscription rather than this process's key.
        if config.assistant_repo:
            try:
                from .assistant_job import make_profile

                crew.add_profile(make_profile(config))
            except Exception:
                log.exception("assistant jobs unavailable; everything else carries on")
    except Exception:  # the assistant is still useful without a worker layer
        log.exception("delegation unavailable; continuing without it")
        crew = None

#: The one program beside Rouh (task 30, step 10). Rouh reaches into it;
#: it never reaches back, and nothing here needs it to be running.
one = OneClient()

#: The one deploy of the one program that may be running, and what happened to
#: it. Pressing the version chip's button starts it; every open tab is told the
#: outcome (`one_deploy.py`).
deployer = one_deploy.Deployer(config)

# --------------------------------------------------------------------------
# Organisations, the people in them, and the credentials each level owns.
#
# `tenancy` is the answer to "who is asking, and which organisation are they
# in", and every query about anything owned by either goes through it. The
# Google pieces are built from it: an organisation's OAuth client, then that
# person's own tokens. If the encryption library is missing there is nowhere
# safe to keep a credential, so the whole feature stays off rather than storing
# one in plain text - everything else about Rouh carries on.
# --------------------------------------------------------------------------

tenancy = Tenancy()

google_store: GoogleStore | None = None
google_auth: GoogleAuth | None = None
google_desk: GoogleDesk | None = None
#: Read-only mailboxes (`rouh/mailboxes.py`).
mailbox_auth: MailboxAuth | None = None
#: Each person's iCloud contacts (`apple_contacts.py`, APPLE.md). Built from
#: the same box as Google's credentials, and off with them for the same reason.
contacts: ContactDesk | None = None
#: Each person's own Telegram account, which makes a group for each fork made
#: on Telegram (`telegram_account.py`). The same box again.
telegram_accounts: telegram_account.TelegramAccounts | None = None
encryption_key_source = "none"
try:
    secret_box = SecretBox(config.encryption_key, data_dir=config.data_dir)
    encryption_key_source = secret_box.key_source
    google_store = GoogleStore(None, secret_box)
    google_auth = GoogleAuth(google_store, config)
    # Every send, every label, every edit lands as one line in
    # {log_dir}/google-writes.log. Rouh can act on somebody's real mailbox
    # now, so there has to be somewhere to look afterwards that is not this
    # process's memory.
    google_audit = WriteLog(config.logs_path)
    # And every message to somebody other than the person, whole, with the
    # id its provider gave it (`rouh/sentlog.py`, card 1315).
    from . import sentlog
    sentlog.configure(config.logs_path)
    google_desk = GoogleDesk(tenancy, google_store, GoogleClients(google_auth, config),
                             audit=google_audit)
    # And every contact Rouh adds, changes or deletes in somebody's iCloud,
    # in {log_dir}/contacts-writes.log beside it.
    contacts = ContactDesk(tenancy, AppleStore(secret_box), config,
                           audit=WriteLog(config.logs_path, name="contacts-writes.log"))
    telegram_accounts = telegram_account.TelegramAccounts(
        telegram_account.AccountStore(secret_box))
    # The person's own mailboxes, each connected read-only, which the brief's
    # "Waiting on others" reads (`mailboxes.py`, `ghosts.py`). Through the same
    # organisation client and the same box.
    mailbox_auth = MailboxAuth(google_store, google_auth, MailboxStore(secret_box), config)
    # And the mail tools read them too, as "my mail" beside Rouh's own inbox
    # (`inboxes.py`).
    inboxes.use(mailbox_auth, config)
except NotEncryptable:
    log.exception("credentials cannot be encrypted here, so Google, Apple Contacts and a "
                  "Telegram account stay off")

#: The Ask AI conversations on the person's workspace pages. One person's
#: threads about one page, in Rouh's own database, keyed by who and by which
#: page: see askai.py. It is made here whether or not this machine has a
#: workspace, because a machine that gains one later must not need a restart.
ask_threads = askai.Threads()

#: Which of the person's workspace pages are public, and under what token.
#: `sharing.py` is the whole of it; the route that serves one is the only
#: address in Rouh that answers without a sign-in and has something of the
#: person's in it, which is why the token is a secret of its own.
shares = sharing.Shares()

#: Which pages are shared with which people, by their email address, and what
#: each may do: `sharing.Guests`, and `rouh/web/guests.py` for the letters and
#: the pages a guest reads them on.
guests = sharing.Guests()

#: Where a shared page is followed to when its folder moves (`rouh/pageplaces.py`).
pageplaces.use(config.assistant_repo)

#: What each person has set for themselves, as against what this machine is
#: configured with. The orb's sliders are the only one so far, and they are
#: here rather than in a browser's local storage because they are the person's:
#: kept in one browser they were not on the phone, and were gone from the
#: desktop as soon as that browser dropped its site data (`settings.py`).
user_settings = Settings()

tools = ToolRegistry(config, memory, crew, one=one, google=google_desk, shares=shares,
                     contacts=contacts)

#: Files the person attaches in the chat, one directory per conversation under
#: the same data directory the database lives in, so one backup covers both.
# `group` is the one whose members are handed files by their path - the crew's
# workers and the one program's runs - and have to be able to open them.
# Everyone else on the machine is shut out - see DIR_MODE in attachments.py.
files = attachments.Attachments(config.data_dir, readable_by=config.crew_user or None,
                                group=config.attachments_group)

#: What people say about Rouh, and what is going to be done about it. Two
#: tables in the same database file, its own connection and its own lock, the
#: shape every other store here has (`rouh/gene_therapy.py`). The files on a
#: piece of feedback are ordinary attachments and go through `files` above.
gene_therapy = gene_therapy_mod.GeneTherapyStore()

brain = Brain(config, memory, tools, files=files)

#: New mail in each person's Gmail inbox, read the moment Google's Pub/Sub says
#: it arrived and handed to Rouh itself, one message at a time, each in a
#: conversation of its own (`mail_alerts.py`, `answer_an_email` below). Off
#: with Google, for the same reason: its one credential, the push address's
#: token, is sealed in the same box.
mail_alerts: MailAlerts | None = None
if google_store is not None and google_auth is not None:
    mail_alerts = MailAlerts(tenancy, AlertStore(secret_box), google_store,
                             GoogleClients(google_auth, config), config,
                             telegram_=tools.telegram,
                             people=contacts.people if contacts is not None else None,
                             audit=google_audit)
    tools.mail_alerts = mail_alerts

#: The Live browser: one real browser per person that Rouh drives for errands
#: and the person watches, takes over and hands back (`browsing.py`). Its
#: logins are sealed in the same box as Google's tokens, and are not kept at
#: all where there is no box. The tabs and `announce` are looked up when they
#: are used, because both are defined further down this file.
browser_desk = browsing.Desk(
    config, tabs=lambda: Hub.sockets,
    announce=lambda note, chat: announce(note, chat),
    box=secret_box if google_store is not None else None)
tools.browsing = browser_desk


async def _scheduled_turn(chat: str, note: str) -> "Turn":
    """A turn in `chat` answering a note of a reminder's (`rouh/timekeeper.py`).

    The same as `tell_thread`, and handing the turn back so the timekeeper can
    wait for what it said: answered into the newest tab standing in that chat,
    and spoken there when its spoken replies are on; with none, in silence.
    """
    here = [s for s in list(Hub.sockets) if not s.closed and s.session_id == chat]
    tab = max(here, key=lambda s: getattr(s, "opened_at", 0.0)) if here else None
    return await Turns.start(chat, f"{turnmarks.NOTE} {note}]", asked_by=tab,
                             speak=bool(tab is not None and tab.voice_replies and voice.ready),
                             answer_now=True, note=True)


async def _goal_chat(title: str, task_id: str) -> str:
    """A goal's own conversation, owned by the goal's task, and every tab told.

    The one chat a goal ever has: its streams are background runs, not chats
    (`goals.py`, Petar on 27 September 2026). The task is new too
    (`goals.create`), so it is filed into the project it belongs in the way
    any new task is (`NewTasks`), and the lists are told about both.
    """
    def made_and_owned() -> str:
        from . import goals

        chat = conversations.new_chat(title, None)
        st = conversations.store()
        st.attach("task", task_id, "chat", chat)
        # Written into the goal before it is filed, which moves its folder.
        goals.attach_chat(st.get_task(task_id), chat)
        return chat

    made = await asyncio.to_thread(made_and_owned)
    with contextlib.suppress(Exception):
        await announce_objects()
        await _announce_workspace()
        await announce_chats()
    NewTasks.maybe_file(task_id)
    return made


async def _goal_run(brief: str, title: str, goal, chat: str) -> str:
    """One step of a goal as a background run, owned by the goal's task.

    The one start path every job goes through (`starting.start`), as the
    person's assistant working in their workspace, so it is on the orb and on
    the run list like any job. Started with no chat, so the brief is not told
    to make the goal's next numbered step (`starting.with_its_task`), and then
    marked as come from the goal's chat, which is where it reports
    (`runs.reports_to`) and where `timekeeper.run_finished` puts its line.
    """
    from . import starting

    got = await starting.start(brief=brief, title=title, preset="assistant_job",
                               owner=("task", goal.id), cfg=config, crew=crew, one=one,
                               emit=Hub.broadcast)
    run_id = str(got.get("id") or "")
    if run_id and chat:
        await asyncio.to_thread(runs.came_from, run_id, chat)
    return run_id


async def _synapse_nightly(who, trying: bool) -> str:
    """The nightly Synapse run, at its time on the Reminders page (`rouh/synapse/nightly.py`).

    Its attempt row first, then one worker of the kind improve_myself starts, which lands through land.sh;
    the line it answers is what the Reminders page says it did."""
    from .synapse import nightly

    got = await nightly.start(who, mode="full", cfg=config, crew=crew, one=one, emit=Hub.broadcast,
                              run_state=nightly.run_state)
    return nightly.said_line(got)


async def _synapse_dream(who, trying: bool) -> str:
    """The nightly dream on Synapse Master, at 04:00 on the Reminders page (`rouh/synapse/dreaming.py`): one
    night queued on the backfill lane; the line it answers is what the Reminders page says it did."""
    from .synapse import dreaming

    return await asyncio.to_thread(dreaming.start_scheduled, who)


async def _nightly_refactor(who, trying: bool) -> str:
    """The nightly code refactoring run, at its time on Clockwork (`rouh/nightly_refactor.py`): the
    night's row, then its run, or a wait while the feature run's night is still going or landing."""
    from . import nightly_refactor

    return await nightly_refactor.start(who, trying=trying)


async def _nightly_feature(who, trying: bool) -> str:
    """The nightly Rouh feature run, at its time on the Reminders page (`rouh/nightly_feature.py`):
    the night's row, then its run (Claude Code on Opus 5.5 unless the Models page picks
    otherwise); the line it answers is what the Reminders page says."""
    from . import nightly_feature

    return await nightly_feature.start(who, trying=trying)


#: How often Mutations is kept true by itself (`evolution.tick`), in seconds.
EVOLUTION_EVERY = 15 * 60


async def _evolution_loop() -> None:
    """The install owner's Mutations kept true by itself (`rouh/evolution.py`): the nights
    brought in, the shelf released into the morning's deck, trial weeks judged by use, and
    mutation requests and removals settled, every quarter of an hour."""
    from . import evolution

    await asyncio.sleep(30)
    while True:
        owner = None
        try:
            owner = await asyncio.to_thread(telegram.phone_owner, tenancy)
            if owner is not None:
                await asyncio.to_thread(evolution.tick, owner)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("Mutations' beat failed")
        try:
            # Ideas handed from the Incubator to Gene therapy, moved on as their requests are.
            from . import incubator

            await asyncio.to_thread(incubator.follow_everyone)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the Incubator's beat failed")
        try:
            # Any idea still without a score is scored (`rouh/incubator_score.py`).
            from . import incubator_score

            if owner is not None:
                await incubator_score.sweep(owner)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the Incubator's scores could not be swept")
        try:
            # And any idea still without its summary is summed up, those to decide first (`rouh/incubator_gist.py`).
            from . import incubator_gist

            if owner is not None:
                await incubator_gist.sweep(owner)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the Incubator's summaries could not be swept")
        await asyncio.sleep(EVOLUTION_EVERY)


#: How often a night of the nightly feature run is looked at (`nightly_feature.watch`), in seconds.
NIGHTLY_WATCH_EVERY = 5 * 60


async def _nightly_watch_loop() -> None:
    """The nightly feature run's night held to its target (Petar, 20 October 2026: "make sure I get
    the right number of genes"): a run whose turn ended short of what Parameters asked is sent back
    to work, and a finished night is ended with what it built, every five minutes."""
    from . import nightly_feature

    await asyncio.sleep(45)
    while True:
        try:
            owner = await asyncio.to_thread(telegram.phone_owner, tenancy)
            if owner is not None:
                await nightly_feature.watch(owner)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the nightly feature run's watch failed")
        await asyncio.sleep(NIGHTLY_WATCH_EVERY)


#: How often the gene log reads what landed and counts each gene's use (`rouh/genelog.py`).
GENE_LOG_EVERY = 15 * 60


async def _gene_log_loop() -> None:
    """The gene log kept true by itself (task 98, step 98-16): Rouh's manifests and Mutations
    followed, every change that landed read and put to its gene (the gene writer for the rest), each
    gene's use counted a day at a time, and, from the 25th of a month, the model's evaluation of the
    genes used that month; and, once this Rouh has joined the Gene Pool, the genes chosen for it kept in
    sync. Each part stops with its switch (`gene_log`, `gene_usage`, `gene_pool`)."""
    from . import birth, genelog, genepool, geneuse

    await asyncio.sleep(60)
    while True:
        try:
            owner = await asyncio.to_thread(telegram.phone_owner, tenancy)
            if owner is not None:
                org = str(owner.org_id)
                await asyncio.to_thread(genelog.tick, owner)
                if await asyncio.to_thread(genelog.on, org):
                    await genelog.write(owner)
                if await asyncio.to_thread(geneuse.on, org):
                    await asyncio.to_thread(geneuse.rollup, org)
                    if time.localtime().tm_mday >= 25:
                        await geneuse.evaluate(owner)
                # The Gene Pool: nothing at all until this Rouh has joined it (`genepool.tick`).
                await asyncio.to_thread(genepool.tick, owner)
                # Its birth: rouh.land asked after its keys, a waiting new key, its second name
                # once due; nothing at all for a Rouh not born (`birth.tick`).
                await birth.tick(owner)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the gene log's beat failed")
        await asyncio.sleep(GENE_LOG_EVERY)


#: How often the model standard and the outcome counts are looked at (`rouh/modeloutcomes.py`);
#: each is done only once a day.
MODEL_STANDARD_EVERY = 60 * 60


async def _model_standard_loop() -> None:
    """The model standard fetched from rouh.land once a day, every call to a model that
    nothing found wanting counted a success, and once a day each organisation's counts
    sent, or kept as a dry run (`modeloutcomes.tick`). A failure is in the log, and the
    last good standard is kept."""
    await asyncio.sleep(90)
    while True:
        try:
            await asyncio.to_thread(modeloutcomes.tick, config)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the model standard's beat failed")
        await asyncio.sleep(MODEL_STANDARD_EVERY)


async def _rule_defaults_loop() -> None:
    """The defaults every Rouh starts with fetched from rouh.land soon after a start and then once a day
    (`rouh/ruledefaults.py`); each Master takes in a new revision on its next turn or Rules page. A failure is
    in the log, and the last good defaults are kept."""
    from . import ruledefaults

    await asyncio.sleep(5)
    while True:
        try:
            if await asyncio.to_thread(ruledefaults.due):
                await asyncio.to_thread(ruledefaults.fetch, config)
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the rule defaults' beat failed")
        await asyncio.sleep(MODEL_STANDARD_EVERY)


#: How often the core checks that each scheduled job really ran and worked (`rouh/job_watch.py`).
JOB_WATCH_EVERY = 30 * 60


async def _job_watch_loop() -> None:
    """Every scheduled job's last run checked against what it left behind, kept for server_health,
    and said once a morning when one did not work (`rouh/job_watch.py`)."""
    from . import job_watch

    await asyncio.sleep(180)
    while True:
        try:
            owner = await asyncio.to_thread(telegram.phone_owner, tenancy)
            if owner is not None:
                got = await job_watch.tick(owner)
                if got.get("failed"):
                    log.warning("scheduled jobs that did not work: %s", got["human"][:600])
        except Exception:  # noqa: BLE001 - tried again on the next beat
            log.exception("the check of the scheduled jobs failed")
        await asyncio.sleep(JOB_WATCH_EVERY)


#: How often the core looks whether the weekly off-site copy is due (`rouh/offsite.py`).
OFFSITE_EVERY = 60 * 60


async def _offsite_loop() -> None:
    """The weekly encrypted copy of this Rouh off its machine (`rouh/offsite.py`), made from the
    newest nightly copy of its database once a week, when the settings file says where it goes.
    Not set up, nothing is sent and nothing is said but once."""
    from . import offsite

    await asyncio.sleep(120)
    if not offsite.set_up():
        log.info("no weekly off-site copy is set up (ROUH_OFFSITE_* in the settings file)")
    while True:
        try:
            if await asyncio.to_thread(offsite.due):
                got = await asyncio.to_thread(offsite.run)
                log.info("the weekly off-site copy was sent: %s, %.1f MB", got["key"], got["bytes"] / 1e6)
        except Exception:  # noqa: BLE001 - tried again later; the reason is kept (offsite.status)
            log.exception("the weekly off-site copy failed")
        await asyncio.sleep(OFFSITE_EVERY)


async def _nightly_feature_ready() -> None:
    """The install owner's nightly feature run on their Reminders page, once its task exists (or the
    reminder that first scheduled it is taken over). Once at start-up; quiet when there is nothing to do."""
    from . import nightly_feature

    def ready() -> bool:
        owner = telegram.phone_owner(tenancy)
        return owner is not None and nightly_feature.ensure(owner) is not None

    try:
        if await asyncio.to_thread(ready):
            timekeeper.clock.poke()
    except Exception:
        log.exception("the nightly feature run could not be scheduled; Rouh carries on without it")


_REFACTOR_RESUMED: list = []


async def _nightly_refactor_ready() -> None:
    """The install owner's nightly refactoring run on Clockwork, at 03:00 the first time, and any
    night that was waiting when Rouh last stopped (a landing's deploy restarts it) waited for again.
    Once at start-up; quiet when there is nothing to do."""
    from . import nightly_refactor

    def ready():
        owner = telegram.phone_owner(tenancy)
        if owner is None:
            return None, False
        had = reminders.server_row(owner, nightly_refactor.JOB) is not None
        return owner, nightly_refactor.ensure(owner) is not None and not had

    try:
        owner, made = await asyncio.to_thread(ready)
        if made:
            timekeeper.clock.poke()
        if owner is not None and not _REFACTOR_RESUMED:
            # In the event loop's thread: each wait is a task of this loop. Once a process: this
            # is asked again every ten minutes (`_own_work_ready`), and a wait resumed twice is two.
            _REFACTOR_RESUMED.append(True)
            nightly_refactor.resume(owner, await asyncio.to_thread(nightly_refactor.waiting, owner))
    except Exception:
        log.exception("the nightly refactoring run could not be scheduled; Rouh carries on without it")


async def _control_room_names(who, trying: bool) -> str:
    """The Control Room's nightly naming pass, at its time on the Reminders page
    (`rouh/controlroom.py`): Opus 5.5 names the clusters and writes their headlines."""
    from . import controlroom

    return await controlroom.nightly(who, trying)


async def _base_patch(who, trying: bool) -> str:
    """The nightly base patch check, at its time on Clockwork (`rouh/base_patches.py`): patch-level
    fixes to what every Rouh runs on, found here and built, checked and published by base.yml."""
    from . import base_patches

    return await base_patches.night(who, trying=trying)


async def _base_patch_ready() -> None:
    """The nightly base patch check on the owner's Clockwork, on the Rouh that makes Rouh's releases
    only. Once at start-up; quiet when it is there already, or when this Rouh makes no releases."""
    from . import base_patches

    def ready() -> bool:
        owner = telegram.phone_owner(tenancy)
        if owner is None:
            return False
        had = reminders.server_row(owner, base_patches.JOB) is not None
        return base_patches.ensure(owner) is not None and not had

    try:
        if await asyncio.to_thread(ready):
            timekeeper.clock.poke()
    except Exception:
        log.exception("the nightly base patch check could not be scheduled; Rouh carries on without it")


async def _control_room_ready() -> None:
    """The install owner's nightly Control Room naming on their Reminders page. Once at
    start-up; quiet when it is there already."""
    from . import controlroom

    def ready() -> bool:
        owner = telegram.phone_owner(tenancy)
        if owner is None:
            return False
        had = reminders.server_row(owner, controlroom.JOB) is not None
        return controlroom.ensure(owner) is not None and not had

    try:
        if await asyncio.to_thread(ready):
            timekeeper.clock.poke()
    except Exception:
        log.exception("the control room's nightly naming could not be scheduled; Rouh carries on without it")


async def _synapse_nightly_ready() -> None:
    """Every person with a Synapse Master has the nightly row on their Reminders page, and the attempts
    table holds what task 85 already tried (`improvements.backfill`). Once at start-up; quiet when done."""
    def ready() -> int:
        from .synapse import db as synapse_db, improvements, nightly

        if not synapse_db.ready() or not improvements.ready():
            return 0
        made = 0
        for row in synapse_db.rows("SELECT org_id, user_id FROM synapse.dataset WHERE master"):
            who = tenancy.identity_of(row["user_id"])
            if who is None or str(who.org_id) != str(row["org_id"]):
                continue
            improvements.backfill(row["org_id"], row["user_id"])
            if nightly.ensure(who) is not None:
                made += 1
            # The nightly dream at 04:00, paused until the evaluation gate turns it on (D86).
            from .synapse import dreaming
            if dreaming.ensure(who) is not None:
                made += 1
        return made

    try:
        if await asyncio.to_thread(ready):
            timekeeper.clock.poke()
    except Exception:
        log.exception("the nightly Synapse run could not be scheduled; Rouh carries on without it")


_OWN_WORK = asyncio.Event()


def own_work_now() -> None:
    """Schedule Rouh's own work now: its owner has just been made (`web/firstrun.py`)."""
    _OWN_WORK.set()


async def _own_work_ready(every: float = 600.0) -> None:
    """Every seeder of Rouh's own scheduled work, now and then every `every` seconds, or as soon
    as an owner is made."""
    while True:
        # The nightly Synapse run on each Master owner's Reminders page, and the attempts it builds on.
        await _synapse_nightly_ready()
        # The nightly Rouh feature run on the owner's Reminders page (`rouh/nightly_feature.py`).
        await _nightly_feature_ready()
        # The nightly refactoring run at 03:00, after it (`rouh/nightly_refactor.py`).
        await _nightly_refactor_ready()
        await _control_room_ready()
        await _base_patch_ready()
        try:
            await asyncio.wait_for(_OWN_WORK.wait(), every)
        except asyncio.TimeoutError:
            pass
        _OWN_WORK.clear()


async def _say_in_chat(chat: str, text: str) -> None:
    """One line of Rouh's in a chat, written down and drawn on every tab in it.

    Written once no turn is running there, so it never lands inside an answer.
    Not a turn: nothing is asked of the model, and the line is the whole of it.
    """
    for _ in range(60):
        if not Turns.busy(chat):
            break
        await asyncio.sleep(2.0)
    if await asyncio.to_thread(memory.chat, chat) is None:
        return
    await asyncio.to_thread(memory.add_message, chat, "assistant",
                            [{"type": "text", "text": text}])
    with contextlib.suppress(Exception):
        await asyncio.to_thread(conversations.touched, chat)
    if not any(getattr(s, "session_id", "") == chat for s in Hub.sockets if not s.closed):
        with contextlib.suppress(Exception):
            await asyncio.to_thread(memory.mark_unread, chat, True)
    await Hub.mirror(None, "assistant", text, chat=chat)
    after_a_turn(chat)


#: Reminders, repeating jobs and goals (`rouh/timekeeper.py`): what the
#: `schedule` and goal tools and the two pages all go through, and the
#: loop that says a row when it is due. The tabs, the turns and the chats are
#: looked up when they are used, because they are defined further down.
timekeeper = Timekeeper(
    memory=memory, telegram=tools.telegram, public_url=config.public_url,
    tabs=lambda: Hub.sockets, start_turn=lambda chat, note: _scheduled_turn(chat, note),
    busy=lambda chat: Turns.busy(chat),
    new_chat=lambda title, task_id: _goal_chat(title, task_id),
    identity_of=lambda user_id: tenancy.identity_of(user_id),
    start_run=lambda brief, title, goal, chat: _goal_run(brief, title, goal, chat),
    say=lambda chat, text: _say_in_chat(chat, text),
    server_jobs={"synapse_nightly": lambda who, trying: _synapse_nightly(who, trying),
                 "synapse_dream": lambda who, trying: _synapse_dream(who, trying),
                 "nightly_feature": lambda who, trying: _nightly_feature(who, trying),
                 "nightly_refactor": lambda who, trying: _nightly_refactor(who, trying),
                 "control_room_names": lambda who, trying: _control_room_names(who, trying),
                 "base_patch": lambda who, trying: _base_patch(who, trying)})
tools.timekeeper = timekeeper


async def _heartbeat_chat(title: str, task_id: str = "") -> str:
    """A chat beats run in - the Heartbeat chat, made loose like any new chat, or a quest's
    own, owned by the quest's task - and every tab told there is one. A quest's task is new
    when the quest is, so it is filed into the project it belongs in the way any new task is
    (`NewTasks`), as a goal's is."""
    def made_and_owned() -> str:
        chat = conversations.new_chat(title, None)
        if task_id:
            st = conversations.store()
            if st.get_task(task_id) is not None:
                st.attach("task", task_id, "chat", chat)
        return chat

    made = await asyncio.to_thread(made_and_owned)
    with contextlib.suppress(Exception):
        if task_id:
            await announce_objects()
            await _announce_workspace()
        await announce_chats()
    if task_id:
        NewTasks.maybe_file(task_id)
    return made


def _heartbeat_busy() -> str:
    """Which chat a turn of Rouh's is running in, in words, or "" when none is."""
    for chat in list(Turns.running):
        if chat == memory.ensure_general():
            return "General"
        row = memory.chat(chat) or {}
        return f"\u201c{row.get('title') or 'a chat'}\u201d"
    return ""


async def _heartbeat_tool(who, name: str, args: dict, chat: str = "") -> str:
    """One action the owner said yes to in the heartbeat's queue, run as their own and nothing else.

    In a task of its own, so none of the beat's marks - nobody watching, held to the
    heartbeat's rules, a mail turn - reach it: it is their yes that runs it, and only under
    it does what never runs without one, a refund, run (`heartbeat.APPROVED`). What it
    draws is kept in the chat of the quest it was for, or the Heartbeat chat.
    """
    from . import heartbeat as hb, mail_turn
    from .tenancy import SPEAKER

    row = await asyncio.to_thread(hb.state_of, who)

    async def run() -> str:
        SPEAKER.set(who)
        hb.BEAT.set(None)
        # His yes, so what it makes is his (`rouh/task_origin.py`).
        task_origin.his()
        hb.TURN_NOTE.set(False)
        hb.APPROVED.set(True)
        protected.UNATTENDED.set(False)
        mail_turn.CURRENT.set(None)
        where = chat or (row.chat_id if row is not None else "")
        if where:
            memory_mod.ANSWERING.set(where)

        async def emit(_message) -> None:
            return None
        return str(await tools.call(name, args, emit))

    return await asyncio.create_task(run())


async def _heartbeat_turn(chat: str, note: str) -> "Turn":
    """A beat's turn: a note in the Heartbeat chat, answered now, spoken nowhere."""
    return await Turns.start(chat, f"{turnmarks.NOTE} {note}]", asked_by=None, speak=False,
                             answer_now=True, note=True)


#: The heartbeat (`rouh/heartbeat.py`): Rouh's own turn every half hour or so, and when
#: work it cares about finishes, on its duties in a chat of its own and on each quest
#: it carries in that quest's chat, for the install's owner.
pulse = heartbeat.Heartbeat(
    start_turn=lambda chat, note: _heartbeat_turn(chat, note),
    busy=_heartbeat_busy, owner=lambda: telegram.phone_owner(tenancy),
    new_chat=lambda title, task_id="": _heartbeat_chat(title, task_id),
    call_tool=lambda who, name, args, chat="": _heartbeat_tool(who, name, args, chat),
    phone=tools.telegram, public_url=config.public_url,
    cancel=lambda chat: Turns.cancel(chat),
    changed=lambda: _heartbeat_changed())


async def _heartbeat_changed() -> None:
    """The heartbeat's queue or state moved: the chats, the decisions it asks, and the goal
    pages, whose quest steps say what its beats are doing (`questcheck.for_goal`)."""
    desk.poke()
    await announce_chats()
    with contextlib.suppress(Exception):
        await timekeeper.tell(await asyncio.to_thread(telegram.phone_owner, tenancy))


async def _decision_to_task(folder: str, text: str) -> tuple[str, str]:
    """The owner's answer to a task's question, given anywhere but the task's own page: said in the
    chat the task's answers go into (`conversations.answer_for_task`) as his own words, the
    way a message from his phone is (`_phone_turn`), and answered there. Waits for a turn
    already running in that chat to end rather than talk over it."""
    chat = await asyncio.to_thread(conversations.answer_for_task, folder)
    if not chat:
        return "", ""
    for _ in range(90):
        if not Turns.busy(chat):
            break
        await asyncio.sleep(2.0)
    await Hub.mirror(None, "user", text, chat=chat)
    await Turns.start(chat, text, asked_by=None, speak=False, answer_now=True)
    with contextlib.suppress(Exception):
        await announce_chats()
    row = await asyncio.to_thread(memory.chat, chat) or {}
    title = str(row.get("title") or "")
    return chat, "" if conversations.is_untitled(title) else title


async def _decisions_push(who, message: dict) -> None:
    """One message to every open tab of this person's, and nobody else's."""
    for tab in list(Hub.sockets):
        me = getattr(tab, "me", None)
        if getattr(tab, "closed", True) or me is None:
            continue
        if (str(me.user_id), str(me.org_id)) != (str(who.user_id), str(who.org_id)):
            continue
        with contextlib.suppress(Exception):
            await tab.emit(message)


#: One message to every open tab of one person's, for whatever else lists something of theirs:
#: their thoughts (`rouh/thoughts.py`).
push_person = _decisions_push


#: Decisions (`rouh/decisions.py`): every question waiting on the person, from every part of
#: Rouh that asks one, in one record, answered in one way. The desk keeps it level with its
#: sources and sends each answer back to the source that asked (`rouh/decision_desk.py`).
desk = decision_desk.Desk(owner=lambda: telegram.phone_owner(tenancy), push=_decisions_push,
                          telegram=tools.telegram, public_url=config.public_url)

#: Notices (`rouh/notices.py`): what Rouh has to tell the person drops in at the top of their
#: screen, and goes to their phone only if it is left there.
notices.hooks.owner = lambda: telegram.phone_owner(tenancy)
notices.hooks.push = _decisions_push
notices.hooks.telegram = tools.telegram
notices.hooks.public_url = config.public_url
notices.hooks.phone_decision = desk.phone_decision
notice_sweeper = notices.Sweeper()
#: The gene lab's look at the registry it is pointed at: the blocklist, and what is new
#: (`rouh/genelab.py`). Asks nobody while no registry is set.
gene_watch = genelab.Watch()
#: Changes a run proposes for this Rouh's own code, and the doctor's word, picked up where a
#: protected core is beside it (`rouh/codechanges.py`, guard/README.md). Asks nothing elsewhere.
code_changes = codechanges.Watch()
decision_sources.hooks.deliver_task = _decision_to_task
decision_sources.hooks.heartbeat = pulse
decision_sources.hooks.one_answer = lambda qid, answer: tools._one_ask(
    "answer", question=qid, answer=answer)
decision_sources.hooks.one_questions = lambda: OneFeed.questions
decision_sources.hooks.keeper = timekeeper
decision_sources.hooks.conflict_answer = lambda cid, pick: ConflictFeed.answer(cid, pick)
decision_sources.hooks.cfg = config
decision_sources.hooks.reply_to_task = lambda run_id, words: tools._reply_to_task(
    {"id": run_id, "answer": words}, Hub.broadcast)
decision_sources.hooks.mail_desk = lambda: mail_alerts.cases if mail_alerts is not None else None


async def _delegate_mail(who, address: str, subject: str, body: str):
    """One email from Rouh's own mailbox to somebody the owner gave authority over a piece of
    work: the decisions waiting on them (`rouh/delegation.py`). Nothing goes where new mail
    is not set up."""
    if mail_alerts is None:
        raise RuntimeError("Rouh's own mailbox is not set up here")
    return await mail_alerts._clients.for_user(who).gmail.send(address, subject, body,
                                                               signed=False)


desk.mail = _delegate_mail


def _nightly_hooks() -> None:
    """What the nightly feature run's night and its tools borrow from here (`rouh/nightly_feature.py`)."""
    from . import nightly_feature, starting

    nightly_feature.hooks.start = lambda **fields: starting.start(
        cfg=config, crew=crew, one=one, emit=Hub.broadcast, **fields)
    nightly_feature.hooks.gmail = ((lambda who, clients=GoogleClients(google_auth, config):
                                    clients.for_user(who).gmail)
                                   if google_auth is not None else None)
    nightly_feature.hooks.say = lambda run_id, words: tools._reply_to_task(
        {"id": run_id, "answer": words}, Hub.broadcast)
    nightly_feature.hooks.phone = tools.telegram
    nightly_feature.hooks.public_url = config.public_url


_nightly_hooks()


def _job_gateway_hooks() -> None:
    """Rouh's own tools, lent to every background job through its gateway (`rouh/job_gateway.py`):
    the registry a turn uses, the heartbeat's queue for what needs the owner's yes, and Rouh's own
    Gmail for mail_find and mail_file (`rouh/job_mail.py`)."""
    from . import job_gateway, job_mail

    job_gateway.hooks.registry = tools
    job_gateway.hooks.changed = _heartbeat_changed
    job_mail.hooks.gmail = ((lambda who, clients=GoogleClients(google_auth, config):
                             clients.for_user(who).gmail)
                            if google_auth is not None else None)


_job_gateway_hooks()


def _refactor_hooks() -> None:
    """What the nightly refactoring run borrows from here (`rouh/nightly_refactor.py`)."""
    from . import nightly_refactor, starting

    nightly_refactor.hooks.start = lambda **fields: starting.start(
        cfg=config, crew=crew, one=one, emit=Hub.broadcast, **fields)


_refactor_hooks()


def _case_fix_hooks() -> None:
    """What the runs fixing a false alarm's check borrow from here (`rouh/case_fixes.py`)."""
    from . import case_fixes, starting

    case_fixes.hooks.start = lambda **fields: starting.start(
        cfg=config, crew=crew, one=one, emit=Hub.broadcast, **fields)
    case_fixes.hooks.say = lambda run_id, words: tools._reply_to_task(
        {"id": run_id, "answer": words}, Hub.broadcast)
    case_fixes.hooks.stop = lambda run_id: tools._stop_task({"id": run_id}, Hub.broadcast)
    case_fixes.hooks.desk = lambda: mail_alerts.cases if mail_alerts is not None else None


_case_fix_hooks()


def _meeting_next_hooks() -> None:
    """What the work after a meeting borrows from here to start its runs (`rouh/meeting_next.py`)."""
    from . import starting

    meeting_next.hooks.start = lambda **fields: starting.start(
        cfg=config, crew=crew, one=one, emit=Hub.broadcast, **fields)


_meeting_next_hooks()


def _task_comments_hooks() -> None:
    """What Have a job apply them borrows from here to start its runs (`rouh/task_comments.py`)."""
    from . import starting, task_comments

    task_comments.hooks.start = lambda **fields: starting.start(
        cfg=config, crew=crew, one=one, emit=Hub.broadcast, **fields)


_task_comments_hooks()


async def _thought_task_made(task_id: str) -> None:
    """A new thought's own task (`rouh/thought_enrich.py`): on every screen, then filed into the
    project it belongs in, waited for so its run is told the folder it stays in."""
    with contextlib.suppress(Exception):
        await announce_objects()
        await _announce_workspace()
    task_id = str(task_id)
    if task_id in NewTasks.working:
        return
    NewTasks.working.add(task_id)
    try:
        await NewTasks._file(task_id)
    finally:
        NewTasks.working.discard(task_id)


def _thought_enrich_hooks() -> None:
    """What a new thought's enriched version borrows from here to start its run (`rouh/thought_enrich.py`)."""
    from . import starting, thought_enrich

    thought_enrich.hooks.start = lambda **fields: starting.start(
        cfg=config, crew=crew, one=one, emit=Hub.broadcast, **fields)
    thought_enrich.hooks.made_task = _thought_task_made


_thought_enrich_hooks()


#: Each person's Google services for the morning brief, or None where Google is
#: off on this install (`rouh/morning_brief.py`).
brief_google = ((lambda who, clients=GoogleClients(google_auth, config): clients.for_user(who))
                if google_auth is not None else None)

#: The morning brief, made at each person's time every morning, with the link
#: sent to the phone the bot reaches (`rouh/morning_brief.py`).
mornings = morning_brief.Mornings(tenancy=tenancy, telegram=tools.telegram,
                                  public_url=config.public_url, google=brief_google,
                                  mailboxes=mailbox_auth)

#: Before you meet: each outside meeting's note on the phone an hour before it
#: (`rouh/meeting_prep.py`, behind its switch `meeting_prep`).
meeting_notes = meeting_prep.Notes(tenancy=tenancy, telegram=tools.telegram,
                                   public_url=config.public_url, google=brief_google)

#: What to raise: where things stand with an outside meeting's guests and what to raise,
#: on the phone an hour before it (`rouh/meeting_brief.py`, behind its switch `meeting_brief`).
meeting_raises = meeting_brief.Raises(tenancy=tenancy, telegram=tools.telegram,
                                      public_url=config.public_url, google=brief_google)

#: After a meeting: the work its notes call for, read once they reach Synapse from the meeting
#: library and waiting in Decisions to be started with one press (`rouh/meeting_next.py`,
#: behind its switch `meeting_next`).
meeting_followups = meeting_next.Reader(owner=lambda: telegram.phone_owner(tenancy),
                                        poke=lambda: desk.poke())

#: Answered in a chat: a question waiting in Decisions that he already answered in a chat
#: shows his words, to answer it with them in one press (`rouh/answered_in_chat.py`, behind
#: its switch `answered_in_chat`).
answered_chats = answered_in_chat.Reader(owner=lambda: telegram.phone_owner(tenancy),
                                         poke=lambda: desk.poke(), tell=lambda who: desk.tell(who))

#: Sources checked: a page with footnotes has its sources read against what it says they say, only
#: when the owner presses Check sources beside it (`rouh/source_check.py`, behind its switch
#: `source_check`).
source_checks = source_check.Reader(owner=lambda: telegram.phone_owner(tenancy),
                                    root=lambda: config.assistant_repo,
                                    browser=browser_desk.read)

#: Sent by you: a reply the owner sends themselves, to mail a task drafted for them, kept in the task's
#: notes in their own words, found in their read-only sent mail (`rouh/sent_by_you.py`, behind its
#: switch `sent_by_you`).
sent_replies = sent_by_you.Watcher(owner=lambda: telegram.phone_owner(tenancy),
                                   auth=lambda: mailbox_auth, cfg=config,
                                   root=lambda: config.assistant_repo)


#: Shared until: a share given an end in the Share panel taken away by itself when it comes
#: (`rouh/share_ends.py`, behind its switch `share_ends`).
from . import share_ends as share_ends_mod  # noqa: E402

share_endings = share_ends_mod.Sweeper()
#: Who is coming: every guest of the next week's meetings looked up on LinkedIn ahead of time
#: and kept on their contact (`rouh/meeting_people.py`, behind its switch `meeting_people`).
meeting_research = meeting_people.Researcher(tenancy=tenancy, google=brief_google,
                                             apify=tools.apify)

#: Everybody from his meetings of fewer than twenty people, added to his iCloud contacts
#: (`rouh/meeting_contacts.py`, behind its switch `meeting_contacts`).
meeting_contacts_adder = meeting_contacts.Adder(tenancy=tenancy, google=brief_google,
                                                contacts=lambda: contacts, apify=tools.apify)


def _decision_number(source: str, source_id: str) -> int | None:
    """The number of the owner's decision a source asks under this id, for a message the
    source sends by itself (`decisions.numbers_of_sources`); None when there is none."""
    from . import decisions, telegram
    from .tenancy import Tenancy

    try:
        who = telegram.phone_owner(Tenancy())
        if who is None:
            return None
        return decisions.numbers_of_sources(who, source, [source_id]).get(str(source_id))
    except Exception:
        log.exception("the decision number of %s %s could not be read", source, source_id)
        return None


async def _phone_turn(chat: str, content, heard) -> "Turn":
    """A turn in `chat` answering what the owner wrote on Telegram (`rouh/telegram_chat.py`).

    Their own words, as if typed into the box, and answered now: a message sent
    from a phone is a finished request. Spoken nowhere, because they are on the
    phone and not at the screen that would speak it; every screen standing in
    the chat still watches it being written.
    """
    return await Turns.start(chat, content, asked_by=None, speak=False,
                             answer_now=True, also=heard)


def _card_address(spec: dict, chat: str) -> str:
    """Where a card a turn from the phone drew can be opened: its own address."""
    public = (config.public_url or "").rstrip("/")
    if not public:
        return ""
    number = spec.get("card_id")
    if artifacts.enabled() and isinstance(number, int):
        return public + addressing.url_for("artifact", f"{artifacts.CARD}{number}")
    return public + addressing.url_for("chat", chat)


#: The owner writing to Rouh from their phone (`rouh/telegram_chat.py`): the loop
#: that reads the bot, lets only their own chat through, answers each message as
#: a turn in the chat it was written to - General from the private chat, a fork
#: from its own group (`rouh/telegram_forks.py`) - and sends the answer back. It does nothing on a
#: machine with no bot set up, which is every test world.
#: Everybody else who writes to the bot: a trusted contact's own Telegram
#: account, linked by them and confirmed by the owner, whose every message is a
#: case held to what they may do by email; a link code; or nobody, ignored
#: (`rouh/telegram_guests.py`).
telegram_guests = telegram_guests_mod.Guests(
    tools.telegram, owner=lambda: telegram.phone_owner(tenancy),
    desk=lambda: mail_alerts.cases if mail_alerts is not None else None,
    public_url=config.public_url)
phone_chat = telegram_chat.PhoneChat(
    tools.telegram, files=files, ears=ears, public_url=config.public_url,
    general=lambda: memory.ensure_general(),
    start_turn=lambda chat, content, heard: _phone_turn(chat, content, heard),
    busy=lambda chat: Turns.busy(chat),
    mirror=lambda chat, text, shown: Hub.mirror(None, "user", text, shown, chat=chat),
    owner=lambda: telegram.phone_owner(tenancy),
    card_link=_card_address,
    changed=lambda: announce_chats(),
    account=telegram_accounts, guests=telegram_guests)

#: Slack, listened to (`rouh/slack_listen.py`): every connected organisation's Socket Mode
#: connection kept open, every message its app can see kept, and a direct message to Rouh or an
#: @Rouh mention handed over - the person's own as a turn of their own, answered back in Slack;
#: anybody else's as a case, like their email. It does nothing until Slack is connected in
#: Settings, which is every test world unless one connects its stand-in.
from . import slack_listen as slack_listen_mod

slack_listener = slack_listen_mod.Listener(
    desk=lambda: mail_alerts.cases if mail_alerts is not None else None,
    converse=lambda *args: answer_an_email(*args),
    open_chat=lambda was, title: open_email_chat(was, title),
    tenancy=tenancy)



async def start_run_for(*, brief: str, title: str, workspace: str = "",
                        policy: str = "", preset: str = "", org_id: str = "") -> dict:
    """One run, started the one way every run on this machine is started.

    Handed to the feedback router so that module knows nothing about the crew,
    the one program or the socket. The broadcast afterwards is what puts the
    new run on every open task list at once, which is what happens when a run
    is started from the sidebar and has to happen when one is started from a
    feature request too.

    `preset` is for the caller that has nobody to ask which workspace and which
    policy: a run started by itself out of a feedback takes
    `improve_myself`, which is Rouh's own code, the one program first and a
    worker here when there is no program (`rouh/triage.PRESET`).

    `org_id` is whose run it is, for its model and how deeply it thinks
    (`rouh/modeldefaults.py`): the feedback's organisation, or the person's
    who pressed Start.

    Raises `starting.CannotStart` with the sentence to say when nothing would
    take it.
    """
    got = await starting.start(brief=brief, title=title, workspace=workspace,
                               policy=policy, preset=preset, org_id=org_id,
                               cfg=config, crew=crew, one=one)
    with contextlib.suppress(Exception):
        await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
    return got


async def restart_job(run_id: str, *, org_id: str = "") -> dict:
    """A job that died, started again from the Restart button on its card.

    `starting.restart` is the whole of what starting it means. What is here is
    what the rest of Rouh has to hear: a feature request its death marked
    failed is building again on the new job, and every open task list shows
    the new card in the dead one's place.

    Raises `starting.CannotStart` with the sentence to say when it cannot be.
    """
    got = await starting.restart(run_id, crew=crew, emit=Hub.broadcast)
    if got.get("id") and not got.get("already") and org_id:
        try:
            moved = await asyncio.to_thread(gene_therapy.run_restarted, org_id, run_id, got["id"])
        except Exception:
            log.exception("the requests job %s was building could not follow it", run_id)
            moved = 0
        if moved:
            await announce_gene_therapy()
    with contextlib.suppress(Exception):
        await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
    TreeFeed.poke()
    return got


async def announce_gene_therapy() -> None:
    """Every open board, redrawn. What the converter says when it has done
    something, and what the board's own switches say when one is moved."""
    with contextlib.suppress(Exception):
        await Hub.broadcast({"type": "gene_therapy"})


#: What carries a feedback the rest of the way with nobody in the middle: reads
#: it, writes the feature request, starts the run, and sweeps for whatever was
#: left behind (`rouh/triage.py`). It is handed the same `start_run_for` the
#: board's own button uses, so a run it starts is a run of exactly the same
#: kind.
converter = triage.Converter(
    gene_therapy, start_run_for,
    on_change=announce_gene_therapy,
    sweep_minutes=config.gene_therapy_sweep_minutes,
    enabled=config.gene_therapy_auto,
)

class GeneTherapySweep:
    """The converter's beat, as something that can be stopped.

    A bare `create_task` would be a task nobody holds: it can be collected
    mid-sweep, and there would be no way to end it when this process is asked
    to go. One class attribute is the whole of what it needs to be neither of
    those things.
    """

    task: asyncio.Task | None = None

    @classmethod
    def start(cls) -> None:
        if cls.task is None or cls.task.done():
            cls.task = asyncio.create_task(converter.sweeping())

    @classmethod
    async def stop(cls) -> None:
        if cls.task is not None:
            cls.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await cls.task
            cls.task = None

#: How far back "today" goes for the spend figures: midnight on the owner's clock
#: (`clock.now`, else the installation's `clock.DEFAULT`), not this machine's.
def _since_midnight() -> float:
    now = clock.now()
    return now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def spend_now(session_id: str = "") -> dict:
    """Tokens and money: today, this chat, and all of it.

    Three because they answer three different questions, and a person asking
    "what is this costing me" means a different one on different days.
    """
    today = memory.spend(since=_since_midnight())
    out = {
        "today": today,
        "all_time": memory.spend(),
        "said": {
            "today": costs.money(today["cost"]),
            "cached": int(today["cached"] * 100),
        },
    }
    if session_id:
        out["chat"] = memory.spend(session_id=session_id)
        out["said"]["chat"] = costs.money(out["chat"]["cost"])
    return out


#: How many cards the canvas asks for at a time. The page draws the newest of
#: them when it opens and asks for the next lot as the reader scrolls back, so
#: a canvas with a thousand cards on it costs the same to open as an empty one.
CANVAS_PAGE = 10
CANVAS_PAGE_MAX = 50

#: The most runs one `mark_seen` may name at once. Landing on the runs list
#: marks every run it was counting, and the list the page draws is capped well
#: below this (`runs.LIMIT`); the number is here so a message from somewhere
#: else cannot ask for a write per id for as long as it likes.
MARK_SEEN_MOST = 500


#: The deploys being waited on, so neither they nor the work they are waiting
#: on can be collected while they are still running.
_watching_a_deploy: set = set()


async def _announce_one_deploy(work: "asyncio.Task[dict]") -> None:
    """Wait for the deploy and tell every open tab what happened to it."""
    try:
        done = await work
    except Exception:
        log.exception("deploying the one program failed")
        done = {"ok": False, "log": "",
                "error": "Deploying the one program failed. The server's log says why."}
    await Hub.broadcast({"type": "one_deploy", "ok": bool(done.get("ok")),
                         "error": done.get("error") or ""})
    # The commit the program reports now, asked of the program itself, so what
    # the chip says after a deploy is what is serving and not what was hoped
    # for. A deploy that failed sends it too: the two commits are then as far
    # apart as they were, which is exactly the point.
    with contextlib.suppress(Exception):
        if shown := await one_version.snapshot(one):
            await Hub.broadcast({"type": "one_version", **shown})


async def deploy_onto_a_landed_change(sha: str, files: list[str]) -> str:
    """Deploy onto a change a run of the one program has just put on main.

    The person's standing policy, and there is no approval step in it: work
    that passes its tests is committed, pushed to main and deployed from there
    without anybody being asked. So this is called by ``one_jobs.OneLander``
    the moment a run in the space "rouh" lands, and what it returns is the
    record of what was deployed, which goes on the card and is said out loud.

    **Both services, every time, whatever the change touched.** Two of them
    come out of this one repository, and this used to deploy the one program
    only when a file under ``one/`` had changed, on the reasoning that nothing
    else could have affected it. It is not true: the two share this repository,
    and a program left on an older commit of it is a program whose checkout
    disagrees with the Rouh talking to it. Every automatic deploy between
    6edd106 and 7596716 moved Rouh alone, and the one program sat four
    commits behind with nothing on any screen saying so. One script now moves
    both, in one go, onto the one commit (``update-all.sh``).

    ``files`` is still taken, because the lander has the list and a later
    reader will want it in the log, but nothing here decides anything by it.
    That decision was the bug.
    """
    if not config.enable_self_update:
        # Rouh will not restart itself on this machine, which is what a test
        # and a laptop are. The one program still catches up, through its own
        # half, started and let go of: the tabs hear how it went through
        # `_announce_one_deploy`, as they do for the button under the chip.
        said = []
        try:
            work = deployer.start()
        except one_deploy.AlreadyDeploying:
            said.append("the one program was already being deployed")
        else:
            watching = asyncio.create_task(_announce_one_deploy(work))
            _watching_a_deploy.add(watching)
            watching.add_done_callback(_watching_a_deploy.discard)
            said.append("the one program is being deployed")
        said.append("Rouh was not restarted onto it, because self-update is off here")
        return "; ".join(said)
    try:
        one_deploy.start_deploy(config)
    except one_deploy.AlreadyDeploying as exc:
        # Two runs finishing seconds apart. The deploy already going fetches
        # main, so it carries this change too; a second one would only be two
        # git commands racing over the same checkout.
        return f"Rouh is already restarting, and takes this with it ({exc})"
    except Exception as exc:
        log.exception("neither service could be deployed onto %s", sha or "the change")
        return f"nothing could be deployed onto it: {exc}"
    # The card for it, on every open tab, the same one `deploy_myself` puts
    # there. `start_deploy` wrote the row; this is only what sends it, so a
    # screen being looked at while a run lands a change shows the deploy
    # rather than nothing at all.
    with contextlib.suppress(Exception):
        await self_update.push()
    return (f"the one program and Rouh are both being put on {sha or 'main'}; "
            "Rouh is restarting onto it")


def watch_one_deploy(work: "asyncio.Task[dict]") -> None:
    """Keep a deploy of the one program, and tell every tab how it went.

    Kept until it is done: the event loop holds nothing but a weak reference to
    a task, and a deploy collected half way through would leave the button
    saying "Deploying..." in every open tab for ever.
    """
    watching = asyncio.create_task(_announce_one_deploy(work))
    _watching_a_deploy.add(watching)
    watching.add_done_callback(_watching_a_deploy.discard)


async def crew_event(query: dict, body) -> dict:
    """One hook from Claude Code in a worker's worktree, and what it changes.

    Two kinds of call arrive on this one endpoint and they cost very different
    amounts. Three hooks say what became of the job: it stopped, it wants a
    person, its session ended. Those are rare, and each one is worth reading the
    worker's screen for and telling every open tab about.

    The other four say what the worker is doing right now, and a busy worker
    fires several a second. They are stored and nothing else happens: no screen
    is read, no task list is rebuilt, no broadcast is sent. The work tree picks
    them up on its own half-second beat.

    The web layer has already checked the caller is this machine
    (`rouh/web/views.py`, `crew_event`).
    """
    if crew is None:
        return {"ok": False, "reason": "delegation is off"}
    # The crewmate id and the kind travel in the query string, which the crew
    # manager builds itself. Without this merge both had to be recovered from
    # the body, which works but means a directory lookup per tool call.
    payload = {**dict(query), **(body if isinstance(body, dict) else {})}

    kind = crew_kind(payload.get("kind") or payload.get("hook_event_name") or "")
    if kind in TELEMETRY_KINDS:
        await crew.handle_event(payload)
        return {"ok": True, "telemetry": True}

    was = _status_before(payload)
    result = await crew.handle_event(payload)
    if result is None:
        return {"ok": True, "matched": False}

    row = result.as_dict() if hasattr(result, "as_dict") else dict(result)

    # Late news about a job that has ended, which changes nothing about it:
    # Claude Code's "waiting for your input" a minute after a job finishes, its
    # SessionEnd a second after one is stopped. handle_event leaves the job
    # alone, and so does every open page: nothing is sent.
    if was and row.get("status") == was and is_late_news(kind, was, payload):
        log.info("crew %s: late %s about an ended job, nothing sent", row.get("id"), kind)
        return {"ok": True, "late": True}

    detail = row.get("detail", "") or ""

    # What a finished job did is in its own closing message, which Claude Code
    # hands the Stop hook. That goes under its title, not the last line on its
    # screen, which for a finished job is Claude Code's mode line.
    if kind == "stop" and row.get("status") == "done":
        from .crew import closing_line

        said = closing_line(payload.get("last_assistant_message") or "")
        if said:
            detail = said
            with contextlib.suppress(Exception):
                crew.set_meta(row["id"], closing=said)

    # A worker that stops is almost always asking something, and the question is
    # only on its terminal. Read it here rather than making someone ask twice.
    if row.get("status") in ("waiting", "done"):
        try:
            seen = await crew.describe(row["id"], lines=60)
            if seen.get("asking"):
                choices = ", ".join(
                    f"{o['number']} {o['label']}" for o in (seen.get("options") or [])[:4]
                )
                detail = seen.get("question") or "waiting for an answer"
                if choices:
                    detail = f"{detail}  [{choices}]"
                row["asking"] = True
                row["question"] = seen.get("question")
                row["options"] = seen.get("options")
            else:
                detail = detail or (seen.get("last_line") or "")[:160]
        except Exception as exc:
            log.warning("could not read %s's screen: %s", row.get("id"), exc)

    log.info("crew %s -> %s%s", row.get("id"), row.get("status"),
             f" ({detail[:120]})" if detail else "")
    await Hub.broadcast({
        "type": "task",
        "id": row.get("id"),
        "status": row.get("status"),
        "title": row.get("title"),
        "detail": detail[:300],
        "asking": bool(row.get("asking")),
        "options": row.get("options") or [],
    })
    await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
    return {"ok": True}


def _status_before(payload: dict) -> str | None:
    """The status of the job a hook is about, before the hook is applied.

    Found the way handle_event finds it: by the id in the query string, or else
    by the folder Claude Code says it is working in. None when there is no such
    job, and when the lookup fails, so a hook is then handled as it always was.
    """
    try:
        crew_id = str(payload.get("crew") or payload.get("crew_id") or payload.get("id") or "").strip()
        mate = crew.get(crew_id) if crew_id else None
        if mate is None and payload.get("cwd"):
            mate = crew.find_by_workdir(str(payload["cwd"]))
    except Exception:
        return None
    return mate.status if mate is not None else None


async def wipe_test_jobs() -> dict:
    """Forget every finished job a live check started ("... - safe to delete").

    The checks call this when they finish, so a run leaves the task list as it
    found it. The web layer has checked the caller is this machine.
    """
    if crew is None:
        return {"ok": False, "reason": "delegation is off"}
    out = await crew.forget_test_jobs()
    gone = [row["id"] for row in out["removed"]]
    log.info("wiped %d test job(s), left %d", len(gone), len(out["skipped"]))
    if gone:
        # A task list only ever adds to what a tab shows, so the tabs are told
        # by name which jobs to drop. The crew has already pushed the tree.
        await Hub.broadcast({"type": "tasks_forgotten", "ids": gone})
        await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
    return {"ok": True, **out}


def started_key(row: dict) -> tuple[float, str]:
    """When a job started, which is the only thing the task list is ordered by.

    The list used to move under the person's eyes: it was ordered by when each
    job last did something, so a job that printed a line jumped over one that
    was quiet, and the row they were about to click was somewhere else by the
    time they clicked. Now a row keeps the place it had when it appeared. Only
    a newer job arriving above it, or a job leaving the list, moves it.

    The id is here so two jobs started in the same instant do not swap places
    between one build of the list and the next.

    The two halves write times differently - a background job
    "2026-09-16T11:00:00+00:00", a run of the one program
    "2026-09-16T11:00:00.412Z" - so the strings are turned into seconds rather
    than compared as text. A job with no start time at all sorts last.
    """
    when = clock.moment(row.get("created_at"))
    return (when.timestamp() if when else float("-inf"), str(row.get("id") or ""))


async def task_list() -> list[dict]:
    """Every run this machine knows about, newest started first.

    One register, one query. A background worker, a run of the one program and
    anything else that runs are the same kind of thing, so this is the same
    list `check_tasks` reads and the same list the orb is drawn from, and the
    three cannot disagree (`rouh/runs.py`). Read from the database rather
    than remembered from events, because events only exist while a tab is open
    and a job started yesterday has to still be on the list.

    The crewmates are reconciled against tmux first, because a worker whose
    window has gone is only found by looking, and what that finds is written
    straight into the register.

    Each row carries its owner as well since step five: a run is an orphan
    until somebody attaches it to a task, a chat or a project, and the list is
    where that is read and changed.
    """
    if crew is not None:
        with contextlib.suppress(Exception):
            await crew.reconcile()
    live = {rid: {"terminal": r.get("terminal")} for rid, r in list(OneFeed.runs.items())}

    # On a thread: every run and its owner, which held the loop - and every tab
    # with it - for 100 to 300 ms on each connect (23 October 2026).
    def listed() -> list[dict]:
        out = runs.rows(live=live)
        _how_the_dead_restart(out)
        return _the_rest_of_the_list(owning.decorate(out, "run"))

    return await asyncio.to_thread(listed)


def _how_the_dead_restart(rows: list[dict]) -> None:
    """Each of Rouh's own jobs that died, with whether its card can restart it.

    `restartable` puts the Restart button on its card, and `restarted_as` is
    the job that replaced it, once it has been restarted. Neither is in the
    register, which knows a run and not the crew's row behind it, so both are
    read off the crew in one query.
    """
    if crew is None or not any(r.get("status") == "lost" for r in rows):
        return
    try:
        again = crew.restarts()
    except Exception:
        log.exception("could not read which dead jobs were restarted")
        return
    for row in rows:
        rid = str(row.get("id"))
        if row.get("status") != "lost" or rid not in again:
            continue
        row["restarted_as"] = again[rid]
        row["restartable"] = not again[rid]


async def remember_what_it_changed(run_id: str) -> None:
    """A run's diff, written down as the artifact it is.

    What a run did to the files is the first thing anybody wants of a finished
    run, and until step five it was a question asked of git every time somebody
    wondered. It is an artifact: kind `diff`, owned by the run and made by the
    run. Owned is the word that matters - it travels with the run, so attaching
    a run to a task puts its diff under that task without anything being
    copied, and detaching takes it back.

    Asked of whichever half actually ran it, once, when it ends. Never a
    reason a job fails: a diff that cannot be read is a diff that is not
    written down.
    """
    try:
        if runs.is_one_run(run_id):
            got = await one.ask("run", run=run_id, entries=0)
            row = (got or {}).get("run") or {}
            changes = {"files": row.get("files") or [], "in_main": row.get("landed")}
        elif crew is not None:
            changes = await crew.changes(run_id)
        else:
            return
        await asyncio.to_thread(owning.record_diff, run_id, changes)
    except Exception:
        log.debug("could not write down what run %s changed", run_id, exc_info=True)


def _the_rest_of_the_list(out: list[dict]) -> list[dict]:
    """What goes on the task list that is not a run, and the order it all reads in.

    Two things belong on the list and are not running work: a job whose work
    will not go onto main, which has stopped and can only be moved by a person,
    and Rouh restarting onto its own new code. Both are drawn the same way
    whether the runs came from the register or from the two halves it replaced.
    """
    # A job waiting on a conflict, red with its question on it. Folded into the
    # row the job already has where there is one, so a run of the program does
    # not appear twice; added as a row of its own where the job is gone, because
    # a question nobody can see is a question nobody answers.
    by_id = {str(row.get("id")): row for row in out}
    for row in ConflictFeed.rows():
        rid = str(row.get("id"))
        if (already := by_id.get(rid)) is not None:
            # Not the title. The register holds the job's own, "Feedback
            # system", and the record holds whatever `land.sh` could work out,
            # which is often only the run's short id. Folding the record over
            # the row renamed three jobs to their own ids on the task list.
            already.update({k: v for k, v in row.items() if k not in ("id", "title")})
            ConflictFeed.own_rows.discard(rid)
        else:
            out.append(row)
            ConflictFeed.own_rows.add(rid)
    # Rouh restarting onto its own new code. It is not a worker and not a run
    # of the one program, so nothing else on this list would ever carry it, and
    # a card that is on no list is a card no snapshot can correct: see
    # self_update.py for the "Updating Rouh - WORKING" that never went away.
    if (deploy := self_update.row()) is not None:
        out.append(deploy)
    out.sort(key=started_key, reverse=True)
    return out


def tree_snapshot() -> dict:
    """The work tree as it is this instant, built from the one register.

    Built every time rather than kept in memory, for the same reason the task
    list is read from the database: a tab that has just opened must not see a
    different world from one that has been open all day, and a restart must not
    lose the shape.
    """
    try:
        return _with_conflicts(_tree_from_the_register(time.time()))
    except Exception:
        log.exception("could not build the work tree")
        return empty_tree()


def _tree_from_the_register(now: float) -> dict:
    """The orb's tree, with its shape taken from `run.parent_run_id` and nothing else.

    A spike is a top-level run, a branch is a run with a parent, and a run that
    is waiting is the red NEEDS YOU node - all from the one register the task
    list and `check_tasks` are answered from, so the orb can no longer show a
    job neither of them has heard of.

    Two things are grafted onto that shape and neither of them is a run. The
    twigs are the tool calls inside each run, which come from that run's own
    hooks because a step is not a run and was never in the register, with
    the effort each run says it thinks at beside them. And Rouh's own work
    hangs straight off the core, because Rouh is the core and not a job it
    started.
    """
    hooks = [build_tree(crew.tree_events(now=now), now=now)] if crew is not None else []
    if OneFeed.tree:
        hooks.append(OneFeed.tree)
    twigs: dict[str, list] = {}
    efforts: dict[str, str] = {}
    for built in hooks:
        for run_id, calls in runs.twigs_of(built).items():
            twigs.setdefault(run_id, []).extend(calls)
        efforts.update(runs.efforts_of(built))

    out = runs.tree(now, twigs=twigs, efforts=efforts)
    own = build_tree([], now=now, own_events=OwnWork.events(), own_state=OwnWork.state)
    out["children"] = list(own.get("children") or []) + list(out.get("children") or [])
    if out["state"] != "waiting" and own.get("state") == "waiting":
        out["state"] = "waiting"
    elif out["state"] != "waiting" and OwnWork.state:
        out["state"] = OwnWork.state
    return out


def _with_conflicts(tree: dict) -> dict:
    """Put every job whose work will not go onto main on the orb, once each.

    A job stuck on a conflict is not running any more, so nothing else would put
    it on the orb, and the orb is the one place a person is told that something
    must not be left alone. A waiting node draws red and dashed with the words
    NEEDS YOU against it, which is what the whole of this is for.

    Once each is the other half of it. The register often still holds the run
    that raised the conflict, so the job is already a spike, and adding the
    conflict as a second one drew the same job twice: once under its title and
    once under its short id. On 22 September 2026 three jobs drew five NEEDS
    YOU between them that way, and answering a conflict took away one of each
    pair and left the other. So a conflict is folded onto its job's spike where
    there is one, keeping the job's own title as the label, and is a spike of
    its own only where the register has nothing to fold it onto.
    """
    try:
        records = ConflictFeed.waiting()
    except Exception:
        log.exception("could not put the conflicts on the work tree")
        return tree
    if not records:
        return tree
    children = [dict(node) for node in (tree.get("children") or [])]
    spikes = {str(node.get("id")): node for node in children}
    extra: list[dict] = []
    for node in conflicts.tree_nodes(records):
        already = spikes.get(str(node.get("run") or ""))
        if already is None:
            # No run for it in the register: the job is gone, or aged out of
            # the tree's window, and a question nobody can see is a question
            # nobody answers. Its label is the register's title where there
            # still is a row, because "a6aa24af" is not the name of anything.
            row = runs.get(str(node.get("run") or ""))
            if row is not None and row.title:
                node["label"] = row.title[:60]
            extra.append(node)
            spikes[str(node["id"])] = node
            continue
        already.update(state="waiting", conflict=node["conflict"],
                       detail=node["detail"], asking=node["detail"],
                       what=node["what"])
    out = dict(tree)
    out["children"] = children + extra
    out["state"] = "waiting"
    return out


def workspace_tasks() -> list[dict]:
    """The numbered work, for the page's second list (D45).

    Answered from the task rows, which are the truth about a task's number, its
    slug, its title and its state. The workspace on disk is read on the way
    past and reconciled into them, so a folder somebody made by hand a minute
    ago is on the list and a task nobody has written out yet has its folder
    written (`conversations.reconcile`).

    A loose chat is not here and never will be: this is numbered work, and a
    conversation that nobody has promoted has no number to be listed under.
    """
    try:
        return conversations.tasks()
    except Exception:
        log.exception("could not list the workspace's tasks")
        return []


class OneFeed:
    """The one program's runs on the orb, and its questions put to the person out loud.

    One connection kept open to the program: its work tree, which is added to
    Rouh's own so the orb draws its runs like any other job, and every
    question a run is waiting on, which Rouh says out loud in the tab being
    looked at, once, when nobody is talking. The phone is told as well, by the
    program, so a question nobody hears here still finds the person.
    """

    tree: dict = {}
    announced: set[str] = set()
    waiting: dict[str, dict] = {}
    #: Every question the program has open, or None until it has said.
    questions: list[dict] | None = None
    tasks: list[asyncio.Task] = []
    #: The program's runs, for the task list, and what each last showed there.
    runs: dict[str, dict] = {}
    shown: dict[str, tuple] = {}
    #: Reports a finished run Rouh started (``one_jobs.OneLander``), when on.
    lander = None
    #: What the program last said it was, so a restart into different code is
    #: pushed to every open tab rather than waiting for somebody to reload.
    build: tuple | None = None
    #: Whether the program has been asked, once a start, for the space of every run
    #: it holds, so the runs kept before runs had a kind are given theirs.
    kinds_asked: bool = False

    @classmethod
    async def kinds_of_old_runs(cls) -> None:
        """Which half of Metabolism each run is on, for runs that never said.

        A run of the program in Rouh's checkout from before 14 October 2026 has
        nothing on its row to say whether it changed Rouh or did the person's
        work (`0152_run_kind`). The program still knows the space each one was
        started in, so it is asked for all of them once, and only the runs with
        no kind are written. Never a reason anything else fails.
        """
        try:
            got = await one.ask("runs", limit=100000)
            done = await asyncio.to_thread(runs.kinds_from_program, (got or {}).get("runs") or [])
        except Exception:
            log.debug("could not ask the program which space its runs were in", exc_info=True)
            return
        if done:
            log.info("gave %d older runs their half of Metabolism from the program's spaces", done)
            await _announce_tasks()

    @classmethod
    async def on_hello(cls, hello: dict) -> None:
        build = (hello.get("version"), hello.get("commit"))
        if build == cls.build:
            return
        cls.build = build
        with contextlib.suppress(Exception):
            if shown := await one_version.snapshot(one):
                await Hub.broadcast({"type": "one_version", **shown})

    @classmethod
    def on_tree(cls, tree: dict) -> None:
        if tree != cls.tree:
            cls.tree = tree or {}
            cls.register_subagents(cls.tree)
            TreeFeed.poke()

    @classmethod
    def register_subagents(cls, tree: dict) -> None:
        """The sub-agents inside the program's runs, as runs of their own.

        The program sends its work tree already built, and a sub-agent inside
        one of its runs appears there and nowhere else - the runs feed knows
        nothing about it. So it is read off the tree once, here, and written
        into the register with its parent's id on it, which is what makes the
        orb draw it as a branch of that run rather than as a spike of its own.
        """
        def walk(node: dict, parent: str) -> None:
            for child in node.get("children") or ():
                if child.get("kind") != "subagent":
                    continue
                agent = str(child.get("id") or "")
                if not agent:
                    continue
                with contextlib.suppress(Exception):
                    runs.sub_run(parent, agent,
                                 title=str(child.get("label") or "sub-agent"),
                                 at=child.get("opened_at"))
                    if child.get("state") not in ("running", "waiting"):
                        runs.sub_done(agent, at=child.get("closed_at"),
                                      state="failed" if child.get("state") == "failed"
                                      else "done")
                walk(child, agent)

        for run_node in (tree or {}).get("children") or ():
            walk(run_node, str(run_node.get("id") or ""))

    @classmethod
    async def on_runs(cls, run_list: list, full: bool = False) -> None:
        """Every run on connecting, then each one that changed, onto the task list.

        The name is `run_list` rather than `runs` because `runs` is the
        register this writes into (`rouh/runs.py`), which is the one place
        every kind of running work is kept since the object model was turned on.
        """
        if full:
            cls.runs = {r["id"]: r for r in run_list if r.get("id")}
            for run in cls.runs.values():
                runs.one_run(run)
            await _announce_tasks()
            if not cls.kinds_asked:
                cls.kinds_asked = True
                cls.tasks.append(asyncio.create_task(cls.kinds_of_old_runs()))
            return
        for run in run_list:
            if not run.get("id"):
                continue
            if run["id"] not in cls.runs:
                # A run seen for the first time is one just started, from here or
                # from anywhere else the program is asked (`rouh/events.py`).
                events.started("run", str(run["id"]), actor=cls.starter(run), source="server",
                               owner=True, props={"agent": str(run.get("agent") or "")[:40],
                                                  "space": str(run.get("space") or "")[:80]})
                cls.turn_from[str(run["id"])] = time.time()
            cls.runs[run["id"]] = run
            RunSummaries.want(run["id"])
            # The register first, so the row the tab is told is read back out
            # of the one place the task list and check_tasks are answered from
            # and cannot say anything different from either of them.
            runs.one_run(run)
            row = runs.row_for(run["id"], live={"terminal": run.get("terminal")})
            if row is None:
                continue
            row = owning.decorate([row], "run")[0]
            # A run changes with every tool call; its line on the list only
            # when what the line says changes. Whether its terminal is open,
            # and whether the person archived it, are on the line too, so both
            # are part of what "changed" means.
            key = (row["status"], row["title"], row["detail"], row["summary"], row["archived"], row["terminal"])
            if cls.shown.get(run["id"]) == key:
                continue
            cls.shown[run["id"]] = key
            # "idle" is in here beside the three endings because a turn that
            # ended is when a run's diff is worth writing down, whether or not
            # the run itself is over. It used to be covered by "done", which is
            # what a run that had finished its turn was called.
            if row["status"] in ("done", "idle", "failed", "lost", "reaped"):
                asyncio.create_task(remember_what_it_changed(str(run["id"])))
            with contextlib.suppress(Exception):
                await Hub.broadcast({"type": "task", **row})

    #: When each run's current turn began, for how long the turn took.
    turn_from: dict[str, float] = {}

    @classmethod
    def starter(cls, run: dict) -> str:
        """Who set a run going: Rouh, from its own device, or the person, from anywhere else."""
        one = getattr(cls.lander, "one", None)
        device = getattr(one, "device_id", None)
        return "rouh" if device and run.get("by") == device else "person"

    @classmethod
    def on_entry(cls, entry: dict) -> None:
        if cls.lander is not None:
            cls.lander.on_entry(entry)
        # A run whose turn's work was saved, or that ended: the heartbeat hears it
        # (`heartbeat.Heartbeat.run_finished`), once per ending.
        from .one_jobs import turn_over

        if turn_over(entry):
            run = cls.runs.get(str(entry["run"])) or {}
            how = {"work.landed": "finished, its work saved", "work.nothing-new": "finished",
                   "work.not-landed": "finished, and its work could not be saved",
                   "agent.stopped": "stopped", "agent.pause-ended": "stopped waiting",
                   "run.ended": "ended"}.get(entry["kind"], "ended")
            pulse.run_finished(str(entry["run"]), str(run.get("title") or ""), how=how,
                               kind="run of the one program")
            # Each ending of a turn of it, with the time since the one before, so the
            # times add up to the run's working time (`rouh/events.py`).
            rid = str(entry["run"])
            began = cls.turn_from.pop(rid, None) or runs._epoch(run.get("started_at")
                                                                 or run.get("requested_at"))
            events.emit("run.finished", actor=cls.starter(run), source="server", object_type="run",
                        object_id=rid, owner=True,
                        duration_ms=(time.time() - began) * 1000 if began else None,
                        props={"outcome": str(entry.get("kind") or "")[:40]})

    @classmethod
    async def on_questions(cls, questions: list) -> None:
        # Every open question, for the decisions (`decision_sources.RunSource`).
        cls.questions = [dict(q) for q in questions if isinstance(q, dict)]
        desk.poke()
        cls.waiting = {q["id"]: q for q in questions if q.get("id") not in cls.announced}
        await cls.say_waiting()

    @classmethod
    async def say_waiting(cls) -> None:
        for qid, q in list(cls.waiting.items()):
            if conversation_busy():
                return
            call = f" The call: {q['detail']}." if q.get("detail") else ""
            choices = q.get("choices") or {}
            if choices.get("yes") and choices.get("no"):
                # A choice rather than a permission: the words say what a yes does,
                # and a yes may spend the person's money.
                note = (f'[A run in the one program is waiting for the person: "{q.get("text")}"'
                        f"{' What stopped it: ' + q['detail'] + '.' if q.get('detail') else ''} "
                        f"Its question is {qid}. Ask the person in one short sentence: "
                        f'"{choices["yes"]}" or "{choices["no"]}"? When they answer, call '
                        f'one_answer with yes for "{choices["yes"]}" or no for "{choices["no"]}". '
                        "Only with their own answer; never answer it yourself.]")
            else:
                note = (f'[A run in the one program is waiting for the person: "{q.get("text")}"'
                        f"{call} Its question is {qid}. Ask the person in one short sentence "
                        "whether to allow it, and when they answer, call one_answer with their "
                        "answer. Do not answer it yourself.]")
            # In the thread that run was started from, like everything else a
            # run says: a question is the run needing something, and it belongs
            # beside the request that made it.
            if await announce(note, runs.reports_to(str(q.get("run") or ""))):
                cls.announced.add(qid)
                cls.waiting.pop(qid, None)

    @classmethod
    def start(cls, codex_key: str = "") -> None:
        cls.tasks = [
            asyncio.create_task(one.watch(on_tree=cls.on_tree, on_questions=cls.on_questions,
                                          on_runs=cls.on_runs, on_entry=cls.on_entry,
                                          on_hello=cls.on_hello, codex_key=codex_key)),
            asyncio.create_task(cls._again()),
        ]

    @classmethod
    async def _again(cls) -> None:
        """A question that could not be said because someone was talking is tried again."""
        while True:
            await asyncio.sleep(5.0)
            with contextlib.suppress(Exception):
                await cls.say_waiting()

    @classmethod
    async def stop(cls) -> None:
        for task in cls.tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        cls.tasks = []


def conflicts_land_script() -> Path:
    """Where ``land.sh`` is: the setting, or the copy beside this package."""
    return Path(config.land_script or (Path(__file__).resolve().parent.parent / "land.sh"))


def _owner_of(path: str) -> str:
    """The Linux user that owns a checkout, or "" when it cannot be said."""
    try:
        import pwd

        return pwd.getpwuid(os.stat(path).st_uid).pw_name
    except Exception:
        return ""


class ConflictFeed:
    """A job whose work will not go onto main, put in front of the person.

    ``land.sh`` climbs the ladder by itself, merging a clash with Rouh's own
    merge pass when the worker could not, and a record waits on the person only
    when the two sides truly want opposite things (`rouh/conflicts.py`, card
    1684). This watches the directory those records are written to, and when
    one of them is waiting it puts the question in the four places the person
    might be, carrying enough with it that they never have to go back to the
    conversation it came from:

    * **the orb** goes red, dashed and NEEDS YOU, because the record becomes a
      waiting node in the work tree, and clicking that node says which job and
      what the question is
    * **the task list** shows the job's row red, with the one line on it
    * **out loud**, once, when nobody is talking: the line and the four choices,
      and a spoken "take mine" is answered with ``answer_conflict``
    * **Telegram**, for when they are not at the screen at all

    Once means once per conflict, for ever, and not once per start of this
    process: what was said and what was sent is written onto the record itself
    (``said_at``, ``phoned_at``), because what this class remembers is gone at
    every deploy, and on 18 October 2026 Petar was read the same two questions
    again after one. And each is asked of the record as it is on disk at the
    moment it would be said (`conflicts.still_waiting`): a question answered,
    landed or closed since the sweep is not said at all.

    The records are read off disk on every sweep rather than remembered, for the
    same reason the task list is read from the database: they are written by
    other processes, under other users, and they have to survive a restart of
    this one. A record is a file, so a question asked before a deploy is still
    being asked after it.
    """

    #: How often the directory is looked at. A conflict is rare and nobody is
    #: watching the clock for one, and a directory listing of a handful of small
    #: files costs nothing.
    interval = 3.0
    task: asyncio.Task | None = None
    #: What was last sent for each record, so the same question is drawn once.
    shown: dict[str, tuple] = {}
    #: The card each waiting record was drawn as, so the row and the node can
    #: point at it and a second sweep does not draw a second card.
    cards: dict[str, int] = {}
    #: The records said out loud and sent to Telegram, so neither happens twice.
    spoken: set[str] = set()
    phoned: set[str] = set()
    #: Which row on the task list each record is drawn as, and which of those
    #: rows this made up rather than folded onto a job that was already there.
    #: A list only ever adds to what a tab is showing, so a row nothing else
    #: owns has to be named to be taken off one (`tasks_forgotten`).
    row_of: dict[str, str] = {}
    own_rows: set[str] = set()

    @classmethod
    def waiting(cls) -> list[dict]:
        """Every conflict waiting on the person, newest first."""
        try:
            return conflicts.waiting_now(cfg=config)
        except Exception:
            log.exception("could not read the conflict records")
            return []

    @classmethod
    def blocks(cls) -> list[dict]:
        """The decision cards, for a tab that has just opened."""
        out = []
        for record in cls.waiting():
            block = conflicts.conflict_block(record)
            block["card_id"] = cls.cards.get(str(record.get("id")))
            out.append(block)
        return out

    @classmethod
    def rows(cls) -> list[dict]:
        """The task rows for jobs stuck on a conflict, folded into the list."""
        out = []
        for record in cls.waiting():
            row = conflicts.task_row(record)
            row["card_id"] = cls.cards.get(str(record.get("id")))
            out.append(row)
        return out

    @classmethod
    def start(cls) -> None:
        if cls.task is None or cls.task.done():
            cls.task = asyncio.create_task(cls._loop())

    @classmethod
    async def stop(cls) -> None:
        if cls.task is not None:
            cls.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await cls.task
            cls.task = None

    @classmethod
    async def _loop(cls) -> None:
        while True:
            try:
                await asyncio.sleep(cls.interval)
                await cls.sweep()
                # A question that could not be said because somebody was
                # talking, or because no tab was open, is tried again. Nobody
                # is coming to look for it.
                await cls.say_again()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - a sweep must never kill the app
                log.exception("the conflict sweep stumbled; continuing")

    @classmethod
    async def sweep(cls) -> None:
        """Draw what is newly waiting, and take away what has been answered."""
        # The records on disk and the register, read on a thread rather than on the loop.
        waiting, stuck = await asyncio.to_thread(lambda: (cls.waiting(), cls.stuck()))
        now = {str(r.get("id")): r for r in waiting if r.get("id")}
        still: set[str] = set()
        for rid, record in now.items():
            job = str(conflicts.task_row(record)["id"])
            cls.row_of[rid] = job
            still.add(job)
            # The fifth state a run can be in. Its work will not go onto main
            # and only a person can say what happens next, which is a different
            # thing from failing, and the register says so rather than leaving
            # the orb to be the only place it is visible.
            with contextlib.suppress(Exception):
                runs.in_conflict(job, str(record.get("question") or ""))
        changed = False
        # Every run the register still says is stuck on a conflict that no
        # waiting record names. Asked of the register rather than remembered,
        # because what this last saw is gone with every restart and the fifth
        # state is not: a conflict answered while Rouh was down, or answered by
        # `land.sh` in the job's own checkout, left a run saying it needed a
        # person for ever, and nothing was ever going to take it back.
        for job in stuck:
            if job in still:
                continue
            changed = True
            await cls.take_the_row_away(job)
        for rid, record in now.items():
            key = (record.get("state"), record.get("question"))
            if cls.shown.get(rid) == key:
                continue
            cls.shown[rid] = key
            changed = True
            await cls.show(record)
        for rid in [k for k in cls.shown if k not in now]:
            # Answered, parked or landed: the question is over, and the row, the
            # node and the orb have to stop saying it is not.
            cls.shown.pop(rid, None)
            cls.cards.pop(rid, None)
            cls.spoken.discard(rid)
            cls.phoned.discard(rid)
            changed = True
            await cls.take_the_row_away(cls.row_of.pop(rid, ""))
        if changed:
            TreeFeed.poke()
            await _announce_tasks()

    @classmethod
    def stuck(cls) -> list[str]:
        """Every run the register says is stuck on a conflict."""
        try:
            return runs.conflicted()
        except Exception:
            log.exception("could not ask the register which runs are in a conflict")
            return []

    @classmethod
    async def take_the_row_away(cls, row_id: str) -> None:
        """Stop a row saying a question is open once it has been answered.

        Two kinds of row, and they come off in two different ways. A row this
        made up for a job nothing else on this machine knows about is dropped by
        name, because a list only ever adds to what a tab shows. A row that
        belongs to a real job stays, with the question and the red taken off it:
        the job is still on the list, it is only not waiting any more.
        """
        if not row_id:
            return
        # Whatever it was doing before the conflict, it is that again: the
        # register kept the run's own word for where it was all along.
        with contextlib.suppress(Exception):
            runs.out_of_conflict(row_id)
        with contextlib.suppress(Exception):
            if row_id in cls.own_rows:
                cls.own_rows.discard(row_id)
                await Hub.broadcast({"type": "tasks_forgotten", "ids": [row_id]})
            else:
                await Hub.broadcast({"type": "task", "id": row_id, "conflict": "",
                                     "asking": False, "detail": ""})

    @classmethod
    async def show(cls, record: dict) -> None:
        """One waiting conflict, in all four places."""
        rid = str(record.get("id"))
        if record.get("card_id"):
            # Drawn already, before this process started: the card is in its
            # thread, so it is pointed at rather than drawn a second time.
            cls.cards[rid] = int(record["card_id"])
            await cls.reach_out(record)
            return
        spec = conflicts.card(record)
        card_id = None
        # The thread the job was started from, so the question lands where it
        # was asked for, the same as the job's report and its permission
        # questions, and General for a job no thread started (`runs.reports_to`).
        # `to_thread` carries the context across with it, which is how
        # `artifacts.keep` is told which thread it is in.
        chat = runs.reports_to(str(record.get("run") or ""))
        with memory_mod.answering_in(chat), contextlib.suppress(Exception):
            card_id, spec = await asyncio.to_thread(artifacts.keep, memory, spec)
        if card_id is not None:
            cls.cards[rid] = card_id
            with contextlib.suppress(Exception):
                conflicts.set_state(record, record.get("state") or conflicts.WAITING,
                                    cfg=config, card_id=card_id)
            # The button inside the card answers by the card's number, so the
            # block carries it too.
            spec = dict(spec)
            spec["blocks"] = [dict(spec["blocks"][0], card_id=card_id)]
        said = {"type": "ui", "spec": dict(spec, at=time.time())}
        # Drawn on the screens standing in that thread and on no other.
        said["chat"] = chat
        with contextlib.suppress(Exception):
            await Hub.broadcast(said)
        log.warning("a conflict needs the person: %s (%s)", record.get("question"), rid)
        await cls.reach_out(record)

    @classmethod
    async def reach_out(cls, record: dict) -> None:
        """Say it out loud when nobody is talking, and tell the person once: a notice on
        their screen, which goes to the phone if it is left there (`rouh/notices.py`).

        Each only if the record still needs the person this moment, and each
        only once per conflict, which the record itself remembers."""
        rid = str(record.get("id"))
        if rid not in cls.phoned:
            fresh = await asyncio.to_thread(conflicts.still_waiting, rid, cfg=config)
            if fresh is None:
                return
            cls.phoned.add(rid)
            if not fresh.get("phoned_at"):
                with contextlib.suppress(Exception):
                    conflicts.set_state(fresh, fresh.get("state") or conflicts.WAITING,
                                        cfg=config, phoned_at=time.time())
                with contextlib.suppress(Exception):
                    # One decision a file, however many jobs collided in it.
                    number = await asyncio.to_thread(
                        _decision_number, "conflict",
                        "file:" + decision_sources.ConflictSource._file_of(fresh))
                    run = str(fresh.get("run") or "")
                    await notices.phone(
                        conflicts.telegram_text(fresh, number), kind="conflict",
                        key=f"conflict:{rid}",
                        link=(f"/decisions/{number}" if number else f"/run/{run}" if run else ""))
        await cls.say_it(rid)

    @classmethod
    async def say_it(cls, rid: str) -> None:
        """The question out loud, once per conflict, and only while it still waits."""
        if rid in cls.spoken or conversation_busy():
            return
        fresh = await asyncio.to_thread(conflicts.still_waiting, rid, cfg=config)
        if fresh is None:
            return
        if fresh.get("said_at"):
            cls.spoken.add(rid)
            return
        if await announce(conflicts.spoken_note(fresh),
                          runs.reports_to(str(fresh.get("run") or ""))):
            cls.spoken.add(rid)
            with contextlib.suppress(Exception):
                again = conflicts.still_waiting(rid, cfg=config) or fresh
                conflicts.set_state(again, again.get("state") or conflicts.WAITING,
                                    cfg=config, said_at=time.time())

    @classmethod
    async def say_again(cls) -> None:
        """A question nobody could be told about because somebody was talking."""
        for record in cls.waiting():
            rid = str(record.get("id"))
            if rid in cls.spoken or record.get("said_at") or conversation_busy():
                continue
            await cls.say_it(rid)

    @classmethod
    async def answer(cls, conflict_id: str, pick) -> dict:
        """The person picked one of the four, by click, by key or by voice.

        The pick is written onto the record and then sent to the worker that
        wrote the code, which is the only thing that can look at the result in a
        browser before it is pushed. Where that worker is gone, Rouh carries
        the pick out itself and says so: a decision the person has already made
        must not be lost because the job that raised it has stopped.
        """
        record = None
        for found in conflicts.read_all(cfg=config):
            if str(found.get("id")) == str(conflict_id):
                record = found
                break
        if record is None:
            return {"ok": False, "why": "there is no conflict by that name any more"}
        if record.get("state") not in (conflicts.WAITING, conflicts.PARKED):
            # Answered already, here or on the phone or out loud, or the job
            # took it back itself. Said rather than swallowed.
            return {"ok": False, "why": "that one has already been decided"}
        picked = conflicts.choice(pick)
        if picked is None:
            return {"ok": False, "why": f"{pick!r} is not one of the four choices"}
        record = conflicts.answer(record, picked["n"], cfg=config) or record
        note = conflicts.answered_note(record, picked["n"])
        # Two different things, and they must not share a name. The card says
        # which happened, and "it went back to the job" about a job that has
        # stopped would be the one sentence here that is not true.
        told = await cls.tell_the_worker(record, note)
        carried = False
        if not told and picked["how"] in ("mine", "theirs"):
            carried = await cls.carry_it_out(record, picked)
        # After both, and with the record left in `shown`, because the sweep is
        # what takes the row and the red off every screen: popping it here first
        # left the question on the task list with nothing to take it away.
        await cls.sweep()
        # And the row keyed by the conflict rather than by the job, which
        # `answer_conflict` used to make and nothing ever took off again: three
        # of them sat on the task list saying "Resolving the conflict - Take
        # main's, drop mine", owned by nobody, long after the jobs were over.
        # It is not made any more; this takes away the ones that are on a
        # screen already.
        with contextlib.suppress(Exception):
            await Hub.broadcast({"type": "tasks_forgotten", "ids": [str(conflict_id)]})
        if picked["how"] == "park":
            said = ("Nothing moves and nothing is lost: the work stays on its own branch. "
                    "Ask for it again whenever you want to decide.")
        elif told:
            said = ("It has gone back to the job, which resolves it, proves it in the "
                    "browser again and lands it.")
        elif carried:
            said = ("That job has stopped, so it was carried out here and the work is on "
                    "main. Nothing looked at the result in a browser first.")
        else:
            said = ("Nothing here could carry it out: the job has stopped and its "
                    "checkout is gone. Its work is still on its own branch.")
        with contextlib.suppress(Exception):
            await Hub.broadcast({"type": "conflict_done", "id": str(conflict_id),
                                 "choice": picked["n"], "label": picked["label"],
                                 "carried": carried,
                                 "said": f'You chose {picked["n"]}, {picked["label"]}. {said}'})
        return {"ok": True, "choice": picked["n"], "label": picked["label"],
                "sent_to_the_worker": bool(told), "carried_out_here": carried}

    @classmethod
    async def tell_the_worker(cls, record: dict, note: str) -> bool:
        """Send the pick to the job that raised it, whichever kind of job it is."""
        run_id = str(record.get("run") or "")
        if not run_id or not note:
            return False
        if one.configured():
            # A run of the program, said into its own session. The program
            # refuses an id that is not one of its runs, which is how a crew
            # job's id falls through to the crew below rather than being lost.
            try:
                await one.ask("say", run=run_id, text=note)
                log.info("the pick for %s went to run %s", record.get("id"), run_id)
                return True
            except Exception as exc:
                log.info("the one program did not take the pick for %s (%s)",
                         record.get("id"), type(exc).__name__)
        if crew is not None and crew.get(run_id) is not None:
            with contextlib.suppress(Exception):
                await crew.send(run_id, note)
                log.info("the pick for %s went to job %s", record.get("id"), run_id)
                return True
        return False

    @classmethod
    async def carry_it_out(cls, record: dict, picked: dict) -> bool:
        """Do what the person picked, here, because the worker is gone.

        Only for the two picks that are a replay with one side preferred: those
        are the person's decision rather than a change anybody wrote, so there is
        nothing for a worker to reconcile. Nothing is proved in a browser on this
        path and the card says so, because Rouh cannot drive one.

        A decision the person has already made must not be lost because the job
        that raised it has stopped, which is the whole reason this exists. The
        crew's own path is tried first, since it knows which user owns the
        checkout; where there is no job at all, the record's own checkout is
        enough, because ``land.sh`` needs nothing else.
        """
        rid = str(record.get("id") or "")
        mate = crew.get(str(record.get("run") or "")) if crew is not None else None
        if mate is not None:
            try:
                got = await crew.run_land_script(mate, answer=str(picked["n"]), conflict=rid)
                log.info("carried out %s for %s: %s", picked["n"], rid, got.get("reason"))
                return bool(got.get("landed"))
            except Exception:
                log.exception("could not carry out the pick for %s through the crew", rid)
                return False
        cwd = str(record.get("cwd") or "")
        script = str(record.get("land") or "") or str(conflicts_land_script())
        if not cwd or not os.path.isdir(cwd) or not os.path.isfile(script):
            log.warning("nothing here can carry out the pick for %s", rid)
            return False
        argv = ["bash", script, "--path", cwd, "--answer", str(picked["n"]),
                "--conflict", rid, "--land-dir", str(conflicts.land_dir(config)), "--quiet"]
        owner = _owner_of(cwd)
        if owner and hasattr(os, "geteuid") and os.geteuid() == 0:
            # The checkout is somebody else's and git refuses another user's
            # ("dubious ownership"), and the key that may push is theirs.
            argv = ["runuser", "-u", owner, "--", "env",
                    f"HOME={os.path.expanduser(f'~{owner}')}", *argv]
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), 1900.0)
        except Exception:
            log.exception("could not carry out the pick for %s", rid)
            return False
        said = [line for line in out.decode("utf-8", "replace").splitlines() if line.strip()]
        try:
            got = json.loads(said[-1]) if said else {}
        except ValueError:
            got = {}
        log.info("carried out %s for %s: %s", picked["n"], rid,
                 got.get("reason") or err.decode("utf-8", "replace")[-200:])
        return bool(got.get("landed"))


class TreeFeed:
    """Pushes the tree to every open tab as soon as something in it changes.

    Everything the tree is built from pokes it when it changes: a worker's
    hook, a job being created, stopped or found dead, one of Rouh's own tool
    calls starting or ending, Rouh starting or stopping work. A poke wakes
    the loop, which gathers for a moment - tool calls fire in bursts of tens a
    second, and a burst should be one message, not one each - then builds the
    tree and sends it if it differs from the last one sent. A change reaches
    the page in about a tenth of a second.

    It used to be a beat, building the tree twice a second whether or not
    anything had changed, so a job stopped just after one beat waited for the
    next. A slow beat is kept for the changes no event announces: a finished
    node leaving the tree a moment after it closed, or a node closed because it
    has been open far too long. Nothing is sent while no tab is open.
    """

    #: How long to gather further changes after the first poke, in seconds.
    gather = 0.06
    #: The beat, for changes with no event behind them.
    interval = 1.0
    last: dict | None = None
    task: asyncio.Task | None = None
    _wake: asyncio.Event | None = None
    _home: asyncio.AbstractEventLoop | None = None

    @classmethod
    def poke(cls) -> None:
        """Something the tree is built from has changed. Safe from any thread."""
        wake, home = cls._wake, cls._home
        if wake is None or home is None or home.is_closed():
            return
        try:
            here = asyncio.get_running_loop()
        except RuntimeError:
            here = None
        if here is home:
            wake.set()
        else:
            with contextlib.suppress(RuntimeError):
                home.call_soon_threadsafe(wake.set)

    @classmethod
    def start(cls) -> None:
        if cls.task is None or cls.task.done():
            cls._home = asyncio.get_running_loop()
            cls._wake = asyncio.Event()
            cls.task = asyncio.create_task(cls._loop())

    @classmethod
    async def stop(cls) -> None:
        if cls.task is not None:
            cls.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await cls.task
            cls.task = None
        cls._wake = None
        cls._home = None

    @classmethod
    async def _loop(cls) -> None:
        wake = cls._wake
        while True:
            try:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(wake.wait(), timeout=cls.interval)
                if wake.is_set():
                    await asyncio.sleep(cls.gather)
                    wake.clear()
                await cls.push()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - the feed must never kill the app
                log.exception("the work tree feed stumbled; continuing")

    @classmethod
    async def push(cls) -> None:
        """Send the tree to every open tab, if it differs from the last one sent."""
        if not Hub.sockets:
            # Nobody is looking. Forget what was last sent so the next tab to
            # open is pushed a tree rather than waiting for the next change.
            cls.last = None
            return
        # On a thread: it reads the run register, and on the loop it held every
        # tab - and the answer being streamed to it - several times a second
        # while anything was running, Rouh's own turn included (23 October 2026).
        tree = await asyncio.to_thread(tree_snapshot)
        if tree == cls.last:
            return
        cls.last = tree
        await Hub.broadcast({"type": "tree", "tree": tree, "now": time.time()})



class OwnWork:
    """What Rouh itself is doing, as tree events.

    The work tree is built from Claude Code hooks, and those only exist inside a
    delegated worker. Rouh's own turn - thinking, searching the web, running
    code, putting something on screen - fires no hooks at all, so none of it
    reached the tree and asking for a search changed nothing on screen.

    Every `tool_start` and `tool_end` the turn already emits to the browser is
    recorded here on the way past, in the shape `tree.build_tree` reads. One
    interception point rather than a second reporting path.
    """

    _events: list[dict] = []
    state: str | None = None
    LIMIT = 400

    @classmethod
    def note(cls, message: dict) -> None:
        kind = message.get("type")
        if message.get("where") != "rouh":
            return
        if kind == "tool_start":
            payload = {"tool_use_id": message.get("id"), "tool_name": message.get("name")}
            # What the call is doing, in words, written where it started. Only
            # these words are kept for the orb, never the call's input.
            for key in ("what", "detail"):
                if message.get(key):
                    payload[key] = message[key]
            # A call made inside one of Rouh's own subagents says which one,
            # and the tree hangs it off that branch rather than off the core.
            if message.get("agent_id"):
                payload["agent_id"] = message["agent_id"]
            cls._events.append({"kind": "PreToolUse", "at": time.time(), "payload": payload})
        elif kind == "tool_update":
            # Anthropic's own tools start before their input has streamed in,
            # so a web search is first only "Searching the web" and learns its
            # query a moment later.
            cls._events.append({
                "kind": "ToolUpdate", "at": time.time(),
                "payload": {"tool_use_id": message.get("id"),
                            "tool_name": message.get("name"),
                            "what": message.get("what"),
                            "detail": message.get("detail")},
            })
        elif kind == "tool_end":
            payload = {"tool_use_id": message.get("id"),
                       "tool_name": message.get("name"),
                       "is_error": not message.get("ok", True)}
            if message.get("agent_id"):
                payload["agent_id"] = message["agent_id"]
            cls._events.append({"kind": "PostToolUse", "at": time.time(), "payload": payload})
        elif kind in ("permission_ask", "permission_done"):
            # A tool call stopped to ask the person something. On the orb that
            # is the same thing a worker asking is: the node goes red and
            # dashed and says NEEDS YOU, which is the one state on the orb
            # that must never be left alone. Drawn on the call's own node
            # rather than as a node of its own, because it is that call that
            # is waiting.
            if not message.get("call_id"):
                return
            cls._events.append({
                "kind": "ToolWaiting", "at": time.time(),
                "payload": {"tool_use_id": message.get("call_id"),
                            "waiting": kind == "permission_ask",
                            "what": message.get("question") or ""},
            })
        elif kind in ("subagent_start", "subagent_end"):
            # Rouh's own subagent (rouh/subagent.py), said in the shape the
            # tree already reads for a worker's sub-agents, so it draws as a
            # branch with its own tool calls on it.
            payload = {"agent_id": message.get("id")}
            if message.get("label"):
                payload["agent_type"] = message["label"]
            cls._events.append({
                "kind": "SubagentStart" if kind == "subagent_start" else "SubagentStop",
                "at": time.time(), "payload": payload,
            })
        else:
            return
        if len(cls._events) > cls.LIMIT:
            del cls._events[: len(cls._events) - cls.LIMIT]
        # The page should see it now, not on the next beat.
        TreeFeed.poke()

    @classmethod
    def events(cls, *, window: float = 300.0) -> list[dict]:
        cutoff = time.time() - window
        return [e for e in cls._events if e["at"] >= cutoff]


class Hub:
    """Every open tab, so a background job can announce itself to all of them."""

    sockets: set["Session"] = set()

    @classmethod
    async def broadcast(cls, message: dict) -> None:
        for s in list(cls.sockets):
            with contextlib.suppress(Exception):
                await s.emit(message)

    @classmethod
    async def mirror(cls, origin: "Session | None", role: str, text: str,
                     files: list[dict] | None = None, *, chat: str = "",
                     steer: str = "") -> None:
        """Put what the person said on one device onto the others' screens.

        A sentence said on the phone is part of the thread the desktop is
        looking at and belongs on it now rather than after a reload. The tab it
        was said in has already drawn it and is skipped, or the person sees
        their own words twice, and so is a tab looking at another thread.

        A message from Telegram was said on no tab at all: `origin` is None,
        `chat` says which thread, and every tab standing in it draws it.

        A tab whose strip of forks has that thread on it is told too, the way
        it is told the answer (`Turn.tabs`), and keeps it for when the thread
        is slid into view: a fork made from the phone is laid beside General,
        and its first question belongs above its answer there.

        Only what the person says travels this way. What Rouh says goes to
        every tab in the thread as it is written, by the turn that is writing
        it (`Turn.emit`), because the turn is the one thing that knows which
        thread the answer belongs to.
        """
        text = (text or "").strip()
        if not text and not files:
            return
        row = {"type": "transcript_add", "role": role, "text": text,
               "ts": time.time()}
        if origin is None:
            # Said from the phone, not on any screen: in demo mode it is not drawn (`rouh/demo.py`).
            row["from_phone"] = True
        if files:
            row["attachments"] = files
        # Sent while an answer is being written, and waiting for the model to
        # read it (`Session.typed`): drawn waiting, under that name.
        if steer:
            row["steer"] = steer
        row["chat"] = chat or (origin.session_id if origin is not None else "")
        if not row["chat"]:
            return
        for other in list(cls.sockets):
            # A socket that has not said hello yet is skipped: its page is
            # about to be handed the whole transcript, and a turn drawn before
            # that arrives is taken for a live one, which makes the page think
            # it has already drawn the history and leaves it showing one line.
            # So is one looking at another thread: this was said in a
            # conversation that is not the one on its screen.
            if other is origin or other.closed or not other.session_id:
                continue
            if other.session_id != row["chat"] and row["chat"] not in other.beside:
                continue
            await other.emit(row)


def chat_snapshot(active: str | None = None, tip: str = "") -> dict:
    """Every chat, every folder, and which chat is the active one.

    `active` is the chat of the tab it is for. Each tab is in a chat of its
    own (`switch_chat`), so the one the list marks open is that tab's; left
    out, it is the chat the person opened last, anywhere. `tip` is the far
    end of that tab's strip of forks (`forks.strip`), which is the tab's too.

    One message rather than three, because the page draws them as one thing:
    the folders with their chats nested under them, and the unfiled chats
    below. Sending them apart means the middle column can be drawn from half
    an answer, with a chat in a folder that has not arrived yet.

    Reads every chat, so it is built on a thread, never on the loop.
    """
    head = conversation_snapshot(active, tip)
    # Every chat has an owner or is an orphan, and an orphan is the default.
    # Read off the one link table rather than guessed from the folder: a chat
    # can be a project's or a task's, and being a task's is what takes it out
    # of a project (`rouh/owning.py`).
    return {
        "chats": owning.decorate(memory.chats(), "chat"),
        "folders": memory.folders(),
        **head,
    }


def conversation_snapshot(active: str | None = None, tip: str = "") -> dict:
    """The part of `chat_snapshot` about the one chat a tab is in, without the lists.

    What the handshake needs to draw the conversation, and nothing that reads
    every chat: which chat it is, its row (`chat`, for its head, until the
    whole list arrives a moment later), the draft it may be, General's id, the
    chats being answered and its forks. Since 23 October 2026 the handshake is
    this and the transcript, and the lists follow it as messages of their own
    (`Session.after_ready`): until then the page waited for all of it at once,
    714 KB built one piece after another, before it showed a single message.
    """
    # The thread that is always there, made if it is not there yet. Asked for
    # here rather than at start-up because this is the one place every tab goes
    # through: a database restored from a backup, or one a test made a second
    # ago, has a General in it by the time anybody can see the rail.
    memory.ensure_general()
    if not active or not chat_is_there(active):
        active = memory.active_chat()
    row = memory.chat(active)
    if row is not None and not row.get("draft"):
        row = (owning.decorate([row], "chat") or [row])[0]
    return {
        "active_chat": active,
        "chat": row,
        # The conversation the person is in when it is not written down yet: a
        # task opened and not talked about, or New chat with nothing said. It
        # is in none of the lists, because it is not a chat; the page keeps it
        # beside them so the head of the conversation can still say whose it
        # is. Null when the active chat is a real one.
        "draft": conversations.draft_row(active),
        "general": memory_mod.CONVERSATION,
        # Which threads are being answered this instant. A turn belongs to the
        # thread it was asked in and goes on there after the person has opened
        # another one, so the rail is where they can see that it is still
        # talking (`Turn`). A thread they are not in that has finished
        # something carries `unread` on its own row instead.
        "answering": _answering(),
        # The forks: the chats laid out beside this one, and the ones marked
        # in its conversation (`fork_snapshot`).
        "forks": fork_snapshot(active, tip),
    }


def _answering() -> list[str]:
    """`Turns.running`, sorted, read safely from a thread while the loop may be changing it."""
    for _ in range(5):
        try:
            return sorted(Turns.running)
        except RuntimeError:  # it changed size while it was read
            continue
    return []


#: How many rows of a conversation the page is sent at a time: the last ones with the
#: handshake and each switch, and each page before them as it is scrolled up to.
TRANSCRIPT_PAGE = 40

#: Seconds the lists after a handshake may take before the log says which was slow (`after_ready`).
SLOW_LISTS = 2.0

#: How much of each chat on a strip the page is handed to draw it with beside
#: the one being talked in: the last things said, each cut short. At a desk it
#: is a sliver's worth; on a phone it is the whole card a finger slides into
#: view, which has to read as the chat itself (`forkPane` in app.js).
PEEK_TURNS = 10
PEEK_CHARS = 1200


def fork_snapshot(active: str, tip: str = "") -> dict:
    """The forks, as the page lays them out around the chat the person is in.

    `strip` is every chat laid out left to right with this one among them -
    the chat it all started in, then each fork down to the tab's `tip` - with
    the last few things said in each, which is what the slivers either side of
    the conversation are drawn from. Empty when there is nothing beside this
    chat, which is nearly always. `marks` is every fork this chat has had,
    open or closed, and the message each came off after: the lines its
    conversation carries at those points, which open them again
    (`rouh/forks.py`). `bare` is whether it may be forked before anything
    is said in it (`forks.bare`), which is when the page shows Fork in a chat
    with nothing in it.
    """
    # Sent with every list of the chats, so the question "is this a chat" is
    # asked of its row alone: a draft has none, and nothing hangs off a draft.
    # The draft of a task's chat may still be forked from its first message,
    # which makes it a chat with nothing in it (`forks.bare`, `forks.make`).
    if not active or conversations.store().get_chat(active) is None:
        return {"strip": [], "marks": [], "bare": bool(active) and forks.bare(active)}
    laid = forks.strip(active, tip)
    strip = []
    if len(laid) > 1:
        for chat_id in laid:
            row = memory.chat(chat_id)
            if row is None:
                continue
            said = [{"role": t.get("role"), "text": (t.get("text") or "")[:PEEK_CHARS]}
                    for t in memory.transcript(chat_id, PEEK_TURNS * 2)
                    if (t.get("text") or "").strip()][-PEEK_TURNS:]
            strip.append({"id": chat_id, "title": row.get("title") or "",
                          "titled": bool(row.get("titled")),
                          "messages": int(row.get("messages") or 0),
                          "unread": bool(row.get("unread")),
                          "fork_of": row.get("fork_of") or "",
                          "said": said})
    return {"strip": strip if len(strip) > 1 else [], "marks": forks.children(active),
            "bare": forks.bare(active)}


def objects_snapshot() -> dict:
    """The tasks and the projects, and what a new run may be started with.

    The other half of `chat_snapshot`: the chats are there, and the things a
    chat, a run or an artifact can belong to are here. One message, because the
    page draws the owner dialog from all of it at once and half of it is not a
    picture of anything.
    """
    return owning.snapshot()


async def _announce_workspace() -> None:
    with contextlib.suppress(Exception):
        await Hub.broadcast({"type": "workspace",
                             "tasks": await asyncio.to_thread(workspace_tasks)})


async def announce_objects() -> None:
    """Tell every tab that a task, a project or an owner has changed.

    Broadcast, like the chats: there is one set of objects and one owner for
    each, so a run attached on the phone is under that task on the desktop.
    """
    # On a thread: it reads every task and project, which held the loop, and
    # with it the turn that made a new chat, for about 250 ms (5 October 2026).
    await Hub.broadcast(dict(await asyncio.to_thread(objects_snapshot), type="objects"))
    # A task's file taken in may have asked something, or stopped asking.
    desk.poke()


async def announce_task_chat() -> None:
    """A chat has just become a task's (`conversations.adopt_made_task`): the
    lists, the tasks and the strip of forks it left are drawn again on every tab."""
    await announce_chats()
    await _announce_workspace()
    await announce_objects()


async def open_thread(tab: "Session", chat_id: str = "", task: str = "", *,
                      alone: bool = False, redraw: bool = False) -> str:
    """Open a thread, by its own id or by the workspace task it is.

    Picking the thread is picking the task, so this is also how a task is
    opened from the index: name the task, and the conversation that task owns
    is opened in the tab that asked. Where it does not have one yet, a draft
    of one is opened instead - its id and its title, "19 Pricing", and no row - and the
    chat is written the moment something is said in it (`Turns.start`).
    Opening a task and saying nothing leaves nothing behind.

    Which conversation a task owns is a row in the link table and not a name
    that happens to match: see `rouh/conversations.py`.

    `alone` opens the chat with no fork beside it in this tab: its strip ends
    at the chat (`forks.strip`). That is Rouh in the navigation, which is the
    main conversation and nothing else (fr_5c306c1cf386). A tab already in
    the chat is not switched into it again, which would read it back for
    nothing; it is only sent its strip, now empty.

    Unless the page says it has none of it on screen (`redraw`): a page at
    the front door is in no chat, while its tab is still held in the chat it
    was in, and Rouh pressed there was answered with nothing at all
    (fr_5fcd2acebed7).
    """
    task = (task or "").strip().strip("/")
    if chat_id and alone:
        if tab.session_id == chat_id and not redraw:
            if tab.tip != chat_id:
                tab.tip = chat_id
                await tell_chats(tab)
            return chat_id
        return await switch_chat(chat_id, tab, tip=chat_id)
    if chat_id:
        return await switch_chat(chat_id, tab)
    if not task:
        return tab.session_id
    row = await asyncio.to_thread(conversations.open_for_task, task)
    if row is None:
        log.warning("there is no task %s to open a thread for", task)
        return tab.session_id
    return await switch_chat(row["id"], tab)


async def start_task_chat(tab: "Session", task: str) -> str:
    """Start chat, on a task's or a step's own page: a new conversation about it.

    Always an empty one, and never the task's conversation with something in
    it: that is what "start" says (`conversations.start_for_task`). A draft,
    like every chat before its first word, opened in the tab that asked.
    """
    drafted = await asyncio.to_thread(conversations.start_for_task, task)
    if drafted is None:
        log.warning("there is no task %s to start a chat about", task)
        return tab.session_id
    return await switch_chat(drafted, tab)


async def answer_task_chat(tab: "Session", task: str) -> tuple[str, bool]:
    """The question box on a task's page, answered: the chat the answer goes
    into, opened in the tab that asked, and whether that moved it.

    The chat the task already has, and a new one only when it has none
    (`conversations.answer_for_task`). ("", False) when there is no such
    task. Already the tab's own, nothing is switched: the tab is in it,
    and a switch would stop the voice and draw the conversation again for
    nothing, so the tab that asked is told instead (`answer_chat`).
    """
    chosen = await asyncio.to_thread(conversations.answer_for_task, task)
    if not chosen:
        log.warning("there is no task %s to answer", task)
        return "", False
    if chosen == tab.session_id:
        return chosen, False
    await switch_chat(chosen, tab)
    return chosen, True


async def promote_thread(chat_id: str) -> dict | None:
    """Make a loose conversation a numbered task, and tell every tab.

    The person saying "this one is work". It takes the next free number, keeps
    every message - it is the same conversation, nothing is copied - and the
    folder for it is written into the workspace from the row that was just
    made, which is the only direction anything is ever written.
    """
    made = await asyncio.to_thread(
        lambda: conversations.promote(chat_id, why="asked for it"))
    if made is None:
        return None
    await announce_chats()
    # And the task itself, in both the messages that carry one: the workspace
    # list the canvas names a task from, and the objects the rail's Tasks list,
    # the owner dialog and the run's "where this belongs" are drawn from.
    await _announce_workspace()
    await announce_objects()
    # Cleared here, so it is not announced twice - and it is also the answer
    # to "did this press make a task": a chat that was already one is handed
    # back its own, and nothing about it is new. Only a task that was just
    # made files itself (`NewTasks`).
    NewTasks.maybe_file(conversations.promotion_to_announce())
    return made


async def file_card_as_step(card) -> dict | None:
    """Write one card into the task that owns it, and tell every tab.

    The press on a card's own button, which is one of the three ways the
    person asks for numbered work and the only one that is about a single
    card. Nothing files a card by itself since 22 September 2026, so this is
    the whole of how a card reaches the workspace from the page
    (`rouh/artifacts.py`).

    The card comes back whatever happened, so the caller can draw it again
    with the number it was given; `filed_into` is empty when there was nowhere
    to put it.
    """
    got = await asyncio.to_thread(artifacts.file_as_step, card,
                                  root=config.assistant_repo)
    if got is not None and got.get("filed_into"):
        # A step is a task of its own, so both lists that draw the workspace
        # have something new in them.
        await _announce_workspace()
        await announce_objects()
    return got


async def announce_chats() -> None:
    """Tell every tab that the list of chats has changed.

    Broadcast rather than answered to whoever asked, because a chat renamed on
    the phone is renamed on the desktop: there is one set of chats. Which of
    them is open is each tab's own, though (`switch_chat`), so every tab is
    sent the list marked with its own chat, and the strip of forks around it,
    which is the tab's own as well (`Session.tip`).
    """
    tabs = open_tabs()
    asked = [(tab.session_id, tab.tip) for tab in tabs]
    # Where each tab was when its lists were worked out. They are built on a
    # thread, and a tab that moves meanwhile - a fork closed, a chat opened -
    # is sent them stamped as they were (`asked`), which the page passes over,
    # and keeps the strip its move gave it here (23 October 2026: a list
    # worked out before a close laid the fork out again after it).
    marks = [tab_mark(tab) for tab in tabs]

    # On a thread, all of it: every chat, and each strip of forks a tab lays
    # out. On the loop it held every socket still while it was read, after
    # every turn and every switch (23 October 2026).
    def built() -> tuple[dict, list[tuple[str, str]]]:
        base = chat_snapshot()
        mine: dict[tuple[str, str], dict] = {(base["active_chat"], ""): base}
        keys = []
        for session_id, tip in asked:
            chat = session_id or base["active_chat"]
            if not chat_is_there(chat):
                chat = base["active_chat"]
            key = (chat, tip if chat == session_id else "")
            if key not in mine:
                mine[key] = dict(base, active_chat=chat,
                                 draft=conversations.draft_row(chat),
                                 forks=fork_snapshot(*key))
            keys.append(key)
        return mine, keys

    mine, keys = await asyncio.to_thread(built)
    for tab, key, mark in zip(tabs, keys, marks):
        snapshot = mine[key]
        # The strip can change without a switch - a fork detached or made a
        # task's chat - and whose turns each tab is shown changes with it.
        if tab_mark(tab) == mark:
            tab.beside = strip_ids(snapshot["forks"])
        with contextlib.suppress(Exception):
            await tab.emit(dict(snapshot, type="chats", asked=mark[2]))


async def announce_model_defaults() -> None:
    """Tell every tab the models have changed: a tab showing the Models page
    reads it again (`model_defaults`), and so does the This page side, which
    names Ask AI's model."""
    await Hub.broadcast({"type": "model_defaults"})


def chat_is_there(chat_id: str) -> bool:
    """Whether a tab can be in this chat: a real one, or a draft of one."""
    return bool(chat_id) and (conversations.chat(chat_id) is not None
                              or conversations.draft(chat_id) is not None)


def open_tabs() -> list["Session"]:
    return [tab for tab in list(Hub.sockets) if not tab.closed]


def chat_peek(chat_id: str, beside) -> dict | None:
    """One chat of a tab's strip of forks as that tab will read it back on sliding onto it.

    The very transcript and marks `switch_chat` would send, for a chat the
    page only shows beside the one it is in: the card it draws there is
    otherwise the last few things said, in words only, and the conversation
    read back in its place a moment after the slide - tool lines, the lines
    under each message, its own forks' marks - was the refresh Petar saw
    after the snap (fr_60918f90d0bb). Only a chat on the strip the tab is
    standing beside, which is the only chat it has any card of.
    """
    if not chat_id or chat_id not in (beside or ()):
        return None
    row = memory.chat(chat_id)
    if row is None:
        return None
    return {"type": "chat_peek", "id": chat_id,
            "messages": int(row.get("messages") or 0),
            "transcript": memory.transcript(chat_id, 40),
            "marks": forks.children(chat_id)}


def strip_ids(laid: dict) -> frozenset[str]:
    """The chats of a strip, from what `fork_snapshot` said of it."""
    return frozenset(c["id"] for c in (laid or {}).get("strip") or [] if c.get("id"))


async def tell_chats(tab: "Session") -> None:
    """The lists and this tab's own strip, to this tab alone: its strip
    changed and nothing else did, so no other tab has anything to redraw."""
    mark = tab_mark(tab)
    snapshot = await asyncio.to_thread(chat_snapshot, tab.session_id, tab.tip)
    if tab_mark(tab) == mark:
        tab.beside = strip_ids(snapshot["forks"])
    with contextlib.suppress(Exception):
        await tab.emit(dict(snapshot, type="chats", asked=mark[2]))


def tab_mark(tab: "Session") -> tuple[str, str, int]:
    """Where a tab is: its chat, the end of its strip, and its newest `ask`."""
    return tab.session_id, tab.tip, tab.asked


def tip_after(tab: "Session", chat_id: str, tip: str | None) -> str:
    """The end of the strip a tab moving into `chat_id` lays out.

    The one it was asked for, when it was (a fork just made, its address, the
    page connecting again). Otherwise its strip as it was, when the chat is
    on it, which is sliding along it; and the chat alone when it is not,
    which is opening another conversation."""
    if tip is not None:
        return forks.tip_for(chat_id, tip)
    if tab.session_id and chat_id in forks.strip(tab.session_id, tab.tip):
        return forks.tip_for(chat_id, tab.tip)
    return chat_id


async def switch_chat(chat_id: str, tabs, tip: str | None = None, *,
                      redraw: bool = False, focus: int | None = None) -> str:
    """Put one chat on the screen of the tabs that asked for it, and no other.

    `tabs` is a tab, or the tabs, being moved: nearly always the one the
    press was made in. Until 29 September 2026 every open tab moved with it,
    on the grounds that the person is one person. Petar asked for the
    opposite (fr_349273a9377e): "I want to have different tabs doing different
    things for comparison purposes and multitasking". So a tab's chat is its
    own, and two tabs are two conversations side by side. The chat opened
    last, in any tab, is still written down as the active one, which is what
    a tab that names no chat of its own opens on.

    A chat that is not there, and is not a draft of one, moves nobody: a
    stale button in a tab that has been open for a day must not be able to
    move it into a conversation that does not exist.

    Each tab is handed that chat's transcript rather than being told to reload:
    what is on the screen is the conversation, and a page that had to be
    reloaded to catch up would lose whatever was half typed in the box.

    **Nothing is cancelled here.** A turn belongs to the thread it was asked
    in and goes on to the end there whatever the screen moves to, and what it
    writes is in that thread when the person comes back (`Turn`).

    **Nor is any other tab's strip touched.** Each tab moved gets the strip
    of forks it is to lay out (`tip_after`), and no other tab hears of it
    beyond the lists. Until 22 October 2026 opening a fork marked it open in
    the database for every tab, so a fork closed on one screen came back by
    itself when another screen opened it (task 62, step 62-23).

    `redraw` is the chat already on those tabs drawn again from the top, which is
    how a branch of its conversation is put on the screen (`branch_redraw`), and
    `focus` the exchange the page scrolls back to once it has.
    """
    if isinstance(tabs, Session):
        tabs = [tabs]
    tabs = [tab for tab in (tabs or []) if not tab.closed]

    # The reading, on a thread: on the loop it held every socket still for as
    # long as General's forks took to read (23 October 2026). Whether it had
    # an unread mark is read before opening it takes the mark off.
    def opened() -> tuple[str, dict, list, str, bool] | None:
        if not chat_is_there(chat_id):
            return None
        unread = bool((memory.chat(chat_id) or {}).get("unread"))
        active = memory.set_active_chat(chat_id)
        transcript, older = memory.transcript_page(active, TRANSCRIPT_PAGE)
        return active, memory.chat(active) or {"id": active}, transcript, older, unread

    got = await asyncio.to_thread(opened)
    if got is None:
        return tabs[0].session_id if tabs else await asyncio.to_thread(memory.active_chat)
    active, row, transcript, older, was_unread = got
    # A turn already running in the chat being opened, so a page that walks
    # back into one shows it still running, with what it has written so far,
    # and goes on receiving the rest of it live.
    turn = Turns.of(active)
    running = turn.picture() if turn is not None else None
    strips: dict[str, dict] = {}
    for tab in tabs:
        tab.tip = await asyncio.to_thread(tip_after, tab, active, tip)
        if tab.tip not in strips:
            strips[tab.tip] = await asyncio.to_thread(fork_snapshot, active, tab.tip)
        laid = strips[tab.tip]
        tab.session_id = active
        # In the same breath, before anything can be sent: a turn in the chat
        # being left goes on reaching this tab while it is on the same strip.
        tab.beside = strip_ids(laid)
        # Words said into the chat being left are not a question asked in the
        # one being opened, and neither is the clock that was going to answer
        # them (`Session.not_finished_yet`).
        tab.stop_waiting()
        tab.pending.clear()
        with contextlib.suppress(Exception):
            said = {"type": "chat_switched", "chat": row,
                    "transcript": transcript, "older": older, "running": running,
                    "forks": laid, "asked": tab.asked}
            if redraw:
                said["redraw"] = True
                if focus:
                    said["focus"] = int(focus)
            await tab.emit(said)
    # The lists, to every tab, only when opening the chat changed them: its
    # unread dot went. The tab that moved has its chat and its strip in the
    # switch itself, and every other tab's lists are as they were. Until 23
    # October 2026 every move along a strip of forks sent the whole list of
    # chats to every tab, and each tab drew it all again.
    if was_unread:
        await announce_chats()
    return active


async def branch_redraw(chat_id: str, root: int, changed) -> None:
    """Put the branch of a chat's conversation that is being read on every tab in it.

    `changed` is the tries that came on or off the screen (`memory.pick_version`,
    `memory.took_branch`). When any of them is outside the exchange `root`, what
    follows it is another conversation now, so the chat is drawn again from the top,
    canvas and all, and the page goes back to the exchange. When only that exchange
    changed, the page already has it, and only the cards a try of it revised are
    drawn again as this branch has them (`artifacts.on_branch`).
    """
    changed = set(changed or ())
    if not changed:
        return
    tabs = [tab for tab in open_tabs() if tab.session_id == chat_id and not tab.closed]
    if any(key[0] != int(root) for key in changed):
        if tabs:
            await switch_chat(chat_id, tabs, tip=None, redraw=True, focus=int(root))
        return
    if not artifacts.enabled():
        return
    firsts = await asyncio.to_thread(memory.tries_of, chat_id, changed)
    specs = await asyncio.to_thread(artifacts.made_in_any, firsts, chat_id)
    for spec in specs:
        for tab in tabs:
            with contextlib.suppress(Exception):
                await tab.send({"type": "ui", "spec": spec, "in_place": True})


async def close_fork(chat_id: str, tab: "Session") -> None:
    """Take a fork off this tab's strip, and put the tab back where it came off.

    The cross in the corner of a fork, and the person saying they are done
    with it: "I want to fully return to the main chat or thread". Every fork
    below it goes with it, because the strip now ends at the chat it came
    off. Nothing is deleted; the mark in the parent's conversation opens it
    again. A tab in the fork, or in a fork of it, moves to the chat it came
    off; a tab beside it is only sent its strip again.

    This tab and no other. The phone, the Mac and a second tab each keep
    their own strip: one that is in the fork stays in it, and a fork closed
    here is never laid out again here by anything they do.
    """
    parent = forks.close(chat_id)
    if not parent or chat_id not in forks.strip(tab.session_id, tab.tip):
        await tell_chats(tab)
        return
    if chat_id in forks.lineage(tab.session_id):
        await switch_chat(parent, tab, tip=parent)
        return
    tab.tip = parent
    await tell_chats(tab)


async def detach_fork(chat_id: str, task_id: str, emit) -> None:
    """Make a fork a chat of the task the person picked, and lay out every
    tab again.

    The tab that asked is answered as a move, because it is one: `attached`,
    the answer `attach` gives, so it says where the chat went (`movedTell`)
    or why it would not. It is sent before the lists, as `attach` sends it,
    because the page reads where the chat was out of the lists it still has.

    The unlinked chain on a fork's card, "Detach from parent chat", which
    since 6 October 2026 opens a picker of tasks first: a fork is detached
    into a task or not at all, so no chat is left loose
    (`owning.detach_fork_into`). Nobody is moved: a tab in the fork stays in
    it, now that task's chat with its own forks still beside it, and a tab in
    the chat it came off sees it gone from beside that chat and its mark
    saying it was detached. Every tab is sent the lists again, which the
    detached chat is in from now on, under its task.
    """
    got = await asyncio.to_thread(owning.detach_fork_into, chat_id, task_id)
    await emit(dict(got, type="attached", kind="chat", id=chat_id))
    if not got.get("ok"):
        return
    log.info("fork %s is detached into task %s", chat_id, task_id)
    await announce_objects()
    await announce_chats()
    await Hub.broadcast({"type": "tasks", "tasks": await task_list()})


class ChatNames:
    """A chat named from its own first exchange, in the background.

    It runs after a turn rather than during one. Naming is a nicety and the
    answer is not: a title that takes three seconds to write must never be
    three seconds the person spends waiting to be spoken to, and a naming that
    fails outright must leave the turn it followed untouched.

    A chat is named once. `titled` is what says whether it has been, so a title
    the person typed themselves is never written over, nor one Rouh gave it
    because they asked (`rename_this_chat`), and a chat whose naming
    failed is tried again after the next turn - which is what "still untitled
    after a couple of turns" means in practice. Nothing retries inside one
    attempt: if the model is down, the next turn is soon enough.
    """

    #: Chats being named this instant, so two turns finishing together do not
    #: ask for the same title twice.
    working: set[str] = set()

    @classmethod
    def maybe_name(cls, chat_id: str) -> None:
        """Name this chat if it still needs one. Returns at once."""
        if not chat_id or chat_id in cls.working:
            return
        row = memory.chat(chat_id)
        if row is None or row["titled"] or row["messages"] < 2:
            return
        cls.working.add(chat_id)
        try:
            task = asyncio.ensure_future(cls._name(chat_id))
        except RuntimeError:                       # no loop: nothing to name on
            cls.working.discard(chat_id)
            return
        task.add_done_callback(lambda _t: cls.working.discard(chat_id))

    @classmethod
    async def _name(cls, chat_id: str) -> None:
        try:
            # How the chat began, and not how it is going: the newest rows of
            # a turn that called a few tools are tool calls with no words in
            # them, which named nothing, and a later quiet exchange then named
            # the chat after itself (`conversations.opening`).
            exchange = await asyncio.to_thread(
                lambda: chatnames.exchange_text(
                    conversations.opening(chat_id, chatnames.TURNS)))
            if not exchange:
                return
            title = await chatnames.suggest(exchange, memory_mod.MAX_TITLE, session_id=chat_id)
            if not title:
                return
            # Checked again here rather than only above: the person may have
            # typed a name of their own while the model was writing one, and
            # what they typed wins.
            row = memory.chat(chat_id)
            if row is None or row["titled"]:
                return
            memory.rename_chat(chat_id, title)
            log.info("named chat %s %r", chat_id, title)
            # A chat made a task before it had a name made an "Untitled task",
            # and the name it has now is the task's too.
            if await asyncio.to_thread(conversations.name_untitled_task, chat_id, title):
                await _announce_workspace()
                await announce_objects()
            await announce_chats()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a title is never worth an error
            log.warning("could not name chat %s: %s", chat_id, exc)


class RunSummaries:
    """What each run was for, in one sentence, written in the background.

    `runsummary.py` says why and what. This is when: the moment a run is
    written down with its brief (`runs.record` calls `want`), whenever the one
    program says a run changed (`on_runs`), and once at start for every run of
    the last few days that has none yet. One at a time, because nobody is
    waiting on any of them and a backfill of a hundred must not hold up the
    naming of a chat.
    """

    #: Every run the model was asked about since this process started,
    #: answered or not, so a run that could not be given a sentence is not
    #: asked again on every tool call it makes (`runsummary.py`, "Written
    #: once"). A run looked at before its brief was written down is not in it:
    #: the one program's news of a run can arrive before `starting` has
    #: recorded what it was asked, and that run is asked about once it has.
    asked: set[str] = set()
    #: The runs being looked at this instant, so two news of one run do not
    #: ask twice, and the ones that had news while they were: looked at again
    #: straight after, because that news may be the brief arriving.
    working: set[str] = set()
    again: set[str] = set()
    loop: asyncio.AbstractEventLoop | None = None
    _one_at_a_time: asyncio.Semaphore | None = None

    @classmethod
    async def start(cls) -> None:
        """Take the running loop, and give the recent runs with none a sentence."""
        cls.loop = asyncio.get_running_loop()
        cls._one_at_a_time = asyncio.Semaphore(1)
        runs.on_brief = cls.want
        since = time.time() - runsummary.BACKFILL_DAYS * 86400
        every = await asyncio.to_thread(runs.all_runs, parent=None)
        wanting = [row.id for row in every
                   if row.brief and not row.summary and row.started_at >= since]
        if wanting:
            log.info("%d run(s) of the last %d days have no sentence yet; writing them",
                     len(wanting), runsummary.BACKFILL_DAYS)
        for run_id in wanting:
            cls.want(run_id)

    @classmethod
    def want(cls, run_id: str) -> None:
        """Give this run its sentence if it has none. Returns at once, from any thread."""
        loop = cls.loop
        if not run_id or run_id in cls.asked or loop is None or loop.is_closed():
            return
        if run_id in cls.working:
            cls.again.add(run_id)
            return
        cls.working.add(run_id)
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(cls._write(run_id)))
        except RuntimeError:                      # the loop is going away
            cls.working.discard(run_id)

    @classmethod
    async def _write(cls, run_id: str) -> None:
        try:
            async with cls._one_at_a_time:
                row = await asyncio.to_thread(runs.get, run_id)
                if row is None or not row.brief:
                    return
                cls.asked.add(run_id)
                if row.summary or row.parent_run_id:
                    return
                said = await runsummary.write(row.title, row.brief, subject=run_id)
                if not said:
                    return
                await asyncio.to_thread(runs.record, run_id, make=False, summary=said)
                log.info("run %s is for: %s", run_id, said)
            await _announce_tasks()
        except Exception as exc:  # noqa: BLE001 - a sentence is never worth an error
            log.warning("run %s was given no sentence: %s", run_id, exc)
        finally:
            cls.working.discard(run_id)
            if run_id in cls.again:
                cls.again.discard(run_id)
                cls.want(run_id)


class NewTasks:
    """A new task filed into the project it belongs in, in the background.

    Petar asked for this out loud: "New tasks should be automatically sorted in
    my folders. You can use a small model to do that. Haiku." The model reads
    the task and every project's description and answers with one project, and
    that is the whole of the decision (`rouh/filing.py`).

    After the task, never in front of it, and for the same reason naming a chat
    happens after the turn: the task is made, numbered and on the screen before
    anything here is asked, so a model that is slow, down or useless costs the
    person nothing.

    **Everything that can go wrong ends with the task in a project anyway.**
    It used to end with the task left where it landed, under a "Not sorted"
    heading at the top of the task browser, and on 23 September 2026 Petar
    asked for that heading gone: the projects are his and the model is meant to
    be sorting into them. So the last answer here is `filing.fallback` -
    Miscellaneous - rather than nowhere, and the model not being asked at all
    (`config.filing_auto` off, no key, no network) ends in the same place.

    **Only a task nobody has filed.** A task made inside a project, and a chat
    that was already under one when it was promoted, both arrive here owned,
    and an owned task is left exactly as it is: somebody has already said where
    that belongs, and it is not this model's to move. The same goes for a task
    whose project the person named out loud - `make_a_task` with a project, or
    `move_task` - even when what they named is the fallback itself
    (`filing.placed_by_person`).

    **Sitting in the fallback is not having been filed.** Miscellaneous is
    where a task waits when nobody has decided, and `objecttree.tidy` puts one
    there the moment the board is drawn, so treating it as a decision would
    mean whoever opened the task browser first got to decide. A task in the
    fallback is still asked about and still moves when there is an answer.
    """

    #: The tasks being filed this instant, so two ways of hearing about the
    #: same promotion do not ask twice.
    working: set[str] = set()

    @classmethod
    def maybe_file(cls, task_id: str) -> None:
        """File this task if nobody has. Returns at once."""
        if not task_id or task_id in cls.working:
            return
        cls.working.add(task_id)
        try:
            job = asyncio.ensure_future(cls._file(task_id))
        except RuntimeError:                      # no loop: nothing to file on
            cls.working.discard(task_id)
            return
        job.add_done_callback(lambda _j: cls.working.discard(task_id))

    @classmethod
    def _to_ask(cls, task_id: str) -> tuple[str, list] | None:
        """What the model is asked about this task, or None to leave it alone."""
        store = owning.store()
        if store is None:
            return None
        task = store.get_task(task_id)
        if task is None:
            return None
        offered = filing.choices(store)
        if not offered or cls._already_filed(store, task_id, offered):
            return None
        # The conversation it came out of, where there is one, read off the
        # link that says this task owns it rather than taken from whoever
        # called: a task called "Personal" says nothing on its own, and the
        # first exchange of its chat is what that title was shortened from.
        said = ""
        with contextlib.suppress(Exception):
            for kind, ident in store.children_of("task", task_id, "chat"):
                if kind == "chat":
                    said = chatnames.exchange_text(
                        conversations.opening(ident, chatnames.TURNS))
                    break
        return filing.about_text(task.title, said), offered

    @classmethod
    async def _file(cls, task_id: str) -> None:
        try:
            asked = await asyncio.to_thread(cls._to_ask, task_id)
            if asked is None:
                return
            about, offered = asked
            picked = ""
            if config.filing_auto:
                picked = await filing.choose(about, offered, subject=task_id)
            if not picked:
                # The model had no answer, or was never asked. Miscellaneous is
                # where a task waits then, because there is no bucket on the
                # screen for it to wait in any more (`rouh/filing.py`).
                picked = filing.fallback(offered)
            if not picked:
                log.info("nothing was filed for task %s and there is no project "
                         "to fall back on: it stays where it landed", task_id)
                return
            # Asked again on the way in, because the person may have filed it
            # themselves while the model was reading, and what they did wins.
            done = await asyncio.to_thread(cls._move, task_id, picked)
            if not done:
                return
            await _announce_workspace()
            await announce_objects()
            # And the chats, because the task's conversation is one of them and
            # every row of it carries the task's folder and its project
            # (`conversations._as_row`), both of which this has just changed.
            # Without it the page kept the folder the task was made in: the
            # head of the chat opened "That page is not here any more", and
            # the chat was listed under no project (fr_cd2c6e74472a). The
            # chats went out after this turn and after the naming, both of
            # which happen before this does.
            await announce_chats()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - filing is never worth an error
            log.warning("task %s could not be filed: %s", task_id, exc)

    @classmethod
    def _already_filed(cls, store, task_id: str, offered: list) -> bool:
        """Whether somebody has said where this task belongs. The fallback has not,
        unless it was the person who said it."""
        if filing.was_placed_by_person(task_id):
            return True
        owner = store.owner_of("task", task_id)
        return owner is not None and owner[1] != filing.fallback(offered)

    @classmethod
    def _move(cls, task_id: str, project_id: str) -> bool:
        """Put the task under that project, through the one move path."""
        store = owning.store()
        if store is None:
            return False
        if cls._already_filed(store, task_id, filing.choices(store)):
            return False
        if (store.owner_of("task", task_id) or ("", ""))[1] == project_id:
            return False
        done = owning.move(task_id, project_id)
        if not done.get("ok"):
            log.warning("task %s could not be moved into %s: %s", task_id,
                        project_id, done.get("why") or "")
            return False
        log.info("task %s was filed into %s by %s", task_id, project_id,
                 modeldefaults.use_model("filing", None, config))
        return True


def after_a_turn(chat_id: str) -> None:
    """What the chats do when a turn in one of them finishes.

    Two things, both of which the person sees in the middle column:

    1. the list is sent again, because that chat has just moved to the top of
       it and its message count has gone up. Without this a list left open
       while somebody talks is a list of what was true when they opened it;
    2. the chat is named, if it has no name yet.

    Neither is worth an error and neither is waited for. Returns at once.
    """
    ChatNames.maybe_name(chat_id)
    # The loop is looked for before the coroutine is made, not after: a
    # coroutine handed to `ensure_future` outside a loop is left never awaited,
    # which Python reports as a warning from wherever the garbage collector
    # happens to be.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(announce_chats())
    # And the objects, but only when this turn made a task: the person asked
    # for one out loud and the model called `make_a_task`, and the rail's Tasks
    # list would otherwise not show it until something else happened
    # (`conversations.promotion_to_announce`). A task made inside the project
    # the person named is already where it belongs, and `NewTasks` leaves it
    # there; one moved with `move_task` told every tab itself, at once.
    promoted = conversations.promotion_to_announce()
    if promoted:
        loop.create_task(announce_objects())
        loop.create_task(_announce_workspace())
        NewTasks.maybe_file(promoted)


def own_state(said: str | None = None) -> None:
    """Set the orb's core to what Rouh is really doing, across every thread.

    A turn that is running wins over anything a tab says about itself. A tab
    reporting "I am idle" because nobody is talking into it must not put out
    the light for a turn still being written in a thread nobody is looking at,
    and that is exactly the state the page is in the moment somebody walks away
    from an answer.
    """
    state = None
    for turn in Turns.running.values():
        if turn.state == "speaking":
            state = "speaking"
        elif turn.state == "thinking" and state is None:
            state = "thinking"
    if state is None and said and said != "idle":
        state = said
    if state != OwnWork.state:
        OwnWork.state = state
        TreeFeed.poke()


def place_card(chat: str, spec, after_call: str | None, in_answer: bool = False):
    """A card about to be put at the end of a chat's conversation, with its
    place there written down, so a reload draws it where it was seen.

    The page puts a card it is sent at the end of the conversation, under the
    line of the call that drew it when there is one (`after_call`), and the
    words written after it below it. Until 5 October 2026 nothing but the
    first drawing was kept, so a card revised or asked for again was at the
    bottom live and back where it began after a reload, an exchange up and
    above the words about it (fr_6b1852e8f32e). Never raises: a place that
    could not be written must not keep the card off the screen.
    """
    if not isinstance(spec, dict) or not spec.get("card_id") or not artifacts.enabled():
        return spec
    try:
        after = memory.last_message_id(chat)
        if artifacts.place(spec["card_id"], after_message_id=after, after_call=after_call,
                           in_answer=in_answer,
                           held_by=lambda mid: memory.holds_message(chat, mid)):
            spec = dict(spec, after_message_id=after)
            spec.pop("after_call", None)
            spec.pop("in_answer", None)
            if after_call:
                spec["after_call"] = after_call
            elif in_answer:
                spec["in_answer"] = True
    except Exception:
        log.warning("where card %s sits in %s could not be kept", spec.get("card_id"), chat,
                    exc_info=True)
    return spec


def _whose_turn() -> tuple[str, str]:
    """The person a turn is answered for, and their organisation (`tenancy.speaker`), else the one person."""
    from .tenancy import Tenancy, speaker

    who = speaker()
    if who is None:
        with contextlib.suppress(Exception):
            who = Tenancy().only_person()
    if who is None:
        return "", modeldefaults.org_now()
    return str(who.user_id or ""), str(who.org_id or "") or modeldefaults.org_now()


class Turn:
    """One answer, owned by the thread it was asked in.

    A turn used to belong to the browser tab that asked for it: the task hung
    off the `Session`, and everything that stood a session's turn down killed
    it. Opening another thread did (`switch_chat` cancelled the turn in every
    tab), opening a task did, and so did the socket going away on a reload. So
    an answer the person did not sit and watch was never given at all: they
    came back to their own question with nothing under it, and nothing anywhere
    said why (20 September 2026).

    A turn now belongs to the chat. It is registered in `Turns` under that
    chat's id, it runs to the end whatever the screen is showing, and its
    answer is written into that chat's history as it completes, so the thread
    has it when the person comes back and after a reload. What it sends goes to
    whichever tabs are looking at that thread at that moment, which may be
    three, one or none.

    Two things still end a turn early, and only these two:

    - the person stopping it, which is the Stop control and Escape
      (`rouh/stopping.py`), and
    - the next question in the same thread, which is them talking over their
      own answer (`Turns.cancel`).

    Leaving the thread is neither of those.
    """

    @staticmethod
    def _plain(content) -> str:
        """The words of a question, for a page that has to draw it again."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                str(b.get("text") or "") for b in content
                if isinstance(b, dict) and b.get("type") == "text").strip()
        return ""

    def __init__(self, chat: str, turn_id: int, asked_by: "Session | None",
                 model: str, speak: bool, asked=None,
                 slot: "memory_mod.Slot | None" = None, note: bool = False,
                 also=None, heard: str = ""):
        self.chat = chat
        self.turn_id = turn_id
        #: How the person's words came: said into the microphone, a Telegram
        #: voice note, typed, a Telegram text, or a note of Rouh's own
        #: (`rouh/replymode.py`). Given by the doorway they came in at, or read
        #: off `thoughts.HOW`, which each doorway sets; unknown is typed.
        self.heard = replymode.heard_as(heard or thoughts.HOW.get(), note=note)
        #: Something besides the screens that is given every message this turn
        #: sends, whoever is looking: the answer on Telegram to a message from
        #: the phone is made from it (`telegram_chat.Heard`). None for a turn
        #: nobody but the screens is waiting on, which is nearly every turn.
        self.also = also
        #: What this turn answers is a note of Rouh's own software - a job's
        #: report, a run's question, a press on a card - and not anything the
        #: person said. It is written down as one (`memory.add_message`), and
        #: nothing of it is ever put on a screen as theirs.
        self.note = note
        #: Which exchange of the conversation this turn is writing into, and
        #: which try it is (`memory.Slot`). An empty one is a new question; one
        #: with a root is the person asking the same thing again, or the same
        #: thing reworded, and its answer takes the old answer's place in the
        #: stream rather than being added to the end of it.
        self.slot = slot if slot is not None else memory_mod.Slot()
        #: Whether this turn answers an exchange again, read once here: the
        #: question of a new exchange is given its root the moment it is
        #: written (`brain.Question.write`), after which `slot.again` says yes
        #: for it too. Until 21 October 2026 `took_their_words` read it then,
        #: so an answered spoken question was never taken off the pending
        #: words and was asked again in front of whatever was said next.
        self.again = self.slot.again
        #: What was asked, and whether it has reached the conversation yet.
        #: Nothing of a turn is stored until the model has said the question
        #: was a whole one (`brain.Question`), so for the first few seconds of
        #: a turn the question exists nowhere but here - and a page that
        #: arrives in that window would otherwise draw an answer with nothing
        #: above it saying what it answers.
        self.asked = "" if note else self._plain(asked)
        self.question_written = False
        #: The row of the question this turn wrote, once it has (`took_their_words`), for its record.
        self.message_id: int | None = None
        #: The tab that asked. It is where the voice goes and whose pending
        #: words this turn is writing down, and it is allowed to disappear: a
        #: reload closes it and the turn carries on without it.
        self.asked_by = asked_by
        #: None until a chat on Auto has routed this turn (`route`).
        self.model = model
        #: What Balanced's router decided for this turn, or None for a chat on a fixed tier.
        self.route = None
        #: Every step of this turn as it happens, sent live and kept with it (`rouh/turntrace.py`).
        self.trace: turntrace.Trace | None = None
        #: Set once what the person said was weighed against the call before it
        #: (`modeloutcomes.heard`), which the router's note of this turn waits for.
        self.heard_done = asyncio.Event()
        #: The tier the person picked for this answer, or "" (`Turns.start`).
        self.picked_tier = ""
        #: The turn's name in the log of requests, which its call is kept under
        #: (`rouh/llmlog.py`, `rouh/modeloutcomes.py`).
        self.turn_id = "turn-" + uuid.uuid4().hex[:12]
        self.speak = speak
        self.started_at = time.time()
        #: The pictures this turn's tools drew and put on the screen
        #: (`imaging.SHOWN`), written into the chat as one message of Rouh's
        #: when the turn ends, however it ends.
        self.shown: list[dict] = []
        #: What this turn is doing, in the page's own words. Handed to a tab
        #: that arrives in the middle (`picture`).
        self.state = "thinking"
        #: The words so far, so a tab that comes back to this thread mid-turn
        #: is shown the half-written answer and then goes on receiving it live,
        #: rather than joining at whatever word happens to be next.
        self.said: list[str] = []
        self.task: asyncio.Task | None = None
        self.tts_task: asyncio.Task | None = None
        self.tts_queue: asyncio.Queue | None = None
        #: The tab the sound of this turn is going to, while it is going. The
        #: audio is one tab's and the rest of the turn is the thread's.
        self.speaking_to: "Session | None" = None
        #: Whether this turn reached the end of its own accord. False for one
        #: that was replaced or cut short, which is what keeps a thread from
        #: being marked as having something new when it has not.
        self.answered = False
        #: The newest call this turn has started, by the id its line is drawn
        #: under. A card the turn puts on the screen sits under it, and the
        #: words written after it go below the card (`place_card`).
        self.last_call: str | None = None
        #: What the person typed and sent while this turn was running, oldest
        #: first, and not read by the model yet (`wait_in`). The model takes
        #: it in at its next step (`brain.Brain._take_steer`); what it has not
        #: taken when the answer ends is the next turn (`follow_on`).
        self.waiting: list[dict] = []
        #: Whether a message sent now can still be read by this turn. False
        #: from the moment the model is done, even while the answer is still
        #: being spoken: a message then is the next question, as it always was.
        self.steerable = True

    #: What belongs to the one screen rather than to the thread. Which chat is
    #: being talked in is the person's and is shared by every device; where
    #: that screen's canvas is pointed and which of its columns are open are
    #: that screen's, and two screens can reasonably stand at different
    #: distances from the same conversation. These go to the tab that asked and
    #: nowhere else, and nowhere at all when it has gone.
    ONE_SCREEN = ("canvas", "panels")

    # --- who hears it -------------------------------------------------------

    def tabs(self) -> list["Session"]:
        """Every tab that should be shown this turn: the ones in its thread.

        None is a perfectly good answer. The person opened something else and
        this turn is now being answered into a thread nobody has on screen;
        it goes on being answered, and what it writes is in the thread when
        they come back.

        A tab whose strip of forks has this thread on it is one of them too,
        whichever chat of the strip it is in. The page keeps every chat of a
        strip it has shown as it was, and applies what arrives for one when
        it is slid back into view: Petar, 26 September 2026 (fr_a3aadda7007c),
        "as I was waiting for a response on a child chat, I saw tool calls and
        I went to reread parent and when I came back the list of tool calls
        was missing - which is a sign of loaded chat anew". The page throws
        away what arrives for a chat it is keeping nothing of (`forkHold` in
        app.js).

        The tab that asked is included whether or not the hub knows about it,
        which is what lets a turn be driven with no socket registry in front of
        it. In the running server it is always one of the others anyway.
        """
        tabs = [t for t in Hub.sockets
                if not t.closed and (t.session_id == self.chat or self.chat in t.beside)]
        asked = self.asked_by
        if (asked is not None and asked not in tabs and not asked.closed
                and asked.session_id == self.chat):
            tabs.append(asked)
        return tabs

    def one_screen(self) -> list["Session"]:
        """The tab this turn was asked in, while it is still here and still in
        this thread. See `ONE_SCREEN`."""
        asked = self.asked_by
        if asked is None or asked.closed or asked.session_id != self.chat:
            return []
        return [asked]

    async def emit(self, message: dict) -> None:
        """One message of this turn, to whoever is looking at its thread.

        Every one of them carries the thread it belongs to and the number of
        the turn that wrote it. The thread is what lets a page throw away
        anything that arrives for a conversation it has just left, which is a
        race nothing else can settle: the switch and the message pass each
        other on the wire.
        """
        from . import answers_now

        answers_now.beat(getattr(self, "answer_id", ""))
        if message.get("type") == "assistant_delta":
            self.said.append(message.get("text") or "")
        if self.trace is not None:
            try:
                self.trace.saw(message)
            except Exception:
                log.exception("a turn's timeline could not take a %s", message.get("type"))
        if self.also is not None:
            try:
                self.also(message)
            except Exception:
                log.exception("a turn's listener failed on a %s", message.get("type"))
        message = dict(message, chat=self.chat)
        message.setdefault("turn_id", self.turn_id)
        # Once for the message rather than once per tab: this is the orb's
        # record of what Rouh itself did, not a copy of what each screen saw.
        OwnWork.note(message)
        # And a beat's record of the tools it called (`heartbeat.saw`).
        heartbeat.saw(message)
        # And the chat's record of the lines its tool calls drew, so a chat
        # read back draws them where they were (fr_3f1814427840).
        # Automatic recall's look-ups are the orb's alone (`orb_only`).
        if message.get("type") in ("tool_start", "tool_update", "tool_end") and not message.get("orb_only"):
            memory.note_tool(self.chat, message)
        if message.get("type") == "tool_start" and (message.get("id") or message.get("name")):
            self.last_call = str(message.get("id") or message.get("name"))
        # A card put at the end of the conversation sits there when it is read
        # back too, under the call that drew it (fr_6b1852e8f32e).
        if message.get("type") == "ui" and not message.get("in_place"):
            message["spec"] = place_card(self.chat, message.get("spec"), self.last_call,
                                         in_answer=True)
        for tab in (self.one_screen() if message.get("type") in self.ONE_SCREEN
                    else self.tabs()):
            await tab.send(message)

    async def say_state(self, value: str) -> None:
        """Tell the thread's tabs what this turn is doing now."""
        self.state = value
        own_state(value)
        await self.emit({"type": "state", "value": value})

    def picture(self) -> dict:
        """This turn, for a page that has just arrived in the middle of it.

        Sent when a thread is opened and with the handshake, so coming back to
        a thread that is still being answered shows it still being answered,
        with the words it has written so far, and picks the rest up live.
        """
        return {"turn_id": self.turn_id, "state": self.state,
                "said": "".join(self.said), "started_at": self.started_at,
                # The exchange it is writing into, when it is one being
                # answered again: the page has just drawn that exchange's old
                # answer out of the history, and this is what tells it the
                # words arriving are the replacement rather than a second one.
                "root": self.slot.root if self.again else None,
                # The question, only while the conversation does not have it
                # yet: sending it twice would draw it twice.
                "asked": "" if self.question_written else self.asked,
                # And its timeline so far, so a page that arrives mid-turn draws it (`turntrace`).
                "trace": self.trace.snapshot() if self.trace is not None else None,
                # And what the person sent since that the model has not read
                # yet, drawn waiting at the bottom as it was where it was sent.
                "waiting": [{"id": w["id"], "text": w["text"], "attachments": w["files"]}
                            for w in self.waiting]}

    def wait_in(self, content, *, sid: str, text: str, files: list[dict],
                by: "Session | None") -> bool:
        """Hold a message the person sent while this turn is running, for the
        model to read at its next step. Says whether it was taken: a turn whose
        model is already done cannot read anything more, and the message is
        the next question instead.

        Never awaits, so the turn cannot end between being asked and holding
        it, which is what makes sure no message is dropped on the way between
        this turn and the next (`follow_on`).
        """
        if not self.steerable:
            return False
        self.waiting.append({"id": sid, "content": content, "text": text,
                             "files": files, "by": by})
        return True

    def take_waiting(self) -> list[dict]:
        """Everything waiting, handed to the model and off the queue."""
        taken, self.waiting = self.waiting, []
        return taken

    async def follow_on(self) -> None:
        """Answer what was sent while this turn ran and was never read, as the
        next turn: the first message is its question and the rest go in under
        it before the model reads anything (`brain.Brain._take_steer`).

        Started the moment this turn's model is done, without waiting for the
        last of its answer to be spoken: a message sent during an answer is the
        person moving on.
        """
        if not self.waiting:
            return
        first = self.waiting[0]
        tab = first.get("by")
        if tab is not None and tab.closed:
            tab = None
        speak = bool(tab is not None and tab.voice_replies and voice.ready)
        await Turns.start(self.chat, first["content"], asked_by=tab, speak=speak,
                          answer_now=True, follows=self, heard="typed")

    def was_stopped(self) -> bool:
        """Did the person stop this turn?

        Read wherever something of a turn is about to reach them: a sentence
        about to be synthesised, audio about to be sent. A stop means none of it
        arrives, including the part that was already written and queued.
        """
        return stopping.stops.is_stopped(self.chat, self.turn_id)

    def is_the_current_one(self) -> bool:
        """Whether this is still the turn of its thread, or a replaced one."""
        return Turns.running.get(self.chat) is self

    # --- running it ---------------------------------------------------------

    def begin(self, user_content, answer_now: bool, stop: asyncio.Event | None) -> None:
        """Start the work. Registered in `Turns` before this is called."""
        self.tts_queue = asyncio.Queue()
        if self.speak:
            self.tts_task = asyncio.create_task(self._speak_loop(self.tts_queue))
        self.task = asyncio.create_task(self._run(user_content, stop, answer_now))
        # An answer in progress, until both its answer and its speaking are over: no deploy
        # restarts Rouh under it (`rouh/answers_now.py`).
        from . import answers_now, mail_turn

        kind = ("telegram" if telegram_chat.FROM_PHONE.get() is not None
                else "mail" if mail_turn.CURRENT.get() is not None
                else "note" if self.note else "chat")
        self.answer_id = answers_now.begin(kind, self.chat, tasks=[self.task, self.tts_task])

    async def _run(self, user_content, stop: asyncio.Event | None,
                   answer_now: bool) -> None:
        # Somebody is waiting on this: work nobody waits on holds back until it
        # is answered (`dbwork.foreground`).
        with dbwork.foreground():
            await self._answer(user_content, stop, answer_now)

    async def _answer(self, user_content, stop: asyncio.Event | None,
                      answer_now: bool) -> None:
        queue = self.tts_queue
        started = time.monotonic()
        first_word = None
        # Which thread everything this turn writes down belongs to, for the
        # code that is never told - a card drawn from inside a tool
        # (`memory.ANSWERING`). Set here rather than around the task that was
        # created, so it is this turn's own context and cannot be read back by
        # a turn running beside it in another thread.
        memory_mod.ANSWERING.set(self.chat)
        # And whether it answers a note rather than the person, which holds a note
        # answered in the Heartbeat chat to the heartbeat's rules (`heartbeat.held`).
        heartbeat.TURN_NOTE.set(self.note)
        # And whether the person started it, with their own words: typed or spoken on a
        # screen of theirs, or written from their own Telegram. Only those words can
        # authorize a sign-up, and only in such a turn (`rouh/signups.py`); a note of
        # Rouh's software - a job's report, a hand-back, an email, a reminder - never.
        person = not self.note and (self.asked_by is not None
                                    or telegram_chat.FROM_PHONE.get() is not None)
        signups.PERSON_TURN.set(person)
        # Asked at a tab while demo mode is on: the turn is on the stage, in front of an
        # audience. It is drawn as it is, told nothing of the person's memory, rules or
        # words, and offered only tools that see nothing of theirs (`rouh/demo.py`).
        if person and self.asked_by is not None and telegram_chat.FROM_PHONE.get() is None:
            try:
                from . import demo

                me = getattr(self.asked_by, "me", None)
                preview = bool(getattr(self.asked_by, "demo_preview", False))
                if me is not None and (preview or await asyncio.to_thread(demo.is_on, me)):
                    demo.stage_turn(self.turn_id, self.chat)
                    # Every tab of theirs hears it, so this turn's words are drawn as they are.
                    asyncio.ensure_future(demo.broadcast(me))
                    demo.STAGE.set(True)
                    demo.STAGE_LENS.set(await asyncio.to_thread(demo.lens_for, me, preview))
            except Exception:
                log.exception("demo: whether this turn is on the stage could not be decided")
        # The turn's timeline, from this moment: the message has reached the server
        # (`rouh/turntrace.py`). In this turn's own context, so the router's task below and
        # every request and tool of the turn find it.
        self.trace = turntrace.Trace(self.chat, self.turn_id, self.emit, started_at=self.started_at,
                                     asked="" if self.note else self.asked, note=self.note)
        turntrace.CURRENT.set(self.trace)
        if self.slot.again:
            self.trace.root = self.slot.root
        if self.model is not None:
            with contextlib.suppress(Exception):
                fixed = await asyncio.to_thread(self.decided)
                self.trace.route = {k: v for k, v in fixed.items() if k != "trace"}
                self.trace.decided(self.model, fixed.get("tier") or "")
        self.trace.touch(now=True)
        # In Balanced, the router's decision is started first, before anything else the
        # turn does, and waited for by the brain only once its memory look-ups are
        # under way too (`Brain.run_turn`): the two run side by side, and neither
        # waits for the other (`rouh/modelrouter.py`).
        model = self.model if self.model is not None else \
            asyncio.ensure_future(self.routed(user_content))
        try:
            if person:
                signups.heard(self.chat, user_content)
                if not self.slot.again:
                    # Asking the last thing again, or saying it was wrong, is how a
                    # call to a model is found wanting (`rouh/modeloutcomes.py`).
                    with contextlib.suppress(Exception):
                        await asyncio.to_thread(modeloutcomes.heard, self.chat, user_content)
        except BaseException:
            # Stopped before the brain took the decision over: nothing waits for it.
            if asyncio.isfuture(model):
                model.cancel()
            raise
        finally:
            self.heard_done.set()
        # And where a tool that draws a picture leaves it, for the end of the
        # turn to write down (`imaging.SHOWN`), the same way.
        imaging.SHOWN.set(self.shown)
        # Written down before the turn and cleared in the `finally` below,
        # however it ends. The only way a row survives is the process going
        # away mid-turn, and that is the case it exists for: `startup` turns
        # what is left here into a sentence in the transcript rather than
        # leaving the person with a question and no reply, ever (memory.py).
        memory.begin_turn(self.chat, user_content, note=self.note)
        saving = ""
        # How the turn ended, for its record (`rouh/turnrecords.py`).
        ended, failure = "", ""
        try:
            if self.slot.again:
                # Said before a word of the new answer is written, because the
                # page has to take the old answer down and point the new one at
                # the place it came out of. Every tab in the thread hears it:
                # the question was changed for the conversation, not for one
                # screen.
                await self.emit({"type": "retry", "root": self.slot.root,
                                 "version": self.slot.version,
                                 "text": self.asked})
            await self.say_state("thinking")

            async def on_sentence(sentence: str) -> None:
                nonlocal first_word
                if first_word is None:
                    first_word = time.monotonic()
                    if self.trace is not None:
                        self.trace.spoken()
                if self.speak and queue is not None:
                    # A task's number is said as its name (`searching.spoken`).
                    try:
                        sentence = await asyncio.to_thread(searching.spoken, sentence)
                    except Exception:
                        log.exception("could not say the task numbers in a sentence by name")
                    await queue.put(sentence)

            await brain.run_turn(
                self.chat,
                user_content,
                self.emit,
                on_sentence if self.speak else None,
                model=model,
                turn_id=self.turn_id,
                stop=stop,
                answer_now=answer_now,
                # Their words stop being pending the moment they are written
                # down, so a question that has been answered is never asked
                # again as part of the next one.
                taken=self.took_their_words,
                slot=self.slot,
                note=self.note,
                steer=self.take_waiting,
                heard=self.heard,
            )
            self.answered = True
            ended = "stopped" if self.was_stopped() else "finished"
            if ended == "finished" and person:
                # Maybe a blind comparison of this answer, once it is shown and only with
                # the opt-in on: in the background, never in the answer's way
                # (`rouh/modelvotes.py`).
                with contextlib.suppress(Exception):
                    from . import modelvotes
                    from .tenancy import speaker

                    root, chat = self.slot.root, self.chat
                    modelvotes.after_turn(
                        chat, self.turn_id, root, speaker(), chatkinds.use_for(chat), self.asked,
                        lambda: memory.history(chat, modelvotes.HISTORY, before=root),
                        lambda message: Pictures.to_chat(chat, message))
            # What follows the answer, until the turn is over (`turntrace`).
            saving = self.trace.start("step", "Saving the answer")
        except turnmarks.Unfinished as unfinished:
            ended = "stopped" if self.was_stopped() else "unfinished"
            if self.was_stopped():
                # Stop, pressed in the moment the model was deciding. There is
                # nothing to stop by then - nothing was said, shown or stored -
                # but what they had said is dropped rather than answered
                # twenty seconds later by a clock nobody can see.
                self.took_their_words()
            elif self.asked_by is not None:
                await self.asked_by.not_finished_yet(unfinished)
        except asyncio.CancelledError:
            # Stopped, or talked over and replaced by the next question.
            ended = "stopped" if self.was_stopped() else "replaced"
            raise
        except Exception as exc:
            log.exception("turn failed")
            ended, failure = "failed", f"{type(exc).__name__}: {exc}"
            from . import providerkeys

            if not await asyncio.to_thread(providerkeys.chats_can_answer):
                # No key for any provider: said plainly, with where to add one, and kept on
                # the screen until closed (a new Rouh's first run, 24 October 2026).
                await self.emit({"type": "error", "message": providerkeys.where_to_add_a_key(),
                                 "fatal": False, "lasting": True})
            else:
                await self.emit({"type": "error", "message": str(exc)[:300], "fatal": False})
        finally:
            # A turn that ended before the brain took the router's decision over.
            if asyncio.isfuture(model) and not model.done():
                model.cancel()
            # The model is done, so a message sent from here on is the next
            # question rather than something this turn can still read.
            self.steerable = False
            with contextlib.suppress(Exception):
                memory.end_turn(self.chat)
            # The pictures the turn drew, after the last of its own rows and
            # in the same exchange, so they go wherever it goes: taken down by
            # a retry with the rest of the answer, and back with it. Before
            # the turn is off the register, so nothing else can be written in
            # this chat in between.
            if self.shown and self.slot.root is not None:
                try:
                    memory.add_message(self.chat, "assistant", list(self.shown),
                                       root=self.slot.root, version=self.slot.version)
                except Exception:
                    log.exception("the pictures a turn drew could not be written down")
            # What the person sent while it ran and the model never got to: the
            # next turn, straight away. Only from the turn still on the
            # register: one that was replaced has handed its queue to the turn
            # that replaced it (`Turns.start`).
            if self.waiting and self.is_the_current_one():
                try:
                    await self.follow_on()
                except Exception:
                    log.exception("what was sent during a turn could not be answered")
            if saving and self.trace is not None:
                self.trace.end(saving)
            if self.speak and queue is not None:
                await queue.put(None)  # tell the voice there is nothing more
                if self.tts_task:
                    speaking = (self.trace.start("step", "Speaking")
                                if self.trace is not None and not self.tts_task.done() else "")
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await self.tts_task
                    if speaking:
                        self.trace.end(speaking)
            if self.trace is not None:
                self.trace.finish(ended or "failed", failure)
            # The flag is dropped last. Until this line a stop can still land on
            # this turn and be read by the voice; after it, the number belongs
            # to nothing and a late press finds nothing to stop, which is the
            # answer it should get.
            stopping.stops.end(self.chat, self.turn_id)
            # Read before it is taken off the register, because that is the
            # question `turn_is_over` answers with: a turn that is still its
            # thread's own ends with "idle", and one that was replaced says so
            # by number instead.
            was_the_current_one = self.is_the_current_one()
            Turns.forget(self)
            # And the thread's tabs are told, whatever became of this turn. See
            # `turn_is_over`: the guard that used to be here announced only the
            # turns that ended tidily.
            with contextlib.suppress(Exception):
                await self.turn_is_over(was_the_current_one)
            # "never" would be wrong when spoken replies are simply switched
            # off, and this line exists to be trusted at a glance.
            if not self.speak:
                spoken_at = "voice off"
            elif first_word:
                spoken_at = f"{first_word - started:.1f}s"
            else:
                spoken_at = "never - nothing was said aloud"
            log.info(
                "turn %s finished: %.1fs total, first words at %s",
                self.turn_id, time.monotonic() - started, spoken_at,
            )
            # How long the answer took and whether it came, whose turn it was
            # (`rouh/events.py`): the person's, or a note of Rouh's software.
            events.emit("turn.finished", actor="person" if person else "rouh",
                        source=("telegram" if telegram_chat.FROM_PHONE.get() is not None
                                else "web" if self.asked_by is not None else "server"),
                        chat_id=self.chat, object_type="chat", object_id=self.chat, owner=True,
                        duration_ms=(time.monotonic() - started) * 1000,
                        props={"ok": bool(self.answered), "spoken": bool(self.speak),
                               "first_word_ms": (int((first_word - started) * 1000)
                                                 if first_word else None)})
            # And what the exchange looks like now it has been answered: one
            # more try behind it than it had, which is what the counter under
            # the message says.
            if self.slot.root is not None:
                with contextlib.suppress(Exception):
                    await self.say_exchange()
            # An exchange answered again is a branch of the conversation from it:
            # every tab in the chat is shown the branch it is on now, what came
            # after the old answer gone with it and every card as this branch has
            # it (`branch_redraw`). Only once the question was written: a try
            # stopped before that changed nothing.
            if self.slot.again and self.slot.root is not None:
                changed = memory.took_branch(self.chat, self.slot.root)
                if changed:
                    with contextlib.suppress(Exception):
                        await branch_redraw(self.chat, self.slot.root, changed)
            # Everything it took, kept for good, and kept again with whatever arrives
            # after it (`rouh/turnrecords.py`).
            if self.trace is not None:
                self.trace.keep = self._keep_trace
                await self._record()
            # An answer that landed in a thread the person is not looking at
            # leaves a quiet mark on that thread in the rail, and nothing else:
            # it is not spoken, and it does not take the view back. They
            # asked, they walked off, and this is how they find out it came
            # (`memory.mark_unread`). The list goes out below.
            if self.answered and not any(tab.session_id == self.chat
                                         for tab in open_tabs()):
                with contextlib.suppress(Exception):
                    memory.mark_unread(self.chat)
            # The question and its answer are both stored by now, which is the
            # first moment this chat can be named from what it is about. It is
            # tried again after the next turn if it did not work, so a chat that
            # is still untitled a couple of turns in gets another go.
            after_a_turn(self.chat)

    def took_their_words(self, message_id: int | None = None) -> None:
        """Their words are written down, so they are no longer pending.

        On the tab that said them, because that is where the pending list is:
        the browser hears where a sentence ends and the model decides where the
        question does, and until it has, what they said is still theirs to add
        to (`rouh/turnmarks.py`).

        It is also the first moment the exchange has a number, so it is where
        the thread's tabs are told which one this turn is writing into. Without
        it a message drawn live has nothing under it to press: retry and edit
        both name an exchange, and until the question is stored there is not
        one to name.
        """
        self.question_written = True
        if message_id is not None:
            self.message_id = int(message_id)
        # Only a question of theirs stops being pending. An exchange being
        # answered again was asked minutes ago and is not what they are in the
        # middle of saying now, so a retry must not swallow it, and a note of
        # Rouh's own is not anything they said.
        if self.asked_by is not None and not self.again and not self.note:
            self.asked_by.pending.clear()
        if message_id is None and self.slot.root is None:
            return
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self.say_exchange())

    async def routed(self, user_content) -> str:
        """Pick this turn's tier on Auto, once, before it starts: a model reads the
        message with what came before it (`rouh/modelrouter.py`). The turn keeps
        that model through every tool loop. Written down with the turn's call."""
        from . import modelrouter

        def before() -> list:
            try:
                return modelrouter.history_of(memory.history(self.chat, 8))
            except Exception:
                return []

        org = modeldefaults.org_now()
        trace = self.trace
        lane = {}

        def asking(router: str) -> None:
            # The router's bar starts the moment the Decisions API is asked (`turntrace`).
            if trace is not None:
                lane["id"] = trace.start("router", "Choosing the model", model=router)

        # Everything it reads, on its own threads and side by side, so it is never
        # behind the memory look-ups started beside it (`modelrouter.off`).
        self.route = await modelrouter.decide(self.chat, user_content, modelrouter.off(before),
                                              turn_id=self.turn_id, org_id=org, cfg=config,
                                              on_start=asking)
        self.model = self.route.model
        if trace is not None:
            d = self.route
            if lane.get("id"):
                trace.end(lane["id"], turntrace.DONE if d.ok else turntrace.FAILED,
                          pick=d.tier, pick_name=modeldefaults.TIER_NAMES.get(d.tier, d.tier),
                          picked=d.model, picked_name=model_name(d.model), easy=d.easy, bar=d.bar,
                          tokens_in=d.tokens_in or None, cost=d.cost, outcome=d.outcome,
                          error=d.error or None, result=d.reason or None)
            # Said the moment it is decided, with the person's message, never only once the
            # question is written (23 October 2026: the line came after the answer).
            trace.route = modelrouter.timeline(d, self.started_at)
            trace.decided(d.model, d.tier)
            trace.touch(now=True)
        # Written after what the person said was weighed against the call before
        # it (`modeloutcomes.heard`), which would otherwise find this one.
        await self.heard_done.wait()
        await modelrouter.off(modeloutcomes.note_route, self.turn_id, session_id=self.chat,
                              use=chatkinds.use_for(self.chat), org_id=org, decision=self.route)
        # The turn goes on with its model now; the "Model decision" line under its
        # answer is kept and said beside it, not in front of it.
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(self._say_route())
        return self.model

    async def _say_route(self) -> None:
        """Keep how the model was decided with the turn, and say it again if the
        question was written while the router was still reading."""
        from . import modelrouter

        with contextlib.suppress(Exception):
            await modelrouter.off(memory.note_route, self.turn_id, self.chat, self.decided(),
                                  self.slot.root)
        if self.slot.root is not None and self.question_written:
            await self.say_exchange()

    async def _keep_trace(self) -> None:
        """The finished turn's model decision and record kept again, with what arrived after it ended."""
        from . import modelrouter

        if self.slot.root is not None:
            with contextlib.suppress(Exception):
                await modelrouter.off(memory.note_route, self.turn_id, self.chat, self.decided(),
                                      self.slot.root)
        await self._record()

    async def _record(self) -> None:
        """This turn's record, whole: its timeline, its times, its answer and what it cost
        (`rouh/turnrecords.py`). Never worth a failure of the turn."""
        from . import modelrouter, turnrecords

        trace = self.trace
        if trace is None:
            return
        try:
            kept = trace.kept()
            route = kept.get("route") or {}
            facts = {
                "turn_id": self.turn_id, "session_id": self.chat, "message_id": self.message_id,
                "root": self.slot.root, "version": self.slot.version, "note": bool(self.note),
                "heard": self.heard or "", "started_at": self.started_at,
                "ended_at": trace.started_at + kept["elapsed_ms"] / 1000, "total_ms": kept["elapsed_ms"],
                "status": kept.get("outcome") or "", "error": kept.get("error") or "",
                "tier": kept.get("tier") or route.get("tier") or "", "model": kept.get("model") or "",
                "mode": route.get("mode") or "", "trace": kept,
            }
            facts["user_id"], facts["org_id"] = _whose_turn()
            await modelrouter.off(turnrecords.save, facts)
        except Exception:
            log.exception("the record of turn %s could not be kept", self.turn_id)

    def decided(self) -> dict:
        """How this turn's model was decided, as the "Model decision" line under its
        answer draws it (`modelrouter.timeline`): the router's steps on Auto, or the
        chat's own fixed tier."""
        from . import modelrouter

        # The timeline itself is the turn's record's (`rouh/turnrecords.py`), not this line's.
        more = {"version": self.slot.version}
        if self.route is not None:
            return dict(modelrouter.timeline(self.route, self.started_at), **more)
        if self.picked_tier:
            return dict(modelrouter.timeline(None, self.started_at, tier=self.picked_tier,
                                             model=self.model or "", chosen=True), **more)
        mode = ""
        try:
            use = chatkinds.use_for(self.chat)
            now = modeldefaults.Now(modeldefaults.org_now(), config)
            tier = now.kind(use)
            if modelstandard.routed(use, now.doc) and use not in now.locked:
                mode = now.mode
        except Exception:
            tier = ""
        if tier == modeldefaults.AUTO:
            # In Balanced, and not routed yet: the line waits for the router.
            return {}
        return dict(modelrouter.timeline(None, self.started_at, tier=tier, model=self.model or "",
                                         mode=mode), **more)

    async def say_exchange(self) -> None:
        """Which exchange this turn is writing into, and how many tries it has,
        and how its model was decided (the "Model decision" line under the answer)."""
        root = self.slot.root
        if root is None:
            return
        if self.route is not None:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(modeloutcomes.note_root, self.turn_id, root)
        decided = {}
        with contextlib.suppress(Exception):
            decided = await asyncio.to_thread(self.decided)
            if decided:
                await asyncio.to_thread(memory.note_route, self.turn_id, self.chat, decided, root)
        with contextlib.suppress(Exception):
            said = dict(memory.exchange(root), type="exchange")
            if decided:
                # The timeline is kept with it, and sent on its own (`trace`).
                said["route"] = {k: v for k, v in decided.items() if k != "trace"}
            if self.note:
                # Began by a note of Rouh's own, so none of the person's
                # messages on the screen is its question (`onExchange`).
                said["note"] = True
            await self.emit(said)

    async def turn_is_over(self, was_the_current_one: bool) -> None:
        """Say that this turn has ended, however it ended.

        Every way out of `_run` comes through here, including the ways that are
        not endings anybody asked for: an exception, a stop, a turn replaced by
        the next question. Before this, the end of a turn was announced only
        when it was still the current one, so a turn that had been superseded
        or cancelled told the browser nothing at all and the page was left with
        the Stop control on screen and Rouh's own line on the orb lit, with
        nothing on any clock to correct it.

        A turn that is still its thread's current one ends with `state: idle`,
        which is what it always was. One that is not is announced by its number
        instead: saying "idle" for a turn that has already been replaced would
        put out the light for the turn now running.
        """
        self.state = "idle"
        own_state()
        if was_the_current_one:
            await self.emit({"type": "state", "value": "idle"})
        else:
            await self.emit({"type": "turn_end"})

    async def cancel(self) -> None:
        """End this turn where it stands, because something replaced it.

        An answer still being written is an answer to a question the person had
        not finished asking, so what the model wrote of it is taken back and
        what they say next joins the question instead. A finished answer that
        happens still to be being spoken is left alone: it was written for the
        whole of what they said, and the turn that wrote it is already over by
        the time it is heard.
        """
        with contextlib.suppress(Exception):
            memory.drop_what_was_written(self.chat, self.started_at)
        Turns.forget(self)
        for task in (self.task, self.tts_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self.state = "idle"
        own_state()
        # Said again here rather than trusted to the cancelled task. It costs
        # one small message, and the page acts on the second copy of it exactly
        # as it acts on the first, which is not at all.
        with contextlib.suppress(Exception):
            await self.emit({"type": "turn_end"})

    # --- the voice ----------------------------------------------------------

    def listener(self) -> "Session | None":
        """The tab this turn may speak into, or None when there is not one.

        Speaking follows the person, not the thread. An answer that finishes
        while they are reading another thread must not start talking over what
        they are doing, so the voice stops the moment the tab that asked has
        moved somewhere else - or has gone, which is what a reload is. The rest
        of the answer is written into the thread in silence, and it is there to
        read when they come back.
        """
        tab = self.asked_by
        if tab is None or tab.closed or tab.session_id != self.chat:
            return None
        return tab if tab.voice_replies else None

    async def _speak_loop(self, queue: asyncio.Queue) -> None:
        """Turn finished sentences into audio, in order, while the model writes."""
        announced = False
        try:
            while True:
                sentence = await queue.get()
                if sentence is None:
                    break
                from . import answers_now

                answers_now.beat(getattr(self, "answer_id", ""))
                # Three ways this turn can be over before its words are: it was
                # replaced by a later one, the person stopped it, or they are
                # no longer anywhere it can be said to. A stopped turn drops
                # whatever is still in the queue unspoken, which is the whole
                # of what "no further speech from that turn" means.
                if not self.is_the_current_one() or self.was_stopped():
                    break
                # Petar, 19 September 2026: "if it is muted, no request needs
                # to go to elevenlabs. i don't want muted to mean calling
                # elevenlabs and just volume-ing it 0." Read here, on every
                # sentence, because the switch can be thrown in the middle of
                # an answer and every sentence after it is one nobody will
                # hear and every one of them would have been billed. The same
                # goes for walking away from the thread.
                tab = self.listener()
                if tab is None:
                    break
                try:
                    async for chunk in voice.stream(sentence):
                        if not self.is_the_current_one() or self.was_stopped():
                            return
                        tab = self.listener()
                        if tab is None:
                            return
                        if not announced:
                            # To the tab the bytes are going to and to no
                            # other: a page that is handed `audio_start` and
                            # never given the audio sits waiting for a sound
                            # that was never meant for it. That the turn is
                            # speaking is everybody's business and is said
                            # below; the sound itself is one tab's.
                            self.speaking_to = tab
                            await tab.send({"type": "audio_start",
                                            "chat": self.chat,
                                            "turn_id": self.turn_id,
                                            "sample_rate": config.tts_sample_rate})
                            await self.say_state("speaking")
                            announced = True
                        await tab.send_audio(chunk)
                except SpeechError as exc:
                    log.warning("speech: %s", exc)
                    await self.emit({"type": "error", "message": str(exc)[:200], "fatal": False})
                    break
        except asyncio.CancelledError:
            raise
        finally:
            if announced and self.speaking_to is not None:
                await self.speaking_to.send({"type": "audio_end",
                                             "chat": self.chat,
                                             "turn_id": self.turn_id})
                self.speaking_to = None


class Turns:
    """Every turn being answered right now, by the thread it belongs to.

    One per thread: a second question asked in the same thread is the person
    talking over their own answer, and it replaces the turn that was running.
    Two different threads can be answered at once, which is the whole point -
    ask something, walk away to another thread, ask something there, and both
    answers land where they were asked.
    """

    running: dict[str, "Turn"] = {}
    #: The last turn of each thread, running or over. What "is this thread
    #: busy" is asked of is `running`; this is for the caller that wants the
    #: turn itself - to wait for it, or to read what it was - a moment after it
    #: has ended.
    latest: dict[str, "Turn"] = {}
    _last = 0

    @classmethod
    def of(cls, chat: str) -> "Turn | None":
        """The turn running in this thread, or None."""
        return cls.running.get(chat)

    @classmethod
    def busy(cls, chat: str) -> bool:
        return cls.of(chat) is not None

    @classmethod
    def anything_running(cls) -> bool:
        return bool(cls.running)

    @classmethod
    def forget(cls, turn: "Turn") -> None:
        """Take a turn off the register, if it is still the one on it."""
        if cls.running.get(turn.chat) is turn:
            cls.running.pop(turn.chat, None)

    @classmethod
    async def cancel(cls, chat: str) -> bool:
        """End the turn running in this thread, because something replaced it.

        Called for the two things that are allowed to: the next question in the
        same thread, and a deliberate interruption. Never for anything the
        person did with the screen.
        """
        turn = cls.running.get(chat)
        if turn is None:
            return False
        await turn.cancel()
        return True

    @classmethod
    async def start(cls, chat: str, user_content, *, asked_by: "Session | None",
                    speak: bool, answer_now: bool = False,
                    slot: "memory_mod.Slot | None" = None,
                    note: bool = False, also=None,
                    follows: "Turn | None" = None, heard: str = "",
                    tier: str = "") -> "Turn":
        """Every turn starts here, so a deploy about to restart Rouh holds new ones back here
        (`rouh/answers_now.py`): the turn waits, and what the person asked on a screen is
        kept on disk too, so a restart that comes first does not lose it. A turn that carries
        on the one before it (`follows`) is part of that answer and is never held."""
        from . import answers_now

        starting = answers_now.enter("starting", chat)
        if not starting and follows is None:
            keep = None
            if asked_by is not None and telegram_chat.FROM_PHONE.get() is None and slot is None:
                keep = answers_now.person_turn(chat, user_content, note=note,
                                               heard=heard or thoughts.HOW.get() or "",
                                               who=getattr(asked_by, "me", None))
            while not starting:
                await answers_now.admit("chat", chat, keep=keep)
                keep = None
                starting = answers_now.enter("starting", chat)
        try:
            return await cls._start(chat, user_content, asked_by=asked_by, speak=speak,
                                    answer_now=answer_now, slot=slot, note=note, also=also,
                                    follows=follows, heard=heard, tier=tier)
        finally:
            answers_now.end(starting)

    @classmethod
    async def _start(cls, chat: str, user_content, *, asked_by: "Session | None",
                     speak: bool, answer_now: bool = False,
                     slot: "memory_mod.Slot | None" = None,
                     note: bool = False, also=None,
                     follows: "Turn | None" = None, heard: str = "",
                     tier: str = "") -> "Turn":
        """Answer this, in this thread, and hand the turn back.

        The thread may be a draft - a task opened, or New chat pressed, with
        nothing said in it yet - and this is the moment it stops being one: the
        chat is written under the id the page already has, owned by what it
        was for, and every tab is told there is a chat, and who holds it now.

        Who answers is the thread's to say and nobody else's: its tier's model,
        General's or every other chat's (`chatkinds.model_for`). Whichever tab asked, and whatever woke it - a
        job's report, an email, a press on a card - the same chat is answered
        by the same model.

        `heard` is how the person's words came (`rouh/replymode.py`); left
        empty, it is read off `thoughts.HOW`, which the doorway set.

        `note` is `user_content` being a note of Rouh's own software rather
        than the person's words (`Turn.note`). `also` is given every message
        the turn sends (`Turn.also`).

        `tier` is a tier the person picked for this one answer (Cheaper, Daily
        or Best beside the "Model decision" line, Petar, 21 October 2026): the
        chat's use on that tier answers, with no router, whatever the chat is on.

        Whatever the person sent while the turn being replaced was running,
        and it never read, is carried into this one and read at its first step
        (`Turn.waiting`). `follows` is the turn whose model has just finished
        with messages still waiting (`Turn.follow_on`): it is not cancelled,
        because it is ending by itself, and the first of its messages is this
        turn's question, whatever `user_content` was handed in.
        """
        made = await asyncio.to_thread(conversations.make, chat)
        # A chat on Auto has no model until its turn has read the message and
        # picked a tier (`Turn.route`, `rouh/modelrouter.py`).
        tier = modelstandard.tier_id(tier) if tier else ""
        tier = tier if tier in modeldefaults.TIERS else ""
        if tier:
            model = await asyncio.to_thread(chatkinds.tier_model, chat, tier, config)
        else:
            routes = await asyncio.to_thread(chatkinds.routes, chat, config)
            model = None if routes else await asyncio.to_thread(chatkinds.model_for, chat, config)
        before = cls.running.get(chat)
        if follows is not None:
            if before is not follows or not follows.waiting:
                # Replaced meanwhile, and the turn that replaced it carried its
                # messages; or the model took them at its very last step.
                return follows
            cls.forget(follows)
        else:
            await cls.cancel(chat)
        # Read after the cancel and with nothing awaited from here until the
        # new turn is on the register, so a message sent in between is either
        # in this list or held by the new turn, and never by neither.
        carried: list[dict] = []
        if before is not None:
            carried, before.waiting = before.waiting, []
        question_of = None
        if follows is not None:
            question_of, carried = carried[0], carried[1:]
            user_content = question_of["content"]
        cls._last += 1
        turn = Turn(chat, cls._last, asked_by, model=model, speak=speak,
                    asked=user_content, slot=slot, note=note, also=also, heard=heard)
        turn.picked_tier = tier
        turn.waiting = carried
        cls.running[chat] = turn
        cls.latest[chat] = turn
        # The turn is registered as stoppable before anything of it runs, so
        # Stop pressed in the same breath as the question still lands on it.
        stop = stopping.stops.begin(chat, turn.turn_id)
        turn.begin(user_content, answer_now, stop)
        if question_of is not None:
            # The message that was waiting is this turn's question now: the
            # page takes the mark off it and puts it under the answer it waited
            # behind (`steer_taken`).
            with contextlib.suppress(Exception):
                await turn.emit({"type": "steer_taken", "question": True, "root": None,
                                 "taken": [{"id": question_of["id"], "message_id": None,
                                            "text": question_of["text"],
                                            "attachments": question_of["files"]}]})
        # The rail says which threads are being answered, and one of them has
        # just started. Scheduled rather than awaited, and for two reasons:
        # it is a nicety that must never hold a question up, and a `start_turn`
        # that gave the loop a turn before it returned would let the whole
        # answer happen inside it.
        with contextlib.suppress(RuntimeError):
            asyncio.get_running_loop().create_task(announce_chats())
            if made is not None:
                # A task that had nothing under it has a chat now, which is
                # what its row in the tree and the count on its page are drawn
                # from.
                asyncio.get_running_loop().create_task(announce_objects())
        return turn


async def inboxes_hear(who, changed: dict) -> None:
    """Tell every tab of this person's that a message in their mailbox changed.

    Archived, read or unread, by a press on an inbox card or by Rouh itself -
    reading an email, archiving the conversation once a reply went - so every
    inbox card on every screen of theirs follows (`card_inbox_changed`), and
    what the card shows is what Gmail now holds.
    """
    if who is None or not changed:
        return
    said = {"type": "card_inbox_changed", **changed}
    for tab in list(Hub.sockets):
        me = getattr(tab, "me", None)
        if tab.closed or me is None or (me.user_id, me.org_id) != (who.user_id, who.org_id):
            continue
        await tab.emit(said)


async def tell_thread(chat: str, note: str, *, pressed_in: "Session | None" = None) -> None:
    """Tell a thread what the person just did on a card, as a note of Rouh's own.

    A press on a card that did something outside Rouh - saved a contact, sent
    an email - is put to the thread the card was drawn in, so the assistant
    says it is done and knows not to do it a second time. That is a turn of
    its own, answered now, and it stands down whatever was being said there,
    because the person has just done the thing it was about. An inbox card's
    archive or mark is not one of these: it is written down without a turn
    (`InboxNotes`).

    Written down as a note (`Turn.note`): it is the model's to read and never
    the person's, so it is never drawn under their name. The card buttons used
    to start it as though the person had typed it, and reading the chat back
    showed "[A note from Rouh's own software...]" as something they had said,
    the very thing feedback fr_2f27e92125ba was about.

    The tab it answers into is the one that pressed, when that tab is in the
    thread, and otherwise the newest tab that is; with none, it is answered in
    silence, there to read when they come back.
    """
    if not note or not chat or memory.chat(chat) is None:
        return
    here = [s for s in list(Hub.sockets) if not s.closed and s.session_id == chat]
    tab = pressed_in if pressed_in in here else (
        max(here, key=lambda s: getattr(s, "opened_at", 0.0)) if here else None)
    await Turns.start(chat, f"{turnmarks.NOTE} {note}]", asked_by=tab,
                      speak=bool(tab is not None and tab.voice_replies and voice.ready),
                      answer_now=True, note=True)


class InboxNotes:
    """What the person did on an inbox card, written into its thread.

    Most of what the card does is written down without a word. Archiving,
    putting back, marking read or unread - anything that only moves a message
    in the mailbox - used to start a turn that said it back out loud, and Petar
    did not want that (25 September 2026): the card already shows it, and a
    sentence about every press talks over the person going down their inbox. So those are kept as a note of Rouh's own in
    the conversation and nothing else: no turn, nothing spoken, nothing drawn.
    The next turn reads the note with the rest of the history, which is how
    Rouh still knows what was archived when it is asked, and knows not to do
    it a second time.

    A person going down their inbox archives one message after another, a
    second or two apart, so the presses in a thread are gathered into one note
    once they stop for a moment (`WAIT`). The note is never written in the
    middle of a turn in that thread: a row put between a tool call and its
    result breaks the conversation for every turn after it
    (`memory.repair_history`), so it waits for the turn to end.

    A send is the one that is still answered (`inbox.Answer.turn`): it is told
    at once as a turn of its own, and Rouh says in a sentence what went, as the
    draft card's Send does. Whatever was waiting to be written down is written
    first, so the thread holds everything in the order it happened.
    """

    #: How long after the last press the note is written.
    WAIT = 4.0

    pending: dict[str, list[str]] = {}
    #: When the first of the waiting presses in each thread was made.
    since: dict[str, float] = {}
    timers: dict[str, asyncio.TimerHandle] = {}
    #: The notes on their way, held so none is collected half told.
    telling: set[asyncio.Task] = set()

    @classmethod
    def add(cls, chat: str, line: str, *, pressed_in: "Session | None" = None,
            turn: bool = False) -> None:
        if not chat or not line:
            return
        waiting = cls.timers.pop(chat, None)
        if waiting is not None:
            waiting.cancel()
        if turn:
            cls._run(cls._told(chat, line, pressed_in, cls._take(chat)))
            return
        cls.pending.setdefault(chat, []).append(line)
        cls.since.setdefault(chat, time.time())
        cls.timers[chat] = asyncio.get_running_loop().call_later(
            cls.WAIT, lambda: cls._run(cls._written(chat, cls._take(chat))))

    @classmethod
    def _take(cls, chat: str) -> tuple[list[str], float]:
        """The presses waiting in this thread, and when the first was made."""
        cls.timers.pop(chat, None)
        return cls.pending.pop(chat, []), cls.since.pop(chat, 0.0)

    @classmethod
    def _run(cls, work) -> None:
        task = asyncio.get_running_loop().create_task(work)
        cls.telling.add(task)
        task.add_done_callback(cls.telling.discard)

    @classmethod
    async def _written(cls, chat: str, waiting: tuple[list[str], float]) -> None:
        """Write the presses into the thread as a note, and start nothing."""
        lines, at = waiting
        if not lines:
            return
        while (running := Turns.of(chat)) is not None and running.task is not None:
            await asyncio.wait({running.task})
        # Nothing is awaited from here to the write, so no turn can start in
        # this thread in between and the note lands between two turns. The
        # chat is asked after the wait: one deleted meanwhile is not made again.
        if memory.chat(chat) is None:
            return
        note = (f"{turnmarks.NOTE} at {clock.stamp(at or time.time())} the person used "
                "the inbox card on the screen, and this was done in their mailbox: "
                + "; then ".join(lines)
                + ". Nothing was said about it, because the card already shows it and "
                "the person does not want it confirmed. This is here so you know it was "
                "done if it comes up. Do not answer this note or bring it up, and do not "
                "do any of it again.]")
        memory.add_message(chat, "user", note, note=True)

    @classmethod
    async def _told(cls, chat: str, line: str, tab: "Session | None",
                    waiting: tuple[list[str], float]) -> None:
        """A send: what was waiting written down first, then a turn about it."""
        if waiting[0]:
            # The send's own turn stands down whatever is running here anyway
            # (`Turns.start`), and doing it first is what lets what was
            # pressed before it go in ahead of it.
            await Turns.cancel(chat)
            await cls._written(chat, waiting)
        note = ("the person used the inbox card on the screen rather than asking out "
                "loud, and Rouh did this in their mailbox: " + line
                + ". Say in one short sentence what was done. Do not do any of it again.")
        await tell_thread(chat, note, pressed_in=tab)


class Pictures:
    """Pictures asked for with the picture controls, rather than in words.

    Three presses come here, all answered by the server without a model deciding
    anything (`rouh/imaging.py`): the composer switched to a picture, with the
    words typed into it and the settings beside them (`picture_make`); the
    editor's Change, with the picture, the area painted on it and what should be
    there instead (`picture_edit`); and More like this, which is an edit with no
    area and no words (`picture_edit` with `variation`).

    Each is written into the chat as an exchange of its own: what the person
    asked, under their name, and the pictures, or the sentence saying why there
    are none, as Rouh's answer. So the model reads what was drawn when it is
    next asked anything, and a reload draws it all again. The question is
    written down the moment it is pressed, unless the chat is in the middle of
    a turn, and the answer once the pictures are done, after whatever turn is
    running there has ended: a row put between a tool call and its result
    breaks the conversation for every turn after it (`memory.repair_history`).

    The work is held here rather than by the tab that asked, so a reload in the
    middle of a picture does not stop it: it goes on, and lands in the chat.
    """

    working: set[asyncio.Task] = set()

    @classmethod
    def start(cls, tab: "Session", msg: dict) -> None:
        task = asyncio.get_running_loop().create_task(cls._run(tab, msg))
        cls.working.add(task)
        task.add_done_callback(cls.working.discard)

    @staticmethod
    async def to_chat(chat: str, message: dict, *, skip: "Session | None" = None) -> None:
        """One message to every tab standing in a chat, or keeping it beside the
        one on screen on its strip of forks, the same as a turn (`Turn.tabs`).

        Petar, 29 September 2026 (fr_762a21c0ccc1): "I tried generating images
        but they don't get generated." He asked for four in a task's chat and
        slid to its fork while they were drawn. The page keeps the chat slid
        away from as it was and holds what arrives for it (`forkHold` in
        app.js), but only a tab standing in the chat was sent the pictures, so
        the kept chat came back with its empty frames still saying Drawing,
        for good, and the four pictures were kept on the server and never
        shown.
        """
        message = dict(message, chat=chat)
        for tab in [s for s in list(Hub.sockets)
                    if not s.closed and (s.session_id == chat or chat in s.beside)]:
            if tab is skip:
                continue
            with contextlib.suppress(Exception):
                await tab.send(message)

    @classmethod
    async def _run(cls, tab: "Session", msg: dict) -> None:
        chat = tab.session_id
        rid = str(msg.get("rid") or "")[:40]
        set_id = imaging.new_set()

        async def send(message: dict) -> None:
            await cls.to_chat(chat, dict(message, rid=rid))

        try:
            if not chat:
                raise imaging.ImageFailed("Open a chat first, so the picture has somewhere "
                                          "to go.")
            provider = imaging.provider_for(config, str(msg.get("provider") or ""))
            ask, question, extra = await asyncio.to_thread(cls._ask, msg, chat, provider)
            if msg.get("type") == "picture_make":
                # The words typed are read with the conversation before them, so
                # "now make it blue" keeps what was settled (`imaging.with_conversation`).
                # Read before the ask is written down, so it is not read twice.
                before = await asyncio.to_thread(memory.history, chat, imaging.CONTEXT_MESSAGES)
                ask = await imaging.with_conversation(ask, before, who=tab.me, session_id=chat)
        except imaging.ImageFailed as exc:
            await send({"type": "pictures", "set": set_id, "state": "failed", "said": exc.said})
            return
        except Exception as exc:                   # noqa: BLE001 - said, never left drawing
            log.exception("a picture could not be asked for")
            await send({"type": "pictures", "set": set_id, "state": "failed",
                        "said": f"That picture could not be asked for: {exc}"})
            return
        # The ask, on every other screen of the chat, as the person's own words:
        # the tab that pressed has drawn it already.
        await cls.to_chat(chat, {"type": "transcript_add", "role": "user",
                                 "text": Turn._plain(question),
                                 "attachments": attachments.markers_in(question),
                                 "ts": time.time()}, skip=tab)
        asked = None
        if Turns.of(chat) is None:
            asked = memory.add_message(chat, "user", question)
            # A chat that was only a draft is a chat now, and the rail says so.
            after_a_turn(chat)
        try:
            with llmlog.about(purpose="picture", session_id=chat):
                answer = await imaging.draw(provider, ask, config, store=files, chat=chat,
                                            send=send, set_id=set_id, extra=extra)
        except imaging.ImageFailed as exc:
            answer = [{"type": "text", "text": imaging.said_failed(exc)}]
        await cls._written(chat, question, answer, asked)

    @staticmethod
    def _ask(msg: dict, chat: str, provider) -> tuple:
        """What the press asks for, the question to write down, and what the
        pictures are to say about themselves besides."""
        kind = msg.get("type")
        extra: dict = {}
        if kind == "picture_make":
            ids = [str(i) for i in (msg.get("references") or [])[:imaging.MOST] if i]
            found, _missing = files.resolve(chat, ids)
            pictures = [r for r in found if r.get("media_type") in imaging.EDITABLE]
            ask = imaging.ask_from(msg, provider=provider, editing=False)
            ask.references = [imaging.source_from(files.read(r), name=r["name"], id=r["id"])
                              for r in pictures]
            return ask, attachments.stored_content(found, ask.prompt), extra

        # An edit: of a picture in this chat, or one shown in it from the chat
        # it came from (a fork's), which is what reading it back could show.
        where = str(msg.get("source_chat") or chat)
        if where != chat and memory.chat(where) is None:
            raise imaging.ImageFailed("That picture is not in a chat any more.")
        source = files.get(where, str(msg.get("source") or ""))
        if source is None:
            raise imaging.ImageFailed("That picture is not there any more.")
        # The copy the editor worked on, when the picture itself would not do:
        # too big, or a photo the browser had to turn the right way up. Always
        # uploaded into this chat, beside the area painted on it.
        image = files.get(chat, str(msg.get("image") or "")) if msg.get("image") else source
        if image is None:
            raise imaging.ImageFailed("The picture to change did not arrive. Try again.")
        if image is not source:
            files.mark(image, {"kind": "work", "from": source["id"]})
        variation = bool(msg.get("variation"))
        said = dict(msg)
        if variation:
            said["prompt"] = imaging.variation_prompt((source.get("made") or {}).get("prompt")
                                                      or "")
        ask = imaging.ask_from(said, provider=provider, editing=True)
        ask.variation = variation
        if variation:
            ask.title = imaging.variation_title(source)
        ask.source = imaging.source_from(files.read(image), name=image["name"],
                                         id=source["id"])
        if msg.get("mask"):
            mask = files.get(chat, str(msg["mask"]))
            if mask is None:
                raise imaging.ImageFailed("The area to change did not arrive. Try again.")
            files.mark(mask, {"kind": "mask", "from": source["id"]})
            ask.mask = files.read(mask)
            imaging.check_mask(ask.mask, ask.source)
            imaging.area_model(provider, ask)
            extra["mask"] = mask["id"]
        if where != chat:
            extra["from_chat"] = where
        preview = files.get(chat, str(msg.get("preview") or "")) if msg.get("preview") else None
        if preview is not None:
            preview = files.mark(preview, {"kind": "area", "from": source["id"]}) or preview
        shown = (attachments.marker(preview, {"kind": "area", "from": source["id"]})
                 if preview is not None else
                 attachments.marker(source, {"kind": "ref"}))
        words = "More like this" if variation else ask.prompt
        return ask, [shown, {"type": "text", "text": words}], extra

    @staticmethod
    async def _written(chat: str, question: list, answer: list, asked: int | None) -> None:
        """The exchange, written down once no turn is running in the chat."""
        while (running := Turns.of(chat)) is not None and running.task is not None:
            await asyncio.wait({running.task})
        # Nothing is awaited from here to the writes, so no turn can start in
        # between. A chat deleted meanwhile is not made again.
        if memory.chat(chat) is None:
            return
        if asked is None:
            asked = memory.add_message(chat, "user", question)
        memory.add_message(chat, "assistant", answer, root=asked)
        after_a_turn(chat)


class Session:
    """One browser tab.

    What is on this screen and what this microphone heard. The answer being
    written is deliberately not here: a turn belongs to the thread it was asked
    in (`Turn`), and this tab may walk away from it, be closed, or never have
    been the tab that asked.
    """

    def __init__(self, ws):
        #: The tab's socket, as the websocket consumer hands it in
        #: (`rouh/web/consumers.py`): something with `send_text` and
        #: `send_bytes`, and nothing else is asked of it.
        self.ws = ws
        #: Who is on this socket. Put here by the endpoint below rather than
        #: read out of the context each time, so anything answering for this
        #: tab has the person in its hand: their own settings are keyed by it
        #: (`settings.py`), and a query that forgot whose would be exactly the
        #: bug `tenancy.py` exists to refuse.
        self.me: Identity | None = None
        self.session_id = ""
        #: The other chats laid out beside this tab's on its strip of forks
        #: (`rouh/forks.py`), whose turns this tab is shown as well as its
        #: own (`Turn.tabs`). Set wherever the page is told the strip.
        self.beside: frozenset[str] = frozenset()
        #: The far end of this tab's strip of forks: the deepest fork it has
        #: laid out to the right of its chat, or its chat itself. The tab's own,
        #: like its chat, and changed by nothing another tab does
        #: (`forks.strip`, `switch_chat`).
        self.tip = ""
        #: The newest `ask` this tab has sent: the page numbers every message
        #: that moves it to a chat or changes its strip. Every message about
        #: the tab's chat and strip carries the one it was worked out after
        #: (`asked`), so the page can tell one that is behind what it did.
        self.asked = 0
        self.capturing = False
        self.buffer = bytearray()
        #: The last state sent down this socket. Read by `state_now`, which is
        #: how a page that missed the end of a turn is put right.
        self.shown_state = "idle"
        self.live: LiveEars | None = None
        self.live_open: asyncio.Task | None = None
        #: When the last utterance ended and when its words came back, for the
        #: one line in the log that says how long the transcriber took. Nothing
        #: to do with `rouh/turnmarks.py`, which is what the model writes.
        self.turn_times: dict = {}
        #: What the person has said that has not been answered yet. The browser
        #: hears where a sentence ends and not where a thought does, so every
        #: utterance joins this rather than becoming a question of its own, and
        #: the whole of it is what the model is asked each time. Emptied the
        #: moment a turn writes those words down (`rouh/turnmarks.py`).
        self.pending: list[str] = []
        #: The clock armed when the model said they had not finished asking.
        #: When it runs out, what there is is answered anyway.
        self.waiting: asyncio.Task | None = None
        self.voice_replies = config.voice_replies
        self.closed = False
        #: Whether the person is dictating: press to start, press to finish.
        #: While it is on, nothing they pause on ends their turn, so nothing
        #: waits on a clock either - Finish is what answers.
        self.dictating = False
        #: Whether this tab has the Live browser open, which is what decides
        #: whether its screen is sent here (`browsing.Desk`).
        self.web_watching = False
        #: And the shape of the box it draws the picture in, which the
        #: browser's window is made to match.
        self.web_shape: tuple = (0, 0, False)
        # The newest tab is the one most likely being looked at, which is where
        # a finished background job announces itself.
        self.opened_at = time.monotonic()
        #: What this socket asked for that runs beside it rather than in its
        #: way: an inbox card waiting on Gmail must not hold up the microphone.
        self.errands: set[asyncio.Task] = set()

    # --- plumbing -----------------------------------------------------------

    async def send(self, message: dict) -> None:
        """One message down this socket, and nothing else.

        What a turn sends goes through here rather than through `emit`: a turn
        is one thing happening in one thread, and it is written down once and
        sent to each of the thread's tabs, not written down once per tab.
        """
        if self.closed:
            return
        with contextlib.suppress(Exception):
            await self.ws.send_text(json.dumps(message))

    async def emit(self, message: dict) -> None:
        """Something this tab is doing, to this tab."""
        OwnWork.note(message)
        await self.send(message)
        # What the person says goes past here on its way to this tab, which is
        # where the other devices in the same thread are told about it. A heard
        # sentence is the half of the transcript that has nowhere else to
        # travel; a typed one is mirrored where it is handled, because it is
        # never echoed back to the tab that typed it (see `text` below), and
        # what Rouh says is sent to every tab in the thread by the turn
        # itself.
        if message.get("type") == "stt" and message.get("final"):
            await Hub.mirror(self, "user", message.get("text") or "")

    async def send_audio(self, chunk: bytes) -> None:
        # Voice replies off means no voice, from the moment it is switched
        # off. `_speak_loop` stops asking for any more of it; this is the
        # sentence already synthesised and on its way, which is dropped rather
        # than played (14 September 2026).
        if self.closed or not self.voice_replies:
            return
        with contextlib.suppress(Exception):
            await self.ws.send_bytes(chunk)

    async def state(self, value: str, turn_id: int = 0, share: bool = True) -> None:
        """Tell this tab what Rouh is doing, and say which turn it is about.

        This is the tab's own state - listening, and the idle that follows
        something that was not a turn. What a turn is doing is said by the turn
        (`Turn.say_state`), to every tab in its thread.

        `turn_id` is carried so the page can tell the end of the turn it is
        showing from the end of one that was replaced while it was not looking.
        `share` is off for an answer to a page that asked: one tab saying "I am
        not doing anything" must not put out the light for a turn another tab
        is in the middle of.
        """
        self.shown_state = value
        if share:
            # The core of the picture shows what Rouh is doing, and a turn
            # running somewhere is what it is doing whatever this tab says
            # about itself.
            own_state(value)
        message = {"type": "state", "value": value}
        if turn_id:
            message["turn_id"] = turn_id
        await self.emit(message)

    # --- the turn -----------------------------------------------------------

    @property
    def turn(self) -> "Turn | None":
        """The turn running in the thread this tab is looking at, if any."""
        return Turns.of(self.session_id)

    @property
    def turn_task(self) -> asyncio.Task | None:
        """The work of this thread's last turn, running or finished.

        The last rather than the running one, so that something holding it can
        wait for the turn to be over without having to catch the moment: a turn
        is taken off the register the instant it ends, and a caller that read
        `None` there would have nothing to wait for and no way to tell that
        from nothing having started.
        """
        turn = Turns.latest.get(self.session_id)
        return turn.task if turn is not None else None

    @property
    def turn_id(self) -> int:
        turn = self.turn
        return turn.turn_id if turn is not None else 0

    def a_turn_is_running(self) -> bool:
        """Is the thread on this screen being answered, right now?"""
        return self.turn is not None

    def state_now(self) -> str:
        """What this tab should be showing, for a page that is no longer sure.

        A page asks for this when it has had a turn on screen with nothing
        arriving for it (`get_state` below), and it is handed to every page as
        it connects. Both are the same recovery: one message the browser can
        trust more than anything it worked out for itself, so a `state: idle`
        that never arrived - because the turn was replaced, or cancelled, or
        because the socket it would have come down had already gone - cannot
        leave the Stop control and Rouh's own line on the orb lit for ever.

        The truth is the thread's, not the tab's: a page that reconnects in the
        middle of an answer is still in the middle of it, because that turn did
        not die with the socket.
        """
        turn = self.turn
        if turn is None:
            return "idle"
        return turn.state if turn.state in ("thinking", "speaking") else "thinking"

    async def start_turn(self, user_content, answer_now: bool = False,
                         slot: "memory_mod.Slot | None" = None,
                         note: bool = False, heard: str = "", tier: str = "") -> "Turn":
        """Answer this in the thread this tab is in, and hand the turn back."""
        return await Turns.start(self.session_id, user_content, asked_by=self,
                                 speak=self.voice_replies and voice.ready,
                                 answer_now=answer_now, slot=slot, note=note, heard=heard,
                                 tier=tier)

    async def ask(self, words: str, *, now: bool = False) -> None:
        """Put what the person has said to the model, pending words and all.

        Every utterance joins the pending question rather than starting one of
        its own. The browser hears where a sentence ends; it cannot hear where
        a thought does, and somebody who dictates slowly stops mid-thought for
        three to five seconds at a time. So each utterance is only a candidate
        question, and the model is the one that says whether it is a whole one
        (`rouh/turnmarks.py`).

        `now` means they have said they are done - Finish, or send - so the
        request carries the note that asks for an answer whatever state the
        words are in.

        Whatever was running is stood down first, before the pending words are
        read. A turn that commits its question in the same breath as this
        arrives would otherwise leave those words both in the conversation and
        in the pending list, and the model would be asked them twice.
        """
        await self.cancel_turn(quiet=True)
        words = (words or "").strip()
        if words:
            self.pending.append(words)
        asked = " ".join(self.pending).strip()
        if not asked:
            return
        # Said aloud, which is how a thought kept in this turn says it came (`rouh/thoughts.py`).
        thoughts.HOW.set("voice")
        await self.box_if_asked(asked)
        await self.start_turn(asked, answer_now=now, heard="voice")

    async def box_if_asked(self, words: str) -> None:
        """A message that is only "give me a box", typed or said aloud, opens the Box page on this
        screen at once, by code, before the model reads it (`rouh/boxes.py`). The turn still runs, so
        Rouh says it is open; what goes in the box never comes this way."""
        if boxes.summoned(words):
            await self.emit({"type": "box_open", "chat": self.session_id})

    async def not_finished_yet(self, unfinished: turnmarks.Unfinished) -> None:
        """The model read their words and said they had not finished asking.

        Nothing was said, nothing was shown and nothing was stored, so there is
        nothing to undo: what they have said so far is still pending and
        whatever they say next joins it. A clock is set, because a person who
        simply stopped talking has to be answered rather than left in silence -
        twenty seconds after being cut off mid-sentence, thirty after only
        announcing what they were about to say.
        """
        self.stop_waiting()
        if self.dictating:
            # They are dictating, so they have not stopped talking and no
            # amount of silence means they have. Finish is what answers.
            log.info("not finished (%s) and still dictating: no clock",
                     unfinished.mark)
            return
        log.info("not finished (%s): waiting %.0fs on %r",
                 unfinished.mark, unfinished.wait, " ".join(self.pending)[:70])
        self.waiting = asyncio.create_task(self._answer_anyway(unfinished.wait))

    async def _answer_anyway(self, wait: float) -> None:
        """Answer what there is, once the wait has run out."""
        await asyncio.sleep(wait)
        # Let go of it before answering: the answer takes the clock down on its
        # way past, and a clock cancelling itself cancels the answer with it.
        self.waiting = None
        if self.closed or not self.pending:
            return
        log.info("the wait ran out: answering %r", " ".join(self.pending)[:70])
        await self.ask("", now=True)

    def stop_waiting(self) -> None:
        """Take the clock down, because something has happened instead."""
        waiting, self.waiting = self.waiting, None
        if waiting is not None and not waiting.done():
            waiting.cancel()

    def turn_was_stopped(self, turn_id: int) -> bool:
        """Did the person stop this turn of this thread?"""
        return stopping.stops.is_stopped(self.session_id, turn_id)

    async def cancel_turn(self, quiet: bool = False) -> None:
        """Stand the turn of this tab's thread down, because it was replaced.

        The two callers are the two things allowed to end a turn early besides
        Stop: the next question, and a deliberate interruption. Nothing the
        person does with the screen comes through here - leaving the thread,
        opening a task, reloading the page - because a turn is not theirs to
        lose by looking at something else.
        """
        # Whatever the clock was going to answer, something is happening
        # instead. The pending words themselves stand: being talked over is
        # carrying a question on, not abandoning it.
        self.stop_waiting()
        await Turns.cancel(self.session_id)
        if self.live is not None:
            with contextlib.suppress(Exception):
                await self.live.close()
            self.live = None
        if not quiet:
            await self.state("listening")

    async def chat_row_action(self, act: str, chat_id: str, msg: dict) -> dict:
        """Pin or rename a chat, down the path a chat already has.

        The row menu on a search result offers the same five things for every
        type, and for a chat these two are the ones this file has had since the
        chats moved onto their own table: a title goes through
        `conversations.rename`, which is what puts the emoji on the front of
        it. Calling the store directly from a menu would be a second writer for
        a chat, and there is one. Deleting is `delete_object`, which every
        cross on the page goes through and which takes what the chat owns.
        """
        if not chat_id:
            return {"ok": False, "why": "There is no such chat."}
        if act == "pin":
            on = bool(msg.get("on", True))
            if memory.pin_chat(chat_id, on) is None:
                return {"ok": False, "why": "There is no such chat."}
            await announce_chats()
            return {"ok": True, "pinned": on}
        if act == "rename":
            title = " ".join(str(msg.get("title") or "").split())[:200]
            if not title:
                return {"ok": False, "why": "A name cannot be empty."}
            if not memory.rename_chat(chat_id, title):
                return {"ok": False, "why": "There is no such chat."}
            await announce_chats()
            return {"ok": True}
        return {"ok": False, "why": f"A chat is not {act}d here."}

    # --- messages -----------------------------------------------------------

    async def _on_search(self, msg: dict) -> None:
        from . import switches
        from .tenancy import speaker
        # The box over everything finds Rouh's own pages too, by their names
        # and the words people use for them (`rouh/genes`); a box that
        # only picks a task, such as the one a fork is detached into, does not.
        org = getattr(speaker(), "org_id", None) or None
        places = None if msg.get("box") else (lambda name: switches.on(name, org))

        def _search(q: str, kind: str):
            # And the shared genes in the organisation's lab (`rouh/genelab.py`).
            from . import genelab

            shared = genelab.shared_manifests(org) if places is not None else []
            return searching.search(q, kind=kind, places=places, shared=shared)
        got = await asyncio.to_thread(
            _search, str(msg.get("q") or "")[:400], str(msg.get("kind") or searching.ALL))
        # `box` says which box on the page asked, and comes back with
        # the answer: the search over everything, or the one a fork is
        # detached into a task from (`detachAsk`).
        await self.emit(dict(got, type="search_results",
                             gen=int(msg.get("gen") or 0),
                             box=str(msg.get("box") or "")[:20]))

    async def _on_search_labels(self, msg: dict) -> None:
        # The numbers for the list the box shows before anything is typed,
        # which the page draws from the chats it already has and so cannot
        # number itself (`searching.labels`).
        ids = msg.get("ids") if isinstance(msg.get("ids"), list) else []
        got = await asyncio.to_thread(
            searching.labels, str(msg.get("kind") or "chat"),
            [str(i)[:200] for i in ids[:200]])
        await self.emit({"type": "search_labels", "kind": str(msg.get("kind") or "chat"),
                         "labels": got})

    async def _on_task_refs(self, msg: dict) -> None:
        # The task numbers an answer on the page names, each to be drawn as
        # its icon and name, a link to it (`searching.refs`, `taskRefs`).
        numbers = msg.get("numbers") if isinstance(msg.get("numbers"), list) else []
        got = await asyncio.to_thread(
            searching.refs, [str(n)[:20] for n in numbers[:searching.REFS_MOST]])
        await self.emit({"type": "task_refs",
                         "asked": [str(n)[:20] for n in numbers[:searching.REFS_MOST]],
                         "refs": got})

    async def _on_find_object(self, msg: dict) -> None:
        # A tab opened at `/?open=chat:<id>`. The address names one object
        # and this turns it back into the same instruction a result row
        # carries, so a new tab and a press on a row go down one path.
        # As long as an address may be, because a note two folders down a
        # step is a longer name than any task (`addressing.inside`).
        found = await asyncio.to_thread(
            searching.find_one, str(msg.get("kind") or ""),
            str(msg.get("id") or "")[:addressing.LONGEST])
        await self.emit({"type": "object_found", "ok": found is not None,
                         "row": found,
                         "why": "" if found else "It is not there any more."})

    async def after_ready(self) -> None:
        """Everything the handshake no longer carries, straight after it, as its own messages.

        Each is built on a thread and all of them at once, and each is sent as
        the message of its own the page already takes when it changes: the
        chats and folders, the tasks and projects, the runs, the workspace's
        tasks, the notices under the bell, the Thoughts count and the decisions count. They go in
        that order whatever order they finish in, because the page draws a
        run's owner from the projects and a chat's place from the folders.
        The work tree is not here: the page asks for it on `ready`.
        """
        if self.closed:
            return
        me = self.me
        session, tip = self.session_id, self.tip
        mark = tab_mark(self)
        began = time.monotonic()
        took: dict[str, float] = {}

        async def timed(name: str, work):
            try:
                return await work
            finally:
                took[name] = time.monotonic() - began

        # In the lane kept for work nobody is waiting on (`dbwork.later`): the
        # page's own next requests - the canvas's cards, a press - come first. Not
        # held for a turn, though: they are this page's, and its lists.
        with dbwork.later(wait=False):
            jobs = [
                asyncio.create_task(timed("chats", asyncio.to_thread(chat_snapshot, session, tip))),
                asyncio.create_task(timed("objects", asyncio.to_thread(objects_snapshot))),
                asyncio.create_task(timed("runs", task_list())),
                asyncio.create_task(timed("workspace", asyncio.to_thread(workspace_tasks))),
            ]
            if me is not None:
                jobs.append(asyncio.create_task(timed("notices", asyncio.to_thread(notices.listing, me))))
                jobs.append(asyncio.create_task(timed("thoughts", asyncio.to_thread(thoughts.counts, me))))
                # The count on Now and on the Decisions row: a tab that comes back after its
                # socket dropped (a phone put away, a deploy) missed every count told meanwhile,
                # and until 4 November 2026 kept the one it had for good.
                jobs.append(asyncio.create_task(timed("decisions", asyncio.to_thread(decisions.counts, me))))

        def said(i: int, what: dict) -> dict | None:
            got = what
            if isinstance(got, BaseException):
                log.warning("after the handshake, part %d could not be read: %s", i, got)
                return None
            if i == 0:
                # Only if the tab is still where it was: a press since then
                # moved it, and that move sent the lists of its own.
                if self.session_id != session:
                    return None
                if tab_mark(self) == mark:
                    self.beside = strip_ids(got.get("forks") or {})
                return dict(got, type="chats", asked=mark[2])
            if i == 1:
                return dict(got, type="objects")
            if i == 2:
                # The whole list, which is the truth: a card for a run the
                # server has no row for is one left over from before a restart.
                return {"type": "tasks", "tasks": got, "whole": True}
            if i == 3:
                return {"type": "workspace", "tasks": got}
            if i == 4:
                return got
            if i == 5:
                return {"type": "thoughts", **got}
            return {"type": "decisions", **got}

        for i, job in enumerate(jobs):
            try:
                got = await job
            except Exception as exc:  # noqa: BLE001 - one list that fails must not stop the rest
                got = exc
            message = said(i, got)
            if message is not None and not self.closed:
                await self.emit(message)
        if time.monotonic() - began > SLOW_LISTS:
            log.warning("the lists after a handshake took %.1fs: %s", time.monotonic() - began,
                        ", ".join(f"{k} {v:.1f}s" for k, v in sorted(took.items(), key=lambda kv: kv[1])))

    async def handle_text(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        kind = msg.get("type")
        ask = msg.get("ask")
        if isinstance(ask, int) and not isinstance(ask, bool) and ask > self.asked:
            self.asked = ask

        if kind == "hello":
            # The chat this tab is in, which is its own: the page says which
            # one it was showing - after a dropped socket, a reload, or an
            # address that names one - and is put back into it. Another tab
            # in another chat is left alone (fr_349273a9377e). A page that
            # names none, or one that is gone, opens on the chat the person
            # opened last. A tab that connects does not stand any other tab
            # down - the person carries a phone and leaves a desktop open,
            # and neither should go dead because of the other.
            asked = str(msg.get("chat") or "")[:200]
            self.session_id = (asked if await asyncio.to_thread(chat_is_there, asked)
                               else await asyncio.to_thread(memory.ensure_session))
            # And the strip of forks it had laid out around that chat, which
            # is the tab's own as well (`forks.strip`): a socket that went and
            # came back, or a page reloaded at an address that names one, lays
            # out exactly the strip it had.
            self.tip = await asyncio.to_thread(
                forks.tip_for, self.session_id, str(msg.get("strip") or "")[:200])
            # The time zone the page is on, which is the person's clock for
            # every time Rouh says or works out from now on (`clock.zone`).
            if self.me is not None and msg.get("tz"):
                await asyncio.to_thread(clock.remember, self.me, msg.get("tz"))
            # The conversation first, and only the conversation (23 October
            # 2026). Until then `ready` was everything the page draws - every
            # chat, every task and project, every run, the workspace, the tree,
            # the two version marks - built one piece after another, 714 KB
            # on the first Rouh, and the page showed not one message until all of it
            # had come: 17 to 100 seconds a morning, by the log. So `ready` is
            # what the conversation needs, and the lists follow it as the
            # messages of their own the page already takes (`after_ready`).
            # The version marks are not read at all: the page has drawn
            # nothing from them since 13 October 2026, and reading them was
            # up to four seconds of git and of a socket to the one program.
            head, (transcript, older) = await asyncio.gather(
                asyncio.to_thread(conversation_snapshot, self.session_id, self.tip),
                asyncio.to_thread(memory.transcript_page, self.session_id, TRANSCRIPT_PAGE),
            )
            # A tab that opens on a strip of forks is shown the turns of every
            # chat of it, as a tab that moved onto one is (`Turn.tabs`).
            self.beside = strip_ids(head["forks"])
            await self.emit(
                {
                    "type": "ready",
                    "asked": self.asked,
                    "session_id": self.session_id,
                    "voice": voice.ready,
                    # Whether this machine wants the voice on, which is not the
                    # same question as whether it is configured above. A page
                    # that has never had the button pressed on it takes this;
                    # one that has keeps its own answer. Until this was sent,
                    # `ROUH_VOICE_REPLIES` could not reach anybody: the page
                    # sent its own default back on `ready` and overwrote it
                    # about a hundred milliseconds after loading, every time.
                    "voice_reply": self.voice_replies,
                    "ears": ears.ready,
                    # What this tab should be showing. A page that lost its
                    # socket in the middle of an answer used to come back with
                    # the Stop control on screen and nothing that ever arrived
                    # afterwards about the turn it was waiting on, because that
                    # turn died with the socket. It does not die with the
                    # socket any more, so this says whichever is true: the
                    # thread is being answered, or it is not.
                    "state": self.state_now(),
                    # And if it is, the turn itself: its number, its state and
                    # the words it has written so far, so a reload in the
                    # middle of an answer draws what there is of it and then
                    # goes on receiving the rest (`Turn.picture`).
                    "running": (Turns.of(self.session_id).picture()
                                if Turns.busy(self.session_id) else None),
                    "tools": tools.names(),
                    # What the picture controls offer: each provider, whether
                    # it is set up here, and what each of its models can do
                    # (`imaging.options`).
                    "pictures": imaging.options(config),
                    "transcript": transcript,
                    # Where the page before it ends, for reading back what came
                    # before as the person scrolls up to it (`/api/transcript`),
                    # or "" when this is all of it.
                    "older": older,
                    # Which chat this transcript belongs to, its row, its forks
                    # and General's id (`conversation_snapshot`). The lists of
                    # every chat and folder come next, in `chats`.
                    **head,
                    # Every conflict waiting on the person, as the decision card
                    # the page draws with four buttons on it. On connect rather
                    # than only when one arrives, because a question is a file
                    # on disk: one asked before this tab opened, or before the
                    # last restart, is still being asked.
                    "conflicts": ConflictFeed.blocks(),
                    # Which build of the page is being served. The files the
                    # page is made of are stamped with this and cached under it
                    # for a year, on purpose, so an open tab keeps working
                    # through a restart - and so a tab that was open before a
                    # deploy is still the old page afterwards, with nothing on
                    # it saying so. On 20 September a change to the orb's
                    # memory rings went live while the person was watching the
                    # orb, and his screen drew the new server's numbers in the
                    # old page's colours. Every connect says which build is
                    # being served now, and a page that is not it knows it is
                    # behind, so the run that deployed it carries a Reload on
                    # its notice (`noteBuild` in app/notices.js).
                    "assets": ASSETS,
                    # When this Rouh started, and whether the one before it went
                    # on purpose, so a page that missed the close of a deploy -
                    # asleep, or in the background - still says Evolving rather
                    # than Reconnecting when it comes back (`rouh/restarts.py`).
                    **restarts.said(),
                    # A deploy of the one program that is running this instant,
                    # so a tab opened or reloaded in the middle of one shows it
                    # working rather than an idle button (`one_deploy.py`).
                    "one_deploying": deployer.busy,
                    # The orb as this person set it, which is theirs rather
                    # than this browser's. Null when they have never saved any,
                    # which is what tells a page that the copy in its own local
                    # storage is worth sending up instead of being thrown away;
                    # an empty object is the opposite and means they put
                    # everything back to the design (`settings.py`).
                    "orb": user_settings.get(self.me, settings_mod.ORB),
                    # Whether this person's Live browser is open, and who has
                    # it, so a page opened in the middle of an errand shows
                    # the row that opens it (`browsing.py`).
                    "browser": browser_desk.picture(self.me),
                    "now": time.time(),
                }
            )
            # And what this tab is showing, which is idle unless the thread it
            # has landed in is being answered. It used to be "idle" flatly, and
            # that was a lie the moment a turn stopped dying with its socket: a
            # page reloaded in the middle of an answer drew the half of it that
            # had been written and then put the Stop control away again, one
            # message later, because the server said nothing was happening.
            await self.state(self.state_now())
            # Beside the tab's own messages rather than in front of them: a
            # press made the moment the conversation is drawn is answered at
            # once, not after every list has been read.
            self.errand(self.after_ready())

        elif kind == "ping":
            await self.emit({"type": "pong"})

        # A press or a swipe on a notice: drawn while the person was looking, put
        # away, opened, or dismissed. Whatever it was, every other tab of theirs
        # is told, so a notice swiped away on the phone leaves the desk too.
        elif kind == "notice":
            if self.me is not None:
                what = str(msg.get("act") or "")
                ids = msg.get("ids") if isinstance(msg.get("ids"), list) else []
                changed = await asyncio.to_thread(notices.act, self.me, ids, what)
                if changed and what != "seen":
                    await notices.tell(self.me)

        # The orb as this person has set it. Sent when a slider is let go of
        # and when the panel is closed, and saved against them rather than
        # against this browser, which is what keeps it across a refresh, a
        # restart and the phone in their pocket.
        #
        # Nothing here is trusted to mean anything: `settings.py` takes a flat
        # object of finite numbers and refuses everything else, and what each
        # number means, and the range it is allowed, is the page's own - the
        # design is in `app.js` beside the sliders that draw it, and `orbSane`
        # there clamps every value on the way back in. There is no answer to
        # this message: the page already has what it sent, and an error the
        # person can do nothing about is not worth a banner.
        elif kind == "set_orb":
            await asyncio.to_thread(
                user_settings.put, self.me, settings_mod.ORB, msg.get("cfg"))

        # --- the chats ------------------------------------------------------
        #
        # One endless conversation was one context window that only ever grew.
        # What the person says is now split into chats, each with its own
        # history and its own cards, and one of them is active: the voice, the
        # transcript and the canvas all follow it. Which one that is belongs to
        # the tab, so two tabs can be two conversations side by side; the list
        # of chats is still one, and every tab is told when it changes.

        elif kind == "list_chats":
            asked = self.asked
            await self.emit(dict(await asyncio.to_thread(chat_snapshot, self.session_id, self.tip),
                                 type="chats", asked=asked))

        elif kind == "new_chat":
            # A draft, not a row: the chat is written by the first thing said
            # in it, so New chat pressed and left leaves nothing behind
            # (`conversations.open_draft`). With a task on it, it is Start chat
            # on that task's page: a new conversation about the task.
            task = str(msg.get("task") or "").strip()
            if task:
                await start_task_chat(self, task)
            else:
                await switch_chat(memory.draft_chat(
                    folder_id=str(msg.get("folder") or "") or None), self)

        elif kind == "answer_chat":
            # An answer from the question box on a task's page, about to be
            # sent: into the chat the task already has, never a new one
            # beside it, and a new one only when it has none. Moved there,
            # every tab is told by the switch and the page sends the answer
            # on it; already there, only this tab is told, and sends it now.
            # Nowhere to put it, the page is told that too, so it says so
            # rather than holding the words for the next chat opened.
            chosen, moved = await answer_task_chat(self, str(msg.get("task") or "").strip())
            if not moved:
                await self.emit({"type": "answer_chat", "chat": chosen})

        elif kind == "note_to_parent":
            # Send to the task, in a subtask's own chat: a decision or a note
            # written against the task above it, listed on that task's page
            # and put in front of Rouh in its chats (`rouh/subtasknotes.py`).
            # Only this tab is told: nothing anybody else is looking at moved.
            got = await asyncio.to_thread(
                subtasknotes.send, str(msg.get("chat") or "") or self.session_id,
                str(msg.get("text") or "")[:subtasknotes.MAX_NOTE * 2])
            await self.emit(dict(got, type="note_sent"))

        elif kind == "open_chat":
            # `strip` is the far end of the strip of forks to lay out with it:
            # an address that names one, or a fork's mark (`forks.strip`).
            # Left out, a chat on the tab's strip keeps the strip, and any
            # other chat is opened alone.
            strip = msg.get("strip")
            await switch_chat(str(msg.get("id") or ""), self,
                              tip=str(strip)[:200] if isinstance(strip, str) else None)

        elif kind == "peek_chat":
            # A chat beside this one on its strip of forks, whole, so the page
            # draws its card with the same hand it draws the chat itself with,
            # and sliding onto it finds nothing left to redraw (fr_60918f90d0bb).
            peek = await asyncio.to_thread(chat_peek, str(msg.get("id") or ""), self.beside)
            if peek:
                await self.emit(peek)

        # --- threads ---------------------------------------------------------
        #
        # A thread is a chat, and a chat whose subject is a numbered workspace
        # task is that task. So these two are the whole of the rail's top half:
        # open one, and tie a loose one to a task.

        elif kind == "open_thread":
            await open_thread(self, str(msg.get("id") or ""), str(msg.get("task") or ""),
                              alone=bool(msg.get("alone")), redraw=bool(msg.get("redraw")))

        elif kind == "promote_thread":
            # "This one is work." A loose conversation becomes a numbered task:
            # it takes the next free number, keeps every message, and its
            # folder is written into the workspace from the row.
            #
            # And it takes what it drew with it: the `owns` rows move from the
            # chat to the task, and the numbered steps are written out from
            # them. That is the thing the old model could not do - what a card
            # belonged to was decided when it was drawn and never looked at
            # again.
            chat_id = str(msg.get("id") or "") or self.session_id
            if chat_id == memory_mod.CONVERSATION:
                # The one thread that is always there is where anything with no
                # home yet is said. Numbering it would file every loose remark
                # under one task and leave nowhere to say the next thing.
                await self.emit({
                    "type": "error",
                    "message": "General is the thread that is always there, and it is "
                               "never numbered. Start a chat for this and make that a task.",
                    "fatal": False})
            elif await promote_thread(chat_id) is None:
                await self.emit({"type": "error",
                                 "message": "There is no such chat to make a task of.",
                                 "fatal": False})

        elif kind == "file_card":
            # "Put that one on the record." One card, written into the task
            # that owns it as its next numbered step, because the person
            # pressed the button on it. A card drawn in a chat a task owns
            # used to be filed the moment it was drawn; nothing does that any
            # more, and this is the asking (`rouh/artifacts.py`).
            got = await file_card_as_step(str(msg.get("id") or ""))
            if got is None:
                await self.emit({"type": "error", "fatal": False,
                                 "message": "There is no such card to file."})
            else:
                # The card either way, so the chip on it says where it went and
                # opens it - and so that a press that could not be honoured
                # leaves a button that can be pressed again rather than one
                # stuck on its way somewhere. `card_filed` and not `ui`: the
                # card has not changed and must not move in the conversation.
                got.pop("filed_into", None)
                await self.emit({"type": "card_filed", "spec": got})
                if not got.get("filed"):
                    await self.emit({
                        "type": "error", "fatal": False,
                        "message": "There is nowhere to file it: this thread is not "
                                   "a task, or the workspace is not on this machine. "
                                   "Make the chat a task and everything it drew goes "
                                   "in with it."})

        elif kind == "card_ask":
            # A press on the buttons at the foot of a card that asks before
            # something leaves Rouh - Save to iCloud on a contact, today
            # (`rouh/asking.py`). The press names the card and the answer and
            # nothing else: what is done is read out of the card as the
            # server stored it, and only for the person it is for.
            await self.card_asked(msg)

        elif kind == "card_pick":
            # Research, pressed on one of the people a LinkedIn search drew
            # (`rouh/linkedin.py`). The press names the card and which one on
            # it and nothing else: whose profile that is, is read out of the
            # card as the server stored it. Beside the socket, like the inbox
            # card's asks, because a harvest waits on LinkedIn for ten seconds
            # or so and the microphone is on this same socket.
            self.errand(self.card_picked(msg))

        elif kind == "card_compose":
            # A save or a press of Send on a card the person writes in
            # (`rouh/composing.py`). What they typed comes up with it, because
            # the whole point of that card is that it is theirs to change;
            # what is *done* with it is read out of the card as the server
            # stored it, and only for the person it belongs to.
            await self.card_composed(msg)

        elif kind in ("picture_make", "picture_edit"):
            # The picture controls: the composer switched to a picture, the
            # editor's Change, and More like this (`Pictures`). Answered by
            # the server, with no model deciding anything, and held apart from
            # this tab, because a picture takes long enough to be reloaded
            # through.
            Pictures.start(self, msg)

        elif kind == "card_inbox":
            # The inbox card at work (`rouh/inbox.py`): list the inbox, open a
            # message, archive it, mark it, fill in a reply, send one. Beside
            # the socket rather than in it, because every one of those waits
            # on Gmail and the microphone is on this same socket.
            self.errand(self.card_inboxed(msg))

        elif kind == "contact_note":
            # The relationship or the online research on a contact card,
            # changed on the card itself (`rouh/people.py`). Rouh's own, never
            # iCloud's, and only ever the signed-in person's own contacts.
            await self.contact_noted(msg)

        elif kind == "pin_thread":
            # Mark a loose conversation as one to keep in view, or take the
            # mark off. Nothing is deleted or archived on a clock any more, so
            # this is a mark and not a reprieve.
            chat_id = str(msg.get("id") or "") or self.session_id
            if memory.pin_chat(chat_id, bool(msg.get("on", True))) is not None:
                await announce_chats()

        elif kind == "rename_chat":
            # An empty name puts a chat back to untitled, which also puts it
            # back in the way of the automatic title.
            if memory.rename_chat(str(msg.get("id") or ""), str(msg.get("title") or "")):
                await announce_chats()

        elif kind == "move_chat":
            if memory.move_chat(str(msg.get("id") or ""),
                                str(msg.get("folder") or "") or None):
                await announce_chats()

        elif kind == "delete_chat":
            # The same delete as everything else, named for the one surface
            # that asked for it first. A tab loaded before 22 September 2026
            # still sends this, so it goes on meaning what it says - down the
            # one path, which now takes the conversation, its messages, and
            # everything the conversation owns.
            await self.delete_object("chat", str(msg.get("id") or ""))

        elif kind == "new_folder":
            # On its own, or inside another project: a project may own a
            # project, which is half of the nesting the hierarchy is made of.
            # A task may never own one and `objects.attach` is what says so.
            memory.new_folder(str(msg.get("name") or ""), str(msg.get("owner") or ""))
            await announce_chats()
            await announce_objects()

        elif kind == "rename_folder":
            # Down `owning.rename` like every other rename on this page, so a
            # project that is a folder of the workspace has its sidecar
            # written with the new title and the row and the folder never
            # disagree about what it is called.
            if memory.rename_folder(str(msg.get("id") or ""),
                                    str(msg.get("name") or "")):
                await announce_chats()
                await announce_objects()
                await _announce_workspace()

        elif kind == "delete_folder":
            # A project, down the same one path as everything else. It
            # takes what is in it - the person asked for that in those words -
            # and this message is the name the chat list used before there was
            # one delete for every type, kept so a tab loaded before
            # 22 September 2026 goes on working.
            #
            # One thing under it is let go of rather than taken, because it is
            # not this project's to destroy: General, the thread that is
            # always there, which comes out of the project and stays
            # (`owning.KEEP`). A folder of the workspace **is** taken, folder
            # and all, which is what the row coming back on the next read used
            # to make impossible (`objecttree.erase`).
            await self.delete_object("project", str(msg.get("id") or ""))

        # --- search, over all five and the files -------------------------------
        #
        # One box over the whole screen, and one list under it: the chats, the
        # tasks, the projects, the artifacts, the runs and the files the person
        # uploaded, ranked against each other rather than in sections
        # (`rouh/searching.py`, `rouh/uploads.py`). The pills
        # narrow what came back; they are not five different questions, which
        # is why the counts for every pill come with every answer.
        #
        # `gen` is the page's own counter and comes straight back on the
        # answer. A search box is typed into faster than a query returns, and
        # this is how the page throws away the answer to the word before the
        # one in the field now.

        elif kind == "search":
            await self._on_search(msg)

        elif kind == "search_labels":
            await self._on_search_labels(msg)

        elif kind == "task_refs":
            await self._on_task_refs(msg)

        elif kind == "find_object":
            await self._on_find_object(msg)

        elif kind in ("pin_object", "rename_object"):
            # Keep one, or rename one, for any of the five, from the row menu
            # on a search result. **Delete is not here**: it is `delete_plan`
            # and `delete_object` below, which every cross on this page already
            # goes through, so a search result deletes with the same cascade
            # and the same confirmation as everything else.
            #
            # A chat's two are the ones this file already had, because
            # `conversations.py` is a chat's only writer; the other four are
            # `owning.py`, which is where the rest of Rouh reaches the objects.
            what = str(msg.get("kind") or "")
            ident = str(msg.get("id") or "")
            # A task's own page names it by its folder (`owning.task_at`).
            if what == "task" and not ident and msg.get("folder"):
                ident = await asyncio.to_thread(owning.task_at, str(msg.get("folder")))
            act = kind.split("_")[0]
            if what == "chat":
                got = await self.chat_row_action(act, ident, msg)
            elif act == "pin":
                got = owning.pin(what, ident, bool(msg.get("on", True)))
            else:
                got = owning.rename(what, ident, str(msg.get("title") or ""))
            if what != "chat" and got.get("ok"):
                await announce_objects()
                if what in ("task", "project"):
                    await _announce_workspace()
                # A project's own row reaches the sidebar in the chat
                # snapshot, which is where both kinds of project are listed,
                # so a pin or a rename on one has to go out down that message
                # as well or the rail draws yesterday's mark. A task's name is
                # in it too, on every chat the task owns (`owned_by`), which
                # is what the head of its conversation is called.
                if what == "project" or (what == "task" and act == "rename"):
                    await announce_chats()
                await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
            await self.emit(dict(got, type="object_changed", act=act,
                                 kind=what, id=ident))

        elif kind == "list_tasks":
            await self.emit({"type": "tasks", "tasks": await task_list()})

        elif kind == "mark_seen":
            # The person opened a task or a run that had stopped, so the red
            # dot on its tab has nothing left to say about that one. Sent on
            # the press rather than worked out here, because only the page
            # knows what was pressed; what "stopped" means, and when a mark is
            # cleared again, are `objects.STOPPED` and `_unseen_again`.
            #
            # Archiving is not here. A run is archived from three places - this
            # file, the one program's own socket, and a job stopping itself -
            # and all three end at `objects.update_run`, which marks it seen
            # there so no caller can forget to.
            #
            # `deep` is the dot itself being pressed rather than the row: that
            # item and everything under it, which is the only honest way to
            # clear a dot that stands for something further down. A project is
            # always deep, because that is all its dot has ever meant.
            #
            # `ids` is the one press that is not a press: landing on the runs
            # list is looking at every run the tab's dot was counting, which is
            # one act about the whole column. One message and one broadcast for
            # it, rather than one of each per run for one glance.
            what = str(msg.get("kind") or "")
            ident = str(msg.get("id") or "")
            deep = bool(msg.get("deep"))
            many = msg.get("ids")
            if what == "run" and isinstance(many, list):
                ids = [str(x) for x in many[:MARK_SEEN_MOST] if x]
                if ids:
                    await asyncio.to_thread(owning.mark_runs_seen, ids)
                    await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
            elif what in ("task", "run", "project") and ident:
                got = await asyncio.to_thread(owning.mark_seen, what, ident, deep)
                if got.get("ok"):
                    if what == "run":
                        await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
                    else:
                        await announce_objects()

        elif kind == "archive_task":
            # Every row of the task list can be put out of the way and brought
            # back, and the page asks here for every one of them. Rouh's own
            # jobs keep their flag in Rouh's database beside the job.
            #
            # A run of the one program keeps its flag in the program, and Rouh
            # asks the program over its own connection, which the program has
            # paired. The page used to ask the program itself, and a phone the
            # program had never paired got "The one program has not let this
            # browser in" instead of the run going away (fr_e40fdd64f4a8). The
            # program's answer comes back through OneFeed like every other
            # change to a run, which is what moves the card on every tab.
            #
            # Archiving a job that is still running stops it as well, so the
            # broadcast below carries the new status too and the card says
            # "Stopped" rather than going on claiming to be running.
            job_id = str(msg.get("id") or "")
            on = bool(msg.get("on", True))
            if job_id == self_update.ID:
                # The deploy card. There is no terminal behind it and no
                # checkout to leave alone, so its button is a dismissal: the
                # record goes, and every tab drops the card.
                self_update.forget()
                await Hub.broadcast({"type": "tasks_forgotten", "ids": [job_id]})
                await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
            elif runs.is_one_run(job_id):
                try:
                    got = await one.ask("archive", run=job_id, on=on)
                except Exception as exc:
                    log.warning("the one program would not archive %s: %s", job_id, exc)
                    await self.emit({"type": "error", "message": f"Could not archive it: {exc}",
                                     "fatal": False})
                    # The page moved the card on the press; this puts it back.
                    await self.emit({"type": "tasks", "tasks": await task_list()})
                else:
                    if got.get("run"):
                        await OneFeed.on_runs([got["run"]], False)
            elif crew is None:
                await _drop_unknown_task(job_id)
            else:
                try:
                    row = await crew.archive(job_id, on)
                except UnknownCrewmate:
                    await _drop_unknown_task(job_id)
                except Exception as exc:
                    log.warning("could not archive %s: %s", job_id, exc)
                    await self.emit({"type": "error", "message": f"Could not archive it: {exc}",
                                     "fatal": False})
                else:
                    told = {"type": "task", "id": job_id, "archived": on}
                    # A card keeps the line it was last given, because the task
                    # list carries no line and the live messages do. A job that
                    # has just been stopped would therefore go on saying
                    # "started" underneath the word Stopped, so it is told the
                    # same closing line stop_task gives.
                    if on and row is not None and row.get("status") == "killed":
                        told.update(status="killed", detail="stopped")
                    await Hub.broadcast(told)
                    await Hub.broadcast({"type": "tasks", "tasks": await task_list()})

        # --- the five objects, and the one thing that changes ownership -------
        #
        # A run, a chat and a task are each made on their own and owned by
        # nothing, and that is the default rather than a half-made state. What
        # changes is `attach`, which is one upsert against the partial unique
        # index in `objects.py` and is the same operation for every pair the
        # ranking allows: project > task > chat > run > artifact. An illegal
        # pair is refused by the store, in its own sentence, and the refusal
        # comes back here rather than being hidden by a list the page filters.

        elif kind == "list_objects":
            await self.emit(dict(await asyncio.to_thread(objects_snapshot), type="objects"))

        elif kind == "new_task":
            # A task like any other: the one create path writes its row, its
            # number and its folder, and it then files itself into the project
            # it belongs in, exactly as a promoted conversation does. It used
            # to be a bare row with no folder at all, which the task browser
            # showed anyway - as a line nothing could open and nothing could
            # move (`owning.new_task`).
            made = owning.new_task(str(msg.get("title") or ""))
            if made is None:
                await self.emit({"type": "error", "fatal": False,
                                 "message": "A task could not be made."})
            else:
                await announce_objects()
                await _announce_workspace()
                NewTasks.maybe_file(made.id)

        elif kind == "start_run":
            # A run on its own: a brief, a workspace and a policy, and nothing
            # else. Nobody's, unless the dialog named an owner. The same
            # `starting.start` the four surface tools are presets over, so a
            # run started from here is a run of exactly the same kind, told
            # apart by the same two fields and nothing more.
            #
            # And no conversation asked for it, so none goes with it. The box
            # is opened from the sidebar, not from a chat, and whichever chat
            # this tab happens to be standing in is not where it was asked:
            # handing that chat along filed the run's report, its card and its
            # words under that chat's task. On 23 September 2026 a question
            # about a path, typed into this box while the films chat was open,
            # came back as a card on a task about films, and one
            # about updating Claude Code as a card on task 29. A run
            # nobody's conversation started reports in General
            # (`runs.reports_to`), and belongs to a task only when somebody
            # says so.
            owner = (str(msg.get("owner_type") or ""), str(msg.get("owner_id") or ""))
            # Which agent, and for Codex who pays: its ChatGPT subscription
            # unless the person picked the OpenAI API key in the box.
            # Only a run of the one program can be Codex; a worker here is
            # Claude Code whatever the box said.
            agent = str(msg.get("agent") or "").strip().lower()
            agent = "codex" if agent == "codex" and msg.get("policy") == "one" else ""
            billing = "api" if agent == "codex" and msg.get("billing") == "api" else ""
            try:
                got = await starting.start(
                    brief=str(msg.get("brief") or ""),
                    title=str(msg.get("title") or ""),
                    workspace=str(msg.get("workspace") or ""),
                    policy=str(msg.get("policy") or ""),
                    agent=agent, billing=billing,
                    cfg=config, crew=crew, one=one,
                    owner=owner if all(owner) else None,
                    emit=self.emit)
            except starting.CannotStart as exc:
                await self.emit({"type": "run_started", "ok": False, "why": str(exc)})
            else:
                await self.emit(dict(got, type="run_started", ok=True))
                await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
                await announce_objects()
                TreeFeed.poke()

        elif kind == "attach":
            # And detach, which is the same message with no owner on it: an
            # orphan is legal, so taking an owner away is a thing a person may
            # simply do, and nothing else happens when they do.
            what = (str(msg.get("kind") or ""), str(msg.get("id") or ""))
            owner_kind = str(msg.get("owner_kind") or "")
            owner_id = str(msg.get("owner_id") or "")
            if owner_kind and owner_id:
                got = owning.attach(what[0], what[1], owner_kind, owner_id)
            else:
                got = owning.detach(what[0], what[1])
            await self.emit(dict(got, type="attached", kind=what[0], id=what[1]))
            if got.get("ok"):
                await announce_objects()
                await announce_chats()
                await Hub.broadcast({"type": "tasks", "tasks": await task_list()})

        elif kind in ("delete_plan", "delete_object"):
            # Deleting, and it is one path for all five types: the person asked
            # for that on 22 September 2026 in those words - "We should be able
            # to delete items of all types - chats, runs, tasks, projects.
            # Delete cascades if there are relationships."
            #
            # Two messages, always in this order, and the first is not optional:
            #
            #   delete_plan     what would go, named and counted, for the
            #                   confirmation. Nothing is written.
            #   delete_object   it goes.
            #
            # They are the same walk of the same `owns` edges (`owning.plan`
            # and `owning.remove`), so the sentence the person agreed to and
            # the write that follows cannot be about different things.
            what = str(msg.get("kind") or "")
            which = str(msg.get("id") or "")
            # A task's own page names it by its folder (`owning.task_at`), and
            # the plan says the id back, which is what the delete then names.
            if what == "task" and not which and msg.get("folder"):
                which = await asyncio.to_thread(owning.task_at, str(msg.get("folder")))
            if kind == "delete_plan":
                await self.emit(dict(
                    await asyncio.to_thread(owning.plan, what, which),
                    type="delete_plan", kind=what, id=which,
                    folder=str(msg.get("folder") or "")))
            else:
                await self.delete_object(what, which)

        elif kind == "list_under":
            # What one object owns, walked down the ranking: a task's runs,
            # their artifacts - a run's diff is one of them - and the cost of
            # all of it added up. Nothing is copied anywhere; this is the same
            # `owns` rows `attach` writes, read the other way round.
            await self.emit({"type": "under", "kind": str(msg.get("kind") or ""),
                             "id": str(msg.get("id") or ""),
                             "under": owning.under(str(msg.get("kind") or ""),
                                                   str(msg.get("id") or ""))})

        elif kind == "list_workspace":
            await self.emit({"type": "workspace", "tasks": await asyncio.to_thread(workspace_tasks)})

        elif kind == "fork_chat":
            # A copy of a conversation, up to a point, to take another way
            # without losing this one (memory.fork_chat). The copy is made
            # active, so the page lands in it.
            from_chat = str(msg.get("id") or self.session_id)
            made = memory.fork_chat(from_chat, upto=msg.get("upto"))
            if made is not None and artifacts.enabled():
                # The canvas too. A branch whose screen is empty is not the
                # same conversation seen again.
                await asyncio.to_thread(
                    artifacts.fork, from_chat, memory.task_of(from_chat), made["id"],
                    until=made.get("branched_ts") or 0.0,
                    became=made.get("became") or {})
            if made is None:
                await self.emit({"type": "error",
                                 "message": "There is no such chat to branch.",
                                 "fatal": False})
            else:
                events.emit("chat.forked", who=self.me, actor="person", source="web",
                            chat_id=made["id"], object_type="chat", object_id=made["id"],
                            props={"from_chat": from_chat, "way": "branch"})
                # This tab moves into the branch, the same as opening any
                # other chat: the branch is where its conversation now is.
                await switch_chat(made["id"], self)

        elif kind == "conflict_answer":
            # The person picked one of the four on a conflict card, by clicking
            # or by pressing its number. Any signed-in tab may answer: there is
            # one person and the card was drawn on every one of their screens.
            got = await ConflictFeed.answer(str(msg.get("id") or ""), msg.get("choice"))
            if not got.get("ok"):
                # Said rather than swallowed, or a button that does nothing
                # looks like a broken button.
                await self.emit({"type": "conflict_gone", "id": str(msg.get("id") or ""),
                                 "why": got.get("why") or "it has already been answered"})

        elif kind == "permission_answer":
            # A gated tool asked the person something and they pressed a
            # button (rouh/permissions.py). Any signed-in tab may answer:
            # there is one conversation across all of them, and the question
            # was drawn on every one.
            answered = tools.gate.answer(str(msg.get("id") or ""),
                                         bool(msg.get("allow")))
            if not answered:
                # It had already been answered, or it timed out while they
                # were reading it. Said rather than swallowed, or a button
                # that does nothing looks like a broken button.
                await self.emit({"type": "permission_gone",
                                 "id": str(msg.get("id") or "")})

        elif kind == "get_tree":
            await self.emit(
                {"type": "tree", "tree": tree_snapshot(), "now": time.time()}
            )

        elif kind in ("browser_watch", "browser_take", "browser_give", "browser_stop",
                      "browser_input", "browser_forget"):
            # The Live browser, from the person: watching it, taking it,
            # handing it back, stopping it, and what they click and type while
            # they have it. Theirs alone, by who is on this socket
            # (`browsing.Desk.from_tab`).
            await browser_desk.from_tab(self, msg)

        elif kind == "set_mode":
            if "voice_reply" in msg:
                self.voice_replies = bool(msg["voice_reply"])
            # Deliberately NOT `ready`. The browser re-asserts its settings every
            # time it sees `ready`, so answering a settings change with `ready`
            # made the two sides talk to each other for ever: one round trip per
            # 50 milliseconds, no error, no visible symptom except traffic.
            await self.emit({"type": "mode", "voice_reply": self.voice_replies})

        elif kind == "speech_start":
            # Deliberately does NOT cancel the turn in flight.
            #
            # The microphone opening is not the same as the person speaking. A
            # cough, a door or a keyboard opens it too, and cancelling here meant
            # any noise while Rouh was thinking killed the answer for good: the
            # turn died, nothing replaced it, and the only trace was three user
            # messages in a row with no reply between them.
            #
            # Real barge-in is not lost by this. The browser sends an explicit
            # `interrupt` when it hears speech over the top of Rouh talking,
            # and a finished utterance that actually contains words replaces the
            # turn in `speech_end` anyway. So cancellation now needs either a
            # deliberate interruption or something that was actually said.
            self.buffer = bytearray()
            self.capturing = True
            if not self.a_turn_is_running():
                await self.state("listening")
            if config.use_realtime_stt and ears.ready:
                # The socket is opened in the background and audio starts
                # buffering into it immediately. Awaiting the connect here
                # instead would throw away the first words of the sentence,
                # which is how a Bulgarian question became a Russian one.
                self.live = LiveEars(config, heard=_heard_names)
                self.live_open = asyncio.create_task(self.live.open(self._on_partial))

        elif kind == "speech_end":
            self.turn_times = {"speech_end": time.monotonic()}
            self.capturing = False
            pcm = bytes(self.buffer)
            self.buffer = bytearray()
            if msg.get("discard"):
                # The browser decided that was too short to be speech. Throw the
                # audio away without paying for a transcription that will come
                # back empty, and leave any running turn alone.
                live, self.live = self.live, None
                if live is not None:
                    with contextlib.suppress(Exception):
                        await live.close()
                self.live_open = None
                if not self.a_turn_is_running():
                    await self.state("idle")
                return
            live, self.live = self.live, None
            if live is not None and self.live_open is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(self.live_open), timeout=6)
                except Exception as exc:
                    log.warning("realtime transcription never opened: %s", exc)
            self.live_open = None

            if live is not None:
                worked = False
                try:
                    text = await live.finish()
                    worked = live.worked
                except Exception as exc:
                    log.warning("realtime transcription failed at commit: %s", exc)
                    text = ""
                # Only fall back when the socket actually broke. An empty result
                # from a working transcriber means there were no words in that
                # audio, which is the correct answer to a cough or a door.
                # Re-sending it to the batch transcriber returned things like
                # "[background noise]", and that was then answered as speech.
                if not text and not worked and pcm:
                    log.info("realtime transcription unavailable; using the batch one")
                    text = await self._transcribe_batch(pcm)
                elif not text:
                    log.info("heard %.1fs of audio with no words in it", len(pcm) / 32000)
            elif pcm:
                if not self.a_turn_is_running():
                    await self.state("thinking")
                text = await self._transcribe_batch(pcm)
            else:
                text = ""

            if not text:
                # Nothing was said. Leave whatever is running alone, and only
                # reset the light if nothing is running.
                if not self.a_turn_is_running():
                    await self.state("idle")
                return
            timing = getattr(self, "turn_times", None) or {}
            if timing:
                timing["heard"] = time.monotonic()
                log.info(
                    "turn: heard in %dms -> %r",
                    int((timing["heard"] - timing["speech_end"]) * 1000), text[:70],
                )
            await self.emit({"type": "stt", "text": text, "final": True})
            # Its length and how long it took to say, never its words (`rouh/events.py`).
            events.emit("chat.message_sent", who=self.me, actor="person", source="voice",
                        chat_id=self.session_id, object_type="chat", object_id=self.session_id,
                        count=len(text), duration_ms=len(pcm) / 32)
            # Not a question yet, only more of one. `ask` joins it to whatever
            # is already waiting and lets the model say whether that is a whole
            # request. `finish` is the browser saying the person pressed
            # Finish, which is them saying they are done.
            await self.ask(text, now=bool(msg.get("finish")))

        elif kind == "get_state":
            # The page has had a turn on screen with nothing arriving for it
            # and is asking whether there is really one running. Answered for
            # this tab alone: the picture of what Rouh is doing as a whole
            # belongs to whoever is actually doing it, and a quiet tab must not
            # put its light out (`state`, `share`).
            await self.state(self.state_now(), turn_id=self.turn_id, share=False)

        elif kind == "interrupt":
            await self.cancel_turn()

        elif kind == "dictation":
            # Press to start, press to finish. The browser holds the utterance
            # open, so nothing the person pauses on reaches here at all; what
            # this is for is the clock. Somebody who is dictating has not
            # stopped talking, so nothing is answered on a timer while it is
            # on - Finish is what answers, and it answers the whole of it.
            self.dictating = bool(msg.get("on"))
            if not self.dictating:
                self.stop_waiting()
            await self.emit({"type": "dictation", "on": self.dictating})

        elif kind == "text":
            # An answer sent from the box at the top of a waiting task's page
            # says so: which task, what it asked and what was answered. It is
            # written down before the turn, so the page says it was answered
            # and the rail stops marking the task, whatever the turn does
            # (`rouh/answering.py`).
            said = msg.get("answers")
            if isinstance(said, dict):
                await self.answered(said)
            await self.typed((msg.get("text") or "").strip(), msg.get("attachments"),
                             steer=str(msg.get("steer") or "")[:64])

        elif kind == "dismiss_question":
            # Dismiss, on the question box at the top of a task's page: the
            # question closed without an answer. Nothing is said to anybody
            # and the task is left as it is; it is written down, so the page
            # keeps it folded and the rail stops marking the task as waiting
            # on the person (`rouh/answering.py`).
            await self.answered(msg, dismissed=True)

        elif kind == "fork":
            await self.fork_and_ask(msg)

        elif kind == "close_fork":
            await close_fork(str(msg.get("id") or ""), self)

        elif kind == "detach_fork":
            await detach_fork(str(msg.get("id") or ""), str(msg.get("task") or ""),
                              self.emit)

        elif kind == "retry":
            await self.answer_again(msg)

        elif kind == "pick_version":
            await self.step_version(msg)

        elif kind == "card_version":
            await self.card_version(msg)

        elif kind == "ui_event":
            # What they pressed, described for the model. The press is theirs;
            # these words are not, so they are never drawn as a message of
            # theirs (`Turn.note`).
            note = f"[the person interacted with the screen: {json.dumps(msg)[:300]}]"
            await self.start_turn(note, answer_now=True, note=True)

    # --- an answer to a waiting task --------------------------------------

    async def answered(self, said: dict, *, dismissed: bool = False) -> None:
        """Write down an answer from a task's page, or its question dismissed
        there, and tell every tab.

        The task is the folder Rouh's own page read off the canvas, never one
        the framed page named (`taskChat` and `taskDismiss` in app.js), and
        the chat is the one this is being said in. Nothing here can fail the
        message itself: an answer that cannot be written down is still sent,
        and said in the log."""
        try:
            task = await asyncio.to_thread(
                lambda: answering.record(
                    str(said.get("task") or ""), str(said.get("asked") or ""),
                    str(said.get("answer") or ""), self.session_id, dismissed=dismissed))
        except Exception:
            log.exception("the answer to %s could not be written down", said.get("task"))
            return
        if task:
            await announce_objects()
            await _announce_workspace()

    # --- typing, and typing into a fork ------------------------------------

    async def typed(self, text: str, attached, *, uploaded_in: str = "",
                    steer: str = "") -> None:
        """What was typed into the box and sent, with the files attached to it.

        `uploaded_in` is the chat the files went up to, when that is not the
        one this is being asked in: the question that opens a fork was typed
        in the chat it forks from.

        Sent while an answer is being written in this chat, it does not stop
        that answer. It waits on the turn, and the model reads it at its next
        step - once the tool it is running comes back, before it decides what
        to do next - so the person can add to what it is doing, change its
        course, or tell it to stop (Petar, 17 October 2026, fr_9fdbf628eb75:
        "add messages during a response and it can be taken into
        consideration, instead of waiting till the last tool call"). If the
        answer ends first, it is the next question (`Turn.follow_on`).
        `steer` is the page's own name for the message, which it drew waiting
        and moves into place when it is read (`steer_taken`).
        """
        # Words said out loud and not yet answered are a question the model is
        # still deciding is whole, and what is typed now finishes it: that one
        # is stood down and asked again with these words, as it always was.
        steering = Turns.of(self.session_id) is not None and not self.pending
        # Anything said out loud and not yet answered goes with it. Somebody
        # who starts a sentence aloud and finishes it in the box has asked
        # one question, and pressing send is them saying it is whole.
        #
        # Whatever was running is stood down before those words are read,
        # for the reason `ask` gives: a turn that writes the question down
        # as this arrives would otherwise leave it in both places.
        if not steering:
            await self.cancel_turn(quiet=True)
        said = " ".join(self.pending).strip()
        self.pending.clear()
        # Files attached to this message. They were uploaded before it was
        # sent, so what arrives here is a list of ids; the bytes are already
        # on disk under the conversation they were attached in, which is this
        # one unless the message is the first of a fork (`fork_and_ask`).
        found, missing = files.resolve(uploaded_in or self.session_id, attached)
        if missing:
            await self.emit({
                "type": "error",
                "message": f"{len(missing)} attached file(s) could not be found any more, "
                           "so they were left out. Attach them again.",
                "fatal": False,
            })
        if not text and not found and not said:
            return
        if found:
            # Given, now that they are sent: searchable from here on, found
            # under their own names (`rouh/uploads.py`). And a .docx, a
            # spreadsheet or a deck has its words read before the model is
            # asked about it, which started when it was uploaded and is
            # nearly always done; a few seconds at most are waited here.
            uploads.take_in(found, ("chat", self.session_id))
            await asyncio.to_thread(uploads.ready, found)
        whole = f"{said} {text}".strip() if said else text
        drawn = attachments.markers_in(attachments.stored_content(found, whole))
        # The tab that typed it drew it itself; every other device is told
        # here, because a typed message is deliberately never echoed back
        # as `stt` and so has nothing else to travel on. One that waits for
        # the answer being written is drawn waiting there too.
        steer = steer or ("s" + uuid.uuid4().hex[:12] if steering else "")
        await Hub.mirror(self, "user", whole, drawn, steer=steer if steering else "")
        # No `stt` echo here. The browser already put what was typed on
        # screen; sending it back produced the same message twice.
        # `stt` means "this is what I heard", which only applies to speech.
        # Its length, never its words (`rouh/events.py`).
        events.emit("chat.message_sent", who=self.me, actor="person", source="web",
                    chat_id=self.session_id, object_type="chat", object_id=self.session_id,
                    count=len(text), props={"files": len(found), "spoken_chars": len(said)})
        # Typed, unless all of it was said aloud first; and "thought:" or "idea:" at its start
        # is kept as a thought before the model reads it (`rouh/thoughts.py`).
        heard = "voice" if said and not text else "typed"
        thoughts.HOW.set(heard)
        await thoughts.keep_prefixed(self.me, whole, self.session_id)
        # "Give me a box" opens one on this screen before the model reads it (`rouh/boxes.py`).
        await self.box_if_asked(whole)
        content = attachments.stored_content(found, whole) if found else whole
        if steering:
            # Asked again, with nothing awaited before the answer: the turn may
            # have ended while the files were being read.
            running = Turns.of(self.session_id)
            if running is not None and running.wait_in(content, sid=steer, text=whole,
                                                       files=drawn, by=self):
                return
        turn = await self.start_turn(content, answer_now=True, heard=heard)
        if steer:
            # The page drew it waiting for an answer that has ended since:
            # it is this turn's question, and the mark comes off it.
            with contextlib.suppress(Exception):
                await turn.emit({"type": "steer_taken", "question": True, "root": None,
                                 "taken": [{"id": steer, "message_id": None, "text": whole,
                                            "attachments": drawn}]})

    async def fork_and_ask(self, msg: dict) -> None:
        """Send as a fork: a side chat off this one, asked this, beside it.

        The press of Fork beside Send, or Ctrl+Shift+Enter. A new fork of the
        chat the person is in is made (`forks.make`), every tab moves into it
        the way opening any chat moves them, and what was typed is asked
        there, of a model that has read the chat it came off up to this moment
        and whose answer never goes back into it. The chat it came off keeps
        its place on the strip, to the left.

        A chat with nothing in it has nothing to fork, and the page says so
        rather than asking it somewhere the person did not mean: the words go
        back into the box (`fork_refused`).

        `root` is Fork on the box a message is being edited in: the edited
        words asked in a fork that comes off just above that message, with
        the files it was asked with, which is what Send there does in place
        (`answer_again`) taken to a side chat. The message and its answer stay
        as they were.
        """
        parent = str(msg.get("from") or "") or self.session_id
        text = (msg.get("text") or "").strip()
        attached = msg.get("attachments")
        uploaded_in, before = parent, None
        if msg.get("root") is not None:
            point = await asyncio.to_thread(memory.fork_point, parent, msg.get("root"))
            if point is None:
                await self.emit({"type": "error", "fatal": False,
                                 "message": "That message is not in this conversation "
                                            "any more, so it cannot be forked from."})
                return
            before, attached = point["root"], point["files"]
            uploaded_in = point["uploaded_in"] or parent
        if not text and not attached:
            return
        made = await asyncio.to_thread(forks.make, parent, before)
        if made is None:
            refused = {"type": "fork_refused", "text": text,
                       "why": "There is nothing in this chat to fork from yet. "
                              "Send it as it is, and fork from the answer."}
            if before is not None:
                refused.update(root=before, why="This is the first message in this chat, so "
                                                "there is nothing above it to fork from. "
                                                "Send it to ask it again here.")
            await self.emit(refused)
            return
        events.emit("chat.forked", who=self.me, actor="person", source="web", chat_id=made,
                    object_type="chat", object_id=made,
                    props={"from_chat": parent, "way": "fork"})
        await switch_chat(made, self, tip=made)
        await self.typed(text, attached, uploaded_in=uploaded_in)

    # --- a card that asks ------------------------------------------------------

    async def card_asked(self, msg: dict) -> None:
        """Answer a press on a card's ask block, and tell its thread.

        The card is drawn again as it now reads - saved, or not saved - on
        every tab standing in the thread it belongs to, this one included. The
        thread is then told, as a note from Rouh's own software, so the
        assistant says it is done and knows not to do it a second time; that
        is a turn of its own, and it stands down whatever was being said
        there, because the person has just answered the question it was
        asking. A press that could not be honoured comes back as
        `card_ask_said`, with why, rather than doing nothing: a button that
        does nothing looks like a broken button.
        """
        from .tenancy import speaker

        card = msg.get("card")
        got = await asking.answer(card, str(msg.get("choice") or ""), speaker(),
                                  root=config.assistant_repo, given=msg.get("given"))
        if not got.ok or got.spec is None:
            await self.emit({"type": "card_ask_said", "card": card,
                             "why": got.why or "That could not be done.",
                             "again": got.again})
            return
        await self.redraw_card(got.spec, got.chat)
        for spec in got.others:
            await self.redraw_card(spec, got.chat, in_place=True)
        await tell_thread(got.chat, got.note, pressed_in=self)

    # --- somebody picked off a list of people ------------------------------

    async def card_picked(self, msg: dict) -> None:
        """Harvest the person pressed on a LinkedIn search card, and tell its thread.

        The harvest is the server's own, so what the button does never waits on
        a model deciding to do it. The profile is drawn as a card of its own in
        the thread the list was drawn in, the list is drawn again in place with
        that one marked, on every tab standing in that thread, and the thread is
        told in a note from Rouh's own software, with the profile in it, so the
        assistant says who this is and does not harvest them a second time.
        Whatever could not be done comes back as `card_pick_said`, with why,
        under the list.
        """
        from .tenancy import speaker

        card, pick = msg.get("card"), msg.get("pick")

        def said(why: str, again: bool = False) -> dict:
            return {"type": "card_pick_said", "card": card, "pick": pick, "why": why,
                    "again": again}

        if tools.apify is None:
            await self.emit(said("LinkedIn research is not set up on this machine."))
            return

        async def keep(spec: dict, chat: str) -> dict | None:
            with memory_mod.answering_in(chat):
                _number, drawn = await asyncio.to_thread(tools._keep, spec)
            return drawn

        got = await linkedin.pick(card, pick, speaker(), tools.apify, draw=keep,
                                  root=config.assistant_repo)
        if got.ok and got.already:
            await self.emit(said(f"Already researched: it is card {got.already}."))
            return
        if not got.ok or got.drawn is None:
            await self.emit(said(got.why or "That could not be done.", got.again))
            return
        drawn = [{"type": "ui", "spec": got.picker, "in_place": True}] if got.picker else []
        drawn.append({"type": "ui", "spec": got.drawn})
        for message in drawn:
            message = dict(message, chat=got.chat)
            for tab in [s for s in list(Hub.sockets)
                        if not s.closed and s.session_id == got.chat]:
                await tab.send(message)
        await tell_thread(got.chat, linkedin.picked_note(got), pressed_in=self)

    async def redraw_card(self, spec: dict, chat: str, *, in_place: bool = False) -> None:
        """A card as it now reads, on this tab and every other tab in its thread.

        `in_place` keeps it where it is in the conversation rather than
        bringing it to the end, for a card that changed because another was
        pressed: a draft turned over to Not sent when its sibling went.
        """
        drawn = {"type": "ui", "spec": spec}
        if in_place:
            drawn["in_place"] = True
        else:
            drawn["spec"] = place_card(chat, spec, None)
        await self.emit(drawn)
        for other in [s for s in list(Hub.sockets)
                      if s is not self and not s.closed and s.session_id == chat]:
            await other.emit(drawn)

    # --- what Rouh knows about a contact, changed on the card ------------------

    async def contact_noted(self, msg: dict) -> None:
        """Keep a relationship or a piece of research typed on a contact card.

        Petar, 25 September 2026: the two fields are to be "visible and
        editable wherever contacts are shown". The card is drawn again as it
        now reads, as a new version of itself, on every tab standing in this
        thread; a change that could not be kept comes back as
        `contact_note_said`, with why, and the card keeps what was typed.
        """
        from .tenancy import speaker

        card = msg.get("card")
        got = await asyncio.to_thread(
            contact_note, card, str(msg.get("contact") or ""), str(msg.get("field") or ""),
            msg.get("value"), speaker())
        if isinstance(got, str):
            await self.emit({"type": "contact_note_said", "card": card, "why": got})
            return
        # In place: the card was changed where it is, so it stays there.
        drawn = {"type": "ui", "spec": got, "in_place": True}
        await self.emit(drawn)
        for other in [s for s in list(Hub.sockets)
                      if s is not self and not s.closed and s.session_id == self.session_id]:
            await other.emit(drawn)

    # --- a card the person writes in -------------------------------------------

    async def card_composed(self, msg: dict) -> None:
        """Keep what they have written in a card, or send it.

        A save answers this tab alone and redraws nothing: the person is
        typing, and a card redrawn under their cursor would take the sentence
        away from them. A send redraws the card on every tab standing in its
        thread, now saying Sent and with nothing left to press, and tells the
        thread in a note from Rouh's own software so the assistant says it has
        gone and does not send it a second time.

        Whatever could not be done comes back as `card_compose_said`, with
        why, and the card stays exactly as they have it: a send that failed
        must never cost somebody the email they had just written.
        """
        from .tenancy import speaker

        card = msg.get("card")
        what = str(msg.get("do") or composing.SAVE)
        edits = msg.get("edits")
        # The files named on the card, found where they were uploaded, so the
        # card can say what is going with the message. What is sent is read
        # from disk again when it is sent, never from the page.
        named = []
        for one in ((edits or {}).get("attachments") or [])[:20]:
            ident = str((one or {}).get("id") if isinstance(one, dict) else (one or ""))
            record = files.get(self.session_id, ident) if ident else None
            if record is not None:
                named.append({"id": record["id"], "name": record["name"],
                              "size": record["size"]})
        got = await composing.press(card, what, edits, speaker(), files=named,
                                    root=config.assistant_repo)
        if got.saved:
            await self.emit({"type": "card_compose_saved", "card": card, "at": time.time()})
            return
        if not got.ok or got.spec is None:
            await self.emit({"type": "card_compose_said", "card": card,
                             "why": got.why or "That could not be done.",
                             "again": got.again})
            return
        await self.redraw_card(got.spec, got.chat)
        for spec in got.others:
            await self.redraw_card(spec, got.chat, in_place=True)
        await tell_thread(got.chat, got.note, pressed_in=self)

    # --- the inbox on the screen ----------------------------------------------

    def errand(self, work) -> None:
        """Run something this socket asked for beside it, held until it is done."""
        task = asyncio.create_task(work)
        self.errands.add(task)
        task.add_done_callback(self.errands.discard)

    async def card_inboxed(self, msg: dict) -> None:
        """Answer one ask of an inbox card, and tell whoever should know.

        The answer goes to this tab alone, carrying the page's own `rid` so
        the card that asked is the card that hears. What changed a message -
        archived, read, unread - goes to every tab of this person as well, so
        the same inbox open on the phone loses the message too; and what was
        done in the mailbox is written into the card's thread (`InboxNotes`),
        in silence unless it was a send.
        """
        from .tenancy import speaker

        who = speaker()
        got = await inbox.press(msg, who)
        answer = {"type": "card_inbox_said", "rid": msg.get("rid"),
                  "do": str(msg.get("do") or ""), "ok": got.ok}
        if got.ok:
            answer.update(got.said)
        else:
            answer["why"] = got.why or "That could not be done."
        await self.emit(answer)
        if got.changed:
            await inboxes_hear(who, got.changed)
        for spec in got.cards:
            await self.redraw_card(spec, got.chat, in_place=True)
        if got.ok and got.note:
            InboxNotes.add(got.chat, got.note, pressed_in=self, turn=got.turn)

    # --- asking the same thing again ----------------------------------------

    async def answer_again(self, msg: dict) -> None:
        """Answer an exchange again, with the same words or with new ones.

        Retry and edit are one thing with one difference: whether `text` came
        with it. Either way the answer takes the place of the one that is there
        rather than being added to the bottom of the conversation, which is the
        whole point - re-asking by sending the same message again left the
        transcript holding the question twice with the old answer between them.

        The old try is kept. It stops being live the instant the new question
        is written down, and the arrows under the message step back to it.

        `tier` is Cheaper, Daily or Best pressed beside the "Model decision"
        line: this one answer comes from that tier, with no router.
        """
        try:
            root = int(msg.get("root"))
        except (TypeError, ValueError):
            return
        text = msg.get("text")
        if text is not None:
            text = str(text).strip()
            if not text:
                await self.emit({"type": "error", "fatal": False,
                                 "message": "An edited message cannot be empty."})
                return
        again = memory.another_try(self.session_id, root, text)
        if again is None:
            await self.emit({"type": "error", "fatal": False,
                             "message": "That message is not in this conversation "
                                        "any more, so it cannot be asked again."})
            return
        # Redo is the answer before having missed (`rouh/modeloutcomes.py`).
        with contextlib.suppress(Exception):
            await asyncio.to_thread(modeloutcomes.redo, self.session_id)
        # Whatever was running is stood down, for the same reason a typed
        # message stands it down: a turn that writes its question as this
        # arrives would leave the words in two places. Read the exchange first,
        # so a press that names nothing does not end the answer being written.
        await self.cancel_turn(quiet=True)
        # Anything they have said and not been answered stays theirs. It is not
        # part of this - they are asking an old question again, not finishing
        # the sentence they were in the middle of - so it is neither joined to
        # it nor thrown away. The clock does come down: a timer answering half
        # a sentence would cancel the retry they just asked for.
        self.stop_waiting()
        await self.start_turn(again["content"], answer_now=True,
                              slot=memory_mod.Slot(again["root"], again["version"]),
                              note=again.get("note", False), heard="typed",
                              tier=str(msg.get("tier") or ""))

    async def delete_object(self, kind: str, obj_id: str) -> None:
        """Delete one object, everything it owns, and everything that wrote out.

        The one delete path, for a chat, a run, a task or a project alike, and
        the order it goes in is the whole of it:

        1. **ask what would go**, again. The dialog asked a moment ago and the
           person agreed to that sentence, but a message can be sent by
           anything at all and a plan is the only thing that knows General may
           not go;
        2. **stop every run under it that is still going**, before its record
           is taken away. A record deleted out from under a live agent orphans
           it: every way of stopping one starts from the database, and a run
           nothing has a row for is in none of them. A worker is stopped by
           the crew, which then forgets its window, its event log and its row;
           a run of the one program is stopped by the program, on its own
           socket, because the program owns that terminal and Rouh does not;
        3. **delete the rows and sweep the disk** (`owning.remove`), which is
           one transaction for the whole subtree and then the artifacts' bytes,
           the workspace folders and their lines in the map file;
        4. **throw away each deleted chat's tape**, which is this module's own
           and has nothing to belong to once the chat is gone;
        5. **tell every tab**, all four lists at once, because a project
           deleted on the phone takes rows out of the rail, the task list, the
           owner dialog and the workspace tree on the desktop.

        A failure at step 2 is logged and never stops step 3. A terminal that
        has already gone, or a program that will not answer, must not leave the
        person with the thing they deleted still on the list.
        """
        plan = await asyncio.to_thread(owning.plan, kind, obj_id)
        if not plan.get("ok"):
            await self.emit({"type": "error", "fatal": False,
                             "message": plan.get("why") or "That cannot be deleted."})
            return
        for row in plan.get("runs") or []:
            await self._stop_and_forget_run(row)
        got = await asyncio.to_thread(owning.remove, kind, obj_id)
        if not got.get("ok"):
            await self.emit({"type": "error", "fatal": False,
                             "message": got.get("why") or "That could not be deleted."})
            return
        # Every chat that went, a fork of one of them included
        # (`owning.plan`, `rouh/forks.py`).
        for chat_id in plan.get("chats") or []:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(memory.forget_chat, chat_id)
        # And whatever was set to happen in any of them at a time: a deleted
        # goal's steps must not go on being done in General.
        if plan.get("chats") and self.me is not None:
            try:
                dropped = await asyncio.to_thread(reminders.drop_for_chats, self.me,
                                                  plan["chats"])
                if dropped:
                    log.info("dropped %d reminder(s) set in the chats that went", dropped)
                    # The rail's Reminders line says when the next one is due.
                    await timekeeper.tell(self.me)
            except Exception:
                log.exception("the reminders in the deleted chats could not be dropped")
        await self.emit(dict(got, type="deleted"))
        # A tab may be in one of the chats that just went, and every such tab
        # is put back into General, which is always there.
        if plan.get("chats"):
            gone = [tab for tab in open_tabs() if not chat_is_there(tab.session_id)]
            if gone:
                await switch_chat(memory.ensure_general(), gone)
        await announce_chats()
        await announce_objects()
        await _announce_workspace()
        await Hub.broadcast({"type": "tasks", "tasks": await task_list()})
        if got.get("counts", {}).get("run") or kind == "run":
            await Hub.broadcast({"type": "tasks_forgotten",
                                 "ids": [g["id"] for g in got.get("gone") or []
                                         if g["type"] == "run"]})
        TreeFeed.poke()

    async def _stop_and_forget_run(self, row: dict) -> None:
        """Stop one run if it is still going, and take its terminal with it.

        Never raises. Whoever owns the terminal is asked - the program for a
        run of its own, the crew for everything else - and whatever they say,
        the row is deleted after this returns.
        """
        run_id = str(row.get("id") or "")
        if not run_id:
            return
        if row.get("policy") == runs.ONE_POLICY:
            if row.get("going") and one is not None:
                try:
                    await one.ask("stop", run=run_id)
                except Exception as exc:
                    log.warning("the one program would not stop %s: %s", run_id, exc)
            return
        if crew is None:
            return
        try:
            await crew.forget(run_id)
        except Exception:
            log.exception("could not stop and forget the job %s", run_id)

    async def step_version(self, msg: dict) -> None:
        """Step an exchange back or forward through the tries it has.

        This changes the conversation and not only the picture of it: the try
        that is live is what the page draws and what the model is sent from
        here on. Nothing is deleted, and every tab in the thread is told, since
        the conversation is the person's and not the screen's.
        """
        try:
            root, version = int(msg.get("root")), int(msg.get("version"))
        except (TypeError, ValueError):
            return
        picked = memory.pick_version(self.session_id, root, version)
        if picked is None:
            await self.emit({"type": "error", "fatal": False,
                             "message": "There is no such version of that message."})
            return
        changed = [tuple(k) for k in picked.pop("changed", [])]
        if picked.pop("branched", False):
            # Another branch of the conversation: what followed this try the last
            # time it was read comes back with it, and what followed the other goes.
            await branch_redraw(self.session_id, root, changed)
            return
        said = dict(picked, type="version_picked", chat=self.session_id)
        for tab in list(Hub.sockets):
            if tab.closed or tab.session_id != self.session_id:
                continue
            await tab.send(said)
        if self not in Hub.sockets:
            await self.send(said)
        # And a card a try of this exchange revised, as this try has it.
        await branch_redraw(self.session_id, root, changed)

    async def card_version(self, msg: dict) -> None:
        """One version of a card on this screen, from the arrows on its head.

        Looking only: the card is drawn again in place as that version read, on this
        tab, and nothing is written - every version stays, and the newest is still the
        newest (`artifacts.at_version`).
        """
        try:
            card, version = int(msg.get("card")), int(msg.get("version"))
        except (TypeError, ValueError):
            return
        spec = (await asyncio.to_thread(artifacts.at_version, card, version)
                if artifacts.enabled() else None)
        if spec is None:
            await self.emit({"type": "error", "fatal": False,
                             "message": "That card has no such version."})
            return
        await self.send({"type": "ui", "spec": spec, "in_place": True})

    async def handle_bytes(self, data: bytes) -> None:
        if not self.capturing:
            return
        # The buffer is kept even when the live socket is up, so a socket that
        # dies mid-sentence can still be recovered by uploading the whole thing.
        if len(self.buffer) < config.mic_sample_rate * 2 * 60:
            self.buffer.extend(data)
        if self.live is not None:
            try:
                await self.live.send(data)
            except Exception as exc:
                log.warning("live audio send failed: %s", exc)
                with contextlib.suppress(Exception):
                    await self.live.close()
                self.live = None

    async def _on_partial(self, text: str) -> None:
        await self.emit({"type": "stt", "text": text, "final": False})

    async def _transcribe_batch(self, pcm: bytes) -> str:
        try:
            return await ears.transcribe(pcm)
        except SpeechError as exc:
            await self.emit({"type": "error", "message": str(exc)[:200], "fatal": False})
            return ""



#: The task that shares tasks with whoever outside asked for them, held so it is not collected.
_REQUESTER_SHARES: list = []


async def _shares_at_start() -> None:
    from . import requester_share

    await requester_share.keep()


_ONE_WATCH: list = []
#: The count of answers in progress, written every second (`rouh/answers_now.py`), and the turns
#: held over the last restart, answered once Rouh is up.
_ANSWERS_WATCH: list = []


async def _answer_held() -> None:
    """What the person asked while the last deploy held new turns back, answered now, in the chat
    they asked it in and as them. Nothing they typed is lost to an update."""
    from . import answers_now
    from .tenancy import Identity, speaking

    await asyncio.sleep(3)
    try:
        rows = await asyncio.to_thread(answers_now.take_held)
    except Exception:
        log.exception("the turns held over the restart could not be read")
        return
    for row in rows:
        chat, who = str(row.get("chat") or ""), row.get("who")
        if not chat or row.get("content") is None:
            continue
        try:
            me = Identity(**who) if isinstance(who, dict) else None
        except TypeError:
            me = None
        log.info("answering what was held over the restart in %s (asked %.0f s ago)",
                 chat, time.time() - float(row.get("at") or time.time()))
        try:
            with speaking(me):
                await Turns.start(chat, row["content"], asked_by=None, speak=False,
                                  note=bool(row.get("note")), heard=str(row.get("heard") or ""))
        except Exception:
            log.exception("a turn held over the restart could not be started in %s", chat)


def _attach_one(one, memory, tools, timekeeper, announce) -> None:
    """Attach to the one program as the voice: its runs, their landing, their tools."""
    if config.assistant_repo:
        # Stage 5: Rouh's assistant jobs run in the program, which lands
        # their work; what they found comes back here the way it always has.
        from .assistant_job import WorkspaceCopy
        from .one_jobs import OneLander

        OneFeed.lander = OneLander(one, memory, Hub.broadcast, announce,
                                   config.assistant_review_url,
                                   copy=WorkspaceCopy(config.assistant_repo,
                                                      config.assistant_user,
                                                      config.assistant_home),
                                   deploy=deploy_onto_a_landed_change)
        OneFeed.lander.goal_runs = timekeeper
        OneFeed.lander.telegram = tools.telegram
        OneFeed.lander.public_url = config.public_url
        OneFeed.lander.phone_done = config.phone_done_jobs
        OneFeed.lander.task_chat_changed = announce_task_chat
    # The OpenAI API key goes with it, for runs of Codex the person asks to
    # have billed to it; the program holds it in memory only. Not in the
    # containers, where the program is a worker and holds no key.
    OneFeed.start(codex_key=config.openai_api_key if config.one_gets_keys else "")
    log.info("the one program: attached as the voice, at %s", one.socket_path)


async def _attach_when_paired(one, memory, tools, timekeeper, announce, every: float = 10.0) -> None:
    while not one.configured():
        await asyncio.sleep(every)
    _attach_one(one, memory, tools, timekeeper, announce)
    tools._one_tools()
    tools._program_jobs()
    log.info("the one program paired after Rouh started; its tools are offered from now on")


async def startup() -> None:
    log.info("jarvis %s starting, at %s", BUILD, get_version()["human_readable"])
    # Every asyncio.to_thread from here on gives its database connection back
    # to the pool when it is done, instead of its thread keeping one for ever
    # (`rouh/dbwork.py`). First, before anything hands work to a thread.
    dbwork.install()
    # A deploy is the one job that cannot report its own result: the process
    # that started it is the process the restart kills. This process starting
    # is that result, so the card is finished here, before any tab can connect
    # and be told it is still working.
    self_update.on_change = _announce_tasks
    # The key the worker in another container shows Rouh's internal addresses, in the volume the
    # two share, before any run asks (`rouh/workerkey.py`; nothing where there is no worker).
    try:
        from rouh import workerkey

        workerkey.ensure()
    except OSError:
        log.warning("the key for the worker could not be made", exc_info=True)
    # The event log's writer, from the start, so its rollups are filled in every
    # minute whether or not anything has happened yet (`rouh/events.py`).
    events.start()
    # Every task made for somebody outside, shared with them to edit once: the ones made
    # before this at the first pass, each new one as it is taken in (`rouh/requester_share.py`),
    # and every task under what is ticked on a contact's page, to read (`rouh/task_access.py`).
    _REQUESTER_SHARES.append(asyncio.create_task(_shares_at_start()))
    # What each run was for, in a sentence, from here on and for the runs of
    # the last few days that have none (`rouh/runsummary.py`).
    with contextlib.suppress(Exception):
        await RunSummaries.start()
    # A one-line title for every reminder that has none (`rouh/reminder_titles.py`).
    with contextlib.suppress(Exception):
        await reminder_titles.Titles.start(timekeeper)
    if (deployed := self_update.reconcile()) is not None:
        log.info("the deploy before this one: %s (%s)",
                 deployed.get("status"), deployed.get("detail"))
    # An order Rouh submitted at a shop that takes the card on its payment page
    # afterwards, and had not paid when this process last went away: the purchase
    # that would have paid it was in the browser's memory. The owner is told plainly
    # that the shop has an unpaid order (`payments.tell_unpaid_after_restart`).
    try:
        from . import payments

        left = await payments.tell_unpaid_after_restart()
        if left:
            log.warning("%d order(s) were left unpaid by the last restart", left)
    except Exception:
        log.exception("orders left unpaid by the last restart could not be looked for")
    # Sign-ins that have run out, and refused attempts too old to count. A
    # restart is as good a moment as any and it costs one statement.
    gone = await asyncio.to_thread(auth.sweep)
    people = await asyncio.to_thread(auth.count)
    log.info("accounts=%d, dropped %d expired sign-in(s)", people, gone)
    if people == 0:
        log.warning("no accounts yet: nobody can sign in."
                    " Make one with: python manage.py account add <username> --generate")
    # The tiers and each use's tier, for the organisation a turn with nobody
    # speaking would use (`rouh/modeldefaults.py`).
    with contextlib.suppress(Exception):
        log.info("models: %s", await asyncio.to_thread(modeldefaults.said))
    # Whether OpenAI's Luna can be asked at all, in the box and as General's
    # own model. Said at every start, because the only thing that decides it
    # is a key nobody can see from here: OPENAI_API_KEY in the service's
    # environment (`rouh/luna.py`).
    log.info("luna=%s", "ready (OPENAI_API_KEY is set)" if luna_ready(config)
             else "not offered: no OPENAI_API_KEY in this service's environment")
    # What run_command runs inside. Looked at once, here, because finding out
    # means running a program and doing that on every pipeline stage would be
    # the slowest part of a spoken turn (`rouh/sandbox.py`).
    # In the containers they run in the worker instead, which looks at its own box
    # (`one/shell.py`), and server_health reads that one.
    if getattr(config, "shell_in_worker", False):
        log.info("run_command runs in the worker, in its box (one/shell.py)")
    else:
        box = await asyncio.to_thread(sandbox.Sandbox(config).look)
        sandbox.use(box)
        (log.info if box.usable else log.warning)("%s", box.said())

    # Everything that has ever been on the screen becomes an artifact row, with
    # the number it already had and the owner its thread gives it. Once, on the
    # first start after this landed; a card that is already there is skipped,
    # so a migration cut off half way finishes on the next start and nothing
    # the person can scroll back to is ever lost.
    if artifacts.enabled():
        try:
            became = await asyncio.to_thread(
                lambda: artifacts.migrate(memory.all_cards()))
            if became:
                log.info("%d card(s) of the screen history became artifacts", became)
        except Exception:
            log.exception("the screen history could not be migrated to artifacts")

    # A turn that was in flight when this process last went away. It left a
    # row behind (memory.open_turns); it becomes a sentence in that chat's
    # transcript, so a person who asked something and got nothing is told why
    # rather than being left to wonder.
    # The answers the last deploy cut at the most it waits are named by it, so those are told
    # it was an update, and after how long (`rouh/answers_now.py`). And from now on, every
    # second, the answers in progress are written where a deploy reads them before it restarts.
    from . import answers_now

    try:
        cut_by_deploy = await asyncio.to_thread(answers_now.cut_by_deploy)
    except Exception:
        log.exception("what the last deploy cut could not be read")
        cut_by_deploy = {}
    _ANSWERS_WATCH.append(asyncio.create_task(answers_now.watch()))
    answers_now.catch_stop()
    try:
        cut_short = await asyncio.to_thread(memory.mark_interrupted, cut_by_deploy)
    except Exception:
        log.exception("the interrupted turns could not be marked")
        cut_short = []
    if cut_short:
        log.info("%d turn(s) were cut short by the last restart", len(cut_short))
    answers_now.LAST_START.update(cut_short=list(cut_short), cut_by_deploy=sorted(cut_by_deploy))

    # Held (config.hold): nothing that reaches out in anyone's name is started.
    held = bool(getattr(config, "hold", False))
    if held:
        log.warning("Rouh is held (ROUH_HOLD): its page and turns work, and nothing reaches out by itself - "
                    "no reminders, night jobs, Telegram, mail, Slack, phone address or crew")
    # The phone address: its name allowed, and its client started again if the owner has it on
    # (`rouh/relay.py`). Never in the way of Rouh starting.
    try:
        from rouh import relay

        if not held:
            await relay.start()
    except Exception:
        log.exception("the phone address could not be started")

    # External MCP servers, if any are configured. Opened before the tool list
    # is logged, so the log says what Rouh really has rather than what it had
    # a moment ago. One that will not open is logged and left out.
    try:
        added = await tools.add_mcp_servers()
    except Exception:
        log.exception("the MCP servers could not be opened")
        added = []
    if added:
        log.info("mcp tools=%s", ", ".join(added))
    log.info("tools=%s", ", ".join(tools.names()))
    if config.missing():
        log.warning("not configured: %s", ", ".join(config.missing()))
    if crew is not None and not held:
        # The sweep that notices a worker whose window has gone. Every two
        # seconds, so a job that dies without a word leaves the orb about as
        # quickly as one that is stopped; each sweep is one tmux call and one
        # small query.
        await crew.start(interval=2.0)
        # Every worker already on record, into the run register, before
        # anything asks it a question. Without this Rouh would come up with an
        # empty task list until each job happened to change, and one that
        # finished last week never does.
        log.info("%d worker(s) put into the run register", crew.register_all())
        # Anything that changes a job changes the tree, and the page should see
        # it at once rather than on the next beat.
        crew.on_tree_change(TreeFeed.poke)

        def _changed(mate, event, detail):
            # The sweep runs in the background; pushing from it is what keeps a
            # card honest without anyone reloading.
            asyncio.create_task(_announce_tasks())
            # And a job that has ended has a diff, which is an artifact of its
            # own from here on, so it goes wherever the run goes.
            if str(getattr(mate, "status", "")) in ("done", "failed", "killed", "lost"):
                asyncio.create_task(remember_what_it_changed(str(mate.id)))

        with contextlib.suppress(Exception):
            crew.on_change(_changed)

        # A job Rouh started on this server tells the person its result when
        # it finishes: a card at once, and Rouh says it once nobody is
        # talking. Assistant jobs are reported by the Lander below instead.
        from .job_report import JobReporter

        def _heartbeat_hears(mate, kind: str, payload) -> None:
            """A crew job ended - an assistant job, a delegated task, an improve_myself
            worker - and the heartbeat hears it (`heartbeat.Heartbeat.run_finished`)."""
            status = str(getattr(mate, "status", ""))
            if not ((kind == "stop" and status == "done") or (kind == "failed" and status == "failed")
                    or (kind in ("lost", "session_end") and status == "lost")):
                return None
            meta = getattr(mate, "meta", None) or {}
            pulse.run_finished(str(mate.id), str(getattr(mate, "title", "") or meta.get("title") or ""),
                               how={"done": "finished", "failed": "failed",
                                    "lost": "was lost"}.get(status, status),
                               kind="assistant job" if meta.get("profile") == "assistant" else "job")
            return None

        with contextlib.suppress(Exception):
            crew.on_change(_heartbeat_hears)

        crew.on_change(JobReporter(crew, memory, Hub.broadcast, announce,
                                   conversation_busy).on_event)

        if config.assistant_repo and "assistant" in (getattr(crew, "profiles", None) or {}):
            from .assistant_job import Lander, WorkspaceCopy

            lander = Lander(crew, memory, Hub.broadcast, announce,
                            config.assistant_review_url,
                            copy=WorkspaceCopy(config.assistant_repo, config.assistant_user,
                                               config.assistant_home))
            # A goal step's run is the goal's, not a report of its own.
            lander.goal_runs = timekeeper
            # A job that needs the owner goes to their phone as a link, and a finished
            # one only if the setting says so (`rouh/job_phone.py`).
            lander.telegram, lander.public_url = tools.telegram, config.public_url
            lander.phone_done = config.phone_done_jobs
            # A chat that asked for a job becomes the chat of the task the job made.
            lander.task_chat_changed = announce_task_chat
            crew.on_change(lander.on_event)
            log.info("assistant jobs on: %s, run as %s",
                     config.assistant_repo, config.assistant_user)

    # Started whether or not background jobs are on: Rouh's own tool calls
    # are a tree too, and with jobs switched off they never reached the orb.
    TreeFeed.start()
    # And the questions land.sh could not answer by itself. Started whatever
    # else is on, because a record is a file: one written before a deploy is
    # still being asked after it, and this process coming up is the moment the
    # person has to be told again.
    conflicts.ensure_land_dir(config)
    # Which model Rouh's own merge pass runs on, for land.sh to read.
    await asyncio.to_thread(modeldefaults.publish_merge_pick, None, config)
    ConflictFeed.start()

    # The workspace's derived content index, built here if nobody ever has.
    #
    # The rows take themselves in on the first page that needs them
    # (`objecttree.ensure_imported`) and the index did not, so it sat empty on
    # this server from the day stage four shipped: 241 objects, 238 links and
    # nought files indexed, because `reindex` is a command and no command is
    # run on a server. On a thread and never on a request, because indexing
    # reads every file of every object; and once only, because the first file
    # in it is what says it has been read.
    def _index_the_workspace() -> None:
        from . import objects, objecttree

        root = config.assistant_repo
        store = objects.shared_store(even_when_off=True)
        if not root or store is None:
            return
        # The repairs first, so the rail and the task list are right from the
        # first screen rather than from the first time somebody opens the task
        # browser. The tree is taken in ahead of them, because there is nothing
        # to repair in rows nobody has read yet, and both write nothing at all
        # once they have run once.
        try:
            objecttree.ensure_imported(root, store)
        except Exception:
            log.exception("the workspace tree could not be taken in")
        objecttree.tidy(root, store)
        try:
            objecttree.ensure_indexed(root, store)
        except Exception:
            # Derived and rebuildable, so it is never a reason not to start.
            log.exception("the workspace content index could not be built")
        # And the pages the workspace has built, taken in as the artifacts they
        # are. Same thread, same rule, and for the same reason it was missing:
        # nothing on a server runs a command, so a row that is only ever
        # written by somebody opening a page is a row that is never written.
        # This machine had 145 built pages and no rows for any of them, so a
        # project's page could say nothing about what had been made in it.
        if artifacts.enabled():
            try:
                counts = artifacts.register_tree_pages(root)
                if counts.get("kept"):
                    log.info("the workspace's built pages: %s of %s folders are "
                             "artifacts", counts["kept"], counts["looked"])
            except Exception:
                log.exception("the workspace's built pages could not be taken in")
        # Every shared page, commented page and Ask AI page followed to where
        # its folder is now, and written down by the object it is in, so the
        # next move of it - by a job's `git mv` as much as by Rouh - takes its
        # links along (`rouh/pageplaces.py`).
        from . import pageplaces

        moved = pageplaces.follow(root, force=True)
        if moved:
            log.info("pages followed to where their folders moved: %s", moved)

    import threading

    threading.Thread(target=_index_the_workspace, name="content-index",
                     daemon=True).start()

    # The files the person has uploaded, searchable by the words in them: any
    # given before this process started and not yet in the index are read and
    # taken in, on a thread of their own and one at a time (`rouh/uploads.py`).
    uploads.start()

    # One home for every file (`rouh/filestore.py`): files kept the old way are moved into their
    # chat's or task's folder once, and the bin is emptied on its schedule, on a thread of its own.
    from . import filestore
    filestore.start()

    # What Rouh makes in the workspace, landed on main, where the server's own
    # settings say this is the machine that does it. Its first look is a little
    # after this, so the tidy above is saved with everything made before today.
    from . import saving, workspace_follow

    saving.start()
    # In the containers, Rouh's live workspace follows the one main its runs land on too, and
    # takes the work they hand it (`rouh/workspace_follow.py`); off on the server, where land.sh
    # moves it.
    workspace_follow.start()
    # And `_tasks.md` written out of the rows again whenever Rouh changes the
    # tree, on every machine, saved or not (`rouh/tasklist.py`).
    from . import objecttree, tasklist

    objecttree.WRITTEN.append(tasklist.changed)

    if one.configured():
        _attach_one(one, memory, tools, timekeeper, announce)
    else:
        # The worker pairs with Rouh on its first start, which in the containers can be after
        # Rouh is up (the core waits only so long, guard/bin/rouh-core-entrypoint). Rouh used to
        # attach only here, once, and then had no runs until it was started again; now it looks
        # again until the pairing is there (CONTAINERS.md, `one.attach-late`).
        _ONE_WATCH.append(asyncio.create_task(_attach_when_paired(one, memory, tools, timekeeper, announce)))

    # The beat behind the Gene therapy board. A submission is taken up the moment
    # it lands, in the request that wrote it, so this is only ever what was
    # left behind: a feedback written while this process was restarting, a
    # conversion cut off half way, a run that nothing would take the first
    # time it was asked, and a run that has ended since without its card being
    # told. Once now, because a process that has just come up is exactly where
    # one of those is waiting, and then on its own beat.
    #
    # Started whether or not the automatic half is on. That flag is about
    # whether a feedback is read and given a run with nobody pressing
    # anything; a request started by hand is `building` just the same and its
    # run ends just the same, and a board that goes on saying Building about
    # work that is finished is the bug this beat now also exists to stop
    # (`triage.settle`).
    GeneTherapySweep.start()
    # Reminders, repeating jobs and goal steps set for a time: a row that fell due while
    # this process was down is said a few seconds from now, late and saying
    # so, and every other one at its time (`rouh/reminders.py`). Each on its
    # person's clock, so everybody's time zone is read first (`clock.load`).
    try:
        await asyncio.to_thread(clock.load)
        # The zone at a shared location outranks the device's (`rouh/location.py`).
        await asyncio.to_thread(location.load)
    except Exception:
        log.exception("the people's time zones could not be read; the installation's own until a page says")
    if held:
        # A change of its own code still goes through its protected core (`rouh/codechanges.py`);
        # nothing below it is started.
        code_changes.start()
        return
    timekeeper.start()
    # The heartbeat, for the install's owner, with its default duties the first time.
    pulse.start()
    # The decisions: everything waiting on the person, taken in from every source now, and
    # each answer sent back to the source that asked (`rouh/decision_desk.py`).
    desk.start()
    desk.poke()
    # The notices' phone copies, each sent once when its notice is left on the screen.
    notice_sweeper.start()
    # The registry's blocklist, hourly: a shared gene it names is switched off and its
    # installer told (`rouh/genelab.py`).
    gene_watch.start()
    code_changes.start()
    # Rouh's own scheduled work, once there is an owner to schedule it for: at the start, and
    # again every ten minutes, each quiet when its row is there already. A new install's owner is
    # made after Rouh starts, on its first-run pages, and until 29 October 2026 a Rouh in the
    # containers had none of its nightly work until something started it again.
    asyncio.ensure_future(_own_work_ready())
    # A night of dreaming is drawn on the orb like Rouh's other own work (`rouh/synapse/dreaming.py`).
    from .synapse import dreaming as synapse_dreaming
    synapse_dreaming.orb = OwnWork.note
    # The morning brief, at each person's time (`rouh/morning_brief.py`).
    mornings.start()
    # Before you meet, an hour before each outside meeting (`rouh/meeting_prep.py`).
    meeting_notes.start()
    # What to raise, an hour before each outside meeting (`rouh/meeting_brief.py`).
    meeting_raises.start()
    # The work each meeting calls for, once its notes are in (`rouh/meeting_next.py`).
    meeting_followups.start()
    # Questions waiting on him that he already answered in a chat (`rouh/answered_in_chat.py`).
    answered_chats.start()
    # A page's sources checked when he asks (`rouh/source_check.py`).
    source_checks.start()
    # Replies he sends himself, to mail a task drafted for him, kept in the task (`rouh/sent_by_you.py`).
    sent_replies.start()
    # Shares given an end, taken away when it comes (`rouh/share_ends.py`).
    share_endings.start()
    # Every task's icon, picked by itself: every task with none, now and whenever one is made
    # (`rouh/taskicons.py`).
    from . import taskicons

    taskicons.picker.start()
    # Ideas added to the Incubator from any thread are scored on this loop (`rouh/incubator_score.py`).
    from . import incubator_score as _incubator_score

    _incubator_score.start()
    # Mutations kept true: shelf, trial weeks, mutations (`rouh/evolution.py`).
    asyncio.ensure_future(_evolution_loop())
    asyncio.ensure_future(_nightly_watch_loop())
    # The gene log: every gene in Rouh, filled by itself, with each gene's use (`rouh/genelog.py`).
    asyncio.ensure_future(_gene_log_loop())
    asyncio.ensure_future(_model_standard_loop())
    # The defaults every Rouh starts with, from rouh.land soon after a start and once a day (`rouh/ruledefaults.py`).
    asyncio.ensure_future(_rule_defaults_loop())
    # The weekly encrypted copy off the machine, where the settings file sets one up (`rouh/offsite.py`).
    asyncio.ensure_future(_offsite_loop())
    # Whether each scheduled job really ran and worked, said once a morning when not (`rouh/job_watch.py`).
    asyncio.ensure_future(_job_watch_loop())
    _ANSWERS_WATCH.append(asyncio.create_task(_answer_held()))
    # Every guest of the week's meetings looked up on LinkedIn ahead of time (`rouh/meeting_people.py`).
    meeting_research.start()
    # And each of them added to his iCloud contacts (`rouh/meeting_contacts.py`).
    meeting_contacts_adder.start()
    # The owner's messages to the bot on their phone, each answered in General and
    # sent back there. A message that arrived while this process was down is
    # waiting at Telegram and is answered now (`rouh/telegram_chat.py`).
    phone_chat.start()
    # Slack, for every organisation that connected it (`rouh/slack_listen.py`): the socket opened,
    # and the last 30 days read back the first time.
    slack_listener.start()
    # Every connected iCloud address book, synced by itself. Only what changed
    # is fetched; a sync never writes to iCloud (`apple_contacts.py`).
    if contacts is not None:
        contacts.start()
        log.info("the contacts beat is running every %g minute(s)", contacts.minutes)
    # Every Gmail watch renewed daily, and every watched inbox looked at on
    # the same beat in case a note from Google never arrived.
    if mail_alerts is not None:
        mail_alerts.converse = answer_an_email
        mail_alerts.open_chat = open_email_chat
        # A job started for the owner's own email reports back to it
        # (`rouh/mail_flow.py`); everybody else's email is a case, carried on
        # by the case sweep (`rouh/mail_cases.py`).
        from . import mail_flow

        mail_flow.on_report = mail_alerts.work_reported
        # What a case's check finds wrong goes back to a job to be fixed - in
        # the workspace, or on the server - and its report back to the case
        # (`mail_cases._hand_off`).
        mail_alerts.start_job = start_case_job
        mail_alerts.start()
        log.info("the mail alerts beat is running every %g minute(s), and every new "
                 "message is handed to Rouh (%s)", mail_alerts.minutes, mail_alerts.model)
    log.info("the Gene therapy beat is running every %g minute(s), and each mutation asked for is %s",
             converter.sweep_minutes,
             "taken up by itself, read by the default model in Settings"
             if converter.enabled else "left for somebody to pick up")

    # Nothing is started here for the chats. There was a `ChatSweep` until
    # 22 September 2026 - it archived a loose chat after a month of quiet and
    # deleted it after three, at start-up and then every six hours - and the
    # person's answer to it was "Remove deleting chats at 90 days. No automatic
    # removal." A chat now goes when somebody deletes it, and nothing in this
    # process holds a clock over one.


async def _announce_tasks() -> None:
    with contextlib.suppress(Exception):
        await Hub.broadcast({"type": "tasks", "tasks": await task_list()})


async def _drop_unknown_task(job_id: str) -> None:
    """A card for a job nothing on this server has ever heard of: drop it.

    This used to come back as "Could not archive it: no crewmate with id ...",
    which put a red banner on the screen and left the card exactly where it
    was, so the one row a person most wants rid of was the one row they could
    not get rid of. A list only ever adds to what a tab shows, so the way to
    take a row off one is to name it, which is what `tasks_forgotten` is for.
    Every tab is told, not only the one that pressed.

    The list is read first, and a row that is really on it is never named. The
    crew not knowing an id is not the same as this machine not knowing it: a
    run of the one program is on the list and is not in the crew's table, and
    dropping the card for a run that is still going would be a worse bug than
    the one being fixed.
    """
    rows = await task_list()
    if any(str(row.get("id")) == job_id for row in rows):
        log.info("not archiving %s here; the list says who holds it", job_id)
        await Hub.broadcast({"type": "tasks", "tasks": rows})
        return
    log.info("dropping the card for %s: no such job here", job_id)
    await Hub.broadcast({"type": "tasks_forgotten", "ids": [job_id]})
    await Hub.broadcast({"type": "tasks", "tasks": rows})


#: The Ask AI exchanges on their way into a conversation, held so that none of
#: them is collected half way (`askai_said`).
_ASKAI_WRITING: set[asyncio.Task] = set()


def askai_said(chat: str, doc: str, title: str):
    """What Ask AI hands each exchange the owner has in it (`askai.answer`).

    Petar, 27 September 2026 (fr_dd4ac24658fa): "ask ai doesn't get included in
    the orb and it should". Ask AI kept its exchanges to itself, so the
    conversation beside it - the Rouh tab, which is the chat the orb and the
    voice talk in - had never heard of them. Now each one is written into that
    conversation too, as the person's question and the answer they had, drawn
    under a label that says it was Ask AI and read by the model like any turn
    (`Memory.add_askai`). The Ask AI topics stay what they were: its own rows,
    and its own history of topics on the page.

    `chat` is the conversation the page had on the screen when the question
    was asked, which is where the person will carry on. One that is not a chat
    or a draft of one any more is the active chat instead.
    """
    def said(question: str, passage: str, answer: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(_askai_write(chat, doc, title, question, passage, answer))
        _ASKAI_WRITING.add(task)
        task.add_done_callback(_ASKAI_WRITING.discard)
    return said


async def _askai_write(chat: str, doc: str, title: str, question: str, passage: str,
                       answer: str) -> None:
    chat = (chat or "").strip()
    if not chat or (memory.chat(chat) is None and conversations.draft(chat) is None):
        chat = memory.active_chat()
    # Between two turns and never inside one: a turn running there has its
    # question, its tool calls and their results to write in that order, and an
    # exchange put in the middle of them would be a conversation the model
    # refuses to read.
    while (running := Turns.of(chat)) is not None and running.task is not None:
        await asyncio.wait({running.task})
    # Nothing is awaited from here to the write, so no turn can start in this
    # chat in between. A chat deleted meanwhile is not made again.
    if memory.chat(chat) is None and conversations.draft(chat) is None:
        return
    try:
        rows = memory.add_askai(chat, doc, title, question, passage, answer)
    except Exception:                               # noqa: BLE001 - logged, never raised
        log.exception("the Ask AI exchange about %s could not be written into %s", doc, chat)
        return
    await Pictures.to_chat(chat, {"type": "askai_said", "rows": rows})
    # A draft is a chat now, and the rail says so; its name, and its place at
    # the top of the list, are a turn's.
    after_a_turn(chat)


async def announce(note: str, chat: str = "") -> bool:
    """Say something unprompted, in the thread the note belongs to.

    `chat` is that thread: the conversation the run was started from, or
    General for a run no conversation started (`runs.reports_to`). It is
    answered there whatever the person has since
    opened, which is the whole of it - a job asked for this morning reports
    under this morning's question, and never in the middle of whatever is on
    the screen now. Petar, 22 September 2026: "It should report a run in the
    chat it was started from."

    What that looks like on the screen is already what a turn does, because a
    turn belongs to its thread and not to a tab (`Turn`). Somebody standing in
    that thread sees it arrive and hears it, exactly as before. Somebody who is
    not sees nothing at all: the answer is written into that thread in silence,
    the voice does not follow them there (`Turn.listener`), and the thread's
    row in the rail is marked as having something new in it, which is the dot
    they come back to.

    An empty `chat` is a note that belongs to no thread in particular - a
    question from the one program with no run behind it - and that one is said
    in General, the thread that is always there for exactly that. It used to be
    answered wherever the person was, and that is how a chat about weekend
    plans came to be full of reports about Rouh's own code (feedback
    fr_9e9cea243870): nothing unprompted is ever said into the chat that merely
    happens to be open.

    False when there is nobody at a screen at all, and when that thread is
    already being answered: the card on the canvas is enough, and whoever is
    waiting on this tries again.
    """
    live = [s for s in Hub.sockets if not s.closed]
    if not live:
        return False
    wanted = (chat or "").strip()
    # A chat that has been deleted since the run started is no address at all,
    # and answering into it would make the row again from under the person.
    if wanted and memory.chat(wanted) is None:
        wanted = ""
    if not wanted:
        wanted = memory.ensure_general()
    # Is that thread already being answered? Asked of the register, because
    # that is where a turn lives, and a turn goes on in a thread nobody has on
    # screen.
    if Turns.busy(wanted):
        return False
    # The newest tab standing in that thread, when there is one. It is what the
    # voice follows and whose spoken-replies switch this turn takes;
    # where there is none the note is answered into the thread in silence, and
    # is there to read when they come back.
    here = [s for s in live if getattr(s, "session_id", "") == wanted]
    tab = max(here, key=lambda s: getattr(s, "opened_at", 0.0)) if here else None
    # Said rather than judged: this is Rouh's own note and not a half
    # sentence of the person's, so there is nothing to wait for them to finish.
    # And written down as a note (`Turn.note`): it is the model's to read and
    # never the person's to see under their own name, which is where reading
    # the chat back used to put it (feedback fr_2f27e92125ba).
    await Turns.start(wanted, note, asked_by=tab,
                      speak=bool(tab is not None and tab.voice_replies and voice.ready),
                      answer_now=True, note=True)
    return True


def _heard_names() -> list[str]:
    """The names this Rouh answers to for whoever is speaking: "Rouh", its own and the nickname they
    gave it (`birth.heard_names`), for the transcriber to listen for (`speech.LiveEars`)."""
    from . import birth
    from .tenancy import speaker

    who = speaker()
    return birth.heard_names(str(who.org_id), str(who.user_id)) if who is not None else [birth.EVERY_ROUH]


def contact_note(card, contact: str, field: str, value, who) -> dict | str:
    """Write one field of a contact's profile from its card, and the card as it now reads.

    Answers the revised card, or a sentence saying why nothing was kept. The
    card has to be a contact card about that very contact, so a page cannot
    use one card to write about somebody else; the contact has to be the
    signed-in person's own (`People.person` is scoped by both ids).
    """
    from . import apple_contacts

    if who is None:
        return "Sign in again: this page does not know who you are any more."
    if contacts is None:
        return "Contacts are switched off on this server."
    if field not in ("relationship", "research", "silos", "refresh", "organisation"):
        return "Only the relationship, the research and the silos can be changed here."
    text = str(value if value is not None and field != "silos" else "")
    picked = None
    if field == "silos":
        # The whole set as pressed, by silo key (`rouh/silos.py`); none is in no silo.
        picked = [str(k) for k in value] if isinstance(value, list) else [] if value in (None, "") else [str(value)]
    shown = artifacts.read(card) if artifacts.enabled() else None
    blocks = (shown or {}).get("blocks") or []
    block = next((b for b in blocks if isinstance(b, dict) and b.get("block") == "contact"),
                 None)
    if block is None or str(block.get("contact") or "") != contact or not contact:
        return "That card is not this contact's any more. Ask Rouh to show the contact again."
    person = contacts.people.person(who.user_id, who.org_id, contact)
    if person is None and field == "refresh":
        # Linked into another person on the card (`synapse/aka.py`): the card is that person now.
        from .synapse import aka

        ds = contacts.people._ds(who.user_id, who.org_id)
        now = aka.live_id(ds, contact) if ds else ""
        person = contacts.people.person(who.user_id, who.org_id, now) if now else None
    if person is None:
        return "That contact is not there any more."
    if field == "organisation" and not person.is_me:
        # The company is changed here on the person's own card only (About You, Contact card);
        # anybody else's is their card's, changed by asking Rouh.
        return "The company can be changed here on your own card only."
    # A refresh writes nothing: its "Also known as" changed on the card (`personlinks.js`), and it is
    # drawn again as it now reads.
    try:
        person = person if field == "refresh" else contacts.people.write(
            who.user_id, who.org_id, person,
            relationship=text if field == "relationship" else None,
            research=text if field == "research" else None,
            # Research typed by the person themselves is theirs to vouch for.
            confirmed=True if field == "research" and text.strip() else None,
            # Its silos, as they pressed them.
            silos=picked,
            # Their company, on their own card (`people.People.write`, queued to iCloud on a card).
            organisation=text if field == "organisation" else None)
    except ValueError as exc:
        return str(exc)
    fresh = apple_contacts.profile_card(person, state=block.get("state") or "shown",
                                        status=block.get("status") or "")
    revised = artifacts.revise(card, title=shown.get("title"), description=shown.get(
        "description"), blocks=[fresh["blocks"][0] if b is block else b for b in blocks],
        root=config.assistant_repo)
    return revised or "The card could not be drawn again, but the change was kept."


async def open_email_chat(was: str, title: str) -> str:
    """The conversation a new email is handled in (`mail_alerts.MailAlerts.handle`).

    The one the last message of its thread was handled in, while it is still
    there, so a reply to a reply carries on where the first was answered; a
    new loose chat otherwise, named for the email. Never made the active chat:
    the person may be in the middle of something else, and a message arriving
    must not move their screen.
    """
    def made() -> str:
        if was and memory.chat(was) is not None and not (memory.chat(was) or {}).get("draft"):
            return was
        return conversations.new_chat(title, None)

    chat = await asyncio.to_thread(made)
    with contextlib.suppress(Exception):
        await announce_chats()
    return chat


async def start_case_job(*, brief: str, title: str, preset: str = "delegate_task") -> str:
    """A job for what an email case sends back to be fixed or hands on, and its id.

    `preset` is "assistant_job" for a fix in the person's workspace, and
    "delegate_task" - an administrator on this machine - only for a step on
    the server or in Rouh itself (`mail_cases.CaseDesk._start_follow_up`).
    Either is a run of its own on the run list, belonging to no conversation:
    its report goes back to the case (`mail_flow.reported`,
    `mail_cases.CaseDesk.job_reported`). Raises `starting.CannotStart` with the
    sentence to say when nothing takes it.
    """
    from . import starting

    if preset not in ("assistant_job", "delegate_task"):
        raise starting.CannotStart(f"a case starts no {preset or 'unnamed'} job")
    if preset == "delegate_task" and not getattr(config, "enable_delegate", False):
        raise starting.CannotStart("server jobs are switched off on this machine")
    got = await starting.start(brief=brief, title=title, preset=preset,
                               cfg=config, crew=crew, one=one, emit=Hub.broadcast)
    return str(got.get("id") or "")


async def answer_an_email(who, chat: str, card: dict | None, brief: str, turn,
                          limit: float) -> tuple[bool, str, str]:
    """Hand one new email to Rouh, in its conversation, and wait for the answer.

    The email itself goes on the screen first, as a card at the head of what is
    said about it, so whoever opens the conversation later sees what arrived
    and then what Rouh did. The brief (`mail_alerts.brief`) is a note of Rouh's
    own software, never the person's words, and the turn runs whether or not
    anybody has Rouh open: it is answered into the conversation in silence and
    leaves the dot that says something new is there.

    Two things ride with the turn, in context variables its task inherits:
    whose mailbox it is (`tenancy.SPEAKER`), so the Google tools act for that
    person with no browser in front of them; and the email itself
    (`mail_turn.CURRENT`), which is what holds a turn about somebody else's
    email to the tools that email may reach.

    Answers (finished, what Rouh said, what went wrong). A turn still going at
    `limit` seconds is left to go on; the caller only stops waiting for it.
    """
    from . import mail_turn
    from .tenancy import SPEAKER

    # The person may be typing in this very conversation, or the message
    # before this one in the same thread may still be being answered. Starting
    # a turn over either would stop it.
    waited = 0.0
    while Turns.busy(chat) and waited < MAIL_FREE_WAIT:
        await asyncio.sleep(1.0)
        waited += 1.0
    if Turns.busy(chat):
        return False, "", "its conversation was busy, so Rouh did not start on it"
    # No card when the owner's own email comes back to be finished, or for a
    # case after its first turn: it is already at the head of its
    # conversation (`mail_flow.resume_note`, `mail_cases.CaseDesk`).
    if card is not None:
        with memory_mod.answering_in(chat):
            _number, spec = await asyncio.to_thread(tools._keep, card)
        drawn = {"type": "ui", "spec": spec, "chat": chat}
        for tab in [s for s in list(Hub.sockets) if not s.closed and s.session_id == chat]:
            with contextlib.suppress(Exception):
                await tab.send(drawn)
    speaker_was = SPEAKER.set(who)
    turn_was = mail_turn.CURRENT.set(turn)
    # What a turn on somebody else's mail makes is the mail's, not the owner's: made for them when
    # they are somebody it can name, made by Mail cases otherwise (`rouh/task_origin.py`).
    # The owner's own mail is their own words.
    making = task_origin.making("mail", f"a turn on mail in chat {chat}")
    if not getattr(turn, "from_owner", False):
        making.__enter__()
    try:
        running = await Turns.start(chat, brief, asked_by=None,
                                    speak=False, answer_now=True, note=True)
    finally:
        if not getattr(turn, "from_owner", False):
            making.__exit__(None, None, None)
        mail_turn.CURRENT.reset(turn_was)
        SPEAKER.reset(speaker_was)
    if running.task is None:
        return False, "", "Rouh's turn did not start"
    try:
        await asyncio.wait_for(asyncio.shield(running.task), timeout=max(30.0, limit))
    except asyncio.TimeoutError:
        return (False, "".join(running.said),
                f"Rouh was still working on it after {max(1, round(limit / 60))} minutes")
    except Exception:  # noqa: BLE001 - the turn says its own trouble in its thread
        pass
    if not running.answered:
        return False, "".join(running.said), "Rouh's turn ended without finishing"
    return True, "".join(running.said), ""


#: How long a new email waits for its conversation to be free.
MAIL_FREE_WAIT = 120.0


def conversation_busy() -> bool:
    """Whether anyone is in the middle of talking with Rouh.

    True while the person is speaking (pauses included), dictating, or being
    answered in any thread, written or aloud. A finished job's result waits for
    this to be False, so it is never said over them; see job_report.py. The
    turns are asked first and are asked of the register rather than of a tab: a
    turn belongs to its thread and goes on being answered after the tab that
    asked for it has moved on (`Turn`).
    """
    for turn in list(Turns.running.values()):
        if turn.task is not None and not turn.task.done():
            return True
        if turn.tts_task is not None and not turn.tts_task.done():
            return True
    for tab in list(Hub.sockets):
        if tab.closed:
            continue
        if tab.capturing or tab.dictating:
            return True
    return False


async def shutdown() -> None:
    # The phone address's client, frpc, ended with Rouh (`rouh/relay.py`).
    with contextlib.suppress(Exception):
        from rouh import relay

        await relay.stop()
    # Every open browser's logins written down before it goes.
    await browser_desk.stop()
    # And every event still waiting in memory (`rouh/events.py`).
    with contextlib.suppress(Exception):
        await asyncio.to_thread(events.WRITER.flush, 5.0)
    for task in _ONE_WATCH:
        task.cancel()
    await OneFeed.stop()
    await TreeFeed.stop()
    await ConflictFeed.stop()
    await GeneTherapySweep.stop()
    await timekeeper.stop()
    await pulse.stop()
    await desk.stop()
    await notice_sweeper.stop()
    await gene_watch.stop()
    await code_changes.stop()
    await mornings.stop()
    await meeting_notes.stop()
    await meeting_raises.stop()
    await meeting_followups.stop()
    await answered_chats.stop()
    await source_checks.stop()
    await sent_replies.stop()
    await share_endings.stop()
    await meeting_research.stop()
    await meeting_contacts_adder.stop()
    await phone_chat.stop()
    await slack_listener.stop()
    if contacts is not None:
        await contacts.stop()
    if mail_alerts is not None:
        await mail_alerts.stop()
    # Every MCP server this process started, and only those: each is stopped
    # by the handle taken when it was spawned.
    await tools.close_mcp()
    await voice.aclose()
    await ears.aclose()
    if crew is not None:
        await crew.stop()
