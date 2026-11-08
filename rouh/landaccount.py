"""The person's rouh.land account, as far as this Rouh knows it: on Your Rouh, whether this Rouh is
connected to it and what is wrong between them (`birthpage.js`), and on You, Your account, the
account itself (`landaccountpage.js`). Rouh Land Account, Your profile from 4 to 7 November 2026,
when step 141-17 gave each journey one home.

Petar, 4 November 2026: "in the settings it needs to be clear what is relevant to rouh.land. so
maybe we should have one separate section Rouh Land Account. in it: - Your Profile with email for
rouh land and everything else". And, the same day, after seeing it: "in the page for my profile I
see ROUH information that should not be the case", and of its buttons, "each one of them needs to
be really well thought out ... we shouldn't have open account at rouh land if I already have an
account". So Your profile is about the person and their rouh.land account only, and says two
things and no more:

- **whether you have a rouh.land account this Rouh knows of**, and
- **whether this Rouh is connected to it**,

and the one email that signs the person in (`signin.primary`), labelled "Signs you in to this Rouh
and rouh.land" when connected, since a connected Rouh follows its account's email, or "Signs you in
to this Rouh" when not (4 November 2026: one email runs both). The account's role is shown as
rouh.land's signed status answer says it, with its email (`birth.check`, kept as the card's
`account`, since 4 November 2026).

Nothing about the Rouh itself is here: its name, its id on rouh.land, the registry's address, since
when, and when its keys were last asked after are Rouh profile's (`birth.py`, `birthpage.js`), and
even there only as "registered on rouh.land" or not.

**Checking with rouh.land is not a press.** The page asks for a check as it opens (`check_now`), at
most once every `RECHECK` seconds, and the gene log's beat asks every six hours by itself
(`birth.tick`). The page says something only when something is wrong (`problem`): rouh.land could
not be reached, or it refused this Rouh's key, each as one plain sentence and the one thing to do.

Signing in and out happens on rouh.land, in the person's own browser: this Rouh holds no rouh.land
session. The way to connect is rouh.land's door, which sends the person back with a code to
`addressing.ROUH_LAND_RETURN`, from where Rouh profile takes it (`birth.be_born`, `birth.connect`).
"""
from __future__ import annotations

from . import birth

#: Keys rouh.land's card might one day carry for the account's email and role, read in this
#: order. None is in today's card, and the page then shows neither.
#: An `account` object in the card, with `email` and `role`, is read the same way.
EMAIL_KEYS = ("owner_email", "account_email", "email")
ROLE_KEYS = ("owner_role", "account_role", "role")

#: How long after a check the page's own check is not asked again: opening the page twice in a
#: minute is one question to rouh.land, not two. A retry pressed beside an error always asks.
RECHECK = 5 * 60
#: The same while a Connected Rouh's account waits on the link emailed to its owner (step 176-16):
#: they may have pressed it a moment ago, so the card asks again sooner.
RECHECK_WAITING = 10


def _recheck(row) -> int:
    return RECHECK_WAITING if row is not None and row.registry_id and not birth.in_account(row) else RECHECK


def _first(payload: dict, keys: tuple[str, ...], inside: str) -> str:
    account = payload.get("account")
    found = [payload.get(k) for k in keys] + [account.get(inside) if isinstance(account, dict) else None]
    for value in found:
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]
    return ""


def _door(row) -> str:
    """rouh.land's birth service: its door is where you sign up or sign in, and its `account/`
    is your account there."""
    url = (row.registry_url if row is not None and row.registry_url else "") or birth.defaults()[0]
    return url if url.endswith("/") else url + "/"


def problem(row) -> dict | None:
    """What is wrong between this Rouh and rouh.land, as {kind, said, do}, or None.

    `kind` is "key" (rouh.land no longer recognises this Rouh), "unreachable" (the last ask did not
    reach it) or "refused" (it answered, and not with what was asked). `said` is the sentence, never
    a key, and `do` the one thing to do about it: "retry", or "" when there is nothing to press.
    """
    if row is None or not row.registry_id:
        return None
    if row.key_dead_at:
        return {"kind": "key", "do": "", "said": birth.standing(row)["said"]}
    error = str(row.error or "")
    if not error:
        return None
    if "could not be reached" in error:
        return {"kind": "unreachable", "do": "retry",
                "said": "rouh.land could not be reached just now. Everything here keeps working; "
                        "it tries again by itself."}
    return {"kind": "refused", "do": "retry", "said": "rouh.land did not accept this Rouh's last check: " + error}


def page(who) -> dict:
    """Everything Your profile draws, for this person: only this organisation's birth row
    (AGENTS.md, "Whose data is it")."""
    org = str(who.org_id)
    row = birth.current(org)
    door = _door(row)
    from . import signin
    from .models import User

    # The one email that signs this person in (4 November 2026: "if you are connected, one email
    # runs both"), shown once, with what it signs them in to.
    mine = signin.primary(User.objects.filter(pk=who.user_id).first())
    out = {"admin": bool(getattr(who, "is_admin", False)), "born": row is not None,
           "connected": False, "has_account": False, "email": "", "role": "",
           "sign_in_email": mine, "sign_in_label": "Signs you in to this Rouh",
           "door": door, "account_url": door + "account/", "problem": None, "check_due": False,
           "rouh_name": "", "owner": birth._owner_of(org)["name"],
           # A Connected Rouh in no account yet: the email rouh.land was asked to confirm, and
           # whether it may be asked again from here (step 176-16).
           "waiting_email": "", "can_confirm": False}
    if row is None:
        return out
    out["rouh_name"] = row.name
    payload = row.card.get("payload") if isinstance(row.card, dict) else None
    payload = payload if isinstance(payload, dict) else {}
    connected = bool(row.registry_id)
    in_account = connected and birth.in_account(row)
    out.update({
        # Connected to your account: registered on rouh.land, in an account there. A registration with
        # no account is not connected to anybody's.
        "connected": in_account,
        "has_account": in_account,
        "email": _first(payload, EMAIL_KEYS, "email") if in_account else "",
        "role": _first(payload, ROLE_KEYS, "role") if in_account else "",
        "problem": problem(row),
        "check_due": connected and out["admin"] and not (row.checked_at and birth._now() - row.checked_at < _recheck(row)),
    })
    if in_account:
        out["sign_in_label"] = "Signs you in to this Rouh and rouh.land"
    elif connected and not row.key_dead_at:
        out["waiting_email"] = birth.account_asked(row)
        out["can_confirm"] = out["admin"]
    return out


def ask_again(who) -> dict:
    """Send the confirm-your-email link again, to the email that signs this person in: Connected is
    the rouh.land account (step 176-16). An administrator's. Answers what `page` does, with `said`."""
    if not getattr(who, "is_admin", False):
        raise birth.Refused("Only an administrator of this Rouh asks rouh.land.")
    from . import signin
    from .models import User

    email = signin.primary(User.objects.filter(pk=who.user_id).first())
    got = birth.ask_account(str(who.org_id), email)
    return {**page(who), "said": got.get("said", "")}


def check_now(who, *, retry: bool = False) -> dict:
    """The page's own ask of rouh.land, as it opens or from a retry beside an error. An
    administrator's, like every ask of rouh.land; a page opened twice in `RECHECK` asks once."""
    if not getattr(who, "is_admin", False):
        raise birth.Refused("Only an administrator of this Rouh asks rouh.land.")
    row = birth.current(str(who.org_id))
    if row is not None and row.registry_id and (retry or not (row.checked_at and birth._now() - row.checked_at < _recheck(row))):
        birth.check(str(who.org_id), force=True)
        try:
            # A new key waiting there is asked after too; what it says is Rouh profile's to show.
            birth.recover_check(str(who.org_id))
        except birth.Refused:
            pass
    return page(who)


def attention(who) -> list[str]:
    """What the status board says for Your profile: not connected to a rouh.land account, or
    something wrong between this Rouh and rouh.land."""
    row = birth.current(str(who.org_id))
    if row is None:
        return []  # Not born yet, said once, by Rouh profile.
    if not row.registry_id or not birth.in_account(row):
        return ["Disconnected from rouh.land" if birth.disconnected(row) else "Not connected to a rouh.land account"]
    said = problem(row)
    if said is None:
        return []
    return ["rouh.land stopped this Rouh" if said["kind"] == "key"
            else "Can't reach rouh.land" if said["kind"] == "unreachable"
            else "rouh.land did not accept the last check"]
