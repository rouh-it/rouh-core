"""The signatures under the email Rouh sends: one person's own, set in Settings.

Petar, 27 September 2026: the signatures are a setting of each person's, on
Settings, "because other people will use Rouh and want their own". Two boxes:
one for a new email, and one for a reply or a forward. An empty box is no
signature at all. They replaced reading the mailbox's Gmail signature, which
was one signature for everything and belonged to the mailbox rather than to
the person Rouh writes for.

A **new email** is `send_mail` or `draft_mail` with no `reply_to_message_id`;
a **reply or forward** is everything else: a reply from a tool or from the
inbox card, a forward, and a draft that answers a message. `google_api.Gmail`
reads the right one as it composes (`for_mail`) and `google_api.with_signature`
puts it under what was written and over anything quoted or forwarded.

Kept in `user_settings` under `NAME`, like the orb and the time zone, with both
ids in every query as `tenancy.py` requires. What is stored is two strings; a
person who never saved has no row, and has no signature.
"""
from __future__ import annotations

import json
import time

#: Where they are kept, in `user_settings`.
NAME = "mail_signature"

#: The two boxes, by the key they are kept and sent under.
NEW, ANSWER = "new", "reply"

#: The most one signature may be. A signature is a few lines; this is so that
#: nothing a browser sends can make every email enormous.
MOST = 2000


def clean(value) -> str:
    """A signature as it is kept: its lines, without trailing spaces or blank ends."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")[:MOST]


def get(who) -> dict:
    """This person's two signatures, "" for a box they left empty or never filled."""
    from .models import UserSetting

    out = {NEW: "", ANSWER: ""}
    if who is None:
        return out
    value = (UserSetting.objects
             .filter(user_id=str(who.user_id), org_id=who.org_id or "", name=NAME)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    if isinstance(held, dict):
        for key in out:
            out[key] = clean(held.get(key))
    return out


def put(who, new, reply) -> dict:
    """Save both signatures for this person. What was kept."""
    from .models import UserSetting

    kept = {NEW: clean(new), ANSWER: clean(reply)}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=NAME,
                     value=json.dumps(kept, ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])
    return kept


def for_mail(who, *, answering: bool) -> str:
    """The signature an email goes out with: the reply one when it answers or forwards."""
    return get(who)[ANSWER if answering else NEW]
