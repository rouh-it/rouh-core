"""A run's own transcript, read as a conversation: the Read tab.

On a phone a run's terminal is a poor thing to read. Claude Code draws on the
terminal's full screen, so a swipe over it travels to the server as scroll
reports, Claude Code draws its whole screen again a line further on, and the
picture comes back: it lags behind the finger, moves a line at a time and runs
on past where the finger stopped (card 723, 24 September 2026). And a long
answer set in a terminal 40 columns wide is cramped however well it scrolls.

Claude Code already writes everything a run says to a file of its own, the
transcript its hooks name (``agent.session``), one JSON record per line. This
reads that file and turns it into what a person reads: what was asked, what the
run answered, and each tool call as one line with what it was for, which the
page opens on a tap. The page scrolls it as an ordinary page scrolls, on the
phone itself.

**The file is the run's user's.** Claude Code writes it in that user's home,
readable by that user alone, and the program is another user. So it is read
through ``asuser.py transcript``, which the sudo rule already lets the program
run as that user, and which refuses any path that is not an agent's own
transcript. With ``--follow`` it stays, and hands on every line the agent adds
as it adds it, which is what makes the Read tab live.

**One follower per run, however many read it.** A follower starts when the
first connection asks to read a run and lingers a minute after the last one
stops, so flicking between Read and Terminal, or reloading, does not read the
whole file again each time. Whoever asks gets everything read so far at once,
and from then on only what changed: a new item, or a tool call whose result
has arrived.

Codex writes a transcript too, in its own shape, and the same reader takes it.

Nothing here is ever written to the list: the transcript is the agent's own
record, and it is read, never kept a second time.
"""
from __future__ import annotations

import asyncio
import contextlib
import html
import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .program import Program

log = logging.getLogger("one.transcripts")

#: How much of a tool's input, and of what came back from it, is sent at first,
#: in characters. The rest is said to be there rather than sent: a run that
#: reads a long file would otherwise send megabytes to a phone that only asked
#: to read. The whole of it is kept, and sent when the reader asks for it
#: (``Reading.whole``): a Read tab that silently lost the middle of what the
#: terminal showed was fr_631835dca7bb, 27 September 2026.
INPUT_KEEP = 2400
RESULT_KEEP = 3200
#: A prompt or a reply is sent whole up to this, which no ordinary one reaches.
TEXT_KEEP = 60_000
#: How long a follower is kept once nobody is reading it.
LINGER = 60.0
#: How long a first read may take before the page is answered with what there is.
FIRST_READ = 20.0
#: A single record longer than this is passed over rather than parsed.
LINE_MAX = 48 * 1024 * 1024
#: How long to wait before reading again after the reader stopped by itself.
AGAIN_AFTER = (1.0, 3.0, 10.0, 30.0)

#: Control characters, which a message pasted into Claude Code's box brings in
#: (the program clears the box with Ctrl-E Ctrl-U before it pastes).
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
#: A terminal's colours and cursor moves, which a ``!`` command's output keeps.
_ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|[@-Z\\-_])")


def sealed_args(run: dict[str, Any] | None) -> list[str]:
    """For a run handed boxes, while they are in its folder: the folder, so ``asuser.py
    transcript`` takes what they hold out of every line it reads (``sealed.py``). Once they
    are shredded the transcript on disk has been scrubbed of them already."""
    if not run or not run.get("boxes") or run.get("boxes_shredded") or not run.get("cwd"):
        return []
    return ["--secrets", f"{run['cwd']}/.secrets"]


def trim(text: str, keep: int) -> str:
    """The text, or its start and its end with how much is left out between."""
    text = str(text or "")
    if len(text) <= keep:
        return text
    head = keep * 3 // 4
    tail = keep - head
    gone = len(text) - keep
    return f"{text[:head].rstrip()}\n\n[{gone:,} more characters]\n\n{text[-tail:].lstrip()}"


#: Which text of an item is cut to how much when it is sent.
_KEEP = {"text": TEXT_KEEP, "detail": INPUT_KEEP, "result": RESULT_KEEP}


def sent(item: dict[str, Any]) -> dict[str, Any]:
    """An item as it is sent: each long text cut to its start and its end, and
    ``cut`` naming the ones that were, which ``Reading.whole`` sends whole."""
    out = dict(item)
    cut = []
    for field, keep in _KEEP.items():
        text = out.get(field)
        if isinstance(text, str) and len(text) > keep:
            out[field] = trim(text, keep)
            cut.append(field)
    if cut:
        out["cut"] = cut
    return out


def _clean(text: str) -> str:
    return _CONTROL.sub("", _REMINDER.sub("", str(text or ""))).strip()


def _tag(text: str, name: str) -> str:
    """What is inside the first ``<name>`` in the text."""
    found = re.search(f"<{re.escape(name)}>(.*?)</{re.escape(name)}>", text or "", re.S)
    return html.unescape(found.group(1)).strip() if found else ""


def _short(text: str, limit: int = 160) -> str:
    """One line of something, for a tool call's line."""
    line = next((part.strip() for part in str(text or "").splitlines() if part.strip()), "")
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"


def _relative(path: str, cwd: str | None) -> str:
    path = str(path or "")
    if cwd and path.startswith(cwd.rstrip("/") + "/"):
        return path[len(cwd.rstrip("/")) + 1:]
    return path


def tool_name(name: str) -> str:
    """A tool's name as a person reads it: an MCP tool says whose it is."""
    if name.startswith("mcp__"):
        server, _, tool = name[5:].partition("__")
        return f"{server} {tool}".strip()
    return name


def tool_line(name: str, args: Any, cwd: str | None = None) -> tuple[str, str, bool]:
    """What a tool call was for, in one line, and what it was given, in full.

    The line is what the Read tab shows before anybody taps; the detail is
    what opens. ``diff`` says the detail is lines taken out and put in.
    """
    a = args if isinstance(args, dict) else {}
    path = _relative(a.get("file_path") or a.get("notebook_path") or a.get("path") or "", cwd)
    if name == "Bash":
        return (_short(a.get("description") or a.get("command")),
                str(a.get("command") or ""), False)
    if name == "Read":
        span = ""
        if a.get("offset") or a.get("limit"):
            start = int(a.get("offset") or 1)
            span = f", from line {start}" + (f", {a['limit']} lines" if a.get("limit") else "")
        return path + span, "", False
    if name == "Write":
        return path, str(a.get("content") or ""), False
    if name in ("Edit", "MultiEdit"):
        edits = a.get("edits") if isinstance(a.get("edits"), list) else [a]
        lines: list[str] = []
        for edit in edits:
            if not isinstance(edit, dict):
                continue
            if lines:
                lines.append("")
            lines += ["- " + line for line in str(edit.get("old_string") or "").splitlines()]
            lines += ["+ " + line for line in str(edit.get("new_string") or "").splitlines()]
        return path, "\n".join(lines), True
    if name == "NotebookEdit":
        return path, str(a.get("new_source") or ""), False
    if name == "Grep":
        where = _relative(a.get("path") or "", cwd)
        return _short(str(a.get("pattern") or "") + (f"  in {where}" if where else "")), "", False
    if name == "Glob":
        return _short(a.get("pattern")), "", False
    if name == "WebFetch":
        return _short(a.get("url")), str(a.get("prompt") or ""), False
    if name == "WebSearch":
        return _short(a.get("query")), "", False
    if name in ("Agent", "Task"):
        return (_short(a.get("description") or a.get("subagent_type")),
                str(a.get("prompt") or ""), False)
    if name == "TodoWrite":
        todos = [t for t in (a.get("todos") or []) if isinstance(t, dict)]
        marks = {"completed": "[x]", "in_progress": "[~]"}
        return (f"{len(todos)} to-do{'s' if len(todos) != 1 else ''}",
                "\n".join(f"{marks.get(t.get('status'), '[ ]')} {t.get('content') or ''}"
                          for t in todos), False)
    if name == "Skill":
        return _short(a.get("skill") or a.get("command")), "", False
    if name == "ToolSearch":
        return _short(a.get("query")), "", False
    # Anything else, an MCP tool among them: its first short string says what
    # it was for, and the whole input is the detail.
    first = next((v for k, v in a.items() if isinstance(v, str) and v.strip()
                  and k not in ("ref", "element_ref")), "")
    detail = json.dumps(a, indent=1, ensure_ascii=False) if a else ""
    return _short(first), detail if detail != "{}" else "", False


#: A command inside a Codex script: ``exec_command({"cmd": "..."})``, with or
#: without quotes round the key.
_CODEX_CMD = re.compile(r'exec_command\(\{\s*"?cmd"?\s*:\s*"((?:[^"\\]|\\.)*)"')


def _json_string(body: str) -> str:
    """The inside of a JSON string, read; one cut off mid-escape is read up to it."""
    for end in range(len(body), max(len(body) - 6, 0) - 1, -1):
        try:
            return str(json.loads('"' + body[:end] + '"'))
        except ValueError:
            continue
    return body


def _result_text(content: Any) -> str:
    """What a tool gave back, as text. A picture is said to be one."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") in ("text", "input_text", "output_text"):
            parts.append(str(block.get("text") or ""))
        elif block.get("type") == "image":
            parts.append("[a picture]")
    return "\n".join(parts)


class Reading:
    """One transcript, record by record, as the items a person reads.

    An item is a dict with an ``id`` and a ``kind``:

    ``prompt``    what the run was asked: ``text``, and ``queued`` for a message
                  typed while it was working
    ``reply``     what it said, as Markdown: ``text``
    ``thinking``  what it thought, when the transcript has the words: ``text``
    ``tool``      one tool call: ``name``, ``line``, ``detail``, ``diff``, and
                  once it is back ``done``, ``error`` and ``result``
    ``note``      something that happened to the conversation: ``text``, and
                  ``error`` when it is the agent saying it could not go on

    A command the person typed into the terminal itself, a ``!`` command or a
    slash command, is a tool call too, with what it printed as its result, so
    everything the terminal showed is here.

    ``feed`` takes one record and hands back the items it added or changed.
    Items are kept whole; ``sent`` cuts them for sending.
    """

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self._by_id: dict[str, dict[str, Any]] = {}
        self.cwd: str | None = None
        #: The command typed into the terminal whose output comes next.
        self._typed: dict[str, Any] | None = None

    def snapshot(self) -> list[dict[str, Any]]:
        return [sent(item) for item in self.items]

    def whole(self, item_id: str) -> dict[str, Any] | None:
        """One item with nothing cut from it, for a reader who asked for all of it."""
        item = self._by_id.get(item_id)
        return dict(item) if item is not None else None

    def _add(self, item: dict[str, Any], changed: list[dict[str, Any]]) -> None:
        if item["id"] in self._by_id:
            return
        self._by_id[item["id"]] = item
        self.items.append(item)
        changed.append(item)

    def feed(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        if not isinstance(record, dict):
            return changed
        if "payload" in record and record.get("type") in (
                "response_item", "session_meta", "event_msg", "turn_context"):
            self._codex(record, changed)
            return changed
        if record.get("isSidechain"):
            return changed
        if record.get("cwd"):
            self.cwd = str(record["cwd"])
        kind = record.get("type")
        if kind == "user":
            self._user(record, changed)
        elif kind == "assistant":
            self._assistant(record, changed)
        elif kind == "attachment":
            self._attachment(record, changed)
        return changed

    # -- Claude Code ---------------------------------------------------------------

    def _user(self, r: dict[str, Any], changed: list) -> None:
        uid = str(r.get("uuid") or len(self.items))
        at = r.get("timestamp")
        content = (r.get("message") or {}).get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    self._result(block, r, changed)
            texts = [str(b.get("text") or "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            pictures = sum(1 for b in content if isinstance(b, dict) and b.get("type") == "image")
        else:
            texts, pictures = [str(content or "")], 0
        text = _clean("\n\n".join(t for t in texts if not t.lstrip().startswith("<system-reminder>")))
        if r.get("isCompactSummary"):
            self._add({"id": uid, "kind": "note", "at": at,
                       "text": "The conversation was summarised here, to make room."}, changed)
            return
        if text.startswith("Stop hook feedback:"):
            # The program's own words at the end of a turn: carry on, or commit.
            self._add({"id": uid, "kind": "prompt", "at": at, "from": "program",
                       "text": text[len("Stop hook feedback:"):].strip()}, changed)
            return
        if r.get("isMeta") or (not text and not pictures):
            return
        if text.startswith("<task-notification>"):
            said = _tag(text, "summary") or "A background task finished."
            self._add({"id": uid, "kind": "note", "at": at, "text": said}, changed)
            return
        if text.startswith("<command-name>"):
            # A slash command typed into the terminal: what it printed follows.
            name = _tag(text, "command-name") or "a command"
            args = _tag(text, "command-args")
            self._typed = {"id": uid, "kind": "tool", "at": at, "name": name,
                           "line": _short(args), "detail": args if "\n" in args else "",
                           "diff": False, "done": True, "error": False, "result": ""}
            self._add(self._typed, changed)
            return
        if text.startswith("<bash-input>"):
            # A `!` command typed into the terminal, run as it is.
            command = _tag(text, "bash-input")
            self._typed = {"id": uid, "kind": "tool", "at": at, "name": "Shell",
                           "line": _short(command), "detail": command if "\n" in command else "",
                           "diff": False, "done": False}
            self._add(self._typed, changed)
            return
        if text.startswith(("<bash-stdout>", "<bash-stderr>",
                            "<local-command-stdout>", "<local-command-stderr>")):
            # Unclean: the colours are taken out, not left as stray letters.
            self._printed(uid, at, _REMINDER.sub("", "\n\n".join(texts)), changed)
            return
        if text.startswith("<command-message>"):
            return
        if text.startswith("[Request interrupted"):
            self._add({"id": uid, "kind": "note", "at": at, "text": "Interrupted."}, changed)
            return
        if pictures:
            mark = "[a picture]" if pictures == 1 else f"[{pictures} pictures]"
            text = (text + "\n\n" + mark).strip()
        self._add({"id": uid, "kind": "prompt", "at": at, "text": text}, changed)

    def _printed(self, uid: str, at: Any, text: str, changed: list) -> None:
        """What a command typed into the terminal printed there, as its result."""
        out = "\n".join(part for part in (
            _ANSI.sub("", _tag(text, name)).strip() for name in
            ("bash-stdout", "local-command-stdout", "bash-stderr", "local-command-stderr")) if part)
        failed = not (_tag(text, "bash-stdout") or _tag(text, "local-command-stdout")) and bool(out)
        item = self._typed
        self._typed = None
        if item is None:
            if out:
                self._add({"id": uid, "kind": "note", "at": at, "error": failed, "text": out}, changed)
            return
        item.update(done=True, error=failed, result=out)
        if item not in changed:
            changed.append(item)

    def _assistant(self, r: dict[str, Any], changed: list) -> None:
        uid = str(r.get("uuid") or len(self.items))
        at = r.get("timestamp")
        message = r.get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for i, block in enumerate(content if isinstance(content, list) else []):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                text = str(block.get("text") or "").strip()
                if not text or text == "(no content)":
                    continue
                if r.get("isApiErrorMessage") or message.get("model") == "<synthetic>":
                    if r.get("isApiErrorMessage"):
                        self._add({"id": f"{uid}:{i}", "kind": "note", "at": at, "error": True,
                                   "text": _short(text, 400)}, changed)
                    continue
                self._add({"id": f"{uid}:{i}", "kind": "reply", "at": at,
                           "text": text}, changed)
            elif kind == "thinking" and str(block.get("thinking") or "").strip():
                self._add({"id": f"{uid}:{i}", "kind": "thinking", "at": at,
                           "text": str(block["thinking"]).strip()}, changed)
            elif kind in ("tool_use", "server_tool_use"):
                name = str(block.get("name") or "a tool")
                line, detail, diff = tool_line(name, block.get("input"), self.cwd)
                self._add({"id": str(block.get("id") or f"{uid}:{i}"), "kind": "tool", "at": at,
                           "name": tool_name(name), "line": line,
                           "detail": detail, "diff": diff,
                           "done": False}, changed)

    def _result(self, block: dict[str, Any], r: dict[str, Any], changed: list) -> None:
        item = self._by_id.get(str(block.get("tool_use_id") or ""))
        if item is None or item.get("kind") != "tool":
            return
        text = _result_text(block.get("content")).strip()
        item.update(done=True, error=bool(block.get("is_error")),
                    result=text)
        if item not in changed:
            changed.append(item)

    def _attachment(self, r: dict[str, Any], changed: list) -> None:
        a = r.get("attachment") or {}
        if a.get("type") != "queued_command":
            return
        uid = str(r.get("uuid") or len(self.items))
        text = _clean(a.get("prompt"))
        if a.get("commandMode") == "prompt" and text:
            self._add({"id": uid, "kind": "prompt", "at": r.get("timestamp"), "queued": True,
                       "text": text}, changed)
        elif text.startswith("<task-notification>"):
            self._add({"id": uid, "kind": "note", "at": r.get("timestamp"),
                       "text": _tag(text, "summary") or "A background task finished."}, changed)

    # -- Codex ---------------------------------------------------------------------

    def _codex(self, r: dict[str, Any], changed: list) -> None:
        p = r.get("payload") or {}
        at = r.get("timestamp")
        if r.get("type") == "session_meta" and p.get("cwd"):
            self.cwd = str(p["cwd"])
        if r.get("type") == "event_msg":
            self._codex_event(r, p, changed)
            return
        if r.get("type") != "response_item":
            return
        kind = p.get("type")
        uid = str(p.get("id") or p.get("call_id") or f"codex-{len(self.items)}")
        if kind == "message":
            texts = [str(b.get("text") or "") for b in p.get("content") or []
                     if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")]
            text = _clean("\n\n".join(texts))
            if not text:
                return
            if p.get("role") == "assistant":
                self._add({"id": uid + f":{len(self.items)}", "kind": "reply", "at": at,
                           "text": text}, changed)
            elif p.get("role") == "user" and not text.startswith(("<", "# AGENTS.md instructions")):
                self._add({"id": uid + f":{len(self.items)}", "kind": "prompt", "at": at,
                           "text": text}, changed)
        elif kind == "reasoning":
            words = "\n\n".join(str(s.get("text") or "") for s in p.get("summary") or []
                                if isinstance(s, dict)).strip()
            if words:
                self._add({"id": uid + f":{len(self.items)}", "kind": "thinking", "at": at,
                           "text": words}, changed)
        elif kind in ("function_call", "custom_tool_call", "local_shell_call"):
            name = str(p.get("name") or "shell")
            raw = p.get("arguments") if kind == "function_call" else p.get("input")
            args: Any = raw
            if isinstance(raw, str):
                with contextlib.suppress(ValueError):
                    args = json.loads(raw)
            if kind == "local_shell_call":
                args = (p.get("action") or {})
            command = ""
            if isinstance(args, dict):
                command = args.get("command") or args.get("cmd") or ""
                if isinstance(command, list):
                    command = " ".join(str(c) for c in command[2:] if c) \
                        if command[:2] in (["bash", "-lc"], ["sh", "-c"]) else " ".join(map(str, command))
            if not command and isinstance(args, str):
                # Codex's own code mode: a script that calls its tools, whose
                # commands are what a person wants to see (Codex 0.154).
                found = [_json_string(c) for c in _CODEX_CMD.findall(args)]
                command = "\n".join(c for c in found if c)
            if command:
                line, detail = _short(command), str(command)
            elif isinstance(args, str):
                files = re.findall(r"\*\*\* (?:Update|Add|Delete) File: ([^\n\\\"]+)", args)
                line = ", ".join(_relative(f, self.cwd) for f in files) or _short(args)
                detail = args
            else:
                line, detail, _ = tool_line(name, args, self.cwd)
            self._add({"id": str(p.get("call_id") or uid), "kind": "tool", "at": at,
                       "name": name, "line": line, "detail": detail,
                       "diff": False, "done": False}, changed)
        elif kind in ("function_call_output", "custom_tool_call_output", "local_shell_call_output"):
            item = self._by_id.get(str(p.get("call_id") or ""))
            if item is None:
                return
            out = p.get("output")
            if isinstance(out, dict):
                out = out.get("content") or out.get("output") or ""
            if isinstance(out, str):
                with contextlib.suppress(ValueError):
                    parsed = json.loads(out)
                    if isinstance(parsed, dict):
                        out = parsed.get("output") or out
            item.update(done=True, error=False, result=_codex_output(out))
            if item not in changed:
                changed.append(item)


    def _codex_event(self, r: dict[str, Any], p: dict[str, Any], changed: list) -> None:
        """What Codex says on its screen and nowhere else: that a turn ended in
        an error, such as its account being out of credits."""
        kind = p.get("type")
        at = r.get("timestamp")
        uid = f"codex-{len(self.items)}"
        if kind == "task_complete" and isinstance(p.get("error"), dict):
            said = str(p["error"].get("message") or "").strip() or "It stopped with an error."
            self._add({"id": uid, "kind": "note", "at": at, "error": True, "text": said}, changed)
        elif kind in ("error", "stream_error") and p.get("message"):
            self._add({"id": uid, "kind": "note", "at": at, "error": True,
                       "text": str(p["message"]).strip()}, changed)
        elif kind == "turn_aborted":
            self._add({"id": uid, "kind": "note", "at": at, "text": "Interrupted."}, changed)


#: What Codex puts before a result it cut short for the model.
_CODEX_CUT = re.compile(r"Warning: truncated output \([^)]*\)\nTotal output lines: \d+\n\n")
#: A command's output inside a Codex result, whose end may have been cut off.
_CODEX_OUTPUT = re.compile(r'"output":"((?:[^"\\]|\\.)*)("?)')


def _codex_output(out: Any) -> str:
    """What a Codex tool call gave back, as the terminal showed it.

    A command's result inside a script's output is JSON, and here it is what
    the command printed instead, with its exit code when that was not 0. When
    Codex cut a result short, the JSON is cut too, so what can be read of it
    is read.
    """
    if isinstance(out, dict):
        out = out.get("content") or out.get("output") or ""
    blocks = [{"type": "text", "text": out}] if isinstance(out, str) else out
    shown = []
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") in ("image", "input_image"):
            shown.append("[a picture]")
            continue
        if block.get("type") not in ("text", "input_text", "output_text"):
            continue
        text = str(block.get("text") or "")
        if re.match(r"Script completed\nWall time [^\n]*\nOutput:\n?$", text):
            continue
        body = _CODEX_CUT.sub("", text, count=1)
        parsed: Any = None
        with contextlib.suppress(ValueError):
            parsed = json.loads(body)
        if isinstance(parsed, dict):
            text = _codex_value(parsed)
        elif body.lstrip().startswith("{") and _CODEX_OUTPUT.search(body):
            text = "\n\n".join(_json_string(m.group(1)) + ("" if m.group(2) else "\n[cut short]")
                                for m in _CODEX_OUTPUT.finditer(body))
        if text.strip():
            shown.append(text.strip())
    return "\n\n".join(shown)


def _codex_value(value: dict[str, Any]) -> str:
    """A result inside a Codex script's output: what the command printed."""
    if isinstance(value.get("result"), dict):
        value = value["result"]
    if isinstance(value.get("value"), dict):
        value = value["value"]
    if isinstance(value.get("output"), str):
        text = value["output"].rstrip()
        code = value.get("exit_code")
        if code not in (0, None):
            text = (text + f"\n[exit code {code}]").strip()
        elif not text and value.get("session_id") and "exit_code" not in value:
            text = "[still running]"
        return text
    if isinstance(value.get("content"), list):
        # An MCP tool's answer.
        return _result_text(value["content"])
    if value.get("status") == "rejected":
        return str(value.get("reason") or "It failed.")
    return json.dumps(value, indent=1, ensure_ascii=False)


#: A sub-agent's id in what its call handed back (``agentId``).
_AGENT_ID = re.compile(r"agentId\W{1,4}([a-z0-9]{6,40})")


def _calls_of(records: list[dict[str, Any]], agent: str) -> list[dict[str, Any]]:
    """The tool calls in a transcript's records, whole, each marked with whose they are."""
    reading = Reading()
    for record in records:
        reading.feed(record)
    out = []
    for item in reading.items:
        if item.get("kind") != "tool":
            continue
        name = str(item.get("name") or "")
        out.append({"name": name, "line": str(item.get("line") or ""),
                    "detail": "" if name in ("Write", "NotebookEdit") else
                    str(item.get("detail") or ""), "agent": agent})
    return out


class Follower:
    """One run's transcript, read as it grows, for everybody reading it."""

    def __init__(self, owner: "Transcripts", run_id: str, path: str, user: str) -> None:
        self.owner = owner
        self.run_id = run_id
        self.path = path
        self.user = user
        self.reading = Reading()
        self.watchers: set[Any] = set()
        self.ready = asyncio.Event()
        #: Why it cannot be read, in words, when it cannot.
        self.why = ""
        #: Where the reader has got to in the file, which is where it starts again.
        self._offset = 0
        self._proc: asyncio.subprocess.Process | None = None
        self._stopping = False
        self._linger: asyncio.TimerHandle | None = None
        self.task = asyncio.create_task(self._run(), name=f"transcript-{run_id}")

    def push(self, message: dict[str, Any]) -> None:
        for client in list(self.watchers):
            client.push(message)

    async def _run(self) -> None:
        attempt = 0
        while not self._stopping:
            started = asyncio.get_running_loop().time()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read()
            if self._stopping or self.why:
                break
            # It stopped by itself: its own time ran out, or it could not be
            # started. Read again, from where it had got to, a little later.
            if asyncio.get_running_loop().time() - started > 60:
                attempt = 0
            await asyncio.sleep(AGAIN_AFTER[min(attempt, len(AGAIN_AFTER) - 1)])
            attempt += 1
        self.ready.set()

    async def _read(self) -> None:
        docs = self.owner.p.documents
        argv = docs.asuser_argv("transcript", "--path", self.path, "--from", str(self._offset),
                                "--follow", *sealed_args(self.owner.p.views.runs.get(self.run_id)),
                                user=self.user)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
        except OSError as exc:
            log.warning("could not read the transcript of %s: %s", self.run_id, exc)
            return
        self._proc = proc
        buffer = bytearray()
        skipping = False
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(1 << 16)
                if not chunk:
                    break
                buffer += chunk
                changed: dict[str, dict[str, Any]] = {}
                marked = False
                while True:
                    cut = buffer.find(b"\n")
                    if cut < 0:
                        if len(buffer) > LINE_MAX:
                            buffer.clear()
                            skipping = True
                        break
                    line = bytes(buffer[:cut])
                    del buffer[:cut + 1]
                    if skipping:
                        skipping = False
                        continue
                    if line.startswith(b"#"):
                        marked |= self._mark(line.decode("utf-8", "replace"))
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    for item in self.reading.feed(record):
                        changed[item["id"]] = item
                if changed and self.ready.is_set():
                    self.push({"t": "transcript", "run": self.run_id,
                               "items": [sent(i) for i in changed.values()]})
                if marked and not self.ready.is_set():
                    self.ready.set()
                if self.why:
                    self.push({"t": "transcript", "run": self.run_id, "items": [],
                               "why": self.why})
                    break
        finally:
            self._proc = None
            with contextlib.suppress(ProcessLookupError, OSError):
                if proc.stdin:
                    proc.stdin.close()
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                with contextlib.suppress(asyncio.TimeoutError, ProcessLookupError):
                    await asyncio.wait_for(proc.wait(), 5)

    def _mark(self, line: str) -> bool:
        """One of the reader's own lines. True when it has caught up."""
        word, _, rest = line[1:].partition(" ")
        if word == "at":
            with contextlib.suppress(ValueError):
                self._offset = int(rest)
            return True
        if word == "reset":
            # The file was cut back, so it is read again from the start.
            self.reading = Reading()
            self._offset = 0
            if self.ready.is_set():
                self.push({"t": "transcript", "run": self.run_id, "reset": True, "items": []})
            return False
        if word == "refused":
            self.why = rest or "that is not a transcript the program may read"
            return True
        return False

    def linger(self) -> None:
        """Nobody is reading it now: stop in a minute, unless somebody comes back."""
        self.cancel_linger()
        self._linger = asyncio.get_running_loop().call_later(
            LINGER, lambda: None if self.watchers else self.owner.drop(self))

    def cancel_linger(self) -> None:
        if self._linger is not None:
            self._linger.cancel()
            self._linger = None

    async def stop(self) -> None:
        self._stopping = True
        self.cancel_linger()
        proc = self._proc
        if proc is not None:
            with contextlib.suppress(ProcessLookupError, OSError):
                if proc.stdin:
                    proc.stdin.close()
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
        self.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self.task


class Transcripts:
    """Every run somebody is reading, and who is reading it."""

    def __init__(self, program: "Program") -> None:
        self.p = program
        self.followers: dict[str, Follower] = {}
        #: Connections that asked to read a run before it had a transcript.
        self.waiting: dict[str, set[Any]] = {}

    def _user_for(self, run: dict[str, Any]) -> str:
        return self.p.settings.space(run.get("space")).user

    def _follower(self, run: dict[str, Any]) -> Follower:
        f = self.followers.get(run["id"])
        if f is not None and f.path != run["transcript"]:
            self.drop(f)
            f = None
        if f is None:
            f = Follower(self, run["id"], str(run["transcript"]), self._user_for(run))
            self.followers[run["id"]] = f
        f.cancel_linger()
        return f

    async def read(self, client: Any, run_id: str, *, watch: bool) -> dict[str, Any]:
        """Everything read of a run's transcript so far, and, with ``watch``,
        every change after it pushed to ``client``."""
        run = self.p.views.runs[run_id]
        if run.get("kind") != "agent":
            return {"items": [], "found": False,
                    "why": "A shell keeps no transcript: its terminal is the whole of it."}
        if not run.get("transcript"):
            if watch:
                self.waiting.setdefault(run_id, set()).add(client)
            return {"items": [], "found": False, "waiting": True,
                    "why": "Its transcript appears here once it has started."}
        f = self._follower(run)
        if watch:
            f.watchers.add(client)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(f.ready.wait()), FIRST_READ)
        if not watch and not f.watchers:
            f.linger()
        if f.why:
            return {"items": [], "found": False, "why": f.why}
        return {"items": f.reading.snapshot(), "found": True}

    def whole(self, run_id: str, item_id: str) -> dict[str, Any]:
        """One item of a run being read, with nothing cut from it: what the
        page's Show all asks for."""
        f = self.followers.get(run_id)
        item = f.reading.whole(item_id) if f is not None else None
        if item is None:
            raise ValueError("that part of its transcript is not being read now; open Read again")
        return {"item": item}

    def leave(self, client: Any, run_id: str) -> None:
        """``client`` has stopped reading this run."""
        waiting = self.waiting.get(run_id)
        if waiting is not None:
            waiting.discard(client)
            if not waiting:
                self.waiting.pop(run_id, None)
        f = self.followers.get(run_id)
        if f is not None and client in f.watchers:
            f.watchers.discard(client)
            if not f.watchers:
                f.linger()

    def forget(self, client: Any) -> None:
        """A connection has closed: it reads nothing any more."""
        for run_id in list(self.waiting):
            self.leave(client, run_id)
        for run_id, f in list(self.followers.items()):
            if client in f.watchers:
                self.leave(client, run_id)

    def hear(self, entry: dict[str, Any]) -> None:
        """A run that somebody is waiting to read has told the program where its
        transcript is: start reading it, and send them what there is."""
        if entry.get("kind") != "agent.session":
            return
        run_id = entry.get("run") or ""
        run = self.p.views.runs.get(run_id)
        if run is None or not run.get("transcript"):
            return
        waiting = self.waiting.pop(run_id, set())
        f = self.followers.get(run_id)
        if not waiting and (f is None or f.path == run["transcript"]):
            return
        watchers = set(waiting) | (set(f.watchers) if f is not None else set())
        f = self._follower(run)
        f.watchers |= watchers
        asyncio.get_running_loop().create_task(self._send_first(f))

    async def calls(self, run_id: str) -> dict[str, Any]:
        """Every tool call a run made, and every call its sub-agents made, whole.

        What a reader of a run uses to see whether what it did stayed in the
        workspace or reached somebody (card 1307, 6 October 2026). The Read tab's own
        reading leaves a sub-agent's calls out - they are in files of their
        own, `<transcript>/subagents/agent-<id>.jsonl`, named by the agent id
        in the call's result - so they are read here as well, through the same
        ``asuser.py transcript``, which reads only an agent's own transcript.

        Each call is ``name``, ``line`` and ``detail`` exactly as the Read tab
        has them, never cut, and ``agent``, the sub-agent's id or "". What a
        file write put in the file is left out: the path says where it went.
        ``found`` is False, with ``why``, when the run's transcript could not
        be read; ``unread`` names each sub-agent whose own could not.
        """
        run = self.p.views.runs[run_id]
        if run.get("kind") != "agent":
            return {"found": False, "calls": [], "why": "a shell keeps no transcript"}
        path = str(run.get("transcript") or "")
        if not path:
            return {"found": False, "calls": [], "why": "it never said where its transcript is"}
        user = self._user_for(run)
        records, why = await self._whole(path, user, sealed_args(run))
        if why:
            return {"found": False, "calls": [], "why": why}
        calls = _calls_of(records, "")
        agents = list(dict.fromkeys(_AGENT_ID.findall(
            "\n".join(json.dumps(r.get("toolUseResult") or "") for r in records
                      if isinstance(r, dict) and r.get("toolUseResult")))))
        unread = []
        base = path[:-len(".jsonl")] if path.endswith(".jsonl") else path
        for agent in agents:
            inner, why = await self._whole(f"{base}/subagents/agent-{agent}.jsonl", user,
                                           sealed_args(run))
            if why:
                unread.append(agent)
                continue
            calls += _calls_of([{k: v for k, v in r.items() if k != "isSidechain"}
                                for r in inner if isinstance(r, dict)], agent)
        return {"found": True, "calls": calls, "agents": agents, "unread": unread}

    async def _whole(self, path: str, user: str,
                     sealed: list[str] = ()) -> tuple[list[dict[str, Any]], str]:
        """A transcript's records as they are now, read once, or why it could not be read."""
        argv = self.p.documents.asuser_argv("transcript", "--path", path, "--from", "0",
                                            *sealed, user=user)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL)
            out, _ = await asyncio.wait_for(proc.communicate(), 60)
        except (OSError, asyncio.TimeoutError) as exc:
            return [], f"its transcript could not be read ({exc or type(exc).__name__})"
        records: list[dict[str, Any]] = []
        for line in out.splitlines():
            if line.startswith(b"#refused"):
                return [], line[1:].decode("utf-8", "replace")
            if line.startswith(b"#"):
                continue
            with contextlib.suppress(ValueError):
                record = json.loads(line)
                if isinstance(record, dict):
                    records.append(record)
        if not records:
            return [], "its transcript is empty or gone"
        return records, ""

    async def _send_first(self, f: Follower) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(asyncio.shield(f.ready.wait()), FIRST_READ)
        f.push({"t": "transcript", "run": f.run_id, "reset": True,
                "items": f.reading.snapshot(), "why": f.why or None})

    def drop(self, f: Follower) -> None:
        if self.followers.get(f.run_id) is f:
            del self.followers[f.run_id]
        asyncio.get_running_loop().create_task(f.stop())

    async def close(self) -> None:
        followers = list(self.followers.values())
        self.followers.clear()
        self.waiting.clear()
        for f in followers:
            await f.stop()
