"""Take shared main's released changes individually, respecting this Rouh's evolution.

The ledger is durable before any proposal, including across the restart each undo point causes.
Each file of a change is taken on its own (17 November 2026, after a Rouh's update stuck for days
on a vendored three.js of 700 KB on one line, which the adapting job only ever saw as cut-off text):

- **copied exactly**: this Rouh's file is the one the change started from (or the file is new), so
  git puts the release's blob in place, byte for byte, and its hash is checked against the release.
  A library, a picture, a font or a minified file is never handed to a model as text.
- **merged by git**: this Rouh changed other lines of the file, and the change's own lines fit
  beside them (a three-way merge with no clash), so they go in with no model.
- **adapted**: only a file whose lines clash with this Rouh's own goes to a background adapting job
  through the LLM service, whose model must belong to the published standard's Smart tier, told
  which files are already in place. A file that can only be copied whole and that this Rouh
  changed itself waits, and says so.

An exact change spends nothing. The protected core executes the proposed proof and owns the
database rehearsal and real migration; from core 1.1 it checks every exact copy against the
release commit itself, and then a security change copied exactly needs no model's proof.

**In order, never around a waiting change** (19 November 2026). The walk stops at the first change
it cannot take, says why, and every later change waits for it (``hold_after``). Until then a waiting
change held back only the later changes guessed to need it (the same file, a name it adds,
``Depends-on:``), and the rest came in around it: installed Rouhs ended up on mixes of code that
never ran anywhere - a page using a table whose migration waited - and broke instead of holding
back. Now this Rouh's code is always shared main as it was at one commit, plus its own changes.

**Observable.** A walk is driven by a run (``code_update.start_run``), one call of its
``update_step`` tool at a time, so its every step is on the run's record as it goes.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import code_update as u
from . import github_org

USE = "code_adapt"
TAKEN = ("copied", "adapted")
STATUS = {"copied": "Copied exactly", "adapted": "Adapted for this Rouh",
          "waiting": "Not taken yet", "depends": "Waiting for an earlier change"}
SENSITIVE = re.compile(r"security|vulnerab|CVE-|CSRF|XSS|SSRF|permission|authentication|authorization|credential", re.I)
SECURITY_PATHS = ("guard/", "rouh/auth", "rouh/tenancy", "rouh/encryption", "rouh/workerkey",
                  "rouh/untrusted", "rouh/checkface", "rouh/password", "rouh/job_policy")
#: This update step copies a released file exactly. The protected core 1.1 reads this line, with
#: UPDATE_STEP, to know whether a Rouh's update step can take such a file (guard/rouh_guard/updatestep.py).
EXACT_COPIES = 1
#: The files of the update step itself. The protected core brings exactly these to the newest
#: release when a Rouh's own copies are released versions it never changed and lack EXACT_COPIES.
UPDATE_STEP = ("rouh/code_evolution.py", "rouh/github_org.py")
#: A file with a line longer than this, or larger than OPAQUE_SIZE, or binary, is copied whole and
#: never read as text: a vendored library, a minified file, a picture, a font.
OPAQUE_LINE = 2000
OPAQUE_SIZE = 512 * 1024
#: Prose keeps a paragraph on one line (README.md has lines of 3,000 characters): a prose file is
#: opaque by its lines only past this, so its lines still merge beside this Rouh's own.
PROSE = (".md", ".markdown", ".txt", ".rst")
OPAQUE_PROSE_LINE = 50000
#: The ledger's classification of a change; a waiting row from before is classified again.
#: 3: a prose file's long paragraphs no longer make it opaque.
#: 4: a test's own files no longer make a change a database change, and a name in the message
#:    (updates.security-database-frontier) no longer makes it a security change (125a033e, 19 November 2026).
CLASSIFIED = 4
#: A change's message is read for security words outside names: a check's id, a path or a variable.
NAME_IN_MESSAGE = re.compile(r"[\w-]+(?:[./_][\w-]+)+")
#: How often a waiting urgent security change is tried again before it waits a day like the rest.
URGENT_TRIES = 3


def test_file(f: str) -> bool:
    """A test's own file, which never runs in a Rouh: tests/..., a tests/ folder, test_*.py.
    Rouh's own committed checks (rouh/selfcheck/) and the protected core's frozen ones are not this."""
    name = Path(f).name
    return f.startswith("tests/") or "/tests/" in f or name.startswith("test_") or name.endswith("_test.py")


#: Why a change that was put back with an earlier undo point waits.
PUT_BACK = ("Put back with an earlier undo point (by the doctor, because Rouh did not answer after it, or in "
            "Changes), so the update does not take it again by itself. Changes can put it back in place.")


def was_put_back(row: dict) -> bool:
    """Whether a change waits because an earlier undo point was put back over it (the doctor or its
    person). A row put back before 19 November 2026 says so only in its reason."""
    return bool(row.get("put_back")) or (row.get("status") not in TAKEN and
                                         str(row.get("reason") or "").startswith("Put back with an earlier undo point"))


def ledger() -> dict:
    return u._read(u.folder() / "ledger.json")


def save(doc: dict) -> None:
    u._write(u.folder() / "ledger.json", doc)


def reconcile_ledger() -> None:
    """An undo point put back by its person or doctor is no longer a taken master change."""
    doc = ledger()
    if not doc:
        return
    head = u._git("rev-parse", "HEAD", cwd=u.code_dir()).stdout.strip()
    if not head or head == doc.get("last_running"):
        return
    changed = False
    for row in doc["changes"]:
        if row.get("status") in TAKEN and row.get("local") and \
                u._git("merge-base", "--is-ancestor", row["local"], head, cwd=u.code_dir()).returncode:
            # Put back by the doctor (Rouh did not answer after it) or by its person. Never taken
            # again by the update on its own: a change that stopped Rouh starting would stop it again,
            # fifteen minutes at a time, with each walk (19 November 2026).
            row.update(status="waiting", put_back=row["status"],
                       reason=PUT_BACK)
            changed = True
        elif was_put_back(row) and row.get("local") and row.get("status") not in TAKEN and \
                u._git("merge-base", "--is-ancestor", row["local"], head, cwd=u.code_dir()).returncode == 0:
            # Its person pressed Put the change back in Changes: it runs again.
            row.update(status=row.get("put_back") or "copied", put_back=None, reason="Put back in place in Changes.")
            changed = True
    if changed:
        through = doc["installed"]
        for row in doc["changes"]:
            if row.get("status") not in TAKEN:
                break
            through = row["master"]
        doc["through"] = through
    doc["last_running"] = head
    save(doc)


def shown() -> dict:
    doc = ledger()
    rows = doc.get("changes", [])
    counts = {k: sum(r.get("status") == k for r in rows) for k in STATUS}
    return {"installed": doc.get("installed"), "through": doc.get("through"), "seen": doc.get("seen"),
            "counts": counts, "waiting": counts["waiting"] + counts["depends"],
            "changes": [{k: r.get(k) for k in ("master", "purpose", "status", "reason", "urgent", "point", "at")}
                        | {"status_label": STATUS.get(r.get("status"), "Not taken yet")} for r in rows]}


def master_repo() -> Path:
    return u.folder() / "master.git"


def sources() -> list[str]:
    """Where shared main is fetched from, in the order to try: ROUH_CODE_MASTER, else rouh-core on
    GitHub (rouh/github_org.py)."""
    return github_org.every(os.environ.get("ROUH_CODE_MASTER") or "https://github.com/{org}/rouh-core.git")


def _fetch_main(repo: Path) -> None:
    """Shared main into repo, from the first of sources() that gives it."""
    why = ""
    for url in sources():
        r = u._git("fetch", "-q", url, "+refs/heads/main:refs/heads/main", cwd=repo)
        if r.returncode == 0:
            return
        why = (r.stderr or r.stdout).strip()[-300:]
    raise u.Refused(f"git fetch failed: {why}")


def _git(*args, **kw):
    return u._out(*args, cwd=kw.get("cwd", master_repo()))


def scan(release: dict, b: dict, *, report: bool = True) -> dict:
    """A release is a forward-only boundary on shared main, never another Rouh's private tree."""
    repo = master_repo()
    repo.parent.mkdir(parents=True, exist_ok=True)
    if not repo.exists():
        u._git("init", "--bare", "-q", str(repo), cwd=repo.parent, check=True)
    if report:
        u._step("reading the released changes on shared main")
    if b.get("how") == "history":
        held = ledger() if ledger().get("installed") else record_start(b, repo)
        if held.get("installed") and u._git("merge-base", "--is-ancestor", release["commit"], "HEAD",
                                            cwd=u.code_dir()).returncode == 0:
            # This Rouh's own history already holds the release: nothing to fetch or list.
            held["looked"] = release["commit"]
            save(held)
            return held
    if release["commit"] not in (ledger().get("seen"), ledger().get("looked")):
        _fetch_main(repo)
    end = release["commit"]
    doc = ledger()
    if not doc.get("installed") and b.get("how") == "history":
        doc = record_start(b, repo) or doc
    # A one-time update (140-08) names its release in a Rouh-release trailer; its first install's
    # record still names the commit it was installed from, which may be on the old history.
    installed = doc.get("installed") or (b.get("release") if b.get("how") == "update" else "") \
        or u._read(u.code_dir() / ".git/rouh-installed.json").get("commit") or b.get("release")
    first = doc.get("history_first_point") or ""
    if not installed:
        raise u.Refused("This Rouh has no record of its installed master version; its history must be established before updating.")
    doc = doc or {"v": 1, "installed": installed, "through": installed, "changes": [],
                  "history_first_point": first}
    start = doc.get("seen") or doc["installed"]
    if start != end and u._git("merge-base", "--is-ancestor", end, start, cwd=repo).returncode == 0:
        # The release is already inside what this Rouh started from (the Creator Rouh, ahead of
        # its own release): nothing to list, and nothing to fetch again for it.
        doc["looked"] = end
        save(doc)
        return doc
    for older, newer in ((start, end), (end, "refs/heads/main")):
        if u._git("merge-base", "--is-ancestor", older, newer, cwd=repo).returncode:
            raise u.Refused("The released changes are not a continuation of shared main. Nothing was copied.")
    known = {r["master"] for r in doc["changes"]}
    for sha in _git("rev-list", "--first-parent", "--reverse", f"{start}..{end}").splitlines():
        if sha in known:
            continue
        parent = _git("rev-parse", sha + "^1")
        message = _git("show", "-s", "--format=%B", sha)
        all_files = _git("diff", "--name-only", "--no-renames", parent, sha).splitlines()
        files = list(all_files)
        # A first install omits release infrastructure; it remains outside this Rouh's own code.
        files = [f for f in files if not any((f == p or f.startswith(p + "/")) and
                  u._git("cat-file", "-e", f"{b.get('local') or 'HEAD'}:{p}", cwd=u.code_dir()).returncode
                  for p in u.LEFT_OUT)]
        kind = classify(sha, parent, all_files, message)
        purpose = message.splitlines()[0]
        already_here = bool(doc.get("history_first_point") or doc.get("history")) and u._git(
            "merge-base", "--is-ancestor", sha, "HEAD", cwd=u.code_dir()).returncode == 0
        doc["changes"].append({"master": sha, "parent": parent, "purpose": purpose, "files": files, **kind,
                               "outside_own_code": [f for f in all_files if f not in files],
                               "depends_on": re.findall(r"^Depends-on:\s*([0-9a-f]{7,40})", message, re.M),
                               "status": "copied" if already_here else "waiting",
                               "local": sha if already_here else None,
                               "reason": "Already present as this master commit in this Rouh's recorded history."
                               if already_here else "Waiting for its turn."})
    for row in doc["changes"]:
        # A row listed before 17 November 2026 read a vendored library's words as a security change.
        if row.get("status") not in TAKEN and row.get("classified") != CLASSIFIED:
            with contextlib.suppress(Exception):
                all_files = _git("diff", "--name-only", "--no-renames", row["parent"], row["master"]).splitlines()
                row.update(classify(row["master"], row["parent"], all_files,
                                    _git("show", "-s", "--format=%B", row["master"])))
    through = doc["installed"]
    for row in doc["changes"]:
        if row.get("status") not in TAKEN:
            break
        through = row["master"]
    doc["through"] = through
    doc["seen"] = end
    save(doc)
    return doc


def _bytes(repo: Path, *args: str) -> bytes:
    r = subprocess.run(["git", "-c", "safe.directory=*", *args], cwd=str(repo), capture_output=True, timeout=600)
    return r.stdout if r.returncode == 0 else b""


def opaque(repo: Path, revision: str, file: str) -> bool:
    """Whether a file at a revision can only be copied whole: binary, too large, or with a line
    longer than OPAQUE_LINE (a vendored or minified library, a picture, a font). A prose file's
    paragraphs are long lines and still text: its limit is OPAQUE_PROSE_LINE."""
    blob = _blob_id(repo, revision, file)
    if not blob:
        return False
    size = u._git("cat-file", "-s", blob, cwd=repo).stdout.strip()
    if size.isdigit() and int(size) > OPAQUE_SIZE:
        return True
    data = _bytes(repo, "cat-file", "blob", blob)
    if b"\0" in data[:8000]:
        return True
    limit = OPAQUE_PROSE_LINE if file.lower().endswith(PROSE) else OPAQUE_LINE
    return any(len(line) > limit for line in data.split(b"\n"))


def database_file(f: str) -> bool:
    """A file that says what the database is: a migration, a model, the schema."""
    return "/migrations/" in f or "/models/" in f or f.endswith("schema.sql")


def classify(sha: str, parent: str, all_files: list[str], message: str) -> dict:
    """Database, security and which files are opaque. Opaque files' bytes are not read for words:
    three.js says "credentials", and that is not a change to how this Rouh keeps anyone's."""
    repo = master_repo()
    whole = [f for f in all_files if opaque(repo, sha, f) or opaque(repo, parent, f)]
    code = [f for f in all_files if f not in whole and (Path(f).name == ".env" or Path(f).suffix in (
        ".py", ".js", ".html", ".sh", ".toml", ".yml", ".yaml", ".json", ".ini", ".cfg", ".sql", ".env"))]
    # The code's own lines are read for security words; a library's licence ("Permission is hereby
    # granted") or a page of prose is not a security change. A test's lines still count for security
    # (a hardening's test may be the only place that says so), never for the database: a test's
    # made-up migration is not one. Its message always counts, its words and not the names in it.
    diff = _git("diff", "--no-ext-diff", parent, sha, "--", *code) if code else ""
    runs = [f for f in code if not test_file(f)]
    run_diff = _git("diff", "--no-ext-diff", parent, sha, "--", *runs) if runs else ""
    database = any(database_file(f) for f in all_files if not test_file(f))
    database = database or bool(re.search(r"\b(?:ALTER|CREATE|DROP)\s+(?:TABLE|INDEX|SCHEMA)\b", run_diff))
    security = bool(SENSITIVE.search(NAME_IN_MESSAGE.sub(" ", message)) or SENSITIVE.search(diff) or
                    any(f.startswith(SECURITY_PATHS) for f in all_files))
    return {"database": database, "security": security, "urgent": security, "opaque": whole,
            "classified": CLASSIFIED}


def record_start(b: dict, repo: Path | None = None) -> dict:
    """The starting version of a Rouh that carries Rouh's whole history (the Creator Rouh): the
    commit of shared main its code started from, written in the ledger as ``installed``.

    It is the protected core's first undo point, as shared main has it, when that point is in this
    Rouh's history; else the newest commit of shared main this Rouh's code contains, as the
    protected core keeps main fetched into /code (refs/upstream/heads/main). rouh-core went public
    on 7 November 2026 with a fresh history, so a first undo point from before then is on neither.
    {} when neither can be said; an existing record is never replaced."""
    doc = ledger()
    if doc.get("installed") or b.get("how") != "history":
        return doc if doc.get("installed") else {}
    code = u.code_dir()
    first = ""
    from . import guardface

    with contextlib.suppress(Exception):
        first = next((p.get("commit", "") for p in guardface.ask("points").get("points", [])
                      if p.get("n") == 1 and p.get("kind") == "first"), "")
    installed, how = "", ""
    if first and u._git("merge-base", "--is-ancestor", first, "HEAD", cwd=code).returncode == 0:
        if repo is not None and repo.exists():
            u._git("fetch", "-q", str(code), first, cwd=repo)
            installed = u._git("merge-base", first, "refs/heads/main", cwd=repo).stdout.strip()
        if not installed:
            installed = u._git("merge-base", first, "refs/upstream/heads/main", cwd=code).stdout.strip()
        how = "the protected core's first undo point, as shared main has it"
    if not installed:
        first = ""
        installed = u._git("merge-base", "HEAD", "refs/upstream/heads/main", cwd=code).stdout.strip()
        how = "the newest commit of shared main this Rouh's code contains"
    if not re.fullmatch(r"[0-9a-f]{40}", installed):
        return {}
    doc = {"v": 1, "installed": installed, "through": installed, "changes": [], "history": True,
           "history_first_point": first, "start_how": how, "start_at": time.time()}
    save(doc)
    return doc


def observe(release: dict, b: dict) -> None:
    """List released purposes before a press, without applying code or spending on a model."""
    if release.get("commit") in (ledger().get("seen"), ledger().get("looked")) or not u._guard():
        return
    if not u._run_lock.acquire(blocking=False):
        return
    try:
        scan(release, b, report=False)
    finally:
        u._run_lock.release()


def frontier(model: str) -> bool:
    """The bar follows the model standard, never a name guessed from the model's spelling."""
    from . import modelstandard

    bar = os.environ.get("ROUH_CODE_UPDATE_MODEL_TIER", "smart")
    if bar != "smart":
        raise u.Refused("The update model bar must be the frontier (Smart) tier.")
    return bool(model and model in modelstandard.tier_pick("smart"))


def model_pick() -> str:
    from . import modeldefaults

    model = modeldefaults.use_model(USE)
    if not frontier(model):
        raise u.Refused("needs a frontier model")
    return model


def _blob(repo: Path, revision: str, file: str) -> str:
    r = u._git("ls-tree", revision, "--", file, cwd=repo)
    return r.stdout.strip().split("\t", 1)[0]


def _blob_id(repo: Path, revision: str, file: str) -> str:
    """The blob's hash alone: what an exact copy must have."""
    got = _blob(repo, revision, file).split()
    return got[2] if len(got) == 3 else ""


def _merge(work: Path, here: str, base: str, theirs: str) -> bytes | None:
    """A three-way merge of one file's blobs: this Rouh's, the change's start and its end. The
    merged bytes, or None when the lines clash."""
    r = subprocess.run(["git", "-c", "safe.directory=*", "merge-file", "--object-id", "-p", "-q", here, base, theirs],
                       cwd=str(work), capture_output=True, timeout=120)
    return r.stdout if r.returncode == 0 else None


#: The release being taken, while advance walks it: [its commit].
_END: list[str] = []


def sort_files(row: dict, work: Path) -> dict:
    """Each file of a change, by how it can be taken here (the master commit already fetched into work):
    exact (this Rouh's file is the one the change started from, or already the one it ends with),
    merged (the change's own lines fit beside this Rouh's, {file: bytes}), clash (adapting job, and
    every migration, model or schema file a database change brings: it must fit this Rouh's schema),
    whole (a file only copied whole that this Rouh changed itself: it waits)."""
    master = master_repo()
    out: dict = {"exact": [], "merged": {}, "clash": [], "whole": [], "already": []}
    for f in row["files"]:
        base, here, theirs = (_blob(master, row["parent"], f), _blob(work, "HEAD", f), _blob(master, row["master"], f))
        if here and here != theirs and _END and here == _blob(master, _END[0], f):
            # Already the release's own final version (the protected core's update step brings its
            # files so): every change before it is in it.
            out["already"].append(f)
        elif here != theirs and row.get("database") and database_file(f) and not opaque(master, row["master"], f):
            # A database change's migration must fit this Rouh's own schema (its own tables, its own
            # newest migration), so the adapting job may change it; it is never locked as a copy.
            out["clash"].append(f)
        elif here == base or here == theirs:
            out["exact"].append(f)
        elif f in (row.get("opaque") or []) or opaque(work, "HEAD", f):
            out["whole"].append(f)
        elif base and here and theirs and base.split()[0] == here.split()[0] == theirs.split()[0]:
            merged = _merge(work, here.split()[2], base.split()[2], theirs.split()[2])
            if merged is None:
                out["clash"].append(f)
            else:
                out["merged"][f] = merged
        else:
            out["clash"].append(f)
    return out


def copy_exact(row: dict, work: Path, files: list[str]) -> dict:
    """The release's own blobs into work, by git, and each checked against the release: {file: blob
    hash, or "" for a file the change deletes}. Never through text."""
    master, out = master_repo(), {}
    for f in files:
        want = _blob(master, row["master"], f)
        if want:
            u._git("restore", "--source=" + row["master"], "--staged", "--worktree", "--", f, cwd=work, check=True)
        else:
            u._git("rm", "-q", "--ignore-unmatch", "--", f, cwd=work, check=True)
        got = u._git("ls-files", "-s", "--", f, cwd=work).stdout.strip()
        mode_blob = " ".join(got.split()[:2]) if got else ""
        if mode_blob != (" ".join(want.split()[0:3:2]) if want else ""):
            raise u.Refused(f"The copy of {f} did not come out exactly as the release has it; nothing was taken.")
        out[f] = want.split()[2] if want else ""
    return out


def check_exact(work: Path, copied: dict) -> None:
    """After an adapting job: every exact copy still is one."""
    for f, blob in copied.items():
        path = work / f
        got = u._git("hash-object", "--", f, cwd=work).stdout.strip() if path.is_file() or path.is_symlink() else ""
        if got != blob:
            raise u.Refused(f"The adapting job changed {f}, which was copied exactly from the release; nothing was taken.")


def _rule() -> str:
    """Read the editable Agent rule now, including local improvements to it."""
    from . import agent_instructions, relay

    who = relay.owner()
    if who is None:
        raise u.Refused("The adapting job has no owner whose agent rule it can read.")
    for row in agent_instructions.agent_rules(str(who.org_id)):
        if (row.get("upstream") or {}).get("key") == "adapt-master-change" or row.get("title") == "Adapting a released master change":
            return str(row["text"])
    # Import the shared default through the same Rules machinery, never a private code prompt.
    from . import ruledefaults
    ds = agent_instructions.owner_master(str(who.org_id))
    if ds:
        defaults = ruledefaults.fallback()
        ruledefaults.take(ds, {**defaults, "rules": [r for r in defaults["rules"] if r["key"] == "adapt-master-change"]})
        for row in agent_instructions.agent_rules(str(who.org_id)):
            if (row.get("upstream") or {}).get("key") == "adapt-master-change" or row.get("title") == "Adapting a released master change":
                return str(row["text"])
    raise u.Refused("The adapting job's agent rule is missing or switched off.")


def _excerpt(text: str, diff: str, limit: int) -> tuple[str, dict]:
    """Keep imports and changed neighbourhoods; large files remain available by inspection."""
    lines = text.splitlines(keepends=True)
    info = {"complete": len(text) <= limit, "lines": len(lines), "characters": len(text)}
    if info["complete"]:
        return text, info
    wanted = set(range(min(30, len(lines))))
    anchors = {s[1:].strip() for s in diff.splitlines() if s[:1] in (" ", "-", "+") and len(s.strip()) > 15}
    functions = re.findall(r"@@.*?@@.*?(?:def|class|function)\s+(\w+)", diff)
    positions: dict[str, list[int]] = {}
    for i, line in enumerate(lines):
        if line.strip() in anchors:
            positions.setdefault(line.strip(), []).append(i)
    centres = [where[0] for where in positions.values() if len(where) == 1]
    if not centres:
        centres = [i for i, line in enumerate(lines) if any(
            re.search(r"\b(?:def|class|function)\s+" + re.escape(f) + r"\b", line) for f in functions)]
    for i in centres:
        wanted.update(range(max(0, i - 12), min(len(lines), i + 24)))
    chunks, used, previous = [], 0, -1
    for i in sorted(wanted):
        if used + len(lines[i]) > limit:
            break
        if previous >= 0 and i != previous + 1:
            chunks.append(f"\n[... omitted; next is line {i + 1} ...]\n")
        chunks.append(lines[i])
        used += len(lines[i])
        previous = i
    return "".join(chunks), info


def brief(row: dict, work: Path) -> dict:
    from . import guardface

    master = master_repo()
    local = {f: (work / f).read_text(errors="replace") if (work / f).is_file() and not (work / f).is_symlink()
             else None for f in row["files"] if f not in (row.get("opaque") or [])}
    tests = [f for f in row["files"] if ("test" in f or "selfcheck" in f or "check" in Path(f).name)
             and f not in (row.get("opaque") or [])]
    whole = set(row.get("opaque") or [])
    diffs = {f: _git("diff", "--no-ext-diff", row["parent"], row["master"], "--", f) for f in row["files"]
             if f not in whole}
    local_info, master_info = {}, {}
    for f, content in local.items():
        if content is not None:
            local[f], local_info[f] = _excerpt(content, diffs[f], max(3000, min(48000, 160000 // max(1, len(local)))))
    master_tests = {}
    for f in tests:
        master_tests[f], master_info[f] = _excerpt(u._git("show", row["master"] + ":" + f, cwd=master).stdout, diffs[f], 24000)
    def readme(text):
        words = {w.lower() for w in re.findall(r"[A-Za-z_]{5,}", row["purpose"] + " " + " ".join(row["files"]))}
        sections = re.split(r"(?m)(?=^## )", text)
        ranked = sorted(sections[1:], key=lambda s: -sum(w in s.lower() for w in words))
        return sections[0][:4000] + "\n" + "\n".join(s[:12000] for s in ranked[:2])
    from .genes import owners

    relevant_genes = {g for f in row["files"] for g in owners.owners_of(f)}
    core = guardface.ask("status")
    database_state = guardface.ask("database_inventory") if row["database"] else {}
    schema = {}
    for column in database_state.get("schema", []):
        schema.setdefault(column["table"], []).append(column["column"] + ": " + column["type"])
    readable = [f for f in row.get("all_files", row["files"]) if f not in whole]
    full_diff = _git("diff", "--no-ext-diff", row["parent"], row["master"], "--", *readable) if readable else ""
    catalogue = u._git("show", row["master"] + ":CONTAINERS.md", cwd=master).stdout
    return {"change": row, "commit_message": _git("show", "-s", "--format=%B", row["master"]),
            "master_diff": full_diff[:100000], "master_diff_complete": len(full_diff) <= 100000,
            "master_tests": master_tests, "master_test_info": master_info,
            "master_readme": readme(u._git("show", row["master"] + ":README.md", cwd=master).stdout),
            "master_checks_catalogue": _excerpt(catalogue, full_diff, 24000)[0],
            "local_files": local, "local_file_info": local_info,
            "local_readme": readme((work / "README.md").read_text(errors="replace"))
            if (work / "README.md").is_file() and not (work / "README.md").is_symlink() else "",
            "local_changes": _git("log", "-40", "--format=%B", cwd=work),
            "genes": {p.name: p.read_text() for p in (work / "rouh/genes/manifests").glob("*.json")
                      if p.stem in relevant_genes and not p.is_symlink()},
            "all_gene_names": [p.stem for p in (work / "rouh/genes/manifests").glob("*.json")],
            "protected_core": {k: core.get(k) for k in ("version", "features")},
            "local_schema": schema,
            "local_migration_history": database_state.get("migrations", []),
            "local_migrations": {p.name: p.read_text() for p in (work / "rouh/migrations").glob("*.py")
                                 if row["database"] and not p.is_symlink()
                                 and u._git("cat-file", "-e", row["parent"] + ":rouh/migrations/" + p.name,
                                                              cwd=master).returncode},
            "database": row["database"], "security": row["security"],
            # Taken by git before this job, byte for byte or as the change's own lines: never edit these.
            "already_in_place": {"copied_exactly_from_the_release": row.get("in_place_exact", []),
                                 "merged_by_git": row.get("in_place_merged", []),
                                 "copied_whole_never_shown_as_text": sorted(whole)},
            "files_to_adapt": row.get("to_adapt", row["files"])}


def _path(work: Path, name: str) -> Path:
    p = work / name
    resolved, root = p.resolve(), work.resolve()
    if not name or name.startswith("-") or ".git" in Path(name).parts or not resolved.is_relative_to(root) \
            or ".git" in resolved.relative_to(root).parts:
        raise u.Refused("The adapting job proposed a file outside its checkout.")
    return p


def inspect_code(row: dict, work: Path, requests: list) -> list[dict]:
    out = []
    for request in requests[:6]:
        name = str(request.get("file") or "")
        side = request.get("side", "local")
        _path(work, name)  # Includes private-git and symlink boundaries for every read.
        if side == "local":
            path = work / name
            content = path.read_text(errors="replace") if path.is_file() and not path.is_symlink() else ""
        elif side == "master":
            content = _git("show", row["master"] + ":" + name)
        elif side == "diff":
            content = _git("diff", "--no-ext-diff", row["parent"], row["master"], "--", name)
        else:
            raise u.Refused("The adapting job requested an unknown source of code.")
        lines = content.splitlines()
        start = max(0, int(request.get("start", 1)) - 1)
        if request.get("find"):
            start = next((max(0, i - 8) for i, line in enumerate(lines) if str(request["find"]) in line), start)
        count = min(300, max(1, int(request.get("lines", 100))))
        out.append({"side": side, "file": name, "start": start + 1, "total_lines": len(lines),
                    "text": "\n".join(lines[start:start + count])[:14000]})
    return out


def adapt(row: dict, work: Path, feedback: str = "") -> dict:
    """One bounded planning/build pass; all tests and the migration gate run in the core afterwards."""
    from . import llm

    model = model_pick()  # Before every request; no cheaper fallback, including on a retry.
    context = brief(row, work)
    context["previous_check"] = feedback
    for turn in range(8):
        raw = json.dumps(context, ensure_ascii=False)
        if len(raw) > 500_000:
            raise u.Refused("This change needs a larger adaptation job than this Rouh can prepare yet.")
        answer = asyncio.run(llm.ask(USE, system=_rule(), messages=[{"role": "user", "content": raw}],
                                    max_tokens=32000, purpose=USE, subject=row["purpose"], timeout=900,
                                    required_tier="smart"))
        if answer.model != model or not frontier(answer.model):
            raise u.Refused("needs a frontier model")
        try:
            text = answer.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0]
            plan = json.loads(text)
        except (ValueError, IndexError):
            raise u.Refused("The adapting job returned no readable plan.") from None
        if not plan.get("inspect"):
            break
        context["inspection"] = inspect_code(row, work, plan["inspect"])
        context["inspection_notes"] = str(plan.get("inspection_notes") or "")[:8000]
    else:
        raise u.Refused("The adapting job needs more time to inspect this change; it will be tried again.")
    if plan.get("waiting"):
        if isinstance(plan.get("depends_on"), list):
            row["depends_on"] = list(set(row["depends_on"] + [str(x) for x in plan["depends_on"]]))
        raise u.Refused(str(plan["waiting"])[:600])
    if not plan.get("reason") or not plan.get("proof") or not isinstance(plan.get("files", {}), dict):
        raise u.Refused("The adapting job left out its implementation, reasoning or master's change checks.")
    for name, content in plan.get("files", {}).items():
        path = _path(work, name)
        if content is None:
            if path.is_file() or path.is_symlink():
                path.unlink()
        elif isinstance(content, str):
            if (context.get("local_file_info", {}).get(name) or {}).get("complete") is False:
                raise u.Refused("The adapting job must use exact edits for a file it only read in parts: " + name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        else:
            raise u.Refused("The adapting job returned a file with no usable content.")
    for name, edits in plan.get("edits", {}).items():
        path = _path(work, name)
        content = path.read_text()
        for edit in edits:
            before, after = edit["before"], edit["after"]
            if not before or content.count(before) != 1:
                raise u.Refused("The adapting job's edit did not identify exactly one place in " + name + ".")
            content = content.replace(before, after, 1)
        path.write_text(content)
    plan["model"] = model
    return plan


def _taken_said(row: dict, copied: dict, sort: dict) -> str:
    """What git took of a change, as a sentence for the record."""
    if not row["files"]:
        return "Release tooling only; those files are not installed in this Rouh's own code."
    parts = []
    if copied:
        parts.append(f"{len(copied)} file{'s' if len(copied) != 1 else ''} copied exactly from the release, "
                     "each checked against its hash there")
    if sort.get("already"):
        parts.append(", ".join(sorted(sort["already"])[:4]) + " already the release's own newest version")
    if sort["merged"]:
        parts.append("its own lines merged by git into this Rouh's " + ", ".join(sorted(sort["merged"])[:4])
                     + (f" and {len(sort['merged']) - 4} more" if len(sort["merged"]) > 4 else ""))
    said = "; ".join(parts)
    return said[:1].upper() + said[1:] + "."


def _waiting(doc: dict, row: dict, reason: str, status: str = "waiting", blocked_by: str | None = None) -> None:
    row.update(status=status, reason=reason, at=time.time(), blocked_by=blocked_by)
    save(doc)


def _through(doc: dict) -> str:
    """The newest change of shared main this Rouh has, with every change before it."""
    through = doc["installed"]
    for row in doc["changes"]:
        if row.get("status") not in TAKEN:
            break
        through = row["master"]
    return through


def hold_after(doc: dict, stopped: dict) -> None:
    """Every change after one that waits waits for it (19 November 2026).

    Released changes come in strictly in order, so this Rouh's code is always shared main as it
    was at one commit, with this Rouh's own changes on top: code that ran on the Creator Rouh
    before it was released. Taking a later change past one that waits made a mix no Rouh had ever
    run - a page using a table whose migration waited, a module calling a function an earlier
    change gave new arguments - and guessing which later changes are safe without it (by names
    and files) missed exactly those, so updated Rouhs broke instead of holding back."""
    after = False
    for row in doc["changes"]:
        if row is stopped:
            after = True
            continue
        if not after or row.get("status") in TAKEN or was_put_back(row):
            continue
        row.update(status="depends", blocked_by=stopped["master"], at=time.time(),
                   reason=f"Waits for “{stopped['purpose']}” ({stopped['master'][:8]}), which is not taken yet. "
                          "Released changes come in in order, so nothing after a change that waits is taken: "
                          "this Rouh stays on code that ran as released.")
    save(doc)


def core_features() -> dict:
    from . import guardface

    return guardface.ask("status").get("features") or {}


def _propose(doc: dict, row: dict, rel: dict, by: str, work: Path, plan: dict, copied: bool,
             taken: dict | None = None) -> bool:
    from . import guardface

    if core_features().get("master_changes") != 1:
        raise u.Refused("needs the protected core's per-change update and database rehearsal gate")
    taken = taken or {}
    u._git("add", "-A", cwd=work, check=True)
    if taken.get("exact"):
        check_exact(work, taken["exact"])
    u._git("commit", "-q", "--allow-empty", "-m", row["purpose"], "-m", "Rouh-master-change: " + row["master"],
           cwd=work, check=True)
    commit = _git("rev-parse", "HEAD", cwd=work)
    u._git("fetch", "-q", str(work), "+HEAD:refs/rouh/update/change", cwd=u.code_dir(), check=True)
    # The release commit itself beside it, so the protected core can check each exact copy against it.
    u._git("fetch", "-q", str(master_repo()), "+" + row["master"] + ":refs/rouh/update/master",
           cwd=u.code_dir(), check=True)
    backup = u._backup(u.code_dir(), False)
    pending = {"release": rel["commit"], "label": u.label(rel["commit"], rel), "commit": commit,
               "at": time.time(), "by": by, "master_change": row["master"],
               "change_status": "copied" if copied else "adapted", "backup": backup,
               "reason": plan.get("reason", "Every touched file still matched master."),
               "continuation": rel}
    u._change(pending=pending)
    # The protected core owns every gate. From core 1.1 it checks each exact copy against the release
    # commit, and a change that is all exact copies (not a database change) needs no model's proof.
    evidence = {"master": row["master"], "database": row["database"], "security": row["security"],
                "proof": plan.get("proof", ""), "database_plan": plan.get("database_plan"),
                "not_applicable": bool(plan.get("not_applicable")),
                "model": plan.get("model", ""), "reason": plan.get("reason", ""),
                "exact": taken.get("exact") or {}, "merged": sorted(taken.get("merged") or [])}
    try:
        answer = guardface.ask("propose", commit=commit, why="Master change: " + row["purpose"],
                               by="Rouh's update (" + by + ")", update=evidence, timeout=3600)
    except guardface.Unavailable:
        u._change(busy=None)
        return False  # The next start reconciles the pending transaction, never guesses success.
    except guardface.Refused as exc:
        u._change(pending=None)
        raise u.Refused(str(exc)) from None
    if not answer.get("ok"):
        u._change(pending=None)
        raise u.Refused(u._plain_refusal(str(answer.get("refused") or "The protected core refused it.")))
    finish(pending, answer.get("point") or {})
    return True


def finish(pending: dict, point: dict) -> None:
    doc = ledger()
    for row in doc.get("changes", []):
        if row["master"] == pending["master_change"]:
            row.update(status=pending["change_status"], local=pending["commit"], point=point.get("n"),
                       at=time.time(), reason=pending["reason"])
    through = doc["installed"]
    for row in doc["changes"]:
        if row.get("status") not in TAKEN:
            break
        through = row["master"]
    doc["through"] = through
    save(doc)
    u._change(pending=None, busy=None, continue_update={"release": pending["continuation"], "by": pending["by"]})


def advance(rel: dict, by: str, work: Path) -> None:
    """Walk in order, one protected undo point a change. Resume remaining work after each restart."""
    reconcile_ledger()
    b = u.base()
    doc = scan(rel, b)
    from . import guardface

    if (guardface.ask("status").get("features") or {}).get("master_changes") != 1:
        for row in doc["changes"]:
            if row.get("status") not in TAKEN:
                _waiting(doc, row, "needs the protected core's per-change update and database rehearsal gate")
        raise u.Refused("needs the protected core's per-change update and database rehearsal gate")
    # A batch survives all of its per-change restarts; a later retry starts a fresh account
    # of what came in, rather than reporting this Rouh's lifetime totals as today's update.
    if not u.state().get("continue_update") or (doc.get("session") or {}).get("release") != rel["commit"]:
        doc["session"] = {"release": rel["commit"],
                          "before": [r["master"] for r in doc["changes"] if r.get("status") in TAKEN]}
        save(doc)
    # Mark the session before the first proposal: if it restarts us, we keep walking the list.
    u._change(continue_update={"release": rel, "by": by})
    if not u._git("status", "--porcelain", cwd=u.code_dir()).stdout.strip() == "":
        raise u.Refused("This Rouh has uncommitted work; the update will try again later.")
    if work.exists():
        shutil.rmtree(work)
    u._git("clone", "-q", "--no-hardlinks", str(u.code_dir()), str(work), cwd=work.parent, check=True)
    # Every release commit's objects beside this Rouh's code, so each file is taken by git, never as text.
    u._git("fetch", "-q", str(master_repo()), rel["commit"], cwd=work, check=True)
    _END[:] = [rel["commit"]]
    stopped: dict | None = None
    for i, row in enumerate(doc["changes"]):
        if row.get("status") in TAKEN:
            continue
        if was_put_back(row):
            stopped = row
            break
        if not row["files"]:
            # Release tooling only (the protected core, the base's versions): an install has none of
            # those files, so nothing of this Rouh's code changes and there is nothing to prove. Until
            # 19 November 2026 such a change, read as security because it touched guard/, waited for a
            # model's proof of a change that changes nothing here.
            row.update(status="copied", local=u._git("rev-parse", "HEAD", cwd=u.code_dir()).stdout.strip(),
                       point=None, at=time.time(), reason=_taken_said(row, {}, {}))
            doc["through"] = _through(doc)
            save(doc)
            continue
        sort = sort_files(row, work)
        if sort["whole"]:
            _waiting(doc, row, "This Rouh has its own version of " + ", ".join(sort["whole"][:3])
                     + (", a file" if len(sort["whole"]) == 1 else ", files")
                     + " that can only be copied whole (a library, a picture or a minified file, not text to"
                       " edit), so the release's version waits rather than replace this Rouh's own.")
            stopped = row
            break
        exact_only = not sort["merged"] and not sort["clash"]
        no_proof = exact_only and bool(row["files"]) and not row.get("outside_own_code") \
            and core_features().get("exact_copies") == 1
        needs_model = bool(sort["clash"]) or row["database"] or (row["security"] and not no_proof)
        start = _git("rev-parse", "HEAD", cwd=work)
        feedback = ""
        for attempt in range(3 if needs_model else 1):
            u._step(("adapting" if sort["clash"] else "checking" if needs_model else "copying") + ": " + row["purpose"])
            u._git("reset", "--hard", start, cwd=work, check=True)
            u._git("clean", "-fdq", cwd=work, check=True)
            try:
                copied = copy_exact(row, work, sort["exact"])
                for f, data in sort["merged"].items():
                    (work / f).write_bytes(data)
                    u._git("add", "--", f, cwd=work, check=True)
                said = _taken_said(row, copied, sort)
                if needs_model:
                    model_pick()
                    view = {**row, "files": sort["clash"], "all_files": row["files"], "to_adapt": sort["clash"],
                            "in_place_exact": sorted(copied), "in_place_merged": sorted(sort["merged"])}
                    plan = adapt(view, work, feedback)
                    row["depends_on"] = view.get("depends_on", row.get("depends_on", []))
                    check_exact(work, copied)
                    plan["reason"] = (said + " " if copied or sort["merged"] else "") + str(plan.get("reason") or "")
                else:
                    plan = {"reason": said}
                if any(f in u.LIBRARIES for f in row["files"]):
                    u._libraries(work)
                _propose(doc, row, rel, by, work, plan, not needs_model and exact_only,
                         taken={"exact": copied, "merged": list(sort["merged"])})
                # A restart may interrupt here. The durable continuation precedes the proposal.
                return
            except (u.Refused, ValueError) as exc:
                feedback = str(exc)
                if feedback == "needs a frontier model":
                    feedback += (" (it changes the database, so a Smart-tier model must fit and prove it)" if row["database"]
                                 else " (its lines clash with this Rouh's own, so a Smart-tier model must adapt them)"
                                 if sort["clash"] else " (a security change, so a Smart-tier model must prove it)")
                if attempt == 0:
                    row["tries"] = int(row.get("tries") or 0) + 1
                _waiting(doc, row, feedback)
                if "frontier model" in feedback or not needs_model:
                    break
            except Exception as exc:  # noqa: BLE001 - said on the row, and the walk stops at it
                feedback = f"The adapting job could not finish ({type(exc).__name__})."
                _waiting(doc, row, feedback)
                break
        u._git("reset", "--hard", start, cwd=work, check=True)
        u._git("clean", "-fdq", cwd=work, check=True)
        stopped = row
        break
    if stopped is not None:
        hold_after(doc, stopped)
    out = shown()
    earlier = set((doc.get("session") or {}).get("before", []))
    came_in = [r for r in doc["changes"] if r["master"] not in earlier and r.get("status") in TAKEN]
    counts = {k: sum(r["status"] == k for r in came_in) for k in TAKEN}
    summary = f"{counts['copied']} copied exactly, {counts['adapted']} adapted, {out['waiting']} waiting."
    waiting = [r for r in doc["changes"] if r["status"] not in TAKEN]
    fingerprint = hashlib.sha256(json.dumps([(r["master"], r["status"], r.get("reason"))
                                           for r in doc["changes"]], sort_keys=True).encode()).hexdigest()[:20]
    previous = u.state().get("last") or {}
    last = {"ok": not waiting, "partial": bool(waiting), "at": time.time(), "release": rel["commit"],
            "label": u.label(rel["commit"], rel), "said": summary, "by": by, "id": fingerprint,
            "stopped_at": {"master": stopped["master"], "purpose": stopped["purpose"],
                           "reason": stopped.get("reason") or ""} if stopped is not None else None,
            "through": doc.get("through"),
            "told": previous.get("id") == fingerprint and previous.get("told", False),
            "came_in": [{"purpose": r["purpose"], "status": r["status"]} for r in came_in],
            "waiting": [{"purpose": r["purpose"], "reason": r["reason"], "urgent": r["urgent"]} for r in waiting]}
    # An urgent change is tried again in half an hour, a few times; one that keeps failing waits a day
    # like the rest, so a walk (and a restart for each change it takes) does not come every half hour.
    urgent = any(r["urgent"] and int(r.get("tries") or 0) < URGENT_TRIES and not was_put_back(r) for r in waiting)
    u._change(busy=None, pending=None, continue_update=None, last=last,
              retry_at=time.time() + (1800 if urgent else 86400),
              retry_release=rel if waiting else None)
