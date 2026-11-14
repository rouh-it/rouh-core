#!/usr/bin/env python3
"""Rouh's own WSL Linux, signed: which .wsl file a Windows install takes, by SHA-256 (task 186, step 186-04).

The .wsl files are built at GitHub for x64 and Arm (.github/workflows/wsl-image.yml) and attached to
the GitHub Release wsl-<version> of rouh-core. What makes one trusted is not where it is downloaded
from but this record, signed with Rouh's release key (the same Ed25519 key, envelope and check as
every release rouh.land hands out, mac_release.py), which names each file's address, size and SHA-256:

    {"format": 1, "key": "rouh-mac-stack-1", "payload": "<the record, as JSON text>", "signature": "..."}

    payload: {"kind": "rouh-wsl-image", "format": 1, "channel": "stable", "version": YYYYMMDDHHMMSS,
              "released": "...Z", "commit": "<rouh-core commit it was built from>", "run": "<the run>",
              "min_wsl": "2.0.0", "images": {"x64": {"file", "url", "size", "sha256"}, "arm64": {...}},
              "contents": {"x64": {"debian", "docker", "compose", ...}, "arm64": {...}}}

rouh.land keeps the newest at /windows/wsl/stable.json (rouh-it-site, rouhit/windows_views.py), and
install.ps1 and Rouh for Windows check the signature with the key written in them, then each byte
of the file against its SHA-256, before WSL imports it.

    wsl_image.py sign --version V --commit SHA --run URL --base-url URL DIR OUT
        the signed record of DIR's rouh-wsl-<V>-<x64|arm64>.wsl files and their .contents
        (the key: $ROUH_MAC_STACK_SIGNING_KEY, or --key FILE)
    wsl_image.py verify FILE [--file x64=PATH] [--file arm64=PATH]
    wsl_image.py publish FILE         sends it to rouh.land (the signature is the permission)
    wsl_image.py status               what rouh.land hands out now, checked

Standard library only, and openssl 3, as mac_release.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "container"))
import mac_release  # noqa: E402

KIND = "rouh-wsl-image"
ARCHES = ("x64", "arm64")
#: The oldest WSL that imports a .wsl file and runs systemd in it.
MIN_WSL = "2.0.0"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_VERSION = re.compile(r"^\d{14}$")
_URL = re.compile(r"^https://[A-Za-z0-9.\-]+/[\x21-\x7e]{1,500}$")
MOST_BYTES = 8 * 1024


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_record(envelope: dict) -> dict:
    """The signature with a trusted key, then the shape: what install.ps1 checks, in Python."""
    r = mac_release._signed(envelope)
    if r.get("kind") != KIND or r.get("format") != 1:
        raise ValueError("not a record of Rouh's WSL Linux")
    if not _VERSION.match(str(r.get("version", ""))):
        raise ValueError("its version is not YYYYMMDDHHMMSS")
    if not re.fullmatch(r"[0-9a-f]{40}", str(r.get("commit", ""))):
        raise ValueError("it names no commit")
    images = r.get("images")
    if not isinstance(images, dict) or not images or not set(images) <= set(ARCHES):
        raise ValueError(f"images must name some of {', '.join(ARCHES)}")
    for arch, i in images.items():
        if not isinstance(i, dict) or not _SHA.match(str(i.get("sha256", ""))):
            raise ValueError(f"images.{arch} has no SHA-256")
        if not _URL.match(str(i.get("url", ""))) or not str(i.get("url")).endswith(".wsl"):
            raise ValueError(f"images.{arch} has no https address of a .wsl file")
        if not isinstance(i.get("size"), int) or not 50_000_000 <= i["size"] <= 4_000_000_000:
            raise ValueError(f"images.{arch}'s size is not that of a Linux")
    return r


def make(directory: Path, *, version: str, commit: str, run: str, base_url: str, key_pem: bytes) -> dict:
    if not _VERSION.match(version):
        mac_release.die("--version is YYYYMMDDHHMMSS")
    images, contents = {}, {}
    for arch in ARCHES:
        f = directory / f"rouh-wsl-{version}-{arch}.wsl"
        if not f.is_file():
            continue
        images[arch] = {"file": f.name, "url": f"{base_url.rstrip('/')}/{f.name}", "size": f.stat().st_size,
                        "sha256": sha256_of(f)}
        c = f.with_name(f.name + ".contents")
        if c.is_file():
            contents[arch] = dict(line.split("=", 1) for line in c.read_text().splitlines() if "=" in line)
    if not images:
        mac_release.die(f"no rouh-wsl-{version}-<arch>.wsl in {directory}")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    record = {"kind": KIND, "format": 1, "channel": "stable", "version": int(version),
              "released": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "commit": commit, "run": run, "min_wsl": MIN_WSL,
              "images": images, "contents": contents}
    payload = json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    env = {"format": 1, "key": mac_release.KEY_ID, "payload": payload,
           "signature": mac_release.sign_payload(payload, key_pem)}
    check_record(env)
    return env


def describe(r: dict) -> str:
    lines = [f"Rouh's WSL Linux {r['version']} ({r['released']}), from commit {r['commit'][:12]}"]
    for arch, i in sorted(r["images"].items()):
        c = (r.get("contents") or {}).get(arch, {})
        lines.append(f"  {arch:6} {i['sha256'][:16]}…  {i['size'] / 1e6:.0f} MB  Debian {c.get('debian', '?')}, "
                     f"Docker {c.get('docker', '?')}  {i['url']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sign")
    s.add_argument("dir")
    s.add_argument("out")
    s.add_argument("--version", required=True)
    s.add_argument("--commit", required=True)
    s.add_argument("--run", default="")
    s.add_argument("--base-url", required=True)
    s.add_argument("--key")
    v = sub.add_parser("verify")
    v.add_argument("file")
    v.add_argument("--file", dest="files", action="append", default=[], metavar="ARCH=PATH")
    p = sub.add_parser("publish")
    p.add_argument("file")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "sign":
        env = make(Path(a.dir), version=a.version, commit=a.commit, run=a.run, base_url=a.base_url,
                   key_pem=mac_release._key_pem(a.key))
        Path(a.out).write_text(json.dumps(env, indent=1) + "\n")
        print(describe(check_record(env)))
        return 0
    if a.cmd == "verify":
        try:
            r = check_record(json.loads(Path(a.file).read_text()))
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            print(f"NOT TRUSTED: {e}")
            return 1
        print(describe(r))
        for pair in a.files:
            arch, _, path = pair.partition("=")
            want = r["images"].get(arch, {}).get("sha256")
            got = sha256_of(Path(path))
            if got != want:
                print(f"NOT TRUSTED: {path} is not the {arch} file the record names ({got[:16]}… is not {str(want)[:16]}…)")
                return 1
            print(f"  {arch}: {path} matches its SHA-256")
        return 0
    if a.cmd == "publish":
        body = Path(a.file).read_bytes()
        check_record(json.loads(body))
        req = urllib.request.Request(f"{mac_release.SITE}/windows/wsl/publish", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                print(resp.status, resp.read().decode()[:400])
                return 0
        except urllib.error.HTTPError as e:
            print(e.code, e.read().decode()[:400])
            return 1
    if a.cmd == "status":
        try:
            r = check_record(mac_release._get("/windows/wsl/stable.json"))
        except (mac_release.FetchError, ValueError) as e:
            print(f"rouh.land hands out no trusted record of Rouh's WSL Linux: {e}")
            return 1
        print(describe(r))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
