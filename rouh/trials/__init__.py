"""Trials: a made-up person tries a change the way a real one would, before it ships.

Petar, 4 November 2026: "Rouh is bad at human usability. What it builds tends to be complicated
and confusing, and its explanations are hard to read." So every change a person will see goes
through one more stage of gene therapy after its Playwright proof: a fresh tester who knows nothing
about Rouh's code, plans or words is handed a persona and a goal, and tries to reach it through a
real browser, at a phone's size, thinking out loud. Playwright says the change works; a trial says a
person can use it. Their reports are kept apart, and a gene passes both.

**The tester** is the model on the Smart tier (the use `trial_tester`, `rouh/modeldefaults.py`),
asked one step at a time through the LLM service. Its whole context is its tester's profile (a row,
`TrialTester`, the person's own, written in the second person; the first two come from `personas/`), a short brief of what Rouh is to them (`BRIEF`), the goal in the
persona's own words, and how to test (`GUIDANCE`). It sees what a person sees and nothing else: the
screen as a picture, the words on it, and a number beside each thing that can be pressed or typed
in, with the words on that thing (`bin/rouh-trial`, which drives the browser). It never sees code,
the page's hidden labels, or an API.

**Where it runs.** The browser is driven where the app being tried is running: a run's own test
world (`./e2e.sh serve`) in its checkout. Each step is sent here (`/internal/trials`), where the
screenshot is kept, the tester is asked what it does next, and the step is written down. So the
person's database holds every trial, whichever run made it, and the model is the one the Models page
names.

**Problems accumulate.** Every confusing or bad moment becomes a problem on one list, with the
persona's own words, the screenshot, how bad it was (blocked, confused, annoyed, minor), the trial
and gene it came from, and when. The same problem seen again (the same screen and the same issue,
judged by the Smart model against the open problems, `trial_matcher`) raises its count and keeps the
new sighting instead of being added twice. The owner's own confusions go on the same list, from
`owner`: a term they ask the meaning of, or saying something in Rouh is confusing (`owner_said`).
A problem is closed only by a later trial that passes and visits its screen without tripping on it,
never by hand, and closed problems stay on the list with when and by which trial; one closed too soon
can be opened again (`reopen`).

**Jobs and discussions** (Petar, 4 November 2026, after "Terrible first version of trials"): every try
belongs to a job, what is being tested, and the list shows jobs; who tried each shows only once one is
opened. Every problem has what should have happened, what did and a suggested fix, and a thread where the
owner writes and Rouh answers (`say`, the use `trial_discuss`), from which it is set aside (not a problem,
won't fix), decided ("fix it like this", which the next round's builder reads), or sent as feedback to
Gene therapy (`set_verdict`). A problem set aside no longer fails a try.

**Pass** is the persona managing the goal with no blocked or confused problem. A failed trial is
fixed by the builder and tried again by a new tester (round 2, then 3); after round 3 the change
ships anyway, its problems stay open, and the owner is told in one line (`_told_shipped`).

Every row carries `org_id` and `user_id`, and every query names both.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from pathlib import Path

log = logging.getLogger("rouh.trials")

#: The model uses on the Models page (`rouh/modeldefaults.py`).
USE = "trial_tester"
MATCH_USE = "trial_matcher"
#: Writing a whole tester from a sentence, and Rouh's side of a problem's discussion.
WRITE_USE = "trial_writer"
TALK_USE = "trial_discuss"

#: Where the personas are: one Markdown file each, in the second person, with a short header.
PERSONAS = Path(__file__).resolve().parent / "personas"
#: Who tries a change unless another persona is asked for by name, and the setting that changes it.
DEFAULT_PERSONA = "vesela"
DEFAULT_SETTING = "trials_persona"
#: The switch that pauses every tester at once (Petar, 5 November 2026), a setting of the person's.
PAUSE_SETTING = "trials_paused"
#: What a run's report and test results say when a try was not started because its tester was paused.
SKIPPED = "skipped: tester paused"

#: How bad a problem is, worst first, as the page says it.
HOW_BAD = ("blocked", "confused", "annoyed", "minor")
HOW_BAD_NAMES = {"blocked": "Stopped the tester", "confused": "Confused the tester", "annoyed": "Annoyed the tester",
                 "minor": "Small"}
#: Which of them fail a trial.
FAILS = ("blocked", "confused")
#: A try's two modes (Petar, 4 November 2026). auto: a test while a feature is built; its builder fixes
#: what tripped the tester, within what was already approved, and tries again, at most two rounds, then it
#: ships, with nobody asked. review: one the owner asked for in their own words ("Have Vesela test this");
#: a report of the walk-through, results and suggestions to read and discuss, and nothing is fixed or
#: shipped from it until the owner chooses what and how. Naming a tester alone never makes a review: the
#: request to have someone test it does.
MODES = ("auto", "review")
MODE_NAMES = {"auto": "Automatic test while building", "review": "Review you asked for"}
#: A trial's states.
STATES = ("queued", "running", "passed", "failed", "broken")
#: The most steps one trial takes before the tester is asked to stop, and the most rounds there are.
MOST_STEPS = 30
ROUNDS = 3

#: What Rouh is to the persona: the same for every one of them.
BRIEF = ("You've had Rouh, a personal assistant on your phone and computer, for two weeks. A friend set "
         "it up for you. You talk or type to it and it does things for you.")

GUIDANCE = """\
## How to do this

- Think out loud as yourself. At every step, say what you see and what you think, in your own words, in English, the way you would say it to a friend sitting next to you.
- Say when you are unsure. Never guess what a word means: if you do not know a word, say that you do not know it.
- Behave like yourself, with your own patience, attention and skills. Read as much as you would really read. If you would give up at this point, give up.
- You can only look at the screen and use it, the way a person does: tap something, type into a box, scroll, or go back. You cannot see anything that is not on the screen.
- When you come to a screen for the first time, or it changes a lot, answer three questions in your own words: What is this? What do I do here? What happens when I do it? If you cannot answer one clearly, say so.
- Every time something stops you, confuses you, annoys you, or is a small bother, say it as a problem, in your own words.

## What you are shown

Each time, you are shown a picture of your screen. Every thing on it that can be tapped or typed into has a small yellow number beside it, so you can say which one you mean. The yellow numbers are not part of the app: ignore them when you judge how it looks. Under the picture you are given the words on the screen, and the list of numbered things with the words written on each one.

## How to answer

Answer with one JSON object and nothing else:

{
  "see": "what you see, in a sentence or two",
  "think": "what you think about it, out loud, as yourself",
  "new_screen": true or false,
  "answers": {"what": "What is this?", "how": "What do I do here?", "then": "What happens when I do it?", "clear": [true or false, true or false, true or false]} or null when the screen is not new,
  "problems": [{"what": "the problem in one short line about the app, not about you, such as: The round button has no words", "said": "your own words about it", "expected": "what you expected to happen or to see, in a sentence", "happened": "what happened or what you saw instead, in a sentence", "how_bad": "blocked, confused, annoyed or minor"}],
  "doing": "what you do now, in your words, such as: I tap Run trial.",
  "do": {"action": "tap, type, scroll_down, scroll_up, back, wait, done or give_up", "number": the yellow number for tap and type, "text": "what you type", "enter": true to press Enter after typing}
}

"blocked" means you cannot go on. "confused" means you do not understand something you need. "annoyed" means you understand but it bothers you. "minor" is a small thing.
Use "done" when you have done what you wanted, and "give_up" when you would stop trying. With either one, add:
"ending": {"managed": "yes, partly or no", "nearly_gave_up": "where you nearly gave up, or an empty string", "how_it_went": "two or three sentences, in your words"}
"""

ENDING_NOW = ("You have been trying for a long time now, and you stop here. Answer with one JSON object and "
              "nothing else: {\"ending\": {\"managed\": \"yes, partly or no\", \"nearly_gave_up\": \"...\", "
              "\"how_it_went\": \"two or three sentences, in your words\"}, \"problems\": [any problem you "
              "have not said yet, as before]}")

MATCH = """You keep a list of usability problems people had with an app. You are given the open problems already on the list, each with its number, its screen and what it is, and new problems just found, each with its index, its screen and what it is.

For each new problem, say whether it is the same problem as one already on the list: the same screen (or the same thing on every screen) and the same issue, even in other words. If two new problems are the same issue as each other, say so too. A different issue on the same screen is not the same problem.

For each new problem that is not the same as one on the list, also suggest how to fix it: one or two plain sentences saying what to change on the screen so the person would not trip, such as: Put the word Save on the button, and say what it saves. Leave "fix" empty for one that is the same as another.

Answer with JSON alone: {"matches": [{"new": 0, "same_as": 12 or null, "same_as_new": an earlier new index or null, "fix": "how to fix it, or an empty string"}]}"""


class Refused(ValueError):
    """What the person or a run asked cannot be done, in a sentence to say."""


class NotFound(Refused):
    pass


class Paused(Refused):
    """The tester (or everyone) is paused, so no try was started. Not a failure: a build that meets it
    skips its trial, says `SKIPPED` in its report, and carries on."""

    def __init__(self, message: str, *, tester: str = "", everyone: bool = False):
        super().__init__(message)
        self.tester, self.everyone = tester, everyone


# --- testers -------------------------------------------------------------------------------------
#
# Petar, 4 November 2026: "I need to be able to see and manage the people testing the software. I want
# to be able to add more people and remove them. I want to see their full profile and everything written
# on them." So a tester is a row (`TrialTester`), the person's own: Vesela and Boris are written from the
# two files in `personas/` the first time a person's Trials are read, and from then on they are rows
# like any other, edited, added and removed (archived, so an old try still says who did it).


class _Whose:
    """Who a row belongs to, for the functions that are handed a row rather than a person."""

    def __init__(self, org_id, user_id):
        self.org_id, self.user_id = str(org_id), str(user_id)


#: The sections a tester's profile has, in order, as headings in the second person: what Rouh writes
#: for a new one, and what the add form starts with.
SECTIONS = ("Home", "Your work", "Your family", "Money", "Education and languages", "Your devices and apps",
            "How good you are with technology", "How you read", "Your patience and temperament",
            "What annoys you", "What makes you trust or distrust software",
            "How you react to jargon, errors and long text", "Bad experiences with apps",
            "What you want from a personal assistant", "Habits and quirks")

THEM = {"her": ("she", "her"), "him": ("he", "his"), "them": ("they", "their")}


def _header(text: str) -> tuple[dict, str]:
    """A persona file's header (name, short, device, age, job, city, them) and the rest of it."""
    head: dict = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    head[k.strip()] = v.strip()
            body = text[end + 4:].lstrip("\n")
    return head, body


def _key_for(name: str) -> str:
    first = re.sub(r"[^a-z0-9]+", "", str(name or "").strip().split(" ")[0].lower()) if str(name or "").strip() else ""
    return first or "tester"


def ensure_testers(who) -> None:
    """The two testers every Rouh starts with, written from their files once, the first time this person's
    testers are read. Never again: a person who removed them both keeps them removed."""
    M = _m()
    if M.TrialTester.objects.filter(**_whose(who)).exists():
        return
    now = _now()
    from django.db import IntegrityError

    for path in sorted(PERSONAS.glob("*.md")):
        head, body = _header(path.read_text(encoding="utf-8"))
        try:
            age = int(head.get("age") or 0) or None
        except ValueError:
            age = None
        try:
            M.TrialTester.objects.create(
                **_whose(who), key=path.stem, name=head.get("name") or path.stem.title(), age=age,
                job=head.get("job", ""), city=head.get("city", ""), short=head.get("short", ""),
                device=head.get("device", "phone"), them=head.get("them", "them"), profile=body.strip(),
                made_by="seed", created_at=now, updated_at=now)
        except IntegrityError:
            continue


def _tester_rows(who, *, archived: bool = False):
    ensure_testers(who)
    q = _m().TrialTester.objects.filter(**_whose(who))
    return q if archived else q.filter(archived_at__isnull=True)


def tester_brief(row) -> dict:
    """A tester as a list shows them, and as the old persona dicts were: {id, name, first, short, ...}."""
    return {"id": row.key, "key": row.key, "name": row.name, "first": row.name.split()[0] if row.name else row.key,
            "short": row.short, "device": row.device, "them": row.them, "age": row.age, "job": row.job,
            "city": row.city, "archived": row.archived_at is not None, "made_by": row.made_by,
            "paused": row.paused_at is not None, "paused_at": row.paused_at, "skipped": row.skipped or 0,
            "skipped_at": row.skipped_at}


def personas(who) -> list[dict]:
    """Every tester who has not been removed, oldest first."""
    return [tester_brief(r) for r in _tester_rows(who).order_by("created_at", "id")]


def _tester(who, pid: str, *, archived: bool = True):
    pid = str(pid or "").strip().lower()
    rows = list(_tester_rows(who, archived=True).order_by("archived_at", "created_at"))
    for r in rows:
        if r.archived_at is not None and not archived:
            continue
        if r.key == pid or r.name.lower() == pid or (r.name.split() or [""])[0].lower() == pid:
            return r
    live = [r for r in rows if r.archived_at is None]
    raise NotFound(f"There is no tester called {pid or 'that'}: there are "
                   + (", ".join(r.name.split()[0] for r in live) or "none") + ".")


def persona(who, pid: str) -> dict:
    return tester_brief(_tester(who, pid, archived=False))


def persona_text(who, pid: str) -> str:
    return _tester(who, pid).profile.strip()


def default_persona(who) -> str:
    """The tester every trial uses unless another is asked for by name: the person's setting, or Vesela,
    or the first tester there is."""
    from rouh.models import UserSetting

    got = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id or ""), name=DEFAULT_SETTING)
           .values_list("value", flat=True).first())
    ids = [p["id"] for p in personas(who)]
    return got if got in ids else DEFAULT_PERSONA if DEFAULT_PERSONA in ids else (ids[0] if ids else DEFAULT_PERSONA)


def set_default_persona(who, pid: str) -> str:
    from rouh.models import UserSetting

    p = persona(who, pid)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=str(who.org_id or ""), name=DEFAULT_SETTING,
                     value=p["id"], updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])
    return p["id"]


def _tester_counts(who) -> dict:
    """For each tester: how many tries they did, how many are going now, and how many problems they found."""
    M = _m()
    tries: dict = {}
    running: dict = {}
    for key, state in M.Trial.objects.filter(**_whose(who)).values_list("persona", "state"):
        tries[key] = tries.get(key, 0) + 1
        if state in ("queued", "running"):
            running[key] = running.get(key, 0) + 1
    found: dict = {}
    for key, pid in M.TrialSighting.objects.filter(**_whose(who), source="persona").values_list("persona", "problem_id"):
        found.setdefault(key, set()).add(pid)
    return {"tries": tries, "running": running, "found": {k: len(v) for k, v in found.items()}}


def testers(who, *, archived: bool = False) -> list[dict]:
    """The testers for the Testers page: the default first, then oldest first, each with their counts."""
    default = default_persona(who)
    counts = _tester_counts(who)
    rows = sorted(_tester_rows(who, archived=archived), key=lambda r: (r.archived_at is not None, r.key != default,
                                                                       r.created_at))
    return [{**tester_brief(r), "default": r.key == default, "tries": counts["tries"].get(r.key, 0),
             "running": counts["running"].get(r.key, 0), "problems": counts["found"].get(r.key, 0)} for r in rows]


# --- pausing ------------------------------------------------------------------------------------
#
# Petar, 5 November 2026: "Can you please pause vesela and Boris testing. ideally give me a pause button I
# can toggle on/off". A paused tester, or every tester while the switch that pauses everyone is on, starts
# no new try of any kind: not the automatic ones a build or a nightly run starts, not a review asked for by
# name. A try already going may finish. Pausing changes nothing else: they stay on the list and stay the
# one who tries every change, so resuming puts everything back exactly as it was. A build that meets a
# pause skips its trial quietly (`Paused`, `SKIPPED`): it is never a failure, and never worked round.


def paused_all(who) -> float | None:
    """When every tester was paused at once, or None while that switch is off."""
    from rouh.models import UserSetting

    got = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id or ""), name=PAUSE_SETTING)
           .values_list("value", "updated_at").first())
    if not got:
        return None
    try:
        on = bool(json.loads(got[0] or "false"))
    except ValueError:
        on = False
    return got[1] if on else None


def pause_state(who) -> dict:
    """The switch for everyone, and who is paused on their own."""
    since = paused_all(who)
    return {"all": since is not None, "all_since": since,
            "testers": {r.key: r.paused_at for r in _tester_rows(who) if r.paused_at is not None}}


def set_paused(who, pid: str = "", on: bool = True) -> dict:
    """Pause or resume one tester (`pid`), or with no tester, the switch that pauses everyone. At once, and
    nothing else about them changes."""
    if not str(pid or "").strip():
        from rouh.models import UserSetting

        UserSetting.objects.bulk_create(
            [UserSetting(user_id=str(who.user_id), org_id=str(who.org_id or ""), name=PAUSE_SETTING,
                         value=json.dumps(bool(on)), updated_at=time.time())],
            update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])
        return {"everyone": True, "paused": bool(on), **pause_state(who)}
    r = _tester(who, pid, archived=False)
    if on and r.paused_at is None:
        r.paused_at = _now()
    elif not on:
        r.paused_at = None
    r.updated_at = _now()
    r.save(update_fields=["paused_at", "updated_at"])
    return {"everyone": False, **tester_brief(r), "paused_all": paused_all(who) is not None}


def is_paused(who, pid: str) -> tuple[bool, bool]:
    """(paused, because everyone is) for the tester with this key."""
    if paused_all(who) is not None:
        return True, True
    r = _m().TrialTester.objects.filter(**_whose(who), key=pid).only("paused_at").first()
    return (r is not None and r.paused_at is not None), False


def _refuse_if_paused(who, pid: str) -> None:
    """Raise `Paused` when this tester may not start a try now, and count the skip on them."""
    paused, everyone = is_paused(who, pid)
    if not paused:
        return
    M = _m()
    from django.db.models import F

    now = _now()
    M.TrialTester.objects.filter(**_whose(who), key=pid).update(skipped=F("skipped") + 1, skipped_at=now)
    row = M.TrialTester.objects.filter(**_whose(who), key=pid).first()
    first = (row.name.split() or [pid])[0] if row else pid
    if everyone:
        said = (f"All testing is paused, so {first} did not start a try. Nothing failed: the trial was skipped. "
                "Resume it on Evolution, Trials, Testers.")
    else:
        said = (f"{first} is paused, so no try was started. Nothing failed: the trial was skipped. "
                f"Resume {first} on Evolution, Trials, Testers.")
    raise Paused(said, tester=pid, everyone=everyone)


def profile_sections(row) -> list[dict]:
    """A profile cut at its headings, each heading said of the tester rather than to them, for the page."""
    _, body = _header(row.profile or "")
    she, her = THEM.get(row.them, THEM["them"])
    first = (row.name.split() or [row.key])[0]
    out, title, lines = [], "", []

    def heading(h: str) -> str:
        h = re.sub(r"^You are\b.*$", "Who " + she + " is", h.strip())
        h = re.sub(r"^Your\b", first + "'s", h)
        h = re.sub(r"\byou are\b", f"{she} is" if she != "they" else "they are", h)
        h = re.sub(r"\byou react\b", f"{she} reacts" if she != "they" else "they react", h)
        h = re.sub(r"\byou read\b", f"{she} reads" if she != "they" else "they read", h)
        h = re.sub(r"\bannoys you\b", f"annoys {her if her != 'his' else 'him'}" if she != "they" else "annoys them", h)
        h = re.sub(r"\byou want\b", f"{she} wants" if she != "they" else "they want", h)
        h = re.sub(r"\bmakes you\b", f"makes {'him' if she == 'he' else 'her' if she == 'she' else 'them'}", h)
        h = re.sub(r"\byour\b", her, h)
        h = re.sub(r"\byou\b", she, h)
        return h[:1].upper() + h[1:]

    def flush():
        text = "\n".join(lines).strip()
        if title or text:
            out.append({"title": heading(title) if title else "Who " + she + " is", "text": text})

    for line in body.splitlines():
        m = re.match(r"^#{1,3}\s+(.*)$", line)
        if m:
            flush()
            title, lines = m.group(1), []
        else:
            lines.append(line)
    flush()
    return [s for s in out if s["text"]]


def tester_read(who, pid: str) -> dict:
    """One tester whole: everything written about them, in sections, with their tries."""
    r = _tester(who, pid)
    counts = _tester_counts(who)
    tries = [trial_dict(t) for t in _m().Trial.objects.filter(**_whose(who), persona=r.key).order_by("-created_at")[:100]]
    return {**tester_brief(r), "default": r.key == default_persona(who), "profile": r.profile,
            "running": counts["running"].get(r.key, 0), "paused_all": paused_all(who) is not None,
            "sections": profile_sections(r), "tries": tries, "tries_count": counts["tries"].get(r.key, 0),
            "problems": counts["found"].get(r.key, 0), "created_at": r.created_at, "updated_at": r.updated_at,
            "text": r.profile}


def persona_read(who, pid: str) -> dict:
    return tester_read(who, pid)


def _clean_tester(fields: dict) -> dict:
    name = _cut(fields.get("name"), 80)
    if not name:
        raise Refused("A tester needs a name.")
    try:
        age = int(str(fields.get("age") or "").strip() or 0) or None
    except ValueError:
        raise Refused("Their age is a number, such as 41.") from None
    if age is not None and not 12 <= age <= 100:
        raise Refused("Their age is between 12 and 100.")
    them = str(fields.get("them") or "them").strip().lower()
    device = str(fields.get("device") or "phone").strip().lower()
    profile = str(fields.get("profile") or "").strip()[:30000]
    if len(profile) < 80:
        raise Refused("Write more about them: a tester is only as real as what is written about them.")
    return {"name": name, "age": age, "job": _cut(fields.get("job"), 160), "city": _cut(fields.get("city"), 80),
            "short": _cut(fields.get("short"), 200), "them": them if them in THEM else "them",
            "device": device if device in ("phone", "desk") else "phone", "profile": profile}


def add_tester(who, fields: dict, *, made_by: str = "owner") -> dict:
    """A new tester, from the add form or a tool. Their key is their first name, made unique."""
    clean = _clean_tester(fields)
    M = _m()
    taken = set(M.TrialTester.objects.filter(**_whose(who)).values_list("key", flat=True))
    ensure_testers(who)
    taken |= set(M.TrialTester.objects.filter(**_whose(who)).values_list("key", flat=True))
    base = _key_for(clean["name"])
    key, n = base, 2
    # Words the pages' addresses use after /testers are never a tester's key.
    taken |= {"new", "draft", "edit"}
    while key in taken:
        key, n = f"{base}{n}", n + 1
    now = _now()
    M.TrialTester.objects.create(**_whose(who), key=key, made_by=made_by if made_by in ("owner", "rouh") else "owner",
                                 created_at=now, updated_at=now, **clean)
    return tester_read(who, key)


def edit_tester(who, pid: str, fields: dict) -> dict:
    r = _tester(who, pid, archived=False)
    clean = _clean_tester({**tester_brief(r), "profile": r.profile, **{k: v for k, v in fields.items() if v is not None}})
    for k, v in clean.items():
        setattr(r, k, v)
    r.updated_at = _now()
    r.save()
    return tester_read(who, r.key)


def remove_tester(who, pid: str) -> dict:
    """A tester taken off the list: archived, so their old tries still say who did them. Never the one who
    tries every change: another is made that first."""
    r = _tester(who, pid, archived=False)
    if r.key == default_persona(who):
        raise Refused(f"{r.name.split()[0]} tries every change. Make someone else the one who does first.")
    r.archived_at = _now()
    r.save(update_fields=["archived_at"])
    return tester_brief(r)


DRAFT = """You write the profile of a made-up person who will test an app called Rouh, a personal assistant on the phone and computer. The person is played by a model, so the profile is written TO them, in the second person ("You are ...", "You live ..."), and it must be detailed and concrete enough that they behave like a real, particular person: their patience, how they read, which words they know and which they do not, what annoys them.

Write it in plain English. Make the person ordinary and believable, never a software developer unless asked. Keep any real person's name, address or company out of it: everyone in it is made up.

Answer with one JSON object and nothing else:
{"name": "first and last name", "age": a number, "job": "their job and where, in a few words", "city": "the city", "short": "one line on who they are, such as: 41, head of HR in Plovdiv, does almost everything on her iPhone", "them": "her, him or them", "device": "phone or desk", "profile": "the whole profile in Markdown"}

The profile starts with a heading "# You are <name>" and a paragraph of who they are, then has exactly these sections, each a "## " heading with several sentences or a short list under it, in this order:
""" + "\n".join("- " + s for s in SECTIONS)


async def draft_tester(who, sentence: str) -> dict:
    """A whole tester written by Rouh from one sentence, for the person to read and change before it is kept."""
    from rouh import llm

    sentence = _cut(sentence, 600)
    if len(sentence) < 8:
        raise Refused("Describe them in a sentence first, such as: a retired teacher in Varna who is wary of apps.")
    got = await llm.ask(WRITE_USE, system=DRAFT, messages=f"Write the profile of this person: {sentence}",
                        max_tokens=6000, who=who, read_only=True, timeout=240, subject="a new tester")
    data = _json_in(got.text) or {}
    if not data.get("profile") or not data.get("name"):
        raise Refused("Rouh's answer could not be turned into a profile this time. Press the button again in a "
                      "minute, or fill in the boxes below yourself. Nothing was saved.")
    out = {k: data.get(k) for k in ("name", "age", "job", "city", "short", "them", "device", "profile")}
    out["profile"] = str(out.get("profile") or "").strip()
    return out


def system_for(who, pid: str, goal: str) -> str:
    """The tester's whole context: their profile, the brief, the goal and how to test. Nothing else."""
    return "\n\n".join([persona_text(who, pid), "## Rouh\n\n" + BRIEF,
                        "## What you want to do now\n\n" + goal.strip(), GUIDANCE])


# --- small helpers -------------------------------------------------------------------------------


def _whose(who) -> dict:
    return {"org_id": str(who.org_id), "user_id": str(who.user_id)}


def _m():
    from rouh import models

    return models


def _now() -> float:
    return time.time()


def _cut(value, most: int) -> str:
    return " ".join(str(value or "").split())[:most]


def screen_name(title: str, key: str = "") -> str:
    """A screen as a person would name it: the browser tab's words without Rouh's own name after them."""
    name = re.sub(r"\s+[-–|]\s*Rouh\s*$", "", _cut(title, 200)).strip()
    return name if name and name != "Rouh" else ("Rouh's first screen" if key in ("", "/") else name or key)


def screen_key(url: str) -> str:
    """Which screen an address is, the same for every one of its kind: the path, with every number
    in it taken out (`/evolution/trials/12` is `/evolution/trials/#`), and no query."""
    path = re.sub(r"^[a-z]+://[^/]+", "", str(url or "").strip(), flags=re.I).split("?", 1)[0].split("#", 1)[0]
    path = re.sub(r"(?<=/)(?:[A-Z]{2,5}-)?\d+(?=/|$)", "#", path or "/")
    return path.rstrip("/") or "/"


def shots_dir(who, trial_id: int) -> Path:
    from rouh.config import config

    return Path(config.data_dir) / "trials" / re.sub(r"[^\w.-]", "_", str(who.org_id)) / str(int(trial_id))


def _json_in(text: str) -> dict | None:
    """The first whole JSON object in a model's words, fenced or not, with words around it or not."""
    text = str(text or "")
    decoder = json.JSONDecoder()
    best = None
    i = text.find("{")
    while i >= 0:
        try:
            got, _ = decoder.raw_decode(text, i)
        except ValueError:
            got = None
        if isinstance(got, dict):
            if "do" in got or "ending" in got or "matches" in got:
                return got
            best = best or got
        i = text.find("{", i + 1)
    return best


def _number_next(model, who) -> int:
    from django.db.models import Max

    return int(model.objects.filter(**_whose(who)).aggregate(n=Max("number"))["n"] or 0) + 1


# --- what is shown ------------------------------------------------------------------------------

#: What the owner made of a problem, as the page says it. "" is not looked at yet.
VERDICTS = {"": "Not looked at yet", "not_a_problem": "Not a problem", "wont_fix": "Won't fix",
            "decided": "Decided how to fix it", "sent": "Sent as feedback"}
#: The verdicts that set a problem aside: it no longer fails a trial, and it is not on the open list.
SET_ASIDE = ("not_a_problem", "wont_fix")
#: The page's filter of where a problem stands.
STANDINGS = ("open", "decided", "fixed", "set_aside", "all")


def standing(p) -> str:
    """Where one problem stands, in one word the page filters by: fixed (a passing trial got past it),
    set_aside (not a problem, or won't fix), decided (decided or sent as feedback) or open."""
    if p.status == "closed":
        return "fixed"
    if p.verdict in SET_ASIDE:
        return "set_aside"
    if p.verdict in ("decided", "sent"):
        return "decided"
    return "open"


def _names(who) -> dict:
    """Every tester's key and first name, the removed ones too, so an old try still says who did it."""
    return {r.key: (r.name.split() or [r.key])[0] for r in _tester_rows(who, archived=True)}


def trial_dict(t, *, steps: bool = False, names: dict | None = None) -> dict:
    who = _Whose(t.org_id, t.user_id)
    names = names if names is not None else _names(who)
    out = {"number": t.number, "persona": t.persona, "persona_name": names.get(t.persona) or t.persona.title(),
           "goal": t.goal, "subject": t.subject or t.page or "", "gene": t.gene, "page": t.page,
           "round": t.round, "first": None, "state": t.state, "passed": t.state == "passed",
           "managed": t.managed, "nearly_gave_up": t.nearly_gave_up, "ending": t.ending, "steps": t.steps,
           "seconds": round(t.seconds or 0), "problems": t.problems, "why": t.why, "by": t.by, "run_id": t.run_id,
           "model": t.model, "created_at": t.created_at, "started_at": t.started_at, "ended_at": t.ended_at,
           "job": None, "job_name": "", "mode": t.mode or "auto",
           "mode_name": MODE_NAMES.get(t.mode or "auto", t.mode)}
    if t.job_id:
        j = _m().TrialJob.objects.filter(id=t.job_id, org_id=t.org_id, user_id=t.user_id).first()
        if j is not None:
            out["job"], out["job_name"] = j.number, j.name
    # How many of the problems it found are still not fixed, so a try says it without opening it.
    ids = set(_m().TrialSighting.objects.filter(trial_id=t.id, org_id=t.org_id, user_id=t.user_id)
              .values_list("problem_id", flat=True))
    rows = list(_m().TrialProblem.objects.filter(id__in=ids, org_id=t.org_id, user_id=t.user_id)) if ids else []
    out["open"] = sum(1 for p in rows if standing(p) in ("open", "decided"))
    if t.first_id:
        out["first"] = _m().Trial.objects.filter(id=t.first_id, org_id=t.org_id, user_id=t.user_id).values_list(
            "number", flat=True).first()
    if steps:
        walk = _m().TrialStep.objects.filter(trial_id=t.id, org_id=t.org_id, user_id=t.user_id).order_by("n")
        out["walk"] = [{"n": s.n, "at": s.at, "url": s.url, "screen": s.screen, "title": screen_name(s.title, s.screen),
                        "shot": bool(s.shot), "see": s.see, "think": s.think, "does": s.does,
                        "answers": s.answers or None, "found": s.found or []} for s in walk]
        seen = list(_m().TrialSighting.objects.filter(trial_id=t.id, org_id=t.org_id, user_id=t.user_id).order_by("at"))
        probs = {p.id: p for p in rows}
        notes = _note_counts(who, list(probs))
        out["found"] = [{**problem_brief(probs[s.problem_id], notes=notes), "step": s.step, "quote": s.quote,
                         "how_bad": s.how_bad, "worst": probs[s.problem_id].how_bad}
                        for s in seen if s.problem_id in probs]
        out["found"].sort(key=lambda f: (HOW_BAD.index(f["how_bad"]) if f["how_bad"] in HOW_BAD else 9, f["step"] or 0))
        closed = _m().TrialProblem.objects.filter(closed_by=t.id, org_id=t.org_id, user_id=t.user_id)
        out["closed"] = [{"number": p.number, "what": p.what} for p in closed]
    return out


def listing(who, *, persona_id: str = "", since: float | None = None, limit: int = 200, job: int | None = None) -> list[dict]:
    q = _m().Trial.objects.filter(**_whose(who))
    if persona_id:
        q = q.filter(persona=_tester(who, persona_id).key)
    if since:
        q = q.filter(created_at__gte=since)
    if job:
        q = q.filter(job_id=_job(who, job).id)
    names = _names(who)
    return [trial_dict(t, names=names) for t in q.order_by("-created_at", "-number")[:limit]]


def _trial(who, number):
    try:
        n = int(str(number).strip().lstrip("#").split()[-1])
    except (TypeError, ValueError, IndexError):
        raise NotFound(f"There is no trial {number}.") from None
    t = _m().Trial.objects.filter(**_whose(who), number=n).first()
    if t is None:
        raise NotFound(f"There is no trial {n}.")
    return t


def one(who, number) -> dict:
    return trial_dict(_trial(who, number), steps=True)


def shot_path(who, number, step: int) -> Path | None:
    t = _trial(who, number)
    s = _m().TrialStep.objects.filter(trial_id=t.id, **_whose(who), n=int(step)).first()
    if s is None or not s.shot:
        return None
    path = shots_dir(who, t.id) / s.shot
    return path if path.is_file() else None


# --- jobs ----------------------------------------------------------------------------------------
#
# Petar: "I want a list of jobs. Each job will have multiple tries and has to say who did it, but only
# when I click on the job." A job is what is being tested; a try is one tester's go at it.


def _job(who, number):
    try:
        n = int(str(number).strip().lstrip("#").split()[-1])
    except (TypeError, ValueError, IndexError):
        raise NotFound(f"There is no job {number}.") from None
    j = _m().TrialJob.objects.filter(**_whose(who), number=n).first()
    if j is None:
        raise NotFound(f"There is no job {n}.")
    return j


def _job_problems(who, job_ids: list) -> dict:
    """For each job: the ids of the problems its tries found."""
    M = _m()
    trial_job = dict(M.Trial.objects.filter(**_whose(who), job_id__in=job_ids).values_list("id", "job_id"))
    out: dict = {}
    for tid, pid in M.TrialSighting.objects.filter(**_whose(who), trial_id__in=list(trial_job)).values_list(
            "trial_id", "problem_id"):
        out.setdefault(trial_job[tid], set()).add(pid)
    return out


def job_dict(j, *, tries: list | None = None, latest=None, count: int = 0, problems: list | None = None) -> dict:
    probs = problems or []
    out = {"number": j.number, "name": j.name, "goal": j.goal, "covers": j.covers, "page": j.page, "gene": j.gene,
           "created_at": j.created_at, "updated_at": j.updated_at, "tries_count": count,
           "open": sum(1 for p in probs if standing(p) in ("open", "decided")),
           "found": len(probs), "latest": None, "last_at": None}
    if latest is not None:
        out["latest"] = {"number": latest.number, "state": latest.state, "round": latest.round,
                         "managed": latest.managed, "mode": latest.mode or "auto"}
        out["last_at"] = latest.created_at
    if tries is not None:
        out["tries"] = tries
    return out


def jobs(who, *, tester: str = "", result: str = "") -> list[dict]:
    """Every job, the one tried most lately first, with its latest result, its tries and its open problems.
    Who tried each is not said here: only once a job is opened."""
    M = _m()
    rows = list(M.TrialJob.objects.filter(**_whose(who)))
    trials = list(M.Trial.objects.filter(**_whose(who), job_id__in=[j.id for j in rows]).order_by("created_at"))
    by_job: dict = {}
    for t in trials:
        by_job.setdefault(t.job_id, []).append(t)
    pids = _job_problems(who, [j.id for j in rows])
    probs = {p.id: p for p in M.TrialProblem.objects.filter(**_whose(who), id__in=set().union(*pids.values()) if pids else [])}
    key = _tester(who, tester).key if tester else ""
    out = []
    for j in rows:
        mine = by_job.get(j.id, [])
        if key and not any(t.persona == key for t in mine):
            continue
        latest = mine[-1] if mine else None
        if result and (latest.state if latest else "none") != result:
            continue
        out.append(job_dict(j, latest=latest, count=len(mine), problems=[probs[i] for i in pids.get(j.id, ()) if i in probs]))
    out.sort(key=lambda d: -(d["last_at"] or d["updated_at"] or 0))
    return out


def job(who, number) -> dict:
    """One job whole: its goal and what it covers, and its tries, newest first, each with who did it."""
    j = _job(who, number)
    M = _m()
    trials = list(M.Trial.objects.filter(**_whose(who), job_id=j.id).order_by("-created_at", "-number"))
    names = _names(who)
    pids = _job_problems(who, [j.id]).get(j.id, set())
    probs = list(M.TrialProblem.objects.filter(**_whose(who), id__in=pids))
    return job_dict(j, tries=[trial_dict(t, names=names) for t in trials], latest=trials[0] if trials else None,
                    count=len(trials), problems=probs)


def edit_job(who, number, *, name=None, goal=None, covers=None) -> dict:
    j = _job(who, number)
    if name is not None:
        if not _cut(name, 160):
            raise Refused("A job needs a name, such as: Sign up and sign in for the first time.")
        j.name = _cut(name, 160)
    if goal is not None:
        j.goal = _cut(goal, 400)
    if covers is not None:
        j.covers = str(covers or "").strip()[:2000]
    j.updated_at = _now()
    j.save()
    return job(who, number)


def _job_for(who, *, job_no=None, name: str = "", subject: str = "", goal: str = "", page: str = "", gene: str = "",
             first_id: int | None = None):
    """The job a new try belongs to: the one named, its first try's, one already called the same, or a new one."""
    M = _m()
    if job_no:
        return _job(who, job_no)
    if first_id:
        jid = M.Trial.objects.filter(id=first_id, **_whose(who)).values_list("job_id", flat=True).first()
        if jid:
            got = M.TrialJob.objects.filter(id=jid, **_whose(who)).first()
            if got is not None:
                return got
    title = _cut(name or subject or "", 160)
    if title:
        got = M.TrialJob.objects.filter(**_whose(who), name__iexact=title).first()
        if got is not None:
            return got
    if goal:
        got = M.TrialJob.objects.filter(**_whose(who), goal=goal).order_by("-updated_at").first()
        if got is not None:
            return got
    title = title or _cut(goal, 120) or (page or "A page of Rouh")
    from django.db import IntegrityError, transaction

    now = _now()
    for _ in range(5):
        try:
            with transaction.atomic():
                return M.TrialJob.objects.create(**_whose(who), number=_number_next(M.TrialJob, who),
                                                  name=title[:1].upper() + title[1:], goal=_cut(goal, 400),
                                                  page=_cut(page, 400), gene=_cut(gene, 80), created_at=now,
                                                  updated_at=now)
        except IntegrityError:
            continue
    raise Refused("The job could not be numbered just now; try again.")


def job_line(j: dict) -> str:
    latest = j.get("latest") or {}
    state = {"passed": "passed", "failed": "did not pass", "running": "running now", "queued": "waiting to start",
             "broken": "could not finish"}.get(latest.get("state"), "not tried yet")
    return (f"Job {j['number']}: {j['name']} - latest try {state}; {j['tries_count']} tries; {j['open']} problems "
            f"open. Goal: {j['goal'] or '-'}  Page: /evolution/trials/job/{j['number']}")


# --- problems ------------------------------------------------------------------------------------


def _note_counts(who, ids: list) -> dict:
    out: dict = {}
    if ids:
        for pid in _m().TrialNote.objects.filter(**_whose(who), problem_id__in=ids, kind="said").values_list(
                "problem_id", flat=True):
            out[pid] = out.get(pid, 0) + 1
    return out


def _reviewed_ids(who, ids) -> set:
    """Of these problems, the ones a review the owner asked for found: those wait on the owner's choice."""
    if not ids:
        return set()
    trials = set(_m().Trial.objects.filter(**_whose(who), mode="review").values_list("id", flat=True))
    if not trials:
        return set()
    return set(_m().TrialSighting.objects.filter(**_whose(who), problem_id__in=list(ids), trial_id__in=trials)
               .values_list("problem_id", flat=True))


def problem_brief(p, *, notes: dict | None = None, reviewed: set | None = None) -> dict:
    """A problem as every place that shows it shows it: where it stands, the owner's verdict, its discussion's size,
    and whether it waits on the owner's choice (found by a review they asked for, and not decided yet)."""
    if reviewed is None:
        reviewed = _reviewed_ids(_Whose(p.org_id, p.user_id), [p.id])
    return {"awaiting_choice": p.id in reviewed and p.status == "open" and not p.verdict,"number": p.number, "what": p.what, "how_bad": p.how_bad, "count": p.count, "status": p.status,
            "standing": standing(p), "verdict": p.verdict, "verdict_name": VERDICTS.get(p.verdict, p.verdict),
            "decision": p.decision, "expected": p.expected, "actual": p.actual, "fix": p.fix,
            "screen": p.screen, "screen_name": p.screen_name or p.screen or "", "source": p.source,
            "personas": p.personas or [], "notes": (notes or {}).get(p.id, 0), "feedback_id": p.feedback_id}


def problem_dict(p, *, sightings: bool = True, notes: bool = False, names: dict | None = None) -> dict:
    who = _Whose(p.org_id, p.user_id)
    out = {**problem_brief(p, notes=_note_counts(who, [p.id])), "gene": p.gene, "closed_at": p.closed_at,
           "closed_by": None, "closed_note": p.closed_note, "first_at": p.first_at, "last_at": p.last_at,
           "verdict_at": p.verdict_at}
    if p.closed_by:
        out["closed_by"] = _m().Trial.objects.filter(id=p.closed_by, org_id=p.org_id, user_id=p.user_id).values_list(
            "number", flat=True).first()
    if sightings:
        names = names if names is not None else _names(who)
        rows = list(_m().TrialSighting.objects.filter(problem_id=p.id, org_id=p.org_id, user_id=p.user_id)
                    .order_by("-at")[:40])
        trials = {t.id: t for t in _m().Trial.objects.filter(id__in={r.trial_id for r in rows if r.trial_id},
                                                              org_id=p.org_id, user_id=p.user_id)}
        jobs_of = {j.id: j for j in _m().TrialJob.objects.filter(id__in={t.job_id for t in trials.values() if t.job_id},
                                                                  org_id=p.org_id, user_id=p.user_id)}
        shots = {}
        for r in rows:
            if r.trial_id and r.step is not None:
                shots[(r.trial_id, r.step)] = _m().TrialStep.objects.filter(
                    trial_id=r.trial_id, n=r.step, org_id=p.org_id, user_id=p.user_id).exclude(shot="").exists()
        out["sightings"] = []
        for r in rows:
            t = trials.get(r.trial_id)
            j = jobs_of.get(t.job_id) if t is not None and t.job_id else None
            out["sightings"].append({
                "quote": r.quote, "how_bad": r.how_bad, "source": r.source, "persona": r.persona,
                "persona_name": names.get(r.persona) or r.persona.title(), "trial": t.number if t else None,
                "round": t.round if t else None, "mode": (t.mode or "auto") if t else "", "job": j.number if j else None,
                "job_name": j.name if j else "",
                "step": r.step, "shot": bool(shots.get((r.trial_id, r.step))), "chat": r.chat, "at": r.at})
        out["jobs"] = sorted({(s["job"], s["job_name"]) for s in out["sightings"] if s["job"]})
        out["jobs"] = [{"number": n, "name": name} for n, name in out["jobs"]]
    if notes:
        out["thread"] = [{"who": n.who, "kind": n.kind, "text": n.text, "at": n.at}
                         for n in _m().TrialNote.objects.filter(problem_id=p.id, org_id=p.org_id, user_id=p.user_id)
                         .order_by("at", "id")]
    return out


def _rank(p) -> tuple:
    order = {"open": 0, "decided": 1, "set_aside": 2, "fixed": 3}
    return (order.get(standing(p), 9), HOW_BAD.index(p.how_bad) if p.how_bad in HOW_BAD else 9, -p.count, -p.last_at)


def problems(who, *, status: str = "", source: str = "", persona_id: str = "", screen: str = "",
             since: float | None = None, job: int | None = None, trial: int | None = None) -> list[dict]:
    """The list: open first, then decided, set aside and fixed; within each the worst and the most seen first.
    `status` is where they stand (open, decided, fixed, set_aside, all; closed is fixed)."""
    status = "fixed" if status == "closed" else status
    q = _m().TrialProblem.objects.filter(**_whose(who))
    if source in ("persona", "owner"):
        q = q.filter(source=source)
    if screen:
        q = q.filter(screen=screen)
    if job or trial:
        ids = (_m().Trial.objects.filter(**_whose(who), job_id=_job(who, job).id).values_list("id", flat=True)
               if job else [_trial(who, trial).id])
        q = q.filter(id__in=_m().TrialSighting.objects.filter(**_whose(who), trial_id__in=list(ids))
                     .values_list("problem_id", flat=True))
    rows = list(q)
    if status in ("open", "decided", "fixed", "set_aside"):
        rows = [p for p in rows if standing(p) == status]
    elif status == "awaiting":
        # Found by a review the owner asked for and not decided yet: waiting on their choice.
        waiting = _reviewed_ids(who, [p.id for p in rows])
        rows = [p for p in rows if p.id in waiting and p.status == "open" and not p.verdict]
    if persona_id:
        pid = _tester(who, persona_id).key
        rows = [p for p in rows if pid in (p.personas or [])]
    if since:
        rows = [p for p in rows if p.last_at >= since]
    rows.sort(key=_rank)
    names = _names(who)
    return [problem_dict(p, names=names) for p in rows]


def _problem(who, number):
    try:
        n = int(str(number).strip().lstrip("#").split()[-1])
    except (TypeError, ValueError, IndexError):
        raise NotFound(f"There is no problem {number}.") from None
    p = _m().TrialProblem.objects.filter(**_whose(who), number=n).first()
    if p is None:
        raise NotFound(f"There is no problem {n}.")
    return p


def problem(who, number) -> dict:
    return problem_dict(_problem(who, number), notes=True)


def _new_problem(who, *, what: str, screen: str, screen_name: str, how_bad: str, source: str, personas: list,
                 gene: str = "", now: float | None = None, expected: str = "", actual: str = "", fix: str = ""):
    from django.db import IntegrityError, transaction

    M = _m()
    now = now or _now()
    for _ in range(5):
        try:
            with transaction.atomic():
                return M.TrialProblem.objects.create(
                    **_whose(who), number=_number_next(M.TrialProblem, who), screen=screen, screen_name=screen_name,
                    what=what, how_bad=how_bad, source=source, personas=personas, gene=gene, count=1,
                    first_at=now, last_at=now, expected=_cut(expected, 600), actual=_cut(actual, 600),
                    fix=_cut(fix, 800))
        except IntegrityError:
            continue
    raise Refused("The problem could not be numbered just now; try again.")


def _source_of(who, source: str, persona_id: str) -> tuple[str, str]:
    """"owner" (the owner's own words) or "persona" with the tester's key."""
    source = str(source or "").strip().lower()
    if source in ("", "owner", "petar", "me", "you", "person") and not persona_id:
        return "owner", ""
    return "persona", _tester(who, persona_id or source).key


def record(who, *, what: str, quote: str = "", screen: str = "", screen_name: str = "", how_bad: str = "confused",
           source: str = "owner", persona_id: str = "", gene: str = "", chat: str = "") -> dict:
    """A problem put on the list by hand: one of the owner's confusions, or one a tester hit outside a trial.
    An open problem with the same words on the same screen is seen again instead of written twice."""
    what = _cut(what, 300)
    if not what:
        raise Refused("Say what the problem is, in one short line.")
    bad = str(how_bad or "confused").lower().strip()
    bad = bad if bad in HOW_BAD else "confused"
    src, pid = _source_of(who, source, persona_id)
    key = screen_key(screen) if screen else ""
    name = _cut(screen_name, 200) or (screen_name_of_key(key) if key else "")
    row = (_m().TrialProblem.objects.filter(**_whose(who), status="open", screen=key, what__iexact=what).first())
    if row is not None:
        return sighting(who, row.number, quote=quote or what, how_bad=bad, source=src, persona_id=pid, chat=chat)
    now = _now()
    row = _new_problem(who, what=what, screen=key, screen_name=name, how_bad=bad, source=src,
                       personas=[pid] if pid else [], gene=_cut(gene, 80), now=now)
    _m().TrialSighting.objects.create(**_whose(who), problem_id=row.id, quote=_cut(quote or what, 1200), how_bad=bad,
                                      source=src, persona=pid, chat=_cut(chat, 120), at=now)
    return problem_dict(row)


def screen_name_of_key(key: str) -> str:
    """A name for a screen known only by its address: the last words of it."""
    parts = [p for p in key.split("/") if p and p != "#"]
    return " ".join(parts[-2:]).replace("-", " ").capitalize() if parts else "Rouh's first screen"


def sighting(who, number, *, quote: str, how_bad: str = "", source: str = "owner", persona_id: str = "",
             trial: int | None = None, step: int | None = None, chat: str = "") -> dict:
    """One more time a problem on the list was seen: its count goes up and the words are kept with it."""
    p = _problem(who, number)
    quote = _cut(quote, 1200)
    if not quote:
        raise Refused("Say what was said or seen, in the words it was said in.")
    bad = str(how_bad or p.how_bad).lower().strip()
    bad = bad if bad in HOW_BAD else p.how_bad
    src, pid = _source_of(who, source, persona_id)
    trial_id = _trial(who, trial).id if trial else None
    now = _now()
    p.count += 1
    p.last_at = now
    p.how_bad = _worse(p.how_bad, bad)
    if pid and pid not in (p.personas or []):
        p.personas = list(p.personas or []) + [pid]
    p.save(update_fields=["count", "last_at", "how_bad", "personas"])
    _m().TrialSighting.objects.create(**_whose(who), problem_id=p.id, trial_id=trial_id,
                                      step=int(step) if step is not None and trial_id else None, quote=quote,
                                      how_bad=bad, source=src, persona=pid, chat=_cut(chat, 120), at=now)
    return problem_dict(p)


def reopen(who, number, *, note: str = "") -> dict:
    """A closed problem back on the open list, when it turns out not to be fixed. Closing is never by hand:
    only a passing trial that visits its screen closes one."""
    p = _problem(who, number)
    if p.status != "open":
        p.status, p.closed_at, p.closed_by = "open", None, None
        p.closed_note = _cut(f"Opened again: {note}" if note else "Opened again.", 400)
        p.save(update_fields=["status", "closed_at", "closed_by", "closed_note"])
    return problem_dict(p)


# --- a problem's discussion and the owner's verdict ----------------------------------------------
#
# Petar: "for each try, I want to see the different problems and discuss them." He writes, Rouh answers
# in the thread on the Smart tier with the problem, its screenshot and the try in front of it, and from
# there he sets it aside (not a problem, won't fix), decides how it is fixed (which the builder of the
# next round reads, `rouh-trial problems --status decided`), or sends it as feedback to Gene therapy.


def set_verdict(who, number, verdict: str, *, decision: str = "", feedback_id: str = "") -> dict:
    """The owner's verdict on a problem, said in its thread as one line. "" takes a verdict back."""
    p = _problem(who, number)
    verdict = str(verdict or "").strip().lower().replace(" ", "_").replace("'", "")
    verdict = {"won't_fix": "wont_fix", "wontfix": "wont_fix", "not": "not_a_problem", "undo": "", "open": "",
               "feedback": "sent"}.get(verdict, verdict)
    if verdict not in VERDICTS:
        raise Refused("A verdict is not_a_problem, wont_fix, decided (with how to fix it), sent, or nothing.")
    decision = str(decision or "").strip()[:3000]
    if verdict == "decided" and not decision:
        raise Refused("Say how it should be fixed: \"Fix it like this: ...\".")
    now = _now()
    p.verdict, p.verdict_at = verdict, now if verdict else None
    p.decision = decision if verdict == "decided" else (p.decision if verdict == "sent" else "")
    if feedback_id:
        p.feedback_id = _cut(feedback_id, 80)
    p.save(update_fields=["verdict", "verdict_at", "decision", "feedback_id"])
    line = {"": "Taken back: it is open again.", "not_a_problem": "Marked as not a problem.",
            "wont_fix": "Marked as won't fix.", "decided": f"Decided: {decision}",
            "sent": "Sent as feedback, to Rouh's list of changes to itself (Gene therapy)."}[verdict]
    _m().TrialNote.objects.create(**_whose(who), problem_id=p.id, who="owner", kind="verdict", text=line, at=now)
    return problem(who, number)


TALK = """You are Rouh, a personal assistant, talking with ‹owner›, the person you belong to, about one usability problem a made-up test person ran into while trying a page of Rouh on their phone. You are shown the problem, every time it was seen with the tester's own words, the try it came from step by step, the discussion so far, and the screenshot of the moment.

Answer ‹owner›'s last message in the thread. Be short and plain: two to five sentences, no headings, no jargon, no code. Say what you think is really going on for the tester and why, and when it helps, suggest one concrete way to fix it on the screen. If ‹owner› seems to be deciding, say in one line what you would mark it as: Not a problem, Won't fix, or Fix it like this: <how>. Never pretend you changed anything: you only talk here."""


def _talk_context(who, p) -> tuple[str, str | None]:
    """The problem, its sightings, the try it was first seen in, and the thread, as text; and one screenshot."""
    d = problem_dict(p, notes=True)
    lines = [f"Problem {d['number']}: {d['what']}", f"How bad: {HOW_BAD_NAMES.get(d['how_bad'], d['how_bad'])}",
             f"On the screen: {d['screen_name'] or 'somewhere in Rouh'}", f"Where it stands: {VERDICTS.get(d['verdict'])}"
             + (" (fixed by a later try)" if d["status"] == "closed" else "")]
    for k, label in (("expected", "What should have happened"), ("actual", "What happened"), ("fix", "Suggested fix"),
                     ("decision", "Decided fix")):
        if d.get(k):
            lines.append(f"{label}: {d[k]}")
    lines.append("")
    lines.append("Every time it was seen:")
    for s in d.get("sightings") or []:
        lines.append(f"- {s['persona_name'] if s['source'] == 'persona' else '‹owner›'}"
                     + (f", try {s['trial']} step {s['step']} ({s['job_name']})" if s.get("trial") else "")
                     + f": \"{s['quote']}\"")
    shot = None
    first = next((s for s in reversed(d.get("sightings") or []) if s.get("trial")), None)
    if first:
        t = _trial(who, first["trial"])
        lines += ["", f"The try: {d['sightings'][0]['persona_name']} wanted to: {t.goal}"]
        for s in _m().TrialStep.objects.filter(trial_id=t.id, **_whose(who)).order_by("n")[:30]:
            lines.append(f"Step {s.n} ({screen_name(s.title, s.screen)}): saw: {s.see} | thought: {s.think} | did: {s.does}")
        if t.ending:
            lines.append(f"Ending: managed it: {t.managed or '-'}. {t.ending}")
        if first.get("shot"):
            path = shot_path(who, first["trial"], first["step"])
            if path is not None:
                shot = base64.b64encode(path.read_bytes()).decode("ascii")
    lines += ["", "The discussion so far:"]
    for n in d.get("thread") or []:
        lines.append(f"{'‹owner›' if n['who'] == 'owner' else 'Rouh'}: {n['text']}")
    return "\n".join(lines), shot


async def say(who, number, text: str) -> dict:
    """The owner writes in a problem's thread, and Rouh answers there. The owner's words are kept even when
    Rouh cannot answer just now, and the answer says why."""
    import asyncio

    from rouh import llm, owner

    text = str(text or "").strip()[:4000]
    if not text:
        raise Refused("Write something first.")
    p = await asyncio.to_thread(_problem, who, number)
    await asyncio.to_thread(lambda: _m().TrialNote.objects.create(**_whose(who), problem_id=p.id, who="owner",
                                                                  kind="said", text=text, at=_now()))
    context, shot = await asyncio.to_thread(_talk_context, who, p)
    content: list[dict] = []
    if shot:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": shot}})
    content.append({"type": "text", "text": await asyncio.to_thread(owner.say, context + "\n\nAnswer ‹owner›'s last message.", who)})
    system = await asyncio.to_thread(owner.say, TALK, who)
    error = "it said nothing"
    try:
        got = await llm.ask(TALK_USE, system=system, messages=[{"role": "user", "content": content}],
                            max_tokens=900, who=who, read_only=True, timeout=180, subject=f"problem {p.number}")
        reply, model = got.text.strip(), got.model
    except Exception as exc:  # noqa: BLE001 - the owner's words are kept, and the thread says Rouh could not answer
        log.exception("trials: problem %s could not be answered", p.number)
        reply, model = "", ""
        error = str(exc).strip() or type(exc).__name__
    if reply:
        await asyncio.to_thread(lambda: _m().TrialNote.objects.create(**_whose(who), problem_id=p.id, who="rouh",
                                                                      kind="said", text=reply[:6000], model=model[:80],
                                                                      at=_now()))
    out = await asyncio.to_thread(problem, who, number)
    if not reply:
        out["unanswered"] = f"Rouh could not answer just now ({error[:200]}). Your words are kept."
    return out


def feedback_text(who, number) -> str:
    """One problem as a report for Gene therapy: what, where, steps, expected, actual, how to fix, in plain words."""
    d = problem(who, number)
    s = next((x for x in d.get("sightings") or [] if x.get("trial")), None)
    lines = [f"Trials, problem {d['number']}: {d['what']}", "",
             f"Where: {d['screen_name'] or 'somewhere in Rouh'}" + (f" ({d['screen']})" if d["screen"] else ""),
             f"How bad: {HOW_BAD_NAMES.get(d['how_bad'], d['how_bad'])}, seen {d['count']} "
             f"time{'' if d['count'] == 1 else 's'}"]
    if s:
        lines.append(f"Found by {s['persona_name']} in try {s['trial']}, step {s['step']} ({s['job_name']}): "
                     f"/evolution/trials/{s['trial']}")
    for k, label in (("expected", "What should have happened"), ("actual", "What happened"),
                     ("decision", "Fix it like this"), ("fix", "Suggested fix")):
        if d.get(k):
            lines += ["", f"{label}: {d[k]}"]
    quotes = [x for x in d.get("sightings") or [] if x.get("quote")][:3]
    if quotes:
        lines += ["", "In their words:"] + [f"- \"{x['quote']}\" ({x['persona_name'] if x['source'] == 'persona' else 'me'})"
                                            for x in quotes]
    lines += ["", f"The problem's page: /evolution/trials/problem/{d['number']}"]
    return "\n".join(lines)


def page_of_gene(key: str) -> str:
    """The address a gene's page opens at, from its manifest, or ""."""
    from rouh import genes

    for m in genes.read():
        if m.get("id") == key:
            return str(m.get("route") or "")
    return ""


def counts(who) -> dict:
    rows = list(_m().TrialProblem.objects.filter(**_whose(who)))
    by = {k: 0 for k in ("open", "decided", "fixed", "set_aside")}
    for p in rows:
        by[standing(p)] += 1
    return {"trials": _m().Trial.objects.filter(**_whose(who)).count(), "jobs": _m().TrialJob.objects.filter(
        **_whose(who)).count(), "open": by["open"] + by["decided"], "closed": by["fixed"], **{"by": by}}


def screens(who) -> list[dict]:
    """Every screen a problem is on, for the page's filter."""
    seen: dict[str, str] = {}
    for key, name in _m().TrialProblem.objects.filter(**_whose(who)).values_list("screen", "screen_name"):
        if key not in seen or (name and not seen[key]):
            seen[key] = name or key
    # The owner's words in a chat have no screen: they are found by who said them, not by where.
    return [{"key": k, "name": v or "Somewhere in Rouh"} for k, v in sorted(seen.items(), key=lambda kv: kv[1]) if k]


def line_for_model(t: dict) -> str:
    state = {"passed": "passed", "failed": "did not pass", "running": "running now", "queued": "waiting to start",
             "broken": "could not finish"}.get(t["state"], t["state"])
    when = time.strftime("%Y-%m-%d", time.localtime(t["created_at"]))
    return (f"Trial {t['number']} ({when}): {t['persona_name']} tried {t['job_name'] or t['subject'] or 'a page'}"
            f"{' (job ' + str(t['job']) + ')' if t.get('job') else ''}, round {t['round']} of "
            f"{ROUNDS}, {state}; managed it: {t['managed'] or '-'}; {t['steps']} steps; {t['problems']} problems. "
            f"Goal: {t['goal']}  Page: /evolution/trials/{t['number']}")


def problem_line(p: dict) -> str:
    who = p["source"] == "owner" and "the owner" or ", ".join(x.title() for x in p["personas"]) or "a tester"
    quote = (p.get("sightings") or [{}])[0].get("quote", "")
    stand = {"open": "open", "decided": "decided", "fixed": "fixed", "set_aside": "set aside"}[p.get("standing") or "open"]
    if p.get("awaiting_choice"):
        stand += ", waiting on the owner's choice from a review: leave it alone"
    return (f"Problem {p['number']} [{stand}{': ' + p['verdict_name'].lower() if p.get('verdict') else ''}] on "
            f"{p['screen_name'] or 'somewhere in Rouh'}: {p['what']} "
            f"({HOW_BAD_NAMES.get(p['how_bad'], p['how_bad']).lower()}, seen {p['count']} time"
            f"{'' if p['count'] == 1 else 's'}, by {who})" + (f" - \"{quote}\"" if quote else "")
            + (f" Fix it like this: {p['decision']}" if p.get("decision") else "")
            + (f" Suggested fix: {p['fix']}" if p.get("fix") and not p.get("decision") else ""))


# --- a trial, step by step ----------------------------------------------------------------------


def start(who, *, persona_id: str = "", goal: str = "", subject: str = "", gene: str = "", page: str = "",
          round_no: int = 1, first: int | None = None, number: int | None = None, by: str = "",
          run_id: str = "", job_no=None, job_name: str = "", mode: str = "auto") -> dict:
    """A new trial, running, or a queued one taken up by the run that came for it (`number`). It belongs to
    the job named (`job_no`, or one called `job_name`), its first round's job, or a job made for it."""
    M = _m()
    if number:
        t = _trial(who, number)
        if t.state not in ("queued", "broken"):
            raise Refused(f"Trial {t.number} has already run.")
        t.state, t.started_at, t.by = "running", _now(), _cut(by, 120) or t.by
        t.run_id = _cut(run_id, 80) or t.run_id
        t.save(update_fields=["state", "started_at", "by", "run_id"])
        return trial_dict(t)
    mode = mode if mode in MODES else "auto"
    goal = _cut(goal, 400)
    if not goal and job_no:
        goal = _job(who, job_no).goal
    if not goal:
        raise Refused("A trial needs its goal: one sentence, as the person would put it.")
    pid = persona(who, persona_id)["id"] if persona_id else default_persona(who)
    # A paused tester, or everyone while all testing is paused, starts nothing new (Petar, 5 November 2026).
    _refuse_if_paused(who, pid)
    # A review has no rounds: nothing is fixed between its tries until the owner chooses.
    round_no = 1 if mode == "review" else max(1, min(ROUNDS, int(round_no or 1)))
    first_id = None
    if round_no > 1:
        if first:
            first_id = _trial(who, first).id
        else:
            earlier = M.Trial.objects.filter(**_whose(who), persona=pid, goal=goal, round=1).order_by("-created_at").first()
            first_id = earlier.id if earlier else None
    j = _job_for(who, job_no=job_no, name=job_name, subject=subject, goal=goal, page=page, gene=gene, first_id=first_id)
    if not subject:
        subject = j.name
    now = _now()
    M.TrialJob.objects.filter(id=j.id).update(updated_at=now, **({"goal": goal} if not j.goal else {}),
                                              **({"page": _cut(page, 400)} if page and not j.page else {}),
                                              **({"gene": _cut(gene, 80)} if gene and not j.gene else {}))
    for _ in range(5):
        try:
            from django.db import IntegrityError, transaction

            with transaction.atomic():
                t = M.Trial.objects.create(**_whose(who), number=_number_next(M.Trial, who), persona=pid, goal=goal,
                                           job_id=j.id, mode=mode,
                                           subject=_cut(subject, 160), gene=_cut(gene, 80), page=_cut(page, 400),
                                           round=round_no, first_id=first_id, state="queued" if not by else "running",
                                           by=_cut(by, 120), run_id=_cut(run_id, 80), created_at=now,
                                           started_at=now if by else None)
            return trial_dict(t)
        except IntegrityError:
            continue
    raise Refused("The trial could not be numbered just now; try again.")


def _history(t, most: int = 12) -> str:
    """What the tester said so far, in its own words, as plain text: each earlier step, what it saw,
    thought and did. Only its own words: never the page's."""
    rows = list(_m().TrialStep.objects.filter(trial_id=t.id, org_id=t.org_id, user_id=t.user_id).order_by("-n")[:most])
    if not rows:
        return ""
    lines = ["What you have done so far, in your own words:"]
    for s in reversed(rows):
        lines.append(f"Step {s.n} ({s.title or 'a screen'}): you saw: {s.see} You thought: {s.think} You did: {s.does}")
    return "\n".join(lines) + "\n\n"


def _observation_text(n: int, obs: dict) -> str:
    marks = obs.get("marks") or []
    lines = []
    for m in marks[:150]:
        words = _cut(m.get("words"), 120)
        kind = _cut(m.get("kind"), 30) or "something to tap"
        lines.append(f"[{int(m.get('n') or 0)}] {kind}: " + (f"\"{words}\"" if words else "no words, only a small picture"))
    where = []
    if obs.get("at_top") is False:
        where.append("there is more above")
    if obs.get("at_bottom") is False:
        where.append("there is more below, if you scroll down")
    said = _cut(obs.get("note"), 300)
    return "\n".join([
        f"Step {n}. This is your screen now." + (f" ({said})" if said else ""),
        f"The words at the top of the browser tab: {_cut(obs.get('title'), 120) or '(none)'}",
        "", "Words on the screen:", str(obs.get("text") or "(none)")[:6000],
        "", "Things you can tap or type into:", "\n".join(lines) or "(none)",
        "", ("On this screen " + " and ".join(where) + ".") if where else "",
        "Answer with one JSON object, as you were told.",
    ])


async def step(who, number, obs: dict) -> dict:
    """One step: keep the screenshot, ask the tester what it sees, thinks and does, write it down, and hand
    back what the browser is to do. `obs` is {url, title, text, marks, shot, marked, at_top, at_bottom, note}."""
    import asyncio

    from rouh import llm

    t = await asyncio.to_thread(_trial, who, number)
    if t.state != "running":
        raise Refused(f"Trial {t.number} is not running.")
    n = await asyncio.to_thread(lambda: _m().TrialStep.objects.filter(trial_id=t.id, **_whose(who)).count() + 1)
    shot = ""
    raw = obs.get("shot") or ""
    if raw:
        try:
            data = base64.b64decode(raw)
            folder = shots_dir(who, t.id)
            folder.mkdir(parents=True, exist_ok=True)
            shot = f"{n}.jpg"
            (folder / shot).write_bytes(data[:4_000_000])
        except (ValueError, OSError):
            log.exception("a trial's screenshot could not be kept")
            shot = ""
    history = await asyncio.to_thread(_history, t)
    system = await asyncio.to_thread(system_for, who, t.persona, t.goal)
    image = obs.get("marked") or raw
    got, said, model, usage = None, "", "", {}
    for tries in range(3):
        if tries:
            await asyncio.sleep(3 * tries)
        content: list[dict] = []
        # An answer with nothing in it is asked again a little differently, since the same question
        # gave nothing three times running (trials 8, 9, 13 and 14): the second time without the picture
        # (the words and the numbered things are still there), the third also without the older steps.
        if image and not tries:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}})
        given = _cut(obs.get("given"), 600)
        text = (f"What you were given for this: {given}\n\n" if given else "") + (history if tries < 2 else "") \
            + _observation_text(n, obs)
        if tries:
            text += ("\n\n(The picture of the screen could not be shown this time: go by the words and the numbered "
                     "things.)" if image else "") + "\n\nAnswer with one JSON object and nothing else."
        content.append({"type": "text", "text": text})
        answer = await llm.ask(USE, system=system, messages=[{"role": "user", "content": content}], max_tokens=4000,
                               who=who, subject=f"trial {t.number}, step {n}", timeout=180)
        said, model, usage = answer.text, answer.model, answer.usage
        got = _json_in(said)
        if got:
            break
    if not got:
        log.warning("trial %s step %s: the tester said %r", t.number, n, said[:2000])
        raise Refused("The tester did not answer in a form that can be read: "
                      + (_cut(said, 300) or f"{model} said nothing ({usage})."))
    do = got.get("do") if isinstance(got.get("do"), dict) else {}
    action = str(do.get("action") or "").strip().lower().replace(" ", "_")
    if action not in ("tap", "type", "scroll_down", "scroll_up", "back", "wait", "done", "give_up"):
        action = "give_up" if n >= MOST_STEPS else "wait"
    do = {"action": action, "number": do.get("number"), "text": _cut(do.get("text"), 500),
          "enter": bool(do.get("enter"))}
    answers = got.get("answers") if isinstance(got.get("answers"), dict) else {}
    if answers:
        clear = answers.get("clear") if isinstance(answers.get("clear"), list) else []
        answers = {"what": _cut(answers.get("what"), 600), "how": _cut(answers.get("how"), 600),
                   "then": _cut(answers.get("then"), 600), "clear": [bool(c) for c in clear[:3]] + [True] * (3 - len(clear[:3]))}
    found = []
    for p in got.get("problems") or []:
        if isinstance(p, dict) and _cut(p.get("what"), 300):
            bad = str(p.get("how_bad") or "").lower().strip()
            found.append({"what": _cut(p.get("what"), 300), "said": _cut(p.get("said") or p.get("what"), 800),
                          "expected": _cut(p.get("expected"), 500), "happened": _cut(p.get("happened"), 500),
                          "how_bad": bad if bad in HOW_BAD else "minor"})
    # A question of the three they could not answer is a problem in itself.
    if answers and not all(answers["clear"]) and not found:
        which = [q for q, ok in zip(("What is this?", "What do I do here?", "What happens when I do it?"),
                                    answers["clear"]) if not ok]
        found.append({"what": "Could not answer: " + " ".join(which), "said": _cut(got.get("think"), 800),
                      "how_bad": "confused"})
    url = _cut(obs.get("url"), 1000)

    def write():
        _m().TrialStep.objects.create(
            **_whose(who), trial_id=t.id, n=n, at=_now(), url=url, screen=screen_key(url),
            title=_cut(obs.get("title"), 200), shot=shot, see=_cut(got.get("see"), 1500),
            think=_cut(got.get("think"), 3000), does=_cut(got.get("doing"), 600), action=do, answers=answers or {},
            found=found)
        key = screen_key(url)
        screens_seen = list(t.screens or [])
        if key not in screens_seen:
            screens_seen.append(key)
        _m().Trial.objects.filter(id=t.id).update(steps=n, model=model[:80], screens=screens_seen)

    await asyncio.to_thread(write)
    out = {"ok": True, "step": n, "do": do, "doing": _cut(got.get("doing"), 600), "think": _cut(got.get("think"), 600)}
    if action in ("done", "give_up"):
        ending = got.get("ending") if isinstance(got.get("ending"), dict) else {}
        out["ending"] = ending
        out["finished"] = await finish(who, t.number, ending=ending, gave_up=action == "give_up")
    return out


async def _ending_now(who, t) -> dict:
    """Out of steps, or stopped: the tester is asked once for its ending."""
    from rouh import llm

    import asyncio

    history = await asyncio.to_thread(_history, t)
    system = await asyncio.to_thread(system_for, who, t.persona, t.goal)
    try:
        answer = await llm.ask(USE, system=system, messages=[{"role": "user", "content": history + ENDING_NOW}],
                               max_tokens=900, who=who, subject=f"trial {t.number}, ending", timeout=120)
    except Exception:  # noqa: BLE001 - the trial ends without the words, said as such
        log.exception("trial %s: the ending could not be asked", t.number)
        return {}
    got = _json_in(answer.text) or {}
    ending = got.get("ending") if isinstance(got.get("ending"), dict) else {}
    extra = [p for p in got.get("problems") or [] if isinstance(p, dict) and p.get("what")]
    if extra:
        def add():
            last = _m().TrialStep.objects.filter(trial_id=t.id, **_whose(who)).order_by("-n").first()
            if last is not None:
                last.found = list(last.found or []) + [
                    {"what": _cut(p.get("what"), 300), "said": _cut(p.get("said") or p.get("what"), 800),
                     "how_bad": p.get("how_bad") if p.get("how_bad") in HOW_BAD else "minor"} for p in extra]
                last.save(update_fields=["found"])
        await asyncio.to_thread(add)
    return ending


async def finish(who, number, *, ending: dict | None = None, gave_up: bool = False, why: str = "") -> dict:
    """The ending: whether they managed it, the problems put on the list, problems they got past closed,
    and pass or fail."""
    import asyncio

    t = await asyncio.to_thread(_trial, who, number)
    if t.state != "running":
        return trial_dict(t)
    ending = dict(ending or {})
    if not ending.get("managed"):
        ending = {**(await _ending_now(who, t)), **{k: v for k, v in ending.items() if v}}
    managed = str(ending.get("managed") or "").strip().lower()
    # Cut short with no ending of their own (the tester stopped answering) is "partly", never a "no" they did not say.
    managed = managed if managed in ("yes", "partly", "no") else ("no" if gave_up else "partly")
    found = await _put_on_list(who, t)
    t = await asyncio.to_thread(_trial, who, number)
    # A problem the owner set aside (not a problem, won't fix) no longer fails a try.
    stops = any(f["how_bad"] in FAILS and f.get("verdict") not in SET_ASIDE for f in found)
    state = "passed" if managed == "yes" and not stops else "failed"

    def write():
        now = _now()
        t.managed, t.state = managed, state
        t.nearly_gave_up = _cut(ending.get("nearly_gave_up"), 800)
        t.ending = _cut(ending.get("how_it_went"), 2000)
        t.why = _cut(why, 400)
        t.problems = len(found)
        t.ended_at = now
        t.seconds = now - (t.started_at or t.created_at)
        t.save(update_fields=["managed", "state", "nearly_gave_up", "ending", "why", "problems", "ended_at", "seconds"])
        if state == "passed":
            _close_got_past(who, t, {f["problem_id"] for f in found})
        if state == "failed" and t.round >= ROUNDS and t.mode != "review":
            _told_shipped(who, t)
        return trial_dict(t, steps=True)

    return await asyncio.to_thread(write)


def broken(who, number, why: str) -> dict:
    """The trial could not finish (the browser, the app or the tester failed): said, and nothing closed."""
    t = _trial(who, number)
    if t.state in ("running", "queued"):
        t.state, t.why, t.ended_at = "broken", _cut(why, 600) or "It could not finish.", _now()
        t.seconds = t.ended_at - (t.started_at or t.created_at)
        t.save(update_fields=["state", "why", "ended_at", "seconds"])
    return trial_dict(t)


async def _matches(who, new: list[dict], open_rows: list) -> list[dict]:
    """For each new problem: the open problem it is the same as, or an earlier new one, by the Smart model;
    or by the same screen and the same words when it cannot be asked."""
    from rouh import llm

    plain = [{"new": i, "same_as": next((p.number for p in open_rows if p.screen == f["screen"]
                                         and p.what.lower() == f["what"].lower()), None),
              "same_as_new": next((j for j in range(i) if new[j]["screen"] == f["screen"]
                                   and new[j]["what"].lower() == f["what"].lower()), None), "fix": ""}
             for i, f in enumerate(new)]
    if not new:
        return []
    listed = "\n".join(f"Problem {p.number} on {p.screen_name or p.screen}: {p.what}" for p in open_rows[:80]) or "(none)"
    fresh = "\n".join(f"New {i} on {f['screen_name'] or f['screen']}: {f['what']} (said: {f['said'][:200]})"
                      for i, f in enumerate(new))
    try:
        answer = await llm.ask(MATCH_USE, system=MATCH, max_tokens=1200, who=who, read_only=True, timeout=120,
                               messages=f"Open problems on the list:\n{listed}\n\nNew problems:\n{fresh}")
    except Exception:  # noqa: BLE001 - matched by their words instead, never lost
        log.exception("trial problems could not be matched by the model")
        return plain
    got = (_json_in(answer.text) or {}).get("matches")
    if not isinstance(got, list):
        return plain
    numbers = {p.number for p in open_rows}
    out = []
    for i in range(len(new)):
        m = next((g for g in got if isinstance(g, dict) and g.get("new") == i), {}) or {}
        same = m.get("same_as") if m.get("same_as") in numbers else None
        twin = m.get("same_as_new") if isinstance(m.get("same_as_new"), int) and 0 <= m.get("same_as_new") < i else None
        out.append({"new": i, "same_as": same, "same_as_new": twin, "fix": _cut(m.get("fix"), 800)})
    return out


def _worse(a: str, b: str) -> str:
    return min(a, b, key=lambda x: HOW_BAD.index(x) if x in HOW_BAD else 9)


async def _put_on_list(who, t) -> list[dict]:
    """Every problem the trial's steps named, on the list: a new problem, or a sighting of one already there."""
    import asyncio

    M = _m()

    def gather():
        steps = list(M.TrialStep.objects.filter(trial_id=t.id, **_whose(who)).order_by("n"))
        new = []
        for s in steps:
            for f in s.found or []:
                new.append({**f, "step": s.n, "screen": s.screen, "screen_name": screen_name(s.title, s.screen)})
        keys = {f["screen"] for f in new}
        # Every problem not fixed, set aside ones too: one seen again is counted, never written twice.
        open_rows = list(M.TrialProblem.objects.filter(**_whose(who), status="open", screen__in=keys))
        return new, open_rows

    new, open_rows = await asyncio.to_thread(gather)
    matches = await _matches(who, new, open_rows)

    def write():
        by_number = {p.number: p for p in open_rows}
        made: dict[int, object] = {}
        out = []
        for m in matches:
            f = new[m["new"]]
            now = _now()
            row = by_number.get(m["same_as"]) if m["same_as"] else made.get(m["same_as_new"]) if m["same_as_new"] is not None else None
            if row is None:
                for _ in range(5):
                    from django.db import IntegrityError, transaction

                    try:
                        with transaction.atomic():
                            row = M.TrialProblem.objects.create(
                                **_whose(who), number=_number_next(M.TrialProblem, who), screen=f["screen"],
                                screen_name=_cut(f["screen_name"], 200), what=f["what"], how_bad=f["how_bad"],
                                source="persona", personas=[t.persona], gene=t.gene, count=1, first_at=now, last_at=now,
                                expected=_cut(f.get("expected"), 600), actual=_cut(f.get("happened"), 600),
                                fix=_cut(m.get("fix"), 800))
                        break
                    except IntegrityError:
                        continue
            else:
                row.count += 1
                row.last_at = now
                row.how_bad = _worse(row.how_bad, f["how_bad"])
                if t.persona not in (row.personas or []):
                    row.personas = list(row.personas or []) + [t.persona]
                # What was expected and what happened, kept from the first sighting that said them.
                row.expected = row.expected or _cut(f.get("expected"), 600)
                row.actual = row.actual or _cut(f.get("happened"), 600)
                row.save(update_fields=["count", "last_at", "how_bad", "personas", "expected", "actual"])
            made[m["new"]] = row
            M.TrialSighting.objects.create(**_whose(who), problem_id=row.id, trial_id=t.id, step=f["step"],
                                           quote=f["said"], how_bad=f["how_bad"], source="persona", persona=t.persona,
                                           at=now)
            out.append({"problem_id": row.id, "number": row.number, "how_bad": f["how_bad"], "verdict": row.verdict})
        return out

    return await asyncio.to_thread(write)


def _close_got_past(who, t, tripped: set) -> int:
    """Open problems on a screen this passing trial visited that it did not trip on are closed by it."""
    keys = set(t.screens or [])
    if not keys:
        return 0
    rows = _m().TrialProblem.objects.filter(**_whose(who), status="open", screen__in=keys).exclude(id__in=tripped)
    return rows.update(status="closed", closed_at=_now(), closed_by=t.id,
                       closed_note=f"Trial {t.number} visited this screen and did not trip on it.")


def _told_shipped(who, t) -> None:
    """After round 3 a change ships anyway, and the owner is told in one line."""
    try:
        from rouh import notices

        name = trial_dict(t)["persona_name"]
        notices.post(who, title=f"Shipped anyway: {name} still struggles with {t.subject or 'a change'} after two "
                                f"rounds of fixes.",
                     link=f"/evolution/trials/{t.number}", link_label="See the trial", kind="trials",
                     key=f"trial-shipped-{t.org_id}-{t.id}")
    except Exception:  # noqa: BLE001 - the line is worth saying, never worth failing the trial over
        log.exception("trial %s: the owner could not be told", t.number)


# --- the owner's own confusions -----------------------------------------------------------------

#: What saying something in Rouh is confusing looks like, in English or Bulgarian.
_CONFUSED = re.compile(
    r"\b(?:(?:this|that|it)(?:'s| is| was)? (?:so |very |really |too )?(?:confusing|unclear|hard to (?:read|follow|understand))"
    r"|(?:i )?(?:still )?(?:don'?t|do not|didn'?t|did not|can'?t|cannot) (?:understand|follow|get) (?:this|that|it|what)"
    r"|makes no sense|what does (?:this|that) (?:mean|button do)|i(?:'m| am) (?:lost|confused))\b"
    r"|не разбирам|объркващо|неясно", re.I)


def owner_said(who, text: str, *, chat: str = "", screen: str = "", screen_name: str = "") -> list[int]:
    """Put the owner's own confusion on the list: a term they ask the meaning of (`plain_words.asked_terms`,
    the same reading that keeps the terms they asked about), or saying something in Rouh is confusing.
    The numbers of the problems written to, or none. Never raises."""
    try:
        from rouh import plain_words

        text = str(text or "").strip()
        if who is None or not text or len(text) > 1500:
            return []
        found: list[tuple[str, str]] = []
        for term in plain_words.asked_terms(text):
            found.append((f"What “{term}” means", "confused"))
        if not found and _CONFUSED.search(text):
            # Said of the screen in front of them, or of an answer: the words are kept as the sighting,
            # and the title says what happened, so it reads on its own.
            found.append(((f"Found {screen_name} confusing" if screen_name else "Found an answer in a chat confusing"),
                          "confused"))
        if not found:
            return []
        M = _m()
        out = []
        now = _now()
        for what, bad in found:
            row = (M.TrialProblem.objects.filter(**_whose(who), source="owner", status="open", screen=screen or "")
                   .filter(what__iexact=what).first())
            if row is None:
                row = M.TrialProblem.objects.create(
                    **_whose(who), number=_number_next(M.TrialProblem, who), screen=screen or "",
                    screen_name=_cut(screen_name, 200) or ("A word Rouh used" if what.startswith("What “") else "A chat with Rouh"),
                    what=what, how_bad=bad, source="owner", personas=[], count=1, first_at=now, last_at=now)
            else:
                row.count += 1
                row.last_at = now
                row.save(update_fields=["count", "last_at"])
            M.TrialSighting.objects.create(**_whose(who), problem_id=row.id, quote=_cut(text, 1200), how_bad=bad,
                                           source="owner", chat=_cut(chat, 120), at=now)
            out.append(row.number)
        return out
    except Exception:  # noqa: BLE001 - noting a confusion is never worth a turn
        log.exception("the owner's confusion could not be put on the list")
        return []


# --- a review's chosen fixes ---------------------------------------------------------------------


def chosen(who, number) -> list[dict]:
    """The problems a try found that the owner chose to have fixed, and how: "Fix it like this", not yet fixed."""
    t = _trial(who, number)
    ids = set(_m().TrialSighting.objects.filter(**_whose(who), trial_id=t.id).values_list("problem_id", flat=True))
    rows = _m().TrialProblem.objects.filter(**_whose(who), id__in=ids, verdict="decided", status="open")
    return [problem_dict(p) for p in sorted(rows, key=_rank)]


def fix_brief(t: dict, picked: list[dict]) -> str:
    lines = [f"‹Owner› went through review {t['number']} of {t['job_name'] or t['subject'] or 'a page of Rouh'} "
             f"(/evolution/trials/{t['number']}) and chose these problems to fix, each the way they said. Fix these "
             "and nothing else from the review: every other problem it found is left as it is, because ‹owner› did "
             "not choose it.", ""]
    for p in picked:
        lines.append(f"- Problem {p['number']} on {p['screen_name'] or 'somewhere in Rouh'}"
                     + (f" ({p['screen']})" if p.get("screen") else "") + f": {p['what']}")
        lines.append(f"  Fix it like this: {p['decision']}")
        if p.get("expected"):
            lines.append(f"  What should have happened: {p['expected']}")
        if p.get("actual"):
            lines.append(f"  What happened: {p['actual']}")
    lines += ["", "Prove each fix in the browser, then run the automatic trial as the stage below says."]
    return "\n".join(lines)


async def fix_chosen(who, number) -> dict:
    """Start one run that fixes the problems the owner chose from a review, their way. Only when they press
    Fix the ones I chose, or say so in their own words."""
    import asyncio

    from rouh import nightly_feature, owner

    t = await asyncio.to_thread(one, who, number)
    picked = await asyncio.to_thread(chosen, who, number)
    if not picked:
        raise Refused("Nothing is chosen to fix yet: on a problem, press Fix it like this and say how.")
    try:
        if nightly_feature.hooks.start is None:
            raise RuntimeError("Rouh's runs are not ready")
        agent = await asyncio.to_thread(nightly_feature.engine, who)
        got = await nightly_feature.hooks.start(
            brief=owner.say(fix_brief(t, picked), who),
            title=f"Fix what you chose from review {t['number']}: {len(picked)} problem{'' if len(picked) == 1 else 's'}",
            preset="improve_myself", agent=agent, use=nightly_feature.USE, org_id=str(who.org_id),
            one_fields={"browser_port": nightly_feature._free_port()})
    except Exception as exc:  # noqa: BLE001 - said plainly
        log.exception("review %s: its chosen fixes could not be started", t["number"])
        raise Refused(f"The fixes could not be started ({str(exc).strip().rstrip('.') or type(exc).__name__}).") from None
    n = len(picked)
    return {"run_id": str(got.get("id") or ""), "count": n,
            "said": f"Rouh is fixing the {n} problem{'' if n == 1 else 's'} you chose, your way, in one go. Nothing else "
                    "from this review is touched."}


# --- in gene therapy -----------------------------------------------------------------------------

#: The words that mark a run that only runs a trial, so it is not told to run one on top.
BY_HAND = "This run only runs a trial."

STAGE = """\
## Trials: can a person use it

After your Playwright proof passes, if your change touches anything a person sees (a page, a card, a screen, a message, an explanation), it goes through a trial before you land it. Playwright checks that it works; the trial checks that a person can use it. Keep the two reports apart: a gene passes both.

1. With your test world still up (`./e2e.sh serve`), run, from your checkout:
   `rouh-trial run --url http://127.0.0.1:<port><the page> --user <its sign-in> --password <its password> --goal "<one sentence>" --job "<what is being tested, in a few plain words>" --gene <the gene's key>`
   The goal is what the gene is for, written as the person would put it, with nothing about how it was built: "You want to see what Rouh did for you yesterday." The job is what is being tested, such as "Seeing yesterday's work"; every try of the same thing goes into the same job. The tester is the person's default (Vesela, unless they made someone else the default) unless the person asked for another by name (`--persona boris`); `rouh-trial personas` lists them.
2. It drives the browser as that person, at a phone's size, and prints PASS or FAIL, what they said, the problems, and the try's page. Wait for it, however long it takes.
3. This is the automatic mode: nobody is asked, and no problem waits for the person's choice. PASS: land it. FAIL: fix what the tester tripped on yourself, within what this change was already asked and approved to be, prove the fix in the browser again, and run it again with `--round 2` (a new tester, who has seen nothing). At most two rounds of fixes: if `--round 3` still fails, land it anyway; the problems stay open on the list, and Rouh tells the person in one line. Where the person already decided ("Fix it like this", `rouh-trial problems --status decided`), do it their way; leave alone what they set aside (not a problem, won't fix) and anything marked as waiting on their choice from a review they asked for.
4. In your last message, give the trial's result, its round and its page, apart from what Playwright showed.
5. If it prints `SKIPPED: skipped: tester paused` (it exits 0), the person has paused that tester, or all testing. That is not a failure and does not block anything: do not run it again, do not pick another tester, do not resume anyone, and do not try any other way round the pause. Land your change as you would after a pass, and write "Trial: skipped: tester paused" in your last message and in your test results."""


FOR_AGENTS = """\
## Trials

A trial is a made-up person, a tester (Vesela unless the person made someone else the default, or asks for another by name), trying a page of Rouh on a phone, step by step, and saying out loud what confuses them. It has two modes. **Automatic** (`rouh-trial run`, the default): a test while a feature is built; its builder fixes what tripped the tester within the feature's approved scope and tries again, at most two rounds, then ships, with nobody asked. **Review** (`rouh-trial run --review`, or `rouh-trial queue`): only when the person asked in their own words for someone to test something ("Have Vesela test this"); it is a report of the walk-through, results and suggestions for them to read and discuss, and nobody fixes anything from it until they choose what and how on its page. Naming a tester alone never makes a review. Every try belongs to a job, what is being tested; every problem a tester hits, and every confusion of the person's own, is kept on one list in Rouh, where the person discusses each and decides what to do with it. You reach all of it with `rouh-trial`, from anywhere:

```sh
rouh-trial run --url http://127.0.0.1:<port>/<page> --user <login> --password <pw> --goal "You want to ..." --job "What is tested"   # in a test world you stood up; prints PASS or FAIL
rouh-trial queue --page /evolution/trials --goal "You want to ..." [--job "..."] [--persona boris] [--wait]   # or --gene <key>; Rouh stands a test world up and runs it
rouh-trial jobs | job <n>                      # what is being tested, and one job with its tries
rouh-trial list | read <n> | wait <n>          # the tries; one with its steps, the three answers and its ending
rouh-trial problems [--status open|decided|fixed|set_aside|all] [--persona vesela] [--job 3] [--source owner|persona]
rouh-trial problem <n>                         # one problem, with every time it was seen, its discussion and the person's decision
rouh-trial record "what goes wrong" --quote "the words said" [--screen /page] [--source owner|boris] [--how-bad confused]
rouh-trial sighting <n> --quote "the words said"   |   rouh-trial reopen <n> --note "why"
rouh-trial personas | persona <name>           # the testers, and one whole profile
rouh-trial tester-add --name "..." --profile-file p.md [--age 33 --job ... --city ... --short ...]   |   rouh-trial tester-edit <name> [...]
rouh-trial tester-remove <name> | default <name>   # only when the person says so in their own words
```

A tester can be paused by the person, or all testing at once (`rouh-trial personas` says who is). A paused tester starts no new try of any kind: `rouh-trial run` and `queue` then print `SKIPPED: skipped: tester paused` and exit 0. That is never a failure and never blocks a build: record "skipped: tester paused" in your report and test results, carry on, and never work round it (another tester, resuming one, or anything else). Only the person pauses and resumes, on Evolution, Trials, Testers or in their own words.

A goal is one sentence, as the person would put it, never how the thing was built. A problem is closed only by a later trial that passes, never by hand. A problem the person decided ("Fix it like this") is fixed their way; one they set aside (not a problem, won't fix) is left alone, and so is one waiting on their choice from a review."""


def for_runs(org: str) -> str:
    """What every agent is told about Trials, after its agent instructions (`agent_instructions`)."""
    return FOR_AGENTS


#: What a build is told instead of the trial stage while testing is paused. Petar, 6 November 2026: "if I
#: pause all testers, anything that gets build should be built nevertheless in the old way before we had
#: testers. so nightly builds for example should keep building". So a paused build has no trial stage to
#: run, wait on or fix from: one line, so its report still says why there was no trial.
PAUSED_STAGE = """\
## Trials are paused

The person has paused usability testing, so this change has no trial stage: do not run `rouh-trial`, and build, prove, commit and land exactly as you would without trials. Write "Trial: skipped: tester paused" in your last message and in your test results. It is not a failure and blocks nothing."""


def build_paused(who) -> bool:
    """Whether a build's automatic trial would be skipped now: all testing is paused, or the tester who tries
    every change is."""
    if who is None:
        return False
    paused, _ = is_paused(who, default_persona(who))
    return paused


def _owner_who():
    from rouh.tenancy import Tenancy

    return Tenancy().only_person()


def stage_section(brief: str, who=None) -> str:
    """What a run of gene therapy is told about the trial stage: the stage, the one line that says trials are
    paused (the build goes on as before trials existed), or "" for a run that only runs a trial. Never an
    error: a pause that cannot be read is no pause, and nothing about it can stop a build."""
    if BY_HAND in brief:
        return ""
    try:
        if build_paused(who if who is not None else _owner_who()):
            return PAUSED_STAGE
    except Exception:  # noqa: BLE001 - a trial is never worth a build
        log.exception("trials: could not read whether testing is paused")
    return STAGE


def by_hand_brief(t: dict, name: str) -> str:
    link = f"/evolution/trials/{t['number']}"
    return "\n".join([
        f"‹Owner› asked for a review: a made-up person, {name}, tries {t['job_name'] or t['subject'] or t['page'] or 'a page of Rouh'} the "
        f"way a real person would, with this goal: \"{t['goal']}\". {BY_HAND} It is a report for ‹owner› to read "
        "and decide on: change no code, commit nothing, and fix nothing, whatever the tester finds.",
        "",
        f"1. Stand up a test world with `./e2e.sh serve`, or one from `./e2e.sh serve --list` that has what "
        f"{t['page'] or 'the page'} needs, and note its address, sign-in and process id.",
        f"2. Run `rouh-trial run --review --trial {t['number']} --url http://127.0.0.1:<port>{t['page'] or '/'} --user <its "
        "sign-in> --password <its password>` from your checkout. It drives the browser as "
        f"{name} and asks Rouh's tester at every step. Wait for it to finish, however long it takes.",
        "3. Stop the world by its process id.",
        f"4. In your last message say, in two plain sentences, whether {name} managed it and what tripped them up, "
        f"give the review's page, {link}, and say that nothing is fixed until ‹owner› chooses what on that page.",
    ])


async def run_by_hand(who, *, persona_id: str = "", goal: str = "", page: str = "", subject: str = "",
                      gene: str = "", again: int | None = None, job_no=None) -> dict:
    """A trial the person asked for ("trial this page with Boris", or Run trial again on a trial's page):
    queued here, and run by a run that stands a test world up for it."""
    import asyncio

    from rouh import nightly_feature, owner

    if again:
        was = await asyncio.to_thread(one, who, again)
        persona_id = persona_id or was["persona"]
        goal, page, subject, gene = goal or was["goal"], page or was["page"], subject or was["subject"], gene or was["gene"]
        job_no = job_no or was.get("job")
    if job_no:
        j = await asyncio.to_thread(_job, who, job_no)
        goal, page, gene = goal or j.goal, page or j.page, gene or j.gene
        job_no = j.number
    page = str(page or "").strip()
    if not page and gene:
        page = await asyncio.to_thread(page_of_gene, gene)
        if not page:
            raise Refused(f"The gene {gene} has no page of its own: say the address to begin at.")
    if page and not page.startswith("/"):
        page = "/" + re.sub(r"^[a-z]+://[^/]+/?", "", page, flags=re.I)
    if not goal:
        raise Refused("Say what the person is trying to do there, in one sentence, as they would put it.")
    if not page:
        raise Refused("Say where the trial begins: a page's address in Rouh, or the gene whose page it is.")
    # A trial the owner asked for in their own words is a review: a report to read, never fixed by itself.
    t = await asyncio.to_thread(lambda: start(who, persona_id=persona_id, goal=goal, page=page, subject=subject,
                                              gene=gene, job_no=job_no, mode="review"))
    name = t["persona_name"]
    try:
        if nightly_feature.hooks.start is None:
            raise RuntimeError("Rouh's runs are not ready")
        agent = await asyncio.to_thread(nightly_feature.engine, who)
        got = await nightly_feature.hooks.start(
            brief=owner.say(by_hand_brief(t, name), who), title=f"Trial {t['number']}: {name} tries {t['job_name'] or t['subject'] or 'a page'}",
            preset="improve_myself", agent=agent, use=nightly_feature.USE, org_id=str(who.org_id),
            one_fields={"browser_port": nightly_feature._free_port()})
    except Exception as exc:  # noqa: BLE001 - said, and the trial says why it never ran
        log.exception("trial %s could not be started", t["number"])
        await asyncio.to_thread(broken, who, t["number"], f"Its run could not be started: {exc}")
        raise Refused(f"The trial could not be started ({str(exc).strip().rstrip('.') or type(exc).__name__}).") from None
    run = str(got.get("id") or "")
    await asyncio.to_thread(lambda: _m().Trial.objects.filter(**_whose(who), number=t["number"]).update(run_id=run))
    return {**t, "run_id": run, "said": f"Review {t['number']} is starting: {name} will try {t['job_name'] or t['subject'] or 'it'}. "
                                         f"It takes a few minutes. Nothing is fixed from it until you choose what."}


__all__ = ["BRIEF", "DEFAULT_PERSONA", "GUIDANCE", "HOW_BAD", "MATCH_USE", "NotFound", "Paused", "Refused", "SKIPPED",
           "STAGE", "PAUSED_STAGE", "USE", "build_paused", "paused_all", "pause_state", "set_paused", "is_paused",
           "broken", "counts", "persona_read", "record", "reopen", "sighting", "default_persona", "finish", "listing", "one", "owner_said",
           "persona", "personas", "problem", "problems", "run_by_hand", "screen_key", "set_default_persona",
           "stage_section", "start", "step", "testers", "tester_read", "add_tester", "edit_tester", "remove_tester",
           "draft_tester", "jobs", "job", "edit_job", "set_verdict", "say", "feedback_text", "VERDICTS", "MODES",
           "fix_chosen", "chosen"]
