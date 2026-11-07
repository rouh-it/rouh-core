"""Rouh's public site: the one name every address of it is made from (task 165).

Petar, 1 November 2026: "I want you to switch everything from rouh.it to rouh.land. all services
on rouh.it should be moved to rouh.land." Until then each of Rouh's addresses on its public site
was written out where it was used: the model standard, the starting rules, the daily totals, the
birth service, the Gene Pool, the phone relay. They are all made from this now:

    ROUH_SITE_URL   the public site, with https:// and no path; https://rouh.land unless said.

Each address keeps its own setting as before (ROUH_MODEL_STANDARD_URL, ROUH_BIRTH_URL,
ROUH_RELAY_URL ...), which wins over this one for a test world or a registry of one's own.

The move is direct (Petar, 2 November 2026): rouh.land is the site, rouh.it sends nobody on and
is retired with its server. So an address a Rouh keeps in its own database from before - where
it is registered for its birth, the Gene Pool, a gene registry - is rewritten from rouh.it to
rouh.land once, by migration 0226 (`rewrite`), on every Rouh as it takes this code in. OLD_URLS
are the only origins it rewrites, and nothing calls them.

Standard library only.
"""
from __future__ import annotations

import os

#: The site's name before rouh.land: only ever rewritten away (`rewrite`), never called.
OLD_URL = "https://rouh.it"
#: Every origin of the old site an address may have been kept under.
OLD_URLS = (OLD_URL, "https://www.rouh.it")
DEFAULT_URL = "https://rouh.land"


def base() -> str:
    """The public site, such as https://rouh.land, with no slash at the end."""
    said = (os.environ.get("ROUH_SITE_URL") or "").strip().rstrip("/")
    return said or DEFAULT_URL


def url(path: str = "/") -> str:
    """An address on the public site: url("/models/standard.json")."""
    return base() + (path if path.startswith("/") else "/" + path)


def name() -> str:
    """The site's bare name, such as rouh.land, for words people read."""
    return base().split("://", 1)[-1].split("/", 1)[0]


def rewrite(address, to: str = DEFAULT_URL):
    """`address` on rouh.land when it is exactly on the old site's origin, else as it was.

    Only https://rouh.it and https://www.rouh.it themselves, any case, followed by nothing, a
    path, a query or a fragment: https://rouh.it/registry/birth/ becomes
    https://rouh.land/registry/birth/, while https://rouh.items.example, http://rouh.it and
    https://rouh.it:8443 are left alone. Anything that is not a string is given back unchanged."""
    if not isinstance(address, str):
        return address
    text = address.strip()
    low = text.lower()
    for old in OLD_URLS:
        if low == old or (low.startswith(old) and low[len(old)] in "/?#"):
            return to.rstrip("/") + text[len(old):]
    return address
