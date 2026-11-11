"""Rouh's updates: this Rouh's own code brought to the newest release of Rouh, with its own changes kept.

Task 140, step 140-18 (11 November 2026). Petar: "one time click that updates your code from our
repo", and "an option to stay in sync with the creator rouh ... people that will be happy to just
ride along". Since 23 October 2026 a Rouh's code is its own (``/code``, a git repository its genes
and the Rouh itself change, each change through its protected core, guard/README.md), and nothing
brought newer code to it after its first start. This is that, for whoever wants it.

**The choice** (Anatomy, Meta, Changes, the card "Rouh's updates"; the ``update_rouh`` tool):

* ``ride`` - "Ride along": this Rouh takes each new release by itself, at a quiet moment (no turn
  in progress, no run going, no deploy waiting), at most once a day. The default.
* ``press`` - "Update when I press": nothing comes in until the person presses "Update to the
  newest Rouh", which shows the version they have, the newest, and a short list of what is new.
* ``own`` - "My own path": this Rouh never asks for releases by itself; the button still works.

A Rouh on its own (Independent, 140-13) asks nobody anything by itself, so it never rides along and
never looks for a release until its person presses a button here.

**A release** is a checked boundary on the shared main branch of rouh-it/rouh-core, after its
changes have run for a day on the early-test Rouhs. Collaborators publish on that branch too.

**An update** takes each released change in order (``code_evolution.py``). Untouched files are
copied exactly without model spend. A frontier model rebuilds any change whose files differ,
and proves its purpose against this Rouh. Database and security changes always need frontier
checks, a protected rehearsal or a failing-before/passing-after security proof, respectively.
Each accepted change is a protected undo point. Waiting changes and dependants stay in the ledger.

**After the restart.** A change that goes live starts Rouh again, which cuts off whatever started it,
so the update is written down first (``state.json``, ``pending``) and the next start reads what the
protected core did with it and says so once in General: "Rouh updated itself to ..." or "Rouh did
not update ... because ..." (``reconcile``).

A Rouh with no protected core beside it (on a server, in a test world) shows the choice and the
releases, and says that its code is updated by land.sh there.
"""
from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import fcntl
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("rouh.code_update")

ROUTE = "/anatomy/meta/changes"
MODES = {"ride": "Ride along", "press": "Update when I press", "own": "My own path"}
DEFAULT_MODE = "ride"
#: As rouh-code-install: release tools a Rouh never runs. Left out only where this Rouh's code has
#: none of them already (a whole checkout keeps its own).
LEFT_OUT = ("guard", "mac", ".github", "deploy/container")
#: A change of these may need libraries the base does not have.
LIBRARIES = ("uv.lock", "one/requirements.txt")
MOST = 400 * 1024 * 1024
UA = "rouh-code-update/1"
#: How often the ride along looks, and how long a release read from rouh.land is kept.
EVERY = float(os.environ.get("ROUH_CODE_UPDATE_EVERY", "1800"))
FRESH = float(os.environ.get("ROUH_CODE_UPDATE_FRESH", "3600"))
#: At most one update by itself in this long ("at most once a day", with room for the clock).
DAY = float(os.environ.get("ROUH_CODE_UPDATE_DAY", str(20 * 3600)))
#: A release that changes the database waits for a nightly copy younger than this.
COPY_AT_MOST = float(os.environ.get("ROUH_CODE_UPDATE_COPY_AGE", str(26 * 3600)))
#: A run whose row has not moved for this long is not counted as going (a run left behind).
RUN_STALE = 6 * 3600
#: How long an update handed to the protected core is waited for before it is called lost.
PENDING_MOST = 3 * 3600
KEEP_BACKUPS = 3
TRAILER = "Rouh-release"
#: This start of Rouh: an update it began is its own until it starts again (a pid may come back).
THIS_START = uuid.uuid4().hex


class Refused(ValueError):
    """An update that is not done, with the reason as a sentence."""


# --- where things are ------------------------------------------------------------------------


def code_dir() -> Path:
    return Path(os.environ.get("ROUH_APP_DIR") or Path(__file__).resolve().parents[1])


def folder() -> Path:
    from .config import config

    return Path(os.environ.get("ROUH_CODE_UPDATE_DIR") or os.path.join(config.data_dir, "code-update"))


def site() -> str:
    return (os.environ.get("ROUH_SITE_URL") or "https://rouh.land").strip().rstrip("/")


def release_url() -> str:
    return os.environ.get("ROUH_CODE_RELEASE_URL") or f"{site()}/mac/code/release.json"


def tarball_url(commit: str) -> str:
    return (os.environ.get("ROUH_CODE_TARBALL")
            or "https://codeload.github.com/rouh-it/rouh-core/tar.gz/{commit}").format(commit=commit)


def _read(path: Path) -> dict:
    try:
        got = json.loads(path.read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


_state_lock = threading.Lock()


def state() -> dict:
    return _read(folder() / "state.json")


def _change(**fields) -> dict:
    with _state_lock:
        s = state()
        for k, v in fields.items():
            if v is None:
                s.pop(k, None)
            else:
                s[k] = v
        _write(folder() / "state.json", s)
        return s


def mode() -> str:
    got = str(_read(folder() / "settings.json").get("mode") or "")
    return got if got in MODES else DEFAULT_MODE


def set_mode(who, value: str) -> str:
    _admin(who)
    if value not in MODES:
        raise Refused("Choose Ride along, Update when I press or My own path.")
    _write(folder() / "settings.json", {"mode": value, "at": time.time(), "by": getattr(who, "name", "") or ""})
    return value


def _admin(who) -> None:
    if who is None:
        raise Refused("Sign in first.")
    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this Rouh changes how its code is updated.")


def on_its_own() -> bool:
    """Whether this Rouh chose to be on its own (Independent): it then asks nobody by itself."""
    from . import relay

    try:
        return relay.chose_connected() is False
    except Exception:  # noqa: BLE001 - a Rouh with no owner yet is not on its own
        return False


# --- git -------------------------------------------------------------------------------------


def _git(*args: str, cwd: Path, check: bool = False, timeout: float = 600) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(cwd), capture_output=True, text=True,
                       timeout=timeout, env={**os.environ, "GIT_TERMINAL_PROMPT": "0",
                                             "GIT_AUTHOR_NAME": "Rouh", "GIT_AUTHOR_EMAIL": "rouh@localhost",
                                             "GIT_COMMITTER_NAME": "Rouh", "GIT_COMMITTER_EMAIL": "rouh@localhost"})
    if check and r.returncode:
        raise Refused(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return r


def _out(*args: str, cwd: Path) -> str:
    return _git(*args, cwd=cwd, check=True).stdout.strip()


def base(code: Path | None = None) -> dict:
    """Which release this Rouh's code came from: {"release": its commit of rouh-core, "local": the
    commit here that holds exactly that release's files, "how"}; or {"how": "history"} for a whole
    copy of Rouh's history (the Creator Rouh, a server checkout), or {"how": "unknown"}."""
    code = code or code_dir()
    if not (code / ".git").exists():
        return {"how": "unknown"}
    log_ = _git("log", "--format=%H%x1f%(trailers:key=" + TRAILER + ",valueonly,separator=)%x1e", "HEAD",
                cwd=code)
    for rec in log_.stdout.split("\x1e"):
        sha, _, said = rec.strip().partition("\x1f")
        said = said.strip()
        if sha and re.fullmatch(r"[0-9a-f]{40}", said):
            return {"how": "update", "release": said, "local": sha}
    installed = _read(code / ".git" / "rouh-installed.json")
    roots = _git("rev-list", "--max-parents=0", "HEAD", cwd=code).stdout.split()
    if re.fullmatch(r"[0-9a-f]{40}", str(installed.get("commit") or "")) and len(roots) == 1:
        return {"how": "install", "release": installed["commit"], "local": roots[0]}
    if _git("rev-list", "--count", "HEAD", cwd=code).stdout.strip() not in ("", "0", "1"):
        return {"how": "history"}
    return {"how": "unknown"}


def _own_commits(code: Path, local: str) -> int:
    from . import code_evolution

    r = _git("rev-list", "--no-merges", "--invert-grep", "--grep=^Rouh-master-change:",
             "--grep=^Rouh-release:", f"{local}..HEAD", cwd=code)
    master = {row["master"] for row in code_evolution.ledger().get("changes", [])
              if row.get("status") in code_evolution.TAKEN and row.get("local") == row["master"]}
    return len(set(r.stdout.split()) - master) if r.returncode == 0 else 0


# --- the release, from rouh.land ---------------------------------------------------------------


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            got = json.loads(r.read(512 * 1024))
    except urllib.error.HTTPError as e:
        try:
            said = json.loads(e.read()).get("error") or ""
        except ValueError:
            said = ""
        if e.code == 404:
            raise Refused("rouh.land has no release of Rouh's code yet.") from None
        raise Refused(f"rouh.land answered {e.code}{': ' + said if said else ''}.") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise Refused(f"rouh.land could not be reached ({getattr(e, 'reason', e)}).") from None
    if not isinstance(got, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(got.get("commit") or "")):
        raise Refused("rouh.land's answer named no release.")
    return got


def newest(*, fresh: bool = False) -> dict:
    """The newest release, as rouh.land says it, kept for an hour. Raises Refused."""
    s = state()
    kept = s.get("release") or {}
    if not fresh and kept and time.time() - float(s.get("checked_at") or 0) < FRESH:
        return kept
    try:
        got = _get_json(release_url())
    except Refused as exc:
        _change(checked_at=time.time(), check_error=str(exc))
        raise
    got = {k: got.get(k) for k in ("commit", "version", "released_at", "live_since", "notes", "recent")}
    _change(release=got, checked_at=time.time(), check_error="")
    return got


def _day(iso: str) -> str:
    try:
        when = dt.datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return ""
    return f"{when.day} {when:%B %Y}"


def label(commit: str, release: dict | None = None) -> str:
    """A release as a person reads it: "Rouh of 11 November 2026 (fff88ca6)"."""
    if not commit:
        return "unknown"
    for r in (release or {}).get("recent") or []:
        if r.get("commit") == commit and _day(r.get("released_at") or ""):
            return f"Rouh of {_day(r['released_at'])} ({commit[:8]})"
    return f"Rouh {commit[:8]}"


def whats_new(release: dict, since: str, most: int = 12) -> list[str]:
    """The notes of every release newer than `since`, newest first, at most `most` lines."""
    lines: list[str] = []
    for r in release.get("recent") or [release]:
        if r.get("commit") == since:
            break
        for n in r.get("notes") or []:
            if n not in lines:
                lines.append(str(n))
    if len(lines) > most:
        lines = lines[:most] + [f"and {len(lines) - most} more"]
    return lines


# --- what the page and the tool say -------------------------------------------------------------


def _guard() -> bool:
    from . import guardface

    return guardface.here()


def makes_releases() -> bool:
    try:
        from .base_patches import makes_releases as m

        return bool(m())
    except Exception:  # noqa: BLE001 - only a label
        return False


def public(who, *, look: bool = False) -> dict:
    """Everything the card and the tool say: the choice, the version here, the newest, what is new,
    whether it can be taken now and why not, and how the last update went."""
    if who is None:
        raise Refused("Sign in first.")
    s = state()
    b = base()
    from . import code_evolution

    evolution = code_evolution.shown()
    own = on_its_own()
    out = {"mode": mode(), "modes": MODES, "admin": bool(getattr(who, "is_admin", False)), "on_its_own": own,
           "guard": _guard(), "how": b.get("how"),
           "busy": s.get("busy") or ({"step": "working through the released changes"} if s.get("continue_update") else None),
           "pending": s.get("pending") or None,
           "last": s.get("last") or None, "checked_at": s.get("checked_at"), "check_error": s.get("check_error") or "",
           "makes_releases": False, "ride": s.get("ride") or None, "ledger": evolution}
    if b.get("how") == "history" and makes_releases():
        out["makes_releases"] = True
        from . import code_release

        out["publishing"] = code_release.public()
    rel: dict = {}
    if look or not own:
        try:
            rel = newest(fresh=look)
        except Refused as exc:
            out["check_error"] = str(exc)
    else:
        rel = s.get("release") or {}
    if rel:
        try:
            code_evolution.observe(rel, b)
        except Refused as exc:
            out["check_error"] = str(exc)
        evolution = code_evolution.shown()
        out["ledger"] = evolution
    here = evolution.get("through") or b.get("release") or ""
    own_base = b.get("local") or evolution.get("installed")
    out["current"] = {"commit": here, "label": label(here, rel) if here else "",
                      "own_commits": _own_commits(code_dir(), own_base) if own_base else 0}
    if rel:
        out["newest"] = {"commit": rel["commit"], "label": label(rel["commit"], rel),
                         "released_at": rel.get("released_at"), "live_since": rel.get("live_since")}
        if evolution.get("installed"):
            out["up_to_date"] = here == rel["commit"] and not evolution["waiting"]
        elif b.get("how") == "history":
            has = _git("cat-file", "-e", f"{rel['commit']}^{{commit}}", cwd=code_dir()).returncode == 0
            out["up_to_date"] = has and _git("merge-base", "--is-ancestor", rel["commit"], "HEAD",
                                               cwd=code_dir()).returncode == 0
        else:
            out["up_to_date"] = here == rel["commit"] and not evolution["waiting"]
        out["whats_new"] = [] if out["up_to_date"] else whats_new(rel, here)
    out["why_not"] = why_not(b, rel, s)
    return out


def said(got: dict) -> str:
    """`public`'s answer as a few plain sentences, for the update_rouh tool."""
    parts = [f"How updates come: {MODES.get(got.get('mode'), '?')}."]
    cur, new = got.get("current") or {}, got.get("newest") or {}
    if got.get("makes_releases"):
        parts.append("This Rouh makes Rouh's releases; " + ((got.get("publishing") or {}).get("said") or "none yet."))
    if cur.get("label"):
        parts.append(f"This Rouh has {cur['label']}"
                     + (f", with {cur['own_commits']} change{'s' if cur['own_commits'] != 1 else ''} of its own"
                        if cur.get("own_commits") else "") + ".")
    if new:
        if got.get("up_to_date"):
            parts.append(f"That is the newest release, {new['label']}.")
        else:
            parts.append(f"The newest release is {new['label']}.")
            if got.get("whats_new"):
                parts.append("What is new: " + "; ".join(got["whats_new"]) + ".")
    elif got.get("check_error"):
        parts.append(f"The newest release is not known: {got['check_error']}")
    if got.get("busy"):
        parts.append(f"An update is on its way: {got['busy'].get('step') or 'starting'}.")
    elif got.get("why_not") and not got.get("up_to_date"):
        parts.append(f"An update cannot start now: {got['why_not']}")
    last = got.get("last") or {}
    if last:
        parts.append("Last time: " + note(last))
    return " ".join(parts)


def why_not(b: dict, rel: dict, s: dict | None = None) -> str:
    """Why an update cannot start now, as a sentence, or "" when it can."""
    s = s if s is not None else state()
    if s.get("busy") and _busy_alive(s["busy"]):
        return "An update is already on its way."
    if s.get("pending"):
        return "The last update is still with the protected core."
    if s.get("continue_update"):
        return "The update is working through the released changes."
    if not _guard():
        return ("This Rouh has no protected core beside it: it runs on a server, where its code is "
                "updated by land.sh.")
    from . import code_evolution

    if b.get("how") == "history" and not code_evolution.ledger().get("installed"):
        return "This Rouh needs its protected core's recorded starting version before it can take master changes."
    if b.get("how") not in ("install", "update", "history"):
        return "This Rouh's code does not say which release it came from, so it cannot be updated this way."
    if not rel:
        return "The newest release is not known yet."
    progress = code_evolution.shown()
    if rel.get("commit") == (progress.get("through") or b.get("release")) and not progress["waiting"]:
        return "This Rouh already has the newest release."
    return ""


def _busy_alive(busy: dict) -> bool:
    return busy.get("start") == THIS_START


# --- an update -----------------------------------------------------------------------------------

_run_lock = threading.Lock()


async def update(who, *, by: str = "a press") -> dict:
    """Start an update to the newest release, now, in the background. Raises Refused with why not."""
    if who is not None:
        _admin(who)
    rel = await asyncio.to_thread(newest, fresh=True)
    b = await asyncio.to_thread(base)
    reason = why_not(b, rel)
    if reason:
        raise Refused(reason)
    if not _run_lock.acquire(blocking=False):
        raise Refused("An update is already on its way.")
    _change(busy={"step": "starting", "since": time.time(), "start": THIS_START, "by": by})

    def go() -> None:
        try:
            _apply(rel, by)
        finally:
            _run_lock.release()

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, go)
    fut.add_done_callback(lambda f: asyncio.ensure_future(_after(f)))
    return {"said": f"Updating to {label(rel['commit'], rel)}. It takes a few minutes; Rouh starts again on it, "
                    "and says in General how it went.", "release": rel["commit"]}


async def _after(fut) -> None:
    with contextlib.suppress(Exception):
        fut.result()
    await tell()


def _step(text: str) -> None:
    s = state().get("busy") or {}
    _change(busy={**s, "step": text, "start": THIS_START})
    log.info("update: %s", text)


def _fail(rel: dict, by: str, said: str) -> None:
    log.warning("update to %s did not happen: %s", str(rel.get("commit"))[:12], said)
    ident = "fail-" + hashlib.sha256((str(rel.get("commit")) + said).encode()).hexdigest()[:20]
    previous = state().get("last") or {}
    _change(busy=None, pending=None, continue_update=None,
            retry_release=rel, retry_at=time.time() + 1800,
            last={"ok": False, "at": time.time(), "release": rel.get("commit"), "label": label(rel.get("commit", ""), rel),
                  "said": said, "by": by, "kept": [], "id": ident, "evolution_failure": True,
                  "told": previous.get("id") == ident and previous.get("told", False)})


def _apply(rel: dict, by: str) -> None:
    """One pass through the released changes. An outcome is always written."""
    work = folder() / "work"
    try:
        folder().mkdir(parents=True, exist_ok=True)
        lock = open(folder() / ".lock", "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        _fail(rel, by, f"another update holds its folder, or the folder cannot be written ({exc}).")
        return
    try:
        _apply_locked(rel, by, work)
    except Refused as exc:
        _fail(rel, by, str(exc))
    except Exception as exc:  # noqa: BLE001 - said in plain words, the details in the log
        log.exception("the update stumbled")
        _fail(rel, by, f"something went wrong while it was being prepared ({type(exc).__name__}: {str(exc)[:200]}).")
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        with contextlib.suppress(Exception):
            if work.exists() and not state().get("pending"):
                shutil.rmtree(work)


def _apply_locked(rel: dict, by: str, work: Path) -> None:
    from . import code_evolution

    code_evolution.advance(rel, by, work)


def _plain_refusal(said: str) -> str:
    said = said.strip()
    if not said:
        return "the protected core did not say why."
    if "What failed:" in said:
        return "it did not pass its checks. What failed:" + said.split("What failed:", 1)[1][:600].rstrip()
    return said[:600]


def _done(pending: dict, point: dict) -> None:
    if pending.get("master_change"):
        from . import code_evolution

        code_evolution.finish(pending, point)
        return
    code = code_dir()
    with contextlib.suppress(Exception):
        _git("update-ref", "refs/rouh/release", pending["local_release"], cwd=code)
    _change(busy=None, pending=None,
            last={"ok": True, "at": time.time(), "release": pending["release"], "label": pending["label"],
                  "from_label": pending.get("from_label") or "", "kept": pending.get("kept") or [],
                  "own": pending.get("own") or 0, "by": pending.get("by") or "", "point": (point or {}).get("n"),
                  "id": f"ok-{pending['commit'][:12]}", "told": False})


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read(MOST + 1)
    except (urllib.error.URLError, OSError) as e:
        raise Refused(f"the release could not be downloaded ({getattr(e, 'reason', e)}).") from None
    if len(data) > MOST:
        raise Refused("the release is larger than an update takes.")
    return data


def _unpack(data: bytes, into: Path, commit: str) -> None:
    """As rouh-code-install: GitHub's tarball of one commit, which must say it is that commit; its top
    folder taken off; nothing outside `into`, no links out."""
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError:
        raise Refused("the download is not a release of Rouh.") from None
    with tar:
        said = (tar.pax_headers or {}).get("comment", "")
        if said != commit:
            raise Refused(f"the download is not commit {commit[:12]} (it says {said[:12] or 'nothing'}).")
        members = []
        for m in tar.getmembers():
            parts = m.name.split("/", 1)
            if len(parts) < 2 or not parts[1]:
                continue
            rel = parts[1]
            if rel.startswith("/") or ".." in rel.split("/"):
                raise Refused(f"the download holds a path that climbs out ({rel[:80]}).")
            if m.issym() or m.islnk():
                target = os.path.normpath(os.path.join(os.path.dirname(rel), m.linkname))
                if m.linkname.startswith("/") or target.startswith(".."):
                    raise Refused(f"the download holds a link that points out ({rel[:80]}).")
            elif not (m.isfile() or m.isdir()):
                continue
            m.name = rel
            members.append(m)
        tar.extractall(into, members=members, filter="tar")


def _genes_of(work: Path, local: str, head: str, path: str) -> list[str]:
    """The genes of this Rouh's own commits that changed `path`, by their Gene: lines; else what the
    gene map says owns it; else "a change of this Rouh's own"."""
    r = _git("log", "--no-merges", "--format=%(trailers:key=Gene,valueonly,separator=%x1f)", f"{local}..{head}",
             "--", path, cwd=work)
    genes = []
    for line in r.stdout.splitlines():
        for g in line.split("\x1f"):
            g = g.strip()
            if g and g not in genes:
                genes.append(g)
    if genes:
        return [f"the gene {g}" for g in genes[:4]]
    with contextlib.suppress(Exception):
        from .genes import owners

        found = owners.owners_of(path)
        if found:
            return [f"a change of its own to the gene {x}" for x in list(found)[:2]]
    return ["a change of its own"]


def _libraries(work: Path) -> None:
    tool = Path(os.environ.get("ROUH_GUARD_BIN", "/opt/rouh-guard/bin")) / "rouh-code-install"
    if not tool.is_file():
        raise Refused("the release needs libraries, and this Rouh's protected core cannot add them.")
    r = subprocess.run(["python3", "-I", str(tool), "--extra-only", str(work)], capture_output=True, text=True,
                       timeout=1800)
    if r.returncode:
        said = (r.stderr or r.stdout).strip().splitlines()
        raise Refused("the libraries the release needs could not be added"
                      + (f": {said[-1][:300]}" if said else "."))


def _backup(code: Path, database_changes: bool) -> dict:
    """The whole of /code as a git bundle, and the newest nightly copy of the database kept aside,
    each in code-update/backups, the newest few kept."""
    keep = folder() / "backups"
    keep.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{time.time_ns() % 1000000:06d}"
    bundle = keep / f"code-{stamp}.bundle"
    _git("bundle", "create", "-q", str(bundle), "--all", cwd=code, check=True)
    out = {"code": str(bundle), "database": "", "database_at": None}
    from .management.commands.export_rouh import newest_nightly

    nightly = newest_nightly()
    age = time.time() - os.path.getmtime(nightly) if nightly else None
    if database_changes and (age is None or age > COPY_AT_MOST):
        bundle.unlink(missing_ok=True)
        raise Refused("the release changes the database, and its newest copy is "
                      + ("missing" if age is None else f"{int(age // 3600)} hours old")
                      + ". It waits for tonight's copy rather than change the database without a fresh one.")
    if nightly:
        copy = keep / f"database-{stamp}.dump"
        shutil.copyfile(nightly, copy)
        os.chmod(copy, 0o600)
        out.update(database=str(copy), database_at=os.path.getmtime(nightly))
    for prefix in ("code-", "database-"):
        old = sorted(p for p in keep.iterdir() if p.name.startswith(prefix))
        for p in old[:-KEEP_BACKUPS]:
            p.unlink(missing_ok=True)
    return out


# --- after a restart -----------------------------------------------------------------------------


def reconcile() -> None:
    """What the protected core did with an update this Rouh handed it before it started again."""
    from . import code_evolution

    code_evolution.reconcile_ledger()
    s = state()
    p = s.get("pending")
    if not p:
        if s.get("busy") and not _busy_alive(s["busy"]):
            _change(busy=None)
        return
    if s.get("busy") and _busy_alive(s["busy"]):
        return
    from . import guardface

    try:
        st = guardface.ask("status")
    except (guardface.Refused, guardface.Unavailable):
        if time.time() - float(p.get("at") or 0) > PENDING_MOST:
            _fail({"commit": p["release"]}, p.get("by") or "", "the protected core never answered about it.")
        return
    cur = ((st.get("code") or {}).get("point") or {})
    if cur.get("commit") == p["commit"]:
        _done(p, cur)
        return
    for ev in st.get("events") or []:
        if ev.get("commit") == p["commit"] and ev.get("what") in ("refused", "waiting"):
            _fail({"commit": p["release"], "released_at": ""}, p.get("by") or "", _plain_refusal(str(ev.get("said") or "")))
            return
    if p["commit"][:12] in str(st.get("busy") or ""):
        return
    if time.time() - float(p.get("at") or 0) > PENDING_MOST:
        _fail({"commit": p["release"]}, p.get("by") or "",
              "the protected core never made it live, and did not say why. Meta, Changes lists what it did.")


def note(last: dict) -> str:
    """The line said in General about the last update."""
    if last.get("evolution_failure"):
        return ("Rouh could not finish this update: " + str(last.get("said") or "the check could not finish")
                + ". Settings, Changes shows what came in and what is waiting. It will be tried again.")
    if "waiting" in last:
        text = "Rouh's update: " + last["said"]
        for status, label in (("copied", "Copied exactly"), ("adapted", "Adapted for this Rouh")):
            purposes = [r["purpose"] for r in last.get("came_in", []) if r["status"] == status]
            if purposes:
                text += " " + label + ": " + "; ".join(purposes[:5])
                if len(purposes) > 5:
                    text += f"; and {len(purposes) - 5} more"
                text += "."
        for row in last["waiting"]:
            text += (" Urgent security update" if row.get("urgent") else " Waiting") + ": " + row["purpose"] + ": " + row["reason"] + "."
        return text + " Settings, Changes has the full record. Waiting changes are tried again."
    if last.get("ok"):
        text = f"Rouh updated itself to {last.get('label') or 'the newest release'}"
        if last.get("from_label"):
            text += f", from {last['from_label']}"
        text += "."
        own = int(last.get("own") or 0)
        if own:
            text += f" Your Rouh's own {own} change{'s' if own != 1 else ''} came along."
        for k in last.get("kept") or []:
            who = " and ".join(k.get("genes") or ["a change of its own"])
            text += (f" {who[:1].upper()}{who[1:]} stayed as it was in {k['file']}: the new release changed the "
                     "same lines, so that file kept your version and did not take the release's.")
        return text + " Anatomy, Meta, Changes has an undo point for it."
    said = str(last.get("said") or "").strip()
    if said and not said.endswith((".", "!", "?")):
        said += "."
    return f"Rouh did not update itself to {last.get('label') or 'the newest release'}: {said} Nothing was changed."


_say = None


def wire(say) -> None:
    """How a line reaches General (`runtime._say_in_chat`), given at start."""
    global _say
    _say = say


async def tell() -> None:
    """Say the last update's outcome in General once, and as a notice when it did not happen."""
    last = state().get("last") or {}
    if not last or last.get("told"):
        return
    from . import conversations, notices

    text = note(last)
    if _say is not None:
        with contextlib.suppress(Exception):
            await _say(conversations.GENERAL, text)
    if not last.get("ok"):
        with contextlib.suppress(Exception):
            await notices.notify(title="Rouh did not update itself", body=text[:900], link=ROUTE, link_label="Changes",
                                 kind="rouh", key=f"code-update-{last.get('id')}")
    _change(last={**last, "told": True})


# --- the ride along ------------------------------------------------------------------------------


def quiet() -> str:
    """Why now is not a quiet moment, or ""."""
    from . import answers_now

    if answers_now.in_progress():
        return "an answer is in progress"
    if answers_now.holding():
        return "a restart is waiting"
    with contextlib.suppress(Exception):
        from .runtime import Turns

        if Turns.anything_running():
            return "a turn is in progress"
    with contextlib.suppress(Exception):
        from . import runs

        now = time.time()
        for row in runs._live_runs(now):
            if row.ended_at is None and runs.status_of(row) in ("running", "starting") and \
                    now - float(row.updated_at or row.started_at or 0) < RUN_STALE:
                return "a run is going"
    return ""


async def ride_once() -> str:
    """One look of the ride along; what it did, as a few words, kept for the page."""
    said = await _ride_once()
    _change(ride={"at": time.time(), "said": said})
    return said


async def _ride_once() -> str:
    await asyncio.to_thread(reconcile)
    await tell()
    s = state()
    continuation = s.get("continue_update")
    retry = s.get("retry_release") if time.time() >= float(s.get("retry_at") or 0) else None
    if continuation or retry:
        urgent = any(r.get("urgent") for r in (s.get("last") or {}).get("waiting", []))
        if continuation or (urgent and mode() != "own" and not on_its_own()) or (mode() == "ride" and not on_its_own()):
            if not s.get("pending") and not quiet() and _run_lock.acquire(blocking=False):
                rel = continuation["release"] if continuation else retry
                by = continuation.get("by", "riding along") if continuation else "retrying a waiting change"
                try:
                    await asyncio.to_thread(_apply, rel, by)
                finally:
                    _run_lock.release()
                await tell()
                return "continued the update"
    if mode() != "ride" or on_its_own() or not _guard():
        return "not riding"
    s = state()
    if time.time() - float(s.get("auto_at") or 0) < DAY:
        return "already today"
    try:
        rel = await asyncio.to_thread(newest)
    except Refused:
        return "no release"
    b = await asyncio.to_thread(base)
    from . import code_evolution

    try:
        await asyncio.to_thread(code_evolution.observe, rel, b)
    except Refused as exc:
        _change(check_error=str(exc))
        return "waiting: " + str(exc)
    if why_not(b, rel, s):
        return "nothing to take"
    busy = quiet()
    if busy:
        log.info("a newer Rouh is waiting for a quiet moment (%s)", busy)
        return "waiting: " + busy
    _change(auto_at=time.time())
    try:
        await update(None, by="riding along")
    except Refused as exc:
        return f"refused: {exc}"
    return "started"


class Watch:
    """The ride along, the Creator Rouh's releases, and the note after a restart."""

    def __init__(self, every: float = EVERY) -> None:
        self.every = every
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop(), name="code_update")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None

    async def _loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                if _guard():
                    await ride_once()
                if makes_releases():
                    from . import code_release

                    await asyncio.to_thread(code_release.once)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad look never stops the next
                log.exception("the look for a newer Rouh stumbled; continuing")
            await asyncio.sleep(min(self.every, 30) if state().get("pending") or state().get("continue_update") else self.every)
