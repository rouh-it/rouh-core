"""One number, one task: what `land.sh` asks before it pushes anything to main.

A task's number is what the person says out loud - "open fifty-six" - and its
id is `task-<number>`, so two folders with one number are two tasks answering
to the same name. That happened three times by 23 September 2026, and every
time for the same reason: two things made the task, and neither could see the
other. Rouh made task 56 in the server's own checkout and never saved it, and
the job Rouh started for the same request made its own task 56 in a checkout
of main, where Rouh's was not; the page then flipped between the two. Task 51
was two pieces of work under one number the same way, and task 02 was a move
the next deploy half undid.

Rouh saves what it makes now (`rouh/saving.py`), so main holds every task
there is. This is the other half, and the one that does not depend on anybody
remembering anything: whatever wrote the commit, a landing that would leave
main with a task number or an object id on two folders is refused before it is
pushed, with the sentence that says which folders and what to do about it.
Only what this landing would add is refused. Main as it already is is never a
reason to stop somebody else's work.

Standard library only, and run as `python -m rouh.numbering check` from the
directory `land.sh` is in, because `land.sh` lands checkouts of this
repository with nothing installed. It fails open: a check that cannot read the
tree says so on stderr and lets the landing go on, because a guard that breaks
every landing is worse than the duplicate it is there to stop.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

from . import gitutil

#: Where the workspace is in a repository that holds it as a folder of its own
#: rather than as the whole of it: Rouh's code repository until the workspace
#: became a repository of its own (21 October 2026). Every question below works
#: out which of the two it is looking at (`prefix_at`), so a landing of either
#: kind is checked the same way.
PREFIX = "workspace/"
#: The file that says a tree is a workspace (`objecttree.MAP_FILE`).
MAP_FILE = "_migration-map.json"
#: A numbered task's folder: the number, a dot, the slug. A step is
#: `56-01.name`, with a dash, and its number is only its task's.
NUMBERED = re.compile(r"^(\d+)\.[^/]+$")
#: An object's sidecar inside its folder, and the one kept beside a folder that
#: is a repository of its own (`objecttree.sidecar_path`).
SIDECAR = ".object.json"
BESIDE = re.compile(r"^\.object\.(.+)\.json$")


def _git(repo: str, *args: str, feed: bytes | None = None) -> bytes:
    done = gitutil.run(repo, *args, timeout=120, text=False, feed=feed)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.decode("utf-8", "replace").strip()
                           or f"git {args[0]} failed")
    return done.stdout


def prefix_at(repo: str, rev: str) -> str:
    """Where the workspace is in this repository at `rev`: "" when it is the
    whole repository, `workspace/` when it is a folder in it, and "" again when
    neither holds a workspace, so there is simply nothing to find."""
    for prefix in ("", PREFIX):
        if gitutil.run(repo, "cat-file", "-e", f"{rev}:{prefix}{MAP_FILE}",
                       timeout=60).returncode == 0:
            return prefix
    return ""


def objects_at(repo: str, rev: str, prefix: str | None = None) -> list[dict]:
    """Every object folder in the workspace at `rev`: its folder, id and type.

    Folders are paths in the repository, so in a repository that holds the
    workspace as `workspace/` they start with it, and in the workspace's own
    repository they do not."""
    prefix = prefix_at(repo, rev) if prefix is None else prefix
    spec = ["--", prefix] if prefix else []
    # --full-tree: from a folder inside the repository, ls-tree would list only that folder.
    names = [n for n in _git(repo, "ls-tree", "-r", "-z", "--full-tree", "--name-only", rev,
                             *spec).decode("utf-8", "replace").split("\0") if n]
    wanted: list[tuple[str, str]] = []
    for name in names:
        where, base = os.path.split(name)
        if base == SIDECAR:
            wanted.append((name, where))
            continue
        beside = BESIDE.match(base)
        if beside:
            wanted.append((name, f"{where}/{beside.group(1)}"))
    if not wanted:
        return []
    feed = "".join(f"{rev}:{name}\n" for name, _ in wanted).encode("utf-8")
    raw = _git(repo, "cat-file", "--batch", feed=feed)
    out = []
    at = 0
    for _name, folder in wanted:
        end = raw.index(b"\n", at)
        header = raw[at:end].split()
        at = end + 1
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
        body, at = raw[at:at + size], at + size + 1
        try:
            node = json.loads(body.decode("utf-8"))
        except ValueError:
            continue
        if isinstance(node, dict):
            out.append({"folder": folder, "id": str(node.get("id") or ""),
                        "type": str(node.get("type") or "")})
    return out


def numbered(objs: list[dict]) -> dict[int, list[str]]:
    """Each task number, and the folders that carry it."""
    out: dict[int, list[str]] = defaultdict(list)
    for node in objs:
        found = NUMBERED.match(os.path.basename(node["folder"]))
        if found and node["type"] == "task":
            out[int(found.group(1))].append(node["folder"])
    return out


def by_id(objs: list[dict]) -> dict[str, list[str]]:
    """Each object id, and the folders that carry it."""
    out: dict[str, list[str]] = defaultdict(list)
    for node in objs:
        if node["id"]:
            out[node["id"]].append(node["folder"])
    return out


def next_free(objs: list[dict]) -> int:
    """The number after the highest one there is."""
    return max(numbered(objs), default=0) + 1


def added(before: list[dict], after: list[dict]) -> list[str]:
    """What `after` holds twice that `before` did not, in sentences.

    Twice, or more, and more of it than there was: a folder moved from one
    project to another is still one folder, and a duplicate main already had
    is somebody else's to mend, not a reason to stop this landing.
    """
    return [sentence for sentence, _new in doubled(before, after)]


def doubled(before: list[dict], after: list[dict]) -> list[tuple[str, list[str]]]:
    """`added`, with the folders each sentence is about: the ones this adds."""
    said: list[tuple[str, list[str]]] = []
    told: list[set[str]] = []
    was, now = numbered(before), numbered(after)
    free = next_free(after)
    for number, folders in sorted(now.items()):
        if len(folders) > 1 and len(folders) > len(was.get(number, [])):
            there = sorted(set(folders) & set(was.get(number, []))) or sorted(folders)[:1]
            new = sorted(set(folders) - set(there))
            told.append(set(folders))
            said.append(((
                f"Task {number} would be {len(folders)} tasks on main: "
                f"{', '.join(there)} is already there, and this adds {', '.join(new)}. "
                "One number is one task. If it is the same piece of work, put what you "
                "made into the task that is already there. If it is not, take the next "
                f"free number, {free}, rename the folder, give its .object.json the id "
                f"task-{free} and change every reference to it, then land again."), new))
            free += 1
    ids_was, ids_now = by_id(before), by_id(after)
    for ident, folders in sorted(ids_now.items()):
        if len(folders) > 1 and len(folders) > len(ids_was.get(ident, [])):
            if any(set(folders) <= folders_told for folders_told in told):
                continue   # the same two folders, already said as one number
            there = sorted(set(folders) & set(ids_was.get(ident, []))) or sorted(folders)[:1]
            new = sorted(set(folders) - set(there))
            said.append(((
                f"The id {ident} would be on {len(folders)} folders on main: "
                f"{', '.join(there)} is already there, and this adds {', '.join(new)}. "
                "An id is one object. Give the new one its own id in its .object.json, "
                "then land again."), new))
    return said


def check(repo: str, before: str, after: str) -> list[str]:
    return added(objects_at(repo, before), objects_at(repo, after))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rouh.numbering",
                                 description="one number, one task, on main")
    sub = ap.add_subparsers(dest="what", required=True)
    checked = sub.add_parser("check", help="what a landing would add twice")
    checked.add_argument("--repo", default=".")
    checked.add_argument("--before", required=True, help="main as it is")
    checked.add_argument("--after", default="HEAD", help="main as it would be")
    free = sub.add_parser("next", help="the next free task number")
    free.add_argument("--repo", default=".")
    free.add_argument("--at", default="HEAD")
    args = ap.parse_args(argv)
    try:
        if args.what == "next":
            print(next_free(objects_at(args.repo, args.at)))
            return 0
        said = check(args.repo, args.before, args.after)
    except Exception as exc:  # noqa: BLE001 - it fails open, and says so
        print(f"the task numbers could not be checked, so they were not: {exc}",
              file=sys.stderr)
        return 0
    if said:
        print(" ".join(said))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
