"""What one person has set for themselves, kept where it belongs to them.

`config.py` is the **machine's** settings: the model, the keys, the
directories, read out of the environment when the process starts and the same
for everybody on this install. This file is the other kind, and the two are
never mixed up: a **person's** own settings, moved by them on a screen, theirs
alone, and kept in Rouh's database beside everything else that is theirs:
the `user_settings` table, which is `rouh.models.UserSetting` since the move
into PostgreSQL on 23 September 2026.

The orb's sliders are the first of them, and they are the reason this file
exists. Until 22 September 2026 they were the browser's: one copy in each
browser's local storage, keyed by nothing and known to nobody. What that meant
in practice is that a look the person tuned on the desktop was not on the phone;
and it was gone from the desktop too the moment that browser dropped its site
data, which a phone does by itself. Two sliders moved and a sign-in later, the
panel was back at the approved design and nothing anywhere remembered
otherwise. They are the person's settings, so they are a row of the person's.

The browser still keeps a copy, and that copy is a mirror rather than the
truth: it draws the first frame, before there is a socket to ask on. The row
here is what a page takes as soon as it has one (`orbFromServer` in
`app.js`).

Both ids are in every query, as `tenancy.py` requires. `user_id` because these
are one person's; `org_id` beside it although the user id alone is unique,
because a caller holding the wrong organisation is exactly the bug worth
turning into "nothing saved" rather than into one customer being handed another
customer's screen.

**What is stored is not trusted to mean anything.** A setting goes in as JSON
and the only thing asked here is the shape: a small flat object of finite
numbers and nothing else, so the table can never hold junk and no reply can be
enormous. What each number *means*, and the range it is allowed to be in, is
the page's business - the design lives in `app.js` beside the sliders that
draw it, and `orbSane` there clamps every value on the way back in. One copy of
the design, in the one place that has to know it.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time

#: The one setting there is so far. A name is part of the key rather than a
#: table of its own, so the next thing the person tunes is one string and no
#: migration.
ORB = "orb"

#: The most numbers one setting may carry, and what a key inside it may be
#: called. The orb has seventeen; the ceiling is here so that nothing a browser
#: sends can grow the row without limit.
MAX_KEYS = 64
KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,39}$")

#: Setting names themselves, which are ours rather than the browser's, but are
#: read off a socket and so are checked the same way.
NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def shaped(value) -> dict | None:
    """One setting as it may be stored, or None when it is not one.

    A flat object of finite numbers, at most `MAX_KEYS` of them, each under a
    plain name. `True` is not a number here however Python feels about it: a
    boolean that reached a slider would be drawn as 1 and saved back as 1, and
    a setting that changes type on a round trip is worse than one that is
    refused. An empty object is a perfectly good answer and means "saved, and
    every one of them is at the design".
    """
    if not isinstance(value, dict) or len(value) > MAX_KEYS:
        return None
    out: dict[str, float] = {}
    for key, number in value.items():
        if not isinstance(key, str) or not KEY.match(key):
            return None
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            return None
        if not math.isfinite(number):
            return None
        out[key] = float(number)
    return out


class Settings:
    """One person's own settings, by name, with both ids in every query.

    The rows are `rouh.models.UserSetting`, keyed by person and name. Until
    23 September 2026 this class opened the SQLite file itself and made its
    table; the schema is Django's migrations' now, and the path the
    constructor is still handed is accepted and not used, so a caller written
    before the move needs no change.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._lock = threading.Lock()

    def close(self) -> None:
        """Nothing to close: the connection is Django's, one per thread."""

    def get(self, who, name: str) -> dict | None:
        """What this person saved under that name, or None if they never have.

        None is an answer and not a missing one: it is what tells a page that
        nobody has saved anything here yet, which is when the copy the browser
        already has is worth sending up rather than throwing away. An empty
        object means the opposite - they saved, and put everything back.
        """
        from .models import UserSetting

        if who is None or not NAME.match(name or ""):
            return None
        with self._lock:
            value = (UserSetting.objects
                     .filter(user_id=who.user_id, org_id=who.org_id, name=name)
                     .values_list("value", flat=True).first())
        if value is None:
            return None
        try:
            return shaped(json.loads(value))
        except (TypeError, ValueError):
            # Written by a build that stored something else, or edited by hand.
            # The page has its design to fall back on, so this is "nothing
            # saved" rather than an error anybody has to see.
            return None

    def put(self, who, name: str, value) -> dict | None:
        """Save one setting. The shape it was stored as, or None if refused.

        One statement whichever way it goes: a row that is there is written
        over, organisation and all, and a row that is not is made. Two tabs
        saving at once cannot both make it.
        """
        from .models import UserSetting

        if who is None or not NAME.match(name or ""):
            return None
        clean = shaped(value)
        if clean is None:
            return None
        with self._lock:
            UserSetting.objects.bulk_create(
                [UserSetting(user_id=who.user_id, org_id=who.org_id, name=name,
                             value=json.dumps(clean, sort_keys=True),
                             updated_at=time.time())],
                update_conflicts=True, unique_fields=["user_id", "name"],
                update_fields=["org_id", "value", "updated_at"])
        return clean

    def forget(self, who, name: str) -> None:
        """Take the row away, so the next read says "never saved"."""
        from .models import UserSetting

        if who is None or not NAME.match(name or ""):
            return
        with self._lock:
            UserSetting.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                       name=name).delete()
