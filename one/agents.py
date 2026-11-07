"""Runs of Claude Code or of Codex: the brief, the hooks, and turning each hook into entries.

Everything here is plain functions, so a check of your own can drive a run's
whole life with nothing but dictionaries. ``runs.py`` does the waiting and the starting.

The hooks were watched working on the server on 14 September 2026 against
Claude Code 2.1.263, with a throwaway listener in place of the program:

* ``PreToolUse`` answered ``deny`` with a reason: the command did not run, and
  Claude said the reason back.
* ``PreToolUse`` answered ``allow``: the command ran with no prompt, although
  the run was in the mode that asks before everything.
* ``Stop`` answered ``{"decision": "block", "reason": ...}``: Claude carried on
  and did what the reason said, and the next ``Stop`` carried
  ``stop_hook_active: true``.
* ``SessionStart`` did not arrive in a run started with ``-p``. Every other
  hook carries ``session_id`` and ``transcript_path``, so the session is taken
  from whichever hook comes first.
* ``Stop`` carries the run's closing words in ``last_assistant_message``.
"""
from __future__ import annotations

import json
import os
import shlex
from typing import Any, Mapping

from rouh import attachments, browser_handoff

from . import billing as _billing
from .briefs import (
    BROWSER_RULE,
    CARRIED_ON,
    CODEX_RULE,
    CODE_BRIEF,
    CODE_ELSEWHERE,
    CODE_HERE,
    FILES_RULE,
    FINISHED_IN_WORKSPACE,
    FINISHED_ON_BRANCH,
    FINISHED_TO_MAIN,
    FINISHED_TO_WORKSPACE,
    FINISHING,
    FINISH_THE_WORK,
    FOLDER_BRIEF,
    MAIL_RULE,
    PUSH_AND_DEPLOY,
    RESTARTED,
    ROUH_NOTE,
    RULES,
    SAVED_ON_BRANCH,
    SAVED_TO_MAIN,
    SCRATCH_BRIEF,
    SESSION_BRIEF,
    SESSION_CODE,
    SESSION_FOLDER,
    SESSION_SCRATCH,
    SIGNUPS_RULE,
    STILL_RUNNING,
    WORKSPACE_BRIEF,
    WORKSPACE_IN_THE_CHECKOUT,
    WORKSPACE_IS_THE_CHECKOUT,
    _code_parts,
    _rules_for,
    compose_brief,
    finish_the_work,
    first_prompt,
    session_brief,
    workspace_layout,
)
# Keep the existing import paths for callers that start runs through agents.
from .engines import (CODEX_HOOKS, DEFAULT_API_BASE_URL, DEFAULT_ENGINE, ENGINES,
                      ENGINE_WORDS, _toml_string, claude_args, codex_args,
                      codex_hook_overrides, engine_of)
from .hookbodies import (INPUT_FIELDS, INPUT_TEXT, _STEP, _effort, closed_body, plain,
                         simple_entry, small_input, step_of, tool_body)
from .keys import _ESCAPE, _KEYS, typed_text

#: Every hook a run is given, the name it arrives under, and how long Claude
#: Code waits for the answer. The two that can wait on a person, or on
#: landing the run's work, wait up to the longest Claude Code allows.
HOOKS: dict[str, tuple[str, str]] = {
    "SessionStart": ("session_start", "short"),
    "UserPromptSubmit": ("prompt", "short"),
    "PreToolUse": ("pre_tool_use", "long"),
    # The second chance. On the server on 14 September, twice, a run's first
    # tool call never reached the program through PreToolUse: once Claude
    # Code asked on its own screen, once a read-only command simply ran.
    # PermissionRequest fires whenever Claude Code is about to ask on its
    # own screen, so the program decides those too, with the same rules.
    "PermissionRequest": ("permission_request", "long"),
    "PostToolUse": ("post_tool_use", "short"),
    "SubagentStart": ("subagent_start", "short"),
    "SubagentStop": ("subagent_stop", "short"),
    "Notification": ("notification", "short"),
    "Stop": ("stop", "long"),
    "SessionEnd": ("session_end", "end"),
}

#: The deny rules written into a run's settings as well. They are the third
#: line, behind the program's two chances to answer: Claude Code enforces
#: them itself, so they bind even when no hook is heard at all.
#: Pushing is not among them since 19 September 2026. The person's standing
#: policy is that work which passes its tests goes to main and is deployed from
#: there, with nobody asked, so a rule that refused the push was refusing the
#: last step of the job (see PUSH_AND_DEPLOY below).
DENY = (
    "Bash(sudo:*)", "Bash(ssh:*)", "Bash(scp:*)",
    "Read(**/.env)", "Read(**/.env.*)", "Read(~/.ssh/**)", "Read(~/.claude.json)",
    "Read(~/.claude/settings.json)", "Read(**/*.pem)", "Read(**/id_rsa*)", "Read(**/id_ed25519*)",
    "Edit(**/.env)", "Edit(~/.ssh/**)", "Edit(~/.claude/**)",
)

#: What a Codex run has not got, and what the program loses with it. Said here
#: rather than in a comment because the write-up and the page both quote it.
CODEX_GAPS = (
    ("Notification", "Codex has no Notification hook. Claude Code sends one when it is "
                     "waiting on its own screen, and the program uses it twice: to tell the "
                     "person a run is stuck at a question, and to end a turn whose Stop hook "
                     "was lost. Neither happens for a Codex run."),
    ("deny list", "Codex has no deny rules in its own settings. A Claude Code run is refused "
                  "pushing, sudo, ssh and key files by Claude Code itself, with no hook "
                  "involved; for a Codex run the same rules hold only through the hook, which "
                  "is why a hook that cannot reach the program refuses the call."),
    ("hook trust", "Codex runs with its hooks silently switched off unless it is started with "
                   "--dangerously-bypass-hook-trust, because the program writes the hooks and "
                   "Codex has not been told by a person to trust them. The program passes that "
                   "flag and then proves the hooks are live: a Codex run that has not sent "
                   "SessionStart within ONE_CODEX_HANDSHAKE seconds is stopped."),
    ("hosted tools", "A tool that runs on OpenAI's side rather than on this machine never reaches "
                     "a hook at all, so the program would never see it or be able to refuse it. "
                     "Codex's web search is the one of those, and this is why a run is never "
                     "started with --search: the only tools a Codex run has are the ones the "
                     "program can decide."),
)

#: Codex reads ``permissionDecision: "ask"`` and then refuses it as unsupported.
#: The program never sends it: ``runs.py`` turns an "ask" rule into a question
#: to the person first and sends allow or deny once that is answered. Written
#: down so nobody adds one later and finds out the hard way. ``"allow"`` is
#: refused the same way, so ``codexhook.py`` answers an allowed call with nothing.
CODEX_NO_ASK = True


def hook_settings(run_id: str, key: str, hook_url: str, *, long_timeout: int = 600,
                  access: str = "full") -> dict[str, Any]:
    """The settings file a run starts with: every hook pointing at the program.

    With full access (D8) nothing is refused, so the deny rules are left out;
    the hooks stay, because every call is still written down.
    """
    timeouts = {"short": 15, "long": long_timeout, "end": 5}
    hooks: dict[str, Any] = {}
    for event, (kind, length) in HOOKS.items():
        url = f"{hook_url}?run={run_id}&kind={kind}&key={key}"
        if event == "SessionStart":
            # Claude Code sends no HTTP hook for SessionStart ("HTTP hooks are
            # not supported for SessionStart", its own debug log on the server,
            # 14 September). A command hook posting the same payload does the
            # same job, and tells the program the moment a run is up.
            command = (f"curl -sS -m 5 -X POST -H 'Content-Type: application/json' "
                       f"--data-binary @- {shlex.quote(url)} >/dev/null 2>&1 || true")
            hooks[event] = [{"hooks": [{"type": "command", "command": command, "timeout": 10}]}]
            continue
        hooks[event] = [{"hooks": [{"type": "http", "url": url, "timeout": timeouts[length]}]}]
    settings: dict[str, Any] = {"hooks": hooks}
    if access != "full":
        settings["permissions"] = {"deny": list(DENY)}
    return settings


def session_context(brief: str) -> dict[str, Any]:
    """How a Codex run is told the way this run works, as the SessionStart answer.

    Claude Code takes it as ``--append-system-prompt``. Codex has no such
    flag, and no config setting for one either; what it has is a SessionStart
    hook whose ``additionalContext`` is put in front of the model as a
    developer message. Proven on this server on 17 September 2026 by reading
    what the model was actually sent.
    """
    return {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                   "additionalContext": brief}}


# ---------------------------------------------------------------------------
# The agent instructions
# ---------------------------------------------------------------------------


#: How long a starting run waits for Rouh to say its agent instructions.
INSTRUCTIONS_TIMEOUT = 8.0


def _rouh_worker_key() -> str:
    """The key Rouh made for a worker in another container (`rouh/workerkey.py`), or ""."""
    path = os.environ.get("ROUH_WORKER_KEY_FILE", "").strip() or "/run/one/rouh-worker.json"
    try:
        with open(path, encoding="utf-8") as fh:
            return str(json.load(fh).get("token") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def fetch_instructions(rouh_url: str, *, run_id: str, task: str = "",
                       timeout: float = INSTRUCTIONS_TIMEOUT) -> str:
    """The agent instructions a run starts with, from Rouh on this machine.

    They were two files in the workspace, ``workspace/AGENTS.md`` and the
    ``AGENTS_ASSISTANT.md`` it imported, until 15 October 2026, when Petar had
    them kept in Rouh's database instead and given to every run as it starts
    (``rouh/agent_instructions.py``): "I need it to be dynamically, because we
    end up modifying the system all the time and no need to save in files".
    Rouh assembles them fresh for each run and writes down what it gave, with
    ``task`` the task in play when there is one. Raises when Rouh does not
    answer with them, saying why.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    if not rouh_url:
        raise RuntimeError("no address for Rouh is set (ONE_ROUH_URL)")
    query = {"run": run_id, "via": "the one program"}
    if task:
        query["task"] = task
    url = f"{rouh_url}/internal/agent-instructions?{urllib.parse.urlencode(query)}"
    # In the containers Rouh is in another container, and the worker shows the key Rouh made
    # for it (`rouh/workerkey.py`); never through a proxy, which Rouh refuses.
    headers = {}
    key = _rouh_worker_key()
    if key:
        headers["X-Rouh-Worker-Key"] = key
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as reply:
            got = json.loads(reply.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            said = json.loads(exc.read().decode("utf-8") or "{}").get("error") or ""
        except ValueError:
            said = ""
        raise RuntimeError(said or f"Rouh answered {exc.code}") from None
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Rouh could not be reached at {rouh_url} ({exc})") from None
    text = str(got.get("text") or "") if got.get("ok") else ""
    if not text.strip():
        raise RuntimeError(str(got.get("error") or "Rouh answered with no instructions"))
    return text


def _post_rouh(rouh_url: str, path: str, body: dict, timeout: float) -> dict:
    """POST JSON to Rouh on this machine, never through a proxy, with the worker's key in the
    containers; the answer, or a RuntimeError saying why there is none. The body is never logged."""
    import urllib.error
    import urllib.request

    if not rouh_url:
        raise RuntimeError("no address for Rouh is set (ONE_ROUH_URL)")
    headers = {"Content-Type": "application/json"}
    key = _rouh_worker_key()
    if key:
        headers["X-Rouh-Worker-Key"] = key
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(f"{rouh_url}{path}", data=json.dumps(body).encode("utf-8"),
                                     headers=headers, method="POST")
    try:
        with opener.open(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            said = json.loads(exc.read().decode("utf-8") or "{}").get("error") or ""
        except ValueError:
            said = ""
        raise RuntimeError(said or f"Rouh answered {exc.code}") from None
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Rouh could not be reached at {rouh_url} ({type(exc).__name__})") from None


def collect_boxes(rouh_url: str, *, key: str, run_id: str, timeout: float = 20.0) -> list[dict]:
    """The boxes a run was handed, ``[{"number", "content"}]``, collected from Rouh once
    (``rouh/boxes.py``, ``collect``). Raises saying why when there are none to collect."""
    got = _post_rouh(rouh_url, "/internal/boxes/collect", {"key": key, "run": run_id}, timeout)
    if not got.get("ok"):
        raise RuntimeError(f"its boxes could not be collected from Rouh: "
                           f"{got.get('error') or 'Rouh gave none'}")
    return [{"number": int(b["number"]), "content": str(b.get("content") or "")}
            for b in got.get("boxes") or []]


def boxes_ended(rouh_url: str, *, run_id: str, timeout: float = 10.0) -> None:
    """Tell Rouh a run's boxes were shredded, so each hand-over's record says so."""
    _post_rouh(rouh_url, "/internal/boxes/shredded", {"run": run_id}, timeout)


#: What Claude Code names in its Stop hook as still going: commands started
#: with ``run_in_background``, sub-agents, monitors, workflows. A turn can end
#: while one of them is still running, which is how run 8109f4b5 came to
#: report itself finished with "Waiting on the `rouh/` suite". Since 18
#: October 2026 such a turn is a pause (`paused_on`), not a finish.
#:
#: Codex sends no such field, so a Codex run is never paused this way and is
#: caught by the checkout instead, which is the rule that holds for both.
BACKGROUND_FIELDS = ("description", "command", "name", "tool_input", "id")


def still_running(payload: Mapping[str, Any]) -> list[str]:
    """What the run started and has not waited for, by name, from a Stop hook.

    Defensive about the shape, because this is somebody else's field, and an
    agent that sends nothing at all is one of the shapes: a list of strings and
    a list of objects both read, and anything else reads as nothing rather than
    as an error at the end of a turn.
    """
    names: list[str] = []
    for task in (payload.get("background_tasks") or []):
        if isinstance(task, str):
            found = task
        elif isinstance(task, Mapping):
            found = next((str(task[f]) for f in BACKGROUND_FIELDS
                          if isinstance(task.get(f), str) and task[f].strip()), "")
        else:
            found = ""
        names.append(" ".join(found.split())[:120] or "a command with no name")
    return names[:10]


#: What a background task's ``status`` says when it is over. Claude Code lists
#: only work in flight, but a field that is somebody else's is read defensively.
OVER = frozenset({"completed", "complete", "done", "failed", "error", "errored", "killed",
                  "stopped", "cancelled", "canceled", "finished", "exited"})


def paused_on(payload: Mapping[str, Any]) -> list[str]:
    """What will wake this session again, by name, from a Stop hook, or [].

    A Stop hook is the end of a turn, and not always the end of the work.
    Claude Code says which in two fields of its own (2.1.2xx and later):
    ``background_tasks``, "in-flight background work ... lets hooks
    distinguish 'session is done' from 'session is paused waiting for
    background work to wake it'", and ``session_crons``, the wake-ups it has
    scheduled (ScheduleWakeup, CronCreate, /loop). Either one, while it lasts,
    comes back to the session as a new prompt by itself: a sub-agent's result,
    a background command's exit, a monitor's line, a wake-up firing.

    Until 18 October 2026 every Stop was read as the run being finished. Run
    9854c2fa ended a turn at 06:48:23 with "The call-site helper is still
    converting files; I'll carry on as soon as it reports", its sub-agent
    "Convert call sites to llm.ask" still editing, and was reported to the
    person as a change that had stopped with nothing saved, then carried on
    for hours by itself when the helper reported.
    """
    names: list[str] = []
    for task in (payload.get("background_tasks") or []):
        if isinstance(task, Mapping) and str(task.get("status") or "").lower() in OVER:
            continue
        names.extend(still_running({"background_tasks": [task]}))
    for cron in (payload.get("session_crons") or []):
        if not isinstance(cron, Mapping):
            continue
        what = " ".join(str(cron.get("prompt") or "").split())[:80]
        when = str(cron.get("schedule") or "").strip()
        label = "a wake-up it scheduled" + (f" ({when})" if when else "")
        if what and not what.startswith("<<"):
            label += f": {what}"
        names.append(label[:120])
    return names[:10]


# ---------------------------------------------------------------------------
# Handing a run back
# ---------------------------------------------------------------------------


def hand_back_message(*, device: str, minutes: float, typed: str, prompts: list[str],
                      screen: str) -> str:
    lines = [f"[The person took over this terminal for {_duration(minutes)}, from {device}, "
             "and has now handed it back to you."]
    if prompts:
        lines.append("What they sent you while they had it:")
        lines += [f"- {p}" for p in prompts[-10:]]
    if typed:
        lines.append("Everything they typed, keys included:")
        lines.append(typed)
    if screen:
        lines.append("What the screen showed when they handed it back:")
        lines.append(screen)
    lines.append("Carry on from where things are now, taking into account what they did.]")
    return "\n".join(lines)


def _duration(minutes: float) -> str:
    seconds = int(round(minutes * 60))
    if seconds < 60:
        return f"{seconds} seconds"
    m = round(seconds / 60)
    return "1 minute" if m == 1 else f"{m} minutes"
