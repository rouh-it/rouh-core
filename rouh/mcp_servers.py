"""Anatomy, Connections, MCP servers: the servers a person connects, kept, tested and opened live.

Petar, 15 November 2026: "we need interface to describe the fact that we have MCP capabilities so
people know. somewhere in anatomy we should have mcps and ability to easily connect one."

MCP (Model Context Protocol) is a standard way to plug another program's tools into Rouh. The
client is `rouh/mcp.py`; this is everything around it that a person needs:

- **The list.** The servers this person connected (`McpServer` rows, `rouh/models/mcp.py`) and the
  ones the installation's setting names (`ROUH_MCP_SERVERS`, `ROUH_MCP_CONFIG`), which are shown
  read-only, "from settings". Each says whether it is connected right now, or failing and why in
  plain words, and what tools it gives.
- **Connecting.** An address (streamable HTTP, or a server that answers with events) with an
  optional header, or a command run on this machine with its arguments and environment values,
  or one of a few well-known servers (`PRESETS`) that fills either in. It is tested before it is
  kept: opened, asked for its tools, and closed. Saving opens it again in the running Rouh
  (`ToolRegistry.mcp_attach`), so its tools are Rouh's tools at once, with no restart.
- **Secrets.** A header's value and an environment value are sealed with the instance's key
  (`rouh/encryption.py`), as the Telegram token is, and only ever shown again as their last four.
  A command a person connected is started with only what a program needs from this process's
  environment (`mcp.PLAIN_ENV`), never Rouh's own keys.
- **Safety.** What a server's tools return is somebody else's words, framed as untrusted content
  (`untrusted.MCP_PREFIX`). Each server has Ask first, on by default, which sends every one of its
  tools through the permission gate (`rouh/permissions.py`) so the person says yes before it runs.
  A person's servers are offered only in that person's own turns (`ToolRegistry._mcp_theirs`).

Every row names its organisation and person, and every query asks with both (AGENTS.md, "Whose
data is it").
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
import time

from . import clock, mcp

log = logging.getLogger("rouh.mcp_servers")

PAGE = "/anatomy/connections/mcp"

#: How long a test may take, all of it: start, hello, the tool list and the goodbye.
TEST_TIMEOUT = 25.0

#: Most servers one person may keep: past this it is a list nobody reads.
MAX_SERVERS = 30

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,29}$")


class Refused(ValueError):
    """What the person sent cannot be a server, said in a sentence for the page."""


#: A few well-known servers that fill the form in. Each needs the person's own token, typed on
#: the page, except where it says none. `secret` says where the token goes: a header (with what
#: goes in front of it) or an environment value.
PRESETS = [
    {"id": "github", "name": "github", "title": "GitHub",
     "about": "Repositories, issues and pull requests in your GitHub account.",
     "kind": "http", "url": "https://api.githubcopilot.com/mcp/",
     "secret": {"where": "header", "key": "Authorization", "prefix": "Bearer ",
                "label": "GitHub personal access token",
                "help": "Make one on GitHub under Settings, Developer settings, Personal access tokens.",
                "link": "https://github.com/settings/personal-access-tokens"}},
    {"id": "linear", "name": "linear", "title": "Linear",
     "about": "Issues, projects and cycles in your Linear workspace.",
     "kind": "http", "url": "https://mcp.linear.app/mcp",
     "secret": {"where": "header", "key": "Authorization", "prefix": "Bearer ",
                "label": "Linear API key",
                "help": "Make one in Linear under Settings, Security and access, Personal API keys.",
                "link": "https://linear.app/settings/account/security"}},
    {"id": "notion", "name": "notion", "title": "Notion",
     "about": "Pages and databases your Notion integration is shared with.",
     "kind": "stdio", "command": ["npx", "-y", "@notionhq/notion-mcp-server"],
     "secret": {"where": "env", "key": "NOTION_TOKEN", "prefix": "",
                "label": "Notion integration secret",
                "help": "Make an internal integration in Notion, then share the pages it may use with it.",
                "link": "https://www.notion.so/profile/integrations"}},
    {"id": "stripe", "name": "stripe", "title": "Stripe",
     "about": "Customers, payments and invoices in your Stripe account.",
     "kind": "http", "url": "https://mcp.stripe.com",
     "secret": {"where": "header", "key": "Authorization", "prefix": "Bearer ",
                "label": "Stripe restricted key",
                "help": "Make a restricted key in the Stripe dashboard with only what Rouh should do.",
                "link": "https://dashboard.stripe.com/apikeys"}},
    {"id": "context7", "name": "context7", "title": "Context7",
     "about": "Current documentation for programming libraries. Needs no token.",
     "kind": "http", "url": "https://mcp.context7.com/mcp", "secret": None},
]
PRESET_IDS = {p["id"]: p for p in PRESETS}


# --- Words ------------------------------------------------------------------------------------

def own_description(text: str) -> str:
    """A tool's own description, without the line `rouh/mcp.py` puts in front of it for the model."""
    text = str(text or "")
    if text.startswith("From the MCP server "):
        text = text.split(". ", 1)[1] if ". " in text else ""
    if text == "It gave no description.":
        return ""
    return text[:300]


def plain_error(exc: BaseException, server: mcp.Server | None = None) -> str:
    """Why a server would not open, in words a person can act on."""
    said = str(exc or "").strip()
    name = type(exc).__name__
    if isinstance(exc, FileNotFoundError):
        program = (server.command[0] if server and server.command else "") or "the command"
        return f"There is no program called {program} on this machine."
    if isinstance(exc, PermissionError):
        return "This machine would not let Rouh run that command."
    if isinstance(exc, asyncio.TimeoutError) or "did not answer in time" in said:
        return f"It did not answer within {int(mcp.START_TIMEOUT)} seconds."
    status = re.search(r"answered (\d{3})", said)
    if status:
        code = int(status.group(1))
        if code in (401, 403):
            return f"It refused the token (error {code}). Check that it is right and has not expired."
        if code == 404:
            return "Nothing answers at that address (error 404). Check the address."
        if code == 405:
            return "That address is not an MCP server (error 405). Check the address."
        if code >= 500:
            return f"The server had a problem of its own (error {code}). Try again later."
        return f"The server answered with error {code}."
    if "closed its output" in said or "not running" in said:
        return "The program stopped before it answered. Check the command and its arguments."
    if "did not answer with JSON" in said or "carried no answer" in said:
        return "Something answered at that address, but it does not speak MCP."
    if name in ("ConnectError", "ConnectTimeout", "gaierror"):
        return "Nothing answered at that address. Check that it is right and that the server is up."
    if name in ("ReadTimeout", "WriteTimeout", "PoolTimeout"):
        return f"It did not answer within {int(mcp.START_TIMEOUT)} seconds."
    if name in ("UnsupportedProtocol", "InvalidURL"):
        return "That is not an address Rouh can reach. It starts with https:// or http://."
    if "refused initialize" in said or "refused tools/list" in said:
        return "It refused to say what it can do: " + said.split(": ", 1)[-1][:200]
    if isinstance(exc, mcp.McpError) and said:
        return said[:240]
    return f"It could not be opened ({name}{': ' + said[:200] if said else ''})."


def _hint(value: str) -> str:
    value = str(value or "")
    return "…" + value[-4:] if len(value) > 8 else "set"


# --- From the page to a server ----------------------------------------------------------------

def _pairs(raw) -> dict:
    """[{name, value}] or {name: value} from the page, as a dict of strings, blanks left out."""
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        raw = [{"name": k, "value": v} for k, v in raw.items()]
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("name") or "").strip()
        if not key:
            continue
        if len(key) > 80 or not re.match(r"^[A-Za-z0-9_.-]+$", key):
            raise Refused(f"{key[:40]!r} cannot be a name here: letters, digits, dashes, dots and "
                          "underscores only.")
        out[key] = str(item.get("value") if item.get("value") is not None else "")
    return out


def spec_from(body: dict, old: dict | None = None) -> dict:
    """What the page sent, checked, as {name, kind, url, command, headers, env, preset}.

    `old` is the saved server being changed, as `_secrets_of` gives it: a header or environment
    value left blank keeps what was saved, so a token is never typed twice to change an address.
    """
    name = str(body.get("name") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not NAME_RE.match(name) or "__" in name:
        raise Refused("Give it a short name: lowercase letters, digits and single underscores, "
                      "starting with a letter, such as github or my_notes.")
    kind = str(body.get("kind") or "http")
    if kind not in ("http", "stdio"):
        raise Refused("Choose an address or a command.")
    preset = str(body.get("preset") or "")
    if preset and preset not in PRESET_IDS:
        preset = ""
    spec = {"name": name, "kind": kind, "url": "", "command": [], "headers": {}, "env": {},
            "preset": preset}
    if kind == "http":
        url = str(body.get("url") or "").strip()
        if not re.match(r"^https?://[^\s/]+", url, re.I):
            raise Refused("The address starts with https:// (or http:// on this machine's own network).")
        if len(url) > 500:
            raise Refused("That address is too long.")
        spec["url"] = url
        spec["headers"] = _pairs(body.get("headers"))
    else:
        command = body.get("command")
        try:
            parts = shlex.split(command) if isinstance(command, str) else [str(c) for c in command or []]
            args = body.get("args") or ""
            parts += shlex.split(args) if isinstance(args, str) else [str(a) for a in args]
        except ValueError as exc:
            raise Refused(f"The command could not be read: {exc}.") from None
        parts = [p for p in parts if p]
        if not parts:
            raise Refused("Type the command that starts the server, such as npx -y some-mcp-server.")
        spec["command"] = parts[:40]
        spec["env"] = _pairs(body.get("env"))
    if old:
        for field in ("headers", "env"):
            for key, value in list(spec[field].items()):
                if value == "" and key in (old.get(field) or {}):
                    spec[field][key] = old[field][key]
    for field in ("headers", "env"):
        spec[field] = {k: v for k, v in spec[field].items() if v != ""}
    return spec


def server_from(spec: dict) -> mcp.Server:
    return mcp.Server(name=spec["name"], command=list(spec["command"]), env=dict(spec["env"]),
                      url=spec["url"], headers=dict(spec["headers"]), inherit_env=False)


async def try_server(server: mcp.Server) -> dict:
    """Open a server, ask what it can do, and close it: {ok, tools, error}."""
    connection = mcp.Connection(server)
    try:
        tools = await asyncio.wait_for(connection.open(mcp.START_TIMEOUT), TEST_TIMEOUT)
    except asyncio.CancelledError:
        await _quietly_close(connection)
        raise
    except BaseException as exc:  # noqa: BLE001 - every failure is a sentence for the page
        await _quietly_close(connection)
        return {"ok": False, "tools": [], "error": plain_error(exc, server)}
    await _quietly_close(connection)
    return {"ok": True, "error": "",
            "tools": [{"name": mcp.plain_name(d["name"]), "description": own_description(d.get("description"))}
                      for d in tools]}


async def _quietly_close(connection) -> None:
    try:
        await asyncio.wait_for(connection.close(), 8)
    except BaseException:  # noqa: BLE001
        pass


# --- Rows -------------------------------------------------------------------------------------

def _whose(me) -> dict:
    return {"org_id": str(me.org_id), "user_id": str(me.user_id)}


def _rows(me):
    from .models import McpServer

    return list(McpServer.objects.filter(**_whose(me)).order_by("name"))


def _row(me, row_id):
    from .models import McpServer

    try:
        row_id = int(row_id)
    except (TypeError, ValueError):
        raise Refused("There is no such server.") from None
    row = McpServer.objects.filter(**_whose(me), id=row_id).first()
    if row is None:
        raise Refused("There is no such server.")
    return row


def _secrets_of(row) -> dict:
    from .encryption import box

    out = {"headers": {}, "env": {}}
    for field, sealed in (("headers", row.headers_sealed), ("env", row.env_sealed)):
        if sealed:
            try:
                out[field] = json.loads(box().open_(sealed))
            except Exception:  # noqa: BLE001 - a secret that cannot be opened is no secret
                log.warning("the sealed %s of MCP server %s could not be opened", field, row.id)
    return out


def server_of(row) -> mcp.Server:
    secrets = _secrets_of(row)
    return mcp.Server(name=row.name, command=list(row.command or []), env=secrets["env"],
                      url=row.url, headers=secrets["headers"], inherit_env=False)


def all_enabled() -> list:
    """Every enabled server anybody here connected, with what opens it, for start-up."""
    from .models import McpServer

    out = []
    for row in McpServer.objects.filter(enabled=True).order_by("id"):
        try:
            out.append((row, server_of(row)))
        except Exception:  # noqa: BLE001
            log.exception("the MCP server %s could not be read", row.id)
    return out


def note_opened(row_id: int, entry: dict) -> None:
    """What happened when a saved server was opened, on its row, for the list to say."""
    from .models import McpServer

    fields = {"checked_at": time.time(), "last_error": entry.get("error") or ""}
    if not entry.get("error"):
        fields["tools"] = entry.get("tools") or []
    McpServer.objects.filter(id=row_id).update(**fields)


def _keep(me, spec: dict, tools: list, row_id=None) -> int:
    from django.db import transaction

    from .encryption import box
    from .models import McpServer

    now = time.time()
    with transaction.atomic():
        clash = McpServer.objects.filter(**_whose(me), name=spec["name"])
        if row_id:
            clash = clash.exclude(id=row_id)
        if clash.exists():
            raise Refused(f"You already have a server called {spec['name']}. Give this one another name.")
        if not row_id and McpServer.objects.filter(**_whose(me)).count() >= MAX_SERVERS:
            raise Refused(f"That is {MAX_SERVERS} servers already. Remove one first.")
        hints = {k: _hint(v) for k, v in {**spec["headers"], **spec["env"]}.items()}
        fields = {
            "name": spec["name"], "kind": spec["kind"], "url": spec["url"], "command": spec["command"],
            "headers_sealed": box().seal(json.dumps(spec["headers"])) if spec["headers"] else "",
            "env_sealed": box().seal(json.dumps(spec["env"])) if spec["env"] else "",
            "hints": hints, "preset": spec["preset"], "tools": tools, "checked_at": now,
            "last_error": "", "updated_at": now, "enabled": True,
        }
        if row_id:
            McpServer.objects.filter(**_whose(me), id=row_id).update(**fields)
            return int(row_id)
        row = McpServer.objects.create(**_whose(me), made_at=now, ask_first=True, **fields)
        return row.id


# --- What the page is handed ------------------------------------------------------------------

def _when(at: float) -> str:
    if not at:
        return ""
    moment = clock.moment(at)
    today = clock.now().date()
    if moment.date() == today:
        return "today at " + moment.strftime("%H:%M")
    return f"{moment.day} {moment.strftime('%B')} at {moment.strftime('%H:%M')}"


def _live_state(entry: dict | None, enabled: bool) -> tuple[str, str]:
    if not enabled:
        return "off", ""
    if entry is None:
        return "waiting", ""
    if entry.get("error"):
        return "failing", entry["error"]
    return "connected", ""


def public(me, registry) -> dict:
    """The page: every server this person may see, settings first, and the presets."""
    live = dict(getattr(registry, "mcp_live", {}) or {})
    servers = []
    for key, entry in sorted(live.items()):
        if entry.get("source") != "settings":
            continue
        state, error = _live_state(entry, True)
        servers.append({
            "id": "", "name": key, "source": "settings", "kind": entry.get("kind") or "http",
            "where": "", "state": state, "error": error, "tools": entry.get("tools") or [],
            "enabled": True, "ask_first": bool(entry.get("ask_first")), "checked": _when(entry.get("at") or 0),
            "secrets": [],
        })
    for row in _rows(me):
        entry = live.get(row.name)
        if entry is not None and entry.get("source") != "saved":
            entry = None
        state, error = _live_state(entry, row.enabled)
        tools = (entry or {}).get("tools") if entry and not entry.get("error") else (row.tools or [])
        servers.append({
            "id": row.id, "name": row.name, "source": "saved", "kind": row.kind,
            "where": row.url if row.kind == "http" else " ".join(shlex.quote(p) for p in row.command or []),
            "state": state, "error": error or (row.last_error if row.enabled and state != "connected" else ""),
            "tools": tools or [], "enabled": row.enabled, "ask_first": row.ask_first,
            "checked": _when((entry or {}).get("at") or row.checked_at),
            "preset": row.preset,
            "secrets": [{"name": k, "hint": v} for k, v in sorted((row.hints or {}).items())],
        })
    return {
        "servers": servers,
        "connected": sum(1 for s in servers if s["state"] == "connected"),
        "tools": sum(len(s["tools"]) for s in servers if s["state"] == "connected"),
        "presets": [{k: v for k, v in p.items()} for p in PRESETS],
        "page": PAGE,
    }


# --- What the page does ------------------------------------------------------------------------

def _settings_names(registry) -> set:
    return {k for k, e in (getattr(registry, "mcp_live", {}) or {}).items() if e.get("source") == "settings"}


async def _spec_for(me, body: dict, registry) -> tuple[dict, int | None]:
    row_id = body.get("id") or None
    old = None
    if row_id:
        row = await asyncio.to_thread(_row, me, row_id)
        old = await asyncio.to_thread(_secrets_of, row)
        row_id = row.id
    spec = spec_from(body, old)
    if spec["name"] in _settings_names(registry):
        raise Refused(f"{spec['name']} is already a server from this Rouh's settings. Give this one "
                      "another name.")
    return spec, row_id


async def test(me, body: dict, registry) -> dict:
    """Open what was typed, list its tools, close it. Nothing is kept."""
    spec, _ = await _spec_for(me, body, registry)
    got = await try_server(server_from(spec))
    if got["ok"]:
        n = len(got["tools"])
        got["said"] = f"It works: {spec['name']} gives {n} tool{'' if n == 1 else 's'}."
    return got


async def save(me, body: dict, registry) -> dict:
    """Test it, keep it, and open it in the running Rouh. A server that fails its test is not kept."""
    spec, row_id = await _spec_for(me, body, registry)
    got = await try_server(server_from(spec))
    if not got["ok"]:
        raise Refused("Not saved. " + got["error"])
    old_name = None
    if row_id:
        old = await asyncio.to_thread(_row, me, row_id)
        old_name = old.name
    row_id = await asyncio.to_thread(_keep, me, spec, got["tools"], row_id)
    row = await asyncio.to_thread(_row, me, row_id)
    if old_name and old_name != row.name:
        await registry.mcp_detach(old_name)
    entry = await _open(row, registry)
    if entry.get("error"):
        return {"said": f"Saved {row.name}, but it would not open just now: {entry['error']}"}
    n = len(entry.get("names") or [])
    return {"said": f"Connected {row.name}. Its {n} tool{'' if n == 1 else 's'} are Rouh's now, "
                    "with no restart."}


async def _open(row, registry) -> dict:
    server = await asyncio.to_thread(server_of, row)
    entry = await registry.mcp_attach(server, source="saved", owner=(row.org_id, row.user_id),
                                      ask_first=row.ask_first, row_id=row.id)
    await asyncio.to_thread(note_opened, row.id, entry)
    return entry


async def check(me, body: dict, registry) -> dict:
    """Open a saved server again now, and say how it went."""
    row = await asyncio.to_thread(_row, me, body.get("id"))
    if not row.enabled:
        raise Refused(f"{row.name} is off. Turn it on first.")
    entry = await _open(row, registry)
    if entry.get("error"):
        return {"said": f"{row.name} is failing: {entry['error']}", "bad": True}
    n = len(entry.get("names") or [])
    return {"said": f"{row.name} is connected and gives {n} tool{'' if n == 1 else 's'}."}


async def set_enabled(me, body: dict, registry) -> dict:
    from .models import McpServer

    row = await asyncio.to_thread(_row, me, body.get("id"))
    on = bool(body.get("on"))
    await asyncio.to_thread(lambda: McpServer.objects.filter(**_whose(me), id=row.id).update(
        enabled=on, updated_at=time.time()))
    if not on:
        await registry.mcp_detach(row.name)
        return {"said": f"{row.name} is off. Its tools are out of Rouh's list until you turn it on."}
    row.enabled = True
    entry = await _open(row, registry)
    if entry.get("error"):
        return {"said": f"{row.name} is on, but failing: {entry['error']}", "bad": True}
    return {"said": f"{row.name} is on."}


async def set_ask_first(me, body: dict, registry) -> dict:
    from .models import McpServer

    row = await asyncio.to_thread(_row, me, body.get("id"))
    on = bool(body.get("on"))
    await asyncio.to_thread(lambda: McpServer.objects.filter(**_whose(me), id=row.id).update(
        ask_first=on, updated_at=time.time()))
    entry = (getattr(registry, "mcp_live", {}) or {}).get(row.name)
    if entry is not None and entry.get("source") == "saved":
        entry["ask_first"] = on
    return {"said": (f"{row.name}'s tools ask you before they run." if on
                     else f"{row.name}'s tools run without asking you first.")}


async def remove(me, body: dict, registry) -> dict:
    from .models import McpServer

    row = await asyncio.to_thread(_row, me, body.get("id"))
    await registry.mcp_detach(row.name)
    await asyncio.to_thread(lambda: McpServer.objects.filter(**_whose(me), id=row.id).delete())
    return {"said": f"Removed {row.name} and its tools."}


def attention(me, registry) -> list[str]:
    """For Anatomy's status board: each of this person's servers that is on and failing."""
    live = getattr(registry, "mcp_live", {}) or {}
    out = []
    for row in _rows(me):
        entry = live.get(row.name)
        if row.enabled and entry is not None and entry.get("source") == "saved" and entry.get("error"):
            out.append(f"The MCP server {row.name} is failing")
    for key, entry in sorted(live.items()):
        if entry.get("source") == "settings" and entry.get("error"):
            out.append(f"The MCP server {key} is failing")
    return out


def said_for_chat(me, registry) -> str:
    """What the `mcp_servers` tool says: the servers, their state, and where to connect one."""
    page = public(me, registry)
    lines = []
    for s in page["servers"]:
        where = " (from settings)" if s["source"] == "settings" else ""
        if s["state"] == "connected":
            names = ", ".join(t["name"] for t in s["tools"][:12])
            lines.append(f"- {s['name']}{where}: connected, {len(s['tools'])} tools ({names})"
                         + ("; asks first" if s["ask_first"] else ""))
        elif s["state"] == "failing":
            lines.append(f"- {s['name']}{where}: failing - {s['error']}")
        else:
            lines.append(f"- {s['name']}{where}: {s['state']}")
    head = (f"{page['connected']} MCP server{'' if page['connected'] == 1 else 's'} connected."
            if lines else "No MCP servers are connected.")
    return (head + ("\n" + "\n".join(lines) if lines else "") +
            f"\nTo connect one, the person opens Anatomy, Connections, MCP servers ({PAGE}) and presses "
            "Connect a server: a well-known one (GitHub, Linear, Notion, Stripe, Context7), an address, "
            "or a command. Tokens are typed on that page, never in a conversation.")
