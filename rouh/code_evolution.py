"""Take shared main's released changes individually, respecting this Rouh's evolution.

The ledger is durable before any proposal, including across the restart each undo point causes.
An exact change spends nothing. Anything else is a background adaptation job through the LLM
service, whose model must belong to the published standard's Smart tier. The protected core
executes the proposed proof and owns the database rehearsal and real migration.
"""
from __future__ import annotations

import asyncio
import ast
import contextlib
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from . import code_update as u

USE = "code_adapt"
TAKEN = ("copied", "adapted")
STATUS = {"copied": "Copied exactly", "adapted": "Adapted for this Rouh",
          "waiting": "Not taken yet", "depends": "Waiting for an earlier change"}
SENSITIVE = re.compile(r"security|vulnerab|CVE-|CSRF|XSS|SSRF|permission|authentication|authorization|credential", re.I)
SECURITY_PATHS = ("guard/", "rouh/auth", "rouh/tenancy", "rouh/encryption", "rouh/workerkey",
                  "rouh/untrusted", "rouh/checkface", "rouh/password", "rouh/job_policy")


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
            row.update(status="waiting", reason="Put back with an earlier undo point; this change is not running.")
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


def source() -> str:
    return os.environ.get("ROUH_CODE_MASTER", "https://github.com/rouh-it/rouh-core.git")


def _git(*args, **kw):
    return u._out(*args, cwd=kw.get("cwd", master_repo()))


def scan(release: dict, b: dict) -> dict:
    """A release is a forward-only boundary on shared main, never another Rouh's private tree."""
    repo = master_repo()
    repo.parent.mkdir(parents=True, exist_ok=True)
    if not repo.exists():
        u._git("init", "--bare", "-q", str(repo), cwd=repo.parent, check=True)
    u._step("reading the released changes on shared main")
    if ledger().get("seen") != release["commit"]:
        u._git("fetch", "-q", source(), "+refs/heads/main:refs/heads/main", cwd=repo, check=True)
    end = release["commit"]
    doc = ledger()
    installed = doc.get("installed") or u._read(u.code_dir() / ".git/rouh-installed.json").get("commit") or b.get("release")
    if not installed:
        raise u.Refused("This Rouh has no record of its installed master version; its history must be established before updating.")
    doc = doc or {"v": 1, "installed": installed, "through": installed, "changes": []}
    start = doc.get("seen") or doc["installed"]
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
        diff = _git("diff", "--no-ext-diff", parent, sha)
        database = any("/migrations/" in f or "/models/" in f or f.endswith("schema.sql") for f in all_files)
        database = database or bool(re.search(r"\b(?:ALTER|CREATE|DROP)\s+(?:TABLE|INDEX|SCHEMA)\b", diff))
        code_changed = any(Path(f).suffix in (".py", ".js", ".html", ".sh", ".toml", ".yml") for f in all_files)
        security = bool((code_changed and SENSITIVE.search(message + "\n" + diff)) or
                        any(f.startswith(SECURITY_PATHS) for f in all_files))
        purpose = message.splitlines()[0]
        doc["changes"].append({"master": sha, "parent": parent, "purpose": purpose, "files": files,
                               "database": database, "security": security, "urgent": security,
                               "outside_own_code": [f for f in all_files if f not in files],
                               "depends_on": re.findall(r"^Depends-on:\s*([0-9a-f]{7,40})", message, re.M),
                               "status": "waiting", "reason": "Waiting for its turn."})
    doc["seen"] = end
    save(doc)
    return doc


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


def _module(path: str) -> str:
    p = Path(path)
    name = str(p.with_suffix(""))
    if p.stem == "__init__":
        name = str(p.parent)
    return name.replace("/", ".")


def imports_of(row: dict) -> set[str]:
    """Direct module dependencies are checked even when two purposes touch different files."""
    from importlib.util import resolve_name

    found: set[str] = set()
    for path in row["files"]:
        if Path(path).suffix not in (".py", ".js", ".ts"):
            continue
        source_text = u._git("show", row["master"] + ":" + path, cwd=master_repo()).stdout
        if path.endswith(".py"):
            try:
                tree = ast.parse(source_text)
            except SyntaxError:
                continue  # The protected code checks still refuse a malformed module.
            package = str(Path(path).parent).replace("/", ".")
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(a.name for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    name = node.module or ""
                    if node.level:
                        with contextlib.suppress(ImportError, ValueError):
                            name = resolve_name("." * node.level + name, package)
                    if name:
                        found.add(name)
                        found.update(name + "." + a.name for a in node.names)
        else:
            for relative in re.findall(r"(?:from\s*|import\s*|require\s*\(\s*)['\"]([^'\"]+)['\"]", source_text):
                if relative.startswith("."):
                    found.add(_module(os.path.normpath(os.path.join(os.path.dirname(path), relative))))
    return found


def exact(row: dict, work: Path) -> bool:
    return all(_blob(master_repo(), row["parent"], f) == _blob(work, "HEAD", f) for f in row["files"])


def _copy(row: dict, work: Path) -> None:
    """Copy only this change, including deletes, modes and binary blobs, using git's tree."""
    u._git("fetch", "-q", str(master_repo()), row["master"], cwd=work, check=True)
    for f in row["files"]:
        if _blob(master_repo(), row["master"], f):
            u._git("restore", "--source=" + row["master"], "--staged", "--worktree", "--", f,
                   cwd=work, check=True)
        else:
            u._git("rm", "-q", "--ignore-unmatch", "--", f, cwd=work, check=True)


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


def brief(row: dict, work: Path) -> dict:
    from . import guardface

    master = master_repo()
    local = {f: (work / f).read_text(errors="replace") if (work / f).is_file() and not (work / f).is_symlink()
             else None for f in row["files"]}
    tests = [f for f in row["files"] if "test" in f or "selfcheck" in f or "check" in Path(f).name]
    def readme(text):
        words = {w.lower() for w in re.findall(r"[A-Za-z_]{5,}", row["purpose"] + " " + " ".join(row["files"]))}
        sections = re.split(r"(?m)(?=^## )", text)
        ranked = sorted(sections[1:], key=lambda s: -sum(w in s.lower() for w in words))
        return sections[0][:4000] + "\n" + "\n".join(s[:12000] for s in ranked[:2])
    from .genes import owners

    relevant_genes = {g for f in row["files"] for g in owners.owners_of(f)}
    core = guardface.ask("status")
    database_state = guardface.ask("database_inventory") if row["database"] else {}
    return {"change": row, "commit_message": _git("show", "-s", "--format=%B", row["master"]),
            "master_diff": _git("diff", "--no-ext-diff", row["parent"], row["master"]),
            "master_tests": {f: u._git("show", row["master"] + ":" + f, cwd=master).stdout for f in tests},
            "master_readme": readme(u._git("show", row["master"] + ":README.md", cwd=master).stdout),
            "master_checks_catalogue": u._git("show", row["master"] + ":CONTAINERS.md", cwd=master).stdout,
            "local_files": local, "local_readme": readme((work / "README.md").read_text(errors="replace"))
            if (work / "README.md").is_file() and not (work / "README.md").is_symlink() else "",
            "local_changes": _git("log", "-40", "--format=%B", cwd=work),
            "genes": {p.name: p.read_text() for p in (work / "rouh/genes/manifests").glob("*.json")
                      if p.stem in relevant_genes and not p.is_symlink()},
            "all_gene_names": [p.stem for p in (work / "rouh/genes/manifests").glob("*.json")],
            "protected_core": {k: core.get(k) for k in ("version", "features")},
            "local_schema": database_state.get("schema", []),
            "local_migration_history": database_state.get("migrations", []),
            "local_migrations": {p.name: p.read_text() for p in (work / "rouh/migrations").glob("*.py")
                                 if row["database"] and not p.is_symlink()
                                 and u._git("cat-file", "-e", row["parent"] + ":rouh/migrations/" + p.name,
                                                              cwd=master).returncode},
            "database": row["database"], "security": row["security"]}


def _path(work: Path, name: str) -> Path:
    p = work / name
    resolved, root = p.resolve(), work.resolve()
    if not name or name.startswith("-") or ".git" in Path(name).parts or not resolved.is_relative_to(root) \
            or ".git" in resolved.relative_to(root).parts:
        raise u.Refused("The adapting job proposed a file outside its checkout.")
    return p


def adapt(row: dict, work: Path, feedback: str = "") -> dict:
    """One bounded planning/build pass; all tests and the migration gate run in the core afterwards."""
    from . import llm

    model = model_pick()  # Before every request; no cheaper fallback, including on a retry.
    context = brief(row, work)
    context["previous_check"] = feedback
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


def dependencies(row: dict, previous: list[dict]) -> list[dict]:
    imports = imports_of(row) if any(p.get("status") not in TAKEN for p in previous) else set()
    return [p for p in previous if p.get("status") not in TAKEN and
            (set(row["files"]) & set(p["files"]) or imports.intersection(_module(f) for f in p["files"])
             or any(p["master"].startswith(d) for d in row["depends_on"]))]


def _waiting(doc: dict, row: dict, reason: str, status: str = "waiting") -> None:
    row.update(status=status, reason=reason, at=time.time())
    save(doc)


def _propose(doc: dict, row: dict, rel: dict, by: str, work: Path, plan: dict, copied: bool) -> bool:
    from . import guardface

    if (guardface.ask("status").get("features") or {}).get("master_changes") != 1:
        raise u.Refused("needs the protected core's per-change update and database rehearsal gate")
    u._git("add", "-A", cwd=work, check=True)
    u._git("commit", "-q", "--allow-empty", "-m", row["purpose"], "-m", "Rouh-master-change: " + row["master"],
           cwd=work, check=True)
    commit = _git("rev-parse", "HEAD", cwd=work)
    u._git("fetch", "-q", str(work), "+HEAD:refs/rouh/update/change", cwd=u.code_dir(), check=True)
    backup = u._backup(u.code_dir(), False)
    pending = {"release": rel["commit"], "label": u.label(rel["commit"], rel), "commit": commit,
               "at": time.time(), "by": by, "master_change": row["master"],
               "change_status": "copied" if copied else "adapted", "backup": backup,
               "reason": plan.get("reason", "Every touched file still matched master."),
               "continuation": rel}
    u._change(pending=pending)
    # Sensitive exact copies still need a frontier job's proof. The protected core owns every gate.
    evidence = {"master": row["master"], "database": row["database"], "security": row["security"],
                "proof": plan.get("proof", ""), "database_plan": plan.get("database_plan"),
                "not_applicable": bool(plan.get("not_applicable")),
                "model": plan.get("model", ""), "reason": plan.get("reason", "")}
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
    for i, row in enumerate(doc["changes"]):
        if row.get("status") in TAKEN:
            continue
        deps = dependencies(row, doc["changes"][:i])
        if deps:
            _waiting(doc, row, "Depends on: " + "; ".join(d["purpose"] for d in deps), "depends")
            continue
        copied = exact(row, work)
        sensitive = row["database"] or row["security"]
        start = _git("rev-parse", "HEAD", cwd=work)
        feedback = ""
        for attempt in range(3 if not copied or sensitive else 1):
            u._step(("checking" if copied else "adapting") + ": " + row["purpose"])
            u._git("reset", "--hard", start, cwd=work, check=True)
            u._git("clean", "-fdq", cwd=work, check=True)
            try:
                if copied and not sensitive:
                    _copy(row, work)
                    plan = {} if row["files"] else {"reason": "Release tooling only; those files are not installed in this Rouh's own code."}
                else:
                    model_pick()
                    plan = adapt(row, work, feedback)
                if any(f in u.LIBRARIES for f in row["files"]):
                    u._libraries(work)
                if _propose(doc, row, rel, by, work, plan, copied and not sensitive):
                    # A restart may interrupt here. The durable continuation precedes the proposal.
                    return
                return
            except (u.Refused, ValueError) as exc:
                feedback = str(exc)
                dependent = dependencies(row, doc["changes"][:i])
                _waiting(doc, row, feedback, "depends" if dependent else "waiting")
                if "frontier model" in feedback or dependent:
                    break
            except Exception as exc:  # A failed model call never blocks an unrelated exact change.
                feedback = f"The adapting job could not finish ({type(exc).__name__})."
                _waiting(doc, row, feedback)
                break
        u._git("reset", "--hard", start, cwd=work, check=True)
        u._git("clean", "-fdq", cwd=work, check=True)
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
            "told": previous.get("id") == fingerprint and previous.get("told", False),
            "came_in": [{"purpose": r["purpose"], "status": r["status"]} for r in came_in],
            "waiting": [{"purpose": r["purpose"], "reason": r["reason"], "urgent": r["urgent"]} for r in waiting]}
    urgent = any(r["urgent"] for r in waiting)
    u._change(busy=None, pending=None, continue_update=None, last=last,
              retry_at=time.time() + (1800 if urgent else 86400),
              retry_release=rel if waiting else None)
