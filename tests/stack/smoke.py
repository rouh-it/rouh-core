"""Every feature of CONTAINERS.md, checked on the running stack from outside, as the person uses it.

tests/stack/run.sh starts the real stack and then runs this on the test machine:

    python3 tests/stack/smoke.py --url http://127.0.0.1:8420 --features CONTAINERS.md \\
        --compose "docker compose -p rouh-stack-test ..." --out DIR [--only ID,ID]

CONTAINERS.md is the one list of what a Rouh can do and whether the containers carry it. Each row
has an id and a status; every row whose status is **works** names a check here by that id, and
that check must pass, or this exits 1. A row still **broken** is checked too when it has a check,
and said, without failing: when it starts to pass, the line says so, and the row is to be marked
works in the same change. A row that says works with no check here fails, so the list cannot say
more than is proved.

The checks drive what the person drives: the first-run pages in a real Chromium, the page's own
socket (`/ws`, PROTOCOL.md) with the stand-in model calling whatever tool a message names
(`TOOL name {json}`, rouh/testing/fake_model.py), the stand-ins' own records of what reached them,
and, for what only happens between the containers, the containers themselves (`docker compose
exec`), never Rouh's internals. Last line: ``STACK-TEST {json}``.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import signal
import subprocess
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

CHECKS: dict[str, callable] = {}
#: The checks that start Rouh again, run after every other; and of those, the ones that undo what
#: the others did, after them.
LAST: set[str] = set()
FINAL: set[str] = set()


class Failed(AssertionError):
    pass


#: How long one check may take before it is failed, so one that hangs cannot hold the rest; and
#: the few that wait on a run or on Rouh starting again, their own.
CHECK_LIMIT = 300
LIMIT: dict[str, float] = {"first-run": 420, "one.run": 480}


class TookTooLong(Failed):
    pass


def _too_long(signum, frame):
    raise TookTooLong("it took longer than its limit, so it was stopped")


def check(*ids: str):
    def mark(fn):
        for i in ids:
            CHECKS[i] = fn
        return fn
    return mark


def expect(cond, why: str) -> None:
    if not cond:
        raise Failed(why)


# --- the list ------------------------------------------------------------------------------------

ROW = re.compile(r"^\|\s*`([a-z0-9][a-z0-9.\-]*)`\s*\|(.*)$")
STATUSES = ("works", "broken", "untested", "manual", "replaced", "creator-only")
#: The rows whose check must pass: what works, and what the containers do another way.
ENFORCED = ("works", "replaced")


def read_features(path: Path) -> list[dict]:
    """Every row of CONTAINERS.md's tables: | `id` | feature | before | now | how it is checked |."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).rstrip("|").split("|")]
        if len(cells) < 4:
            continue
        now = cells[2].strip("* ").lower()
        if now not in STATUSES:
            raise SystemExit(f"CONTAINERS.md: {m.group(1)} has the status {cells[2]!r}, not one of {', '.join(STATUSES)}")
        rows.append({"id": m.group(1), "feature": cells[0], "before": cells[1].strip("* ").lower(), "now": now})
    ids = [r["id"] for r in rows]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise SystemExit(f"CONTAINERS.md: these ids are on more than one row: {', '.join(dup)}")
    return rows


# --- the stack -----------------------------------------------------------------------------------

class Stack:
    def __init__(self, url: str, compose: str, out: Path):
        self.url = url.rstrip("/")
        self.compose = shlex.split(compose)
        self.out = out
        self.cookie = ""
        self.ws = None
        self.chat = ""
        self._ready: dict = {}
        self.setup_url = ""

    # The containers themselves, for what only happens between them.
    def run(self, service: str, script: str, *, user: str | None = None, timeout: float = 120,
            env: dict | None = None) -> subprocess.CompletedProcess:
        args = [*self.compose, "exec", "-T"]
        if user:
            args += ["--user", user]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        args += [service, "bash", "-c", script]
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)

    def py(self, service: str, code: str, **kw) -> subprocess.CompletedProcess:
        return self.run(service, "cd /code && python - <<'PY'\n" + code + "\nPY", **kw)

    def manage(self, code: str, timeout: float = 120) -> str:
        """Python inside the core, with Rouh's Django set up, as its own commands set it up."""
        r = self.py("core", "from rouh.project import setup\nsetup()\n" + code, timeout=timeout)
        if r.returncode:
            raise Failed(f"Python in the core failed: {(r.stderr or r.stdout)[-600:]}")
        return r.stdout

    def logs(self, service: str, tail: int = 400) -> str:
        r = subprocess.run([*self.compose, "logs", "--no-color", "--tail", str(tail), service],
                           capture_output=True, text=True, timeout=60)
        return r.stdout + r.stderr

    def standin(self, port: int, path: str) -> object:
        """What a stand-in saw, read from inside the stack (it answers on the standins network)."""
        r = self.run("core", f"python -c \"import urllib.request,sys; sys.stdout.write(urllib.request.urlopen('http://standins:{port}{path}', timeout=10).read().decode())\"")
        if r.returncode:
            raise Failed(f"the stand-in on {port} did not answer {path}: {r.stderr[-300:]}")
        try:
            return json.loads(r.stdout)
        except ValueError:
            return r.stdout

    # The page's own HTTP and socket, signed in as the owner.
    def get(self, path: str, *, cookie: bool = True, follow: bool = True,
            headers: dict | None = None) -> tuple[int, str, dict]:
        req = urllib.request.Request(self.url + path, headers={
            **({"Cookie": self.cookie} if cookie and self.cookie else {}), **(headers or {})})
        opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)

    def socket(self):
        """The page's own socket, signed in, in the stack test's own chat: a new one, made on the
        first message and kept, so no other turn (the phone's, in General) is taken for one of
        these. Opened afresh for every message: a socket nobody reads between checks stops
        answering the server's pings and is dropped."""
        from websockets.sync.client import connect

        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001 - a socket already gone is closed enough
                pass
        ws_url = self.url.replace("http", "ws", 1) + "/ws"
        self.ws = connect(ws_url, additional_headers={"Cookie": self.cookie}, open_timeout=30,
                          max_size=64 * 1024 * 1024)
        self.ws.send(json.dumps({"type": "hello", "client": "stack-test/1", "tz": "Europe/Athens",
                                 "chat": self.chat, "strip": ""}))
        self._ready = self.wait_for(lambda m: m.get("type") == "ready", 60)
        if not self.chat:
            self.ws.send(json.dumps({"type": "new_chat"}))
            got = self.wait_for(lambda m: m.get("type") == "chat_switched", 30)
            self.chat = str((got.get("chat") or {}).get("id") or "")
            expect(self.chat, f"a new chat was not opened: {got}")
        return self.ws

    def wait_for(self, want, limit: float, seen: list | None = None) -> dict:
        end = time.time() + limit
        while time.time() < end:
            try:
                raw = self.ws.recv(timeout=max(0.1, end - time.time()))
            except TimeoutError:
                break
            if isinstance(raw, bytes):
                continue
            m = json.loads(raw)
            if seen is not None:
                seen.append(m)
            if want(m):
                return m
        raise Failed("the page's socket did not say what was waited for in %ds" % limit)

    def say(self, text: str, limit: float = 120) -> tuple[str, list[dict]]:
        """A typed message, as the page sends it; the whole answer and everything sent meanwhile."""
        self.socket()
        seen: list[dict] = []
        try:
            self.ws.send(json.dumps({"type": "text", "text": text}))
            done = self.wait_for(lambda m: (m.get("type") == "assistant_done" and str(m.get("chat") or self.chat) == self.chat)
                                 or (m.get("type") == "error" and m.get("fatal") is not False), limit, seen)
        finally:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass
            self.ws = None
        if done.get("type") == "error":
            raise Failed(f"the turn ended in an error: {done.get('message')}")
        return done.get("text") or "", seen

    def tool(self, name: str, args: dict | None = None, limit: float = 120) -> str:
        """Rouh calls one tool, as the model asked it to, and the stand-in model says back what it
        handed back (fake_model: "I received: tool result ...")."""
        text, seen = self.say(f"TOOL {name} {json.dumps(args or {})}", limit)
        ends = [m for m in seen if m.get("type") == "tool_end" and m.get("name") == name]
        if not ends and "A job has finished" in text:
            # The report of a job an earlier check started (crew.tools) is its own turn in this
            # chat, and its end was taken for this one's: the tool was never called, so ask again.
            text, seen = self.say(f"TOOL {name} {json.dumps(args or {})}", limit)
            ends = [m for m in seen if m.get("type") == "tool_end" and m.get("name") == name]
        expect(ends, f"{name} was not called (is it offered here?): {text[:300]}")
        result = text.split("tool result ", 1)[-1] if "tool result " in text else text
        if "There is no tool called" in result:
            raise Failed(f"{name} is not a tool this Rouh has")
        return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


# --- the stack itself ------------------------------------------------------------------------------

@check("stack.check")
def stack_check(s: Stack) -> None:
    said = (s.out / "stack-check.txt").read_text() if (s.out / "stack-check.txt").is_file() else ""
    expect("may be applied" in said, f"the stack check on deploy/stack/compose.yml: {said[-600:] or 'it did not run'}")


@check("stack.up")
def stack_up(s: Stack) -> None:
    r = subprocess.run([*s.compose, "ps", "-a", "--format", "{{.Service}}|{{.State}}|{{.Health}}|{{.ExitCode}}"],
                       capture_output=True, text=True, timeout=60)
    parts = [l.split("|") for l in r.stdout.splitlines() if l.count("|") == 3]
    bad = [p[0] for p in parts if (p[1] == "exited" and p[3] != "0") or p[2] in ("unhealthy", "starting")
           or p[1] not in ("running", "exited")]
    expect(r.returncode == 0 and r.stdout.strip() and not bad, f"not every part is healthy: {bad or r.stderr[-300:]}")


# --- the person's first minutes --------------------------------------------------------------------

@check("first-run")
def first_run(s: Stack) -> None:
    """The setup address the core gives (manage.py setup_link; since step 176-25 a start never prints
    the code into the logs, and the logs must not hold it), opened in a real Chromium, every page
    answered as a person would, ending signed in on Rouh's own page."""
    logs = s.setup_url or s.run("core", "cd /code && python manage.py setup_link").stdout
    codes = re.findall(r"/setup\?code=([A-Za-z0-9_\-]+)", logs)
    expect(codes, "the core gave no setup address: " + logs[-400:])
    expect(codes[-1] not in s.logs("core", 4000), "the setup code is in the core's logs, where the docker group reads it")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        pg = ctx.new_page()
        pg.goto(f"{s.url}/setup?code={codes[-1]}")
        for _ in range(16):
            pg.wait_for_load_state()
            start = pg.get_by_role("button", name="Start talking")
            if "/setup" not in pg.url:
                break
            if pg.query_selector("#firstName"):
                pg.fill("#firstName", "Alex"); pg.fill("#lastName", "Morgan"); pg.fill("#email", "alex@example.com")
                if pg.query_selector("#password1"):
                    pg.fill("#password1", STACK_PASSWORD); pg.fill("#password2", STACK_PASSWORD)
                pg.click("button[type=submit]")
            elif pg.query_selector("button[value=own]"):
                pg.click("button[value=own]")
            elif pg.query_selector("#hNick"):
                pg.click("button[type=submit]")
            elif pg.query_selector("#next"):
                pg.eval_on_selector("#next", "e => e.hidden = false"); pg.click("#next")
            elif start.count():
                start.first.click()
            elif "/setup/brain" in pg.url and not pg.query_selector("#key") and pg.query_selector("a[href$='/anthropic']"):
                pg.click("a[href$='/anthropic']")
            elif pg.query_selector("#key"):
                pg.fill("#key", "sk-ant-stack-test-not-a-real-one"); pg.click("button[type=submit]")
            else:
                break
        pg.screenshot(path=str(s.out / "first-run.png"))
        expect("/setup" not in pg.url and "/login" not in pg.url,
               f"the first run ended at {pg.url}: {pg.inner_text('body')[:400]}")
        pg.wait_for_selector("#conn[data-state=live]", state="attached", timeout=90000)
        s.cookie = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies())
        (s.out / "cookie.txt").write_text(s.cookie)
        b.close()


#: The owner's password, set on the first run's details screen (the way in while a Rouh cannot email): a
#: letter, a number, a symbol and ten characters, as the password rules ask (task 176).
STACK_PASSWORD = "stack-test-garden-hedgehog-91"


@check("sign-in.email")
def sign_in_email(s: Stack) -> None:
    """The sign-in page, signed out, in a real Chromium: one email box and Continue, no Google; the
    owner's email leads on to a link by email or to the password, and the password signs in; and
    the server's own one-time link (`manage.py signin_link`) signs the owner in too."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context().new_page()
        pg.goto(f"{s.url}/login")
        body = pg.inner_text("body")
        expect(pg.query_selector("#email") and "Continue with email" in body and "Google" not in body,
               f"the sign-in page is not one email box: {body[:300]}")
        pg.fill("#email", "alex@example.com"); pg.click("#continueBtn"); pg.wait_for_load_state()
        body = pg.inner_text("body")
        expect("Check your email" in body or "sign in with your password" in body,
               f"Continue said neither: {body[:300]}")
        if "Check your email" in body:
            pg.click("text=Can't get the email?")
        pg.fill("#password", STACK_PASSWORD); pg.click("button:has-text('Sign in')" if "Check your email" not in body
                                                      else "button:has-text('Sign in with password')")
        pg.wait_for_load_state()
        expect("/login" not in pg.url, f"the password did not sign in: {pg.inner_text('body')[:300]}")
        r = s.run("core", "cd /code && python manage.py signin_link alex@example.com")
        link = re.search(r"(/login/link/[A-Za-z0-9_\-]+)", r.stdout)
        expect(r.returncode == 0 and link, f"signin_link printed no link: {(r.stderr or r.stdout)[-300:]}")
        other = b.new_context().new_page()
        other.goto(s.url + link.group(1)); other.click("button:has-text('Sign in')"); other.wait_for_load_state()
        expect("/login" not in other.url, f"the one-time link did not sign in: {other.inner_text('body')[:300]}")
        b.close()


@check("page-loads")
def page_loads(s: Stack) -> None:
    """Rouh's page, and every page its navigation links to (the rail's rows and Anatomy's
    groups, read off the page itself), each opened in a real Chromium, signed in, with no error
    in its script."""
    code, body, _ = s.get("/")
    expect(code == 200 and "<html" in body.lower(), f"Rouh's page answered {code}")
    for path in ("/settings", "/healthz"):
        code, said, _ = s.get(path)
        expect(code == 200, f"{path} answered {code}: {said[:200]}")
    pages = []
    for tag in re.findall(r"<a\b[^>]*>", body):
        named = re.search(r'data-nav="([^"]+)"', tag) or re.search(r'id="(nav-[^"]+)"', tag)
        href = re.search(r'href="(/[^"]*)"', tag)
        if named and href and href.group(1) not in pages:
            pages.append(href.group(1))
    expect(len(pages) >= 10, f"the navigation has only {pages}")
    from playwright.sync_api import sync_playwright

    host = s.url.split("://", 1)[1].split("/", 1)[0].split(":")[0]
    bad = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        ctx.add_cookies([{"name": k, "value": v, "domain": host, "path": "/"}
                         for k, v in (c.strip().split("=", 1) for c in s.cookie.split(";") if "=" in c)])
        for path in pages:
            pg = ctx.new_page()
            errors = []
            pg.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            answer = pg.goto(s.url + path, wait_until="load", timeout=60000)
            pg.wait_for_timeout(1500)
            if answer is None or answer.status != 200 or "/login" in pg.url or errors:
                bad.append(f"{path}: {answer.status if answer else 'no answer'} at {pg.url} {errors[:2]}")
            pg.close()
        b.close()
    expect(not bad, "pages of the navigation did not open: " + "; ".join(bad))


@check("chat-turn")
def chat_turn(s: Stack) -> None:
    text, _ = s.say("Hello from the stack test")
    expect("I received" in text, f"the answer was not the stand-in model's: {text[:300]}")


# --- tools that need only Rouh itself --------------------------------------------------------------

def tool_ok(name: str, args: dict, *, has: str = "", refused=("Traceback", "not available", "is off", "isn't set up")):
    def fn(s: Stack) -> None:
        got = s.tool(name, args)
        for word in refused:
            expect(word not in got, f"{name}: {got[:400]}")
        if has:
            expect(has.lower() in got.lower(), f"{name} did not hand back {has!r}: {got[:400]}")
    fn.__name__ = f"tool_{name}"
    return fn


CHECKS["tool.show-on-screen"] = tool_ok("show_on_screen", {"title": "Stack test card", "blocks": [{"block": "text", "text": "A card from the stack test"}]})
CHECKS["tool.memory"] = tool_ok("remember", {"text": "The stack test likes plain words"})
CHECKS["tool.server-health"] = tool_ok("server_health", {}, has="memory")
CHECKS["tool.what-is-running"] = tool_ok("what_is_running", {})


@check("tool.tasks")
def tool_tasks(s: Stack) -> None:
    got = s.tool("make_a_task", {"title": "Stack test task"})
    expect("Traceback" not in got, got[:400])
    got = s.tool("read_workspace", {"search": "Stack test task"})
    expect("stack test task" in got.lower(), f"the new task was not found: {got[:400]}")


@check("tool.clockwork")
def tool_clockwork(s: Stack) -> None:
    got = s.tool("schedule", {"title": "Hello from the stack test", "kind": "remind", "in_minutes": 600})
    expect("Traceback" not in got, got[:400])
    got = s.tool("upcoming", {})
    expect("hello from the stack test" in got.lower(), f"the reminder is not in upcoming: {got[:400]}")


# --- the containers' own walls ---------------------------------------------------------------------

@check("keys.proxy-adds-key")
def proxy_adds_key(s: Stack) -> None:
    """A run's call to the model, from the worker with no key, reaches the model with the
    installation's key on (the stand-in model records the request it got)."""
    r = s.py("worker", """
import json, urllib.request
req = urllib.request.Request("http://keyproxy:8080/anthropic/v1/messages", method="POST",
    data=json.dumps({"model": "claude-x", "max_tokens": 16, "messages": [{"role": "user", "content": "proxy check"}]}).encode(),
    headers={"content-type": "application/json", "anthropic-version": "2023-06-01", "x-api-key": "the-worker-has-none"})
print(urllib.request.urlopen(req, timeout=30).status)
""")
    expect(r.returncode == 0 and "200" in r.stdout, f"the worker's call through the key proxy failed: {r.stderr[-400:]}")


@check("keys.worker-holds-none")
def worker_holds_none(s: Stack) -> None:
    r = s.run("worker", "env | grep -iE 'ANTHROPIC_API_KEY|OPENAI_API_KEY' | grep -v via-keyproxy; ls /keys 2>&1; "
                        "grep -rl 'not-a-real-one' /home/rouh /run/one 2>/dev/null | head -3; true")
    expect("not-a-real-one" not in r.stdout and "No such file" in r.stdout,
           f"the worker can see a key: {r.stdout[-400:]}")


@check("walls.worker-no-database")
def worker_no_database(s: Stack) -> None:
    r = s.run("worker", "getent hosts postgres || echo none")
    expect("none" in r.stdout, f"the worker can resolve the database: {r.stdout}")


@check("walls.worker-no-direct-internet")
def worker_no_direct(s: Stack) -> None:
    r = s.run("worker", "env -u HTTPS_PROXY -u https_proxy -u HTTP_PROXY -u http_proxy "
                        "curl -sS --max-time 8 https://example.com -o /dev/null && echo reached || echo refused")
    expect("refused" in r.stdout, "the worker reached the internet past the key proxy")


@check("walls.proxy-refuses-private")
def proxy_refuses_private(s: Stack) -> None:
    r = s.run("worker", "curl -sS --max-time 8 -x http://keyproxy:8080 https://core:8021/healthz -o /dev/null -w '%{http_code}' ; echo")
    expect("200" not in r.stdout, f"the key proxy let the worker through to a private address: {r.stdout}")


@check("walls.no-root")
def no_root(s: Stack) -> None:
    """No long-running part runs as root once started, but the guard, which is root only in its
    own box (compose.yml says why): every process in the core, the worker and the key proxy but
    the container's own init is its part's user."""
    for svc, want in (("core", "10001"), ("worker", "10001"), ("keyproxy", "10002")):
        r = s.run(svc, "python3 -c " + shlex.quote(
            "import os\n"
            "me = {os.getpid(), os.getppid()}\n"
            "for n in os.listdir('/proc'):\n"
            "    if not n.isdigit() or n == '1' or int(n) in me: continue\n"
            "    try:\n"
            "        uid = [l.split()[1] for l in open(f'/proc/{n}/status') if l.startswith('Uid:')][0]\n"
            "        cmd = open(f'/proc/{n}/cmdline').read().replace(chr(0), ' ')[:60]\n"
            "    except OSError: continue\n"
            "    print(n, uid, cmd)\n"), user=want)
        rows = [line.split(" ", 2) for line in r.stdout.splitlines() if line.strip()]
        root = [row for row in rows if row[1] == "0"]
        # Docker's own health probe is exec'd as the image's user for a second at a time; what is
        # asked here is that no lasting part is root, so a root process must be there each time.
        for _ in range(2):
            if not root:
                break
            time.sleep(2)
            again = s.run(svc, f"for p in {' '.join(row[0] for row in root)}; do "
                               "[ -d /proc/$p ] && awk '/^Uid:/{print $2}' /proc/$p/status | sed \"s/^/$p /\"; done",
                          user=want).stdout.split()
            still = {again[i] for i in range(0, len(again) - 1, 2) if again[i + 1] == "0"}
            root = [row for row in root if row[0] in still]
        expect(rows and not root, f"{svc} runs something as root: {root[:3] or r.stderr[-200:]}")


# --- the one program -------------------------------------------------------------------------------

@check("one.paired")
def one_paired(s: Stack) -> None:
    got = s.tool("one_runs", {})
    expect("Traceback" not in got and "not paired" not in got.lower(), got[:400])


@check("one.run-screen")
def one_run_screen(s: Stack) -> None:
    code, body, _ = s.get("/one/runs")
    expect(code == 200 and "one" in body.lower(), f"/one/runs answered {code} through the core")


@check("one.terminal")
def one_terminal(s: Stack) -> None:
    """The one program's socket, as Rouh's run screen opens it: through the core, signed in to
    Rouh, and answered by the program, not refused as a browser it does not know (4401)."""
    from websockets.sync.client import connect

    ws = connect(s.url.replace("http", "ws", 1) + "/one/ws", additional_headers={"Cookie": s.cookie},
                 open_timeout=30)
    try:
        ws.send(json.dumps({"t": "hello", "id": 1}))
        got = json.loads(ws.recv(timeout=20))
    finally:
        ws.close()
    expect(got.get("t") != "err", f"the one program refused the page's socket: {got}")


@check("one.phone-question")
def one_phone_question(s: Stack) -> None:
    """A run's question page on the phone, by its own address, with no sign-in: a wrong token is
    the program's own "no such question", not Rouh's 404 or its sign-in page."""
    req = urllib.request.Request(s.url + "/one/q/not-a-real-question-token")
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=20) as r:
            code, body = r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, body = e.code, e.read().decode("utf-8", "replace")
    expect(code != 302 and "/login" not in body[:2000] and code in (200, 404, 410),
           f"/one/q/ answered {code} through the core: {body[:200]}")
    expect("one" in body.lower() or "question" in body.lower(), f"that was not the one program's answer: {body[:200]}")


# --- a run in the worker, doing what its brief says ---------------------------------------------

#: What the stack test's one run does, line by line (one/tests/fake_claude.py): its probe,
#: tests/stack/run-probe.sh, leaves what it found in the worker's /tmp for the checks below.
RUN_BRIEF = """Stack test run
RUN: echo started > /tmp/stack-run-started
RUN: bash /code/tests/stack/run-probe.sh
WRITE: stack-test/run-note.md A note the stack test's run wrote in the workspace.
COMMIT: A note from the stack test's run
RUN: echo finished > /tmp/stack-run-finished
SAY: The stack test run is done."""

_RUN: dict = {}


def the_run(s: Stack) -> dict:
    """Start the stack test's run once, through Rouh's own tool, and wait for its last line."""
    if _RUN:
        if _RUN.get("error"):
            raise Failed(_RUN["error"])
        return _RUN
    try:
        got = s.tool("one_start", {"brief": RUN_BRIEF, "title": "Stack test run"})
        _RUN["started"] = got
        end = time.time() + 300
        while time.time() < end:
            r = s.run("worker", "cat /tmp/stack-run-finished 2>/dev/null", timeout=30)
            if "finished" in r.stdout:
                break
            time.sleep(5)
        else:
            raise Failed(f"the run did not finish in five minutes (one_start said: {got[:300]}); "
                         f"the worker's log: {s.logs('worker', 60)[-1500:]}")
        for name in ("internet", "notify", "tools", "env", "tree", "task"):
            _RUN[name] = s.run("worker", f"cat /tmp/stack-run-{name} 2>/dev/null").stdout
    except Failed as e:
        _RUN["error"] = str(e)
        raise
    return _RUN


@check("one.run")
def one_run(s: Stack) -> None:
    the_run(s)


@check("runs.internet")
def runs_internet(s: Stack) -> None:
    got = the_run(s)["internet"].strip()
    expect(got.startswith("200"), f"a run's request to https://example.com: {got[:300]} "
                                  f"(the run had {the_run(s)['env'].split() or 'no proxy settings'})")


def _mcp_answer(raw: str, want_id: int) -> dict:
    for line in raw.splitlines():
        try:
            m = json.loads(line)
        except ValueError:
            continue
        if m.get("id") == want_id:
            return m
    raise Failed(f"Rouh's MCP server for runs did not answer: {raw[-500:]}")


# --- runs calling back into Rouh -------------------------------------------------------------------

@check("callbacks.notify-owner")
def notify_owner(s: Stack) -> None:
    """notify_owner from a real run in the worker queues a note Rouh holds for the owner."""
    m = _mcp_answer(the_run(s)["notify"], 2)
    text = json.dumps(m.get("result") or m.get("error"))
    expect(not (m.get("result") or {}).get("isError") and "error" not in m, f"notify_owner from a run: {text[:400]}")
    expect("queued" in text.lower() or "will" in text.lower() or "email" in text.lower(), f"notify_owner said: {text[:400]}")


@check("callbacks.job-tools")
def job_tools(s: Stack) -> None:
    """A run in the worker is offered Rouh's own tools for jobs (mail, calendar, Drive, memory),
    which Rouh lists for it only when the run's call reaches it."""
    m = _mcp_answer(the_run(s)["tools"], 3)
    names = [t.get("name") for t in (m.get("result") or {}).get("tools", [])]
    expect("notify_owner" in names, f"the run's tools: {names}")
    expect(len(names) > 3, f"Rouh's job tools were not offered to the run (only {names}); Rouh was not reached")


@check("callbacks.agent-instructions")
def agent_instructions(s: Stack) -> None:
    """The one program asks Rouh for a run's agent instructions, from the worker, as a run starts."""
    r = s.py("worker", """
import json, urllib.request
key = json.load(open("/run/one/rouh-worker.json"))
req = urllib.request.Request(key["url"] + "/internal/agent-instructions?run=stacktest&via=stack-test",
                             headers={"X-Rouh-Worker-Key": key["token"]})
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    got = json.loads(opener.open(req, timeout=20).read())
    print("ok" if got.get("ok") and got.get("text") else "empty", len(got.get("text") or ""))
except Exception as e:
    print("refused", e)
""")
    expect(r.stdout.strip().startswith("ok"), f"the worker's ask for agent instructions: {(r.stdout + r.stderr).strip()[:400]}")


@check("walls.internal-needs-key")
def internal_needs_key(s: Stack) -> None:
    """Without the worker's key, Rouh's internal addresses still refuse a caller in another
    container, and from the published port too."""
    r = s.py("worker", """
import urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    print(opener.open("http://core:8021/internal/agent-instructions?run=x", timeout=10).status)
except urllib.error.HTTPError as e:
    print(e.code)
except Exception as e:
    print("refused", e)
""")
    expect(not r.stdout.strip().startswith("200"), f"an internal address answered the worker with no key: {r.stdout.strip()}")
    code, _, _ = s.get("/internal/agent-instructions?run=x", cookie=False)
    expect(code != 200, f"an internal address answered the published port with no key: {code}")


# --- running it ------------------------------------------------------------------------------------

def load_checks() -> None:
    """The checks of each area that keeps its own file, tests/stack/checks_<area>.py, each
    importing `smoke` for `check`, `expect`, `Failed` and `Stack`."""
    import importlib.util

    sys.modules.setdefault("smoke", sys.modules[__name__])
    for path in sorted(Path(__file__).resolve().parent.glob("checks_*.py")):
        spec = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        # Known by its name before it runs, so `from checks_x import ...` in another file gets this
        # one, and not a second copy whose checks register again with nothing they share remembered.
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)


def main() -> int:
    signal.signal(signal.SIGALRM, _too_long)
    load_checks()
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--features", required=True)
    ap.add_argument("--compose", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--cookie", default="", help="a signed-in cookie from an earlier run here (cookie.txt), to skip the first run")
    ap.add_argument("--setup-url", default="", help="the setup address, when the core's log is not to hand")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = read_features(Path(a.features))
    only = {i for i in a.only.split(",") if i}
    s = Stack(a.url, a.compose, out)
    s.setup_url = a.setup_url
    s.cookie = a.cookie
    results = []
    # The first run comes first: everything after is signed in as the owner it makes. What
    # starts Rouh again (a change of its own code going live) comes last.
    order = sorted(rows, key=lambda r: (r["id"] != "first-run", r["id"] != "page-loads", r["id"] in LAST or r["id"] in FINAL, r["id"] in FINAL))
    for row in order:
        if only and row["id"] not in only and row["id"] != "first-run":
            continue
        fn = CHECKS.get(row["id"])
        if row["id"] == "first-run" and s.cookie:
            continue
        if fn is None:
            if row["now"] in ENFORCED:
                results.append({**row, "result": "failed", "why": "CONTAINERS.md says it works, and nothing checks it"})
                print(f"FAIL  {row['id']}: CONTAINERS.md says it works, and nothing checks it", flush=True)
            continue
        began = time.time()
        signal.alarm(int(LIMIT.get(row["id"], CHECK_LIMIT)))
        try:
            fn(s)
            result, why = "passed", ""
        except Exception as e:  # noqa: BLE001 - every failure is a sentence in the report
            result = "failed"
            why = str(e) if isinstance(e, Failed) else f"{type(e).__name__}: {e} ({traceback.format_exc().strip().splitlines()[-3].strip()})"
        finally:
            signal.alarm(0)
        took = round(time.time() - began, 1)
        results.append({**row, "result": result, "why": why[:1200], "seconds": took})
        if row["id"] == "first-run" and result != "passed":
            print(f"FAIL  first-run: {why[:600]}", flush=True)
            print("      nothing else can be checked without the owner the first run makes", flush=True)
            break
        if row["now"] in ENFORCED:
            print(f"{'ok  ' if result == 'passed' else 'FAIL'}  {row['id']}" + (f": {why[:600]}" if why else ""), flush=True)
        elif result == "passed":
            print(f"now passes  {row['id']} (CONTAINERS.md says {row['now']}: mark it works)", flush=True)
        else:
            print(f"{row['now']:<8}  {row['id']}: {why[:300]}", flush=True)
    bad = [r for r in results if r["now"] in ENFORCED and r["result"] != "passed"]
    counts = {st: sum(1 for r in rows if r["now"] == st) for st in STATUSES}
    summary = {"ok": not bad, "checked": len(results), "failed": [{"id": r["id"], "why": r["why"]} for r in bad],
               "now_pass": [r["id"] for r in results if r["now"] not in ENFORCED and r["result"] == "passed"],
               "counts": counts}
    (out / "results.json").write_text(json.dumps({"summary": summary, "results": results}, indent=1))
    print(f"{sum(1 for r in results if r['result'] == 'passed')} passed, {len(bad)} failed; "
          + ", ".join(f"{v} {k}" for k, v in counts.items() if v))
    print("STACK-TEST " + json.dumps(summary, ensure_ascii=False))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
