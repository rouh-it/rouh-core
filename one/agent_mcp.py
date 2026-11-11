"""Agent tool-server configuration used by the privileged command.

The command supplies the helper lookup boundary so imported callers and isolated
script invocation keep their existing configuration and monkeypatch paths.
"""
from __future__ import annotations

import json
import os
import select
import shutil
import subprocess
import tempfile
import time


#: The MCP servers every agent on this machine gets, wherever it runs. One
#: file, committed at the top of this repository, read by this and by
#: rouh/crew.py, which are the two places that start an agent. Adding a
#: server for every run means editing that file and nothing else. It is found
#: beside this script rather than in the run's checkout, so a run in any
#: repository at all gets the machine's servers, not that repository's idea of
#: them. See AGENTS.md, "The MCP servers every run gets".
MACHINE_MCP_SERVERS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp-servers.json")


def _mcp_servers(path: str) -> dict:
    """The ``mcpServers`` table in one of these files, or nothing at all.

    Never raises. A checkout with no .mcp.json is the ordinary case, and a
    machine still serving a deploy from before mcp-servers.json existed reads
    nothing here rather than failing to start a run.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            servers = json.load(fh).get("mcpServers")
        return dict(servers) if isinstance(servers, dict) else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _machine_mcp_servers(command) -> dict:
    """This machine's own servers, with ``{repo}`` filled in.

    ``{repo}`` is the folder MACHINE_MCP_SERVERS is in: the program's own
    checkout, which no run can change. It is how a server that is a file of
    this repository - Rouh's ``rouh/worker_mcp.py`` - is named whatever
    checkout the run works in. rouh/crew.py fills it in the same way.
    """
    here = os.path.dirname(command.MACHINE_MCP_SERVERS)

    def fill(value):
        if isinstance(value, str):
            return value.replace("{repo}", here)
        if isinstance(value, list):
            return [fill(v) for v in value]
        if isinstance(value, dict):
            return {k: fill(v) for k, v in value.items()}
        return value

    return command._pinned_browser({
        name: fill(spec)
        for name, spec in command._mcp_servers(command.MACHINE_MCP_SERVERS).items()
    })


def _pinned_browser(servers: dict) -> dict:
    """The headless browser the base image keeps, where it says so.

    mcp-servers.json asks for ``@playwright/mcp@latest``, which on the server is
    what npx fetches. In Rouh's containers the code is the person's own (/code)
    and the base image beside it holds a pinned Playwright MCP and Debian's
    Chromium, which it keeps on Chrome's security releases
    (deploy/container/Dockerfile.base). It says so with ``ONE_PLAYWRIGHT_MCP``
    (the package to run instead) and ``ONE_PLAYWRIGHT_CHROMIUM`` (the browser
    it is to drive), so a run starts the browser the base keeps patched, with
    nothing downloaded. Neither is set on the server, where nothing changes.
    """
    # sudo intentionally clears the service environment before running
    # asuser.py, so the image's own recorded pins are the reliable source for
    # both its main process and the privileged launcher.
    base = {}
    try:
        with open("/opt/rouh-base/base.env", encoding="utf-8") as fh:
            for line in fh:
                key, sep, value = line.rstrip("\n").partition("=")
                if sep:
                    base[key] = value
    except OSError:
        pass
    spec = (os.environ.get("ONE_PLAYWRIGHT_MCP") or
            (f"@playwright/mcp@{base['playwright_mcp']}" if base.get("playwright_mcp") else "")).strip()
    chromium = (os.environ.get("ONE_PLAYWRIGHT_CHROMIUM") or
                ("/usr/bin/chromium" if base.get("playwright_mcp") else "")).strip()
    playwright = servers.get("playwright")
    if not isinstance(playwright, dict) or not (spec or chromium):
        return servers
    playwright = dict(playwright)
    if spec:
        # The base installs this exact package globally. Running it through
        # npx still makes npm resolve a package spec and can try the network
        # from an isolated worker, even though the package is already present.
        # Use npm's global shim directly and keep only the server options.
        binary = os.environ.get("ONE_PLAYWRIGHT_MCP_COMMAND", "/usr/local/bin/playwright-mcp")
        playwright["command"] = binary
        playwright["args"] = [a for a in (playwright.get("args") or [])
                              if not str(a).startswith("@playwright/mcp@")]
        if chromium and not any(str(a).startswith("--executable-path")
                                for a in playwright["args"]):
            playwright["args"] += ["--executable-path", chromium]
    if chromium:
        playwright["env"] = {**(playwright.get("env") or {}), "PLAYWRIGHT_MCP_EXECUTABLE_PATH": chromium}
    return {**servers, "playwright": playwright}


def _mcp_response(proc: subprocess.Popen, wanted: int, deadline: float) -> dict:
    """Read stdio MCP messages until the response with ``wanted`` arrives."""
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        ready, _, _ = select.select([proc.stdout], [], [], remaining)
        if not ready:
            break
        line = proc.stdout.readline()
        if not line:
            break
        try:
            message = json.loads(line)
        except (TypeError, ValueError):
            continue
        if message.get("id") == wanted:
            if "error" in message:
                raise RuntimeError(str(message["error"]))
            return message.get("result") or {}
    if proc.poll() is not None:
        raise RuntimeError(f"server exited with status {proc.returncode}")
    raise TimeoutError(f"no MCP response to request {wanted} within 20 seconds")


def _mcp_call(proc: subprocess.Popen, request_id: int, method: str, params: dict,
              deadline: float) -> dict:
    proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": request_id,
                                  "method": method, "params": params}) + "\n").encode())
    proc.stdin.flush()
    return _mcp_response(proc, request_id, deadline)


def check_playwright(servers: dict, env: dict, *, cwd: str) -> None:
    """Fail before an agent starts unless its configured browser can load a page.

    This exercises the same server entry from the merged MCP config used by
    Claude, and the same machine server that Codex is configured to launch.
    It checks the tool list and drives Chromium through browser_navigate and
    browser_snapshot, rather than treating an installed package as proof.
    """
    spec = servers.get("playwright")
    if not isinstance(spec, dict):
        raise RuntimeError("the merged MCP configuration has no playwright server")
    command = spec.get("command")
    if not isinstance(command, str) or not command:
        raise RuntimeError("the playwright MCP server has no command")
    binary = command if os.path.isabs(command) else shutil.which(command, path=env.get("PATH", ""))
    if not binary or not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        raise RuntimeError(f"the playwright MCP command is not executable: {command}")
    server_env = dict(env)
    server_env.update({str(k): str(v) for k, v in (spec.get("env") or {}).items()})
    args = [str(a) for a in (spec.get("args") or [])]
    proc = None
    try:
        proc = subprocess.Popen([binary, *args], cwd=cwd, env=server_env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=False, bufsize=0)
        deadline = time.monotonic() + 20
        initialized = _mcp_call(proc, 1, "initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "one-browser-startup-check", "version": "1"}}, deadline)
        if not initialized.get("serverInfo"):
            raise RuntimeError("the playwright MCP server did not complete initialization")
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
                          + "\n").encode())
        proc.stdin.flush()
        tools = _mcp_call(proc, 2, "tools/list", {}, deadline).get("tools") or []
        names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        if not {"browser_navigate", "browser_snapshot"} <= names:
            raise RuntimeError("the playwright MCP server did not offer browser_navigate and browser_snapshot")
        page_text = "Playwright MCP startup check passed"
        url = "data:text/html,<title>Worker browser ready</title><p>" + page_text.replace(" ", "%20") + "</p>"
        navigated = _mcp_call(proc, 3, "tools/call", {
            "name": "browser_navigate", "arguments": {"url": url}}, deadline)
        if navigated.get("isError"):
            raise RuntimeError(f"browser_navigate failed: {navigated.get('content', [])}")
        snapshot = _mcp_call(proc, 4, "tools/call", {
            "name": "browser_snapshot", "arguments": {}}, deadline)
        if snapshot.get("isError"):
            raise RuntimeError(f"browser_snapshot failed: {snapshot.get('content', [])}")
        text = " ".join(str(item.get("text", "")) for item in snapshot.get("content", [])
                        if isinstance(item, dict))
        if page_text not in text:
            raise RuntimeError("Chromium opened a page, but its snapshot did not contain the expected text")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)


#: What Codex has to be told to pass on to a machine server, by name. Claude
#: Code hands an MCP server its whole environment; Codex hands it almost none,
#: so the run's id, which is the only way Rouh's server knows whose note it is
#: queueing (rouh/worker_mcp.py), is named here. Checked against Codex 0.154
#: with ``codex mcp get`` on 24 September 2026.
CODEX_PASSES_ON = {"rouh": ("ONE_RUN",)}


def _write_merged_mcp(cwd: str, command) -> str:
    """Write the MCP servers this run gets, and return the file to hand it.

    A run works in a worktree made a minute ago, and a directory Claude Code
    has never seen has no servers at all. That is why `/mcp` in a new run said
    "No MCP servers configured": the browser every change here is meant to be
    proved in was simply not there.

    Two things are merged: MACHINE_MCP_SERVERS, the list at the top of the
    rouh repository that every run on this machine is entitled to, and the
    checkout's own .mcp.json. **The checkout's own entry wins a name
    collision**, which is what the order of the update below does.

    Everything is then handed over with --mcp-config, the checkout's own
    included, and that is not belt and braces. Measured on Claude Code 2.1.274
    on 21 September 2026: a checkout's .mcp.json is not loaded at all unless
    something enables it, and what enables it is `enabledMcpjsonServers` in
    that checkout's own .claude/settings.json. The per-path approval seeded
    into ~/.claude.json below is not what this build reads. Two worktrees, one
    of the rouh repository and one of the person's workspace, were approved
    identically there and both committed a playwright to .mcp.json; the first
    came up "connected" and the second said "No MCP servers configured", and
    the only difference was that the rouh repository commits a
    .claude/settings.json that turns it on. A server passed with --mcp-config
    needs no approval anywhere and came up connected in a git directory made
    seconds earlier, so that is the one road everything takes.

    Returns the path to pass, or "" when there is nothing to pass. It goes in
    ``.one/``, which already carries a .gitignore of ``*``, so it can never
    reach the repository, whatever repository this is.
    """
    wanted = command._machine_mcp_servers()
    wanted.update(command._mcp_servers(os.path.join(cwd, ".mcp.json")))
    if not wanted:
        return ""
    own = os.path.join(cwd, ".one")
    path = os.path.join(own, "mcp.json")
    try:
        os.makedirs(own, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=own, prefix=".mcp.json.one-")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"mcpServers": wanted}, fh, indent=2)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
        return path
    except OSError:
        return ""


#: The variable Playwright MCP reads a configuration file's path from. Set
#: only for a run whose browser Rouh is to reach (``--browser-port``).
BROWSER_CONFIG_VAR = "PLAYWRIGHT_MCP_CONFIG"


def _browser_config(cwd: str, port: int) -> str:
    """The run's own Playwright MCP configuration, which opens DevTools on ``port``.

    For the nightly feature run only (`rouh/nightly_feature.py`): Rouh connects
    to that port on this machine and fills the vault's card into the checkout
    the run has open, so the card is typed by Rouh and never by the run's model
    (`rouh/payments.py`, `fill_card_in_run`). Chromium listens on loopback
    alone. The file is in the run's own folder, which the program never shows.
    """
    own = os.path.join(cwd, ".one")
    os.makedirs(own, exist_ok=True)
    path = os.path.join(own, "playwright.json")
    body = {"browser": {"launchOptions": {"args": [
        f"--remote-debugging-port={int(port)}", "--remote-debugging-address=127.0.0.1"]}}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh)
    return path
