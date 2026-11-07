"""Every task's icon, as a Notion page has one: an emoji, or a small picture, in front of its title.

Petar, 22 October 2026 (fr_0ac90fe38f73): "I would love it if each task has its own emoji. 1. you
pick the emoji in front automatically. 2. you make a run and change all the emojis for the tasks.
3. should be stored in db, not in files. 4. I should be able to click it and change it, just like
in notion. it should be possible to put an image upload, small icon instead of emoji. if file is
uploaded, it should be a file in the folder. database will save the name of the file to point to
for display. this file is going to be hidden from our file browser ... 5. sub tasks have their
own icon naturally."

- **Where it is kept.** `task.icon`, one value per task and per step: the emoji itself, or the
  file name of a picture (`is_picture`). Every change is a row of `task_change`
  (`ObjectStore.set_task_icon`).
- **A picture** is a file in `task-icons/` in Rouh's data folder (`folder`), named for its task
  and its own bytes, so a new one never overwrites an old one and an old icon can be put back
  from the history. That folder is outside the workspace, so no list of a task's files ever
  shows it, and no deploy resets it. The task browser and a task's page are sandboxed frames
  that cannot fetch anything signed in, so a picture is put into them as a data address
  (`src`). Pictures are made small on the page before they are sent (`taskicon.js`), and refused
  here above `MOST_BYTES` or when they are not PNG, JPEG, GIF or WebP.
- **Picked by itself.** A task is born with none, and `Picker` gives it one within moments:
  the model the Models page has for "Task icons" picks an emoji for each task from its title,
  many tasks to one question; where that model cannot be asked, `guess` picks one from the
  words of the title, so no task is left without one. The first time Rouh starts with this,
  every task there is has none, and that one pass is the run that gives every task its emoji.
  `manage.py task_icons --all` picks every one again, over whatever each has.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import re
from pathlib import Path

log = logging.getLogger(__name__)

#: The model use on the Models page (`rouh/modeldefaults.py`).
USE = "task_icon"

#: The folder in Rouh's data folder the pictures are in.
FOLDER = "task-icons"

#: The biggest picture kept. The page sends one at most 128 pixels square, which is a few kB.
MOST_BYTES = 256 * 1024

#: What a picture may be, by its first bytes, and the extension it is kept under.
KINDS = (
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"GIF87a", "gif", "image/gif"),
    (b"GIF89a", "gif", "image/gif"),
)
MEDIA = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}

#: A picture's name: the task's id made safe, and the start of its bytes' sha256.
_PICTURE = re.compile(r"^[A-Za-z0-9_-]{1,80}-[0-9a-f]{12}\.(png|jpg|gif|webp)$")

#: How many tasks one question to the model names, and how long it may take.
BATCH = 60
TIMEOUT = 90.0

#: How many tasks one pass of the picker takes.
PASS = 300

#: How often the picker looks for tasks with none, besides being poked when one is made.
BEAT = 600.0

#: Who a change made here is by, in `task_change`.
BY = "Rouh, picking an icon"
#: And one the person made in the picker.
PERSON = "owner"

SYSTEM = """You pick one emoji for each task in a person's task list, the way a Notion page has an icon.

Pick the emoji that best says what the task is about, so the person finds it at a glance: its subject, not its status. Prefer a concrete, specific emoji (a car for car seats, a house for a property, a robot for a robot vacuum) over a generic one (a clipboard, a pin, a check mark). Two tasks about different things should look different.

Answer with JSON alone: an object from each task's number, as a string, to one emoji. Nothing else."""


# --- what an icon is -------------------------------------------------------------------------


def is_picture(icon: str) -> bool:
    """Whether this icon is a picture's file name rather than an emoji."""
    return bool(_PICTURE.match(str(icon or "")))


def emoji_of(said: str) -> str:
    """The one emoji at the start of `said`, with whatever joins it, or "" when it starts with
    none. A flag is two regional letters, a family is several joined by zero-width joiners."""
    from . import chats

    said = str(said or "").strip()
    if not said or not chats.is_emoji(said[0]) or said[0] == "\ufe0f":
        return ""
    if 0x1F1E6 <= ord(said[0]) <= 0x1F1FF:
        two = said[:2]
        return two if len(two) == 2 and 0x1F1E6 <= ord(two[1]) <= 0x1F1FF else said[0]
    end = 1
    while end < len(said):
        ch = said[end]
        if ch in ("\ufe0f", "\u20e3") or 0x1F3FB <= ord(ch) <= 0x1F3FF:
            end += 1
        elif ch == "\u200d" and end + 1 < len(said):
            end += 2
        else:
            break
    return said[:end]


def folder() -> Path:
    from .config import config

    return Path(config.data_dir) / FOLDER


def src(icon: str) -> str:
    """What the page draws: the emoji as it is, or a picture as a data address, or "" for a
    picture whose file is gone, which the page draws as the guess for its title."""
    if not is_picture(icon):
        return icon or ""
    return _data_address(icon)


_SEEN: dict[str, tuple[float, str]] = {}


def _data_address(name: str) -> str:
    path = folder() / name
    try:
        when = path.stat().st_mtime
    except OSError:
        return ""
    kept = _SEEN.get(name)
    if kept and kept[0] == when:
        return kept[1]
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    ext = name.rsplit(".", 1)[-1]
    out = f"data:{MEDIA.get(ext, 'image/png')};base64,{base64.b64encode(data).decode()}"
    _SEEN[name] = (when, out)
    return out


def shown(icon: str, title: str) -> dict:
    """An icon as the pages are sent it: `icon` the emoji (or the guess while there is none
    yet, or a picture's file is gone) and `img` a picture's data address, or ""."""
    img = src(icon) if is_picture(icon) else ""
    if img:
        return {"icon": "", "img": img}
    return {"icon": icon if icon and not is_picture(icon) else guess(title), "img": ""}


# --- the guess -------------------------------------------------------------------------------

#: Words in a title, and the emoji a task about them gets when no model can be asked. The first
#: that matches wins, so the more particular come first. A match is on the start of a word.
WORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("bug", "fix", "broken", "error", "crash"), "\U0001F41E"),
    (("deploy", "server", "docker", "container", "kubernetes", "nginx", "ssh"), "\U0001F5A5\ufe0f"),
    (("test", "playwright", "verify", "check"), "\U0001F9EA"),
    (("code", "refactor", "repo", "github", "git", "api", "script", "python", "javascript"),
     "\U0001F4BB"),
    (("rouh", "agent", "model", "llm", "claude", "openai", "gpt", "ai", "prompt"), "\U0001F916"),
    (("robot", "vacuum", "dreame", "roomba"), "\U0001F9F9"),
    (("car", "seat", "drive", "vehicle", "tyre", "tire"), "\U0001F697"),
    (("flight", "fly", "travel", "trip", "airport", "visa", "holiday", "vacation"), "\u2708\ufe0f"),
    (("hotel", "booking", "stay"), "\U0001F3E8"),
    (("house", "home", "property", "apartment", "flat", "rent", "lease", "mortgage", "renovat"),
     "\U0001F3E0"),
    (("garden", "plant", "tree", "flower"), "\U0001F331"),
    (("doctor", "health", "medical", "clinic", "dentist", "hospital", "therapy", "gene"), "\U0001FA7A"),
    (("baby", "child", "kid", "son", "daughter", "school", "kindergarten"), "\U0001F9D2"),
    (("birthday", "party", "gift", "present"), "\U0001F381"),
    (("wedding", "marriage"), "\U0001F48D"),
    (("money", "pay", "payment", "invoice", "bank", "tax", "budget", "price", "cost", "salary",
      "finance", "accounting", "receipt"), "\U0001F4B6"),
    (("insurance",), "\U0001F6E1\ufe0f"),
    (("legal", "law", "contract", "lawyer", "court", "foundation", "register", "licen", "patent"),
     "\u2696\ufe0f"),
    (("buy", "purchase", "shop", "order", "store"), "\U0001F6D2"),
    (("email", "mail", "inbox", "reply", "newsletter"), "\u2709\ufe0f"),
    (("telegram", "slack", "message", "chat", "whatsapp"), "\U0001F4AC"),
    (("call", "phone", "meeting", "interview"), "\U0001F4DE"),
    (("calendar", "schedule", "plan", "nightly", "weekly", "daily", "remind"), "\U0001F4C5"),
    (("research", "compare", "which", "find", "search", "investigat", "study"), "\U0001F50D"),
    (("write", "article", "post", "blog", "book", "playbook", "doc", "copy", "notes", "summary"),
     "\u270D\ufe0f"),
    (("design", "logo", "brand", "colour", "color", "icon"), "\U0001F3A8"),
    (("site", "website", "page", "web", "landing"), "\U0001F310"),
    (("video", "film", "youtube", "camera", "photo", "picture", "image"), "\U0001F3AC"),
    (("music", "song", "audio", "sound", "voice", "podcast", "speech", "transcri"), "\U0001F3A7"),
    (("learn", "course", "teach", "lesson", "training"), "\U0001F393"),
    (("hire", "hiring", "recruit", "candidate", "role", "job", "career"), "\U0001F91D"),
    (("sell", "sales", "client", "customer", "deal", "pitch", "investor"), "\U0001F4C8"),
    (("security", "password", "secret", "backup", "privacy"), "\U0001F512"),
    (("network", "wifi", "router", "internet", "5g"), "\U0001F4F6"),
    (("print", "printer", "scan"), "\U0001F5A8\ufe0f"),
    (("3d", "blender", "model"), "\U0001F9CA"),
    (("food", "cook", "recipe", "restaurant", "dinner"), "\U0001F37D\ufe0f"),
    (("sport", "gym", "run", "fitness", "bike", "ski"), "\U0001F3C3"),
    (("idea", "suggest", "brainstorm"), "\U0001F4A1"),
    (("goal", "quest"), "\U0001F3AF"),
)

#: A task whose title matches nothing above.
DEFAULT = "\U0001F4CC"


def guess(title: str) -> str:
    """An emoji for a task from the words of its title alone, with no model: an emoji the title
    starts with, else the first of `WORDS` whose word starts one of its words, else `DEFAULT`."""
    own = emoji_of(title)
    if own:
        return own
    words = re.findall(r"[a-z0-9]+", str(title or "").lower())
    for keys, emoji in WORDS:
        if any(word.startswith(key) for key in keys for word in words):
            return emoji
    return DEFAULT


# --- the model's pick ------------------------------------------------------------------------


def _question(rows: list[tuple[str, str, str]]) -> str:
    lines = []
    for n, (_ident, title, above) in enumerate(rows, 1):
        line = f"{n}. {title.strip()[:160]}"
        if above:
            line += f"  (a step of: {above.strip()[:100]})"
        lines.append(line)
    return "The tasks:\n" + "\n".join(lines)


def read_back(text: str, rows: list[tuple[str, str, str]]) -> dict[str, str]:
    """The model's answer, as an emoji by task id, for the tasks it gave a real emoji to."""
    found = re.search(r"\{.*\}", str(text or ""), re.DOTALL)
    if not found:
        return {}
    try:
        got = json.loads(found.group(0))
    except ValueError:
        return {}
    if not isinstance(got, dict):
        return {}
    out = {}
    for key, said in got.items():
        try:
            n = int(str(key).strip().rstrip("."))
        except ValueError:
            continue
        emoji = emoji_of(str(said or ""))
        if 1 <= n <= len(rows) and emoji:
            out[rows[n - 1][0]] = emoji
    return out


async def pick(rows: list[tuple[str, str, str]], *, who=None) -> dict[str, str]:
    """An emoji for every one of these tasks, by id: the model's, a batch to a question, and the
    guess for any it gave none to or could not be asked about."""
    from . import llm

    out: dict[str, str] = {}
    for start in range(0, len(rows), BATCH):
        some = rows[start:start + BATCH]
        try:
            got = await llm.ask(USE, system=SYSTEM, messages=_question(some),
                                max_tokens=40 * len(some) + 200, who=who, timeout=TIMEOUT,
                                subject=f"{len(some)} task icons", read_only=True)
            out.update(read_back(got.text, some))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the guess stands in, never an error
            log.warning("the task icon model could not be asked (%s); guessing from the titles",
                        exc)
        for ident, title, _above in some:
            out.setdefault(ident, guess(title))
    return out


async def fill(*, every: bool = False, who=None) -> int:
    """Give every task with no icon one, or with `every` every task a new one over whatever it
    has (`manage.py task_icons --all`). How many were written."""
    from . import objects

    store = objects.shared_store(even_when_off=True)
    if store is None:
        return 0
    written = 0
    # A few hundred at a time, until none is left; a task the model gave nothing to is given
    # the guess, so every pass leaves fewer.
    for _pass in range(1 if every else 20):
        rows = await asyncio.to_thread(lambda: store.tasks_for_icons(
            every=every, limit=None if every else PASS))
        if not rows:
            break
        picked = await pick(rows, who=who)
        some = 0
        for ident, emoji in picked.items():
            if await asyncio.to_thread(store.set_task_icon, ident, emoji,
                                       only_if_none=not every, by=BY):
                some += 1
        written += some
        if not some:
            break
    if written:
        log.info("task icons: %s picked", written)
    return written


# --- a picture -------------------------------------------------------------------------------


def kind_of(data: bytes) -> str:
    """The extension a picture is kept under, or "" for bytes that are no picture taken here."""
    for head, ext, _media in KINDS:
        if data.startswith(head):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def save_picture(task_id: str, data: bytes) -> dict:
    """Keep a picture as one task's icon: written into `folder()`, its name into the task's row.
    {"ok": True, "icon": name} or {"ok": False, "why": words}."""
    from . import objects

    if not data:
        return {"ok": False, "why": "That picture is empty."}
    if len(data) > MOST_BYTES:
        return {"ok": False, "why": "That picture is too big for an icon. Pick a smaller one."}
    ext = kind_of(data)
    if not ext:
        return {"ok": False, "why": "An icon can be a PNG, JPEG, GIF or WebP picture."}
    store = objects.shared_store(even_when_off=True)
    if store is None or store.get_task(task_id) is None:
        return {"ok": False, "why": "There is no task here with that id."}
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", task_id)[:80] or "task"
    name = f"{safe}-{hashlib.sha256(data).hexdigest()[:12]}.{ext}"
    here = folder()
    try:
        here.mkdir(parents=True, exist_ok=True)
        path = here / name
        if not path.exists():
            spare = here / f".{name}.part"
            spare.write_bytes(data)
            os.replace(spare, path)
    except OSError as exc:
        log.exception("a task's icon could not be written")
        return {"ok": False, "why": f"It could not be saved here: {exc}"}
    store.set_task_icon(task_id, name, by=PERSON)
    return {"ok": True, "icon": name}


def set_emoji(task_id: str, said: str) -> dict:
    """One task's icon, as the person picked it: {"ok", "why"}."""
    from . import objects

    emoji = emoji_of(said)
    if not emoji:
        return {"ok": False, "why": "That is not an emoji."}
    store = objects.shared_store(even_when_off=True)
    if store is None or store.get_task(task_id) is None:
        return {"ok": False, "why": "There is no task here with that id."}
    store.set_task_icon(task_id, emoji, by=PERSON)
    return {"ok": True}


# --- the picker ------------------------------------------------------------------------------


class Picker:
    """Gives every task with no icon one: once a little after start, whenever a task is made
    (`poke`), and every `BEAT` in case something was made where nothing poked."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None

    def start(self) -> None:
        if self._task is None:
            self._loop = asyncio.get_running_loop()
            self._wake = asyncio.Event()
            self._task = self._loop.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    def poke(self) -> None:
        """From any thread: look now."""
        loop, wake = self._loop, self._wake
        if loop is None or wake is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(wake.set)

    async def _run(self) -> None:
        await asyncio.sleep(5.0)
        while True:
            assert self._wake is not None
            self._wake.clear()
            try:
                await fill()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the task icon picker failed")
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), BEAT)
            # A few tasks made together are one question.
            await asyncio.sleep(2.0)


#: The one picker in this process.
picker = Picker()


def poke() -> None:
    """A task was made: give it its icon in a moment."""
    picker.poke()


__all__ = ["BEAT", "DEFAULT", "FOLDER", "Picker", "USE", "WORDS", "emoji_of", "fill", "folder",
           "guess", "is_picture", "pick", "picker", "poke", "read_back", "save_picture",
           "set_emoji", "shown", "src"]
