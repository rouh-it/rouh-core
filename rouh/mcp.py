"""Speaking MCP, so somebody else's tools can be Rouh's tools.

Every integration in this repository is hand-written. Mail took a week, Drive
took longer, and the next one will take about the same, because each is a set
of tool declarations, a handler apiece, words for the orb and a paragraph of
prompt. The Model Context Protocol is the industry's answer to that: a server
declares its tools over JSON-RPC and any client can call them.

This is that client, small and with no new dependency. Two transports, which is
all anybody actually runs:

- **stdio**: the server is a process here, and messages are JSON-RPC objects
  one per line on its standard input and output. This is what a local server
  is, and it is how most of them ship.
- **streamable HTTP**: one POST per message to one address, answered either
  with JSON or with a short server-sent-event stream. This is what a hosted
  server is.

What reaches the model
----------------------

A server's tools arrive namespaced, `mcp__<server>__<tool>`, the same shape
Claude Code uses, so two servers with a `search` each are two different tools
and the model can never call one meaning the other. They go into the same
registry as the native tools and are called the same way, so they emit the same
`tool_start` and `tool_end`, draw the same twigs on the orb, and are described
by `worklabel` like everything else.

Two rules that are not negotiable, and both are about trust:

- **What an MCP server returns is somebody else's words.** It is a program
  somebody else wrote, often talking to a service somebody else runs, and its
  answer goes into the window framed as untrusted content like a web page or an
  email (`rouh/untrusted.py`). That is done by name in `untrusted.SOURCES`,
  which treats the whole `mcp__` namespace as third-party.
- **A server that will not start does not stop Rouh.** Discovery runs at
  start-up, each server on its own, with a timeout, and one that fails is
  logged and left out of the tool list. A machine with a broken MCP server in
  its configuration is a machine with fewer tools, not a machine with no voice.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shlex
from dataclasses import dataclass, field

log = logging.getLogger("rouh.mcp")

#: The namespace every MCP tool lands in. `mcp__<server>__<tool>`.
PREFIX = "mcp__"

#: The protocol version this client speaks.
VERSION = "2025-06-18"

#: How long to wait for a server to say hello and list its tools. A server that
#: is slower than this at start-up is a server that would be slower than this
#: inside a spoken turn.
START_TIMEOUT = 20.0

#: How long one tool call may take.
CALL_TIMEOUT = 60.0

#: How much of one line the reader will hold. asyncio's default is 64 KiB and
#: `readline` raises past it, which is not a theoretical limit here: one
#: message is one line, and a tool that returns a document returns a line
#: longer than that. A server that sends more than this in one message is
#: doing something nobody asked for, and the read fails with a sentence.
LINE_LIMIT = 16 * 1024 * 1024

#: The most characters of a tool's answer that are carried back. Past this it
#: is cut and said to be cut: somebody else's server has no reason to be
#: trusted with the size of this window either.
MAX_RESULT = 20_000


class McpError(RuntimeError):
    """A server that would not speak, or answered that it could not."""


def tool_name(server: str, tool: str) -> str:
    return f"{PREFIX}{safe_name(server)}__{tool}"


def safe_name(raw: str) -> str:
    """A server name that is safe in a tool name: letters, digits, underscores."""
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in str(raw or ""))
    return out.strip("_")[:40] or "server"


def is_mcp(name: str) -> bool:
    return str(name or "").startswith(PREFIX)


def server_of(name: str) -> str:
    """Which server a namespaced tool belongs to, for saying where it came from."""
    if not is_mcp(name):
        return ""
    return str(name)[len(PREFIX):].split("__", 1)[0]


def plain_name(name: str) -> str:
    """The tool's own name, without the namespace."""
    if not is_mcp(name):
        return str(name or "")
    rest = str(name)[len(PREFIX):].split("__", 1)
    return rest[1] if len(rest) > 1 else rest[0]


@dataclass
class Server:
    """One configured MCP server. Either a command to run or an address to post to."""

    name: str
    command: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    url: str = ""
    headers: dict = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return "stdio" if self.command else "http"


def servers_from(raw) -> list[Server]:
    """The configured servers, from JSON or from a dictionary.

    The shape is the one everything else in this world uses, so a server
    already configured for another client can be pasted in:

        {"weather": {"command": "uvx mcp-server-weather"},
         "notion":  {"url": "https://example.test/mcp",
                     "headers": {"Authorization": "Bearer ..."}}}

    Anything unreadable is nothing rather than an exception: a typo in the
    configuration must cost the tools it describes and not the voice.
    """
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            raw = json.loads(raw)
        except ValueError:
            log.warning("the MCP configuration is not valid JSON, so no servers were read")
            return []
    if not isinstance(raw, dict):
        return []
    # Both spellings: the bare mapping, and the one nested under "mcpServers"
    # that every configuration file in this world happens to use.
    if isinstance(raw.get("mcpServers"), dict):
        raw = raw["mcpServers"]

    out = []
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        command = spec.get("command") or []
        if isinstance(command, str):
            command = shlex.split(command)
        args = spec.get("args") or []
        if isinstance(args, str):
            args = shlex.split(args)
        command = [str(part) for part in [*command, *args]]
        url = str(spec.get("url") or "")
        if not command and not url:
            continue
        out.append(Server(
            name=str(name),
            command=command,
            env={str(k): str(v) for k, v in (spec.get("env") or {}).items()},
            url=url,
            headers={str(k): str(v) for k, v in (spec.get("headers") or {}).items()},
        ))
    return out


def configured(cfg) -> list[Server]:
    """What the configuration asks for: inline JSON, or a file, or nothing."""
    inline = getattr(cfg, "mcp_servers", "") or ""
    if inline:
        return servers_from(inline)
    path = getattr(cfg, "mcp_config", "") or ""
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                return servers_from(fh.read())
        except OSError as exc:
            log.warning("the MCP configuration at %s could not be read: %s", path, exc)
    return []


# ---------------------------------------------------------------------------
# The two transports
# ---------------------------------------------------------------------------


class Transport:
    """What both transports have to do: one request, one answer."""

    async def start(self) -> None:
        raise NotImplementedError

    async def request(self, method: str, params: dict, timeout: float) -> dict:
        raise NotImplementedError

    async def notify(self, method: str, params: dict) -> None:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class Stdio(Transport):
    """A server running here, spoken to in JSON-RPC, one object per line."""

    def __init__(self, server: Server):
        self.server = server
        self.proc: asyncio.subprocess.Process | None = None
        self._next = 0
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        env = dict(os.environ)
        env.update(self.server.env)
        self.proc = await asyncio.create_subprocess_exec(
            *self.server.command,
            limit=LINE_LIMIT,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            # Its own standard error is its own business and is not read: a
            # server that logs faster than anybody reads would otherwise fill
            # a pipe and stop.
            stderr=asyncio.subprocess.DEVNULL,
            env=env,
        )

    async def _send(self, message: dict) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise McpError("the server is not running")
        self.proc.stdin.write((json.dumps(message) + "\n").encode())
        await self.proc.stdin.drain()

    async def _read_answer(self, want: int, timeout: float) -> dict:
        """The answer to one request, skipping anything else on the way.

        A server may write notifications and log lines of its own between the
        request and its answer, so the id is what is matched on rather than
        the next line being assumed to be the reply.
        """
        if self.proc is None or self.proc.stdout is None:
            raise McpError("the server is not running")
        loop = asyncio.get_running_loop()
        until = loop.time() + timeout
        while True:
            left = until - loop.time()
            if left <= 0:
                raise McpError("the server did not answer in time")
            try:
                line = await asyncio.wait_for(self.proc.stdout.readline(), left)
            except ValueError as exc:
                # One message longer than LINE_LIMIT. The reader's buffer is
                # in an unknown state after this, so the connection is done.
                raise McpError(f"the server sent a message too large to read: "
                               f"{exc}") from None
            if not line:
                raise McpError("the server closed its output")
            try:
                message = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                continue                      # a log line on the wrong pipe
            if isinstance(message, dict) and message.get("id") == want:
                return message

    async def request(self, method: str, params: dict, timeout: float) -> dict:
        async with self._lock:
            self._next += 1
            call_id = self._next
            await self._send({"jsonrpc": "2.0", "id": call_id,
                              "method": method, "params": params})
            return await self._read_answer(call_id, timeout)

    async def notify(self, method: str, params: dict) -> None:
        async with self._lock:
            await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def close(self) -> None:
        proc, self.proc = self.proc, None
        if proc is None:
            return
        # Only ever this process, by the handle taken when it was spawned.
        with_stdin = proc.stdin
        if with_stdin is not None and not with_stdin.is_closing():
            with_stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), 5)
            return
        except (asyncio.TimeoutError, ProcessLookupError):
            pass
        try:
            proc.kill()
        except ProcessLookupError:
            return
        # Waited for after the kill as well as before it. Without this the
        # process is signalled and never reaped, and its transport is then
        # collected after the event loop has gone: "Event loop is closed",
        # raised out of a destructor, which nothing can catch and nothing
        # explains.
        with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
            await asyncio.wait_for(proc.wait(), 5)


class Http(Transport):
    """A hosted server: one POST per message, answered as JSON or as events."""

    def __init__(self, server: Server):
        self.server = server
        self.client = None
        self.session = ""
        self._next = 0

    async def start(self) -> None:
        import httpx

        self.client = httpx.AsyncClient(timeout=CALL_TIMEOUT, follow_redirects=True)

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            # Both, because a streamable-HTTP server picks whichever it likes.
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": VERSION,
        }
        headers.update(self.server.headers)
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        return headers

    async def _post(self, body: dict, timeout: float):
        if self.client is None:
            raise McpError("the client was never started")
        answer = await self.client.post(self.server.url, json=body,
                                        headers=self._headers(), timeout=timeout)
        if answer.status_code >= 400:
            raise McpError(f"the server answered {answer.status_code}")
        got = answer.headers.get("mcp-session-id")
        if got:
            self.session = got
        return answer

    async def request(self, method: str, params: dict, timeout: float) -> dict:
        self._next += 1
        body = {"jsonrpc": "2.0", "id": self._next, "method": method, "params": params}
        answer = await self._post(body, timeout)
        kind = (answer.headers.get("content-type") or "").split(";")[0].strip()
        if kind == "text/event-stream":
            return _first_event(answer.text, self._next)
        try:
            return answer.json()
        except ValueError as exc:
            raise McpError(f"the server did not answer with JSON: {exc}") from None

    async def notify(self, method: str, params: dict) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, "params": params},
                         CALL_TIMEOUT)

    async def close(self) -> None:
        client, self.client = self.client, None
        if client is not None:
            await client.aclose()


def _first_event(text: str, want: int) -> dict:
    """The JSON-RPC answer out of a server-sent-event body."""
    for block in text.split("\n\n"):
        data = "".join(line[5:].strip() for line in block.splitlines()
                       if line.startswith("data:"))
        if not data:
            continue
        try:
            message = json.loads(data)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == want:
            return message
    raise McpError("the server's event stream carried no answer")


# ---------------------------------------------------------------------------
# One server, from hello to its tools
# ---------------------------------------------------------------------------


class Connection:
    """One MCP server: connected, asked what it can do, and callable."""

    def __init__(self, server: Server, transport: Transport | None = None):
        self.server = server
        self.transport = transport or (Stdio(server) if server.command else Http(server))
        self.tools: list[dict] = []
        self.info: dict = {}

    async def open(self, timeout: float = START_TIMEOUT) -> list[dict]:
        """Say hello, and come back with the tools this server offers.

        The definitions are already in the shape the Messages API takes, with
        the namespaced name on them, so the caller has nothing to translate.
        """
        await self.transport.start()
        hello = await self._ask("initialize", {
            "protocolVersion": VERSION,
            "capabilities": {},
            "clientInfo": {"name": "rouh", "version": "1"},
        }, timeout)
        self.info = hello.get("serverInfo") or {}
        await self.transport.notify("notifications/initialized", {})

        listed = await self._ask("tools/list", {}, timeout)
        self.tools = []
        for tool in listed.get("tools") or []:
            if not isinstance(tool, dict) or not tool.get("name"):
                continue
            self.tools.append({
                "name": tool_name(self.server.name, str(tool["name"])),
                "description": _described(self.server.name, tool),
                "input_schema": tool.get("inputSchema") or {"type": "object",
                                                            "properties": {}},
            })
        return self.tools

    async def call(self, name: str, args: dict, timeout: float = CALL_TIMEOUT) -> str:
        """Call one of this server's tools and return what it said, as text."""
        answer = await self._ask("tools/call",
                                 {"name": plain_name(name), "arguments": args or {}},
                                 timeout)
        said = _text_of(answer.get("content"))
        if answer.get("isError"):
            # Said as an answer rather than raised: the turn should be able to
            # tell the person what the server said, not that a tool exploded.
            return f"{self.server.name} could not do that: {said or 'it did not say why'}"
        if len(said) > MAX_RESULT:
            said = said[:MAX_RESULT] + (
                f"\n\n(cut here: {self.server.name} returned more than "
                f"{MAX_RESULT} characters)")
        return said or "It did that and said nothing."

    async def close(self) -> None:
        await self.transport.close()

    async def _ask(self, method: str, params: dict, timeout: float) -> dict:
        message = await self.transport.request(method, params, timeout)
        if not isinstance(message, dict):
            raise McpError(f"{self.server.name} answered something that is not a message")
        if message.get("error"):
            error = message["error"]
            said = error.get("message") if isinstance(error, dict) else str(error)
            raise McpError(f"{self.server.name} refused {method}: {said}")
        result = message.get("result")
        return result if isinstance(result, dict) else {}


def _described(server: str, tool: dict) -> str:
    """A tool's description, with where it came from said in it.

    Said out loud because the model has to know: this is somebody else's
    program, its answers are quoted material, and a tool called `search` from
    two different servers is two different things.
    """
    own = " ".join(str(tool.get("description") or "").split())[:800]
    lead = f"From the MCP server {server!r}."
    return f"{lead} {own}" if own else f"{lead} It gave no description."


def _text_of(content) -> str:
    """The text out of an MCP result's content blocks."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text") or ""))
        elif block.get("type") == "resource":
            resource = block.get("resource") or {}
            parts.append(str(resource.get("text") or resource.get("uri") or ""))
        else:
            parts.append(f"[{block.get('type') or 'something'} from the server]")
    return "\n".join(p for p in parts if p).strip()


async def connect_all(servers, *, timeout: float = START_TIMEOUT) -> list[Connection]:
    """Open every configured server, and leave out the ones that will not open.

    One that fails is logged and dropped. A machine with a broken server in its
    configuration is a machine with fewer tools, never one with no voice.
    """
    out: list[Connection] = []
    for server in servers:
        connection = Connection(server)
        try:
            tools = await asyncio.wait_for(connection.open(timeout), timeout + 5)
        except Exception as exc:
            log.warning("the MCP server %r would not start (%s: %s)",
                        server.name, type(exc).__name__, exc)
            try:
                await connection.close()
            except Exception:
                pass
            continue
        log.info("MCP server %r: %d tool%s", server.name, len(tools),
                 "" if len(tools) == 1 else "s")
        out.append(connection)
    return out
