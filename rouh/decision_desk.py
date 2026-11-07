"""The desk: what keeps the decisions true while Rouh runs (`rouh/decisions.py`).

Three jobs, in one loop:

- **Taking them in.** Every `SYNC_EVERY` seconds, and soon after anything says a source moved
  (`poke`: the heartbeat queued an approval, the one program's questions changed, a task's
  file was taken in), it syncs the install owner's decisions with their sources, and tells
  every tab of theirs how many wait (`decisions` on the socket), which is the count on the
  navigation's Now tab, the sidebar's Decisions row and in the Control Room. After every sync
  the count is read once more and told again if it is not what the tabs were last told
  (`level`), and a tab that connects is told it with the lists after its handshake
  (`runtime.Session.after_ready`), so no count is ever left behind on a screen.
- **Sending answers back.** An answer waits `decisions.UNDO_SECONDS` to be undone; then the
  desk claims it (`decisions.take`, so one process and one pass only) and awaits its source's
  `apply`, and writes down what the source said. A source that fails leaves it `failed`, and
  answerable again.
- **The phone.** A new question that is urgent ("now") and whose source does not tell the
  phone itself drops in on his screen as a notice (`rouh/notices.py`), and is sent to
  Telegram once if that notice is left there, with a button for each answer when they are few and
  short. A press is the person's own (`telegram_chat._press` lets only his through), and goes
  through `decisions.answer` like any other answer; an option that carries a gated risk asks
  for a second press that names the risk first. Once answered anywhere, its buttons come off.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Awaitable, Callable

from . import decision_gate, decision_sources, decisions, delegation

log = logging.getLogger("rouh.decision_desk")

#: How often the sources are read with nothing poking.
SYNC_EVERY = 30.0
#: How often answers past their undo window are looked for.
APPLY_EVERY = 1.0
#: How long after a poke the sync waits, so a burst of changes is one read.
POKE_GAP = 1.0
#: "Later" pressed on Telegram.
LATER_SECONDS = 3 * 3600

#: The desk Rouh runs, for the tool, the pages and the phone to reach.
LIVE: "Desk | None" = None


def _whose_key(who) -> str:
    return f"{who.user_id}/{who.org_id or ''}"


class Desk:
    def __init__(self, *, owner: Callable[[], object], push: Callable[[object, dict], Awaitable],
                 telegram=None, public_url: str = ""):
        self.owner = owner
        self.push = push
        self.telegram = telegram
        self.public_url = public_url
        self._poked: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        #: What every tab of each person's was last told, by "user/org" (`level`).
        self._last_counts: dict[str, dict] = {}
        #: async (who, address, subject, body): one email from Rouh's own mailbox, for the
        #: briefs a delegate is sent (`delegation.brief_delegates`). None sends nothing.
        self.mail = None

    # --- running -------------------------------------------------------------------------

    def start(self) -> None:
        global LIVE
        LIVE = self
        self._poked = asyncio.Event()
        self._tasks = [asyncio.create_task(self._syncing(), name="decisions-sync"),
                       asyncio.create_task(self._applying(), name="decisions-apply")]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._tasks = []

    def poke(self) -> None:
        """A source moved: read them all again in a moment."""
        if self._poked is not None:
            self._poked.set()

    async def _syncing(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._poked.wait(), timeout=SYNC_EVERY)
                await asyncio.sleep(POKE_GAP)
            except asyncio.TimeoutError:
                pass
            self._poked.clear()
            with contextlib.suppress(Exception):
                who = await asyncio.to_thread(self.owner)
                if who is not None:
                    await self.sync(who)
                    await self.judge(who)
            # Apart from the sync, so a sync that failed still lets a count that moved be told.
            with contextlib.suppress(Exception):
                who = await asyncio.to_thread(self.owner)
                if who is not None:
                    await self.level(who)

    async def judge(self, who) -> None:
        """The questions the gate still has to judge (`decision_gate.judge_pending`), between
        syncs so no page waits on a model; whatever it decided is made, or cleared, at once."""
        try:
            decided = await decision_gate.judge_pending(who)
        except Exception:
            log.exception("decisions: the gate could not judge this pass")
            return
        if decided:
            await self.sync(who)
        if decided >= decision_gate.PER_PASS:
            self.poke()               # more may be waiting: the next pass in a moment

    async def _applying(self) -> None:
        while True:
            await asyncio.sleep(APPLY_EVERY)
            try:
                await self.apply_due()
            except Exception:
                log.exception("decisions: answers could not be sent back this pass")

    # --- the work ------------------------------------------------------------------------

    async def sync(self, who, kinds=None) -> decisions.Synced:
        got = await asyncio.to_thread(decisions.sync, who, kinds)
        if got.changed:
            await self.tell(who)
        for ident in got.new:
            with contextlib.suppress(Exception):
                await self._phone_new(who, ident)
        await self._brief_delegates(who)
        return got

    async def _brief_delegates(self, who) -> None:
        """The decisions newly waiting on somebody the owner gave authority over them, emailed to
        them once each (`rouh/delegation.py`)."""
        if self.mail is None:
            return
        mail = self.mail

        async def send(address, subject, body):
            return await mail(who, address, subject, body)

        try:
            went = await delegation.brief_delegates(who, send)
        except Exception:
            log.exception("decisions: the delegates' briefs could not be sent")
            return
        if went:
            log.info("decisions: %d decision(s) emailed to the people who decide them", went)

    async def tell(self, who, force: bool = False) -> None:
        """Every tab of theirs: how many wait, and that the list moved."""
        counts = await asyncio.to_thread(decisions.counts, who)
        self._last_counts[_whose_key(who)] = counts
        await self.push(who, {"type": "decisions", **counts})

    async def level(self, who) -> bool:
        """Every tab of theirs told the count again when it is not what they were last told.

        Petar, 4 November 2026: the count on Now "doesn't grow more than that and it doesn't
        change". A tab is told the count only when something here moved it (`tell`), so a count
        that moved any other way stayed wrong on every screen until the page was loaded again:
        a `tell` whose read failed (the database out of connections, task 137), a delegate's
        grant given or taken back, a row another process wrote. Checked after every sync, one
        small count, so whatever moved it the screens catch up within `SYNC_EVERY`. True when
        it was told."""
        counts = await asyncio.to_thread(decisions.counts, who)
        key = _whose_key(who)
        if self._last_counts.get(key) == counts:
            return False
        self._last_counts[key] = counts
        await self.push(who, {"type": "decisions", **counts})
        return True

    async def apply_due(self) -> None:
        rows = await asyncio.to_thread(decisions.due)
        for row in rows:
            if not await asyncio.to_thread(decisions.take, row.id):
                continue
            who = _Who(row.user_id, row.org_id)
            source = decision_sources.sources().get(row.source)
            await asyncio.to_thread(decisions._event, row, "applying", channel=row.channel)
            try:
                got = (await source.apply(who, row, row.channel) if source is not None
                       else decisions.Applied(False, "Nothing asks this any more."))
            except Exception as exc:  # noqa: BLE001 - written on the decision
                log.exception("decisions: #%s could not be sent back to its %s", row.id, row.source)
                got = decisions.Applied(False, f"It failed: {type(exc).__name__}: {exc}")
            await asyncio.to_thread(decisions.finished, row.id, got)
            await self.tell(who)
            if row.telegram_message:
                with contextlib.suppress(Exception):
                    await self.telegram.rebutton(int(row.telegram_message), None)
            # The source moved: read it again, so its own pages say so.
            self.poke()

    # --- the four things a person does, for the pages, the tool and the phone -------------

    async def answer(self, who, ident, **kw) -> dict:
        got = await asyncio.to_thread(lambda: decisions.answer(who, ident, **kw))
        await self.tell(who)
        return got

    async def delegate(self, who, ident, channel: str = "screen") -> dict:
        got = await asyncio.to_thread(lambda: decisions.delegate(who, ident, channel=channel))
        await self.tell(who)
        return got

    async def act(self, who, ident, act: str, body: dict, channel: str = "screen") -> dict:
        """One press on a decision, from a page: answer, delegate, snooze, wake, undo,
        dismiss, reopen, not_this. Raises `decisions.Refused` with the words to show."""
        if act == "answer":
            return await self.answer(who, ident, choice=body.get("choice"),
                                     text=str(body.get("text") or ""),
                                     confirm=str(body.get("confirm") or ""), channel=channel,
                                     items=body.get("items") if isinstance(body.get("items"), dict)
                                     else None)
        if act == "delegate":
            return await self.delegate(who, ident, channel)
        if act == "snooze":
            got = await asyncio.to_thread(decisions.snooze, who, ident, body.get("until"),
                                          channel=channel)
        elif act == "wake":
            got = await asyncio.to_thread(decisions.wake, who, ident)
        elif act == "undo":
            got = await asyncio.to_thread(decisions.undo, who, ident)
        elif act == "dismiss":
            got = await asyncio.to_thread(decisions.dismiss, who, ident, channel=channel)
            self.poke()
        elif act == "reopen":
            # Undo what its source closed by itself (a promise a later Slack message showed kept).
            got = await asyncio.to_thread(decisions.reopen, who, ident, channel=channel)
            self.poke()
        elif act == "not_this":
            # What he said in a chat does not answer it (`rouh/answered_in_chat.py`).
            from . import answered_in_chat

            got = {"ok": True, "said": "It stays open, and those words are not offered for it again.",
                   "decision": await asyncio.to_thread(answered_in_chat.not_this, who, ident)}
        else:
            raise decisions.Refused("That is not something a decision can do.")
        await self.tell(who)
        return got

    # --- the phone -----------------------------------------------------------------------

    def _phone_ready(self) -> bool:
        tg = self.telegram
        try:
            return bool(tg is not None and tg.configured())
        except Exception:
            return False

    async def _phone_new(self, who, ident: int) -> None:
        """A new question that cannot wait: on his screen first, as a notice that carries it,
        and on Telegram, with its buttons, only if the notice is left there
        (`rouh/notices.py`, `phone_decision`)."""
        d = await asyncio.to_thread(decisions.get, who, ident)
        if d is None or d["urgency"] != "now" or d["status"] != decisions.OPEN:
            return
        source = decision_sources.sources().get(d["source"])
        if source is None or source.notifies:
            return
        if d.get("decider"):
            # Somebody the owner gave authority over it decides it, and is emailed it.
            return
        from . import notices

        await notices.notify(
            who=who, kind="decision", key=f"decision:{ident}",
            title=f"{decisions.name_of(d)}: {d['title'] or d['question']}",
            body=d["question"] if d["title"] else (d.get("why") or ""),
            link=decisions.page_of(d), link_label="Answer it",
            decision_id=int(ident))

    async def phone_decision(self, who, ident: int) -> bool:
        """The decision's own Telegram message, once its notice was left on the screen. False
        when it is not waiting any more, or there is no phone to send it to."""
        d = await asyncio.to_thread(decisions.get, who, ident)
        if d is None or d["status"] != decisions.OPEN or not self._phone_ready():
            return False
        ids = await self.telegram.send_parts(decisions.telegram_text(d, self.public_url),
                                             buttons=decisions.telegram_buttons(d), who=who)
        if ids and ids[-1]:
            await asyncio.to_thread(decisions.set_telegram, ident, ids[-1])
            await asyncio.to_thread(decisions.told, ident, "sent with its answers as buttons")
        return bool(ids)

    async def press(self, who, query_id: str, message_id: int, what: str, ident: int,
                    option: str) -> None:
        """A press on one of a decision's buttons on Telegram, already known to be his."""
        tg = self.telegram
        d = await asyncio.to_thread(decisions.get, who, ident)
        if d is None:
            await tg.pressed(query_id, "That question is not there any more.")
            await tg.rebutton(message_id, None)
            return
        if what == "cancel":
            await tg.pressed(query_id, "Not sent.")
            await tg.rebutton(message_id, decisions.telegram_buttons(d))
            return
        if what == "later":
            try:
                await asyncio.to_thread(decisions.snooze, who, ident, time.time() + LATER_SECONDS,
                                        channel="telegram")
            except decisions.Refused as exc:
                await tg.pressed(query_id, str(exc)[:190])
                await tg.rebutton(message_id, None)
                return
            await self.tell(who)
            await tg.pressed(query_id, "Later: it comes back in three hours.")
            await tg.rebutton(message_id, None)
            return
        picked = next((o for o in d["options"] if o["id"] == option), None)
        if picked is None:
            await tg.pressed(query_id, "That answer is not one of its answers any more.")
            return
        if what == "answer" and d["gated"] and picked.get("go"):
            # The risk itself, named, and a second press for it.
            await tg.pressed(query_id, "Confirm it first.")
            await tg.rebutton(message_id, decisions.confirm_buttons(d, option))
            await tg.send(f"⚠ {d['risk_words']}: {d['risk_note'] or d['question']}\n"
                          f"Press “Yes: {picked['label']}” to confirm that, or Cancel.", who=who)
            return
        try:
            got = await self.answer(who, ident, choice=[option],
                                    confirm=d["risk"] if what == "confirm" else "",
                                    channel="telegram")
        except decisions.Refused as exc:
            await tg.pressed(query_id, str(exc)[:190])
            await tg.rebutton(message_id, None)
            return
        await tg.pressed(query_id, f"Answered: {picked['label']}")
        await tg.rebutton(message_id, None)
        if not got.get("again"):
            await tg.send(f"Answered: {picked['label']}. It goes in "
                          f"{int(decisions.UNDO_SECONDS)} seconds; undo it on the Decisions "
                          "page until then.", who=who)


class _Who:
    def __init__(self, user_id, org_id):
        self.user_id, self.org_id = str(user_id), str(org_id)
