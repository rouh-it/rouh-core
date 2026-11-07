"""Owed to you: what somebody promised in a meeting by a date, said in the brief once the date passed.

Built by the nightly feature run, night 18, 21 October 2026 (task 94, idea I-112). Every recorded
meeting reaches Rouh from the meeting library with its action items, each with who owns it and
when it is due ("Send a written discounting policy document ... (Ivan Varbanov (outside), due
2026-10-16)", the pricing meeting of 8 October 2026, `rouh/synapse/sources/meetings.py`). What
the other side owes ‹owner› then sat in the library: nothing said when its day passed, and the
task that waited on it said "waits for ... due by 16 October" for days after. The library shows
the item; nobody tells ‹him› it is late, and chasing it is one more email to write by hand.

So, while its switch is on, the morning brief has a section **Owed to you**, read afresh every
time the page opens, with no model:

- **Which.** Action items of ‹his› own meetings in ‹his› Master (`synapse.item`, kind `meeting`,
  from the library) over the last `LOOK_BACK_DAYS`, owned by somebody who took part or was
  invited and is not ‹him› (their address is none of ‹his› own, `meeting_prep.own_addresses`),
  with a due date that has passed on ‹his› clock, and not marked done by the library.
- **Each line.** Who, what they said they would do, the day it was due and how late it is, and
  the meeting it was said in, linked to its notes. **What was this about** (version 2, mutation
  request 4, 27 October 2026: "I need a toggle to expand this and I can see context. What was the
  conversation about, with who and what exactly was said promised and to which party"), closed
  at first and read only when opened (`context`): when the meeting was, who took part, whom it
  was promised to, the meeting's summary and the turns of its transcript where it was said.
  **Draft a follow-up** (the same request: "We don't need to draft follow ups unless I decide it
  is something I want to ask for") writes one only when pressed (`draft`), by plain rules from the
  item itself and editable, with **Send**, which emails it from Rouh's own inbox to that person,
  as Rouh writing for ‹him›; **It came**, which puts the line away, with Undo;
  and **Dismiss** (fr_c80e0bd69613, 25 October 2026), which puts it away too, with Undo, for a
  line ‹he› means to ignore: nothing is said to have come and nothing is sent.
  A line chased stays, saying when, until it is marked as come or dismissed.

**Whose.** ‹His› own Master and ‹his› own settings (`user_settings`, `owed_to_you`), by
`org_id` and `user_id`. Nothing goes to anybody until ‹he› presses Send.

**Its switch** is `owed_to_you` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta

log = logging.getLogger("rouh.owed_to_you")

SWITCH = "owed_to_you"
#: How far back meetings are read, in days.
LOOK_BACK_DAYS = 60
#: The person's own setting: {line key: {"state": "came"|"dismissed"|"chased", "at": seconds}}.
KEPT = "owed_to_you"
#: The most lines in the section, and the longest follow-up sent.
MOST = 12
MOST_TEXT = 4000
#: What takes a line off the list: It came, or Dismiss, which only means it is to be ignored.
PUT_AWAY = ("came", "dismissed")

_ITEM = re.compile(r"^- (?P<what>.+) \((?P<extra>[^()]*(?:\([^()]*\)[^()]*)*)\)\s*$")
_DUE = re.compile(r"\bdue (\d{4}-\d{2}-\d{2})\b")
_PERSON = re.compile(r"^\s*(?P<name>[^<;]+?)\s*(?:<(?P<email>[^>]+)>)?\s*(?P<outside>\(outside\))?\s*$")
#: One speaker's turn in a transcript passage: "[12:34] Ivan Varbanov: what was said".
_TURN = re.compile(r"^\[(?P<at>[\d:?]+)\] (?P<who>[^:]+): (?P<said>.*)$")
_WORD = re.compile(r"[^\W\d_]{4,}", re.UNICODE)
#: Words too common to say where in a meeting a promise was made.
_COMMON = frozenset("""about after also back been before being both could does done each even from
going have here into just know like make more much need next only other over really right said
same send should some such that them then there these they thing think this those through time
very want well were what when where which will with would your their our it's that's""".split())
#: The most turns of the transcript shown under What was this about.
MOST_TURNS = 3


class Refused(ValueError):
    """What cannot be done, in the words the page shows."""


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _key(meeting_id: str, what: str) -> str:
    return "o-" + hashlib.sha256(f"{meeting_id}\n{what}".encode()).hexdigest()[:16]


def _attendees(body: str) -> list[dict]:
    """Everybody the meeting names, in its order: [{name, email, outside, took_part}]."""
    out: list[dict] = []
    for line in body.splitlines():
        head, _, rest = line.partition(":")
        if head.strip() not in ("Took part", "Invited, did not take part"):
            continue
        for one in rest.split(";"):
            found = _PERSON.match(one)
            if found:
                out.append({"name": " ".join(found.group("name").split()),
                            "email": (found.group("email") or "").strip().lower(),
                            "outside": bool(found.group("outside")), "took_part": head.strip() == "Took part"})
    return out


def _people(body: str) -> dict[str, str]:
    """Everybody the meeting names, by name in lower case, to their address."""
    return {p["name"].lower(): p["email"] for p in _attendees(body) if p["email"]}


def _summary(body: str) -> str:
    """The meeting's summary, as the library wrote it."""
    out, inside = [], False
    for line in (body or "").splitlines():
        if line.strip() == "Summary:":
            inside = True
            continue
        if inside:
            if not line.strip() or line.startswith(("Next meeting:", "Decisions:", "Action items:")):
                break
            out.append(line.strip())
    return " ".join(out)


def parse(body: str) -> list[dict]:
    """The action items of one meeting's notes: [{what, owner, due, outside, status}]."""
    out, inside = [], False
    for line in (body or "").splitlines():
        if line.strip() == "Action items:":
            inside = True
            continue
        if not inside:
            continue
        if not line.startswith("- "):
            if line.strip():
                inside = False
            continue
        found = _ITEM.match(line.strip())
        if not found:
            continue
        extra = found.group("extra")
        due = _DUE.search(extra)
        if not due:
            continue
        before, _, after = extra.partition(due.group(0))
        owner = before.strip().rstrip(",").strip()
        outside = owner.endswith("(outside)")
        owner = owner[: -len("(outside)")].strip() if outside else owner
        status = after.strip().lstrip(",").strip().lower()
        out.append({"what": found.group("what").strip(), "owner": owner, "due": due.group(1),
                    "outside": outside, "status": status})
    return out


def _meetings(who, only: str = "") -> list[dict]:
    from .synapse import db

    if not db.ready():
        return []
    from .synapse import master
    from .synapse.sources import meetings as library

    ds = master.of(str(who.org_id), str(who.user_id))
    if ds is None:
        return []
    rows = db.rows(
        "SELECT id, title, body, said_at, meta FROM synapse.item WHERE dataset_id = %s "
        "AND kind = 'meeting' AND source = %s AND deleted_at IS NULL AND said_at > %s "
        + ("AND id = %s " if only else "") + "ORDER BY said_at DESC LIMIT 200",
        (ds["id"], library.SOURCE, datetime.now().astimezone() - timedelta(days=LOOK_BACK_DAYS))
        + ((only,) if only else ()))
    out = []
    for r in rows:
        meta = r.get("meta") or {}
        if isinstance(meta, str):
            with contextlib.suppress(ValueError):
                meta = json.loads(meta)
        meeting = (meta or {}).get("meeting") if isinstance(meta, dict) else {}
        meeting = meeting if isinstance(meeting, dict) else {}
        said = r.get("said_at")
        out.append({"id": str(r["id"]), "dataset": str(ds["id"]), "title": str(r.get("title") or "the meeting"),
                    "body": str(r.get("body") or ""), "page": str(meeting.get("page") or ""),
                    "at": said.timestamp() if hasattr(said, "timestamp") else 0.0})
    return out


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


def _first(name: str) -> str:
    word = (name or "").split()
    return word[0] if word and "@" not in word[0] else ""


def follow_up(item: dict, who=None) -> str:
    """The follow-up for one line, by plain rules: words only, sent only on Send."""
    from . import clock, owner

    first = _first(item["who"])
    hello = f"Hello {first}," if first else "Hello,"
    met = clock.moment(item["met_at"]) if item.get("met_at") else None
    when = f" on {met.day} {met:%B}" if met else ""
    due = date.fromisoformat(item["due"])
    what = item["what"][0].lower() + item["what"][1:] if item["what"] else "it"
    text = (f"{hello}\n\nFollowing up on our meeting \u201c{item['meeting']}\u201d{when}: you "
            f"were going to {what} by {due.day} {due:%B}. Could you let us know where it stands, "
            f"or send it over when it is ready?\n\nThank you,\nRouh, ‹owner_full›'s assistant")
    return owner.say(text, who)


def lines(who, *, today: date | None = None) -> list[dict]:
    """Everything owed to the person past its date, the latest first, with what was done about it."""
    from . import clock, meeting_prep

    own = {a.lower() for a in meeting_prep.own_addresses(who)}
    today = today or clock.now().date()
    held = kept(who)
    out = []
    for m in _meetings(who):
        people = _people(m["body"])
        for one in parse(m["body"]):
            if one["status"] in ("done", "completed", "closed", "cancelled", "canceled"):
                continue
            email = people.get(one["owner"].lower(), "")
            if not email or email in own:
                continue
            try:
                due = date.fromisoformat(one["due"])
            except ValueError:
                continue
            if due >= today:
                continue
            key = _key(m["id"], one["what"])
            mark = held.get(key) or {}
            if mark.get("state") in PUT_AWAY:
                continue
            item = {"key": key, "meeting_id": m["id"], "who": one["owner"], "email": email, "what": one["what"],
                    "due": one["due"], "late": (today - due).days, "meeting": m["title"],
                    "met_at": m["at"], "page": m["page"], "outside": one["outside"],
                    "chased": float(mark.get("at") or 0) if mark.get("state") == "chased" else 0.0}
            out.append(item)
    out.sort(key=lambda i: (i["due"], i["who"]))
    return out[:MOST]


def _line(who, key: str) -> dict | None:
    if not on(who):
        raise Refused("Owed to you is switched off.")
    return next((one for one in lines(who) if one["key"] == key), None)


def draft(who, key: str) -> str:
    """Draft a follow-up, pressed: written only now, by plain rules, for the page to show and edit."""
    item = _line(who, key)
    if item is None:
        raise Refused("That is not on the list any more. Open the brief again.")
    from . import evolution

    evolution.used(SWITCH, "drafted", who=who, detail=f"drafted a follow-up to {item['who']}")
    return follow_up(item, who)


def _words(text: str) -> set[str]:
    return {w for w in (x.lower() for x in _WORD.findall(text or "")) if w not in _COMMON}


def _said(ds_id: str, item_id: str, what: str, owner: str) -> list[dict]:
    """The turns of the meeting's transcript where the promise was made: the turn that shares most
    words with the action item (the owner's own turns first when they tie), with the turn before and
    after it. Nothing when no turn shares two words with it."""
    from .synapse import db
    from .synapse.sources import meetings as library

    rows = db.rows("SELECT seq, text FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND part = %s "
                   "ORDER BY seq", (ds_id, item_id, library.PART))
    turns = []
    for r in rows:
        for line in str(r.get("text") or "").splitlines():
            found = _TURN.match(line.strip())
            if found:
                turns.append({"at": found.group("at"), "who": found.group("who").strip(),
                              "said": found.group("said").strip()})
            elif turns and line.strip():
                turns[-1]["said"] += " " + line.strip()
    want, name = _words(what), owner.lower()
    best, score = -1, (1, 1)
    for i, t in enumerate(turns):
        mine = (len(want & _words(t["said"])), 1 if name and t["who"].lower() == name else 0)
        if mine > score:
            best, score = i, mine
    if best < 0:
        return []
    return turns[max(0, best - 1): best - 1 + MOST_TURNS] if best else turns[:MOST_TURNS - 1]


def context(who, key: str) -> dict:
    """What was this about, opened: the meeting, who was in it, whom it was promised to, its summary
    and what was said, read from ‹his› own Master only now."""
    item = _line(who, key)
    if item is None:
        raise Refused("That is not on the list any more. Open the brief again.")
    from . import evolution, meeting_prep

    found = _meetings(who, item["meeting_id"])
    if not found:
        raise Refused("That meeting is not in your meeting library any more.")
    m = found[0]
    own = {a.lower() for a in meeting_prep.own_addresses(who)}
    people = []
    for p in _attendees(m["body"]):
        people.append({"name": "You" if p["email"] in own else p["name"], "outside": p["outside"],
                       "took_part": p["took_part"], "owner": p["name"].lower() == item["who"].lower(),
                       "you": p["email"] in own})
    owner = next((p for p in people if p["owner"]), None)
    there = [p for p in people if p["took_part"] and not p["owner"]]
    if owner is not None and owner["outside"]:
        to = [p for p in there if not p["outside"]]
    else:
        to = [p for p in there if p["outside"]] or [p for p in there if p["you"]]
    to.sort(key=lambda p: not p["you"])
    mine = {p["name"].lower() for p in _attendees(m["body"]) if p["email"] in own}
    said = [{**t, "who": "You" if t["who"].lower() in mine else t["who"]}
            for t in _said(m["dataset"], m["id"], item["what"], item["who"])]
    evolution.used(SWITCH, "context", who=who, detail=f"read what {item['who']} promised in {m['title']}")
    return {"meeting": m["title"], "met_at": m["at"], "page": m["page"], "people": people,
            "to": [p["name"] for p in to], "summary": _summary(m["body"]),
            "said": said}


async def again(who, brief: dict) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("owed", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        found = await sync_to_async(lines)(who)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("what is owed to the person could not be read")
        return
    if found:
        from . import evolution

        brief["owed"] = {"ok": True, "items": found, "source": "Meeting library"}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                            detail=f"{len(found)} owed past their date")


def mark(who, key: str, state: str) -> None:
    """It came, Dismiss, or Undo (state ""): kept in the person's own setting."""
    held = kept(who)
    was = held.get(key) or {}
    chased = float(was.get("at") or 0) if was.get("state") == "chased" else float(was.get("chased") or 0)
    if state in PUT_AWAY:
        held[key] = {"state": state, "at": time.time(), "chased": chased}
    elif state:
        held[key] = {"state": state, "at": time.time()}
    elif chased:
        held[key] = {"state": "chased", "at": chased}
    else:
        held.pop(key, None)
    _keep(who, held)
    if state == "came":
        from . import evolution

        evolution.used(SWITCH, "came", who=who, detail="marked as come")
    elif state == "dismissed":
        from . import evolution

        evolution.used(SWITCH, "dismissed", who=who, detail="dismissed, to be ignored")


async def chase(who, google, key: str, text: str) -> dict:
    """Send the follow-up from Rouh's own inbox to the person who owes it, and mark it chased."""
    from asgiref.sync import sync_to_async

    text = str(text or "").strip()
    if not text:
        raise Refused("There is nothing in the follow-up to send.")
    if len(text) > MOST_TEXT:
        raise Refused("That follow-up is too long to send.")
    item = await sync_to_async(_line)(who, key)
    if item is None:
        raise Refused("That is not on the list any more. Open the brief again.")
    if google is None:
        raise Refused("Google is not set up here, so nothing can be sent.")
    subject = "Following up: " + (item["what"] if len(item["what"]) <= 80
                                  else item["what"][:79].rstrip() + "…")
    try:
        wrote = await google(who).gmail.send(item["email"], subject, text)
    except Exception as exc:  # noqa: BLE001 - said on the page, and nothing is marked
        log.info("a follow-up from the brief was not sent: %r", exc)
        said = re.sub(r"\s+", " ", str(exc)).strip()[:220]
        raise Refused("It did not go" + (f": {said}" if said else ".")) from exc
    await sync_to_async(mark)(who, key, "chased")
    from . import evolution, runtime

    audit = getattr(runtime, "google_audit", None)
    if audit is not None:
        audit.wrote("send_mail", wrote.get("to") or item["email"],
                    f"Sent to {wrote.get('to') or item['email']} - subject {subject!r} - a "
                    f"follow-up on an action item owed from {item['meeting']} - pressed on the brief",
                    user_id=who.user_id, org_id=who.org_id)
    await sync_to_async(evolution.used)(SWITCH, "chased", who=who, detail=f"chased {item['who']}")
    return {"to": wrote.get("to") or item["email"], "at": time.time()}


__all__ = ["KEPT", "Refused", "SWITCH", "again", "chase", "context", "draft", "follow_up", "lines",
           "mark", "on", "parse"]
