"""No email carries an address that works only on this Rouh's own computer (task 140, step 140-14).

Petar, 11 November 2026: "when I was installing this on a different computer, there was a
confirmation in the email that was a link to 127.0.0.1 ... maria received it, clicked on the phone,
where she was logged and obviously hit an error since rouh wasn't running on her phone ... I want
to eradicate this specific thing."

A Rouh on a Mac is reached at http://127.0.0.1:8420 (`ROUH_PUBLIC_URL`'s default in the stack), and
the sign-in letters built their link from that address, or from the address the browser asked on.
Such a link works only on that one computer. So:

- `outside_base` is where a letter's link may point: the installation's public address when it is
  one the world can reach, else this Rouh's own address on rouh.page through the relay while it is
  on, else nothing, and the letter carries only its code.
- `clean` is the guard every mail exit runs (`mailer.Mailer.send`, `Gmail.send`, the sign-in letter
  rouh.land sends for this Rouh): a link to a loopback, private-network or `.local` address is moved
  onto `outside_base` when there is one, else taken out with a few words saying so.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

#: Names that only ever mean "this computer" or "this house's network".
_LOCAL_NAMES = ("localhost", "host.docker.internal", "gateway.docker.internal")
_LOCAL_ENDINGS = (".localhost", ".local", ".lan", ".home.arpa", ".internal")
#: The carrier-grade block (100.64.0.0/10) a phone network hands out: never reachable from outside.
_SHARED = ipaddress.ip_network("100.64.0.0/10")

#: A web address in text or in HTML: up to a space, a quote, a bracket or an angle bracket.
URL = re.compile(r"https?://(?:\[[0-9a-f:.]+\]|[^\s<>\"'()\[\]{}/])[^\s<>\"'()\[\]{}]*", re.IGNORECASE)

#: A local address written without its "http://", with a port: "127.0.0.1:8420/login/link/x" or
#: "localhost:8420". A mail client makes a link of it all the same (step 140-14, 12 November 2026).
BARE = re.compile(
    r"(?<![\w./@:-])(localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}"
    r"|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}|169\.254(?:\.\d{1,3}){2}|\[::1\])"
    r"(:\d{2,5})(/[^\s<>\"'()\[\]{}]*)?", re.IGNORECASE)


class LocalAddress(ValueError):
    """A letter still held an address that opens only on this computer after `clean`: it is not
    sent (`guard`)."""


#: What stands where a link was taken out.
GONE = "(a link that opens only on this Rouh's own computer was left out)"


def local_host(host: str) -> bool:
    """Whether a host name or address means this computer or a private network only."""
    name = str(host or "").strip().strip("[]").rstrip(".").lower()
    if not name:
        return False
    if name in _LOCAL_NAMES or name.endswith(_LOCAL_ENDINGS) or "." not in name and ":" not in name:
        # A bare name with no dot ("mozart", "rouh") is a name on one network only.
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified or ip.is_reserved
            or (isinstance(ip, ipaddress.IPv4Address) and ip in _SHARED))


def is_local(url: str) -> bool:
    """Whether a web address opens only on this computer or this network."""
    try:
        return local_host(urlsplit(str(url or "").strip()).hostname or "")
    except ValueError:
        return True  # A broken address is no address to send anybody.


def outside_base() -> str:
    """Where this Rouh is reached from anywhere, with no slash at the end, or "".

    The installation's public address when the world can reach it (a server's own name); else, on a
    Rouh at home such as Rouh for Mac, its rouh.page address through the relay while it is on; else
    nothing."""
    try:
        from .config import config

        public = str(config.public_url or "").strip().rstrip("/")
    except Exception:  # noqa: BLE001 - only where a link points
        public = ""
    if public and not is_local(public):
        return public
    try:
        from . import relay

        held = relay.read()
        if held.get("on"):
            there = relay.preferred_address(held).rstrip("/")
            if there and not is_local(there):
                return there
    except Exception:  # noqa: BLE001 - no relay, no address
        pass
    return ""


def _moved(url: str, base: str) -> str:
    """The same page on `base`: its path, query and fragment kept."""
    parts = urlsplit(url)
    rest = parts.path or "/"
    if parts.query:
        rest += "?" + parts.query
    if parts.fragment:
        rest += "#" + parts.fragment
    return base + rest


def clean(text: str, *, strict: bool = True, base: str | None = None, html: bool = False) -> str:
    """`text` with no link that opens only on this computer.

    `strict` (Rouh's own letters): loopback, private-network and `.local` addresses are all moved or
    taken out. Not strict (mail the person writes and Rouh sends for them): only links to this Rouh
    on this computer (`_own_ports` on 127.x or localhost); any other address a person typed on
    purpose is theirs to send.
    A link is moved onto `base` (`outside_base` unless given) when there is one, else taken out."""
    if not text or ("://" not in text and not BARE.search(text)):
        return text or ""
    there: list[str] = []

    def target() -> str:
        if not there:
            there.append(outside_base() if base is None else str(base or "").rstrip("/"))
        return there[0]

    def one(match: re.Match) -> str:
        url = match.group(0)
        # A sentence's full stop or comma is not part of the address.
        tail = ""
        while url and url[-1] in ".,;:!?":
            tail, url = url[-1] + tail, url[:-1]
        if not _bad(url, strict):
            return match.group(0)
        to = target()
        if to:
            log.info("mail: a link to this Rouh's own computer was moved onto its outside address")
            return _moved(url, to) + tail
        log.info("mail: a link to this Rouh's own computer was left out (no outside address)")
        return ("#" if html else GONE) + tail

    text = URL.sub(one, text)

    def bare(match: re.Match) -> str:
        whole = match.group(0)
        tail = ""
        while whole and whole[-1] in ".,;:!?":
            tail, whole = whole[-1] + tail, whole[:-1]
        if not _bad("http://" + whole, strict):
            return match.group(0)
        to = target()
        if to:
            return _moved("http://" + whole, to) + tail
        return ("#" if html else GONE) + tail

    return BARE.sub(bare, text) if ":" in text else text


def _own_ports() -> set[int]:
    """The ports this Rouh answers on at home: its public address's when that is local, and the
    stack's own 8420."""
    ports = {8420}
    try:
        from .config import config

        public = str(config.public_url or "")
        if public and is_local(public):
            ports.add(urlsplit(public).port or (443 if public.startswith("https") else 80))
    except Exception:  # noqa: BLE001
        pass
    return ports


def _bad(url: str, strict: bool) -> bool:
    if strict:
        return is_local(url)
    # Mail the person writes: only a link to this very Rouh on this computer (127.0.0.1:8420 and
    # the like). "Open http://localhost:3000" to a developer is an instruction for their own
    # computer, and stays.
    try:
        parts = urlsplit(url)
        host, port = (parts.hostname or "").lower(), parts.port
    except ValueError:
        return False
    if port is None or port not in _own_ports():
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_unspecified


def has_local(text: str, *, strict: bool = True) -> bool:
    """Whether `text` holds a link `clean` would move or take out."""
    return bool(local_left(text, strict=strict))


def local_left(text: str, *, strict: bool = True) -> list[str]:
    """Every address in `text` that opens only on this computer or this network: written as a link,
    or bare with a port ("127.0.0.1:8420/x", "localhost:8420")."""
    text = str(text or "")
    found = [m.group(0).rstrip(".,;:!?") for m in URL.finditer(text)]
    found = [u for u in found if _bad(u, strict)]
    found += [m.group(0).rstrip(".,;:!?") for m in BARE.finditer(text)
              if _bad("http://" + m.group(0).rstrip(".,;:!?"), strict)]
    return found


def guard(text: str, *, strict: bool = True, html: bool = False, base: str | None = None) -> str:
    """`clean`, and then the check that fails: if anything local is still in the letter, it is not
    sent (`LocalAddress`). Every mail exit runs this (`mailer.Mailer.send`, `Gmail.send`), and the
    self-check holds every exit to it (`rouh/selfcheck/own.py`, "no letter leaves with ...")."""
    out = clean(text, strict=strict, base=base, html=html)
    left = local_left(out, strict=strict)
    if left:
        log.error("mail: a letter still held %d address(es) that open only on this computer; not sent", len(left))
        raise LocalAddress("The letter held an address that opens only on this computer, so it was not sent.")
    return out


def link_base(request) -> str:
    """Where a letter's link points when a person asked for it in their browser: the name that
    browser is on when it is one of Rouh's own public names, else `outside_base`, else "" (the
    letter then carries only its code). Never the address of this computer."""
    from .web.common import public_base

    base = public_base(request)
    if base and not is_local(base):
        return base
    return outside_base()
