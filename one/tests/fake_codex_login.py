"""A stand-in for Codex's sign-in commands, so the sign-in page can be driven to the end offline.

``fake_codex.py`` hands ``login``, ``logout`` and ``exec`` here. They print what codex-cli
0.163.0 was watched printing on 6 November 2026, colours and all, and keep their sign-in in
``$CODEX_HOME/auth.json`` the way the real one does, with an id token whose claims carry an
email and a plan, so the page can say whose account it is. Nothing reaches the network.

``login --device-auth`` waits for its approval, which a person driving the page gives by
making a file in Codex's folder, the way OpenAI's page would answer the real one:

    touch "$CODEX_HOME/fake-approve"     signed in as alex@example.test, on ChatGPT Plus
    touch "$CODEX_HOME/fake-refuse"      Codex's own error for a code that was not approved

Only the standard library.
"""
import base64
import json
import os
import random
import string
import sys
import time

GREY, BLUE, END = "\x1b[90m", "\x1b[94m", "\x1b[0m"


def home():
    return os.environ.get("CODEX_HOME") or os.path.join(os.path.expanduser("~"), ".codex")


def auth():
    return os.path.join(home(), "auth.json")


def _b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def device():
    os.makedirs(home(), exist_ok=True)
    pick = lambda n: "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))
    code = pick(4) + "-" + pick(5)
    sys.stdout.write(
        "\nWelcome to Codex [v%s0.163.0%s]\n%sOpenAI's command-line coding agent%s\n\n"
        "Follow these steps to sign in with ChatGPT using device code authorization:\n\n"
        "1. Open this link in your browser and sign in to your account\n   %shttps://auth.openai.com/codex/device%s\n\n"
        "2. Enter this one-time code %s(expires in 15 minutes)%s\n   %s%s%s\n\n"
        "%sContinue only if you started this login in Codex. If a website or another person gave you this code, cancel.%s\n\n"
        % (GREY, END, GREY, END, BLUE, END, GREY, END, BLUE, code, END, GREY, END))
    sys.stdout.flush()
    approve, refuse = os.path.join(home(), "fake-approve"), os.path.join(home(), "fake-refuse")
    end = time.time() + float(os.environ.get("FAKE_CODEX_LOGIN_SECONDS", "900"))
    while time.time() < end:
        if os.path.exists(refuse):
            os.unlink(refuse)
            sys.stdout.write("Error logging in with device code: device code exchange failed: the code was declined\n")
            return 1
        if os.path.exists(approve):
            os.unlink(approve)
            claims = {"email": "alex@example.test",
                      "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"}}
            token = _b64({"alg": "none"}) + "." + _b64(claims) + ".stand-in"
            with open(auth(), "w") as fh:
                json.dump({"OPENAI_API_KEY": None, "tokens": {"id_token": token, "access_token": "stand-in",
                                                               "refresh_token": "stand-in"}}, fh)
            os.chmod(auth(), 0o644)  # looser than the real one, so the page's own 600 is seen
            sys.stdout.write("Successfully logged in\n")
            return 0
        time.sleep(0.3)
    sys.stdout.write("Error logging in with device code: device code expired\n")
    return 1


def main(args):
    if args[:1] == ["logout"]:
        if os.path.exists(auth()):
            os.unlink(auth())
            print("Successfully logged out")
            return 0
        print("Not logged in")
        return 0
    if args[:2] == ["login", "status"]:
        if os.path.exists(auth()):
            print("Logged in using ChatGPT")
            return 0
        print("Not logged in", file=sys.stderr)
        return 1
    if args[:1] == ["login"] and "--device-auth" in args:
        return device()
    if args[:1] == ["exec"]:
        if not os.path.exists(auth()):
            print("ERROR: unexpected status 401 Unauthorized: Missing bearer or basic authentication", file=sys.stderr)
            return 1
        print("codex", file=sys.stderr)
        print("Codex works")
        return 0
    print("the stand-in knows only login, logout and exec", file=sys.stderr)
    return 2
