"""Shared with you: a Google document somebody shared with ‹him›, in the morning brief, with its task.

Built by the nightly feature run, night 23, 26 October 2026 (task 94, idea I-140). ‹His› work's
documents come to ‹him› as Google's "Document shared with you" emails: five in the six weeks to
26 October 2026 in ‹his› own work inbox, three from the writer of ‹his› company's site. Each one
belongs to a task, and nothing put it there. On 22 October 2026 ‹he› pasted the newest into a chat
("there is a new document I think") so a job could find it; the task's notes then held its Drive id
but no link to it, so the task's Documents section (`rouh/task_docs.py`) never listed it, and
What changed, On the page? and Ask AI's guests could not read it from there. And a document
shared with ‹him› alone is one Rouh's own Google account cannot open, which a job finds out only
when it tries ("Company - Draft, which Google still refuses to Rouh until Tom shares it").

So, while its switch is on, the morning brief has a section **Shared with you**, read as the page
opens, with no model: every Google Doc, Sheet or Slides deck shared with ‹him› in ‹his› own
inboxes (the read-only mailboxes, `rouh/inboxes.py`) in the last `DAYS` days that no task's notes
link or name yet. Each line says who shared it and when, whether Rouh's own Google account can
open it, and the task it belongs to: the task whose notes name the person who shared it most,
by their address first and their name second (none is offered when no task names them, rather
than a guess). **Add to task NN** keeps its link in that task's notes (`task_docs.add_link`), so
the task's Documents section and everything reading the task has it, with Undo; **Open** opens the
document; **Got it** puts it away. Another task can be picked when the person who shared it is
named in more than one.

**Whose.** ‹His› own inboxes, read only, by `org_id` and `user_id` (`inboxes.theirs`); ‹his›
workspace's task notes; what ‹he› put away is ‹his› own setting (`user_settings`,
`shared_with_you`). Rouh's own Google account is only asked whether it can open the document.
The one thing written is the line in the task's notes ‹he› pressed Add for.

**Its switch** is `shared_with_you` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("rouh.shared_with_you")

SWITCH = "shared_with_you"
#: How far back shares are read, in days, and the most read and shown.
DAYS = 14
MOST = 20
SHOWN = 8
#: The person's own setting: {document id: {"act": "seen"|"added", "task", "line"}}.
KEPT = "shared_with_you"
#: Google's own sender of "Document shared with you".
SENDER = "drive-shares-dm-noreply@google.com"
#: How long what was read is kept before it is read again, in seconds.
FRESH = 300

_SUBJECT = re.compile(r"[\"“](.+?)[\"”]\s*$")
_VIA = re.compile(r"^\s*\"?(.+?)\s*\((?:via|по|чрез)[^)]*\)\"?\s*<", re.I)

_messages: dict[str, dict] = {}
_index: dict[str, tuple[float, list[dict]]] = {}
_found: dict[str, tuple[float, list[dict]]] = {}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


# --- What the person put away ----------------------------------------------------------------

def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


# --- One share email, read ---------------------------------------------------------------------

def _address(text: str) -> tuple[str, str]:
    """(name, address) from a header such as 'Tom Berger <tom@example.test>'."""
    from email.utils import parseaddr

    name, address = parseaddr(str(text or ""))
    return name.strip().strip('"'), address.strip().lower()


def read_share(message: dict) -> dict | None:
    """{id, kind, url, title, who, email, note, at} from one share email, or None if it is not one."""
    from . import task_docs

    if SENDER not in str(message.get("from") or "").lower():
        return None
    words = f"{message.get('body') or ''}\n{message.get('html') or ''}"
    link = task_docs.link_of(words)
    if link is None:
        return None
    name, address = _address(message.get("reply_to") or "")
    if not name:
        via = _VIA.match(str(message.get("from") or ""))
        name = via.group(1).strip() if via else ""
    got = _SUBJECT.search(str(message.get("subject") or ""))
    title = got.group(1).strip() if got else ""
    return {**link, "title": title, "who": name or address, "email": address,
            "at": float(message.get("at") or 0) or time.time(), "message": message.get("id") or ""}


async def shares(who) -> list[dict]:
    """The documents shared with the person in their own inboxes in the last `DAYS` days, newest first."""
    from asgiref.sync import sync_to_async

    from . import inboxes

    held = _found.get(str(who.user_id))
    if held and time.time() - held[0] < FRESH:
        return held[1]
    out: dict[str, dict] = {}
    for one in await sync_to_async(inboxes.theirs)(who):
        if one.needs_reconnect:
            continue
        try:
            opened = await sync_to_async(inboxes.open_one)(who, one)
            listed = await opened.gmail.recent(MOST, f"from:{SENDER} newer_than:{DAYS}d")
        except Exception as exc:  # noqa: BLE001 - one inbox that cannot be read leaves the rest
            log.info("the shares in %s could not be read: %r", one.said(), exc)
            continue
        for row in listed:
            mid = row.get("id") or ""
            if not mid:
                continue
            if mid not in _messages:
                try:
                    _messages[mid] = await opened.gmail.message(mid)
                except Exception as exc:  # noqa: BLE001
                    log.info("the share email %s could not be read: %r", mid, exc)
                    continue
            share = read_share(_messages[mid])
            if share and share["id"] not in out:
                out[share["id"]] = {**share, "inbox": one.email}
    found = sorted(out.values(), key=lambda s: s["at"], reverse=True)
    _found[str(who.user_id)] = (time.time(), found)
    return found


# --- Which task it belongs to ------------------------------------------------------------------

def _tasks(root) -> list[dict]:
    """Every task in the workspace with the words of its notes, kept for `FRESH` seconds."""
    from . import steps
    from .task_docs import MOST_BYTES

    key = str(root)
    held = _index.get(key)
    if held and time.time() - held[0] < FRESH:
        return held[1]
    base = Path(root)
    out: list[dict] = []

    def walk(folder: Path, depth: int) -> None:
        try:
            kids = sorted(p for p in folder.iterdir() if p.is_dir())
        except OSError:
            return
        for kid in kids:
            if kid.name.startswith(".") or kid.name in ("node_modules", "temp", "source-code"):
                continue
            if steps._TASK_NAME.match(kid.name) and (kid / "AGENTS.md").is_file():
                words = []
                for path in kid.rglob("*.md"):
                    parts = path.relative_to(kid).parts
                    if any(p.startswith(".") or p in ("temp", "node_modules") for p in parts):
                        continue
                    try:
                        if path.stat().st_size <= MOST_BYTES:
                            words.append(path.read_text(encoding="utf-8", errors="replace"))
                    except OSError:
                        continue
                    if len(words) >= 300:
                        break
                head = (kid / "AGENTS.md").read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
                title = re.sub(r"^#\s*\d+[.)]?\s*", "", head).strip() or kid.name.split(".", 1)[-1]
                out.append({"rel": str(kid.relative_to(base)), "number": kid.name.split(".", 1)[0],
                            "title": title, "low": "\n".join(words).lower()})
            elif depth < 4:
                walk(kid, depth + 1)

    walk(base, 0)
    _index[key] = (time.time(), out)
    return out


def tasks_for(tasks: list[dict], share: dict) -> list[dict]:
    """The tasks whose notes name the person who shared it, the likeliest first; at most three."""
    email = (share.get("email") or "").lower()
    name = " ".join(str(share.get("who") or "").split())
    scored = []
    for t in tasks:
        low = t["low"]
        score = 0
        if email and "@" in email:
            score += 3 * low.count(email)
        if name and " " in name:
            score += low.count(name.lower())
        if score:
            scored.append((score, t))
    scored.sort(key=lambda s: -s[0])
    return [{"rel": t["rel"], "number": t["number"], "title": t["title"]} for _, t in scored[:3]]


def linked_anywhere(tasks: list[dict], doc_id: str) -> bool:
    want = doc_id.lower()
    return any(want in t["low"] for t in tasks)


# --- The section -------------------------------------------------------------------------------

def _day(at: float) -> str:
    from datetime import datetime

    from . import clock

    here = datetime.fromtimestamp(at, clock.zone())
    return f"{here:%A} {here.day} {here:%B}"


async def found(who, root, google=None) -> dict | None:
    """{items, count} for the brief, or None when nothing new was shared with the person."""
    import asyncio

    from asgiref.sync import sync_to_async

    got = await shares(who)
    if not got:
        return None
    put_away = await sync_to_async(kept)(who)
    fresh = [s for s in got if s["id"] not in put_away]
    if not fresh:
        return None
    tasks = await asyncio.to_thread(_tasks, root)
    fresh = [s for s in fresh if not linked_anywhere(tasks, s["id"])]
    if not fresh:
        return None

    async def readable(doc_id: str) -> bool | None:
        if google is None:
            return None
        try:
            await google(who).drive.metadata(doc_id)
            return True
        except Exception as exc:  # noqa: BLE001 - a document it cannot open is said so
            log.info("Rouh's account cannot open %s: %r", doc_id, exc)
            return False

    shown = fresh[:SHOWN]
    opens = await asyncio.gather(*(readable(s["id"]) for s in shown))
    items = []
    for share, can in zip(shown, opens):
        items.append({"key": share["id"], "title": share["title"] or share["kind"], "kind": share["kind"],
                      "url": share["url"], "who": share["who"], "email": share["email"],
                      "day": _day(share["at"]), "at": share["at"], "rouh_can_open": can,
                      "tasks": tasks_for(tasks, share)})
    return {"items": items, "count": len(fresh)}


async def again(who, brief: dict, root, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("shared_with_you", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, root, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the documents shared with the person could not be read")
        return
    if got:
        from . import evolution

        brief["shared_with_you"] = {"ok": True, "source": "Your inboxes", **got}
        await sync_to_async(evolution.used)(
            SWITCH, "shown", who=who, detail=f"{got['count']} documents shared with you")


class Refused(ValueError):
    """What cannot be done with a share, in a sentence."""


async def act(who, root, key: str, what: str, task: str = "") -> dict:
    """Add to a task, Open, Got it, or Undo either."""
    from asgiref.sync import sync_to_async

    from . import evolution, task_docs

    held = await sync_to_async(kept)(who)
    if what == "open":
        await sync_to_async(evolution.used)(SWITCH, "opened", who=who,
                                            detail="opened a document shared with you from the brief")
        return {"ok": True}
    if what == "seen":
        held[key] = {"act": "seen", "at": time.time()}
        await sync_to_async(_keep)(who, held)
        await sync_to_async(evolution.used)(SWITCH, "seen", who=who,
                                            detail="put away a document shared with you")
        return {"ok": True}
    if what == "undo":
        was = held.pop(key, None) or {}
        if was.get("act") == "added" and was.get("task"):
            await sync_to_async(task_docs.take_link)(root, was["task"], was.get("line") or "")
        await sync_to_async(_keep)(who, held)
        _index.clear()
        return {"ok": True}
    if what != "add":
        raise Refused("Add, Open, Got it or Undo.")
    share = next((s for s in await shares(who) if s["id"] == key), None)
    if share is None:
        raise Refused("That document is not one shared with you in the last two weeks.")
    tasks = await sync_to_async(_tasks)(root)
    rel = next((t["rel"] for t in tasks if t["rel"] == task), "")
    if not rel:
        raise Refused("That is not one of your tasks.")
    note = f"shared with you by {share['who']}" + (f" ({share['email']})" if share["email"] else "") \
        + f" on {_day(share['at'])}"
    try:
        done = await sync_to_async(task_docs.add_link)(root, rel, share, share["title"], note)
    except ValueError as exc:
        raise Refused(str(exc)) from exc
    held[key] = {"act": "added", "task": rel, "line": done["line"], "at": time.time()}
    await sync_to_async(_keep)(who, held)
    _index.clear()
    await sync_to_async(evolution.used)(SWITCH, "added", who=who,
                                        detail=f"added a document shared with you to {rel.rsplit('/', 1)[-1]}")
    return {"ok": True, "added": done["added"]}


__all__ = ["KEPT", "SWITCH", "Refused", "act", "again", "found", "on", "read_share", "shares",
           "tasks_for"]
