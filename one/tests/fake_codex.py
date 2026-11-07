"""A stand-in for Codex, so the program's tests spend no tokens.

It takes the same arguments the program gives the real one, reads its hooks out
of the ``-c hooks.<Event>=...`` settings on its own command line, and sends them
the same way, with the same fields, as Codex CLI 0.154.0 was watched sending
them on this server on 17 September 2026, driven by a stand-in model. It obeys
the answers the same way: a refused call does not run, a follow-up at the end of
a turn is carried out in the same turn, and what SessionStart answers with is
kept where a test can read it.

What it "does" is written in its prompts, in the same words ``fake_claude.py``
takes, so one test can be written for both agents:

    RUN: <command>          run a shell command, through Codex's shell tool
    WRITE: <path> <text>    write a file, through that same shell tool
    COMMIT: <message>       git add -A and commit
    SAY: <text>             what its last message says
    WAIT: <seconds>         think for a while
    CRASH: <code>           exit at once with that code
    EFFORT                  say what reasoning effort it was started at, so a
                            test can see the level that really reached the
                            command line rather than the one meant to
    NOHOOKS                 from here on, do not send PreToolUse at all: what
                            the real Codex does, silently, when it has not been
                            told to trust the hooks it was given
    LIMIT                   on the ChatGPT subscription, the turn fails the way
                            Codex 0.154 was watched failing when the
                            subscription's usage limit is reached: a
                            ``task_complete`` with ``codex_error_info``
                            ``usage_limit_exceeded`` in the session file, the
                            message on the screen, and no Stop hook. On the API
                            key it is not a limit and the turn goes on
    UNAUTH                  the same, for a login that stopped working
    NOCARRY                 this conversation will not be taken by the API key:
                            resumed on the key, its first turn fails with the
                            API's own "could not be verified", as a real one
                            might (billing.py says why that is not known)
    BILLING                 say who is paying: the subscription, or the key and
                            whether its own shell can see the key - never the key

Who pays is read the way the real one decides it: the run's own provider on
the command line (``-c model_provider="one-openai-api"``) is the OpenAI API key,
read from ``OPENAI_API_KEY``, and anything else is the subscription. ``resume
<session> <prompt>`` carries on the conversation in that session's file, as
``codex resume`` does, and fails at once when there is no such session.

Two things are deliberately different from ``fake_claude.py``, because they are
different in the real pair:

* every shell call arrives as ``tool_name`` ``"Bash"`` with ``tool_input``
  ``{"command": ...}``, which is what Codex sends although its own tool is
  ``exec_command`` and takes a ``cmd``;
* ``tool_response`` on PostToolUse is a plain string, not an object.

Only the standard library, and nothing newer than Python 3.9.
"""
import json
import os
import select
import signal
import subprocess
import sys
import termios
import time
import tty
import uuid

ARGS = sys.argv[1:]
if ARGS[:1] in (["login"], ["logout"], ["exec"]):
    # Codex's sign-in commands, and the one-prompt check after a sign-in (fake_codex_login.py).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fake_codex_login

    sys.exit(fake_codex_login.main(ARGS))
#: The exit code Codex gives when SIGTERM ends it, as Claude Code does: 128 + 15.
TERM_EXIT = 143


def hook_settings(args):
    """The hooks off the command line: every ``-c hooks.<Event>=<toml>``.

    Only the shape the program writes is read, which is one command hook per
    event: this is a stand-in, not a TOML parser.
    """
    hooks = {}
    for i, a in enumerate(args):
        if a != "-c" or i + 1 >= len(args):
            continue
        setting = args[i + 1]
        if not setting.startswith("hooks."):
            continue
        event, _, value = setting[len("hooks."):].partition("=")
        command = _between(value, 'command=', ',timeout=')
        timeout = _between(value, ',timeout=', '}]')
        if command is None:
            continue
        hooks[event] = {"command": json.loads(command), "timeout": int(timeout or 60)}
    return hooks


def _between(text, start, end):
    i = text.find(start)
    if i < 0:
        return None
    i += len(start)
    j = text.find(end, i)
    return text[i:j] if j >= 0 else text[i:]


def override(args, key):
    """A ``-c key=value`` config override off the command line, unquoted.

    Codex parses the value as TOML and falls back to the raw string, so a
    string written the way the program writes one, ``"xhigh"``, reads here as
    JSON, and anything else is taken as it stands.
    """
    for i, a in enumerate(args):
        if a != "-c" or i + 1 >= len(args):
            continue
        name, _, value = args[i + 1].partition("=")
        if name != key:
            continue
        try:
            return json.loads(value)
        except ValueError:
            return value
    return None


def flag(args, name, default=None):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return default


def positional(args):
    """The prompt: the last argument that is not a flag or a flag's value."""
    valued = {"-c", "--model", "--sandbox", "--ask-for-approval", "-C", "--cd", "-m", "-s", "-a"}
    rest, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in valued:
            skip = True
        elif not a.startswith("-"):
            rest.append(a)
    return rest


HOOKS = hook_settings(ARGS)
#: ``codex resume <session> [prompt]``: the same conversation, carried on.
RESUMED = bool(ARGS) and ARGS[0] == "resume"
_WORDS = positional(ARGS[1:] if RESUMED else ARGS)
SESSION = _WORDS[0] if RESUMED and _WORDS else str(uuid.uuid4())
TURN = {"id": str(uuid.uuid4())}
CWD = os.getcwd()
#: Where Codex keeps a session's transcript: under ~/.codex/sessions, which is
#: where the program reads it from for the Read tab (one/transcripts.py).
TRANSCRIPT = os.path.join(os.environ.get("HOME", "/tmp"), ".codex", "sessions", "fake",
                          "rollout-" + SESSION + ".jsonl")
os.makedirs(os.path.dirname(TRANSCRIPT), exist_ok=True)
if RESUMED:
    PROMPT = _WORDS[1] if len(_WORDS) > 1 else ""
else:
    PROMPT = (_WORDS or [""])[-1]
#: Who pays: the run's own provider is the OpenAI API key, anything else the
#: ChatGPT subscription Codex is logged in with.
ON_KEY = override(ARGS, "model_provider") == "one-openai-api"
#: What the model's own shell commands are given instead of the key.
SHELL_SET = override(ARGS, "shell_environment_policy.set")
#: "danger-full-access" is Codex's own checks off, the way the program starts it
#: with full access.
SANDBOX = flag(ARGS, "--sandbox") or flag(ARGS, "-s") or "workspace-write"
MODE = "bypassPermissions" if SANDBOX == "danger-full-access" else "default"
#: How hard this run was told to think: `-c model_reasoning_effort=`, which is
#: the only way Codex takes the level. None means nothing was asked for.
EFFORT = override(ARGS, "model_reasoning_effort")
#: Set by NOHOOKS: the run stops asking, as an untrusted real Codex does.
SILENT = {"on": False}
PENDING = bytearray()


def out(text):
    sys.stdout.write(text.replace("\n", "\r\n"))
    sys.stdout.flush()


def hook(event, **fields):
    """Send one hook, wait for the answer, and return it."""
    handler = HOOKS.get(event)
    if not handler:
        return {}
    body = {"session_id": SESSION, "transcript_path": TRANSCRIPT, "cwd": CWD,
            "hook_event_name": event, "model": flag(ARGS, "--model") or "fake",
            "permission_mode": MODE}
    if event not in ("SessionStart", "SessionEnd"):
        body["turn_id"] = TURN["id"]
    body.update(fields)
    try:
        p = subprocess.run(["sh", "-c", handler["command"]], input=json.dumps(body),
                           capture_output=True, text=True, timeout=handler["timeout"] + 5)
        return json.loads(p.stdout) if p.stdout.strip() else {}
    except Exception as exc:
        out("[hook %s failed: %s]\n" % (event, type(exc).__name__))
        return {}


def on_term(*_):
    hook("SessionEnd", reason="other")
    os._exit(TERM_EXIT)


def transcript(text):
    """What it said, as Codex 0.154 records a message of its own."""
    record({"type": "response_item", "payload": {
        "type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": text}]}})


def record(line):
    with open(TRANSCRIPT, "a") as fh:
        fh.write(json.dumps(line) + "\n")


def asked(text):
    """What it was asked, as Codex records the person's message."""
    record({"type": "response_item", "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})


def turn_over(said=None, error=None):
    """The end of a turn in the session file: ``task_complete``, as 0.154 writes it."""
    payload = {"type": "task_complete", "turn_id": TURN["id"], "last_agent_message": said}
    if error:
        payload["error"] = error
    record({"type": "event_msg", "payload": payload})


def first_asked():
    """The first thing this conversation was asked, out of its own file."""
    try:
        with open(TRANSCRIPT) as fh:
            for line in fh:
                r = json.loads(line)
                p = r.get("payload") or {}
                if p.get("type") == "message" and p.get("role") == "user":
                    return p["content"][0]["text"]
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return ""


def in_file(word):
    try:
        with open(TRANSCRIPT) as fh:
            return word in fh.read()
    except OSError:
        return False


#: The turns this process has run, so the first one after a resume is known.
TURNS = {"n": 0}


def failed(info, message):
    """A turn Codex could not run: written down, shown, and no Stop hook."""
    turn_over(error={"message": message, "codex_error_info": info})
    out("\n\u25a0 %s\n" % message)


def billing_words():
    if not ON_KEY:
        seen = "set" if os.environ.get("OPENAI_API_KEY") else "not set"
        return "billing: ChatGPT subscription (OPENAI_API_KEY %s in my environment)" % seen
    key = os.environ.get("OPENAI_API_KEY") or ""
    shell = subprocess.run("printf %s \"$OPENAI_API_KEY\" | wc -c", shell=True,
                           capture_output=True, text=True, env=shell_env()).stdout.strip()
    return ("billing: OpenAI API key (%d characters in my environment; my shell sees %s "
            "characters of it)" % (len(key), shell or "0"))


def tool(command, act):
    """One shell call, as Codex sends it: the name Bash, the field command."""
    call = "call_" + uuid.uuid4().hex[:16]
    tool_input = {"command": command}
    if not SILENT["on"]:
        answer = hook("PreToolUse", tool_name="Bash", tool_input=tool_input, tool_use_id=call)
        decision = (answer.get("hookSpecificOutput") or {}).get("permissionDecision", "allow")
        if decision == "deny":
            why = (answer.get("hookSpecificOutput") or {}).get("permissionDecisionReason", "")
            out("  Refused: %s\n" % why)
            return "refused: %s" % why
    result, ok = act()
    hook("PostToolUse", tool_name="Bash", tool_input=tool_input, tool_use_id=call,
         tool_response=result if ok else "error: " + result)
    out("  Bash: %s\n" % result.strip()[:200])
    return result


def shell_env():
    """What a command the model runs is given. The key is blanked the way the
    real one blanks it, by the ``shell_environment_policy.set`` it was told."""
    env = dict(os.environ)
    if isinstance(SHELL_SET, str) and "OPENAI_API_KEY" in SHELL_SET:
        env["OPENAI_API_KEY"] = ""
    return env


def bash(command):
    def act():
        p = subprocess.run(command, shell=True, cwd=CWD, capture_output=True, text=True,
                           env=shell_env())
        return (p.stdout + p.stderr), p.returncode == 0
    return tool(command, act)


def write(path, text):
    full = os.path.join(CWD, path)

    def act():
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w") as fh:
            fh.write(text + "\n")
        return "wrote %s" % path, True
    # Codex has no file-writing tool of its own: it writes through the shell,
    # so the program sees a command, as it would from a person at a terminal.
    return tool("write %s" % full, act)


def read_escape():
    """The rest of an escape sequence, once the escape itself has been read."""
    seq = bytearray()
    while True:
        if not select.select([0], [], [], 0.2)[0]:
            return bytes(seq)
        ch = os.read(0, 1)
        if not ch:
            return bytes(seq)
        seq.extend(ch)
        if len(seq) == 1 and ch not in b"[O":
            return bytes(seq)
        if len(seq) > 1 and 0x40 <= ch[0] <= 0x7E:
            return bytes(seq)


def read_line():
    """A line typed at the prompt, the way Codex's own prompt box reads one.

    The program sends a message as Ctrl-E, Ctrl-U, a bracketed paste and
    Enter, so all four are read here, or a message arrives in pieces or not at
    all. The newlines inside a paste belong to the message: a multi-line brief
    sent as several Enters would be several half-messages.
    """
    if not os.isatty(0):
        time.sleep(3600)
        return ""
    line = bytearray(PENDING)
    PENDING.clear()
    ctrl_c, pasting = 0.0, False
    while True:
        if not select.select([0], [], [], 0.2)[0]:
            continue
        ch = os.read(0, 1)
        if not ch:
            return ""
        if ch == b"\x1b":
            seq = read_escape()
            if seq == b"[200~":
                pasting = True
            elif seq == b"[201~":
                pasting = False
            continue
        if ch == b"\x03":
            if time.time() - ctrl_c < 2.0:
                hook("SessionEnd", reason="other")
                os._exit(0)
            ctrl_c = time.time()
            out("\n[Press Ctrl-C again to exit]\n")
            continue
        if ch == b"\x15":            # Ctrl-U: clear the line
            line.clear()
            continue
        if ch == b"\x05":            # Ctrl-E: to the end of the line
            continue
        if ch in (b"\r", b"\n"):
            out("\n")
            if pasting:
                line.extend(b"\n")
                continue
            return line.decode("utf-8", "replace")
        if ch in (b"\x7f", b"\x08"):
            line[-1:] = b""
            out("\b \b")
            continue
        line.extend(ch)
        out(ch.decode("utf-8", "replace"))


def work(prompt):
    said, again = None, False
    TURN["id"] = str(uuid.uuid4())
    TURNS["n"] += 1
    asked(prompt)
    if ON_KEY and not os.environ.get("OPENAI_API_KEY"):
        failed("other", "Missing environment variable: `OPENAI_API_KEY`.")
        return
    if ON_KEY and RESUMED and TURNS["n"] == 1 and in_file("NOCARRY"):
        failed("other", '{"error":{"message":"The encrypted content could not be verified.",'
                        '"type":"invalid_request_error","code":"invalid_encrypted_content"}}')
        return
    while True:
        for line in prompt.splitlines():
            line = line.strip()
            # The subscription gives out between one request and the next, so
            # whatever came before it in the turn has already been done.
            if line == "LIMIT" and not ON_KEY:
                failed("usage_limit_exceeded", "You've hit your usage limit. Visit "
                       "https://chatgpt.com/codex/settings/usage to purchase more credits "
                       "or try again at 11:43 AM.")
                return
            if line == "UNAUTH" and not ON_KEY:
                failed("unauthorized", "Your access token could not be refreshed. Please "
                                       "log out and sign in again.")
                return
            if line.startswith("RUN: "):
                bash(line[5:])
            elif line.startswith("WRITE: "):
                path, _, text = line[7:].partition(" ")
                write(path, text)
            elif line.startswith("COMMIT: "):
                bash("git add -A && git commit -q -m %s" % json.dumps(line[8:]))
            elif line.startswith("SAY: "):
                said = line[5:]
            elif line.startswith("WAIT: "):
                time.sleep(float(line[6:]))
            elif line.startswith("CRASH: "):
                sys.exit(int(line[7:]))
            elif line == "EFFORT":
                said = "reasoning effort: %s" % (EFFORT or "not set")
            elif line == "NOHOOKS":
                SILENT["on"] = True
            elif line == "BILLING":
                said = billing_words()
        if not said and RESUMED:
            said = ("Carried on in session %s, which began with: %s"
                    % (SESSION[:8], first_asked().strip().splitlines()[0][:80]
                       if first_asked().strip() else "nothing"))
        said = said or "I read: %s" % prompt.strip()[:120]
        transcript(said)
        turn_over(said)
        out("\n%s\n" % said)
        answer = hook("Stop", last_assistant_message=said, stop_hook_active=again)
        if answer.get("decision") == "block" and answer.get("reason"):
            prompt, said, again = answer["reason"], None, True
            out("\n[carrying on]\n")
            continue
        return


def main():
    # The terminal goes into raw mode once and stays there, as Codex's own
    # does. Doing it per prompt leaves a gap in which the line discipline,
    # not this program, reads the Ctrl-U the program sends before a message.
    old = None
    if os.isatty(0):
        old = termios.tcgetattr(0)
        tty.setraw(0)
    signal.signal(signal.SIGTERM, on_term)
    try:
        _session(old)
    finally:
        if old is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, old)


def _session(_old):
    if RESUMED and not os.path.exists(TRANSCRIPT):
        out("ERROR: No saved session found with ID %s.\n" % SESSION)
        sys.exit(1)
    started = hook("SessionStart", source="resume" if RESUMED else "startup")
    context = ((started.get("hookSpecificOutput") or {}).get("additionalContext") or "")
    if context:
        # Codex puts this in front of the model as a developer message. Kept
        # where a test can see it arrived, and nowhere the run's own work is.
        with open(TRANSCRIPT + ".context", "w") as fh:
            fh.write(context)
    if PROMPT:
        hook("UserPromptSubmit", prompt=PROMPT)
        work(PROMPT)
    while True:
        out("\n> ")
        typed = read_line()
        if not typed.strip():
            continue
        hook("UserPromptSubmit", prompt=typed)
        work(typed)


if __name__ == "__main__":
    main()
