"""CONTAINERS.md: Telegram both ways, Rouh's own letters, and a run's note to the phone.

The stand-ins (tests/stack/standins.py) are Telegram's Bot API on 9014 and Brevo on 9005; the
settings file of the stack test gives Rouh their keys the way an installer does
(ROUH_TELEGRAM_BOT_TOKEN, ROUH_TELEGRAM_CHAT_ID, ROUH_BREVO_API_KEY).
"""
from __future__ import annotations

import json
import time

from smoke import Failed, Stack, check, expect

TELEGRAM, BREVO = 9014, 9005
CHAT = 4242


def _phone(s: Stack) -> list[dict]:
    got = s.standin(TELEGRAM, f"/_chat?chat={CHAT}")
    return got.get("messages", []) if isinstance(got, dict) else []


def _wait_phone(s: Stack, words: str, limit: float = 90) -> dict:
    end = time.time() + limit
    while time.time() < end:
        for m in _phone(s):
            if words.lower() in json.dumps(m).lower():
                return m
        time.sleep(3)
    raise Failed(f"nothing reached the phone with {words!r}; it shows: {json.dumps(_phone(s))[-600:]}")


@check("telegram.send", "install.telegram")
def telegram_send(s: Stack) -> None:
    got = s.tool("send_telegram", {"text": "Hello from the stack test", "straight_to_phone": True})
    expect("not set up" not in got.lower(), f"send_telegram: {got[:300]}")
    _wait_phone(s, "Hello from the stack test")


@check("install.telegram-page")
def telegram_from_the_page(s: Stack) -> None:
    """A new owner sets Rouh's bot on the page, not in stack.env (`rouh/telegram_bot.py`): the core
    checks it with Telegram's stand-in, writes it itself, and uses it at once, with nothing restarted."""
    from checks_tools import post

    secret = "S" * 35
    token = "123456789:" + secret
    code, got = post(s, "/api/settings/telegram-bot", {"token": token, "chat": str(CHAT)})
    try:
        expect(code == 200 and (got.get("bot") or {}).get("source") == "page",
               f"the page's save: {code} {json.dumps(got)[:400]}")
        expect(secret not in json.dumps(got), "the token came back in the page's answer")
        r = s.run("core", 'stat -c "%a" "$ROUH_TELEGRAM_FILE"')
        expect(r.stdout.strip() == "600", f"the bot's file in the core: {(r.stdout + r.stderr)[-300:]}")
        said = s.tool("send_telegram", {"text": "Sent with the bot set on the page", "straight_to_phone": True})
        expect("not set up" not in said.lower(), f"send_telegram: {said[:300]}")
        _wait_phone(s, "Sent with the bot set on the page")
        expect(secret not in s.logs("core", 2000), "the token is in the core's log")
    finally:
        code, got = post(s, "/api/settings/telegram-bot/remove")
    expect(code == 200 and (got.get("bot") or {}).get("source") == "settings_file",
           f"Remove did not give the settings file's bot back: {code} {json.dumps(got)[:300]}")


@check("telegram.chat")
def telegram_chat(s: Stack) -> None:
    """The owner writes to the bot; Rouh takes it as a turn of General and answers on the phone."""
    s.run("core", f"""python -c "import json,urllib.request; urllib.request.urlopen(urllib.request.Request(
'http://standins:{TELEGRAM}/_send', data=json.dumps({{'chat_id': {CHAT}, 'text': 'Written on the phone in the stack test'}}).encode(),
headers={{'content-type': 'application/json'}}), timeout=10)" """)
    _wait_phone(s, "Written on the phone in the stack test", 120)
    # The stand-in model's answer says back what it received.
    end = time.time() + 120
    while time.time() < end:
        if any("i received" in json.dumps(m).lower() for m in _phone(s)):
            return
        time.sleep(3)
    raise Failed(f"Rouh did not answer on the phone: {json.dumps(_phone(s))[-600:]}")


@check("one.phone-note")
def one_phone_note(s: Stack) -> None:
    """The one program's note to the phone, from the worker, sent with Rouh's own bot."""
    r = s.py("worker", f"""
import asyncio
from one.phone import Phone
print(asyncio.run(Phone("/nonexistent/telegram.json").send("A run is waiting for you in the stack test",
                                                     buttons=[("Open", "{s.url}/one/")])))
""")
    expect("True" in r.stdout, f"the one program's phone note: {(r.stdout + r.stderr)[-400:]}")
    _wait_phone(s, "A run is waiting for you in the stack test")


@check("brevo.letters", "install.brevo")
def brevo_letters(s: Stack) -> None:
    """A guest's forgotten password: the page sends them a letter from Rouh's own address, through
    Brevo's stand-in (`password_reset._send_to_guest`; the owner's own reset goes through their
    Google account). The guest is an account made with a password, marked a guest, as an
    invitation makes one.)"""
    from playwright.sync_api import sync_playwright

    s.manage("from rouh import accounts\nfrom rouh.models import User\n"
             "u = accounts.get_user('sam') or accounts.add_user('sam', 'a-password-the-stack-test-sets')\n"
             "User.objects.filter(pk=u.pk).update(email='sam@example.com', is_guest=True)\nprint('made')")

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(s.url + "/login/forgot")
        pg.fill("input[name=who]", "sam@example.com")
        pg.click("button[type=submit]")
        pg.wait_for_load_state()
        b.close()
    end = time.time() + 60
    while time.time() < end:
        letters = s.standin(BREVO, "/letters")
        if "sam@example.com" in json.dumps(letters):
            return
        time.sleep(3)
    raise Failed(f"no letter reached Brevo's stand-in: {json.dumps(letters)[-400:]}")
