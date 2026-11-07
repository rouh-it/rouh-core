"""The key proxy: the workers' only way out, and the only place their model keys are added.

Rouh's containers are two parts (98-06, task 98): the core, which holds the
person's accounts, the database and every key, and the workers, where the one
program, Claude Code, Codex and the headless browser run. Anthropic says a
container does not stop a malicious project taking "anything accessible inside
the container, including the credentials", so a worker never holds a key. It
sits on a network with no way out, and this proxy, which is on that network and
on one that does reach the internet, does two things for it:

* ``/anthropic/...`` and ``/openai/...`` are passed to Anthropic's and OpenAI's
  APIs with the installation's key added on the way, read from the keys volume
  the core writes and this proxy mounts read-only. Whatever key or token the
  worker sent is taken off first, so the only key that ever reaches those two
  companies from here is the installation's, and the worker never sees it: not
  in a file, not in its environment, not in a reply.
* GitHub, while the owner has opened a grant for it from their own machine
  (``rouh-github-grant``, deploy/grants/README.md): the owner's token sits in the
  keys volume beside its end time (``github_grant.json``), and until that time it is
  added to every request a worker sends to github.com, api.github.com,
  uploads.github.com, codeload.github.com and raw.githubusercontent.com, whatever
  credential the worker sent taken off first. The worker reaches those as plain
  http, which this proxy sends on as https: ``http://github.com/...`` through
  ``HTTP_PROXY`` (git, with ``url.http://github.com/.insteadOf https://github.com/``),
  or a request with one of those names as its ``Host`` (the gh CLI, over the socket
  ``bin/rouh-github`` keeps). At the end time the token is no longer added, and the
  file is deleted by the machine's prune (this proxy only reads the keys volume).
  With no grant open, the same requests go on with nothing added.
* Anything else is an ordinary forward proxy (``HTTPS_PROXY``): ``CONNECT`` for
  https and absolute addresses for plain http, so Claude Code's installer, its
  own sign-in, git over https, npm and web pages work, and so does the core's
  browser, whose only way out this is too (the browser container). Nothing is added to
  those, and nothing on a private, loopback or link-local address is reached,
  so the proxy cannot be used to walk into the machine or the network it runs on.

It uses the standard library only, so its image is Python and this file.

    python3 keyproxy.py            # listens on ROUH_KEYPROXY_PORT, 8080

Settings, all optional:

    ROUH_KEYPROXY_PORT        the port, 8080
    ROUH_KEYS_DIR             where the key files are, /keys
    ROUH_KEYPROXY_PORTS       ports a CONNECT may reach, "80,443"
    ROUH_KEYPROXY_ANTHROPIC   where /anthropic goes, https://api.anthropic.com
    ROUH_KEYPROXY_OPENAI      where /openai goes, https://api.openai.com
    ROUH_KEYPROXY_ALLOW_PRIVATE  hosts that may be reached although private,
                              comma separated (only a test needs one)
    ROUH_KEYPROXY_ALLOW       host:port pairs a CONNECT, or a plain-http request, may reach
                              whatever the port and wherever the host is, comma separated:
                              the owner's own servers a run works on over SSH
                              (git.example.com:22) or the browser opens, and nothing else of
                              theirs (CONTAINERS.md, runs.ssh)
    ROUH_KEYPROXY_GITHUB      where every GitHub name is sent instead of its own https address
                              (only a test needs one); the request's Host is kept

Besides ROUH_KEYPROXY_ALLOW, which is read once at the start, the keys volume may hold the
owner's timed grants, ``keyproxy_grants.json``, which the owner's machine writes
(``rouh-proxy-grant``, deploy/grants/README.md). It is read again whenever it changes, with no
restart, and a grant whose end has passed counts for nothing. Each grant is one of:

    all        any public address, on any port
    ssh        the usual ssh ports (22, 2222 ...) on any public address
    servers    the owner's own servers, by name or address, on any port (the list is in the file)
    lan        the office network and the machine itself (the file says which addresses, and
               which are the containers' own networks, which stay refused), on any port
    name       one name and every name under it (example.com, www.example.com ...), any port
    pair       one host:port, as before

Nothing but ``lan`` ever reaches an address that is not on the public internet, and ``lan``
never reaches the containers' networks, loopback or link-local addresses. Every connection a
grant let through, rather than the standing rules, is logged as ``GRANT <grant> <how>
host:port address``, with no header and no key, so the owner can see what a window was used for
(``rouh-proxy-grant log``). The older ``keyproxy_allow_timed`` (``host:port end`` a line) is still
read, as pair grants.

Every address is looked up once and the connection made to the address that was
checked, so a name cannot answer one address to the check and another to the connection.

Nothing here ever writes a key or a header to the log.
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import os
import base64
import re
import socket
import ssl
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

log = logging.getLogger("keyproxy")

KEYS_DIR = os.environ.get("ROUH_KEYS_DIR", "/keys")
PORT = int(os.environ.get("ROUH_KEYPROXY_PORT", "8080"))
PORTS = {int(p) for p in os.environ.get("ROUH_KEYPROXY_PORTS", "80,443").split(",") if p.strip()}
ALLOW_PRIVATE = {h.strip().lower() for h in os.environ.get("ROUH_KEYPROXY_ALLOW_PRIVATE", "").split(",")
                 if h.strip()}
ALLOW_PAIRS = {p.strip().lower() for p in os.environ.get("ROUH_KEYPROXY_ALLOW", "").split(",")
               if p.strip().count(":") == 1}

#: The owner's GitHub grant and the timed grants, all in the keys volume (deploy/grants/).
GITHUB_FILE = "github_grant.json"
ALLOW_TIMED_FILE = "keyproxy_allow_timed"
GRANTS_FILE = "keyproxy_grants.json"
#: Which grants file this proxy reads; rouh-grant on the machine looks for this line to know
#: whether the running proxy understands the grants it writes.
ROUH_GRANTS_FORMAT = 2
#: The ssh ports an ``ssh`` grant opens.
SSH_PORTS = {22, 222, 2022, 2222, 22022}
#: Which grant is named in the log when several would let a connection through: the narrowest.
GRANT_ORDER = ("pair", "name", "servers", "ssh", "lan", "all")
#: The names the GitHub token is added for; nowhere else, so it never reaches a page a repository
#: links to, nor the signed addresses GitHub sends a download on to.
GITHUB_HOSTS = {"github.com", "api.github.com", "uploads.github.com", "codeload.github.com",
                "raw.githubusercontent.com"}
GITHUB_UPSTREAM = os.environ.get("ROUH_KEYPROXY_GITHUB", "")
#: What the worker sent that could be a credential of its own; taken off every GitHub request.
GITHUB_STRIP = {"authorization", "cookie"}
#: A token is only ever letters, digits and these, so nothing it holds can break a header.
TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_.\-]{8,512}")

#: A request's head may be at most this long; more is refused.
HEAD_LIMIT = 64 * 1024

#: The two APIs a key is added for: the path they are reached by, where they
#: go, the file in the keys volume, and how the key is written into a request.
#: Every header in ``strip`` is taken off whatever the worker sent first.
ROUTES = {
    "/anthropic": {
        "upstream": os.environ.get("ROUH_KEYPROXY_ANTHROPIC", "https://api.anthropic.com"),
        "file": "anthropic_api_key", "name": "Anthropic",
        "header": lambda key: ("x-api-key", key),
        "strip": {"x-api-key", "authorization"},
    },
    "/openai": {
        "upstream": os.environ.get("ROUH_KEYPROXY_OPENAI", "https://api.openai.com"),
        "file": "openai_api_key", "name": "OpenAI",
        "header": lambda key: ("authorization", f"Bearer {key}"),
        "strip": {"authorization", "openai-organization", "openai-project"},
    },
}

#: Headers that belong to one hop and are never passed on.
HOP = {"connection", "keep-alive", "proxy-connection", "proxy-authorization", "proxy-authenticate",
       "te", "trailer", "upgrade", "host"}


def read_key(name: str) -> str:
    """The key in the keys volume, read afresh each time so a key added later
    works without a restart. Blank when there is none."""
    try:
        with open(os.path.join(KEYS_DIR, name), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def github_grant(now: float | None = None) -> tuple[dict | None, str]:
    """The owner's GitHub grant, read afresh on every request: (the grant, "open") until its end
    time, then (None, "ended"); (None, "none") when there is none or it is not one."""
    path = os.path.join(KEYS_DIR, GITHUB_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            grant = json.load(fh)
        token, until = str(grant["token"]).strip(), float(grant["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None, "none"
    if not TOKEN_SHAPE.fullmatch(token):
        return None, "none"
    if (time.time() if now is None else now) >= until:
        # The keys volume is read-only here, so this is a courtesy: the machine's prune deletes it.
        with contextlib.suppress(OSError):
            os.remove(path)
        return None, "ended"
    return {"token": token, "until": until, "login": str(grant.get("login") or "")}, "open"


_timed: dict = {"stamp": None, "lines": []}


def timed_pairs(now: float | None = None) -> set[str]:
    """The host:port pairs of the older timed allow list whose end has not passed. The file is
    parsed again only when it changed, so a grant added or taken away counts at the next connection."""
    path = os.path.join(KEYS_DIR, ALLOW_TIMED_FILE)
    try:
        st = os.stat(path)
    except OSError:
        return set()
    stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
    if stamp != _timed["stamp"]:
        lines = []
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read(256 * 1024)
        except OSError:
            return set()
        for line in text.splitlines():
            parts = line.split("#", 1)[0].split()
            if len(parts) < 2 or parts[0].count(":") != 1:
                continue
            try:
                lines.append((parts[0].lower(), float(parts[1])))
            except ValueError:
                continue
        _timed.update(stamp=stamp, lines=lines)
    moment = time.time() if now is None else now
    return {pair for pair, until in _timed["lines"] if until > moment}


def _nets(values) -> list:
    out = []
    for v in values or []:
        with contextlib.suppress(ValueError, TypeError):
            net = ipaddress.ip_network(str(v), strict=False)
            if net.version == 4:
                out.append(net)
    return out


def _addresses(values) -> set:
    out = set()
    for v in values or []:
        with contextlib.suppress(ValueError, TypeError):
            out.add(ipaddress.ip_address(str(v)))
    return out


_grants: dict = {"stamp": None, "data": None}


def grants_file() -> dict:
    """The owner's timed grants, parsed, read again only when the file changed: the grants (each
    with its kind and end), the servers' names and addresses, and the office network's."""
    path = os.path.join(KEYS_DIR, GRANTS_FILE)
    empty = {"grants": [], "servers": [], "lan": {"nets": [], "hosts": set(), "deny": []}}
    try:
        st = os.stat(path)
    except OSError:
        _grants.update(stamp=None, data=None)
        return empty
    stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
    if stamp == _grants["stamp"] and _grants["data"] is not None:
        return _grants["data"]
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.loads(fh.read(1024 * 1024))
    except (OSError, ValueError):
        return empty
    if not isinstance(raw, dict):
        return empty
    grants = []
    for g in raw.get("grants") or []:
        if not isinstance(g, dict) or g.get("kind") not in GRANT_ORDER:
            continue
        try:
            item = {"kind": g["kind"], "until": float(g["until"])}
            if g["kind"] == "name":
                item["name"] = str(g["name"]).strip().lower().strip(".")
                if not item["name"]:
                    continue
            elif g["kind"] == "pair":
                item["host"], item["port"] = str(g["host"]).strip().lower(), int(g["port"])
        except (KeyError, ValueError, TypeError):
            continue
        grants.append(item)
    servers = []
    for e in raw.get("servers") or []:
        if isinstance(e, dict) and e.get("name"):
            servers.append({"name": str(e["name"]).strip().lower(), "addresses": _addresses(e.get("addresses"))})
    lan = raw.get("lan") if isinstance(raw.get("lan"), dict) else {}
    data = {"grants": grants, "servers": servers,
            "lan": {"nets": _nets(lan.get("nets")), "hosts": _addresses(lan.get("hosts")),
                    "deny": _nets(lan.get("deny"))}}
    _grants.update(stamp=stamp, data=data)
    return data


def open_grants(now: float | None = None) -> tuple[list[dict], dict]:
    """The grants whose end has not passed (the older timed list's as pairs), and the file."""
    data = grants_file()
    moment = time.time() if now is None else now
    live = [g for g in data["grants"] if g["until"] > moment]
    for pair in timed_pairs(moment):
        host, _, port = pair.rpartition(":")
        with contextlib.suppress(ValueError):
            live.append({"kind": "pair", "host": host, "port": int(port), "until": moment + 1})
    return live, data


def listed(host: str, port: int) -> bool:
    """Whether host:port is one the settings list for good (ROUH_KEYPROXY_ALLOW)."""
    return f"{host.lower()}:{port}" in ALLOW_PAIRS


def lookup(host: str) -> list[str]:
    """Every address a host has, looked up once; empty when it does not resolve."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    return [info[4][0].split("%")[0] for info in infos]


def is_public(host: str, addresses: list[str]) -> bool:
    """Whether every address is on the public internet (or ALLOW_PRIVATE names the host)."""
    if host.lower() in ALLOW_PRIVATE:
        return True
    for a in addresses:
        address = ipaddress.ip_address(a)
        if not address.is_global or address.is_multicast:
            return False
    return True


def resolve(host: str, *, anywhere: bool = False) -> str | None:
    """The one address to connect to for a host, or None when it may not be reached: when it
    is, or resolves to, an address not on the public internet (unless `anywhere`, or the host
    is one ALLOW_PRIVATE names), or does not resolve at all."""
    addresses = lookup(host)
    if not addresses or not (anywhere or is_public(host, addresses)):
        return None
    return addresses[0]


def private(host: str) -> bool:
    """Whether a host is, or resolves to, an address that is not on the public internet."""
    return resolve(host) is None


def in_lan(address: str, lan: dict) -> bool:
    """Whether a ``lan`` grant reaches this address: one of the machine's own addresses, or one on
    the office network that is not on a container network. Never loopback, link-local, multicast
    or unspecified, whatever the file says: here loopback is this proxy itself."""
    try:
        a = ipaddress.ip_address(address)
    except ValueError:
        return False
    if a.version != 4 or a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified:
        return False
    if a in lan["hosts"]:
        return True
    if any(a in net for net in lan["deny"]):
        return False
    return any(a in net for net in lan["nets"])


def name_covers(name: str, host: str) -> bool:
    return host == name or host.endswith("." + name)


def decide(host: str, port: int) -> tuple[str | None, str | None, str]:
    """Whether a worker may reach host:port, and how: (the one address to connect to, the grant that
    let it through or None for the standing rules, why not). The host is looked up once here, and
    the connection is made to the very address checked."""
    host = host.strip("[]").lower()
    if listed(host, port):
        address = resolve(host, anywhere=True)
        return (address, None, "") if address else (None, None, f"{host} does not resolve")
    addresses = lookup(host)
    if not addresses:
        return None, None, "that address is not on the public internet\n" if host else "no host\n"
    address = addresses[0]
    grants, data = open_grants()
    if not is_public(host, addresses):
        if any(g["kind"] == "lan" for g in grants) and in_lan(address, data["lan"]):
            return address, "lan", ""
        if any(g["kind"] == "lan" for g in grants):
            return None, None, "that address is not on the office network, or is one of Rouh's own containers\n"
        return None, None, "that address is not on the public internet\n"
    if port in PORTS:
        return address, None, ""
    ip = ipaddress.ip_address(address)
    found = set()
    for g in grants:
        kind = g["kind"]
        if kind == "all":
            found.add("all")
        elif kind == "ssh" and port in SSH_PORTS:
            found.add("ssh")
        elif kind == "name" and name_covers(g["name"], host):
            found.add(f"name {g['name']}")
        elif kind == "pair" and g["host"] == host and g["port"] == port:
            found.add(f"pair {host}:{port}")
        elif kind == "servers":
            for e in data["servers"]:
                if e["name"] == host or ip in e["addresses"]:
                    found.add(f"servers {e['name']}")
    if not found:
        return None, None, f"port {port} is not one the workers may reach\n"
    label = min(found, key=lambda f: GRANT_ORDER.index(f.split(" ", 1)[0]))
    return address, label, ""


async def read_head(reader: asyncio.StreamReader) -> bytes:
    head = await reader.readuntil(b"\r\n\r\n")
    if len(head) > HEAD_LIMIT:
        raise ValueError("head too long")
    return head


def parse_head(head: bytes) -> tuple[str, list[tuple[str, str]]]:
    lines = head.decode("latin-1").split("\r\n")
    headers = []
    for line in lines[1:]:
        if not line:
            continue
        name, _, value = line.partition(":")
        headers.append((name.strip(), value.strip()))
    return lines[0], headers


def build_head(first: str, headers: list[tuple[str, str]]) -> bytes:
    return ("\r\n".join([first, *(f"{n}: {v}" for n, v in headers)]) + "\r\n\r\n").encode("latin-1")


async def answer(writer: asyncio.StreamWriter, status: str, body: dict | str) -> None:
    data = (json.dumps(body) if isinstance(body, dict) else body).encode()
    kind = "application/json" if isinstance(body, dict) else "text/plain"
    writer.write(f"HTTP/1.1 {status}\r\nContent-Type: {kind}\r\nContent-Length: {len(data)}\r\n"
                 f"Connection: close\r\n\r\n".encode() + data)
    with contextlib.suppress(Exception):
        await writer.drain()


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            if writer.can_write_eof():
                writer.write_eof()


async def splice(a_reader, a_writer, b_reader, b_writer) -> None:
    """Both ways at once, until both sides are done."""
    await asyncio.gather(pipe(a_reader, b_writer), pipe(b_reader, a_writer))
    for w in (a_writer, b_writer):
        with contextlib.suppress(Exception):
            w.close()


async def tunnel(reader, writer, target: str) -> None:
    """``CONNECT host:port``: a plain tunnel to a public address, nothing added."""
    host, _, port_text = target.rpartition(":")
    host = host.strip("[]")
    try:
        port = int(port_text)
    except ValueError:
        return await answer(writer, "400 Bad Request", "not host:port\n")
    address, grant, why = await asyncio.to_thread(decide, host, port)
    if address is None:
        return await answer(writer, "403 Forbidden", why)
    if grant:
        log.info("GRANT %s CONNECT %s:%d %s", grant, host.lower(), port, address)
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(address, port), 20)
    except (OSError, asyncio.TimeoutError):
        return await answer(writer, "502 Bad Gateway", f"could not reach {host}:{port}\n")
    writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await writer.drain()
    await splice(reader, writer, up_reader, up_writer)


async def forward_plain(reader, writer, first: str, headers, url: str) -> None:
    """A plain-http request in absolute form: passed on as it is, nothing added."""
    parts = urlsplit(url)
    host, port = parts.hostname or "", parts.port or 80
    # A server the settings or a grant open is reached over plain http as over CONNECT: the
    # browser asks for an http page this way, never with CONNECT.
    if parts.scheme != "http":
        return await answer(writer, "403 Forbidden", "not a port the workers may reach\n")
    address, grant, why = await asyncio.to_thread(decide, host, port)
    if address is None:
        return await answer(writer, "403 Forbidden", why)
    if grant:
        log.info("GRANT %s HTTP %s:%d %s", grant, host.lower(), port, address)
    method, _, version = first.split(" ", 2)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    kept = [(n, v) for n, v in headers if n.lower() not in HOP]
    kept += [("Host", parts.netloc), ("Connection", "close")]
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(address, port), 20)
    except (OSError, asyncio.TimeoutError):
        return await answer(writer, "502 Bad Gateway", f"could not reach {host}:{port}\n")
    up_writer.write(build_head(f"{method} {path} {version}", kept))
    await up_writer.drain()
    await splice(reader, writer, up_reader, up_writer)


async def with_key(reader, writer, first: str, headers, prefix: str, route: dict) -> None:
    """``/anthropic/...`` or ``/openai/...``: to that company's API, with the key added."""
    key = read_key(route["file"])
    if not key:
        return await answer(writer, "503 Service Unavailable", {
            "type": "error", "error": {"type": "no_key",
                                       "message": f"No {route['name']} key has been added to Rouh yet."}})
    method, target, version = first.split(" ", 2)
    upstream = urlsplit(route["upstream"])
    path = (upstream.path.rstrip("/") + target[len(prefix):]) or "/"
    if not path.startswith("/"):
        path = "/" + path
    kept = [(n, v) for n, v in headers if n.lower() not in HOP and n.lower() not in route["strip"]]
    kept += [("Host", upstream.netloc), route["header"](key), ("Connection", "close")]
    secure = upstream.scheme == "https"
    await relay(reader, writer, build_head(f"{method} {path} {version}", kept), upstream.hostname,
                upstream.port or (443 if secure else 80), secure, route["name"])


async def relay(reader, writer, head: bytes, host: str, port: int, secure: bool, name: str,
                note: tuple[str, str] | None = None) -> None:
    """One request, its head already made, to host:port, and its answer back with
    Connection: close (and `note`, a header of this proxy's own, when given)."""
    try:
        up_reader, up_writer = await asyncio.wait_for(asyncio.open_connection(
            host, port, ssl=ssl.create_default_context() if secure else None,
            server_hostname=host if secure else None), 20)
    except (OSError, asyncio.TimeoutError, ssl.SSLError):
        return await answer(writer, "502 Bad Gateway", {
            "type": "error", "error": {"type": "unreachable", "message": f"Could not reach {name}."}})
    up_writer.write(head)
    await up_writer.drain()
    # The answer's head is read so it can say Connection: close: a client that
    # kept the connection for a second request would send it to a socket this
    # proxy has already handed back.
    body = asyncio.create_task(pipe(reader, up_writer))
    try:
        while True:
            reply_first, reply_headers = parse_head(await read_head(up_reader))
            # "100 Continue" and its kind go back as they came, and the real answer follows.
            code = (reply_first.split(" ") + [""])[1]
            if len(code) == 3 and code.startswith("1") and code != "101":
                writer.write(build_head(reply_first, reply_headers))
                await writer.drain()
                continue
            break
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ValueError, ConnectionError):
        body.cancel()
        return await answer(writer, "502 Bad Gateway", "the API closed the connection\n")
    reply_headers = [(n, v) for n, v in reply_headers if n.lower() not in ("connection", "keep-alive")]
    if note:
        reply_headers.append(note)
    writer.write(build_head(reply_first, reply_headers + [("Connection", "close")]))
    await writer.drain()
    await pipe(up_reader, writer)
    body.cancel()
    for w in (writer, up_writer):
        with contextlib.suppress(Exception):
            w.close()


def github_credential(host: str, token: str) -> tuple[str, str]:
    """git over https takes the token as a password; the API and the rest take it as a bearer."""
    if host == "github.com":
        pair = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return "Authorization", f"Basic {pair}"
    return "Authorization", f"Bearer {token}"


async def github(reader, writer, method: str, host: str, path: str, version: str, headers) -> None:
    """A worker's request to one of GitHub's names, sent on over https with the owner's token
    added while a grant is open. Whatever credential the worker sent is taken off first, always."""
    grant, state = github_grant()
    kept = [(n, v) for n, v in headers if n.lower() not in HOP and n.lower() not in GITHUB_STRIP]
    kept.append(("Host", host))
    if grant:
        kept.append(github_credential(host, grant["token"]))
        when = datetime.fromtimestamp(grant["until"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        note = ("X-Rouh-GitHub-Grant", f"open until {when}" + (f" as {grant['login']}" if grant["login"] else ""))
    else:
        note = ("X-Rouh-GitHub-Grant", state)
    kept.append(("Connection", "close"))
    log.info("%s GitHub %s%s (grant %s)", method, host, urlsplit(path).path, state)
    if GITHUB_UPSTREAM:
        up = urlsplit(GITHUB_UPSTREAM)
        secure = up.scheme == "https"
        return await relay(reader, writer, build_head(f"{method} {path} {version}", kept), up.hostname,
                           up.port or (443 if secure else 80), secure, "GitHub", note)
    await relay(reader, writer, build_head(f"{method} {path} {version}", kept), host, 443, True, "GitHub", note)


def host_name(value: str) -> str:
    """A Host header's name, without its port, in small letters."""
    value = value.strip().lower()
    if value.startswith("["):
        return value.split("]", 1)[0] + "]"
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        try:
            first, headers = parse_head(await asyncio.wait_for(read_head(reader), 30))
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError,
                ValueError, ConnectionError):
            return
        parts = first.split(" ")
        if len(parts) != 3:
            return await answer(writer, "400 Bad Request", "not an HTTP request\n")
        method, target, _ = parts
        if method == "CONNECT":
            log.info("CONNECT %s", target)
            return await tunnel(reader, writer, target)
        if target.startswith("http://"):
            parts = urlsplit(target)
            if (parts.hostname or "").lower() in GITHUB_HOSTS and (parts.port or 80) == 80:
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                return await github(reader, writer, method, parts.hostname.lower(), path,
                                    first.split(" ", 2)[2], headers)
            log.info("%s %s", method, parts.netloc)
            return await forward_plain(reader, writer, first, headers, target)
        asked = host_name(next((v for n, v in headers if n.lower() == "host"), ""))
        if target.startswith("/") and asked in GITHUB_HOSTS:
            return await github(reader, writer, method, asked, target, first.split(" ", 2)[2], headers)
        if target in ("/health", "/healthz"):
            return await answer(writer, "200 OK", "ok\n")
        for prefix, route in ROUTES.items():
            if target == prefix or target.startswith(prefix + "/"):
                log.info("%s %s%s", method, route["name"], urlsplit(target).path[len(prefix):])
                return await with_key(reader, writer, first, headers, prefix, route)
        return await answer(writer, "404 Not Found", "not a path this proxy serves\n")
    except Exception:
        log.exception("a request failed")
    finally:
        with contextlib.suppress(Exception):
            writer.close()


async def main() -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, limit=HEAD_LIMIT * 2)
    log.info("key proxy listening on %d; keys from %s", PORT, KEYS_DIR)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("ROUH_KEYPROXY_LOG", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
