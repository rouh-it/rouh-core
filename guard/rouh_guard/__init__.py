"""The protected core of a Rouh: ``rouh-guard`` (task 98, step 98-23, 24 October 2026).

The small set of safety and repair parts that a Rouh uses and cannot edit, shipped as an image
of its own and updated only by the makers' signed releases: the key proxy, the base check with the
frozen security checks, the start scripts, the signature check on a shared gene, the doctor, and
the change step that keeps undo points. ``guard/README.md`` has the whole of it.

A Rouh never imports this. It talks to the protected core through four numbered contracts,
``CONTRACTS``; within one number the core only adds, and never removes or changes, and an old
number is kept for at least a year.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
VERSION = (HERE.parent / "VERSION").read_text().strip() if (HERE.parent / "VERSION").is_file() else "0.0.0"

#: Each contract and the numbers this core answers.
#:   keys       HTTP to the key proxy: /anthropic/..., /openai/..., /health
#:   changes    the socket /run/guard/guard.sock: status, points, propose, undo, verify, gene
#:   check      the last line a check prints, "ROUH-CHECK {json}"
#:   checkface  the calls the frozen security checks make of rouh/checkface.py
CONTRACTS = {"keys": [1], "changes": [1], "check": [1], "checkface": [1]}


def version_key(v: str) -> tuple[int, ...]:
    out = []
    for p in str(v or "").split("."):
        if not p.isdigit():
            return ()
        out.append(int(p))
    return tuple(out + [0] * (3 - len(out)))


def satisfies(need: str, have: str = VERSION) -> bool:
    """Whether this core's version satisfies a gene's needs_guard, such as ">=1.3" or "1.3"."""
    need = str(need or "").strip()
    if not need:
        return True
    for op in (">=", "=="):
        if need.startswith(op):
            want = version_key(need[len(op):].strip())
            if not want:
                return False
            return version_key(have) >= want if op == ">=" else version_key(have) == want
    want = version_key(need)
    return bool(want) and version_key(have) >= want
