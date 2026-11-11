"""Signing in to Rouh by email, for owners and guests alike (`rouh/web/auth.py` draws the pages).

Petar, 4 November 2026: "Google is just a source of data. It never decides who you are", "other
guests need email so email authentication is needed ... passkey/face/touch should be extra, not
default", and of Claude's own sign-in screen, one email box and Continue: "that's how it should
be, but behind when do we choose link and pass?! you figure it out."

**What follows Continue, decided here and never picked by the person:**

1. **This device holds a passkey for that email** (the page remembers, in this browser only,
   the addresses a passkey was added for here): the passkey is offered first, with "Send me a link
   instead" under it. Nothing on the server is asked, so nothing says whether an account exists.
2. **Otherwise, if this Rouh can send mail** (`routes`): a letter with a link that works once and
   expires in `LINK_MINUTES`, and a six-digit code in the same letter for reading the mail on
   another device. The page says "Check your email" and has a box for the code.
3. **Otherwise**: a password. It is set once, when the owner first sets the Rouh up and when a
   guest first opens their invitation. Once mail works, links are the default and the password
   stays a fallback, behind "Can't get the email?", never offered as a choice beside the link.

**How the letter goes** (`routes`, in this order, the first that works):

- a Rouh connected to a rouh.land account sends it through rouh.land (`birth.sign_in_letter`),
  from noreply@rouh.land, which sends only sign-in letters for that Rouh's own people;
- else the owner's connected Google account sends it, as Rouh (the way a password reset went);
- else this installation's own mail service (`rouh/mailer.py`), when it has one.

If rouh.land is down, or the account there is gone, only the mail route falls back. Whether
somebody may come in is never asked of rouh.land: it is this Rouh's own record (`SignInEmail`).

**What keeps it from being used against anybody:**

- The page answers the same whether or not an address has an account; a row is written for an
  unknown address too (never sent), so the limits below count both alike, and the letter is sent
  after the page has answered, so the time it takes says nothing either.
- At most one letter per address every `GAP_SECONDS`, `PER_EMAIL` an hour, `PER_IP` an hour from
  one place, `ALL` an hour in all. A code may be tried `CODE_TRIES` times, then that letter is dead.
- A link opened in the browser that asked for it signs in at once; opened anywhere else it shows
  one button first, so a mail service that opens links to check them never uses one up (the same
  pattern as rouh.land's own links).
- Only hashes of links and codes are kept. A link's token never reaches a log line.

**The way in when everything else fails**: ``python manage.py signin_link EMAIL``, run by an
administrator on the machine, prints a one-time link and code for that address (`issue`).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
import time

log = logging.getLogger("rouh.signin")

#: How long a link and its code work.
LINK_MINUTES = 15
#: The shortest time between two letters to one address. Asking again sooner is answered the same
#: and sends nothing: the first letter is on its way.
GAP_SECONDS = 30
PER_EMAIL = 5
PER_IP = 20
ALL = 200
#: Wrong codes a letter takes before it is dead.
CODE_TRIES = 5
#: The path a letter's link opens; its token is blanked from the request log (`password_reset`).
LINK_PATH = "/login/link/"

EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def _m():
    from . import models

    return models


def _now() -> float:
    return time.time()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normal(email) -> str:
    return str(email or "").strip().lower()[:254]


def looks_right(email: str) -> bool:
    return bool(EMAIL.match(email or ""))


def ip_key(ip: str) -> str:
    from django.conf import settings

    return hmac.new(settings.SECRET_KEY.encode(), str(ip or "").encode(), hashlib.sha256).hexdigest()


# --- whose address is it ----------------------------------------------------------------------------


def user_for(email: str):
    """The active account this address signs in, or None.

    An account made after this table began by any other road (`manage.py setup`, `account add`,
    the Django admin) and never given a sign-in address is given its own email the first time
    it is asked for, so no way of making an account leaves one that cannot sign in."""
    email = normal(email)
    if not email:
        return None
    M = _m()
    row = M.SignInEmail.objects.select_related("user").filter(email=email).first()
    if row is None:
        found = list(M.User.objects.filter(email__iexact=email, is_active=True)[:2])
        if len(found) != 1 or M.SignInEmail.objects.filter(user_id=found[0].pk).exists():
            return None
        if _land_guest(found[0]):
            return None
        try:
            M.SignInEmail.objects.create(email=email, user_id=found[0].pk, primary=True, added_at=_now(),
                                         source="account")
        except Exception:  # noqa: BLE001 - made at the same moment by another request
            pass
        return found[0]
    if not row.user.is_active or _land_guest(row.user):
        return None
    return row.user


def _land_guest(user) -> bool:
    """A guest rouh.land vouches for signs in only through rouh.land (`rouh/landshare.py`), never here."""
    return bool(getattr(user, "is_guest", False) and getattr(user, "land_id", ""))


def primary(user) -> str:
    """The address that signs this person in, as Anatomy shows it; "" when they have none."""
    if user is None or not getattr(user, "pk", None):
        return ""
    rows = list(_m().SignInEmail.objects.filter(user_id=user.pk).order_by("-primary", "added_at"))
    if rows:
        return rows[0].email
    own = normal(getattr(user, "email", ""))
    return own if own and user_for(own) == user else ""


def addresses(user) -> list[dict]:
    return [{"email": r.email, "primary": r.primary, "source": r.source}
            for r in _m().SignInEmail.objects.filter(user_id=user.pk).order_by("-primary", "added_at")]


class Taken(ValueError):
    """The address already signs another account in."""


def set_primary(user, email: str, *, source: str, keep_old: bool = True) -> bool:
    """Make `email` the address that signs this person in. The one before stays as a second way in
    until the new one has been used once (`retire_others`), unless `keep_old` is False. Changes
    nothing, and says False, when it is theirs already."""
    from django.db import transaction

    email = normal(email)
    if not looks_right(email):
        raise ValueError(f"{email or 'That'} is not an email address.")
    M = _m()
    with transaction.atomic():
        held = M.SignInEmail.objects.select_for_update().filter(email=email).first()
        if held is not None and held.user_id != user.pk:
            raise Taken(f"{email} already signs another account in to this Rouh.")
        if held is not None and held.primary:
            return False
        others = M.SignInEmail.objects.filter(user_id=user.pk).exclude(email=email)
        if keep_old:
            others.update(primary=False)
        else:
            others.delete()
        if held is None:
            M.SignInEmail.objects.create(email=email, user_id=user.pk, primary=True, added_at=_now(),
                                         source=source)
        else:
            M.SignInEmail.objects.filter(pk=held.pk).update(primary=True, source=source)
    log.info("account %s signs in with a new address now (%s)", user.pk, source)
    return True


def retire_others(user, used: str) -> int:
    """Once the primary address has signed this person in, the former ones stop working."""
    M = _m()
    used = normal(used)
    row = M.SignInEmail.objects.filter(user_id=user.pk, email=used).first()
    if row is None:
        return 0
    M.SignInEmail.objects.filter(pk=row.pk).update(last_used_at=_now())
    if not row.primary:
        return 0
    gone = M.SignInEmail.objects.filter(user_id=user.pk, primary=False).delete()[0]
    if gone:
        log.info("account %s: %d former sign-in address(es) retired, the new one is proven", user.pk, gone)
    return gone


def remove_address(user, email: str) -> bool:
    """Take one address off an account, never its last one."""
    M = _m()
    rows = M.SignInEmail.objects.filter(user_id=user.pk)
    if rows.count() <= 1:
        raise ValueError("That is the only address this account signs in with, so it stays.")
    gone = rows.filter(email=normal(email)).first()
    if gone is None:
        return False
    gone.delete()
    if not rows.filter(primary=True).exists():
        first = rows.order_by("added_at").first()
        M.SignInEmail.objects.filter(pk=first.pk).update(primary=True)
    return True


def follow_land(org: str, email: str) -> bool:
    """rouh.land told this Rouh its account's email (`birth.check`): a connected Rouh's owner signs
    in with that address. rouh.land only ever holds an address its owner opened a link at, so it is
    proven; the address before stays a second way in until the new one has been used once."""
    from .web import firstrun

    email = normal(email)
    if not looks_right(email):
        return False
    owner = _owner_of(org) or firstrun.the_owner()
    if owner is None:
        return False
    try:
        return set_primary(owner, email, source="rouh.land")
    except Taken:
        log.warning("rouh.land's account email already signs another account in here; the owner's is unchanged")
        return False


def _owner_of(org: str):
    from .models import User
    from .models.accounts import DEFAULT_ORG_ID

    return (User.objects.filter(is_active=True, is_guest=False, org_id=org or DEFAULT_ORG_ID)
            .order_by("date_joined", "pk").first())


# --- how a letter can go ---------------------------------------------------------------------------


def _land_ready(org: str) -> bool:
    from . import birth

    row = birth.current(org)
    return bool(row is not None and row.registry_id and row.registry_url and not row.key_dead_at
                and birth.in_account(row))


def _gmail_ready(org: str) -> bool:
    from . import runtime
    from .password_reset import SEND_SCOPE

    owner = _owner_of(org)
    if owner is None or runtime.google_store is None or runtime.google_auth is None:
        return False
    try:
        held = runtime.google_store.connection(str(owner.pk), str(owner.org_id or org))
    except Exception:  # noqa: BLE001 - a store that cannot answer cannot send
        return False
    return bool(held is not None and held.google_email and (not held.scopes or SEND_SCOPE in held.scopes))


def _mailer_ready() -> bool:
    from . import mailer
    from .config import config

    try:
        return mailer.ready(config)
    except Exception:  # noqa: BLE001
        return False


def routes(org: str = "") -> list[str]:
    """The ways this Rouh can send a sign-in letter now, in the order they are tried."""
    from .models.accounts import DEFAULT_ORG_ID

    org = org or DEFAULT_ORG_ID
    out = []
    if _land_ready(org):
        out.append("rouh.land")
    if _gmail_ready(org):
        out.append("gmail")
    if _mailer_ready():
        out.append("mailer")
    return out


def can_send(org: str = "") -> bool:
    return bool(routes(org))


def rouh_name(org: str = "") -> str:
    from . import birth
    from .models.accounts import DEFAULT_ORG_ID

    row = birth.current(org or DEFAULT_ORG_ID)
    return row.name if row is not None and row.name else "your Rouh"


def letter(name: str, link: str, code: str) -> tuple[str, str]:
    """The subject and the words. Plain text: a link in it goes straight to this Rouh."""
    whom = name if name == "your Rouh" else f"{name}, your Rouh"
    from . import outside_links

    if link and outside_links.is_local(link):
        # Never a link that opens only on this Rouh's own computer (task 140, step 140-14): a phone
        # that opens it finds nothing there.
        link = ""
    if not link:
        return (f"Sign in to {name}",
                f"Your code to sign in to {whom}: {code}\n\n"
                "Type it on the sign-in page where you asked for it.\n\n"
                f"The code works once, for the next {LINK_MINUTES} minutes. If you did not ask to sign in, "
                "ignore this email: nothing happens unless the code is typed.\n\n"
                f"{name}\n")
    return (f"Sign in to {name}",
            f"Press the link below to sign in to {whom}.\n\n{link}\n\n"
            f"Reading this on another device? Type this code on the sign-in page instead: {code}\n\n"
            f"The link and the code work once, for the next {LINK_MINUTES} minutes. If you did not ask "
            "to sign in, ignore this email: nothing happens unless the link is pressed or the code typed.\n\n"
            f"{name}\n")


async def _send_one(route: str, org: str, to: str, link: str, code: str) -> bool:
    from asgiref.sync import sync_to_async

    name = await sync_to_async(rouh_name)(org)
    subject, text = letter(name, link, code)
    if route == "rouh.land":
        from . import birth

        await sync_to_async(birth.sign_in_letter)(org, to, link, code)
        return True
    if route == "gmail":
        from . import runtime
        from .config import config
        from .google_api import GoogleClients, Gmail

        owner = await sync_to_async(_owner_of)(org)
        who = await sync_to_async(runtime.tenancy.identity_of)(str(owner.pk))
        held = await sync_to_async(runtime.google_store.connection)(who.user_id, who.org_id)
        sent = await Gmail(GoogleClients(runtime.google_auth, config), who).send(to, subject, text, signed=False)
        runtime.google_audit.wrote(
            "send_mail", to, f"a link to sign in to Rouh, asked for on the sign-in page - message id "
                             f"{(sent or {}).get('id') or 'unknown'}",
            user_id=who.user_id, org_id=who.org_id, account=held.google_email if held else "")
        return True
    if route == "mailer":
        from . import mailer
        from .config import config

        await mailer.Mailer(config).send(mailer.Letter(to=to, subject=subject, text=text))
        return True
    return False


async def send(org: str, to: str, link: str, code: str, *, only: list[str] | None = None) -> str:
    """Send one sign-in letter by the first route that works; the route it went by, or ""."""
    from asgiref.sync import sync_to_async

    from .models.accounts import DEFAULT_ORG_ID

    org = org or DEFAULT_ORG_ID
    for route in (only if only is not None else await sync_to_async(routes)(org)):
        try:
            if await _send_one(route, org, to, link, code):
                return route
        except Exception as exc:  # noqa: BLE001 - the next route is tried
            log.warning("a sign-in letter did not go by %s: %s", route, type(exc).__name__)
    return ""


# --- links and codes -------------------------------------------------------------------------------


class Limited(Exception):
    """Too many letters asked for; the text says so, the same for every address."""


def _limits(email: str, ipk: str, now: float) -> str:
    """Why no new letter goes, or "" when one may. "gap" means one went a moment ago."""
    # A link made by hand on the machine (`issue`) or for a guest by the owner is nobody's ask, so it
    # never holds a letter back.
    L = _m().SignInLink.objects.exclude(route="command")
    hour = now - 3600
    last = L.filter(email=email).order_by("-made_at").values_list("made_at", flat=True).first()
    if last is not None and now - last < GAP_SECONDS:
        return "gap"
    if L.filter(email=email, made_at__gte=hour).count() >= PER_EMAIL:
        return "Too many sign-in emails went to this address in the last hour. Use the newest one, or try again later."
    if L.filter(ip_key=ipk, made_at__gte=hour).count() >= PER_IP:
        return "Too many sign-in emails were asked for from here in the last hour. Try again later."
    if L.filter(made_at__gte=hour).count() >= ALL:
        return "This Rouh has sent a great many sign-in emails in the last hour. Try again in an hour."
    return ""


def new_code() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def make(email: str, *, ip: str, browser: str = "", next_to: str = "", route_hint: str = "") -> dict:
    """Write a new link for an address, cancelling the one before: {token, code, user} or, for an
    address with no account, a row that is never sent ({user: None}). Limited when there is no room."""
    email = normal(email)
    now = _now()
    ipk = ip_key(ip)
    why = _limits(email, ipk, now)
    if why == "gap":
        return {"gap": True, "user": None}
    if why:
        raise Limited(why)
    user = user_for(email)
    M = _m()
    token, code = secrets.token_urlsafe(32), new_code()
    if user is None:
        M.SignInLink.objects.create(token_hash=_hash(token), email=email, ip_key=ipk, made_at=now,
                                    expires_at=now, cancelled_at=now)
        return {"user": None}
    M.SignInLink.objects.filter(email=email, used_at__isnull=True, cancelled_at__isnull=True).update(cancelled_at=now)
    M.SignInLink.objects.create(token_hash=_hash(token), code_hash=_hash(email + ":" + code), email=email,
                                user_id=user.pk, browser=_hash(browser) if browser else "", ip_key=ipk,
                                route=route_hint, next=next_to, made_at=now,
                                expires_at=now + LINK_MINUTES * 60)
    return {"token": token, "code": code, "user": user}


def sent_by(token: str, route: str) -> None:
    """Note the route a letter went by; a letter that went by none is cancelled."""
    L = _m().SignInLink.objects.filter(token_hash=_hash(token))
    if route:
        L.update(route=route)
    else:
        L.update(cancelled_at=_now())


def peek(token: str):
    return _m().SignInLink.objects.select_related("user").filter(token_hash=_hash(token)).first() if token else None


def why_not(link) -> str:
    """Why this link no longer signs anybody in, or "" while it does."""
    if link is None:
        return "This is not a sign-in link of this Rouh's, or not a whole one."
    if link.used_at:
        return "This link was used already. Each link works once."
    if link.cancelled_at:
        return "A newer sign-in email was sent to this address since, and only the newest one works."
    if link.expires_at <= _now():
        return f"This link has expired. Each link works for {LINK_MINUTES} minutes."
    if link.user is None or not link.user.is_active:
        return "This address no longer signs anybody in to this Rouh."
    if link.next == CONFIRM:
        other = user_for(link.email)
        return "" if other is None or other == link.user else "This address signs another account in now."
    if user_for(link.email) != link.user:
        return "This address no longer signs anybody in to this Rouh."
    return ""


def same_browser(link, browser: str) -> bool:
    return bool(browser and link.browser) and hmac.compare_digest(_hash(browser), link.browser)


def take(link):
    """Use the link up, once, whatever else happens at the same moment: its account, or None."""
    now = _now()
    if _m().SignInLink.objects.filter(pk=link.pk, used_at__isnull=True, cancelled_at__isnull=True,
                                      expires_at__gt=now).update(used_at=now) != 1:
        return None
    user = link.user
    if link.next == CONFIRM:
        # A new address, proven by its own letter: it signs this person in from now on.
        set_primary(user, link.email, source="confirmed")
    retire_others(user, link.email)
    return user


#: A link's `next` when it confirms a new sign-in address rather than signing in (`confirm`).
CONFIRM = "confirm-email"


def confirm(user, email: str, *, ip: str) -> dict:
    """A letter to a new address a signed-in person asked to sign in with: opening its link makes
    it theirs. Nothing changes until then. {token, code}."""
    email = normal(email)
    now = _now()
    ipk = ip_key(ip)
    why = _limits(email, ipk, now)
    if why == "gap":
        raise Limited("A link went to that address a moment ago. Look for it before asking again.")
    if why:
        raise Limited(why)
    M = _m()
    token, code = secrets.token_urlsafe(32), new_code()
    M.SignInLink.objects.filter(email=email, used_at__isnull=True, cancelled_at__isnull=True).update(cancelled_at=now)
    M.SignInLink.objects.create(token_hash=_hash(token), code_hash=_hash(email + ":" + code), email=email,
                                user_id=user.pk, ip_key=ipk, next=CONFIRM,
                                made_at=now, expires_at=now + LINK_MINUTES * 60)
    return {"token": token, "code": code}


def by_code(email: str, code: str):
    """The account the newest letter to this address is for, if `code` is its code; else None.
    A wrong code counts against that letter, and `CODE_TRIES` of them kill it."""
    email, code = normal(email), re.sub(r"\D", "", str(code or ""))
    M = _m()
    now = _now()
    link = (M.SignInLink.objects.select_related("user")
            .filter(email=email, used_at__isnull=True, cancelled_at__isnull=True, expires_at__gt=now)
            .exclude(code_hash="").order_by("-made_at").first())
    if link is None or len(code) != 6:
        return None
    if not hmac.compare_digest(link.code_hash, _hash(email + ":" + code)):
        tries = link.code_tries + 1
        M.SignInLink.objects.filter(pk=link.pk).update(
            code_tries=tries, **({"cancelled_at": now} if tries >= CODE_TRIES else {}))
        return None
    if why_not(link):
        return None
    return take(link)


def issue(email: str, *, minutes: int = LINK_MINUTES) -> dict:
    """The emergency way in, for an administrator on the machine (`manage.py signin_link`): a
    link and code for an address that signs an account in, sent to nobody. Raises ValueError for an
    address that signs nobody in."""
    email = normal(email)
    user = user_for(email)
    if user is None:
        raise ValueError(f"{email} signs nobody in to this Rouh. `manage.py signin_email list` shows who signs in with what.")
    M = _m()
    now = _now()
    token, code = secrets.token_urlsafe(32), new_code()
    M.SignInLink.objects.filter(email=email, used_at__isnull=True, cancelled_at__isnull=True).update(cancelled_at=now)
    M.SignInLink.objects.create(token_hash=_hash(token), code_hash=_hash(email + ":" + code), email=email,
                                user_id=user.pk, ip_key=ip_key("command"), route="command", made_at=now,
                                expires_at=now + max(1, min(int(minutes), 60)) * 60)
    log.info("a one-time sign-in link was made by hand for account %s", user.pk)
    return {"token": token, "code": code, "path": LINK_PATH + token, "user": user}


def start_sending(org: str, to: str, token: str, link: str, code: str) -> None:
    """Send after the page has answered, so the time it takes says nothing about the address."""
    from asgiref.sync import sync_to_async

    async def go():
        route = await send(org, to, link, code)
        await sync_to_async(sent_by)(token, route)
        if not route:
            log.warning("a sign-in letter could not be sent by any route")

    task = asyncio.get_running_loop().create_task(go())
    _under_way.add(task)
    task.add_done_callback(_under_way.discard)


_under_way: set = set()


def hide_token(text: str) -> str:
    return re.sub(r"(" + re.escape(LINK_PATH) + r")[A-Za-z0-9_\-]+", r"\1(token)", text)
