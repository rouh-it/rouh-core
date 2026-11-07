"""Signing Claude Code in from Rouh's own page, in the containers.

Rouh's runs are Claude Code in the worker container (`deploy/container/`), and
Claude Code works for somebody only once it is signed in. Nobody who installs
Rouh for Mac is to open a terminal for that, so this page does it, right after
the first-run page has made the owner (`firstrun.py`), and stays at
``/setup/claude`` for the owner to come back to.

Two ways, the person picks one:

* **Sign in with Claude**, their Claude subscription. The worker runs Claude
  Code's own sign-in (`one/claude_signin.py`), this page shows its address as a
  button that opens Claude's page in a new tab, and the code Claude shows there
  is typed into a box here and passed to the worker. Claude Code keeps that
  sign-in in the worker's home, as it does anywhere.
* **An Anthropic API key.** The core keeps it in the keys volume, which only the
  core and the key proxy mount, and tells the worker to send Claude Code through
  the key proxy, which adds the key. The key never reaches the worker.

Apart from both, a key for **Rouh's own chats**, which call Anthropic's or OpenAI's API
themselves and cannot use a Claude subscription: kept in the keys volume and given to the
running Rouh at once (`keep_key`), without switching Claude Code, whose runs stay on the
person's account (a new Rouh's first run, 24 October 2026).

The page is there only where the installation says so (``ROUH_CLAUDE_SIGNIN=1``,
which the core image sets), and only for the owner: an organisation's
administrator, or the installation's.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render

from rouh.one_client import OneClient, OneRefused, OneUnavailable

from .common import client_ip

log = logging.getLogger("rouh.claude_signin")

PATH = "/setup/claude"

#: The file the key proxy reads the Anthropic key from (keyproxy.py, rouh-keys).
KEY_FILE = "anthropic_api_key"
#: Each provider whose key Rouh's own chats can use, with its file in the keys volume and
#: its setting; the key proxy reads the same files, but adds a key to the worker's requests
#: only once Claude Code has been switched to it (`_ask("api_key", on=True)`).
CHAT_KEYS = {"anthropic": (KEY_FILE, "anthropic_api_key", "ANTHROPIC_API_KEY", "Anthropic"),
             "openai": ("openai_api_key", "openai_api_key", "OPENAI_API_KEY", "OpenAI")}


def enabled() -> bool:
    return os.environ.get("ROUH_CLAUDE_SIGNIN", "").strip() == "1"


def keys_dir() -> str:
    return os.environ.get("ROUH_KEYS_DIR", "/keys")


def _may(user) -> bool:
    return bool(user and user.is_authenticated and not getattr(user, "is_guest", False)
                and (user.is_staff or getattr(user, "is_org_admin", False)))


async def _ask(do: str, timeout: float = 30.0, **fields) -> dict:
    return await OneClient(timeout=timeout).ask("claude_signin", do=do, **fields)


async def _status() -> dict:
    """What the worker says, or why it cannot say: never raises."""
    try:
        return {"reached": True, **await _ask("status")}
    except OneUnavailable:
        return {"reached": False}
    except OneRefused as exc:
        return {"reached": False, "why": str(exc)}
    except Exception:  # the worker's answer took too long, or the socket broke
        log.exception("claude sign-in: the worker's status could not be read")
        return {"reached": False}


def state_of(status: dict) -> str:
    """One word for the page: starting, waiting_for_code, signed_in or signed_out."""
    if not status.get("reached") or not status.get("installed"):
        return "starting"
    if status.get("waiting_for_code"):
        return "waiting_for_code"
    return "signed_in" if status.get("signed_in") else "signed_out"


def how_signed_in(status: dict) -> str:
    """The sentence under a green tick: how Claude Code is signed in, in plain words."""
    method = status.get("method") or ""
    if status.get("api_key_through_proxy") or method in ("api_key_helper", "api_key"):
        return "Claude Code uses your Anthropic API key, which Rouh adds to its requests. The worker never sees the key."
    who = status.get("email") or ""
    plan = status.get("subscriptionType") or ""
    said = "Claude Code is signed in with your Claude account"
    if who:
        said += f", {who}"
    if plan:
        said += f" ({plan})"
    return said + "."


def keep_key(value: str, provider: str = "anthropic") -> None:
    """Writes a model key into the keys volume, readable by the core and the key proxy only,
    and gives it to Rouh's own calls at once, with no restart.

    The folder is the core's and its group is the proxy's, `keys`, which the
    core's own user is a member of (Dockerfile.core), so the file is given to
    that group without root, as `rouh-keys` does as root. Written beside its
    place and moved in, so the proxy never reads half a key. It switches
    nothing in the worker: Claude Code stays signed in as it was.
    """
    file, field, env, _ = CHAT_KEYS[provider]
    folder = keys_dir()
    fd, tmp = tempfile.mkstemp(prefix=".new.", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
        os.chown(tmp, -1, os.stat(folder).st_gid)
        os.chmod(tmp, 0o440)
        os.replace(tmp, os.path.join(folder, file))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    # Rouh's own calls read the key from its settings; the chats' clients follow it
    # (`brain.Brain.client`, `luna.client_for`, `llm._client`).
    from rouh.config import config

    setattr(config, field, value)
    os.environ[env] = value


def provider_of(key: str) -> str:
    """Whose key this is, from how it starts: "anthropic", "openai", or "" for neither."""
    if key.startswith("sk-ant-"):
        return "anthropic"
    if key.startswith("sk-"):
        return "openai"
    return ""


def chats_key() -> str:
    """The name of the provider Rouh's own chats have a key for, the first of them, or ""."""
    from rouh import providerkeys
    from rouh.config import PROVIDER_NAMES

    have = providerkeys.available()
    return PROVIDER_NAMES.get(have[0], have[0]) if have else ""


def has_key() -> bool:
    try:
        return os.path.getsize(os.path.join(keys_dir(), KEY_FILE)) > 0
    except OSError:
        return False


def _page(request: HttpRequest, status: dict, *, problem: str = "", key_problem: bool = False,
          chat_problem: str = "", http: int = 200) -> HttpResponse:
    state = state_of(status)
    response = render(request, "rouh/claude_signin.html", {
        "state": state,
        "address": status.get("address", ""),
        "how": how_signed_in(status) if state == "signed_in" else "",
        "problem": problem,
        # The API key's section is opened only for a problem with the key.
        "key_problem": key_problem,
        "has_key": has_key(),
        "why": status.get("why", ""),
        # Rouh's own chats, apart from Claude Code: which provider they answer with, if any.
        "chats_key": chats_key(),
        "chat_problem": chat_problem,
    }, status=http)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


async def page(request: HttpRequest) -> HttpResponse:
    """The page, and what its buttons post to."""
    if not enabled():
        raise Http404
    if not _may(request.user):
        raise Http404
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    if request.method != "POST":
        return _page(request, await _status())

    do = request.POST.get("do") or ""
    try:
        if do == "start":
            await _ask("start", timeout=60)
            return HttpResponseRedirect(PATH, status=303)
        if do == "code":
            status = await _ask("code", timeout=120, code=request.POST.get("code") or "")
            log.info("claude sign-in: Claude Code was signed in from %s", client_ip(request))
            return _page(request, {"reached": True, **status})
        if do == "cancel":
            await _ask("cancel")
            return HttpResponseRedirect(PATH, status=303)
        if do == "chat_key":
            # A key for Rouh's own chats alone: kept, and Claude Code is not switched to it.
            key = (request.POST.get("key") or "").strip()
            provider = provider_of(key)
            if not key or len(key) > 500 or any(c.isspace() for c in key):
                return _page(request, await _status(), http=400,
                             chat_problem="Paste the whole key, in one piece.")
            if not provider:
                return _page(request, await _status(), http=400, chat_problem=(
                    "That is not an Anthropic key (it starts sk-ant-) or an OpenAI key (it starts sk-)."))
            await asyncio.to_thread(keep_key, key, provider)
            log.info("first run: an %s key for the chats was kept from %s", CHAT_KEYS[provider][3], client_ip(request))
            return HttpResponseRedirect(PATH + "#chats", status=303)
        if do == "api_key":
            key = (request.POST.get("key") or "").strip()
            if not key or len(key) > 500 or any(c.isspace() for c in key):
                return _page(request, await _status(), problem="Paste the whole key, in one piece.",
                             key_problem=True, http=400)
            await asyncio.to_thread(keep_key, key)
            log.info("claude sign-in: an Anthropic API key was kept from %s", client_ip(request))
            try:
                status = await _ask("api_key", on=True)
            except (OneUnavailable, OneRefused):
                return _page(request, await _status(), http=503, key_problem=True, problem=(
                    "Your key is kept. The worker is not answering yet, so Claude Code could not be "
                    "switched to it: press Use this key again in a minute."))
            return _page(request, {"reached": True, **status})
    except OneUnavailable:
        return _page(request, await _status(), http=503,
                     problem="Rouh's worker is not answering yet. Wait a minute, then press the button again.")
    except OneRefused as exc:
        why = str(exc).rstrip(".")
        return _page(request, await _status(), http=400, problem=why[:1].upper() + why[1:] + ".")
    raise Http404


async def state(request: HttpRequest) -> JsonResponse:
    """Only the one word, for the page to see the worker become ready without reloading itself."""
    if not enabled() or not _may(request.user):
        raise Http404
    return JsonResponse({"state": state_of(await _status())}, headers={"Cache-Control": "no-store"})
