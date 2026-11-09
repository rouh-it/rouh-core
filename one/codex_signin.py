"""Codex's sign-in with a ChatGPT plan, done for Rouh's page rather than in a terminal.

Petar, 6 November 2026: "That logging needs to be ironed out and SIMPLE because people will
have to be able to login." The nightly refactoring run was refused every night because Codex
had never been signed in in the worker container. Rouh's page has a "Sign in Codex with
ChatGPT" button (``rouh/web/codex_signin.py``, ``/setup/codex``, and Settings, Models); the
page asks Rouh's core, the core asks this program on its own connection (``codex_signin``,
which only the voice, Rouh's connection, may send), and this program, which runs as the
worker's user, does the signing in with Codex's own commands:

* ``codex login --device-auth`` (codex-cli 0.163) prints an address,
  ``https://auth.openai.com/codex/device``, and a one-time code such as ``3KAB-E66R3`` that
  expires in 15 minutes, then waits until the person has typed the code in on OpenAI's page
  and approved it. :meth:`CodexSignIn.start` runs it and hands both back; a task of its own
  waits for it to end, at most :data:`WAITS` seconds, and kills it after that, so it never
  hangs on. Codex writes the sign-in to ``auth.json`` in its folder (``codexhome.py``) and
  renews it itself.
* ``codex login status`` says whether it is signed in, and how: "Logged in using ChatGPT",
  "Logged in using an API key - ...", or "Not logged in". It names no account, so whose
  account and which plan are read from the two claims Codex itself shows in its ``/status``,
  ``email`` and ``chatgpt_plan_type``, in the id token in ``auth.json``. Nothing else of that
  file is read, and nothing of it is ever logged, answered back or written anywhere.
* ``codex exec`` with one trivial prompt, read-only and in an empty folder, right after a
  sign-in, proves a real run gets past the sign-in (:meth:`CodexSignIn.test`).
* ``codex logout`` signs it out.

**The OpenAI key instead.** A person with no ChatGPT plan can have every run of Codex billed
per use to the OpenAI API key (``billing.py``). That is their choice, kept in
``rouh-billing.json`` beside ``auth.json`` and off until they turn it on; nothing turns it on
for them. While it is on, a run of Codex asked for with no billing is billed to the key
(``protocol._do_start``).

**When the sign-in is lost.** A run refused because Codex is not signed in, or one whose
turn Codex ended as ``unauthorized``, says one line, :data:`NEEDS`, with the page's address,
and the phone is told once (:meth:`CodexSignIn.tell_lost`) until Codex is signed in again:
no question for each run.

Only where the machine says so (``ONE_CLAUDE_SIGNIN=1``, which the workers' image sets, and
which turns on both agents' sign-ins): on the server Codex is signed in by the person who
runs it, and this program never touches it there.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import signal
import tempfile
import time
from typing import TYPE_CHECKING, Any, Callable

from . import codexhome, subscriptions

if TYPE_CHECKING:  # pragma: no cover
    from .config import Settings

log = logging.getLogger("one.codex_signin")

#: The one line every refusal for a lost sign-in says, followed by where the button is.
NEEDS = "Codex needs signing in again"

#: How long a device sign-in may wait for its approval: Codex says its code expires in 15
#: minutes, and it is killed a little after that if it has not ended by itself.
WAITS = 15 * 60 + 30
#: How long the trial call after a sign-in may take.
TEST_TIMEOUT = 150
#: What the trial call asks, and the word it is to answer with.
TEST_PROMPT = "This is a sign-in check. Do not run any command or change any file. Reply with exactly: Codex works"

#: The address and the code in Codex's own output, once its colours are taken off.
ADDRESS = re.compile(r"https://\S*/codex/device\S*|https://auth\.openai\.com/\S+")
CODE = re.compile(r"\b([A-Z0-9]{4,5}-[A-Z0-9]{4,6})\b")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")

#: The person's choice of billing every run of Codex to the OpenAI key, beside auth.json.
CHOICE_FILE = "rouh-billing.json"
#: Kept while the phone has been told that the sign-in was lost, so it is told once.
TOLD_FILE = "rouh-signin-told"


class Refused(ValueError):
    """Said back to Rouh in one sentence."""


def enabled() -> bool:
    return os.environ.get("ONE_CLAUDE_SIGNIN", "").strip() == "1"


def plain(text: str) -> str:
    return ANSI.sub("", text or "").replace("\r", "")


def page_address(public_url: str) -> str:
    """Where the button is, from this program's own address (Rouh's, with ``/one`` after it)."""
    base = (public_url or "").rstrip("/")
    if base.endswith("/one"):
        base = base[: -len("/one")]
    return f"{base}/setup/codex" if base else "/setup/codex"


def needs_line(public_url: str) -> str:
    return f"{NEEDS}: {page_address(public_url)}"


def prefers_api_key() -> bool:
    """Whether the person chose to bill every run of Codex to the OpenAI key."""
    try:
        with open(os.path.join(codexhome.folder(), CHOICE_FILE), encoding="utf-8") as fh:
            return bool(json.load(fh).get("api_key"))
    except (OSError, ValueError, AttributeError):
        return False


def _claims(auth_path: str) -> dict[str, str]:
    """Whose account and which plan, from the id token's claims; nothing else, and never the token."""
    try:
        with open(auth_path, encoding="utf-8") as fh:
            tokens = (json.load(fh) or {}).get("tokens") or {}
            token = str(tokens.get("id_token") or "")
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (OSError, ValueError, IndexError, AttributeError, TypeError):
        return {}
    if not isinstance(claims, dict):
        return {}
    auth = claims.get("https://api.openai.com/auth") or {}
    out = {}
    if isinstance(claims.get("email"), str):
        out["email"] = claims["email"][:200]
    plan = auth.get("chatgpt_plan_type") if isinstance(auth, dict) else None
    if isinstance(plan, str) and plan:
        out["plan"] = plan[:40]
    for source, target in (("chatgpt_account_id", "account_id"), ("chatgpt_workspace_name", "workspace_name")):
        value = auth.get(source) if isinstance(auth, dict) else None
        if isinstance(value, str):
            out[target] = value[:200]
    if not out.get("account_id") and isinstance(tokens.get("account_id"), str):
        out["account_id"] = tokens["account_id"][:200]
    out["workspace"] = subscriptions.workspace(out.get("plan", ""))
    return out


def _env() -> dict[str, str]:
    """Codex's own environment, minus the API key's stand-in: a sign-in and its check are the plan's."""
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "CODEX_API_KEY")}
    env.update(NO_COLOR="1", TERM="dumb", BROWSER="/bin/false")
    return env


def _first_error(said: str) -> str:
    """Codex's own reason, in its own words: its error line, else its last line."""
    lines = [ln.strip() for ln in plain(said).splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith("WARNING: proceeding")]
    for ln in lines:
        low = ln.lower()
        if low.startswith(("error", "login failed")) or "failed" in low or "expired" in low:
            return ln[:400]
    return (lines[-1] if lines else "Codex ended without saying why")[:400]


async def _run(*args: str, timeout: float, cwd: str | None = None) -> dict[str, Any]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=_env(), cwd=cwd, start_new_session=True)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        _kill(proc)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 5)
        return {"code": -1, "stdout": "", "stderr": f"took longer than {int(timeout)} seconds"}
    return {"code": proc.returncode, "stdout": out.decode("utf-8", "replace"),
            "stderr": err.decode("utf-8", "replace")}


def _kill(proc: asyncio.subprocess.Process) -> None:
    """The whole group: Codex is a node launcher with the real binary under it."""
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
        os.killpg(proc.pid, signal.SIGKILL)
    with contextlib.suppress(ProcessLookupError):
        proc.kill()


class CodexSignIn:
    """At most one device sign-in at a time, and what the last one and its check said."""

    def __init__(self, settings: "Settings | None" = None,
                 tell: Callable[[str], None] | None = None) -> None:
        self.s = settings
        self._tell = tell
        self._proc: asyncio.subprocess.Process | None = None
        self._waiter: asyncio.Task | None = None
        self._tester: asyncio.Task | None = None
        self._waiting: dict[str, Any] = {}
        self._last: dict[str, Any] = {}
        self._test: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._workspace_supported: bool | None = None

    # -- what the page asks for -----------------------------------------------------

    async def handle(self, do: str, message: dict[str, Any]) -> dict[str, Any]:
        if not enabled():
            raise Refused("this program does not look after Codex's sign-in on this machine")
        async with self._lock:
            if do == "status":
                return await self.status()
            if do == "start":
                return await self.start(message)
            if do == "limits":
                return await subscriptions.capacity("codex", lambda: subscriptions.codex_limits(self.binary(), _env()))
            if do == "cancel":
                await self._drop()
                return await self.status()
            if do == "logout":
                return await self.logout()
            if do == "test":
                self._start_test()
                return await self.status()
            if do == "api_key":
                return await self.choose_api_key(bool(message.get("on")))
        raise Refused(f"there is no Codex sign-in step called {do!r}")

    def binary(self) -> str:
        return (getattr(self.s, "codex", "") if self.s is not None else "") or "codex"

    def installed(self) -> bool:
        b = self.binary()
        return os.access(b, os.X_OK) if os.sep in b else any(
            os.access(os.path.join(d, b), os.X_OK) for d in os.environ.get("PATH", "").split(os.pathsep) if d)

    async def status(self) -> dict[str, Any]:
        """Whether Codex is installed and signed in, how, as whom and on which plan."""
        out: dict[str, Any] = {"installed": self.installed(), "waiting": self.is_waiting(),
                               "api_key_chosen": prefers_api_key(), "page": self.page()}
        chosen = subscriptions.choice()
        out["workspace_choice"] = chosen.get("kind", "personal")
        if self.is_waiting():
            out.update(self._waiting)
        if self._last:
            out["last"] = dict(self._last)
        if self._test:
            out["test"] = dict(self._test)
        if not out["installed"]:
            return out
        said = await _run(self.binary(), "login", "status", timeout=30)
        words = plain(said["stdout"] + "\n" + said["stderr"])
        found = re.search(r"Logged in using ([^\n-]+)", words)
        out["signed_in"] = bool(found) and "Not logged in" not in words
        if found:
            how = found.group(1).strip().lower()
            out["method"] = "chatgpt" if how.startswith("chatgpt") else (
                "api_key" if "api key" in how else how[:40])
        if self._workspace_supported is None:
            version = await _run(self.binary(), "--version", timeout=5)
            found_version = re.search(r"(\d+)\.(\d+)\.(\d+)", version["stdout"])
            self._workspace_supported = bool(found_version and tuple(map(int, found_version.groups())) >= (0, 163, 0))
        out["workspace_supported"] = self._workspace_supported
        auth = codexhome.auth_file()
        if out["signed_in"] and out.get("method") == "chatgpt":
            out.update(_claims(auth))
            chosen = subscriptions.choice()
            out["workspace_choice"] = chosen.get("kind", "personal")
            out["workspace_locked"] = bool(chosen.get("locked") and out.get("account_id")
                                           and subscriptions.held_workspace() == out["account_id"])
            out["workspace_mismatch"] = bool(chosen.get("kind") in ("personal", "team") and
                out.get("workspace", "").lower() != chosen["kind"])
            if chosen.get("account_id") and chosen["account_id"] != out.get("account_id"):
                out["workspace_mismatch"] = True
                out["workspace_expected_id"] = chosen["account_id"]
            self._keep_private(auth)
            self._forget_told()
        elif not out["signed_in"] and "Not logged in" not in words and said["code"] not in (0, 1):
            out["why"] = _first_error(words)
        return out

    def page(self) -> str:
        return page_address(getattr(self.s, "public_url", "") if self.s is not None else "")

    def is_waiting(self) -> bool:
        return self._proc is not None and self._proc.returncode is None and bool(self._waiting)

    async def start(self, message: dict | None = None) -> dict[str, Any]:
        """Starts ``codex login --device-auth`` and hands back its address and code."""
        await self._drop()
        if not self.installed():
            raise Refused("Codex is not installed in the worker")
        os.makedirs(codexhome.folder(), mode=0o700, exist_ok=True)
        if message and "workspace" in message:
            kind = str(message.get("workspace") or "personal")
            if kind not in ("personal", "team", "any"):
                raise Refused("choose Personal, Team or Any workspace")
            account = str(message.get("account_id") or "").strip()
            if account:
                from uuid import UUID
                try:
                    account = str(UUID(account))
                except ValueError:
                    raise Refused("the workspace id must be a UUID")
            # A restriction for the old account must not prevent an intentional account change.
            if self._workspace_supported is None:
                await self.status()
            if account and not self._workspace_supported:
                raise Refused("this Codex version cannot hold a workspace; choose it on OpenAI’s page")
            if self._workspace_supported:
                subscriptions.pin(account)
            subscriptions.keep_choice({"kind": kind, "account_id": account, "locked": bool(account)})
        self._last, self._test = {}, {}
        proc = await asyncio.create_subprocess_exec(
            self.binary(), "login", "--device-auth",
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=_env(), start_new_session=True)
        self._proc = proc
        seen = ""
        address = code = ""
        try:
            async with asyncio.timeout(45):
                while not (address and code):
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    seen += plain(chunk.decode("utf-8", "replace"))
                    a, c = ADDRESS.search(seen), CODE.search(seen)
                    address, code = (a.group(0) if a else ""), (c.group(1) if c else "")
        except TimeoutError:
            pass
        if not (address and code):
            rest = b""
            with contextlib.suppress(Exception):
                rest = await asyncio.wait_for(proc.stdout.read(), 2)
            await self._drop()
            said = _first_error(seen + plain(rest.decode("utf-8", "replace")))
            self._last = {"ok": False, "said": said, "at": time.time()}
            raise Refused(f"Codex did not give a sign-in code. It said: {said}")
        self._waiting = {"address": address, "code": code, "started": time.time(),
                         "expires": time.time() + 15 * 60}
        self._waiter = asyncio.ensure_future(self._wait(proc, seen))
        log.info("codex sign-in started")
        return await self.status()

    async def _wait(self, proc: asyncio.subprocess.Process, seen: str) -> None:
        """Until Codex says the sign-in finished or failed, or its code has expired."""
        said = seen
        seen_address = str(self._waiting.get("address") or "")
        try:
            async with asyncio.timeout(WAITS):
                while True:
                    chunk = await proc.stdout.read(4096)
                    if not chunk:
                        break
                    said = (said + plain(chunk.decode("utf-8", "replace")))[-8000:]
                await proc.wait()
        except TimeoutError:
            _kill(proc)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)
            if self._proc is proc:
                self._waiting = {}
                self._proc = None
                self._last = {"ok": False, "at": time.time(),
                              "said": "The code expired before it was approved on OpenAI's page."}
            return
        except asyncio.CancelledError:
            _kill(proc)
            raise
        if self._proc is not proc:
            return
        self._proc, self._waiting = None, {}
        if proc.returncode == 0:
            self._last = {"ok": True, "at": time.time(), "address": seen_address}
            self._keep_private(codexhome.auth_file())
            self._forget_told()
            log.info("codex sign-in finished")
            chosen = subscriptions.choice()
            claims = _claims(codexhome.auth_file())
            matches = chosen.get("kind") == "any" or claims.get("workspace", "").lower() == chosen.get("kind")
            matches = matches and (not chosen.get("account_id") or chosen["account_id"] == claims.get("account_id"))
            if chosen and matches and claims.get("account_id") and self._workspace_supported:
                try:
                    subscriptions.pin(claims["account_id"])
                    chosen["locked"] = True
                    subscriptions.keep_choice(chosen)
                except (ValueError, OSError):
                    pass
            # The setup's existing probe stays; Connections only needs metadata and limits.
            if not chosen:
                self._start_test()
        else:
            self._last = {"ok": False, "at": time.time(), "said": _first_error(said)}
            log.info("codex sign-in ended with exit code %s", proc.returncode)

    def _start_test(self) -> None:
        if self._tester is not None and not self._tester.done():
            return
        self._test = {"running": True, "at": time.time()}
        self._tester = asyncio.ensure_future(self.test())

    async def test(self) -> dict[str, Any]:
        """One trivial prompt through ``codex exec``, read-only, in an empty folder, on the plan."""
        with tempfile.TemporaryDirectory(prefix="codex-check-") as where:
            args = [self.binary(), "exec", "--skip-git-repo-check", "--ephemeral",
                    "--sandbox", "read-only", "--color", "never", "-C", where]
            model = getattr(self.s, "codex_model", "") if self.s is not None else ""
            if model:
                args += ["-m", model]
            said = await _run(*args, TEST_PROMPT, timeout=TEST_TIMEOUT, cwd=where)
        answer = [ln.strip() for ln in plain(said["stdout"]).splitlines() if ln.strip()]
        ok = said["code"] == 0 and bool(answer)
        self._test = {"ok": ok, "at": time.time(),
                      "said": (answer[-1] if ok else _first_error(said["stderr"] + "\n" + said["stdout"]))[:300]}
        log.info("codex sign-in check %s", "passed" if ok else "failed")
        return dict(self._test)

    async def logout(self) -> dict[str, Any]:
        await self._drop()
        said = await _run(self.binary(), "logout", timeout=30)
        self._last, self._test = {}, {}
        if said["code"] not in (0, None):
            words = plain(said["stdout"] + said["stderr"])
            if "Not logged in" not in words:
                raise Refused(f"Codex did not sign out: {_first_error(words)}")
        log.info("codex signed out")
        return await self.status()

    async def choose_api_key(self, on: bool) -> dict[str, Any]:
        path = os.path.join(codexhome.folder(), CHOICE_FILE)
        if on:
            os.makedirs(codexhome.folder(), mode=0o700, exist_ok=True)
            tmp = path + ".new"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"api_key": True, "since": time.time()}, fh)
            os.replace(tmp, path)
        else:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(path)
        log.info("codex runs are billed to %s", "the OpenAI key" if on else "the ChatGPT plan")
        return await self.status()

    # -- a lost sign-in, said once ------------------------------------------------------

    def tell_lost(self) -> None:
        """The phone hears once that Codex needs signing in again, until it is signed in."""
        told = os.path.join(codexhome.folder(), TOLD_FILE)
        if os.path.exists(told) or self._tell is None:
            return
        with contextlib.suppress(OSError):
            os.makedirs(codexhome.folder(), mode=0o700, exist_ok=True)
            with open(told, "w", encoding="utf-8") as fh:
                fh.write(str(time.time()))
        self._tell(needs_line(getattr(self.s, "public_url", "") if self.s is not None else ""))

    def _forget_told(self) -> None:
        with contextlib.suppress(OSError):
            os.unlink(os.path.join(codexhome.folder(), TOLD_FILE))

    # -- the file, and the process ------------------------------------------------------

    @staticmethod
    def _keep_private(path: str) -> None:
        """auth.json for its own user only, and its folder too."""
        with contextlib.suppress(OSError):
            if os.stat(path).st_mode & 0o077:
                os.chmod(path, 0o600)
        with contextlib.suppress(OSError):
            folder = os.path.dirname(path)
            if os.stat(folder).st_mode & 0o077:
                os.chmod(folder, 0o700)

    async def _drop(self) -> None:
        proc, waiter = self._proc, self._waiter
        self._proc, self._waiter, self._waiting = None, None, {}
        if waiter is not None and not waiter.done():
            waiter.cancel()
        if proc is not None:
            _kill(proc)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)

    async def close(self) -> None:
        await self._drop()
        if self._tester is not None and not self._tester.done():
            self._tester.cancel()
