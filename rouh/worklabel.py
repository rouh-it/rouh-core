"""What one piece of work on the orb is, in words a person would use.

The orb draws every background job, helper and tool call running right now,
and pointing at a line used to say only "Running a shell command" or
"Searching the web" - true of every shell command and every search, so it
said nothing. Asked for on 13 September: "I want to hover and know what is
being searched ... It has to mean something to me."

Everything here turns what a tool call was given into two lines:

* ``what`` - one short line, readable at a glance in a hover:
  ``Searching the web for "dumbbell bar length"``.
* ``detail`` - the longer version for the card a click opens: the command
  itself, the full path, what a page was fetched for.

Built on the server, in this one module, from the hook payloads Claude Code
sends and from the arguments Rouh's own tools are called with. Only these
words go to the page, never the raw input, and every line goes through
:func:`redact` and is capped. A key pasted into a command, a password in an
environment variable, a token in a URL: none of them reaches the screen.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

__all__ = ["WHAT_MAX", "DETAIL_MAX", "redact", "describe_step", "describe_helper",
           "given", "describe_doing", "command_input", "command_output"]

#: The hover line. Short enough to read in a glance next to the pointer.
WHAT_MAX = 90
#: The card's longer line.
DETAIL_MAX = 220

# ---------------------------------------------------------------------------
# Hiding secrets
# ---------------------------------------------------------------------------

_HIDDEN = "[hidden]"

_SECRET_WORD = r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|PWD|CREDENTIALS?|AUTH|COOKIE|SESSION|SIGNATURE)"

#: Applied in order. Each says what it catches, because a pattern that is too
#: greedy hides a whole command and one that is too shy shows a key. These
#: first ones go by what a secret looks like, wherever it is written.
_BY_SHAPE: list[tuple[re.Pattern[str], str]] = [
    # Keys with a known shape: Anthropic, OpenAI, GitHub, Slack, AWS, Google.
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{8,}"), _HIDDEN),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{12,}"), _HIDDEN),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{16,}"), _HIDDEN),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{8,}"), _HIDDEN),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _HIDDEN),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}"), _HIDDEN),
    (re.compile(r"\bapify_api_[A-Za-z0-9]{8,}"), _HIDDEN),
    # "Authorization: Bearer abc", "Authorization=...", "x-api-key: abc".
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:(?:bearer|basic|token)\s+)?[^\s'\"]+"), r"\1" + _HIDDEN),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9\-._~+/=]{8,}"), r"\1 " + _HIDDEN),
    (re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s'\"]+"), r"\1" + _HIDDEN),
    # A login inside a URL: scheme://user:password@host.
    (re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1" + _HIDDEN + "@"),
    # A query parameter with a secret-sounding name: ?token=..., &session=...
    (re.compile(r"(?i)([?&][a-z0-9_\-]*" + _SECRET_WORD + r"[a-z0-9_\-]*=)[^&\s#'\"]+"), r"\1" + _HIDDEN),
    # Flags: --password x, --token=x, --api-key x, -p=x is left alone (too common).
    (re.compile(r"(?i)(--(?:password|passwd|token|api[-_]?key|secret|auth)(?:=|\s+))(\"[^\"]*\"|'[^']*'|\S+)"),
     r"\1" + _HIDDEN),
]

#: Long random-looking strings: mixed case and digits, 32 characters or more.
#: A git hash (lower-case hex) and a file path are not caught. Last, so a key
#: another rule has already named is hidden once.
_RANDOM = (re.compile(r"(?<![A-Za-z0-9_\-+=])(?=[A-Za-z0-9_\-+=]*[A-Z])(?=[A-Za-z0-9_\-+=]*[a-z])"
                      r"(?=[A-Za-z0-9_\-+=]*\d)[A-Za-z0-9_\-+=]{32,}"), _HIDDEN)

_REDACTIONS: list[tuple[re.Pattern[str], str]] = _BY_SHAPE + [
    # An environment variable given a value, VAR=value: never shown, whatever
    # its name. Upper-case names only, which is how shells spell them.
    (re.compile(r"\b([A-Z][A-Z0-9_]{1,})=(\"[^\"]*\"|'[^']*'|[^\s;&|'\"]+)"), r"\1=" + _HIDDEN),
    # Any name that sounds secret, in any case: api_key=..., "password": "..."
    (re.compile(r"(?i)\b([a-z0-9_\-]*" + _SECRET_WORD + r"[a-z0-9_\-]*)(\"?\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&|}'\"]+)"),
     r"\1\2" + _HIDDEN),
    _RANDOM,
]

#: What a command printed is mostly code, settings and listings, where
#: `var key = ...` and `DEBUG=1` are far more often a variable than a secret,
#: and the two rules above hid a line of a code search as `var key = [hidden]`.
#: So in output a name hides a value only where secrets are really written
#: down: an upper-case name that sounds secret given a value, as in `.env` and
#: `env` (`ANTHROPIC_API_KEY=...`), or a name that sounds secret given a quoted
#: value, as in JSON and code (`"api_key": "..."`). Neither reaches past the
#: end of its line.
_IN_OUTPUT: list[tuple[re.Pattern[str], str]] = _BY_SHAPE + [
    (re.compile(r"\b([A-Z0-9_]*" + _SECRET_WORD + r"[A-Z0-9_]*)=(\"[^\"\n]*\"|'[^'\n]*'|[^\s;&|'\"]+)"),
     r"\1=" + _HIDDEN),
    (re.compile(r"(?i)\b([a-z0-9_\-]*" + _SECRET_WORD + r"[a-z0-9_\-]*)(\"?\s*[:=]\s*)(\"[^\"\n]*\"|'[^'\n]*')"),
     r"\1\2" + _HIDDEN),
    _RANDOM,
]


def redact(text: Any, rules: list[tuple[re.Pattern[str], str]] = _REDACTIONS) -> str:
    """The same text with anything that looks like a secret replaced by [hidden]."""
    out = str(text or "")
    for pattern, replacement in rules:
        out = pattern.sub(replacement, out)
    return out


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _clean(text: Any) -> str:
    """One line: whitespace and newlines collapsed."""
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _cap(text: str, limit: int) -> str:
    text = _clean(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _arg(args: Mapping[str, Any], *names: str) -> str:
    for name in names:
        value = args.get(name)
        if isinstance(value, str) and value.strip():
            return _clean(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _where(path: str) -> str:
    """``/srv/app/src/auth/login.py`` -> ``login.py in src/auth``."""
    path = _clean(path).rstrip("/")
    if not path:
        return ""
    base = os.path.basename(path) or path
    parent = os.path.dirname(path).strip("/")
    folder = "/".join(parent.split("/")[-2:]) if parent else ""
    return f"{base} in {folder}" if folder else base


def _folder(path: str) -> str:
    """A folder named by its last two parts, the way a person says it."""
    path = _clean(path).rstrip("/")
    if not path:
        return "the job's folder"
    return "/".join(path.strip("/").split("/")[-2:]) or path


def _page(url: str) -> str:
    """``https://www.site.com/a/b?x=1`` -> ``site.com/a/b`` (no query, no login)."""
    url = _clean(url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if not parts.netloc:
        return url
    host = parts.hostname or parts.netloc
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    return f"{host}{path}" if path else host


def _short_command(command: str, limit: int = 60) -> str:
    return _cap(command, limit)


def _first_sentence(text: str) -> str:
    text = _clean(text)
    match = re.match(r"(.+?[.!?])(\s|$)", text)
    return match.group(1) if match else text


# ---------------------------------------------------------------------------
# One tool call
# ---------------------------------------------------------------------------

Step = tuple[str, str]
_STEPS: dict[str, Callable[[Mapping[str, Any]], Step]] = {}


def _step(*names: str):
    def register(fn: Callable[[Mapping[str, Any]], Step]):
        for name in names:
            _STEPS[name] = fn
        return fn
    return register


@_step("WebSearch", "web_search")
def _web_search(a):
    query = _arg(a, "query", "q")
    what = f'Searching the web for "{query}"' if query else "Searching the web"
    # A query too long for the hover line is given whole in the card.
    return what, (query if len(what) > WHAT_MAX else "")


@_step("WebFetch", "web_fetch")
def _web_fetch(a):
    url = _arg(a, "url")
    wanted = _arg(a, "prompt")
    return (f"Reading {_page(url)}" if url else "Reading a web page",
            f"Looking for: {wanted}" if wanted else (url and _page(url)))


@_step("browser_fetch")
def _browser_fetch(a):
    # A page web_fetch could not read, read again in a headless browser
    # (rouh/fetchfallback.py). Rouh's own second try, never the model's.
    url = _arg(a, "url")
    return (f"Reading {_page(url)} in a browser" if url else "Reading a page in a browser",
            "web_fetch could not read it")


@_step("read_rouh_link")
def _read_rouh_link(a):
    # A link to Rouh itself, read inside Rouh as the person, never through the
    # web (rouh/rouhlinks.py): the path and its # part, which is what it names.
    url = _arg(a, "url")
    try:
        parts = urlsplit(url if "://" in url else "https://" + url)
        where = (parts.path or "/") + (f"#{parts.fragment}" if parts.fragment else "")
    except ValueError:
        where = url
    return (f"Reading {where} inside Rouh" if url else "Reading a page of Rouh's own",
            "Read inside Rouh, as you, never through the web")


@_step("tool_search_tool_regex", "tool_search_tool_bm25", "find_tools", "tool_search")
def _tool_search(a):
    # Rouh loading a tool it is about to use (rouh/toolsearch.py). The model
    # searches with the exact names from its catalogue, so a pattern like
    # ^(show_on_screen|remember)$ is said as the names it asks for.
    asked = _arg(a, "pattern", "query")
    names = [n for n in re.findall(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+", asked)]
    if names:
        return "Loading " + ", ".join(dict.fromkeys(names)), asked
    return (f'Looking for a tool: "{asked}"' if asked else "Looking for a tool"), ""


@_step("youtube_transcript")
def _youtube_transcript(a):
    video = _arg(a, "video", "url", "video_id")
    span = ""
    if a.get("start") or a.get("end"):
        span = f" from {_arg(a, 'start') or 'the start'} to {_arg(a, 'end') or 'the end'}"
    return (f"Reading what was said in {_youtube_said(video)}" if video
            else "Reading a YouTube transcript"), (video + span if video else "")


@_step("youtube_search")
def _youtube_search(a):
    query = _arg(a, "query", "q")
    what = f'Searching YouTube for "{query}"' if query else "Searching YouTube"
    return what, (query if len(what) > WHAT_MAX else "")


@_step("linkedin_search")
def _linkedin_search(a):
    name = " ".join(v for v in (_arg(a, "first_name"), _arg(a, "last_name")) if v)
    more = ", ".join(v for v in (_arg(a, "title"), _arg(a, "company"), _arg(a, "location"),
                                 _arg(a, "school")) if v)
    what = f"Looking for {name} on LinkedIn" if name else "Searching LinkedIn"
    return what, more


@_step("make_picture")
def _make_picture(a):
    count = a.get("count")
    many = isinstance(count, int) and not isinstance(count, bool) and count > 1
    return (f"Drawing {count} pictures" if many else "Drawing a picture"), _arg(a, "prompt")


@_step("change_picture")
def _change_picture(a):
    if a.get("variation"):
        return "Drawing more like a picture", _arg(a, "picture")
    return "Changing a picture", _arg(a, "prompt")


@_step("linkedin_profile")
def _linkedin_profile(a):
    url = _arg(a, "url")
    if url:
        return f"Reading the LinkedIn profile at {_page(url)}", url
    card, number = _arg(a, "card"), _arg(a, "number")
    if card and number:
        return f"Reading the LinkedIn profile of number {number} on card {card}", ""
    return "Reading a LinkedIn profile", ""


@_step("browser")
def _browser(a):
    """The Live browser (`rouh/browsing.py`), one action at a time."""
    action = _arg(a, "action").lower()
    if action == "open":
        url = _arg(a, "url")
        return (f"Opening {_page(url)} in the browser" if url else "Opening the browser"), ""
    if action == "type":
        # What was typed stays off the hover line: it can be somebody's
        # address or phone number, and the line is read out on the orb.
        return "Typing into a page in the browser", ""
    if action == "select":
        return "Picking an option on a page in the browser", ""
    if action == "press":
        key = _arg(a, "key")
        return (f"Pressing {key} in the browser" if key else "Pressing a key in the browser"), ""
    if action == "hand_over":
        return "Handing the browser to you", _arg(a, "why")
    return {
        "look": "Reading the page in the browser",
        "click": "Clicking on a page in the browser",
        "back": "Going back a page in the browser",
        "close": "Closing the browser",
        "fill_card": "Filling in the card in the browser",
        "authorize_purchase": "Writing down your order",
        "place_order": "Placing your order in the browser",
    }.get(action, "Using the browser"), ""


def _youtube_said(video: str) -> str:
    """A video, for a hover line: its id, which is all anybody can read of it."""
    video = _clean(video)
    if "youtu" in video:
        # The id is the useful half of a watch URL and the rest is noise in a
        # 90-character line.
        for marker in ("v=", "/shorts/", "/live/", "youtu.be/", "/embed/"):
            if marker in video:
                tail = video.split(marker, 1)[1]
                return "YouTube video " + re.split(r"[&?/#]", tail)[0][:16]
    return f"YouTube video {video[:16]}" if video else "a YouTube video"


@_step("Bash", "run_command")
def _bash(a):
    command = _arg(a, "command", "cmd")
    said = _arg(a, "description")
    if said:
        return said, f"$ {command}" if command else ""
    return (f"Running {_short_command(command)}" if command else "Running a shell command",
            f"$ {command}" if command else "")


@_step("BashOutput")
def _bash_output(a):
    return "Reading the output of a command running in the background", ""


@_step("KillShell", "KillBash")
def _kill_shell(a):
    return "Stopping a command running in the background", ""


@_step("Read")
def _read(a):
    path = _arg(a, "file_path", "path")
    span = ""
    if a.get("offset") or a.get("limit"):
        start = int(a.get("offset") or 1)
        count = a.get("limit")
        span = f", lines {start}-{start + int(count) - 1}" if count else f", from line {start}"
    return (f"Reading {_where(path)}" if path else "Reading a file", f"{path}{span}" if path else "")


@_step("Edit", "MultiEdit")
def _edit(a):
    path = _arg(a, "file_path", "path")
    return (f"Editing {_where(path)}" if path else "Editing a file", path)


@_step("Write")
def _write(a):
    path = _arg(a, "file_path", "path")
    return (f"Writing {_where(path)}" if path else "Writing a file", path)


@_step("NotebookEdit")
def _notebook(a):
    path = _arg(a, "notebook_path", "file_path")
    return (f"Editing the notebook {_where(path)}" if path else "Editing a notebook", path)


@_step("Grep")
def _grep(a):
    pattern = _arg(a, "pattern")
    path = _arg(a, "path")
    files = _arg(a, "glob", "type")
    where = _folder(path) if path else "the job's folder"
    detail = ", ".join(x for x in (path and f"in {path}", files and f"files {files}") if x)
    return (f'Searching for "{pattern}" in {where}' if pattern else "Searching inside files", detail)


@_step("Glob")
def _glob(a):
    pattern = _arg(a, "pattern")
    path = _arg(a, "path")
    where = _folder(path) if path else "the job's folder"
    return (f'Finding files matching "{pattern}" in {where}' if pattern else "Finding files by name",
            f"in {path}" if path else "")


@_step("LS")
def _ls(a):
    path = _arg(a, "path")
    return (f"Listing {_folder(path)}" if path else "Listing a folder", path)


@_step("Task", "Agent")
def _agent(a):
    helper = describe_helper(a)
    return f"Starting a helper: {helper['what']}", helper["detail"] or ""


@_step("TodoWrite")
def _todo(a):
    todos = a.get("todos")
    if isinstance(todos, list):
        doing = next((t for t in todos if isinstance(t, Mapping) and t.get("status") == "in_progress"), None)
        if doing:
            now = _clean(doing.get("activeForm") or doing.get("content"))
            return f"Updating its to-do list, now: {now}", f"{len(todos)} items"
        return "Updating its to-do list", f"{len(todos)} items"
    return "Updating its to-do list", ""


# Anthropic's own tools, run on their side inside one model call.

#: A web search or page fetch made from inside code: Rouh often searches this
#: way, and "Running code" alone then says nothing of what it looked for.
_CODE_CALL = re.compile(
    r"\b(web_search|web_fetch)\s*\(\s*\{?\s*(?:[\"'](?:query|url)[\"']\s*:|(?:query|url)\s*=)\s*"
    r"([\"'])(.*?)(?<!\\)\2")


@_step("code_execution")
def _code(a):
    raw = next((a[k] for k in ("code", "command") if isinstance(a.get(k), str) and a[k].strip()), "")
    if not raw:
        return "Running code on Anthropic's side", ""
    call = _CODE_CALL.search(raw)
    if call:
        tool, _, value = call.groups()
        what = (f'Running code that searches the web for "{value}"' if tool == "web_search"
                else f"Running code that reads {_page(value)}")
        return what, raw
    lines = [line.strip() for line in raw.splitlines()
             if line.strip() and not line.strip().startswith(("import ", "from ", "#"))]
    return (f"Running code: {lines[0]}" if lines else "Running code on Anthropic's side"), raw


@_step("bash_code_execution")
def _code_bash(a):
    command = _arg(a, "command")
    return (f"Running {_short_command(command)} on Anthropic's side" if command
            else "Running a command on Anthropic's side", f"$ {command}" if command else "")


@_step("text_editor_code_execution")
def _code_editor(a):
    action = _arg(a, "command")
    path = _arg(a, "path")
    verb = {"view": "Reading", "create": "Writing", "str_replace": "Editing"}.get(action, "Working on")
    return (f"{verb} {_where(path)} on Anthropic's side" if path else "Working on a file on Anthropic's side",
            path)


# Rouh's own tools.

@_step("show_on_screen")
def _show(a):
    title = _arg(a, "title")
    return (f'Putting "{title}" on the canvas' if title else "Putting something on the canvas",
            _arg(a, "description"))


@_step("show_workspace_page")
def _show_page(a):
    title = _arg(a, "title")
    path = _arg(a, "path")
    name = title or (os.path.basename(path.rstrip("/")) if path else "")
    return (f'Putting the page "{name}" on the canvas' if name else "Putting a workspace page on the canvas",
            path)


@_step("show_canvas")
def _show_canvas(a):
    step, task = _arg(a, "step"), _arg(a, "task")
    where = step or task
    if step:
        said = "Opening a step on the canvas"
    elif task:
        said = "Opening a task on the canvas"
    elif _arg(a, "mode") == "now":
        said = "Going back to the live work"
    else:
        said = "Opening the task browser"
    return (said, where)


def _work_named(said: str) -> str:
    """"task 56" or "step 56-01" for a number, and a path's last part otherwise."""
    if re.fullmatch(r"\d{1,4}-\d{1,3}", said):
        return f"step {said}"
    if re.fullmatch(r"\d{1,4}", said):
        return f"task {said}"
    return os.path.basename(said.rstrip("/")) or said


@_step("publish_task")
def _publish_task(a):
    said = _arg(a, "task")
    work = _work_named(said) if said else "a task"
    if _arg(a, "access").lower() == "off":
        return f"Taking {work} down, so it is not public any more", said
    return f"Making {work} public", said


@_step("share_with_person")
def _share_with_person(a):
    said, email = _arg(a, "task"), _arg(a, "email")
    work = _work_named(said) if said else "a task"
    can = " to edit" if _arg(a, "role").lower() == "edit" else ""
    return (f"Sharing {work} with {email or 'somebody'}{can} and emailing them the link",
            email)


@_step("check_task_sharing")
def _check_task_sharing(a):
    said = _arg(a, "task")
    return f"Checking whether {_work_named(said) if said else 'a task'} is public", said


@_step("show_again")
def _show_again(a):
    card, version = _arg(a, "id"), _arg(a, "version")
    said = f"Bringing card #{card} back" if card else "Bringing a card back"
    if version:
        said += f", as it was at version {version}"
    return (said, "")


@_step("read_card")
def _read_card(a):
    which, version, find = _arg(a, "id"), _arg(a, "version"), _arg(a, "find")
    if not which:
        return (f'Looking through past work for "{find}"' if find
                else "Looking through past work", "")
    said = f"Reading card #{which}" if which.isdigit() else "Reading past work"
    if version:
        said += f", as it was at version {version}"
    return (said, "")


@_step("revise_on_screen")
def _revise(a):
    card, title = _arg(a, "id"), _arg(a, "title")
    return (f"Revising card #{card}" if card else "Revising a card on the canvas",
            title or _arg(a, "description"))


@_step("what_was_on_screen")
def _looked_back(a):
    query = _arg(a, "query")
    return (f'Looking back through the canvas for "{query}"' if query else "Looking back through the canvas", "")


@_step("set_panels")
def _panels(a):
    said = []
    for key, words in (("tasks", "the task list"), ("transcript", "the conversation"),
                       ("canvas", "the canvas"), ("orb", "the orb")):
        value = a.get(key)
        if value in ("open", "closed", True, False):
            said.append(f"{'opening' if value in ('open', True) else 'closing'} {words}")
    text = ", ".join(said)
    return (text[:1].upper() + text[1:]) if text else "Opening or closing a column, or the orb", ""


#: A fact stored under a name like "wifi password" or "door pin" is shown by its
#: name only: the value is the secret, and nothing marks it as one but the name.
_SECRET_NAME = re.compile(_SECRET_WORD + r"|\bPIN\b", re.I)


@_step("remember")
def _remember(a):
    key = _arg(a, "key")
    value = _arg(a, "value")
    if key and _SECRET_NAME.search(key):
        value = _HIDDEN if value else ""
    return (f'Remembering "{key}"' if key else "Remembering a fact", value)


@_step("forget")
def _forget(a):
    key = _arg(a, "key")
    return (f'Forgetting "{key}"' if key else "Forgetting a fact", "")


def _when_said(a) -> str:
    """When something is scheduled for, as the tool was given it."""
    minutes = a.get("in_minutes")
    if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and minutes > 0:
        return f"in {int(minutes)} minute{'s' if int(minutes) != 1 else ''}"
    at = _arg(a, "at").replace("T", " ")
    return f"for {at}" if at else ""


@_step("schedule")
def _schedule(a):
    when = _when_said(a)
    repeat = _arg(a, "repeat").lower()
    often = "" if repeat in ("", "once") else f", {repeat}"
    if _arg(a, "kind").lower() == "do":
        return (f"Scheduling a job {when}{often}".replace("  ", " ").strip(),
                _arg(a, "what"))
    return (f"Setting a reminder {when}{often}".replace("  ", " ").strip(), _arg(a, "what"))


@_step("upcoming")
def _upcoming(a):
    return "Reading what is coming up", ""


@_step("heartbeat")
def _heartbeat(a):
    return ({"pause": "Pausing the heartbeat", "resume": "Resuming the heartbeat",
             "beat_now": "Starting a heartbeat now", "set": "Changing the heartbeat",
             "answer": "Answering the heartbeat's question"}.get(_arg(a, "action").lower(),
                                                                 "Reading the heartbeat"), "")


@_step("quest", "long_work")
def _quest(a):
    return ({"create": "Starting a quest", "brief": "Changing its brief",
             "edit": "Changing the quest",
             "ledger": "Reading its ledger" if _arg(a, "amount") == "" else "Writing in its ledger",
             "set": "Changing its budget or dates", "pause": "Pausing it",
             "resume": "Resuming it", "beat_now": "Starting a beat on it",
             "reset": "Starting it again from beat 1" if a.get("confirm") is True
             else "Asking about a reset",
             "delete": "Deleting it" if a.get("confirm") is True else "Asking about deleting it"}
            .get(_arg(a, "action").lower(), "Reading the quests"),
            _arg(a, "quest") or _arg(a, "work"))


@_step("payments")
def _payments(a):
    return "Reading the card vault and Stripe", ""


@_step("stripe")
def _stripe(a):
    return ({"create_product": "Making a Stripe product", "create_price": "Making a Stripe price",
             "create_payment_link": "Making a payment link", "payments": "Reading payments",
             "balance": "Reading the Stripe balance", "refund": "Asking to refund a payment"}
            .get(_arg(a, "action").lower(), "Reading Stripe"), _arg(a, "name"))


@_step("heartbeat_end")
def _heartbeat_end(a):
    return ({"note": "Leaving a note for you", "telegram": "Telling you on Telegram"}
            .get(_arg(a, "how").lower(), "Ending the beat"), "")


@_step("heartbeat_ask")
def _heartbeat_ask(a):
    return "Asking for your yes", _arg(a, "what")


@_step("heartbeat_brief")
def _heartbeat_brief(a):
    return f"Updating the work's {_arg(a, 'part') or 'plan'}", ""


@_step("heartbeat_ledger")
def _heartbeat_ledger(a):
    return "Writing in the ledger", _arg(a, "what")


@_step("heartbeat_next")
def _heartbeat_next(a):
    return "Setting the next beat", _arg(a, "why")


@_step("heartbeat_thread")
def _heartbeat_thread(a):
    return "Marking a mail thread as the heartbeat's", ""


@_step("change_scheduled")
def _change_scheduled(a):
    action = _arg(a, "action").lower()
    return ({"cancel": "Cancelling a reminder", "pause": "Pausing a reminder",
             "resume": "Resuming a reminder"}.get(action, "Changing a reminder"),
            _arg(a, "what"))


@_step("set_goal")
def _set_goal(a):
    name = _arg(a, "name")
    return (f'Setting a goal: "{name}"' if name else "Setting a goal"), ""


@_step("plan_goal")
def _plan_goal(a):
    goal = _arg(a, "goal")
    return (f'Planning "{goal}"' if goal else "Planning the goal"), _arg(a, "why")


@_step("goal_step")
def _goal_step(a):
    step = _arg(a, "step")
    status = _arg(a, "status").lower()
    if status == "done":
        return (f'Marking my part of "{step}" done' if step else "Marking my part done"), ""
    return (f'Changing the step "{step}"' if step else "Changing a step"), ""


@_step("goals")
def _goals(a):
    return "Reading your goals", ""


@_step("list_memory")
def _list_memory(a):
    return "Reading its memory", ""


@_step("agent_instructions")
def _agent_instructions(a):
    action = str(a.get("action") or "list")
    return {"add": "Adding an agent instruction", "edit": "Changing an agent instruction",
            "enable": "Switching an agent instruction on", "disable": "Switching an agent instruction off",
            "delete": "Deleting an agent instruction"}.get(action, "Reading the agent instructions"), ""


@_step("what_is_running")
def _what_running(a):
    return "Reading what is running on the server", ""


@_step("check_tasks")
def _check(a):
    job = _arg(a, "id")
    return (f"Checking job {job}" if job else "Checking the job list", "")


@_step("delegate_task")
def _delegate(a):
    title = _arg(a, "title")
    return (f'Starting a server job: "{title}"' if title else "Starting a server job", _arg(a, "task"))


@_step("assistant_job")
def _assistant(a):
    title = _arg(a, "title")
    return (f'Handing "{title}" to your assistant' if title else "Handing a job to your assistant",
            _arg(a, "request"))


@_step("look_into")
def _look_into(a):
    """The subagent tool (rouh/subagent.py). Named by what it was sent to
    find out, because that is the only thing anybody wants to read off a
    branch on the orb."""
    task = _arg(a, "task")
    return (f'Looking into: "{_first_sentence(task)}"' if task else "Looking something up",
            task)


@_step("look_at_task")
def _look(a):
    job = _arg(a, "id")
    return (f"Reading the screen of job {job}" if job else "Reading a job's screen", "")


@_step("reply_to_task")
def _reply(a):
    job = _arg(a, "id")
    return (f"Answering the question job {job} asked" if job else "Answering a job's question",
            _arg(a, "answer"))


@_step("read_task_log")
def _log(a):
    job = _arg(a, "id")
    return (f"Reading the log of job {job}" if job else "Reading a job's log", "")


@_step("what_task_changed")
def _changed(a):
    job = _arg(a, "id")
    return (f"Reading what job {job} changed" if job else "Reading what a job changed", "")


@_step("tidy_tasks")
def _tidy(a):
    job = _arg(a, "id")
    return (f"Tidying job {job}" if job else "Tidying finished jobs", "")


@_step("stop_task")
def _stop(a):
    job = _arg(a, "id")
    return (f"Stopping job {job}" if job else "Stopping a job", "")


@_step("improve_myself")
def _improve(a):
    title = _arg(a, "title")
    return (f'Changing its own code: "{title}"' if title else "Changing its own code", _arg(a, "change"))


@_step("deploy_myself")
def _deploy(a):
    # Both services, so the label says both: this is the one line a person sees
    # while it happens, and "its own code" said nothing about the one program
    # going with it.
    target = _arg(a, "to")
    return (f"Deploying both services, {target}" if target else "Deploying both services", "")


@_step("server_health")
def _health(a):
    return "Checking the server", ""


@_step("read_workspace")
def _workspace(a):
    search = _arg(a, "search")
    path = _arg(a, "path")
    if search:
        return f'Searching the workspace for "{search}"', path and f"in {path}"
    if path:
        return f"Reading {_where(path)} in the workspace", path
    return "Reading the workspace", ""


# --- Google: what Rouh is doing in somebody's mailbox, Drive, documents or calendar ---
#
# The orb draws these while they run, and they are the tool calls it matters
# most to be able to point at: everything below "reading" writes to a real
# account, so the hover line says what is being written and to whom.


def _service_list(a: Mapping[str, Any], name: str) -> list[str]:
    """Nonblank service list arguments, keeping their original spacing."""
    return [str(x) for x in (a.get(name) or []) if str(x).strip()]


def _whose_mail(a) -> str:
    """ in your inbox", " in my inbox", or "" for both (`rouh/inboxes.py`)."""
    said = (_arg(a, "inbox") or "").lower()
    if said in ("rouh", "yours"):
        return " in Rouh's inbox"
    if said in ("person", "mine") or "@" in said:
        return " in your own inbox"
    return ""


@_step("read_recent_mail")
def _recent_mail(a):
    query = _arg(a, "query")
    where = _whose_mail(a)
    return (f'Looking through the mail{where} for "{query}"' if query
            else f"Reading the newest mail{where}", query)


@_step("read_mail")
def _read_mail(a):
    return "Reading a message in full", _arg(a, "message_id")


@_step("read_mail_attachment")
def _read_mail_attachment(a):
    return "Reading a file attached to an email", _arg(a, "message_id")


@_step("show_inbox")
def _show_inbox(a):
    query = _arg(a, "query")
    where = _whose_mail(a)
    return (f"Putting {'the inbox' if not where else where.strip()[3:]} on the screen",
            f"Only {query}" if query else "")


@_step("meeting_people")
def _meeting_people(a):
    if a.get("research_now") is True:
        return "Looking up who is coming to a meeting", ""
    return "Reading who is coming to a meeting", ""


@_step("mail_alerts")
def _mail_alerts(a):
    return "Looking at what became of new mail", ""


@_step("show_contact")
def _show_contact(a):
    who = _arg(a, "contact_id") or _arg(a, "email") or _arg(a, "query")
    return "Showing a contact", who


@_step("link_person")
def _link_person(a):
    what = {"unlink": "Unlinking", "undo": "Undoing a link on", "show": "Showing"}.get(
        str((a or {}).get("action") or "").lower(), "Linking")
    return f"{what} a person's Slack, address or name", _arg(a, "other") or _arg(a, "person")


@_step("update_contact_profile")
def _update_contact_profile(a):
    who = _arg(a, "contact_id") or _arg(a, "email")
    what = ("who they are to you" if "relationship" in (a or {}) else
            "the research about them" if "research" in (a or {}) else "a contact")
    return f"Keeping {what}", who


def _mail_detail(a) -> str:
    """"Subject: Photos - with IMG_8997.jpeg", for an email being written.

    The files by their names alone: a path says where on this machine a file
    was, which is nothing a person looking at the orb needs to read.
    """
    raw = (a or {}).get("attachments")
    raw = [raw] if isinstance(raw, str) else raw if isinstance(raw, (list, tuple)) else []
    names = [os.path.basename(_clean(one).rstrip("/")) for one in raw if _clean(one)]
    files = ("" if not names else f"with {len(names)} files" if len(names) > 2
             else "with " + " and ".join(names))
    subject = _arg(a, "subject")
    return " - ".join(part for part in (f"Subject: {subject}" if subject else "", files) if part)


@_step("send_mail")
def _send_mail(a):
    to = _arg(a, "to")
    replying = _arg(a, "reply_to_message_id")
    what = ("Replying to " + to if replying and to else
            "Replying to a message" if replying else
            f"Sending mail to {to}" if to else "Sending mail")
    return what, _mail_detail(a)


@_step("send_telegram")
def _send_telegram(a):
    # The message itself on the card, because on the orb "Messaging you on
    # Telegram" is true of every one of them and so says nothing. It is its own
    # text, and it goes through `redact` and the cap like every other line.
    said = _arg(a, "text")
    return "Messaging you on Telegram", said


@_step("draft_mail")
def _draft_mail(a):
    to = _arg(a, "to")
    return (f"Drafting mail to {to}" if to else "Drafting mail", _mail_detail(a))


@_step("forward_mail")
def _forward_mail(a):
    to = _arg(a, "to")
    return (f"Forwarding mail to {to}" if to else "Forwarding mail", _arg(a, "note"))


@_step("forward_thread")
def _forward_thread(a):
    to = _arg(a, "to")
    return (f"Forwarding a whole conversation to {to}" if to
            else "Forwarding a whole conversation", _arg(a, "note"))


@_step("worker_outbox")
def _worker_outbox(a):
    action = _arg(a, "action") or "list"
    note = _arg(a, "note_id")
    if action == "sent":
        return f"Marking note {note} sent" if note else "Marking a note sent", _arg(a, "message_id")
    if action == "dismissed":
        return f"Dismissing note {note}" if note else "Dismissing a note", ""
    return "Looking at the emails jobs have queued", _arg(a, "job")


@_step("mcp__rouh__notify_owner", "mcp__rouh__notify_petar")
def _notify_owner(a):
    # A worker's call, on its own spike: the email it queued for Rouh to send.
    subject = _arg(a, "subject")
    return "Queueing an email for Rouh to send", (f"Subject: {subject}" if subject else "")


@_step("mail_find")
def _job_mail_find(a):
    # A worker asking Rouh for emails and their files (`rouh/job_mail.py`).
    return "Looking for an email through Rouh", _arg(a, "query")


@_step("mail_file")
def _job_mail_file(a):
    return "Saving a file from an email", _arg(a, "name") or _arg(a, "save_to")


@_step("request_from_rouh")
def _request_from_rouh(a):
    # A job asking Rouh for what none of its tools gives (`rouh/job_gateway.py`).
    return "Asking Rouh for something it needs", _arg(a, "need")


@_step("request_status")
def _request_status(a):
    return "Checking what Rouh was asked for", _arg(a, "id")


@_step("modify_mail")
def _modify_mail(a):
    if a.get("trash"):
        return "Putting a message in the bin", _arg(a, "message_id")
    if a.get("archive"):
        return "Archiving a message", _arg(a, "message_id")
    labels = _service_list(a, "add_labels")
    if labels:
        return "Labelling a message " + ", ".join(labels), _arg(a, "message_id")
    if a.get("mark_read"):
        return "Marking a message read", _arg(a, "message_id")
    if a.get("mark_unread"):
        return "Marking a message unread", _arg(a, "message_id")
    return "Changing a message", _arg(a, "message_id")


@_step("search_drive")
def _search_drive(a):
    text = _arg(a, "text")
    drive = _arg(a, "drive")
    return (f'Searching Drive for "{text}"' if text else "Searching Drive",
            f"in the shared drive {drive}" if drive else text)


@_step("list_drive_folder")
def _list_drive_folder(a):
    folder = _arg(a, "folder")
    drive = _arg(a, "drive")
    listing = "Listing the folders in" if a.get("folders_only") else "Listing"
    where = (folder if folder else
             f"the top of {drive}" if drive else
             "the root of My Drive")
    return f"{listing} {where}", (f"in the shared drive {drive}" if drive and folder else "")


@_step("list_shared_drives")
def _list_shared_drives(a):
    return "Listing the shared drives", ""


@_step("create_shared_drive")
def _create_shared_drive(a):
    name = _arg(a, "name")
    managers = _service_list(a, "managers")
    return (f"Making the shared drive {name}" if name else "Making a shared drive",
            ("Managers: " + ", ".join(managers)) if managers else "")


@_step("add_shared_drive_members")
def _add_shared_drive_members(a):
    drive = _arg(a, "drive")
    people = [str(x.get("email") if isinstance(x, dict) else x)
              for x in (a.get("people") or [])]
    return (f"Adding people to the shared drive {drive}" if drive
            else "Adding people to a shared drive", ", ".join(p for p in people if p))


@_step("write_drive_file")
def _write_drive(a):
    name = _arg(a, "name")
    folder = _arg(a, "folder")
    what = ("Replacing " + name if _arg(a, "file_id") and name else
            f"Saving {name} to Drive" if name else "Saving a file to Drive")
    return what, (f"in {folder}" if folder else "")


@_step("upload_drive_file")
def _upload_drive(a):
    path = _arg(a, "path")
    folder = _arg(a, "folder")
    name = os.path.basename(path.rstrip("/")) if path else ""
    return (f"Uploading {name} to Drive" if name else "Uploading a file to Drive",
            (f"{path} into {folder}" if folder else path))


@_step("create_drive_folder")
def _create_drive_folder(a):
    name = _arg(a, "name")
    parent = _arg(a, "parent")
    return (f"Making the Drive folder {name}" if name else "Making a Drive folder",
            (f"inside {parent}" if parent else ""))


@_step("manage_drive_file")
def _manage_drive(a):
    if a.get("trash"):
        return "Putting a Drive file in the bin", _arg(a, "file_id")
    name = _arg(a, "new_name")
    folder = _arg(a, "folder")
    if name and folder:
        return f"Renaming a Drive file to {name} and moving it", f"into {folder}"
    if name:
        return f"Renaming a Drive file to {name}", _arg(a, "file_id")
    if folder:
        return f"Moving a Drive file into {folder}", _arg(a, "file_id")
    return "Changing a Drive file", _arg(a, "file_id")


@_step("read_doc")
def _read_doc(a):
    named, tab = _arg(a, "document"), _arg(a, "tab")
    return (f"Reading the document {named}" if named else "Reading a Google Doc",
            f"the tab {tab}" if tab else named)


@_step("doc_changes")
def _doc_changes(a):
    named, since = _arg(a, "document"), _arg(a, "since")
    return (f"Reading what changed in {named}" if named else "Reading what changed in a Google Doc",
            f"since {since}" if since else "over the last week")


@_step("create_doc")
def _create_doc(a):
    title = _arg(a, "title")
    return (f"Writing a new document, {title}" if title else "Writing a new document",
            _arg(a, "folder") and f"in {_arg(a, 'folder')}")


@_step("edit_doc")
def _edit_doc(a):
    named = _arg(a, "document")
    edits = [e for e in (a.get("edits") or []) if isinstance(e, Mapping)]
    ops = ", ".join(str(e.get("op") or "") for e in edits if e.get("op"))
    return (f"Editing the document {named}" if named else "Editing a Google Doc",
            ops and f"{len(edits)} change" + ("s" if len(edits) != 1 else "") + f": {ops}")


@_step("edit_sheet")
def _edit_sheet(a):
    named = _arg(a, "sheet")
    tab = _arg(a, "tab")
    return (f"Writing into the sheet {named}" if named else "Writing into a Google Sheet",
            tab and f"on the tab {tab}")


@_step("copy_drive_file")
def _copy_drive_file(a):
    named = _arg(a, "file")
    return (f"Copying {named}" if named else "Copying a file in Drive", _arg(a, "name") and f"as {_arg(a, 'name')}")


@_step("block_my_time")
def _block_my_time(a):
    focus = _arg(a, "kind") == "focus"
    return ("Putting focus time on the calendar" if focus else "Putting out of office on the calendar",
            _arg(a, "start") and f"from {_arg(a, 'start')}")


@_step("to_answer")
def _to_answer(a):
    return ("Finding the emails you have not answered", _arg(a, "person"))


@_step("between_us")
def _between_us(a):
    return ("Reading what is open between you and them by email", _arg(a, "person"))


@_step("promised_to_you")
def _promised_to_you(a):
    return ("Reading what people promised you by email", _arg(a, "person"))


@_step("unread_lists")
def _unread_lists(a):
    stop = a.get("stop") if isinstance(a.get("stop"), list) else []
    if stop:
        return ("Unsubscribing from " + ", ".join(str(x) for x in stop[:3]), None)
    return ("Finding the newsletters you never open", None)


@_step("when_free")
def _when_free(a):
    people = a.get("people") if isinstance(a.get("people"), list) else []
    return ("Reading when they are free" if people else "Reading free and busy times",
            ", ".join(str(p) for p in people[:3]))


@_step("read_calendar_link")
def _read_calendar_link(a):
    return "Reading a calendar's link", _arg(a, "words") or ""


@_step("no_company")
def _no_company(a):
    return "Reading which contacts have no company", ""


@_step("same_contact")
def _same_contact(a):
    return "Reading which contacts are there twice", ""


@_step("contact_card")
def _contact_card(a):
    return "Making their card to pass on", _arg(a, "name") or ""


@_step("reply_times")
def _reply_times(a):
    return "Counting reply times", _arg(a, "who") or ""


@_step("meeting_hours")
def _meeting_hours(a):
    return "Counting your meeting time", _arg(a, "company") or _arg(a, "person") or ""


@_step("public_holidays")
def _public_holidays(a):
    return "Reading public holidays", _arg(a, "country") or ""


@_step("edit_slides")
def _edit_slides(a):
    named = _arg(a, "deck")
    return (f"Changing the deck {named}" if named else "Changing a Google Slides deck", "")


@_step("list_calendars")
def _list_calendars(a):
    return "Listing the calendars it can see", ""


@_step("list_calendar_events")
def _list_calendar_events(a):
    text = _arg(a, "text")
    start = _arg(a, "start")
    end = _arg(a, "end")
    calendar = _arg(a, "calendar")
    what = f'Searching the calendar for "{text}"' if text else "Reading the calendar"
    span = (f"{start} to {end}" if start and end and start != end else start or end)
    return what, " - ".join(one for one in (span, calendar and f"on {calendar}") if one)


@_step("read_calendar_event")
def _read_calendar_event(a):
    return "Reading a calendar event", _arg(a, "event_id")


@_step("create_calendar_event")
def _create_calendar_event(a):
    title = _arg(a, "title")
    guests = _service_list(a, "guests")
    return (f"Putting {title} on the calendar" if title else "Putting an event on the calendar",
            " - ".join(one for one in (_arg(a, "start"),
                                       guests and "inviting " + ", ".join(guests)) if one))


@_step("update_calendar_event")
def _update_calendar_event(a):
    answer = _arg(a, "answer")
    if answer:
        words = {"accepted": "Accepting", "declined": "Declining",
                 "tentative": "Saying maybe to"}.get(answer, "Answering")
        return f"{words} an invitation", _arg(a, "event_id")
    if _arg(a, "start"):
        return "Moving a calendar event", f"to {_arg(a, 'start')}"
    title = _arg(a, "title")
    return (f"Renaming a calendar event to {title}" if title else "Changing a calendar event",
            _arg(a, "event_id"))


@_step("delete_calendar_event")
def _delete_calendar_event(a):
    if a.get("confirmed"):
        return ("Deleting a calendar event" + (" and its series" if a.get("whole_series") else ""),
                _arg(a, "event_id"))
    return "Checking a calendar event before deleting it", _arg(a, "event_id")


@_step("restore_calendar_event")
def _restore_calendar_event(a):
    if a.get("confirmed"):
        return "Restoring a cancelled calendar event", _arg(a, "event_id")
    return "Checking a calendar event before restoring it", _arg(a, "event_id")


@_step("add_shared_calendar")
def _add_shared_calendar(a):
    return "Adding a shared calendar", _arg(a, "calendar_id")


@_step("create_calendar")
def _create_calendar(a):
    name = _arg(a, "name")
    return (f"Making the calendar {name}" if name else "Making a calendar"), _arg(a, "time_zone")


@_step("share_calendar")
def _share_calendar(a):
    action, email, calendar = _arg(a, "action"), _arg(a, "email"), _arg(a, "calendar")
    if action == "share":
        return (f"Sharing a calendar with {email}" if email else "Sharing a calendar",
                " - ".join(one for one in (calendar, _arg(a, "role")) if one))
    if action == "remove":
        return (f"Taking {email} off a calendar" if email else "Taking someone off a calendar",
                calendar)
    return "Reading who can see a calendar", calendar


def _generic(name: str, a: Mapping[str, Any]) -> Step:
    if name.startswith("mcp__"):
        parts = name.split("__")
        tool = parts[-1].replace("_", " ") if parts else name
        server = parts[1] if len(parts) > 2 else "a connector"
        first = next((v for v in a.values() if isinstance(v, str) and v.strip()), "")
        return f"Using {tool} from {server}", _clean(first)
    first = next((v for v in a.values() if isinstance(v, str) and v.strip()), "")
    return f"Using {name}", _clean(first)


def _as_args(tool_input: Any) -> Mapping[str, Any]:
    if isinstance(tool_input, Mapping):
        return tool_input
    if isinstance(tool_input, str) and tool_input.strip().startswith("{"):
        try:
            parsed = json.loads(tool_input)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, Mapping) else {}
    return {}


#: What a job's MCP client calls the tools of the `rouh` server (`rouh/worker_mcp.py`).
_GATEWAY = "mcp__rouh__"


def _dispatch_step(name: str, args: Mapping[str, Any]) -> Step:
    """Choose a formatter, containing errors from a strange tool payload."""
    try:
        fn = _STEPS.get(name)
        if fn is None and name.startswith(_GATEWAY):
            # A job calling one of Rouh's own tools through Rouh's gateway
            # (`rouh/job_gateway.py`): said as Rouh's own call of it is.
            fn = _STEPS.get(name[len(_GATEWAY):])
        what, detail = fn(args) if fn else _generic(name, args)
    except Exception:  # a strange payload must never cost the tree
        what, detail = f"Using {name}", ""
    return what, detail


def _sanitize_lines(what: Any, detail: Any) -> tuple[str, str | None]:
    """Hide secrets and bound display lines before callers handle duplicates."""
    return (_cap(redact(what), WHAT_MAX),
            _cap(redact(detail), DETAIL_MAX) if detail else None)


def describe_step(name: Any, tool_input: Any) -> dict[str, str | None]:
    """``{"what": ..., "detail": ...}`` for one tool call. Never raises."""
    name = str(name or "tool")
    args = _as_args(tool_input)
    what, detail = _sanitize_lines(*_dispatch_step(name, args))
    return {"what": what, "detail": detail if detail and detail != what else None}


def describe_helper(tool_input: Any) -> dict[str, str | None]:
    """A helper (a Claude Code sub-agent) by the task it was given.

    Claude Code starts one with its ``Agent`` tool (``Task`` in older builds),
    whose input carries a short ``description`` and the full ``prompt``.
    """
    args = _as_args(tool_input)
    said = _arg(args, "description")
    prompt = _arg(args, "prompt")
    what = said or (_first_sentence(prompt) if prompt else "") or "A helper"
    detail = prompt if prompt and prompt != what else ""
    what, detail = _sanitize_lines(what, detail)
    return {
        "what": what,
        "detail": detail,
        "type": _cap(_arg(args, "subagent_type"), 40) or None,
    }


def given(what: Any, detail: Any = None) -> dict[str, str | None]:
    """Words that arrive already written go through the same hiding and caps.

    Rouh's own tools describe themselves where they start, and the tree
    passes those words on only through here, so no path to the screen skips
    :func:`redact`.
    """
    what, detail = _sanitize_lines(what, detail)
    return {"what": what or None, "detail": detail if detail and detail != what else None}


def describe_doing(open_steps: Any = (), *, waiting: bool = False, helpers: Any = ()) -> str:
    """What a job or a helper is doing this moment, in one line.

    ``open_steps`` are the ``what`` lines of its steps still running, newest
    first; ``helpers`` the tasks of the helpers inside it still running. Built
    for the orb, and usable as the task list's "doing now" line as well.
    """
    if waiting:
        return "Stopped, waiting for you to answer"
    steps = [_clean(s) for s in open_steps or () if _clean(s)]
    if steps:
        tail = f" (and {len(steps) - 1} more at once)" if len(steps) > 1 else ""
        return _cap(redact(steps[0]), WHAT_MAX - len(tail)) + tail
    names = [_clean(h) for h in helpers or () if _clean(h)]
    if names:
        tail = f" (and {len(names) - 1} more)" if len(names) > 1 else ""
        return _cap(redact(f'Its helper is working on "{names[0]}"'), WHAT_MAX - len(tail)) + tail
    return "Thinking about its next step"


# ---------------------------------------------------------------------------
# A command and what it printed, on its line in the chat
# ---------------------------------------------------------------------------

#: Rouh's own tools that run a command, and the argument the command is in.
#: Their line in the chat opens onto the command and, under it, what the
#: command printed, each as the plain text it is (`COMMAND_TOOLS` in app.js).
#: Asked for on 26 September 2026: "I already know that this is a command, so
#: I don't need to see the curly braces the json the 'command:'".
COMMANDS = {"run_command": "command"}

#: The most of a command, or of what it printed, that goes to the page.
#: `run_command` already stops its output at 4,000 characters and says so
#: (`tools.run_pipeline`), so this is only a ceiling against a surprise.
SHOWN_MAX = 8000

#: What `run_command` hands the model when a command printed nothing at all.
#: The page is sent nothing instead, and says so in words of its own.
NO_OUTPUT = "(no output)"


def command_input(name: Any, tool_input: Any) -> str | None:
    """What a command tool was sent, as JSON text for its line in the chat.

    The command goes whole, where every other call's input is cut at 400
    characters (`brain._shallow`): it is the one thing its line shows, and a
    command cut short is no longer JSON, which put the braces back on screen.
    Anything secret in it is hidden, as it is on the orb. None for any tool
    that does not run a command.
    """
    key = COMMANDS.get(str(name or ""))
    if not key:
        return None
    command = str(_as_args(tool_input).get(key) or "")
    return json.dumps({key: redact(command)[:SHOWN_MAX]})


def command_output(name: Any, payload: Any) -> str | None:
    """What a command printed, line breaks and all, with anything secret hidden.

    Empty when it printed nothing, and None for any tool that does not run a
    command: only a command's line has somewhere to show all of it.
    """
    if str(name or "") not in COMMANDS:
        return None
    text = payload if isinstance(payload, str) else json.dumps(payload)
    if text.strip() == NO_OUTPUT:
        return ""
    return redact(text, _IN_OUTPUT)[:SHOWN_MAX]
