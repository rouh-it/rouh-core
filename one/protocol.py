"""One set of messages, for every place that talks to the program.

A terminal on the server, the laptop through ssh, a browser tab, Rouh's
voice: each is a :class:`Client`, and each sends the same JSON messages. Over
the socket they are one per line; over the web they are websocket frames.
That is step 07's Language Server Protocol lesson: a new place to talk from
costs a client, not a change to the program.

Every message is ``{"t": <type>, "id": <any>, ...}``. The answer is
``{"t": "ok", "re": <id>, ...}`` or ``{"t": "err", "re": <id>, "why": ...}``.
What the program pushes without being asked:

``entry``      one entry of the list, for ``tail``
``run``        one run, changed, for ``runs`` with ``watch``
``questions``  the open questions, for ``questions`` with ``watch``
``tree``       the work tree, for ``tree`` with ``watch``
``screen``     a run's whole screen, drawn, when you attach
``tty``        what a run's terminal printed since, while attached
``driving`` / ``watching``  you now hold a run's keyboard, or no longer do
``transcript`` what changed in a run's transcript, for ``transcript`` with
               ``watch``: the items added or changed, by id (one/transcripts.py)

Every run sent out carries ``terminal``: whether its terminal session is open
this instant, asked of the system each time rather than worked out from the
run's state, because "it finished its turn" and "its terminal has gone" both
read as done.

``rules.check`` runs on every message before anything else, with the place
the device was paired as - never the place a message claims to come from.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import logging
import os
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from . import billing, codex_signin, rules, version
from .config import this_machine
from .devices import hash_token, new_device_id, new_token
from .documents import DocumentsError
from .runs import RunError

if TYPE_CHECKING:  # pragma: no cover
    from .program import Program

log = logging.getLogger("one.protocol")

#: Messages queued for a connection that is not reading, before it is dropped.
QUEUE_LIMIT = 20_000

#: Messages whose answer can take a while, answered in their own time so that
#: the connection's next message is not held up behind them. A browser's
#: messages arrive one after another, and the first read of a long transcript
#: would otherwise hold up the keys typed into a run's terminal on the same page.
IN_ITS_OWN_TIME = frozenset({"transcript", "calls"})

CONSOLE = {"id": "console", "name": "the server's own terminal", "surface": "terminal"}


def is_here(address: str) -> bool:
    """Whether an address nginx forwarded is this machine itself.

    A page open on the server, through a tunnel or a browser on it, is told
    the plain command; a page anywhere else is told how to ssh in.
    """
    address = (address or "").split(",")[0].strip()
    if not address:
        return False
    with contextlib.suppress(ValueError):
        return ipaddress.ip_address(address).is_loopback or address == this_machine()
    return False


#: Fields of a run that are not sent in a list of runs, to keep it small.
_LIST_SKIP = ("brief",)


def public_run(run: dict[str, Any], *, full: bool = False,
               terminal: bool | None = None) -> dict[str, Any]:
    out = dict(run)
    # Whether the run's terminal session is open this instant, asked of the
    # system rather than guessed from the run's state: "finished its turn" and
    # "its terminal has gone" are not the same thing, and both read as done.
    if terminal is not None:
        out["terminal"] = bool(terminal)
    if not full:
        for name in _LIST_SKIP:
            out.pop(name, None)
        out["files"] = list(out.get("files") or [])[:20]
    return out


def public_device(dev: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in dev.items() if k != "token_hash"}


class Client:
    def __init__(self, program: "Program", send: Callable[[dict], Awaitable[None]], *,
                 local: bool, device: dict[str, Any] | None = None, at: str = "") -> None:
        self.p = program
        self._send = send
        self.local = local
        #: The address this connection came from, as nginx forwarded it. Empty
        #: for the socket, which is this machine by definition.
        self.at = at
        self.device: dict[str, Any] | None = device
        self.surface: str | None = device["surface"] if device else None
        self.subs: set[str] = set()
        self.tail_run: str | None = None
        #: run id -> when this connection attached
        self.attached: dict[str, float] = {}
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
        self._sender = asyncio.create_task(self._drain())
        #: Answers still being worked out (IN_ITS_OWN_TIME).
        self._slow: set[asyncio.Task] = set()
        self.closed = False

    @property
    def device_id(self) -> str:
        return (self.device or {}).get("id") or "unknown"

    # -- sending ------------------------------------------------------------------

    def push(self, message: dict[str, Any]) -> None:
        if self.closed:
            return
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            log.warning("a %s connection fell too far behind and was closed", self.surface)
            asyncio.create_task(self.close())

    async def _drain(self) -> None:
        try:
            while True:
                message = await self._queue.get()
                await self._send(message)
        except asyncio.CancelledError:
            raise
        except Exception:
            asyncio.create_task(self.close())

    def hear(self, entry: dict[str, Any]) -> None:
        """Every entry the list takes, as it takes it."""
        if self.closed or self.device is None:
            return
        run_id = entry.get("run")
        if "tail" in self.subs and (self.tail_run is None or run_id == self.tail_run):
            self.push({"t": "entry", "entry": entry})
        if "runs" in self.subs and run_id and run_id in self.p.views.runs:
            self.push({"t": "run", "run": self._run(self.p.views.runs[run_id])})
        if "questions" in self.subs and entry["kind"].startswith("question."):
            self.push({"t": "questions", "questions": self.p.views.open_questions()})
        if entry["kind"] == "device.revoked" and entry["body"].get("device") == self.device_id:
            self.push({"t": "err", "why": "this device was revoked"})
            asyncio.create_task(self.close())

    # -- receiving ----------------------------------------------------------------

    async def handle(self, message: dict[str, Any]) -> None:
        kind = str(message.get("t") or "")
        if kind in IN_ITS_OWN_TIME:
            task = asyncio.create_task(self._answer(kind, message))
            self._slow.add(task)
            task.add_done_callback(self._slow.discard)
            return
        await self._answer(kind, message)

    async def _answer(self, kind: str, message: dict[str, Any]) -> None:
        rid = message.get("id")
        try:
            if kind == "ping":
                self.push({"t": "pong", "re": rid})
                return
            if kind == "hello":
                self.push({"t": "ok", "re": rid, **self._hello(message)})
                return
            if self.device is None:
                raise rules.Refused("say hello first")
            rules.check(self.surface or "", kind)
            handler = getattr(self, f"_do_{kind}", None)
            if handler is None:
                raise rules.Refused(f"there is no message called {kind!r}")
            result = await handler(message)
            self.push({"t": "ok", "re": rid, **(result or {})})
        except (rules.Refused, RunError, ValueError, KeyError) as exc:
            why = str(exc).strip("'\"") if not isinstance(exc, KeyError) else f"{exc} is missing"
            self.push({"t": "err", "re": rid, "why": why})
        except Exception:
            log.exception("a %s message failed", kind)
            self.push({"t": "err", "re": rid, "why": "something went wrong inside the program"})

    def _hello(self, message: dict[str, Any]) -> dict[str, Any]:
        token = message.get("token")
        if token:
            dev = self.p.views.device_for_token_hash(hash_token(str(token)))
            if dev is None:
                raise rules.Refused("that device is not paired, or it was revoked")
        elif self.device is not None:
            dev = self.device
        elif self.local:
            dev = CONSOLE
        else:
            raise rules.Refused("pair this device first")
        self.device = dev
        self.surface = dev["surface"]
        return {"device": dev["id"], "name": dev.get("name"), "surface": self.surface,
                "allowed": sorted(rules.ALLOWED.get(self.surface, ())),
                # Which version is serving this connection, and which build of
                # it. Rouh asks for no other reason than to put it on its top
                # bar, where a program left behind by a deploy is visible before
                # somebody presses the button it cannot answer.
                **version.describe(),
                # Whether a run of Codex can be billed to the OpenAI API key
                # here, so a page offers it only when it can be done.
                "codex_api": self.p.api_key.available(),
                "n": self.p.list.last_n, "attach": self.attach_command()}

    def attach_command(self) -> dict[str, Any]:
        """How to take a run over in a real terminal, from where this
        connection is (D52).

        ``one take <run>`` is the command: it shows the run's terminal and
        types into it. It works in a shell on the server and on the person's
        laptop, where the ``one`` command reaches the server through ssh. On a
        machine with no ``one`` command of its own, ssh to this machine and
        run it here; the name the page was served under is no use for that,
        because that is usually a proxy's address (Cloudflare's), not this machine's.
        """
        return {"take": "one take", "watch": "one attach",
                "ssh": "ssh -t " + (self.p.settings.ssh_target or f"root@{this_machine()}"),
                "here": bool(self.local or is_here(self.at))}

    def _run(self, run: dict[str, Any], *, full: bool = False) -> dict[str, Any]:
        """One run as anyone outside sees it, with its terminal's state now.

        A run waiting on a question carries the question's words as well as
        its id, so Rouh's list can say what it is waiting on rather than a
        number nobody can read.
        """
        out = public_run(run, full=full, terminal=self.p.terminals.alive(run["id"]))
        asked = self.p.views.questions.get(run.get("question") or "")
        if asked and asked.get("open"):
            out["question_text"] = asked.get("text")
        return out

    def _run_id(self, message: dict[str, Any]) -> str:
        run_id = str(message.get("run") or "")
        if run_id not in self.p.views.runs:
            # A run can be named by the start of its id, as a person types it.
            found = [r for r in self.p.views.runs if run_id and r.startswith(run_id)]
            if len(found) == 1:
                return found[0]
            raise rules.Refused(f"there is no run {run_id!r}")
        return run_id

    # -- looking ---------------------------------------------------------------------

    async def _do_runs(self, m):
        if m.get("watch"):
            self.subs.add("runs")
        runs = self.p.views.run_list(limit=int(m.get("limit") or 100),
                                     open_only=bool(m.get("open")))
        return {"runs": [self._run(r) for r in runs]}

    async def _do_run(self, m):
        run_id = self._run_id(m)
        entries = list(self.p.list.read(run=run_id))[-int(m.get("entries") or 300):]
        terminal = self.p.terminals.get(run_id)
        # A screen only once the terminal is connected: `one claude` attaches
        # as soon as it sees one, and on 14 September it saw an empty screen
        # a moment before the connection, and the attach was refused.
        live = terminal is not None and terminal.connected
        return {"run": self._run(self.p.views.runs[run_id], full=True), "entries": entries,
                "screen": terminal.screen_text() if live else None}

    async def _do_transcript(self, m):
        """A run's transcript as a conversation, for the Read tab.

        With ``watch`` every change after it is pushed as it happens, until the
        same message comes with ``watch`` false or the connection closes. With
        ``item`` it is that one item whole, which items are not when sent
        (``cut`` names what was cut from one).
        """
        run_id = self._run_id(m)
        if m.get("item"):
            return self.p.transcripts.whole(run_id, str(m["item"]))
        if m.get("watch") is False:
            self.p.transcripts.leave(self, run_id)
            return {}
        return await self.p.transcripts.read(self, run_id, watch=bool(m.get("watch")))

    async def _do_calls(self, m):
        """Every tool call a run and its sub-agents made, whole (`Transcripts.calls`)."""
        return await self.p.transcripts.calls(self._run_id(m))

    async def _do_tree(self, m):
        if m.get("watch"):
            self.subs.add("tree")
        return {"tree": self.p.tree(), "now": time.time()}

    async def _do_questions(self, m):
        if m.get("watch"):
            self.subs.add("questions")
        return {"questions": self.p.views.open_questions()}

    async def _do_processes(self, message: dict[str, Any]) -> dict[str, Any]:
        """What this service is holding, process by process.

        Read only, and read fresh: it walks /proc, so it is asked for rather
        than pushed, and it is never part of the tree a screen subscribes to.
        A machine with no cgroups answers with what it can and says the rest is
        empty, which is what a laptop does.
        """
        limit = int(message.get("limit") or 40)
        return await asyncio.to_thread(self.p.scheduler.reaper.picture,
                                       limit=max(1, min(limit, 200)))

    async def _do_tail(self, m):
        self.tail_run = str(m["run"]) if m.get("run") else None
        since = int(m.get("since") if m.get("since") is not None else max(0, self.p.list.last_n - 100))
        for entry in self.p.list.read(since=since, run=self.tail_run):
            self.push({"t": "entry", "entry": entry})
        self.subs.add("tail")
        return {"n": self.p.list.last_n}

    async def _do_devices(self, m):
        return {"devices": [public_device(d) for d in self.p.views.devices.values()]}

    async def _do_spaces(self, m):
        return {"spaces": self.p.documents.spaces(), "folders": self.p.settings.folders_dir}

    async def _do_add_space(self, m):
        try:
            got = await self.p.documents.add_space(str(m.get("repo") or ""),
                                                   str(m.get("name") or "") or None,
                                                   folder=str(m.get("folder") or ""))
        except DocumentsError as exc:
            raise rules.Refused(str(exc))
        body = {"space": got["name"], **{k: v for k, v in got.items() if k != "name"}}
        self.p.list.append("space.added", by=self.device_id, body=body)
        return body

    # -- acting ----------------------------------------------------------------------

    async def _do_start(self, m):
        opts = rules.start_options(self.surface or "", m)
        if (opts.get("engine") == "codex" and opts.get("billing") != billing.API
                and not m.get("billing") and codex_signin.prefers_api_key()):
            # The person chose, on the Codex sign-in page, to bill every run of Codex to the
            # OpenAI key; a run that says nothing about billing follows that choice.
            opts["billing"] = billing.API
            if not self.p.api_key.available():
                raise rules.Refused("Codex runs are set to the OpenAI key on the Codex sign-in page "
                                    f"({self.p.codex_signin.page()}), and no key has reached the program, "
                                    "so the run was not started and nothing was billed")
        if not self.p.documents.has_space(opts["space"]):
            raise rules.Refused(f"there is no space called {opts['space']!r}: add it from a "
                                "terminal with one space add owner/name")
        if opts.get("billing") == billing.API and not self.p.api_key.available():
            raise rules.Refused("no OpenAI API key has reached the program, so a run cannot be "
                                "billed to it. Start it on the ChatGPT subscription instead.")
        run_id = self.p.runs.request(opts, by=self.device_id, surface=self.surface or "")
        return {"run": run_id}

    async def _do_stop(self, m):
        await self.p.runs.stop(self._run_id(m), by=self.device_id)
        return {}

    async def _do_archive(self, m):
        """Put a run out of the list's way, or bring it back.

        Putting it away stops it: the person is done with it, so the terminal
        behind it is closed too. Bringing it back starts nothing.
        """
        run = await self.p.runs.archive(self._run_id(m), by=self.device_id,
                                        on=bool(m.get("on", True)))
        return {"run": self._run(run)}

    async def _do_forget(self, m):
        """Forget an ended run for good (`Runs.forget`), or, with `after`, once it has
        ended and that many seconds have gone (`Runs.forget_later`): only from a terminal."""
        if m.get("after") is not None:
            self.p.runs.forget_later(self._run_id(m), by=self.device_id, after=float(m["after"]))
            return {"later": True}
        dropped = await self.p.runs.forget(self._run_id(m), by=self.device_id)
        return {"dropped": dropped}

    async def _do_retitle(self, m):
        """Give a run another title, and another brief when one is sent: only from a terminal."""
        self.p.runs.retitle(self._run_id(m), str(m.get("title") or ""), by=self.device_id,
                            brief=m.get("brief"))
        return {}

    async def _do_resume(self, m):
        await self.p.runs.carry_on(self._run_id(m), by=self.device_id)
        return {}

    async def _do_say(self, m):
        how = await self.p.runs.say(self._run_id(m), str(m.get("text") or ""), by=self.device_id,
                                    files=_files_of(m.get("files")))
        return {"how": how}

    async def _do_answer(self, m):
        qid, answer = str(m.get("question") or ""), str(m.get("answer") or "").strip().lower()
        q = dict(self.p.views.questions.get(qid) or {})
        if not self.p.questions.answer(qid, answer, by=self.device_id):
            raise rules.Refused("that question is closed, or the answer was not yes or no")
        # What the answer does, in the words its button said, for whoever
        # answered by voice and has to say it back.
        choices = q.get("choices") or {}
        return {"said": choices.get(answer)} if choices.get(answer) else {}

    async def _do_codex_key(self, m):
        """Rouh hands over the OpenAI API key, for runs of Codex billed to it.

        Held in memory and nowhere else (billing.Key). Nothing about it is
        answered back, written to the list or logged.
        """
        self.p.api_key.give(str(m.get("key") or ""))
        return {"codex_api": self.p.api_key.available()}

    async def _do_shell(self, m):
        """Rouh's read-only shell, in the containers only (one/shell.py)."""
        if os.environ.get("ONE_SHELL_FOR_ROUH") != "1":
            raise rules.Refused("this program does not run Rouh's shell")
        from . import shell

        text = await asyncio.to_thread(shell.run, m.get("stages"), cwd=str(self.p.settings.workspace or ""),
                                       timeout=float(m.get("timeout") or 20), limit=int(m.get("limit") or 4000))
        return {"text": text}

    async def _do_claude_signin(self, m):
        """Rouh's page signs Claude Code in, in the containers (one/claude_signin.py).

        ``do`` is status, start (answers the sign-in page's address), code
        (the code Claude showed), cancel, or api_key with ``on``: Claude Code
        sent through the key proxy, which adds the installation's key.
        """
        return await self.p.claude_signin.handle(str(m.get("do") or "status"), m)

    async def _do_codex_signin(self, m):
        """Rouh's page signs Codex in with a ChatGPT plan, in the containers (one/codex_signin.py).

        ``do`` is status, start (answers the address and the one-time code), cancel, logout,
        test (one trivial run), or api_key with ``on``: the person's own choice of billing
        every run of Codex to the OpenAI key instead.
        """
        return await self.p.codex_signin.handle(str(m.get("do") or "status"), m)

    # -- terminals ---------------------------------------------------------------------

    async def _do_attach(self, m):
        run_id = self._run_id(m)
        terminal = self.p.terminals.get(run_id)
        if terminal is None or not terminal.connected:
            raise rules.Refused("that run has no terminal right now")
        key = f"client-{id(self)}"
        encode = base64.b64encode

        def watcher(data: bytes) -> None:
            self.push({"t": "tty", "run": run_id, "b64": encode(data).decode()})

        if self.surface == "terminal" and m.get("cols") and m.get("rows"):
            before = (terminal.cols, terminal.rows)
            await terminal.resize(int(m["cols"]), int(m["rows"]))
            if (terminal.cols, terminal.rows) != before:
                self._sized(run_id, terminal)
        terminal.watchers[key] = watcher
        first = run_id not in self.attached
        self.attached[run_id] = time.time()
        # With history, the run's recent output rather than its screen alone, so
        # a page can scroll back through it (D50).
        shown = terminal.history() if m.get("history") else terminal.screen_ansi()
        self.push({"t": "screen", "run": run_id, "b64": encode(shown).decode(),
                   "cols": terminal.cols, "rows": terminal.rows,
                   # Whose size the screen is drawn for: a page that opens a
                   # run a real terminal already has open shows it at that
                   # terminal's size, and never pushes its own box's (D52).
                   "sized_by": self.sizing_terminal(run_id)})
        if first:
            self.p.list.append("run.attached", run=run_id, by=self.device_id,
                               body={"surface": self.surface})
        if self.surface == "terminal":
            await terminal.nudge_redraw()
        return {"cols": terminal.cols, "rows": terminal.rows,
                "driver": self.p.runs.driver(run_id),
                "sized_by": self.sizing_terminal(run_id)}

    async def _do_detach(self, m):
        await self._detach(self._run_id(m))
        return {}

    async def _detach(self, run_id: str) -> None:
        if run_id not in self.attached:
            return
        self.attached.pop(run_id, None)
        terminal = self.p.terminals.get(run_id)
        if terminal is not None:
            terminal.watchers.pop(f"client-{id(self)}", None)
            # The last real terminal has gone: its size is nobody's now, and a
            # page watching may take the run's terminal to its own box (D52).
            if self.surface == "terminal" and self.sizing_terminal(run_id) is None:
                self._sized(run_id, terminal, by=None)
        if self.p.runs.driver(run_id) == self.device_id and not any(
                c is not self and run_id in c.attached and c.device_id == self.device_id
                for c in self.p.clients):
            await self.p.runs.give(run_id, by=self.device_id)
        if run_id in self.p.views.runs:
            self.p.list.append("run.detached", run=run_id, by=self.device_id,
                               body={"surface": self.surface})

    async def _do_take(self, m):
        run_id = self._run_id(m)
        if self.surface == "voice":
            # "Let me drive" said out loud: the keyboard goes to the terminal
            # that has the run open, which is where the person's hands are.
            terminals = sorted((c for c in self.p.clients if c.surface == "terminal"
                                and run_id in c.attached), key=lambda c: c.attached[run_id])
            if not terminals:
                raise rules.Refused("nobody has that run open in a terminal. Open it there first "
                                    "with one attach, then ask again.")
            target = terminals[-1]
        else:
            if run_id not in self.attached:
                raise rules.Refused("attach to the run first")
            target = self
        # Hands in a real terminal beat a page's (D52). A browser holds a
        # run's keyboard for two minutes after the last key, so `one take`
        # from a terminal met "your browser is already driving it" and the
        # person could not type anywhere. The page is told it is watching.
        driver = self.p.runs.driver(run_id)
        held = self.p.runs.takeovers.get(run_id)
        if (driver and driver != target.device_id and target.surface == "terminal"
                and held is not None and held.direct):
            await self.hand_back(run_id, driver)
        self.p.runs.take(run_id, target.device_id, asked_by=self.device_id,
                         direct=target.surface == "browser")
        target.push({"t": "driving", "run": run_id})
        return {"driver": target.device_id}

    async def _do_give(self, m):
        run_id = self._run_id(m)
        driver = self.p.runs.driver(run_id)
        if driver is None:
            return {}
        if self.surface != "voice" and driver != self.device_id:
            raise rules.Refused(f"{self.p.device_name(driver)} is driving it, not you")
        await self.hand_back(run_id, driver)
        return {}

    async def hand_back(self, run_id: str, driver: str) -> None:
        """Hand a run back, and tell whoever was driving that they are watching."""
        await self.p.runs.give(run_id, by=self.device_id)
        for client in list(self.p.clients):
            if client.device_id == driver and run_id in client.attached:
                client.push({"t": "watching", "run": run_id})

    async def _do_input(self, m):
        run_id = self._run_id(m)
        if m.get("b64"):
            data = base64.b64decode(m["b64"])
        else:
            data = str(m.get("text") or "").encode("utf-8")
        # A dropped file's path comes in as a paste, which is the only way
        # Claude Code turns it into an attachment (D52).
        await self.p.runs.type_in(run_id, self.device_id, data,
                                  paste=bool(m.get("paste")))
        return {}

    async def _do_scroll(self, m):
        run_id = self._run_id(m)
        if run_id not in self.attached:
            raise rules.Refused("attach to the run first")
        await self.p.runs.scroll(run_id, self.device_id, int(m.get("lines") or 0),
                                 int(m.get("col") or 1), int(m.get("row") or 1))
        return {}

    async def _do_mouse(self, m):
        run_id = self._run_id(m)
        if run_id not in self.attached:
            raise rules.Refused("attach to the run first")
        await self.p.runs.mouse(run_id, self.device_id, base64.b64decode(m.get("b64") or ""))
        return {}

    async def _do_resize(self, m):
        run_id = self._run_id(m)
        # A browser sizes a run's terminal to its window (D50), unless somebody
        # else has the run's keyboard: then its size is theirs.
        driver = self.p.runs.driver(run_id)
        if self.surface == "browser" and driver and driver != self.device_id:
            raise rules.Refused(f"{self.p.device_name(driver)} has its keyboard, and sets its size")
        # A real terminal is a window of its own, and the person who opened it
        # is looking at it: while it has the run open, the run's terminal is
        # that terminal's size and nothing else may change it (D52). Before
        # this, a page's own box pushed a size back the moment it was clicked,
        # and the terminal the person was typing in shrank under them.
        sizer = self.sizing_terminal(run_id)
        if sizer and self.surface != "terminal":
            raise rules.Refused(f"{self.p.device_name(sizer)} has this run open in a terminal, "
                                "and its size is that terminal's")
        terminal = self.p.terminals.get(run_id)
        if terminal is None:
            return {}
        before = (terminal.cols, terminal.rows)
        await terminal.resize(int(m["cols"]), int(m["rows"]))
        if (terminal.cols, terminal.rows) != before:
            self._sized(run_id, terminal)
        return {"cols": terminal.cols, "rows": terminal.rows}

    def sizing_terminal(self, run_id: str) -> str | None:
        """The real terminal that has this run open, if another connection is
        one (D52). While there is one, the run's terminal is its size."""
        for client in list(self.p.clients):
            if client is not self and client.surface == "terminal" and run_id in client.attached:
                return client.device_id
        return None

    def _sized(self, run_id: str, terminal, by: str | None = "") -> None:
        """Tell everyone else watching a run its terminal's new size (D51).

        What the run draws next is drawn for that size. On 15 September two
        pages had one run open, each at its own size, and one of them showed
        Claude Code's lines drawn for the other's width. ``by`` of None says
        the size is nobody's now: the last real terminal has closed, and a
        page may size the run to its own box again (D52).
        """
        who = self.device_id if by == "" else by
        for client in list(self.p.clients):
            if client is not self and run_id in client.attached:
                client.push({"t": "size", "run": run_id, "cols": terminal.cols,
                             "rows": terminal.rows, "by": who,
                             "terminal": bool(who) and self.surface == "terminal"})

    # -- devices -------------------------------------------------------------------------

    async def _do_pair(self, m):
        surface = str(m.get("surface") or "browser")
        name = str(m.get("name") or "").strip()[:40] or surface
        if surface == "browser" and m.get("direct"):
            # A browser device made at once, for whoever holds this program's socket on the
            # machine itself: the worker's start, pairing Rouh's own page in the containers,
            # where Rouh passes the program's pages on to a person already signed in to Rouh
            # (`rouh/onebridge.py`). Never over the network, the same as a terminal or a voice.
            if not self.local:
                raise rules.Refused("a browser can only be paired directly on the server itself")
            token = new_token()
            device_id = new_device_id(name)
            self.p.list.append("device.paired", by=self.device_id, body={
                "device": device_id, "name": name, "surface": "browser", "token_hash": hash_token(token)})
            return {"device": device_id, "token": token}
        if surface == "browser":
            code = self.p.pairing.issue(surface="browser", name=name, by=self.device_id)
            self.p.list.append("pair.code-issued", by=self.device_id,
                               body={"surface": "browser", "name": name})
            return {"code": code.code, "expires_in": int(code.expires - time.time()),
                    "url": f"{self.p.settings.public_url}/pair"}
        if surface not in ("terminal", "voice"):
            raise rules.Refused(f"there is no surface called {surface!r}")
        if not self.local:
            raise rules.Refused("a terminal or a voice can only be paired on the server itself")
        token = new_token()
        device_id = new_device_id(name)
        self.p.list.append("device.paired", by=self.device_id, body={
            "device": device_id, "name": name, "surface": surface, "token_hash": hash_token(token)})
        return {"device": device_id, "token": token}

    async def _do_revoke(self, m):
        device_id = str(m.get("device") or "")
        if device_id not in self.p.views.devices:
            raise rules.Refused(f"there is no device {device_id!r}")
        self.p.list.append("device.revoked", by=self.device_id, body={"device": device_id})
        return {}

    # -- closing -------------------------------------------------------------------------

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.p.transcripts.forget(self)
        for run_id in list(self.attached):
            with contextlib.suppress(Exception):
                await self._detach(run_id)
        self.p.clients.discard(self)
        self._sender.cancel()


def _files_of(raw) -> list[tuple[str, str, bytes]]:
    """The files a ``say`` carries: each {"name", "type", "data"}, data in base64.

    Rouh sends the pictures a person asked it to hand to a run this way,
    because the folder it keeps them in is one no run can read.
    """
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("files has to be a list")
    out = []
    for one in raw:
        if not isinstance(one, dict):
            raise ValueError("each file has to be a name, a type and its data")
        try:
            data = base64.b64decode(str(one.get("data") or ""), validate=True)
        except ValueError:
            raise ValueError(f"{one.get('name') or 'a file'} did not arrive whole") from None
        out.append((str(one.get("name") or ""), str(one.get("type") or ""), data))
    return out
