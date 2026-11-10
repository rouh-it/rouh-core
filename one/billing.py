"""Which account pays for a run of Codex, and changing that only when a person says so.

A run of Codex is paid for one of two ways, and the person chooses per run:

* ``subscription`` - Codex's own ChatGPT login, in the run's user's
  ``~/.codex/auth.json``. What every run of Codex was until 27 September 2026,
  and still what a run is unless the person asks otherwise. Nothing about how
  such a run starts changed when the second way came in.
* ``api`` - the OpenAI API key, billed per token to the API account. Only ever
  because a person asked for it: when they started the run, or when they
  answered yes to carrying a run on after its subscription stopped it.

**One installation, one CODEX_HOME, and the key in one process.** Watched with
codex-cli 0.154.0 on this server on 27 September 2026, against a stand-in
Responses server: a model provider of the run's own, given on its command line
with ``env_key = "OPENAI_API_KEY"``, makes Codex send that key and nothing else
- not the ChatGPT token, not the account header - and without the variable it
refuses to start the turn at all ("Missing environment variable"), rather than
falling back to the subscription. It never reads or writes ``auth.json`` for
it, so a run on the key and a run on the subscription side by side cannot
overwrite each other's login. Sessions stay where every other session is, in
``~/.codex/sessions``, which is what lets one be resumed under the other.

**Where the key is and is not.** The program holds it in memory only
(:class:`Key`): from its own environment when the machine gives it one, or
handed over by Rouh, whose environment has it, on its own connection. For a
run it goes into a file of mode 600 in the run's own ``.one`` folder, written
through ``asuser.py write`` from stdin, and ``asuser.py agent`` reads that file,
deletes it, and puts the key in the environment of the Codex process it
becomes. It is never an argument, so never on a process list; never an entry
in the list, so never in a run's record or on a screen; and never logged. The
model's own shell commands get the variable set to nothing
(``shell_environment_policy.set``): Codex 0.154 hands its whole environment to
them otherwise, and its ``exclude`` and ``inherit`` settings were watched doing
nothing for ``exec_command``. What it cannot be kept from is the run's own
user: a process of that user can read ``/proc/<codex>/environ``, as it can read
``auth.json``. The two logins are only ever as separate as two files of one
user are.

**How a subscription that has run out is noticed.** Codex sends no hook when a
turn fails: no Stop, nothing. What it does is write the failure into its own
session file, as a ``task_complete`` with an ``error`` whose
``codex_error_info`` says why - ``usage_limit_exceeded`` for the limit,
``unauthorized`` for a login that no longer works. :class:`Watcher` reads that
file as Codex writes it, the same way the Read tab does.

**How a run is carried on.** Never mid-request: the turn has already ended
when the failure is written, and Codex is sitting at its prompt. The run is
paused with a question, and only a yes changes anything. Then Codex is asked
to leave, the way a run is always asked to leave, and started again as
``codex resume <session>`` with the run's own provider, in the same checkout:
watched carrying the whole conversation over. If the API will not take the
conversation - its reasoning was written under the subscription, and whether
the API accepts that could not be tried without spending real money - the
first turn fails too, and the person is asked whether to start a fresh session
on the key in the same checkout, told where the old conversation is. Nothing is
started over without that second yes.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:  # pragma: no cover
    from .documents import Documents

log = logging.getLogger("one.billing")

SUBSCRIPTION, API = "subscription", "api"
BILLINGS = (SUBSCRIPTION, API)
#: Who pays, in the words a person reads.
WORDS = {SUBSCRIPTION: "ChatGPT subscription", API: "OpenAI API key"}

#: The environment variable Codex reads the key from, and the one variable of
#: that name anything here ever sets.
KEY_VAR = "OPENAI_API_KEY"
#: The run's own provider. Not "openai": Codex refuses to let a built-in one be
#: redefined ("Built-in providers cannot be overridden").
PROVIDER = "one-openai-api"
#: The key's file in the run's own ``.one`` folder, for the second between the
#: program writing it and ``asuser.py agent`` reading and deleting it.
KEY_FILE = "codex-api-key"

#: Why Codex stopped a turn on the subscription, by ``codex_error_info``, as
#: the end of the sentence "the ChatGPT subscription ...". Only these two are
#: the subscription itself: a rate limit passes by itself, and anything else
#: would fail the same way on the key.
STOPS = {
    "usage_limit_exceeded": "reached its usage limit",
    "unauthorized": "is no longer logged in",
}

#: The kinds of question this module asks, and what their two buttons say.
#: A yes is the only thing that ever puts a run on the key.
ASK_API = "codex-billing"
ASK_FRESH = "codex-fresh"
CHOICES = {
    ASK_API: {"yes": "Continue on the API key", "no": "Not now"},
    ASK_FRESH: {"yes": "Start fresh on the API key", "no": "Leave it stopped"},
}

#: What a run carried over to the key is told, as the prompt it resumes with.
CONTINUED = (
    "This run was stopped because the ChatGPT subscription it was using {why}, and the "
    "person chose to carry it on, billed to the OpenAI API key. This is the same "
    "conversation, resumed, in the same checkout, with every file as you left it. Carry on "
    "with the task from where you stopped; `git status` shows where the work was.")

#: What a fresh session on the key is told when the conversation could not be
#: carried over. The old conversation is named so it can be read, never lost.
FRESH = (
    "You are taking over a run of Codex that was working in this checkout. It was stopped "
    "because the ChatGPT subscription it used {why}; the person chose to carry it on, billed "
    "to the OpenAI API key, and its conversation could not be carried over to the key "
    "({failure}). So this is a fresh conversation, in the same checkout, with every file as "
    "that run left it. Its whole conversation is in {transcript}, which you can read. Look at "
    "`git status` and `git log` to see what was already done, then finish the task.\n\n"
    "The task, as it was given:\n\n{brief}")


#: Where Rouh writes the mode of its Models page for this program (`rouh/modeldefaults.py`,
#: `publish_mode`), in the landing directory both can read.
MODE_FILE = "model-mode.json"
#: What a run told it is waiting for its subscription in Saver.
SAVER_WAITS = ("{title} is paused: the ChatGPT subscription it runs on {why}. Rouh is in Saver, "
               "which never moves a run to per-token billing, so it waits for the subscription to "
               "reset. Say carry on once it has.")


def saver(land_dir: str = "") -> bool:
    """Whether Rouh's Models page is on Saver (Petar, 23 October 2026: "If a subscription hits
    its limit, the run waits for it to reset or carries on with Luna. It never moves to
    per-token billing for the smart model"). False when it cannot be read."""
    base = land_dir or os.environ.get("ROUH_LAND_DIR") or "/srv/rouh-land"
    try:
        with open(os.path.join(base, MODE_FILE), encoding="utf-8") as fh:
            return str((json.load(fh) or {}).get("mode") or "") == "saver"
    except (OSError, ValueError, AttributeError):
        return False


def billing_of(engine: Any, value: Any) -> str:
    """Who pays for a run: the key only when it was asked for, and only for Codex."""
    if str(engine or "") == "codex" and str(value or "").strip().lower() == API:
        return API
    return SUBSCRIPTION


def asked_for(engine: Any, value: Any) -> str:
    """What a request said about billing, refused when it cannot be right.

    Nothing at all is the subscription. The key is for Codex alone: Claude
    Code has a subscription of its own and no key here.
    """
    said = str(value or "").strip().lower()
    if not said or said == SUBSCRIPTION:
        return SUBSCRIPTION
    if said != API:
        raise ValueError(f"billing is {SUBSCRIPTION} or {API}, not {value!r}")
    if str(engine or "") != "codex":
        raise ValueError("only a run of Codex can be billed to the OpenAI API key")
    return API


def _toml(text: str) -> str:
    return json.dumps(text)


def provider_overrides(base_url: str) -> list[str]:
    """The ``-c`` settings that put one run of Codex on the API key.

    All on the command line, and none of them secret: the key itself is only
    named, by the variable Codex reads it from.
    """
    table = ("{name=%s,base_url=%s,wire_api=\"responses\",env_key=%s}"
             % (_toml("OpenAI API key (billed per token)"), _toml(base_url), _toml(KEY_VAR)))
    return ["-c", f"model_providers.{PROVIDER}={table}",
            "-c", f"model_provider={_toml(PROVIDER)}",
            # The model's own commands see the variable empty: otherwise Codex
            # hands the key to every command it runs (see the module's note).
            "-c", "shell_environment_policy.set={%s=\"\"}" % KEY_VAR]


def turn_error(record: Any) -> dict[str, Any] | None:
    """A turn Codex ended with an error, out of one line of its session file.

    ``{"turn": id, "info": codex_error_info, "message": text}``, or None for
    anything else, including every turn that ended well.
    """
    if not isinstance(record, dict) or record.get("type") != "event_msg":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "task_complete":
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    return {"turn": str(payload.get("turn_id") or ""),
            "info": str(error.get("codex_error_info") or ""),
            "message": _message(error.get("message"))}


def model_refused(failed: dict[str, Any]) -> bool:
    """A provider's refusal of this model, rather than a quota or transient failure."""
    if failed.get("info") in ("model_not_found", "unsupported_model", "model_not_available"):
        return True
    message = str(failed.get("message") or "").lower()
    return "model" in message and any(word in message for word in (
        "not supported", "unsupported", "not available", "unavailable", "does not exist",
        "not found", "do not have access", "don't have access", "not allowed"))


def _message(raw: Any) -> str:
    """The error in words. The API's own errors arrive as a JSON body, whole."""
    text = str(raw or "").strip()
    if text.startswith("{"):
        with contextlib.suppress(ValueError, AttributeError, TypeError):
            inner = json.loads(text).get("error") or {}
            text = str(inner.get("message") or text)
    return text


class Key:
    """The OpenAI API key, held in memory and handed to nobody but a run.

    The program's own environment first, when the machine gives it one; then
    whatever Rouh handed over on its own connection, because Rouh's
    environment is where the key is on this server. Never written to the list,
    never logged, never sent back to anybody who asks.
    """

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ
        self._given = ""

    def give(self, key: str) -> None:
        self._given = str(key or "").strip()

    def get(self) -> str:
        return str(self._environ.get(KEY_VAR) or "").strip() or self._given

    def available(self) -> bool:
        return bool(self.get())


#: How long to wait before reading again after the reader stopped by itself.
AGAIN_AFTER = (1.0, 3.0, 10.0, 30.0)


class Watcher:
    """One run of Codex's session file, read as Codex writes it, for turns that failed.

    Only ``task_complete`` and ``turn_context`` lines are parsed: the file holds
    the whole conversation, and a run that reads a big file writes a big line.
    Every failed turn is handed to ``on_error``, the ones from before this
    watcher started too; which of them are new is the caller's to know, by
    their turn ids.
    """

    def __init__(self, docs: "Documents", run_id: str, path: str, user: str,
                 on_error: Callable[[str, dict[str, Any]], Awaitable[None]],
                 on_model: Callable[[str, str], Awaitable[None]] | None = None) -> None:
        self.docs = docs
        self.run_id = run_id
        self.path = path
        self.user = user
        self.on_error = on_error
        self.on_model = on_model
        self._offset = 0
        self._stopping = False
        self._proc: asyncio.subprocess.Process | None = None
        self.task = asyncio.create_task(self._run(), name=f"codex-billing-{run_id}")

    async def _run(self) -> None:
        attempt = 0
        while not self._stopping:
            started = asyncio.get_running_loop().time()
            refused = False
            with contextlib.suppress(asyncio.CancelledError):
                refused = await self._read()
            if self._stopping or refused:
                return
            if asyncio.get_running_loop().time() - started > 60:
                attempt = 0
            await asyncio.sleep(AGAIN_AFTER[min(attempt, len(AGAIN_AFTER) - 1)])
            attempt += 1

    async def _read(self) -> bool:
        """Read until the reader stops. True when it refused the path for good."""
        argv = self.docs.asuser_argv("transcript", "--path", self.path, "--from",
                                     str(self._offset), "--follow", user=self.user)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError as exc:
            log.warning("could not watch the session of %s: %s", self.run_id, exc)
            return False
        self._proc = proc
        buffer = bytearray()
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(1 << 16)
                if not chunk:
                    return False
                buffer += chunk
                while True:
                    cut = buffer.find(b"\n")
                    if cut < 0:
                        break
                    line = bytes(buffer[:cut])
                    del buffer[:cut + 1]
                    if line.startswith(b"#"):
                        word, _, rest = line[1:].decode("utf-8", "replace").partition(" ")
                        if word == "at":
                            with contextlib.suppress(ValueError):
                                self._offset = int(rest)
                        elif word == "reset":
                            self._offset = 0
                        elif word == "refused":
                            log.warning("the session of %s cannot be watched: %s",
                                        self.run_id, rest)
                            return True
                        continue
                    if b'"task_complete"' not in line and b'"turn_context"' not in line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(record, dict) and record.get("type") == "turn_context" and self.on_model:
                        payload = record.get("payload")
                        model = payload.get("model") if isinstance(payload, dict) else None
                        if isinstance(model, str) and model:
                            try:
                                await self.on_model(self.run_id, model)
                            except Exception:
                                log.exception("the model of %s was not recorded", self.run_id)
                    found = turn_error(record)
                    if found is not None:
                        try:
                            await self.on_error(self.run_id, found)
                        except Exception:
                            log.exception("a failed turn of %s was not handled", self.run_id)
        finally:
            self._proc = None
            with contextlib.suppress(ProcessLookupError, OSError):
                if proc.stdin:
                    proc.stdin.close()
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                    await asyncio.wait_for(proc.wait(), 5)

    async def stop(self) -> None:
        self._stopping = True
        proc = self._proc
        if proc is not None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.task
