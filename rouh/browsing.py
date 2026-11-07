"""A browser Rouh drives for errands, which the person can watch and take over.

Petar, 24 September 2026, answering task 60, a piece of research into assistants:
"for now I only want 9 - the live visual browser." Idea 9 of that research was
a browser Rouh drives for errands, whose screen the person can watch live, and
which they can take over for the parts only they should do - a login, a
captcha, a payment - and hand back.

What it is
----------

One real Chromium per person, started the first time Rouh is asked to use it
and closed after a quarter of an hour of nobody using it. Rouh drives it with
the `browser` tool (`tools.py`): it opens an address, reads the page as an
outline in which everything it can act on carries a ref, and clicks, types,
picks and presses keys by those refs. The outline is Playwright's own snapshot
for an agent, the one Playwright MCP reads, so a page is read here the way
every background run on this machine already reads one.

The person sees it live. The page's screen goes to every tab of theirs that
has the Live browser open (`webView` in app.js), as JPEG frames from
Chromium's own screencast, and only while somebody is watching: nothing is
drawn, encoded or sent for a browser nobody is looking at. What Rouh is doing
goes with it, in words and as a ring round the thing it is about to press.
Take control stops Rouh and gives them the mouse and the keyboard; Hand back
gives it back and tells Rouh, in the chat the errand belongs to, where the page
is now and how many times they clicked and typed - never what they typed.

What it keeps
-------------

The person's logins, and only in the database, sealed. When the browser closes,
when it is handed back, and every few minutes while it is open, its cookies and
local storage are read out (`storage_state`), sealed with
`encryption.SecretBox` and written to one row keyed by the person and their
organisation (`BrowserLogins`). The next browser starts from them. Nothing of
theirs is left on disk: the profile is Playwright's own temporary directory,
removed with the browser.

What it may not do
------------------

- **Reach this machine or its network.** Every connection the browser makes
  goes through `Gatekeeper`, a SOCKS proxy inside this process, which resolves
  the name itself and refuses any address that is not on the public internet:
  loopback, the private ranges, link-local and everything else `ipaddress`
  does not call global. It then connects to the very address it checked, so a
  name that is public when it is checked and 127.0.0.1 when it is used gets
  nowhere. The one program trusts a caller on this machine, and a web page that
  talked Rouh into opening http://127.0.0.1:... would otherwise be that caller.
- **Run as root.** Rouh does, so where it is root the browser is started as an
  unprivileged user (`ROUH_BROWSER_USER`, nobody unless it says otherwise),
  inside bubblewrap with a filesystem of its own: the system's libraries, its
  fonts and certificates, the browser's build and its profile, and nothing
  else - no workspace, no data directory, no `.env`, and none of this
  process's environment. A browser that cannot be started that way is not
  started at all, and the tool says why.
- **Type a password, a card number or a one-time code.** A field that is one
  is refused in code, whatever the model was told or talked into, and the tool
  says to hand the browser over instead. The one way a card reaches a page is
  `Desk.fill_card`, called by `payments.fill_card` with the vault's card after
  every cap is checked: it fills the checkout's card fields itself, in every
  frame, and the model only ever learns which fields were filled. Every
  outline read back from that browser afterwards has the card scrubbed out of
  it (`scrub_card`), so the digits on the page never reach the model either.
  A one-time code, a card's number and a log-in's password are refused always.
- **Sign up for anything nobody authorized.** The one password the browser
  ever fills in is a new account's, for a sign-up the person authorized
  themselves (`rouh/signups.py`): in their own words in a conversation, or on
  the Sign-ups page in Settings. It is the password they set there, sealed,
  filled in by `fill_password` straight from the seal into a new-password
  field on that site; the model never sees it, and every outline is scrubbed
  of it (`signups.scrub`). On a site with such a sign-up every press is
  judged (`signups.judge`): the registration step goes without asking again,
  and a payment, a price, card or bank details, an identity check, a
  declaration, sending or publishing stops there (`STOPPED`). Petar, 6
  October 2026, after a Stripe sign-up he had asked for stopped at both.

- **Place an order nobody asked for.** A click on a button that reads as the
  one that places an order and pays ("Buy now", "Place order", "Zahlungspflichtig
  bestellen", "Pay") is refused in code (`purchases.final_press`). The one way
  it is pressed is `place_order`, for a purchase the owner asked for themselves, in their
  own words (`rouh/purchases.py`), once the card is in from the vault and the
  total and the delivery address the page shows have been read and checked
  (`Desk.place_order`). At a shop that takes the card only after its order
  button, on its payment provider's page, the order button goes first, with a
  card picked as the way to pay and no card fields on the page, and the pages
  the shop sends the browser to straight after are that purchase's payment
  pages, where the card goes in and the last Pay is pressed (`Desk._follow`). Petar, 17 October 2026: "Don't leave pay button for me,
  you need to learn to do it autonomously. And terms box too should be checked
  by you during purchase process". So a shop's own required terms, privacy and
  withdrawal boxes are Rouh's to tick, and an optional box - a newsletter,
  marketing, making an account, saving the card - is never ticked by Rouh on any
  site (`Desk._guard`).

What it does not stop: Rouh pressing a button that sends a message or books.
The tool tells it to hand the browser over before anything that cannot be
undone, and the person can watch it.

Reading one page
----------------

`Desk.read` is the other thing a browser is for here: one page, read once,
when web_fetch could not read it (`rouh/fetchfallback.py`). It is not the
person's browser. It starts with nobody's logins, nobody watches it and it is
closed the moment the page is read, but it goes out through the same
gatekeeper and starts inside the same jail, so it can reach no more than the
Live browser can.

In the containers
-----------------

There the core holds the keys and the database, and runs no browser beside
them. Every browser it uses is a connection to the stack's browser container
(`browser_remote`, `chromium`): Debian's Chromium, run by the protected core's
own start script (guard/bin/rouh-browser-server) as a user with nothing of
anybody's, on a network only the core and the key proxy share, and out only
through the key proxy, which refuses this machine and private networks as the
gatekeeper does. The container is the jail, so neither the gatekeeper nor
bubblewrap is used there; the screencast, taking over and the sealed logins
are the same, because they are Playwright's and Rouh's, not the browser's.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import ipaddress
import json
import logging
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from urllib.parse import unquote_plus, urlsplit

from . import clock, protected, purchases, rouhlinks, sandbox, signups, untrusted
# How a checkout is filled lives in its own module; the public names are re-exported here
# for the callers that reach them through browsing (`payments`).
from .checkout_fields import (_BILL_FORM, _BILL_LOOSE, _CARD_BILLING_KINDS, _SCRUBBED,  # noqa: F401
                              _SHIP_FORM, BILL_FIELDS, CARD_FIELDS, SHIP_LABELS, _bill_apart,
                              _card_values, _fill_delivery, _fill_first, _fill_set,
                              _number_forms, _open_apart, _showing, fill_card_over_cdp,
                              scrub_card)

log = logging.getLogger("rouh.browsing")

#: The size of the browser's window, in CSS pixels, until somebody watches it.
#: As wide as a small laptop's, so a site lays itself out for a desk, and no
#: wider, because the picture of it is read on a canvas half a screen wide.
#: Watched, it takes the shape of the screen it is watched on (`_fit`).
VIEWPORT = {"width": 1024, "height": 720}
HEIGHTS = (480, 1400)

#: How good each frame of the live picture is, and how often one may be sent.
#: A frame is only sent when the page has changed, so a page standing still
#: costs nothing; this is the ceiling while it moves.
FRAME_QUALITY = 60
FRAME_GAP = 0.15

#: How long a browser nobody has used stays open, and how long one the person
#: has taken and walked away from does.
IDLE_SECONDS = 15 * 60
IDLE_TAKEN_SECONDS = 60 * 60

#: How often an open browser's logins are written down while it is open.
SAVE_EVERY = 5 * 60

#: How much of a page's outline goes back to the model. A long page is cut
#: here rather than filling the window.
OUTLINE_CHARS = 24000

#: How long an errand that Rouh was in the middle of counts as still going,
#: for whether handing the browser back should tell Rouh so.
ERRAND_FRESH = 10 * 60

#: How a press held back as the person's commitment begins (`Desk._commitment`),
#: so the tool can hand the browser over and tell the phone.
STOPPED = "Stopped at the person's step."

#: What the model may ask for, and nothing else.
ACTIONS = ("open", "look", "click", "type", "select", "press", "back",
           "hand_over", "close", "fill_password")

#: What a page's `autocomplete` says when a field holds something Rouh must
#: never type: a password, a one-time code, a card's number or its code, and
#: what kind of field each is (`_field_kind`).
_SECRET_AUTOCOMPLETE = {"current-password": "login_password", "new-password": "password",
                        "one-time-code": "code", "cc-number": "card", "cc-csc": "card",
                        "cc-exp": "card", "cc-exp-month": "card", "cc-exp-year": "card"}
_CARD_NAME = re.compile(r"cvv|cvc|csc|card.?num|cardnumber|ccnum", re.IGNORECASE)
_CODE_NAME = re.compile(r"passcode|\bpin\b|\botp\b|one.?time|security.?code", re.IGNORECASE)
_PASSWORD_NAME = re.compile(r"passw|pwd", re.IGNORECASE)
_EMAIL_NAME = re.compile(r"e-?mail", re.IGNORECASE)
#: The kinds of field the model never types into, whatever it was told.
SECRET_KINDS = ("card", "code", "login_password", "password")

#: The keys the model may press by name. Anything else is one character.
_KEYS = {"Enter", "Escape", "Tab", "Backspace", "Delete", "Space", "Home", "End",
         "PageUp", "PageDown", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight",
         "Shift+Tab"}

#: A ref from the outline: `e12`, or `f1e12` inside a frame.
_REF = re.compile(r"^(?:f\d+)?e\d+$")


#: How much of a page `Desk.read` hands back. A long page is cut here with a
#: line that says so, rather than filling the window with one page.
PAGE_CHARS = 60000

#: How long a page read once may take to load, and how long it is then given
#: for what its scripts draw, which is most of what a browser reads that a
#: fetch cannot.
READ_LOAD_MS = 30000
READ_SCRIPTS_MS = 6000
#: The longest a page read once may take, all of it, whatever it is doing: a
#: page that keeps loading itself again, as a check for bots can, would
#: otherwise hold a turn for as long as it kept at it.
READ_SECONDS = 60


class CannotBrowse(RuntimeError):
    """The browser cannot be started here, with the sentence that says why."""


@dataclass
class Reading:
    """One page read by `Desk.read`: what it said, or why it could not be read.

    `error` is empty when the page was read, and is otherwise a sentence that
    fits after "the browser said", such as "the site answered 403 Forbidden".
    """

    url: str
    title: str = ""
    text: str = ""
    error: str = ""
    #: Whether the page was a check for bots that only a person can pass,
    #: which the Live browser can hand them.
    bot_check: bool = False

    @property
    def ok(self) -> bool:
        return not self.error


# ---------------------------------------------------------------------------
# The logins, sealed
# ---------------------------------------------------------------------------


class Logins:
    """Each person's saved logins: the browser's storage state, sealed.

    One row per person, keyed by them and by their organisation and asked for
    by both (`AGENTS.md`, "Whose data is it"). The state is cookies and local
    storage, which is exactly what a login is to a website, so it is sealed
    like every other credential Rouh holds.
    """

    def __init__(self, box) -> None:
        self._box = box

    def load(self, user_id: str, org_id: str) -> dict | None:
        from .encryption import CannotOpen
        from .models import BrowserLogins

        row = BrowserLogins.objects.filter(user_id=user_id, org_id=org_id).first()
        if row is None or not row.state_sealed:
            return None
        try:
            state = json.loads(self._box.open_(row.state_sealed))
        except (CannotOpen, ValueError):
            # A key that changed, or a row edited by hand. The browser starts
            # signed out rather than not at all, and says so in the log.
            log.warning("the saved browser logins would not open; starting without them")
            return None
        return state if isinstance(state, dict) else None

    def save(self, user_id: str, org_id: str, state: dict) -> int:
        from .models import BrowserLogins

        cookies = state.get("cookies") or []
        sites = len({str(c.get("domain") or "").lstrip(".") for c in cookies
                     if c.get("domain")})
        BrowserLogins.objects.update_or_create(
            user_id=user_id, org_id=org_id,
            defaults={"state_sealed": self._box.seal(json.dumps(state)),
                      "sites": sites, "saved_at": time.time()})
        return sites

    def sites(self, user_id: str, org_id: str) -> int:
        from .models import BrowserLogins

        row = (BrowserLogins.objects.filter(user_id=user_id, org_id=org_id)
               .values("sites").first())
        return int(row["sites"]) if row else 0

    def forget(self, user_id: str, org_id: str) -> bool:
        from .models import BrowserLogins

        gone, _ = BrowserLogins.objects.filter(user_id=user_id, org_id=org_id).delete()
        return bool(gone)


# ---------------------------------------------------------------------------
# The door every connection goes out through
# ---------------------------------------------------------------------------


def _allowed_list(said: str) -> set[str]:
    """`ROUH_BROWSER_ALLOW`: host:port pairs a test world may reach anyway."""
    return {part.strip().lower() for part in (said or "").split(",") if part.strip()}


def remote(cfg=None) -> str:
    """The browser container's address (`browser_remote`), or "" where a browser is started
    beside Rouh itself."""
    if cfg is None:
        from .config import config as cfg
    return str(getattr(cfg, "browser_remote", "") or "").strip()


async def chromium(driver, cfg=None, **launch):
    """A Chromium for any of Rouh's browsers: the browser container's, over Playwright's own
    protocol, where there is one (`remote`), else one started here with `launch`.

    In the containers the core holds the keys and the database, so no browser runs beside
    it (deploy/stack/compose.yml, the browser service). Each connection is a browser of its
    own as far as Rouh can tell: its contexts are invisible to every other connection and
    closed with it, and closing the browser closes the connection. What a launch would say
    - the proxy, the switches - is the browser container's to say
    (guard/bin/rouh-browser-server), so nothing in `launch` is used there.
    """
    endpoint = remote(cfg)
    if not endpoint:
        return await driver.chromium.launch(**launch)
    try:
        return await driver.chromium.connect(endpoint, timeout=30000)
    except Exception as exc:  # noqa: BLE001 - said as it is
        log.warning("the browser container did not answer at %s: %s", endpoint, exc)
        raise CannotBrowse("the browser's own container did not answer ("
                           + (str(exc).splitlines() or ["no reason given"])[0][:160] + ")") from None


def _not_reached(gate: "Gatekeeper", host: str, since: float, exc: Exception) -> str:
    """Why a page would not load, when it was the way out that turned it away; "" otherwise.

    Here the gatekeeper says so itself. In the containers the way out is the key proxy
    (guard/rouh_guard/keyproxy.py), which refuses anything not on the public internet and
    answers for a site it cannot reach, and Chromium reports either as a tunnel it could
    not make; which of the two it was is the proxy's to know."""
    if gate.was_refused(host, since):
        return (f"{host} is not on the public internet - it is this machine or a private "
                "network - and the browser may not go there")
    if "ERR_TUNNEL_CONNECTION_FAILED" in str(exc):
        return (f"the browser's way out did not take it to {host}: it is not on the public "
                "internet, where the browser may not go, or it did not answer")
    return ""


def is_public(address: str) -> bool:
    """Whether an IP address is somewhere on the public internet.

    `is_global` is the whole of the test, with the one thing it misses said
    out loud: an IPv6 address that carries an IPv4 one inside it is judged by
    the IPv4 address, so ::ffff:127.0.0.1 is this machine and not the world.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global and not ip.is_multicast)


class Gatekeeper:
    """A SOCKS5 proxy that lets the browser reach the public internet and
    nothing else.

    SOCKS rather than an HTTP proxy because it is one question per connection
    whatever goes over it - http, https and websockets alike - and because
    Chromium hands a SOCKS5 proxy the name rather than an address it looked up
    itself, so the only lookup that matters is the one done here.
    """

    def __init__(self, allow: str = "") -> None:
        self.allow = _allowed_list(allow)
        self.port = 0
        self._server: asyncio.base_events.Server | None = None
        #: Every connection open through it, so stopping closes them too.
        self._open: set[asyncio.StreamWriter] = set()
        #: The names refused lately, newest last, so a page that would not
        #: load can be explained rather than reported as a network error.
        self.refused: list[tuple[float, str]] = []

    async def start(self) -> int:
        if self._server is None:
            self._server = await asyncio.start_server(self._serve, "127.0.0.1", 0)
            self.port = self._server.sockets[0].getsockname()[1]
            log.info("the browser's gatekeeper is on 127.0.0.1:%d", self.port)
        return self.port

    async def stop(self) -> None:
        # The connections first. Since Python 3.12 a server's `wait_closed`
        # waits for every connection it accepted to finish, so waiting on it
        # with one still open, and closing them only after, waited for ever.
        for writer in list(self._open):
            with contextlib.suppress(Exception):
                writer.close()
        self._open.clear()
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 10)
            self._server = None
            self.port = 0

    def was_refused(self, host: str, since: float) -> bool:
        host = (host or "").lower()
        return any(at >= since and name == host for at, name in self.refused)

    async def vet(self, host: str, port: int) -> str | None:
        """The address to connect to for `host:port`, or None when it may not."""
        host = (host or "").strip().lower().rstrip(".")
        if not host or not 0 < port < 65536:
            return None
        loop = asyncio.get_running_loop()
        try:
            found = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), 10)
        except (OSError, asyncio.TimeoutError):
            return None
        addresses = [info[4][0] for info in found]
        if not addresses:
            return None
        if f"{host}:{port}" in self.allow:
            return addresses[0]
        # Every address the name has must be public, not only the first: a
        # name with one public and one private address is somebody choosing
        # which of the two the browser gets.
        if host == "localhost" or host.endswith(".localhost") or \
                not all(is_public(a) for a in addresses):
            self.refused = (self.refused + [(time.time(), host)])[-20:]
            log.warning("the browser was refused %s:%d, which is not on the public "
                        "internet", host, port)
            return None
        return addresses[0]

    async def _serve(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter) -> None:
        upstream: asyncio.StreamWriter | None = None
        self._open.add(writer)
        try:
            ver, count = await asyncio.wait_for(reader.readexactly(2), 15)
            await reader.readexactly(count)
            if ver != 5:
                return
            writer.write(b"\x05\x00")                      # no authentication
            ver, cmd, _, kind = await asyncio.wait_for(reader.readexactly(4), 15)
            if kind == 1:
                host = socket.inet_ntop(socket.AF_INET, await reader.readexactly(4))
            elif kind == 4:
                host = socket.inet_ntop(socket.AF_INET6, await reader.readexactly(16))
            elif kind == 3:
                size = (await reader.readexactly(1))[0]
                # Chromium sends a name as ASCII, international ones in
                # punycode; anything else is not a name it sent.
                host = (await reader.readexactly(size)).decode("ascii")
            else:
                writer.write(b"\x05\x08\x00\x01" + b"\x00" * 6)
                return
            port = struct.unpack("!H", await reader.readexactly(2))[0]
            if cmd != 1:                                   # CONNECT only
                writer.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
                return
            address = await self.vet(host, port)
            if address is None:
                writer.write(b"\x05\x02\x00\x01" + b"\x00" * 6)   # not allowed
                return
            try:
                up_reader, upstream = await asyncio.wait_for(
                    asyncio.open_connection(address, port), 20)
            except (OSError, asyncio.TimeoutError):
                writer.write(b"\x05\x05\x00\x01" + b"\x00" * 6)   # refused
                return
            writer.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
            await writer.drain()
            self._open.add(upstream)
            await asyncio.gather(_pipe(reader, upstream), _pipe(up_reader, writer))
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, OSError,
                UnicodeError):
            pass
        finally:
            for end in (upstream, writer):
                if end is not None:
                    self._open.discard(end)
                    with contextlib.suppress(Exception):
                        end.close()


async def _pipe(source: asyncio.StreamReader, sink: asyncio.StreamWriter) -> None:
    try:
        while True:
            chunk = await source.read(65536)
            if not chunk:
                break
            sink.write(chunk)
            await sink.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            if sink.can_write_eof():
                sink.write_eof()


# ---------------------------------------------------------------------------
# Starting the browser as somebody who is not root
# ---------------------------------------------------------------------------


#: What in /etc a browser needs to draw text and trust a certificate.
_ETC = ("/etc/fonts", "/etc/ssl", "/etc/ca-certificates", "/etc/localtime",
        "/etc/passwd", "/etc/group", "/etc/nsswitch.conf")


class Jail:
    """How the browser is started: as whom, and inside what.

    Where Rouh is root, the browser is started through a small script written
    for it that hands the profile directory Playwright made to the browser's
    own user, drops to that user with `setpriv`, and runs the browser inside
    bubblewrap. Where Rouh is somebody else already - a laptop, a test world -
    only the bubblewrap part applies, when bubblewrap works here.
    """

    def __init__(self, cfg) -> None:
        self.user = (getattr(cfg, "browser_user", "") or "nobody").strip()
        self.builds = (getattr(cfg, "browser_builds", "") or "/var/lib/rouh-browser").strip()
        self._folder = ""

    def prepare(self, executable: str) -> tuple[str, dict]:
        """The file to launch and the environment to launch it with.

        Raises `CannotBrowse` rather than ever starting the browser as root.
        """
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
               "HOME": tempfile.gettempdir()}
        root = hasattr(os, "geteuid") and os.geteuid() == 0
        ids = None
        if root:
            ids = self._ids()
            executable = self._reachable(executable, ids)
        box = self._box(ids)
        if not root and not box:
            return executable, env
        self._folder = tempfile.mkdtemp(prefix="rouh-browser-")
        script = os.path.join(self._folder, "launch")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(self._script(executable, ids, box))
        os.chmod(script, 0o700)
        return script, env

    def cleanup(self) -> None:
        if self._folder:
            shutil.rmtree(self._folder, ignore_errors=True)
            self._folder = ""

    def _ids(self) -> tuple[int, int]:
        import pwd

        try:
            entry = pwd.getpwnam(self.user)
        except KeyError:
            raise CannotBrowse(
                f"the browser runs as the user {self.user!r}, which this machine does "
                "not have, and it is never started as root") from None
        if entry.pw_uid == 0:
            raise CannotBrowse("the browser's user is root, and it is never started as root")
        return entry.pw_uid, entry.pw_gid

    def _as(self, ids: tuple[int, int] | None, argv: list[str]) -> list[str]:
        if ids is None:
            return argv
        return ["setpriv", f"--reuid={ids[0]}", f"--regid={ids[1]}", "--clear-groups",
                "--no-new-privs", *argv]

    def _runs(self, ids, argv: list[str]) -> bool:
        try:
            done = subprocess.run(self._as(ids, argv), stdin=subprocess.DEVNULL,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=15, check=False)
        except (OSError, subprocess.SubprocessError):
            return False
        return done.returncode == 0

    def _reachable(self, executable: str, ids: tuple[int, int]) -> str:
        """The browser, at a path its own user can run it from.

        Playwright keeps its builds in the home of whoever installed them,
        which on a server where Rouh is root is /root, and nobody else may
        walk into /root. The build is linked into a folder of its own instead:
        hard links, on the same disk, so it takes no room and no time; a copy
        only where the two are on different disks.
        """
        if self._runs(ids, ["test", "-x", executable]):
            return executable
        chrome_dir = os.path.dirname(executable)
        build = os.path.dirname(chrome_dir)
        linked = os.path.join(self.builds, os.path.basename(build))
        there = os.path.join(linked, os.path.basename(chrome_dir),
                             os.path.basename(executable))
        if not os.path.exists(there):
            os.makedirs(self.builds, mode=0o755, exist_ok=True)
            os.chmod(self.builds, 0o755)
            partial = linked + ".partial"
            shutil.rmtree(partial, ignore_errors=True)
            made = subprocess.run(["cp", "-al", build, partial], capture_output=True,
                                  timeout=300, check=False)
            if made.returncode != 0:
                shutil.rmtree(partial, ignore_errors=True)
                made = subprocess.run(["cp", "-a", build, partial], capture_output=True,
                                      timeout=600, check=False)
            if made.returncode != 0:
                raise CannotBrowse("the browser's build could not be put where its "
                                   "own user can run it")
            os.chmod(partial, 0o755)
            os.replace(partial, linked)
            log.info("linked the browser build into %s for %s", linked, self.user)
        if not self._runs(ids, ["test", "-x", there]):
            raise CannotBrowse(f"the user {self.user!r} cannot run the browser at {there}")
        return there

    def _box(self, ids) -> bool:
        """Whether bubblewrap runs here, as the browser's user."""
        if not sandbox.available():
            log.warning("bubblewrap is not installed, so the browser runs without a "
                        "filesystem of its own")
            return False
        works = self._runs(ids, ["bwrap", "--unshare-user", "--ro-bind", "/", "/",
                                 "--dev", "/dev", "--proc", "/proc", "true"])
        if not works:
            log.warning("bubblewrap will not start here, so the browser runs without a "
                        "filesystem of its own")
        return works

    def _script(self, executable: str, ids, box: bool) -> str:
        q = shlex.quote
        lines = [
            "#!/bin/sh",
            "# Written by rouh/browsing.py to start one browser, and removed with it.",
            "dir=",
            'for arg do case "$arg" in --user-data-dir=*) dir="${arg#--user-data-dir=}" ;; esac; done',
            '[ -n "$dir" ] || { echo "rouh: no profile directory was given" >&2; exit 64; }',
        ]
        if ids is not None:
            lines.append(f'chown -R {ids[0]}:{ids[1]} "$dir" || exit 65')
        argv = self._as(ids, [])
        if box:
            build = os.path.dirname(os.path.dirname(executable))
            argv += ["bwrap", "--unshare-user", "--unshare-pid", "--unshare-ipc",
                     "--unshare-uts", "--unshare-cgroup-try", "--die-with-parent",
                     "--new-session", "--clearenv",
                     "--ro-bind", "/usr", "/usr"]
            for top in ("/bin", "/sbin", "/lib", "/lib32", "/lib64"):
                if os.path.islink(top):
                    argv += ["--symlink", os.readlink(top), top]
                elif os.path.isdir(top):
                    argv += ["--ro-bind", top, top]
            for path in _ETC:
                argv += ["--ro-bind-try", path, path]
            argv += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                     "--ro-bind", build, build,
                     "--setenv", "PATH", "/usr/bin:/bin", "--setenv", "LANG", "C.UTF-8",
                     "--setenv", "TMPDIR", "/tmp", "--chdir", "/"]
            tail = " ".join(q(a) for a in argv) + \
                ' --bind "$dir" "$dir" --setenv HOME "$dir" -- ' + q(executable) + ' "$@"'
        else:
            tail = " ".join(q(a) for a in argv) + (" " if argv else "") + \
                'env HOME="$dir" ' + q(executable) + ' "$@"'
        lines.append("exec " + tail)
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# One person's browser
# ---------------------------------------------------------------------------


@dataclass
class Errand:
    """One person's open browser, and who has it."""

    user_id: str
    org_id: str
    #: The chat Rouh was last asked to use it from, where handing it back is
    #: said.
    chat: str
    browser: object = None
    context: object = None
    page: object = None
    jail: Jail | None = None
    #: "rouh" while Rouh may drive it, "person" while they have it.
    control: str = "rouh"
    #: Why Rouh handed it over, in its own words, while it waits for them.
    why: str = ""
    #: Whether the person has it because Rouh asked, rather than because they
    #: took it themselves.
    asked: bool = False
    #: What Rouh is doing this moment, and where on the page.
    doing: str = ""
    mark: dict | None = None
    #: What the page showed in a dialog that was answered for it.
    dialogs: list[str] = field(default_factory=list)
    outline: str = ""
    page_title: str = ""
    width: int = VIEWPORT["width"]
    height: int = VIEWPORT["height"]
    started_at: float = field(default_factory=time.time)
    used_at: float = field(default_factory=time.time)
    rouh_used_at: float = 0.0
    saved_at: float = field(default_factory=time.time)
    clicks: int = 0
    typed: int = 0
    cdp: object = None
    casting: bool = False
    #: The newest picture not sent yet, when the last went out, and the task
    #: sending them (`_frame`).
    latest: tuple | None = None
    sent_at: float = 0.0
    sending: asyncio.Task | None = None
    #: The address last asked for, which is what the page is showing when
    #: all it can show is the browser's own error page.
    tried: str = ""
    #: One of Rouh's actions at a time.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: What `fill_card` put into this browser's pages, kept only in memory and only
    #: so every outline read from it afterwards can be scrubbed of it (`scrub_card`).
    card_values: list[str] = field(default_factory=list)
    card_last4: str = ""
    #: The site the card was last filled in on, where Enter is never pressed for the
    #: order (`Desk._held`).
    card_site: str = ""
    #: The delivery address `fill_shipping` last filled in, so `fill_card` knows whether the
    #: card's billing address is another one (`_bill_apart`).
    shipped: dict = field(default_factory=dict)
    #: What the last `fill_card` did to give the billing address a place of its own, in
    #: words (`_bill_apart`), or "".
    bill_note: str = ""
    #: A sign-up's password `fill_password` put into a page, kept only in memory and
    #: only so every outline read from it afterwards can be scrubbed of it.
    secret_values: list[str] = field(default_factory=list)
    #: The site the last page shown was on, and the site an address was last opened on
    #: by somebody's asking, and when: a page the shop sent the browser to is a purchase's
    #: payment page, one opened by address never is (`Desk._follow`).
    last_site: str = ""
    opened_site: str = ""
    opened_at: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.org_id, self.user_id)


class Desk:
    """Every person's browser, and the one way to each of them.

    The tool, the person's tabs and the clock all come here: the tool with
    what Rouh wants done, the tabs with watching, taking, handing back and
    what the person clicks and types, and the clock with closing a browser
    nobody is using. `tabs` and `announce` are handed in by runtime.py, so this
    knows nothing about sockets or turns.
    """

    def __init__(self, cfg, *, tabs, announce, box=None) -> None:
        self.cfg = cfg
        self._tabs = tabs
        self._announce = announce
        self.logins = Logins(box) if box is not None else None
        self.gate = Gatekeeper(getattr(cfg, "browser_allow", ""))
        self._errands: dict[tuple[str, str], Errand] = {}
        self._driver = None
        self._starting: dict[tuple[str, str], asyncio.Lock] = {}
        self._sweeper: asyncio.Task | None = None
        #: When each person last pressed Stop, so the next open is told.
        self._stopped: dict[tuple[str, str], float] = {}
        #: The purchases each person authorized, by site, until each is placed
        #: (`rouh/purchases.py`). Kept in memory only: a restart asks for them again.
        self._purchases: dict[tuple[str, str], dict[str, purchases.Purchase]] = {}

    # --- who is looking ----------------------------------------------------

    @staticmethod
    def _theirs(tab, key: tuple[str, str]) -> bool:
        me = getattr(tab, "me", None)
        return (me is not None and not getattr(tab, "closed", False)
                and (me.org_id, me.user_id) == key)

    def _watchers(self, key: tuple[str, str]) -> list:
        return [t for t in list(self._tabs())
                if self._theirs(t, key) and getattr(t, "web_watching", False)]

    async def _tell(self, key: tuple[str, str], message: dict) -> None:
        for tab in list(self._tabs()):
            if self._theirs(tab, key):
                with contextlib.suppress(Exception):
                    await tab.send(message)

    def picture(self, who) -> dict:
        """What a tab is told about this person's browser: open or not, and
        everything it needs to draw the Live browser's head."""
        if who is None:
            return {"type": "browser", "open": False}
        return self._picture(self._errands.get((who.org_id, who.user_id)))

    @staticmethod
    def _picture(errand: Errand | None) -> dict:
        if errand is None:
            return {"type": "browser", "open": False}
        return {
            "type": "browser", "open": True,
            "url": _shown_url(errand), "title": errand.page_title,
            "control": errand.control, "why": errand.why, "asked": errand.asked,
            "doing": errand.doing, "mark": errand.mark, "from_chat": errand.chat,
            "width": errand.width, "height": errand.height,
        }

    async def _say(self, errand: Errand, *, show: bool = False) -> None:
        """Every tab of theirs, told where the browser is and who has it.

        `show` asks a tab standing in the errand's chat to open the Live
        browser, which is what Rouh starting an errand, or handing the browser
        over, should do for somebody who is looking.
        """
        with contextlib.suppress(Exception):
            errand.page_title = await errand.page.title()
        said = self._picture(errand)
        if show:
            said["show"] = True
        await self._tell(errand.key, said)

    # --- starting and stopping ---------------------------------------------

    async def _playwright(self):
        if self._driver is None:
            from playwright.async_api import async_playwright

            browsers = getattr(self.cfg, "playwright_browsers", "")
            if browsers:
                os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers)
            self._driver = await async_playwright().start()
        return self._driver

    async def _launch(self, jail: Jail):
        """A headless Chromium, started in `jail` and sent out through the gatekeeper.

        Raises `CannotBrowse` with the reason, and leaves nothing of the jail
        behind when it does.
        """
        try:
            import playwright.async_api  # noqa: F401
        except ImportError:
            raise CannotBrowse("Playwright is not installed for Rouh here") from None
        driver = await self._playwright()
        if remote(self.cfg):
            # In the containers: the browser container's Chromium, which is its own jail and
            # goes out only through the key proxy (`chromium`).
            return await chromium(driver, self.cfg)
        port = await self.gate.start()
        launch, env = await asyncio.to_thread(jail.prepare, driver.chromium.executable_path)
        try:
            return await driver.chromium.launch(
                headless=True, executable_path=launch, env=env,
                handle_sigint=False, handle_sigterm=False, handle_sighup=False,
                proxy={"server": f"socks5://127.0.0.1:{port}"},
                args=["--no-sandbox", "--disable-dev-shm-usage",
                      "--disable-quic",
                      "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                      "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                      "--disable-blink-features=AutomationControlled"])
        except Exception as exc:
            jail.cleanup()
            log.warning("the browser would not start: %s", exc)
            raise CannotBrowse("the browser would not start here ("
                               + str(exc).splitlines()[0][:160] + ")") from None

    async def _open(self, who, chat: str) -> Errand:
        key = (who.org_id, who.user_id)
        errand = self._errands.get(key)
        if errand is not None:
            return errand
        lock = self._starting.setdefault(key, asyncio.Lock())
        async with lock:
            errand = self._errands.get(key)
            if errand is not None:
                return errand
            jail = Jail(self.cfg)
            browser = await self._launch(jail)
            state = None
            if self.logins is not None:
                with contextlib.suppress(Exception):
                    state = await asyncio.to_thread(self.logins.load, who.user_id, who.org_id)
            try:
                context = await browser.new_context(
                    viewport=VIEWPORT, accept_downloads=False, storage_state=state,
                    timezone_id=clock.zone_of(who).key, locale="en-GB")
            except Exception:
                # A saved state the browser will not take is not a reason to
                # have no browser at all.
                log.warning("the saved logins were refused; starting without them",
                            exc_info=True)
                context = await browser.new_context(
                    viewport=VIEWPORT, accept_downloads=False,
                    timezone_id=clock.zone_of(who).key, locale="en-GB")
            errand = Errand(user_id=who.user_id, org_id=who.org_id, chat=chat,
                            browser=browser, context=context, jail=jail)
            page = await context.new_page()
            self._watch_page(errand, page)
            errand.page = page
            # Only after the first page, which is not a new tab of anything.
            context.on("page", lambda page: asyncio.ensure_future(self._new_page(errand, page)))
            browser.on("disconnected", lambda _browser: asyncio.ensure_future(self._lost(errand)))
            self._errands[key] = errand
            # A Live browser already open on a screen, saying the browser was
            # closed, is watching this one from the moment it exists.
            watchers = self._watchers(key)
            if watchers:
                await self._fit(errand, *getattr(watchers[-1], "web_shape", (0, 0, False)))
                await self._cast(errand, True)
            if self._sweeper is None or self._sweeper.done():
                self._sweeper = asyncio.create_task(self._sweep())
            log.info("a browser was opened for %s", who.user_id)
            return errand

    def _watch_page(self, errand: Errand, page) -> None:
        page.on("dialog", lambda dialog: asyncio.ensure_future(self._dialog(errand, dialog)))
        page.on("close", lambda _page: asyncio.ensure_future(self._page_closed(errand, _page)))
        page.on("framenavigated", lambda frame: asyncio.ensure_future(
            self._navigated(errand, frame)))

    async def _dialog(self, errand: Errand, dialog) -> None:
        """A page's own alert, question or prompt, answered so nothing hangs.

        An alert is acknowledged, and a question - "leave this page?", "are
        you sure?" - is answered no, because a yes is exactly the kind of
        thing that should be the person's. Either way the model is told what
        it said, on the next page it reads.
        """
        said = " ".join(str(dialog.message or "").split())[:300]
        errand.dialogs.append(f"{dialog.type}: {said}")
        with contextlib.suppress(Exception):
            if dialog.type == "alert":
                await dialog.accept()
            else:
                await dialog.dismiss()

    async def _new_page(self, errand: Errand, page) -> None:
        """A page opened in a new tab is the one on the screen from now on.

        It is a browser with one window as far as anybody here can tell, so
        a link that opens a new tab goes on in the same place.
        """
        self._watch_page(errand, page)
        with contextlib.suppress(Exception):
            if page.main_frame.url.startswith("http"):
                self._follow(errand, page.main_frame)
        await self._switch(errand, page)

    async def _page_closed(self, errand: Errand, page) -> None:
        if errand.page is not page or self._errands.get(errand.key) is not errand:
            return
        left = [p for p in errand.context.pages if not p.is_closed()]
        with contextlib.suppress(Exception):
            await self._switch(errand, left[-1] if left else await errand.context.new_page())

    async def _fit(self, errand: Errand, width, height, phone=False) -> None:
        """The browser's window made the shape of the screen watching it.

        At a desk it stays 1024 wide and only its height follows the box the
        picture is drawn in, so the picture fills it. On a phone - the page
        says when it is in its phone layout - it is the box's own size, so
        the site lays itself out for a phone and the picture is drawn one to
        one: a desk's layout shrunk to a phone's width is text a third of its
        size, which nobody can read. A page laid out again sideways moves
        what Rouh read the refs of; Rouh reads the page again after every
        action, and a ref that went is said to be gone rather than pressed.
        """
        try:
            width, height = float(width), float(height)
        except (TypeError, ValueError):
            return
        if width <= 0 or height <= 0:
            return
        if phone:
            wide = int(max(320, min(VIEWPORT["width"], round(width))))
            tall = int(max(320, min(HEIGHTS[1], round(height))))
        else:
            wide = VIEWPORT["width"]
            tall = int(max(HEIGHTS[0], min(HEIGHTS[1], round(wide * height / width))))
        if wide == errand.width and abs(tall - errand.height) < 24:
            return
        errand.width, errand.height = wide, tall
        with contextlib.suppress(Exception):
            await errand.page.set_viewport_size({"width": wide, "height": tall})

    async def _switch(self, errand: Errand, page) -> None:
        casting = errand.casting
        await self._cast(errand, False)
        errand.page = page
        with contextlib.suppress(Exception):
            await page.set_viewport_size({"width": errand.width, "height": errand.height})
        if casting or self._watchers(errand.key):
            await self._cast(errand, True)
        await self._say(errand)

    async def _back(self, errand: Errand) -> None:
        """The page before this one.

        A page a link opened in a new tab has nothing before it, and in a
        browser with one window what is before it is the page the link was
        on, so Back closes it and goes there.
        """
        page = errand.page
        try:
            depth = int(await page.evaluate("history.length"))
        except Exception:
            depth = 2
        others = [p for p in errand.context.pages if p is not page and not p.is_closed()]
        if depth <= 1 and others:
            await self._switch(errand, others[-1])
            with contextlib.suppress(Exception):
                await page.close()
            return
        with contextlib.suppress(Exception):
            await page.go_back(wait_until="domcontentloaded", timeout=15000)

    async def _navigated(self, errand: Errand, frame) -> None:
        if frame.parent_frame is None:
            self._follow(errand, frame)
        if frame.page is errand.page and frame.parent_frame is None:
            await self._say(errand)

    def _follow(self, errand: Errand, frame) -> None:
        """A page the shop of a purchase sent the browser to, on another site, is that
        purchase's payment page (`purchases.Purchase.providers`).

        Only while Rouh drives it, only in the moments after a press on the shop's or its
        payment pages (`Purchase.follow`), and only from one of those pages: an address Rouh
        or the person opened, a page reached from anywhere else, and anything later are not.
        """
        try:
            url = frame.url or ""
        except Exception:  # noqa: BLE001 - a frame already gone
            return
        site = signups.site_of(url) if url.startswith(("http://", "https://")) else ""
        if not site:
            return
        before, errand.last_site = errand.last_site, site
        now = time.time()
        if errand.control != "rouh" or before == site or (
                site == errand.opened_site and now - errand.opened_at < 30):
            return
        for purchase in self._purchases.get(errand.key, {}).values():
            if (purchase.live and now <= purchase.follow_until and purchase.covers(before)
                    and not purchase.covers(site)):
                purchase.providers.append(site)
                purchase.follow(now)
                log.info("the browser was sent from %s to %s, the payment page of the purchase "
                         "on %s", before, site, purchase.site)

    async def _left_unpaid(self, key: tuple[str, str], purchase, why: str) -> None:
        """An order submitted at a shop and not paid: the owner told plainly, once
        (`payments.left_unpaid`), and nothing more is filled or pressed for it."""
        if purchase.told_unpaid or not purchase.awaiting:
            return
        purchase.told_unpaid = True
        purchase.expires_at = min(purchase.expires_at, time.time())
        from types import SimpleNamespace

        from . import payments

        with contextlib.suppress(Exception):
            await payments.left_unpaid(SimpleNamespace(org_id=key[0], user_id=key[1]),
                                       purchase, why)

    async def _unpaid_sweep(self, now: float) -> None:
        """Orders submitted and then left: nothing done on them for
        `purchases.UNPAID_MINUTES` while Rouh had the browser, or their authorization run out."""
        for key, held in list(self._purchases.items()):
            errand = self._errands.get(key)
            for purchase in list(held.values()):
                if not purchase.awaiting or purchase.told_unpaid:
                    continue
                if purchase.expires_at <= now:
                    await self._left_unpaid(key, purchase, "its authorization ran out first")
                elif (errand is not None and errand.control == "rouh"
                      and now - purchase.touched_at > purchases.UNPAID_MINUTES * 60):
                    await self._left_unpaid(
                        key, purchase, f"nothing was done on it for {purchases.UNPAID_MINUTES} "
                                       "minutes")

    def _touch(self, errand: Errand, *, pressing: bool = False) -> None:
        """Rouh is working on the page of a purchase: it is not left. A press there may send
        the browser on to its payment page."""
        url = _page_url(errand.page)
        site = signups.site_of(url) if url else ""
        for purchase in self._purchases.get(errand.key, {}).values():
            if purchase.live and purchase.covers(site):
                purchase.touched_at = time.time()
                if pressing:
                    purchase.follow()

    async def _lost(self, errand: Errand) -> None:
        """The browser went away by itself: it crashed, or, in the containers, the browser
        container was started again. That errand is over, and the next open starts a new
        browser from the logins last written down."""
        if self._errands.get(errand.key) is not errand:
            return
        self._errands.pop(errand.key, None)
        if errand.jail is not None:
            errand.jail.cleanup()
        log.warning("the browser for %s went away by itself", errand.user_id)
        await self._tell(errand.key, {"type": "browser", "open": False})

    async def close(self, key: tuple[str, str], *, save: bool = True) -> bool:
        errand = self._errands.pop(key, None)
        if errand is None:
            return False
        for purchase in list(self._purchases.get(key, {}).values()):
            await self._left_unpaid(key, purchase, "the browser was closed first")
        if save:
            await self._save(errand)
        await self._cast(errand, False)
        with contextlib.suppress(Exception):
            await errand.context.close()
        with contextlib.suppress(Exception):
            await errand.browser.close()
        if errand.jail is not None:
            errand.jail.cleanup()
        log.info("a browser was closed for %s", errand.user_id)
        await self._tell(key, {"type": "browser", "open": False})
        return True

    async def stop(self) -> None:
        """Rouh is stopping: every browser saved and closed."""
        for key in list(self._errands):
            with contextlib.suppress(Exception):
                await self.close(key)
        if self._sweeper is not None:
            self._sweeper.cancel()
            self._sweeper = None
        await self.gate.stop()
        if self._driver is not None:
            with contextlib.suppress(Exception):
                await self._driver.stop()
            self._driver = None

    async def _save(self, errand: Errand) -> None:
        if self.logins is None:
            return
        try:
            state = await errand.context.storage_state()
            await asyncio.to_thread(self.logins.save, errand.user_id, errand.org_id, state)
            errand.saved_at = time.time()
        except Exception:
            log.warning("the browser's logins could not be saved", exc_info=True)

    async def _sweep(self) -> None:
        """Close what nobody is using, and write down what is open."""
        while self._errands:
            await asyncio.sleep(30)
            now = time.time()
            with contextlib.suppress(Exception):
                await self._unpaid_sweep(now)
            for key, errand in list(self._errands.items()):
                limit = IDLE_TAKEN_SECONDS if errand.control == "person" else IDLE_SECONDS
                if now - errand.used_at > limit:
                    log.info("closing a browser nobody has used for %d minutes",
                             int((now - errand.used_at) // 60))
                    await self.close(key)
                elif now - errand.saved_at > SAVE_EVERY:
                    await self._save(errand)

    # --- the live picture --------------------------------------------------

    async def _cast(self, errand: Errand, on: bool) -> None:
        if on == errand.casting:
            return
        if not on:
            errand.casting = False
            cdp, errand.cdp = errand.cdp, None
            if cdp is not None:
                with contextlib.suppress(Exception):
                    await cdp.send("Page.stopScreencast")
                with contextlib.suppress(Exception):
                    await cdp.detach()
            return
        try:
            cdp = await errand.context.new_cdp_session(errand.page)
            cdp.on("Page.screencastFrame",
                   lambda event: asyncio.ensure_future(self._frame(errand, cdp, event)))
            await cdp.send("Page.startScreencast", {
                "format": "jpeg", "quality": FRAME_QUALITY,
                "maxWidth": 2 * VIEWPORT["width"], "maxHeight": HEIGHTS[1],
                # Every one: a page that has finished loading paints once, and
                # asking for every second frame skips exactly that one.
                "everyNthFrame": 1})
        except Exception:
            log.warning("the browser's screen could not be streamed", exc_info=True)
            return
        errand.cdp, errand.casting = cdp, True
        # The screencast only sends a frame when something changes, so a page
        # standing still would be a black box to whoever just opened it.
        await self._still(errand)

    async def _still(self, errand: Errand) -> None:
        try:
            shot = await errand.page.screenshot(type="jpeg", quality=FRAME_QUALITY,
                                                timeout=10000)
        except Exception:
            return
        await self._send_frame(errand, base64.b64encode(shot).decode(),
                               errand.width, errand.height)

    async def _frame(self, errand: Errand, cdp, event: dict) -> None:
        """One picture from the screencast.

        Acknowledged at once, every time. Chromium sends nothing more until a
        picture is acknowledged and does not go back for one it skipped, so a
        page that changed while an acknowledgement was held back - to pace the
        stream - stayed on the screen as it was before, with a title saying it
        had moved on. The pacing is in the sending instead: the newest picture
        is kept, and goes out at most every `FRAME_GAP`.
        """
        if cdp is not errand.cdp:
            return
        with contextlib.suppress(Exception):
            await cdp.send("Page.screencastFrameAck", {"sessionId": event.get("sessionId")})
        if not self._watchers(errand.key):
            await self._cast(errand, False)
            return
        meta = event.get("metadata") or {}
        errand.latest = (event.get("data") or "",
                         meta.get("deviceWidth") or errand.width,
                         meta.get("deviceHeight") or errand.height)
        if errand.sending is None or errand.sending.done():
            errand.sending = asyncio.create_task(self._send_latest(errand))

    async def _send_latest(self, errand: Errand) -> None:
        while errand.latest is not None:
            wait = FRAME_GAP - (time.monotonic() - errand.sent_at)
            if wait > 0:
                await asyncio.sleep(wait)
            latest, errand.latest = errand.latest, None
            if latest is None:
                break
            errand.sent_at = time.monotonic()
            await self._send_frame(errand, *latest)

    async def _send_frame(self, errand: Errand, data: str, width, height) -> None:
        if not data:
            return
        message = {"type": "browser_frame", "data": data,
                   "width": width, "height": height}
        for tab in self._watchers(errand.key):
            with contextlib.suppress(Exception):
                await tab.send(message)

    # --- the person's side -------------------------------------------------

    async def from_tab(self, tab, message: dict) -> None:
        """One of the `browser_*` messages from a page, from the person."""
        who = getattr(tab, "me", None)
        if who is None:
            return
        key = (who.org_id, who.user_id)
        kind = message.get("type")
        errand = self._errands.get(key)
        if kind == "browser_watch":
            tab.web_watching = bool(message.get("on"))
            if tab.web_watching:
                tab.web_shape = (message.get("w"), message.get("h"), bool(message.get("phone")))
            if errand is not None:
                # The newest screen watching decides the shape: this one, or
                # the one still watching after this one stopped.
                left = [t for t in self._watchers(key)]
                if tab.web_watching:
                    await self._fit(errand, *tab.web_shape)
                elif left:
                    await self._fit(errand, *getattr(left[-1], "web_shape", (0, 0, False)))
            await tab.send(self.picture(who))
            if errand is not None:
                if tab.web_watching and errand.casting:
                    await self._still(errand)
                await self._cast(errand, bool(self._watchers(key)))
            return
        if kind == "browser_forget":
            if errand is not None:
                await self.close(key, save=False)
            forgot = False
            if self.logins is not None:
                forgot = await asyncio.to_thread(self.logins.forget, who.user_id, who.org_id)
            await tab.send({"type": "browser_forgot", "had": forgot})
            return
        if errand is None:
            await tab.send({"type": "browser", "open": False})
            return
        if kind == "browser_stop":
            self._stopped[key] = time.time()
            await self.close(key)
            return
        if kind == "browser_take":
            if errand.control != "person":
                errand.control, errand.asked, errand.why = "person", False, ""
                errand.clicks = errand.typed = 0
                self._handed(key)
            errand.doing, errand.mark = "", None
            errand.used_at = time.time()
            await self._say(errand)
            return
        if kind == "browser_give":
            await self._give(errand)
            return
        if kind == "browser_input":
            if errand.control != "person":
                return
            errand.used_at = time.time()
            with contextlib.suppress(Exception):
                await self._person_input(errand, message)

    async def _person_input(self, errand: Errand, message: dict) -> None:
        page = errand.page
        what = message.get("kind")
        if what in ("click", "wheel", "move"):
            try:
                x = max(0.0, min(float(message.get("x")), errand.width))
                y = max(0.0, min(float(message.get("y")), errand.height))
            except (TypeError, ValueError):
                return
            if what == "click":
                await page.mouse.click(x, y)
                errand.clicks += 1
            elif what == "wheel":
                await page.mouse.move(x, y)
                await page.mouse.wheel(float(message.get("dx") or 0),
                                       float(message.get("dy") or 0))
            else:
                await page.mouse.move(x, y)
        elif what == "text":
            text = str(message.get("text") or "")[:2000]
            if text:
                # Typed as keys, the way a site that suggests as you type
                # expects to hear them; a long paste goes in whole.
                if len(text) <= 200:
                    await page.keyboard.type(text)
                else:
                    await page.keyboard.insert_text(text)
                errand.typed += 1
        elif what == "key":
            key = str(message.get("key") or "")
            if key in _KEYS or re.fullmatch(r"(?:(?:Control|Meta|Alt|Shift)\+)*[A-Za-z0-9]", key):
                await page.keyboard.press(key)
                errand.typed += 1
        elif what == "go":
            url = _address(str(message.get("url") or ""))
            if url:
                errand.tried = url
                errand.opened_site, errand.opened_at = signups.site_of(url), time.time()
                with contextlib.suppress(Exception):
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        elif what == "back":
            await self._back(errand)
        elif what == "forward":
            with contextlib.suppress(Exception):
                await page.go_forward(wait_until="domcontentloaded", timeout=15000)

    async def _give(self, errand: Errand) -> None:
        """The person hands the browser back to Rouh."""
        was_person = errand.control == "person"
        asked = errand.asked
        clicks, typed = errand.clicks, errand.typed
        errand.control, errand.asked, errand.why = "rouh", False, ""
        errand.used_at = time.time()
        await self._save(errand)
        await self._say(errand)
        if not was_person:
            return
        # Rouh hears about it when it asked for it, or when it was in the
        # middle of something: a person who took the browser to look at a
        # page on their own has not asked Rouh to do anything.
        if not asked and time.time() - errand.rouh_used_at > ERRAND_FRESH:
            return
        opening = ("The person did what you handed the browser over for, and has handed "
                   "it back to you." if asked else
                   "The person took the browser over while you were using it, and has "
                   "handed it back to you.")
        # The address without its query: a form that sent what they typed in
        # the address is still not going to hand it to Rouh this way.
        note = (f"[{opening} It is at {_bare(_page_url(errand.page))}, on a page titled "
                f"{json.dumps(errand.page_title or 'untitled')}. While they had it they "
                + (f"clicked {_times(clicks)} and " if clicks else "clicked nothing and ")
                + ("typed on the page; what they typed is not shown to you. " if typed
                   else "typed nothing. ")
                + "Carry on with the errand from here, starting with "
                "look, or say in a sentence that it is done if it is.]")
        with contextlib.suppress(Exception):
            await self._announce(note, errand.chat)

    # --- Rouh's side -------------------------------------------------------

    async def act(self, who, chat: str, args: dict) -> str:
        """One `browser` tool call. Returns the page, boxed as somebody
        else's words, or a sentence of Rouh's own (`untrusted.ours`)."""
        if who is None:
            return untrusted.ours(
                "There is nobody signed in on this turn, so there is no browser to use.")
        action = str(args.get("action") or "").strip().lower()
        if action not in ACTIONS:
            return untrusted.ours(
                f"There is no browser action called {action!r}. It is one of: "
                + ", ".join(ACTIONS) + ".")
        key = (who.org_id, who.user_id)
        errand = self._errands.get(key)
        if action == "close":
            if errand is None:
                return untrusted.ours("The browser was not open.")
            await self.close(key)
            return untrusted.ours("The browser is closed. The logins in it are kept "
                                  "for next time.")
        if errand is None:
            if action != "open":
                return untrusted.ours("The browser is not open. Use open with an "
                                      "address first.")
            stopped = self._stopped.pop(key, 0.0)
            if time.time() - stopped < 60:
                return untrusted.ours(
                    "The person pressed Stop on the browser a moment ago. Do not open "
                    "it again unless they have asked you to since then; if they have, "
                    "call open again.")
            try:
                errand = await self._open(who, chat)
            except CannotBrowse as exc:
                return untrusted.ours(f"The browser cannot be used here: {exc}.")
            fresh = True
        else:
            # A browser Rouh has not touched for a couple of minutes is a new
            # errand, and is shown to the person the way a new browser is.
            fresh = time.time() - errand.rouh_used_at > 120
        if chat:
            errand.chat = chat
        if errand.control == "person":
            return untrusted.ours(
                "The person has the browser now"
                + (f", for what you asked: {errand.why}" if errand.why else "")
                + ". Do not use it until they hand it back: end your turn, and you "
                  "will be told when they do.")
        async with errand.lock:
            errand.used_at = errand.rouh_used_at = time.time()
            self._touch(errand, pressing=action in ("click", "press", "select")
                        or (action == "type" and bool(args.get("submit"))))
            try:
                return await self._do(errand, action, args, fresh)
            finally:
                errand.doing, errand.mark = "", None
                if self._errands.get(key) is errand:
                    self._touch(errand)
                    await self._say(errand)

    async def _do(self, errand: Errand, action: str, args: dict, fresh: bool) -> str:
        page = errand.page
        if action == "open":
            url = _address(str(args.get("url") or ""))
            if not url:
                return untrusted.ours("That is not a web address. Give one starting "
                                      "with https:// or a site's name, such as "
                                      "booking.com.")
            if rouhlinks.own(url, self.cfg):
                return untrusted.ours(_OWN_REFUSED.format(url=url))
            errand.doing = f"Opening {_short(url)}"
            errand.tried = url
            errand.opened_site, errand.opened_at = signups.site_of(url), time.time()
            await self._say(errand, show=fresh)
            since = time.time()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:
                why = _not_reached(self.gate, (urlsplit(url).hostname or "").lower(), since, exc)
                if why:
                    return untrusted.ours(why[:1].upper() + why[1:] + ".")
                return untrusted.ours(f"The page would not load: {_first_line(exc)}.")
            await _settle(page)
            return await self._report(errand)
        if action == "look":
            if fresh:
                await self._say(errand, show=True)
            return await self._report(errand)
        if action == "back":
            errand.doing = "Going back"
            await self._say(errand)
            await self._back(errand)
            await _settle(errand.page)
            return await self._report(errand)
        if action == "press":
            key = str(args.get("key") or "").strip()
            if key not in _KEYS and not re.fullmatch(r"\S", key):
                return untrusted.ours(
                    "Press takes one key: " + ", ".join(sorted(_KEYS))
                    + ", or a single character.")
            if key in ("Enter", "Space", " "):
                # Enter sends the form its field is in, and Space presses the
                # button that has the focus: the commitment, from the keyboard.
                held = await self._held(errand, None, f"press {key} there",
                                        enter=key == "Enter")
                if held:
                    return held
            errand.doing = f"Pressing {key}"
            await self._say(errand)
            await page.keyboard.press("Shift+Tab" if key == "Shift+Tab" else key)
            await _settle(page)
            return await self._report(errand)
        if action == "hand_over":
            why = " ".join(str(args.get("why") or "").split())[:300]
            already = errand.control == "person"
            errand.control, errand.asked, errand.why = "person", True, why
            errand.clicks = errand.typed = 0
            self._handed(errand.key)
            await self._say(errand, show=True)
            if not already:
                await self._phone_step(errand, why)
            return untrusted.ours(
                "The browser is the person's now, and their screen shows it with your "
                "reason. End your turn: tell them in one short sentence what to do in "
                "it and to press Hand back when they are done. Do not use the browser "
                "until then; you will be told when they hand it back.")
        # What is left acts on one element, named by its ref.
        ref = str(args.get("ref") or "").strip()
        if not _REF.match(ref):
            return untrusted.ours(
                "That needs the ref of the thing on the page, such as e12, from the "
                "last page you were given. Use look to read the page again.")
        target = page.locator(f"aria-ref={ref}")
        name = _named(errand.outline, ref)
        try:
            await target.scroll_into_view_if_needed(timeout=4000)
            box = await target.bounding_box(timeout=4000)
        except Exception:
            return untrusted.ours(
                f"There is no {ref} on the page any more. Use look to read it again "
                "and take the ref from that.")
        errand.mark = ({k: round(float(box[k]), 1) for k in ("x", "y", "width", "height")}
                       if box else None)
        if action == "click":
            held = (await self._guard(errand, target, name or ref)
                    or await self._held(errand, target, f"press {name or ref}"))
            if held:
                return held
            errand.doing = f"Clicking {name}" if name else "Clicking"
            await self._say(errand)
            await asyncio.sleep(0.35)          # long enough to see the ring
            try:
                await target.click(timeout=8000)
            except Exception as exc:
                return untrusted.ours(f"That could not be clicked: {_first_line(exc)}.")
            await _settle(page)
            return await self._report(errand)
        if action == "select":
            option = str(args.get("text") or args.get("option") or "").strip()
            if not option:
                return untrusted.ours("Select needs text: the words of the option to pick.")
            errand.doing = f"Picking {json.dumps(option)}" + (f" in {name}" if name else "")
            await self._say(errand)
            try:
                await target.select_option(label=option, timeout=8000)
            except Exception:
                try:
                    await target.select_option(value=option, timeout=4000)
                except Exception as exc:
                    return untrusted.ours(
                        f"That option could not be picked: {_first_line(exc)}.")
            await _settle(page)
            return await self._report(errand)
        if action == "fill_password":
            return await self._fill_password(errand, target, name or ref)
        # type
        text = str(args.get("text") if args.get("text") is not None else "")
        kind = await _field_kind(target)
        grant = await self._grant(errand) if kind in ("password", "email") else None
        if kind in SECRET_KINDS:
            if kind == "password" and grant is not None:
                return untrusted.ours(
                    "That field is the new account's password, and you never type it. Use "
                    "fill_password with this ref: it fills in the password sealed for this "
                    "sign-up, the one the person set or gave for it, without you passing it.")
            return untrusted.ours(
                "That field is for a password, a code or a card, and you never type "
                "those. Hand the browser over to the person with hand_over and say "
                "what is left for them to fill in.")
        if kind == "email" and grant is not None and grant.email and "@" in text \
                and "".join(text.split()).lower() != grant.email:
            return untrusted.ours(
                f"The sign-up the person authorized on {grant.site} is for {grant.email}, "
                "and only that account. Type that address, or ask them.")
        if args.get("submit"):
            held = await self._held(errand, target, f"press Enter in {name or ref}",
                                    enter=True)
            if held:
                return held
        errand.doing = "Typing" + (f" into {name}" if name else "")
        await self._say(errand)
        try:
            await target.fill(text, timeout=8000)
        except Exception:
            try:
                await target.click(timeout=4000)
                await page.keyboard.press("Control+A")
                await page.keyboard.type(text)
            except Exception as exc:
                return untrusted.ours(f"That could not be typed into: {_first_line(exc)}.")
        if args.get("submit"):
            await target.press("Enter")
        await _settle(page)
        return await self._report(errand)

    async def _grant(self, errand: Errand):
        """The sign-up the person authorized that covers the page open now, or None.

        Asked of the database each time, so one withdrawn on the Sign-ups page stops
        at the next press. Anything that goes wrong asking is no sign-up at all.
        """
        url = _page_url(errand.page)
        if not url:
            return None
        try:
            return await asyncio.to_thread(signups.grant_here, errand.user_id,
                                           errand.org_id, url)
        except Exception:  # noqa: BLE001 - no grant is the safe answer
            log.warning("the sign-ups could not be read", exc_info=True)
            return None

    async def _held(self, errand: Errand, target, what: str, *, enter: bool = False) -> str:
        """The refusal for a press that is the person's, or "" when it may go.

        On a site with a sign-up the person authorized, every press is judged by
        what that sign-up covers (`_signup_step`), with nobody watching or not.
        Anywhere else, only a turn nobody is watching is held to the person's
        steps (`_commitment`), as it always was.
        """
        url = _page_url(errand.page)
        if (target is None or enter) and errand.card_site and signups.covers(errand.card_site, url):
            # On a checkout with the card in it, a key that sends the form could be the
            # order itself, which is pressed only with place_order.
            seen = await self._read(errand, target, protected.COMMIT_SCRIPT)
            why = protected.commit_step(seen, enter=enter)
            if why:
                return untrusted.ours(
                    f"The next step, to {what}, is refused: {why}, on a checkout with the card "
                    "in it, where it could place the order. Press the page's own buttons with "
                    "click, and the button that places the order only with place_order.")
        if protected.away() and self._purchase_on(errand.key, url) is not None:
            return await self._checkout_step(errand, target, what, enter=enter)
        grant = await self._grant(errand)
        if grant is not None:
            return await self._signup_step(errand, grant, target, what, enter=enter)
        if protected.away():
            return await self._commitment(errand, target, what, enter=enter)
        return ""

    @staticmethod
    async def _read(errand: Errand, target, script: str):
        """What `script` says of the element about to be pressed (or the one with the focus),
        or None when it could not be read."""
        try:
            if target is None:
                return await errand.page.evaluate(f"({script})(document.activeElement)")
            return await target.evaluate(script, timeout=4000)
        except Exception:
            return None

    async def _guard(self, errand: Errand, target, thing: str) -> str:
        """The refusal for a click that is never Rouh's to make as a click, or "".

        Watched or not, on every site: an optional tick box - a newsletter, marketing,
        offers, making an account, saving the card - is never ticked (unticking is fine),
        and the button that places an order is pressed only with place_order, whose checks
        are the point (`rouh/purchases.py`). A shop's required terms, privacy and
        withdrawal boxes are ticked like anything else.
        """
        box = await self._read(errand, target, purchases.BOX_SCRIPT)
        if isinstance(box, dict) and box.get("box"):
            if box.get("checked"):
                return ""
            kind = purchases.box_kind(box.get("label") or "")
            if kind == "optional" or (kind == "account" and await self._grant(errand) is None):
                log.info("the browser left an optional box unticked on %s",
                         _bare(_page_url(errand.page)))
                return untrusted.ours(
                    f"Not ticked: {thing} is an optional box ("
                    + ("a newsletter, marketing or offers" if kind == "optional" else
                       "making an account, or saving the card or the details")
                    + "), and those are left as they are. Only the shop's own required "
                      "terms, privacy and withdrawal boxes are yours to tick. If the person "
                      "asked for this one in their own words, hand it over.")
            return ""
        seen = await self._read(errand, target, protected.COMMIT_SCRIPT)
        words = " ".join(str(seen.get("words") or "").split()) if isinstance(seen, dict) else ""
        if not purchases.final_press(words):
            return ""
        log.info("the browser held back a click on an order button on %s",
                 _bare(_page_url(errand.page)))
        if self._purchase_on(errand.key, _page_url(errand.page)) is not None:
            return untrusted.ours(
                f"Not pressed: {thing} places the order, and that button is pressed only "
                "with place_order, which reads the page's total and delivery address and "
                "checks them first. Call place_order with this ref.")
        return untrusted.ours(
            f"{STOPPED} The next step, to press {thing}, is refused: it places the order, and no "
            "purchase ‹owner› asked for ‹himself› covers this site. If ‹he› asked for it in ‹his› own "
            "words, call authorize_purchase with them, then fill_card, then place_order; if "
            "not, hand the browser over.")

    async def _checkout_step(self, errand: Errand, target, what: str, *,
                             enter: bool = False) -> str:
        """A press in the checkout of a purchase authorized by the owner's stored words, while
        nobody is watching: the checkout's own steps go (`purchases.checkout_step`)."""
        seen = await self._read(errand, target, protected.COMMIT_SCRIPT)
        if isinstance(seen, dict) and seen.get("field") and not enter:
            return ""
        why = purchases.checkout_step(seen)
        if not why:
            return ""
        log.info("the browser held back %s in an authorized checkout on %s: %s", what,
                 _bare(_page_url(errand.page)), why)
        return untrusted.ours(
            f"{STOPPED} The next step, to {what}, is refused: {why}, and that step is "
            f"{protected.GROUPS[protected.MONEY]}, which is the person's own while nobody "
            "is watching.")

    # --- purchases the owner authorized (`rouh/purchases.py`) -------------------

    def authorize_purchase(self, who, purchase: purchases.Purchase) -> str:
        """Keep one purchase the owner authorized, for its site, in place of any before it there;
        or why not: an order already submitted on that site and waiting to be paid, which a
        second one would order again."""
        held = self._purchases.setdefault((who.org_id, who.user_id), {})
        before = held.get(purchase.site)
        if before is not None and before.live and before.awaiting:
            return (f"an order for {before.what} was already submitted at {before.site} and "
                    "waits to be paid. Finish paying it on its payment page with fill_card and "
                    "place_order, or tell ‹owner› plainly that it is unpaid; a second one would "
                    "order it twice.")
        if before is not None and before.live and before.confirming:
            return (f"the payment for {before.what} at {before.site} was pressed and is "
                    "awaiting confirmation" + (", waiting for ‹owner›'s bank approval"
                                               if before.outcome == "bank" else "")
                    + ". A second one could pay it twice: wait for the page to confirm it, or "
                      "for ‹owner›.")
        held[purchase.site] = purchase
        return ""

    def _purchase_on(self, key: tuple[str, str], url: str):
        """The live purchase whose page this is: its shop's, or a payment page the shop sent
        the browser to."""
        site = signups.site_of(url) if url else ""
        if not site:
            return None
        held = self._purchases.get(key, {})
        found = held.get(site)
        if found is None or not found.live:
            found = next((p for p in held.values() if p.live and p.covers(site)), None)
        return found if found is not None and found.live else None

    async def _phone_step(self, errand: Errand, why: str) -> None:
        """The step the browser was handed over for, sent to the owner's phone on Telegram at
        once as well as on their screen (17 October 2026: "I should be notified on telegram
        for timely stuff like that"): what is waiting, where, for how much if an order of his
        is waiting on it, and the link to the live browser. Not a second message for a step
        he was just sent: his bank's for the purchase on this page, or a job's hand-off on
        the same site (`notices.step_told_lately`)."""
        from types import SimpleNamespace

        from . import notices

        who = SimpleNamespace(org_id=errand.org_id, user_id=errand.user_id)
        url = _page_url(errand.page) if errand.page is not None else ""
        site = signups.site_of(url) if url else ""
        purchase = self._purchase_on(errand.key, url)
        if notices.step_told_lately(who, site):
            return
        if purchase is not None and purchase.confirming and purchase.outcome == "bank":
            return
        base = str(notices.hooks.public_url or "").rstrip("/")
        owed = ""
        if purchase is not None and purchase.placed_at is None and (
                purchase.submitted_at or purchase.pressed_at or purchase.charge_id):
            total = purchase.submitted_total or purchase.amount
            owed = (f"\nThe order for {purchase.what[:120]} ({total} {purchase.currency}) is "
                    "unpaid until you do.")
        text = (f"\U0001f590 Rouh needs you in the live browser: {why or 'a step only you can do'}"
                f"\nOn {urlsplit(url).hostname or site or 'the page it is on'}.{owed}"
                + (f"\n\n{base}/browser" if base else ""))
        try:
            await notices.phone(text[:1500], kind="browser", who=who, link="/browser",
                                at_once=True)
            notices.step_told(who, site)
        except Exception:  # noqa: BLE001 - the screen already shows the hand-over
            log.exception("a hand-over could not be sent to the phone")

    def _handed(self, key: tuple[str, str]) -> None:
        """The person has the browser while an order of theirs waits to be paid."""
        for purchase in self._purchases.get(key, {}).values():
            if purchase.awaiting:
                purchase.handed = True

    def purchase_here(self, who):
        """The live purchase the owner authorized on the site the browser is on, or None."""
        errand = self._errands.get((who.org_id, who.user_id)) if who is not None else None
        if errand is None or errand.page is None:
            return None
        return self._purchase_on(errand.key, _page_url(errand.page))

    def page_site(self, who) -> str:
        """The registrable domain of the page the browser is on, or ""."""
        url = self.where(who)[0]
        return signups.site_of(url) if url else ""

    async def _page_text(self, errand: Errand) -> str:
        """What every frame of the page shows and has typed into its ordinary fields, for the
        code to read the total and the delivery address from. Never said to anybody."""
        parts = []
        for frame in list(errand.page.frames):
            try:
                parts.append(str(await asyncio.wait_for(
                    frame.evaluate(purchases.PAGE_TEXT_SCRIPT), timeout=5) or ""))
            except Exception:  # noqa: BLE001 - a frame that cannot be read adds nothing
                continue
        text = "\n".join(parts)
        if errand.card_values:
            text = scrub_card(text, errand.card_values, errand.card_last4)
        if errand.secret_values:
            text = signups.scrub(text, errand.secret_values)
        return text

    async def _seen(self, errand: Errand) -> list[tuple[str, list[str], str]]:
        """Every tab of the browser as the code reads it for what became of a payment: its
        address, the addresses of its frames after it, and what all of them show, card and
        secrets scrubbed. Never said to anybody."""
        out = []
        pages = [p for p in list(errand.context.pages) if not p.is_closed()][:8]
        if errand.page is not None and errand.page in pages:
            pages.remove(errand.page)
            pages.insert(0, errand.page)
        for page in pages:
            frames = list(page.frames)[:30]
            urls = [_page_url(page)] + [f.url for f in frames[1:] if f.url]
            parts = []
            for frame in frames:
                try:
                    parts.append(str(await asyncio.wait_for(
                        frame.evaluate(purchases.PAGE_TEXT_SCRIPT), timeout=5) or ""))
                except Exception:  # noqa: BLE001 - a frame that cannot be read adds nothing
                    continue
            text = "\n".join(parts)
            if errand.card_values:
                text = scrub_card(text, errand.card_values, errand.card_last4)
            if errand.secret_values:
                text = signups.scrub(text, errand.secret_values)
            out.append((urls[0], urls, text))
        return out

    async def _outcome(self, errand: Errand, purchase) -> tuple[str, str]:
        """What the tabs show became of the purchase's payment since its press
        (`purchases.outcome_of`): a decline on any of them first, then the bank's step,
        then a confirmation on the shop's own pages or its payment pages."""
        found: dict[str, str] = {}
        for url, urls, text in await self._seen(errand):
            kind, words = purchases.outcome_of(
                text, urls, before=purchase.before_text, before_urls=purchase.before_urls,
                ours=purchase.covers(signups.site_of(url) if url else ""))
            if kind and kind not in found:
                found[kind] = words
        for kind in ("failed", "bank", "paid"):
            if kind in found:
                return kind, found[kind]
        return "", ""

    def watch(self, who, purchase) -> None:
        """Watch a purchase whose Pay was pressed until its pages say what became of it, and
        have it written down and told (`payments.settle`)."""
        key = (who.org_id, who.user_id)
        if purchase.watching is not None and not purchase.watching.done():
            return
        purchase.watching = asyncio.create_task(self._watch(key, purchase),
                                                name=f"payment {purchase.site}")

    async def _watch(self, key: tuple[str, str], purchase) -> None:
        from types import SimpleNamespace

        from . import payments

        who = SimpleNamespace(org_id=key[0], user_id=key[1])
        try:
            while purchase.confirming:
                errand = self._errands.get(key)
                now = time.time()
                if errand is None or purchase.expires_at <= now:
                    if purchase.outcome != "bank":
                        await payments.settle(who, purchase, "unconfirmed",
                                              "the browser was closed" if errand is None
                                              else "its authorization ran out")
                    return
                kind, words = await self._outcome(errand, purchase)
                if kind in ("paid", "failed"):
                    await payments.settle(who, purchase, kind, words)
                    return
                if kind == "bank" and purchase.outcome != "bank":
                    await payments.settle(who, purchase, "bank", words)
                elif (purchase.outcome == "bank" and not purchase.reminded
                      and purchase.bank_at is not None
                      and now - purchase.bank_at >= purchases.REMIND_MINUTES * 60):
                    purchase.reminded = True
                    await payments.settle(who, purchase, "remind")
                await asyncio.sleep(purchases.WATCH_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("a payment on %s could not be watched", purchase.site)

    async def place_order(self, who, chat: str, ref: str, check) -> dict:
        """Press the button that places the order of the purchase authorized on this page,
        once `check(text)`, given what the page shows, finds nothing wrong.

        Called only by `payments.place_order`. The element must read as an order button, and
        the page is read, checked and pressed under the browser's one lock, so nothing moves
        in between. Answers {"pressed", "said", "page", "bank"}: whether it was pressed, the
        refusal when not, the page afterwards, and whether the page then asks for the
        bank's approval or a code. A press is never a payment: "outcome" and "words" are
        what the pages showed in the moments after it (`purchases.outcome_of`), "" for
        nothing yet, and the purchase keeps what they showed before it, for `watch`.
        """
        errand = self._errands.get((who.org_id, who.user_id)) if who is not None else None
        if errand is None or errand.page is None:
            raise CannotBrowse("the browser is not open")
        if errand.control == "person":
            raise CannotBrowse("the person has the browser now")
        if chat:
            errand.chat = chat
        ref = str(ref or "").strip()
        if not _REF.match(ref):
            return {"pressed": False, "said": "place_order needs the ref of the button that "
                                              "places the order, such as e12, from the latest page."}
        async with errand.lock:
            errand.used_at = errand.rouh_used_at = time.time()
            page = errand.page
            target = page.locator(f"aria-ref={ref}")
            name = _named(errand.outline, ref) or ref
            try:
                await target.scroll_into_view_if_needed(timeout=4000)
                box = await target.bounding_box(timeout=4000)
            except Exception:
                return {"pressed": False, "said": f"There is no {ref} on the page any more. Use "
                                                  "look to read it again and take the ref from that."}
            seen = await self._read(errand, target, protected.COMMIT_SCRIPT)
            words = " ".join(str(seen.get("words") or "").split()) if isinstance(seen, dict) else ""
            if not (purchases.final_press(words) or protected.COMMIT.search(words)
                    or (isinstance(seen, dict) and seen.get("submits"))):
                return {"pressed": False,
                        "said": f"{name} does not read as the button that places the order "
                                f"(it says {words[:60]!r}). Press the checkout's other buttons "
                                "with click; place_order is for the last one only."}
            why = await check(await self._page_text(errand), await self._payment(errand))
            if why:
                return {"pressed": False, "said": why}
            # The shop may send the browser on to its payment page with this press.
            pressing = self._purchase_on(errand.key, _page_url(page))
            for purchase in self._purchases.get(errand.key, {}).values():
                if purchase.live and purchase.covers(signups.site_of(_page_url(page))):
                    purchase.touched_at = time.time()
                    purchase.follow()
            if pressing is not None:
                # What every tab shows before the press, so only what it brings counts.
                seen = await self._seen(errand)
                pressing.before_text = "\n".join(t for _u, _us, t in seen)
                pressing.before_urls = [u for _u, us, _t in seen for u in us]
            errand.mark = ({k: round(float(box[k]), 1) for k in ("x", "y", "width", "height")}
                           if box else None)
            errand.doing = f"Placing the order: {name}"
            try:
                await self._say(errand)
                await asyncio.sleep(0.35)
                try:
                    await target.click(timeout=8000)
                except Exception as exc:
                    return {"pressed": False,
                            "said": f"That could not be clicked: {_first_line(exc)}."}
                await _settle(page)
                with contextlib.suppress(Exception):
                    await page.wait_for_load_state("networkidle", timeout=5000)
                page = errand.page
                outcome, words = (await self._outcome(errand, pressing)
                                  if pressing is not None else ("", ""))
                bank = outcome == "bank"
                said = await self._report(errand)
                now_at = _page_url(page)
            finally:
                errand.doing, errand.mark = "", None
                await self._say(errand)
        log.info("the browser placed the order on %s with %s", _bare(_page_url(page)), name)
        return {"pressed": True, "said": "", "page": said, "name": name, "bank": bank,
                "outcome": outcome, "words": words,
                "site": signups.site_of(now_at) if now_at else ""}

    async def _payment(self, errand: Errand) -> dict:
        """How the page says it will be paid, from every frame (`purchases.PAYMENT_SCRIPT`):
        the options picked, whether a card field is showing, and what is typed into its
        billing address fields (`purchases.BILLED_SCRIPT`). Read by the code only."""
        fields = ", ".join(sel for kind, _words, sels in CARD_FIELDS
                           if kind in ("number", "cvc") for sel in sels)
        picked: list[str] = []
        billed: list[str] = []
        card = False
        for frame in list(errand.page.frames):
            try:
                got = await asyncio.wait_for(
                    frame.evaluate(purchases.PAYMENT_SCRIPT, fields), timeout=5) or {}
            except Exception:  # noqa: BLE001 - a frame that cannot be read adds nothing
                continue
            picked += [str(x) for x in (got.get("picked") or [])][:40]
            card = card or bool(got.get("card_fields"))
            with contextlib.suppress(Exception):
                billed.append(str(await asyncio.wait_for(
                    frame.evaluate(purchases.BILLED_SCRIPT), timeout=5) or ""))
        return {"picked": picked, "card_fields": card,
                "billed": "\n".join(x for x in billed if x)}

    async def _signup_step(self, errand: Errand, grant, target, what: str, *,
                           enter: bool = False) -> str:
        """A press on the site of an authorized sign-up: the registration step goes,
        anything past it stops (`signups.judge`)."""
        try:
            if target is None:
                seen = await errand.page.evaluate(
                    f"({signups.SIGNUP_SCRIPT})(document.activeElement)")
            else:
                seen = await target.evaluate(signups.SIGNUP_SCRIPT, timeout=4000)
        except Exception:
            seen = None
        why = signups.judge(seen, enter=enter)
        if not why:
            if protected.commit_step(seen, enter=enter):
                log.info("the browser pressed the authorized sign-up's step on %s (grant %s)",
                         grant.site, grant.id)
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(signups.note, grant, "submitted")
            return ""
        log.info("the browser held back %s on %s, past the authorized sign-up: %s",
                 what, _bare(_page_url(errand.page)), why)
        return untrusted.ours(
            f"{STOPPED} The next step, to {what}, is refused: {why}. The sign-up the "
            f"person authorized on {grant.site} covers filling in its form and pressing "
            "its registration button, and nothing past that. Stop here: hand the browser "
            "over, or ask them, and say exactly what this step is.")

    async def _fill_password(self, errand: Errand, target, name: str) -> str:
        """The password the person set for an authorized sign-up, into a new-password field.

        Opened from its seal here and handed to the page, and to nothing else: not the
        model, not the log, not the answer. Kept in memory so every outline read back
        is scrubbed of it.
        """
        kind = await _field_kind(target)
        if kind != "password":
            return untrusted.ours(
                "fill_password is only for the password field of a new account; that field "
                + ("is a log-in's password, which is the person's: hand it over."
                   if kind == "login_password" else
                   "is not one. Use type for ordinary fields; a code or a card is the "
                   "person's."))
        grant = await self._grant(errand)
        if grant is None:
            return untrusted.ours(
                "No sign-up on this site is authorized by the person, so its password is "
                "theirs to type. Hand the browser over with hand_over, or ask them whether "
                "they want you to make this account.")
        password = await asyncio.to_thread(signups.password_for, grant)
        if not password:
            # One the person gave for it in their own words in the conversation, taken from
            # their message and sealed by `signups.adopt_password`, never by the model.
            why = await asyncio.to_thread(signups.adopt_password, grant,
                                          signups.chats_for(grant, errand.chat))
            if not why:
                password = await asyncio.to_thread(signups.password_for, grant)
        if not password:
            return untrusted.ours(
                f"There is no password for the {grant.service} sign-up: none is set on the "
                f"Sign-ups page, and {why or signups.NOT_SAID}. Hand over just this field "
                "with hand_over (why: Type the password for the new "
                f"{grant.service} account), or ask them to set it on the Sign-ups page "
                f"({signups.PAGE}). Never type one yourself, and never ask them to type it "
                "into the chat.")
        errand.doing = "Filling in the new account's password" + (f" in {name}" if name else "")
        await self._say(errand)
        if password not in errand.secret_values:
            errand.secret_values.append(password)
        try:
            await target.fill(password, timeout=8000)
        except Exception:
            # Never the error's own words: they could quote what was filled.
            return untrusted.ours("That field could not be filled. Use look and try the "
                                  "field again, or hand that one field over.")
        finally:
            password = ""
        log.info("the browser filled the authorized sign-up's password on %s (grant %s)",
                 grant.site, grant.id)
        with contextlib.suppress(Exception):
            await asyncio.to_thread(signups.note, grant, "filled")
        await _settle(errand.page)
        return await self._report(errand)

    async def _commitment(self, errand: Errand, target, what: str, *, enter: bool = False) -> str:
        """The refusal for a press that pays, buys, books, submits or signs up, or "".

        Only in a turn nobody is watching (`protected.away`): that step is the
        person's. Read from the element itself - its words, and whether it
        sends a form that is not a search (`protected.commit_step`) - and
        refused when it cannot be read.
        """
        try:
            if target is None:
                seen = await errand.page.evaluate(
                    f"({protected.COMMIT_SCRIPT})(document.activeElement)")
            else:
                seen = await target.evaluate(protected.COMMIT_SCRIPT, timeout=4000)
        except Exception:
            seen = None
        why = protected.commit_step(seen, enter=enter)
        if not why:
            return ""
        log.info("the browser held back %s on %s: %s", what, _bare(_page_url(errand.page)), why)
        return untrusted.ours(
            f"{STOPPED} The next step, to {what}, is refused: {why}, and that step is "
            f"{protected.GROUPS[protected.MONEY]}, which is the person's own while nobody "
            "is watching.")

    async def fill_card(self, who, chat: str, card: dict) -> list[str]:
        """Fill the checkout's card fields on the open page with this card, in every frame.

        Called only by `payments.fill_card`, after every cap is checked and the purchase
        is written down. Answers which fields were filled, in words, never their values.
        """
        errand = self._errands.get((who.org_id, who.user_id)) if who is not None else None
        if errand is None or errand.page is None:
            raise CannotBrowse("the browser is not open")
        if errand.control == "person":
            raise CannotBrowse("the person has the browser now")
        if chat:
            errand.chat = chat
        from . import purchases

        values = _card_values(card)
        filled: list[str] = []
        errand.bill_note = ""
        async with errand.lock:
            errand.used_at = errand.rouh_used_at = time.time()
            errand.doing = "Filling in the card from the vault"
            await self._say(errand)
            try:
                frames = list(errand.page.frames)
                # Only where the card itself goes: a page with no card number field gets no
                # billing address either, nor a charge for nothing.
                if not await _showing(frames, CARD_FIELDS[0][2]):
                    frames = []
                elif values.get("line1") and not purchases.same_place(values, errand.shipped):
                    # A billing address of its own, where the page would bill the delivery
                    # address by a box ticked for it.
                    errand.bill_note = await _bill_apart(frames)
                    if errand.bill_note:
                        with contextlib.suppress(Exception):
                            await _settle(errand.page)
                        frames = list(errand.page.frames)
                for frame in frames:
                    for kind, words, selectors in CARD_FIELDS:
                        value = values.get(kind)
                        if not value or words in filled:
                            continue
                        side = "billing" if kind in _CARD_BILLING_KINDS else ""
                        if await _fill_first(frame, selectors, value, side):
                            filled.append(words)
            finally:
                errand.doing, errand.mark = "", None
                await self._say(errand)
            if filled:
                errand.card_site = signups.site_of(_page_url(errand.page))
                errand.card_values = sorted(
                    {v for k, v in values.items() if k in _SCRUBBED and v}
                    | {values.get("exp", "").replace(" ", "")}
                    | set(_number_forms(values.get("number", ""))), key=len, reverse=True)
                errand.card_last4 = values.get("number", "")[-4:]
            with contextlib.suppress(Exception):
                await _settle(errand.page)
        values.clear()
        return filled

    async def fill_shipping(self, who, chat: str, values: dict, billing: dict | None = None
                            ) -> dict:
        """Fill the open checkout's delivery fields with one of the person's shipping options
        (`shipping.fill_values`), and its billing address form, when it shows one, with the
        billing entity of the card that will pay (`payments.billing_values`), in every frame.

        The two are never mixed: a field marked billing, Shopware's main billingAddress[...]
        form among them, is filled only from `billing`, and a delivery field never with it.
        When the page shows its billing form and the delivery address is another place, the
        page's own box for a separate delivery address is ticked (`_APART`) and the delivery
        goes there; with no such box, the delivery address is filled nowhere, so the order is
        never billed to it (fr_cd4ba48083df). With no billing address to give, the billing
        form is left empty. Nothing is pressed. A field found by no name is looked for by its
        label (`SHIP_LABELS`). Entrance, floor and apartment go into fields of their own where
        the page has them, else into the second address line, else after the street.

        Answers {"filled", "billed", "billing_form", "no_billing", "apart", "no_shipping_form"}:
        the delivery fields filled, the billing ones, whether the page has a billing form,
        whether it was left empty for want of an address, whether the separate delivery form
        was opened, and whether there was none to put the delivery address in.
        """
        from . import purchases

        errand = self._errands.get((who.org_id, who.user_id)) if who is not None else None
        if errand is None or errand.page is None:
            raise CannotBrowse("the browser is not open")
        if errand.control == "person":
            raise CannotBrowse("the person has the browser now")
        if chat:
            errand.chat = chat
        out = {"filled": [], "billed": [], "billing_form": False, "no_billing": False,
               "apart": False, "no_shipping_form": False}
        async with errand.lock:
            errand.used_at = errand.rouh_used_at = time.time()
            errand.doing = "Filling in where it is delivered"
            await self._say(errand)
            try:
                frames = list(errand.page.frames)
                if await _showing(frames, _BILL_FORM):
                    out["billing_form"] = True
                    if billing and billing.get("line1"):
                        errand.doing = "Filling in where it is billed"
                        await self._say(errand)
                        out["billed"] = await _fill_set(frames, BILL_FIELDS, billing, "billing")
                    else:
                        out["no_billing"] = True
                    same = bool(billing) and purchases.same_place(billing, values)
                    if not same and not await _showing(frames, _SHIP_FORM):
                        if await _open_apart(frames):
                            out["apart"] = True
                            with contextlib.suppress(Exception):
                                await _settle(errand.page)
                            frames = list(errand.page.frames)
                        if not await _showing(frames, _SHIP_FORM):
                            out["no_shipping_form"] = True
                    errand.doing = "Filling in where it is delivered"
                    await self._say(errand)
                if not out["no_shipping_form"]:
                    out["filled"] = await _fill_delivery(frames, values)
                    errand.shipped = {k: str(values.get(k) or "")
                                      for k in ("line1", "city", "postal_code", "country")}
            finally:
                errand.doing, errand.mark = "", None
                await self._say(errand)
            with contextlib.suppress(Exception):
                await _settle(errand.page)
        return out

    async def fill_billing(self, who, chat: str, billing: dict) -> list[str]:
        """Fill the open page's billing address with the billing entity of the card that will
        pay (`payments.billing_values`): its fields marked billing (`BILL_FIELDS`), else, on a
        page that marks none, such as the address editor a shop opens for "Change billing
        address", its plain address fields that are not the delivery address's
        (`CARD_FIELDS`' address part). Nothing is pressed. Answers what was filled."""
        errand = self._errands.get((who.org_id, who.user_id)) if who is not None else None
        if errand is None or errand.page is None:
            raise CannotBrowse("the browser is not open")
        if errand.control == "person":
            raise CannotBrowse("the person has the browser now")
        if chat:
            errand.chat = chat
        async with errand.lock:
            errand.used_at = errand.rouh_used_at = time.time()
            errand.doing = "Filling in where it is billed"
            await self._say(errand)
            try:
                frames = list(errand.page.frames)
                if await _showing(frames, _BILL_FORM):
                    filled = await _fill_set(frames, BILL_FIELDS, billing, "billing")
                else:
                    filled = await _fill_set(frames, _BILL_LOOSE, billing, "billing", SHIP_LABELS)
            finally:
                errand.doing, errand.mark = "", None
                await self._say(errand)
            with contextlib.suppress(Exception):
                await _settle(errand.page)
        return filled

    def bill_note(self, who) -> str:
        """What the last card fill did so the order is not billed to the delivery address."""
        errand = self._errands.get((who.org_id, who.user_id)) if who is not None else None
        return errand.bill_note if errand is not None else ""

    def where(self, who) -> tuple[str, str]:
        """The address and title of the page the person's browser is on, or two blanks."""
        errand = self._errands.get((who.org_id, who.user_id)) if who is not None else None
        if errand is None or errand.page is None:
            return "", ""
        return _bare(_page_url(errand.page)), errand.page_title or ""

    async def _report(self, errand: Errand) -> str:
        page = errand.page
        try:
            outline = await page._impl_obj._channel.send(
                "snapshotForAI", None, {"timeout": 10000})
        except Exception:
            try:
                outline = await page.locator("body").aria_snapshot(timeout=10000)
            except Exception as exc:
                return untrusted.ours(f"The page could not be read: {_first_line(exc)}.")
        errand.outline = str(outline or "")
        if errand.card_values:
            errand.outline = scrub_card(errand.outline, errand.card_values, errand.card_last4)
        if errand.secret_values:
            errand.outline = signups.scrub(errand.outline, errand.secret_values)
        with contextlib.suppress(Exception):
            errand.page_title = await page.title()
        lines = [f"Page: {errand.page_title or '(no title)'}",
                 f"Address: {_masked(_shown_url(errand))}"]
        while errand.dialogs:
            lines.append(f"The page showed a dialog, answered for you ({errand.dialogs.pop(0)})")
        body = errand.outline
        if len(body) > OUTLINE_CHARS:
            body = (body[:OUTLINE_CHARS]
                    + "\n... the rest of the page is cut off here.")
        lines.append(body)
        said = "\n".join(lines)
        if errand.secret_values:
            said = signups.scrub(said, errand.secret_values)
        grant = await self._grant(errand)
        if grant is None:
            return said
        if not grant.has_password:
            # So the model is told the truth: a password the person gave for it in their
            # own words is sealed now, before it reaches the field (`signups.adopt_password`).
            with contextlib.suppress(Exception):
                await asyncio.to_thread(signups.adopt_password, grant,
                                        signups.chats_for(grant, errand.chat))
        # Rouh's own words about the site, outside the page's box: a sentence inside
        # it is the page's, and the page is never the one to say what was authorized.
        return untrusted.ours(untrusted.wrap(said, untrusted.SOURCES["browser"])
                              + f"\n\nA sign-up covers this site: {signups.described(grant)}.")

    # --- one page, read once -------------------------------------------------

    async def read(self, url: str) -> Reading:
        """One page, read in a browser of its own that is closed again after.

        For a page web_fetch could not read (`rouh/fetchfallback.py`). Not the
        person's browser: it carries none of their logins, so it reads what
        anybody would see, and it is never on their screen. The gatekeeper and
        the jail are the Live browser's own, so it reaches the public internet
        and nothing else. Never raises: what went wrong is the reading's
        `error`.
        """
        url = _address(url)
        if not url:
            return Reading(url="", error="that is not a web address")
        if rouhlinks.own(url, self.cfg):
            # Never from outside: it is the person's own page, and a browser
            # with none of their logins reads only its sign-in page.
            return Reading(url=url, error="it is one of Rouh's own pages, which are read inside "
                                          "Rouh with read_rouh_link and never in a browser")
        jail = Jail(self.cfg)
        browser = None
        try:
            try:
                browser = await self._launch(jail)
            except CannotBrowse as exc:
                return Reading(url=url, error=f"the browser cannot be used here: {exc}")
            context = await browser.new_context(
                viewport=VIEWPORT, accept_downloads=False,
                timezone_id=clock.zone().key, locale="en-GB",
                # The Chrome it is, without "Headless" in its name. That word
                # is turned away on sight by sites that would show the same
                # page to anybody's browser, which is the page wanted here.
                user_agent=_plain_agent(browser.version))
            page = await context.new_page()
            # Nothing is left waiting on a page's own alert or question.
            page.on("dialog", lambda dialog: asyncio.ensure_future(_dismiss(dialog)))
            return await asyncio.wait_for(_read(page, url, self.gate), READ_SECONDS)
        except asyncio.TimeoutError:
            log.warning("reading %s in the browser took more than %d seconds", url,
                        READ_SECONDS)
            return Reading(url=url, error=f"the page was still loading after {READ_SECONDS} "
                                          "seconds, so it was left")
        except Exception as exc:
            log.warning("a page could not be read in the browser", exc_info=True)
            return Reading(url=url, error=f"the browser failed ({_first_line(exc)})")
        finally:
            if browser is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(browser.close(), 15)
            jail.cleanup()


async def _read(page, url: str, gate: Gatekeeper) -> Reading:
    """The page at `url`, loaded and read as the text a person would see on it."""
    # The last document the page's own frame loaded. A redirect made by the
    # page's own script lands after `goto` has already answered, and that
    # later answer is the one that says whether there is a page to read.
    landed = {}

    def note(response) -> None:
        with contextlib.suppress(Exception):
            if response.request.is_navigation_request() and response.frame == page.main_frame:
                landed["response"] = response

    page.on("response", note)
    since = time.time()
    try:
        first = await page.goto(url, wait_until="domcontentloaded", timeout=READ_LOAD_MS)
    except Exception as exc:
        why = _not_reached(gate, (urlsplit(url).hostname or "").lower(), since, exc)
        if why:
            return Reading(url=url, error=why)
        return Reading(url=url, error=f"the page would not load ({_first_line(exc)})")
    # A page drawn by its scripts has nothing on it until they have run.
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("load", timeout=READ_SCRIPTS_MS)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=READ_SCRIPTS_MS)
    title = ""
    with contextlib.suppress(Exception):
        title = " ".join(str(await page.title() or "").split())
    where = _page_url(page) or url
    answer = landed.get("response") or first
    status = answer.status if answer is not None else 0
    if status >= 400:
        headers = {}
        with contextlib.suppress(Exception):
            headers = await answer.all_headers()
        # Cloudflare says so in a header when the page is its check for bots
        # rather than the site: "Just a moment...", which a person can pass
        # and nothing here tries to.
        checked = str(headers.get("cf-mitigated") or "").lower() == "challenge"
        said = f"the site answered {status}"
        with contextlib.suppress(Exception):
            if answer.status_text:
                said += f" {answer.status_text}"
        if checked:
            said += ", with a check for bots that only a person can pass"
        elif title:
            said += f", with a page titled {json.dumps(title)}"
        return Reading(url=where, title=title, error=said, bot_check=checked)
    try:
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception as exc:
        return Reading(url=where, title=title,
                       error=f"the page could not be read ({_first_line(exc)})")
    text = _tidy(str(text or ""))
    if not text:
        return Reading(url=where, title=title,
                       error="the page loaded with nothing on it to read")
    if len(text) > PAGE_CHARS:
        text = text[:PAGE_CHARS].rstrip() + "\n... the rest of the page is cut off here."
    return Reading(url=where, title=title, text=text)


#: What a page says when the bank wants its own approval after the order button: 3-D
#: Secure, a code sent to the phone, or the bank's app. That step is the person's.
_BANK = purchases.BANK
_BANK_URL = purchases.BANK_URL


def _plain_agent(version: str) -> str:
    """What Chrome of this version calls itself on Linux when it has a window."""
    return ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version or '141.0.0.0'} Safari/537.36")


async def _dismiss(dialog) -> None:
    with contextlib.suppress(Exception):
        await dialog.dismiss()


def _tidy(text: str) -> str:
    """A page's text with the blank space a layout leaves between its parts
    closed up: no line is longer at its end than its words, and never more
    than one empty line in a row."""
    lines = [line.rstrip() for line in text.replace("\r", "").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _shown_url(errand: Errand) -> str:
    """The address to show: the page's, or the one it failed to reach."""
    url = _page_url(errand.page)
    return errand.tried if url.startswith("chrome-error:") and errand.tried else url


def _page_url(page) -> str:
    with contextlib.suppress(Exception):
        return str(page.url or "")
    return ""


#: The names of the parts of an address whose values Rouh is not shown: a
#: form that sends by GET puts what was typed into the address, and a card
#: number or a password typed by the person must not come back to the model
#: in the next page it reads.
_SECRET_QUERY = re.compile(r"passw|pwd|pass$|^pin$|cvv|cvc|csc|card|ccnum|otp|"
                           r"^code$|token|secret|auth", re.IGNORECASE)


def _masked(url: str) -> str:
    """An address with the values of anything secret in its query hidden."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.query:
        return url
    kept = []
    for pair in parts.query.split("&"):
        name = pair.split("=", 1)[0]
        kept.append(f"{name}=(hidden)" if "=" in pair and _SECRET_QUERY.search(
            unquote_plus(name)) else pair)
    return parts._replace(query="&".join(kept)).geturl()


def _bare(url: str) -> str:
    """An address without its query and its fragment."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    return f"{parts.scheme}://{parts.netloc}{parts.path}" if parts.netloc else url


#: What the browser says to one of Rouh's own addresses (`rouh/rouhlinks.py`).
_OWN_REFUSED = ("{url} is one of Rouh's own pages. It is never opened in the browser, "
                "which would see only its sign-in page: read it with read_rouh_link, which "
                "reads it inside Rouh as the person.")


def _address(said: str) -> str:
    """An address the browser may be sent to, or nothing.

    A site's bare name is taken to mean its https address, which is what a
    person means by "go to booking.com". Nothing but http and https: a file on
    this machine, a browser's own settings page or a script is not a website.
    """
    said = said.strip()
    if not said or len(said) > 2000 or any(c.isspace() for c in said):
        return ""
    if "://" not in said:
        said = "https://" + said
    try:
        parts = urlsplit(said)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    return said


def _short(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return url[:60]
    host = (parts.hostname or "")
    return host[4:] if host.startswith("www.") else host or url[:60]


def _first_line(exc: Exception) -> str:
    text = str(exc).strip().splitlines()
    first = text[0] if text else type(exc).__name__
    return first.replace("Locator.", "").replace("Page.", "")[:200]


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _named(outline: str, ref: str) -> str:
    """What the outline calls the thing with that ref: `the "Book" button`."""
    found = re.search(r'-\s+(\w+)(?:\s+"((?:[^"\\]|\\.)*)")?[^\n]*\[ref=' + re.escape(ref)
                      + r"\]", outline or "")
    if not found:
        return ""
    role, words = found.group(1), (found.group(2) or "").strip()
    role = {"textbox": "field", "combobox": "list", "searchbox": "search box",
            "checkbox": "tick box", "generic": ""}.get(role, role)
    words = words[:60]
    if words and role:
        return f"the {json.dumps(words, ensure_ascii=False)} {role}"
    if words:
        return json.dumps(words, ensure_ascii=False)
    return f"the {role}" if role else ""


async def _settle(page) -> None:
    """Give a page a moment to finish what a press started."""
    await asyncio.sleep(0.3)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("load", timeout=4000)


async def _field_kind(target) -> str:
    """What a field is, for what may be typed into it: "card", "code", "login_password"
    (an existing account's), "password" (a new one's), "email", or "" for anything else.

    A field that cannot be read is a password's, which nobody types: what cannot be
    checked is never typed into blind.
    """
    try:
        said = await target.evaluate(
            "e => [e.type || '', e.getAttribute('autocomplete') || '', e.name || '',"
            " e.id || '', e.getAttribute('aria-label') || '',"
            " e.getAttribute('placeholder') || ''].join('\\n')", timeout=4000)
    except Exception:
        return "login_password"
    return field_kind(*(str(said or "") + "\n" * 6).split("\n")[:6])


def field_kind(kind: str, autocomplete: str, *names: str) -> str:
    """`_field_kind` from what the field says of itself: its type, its autocomplete,
    and its name, id, label and placeholder."""
    kind = kind.strip().lower()
    marks = [_SECRET_AUTOCOMPLETE[p] for p in autocomplete.lower().split()
             if p in _SECRET_AUTOCOMPLETE]
    for wanted in ("card", "code", "login_password", "password"):
        if wanted in marks:
            return wanted
    names = tuple(n for n in names if n)
    if any(_CARD_NAME.search(n) for n in names):
        return "card"
    if any(_CODE_NAME.search(n) for n in names):
        return "code"
    if kind == "password" or any(_PASSWORD_NAME.search(n) for n in names):
        return "password"
    if kind == "email" or "email" in autocomplete.lower().split() \
            or any(_EMAIL_NAME.search(n) for n in names):
        return "email"
    return ""
