"""A stand-in for Claude Code, so the program's tests spend no tokens.

It takes the same arguments the program gives the real one, reads the hooks
from the same settings file, and sends them the same way, with the same
fields, as Claude Code 2.1.263 was watched sending them on 14 September. It
obeys the answers the same way: a refused tool call does not run, and a
follow-up at the end of a turn is carried out in the same turn.

What it "does" is written in its prompts, one instruction per line:

    RUN: <command>          run a shell command, through the Bash tool
    BACKGROUND: <command>   start a command and walk away from it: it is named
                            in every Stop hook from then on, the way Claude
                            Code names what `run_in_background` started and
                            has not been waited for
    HELPER: <secs> <name>   start a helper, as a sub-agent run in the
                            background: named in every Stop hook while it
                            runs, and when it finishes, <secs> later, the
                            session is prompted again by itself with a task
                            notification, as Claude Code does
    ONWAKE: <line>          a line the next such notification carries out,
                            such as ONWAKE: COMMIT: done
    WAKEUP: <secs> <prompt> schedule a wake-up, named in every Stop hook's
                            session_crons until it fires and prompts the
                            session with <prompt>
    WRITE: <path> <text>    write a file, through the Write tool
    COMMIT: <message>       git add -A and commit, through the Bash tool
    SAY: <text>             what its last message says; several SAY lines are
                            several lines of it, in order
    WAIT: <seconds>         think for a while
    ASK: <question>         ask on its own screen, and wait for a line typed
    CRASH: <code>           exit at once with that code
    LINES: <n>              print n numbered lines, "line 01" onwards
    FULLSCREEN              draw on the full screen from now on, as Claude Code
                            2.1.263 does: it asks for the mouse, shows the end
                            of what it printed, and scrolls back through all of
                            it when told of the wheel; a click is said where it
                            was, and letting go copies, with OSC 52
    TIDYING: <seconds>      after the turn has ended, spend that long putting
                            the session away, as Claude Code does. A Ctrl-C in
                            that time stops the tidying and is used up: it does
                            not count towards the two presses that make it leave
    DEAF                    stop listening for Ctrl-C from now on, so only
                            SIGTERM can end it

Anything else is answered "I read: ...". Between turns it sits at a prompt
reading the keyboard the way Claude Code does: letters, a paste in bracketed
markers, Enter to send, Ctrl-E and Ctrl-U to clear the line, and Ctrl-C twice
to leave.

Only the standard library, and nothing newer than Python 3.9.
"""
import base64
import json
import os
import re
import select
import signal
import subprocess
import sys
import termios
import time
import tty
import urllib.request
import uuid


def arg_value(args, name):
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return None


ARGS = sys.argv[1:]
SETTINGS = json.load(open(arg_value(ARGS, "--settings")))
SESSION = arg_value(ARGS, "--session-id") or arg_value(ARGS, "--resume") or str(uuid.uuid4())
#: "bypassPermissions" never asks on its own screen, as Claude Code does in it.
MODE = arg_value(ARGS, "--permission-mode") or "default"
CWD = os.getcwd()
#: Where Claude Code keeps a session's transcript: a folder under
#: ~/.claude/projects named after the working folder, every character that is
#: not a letter or a digit made a dash, and a file named after the session.
#: The program reads it from there for the Read tab (one/transcripts.py), and
#: will read nothing that is anywhere else.
TRANSCRIPT = os.path.join(os.environ.get("HOME", "/tmp"), ".claude", "projects",
                          re.sub(r"[^A-Za-z0-9]", "-", CWD), SESSION + ".jsonl")
os.makedirs(os.path.dirname(TRANSCRIPT), exist_ok=True)
#: The flags that take a value, so a value is never mistaken for the prompt.
VALUED = {"--settings", "--permission-mode", "--model", "--name", "--debug-file", "--resume",
          "--session-id", "--append-system-prompt", "--effort"}


def positional(args):
    rest, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in VALUED:
            skip = True
        elif not a.startswith("--"):
            rest.append(a)
    return rest


PROMPT = (positional(ARGS) or [""])[-1]
APPENDED = arg_value(ARGS, "--append-system-prompt") or ""


#: What it printed, line by line, and how far back the full screen is scrolled.
FULL = {"on": False, "lines": [""], "back": 0}

#: Keys that arrived while it was busy and were not Ctrl-C. read_line takes
#: these before it reads the terminal again, so nothing typed is lost.
PENDING = bytearray()
#: Set by DEAF: Ctrl-C is read and thrown away, so only a signal ends it.
DEAF = {"on": False}
#: The exit code Claude Code gives when SIGTERM ends it: 128 + 15.
TERM_EXIT = 143
#: And when a hangup ends it: 128 + 1. A machine going down sends SIGHUP to
#: whatever is in a terminal it is tearing down, and Claude Code answers it
#: the way it answers SIGTERM: it closes the session and exits with the
#: number. So a run killed by a reboot ends `exited`, with a code and no
#: signal, which is exactly how run 76a0d438 ended on 22 September 2026.
#: Until this was here the stand-in had no handler and simply died on the
#: signal, so no world in this repository could make that shape happen.
HUP_EXIT = 129
#: The two stopping signals this stand-in answers, and the code each leaves.
#: Both are "something stopped it" rather than "it broke", which is the whole
#: distinction `one.views.ended_state` turns into a colour.
STOP_EXIT = {int(signal.SIGTERM): TERM_EXIT, int(signal.SIGHUP): HUP_EXIT}


def eaten_ctrl_c():
    """Whether Ctrl-C arrived while it was busy, and using it up if it did.

    Claude Code answers Ctrl-C during a turn by stopping what it is doing, and
    that press is used up: it does not count towards the two presses that make
    it leave, and the prompt never sees it. The program stops a run by pressing
    twice half a second apart, and on 16 September 2026 the first press landed
    inside the tidying that follows a turn on a machine at 96% of its
    processor. Only the second reached the prompt, which armed "Press Ctrl-C
    again to exit" and nothing more, so the session stayed open until SIGTERM
    took the terminal away and it exited 143 - and six finished runs were
    called failed.
    """
    hit = False
    while os.isatty(0) and select.select([0], [], [], 0)[0]:
        ch = os.read(0, 1)
        if not ch:
            break
        if ch == b"\x03":
            hit = True
        else:
            PENDING.extend(ch)
    return hit


def on_stop(signum, *_):
    """A stopping signal, as Claude Code answers one.

    The session is put away and the process exits 128 plus the signal's own
    number, which is how a stopped run is told apart from a broken one:
    SIGTERM leaves TERM_EXIT and a hangup leaves HUP_EXIT, and neither of them
    is the run's own doing.
    """
    hook("SessionEnd", reason="other")
    out("\nResume this session with:\n")
    os._exit(STOP_EXIT.get(int(signum), 128 + int(signum)))


def out(text):
    lines = FULL["lines"]
    for ch in text:
        if ch == "\n":
            lines.append("")
        elif ch == "\b":
            lines[-1] = lines[-1][:-1]
        elif ch != "\r":
            lines[-1] += ch
    if FULL["on"]:
        draw()
    else:
        sys.stdout.write(text.replace("\n", "\r\n"))
        sys.stdout.flush()


def draw():
    """The full screen: the end of what it printed, or further back when scrolled."""
    try:
        cols, rows = os.get_terminal_size(1)
    except OSError:
        cols, rows = 80, 24
    lines = FULL["lines"]
    FULL["back"] = max(0, min(FULL["back"], len(lines) - rows))
    end = len(lines) - FULL["back"]
    shown = lines[max(0, end - rows):end]
    sys.stdout.write("\x1b[H\x1b[2J" + "".join(
        f"\x1b[{i + 1};1H{line[:cols]}" for i, line in enumerate(shown)))
    sys.stdout.flush()


def fullscreen():
    FULL["on"] = True
    signal.signal(signal.SIGWINCH, lambda *_: draw())
    sys.stdout.write("\x1b[?1049h\x1b[?1000h\x1b[?1002h\x1b[?1003h\x1b[?1006h\x1b[?2004h")
    draw()


def hook(event, **fields):
    """Send one hook, wait for the answer, and return it."""
    entries = SETTINGS.get("hooks", {}).get(event) or []
    answer = {}
    for group in entries:
        for h in group.get("hooks", []):
            body = {"session_id": SESSION, "transcript_path": TRANSCRIPT, "cwd": CWD,
                    "hook_event_name": event, "permission_mode": MODE,
                    "prompt_id": str(uuid.uuid4())}
            body.update(fields)
            if h.get("type") == "command":
                # As Claude Code runs a command hook: the payload on its input.
                try:
                    p = subprocess.run(["sh", "-c", h["command"]], input=json.dumps(body),
                                       capture_output=True, text=True, timeout=h.get("timeout", 60))
                    answer = json.loads(p.stdout) if p.stdout.strip() else {}
                except Exception as exc:
                    out(f"[hook {event} failed: {type(exc).__name__}]\n")
                continue
            request = urllib.request.Request(h["url"], data=json.dumps(body).encode(),
                                             headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(request, timeout=h.get("timeout", 60)) as r:
                    text = r.read().decode() or "{}"
                answer = json.loads(text) if text.strip() else {}
            except Exception as exc:  # a hook that fails is not fatal, as in Claude Code
                out(f"[hook {event} failed: {type(exc).__name__}]\n")
    return answer


def record(kind, content, **fields):
    """One record of the transcript, in the shape Claude Code 2.1.280 writes."""
    body = {"parentUuid": None, "isSidechain": False, "type": kind,
            "message": {"role": kind, "content": content},
            "uuid": str(uuid.uuid4()), "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            "cwd": CWD, "sessionId": SESSION}
    body.update(fields)
    with open(TRANSCRIPT, "a") as fh:
        fh.write(json.dumps(body) + "\n")


def transcript(text):
    """What it said, as an assistant message of the transcript."""
    record("assistant", [{"type": "text", "text": text}])


def prompted(text, meta=False):
    """What it was asked, as the person's message of the transcript. The
    program's follow-up at the end of a turn is written as Claude Code writes
    a Stop hook's reason: a message of its own, marked as not the person's."""
    if meta:
        record("user", "Stop hook feedback:\n" + text, isMeta=True)
    else:
        record("user", text)


#: What the next tool call leaves out, to test what the program does when a
#: hook never arrives, as seen on the server on 14 September: "pre" skips
#: PreToolUse, so the call reaches the program only through PermissionRequest;
#: "all" skips both, as a read-only command Claude Code allows by itself does.
SKIP = {"next": None}


def tool(name, tool_input, act):
    call = "toolu_01" + uuid.uuid4().hex[:22]
    record("assistant", [{"type": "tool_use", "id": call, "name": name, "input": tool_input}])
    result = run_tool(call, name, tool_input, act)
    ok = not result.startswith("refused")
    record("user", [{"type": "tool_result", "tool_use_id": call, "content": result,
                     "is_error": not ok or TOOL_FAILED.pop("failed", False)}])
    return result


#: Whether the last tool call's command failed, for its result in the transcript.
TOOL_FAILED = {}


def run_tool(call, name, tool_input, act):
    skip, SKIP["next"] = SKIP["next"], None
    if skip is None:
        answer = hook("PreToolUse", tool_name=name, tool_input=tool_input, tool_use_id=call)
        decision = (answer.get("hookSpecificOutput") or {}).get("permissionDecision", "ask")
    elif skip == "all":
        decision = "allow"
    else:
        decision = "ask"
    if decision == "deny":
        why = (answer.get("hookSpecificOutput") or {}).get("permissionDecisionReason", "")
        out(f"  Refused: {why}\n")
        return f"refused: {why}"
    if decision == "ask" and MODE == "bypassPermissions":
        decision = "allow"
    if decision == "ask" and SETTINGS.get("hooks", {}).get("PermissionRequest"):
        # About to ask on its own screen: the PermissionRequest hook first.
        answer = hook("PermissionRequest", tool_name=name, tool_input=tool_input,
                      permission_suggestions=[])
        behaviour = ((answer.get("hookSpecificOutput") or {}).get("decision") or {}).get("behavior")
        if behaviour == "deny":
            why = ((answer.get("hookSpecificOutput") or {}).get("decision") or {}).get("message", "")
            out(f"  Refused: {why}\n")
            return f"refused: {why}"
        if behaviour == "allow":
            decision = "allow"
    if decision != "allow":
        # What Claude Code does when no hook decided: ask on its own screen,
        # and a few seconds later send a notification that it is waiting.
        out(f"  [{name} needs permission on this screen: y/n] ")
        hook("Notification", notification_type="permission_prompt",
             message=f"Claude needs your permission to use {name}")
        line = read_line()
        if line.strip().lower() != "y":
            return "refused on screen"
    started = time.time()
    result, ok = act()
    if not ok:
        TOOL_FAILED["failed"] = True
    hook("PostToolUse", tool_name=name, tool_input=tool_input, tool_use_id=call,
         duration_ms=int((time.time() - started) * 1000),
         tool_response={"stdout": result} if ok else {"is_error": True, "stderr": result})
    out(f"  {name}: {result.strip()[:200]}\n")
    return result


def bash(command):
    def act():
        p = subprocess.run(command, shell=True, cwd=CWD, capture_output=True, text=True)
        return (p.stdout + p.stderr), p.returncode == 0
    return tool("Bash", {"command": command, "description": command[:40]}, act)


def write(path, text):
    def act():
        full = os.path.join(CWD, path)
        os.makedirs(os.path.dirname(full) or ".", exist_ok=True)
        with open(full, "w") as fh:
            fh.write(text + "\n")
        return f"wrote {path}", True
    return tool("Write", {"file_path": os.path.join(CWD, path), "content": text}, act)


#: Commands started and not waited for, named in every Stop hook from then on.
BACKGROUND = []
#: Helpers and wake-ups still to come back: [when, what, the prompt it brings].
LATER = []
#: Lines the next helper's notification carries out.
ONWAKE = []


class Woken(Exception):
    """Something the session started came back while it sat at its prompt."""

    def __init__(self, prompt):
        super().__init__(prompt)
        self.prompt = prompt


def in_flight():
    """What a Stop hook names: the background work and the scheduled wake-ups."""
    tasks = list(BACKGROUND) + [{"id": f"t{i}", "type": "subagent", "status": "running",
                                 "description": what}
                                for i, (_, what, _, kind) in enumerate(LATER) if kind == "helper"]
    crons = [{"id": f"c{i}", "schedule": "* * * * *", "recurring": False, "prompt": prompt}
             for i, (_, _, prompt, kind) in enumerate(LATER) if kind == "cron"]
    return tasks, crons


def next_woken():
    """The prompt of whatever is due, or None, and how long until the next."""
    if not LATER:
        return None, None
    LATER.sort(key=lambda x: x[0])
    when, what, prompt, kind = LATER[0]
    left = when - time.time()
    if left > 0:
        return None, left
    LATER.pop(0)
    return prompt, 0


def work(prompt):
    """Carry out one prompt, then end the turn, doing any follow-up the Stop hook gives."""
    said = None
    again = False
    tidying = 0.0
    while True:
        prompted(prompt, meta=again)
        for line in prompt.splitlines():
            line = line.strip()
            if line.startswith("RUN: "):
                bash(line[5:])
            elif line.startswith("BACKGROUND: "):
                BACKGROUND.append({"description": line[12:], "status": "running"})
            elif line.startswith("HELPER: "):
                secs, _, what = line[8:].partition(" ")
                lines = "\n".join(ONWAKE) or f"SAY: The helper {what} reported."
                ONWAKE.clear()
                LATER.append([time.time() + float(secs), what,
                              f"<task-notification>Agent \"{what}\" finished</task-notification>\n"
                              + lines, "helper"])
            elif line.startswith("ONWAKE: "):
                ONWAKE.append(line[8:])
            elif line.startswith("WAKEUP: "):
                secs, _, then = line[8:].partition(" ")
                LATER.append([time.time() + float(secs), "wake-up", then, "cron"])
            elif line.startswith("WRITE: "):
                path, _, text = line[7:].partition(" ")
                write(path, text)
            elif line.startswith("COMMIT: "):
                bash(f"git add -A && git commit -q -m {json.dumps(line[8:])}")
            elif line.startswith("SAY: "):
                said = f"{said}\n{line[5:]}" if said else line[5:]
            elif line.startswith("WAIT: "):
                time.sleep(float(line[6:]))
            elif line.startswith("ASK: "):
                hook("Notification", notification_type="permission_prompt", message=line[5:])
                out(f"  ? {line[5:]} ")
                said = f"You answered: {read_line()}"
            elif line.startswith("CRASH: "):
                sys.exit(int(line[7:]))
            elif line.startswith("LINES: "):
                out("".join(f"line {i:02d}\n" for i in range(1, int(line[7:]) + 1)))
            elif line == "FULLSCREEN":
                fullscreen()
            elif line.startswith("TIDYING: "):
                tidying = float(line[9:])
            elif line == "DEAF":
                DEAF["on"] = True
            elif line == "SKIPHOOK":
                SKIP["next"] = "pre"
            elif line == "NOHOOK":
                SKIP["next"] = "all"
            elif line == "NOSTOP":
                SKIP["stop"] = True
        said = said or f"I read: {prompt.strip()[:120]}"
        transcript(said)
        out(f"\n{said}\n")
        if SKIP.pop("stop", None):
            # As when the Stop hook is lost: Claude Code only says, later, that
            # it is waiting for input.
            hook("Notification", notification_type="idle_prompt",
                 message="Claude is waiting for your input")
            return
        tasks, crons = in_flight()
        answer = hook("Stop", last_assistant_message=said, stop_hook_active=again,
                      background_tasks=tasks, session_crons=crons)
        if answer.get("decision") == "block" and answer.get("reason"):
            prompt, said, again = answer["reason"], None, True
            out("\n[carrying on]\n")
            continue
        # Putting the session away, as Claude Code writes its skills and its
        # config after a turn. The program closes a run the moment its turn
        # ends, so this is exactly where its first Ctrl-C lands, and here as
        # there that press is used up.
        settle = time.time() + tidying
        while time.time() < settle:
            if eaten_ctrl_c():
                out("\n  Interrupted\n")
                break
            time.sleep(0.05)
        return


def read_escape():
    """The rest of an escape sequence after its ESC: a CSI up to its last
    byte, with the three bytes of the mouse in its old form, or one byte."""
    first = os.read(0, 1)
    if first != b"[":
        return first + (os.read(0, 1) if first == b"O" else b"")
    seq = b"["
    while True:
        ch = os.read(0, 1)
        if not ch:
            return seq
        seq += ch
        if seq == b"[M":
            rest = b""
            while len(rest) < 3:
                more = os.read(0, 3 - len(rest))
                if not more:
                    break
                rest += more
            return seq + rest
        if 0x40 <= ch[0] <= 0x7E:
            return seq


#: The pictures Claude Code attaches when their path is pasted at its prompt.
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp")

#: How many it has attached this session, which is the number it shows.
ATTACHED = {"n": 0}


def as_attachments(text):
    """A pasted line with every image path in it replaced by [Image #N].

    This is the one thing a run's terminal relies on that a stand-in could
    easily get wrong by being too kind. Claude Code attaches a picture only
    when its path arrives as a *paste*: measured against Claude Code 2.1.263
    on 16 September, the same path sent key by key stays a path on the screen
    and the picture never reaches the model, which is exactly the fault a
    dropped file had that day (D52). So the distinction lives here, and a
    test that drops a file can tell the two apart.
    """
    out = []
    for word in text.split(" "):
        bare = word.strip("'\"")
        if bare.lower().endswith(IMAGES) and os.path.isabs(bare) and os.path.exists(bare):
            ATTACHED["n"] += 1
            out.append(f"[Image #{ATTACHED['n']}]")
        else:
            out.append(word)
    return " ".join(out)


def read_line():
    """One line from the keyboard, the way a prompt box reads it."""
    buf = []
    pasting = False
    pasted = []
    ctrl_c = 0.0
    while True:
        if PENDING:
            ch = bytes(PENDING[:1])
            del PENDING[:1]
        else:
            if not buf and not pasting:
                # Sitting at the prompt: whatever it started may come back first.
                due, left = next_woken()
                if due is not None:
                    raise Woken(due)
                if left is not None and not select.select([0], [], [], left)[0]:
                    continue
            ch = os.read(0, 1)
        if not ch:
            raise EOFError
        if ch == b"\x1b":
            seq = read_escape()
            if seq == b"[200~":
                pasting = True
                pasted = []
            elif seq == b"[201~":
                pasting = False
                shown = as_attachments(b"".join(pasted).decode("utf-8", "replace"))
                buf.append(shown.encode("utf-8"))
                out(shown.replace("\r", "\n"))
            elif seq.startswith(b"[<") and FULL["on"]:
                # The mouse, in the form 1006: the wheel scrolls the full screen,
                # a press of the first button is said where it was, and letting
                # it go copies, as the fullscreen renderer copies a selection.
                fields = seq[2:-1].split(b";")
                button, where = fields[0], b",".join(fields[1:]).decode()
                if button in (b"64", b"65"):
                    FULL["back"] += 1 if button == b"64" else -1
                    draw()
                elif button == b"0" and seq.endswith(b"M"):
                    out(f"clicked {where}\n")
                elif button == b"0" and seq.endswith(b"m"):
                    copied = base64.b64encode(f"copied at {where}".encode()).decode()
                    sys.stdout.write(f"\x1b]52;c;{copied}\x07")
                    sys.stdout.flush()
            continue
        if ch == b"\x03":
            if DEAF["on"]:
                continue
            if time.time() - ctrl_c < 2.0:
                raise KeyboardInterrupt
            ctrl_c = time.time()
            buf = []
            out("\n  Press Ctrl-C again to exit\n> ")
            continue
        if ch in (b"\x05",):
            continue
        if ch == b"\x15":
            buf = []
            continue
        if ch in (b"\r", b"\n") and not pasting:
            out("\n")
            return b"".join(buf).decode("utf-8", "replace")
        if pasting:
            # Held back until the paste ends: what it says on the screen
            # depends on the whole of it, not on each character as it lands.
            pasted.append(ch)
            continue
        if ch == b"\x7f":
            if buf:
                buf.pop()
                out("\b \b")
            continue
        buf.append(ch)
        out(ch.decode("utf-8", "replace") if ch not in (b"\r", b"\n") else "\n")


def main():
    old = None
    if os.isatty(0):
        old = termios.tcgetattr(0)
        tty.setraw(0)
    for sig in STOP_EXIT:
        signal.signal(sig, on_stop)
    try:
        hook("SessionStart", source="startup")
        out(f"Fake Claude Code, session {SESSION[:8]}\n")
        if APPENDED:
            out("(told the one program's instructions for this session)\n")
            # Kept where a check can read what arrived, as the stand-in for
            # Codex keeps its SessionStart context.
            with open(TRANSCRIPT + ".appended", "w") as fh:
                fh.write(APPENDED)
        if PROMPT:
            hook("UserPromptSubmit", prompt=PROMPT)
            work(PROMPT)
        while True:
            out("> ")
            try:
                line = read_line()
            except Woken as woken:
                line = woken.prompt
                out("\n[woken]\n")
            if not line.strip():
                continue
            hook("UserPromptSubmit", prompt=line)
            work(line)
    except (KeyboardInterrupt, EOFError):
        hook("SessionEnd", reason="prompt_input_exit")
        out("\nbye\n")
    finally:
        if old is not None:
            termios.tcsetattr(0, termios.TCSADRAIN, old)


if __name__ == "__main__":
    main()
