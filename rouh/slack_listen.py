"""Slack, listened to: every message the app can see, kept as it happens, and what is said to Rouh
handed to Rouh (`rouh/slack.py` has the app, its tokens and what is kept).

**Socket Mode.** Rouh opens the socket itself (`apps.connections.open` with the app-level token)
and Slack sends every event down it, so nothing on this server has to be reachable from outside.
Each envelope is acknowledged the moment it arrives and then handled, one at a time in order, so a
slow look-up never makes Slack send it again. Slack asks for a new socket every few hours
("disconnect"), and one that drops for any other reason is opened again after a pause that grows
from a second to a minute; the page says which it is doing (`slack.note_listening`). The
`Listener` itself is started with Rouh (`runtime.startup`) and looks every half minute, or at once
when the page saves or removes tokens, for an organisation that is connected and not listened to.

**What arrives.** With the bot token's events: every message in a channel, private channel or
group direct message Rouh is a member of, and every direct message to Rouh; with the person's own
user token's: their own direct messages and group direct messages, which are theirs only
(`private`). An edit changes the kept copy and a deletion removes it. Rouh being added to a channel
(`member_joined_channel` naming the bot) reads that channel's last 90 days at once; a new public
channel is noted, and is read only once Rouh is in it.

**The first look back.** On the first connection, every conversation Rouh can read - the channels
it is in, its own direct messages, and the person's own direct messages - is read back over the
last `slack.BACKFILL_DAYS` days with `conversations.history` and every thread in it with
`conversations.replies`, on a thread of its own, waiting out each Retry-After Slack gives. A
finished look back says how many days it covered (`days`); one that covered fewer than
`BACKFILL_DAYS` (the 30 there were until 16 October 2026) is read back once more over the longer
period when the socket next opens. Every message is kept by its conversation and ts, so one
already kept is updated in place rather than kept twice.

**Said to Rouh.** A direct message to Rouh's bot, or a message that mentions @Rouh, written by a
person while Rouh listens (never one read back from before), is handed over once:

- from the person themselves (their Slack account, the user token's, or one whose address is one
  of their own): a turn in a conversation of its own, as their own email is, whose answer Rouh's
  code posts back to them in Slack as Rouh's bot (`_owner_said`);
- from somebody the owner set up - a trusted contact, switched on, by the address on their Slack
  profile, which Slack confirmed when they joined the workspace: a case, exactly like an email from
  them (`mail_cases.CaseDesk.take`), with the grants the owner gave them, answered from what they - and in
  a channel everybody in it - may see (`rouh/slack_team.py`), through the one outbox
  (`mail_outbox`), in Slack, in the thread it was asked in;
- from anybody else: one polite answer there that Rouh can only help people the owner has set up, and
  the owner told once for each person, with a button to set them up (`_not_set_up`). Until 16 October
  2026 they were a case with communication only, as a stranger's email still is.

Everything they wrote stays their words: it reaches the model inside the case's brief as somebody
else's message, and an instruction in it is never followed.

**Read for promises.** Every message kept, heard or read back, is read for promises made by the
person or to them (`rouh/slack_promises.py`): once Slack has been quiet for a moment after a
message, a model call per conversation, and every ten minutes besides for what was read back and
what came due (`_promise_reader`).

**Read for decisions.** At the same moment, a channel linked to a task is read for the decisions
made in it, which are written into the task's notes (`rouh/slack_tasks.py`).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from email.utils import formatdate

from . import slack

log = logging.getLogger("rouh.slack_listen")

#: How often the listener looks for a connection to start or stop listening to.
LOOK_EVERY = 30.0
#: The longest pause before trying a dropped socket again.
PAUSE_MOST = 60.0
#: After Slack refuses the app-level token, how long before asking again.
REFUSED_PAUSE = 300.0
#: A message older than this when it arrives is kept but never handed to Rouh: Slack sending it
#: again after a long outage is not somebody asking now.
FRESH = 900.0


def _socket_url(conn) -> str:
    got = slack.Client(slack.token(conn, "app")).call("apps.connections.open")
    url = str(got.get("url") or "")
    if not url:
        raise slack.SlackError("no_url", "Slack gave no address for the socket")
    return url


class Listener:
    """Every connected organisation's Slack socket, kept open, and what comes down it handled.

    Handed Rouh's running pieces by runtime.py: the case desk while there is one (`desk`, None
    where there is no mail), the turn runner for a message of the person's own (`converse`, which
    is `runtime.answer_an_email`), and the conversation opener (`open_chat`).
    """

    def __init__(self, *, desk=None, converse=None, open_chat=None, tenancy=None) -> None:
        self.desk = desk or (lambda: None)
        self.converse = converse
        self.open_chat = open_chat
        self.tenancy = tenancy
        self._loop: asyncio.AbstractEventLoop | None = None
        self._watch: asyncio.Task | None = None
        self._sockets: dict[str, asyncio.Task] = {}
        self._workers: dict[str, asyncio.Task] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._poke: asyncio.Event | None = None
        self._backfilling: dict[str, threading.Thread] = {}
        self._heard_said: dict[str, float] = {}
        self._handing: set[asyncio.Task] = set()
        #: Set when a message was kept: the promise reader reads once Slack is quiet.
        self._said: asyncio.Event | None = None
        self._promises: asyncio.Task | None = None

    # --- the beat -----------------------------------------------------------------------------

    def start(self) -> None:
        if self._watch is not None:
            return
        self._loop = asyncio.get_running_loop()
        self._poke = asyncio.Event()
        self._said = asyncio.Event()
        self._watch = asyncio.create_task(self._supervise(), name="slack-listener")
        self._promises = asyncio.create_task(self._promise_reader(), name="slack-promises")

    def poke(self) -> None:
        """Look again now: tokens were saved or removed. Safe from any thread."""
        if self._loop is None or self._poke is None:
            return
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self._poke.set)

    async def stop(self) -> None:
        tasks = [t for t in [self._watch, self._promises, *self._sockets.values(), *self._workers.values(),
                             *self._handing] if t]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(BaseException):
                await t
        self._watch = None
        self._promises = None
        self._sockets.clear()
        self._workers.clear()

    async def _supervise(self) -> None:
        while True:
            try:
                rows = await asyncio.to_thread(slack.connections)
                wanted = {str(r.org_id) for r in rows}
                for org in wanted:
                    task = self._sockets.get(org)
                    if task is None or task.done():
                        self._sockets[org] = asyncio.create_task(self._socket(org), name=f"slack-socket-{org}")
                    worker = self._workers.get(org)
                    if worker is None or worker.done():
                        self._queues.setdefault(org, asyncio.Queue())
                        self._workers[org] = asyncio.create_task(self._work(org), name=f"slack-events-{org}")
                for org in list(self._sockets):
                    if org not in wanted:
                        self._sockets.pop(org).cancel()
                        worker = self._workers.pop(org, None)
                        if worker is not None:
                            worker.cancel()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the next look
                log.exception("slack: the listener could not look at the connections")
            assert self._poke is not None
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._poke.wait(), timeout=LOOK_EVERY)
            self._poke.clear()

    # --- one socket ---------------------------------------------------------------------------

    async def _socket(self, org: str) -> None:
        from websockets.asyncio.client import connect

        pause = 1.0
        while True:
            conn = await asyncio.to_thread(slack.connection, org)
            if conn is None or not conn.app_sealed or not conn.bot_sealed:
                return
            await asyncio.to_thread(slack.note_listening, org, "connecting")
            said, wait = "", pause
            try:
                url = await asyncio.to_thread(_socket_url, conn)
                async with connect(url, max_size=2 ** 24, open_timeout=20, ping_interval=30,
                                   ping_timeout=30) as ws:
                    await asyncio.to_thread(slack.note_listening, org, "listening", "",
                                            connected_at=time.time(), heard_at=time.time())
                    log.info("slack: listening to the %s workspace", conn.team_name or conn.team_id)
                    pause = 1.0
                    why = backfill_due(conn)
                    if why:
                        self.backfill(org, reason=why)
                    async for raw in ws:
                        try:
                            env = json.loads(raw)
                        except (TypeError, ValueError):
                            continue
                        if env.get("envelope_id"):
                            # Acknowledged first, handled after: Slack sends it again if it waits.
                            await ws.send(json.dumps({"envelope_id": env["envelope_id"]}))
                        kind = env.get("type")
                        if kind == "disconnect":
                            said = f"Slack asked for a new connection ({env.get('reason') or 'no reason'})"
                            wait = 0.0
                            break
                        if kind == "events_api" and isinstance(env.get("payload"), dict):
                            self._queues.setdefault(org, asyncio.Queue()).put_nowait(env["payload"])
                            await self._heard(org)
                    else:
                        said = "Slack closed the connection"
            except asyncio.CancelledError:
                # Stopped: by Rouh shutting down, or after Disconnect, whose own words are kept.
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(lambda: slack._model().objects.filter(org_id=org).exclude(
                        listening="off").update(listening="off", listening_said="Stopped.",
                                                updated_at=time.time()))
                raise
            except slack.NotSetUp:
                return
            except slack.SlackError as exc:
                said = f"Slack would not open a connection ({exc.error})"
                if exc.error in ("invalid_auth", "not_authed", "account_inactive", "token_revoked",
                                 "not_allowed_token_type", "missing_scope"):
                    wait = REFUSED_PAUSE
            except Exception as exc:  # noqa: BLE001 - said on the page, tried again
                said = f"The connection to Slack dropped ({type(exc).__name__})"
                log.info("slack: the socket for org %s dropped: %r", org, exc)
            if wait:
                await asyncio.to_thread(slack.note_listening, org, "waiting",
                                        f"{said}; trying again in {int(wait)} s.")
                await asyncio.sleep(wait)
                pause = min(PAUSE_MOST, max(1.0, pause * 2))

    def said_something(self) -> None:
        """A message was kept, here or by a look back: read for promises once Slack is quiet. Safe
        from any thread."""
        if self._loop is None or self._said is None:
            return
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(self._said.set)

    async def _promise_reader(self) -> None:
        """Every connection's new messages read for promises (`slack_promises.sweep`), and the
        channels linked to tasks for decisions (`slack_tasks.sweep`): once Slack has been quiet for
        `QUIET` after a message (never waiting more than `WAIT_MOST`), and every `EVERY` besides,
        for what was read back and what came due."""
        from . import decision_desk, slack_promises, slack_tasks

        assert self._said is not None
        while True:
            try:
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._said.wait(), timeout=slack_promises.EVERY)
                began = time.time()
                while True:
                    self._said.clear()
                    await asyncio.sleep(slack_promises.QUIET)
                    if not self._said.is_set() or time.time() - began >= slack_promises.WAIT_MOST:
                        break
                self._said.clear()
                more = moved = False
                for conn in await asyncio.to_thread(slack.connections):
                    got = await slack_promises.sweep(str(conn.org_id))
                    more = more or bool(got.get("more"))
                    moved = moved or bool(got.get("made") or got.get("kept"))
                    try:
                        decided = await slack_tasks.sweep(str(conn.org_id))
                    except Exception:  # noqa: BLE001 - the promises are read whatever this does
                        log.exception("slack: the linked channels could not be read for decisions")
                        decided = {}
                    more = more or bool(decided.get("more"))
                if moved and decision_desk.LIVE is not None:
                    decision_desk.LIVE.poke()
                if more:
                    self._said.set()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the next pass
                log.exception("slack: the messages could not be read for promises")

    async def _heard(self, org: str) -> None:
        """When Slack last said anything, written at most every half minute."""
        now = time.time()
        if now - self._heard_said.get(org, 0) >= 30:
            self._heard_said[org] = now
            await asyncio.to_thread(lambda: slack._model().objects.filter(org_id=org).update(heard_at=now))

    async def _work(self, org: str) -> None:
        queue = self._queues.setdefault(org, asyncio.Queue())
        while True:
            payload = await queue.get()
            try:
                await self.take(org, payload)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one event never stops the others
                log.exception("slack: an event could not be handled")

    # --- one event ----------------------------------------------------------------------------

    async def take(self, org: str, payload: dict) -> None:
        """One event Slack sent, as its payload: kept, changed, removed, or handed to Rouh."""
        conn = await asyncio.to_thread(slack.connection, org)
        if conn is None or (conn.team_id and payload.get("team_id") and payload["team_id"] != conn.team_id):
            return
        event = payload.get("event") or {}
        kind = event.get("type")
        if kind == "message":
            await self._message(conn, event)
        elif kind == "app_mention":
            await self._message(conn, {**event, "channel_type": event.get("channel_type") or ""},
                                mention=True)
        elif kind == "member_joined_channel":
            if str(event.get("user") or "") == conn.bot_user_id:
                cid = str(event.get("channel") or "")
                await asyncio.to_thread(self._joined, conn, cid)
                self.backfill(org, reason="Rouh was added to a channel", only=cid)
        elif kind == "channel_created":
            info = event.get("channel") or {}
            await asyncio.to_thread(slack.keep_conversation, conn, {**info, "is_channel": True}, member=False)

    @staticmethod
    def _joined(conn, cid: str) -> None:
        try:
            info = slack.bot(conn).call("conversations.info", channel=cid).get("channel") or {"id": cid}
        except slack.SlackError:
            info = {"id": cid}
        slack.keep_conversation(conn, {**info, "id": cid, "is_member": True}, member=True)

    async def _message(self, conn, event: dict, *, mention: bool = False) -> None:
        sub = str(event.get("subtype") or "")
        cid = str(event.get("channel") or "")
        if not cid:
            return
        hint = str(event.get("channel_type") or "")
        if sub == "message_changed":
            new = event.get("message") or {}
            await asyncio.to_thread(self._keep, conn, cid, hint, new)
            return
        if sub == "message_deleted":
            gone = await asyncio.to_thread(slack.forget_message, conn, cid, str(event.get("deleted_ts") or ""))
            if gone:
                log.info("slack: a message deleted in Slack was removed here")
            return
        row, conv = await asyncio.to_thread(self._keep, conn, cid, hint, event)
        if row is not None and not row.promises_read:
            self.said_something()
        if row is None or conv is None or not self._to_rouh(conn, conv, row, event, mention):
            return
        claimed = await asyncio.to_thread(
            lambda: type(row).objects.filter(id=row.id, handed="").update(handed="taking"))
        if not claimed:
            return
        task = asyncio.create_task(self._hand(conn, conv, row))
        self._handing.add(task)
        task.add_done_callback(self._handing.discard)

    @staticmethod
    def _keep(conn, cid: str, hint: str, m: dict):
        conv = slack.conversation(conn, cid, hint=hint)
        if conv is None:
            return None, None
        row, _made = slack.keep_message(conn, conv, m)
        return row, conv

    @staticmethod
    def _to_rouh(conn, conv, row, event: dict, mention: bool) -> bool:
        """Said to Rouh, now, by a person: a direct message to the bot, or @Rouh."""
        if row.by_rouh or row.handed or conv.private or not event.get("user") or event.get("bot_id"):
            return False
        if str(event.get("subtype") or "") not in ("", "file_share", "thread_broadcast", "me_message"):
            return False
        if time.time() - row.at > FRESH:
            return False
        if conv.kind == "im" and conv.is_member:
            return True
        return mention or slack.mentions(event.get("text") or "", conn.bot_user_id)

    # --- handed to Rouh -----------------------------------------------------------------------

    async def _hand(self, conn, conv, row) -> None:
        from . import my_card

        try:
            who = await asyncio.to_thread(self._owner, conn)
            if who is None:
                log.warning("slack: a message to Rouh was not handed over: the connection has no owner")
                return
            author = await asyncio.to_thread(slack.person, conn, row.author_id)
            own = await asyncio.to_thread(my_card.own_addresses, who.user_id, who.org_id) \
                if author is not None and author.email else []
            if row.author_id == conn.slack_user_id or (author is not None and author.email and
                                                       author.email in {a.lower() for a in own or []}):
                await self._owner_said(conn, who, conv, row, author)
            else:
                await self._case(conn, who, conv, row, author)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - written down; the message stays kept
            log.exception("slack: a message to Rouh could not be handed over")
            await asyncio.to_thread(lambda: type(row).objects.filter(id=row.id, handed="taking")
                                    .update(handed="failed"))

    def _owner(self, conn):
        if self.tenancy is not None:
            return self.tenancy.identity_of(str(conn.user_id))
        from .tenancy import Tenancy

        return Tenancy().identity_of(str(conn.user_id))

    @staticmethod
    def thread_of(conv, row) -> str:
        """Where the answer goes: the thread it was written in; a new thread on a message in a
        channel; and the direct message itself for a message there that is in no thread."""
        if row.thread_ts:
            return row.thread_ts
        return "" if conv.kind == "im" else row.ts

    @staticmethod
    def where_said(conv) -> str:
        if conv.kind == "im":
            return "a direct message to Rouh"
        return slack.conversation_label(conv)

    def _chat_of(self, conn, conv, thread: str) -> str:
        """The conversation the last message of this Slack thread was handled in, or ""."""
        from .models import SlackMessage

        for r in SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, channel_id=conv.channel_id,
                                             handed__startswith="chat:").order_by("-at")[:200]:
            if self.thread_of(conv, r) == thread:
                return r.handed[len("chat:"):]
        return ""

    async def _owner_said(self, conn, who, conv, row, author) -> None:
        """The person's own message to Rouh: their instruction, answered back in Slack as Rouh."""
        from . import mail_turn
        from .mail_alerts import email_card
        from .turnmarks import NOTE

        thread = self.thread_of(conv, row)
        where = self.where_said(conv)
        owner = ((who.name or "").split() or ["‹owner›"])[0]
        chat = ""
        if self.open_chat is not None:
            was = await asyncio.to_thread(self._chat_of, conn, conv, thread)
            chat = await self.open_chat(was, f"💬 Slack: {' '.join(row.text.split())[:50]}")
        await asyncio.to_thread(lambda: type(row).objects.filter(id=row.id).update(handed=f"chat:{chat}"))
        if not chat or self.converse is None:
            return
        shown = {"from": f"{row.author_name} on Slack", "to": f"Rouh, in {where}", "subject": "Slack message",
                 "body": row.text + (("\n\n[files: " + ", ".join(row.files) + "]") if row.files else ""),
                 "date": formatdate(row.at, localtime=True), "channel": "slack"}
        public = conv.kind != "im"
        brief = "\n".join([
            f"{NOTE} A message from {owner} has arrived on Slack, in {where} in the "
            f"{conn.team_name or 'connected'} workspace, and it is yours to handle now. {owner} is not "
            "at the screen: this conversation is for this Slack conversation alone, and ‹his› message is "
            "on the screen at the head of it.]",
            "",
            f"It is {owner} ‹himself›: Slack says it came from ‹his› own account ({row.author_name}), so it "
            f"is ‹his› instruction, and you carry it out exactly as if ‹he› had said it to you here, with "
            "everything you can do.",
            "- Your answer at the end of this turn is posted back to ‹him› in Slack by Rouh's code, as "
            "Rouh's bot" + (", in a thread under ‹his› message" if thread else "") + ". Write it as a "
            "Slack message: short and plain, no headings and no tables. Never call slack_send to "
            "answer ‹him›, or ‹he› gets it twice.",
            (f"- Everybody in {where} reads that answer, so put nothing in it that is ‹his› alone: "
             "nothing from ‹his› own direct messages, ‹his› mail or ‹his› private notes." if public else
             "- Only ‹he› reads that answer."),
            "- If it goes to a background job, say in your answer that it has started.",
            "- If you cannot tell what ‹he› wants, ask ‹him› in your answer. Never guess at something "
            "that cannot be undone.",
            "",
            "‹His› message:",
            row.text or "(nothing written)",
        ])
        turn = mail_turn.MailTurn(
            user_id=who.user_id, org_id=who.org_id,
            message_id=f"{slack.CASE_PREFIX}{conn.team_id}:{conv.channel_id}:{row.ts}",
            thread_id=f"{slack.CASE_PREFIX}{conn.team_id}:{conv.channel_id}:{thread}",
            from_owner=True, recall_words=row.text[:2000], chat_id=chat)
        limit = 8 * 60.0
        finished, said, trouble = await self.converse(who, chat, email_card(shown), brief, turn, limit)
        answer = (said or "").strip()
        if not answer:
            answer = ("I could not finish that: " + trouble + ".") if trouble else ""
        if not answer:
            return
        try:
            await asyncio.to_thread(slack.post_message, conn, channel=conv.channel_id, text=answer,
                                    thread_ts=thread, kind="answer_to_owner",
                                    to_said=f"{row.author_name} in {where}")
        except (slack.SlackError, slack.NotSetUp, ValueError) as exc:
            log.warning("slack: the answer to the owner's Slack message could not be posted: %s", exc)

    async def _case(self, conn, who, conv, row, author) -> None:
        """Somebody else's message to Rouh: a case, like an email from them, when the owner set them
        up; anybody else is told Rouh can only help people the owner has set up (`rouh/slack_team.py`)."""
        from . import slack_team
        from . import trusted as trust

        sender = slack.SENDER + row.author_id
        email = (author.email if author is not None else "") or ""
        contact = await asyncio.to_thread(self._trusted, trust.TrustStore(), who, email, sender)
        where = self.where_said(conv)
        thread = self.thread_of(conv, row)
        if not slack_team.set_up(contact):
            await self._not_set_up(conn, who, conv, row, contact, email=email, where=where, thread=thread)
            return
        desk = self.desk()
        if desk is None:
            log.warning("slack: a message to Rouh from Slack member %s was not taken: there is no case "
                        "desk on this server (no Google)", row.author_id)
            await asyncio.to_thread(lambda: type(row).objects.filter(id=row.id).update(handed="no desk"))
            return
        # Everybody else who reads the answer there, so it holds only what each of them may see.
        heard = await asyncio.to_thread(slack_team.audience, who, conn, conv, row.author_id)
        thread_key = f"{slack.CASE_PREFIX}{conn.team_id}:{conv.channel_id}:{thread}"
        message = {
            "id": f"{slack.CASE_PREFIX}{conn.team_id}:{conv.channel_id}:{row.ts}",
            "thread_id": thread_key,
            "from": f"{row.author_name} (on Slack)", "to": f"Rouh, in {where}", "cc": "",
            "subject": "Slack message",
            "body": row.text + (("\n\n[files: " + ", ".join(row.files) + "]") if row.files else ""),
            "date": formatdate(row.at, localtime=True), "attachments": [],
            "channel": "slack", "slack_team": conn.team_id, "slack_workspace": conn.team_name,
            "slack_channel": conv.channel_id, "slack_ts": row.ts, "slack_thread": thread,
            "slack_where": where, "slack_user": row.author_id,
            "slack_account": f"{row.author_name}" + (f" <{email}>" if email else "")
            + f" (Slack member {row.author_id} of {conn.team_name or 'the workspace'})",
            "slack_audience": heard["ids"], "slack_audience_unknown": bool(heard.get("unknown")),
            "slack_audience_said": heard.get("said") or "",
        }
        said = (f"Slack says it came from its member {row.author_name}"
                + (f", whose Slack address {email} Slack confirmed" if email else "")
                + f", which is one of {contact.name}'s addresses you trusted"
                + f", in the {conn.team_name or 'connected'} workspace")
        chat = ""
        open_chat = getattr(desk.alerts, "open_chat", None) or self.open_chat
        if open_chat is not None:
            from .telegram_guests import chat_of_thread

            was = await asyncio.to_thread(chat_of_thread, who.user_id, who.org_id, thread_key)
            chat = await open_chat(was, f"💬 {row.author_name}: {' '.join(row.text.split())[:50]}")
        case_id = await desk.take(who, message, contact=contact, chat=chat, identity_ok=True,
                                  identity_said=said[:300], sender=sender, sender_name=row.author_name,
                                  soon=True)
        await asyncio.to_thread(lambda: type(row).objects.filter(id=row.id).update(handed=f"case:{case_id}"))
        log.info("slack: a message from Slack member %s is case %s", row.author_id, case_id)

    async def _not_set_up(self, conn, who, conv, row, contact, *, email: str, where: str, thread: str) -> None:
        """Somebody the owner has not set up: one polite answer where they asked, and the owner told
        once for each person, with a button to set them up (`slack_team.tell_owner`)."""
        from . import mail_outbox, slack_team

        owner = ((who.name or "").split() or ["‹owner›"])[0]
        sent = await mail_outbox.slack_not_set_up(
            who, conn, channel=conv.channel_id, thread=thread, to=slack.SENDER + row.author_id,
            to_said=f"{row.author_name} in {where}", text=slack_team.stranger_text(owner, row.author_name))
        told = await asyncio.to_thread(
            slack_team.tell_owner, who, conn, slack_id=row.author_id, name=row.author_name, email=email,
            contact=contact, where=where, said=row.text)
        await asyncio.to_thread(lambda: type(row).objects.filter(id=row.id).update(
            handed="not set up" if sent.ok else f"not set up, answer {sent.state}"))
        log.info("slack: Slack member %s is not set up: answered (%s), owner %s", row.author_id, sent.state,
                 "told" if told else "told before")

    @staticmethod
    def _trusted(store, who, email: str, sender: str):
        """The trusted contact whose ticked address is the one on this Slack account, switched on
        or not, or None."""
        from .models import TrustedAddress

        if not email:
            return None
        found = TrustedAddress.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                              address=email.lower()).values_list("contact_id", flat=True).first()
        if found is None:
            return None
        contact = store.get(who.user_id, who.org_id, found)
        if contact is not None and sender not in contact.slack:
            contact.slack = [*contact.slack, sender]
        return contact

    # --- reading back -------------------------------------------------------------------------

    def backfill(self, org: str, *, reason: str, only: str = "") -> None:
        """The last `slack.BACKFILL_DAYS` days read back, on a thread of its own: everything Rouh can read, or one
        conversation (`only`). One at a time per organisation; a second asks after the first."""
        key = f"{org}:{only}"
        running = self._backfilling.get(key)
        if running is not None and running.is_alive():
            return

        def run():
            from django.db import connection as db

            try:
                backfill(org, only=only, reason=reason)
            except Exception:  # noqa: BLE001 - said on the page
                log.exception("slack: reading back failed")
            finally:
                db.close()
                # What was read back is read for promises that are not yet due.
                self.said_something()

        thread = threading.Thread(target=run, name=f"slack-backfill-{org}", daemon=True)
        self._backfilling[key] = thread
        thread.start()


def backfill_due(conn) -> str:
    """Why the whole look back is to run now, or "": it never finished, or it finished over fewer
    days than `slack.BACKFILL_DAYS` (one from before that a finished look back said its days was 30)."""
    state = conn.backfill or {}
    if not state.get("finished_at"):
        return "the look back did not finish" if state.get("started_at") else "the first connection"
    covered = int(state.get("days") or 30)
    if covered < slack.BACKFILL_DAYS:
        return f"the look back was {covered} days and is {slack.BACKFILL_DAYS} now"
    return ""


def backfill(org: str, *, only: str = "", reason: str = "", days: int = slack.BACKFILL_DAYS) -> dict:
    """Every conversation Rouh can read, or one, read back over the last `days`: each message with
    `conversations.history`, each thread with `conversations.replies`. Returns counts."""
    conn = slack.connection(org)
    if conn is None or not conn.bot_sealed:
        return {}
    oldest = f"{time.time() - days * 86400:.6f}"
    bot = slack.bot(conn)
    mine = slack.user_client(conn)
    state = dict(conn.backfill or {})
    if not only:
        state.update(started_at=time.time(), finished_at=0, days=days, conversations=0, messages=0,
                     said=f"Reading back the last {days} days ({reason}).")
        slack._set(conn.id, backfill=state)
    seen: dict[str, object] = {}
    try:
        for info in bot.pages("conversations.list", "channels", types="public_channel,private_channel,mpim,im",
                              exclude_archived="true", limit=200):
            row = slack.keep_conversation(conn, info)
            if row is not None:
                seen[row.channel_id] = row
        if mine is not None:
            for info in mine.pages("conversations.list", "channels", types=",".join(slack.USER_KINDS),
                                   exclude_archived="true", limit=200):
                if str(info.get("id") or "") in seen:
                    continue
                row = slack.keep_conversation(conn, info, private=True)
                if row is not None:
                    seen[row.channel_id] = row
    except slack.SlackError as exc:
        state.update(said=f"Slack would not list the conversations ({exc.error}).")
        slack._set(conn.id, backfill=state)
        return state
    got_conversations = got_messages = 0
    for cid, conv in seen.items():
        if only and cid != only:
            continue
        if not (conv.is_member or conv.private):
            continue
        client = mine if conv.private else bot
        if client is None:
            continue
        n = _read_back(conn, conv, client, oldest)
        got_conversations += 1
        got_messages += n
        from .models import SlackConversation

        SlackConversation.objects.filter(id=conv.id).update(backfilled_at=time.time())
        if not only:
            state.update(conversations=got_conversations, messages=got_messages)
            slack._set(conn.id, backfill=state)
    if not only:
        state.update(finished_at=time.time(), conversations=got_conversations, messages=got_messages,
                     said=f"Read back {got_messages} message{'' if got_messages == 1 else 's'} from "
                          f"{got_conversations} conversation{'' if got_conversations == 1 else 's'}.")
        slack._set(conn.id, backfill=state)
    log.info("slack: read back %d message(s) from %d conversation(s) (%s)", got_messages, got_conversations,
             reason or "asked")
    return {"conversations": got_conversations, "messages": got_messages}


def _read_back(conn, conv, client, oldest: str) -> int:
    """One conversation's messages since `oldest`, and every thread in it."""
    n = 0
    try:
        for m in client.pages("conversations.history", "messages", channel=conv.channel_id, oldest=oldest,
                              limit=200):
            row, _ = slack.keep_message(conn, conv, m, client=None)
            n += 1 if row is not None else 0
            if int(m.get("reply_count") or 0) and m.get("thread_ts"):
                for r in client.pages("conversations.replies", "messages", channel=conv.channel_id,
                                      ts=m["thread_ts"], oldest=oldest, limit=200):
                    if str(r.get("ts")) == str(m.get("ts")):
                        continue
                    row, _ = slack.keep_message(conn, conv, r)
                    n += 1 if row is not None else 0
    except slack.SlackError as exc:
        log.info("slack: %s could not be read back: %s", slack.conversation_label(conv), exc.error)
    return n
