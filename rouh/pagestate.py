"""A page's own settings, kept on the server for the person who chose them.

A workspace page is shown sandboxed (`pages.py`): it has no storage that lasts
past its closing and it cannot reach Rouh. So a page that wants to remember
what its reader chose - a part hidden, a tab picked - hands it to Rouh's page
around it, which saves it here, signed in, and hands it back the next time the
page opens, on any device (``stateRelay`` in cards.js).

Built 29 October 2026 for 158-05's hide and show buttons, and for any page:
Petar, "everything should be persistent storage ... for this page". He said
SQLite; it is Rouh's own PostgreSQL, so it is backed up with everything else.

**Whose.** One row a person a page (`models.PageState`): their org, their
account and the page's path. Nobody reads or writes another person's. Whoever
may open the page may keep settings on it, and the page is checked the way
Ask AI checks it (`askai.resolve`).

**What.** ``settings`` is one JSON object of the page's own keys. A write names
one key and its new value, and replaces that key's value; a value of null
removes the key. Or it hands the whole object, which replaces all of it.
Never more than `MOST` bytes for one page.
"""
from __future__ import annotations

import json
import time

#: The most one person's settings for one page may take, as JSON.
MOST = 64 * 1024
#: The longest key.
KEY_MOST = 200


class Refused(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _size(settings: dict) -> int:
    return len(json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode())


def read(org_id: str, user_id: str, rel: str) -> dict:
    """The person's settings on the page, ``{}`` when they have none."""
    from .models import PageState

    row = PageState.objects.filter(org_id=org_id, user_id=user_id, rel=rel).first()
    return {"settings": row.settings if row else {}, "updated_at": row.updated_at if row else None}


def write(org_id: str, user_id: str, rel: str, body: dict) -> dict:
    """One key set (``{"key", "value"}``) or the whole of it replaced (``{"settings"}``)."""
    from django.db import transaction

    from .models import PageState

    if "settings" in body:
        settings = body["settings"]
        if not isinstance(settings, dict):
            raise Refused("settings must be an object.")
        key = None
    else:
        key = body.get("key")
        if not isinstance(key, str) or not key or len(key) > KEY_MOST:
            raise Refused("Say which setting: a key of 1 to %d characters." % KEY_MOST)
        if "value" not in body:
            raise Refused("Say its value, or null to remove it.")
    now = time.time()
    with transaction.atomic():
        row = (PageState.objects.select_for_update()
               .filter(org_id=org_id, user_id=user_id, rel=rel).first())
        if key is not None:
            settings = dict(row.settings) if row else {}
            if body["value"] is None:
                settings.pop(key, None)
            else:
                settings[key] = body["value"]
        if _size(settings) > MOST:
            raise Refused("A page's settings may take %d KB at most." % (MOST // 1024), 413)
        if row is None:
            PageState.objects.create(org_id=org_id, user_id=user_id, rel=rel,
                                     settings=settings, updated_at=now)
        else:
            row.settings, row.updated_at = settings, now
            row.save(update_fields=["settings", "updated_at"])
    return {"settings": settings, "updated_at": now}


__all__ = ["MOST", "Refused", "read", "write"]
