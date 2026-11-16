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
- **In a task's chat** (or a step's, which is a task inside a task), what the task is: its record (number,
  name, status, summary, meta), the goal when the task is one (`goal.md`), its `AGENTS.md`, and its notes
  (`.md`) and pages (`.html`), read from its folder in the workspace. No subtask by default. The person can
  add every subtask or chosen ones, keep only notes or only pages, and add the chat histories of what is
  included.
- **Sizes**: each item is labelled short, long or very long from its tokens (`size_word`). What is included
  is read whole up to `BUDGET` tokens; past it, the largest items are read as an outline (their headings and
  first lines) and the panel and the model are both told which (`plan`). Nothing is blown into the prompt
  blindly: a step of a million tokens is an outline.

`block` is what a turn of a task's chat is told (`brain.Brain._system`), `switches` what the turn does with
memory, rules and tools, `view` what the panel draws, and `strip` the one line under the chat's title that
says in plain words what is being read.
"""
from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

log = logging.getLogger("rouh.reading")

#: The defaults: memory, rules and tools on; a task's chat reads the task, its notes and pages, no subtasks,
#: no chat histories.
DEFAULTS = {"memory": True, "rules": True, "tools": True, "subtasks": "none", "picked": [], "md": True,
            "html": True, "histories": False, "off": [], "keep": False}
#: What a person can save as the start of every new chat (`saved`): the three switches and the items off.
SAVED_KEYS = ("memory", "rules", "tools", "off")
#: The person's saved choices, a `UserSetting` of theirs.
SAVED = "chat_options"
SUBTASKS = ("none", "all", "some")
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


def _whose(who=None):
    """The person these settings are for: `who`, else whoever the turn is for."""
    if who is not None:
        return who
    try:
        from .tenancy import speaker

        return speaker()
    except Exception:  # noqa: BLE001
        return None


def saved(who=None) -> dict:
    """The choices the person saved for every new chat ("This chat and new chats" in Chat Options), or {}."""
    who = _whose(who)
    uid = str(getattr(who, "user_id", "") or "")
    if not uid:
        return {}
    try:
        import json

        from .models import UserSetting

        raw = UserSetting.objects.filter(user_id=uid, name=SAVED).values_list("value", flat=True).first()
        got = json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001 - a chat starts on Rouh's defaults rather than not at all
        log.exception("the saved chat options could not be read")
        return {}
    return {k: v for k, v in got.items() if k in SAVED_KEYS} if isinstance(got, dict) else {}


def _save(who, value: dict | None) -> None:
    """Keep these choices for every new chat, or forget them (None)."""
    import json
    import time

    from .models import UserSetting

    who = _whose(who)
    uid, org = str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")
    if not uid:
        return
    if value is None:
        UserSetting.objects.filter(user_id=uid, name=SAVED).delete()
        return
    UserSetting.objects.update_or_create(
        user_id=uid, name=SAVED,
        defaults={"org_id": org, "value": json.dumps({k: value[k] for k in SAVED_KEYS if k in value}),
                  "updated_at": time.time()})


def settings(chat_id: str, who=None) -> dict:
    """This chat's settings: Rouh's defaults, under the person's saved choices, under what this chat set."""
    row = _chat_row(chat_id) if chat_id else None
    got = dict(DEFAULTS)
    own = row.reading if row is not None and isinstance(row.reading, dict) else {}
    # An incognito chat is its own: nothing saved for ordinary chats reaches it.
    if not (row is not None and row.incognito):
        got.update(saved(who))
    got.update({k: v for k, v in own.items() if k in DEFAULTS})
    if got["subtasks"] not in SUBTASKS:
        got["subtasks"] = "none"
    got["picked"] = [str(x) for x in got.get("picked") or []][:200]
    got["off"] = sorted({str(x) for x in got.get("off") or []})[:500]
    return got


def put(chat_id: str, change: dict, who=None) -> dict:
    """Change some of this chat's settings; what it is now. Unknown keys are ignored.

    `reset` puts the chat back on Rouh's defaults and forgets the person's saved choices; `keep` true saves
    this chat's choices for every new chat, now and with each change after, and false stops that."""
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
        # Rouh's defaults: everything on, nothing left out. An incognito chat still reads no memory until
        # the person turns it on, as it started (`incognito.start`).
        now = {"memory": False} if row.incognito else {}
        Chat.objects.filter(id=chat_id).update(reading=now)
        if not row.incognito:
            _save(who, None)
        return settings(chat_id, who)
    for k, v in change.items():
        if k not in DEFAULTS:
            continue
        if k == "subtasks":
            if v in SUBTASKS:
                now[k] = v
        elif k == "picked":
            now[k] = [str(x) for x in (v or [])][:200]
        elif k == "off":
            now[k] = sorted({str(x) for x in (v or []) if str(x)})[:500]
        else:
            now[k] = bool(v)
    if row.incognito:
        now.pop("keep", None)   # an incognito chat's choices are never saved for others
    Chat.objects.filter(id=chat_id).update(reading=now)
    got = settings(chat_id, who)
    if got.get("keep") and not row.incognito:
        _save(who, got)
    return got


# --- what is in a task --------------------------------------------------------------------------


def tokens(text: str) -> int:
    """About how many tokens: four characters each, which is what every model here comes to on prose."""
    return (len(text or "") + 3) // 4


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
    """One thing a task's chat may read."""

    id: str
    kind: str            # task, goal, agents, md, html, history
    label: str
    owner: str = ""      # the task it is part of, as "68" or "68-01"
    path: str = ""       # in the workspace, for a file
    tokens: int = 0
    on: bool = True
    how: str = "whole"   # whole, outline, or off
    text: str = field(default="", repr=False)

    def public(self) -> dict:
        return {"id": self.id, "kind": self.kind, "label": self.label, "owner": self.owner, "path": self.path,
                "size": size_word(self.tokens), "tokens": self.tokens, "on": self.on, "how": self.how}


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


def _files(folder: Path, suffix: str) -> list[Path]:
    """The files of a kind in a task's own folder and its own subfolders that are not steps, by name."""
    from . import subtasknotes

    out: list[Path] = []
    if not folder.is_dir():
        return out
    for p in sorted(folder.rglob(f"*{suffix}")):
        rel = p.relative_to(folder)
        parts = rel.parts[:-1]
        # A step's folder is a subtask's, read only when the subtask is; scratch and hidden folders never.
        if any(subtasknotes.step_of_folder(x) or x.startswith(".") or x in ("temp", "node_modules", "images")
               for x in parts):
            continue
        if p.name.upper() == "AGENTS.MD" and not parts:
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


def _task_items(task, owner: str, s: dict, root: Path | None, *, main: bool) -> list[Item]:
    from . import goals, instructions

    items = [Item(id=f"task:{task.id}", kind="task", label=("This task" if main else f"Task {owner}"),
                  owner=owner, text=_record(task))]
    folder = (root / task.folder) if (root and task.folder) else None
    if folder is not None and folder.is_dir():
        goal = folder / goals.ABOUT_FILE
        if goal.is_file():
            items.append(Item(id=f"goal:{task.id}", kind="goal", label="The goal", owner=owner,
                              path=str(goal.relative_to(root)), text=_read(goal)))
        agents = instructions.in_folder(folder)
        if agents.is_file():
            items.append(Item(id=f"agents:{task.id}", kind="agents", label=agents.name, owner=owner,
                              path=str(agents.relative_to(root)), text=_read(agents)))
        if s["md"]:
            for p in _files(folder, ".md"):
                if p.name == goals.ABOUT_FILE and p.parent == folder:
                    continue
                rel = str(p.relative_to(root))
                items.append(Item(id=f"md:{rel}", kind="md", label=str(p.relative_to(folder)), owner=owner,
                                  path=rel, text=_read(p)))
        if s["html"]:
            for p in _files(folder, ".html"):
                rel = str(p.relative_to(root))
                items.append(Item(id=f"html:{rel}", kind="html", label=str(p.relative_to(folder)), owner=owner,
                                  path=rel, text=html_text(_read(p))))
    if s["histories"]:
        items += _histories(task, owner, skip_main=main)
    for it in items:
        it.tokens = tokens(it.text)
    return items


def _histories(task, owner: str, *, skip_main: bool) -> list[Item]:
    """The words of the chats a task owns. The chat being read in already sends its own."""
    from . import conversations
    from .models.objects import ChatMessage

    st = conversations.store()
    out = []
    for kind, chat_id in st.children_of("task", task.id, "chat"):
        if skip_main and chat_id == _CURRENT.get(""):
            continue
        rows = list(ChatMessage.objects.filter(chat_id=chat_id).order_by("-seq")
                    .values_list("role", "body")[:HISTORY_ROWS])
        if not rows:
            continue
        rows.reverse()
        chat = st.get_chat(chat_id)
        name = (chat.title if chat and chat.title else "a chat").strip()
        text = "\n".join(f"{'Person' if r == 'user' else 'Rouh'}: {' '.join(str(b or '').split())}" for r, b in rows)
        out.append(Item(id=f"history:{chat_id}", kind="history", label=f"Chat: {name}", owner=owner, text=text))
    return out


import contextvars  # noqa: E402 - beside the one thing that uses it

_CURRENT: contextvars.ContextVar[str] = contextvars.ContextVar("reading_chat", default="")


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


def items(chat_id: str, s: dict | None = None) -> tuple[object, list[Item], list]:
    """(the task, every item it may read with how it is read, its subtasks), or (None, [], [])."""
    s = s or settings(chat_id)
    task = task_of(chat_id)
    if task is None:
        return None, [], []
    from . import subtasknotes

    root = _root()
    token = _CURRENT.set(chat_id)
    try:
        got = _task_items(task, str(task.number) if task.number is not None else subtasknotes.step_number(task),
                          s, root, main=True)
        subs = subtasks(task)
        if s["subtasks"] != "none":
            picked = set(s["picked"])
            for sub in subs:
                if s["subtasks"] == "all" or sub.id in picked:
                    got += _task_items(sub, subtasknotes.step_number(sub) or str(sub.number or ""), s, root,
                                       main=False)
    finally:
        _CURRENT.reset(token)
    plan(got)
    return task, got, subs


def plan(got: list[Item]) -> int:
    """Read whole what fits `BUDGET`, the rest as outlines: a subtask's items first, then the task's own
    notes, pages and chat histories, and its goal and AGENTS.md last, the largest first within each. The
    tokens it comes to."""
    main = got[0].owner if got else ""

    def order(i: Item):
        rank = 0 if i.owner != main else (2 if i.kind in ("agents", "goal") else 1)
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
        task, got, _subs = items(chat_id)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("what chat %s reads could not be put together", chat_id)
        return ""
    if task is None or not got:
        return ""
    head = (f"What the person has this chat reading, as they set it in Chat Options beside the box "
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
#: The tools that read or keep the person's memory: not declared while Memory is off.
MEMORY_TOOLS = frozenset({"remember", "forget", "list_memory", "agent_instructions", "capture_thought",
                          "thoughts", "goals", "plan_goal", "goal_step", "set_goal", "goal_control"})

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
     "In a task's chat: the task, its goal, AGENTS.md, notes and pages, as set under the task above."),
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
    return bool(reads[src])


def context_told(key: str, reads: dict) -> bool:
    """Whether a turn with these switches is told this piece of live context (`CONTEXT`)."""
    src = _CONTEXT_SOURCE.get(key, "chat")
    if "ctx:" + key in set(reads.get("off") or ()):
        return False
    if key in ("inboxes", "synapse"):   # about the person, and about the tools that read it
        return bool(reads["memory"]) and bool(reads["tools"])
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
    """{"memory", "rules", "tools", "off"}: what a turn in this chat may use. An incognito chat's are its own."""
    s = settings(chat_id) if chat_id else dict(DEFAULTS)
    return {"memory": bool(s["memory"]), "rules": bool(s["rules"]), "tools": bool(s["tools"]),
            "off": list(s.get("off") or [])}


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
    reads = {"memory": bool(s["memory"]), "rules": bool(s["rules"]), "tools": bool(s["tools"]), "off": s["off"]}
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
                    "reply": r.get("mode") or ""})
    order = {"builtin": 0, "safety": 1, "memory": 2, "rules": 3, "tools": 4}
    out.sort(key=lambda x: (order.get(x["source"], 9), x["title"].lower()))
    return out


def context_listing(chat_id: str, who=None, s: dict | None = None) -> list[dict]:
    """The live context a turn of this chat can be told, beside the rules: each with what it says now when
    there is something to say, else what it holds."""
    s = s or settings(chat_id, who)
    reads = {"memory": bool(s["memory"]), "rules": bool(s["rules"]), "tools": bool(s["tools"]), "off": s["off"]}
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


def strip(chat_id: str, s: dict | None = None, got: list[Item] | None = None, task=None,
          incognito: bool = False) -> str:
    """The line under the chat's title: what is being read, in plain words."""
    s = s or settings(chat_id)
    bits = []
    if s["memory"] and not incognito:
        bits.append("Memory")
    if s["rules"]:
        bits.append("Your rules")
    else:
        bits.append("Safety rules only")
    if s["tools"]:
        bits.append("Tools")
    if task is not None:
        bits.append(f"Task {_label(task).split(' · ')[0]}")
        if any(i.kind == "agents" for i in got or []):
            bits.append("AGENTS.md")
        notes = sum(1 for i in got or [] if i.kind == "md")
        pages = sum(1 for i in got or [] if i.kind == "html")
        subs = len({i.owner for i in got or [] if i.kind == "task"}) - 1
        hist = sum(1 for i in got or [] if i.kind == "history")
        if notes:
            bits.append(f"{notes} note{'s' if notes != 1 else ''}")
        if pages:
            bits.append(f"{pages} page{'s' if pages != 1 else ''}")
        if subs > 0:
            bits.append(f"{subs} subtask{'s' if subs != 1 else ''}")
        if hist:
            bits.append(f"{hist} chat histor{'ies' if hist != 1 else 'y'}")
        cut = sum(1 for i in got or [] if i.how == "outline")
        if cut:
            bits.append(f"{cut} as outlines")
    return " · ".join(bits)


def view(chat_id: str, who=None) -> dict:
    """Everything the panel draws for this chat."""
    from .models.objects import Chat

    row = Chat.objects.filter(id=chat_id).values("incognito").first()
    is_incognito = bool(row and row["incognito"])
    s = settings(chat_id, who)
    task, got, subs = items(chat_id, s)
    total = sum(i.tokens if i.how == "whole" else tokens(outline(i.text)) for i in got)
    out = {"chat": chat_id, "kind": kind_of(chat_id), "settings": s, "incognito": is_incognito,
           "items": [i.public() for i in got], "budget": BUDGET, "reads": total,
           "outlined": sum(1 for i in got if i.how == "outline"),
           "strip": strip(chat_id, s, got, task, is_incognito)}
    if task is not None:
        from . import subtasknotes

        out["task"] = {"id": task.id, "label": _label(task)}
        picked = set(s["picked"])
        out["subtasks"] = [{"id": sub.id, "label": subtasknotes.label(sub),
                            "on": s["subtasks"] == "all" or (s["subtasks"] == "some" and sub.id in picked)}
                           for sub in subs]
    if is_incognito:
        from . import incognito

        out["kept"] = incognito.KEPT
    # Everything this chat can be told, for the full list: the rules, each with the switch it follows, the
    # live context, and the one line for Synapse.
    out["rules"] = rules_listing(chat_id, who, s)
    out["context"] = context_listing(chat_id, who, s)
    out["synapse"] = {"text": SYNAPSE_LINE, "on": bool(s["memory"])}
    out["sources"] = SOURCES
    out["saved"] = saved(who) if not is_incognito else {}
    return out
