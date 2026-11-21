"""Handholding, at /handholding: the guided way into Rouh for someone who has never seen it.

Petar, 20 November 2026: "I want to be able to put a person that has never seen rouh and step by
step the guide should lead him to using the absolute maximum of rouh." It is a section of the
navigation of its own (`rouh/static/handholdingpage.js`).

**One source: a lesson is a step** (Petar, the same day, reviewing the first version: "for each
action there is a step ... this way we won't have two sources that go to one place"). A path of eight
stages, each a list of lessons; every lesson has one id, one entry in the data file, a card form, and a
full page at `/handholding/lesson/<id>` that ends with the next lesson on the path.

- **The words** are a data file, `rouh/handholding.json`, so they are edited and translated without
  touching code: every stage and lesson, its pictures (`rouh/static/handholding/`), the things you can
  say and the page to open.
- **What is done** is kept per person, in `user_settings` under `NAME`: `{lesson id: when}`, and an
  optional lesson the person said is not for them as minus when, which counts as done. Both ids are in
  every query (AGENTS.md, "Whose data is it"). Ticks kept under an id the data file has since renamed
  (`renamed`, the first version's step ids) are read under the new one, and written back that way the
  next time the person ticks anything, so nobody loses progress.
- **What Rouh can see for itself** is ticked by itself and marked Detected (`detected`): a
  connection that is live, a first task, a rule of the person's own, a reminder. Each is a small
  read of the database, never a call to a service, and one that cannot be read is simply not
  detected.
- **A connection's badge** says what `connection_status` says of it (and, for the few it does not
  cover, whether the setting exists): Connected, Needs attention with its words, or Not connected.
  One that could not be read says Status unknown, never a false Not connected.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger("rouh.handholding")

#: Where each person's ticks are kept, in `user_settings`.
NAME = "handholding_done"
#: The data file: every word on the page.
FILE = os.path.join(os.path.dirname(__file__), "handholding.json")

_HELD: dict = {}


def content() -> dict:
    """The data file, read again whenever it changes on disk."""
    try:
        at = os.path.getmtime(FILE)
    except OSError:
        return {}
    held = _HELD.get("content")
    if held and held[0] == at:
        return held[1]
    with open(FILE, encoding="utf-8") as fh:
        got = json.load(fh)
    _HELD["content"] = (at, got)
    return got


#: Where the section's pages live: `/handholding/<page>`, and one lesson at `/handholding/lesson/<id>`.
ROOT = "/handholding"
#: The word in a lesson's address, which no page may be called.
LESSON = "lesson"


def pages() -> list[dict]:
    """The section's sub-pages, in the order the navigation lists them (`pages` in the data file):
    each an id, a name, a glyph and the views it draws."""
    return [p for p in content().get("pages", []) if isinstance(p, dict) and p.get("id") and p.get("name")
            and p["id"] != LESSON]


def page_route(page: str) -> str:
    return f"{ROOT}/{page}"


def lesson_route(lesson: str) -> str:
    return f"{ROOT}/{LESSON}/{lesson}"


def lessons(data: dict | None = None) -> list[dict]:
    """Every lesson, in the order of the path."""
    data = data if data is not None else content()
    return [les for stage in data.get("stages", []) for les in stage.get("lessons", []) if les.get("id")]


def step_ids(data: dict | None = None) -> set[str]:
    """Every lesson's id: a lesson is a step, and its id is what a tick is kept under."""
    return {les["id"] for les in lessons(data)}


def renamed() -> dict:
    """{old id: the lesson's id now}, for ticks and addresses from before a lesson was renamed."""
    got = content().get("renamed") or {}
    return got if isinstance(got, dict) else {}


def page_now(page: str) -> str:
    """A sub-page by its id, or by the id it had before (`old_pages`); '' for none."""
    ids = {p["id"] for p in pages()}
    if page in ids:
        return page
    moved = (content().get("old_pages") or {}).get(page, "")
    return moved if moved in ids else ""


def lesson_now(lesson: str, old_library: bool = False) -> str:
    """A lesson by its id, or by an id it had before: a step's (`renamed`), or with `old_library`
    a lesson of the first version's separate library (`old_lessons`); '' for none."""
    ids = step_ids()
    if lesson in ids:
        return lesson
    if old_library:
        got = (content().get("old_lessons") or {}).get(lesson, "")
        if got in ids:
            return got
    got = renamed().get(lesson, "")
    return got if got in ids else ""


def _migrated(held: dict) -> dict:
    """The ticks under today's ids: a renamed one moves to its new id. Where two old ids became one
    lesson, a tick wins over a Not for me, and the earlier tick is kept."""
    moves = renamed()
    out: dict = {}
    for k, v in held.items():
        if not isinstance(v, (int, float)):
            continue
        k = moves.get(k, k)
        was = out.get(k)
        if was is None or (v > 0 and (was < 0 or v < was)):
            out[k] = v
    return out


# --- what the person ticked --------------------------------------------------------------------


def progress(who) -> dict:
    """{lesson id: when it was ticked}, for the lessons the data file has, old ids read as new ones."""
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id or ""), name=NAME)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    if not isinstance(held, dict):
        return {}
    known = step_ids()
    return {k: v for k, v in _migrated(held).items() if k in known}


def optional_ids() -> set[str]:
    return {les["id"] for les in lessons() if les.get("optional")}


def mark(who, step: str, done: bool, skip: bool = False) -> dict:
    """Tick a step, or take the tick off; with `skip`, an optional step is not for this person (kept
    as minus when). ValueError for a step the page does not have, or a skip of one that is not optional."""
    from django.db import transaction

    from .models import UserSetting

    step = lesson_now(step)
    if not step:
        raise ValueError("There is no such lesson.")
    if skip and step not in optional_ids():
        raise ValueError("Only an optional lesson can be left out.")
    with transaction.atomic():
        row = (UserSetting.objects.select_for_update()
               .filter(user_id=str(who.user_id), org_id=str(who.org_id or ""), name=NAME).first())
        try:
            held = json.loads(row.value) if row and row.value else {}
        except (TypeError, ValueError):
            held = {}
        if not isinstance(held, dict):
            held = {}
        held = _migrated(held)
        if done and skip:
            held[step] = -time.time()
        elif done:
            held[step] = held.get(step) if (held.get(step) or 0) > 0 else time.time()
        else:
            held.pop(step, None)
        UserSetting.objects.bulk_create(
            [UserSetting(user_id=str(who.user_id), org_id=str(who.org_id or ""), name=NAME,
                         value=json.dumps(held), updated_at=time.time())],
            update_conflicts=True, unique_fields=["user_id", "name"],
            update_fields=["org_id", "value", "updated_at"])
    return progress(who)


# --- what Rouh can see for itself --------------------------------------------------------------


def _said(spoken: bool) -> bool:
    # Chats belong to the one owner of a Rouh, so the person's own words in any chat count.
    from .models import TranscriptMessage

    return TranscriptMessage.objects.filter(role="user", note=False, spoken=spoken).exists()


def _owner_rule(who) -> bool:
    from . import rules

    ds = rules.master(who.user_id, who.org_id)
    if not ds:
        return False
    return any(rules.origin_kind(r.get("origin")) in ("manual", "chat") for r in rules.rules(ds))


def _vocabulary(who) -> bool:
    from . import rules, vocabulary

    ds = rules.master(who.user_id, who.org_id)
    return bool(ds) and bool(vocabulary.entries(ds))


def _checks(who) -> dict:
    """What each detector looks at: a few cheap reads, each on its own."""
    from .models import (Artifact, Box, Decision, Reminder, Run, Task, Thought, TrustedContact)

    me = {"user_id": str(who.user_id), "org_id": str(who.org_id or "")}
    return {
        "said_typed": (lambda: _said(False), "Rouh saw you type to it."),
        "said_voice": (lambda: _said(True), "Rouh heard you speak to it."),
        "artifact": (lambda: Artifact.objects.filter(kind="card").exists(), "Rouh has put something on your canvas."),
        "reminder": (lambda: Reminder.objects.filter(**me, kind__in=("remind", "do")).exists(),
                     "You have a reminder in Clockwork."),
        "repeat": (lambda: Reminder.objects.filter(**me, kind__in=("remind", "do"))
                   .exclude(repeat="once").exists(), "Something of yours is on repeat in Clockwork."),
        "task": (lambda: Task.objects.filter(number__isnull=False).exists(), "You have a task."),
        "pinned": (lambda: Task.objects.filter(pinned=True).exists(), "You have pinned a task."),
        "goal": (lambda: Task.objects.filter(meta__tags__contains=["goal"]).exists(), "You have a goal."),
        "run": (lambda: Run.objects.exists(), "Rouh has run work in the background for you."),
        "decision": (lambda: Decision.objects.filter(**me, status__in=("answered", "applied")).exists(),
                     "You have answered a decision."),
        "thought": (lambda: Thought.objects.filter(**me).exists(), "You have kept a thought."),
        "box": (lambda: Box.objects.filter(**me).exists(), "You have a box."),
        "trusted": (lambda: TrustedContact.objects.filter(**me, trusted=True).exists(),
                    "You have a trusted contact."),
        "rule": (lambda: _owner_rule(who), "You have given Rouh a rule of your own."),
        "vocabulary": (lambda: _vocabulary(who), "Rouh knows one of your words."),
    }


def status(who) -> dict:
    """Each connection the page has a card for: {key: {kind, words, said}}; kind is live, attention,
    off or unknown. Never a credential."""
    from . import connection_status

    out: dict = {}
    found = connection_status.connections(who)
    broken = {c["connection"] for c in found if c.get("state") == "could not be read"}

    def one(key, rows):
        if not rows:
            out[key] = {"kind": "off", "words": "Not connected"}
            return
        bad = [r for r in rows if not _live(r)]
        if bad:
            r = bad[0]
            out[key] = {"kind": "attention", "words": "Needs attention",
                        "said": _sentence(r.get("name") or key, r.get("state"))}
        else:
            out[key] = {"kind": "live", "words": "Connected"}

    readers = {"google": "google", "apple_contacts": "apple", "slack": "slack", "hue": "hue",
               "dreame": "dreame", "telegram": "telegram", "cloudflare": "cloudflare"}
    for key, reader in readers.items():
        if reader in broken:
            out[key] = {"kind": "unknown", "words": "Status unknown"}
            continue
        rows = [c for c in found if c.get("connection") == key or c.get("connection", "").startswith(key + ":")]
        if key == "telegram" and not rows and _key_set("ROUH_TELEGRAM_BOT_TOKEN"):
            out[key] = {"kind": "live", "words": "Connected"}
            continue
        one(key, rows)
    for key, read in (("mcp", _mcp), ("payments", _payments), ("meetings", _meetings)):
        try:
            out[key] = read(who)
        except Exception:  # noqa: BLE001 - one connection never hides the others
            log.exception("handholding: %s could not be read", key)
            out[key] = {"kind": "unknown", "words": "Status unknown"}
    return out


def _live(row: dict) -> bool:
    state = str(row.get("state") or "").lower()
    return state in ("connected", "listening", "on", "ready") or (state.startswith("connected") and "not" not in state)


def _sentence(name: str, state) -> str:
    state = str(state or "").strip()
    return f"{name}: {state}." if state else f"{name} needs attention."


def _key_set(name: str) -> bool:
    from . import service_keys

    try:
        return bool(service_keys.value(name))
    except Exception:  # noqa: BLE001
        return False


def _mcp(who) -> dict:
    from .models import McpServer

    rows = list(McpServer.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id or ""), enabled=True)
                .values("name", "last_error"))
    if not rows:
        return {"kind": "off", "words": "Not connected"}
    bad = [r for r in rows if r["last_error"]]
    if bad:
        return {"kind": "attention", "words": "Needs attention",
                "said": f"The MCP server {bad[0]['name']} is failing."}
    return {"kind": "live", "words": "Connected"}


def _payments(who) -> dict:
    from .models import PaymentCard, PaymentSettings

    me = {"user_id": str(who.user_id), "org_id": str(who.org_id or "")}
    card = PaymentCard.objects.filter(**me).exists()
    stripe = PaymentSettings.objects.filter(**me).exclude(stripe_sealed="").exists()
    if card or stripe:
        return {"kind": "live", "words": "Set up"}
    return {"kind": "off", "words": "Not connected"}


def _meetings(who) -> dict:
    if _key_set("MEETING_LIBRARY_KEY") and _key_set("MEETING_LIBRARY_URL"):
        return {"kind": "live", "words": "Set up"}
    return {"kind": "off", "words": "Not connected"}


def detected(who, connections: dict | None = None) -> dict:
    """{lesson id: why Rouh ticked it}, for every lesson the data file says Rouh can see."""
    checks = _checks(who)
    out: dict = {}
    seen: dict = {}
    for st in lessons():
        what = st.get("detect") or ""
        if not what:
            continue
        if what.startswith("connection:"):
            key = what.split(":", 1)[1]
            s = (connections or {}).get(key) or {}
            if s.get("kind") == "live":
                out[st["id"]] = "Rouh sees it connected."
            continue
        if what not in checks:
            continue
        if what not in seen:
            read, why = checks[what]
            try:
                seen[what] = why if read() else ""
            except Exception:  # noqa: BLE001 - a lesson that cannot be read is simply not detected
                log.exception("handholding: %s could not be read", what)
                seen[what] = ""
        if seen[what]:
            out[st["id"]] = seen[what]
    # And the lessons done by asking Rouh in a chat, while that gene is on (`rouh/lesson_ticks.py`).
    try:
        from . import lesson_ticks

        known = {st["id"] for st in lessons()}
        for lesson, why in lesson_ticks.done(who).items():
            if lesson in known and lesson not in out:
                out[lesson] = why
    except Exception:  # noqa: BLE001 - those lessons wait for a tick by hand, as before
        log.exception("handholding: the lessons done in a chat could not be read")
    return out


def page(who) -> dict:
    """Everything the page draws: the words, what is ticked, what Rouh saw, and the badges."""
    try:
        conns = status(who)
    except Exception:  # noqa: BLE001 - the page draws "Status unknown"
        log.exception("handholding: the connections could not be read")
        conns = None
    seen = detected(who, conns)
    try:
        from . import lesson_ticks

        lesson_ticks.seen(who, seen)
    except Exception:  # noqa: BLE001 - a use not counted never stops the page
        log.exception("handholding: the use of lesson_ticks could not be counted")
    return {"content": content(), "progress": progress(who), "detected": seen, "status": conns}
