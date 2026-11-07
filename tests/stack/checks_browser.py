"""CONTAINERS.md: the live browser, and everything else of the core's that reads a page in one.

In the containers the core runs no browser beside its keys. Its browsers are connections to the
browser container (deploy/stack/compose.yml, guard/bin/rouh-browser-server), whose only way out
is the key proxy. The website it opens here is the stand-in shop (rouh/testing/fake_shop.py),
on the stand-ins' private network, which the stack test's settings list for the key proxy as the
owner lists a server of their own (ROUH_KEYPROXY_ALLOW).
"""
from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import shlex
from urllib.parse import urlsplit

from smoke import LIMIT, Failed, Stack, check, expect

SHOP = os.environ.get("STACK_SHOP_URL", "http://shop.stack.test:9017")
SHOP_PORT = 9017
#: Where the page the PDF is made of is put, in the core's workspace.
PRINT_FOLDER = "stack-test-print"

#: The checks of this file that take longer than smoke.CHECK_LIMIT: each is several turns.
LIMIT.update({"browser.handoff": 540, "signups": 480, "browser.live": 420})


def _open_shop(s: Stack) -> str:
    """The browser tool opens the shop's front page; what the tool handed back."""
    got = s.tool("browser", {"action": "open", "url": SHOP + "/"}, limit=180)
    expect("Stack test shop" in got and "Press here" in got,
           f"the browser did not open the stand-in website: {got[:600]}")
    return got


def _tab(s: Stack) -> Stack:
    """A second tab of the person's, in the stack test's chat, kept open while the check uses
    it: the one that watches the Live browser and takes it over. `Stack.say` opens and closes
    a socket of its own for every message, so this one is never handed to it."""
    tab = Stack(s.url, "true", s.out)
    tab.cookie, tab.chat = s.cookie, s.chat
    tab.socket()
    return tab


def _browser_said(m: dict, **want) -> bool:
    return m.get("type") == "browser" and all(m.get(k) == v for k, v in want.items())


@check("browser.live")
def browser_live(s: Stack) -> None:
    """Rouh opens a page in the browser container, the page's own screen reaches the person's
    tab as they watch it, and the browser has nothing of anybody's and no way out but the key
    proxy, which keeps it off private addresses."""
    _open_shop(s)
    tab = _tab(s)
    try:
        tab.ws.send(json.dumps({"type": "browser_watch", "on": True, "w": 1024, "h": 720}))
        frame = tab.wait_for(lambda m: m.get("type") == "browser_frame" and m.get("data"), 60)
        tab.ws.send(json.dumps({"type": "browser_watch", "on": False}))
    finally:
        tab.ws.close()
    picture = base64.b64decode(frame["data"])
    expect(picture[:3] == b"\xff\xd8\xff" and len(picture) > 2000,
           f"the screen that came was not a picture of the page ({len(picture)} bytes)")
    expect(frame.get("width") and frame.get("height"), f"the screen had no size: {frame.get('width')}x{frame.get('height')}")

    # Its own walls: not root, no key, no database, and no way out but the key proxy.
    if s.compose and s.compose[0] != "true":
        r = s.run("browser", "id -u; env | grep -ciE 'not-a-real-one|^(POSTGRES|ROUH_DB)_PASSWORD=|^[a-z_]*api_key=' || true; "
                             "getent hosts postgres >/dev/null && echo database || echo no-database; "
                             "find /keys /data /code /extra /run/one -mindepth 1 2>/dev/null | wc -l; "
                             "env -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy curl -sS --max-time 8 "
                             "https://example.com -o /dev/null && echo reached || echo refused")
        lines = r.stdout.split()
        expect(len(lines) >= 5, f"the browser container could not be looked into: {(r.stdout + r.stderr)[-300:]}")
        expect(lines[0] != "0", "the browser container runs as root")
        expect(lines[1] == "0", "the browser container's environment holds a key or a password")
        expect(lines[2] == "no-database", "the browser container can reach the database")
        expect(lines[3] == "0", f"the browser container has files of somebody's: {r.stdout}")
        expect(lines[4] == "refused", "the browser container reached the internet past the key proxy")

        # A private address, through the browser's way out: refused, and said so.
        got = s.tool("browser", {"action": "open", "url": "https://standins:9001/"}, limit=120)
        expect("way out did not take it" in got or "not on the public internet" in got,
               f"a private address in the browser was not refused as one: {got[:400]}")


@check("browser.handoff")
def browser_handoff(s: Stack) -> None:
    """The person takes the browser over, clicks on the page where its button is, and hands
    it back: Rouh is held off meanwhile, is told, and sees the page as the click left it."""
    _open_shop(s)
    tab = _tab(s)
    try:
        tab.ws.send(json.dumps({"type": "browser_take"}))
        tab.wait_for(lambda m: _browser_said(m, control="person"), 30)
        got = s.tool("browser", {"action": "look"}, limit=120)
        expect("The person has the browser now" in got,
               f"Rouh was not held off while the person had the browser: {got[:400]}")
        # The button fills the top left of the page (fake_shop.FRONT).
        tab.ws.send(json.dumps({"type": "browser_input", "kind": "click", "x": 200, "y": 100}))
        # A moment, as a person takes, so the turn that looked is over before the hand-back is told.
        with contextlib.suppress(Failed):
            tab.wait_for(lambda m: False, 6)
        tab.ws.send(json.dumps({"type": "browser_give"}))
        tab.wait_for(lambda m: _browser_said(m, control="rouh"), 30)
        # Rouh hears it in the chat the errand belongs to, in a turn of its own: the stand-in
        # model's search starts with the note's first words, and the note is kept in the chat.
        tab.wait_for(lambda m: "handed it back" in json.dumps(m), 120)
        with contextlib.suppress(Failed):
            tab.wait_for(lambda m: m.get("type") == "assistant_done", 120)
    finally:
        tab.ws.close()
    if s.compose and s.compose[0] != "true":
        note = s.manage("from rouh.models.memory import TranscriptMessage as M\n"
                        "m = M.objects.filter(note=True, content__contains='handed it back').order_by('-id').first()\n"
                        "print(m.content if m else 'none')")
        expect("clicked once" in note, f"Rouh was not told the person clicked: {note[-400:]}")
    got = s.tool("browser", {"action": "look"}, limit=120)
    expect("Pressed by the person" in got, f"the person's click did not reach the page: {got[:500]}")


@check("browser.fallback")
def browser_fallback(s: Stack) -> None:
    """A page web_fetch is turned away from is read in the browser container instead: the
    stand-in shop's wall answers Python's fetcher 403 and a browser its page."""
    text, seen = s.say(f"What does {SHOP}/wall say?", 240)
    second = [m for m in seen if m.get("type") == "tool_end" and m.get("name") == "browser_fetch"]
    expect(second, f"the failed fetch was not tried again in a browser: {text[:400]}")
    summary = str(second[-1].get("summary") or "")
    expect(summary.startswith("read in a browser instead"), f"the browser's read: {summary[:400]}")
    expect("hidden sentence" in text or "Behind the wall" in text or "Behind the wall" in summary,
           f"what the browser read did not reach the answer: {text[:400]}")


@check("signups")
def signups(s: Stack) -> None:
    """A sign-up the person asks for in their own words: authorized, the form filled in the
    browser container with the password they gave (which the model never passes), and sent."""
    password = "Stack-Signup-Pass-42"
    host = urlsplit(SHOP).hostname
    words = f"sign me up for Stackshop at {host}"
    authorize = {"action": "authorize_signup", "service": "stackshop", "site": host,
                 "email": "alex@example.com", "words": words}
    text, _ = s.say(f"Please {words} with alex@example.com, and the password you should use to setup "
                    f"the account is: {password} (will change it later)\n"
                    f"TOOL browser {json.dumps(authorize)}", 180)
    expect("Authorized" in text, f"the sign-up was not authorized: {text[:500]}")
    page = s.tool("browser", {"action": "open", "url": SHOP + "/signup"}, limit=120)

    def ref(kind: str, name: str) -> str:
        # From the page as the last action left it: a ref is the outline's, read afresh each time.
        found = re.search(rf'{kind} "{name}"(?: \[[a-z]+\])* \[ref=([a-z0-9]+)\]', page)
        expect(found, f"the sign-up page has no {kind} {name!r}: {page[:600]}")
        return found.group(1)

    page = s.tool("browser", {"action": "type", "ref": ref("textbox", "Email"), "text": "alex@example.com"})
    expect("refused" not in page.lower(), f"typing the email: {page[:300]}")
    page = s.tool("browser", {"action": "fill_password", "ref": ref("textbox", "Password")})
    expect(password not in page and not page.startswith("Not"), f"fill_password: {page[:400]}")
    page = s.tool("browser", {"action": "click", "ref": ref("button", "Create account")})
    expect("Welcome aboard" in page, f"the registration was not sent: {page[:400]}")
    seen = s.standin(SHOP_PORT, "/_signups")
    made = (seen or {}).get("signups") if isinstance(seen, dict) else None
    expect(made and made[-1].get("email") == "alex@example.com" and made[-1].get("password") == password,
           f"the shop did not get the account the person asked for: {json.dumps(seen)[:300]}")


@check("tool.print-page")
def print_page(s: Stack) -> None:
    """A page of the workspace with a picture beside it, made a PDF in the browser container:
    the page and its picture are handed to the browser by the core, and the PDF is kept beside
    the page."""
    make = (
        "import os, struct, zlib\n"
        "root = os.path.join(os.environ['ROUH_WORKSPACE'], " + repr(PRINT_FOLDER) + ")\n"
        "os.makedirs(root, exist_ok=True)\n"
        "def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))\n"
        "raw = b''.join(b'\\x00' + b'\\xcc\\x33\\x33' * 40 for _ in range(30))\n"
        "png = (b'\\x89PNG\\r\\n\\x1a\\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 40, 30, 8, 2, 0, 0, 0))\n"
        "       + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))\n"
        "open(os.path.join(root, 'picture.png'), 'wb').write(png)\n"
        "open(os.path.join(root, 'index.html'), 'w').write('<!doctype html><title>Stack test printable page</title>'\n"
        "    '<h1>Stack test printable page</h1>' + '<p>A paragraph long enough to be taken out of its layout. ' * 8\n"
        "    + '</p><img src=\"picture.png\" alt=\"A red box\"><p>The end.</p>')\n"
    )
    r = s.run("core", "python -c " + shlex.quote(make), user="10001")
    expect(r.returncode == 0, f"the page could not be put in the workspace: {r.stderr[-300:]}")
    got = s.tool("print_page", {"page": PRINT_FOLDER}, limit=180)
    expect("The PDF is made" in got, f"print_page: {got[:400]}")
    r = s.run("core", "cd \"$ROUH_WORKSPACE\"/" + PRINT_FOLDER + " && python -c " + shlex.quote(
        "import glob, re; pdf = open(sorted(glob.glob('*.pdf'))[-1], 'rb').read(); "
        "print(pdf[:5].decode(), bool(re.search(rb'/Subtype\\s*/Image\\s*/Width 40\\s*/Height 30', pdf)))"))
    expect(r.stdout.split()[:1] == ["%PDF-"], f"no PDF beside the page: {(r.stdout + r.stderr)[-300:]}")
    expect("True" in r.stdout, f"the page's picture is not in the PDF: {r.stdout[-200:]}")

