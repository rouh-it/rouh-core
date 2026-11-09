"""Safe subscription metadata and read-only capacity, kept in the worker.

No credential is returned to the core. Codex's own app-server reads its limits;
Claude's usage endpoint uses its local sign-in and returns only known numbers.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import re
import time
from pathlib import Path
from uuid import UUID

from . import codexhome

TEAM_PLANS = {"team", "business", "enterprise", "edu"}
PERSONAL_PLANS = {"free", "go", "plus", "pro", "max"}


def workspace(plan: str) -> str:
    plan = plan.lower()
    return "Team" if plan in TEAM_PLANS else "Personal" if plan in PERSONAL_PLANS else "Unknown"


def read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def choice(home: str | None = None) -> dict:
    return read(Path(codexhome.folder(home)) / "rouh-workspace.json")


def keep_choice(data: dict) -> None:
    path = Path(codexhome.folder()) / "rouh-workspace.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".new")
    tmp.write_text(json.dumps(data) + "\n")
    tmp.chmod(0o600)
    tmp.replace(path)


def pin(account_id: str) -> None:
    """Change just the root workspace setting; preserve every other TOML setting."""
    if account_id:
        account_id = str(UUID(account_id))
    path = Path(codexhome.folder()) / "config.toml"
    text = path.read_text() if path.exists() else ""
    lines = text.splitlines(keepends=True)
    root = True
    for i, line in enumerate(lines):
        if line.lstrip().startswith("["):
            root = False
        if root and re.match(r"\s*forced_chatgpt_workspace_id\s*=", line):
            lines[i] = ""
    if account_id:
        lines.insert(0, f'forced_chatgpt_workspace_id = {json.dumps(account_id)}\n')
    import tomllib
    tomllib.loads("".join(lines))
    tmp = path.with_suffix(".toml.new")
    tmp.write_text("".join(lines))
    tmp.chmod(0o600)
    tmp.replace(path)


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def limits(data: dict, *, camel: bool = False) -> dict:
    """A strict allowlist; extra provider fields can never carry secrets to the page."""
    out = {"checked_at": time.time()}
    for key in ("primary", "secondary"):
        w = data.get(key)
        if isinstance(w, dict):
            out[key] = {"used_percent": number(w.get("usedPercent" if camel else "used_percent")),
                        "resets_at": number(w.get("resetsAt" if camel else "resets_at")),
                        "window_minutes": number(w.get("windowDurationMins" if camel else "window_minutes"))}
    c = data.get("credits")
    if isinstance(c, dict):
        balance = c.get("balance")
        # Some Codex versions serialize decimal balances as strings.
        if isinstance(balance, str) and re.fullmatch(r"\d+(\.\d+)?", balance):
            balance = float(balance)
        out["credits"] = {"balance": number(balance),
                          "has_credits": c.get("hasCredits" if camel else "has_credits") if isinstance(c.get("hasCredits" if camel else "has_credits"), bool) else None,
                          "unlimited": c.get("unlimited") is True}
    return out


async def codex_limits(binary: str, env: dict) -> dict:
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "app-server", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env=env, start_new_session=True, limit=2**20)

        async def ask(ident, method, params):
            proc.stdin.write((json.dumps({"id": ident, "method": method, "params": params}) + "\n").encode())
            await proc.stdin.drain()
            while line := await proc.stdout.readline():
                got = json.loads(line)
                if got.get("id") == ident:
                    if "error" in got:
                        raise ValueError("limits unavailable")
                    return got.get("result") or {}
            raise ValueError("worker ended")

        async with asyncio.timeout(15):
            await ask(1, "initialize", {"clientInfo": {"name": "rouh_subscriptions", "version": "1"}})
            proc.stdin.write(b'{"method":"initialized","params":{}}\n')
            got = await ask(2, "account/rateLimits/read", {})
            data = (got.get("rateLimitsByLimitId") or {}).get("codex") or got.get("rateLimits") or {}
            return limits(data, camel=True)
    except (OSError, ValueError, TimeoutError):
        return {"why": "Codex could not read live limits. Press Refresh to try again."}
    finally:
        if proc is not None:
            from .codex_signin import _kill
            _kill(proc)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), 5)


async def claude_limits() -> dict:
    import httpx

    folder = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    oauth = read(folder / ".credentials.json").get("claudeAiOauth") or {}
    token = oauth.get("accessToken")
    if not token:
        return {"why": "Claude Code has not supplied live limits."}
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.get("https://api.anthropic.com/api/oauth/usage", headers={
                "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"})
            response.raise_for_status()
            data = response.json()
        from datetime import datetime
        mapped = {}
        for target, source, minutes in (("primary", "five_hour", 300), ("secondary", "seven_day", 10080)):
            w = data.get(source)
            if isinstance(w, dict):
                reset = w.get("resets_at")
                try:
                    reset = datetime.fromisoformat(reset.replace("Z", "+00:00")).timestamp() if reset else None
                except (ValueError, TypeError, AttributeError):
                    reset = None
                mapped[target] = {"used_percent": w.get("utilization"), "resets_at": reset, "window_minutes": minutes}
        # Extra usage is money, not credits. Do not turn it into a credit balance.
        return limits(mapped)
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return {"why": "Claude Code could not read live limits. Press Refresh to try again."}


# Cache only for this credential file generation, never across an account switch.
_CACHE: dict[str, tuple[tuple, float, dict]] = {}


def credential_stamp(provider: str, home: str | None = None) -> tuple:
    if provider == "codex":
        paths = [Path(codexhome.auth_file(home))]
    else:
        folder = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path(home or Path.home()) / ".claude")
        paths = [folder / ".credentials.json", folder / "settings.json"]
    stamps = []
    for path in paths:
        try:
            st = path.stat()
            stamps.append((str(path), st.st_mtime_ns, st.st_size, st.st_ino))
        except OSError:
            stamps.append((str(path), None))
    return tuple(stamps)


async def capacity(provider: str, load) -> dict:
    stamp = credential_stamp(provider)
    old = _CACHE.get(provider)
    if old and old[0] == stamp and time.monotonic() - old[1] < (15 if old[2].get("why") else 45):
        return dict(old[2])
    result = await load()
    _CACHE[provider] = (stamp, time.monotonic(), result)
    return dict(result)


def codex_workspace_matches(home: str | None = None) -> bool:
    chosen = choice(home)
    if not chosen:
        return True
    from .codex_signin import _claims
    claims = _claims(codexhome.auth_file(home))
    kind = chosen.get("kind")
    return (kind == "any" or claims.get("workspace", "").lower() == kind) and (
        not chosen.get("account_id") or chosen["account_id"] == claims.get("account_id"))


def held_workspace() -> str:
    import tomllib
    try:
        config = tomllib.loads((Path(codexhome.folder()) / "config.toml").read_text())
        return str(config.get("forced_chatgpt_workspace_id") or "")
    except (OSError, ValueError):
        return ""
