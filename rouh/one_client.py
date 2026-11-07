"""Rouh's voice, attached to the one program (task 30, step 10).

The one program holds runs of Claude Code that a terminal can take over, keeps
one list of everything that happens, and answers a terminal, a browser, the
phone and this: Rouh's voice. It lives beside Rouh, at
``/run/one/one.sock``, and Rouh reaches into it; it never reaches back.

What the voice may do there is decided by the program, not here: it may start
an ordinary run, stop one, answer a question yes or no, and take or hand back
a run that a terminal is watching. The program refuses anything else, whatever
a sentence might talk a model into.

Two ways in:

* :meth:`OneClient.ask` - one message, one answer, for the voice's tools.
* :meth:`OneClient.watch` - a connection kept open for the orb and for
  questions: the program's work tree, so the orb draws its runs next to
  Rouh's own jobs, and every question a run asks, so Rouh can put it to
  the person out loud.

If the program is not there, every call says so in one sentence and Rouh
carries on. Nothing in Rouh depends on the program running.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import Any, Awaitable, Callable

log = logging.getLogger("rouh.one")

SOCKET = "/run/one/one.sock"
#: The voice's own device token for the program, written when Rouh was paired
#: with it (``one pair voice --save``). Readable by root only.
TOKEN_FILE = "/var/www/rouh/one-voice.json"

NOT_RUNNING = "The one program is not running right now."

#: What each subscription of ``OneClient.watch`` is, by its message id.
WATCHED = {1: "its work tree", 2: "its questions", 3: "its runs", 4: "its list",
           5: "whether it took the OpenAI API key"}


class OneUnavailable(RuntimeError):
    """The program is not there, or Rouh has not been paired with it."""


class OneRefused(RuntimeError):
    """The program said no, in its own words."""


class OneClient:
    def __init__(self, socket_path: str | None = None, token_file: str | None = None,
                 *, timeout: float = 10.0) -> None:
        self.socket_path = socket_path or os.environ.get("ROUH_ONE_SOCKET", SOCKET)
        self.token_file = token_file or os.environ.get("ROUH_ONE_TOKEN", TOKEN_FILE)
        self.timeout = timeout
        #: Rouh's own device id in the program, from its last hello: how the
        #: runs Rouh started are told apart from everyone else's.
        self.device_id: str | None = None
        #: The number of the program's newest entry at the last hello.
        self.last_n = 0
        #: The whole of the program's last hello. It carries what the program
        #: says about itself - its version and the commit it was built from -
        #: which is what Rouh's top bar shows (`one_version.py`).
        self.hello: dict[str, Any] = {}

    def configured(self) -> bool:
        """Rouh has been paired with the program on this machine."""
        return self._token() is not None

    def _token(self) -> str | None:
        try:
            with open(self.token_file, encoding="utf-8") as fh:
                return json.load(fh).get("token") or None
        except (OSError, ValueError, AttributeError):
            return None

    async def _open(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        token = self._token()
        if token is None:
            raise OneUnavailable("Rouh has not been paired with the one program.")
        if not os.path.exists(self.socket_path):
            raise OneUnavailable(NOT_RUNNING)
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self.socket_path, limit=8 << 20), 3.0)
        except (OSError, asyncio.TimeoutError):
            raise OneUnavailable(NOT_RUNNING)
        await _send(writer, {"t": "hello", "id": 0, "token": token})
        hello = await _reply(reader, 0, self.timeout)
        self.hello = hello
        self.device_id = hello.get("device") or self.device_id
        self.last_n = int(hello.get("n") or 0)
        return reader, writer

    async def identify(self) -> dict[str, Any]:
        """The program's hello, and nothing else: who it thinks this device is,
        which version it is and which commit it was built from.

        Opening a connection is the whole question, so this sends no message of
        its own. It is what Rouh's top bar asks every time a page connects.
        """
        reader, writer = await self._open()
        with contextlib.suppress(Exception):
            writer.close()
        return dict(self.hello)

    async def ask(self, t: str, **fields: Any) -> dict[str, Any]:
        """Send one message and return the program's answer. Raises on a refusal."""
        reader, writer = await self._open()
        try:
            await _send(writer, {"t": t, "id": 1, **fields})
            return await _reply(reader, 1, self.timeout)
        finally:
            with contextlib.suppress(Exception):
                writer.close()

    async def watch(self, *, on_tree: Callable[[dict], Any] | None = None,
                    on_questions: Callable[[list], Awaitable[None] | None] | None = None,
                    on_runs: Callable[[list, bool], Awaitable[None] | None] | None = None,
                    on_entry: Callable[[dict], Awaitable[None] | None] | None = None,
                    on_hello: Callable[[dict], Awaitable[None] | None] | None = None,
                    codex_key: str = "", retry: float = 5.0) -> None:
        """Keep a connection open for the tree, the questions, the runs and the list.

        ``on_runs`` hears every run on connecting (``True``), then each run
        that changes (``False``). ``on_entry`` hears every entry the list takes
        from the moment of connecting; nothing from before is replayed.
        ``on_hello`` hears the program's hello every time this connects, which
        is how a program that restarted into new code is noticed without
        anybody reloading a page.

        ``codex_key`` is the OpenAI API key in Rouh's own environment, handed
        to the program each time this connects, because the program starts
        the runs of Codex that may be billed to it and its own environment
        does not have it (one/billing.py). It goes over this socket and
        nowhere else, and nothing here writes it down.
        Never returns, never raises.
        """
        while True:
            try:
                reader, writer = await self._open()
                try:
                    if on_hello is not None:
                        result = on_hello(dict(self.hello))
                        if asyncio.iscoroutine(result):
                            await result
                    if on_tree is not None:
                        await _send(writer, {"t": "tree", "id": 1, "watch": True})
                    if on_questions is not None:
                        await _send(writer, {"t": "questions", "id": 2, "watch": True})
                    if on_runs is not None:
                        await _send(writer, {"t": "runs", "id": 3, "watch": True, "limit": 100})
                    if on_entry is not None:
                        await _send(writer, {"t": "tail", "id": 4, "since": self.last_n})
                    if codex_key:
                        await _send(writer, {"t": "codex_key", "id": 5, "key": codex_key})
                    while True:
                        line = await reader.readline()
                        if not line:
                            break
                        message = json.loads(line)
                        kind, re_ = message.get("t"), message.get("re")
                        result = None
                        if on_tree is not None and (kind == "tree" or (kind == "ok" and re_ == 1)):
                            result = on_tree(message.get("tree") or {})
                        elif on_questions is not None and (
                                kind == "questions" or (kind == "ok" and re_ == 2)):
                            result = on_questions(message.get("questions") or [])
                        elif on_runs is not None and kind == "ok" and re_ == 3:
                            result = on_runs(message.get("runs") or [], True)
                        elif on_runs is not None and kind == "run" and message.get("run"):
                            result = on_runs([message["run"]], False)
                        elif on_entry is not None and kind == "entry" and message.get("entry"):
                            result = on_entry(message["entry"])
                        elif kind == "err" and re_ in WATCHED:
                            # Said once per connection, so a refusal is never silent.
                            log.warning("the one program would not send %s to the voice: %s",
                                        WATCHED[re_], message.get("why"))
                        if asyncio.iscoroutine(result):
                            await result
                finally:
                    with contextlib.suppress(Exception):
                        writer.close()
            except asyncio.CancelledError:
                raise
            except OneUnavailable:
                pass
            except Exception:
                log.exception("the connection to the one program failed; trying again")
            if on_tree is not None:
                on_tree({})  # the program's runs leave the orb while it is away
            await asyncio.sleep(retry)


async def _send(writer: asyncio.StreamWriter, message: dict) -> None:
    writer.write((json.dumps(message) + "\n").encode("utf-8"))
    await writer.drain()


async def _reply(reader: asyncio.StreamReader, rid: int, timeout: float) -> dict:
    async def read() -> dict:
        while True:
            line = await reader.readline()
            if not line:
                raise OneUnavailable("The one program closed the connection.")
            message = json.loads(line)
            if message.get("re") == rid:
                if message.get("t") == "err":
                    raise OneRefused(str(message.get("why") or "it said no"))
                return message

    try:
        return await asyncio.wait_for(read(), timeout)
    except asyncio.TimeoutError:
        raise OneUnavailable("The one program did not answer in time.")


# ---------------------------------------------------------------------------
# Words for the voice
# ---------------------------------------------------------------------------

STATE_WORDS = {"queued": "queued", "starting": "starting", "working": "working",
               "asking": "waiting for you", "saving": "saving its work",
               "idle": "finished its turn", "done": "done", "unfinished": "unfinished",
               "failed": "failed", "lost": "lost", "refused": "refused",
               # Stopped by the program at its time limit (one/scheduler.py).
               "reaped": "cleaned up, stopped at the time limit"}


def state_words(run: dict) -> str:
    """A run's state in one phrase, with the reason a queued run is waiting.

    "waiting to start" said nothing about what the wait was for and read as
    stuck, so a queued run carries the program's own sentence: "queued - 6 runs
    are already working; it starts when one finishes". A run queued for the
    moment before the program's scheduler has looked at it has no reason on it
    yet, and "queued" alone is the truth about it.
    """
    state = str(run.get("state") or "")
    word = STATE_WORDS.get(state, state)
    # An unfinished run always says what is unfinished about it: read out on
    # its own, "unfinished" only moves the question along.
    if state in ("unfinished", "reaped") and run.get("left"):
        return f"{word} - {run['left']}"
    why = run.get("queued_because")
    return f"{word} - {why}" if state == "queued" and why else word


#: The one field of an entry's body worth reading, tried in this order. The
#: program's kinds are in `one/KINDS.md`; this deliberately knows none of them
#: by name, because Rouh reads the program over a socket and holds none of
#: its code, and a kind added there should still read here.
ENTRY_SAYS = ("what", "text", "message", "why", "reason", "command", "title", "how", "name")


def describe_entries(entries: list[dict], limit: int = 120) -> str:
    """A run's own history as plain lines, oldest last.

    This is what `read_task_log` answers with for a run of the program. Until
    19 September 2026 it answered with the run's visible screen, which is what
    `look_at_task` already says, so a run whose first hour had scrolled off the
    top could not be asked what it had done. The entries are what the program
    keeps, and it sends them with every `run` message; they were thrown away.
    """
    lines: list[str] = []
    for entry in entries[-limit:]:
        body = entry.get("body") or {}
        said = ""
        for field in ENTRY_SAYS:
            value = body.get(field)
            if isinstance(value, str) and value.strip():
                said = " ".join(value.split())[:200]
                break
        when = str(entry.get("at") or "")[11:19]
        lines.append(f"{when} {entry.get('kind') or 'something'}" + (f": {said}" if said else ""))
    return "\n".join(lines)


#: The states of a run that is over: nothing more will happen in it.
ENDED_STATES = ("done", "unfinished", "failed", "lost", "refused", "reaped")


def _runs(n: int) -> str:
    return f"{n} run{'s' if n != 1 else ''}"


def describe_runs(runs: list[dict], questions: list[dict], *, ended_shown: int = 3) -> str:
    """The program's runs as a few plain lines a model can read out.

    Open is two different things and the answer says which (D49). A run that
    is **working** is doing something now. A run that has **finished its
    turn** is doing nothing: it is at its prompt, still open, and carries on
    the moment something is said to it, until a person closes it. On 29
    September 2026 this said "32 runs open" over a list where twenty of them
    said "finished its turn", which read as thirty-two things going on. Those
    twenty are listed too, because each can still be carried on, and after the
    working ones, so what is going on is read first.

    An archived run is neither: archiving is the person putting it away, and
    the program stops it on the way (`one/runs.py`, `archive`).
    """
    open_runs = [r for r in runs
                 if r.get("state") not in ENDED_STATES and not r.get("archived")]
    ended = [r for r in runs if r not in open_runs][:ended_shown]
    asked = {q.get("run"): q for q in questions}
    busy = [r for r in open_runs if r.get("state") != "idle"]
    resting = [r for r in open_runs if r.get("state") == "idle"]
    open_runs = busy + resting
    lines: list[str] = []
    if not open_runs:
        lines.append("Nothing is running in the one program.")
    else:
        head = f"{_runs(len(open_runs))} open in the one program"
        if not resting:
            head += ", working or waiting"
        elif not busy:
            head += (", none of them working: "
                     + ("it has finished its turn and waits at its prompt"
                        if len(resting) == 1 else
                        "each has finished its turn and waits at its prompt")
                     + " to be carried on or closed")
        else:
            head += (f": {len(busy)} working or waiting, and {len(resting)} "
                     + ("that has finished its turn and waits at its prompt"
                        if len(resting) == 1 else
                        "that have finished their turn and wait at their prompt")
                     + " to be carried on or closed")
        lines.append(head + ":")
    for r in open_runs:
        line = f"- run {r['id']}, \"{r.get('title')}\": {state_words(r)}"
        if r.get("state") == "working" and r.get("doing"):
            line += f", {r['doing']}"
        if r.get("driver"):
            line += ", a person is driving it"
        q = asked.get(r["id"])
        if q:
            line += (f". It asks (question {q['id']}): {q.get('text')}"
                     + (f" The call: {q['detail']}" if q.get("detail") else ""))
        elif r.get("waiting_on_terminal"):
            line += f". It is waiting in its own terminal: {r['waiting_on_terminal']}"
        lines.append(line)
    if ended:
        lines.append("Ended recently:")
        for r in ended:
            said = f": {r['last_message'][:200]}" if r.get("last_message") else ""
            word = ("archived" if r.get("archived") and r.get("state") not in ENDED_STATES
                    else state_words(r))
            lines.append(f"- run {r['id']}, \"{r.get('title')}\", {word}{said}")
    return "\n".join(lines)
