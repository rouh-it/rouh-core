"""CONTAINERS.md: the tools that need only Rouh itself, each called as the model calls it.

`Stack.tool` makes Rouh call one tool through the stand-in model and hands back what the tool
gave; the few that answer through a stand-in (pictures through OpenAI's, a helper's own loop
through Anthropic's, YouTube's search) read what that stand-in saw too. What the person does on
a page around a tool, putting words in a box or opening a public link signed out, is done the
way the page does it: its own API, with its own cookie and CSRF token.
"""
from __future__ import annotations

import contextlib
import json
import re
import shlex
import time
import urllib.request

from smoke import Failed, Stack, check, expect

OPENAI, YOUTUBE = 9002, 9018


def post(s: Stack, path: str, body: dict | None = None) -> tuple[int, dict]:
    """What the page's own script posts, signed in: the session cookie, and the CSRF token from
    its cookie sent back as the header (rouh/static/csrf.js)."""
    token = re.search(r"rouh_csrftoken=([^;]+)", s.cookie)
    req = urllib.request.Request(
        s.url + path, method="POST", data=json.dumps(body or {}).encode(),
        headers={"Cookie": s.cookie, "Content-Type": "application/json", "Origin": s.url,
                 "Referer": s.url + "/", "X-CSRFToken": token.group(1) if token else ""})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw, code = r.read(), r.status
    except urllib.error.HTTPError as e:
        raw, code = e.read(), e.code
    try:
        return code, json.loads(raw or b"{}")
    except ValueError:
        return code, {"text": raw.decode("utf-8", "replace")[:400]}


@contextlib.contextmanager
def signed_in(s: Stack):
    """A real Chromium, signed in as the owner the first run made."""
    from playwright.sync_api import sync_playwright

    host = s.url.split("://", 1)[1].split("/", 1)[0].split(":")[0]
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        ctx.add_cookies([{"name": k, "value": v, "domain": host, "path": "/"}
                         for k, v in (c.strip().split("=", 1) for c in s.cookie.split(";") if "=" in c)])
        try:
            yield ctx.new_page()
        finally:
            b.close()


def wait_until(what, why: str, limit: float = 60):
    end = time.time() + limit
    last = None
    while time.time() < end:
        last = what()
        if last:
            return last
        time.sleep(2)
    raise Failed(f"{why}: {str(last)[:400]}")


def fine(name: str, got: str) -> str:
    for word in ("Traceback", "not available", "is off", "isn't set up", "not set up"):
        expect(word not in got, f"{name}: {got[:400]}")
    return got


@check("tool.goals")
def tool_goals(s: Stack) -> None:
    s.chat = ""  # a chat already filed into a task would file this one into it
    got = fine("set_goal", s.tool("set_goal", {"name": "Stack test goal", "about": "A goal the stack test sets"}))
    expect(re.search(r"task \d+", got), f"set_goal made no task: {got[:400]}")
    got = fine("goals", s.tool("goals", {}))
    expect("stack test goal" in got.lower(), f"the goal is not in goals: {got[:400]}")


@check("tool.decisions")
def tool_decisions(s: Stack) -> None:
    got = fine("decisions", s.tool("decisions", {"action": "list"}))
    expect("waiting" in got.lower() or "decision" in got.lower(), f"decisions said: {got[:400]}")
    code, body, _ = s.get("/api/decisions")
    expect(code == 200, f"/api/decisions answered {code}: {body[:200]}")


@check("tool.thoughts")
def tool_thoughts(s: Stack) -> None:
    got = fine("capture_thought", s.tool("capture_thought", {"words": "The stack test thinks in plain words",
                                                             "title": "Stack test thought"}))
    expect("kept" in got.lower(), f"capture_thought: {got[:400]}")
    got = fine("thoughts", s.tool("thoughts", {"action": "list", "q": "stack test"}))
    expect("stack test thought" in got.lower(), f"the thought is not listed: {got[:400]}")


@check("tool.incubator")
def tool_incubator(s: Stack) -> None:
    got = fine("incubator_add", s.tool("incubator_add", {"title": "Stack test incubator idea",
                                                         "text": "Kept by the stack test's tool call."}))
    expect("added inc-" in got.lower(), f"incubator_add: {got[:400]}")
    code = got.split("Added ", 1)[1].split(",", 1)[0]
    got = fine("incubator_list", s.tool("incubator_list", {"q": "stack test incubator"}))
    expect(code.lower() in got.lower(), f"the idea is not listed: {got[:400]}")
    got = fine("incubator_status", s.tool("incubator_status", {"ids": [code], "status": "parked", "note": "stack test"}))
    expect("parked" in got.lower(), f"incubator_status: {got[:400]}")


@check("tool.trials")
def tool_trials(s: Stack) -> None:
    got = fine("trials", s.tool("trials", {"action": "list"}))
    # "No tries yet." on a fresh Rouh (0e8a66e1 renamed a trial's runs to tries).
    expect("trial" in got.lower() or "tries" in got.lower(), f"trials list: {got[:400]}")
    got = fine("trials", s.tool("trials", {"action": "problems", "status": "all"}))
    expect("problem" in got.lower(), f"trials problems: {got[:400]}")


@check("tool.box")
def tool_box(s: Stack) -> None:
    """A box on the screen, the person's words put into it on the Boxes page, and opened by its
    number only because the person named it."""
    got = fine("new_box", s.tool("new_box", {}))
    expect("box" in got.lower(), f"new_box: {got[:400]}")
    code, made = post(s, "/api/box/new", {"content": "the stack test's sealed words", "label": "Stack test"})
    expect(code == 200 and made.get("ok"), f"the Boxes page could not keep a box: {code} {made}")
    number = (made.get("box") or {}).get("number")
    text, _ = s.say(f"Open box {number}. TOOL open_box {json.dumps({'number': number})}")
    expect("the stack test's sealed words" in text, f"open_box did not open the box the person named: {text[:400]}")


@check("tool.payments")
def tool_payments(s: Stack) -> None:
    got = fine("payments", s.tool("payments", {"action": "status"}))
    expect("card" in got.lower() and "stripe" in got.lower(), f"payments: {got[:400]}")
    code, body, _ = s.get("/api/payments")
    expect(code == 200, f"the Payments page's /api/payments answered {code}: {body[:200]}")


@check("tool.shipping")
def tool_shipping(s: Stack) -> None:
    got = fine("shipping", s.tool("shipping", {"action": "list"}))
    expect("shipping" in got.lower(), f"shipping: {got[:400]}")
    code, body, _ = s.get("/api/shipping")
    expect(code == 200, f"the Shipping page's /api/shipping answered {code}: {body[:200]}")


@check("tool.look-into")
def tool_look_into(s: Stack) -> None:
    """A helper's own short loop, answered by the stand-in model, and only its answer back."""
    got = fine("look_into", s.tool("look_into", {"task": "What does the stack test check?"}))
    expect("helper" in got.lower() and "I received" in got, f"look_into: {got[:400]}")


@check("tool.agent-instructions")
def tool_agent_instructions(s: Stack) -> None:
    """One added in the person's words, then on the Agent instructions page, which is what the
    worker's runs are handed (callbacks.agent-instructions)."""
    fine("agent_instructions", s.tool("agent_instructions", {
        "action": "add", "text": "The stack test asks every agent for plain words.",
        "title": "Stack test words", "group": "Stack test"}))
    code, body, _ = s.get("/api/agent-instructions")
    expect(code == 200 and "The stack test asks every agent for plain words." in body,
           f"the new agent instruction is not on its page ({code}): {body[:300]}")


@check("tool.models")
def tool_models(s: Stack) -> None:
    """The models read, the mode switched to Saver as the person asks for it, seen on Settings,
    Models, and put back."""
    got = s.tool("model_defaults", {})
    expect("Traceback" not in got, got[:400])
    expect("cheaper" in got.lower() and "smart" in got.lower(), f"model_defaults: {got[:400]}")
    was = json.loads(s.get("/api/settings/models")[1]).get("mode") or "balanced"
    try:
        got = s.tool("model_defaults", {"which": "mode", "mode": "saver"})
        expect("Changed" in got, f"model_defaults could not switch to Saver: {got[:400]}")
        code, body, _ = s.get("/api/settings/models")
        expect(code == 200 and json.loads(body).get("mode") == "saver", f"Settings, Models says: {body[:200]}")
    finally:
        s.tool("model_defaults", {"which": "mode", "mode": was})


@check("tool.publish")
def tool_publish(s: Stack) -> None:
    """A task's built page made public, and its link opened by somebody who is not signed in."""
    s.chat = ""  # a chat already filed into a task would file this one into it
    got = fine("set_goal", s.tool("set_goal", {"name": "Stack test public page", "about": "A page to publish"}))
    number = re.search(r"task (\d+)", got)
    expect(number, f"no task to publish: {got[:400]}")
    number = number.group(1)
    # The page a run or Ask AI would build, written into the task's folder in the core's workspace.
    r = s.run("core", "cd /code && python -c " + shlex.quote(
        "import pathlib, sys\n"
        "from rouh.config import config\n"
        f"found = sorted(pathlib.Path(config.assistant_repo).glob('**/{number}.*'))\n"
        "folder = [f for f in found if f.is_dir()][0]\n"
        "(folder / 'page.html').write_text('<!doctype html><title>Stack test page</title>"
        "<p>The stack test published this page.</p>')\n"
        "print(folder)\n"), user="10001")
    expect(r.returncode == 0, f"the page could not be written: {(r.stderr or r.stdout)[-400:]}")
    text, seen = s.say(f"Make task {number} public. TOOL publish_task {json.dumps({'task': number})}")
    links = [b.get("href") for m in seen if m.get("type") == "ui"
             for b in (m.get("spec") or {}).get("blocks") or [] if b.get("block") == "link"]
    expect(links, f"publish_task gave no link: {text[:400]}")
    path = links[0].split("://", 1)[-1].split("/", 1)[-1]
    code, body, _ = s.get("/" + path, cookie=False)
    expect(code == 200 and "The stack test published this page" in body,
           f"the public link {links[0]} answered {code} signed out: {body[:300]}")


@check("tool.picture")
def tool_picture(s: Stack) -> None:
    """A picture drawn by the stand-in for OpenAI's images, and shown in the chat."""
    text, seen = s.say('Draw a small red house. TOOL make_picture {"prompt": "A small red house"}', 180)
    ends = [m for m in seen if m.get("type") == "tool_end" and m.get("name") == "make_picture"]
    expect(ends, f"make_picture was not called (is there an OpenAI key in the core?): {text[:300]}")
    expect("There is no tool called" not in text and "Traceback" not in text, f"make_picture: {text[:400]}")
    expect("could not" not in text.lower() and "failed" not in text.lower(), f"make_picture: {text[:400]}")


@check("tool.web")
def tool_web(s: Stack) -> None:
    """A page read with web_fetch, the server tool Rouh offers the model: the stand-in model
    reads it only when Rouh's request offers web search and fetch as the model's own."""
    text, _ = s.say("What does http://core:8021/login say?", 180)
    expect("from memory" not in text, f"Rouh's request did not offer the web tools: {text[:400]}")
    expect(" says: " in text and "could not read" not in text, f"the page was not read: {text[:400]}")


@check("tool.youtube")
def tool_youtube(s: Stack) -> None:
    """YouTube's search, through the Data API with the installation's key (the stand-in's)."""
    got = fine("youtube_search", s.tool("youtube_search", {"query": "stack test"}))
    expect("scraped" not in got.lower(), f"youtube_search did not use the API: {got[:400]}")
    expect("youtube.com/watch" in got, f"youtube_search found nothing: {got[:400]}")
    seen = s.standin(YOUTUBE, "/_calls")
    expect(any("stack test" in json.dumps(c) for c in (seen or [])), f"the stand-in for YouTube saw: {seen}")


# --- the machine, and Claude Code in the worker ---------------------------------------------------

@check("machine.load")
def machine_load(s: Stack) -> None:
    """The orb's reading of the machine: the core container's own processors and processes."""
    code, body, _ = s.get("/api/machine/load")
    expect(code == 200, f"/api/machine/load answered {code}: {body[:200]}")
    got = json.loads(body)
    r = s.run("core", "python3 -c 'import os; print(os.cpu_count(), sum(n.isdigit() for n in os.listdir(\"/proc\")))'")
    cpus, procs = (int(n) for n in r.stdout.split())
    expect(got.get("cpu_count") == cpus, f"the reading has {got.get('cpu_count')} processors, the container {cpus}")
    expect(isinstance(got.get("cpu_percent"), (int, float)), f"no processor load in the reading: {body[:300]}")
    expect(abs(int(got.get("processes") or 0) - procs) <= 25,
           f"the reading counts {got.get('processes')} processes, the container has {procs}")
    expect((got.get("memory") or {}).get("total_bytes"), f"no memory in the reading: {body[:300]}")


@check("claude.installed")
def claude_installed(s: Stack) -> None:
    r = s.run("worker", "claude --version", user="10001")
    expect(r.returncode == 0 and re.search(r"\d+\.\d+", r.stdout), f"claude --version in the worker: {(r.stdout + r.stderr)[-300:]}")


@check("claude.signin")
def claude_signin(s: Stack) -> None:
    """Claude Code's sign-in page, opened in a real Chromium by the owner, asks the one program in
    the worker for Claude Code's state and says it."""
    code, body, _ = s.get("/setup/claude/state")
    expect(code == 200, f"/setup/claude/state answered {code}: {body[:200]}")
    state = json.loads(body).get("state")
    expect(state in ("signed_out", "signed_in", "waiting_for_code"),
           f"the page could not ask the one program: it says {state!r}")
    with signed_in(s) as pg:
        answer = pg.goto(s.url + "/setup/claude")
        expect(answer and answer.status == 200 and "/setup/claude" in pg.url, f"/setup/claude opened at {pg.url}")
        pg.screenshot(path=str(s.out / "claude-signin.png"))
        text = pg.inner_text("body").lower()
    expect("claude" in text and "sign in" in text, f"the sign-in page says: {text[:300]}")


@check("codex.signin")
def codex_signin(s: Stack) -> None:
    """Codex's sign-in with a ChatGPT plan (`/setup/codex`): the page asks the one program in the
    worker, which runs `codex login status`, and Codex's folder is on the worker-home volume, so a
    sign-in outlives a rebuilt or redeployed worker. Starting the device sign-in needs OpenAI, which
    a stack test never reaches, so it is proved in a browser instead (CONTAINERS.md)."""
    code, body, _ = s.get("/setup/codex/state")
    expect(code == 200, f"/setup/codex/state answered {code}: {body[:200]}")
    state = json.loads(body).get("state")
    expect(state in ("signed_out", "signed_in"), f"the page could not ask the one program: it says {state!r}")
    r = s.run("worker", "python3 -c 'import sys; sys.path.insert(0, \"/code\"); from one import codexhome; "
                        "print(codexhome.folder())' && grep -c ' /home/rouh ' /proc/self/mountinfo", user="10001")
    lines = r.stdout.split()
    expect(r.returncode == 0 and lines[:1] == ["/home/rouh/.codex"] and lines[1:2] != ["0"],
           f"Codex's folder in the worker, and whether /home/rouh is a volume: {(r.stdout + r.stderr)[-300:]}")
    with signed_in(s) as pg:
        answer = pg.goto(s.url + "/setup/codex")
        expect(answer and answer.status == 200 and "/setup/codex" in pg.url, f"/setup/codex opened at {pg.url}")
        pg.screenshot(path=str(s.out / "codex-signin.png"))
        text = pg.inner_text("body")
    expect("Sign in Codex with ChatGPT" in text, f"the sign-in page says: {text[:300]}")
