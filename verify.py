#!/usr/bin/env python3
"""Prove the live Rouh works, from the outside, the way a browser would.

    ./verify.py                      against this installation's public address (ROUH_PUBLIC_URL)
    ./verify.py --base http://...    against another one, such as a local one
    ./verify.py --quick              skip the slow speech tests

Every check goes through the public address, so it exercises Cloudflare, nginx,
the certificate, the sign-in, the websocket and the model, in that order.
Nothing here is mocked. It costs a few cents of tokens and a few hundred
ElevenLabs credits to run.

It can never hang. Every section of checks has a time limit, every socket is
closed within a few seconds (``close_quickly``), and the whole run has a limit
too. A section that runs out of time is reported as a failed check with the
reason, the run goes on to the next section, and the summary is always printed.
Live on 12 September it once sat for over twelve minutes inside websockets' own
close(), which waits with no limit for a connection that cannot finish closing.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass

import httpx
import websockets

from rouh import attachments
from rouh.testing.session import close_quickly

#: The installation's own public address, the same setting the service reads
#: (`rouh/config.py`, SETUP.md). Never another installation's: with none set and
#: no --base, there is nothing to check.
BASE = os.environ.get("ROUH_PUBLIC_URL", "").strip().rstrip("/")
#: The ssh host the service runs on, for the one check that asks systemd
#: itself. Blank skips that check.
SSH_HOST = os.environ.get("ROUH_VERIFY_SSH", "").strip()


def _login_file() -> str:
    """Where this laptop keeps the account it checks the live site with.

    Two lines: the username, then the password. Nothing in this repository, and
    nothing on the command line, so it is never in a shell history and never in
    a commit. `ROUH_USERNAME` and `ROUH_PASSWORD` do instead where there is
    no file, which is how this runs on a server.
    """
    for path in (os.environ.get("ROUH_LOGIN_FILE", ""),
                 os.path.expanduser("~/.config/rouh/login")):
        if path and os.path.isfile(path):
            return path
    return os.path.expanduser("~/.config/rouh/login")


LOGIN_FILE = _login_file()


def _account() -> tuple[str, str]:
    """The username and the password to sign in with, or two empty strings."""
    name = os.environ.get("ROUH_USERNAME", "").strip()
    word = os.environ.get("ROUH_PASSWORD", "").strip()
    if name and word:
        return name, word
    if os.path.isfile(LOGIN_FILE):
        with open(LOGIN_FILE) as fh:
            lines = [line.strip() for line in fh if line.strip()]
        if len(lines) >= 2:
            return lines[0], lines[1]
    return "", ""

#: The whole run, at most. A normal run takes five or six minutes; this only
#: catches something no section limit did.
RUN_LIMIT = 25 * 60

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
SKIP = "\033[33m-\033[0m"

results: list[tuple[bool | None, str, str]] = []


def check(ok: bool | None, name: str, detail: str = "") -> None:
    mark = PASS if ok else (SKIP if ok is None else FAIL)
    print(f"  {mark} {name}" + (f"  \033[2m{detail}\033[0m" if detail else ""))
    results.append((ok, name, detail))


def section(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m")


@dataclass
class Run:
    """What one section hands the next."""

    base: str
    ws_base: str
    username: str
    password: str
    quick: bool
    cookie: str | None = None
    token: str | None = None

    @property
    def headers(self) -> dict:
        return {"Cookie": f"rouh_session={self.cookie}"}


async def _section(title: str, body, limit: float, heading: bool = True) -> None:
    """One section of checks, under a time limit.

    A section that runs out of time, or breaks, is a failed check saying so,
    and the run goes on to the next section.
    """
    if heading:
        section(title)
    try:
        await asyncio.wait_for(body(), limit)
    except (asyncio.TimeoutError, TimeoutError) as exc:
        # The section's own limit, or a limit inside it that named itself.
        check(False, f"{title}: finished in time", str(exc) or f"ran out of time after {limit:g}s")
    except Exception as exc:
        check(False, f"{title}: ran to the end", f"{type(exc).__name__}: {str(exc)[:80]}")


#: What a connection dropped on its way open raises: the network errors
#: websockets itself treats as worth another try. Not InvalidStatus - a refusal
#: is the server's answer, and one check wants exactly that answer.
_DROPPED_OPENING = (EOFError, OSError, asyncio.TimeoutError)

#: How long to wait before the one retry.
RETRY_PAUSE = 2.0


@contextlib.asynccontextmanager
async def _socket(url: str, **kwargs):
    """A websocket that is always closed within a few seconds (see close_quickly).

    Opening it gets one more try, after a short pause, when the connection was
    dropped on its way open. Live on 12 September a new conversation failed
    with "EOFError: connection closed while reading HTTP status line" and the
    server logged nothing: the connection was lost between here and it. Only
    the opening is retried, never a check, and a second failure is raised.
    """
    ws = None
    for attempt in (1, 2):
        try:
            ws = await websockets.connect(url, **kwargs)
            break
        except _DROPPED_OPENING:
            if attempt == 2:
                raise
            await asyncio.sleep(RETRY_PAUSE)
    try:
        yield ws
    finally:
        await close_quickly(ws)


async def _command(argv: list[str], limit: float) -> str:
    """Run a program and return what it printed, killing it if it overruns.

    Not subprocess.run: that blocks the event loop, and with it every other
    time limit in this file.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), limit)
    except BaseException as exc:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(proc.wait(), 5)
        if isinstance(exc, TimeoutError):
            # Named here, or the section reports its own limit instead of this
            # one: a 40 s limit on ssh was reported as "after 60s".
            raise TimeoutError(f"{argv[0]} ran out of time after {limit:g}s") from None
        raise
    return out.decode(errors="replace")


async def main(args) -> None:
    base = args.base.rstrip("/")
    username, password = _account()
    if not (username and password):
        print(f"No account to sign in with. Put the username and the password on two"
              f" lines in {LOGIN_FILE}, or set ROUH_USERNAME and ROUH_PASSWORD.",
              file=sys.stderr)
        raise SystemExit(2)
    run = Run(base=base, ws_base=base.replace("https://", "wss://").replace("http://", "ws://"),
              username=username, password=password, quick=args.quick)

    await _section("Reachable, and with a certificate a browser will accept",
                   lambda: reachable(run), 120)
    if not run.cookie:
        return
    await _section("An unauthenticated socket is refused", lambda: unauthorised(run), 30)
    await _section("Attaching a file", lambda: attaching(run), 60)
    await the_socket(run)
    # A new conversation starts from the store alone, with none of the words of
    # the memory checks, so it is the one place the token could still come from.
    await _section("Memory, in a new conversation", lambda: fresh_conversation(run), 180,
                   heading=False)
    if run.base == BASE and SSH_HOST:
        # ssh to the server sometimes takes about 20 s on its own; with 40 s for
        # ssh inside 60 s for the section, one live run in two failed here.
        await _section("The service itself", the_service, 120)


# ---------------------------------------------------------------- reachable
async def reachable(run: Run) -> None:
    async with httpx.AsyncClient(follow_redirects=False, timeout=25) as c:
        try:
            r = await c.get(f"{run.base}/healthz")
            health = r.json()
            check(r.status_code == 200, "health endpoint answers", f"HTTP {r.status_code}")
            check(health.get("ok") is True, "reports itself healthy")
            check(
                not health.get("missing_config"),
                "no missing settings",
                ", ".join(health.get("missing_config") or []) or "all set",
            )
            check(health.get("voice_ready") is True, "text to speech configured")
            check(health.get("ears_ready") is True, "speech to text configured")
            check(
                health.get("delegation") is True,
                "background workers available",
                "" if health.get("delegation") else "crew module not loaded",
            )
            check(
                "show_on_screen" in (health.get("tools") or []),
                "screen tool registered",
                f"{len(health.get('tools') or [])} tools",
            )
            # The whole point of the version string: after a deploy, this line
            # prints which commit is answering, so "did that go out" stops
            # being a guess.
            git = health.get("git") or {}
            check(
                bool(git.get("short_sha")) and git.get("short_sha") != "unknown",
                "the live site says which build it is running",
                git.get("human_readable") or "no version reported",
            )
        except Exception as exc:
            check(False, "health endpoint answers", str(exc)[:90])
            return

        # The certificate matters more than it looks: without a trusted one the
        # browser refuses the microphone and the whole thing is a text box.
        if run.base.startswith("https://"):
            try:
                async with httpx.AsyncClient(verify=True, timeout=20) as strict:
                    await strict.get(f"{run.base}/healthz")
                check(True, "certificate is trusted without an override")
            except Exception as exc:
                check(False, "certificate is trusted without an override", str(exc)[:90])

        # --------------------------------------------------------------- sign-in
        section("The sign-in")
        r = await c.get(f"{run.base}/", headers={"accept": "text/html"})
        gated = r.status_code == 303 and "/login" in (r.headers.get("location") or "")
        check(gated, "the page is not served without a cookie", f"HTTP {r.status_code}")
        # The form first, as a browser does: Django takes a sign-in only with
        # the token the form was given, from this site's own page.
        form = await c.get(f"{run.base}/login")
        found = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form.text)
        token = found.group(1) if found else ""
        check(bool(token), "the sign-in form carries its CSRF token")
        from_the_form = {"Referer": f"{run.base}/login", "Origin": run.base}
        bad = await c.post(f"{run.base}/login", headers=from_the_form,
                           data={"username": run.username, "password": "definitely-not-it",
                                 "csrfmiddlewaretoken": token})
        check(bad.status_code == 401 and "do not match" in bad.text,
              "a wrong password is refused", f"HTTP {bad.status_code}")
        good = await c.post(f"{run.base}/login", headers=from_the_form,
                            data={"username": run.username, "password": run.password,
                                  "csrfmiddlewaretoken": token})
        cookie = good.cookies.get("rouh_session")
        check(bool(cookie), "the right password starts a sign-in")
        if not cookie:
            return
        run.cookie = cookie
        set_on = next((h for h in good.headers.get_list("set-cookie")
                       if h.startswith("rouh_session=")), "")
        check("HttpOnly" in set_on and "Secure" in set_on and "Path=/" in set_on,
              "and the cookie is HttpOnly, Secure and on the whole site", set_on[:70])
        page = await c.get(f"{run.base}/", headers={"Cookie": f"rouh_session={cookie}"})
        check(page.status_code == 200 and "<" in page.text, "the page is served with the cookie")
        for asset in ("app.js", "app.css", "mic-worklet.js"):
            a = await c.get(f"{run.base}/static/{asset}")
            check(a.status_code == 200 and len(a.content) > 500, f"{asset} is served",
                  f"{len(a.content)} bytes")

        # The speech detector, and the two ways it silently fails to load.
        section("The speech detector's files")
        stamp = None
        page = await c.get(f"{run.base}/", headers={"Cookie": f"rouh_session={cookie}"})
        import re as _re
        m = _re.search(r"/a/([a-f0-9]+)/", page.text)
        stamp = m.group(1) if m else None
        check(bool(stamp), "the page carries a versioned asset path", stamp or "none found")
        if stamp:
            expected = {
                "vad.js": "javascript",
                "silero-vad.onnx": "octet-stream",
                # WebAssembly.instantiateStreaming refuses anything but this, and
                # the failure is a console warning nobody sees.
                "ort-wasm-simd-threaded.wasm": "application/wasm",
                "ort.min.mjs": "javascript",
            }
            for name, want in expected.items():
                r2 = await c.get(f"{run.base}/a/{stamp}/{name}")
                ok = r2.status_code == 200 and want in r2.headers.get("content-type", "")
                check(ok, f"{name} is served as {want}",
                      f"{r2.status_code} {r2.headers.get('content-type','?')} "
                      f"{len(r2.content)} bytes")
            vad = await c.get(f"{run.base}/a/{stamp}/vad.js")
            check("silero-vad.onnx" in vad.text and "ort.min.mjs" in vad.text,
                  "it points at the model and the runtime")


# ---------------------------------------------------------------- attachments
#: One real PNG, one pixel, so the signature check on the server has something
#: true to agree with.
ONE_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


async def attaching(run: Run) -> None:
    """A file goes up, comes back down, and a bad one is refused in words.

    This is checked against the live site because the failure it guards is a
    deployment one: nginx has its own body-size limit, and when that is smaller
    than the app's every attachment fails with an nginx error page that says
    nothing about Rouh. `client_max_body_size` in the rouh site has to be
    at least attachments.MAX_BYTES.
    """
    headers = {"Cookie": f"rouh_session={run.cookie}"}
    session = "verify" + uuid.uuid4().hex[:10]
    async with httpx.AsyncClient(follow_redirects=False, timeout=60) as c:
        up = await c.post(f"{run.base}/attachments/{session}", headers=headers,
                          files={"file": ("verify.png", ONE_PIXEL, "image/png")})
        ok = up.status_code == 200 and (up.json() or {}).get("kind") == "image"
        check(ok, "a picture can be attached", f"HTTP {up.status_code}")
        if not ok:
            return
        att = up.json()["id"]
        down = await c.get(f"{run.base}/attachments/{session}/{att}", headers=headers)
        check(down.status_code == 200 and down.content == ONE_PIXEL,
              "and comes back down byte for byte", f"HTTP {down.status_code}")
        check("private" in down.headers.get("cache-control", ""),
              "and no shared cache keeps a copy of it",
              down.headers.get("cache-control", "none"))

        # An uploaded page is stored and handed back as a download, never as a
        # page on this address: a script served here would be inside the
        # signed-in session.
        page_up = await c.post(f"{run.base}/attachments/{session}", headers=headers,
                               files={"file": ("page.html", b"<script>x()</script>",
                                               "text/html")})
        served = {}
        if page_up.status_code == 200:
            got = await c.get(f"{run.base}/attachments/{session}/{page_up.json()['id']}",
                              headers=headers)
            served = got.headers
        check(page_up.status_code == 200, "an html file can be attached",
              f"HTTP {page_up.status_code}")
        check("text/html" not in served.get("content-type", "text/html")
              and served.get("content-disposition", "").startswith("attachment"),
              "and comes back as a download rather than as a page",
              f"{served.get('content-type', 'none')} / "
              f"{served.get('content-disposition', 'none')}")

        bad = await c.post(f"{run.base}/attachments/{session}", headers=headers,
                           files={"file": ("setup.exe", b"\x00" * 64,
                                           "application/octet-stream")})
        said = (bad.json() or {}).get("error", "") if bad.status_code == 400 else ""
        check("cannot be attached" in said, "a program is refused in words",
              said[:70] or f"HTTP {bad.status_code}")

        # The limit the app promises has to survive whatever sits in front of
        # it. This is a megabyte under it, so the proxy is what it measures.
        big = b"%PDF-1.4" + b"\x00" * (attachments.MAX_BYTES - 1024 * 1024)
        heavy = await c.post(f"{run.base}/attachments/{session}", headers=headers,
                             files={"file": ("big.pdf", big, "application/pdf")})
        check(heavy.status_code == 200,
              f"and {attachments.human_size(len(big))} gets through the proxy",
              f"HTTP {heavy.status_code}")

        # The paperclip on the page is the way in, and it spent a long time
        # switched off saying so.
        page = await c.get(f"{run.base}/", headers=headers)
        clip = page.text[page.text.find('id="attachBtn"'):][:400]
        check("disabled" not in clip and "not built yet" not in clip,
              "the paperclip on the page is switched on")


# --------------------------------------------------------------- unauthorised
async def unauthorised(run: Run) -> None:
    """A socket with no sign-in behind it is taken and then closed with 4401.

    Closed rather than refused at the handshake on purpose: a refused handshake
    reaches the page as a plain failed connection and it sits there reconnecting
    for ever, where 4401 tells it to send the person to the sign-in page. So
    what is checked here is that nothing can be said on it, not that it was
    never accepted.
    """
    try:
        async with _socket(f"{run.ws_base}/ws", open_timeout=15) as ws:
            try:
                await asyncio.wait_for(ws.recv(), timeout=10)
                check(False, "socket without a cookie is closed", "it stayed open")
            except Exception:
                code = getattr(ws, "close_code", None)
                check(code == 4401, "socket without a cookie is closed with 4401",
                      f"closed with {code}")
    except Exception as exc:
        check(True, "socket without a cookie is closed", type(exc).__name__)


# ----------------------------------------------------------------- the socket
async def the_socket(run: Run) -> None:
    section("The websocket, through the proxy")
    t0 = time.monotonic()
    try:
        async with _socket(f"{run.ws_base}/ws", additional_headers=run.headers,
                           open_timeout=25) as ws:
            check(True, "socket opens through Cloudflare", f"{int((time.monotonic()-t0)*1000)}ms")
            await _section("The websocket, through the proxy", lambda: handshake(ws), 45,
                           heading=False)
            await _section("A settings change does not start a loop",
                           lambda: settings_loop(ws), 20)
            await _section("A typed turn", lambda: typed_turn(ws), 150)
            await _section("Putting something on the screen", lambda: the_screen(ws), 150)
            if not run.quick:
                await _section("Speaking", lambda: speaking(ws), 150)
                await _section("Interrupting it mid-sentence", lambda: interrupting(ws), 120)
            else:
                check(None, "speaking", "skipped")
                check(None, "interrupting", "skipped")
            await _section("Memory", lambda: memory(run, ws), 400)
    except Exception as exc:
        check(False, "socket opens through Cloudflare", f"{type(exc).__name__}: {str(exc)[:80]}")


async def handshake(ws) -> None:
    await ws.send(json.dumps({"type": "hello", "client": "verify"}))
    ready = await _wait_for(ws, "ready")
    session_id = ready.get("session_id")
    check(bool(session_id), "handshake returns a session")
    await ws.send(json.dumps({"type": "ping"}))
    check(bool(await _wait_for(ws, "pong", 10)), "keepalive answered")


async def settings_loop(ws) -> None:
    await ws.send(json.dumps({"type": "set_mode", "voice_reply": False}))
    seen = []
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.4)
        except asyncio.TimeoutError:
            continue
        if isinstance(raw, bytes):
            continue
        seen.append(json.loads(raw).get("type"))
    check("ready" not in seen, "it is not answered with a handshake",
          ">".join(seen) or "nothing else")
    check(len(seen) <= 3, "and it does not ping-pong", f"{len(seen)} messages in 3s")


# ------------------------------------------------------------- a text turn
async def typed_turn(ws) -> None:
    await ws.send(json.dumps({"type": "set_mode", "voice_reply": False}))
    check(bool(await _wait_for(ws, "mode", 10)), "a settings change is confirmed")
    turn = await _turn(ws, "In one short sentence, what are you?")
    check(len(turn["text"]) > 10, "the model answers", turn["text"][:60])
    check(turn["first_token"] < 12, "first word arrives promptly",
          f"{turn['first_token']:.2f}s")
    check("—" not in turn["text"], "no em dash in the reply")
    check(len(turn["text"]) < 400, "the answer is short enough to say aloud",
          f"{len(turn['text'])} chars")


# --------------------------------------------------------------- the screen
async def the_screen(ws) -> None:
    turn = await _turn(ws, "Show me a table of three European capitals and their country, "
                           "then say one short sentence about it.")
    check(turn["ui"] > 0, "a card was sent", f"{turn['ui']} card(s)")
    spec = turn["last_ui"] or {}
    blocks = [b.get("block") for b in (spec.get("blocks") or [])]
    check("table" in blocks, "the card contains a table", ", ".join(blocks))
    rows = next((b.get("rows") for b in spec.get("blocks", []) if b.get("block") == "table"), [])
    check(len(rows or []) >= 3, "the table has rows", f"{len(rows or [])} rows")
    check("show_on_screen" in turn["tools"], "the screen tool was used")


# ---------------------------------------------------------------- the voice
async def speaking(ws) -> None:
    await ws.send(json.dumps({"type": "set_mode", "voice_reply": True}))
    await _wait_for(ws, "mode", 10)
    turn = await _turn(ws, "Say good morning in one short sentence.", want_audio=True)
    check(turn["audio_bytes"] > 8000, "audio came back",
          f"{turn['audio_bytes']/2/24000:.2f}s of speech")
    check(turn["first_audio"] is not None and turn["first_audio"] < 15,
          "first sound arrives promptly",
          f"{turn['first_audio']:.2f}s" if turn["first_audio"] else "never")
    check(turn["states"][-1] == "idle", "the turn ends back at idle",
          ">".join(turn["states"]))


# ----------------------------------------------------------- interrupt
async def interrupting(ws, first_sound_limit: float = 30.0, speak_for: float = 1.5,
                       listen_after: float = 3.0, stop_limit: float = 10.0) -> None:
    # This check once reported 168,960 bytes - 3.5 seconds of speech -
    # arriving after the interrupt, and the server had stopped 7 ms
    # after it. Two faults in the check made the number:
    #
    # 1. It asked the next question while the previous reply was still
    #    arriving. Speech is sent at the pace it is spoken, so a reply
    #    keeps arriving well after its text is finished.
    # 2. It then slept for 3.5 seconds without reading the socket, so
    #    everything that arrived during the sleep - sent BEFORE the
    #    interrupt - was counted as arriving after it.
    #
    # So: wait for quiet, read while waiting, and allow the half second
    # of speech that can legitimately already be on its way.
    #
    # And interrupt only once it is speaking. A fixed 3.5 s after asking was
    # too early the day Rouh took 10.58 s to make its first sound: the
    # interrupt went out before any speech, and the check failed with 0.00 s.
    await _quiet(ws)
    await ws.send(json.dumps({"type": "text",
                              "text": "Count slowly from one to forty."}))
    spoken = 0
    started = None
    end = time.monotonic() + first_sound_limit
    while time.monotonic() < end:
        try:
            m = await asyncio.wait_for(ws.recv(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        if isinstance(m, bytes):
            spoken += len(m)
            if started is None:
                started = time.monotonic()
                end = started + speak_for
    await ws.send(json.dumps({"type": "interrupt"}))
    sent = time.monotonic()
    if started is None:
        check(False, "it was speaking when interrupted",
              f"no sound within {first_sound_limit:g}s of asking")
        return
    # The server says when its voice has stopped - audio_end - on the same
    # connection as the audio and in the order it sent them. Audio that
    # arrives before it left the server before the server acted: on its way,
    # or sent while the interrupt itself was still travelling to the server,
    # which on the live site took up to 3.9 s after a few seconds with nothing
    # sent from here (measured 12 September; never from a client on the server
    # itself). Audio after it is speech made after the stop, which is the fault
    # this looks for: live, the model's last words before it noticed the
    # interrupt were once spoken as a new sentence 110 ms after the voice stopped.
    on_its_way = after_stop = 0
    stopped = None
    end = sent + stop_limit
    while time.monotonic() < end:
        try:
            m = await asyncio.wait_for(ws.recv(), timeout=0.2)
        except asyncio.TimeoutError:
            continue
        if isinstance(m, bytes):
            if stopped is None:
                on_its_way += len(m)
            else:
                after_stop += len(m)
        elif stopped is None and json.loads(m).get("type") == "audio_end":
            stopped = time.monotonic()
            end = stopped + listen_after
    check(spoken > 0, "it was speaking when interrupted",
          f"{spoken / 48000:.2f}s of speech before the interrupt")
    check(stopped is not None, "it stops when interrupted",
          f"{(stopped - sent) * 1000:.0f} ms after the interrupt, with "
          f"{on_its_way / 48000:.2f}s of speech already on its way"
          if stopped is not None else f"no audio_end within {stop_limit:g}s")
    check(stopped is not None and after_stop == 0, "no audio is sent after it stops",
          f"{after_stop} bytes = {after_stop / 48000:.2f}s after it stopped")


# ----------------------------------------------------------------- memory
async def memory(run: Run, ws) -> None:
    await ws.send(json.dumps({"type": "set_mode", "voice_reply": False}))
    await _wait_for(ws, "mode", 10)
    token = f"verify-{int(time.time())}"
    run.token = token
    await _turn(ws, f"Remember that the verification token is {token}. Confirm briefly.")
    turn = await _turn(ws, "What is the verification token? Answer with just the token.")
    check(token in turn["text"], "a fact is stored and read back", turn["text"][:60])
    # And taken out again, with Rouh's own tool. Every run used to leave its
    # token in the store, and everything in the store goes into every prompt.
    gone = await _turn(ws, "Now forget the verification token, using the forget tool. "
                           "Confirm briefly.")
    said = gone["summaries"].get("forget", "")
    check(said == "Forgotten.", "it forgets the fact again",
          said or f"tools used: {', '.join(gone['tools']) or 'none'}")


async def fresh_conversation(run: Run) -> None:
    if not run.token:
        check(None, "and a new conversation no longer knows it", "skipped: no token was stored")
        return
    async with _socket(f"{run.ws_base}/ws", additional_headers=run.headers,
                       open_timeout=25) as ws:
        await ws.send(json.dumps({"type": "hello", "client": "verify"}))
        await _wait_for(ws, "ready")
        await ws.send(json.dumps({"type": "set_mode", "voice_reply": False}))
        await _wait_for(ws, "mode", 10)
        fresh = await _turn(ws, "Is there a verification token in your memory? "
                                "If there is, say it; if there is not, say none.")
        check(run.token not in fresh["text"], "and a new conversation no longer knows it",
              fresh["text"][:60])


# ------------------------------------------------------------------ the service
async def the_service() -> None:
    # BatchMode: a prompt for a password or a host key would wait for an answer
    # nobody is there to give.
    out = (await _command(["ssh", "-o", "BatchMode=yes", SSH_HOST,
                           "systemctl is-active rouh; systemctl is-enabled rouh"],
                          90)).split()
    check(out[:1] == ["active"], "the service is running")
    check(out[1:2] == ["enabled"], "it will come back after a reboot")


# ------------------------------------------------------------------- summary
def summary() -> int:
    failed = [r for r in results if r[0] is False]
    skipped = [r for r in results if r[0] is None]
    passed = [r for r in results if r[0] is True]
    print(f"\n\033[1m{len(passed)} passed, {len(failed)} failed"
          + (f", {len(skipped)} skipped" if skipped else "") + "\033[0m")
    for _, name, detail in failed:
        print(f"  {FAIL} {name}  {detail}")
    return 1 if failed else 0


async def run_all(args) -> int:
    """The whole run under RUN_LIMIT, and the summary however it ends."""
    try:
        await asyncio.wait_for(main(args), RUN_LIMIT)
    except (asyncio.TimeoutError, TimeoutError):
        check(False, "the whole run finished in time",
              f"ran out of time after {RUN_LIMIT / 60:g} minutes")
    except Exception as exc:
        check(False, "the run reached its end", f"{type(exc).__name__}: {str(exc)[:80]}")
    return summary()


async def _wait_for(ws, kind: str, timeout: float = 30) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            m = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.monotonic()))
        except asyncio.TimeoutError:
            return {}
        if isinstance(m, bytes):
            continue
        d = json.loads(m)
        if d.get("type") == kind:
            return d
    return {}


async def _quiet(ws, gap: float = 1.5, limit: float = 45.0) -> None:
    """Read and discard until nothing has arrived for `gap` seconds.

    A reply's speech keeps arriving after its text is done, at the pace it is
    spoken. A check that starts before that has stopped measures the last
    check's reply as well as its own.
    """
    end = time.monotonic() + limit
    while time.monotonic() < end:
        try:
            await asyncio.wait_for(ws.recv(), timeout=gap)
        except asyncio.TimeoutError:
            return


async def _turn(ws, prompt: str, want_audio: bool = False, timeout: float = 120) -> dict:
    t0 = time.monotonic()
    await ws.send(json.dumps({"type": "text", "text": prompt}))
    out = {"text": "", "tools": [], "ui": 0, "last_ui": None, "audio_bytes": 0,
           "first_audio": None, "first_token": 999.0, "states": [], "errors": [], "summaries": {}}
    parts: list[str] = []
    done = False
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            m = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.monotonic()))
        except asyncio.TimeoutError:
            break
        if isinstance(m, bytes):
            if out["first_audio"] is None:
                out["first_audio"] = time.monotonic() - t0
            out["audio_bytes"] += len(m)
            continue
        d = json.loads(m)
        k = d.get("type")
        if k == "assistant_delta":
            if not parts:
                out["first_token"] = time.monotonic() - t0
            parts.append(d["text"])
        elif k == "tool_end":
            out["tools"].append(d["name"])
            out["summaries"][d["name"]] = d.get("summary") or ""
        elif k == "ui":
            out["ui"] += 1
            out["last_ui"] = d["spec"]
        elif k == "state":
            out["states"].append(d["value"])
            if d["value"] == "idle" and done and (out["audio_bytes"] or not want_audio):
                break
        elif k == "error":
            out["errors"].append(d["message"])
        elif k == "assistant_done":
            done = True
            if not want_audio:
                break
    out["text"] = "".join(parts).strip()
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=BASE)
    p.add_argument("--quick", action="store_true")
    parsed = p.parse_args()
    if not parsed.base:
        sys.exit("verify: say which Rouh to check, with --base or ROUH_PUBLIC_URL.")
    sys.exit(asyncio.run(run_all(parsed)))
