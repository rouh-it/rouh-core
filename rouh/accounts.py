"""Who may use Rouh, and how a refused sign-in is slowed down.

Until 23 September 2026 this file was the whole of the accounts: three SQLite
tables, a scrypt hash of its own and a signed cookie of its own. Django does
those three things now, and does them the standard way:

- **Accounts** are Django's (`rouh.models.User`), with the organisation and
  whether the person manages it added on top (`rouh/models/accounts.py`).
- **Passwords** are hashed by Django's scrypt hasher, with the same cost the
  old one used. The hashes the old table held are read by
  :class:`LegacyScryptHasher`, so a password that worked the day before the
  move works the day after, and each is rewritten into Django's own format the
  first time it is used.
- **Sign-ins** are Django sessions, in PostgreSQL, in the ``rouh_session``
  cookie. Signing out deletes the row, so the cookie is dead even if it is
  kept, which is what the old table did too.

What stays here is what Django does not do, and what Rouh has always done:

- **Refused attempts** (:class:`SignInFailure`), by address and by the name
  that was tried. They decide how long the next attempt has to wait and when
  an account or an address is shut out for a while.
- **The admin command**, now `python manage.py account`, which makes an
  account, changes a password, lists them and signs one out everywhere.
  ``python -m rouh.accounts`` still works and runs the same thing.

Passwords are never logged, never returned and never stored. A generated one
is printed exactly once, by the admin command, or sent to its owner exactly
once by the handover (`rouh/handover.py`), and then only exists in whoever
read it.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import logging
import os
import secrets
import sys
import time

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.hashers import BasePasswordHasher, mask_hash

log = logging.getLogger("rouh.accounts")

# --- how a refused sign-in is slowed down ----------------------------------

#: How far back failures are counted.
FAILURE_WINDOW = 15 * 60
#: How many failures, from one address or against one account, shut it out.
LOCKOUT_AFTER = 8
#: For how long.
LOCKOUT_SECONDS = 15 * 60
#: The wait before the answer to a wrong password. Doubles per recent failure.
DELAY_BASE = 0.4
DELAY_MAX = 6.0

#: How much of a sign-in's life has to be used up before a request pushes its
#: end back. Renewing on every request would write a row per image on the page;
#: a day's granularity costs one write a day per browser and nobody can tell.
RENEW_AFTER = 24 * 60 * 60


# --- the old hashes ------------------------------------------------------------

def _check_legacy(password: str, stored: str) -> bool:
    """Is this the password behind a hash the old accounts table made?

    ``scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>``. Anything it cannot parse is
    False rather than an exception: a row corrupted somehow must refuse a
    sign-in, not take the process down.
    """
    try:
        kind, n, r, p, salt_b64, want_b64 = stored.split("$")
        if kind != "scrypt":
            return False
        want = base64.b64decode(want_b64)
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=base64.b64decode(salt_b64),
            n=int(n), r=int(r), p=int(p), dklen=len(want), maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(derived, want)


class LegacyScryptHasher(BasePasswordHasher):
    """The hashes Rouh's own accounts table held until 23 September 2026.

    Stored as ``rouh_scrypt$`` in front of exactly the string the old table
    had. Django only ever reads these: the first hasher in PASSWORD_HASHERS is
    what makes a new one, and a successful sign-in with one of these rewrites
    it into that format, so this class matters less every day and can go once
    no row starts with its name.
    """

    algorithm = "rouh_scrypt"

    def encode(self, password, salt):
        raise ValueError("Rouh does not make new hashes of the old kind.")

    def decode(self, encoded):
        algorithm, _, old = encoded.partition("$")
        parts = old.split("$")
        return {"algorithm": algorithm, "hash": parts[-1] if parts else "",
                "salt": parts[-2] if len(parts) > 1 else ""}

    def verify(self, password, encoded):
        algorithm, _, old = encoded.partition("$")
        if algorithm != self.algorithm:
            return False
        return _check_legacy(password or "", old)

    def safe_summary(self, encoded):
        decoded = self.decode(encoded)
        return {"algorithm": decoded["algorithm"], "salt": mask_hash(decoded["salt"]),
                "hash": mask_hash(decoded["hash"])}

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        pass


def legacy_to_django(stored: str) -> str:
    """The old table's hash, in the form Django stores it."""
    return f"{LegacyScryptHasher.algorithm}${stored}" if stored else "!"


def _by_email(User, said: str):
    """The one active account with this email address, when what was typed is
    one and exactly one account has it. A guest's name to sign in with is
    their address; anybody else may type theirs instead of their name."""
    if "@" not in said:
        return None
    found = list(User.objects.filter(email__iexact=said, is_active=True)[:2])
    return found[0] if len(found) == 1 else None


class CaseInsensitiveBackend(ModelBackend):
    """Django's own sign-in, matching the username regardless of case.

    The old table said COLLATE NOCASE, so "Alex" and "alex" were always the
    same account, and a phone that capitalises the first letter of a field
    must not turn a right password into a wrong one.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        said = (username or "").strip()
        try:
            user = User.objects.get(username__iexact=said)
        except User.DoesNotExist:
            user = _by_email(User, said)
        if user is None:
            # Run the hasher once anyway, so "no such account" and "wrong
            # password" take the same time and the page cannot be used to find
            # out which names exist.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    async def aauthenticate(self, request, username=None, password=None, **kwargs):
        """The same rule, for the sign-in page, which signs in asynchronously.

        Django's own `ModelBackend.aauthenticate` does not call `authenticate`
        above: it looks the name up exactly as typed, so until 24 September
        2026 "Alex" was refused where "alex" was let in, and an email
        address was never looked up at all. Found signing a guest in as
        "Ana@Example.com".
        """
        from asgiref.sync import sync_to_async

        return await sync_to_async(self.authenticate)(request, username=username,
                                                      password=password, **kwargs)


# --- generated passwords ---------------------------------------------------------

def generate_password(words: int = 4) -> str:
    """A password a person can read down a telephone and still not guess.

    Four words out of this list and two digits is about 62 bits, which is more
    than anything that has to survive a rate-limited sign-in needs, and it can
    be read out loud without spelling anything.
    """
    return "-".join(secrets.choice(WORDS) for _ in range(words)) + "-" + str(
        secrets.randbelow(90) + 10)


#: Short, common, unambiguous when spoken. Deliberately no words that sound
#: like another word on the list.
WORDS = (
    "amber anchor apple arrow autumn basket beacon birch bridge bronze candle "
    "canyon cedar cherry cobalt copper coral cotton crimson crystal delta desert "
    "diamond dolphin ember falcon feather forest garden ginger glacier granite "
    "harbour harvest hazel indigo island ivory jasmine jungle juniper lantern "
    "laurel lemon lighthouse lily lotus maple marble meadow meteor mint mountain "
    "nectar nutmeg oak ocean olive opal orchid otter oyster paprika pebble pepper "
    "pilot pine planet pocket poppy prairie quartz quill rain raven ribbon river "
    "rocket rosemary saffron sage sapphire shadow silver sparrow spruce stone "
    "summit sunset thistle thunder timber topaz tulip valley velvet violet walnut "
    "willow window winter zephyr"
).split()


# --- accounts ------------------------------------------------------------------------

def get_user(username: str):
    """The account called that, whatever the case, or None."""
    User = get_user_model()
    return User.objects.filter(username__iexact=(username or "").strip()).first()


def count() -> int:
    """How many accounts there are. Never who they are."""
    return get_user_model().objects.count()


def add_user(username: str, password: str | None, email: str = "", *,
             org_id: str = "", is_org_admin: bool | None = None):
    """A new account, in an organisation. Refuses a name already taken.

    ``password`` None makes an account that can only sign in with Google,
    which is what signing in with Google makes (`rouh/web/sso.py`). An
    organisation's first member manages it, as it always was
    (`rouh/tenancy.py`).
    """
    from . import tenancy

    username = (username or "").strip()
    if not username:
        raise ValueError("a username cannot be empty")
    if get_user(username) is not None:
        raise ValueError(f"there is already an account called {username!r}")
    User = get_user_model()
    user = User(username=username, email=(email or "").strip())
    if password:
        user.set_password(password)
    else:
        user.set_unusable_password()
    user.org_id = org_id or tenancy.DEFAULT_ORG_ID
    tenancy.ensure_organisation(user.org_id)
    user.save()
    if is_org_admin is None:
        tenancy.Tenancy().adopt(str(user.pk), user.org_id)
    else:
        user.is_org_admin = bool(is_org_admin)
        user.save(update_fields=["is_org_admin"])
    user.refresh_from_db()
    return user


def set_password(username: str, password: str) -> bool:
    """Change a password, and sign that account out everywhere.

    A password is changed either because it leaked or because somebody else
    may have it, and both mean the open sign-ins have to go.
    """
    user = get_user(username)
    if user is None:
        return False
    user.set_password(password)
    user.save(update_fields=["password"])
    end_all_sessions(user.username)
    forget_failures(username=user.username)
    return True


def _sessions_of(user_id) -> list:
    """Every open sign-in of one account: Django's session rows that name it."""
    from django.contrib.sessions.models import Session

    now = _now_aware()
    mine = []
    for row in Session.objects.filter(expire_date__gt=now).iterator():
        try:
            data = row.get_decoded()
        except Exception:
            continue
        if str(data.get("_auth_user_id") or "") == str(user_id):
            mine.append(row)
    return mine


def _now_aware():
    from django.utils import timezone

    return timezone.now()


def end_all_sessions(username: str) -> int:
    user = get_user(username)
    if user is None:
        return 0
    gone = 0
    for row in _sessions_of(user.pk):
        row.delete()
        gone += 1
    return gone


def sweep(now: float | None = None) -> int:
    """Drop sign-ins that have run out and failures too old to count."""
    from django.contrib.sessions.models import Session

    from .models import SignInFailure

    now = time.time() if now is None else now
    gone, _ = Session.objects.filter(expire_date__lte=_now_aware()).delete()
    SignInFailure.objects.filter(ts__lt=now - max(FAILURE_WINDOW, LOCKOUT_SECONDS) * 4).delete()
    return gone


# --- refused attempts --------------------------------------------------------------

def record_failure(ip: str, username: str, now: float | None = None) -> None:
    from .models import SignInFailure

    SignInFailure.objects.create(ts=time.time() if now is None else now,
                                 ip=(ip or "")[:64], username=(username or "").strip()[:64])


def forget_failures(ip: str = "", username: str = "") -> None:
    """Wipe the slate for an address, an account, or both. A sign-in that
    worked clears what came before it, so a person who mistyped twice and then
    got it right is not still being slowed down an hour later."""
    from django.db.models import Q

    from .models import SignInFailure

    which = Q()
    if ip:
        which |= Q(ip=ip[:64])
    if username:
        which |= Q(username__iexact=username.strip()[:64])
    if not which:
        return
    SignInFailure.objects.filter(which).delete()


def recent_failures(ip: str, username: str, now: float | None = None) -> tuple[int, int]:
    """How many failures this address and this account have run up lately."""
    from .models import SignInFailure

    now = time.time() if now is None else now
    recent = SignInFailure.objects.filter(ts__gte=now - FAILURE_WINDOW)
    by_ip = recent.filter(ip=(ip or "")[:64]).count() if ip else 0
    name = (username or "").strip()[:64]
    by_user = recent.filter(username__iexact=name).count() if name else 0
    return by_ip, by_user


def locked_for(ip: str, username: str, now: float | None = None) -> float:
    """How many seconds until this address or this account may try again.

    Zero means now. The clock runs from the newest failure, so a locked-out
    attacker who keeps trying keeps the lock on themselves.
    """
    from django.db.models import Max, Q

    from .models import SignInFailure

    now = time.time() if now is None else now
    by_ip, by_user = recent_failures(ip, username, now)
    if max(by_ip, by_user) < LOCKOUT_AFTER:
        return 0.0
    newest = SignInFailure.objects.filter(
        Q(ts__gte=now - FAILURE_WINDOW)
        & (Q(ip=(ip or "")[:64]) | Q(username__iexact=(username or "").strip()[:64]))
    ).aggregate(m=Max("ts"))["m"] or now
    return max(0.0, newest + LOCKOUT_SECONDS - now)


def delay_for(ip: str, username: str, now: float | None = None) -> float:
    """How long to wait before telling this caller they were wrong.

    Doubling per recent failure. The first mistake costs almost nothing, so a
    person who fumbles their password does not notice; the tenth costs six
    seconds, which makes a script pointless long before the lockout above.
    """
    by_ip, by_user = recent_failures(ip, username, now)
    return min(DELAY_BASE * (2 ** max(by_ip, by_user)), DELAY_MAX)


# --------------------------------------------------------------------------
# The admin command: python manage.py account
#
# One of the three ways an account is made - the others are the Django admin
# and signing in with Google from an organisation's own domain - and the only
# way to change a password from a terminal. It writes to the same database the
# server reads, so a change takes effect on the next request with no restart.
# A generated password is printed once, here, and kept nowhere.
# --------------------------------------------------------------------------


def _ask_for_a_password(generate: bool, given: str) -> tuple[str, bool]:
    """The password to use, and whether it was made up here.

    Never taken from the command line unless it is asked for there, and never
    echoed: a password in a shell history is a password that leaked.
    """
    if given:
        return given, False
    if generate or not sys.stdin.isatty():
        return generate_password(), True
    first = getpass.getpass("Password: ")
    again = getpass.getpass("Again: ")
    if first != again:
        raise SystemExit("those were not the same")
    if not first:
        raise SystemExit("a password cannot be empty")
    return first, False


def parser(prog: str = "python manage.py account") -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog=prog, description="Rouh's accounts: make one, change a password, list them.")
    sub = ap.add_subparsers(dest="what", required=True)

    add = sub.add_parser("add", help="make an account")
    add.add_argument("username")
    add.add_argument("--email", default="")
    add.add_argument("--org", default="", help="the organisation's id; the default one if not said")
    add.add_argument("--password", default="", help="better to be asked, or to generate one")
    add.add_argument("--generate", action="store_true", help="make one up and print it once")
    add.add_argument("--staff", action="store_true",
                     help="may open the Django admin at /admin/ and manage accounts")

    setp = sub.add_parser("passwd", help="change an account's password")
    setp.add_argument("username")
    setp.add_argument("--password", default="")
    setp.add_argument("--generate", action="store_true")

    ensure = sub.add_parser(
        "ensure",
        help="make the account if it is not there yet, and say nothing if it is")
    ensure.add_argument("username")
    ensure.add_argument("--email", default="")

    sub.add_parser("list", help="every account")

    out = sub.add_parser("signout", help="end every open sign-in for an account")
    out.add_argument("username")
    return ap


def run(args: argparse.Namespace, out=print) -> int:
    """What the command does, once Django is set up."""
    User = get_user_model()

    if args.what == "list":
        users = list(User.objects.select_related("org").order_by("id"))
        for user in users:
            open_now = len(_sessions_of(user.pk))
            when = user.date_joined.strftime("%Y-%m-%d") if user.date_joined else "-"
            role = "admin" if user.is_staff else ("manages org" if user.is_org_admin else
                                                  ("guest" if user.is_guest else "member"))
            out(f"{user.username:<20} {user.email or '-':<28} {user.org_id or '-':<14} "
                f"{role:<11} made {when}  {open_now} open sign-in(s)")
        if not users:
            out("no accounts yet: python manage.py account add <username> --generate")
        return 0

    if args.what == "signout":
        out(f"ended {end_all_sessions(args.username)} sign-in(s) for {args.username}")
        return 0

    if args.what == "ensure":
        if get_user(args.username) is not None:
            out(f"{args.username} already has an account")
            return 0
        password = generate_password()
        add_user(args.username, password, args.email)
        _announce(args.username, password, out)
        return 0

    password, made_up = _ask_for_a_password(args.generate, args.password)

    if args.what == "add":
        try:
            user = add_user(args.username, password, args.email, org_id=args.org)
        except ValueError as exc:
            raise SystemExit(str(exc))
        if args.staff:
            user.is_staff = True
            user.is_superuser = True
            user.save(update_fields=["is_staff", "is_superuser"])
        _announce(args.username, password if made_up else "", out)
        return 0

    if args.what == "passwd":
        if not set_password(args.username, password):
            raise SystemExit(f"there is no account called {args.username!r}")
        out(f"the password for {args.username} is changed, and every browser"
            " signed in as them has been signed out")
        if made_up:
            _announce(args.username, password, out)
        return 0

    return 2


def _announce(username: str, password: str, out=print) -> None:
    out(f"account: {username}")
    if password:
        out(f"password: {password}")
        out("This is the only time it is printed. It is not stored anywhere"
            " it can be read back.")


def main(argv: list[str] | None = None) -> int:
    """``python -m rouh.accounts``: the same command, for the old habit."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rouh.project.settings")
    import django

    django.setup()
    return run(parser("python -m rouh.accounts").parse_args(argv))


if __name__ == "__main__":  # pragma: no cover - the command itself
    raise SystemExit(main())
