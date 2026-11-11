#!/usr/bin/env python3
"""Holds the stack check (guard/rouh_guard/stackpolicy.py) to the fixtures beside this.

    python3 guard/policy/fixtures/check.py

Each fixture is a stack file resolved by docker compose (make.py); a good one must be let
through, and each hostile one refused with a sentence holding the words expect.json gives. Rouh
for Mac's StackPolicyTests hold StackPolicy.swift to the same files. Each case's own text (its .yml)
is checked too, as the stack file's text is in use. A file of the machine outside the stack folder
is written "@TMP@" in them.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from rouh_guard import stackpolicy  # noqa: E402


def load(name: str) -> dict:
    return json.loads((HERE / f"{name}.json").read_text().replace("@STACK@", str(HERE)).replace("@TMP@", "/tmp/rouh-fixture-elsewhere"))


def main() -> int:
    bad = 0
    for f in ("expect.json", "expect-edge.json"):
        if (HERE / f).is_file():
            bad += one(json.loads((HERE / f).read_text()))
    return 1 if bad else 0


def one(expect: dict) -> int:
    ref = load(expect["reference"])
    bad = 0
    for name, want in expect["cases"].items():
        text = (HERE / f"{name}.yml").read_bytes()
        got = stackpolicy.check(load(name), ref, base=expect["base"], stack_dir=HERE, text=text)
        if want["ok"] and got:
            bad += 1
            print(f"FAIL  {name}: should be let through, and was refused: {got}")
        elif not want["ok"] and not got:
            bad += 1
            print(f"FAIL  {name}: should be refused, and was let through")
        elif not want["ok"] and not any(want["says"] in line for line in got):
            bad += 1
            print(f"FAIL  {name}: refused, but not for {want['says']!r}: {got}")
        else:
            print(f"ok    {name}" + (f": {got[0]}" if got else ""))
    print(f"{len(expect['cases']) - bad} of {len(expect['cases'])} as they must be")
    return bad


if __name__ == "__main__":
    sys.exit(main())
