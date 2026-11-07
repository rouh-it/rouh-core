"""The flag that stops a turn part way through.

Rouh is an agentic loop, not one call to a model. By the time the person
wants it to stop, a turn can be several model calls and several tool calls
deep: the words being streamed now are the fourth response of the turn, two
searches and a workspace read have already happened, and a fifth request is
about to go out. Escape has to end all of that at the first safe point.

So the stop is a flag rather than a cancellation, and it is held here rather
than on the socket the person happened to press it from.

**A flag, not `task.cancel()`.** Two reasons, both learned the hard way in
neighbouring code. The first is that the turn has to end tidily: the transcript
has to say it was stopped, or the next turn replays a conversation that ends in
a question nobody answered, and the API rejects it (see
`memory.repair_history`). The second is that cancelling reaches everything the
turn is awaiting, and one of those things is the tool call that handed a job to
a background worker. Stopping Rouh is not stopping the work it has already
handed over, and nothing in here touches a worker, an `assistant_job`, a
`delegate_task` or a run of the one program.

**Keyed by session and turn.** Every turn gets a number (`Session.turn_id`),
and the flag is keyed by the conversation it belongs to and that number. A stop
that arrives a moment after a turn ended must not land on the next one, which
is what keying by the session alone would do.

The registry is small and deliberately dull: a flag is created when a turn
starts, set when somebody stops it, and dropped when the turn is over.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.stopping")

#: What is written into the conversation in the person's place when they stop a
#: turn. It is stored as a message so that the next turn reads it: without it
#: the model sees its own half-finished answer and no reason for it, and carries
#: on as though nothing happened.
#:
#: The second sentence is there for the model as much as for the person. Being
#: stopped is not being told the work was wrong, and a turn that answers "shall
#: I cancel the job as well" to a stop has misread what happened.
STOP_NOTE = (
    "[Stopped by the person. Your turn was abandoned part way through and "
    "nothing more of it was said or done. Background jobs, delegated tasks and "
    "runs that had already been started were not stopped and are still going. "
    "Carry on from whatever they say next.]"
)


class Stops:
    """Every turn that can still be stopped, by conversation and turn number."""

    def __init__(self) -> None:
        self._turns: dict[str, dict[int, asyncio.Event]] = {}

    def begin(self, session_id: str, turn_id: int) -> asyncio.Event:
        """Open a turn and hand back the flag the loop reads."""
        flag = asyncio.Event()
        self._turns.setdefault(session_id, {})[turn_id] = flag
        return flag

    def end(self, session_id: str, turn_id: int) -> None:
        """The turn is over, however it ended. Forget its flag."""
        turns = self._turns.get(session_id)
        if not turns:
            return
        turns.pop(turn_id, None)
        if not turns:
            self._turns.pop(session_id, None)

    def running(self, session_id: str) -> list[int]:
        """Which turns of this conversation are still stoppable, oldest first."""
        return sorted(self._turns.get(session_id, {}))

    def flag(self, session_id: str, turn_id: int) -> asyncio.Event | None:
        return self._turns.get(session_id, {}).get(turn_id)

    def is_stopped(self, session_id: str, turn_id: int) -> bool:
        flag = self.flag(session_id, turn_id)
        return bool(flag and flag.is_set())

    def stop(self, session_id: str, turn_id: int | None = None) -> list[int]:
        """Stop a turn of this conversation, or every turn still open in it.

        Returns the numbers of the turns actually stopped, which is empty when
        there was nothing running. Setting a flag is all this does: it takes no
        locks, waits for nothing and never blocks, which is what lets the
        endpoint answer while the model is still streaming.
        """
        turns = self._turns.get(session_id, {})
        wanted = [turn_id] if turn_id is not None else sorted(turns)
        stopped = []
        for number in wanted:
            flag = turns.get(number)
            if flag is None or flag.is_set():
                continue
            flag.set()
            stopped.append(number)
        if stopped:
            log.info("turn %s of %s stopped by the person", stopped, session_id)
        return stopped

    def forget_everything(self) -> None:
        """Only for tests, which share one process across many conversations."""
        self._turns.clear()


#: One registry for the server. A turn is answered in one process, so there is
#: nothing here to share between them.
stops = Stops()
