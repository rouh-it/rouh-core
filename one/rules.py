"""What each place may ask the program for, and what a run may do.

Both are written as data and decided in one place, because step 07's point is
that a rule enforced in one place cannot be got round by asking somewhere else.

**What each place may ask for** (``ALLOWED``). Step 07, section 9: "the voice
can start work but can never widen it". A microphone cannot tell who is in the
room, so the voice may start a run, say something to one, answer yes or no,
stop, and take or hand back a run a terminal is watching - and nothing else.
The phone may only answer a question the program asked it. This is a list of
messages each place may send, checked before a message reaches anything, not
an instruction to a model that a clever sentence could talk round.

``say`` reached the voice on 19 September 2026, at the person's word: "I want
to be able to control and communicate with every run from the voice, exactly
as I can with my own background workers." Until then a message could only come
from a terminal or a browser, so a run that asked something out of hours sat
there while the person, who was in the room, could not answer it. It is the
same message a terminal sends and it lands the same way, at the run's own
prompt (``runs.say``); the voice does not gain a keyboard, only a sentence.

**What a run may do** (:func:`decide`). Every tool call Claude Code wants to
make in a run comes to the program first, through its PreToolUse hook, and
gets one of three answers:

``allow``  it goes ahead without asking anyone;
``deny``   it does not happen, and Claude Code is told why, so it can do
           something else;
``ask``    a person is asked, on every surface at once and on the phone, and
           the run waits for the answer.

The rules come from task 36's reading of Simon Willison's rule (16 June 2025):
harm needs a run to hold the person's private data, text written by strangers
and a way to send something out, all three. A workspace run always holds the
first, and can read the second whenever it searches or fetches the web. So the
third is where the line is drawn: a run never logs in elsewhere or reads keys,
and anything that could send data out of the machine is asked about first.

**Pushing is not one of those things, since 19 September 2026.** It was, and
the person said plainly that it should not be: "a change is only done when it
is committed, merged to main AND deployed", with no approval step anywhere in
it. A run that had to ask before pushing ended its turn asking, and the work
sat on a branch nobody merged - run 8921e843 verified a clean merge and then
deliberately did not push, waiting for an approval that was never coming. So a
run may push, and the standing default is that it does: ``agents.PUSH_AND_DEPLOY``
is what every run that saves work to a branch is told. The repository it pushes
to is its own, its credentials are the server's own key, and the work goes to
the branch everything is deployed from, which is where the person wants it.
What follows a change landing on main in the space ``rouh`` is one deploy of
both services on this machine - this program and Rouh, onto that one commit
(``update-all.sh``) - so nothing a run lands can go live in one of them and not
the other. Since 21 September 2026 that deploy is ``land.sh``'s own last step
rather than something that happens afterwards, and it is not reported as done
until both services answer with the commit that was pushed: a commit sitting on
main unserved for six hours is what pushing without deploying looks like.

These are checks on what a call says it will do, and a determined program can
disguise what it does. The hard limits are underneath: a run works as its own
Linux user, in its own checkout, and holds no key the program does not give it.
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Mapping

from one import agents, billing

SURFACES = ("terminal", "browser", "voice", "phone")

#: The messages each place may send. Everything else is refused.
ALLOWED: dict[str, frozenset[str]] = {
    "terminal": frozenset({
        "hello", "ping", "runs", "run", "tree", "tail", "questions", "start", "stop", "say",
        "attach", "detach", "take", "give", "input", "resize", "answer", "pair", "devices",
        "revoke", "resume", "spaces", "add_space", "processes", "transcript", "forget",
        "retitle",
    }),
    # Since D46 a browser types into a run's terminal, as a terminal does: it
    # takes the keyboard, types and gives it back. Since D50 it also sizes the
    # run's terminal to its window, unless another device has the keyboard.
    # Since D51 its mouse reaches a run whose program asks for the mouse, as
    # Claude Code's fullscreen renderer does: the wheel scrolls, and a click and
    # a drag do what they do there. The mouse does not take the keyboard.
    # "archive" puts a run out of the list's way and brings it back; it is the
    # one place a person keeps their own list, so it is the one place that may.
    # Putting one away stops it as well: the person is done with it.
    # "transcript" is the Read tab: the run's own transcript as a conversation,
    # which only reads.
    "browser": frozenset({
        "hello", "ping", "runs", "run", "tree", "tail", "questions", "start", "stop", "say",
        "attach", "detach", "take", "give", "input", "resize", "scroll", "mouse", "answer",
        "archive", "devices", "spaces", "add_space", "processes", "transcript",
    }),
    # "tail", the list as it grows, is how Rouh hears a job it started
    # finish and puts the result on its screen (stage 5); it only reads.
    # "say" is the person talking to a run through Rouh: the same message a
    # terminal sends, landing at the run's own prompt.
    # "codex_key" is Rouh handing over the OpenAI API key its own environment
    # holds, for runs of Codex billed to it (billing.py). Only Rouh's own
    # connection may: a page could otherwise choose whose account is billed.
    # "archive" is the archive button on Rouh's list of runs, passed on by
    # Rouh since 1 October 2026, so a browser the program never paired can
    # still put a run away (fr_e40fdd64f4a8). It stops a run, as "stop" does.
    # "calls" is every tool call a run and its sub-agents made, which Rouh
    # reads to judge what a finished job of an email case did before that
    # case is redone (card 1307, 6 October 2026); it only reads.
    # "claude_signin" is Rouh's page signing the worker's Claude Code in, in
    # the containers only (one/claude_signin.py, 22 October 2026): only Rouh's
    # own connection may, because it decides whose account the runs use.
    # "codex_signin" is the same for Codex and a ChatGPT plan (one/codex_signin.py,
    # 6 November 2026), for the same reason.
    # "shell" is Rouh's read-only shell, run here in the containers, where the
    # program holds no key and Rouh's core holds them all (one/shell.py, 29
    # October 2026): only stages Rouh's own read-only rules allowed.
    "voice": frozenset({
        "hello", "ping", "runs", "run", "tree", "tail", "questions", "start", "stop", "say",
        "answer", "take", "give", "spaces", "codex_key", "archive", "calls", "claude_signin",
        "codex_signin", "shell",
    }),
    "phone": frozenset({"hello", "ping", "answer"}),
}

#: What a run started from each place may be. The voice starts only runs of
#: Claude Code with a brief, and says nothing about them but where they work.
START_FIELDS: dict[str, frozenset[str]] = {
    # "interactive" is the person's own session: Claude Code with no brief,
    # typed to from the terminal that starts it. Only a terminal has hands.
    # "billing" is who pays for a run of Codex (billing.py): the ChatGPT
    # subscription unless the person asks for the OpenAI API key, from any
    # place that may start a run of Codex at all.
    "terminal": frozenset({"brief", "title", "kind", "space", "model", "effort", "task",
                           "interactive", "engine", "expects", "billing"}),
    "browser": frozenset({"brief", "title", "space", "task", "engine", "expects", "billing"}),
    # The voice says which space a run works in since D42: the assistant, or
    # a repository such as Rouh's own code. Since 17 September it may also
    # say Codex, because that is the person asking for one by name. Since 27
    # September it says which model and how deeply, because those are the
    # organisation's defaults in Rouh's Settings (`rouh/modeldefaults.py`).
    # Since 6 October 2026 it may also start the nightly feature run
    # (`rouh/nightly_feature.py`): "signups" says the run may sign up for
    # services and pay through Rouh's tools rather than stopping at that step,
    # and "browser_port" opens its browser to Rouh on that port, so Rouh can
    # fill the vault's card into its checkout. Nothing else may ask for either.
    # Since 15 October 2026 it also says which task the run is for, so the
    # run starts with that task's own record after its agent instructions.
    # Since 2 November 2026 it may hand a run boxes the person named (`rouh/boxes.py`): their
    # numbers and names, and the one-time key the program collects them from Rouh with as the
    # run starts. Never what is in them. Nothing else may hand a run a box.
    "voice": frozenset({"brief", "title", "space", "model", "effort", "engine", "expects",
                        "billing", "signups", "browser_port", "task", "boxes"}),
    "phone": frozenset(),
}

#: A space's name (D42): the assistant, "scratch" for a folder of its own, or
#: a repository added with `one space add`, named by its folder.
SPACE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
KINDS = ("agent", "shell")
#: How hard a run may be asked to think, shallowest first: every word both
#: Claude Code's `--effort` and Codex's `model_reasoning_effort` take.
EFFORTS = ("low", "medium", "high", "xhigh", "max")

#: The most files a run may declare it expects to touch. A declaration is a
#: promise about where the work is, not an inventory of the repository: a run
#: that names two hundred files has said nothing, and would queue everything
#: behind it for ever.
MAX_EXPECTS = 40
#: A path inside the run's own checkout. Never absolute, never upwards, and
#: never a shell glob's worth of the repository on its own.
EXPECTS_PATH = re.compile(r"^[A-Za-z0-9._*][A-Za-z0-9._*/-]{0,200}$")


def expected_files(given: Any) -> list[str]:
    """The files a run says it expects to touch, cleaned up.

    Anything that is not a plain relative path inside the checkout is dropped
    rather than refused: a declaration is the cheap prevention, and a job that
    named one path oddly should still start and still be compared on the others.
    A trailing slash means the folder, which is what a job that is going to work
    in one usually means.
    """
    if isinstance(given, str):
        given = [p for p in re.split(r"[,\n]", given)]
    if not isinstance(given, (list, tuple)):
        return []
    out: list[str] = []
    for item in given:
        path = str(item or "").strip()
        if path.startswith("/"):
            # Absolute. Dropped rather than quietly turned into a relative path:
            # a job that named /etc/passwd did not mean etc/passwd in its own
            # checkout, and silently deciding it did is how a declaration stops
            # meaning anything.
            continue
        path = path.rstrip("/")
        if not path or ".." in path.split("/") or not EXPECTS_PATH.match(path):
            continue
        if path not in out:
            out.append(path)
        if len(out) >= MAX_EXPECTS:
            break
    return out
#: Which agent a run is. Claude Code unless Codex is asked for by name.
ENGINES = agents.ENGINES


class Refused(Exception):
    """A message a place may not send, or a value it may not set."""


def check(surface: str, message_type: str) -> None:
    if message_type not in ALLOWED.get(surface, frozenset()):
        raise Refused(f"{message_type!r} cannot be asked for from the {surface}")


#: The longest brief a run is started with, in characters. A longer one is refused, not cut;
#: one over 32 KB is handed to the agent as a file to read (`agents.first_prompt`).
BRIEF_MOST = 100_000


def start_options(surface: str, msg: Mapping[str, Any]) -> dict[str, Any]:
    """The run a place asked for, with anything it may not set refused, not ignored."""
    allowed = START_FIELDS.get(surface, frozenset())
    given = {k for k in msg if k not in ("t", "id")}
    extra = sorted(given - allowed)
    if extra:
        raise Refused(f"the {surface} cannot set {', '.join(extra)} on a run")
    brief = str(msg.get("brief") or "").strip()
    kind = str(msg.get("kind") or "agent")
    if kind not in KINDS:
        raise Refused(f"there is no kind of run called {kind!r}")
    interactive = bool(msg.get("interactive"))
    if interactive and kind != "agent":
        raise Refused("only Claude Code can be your own session")
    if kind == "agent" and not brief and not interactive:
        raise Refused("a run of Claude Code needs a brief")
    if len(brief) > BRIEF_MOST:
        # Refused, never cut: a brief cut to fit loses its end, which is where a brief keeps
        # what is asked of this one run, and the run is never told (17 October 2026).
        raise Refused(f"the brief is {len(brief):,} characters, and a run takes at most "
                      f"{BRIEF_MOST:,}")
    engine = str(msg.get("engine") or agents.DEFAULT_ENGINE).strip().lower()
    if engine not in ENGINES:
        raise Refused(f"there is no agent called {engine!r}: it is "
                      f"{' or '.join(ENGINES)}")
    if engine != agents.DEFAULT_ENGINE and kind != "agent":
        raise Refused(f"only a run of an agent can be {engine}")
    space = str(msg.get("space") or "assistant").strip().lower()
    if not SPACE_NAME.match(space):
        raise Refused(f"{space!r} is not the name of a space")
    effort = str(msg.get("effort") or "").strip().lower() or None
    if effort is not None and effort not in EFFORTS:
        raise Refused(f"{effort!r} is not how hard a run can think: it is "
                      f"{', '.join(EFFORTS)}")
    try:
        pays = billing.asked_for(engine, msg.get("billing"))
    except ValueError as exc:
        raise Refused(str(exc)) from None
    boxes, box_key = handed_boxes(msg.get("boxes"))
    port = msg.get("browser_port")
    if port not in (None, "", 0):
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            raise Refused(f"{port!r} is not a port a run's browser can listen on")
    return {
        "brief": brief,
        "title": str(msg.get("title") or "").strip()[:120],
        "kind": kind,
        "space": space,
        "model": str(msg.get("model") or "").strip() or None,
        # How hard it thinks, when the place that asked for it says: `claude
        # --effort`, or Codex's `model_reasoning_effort`. None is the
        # program's own level for its agent (`Settings.agent_effort`).
        "effort": effort,
        "engine": engine,
        # Who pays: said on the run only when it is the key, so a run on the
        # subscription is asked for in exactly the words it always was.
        **({"billing": pays} if pays == billing.API else {}),
        "task": str(msg.get("task") or "").strip() or None,
        "interactive": interactive,
        # What it says up front it expects to touch, so the scheduler can queue
        # a run that would collide with one already working instead of starting
        # both and resolving the collision afterwards. The cheap prevention on
        # card 488, and much cheaper than any resolver.
        "expects": expected_files(msg.get("expects")),
        # Said on the run only when asked for, so every other run is asked for
        # in exactly the words it always was.
        **({"signups": True} if msg.get("signups") is True else {}),
        **({"browser_port": port} if port else {}),
        # The boxes handed to it, by number and name; the key is taken off before anything is
        # written down (`runs.Runs.request`) and kept in memory until the run starts.
        **({"boxes": boxes, "box_key": box_key} if boxes else {}),
    }


def handed_boxes(given: Any) -> tuple[list[dict[str, Any]], str]:
    """The boxes a run is handed, ``{"key", "boxes": [{"number", "name"}]}``, checked."""
    if given in (None, "", {}):
        return [], ""
    if not isinstance(given, Mapping):
        raise Refused("boxes are handed to a run as a key and a list")
    key = given.get("key")
    listed = given.get("boxes")
    if not isinstance(key, str) or not 20 <= len(key) <= 200 or not isinstance(listed, list) \
            or not 1 <= len(listed) <= 10:
        raise Refused("boxes are handed to a run as one key and one to ten boxes")
    out = []
    for one in listed:
        number = one.get("number") if isinstance(one, Mapping) else None
        if not isinstance(number, int) or isinstance(number, bool) or not 0 < number < 1_000_000:
            raise Refused(f"{one!r} is not a box a run can be handed")
        out.append({"number": number, "name": " ".join(str(one.get("name") or "").split())[:120]})
    return out, key


# ---------------------------------------------------------------------------
# What a run may do
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    decision: str            # allow, deny or ask
    rule: str                # which rule decided, for the list
    why: str = ""            # said to the person, and to Claude Code on a deny

    def as_dict(self) -> dict[str, str]:
        return {"decision": self.decision, "rule": self.rule, "why": self.why}


ALLOW = Decision("allow", "ordinary")

_WRITE_TOOLS = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})
_READ_TOOLS = frozenset({"Read", "Grep", "Glob", "LS", "NotebookRead"})

#: Sending a repository's work somewhere as mail rather than as a push. That is
#: mail, so it is asked about like any other way out of the machine; pushing
#: itself is allowed, and is the standing default (see the note at the top).
_GIT_SENDS = frozenset({"send-email", "request-pull"})
#: Becoming someone else.
_BECOME = frozenset({"sudo", "su", "doas", "runuser", "pkexec", "setpriv"})
#: Logging in to, or copying to, another machine.
_REMOTE = frozenset({"ssh", "scp", "sftp", "mosh", "sshpass"})
#: Programs whose whole job is sending data out of the machine.
_SENDERS = frozenset({"nc", "ncat", "netcat", "telnet", "socat", "mail", "mailx", "sendmail",
                      "mutt", "ftp", "lftp"})
#: Programs that run whatever they are given, and wrap the real one.
_WRAPPERS = frozenset({"command", "exec", "nohup", "time", "env", "nice", "timeout", "stdbuf",
                       "xargs", "builtin", "caffeinate", "ionice"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
_CURL_SEND = re.compile(r"^(?:-d|--data(?:-\w+)?|-F|--form(?:-string)?|-T|--upload-file|--json)"
                        r"(?:=|$)|^-X\s*(?:POST|PUT|PATCH|DELETE)$|^-d.+|^-F.+|^-T.+", re.I)
_WGET_SEND = re.compile(r"^--(?:post-data|post-file|body-data|body-file)(?:=|$)|"
                        r"^--method=(?:POST|PUT|PATCH|DELETE)$", re.I)
_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_HOST_PATH = re.compile(r"^(?:[\w.-]+@)?[\w.-]+:(?!//)")

#: Files that hold keys and secrets, by name anywhere in a path.
_SECRET_PATH = re.compile(
    r"(?:^|/)(?:\.env(?:\.[\w-]+)?|\.ssh(?:/|$)|id_(?:rsa|ed25519|ecdsa|dsa)\b|[\w.-]+\.pem\b|"
    r"\.claude\.json\b|\.credentials(?:\.json)?\b|\.netrc\b|\.git-credentials\b|\.pgpass\b|"
    r"\.aws/credentials\b|\.docker/config\.json\b|\.passphrase\b|telegram\.json\b)")
_SECRET_OK = re.compile(r"(?:^|/)\.env\.(?:example|sample|template|dist)$")
#: Claude Code's own settings for the run's user hold the subscription key.
_CLAUDE_SETTINGS = re.compile(r"(?:^|/)\.claude/settings(?:\.local)?\.json\b")


def _segments(command: str) -> list[list[str]]:
    """A command line cut into the separate programs it runs.

    ``cd x && git push | tee log`` is three: each is checked on its own, so a
    push at the end of a chain is found, and the word "sudo" inside an echo is
    not mistaken for sudo.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = command.replace(";", " ; ").replace("|", " | ").replace("&", " & ").split()
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and set(token) <= set(";&|()"):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _program(segment: list[str]) -> tuple[str, list[str]]:
    """The program a segment runs, past variable settings and wrappers, and its arguments."""
    i = 0
    while i < len(segment):
        word = segment[i]
        if _ASSIGNMENT.match(word):
            i += 1
            continue
        name = os.path.basename(word)
        if name in _WRAPPERS:
            i += 1
            while i < len(segment) and (segment[i].startswith("-") or _ASSIGNMENT.match(segment[i])
                                        or re.match(r"^\d+(?:\.\d+)?[smhd]?$", segment[i])):
                i += 1
            continue
        return name, segment[i + 1:]
    return "", []


def _git_subcommand(args: list[str]) -> str:
    takes_value = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
    i = 0
    while i < len(args):
        if args[i] in takes_value:
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i]
    return ""


_REDIRECT = re.compile(r"^\d*[<>]+&?")


def _words(token: str) -> str:
    """A token with any redirection stuck to its front taken off: ``<.env`` is ``.env``."""
    return _REDIRECT.sub("", token)


def _is_secret(path: str, home: str | None = None) -> bool:
    path = path.strip().strip("'\"")
    if not path or _SECRET_OK.search(path):
        return False
    if _SECRET_PATH.search(path):
        return True
    # A run's own checkout may have a .claude/settings.json of the project's;
    # the user's own, in their home, holds the subscription key.
    if _CLAUDE_SETTINGS.search(path):
        expanded = os.path.expanduser(path) if path.startswith("~") else path
        return path.startswith("~") or (home is not None and expanded.startswith(home))
    return False


def _inside(path: str, roots: list[str], cwd: str) -> bool:
    if not path:
        return True
    full = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
    for root in roots:
        root = os.path.normpath(root)
        if full == root or full.startswith(root.rstrip("/") + "/"):
            return True
    return False


def decide(tool: str, tool_input: Mapping[str, Any] | None, *, cwd: str,
           scratch: str | None = None, home: str | None = None) -> Decision:
    """Allow, refuse or ask about one tool call a run wants to make."""
    tool_input = tool_input or {}
    if tool == "Bash":
        return _decide_bash(str(tool_input.get("command") or ""), home=home)

    if tool in _WRITE_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")
        roots = [cwd, "/tmp", "/private/tmp"] + ([scratch] if scratch else [])
        if _is_secret(path, home):
            return Decision("deny", "no-secrets",
                            "A run does not write to files that hold keys or passwords.")
        if not _inside(path, roots, cwd):
            return Decision("deny", "own-folder",
                            "A run changes files only inside its own checkout "
                            f"({cwd}) or a temporary folder.")
        return ALLOW

    if tool in _READ_TOOLS:
        path = str(tool_input.get("file_path") or tool_input.get("path")
                   or tool_input.get("notebook_path") or "")
        pattern = str(tool_input.get("pattern") or "")
        if _is_secret(path, home) or (tool == "Glob" and _is_secret(pattern, home)):
            return Decision("deny", "no-secrets",
                            "A run does not read files that hold keys or passwords.")
        return ALLOW

    if tool.startswith("mcp__"):
        return Decision("ask", "outside-tool",
                        f"It wants to use {tool}, a tool from outside Claude Code that "
                        "could reach other services.")
    return ALLOW


_DENY_SUDO = Decision("deny", "no-sudo", "A run never becomes another user.")
_DENY_REMOTE = Decision("deny", "no-remote", "A run never logs in to or copies to another machine.")
_DENY_SECRET = Decision("deny", "no-secrets",
                        "A run does not read or touch files that hold keys or passwords.")
_ASK_SEND = Decision("ask", "sends-out", "It wants to send data out of this machine.")


def _decide_bash(command: str, *, home: str | None = None, depth: int = 0) -> Decision:
    asked: Decision | None = None
    for segment in _segments(command.replace("\n", " ; ")):
        for token in segment:
            if _is_secret(_words(token), home):
                return _DENY_SECRET
        program, args = _program(segment)
        if not program:
            continue
        if program in _SHELLS or program == "eval":
            # sh -c "git push" is a push. Look inside, once or twice, no further.
            inner = args[args.index("-c") + 1] if "-c" in args and args.index("-c") + 1 < len(args) \
                else (" ".join(args) if program == "eval" else "")
            if inner and depth < 3:
                found = _decide_bash(inner, home=home, depth=depth + 1)
                if found.decision == "deny":
                    return found
                if found.decision == "ask":
                    asked = found
            continue
        if program == "git" and _git_subcommand(args) in _GIT_SENDS:
            asked = _ASK_SEND
        if program in _BECOME:
            return _DENY_SUDO
        if program in _REMOTE:
            return _DENY_REMOTE
        if program == "rsync" and any(_HOST_PATH.match(a) or a.startswith("rsync://")
                                      for a in args if not a.startswith("-")):
            return _DENY_REMOTE
        if program in _SENDERS:
            asked = _ASK_SEND
        elif program == "curl" and any(_CURL_SEND.match(a) for a in _joined_flags(args)):
            asked = _ASK_SEND
        elif program == "wget" and any(_WGET_SEND.match(a) for a in args):
            asked = _ASK_SEND
        elif program in ("http", "https", "xh", "xhs") and any(
                a.upper() in _METHODS or re.match(r"^[\w.-]+:?=", a) for a in args):
            asked = _ASK_SEND
    return asked or ALLOW


def _joined_flags(args: list[str]) -> list[str]:
    """``-X POST`` as one word, so it reads the same as ``-XPOST``."""
    out: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "-X" and i + 1 < len(args):
            out.append(f"-X {args[i + 1]}")
            i += 2
        else:
            out.append(args[i])
            i += 1
    return out
