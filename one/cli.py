"""``one``: the program, from a terminal.

    one ls                       what is running, and what ran recently
    one start "brief"            start a run of Claude Code in the workspace
    one shell                    start a shell of your own, in a checkout, and drive it
    one claude [<run>]           your own Claude Code, on the server, typed to from here
    one show <run>               one run: what it is doing, its last entries, its screen
    one attach <run>             watch a run's terminal, typing nothing (Ctrl-] leaves)
    one take <run>               watch it and type into it (Ctrl-] hands it back and leaves)
    one give <run>               hand a run back
    one say <run> "text"         give a run of Claude Code a message
    one stop <run>               stop a run
    one questions                what the runs are asking
    one answer <question> yes|no answer one
    one tree                     the work tree, as text
    one tail [<run>]             the list as it grows
    one pair browser             a code to pair a browser with
    one devices                  paired devices
    one revoke <device>          stop a device working, from any other

A run is named by the start of its id: ``one take 6aa9`` is enough.

On the server it talks to the program's socket, ``/run/one/one.sock``. Only
root and the program's own user may open that socket, so from any other
account here the command asks sudo to run ``one proxy`` as root: on 16
September ``one attach`` from the server's own shell went looking for the
server by its ssh name instead, because the socket it could not see was read
as "this is not the server".

Anywhere else it talks to the server through ssh (``ONE_HOST``, the name
ssh knows the server by, which each machine sets for itself), identified by the token in ``~/.config/one/device.json``. Only the
standard library, so it runs with whatever Python a machine has.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import shutil
import signal
import sys
import time
from pathlib import Path

SOCKET = os.environ.get("ONE_SOCKET", "/run/one/one.sock")
HOST = os.environ.get("ONE_HOST", "")
DEVICE_FILE = Path(os.environ.get("ONE_DEVICE_FILE", "~/.config/one/device.json")).expanduser()
LEAVE = b"\x1d"  # Ctrl-]
ENDED = ("done", "unfinished", "failed", "lost", "refused", "reaped")


def on_the_server() -> bool:
    """Whether the program is on this machine.

    Not "can this account open the socket": the socket is ``srw-------`` and
    owned by the program's user, so every other account on the server is
    refused before it has read anything, and the folder it sits in cannot even
    be listed. Both are still enough to see that the socket is here.
    """
    return os.path.exists(SOCKET) or os.path.isdir(os.path.dirname(SOCKET) or ".")


def sudo_proxy() -> list[str]:
    """The command that runs ``one proxy`` as root, for an account here that
    may not open the socket itself. It speaks the same JSON over its input and
    output as ssh does, so nothing above this cares which one it got."""
    keep = ["env", f"ONE_SOCKET={SOCKET}"]
    installed = shutil.which("one")
    if installed:
        return ["sudo", "-n", *keep, installed, "proxy"]
    return ["sudo", "-n", *keep, f"PYTHONPATH={os.environ.get('PYTHONPATH', '')}",
            sys.executable, "-m", "one.cli", "proxy"]


class Connection:
    """The same messages over the socket, or over ssh or sudo to the socket."""

    def __init__(self) -> None:
        self.reader: asyncio.StreamReader | None = None
        self.writer = None
        self.proc = None
        #: How it reached the program: its socket here, sudo as root here, or ssh.
        self.through = "socket"
        self._next = 0
        self._waiting: dict[int, asyncio.Future] = {}
        self.pushes: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def open(self) -> None:
        if on_the_server():
            await self._here()
        else:
            self.through = "ssh"
            if not HOST:
                raise SystemExit("This is not the server, and ONE_HOST does not say which server to "
                                 "reach over ssh. Set ONE_HOST to the name ssh knows it by.")
            await self._spawn(["ssh", "-T", "-o", "BatchMode=yes", HOST, "one", "proxy"])
        self._task = asyncio.create_task(self._read())

    async def _here(self) -> None:
        """The socket on this machine, as this account or through sudo as root.

        Being refused the socket and the socket not being there are different
        things, and saying so is the whole point: the first is this account,
        the second is the program.
        """
        try:
            self.reader, self.writer = await asyncio.open_unix_connection(SOCKET, limit=16 << 20)
            return
        except PermissionError as why:
            refused = why
        except (FileNotFoundError, ConnectionRefusedError):
            raise SystemExit(f"one: the program is not running on this machine: nothing is "
                             f"listening on {SOCKET}. Start it with: systemctl start one (on a server), or start the "
                             "worker container (in the containers)")
        if not shutil.which("sudo"):
            raise SystemExit(f"one: {SOCKET} is the program's socket and this account may not "
                             f"open it ({refused}). Run this as root, or as the program's user.")
        self.through = "sudo"
        await self._spawn(sudo_proxy())

    async def _spawn(self, argv: list[str]) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            limit=16 << 20)
        self.reader, self.writer = self.proc.stdout, self.proc.stdin

    def why_it_closed(self) -> str:
        """What to say when nothing came back: which way out it tried, and what
        to do about it. "the connection to the program closed" on its own left
        a person on the server reading ssh complaining about a machine name."""
        if self.through == "ssh":
            return (f"ssh could not reach the server as {HOST!r}. Name the server in ONE_HOST, "
                    f"or run this command on the server itself.")
        if self.through == "sudo":
            return (f"only root and the program's own user may open {SOCKET}, and sudo would not "
                    f"run it as root without asking. Try: sudo one <the same command>")
        return "the connection to the program closed"

    async def _read(self) -> None:
        while True:
            line = await self.reader.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except ValueError:
                continue
            future = self._waiting.pop(message.get("re"), None) if "re" in message else None
            if future is not None and not future.done():
                future.set_result(message)
            else:
                await self.pushes.put(message)
        for future in self._waiting.values():
            if not future.done():
                future.set_result({"t": "err", "why": self.why_it_closed()})
        await self.pushes.put({"t": "closed"})

    def send_nowait(self, message: dict) -> None:
        self.writer.write((json.dumps(message) + "\n").encode())

    async def ask(self, t: str, **fields) -> dict:
        self._next += 1
        future = asyncio.get_running_loop().create_future()
        self._waiting[self._next] = future
        self.send_nowait({"t": t, "id": self._next, **fields})
        await self.writer.drain()
        answer = await future
        if answer.get("t") == "err":
            raise SystemExit(f"one: {answer.get('why')}")
        return answer

    async def hello(self) -> dict:
        fields = {}
        with contextlib.suppress(OSError, ValueError):
            fields["token"] = json.loads(DEVICE_FILE.read_text())["token"]
        return await self.ask("hello", **fields)

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            self.writer.close()
        if self.proc is not None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.terminate()
            # Waited for, or asyncio complains at exit that nobody reaped ssh.
            with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                await asyncio.wait_for(self.proc.wait(), 5)


# ---------------------------------------------------------------------------
# Showing things
# ---------------------------------------------------------------------------

STATE_WORDS = {"queued": "queued", "starting": "starting", "working": "working",
               "asking": "NEEDS YOU", "saving": "saving its work", "idle": "finished its turn",
               "done": "done", "unfinished": "UNFINISHED",
               "failed": "failed", "lost": "lost", "refused": "refused",
               "reaped": "cleaned up"}


def state_words(run: dict) -> str:
    """A run's state in one phrase, with the reason a queued run is waiting.

    "waiting to start" said nothing about what the wait was for and read as
    stuck. The scheduler works the reason out (``scheduler.why_wait``) and puts
    it on the run; a run queued for the moment before it has looked at one has
    no reason yet, and "queued" alone is the truth about it.
    """
    state = str(run.get("state") or "")
    word = STATE_WORDS.get(state, state)
    if state == "unfinished" and run.get("left"):
        return f"{word} - {run['left']}"
    why = run.get("queued_because")
    return f"{word} - {why}" if state == "queued" and why else word


def _ago(at: str | None) -> str:
    if not at:
        return ""
    from datetime import datetime
    seconds = time.time() - datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp()
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    return f"{int(seconds // 86400)}d ago"


def print_runs(runs: list[dict]) -> None:
    if not runs:
        print("No runs yet. Start one with: one start \"what to do\"")
        return
    width = shutil.get_terminal_size((100, 20)).columns
    for run in runs:
        state = STATE_WORDS.get(run["state"], run["state"])
        who = f" driven by {run['driver']}" if run.get("driver") else ""
        doing = f" - {run['doing']}" if run.get("doing") and run["state"] == "working" else ""
        # The state column is as wide as the longest single word, and a queued
        # run's reason is a sentence, so it goes where a working run says what
        # it is doing rather than pushing every other row sideways.
        if run["state"] == "queued" and run.get("queued_because"):
            doing = f" - {run['queued_because']}"
        # A run of Codex billed to the API key says so on its own line, every time.
        paid = " [Codex, billed to the OpenAI API key]" if run.get("billing") == "api" else ""
        line = (f"{run['id']}  {state:<17} {run['title']}{paid}{doing}{who}  "
                f"({_ago(run.get('last_at'))})")
        print(line[:width])


def print_processes(seen: dict) -> None:
    """What the service is holding, biggest first, with what has no owner marked.

    The point of it is the last column. A machine whose memory is climbing
    looks exactly like a busy one in a total; it does not look like one here,
    where anything the reaper is about to sweep says so on its own line.
    """
    if seen.get("error"):
        print(f"Could not read the process table: {seen['error']}")
        return
    rows = seen.get("top") or []
    if not rows:
        print("Nothing is running under this service.")
        return
    held = seen.get("rss_bytes", 0)
    print(f"{seen['processes']} processes, holding {_mb(held)}"
          + (f", of which {_mb(seen['stray_bytes'])} in {seen['strays']} "
             f"with no owner" if seen.get("strays") else ""))
    layout = seen.get("layout") or {}
    if not layout.get("settled") and layout.get("why"):
        print(f"  (no per-run ceilings: {layout['why']})")
    print()
    print(f"  {'PID':>8}  {'AGE':>9}  {'HELD':>9}  {'RUN':<10}  WHAT")
    for row in rows:
        mark = "  <- stray" if row["stray"] else ("  <- run is over" if row["gone_run"] else "")
        print(f"  {row['pid']:>8}  {_age(row['age']):>9}  {_mb(row['rss_bytes']):>9}  "
              f"{(row['run'] or '-'):<10}  {row['what'][:60]}{mark}")
    scratch = seen.get("scratch") or {}
    where = "memory" if scratch.get("tmpfs") else "disk"
    if scratch.get("loose_bytes"):
        print(f"\n  and {_mb(scratch['loose_bytes'])} of {where} in "
              f"{scratch['loose']} leftover folders under {scratch['path']}")
    if scratch.get("unreadable"):
        # Never reported as nothing. A folder this user cannot look inside held
        # 2.7 GB of memory on 22 September while the sweep said "0 MB".
        print(f"\n  and {scratch['unreadable']} leftover folders under "
              f"{scratch['path']} that belong to the run's user, so their size "
              f"cannot be read from here; the sweep hands those to that user")


def _mb(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.1f} GB"
    return f"{n / (1 << 20):.0f} MB"


def _age(seconds: float) -> str:
    if seconds >= 86400:
        return f"{seconds / 86400:.1f} d"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    if seconds >= 60:
        return f"{seconds / 60:.0f} m"
    return f"{seconds:.0f} s"


def one_line(entry: dict) -> str:
    """What an entry says, on one line.

    A run's first prompt is the person's request with the program's own
    instructions after a line of three dashes; only the request is theirs.
    """
    body = entry.get("body") or {}
    said = str(body.get("what") or body.get("text") or body.get("message") or body.get("why") or "")
    said = said.split("\n---\n")[0]
    return " ".join(said.split())


def print_tree(node: dict, depth: int = 0) -> None:
    for child in node.get("children", []):
        label = child.get("what") or child.get("label") or child["id"]
        state = child.get("state")
        mark = {"running": "~", "waiting": "!", "done": "-", "failed": "x", "lost": "?"}.get(state, " ")
        print(f"{'  ' * depth}{mark} {label}")
        print_tree(child, depth + 1)


# ---------------------------------------------------------------------------
# Attaching: a run's terminal in this one
# ---------------------------------------------------------------------------


async def attach(conn: Connection, run: str, *, take: bool, session: bool = False) -> None:
    import termios
    import tty

    stdin, stdout = sys.stdin.fileno(), sys.stdout.buffer
    cols, rows = shutil.get_terminal_size((120, 40))
    await conn.ask("attach", run=run, cols=cols, rows=rows)
    driving = False
    if take:
        try:
            await conn.ask("take", run=run)
            driving = True
        except SystemExit as refused:
            # Somebody else is driving. Watching it is still worth having, and
            # it is better than being dropped back at a shell prompt.
            print(f"{refused} Watching it instead.")
    if not driving:
        # Said before the run's screen covers it: keys typed into a terminal
        # that is only watching reach nobody, and on 16 September that read as
        # a frozen terminal.
        print(f"Watching {run}. Your keys do not reach it: type into it with "
              f"`one take {run}`. Ctrl-] leaves.")
    old = termios.tcgetattr(stdin)
    tty.setraw(stdin)
    loop = asyncio.get_running_loop()
    done = asyncio.Event()

    def title(text: str) -> None:
        stdout.write(f"\x1b]0;{text}\x07".encode())
        stdout.flush()

    title(f"one: {'driving' if driving else 'watching'} {run}")
    said = False

    def on_key() -> None:
        # `driving` is only read here, so it needs no declaration; `said` is
        # written, so it does.
        nonlocal said
        data = os.read(stdin, 4096)
        if not data or LEAVE in data:
            done.set()
            return
        if driving:
            conn.send_nowait({"t": "input", "run": run, "b64": base64.b64encode(data).decode()})
        elif not said:
            # Typed at a run this terminal is only watching. The screen belongs
            # to the run, so the title bar is where it can be said.
            said = True
            title(f"one: watching {run} - your keys go nowhere; one take {run} to type")

    def on_resize() -> None:
        c, r = shutil.get_terminal_size((120, 40))
        conn.send_nowait({"t": "resize", "run": run, "cols": c, "rows": r})

    loop.add_reader(stdin, on_key)
    loop.add_signal_handler(signal.SIGWINCH, on_resize)
    try:
        while not done.is_set():
            getter = asyncio.create_task(conn.pushes.get())
            waiter = asyncio.create_task(done.wait())
            finished, _ = await asyncio.wait({getter, waiter}, return_when=asyncio.FIRST_COMPLETED)
            if getter not in finished:
                getter.cancel()
                break
            waiter.cancel()
            message = getter.result()
            kind = message.get("t")
            if kind in ("screen", "tty") and message.get("run") == run:
                stdout.write(base64.b64decode(message["b64"]))
                stdout.flush()
            elif kind == "driving" and message.get("run") == run:
                driving, said = True, False
                title(f"one: driving {run}")
            elif kind == "watching" and message.get("run") == run:
                driving, said = False, False
                title(f"one: watching {run}")
            elif kind == "entry" and message["entry"].get("run") == run \
                    and message["entry"]["kind"] == "run.ended":
                break
            elif kind == "closed":
                break
    finally:
        loop.remove_reader(stdin)
        loop.remove_signal_handler(signal.SIGWINCH)
        termios.tcsetattr(stdin, termios.TCSADRAIN, old)
        if driving:
            with contextlib.suppress(SystemExit):
                await conn.ask("give", run=run)
        with contextlib.suppress(SystemExit):
            await conn.ask("detach", run=run)
        # The run's screen came with the modes its program had on (D51): this
        # terminal is given back off the full screen and not telling of the mouse.
        stdout.write(b"\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l\x1b[?2004l\x1b[?1l"
                     b"\x1b[?1049l\x1b[?25h\x1b[0m\r\n")
        stdout.flush()
        if session:
            print(f"Left your session {run}. It carries on; come back with: one claude {run}")
        else:
            print(f"Left run {run}{', and handed it back' if driving else ''}.")


async def wait_for_terminal(conn: Connection, run: str, timeout: float = 30.0) -> None:
    """Until the run's terminal is up, or say plainly why it never came up."""
    deadline = time.monotonic() + timeout
    told = False
    while True:
        info = await conn.ask("run", run=run, entries=1)
        state = info["run"]["state"]
        if info.get("screen") is not None and state not in ENDED:
            return
        if state in ENDED:
            raise SystemExit(f"one: it did not start: {info['run'].get('how') or state}")
        if state == "queued":
            # Waiting for a free place is not a failure: it starts when one
            # ends. A run just asked for is queued for a moment too, until the
            # scheduler looks at it; that is not worth a word.
            why = info["run"].get("queued_because")
            if why and not told:
                print(f"Queued: {why}.")
                told = True
            deadline = time.monotonic() + timeout
        elif time.monotonic() > deadline:
            raise SystemExit(f"one: its terminal did not come up in time; look with: one show {run}")
        await asyncio.sleep(0.1)


# ---------------------------------------------------------------------------
# The commands
# ---------------------------------------------------------------------------


async def run_command(args: argparse.Namespace) -> int:
    if args.cmd == "proxy":
        return await proxy()
    conn = Connection()
    await conn.open()
    hello = await conn.hello()
    try:
        return await dispatch(conn, hello, args)
    finally:
        await conn.close()


async def dispatch(conn: Connection, hello: dict, a: argparse.Namespace) -> int:
    if a.cmd in (None, "ls"):
        got = await conn.ask("runs", limit=a.limit if a.cmd == "ls" else 20,
                             open=bool(getattr(a, "open", False)))
        print_runs(got["runs"])
    elif a.cmd == "start":
        fields = {"brief": a.brief}
        for name in ("title", "space", "model"):
            if getattr(a, name, None):
                fields[name] = getattr(a, name)
        if getattr(a, "codex", False):
            fields["engine"] = "codex"
        if getattr(a, "api", False):
            fields["billing"] = "api"
        got = await conn.ask("start", **fields)
        print(f"Started run {got['run']}. Watch it with: one attach {got['run']}")
    elif a.cmd == "shell":
        got = await conn.ask("start", kind="shell", **({"space": a.space} if a.space else {}))
        await wait_for_terminal(conn, got["run"])
        await attach(conn, got["run"], take=True)
    elif a.cmd in ("claude", "codex"):
        # Stage 4: your own agent runs on the server, in its own checkout of
        # the workspace, and this terminal is its keyboard. `one claude` is
        # Claude Code and `one codex` is Codex; nothing else about them differs.
        if a.run:
            run = (await conn.ask("run", run=a.run, entries=0))["run"]
            run_id = run["id"]
            if run["state"] in ENDED:
                await conn.ask("resume", run=run_id)
        else:
            fields = {"interactive": True, "engine": a.cmd}
            for name in ("title", "model", "space"):
                if getattr(a, name, None):
                    fields[name] = getattr(a, name)
            run_id = (await conn.ask("start", **fields))["run"]
            print(f"Your session is run {run_id}. Ctrl-] leaves it running.")
        await wait_for_terminal(conn, run_id)
        await attach(conn, run_id, take=True, session=True)
    elif a.cmd == "spaces":
        for sp in (await conn.ask("spaces"))["spaces"]:
            print(f"{sp['name']:<28} {sp.get('repo') or ('the folder ' + sp['folder'] if sp.get('folder') else '')}")
    elif a.cmd == "space":
        if bool(a.folder) == bool(a.repo):
            print("one: give a repository, owner/name, or --folder and a project's name")
            return 2
        what = {"folder": a.folder} if a.folder else {"repo": a.repo}
        got = await conn.ask("add_space", **what, **({"name": a.name} if a.name else {}))
        if got.get("kind") == "folder":
            made = " (made just now)" if got.get("made") else ""
            how = f"runs work in {got['folder']}{made} directly, and nothing is saved for them"
        elif got.get("flow") == "branch":
            how = f"its work goes up on its own branch, for a pull request into {got['target']}"
        else:
            how = f"its work is saved to {got.get('target') or 'main'}"
        print(f"Added the space {got['space']}: {how}. Start one with: one claude --space {got['space']}")
    elif a.cmd == "show":
        got = await conn.ask("run", run=a.run, entries=a.entries)
        run = got["run"]
        print(f"{run['id']}  {state_words(run)}  {run['title']}")
        for key in ("space", "branch", "target", "cwd", "session_id", "driver", "landed",
                    "compare", "land_reason", "ended_why"):
            if run.get(key):
                print(f"  {key}: {run[key]}")
        if run.get("last_message"):
            print(f"  last said: {run['last_message'][:400]}")
        print("\nLast entries:")
        for entry in got["entries"]:
            print(f"  {entry['at'][11:19]} {entry['kind']:<18} {one_line(entry)[:90]}")
        if got.get("screen"):
            print("\nScreen now:\n" + got["screen"])
    elif a.cmd in ("attach", "take"):
        await attach(conn, (await conn.ask("run", run=a.run, entries=0))["run"]["id"],
                     take=a.cmd == "take")
    elif a.cmd == "give":
        await conn.ask("give", run=a.run)
        print("Handed back.")
    elif a.cmd == "say":
        got = await conn.ask("say", run=a.run, text=a.text)
        print({"sent": "Sent.", "queued": "It is working; it gets this when its turn ends.",
               "carried on": "It had ended; it is carrying on with this."}.get(got["how"], got["how"]))
    elif a.cmd == "stop":
        await conn.ask("stop", run=a.run)
        print("Stopping.")
    elif a.cmd == "questions":
        got = await conn.ask("questions")
        if not got["questions"]:
            print("Nothing is waiting for you.")
        for q in got["questions"]:
            print(f"{q['id']}  run {q['run']}: {q['text']}")
    elif a.cmd == "answer":
        await conn.ask("answer", question=a.question, answer=a.answer)
        print("Answered.")
    elif a.cmd == "processes":
        print_processes(await conn.ask("processes", limit=a.limit))
    elif a.cmd == "tree":
        got = await conn.ask("tree")
        if not got["tree"].get("children"):
            print("Nothing is running.")
        print_tree(got["tree"])
    elif a.cmd == "tail":
        fields = {"run": a.run} if a.run else {}
        await conn.ask("tail", since=a.since, **fields)
        while True:
            message = await conn.pushes.get()
            if message.get("t") == "closed":
                break
            if message.get("t") == "entry":
                e = message["entry"]
                print(f"{e['n']:>7} {e['at'][11:23]} {e.get('run') or '-':<8} {e['kind']:<18} "
                      f"{one_line(e)[:80]}", flush=True)
    elif a.cmd == "pair":
        direct = a.surface == "browser" and bool(a.save)
        got = await conn.ask("pair", surface=a.surface, name=a.name or a.surface,
                             **({"direct": True} if direct else {}))
        if a.surface == "browser" and not direct:
            print(f"Code: {got['code']}\nOpen {got['url']} on the browser and type it within "
                  f"{got['expires_in'] // 60} minutes. It works once.")
        elif a.save:
            path = Path(a.save).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as fh:
                json.dump({"device": got["device"], "token": got["token"]}, fh)
            print(f"Paired {got['device']}; its token is in {path}.")
        else:
            print(json.dumps({"device": got["device"], "token": got["token"]}))
    elif a.cmd == "devices":
        got = await conn.ask("devices")
        for d in got["devices"]:
            gone = f"  revoked {d['revoked_at'][:16]}" if d.get("revoked_at") else ""
            print(f"{d['id']:<24} {d['surface']:<9} {d['name']}{gone}")
    elif a.cmd == "revoke":
        await conn.ask("revoke", device=a.device)
        print("Revoked.")
    elif a.cmd == "forget":
        for run in a.runs:
            if a.when_ended is not None:
                await conn.ask("forget", run=run, after=a.when_ended)
                print(f"{run} is forgotten {a.when_ended:g} seconds after it ends.")
                continue
            got = await conn.ask("forget", run=run)
            print(f"Forgot {run}: {got.get('dropped', 0)} list entries and its folder deleted.")
    elif a.cmd == "retitle":
        await conn.ask("retitle", run=a.run, title=a.title,
                       **({"brief": a.brief} if a.brief is not None else {}))
        print(f"{a.run} is now called {a.title!r}.")
    return 0


async def proxy() -> int:
    """Pass this process's input and output to the socket and back. What ssh runs."""
    reader, writer = await asyncio.open_unix_connection(SOCKET, limit=16 << 20)
    loop = asyncio.get_running_loop()
    stdin = asyncio.StreamReader(limit=16 << 20)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(stdin), sys.stdin)

    async def up() -> None:
        while True:
            data = await stdin.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
        writer.close()

    async def down() -> None:
        out = sys.stdout.buffer
        while True:
            data = await reader.read(65536)
            if not data:
                break
            out.write(data)
            out.flush()

    await asyncio.wait({asyncio.create_task(up()), asyncio.create_task(down())},
                       return_when=asyncio.FIRST_COMPLETED)
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="one", description="The one program, from a terminal.")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("ls", help="what is running")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--open", action="store_true", help="only runs that have not ended")
    s = sub.add_parser("start", help="start a run of Claude Code")
    s.add_argument("brief")
    s.add_argument("--title")
    space_help = "the repository to work in, as `one spaces` lists them; the assistant if not given"
    s.add_argument("--space", help=space_help)
    s.add_argument("--model")
    s.add_argument("--codex", action="store_true",
                   help="run Codex instead of Claude Code, which is what a run is otherwise")
    s.add_argument("--api", action="store_true",
                   help="with --codex: bill it to the OpenAI API key, per token, instead of the "
                        "ChatGPT subscription Codex is logged in with")
    s = sub.add_parser("shell", help="a shell of your own, in a checkout")
    s.add_argument("--space", help=space_help)
    for name, what in (("claude", "Claude Code"), ("codex", "Codex")):
        s = sub.add_parser(name, help=f"your own {what}, on the server, typed to from here")
        s.add_argument("run", nargs="?", help="go back to this session, carrying it on if it ended")
        s.add_argument("--space", help=space_help)
        s.add_argument("--title")
        s.add_argument("--model")
    sub.add_parser("spaces", help="the repositories a run can work in")
    s = sub.add_parser("space", help="add a space: one space add owner/name, "
                                     "or one space add --folder project")
    s.add_argument("action", choices=("add",))
    s.add_argument("repo", nargs="?", help="a repository's GitHub name, owner/name")
    s.add_argument("--folder", help="a project's name, made as a folder on the server if it "
                                    "is not there yet, or a folder's whole path")
    s.add_argument("--name", help="what to call it; the repository's own name if not given")
    s = sub.add_parser("show", help="one run")
    s.add_argument("run")
    s.add_argument("--entries", type=int, default=15)
    for name in ("attach", "take", "give", "stop"):
        sub.add_parser(name).add_argument("run")
    s = sub.add_parser("say")
    s.add_argument("run")
    s.add_argument("text")
    sub.add_parser("questions")
    s = sub.add_parser("answer")
    s.add_argument("question")
    s.add_argument("answer", choices=("yes", "no"))
    s = sub.add_parser("processes",
                       help="what this machine is holding, and what has no owner")
    s.add_argument("--limit", type=int, default=40)
    sub.add_parser("tree")
    s = sub.add_parser("tail")
    s.add_argument("run", nargs="?")
    s.add_argument("--since", type=int, default=None)
    s = sub.add_parser("pair")
    s.add_argument("surface", choices=("browser", "terminal", "voice"))
    s.add_argument("--name")
    s.add_argument("--save", help="write the new device's token to this file")
    sub.add_parser("devices")
    sub.add_parser("revoke").add_argument("device")
    s = sub.add_parser("forget", help="forget ended runs for good: their list entries and folders")
    s.add_argument("runs", nargs="+")
    s.add_argument("--when-ended", type=float, default=None, metavar="SECONDS",
                   help="forget each run this many seconds after it ends, even one still working")
    s = sub.add_parser("retitle", help="give a run another title, and another brief")
    s.add_argument("run")
    s.add_argument("title")
    s.add_argument("--brief", default=None)
    sub.add_parser("proxy", help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return asyncio.run(run_command(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
