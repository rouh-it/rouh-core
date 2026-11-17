"""Rouh's GitHub organisation, rouh-land (task 187).

The organisation that holds rouh-core and the images was called rouh-it until 16 November 2026,
when it was renamed rouh-land. For the rename every reader of GitHub took both names for a while
(stages 1 to 3); stage 4, on 17 November 2026, took the old name out of the code, so rouh-land is
the only one asked. GitHub still forwards rouh-it's addresses to rouh-land, because the owner holds
the old name with an empty organisation and no repository of ours is ever made in it: that is what
a Rouh on code from before the rename uses to reach its next update, which then knows rouh-land.

Every place that reads rouh-core on GitHub asks ``every`` for the address, with ``{org}`` filled in,
and ``read_json`` for a JSON answer.
"""
from __future__ import annotations

import json
import re
import urllib.request

#: The organisation's name.
NAME = "rouh-land"
#: The name, for a regular expression.
ANY = re.escape(NAME)


def org() -> str:
    """The name written where one is needed: a link a person follows, an address to fetch."""
    return NAME


def every(template: str) -> list[str]:
    """template with {org} filled in, as a list of the one address to try; as it is without {org}."""
    return [template.replace("{org}", NAME)]


def is_ours(remote: str, repo: str = "rouh-core") -> bool:
    """Whether a git remote names rouh-core (or repo) on GitHub."""
    return bool(re.search(rf"{ANY}/{re.escape(repo)}(\.git)?/?$", remote.strip()))


def read_json(template: str, *, headers: dict | None = None, timeout: float = 30,
              most: int = 4 * 1024 * 1024):
    """The JSON at template, {org} filled in. Any failure is raised as it is."""
    req = urllib.request.Request(every(template)[0], headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read(most))
