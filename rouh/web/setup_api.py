"""The first run as a JSON API, for Rouh for Mac's own native setup screens (task 140, step 140-13).

Petar, 10 November 2026: "show pages in the setup. but make them native, not web-based with some
kind of browser." So Rouh for Mac draws every screen of the first run itself, in SwiftUI, and does
the work through these addresses; the browser opens only at the very end, on Open Rouh. The web
screens (`firstrun.py`) stay exactly as they were, for a Rouh set up on a server or with
``docker compose`` by hand, which has no app. Both are one first run: the same record in the
owner's settings (``firstrun.SETTING``), the same helpers, the same calls to rouh.land.

**Who may call.** Only whoever holds the setup code: Rouh for Mac reads it from the core's file
(`firstrun.code_file`) through Docker on the Mac, and sends it as ``Authorization: Bearer <code>``.
Unlike ``/setup?code=``, which ends up in a browser's history and so is used once, the header never
leaves the Mac, and the code is not replaced by a call here. Everything under ``/setup`` is refused
through the relay (`relay.local_only`), so none of this is reachable from a phone or the internet.

**What an Independent Rouh sends.** Nothing, to anybody: ``you`` with ``kind=independent`` makes
the owner on this computer and stops; ``born``, ``key`` and ``plan`` talk only to this Rouh, its
worker and the model company of the key that was pasted. The address calls (``name``,
``address/email``) answer 409 for an Independent Rouh before anything is sent.

The order the app follows, and ``step`` in every answer: ``you`` (no owner yet), ``kind`` (an owner
made before the choice came first), ``email`` (Connected: the code rouh.land emailed), ``born``,
``brain`` (a working key), ``plan`` (Claude Code on a Claude plan, or skipped knowing it costs more),
then ``done``. The address page and Open Rouh are the app's own; ``open`` gives the address to open.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import secrets
import time

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import claude_signin, firstrun
from .common import client_ip

log = logging.getLogger("rouh.setup_api")

NO_STORE = {"Cache-Control": "no-store"}
KINDS = {"connected": True, "independent": False}


def _answer(doc: dict, status: int = 200) -> JsonResponse:
    return JsonResponse(doc, status=status, headers=NO_STORE)


def _problem(text: str, status: int = 400, **more) -> JsonResponse:
    return _answer({"problem": text, **more}, status)


def _bearer(request: HttpRequest) -> str:
    said = request.headers.get("Authorization", "")
    return said[7:].strip() if said.lower().startswith("bearer ") else ""


def _body(request: HttpRequest) -> dict:
    try:
        got = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return {}
    return got if isinstance(got, dict) else {}


def endpoint(*methods: str):
    """An address of this API: only its methods, only with the setup code, never through the relay
    (the middleware already refuses ``/setup`` there; checked again here)."""
    def wrap(view):
        @csrf_exempt
        @functools.wraps(view)
        async def inner(request: HttpRequest, *args, **kwargs):
            from rouh import relay

            if request.method not in methods:
                return _answer({"problem": f"Use {' or '.join(methods)}."}, 405)
            if not firstrun.code_file():
                return _answer({"problem": "This Rouh has no setup code, so it has no setup API."}, 404)
            if relay.enabled() and await asyncio.to_thread(relay.through, request):
                return _answer({"problem": "Not here."}, 404)
            from . import gate

            if gate.through_edge(request):
                return _answer({"problem": "Not here."}, 404)
            if not await asyncio.to_thread(firstrun._right, _bearer(request)):
                if await asyncio.to_thread(firstrun.code_expired):
                    return _answer({"problem": "The setup code has expired: it lasts "
                                               f"{firstrun.code_hours():g} hours while Rouh has no owner. "
                                               "Run rouh setup for a new one.", "expired": True}, 401)
                log.warning("setup api: a call without the right setup code from %s", client_ip(request))
                return _answer({"problem": "The setup code is not right. Read it again from the core."}, 401)
            return await view(request, *args, **kwargs)
        return inner
    return wrap


# --- the state -----------------------------------------------------------------------------------


def _plan_skipped(held: dict) -> bool:
    return bool(held.get("plan_skipped_at"))


def step_of(user, plan_on: bool | None = None) -> str:
    """Where the owner is in the native first run (the module's docstring has the order)."""
    if user is None:
        return "you"
    held = firstrun.record(user)
    if held.get("done_at") or (not held and firstrun.has_owner()):
        return "done"
    if "connected" not in held:
        return "kind"
    if held.get("connected") and held.get("email_wait") and not firstrun._born(user):
        return "email"
    if not held.get("named_at"):
        return "born"
    if "ok" not in firstrun.key_states(user).values():
        return "brain"
    if not plan_on and not _plan_skipped(held):
        return "plan"
    return "ready"


def _relay_part() -> dict:
    from rouh import relay

    if not relay.enabled():
        return {"relay": False}
    held = relay.read()
    st = relay.SUPERVISOR.snapshot()
    return {"relay": True, "hostname": held.get("hostname") or "", "chosen": held.get("chosen") or "",
            "addresses": relay.hostnames(held), "address": relay.preferred_address(held),
            "relay_state": st["state"] if held.get("on") else "off", "relay_said": st["said"] if held.get("on") else "",
            "reachable": bool(held.get("on") and st["state"] == "connected" and relay.has_cert(held)),
            "pending": (held.get("pending") or {}).get("said") or "", "claim_error": held.get("claim_error") or ""}


def state(user=None) -> dict:
    """Everything the app's screens draw, in one answer (blocking; run it in a thread)."""
    from rouh import birth

    user = user if user is not None else firstrun.the_owner()
    doc = {"v": 1, "service": firstrun.service_name(), "owner": user is not None}
    if user is None:
        doc["step"] = "you"
        return doc
    held = firstrun.record(user)
    connected = held.get("connected")
    doc.update({
        "kind": None if connected is None else ("connected" if connected else "independent"),
        "first_name": user.first_name or "", "email": user.email or "",
        "email_to": held.get("email_to") or "", "email_sent": bool(held.get("email_ticket")),
        "email_minutes": held.get("email_minutes") or 15, "email_problem": held.get("email_problem") or "",
        "keys": firstrun.key_states(user), "plan_skipped": _plan_skipped(held),
        "done": bool(held.get("done_at")),
    })
    row = birth.current(str(user.org_id))
    born = firstrun._born_values(user) if row is not None or connected is False else {}
    doc["born"] = {"born": bool(born.get("born")), "name": born.get("name") or firstrun._rouh_name(user),
                   "day": born.get("born_day", ""), "time": born.get("born_time", ""),
                   "place": born.get("born_place", ""), "nickname": (born.get("names") or {}).get("nickname", ""),
                   "every": birth.EVERY_ROUH} if born or row is not None else None
    if connected:
        doc.update(_relay_part())
    doc["step"] = step_of(user, plan_on=None)
    return doc


async def _plan_card() -> dict:
    """Claude Code's sign-in as the plan screen needs it; never raises."""
    from . import subscriptions

    try:
        card = await subscriptions.card("claude")
    except Exception:  # noqa: BLE001 - the worker is starting, or gone for a moment
        return {"state": "starting", "on_plan": False}
    return {"state": claude_signin.state_of(card), "on_plan": bool(card.get("on_plan")),
            "address": card.get("address") or "", "email": card.get("email") or "",
            "plan": card.get("subscriptionType") or card.get("plan") or "",
            "how": claude_signin.how_signed_in(card) if card.get("signed_in") else ""}


async def _codex_card() -> dict:
    """Codex's sign-in, as the plan step needs it: a ChatGPT plan counts as the subscription, an
    OpenAI key that Codex runs on does not (that is the "Go on without a plan" path). Never raises."""
    from . import codex_signin

    s = await codex_signin.status()
    card = codex_signin.public(s)
    card["on_plan"] = card["state"] == "signed_in" and card.get("method") != "api_key"
    if card.get("address"):
        card["qr"] = qr_rows(card["address"])
    return card


async def _full_state(request: HttpRequest | None = None, *, plan: bool = True) -> dict:
    doc = await asyncio.to_thread(state)
    if plan and doc.get("owner") and doc["step"] in ("plan", "ready", "done"):
        card = await _plan_card()
        if card.get("address"):
            card["qr"] = qr_rows(card["address"])
        doc["plan"] = card
        doc["codex"] = await _codex_card()
        if doc["step"] == "plan" and (card["on_plan"] or doc["codex"]["on_plan"]):
            doc["step"] = "ready"
    if doc.get("step") == "ready" and doc.get("done"):
        doc["step"] = "done"
    return doc


@endpoint("GET")
async def get_state(request: HttpRequest) -> JsonResponse:
    return _answer(await _full_state(request))


# --- you: the owner, and Connected or Independent -------------------------------------------------


def _password_problem(password: str, said: dict) -> str:
    """Django's own rules for a password, the same ones the web's form holds (`password_rules`)."""
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    from rouh.models import User

    try:
        validate_password(password, User(username=said.get("email", ""), email=said.get("email", ""),
                                          first_name=said.get("first_name", ""), last_name=said.get("last_name", "")))
    except ValidationError as exc:
        return " ".join(exc.messages)
    return ""


def _make_owner(said: dict, password: str = "") -> tuple[object | None, dict]:
    """The owner from the app's screen: names and email. With no password the app signs them in on
    this Mac with the setup code and a Connected Rouh sends sign-in letters through rouh.land; a
    server's terminal wizard (``rouh setup``, task 176, step 176-25) gives the owner's own password,
    held to the same rules as the web's form, as the way in from any browser."""
    from django.core.exceptions import ValidationError
    from django.core.management import call_command
    from django.core.management.base import CommandError
    from django.core.validators import validate_email

    from rouh import accounts, clock, signin

    problems = {}
    if not said["first_name"]:
        problems["first_name"] = "Type your first name."
    if not said["last_name"]:
        problems["last_name"] = "Type your last name. Only one name? Put one letter here."
    if not said["email"]:
        problems["email"] = "Type your email."
    else:
        try:
            validate_email(said["email"])
        except ValidationError:
            problems["email"] = "That doesn't look like an email address. Check it for a typing mistake."
    if password and not problems:
        bad = _password_problem(password, said)
        if bad:
            problems["password"] = bad
    if problems:
        return None, problems
    email = said["email"].lower()
    zone = clock.zone_named(said.get("zone") or "")
    try:
        call_command("setup", username=email, email=email, first_name=said["first_name"],
                     last_name=said["last_name"], password=secrets.token_urlsafe(32),
                     zone=zone.key if zone else "", no_migrate=True, verbosity=0)
    except CommandError as exc:
        return None, {"email": str(exc)}
    user = accounts.get_user(email)
    if password:
        user.set_password(password)
        user.save(update_fields=["password"])
    signin.set_primary(user, email, source="setup")
    firstrun._save(user, made_at=time.time(), zone=zone.key if zone else "", made_by=said.get("by") or "mac")
    return user, {}


@endpoint("POST")
async def you(request: HttpRequest) -> JsonResponse:
    body = _body(request)
    kind = body.get("kind")
    if kind not in KINDS:
        return _problem("Choose Connected or Independent first.")
    if await asyncio.to_thread(firstrun.has_owner):
        return _problem("This Rouh already has its owner.", 409, state=await _full_state(request))
    said = {k: " ".join(str(body.get(k) or "").split()) for k in ("first_name", "last_name", "email", "zone")}
    said["by"] = "terminal" if body.get("by") == "terminal" else "mac"
    password = body.get("password")
    password = password if isinstance(password, str) else ""
    user, problems = await asyncio.to_thread(_make_owner, said, password)
    if user is None:
        return _problem(next(iter(problems.values())), 400, problems=problems)
    from rouh import runtime

    runtime.own_work_now()
    # Connected: rouh.land emails the code now. Independent: nothing leaves this computer.
    await asyncio.to_thread(firstrun._choose, user, KINDS[kind])
    log.info("setup api: the owner %s was made from %s (%s)", user.username,
             "the terminal" if said["by"] == "terminal" else "Rouh for Mac", kind)
    return _answer(await _full_state(request))


@endpoint("POST")
async def kind(request: HttpRequest) -> JsonResponse:
    """An owner made before the choice came first, or the email never came: Connected or Independent."""
    want = _body(request).get("kind")
    if want not in KINDS:
        return _problem("Choose Connected or Independent.")
    user = await asyncio.to_thread(firstrun.the_owner)
    if user is None:
        return _problem("Make the owner first.", 409)
    held = await asyncio.to_thread(firstrun.record, user)
    if await asyncio.to_thread(firstrun._born, user):
        return _problem("This Rouh is born already; connect it later in Anatomy, Your Rouh.", 409)
    if want == "independent" and held.get("connected"):
        await asyncio.to_thread(firstrun._save, user, connected=False, email_wait=False, email_ticket="")
    elif want == "connected" and not held.get("connected"):
        await asyncio.to_thread(firstrun._choose, user, True)
    elif "connected" not in held:
        await asyncio.to_thread(firstrun._choose, user, KINDS[want])
    return _answer(await _full_state(request))


# --- the email code (Connected) -------------------------------------------------------------------


@endpoint("POST")
async def email(request: HttpRequest) -> JsonResponse:
    user = await asyncio.to_thread(firstrun.the_owner)
    if user is None or await asyncio.to_thread(step_of, user) != "email":
        return _problem("There is no email code waiting.", 409, state=await _full_state(request))
    body = _body(request)
    do = body.get("do") or "check"
    if do == "resend":
        bad = await asyncio.to_thread(firstrun._send_code, user)
        doc = await _full_state(request)
        return _answer({**doc, "notice": "" if bad else "A new code is on its way. Only the newest one works.",
                        "problem": bad}, 429 if bad else 200)
    if do == "change":
        bad = await asyncio.to_thread(firstrun._change_email, user, body.get("email", ""))
        doc = await _full_state(request)
        return _answer({**doc, "notice": "" if bad else "The code is on its way to your new address.",
                        "problem": bad}, 400 if bad else 200)
    if do == "independent":
        await asyncio.to_thread(firstrun._save, user, connected=False, email_wait=False, email_ticket="")
        return _answer(await _full_state(request))
    bad, born_now = await asyncio.to_thread(firstrun._check_code, user, body.get("code", ""))
    if not born_now:
        return _answer({**await _full_state(request), "problem": bad}, 400)
    return _answer(await _full_state(request))


# --- born -----------------------------------------------------------------------------------------


@endpoint("POST")
async def born(request: HttpRequest) -> JsonResponse:
    from rouh import birth

    user = await asyncio.to_thread(firstrun.the_owner)
    if user is None or await asyncio.to_thread(step_of, user) in ("you", "kind", "email"):
        return _problem("Your Rouh is not born yet.", 409, state=await _full_state(request))
    try:
        await asyncio.to_thread(firstrun._name_it, user, str(_body(request).get("nickname") or ""))
    except birth.Refused as exc:
        return _problem(str(exc), 400)
    return _answer(await _full_state(request))


# --- a brain: the key -----------------------------------------------------------------------------


@endpoint("POST")
async def key(request: HttpRequest) -> JsonResponse:
    """A pasted key, checked with its company at once: kept when it works, held when it has no
    credit yet (``do: again`` checks the held one), refused with the reason otherwise. Unlike the
    web's brain screen, a working key does not end the first run: the plan comes next."""
    user = await asyncio.to_thread(firstrun.the_owner)
    if user is None or await asyncio.to_thread(step_of, user) in ("you", "kind", "email", "born"):
        return _problem("Your Rouh needs its birth first.", 409)
    body = _body(request)
    company = body.get("company")
    if company not in firstrun.COMPANIES:
        return _problem("Choose Anthropic or OpenAI.")
    c = firstrun.COMPANIES[company]
    if body.get("do") == "again":
        pasted = await asyncio.to_thread(firstrun._held, user, company)
        if not pasted:
            return _problem(f"Paste your {c['name']} key again.")
    else:
        pasted = "".join(str(body.get("key") or "").split())
        shape = firstrun._shape(company, pasted)
        if shape:
            return _problem(shape.replace("Go back and tap", "Choose"))
    got = await firstrun.check_key(company, pasted, user)
    log.info("setup api: a pasted %s key came back %s", c["name"], got.state)
    if got.state == "ok":
        await asyncio.to_thread(firstrun._works, user, company, pasted)
        if company == "anthropic":
            await firstrun._terminal_on_key()
        return _answer(await _full_state(request))
    if got.state == "no_credit":
        await asyncio.to_thread(firstrun._hold, user, company, pasted)
    return _answer({**await _full_state(request), "problem": got.said, "key_state": got.state}, 400)


# --- the plan: Claude Code on a Claude subscription -----------------------------------------------


@endpoint("GET", "POST")
async def plan(request: HttpRequest) -> JsonResponse:
    """``start`` gives Claude's own sign-in address, which the app opens (Claude's page, not
    Rouh's); ``code`` passes the code Claude shows; ``skip`` goes on with the agents on the API key,
    chosen knowing it costs more; ``unskip`` takes that back."""
    from rouh.one_client import OneRefused, OneUnavailable

    user = await asyncio.to_thread(firstrun.the_owner)
    if user is None:
        return _problem("Make the owner first.", 409)
    if request.method == "POST":
        body = _body(request)
        do = body.get("do")
        try:
            if do == "start":
                await claude_signin._ask("start", timeout=60)
            elif do == "code":
                await claude_signin._ask("code", timeout=120, code=str(body.get("code") or ""))
                log.info("setup api: Claude Code was signed in with a Claude plan")
            elif do == "cancel":
                await claude_signin._ask("cancel")
            elif do == "skip":
                await asyncio.to_thread(firstrun._save, user, plan_skipped_at=time.time())
                log.info("setup api: the owner chose to run the agents without a plan")
            elif do == "unskip":
                await asyncio.to_thread(firstrun._save, user, plan_skipped_at=None)
            else:
                return _problem("Choose start, code, cancel or skip.")
        except OneUnavailable:
            return _problem("Rouh's worker is not answering yet. Wait a minute, then press the button again.", 503,
                            state=await _full_state(request))
        except OneRefused as exc:
            why = str(exc).rstrip(".")
            return _problem(why[:1].upper() + why[1:] + ".", 400, state=await _full_state(request))
        except asyncio.TimeoutError:
            return _problem("Claude did not answer in time. Press Sign in with Claude again.", 504)
    return _answer(await _full_state(request))


# --- done: the first run is over ------------------------------------------------------------------


@endpoint("POST")
async def done(request: HttpRequest) -> JsonResponse:
    """Over only when a key works and the plan is signed in or skipped (Petar, 10 November 2026:
    "Rouh is ready only when step 6 is done, and step 7 is done or explicitly skipped")."""
    doc = await _full_state(request)
    if doc.get("step") not in ("ready", "done"):
        return _problem("Setup is not finished yet.", 409, state=doc)
    user = await asyncio.to_thread(firstrun.the_owner)
    if not doc.get("done"):
        await asyncio.to_thread(firstrun._save, user, done_at=time.time())
        await asyncio.to_thread(firstrun._greet, user)
        log.info("setup api: the first run is over (Rouh for Mac)")
    return _answer(await _full_state(request))


# --- the address: Connected only ------------------------------------------------------------------


def _connected_owner():
    user = firstrun.the_owner()
    if user is None or not firstrun.record(user).get("connected"):
        return None
    return user


@endpoint("GET", "POST")
async def name(request: HttpRequest) -> JsonResponse:
    """GET ``?name=``: whether that name is free on rouh.page (asked of rouh.land). POST ``{name}``:
    take it as this Rouh's own address beside its born one ("" gives it back)."""
    from rouh import relay

    if await asyncio.to_thread(_connected_owner) is None:
        return _problem("Only a Connected Rouh has an address to name.", 409)
    try:
        if request.method == "GET":
            return _answer(await asyncio.to_thread(relay.name_free, request.GET.get("name", "")))
        got = await asyncio.to_thread(relay.choose_name, str(_body(request).get("name") or ""))
    except relay.Refused as exc:
        return _problem(str(exc), 409)
    return _answer({**await _full_state(request, plan=False), "chosen_now": got.get("chosen", "")})


@endpoint("POST")
async def address_email(request: HttpRequest) -> JsonResponse:
    """Email it to me: rouh.land emails the owner's account this Rouh's addresses."""
    from rouh import relay

    if await asyncio.to_thread(_connected_owner) is None:
        return _problem("Only a Connected Rouh has an address to email.", 409)
    try:
        got = await asyncio.to_thread(relay.address_letter)
    except relay.Refused as exc:
        return _problem(str(exc), 409)
    return _answer({"sent_to": got.get("sent_to", "")})


@endpoint("POST")
async def open_rouh(request: HttpRequest) -> JsonResponse:
    """Where Open Rouh goes, signed in: the owner's own domain when ``rouh domain`` turned one on
    (task 176, step 176-25), else the rouh.page address with a one-time sign-in when the relay has
    it reachable, else this computer's own address with the setup code (``where: local``). The app
    tries the first and falls back to the second when the Mac cannot reach it. ``qr`` is the link as
    rows for a terminal to draw."""
    from rouh import relay

    from . import gate

    user = await asyncio.to_thread(firstrun.the_owner)
    out: dict = {"where": "local"}
    own = gate.edge_domain()
    if user is not None and own:
        link = await asyncio.to_thread(relay.signin_link, user, "open", f"https://{own}")
        out = {"where": "domain", "url": link["link"], "address": f"https://{own}", "seconds": link["seconds"]}
    elif user is not None and relay.enabled():
        part = await asyncio.to_thread(_relay_part)
        if part.get("reachable") and await asyncio.to_thread(lambda: bool(firstrun.record(user).get("connected"))):
            try:
                link = await asyncio.to_thread(relay.signin_link, user, "open")
                out = {"where": "relay", "url": link["link"], "address": part.get("address", ""),
                       "seconds": link["seconds"]}
            except relay.Refused:
                pass
    code = await asyncio.to_thread(firstrun._code)
    out["local"] = f"/setup?code={code}" if code else "/"
    if out.get("url"):
        out["qr"] = qr_rows(out["url"])
    return _answer(out)


# --- for the terminal: password rules, a QR code as rows, Codex's device code --------------------
#
# Task 176, step 176-25: ``rouh setup`` on a Linux server is the same first run as Rouh for Mac's,
# drawn in a terminal. These three are what a terminal needs that the Mac draws itself.


def qr_rows(text: str) -> list[str]:
    """A QR code of ``text`` as rows of "1" (dark) and "0" (light), quiet zone included, for a
    terminal to draw with half blocks. Made here with segno, which the core has and a server may not."""
    if not text:
        return []
    import segno

    q = segno.make(text, error="l")
    return ["".join("1" if cell else "0" for cell in row) for row in q.matrix_iter(scale=1, border=2)]


@endpoint("GET", "POST")
async def password(request: HttpRequest) -> JsonResponse:
    """GET: the rules a password is held to, to show before anything is typed. POST ``{password,
    first_name, last_name, email}``: each rule met or not, and the server's own verdict."""
    from rouh import password_rules

    rules = [{"kind": r["kind"], "text": r["text"]} for r in password_rules.rules(username_is_email=True)
             if r["kind"] != "same"]
    if request.method == "GET":
        return _answer({"rules": rules, "min": password_rules.min_length()})
    body = _body(request)
    pw = body.get("password") if isinstance(body.get("password"), str) else ""
    said = {k: " ".join(str(body.get(k) or "").split()) for k in ("first_name", "last_name", "email")}

    def judge() -> dict:
        from django.contrib.auth.password_validation import get_default_password_validators
        from django.core.exceptions import ValidationError

        from rouh.models import User

        person = User(username=said["email"], email=said["email"], first_name=said["first_name"],
                      last_name=said["last_name"])
        met = []
        for v, r in zip(get_default_password_validators(), rules):
            try:
                v.validate(pw, person)
                met.append({**r, "met": True})
            except ValidationError:
                met.append({**r, "met": False})
        return {"rules": met, "problem": _password_problem(pw, said)}

    return _answer(await asyncio.to_thread(judge))


@endpoint("GET", "POST")
async def codex(request: HttpRequest) -> JsonResponse:
    """Codex on a ChatGPT plan, by its device code (``codex login --device-auth`` in the worker,
    `one/codex_signin.py`): ``start`` gives the address and the one-time code, which the owner
    approves on any device; GET follows it; ``cancel`` stops waiting. The code must first be allowed
    in ChatGPT's own security settings, which the address's page says."""
    from rouh.one_client import OneRefused, OneUnavailable

    from . import codex_signin

    if await asyncio.to_thread(firstrun.the_owner) is None:
        return _problem("Make the owner first.", 409)
    if request.method == "POST":
        do = _body(request).get("do")
        if do not in ("start", "cancel", "test"):
            return _problem("Choose start, cancel or test.")
        try:
            await codex_signin._ask(do, timeout=60)
        except OneUnavailable:
            return _problem("Rouh's worker is not answering yet. Wait a minute, then try again.", 503)
        except OneRefused as exc:
            why = str(exc).rstrip(".")
            return _problem(why[:1].upper() + why[1:] + ".", 400)
        log.info("setup api: Codex sign-in %s", do)
    return _answer(await _codex_card())
