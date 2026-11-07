"""Email addresses on Rouh's pages show as themselves, never as "[email protected]".

Petar, 11 October 2026, on an iPhone: a trusted contact's case page said
"[email protected]" beside their name and in "<the contact> is trusted for [email
protected], [email protected]". That is Cloudflare's Email Address Obfuscation (Scrape
Shield), which was on for the site's zone: it rewrites anything in an HTML page that looks
like an address into a link to /cdn-cgi/l/email-protection with the address encoded, and
puts it back only with a script of Cloudflare's own that Rouh's pages do not run. Every page
of Rouh is behind a sign-in, so hiding addresses from scrapers there protects nothing and
breaks what the person reads. The zone's setting is turned off too; this holds whatever it
is set to.

Cloudflare leaves alone whatever sits between `<!--email_off-->` and `<!--/email_off-->`,
so this middleware puts the whole body of every HTML page Rouh draws between the two: one
place, for every page, whatever template drew it. A page with no body tag, such as a part
of a page drawn again by script, is wrapped whole. Streamed files, such as a task's own
pages, are left as they are: the zone's setting is what covers those.
"""
from __future__ import annotations

import re

from asgiref.sync import iscoroutinefunction, markcoroutinefunction

OFF, ON = b"<!--email_off-->", b"<!--/email_off-->"

_BODY_OPEN = re.compile(rb"<body\b[^>]*>", re.IGNORECASE)
_BODY_CLOSE = re.compile(rb"</body\s*>", re.IGNORECASE)


def unobfuscated(html: bytes) -> bytes:
    """An HTML page with its body marked for Cloudflare to leave its addresses alone."""
    if OFF in html:
        return html
    opened = _BODY_OPEN.search(html)
    closed = None
    for closed in _BODY_CLOSE.finditer(html):
        pass
    if opened and closed and closed.start() > opened.end():
        return (html[:opened.end()] + OFF + html[opened.end():closed.start()] + ON
                + html[closed.start():])
    return OFF + html + ON


class AddressesAsThemselves:
    """Every HTML page's body between `<!--email_off-->` and `<!--/email_off-->`."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._async = iscoroutinefunction(self.get_response)
        if self._async:
            markcoroutinefunction(self)

    def __call__(self, request):
        if self._async:
            return self._acall(request)
        return self._mark(self.get_response(request))

    async def _acall(self, request):
        return self._mark(await self.get_response(request))

    @staticmethod
    def _mark(response):
        kind = str(response.get("Content-Type") or "").lower()
        if getattr(response, "streaming", False) or not kind.startswith("text/html") \
                or response.get("Content-Encoding"):
            return response
        response.content = unobfuscated(response.content)
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response
