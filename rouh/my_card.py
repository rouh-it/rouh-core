"""Which addresses are the person's own: their account's, and the card they picked.

Petar, 1 October 2026: "I want my own email addresses for mail handling to
come from one contact card that I pick explicitly in Settings, instead of being
worked out implicitly." Until then they were the account's address and
whatever a profile marked `is_me` had gathered (`people.People.me`), which was
tied to a card by nothing he had ever chosen.

So now there is exactly one answer, and this is it:

- **The account's own address**, always.
- **Every email on the card picked in Settings, My contact card**: an iCloud
  card (`models.AppleContact`), found by its vCard UID, which survives a sync
  rewriting the row. Kept in `user_settings` under `NAME`, like the signatures,
  with both ids in every query. The emails are read off the card every time
  they are asked for, so a change made on that Settings card counts on the
  next email, and one made on the phone counts on the next sync.
- **Never Rouh's own mailbox**, `inbox.own()`, even when it is on the card:
  mail from it is Rouh writing, not him. Settings refuses to put it there.

No card picked, or the picked card gone from iCloud, is the account's address
alone. Nothing guesses a card.

`own_addresses` is what `mail_alerts.MailAlerts.handle` sorts each new email
by (his own instruction when Gmail confirmed it, a refused case when it did
not), and `is_own` / `is_my_card` are what keep his own addresses and his own
card out of trusted contacts and out of a stranger's case (`trusted.py`,
`mail_cases.py`). Nothing else decides whether an address is his.
"""
from __future__ import annotations

import json
import time

#: Where the choice is kept, in `user_settings`.
NAME = "my_contact_card"


def _addr(value) -> str:
    return str(value or "").strip().lower()


def never_mine(address) -> bool:
    """Rouh's own mailbox, which is never the person's, whatever a card says."""
    from .inbox import own

    return _addr(address) in own()


def refused_because(address) -> str:
    """Why an address may not be one of the person's own, or "" when it may."""
    if never_mine(address):
        return (f"{_addr(address)} is Rouh's own address, so it never counts as yours. "
                "It was not put on your card.")
    return ""


# --- the choice ---------------------------------------------------------------------------


def chosen_uid(user_id: str, org_id: str) -> str:
    """The vCard UID of the card picked, or "" when none was."""
    from .models import UserSetting

    if not user_id or not org_id:
        return ""
    value = (UserSetting.objects.filter(user_id=str(user_id), org_id=org_id, name=NAME)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return str(held.get("uid") or "") if isinstance(held, dict) else ""


def card(user_id: str, org_id: str) -> dict | None:
    """The card picked, as iCloud last held it, or None: none picked, or it is gone."""
    from .synapse import contacts

    uid = chosen_uid(user_id, org_id)
    if not uid or not user_id or not org_id:
        return None
    return contacts.by_uid(str(user_id), org_id, uid)


def choose(user_id: str, org_id: str, contact_id) -> dict:
    """Pick the card with this id (a person of Synapse Master) as the person's own. ValueError says why not."""
    from .models import UserSetting
    from .synapse import contacts

    found = contacts.one(str(user_id), org_id, contact_id) if user_id and org_id and contact_id else None
    if found is None or found.get("kind") != "individual":
        raise ValueError("That contact is not in your iCloud contacts. Search again and "
                         "pick one from the list.")
    if not found.get("uid"):
        raise ValueError("That contact has no identity iCloud keeps, so it cannot be "
                         "followed. Pick another.")
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(user_id), org_id=org_id, name=NAME,
                     value=json.dumps({"uid": found["uid"], "id": found["id"]}),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])
    return found


def forget(user_id: str, org_id: str) -> bool:
    """No card picked any more: only the account's address is the person's."""
    from .models import UserSetting

    gone, _ = UserSetting.objects.filter(user_id=str(user_id), org_id=org_id,
                                         name=NAME).delete()
    return bool(gone)


# --- the answer ---------------------------------------------------------------------------


def account_address(user_id: str) -> str:
    from .models import User

    row = User.objects.filter(pk=user_id).values("email").first() if user_id else None
    return _addr(row["email"]) if row else ""


def card_addresses(found: dict | None) -> list[str]:
    """The emails on a card, lower case, each once, in the card's order."""
    out: list[str] = []
    for one in (found or {}).get("emails") or ():
        address = _addr(one.get("address") if isinstance(one, dict) else one)
        if address and "@" in address and address not in out:
            out.append(address)
    return out


def own_addresses(user_id: str, org_id: str) -> list[str]:
    """Every address that is the person's own: the account's, then the picked card's.

    Read fresh each time, so it is never staler than Rouh's copy of the card.
    """
    out: list[str] = []
    for address in [account_address(user_id), *card_addresses(card(user_id, org_id))]:
        if address and address not in out and not never_mine(address):
            out.append(address)
    return out


def is_own(user_id: str, org_id: str, address) -> bool:
    address = _addr(address)
    return bool(address) and address in own_addresses(user_id, org_id)


def is_my_card(user_id: str, org_id: str, person) -> bool:
    """Whether a contact (`people.Person`) is the person themselves.

    Their picked card, or the profile Rouh kept for them before there was a
    choice (`is_me`), which is still them even though its addresses no longer
    decide anything.
    """
    if person is None:
        return False
    if getattr(person, "is_me", False):
        return True
    uid = str((getattr(person, "card", None) or {}).get("uid") or "")
    return bool(uid) and uid == chosen_uid(user_id, org_id)
