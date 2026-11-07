"""``python -m rouh.hostguard``: no code tied to the old server's layout without saying so.

Petar, 5 November 2026: since Rouh moved into containers on 31 October 2026, code that still
assumed the server - a systemd service called rouh, its settings in /var/www/rouh/.env, the app in
/var/www/rouh/app - kept failing quietly. The nightly Synapse worker ran
`deploy/with-rouh-env.sh`, which copies the service's environment through systemd, and every call
said "System has not been booted with systemd"; five nights went by with a failure and no reason.

So every place in Rouh's code, the one program and `bin/` that names the server's layout
(`PATTERN`) is listed in `hostpaths.json` with why it is right: a server default the containers'
image overrides, documentation of the server, a feature that is off in the containers, or code that
already knows which it is on. A new mention, in a file not listed or one more in a file that is,
fails until it is looked at and either made to work in the containers or added to the list with
its reason. The deploy tools (`deploy/`, `one/deploy/`, `land.sh`, `update-all.sh`) are the server's own and are
not read.

The protected core runs it with Rouh's own checks on every change of its code
(`rouh/selfcheck/own.py`), and `land.sh` before it pushes work that touches Python (`host_guard`).
Standard library only.

    python -m rouh.hostguard            check; the last line says what it found
    python -m rouh.hostguard --list     every file with a mention, and how many
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
PATTERN = re.compile(r"with-rouh-env|systemctl|systemd-run|/var/www/rouh|journalctl")
#: Where code that runs, and briefs that jobs are given, live.
ROOTS = ("rouh", "one", "bin")
#: The test worlds' stand-ins, the migrations' history, the committed checks, and this list itself.
SKIP = ("rouh/testing/", "rouh/selfcheck/", "one/tests/", "one/deploy/", "rouh/static/", "rouh/hostguard.py",
        "rouh/hostpaths.json", "rouh/genes/owners.json")
SUFFIXES = (".py", ".md", ".sh", ".txt", "")
LISTED = Path(__file__).with_name("hostpaths.json")


def _files() -> list[Path]:
    out = []
    for root in ROOTS:
        base = CODE / root
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            rel = path.relative_to(CODE).as_posix()
            if not path.is_file() or rel.startswith(SKIP) or "/migrations/" in rel or "__pycache__" in rel:
                continue
            if path.suffix not in SUFFIXES or (path.suffix == "" and root != "bin"):
                continue
            out.append(path)
    return sorted(out)


def found() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = sum(1 for line in text.splitlines() if PATTERN.search(line))
        if n:
            counts[path.relative_to(CODE).as_posix()] = n
    return counts


def listed() -> dict[str, dict]:
    return json.loads(LISTED.read_text(encoding="utf-8"))["files"]


def problems() -> list[str]:
    allowed = listed()
    out = []
    for rel, n in sorted(found().items()):
        said = allowed.get(rel)
        if said is None:
            out.append(f"FAIL {rel}: {n} line(s) name the old server's layout (systemd, /var/www/rouh, "
                       "with-rouh-env.sh), and it is not in rouh/hostpaths.json. Make it work in the "
                       "containers too, or list it there with why it is right as it is.")
        elif n > int(said.get("lines") or 0):
            out.append(f"FAIL {rel}: {n} line(s) name the old server's layout, {said.get('lines')} are listed "
                       f"({said.get('why')}). Look at the new one: make it work in the containers, or raise the "
                       "count in rouh/hostpaths.json with why.")
    return out


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for rel, n in sorted(found().items()):
            print(f"{n:3}  {rel}")
        return 0
    bad = problems()
    for line in bad:
        print(line)
    if bad:
        print(f"{len(bad)} file(s) name the old server's layout without saying why that is right.")
        return 1
    print(f"Every mention of the old server's layout is accounted for ({len(found())} files, rouh/hostpaths.json).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
