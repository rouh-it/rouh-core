"""One message's memory: automatic recall and the seed look-up, from the moment the message is said until
everything they looked up has found a place, and the timeline of it under the message.

Petar, by voice, 10 October 2026: "I definitely don't want answers to be limited to 2.5 seconds. At the very
least, we can do better than that, and this is what we're going to do. I want you to visualize the background
calls and the parallel calls, and see in 2.5 seconds whether they returned results or timed out. That will
help me get a sense of what's going on when I type a message."

So, for every message recall applies to (`rouh/synapse/autorecall.py` says which):

- **The first request waits**, from the moment the message came, until every look-up is back or
  `recall_wait_ms` has gone by (a number of Master's, 10 seconds since 14 October 2026, 6 before), and takes
  what is back.
  The seed look-up's own short wait is unchanged (`brain.seeds_for_turn`); what it found while recall was
  being waited for goes into the same first request.
- **Nothing is dropped.** The look-ups run on to `autorecall.CEILING_S`. What comes back after the first
  request went goes in after the tool results of the turn's next request (`late`), and what comes back after
  the turn's last request is kept for the next message in the same chat (`carried`, `_carried`), the seeds'
  matches too.
- **Every look-up is a bar** on the message's timeline, with when it started and ended, how many items it
  found and its outcome: `running`, `in_time` (back for the first request, with something), `empty` (back
  in time with nothing), `late`, `carried`, or `failed` (an error, or not back by the ceiling). The page is
  sent the whole timeline (`recall` on the socket, PROTOCOL.md) as it changes, and draws it under the
  message (`recallLine` in app/transcript.js); it is kept with the message (`RecallTimeline`), and once the
  turn is over and every look-up has ended, and both models reading the message, the slower one too, it goes
  into the recall trace in Master's Activity (`autorecall.record`).
"""
from __future__ import annotations

import asyncio
import functools
import logging
import threading
import time
import uuid

from . import dbwork

log = logging.getLogger("rouh.recalling")

#: Writes of timelines, one at a time and in order, so the newest is what is kept.
_KEEP = dbwork.Executor(max_workers=1, thread_name_prefix="recall-keep")

#: What is still to come for each chat from messages whose turns are over: `MessageMemory`s, oldest first.
_carried: dict[str, list["MessageMemory"]] = {}
_carried_lock = threading.Lock()
#: How long a message's late memory waits for the next message in its chat, in seconds.
CARRY_FOR_S = 6 * 3600
#: And how many messages' worth a chat holds at most.
CARRY_MOST = 4

LATE_PREFIX = "(Rouh's software, not the person:) "


def _ms(since: float, at: float | None = None) -> int:
    return int(((time.monotonic() if at is None else at) - since) * 1000)


class MessageMemory:
    """What one message looked up, as it goes. Made by `brain.start_recall`, read by the turn at its first
    request (`first`), between its requests (`late`) and at its end (`over`), and by the next message in the
    same chat for what it carried (`take_carried`)."""

    def __init__(self, session_id: str, text: str, emit, loop, *, seeds=None, root=None,
                 source: str = "message", keep=None) -> None:
        self.session_id, self.text, self.emit, self.loop = session_id, text, emit, loop
        self.seeds, self.root, self.source, self.keep = seeds, root, source, keep
        self.began, self.began_at = time.monotonic(), time.time()
        from .synapse import autorecall

        self.look = autorecall.Lookups()
        self.wait_s = autorecall.wait_seconds()
        self.future = None                       # the recall's thread: (ds, what it found) or None
        self.ds = None
        self.applies = None                      # recall: None until its thread knows
        self.first_ms = None                     # when the first request went, from `began`
        self.over_ms = None                      # when the turn ended
        self.outcome: dict[str, str] = {}        # look-up id -> outcome, once decided
        self.sent: list[str] = []                # item ids any request has carried
        self.used: list[dict] = []               # {id, kind, title, when}: what went in, and where
        self.tokens = 0
        self.seed_outcome = ""
        self.seed_ids: list[str] = []
        self.carried_in: list[dict] = []         # what this message was given from earlier ones
        self.previous: list[MessageMemory] = []  # earlier messages' memory, still to be given
        self.message_id = None
        self.recorded = False
        self.trace_id = ""
        self.given_to = None                     # the message that was handed what this one carried
        self._given: set[str] = set()            # carried look-ups already handed on
        self.lock = threading.RLock()
        self.tag = uuid.uuid4().hex[:8]

    # --- starting ---------------------------------------------------------------------------------------------

    def start(self, words: str) -> None:
        """The recall's thread, started now, with the context it was started in (whose turn it is)."""
        import contextvars

        self.previous = take_carried(self.session_id)
        run = functools.partial(contextvars.copy_context().run, self._recall, words)
        self.future = self.loop.run_in_executor(None, run)
        self.future.add_done_callback(lambda _f: self._maybe_finish())
        if self.seeds is not None:
            self.seeds.future.add_done_callback(lambda _f: self._seeds_back())

    def _recall(self, words: str):
        """On a thread: the person's Master, its switch, and the look-ups; None where recall does not apply."""
        from .synapse import autorecall, db as synapse_db
        from .synapse import chat as synapse_chat

        try:
            if not words or not synapse_db.ready() or synapse_chat.place_of_chat(self.session_id):
                self.applies = False
                return None
            ds = synapse_chat.master_for_turn()
            if not ds:
                self.applies = False
                return None
            autorecall.register(str(ds["org_id"]))
            if not autorecall.on(ds["org_id"]):
                self.applies = False
                return None
            self.ds, self.applies = ds, True
            self.wait_s = autorecall.wait_seconds(ds)
            return ds, autorecall.run(ds, words, chat_id=self.session_id, look=self.look, say=self._said)
        except Exception:  # noqa: BLE001 - the turn goes on without it
            log.exception("automatic recall failed")
            self.applies = bool(self.applies)
            return None
        finally:
            self.publish()

    def _said(self, event: str, call) -> None:
        """A look-up started or ended: its twig on the orb, and the timeline again."""
        if call is not None:
            message = {"type": "tool_start" if event == "start" else "tool_end",
                       "id": f"recall-{self.tag}-{call.id}", "name": call.tool, "where": "rouh", "orb_only": True}
            if event == "start":
                message.update({"input": {}, "what": call.what, "detail": call.what + (
                    ", for what to look up in Synapse Master" if call.tool == "recall_pick" else ", in Synapse Master")})
            else:
                thing = "thing" if call.tool == "recall_pick" else "item"
                message.update({"ok": call.ok, "summary": call.error or
                                ("answered first: " if call.won else "answered second, not used: "
                                 if call.tool == "recall_pick" else "")
                                + f"{call.count} {thing}{'' if call.count == 1 else 's'} in {call.ms} ms"})
                if not call.ok and call.tool != "recall_pick":
                    with self.lock:
                        if self.outcome.get(call.id) in (None, "carried"):
                            self.outcome[call.id] = "failed"
            self._send(message)
        self.publish()

    def _seeds_back(self) -> None:
        try:
            got = self.seeds.result()
        except Exception:  # noqa: BLE001
            got = None
        with self.lock:
            if isinstance(got, dict):
                self.seed_ids = [x["id"] for x in (got.get("named") or []) + (got.get("strong") or [])]
            else:
                # Not wired to anything (switched off, no Master, a chat of Synapse's own): no bar at all.
                self.seed_outcome = "none"
        self.publish()
        self._maybe_finish()

    # --- the turn ---------------------------------------------------------------------------------------------

    async def wait_first(self) -> None:
        """Until every look-up is back, or `recall_wait_ms` from the moment the message came."""
        while self.future is not None and not self.future.done():
            left = self.began + self.wait_s - time.monotonic()
            if left <= 0:
                break
            # The thread reads the dataset's wait a moment after the turn starts, and it may be shorter than the
            # last one read: so the wait is measured again every few moments.
            await asyncio.wait({self.future}, timeout=min(left, 0.2))

    async def first(self, seeds_skip=()) -> str:
        """The block for the turn's first request: what is back once `wait_first` is over, and what earlier
        messages in this chat carried. "" when there is nothing."""
        await self.wait_first()
        self.first_ms = _ms(self.began)
        try:
            text = await asyncio.to_thread(self._first_block, list(seeds_skip))
        except Exception:  # noqa: BLE001
            log.exception("automatic recall's block could not be made")
            text = ""
        self.publish()
        return text

    def _first_block(self, seeds_skip: list[str]) -> str:
        from .synapse import autorecall

        with self.lock:
            self.sent.extend(seeds_skip)
            ended = [c for c in list(self.look.calls) if c.ended]
            for c in ended:
                self.outcome[c.id] = ("in_time" if c.count else "empty") if c.ok else "failed"
            parts = []
            if any(c.ok for c in ended) and self.ds is not None:
                made = autorecall.block(self.ds, self.look.found([c.id for c in ended if c.ok]), skip=self.sent)
                parts.append(self._took(made, "first"))
            parts.append(self._from_previous())
            return "\n\n".join(p for p in parts if p)

    def _took(self, made: dict, when: str) -> str:
        """Note what a block carried, and give its text."""
        if not made.get("text"):
            return ""
        self.sent.extend(made.get("shown") or [])
        self.used.extend({**i, "when": when} for i in made.get("items") or [])
        self.tokens += int(made.get("tokens") or 0)
        return made["text"]

    def _from_previous(self) -> str:
        """What earlier messages in this chat looked up and had not given yet, for whatever of it is back."""
        parts = []
        for prev in list(self.previous):
            got = prev.give_carried(self.message_id, self.sent)
            if got["text"]:
                parts.append(got["text"])
                self.sent.extend(got["shown"])
                self.carried_in.append({"text": prev.text[:120], "items": len(got["shown"]),
                                        "titles": got["titles"][:8]})
            if got["finished"]:
                self.previous.remove(prev)
        return "\n\n".join(parts)

    def late(self) -> str:
        """What came back since the last request, for the next one, after its tool results; "" for nothing.
        Called on a thread between two requests of the turn."""
        from .synapse import autorecall

        with self.lock:
            fresh = [c for c in list(self.look.calls) if c.ended and c.id not in self.outcome]
            if not fresh and not self.previous:
                return ""
            for c in fresh:
                self.outcome[c.id] = "late" if c.ok else "failed"
            parts = []
            if any(c.ok for c in fresh) and self.ds is not None:
                given = [c.id for c in self.look.calls if self.outcome.get(c.id) in ("in_time", "empty", "late")]
                made = autorecall.block(self.ds, self.look.found(given), skip=self.sent, label=autorecall.LATE_LABEL)
                parts.append(self._took(made, "late"))
            parts.append(self._from_previous())
            text = "\n\n".join(p for p in parts if p)
        self.publish()
        return LATE_PREFIX + text if text else ""

    def over(self) -> None:
        """The turn has ended, however it ended: whatever is still to come is kept for the next message."""
        with self.lock:
            if self.over_ms is not None:
                return
            self.over_ms = _ms(self.began)
            for c in list(self.look.calls):
                if c.id not in self.outcome:
                    self.outcome[c.id] = "carried" if (c.ok or not c.ended) else "failed"
            seeds_left = False
            if self.seeds is not None and self.seed_outcome in ("", "back"):
                if not self.seeds.done():
                    self.seed_outcome, seeds_left = "carried", True
                elif self.seeds.sent != "all" and self._seed_rest(peek=True):
                    self.seed_outcome, seeds_left = "carried", True
                else:
                    self.seed_outcome = "late" if self.seed_outcome == "back" and self.seed_ids else (
                        "empty" if not self.seed_ids else "in_time")
            keep = any(v == "carried" for v in self.outcome.values()) or seeds_left
            # What earlier messages had still to give, and did not get to, waits for the next one in turn.
            for prev in self.previous:
                carry(prev)
            self.previous = []
        if keep:
            carry(self)
        self.publish()
        self._maybe_finish()

    def written(self, message_id: int) -> None:
        """The message is in the conversation now, under this id: the timeline is kept with it from here."""
        self.message_id = int(message_id)
        self.publish()

    # --- what an earlier message hands on ----------------------------------------------------------------------

    def give_carried(self, to_message, skip) -> dict:
        """What this message's turn did not get to, for a later message's request: `{"text", "shown",
        "titles", "finished"}`. `finished` once nothing more can come."""
        from .synapse import autorecall

        out = {"text": "", "shown": [], "titles": [], "finished": False}
        with self.lock:
            parts = []
            back = [c for c in self.look.back() if self.outcome.get(c.id) == "carried" and c.id not in self._given]
            if back and self.ds is not None:
                made = autorecall.block(self.ds, self.look.found(), skip=list(self.sent) + list(skip),
                                        label=autorecall.CARRIED_LABEL)
                if made.get("text"):
                    parts.append(made["text"])
                    out["shown"] += made["shown"]
                    out["titles"] += [i["title"] for i in made["items"]]
                    self.sent.extend(made["shown"])
                    self.used.extend({**i, "when": "next"} for i in made["items"])
                    self.tokens += int(made.get("tokens") or 0)
                self._given.update(c.id for c in back)
            seeds = self.seeds
            if seeds is not None and seeds.done() and seeds.sent != "all":
                block = self._seed_rest()
                if block:
                    parts.append("From the person's previous message in this chat, back only after that answer "
                                 "had ended:\n" + block)
                    out["titles"].append("seed matches")
            seeds_done = seeds is None or seeds.done()
            calls_done = self.future is not None and self.future.done()
            out["finished"] = seeds_done and calls_done and all(
                c.id in self._given or self.outcome.get(c.id) != "carried" for c in self.look.calls)
            out["text"] = "\n\n".join(parts)
        if out["text"]:
            self.given_to = to_message
            self.publish()
        if out["finished"]:
            self._maybe_finish()
        return out

    def _seed_rest(self, peek: bool = False) -> str:
        """The seeds' block the turns have not carried yet, marked as carried unless only peeked at."""
        try:
            got = self.seeds.result()
        except Exception:  # noqa: BLE001
            return ""
        if not isinstance(got, dict):
            return ""
        block = got.get("match_block") if self.seeds.sent == "named" else got.get("block")
        if not peek:
            self.seeds.sent = "all"
        return block or ""

    def seeds_given(self, when: str) -> None:
        """The seeds went into a request: `in_time` (the first) or `late` (a later one)."""
        with self.lock:
            if when == "in_time" and not self.seed_ids:
                when = "empty"
            self.seed_outcome = when
        self.publish()

    # --- the timeline -----------------------------------------------------------------------------------------

    def timeline(self) -> dict:
        """The message's timeline, as the page draws it and as it is kept: every time in ms from `began`."""
        from .synapse import autorecall

        with self.lock:
            bars = []
            seeds = self.seeds
            if seeds is not None and self.seed_outcome != "none":
                ended = seeds.ended
                outcome = self.seed_outcome if self.seed_outcome not in ("", "back") else (
                    "running" if ended is None else "back")
                bars.append({"id": "seeds", "tool": "seeds", "what": "Seeds: the whole message, by words and meaning",
                             "start_ms": _ms(self.began, seeds.began), "end_ms": None if ended is None
                             else _ms(self.began, ended), "count": len(self.seed_ids), "outcome": outcome})
            readers = {id(r.call): r for r in (self.look.pick.readers if self.look.pick is not None else [])}
            for pick in list(self.look.pick_calls):
                # Each model reading the message: the one whose answer was used is in time when its look-ups
                # could still reach the first request; the other, back with an answer, was slower.
                if not pick.started:
                    continue
                outcome = ("running" if not pick.ended else "failed" if not pick.ok else
                           ("in_time" if self.first_ms is None or _ms(self.began, pick.ended_at) <= self.first_ms
                            else "late") if pick.won else "slower")
                bars.append({"id": pick.id, "tool": pick.tool, "what": pick.what[len("Reading the message with "):]
                             if pick.what.startswith("Reading the message with ") else pick.what,
                             "start_ms": _ms(self.began, pick.started), "end_ms": None if pick.ended_at is None
                             else _ms(self.began, pick.ended_at), "count": pick.count, "outcome": outcome,
                             "error": pick.error, "won": pick.won, **_reader(readers.get(id(pick)))})
            for c in list(self.look.calls):
                outcome = self.outcome.get(c.id)
                if outcome is None:
                    outcome = "failed" if c.ended and not c.ok else ("back" if c.ended else "running")
                bars.append({"id": c.id, "tool": c.tool, "what": c.what[len("Recalling "):] if c.what.startswith(
                    "Recalling ") else c.what, "start_ms": _ms(self.began, c.started),
                    "end_ms": None if c.ended_at is None else _ms(self.began, c.ended_at), "count": c.count,
                    "outcome": outcome, "error": c.error, **_found(self.look.results.get(c.id))})
            done = (self.future is not None and self.future.done() and (seeds is None or seeds.done())
                    and self.over_ms is not None)
            return {
                "v": 1, "source": self.source, "msg": self.message_id, "root": self.root,
                "began": self.began_at, "elapsed_ms": _ms(self.began), "state": "done" if done else "running",
                "applies": self.applies, "wait_ms": int(self.wait_s * 1000),
                "mark_ms": int(autorecall.OLD_BUDGET_S * 1000), "ceiling_ms": int(autorecall.CEILING_S * 1000),
                "first_ms": self.first_ms, "over_ms": self.over_ms,
                "named": [{"kind": e.kind, "label": e.label} for e in self.look.entities],
                "named_ms": self.look.names_ms if self.look.named else None,
                "pick": self.look.pick.shown() if self.look.pick is not None and self.look.named else None,
                "why": (("the model could not read it" if self.look.pick is not None and not self.look.pick.ok
                         else "nothing to look up") if self.look.named and not self.look.entities else ""),
                "bars": bars, "used": list(self.used), "tokens": self.tokens, "carried_in": list(self.carried_in),
                "seed_ids": list(self.seed_ids[:100]),
                # The recall's own trace in Master's Activity, once the turn is over and it is written
                # (`autorecall.record`), which the turn's record links to (`rouh/turnrecords.py`).
                **({"trace": self.trace_id} if self.trace_id else {}),
            }

    def publish(self) -> None:
        """The timeline to the chat's tabs, and kept with the message once it has an id. From any thread."""
        try:
            data = self.timeline()
        except Exception:  # noqa: BLE001 - a picture is never worth a turn
            log.exception("a recall timeline could not be made")
            return
        # Sent even when there is nothing to draw, so a line drawn for a seed look-up that then turned out
        # not to apply is taken down again.
        self._send({"type": "recall", "timeline": data, "msg": self.message_id,
                    "note": self.source != "message"})
        if not shown(data):
            return
        if self.message_id is not None and self.keep is not None:
            _KEEP.submit(self._keep, self.message_id, data)

    def _keep(self, message_id: int, data: dict) -> None:
        try:
            from django.db import close_old_connections

            close_old_connections()
            self.keep(message_id, self.session_id, data)
        except Exception:  # noqa: BLE001
            log.exception("a recall timeline could not be kept")

    def _record(self, write) -> None:
        """Master's Activity written, and the timeline kept again with the trace it made."""
        try:
            got = write()
        except Exception:  # noqa: BLE001
            log.exception("a recall could not be recorded")
            return
        if got:
            with self.lock:
                self.trace_id = str(got)
            self.publish()

    def _send(self, message: dict) -> None:
        try:
            asyncio.run_coroutine_threadsafe(self.emit(message), self.loop)
        except RuntimeError:  # the loop is closing: nobody is left to see it
            pass

    # --- the record -------------------------------------------------------------------------------------------

    def _maybe_finish(self) -> None:
        """Once the turn is over and every look-up has ended: the trace in Master's Activity, once."""
        with self.lock:
            if self.recorded or self.over_ms is None or self.future is None or not self.future.done():
                return
            if self.seeds is not None and not self.seeds.done():
                return
            self.recorded = True
        self.publish()
        try:
            back = self.future.result()
        except Exception:  # noqa: BLE001
            back = None
        if not back:
            return
        ds, got = back
        from .synapse import autorecall

        def record() -> None:
            # Once the slower model reading the message is back too, so its answer is kept with the other's.
            bars = self.timeline()["bars"]
            made = {"shown": list(self.sent), "tokens": self.tokens, "items": list(self.used),
                    "text": ""}
            _KEEP.submit(self._record, functools.partial(autorecall.record, ds, self.text, got, made,
                                                         chat_id=self.session_id, bars=bars))
            if self.sent:
                from . import evolution

                _KEEP.submit(functools.partial(evolution.used, autorecall.SWITCH, "recalled",
                                               detail=f"{len(self.sent)} things it found, in chat {self.session_id}"))

        pick = got.get("pick")
        if pick is None:
            record()
        else:
            pick.when_settled(record)


def _reader(r) -> dict:
    """What one model reading the message took and cost, for its bar."""
    if r is None:
        return {}
    return {"model": r.model, "cost": round(float(r.cost or 0), 6), "tokens_in": int(r.tokens_in or 0),
            "tokens_cached": int(r.tokens_cached or 0), "tokens_out": int(r.tokens_out or 0)}


def _found(got) -> dict:
    """The ids of what one look-up found, for its bar (`autorecall._in_thread`)."""
    if isinstance(got, dict):
        return {"ids": [str(x) for x in (got.get("ids") or [])][:100],
                **({"trace": str(got["trace"])} if got.get("trace") else {})}
    if isinstance(got, list):
        return {"ids": [str(r["id"]) for r in got if isinstance(r, dict) and r.get("id")][:100]}
    return {}


def shown(data: dict | None) -> bool:
    """Whether a timeline has anything to draw: a look-up, or recall that applied and found nothing named."""
    return bool(data) and (bool(data.get("bars")) or data.get("applies") is True and data.get("named_ms") is not None)


def carry(mm: MessageMemory) -> None:
    """Keep a message's memory for the next message in its chat."""
    with _carried_lock:
        held = [m for m in _carried.get(mm.session_id, []) if time.monotonic() - m.began < CARRY_FOR_S]
        held = [m for m in held if m is not mm] + [mm]
        _carried[mm.session_id] = held[-CARRY_MOST:]


def take_carried(session_id: str) -> list[MessageMemory]:
    """What earlier messages in this chat still have to give, for the message starting now."""
    with _carried_lock:
        held = _carried.pop(session_id, [])
    return [m for m in held if time.monotonic() - m.began < CARRY_FOR_S]
