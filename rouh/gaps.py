"""The ten gaps between this hand-written agent loop and the Claude Agent SDK.

Why a file rather than a page of markup: the status page has to say what is
true, and the only way it can is by reading the same record the work itself
updates. `gaps.json` beside this module is that record. The page fetches it
through `/api/gaps`, the command below is how a row is moved on, and nothing
anywhere writes a status into HTML.

A status is one of `STATUSES`, in that order, and only the last of them counts
as done. That is the house rule: a change that passes its tests and sits on a
branch is not finished, and a row that says so is a row that lies.

To move a row on:

    python -m rouh.gaps set context-editing "merged to main" --commit abc1234
    python -m rouh.gaps set context-editing deployed --commit abc1234
    python -m rouh.gaps show
"""
from __future__ import annotations

import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))

#: The record itself. One file, in the repository, next to the code it is about.
#:
#: ROUH_GAPS_FILE moves it, and exists for one reason: a test that wants to
#: watch a row move on the page must not write to the repository's own copy.
#: Nothing in production sets it.
PATH = os.environ.get("ROUH_GAPS_FILE", "").strip() or os.path.join(HERE, "gaps.json")

#: Every status a gap may be in, from untouched to running in production.
#: The order is the order of the work, and the page draws a row's progress
#: from where its status sits in this list.
STATUSES = (
    "not started",
    "in progress",
    "built",
    "tests passing",
    "merged to main",
    "deployed",
)

#: The only one that counts as done.
DONE = "deployed"


class Unknown(ValueError):
    """A gap id or a status that is not in the record."""


def normalise(status: str) -> str:
    """A status as the record keeps it: lower case, spaces, nothing else.

    The page shows "DEPLOYED" in capitals because it is the one that matters,
    and a person typing it at the command line will type it that way. What is
    written down is always the lower-case form.
    """
    value = " ".join(str(status or "").split()).lower()
    if value not in STATUSES:
        raise Unknown(f"{status!r} is not a status. They are: {', '.join(STATUSES)}.")
    return value


def load(path: str = "") -> dict:
    """The whole record, as it is on disk."""
    with open(path or PATH, encoding="utf-8") as fh:
        return json.load(fh)


def save(record: dict, path: str = "") -> None:
    """Write the record back, formatted so a diff of it reads."""
    with open(path or PATH, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def gaps(path: str = "") -> list[dict]:
    """Every gap, in the order they are worked."""
    return list(load(path).get("gaps", []))


def find(gap_id: str, path: str = "") -> dict:
    for gap in gaps(path):
        if gap.get("id") == gap_id:
            return gap
    known = ", ".join(g.get("id", "") for g in gaps(path))
    raise Unknown(f"There is no gap called {gap_id!r}. They are: {known}.")


def summary(path: str = "") -> dict:
    """How many gaps there are and how many are actually done.

    Counted here rather than in the page, so the speech and the screen can
    never disagree about it.
    """
    rows = gaps(path)
    return {
        "total": len(rows),
        "deployed": sum(1 for g in rows if g.get("status") == DONE),
        "started": sum(1 for g in rows if g.get("status") != STATUSES[0]),
    }


def set_status(gap_id: str, status: str, *, commit: str = "", when: str = "",
               path: str = "") -> dict:
    """Move one gap to a status, and write down the commit and the day.

    The commit is kept short, the way the repository's own log prints it, and
    the day is written the moment the status becomes `deployed`, because that
    is the only date anybody asks about.
    """
    status = normalise(status)
    record = load(path)
    for gap in record.get("gaps", []):
        if gap.get("id") != gap_id:
            continue
        gap["status"] = status
        if commit:
            gap["commit"] = commit.strip()[:12]
        if status == DONE:
            gap["deployed"] = when or date.today().isoformat()
        elif when:
            gap["deployed"] = when
        save(record, path)
        return gap
    known = ", ".join(g.get("id", "") for g in record.get("gaps", []))
    raise Unknown(f"There is no gap called {gap_id!r}. They are: {known}.")


def lines(path: str = "") -> list[str]:
    """The record as plain text, one gap a line, for the model and the terminal."""
    out = []
    for gap in gaps(path):
        tail = ""
        if gap.get("commit"):
            tail += f", commit {gap['commit']}"
        if gap.get("deployed"):
            tail += f", deployed {gap['deployed']}"
        status = gap.get("status", "")
        shown = status.upper() if status == DONE else status
        out.append(f"{gap.get('number')}. {gap.get('name')}: {shown}{tail}")
    return out


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m rouh.gaps",
                                     description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show", help="print every gap and where it is")
    setter = sub.add_parser("set", help="move one gap to a status")
    setter.add_argument("id")
    setter.add_argument("status")
    setter.add_argument("--commit", default="")
    setter.add_argument("--when", default="")
    args = parser.parse_args(argv)

    if args.command == "show":
        print("\n".join(lines()))
        return 0
    gap = set_status(args.id, args.status, commit=args.commit, when=args.when)
    print(f"{gap['name']}: {gap['status']}"
          + (f", commit {gap['commit']}" if gap.get("commit") else "")
          + (f", deployed {gap['deployed']}" if gap.get("deployed") else ""))
    return 0


if __name__ == "__main__":  # pragma: no cover - the command line
    import sys

    raise SystemExit(_main(sys.argv[1:]))
