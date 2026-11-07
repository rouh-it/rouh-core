"""A picture from the web, fetched by Rouh rather than by the browser.

A card can carry a picture now (`show_on_screen`, block ``image``), and the
browser loads it straight from wherever it is. That is what a browser is for:
it costs this machine nothing, it is cached where caches are, and the picture
is on the screen in one round trip.

Some hosts will not have it. They read the ``Referer`` and refuse anything that
is not one of their own pages, or they refuse a request whose ``User-Agent``
they do not like, and what the person gets is an empty box where the whale was.
Asking again with no referrer fixes most of that and app.js does it, but not
all of it.

So a picture that still will not load is asked for a second time through here.
Rouh fetches it on its own connection, as a browser, and hands the bytes to
the page - a request the host has no reason to refuse, because it is not a
hotlink from somebody else's site.

What this will not do, and why:

- **anything that is not http or https.** A ``file:`` address here would be
  Rouh reading its own disk out to the browser.
- **anything on this machine or on this network.** Every address the name
  resolves to is checked, not only the first, and every hop of a redirect is
  checked again: a public host that answers ``302 http://127.0.0.1:8000/`` is
  the ordinary way this kind of endpoint is turned into a way of reaching
  servers only the server can see. What it cannot close is the gap between
  the check and the connection - the name is resolved twice and could answer
  differently the second time - so this is a wall against a careless address
  and a redirect, not against a host built to defeat it. The endpoint is
  behind the sign-in, which is the other half of the answer.
- **anything that does not come back as a picture.** The content type has to
  say ``image/``, and it goes out again as exactly that, with ``nosniff``, so
  no browser can decide the bytes were markup after all.
- **anything over MAX_BYTES**, counted as it streams rather than believed from
  the ``Content-Length`` header.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

#: A picture that will not fit on a card in any useful sense. Big enough for a
#: photograph off a news site, small enough that a signed-in browser cannot use
#: this to pull a film through Rouh.
MAX_BYTES = 12 * 1024 * 1024

#: The whole fetch, connection included. A card that is waiting on a picture is
#: a card that is not finished, so this is short.
TIMEOUT = 15.0

#: How many times a host may say "it is over there" before this gives up.
MAX_HOPS = 4

#: A browser's own. Several large hosts - Wikimedia among them - answer 400 to
#: a request whose agent looks like a library, which is one of the two reasons
#: a picture needs this route at all.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like "
              "Gecko) Chrome/128.0.0.0 Safari/537.36 Rouh/1.0")

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    # No referrer, so a host that refuses hotlinks has nothing to refuse.
    "Accept-Language": "en",
}

#: What goes back with the bytes. The picture is somebody's private page's
#: idea of a picture by the time it is here, so no shared cache holds it, and
#: `sandbox` means that if the address were ever opened as a page rather than
#: drawn as a picture - an SVG can be both - it would have an origin of its own
#: and nothing it could reach.
ANSWER_HEADERS = {
    "Cache-Control": "private, max-age=86400",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}


class Refused(Exception):
    """The address may not be fetched, and this says why in a sentence."""


class Unreadable(Exception):
    """The address was allowed, and fetching it did not work."""


def _address_is_public(host: str) -> None:
    """Raise unless every address this name has is out on the internet."""
    if not host:
        raise Refused("that address has no host in it")
    try:
        found = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise Unreadable(f"{host} could not be looked up ({exc})") from exc
    seen = []
    for family, _type, _proto, _canon, sockaddr in found:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:                       # a shape this cannot judge
            raise Refused(f"{host} resolves to something unrecognisable")
        seen.append(ip)
        if not ip.is_global:
            raise Refused(
                f"{host} is on this machine or on its network ({ip}), and Rouh "
                "does not fetch pictures from there")
    if not seen:
        raise Unreadable(f"{host} could not be looked up")


def check(src: str) -> str:
    """The address to fetch, or :class:`Refused` saying why not.

    Called once for what the page asked for and again for every redirect, which
    is the point: the second call is the one that catches a public host sending
    this at ``http://169.254.169.254/``.
    """
    src = (src or "").strip()
    if not src:
        raise Refused("no picture was named")
    if len(src) > 2048:
        raise Refused("that address is too long to be a picture's")
    parts = urlsplit(src)
    if parts.scheme not in ("http", "https"):
        raise Refused(f"{parts.scheme or 'that'} is not an address Rouh will fetch a picture from")
    try:
        host = parts.hostname or ""
    except ValueError as exc:                    # a bracketed address that is not one
        raise Refused(f"that address is malformed ({exc})") from exc
    _address_is_public(host)
    return src


async def fetch(src: str) -> tuple[bytes, str]:
    """The picture's bytes and its content type.

    Redirects are followed by hand rather than by httpx, because each hop has
    to go back through :func:`check` before it is connected to.
    """
    url = check(src)
    async with httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT) as client:
        for _ in range(MAX_HOPS):
            try:
                async with client.stream("GET", url, headers=REQUEST_HEADERS) as answer:
                    if answer.status_code in (301, 302, 303, 307, 308):
                        where = answer.headers.get("location") or ""
                        if not where:
                            raise Unreadable("that host redirected without saying where to")
                        url = check(urljoin(url, where))
                        continue
                    if answer.status_code != 200:
                        raise Unreadable(f"that host answered {answer.status_code}")
                    media = (answer.headers.get("content-type") or "").split(";")[0].strip().lower()
                    if not media.startswith("image/"):
                        raise Unreadable(
                            f"what came back is {media or 'of no stated kind'}, not a picture")
                    body = bytearray()
                    async for chunk in answer.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise Unreadable(
                                f"that picture is larger than {MAX_BYTES // (1024 * 1024)} MB")
                    if not body:
                        raise Unreadable("that host sent an empty picture")
                    return bytes(body), media
            except httpx.HTTPError as exc:
                raise Unreadable(f"that picture could not be fetched ({exc})") from exc
    raise Unreadable("that address redirected too many times")
