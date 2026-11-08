"""Demo mode: one switch that blurs the person's content everywhere, so Rouh can be shown and
recorded with nothing of theirs readable (task 155, Show off Rouh).

Petar, 28 October 2026: "with one toggle we can safely blur everything - no risk. Then we
manually go through tasks and settings and designate what can be unblurred... purple dots
showing me where I have content and unblurred sections... for tasks that I really want to show
and have actually PII, we will specifically make a copy and that copy will be enabled and
visible only during this mode."

**The switch is the account's.** It is a row (`DemoState`), so every device and every tab
follows it: each tab is told the moment it changes (`broadcast`), each page asks before it draws
(`views.index` sets the `rouh_demo` cookie the page's first script reads), and every change is
written down with when and from which device (`DemoEvent`). It is not an item in Decisions:
nothing waits on anybody.

**The browser blurs, from the first paint.** Petar, the same day: "just make sure css loads
first, and I can freely open new tabs and the loading won't mess up, also if I do refresh". So
every page carries demo mode's style and first script inline in its head (`rouh/demo_style.py`),
which draw every word that is not the interface's as the same soft bar, and the server sends
what it always sends.

**What may be seen is approved, as it was** (`DemoApproval`). A task with all its steps, one
step, a chat, a card or a section of settings; each with a fingerprint of what it was, so
anything changed afterwards is blurred again until it is approved again (`changed`).

**The stage.** What happens while it is on is in front of the audience and is drawn as it is: a
turn asked at a tab (`stage_turn`), and a chat started and talked in while it is on. Such a
turn is told none of the person's memory, rules or words, and offered only tools that see
nothing of theirs (`TOOLS`).

**Demo copies.** A copy of a task that the person makes safe by hand (`make_copy`): shown only
while demo mode is on, and left out of every list when it is off (`hide_copies`).

**A preview** is the same lens for one browser only (the `rouh_demo_preview` cookie), with
nothing written down: for walking through the talk the night before.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlsplit

log = logging.getLogger("rouh")

#: The cookie the server sets while the account is in demo mode, read by the page's first
#: script before anything is drawn. Not secret: it says only that the screen is to be blurred.
COOKIE = "rouh_demo"
#: The cookie that puts one browser in the preview.
PREVIEW_COOKIE = "rouh_demo_preview"

KINDS = ("task", "step", "chat", "card", "setting", "copy")

#: The tools a turn on the stage may use: they see nothing of the person's but what was approved,
#: or nothing of theirs at all. Every other tool is not offered, and is refused if asked for.
TOOLS = frozenset("""
show_on_screen revise_on_screen set_panels show_canvas show_workspace_page read_workspace
make_picture change_picture rename_this_chat make_a_task youtube_search youtube_transcript
web_search web_fetch code_execution
""".split())

#: Set for the length of one turn on the stage (`runtime.Turn._answer`).
STAGE = contextvars.ContextVar("rouh_demo_stage", default=False)
#: The lens of the person whose turn this is, for the tools that read the workspace.
STAGE_LENS = contextvars.ContextVar("rouh_demo_stage_lens", default=None)

#: The lens of whoever a workspace page is being drawn for, when they are in demo mode or its
#: preview, set by the view around the drawing (`browser_marks`).
PAGE_LENS = contextvars.ContextVar("rouh_demo_page_lens", default=None)

_STAGE_TURNS: dict[str, float] = {}
#: When each turn on the stage began, by chat: the rows a chat holds from then are the stage's.
_STAGE_WINDOWS: dict[str, list[float]] = {}
#: How long after a turn on the stage began its rows are still taken for its own.
STAGE_TURN_SECONDS = 900
_STATE: dict[tuple[str, str], tuple[float, dict]] = {}
_LENSES: dict[tuple[str, str, bool], tuple[float, "Lens"]] = {}
_COPIES: list = [0.0, {}]
_LOCK = threading.Lock()
#: How long a read of the switch is trusted before it is read again. A change made in this
#: process forgets it at once (`forget`); this is for one made by another.
STATE_SECONDS = 2.0
LENS_SECONDS = 4.0

_NUMBER = re.compile(r"^(\d+(?:-\d+)*)(?:\.|$)")


def _whose(who) -> tuple[str, str]:
    return str(getattr(who, "org_id", "") or ""), str(getattr(who, "user_id", "") or "")


def _root() -> str:
    from .config import config

    return str(config.assistant_repo or "")


# --------------------------------------------------------------------------
# The switch
# --------------------------------------------------------------------------

def state(who) -> dict:
    """{on, since, device, dots, updated_at} for one person, read at most every few seconds."""
    if who is None:
        return {"on": False, "since": 0.0, "device": "", "dots": True, "updated_at": 0.0}
    key = _whose(who)
    now = time.monotonic()
    got = _STATE.get(key)
    if got is not None and now - got[0] < STATE_SECONDS:
        return got[1]
    from .models import DemoState

    row = DemoState.objects.filter(org_id=key[0], user_id=key[1]).first()
    said = {"on": bool(row and row.on), "since": float(row.since) if row else 0.0,
            "device": row.device if row else "", "dots": bool(row.dots) if row else True,
            "updated_at": float(row.updated_at) if row else 0.0}
    _STATE[key] = (now, said)
    return said


def is_on(who) -> bool:
    try:
        return bool(state(who)["on"])
    except Exception:
        log.exception("demo: whether demo mode is on could not be read; taking it as on")
        return True


def forget(who=None) -> None:
    """Read the switch and the approvals again next time."""
    with _LOCK:
        if who is None:
            _STATE.clear()
            _LENSES.clear()
            return
        key = _whose(who)
        _STATE.pop(key, None)
        for k in [k for k in _LENSES if k[:2] == key]:
            _LENSES.pop(k, None)
    _COPIES[0] = 0.0


def device_of(agent: str) -> str:
    """A browser's own words for itself, as a few words a person recognises."""
    a = agent or ""
    kind = ("iPhone" if "iPhone" in a else "iPad" if "iPad" in a else "Android" if "Android" in a
            else "Mac" if "Macintosh" in a else "Windows" if "Windows" in a
            else "Linux" if "Linux" in a else "a device")
    browser = ("Edge" if "Edg/" in a else "Chrome" if "Chrome/" in a or "CriOS" in a
               else "Firefox" if "Firefox/" in a or "FxiOS" in a else "Safari" if "Safari/" in a
               else "a browser")
    return f"{kind}, {browser}"


def turn(who, on: bool, *, agent: str = "", address: str = "") -> dict:
    """Turn demo mode on or off for one person, write it down, and tell every tab of theirs."""
    from .models import DemoEvent, DemoState

    org_id, user_id = _whose(who)
    now = time.time()
    device = device_of(agent)
    row, _ = DemoState.objects.get_or_create(org_id=org_id, user_id=user_id,
                                             defaults={"updated_at": now})
    if bool(row.on) != bool(on):
        row.on = bool(on)
        if on:
            row.since = now
        row.device = device
        row.updated_at = now
        row.save()
        DemoEvent.objects.create(org_id=org_id, user_id=user_id, on=bool(on), at=now,
                                 device=device, agent=(agent or "")[:300],
                                 address=(address or "")[:300])
        log.info("demo mode %s for %s from %s", "on" if on else "off", user_id, device)
    forget(who)
    return state(who)


def set_dots(who, dots: bool) -> dict:
    from .models import DemoState

    org_id, user_id = _whose(who)
    row, _ = DemoState.objects.get_or_create(org_id=org_id, user_id=user_id,
                                             defaults={"updated_at": time.time()})
    row.dots = bool(dots)
    row.save()
    forget(who)
    return state(who)


def history(who, limit: int = 50) -> list[dict]:
    from .models import DemoEvent

    org_id, user_id = _whose(who)
    rows = DemoEvent.objects.filter(org_id=org_id, user_id=user_id).order_by("-at")[:limit]
    return [{"on": r.on, "at": r.at, "device": r.device} for r in rows]


async def broadcast(who) -> None:
    """Every open tab of this person's hears the switch now, and blurs or clears."""
    from . import runtime

    org_id, user_id = _whose(who)
    for tab in list(runtime.Hub.sockets):
        me = getattr(tab, "me", None)
        if tab.closed or me is None or _whose(me) != (org_id, user_id):
            continue
        try:
            await tab.send({"type": "demo", **page_state(me, getattr(tab, "demo_preview", False))})
        except Exception:
            log.exception("demo: a tab could not be told")


# --------------------------------------------------------------------------
# What may be seen
# --------------------------------------------------------------------------

_HASHES: dict[tuple[str, int, int], str] = {}


def _file_hash(path: str, st: os.stat_result) -> str:
    key = (path, st.st_size, st.st_mtime_ns)
    got = _HASHES.get(key)
    if got is None:
        h = hashlib.sha1()
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        except OSError:
            return "?"
        got = h.hexdigest()
        if len(_HASHES) > 20000:
            _HASHES.clear()
        _HASHES[key] = got
    return got


def fingerprint_folder(rel: str) -> str:
    """What a task's or a step's folder holds now, and what its row says, as one hash."""
    root = _root()
    base = os.path.join(root, rel)
    h = hashlib.sha256()
    if os.path.isdir(base):
        for here, dirs, files in os.walk(base):
            dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d != "temp")
            for name in sorted(files):
                if name.startswith(".") and name != ".object.json":
                    continue
                path = os.path.join(here, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                h.update(os.path.relpath(path, base).encode("utf-8", "surrogateescape"))
                h.update(_file_hash(path, st).encode())
    try:
        from . import objects

        store = objects.shared_store(even_when_off=True)
        row = store.by_folder("task", rel) if store is not None else None
        if row is not None:
            said = {k: getattr(row, k, None) for k in ("title", "summary", "status")}
            h.update(json.dumps(said, sort_keys=True, default=str).encode())
    except Exception:
        log.exception("demo: the row of %s could not be read for its fingerprint", rel)
    return h.hexdigest()


def fingerprint_chat(chat: str) -> str:
    """The newest message of a chat now: what comes after it is not approved."""
    from .models import TranscriptMessage

    last = TranscriptMessage.objects.filter(session_id=chat).order_by("-id").values_list("id", flat=True).first()
    return str(last or 0)


def card_hash(spec: dict) -> str:
    said = {k: spec.get(k) for k in ("title", "description", "blocks")}
    return hashlib.sha256(json.dumps(said, sort_keys=True, default=str).encode()).hexdigest()


def _card_now(ident: str) -> dict | None:
    from . import artifacts

    try:
        got = artifacts.about(ident, root=_root()) if artifacts.enabled() else None
    except Exception:
        return None
    if not isinstance(got, dict):
        return None
    spec = got.get("spec") if isinstance(got.get("spec"), dict) else got
    return spec


def current(kind: str, ref: str) -> str:
    """Where an approved task or step is now: a task moved to another project since keeps its
    number, and is found by it."""
    if kind not in ("task", "step", "copy") or os.path.isdir(os.path.join(_root(), ref)):
        return ref
    m = _NUMBER.match(ref.rsplit("/", 1)[-1])
    return (folder_for_number(m.group(1)) if m else "") or ref


def fingerprint(kind: str, ref: str) -> str:
    if kind in ("task", "step", "copy"):
        return fingerprint_folder(ref)
    if kind == "chat":
        return fingerprint_chat(ref)
    if kind == "card":
        spec = _card_now(ref)
        return card_hash(spec) if spec else ""
    return ""


def folder_of(asked: str) -> str:
    """A task's or a step's folder from anything that names it: its folder, its address, its
    number."""
    said = unquote(str(asked or "")).strip()
    for lead in ("/workspace/_task/", "/workspace/", "/task/", "/project/", "/sources/"):
        if said.startswith(lead):
            said = said[len(lead):]
            break
    said = said.split("?")[0].split("#")[0].strip("/")
    if re.fullmatch(r"\d+(?:-\d+)*", said):
        found = folder_for_number(said)
        return found or ""
    root = _root()
    while said and not os.path.isdir(os.path.join(root, said)):
        said = said.rsplit("/", 1)[0] if "/" in said else ""
    return said


def folder_for_number(number: str) -> str:
    """The folder of task "155" or step "155-01", from the rows or the disk."""
    root = _root()
    task = number.split("-")[0]
    try:
        from .models import Task

        row = Task.objects.filter(number=int(task)).values("folder").first()
        base = row["folder"] if row else ""
    except Exception:
        base = ""
    if not base:
        return ""
    if "-" not in number:
        return base
    full = os.path.join(root, base)
    try:
        for name in os.listdir(full):
            if name.startswith(number + "."):
                return f"{base}/{name}"
    except OSError:
        pass
    return ""


def approve(who, kind: str, ref: str) -> dict:
    """Let the audience see one thing, as it is now."""
    from .models import DemoApproval

    if kind not in KINDS or kind == "copy":
        raise ValueError("That cannot be approved for demo mode.")
    if kind in ("task", "step"):
        ref = folder_of(ref)
        if not ref:
            raise ValueError("There is no task or step there.")
    ref = str(ref or "").strip()[:500]
    if not ref:
        raise ValueError("Nothing was named.")
    org_id, user_id = _whose(who)
    row, _ = DemoApproval.objects.update_or_create(
        org_id=org_id, user_id=user_id, kind=kind, ref=ref,
        defaults={"fingerprint": fingerprint(kind, ref), "approved_at": time.time()})
    forget(who)
    return {"kind": kind, "ref": ref, "approved_at": row.approved_at}


def unapprove(who, kind: str, ref: str) -> bool:
    from .models import DemoApproval

    if kind in ("task", "step"):
        ref = folder_of(ref) or ref
    org_id, user_id = _whose(who)
    gone, _ = DemoApproval.objects.filter(org_id=org_id, user_id=user_id, kind=kind,
                                          ref=ref).exclude(kind="copy").delete()
    forget(who)
    return bool(gone)


@dataclass
class Lens:
    """What one person's audience may see, worked out once and asked many times a second."""

    on: bool
    since: float = 0.0
    preview: bool = False
    dots: bool = True
    folders: set = field(default_factory=set)
    numbers: set = field(default_factory=set)
    deep: set = field(default_factory=set)
    #: Approved chats, each with the newest message approved with it.
    chats: dict = field(default_factory=dict)
    stage_chats: set = field(default_factory=set)
    cards: dict = field(default_factory=dict)
    settings: set = field(default_factory=set)
    copies: dict = field(default_factory=dict)
    changed: list = field(default_factory=list)

    # -- asked by demo_redact --
    def shows_number(self, number: str) -> bool:
        number = str(number or "")
        if number in self.numbers:
            return True
        task = number.split("-")[0]
        return task in self.deep

    def shows_folder(self, rel: str) -> bool:
        rel = str(rel or "").strip("/")
        if not rel:
            return False
        for f in self.folders:
            if rel == f or rel.startswith(f + "/"):
                return True
        last = rel.rsplit("/", 1)[-1]
        m = _NUMBER.match(last)
        if m and "." in last and self.shows_number(m.group(1)):
            # Only a folder named by a number shown, inside the same place.
            return any(rel.startswith(f.rsplit("/", 1)[0] + "/") for f in self.folders)
        return False

    def shows_value(self, key: str, value) -> bool:
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            return False
        v = str(value)
        if not v:
            return False
        if key in ("chat", "chat_id", "session_id", "id"):
            if v in self.chats or v in self.stage_chats:
                return True
            if key == "id":
                return False
        if key in ("number", "num", "task", "task_number", "step", "label") and \
                re.fullmatch(r"\d+(?:-\d+)*", v):
            return self.shows_number(v)
        if key in ("folder", "path", "rel", "href", "url", "link", "address", "dir", "slug", "task",
                   "step", "page", "at_path"):
            said = unquote(v)
            parts = urlsplit(said)
            path = parts.path if parts.scheme in ("", "http", "https") else ""
            for lead in ("/workspace/_task/", "/workspace/", "/task/", "/project/", "/sources/"):
                if path.startswith(lead):
                    path = path[len(lead):]
                    break
            else:
                if path.startswith("/"):
                    return False
            return self.shows_folder(path)
        return False

    def shows_setting(self, name: str) -> bool:
        return name in self.settings


def lens_for(who, preview: bool = False) -> Lens | None:
    """The lens for one person now, or None when they are not in demo mode (nor previewing)."""
    if who is None:
        return None
    st = state(who)
    if not st["on"] and not preview:
        return None
    key = (*_whose(who), bool(preview and not st["on"]))
    now = time.monotonic()
    got = _LENSES.get(key)
    if got is not None and now - got[0] < LENS_SECONDS:
        return got[1]
    lens = _build(who, st, preview and not st["on"])
    with _LOCK:
        _LENSES[key] = (now, lens)
    return lens


def _build(who, st: dict, preview: bool) -> Lens:
    from .models import Chat, DemoApproval

    org_id, user_id = _whose(who)
    since = st["since"] if st["on"] else time.time()
    lens = Lens(on=True, since=since, preview=preview, dots=st["dots"] or preview)
    for row in DemoApproval.objects.filter(org_id=org_id, user_id=user_id):
        row.ref = current(row.kind, row.ref)
        now = fingerprint(row.kind, row.ref) if row.kind not in ("setting", "copy") else ""
        if row.kind in ("task", "step"):
            if row.fingerprint and now != row.fingerprint:
                lens.changed.append({"kind": row.kind, "ref": row.ref, "approved_at": row.approved_at})
                continue
            lens.folders.add(row.ref)
            m = _NUMBER.match(row.ref.rsplit("/", 1)[-1])
            if m:
                lens.numbers.add(m.group(1))
                if row.kind == "task":
                    lens.deep.add(m.group(1))
        elif row.kind == "copy":
            lens.copies[row.ref] = row.source
            lens.folders.add(row.ref)
            m = _NUMBER.match(row.ref.rsplit("/", 1)[-1])
            if m:
                lens.numbers.add(m.group(1))
                lens.deep.add(m.group(1))
        elif row.kind == "chat":
            try:
                lens.chats[row.ref] = int(row.fingerprint or 0)
            except ValueError:
                lens.chats[row.ref] = 0
        elif row.kind == "card":
            lens.cards[row.ref] = row.fingerprint
        elif row.kind == "setting":
            lens.settings.add(row.ref)
    if st["on"]:
        # A chat started on the stage, and talked in there, is the stage's own, its name too.
        talked = [c for c, began in _STAGE_WINDOWS.items() if any(b >= since - 1 for b in began)]
        if talked:
            lens.stage_chats = set(Chat.objects.filter(id__in=talked, created_at__gte=since - 1)
                                   .values_list("id", flat=True))
    return lens


def page_state(who, preview: bool = False) -> dict:
    """What a tab is told: whether it is in demo mode, and what it may put a purple dot on."""
    st = state(who)
    lens = lens_for(who, preview) if (st["on"] or preview) else None
    out = {"on": bool(st["on"]), "preview": bool(preview and not st["on"]), "since": st["since"],
           "device": st["device"], "dots": st["dots"]}
    if lens is not None:
        out["shown"] = {
            "numbers": _shown_numbers(lens),
            "chats": sorted(set(lens.chats) | lens.stage_chats),
            "settings": sorted(lens.settings),
            "cards": sorted(lens.cards),
            # Each approved chat with the newest message approved with it (0 for all of it).
            "chat_upto": {c: n for c, n in lens.chats.items()},
        }
        # When each turn on the stage began, by chat: what it said is drawn as it is.
        out["stage"] = {c: [b for b in began if b >= out["since"] - 1]
                        for c, began in _STAGE_WINDOWS.items()
                        if any(b >= out["since"] - 1 for b in began)}
        out["stage_seconds"] = STAGE_TURN_SECONDS
        out["turns"] = [t for t, at in _STAGE_TURNS.items() if at >= out["since"] - 1][-200:]
        out["changed"] = len(lens.changed)
    return out


def _shown_numbers(lens: Lens) -> list[str]:
    """The numbers approved, a task approved with its steps as "155" and "155*"."""
    return sorted(lens.numbers | {n + "*" for n in lens.deep})


def browser_marks(who) -> dict:
    """What the task browser is told: whether demo mode (or its preview) is on, so it draws the
    purple dots, and every number approved, for Shown in demo, on or off."""
    if who is None:
        # Every answer has the same three keys: `index_data` reads `demo` on every call, and a
        # call with nobody reading it (the one thing's picker, `rouh/one_thing.py`) had none, so
        # from 7 November 2026 the picker said "Your projects could not be read just now" to
        # everybody (fr_7bfe96b7672b).
        return {"on": False, "demo": False, "shown": []}
    seen = PAGE_LENS.get()
    lens = seen
    try:
        if lens is None:
            lens = _build(who, state(who), True)
    except Exception:
        log.exception("demo: what is approved could not be read for the task browser")
        return {"on": False, "demo": seen is not None, "shown": []}
    # `on` draws the dots; `demo` is whether the page is being looked at in demo mode at all.
    return {"on": bool(seen is not None and (lens.dots or lens.preview)), "demo": seen is not None,
            "shown": _shown_numbers(lens)}


def approvals(who) -> dict:
    """Everything approved, by kind, with what changed since: for the panel under the switch."""
    from .models import DemoApproval

    org_id, user_id = _whose(who)
    lens = lens_for(who, preview=True) or _build(who, state(who), True)
    changed = {(c["kind"], c["ref"]) for c in lens.changed}
    rows = []
    for row in DemoApproval.objects.filter(org_id=org_id, user_id=user_id).order_by("-approved_at"):
        rows.append({"kind": row.kind, "ref": row.ref, "approved_at": row.approved_at,
                     "source": row.source, "changed": (row.kind, row.ref) in changed,
                     "number": _NUMBER.match(row.ref.rsplit("/", 1)[-1]).group(1)
                     if _NUMBER.match(row.ref.rsplit("/", 1)[-1]) else ""})
    return {"items": rows, "changed": len(changed)}


# --------------------------------------------------------------------------
# The stage
# --------------------------------------------------------------------------

def stage_turn(turn_id, chat: str = "") -> None:
    """This turn was asked at a tab while demo mode was on: what it says is drawn as it is, now
    and when the chat is read back."""
    now = time.time()
    _STAGE_TURNS[str(turn_id)] = now
    if chat:
        _STAGE_WINDOWS.setdefault(chat, []).append(now)
        with _LOCK:
            _LENSES.clear()
    if len(_STAGE_TURNS) > 2000:
        for k in sorted(_STAGE_TURNS, key=_STAGE_TURNS.get)[:1000]:
            _STAGE_TURNS.pop(k, None)


def on_stage() -> bool:
    return bool(STAGE.get())


def tool_allowed(name: str) -> bool:
    return name in TOOLS


def refused(name: str) -> str:
    return (f"{name} is not available in demo mode: it would read the person's own data, and "
            "the screen is being shown to an audience. Answer from what is on the screen and in "
            "the tasks approved for the demo.")


def readable(rel: str) -> bool:
    """May a turn on the stage read this workspace file? Only inside what was approved."""
    lens = STAGE_LENS.get()
    if lens is None:
        return True
    rel = str(rel or "").strip("/")
    if rel in ("", "_tasks.md"):
        return False
    return lens.shows_folder(rel) or lens.shows_folder(rel.rsplit("/", 1)[0])


# --------------------------------------------------------------------------
# Demo copies
# --------------------------------------------------------------------------

def copies() -> dict:
    """Every demo copy there is, folder to its original's, read at most every few seconds."""
    now = time.monotonic()
    if now - _COPIES[0] < LENS_SECONDS:
        return _COPIES[1]
    from .models import DemoApproval

    try:
        found = {current("copy", ref): source for ref, source in
                 DemoApproval.objects.filter(kind="copy").values_list("ref", "source")}
    except Exception:
        found = {}
    _COPIES[0] = now
    _COPIES[1] = found
    return found


def copy_numbers() -> set:
    out = set()
    for rel in copies():
        m = _NUMBER.match(rel.rsplit("/", 1)[-1])
        if m:
            out.add(m.group(1))
    return out


def _names_a_copy(d: dict, folders: dict, numbers: set) -> bool:
    for key in ("folder", "dir", "path", "rel", "href", "url"):
        v = d.get(key)
        if isinstance(v, str) and v:
            v = unquote(v)
            for f in folders:
                if f in v:
                    return True
    for key in ("number", "num", "task", "task_number"):
        v = d.get(key)
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v) in numbers:
            return True
    return False


def hide_copies(value, folders: dict | None = None, numbers: set | None = None):
    """A JSON value with every row that is a demo copy taken out: outside demo mode they are
    nowhere."""
    if folders is None:
        folders = copies()
        if not folders:
            return value
        numbers = copy_numbers()
    if isinstance(value, list):
        return [hide_copies(v, folders, numbers) for v in value
                if not (isinstance(v, dict) and _names_a_copy(v, folders, numbers))]
    if isinstance(value, dict):
        return {k: hide_copies(v, folders, numbers) for k, v in value.items()}
    return value


def make_copy(who, asked: str) -> dict:
    """A demo copy of a task with its steps and pages, beside it, for the person to make safe."""
    from . import objects, objecttree, taskmeta
    from .models import DemoApproval

    root = _root()
    rel = folder_of(asked)
    if not rel:
        raise ValueError("There is no task there to copy.")
    store = objects.shared_store(even_when_off=True)
    src = store.by_folder("task", rel)
    if src is None:
        raise ValueError("There is no task there to copy.")
    # Beside its original, in the same project.
    _rows, owners, _under = objecttree.tree_now(store)
    owner = owners.get(getattr(src, "id", ""), "") or ""
    title = (getattr(src, "title", "") or rel.rsplit("/", 1)[-1]) + " (demo copy)"
    made = objecttree.create(root, store, type="task", title=title, owner=owner)
    new_rel = made["rel"]
    src_path = Path(root) / rel
    new_path = Path(root) / new_rel
    old_number = _NUMBER.match(rel.rsplit("/", 1)[-1]).group(1)
    new_number = str(made.get("number") or _NUMBER.match(new_rel.rsplit("/", 1)[-1]).group(1))
    # The task's own files, then each step as a step of the copy, made the same way any step is.
    for item in sorted(src_path.iterdir()):
        if item.name.startswith(".") or item.name == "temp":
            continue
        step = re.match(rf"^{re.escape(old_number)}-(\d+)\.", item.name)
        if item.is_dir() and step:
            step_row = store.by_folder("task", f"{rel}/{item.name}")
            step_title = getattr(step_row, "title", "") or item.name.split(".", 1)[-1].replace("-", " ")
            made_step = objecttree.create(root, store, type="task", title=step_title, owner=made["id"])
            target = Path(root) / made_step["rel"]
            for inner in item.iterdir():
                if inner.name in (".object.json", "temp"):
                    continue
                dest = target / inner.name.replace(f"{old_number}-", f"{new_number}-", 1)
                if inner.is_dir():
                    shutil.copytree(inner, dest, dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns("temp", ".object.json"))
                else:
                    shutil.copy2(inner, dest)
        elif item.is_dir():
            shutil.copytree(item, new_path / item.name, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("temp", ".object.json"))
        else:
            shutil.copy2(item, new_path / item.name)
    try:
        objecttree.refresh(root, store, [made["id"]])
    except Exception:
        log.exception("demo: the copy %s could not be indexed", new_rel)
    try:
        taskmeta.change(new_rel, lambda was: taskmeta.merge_parts(was, {"demo_copy": {"source": rel}}),
                        root=root, by="demo")
    except Exception:
        log.exception("demo: the copy %s could not be marked in its meta", new_rel)
    org_id, user_id = _whose(who)
    DemoApproval.objects.update_or_create(
        org_id=org_id, user_id=user_id, kind="copy", ref=new_rel,
        defaults={"source": rel, "fingerprint": "", "approved_at": time.time()})
    forget(who)
    return {"folder": new_rel, "number": new_number, "source": rel, "title": title}
