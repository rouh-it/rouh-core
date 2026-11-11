"""``rouh setup``: Rouh's first run in a terminal, for a server with no screen (task 176, step 176-25).

The same first run as Rouh for Mac's native screens (0.4.0 and 0.5.0, task 140) and the web's
(`rouh/web/firstrun.py`), in the same order and words, done through the same JSON API
(`rouh/web/setup_api.py`) on 127.0.0.1 with the setup code, so nothing of setup is ever reachable
from the network:

1. What kind of Rouh: Connected first, the recommended one; Independent beside it (step 176-15).
2. About you: names, email, and a password, its rules shown before anything is typed.
3. Connected: the 6-digit code rouh.land emails, before the birth (step 176-20).
4. Born: Name, Birthday, URL; it always answers to Rouh, and a nickname is optional.
5. A brain: an Anthropic or OpenAI key, required, checked live with a real answer.
6. A plan for the agents: Claude (paste back the code Claude shows) or ChatGPT (Codex's device
   code), pushed hard and on by default; going on without one needs "Go on without a plan…" and
   its cost warning, as on the Mac (Petar, 11 November 2026: "obligatory" key, plan "optional
   but highly recommended").
7. Ready: the address to open, a one-time sign-in link with a QR code for a phone.

It can be stopped at any point and run again; it carries on where the API says setup is.
"""
from __future__ import annotations

import time

from common import (BOLD, DIM, NO, OK, RESET, WARN, Api, Stop, ask, can_ask, choose, code_status, heading,
                    name, qr, say, setup_code, user_name, yes, local_ip, public_ip, port)

# --- the words, Rouh for Mac's (NativeSetup.swift, SetupWords) unless a terminal needs its own ------

KIND_TITLE = "What kind of Rouh do you want?"
KIND_LEDE = "You can change this later."
CONNECTED_DETAIL = "A free rouh.land account with the email you type next, and a service that helps your Rouh with:"
CONNECTED_BULLETS = [
    "Models: which model to use for what, at the best price.",
    "Security: fixes as soon as they are out.",
    "Updates: new versions of Rouh as they come out.",
    "Gene ideas: from other Rouhs, in the Gene Pool.",
    "Your own address: reach your Rouh from your phone, from anywhere, with nothing to open on this server.",
]
INDEPENDENT_DETAIL = "Runs on this server on its own, with no rouh.land account."
INDEPENDENT_BULLETS = [
    "What you fill in stays on this server and goes nowhere.",
    "It answers to Rouh, or to a nickname you give it.",
    "No Gene Pool, no address for your phone. You reach it through SSH, your own VPN or your own domain.",
]
KIND_FOOTER = ("Either way your files, chats and every call to a model stay on your Rouh. A Connected Rouh sends "
               "rouh.land only its birth and your email, for your account.")
YOU_CONNECTED = "Your name and email make your rouh.land account. rouh.land emails you a code next."
YOU_INDEPENDENT = "Only for your own protection: what you type stays on this server and goes nowhere."
PASSWORD_LEDE = "A password, for signing in to your Rouh from any browser. It needs:"
BRAIN_LEDE = "Choose a company and paste its API key. Rouh's chats use it. One is enough, and it is required."
BRAIN_STEPS = {
    "anthropic": ["Open the Claude Console, at the address below, on any computer or phone, and sign in.",
                  "Add credit under Billing: Rouh pays per use.",
                  "Under API keys, press Create Key, then copy it.",
                  "Paste it here. It is not shown as you paste."],
    "openai": ["Open the OpenAI Platform, at the address below, on any computer or phone, and sign in.",
               "Add credit under Billing: Rouh pays per use.",
               "Under API keys, press Create new secret key, then copy it.",
               "Paste it here. It is not shown as you paste."],
}
CONSOLE = {"anthropic": "https://console.anthropic.com/settings/keys", "openai": "https://platform.openai.com/api-keys"}
COMPANY = {"anthropic": "Anthropic", "openai": "OpenAI"}
PLAN_TITLE = "Run Rouh's agents on a plan (strongly recommended)"
PLAN_LEDE = ("Rouh's agents do the long jobs: in Claude Code on a Claude Pro or Max plan, or in Codex on a "
             "ChatGPT plan. On a plan they cost a fixed monthly price. Without one, every job is billed by use "
             "on your API key, and that costs much more.")
CLAUDE_STEPS = ["Open the address below on any computer or phone (or scan the code): it is Claude's own sign-in page.",
                "Sign in and press Authorize.",
                "Claude shows a code. Copy it, come back here and paste it."]
CODEX_STEPS = ["First, in ChatGPT on the web: Settings, Security, turn on device code sign-in for Codex.",
               "Open the address below on any computer or phone (or scan the code).",
               "Sign in, type the code shown here, and approve. This waits for you."]
SKIP_LINK = "Go on without a plan…"
SKIP_WARNING = ("Every job the agents do is then billed by use on your API key, and costs much more than a plan. "
                "You can connect a plan later: run rouh setup again, or in Rouh, Settings, Models.")
READY_TITLE = "Rouh is ready"


def _problem(doc: dict) -> str:
    said = doc.get("problem") or "Rouh said no, without a reason."
    # The API's words are the Mac's, which has buttons; a terminal has choices.
    return said.replace("press the button again", "choose it again").replace("Press Resend code", "Type r")


def _zone() -> str:
    try:
        from pathlib import Path

        z = Path("/etc/timezone").read_text().strip()
        if z:
            return z
    except OSError:
        pass
    import os

    link = os.path.realpath("/etc/localtime")
    return link.split("zoneinfo/", 1)[1] if "zoneinfo/" in link else ""


# --- the steps ---------------------------------------------------------------------------------------


def step_kind() -> str:
    heading(KIND_TITLE)
    say(KIND_LEDE, "")
    say(f"  {BOLD}C  Connected Rouh{RESET} (recommended)", f"     {CONNECTED_DETAIL}")
    for b in CONNECTED_BULLETS:
        say(f"       · {b}")
    say("", f"  {BOLD}I  Independent Rouh{RESET}", f"     {INDEPENDENT_DETAIL}")
    for b in INDEPENDENT_BULLETS:
        say(f"       · {b}")
    say("", f"{DIM}{KIND_FOOTER}{RESET}", "")
    got = choose("Connected or Independent? [C/i] ", [("connected", ""), ("independent", "")], "connected")
    say(f"{OK} {'Connected Rouh' if got == 'connected' else 'Independent Rouh'}.")
    return got


def _password(api: Api, said: dict) -> str:
    status, doc = api.call("password")
    rules = doc.get("rules") or [] if status == 200 else []
    say("", PASSWORD_LEDE)
    for r in rules:
        say(f"  · {r['text']}")
    say("  · The same twice")
    while True:
        first = ask("Password (hidden): ", hidden=True)
        status, doc = api.call("password", {"password": first, **said})
        if status != 200:
            raise Stop(_problem(doc))
        for r in doc.get("rules") or []:
            say(f"  {OK if r['met'] else NO} {r['text']}")
        if doc.get("problem"):
            say(f"{WARN} {doc['problem']} Try another.")
            continue
        again = ask("The same password again (hidden): ", hidden=True)
        if again != first:
            say(f"  {NO} The same twice", f"{WARN} The two passwords are not the same. Type it again.")
            continue
        say(f"  {OK} The same twice")
        return first


def step_you(api: Api, kind: str) -> dict:
    heading("About you")
    say(YOU_CONNECTED if kind == "connected" else YOU_INDEPENDENT, "")
    while True:
        said = {"first_name": ask("First name: "), "last_name": ask("Last name (only one name? put one letter): "),
                "email": ask("Email: ")}
        zone = _zone()
        got = ask(f"Your time zone [{zone or 'UTC'}]: ", default=zone)
        password = _password(api, said)
        status, doc = api.call("you", {"kind": kind, **said, "zone": got, "password": password, "by": "terminal"})
        if status == 200:
            say(f"{OK} You are the owner of this Rouh.")
            return doc
        say(f"{WARN} {_problem(doc)}")
        if status == 409:
            return api.state()


def step_email(api: Api, doc: dict) -> dict:
    heading("Check your email")
    while True:
        to, minutes = doc.get("email_to") or doc.get("email"), doc.get("email_minutes") or 15
        if doc.get("email_problem") and not doc.get("email_sent"):
            say(f"{WARN} {doc['email_problem']}")
        else:
            say(f"rouh.land sent a 6-digit code to {to}. Type it here. It works for {minutes} minutes.")
        say(f"{DIM}Or: r to resend the code, c to change the email, i to set it up as Independent instead.{RESET}")
        got = ask("Code: ").strip().lower().replace(" ", "")
        if got in ("r", "resend"):
            status, doc = api.call("email", {"do": "resend"})
            say(f"{OK if status == 200 else WARN} {doc.get('notice') or _problem(doc)}")
            continue
        if got in ("c", "change"):
            status, doc = api.call("email", {"do": "change", "email": ask("Your email: ")})
            say(f"{OK if status == 200 else WARN} {doc.get('notice') or _problem(doc)}")
            continue
        if got in ("i", "independent"):
            if yes("Set it up as an Independent Rouh instead, with no rouh.land account?", default=False):
                _, doc = api.call("email", {"do": "independent"})
                return doc
            continue
        if not got.isdigit() or len(got) != 6:
            say(f"{WARN} The code is the 6 digits in the email.")
            continue
        status, doc = api.call("email", {"do": "check", "code": got}, timeout=120)
        if status == 200:
            say(f"{OK} Your email is confirmed, and your rouh.land account is made.")
            return doc
        say(f"{WARN} {_problem(doc)}")


def step_born(api: Api, doc: dict) -> dict:
    born = doc.get("born") or {}
    connected = doc.get("kind") == "connected"
    heading("Your Rouh is born!" if connected else "Your Rouh is ready")
    say(f"  Name:      {name(born.get('name', ''))}")
    if born.get("day"):
        say(f"  Birthday:  {born['day']}")
    if connected and (doc.get("address") or doc.get("hostname")):
        say(f"  URL:       {doc.get('address') or 'https://' + doc['hostname']}")
    say("", "It always answers to Rouh. You can also give it a nickname, which it answers to as well.")
    nick = ask("Nickname (optional, Enter for none): ")
    status, doc = api.call("born", {"nickname": nick})
    if status != 200:
        say(f"{WARN} {_problem(doc)}")
        return api.state()
    if nick:
        say(f"{OK} It answers to Rouh and to {name(nick)}.")
    return doc


def step_brain(api: Api, doc: dict) -> dict:
    who = (doc.get("born") or {}).get("name") or "Rouh"
    heading(f"Give {name(who)}{BOLD} a brain")
    say(BRAIN_LEDE, "")
    company = choose("Anthropic or OpenAI? [A/o] ", [("anthropic", ""), ("openai", "")], "anthropic")
    say("")
    for i, line in enumerate(BRAIN_STEPS[company], 1):
        say(f"  {i}. {line}")
    say("", f"     {CONSOLE[company]}", "")
    while True:
        key = ask(f"Your {COMPANY[company]} key (hidden): ", hidden=True)
        if not key:
            if yes("Use the other company instead?", default=False):
                return step_brain(api, doc)
            continue
        say(f"Checking it with {COMPANY[company]}: a real question, and its answer…")
        status, got = api.call("key", {"company": company, "key": key}, timeout=180)
        while status == 400 and got.get("key_state") == "no_credit":
            say(f"{WARN} {_problem(got)}")
            if not yes("Added credit? Check the same key again?"):
                break
            status, got = api.call("key", {"company": company, "do": "again"}, timeout=180)
        if status == 200:
            say(f"{OK} {COMPANY[company]} answered: the key works. Rouh's chats use it.")
            return got
        say(f"{WARN} {_problem(got)}")


def _wait_plan(api: Api, which: str, seconds: int) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        status, doc = api.call("state", timeout=90)
        if status == 200 and (doc.get(which) or {}).get("on_plan"):
            return True
        time.sleep(4)
    return False


def plan_claude(api: Api) -> bool:
    status, doc = api.call("plan", {"do": "start"}, timeout=90)
    if status != 200:
        say(f"{WARN} {_problem(doc)}")
        return False
    card = doc.get("plan") or {}
    if not card.get("address"):
        for _ in range(10):
            time.sleep(3)
            card = (api.state().get("plan") or {})
            if card.get("address"):
                break
    if not card.get("address"):
        say(f"{WARN} Claude did not give its sign-in address. Try again in a moment.")
        return False
    say("")
    for i, line in enumerate(CLAUDE_STEPS, 1):
        say(f"  {i}. {line}")
    say("", f"     {card['address']}", "", qr(card.get("qr") or []), "")
    while True:
        code = ask("The code Claude shows (or Enter to go back): ")
        if not code:
            api.call("plan", {"do": "cancel"})
            return False
        status, doc = api.call("plan", {"do": "code", "code": code}, timeout=150)
        if status == 200 and ((doc.get("plan") or {}).get("on_plan") or _wait_plan(api, "plan", 30)):
            plan = (doc.get("plan") or {}).get("plan") or ""
            say(f"{OK} Claude Code is signed in{' on ' + plan if plan else ''}. Rouh's agents run on your plan.")
            return True
        say(f"{WARN} {_problem(doc) if status != 200 else 'Claude did not take that code. Copy it again, all of it.'}")


def plan_codex(api: Api) -> bool:
    status, doc = api.call("codex", {"do": "start"}, timeout=90)
    if status != 200:
        say(f"{WARN} {_problem(doc)}")
        return False
    if not doc.get("code"):
        for _ in range(10):
            time.sleep(3)
            status, doc = api.call("codex")
            if doc.get("code") or doc.get("state") == "signed_in":
                break
    if doc.get("state") != "signed_in":
        if not doc.get("address"):
            say(f"{WARN} Codex did not give its sign-in code. Try again in a moment.")
            return False
        say("")
        for i, line in enumerate(CODEX_STEPS, 1):
            say(f"  {i}. {line}")
        say("", f"     {doc['address']}", "", qr(doc.get("qr") or []), "", f"  The code:  {BOLD}{doc.get('code', '')}{RESET}", "")
        say(f"{DIM}Waiting for you to approve it (up to 15 minutes; Ctrl-C to choose again)…{RESET}")
        try:
            if not _wait_plan(api, "codex", 900):
                say(f"{WARN} The code was not approved in time.")
                return False
        except KeyboardInterrupt:
            api.call("codex", {"do": "cancel"})
            say("")
            return False
    _, doc = api.call("codex")
    if not doc.get("on_plan"):
        say(f"{WARN} Codex is signed in with an API key, not a ChatGPT plan.")
        return False
    say(f"{OK} Codex is signed in{' on ' + doc['plan'] if doc.get('plan') else ''}. Rouh's agents run on your plan.")
    return True


def step_plan(api: Api, doc: dict) -> dict:
    heading(PLAN_TITLE)
    say(PLAN_LEDE, "")
    openai = (doc.get("keys") or {}).get("openai") == "ok" and (doc.get("keys") or {}).get("anthropic") != "ok"
    first = "chatgpt" if openai else "claude"
    while True:
        say(f"  {BOLD}1  Claude plan{RESET} (Pro or Max): Claude Code runs the agents" + (" (recommended)" if first == "claude" else ""))
        say(f"  {BOLD}2  ChatGPT plan{RESET} (Plus or Pro): Codex runs the agents" + (" (recommended)" if first == "chatgpt" else ""))
        say(f"  {DIM}3  {SKIP_LINK}{RESET}", "")
        got = choose(f"Connect a plan now? [{'1/2' if first == 'claude' else '2/1'}/3] ",
                     [("1", ""), ("2", ""), ("3", "")], "1" if first == "claude" else "2")
        if got == "1" and plan_claude(api):
            break
        if got == "2" and plan_codex(api):
            break
        if got == "3":
            say("", f"{WARN} {BOLD}Run the agents on your API key?{RESET}", SKIP_WARNING)
            if yes("Use my API key for agents?", default=False):
                api.call("plan", {"do": "skip"})
                say(f"{WARN} The agents run on your API key, billed by use. rouh status reminds you until a plan is connected.")
                break
        say("")
    return api.state()


def step_address(api: Api, doc: dict) -> None:
    """Connected: a name of the owner's own on rouh.page, beside the born one, if they want one."""
    if doc.get("kind") != "connected" or doc.get("chosen"):
        return
    if not yes("Choose your own address on rouh.page too, such as yourname.rouh.page?", default=False):
        return
    while True:
        want = ask("Your own address (letters, digits and dashes; Enter to skip): ").lower().removesuffix(".rouh.page")
        if not want:
            return
        status, got = api.call(f"name?name={want}")
        if status == 200 and got.get("free"):
            status, got = api.call("name", {"name": want})
            if status == 200:
                say(f"{OK} {want}.rouh.page is yours too. Your born address keeps working for good.")
                return
        say(f"{WARN} {got.get('said') or got.get('problem') or 'That name is taken. Try another.'}")


def finish(api: Api) -> None:
    status, doc = api.call("done", {})
    if status != 200 and doc.get("state", {}).get("step") != "done":
        raise Stop(_problem(doc))
    heading(READY_TITLE)
    state = api.state()
    who = (state.get("born") or {}).get("name") or ""
    say(f"Your Rouh{' ' + name(who) if who else ''} is set up, with its chats and its agents connected." if
        (state.get("plan") or {}).get("on_plan") or (state.get("codex") or {}).get("on_plan") else
        f"Your Rouh{' ' + name(who) if who else ''} is set up. Its agents run on your API key until you connect a plan.")
    open_rouh(api, wait=state.get("kind") == "connected")
    say("", "Rouh updates itself every night between 03:00 and 05:00, after a backup.",
        f"Any time: {BOLD}rouh status{RESET}, and {BOLD}rouh open{RESET} for a new sign-in link.")


def open_rouh(api: Api, *, wait: bool = False) -> None:
    """A one-time sign-in link, by the best way there is: the owner's own domain, the rouh.page
    address, or an SSH tunnel and a local link."""
    end = time.monotonic() + (150 if wait else 0)
    while True:
        status, doc = api.call("open", {})
        if status != 200:
            raise Stop(_problem(doc))
        if doc.get("where") in ("domain", "relay") or time.monotonic() >= end:
            break
        if wait:
            say(f"{DIM}Waiting for your address to answer from the internet…{RESET}")
            wait = False
        time.sleep(5)
    if doc.get("where") in ("domain", "relay"):
        minutes = int(doc.get("seconds") or 600) // 60
        say("", f"Open Rouh, on any computer or phone (it signs you in once, for {minutes} minutes):", "",
            f"    {BOLD}{doc['url']}{RESET}", "", qr(doc.get("qr") or []), "",
            f"{DIM}Your Rouh's address: {doc.get('address', '')}. rouh open makes a new link.{RESET}")
        return
    p, user = port(), user_name()
    pub, mine = public_ip(), local_ip()
    there = pub if pub and pub == mine else (mine or pub or "this-server")
    say("", "Open Rouh from your own computer: first, in a terminal there, run", "",
        f"    {BOLD}ssh -L {p}:127.0.0.1:{p} {user}@{there}{RESET}", "")
    if pub and mine and pub != mine:
        say(f"{DIM}  (From the internet the address may be {pub}; on the same network, {mine}.){RESET}", "")
    say("and keep it open. Then open this address there (it signs you in once):", "",
        f"    {BOLD}{'http://127.0.0.1:' + p + doc.get('local', '/')}{RESET}", "",
        f"{DIM}On your phone: give Rouh a domain of your own (rouh domain rouh.example.com). With Tailscale "
        f"(tailscale.com) on this server and your laptop, the tunnel works from anywhere.{RESET}")


def run_wizard() -> int:
    if not can_ask():
        say("Setup asks questions, and there is no terminal here to answer them in.",
            "Run it yourself, over SSH:  rouh setup")
        return 2
    st = code_status()
    if st.get("owner") and st.get("setup_done"):
        api = Api(setup_code())
        state = api.state()
        if state.get("step") == "done":
            say(f"{OK} This Rouh is set up already.")
            open_rouh(api)
            return 0
    code = setup_code(renew=True)
    api = Api(code)
    doc = api.state()
    say(f"{DIM}Setting up your Rouh. Ctrl-C stops; rouh setup carries on where you left off.{RESET}")
    kind = None
    for _ in range(20):
        step = doc.get("step")
        if step == "you":
            kind = kind or step_kind()
            doc = step_you(api, kind)
        elif step == "kind":
            kind = step_kind()
            _, doc = api.call("kind", {"kind": kind})
        elif step == "email":
            doc = step_email(api, doc)
        elif step == "born":
            doc = step_born(api, doc)
        elif step == "brain":
            doc = step_brain(api, doc)
        elif step == "plan":
            doc = step_plan(api, doc)
        elif step in ("ready", "done"):
            step_address(api, doc)
            finish(api)
            return 0
        else:
            raise Stop(f"Rouh is at a step this terminal does not know ({step!r}). Update Rouh: rouh update")
    raise Stop("Setup went round without finishing. Run rouh setup again.")
