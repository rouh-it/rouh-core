"""Rouh merges a clash itself: the rung of ``land.sh`` that used to ask the person.

Petar's standing instruction is that Rouh resolves merge clashes and he is not
asked. On 18 October 2026 he was asked eight times and none of it needed him
(card 1684), so the ladder in ``land.sh`` no longer ends at the person. When a
replay still collides after the worker that wrote the code has had it back
(attempt two), or when both sides rewrote the same file, ``land.sh`` stops the
rebase at the collision and runs this.

What it does, in the checkout, with the rebase stopped:

1. Reads what collides (``git diff --diff-filter=U``), both sides' diffs and
   commit messages, and the run's brief - the request the work was for.
2. Runs one Claude Code pass in the checkout with all of that, told to write
   the version of each colliding file that keeps both intents, editing only
   those files, and to end with one line of JSON saying what it did. Only when
   the two sides truly want opposite things - one deletes or reverses what the
   other adds, and both cannot hold - does it leave the files alone and say
   so, with which side it recommends and why.
3. Checks what came back: not one conflict marker left, every Python, JSON
   and shell file it touched still parses, and nothing outside the colliding
   files changed (anything else it touched is put back). Then it stages the
   files, which is what lets ``land.sh`` carry on with the rebase, and rerere
   records the resolution so the same collision resolves itself next time.

It prints one JSON object as its last line, which is what ``land.sh`` reads:

    {"outcome": "merged",   "files": [...], "how": "...", ...}
    {"outcome": "opposite", "why": "...", "recommend": 1 or 2, "recommend_why": "..."}
    {"outcome": "failed",   "why": "..."}

A failure is never a question for the person: it is Rouh's own pass that could
not finish (no Claude Code here, a timeout, markers left behind), and the work
goes back to the ladder's earlier rungs with the reason, kept on its branch.

The model is Rouh's pick for "Merging a clash" on the Models page, which Rouh
writes into the landing directory because this runs as whichever user lands
the work and cannot read Rouh's database (`write_merge_pick`). The
same file carries what the prompt's owner marks say (`rouh/owner.py`), so the
prompt names the installation's owner without a database; without it, it
says "the owner".

Standard library only, like ``rouh/conflicts.py``, because ``land.sh`` runs it
as a command in any checkout::

    PYTHONPATH=<the rouh checkout> python3 -m rouh.merge_pass --repo . \\
        --base <sha> --head <sha> --target-ref origin/main
"""
from __future__ import annotations

import argparse
import contextlib
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: How long the pass gets. A collision is a handful of hunks; a pass still
#: going after this is not going to finish well.
TIMEOUT = 1200

#: How much of each side's diff and of the brief the pass is shown.
DIFF_LIMIT = 30_000
BRIEF_LIMIT = 8_000

#: A conflict marker, at the start of a line, as git writes them in diff3 style.
MARKER = re.compile(r"^(<{7}|\|{7}|>{7})( |$)|^={7}$", re.M)

#: The tools the pass may use. It edits files and reads history; it never
#: commits, rebases or pushes - that is ``land.sh``'s, under its lock.
TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")
ALLOWED = ("Read", "Edit", "Write", "Glob", "Grep", "Bash(git diff:*)", "Bash(git log:*)",
           "Bash(git show:*)", "Bash(git status:*)", "Bash(git blame:*)")

PROMPT = """You are Rouh's merge pass. Two pieces of work collide, and ‹owner› has asked that Rouh resolve such clashes itself rather than ask ‹him›. You are in a git checkout with a rebase stopped at the collision.

## What the job was asked to do (its brief)

{brief}

## The job's side: what it wrote

{mine_messages}

```diff
{mine_diff}
```

## Main's side: what landed while the job worked

{theirs_messages}

```diff
{theirs_diff}
```

## The commit being replayed now

{stopped}

## The files that collide

{files}

Each file holds conflict markers in diff3 style: `<<<<<<<` main's side (with any of the job's commits already replayed), `|||||||` the version both started from, `=======`, then the job's side up to `>>>>>>>`.{deleted}

## What to do

1. Read each colliding file whole, and read both diffs above, until you know what each side was for.
2. Write, in place, the version of each file that does both: everything main's side meant and everything the job meant. That may mean writing something neither side wrote. Never drop one side to make the other fit, and never leave a conflict marker.
3. Edit only the files listed above. Do not run any git command that changes anything (no add, commit, rebase, checkout, reset or push), do not start servers and do not run tests: the checks after you are not yours.
4. If, and only if, the two sides truly want opposite things - one deletes or reverses what the other adds, and both cannot hold at once - change nothing and say so.

End your reply with exactly one line of JSON and nothing after it, one of:

{{"verdict": "merged", "how": "<one plain sentence: what each side kept>"}}
{{"verdict": "opposite", "why": "<one plain sentence: what each side wants and why both cannot hold>", "recommend": <1 to keep the job's side, 2 to keep main's>, "recommend_why": "<one plain sentence>"}}
"""


#: The file in the landing directory that says which model Rouh's merge pass
#: runs on. ``land.sh`` runs in any checkout as any user and cannot read Rouh's
#: database, so Rouh writes its pick there (Anatomy, Behaviour, Models, "Merging a clash")
#: when it starts and whenever the pick changes (`modeldefaults`).
MERGE_PICK = "merge-pass.json"


def write_merge_pick(model: str, effort: str = "", *, cfg: Any = None,
                     words: dict | None = None) -> bool:
    """Write the merge pass's model and level where ``land.sh`` reads them. Never raises.

    `words` is what each owner mark says for the installation's owner
    (`owner.words`), so the merge pass, which cannot read the database, names
    them in its prompt; without it the prompt says "the owner".
    """
    # Share the landing-file mechanics without an import-time cycle: conflicts
    # re-exports this helper for checkouts that have not deployed yet.
    from .conflicts import land_dir, log, write_bytes

    base = land_dir(cfg)
    body = json.dumps({"model": str(model or ""), "effort": str(effort or ""),
                       "owner": {str(k): str(v) for k, v in (words or {}).items()},
                       "at": time.time()}, ensure_ascii=False) + "\n"
    try:
        if not base.is_dir():
            return False
        place = base / MERGE_PICK
        if not write_bytes(place, body):
            return False
        with contextlib.suppress(OSError):
            os.chmod(place, 0o664)
        return True
    except OSError as exc:
        log.warning("could not write the merge pass's model to %s (%s)", base, exc)
        return False


def read_merge_pick(where: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """The merge pass's model and level, or blanks for Claude Code's own."""
    from .conflicts import land_dir

    base = Path(where) if where else land_dir()
    try:
        got = json.loads((base / MERGE_PICK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"model": "", "effort": ""}
    if not isinstance(got, dict):
        return {"model": "", "effort": ""}
    return {"model": str(got.get("model") or ""), "effort": str(got.get("effort") or "")}


def git(repo: str, *args: str, check: bool = False) -> tuple[int, str]:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          errors="replace", check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()[:300]}")
    return proc.returncode, proc.stdout


def colliding(repo: str) -> dict[str, str]:
    """Every unmerged path, with git's two-letter code for how it collides."""
    _, out = git(repo, "status", "--porcelain=v1", "-z")
    found: dict[str, str] = {}
    for entry in out.split("\0"):
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "U" in code or code in ("AA", "DD"):
            found[path] = code
    return found


def changed_elsewhere(repo: str) -> tuple[set[str], set[str]]:
    """What differs from the index outside the collision: edited tracked files, new files."""
    _, edited = git(repo, "diff", "--name-only", "-z")
    _, new = git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return ({p for p in edited.split("\0") if p}, {p for p in new.split("\0") if p})


def _fill(text: str, said: dict) -> str:
    """The prompt with its owner marks filled in from the landing directory's words, or "the owner"."""
    from . import owner

    table = owner.words(None)
    table.update({k: str(v) for k, v in (said or {}).items() if k in table and isinstance(v, str) and v})
    return owner.say(text, said=table)


def find_claude() -> str:
    """Claude Code, wherever this user has it. "" when it is nowhere."""
    said = os.environ.get("ROUH_MERGE_CLAUDE") or os.environ.get("ONE_CLAUDE") or ""
    if said and os.access(said, os.X_OK):
        return said
    found = shutil.which("claude")
    if found:
        return found
    home = os.path.expanduser("~")
    for pattern in (f"{home}/.local/bin/claude", f"{home}/.nvm/versions/node/*/bin/claude",
                    "/usr/local/bin/claude", "/usr/bin/claude"):
        for place in sorted(glob.glob(pattern), reverse=True):
            if os.access(place, os.X_OK):
                return place
    return ""


def read_brief(brief_file: str, beside: str) -> str:
    for place in (brief_file, os.path.join(beside, "brief.md") if beside else ""):
        if place and os.path.isfile(place):
            try:
                text = Path(place).read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            if text:
                return text[:BRIEF_LIMIT]
    return "It was not written down: read what each side's commits say they were for."


def side(repo: str, base: str, tip: str, files: list[str]) -> tuple[str, str]:
    _, messages = git(repo, "log", "--format=- %s", f"{base}..{tip}", "--", *files)
    _, diff = git(repo, "diff", f"{base}..{tip}", "--", *files)
    return (messages.strip() or "- (it did not say)"), (diff[:DIFF_LIMIT] or "(no diff)")


def last_json(text: str) -> dict[str, Any] | None:
    """The last line of the reply that is a JSON object, which is the verdict."""
    for line in reversed([l.strip() for l in (text or "").splitlines() if l.strip()]):
        line = line.strip("`")
        if line.startswith("{") and line.endswith("}"):
            try:
                got = json.loads(line)
            except ValueError:
                continue
            if isinstance(got, dict) and got.get("verdict"):
                return got
    return None


def still_broken(repo: str, path: str) -> str:
    """Why a file the pass wrote cannot be kept, or "" when it can."""
    full = os.path.join(repo, path)
    try:
        text = Path(full).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"{path} could not be read ({exc})"
    if MARKER.search(text):
        return f"{path} still holds a conflict marker"
    if path.endswith(".py"):
        try:
            compile(text, path, "exec")
        except SyntaxError as exc:
            return f"{path} no longer parses as Python: {exc.msg} on line {exc.lineno}"
    elif path.endswith(".json"):
        try:
            json.loads(text)
        except ValueError as exc:
            return f"{path} is no longer valid JSON: {exc}"
    elif path.endswith(".sh") or text.startswith("#!/usr/bin/env bash") or text.startswith("#!/bin/bash"):
        proc = subprocess.run(["bash", "-n", full], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return f"{path} no longer parses as shell: {proc.stderr.strip()[:200]}"
    elif path.endswith((".js", ".mjs")) and shutil.which("node"):
        proc = subprocess.run(["node", "--check", full], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return f"{path} no longer parses as JavaScript: {proc.stderr.strip()[:200]}"
    return ""


def run(args: argparse.Namespace) -> dict[str, Any]:
    repo = os.path.abspath(args.repo)
    files = colliding(repo)
    if not files:
        return {"outcome": "failed", "why": "the rebase is not stopped at a collision"}
    claude = find_claude()
    if not claude:
        return {"outcome": "failed", "why": "Claude Code is not on this machine for this user"}
    names = sorted(files)
    deleted = [f"`{p}` was deleted by {'main' if code in ('DU', 'DA') else 'the job'}"
               for p, code in files.items() if code in ("DU", "UD", "DA", "AD")]
    mine_messages, mine_diff = side(repo, args.base, args.head, names)
    theirs_messages, theirs_diff = side(repo, args.base, args.target_ref, names)
    _, stopped = git(repo, "log", "-1", "--format=%h %s", "REBASE_HEAD")
    prompt = PROMPT.format(
        brief=read_brief(args.brief_file, args.beside),
        mine_messages=mine_messages, mine_diff=mine_diff,
        theirs_messages=theirs_messages, theirs_diff=theirs_diff,
        stopped=stopped.strip() or "(not known)",
        files="\n".join(f"- `{p}`" for p in names),
        deleted=("\n\n" + "; ".join(deleted) + ". Keeping such a file means writing it whole; "
                 "letting it go means deleting it.") if deleted else "",
    )
    edited_before, new_before = changed_elsewhere(repo)
    argv = [claude, "-p", "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--permission-mode", "acceptEdits",
            "--tools", *TOOLS, "--allowedTools", *ALLOWED]
    pick = {"model": args.model, "effort": args.effort}
    said: dict = {}
    if args.land_dir:
        try:
            got = json.loads(Path(args.land_dir, MERGE_PICK).read_text(encoding="utf-8"))
            if not pick["model"]:
                pick = {"model": str(got.get("model") or ""), "effort": str(got.get("effort") or "")}
            if isinstance(got.get("owner"), dict):
                said = got["owner"]
        except (OSError, ValueError, AttributeError):
            pass
    prompt = _fill(prompt, said)
    if pick["model"]:
        argv += ["--model", pick["model"]]
    if pick["effort"]:
        argv += ["--effort", pick["effort"]]
    env = dict(os.environ, CLAUDE_CODE_DISABLE_CLAUDE_MDS="1")
    try:
        proc = subprocess.run(argv, input=prompt, cwd=repo, capture_output=True, text=True,
                              errors="replace", timeout=args.timeout, env=env, check=False)
    except subprocess.TimeoutExpired:
        put_back(repo, names, edited_before, new_before)
        return {"outcome": "failed", "why": f"Rouh's merge pass took longer than {args.timeout}s"}
    except OSError as exc:
        return {"outcome": "failed", "why": f"Claude Code could not be started: {exc}"}
    reply, cost = proc.stdout, None
    try:
        said = json.loads(proc.stdout)
        if isinstance(said, dict):
            reply = str(said.get("result") or "")
            cost = said.get("total_cost_usd")
            if said.get("is_error"):
                put_back(repo, names, edited_before, new_before)
                return {"outcome": "failed", "why": f"Claude Code said: {reply.strip()[:300]}"}
    except ValueError:
        pass
    touched = put_back(repo, names, edited_before, new_before)
    verdict = last_json(reply)
    about = {"model": pick["model"] or "Claude Code's own default", "cost_usd": cost,
             "files": names}
    if touched:
        about["put_back"] = touched
    if verdict is None:
        tail = (reply or proc.stderr or "").strip()[-300:]
        return {"outcome": "failed", "why": f"the merge pass ended without a verdict: {tail}",
                **about}
    if verdict.get("verdict") == "opposite":
        recommend = verdict.get("recommend")
        return {"outcome": "opposite", "why": str(verdict.get("why") or "")[:400],
                "recommend": recommend if recommend in (1, 2) else None,
                "recommend_why": str(verdict.get("recommend_why") or "")[:400], **about}
    if verdict.get("verdict") != "merged":
        return {"outcome": "failed", "why": f"the merge pass said {verdict!r}", **about}
    problems = []
    for path in names:
        if not os.path.lexists(os.path.join(repo, path)):
            continue
        why = still_broken(repo, path)
        if why:
            problems.append(why)
    if problems:
        return {"outcome": "failed", "why": "; ".join(problems)[:600], **about}
    for path in names:
        if os.path.lexists(os.path.join(repo, path)):
            git(repo, "add", "--", path)
        else:
            git(repo, "rm", "-q", "--cached", "--ignore-unmatch", "--", path)
    left = colliding(repo)
    if left:
        return {"outcome": "failed", "why": f"still unmerged: {', '.join(sorted(left))}", **about}
    return {"outcome": "merged", "how": str(verdict.get("how") or "")[:400], **about}


def put_back(repo: str, names: list[str], edited_before: set[str], new_before: set[str]) -> list[str]:
    """Undo anything the pass changed outside the colliding files. What it put back."""
    edited, new = changed_elsewhere(repo)
    undone = []
    for path in sorted(edited - edited_before - set(names)):
        git(repo, "checkout", "--", path)
        undone.append(path)
    for path in sorted(new - new_before - set(names)):
        try:
            os.remove(os.path.join(repo, path))
            undone.append(path)
        except OSError:
            pass
    return undone


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python3 -m rouh.merge_pass")
    p.add_argument("--repo", default=".")
    p.add_argument("--base", required=True)
    p.add_argument("--head", required=True)
    p.add_argument("--target-ref", required=True)
    p.add_argument("--brief-file", default="")
    p.add_argument("--beside", default="")
    p.add_argument("--land-dir", default=os.environ.get("ROUH_LAND_DIR", ""))
    p.add_argument("--model", default=os.environ.get("ROUH_MERGE_MODEL", ""))
    p.add_argument("--effort", default=os.environ.get("ROUH_MERGE_EFFORT", ""))
    p.add_argument("--timeout", type=int, default=TIMEOUT)
    args = p.parse_args(argv)
    try:
        out = run(args)
    except Exception as exc:  # the answer is always one JSON line
        out = {"outcome": "failed", "why": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(out))
    return 0


if __name__ == "__main__":  # pragma: no cover - a command land.sh runs
    raise SystemExit(main(sys.argv[1:]))
