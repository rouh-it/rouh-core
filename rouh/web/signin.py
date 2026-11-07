"""Signing in, from the signed-in side: Anatomy, You, Account, and a guest's contact card
(`rouh/signin.py`, `signinpage.js`).

    GET  /api/sign-in/me                   the email that signs you in, and how it is labelled;
                                           your passkeys; whether you have a password
    POST /api/sign-in/email                {email}: change it. Connected to rouh.land, it is changed
                                           there and this Rouh follows, so the answer is where to go.
                                           Not connected, a link goes to the new address and the
                                           change is made when it is opened (or, when this Rouh
                                           cannot send mail, at once, with your password)
    POST /api/sign-in/passkey/options      a challenge for adding a passkey on this device
    POST /api/sign-in/passkey/add          the new passkey
    POST /api/sign-in/passkey/remove       {id}

For the owner, about a guest, from that guest's contact card:

    GET  /api/sign-in/guest?email=         whether that address signs a guest in, and how it can be helped
    POST /api/sign-in/guest/send           {email}: send them a sign-in email now
    POST /api/sign-in/guest/link           {email}: a one-time sign-in link to hand them yourself
"""
from __future__ import annotations

import secrets
import time

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import passkeys, signin

from .auth import _link_base, _rp
from .common import answer, body_of, only, refuse, who
from .google import Meter

#: Add, remove and change, a few a minute; the guest letters too.
meter = Meter(10, 60.0)
ADD_CHALLENGE = "signin_passkey_add"


def _user(me):
    from rouh.models import User

    return User.objects.filter(pk=int(me.user_id)).first()


def _connected(me) -> tuple[bool, str]:
    """Whether this Rouh is connected to a rouh.land account, and that account's page there."""
    from rouh import birth

    row = birth.current(str(me.org_id))
    if row is None or not birth.in_account(row):
        return False, ""
    url = row.registry_url or birth.defaults()[0]
    return True, (url if url.endswith("/") else url + "/") + "account/"


def _when(at, me) -> str:
    from rouh import evolution

    return evolution.when_words(at, me) if at else ""


def state(me) -> dict:
    user = _user(me)
    connected, account_url = _connected(me) if not user.is_guest else (False, "")
    email = signin.primary(user)
    return {
        "email": email,
        "label": "Signs you in to this Rouh and rouh.land" if connected else "Signs you in to this Rouh",
        "connected": connected,
        "account_url": account_url,
        "former": [a["email"] for a in signin.addresses(user) if not a["primary"]],
        "guest": bool(user.is_guest),
        "has_password": user.has_usable_password(),
        "can_send": signin.can_send(str(me.org_id)),
        "passkeys": [{"id": p.pk, "name": p.name or "Passkey", "added": _when(p.created_at, me),
                      "used": _when(p.last_used_at, me)}
                     for p in user.passkeys.order_by("created_at")],
    }


@only("GET")
async def me_state(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await sync_to_async(state)(me), headers={"Cache-Control": "no-store"})


def _change_email(me, request, email: str, password: str) -> dict:
    user = _user(me)
    connected, account_url = _connected(me) if not user.is_guest else (False, "")
    if connected:
        return {"go": account_url, "said": "Your email is changed on rouh.land, and this Rouh follows it."}
    email = signin.normal(email)
    if not signin.looks_right(email):
        raise ValueError("Type the whole email address, such as you@example.com.")
    other = signin.user_for(email)
    if other is not None and other.pk != user.pk:
        raise ValueError(f"{email} already signs another account in to this Rouh.")
    if email == signin.primary(user):
        return {"said": "That is your email already."}
    if not signin.can_send(str(me.org_id)):
        if not user.has_usable_password() or not user.check_password(password or ""):
            raise ValueError("Type your password to change your email: this Rouh cannot send email to check the new one.")
        signin.set_primary(user, email, source="you")
        return {"said": f"You sign in with {email} now. Your old email works until you first sign in with the new one."}
    made = signin.confirm(user, email, ip=request.META.get("REMOTE_ADDR", ""))
    base = _link_base(request)
    return {"said": f"A link went to {email}. Open it to make it your sign-in email; until then nothing changes.",
            "_send": {**made, "link": base + signin.LINK_PATH + made["token"] if base else ""}, "_to": email}


@only("POST")
async def change_email(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if meter.too_many("email:" + me.user_id):
        return refuse("Too many changes at once. Try again in a minute.", 429)
    body = body_of(request)
    try:
        got = await sync_to_async(_change_email)(me, request, body.get("email", ""), body.get("password", ""))
    except (ValueError, signin.Limited) as exc:
        return refuse(str(exc), 400)
    send = got.pop("_send", None)
    to = got.pop("_to", "")
    if send:
        signin.start_sending(str(me.org_id), to, send["token"], send["link"], send["code"])
    return answer({"ok": True, **got, **(await sync_to_async(state)(me))})


@only("POST")
async def passkey_options(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    user = await sync_to_async(_user)(me)
    challenge = secrets.token_bytes(32)
    await request.session.aset(ADD_CHALLENGE, passkeys.b64url(challenge))
    rp_id, _origin = _rp(request)
    email = await sync_to_async(signin.primary)(user)
    have = await sync_to_async(lambda: [passkeys.b64url(bytes(c)) for c in
                                        user.passkeys.values_list("credential_id", flat=True)])()
    return answer({
        "challenge": passkeys.b64url(challenge),
        "rp": {"id": rp_id, "name": "Rouh"},
        "user": {"id": passkeys.b64url(f"rouh-user-{user.pk}".encode()), "name": email or user.username,
                 "displayName": (user.get_full_name() or email or user.username)[:64]},
        "pubKeyCredParams": [{"type": "public-key", "alg": a} for a in passkeys.ALGORITHMS],
        "timeout": 120000, "attestation": "none",
        "authenticatorSelection": {"residentKey": "required", "requireResidentKey": True,
                                   "userVerification": "preferred"},
        "excludeCredentials": [{"type": "public-key", "id": c} for c in have],
        "email": email,
    }, headers={"Cache-Control": "no-store"})


def _add(me, request, body: dict) -> str:
    from rouh.models import Passkey

    challenge = request.session.pop(ADD_CHALLENGE, "")
    if not challenge:
        raise ValueError("Start again: press Add a passkey.")
    rp_id, origin = _rp(request)
    try:
        got = passkeys.registration(client_data=passkeys.unb64url(body.get("clientDataJSON", "")),
                                    attestation=passkeys.unb64url(body.get("attestationObject", "")),
                                    challenge=passkeys.unb64url(challenge), origin=origin, rp_id=rp_id)
    except passkeys.Wrong as exc:
        raise ValueError(f"That passkey was not added: {exc}.") from None
    if Passkey.objects.filter(credential_id=got["credential_id"]).exists():
        raise ValueError("That passkey is on an account here already.")
    name = " ".join(str(body.get("name") or "").split())[:60] or "Passkey"
    Passkey.objects.create(user_id=int(me.user_id), credential_id=got["credential_id"], public_key=got["public_key"],
                           sign_count=got["sign_count"], name=name, created_at=time.time())
    return "Passkey added. On this device, the sign-in page offers it first."


@only("POST")
async def passkey_add(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if meter.too_many("passkey:" + me.user_id):
        return refuse("Too many at once. Try again in a minute.", 429)
    try:
        said = await sync_to_async(_add)(me, request, body_of(request))
    except ValueError as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, "said": said, **(await sync_to_async(state)(me))})


@only("POST")
async def passkey_remove(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    from rouh.models import Passkey

    pk = str(body_of(request).get("id") or "")
    gone = await sync_to_async(lambda: Passkey.objects.filter(
        user_id=int(me.user_id), pk=int(pk) if pk.isdigit() else -1).delete()[0])()
    return answer({"ok": True, "said": "Passkey removed. You still sign in by email." if gone else "",
                   **(await sync_to_async(state)(me))})


# --- the owner, for a guest ---------------------------------------------------------------------------


def _guest_for(me, email: str):
    """The guest this address signs in, when the one asking may help them: the owner, never a guest."""
    if not me.is_admin:
        return None
    asker = _user(me)
    if asker is None or asker.is_guest:
        return None
    user = signin.user_for(email)
    return user if user is not None and user.is_guest else None


@only("GET")
async def guest_state(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    emails = [e for e in str(request.GET.get("email") or "").split(",") if e.strip()][:10]
    found = []
    for email in emails:
        guest = await sync_to_async(_guest_for)(me, email)
        if guest is not None:
            found.append({"email": signin.normal(email), "name": guest.get_full_name() or guest.username})
    return answer({"guests": found, "can_send": await sync_to_async(signin.can_send)(str(me.org_id))},
                  headers={"Cache-Control": "no-store"})


@only("POST")
async def guest_send(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if meter.too_many("guest:" + me.user_id):
        return refuse("Too many at once. Try again in a minute.", 429)
    email = signin.normal(body_of(request).get("email"))
    guest = await sync_to_async(_guest_for)(me, email)
    if guest is None:
        return refuse("That address does not sign a guest in to this Rouh.", 404)
    made = await sync_to_async(signin.issue)(email)
    base = _link_base(request)
    route = await signin.send(str(me.org_id), email, base + made["path"] if base else "", made["code"])
    await sync_to_async(signin.sent_by)(made["token"], route)
    if not route:
        return refuse("The email could not be sent just now. Make a one-time link instead, and give it to them yourself.", 502)
    return answer({"ok": True, "said": f"A sign-in email went to {email}. It works once, for {signin.LINK_MINUTES} minutes."})


@only("POST")
async def guest_link(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if meter.too_many("guest:" + me.user_id):
        return refuse("Too many at once. Try again in a minute.", 429)
    email = signin.normal(body_of(request).get("email"))
    guest = await sync_to_async(_guest_for)(me, email)
    if guest is None:
        return refuse("That address does not sign a guest in to this Rouh.", 404)
    made = await sync_to_async(signin.issue)(email, minutes=60)
    base = _link_base(request)
    return answer({"ok": True, "link": (base + made["path"]) if base else made["path"], "code": made["code"],
                   "said": f"A one-time sign-in link for {email}. Give it to them yourself; it works once, for an hour."})
