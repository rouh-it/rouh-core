"""Giving a person their password, and proving it reached them.

Written for the day Rouh moved to Django, 23 September 2026, because of what
happened the last time an account was made for the owner: the password was made,
it was never given to them, and they were locked out of their own assistant. So the
rule here is that **a password is only set once it has been delivered**:

1. a new password is made (`accounts.generate_password`: four words and a
   number, easy to read off a phone);
2. it is sent - on Telegram, by Rouh's own bot to the one chat it may send to
   (`rouh/telegram.py`), and by email, from Rouh's own Google account to the
   person's address (`rouh/google_api/gmail.py`), each tried, each allowed to fail;
3. only if at least one of them went is it set on the account, checked by
   signing in with it, and written down as delivered (`Handover`);
4. if neither went, nothing changes and the caller is told, which in the
   deploy means the switch does not happen (`manage.py predeploy`).

The password is never written anywhere but into those messages and, hashed,
into the account. It is not logged, not printed and not returned.

Whose account it is, the address it goes to and the domain an organisation
signs in with Google from are the caller's to say (`manage.py handover`,
`manage.py predeploy`): nothing here names anybody. It was written for one
cutover, the owner's, whose account, address and team's Google domain were
then written in this file; since 20 October 2026 (SETUP.md) a fresh
installation must start with nobody's, so with nothing named nothing happens.
"""
from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger("rouh.handover")

#: Kept, blank, for callers that still read them: nobody is named in the code.
#: The account, its address and the sign-in domain are passed in by the caller.
OWNER_USERNAME = ""
OWNER_EMAIL = ""
OWNER_SSO_DOMAIN = ""


class NotDelivered(RuntimeError):
    """No channel took the message, so the password was not changed."""


def _message(username: str, password: str, sign_in: str, email: str) -> str:
    google = (f"\nOr press Sign in with Google and choose {email}." if email else "")
    return (
        "Rouh is moving to its new Django backend now, and this is your sign-in for it.\n"
        f"\nUsername: {username}\nPassword: {password}\n"
        f"\nSign in at {sign_in} once it is back, in a minute or two.{google}\n"
        "\nThis password was made just now and is kept nowhere it can be read back. "
        "To change it: python manage.py account passwd " + username
    )


async def _by_telegram(owner_id: str, text: str) -> str:
    """To the one chat this machine's bot reaches, and only when that chat is this person's."""
    from .telegram import Telegram, phone_owner
    from .tenancy import Tenancy

    whose = await asyncio.to_thread(phone_owner, Tenancy())
    if whose is None or str(whose.user_id) != str(owner_id):
        raise NotDelivered("the Telegram chat on this machine is not this person's")
    await Telegram().send(text, who=owner_id)
    return "telegram"


async def _by_email(owner_id: str, to: str, text: str) -> str:
    """From Rouh's own Google account, if this install has one connected."""
    from .config import config
    from .encryption import SecretBox
    from .google_api import GoogleClients, Gmail
    from .google_audit import WriteLog
    from .google_oauth import GoogleAuth
    from .google_store import GoogleStore
    from .tenancy import Tenancy

    who = Tenancy().identity_of(owner_id)
    if who is None:
        raise NotDelivered("there is no account to send the email as")
    box = SecretBox(config.encryption_key, data_dir=config.data_dir)
    store = GoogleStore(None, box)
    if store.connection(who.user_id, who.org_id) is None:
        raise NotDelivered("no Google account is connected to send email from")
    auth = GoogleAuth(store, config)
    gmail = Gmail(GoogleClients(auth, config), who)
    sent = await gmail.send(to, "Your sign-in for Rouh", text, signed=False)
    # Into the record of every Google write, like any other mail Rouh sends
    # (`rouh/google_audit.py`). What it was, never what it said: the body
    # holds the password.
    held = store.connection(who.user_id, who.org_id)
    WriteLog(config.logs_path).wrote(
        "send_mail", to, f"the sign-in for {who.name}, sent before the move to Django"
        f" - message id {(sent or {}).get('id') or 'unknown'}",
        user_id=who.user_id, org_id=who.org_id, account=held.google_email if held else "")
    return f"email to {to}"


def hand_over(username: str, email: str = "", *,
              sign_in: str = "", channels: tuple[str, ...] = ("telegram", "email")) -> list[str]:
    """Make a password, deliver it, and only then set it. Returns where it went.

    Raises `NotDelivered` when nothing took it; the account is then exactly as
    it was.
    """
    from django.contrib.auth import authenticate
    from django.db import transaction

    from . import accounts
    from .config import config
    from .models import Handover

    if not (username or "").strip():
        raise NotDelivered("no account was named to hand over")
    user = accounts.get_user(username)
    if user is None:
        raise NotDelivered(f"there is no account called {username!r} to hand over")
    address = (user.email or email or "").strip()
    password = accounts.generate_password()
    text = _message(user.username, password, sign_in or config.public_url.rstrip("/") + "/login",
                    address)

    went: list[str] = []
    why: list[str] = []

    async def deliver():
        if "telegram" in channels:
            try:
                went.append(await _by_telegram(str(user.pk), text))
            except Exception as exc:
                why.append(f"telegram: {exc}")
        if "email" in channels and address:
            try:
                went.append(await _by_email(str(user.pk), address, text))
            except Exception as exc:
                why.append(f"email: {type(exc).__name__}: {exc}")

    asyncio.run(deliver())
    if not went:
        raise NotDelivered("the password went nowhere, so it was not set ("
                           + "; ".join(why) + ")")

    with transaction.atomic():
        user.set_password(password)
        if email and not user.email:
            user.email = email
        user.save(update_fields=["password", "email"])
        Handover.objects.create(user=user, sent_at=time.time(), channels=", ".join(went),
                                reason="; ".join(why))
    # Proved by using it, the way the person will.
    if authenticate(username=user.username, password=password) is None:
        raise NotDelivered("the password was delivered but does not sign in")
    accounts.end_all_sessions(user.username)
    log.info("the sign-in for %s was delivered by %s", user.username, ", ".join(went))
    for said in why:
        log.warning("a channel did not take the handover: %s", said)
    return went


def set_up_sign_in_with_google(org_id: str = "", domain: str = "") -> bool:
    """Say the default organisation's people sign in with Google from `domain`.

    Only if nobody has said anything about it yet, and never with accounts
    made automatically: see `Organisation.sso_auto_create`. True if it changed.
    With no domain given, nothing is changed.
    """
    from .models import DEFAULT_ORG_ID, Organisation

    domain = (domain or "").strip().lower()
    if not domain:
        return False

    changed = Organisation.objects.filter(id=org_id or DEFAULT_ORG_ID, sso_domain="") \
        .update(sso_domain=domain)
    return bool(changed)
