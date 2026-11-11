"""Who opens what was shared with them: rouh.land says, and this Rouh checks it against the share.

Petar, 11 November 2026 (task 176, step 176-26): "can you also make the sharing now work through
rouh.land, not through people making accounts in your own rouh installation."

Until then a page or a task shared with somebody by email (`rouh/web/guests.py`) sent them a letter
with a form on this Rouh: their first name and last name, and from then on a sign-in here. Now a
**Connected Rouh** (registered on rouh.land, with its own relay address, `rouh/relay.py`) asks
rouh.land who they are instead:

1. **The letter** links to the share on this Rouh's relay address (`address`), the same address the
   phone uses: `https://<its name>.rouh.page/shared/<token>`.
2. **Not signed in here**, they are sent to `/shared/in` (`rouh/web/gate.py`), which puts a one-time
   `state` in this browser's session and sends them to rouh.land's vouch page (`start`), naming this
   Rouh, the relay name to come back to, the address the share was for, and where to go after.
3. **On rouh.land** they sign in with the one-email sign-in (an emailed link, an optional passkey),
   or sign up in the same step if they have no account yet, and press Continue. rouh.land answers
   with a note of their email signed by its own key, the one this Rouh already pins for its birth
   answers (`birth.defaults`), kind ``rouh-identity`` (rouh-it-site `birth/vouch.py`).
4. **Back at `/shared/in/back`** this Rouh holds the note to everything (`check`): rouh.land's
   signature, the kind, that it is for this Rouh, on one of its own relay names, with the state this
   browser was given, and not past its `until`. Then the email is the person: the share lets them in
   only if it names that email (`sharing.Guests.belongs_to`), view or edit as before, and nothing
   else of this Rouh opens to them (`gate.GUEST_PATHS`).

rouh.land only vouches for who somebody is. It never sees what was shared, and the page goes from
here, through the relay, still locked, as the phone's does.

**What is kept about them here** is the least this Rouh needs to hold a sign-in and keep their own
Ask AI questions apart: a guest record by their email (`User.is_guest`) with rouh.land's id for
them (`User.land_id`), made the first time they come back from rouh.land. It has no name, no
password and no sign-in of its own: only rouh.land lets them in (`may_stay`). Nobody fills in a form.

**Recipients from before.** A guest who made an account from an invitation keeps it, and its sign-in
here, until they first come in through rouh.land: from then that record is theirs by rouh.land
(`land_id` set) and the sign-in here stops (`may_stay`). Every share is by email already, so nothing
shared is lost or moved by hand. An account of this Rouh's own people (not a guest) is never signed
in by rouh.land's word: somebody with one signs in here as always (`guest_for` refuses).

**A Rouh On its own** (never registered on rouh.land, or with no relay address) cannot share
privately: `refusal` says so, and `share_and_tell` stops there rather than making an account.
Public links (`publish_task`, `/p/<token>`) are untouched by all of this.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import secrets
import time
from urllib.parse import urlencode, urlsplit

log = logging.getLogger("rouh.landshare")

#: What rouh.land signs its note as (rouh-it-site `birth/vouch.py`).
KIND = "rouh-identity"
#: Where the person starts, and where rouh.land sends them back to.
IN_PATH = "/shared/in"
BACK_PATH = "/shared/in/back"
#: rouh.land's page that vouches, under its birth service.
VOUCH = "vouch/"
#: The session key the one-time states are kept under, and how many are kept at once (several tabs).
STATES = "landshare_states"
STATES_MAX = 8
#: How long a state waits for its answer.
STATE_SECONDS = 3600
#: The session key that says this sign-in came from rouh.land (`may_stay`).
VOUCHED = "landshare_vouched"
#: The longest note taken from an address.
VOUCH_MAX = 4000

#: What an On its own Rouh says when asked to share with a person.
ON_ITS_OWN = ("This Rouh is On its own, so it cannot share privately with a person: the person it is "
              "shared with signs in with rouh.land, and only a Connected Rouh can ask rouh.land who they "
              "are. Make a public link instead (anyone with the link, no sign-in), or connect this Rouh "
              "to rouh.land in Anatomy, Rouh Land Account.")


class Refused(ValueError):
    """A note from rouh.land that is not let in, with the reason in words."""


class NotAGuest(Refused):
    """The email belongs to one of this Rouh's own accounts, which signs in here, never by rouh.land."""


def _row(org: str = ""):
    from . import birth
    from .tenancy import DEFAULT_ORG_ID

    return birth.current(str(org or DEFAULT_ORG_ID))


def refusal(org: str = "") -> str:
    """Why this Rouh cannot share privately through rouh.land, or "" when it can."""
    from . import relay

    row = _row(org)
    if row is None or not row.registry_id:
        return ON_ITS_OWN
    if row.key_dead_at:
        return ("rouh.land no longer recognises this Rouh's key, so it cannot share privately until its "
                "key is replaced (Anatomy, Rouh Land Account, Rouh profile).")
    if not relay.hostname():
        return ("This Rouh has no relay address yet, so the person it shares with could not reach it. "
                "Turn the relay on (Settings, Connections, Phone) and share again.")
    return ""


def ready(org: str = "") -> bool:
    return not refusal(org)


def address() -> str:
    """Where a person a page is shared with reaches this Rouh: its relay address, the phone's.

    ``ROUH_LANDSHARE_ADDRESS`` names another, for a test world on this machine, which has no relay.
    """
    from . import relay

    return (os.environ.get("ROUH_LANDSHARE_ADDRESS", "").strip().rstrip("/")
            or relay.preferred_address() or relay.address())


def link(path: str) -> str:
    """The whole link to a path on this Rouh, as a letter puts it."""
    return address() + path


def on_address(request) -> bool:
    """Whether this request came to the address the share flow runs on (the session must be there)."""
    want = urlsplit(address()).netloc.lower()
    return bool(want) and (request.get_host() or "").lower() == want


def _then(value) -> str:
    """Where to go after, held to the shared pages of this Rouh: `/shared...`, `/p/...` or `/join/...`."""
    then = str(value or "")[:600]
    if re.match(r"^/(?:shared|p/|join/)", then) and "//" not in then and "\\" not in then \
            and not then.startswith(IN_PATH):
        return then
    return "/shared"


def start(request, then: str, email: str = "") -> str:
    """The address on rouh.land to send this browser to, with a new state kept in its session."""
    from . import birth, relay

    row = _row()
    state = secrets.token_urlsafe(24)
    now = time.time()
    kept = [s for s in (request.session.get(STATES) or []) if now - float(s.get("at") or 0) < STATE_SECONDS]
    kept.append({"state": state, "at": now, "then": _then(then)})
    request.session[STATES] = kept[-STATES_MAX:]
    host = (urlsplit(address()).hostname or "").lower()
    names = relay.hostnames()
    q = {"rouh": row.registry_id, "state": state, "then": _then(then),
         "host": host if host in names else (names[0] if names else host)}
    if email:
        q["email"] = email
    base = row.registry_url or birth.defaults()[0]
    return base.rstrip("/") + "/" + VOUCH + "?" + urlencode(q)


def _decode(raw: str) -> dict:
    raw = str(raw or "")
    if not raw or len(raw) > VOUCH_MAX or not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        raise Refused("The answer from rouh.land is cut short. Open the link in your email again.")
    try:
        doc = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except (ValueError, TypeError):
        raise Refused("The answer from rouh.land could not be read. Open the link in your email again.") from None
    if not isinstance(doc, dict):
        raise Refused("The answer from rouh.land could not be read. Open the link in your email again.")
    return doc


def check(request, raw: str, state: str) -> dict:
    """rouh.land's note, held to everything: {email, land_id, then}. The state is used up.

    Raises Refused, in words, for anything that does not hold. A note whose state this browser was not
    given (opened on another device, or a stranger's) is refused with `then` kept, so the caller can
    start again here, where rouh.land, already signed in, takes one press."""
    from . import birth, genelab, relay

    row = _row()
    if row is None or not row.registry_id:
        raise Refused(ON_ITS_OWN)
    doc = _decode(raw)
    _, key = birth.defaults()
    try:
        payload = genelab.verify(doc, genelab.load_key(key), KIND)
    except genelab.Refused as exc:
        log.warning("landshare: a note from rouh.land was refused: %s", exc)
        raise Refused("rouh.land's answer did not hold, so nobody was let in.") from None
    if str(payload.get("rouh") or "") != str(row.registry_id):
        raise Refused("That answer from rouh.land was for another Rouh.")
    if str(payload.get("host") or "").lower() not in relay.hostnames() and not os.environ.get("ROUH_LANDSHARE_ADDRESS"):
        raise Refused("That answer from rouh.land was for another address.")
    try:
        until = float(payload.get("until") or 0)
    except (TypeError, ValueError):
        until = 0
    if until < time.time():
        raise Refused("That answer from rouh.land is too old. Open the link in your email again.")
    from .sharing import clean_email

    email = clean_email(payload.get("email"))
    land_id = str(payload.get("owner") or "")[:64]
    if not email or not land_id:
        raise Refused("rouh.land's answer named nobody.")
    kept = request.session.get(STATES) or []
    mine = next((s for s in kept if secrets.compare_digest(str(s.get("state") or ""), str(state or ""))
                 and str(payload.get("state") or "") == str(state or "")), None)
    if mine is None or time.time() - float(mine.get("at") or 0) > STATE_SECONDS:
        err = Refused("This browser did not ask for that answer.")
        err.then = _then(payload.get("then"))   # type: ignore[attr-defined]
        raise err
    request.session[STATES] = [s for s in kept if s is not mine]
    return {"email": email, "land_id": land_id, "then": _then(mine.get("then") or payload.get("then"))}


def guest_for(email: str, land_id: str):
    """The guest record for this person, made the first time; NotAGuest for one of this Rouh's own.

    A guest from before, who made an account from an invitation, is found by email and from now on is
    theirs by rouh.land (`land_id`), so its sign-in here stops (`may_stay`)."""
    from django.db import IntegrityError

    from . import signin
    from .models import User
    from .sharing import clean_email

    email = clean_email(email)
    own = signin.user_for(email)
    found = list(User.objects.filter(email__iexact=email, is_active=True).order_by("pk")[:5])
    if own is not None and not own.is_guest:
        raise NotAGuest("This address has an account on this Rouh. Sign in here with it.")
    if any(not u.is_guest for u in found):
        raise NotAGuest("This address has an account on this Rouh. Sign in here with it.")
    guest = next((u for u in found if u.land_id == land_id), None) or (found[0] if found else None)
    if guest is None:
        try:
            guest = User.objects.create_user(username=email, email=email, password=None, is_guest=True,
                                             land_id=land_id)
        except IntegrityError:
            guest = User.objects.filter(username__iexact=email).first()
            if guest is None or not guest.is_guest:
                raise NotAGuest("This address has an account on this Rouh. Sign in here with it.") from None
        log.info("landshare: a guest record was made for a person rouh.land vouched for")
    if guest.land_id != land_id:
        moved = not guest.land_id
        User.objects.filter(pk=guest.pk).update(land_id=land_id)
        guest.land_id = land_id
        if moved:
            log.info("landshare: guest %s moved to rouh.land", guest.pk)
    from . import runtime

    runtime.guests.claim(email, str(guest.pk))
    return guest


def vouched(request) -> None:
    """Mark this sign-in as rouh.land's, after `alogin` made a new session."""
    request.session[VOUCHED] = True


def may_stay(user, session) -> bool:
    """Whether this signed-in user may stay signed in: a guest who is rouh.land's only by rouh.land."""
    if not getattr(user, "is_guest", False) or not getattr(user, "land_id", ""):
        return True
    return bool(session.get(VOUCHED))
