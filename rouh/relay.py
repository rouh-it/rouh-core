"""Reaching a Rouh from a phone: its own address on the relay's domain, locked end to end.

A Rouh runs on its owner's computer, where a phone outside the house cannot reach it. A
Connected Rouh (the first run's "Connected · free · recommended", `rouh/web/firstrun.py`) is
given an address of its own, ``<its-name>.<the relay's domain>``, by the birth service's relay:

1. **The claim, at birth.** Right after the owner chooses Connected, the Rouh asks the claim
   endpoint (``ROUH_RELAY_URL`` + ``claim``) for its name's address, signed with its daily key
   the way the Gene Pool's requests are (`genepool._sign`), with its birth statement so the
   service can work its name out of its birth key (`rouh/names`). It gets back its hostname and
   its credentials for the relay. An "On its own" Rouh claims nothing and opens nothing.
2. **Open from birth.** Petar, 8 November 2026: "the relay should be working immediately at the
   registration." So the moment the claim is granted the address is on (`open_by_itself`): the
   Rouh starts frp's client, ``frpc``, which keeps one line open to the relay and reconnects by
   itself whenever the relay or the network goes away, and gets its certificate. Until 8 November
   it waited for the owner to press "Reach me from my phone", so a newborn Rouh showed an address
   that answered nothing (ERR_SSL_UNRECOGNIZED_NAME_ALERT: the relay had no route for the name).
   The owner can still turn it off (Settings, Connections, Phone), and off stays off.
3. **The relay never sees plain text.** Two ways in come through that line, both for this name
   only: HTTPS, which the relay routes by the name in the TLS hello and passes on still locked,
   unlocked here by frpc with this Rouh's own certificate and handed to Rouh's web server; and
   plain HTTP on port 80, which answers Let's Encrypt's HTTP-01 check and sends everything else
   to HTTPS. The certificate is Let's Encrypt's, got and renewed by this Rouh (`rouh/acme.py`).
4. **What is never reachable from outside.** frpc marks every request it hands over (a header it
   sets over anything the visitor sent, `MARK_HEADER`, and the visitor's address in the
   forwarding headers), so a request that came through the relay is never "from this machine"
   (`common.from_this_machine`), and the first-run pages and their setup code (`/setup...`) and
   the internal addresses answer 404 to it (`local_only`). The owner, who has no password, signs
   in on the phone with a one-time code shown as a QR code on the computer (`signin_link`).

Everything that names a service is a setting, so an installation can have a relay of its own:
``ROUH_RELAY_URL`` (the claim endpoint's folder), ``ROUH_RELAY_DOMAIN`` (only shown before the
claim answers; the claim's hostname is the truth), ``ROUH_RELAY=0`` (no relay at all),
``ROUH_FRPC`` (the frpc binary), ``ROUH_ACME_DIRECTORY`` and, for tests, ``ROUH_ACME_CA_BUNDLE``
and ``ROUH_RELAY_CHECK_CA``.

The relay's own side (frps, its Login and NewProxy checks, the claim endpoint, the traffic
counts) is the service's and not in this repository; `PROTOCOL.md`, "The relay: a Rouh's phone
address", is the wire between the two.
"""
from __future__ import annotations

from . import site as _site

import asyncio
import base64
import contextlib
import hashlib
import hmac
import io
import json
import logging
import os
import platform
import secrets
import shutil
import socket
import tarfile
import tempfile
import threading
import time
from urllib.parse import urljoin, urlsplit

log = logging.getLogger("rouh.relay")

#: Made from ROUH_SITE_URL, the one setting for Rouh's public site (`rouh/site.py`, task 165).
DEFAULT_URL = _site.url("/relay/")
DEFAULT_DOMAIN = "rouh.page"
#: The frp release this Rouh runs, and each build's tarball by its sha256 (the release's own
#: frp_sha256_checksums.txt). Dockerfile.base installs the same one.
FRP_VERSION = "0.71.1"
FRP_SHA256 = {
    "linux_amd64": "1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803",
    "linux_arm64": "8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019",
    "darwin_amd64": "8acb59b6fb998cc8d209d1373d90bf70fa5ec3efeb4dfbc7bda6ce3abd78cb45",
    "darwin_arm64": "d15d0324b99e14619c9aa46e37f6db588c06a09be4bc6f7948890b6b61077842",
}
FRP_DOWNLOAD = "https://github.com/fatedier/frp/releases/download/v{v}/frp_{v}_{build}.tar.gz"
#: The header frpc sets on every request it hands to Rouh, over anything a visitor sent.
MARK_HEADER = "x-rouh-relay"
#: Addresses a request through the relay never reaches.
LOCAL_ONLY = ("/setup", "/internal/")
TIMEOUT = 20.0
#: How long a sign-in code shown as a QR code lasts.
SIGNIN_SECONDS = 600
SIGNIN_PATH = "/phone/in"
CHALLENGE_PATH = "/.well-known/acme-challenge/"
#: How often the supervisor looks at frpc, and checks the address from outside.
LOOK_EVERY = 3.0
CHECK_EVERY = 600.0
USAGE_EVERY = 1800.0
RENEW_LOOK_EVERY = 6 * 3600.0


class Refused(ValueError):
    """Something the relay, or this Rouh, will not do, with the reason in words."""


# --- settings ------------------------------------------------------------------------------------


def enabled() -> bool:
    return os.environ.get("ROUH_RELAY", "").strip().lower() not in ("0", "false", "no", "off")


def service_url() -> str:
    url = os.environ.get("ROUH_RELAY_URL", "").strip() or DEFAULT_URL
    return url if url.endswith("/") else url + "/"


def domain() -> str:
    return (os.environ.get("ROUH_RELAY_DOMAIN", "").strip().lower() or DEFAULT_DOMAIN).strip(".")


def label_for(name: str) -> str:
    """The address's first part, as the relay gives it by default: "Still Heron" -> still-heron."""
    return "-".join("".join(c for c in w.lower() if c.isalnum()) for w in str(name).split() if w)


# --- the state, kept in the data folder ----------------------------------------------------------

_LOCK = threading.RLock()


def folder() -> str:
    from .config import config

    path = os.path.join(config.data_dir, "relay")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def _state_file() -> str:
    return os.path.join(folder(), "state.json")


_READ: dict = {"at": None, "held": {}}


def read() -> dict:
    """The state, read again only when the file changed: every request asks `through`."""
    path = _state_file()
    try:
        at = os.stat(path).st_mtime_ns
    except OSError:
        return {}
    if _READ["at"] == at:
        return dict(_READ["held"])
    try:
        with open(path, encoding="utf-8") as fh:
            held = json.load(fh)
    except (OSError, ValueError):
        return {}
    held = held if isinstance(held, dict) else {}
    _READ.update(at=at, held=held)
    return dict(held)


def _write(held: dict) -> None:
    path = _state_file()
    fd, tmp = tempfile.mkstemp(prefix=".state.", dir=os.path.dirname(path))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(held, fh, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _change(**changes) -> dict:
    with _LOCK:
        held = read()
        for k, v in changes.items():
            if v is None:
                held.pop(k, None)
            else:
                held[k] = v
        _write(held)
        return held


def _box():
    from .encryption import box

    return box()


def _open(held: dict, key: str) -> str:
    sealed = held.get(key) or ""
    return _box().open_(sealed) if sealed else ""


def hostname() -> str:
    return str(read().get("hostname") or "")


def hostnames(held: dict | None = None) -> list[str]:
    """Every name this Rouh answers on: its born one, then the one its owner chose, if any (task 140,
    step 140-13). The born name is kept for good, so links and phones signed in on it never break."""
    held = read() if held is None else held
    names = [str(held.get("hostname") or "")] + [str(a) for a in held.get("aliases") or []]
    return [n for i, n in enumerate(names) if n and n not in names[:i]]


def preferred_address(held: dict | None = None) -> str:
    """The address to show and open: the chosen one once its certificate covers it, else the born one."""
    held = read() if held is None else held
    base = address(held)
    chosen = str(held.get("chosen") or "")
    if not base or not chosen or chosen not in _cert_names(held):
        return base
    port = int(held.get("https_port") or 443)
    return f"https://{chosen}" + ("" if port == 443 else f":{port}")


def address(held: dict | None = None) -> str:
    """The whole address, https and the port when it is not 443; "" before the claim."""
    held = read() if held is None else held
    host = held.get("hostname") or ""
    if not host:
        return ""
    port = int(held.get("https_port") or 443)
    return f"https://{host}" + ("" if port == 443 else f":{port}")


def allow_host(host: str = "") -> None:
    """Let Django answer on the claimed name. ALLOWED_HOSTS is one list, which the socket's origin
    check holds too (`project/asgi.py`), so it is added to in place."""
    from django.conf import settings

    allowed = settings.ALLOWED_HOSTS
    for name in ([host] if host else hostnames()):
        name = name.lower()
        if name and isinstance(allowed, list) and name not in allowed:
            allowed.append(name)


# --- requests through the relay ------------------------------------------------------------------


def through(request) -> bool:
    """Whether this request came in through the relay: frpc's mark, or the claimed name."""
    held = read()
    mark = held.get("mark") or ""
    given = request.headers.get(MARK_HEADER, "")
    if given and mark and hmac.compare_digest(given.encode(), mark.encode()):
        return True
    names = hostnames(held)
    if not names:
        return False
    asked = (request.headers.get("host") or "").split(":")[0].strip().lower()
    return asked in names


def local_only(path: str) -> bool:
    return path == "/setup" or any(path.startswith(p) for p in LOCAL_ONLY)


# --- who the Rouh is ----------------------------------------------------------------------------


def owner():
    from .web import firstrun

    return firstrun.the_owner()


def chose_connected(user=None) -> bool | None:
    """The owner's choice on the first run: True Connected, False On its own, None never asked."""
    from .web import firstrun

    user = user or owner()
    if user is None:
        return None
    held = firstrun.record(user)
    if "connected" not in held:
        return None
    return bool(held.get("connected"))


def linked_later(user=None, *, claim: bool = True) -> None:
    """A Rouh born before its first run asked, now linked to its owner's rouh.land account with the
    code rouh.land gave them (Birthday, `/api/birth/connect`): that is its owner choosing Connected,
    so the choice is kept and its address asked for, as the first run does (`firstrun._choose`).
    Its name stays the one it was born with; an On its own choice is left as it is."""
    from .web import firstrun

    if not enabled():
        return
    user = user or owner()
    if user is None:
        return
    choice = chose_connected(user)
    if choice is False:
        return
    if choice is None:
        # An owner who never had a first run is kept as one who finished it: a record with no
        # done_at is a first run part way through, which sends them back to its screens.
        never = not firstrun.record(user)
        firstrun._save(user, connected=True, chose_at=time.time(), chose_later=True,
                       **({"done_at": time.time()} if never else {}))
        log.info("relay: linked to rouh.land after birth, so Connected")
    if claim and not hostname():
        claim_soon(user)
    else:
        open_by_itself(user)


def in_account() -> bool:
    """Whether this Rouh's registration on rouh.land is in its owner's account there."""
    from . import birth

    user = owner()
    row = birth.current(str(user.org_id)) if user is not None else None
    return bool(row is not None and row.registry_id and birth._in_account(row))


def _identity(user):
    from . import birth

    me = birth.identity(str(user.org_id))
    if me is None:
        raise Refused("This Rouh is not born yet, so it has no name to ask an address for.")
    row = birth.current(str(user.org_id))
    return me, row


def _version() -> str:
    try:
        from .version import BUILD

        return str(BUILD)
    except Exception:  # noqa: BLE001 - only a label
        return ""


def _signed(seed: bytes, method: str, url: str, body: bytes) -> dict:
    from . import genepool

    return genepool._sign(seed, method, urlsplit(url).path, body)


def _said(got) -> str:
    try:
        said = (got.json() or {}).get("error") or ""
    except ValueError:
        said = ""
    return " ".join(str(said).split())[:300]


# --- 1. the claim --------------------------------------------------------------------------------


def claim(user=None, *, rotate: bool = False) -> dict:
    """Ask the relay for this Rouh's address and its credentials; kept here, the secrets sealed."""
    import httpx

    if not enabled():
        raise Refused("This installation has no relay (ROUH_RELAY=0).")
    user = user or owner()
    if user is None:
        raise Refused("This Rouh has no owner yet.")
    if chose_connected(user) is False:
        raise Refused("This Rouh is on its own: it asks nobody for an address.")
    me, row = _identity(user)
    url = urljoin(service_url(), "claim")
    payload = {"v": 1, "public_key": me["public"], "name": me["name"], "tag": me["tag"],
               "birth": row.birth_statement, "changes": row.key_changes or [],
               "owner_email": (user.email or "").strip(), "rouh_version": _version()}
    if rotate:
        payload["rotate"] = True
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Rouh relay",
               **_signed(me["seed"], "POST", url, body)}
    try:
        got = httpx.post(url, content=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        _change(claim_error=f"{urlsplit(url).hostname} could not be reached ({type(exc).__name__}).",
                claim_tried_at=time.time())
        raise Refused(f"The relay at {urlsplit(url).hostname} could not be reached. It is asked again by itself.") from None
    if got.status_code >= 400:
        said = _said(got) or f"it answered {got.status_code}"
        _change(claim_error=said, claim_tried_at=time.time())
        raise Refused(f"The relay said no: {said}")
    try:
        answer = got.json()
    except ValueError:
        answer = {}
    state = answer.get("state")
    if state == "pending":
        said = " ".join(str(answer.get("said") or "The relay has not given the address yet.").split())[:300]
        _change(pending={"said": said, "retry_after": int(answer.get("retry_after") or 60), "at": time.time()},
                claim_error=None, claim_tried_at=time.time())
        return {"state": "pending", "said": said}
    relay = answer.get("relay") or {}
    host = str(answer.get("hostname") or "").strip().lower().rstrip(".")
    user_name = str(relay.get("user") or relay.get("label") or "")
    # The pass frps's Login and NewProxy checks hold this Rouh to (metadatas.token).
    token = str(relay.get("token") or relay.get("pass") or relay.get("secret") or "")
    needed = (host, relay.get("server_addr"), relay.get("server_port"), user_name, token)
    if state != "granted" or not all(needed):
        _change(claim_error="the relay's answer was not one this Rouh understands", claim_tried_at=time.time())
        raise Refused("The relay's answer was not one this Rouh understands, so nothing was kept.")
    chosen = str(answer.get("chosen") or "").strip().lower().rstrip(".")
    aliases = [str(a).strip().lower().rstrip(".") for a in answer.get("aliases") or [] if str(a).strip()]
    held = _change(
        hostname=host, https_port=int(answer.get("https_port") or 443),
        chosen=chosen or None, aliases=[a for a in aliases if a != host] or None,
        server_addr=str(relay["server_addr"]), server_port=int(relay["server_port"]), user=user_name,
        server_name=str(relay.get("server_name") or "") or None, ca=str(relay.get("ca") or "") or None,
        auth_token=_box().seal(str(relay.get("auth_token") or "")), secret=_box().seal(token),
        limit_bytes=int(answer.get("limit_bytes") or 0) or None, usage_url=str(answer.get("usage_url") or "") or None,
        public_key=me["public"], claimed_at=time.time(), pending=None, claim_error=None,
        mark=read().get("mark") or secrets.token_urlsafe(24))
    allow_host()
    log.info("relay: %s claimed %s", me["name"], host)
    try:
        open_by_itself(user)
    except Exception:  # noqa: BLE001 - opened again at the next start
        log.exception("relay: the address could not be opened after the claim")
    return {"state": "granted", "address": address(held)}


# --- 1b. a name of the owner's own (task 140, step 140-13) -----------------------------------------

#: The shape rouh.land takes; rouh.land is the judge of everything else (taken, kept, brand names).
NAME_SHAPE = "Use 3 to 30 letters, digits or dashes."


def plain_name(text: str) -> str:
    """What the owner typed, as an address's first part: "Petar P" -> petar-p; a whole address
    typed (petar.rouh.page) is cut to its first part."""
    text = str(text or "").strip().lower()
    if text.endswith("." + domain()):
        text = text[: -len(domain()) - 1]
    text = text.replace("_", "-").replace(" ", "-")
    return "".join(c for c in text if c.isalnum() or c == "-")[:40]


def _shape_problem(name: str) -> str:
    import re

    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])", name or "") or "--" in name or name.isdigit():
        return NAME_SHAPE
    return ""


def name_free(text: str) -> dict:
    """Whether a name is free on the relay's domain, as rouh.land says; this Rouh's own chosen
    name is "yours". Only a Connected Rouh asks (the API checks before calling)."""
    import httpx

    name = plain_name(text)
    held = read()
    out = {"name": name, "address": f"{name}.{domain()}" if name else ""}
    bad = _shape_problem(name)
    if bad:
        return {**out, "available": False, "why": bad}
    if f"{name}.{domain()}" in (held.get("chosen") or "", held.get("hostname") or ""):
        return {**out, "available": True, "yours": True, "why": ""}
    url = urljoin(service_url(), "name")
    try:
        got = httpx.get(url, params={"name": name}, timeout=TIMEOUT,
                        headers={"Accept": "application/json", "User-Agent": "Rouh relay"})
    except httpx.HTTPError as exc:
        raise Refused(f"{urlsplit(url).hostname} could not be reached ({type(exc).__name__}). Try again in a moment.") from None
    if got.status_code >= 400:
        raise Refused(_said(got) or f"{urlsplit(url).hostname} answered {got.status_code}.")
    try:
        answer = got.json() or {}
    except ValueError:
        answer = {}
    return {**out, "available": bool(answer.get("available")), "why": str(answer.get("why") or "")}


def _signed_post(rest: str, payload: dict, user=None):
    """A request to the relay's service signed with this Rouh's daily key, as the claim is."""
    import httpx

    user = user or owner()
    if user is None:
        raise Refused("This Rouh has no owner yet.")
    if chose_connected(user) is not True:
        raise Refused("This Rouh is on its own: it asks nobody for anything.")
    me, _row = _identity(user)
    url = urljoin(service_url(), rest)
    body = json.dumps({"v": 1, "public_key": me["public"], **payload}, separators=(",", ":"),
                      sort_keys=True).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Rouh relay",
               **_signed(me["seed"], "POST", url, body)}
    try:
        got = httpx.post(url, content=body, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise Refused(f"{urlsplit(url).hostname} could not be reached ({type(exc).__name__}). Try again in a moment.") from None
    if got.status_code >= 400:
        raise Refused(_said(got) or f"{urlsplit(url).hostname} answered {got.status_code}.")
    try:
        return got.json() or {}
    except ValueError:
        return {}


def choose_name(text: str, user=None) -> dict:
    """Take a name of the owner's own (petar.rouh.page) beside the born one, or give it back with
    "". rouh.land checks and keeps it; this Rouh then answers on both, gets one certificate for
    both, and opens the chosen one from then on. The born name keeps working for good."""
    name = plain_name(text)
    if name:
        bad = _shape_problem(name)
        if bad:
            raise Refused(bad)
    answer = _signed_post("name", {"name": name}, user)
    chosen = str(answer.get("chosen") or "").strip().lower().rstrip(".")
    aliases = [str(a).strip().lower().rstrip(".") for a in answer.get("aliases") or [] if str(a).strip()]
    host = read().get("hostname") or str(answer.get("hostname") or "").strip().lower()
    _change(chosen=chosen or None, aliases=[a for a in aliases if a != host] or None, chosen_at=time.time())
    allow_host()
    SUPERVISOR.restart_wanted = True
    SUPERVISOR.cert_now = True
    log.info("relay: the owner's own address is now %s", chosen or "none (the born one only)")
    with contextlib.suppress(Exception):
        open_by_itself(user)
    return {"chosen": chosen, "addresses": hostnames()}


def address_letter(user=None) -> dict:
    """Email it to me: rouh.land emails the owner's account this Rouh's addresses."""
    answer = _signed_post("address-letter", {}, user)
    return {"sent_to": str(answer.get("sent_to") or "")}


def open_by_itself(user=None) -> bool:
    """A Connected Rouh's address is on from birth, unless its owner turned it off: on, and frpc
    started (the supervisor claims again by itself if the claim at birth did not get through).
    "on" missing means nobody ever chose; Turn off writes False, which is kept."""
    if not enabled():
        return False
    held = read()
    if "on" not in held:
        if chose_connected(user) is not True:
            return False
        held = _change(on=True, on_at=time.time(), on_by="birth",
                       mark=held.get("mark") or secrets.token_urlsafe(24))
        log.info("relay: the address is on from birth")
    if held.get("on"):
        _wake()
    return bool(held.get("on"))


#: Rouh's own event loop, kept by `start`, so a thread (the claim at birth) can start the supervisor.
_LOOP: asyncio.AbstractEventLoop | None = None


def _wake() -> None:
    loop = _LOOP
    if loop is None or loop.is_closed():
        return
    try:
        if asyncio.get_running_loop() is loop:
            SUPERVISOR.start()
            return
    except RuntimeError:
        pass
    loop.call_soon_threadsafe(SUPERVISOR.start)


def claim_soon(user) -> None:
    """The claim at birth, in a thread of its own, so the first run's screens never wait for it;
    then the address is opened, granted or not (the supervisor asks again until it is)."""
    def go():
        try:
            claim(user)
        except Refused as exc:
            log.info("relay: no address at birth yet: %s", exc)
        except Exception:  # noqa: BLE001 - asked again by the supervisor or the Settings page
            log.exception("relay: the claim at birth failed")
        try:
            open_by_itself(user)
        except Exception:  # noqa: BLE001 - tried again at the next start
            log.exception("relay: the address could not be opened at birth")
        finally:
            from django.db import connection

            connection.close()

    global _CLAIMING
    _CLAIMING = threading.Thread(target=go, name="relay-claim", daemon=True)
    _CLAIMING.start()


_CLAIMING: threading.Thread | None = None


def claim_waited(most: float) -> None:
    """Wait up to ``most`` seconds for the claim at birth, if one is on its way."""
    thread = _CLAIMING
    if thread is not None and thread.is_alive():
        thread.join(most)


def usage() -> dict | None:
    """This month's traffic as the relay counts it, or None when it says nothing."""
    import httpx

    held = read()
    url = held.get("usage_url") or ""
    user = owner()
    if not url or user is None:
        return None
    try:
        me, _ = _identity(user)
    except Refused:
        return None
    headers = {"Accept": "application/json", "User-Agent": "Rouh relay", "X-Rouh-Key": me["public"],
               **_signed(me["seed"], "GET", url, b"")}
    try:
        got = httpx.get(url, headers=headers, timeout=TIMEOUT)
        answer = got.json() if got.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        answer = None
    if not isinstance(answer, dict) or "bytes" not in answer:
        return None
    out = {"month": str(answer.get("month") or ""), "bytes": int(answer.get("bytes") or 0),
           "limit_bytes": int(answer.get("limit_bytes") or held.get("limit_bytes") or 0),
           "slowed": bool(answer.get("slowed")), "at": time.time()}
    _change(usage=out)
    return out


# --- the client, frpc ----------------------------------------------------------------------------


def _build() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}.get(machine, machine)
    return f"{system}_{arch}"


def frpc_path() -> str:
    """frpc: the setting, the one on the PATH (the base image has it), or the pinned release
    fetched once into the data folder and checked against its sha256."""
    named = os.environ.get("ROUH_FRPC", "").strip()
    if named:
        return named
    found = shutil.which("frpc")
    if found:
        return found
    build = _build()
    want = FRP_SHA256.get(build)
    if not want:
        raise Refused(f"There is no frp client for this machine ({build}).")
    target = os.path.join(folder(), "bin", f"frpc-{FRP_VERSION}")
    if os.path.exists(target):
        return target
    import httpx

    url = FRP_DOWNLOAD.format(v=FRP_VERSION, build=build)
    try:
        got = httpx.get(url, follow_redirects=True, timeout=120.0)
        got.raise_for_status()
    except httpx.HTTPError as exc:
        raise Refused(f"The frp client could not be fetched ({type(exc).__name__}).") from None
    if hashlib.sha256(got.content).hexdigest() != want:
        raise Refused("The frp client that came was not the one this Rouh pins, so it was not used.")
    with tarfile.open(fileobj=io.BytesIO(got.content), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.isfile() and m.name.endswith("/frpc")), None)
        if member is None:
            raise Refused("The frp release had no client in it.")
        data = tar.extractfile(member).read()
    os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target))
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.chmod(tmp, 0o700)
    os.replace(tmp, target)
    log.info("relay: frpc %s fetched for %s", FRP_VERSION, build)
    return target


def _tls_dir() -> str:
    path = os.path.join(folder(), "tls")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def cert_paths() -> tuple[str, str]:
    d = _tls_dir()
    return os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")


def _cert_names(held: dict) -> list[str]:
    """The names the certificate on disk was got for ("a,b" since step 140-13, one name before)."""
    return [n for n in str(held.get("cert_for") or "").split(",") if n]


def has_cert(held: dict | None = None) -> bool:
    """A certificate for the born name is here (the chosen one may still be on its way)."""
    held = read() if held is None else held
    cert, key = cert_paths()
    return bool(held.get("hostname") and held.get("hostname") in _cert_names(held)
                and os.path.exists(cert) and os.path.exists(key))


def cert_covers_all(held: dict | None = None) -> bool:
    held = read() if held is None else held
    return has_cert(held) and set(hostnames(held)) <= set(_cert_names(held))


def _toml(value: str) -> str:
    return json.dumps(str(value))


def frpc_config(held: dict, admin_port: int, local: str) -> str:
    """frpc's settings for this Rouh. The token, the secret and the admin password are read from
    frpc's own environment, so none of them is ever written to a file."""
    names = hostnames(held)
    mark = held["mark"]
    # The https side only for names the certificate covers; port 80 for all, for the HTTP-01 check.
    locked = [n for n in names if n in _cert_names(held)]
    lines = [
        f"serverAddr = {_toml(held['server_addr'])}",
        f"serverPort = {int(held['server_port'])}",
        f"user = {_toml(held['user'])}",
        "loginFailExit = false",
        'auth.method = "token"',
        'auth.token = "{{ .Envs.ROUH_FRP_TOKEN }}"',
        'metadatas.token = "{{ .Envs.ROUH_FRP_SECRET }}"',
        "transport.tls.enable = true",
        "transport.heartbeatInterval = 30",
        "transport.heartbeatTimeout = 90",
        'webServer.addr = "127.0.0.1"',
        f"webServer.port = {admin_port}",
        'webServer.user = "rouh"',
        'webServer.password = "{{ .Envs.ROUH_FRP_ADMIN }}"',
        'log.to = "console"',
        # Warnings only: Rouh asks frpc's own status page every few seconds, and at info every
        # one of those asks would be a line.
        'log.level = "warn"',
        "",
        "[[proxies]]",
        'name = "http"',
        'type = "http"',
        f"customDomains = [{', '.join(_toml(n) for n in names)}]",
        f"localIP = {_toml(local.split(':')[0])}",
        f"localPort = {int(local.split(':')[1])}",
        f"requestHeaders.set.{MARK_HEADER} = {_toml(mark)}",
        'requestHeaders.set.x-forwarded-proto = "http"',
    ]
    if held.get("ca"):
        # The relay's own certificate authority, from the claim: frpc trusts only it, so nobody in
        # between can pose as the relay and take this Rouh's pass.
        ca = os.path.join(_tls_dir(), "relay-ca.pem")
        with open(ca, "w", encoding="utf-8") as fh:
            fh.write(held["ca"])
        at = lines.index("transport.tls.enable = true") + 1
        lines[at:at] = [f"transport.tls.trustedCaFile = {_toml(ca)}",
                        f"transport.tls.serverName = {_toml(held.get('server_name') or held['server_addr'])}"]
    if has_cert(held):
        cert, key = cert_paths()
        lines += [
            "",
            "[[proxies]]",
            'name = "https"',
            'type = "https"',
            f"customDomains = [{', '.join(_toml(n) for n in locked)}]",
            "[proxies.plugin]",
            'type = "https2http"',
            f"localAddr = {_toml(local)}",
            f"crtPath = {_toml(cert)}",
            f"keyPath = {_toml(key)}",
            f"requestHeaders.set.{MARK_HEADER} = {_toml(mark)}",
            'requestHeaders.set.x-forwarded-proto = "https"',
        ]
    return "\n".join(lines) + "\n"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --- the certificate -----------------------------------------------------------------------------

#: The HTTP-01 answers being asked for right now, by token.
CHALLENGES: dict[str, str] = {}


def challenge_answer(token: str) -> str:
    return CHALLENGES.get(token, "")


def _renew_at(cert_pem: str) -> float:
    from . import acme

    start, end = acme.not_before(cert_pem), acme.not_after(cert_pem)
    return start + (end - start) * 2 / 3


def needs_cert(held: dict | None = None) -> bool:
    held = read() if held is None else held
    if not cert_covers_all(held):
        return True
    cert, _ = cert_paths()
    try:
        with open(cert, encoding="utf-8") as fh:
            return time.time() >= _renew_at(fh.read())
    except (OSError, ValueError):
        return True


def get_cert() -> dict:
    """A certificate for the claimed name, from Let's Encrypt (or ``ROUH_ACME_DIRECTORY``), its
    HTTP-01 check answered through the relay's port 80. Blocking: run it in a thread."""
    from . import acme

    held = read()
    host = held.get("hostname") or ""
    if not host:
        raise Refused("There is no address to get a certificate for yet.")
    account = _open(held, "acme_account") or acme.new_key_pem()
    directory = acme.directory_url()
    kid = held.get("acme_kid") if held.get("acme_directory") == directory else ""
    # No contact address: Let's Encrypt sends no expiry mail any more, and it refuses an account
    # whose address it cannot check, which would leave the phone without a certificate.
    client = acme.Client(account, directory=directory, kid=kid or "")
    try:
        kid = client.account()
        _change(acme_account=_box().seal(account), acme_kid=kid, acme_directory=directory)
        key_pem = acme.new_key_pem()
        names = hostnames(held)
        chain = client.certificate(names, key_pem, publish=CHALLENGES.__setitem__,
                                   unpublish=lambda t: CHALLENGES.pop(t, None))
    finally:
        client.close()
    cert, key = cert_paths()
    for path, text in ((key, key_pem), (cert, chain)):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    until = acme.not_after(chain)
    _change(cert_for=",".join(names), cert_at=time.time(), cert_until=until, cert_error=None, cert_tried_at=time.time())
    log.info("relay: a certificate for %s, good until %s", ", ".join(names), time.strftime("%Y-%m-%d", time.gmtime(until)))
    return {"until": until}


# --- the check from outside ----------------------------------------------------------------------


def check_from_outside() -> bool:
    """Whether the address answers as this Rouh, over the internet and through the relay, locked
    with a certificate a phone trusts."""
    import httpx

    held = read()
    url = address(held)
    if not url or not has_cert(held):
        return False
    verify = os.environ.get("ROUH_RELAY_CHECK_CA", "").strip() or True
    try:
        got = httpx.get(url + "/healthz", timeout=TIMEOUT, verify=verify)
        ok = got.status_code == 200 and b'"ok"' in got.content
        said = "" if ok else f"the address answered {got.status_code}"
    except httpx.HTTPError as exc:
        ok, said = False, f"the address did not answer from outside ({type(exc).__name__})"
    _change(checked_at=time.time(), checked_ok=ok, check_error=said or None)
    return ok


# --- the supervisor ------------------------------------------------------------------------------


class Supervisor:
    """Keeps frpc running while the owner has the address on: claims first if need be, gets and
    renews the certificate, starts frpc again when it ends, and says what is happening."""

    def __init__(self):
        self.task: asyncio.Task | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.admin_port = 0
        self.admin_password = ""
        self.state = "off"
        self.said = ""
        self.ever_connected = False
        self.since = 0.0
        self.restart_wanted = False
        # A name was just chosen: its certificate is asked for now, not after a backoff.
        self.cert_now = False

    # what the page sees

    def snapshot(self) -> dict:
        return {"state": self.state, "said": self.said, "since": self.since}

    def _set(self, state: str, said: str = "") -> None:
        if state != self.state:
            log.info("relay: %s%s", state, f" ({said})" if said else "")
            self.since = time.time()
        self.state, self.said = state, said

    # running

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.get_running_loop().create_task(self._run(), name="relay")

    async def stop(self) -> None:
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._end()
        self._set("off")

    async def _end(self) -> None:
        proc, self.proc = self.proc, None
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    async def _spawn(self, held: dict) -> None:
        from .config import config

        binary = await asyncio.to_thread(frpc_path)
        self.admin_port = _free_port()
        self.admin_password = secrets.token_urlsafe(18)
        local = f"127.0.0.1:{config.port}"
        cfg = os.path.join(folder(), "frpc.toml")
        text = frpc_config(held, self.admin_port, local)
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(cfg, 0o600)
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": folder(),
               "ROUH_FRP_TOKEN": _open(held, "auth_token"), "ROUH_FRP_SECRET": _open(held, "secret"),
               "ROUH_FRP_ADMIN": self.admin_password}
        # frpc reaches the relay through the proxy this Rouh is behind, if it is behind one
        # (frp reads http_proxy for transport.proxyURL).
        proxy = os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY") or ""
        if proxy:
            env["http_proxy"] = proxy
        logfile = os.path.join(folder(), "frpc.log")
        with contextlib.suppress(OSError):
            if os.path.getsize(logfile) > 2_000_000:
                os.replace(logfile, logfile + ".1")
        out = open(logfile, "ab")  # noqa: SIM115 - handed to the child, closed below
        try:
            self.proc = await asyncio.create_subprocess_exec(binary, "-c", cfg, stdin=asyncio.subprocess.DEVNULL,
                                                             stdout=out, stderr=out, env=env)
        finally:
            out.close()
        log.info("relay: frpc started (pid %s) for %s", self.proc.pid, held["hostname"])

    async def _proxies(self) -> dict:
        """frpc's own account of its proxies: {"http": "running", ...}; {} while it is not logged in."""
        import httpx

        auth = base64.b64encode(f"rouh:{self.admin_password}".encode()).decode()
        try:
            async with httpx.AsyncClient(timeout=3.0) as http:
                got = await http.get(f"http://127.0.0.1:{self.admin_port}/api/status",
                                     headers={"Authorization": f"Basic {auth}"})
            data = got.json() if got.status_code == 200 else {}
        except (httpx.HTTPError, ValueError):
            return {}
        out = {}
        for rows in (data or {}).values():
            for row in rows or []:
                out[str(row.get("name") or "").split(".")[-1]] = str(row.get("status") or "")
        return out

    async def _run(self) -> None:
        wait = 2.0
        checked = usage_at = renew_look = 0.0
        cert_wait_until = 0.0
        cert_backoff = 900.0
        while True:
            try:
                held = read()
                if not held.get("on"):
                    await self._end()
                    self._set("off")
                    return
                if not held.get("hostname"):
                    self._set("connecting", "Asking the relay for this Rouh's address.")
                    # The claim at birth may still be on its way: one claim at a time.
                    await asyncio.to_thread(claim_waited, TIMEOUT + 5)
                    held = read()
                if not held.get("hostname"):
                    try:
                        await asyncio.to_thread(claim)
                    except Refused as exc:
                        self._set("reconnecting" if self.ever_connected else "connecting", str(exc))
                        await asyncio.sleep(min(wait, 300))
                        wait = min(wait * 2, 300)
                        continue
                    held = read()
                    if not held.get("hostname"):
                        await asyncio.sleep(max(30, int((held.get("pending") or {}).get("retry_after") or 60)))
                        continue
                if self.proc is None or self.proc.returncode is not None or self.restart_wanted:
                    if self.proc is not None and self.proc.returncode is not None:
                        log.warning("relay: frpc ended (%s); starting it again", self.proc.returncode)
                    self.restart_wanted = False
                    await self._end()
                    await self._spawn(held)
                    await asyncio.sleep(1.5)
                proxies = await self._proxies()
                now = time.time()
                if self.cert_now:
                    self.cert_now = False
                    cert_wait_until = 0.0
                if proxies.get("http") == "running":
                    wait = 2.0
                    if needs_cert(held) and now >= cert_wait_until:
                        self._set("connected" if self.ever_connected and has_cert(held) else "connecting",
                                  "Getting this address's certificate from Let's Encrypt.")
                        try:
                            await asyncio.to_thread(get_cert)
                            cert_backoff = 900.0
                            self.restart_wanted = True
                            continue
                        except Exception as exc:  # noqa: BLE001 - said, and tried again later
                            said = str(exc) or type(exc).__name__
                            log.warning("relay: no certificate for %s: %s", held.get("hostname"), said)
                            _change(cert_error=said[:300], cert_tried_at=now)
                            cert_wait_until = now + cert_backoff
                            cert_backoff = min(cert_backoff * 2, 6 * 3600)
                    if has_cert(held) and proxies.get("https") == "running":
                        self.ever_connected = True
                        self._set("connected")
                        if now - checked > CHECK_EVERY:
                            checked = now
                            await asyncio.to_thread(check_from_outside)
                        if now - usage_at > USAGE_EVERY:
                            usage_at = now
                            await asyncio.to_thread(usage)
                        if now - renew_look > RENEW_LOOK_EVERY:
                            renew_look = now
                    elif not has_cert(held):
                        error = read().get("cert_error") or ""
                        self._set("connecting", f"No certificate yet: {error}" if error
                                  else "Getting this address's certificate from Let's Encrypt.")
                else:
                    self._set("reconnecting" if self.ever_connected else "connecting",
                              "Waiting for the relay to answer.")
                    checked = 0.0
                await asyncio.sleep(LOOK_EVERY)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - never ends by itself while the address is on
                log.exception("relay: the supervisor tripped")
                self._set("reconnecting" if self.ever_connected else "connecting", str(exc)[:200])
                await asyncio.sleep(min(wait, 60))
                wait = min(wait * 2, 60)


SUPERVISOR = Supervisor()


async def start() -> None:
    """At Rouh's start: the claimed name allowed, and frpc started again if the address is on."""
    global _LOOP
    if not enabled():
        return
    _LOOP = asyncio.get_running_loop()
    held = await asyncio.to_thread(read)
    if held.get("hostname"):
        allow_host()
    # A Connected Rouh never turned on or off (born before 8 November 2026, or its claim at birth
    # never got through) is opened now, as one born today is.
    try:
        await asyncio.to_thread(open_by_itself)
    except Exception:  # noqa: BLE001 - never in the way of Rouh starting
        log.exception("relay: the address could not be opened by itself")
    if (await asyncio.to_thread(read)).get("on"):
        SUPERVISOR.start()


async def stop() -> None:
    await SUPERVISOR.stop()


async def turn_on() -> dict:
    if not enabled():
        raise Refused("This installation has no relay (ROUH_RELAY=0).")
    if await asyncio.to_thread(chose_connected) is not True:
        raise Refused("This Rouh is on its own, so it opens no address to the internet.")
    await asyncio.to_thread(lambda: _change(on=True, on_at=time.time(),
                                            mark=read().get("mark") or secrets.token_urlsafe(24)))
    SUPERVISOR.start()
    return await asyncio.to_thread(status)


async def turn_off() -> dict:
    await asyncio.to_thread(lambda: _change(on=False))
    await SUPERVISOR.stop()
    return await asyncio.to_thread(status)


def _safe(fn) -> bool:
    try:
        return bool(fn())
    except Exception:  # noqa: BLE001 - only what the page shows
        return False


def _link_url() -> str:
    try:
        from . import birth

        return birth.defaults()[0]
    except Exception:  # noqa: BLE001 - only a link
        return ""


def _independent() -> str:
    from .birth import INDEPENDENT

    return INDEPENDENT


def status() -> dict:
    """What Settings and the born screen show: the real state, the address, the traffic."""
    held = read()
    on = bool(held.get("on"))
    snap = SUPERVISOR.snapshot()
    state = snap["state"] if on else "off"
    if on and state == "off":
        state = "connecting"
    usage_held = held.get("usage") or None
    return {
        "relay": enabled(),
        "connected_choice": chose_connected(),
        "independent": _independent(),
        "address": address(held),
        "hostname": held.get("hostname") or "",
        "chosen": held.get("chosen") or "",
        "addresses": hostnames(held),
        "preferred": preferred_address(held),
        "domain": domain(),
        "service": urlsplit(service_url()).hostname or "",
        # Where the owner of a Rouh never asked signs in to link it (Rouh profile's own link).
        "account_url": _link_url(),
        "account": _safe(in_account),
        "on": on,
        "state": state,
        "said": snap["said"] if on else "",
        "since": snap["since"] if on else 0,
        "pending": (held.get("pending") or {}).get("said") or "",
        "claim_error": held.get("claim_error") or "",
        "certificate": {"until": held.get("cert_until") or 0, "error": held.get("cert_error") or ""}
        if held.get("hostname") else None,
        "checked": {"at": held.get("checked_at") or 0, "ok": bool(held.get("checked_ok")),
                    "error": held.get("check_error") or ""} if held.get("checked_at") else None,
        "usage": usage_held,
        "limit_bytes": (usage_held or {}).get("limit_bytes") or held.get("limit_bytes") or 0,
    }


# --- signing in on the phone ---------------------------------------------------------------------

_CODES: dict[str, tuple[str, float, str]] = {}


def signin_link(user, purpose: str = "phone", base: str = "") -> dict:
    """A one-time sign-in link to the phone address, for the owner signed in on the computer:
    shown as a QR code, good once, for ten minutes; a new one ends the one before of the same
    purpose ("phone" for the QR code, "open" for Rouh for Mac's Open Rouh, step 140-13). It goes to
    the chosen address once its certificate covers it, else the born one; or to ``base``, the
    owner's own domain on a Linux server (``rouh domain``, task 176, step 176-24)."""
    from . import birth

    url = base.rstrip("/") or preferred_address()
    if not url:
        raise Refused("This Rouh has no address yet.")
    code = secrets.token_urlsafe(24)
    digest = hashlib.sha256(code.encode()).hexdigest()
    with _LOCK:
        for k, (uid, _, why) in list(_CODES.items()):
            if uid == str(user.pk) and why == purpose:
                _CODES.pop(k, None)
        _CODES[digest] = (str(user.pk), time.time() + SIGNIN_SECONDS, purpose)
    link = f"{url}{SIGNIN_PATH}?code={code}"
    return {"link": link, "address": url, "qr": birth_qr(link), "until": time.time() + SIGNIN_SECONDS,
            "seconds": SIGNIN_SECONDS, "name": getattr(birth.current(str(user.org_id)), "name", "")}


def take_signin(code: str) -> str:
    """The account a sign-in code was made for, once; "" for a wrong, used or old one."""
    digest = hashlib.sha256(str(code or "").encode()).hexdigest()
    with _LOCK:
        uid, until, _ = _CODES.pop(digest, ("", 0.0, ""))
    return uid if uid and until > time.time() else ""


def birth_qr(text: str) -> str:
    """A QR code of ``text`` as SVG markup, the way the recovery words' one is drawn."""
    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", xmldecl=False, svgns=True, nl=False, scale=5, border=2,
                                     dark="#000", light="#fff")
    return buf.getvalue().decode()
