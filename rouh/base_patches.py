"""The nightly base patch job: patch-level fixes to what every Rouh runs on, found, built, checked, published.

Petar, 23 October 2026: "latest" for a Rouh means only patch-level fixes to what it runs on, and
those go in automatically; features, Rouh's own logic, its own security fixes and big library
upgrades reach a Rouh only as genes, because each user's Rouh changes its own code and a pull
must never overwrite it. So the base image (deploy/container/Dockerfile.base) holds no Rouh code,
and this job keeps it patched:

1. **Look** (here, on the Creator Rouh, the owner's Rouh, the one that makes Rouh's
   releases): `deploy/container/base_patch.py look` over the version list in main,
   ``deploy/container/base/``: every pinned Python library, the python:3.12.x-slim base, Node,
   Codex, Debian's security updates and Chromium's security releases (against the Debian packages
   of the published level, read out of its public image), and the database image (PostgreSQL
   counted major.patch, pinned by digest), patch-level only. Anything newer than a patch is
   listed and left for genes.
2. **Open a pull request on main**: the line's next level is committed on top of main, on a
   branch of its own, ``base-patch/<level>``, and pushed with the git key this Rouh already has.
   That push starts `.github/workflows/base.yml`, which opens the pull request (it shows every
   version that changes) and runs its tests on GitHub's Intel and Arm runners: it builds the base
   and the protected core (rouh-guard, guard/README.md) and runs the whole check on them with the
   newest commit of main that passed its tests (rouh-check: the base's parts, the headless browser
   over MCP, the frozen security checks and Rouh's own checks). Only if everything passes on both
   does it merge the pull request by moving main to exactly the commit it tested, tag that commit
   ``base-<level>``, and publish it as a signed release of format 2 that moves rouh.land's
   /mac/release/stable.json - "latest" - to it, with its records on the GitHub Release
   ``base-<level>``. A failed one stays open on GitHub, saying what failed.
3. **Say how it went.** This reads git only, as its key allows: the tag ``base-<level>`` is a
   published level; the ref ``refs/base-failed/<level>``, an annotated tag the workflow writes,
   is a failed one, with which job and step in its message. It watches for up to three hours, and
   again the next night, and a failure is told to the owner once: which update, which step, the
   pull request. A success is the Clockwork line and nothing else (Petar's N1: a notice only
   when he must act or know). The next night's look starts from main, which only ever holds a
   level that passed, so a failed level is tried again under the same number, on the same
   branch and the same pull request.

Until 30 October 2026 the version list lived on a branch of its own, ``base``, which this pushed
the next level onto; that branch is kept, read-only, as ``archive/base-branch-until-2026-10``.

How the owner is told: a notice from Rouh (`notices.notify`, on the screen and then the phone),
because this job is Rouh's own and not a worker's, and notify_owner is how a worker asks Rouh
to tell the owner. It is the same note, one step shorter.

**Library patches wait for the week.** Some libraries publish a patch nearly every day (boto3),
and each new level is a download on every Mac and an hour of build minutes. So a level is made
the same night for anything that matters for safety - a Debian security update (Chromium's
among them), a Python, Node, Codex or PostgreSQL patch - and otherwise once a week, with every
library patch gathered since.

**When.** A row of Rouh's own scheduled work, a reminder of kind ``server`` whose job is
``base_patch``, daily at 00:40 on the owner's clock (before the nightly runs), so it is on
Clockwork as "Rouh's own server job: Nightly base image patch check", paused, resumed or moved
there like the others. Only on the Creator Rouh, the one that makes Rouh's releases: one whose code
is a checkout of Rouh's release repository, or that says so with ``ROUH_MAKES_RELEASES=1``. No
Rouh instance (every other Rouh) has it.

**In the containers** (deploy/stack/compose.yml) the Rouh has no git key and no way to GitHub of its
own. There the Creator Rouh's protected core holds the one key that can write to rouh-core, and
only when its owner set ``ROUH_GUARD_UPSTREAM`` (guard/rouh_guard/upstream.py, task 161): it keeps
rouh-core's main, the base tags and the failure refs fetched into /code under ``refs/upstream/``,
which this reads, and a level is handed to it (``push_branch``), which checks it with the change
step's checks and pushes ``base-patch/<level>`` only if they pass and it changes nothing but the
version list. ``_through_guard`` says which way this Rouh goes.

Where a gene update will come in: never here. This job only patches the base; a Rouh's code
changes as a gene, a commit in that Rouh's own /code.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import pwd
import re
import subprocess
import time
from pathlib import Path

log = logging.getLogger("rouh.base_patches")

JOB = "base_patch"
TITLE = "Nightly base image patch check"
WHAT = ("Look for patch-level fixes to what Rouh runs on, build and check a new base with them, "
        "and publish it only if every check passes")
AT = "00:40"
#: Rouh's release repository, as a git remote names it.
RELEASE_REPO = re.compile(r"rouh-it/rouh-core(\.git)?$")
#: The version list, in main.
STATE = Path("deploy") / "container" / "base"
#: The branch each level is pushed on; base.yml opens its pull request.
BRANCH = "base-patch/{level}"
#: Where base.yml says a level failed (an annotated tag object: which job and step).
FAILED = "refs/base-failed/{level}"
#: rouh-core's main, as the Creator Rouh's protected core keeps it fetched into /code.
UPSTREAM = "refs/upstream/heads/main"
GITHUB = "https://github.com/rouh-it/rouh-core"
#: How long a pushed level is watched for its result before the next night takes it up.
WATCH_FOR = 3 * 3600
WATCH_EVERY = 300
#: How long library patches alone wait before they make a level of their own.
LIBRARIES_WAIT = 7 * 86400


def _cfg():
    from .config import config

    return config


def _app_dir() -> Path:
    return Path(os.environ.get("ROUH_APP_DIR") or getattr(_cfg(), "app_dir", "/var/www/rouh/app"))


def _git(*args, cwd: Path, timeout: float = 300) -> subprocess.CompletedProcess:
    # git reads who may use a checkout (safe.directory) and its keys from the home folder, which
    # a service started without HOME does not say; the user's own is taken then.
    home_dir = os.environ.get("HOME") or pwd.getpwuid(os.getuid()).pw_dir
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                          env=dict(os.environ, GIT_TERMINAL_PROMPT="0", HOME=home_dir))


def origin_url() -> str:
    r = _git("remote", "get-url", "origin", cwd=_app_dir(), timeout=20)
    return r.stdout.strip() if r.returncode == 0 else ""


def _through_guard() -> bool:
    """Whether this Rouh's git reaches rouh-core through its protected core (the Creator Rouh in
    the containers) rather than with a key of its own (the Creator Rouh on the server)."""
    from . import guardface

    if not guardface.here():
        return False
    try:
        got = guardface.ask("upstream", timeout=30)
        return bool(got.get("on") and got.get("ready"))
    except (guardface.Refused, guardface.Unavailable):
        return False


def makes_releases() -> bool:
    """Whether this Rouh is the one that makes Rouh's releases (see the module)."""
    said = os.environ.get("ROUH_MAKES_RELEASES", "").strip()
    if said:
        return said not in ("0", "no", "false")
    return _through_guard() or bool(RELEASE_REPO.search(origin_url()))


def ensure(who):
    """The owner's row for the nightly job, made once (daily at 00:40 on their clock), only on the
    Rouh that makes releases. A paused or moved row stays as it was left."""
    from . import clock, reminders

    if not makes_releases():
        return None
    got = reminders.server_row(who, JOB)
    if got is not None:
        return got
    with clock.person(who):
        first = reminders.moment_of(AT)
    row = reminders.add_server(who, job=JOB, title=TITLE, what=WHAT, first=first, repeat="daily")
    log.info("the nightly base patch check is scheduled for %s/%s at %s (reminder %s)",
             who.org_id, who.user_id, AT, row.id)
    return row


# --- the folder it works in ---------------------------------------------------------------------


def home() -> Path:
    data = Path(getattr(_cfg(), "data_dir", "") or os.environ.get("ROUH_DATA_DIR") or "/var/www/rouh/data")
    return data / "base-patches"


def _record_file() -> Path:
    return home() / "record.json"


def record() -> dict:
    try:
        return json.loads(_record_file().read_text())
    except (OSError, ValueError):
        return {}


def _keep(rec: dict) -> None:
    home().mkdir(parents=True, exist_ok=True)
    tmp = _record_file().with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True))
    tmp.replace(_record_file())


def _state() -> Path:
    """A clone of the release repository with main checked out, fetched afresh; the version list
    is its deploy/container/base/. Never the live checkout: nothing here touches the code Rouh
    runs from."""
    repo = home() / "repo"
    guarded = _through_guard()
    url = str(_app_dir()) if guarded else origin_url()
    if guarded:
        # The protected core fetches rouh-core first; main is then read out of /code.
        from . import guardface

        guardface.ask("upstream", fetch=True, timeout=300)
    if not url:
        raise RuntimeError("this Rouh's code has no origin to fetch main from")
    if not (repo / ".git").is_dir():
        home().mkdir(parents=True, exist_ok=True)
        r = _git("clone", "-q", "--no-checkout", "--filter=blob:none", url, str(repo), cwd=home(), timeout=600)
        if r.returncode:
            raise RuntimeError(f"could not clone {url}: {r.stderr.strip()[-300:]}")
    if guarded:
        _git("remote", "set-url", "origin", url, cwd=repo, timeout=20)
    r = _git("fetch", "-q", "origin", f"+{UPSTREAM if guarded else 'refs/heads/main'}:refs/remotes/origin/main", cwd=repo)
    if r.returncode:
        raise RuntimeError(f"main could not be fetched: {r.stderr.strip()[-300:]}")
    _git("checkout", "-q", "-B", "main", "origin/main", cwd=repo)
    _git("reset", "-q", "--hard", "origin/main", cwd=repo)
    _git("clean", "-qfd", cwd=repo)
    return repo


def _result(repo: Path, level: str) -> dict | None:
    """How base.yml left `level`, from git alone: None while it says nothing yet."""
    tag, failed = f"refs/tags/base-{level}", FAILED.format(level=level)
    if _through_guard():
        # Fetched into /code by the protected core, under refs/upstream/.
        code = _app_dir()
        tag, failed = tag.replace("refs/", "refs/upstream/", 1), failed.replace("refs/", "refs/upstream/", 1)
        r = _git("for-each-ref", "--format=%(objectname)\t%(refname)", tag, failed, cwd=code, timeout=20)
        refs = {line.split("\t")[1] for line in r.stdout.splitlines() if "\t" in line}
        if tag in refs:
            return {"level": level, "ok": True, "run": f"{GITHUB}/releases/tag/base-{level}"}
        if failed not in refs:
            return None
        words = _git("for-each-ref", "--format=%(contents)", failed, cwd=code, timeout=20).stdout
        return _failed(level, words)
    r = _git("ls-remote", "origin", tag, failed, cwd=repo, timeout=60)
    if r.returncode:
        return None
    refs = {line.split("\t")[1] for line in r.stdout.splitlines() if "\t" in line}
    if tag in refs:
        return {"level": level, "ok": True, "run": f"{GITHUB}/releases/tag/base-{level}"}
    if failed not in refs:
        return None
    _git("fetch", "-q", "origin", f"+{failed}:{failed}", cwd=repo, timeout=60)
    words = _git("for-each-ref", "--format=%(contents)", failed, cwd=repo, timeout=20).stdout
    return _failed(level, words)


def _failed(level: str, words: str) -> dict:
    what = next((ln[len("What failed: "):] for ln in words.splitlines() if ln.startswith("What failed: ")), "")
    run = next((ln[len("The run: "):] for ln in words.splitlines() if ln.startswith("The run: ")), "")
    pr = next((ln[len("The pull request: "):] for ln in words.splitlines() if ln.startswith("The pull request: ")), "")
    return {"level": level, "ok": False, "what": what, "run": run, "pr": pr}


def _failure_words(result: dict, plan: dict | None) -> str:
    steps = result.get("what") or "the build did not finish"
    what = ", ".join(f"{c['what']} {c['from'] or '(new)'} -> {c['to']}" for c in (plan or {}).get("changes", [])[:8])
    sec = len((plan or {}).get("security") or [])
    if sec:
        what = (what + "; " if what else "") + f"{sec} Debian security updates"
    return (f"Base {result.get('level')} was not published, so every Rouh stays on the base it has. "
            f"It was to bring: {what or 'what the last look found'}. What failed: {steps}. "
            f"Its pull request stays open: {result.get('pr') or _pulls(result.get('level', ''))}")


def _pulls(level: str) -> str:
    return f"{GITHUB}/pulls?q=is%3Apr+head%3Abase-patch%2F{level}"


async def _tell(who, rec: dict, level: str, words: str, link: str) -> None:
    """One notice for one failed level, never twice (Petar's N1)."""
    from . import notices

    told = set(rec.get("told") or [])
    if level in told:
        return
    await notices.notify(title=f"Base {level} failed its checks and was not published", body=words,
                         link=link, link_label="The pull request", kind="base_patch", key=f"base-patch-{level}",
                         phone_text=f"Rouh's base {level} failed its checks and was not published. {link}",
                         who=who)
    told.add(level)
    rec["told"] = sorted(told)[-40:]


async def _settle(who, rec: dict, repo: Path) -> str:
    """What became of the level pushed last, said once: "" while it is still being built."""
    pending = rec.get("pending")
    if not pending:
        return ""
    got = _result(repo, pending["level"])
    if got is None:
        if time.time() - pending.get("pushed_at", 0) < WATCH_FOR:
            return f"base {pending['level']} is still being built and checked"
        got = {"level": pending["level"], "ok": False, "run": "", "pr": _pulls(pending["level"]),
               "what": "it never said how it went, in three hours"}
    rec.pop("pending", None)
    if got.get("ok"):
        rec["published"] = {"level": got["level"], "at": time.time()}
        return f"base {got['level']} passed every check and is published"
    await _tell(who, rec, got["level"], _failure_words(got, pending.get("plan")),
                got.get("pr") or got.get("run") or _pulls(got["level"]))
    return f"base {got['level']} failed its checks and was not published; the owner was told"


def _report(repo: Path) -> str:
    """The level's plan.json in words, as base_patch.py says it."""
    r = subprocess.run(["python3", str(_app_dir() / "deploy" / "container" / "base_patch.py"), "report",
                        str(repo / STATE)], capture_output=True, text=True, timeout=60)
    return r.stdout if r.returncode == 0 else ""


def _urgent(plan: dict) -> bool:
    if plan.get("security"):
        return True
    return any(c["what"] in ("Python", "Node", "@openai/codex", "PostgreSQL") for c in plan.get("changes", []))


def _why(text: str) -> str:
    """What a failed script said, as the line that says why: a traceback's last line (the error,
    whole, with the path it names), never its frames or the tail of a frame cut in half."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return "it said nothing"
    if any(ln.startswith("Traceback") for ln in lines):
        return lines[-1][:300]
    return " ".join(lines)[-300:]


def _look(repo: Path) -> dict:
    script = _app_dir() / "deploy" / "container" / "base_patch.py"
    # The base image has no uv, so base_patch.py installs its pinned one here, once. Without it every
    # night from the move to the containers stopped on FileNotFoundError: '/usr/local/bin/uv'.
    env = dict(os.environ, ROUH_UV_DIR=str(home() / "uv"))
    r = subprocess.run(["python3", str(script), "look", str(repo / STATE), "--write", "--json"], capture_output=True,
                       text=True, timeout=1800, env=env)
    if r.returncode:
        raise RuntimeError(f"the look failed: {_why(r.stderr or r.stdout)}")
    return json.loads(r.stdout)


async def night(who, *, trying: bool = False) -> str:
    """Tonight's look, and the build it starts: the line Clockwork says it did."""
    rec = record()
    try:
        repo = await asyncio.to_thread(_state)
    except Exception as e:  # noqa: BLE001 - said on the row
        return f"could not look: {e}"
    settled = await _settle(who, rec, repo)
    _keep(rec)
    if rec.get("pending"):
        return settled
    if not (repo / STATE / "line.json").exists():
        return f"main has no base line in {STATE}: run the Base image workflow by hand with cut, such as 1.1"
    try:
        plan = await asyncio.to_thread(_look, repo)
    except Exception as e:  # noqa: BLE001
        return (settled + "; " if settled else "") + f"could not look: {e}"
    left = len(plan.get("left_for_genes") or [])
    later = f"{left} updates newer than a patch are left for genes" if left else "nothing is newer than a patch"
    if not plan.get("changed"):
        _git("checkout", "-q", "--", ".", cwd=repo)
        return (settled + "; " if settled else "") + f"nothing new for base {plan['from_level']}; {later}"
    last = (rec.get("published") or {}).get("at") or 0
    if not _urgent(plan) and time.time() - last < LIBRARIES_WAIT and not trying:
        _git("checkout", "-q", "--", ".", cwd=repo)
        n = len(plan.get("changes") or [])
        return ((settled + "; " if settled else "") +
                f"{n} library patches wait for this week's base; nothing urgent; {later}")
    words = "; ".join(f"{c['what']} {c['from'] or '(new)'} -> {c['to']}" for c in plan["changes"][:20])
    if plan.get("security"):
        words += ("; " if words else "") + f"{len(plan['security'])} Debian security updates"
    branch = BRANCH.format(level=plan["level"])
    _git("checkout", "-q", "-B", branch, cwd=repo)
    _git("add", "-A", "--", str(STATE), cwd=repo)
    r = _git("-c", "user.name=Rouh", "-c", "user.email=rouh@localhost", "commit", "-q", "-m",
             f"base {plan['level']}: {words[:180]}", "-m", _report(repo)[:4000], cwd=repo)
    if r.returncode:
        return f"could not commit base {plan['level']}: {r.stderr.strip()[-300:]}"
    why = await asyncio.to_thread(push_level, repo, branch)
    if why:
        return f"could not push base {plan['level']} for its pull request: {why}"
    rec["pending"] = {"level": plan["level"], "branch": branch, "pushed_at": time.time(), "plan": plan}
    # Each try of a level is told once if it fails, a level tried again included.
    rec["told"] = [t for t in rec.get("told") or [] if t != plan["level"]]
    _keep(rec)
    asyncio.ensure_future(_watch(who, plan["level"]))
    return ((settled + "; " if settled else "") +
            f"found {len(plan['changes'])} patch-level updates and {len(plan.get('security') or [])} Debian security "
            f"updates; base {plan['level']} is a pull request on main, being built and checked; {later}")


def push_level(repo: Path, branch: str) -> str:
    """The level committed in `repo` pushed as `branch`: "" when it is, else why not. A level
    tried again: the word that the last try failed is taken back, and the branch (and so its open
    pull request) carries the new try. In the containers the protected core checks it and pushes
    it (guard/rouh_guard/upstream.py, push_branch), and takes the failure word back itself."""
    level = branch.split("/", 1)[-1]
    if _through_guard():
        from . import guardface

        sha = _git("rev-parse", "HEAD", cwd=repo, timeout=20).stdout.strip()
        # Forced: the ref is only how the commit reaches /code, and a level tried again is cut afresh
        # on rouh-core's main as it is now, so it is never on top of the last try. Without the force
        # the second try of 1.0.13 (10 November 2026) was refused as "behind its remote counterpart".
        r = _git("push", "-q", "--force", str(_app_dir()), f"HEAD:refs/base-patch/{level}", cwd=repo)
        if r.returncode:
            return f"the level could not be handed to the protected core: {r.stderr.strip()[-300:]}"
        try:
            guardface.ask("push_branch", commit=sha, branch=branch, why=f"base {level}", timeout=3600)
        except guardface.Refused as e:
            return f"the protected core did not push it: {e}"
        except guardface.Unavailable as e:
            return str(e)
        return ""
    _git("push", "-q", "origin", ":" + FAILED.format(level=level), cwd=repo)
    r = _git("push", "-q", "--force", "origin", f"HEAD:refs/heads/{branch}", cwd=repo)
    return r.stderr.strip()[-300:] if r.returncode else ""


async def _watch(who, level: str) -> None:
    """The level just pushed, watched until its result is written, so a failure is told tonight."""
    end = time.time() + WATCH_FOR
    while time.time() < end:
        await asyncio.sleep(WATCH_EVERY)
        try:
            rec = record()
            if (rec.get("pending") or {}).get("level") != level:
                return
            repo = await asyncio.to_thread(_state)
            if _result(repo, level) is None:
                continue
            said = await _settle(who, rec, repo)
            _keep(rec)
            log.info("the base patch job: %s", said)
            return
        except Exception:  # noqa: BLE001 - the next night takes it up
            log.exception("watching base %s failed; the next night takes it up", level)
            return
