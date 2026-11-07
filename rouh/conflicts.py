"""Merge conflicts between a job's work and main, as a record and as a decision.

On 20 September 2026 three jobs finished good work and pushed none of it,
because the rebase onto main failed. One of them (5f932c8) had already landed
from an earlier attempt and collided with itself; the other two collided with
runs that landed while they worked. Every one of those was recoverable and
nobody was told, which is the failure this module and ``land.sh`` exist to end.

``land.sh`` is the ladder, and since 18 October 2026 Rouh climbs all of it
itself. Petar's standing instruction is that Rouh resolves merge clashes and he
is not asked; that day he was asked eight times and not one of them needed him
(card 1684). The rungs, in order:

1. Already landed, compared by patch: nothing to do.
2. One at a time, under one lock.
3. Rebase with memory (rerere), and a generated file - the workspace task list,
   which Rouh makes again out of its database - is always taken as main has it
   and made again afterwards, never merged and never asked about.
4. Handed back to the worker that wrote the code, which knows what it meant.
5. The worker gone: a fresh run redoes the change from main (``redo_brief``).
6. Twice failed, or both sides rewrote the same thing: **Rouh merges it
   itself.** A Claude Code merge pass is given both diffs, both sides' commit
   messages and the run's brief, writes the version that keeps both intents,
   and the usual checks prove it before it lands (``rouh/merge_pass.py``).
7. Only when the two sides truly want opposite things - one deletes or reverses
   what the other adds, and both cannot hold - is the person asked, and then
   the question carries Rouh's recommendation (``recommend``).

A replay that stops without a single colliding file is not a clash at all: on
6 to 18 October 2026 Rouh's own saver asked Petar three times about a "clash"
whose only cause was a rebase with no committer name. ``land.sh`` reports that
as an error, and a record with no files is never put to anybody.

**The record.** When a landing collides, ``land.sh`` writes one JSON file
holding both diffs, both sides' commit messages, the conflicting files, the
name of the pre-resolution branch and a single plain-English line stating the
question. It is written twice on purpose: once beside the run, which is where
somebody looking at the run will find it, and once in a directory Rouh
watches, which is how a question reaches the person. Nothing is ever
discarded: the pre-resolution branch is kept for every attempt, so whatever
happens next, the work as the job wrote it is still a `git checkout` away.

A record from a scratch repository - a test's checkout under the system's
temporary folder, or under a run's own ``.one/tmp`` - is never written into the
real landing directory (``scratch_repo``). On 18 October 2026 six of them were:
the one program's old tests, brought back from history by a nightly run, landed
into ``/srv/rouh-land`` and reached Petar as real decisions.

**The four choices.** When the person is asked at all, they are never asked to
write free text. They get exactly four, each one a command ``land.sh`` already
knows how to run:

1. Take mine, redo on top      the job's side wins, replayed over main
2. Take main's, drop mine      main's side wins where the two collide
3. Merge both, you decide how  back to the worker, to keep both intents
4. Park it, ask me later       nothing moves, and nothing is lost

They carry enough with them that the decision never needs the conversation it
came from: the question, both sides and the files travel with the conflict, so
picking a number is the whole of the person's part. That is why they can be
answered by a click, by a key, by voice or from Telegram, all four reaching the
same place.

Nothing here imports anything but the standard library, because ``land.sh``
runs it as a command in a checkout that may be any repository at all::

    PYTHONPATH=<the rouh checkout> python3 -m rouh.conflicts write < parts.json
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable, Mapping

# Compatibility for land.sh running from a checkout before its next deploy.
from .merge_pass import MERGE_PICK, read_merge_pick, write_merge_pick

log = logging.getLogger("rouh.conflicts")

#: Where the lock and the records live, for both users that land work: the
#: ``rouh`` user, which runs Rouh's own crew, and ``assistant``, which runs
#: every run of the one program. Neither is in the other's group, so the
#: directory is made sticky and world-writable, the way ``/tmp`` is: anybody may
#: add a file, nobody may remove anybody else's. What is in it is diffs of the
#: person's own repositories on the person's own single-user server.
LAND_DIR = os.environ.get("ROUH_LAND_DIR") or "/srv/rouh-land"

#: The landing directory of the server itself: the one Rouh reads its questions
#: out of. A test that reaches it reaches Petar, so nothing from a scratch
#: repository is ever written there (`scratch_repo`).
REAL_LAND_DIR = "/srv/rouh-land"

#: The one file every landing takes an exclusive lock on, so two jobs never
#: land at the same moment and the second rebases onto a main that has stopped
#: moving. ``land.sh`` holds it for the whole fetch, rebase, prove, push
#: sequence and releases it on every exit path, including failure.
LOCK_NAME = "land.lock"

#: How many seconds a landing waits for that lock before giving up. Long enough
#: for a job ahead of it to rebase, prove itself in a browser and push; short
#: enough that a lock nobody released is a failure somebody is told about rather
#: than a job that never ends.
LOCK_WAIT = 900

#: A record's states. ``handback`` is a conflict the worker that wrote the code
#: is fixing itself, which is the common case and never reaches the person.
#: ``waiting`` is the only one that turns anything red.
WAITING = "waiting"
HANDBACK = "handback"
ANSWERED = "answered"
PARKED = "parked"
LANDED = "landed"
STATES = (WAITING, HANDBACK, ANSWERED, PARKED, LANDED)


# ---------------------------------------------------------------------------
# The four choices
# ---------------------------------------------------------------------------

#: Exactly four, in this order, for ever. The number is the whole of the
#: person's answer, so it is the key hint on the button, the digit they press,
#: the word they say and what Telegram asks for.
#:
#: ``how`` is what ``land.sh --answer`` does with it. ``words`` is what a
#: spoken answer may sound like; the model is told the four labels, and
#: :func:`choice_from_words` is the net under a person who says "take mine"
#: rather than "one".
CHOICES: tuple[dict[str, Any], ...] = (
    {
        "n": 1,
        "label": "Take mine, redo on top",
        "how": "mine",
        "tone": "good",
        "means": ("Your job's side wins wherever the two collide, replayed on top of "
                  "main. Everything on main that your job did not touch stays."),
        "words": ("take mine", "mine", "keep mine", "my side", "my version",
                  "redo on top", "redo mine", "one"),
    },
    {
        "n": 2,
        "label": "Take main's, drop mine",
        "how": "theirs",
        "tone": "plain",
        "means": ("Main's side wins wherever the two collide. Your job's side of those "
                  "hunks goes, and the branch that holds it is kept."),
        "words": ("take main", "take mains", "take main's", "main", "main's", "mains",
                  "drop mine", "theirs", "two"),
    },
    {
        "n": 3,
        "label": "Merge both, you decide how",
        "how": "both",
        "tone": "plain",
        "means": ("Back to the worker, to reconcile the two intents by hand and prove it "
                  "again in a browser before it may push."),
        "words": ("merge both", "both", "keep both", "merge them", "you decide",
                  "you decide how", "three"),
    },
    {
        "n": 4,
        "label": "Park it, ask me later",
        "how": "park",
        "tone": "warn",
        "means": ("Nothing moves. The work stays on its own branch, the record is kept, "
                  "and the question comes back whenever you ask for it."),
        # "not now" is deliberately not here: anything with "not" in it is read
        # as a refusal rather than a choice, which is the right way round.
        "words": ("park it", "park", "later", "ask me later", "leave it", "four"),
    },
)

_BY_N = {c["n"]: c for c in CHOICES}


def choice(n: Any) -> dict[str, Any] | None:
    """One of the four, by its number. None for anything else."""
    try:
        return _BY_N.get(int(n))
    except (TypeError, ValueError):
        return None


def choices_for_speech() -> str:
    """The four, as one line to read out loud."""
    return ", ".join(f"{c['n']}, {c['label'].lower()}" for c in CHOICES)


_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4,
                 "first": 1, "second": 2, "third": 3, "fourth": 4}


def choice_from_words(said: str) -> int | None:
    """Which of the four somebody just said, or None when it is not one of them.

    The longest phrase wins, and what it matched is taken out of the sentence
    before anything shorter is looked for. That one rule is what makes "drop
    mine" choice 2 rather than an argument between "drop mine" and "mine": the
    label the person half-remembered is longer than the word inside it, so the
    label decides.

    A sentence with a refusal in it, or one that still names two different
    choices once the longest phrases are out, is not an answer. Coming back and
    asking again is cheap; the wrong answer is carried out at once, and nobody
    is asked a second time.
    """
    text = " " + re.sub(r"[^a-z0-9' ]+", " ", (said or "").lower()).strip() + " "
    text = re.sub(r"\s+", " ", text)
    if not text.strip():
        return None
    if re.search(r"\b(not|don'?t|never|rather than|instead of)\b", text):
        return None
    hits: set[int] = set()
    for match in re.finditer(r"\b([1-4])\b", text):
        hits.add(int(match.group(1)))
    # Four letters is the floor, because "mine", "main", "both" and "park" are
    # each the whole of an answer somebody would give, and each of them is four.
    phrases = sorted(
        ((phrase, int(c["n"])) for c in CHOICES for phrase in c["words"] if len(phrase) >= 4),
        key=lambda pair: len(pair[0]), reverse=True)
    phrases += sorted(((word, n) for word, n in _WORD_NUMBERS.items()),
                      key=lambda pair: len(pair[0]), reverse=True)
    for phrase, n in phrases:
        if f" {phrase} " in text:
            hits.add(n)
            text = text.replace(f" {phrase} ", " ")
    return hits.pop() if len(hits) == 1 else None


# ---------------------------------------------------------------------------
# Where the records are
# ---------------------------------------------------------------------------


def land_dir(cfg: Any = None) -> Path:
    """The directory holding the lock and the records."""
    return Path(getattr(cfg, "land_dir", None) or LAND_DIR)


def records_dir(cfg: Any = None) -> Path:
    return land_dir(cfg) / "conflicts"


def ensure_dir(path: Path) -> Path:
    """Make a directory two users can both write into, and say where it is.

    Sticky and world-writable, like ``/tmp``, and for the same reason: the two
    users that land work are in neither's group. Never raises: a directory that
    cannot be made is a record that is only written beside the run, which is
    still a record.
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        if path.stat().st_mode & 0o1777 != 0o1777:
            os.chmod(path, 0o1777)
    except OSError as exc:
        log.warning("could not prepare %s (%s)", path, exc)
    return path


def ensure_land_dir(cfg: Any = None) -> Path:
    """Make the directory both services land through, and the records inside it.

    Every level of it, not only the leaf: ``mkdir -p`` makes a parent with the
    umask's mode, and a parent at 0755 owned by root is a directory neither user
    that lands work can put a lock file in. Rouh runs as root and this is
    called when it starts, which is what makes the directory exist on a machine
    where the deploy has not made it yet.
    """
    base = land_dir(cfg)
    ensure_dir(base)
    ensure_dir(base / "conflicts")
    # And the lock file itself, made here rather than by whichever job lands
    # first. This kernel refuses to open another user's file for writing inside
    # a world-writable sticky directory (`fs.protected_regular`), so a lock file
    # created by one of the two users that land work would be a lock only that
    # user could take. Made by root, mode 0666, `land.sh` opens it for reading,
    # and flock needs nothing more than that.
    lock = base / LOCK_NAME
    try:
        if not lock.exists():
            lock.touch()
        os.chmod(lock, 0o666)
    except OSError as exc:
        log.warning("could not prepare the landing lock %s (%s)", lock, exc)
    return base


def is_real_land_dir(where: str | os.PathLike[str] | None = None, cfg: Any = None) -> bool:
    """Whether this landing directory is the server's own, the one questions reach Petar from."""
    base = Path(where) if where else land_dir(cfg)
    try:
        return os.path.realpath(base) == os.path.realpath(REAL_LAND_DIR)
    except (OSError, ValueError):
        return False


def _temp_roots() -> list[str]:
    roots = {"/tmp", "/var/tmp", "/dev/shm"}
    with contextlib.suppress(Exception):
        roots.add(tempfile.gettempdir())
    out = []
    for root in roots:
        with contextlib.suppress(OSError, ValueError):
            out.append(os.path.realpath(root).rstrip("/") or "/")
    return [r for r in out if r != "/"]


def scratch_repo(path: Any) -> bool:
    """Whether a repository is a scratch one: a test's, never real work.

    Under the system's temporary folders, or under a run's own scratch folder
    (``.one/tmp``, ``.rouh/tmp``, where a run keeps its throwaway checkouts).
    No real run works in either: one program runs are in ``/srv/one-runs/<id>``,
    Rouh's own jobs in its crew's worktrees and its saver in its data folder.
    """
    said = str(path or "").strip()
    if not said:
        return False
    try:
        real = os.path.realpath(said)
    except (OSError, ValueError):
        real = said
    for place in {said, real}:
        if "/.one/tmp/" in place + "/" or "/.rouh/tmp/" in place + "/":
            return True
        for root in _temp_roots():
            if place == root or place.startswith(root + "/"):
                return True
    return False


def run_landed_since(record: Mapping[str, Any], records: Iterable[Mapping[str, Any]]) -> bool:
    """Whether another record of the same run says its work landed after this one was written.

    `close_for_run` marks every record of a run landed the moment its work is
    on main, but a record written by an attempt that was still on its way, or
    a copy that missed the write, can go on saying ``waiting``. A run whose
    work is on main has nothing left for anybody to decide.
    """
    run = str(record.get("run") or "")
    if not run:
        return False
    at = float(record.get("at") or 0.0)
    for other in records:
        if other is record or str(other.get("run") or "") != run:
            continue
        if other.get("state") != LANDED:
            continue
        if float(other.get("landed_at") or other.get("changed_at") or 0.0) >= at:
            return True
    return False


def write_bytes(path: Path, body: str) -> bool:
    """Write a record file, even when somebody else made it. True when it landed.

    ``Path.write_text`` opens with ``O_CREAT``, and this kernel refuses that
    for a file another user made inside a world-writable sticky directory
    (``fs.protected_regular``, which is 2 on this machine). The landing
    directory is exactly such a directory, on purpose, because two users land
    work through it - and a record in it is written by whichever of them ran
    the job, while Rouh, which answers it, is root.

    Measured on the server on 22 September 2026: ``cf-a6aa24af-2`` said
    ``answered`` in the copy beside the run and ``waiting`` in the copy
    everything actually reads, because the second write had been refused with
    EACCES and swallowed. The orb went on drawing NEEDS YOU for three jobs that
    were over, and nothing could ever clear them.

    Opening a file that already exists **without** ``O_CREAT`` is allowed, so
    that is tried first and creating is the fallback.
    """
    data = body.encode("utf-8")
    why: OSError | None = None
    for flags in (os.O_WRONLY | os.O_TRUNC, os.O_WRONLY | os.O_CREAT | os.O_TRUNC):
        try:
            fd = os.open(path, flags, 0o664)
        except OSError as exc:
            why = exc
            continue
        try:
            written = 0
            while written < len(data):
                written += os.write(fd, data[written:])
        finally:
            os.close(fd)
        return True
    log.warning("could not write the conflict record to %s (%s)", path, why)
    return False


def read(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """One record, or None when it is not there or is not a record."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("id"):
        return None
    data["path"] = str(path)
    return data


def _mtime(path: str | os.PathLike[str]) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def freshest(record: Mapping[str, Any]) -> dict[str, Any]:
    """The newest copy of a record, and the copies it disagreed with brought up to date.

    A record is written in two places on purpose, and the two can disagree,
    because either write can fail: see :func:`write_bytes` for the one that did.
    A disagreement only ever costs anybody anything one way round - a copy that
    still says ``waiting`` about a question that has been answered - so that is
    the only one looked for, and it is looked for with a ``stat`` rather than a
    read, because this runs every three seconds over records that are tens of
    kilobytes each.

    Where the copies do disagree the newest wins and the others are written
    again from it, so the disagreement is settled once instead of on every
    sweep.
    """
    here = dict(record)
    if here.get("state") != WAITING:
        return here
    mine = _mtime(str(here.get("path") or ""))
    best, when = here, mine
    for place in here.get("paths") or []:
        if not place or _mtime(str(place)) <= when:
            continue
        other = read(place)
        if other is None or str(other.get("id")) != str(here.get("id")):
            continue
        best, when = other, _mtime(str(place))
    if best is here:
        return here
    log.info("the conflict record %s says %s in %s and %s in %s; the newer one wins",
             here.get("id"), here.get("state"), here.get("path"),
             best.get("state"), best.get("path"))
    healed = dict(best, path=here.get("path"), paths=here.get("paths"))
    return set_state(healed, str(best.get("state") or WAITING))


def read_all(where: str | os.PathLike[str] | None = None, *,
             cfg: Any = None) -> list[dict[str, Any]]:
    """Every record in the directory, newest first, each of them the newest copy of itself."""
    folder = Path(where) if where else records_dir(cfg)
    out: list[dict[str, Any]] = []
    try:
        names = sorted(folder.glob("*.json"))
    except OSError:
        return out
    for name in names:
        found = read(name)
        if found is not None:
            out.append(freshest(found))
    out.sort(key=lambda r: float(r.get("at") or 0.0), reverse=True)
    return out


def needs_a_person(record: Mapping[str, Any], *, now: float | None = None) -> bool:
    """Whether this record still needs the person. The one answer, for every reader.

    The orb, `what_is_running`, `check_tasks`, the decisions list and the
    notice all ask this and none of them works it out for itself, because a
    conflict that is pending in one of them and resolved in another is the
    fault this function exists to end.

    A record needs the person only while all of these are true:

    * **Its state is waiting** - not handed back to its own worker, merged by
      Rouh, answered, parked or landed.
    * **It carries no choice.** ``land.sh`` puts a record back to ``waiting``
      when even taking one side outright will not replay, and it clears the
      choice when it does, so the two can never be read as one.
    * **It names the files that collide.** A record with none is a replay
      that failed for some other reason - on 6 to 18 October 2026, a rebase
      with no committer name - and there is nothing in it for anybody to pick.
    * **It is not from a scratch repository** (`scratch_repo`): a test's
      checkout is never anybody's decision.
    * **Settling it would lose his own words** (`his_words`). Since 18 October
      2026 every other clash is Rouh's to settle, and ``land.sh`` settles it.

    Whether the run has landed since is asked by `waiting_now`, which has
    every record to hand.

    Never its age. Until 8 October 2026 a record older than seven days stopped
    needing anybody and its decision closed as withdrawn, with the work still
    off main; Petar that day: "Nothing expires due to time only. This question
    may be valid in 1 year." It waits until he answers or dismisses it. `now`
    is kept for callers that pass it.
    """
    return (record.get("state") == WAITING and not record.get("choice")
            and bool([f for f in (record.get("files") or []) if str(f).strip()])
            and not scratch_repo(record.get("repo") or record.get("cwd"))
            and his_words(record))


def his_words(record: Mapping[str, Any]) -> bool:
    """Whether settling this clash would lose words the person wrote himself, which is the one
    kind Rouh may not settle on its own (Petar, 18 October 2026).

    ``land.sh`` says so on the record (``needs_person`` "his_words") when the side Rouh would
    drop carries a commit of Rouh's saver - an edit he made in place, on a page or in a task's
    notes, which the saver carried to main (`rouh/saving.py`) - and the merge pass found no way
    to keep both. Every other clash is settled by ``land.sh`` itself: merged, or the side its
    merge pass recommends taken, with what was chosen and why in the job's report. A record
    written before that, waiting, is nobody's question."""
    return str(record.get("needs_person") or "") == "his_words"


def waiting_now(where: str | os.PathLike[str] | None = None, *, cfg: Any = None,
                now: float | None = None) -> list[dict[str, Any]]:
    """The records that are waiting on the person, newest first.

    Less any whose run has landed since it was written (`run_landed_since`).
    """
    every = read_all(where, cfg=cfg)
    return [r for r in every
            if needs_a_person(r, now=now) and not run_landed_since(r, every)]


def still_waiting(record_id: str, where: str | os.PathLike[str] | None = None, *,
                  cfg: Any = None) -> dict[str, Any] | None:
    """The record as it is on disk this moment, if it still needs the person, else None.

    Asked right before anything is said about a record, so a question that was
    answered, closed or landed in the seconds since the sweep is not said.
    """
    for record in waiting_now(where, cfg=cfg):
        if str(record.get("id")) == str(record_id):
            return record
    return None


def parked_now(where: str | os.PathLike[str] | None = None, *, cfg: Any = None,
               now: float | None = None) -> list[dict[str, Any]]:
    """The records the person parked, newest first.

    "Park it, ask me later" has to mean something later, or it is only a way of
    making a question disappear. A parked conflict turns nothing red and says
    nothing out loud - that is what parking it was for - but it is still on the
    answer to "how are my jobs", and answering it with a number still works,
    however long ago it was parked.
    """
    return [r for r in read_all(where, cfg=cfg) if r.get("state") == PARKED]


def write_record(record: Mapping[str, Any], *, beside: str | os.PathLike[str] | None = None,
                 cfg: Any = None) -> list[str]:
    """Write a record where it belongs, and say every path it reached.

    Twice, on purpose. Beside the run, because that is where somebody reading
    the run will look for it and where it survives everything but the checkout
    being removed; and in the directory Rouh watches, because that is how the
    question reaches the person. The same bytes both times.
    """
    data = dict(record)
    body = json.dumps(data, indent=1, sort_keys=True) + "\n"
    name = f"{data['id']}.json"
    written: list[str] = []
    places: list[Path] = []
    if beside:
        places.append(ensure_beside(beside) / name)
    if refused_here(data, cfg=cfg):
        log.warning("the conflict %s is from the scratch repository %s, so it was not written "
                    "into the real landing directory %s: a test never reaches the person",
                    data.get("id"), data.get("repo") or data.get("cwd"), records_dir(cfg))
    else:
        places.append(ensure_dir(records_dir(cfg)) / name)
    for place in places:
        if not write_bytes(place, body):
            continue
        with contextlib.suppress(OSError):
            os.chmod(place, 0o664)
        written.append(str(place))
    return written


def refused_here(record: Mapping[str, Any], *, cfg: Any = None) -> bool:
    """Whether this record must stay out of this landing directory: a scratch
    repository's record, and the server's own directory."""
    return (scratch_repo(record.get("repo") or record.get("cwd"))
            and is_real_land_dir(cfg=cfg))


def ensure_beside(path: str | os.PathLike[str]) -> Path:
    folder = Path(path)
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.warning("could not prepare %s (%s)", folder, exc)
    return folder


def every_copy(record: Mapping[str, Any], *, cfg: Any = None) -> list[str]:
    """Every file this record is, without naming one of them twice.

    Three sources, because leaving one out is how a question goes on being
    asked after it has been answered: the record's own ``paths``, which is
    where it was written; the path it was read from, which is where it is; and
    the landing directory, which is the one every reader reads. They are
    compared by their real paths, so the same file under two names - the
    landing directory is reached by both its own name and the one it had before
    the rename - is written once.
    """
    places = [str(p) for p in (record.get("paths") or []) if p]
    if record.get("path"):
        places.append(str(record["path"]))
    here = records_dir(cfg) / f"{record.get('id')}.json"
    if here.exists():
        places.append(str(here))
    out: list[str] = []
    seen: set[str] = set()
    for place in places:
        real = os.path.realpath(place)
        if real in seen:
            continue
        seen.add(real)
        out.append(place)
    return out


def set_state(record: Mapping[str, Any], state: str, *, cfg: Any = None,
              **fields: Any) -> dict[str, Any]:
    """Write a record again with a new state, everywhere it already is.

    Everywhere is the whole of the point: a pick made in the browser has to
    reach the copy beside the run and the copy in the landing directory, and
    the one it does not reach is the one that goes on saying a job needs a
    person (:func:`write_bytes`).
    """
    data = dict(record)
    data["state"] = state
    data.update(fields)
    data["changed_at"] = time.time()
    body = json.dumps({k: v for k, v in data.items() if k != "path"},
                      indent=1, sort_keys=True) + "\n"
    for place in every_copy(data, cfg=cfg):
        write_bytes(Path(place), body)
    return data


def close_for_run(run: str, sha: str, *, where: str | os.PathLike[str] | None = None,
                  cfg: Any = None) -> list[str]:
    """Mark every record of this run that is not yet landed as landed. The ids.

    A run whose work has reached main has nothing left for anybody to decide.
    A collision it was handed back and reconciled itself, or one it asked the
    person about and then reconciled anyway, is answered by the landing, and a
    record left saying ``waiting`` goes on turning the task red for a question
    with no answer left to give. Found on 24 September 2026: run cfd46c81's
    second attempt asked Petar which side wins, the run kept both sides itself
    and landed at bbc33ae, and the question stayed red.
    """
    closed: list[str] = []
    if not run:
        return closed
    for record in read_all(where, cfg=cfg):
        if str(record.get("run") or "") != run or record.get("state") == LANDED:
            continue
        set_state(record, LANDED, cfg=cfg, sha=sha, landed_at=time.time())
        closed.append(str(record.get("id") or ""))
    return closed


def answer(record: Mapping[str, Any], n: Any, *, cfg: Any = None) -> dict[str, Any] | None:
    """Record the person's pick. None when it is not one of the four."""
    picked = choice(n)
    if picked is None:
        return None
    return set_state(record, PARKED if picked["how"] == "park" else ANSWERED,
                     cfg=cfg, choice=picked["n"], choice_label=picked["label"],
                     choice_how=picked["how"], answered_at=time.time())


# ---------------------------------------------------------------------------
# The question, in one line
# ---------------------------------------------------------------------------


def _files_phrase(files: Iterable[str]) -> str:
    names = [f for f in files if f]
    if not names:
        return "the same work"
    short = [n.rsplit("/", 1)[-1] for n in names]
    if len(short) == 1:
        return short[0]
    if len(short) == 2:
        return f"{short[0]} and {short[1]}"
    return f"{short[0]}, {short[1]} and {len(short) - 2} more"


def _trim(text: str, limit: int = 90) -> str:
    said = re.sub(r"\s+", " ", (text or "").strip())
    # A commit here is written "rouh: the top bar is gone". The prefix is for
    # the log, not for a sentence somebody is read out loud.
    said = re.sub(r"^(rouh|jarvis|one|tests|deploy|docs)\s*:\s*", "", said)
    if len(said) <= limit:
        return said
    return said[: limit - 1].rstrip() + "…"


def question_for(record: Mapping[str, Any]) -> str:
    """The one plain-English line the person is asked, and nothing more.

    One sentence saying what collided, then one asking which side wins. It has
    to stand on its own: it goes on the orb, on the job's row, out loud and to
    Telegram, and in none of those places is the conversation it came from.
    Rouh's recommendation is not in it, because the decision card shows it in
    its own place; the spoken note and Telegram add it (`recommendation_line`).
    """
    files = list(record.get("files") or [])
    mine = _trim(str((record.get("mine") or {}).get("wrote") or "your job's change"))
    theirs = _trim(str((record.get("theirs") or {}).get("wrote") or "a change on main"))
    where = _files_phrase(files)
    if record.get("opposite_why"):
        asked = (f"Your job wrote {mine} and main has since {theirs}, and in {where} they "
                 f"want opposite things: {_trim(str(record['opposite_why']), 200)} Which side wins?")
    elif record.get("both_rewrote"):
        asked = (f"Both sides rewrote {where}. Keep your job's version, {mine}, "
                 f"or main's, {theirs}?")
    else:
        asked = (f"Your job wrote {mine} and main has since {theirs}, and they collide in "
                 f"{where}. Which side wins?")
    return asked


def recommendation_line(record: Mapping[str, Any]) -> str:
    """"Rouh recommends 1, take mine, redo on top: <why>", or "" when it has none."""
    picked = choice(record.get("recommend"))
    if picked is None:
        return ""
    why = _trim(str(record.get("recommend_why") or ""), 200).rstrip(".")
    return (f"Rouh recommends {picked['n']}, {picked['label'].lower()}"
            + (f": {why}." if why else "."))


def side_summary(side: Mapping[str, Any]) -> str:
    """What one side did, in a short plain-English line for the card."""
    messages = [m for m in (side.get("messages") or []) if str(m).strip()]
    if not messages:
        return "It did not say what it changed."
    if len(messages) == 1:
        return _trim(messages[0], 160)
    first = _trim(messages[0], 120)
    return f"{first} and {len(messages) - 1} more commit" + ("s" if len(messages) > 2 else "")


def files_line(side: Mapping[str, Any], shown: int = 3) -> str:
    names = [f for f in (side.get("files") or []) if f]
    if not names:
        return "no files"
    head = ", ".join(n.rsplit("/", 1)[-1] for n in names[:shown])
    return head if len(names) <= shown else f"{head}, +{len(names) - shown}"


# ---------------------------------------------------------------------------
# The card
# ---------------------------------------------------------------------------


def card(record: Mapping[str, Any]) -> dict[str, Any]:
    """The decision card, as a screen spec.

    One ``conflict`` block and nothing else. It is a block of its own rather
    than the ``html`` one because the four choices have to be pressed: an
    ``html`` block is drawn in a sandboxed frame that can reach neither this
    page nor the socket, so buttons inside one would be a picture of buttons.
    The page draws it with the number of each choice as its key hint, and the
    digits 1 to 4 answer it from the keyboard.
    """
    title = str(record.get("title") or "a job")
    sha = str(record.get("head") or "")[:7]
    target = str(record.get("target") or "main")
    return {
        "title": f"Conflict needs you: {title}",
        "description": (f"the merge conflict between {title} and {target}, "
                        "and the four ways out of it"),
        "blocks": [conflict_block(record)],
        "conflict_id": record.get("id"),
        "heading": f"{sha} into {target}" if sha else f"into {target}",
    }


def conflict_block(record: Mapping[str, Any]) -> dict[str, Any]:
    """The one block the card is made of."""
    mine = record.get("mine") or {}
    theirs = record.get("theirs") or {}
    sha = str(record.get("head") or "")[:7]
    target = str(record.get("target") or "main")
    return {
        "block": "conflict",
        "id": record.get("id"),
        "run": record.get("run"),
        "title": record.get("title") or "a job",
        "heading": f"{sha} into {target}" if sha else f"into {target}",
        "question": record.get("question") or question_for(record),
        "state": record.get("state") or WAITING,
        "choice": record.get("choice"),
        "pre_branch": record.get("pre_branch") or "",
        "sides": [
            {"heading": "Your job wrote", "text": side_summary(mine),
             "files": files_line(mine)},
            {"heading": "Main has since", "text": side_summary(theirs),
             "files": files_line(theirs)},
        ],
        "options": [{"n": c["n"], "label": c["label"], "tone": c["tone"],
                     "means": c["means"]} for c in CHOICES],
    }


def telegram_text(record: Mapping[str, Any], number: int | None = None) -> str:
    """The same question, for a phone, with the four answers spelled out, under its
    decision's number when it has one (`decision_numbers`)."""
    lines = [f"Conflict needs you{' (Decision ' + str(number) + ')' if number else ''}: "
             f"{record.get('title') or 'a job'}",
             "",
             str(record.get("question") or question_for(record))]
    if recommendation_line(record):
        lines.append(recommendation_line(record))
    lines.append("")
    mine, theirs = record.get("mine") or {}, record.get("theirs") or {}
    lines += [f"Your job wrote: {side_summary(mine)} ({files_line(mine)})",
              f"Main has since: {side_summary(theirs)} ({files_line(theirs)})",
              ""]
    for c in CHOICES:
        lines.append(f"{c['n']} {c['label']}")
    lines += ["", "Say or type the number. Nothing is lost either way: the work as the "
              f"job wrote it is kept on {record.get('pre_branch') or 'its own branch'}."]
    return "\n".join(lines)


def spoken_note(record: Mapping[str, Any]) -> str:
    """What Rouh is told to say, so the person hears the line and the four options."""
    return (
        f'[A job\'s work will not go onto main and it needs the person to decide: '
        f'"{record.get("title") or "a job"}". The question, in one line: '
        f'{record.get("question") or question_for(record)} '
        f'{recommendation_line(record) + " " if recommendation_line(record) else ""}'
        f'Their four choices are: {choices_for_speech()}. '
        f"Read them the question and the four choices, in one or two short sentences, and "
        f"say they can answer with the number or in words, and say what Rouh recommends when "
        f"there is a recommendation. When they answer, call "
        f"answer_conflict with the conflict {record.get('id')} and their choice. Do not "
        "choose for them and do not start anything else.]"
    )


# ---------------------------------------------------------------------------
# The tree, so the orb goes red
# ---------------------------------------------------------------------------


def tree_nodes(records: Iterable[Mapping[str, Any]], *, now: float | None = None
               ) -> list[dict[str, Any]]:
    """A waiting node for each conflict, in the shape the orb already draws.

    A job whose work will not land is not running any more, so nothing else
    would put it on the orb, and the orb is the one place the person is told
    something must not be left alone. The node is a worker node in the state
    ``waiting``, which the orb draws red and dashed with the words NEEDS YOU
    against it, and it carries the question so the card behind the node says
    the same thing the row on the task list says.

    One of these is a spike of its own only where the register has no run for
    the job. Where it does, the caller folds it onto that run's spike, because
    one job is one spike: see ``server._with_conflicts``.
    """
    now = time.time() if now is None else now
    out: list[dict[str, Any]] = []
    for record in records:
        rid = str(record.get("id") or "")
        if not rid:
            continue
        out.append({
            "id": f"conflict-{rid}",
            "kind": "worker",
            "state": WAITING,
            "label": str(record.get("title") or "a job")[:60],
            "what": "its work will not go onto main",
            "detail": str(record.get("question") or question_for(record))[:400],
            # The job this is about, so whoever draws the tree can tell that
            # this node and the run the register already holds are one job and
            # draw them as one spike rather than as two.
            "run": str(record.get("run") or ""),
            # No owner on purpose. That field says which of the two things on
            # this machine is running a job, and this job is not running: it has
            # finished and is waiting for one decision. "Run by Conflict" is not
            # a sentence.
            "opened_at": float(record.get("at") or now),
            "conflict": rid,
            "children": [],
        })
    return out


def task_row(record: Mapping[str, Any]) -> dict[str, Any]:
    """The job's row on the task list while its conflict waits.

    Red, with the one-line question on it. ``conflict`` is what turns the row
    red rather than amber: a job that has stopped to ask Claude Code's own
    question is waiting, and a job whose work will not land is waiting on a
    decision only the person can make, and the two must not look the same.
    """
    return {
        "id": record.get("run") or f"conflict-{record.get('id')}",
        "title": record.get("title") or "a job",
        "status": WAITING,
        "detail": str(record.get("question") or question_for(record))[:300],
        "asking": True,
        "conflict": record.get("id"),
        "card_id": record.get("card_id"),
        "options": [f"{c['n']} {c['label']}" for c in CHOICES],
    }


# ---------------------------------------------------------------------------
# What a worker is told when the conflict comes back to it
# ---------------------------------------------------------------------------

_HANDBACK = """Your work will not go onto `{target}`: a change landed there while you worked and it collides with yours. Nothing was pushed and nothing was lost. The work exactly as you wrote it is on the branch `{pre_branch}`, your checkout is back on `{branch}` with that same work on it, and no rebase is left half done.

This is yours to fix, not a person's, because you wrote the code and you know what you meant by it.

The question in one line: {question}

What your side did: {mine}
What landed on {target} while you worked: {theirs}

The files that collide:
{files}

Do this, in order, and do not skip a step:

1. Read both sides. `git log --oneline {base}..{target_ref}` is what landed while you worked, and `git diff {base}..{pre_branch}` is your own change whole.
2. `git fetch origin {target}` and then `git rebase {target_ref}`. It will stop at the same collision, with the conflict markers in the files in diff3 style, so each one shows your side, their side and the version you both started from.
3. **Reconcile the intent, not the text.** Both changes were wanted. Work out what each was for and write the version that does both, even where that means writing something neither side wrote. Never drop one side to make the other apply.
4. `git add` each file you resolved and `git rebase --continue`, until the rebase is done. rerere is on in this repository, so the resolution you write here is remembered and put back by itself if this ever collides the same way again.
5. **Prove it in a real browser before you push it.** Whatever you proved before, prove again now: the code you are about to push is not the code you proved, because it is your change reconciled with somebody else's. Drive the running app over Playwright MCP the way AGENTS.md says, and say in your last message what you saw on the screen.
6. Then run `./land.sh` again. Your work is on top of the newest `{target}` by then, so it pushes, and it deploys what it pushed. Read its last line: it is only done when it says both services are serving the commit.

Do not run `./land.sh` with your work still on the old base: it would replay into the same collision, and the second collision is taken out of your hands and merged by Rouh without the context you hold.

If the two really cannot both stand - if your change and the one on {target} are answers to the same question - say so plainly and run `./land.sh` anyway. The second collision goes to Rouh's own merge pass, which keeps both intents where both can hold, and only when they truly want opposite things is the person asked, with Rouh's recommendation.
"""


_HANDBACK_BOTH = """The person was asked which side of this conflict wins and they chose: **{label}**. {means}

The question they answered: {question}

Their answer means you reconcile the two sides yourself, keeping both intents. The work as you wrote it is on `{pre_branch}`; what landed on `{target}` while you worked is on `{target_ref}`.

Do this, in order:

1. Read both sides: `git diff {base}..{pre_branch}` for yours, `git log --oneline {base}..{target_ref}` for theirs.
2. `git reset --hard {pre_branch}` if your checkout is not already on that work, then `git fetch origin {target}` and `git rebase {target_ref}`. It stops at the collision with diff3 markers in the files.
3. Write the version that does both. Never drop one side to make the other apply. Then `git add` and `git rebase --continue`.
4. **Prove it in a real browser first.** The reconciled code is not the code you proved before. Drive the app over Playwright MCP and say what you saw.
5. Run `./land.sh` again.
"""


_REDO = """Reimplement a change whose own worker is gone.

A job finished this work and could not put it on `{target}`, because a change landed there while it ran and the two collide. Its worker is no longer there to reconcile them, so this is a fresh start from the current `{target}` rather than an untangling of a stale patch. That is the way that actually worked when this happened on 20 September 2026.

## What the old job was asked to do

{brief}

## What it wrote, in its own words

{messages}

## What landed on {target} in the meantime

{theirs}

## Its diff, as it wrote it

The whole of it is on the branch `{pre_branch}` in this repository, which is kept and is never deleted, so `git diff {base}..{pre_branch}` is the original change whole. The conflicting part of it:

```diff
{diff}
```

## What to do

Reimplement the change on top of the current `{target}`, as if writing it for the first time, knowing what is there now. Do not cherry-pick the old commits and do not resolve the old conflict: read what the change was for, read what is on `{target}` now, and write the version that belongs on top of it.

Then prove it yourself in a real browser over Playwright MCP the way AGENTS.md says, commit, and end with `./land.sh`. Say in your last message what you saw on the screen and what landed.
"""


def handback(record: Mapping[str, Any], *, chose: Mapping[str, Any] | None = None) -> str:
    """What the worker that wrote the code is told, so it can fix it itself.

    The whole point of rung four: the run does not end, and the conflict goes
    back to the one thing that still holds the context the code was written in.
    """
    mine, theirs = record.get("mine") or {}, record.get("theirs") or {}
    target = str(record.get("target") or "main")
    common = {
        "target": target,
        "target_ref": str(record.get("target_ref") or f"origin/{target}"),
        "base": str(record.get("base") or "")[:12] or f"origin/{target}",
        "branch": record.get("branch") or "your branch",
        "pre_branch": record.get("pre_branch") or "its own branch",
        "question": record.get("question") or question_for(record),
        "mine": side_summary(mine),
        "theirs": side_summary(theirs),
    }
    if chose is not None:
        return _HANDBACK_BOTH.format(label=chose.get("label"), means=chose.get("means"),
                                     **common)
    files = "\n".join(f"- `{f}`" for f in (record.get("files") or [])) or "- (none named)"
    return _HANDBACK.format(files=files, **common)


_ANSWERED = """The person has decided how your conflict with `{target}` is resolved. They chose **{n} {label}**. {means}

The question they were asked: {question}

Do this, in order, and nothing else:

1. Run `./land.sh --answer {n} --no-push` in `{cwd}`. It starts again from `{pre_branch}`, which holds your work exactly as you wrote it, replays it over the newest `{target}` with their side preferred where the two collide, and stops without pushing.
2. **Prove it in a real browser.** The code sitting in your checkout now is not the code you proved: it is one side of a collision taken outright. Drive the running app over Playwright MCP the way AGENTS.md says and look at the thing your change was about.
3. Then run `./land.sh` with nothing after it, which pushes it and then deploys it. Read its last line: a change that is on `{target}` and not live is not done.
4. Say in your last message what you saw on the screen, what landed and what was deployed.

If what you see in the browser is broken by the resolution, do not push it: say so plainly, say what is broken, and run `./land.sh` anyway so the choice goes back to the person rather than a broken main going live.
"""


def answered_note(record: Mapping[str, Any], n: Any) -> str:
    """What the worker is sent when the person has picked, so it carries it out.

    The pick goes back to the same worker rather than being carried out behind
    its back, because the worker is the only thing that can look at the result
    in a browser before it is pushed, and a resolution nobody looked at is the
    same guess this whole ladder exists to stop.
    """
    picked = choice(n)
    if picked is None:
        return ""
    if picked["how"] == "both":
        return handback(record, chose=picked)
    if picked["how"] == "park":
        return (f"The person parked this one for now: {record.get('question')} Nothing moves and "
                f"nothing is lost. Your work is on `{record.get('pre_branch')}`. Stop here and "
                "say that it is parked.")
    return _ANSWERED.format(
        n=picked["n"], label=picked["label"], means=picked["means"],
        question=record.get("question") or question_for(record),
        target=record.get("target") or "main",
        cwd=record.get("cwd") or "its checkout",
        pre_branch=record.get("pre_branch") or "its own branch",
    )


def redo_brief(record: Mapping[str, Any], *, brief: str = "") -> str:
    """What a fresh job is given when the worker that wrote the code is gone."""
    mine, theirs = record.get("mine") or {}, record.get("theirs") or {}
    messages = "\n".join(f"- {m}" for m in (mine.get("messages") or [])) or "- (it did not say)"
    theirs_said = "\n".join(f"- {m}" for m in (theirs.get("messages") or [])) or "- (nothing named)"
    return _REDO.format(
        target=record.get("target") or "main",
        brief=(brief or record.get("brief") or "It was not written down.").strip(),
        messages=messages,
        theirs=theirs_said,
        pre_branch=record.get("pre_branch") or "its own branch",
        base=str(record.get("base") or "")[:12] or "the merge base",
        diff=str(mine.get("diff") or "(the diff was not kept)")[:12000],
    )


# ---------------------------------------------------------------------------
# Building a record, which is what land.sh calls
# ---------------------------------------------------------------------------

#: How much of each side's diff is kept. Enough to read what collided, little
#: enough that a record stays a file somebody opens rather than one they grep.
DIFF_LIMIT = 40_000


def build(parts: Mapping[str, Any]) -> dict[str, Any]:
    """A record, from the git facts ``land.sh`` gathered.

    ``land.sh`` knows git and knows nothing about how a question is worded, so
    it hands over the facts and this decides what the person is asked. Both
    sides' diffs are capped here rather than in the shell, where cutting text
    by bytes would cut a UTF-8 character in half.
    """
    now = float(parts.get("at") or time.time())
    mine = dict(parts.get("mine") or {})
    theirs = dict(parts.get("theirs") or {})
    for side in (mine, theirs):
        side["diff"] = str(side.get("diff") or "")[:DIFF_LIMIT]
        side["messages"] = [str(m).strip() for m in (side.get("messages") or []) if str(m).strip()]
        side["files"] = [str(f) for f in (side.get("files") or []) if str(f).strip()]
        side["wrote"] = side.get("wrote") or (side["messages"][0] if side["messages"] else "")
    record: dict[str, Any] = {
        "id": str(parts.get("id") or f"cf-{int(now)}"),
        "at": now,
        "run": str(parts.get("run") or ""),
        "title": str(parts.get("title") or parts.get("run") or "a job"),
        "repo": str(parts.get("repo") or ""),
        "cwd": str(parts.get("cwd") or ""),
        "branch": str(parts.get("branch") or ""),
        "target": str(parts.get("target") or "main"),
        "target_ref": str(parts.get("target_ref") or ""),
        "base": str(parts.get("base") or ""),
        "head": str(parts.get("head") or ""),
        "attempt": int(parts.get("attempt") or 1),
        "pre_branch": str(parts.get("pre_branch") or ""),
        "files": [str(f) for f in (parts.get("files") or []) if str(f).strip()],
        "both_rewrote": bool(parts.get("both_rewrote")),
        "git_said": str(parts.get("git_said") or "")[:2000],
        "land": str(parts.get("land") or ""),
        "state": str(parts.get("state") or WAITING),
        "choice": None,
        "mine": mine,
        "theirs": theirs,
    }
    # What Rouh's own merge pass made of it (`rouh/merge_pass.py`): merged, or
    # the two want opposite things and this is what it recommends.
    # And what Rouh settled itself, or why this one is the person's after all: it would drop
    # his own words (`his_words`).
    for key in ("rouh_merge", "opposite_why", "recommend_why", "brief", "rouh_settled",
                "needs_person", "his_words_why"):
        if parts.get(key):
            record[key] = parts[key]
    if choice(parts.get("recommend")) is not None:
        record["recommend"] = int(parts["recommend"])
    record["question"] = str(parts.get("question") or "") or question_for(record)
    return record


def _cli(argv: list[str]) -> int:
    """``python3 -m rouh.conflicts write``, ``landed``, and the two queries land.sh makes.

    ``write`` reads the git facts as JSON on standard input, writes the record
    where it belongs and prints one JSON object saying where it went and what
    the person will be asked. ``handback`` prints what a worker is told.
    """
    what = argv[0] if argv else ""
    if what == "write":
        parts = json.load(sys.stdin)
        record = build(parts)
        paths = write_record(record, beside=parts.get("beside") or None)
        record["paths"] = paths
        if paths:
            # Written again so every copy carries the list of every copy: that
            # is what lets an answer from the browser reach the one beside the
            # run.
            set_state(record, record["state"], paths=paths)
        print(json.dumps({"id": record["id"], "paths": paths,
                          "question": record["question"],
                          "state": record["state"],
                          "handback": handback(record)}))
        return 0
    if what == "handback":
        record = read(argv[1]) if len(argv) > 1 else None
        if record is None:
            print("no such conflict record", file=sys.stderr)
            return 2
        picked = choice(argv[2]) if len(argv) > 2 else None
        print(handback(record, chose=picked))
        return 0
    if what == "landed":
        # The run landed: every question it raised on the way is closed.
        closed = close_for_run(argv[1] if len(argv) > 1 else "",
                               argv[2] if len(argv) > 2 else "")
        print(json.dumps({"closed": closed}))
        return 0
    if what == "question":
        record = read(argv[1]) if len(argv) > 1 else None
        if record is None:
            print("no such conflict record", file=sys.stderr)
            return 2
        print(record.get("question") or question_for(record))
        return 0
    print(__doc__ or "", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover - a command land.sh runs
    raise SystemExit(_cli(sys.argv[1:]))
