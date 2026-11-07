"""The person's own profile: who they say they are, and whether a card says it for them.

Petar, 13 October 2026 (fr_02048b1ef832), asking for Edit behind his own name:
"a page where users can edit their name, nickname, email, password etc,
information about themselves if needed and connection to their contact card. A
person should be able to connect their contact card or not. Some people will
want to be in sync which would be nice, some people will want to be anonymous
and use fake names, so connecting the contact card sync should be optional".

So a profile is:

- **The account's own fields**, Django's (`models.User`): the first and last
  name, which the welcome, comments and the rest already read, and the email,
  which signing in by address and `my_card.own_addresses` read. The username
  is what they sign in with and is not changed here.
- **What the account has no field for**, kept in `user_settings` under `NAME`
  with both ids, like the signatures: a nickname, their pronouns, and whether
  their name follows their contact card.
- **Who they are and their company are their contact's**, not the profile's.
  Petar, 4 November 2026, renaming the page About You: "inside should be no
  'about you' text area, that should be available in the contact card. same
  for organization". So both are fields of their own contact (`people.People.me`):
  who they are is its relationship field, and their company its organisation,
  the card's own when there is an iCloud card. The page shows and changes them
  under Contact card (`card_about`, `card_company`), the contact card on the
  canvas does too, and `rouh/owner.py` reads the company from there. What they
  had typed on the profile before (its `about`, and the organisation's name)
  was carried onto the contact once (`carry_to_card`), never over anything
  already on it, and the profile keeps its copy.

The name and the pronouns are what Rouh's prompts call the person
(`rouh/owner.py`, SETUP.md): "he" or "she", or nothing, which has the prompts
say the name again instead of a pronoun.
- **The contact card**, which is `my_card`'s choice and nothing else: no card
  is the default, and a profile with none is a whole profile, whatever name is
  on it. With one picked and following on (it is, unless they turn it off), the
  card's name is the account's name, read off the card each time the profile
  is, so a change on the phone arrives with the next sync. Only the name
  follows: the card's emails already count as theirs for mail, and the
  account's email is what they sign in with, so a card never changes it.

The password is changed with the one they have now, never without it, unless
the account has none (one made to sign in with Google), when it is set.
"""
from __future__ import annotations

import json
import re
import time

#: Where the profile's own fields are kept, in `user_settings`.
NAME = "profile"

#: How long each field may be.
LONGEST = {"first_name": 150, "last_name": 150, "nickname": 60, "card_about": 2000, "card_company": 120}

#: The pronouns a profile may hold, as the page offers them; "" is "use my name".
PRONOUNS = ("", "he", "she")


def _held(user_id: str, org_id: str) -> dict:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(user_id), org_id=org_id, name=NAME)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _keep(user_id: str, org_id: str, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(user_id), org_id=org_id, name=NAME,
                     value=json.dumps(held, ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def nickname(user_id: str, org_id: str) -> str:
    """What the person asked to be called, or ""."""
    if not user_id or not org_id:
        return ""
    return str(_held(user_id, org_id).get("nickname") or "").strip()


def follows_card(held: dict) -> bool:
    """Whether the name follows the picked card. On unless turned off."""
    return held.get("follow_card") is not False


def split_name(full: str) -> tuple[str, str]:
    """A card's one name as a first name and the rest."""
    words = str(full or "").split()
    return (words[0], " ".join(words[1:])) if words else ("", "")


def card_name(found: dict | None) -> tuple[str, str]:
    """The given and family name on a card: its vCard's N where it has one, else its name split."""
    if not found:
        return "", ""
    for line in str(found.get("vcard") or "").splitlines():
        m = re.match(r"(?i)^N(?:;[^:]*)?:(.*)$", line.strip())
        if m:
            parts = (m.group(1).split(";") + ["", ""])[:2]
            family, given = (p.replace("\\,", ",").strip() for p in parts)
            if given or family:
                return given, family
    return split_name(found.get("name") or "")


def _follow(user, held: dict, found: dict | None) -> bool:
    """The card's name onto the account, when it follows the card and they differ. True when it changed."""
    if found is None or not follows_card(held):
        return False
    first, last = card_name(found)
    if not (first or last) or (user.first_name, user.last_name) == (first, last):
        return False
    user.first_name, user.last_name = first[:LONGEST["first_name"]], last[:LONGEST["last_name"]]
    user.save(update_fields=["first_name", "last_name"])
    return True


def state(user_id: str, org_id: str) -> dict:
    """The whole profile, as the page draws it, with the card's name brought across first."""
    from . import my_card
    from .models import User

    user = User.objects.get(pk=user_id)
    held = _held(user_id, org_id)
    found = my_card.card(user_id, org_id)
    _follow(user, held, found)
    me = _my_contact(user_id, org_id, held)
    return {
        "pronouns": str(held.get("pronouns") or "") if held.get("pronouns") in PRONOUNS else "",
        "username": user.username,
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "nickname": str(held.get("nickname") or ""),
        "email": user.email or "",
        "card_about": me.relationship if me is not None else "",
        "card_company": me.organisation if me is not None else "",
        "card_contact": me is not None,
        "card_icloud": bool(me is not None and me.card is not None),
        "has_password": user.has_usable_password(),
        "follow_card": follows_card(held),
        "card": ({"name": found.get("name") or "", "first_name": card_name(found)[0],
                  "last_name": card_name(found)[1]} if found else None),
    }


def _clean(value, field: str) -> str:
    text = " ".join(str(value or "").split()) if field != "card_about" else str(value or "").strip()
    return text[:LONGEST[field]]


def _default_org_name(name: str) -> bool:
    from .models.accounts import DEFAULT_ORG_NAME

    return not name.strip() or name.strip() == DEFAULT_ORG_NAME


def carry_to_card(user_id: str, org_id: str, held: dict | None = None):
    """Once, what the person had typed on their profile about themselves, and their organisation's
    name, onto their own contact (`people.People.ensure_me`): the words about them onto who they
    are, after anything already there, and the organisation's name as their company only where the
    contact has none. Never over what is there, and the profile keeps its copy; marked done in the
    profile (`carried_to_card`). Their contact, or None when Synapse cannot be reached."""
    from . import people
    from .models import Organisation, User
    from .models.accounts import DEFAULT_ORG_ID

    held = _held(user_id, org_id) if held is None else held
    desk = people.People()
    try:
        me = desk.ensure_me(str(user_id), str(org_id))
    except Exception:  # noqa: BLE001 - the profile still opens; carried on the next read
        import logging

        logging.getLogger("rouh.profile").exception("the person's own contact could not be read")
        return None
    if me is None or held.get("carried_to_card"):
        return me
    about = str(held.get("about") or "").strip()
    rel = me.relationship
    if about and about not in rel:
        rel = (rel + "\n\n" + about).strip() if rel else about
    else:
        rel = None
    company = None
    user = User.objects.filter(pk=user_id).first()
    org = (Organisation.objects.filter(id=(user.org_id if user else None) or DEFAULT_ORG_ID)
           .values_list("name", flat=True).first() or "")
    if not me.organisation and not _default_org_name(org):
        company = org.strip()
    if rel is not None or company is not None:
        me = desk.write(str(user_id), str(org_id), me, relationship=rel[:people.MAX_RELATIONSHIP] if rel else None,
                        organisation=company)
    held["carried_to_card"] = time.time()
    _keep(user_id, org_id, held)
    return me


def _my_contact(user_id: str, org_id: str, held: dict):
    """The person's own contact, with what the profile once held carried onto it first."""
    return carry_to_card(user_id, org_id, held)


def save(user_id: str, org_id: str, body: dict) -> str:
    """Change what was sent of the profile. Says what changed; ValueError says why nothing did."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    from . import my_card
    from .models import User

    user = User.objects.get(pk=user_id)
    held = _held(user_id, org_id)
    found = my_card.card(user_id, org_id)
    if "follow_card" in body:
        held["follow_card"] = bool(body["follow_card"])
    following = found is not None and follows_card(held)
    fields: set[str] = set()
    changed: list[str] = []

    if "email" in body:
        email = str(body.get("email") or "").strip()[:254]
        if email:
            try:
                validate_email(email)
            except ValidationError:
                raise ValueError(f"{email} is not an email address.") from None
            if User.objects.filter(email__iexact=email, is_active=True).exclude(pk=user.pk).exists():
                raise ValueError(f"Another account already has {email}. Each account's email is its own, "
                                 "because you can sign in with it.")
        if email != (user.email or ""):
            user.email = email
            fields.add("email")
    # A name that follows the card is the card's: what was typed is not kept over it.
    if not following:
        for field in ("first_name", "last_name"):
            if field in body:
                value = _clean(body.get(field), field)
                if value != (getattr(user, field) or ""):
                    setattr(user, field, value)
                    fields.add(field)
    for field in ("nickname",):
        if field in body:
            value = _clean(body.get(field), field)
            if value != str(held.get(field) or ""):
                held[field] = value
                changed.append(field)
    if "pronouns" in body:
        value = str(body.get("pronouns") or "").strip().lower()
        if value not in PRONOUNS:
            raise ValueError("Pronouns are he, she, or none, which uses your name.")
        if value != str(held.get("pronouns") or ""):
            held["pronouns"] = value
            changed.append("pronouns")
    if "card_about" in body or "card_company" in body:
        # Who they are and their company are their own contact's (`people.People.me`).
        from . import people

        me = _my_contact(user_id, org_id, held)
        if me is None:
            raise ValueError("Your contact card could not be reached just now. Nothing was changed.")
        about = _clean(body.get("card_about"), "card_about") if "card_about" in body else None
        company = _clean(body.get("card_company"), "card_company") if "card_company" in body else None
        if about == me.relationship:
            about = None
        if company == me.organisation:
            company = None
        if about is not None or company is not None:
            people.People().write(str(user_id), str(org_id), me, relationship=about, organisation=company)
            changed.append("card")
    if fields:
        user.save(update_fields=sorted(fields))
    _keep(user_id, org_id, held)
    _follow(user, held, found)
    from . import owner

    owner.forget()
    if changed == ["card"] and not fields:
        return "Saved on your contact card."
    if changed or fields:
        return "Saved your profile."
    if "follow_card" in body:
        return ("Your name follows your contact card now." if follows_card(held)
                else "Your name is your own now. The card only says which emails are yours.")
    return "Nothing had changed."


def change_password(user, current: str, new: str, again: str) -> str:
    """Set a new password, given the one there is now. ValueError says why not."""
    from django.contrib.auth import password_validation
    from django.core.exceptions import ValidationError

    if user.has_usable_password() and not user.check_password(current or ""):
        raise ValueError("That is not your password now, so it was not changed.")
    if not new:
        raise ValueError("Type the new password.")
    if new != again:
        raise ValueError("The two new passwords are not the same.")
    try:
        password_validation.validate_password(new, user)
    except ValidationError as err:
        raise ValueError(" ".join(err.messages)) from None
    user.set_password(new)
    user.save(update_fields=["password"])
    return "Your password is changed. You stay signed in here; anywhere else you signed in asks for it again."
