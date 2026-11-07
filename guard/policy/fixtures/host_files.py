#!/usr/bin/env python3
"""Proves, with real Docker, that no file of the machine reaches a Rouh's stack (task 158).

    python3 guard/policy/fixtures/host_files.py --guard IMAGE [--base IMAGE]

Compose reads any file a stack file names while it resolves it - env_file, label_file, include,
extends - and folds it into the resolved file, where the stack check cannot see where it came
from (proved on Compose 2.38.2 and 5.6.0). For each way in, this writes a Rouh's own stack folder
that tries it on a secret file of the machine, and runs what a Linux machine runs
(deploy/container/linux_stack.py): the stack resolved sealed, then the protected core's own check
out of the guard image. Each must be refused, and the secret must appear nowhere: not in what
Compose answered, not in the resolved stack, not in any file the updater wrote. The release's own
stack file, and one with a settings file of its own folder, must still pass.

Needs Docker with Compose; --guard is a rouh-guard image (built from this checkout:
docker build -f guard/Dockerfile -t rouh-guard-test .), --base any image the sealed Compose runs on
(the release's base in real use).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "deploy" / "container"))
import linux_stack  # noqa: E402

SECRET = "only-on-this-machine-7f3a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--guard", required=True)
    ap.add_argument("--base", default="debian:trixie-slim")
    a = ap.parse_args()
    reference = (REPO / "deploy" / "stack" / "compose.yml").read_text()
    bad = 0
    with tempfile.TemporaryDirectory() as t:
        t = Path(t).resolve()
        host = t / "host"
        host.mkdir()
        (host / "secret.env").write_text(f"HOST_SECRET={SECRET}\n")
        (host / "other.yml").write_text(f"services:\n  leak:\n    image: busybox\n    network_mode: none\n"
                                        f"    environment:\n      OTHER: {SECRET}\n")
        root = t / "rouh"
        root.mkdir()
        (root / ".env").write_text("POSTGRES_PASSWORD=x\nROUH_PORT=8420\n")
        m = linux_stack.Machine(root)
        images = {"base": "ghcr.io/rouh-it/rouh-base@sha256:" + "1" * 64, "guard": a.guard,
                  "postgres": "pgvector/pgvector:0.8.2-pg18-trixie@sha256:" + "3" * 64}
        m.release_env.write_text(m.release_env_text({"version": 1, "level": "test", "images": images}, m.settings))
        m.reference.write_text(reference)
        m.policy.write_text((HERE.parent / "stack-policy.json").read_text())
        ref, why = m.resolve(m.reference)
        assert ref is not None, why

        add = lambda service: reference.replace("\nservices:\n", "\nservices:\n" + service, 1)  # noqa: E731
        cases = {
            "env_file, a path of the machine": (add(f"  peek:\n    image: busybox\n    network_mode: none\n    env_file: [\"{host}/secret.env\"]\n"), False),
            "env_file, climbing out of the folder": (add("  peek:\n    image: busybox\n    network_mode: none\n    env_file: [\"../../../host/secret.env\"]\n"), False),
            "env_file, a link in the folder to the machine": (add("  peek:\n    image: busybox\n    network_mode: none\n    env_file: [\"./linked.env\"]\n"), False),
            "env_file, the long form": (add(f"  peek:\n    image: busybox\n    network_mode: none\n    env_file:\n      - path: {host}/secret.env\n        required: true\n"), False),
            "label_file": (add(f"  peek:\n    image: busybox\n    network_mode: none\n    label_file: [\"{host}/secret.env\"]\n"), False),
            "include": (reference.replace("\nservices:\n", f"\ninclude:\n  - {host}/other.yml\nservices:\n", 1), False),
            "extends": (add(f"  peek:\n    network_mode: none\n    extends:\n      file: {host}/other.yml\n      service: leak\n"), False),
            "include, its key spelled with an escape": (reference.replace("\nservices:\n", f"\n\"\\x69nclude\":\n  - {host}/other.yml\nservices:\n", 1), False),
            "the release's own stack file": (reference, True),
            "a settings file of its own folder": (add("  peek:\n    image: busybox\n    network_mode: none\n    env_file: [\"./own.env\"]\n"), True),
        }
        for name, (text, ok) in cases.items():
            linux_stack._wipe(m.own)
            m.own.mkdir(mode=0o700)
            (m.own / "compose.yml").write_text(text)
            (m.own / "own.env").write_text("OWN_SETTING=1\n")
            os.symlink(host / "secret.env", m.own / "linked.env")
            said = ""
            resolved, why = m.resolve_sealed(m.own, a.base)
            if resolved is None:
                refused, said = [f"could not be resolved sealed: {why}"], why
            else:
                said = json.dumps(resolved)
                refused = m.policy_check(a.guard, m.own, resolved, ref)
            leaked = SECRET in said or any(SECRET in f.read_text(errors="replace") for f in root.rglob("*")
                                           if f.is_file() and not f.is_symlink())
            good = (not refused if ok else bool(refused)) and not leaked
            bad += not good
            print(("ok    " if good else "FAIL  ") + f"{name}: " + ("allowed" if not refused else refused[0][:150])
                  + ("  THE SECRET LEAKED" if leaked else ""))
    print(f"{len(cases) - bad} of {len(cases)} as they must be; no file of the machine reached a stack" if not bad
          else f"{bad} of {len(cases)} wrong")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
