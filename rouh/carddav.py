"""CardDAV, as iCloud speaks it: finding the address book, and reading and
writing the cards in it.

Apple publishes no contacts API. What it does have is CardDAV (RFC 6352) at
``contacts.icloud.com``, signed in to with the Apple ID and an app-specific
password - never the real Apple ID password, which iCloud refuses here anyway
once two-factor authentication is on, and which is on for every Apple ID now.

Five things this does, each one request or a few:

1. **Where the address book is.** A PROPFIND on the root for
   ``current-user-principal`` names the person (``/1234567890/principal/``);
   one on that for ``addressbook-home-set`` names their home, which is on a
   partition host of its own (``https://p52-contacts.icloud.com:443/.../
   carddavhome/``); and one on the home, one level deep, finds the address
   book inside it (``card/``). iCloud has exactly one.
2. **What changed.** The ``sync-collection`` REPORT (RFC 6578): hand back the
   token from last time and iCloud names every card that changed and every one
   that went since. An empty token is the whole book. A token iCloud no longer
   honours is `TokenExpired`, and the caller starts again with an empty one.
3. **Every card and its ETag**, with a PROPFIND one level deep: the fallback
   when a server does not do ``sync-collection`` at all, compared ETag by ETag.
4. **The cards themselves**, fifty at a time, with ``addressbook-multiget``.
5. **Writing.** A PUT with ``If-Match`` on the ETag Rouh last saw, so a card
   changed on the phone in the meantime is refused (412, `Changed`) instead
   of being overwritten; ``If-None-Match: *`` for a new one; and a DELETE,
   also with ``If-Match``.

What iCloud really does with a wrong or revoked app-specific password was
measured on 24 September 2026, and it is the whole of the answer: a 401 with
an empty body and ``WWW-Authenticate: X-MobileMe-AuthToken realm="Newcastle",
Basic realm="Newcastle"``, from the root and from ``/.well-known/carddav``
alike. That is `NotAccepted`. (Without credentials at all the root answers
404, which is why nothing here ever asks without them.)

Credentials only ever go to the host this was pointed at, a host under the
same domain (the partition hosts are ``*.icloud.com``), or loopback when the
host itself is loopback, which is what a test's stand-in is. An address in a
response that points anywhere else is refused before anything is sent to it.
Nothing here logs a password, and ``redaction.py`` masks both an
app-specific password's shape and a Basic authorisation header besides.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Self

import httpx

log = logging.getLogger("rouh.contacts")

#: iCloud's own address. A setting (`config.carddav_url`) only so a test can
#: stand in for it.
ICLOUD = "https://contacts.icloud.com/"

D = "{DAV:}"
C = "{urn:ietf:params:xml:ns:carddav}"
CS = "{http://calendarserver.org/ns/}"

USER_AGENT = "Rouh/1.0 (CardDAV)"

#: How many cards one multiget asks for.
BATCH = 50

#: How many truncated pages of one sync-collection are followed before giving
#: up. A page is hundreds of cards, so this is tens of thousands.
PAGES = 100

#: Attempts at one request when iCloud is busy or the network drops it.
ATTEMPTS = 3

TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class CardDAVError(RuntimeError):
    """Something about iCloud, said in a sentence a person can act on."""


class NotAccepted(CardDAVError):
    """401: the Apple ID and app-specific password were not accepted."""


class Unreachable(CardDAVError):
    """iCloud could not be reached, or kept failing, after every attempt."""


class Refused(CardDAVError):
    """iCloud answered, and the answer was no."""

    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class Changed(CardDAVError):
    """412: the card is not the one Rouh last saw. It changed somewhere else."""


class Gone(CardDAVError):
    """404: there is no such card any more."""


class TokenExpired(CardDAVError):
    """The sync token is no longer honoured, so the whole book is read again."""


@dataclass
class Place:
    """Where one person's contacts are."""

    principal: str
    home: str
    book: str
    name: str = ""


@dataclass
class Found:
    """One card as iCloud holds it."""

    href: str
    etag: str
    data: str


@dataclass
class Changes:
    """What one sync-collection said."""

    changed: list[tuple[str, str]] = field(default_factory=list)   # (href, etag)
    removed: list[str] = field(default_factory=list)
    token: str = ""


@dataclass
class _Response:
    href: str
    status: int | None
    props: dict[str, ET.Element]
    missing: set[str]


def _xml(body: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-8"?>\n' + body).encode("utf-8")


def _status(text: str | None) -> int | None:
    parts = (text or "").split()
    if len(parts) >= 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def _parse(content: bytes) -> ET.Element:
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise Refused("iCloud answered with something that is not a CardDAV response.") from exc


def _responses(root: ET.Element) -> list[_Response]:
    out = []
    for response in root.findall(f"{D}response"):
        hrefs = [h.text or "" for h in response.findall(f"{D}href")]
        status = _status(response.findtext(f"{D}status"))
        props: dict[str, ET.Element] = {}
        missing: set[str] = set()
        for propstat in response.findall(f"{D}propstat"):
            code = _status(propstat.findtext(f"{D}status"))
            held = propstat.find(f"{D}prop")
            for prop in (list(held) if held is not None else []):
                if code == 200:
                    props[prop.tag] = prop
                else:
                    missing.add(prop.tag)
        for href in hrefs or [""]:
            out.append(_Response(href.strip(), status, props, missing))
    return out


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return True


def _is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class CardDAV:
    """One person's iCloud contacts, over one HTTP client.

    Use it as ``async with CardDAV(url, apple_id, password) as dav:``. The
    password is handed to httpx's Basic authentication and kept nowhere else,
    and this object's repr does not carry it.
    """

    def __init__(self, base_url: str, apple_id: str, password: str, *,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.base = (base_url or ICLOUD).rstrip("/") + "/"
        parts = urllib.parse.urlsplit(self.base)
        self._scheme = parts.scheme
        self._host = (parts.hostname or "").lower()
        # The partition hosts are the base's siblings: contacts.icloud.com
        # sends the person to p52-contacts.icloud.com, and the China mainland
        # service does the same under icloud.com.cn. So the base without its
        # first label is what may be trusted, never a bare "com.cn", and an
        # address given as an IP trusts nothing but itself.
        _first, _, parent = self._host.partition(".")
        self._domain = parent if parent.count(".") >= 1 and not _is_ip(self._host) \
            else self._host
        self._client = httpx.AsyncClient(
            auth=httpx.BasicAuth(apple_id, password), timeout=TIMEOUT,
            follow_redirects=False, headers={"User-Agent": USER_AGENT},
            transport=transport)

    def __repr__(self) -> str:
        return f"<CardDAV {self.base}>"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    # --- the one way a request goes out ---------------------------------------

    def _trusted(self, url: str) -> bool:
        parts = urllib.parse.urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme != self._scheme and not (_is_loopback(host) and _is_loopback(self._host)):
            return False
        if host == self._host or host == self._domain or host.endswith("." + self._domain):
            return True
        return _is_loopback(host) and _is_loopback(self._host)

    def trusts(self, url: str) -> bool:
        """Whether an address is iCloud's own, so it may be asked with the Apple ID's password."""
        return bool(url) and self._trusted(url)

    async def picture(self, url: str, *, most: int) -> bytes:
        """A contact's picture kept on iCloud's own photo server, read with the same sign-in."""
        response = await self._send("GET", url)
        if response.status_code != 200:
            raise Refused(f"iCloud answered {response.status_code} for a contact's picture.",
                          response.status_code)
        if len(response.content) > most:
            raise Refused("That contact's picture is too large to keep.")
        return response.content

    def at(self, base: str, href: str) -> str:
        return urllib.parse.urljoin(base, href)

    async def _send(self, method: str, url: str, *, body: bytes | None = None,
                    headers: dict | None = None) -> httpx.Response:
        if not self._trusted(url):
            raise Refused(f"iCloud pointed at {urllib.parse.urlsplit(url).hostname}, "
                          "which is not iCloud, so nothing was sent there.")
        last = ""
        for attempt in range(ATTEMPTS):
            try:
                response = await self._client.request(method, url, content=body,
                                                       headers=headers or {})
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                await asyncio.sleep(0.5 * (2 ** attempt) + random.random() * 0.2)
                continue
            if response.status_code == 401:
                raise NotAccepted(
                    "iCloud did not accept that Apple ID and app-specific password.")
            if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < ATTEMPTS:
                last = f"iCloud answered {response.status_code}"
                wait = response.headers.get("retry-after", "")
                await asyncio.sleep(min(float(wait), 10.0) if wait.isdigit()
                                    else 0.5 * (2 ** attempt) + random.random() * 0.2)
                continue
            if response.status_code >= 500:
                raise Unreachable(f"iCloud is not answering properly right now "
                                  f"({response.status_code}).")
            return response
        raise Unreachable(f"iCloud could not be reached ({last}).")

    async def _propfind(self, url: str, props: str, depth: str, *,
                        redirects: int = 0) -> tuple[str, list[_Response]]:
        body = _xml(f'<d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav" '
                    f'xmlns:cs="http://calendarserver.org/ns/"><d:prop>{props}</d:prop>'
                    f'</d:propfind>')
        response = await self._send("PROPFIND", url, body=body, headers={
            "Depth": depth, "Content-Type": "application/xml; charset=utf-8"})
        if response.status_code in (301, 302, 307, 308) and redirects > 0:
            target = self.at(url, response.headers.get("location", ""))
            return await self._propfind(target, props, depth, redirects=redirects - 1)
        if response.status_code != 207:
            raise Refused(f"iCloud refused to list {urllib.parse.urlsplit(url).path} "
                          f"({response.status_code}).", response.status_code, response.text[:500])
        return url, _responses(_parse(response.content))

    async def _report(self, url: str, body: str) -> httpx.Response:
        return await self._send("REPORT", url, body=_xml(body), headers={
            "Depth": "0", "Content-Type": "application/xml; charset=utf-8"})

    # --- 1. where the address book is -------------------------------------------

    async def principal(self) -> str:
        want = "<d:current-user-principal/>"
        for start in (self.base, self.at(self.base, "/.well-known/carddav")):
            try:
                url, found = await self._propfind(start, want, "0", redirects=2)
            except Refused as exc:
                if exc.status in (404, 405):
                    continue
                raise
            for response in found:
                prop = response.props.get(f"{D}current-user-principal")
                href = prop.findtext(f"{D}href") if prop is not None else None
                if href:
                    return self.at(url, href.strip())
        raise Refused("iCloud accepted the password but did not say whose contacts these are.")

    async def home(self, principal: str) -> tuple[str, str]:
        url, found = await self._propfind(
            principal, "<card:addressbook-home-set/><d:displayname/>", "0")
        for response in found:
            prop = response.props.get(f"{C}addressbook-home-set")
            href = prop.findtext(f"{D}href") if prop is not None else None
            if href:
                name = response.props.get(f"{D}displayname")
                return self.at(url, href.strip()), (name.text or "").strip() if name is not None else ""
        raise Refused("iCloud accepted the password, but this Apple ID has no contacts in "
                      "iCloud. Turn Contacts on under iCloud in the iPhone's Settings.")

    async def books(self, home: str) -> list[tuple[str, str]]:
        url, found = await self._propfind(
            home, "<d:resourcetype/><d:displayname/>", "1")
        out = []
        for response in found:
            kind = response.props.get(f"{D}resourcetype")
            if kind is None or kind.find(f"{C}addressbook") is None:
                continue
            name = response.props.get(f"{D}displayname")
            out.append((self.at(url, response.href),
                        (name.text or "").strip() if name is not None else ""))
        return out

    async def discover(self) -> Place:
        """The principal, the home and the address book, or why not."""
        principal = await self.principal()
        home, name = await self.home(principal)
        books = await self.books(home)
        if not books:
            raise Refused("iCloud accepted the password, but there is no address book in "
                          "this Apple ID's iCloud. Turn Contacts on under iCloud on the iPhone.")
        # iCloud has one, called "card". Anything else that ever has more reads
        # the one named card first, and otherwise the first it lists.
        books.sort(key=lambda b: (not b[0].rstrip("/").endswith("/card"), b[0]))
        return Place(principal=principal, home=home, book=books[0][0], name=name)

    # --- 2. what changed ------------------------------------------------------------

    async def changes(self, book: str, token: str) -> Changes:
        """Everything that changed since `token`; the whole book for ''.

        A truncated answer (507 on the book itself) is followed with the token
        it came back with, page after page, until it is whole.
        """
        out = Changes(token=token)
        for _page in range(PAGES):
            body = ('<d:sync-collection xmlns:d="DAV:">'
                    f'<d:sync-token>{_escape_xml(out.token)}</d:sync-token>'
                    '<d:sync-level>1</d:sync-level>'
                    '<d:prop><d:getetag/></d:prop></d:sync-collection>')
            response = await self._report(book, body)
            if response.status_code in (400, 403, 409, 412) and "valid-sync-token" in response.text:
                raise TokenExpired("iCloud no longer honours the sync token.")
            if response.status_code != 207:
                raise Refused(f"iCloud would not say what changed ({response.status_code}).",
                              response.status_code, response.text[:500])
            root = _parse(response.content)
            more = False
            book_path = urllib.parse.urlsplit(book).path.rstrip("/")
            for item in _responses(root):
                url = self.at(book, item.href)
                if urllib.parse.urlsplit(url).path.rstrip("/") == book_path:
                    more = more or item.status == 507
                    continue
                if item.status == 404:
                    out.removed.append(url)
                    continue
                etag = item.props.get(f"{D}getetag")
                if etag is not None and (etag.text or "").strip():
                    out.changed.append((url, etag.text.strip()))
            new = root.findtext(f"{D}sync-token")
            if new:
                out.token = new.strip()
            if not more:
                return out
        raise Refused("iCloud kept saying there was more to sync, so the sync stopped.")

    # --- 3. every card and its ETag ----------------------------------------------------

    async def listing(self, book: str) -> dict[str, str]:
        url, found = await self._propfind(book, "<d:getetag/>", "1")
        book_path = urllib.parse.urlsplit(url).path.rstrip("/")
        out = {}
        for response in found:
            href = self.at(url, response.href)
            if urllib.parse.urlsplit(href).path.rstrip("/") == book_path:
                continue
            etag = response.props.get(f"{D}getetag")
            if etag is not None and (etag.text or "").strip():
                out[href] = etag.text.strip()
        return out

    # --- 4. the cards themselves ---------------------------------------------------------

    async def fetch(self, book: str, hrefs: list[str]) -> list[Found]:
        out: list[Found] = []
        for start in range(0, len(hrefs), BATCH):
            batch = hrefs[start:start + BATCH]
            wanted = "".join(f"<d:href>{_escape_xml(urllib.parse.urlsplit(h).path)}</d:href>"
                             for h in batch)
            body = ('<card:addressbook-multiget xmlns:d="DAV:" '
                    'xmlns:card="urn:ietf:params:xml:ns:carddav">'
                    '<d:prop><d:getetag/><card:address-data/></d:prop>'
                    f'{wanted}</card:addressbook-multiget>')
            response = await self._report(book, body)
            if response.status_code != 207:
                raise Refused(f"iCloud would not hand over the cards ({response.status_code}).",
                              response.status_code, response.text[:500])
            for item in _responses(_parse(response.content)):
                data = item.props.get(f"{C}address-data")
                etag = item.props.get(f"{D}getetag")
                if data is None or not (data.text or "").strip():
                    continue
                out.append(Found(href=self.at(book, item.href),
                                 etag=(etag.text or "").strip() if etag is not None else "",
                                 data=data.text))
        return out

    # --- 5. writing -------------------------------------------------------------------------

    async def put(self, href: str, vcard: str, *, etag: str = "") -> str:
        """Write one card. `etag` for a change, none for a new card.

        Returns the ETag iCloud answered with, which is empty whenever iCloud
        changed the card on the way in (RFC 6352 5.3.4): the caller reads the
        card back rather than trusting what it sent.
        """
        headers = {"Content-Type": "text/vcard; charset=utf-8"}
        if etag:
            headers["If-Match"] = etag
        else:
            headers["If-None-Match"] = "*"
        response = await self._send("PUT", href, body=vcard.encode("utf-8"), headers=headers)
        if response.status_code == 412:
            raise Changed("That card was changed somewhere else since Rouh last read it.")
        if response.status_code not in (200, 201, 204):
            raise Refused(f"iCloud would not save the card ({response.status_code}).",
                          response.status_code, response.text[:500])
        return (response.headers.get("etag") or "").strip()

    async def delete(self, href: str, etag: str) -> None:
        response = await self._send("DELETE", href, headers={"If-Match": etag} if etag else {})
        if response.status_code == 412:
            raise Changed("That card was changed somewhere else since Rouh last read it.")
        if response.status_code == 404:
            raise Gone("That card is not in iCloud any more.")
        if response.status_code not in (200, 204):
            raise Refused(f"iCloud would not delete the card ({response.status_code}).",
                          response.status_code, response.text[:500])


def _escape_xml(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
