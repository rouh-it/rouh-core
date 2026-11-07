"""Claude Code's sign-in, done for Rouh's page rather than in a terminal.

In the containers (`deploy/container/`) the person never opens a terminal:
Rouh's page has a "Sign in with Claude" button and a box for the code Claude
gives back (`rouh/web/claude_signin.py`). The page asks Rouh's core, the core
asks this program on its own connection (``claude_signin``, which only the
voice, Rouh's connection, may send), and this program, which runs as the
worker's user, does the signing in with Claude Code's own documented commands:

* ``claude auth login --claudeai`` prints the address of Claude's sign-in page
  and then waits at "Paste code here if prompted" for the code Claude shows
  when the browser cannot come back to it, which in a container it never can.
  :meth:`SignIn.start` runs it and hands back the address; :meth:`SignIn.code`
  types the code into it and waits for it to finish. Claude Code keeps the
  sign-in in ``~/.claude/.credentials.json`` and renews it itself.
* ``claude auth status`` says whether it is signed in, and how.

The other way is the installation's Anthropic API key, which the worker never
holds: the core keeps it in the keys volume and the key proxy adds it to every
request on ``/anthropic``. :meth:`SignIn.use_api_key` points Claude Code there
in its user settings (``~/.claude/settings.json``): ``ANTHROPIC_BASE_URL`` is
the proxy's ``/anthropic`` and ``apiKeyHelper`` prints a stand-in, which the
proxy takes off. An ``apiKeyHelper`` comes before a subscription in Claude
Code's order of credentials, so signing in with Claude takes both out again.

Only where the machine says so (``ONE_CLAUDE_SIGNIN=1``, which the workers'
image sets): on the server Claude Code is signed in by the person who runs it,
and this program never touches it there.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

log = logging.getLogger("one.claude_signin")

#: The address Claude Code prints, on the line "If the browser didn't open, visit: ...".
SIGN_IN_ADDRESS = re.compile(r"https://\S+/oauth/authorize\?\S+")

#: The stand-in the apiKeyHelper prints. It is not a key: the proxy takes it off.
STAND_IN = "via-keyproxy"

#: How long a sign-in that was started waits for its code before it is dropped.
WAITS_FOR_CODE = 15 * 60


class Refused(ValueError):
    """Said back to Rouh in one sentence."""


def enabled() -> bool:
    return os.environ.get("ONE_CLAUDE_SIGNIN", "").strip() == "1"


def claude_binary() -> str:
    return os.environ.get("ONE_CLAUDE") or str(Path.home() / ".local/bin/claude")


def settings_file() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def proxy_url() -> str:
    base = os.environ.get("ROUH_MODEL_PROXY", "").strip().rstrip("/")
    return f"{base}/anthropic" if base else ""


class SignIn:
    """At most one sign-in at a time, held between the page's two presses."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._address = ""
        self._expiry: asyncio.TimerHandle | None = None
        self._lock = asyncio.Lock()

    # -- what the page asks for -----------------------------------------------------

    async def handle(self, do: str, message: dict[str, Any]) -> dict[str, Any]:
        if not enabled():
            raise Refused("this program does not look after Claude Code's sign-in on this machine")
        async with self._lock:
            if do == "status":
                return await self.status()
            if do == "start":
                return await self.start()
            if do == "code":
                return await self.code(str(message.get("code") or ""))
            if do == "cancel":
                await self._drop()
                return await self.status()
            if do == "api_key":
                return await self.use_api_key(bool(message.get("on", True)))
        raise Refused(f"there is no sign-in step called {do!r}")

    async def status(self) -> dict[str, Any]:
        """Whether Claude Code is installed and signed in, and how, in Claude Code's own words."""
        binary = claude_binary()
        out: dict[str, Any] = {"installed": os.access(binary, os.X_OK), "waiting_for_code": self._waiting(),
                               "proxy": bool(proxy_url())}
        if self._waiting():
            out["address"] = self._address
        if not out["installed"]:
            return out
        said = await _run(binary, "auth", "status", "--json", timeout=30)
        with contextlib.suppress(ValueError, TypeError):
            got = json.loads(said["stdout"])
            out["signed_in"] = bool(got.get("loggedIn"))
            out["method"] = str(got.get("authMethod") or "")
            for field in ("email", "orgName", "subscriptionType"):
                if got.get(field):
                    out[field] = str(got[field])
        out["api_key_through_proxy"] = self._api_mode()
        return out

    async def start(self) -> dict[str, Any]:
        """Starts ``claude auth login`` and hands back the address it prints."""
        await self._drop()
        binary = claude_binary()
        if not os.access(binary, os.X_OK):
            raise Refused("Claude Code is not installed in the worker yet; it installs itself on the worker's first start")
        self._proc = await asyncio.create_subprocess_exec(
            binary, "auth", "login", "--claudeai",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "BROWSER": "/bin/false"}, start_new_session=True)
        seen = b""
        try:
            async with asyncio.timeout(45):
                while not SIGN_IN_ADDRESS.search(seen.decode("utf-8", "replace")):
                    chunk = await self._proc.stdout.read(4096)
                    if not chunk:
                        break
                    seen += chunk
        except TimeoutError:
            pass
        found = SIGN_IN_ADDRESS.search(seen.decode("utf-8", "replace"))
        if not found:
            await self._drop()
            raise Refused("Claude Code did not give a sign-in address; the worker may not reach the internet yet")
        self._address = found.group(0)
        self._expiry = asyncio.get_running_loop().call_later(
            WAITS_FOR_CODE, lambda: asyncio.ensure_future(self._drop()))
        log.info("claude sign-in started")
        return {"address": self._address}

    async def code(self, code: str) -> dict[str, Any]:
        """Types the code Claude showed into the waiting sign-in and waits for it to finish."""
        code = code.strip()
        if not code or len(code) > 1000 or any(c.isspace() for c in code):
            raise Refused("paste the whole code Claude shows, in one piece")
        proc = self._proc
        if not self._waiting() or proc is None or proc.stdin is None:
            raise Refused("that sign-in is no longer waiting; press Sign in with Claude again")
        proc.stdin.write(code.encode() + b"\n")
        with contextlib.suppress(OSError):
            await proc.stdin.drain()
        try:
            async with asyncio.timeout(90):
                rest = await proc.stdout.read()
                await proc.wait()
        except TimeoutError:
            await self._drop()
            raise Refused("Claude did not answer in time; press Sign in with Claude again")
        self._forget()
        if proc.returncode != 0:
            said = rest.decode("utf-8", "replace")
            log.info("claude sign-in refused: %s", _first_failure(said))
            raise Refused("Claude did not accept that code. Press Sign in with Claude again, "
                          "and paste the new code Claude shows")
        log.info("claude sign-in finished")
        # A subscription comes after an apiKeyHelper in Claude Code's order,
        # so the API key way is taken out, or the sign-in would do nothing.
        self._set_api_mode(False)
        return await self.status()

    async def use_api_key(self, on: bool) -> dict[str, Any]:
        if on and not proxy_url():
            raise Refused("the worker has no key proxy to send Claude Code through (ROUH_MODEL_PROXY)")
        self._set_api_mode(on)
        return await self.status()

    # -- the settings file -------------------------------------------------------------

    def _api_mode(self) -> bool:
        s = _read_json(settings_file())
        return bool(s.get("apiKeyHelper")) and (s.get("env") or {}).get("ANTHROPIC_BASE_URL") == proxy_url()

    def _set_api_mode(self, on: bool) -> None:
        path = settings_file()
        s = _read_json(path)
        env = dict(s.get("env") or {})
        if on:
            s["apiKeyHelper"] = f"echo {STAND_IN}"
            env["ANTHROPIC_BASE_URL"] = proxy_url()
        else:
            if s.get("apiKeyHelper") == f"echo {STAND_IN}":
                s.pop("apiKeyHelper")
            if env.get("ANTHROPIC_BASE_URL") == proxy_url():
                env.pop("ANTHROPIC_BASE_URL")
        if env:
            s["env"] = env
        else:
            s.pop("env", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.new")
        tmp.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    # -- the waiting process -----------------------------------------------------------

    def _waiting(self) -> bool:
        return self._proc is not None and self._proc.returncode is None and bool(self._address)

    def _forget(self) -> None:
        if self._expiry is not None:
            self._expiry.cancel()
        self._proc, self._address, self._expiry = None, "", None

    async def _drop(self) -> None:
        proc = self._proc
        self._forget()
        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)


def _first_failure(said: str) -> str:
    for line in said.splitlines():
        line = line.strip()
        if line.lower().startswith(("login failed", "error")):
            return line[:200]
    return "it gave no reason"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


async def _run(*args: str, timeout: float) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(*args, stdin=asyncio.subprocess.DEVNULL,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        return {"code": -1, "stdout": "", "stderr": "took too long"}
    return {"code": proc.returncode, "stdout": out.decode("utf-8", "replace"), "stderr": err.decode("utf-8", "replace")}
