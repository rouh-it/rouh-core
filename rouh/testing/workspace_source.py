"""Which real workspace a test world copies, when it copies one.

A world that is about the person's own tree (`rouh_with_tree` in
tests/e2e/conftest.py, `rouh/testing/browser.py`) copies a real workspace into
itself and never touches the original. Until 21 October 2026 that was the
`workspace/` of the checkout the suite ran out of. The workspace is a
repository of its own now, and Rouh's code holds none of it, so the copy comes
from a setting:

- `ROUH_TEST_WORKSPACE`, a workspace to copy, said for the suite;
- else the installation's own, `ROUH_WORKSPACE` (or `ROUH_ASSISTANT_REPO`);
- else `workspace/` in this checkout, which a checkout from before the split
  still holds;
- else the one program's checkout of the workspace (`ONE_WORKSPACE`, or
  `/srv/spaces/workspace`), which is what a run on the server has beside it.

Only a folder with `_migration-map.json` in it is a workspace. None at all is a
plain error that says what to set, never a world with nothing in it.
"""
from __future__ import annotations

import os

MAP = "_migration-map.json"
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def candidates() -> list[str]:
    said = [os.environ.get(name, "").strip()
            for name in ("ROUH_TEST_WORKSPACE", "ROUH_WORKSPACE", "ROUH_ASSISTANT_REPO",
                         "JARVIS_ASSISTANT_REPO")]
    return [p for p in (*said, os.path.join(REPO, "workspace"),
                        os.environ.get("ONE_WORKSPACE", "").strip(), "/srv/spaces/workspace") if p]


def source() -> str:
    for path in candidates():
        if os.path.isfile(os.path.join(path, MAP)):
            return path
    raise RuntimeError("there is no workspace to copy into this world: set ROUH_TEST_WORKSPACE "
                       "to a checkout of one (a folder with _migration-map.json in it)")
