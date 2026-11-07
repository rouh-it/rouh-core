"""The timeline of one turn: every step from the message reaching the server to the
answer, drawn live in the reply and kept with the turn.

Petar, 23 October 2026 (card 1842, "Live timeline of each message"): "It starts the
moment Petar presses send, with the server receiving the message as the first mark.
Lanes run side by side: the Decisions API router and each Synapse lookup, each a bar
from when it starts to when it ends. Then the final model call ... Every bar drawn
live as it happens, with its time in ms, its model, its tokens and its cost. The
bouncing dots replaced by a label for what is actually going on." And: "Each step in
its real order, with the real status. Running only while it actually runs" (B3).

So a turn (`runtime.Turn`) holds one `Trace`, in `CURRENT` for everything the turn
does, and the trace is told each step as it really starts and ends:

- **the router** (`runtime.Turn.routed`): a bar from the moment the Decisions API is
  asked to its answer, with the pick, how sure it was, its tokens and its cost;
- **the memory look-ups**: each bar of the message's recall timeline as it arrives
  (`recall` messages, `recalling.MessageMemory.timeline`), put on the turn's clock;
- **every request of the answer** (`llmlog.Entry`, purpose "turn"): sent, waiting for
  its first word, thinking, writing or writing a tool call, ended, with its tokens and
  cost once its answer is read;
- **every tool call** (`tool_start` and `tool_end` as the turn sends them);
- **the steps after the answer**: saving it, and speaking it.

Each change is sent to the chat's tabs as one `trace` message, at most every
`EVERY` seconds (PROTOCOL.md), with `now`, the one label that replaces the dots. When
the turn ends the whole of it is kept for good in the turn's record (`TurnRecord`,
`rouh/turnrecords.py`), with how the turn ended, when its first token, first written
word and first spoken word came, and every look-up of Synapse it made, so a chat read
back draws the same timeline and the turn can be weighed against others later.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
import threading
import time

from .config import model_name

log = logging.getLogger("rouh.turntrace")

#: The trace of the turn being answered here, for code the turn never hands it to.
CURRENT: contextvars.ContextVar["Trace | None"] = contextvars.ContextVar("rouh_turn_trace", default=None)

#: How often, at most, a trace is sent while it changes.
EVERY = 0.12
#: The most lanes a trace keeps: a turn of a hundred tools is still drawn, its oldest first.
MOST = 160

RUNNING, DONE, FAILED, STOPPED = "running", "done", "failed", "stopped"
#: Where a model's request is, from what its stream has said so far.
WAITING, THINKING, WRITING, CALLING = "waiting", "thinking", "writing", "calling"


def current() -> "Trace | None":
    return CURRENT.get()


def _short(value, most: int) -> str:
    """A tool's arguments or result, in a line of at most `most` characters."""
    if value is None:
        return ""
    if not isinstance(value, str):
        import json

        try:
            value = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            value = str(value)
    value = " ".join(value.split())
    return value if len(value) <= most else value[: most - 1] + "\u2026"


class Trace:
    """One turn's steps. Changed on the turn's event loop, or from any thread through
    `soon`; sent to the chat's tabs by `emit` (the turn's own)."""

    def __init__(self, chat: str, turn_id: str, emit, *, started_at: float | None = None,
                 asked: str = "", note: bool = False) -> None:
        self.chat = chat
        self.turn_id = turn_id
        self.emit = emit
        self.started_at = started_at or time.time()
        #: The person's own words, which a run started from a brief another model wrote
        #: carries with it (`tools._started`).
        self.asked = asked
        self.note = note
        #: The model this turn answers with, once known, and its tier.
        self.model = ""
        self.tier = ""
        self.lanes: list[dict] = []
        self._by: dict[str, dict] = {}
        self.memory: dict | None = None
        #: How the answer's model was decided, the "Model decision" line, once it is
        #: (`modelrouter.timeline`), sent with every trace so the line is drawn the moment
        #: the router decides.
        self.route: dict | None = None
        #: The exchange it answers again, for a retry, whose question is on the screen already.
        self.root: int | None = None
        self.state = RUNNING
        #: How the turn ended (`runtime.Turn._answer`): finished, stopped, failed, unfinished
        #: or replaced, and what went wrong.
        self.outcome = ""
        self.error = ""
        #: When the answer's first token came (any request's), its first word reached the
        #: screen, and its first word was spoken, in ms from the message reaching the server.
        self.first_token_ms: int | None = None
        self.first_word_ms: int | None = None
        self.spoken_ms: int | None = None
        #: When the answer's last word reached the screen.
        self.last_word_ms: int | None = None
        #: From when the turn was ready to ask the model (`ready`) to its first request: the
        #: time spent building the request, shown as a bar of its own.
        self._ready_ms: int | None = None
        #: When the turn was over, once it is: the timeline's length from then on.
        self.ended_ms: int | None = None
        #: Every look-up of Synapse a tool of the turn made (`noted_synapse`), with its trace.
        self.synapse: list[dict] = []
        #: Keeps the timeline with the turn again (`runtime.Turn`), for what arrives once it is over.
        self.keep = None
        self._n = 0
        self._lock = threading.Lock()
        self._sent_at = 0.0
        self._pending: asyncio.TimerHandle | None = None
        self._keeping: asyncio.TimerHandle | None = None
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

    # --- the clock ------------------------------------------------------------------------

    def ms(self, at: float | None = None) -> int:
        return max(0, int(round(((time.time() if at is None else at) - self.started_at) * 1000)))

    # --- lanes ----------------------------------------------------------------------------

    def start(self, kind: str, name: str, *, key: str = "", model: str = "", at: float | None = None,
              **more) -> str:
        """A step begins: a running bar from now (or `at`). Its id back, for `end`."""
        with self._lock:
            self._n += 1
            lane_id = key or f"{kind}-{self._n}"
            if lane_id in self._by:
                return lane_id
            lane = {"id": lane_id, "kind": kind, "name": str(name or kind)[:160], "start_ms": self.ms(at),
                    "end_ms": None, "state": RUNNING}
            if model:
                lane["model"], lane["model_name"] = model, model_name(model)
            lane.update({k: v for k, v in more.items() if v not in (None, "")})
            self.lanes.append(lane)
            self._by[lane_id] = lane
            if len(self.lanes) > MOST:
                gone = self.lanes.pop(0)
                self._by.pop(gone["id"], None)
        self.touch()
        return lane_id

    def update(self, lane_id: str, **fields) -> None:
        with self._lock:
            lane = self._by.get(lane_id)
            if lane is None:
                return
            changed = any(lane.get(k) != v for k, v in fields.items())
            lane.update({k: v for k, v in fields.items() if v is not None})
        if changed:
            self.touch()
            # A request's tokens and cost are read on the request log's own thread, and can
            # come after the turn kept its timeline: kept again, so a reload shows them too.
            self._keep_again()

    def _keep_again(self) -> None:
        """Something arrived after the turn ended: its record is written again, once for
        whatever arrives within half a second. On the turn's loop, from any thread."""
        if self.state == RUNNING or self.keep is None or self.loop is None or self.loop.is_closed():
            return
        try:
            on_loop = asyncio.get_running_loop() is self.loop
        except RuntimeError:
            on_loop = False
        if not on_loop:
            self.soon(self._keep_again)
            return
        if self._keeping is not None:
            return

        def run() -> None:
            self._keeping = None
            task = self.loop.create_task(self.keep())
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        self._keeping = self.loop.call_later(0.5, run)

    def end(self, lane_id: str, state: str = DONE, *, at: float | None = None, **fields) -> None:
        with self._lock:
            lane = self._by.get(lane_id)
            if lane is None:
                return
            if lane["end_ms"] is None:
                lane["end_ms"] = max(lane["start_ms"], self.ms(at))
                lane["state"] = state
            lane.pop("phase", None)
            lane.update({k: v for k, v in fields.items() if v is not None})
        self.touch()

    def soon(self, fn, *args, **kwargs) -> None:
        """Do this on the turn's loop, from any thread."""
        if self.loop is None or self.loop.is_closed():
            return
        try:
            self.loop.call_soon_threadsafe(lambda: fn(*args, **kwargs))
        except RuntimeError:
            pass

    # --- what the turn tells it -----------------------------------------------------------

    def saw(self, message: dict) -> None:
        """A message the turn is sending (`runtime.Turn.emit`): its tools, and the memory
        timeline of its message."""
        kind = message.get("type")
        if kind == "recall" and not message.get("note"):
            tl = message.get("timeline")
            if isinstance(tl, dict):
                self.memory = tl
                self.touch()
                # The recall's own trace in Synapse is written once the turn is over.
                self._keep_again()
        elif kind == "assistant_delta" and str(message.get("text") or "").strip():
            at = self.ms()
            if self.first_word_ms is None:
                self.first_word_ms = at
            self.last_word_ms = at
            # And the first visible word of the request that wrote it.
            with self._lock:
                lane = next((x for x in reversed(self.lanes) if x["kind"] == "model"), None)
            if lane is not None and lane.get("first_word_ms") is None:
                self.update(lane["id"], first_word_ms=at)
            self.touch()
        elif kind == "tool_start" and not message.get("orb_only"):
            key = "tool-" + str(message.get("id") or message.get("name") or "")
            self.start("tool", str(message.get("name") or "tool"), key=key,
                       what=str(message.get("what") or "")[:200], input=_short(message.get("input"), 600))
        elif kind == "tool_update" and not message.get("orb_only"):
            key = "tool-" + str(message.get("id") or message.get("name") or "")
            if message.get("input") is not None:
                self.update(key, input=_short(message.get("input"), 600))
        elif kind == "tool_end" and not message.get("orb_only"):
            key = "tool-" + str(message.get("id") or message.get("name") or "")
            # What it said back, in short, with whether it worked.
            self.end(key, DONE if message.get("ok", True) is not False else FAILED,
                     result=_short(message.get("summary"), 300) or None)

    def waited(self, name: str, since: float) -> None:
        """The turn waited for something from `since` (time.time()) until now: a bar of its own, so the
        time between the steps around it is never an unexplained gap. Always drawn, a few ms too, so
        the same turn always has the same rows."""
        lane_id = self.start("wait", name, at=since)
        self.end(lane_id)

    def ready(self) -> None:
        """Everything the first request waits for is in (`brain.memory_for_turn`): from now to that
        request is building it."""
        if self._ready_ms is None:
            self._ready_ms = self.ms()

    def request_started(self, purpose: str) -> str:
        """A request of the answer went out (`llmlog.Entry`): a bar for it, waiting for its first word."""
        if purpose != "turn":
            return ""
        n = sum(1 for lane in self.lanes if lane["kind"] == "model") + 1
        if n == 1 and self._ready_ms is not None:
            self.waited("Getting the request ready", self.started_at + self._ready_ms / 1000)
        return self.start("model", self.model and model_name(self.model) or "The model",
                          model=self.model, phase=WAITING, request=n)

    def request_first(self, lane_id: str) -> None:
        """A request's first word or thought arrived (`llmlog.Entry.took`)."""
        if not lane_id:
            return
        at = self.ms()
        if self.first_token_ms is None:
            self.first_token_ms = at
        self.update(lane_id, first_ms=at)

    def request_phase(self, lane_id: str, phase: str) -> None:
        if lane_id:
            self.update(lane_id, phase=phase)

    def request_ended(self, lane_id: str, outcome: str) -> None:
        if lane_id:
            self.end(lane_id, {"ended": DONE, "stopped": STOPPED}.get(outcome, FAILED))

    def request_counted(self, lane_id: str, *, tokens_in: int, tokens_out: int, cache_read: int,
                        cost, cache_write: int = 0, row: int | None = None) -> None:
        """What a request read, wrote and cost, once its answer was read (from the writer's thread):
        `tokens_in` is everything it read, `cache_read` of it from the cache and `cache_write` into
        it, and `row` is its row in `llm_requests`, which the turn's record links to."""
        if lane_id:
            self.soon(self.update, lane_id, tokens_in=int(tokens_in or 0) + int(cache_read or 0),
                      cache_read=int(cache_read or 0), cache_write=int(cache_write or 0),
                      tokens_out=int(tokens_out or 0), cost=None if cost is None else float(cost),
                      request_id=row)

    def tool_sized(self, call_id: str, size: int) -> None:
        """How much a tool call gave back, in characters, before its line ends."""
        self.update("tool-" + str(call_id or ""), size=int(size))

    def noted_synapse(self, entry: dict) -> None:
        """A tool of the turn looked in Synapse (`synapse.chat.find`, `query`): kept for the record,
        and its items and cost put on the tool's own bar. From any thread."""
        entry = dict(entry, at_ms=self.ms())
        with self._lock:
            self.synapse.append(entry)

        def on_bar() -> None:
            with self._lock:
                bar = next((lane for lane in reversed(self.lanes) if lane["kind"] == "tool"
                            and lane["name"] == entry.get("tool") and lane["state"] == RUNNING), None)
            if bar is not None:
                self.update(bar["id"], count=entry.get("count"), cost=entry.get("cost"),
                            synapse_trace=entry.get("trace") or None)
        on_bar()

    def spoken(self) -> None:
        """The answer's first words went to the voice."""
        if self.spoken_ms is None:
            self.spoken_ms = self.ms()
            self.touch()

    def decided(self, model: str, tier: str) -> None:
        """The model the answer is asked of, once known."""
        self.model, self.tier = model or "", tier or ""
        self.touch()

    def finish(self, outcome: str = "", error: str = "") -> None:
        """The turn is over: anything still running is stopped where it is."""
        self.outcome = outcome or self.outcome or "finished"
        self.error = (error or self.error or "")[:500]
        self.ended_ms = self.ms()
        with self._lock:
            for lane in self.lanes:
                if lane["end_ms"] is None:
                    lane["end_ms"] = self.ms()
                    lane["state"] = STOPPED
                    lane.pop("phase", None)
            self.state = DONE
        self.touch(now=True)

    # --- what is sent ---------------------------------------------------------------------

    def _memory_lanes(self) -> list[dict]:
        tl = self.memory
        if not tl or not tl.get("bars"):
            return []
        shift = int(round((float(tl.get("began") or self.started_at) - self.started_at) * 1000))
        out = []
        for b in tl["bars"]:
            outcome = str(b.get("outcome") or "")
            end = b.get("end_ms")
            state = (RUNNING if end is None and outcome == "running" else
                     FAILED if outcome in ("failed", "timeout") else DONE)
            what = str(b.get("what") or b.get("tool") or "")
            name = (f"Memory: reading the message with {what}" if b.get("tool") == "recall_pick"
                    else "Memory: " + what[:1].lower() + what[1:] if what else "Memory")
            out.append({"id": "memory-" + str(b.get("id")), "kind": "memory", "name": name[:160],
                        "start_ms": max(0, shift + int(b.get("start_ms") or 0)),
                        "end_ms": None if end is None else max(0, shift + int(end)),
                        "state": state, "outcome": outcome, "count": b.get("count"),
                        **({"ids": list(b["ids"])} if b.get("ids") else {}),
                        **({"error": b["error"]} if b.get("error") else {}),
                        **({"cost": b["cost"]} if b.get("cost") is not None else {})})
        return out

    def now_said(self, lanes: list[dict]) -> str:
        """What is happening at this moment, in a few words: the label in place of the dots."""
        running = [lane for lane in lanes if lane["state"] == RUNNING]
        tool = [lane for lane in running if lane["kind"] == "tool"]
        if tool:
            lane = tool[-1]
            return lane.get("what") or ("Running " + lane["name"])
        model = [lane for lane in running if lane["kind"] == "model"]
        if model:
            lane = model[-1]
            who = lane.get("model_name") or "The model"
            return {WAITING: f"Waiting for {who}'s first word", THINKING: f"{who} is thinking",
                    WRITING: f"{who} is writing", CALLING: f"{who} is choosing a tool"}.get(
                lane.get("phase") or WAITING, f"{who} is answering")
        step = [lane for lane in running if lane["kind"] == "step"]
        if step:
            return step[-1]["name"]
        router = any(lane["kind"] == "router" for lane in running)
        memory = any(lane["kind"] == "memory" for lane in running)
        if router and memory:
            return "Choosing the model and looking in memory"
        if router:
            return "Choosing the model"
        if memory:
            return "Looking in memory"
        if self.state != RUNNING:
            return ""
        return "Getting the answer ready" if self.model else "Starting"

    def snapshot(self) -> dict:
        with self._lock:
            lanes = [dict(lane) for lane in self.lanes]
        lanes = lanes + self._memory_lanes()
        lanes.sort(key=lambda lane: (lane["start_ms"], lane["kind"] != "router"))
        costs = [lane["cost"] for lane in lanes if lane.get("cost") is not None]
        elapsed = self.ended_ms if self.ended_ms is not None and self.state != RUNNING else self.ms()
        return {"v": 1, "turn_at": self.started_at, "elapsed_ms": elapsed, "state": self.state,
                "model": self.model, "model_name": model_name(self.model) if self.model else "",
                "tier": self.tier, "lanes": lanes, "now": self.now_said(lanes), "note": self.note,
                "root": self.root, "outcome": self.outcome, "error": self.error,
                "first_token_ms": self.first_token_ms, "first_word_ms": self.first_word_ms,
                "spoken_ms": self.spoken_ms, "last_word_ms": self.last_word_ms,
                "cost": round(sum(costs), 6) if costs else None,
                **({"route": self.route} if self.route else {})}

    def kept(self) -> dict:
        """What the turn's record keeps (`rouh/turnrecords.py`): the timeline, the message's recall
        timeline whole (`memory`) and its tools' look-ups of Synapse (`synapse`)."""
        said = self.snapshot()
        with self._lock:
            said["synapse"] = [dict(e) for e in self.synapse]
        if self.memory:
            said["memory"] = self.memory
        return said

    def touch(self, now: bool = False) -> None:
        """Something changed: send the trace, at most every `EVERY` seconds."""
        if self.loop is None or self.loop.is_closed():
            return
        try:
            on_loop = asyncio.get_running_loop() is self.loop
        except RuntimeError:
            on_loop = False
        if not on_loop:
            self.soon(self.touch, now)
            return
        if self._pending is not None and not now:
            return
        wait = 0.0 if now else max(0.0, EVERY - (time.monotonic() - self._sent_at))
        if self._pending is not None:
            self._pending.cancel()
        self._pending = self.loop.call_later(wait, self._send)

    def _send(self) -> None:
        self._pending = None
        self._sent_at = time.monotonic()
        try:
            said = self.snapshot()
        except Exception:  # noqa: BLE001 - a picture is never worth a turn
            log.exception("a turn's timeline could not be made")
            return
        task = self.loop.create_task(self._emit({"type": "trace", "trace": said}))
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    async def _emit(self, message: dict) -> None:
        try:
            await self.emit(message)
        except Exception:  # noqa: BLE001
            log.debug("a turn's timeline could not be sent", exc_info=True)
