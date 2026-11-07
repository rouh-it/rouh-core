"""Agent trust configuration used by the privileged command.

The command supplies identity, MCP merging and JSON output through its module,
so both imported callers and isolated script invocation keep the same boundary.
"""
from __future__ import annotations

import json
import os
import re
import tempfile


def _toml_str(text: str) -> str:
    """A TOML basic string. JSON's escaping of these characters is TOML's."""
    return json.dumps(text)


def _codex_home(command) -> str:
    return os.environ.get("CODEX_HOME") or os.path.join(command._home(), ".codex")


def _seed_codex_trust(args, _trust_command) -> int:
    """Tell Codex this checkout is trusted, before a run nobody is watching starts in it.

    Codex in a folder it has never seen stops on its own screen and asks
    whether the folder is trusted, and a run nobody is watching would sit there
    for ever: seen on this server on 17 September 2026, where the session put
    out 829 bytes and stopped, having sent not one hook, and 28 kilobytes and
    worked normally once the folder was trusted.

    Trust is one table in Codex's own config, which is this user's and is
    shared by every run, so the file is read, added to and written back whole;
    nothing else in it is touched. Codex's config is TOML and this has no TOML
    writer in the standard library, so the entry is appended as text, which is
    what TOML's own grammar is for: a table at the end of a file is the same
    table wherever it appears. An entry already there is left alone.
    """
    path = os.path.realpath(args.path)
    home = _trust_command._codex_home()
    config_path = os.path.join(home, "config.toml")
    header = f'[projects."{path}"]'
    if '"' in path or "\\" in path:
        return _trust_command._out({"ok": False, "reason": f"{path} cannot be named in Codex's config"})
    try:
        with open(config_path, encoding="utf-8") as fh:
            text = fh.read()
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        return _trust_command._out({"ok": False, "reason": f"{config_path}: {exc}"})
    addition = ""
    if header not in text:
        addition += (
            f'\n# Added by the one program so a run of Codex in this checkout does not\n'
            f'# stop to ask whether the folder is trusted. Nobody is watching it.\n'
            f'{header}\ntrust_level = "trusted"\n')
    # Codex has no --mcp-config: its servers live in this one file, which is
    # this user's and is shared by every run, so this machine's servers are
    # added to it once rather than per checkout. A name already in the file
    # wins and is left exactly as it is, which is the same rule Claude Code
    # gets, one level up: what is already configured beats the default.
    added = []
    for name, spec in sorted(_trust_command._machine_mcp_servers().items()):
        table = f'[mcp_servers.{name}]'
        if table in text or table in addition or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            continue
        command = spec.get("command")
        if not isinstance(command, str):
            continue
        args = [a for a in (spec.get("args") or []) if isinstance(a, str)]
        passes = _trust_command.CODEX_PASSES_ON.get(name, ())
        addition += (
            f'\n# Added by the one program: the MCP servers every run on this machine\n'
            f'# gets. Edit mcp-servers.json in the rouh repository, not this file.\n'
            f'{table}\ncommand = {_trust_command._toml_str(command)}\n'
            f'args = [{", ".join(_trust_command._toml_str(a) for a in args)}]\n'
            + (f'env_vars = [{", ".join(_trust_command._toml_str(v) for v in passes)}]\n' if passes else ""))
        added.append(name)
    if not addition:
        return _trust_command._out({"ok": True, "paths": [path], "already": True, "mcp": []})
    os.makedirs(home, mode=0o700, exist_ok=True)
    head = "" if not text or text.endswith("\n") else "\n"
    fd, tmp = tempfile.mkstemp(dir=home, prefix=".config.toml.one-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text + head + addition)
    os.chmod(tmp, 0o600)
    os.replace(tmp, config_path)
    return _trust_command._out({"ok": True, "paths": [path], "already": False, "mcp": added})


def _claude_project_root(folder: str) -> str | None:
    """The folder Claude Code files ``folder``'s trust under, or None outside git.

    Claude Code keys its per-project config, which holds the answer to the
    trust dialog and the MCP servers approved with it, on the repository a
    folder belongs to rather than on the folder: the git root above it, and
    for a git worktree the repository the worktree was made from. A run's
    checkout at /srv/one-runs/<id> is filed under /srv/spaces/<space>.

    This reads the worktree's ``.git`` file the way the binary does, and
    checks the same things it checks, so a folder it would not follow to a
    repository is answered with its own git root, as the binary answers it.
    Read out of Claude Code 2.1.274 on 24 September 2026; rouh/crew.py has
    the same function for the crew's worktrees.
    """
    here, root = os.path.abspath(folder), None
    while True:
        if os.path.lexists(os.path.join(here, ".git")):
            root = here
            break
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up
    dot_git = os.path.join(root, ".git")
    if os.path.islink(dot_git):
        return None
    try:
        with open(dot_git, encoding="utf-8") as fh:
            line = fh.read().strip()
    except OSError:
        # A directory: an ordinary checkout, filed under its own root.
        return root
    if not line.startswith("gitdir:"):
        return root
    try:
        gitdir = os.path.normpath(os.path.join(root, line[len("gitdir:"):].strip()))
        with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as fh:
            common = os.path.normpath(os.path.join(gitdir, fh.read().strip()))
        with open(os.path.join(gitdir, "gitdir"), encoding="utf-8") as fh:
            back = os.path.normpath(os.path.join(gitdir, fh.read().strip()))
    except OSError:
        return root
    if os.path.dirname(gitdir) != os.path.join(common, "worktrees"):
        return root
    if os.path.realpath(back) != os.path.realpath(dot_git):
        return root
    return os.path.dirname(common) if os.path.basename(common) == ".git" else common


def _seed_claude_trust(args, command) -> int:
    """Answer Claude Code's first-run questions for this checkout before it starts.

    Found the hard way by Rouh's crew (task 30, 8 September 2026): interactive
    Claude Code in a folder it has never seen stops on "Is this a project you
    trust?", and throws away the folder's hooks until someone says yes. A run
    nobody is watching would sit there for ever. The same is true of the text
    style question and the onboarding screens on a machine where nobody has
    ever run it by hand. So they are answered in its config file first.

    A checkout's own ``.mcp.json`` raises "use this MCP server?" as well. That
    one is answered yes: a server committed to the repository is the repository
    asking for it, which is not the same as a server a stranger's folder asks
    for, and a run that has to drive a browser over Playwright MCP cannot do it
    if the first thing done to its checkout is to turn that server off. It was
    answered no until 20 September 2026, which quietly disabled the browser for
    every run in a repository that had just been given one.
    """
    config_path = os.path.join(command._home(), ".claude.json")
    paths = {args.path, os.path.realpath(args.path)}
    # And the repository the checkout was made from, which is where Claude
    # Code looks (`_claude_project_root`). Trust on the checkout alone gets
    # past the first question, but a checkout whose .claude/settings.json
    # pre-approves a tool is asked again, on the same screen, unless its
    # repository is trusted: "This folder pre-approves 1 tool permission in
    # .claude/settings.json ... No, continue without these permissions".
    # Rouh's crew sat on it on 24 September 2026; runs here were spared
    # only because /srv/spaces/rouh had been trusted by hand.
    if (repository := command._claude_project_root(args.path)) is not None:
        paths |= {repository, os.path.realpath(repository)}
    # This machine's own servers go into the checkout now, to be handed to the
    # run with --mcp-config, and their names are approved here beside the
    # checkout's own. The machine's need no approval to be passed that way, but
    # a repository that later commits one of the same names to its own
    # .mcp.json would raise "use this MCP server?" for it, and the answer is
    # already known.
    mcp_config = command._write_merged_mcp(args.path)
    offered = sorted(set(command._mcp_servers(os.path.join(args.path, ".mcp.json")))
                     | set(command._mcp_servers(command.MACHINE_MCP_SERVERS)))
    try:
        with open(config_path, encoding="utf-8") as fh:
            config = json.load(fh)
    except FileNotFoundError:
        config = {}
    except ValueError:
        return command._out({"ok": False, "reason": f"{config_path} is not valid JSON"})
    config["hasCompletedOnboarding"] = True
    config.setdefault("theme", "dark")
    projects = config.setdefault("projects", {})
    for path in paths:
        entry = projects.get(path) if isinstance(projects.get(path), dict) else {}
        merged = {
            "allowedTools": [], "mcpContextUris": [], "mcpServers": {},
            "enabledMcpjsonServers": [], "disabledMcpjsonServers": [],
            "hasClaudeMdExternalIncludesApproved": False,
            "hasClaudeMdExternalIncludesWarningShown": False,
            **entry,
            "hasTrustDialogAccepted": True,
        }
        if offered:
            # Taken off the refused list as well as put on the allowed one: a
            # checkout seeded before this changed still says no, and no wins.
            merged["enabledMcpjsonServers"] = sorted(
                set(merged.get("enabledMcpjsonServers") or []) | set(offered))
            merged["disabledMcpjsonServers"] = sorted(
                set(merged.get("disabledMcpjsonServers") or []) - set(offered))
        projects[path] = merged
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(config_path), prefix=".claude.json.one-")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, config_path)
    if args.bypass:
        # Full access starts Claude Code with its own permission checks off,
        # and it asks once, on its screen, whether that is really meant. The
        # answer it reads is in the user's settings file, as Rouh's crew
        # found on 8 September; everything else in that file is kept.
        settings_path = os.path.join(command._home(), ".claude", "settings.json")
        try:
            with open(settings_path, encoding="utf-8") as fh:
                settings = json.load(fh)
        except FileNotFoundError:
            settings = {}
        except ValueError:
            return command._out({"ok": False, "reason": f"{settings_path} is not valid JSON"})
        if settings.get("skipDangerousModePermissionPrompt") is not True:
            settings["skipDangerousModePermissionPrompt"] = True
            os.makedirs(os.path.dirname(settings_path), mode=0o700, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(settings_path), prefix=".settings.json.one-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(settings, fh, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, settings_path)
    # ``mcp_config`` is the file the run is handed with --mcp-config. The
    # program reads it off this line; an empty string means the checkout
    # already defines everything this machine would have added.
    return command._out({"ok": True, "paths": sorted(paths), "trusted_mcp": offered,
                 "mcp_config": mcp_config})
