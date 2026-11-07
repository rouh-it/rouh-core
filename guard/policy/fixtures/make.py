#!/usr/bin/env python3
"""Makes the stack check's fixtures: good and hostile stack files, each resolved by the real
`docker compose config --format json`, and what the check must say of each (expect.json).

    python3 guard/policy/fixtures/make.py        # needs docker compose; writes this folder
    ROUH_COMPOSE=/path/to/docker-compose python3 guard/policy/fixtures/make.py   # another Compose

Made with Rouh for Mac's Compose (5.6.0 since 29 October 2026, task 158) and --no-env-resolution,
as both apps resolve a stack: an env_file stays in the resolved file as its path. A file of the
machine outside the stack folder is written "@TMP@/host/...".

Each fixture is the release's stack file (deploy/stack/compose.yml) with one change, as an
override file merged over it, or as a whole file where an override cannot say it (taking a
service out). The resolved JSON is what both checks read: guard/rouh_guard/stackpolicy.py (and
its check, check.py here) and Rouh for Mac's StackPolicy.swift (its tests). The folder this was
made in is written "@STACK@" in them, so a build's context can be checked anywhere.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
REFERENCE = REPO / "deploy" / "stack" / "compose.yml"
BASE = "ghcr.io/rouh-it/rouh-base@sha256:" + "1" * 64
RELEASE_ENV = (f"ROUH_BASE_IMAGE={BASE}\n"
               f"ROUH_GUARD_IMAGE=ghcr.io/rouh-it/rouh-guard@sha256:{'2' * 64}\n"
               f"ROUH_POSTGRES_IMAGE=pgvector/pgvector:0.8.2-pg18-trixie@sha256:{'3' * 64}\n")
STACK_ENV = "POSTGRES_PASSWORD=fixture-password\nROUH_PORT=8420\n"
#: A file of the machine's own, which no stack file may read: its words must never reach a fixture.
HOST_SECRET = "HOST_SECRET=only-on-this-machine\n"
COMPOSE = os.environ.get("ROUH_COMPOSE", "")

#: name: (override YAML, or a function of the reference text giving a whole file; ok?; a few words
#: every refusal list for it must hold)
CASES = {
    "good-as-released": ("", True, ""),
    "good-mongo-instead-of-postgres": ("""
services:
  mongo:
    image: mongo:7.0
    restart: unless-stopped
    security_opt: ["no-new-privileges:true"]
    volumes: [mongo-data:/data/db]
    networks: [mongo]
  core:
    networks: [db, workers, edge, mongo]
networks:
  mongo:
    internal: true
volumes:
  mongo-data: {}
""", True, ""),
    "good-more-memory": ("""
services:
  core:
    mem_limit: 6g
  worker:
    shm_size: 2g
    mem_limit: 8g
""", True, ""),
    "good-own-image-on-the-base": ("""
services:
  core:
    image: !reset null
    build:
      context: ./images/core
""", True, ""),
    "good-local-port": ("""
services:
  adminer:
    image: adminer:5
    networks: [db]
    ports: ["127.0.0.1:8081:8080"]
""", True, ""),
    "bad-privileged": ("services:\n  core:\n    privileged: true\n", False, "privileged"),
    "bad-host-network": ("services:\n  worker:\n    networks: !reset null\n    network_mode: host\n", False, "network_mode 'host'"),
    "bad-host-pid": ("services:\n  sidecar:\n    image: busybox\n    pid: host\n", False, "pid 'host'"),
    "bad-host-ipc": ("services:\n  sidecar:\n    image: busybox\n    ipc: host\n", False, "ipc 'host'"),
    "bad-host-userns": ("services:\n  sidecar:\n    image: busybox\n    userns_mode: host\n", False, "userns_mode 'host'"),
    "bad-host-cgroup": ("services:\n  sidecar:\n    image: busybox\n    cgroup: host\n", False, "cgroup 'host'"),
    "bad-seccomp-unconfined": ("services:\n  worker:\n    security_opt: [\"no-new-privileges:true\", \"seccomp:unconfined\"]\n", False, "seccomp:unconfined"),
    "bad-apparmor-unconfined": ("services:\n  core:\n    security_opt: [\"no-new-privileges:true\", \"apparmor:unconfined\"]\n", False, "apparmor:unconfined"),
    "bad-devices": ("services:\n  sidecar:\n    image: busybox\n    devices: [\"/dev/sda:/dev/sda\"]\n", False, "devices"),
    "bad-sysctls": ("services:\n  sidecar:\n    image: busybox\n    sysctls: {net.ipv4.ip_forward: 1}\n", False, "sysctls"),
    "bad-docker-socket": ("services:\n  core:\n    volumes: [\"/var/run/docker.sock:/var/run/docker.sock\"]\n", False, "Docker socket"),
    "bad-bind-mount": ("services:\n  worker:\n    volumes: [\"/Users:/mac\"]\n", False, "bind mount"),
    "bad-bind-disguised-as-volume": ("""
services:
  worker:
    volumes: [host-root:/host]
volumes:
  host-root:
    driver: local
    driver_opts: {type: none, o: bind, device: /}
""", False, "driver_opts"),
    "bad-external-volume": ("services:\n  worker:\n    volumes: [elsewhere:/x]\nvolumes:\n  elsewhere:\n    external: true\n", False, "external"),
    "bad-extra-capability": ("services:\n  worker:\n    cap_add: [SYS_ADMIN]\n", False, "SYS_ADMIN"),
    "bad-net-admin": ("services:\n  sidecar:\n    image: busybox\n    cap_add: [NET_ADMIN]\n", False, "NET_ADMIN"),
    "bad-port-every-address": ("services:\n  core:\n    ports: !override [\"8420:8021\"]\n", False, "every address"),
    "bad-port-zeroes": ("services:\n  sidecar:\n    image: busybox\n    ports: [\"0.0.0.0:9000:9000\"]\n", False, "0.0.0.0"),
    "bad-guard-changed": ("services:\n  guard:\n    environment:\n      ROUH_GUARD_DOCTOR_PATIENCE: \"999999\"\n", False, "protected core"),
    "bad-guard-removed": (lambda text: re.sub(r"\n  guard:\n(    .*\n|\n)+?(?=  [a-z])", "\n", text, count=1)
                          .replace("      guard:\n        condition: service_healthy\n", ""), False, "'guard' is gone"),
    "bad-keyproxy-reads-code": ("services:\n  keyproxy:\n    volumes: [\"code:/code:ro\"]\n", False, "protected core"),
    "bad-worker-gets-keys": ("services:\n  worker:\n    volumes: [\"keys:/keys:ro\"]\n", False, "'keys'"),
    "bad-worker-writes-code": ("services:\n  worker:\n    volumes: !override\n      - worker-home:/home/rouh\n      - one-run:/run/one\n      - code:/code\n      - extra:/extra:ro\n      - guard-bin:/opt/rouh-guard:ro\n      - guard-signal:/run/guard-signal:ro\n", False, "may only read it"),
    "bad-core-reads-undo-points": ("services:\n  core:\n    volumes: [\"guard-state:/guard\"]\n", False, "'guard-state'"),
    "bad-worker-on-egress": ("services:\n  worker:\n    networks: [workers, egress]\n", False, "egress"),
    "bad-new-service-on-edge": ("services:\n  sidecar:\n    image: busybox\n    networks: [edge]\n", False, "edge"),
    "bad-browser-reads-data": ("services:\n  browser:\n    volumes: [\"core-data:/data:ro\"]\n", False, "volumes"),
    "bad-browser-on-workers": ("services:\n  browser:\n    networks: [browser, workers]\n", False, "networks"),
    "bad-browser-way-round-the-proxy": ("services:\n  browser:\n    environment:\n      ROUH_BROWSER_PROXY: \"\"\n", False, "environment"),
    "bad-new-service-beside-the-browser": ("services:\n  sidecar:\n    image: busybox\n    networks: [browser]\n", False, "'browser'"),
    "bad-wall-opened":("networks:\n  workers:\n    internal: false\n", False, "walls"),
    "bad-own-network-with-a-way-out": ("services:\n  sidecar:\n    image: busybox\n    networks: [out]\nnetworks:\n  out: {}\n", False, "not internal"),
    "bad-core-entrypoint": ("services:\n  core:\n    entrypoint: [\"/code/deploy/run-server.sh\"]\n", False, "entrypoint"),
    "bad-worker-as-root": ("services:\n  worker:\n    user: \"0:0\"\n", False, "user"),
    "bad-lifecycle-hook": ("services:\n  core:\n    post_start:\n      - command: [\"sh\", \"-c\", \"true\"]\n        privileged: true\n        user: root\n", False, "post_start"),
    "bad-image-mount": ("services:\n  core:\n    volumes:\n      - type: image\n        source: alpine:3\n        target: /mnt/alpine\n", False, "image mount"),
    "bad-volumes-from": ("services:\n  sidecar:\n    image: busybox\n    volumes_from: [guard]\n", False, "volumes_from"),
    "bad-build-from-elsewhere": ("services:\n  core:\n    image: !reset null\n    build:\n      context: ./images/elsewhere\n", False, "FROM alpine"),
    "bad-build-host-network": ("services:\n  core:\n    image: !reset null\n    build:\n      context: ./images/core\n      network: host\n", False, "network"),
    "bad-build-outside": ("services:\n  core:\n    image: !reset null\n    build:\n      context: /\n", False, "outside"),
    "bad-core-other-image": ("services:\n  core:\n    image: debian:13\n", False, "debian:13"),
    # Reading a file of the machine while Compose resolves the stack (task 158): each folded into the
    # resolved file by Compose itself, so refused in the text, or by where its env_file points.
    "bad-env-file-from-the-machine": ("services:\n  peek:\n    image: busybox\n    network_mode: none\n    env_file: [\"@HOSTDIR@/secret.env\"]\n",
                                      False, "outside its own folder"),
    "bad-env-file-climbing-out": ("services:\n  worker:\n    env_file: [\"../host/secret.env\"]\n", False, "outside its own folder"),
    "bad-label-file": ("services:\n  peek:\n    image: busybox\n    network_mode: none\n    label_file: [\"@HOSTDIR@/secret.env\"]\n",
                       False, "'label_file'"),
    "bad-include": (lambda text: text.replace("\nservices:\n", "\ninclude:\n  - @HOSTDIR@/other.yml\nservices:\n", 1), False, "'include'"),
    "bad-extends": ("services:\n  peek:\n    network_mode: none\n    extends:\n      file: @HOSTDIR@/other.yml\n      service: leak\n",
                    False, "'extends'"),
    "bad-escaped-key": ("services:\n  peek:\n    image: busybox\n    network_mode: none\n    \"\\x65nvironment\": {A: \"1\"}\n",
                        False, "backslash escape"),
    "bad-yaml-tag": ("services:\n  peek:\n    image: !!str busybox\n    network_mode: none\n", False, "YAML tag"),
    "good-env-file-of-its-own": ("services:\n  worker:\n    env_file: [\"./own.env\"]\n", True, ""),
    "bad-syslog-logging": ("services:\n  worker:\n    logging:\n      driver: syslog\n      options: {syslog-address: \"udp://192.0.2.1:514\"}\n", False, "syslog"),
}


def main() -> int:
    with tempfile.TemporaryDirectory() as t:
        stack = Path(t) / "stack"
        stack.mkdir()
        (stack / "release.env").write_text(RELEASE_ENV)
        (stack / "stack.env").write_text(STACK_ENV)
        (stack / "images" / "core").mkdir(parents=True)
        (stack / "images" / "core" / "Dockerfile").write_text(
            "ARG ROUH_BASE_IMAGE\nFROM ${ROUH_BASE_IMAGE}\nRUN echo a Rouh's own image on its base\n")
        (stack / "images" / "elsewhere").mkdir(parents=True)
        (stack / "images" / "elsewhere" / "Dockerfile").write_text("FROM alpine:3\nRUN echo not the base\n")
        (stack / "own.env").write_text("OWN_SETTING=1\n")
        host = Path(t) / "host"
        host.mkdir()
        (host / "secret.env").write_text(HOST_SECRET)
        (host / "other.yml").write_text("services:\n  leak:\n    image: busybox\n    network_mode: none\n"
                                        "    environment:\n      OTHER: only-on-this-machine\n")
        shutil.copy(stack / "own.env", HERE / "own.env")
        shutil.copytree(stack / "images", HERE / "images", dirs_exist_ok=True)
        text = REFERENCE.read_text()
        expect = {}
        for name, (change, ok, says) in CASES.items():
            files = ["compose.yml"]
            whole = change(text).replace("@HOSTDIR@", str(host)) if callable(change) else text
            (stack / "compose.yml").write_text(whole)
            if isinstance(change, str) and change.strip():
                (stack / "override.yml").write_text(change.lstrip().replace("@HOSTDIR@", str(host)))
                files.append("override.yml")
            elif (stack / "override.yml").exists():
                (stack / "override.yml").unlink()
            cmd = ([COMPOSE] if COMPOSE else ["docker", "compose"]) + ["--project-name", "rouh", "--env-file", "stack.env", "--env-file", "release.env"]
            for f in files:
                cmd += ["-f", f]
            r = subprocess.run(cmd + ["config", "--format", "json", "--no-env-resolution"], cwd=stack, capture_output=True, text=True)
            if r.returncode:
                print(f"{name}: docker compose refused it itself: {r.stderr.strip()[-300:]}", file=sys.stderr)
                return 1
            resolved = (r.stdout.replace(str(stack.resolve()), "@STACK@").replace(str(stack), "@STACK@")
                        .replace(str(Path(t).resolve()), "@TMP@").replace(str(Path(t)), "@TMP@"))
            (HERE / f"{name}.json").write_text(json.dumps(json.loads(resolved), indent=1, sort_keys=True) + "\n")
            if callable(change):
                (HERE / f"{name}.yml").write_text(change(text).replace("@HOSTDIR@", "@TMP@/host"))
            else:
                (HERE / f"{name}.yml").write_text(change.lstrip().replace("@HOSTDIR@", "@TMP@/host") if change.strip()
                                                  else "# The release's own stack file, unchanged.\n")
            if "only-on-this-machine" in resolved and ok:
                print(f"{name}: a file of the machine reached the resolved stack", file=sys.stderr)
                return 1
            expect[name] = {"ok": ok, "says": says}
            print(f"{name}: resolved")
        (HERE / "expect.json").write_text(json.dumps({"base": BASE, "reference": "good-as-released",
                                                     "cases": expect}, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
