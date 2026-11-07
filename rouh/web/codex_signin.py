"""Signing Codex in with a ChatGPT plan from Rouh's own page, in the containers.

Petar, 6 November 2026: "That logging needs to be ironed out and SIMPLE because people will
have to be able to login." Codex runs in the worker container, as Claude Code does, and
works for somebody only once it is signed in. Nobody is to open a terminal for that, so this
page does it, at ``/setup/codex``, beside ``/setup/claude``, and Settings, Models has the
same button (``rouh/templates/rouh/index.html``, the Agents card).

One press: the worker runs Codex's own device sign-in (``one/codex_signin.py``), and this page
shows the address and the one-time code Codex gives, large, with a link and a QR code so it
can be done from a phone. The page asks every few seconds how it is going and changes by
itself when Codex says it is signed in, then shows the result of one trivial Codex run that
proves a real run gets past the sign-in. The code also goes to the phone, as a notice
(`notices.phone`), which reaches Telegram only when it is left unseen: the page, while it is
in front of somebody, marks it seen.

Apart from it, for somebody with no ChatGPT plan, a choice of billing every run of Codex to
the OpenAI API key, per use; off until they turn it on, and never turned on for them. And Sign
out, which is ``codex logout``.

Nothing of Codex's sign-in file ever reaches this process: the worker answers whether it is
signed in, as whom and on which plan, and nothing else. The page is there only where the
installation says so (``ROUH_CLAUDE_SIGNIN=1``, which the core image sets, and which turns on
both agents' sign-in pages), and only for the owner: an organisation's administrator, or the
installation's.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import os

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import render

from rouh.one_client import OneClient, OneRefused, OneUnavailable

from . import claude_signin
from .common import client_ip

log = logging.getLogger("rouh.codex_signin")

PATH = "/setup/codex"
#: The kind of the notice that carries the code to the phone.
NOTICE = "codex-signin"
#: The file in the keys volume the key proxy reads OpenAI's key from (`claude_signin.CHAT_KEYS`).
OPENAI_KEY_FILE = claude_signin.CHAT_KEYS["openai"][0]

#: How the plans Codex names read on the page.
PLANS = {"plus": "ChatGPT Plus", "pro": "ChatGPT Pro", "team": "ChatGPT Team", "business": "ChatGPT Business",
         "enterprise": "ChatGPT Enterprise", "edu": "ChatGPT Edu", "free": "ChatGPT Free", "go": "ChatGPT Go"}


def enabled() -> bool:
    return claude_signin.enabled()


async def _ask(do: str, timeout: float = 30.0, **fields) -> dict:
    return await OneClient(timeout=timeout).ask("codex_signin", do=do, **fields)


async def status() -> dict:
    """What the worker says, or why it cannot say: never raises."""
    try:
        return {"reached": True, **await _ask("status")}
    except OneUnavailable:
        return {"reached": False}
    except OneRefused as exc:
        return {"reached": False, "why": str(exc)}
    except Exception:  # the worker's answer took too long, or the socket broke
        log.exception("codex sign-in: the worker's status could not be read")
        return {"reached": False}


def state_of(s: dict) -> str:
    """One word: starting, waiting, signed_in or signed_out."""
    if not s.get("reached") or not s.get("installed"):
        return "starting"
    if s.get("waiting"):
        return "waiting"
    return "signed_in" if s.get("signed_in") else "signed_out"


def plan_name(plan: str) -> str:
    plan = str(plan or "").strip()
    return PLANS.get(plan.lower(), plan.replace("_", " ").title() if plan else "")


def how(s: dict) -> str:
    """The one sentence the page and Settings say of Codex now."""
    state = state_of(s)
    if state == "starting":
        return "Codex: the worker is not answering yet."
    if state == "waiting":
        return "Codex: waiting for the code to be approved on OpenAI's page."
    if state == "signed_out":
        return "Codex: not signed in."
    if s.get("method") == "api_key":
        return "Codex: signed in with an OpenAI API key."
    said = "Codex: signed in"
    if s.get("email"):
        said += f" as {s['email']}"
    if s.get("plan"):
        said += f", {plan_name(s['plan'])}"
    return said + "."


def has_openai_key() -> bool:
    try:
        return os.path.getsize(os.path.join(claude_signin.keys_dir(), OPENAI_KEY_FILE)) > 0
    except OSError:
        return False


def qr_svg(text: str) -> str:
    """The address as a QR code, an SVG drawn here with segno: nothing is fetched from anywhere."""
    if not text:
        return ""
    import segno

    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", xmldecl=False, svgns=True, nl=False, scale=6, border=2,
                                     dark="#000", light="#fff")
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def public(s: dict) -> dict:
    """What a browser is given: the state and the sentence, and never anything of the sign-in file."""
    state = state_of(s)
    out = {"state": state, "said": how(s), "page": PATH,
           "api_key_chosen": bool(s.get("api_key_chosen")), "has_openai_key": has_openai_key()}
    if state == "waiting":
        out.update(code=str(s.get("code") or ""), address=str(s.get("address") or ""),
                   expires=s.get("expires"))
    if state == "signed_in":
        out.update(email=str(s.get("email") or ""), plan=plan_name(s.get("plan") or ""),
                   method=str(s.get("method") or ""))
    last = s.get("last") or {}
    if last and not last.get("ok") and state != "waiting":
        out["failed"] = str(last.get("said") or "Codex did not finish signing in.")
    test = s.get("test") or {}
    if test:
        out["test"] = {"running": bool(test.get("running")), "ok": bool(test.get("ok")),
                       "said": str(test.get("said") or "")}
    if s.get("why") and state == "starting":
        out["why"] = str(s["why"])
    return out


def _notice_link(s: dict) -> str:
    return str(s.get("address") or "")


async def _tell_phone(s: dict) -> None:
    """The code as a notice; it goes on to Telegram only if nobody looks at it (`notices`)."""
    from rouh import notices

    code, address = str(s.get("code") or ""), _notice_link(s)
    if not (code and address):
        return
    try:
        await notices.phone(
            f"Sign Codex in with ChatGPT: open {address} and enter the code {code}. It expires in 15 minutes.",
            kind=NOTICE, key=f"{NOTICE}:{code}", title=f"Codex sign-in code {code}", link=address)
    except Exception:  # noqa: BLE001 - the code is on the page either way
        log.exception("codex sign-in: the code could not be sent to the phone")


async def _settle(link: str) -> None:
    """The code's notice is read: somebody has it in front of them, or it is no longer wanted."""
    from rouh import notices

    if not link:
        return
    who = await notices._owner()
    if who is not None:
        await notices.settled(who, kind=NOTICE, link=link)


def _page(request: HttpRequest, s: dict, *, problem: str = "", key_problem: str = "", http: int = 200) -> HttpResponse:
    shown = public(s)
    response = render(request, "rouh/codex_signin.html", {
        **shown, "s": shown, "problem": problem, "key_problem": key_problem,
        "qr": qr_svg(shown.get("address", "")) if shown["state"] == "waiting" else "",
    }, status=http)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


async def page(request: HttpRequest) -> HttpResponse:
    """The page, and what its buttons post to."""
    if not enabled() or not claude_signin._may(request.user):
        raise Http404
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    if request.method != "POST":
        return _page(request, await status())

    do = request.POST.get("do") or ""
    back = PATH if request.POST.get("back") != "settings" else "/"
    try:
        if do == "start":
            s = {"reached": True, **await _ask("start", timeout=60)}
            log.info("codex sign-in: started from %s", client_ip(request))
            await _tell_phone(s)
            return HttpResponseRedirect(PATH, status=303)
        if do in ("cancel", "logout", "test"):
            before = await status() if do == "cancel" else {}
            await _ask(do, timeout=60)
            await _settle(_notice_link(before))
            if do == "logout":
                log.info("codex sign-in: signed out from %s", client_ip(request))
            return HttpResponseRedirect(back, status=303)
        if do == "api_key":
            on = request.POST.get("on") == "1"
            await _ask("api_key", on=on)
            log.info("codex sign-in: runs billed to %s, from %s", "the OpenAI key" if on else "the plan",
                     client_ip(request))
            return HttpResponseRedirect(PATH + "#key", status=303)
        if do == "openai_key":
            key = (request.POST.get("key") or "").strip()
            if not key or len(key) > 500 or any(c.isspace() for c in key) or claude_signin.provider_of(key) != "openai":
                return _page(request, await status(), http=400,
                             key_problem="Paste the whole OpenAI key, in one piece. It starts sk-.")
            await asyncio.to_thread(claude_signin.keep_key, key, "openai")
            log.info("codex sign-in: an OpenAI key was kept from %s", client_ip(request))
            return HttpResponseRedirect(PATH + "#key", status=303)
    except OneUnavailable:
        return _page(request, await status(), http=503,
                     problem="Rouh's worker is not answering yet. Wait a minute, then press the button again.")
    except OneRefused as exc:
        why = str(exc).rstrip(".")
        return _page(request, await status(), http=400, problem=why[:1].upper() + why[1:] + ".")
    raise Http404


async def state(request: HttpRequest) -> JsonResponse:
    """Where the sign-in is, for the page and Settings to follow it without reloading.

    ``seen=1`` is the page saying it is in front of somebody: the code's notice is then marked
    seen, so it does not go on to the phone.
    """
    if not enabled() or not claude_signin._may(request.user):
        raise Http404
    s = await status()
    if request.GET.get("seen") == "1" and state_of(s) == "waiting":
        await _settle(_notice_link(s))
    elif state_of(s) == "signed_in":
        await _settle(_notice_link(s.get("last") or {}))
    return JsonResponse(public(s), headers={"Cache-Control": "no-store"})
