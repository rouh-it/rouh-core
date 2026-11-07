"""Setting a new password when the old one is forgotten.

The sign-in page has a "Forgot password?" link (`rouh/web/reset.py`), and
behind it is this. It goes the way a careful site's does, in four steps:

1. **The person says who they are**, by username or by the email address on
   their account. Whatever they typed, the page answers with the same words in
   the same time, because an answer that differed would tell a stranger which
   names and addresses have an account here. The looking up and the sending
   happen after that answer has gone (`start`).
2. **A link is made** for each active account that name or address is, if it
   has a password to forget. The token in it is Django's own
   (`PasswordResetTokenGenerator`): a signature over the account's id, its
   password hash, when it last signed in and its email, stamped with when it
   was made. Nothing is stored. It is refused after an hour
   (`PASSWORD_RESET_TIMEOUT`), and it dies the moment the password changes or
   the account signs in, so it works once.
3. **The link is emailed from the person's own Google account to itself.**
   Rouh has no mail server - there is none on its machine - and a mail account
   of the server's own, used for everybody, would be exactly the global
   credential AGENTS.md forbids. What Rouh does have is the Google account
   each person connects in Settings, which may send mail. So the link goes out
   through that account and to that account's own address: the person's own
   credential, used for them and nobody else, to a mailbox Google has already
   vouched is theirs, and the copy in Sent is in that same mailbox. The
   address typed into an account by an administrator is never where a link
   goes, because nothing has proved it reaches the person.
   An account with no connected Google account that may send mail cannot be
   reached at all. The page says so, to everybody alike: if nothing arrives,
   an administrator can set a new password (`python manage.py account passwd`,
   or the Django admin).
   **A guest is the one exception** (since 24 September 2026). A guest's
   account was made from an invitation to one address, by somebody who opened
   the letter sent there (`rouh/web/guests.py`), so that address is proved in
   the same way a connected Google account's is, and a guest has no Google
   account to send through. Their link goes to that address from Rouh's own
   (`rouh/mailer.py`).
4. **The new password is set** through `accounts.set_password`, after the same
   validators as everywhere else, which signs that account out everywhere.
   The old password stops working, and so does the link.

What is written down about a reset is who and when, never the link: whoever
can read a log line with a live link in it can take the account. That includes
the request log uvicorn writes into ``rouh.log``, which other users on the
machine can read, so the token is blanked out of it on the way in
(`HideResetTokens`, installed in `rouh/project/asgi.py`).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict, deque

from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

log = logging.getLogger("rouh.reset")

#: Where the link in the email opens. `<uid>/<token>`, then the form.
LINK_PATH = "/login/reset/"

#: The mail scope a connection needs for Rouh to send the link through it.
SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"

#: Emails to one account, however many times anybody asks. Enough for a
#: person who asked, waited, and asked again; not enough to fill a mailbox.
PER_ACCOUNT = 3
PER_ACCOUNT_SECONDS = 60 * 60

#: At most this many accounts are sent a link for one thing typed. An address
#: can be on more than one account; it is not on dozens.
MOST_ACCOUNTS = 5

SUBJECT = "Set a new password for Rouh"

tokens = PasswordResetTokenGenerator()


class Recent:
    """How often something - an account, an address - has come up lately, in
    this process's memory. A restart forgets it, which costs at most one more
    round of the limit."""

    def __init__(self, allowed: int, window: float) -> None:
        self._allowed = allowed
        self._window = window
        self._seen: dict[str, deque[float]] = defaultdict(deque)

    def too_many(self, key: str) -> bool:
        now = time.monotonic()
        seen = self._seen[key]
        while seen and now - seen[0] > self._window:
            seen.popleft()
        if len(seen) >= self._allowed:
            return True
        seen.append(now)
        return False


_sent_lately = Recent(PER_ACCOUNT, PER_ACCOUNT_SECONDS)

#: The sends under way, held so none is collected half way through.
_under_way: set[asyncio.Task] = set()


# --- who it is --------------------------------------------------------------


def accounts_for(said: str) -> list:
    """The accounts a typed username or email address is, that can be reset.

    Active, and with a password: an account that only ever signs in with
    Google has no password to forget, and making it one here would add a way in
    that nobody asked for.
    """
    from django.db.models import Q

    from .models import User

    said = (said or "").strip()
    if not said or len(said) > 254:
        return []
    found = (User.objects.filter(Q(username__iexact=said) | Q(email__iexact=said),
                                 is_active=True)
             .order_by("id")[:MOST_ACCOUNTS])
    return [user for user in found if user.has_usable_password()]


def uid_of(user) -> str:
    return urlsafe_base64_encode(force_bytes(user.pk))


def user_of(uid: str):
    """The account a link's first half names, or None."""
    from .models import User

    try:
        pk = int(force_str(urlsafe_base64_decode(uid)))
    except (TypeError, ValueError, OverflowError):
        return None
    return User.objects.filter(pk=pk, is_active=True).first()


def token_good(user, token: str) -> bool:
    return bool(user is not None and token and tokens.check_token(user, token))


def link_for(user, public_url: str) -> str:
    """The address the email carries. Always this install's own public address,
    never the Host a request came in on: a link built from a forged Host header
    would send the person's token to whoever forged it."""
    return (public_url.rstrip("/") + LINK_PATH + uid_of(user) + "/"
            + tokens.make_token(user))


def letter(username: str, link: str) -> str:
    return (
        f"Somebody asked to set a new password for your Rouh account, {username}.\n"
        f"\nTo set one, open this link within the hour:\n{link}\n"
        "\nIt works once. If it was not you, you can ignore this email: your password "
        "stays as it is.\n"
        "\nRouh sent this through your own Google account, the one connected in "
        "Settings, because it has no mail server of its own.\n"
    )


#: The token half of a reset link in a path, and not the form's own address.
_TOKEN_IN_PATH = re.compile(
    "(" + re.escape(LINK_PATH) + r"[^/?#\s]+/)(?!set-password\b)[^/?#\s\"]+")


#: A sign-in letter's link (`rouh/signin.py`), held out of the log the same way.
SIGN_IN_PATH = "/login/link/"
_SIGN_IN_TOKEN = re.compile("(" + re.escape(SIGN_IN_PATH) + r")[^/?#\s\"]+")


def hide_token(text: str) -> str:
    """The same text with any reset link's or sign-in link's token blanked out."""
    return _SIGN_IN_TOKEN.sub(r"\1(token)", _TOKEN_IN_PATH.sub(r"\1(token)", text))


class HideResetTokens(logging.Filter):
    """Keep reset links' tokens out of the log.

    uvicorn logs every request as ``'%s - "%s %s HTTP/%s" %d'``, and Django a
    request that went wrong as ``"%s: %s"``, with the path among the arguments
    either way, so the arguments are rewritten before the line is formatted.
    A message with no arguments is checked whole.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and any(
                isinstance(one, str) and (LINK_PATH in one or SIGN_IN_PATH in one) for one in args):
            record.args = tuple(hide_token(one) if isinstance(one, str) else one
                                for one in args)
        elif isinstance(record.msg, str) and (LINK_PATH in record.msg or SIGN_IN_PATH in record.msg):
            record.msg = hide_token(record.msg)
        return True


# --- sending it -------------------------------------------------------------------


async def send_link(user) -> str:
    """Email one account its link. Returns where it went, or "" and says why in
    the log. Never raises: the page has already answered."""
    from asgiref.sync import sync_to_async

    from . import runtime
    from .config import config
    from .google_api import GoogleClients, Gmail

    if getattr(user, "is_guest", False):
        return await _send_to_guest(user)
    if runtime.google_store is None or runtime.google_auth is None:
        log.warning("a reset for %s cannot be sent: Google is off on this server",
                    user.username)
        return ""
    who = await sync_to_async(runtime.tenancy.identity_of)(str(user.pk))
    if who is None:
        return ""
    held = await sync_to_async(runtime.google_store.connection)(who.user_id, who.org_id)
    if held is None or not held.google_email:
        log.info("a reset for %s was not sent: no Google account is connected to send "
                 "it through", user.username)
        return ""
    if held.scopes and SEND_SCOPE not in held.scopes:
        log.info("a reset for %s was not sent: the connected Google account may not "
                 "send mail", user.username)
        return ""
    if _sent_lately.too_many(str(user.pk)):
        log.warning("a reset for %s was not sent: %d already this hour", user.username,
                    PER_ACCOUNT)
        return ""
    link = await sync_to_async(link_for)(user, config.public_url)
    try:
        gmail = Gmail(GoogleClients(runtime.google_auth, config), who)
        sent = await gmail.send(held.google_email, SUBJECT, letter(user.username, link),
                                signed=False)
    except Exception as exc:
        log.warning("a reset for %s could not be sent through Google: %s", user.username,
                    type(exc).__name__)
        return ""
    # Into the record of every Google write, like any other mail Rouh sends
    # (`rouh/google_audit.py`). What it was, never the link in it.
    runtime.google_audit.wrote(
        "send_mail", held.google_email,
        f"a link to set a new Rouh password, asked for on the sign-in page - message id "
        f"{(sent or {}).get('id') or 'unknown'}",
        user_id=who.user_id, org_id=who.org_id, account=held.google_email)
    log.info("a reset link for %s was emailed to their connected Google account",
             user.username)
    return held.google_email


async def _send_to_guest(user) -> str:
    """A guest's link, to the address their invitation proved, from Rouh's own."""
    from asgiref.sync import sync_to_async

    from . import mailer
    from .config import config

    if not user.email:
        return ""
    if _sent_lately.too_many(str(user.pk)):
        log.warning("a reset for a guest was not sent: %d already this hour", PER_ACCOUNT)
        return ""
    link = await sync_to_async(link_for)(user, config.public_url)
    text = (f"Somebody asked to set a new password for your Rouh account, {user.email}.\n"
            f"\nTo set one, open this link within the hour:\n{link}\n"
            "\nIt works once. If it was not you, you can ignore this email: your password "
            "stays as it is.\n")
    try:
        await mailer.Mailer(config).send(mailer.Letter(to=user.email, subject=SUBJECT,
                                                       text=text))
    except (mailer.NotSetUp, mailer.NotSent) as exc:
        log.warning("a reset for a guest could not be sent: %s", exc)
        return ""
    log.info("a reset link for a guest was emailed to the address they were invited at")
    return user.email


async def _send_all(said: str) -> None:
    from asgiref.sync import sync_to_async

    try:
        found = await sync_to_async(accounts_for)(said)
    except Exception:
        log.exception("a reset could not look up who it was for")
        return
    if not found:
        log.info("a reset was asked for something that is not an account")
    for user in found:
        await send_link(user)


def start(said: str) -> None:
    """Look up and send, after the page has answered. See step 1 above."""
    task = asyncio.get_running_loop().create_task(_send_all(said))
    _under_way.add(task)
    task.add_done_callback(_under_way.discard)
