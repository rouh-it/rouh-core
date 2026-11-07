"""A real sign-in, for a test that has to get past the gate.

Every address Rouh serves is behind a Django account (`rouh/accounts.py`), so
a test that asks for one has to be somebody. There is no way round that and
there is deliberately no switch to turn it off: an open mode that only the tests
use is a mode nobody tests, and it is one environment variable away from being
on in production.

So the tests do what the person does. This makes an account in whatever
throwaway database the test is pointed at and hands back the value of the cookie
a browser would be holding.
"""
from __future__ import annotations

#: The account every test signs in as, unless it wants its own.
USERNAME = "tester"
PASSWORD = "a-password-only-the-tests-use"


def an_account(server=None, username: str = USERNAME, password: str = PASSWORD) -> int:
    """Make the account if it is not there yet, and hand back its id.

    `server` is not used any more: the accounts are Django's since 23 September
    2026 and are reached the same way from anywhere Django is set up. It is
    still taken so a caller written before then keeps working.
    """
    from rouh import accounts

    there = accounts.get_user(username)
    if there is not None:
        return int(there.pk)
    return int(accounts.add_user(username, password).pk)


def a_cookie(server=None, username: str = USERNAME, password: str = PASSWORD) -> str:
    """The value of `rouh_session` for a browser signed in as `username`.

    A real Django session, made the way `django.contrib.auth.login` makes one,
    for a test that talks to the server without going through the form.
    """
    from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
    from django.contrib.sessions.backends.db import SessionStore

    from rouh import accounts

    user_id = an_account(server, username, password)
    user = accounts.get_user(username)
    session = SessionStore()
    session[SESSION_KEY] = str(user_id)
    session[BACKEND_SESSION_KEY] = "rouh.accounts.CaseInsensitiveBackend"
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session.create()
    return session.session_key


def make_account_in(data_dir: str, env: dict[str, str] | None = None,
                    username: str = USERNAME, password: str = PASSWORD) -> None:
    """One account in a throwaway world, through the admin command.

    For a test that starts a real server in another process. It runs the same
    command a person runs on the server, which is the point: the command is
    exercised by every run of the suite rather than only by whoever remembers
    it exists. `env` has to name the world's database already
    (`rouh/testing/postgres.py`, `for_world`).
    """
    import os
    import subprocess
    import sys

    repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    made = subprocess.run(
        [sys.executable, "manage.py", "account", "add", username, "--password", password],
        cwd=repo, capture_output=True, text=True, timeout=120,
        env={**(env or os.environ), "ROUH_DATA_DIR": str(data_dir)},
    )
    if made.returncode != 0:
        raise RuntimeError(f"the account could not be made:\n{made.stdout}\n{made.stderr}")


def sign_in_in_the_browser(page, base_url: str, username: str = USERNAME,
                           password: str = PASSWORD):
    """Type the username and the password into the real form and press the
    button, which is the only way into any of this."""
    page.goto(base_url.rstrip("/") + "/login", wait_until="domcontentloaded")
    # One box first (since 4 November 2026, `rouh/web/auth.py`): a username, not an email, goes
    # straight on to the password.
    page.fill("#email", username)
    page.click("#continueBtn")
    page.wait_for_selector("input[name=password]")
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_selector("#input", timeout=30_000)
    return page


def sign_in_over_http(base_url: str, username: str = USERNAME,
                      password: str = PASSWORD) -> str:
    """Post the sign-in form to a server running in another process and hand
    back the value of the cookie it set.

    For a test that talks to the server without a browser and still has to be
    somebody: the raw-socket requests that check what is served under
    /workspace/, for instance.
    """
    import http.cookies
    import urllib.error
    import urllib.parse
    import urllib.request

    import re

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **k):
            return None

    # The form first, as a browser would: Django will not take a sign-in that
    # does not carry the token the form was given, with the cookie it came in.
    base = base_url.rstrip("/")
    form = urllib.request.urlopen(base + "/login", timeout=30)
    page = form.read().decode("utf-8", "replace")
    token = (re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page) or [None, ""])[1]
    jar = http.cookies.SimpleCookie()
    for raw in form.headers.get_all("set-cookie") or []:
        jar.load(raw)
    cookie = "; ".join(f"{k}={v.value}" for k, v in jar.items())
    body = urllib.parse.urlencode({"username": username, "password": password,
                                   "csrfmiddlewaretoken": token}).encode()
    ask = urllib.request.Request(base + "/login", data=body, method="POST",
                                 headers={"Cookie": cookie, "Referer": base + "/login",
                                          "Origin": base})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        answer = opener.open(ask, timeout=30)
    except urllib.error.HTTPError as exc:          # 303 is the success here
        answer = exc
    for raw in answer.headers.get_all("set-cookie") or []:
        jar = http.cookies.SimpleCookie()
        jar.load(raw)
        if "rouh_session" in jar:
            return jar["rouh_session"].value
    raise RuntimeError(f"the sign-in was refused: {answer.status}")
