"""What Rouh reads in a chat, and the one place the person sets it: Chat Options (until 16 November 2026 "What I'm reading").

Petar, 15 November 2026, in the chat "Chat Change Planning":

    "by default we are including the task, the goal, the agent the mds the html. no subtasks. I should be able
    to manage those - include subtasks, all, some, mds only, htmls only, chat histories..."

    "context controls should be unified everywhere. same icon, same location, same interface."

So every chat has the same settings, kept on the chat (`Chat.reading`), and the same panel beside the composer
draws them (`readingPaint` in app/reading.js):

- **In every chat**: memory (Synapse's background memory and what the message found in it), the person's own
  rules, and tools. Each on unless the person turns it off for this chat. Rules about permission, privacy and
  safety are never turned off with the rest (`locked`): turning "Your rules" off leaves them, and Rouh's own
  built-in rules, as they are.
- **In a task's chat** (or a subtask's, which is a task inside a task), what the task is: its record (number,
  name, status, summary, meta), the goal when the task is one (`goal.md`), its `AGENTS.md`, and its notes
  (`.md`) and pages (`.html`), read from its folder in the workspace. No subtask by default. The person can
  add every subtask or chosen ones, of each everything, its notes only or its pages only, the subtasks'
  chat histories, and the folder's other files, in the strip's panel (below). The panel says "subtasks"
  since 17 November 2026 (Petar: "rename steps to subtasks"); the keys kept on a chat still say steps.
- **Sizes**: each item is labelled short, long or very long from its tokens (`size_word`). What is included
  is read whole up to `BUDGET` tokens; past it, the largest items are read as an outline (their headings and
  first lines) and the panel and the model are both told which (`plan`). Nothing is blown into the prompt
  blindly: a subtask of a million tokens is an outline.

- **Modes** (Petar, 16 November 2026: "we still don't have quick chat mode, which we should, because most of
  the times people will not know what to choose"): a chat is on one of three, picked at the top of Chat
  Options like the model. *Simple chat* (`SIMPLE`) is Memory and Your rules off, and Tools on demand: the
  system prompt is the minimal one of an all-off chat, the catalogue of tools, and each tool's own
  instructions only once the model loads it (`light`), so a quick web search still works and the turn is fast
  and cheap. It is not incognito: the chat is kept. *Full capabilities* is everything on, and in a task's chat
  the task's default content. *Custom* is the switches one by one, as they were before; changing any of them
  puts the chat on Custom by itself. The mode is the chat's own, the way the model beside it is
  (`chatkinds.choice_of`; Petar, 16 November 2026: "behavior should be like smart/cheap selection"): a choice
  stays with its chat, a fork carries on with its parent's (`forks.fork`), and every new chat starts on
  Rouh's default, Full for General, forks and task chats, Simple for an incognito chat (`incognito.start`).
  Nothing is saved for new chats any more: "Start new chats like this" is gone, and the choices it saved
  were forgotten (`0256_forget_saved_chat_options`).

**Two controls, one job each** (Petar, 16 November 2026: "I hate duplicate stuff ... the bar on the top we can
use to control the contents ... while bottom includes rules, tools, memory, this should control the other
content"). Chat Options, by the box, is how Rouh works: the mode, memory, rules and tools (`SWITCH_KEYS`). The
strip under the chat's title is what the chat is about (`CONTENT_KEYS`), with a panel of its own: This task
(on), Other files in the folder (off), Subtasks (off; all or chosen; everything, notes only or pages only),
Subtasks' chat histories (off); in a subtask's chat Parent task (on, `subtasknotes.background`) and Parent task's
chat history (off); in a fork one row for each parent chat, each with its own switch (on, `parent_on`, read by
`memory.Memory._window` through `parents_off`), and the chat itself under them.
A mode never changes what the chat is about, and Reset to defaults leaves it. Each choice is listed with its
size whether it is on or not; what is left out is sized from the file or the database and never read
(`items`, `GROUPS`, `content`).

`block` is what a turn of a task's chat is told (`brain.Brain._system`), `switches` what the turn does with
memory, rules and tools, `view` what the panels draw, and `strip` the one line under the chat's title that
says in plain words what the chat is about.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

log = logging.getLogger("rouh.reading")

#: The defaults. How Rouh works (Chat Options, beside the box): Full capabilities, memory, rules and tools on.
#: What the chat is about (the strip under its title, since 17 November 2026): the task whole, its other
#: files, subtasks and their chats left out; a subtask's chat reads its parent task as background and not the
#: parent's chats; a fork carries the conversation it came off, as it always has (`memory.Memory._window`).
DEFAULTS = {"mode": "full", "memory": True, "rules": True, "tools": True, "off": [],
            "task": True, "others": False, "subtasks": "none", "picked": [], "steps_what": "all",
            "step_histories": False, "parent_task": True, "parent_task_history": False, "fork_history": True,
            "parents": {}}
#: The three modes, as the selector at the top of Chat Options names them.
MODES = ("simple", "full", "custom")
MODE_NAMES = {"simple": "Simple chat", "full": "Full capabilities", "custom": "Custom"}
#: What Simple chat and Full capabilities set; Custom is whatever the switches say. A mode is how Rouh works
#: and nothing about what the chat is about (Petar, 16 November 2026: "while bottom includes rules, tools,
#: memory, this should control the other content").
SIMPLE = {"memory": False, "rules": False, "tools": True, "off": []}
FULL = {"memory": True, "rules": True, "tools": True, "off": []}
#: The switches a mode sets, and which Custom leaves to the person one by one.
SWITCH_KEYS = ("memory", "rules", "tools", "off")
#: What the chat is about: set in the strip's panel, never by a mode, kept with the chat.
CONTENT_KEYS = ("task", "others", "subtasks", "picked", "steps_what", "step_histories", "parent_task",
                "parent_task_history", "fork_history", "parents")
SUBTASKS = ("none", "all", "some")
#: Of each subtask that is read: everything, its notes (.md) only, or its pages (.html) only.
STEPS_WHAT = ("all", "md", "html")
#: What the included items may take of a turn, in tokens, before the largest are read as outlines.
BUDGET = 60_000
#: Short, long and very long: under 2,000 tokens, under 20,000, and the rest.
SHORT, LONG = 2_000, 20_000
#: The most of one outline, in characters, and of one file read at all (a file larger is an outline at once).
OUTLINE_CHARS = 2_400
READ_MOST = 4_000_000
#: The most files of a kind read from one folder, and the most rows of one chat history.
MOST_FILES = 60
HISTORY_ROWS = 200


def _chat_row(chat_id: str):
    from .models.objects import Chat

    return Chat.objects.filter(id=chat_id).first()


def mode_of(stored: dict) -> str:
    """The mode a stored set of choices is on. One kept before the modes (16 November 2026) has none: it is
    Full when it changed nothing from the defaults, else Custom, so no switch the person set is lost."""
    mode = stored.get("mode")
    if mode in MODES:
        return mode
    differs = any(k in stored and stored[k] != DEFAULTS[k] for k in SWITCH_KEYS)
    return "custom" if differs else "full"


def _on_mode(got: dict) -> dict:
    """The settings with what their mode sets put in: Simple and Full set every switch, Custom none."""
    if got["mode"] == "simple":
        got.update({k: (list(v) if isinstance(v, list) else v) for k, v in SIMPLE.items()})
    elif got["mode"] == "full":
        got.update({k: (list(v) if isinstance(v, list) else v) for k, v in FULL.items()})
    return got


def settings(chat_id: str, who=None) -> dict:
    """This chat's settings: Rouh's defaults under what this chat set, with what its mode sets on top
    (`_on_mode`). `who` is kept for the callers; the settings are the chat's alone."""
    row = _chat_row(chat_id) if chat_id else None
    got = dict(DEFAULTS)
    own = row.reading if row is not None and isinstance(row.reading, dict) else {}
    got.update({k: v for k, v in own.items() if k in DEFAULTS})
    if own:
        got["mode"] = mode_of(own) if "mode" in own or any(k in own for k in SWITCH_KEYS) else got["mode"]
    if got["mode"] not in MODES:
        got["mode"] = "full"
    if got["subtasks"] not in SUBTASKS:
        got["subtasks"] = "none"
    if got["steps_what"] not in STEPS_WHAT:
        got["steps_what"] = "all"
    got["picked"] = [str(x) for x in got.get("picked") or []][:200]
    got["parents"] = _parents_of(got.get("parents"))
    got["off"] = sorted({str(x) for x in got.get("off") or []})[:500]
    return _on_mode(got)


def _parents_of(v) -> dict[str, bool]:
    """Each parent chat this chat chose on or off, by its id: {} when none was chosen one by one."""
    if not isinstance(v, dict):
        return {}
    return {str(k): bool(x) for k, x in list(v.items())[:64] if str(k)}


def parent_on(s: dict, parent_id: str) -> bool:
    """Whether this chat is sent the part it carries of that parent chat. Each parent chat is its own
    choice since 18 November 2026 (Petar: "with a separate toggle for each"); one never chosen by itself
    follows the one switch every parent chat had before (`fork_history`), so a chat that had turned it off
    has every parent chat off, and one that had it on has every one on."""
    got = _parents_of(s.get("parents"))
    return got[parent_id] if parent_id in got else bool(s.get("fork_history", True))


def parents_off(chat_id: str) -> frozenset:
    """The parent chats this chat leaves out (`memory.Memory._window`, `recall.chain`). None when it cannot
    be read: a turn is never lost to its settings, and carries what it always has."""
    from . import forks

    try:
        row = _chat_row(chat_id) if chat_id else None
        own = row.reading if row is not None and isinstance(row.reading, dict) else {}
        if not own or ("parents" not in own and own.get("fork_history", True)):
            return frozenset()
        return frozenset(p for p, _at in forks.carried_chain(chat_id) if not parent_on(own, p))
    except Exception:  # noqa: BLE001
        log.exception("which parent chats chat %s leaves out could not be read", chat_id)
        return frozenset()


def put(chat_id: str, change: dict, who=None) -> dict:
    """Change some of this chat's settings; what it is now. Unknown keys are ignored.

    `reset` puts how Rouh works back on Rouh's defaults (Chat Options' Reset to defaults) and leaves what the
    chat is about as it was. Every choice is this chat's own: none is kept for new chats (the model beside it
    works the same way). A choice of what the chat is about never moves the mode."""
    from .models.objects import Chat

    row = _chat_row(chat_id)
    if row is None:
        from . import conversations

        # A draft becomes the chat when the person sets what it reads, as when they first say something.
        if conversations.draft(chat_id):
            conversations.make(chat_id)
            row = _chat_row(chat_id)
    if row is None:
        raise LookupError("There is no such chat.")
    now = dict(row.reading or {}) if isinstance(row.reading, dict) else {}
    change = dict(change or {})
    if change.pop("reset", False):
        # Rouh's defaults: Full capabilities, nothing left out. An incognito chat goes back to Simple chat,
        # as it started (`incognito.start`).
        content = {k: v for k, v in now.items() if k in CONTENT_KEYS}
        now = {"mode": "simple"} if row.incognito else {"mode": "full"}
        now.update(content)
        Chat.objects.filter(id=chat_id).update(reading=now)
        return settings(chat_id, who)
    before = settings(chat_id, who)
    mode = change.pop("mode", None)
    if mode in MODES:
        now["mode"] = mode
        if mode == "custom":
            # Custom starts from where the chat was, so its switches show what it was using.
            now.update({k: before[k] for k in SWITCH_KEYS})
    elif any(k in change for k in SWITCH_KEYS):
        # A switch changed by hand puts the chat on Custom, starting from what its mode had set.
        if before["mode"] != "custom":
            now.update({k: before[k] for k in SWITCH_KEYS})
        now["mode"] = "custom"
    if "parents" in change or "fork_history" in change:
        # One choice for each parent chat, kept by its id. The first one made by itself writes every parent
        # chat down as it was, from the one switch they all had until 18 November 2026 (`fork_history`), so
        # pressing one never moves another; Parent chat history sent as one still sets them all.
        from . import forks

        chain = [p for p, _at in forks.carried_chain(chat_id)]
        if "fork_history" in change:
            whole = bool(change.pop("fork_history"))
            mine = {p: whole for p in chain}
        else:
            mine = {p: parent_on(now, p) for p in chain}
        asked = _parents_of(change.pop("parents", None))
        mine.update({p: v for p, v in asked.items() if p in chain})
        now["parents"] = mine
        now.pop("fork_history", None)
    for k, v in change.items():
        if k not in DEFAULTS or k in ("mode", "parents"):
            continue
        if k == "subtasks":
            if v in SUBTASKS:
                now[k] = v
        elif k == "steps_what":
            if v in STEPS_WHAT:
                now[k] = v
        elif k == "picked":
            now[k] = [str(x) for x in (v or [])][:200]
        elif k == "off":
            now[k] = sorted({str(x) for x in (v or []) if str(x)})[:500]
        else:
            now[k] = bool(v)
    now.pop("keep", None)   # the old "Start new chats like this", gone since 16 November 2026
    for old in ("md", "html", "histories"):   # the task's switches in Chat Options until 17 November 2026
        now.pop(old, None)
    Chat.objects.filter(id=chat_id).update(reading=now)
    return settings(chat_id, who)


# --- what is in a task --------------------------------------------------------------------------


def tokens(text: str) -> int:
    """How many tokens these words are when they are sent (`tokencount.text`, fitted on the model's own
    count; until 17 November 2026 a quarter of the characters, which was a third out)."""
    from . import tokencount

    return tokencount.text(text or "")


def size_word(n: int) -> str:
    return "short" if n < SHORT else "long" if n < LONG else "very long"


class _Text(HTMLParser):
    """The words of a page: no script, no style, a line for each block."""

    BLOCKS = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "br", "td",
              "th", "header", "footer", "nav", "main", "aside", "blockquote", "pre", "dt", "dd", "figcaption"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template", "svg", "noscript"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.out.append("\n")
        if tag in ("h1", "h2", "h3", "h4") and not self.skip:
            self.out.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template", "svg", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(source: str) -> str:
    p = _Text()
    try:
        p.feed(source)
        p.close()
    except Exception:  # noqa: BLE001 - a broken page still has words
        return re.sub(r"<[^>]+>", " ", html.unescape(source))
    text = "".join(p.out)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def outline(text: str) -> str:
    """The headings and the first line under each, to `OUTLINE_CHARS`."""
    out: list[str] = []
    take_next = True
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            out.append(line)
            take_next = True
        elif take_next:
            out.append(line[:240])
            take_next = False
        if sum(len(x) + 1 for x in out) > OUTLINE_CHARS:
            break
    got = "\n".join(out)[:OUTLINE_CHARS]
    return got or (text or "")[:OUTLINE_CHARS]


@dataclass
class Item:
    """One thing a chat may read about what it is about."""

    id: str
    kind: str            # task, goal, agents, md, html, other, history, parent, fork
    label: str
    owner: str = ""      # the task it is part of, as "68" or "68-01"
    path: str = ""       # in the workspace, for a file
    tokens: int = 0
    on: bool = True
    how: str = "whole"   # whole, outline, or off
    text: str = field(default="", repr=False)
    #: Which choice in the strip's panel brings it in (`GROUPS`).
    group: str = "task"
    #: Told by another part of the prompt (the parent task's background, a fork's carried conversation), so
    #: never in `block` and never counted against `BUDGET`: listed only for its size.
    elsewhere: bool = False

    @property
    def sent(self) -> int:
        """The tokens of what is sent of it: its outline when it is read as one, else all of it. A choice
        left out is sized as what it would send."""
        return tokens(outline(self.text)) if self.how == "outline" and self.text else self.tokens

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "owner": self.owner, "path": self.path,
                "size": size_word(self.sent), "tokens": self.sent, "on": self.on, "how": self.how,
                "group": self.group}


def _root() -> Path | None:
    from . import conversations

    root = conversations._root()
    return Path(root) if root else None


def _label(task) -> str:
    from . import subtasknotes

    return subtasknotes.label(task)


def _record(task) -> str:
    """A task's own record: number, name, status, summary and meta, from its row."""
    from .models.objects import Task

    row = Task.objects.filter(id=task.id).values("status", "summary", "meta", "state").first() or {}
    lines = [f"Task {_label(task)}", f"Folder: {task.folder or '(none)'}",
             f"Status: {row.get('status') or row.get('state') or 'unknown'}"]
    if row.get("summary"):
        lines.append("Summary: " + " ".join(str(row["summary"]).split()))
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    if meta:
        import json

        keep = {k: v for k, v in meta.items() if k not in ("history",)}
        lines.append("Meta: " + json.dumps(keep, ensure_ascii=False, default=str)[:6000])
    return "\n".join(lines)


#: "Other files in the folder": the text files of a task's folder that are neither notes nor pages.
OTHER_SUFFIXES = (".txt", ".csv", ".tsv", ".json", ".yml", ".yaml", ".toml", ".ini", ".xml", ".py", ".js",
                  ".mjs", ".ts", ".css", ".sql", ".sh", ".log", ".tex", ".rst")


def _files(folder: Path, suffixes) -> list[Path]:
    """The files of these kinds in a task's own folder and its own subfolders that are not steps, by name."""
    from . import subtasknotes

    if isinstance(suffixes, str):
        suffixes = (suffixes,)
    out: list[Path] = []
    if not folder.is_dir():
        return out
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() not in suffixes or not p.is_file():
            continue
        rel = p.relative_to(folder)
        parts = rel.parts[:-1]
        # A step's folder is a subtask's, read only when the subtask is; scratch and hidden folders never.
        if any(subtasknotes.step_of_folder(x) or x.startswith(".") or x in ("temp", "node_modules", "images")
               for x in parts):
            continue
        if p.name.upper() == "AGENTS.MD" and not parts:
            continue
        if p.name.startswith("."):
            continue
        out.append(p)
        if len(out) >= MOST_FILES:
            break
    return out


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > READ_MOST:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                return f.read(READ_MOST)
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


#: The tokens of a file left out, by (path, its size, when it changed): what a choice would bring in is sized
#: the same whether it is on or off, and a file is read for it once until it changes.
_SIZED: dict[tuple, int] = {}


def _sized(path: Path, page: bool = False) -> int:
    """How many tokens a file left out comes to: the same count as when it is read (a page's words, not its
    markup), kept until the file changes, so it is worked out once."""
    try:
        st = path.stat()
    except OSError:
        return 0
    key = (str(path), st.st_size, st.st_mtime_ns)
    got = _SIZED.get(key)
    if got is None:
        raw = _read(path)
        got = tokens(html_text(raw) if page else raw)
        if len(_SIZED) > 20_000:
            _SIZED.clear()
        _SIZED[key] = got
    return got


def _file(kind: str, p: Path, folder: Path, root: Path, owner: str, group: str, read: bool) -> Item:
    rel = str(p.relative_to(root))
    it = Item(id=f"{kind}:{rel}", kind=kind, label=str(p.relative_to(folder)), owner=owner, path=rel,
              group=group, on=read)
    if read:
        raw = _read(p)
        it.text = html_text(raw) if kind == "html" else raw
        it.tokens = tokens(it.text)
    else:
        it.tokens = _sized(p, page=kind == "html")
    return it


def _task_items(task, owner: str, root: Path | None, *, main: bool, group: str, read: bool,
                what: str = "all") -> list[Item]:
    """A task's record, goal, AGENTS.md, notes and pages, as one choice brings them in: everything, or (of a
    step) its notes only or its pages only. Read when `read`, else only sized."""
    from . import goals, instructions

    record = _record(task)
    items = [Item(id=f"task:{task.id}", kind="task", label=("The task's record" if main else f"Task {owner}"),
                  owner=owner, text=record if read else "", tokens=tokens(record), group=group, on=read)]
    folder = (root / task.folder) if (root and task.folder) else None
    if folder is None or not folder.is_dir():
        return items
    notes, pages = what in ("all", "md"), what in ("all", "html")
    goal = folder / goals.ABOUT_FILE
    if what == "all" and goal.is_file():
        items.append(_file("goal", goal, folder, root, owner, group, read))
        items[-1].label = "The goal"
    agents = instructions.in_folder(folder)
    if notes and agents.is_file():
        items.append(_file("agents", agents, folder, root, owner, group, read))
        items[-1].label = agents.name
    if notes:
        for p in _files(folder, ".md"):
            if p.name == goals.ABOUT_FILE and p.parent == folder:
                continue
            items.append(_file("md", p, folder, root, owner, group, read))
    if pages:
        for p in _files(folder, ".html"):
            items.append(_file("html", p, folder, root, owner, group, read))
    return items


def _others(task, owner: str, root: Path | None, read: bool) -> list[Item]:
    """The task's other text files: data, scripts, lists, neither notes nor pages."""
    folder = (root / task.folder) if (root and task.folder) else None
    if folder is None or not folder.is_dir():
        return []
    return [_file("other", p, folder, root, owner, "others", read) for p in _files(folder, OTHER_SUFFIXES)]


#: The words of a chat as a task's chat is told them, by (chat, its newest message, how many): read once until
#: something is said in it, so a history is sized by the very words it would send, on or off.
_SAID: dict[tuple, str] = {}


def _said(chat_id: str) -> str:
    """The newest `HISTORY_ROWS` messages of a chat as a turn is told them: "Person: ..." and "Rouh: ...", one a
    line. "" when nothing is said in it."""
    from django.db.models import Count, Max

    from .models.objects import ChatMessage

    mark = ChatMessage.objects.filter(chat_id=chat_id).aggregate(n=Count("id"), last=Max("seq"))
    if not mark["n"]:
        return ""
    key = (chat_id, mark["last"], mark["n"])
    got = _SAID.get(key)
    if got is None:
        rows = list(ChatMessage.objects.filter(chat_id=chat_id).order_by("-seq")
                    .values_list("role", "body")[:HISTORY_ROWS])
        rows.reverse()
        got = "\n".join(f"{'Person' if r == 'user' else 'Rouh'}: {' '.join(str(b or '').split())}"
                        for r, b in rows)
        if len(_SAID) > 2_000:
            _SAID.clear()
        _SAID[key] = got
    return got


def _histories(task, owner: str, *, group: str, read: bool, skip: str = "") -> list[Item]:
    """The words of the chats a task owns, but `skip`: the chat being read in already sends its own. Sized by
    the words they would send, whether they are read or left out (`_said`)."""
    from . import conversations

    st = conversations.store()
    out = []
    for _kind, chat_id in st.children_of("task", task.id, "chat"):
        if skip and chat_id == skip:
            continue
        said = _said(chat_id)
        if not said:
            continue
        chat = st.get_chat(chat_id)
        name = (chat.title if chat and chat.title else "a chat").strip()
        it = Item(id=f"history:{chat_id}", kind="history", label=f"Chat: {name}", owner=owner, group=group,
                  on=read, tokens=tokens(said))
        if read:
            it.text = said
        out.append(it)
    return out


def task_of(chat_id: str):
    """The task a chat reads: the one that owns it, or the one a fork of its chat hangs off."""
    from . import conversations, forks

    task = conversations.task_of(chat_id)
    if task is None:
        task = forks.task_above(chat_id)
    if task is None:
        # A task's chat before anything is said in it is a draft, not a row yet (`conversations.draft`).
        held = conversations.draft(chat_id) or {}
        if held.get("task"):
            task = conversations.store().get_task(held["task"])
    return task


def subtasks(task) -> list:
    """The task's own subtasks (its steps), oldest first."""
    from . import conversations

    st = conversations.store()
    out = []
    for _kind, sid in st.children_of("task", task.id, "task"):
        sub = st.get_task(sid)
        if sub is not None:
            out.append(sub)
    return out


def _step_parent(chat_id: str):
    """(the step, its parent task) when this is a step's own chat, else (None, None). A fork of a step's chat
    is told the step's task, not its parent's background (`subtasknotes.prompt_block` asks the same)."""
    from . import conversations, subtasknotes

    task = conversations.task_of(chat_id)
    if task is None:
        held = conversations.draft(chat_id) or {}
        if held.get("task"):
            task = conversations.store().get_task(held["task"])
    if task is None:
        return None, None
    parent = subtasknotes.parent_of(task.id)
    return (task, parent) if parent is not None else (None, None)


#: What a fork's carried conversation comes to, in tokens, by what it is made of (`_carried_tokens`): worked out
#: once, and again only when something is said or tried again in the fork or in what it carries.
_CARRIED: dict[tuple, int] = {}


def _runtime():
    """(the server's memory, its attachment store), or a memory of its own and no store outside the server."""
    try:
        from . import runtime

        return runtime.memory, getattr(runtime, "files", None)
    except Exception:  # noqa: BLE001 - sized without the files' places rather than not at all
        from .memory import Memory

        return Memory(), None


def _carried_tokens(chat_id: str, chain: list[tuple[str, int]]) -> dict[str, int]:
    """The tokens each parent chat comes to in what this fork is sent, and its own words under "": the
    very messages a turn sends (`memory.Memory.carried_sent`: for a fork of General its window of
    `history_turns` up to the fork, for any other chat all of it, each cut where the one below it was forked
    from it; repaired, earlier tool results as stubs and older pictures as lines), with the files that go
    whole read as they are sent, counted by `tokencount`. A parent chat is sized by itself, with every
    other left out, so its size is the same whether it is on or off. General's running summary is told in
    General alone (`brain._general_summary_block`), so it is not part of it."""
    from django.db.models import Count, Max, Q

    from . import attachments, chatkinds, context_editing, forks, tokencount
    from .memory import repair_history
    from .models.memory import TranscriptMessage

    limit = chatkinds.profile(chat_id).history
    own = TranscriptMessage.objects.filter(session_id=chat_id).aggregate(
        last=Max("id"), live=Count("id", filter=Q(live=True)))
    above = []
    for parent, at in chain:
        n = TranscriptMessage.objects.filter(session_id=parent, id__lte=at).aggregate(
            live=Count("id", filter=Q(live=True)))
        above.append((parent, at, n["live"], chatkinds.profile(parent).history))
    key = (chat_id, own["last"], own["live"], limit, tuple(above))
    got = _CARRIED.get(key)
    if got is None:
        memory, store = _runtime()
        ids = [p for p, _at in chain]

        def counted(msgs: list) -> int:
            if store is not None:
                msgs = attachments.hydrate(msgs, store)
            return tokencount.messages(msgs)

        got = {}
        for parent in ids:
            sent = memory.carried_sent(chat_id, limit, limit_of=lambda c: chatkinds.profile(c).history,
                                       files=store, off=frozenset(p for p in ids if p != parent))
            got[parent] = counted(sent)
        mine, _did = context_editing.lean(repair_history(memory._window(chat_id, limit, depth=forks.DEEP)),
                                          store=store)
        got[""] = counted(mine)
        if len(_CARRIED) > 500:
            _CARRIED.clear()
        _CARRIED[key] = got
    return got


def chat_name(chat_id: str) -> str:
    """A chat's name as the strip's panel says it: its title, with the chat mark when it has none."""
    from . import conversations

    chat = conversations.store().get_chat(chat_id)
    name = (chat.title if chat and chat.title else "").strip()
    if not name or conversations.is_untitled(name):
        name = "General" if chat_id == conversations.GENERAL else "Untitled chat"
    return name if not name[:1].isalnum() else f"\N{SPEECH BALLOON} {name}"


#: The words of the row for the chat itself, at the foot of the tree (Petar, 18 November 2026).
THIS_CHAT = "This chat - \N{SPOOL OF THREAD} Chat fork history"


def _fork_items(chat_id: str, s: dict) -> list[Item]:
    """The parent chats a fork carries above its own words (`memory.Memory._window`), nearest first, each
    with its own switch (`parent_on`) and sized as it is sent (`_carried_tokens`); [] when it carries none."""
    from . import forks

    chain = forks.carried_chain(chat_id)
    if not chain:
        return []
    try:
        sizes = _carried_tokens(chat_id, chain)
    except Exception:  # noqa: BLE001 - a size is never worth the panel
        log.exception("what chat %s carries could not be sized", chat_id)
        sizes = {}
    got = []
    for depth, (parent, _at) in enumerate(chain):
        got.append(Item(id=f"fork:{parent}", kind="fork", label=chat_name(parent),
                        tokens=max(1, sizes.get(parent, 0)), group="fork_history", owner=str(depth + 1),
                        on=parent_on(s, parent), elsewhere=True))
    got.append(Item(id=f"self:{chat_id}", kind="self", label=THIS_CHAT, tokens=sizes.get("", 0),
                    group="fork_self", on=True, elsewhere=True))
    return got


def items(chat_id: str, s: dict | None = None) -> tuple[object, list[Item], list]:
    """(the task, every item this chat may read about what it is about with whether it does and how, the
    task's subtasks). What a choice leaves out is listed with its size and never read. The task is None for
    a chat that is no task's, whose only item can be a fork's carried conversation."""
    from . import subtasknotes

    s = s or settings(chat_id)
    task = task_of(chat_id)
    got: list[Item] = []
    subs: list = []
    root = _root()
    if task is not None:
        number = str(task.number) if task.number is not None else subtasknotes.step_number(task)
        got += _task_items(task, number, root, main=True, group="task", read=bool(s["task"]))
        got += _others(task, number, root, read=bool(s["others"]))
        subs = subtasks(task)
        picked = set(s["picked"])
        steps_on = s["subtasks"] != "none"
        for sub in subs:
            # Every subtask is listed, with its size; one not chosen is in a group of its own, so Subtasks
            # says the size of what it brings in.
            chosen = s["subtasks"] != "some" or sub.id in picked
            label = subtasknotes.step_number(sub) or str(sub.number or "")
            got += _task_items(sub, label, root, main=False, group="steps" if chosen else "steps_not_chosen",
                               read=steps_on and chosen, what=s["steps_what"])
        for sub in subs:
            if s["subtasks"] == "some" and sub.id not in picked:
                continue
            label = subtasknotes.step_number(sub) or str(sub.number or "")
            got += _histories(sub, label, group="step_histories", read=bool(s["step_histories"]))
        step, parent = _step_parent(chat_id)
        if parent is not None:
            background = subtasknotes.background(parent, step, root)
            got.append(Item(id=f"parent:{parent.id}", kind="parent", label=f"Task {_label(parent)}",
                            owner=str(parent.number or ""), tokens=tokens(background), group="parent_task",
                            on=bool(s["parent_task"]), elsewhere=True))
            got += _histories(parent, str(parent.number or ""), group="parent_task_history",
                              read=bool(s["parent_task_history"]))
    got += _fork_items(chat_id, s)
    for it in got:
        if not it.on:
            it.how = "off"
    plan([i for i in got if i.on and not i.elsewhere])
    return task, got, subs


def plan(got: list[Item]) -> int:
    """Read whole what fits `BUDGET`, the rest as outlines: a subtask's items first, then the task's own
    notes, pages and chat histories, and its goal and AGENTS.md last, the largest first within each. The
    tokens it comes to."""
    main = got[0].owner if got and got[0].group == "task" else ""

    def order(i: Item):
        rank = 0 if i.owner != main or i.group != "task" else (2 if i.kind in ("agents", "goal") else 1)
        return (rank, -i.tokens)

    total = sum(i.tokens for i in got)
    for it in sorted(got, key=order):
        if total <= BUDGET:
            break
        if it.kind == "task":
            continue
        short = tokens(outline(it.text))
        total -= it.tokens - short
        it.how = "outline"
    return total


def block(chat_id: str) -> str:
    """What a turn of a task's chat is told about the task, as the person set it, or ""."""
    try:
        task, every, _subs = items(chat_id)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("what chat %s reads could not be put together", chat_id)
        return ""
    got = [i for i in every if i.on and not i.elsewhere]
    if task is None or not got:
        return ""
    head = (f"What the person has this chat reading, as they set it in the strip under the chat's title "
            f"(task {_label(task)}). It is the task's own material, read from its folder in the workspace just "
            "now; a page's words are its text without its markup.")
    outlined = [i for i in got if i.how == "outline"]
    if outlined:
        head += (f" {len(outlined)} item(s) were too long to read whole together and are given as an outline "
                 "(headings and first lines): read the file itself with read_workspace when you need more.")
    parts = [head]
    for it in got:
        where = f" ({it.path})" if it.path else ""
        body = it.text if it.how == "whole" else outline(it.text)
        tag = "" if it.how == "whole" else " [outline]"
        parts.append(f"=== {it.label}{where}{tag} ===\n{body.strip()}")
    return "\n\n".join(parts)


def parent_told(chat_id: str) -> bool:
    """Whether a step's chat is told its parent task as background (`subtasknotes.prompt_block`)."""
    try:
        row = _chat_row(chat_id) if chat_id else None
    except Exception:  # noqa: BLE001
        return True
    own = row.reading if row is not None and isinstance(row.reading, dict) else {}
    return bool(own.get("parent_task", True))


# --- memory, rules and tools: where everything a chat is told comes from --------------------------
#
# Petar, 16 November 2026, of an incognito chat with Memory, Your rules and Tools all off that still knew his
# name, his city, his goals and how his Rouh is set up: every stretch of a turn's system prompt follows one of
# the switches, and only who Rouh is, the clock and the rules about permission, privacy and safety are left
# when all three are off. `source_of` says which switch a rule follows, `CONTEXT` which switch each piece of
# live context follows, and `brain.Brain._system` asks `rule_told` and `context_told` for every one of them.

#: Each source, as Chat Options and its full list name it.
SOURCES = {"memory": "Memory", "rules": "Your rules", "tools": "Tools",
           "safety": "Permission, privacy and safety", "builtin": "Built in", "chat": "This chat"}

#: Rouh's own built-in rules told whatever the switches say: who it is, which model answers, the clock, how
#: this turn came and how its reply goes out, and how the rules rank. Every other built-in rule says how the
#: screen, the orb, jobs, mail, the workspace and the rest work, and goes with Tools.
CORE = frozenset({"identity", "model-luna", "model-other", "order", "clock", "this-turn-written",
                  "this-turn-spoken", "turn-marks", "from-telegram"})
#: Built-in rules that hold what this Rouh knows of its setting up: the name it was born with and the
#: nickname the person gave it. They go with Memory.
MEMORY_RULES = frozenset({"born-name", "nickname"})
#: The tools that read or keep the person's memory: not declared while Memory is off. Synapse's own tools are
#: among them (16 November 2026): with them a chat on Memory off could still look the person up.
MEMORY_TOOLS = frozenset({"remember", "forget", "list_memory", "agent_instructions", "capture_thought",
                          "thoughts", "goals", "plan_goal", "goal_step", "set_goal", "goal_control",
                          "synapse_find", "synapse_query", "synapse_add", "synapse_edit"})

#: The live context a turn may be told beside the rules: (key, title, source, what it holds).
CONTEXT = (
    ("location", "Where you are", "memory",
     "Where you are, from your browser's location or the place you typed in Settings, and your time zone's "
     "name with the clock."),
    ("inboxes", "Which inbox is whose", "memory", "Which connected mailbox is yours and which is shared."),
    ("own-mail", "Rouh's own email address", "tools", "The address Rouh sends from."),
    ("goals", "Your goals", "memory", "Your goals in a few lines, and the whole of this chat's own goal."),
    ("terms", "Plain words, and the terms you asked about", "memory",
     "The terms you asked the meaning of, to be explained whenever they come up, and a request you keep "
     "typing by hand, offered once as scheduled work."),
    ("synapse", "Synapse Master, and how to read it", "memory",
     "What Synapse Master holds and the tools that read and change it (in a Synapse dataset's own chat, which "
     "dataset is open)."),
    ("phone", "What was sent to your phone", "memory", "What Rouh lately sent you on Telegram."),
    ("heartbeat", "What the heartbeat noted", "memory", "What Rouh noted on its own since you last talked."),
    ("genes", "Genes on offer", "memory", "Kept genes Rouh may offer you."),
    ("gene-drafts", "Genes on the fly", "tools", "Whether Rouh may offer to draft a gene."),
    ("meetings", "The meeting library", "tools", "When to read a meeting with the meeting tools."),
    ("catalogue", "The list of tools", "tools", "One line for each tool this chat can use."),
    ("general-summary", "What General said before", "chat",
     "General's running summary of what fell out of its window. Only in General."),
    ("task", "This chat's task", "chat",
     "In a task's chat: the task, its goal, AGENTS.md, notes and pages, as set in the strip under the chat's "
     "title."),
    ("page", "The page beside the chat", "chat", "The page open on the canvas, and what you selected on it."),
)
_CONTEXT_SOURCE = {k: src for k, _t, src, _w in CONTEXT}

#: The one line that stands for Synapse in the list: it is too big to list, and is told whole or not at all.
SYNAPSE_LINE = ("All of Synapse, Rouh's memory: what it has learned about you and your people, read for "
                "each message and found by automatic recall.")


def locked(r: dict) -> bool:
    """A rule no switch takes away: permission, privacy and safety (its group is Asking and permissions, or
    it is marked so, `guard` in its row), and the few built-in rules a chat cannot work without (`CORE`)."""
    return source_of(r) in ("safety", "builtin")


def source_of(r: dict) -> str:
    """Which switch a rule follows: "safety" or "builtin" (none, always on), "memory", "tools" or "rules"."""
    if bool((r.get("when") or {}).get("guard")) or bool(r.get("guard")) or r.get("group") == "asking":
        return "safety"
    key = str(r.get("key") or "")
    if r.get("place"):
        if key in CORE:
            return "builtin"
        if key in MEMORY_RULES:
            return "memory"
        return "tools"
    return "rules"


def rule_item(r: dict) -> str:
    """A rule's id in a chat's list of items turned off one by one."""
    return "rule:" + str(r.get("id") or "")


def rule_told(r: dict, reads: dict) -> bool:
    """Whether a turn with these switches (`switches`) is told this rule."""
    src = source_of(r)
    if src in ("safety", "builtin"):
        return True
    if rule_item(r) in set(reads.get("off") or ()):
        return False
    if src == "rules":
        from . import tool_rules

        # A rule of the person's told with its tools goes with them as well.
        return bool(reads["rules"]) and (bool(reads["tools"]) or not tool_rules.told_with_tools(r))
    if src == "tools" and reads.get("light"):
        from . import tool_rules

        # Simple chat: a built-in rule about a tool comes only with the tool, never in the prompt.
        return bool(reads["tools"]) and tool_rules.told_with_tools(r)
    return bool(reads[src])


def context_told(key: str, reads: dict) -> bool:
    """Whether a turn with these switches is told this piece of live context (`CONTEXT`)."""
    src = _CONTEXT_SOURCE.get(key, "chat")
    if "ctx:" + key in set(reads.get("off") or ()):
        return False
    if key in ("inboxes", "synapse"):   # about the person, and about the tools that read it
        return bool(reads["memory"]) and bool(reads["tools"])
    if src == "tools" and reads.get("light"):
        # Simple chat: of what goes with Tools, only the one-line list the model finds a tool by.
        return key == "catalogue" and bool(reads["tools"])
    return src == "chat" or bool(reads[src])


def anonymous(text: str, who=None, *, owner=...) -> str:
    """Text with the person's name taken out, for a turn with Memory off: the owner's marks are said as "the
    person", and their name written out in a rule of their own is too."""
    from . import owner as owners

    if not isinstance(text, str) or not text:
        return text
    table = {"‹owner›": "the person", "‹Owner›": "The person", "‹owner_full›": "the person",
             "‹company›": "their company", "‹he›": "they", "‹He›": "They", "‹him›": "them", "‹his›": "their",
             "‹His›": "Their", "‹himself›": "themself"}
    if owners.OPEN in text:
        text = owners._MARK.sub(lambda m: table[m.group(0)], text)
    if owner is ...:
        try:
            found = owners.resolve(who)
        except Exception:  # noqa: BLE001
            found = None
    else:
        found = owner
    names = []
    if found is not None:
        for n in (found.full_name, found.name):
            n = str(n or "").strip()
            if len(n) >= 2:
                names.append(n)
                names += [w for w in n.split() if len(w) >= 3]
    for n in sorted(set(names), key=len, reverse=True):
        text = re.sub(r"\b" + re.escape(n) + r"(?:'s)?\b",
                      lambda m: "the person's" if m.group(0).endswith("'s") else "the person", text)
    return text


def switches(chat_id: str) -> dict:
    """{"memory", "rules", "tools", "off", "light"}: what a turn in this chat may use. An incognito chat's are
    its own. `light` is Simple chat: tools only on demand, so no built-in rule about how the screen, the orb,
    mail or jobs work is told in the prompt; a rule told with its tool still comes with the tool."""
    s = settings(chat_id) if chat_id else dict(DEFAULTS)
    return {"memory": bool(s["memory"]), "rules": bool(s["rules"]), "tools": bool(s["tools"]),
            "off": list(s.get("off") or []), "light": s.get("mode") == "simple"}


def _reads_of(s: dict) -> dict:
    """What a turn does with these settings, as `switches` says it."""
    return {"memory": bool(s["memory"]), "rules": bool(s["rules"]), "tools": bool(s["tools"]), "off": s["off"],
            "light": s.get("mode") == "simple"}


def _master_for(who=None):
    from . import rules as rules_mod

    uid, org = (str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")) if who else ("", "")
    ds = rules_mod.master(uid, org) if uid and org else rules_mod.master()
    if ds:
        from . import ruledefaults

        # The defaults every Rouh starts with, taken in as a turn or the Rules page would (`ensure`).
        ruledefaults.ensure(ds)
    return ds


def rules_listing(chat_id: str, who=None, s: dict | None = None) -> list[dict]:
    """Every rule a turn of this chat can be told, for Chat Options and its full list: each with its whole
    text as the model is told it, the switch it follows (`source`), whether it is locked on, whether it is
    told with these settings (`on`), whether the person turned it off by itself (`off`), the tools it goes
    with, and when it is told only in some turns."""
    from . import owner, prompting, rules as rules_mod, tool_rules

    try:
        ds = _master_for(who)
        every = [r for r in rules_mod.rules(ds) if rules_mod.in_chat(r)] if ds else []
    except Exception:  # noqa: BLE001 - the panel says nothing rather than break
        log.exception("the rules could not be listed for the panel")
        return []
    s = s or settings(chat_id, who)
    reads = _reads_of(s)
    off = set(s["off"])
    out = []
    for r in every:
        src = source_of(r)
        text = owner.say(r["text"], who) if reads["memory"] else anonymous(r["text"], who)
        when = prompting.situation_words(r.get("when") or {})
        out.append({"id": rule_item(r), "title": r.get("title") or rules_mod._title_of(r["text"]), "text": text,
                    "source": src, "locked": src in ("safety", "builtin"), "own": src == "rules",
                    "on": rule_told(r, reads), "off": rule_item(r) in off,
                    "with": tool_rules.said(tool_rules.targets(r)) if tool_rules.told_with_tools(r) else "",
                    "when": ("only when " + "; ".join(when)) if when else "",
                    "fills": prompting.value_words(prompting.placeholders(r["text"])) if r.get("fills") else "",
                    "reply": r.get("mode") or ""})
    order = {"builtin": 0, "safety": 1, "memory": 2, "rules": 3, "tools": 4}
    out.sort(key=lambda x: (order.get(x["source"], 9), x["title"].lower()))
    return out


def context_listing(chat_id: str, who=None, s: dict | None = None) -> list[dict]:
    """The live context a turn of this chat can be told, beside the rules: each with what it says now when
    there is something to say, else what it holds."""
    s = s or settings(chat_id, who)
    reads = _reads_of(s)
    now = _context_now(chat_id, who)
    out = []
    for key, title, src, what in CONTEXT:
        said = now.get(key, "")
        if key in ("general-summary", "task", "page") and not said:
            continue   # not part of this chat at all
        out.append({"id": "ctx:" + key, "title": title, "source": src, "locked": src == "chat",
                    "on": context_told(key, reads), "off": ("ctx:" + key) in set(s["off"]),
                    "text": said or what, "live": bool(said), "what": what})
    return out


def _context_now(chat_id: str, who=None) -> dict:
    """What each piece of live context says for this chat now, where it can be read without a turn."""
    from . import brain
    from .tenancy import speaking

    out: dict[str, str] = {}

    def take(key, fn):
        try:
            got = fn()
        except Exception:  # noqa: BLE001 - the list says what the item holds instead
            log.debug("%s could not be read for Chat Options", key, exc_info=True)
            got = ""
        if got:
            out[key] = str(got)

    with speaking(who) if who is not None else _nothing():
        from . import location

        take("location", location.prompt_line)
        take("inboxes", brain._inboxes_line)
        take("own-mail", brain._own_mail)
        take("goals", lambda: brain._goals_block(chat_id))
        take("synapse", lambda: brain._synapse_block(chat_id))
        take("general-summary", lambda: brain._general_summary_block(chat_id))
        take("task", lambda: "Read from the task's folder: " + strip(chat_id) if task_of(chat_id) else "")
    return out


class _nothing:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# --- the panel and the strip --------------------------------------------------------------------


def kind_of(chat_id: str) -> str:
    from . import chatkinds, conversations

    if chat_id == conversations.GENERAL:
        return "general"
    if task_of(chat_id) is not None:
        return "task"
    return "general-fork" if chatkinds.of_general(chat_id) or _of_general(chat_id) else "chat"


def _of_general(chat_id: str) -> bool:
    from . import conversations

    try:
        return chat_id in conversations._of_general([chat_id])
    except Exception:  # noqa: BLE001
        return False


#: The choices of the strip's panel, in its order: (key, title, what it brings in, the chats it is for).
GROUPS = (
    ("task", "This task", "The task, its goal, AGENTS.md, its notes (.md) and its pages (.html)"),
    ("others", "Other files in the folder", "The task's other text files: lists, data, scripts"),
    ("steps", "Subtasks", "What the task's subtasks hold"),
    ("step_histories", "Subtasks' chat histories", "What was said in the subtasks' own chats"),
    ("parent_task", "Parent task", "Its AGENTS.md, what it says this subtask is, and what its other subtasks sent up"),
    ("parent_task_history", "Parent task's chat history", "What was said in the parent task's chats"),
)


def _plural(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def content(chat_id: str, s: dict, got: list[Item], task, subs: list) -> dict:
    """What the strip's panel draws: each choice this chat has, with whether it is on, its size, and how many
    things it brings in. A choice with nothing to bring in is not drawn (no Subtasks in a task without subtasks);
    a chat with no choice at all (General, a chat of its own) has an empty list, and no panel."""
    groups = []
    for key, title, sub in GROUPS:
        of = [i for i in got if i.group == key]
        # A history choice is drawn wherever it belongs, even before there is anything said to bring in.
        belongs = {"steps": bool(subs), "step_histories": bool(subs),
                   "parent_task_history": any(i.group == "parent_task" for i in got)}
        if key in belongs:
            if not belongs[key]:
                continue
        elif not of:
            continue
        on = bool(s[key]) if key != "steps" else s["subtasks"] != "none"
        n = sum(i.sent for i in of)
        if not of and key != "steps":
            sub = "Nothing said in them yet"
        g = {"key": key, "title": title, "sub": sub, "on": on, "tokens": n, "size": size_word(n) if of else "",
             "count": len(of), "outlined": sum(1 for i in of if i.how == "outline")}
        if key == "parent_task" and of:
            g["title"] = f"Parent task: {of[0].label.removeprefix('Task ')}"
        groups.append(g)
    return {"groups": groups, "tree": tree(got), "summary": strip(chat_id, s, got, task, subs=subs)}


def tree(got: list[Item]) -> list[dict]:
    """The chain of chats a fork carries, as the strip's panel draws it (Petar, 18 November 2026: "show the
    entire tree of conversations"): the chat it all started in at the top and least set in, each one forked
    from it under it and set in one more, and this chat at the foot, set in the most, with no switch of its
    own because its own words are always sent. [] for a chat that is no fork."""
    chats = [i for i in got if i.kind == "fork"]
    if not chats:
        return []
    out = [{"id": i.id.removeprefix("fork:"), "label": i.label, "tokens": i.tokens, "on": i.on}
           for i in reversed(chats)]
    for depth, row in enumerate(out):
        row["depth"] = depth
    me = next((i for i in got if i.kind == "self"), None)
    out.append({"id": "", "label": THIS_CHAT, "tokens": me.tokens if me else 0, "on": True,
                "depth": len(chats), "self": True})
    return out


def strip(chat_id: str, s: dict | None = None, got: list[Item] | None = None, task=None,
          incognito: bool = False, subs: list | None = None) -> str:
    """The line under the chat's title: what this chat is about, in a few plain words: "Task 130 · 2 notes ·
    3 pages · subtasks left out", "Subtask 130-02 · 1 note · parent task", "Forked from General · history included".
    "" when the chat has nothing to choose (General, or a chat of its own), and no strip is drawn. How Rouh
    works (the mode) is said on the Chat Options button, never here."""
    from . import subtasknotes

    s = s or settings(chat_id)
    if got is None:
        task, got, subs = items(chat_id, s)
    on = [i for i in got if i.on]
    bits = []
    chain = [i for i in got if i.kind == "fork"]
    if task is not None:
        step = subtasknotes.parent_of(task.id) is not None
        name = (f"Subtask {subtasknotes.step_number(task)}" if step and subtasknotes.step_number(task)
                else f"Task {_label(task).split(' · ')[0]}")
        if not s["task"]:
            bits.append(f"{name} left out")
        else:
            bits.append(name)
            mine = [i for i in on if i.group == "task"]
            notes = sum(1 for i in mine if i.kind == "md")
            pages = sum(1 for i in mine if i.kind == "html")
            if notes:
                bits.append(_plural(notes, "note"))
            if pages:
                bits.append(_plural(pages, "page"))
        others = sum(1 for i in on if i.group == "others")
        if others:
            bits.append(_plural(others, "other file"))
        if subs:
            if s["subtasks"] == "none":
                bits.append("subtasks left out")
            else:
                n = len({i.owner for i in on if i.group == "steps" and i.kind == "task"})
                what = {"md": " (notes)", "html": " (pages)"}.get(s["steps_what"], "")
                bits.append(_plural(n, "subtask") + what)
        if any(i.group == "step_histories" for i in on):
            bits.append("subtasks' chats")
        if any(i.group == "parent_task" for i in on):
            bits.append("parent task")
        if any(i.group == "parent_task_history" for i in on):
            bits.append("parent's chats")
        cut = sum(1 for i in on if i.how == "outline")
        if cut:
            bits.append(f"{cut} as outlines")
    if chain:
        n, k = len(chain), sum(1 for i in chain if i.on)
        if not k:
            said = "parent chat left out" if n == 1 else "parent chats left out"
        elif n == 1:
            said = "parent chat included"
        else:
            said = f"{k} of {n} parent chats"
        bits.append(f"Forked from {chain[0].label} · {said}" if task is None else f"forked, {said}")
    return " · ".join(bits)


def last_turn(chat_id: str) -> dict | None:
    """What this chat's last message really came to, from the provider's own numbers (`memory.note_spend`):
    the tokens its first request went out with (input, read from the cache and written to it; the window
    `context_editing.window_tokens` measures), the part of them read from the cache, and how many requests
    the turn took. None before anything was answered here."""
    from .models.memory import Spend

    row = (Spend.objects.filter(session_id=chat_id).order_by("-ts")
           .values("calls", "input_tokens", "cache_read", "cache_write", "ts").first())
    if row is None:
        return None
    calls = [c for c in (row["calls"] or []) if isinstance(c, dict)]
    first = calls[0] if calls else {"input": row["input_tokens"], "cache_read": row["cache_read"],
                                    "cache_write": row["cache_write"]}
    tokens_in = sum(int(first.get(k) or 0) for k in ("input", "cache_read", "cache_write"))
    if not tokens_in:
        return None
    return {"tokens": tokens_in, "cached": int(first.get("cache_read") or 0), "requests": max(1, len(calls)),
            "ts": row["ts"]}


def view(chat_id: str, who=None) -> dict:
    """Everything the panel draws for this chat."""
    from .models.objects import Chat

    row = Chat.objects.filter(id=chat_id).values("incognito").first()
    is_incognito = bool(row and row["incognito"])
    s = settings(chat_id, who)
    task, got, subs = items(chat_id, s)
    read = [i for i in got if i.on and not i.elsewhere]
    total = sum(i.sent for i in read)
    told = content(chat_id, s, got, task, subs)
    out = {"chat": chat_id, "kind": kind_of(chat_id), "settings": s, "incognito": is_incognito,
           "mode": s["mode"], "modes": [{"id": m, "name": MODE_NAMES[m]} for m in MODES],
           # What is read now, of what the chat is about: what its choices bring in, with how.
           "items": [i.public() for i in got if i.on], "budget": BUDGET, "reads": total,
           "outlined": sum(1 for i in read if i.how == "outline"),
           "content": told["groups"], "tree": told["tree"], "strip": told["summary"]}
    try:
        out["last"] = last_turn(chat_id)
    except Exception:  # noqa: BLE001 - a number on a panel
        log.exception("chat %s's last turn could not be read", chat_id)
    if task is not None:
        from . import subtasknotes

        out["task"] = {"id": task.id, "label": _label(task)}
        picked = set(s["picked"])
        sizes: dict[str, int] = {}
        for i in got:
            if i.group in ("steps", "steps_not_chosen"):
                sizes[i.owner] = sizes.get(i.owner, 0) + i.sent
        out["subtasks"] = []
        for sub in subs:
            n = sizes.get(subtasknotes.step_number(sub) or str(sub.number or ""), 0)
            out["subtasks"].append({"id": sub.id, "label": subtasknotes.label(sub), "size": size_word(n), "tokens": n,
                                    "on": s["subtasks"] == "all" or (s["subtasks"] == "some" and sub.id in picked)})
    if is_incognito:
        from . import incognito

        out["kept"] = incognito.KEPT
    # Everything this chat can be told, for the full list: the rules, each with the switch it follows, the
    # live context, and the one line for Synapse.
    out["rules"] = rules_listing(chat_id, who, s)
    out["context"] = context_listing(chat_id, who, s)
    out["synapse"] = {"text": SYNAPSE_LINE, "on": bool(s["memory"])}
    out["sources"] = SOURCES
    return out
