"""The Creator Rouh's releases of Rouh's code: the pointer every other Rouh updates itself to.

Task 140, step 140-18 (11 November 2026). A release is not every commit of main. It is a commit
that has run on the Creator Rouh - the maker's own, where Rouh's code is made and which pushes
each checked change to rouh-core's main (guard/rouh_guard/upstream.py) - for at least a day, with
nothing put back and its checks passed. This module decides that, by itself, and moves rouh.land's
pointer (``POST /mac/code/release``) forward, at most once a day; nobody approves each release
(Petar, 11 November 2026). Every Rouh reads the pointer (``rouh/code_update.py``).

How a release is chosen (``candidate``):

* **Seen running.** Every look (``code_update.Watch``, every half hour) writes down the commit
  the protected core says runs now (``seen.jsonl`` in ``code-release/`` in the data folder).
* **An undo point of a change** (``kind`` "change"), whose checks passed (the frozen security
  checks and Rouh's own, `guard/rouh_guard/checks.py`), that the doctor never put back.
* **A day.** It went live at least ``LIVE_FOR`` ago, and every commit seen running since then
  contains it: nothing put it back, by the doctor or by a press of Put back. The looks must
  cover the day, with no gap longer than ``GAP``: a day this Rouh was not running is not a day it
  ran.
* **Public.** It is on rouh-core's main, as the protected core keeps it fetched into /code
  (``refs/upstream/heads/main``), so every Rouh can download it.
* **Forward only.** It contains the release before it.

The newest such point is the release. Its notes are the subjects of the commits since the release
before, in plain words with the task numbers taken off (``notes``).

The request is signed with this Rouh's daily key, as its relay requests are (`relay._signed_post`),
and rouh.land takes it only from a Rouh whose registry id it lists as a release maker.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

log = logging.getLogger("rouh.code_release")

#: How long a change must have run on the Creator Rouh before it is a release.
LIVE_FOR = float(os.environ.get("ROUH_RELEASE_LIVE_FOR", str(24 * 3600)))
#: The longest gap between two looks that still counts as running throughout.
GAP = float(os.environ.get("ROUH_RELEASE_GAP", str(3 * 3600)))
#: At most one publish a day.
EVERY = float(os.environ.get("ROUH_RELEASE_EVERY", str(20 * 3600)))
UPSTREAM = "refs/upstream/heads/main"
KEEP_SEEN = 10 * 86400
MOST_NOTES = 12


def folder() -> Path:
    from .config import config

    return Path(os.environ.get("ROUH_CODE_RELEASE_DIR") or os.path.join(config.data_dir, "code-release"))


def _code() -> Path:
    from .code_update import code_dir

    return code_dir()


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(_code()), capture_output=True, text=True,
                          timeout=120, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})


def _contains(newer: str, older: str) -> bool:
    """Whether commit `newer` has `older` in its history (or is it)."""
    return bool(newer and older) and _git("merge-base", "--is-ancestor", older, newer).returncode == 0


def _state() -> dict:
    try:
        got = json.loads((folder() / "state.json").read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(**fields) -> dict:
    s = {**_state(), **fields}
    folder().mkdir(parents=True, exist_ok=True)
    tmp = folder() / "state.tmp"
    tmp.write_text(json.dumps(s, indent=1, ensure_ascii=False))
    tmp.replace(folder() / "state.json")
    return s


# --- seen running --------------------------------------------------------------------------------


def seen() -> list[dict]:
    rows = []
    with contextlib.suppress(OSError):
        for line in (folder() / "seen.jsonl").read_text().splitlines():
            with contextlib.suppress(ValueError):
                row = json.loads(line)
                if isinstance(row, dict) and row.get("commit"):
                    rows.append(row)
    return rows


def observe(commit: str, now: float | None = None) -> None:
    """Write down that `commit` runs now; the log is kept for ten days."""
    now = now or time.time()
    rows = [r for r in seen() if now - float(r.get("at") or 0) < KEEP_SEEN]
    rows.append({"at": round(now), "commit": commit})
    folder().mkdir(parents=True, exist_ok=True)
    tmp = folder() / "seen.tmp"
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    tmp.replace(folder() / "seen.jsonl")


def ran_throughout(commit: str, since: float, now: float, looks: list[dict]) -> str:
    """"" when every look from `since` to `now` saw code containing `commit`, with no gap longer
    than GAP; else why not, in a few words."""
    after = sorted((r for r in looks if float(r["at"]) >= since), key=lambda r: float(r["at"]))
    if not after:
        return "not seen running since it went live"
    times = [since] + [float(r["at"]) for r in after] + [now]
    if max(b - a for a, b in zip(times, times[1:])) > GAP:
        return "not seen running for part of the day"
    for r in after:
        if r["commit"] != commit and not _contains(r["commit"], commit):
            return f"put back at {dt.datetime.fromtimestamp(float(r['at']), dt.timezone.utc):%d %b %H:%M} UTC"
    return ""


# --- the choice ----------------------------------------------------------------------------------


def candidate(points: list[dict], published: str, now: float | None = None,
              looks: list[dict] | None = None) -> tuple[dict | None, str]:
    """(the undo point to release, "") or (None, why there is none)."""
    now = now or time.time()
    looks = seen() if looks is None else looks
    up = _git("rev-parse", "--verify", "-q", UPSTREAM).stdout.strip()
    if not up:
        return None, "rouh-core's main is not fetched here"
    why = "nothing newer than the release has run a whole day yet"
    for p in sorted(points, key=lambda p: -float(p.get("at") or 0)):
        commit = str(p.get("commit") or "")
        if published and (commit == published or _contains(published, commit)):
            return None, why
        if p.get("kind") != "change" or not (p.get("checked") or {}).get("passed") or p.get("doctored"):
            continue
        if now - float(p.get("at") or 0) < LIVE_FOR:
            continue
        if not _contains(up, commit):
            why = f"{commit[:12]} is not on rouh-core's main"
            continue
        if published and not _contains(commit, published):
            why = f"{commit[:12]} does not contain the release before it"
            continue
        said = ran_throughout(commit, float(p["at"]), now, looks)
        if said:
            why = f"{commit[:12]} was {said}"
            continue
        return p, ""
    return None, why


_SKIP = re.compile(r"^(Step number:|Merge |Revert \"Merge|fixup!|squash!)", re.I)
_TASK = re.compile(r"\s*\((?:[^()]*\b(?:task|step|night)\b[^()]*)\)\s*$", re.I)
_NIGHT = re.compile(r"^Night \d+ \([^)]*\):\s*", re.I)


def notes(since: str, commit: str) -> list[str]:
    """What is new from `since` to `commit`, one plain line a change, newest first."""
    if not since:
        return ["The first release that a Rouh can update itself to."]
    r = _git("log", "--no-merges", "--format=%s", f"{since}..{commit}")
    lines: list[str] = []
    for subject in r.stdout.splitlines():
        if not subject.strip() or _SKIP.match(subject):
            continue
        text = _NIGHT.sub("", _TASK.sub("", subject)).strip().rstrip(".")
        text = text[:1].upper() + text[1:]
        if len(text) > 290:
            text = text[:287].rstrip() + "..."
        if text and text not in lines:
            lines.append(text)
    if len(lines) > MOST_NOTES:
        lines = lines[:MOST_NOTES] + [f"And {len(lines) - MOST_NOTES} smaller changes"]
    return lines or ["Small fixes"]


# --- publishing ----------------------------------------------------------------------------------


def published() -> dict:
    """The release rouh.land serves now, or {} for none."""
    from . import code_update

    try:
        return code_update.newest(fresh=True)
    except code_update.Refused:
        return {}


def publish(point: dict, since: str) -> dict:
    """POST /mac/code/release, signed with this Rouh's daily key in the relay client's format (the key
    in the body, the four X-Rouh headers). Not `relay._signed_post`, which asks the first run's
    Connected choice: the Creator Rouh is older than that question, and rouh.land judges it by its
    registry id alone."""
    import httpx

    from . import relay
    from .site import url as site_url

    user = relay.owner()
    if user is None:
        raise RuntimeError("this Rouh has no owner yet")
    me, _row = relay._identity(user)
    live = dt.datetime.fromtimestamp(float(point["at"]), dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {"v": 1, "public_key": me["public"], "commit": point["commit"], "live_since": live,
               "notes": notes(since, point["commit"]),
               "checks": {"passed": (point.get("checked") or {}).get("passed"), "point": point.get("n")}}
    url = os.environ.get("ROUH_CODE_RELEASE_PUBLISH") or site_url("/mac/code/release")
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    got = httpx.post(url, content=raw, timeout=30, headers={
        "Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Rouh releases",
        **relay._signed(me["seed"], "POST", url, raw)})
    try:
        answer = got.json() or {}
    except ValueError:
        answer = {}
    if got.status_code >= 400:
        raise RuntimeError(str(answer.get("error") or f"rouh.land answered {got.status_code}"))
    return answer


def once(now: float | None = None, *, force: bool = False) -> dict:
    """One look: write down what runs, and once a day publish the newest release there is."""
    from . import guardface

    now = now or time.time()
    try:
        status = guardface.ask("status")
        points = guardface.ask("points").get("points") or []
    except (guardface.Refused, guardface.Unavailable) as exc:
        return _save(said=f"The protected core did not answer: {exc}", looked_at=now)
    cur = ((status.get("code") or {}).get("point") or {}).get("commit") or ""
    if cur:
        observe(cur, now)
    s = _state()
    if not force and now - float(s.get("tried_at") or 0) < EVERY:
        return s
    rel = published()
    point, why = candidate(points, str(rel.get("commit") or ""), now)
    if point is None:
        return _save(tried_at=now, said=f"No new release: {why}.", looked_at=now)
    try:
        got = publish(point, str(rel.get("commit") or ""))
    except Exception as exc:  # noqa: BLE001 - said, and tried again tomorrow
        log.warning("the release could not be published: %s", exc)
        return _save(tried_at=now, said=f"The release of {point['commit'][:12]} could not be published: {exc}",
                     looked_at=now)
    log.info("released %s (undo point %s) on rouh.land", point["commit"][:12], point.get("n"))
    with contextlib.suppress(Exception):
        from . import code_update

        code_update.newest(fresh=True)
    return _save(tried_at=now, looked_at=now, released={"commit": point["commit"], "at": now, "point": point.get("n")},
                 said=f"Released {point['commit'][:12]} ({got.get('state') or 'published'}).")


def public() -> dict:
    s = _state()
    looks = seen()
    return {"said": s.get("said") or "", "released": s.get("released"), "tried_at": s.get("tried_at"),
            "seen_since": looks[0]["at"] if looks else None}
