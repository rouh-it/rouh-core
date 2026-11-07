"""Engine selection and command lines for Claude Code and Codex runs."""
from __future__ import annotations

import json

from . import billing as _billing

#: The two agents a run can be, and what each one is called in plain words.
#: Claude Code is the default and is exactly what every run was before 17
#: September 2026; Codex is OpenAI's command-line agent, asked for by name.
ENGINES = ("claude", "codex")
DEFAULT_ENGINE = "claude"
ENGINE_WORDS = {"claude": "Claude Code", "codex": "Codex"}


def engine_of(value: object) -> str:
    """Which agent a run is. Anything unknown, or nothing, is Claude Code."""
    name = str(value or "").strip().lower()
    return name if name in ENGINES else DEFAULT_ENGINE


#: Every hook Codex has, the name it arrives under, and how long Codex waits.
#: The names on both sides are the same, and so are the payloads and the
#: answers, so one set of code in ``runs.py`` decides a call from either agent.
#:
#: Watched working on this server on 17 September 2026 against Codex CLI
#: 0.154.0, driven by a stand-in model, with a throwaway listener in place of
#: the program:
#:
#: * ``SessionStart`` arrived first, in both ``codex exec`` and the full-screen
#:   session, carrying ``session_id``, ``transcript_path`` and ``cwd``. Claude
#:   Code sends no HTTP hook for it at all; Codex sends this one like any other.
#: * ``SessionStart`` answered ``{"hookSpecificOutput": {"additionalContext":
#:   ...}}`` put that text in front of the model as a developer message. That is
#:   what Claude Code's ``--append-system-prompt`` does, which Codex has not got.
#: * ``PreToolUse`` arrived for a shell command as ``tool_name`` ``"Bash"`` with
#:   ``tool_input`` ``{"command": ...}`` - the same name and the same shape
#:   Claude Code uses, although the tool Codex offers its model is called
#:   ``exec_command`` and takes a ``cmd``.
#: * ``PreToolUse`` answered ``deny`` with a reason: the command did not run,
#:   and the reason was given back to the model as the call's result.
#: * ``Stop`` answered ``{"decision": "block", "reason": ...}``: Codex carried
#:   on and did what the reason said, and a second ``Stop`` followed.
#: * ``PostToolUse`` carries ``tool_response`` as a plain string, where Claude
#:   Code sends an object. ``closed_body`` reads both.
CODEX_HOOKS: dict[str, tuple[str, str]] = {
    "SessionStart": ("session_start", "short"),
    "UserPromptSubmit": ("prompt", "short"),
    "PreToolUse": ("pre_tool_use", "long"),
    "PermissionRequest": ("permission_request", "long"),
    "PostToolUse": ("post_tool_use", "short"),
    "SubagentStart": ("subagent_start", "short"),
    "SubagentStop": ("subagent_stop", "short"),
    "Stop": ("stop", "long"),
    "SessionEnd": ("session_end", "end"),
}


def claude_args(*, model: str, settings_path: str, session_id: str | None = None,
                resume: str | None = None, run_id: str, prompt: str | None,
                debug_file: str | None = None, access: str = "full",
                effort: str | None = None, mcp_config: str | None = None,
                append_system_prompt: str | None = None) -> list[str]:
    # Full access runs with Claude Code's own permission checks off: a run
    # works unwatched on the server, so it never stops to ask on its screen.
    mode = "bypassPermissions" if access == "full" else "default"
    args = ["--settings", settings_path, "--permission-mode", mode, "--model", model,
            "--name", f"one-{run_id}"]
    # How hard the run thinks. A run works unwatched, so it is given the
    # thinking rather than the speed. The level is the run's own when its
    # request said one, and `Settings.agent_effort` when not.
    if effort:
        args += ["--effort", effort]
    # This machine's own MCP servers, which a worktree made a minute ago has no
    # other way of getting: a directory Claude Code has never seen has none at
    # all unless the checkout committed a .mcp.json, and most do not. Passed
    # this way they need no approval, so nothing stops to ask a question a run
    # nobody is watching cannot answer. `asuser.py` wrote the file and said
    # where; see `_write_machine_mcp` there for why the checkout's own wins.
    if mcp_config:
        args += ["--mcp-config", mcp_config]
    if debug_file:
        args += ["--debug-file", debug_file]
    if append_system_prompt:
        args += ["--append-system-prompt", append_system_prompt]
    if resume:
        args += ["--resume", resume]
    elif session_id:
        args += ["--session-id", session_id]
    # The person's own session starts with no prompt: they type the first one.
    if prompt:
        args.append(prompt)
    return args


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


#: Where the OpenAI API is, for a run billed to the key.
DEFAULT_API_BASE_URL = "https://api.openai.com/v1"


def _toml_string(text: str) -> str:
    """A TOML basic string. JSON's escaping of these characters is TOML's."""
    return json.dumps(text)


def codex_hook_overrides(run_id: str, hook_url: str, *, poster: str, python: str,
                         long_timeout: int = 600) -> list[str]:
    """Every hook a Codex run is given, as ``-c`` settings on its command line.

    They do not go in a file. Codex reads hooks from ``$CODEX_HOME/hooks.json``
    or from a ``[hooks]`` table in its config, both of which are the whole
    machine's, shared by every run; a run's hooks have to name that run, so
    they travel on its own command line instead. Nothing secret is on that
    line: the run's key goes to the hook in the environment (``ONE_HOOK_KEY``),
    which ``asuser.py`` sets and which Codex passes to a command hook.
    """
    timeouts = {"short": 15, "long": long_timeout, "end": 5}
    out: list[str] = []
    for event, (kind, length) in CODEX_HOOKS.items():
        seconds = timeouts[length]
        command = " ".join([python, poster, _toml_string(hook_url), run_id, kind, str(seconds)])
        value = ('[{hooks=[{type="command",command=%s,timeout=%d}]}]'
                 % (_toml_string(command), seconds))
        out += ["-c", f"hooks.{event}={value}"]
    return out


def codex_args(*, model: str, run_id: str, hook_url: str, poster: str, python: str,
               prompt: str | None, long_timeout: int = 600, access: str = "full",
               effort: str | None = None, billing: str = "subscription",
               api_base_url: str = "", resume_session: str | None = None,
               browser_port: int = 0) -> list[str]:
    """The command a run of Codex is started with.

    ``--dangerously-bypass-hook-trust`` is not optional and is not bravado.
    Codex will not run a hook it has not been told by a person to trust, and it
    says nothing at all when it skips one: watched on this server on 17
    September 2026, a Codex run with the program's hooks and without this flag
    ran its command, wrote its file and reported success, having asked the
    program nothing. The flag is Codex's own documented way in for "automation
    that already vets hook sources", which is exactly what the program is: it
    writes the hooks itself, on the command line, a moment before it starts the
    run. What it does not do is make the flag the only thing standing between a
    run and no rules, which is what ``runs.py``'s handshake is for.

    ``billing`` is who pays (``billing.py``). The subscription is Codex's own
    login and adds nothing to this line, so a run on it starts exactly as every
    run of Codex did before the key could be chosen. The key adds the run's own
    provider, which names the variable the key is in and never the key.

    ``resume_session`` starts ``codex resume <session>`` instead of a new
    conversation: the same session file, carried on, which is how a run
    stopped by its subscription goes on on the key.
    """
    args = ["resume"] if resume_session else []
    args += ["--dangerously-bypass-hook-trust"]
    if model:
        args += ["--model", model]
    if effort:
        # How hard the run thinks. Codex has no flag for it: the level is the
        # config setting `model_reasoning_effort`, and a `-c` override beats
        # every config file, so it travels on the command line as the hooks
        # above do. `Settings.codex_effort` is where the level is.
        #
        # The level is the model's, not Codex's: xhigh is not something every
        # model has. Watched here with codex-cli 0.154.0 on 19 September 2026,
        # against `codex debug prompt-input`, which reads the same config a run
        # does: a level the model does not know is taken without a word and the
        # run starts anyway, while a value that is not a string is refused
        # outright ("invalid type: integer `5`, expected a string in
        # `model_reasoning_effort`", exit 1). So the level is always written as
        # a TOML string, and a level that turns out to be wrong for the model
        # costs the run its thinking, never its start.
        args += ["-c", f"model_reasoning_effort={_toml_string(effort)}"]
    if access == "full":
        # Full access, the person's decision (D8): Codex's own sandbox off and
        # nobody asked, the way Claude Code's bypass mode is. The program's
        # hooks still see every call and still write every one down.
        args += ["--sandbox", "danger-full-access", "--ask-for-approval", "never"]
    else:
        # Guarded: Codex may write in the run's own folder and asks about
        # anything beyond it, and the asking comes to the program through the
        # PermissionRequest hook, as Claude Code's does.
        args += ["--sandbox", "workspace-write", "--ask-for-approval", "on-request"]
    args += codex_hook_overrides(run_id, hook_url, poster=poster, python=python,
                                 long_timeout=long_timeout)
    if billing == _billing.API:
        args += _billing.provider_overrides(api_base_url or DEFAULT_API_BASE_URL)
    if browser_port:
        # Codex hands an MCP server only the variables it is told to, and the
        # machine's servers are in its shared config, so this run's browser is
        # given the path to its own configuration here, on its own line
        # (asuser.py, ``_browser_config``). Claude Code passes its environment on.
        args += ["-c", 'mcp_servers.playwright.env_vars=["PLAYWRIGHT_MCP_CONFIG"]']
    if resume_session:
        args.append(resume_session)
    if prompt:
        args.append(prompt)
    return args
