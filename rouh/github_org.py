"""Rouh's GitHub organisation, under either of its names (task 187, 15 November 2026).

The organisation that holds rouh-core and the images is being renamed from rouh-it to rouh-land,
in four stages: everything accepts both names (this module), every Rouh and every Mac moves onto
a release that does, the organisation is renamed and an empty rouh-it is made to hold the old
name, and only then is rouh-it taken out of the code.

So every place that reads rouh-core on GitHub asks ``every`` for the addresses to try, in order,
and takes the first that answers: rouh-land first, since the organisation was renamed on 16
November 2026 (until then the old name was first, as the only one that existed), and rouh-it after
it, which GitHub forwards to rouh-land while no repository of the same name is made under it. A name that answers "not found" is passed over; any other failure is the answer, so a
GitHub that cannot be reached is never taken for a repository that is not there.

``ROUH_GITHUB_ORG`` names the organisation tried first, and the one written where a single name
is needed (a link); the other is tried after it. A machine can be moved over with that setting,
before the code says rouh-land everywhere.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

#: The two names, the new one first since the rename (16 November 2026); rouh-it, which GitHub
#: forwards, stays the fallback until stage 4.
NAMES = ("rouh-land", "rouh-it")
#: Either name, for a regular expression.
ANY = "(?:" + "|".join(re.escape(n) for n in NAMES) + ")"


def orgs() -> tuple[str, ...]:
    """Both names, the one to try first first: ROUH_GITHUB_ORG when it is one of them."""
    first = (os.environ.get("ROUH_GITHUB_ORG") or "").strip().lower()
    return (first, *(n for n in NAMES if n != first)) if first in NAMES else NAMES


def org() -> str:
    """The name written where only one can be: a link a person follows."""
    return orgs()[0]


def every(template: str) -> list[str]:
    """template with {org} as each name, in the order to try them; as it is without {org}."""
    return [template.replace("{org}", o) for o in orgs()] if "{org}" in template else [template]


def is_ours(remote: str, repo: str = "rouh-core") -> bool:
    """Whether a git remote names rouh-core (or repo) under either name."""
    return bool(re.search(rf"{ANY}/{re.escape(repo)}(\.git)?/?$", remote.strip()))


def read_json(template: str, *, headers: dict | None = None, timeout: float = 30,
              most: int = 4 * 1024 * 1024):
    """The JSON at the first address of every(template) that is found. "Not found" passes on to
    the next name; any other failure is raised as it is, and so is the last "not found"."""
    last: Exception | None = None
    for url in every(template):
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read(most))
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            last = e
    raise last or LookupError(template)
