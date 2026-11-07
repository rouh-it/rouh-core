"""The first run of a fresh installation: from nobody to a Rouh that answers, in the browser.

On the server an installation's owner is made by ``python manage.py setup``
(SETUP.md), typed by whoever installs it. In the containers
(`deploy/container/`) nobody types anything: the person starts the stack, from
Rouh for Mac or with ``docker compose up``, and Rouh's page takes them through
the first run, one thing per screen, each at its own address so Back, a reload
and a restart of Rouh land where the person was:

1. ``/setup/you``: first and last name, both required, email, and a password.
   One account, the owner's alone (decisions 1 and 2). The email is how the
   owner signs in; the password is the way in while this Rouh cannot send
   email yet (`rouh/signin.py`, 4 November 2026).
2. ``/setup/connect``: Connected (free, recommended, chosen already) or On its
   own. Connected is its birth: it is registered at once on the birth service
   (``ROUH_BIRTH_URL``, rouh.land unless an installation names its own) with no
   code and no account, which gives it its official name (`birth.be_born`), and
   asks the relay for its own phone address (`rouh/relay.py`). On its own it stays
   a free Rouh: no name, no keys, only the nickname its person gives it (Petar,
   4 November 2026). If rouh.land cannot be reached, a Connected choice stays free
   too, and is connected later on Your profile.
3. ``/setup/born``: born, its name and birthday; or free, "Your Rouh is ready";
   either way the human names the owner may give it (and change, on Anatomy, Rouh
   Land Account, Rouh profile).
4. ``/setup/brain``: an Anthropic or OpenAI key, required, with each company's
   guide built in and the key checked the moment it is pasted (decision 3).

No screen shows, asks for or mentions recovery words or keys. The words were the
fourth screen until 4 November 2026.

Then the chat, which takes over for Google, Telegram, the phone and getting to
know the person (decision 5; the built-in rule ``new-rouh``).

**The setup code.** Nobody ever types or sees it, and it is still what stops
whoever reaches the page first from taking the installation, because no
installation can tell for sure that only its own machine reaches it: a tunnel or
any port forward puts a Mac's page on the internet.

1. The containers' entrypoint writes a code into ``ROUH_FIRST_RUN_CODE_FILE``
   on a start that finds no owner, and ``python manage.py setup_link`` prints
   the whole address for anybody running Docker by hand. Rouh for Mac reads the
   file and opens ``/setup?code=...`` from every button, reading it afresh
   each time.
2. This page takes the code out of the address at once: a right one is kept in
   the browser's session and the browser is sent on, so it is never on the
   screen or in a bookmark.
3. Without it the page says in one line how to open it properly.

The code is also how the owner signs in again
from this machine: the file stays once the owner is made, a right code signs
the owner in, and a new code is written in its place at once, so an address
that was used is dead. That is Rouh for Mac's Open Rouh, unchanged: it opens
the coded address for as long as the file is there. Signing in through the
birth service's accounts replaces it once that service offers them.

The way through is kept in the owner's own settings (``SETTING``), so an owner
made any other way - on a server, before this page - is never sent here.
"""
from __future__ import annotations

import asyncio
import copy
import hmac
import json
import logging
import os
import secrets
import tempfile
import time

from django.contrib.auth import alogin
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.validators import validate_email
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render

from . import claude_signin
from .common import client_ip

log = logging.getLogger("rouh.firstrun")

PATH = "/setup"
#: The screens, in order, each at ``/setup/<screen>``.
SCREENS = ("you", "connect", "born", "words", "brain")

#: Where a right code is kept once it has been taken out of the address.
SESSION_KEY = "firstrun_code"
#: The owner's way through the screens, in their own settings (`UserSetting`).
SETTING = "first_run"

#: What the page says when it is opened without a right code: one line for each way Rouh runs.
OPEN_IT_PROPERLY = "Open Rouh from the Rouh menu bar app on your Mac: press Open Rouh."
WITH_DOCKER = "Running Docker yourself? Run this, then open the address it prints:"
LINK_COMMAND = "docker compose exec core python manage.py setup_link"

#: The two companies whose key gives Rouh a brain on this page: their chats and their terminals.
COMPANIES = {
    "anthropic": {"name": "Anthropic", "product": "Claude", "starts": "sk-ant-",
                  "console": "the Claude Console", "use": "key_check_anthropic"},
    "openai": {"name": "OpenAI", "product": "ChatGPT", "starts": "sk-",
               "console": "the OpenAI Platform", "use": "key_check_openai"},
}


# --- the code ------------------------------------------------------------------------------------


def code_file() -> str:
    return os.environ.get("ROUH_FIRST_RUN_CODE_FILE", "").strip()


def _code() -> str:
    path = code_file()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def new_code() -> str:
    """Write a fresh code in place of the old one, and give it back; "" when there is no file to write."""
    path = code_file()
    if not path:
        return ""
    code = secrets.token_urlsafe(18)
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".new.", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(code + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return code


def _right(code: str) -> bool:
    expected = _code()
    return bool(expected and code) and hmac.compare_digest(code.encode(), expected.encode())


def _kept(request: HttpRequest) -> str:
    """The right code this browser brought, kept in its session; "" when it brought none."""
    code = request.session.get(SESSION_KEY, "")
    return code if isinstance(code, str) and _right(code) else ""


def has_owner() -> bool:
    from rouh.models import User

    return User.objects.filter(is_active=True, is_guest=False).exists()


def the_owner():
    """The installation's owner: its first active account that is not a guest."""
    from rouh.models import User

    return User.objects.filter(is_active=True, is_guest=False).order_by("date_joined", "pk").first()


def open_now() -> bool:
    """Whether the first-run page is open: a code to check, and no owner yet."""
    return bool(_code()) and not has_owner()


def owner_way_in() -> dict | None:
    """How the owner of a containers' Rouh signs in, for the sign-in page; None elsewhere."""
    if not code_file():
        return None
    return {"mac": OPEN_IT_PROPERLY, "docker": WITH_DOCKER, "command": LINK_COMMAND}


# --- the owner's way through ---------------------------------------------------------------------


def record(user) -> dict:
    """What the owner has done of the first run, or {} for an owner who never had one."""
    from rouh.models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(user.pk), name=SETTING)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        return {}
    return held if isinstance(held, dict) else {}


def _save(user, **changes) -> dict:
    from rouh.models import UserSetting

    held = record(user)
    held.update(changes)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(user.pk), org_id=user.org_id or "", name=SETTING,
                     value=json.dumps(held, ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])
    return held


def unfinished(user) -> bool:
    """Whether this person is the owner part way through the first run."""
    if not getattr(user, "is_authenticated", False):
        return False
    held = record(user)
    # chose_later: Connected chosen after a birth with no first run (`relay.linked_later`), not a first run.
    return bool(held) and not held.get("done_at") and not held.get("chose_later")


def _born(user) -> bool:
    from rouh import birth

    return birth.current(str(user.org_id)) is not None


def next_screen(user) -> str:
    """The first screen this owner has not done, or "" when the first run is over (or never was)."""
    held = record(user)
    if not held or held.get("done_at") or held.get("chose_later"):
        return ""
    if "connected" not in held:
        return "connect"
    if not held.get("named_at"):
        return "born"
    return "brain"


def next_path(user) -> str:
    screen = next_screen(user)
    return f"{PATH}/{screen}" if screen else "/"


def key_states(user) -> dict:
    """Each company's key as the brain screen shows it: "ok", "no_credit" or ""."""
    from rouh import providerkeys

    keys = record(user).get("keys") or {}
    out = {}
    for company in COMPANIES:
        state = (keys.get(company) or {}).get("state", "")
        # A key that works is one the chats really have.
        out[company] = state if state != "ok" or providerkeys.has(company, str(user.org_id)) else ""
    return out


def guiding(org_id: str) -> bool:
    """Whether the chat is to take the owner through the rest of setting up: the first run is
    finished, a few days ago at most (the built-in rule ``new-rouh``)."""
    owner = the_owner()
    if owner is None or str(owner.org_id or "") != str(org_id or ""):
        return False
    done = record(owner).get("done_at") or 0
    return bool(done) and time.time() - done < GUIDE_DAYS * 86400


#: How long after the first run the chat offers the next steps of setting up.
GUIDE_DAYS = 14


# --- the pages -----------------------------------------------------------------------------------


def _who(user):
    from rouh import runtime

    return runtime.tenancy.current(user)


def _zone_of(user):
    from rouh import clock
    from rouh.models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(user.pk), name=clock.SETTING)
             .values_list("value", flat=True).first())
    try:
        name = (json.loads(value) or {}).get("zone") if value else ""
    except (TypeError, ValueError, AttributeError):
        name = ""
    return clock.zone_named(name) or clock.zone_named(os.environ.get("ROUH_DEFAULT_ZONE", "")) or clock.DEFAULT


def service_name() -> str:
    """The birth service a Rouh connects to, as the screens name it: the host of its address
    (`birth.defaults`, ``ROUH_BIRTH_URL``), "rouh.land" unless an installation names its own."""
    from urllib.parse import urlparse

    from rouh import birth

    host = (urlparse(birth.defaults()[0]).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _rouh_name(user) -> str:
    from rouh import birth

    row = birth.current(str(user.org_id))
    if row is not None:
        return row.name
    # A free Rouh has no name: what its owner calls it, else Rouh.
    return birth.nickname(str(user.org_id), str(user.pk)) or birth.EVERY_ROUH


def _render(request: HttpRequest, screen: str, *, status: int = 200, **values) -> HttpResponse:
    values.setdefault("step", {"you": 1, "connect": 2, "born": 3, "brain": 4, "key": 4}.get(screen, 0))
    response = render(request, "rouh/firstrun.html", {"screen": screen, **values}, status=status)
    response["Cache-Control"] = "no-store"
    # No other site is told this page's address. Not "no-referrer", which
    # makes the form's own post arrive from nowhere.
    response["Referrer-Policy"] = "same-origin"
    return response


def _not_open(request: HttpRequest, status: int = 200) -> HttpResponse:
    return _render(request, "closed", status=status, mac=OPEN_IT_PROPERLY, docker=WITH_DOCKER,
                   command=LINK_COMMAND)


#: The pages the setup code may send its owner on to, once signed in (``/setup?code=...&next=``).
AFTER_SIGN_IN = {"/setup/claude"}


def _go(where: str) -> HttpResponseRedirect:
    return HttpResponseRedirect(where, status=303)


async def setup(request: HttpRequest) -> HttpResponse:
    """``/setup``: where every button of Rouh for Mac lands, with the code in the address."""
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD"})
    given = request.GET.get("code", "")
    owner = await asyncio.to_thread(has_owner)
    if given:
        # Taken out of the address at once, whatever it is.
        if not await asyncio.to_thread(_right, given):
            log.warning("first run: a wrong setup code from %s", client_ip(request))
            return _go(PATH)
        if not owner:
            await request.session.aset(SESSION_KEY, given)
            return _go(f"{PATH}/you")
        # The owner, signed in from this machine; the code that did it is dead at once.
        person = await asyncio.to_thread(the_owner)
        await asyncio.to_thread(new_code)
        await alogin(request, person, backend="rouh.accounts.CaseInsensitiveBackend")
        log.info("first run: the owner %s signed in with the setup code from %s", person.username, client_ip(request))
        where = await asyncio.to_thread(next_path, person)
        # Rouh for Mac's "Sign in to Claude" goes on to Claude's page, once the first run is over.
        if where == "/" and request.GET.get("next") in AFTER_SIGN_IN:
            where = request.GET["next"]
        return _go(where)
    if not owner:
        if not code_file():
            raise Http404
        if await asyncio.to_thread(_kept, request):
            return _go(f"{PATH}/you")
        return await asyncio.to_thread(_not_open, request)
    user = await request.auser()
    if not user.is_authenticated:
        return _go("/login")
    return _go(await asyncio.to_thread(next_path, user))


# --- 1. you --------------------------------------------------------------------------------------


def _make(request: HttpRequest) -> tuple[object | None, dict, dict]:
    """The owner, from the form: (the account, what was said, the problem with each field)."""
    from rouh import accounts, clock

    said = {k: " ".join((request.POST.get(k) or "").split())
            for k in ("first_name", "last_name", "email", "zone")}
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
    # A password, set once here: the way in while this Rouh cannot send email (4 November 2026). Once
    # it can, a link to the email is the way in and the password stays a quiet fallback.
    password, again = request.POST.get("password1") or "", request.POST.get("password2") or ""
    if not password:
        problems["password"] = "Choose a password, for when Rouh cannot email you yet."
    elif password != again:
        problems["password"] = "The two passwords are not the same."
    else:
        from django.contrib.auth.password_validation import validate_password

        from rouh.models import User

        try:
            validate_password(password, User(username=said["email"], email=said["email"],
                                              first_name=said["first_name"], last_name=said["last_name"]))
        except ValidationError as exc:
            problems["password"] = " ".join(exc.messages)
    if problems:
        return None, said, problems
    email = said["email"].lower()
    zone = clock.zone_named(said["zone"])
    try:
        # The same command a server's owner is made with, and the same rules. The password is
        # made up and thrown away at once: this owner signs in from this machine (`setup`).
        call_command("setup", username=email, email=email, first_name=said["first_name"],
                     last_name=said["last_name"], password=secrets.token_urlsafe(32),
                     zone=zone.key if zone else os.environ.get("ROUH_DEFAULT_ZONE", "").strip(),
                     no_migrate=True, verbosity=0)
    except CommandError as exc:
        return None, said, {"email": str(exc)}
    user = accounts.get_user(email)
    user.set_password(password)
    user.save(update_fields=["password"])
    from rouh import signin

    signin.set_primary(user, email, source="setup")
    _save(user, made_at=time.time(), zone=zone.key if zone else "")
    log.info("first run: the owner %s was made from %s", email, client_ip(request))
    return user, said, {}


async def you(request: HttpRequest) -> HttpResponse:
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    if await asyncio.to_thread(has_owner):
        user = await request.auser()
        return _go(await asyncio.to_thread(next_path, user) if user.is_authenticated else "/login")
    if not code_file():
        raise Http404
    if not await asyncio.to_thread(_kept, request):
        if request.method == "POST":
            log.warning("first run: a setup without the right code from %s", client_ip(request))
        return await asyncio.to_thread(_not_open, request, 403 if request.method == "POST" else 200)
    if request.method != "POST":
        return await asyncio.to_thread(_render, request, "you", said={}, problems={})
    user, said, problems = await asyncio.to_thread(_make, request)
    if user is None:
        return await asyncio.to_thread(_render, request, "you", said=said, problems=problems, status=400)
    await request.session.apop(SESSION_KEY, None)
    await alogin(request, user, backend="rouh.accounts.CaseInsensitiveBackend")
    # Rouh's own scheduled work, for the owner just made, rather than at the next look.
    from rouh import runtime

    runtime.own_work_now()
    return _go(f"{PATH}/connect")


# --- the screens after it, all the owner's -------------------------------------------------------


async def _owner_at(request: HttpRequest, screen: str):
    """The signed-in owner, if this screen is theirs to see now; else where to send them."""
    user = await request.auser()
    if not user.is_authenticated:
        return None, _go("/login")
    nxt = await asyncio.to_thread(next_screen, user)
    if not nxt:
        return None, _go("/")
    # A screen already done may be gone back to; one not reached yet may not.
    if SCREENS.index(screen) > SCREENS.index(nxt):
        return None, _go(f"{PATH}/{nxt}")
    return user, None


# --- 2. connected or on its own ------------------------------------------------------------------


def _choose(user, connected: bool) -> None:
    from rouh import birth

    _save(user, connected=connected, chose_at=time.time())
    if not connected:
        # On its own: a free Rouh, with no birth, no name and no keys (4 November 2026).
        return
    # Connected: born on rouh.land at once, with no code and no account (Petar, 28 October 2026),
    # which gives it its name, and the relay its address. If rouh.land cannot be reached or refuses,
    # it stays a free Rouh, the first run goes on, and it connects later on Your profile.
    try:
        birth.connect(_who(user))
    except birth.Refused as exc:
        log.info("first run: Connected, but not registered on rouh.land: %s", exc)
        return
    # Its own address on the relay, asked for now and kept; nothing is open to the internet until
    # the owner presses "Reach me from my phone" (`rouh/relay.py`).
    from rouh import relay

    if relay.enabled() and not relay.hostname():
        relay.claim_soon(user)


async def connect(request: HttpRequest) -> HttpResponse:
    user, away = await _owner_at(request, "connect")
    if away:
        return away
    if request.method == "POST":
        choice = request.POST.get("choice")
        if choice in ("connected", "own"):
            await asyncio.to_thread(_choose, user, choice == "connected")
            return _go(f"{PATH}/born")
    held = await asyncio.to_thread(record, user)
    return await asyncio.to_thread(_render, request, "connect", connected=held.get("connected", True),
                                   service=await asyncio.to_thread(service_name))


# --- 3. born -------------------------------------------------------------------------------------


def _born_values(user) -> dict:
    from rouh import birth
    from rouh.models import RouhNickname

    row = birth.current(str(user.org_id))
    zone = _zone_of(user)
    from datetime import datetime

    at = datetime.fromtimestamp(row.born_at, zone) if row else None
    nick = RouhNickname.objects.filter(org_id=str(user.org_id), user_id=str(user.pk)).first()
    from rouh import clock

    return {"name": row.name if row else "", "born": row is not None,
            "born_day": f"{at.day} {at.strftime('%B %Y')}" if at else "",
            "born_time": at.strftime("%H:%M") if at else "", "born_place": clock.place(zone),
            "names": {"first": getattr(nick, "first_name", "") if nick else "",
                      "last": getattr(nick, "last_name", "") if nick else "",
                      "nickname": nick.nickname if nick else ""},
            "connected": bool(record(user).get("connected")), "registered": bool(row and row.registry_id),
            "service": service_name(),
            "address": _address_at_birth(user)}


def _address_at_birth(user) -> str:
    """The phone address the claim at birth got, waiting a moment for it; "" for none."""
    from rouh import relay

    if not record(user).get("connected") or not relay.enabled():
        return ""
    relay.claim_waited(BORN_WAITS)
    return relay.hostname()


#: How long the born screen waits for the claim at birth before it draws without the address.
BORN_WAITS = 4.0


def _name_it(user, first: str, last: str, nickname: str) -> None:
    from rouh import birth

    birth.set_human_names(_who(user), first=first, last=last, nickname=nickname)
    _save(user, named_at=time.time())


async def born(request: HttpRequest) -> HttpResponse:
    from rouh import birth

    user, away = await _owner_at(request, "born")
    if away:
        return away
    if request.method == "POST":
        try:
            await asyncio.to_thread(_name_it, user, request.POST.get("first", ""), request.POST.get("last", ""),
                                    request.POST.get("nickname", ""))
        except birth.Refused as exc:
            values = await asyncio.to_thread(_born_values, user)
            values["names"] = {k: request.POST.get(k, "") for k in ("first", "last", "nickname")}
            return await asyncio.to_thread(_render, request, "born", problem=str(exc), status=400, **values)
        return _go(f"{PATH}/brain")
    return await asyncio.to_thread(_render, request, "born", **await asyncio.to_thread(_born_values, user))


# --- 4. a brain ----------------------------------------------------------------------------------


class Check:
    """What a pasted key came to: whether it works, and what to say."""

    def __init__(self, state: str, said: str = ""):
        self.state, self.said = state, said


def _shape(company: str, key: str) -> str:
    """What is wrong with how a pasted key looks, before anybody is asked, or ""."""
    c = COMPANIES[company]
    if not key:
        return f"Paste your {c['name']} key."
    if company == "openai" and key.startswith("sk-ant-"):
        return "That is an Anthropic key. Go back and tap Anthropic to paste it there."
    if company == "anthropic" and key.startswith("sk-") and not key.startswith("sk-ant-"):
        return "That looks like an OpenAI key. Go back and tap OpenAI to paste it there."
    if not key.startswith(c["starts"]):
        return (f"That isn't a {c['name']} key: they start with {c['starts']}. Copy the key again from "
                f"{c['console']}.")
    if len(key) < 30 or len(key) > 400:
        return f"That is only part of a key. Copy the whole key from {c['console']} and paste it again."
    return ""


def no_credit_words(company: str) -> str:
    return (f"Your key is right, but your {COMPANIES[company]['name']} account has no credit yet. "
            "Buy credit (step 2 of the guide), then press Check again.")


def _status(exc: BaseException) -> int:
    return int(getattr(exc, "status_code", 0) or 0)


def _no_credit(exc: BaseException) -> bool:
    from rouh import llm

    said = llm.failure(exc).lower()
    return ("credit balance" in said or "insufficient_quota" in said or "exceeded your current quota" in said
            or getattr(exc, "code", "") == "insufficient_quota")


def _model_list_failure(company: str, exc: BaseException) -> Check:
    """What the company's model-list failure says about a pasted key."""
    import anthropic
    import openai

    from rouh import llm

    c = COMPANIES[company]
    if isinstance(exc, (anthropic.AuthenticationError, openai.AuthenticationError)):
        return Check("wrong", f"{c['name']} doesn't know this key. It may have a typing mistake, or it "
                              f"was deleted (revoked) in {c['console']}. Copy it again, or make a new one.")
    if isinstance(exc, (anthropic.PermissionDeniedError, openai.PermissionDeniedError)):
        return Check("wrong", f"{c['name']} knows this key but won't let it be used. In {c['console']}, "
                              "make a new key with every permission, and paste that one.")
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError, asyncio.TimeoutError)):
        return Check("unreached", f"Rouh couldn't reach {c['name']}. Check this computer's internet "
                                  "connection, then press Check again.")
    return Check("unreached", f"{c['name']} didn't answer properly ({llm.failure(exc)}). Wait a "
                              "minute, then press Check again.")


def _key_trial_failure(company: str, exc: BaseException) -> Check:
    """What the trial question's failure says about the key and its credit."""
    import anthropic
    import openai

    from rouh import llm

    c = COMPANIES[company]
    if isinstance(exc, (anthropic.APIStatusError, openai.APIStatusError)):
        if _no_credit(exc):
            return Check("no_credit", no_credit_words(company))
        if _status(exc) == 429:
            # Busy, not broken: the key and the credit are there.
            return Check("ok")
        return Check("unreached", f"{c['name']} took the key, but its model said: {llm.failure(exc)}.")
    if isinstance(exc, (anthropic.APIConnectionError, openai.APIConnectionError, asyncio.TimeoutError)):
        return Check("unreached", f"Rouh couldn't reach {c['name']}. Check this computer's internet "
                                  "connection, then press Check again.")
    return Check("unreached", f"Rouh couldn't ask {c['name']}: {exc}.")


async def check_key(company: str, key: str, user) -> Check:
    """Ask the company about this key: its list of models first, which proves the key, then one
    word from its cheapest model, through the LLM service, which proves there is credit.
    Nothing is kept here."""
    import anthropic
    import openai

    from rouh import llm, llmlog
    from rouh.config import config

    c = COMPANIES[company]
    who = await asyncio.to_thread(_who, user)
    with llmlog.about(who, purpose=c["use"], subject=company):
        client = llmlog.client(key, max_retries=0) if company == "anthropic" else \
            llmlog.openai_client(key, max_retries=0)
        try:
            await asyncio.wait_for(client.models.list(), 30)
        except (anthropic.APIStatusError, openai.APIStatusError,
                anthropic.APIConnectionError, openai.APIConnectionError, asyncio.TimeoutError) as exc:
            return _model_list_failure(company, exc)
    # The key, and only this key, for the one question: the chats are not given it until it works.
    trial = copy.copy(config)
    setattr(trial, "anthropic_api_key" if company == "anthropic" else "openai_api_key", key)
    try:
        await llm.ask(c["use"], messages="Reply with the word OK.", max_tokens=16, who=who,
                      cfg=trial, timeout=45)
    except (anthropic.APIStatusError, openai.APIStatusError,
            anthropic.APIConnectionError, openai.APIConnectionError, asyncio.TimeoutError, llm.Cannot) as exc:
        return _key_trial_failure(company, exc)
    return Check("ok")


def _hold(user, company: str, key: str) -> None:
    """A right key with no credit yet, kept sealed for Check again, and given to nothing."""
    from rouh.encryption import box

    held = record(user)
    pending = dict(held.get("pending") or {})
    pending[company] = box().seal(key)
    keys = dict(held.get("keys") or {})
    keys[company] = {"state": "no_credit", "last4": key[-4:], "at": time.time()}
    _save(user, pending=pending, keys=keys)


def _held(user, company: str) -> str:
    from rouh.encryption import box

    sealed = (record(user).get("pending") or {}).get(company)
    try:
        return box().open_(sealed) if sealed else ""
    except Exception:
        return ""


def _works(user, company: str, key: str) -> None:
    """A key that works: Rouh's chats have it from this moment (`claude_signin.keep_key`)."""
    claude_signin.keep_key(key, company)
    held = record(user)
    pending = dict(held.get("pending") or {})
    pending.pop(company, None)
    keys = dict(held.get("keys") or {})
    keys[company] = {"state": "ok", "last4": key[-4:], "at": time.time()}
    _save(user, pending=pending, keys=keys)
    log.info("first run: a working %s key was kept", COMPANIES[company]["name"])


async def _terminal_on_key() -> None:
    """Claude Code on the Anthropic key too, when it is not signed in another way yet; never in the way."""
    try:
        status = await claude_signin._status()
        if claude_signin.state_of(status) == "signed_out":
            await claude_signin._ask("api_key", timeout=15, on=True)
    except Exception:  # the worker may not be there yet: /setup/claude does it later
        log.info("first run: Claude Code was not switched to the key now")


def _brain_values(user) -> dict:
    return {"name": _rouh_name(user), "keys": key_states(user),
            "claude_later": claude_signin.enabled()}


async def brain(request: HttpRequest) -> HttpResponse:
    user, away = await _owner_at(request, "brain")
    if away:
        return away
    if request.method == "POST" and request.POST.get("do") == "done":
        states = await asyncio.to_thread(key_states, user)
        if "ok" in states.values():
            await asyncio.to_thread(_save, user, done_at=time.time())
            return _go("/")
    return await asyncio.to_thread(_render, request, "brain", **await asyncio.to_thread(_brain_values, user))


async def company_key(request: HttpRequest, company: str, how: bool = False) -> HttpResponse:
    """``/setup/brain/<company>``: paste a key and have it checked; with ``/how``, the guide too."""
    if company not in COMPANIES:
        raise Http404
    user, away = await _owner_at(request, "brain")
    if away:
        return away
    c = COMPANIES[company]
    states = await asyncio.to_thread(key_states, user)
    values = {"company": company, "c": c, "name": await asyncio.to_thread(_rouh_name, user),
              "state": states.get(company, ""), "how": how}
    if request.method != "POST":
        if values["state"] == "no_credit":
            values["problem"] = no_credit_words(company)
        return await asyncio.to_thread(_render, request, "key", **values)
    if request.POST.get("do") == "again":
        key = await asyncio.to_thread(_held, user, company)
        if not key:
            return await asyncio.to_thread(_render, request, "key", status=400, problem=f"Paste your {c['name']} key again.",
                                           **{**values, "state": ""})
    else:
        key = "".join((request.POST.get("key") or "").split())
        shape = _shape(company, key)
        if shape:
            return await asyncio.to_thread(_render, request, "key", status=400, problem=shape, **values)
    got = await check_key(company, key, user)
    log.info("first run: a pasted %s key came back %s, from %s", c["name"], got.state, client_ip(request))
    if got.state == "ok":
        await asyncio.to_thread(_works, user, company, key)
        if company == "anthropic":
            await _terminal_on_key()
        return _go(f"{PATH}/brain")
    if got.state == "no_credit":
        await asyncio.to_thread(_hold, user, company, key)
        values["state"] = "no_credit"
    return await asyncio.to_thread(_render, request, "key", status=400, problem=got.said, **values)


async def company_how(request: HttpRequest, company: str) -> HttpResponse:
    return await company_key(request, company, how=True)
