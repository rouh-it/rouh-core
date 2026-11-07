#!/usr/bin/env python3
"""Rouh for Mac's stack releases: what the Mac app runs, signed, and published on rouh.land.

The app carries no addresses of Rouh's images. Before 0.3.3 it asked rouh.land for the newest
release of its stack, checked the signature with the public key built into it, and ran exactly
the images the release named, each pinned by its digest. So Rouh can be updated, and taken back,
without a new signed build of the app. Only the app's own Swift code needs one.

A release is one JSON document (the envelope):

    {"format": 1, "key": "rouh-mac-stack-1", "payload": "<the release, as JSON text>",
     "signature": "<Ed25519 over the payload's bytes, base64>"}

and the payload holds the release's number (its UTC time, YYYYMMDDHHMMSS, so a newer one is
always a larger number and nothing has to be counted), when it was made, the oldest app that can
run it, the commit and the run it came from, the four images by digest, and the stack file
itself with its SHA-256. Nothing secret and nothing of anybody's.

    mac_release.py sign COMPOSE --commit SHA [--run URL] [--rollback-of N] [--min-app V] OUT
        the signed release; the key is the PEM in $ROUH_MAC_STACK_SIGNING_KEY, or --key FILE
    mac_release.py verify FILE           checks a release with the public key the app has
    mac_release.py publish FILE          sends a signed release to rouh.land
    mac_release.py status                what rouh.land serves now, checked
    mac_release.py list                  every release rouh.land has, newest first
    mac_release.py rollback N            publishes release N again, as a new, newer release
                                         (a Mac never goes back to a smaller number), signed with
                                         the key on the signing machine ($ROUH_MAC_STACK_SIGNING_KEY_FILE,
                                         else /root/.config/rouh-mac-stack/

Since 23 October 2026 (Petar: "latest" means only patch-level fixes to what Rouh runs on) a Mac
follows **base releases** instead, at https://rouh.land/mac/base/stable.json: the same envelope and
key, a payload of kind "rouh-base" naming the base image, the code image that fills an empty code
volume once, and PostgreSQL, with the stack file, the line and its patch level. Each Mac checks a
base release with its own /code before it switches (the app's StackUpdater.check). The stack
releases above are kept for apps older than 0.3.3, which read nothing else: one last one, the
**bridge**, moves them onto the new layout (the same images under the names they know), and none
follows it, because an old app would switch without the check.

    mac_release.py base-pin --base REF --code REF [--postgres REF] [--commit SHA] OUT
        compose.ghcr.yml pinned to a base and its code image, for Rouh for Mac (stack.env)
    mac_release.py base-sign COMPOSE --line L --level V --commit SHA [--run URL]
                       [--contents FILE] [--changes FILE] [--min-app V] OUT
    mac_release.py base-verify FILE | base-publish FILE | base-status | base-list
    mac_release.py base-rollback N       publishes base release N again as a new, newer one
    mac_release.py bridge --code-as-core REF --base-as-workers REF --base-as-keyproxy REF
                       [--postgres REF] --commit SHA OUT
        the format-1 stack file of the new layout, for apps before 0.3.3; sign and publish it
        with sign and publish

Since 24 October 2026 (task 98, step 98-23, the protected core) a Mac from Rouh for Mac 0.3.4
follows **releases of format 2** instead, at https://rouh.land/mac/release/<line>.json (stable.json
for a Rouh with none): the same envelope and key, a payload of kind "rouh-release" naming the base,
the protected core (rouh-guard) and PostgreSQL, each pinned by digest - PostgreSQL's from the
line's own pin (base_patch.py), never a floating tag looked up now - with the reference stack file
(deploy/stack/compose.yml, which names its images by ${ROUH_BASE_IMAGE} and the like), the stack
check's allow-list (guard/policy/stack-policy.json), and the newest commit of main that passed its
tests, which a new install starts from. The code image is gone: a Rouh's code comes from rouh.land.
Since 29 October 2026 (task 158) it also names check_sha256: one SHA-256 of the stack check as it
was at that commit - its code, its allow-list and its fixtures (CHECK_FILES) - so Rouh for Mac's
build can prove that its own twin of the check was held to the very cases this release ships
(rouh-mac's scripts/sync-rouh-core.sh), and the Linux machine's linux_stack.py runs the check out
of this release's guard image.

    mac_release.py release-sign --line L --level V --commit SHA --base REF --guard REF
                       --postgres REF [--postgres-version V] [--code-commit SHA --code-run URL
                       --code-passed-at T] [--contents FILE] [--changes FILE] [--run URL] OUT
    mac_release.py release-verify FILE | release-publish FILE | release-status | release-list
    mac_release.py release-rollback N    publishes release N again as a new, newer one
    mac_release.py code-pass --commit SHA --run URL OUT    signs "this commit of main passed"
    mac_release.py code-publish FILE                        sends it to rouh.land
    mac_release.py code-newest                              what rouh.land hands out now
    mac_release.py check-sha256 [ROOT]                      check_sha256 of a checkout (this one)
    mac_release.py release-matches FILE --src DIR --commit SHA --base REF --guard REF [--code SHA] [--tag base-<level>]
        refuses a signed release that is not, every part of it, the one commit it names: its commit
        is DIR's checked-out commit, its stack file, allow-list and check_sha256 are DIR's, its images
        the ones built from it; base.yml runs it before it publishes

Standard library only, and openssl (3.x) for Ed25519, so it runs on GitHub's runners and on
the signing machine as it is. Change PUBLIC_KEYS together with Rouh for Mac's StackRelease.trustedKeys (rouh-it/rouh-mac) and
rouh.land's MAC_STACK_KEYS.
"""
import argparse
import base64
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: Rouh's public site: ROUH_MAC_STACK_SITE, else the one setting ROUH_SITE_URL (rouh/site.py, task 165).
SITE = (os.environ.get("ROUH_MAC_STACK_SITE") or os.environ.get("ROUH_SITE_URL") or "https://rouh.land").strip().rstrip("/")
CHANNEL = "stable"
#: The first version of Rouh for Mac that reads releases.
MIN_APP = "0.3.0"
#: The key that signs, and the public half every app has built in.
KEY_ID = "rouh-mac-stack-1"
PUBLIC_KEYS = {KEY_ID: "XyU09FKab+ZrKEvIfHSaYvnLF3F8FSOnIdX8frWCjiA="}
#: Where the signing machine keeps the private key, readable by root only; a setting of that machine.
KEY_FILE = Path(os.environ.get("ROUH_MAC_STACK_SIGNING_KEY_FILE") or "/root/.config/rouh-mac-stack/signing-key.pem")
POSTGRES = "pgvector/pgvector:0.8.2-pg18-trixie"
#: The first version of Rouh for Mac that reads base releases and checks them before switching.
MIN_APP_BASE = "0.3.3"
BASE_KINDS = {"ghcr.io/rouh-it/rouh-base": "base", "ghcr.io/rouh-it/rouh-code": "code",
              "pgvector/pgvector": "postgres"}
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
UA = "rouh-mac-release/1"


def die(msg):
    print(f"mac_release: {msg}", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- the stack file


def _for_the_mac(text: str, commit: str, what: str) -> str:
    """stack.env as the settings file, every image by digest, and the head that says so."""
    for old, new in (("- path: .env\n", "- path: stack.env\n"), (".env must set", "stack.env must set"),
                     ("ROUH_PORT in .env", "ROUH_PORT in stack.env")):
        if old not in text:
            die(f"compose.ghcr.yml no longer has {old!r}")
        text = text.replace(old, new)
    text = re.sub(r"# ROUH_(BASE_)?TAG in \.env picks a [^\n]*\n", "", text)
    for line in text.splitlines():
        if line.strip().startswith("image:") and not DIGEST.search(line.strip()):
            die(f"an image is not pinned by digest: {line.strip()}")
    rest = text.split("\nname:", 1)[1]
    if "ROUH_TAG" in rest or "ROUH_BASE_TAG" in rest or "ROUH_IMAGE_PREFIX" in rest:
        die("a ROUH_TAG, ROUH_BASE_TAG or ROUH_IMAGE_PREFIX is left in the stack")
    head = (f"# Rouh for Mac's stack, {what}: made by deploy/container/mac_release.py from\n"
            f"# deploy/container/compose.ghcr.yml at commit {commit or 'unknown'}, each image\n"
            "# pinned by its digest. Published, signed, as a release on rouh.land; never edited\n"
            "# by hand. The app runs it with stack.env beside it and the project name rouh.\n#\n")
    return head + text


def _by_service(text: str, image_of) -> str:
    """Every service's image line set to image_of(service, the line as it is)."""
    out, service, in_services = [], "", False
    for line in text.splitlines(keepends=True):
        if line.startswith("services:"):
            in_services = True
        elif in_services and re.match(r"^  [a-z][a-z0-9-]*:\s*$", line):
            service = line.strip()[:-1]
        elif in_services and line.startswith("    image:"):
            line = f"    image: {image_of(service, line.split(':', 1)[1].strip())}\n"
        out.append(line)
    return "".join(out)


BASE_SERVICES = {"code-init": "code", "core": "base", "keyproxy": "base", "worker-perms": "base",
                 "worker": "base", "postgres": "postgres"}


def pin_base(source: str, images: dict, commit: str) -> str:
    """compose.ghcr.yml, made Rouh for Mac's for a base release: each service on its image by digest."""
    seen = set()

    def image_of(service, now):
        kind = BASE_SERVICES.get(service)
        if not kind:
            die(f"compose.ghcr.yml has a service the base releases do not know: {service}")
        seen.add(service)
        return images[kind]
    text = _by_service(source, image_of)
    if seen != set(BASE_SERVICES):
        die(f"compose.ghcr.yml lacks {sorted(set(BASE_SERVICES) - seen)}")
    return _for_the_mac(text, commit, "on a base release")


#: The bridge, for apps before 0.3.3: the new layout under the names those apps check for. The
#: workers and key proxy names carry the base itself, the core name the code image (the base with
#: the release's copy on top), so every image is one these apps already know how to verify.
BRIDGE_SERVICES = {"code-init": "core", "core": "core", "keyproxy": "keyproxy", "worker-perms": "workers",
                   "worker": "workers", "postgres": "postgres"}


def pin_bridge(source: str, images: dict, commit: str) -> str:
    text = _by_service(source, lambda service, now: images[BRIDGE_SERVICES[service]])
    return _for_the_mac(text, commit, "the bridge onto the base layout, for Rouh for Mac before 0.3.3")


def images_in(compose: str) -> dict:
    found = {}
    for line in compose.splitlines():
        s = line.strip()
        if not s.startswith("image:"):
            continue
        ref = s.split(":", 1)[1].strip()
        name = ref.split("@", 1)[0].split(":", 1)[0] if "@" in ref else ref
        kind = {"ghcr.io/rouh-it/rouh-core": "core", "ghcr.io/rouh-it/rouh-workers": "workers",
                "ghcr.io/rouh-it/rouh-keyproxy": "keyproxy", "pgvector/pgvector": "postgres"}.get(name)
        if not kind:
            die(f"an image the app does not know: {ref}")
        if found.get(kind, ref) != ref:
            die(f"two different {kind} images in one stack")
        found[kind] = ref
    if set(found) != {"core", "workers", "keyproxy", "postgres"}:
        die(f"the stack must name core, workers, keyproxy and postgres; it names {sorted(found)}")
    return found


# ---------------------------------------------------------------- signing


def _openssl(*args, data: bytes = b""):
    r = subprocess.run(["openssl", *args], input=data, capture_output=True)
    return r.returncode, r.stdout, r.stderr


def _public_pem(raw_b64: str) -> bytes:
    der = bytes.fromhex("302a300506032b6570032100") + base64.b64decode(raw_b64)
    return b"-----BEGIN PUBLIC KEY-----\n" + base64.encodebytes(der) + b"-----END PUBLIC KEY-----\n"


def _key_pem(path: str | None) -> bytes:
    if os.environ.get("ROUH_MAC_STACK_SIGNING_KEY"):
        return os.environ["ROUH_MAC_STACK_SIGNING_KEY"].encode()
    p = Path(path) if path else KEY_FILE
    try:
        return p.read_bytes()
    except OSError as e:
        die(f"no signing key: set ROUH_MAC_STACK_SIGNING_KEY or give --key ({e.strerror}: {p})")


def sign_payload(payload: str, key_pem: bytes) -> str:
    with tempfile.TemporaryDirectory() as t:
        key, msg = Path(t, "k.pem"), Path(t, "m")
        key.touch(mode=0o600)
        key.write_bytes(key_pem)
        msg.write_bytes(payload.encode())
        code, out, err = _openssl("pkeyutl", "-sign", "-inkey", str(key), "-rawin", "-in", str(msg))
        # The public half of the key used must be the one the app trusts.
        c2, pub, _ = _openssl("pkey", "-in", str(key), "-pubout", "-outform", "DER")
    if code or len(out) != 64:
        die(f"openssl could not sign: {err.decode().strip()}")
    if c2 or base64.b64encode(pub[-32:]).decode() != PUBLIC_KEYS[KEY_ID]:
        die("that signing key is not the one Rouh for Mac trusts")
    return base64.b64encode(out).decode()


def check(envelope: dict) -> dict:
    """The app's own checks, in Python: the signature with a trusted key, then the shape."""
    if envelope.get("format") != 1:
        raise ValueError("not a format 1 release")
    raw = PUBLIC_KEYS.get(envelope.get("key"))
    if not raw:
        raise ValueError(f"signed with a key the app does not know: {envelope.get('key')!r}")
    payload, sig = envelope.get("payload"), envelope.get("signature")
    if not isinstance(payload, str) or not isinstance(sig, str):
        raise ValueError("no payload or no signature")
    with tempfile.TemporaryDirectory() as t:
        Path(t, "p.pem").write_bytes(_public_pem(raw))
        Path(t, "m").write_bytes(payload.encode())
        Path(t, "s").write_bytes(base64.b64decode(sig))
        code, _, _ = _openssl("pkeyutl", "-verify", "-pubin", "-inkey", str(Path(t, "p.pem")), "-rawin",
                              "-in", str(Path(t, "m")), "-sigfile", str(Path(t, "s")))
    if code:
        raise ValueError("the signature does not match")
    r = json.loads(payload)
    if r.get("kind") != "rouh-mac-stack" or r.get("format") != 1:
        raise ValueError("not a Rouh for Mac stack release")
    if hashlib.sha256(r["compose"].encode()).hexdigest() != r.get("compose_sha256"):
        raise ValueError("the stack file does not match its SHA-256")
    if images_in(r["compose"]) != r.get("images"):
        raise ValueError("the images listed are not the stack's")
    return r


def make(compose: str, *, commit: str, run: str, min_app: str, rollback_of: int | None, key_pem: bytes) -> dict:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    release = {
        "kind": "rouh-mac-stack",
        "format": 1,
        "channel": CHANNEL,
        "version": int(now.strftime("%Y%m%d%H%M%S")),
        "released": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "min_app": min_app,
        "commit": commit,
        "run": run,
        "rollback_of": rollback_of,
        "images": images_in(compose),
        "compose": compose,
        "compose_sha256": hashlib.sha256(compose.encode()).hexdigest(),
    }
    payload = json.dumps(release, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    env = {"format": 1, "key": KEY_ID, "payload": payload, "signature": sign_payload(payload, key_pem)}
    check(env)
    return env


# ---------------------------------------------------------------- base releases


def base_images_in(compose: str) -> dict:
    found = {}
    for line in compose.splitlines():
        s = line.strip()
        if not s.startswith("image:"):
            continue
        ref = s.split(":", 1)[1].strip()
        kind = BASE_KINDS.get(ref.split("@", 1)[0].split(":", 1)[0])
        if not kind:
            die(f"an image a base release does not know: {ref}")
        if found.get(kind, ref) != ref:
            die(f"two different {kind} images in one stack")
        found[kind] = ref
    if set(found) != {"base", "code", "postgres"}:
        die(f"a base release's stack must name base, code and postgres; it names {sorted(found)}")
    return found


def check_base(envelope: dict) -> dict:
    """The app's checks for a base release, in Python: signature, kind, shape, line and level."""
    r = _signed(envelope)
    if r.get("kind") != "rouh-base" or r.get("format") != 1:
        raise ValueError("not a Rouh base release")
    if not re.fullmatch(r"\d+\.\d+", str(r.get("line"))) or not str(r.get("level", "")).startswith(f"{r['line']}."):
        raise ValueError("its line and level do not hold together")
    if hashlib.sha256(r["compose"].encode()).hexdigest() != r.get("compose_sha256"):
        raise ValueError("the stack file does not match its SHA-256")
    if base_images_in(r["compose"]) != r.get("images"):
        raise ValueError("the images listed are not the stack's")
    return r


def _signed(envelope: dict) -> dict:
    """The payload of an envelope whose signature is good with a trusted key."""
    if envelope.get("format") != 1:
        raise ValueError("not a format 1 release")
    raw = PUBLIC_KEYS.get(envelope.get("key"))
    if not raw:
        raise ValueError(f"signed with a key the app does not know: {envelope.get('key')!r}")
    payload, sig = envelope.get("payload"), envelope.get("signature")
    if not isinstance(payload, str) or not isinstance(sig, str):
        raise ValueError("no payload or no signature")
    with tempfile.TemporaryDirectory() as t:
        Path(t, "p.pem").write_bytes(_public_pem(raw))
        Path(t, "m").write_bytes(payload.encode())
        Path(t, "s").write_bytes(base64.b64decode(sig))
        code, _, _ = _openssl("pkeyutl", "-verify", "-pubin", "-inkey", str(Path(t, "p.pem")), "-rawin",
                              "-in", str(Path(t, "m")), "-sigfile", str(Path(t, "s")))
    if code:
        raise ValueError("the signature does not match")
    return json.loads(payload)


def make_base(compose: str, *, line: str, level: str, commit: str, run: str, contents: dict,
              changes: list, min_app: str, rollback_of: int | None, key_pem: bytes) -> dict:
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    release = {
        "kind": "rouh-base", "format": 1, "channel": CHANNEL,
        "version": int(now.strftime("%Y%m%d%H%M%S")), "released": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "line": line, "level": level, "min_app": min_app, "commit": commit, "run": run,
        "rollback_of": rollback_of, "images": base_images_in(compose), "compose": compose,
        "compose_sha256": hashlib.sha256(compose.encode()).hexdigest(),
        "contents": {k: str(v) for k, v in sorted((contents or {}).items())},
        "changes": [str(c)[:200] for c in (changes or [])][:60],
    }
    payload = json.dumps(release, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    env = {"format": 1, "key": KEY_ID, "payload": payload, "signature": sign_payload(payload, key_pem)}
    check_base(env)
    return env


def describe_base(r: dict) -> str:
    lines = [f"base {r['level']} (line {r['line']}), release {r['version']} ({r['released']}), "
             f"for Rouh for Mac {r['min_app']} or later",
             f"  code from commit {r['commit'][:12]}" + (f", {r['run']}" if r.get("run") else ""),
             *(f"  {k:9} {v}" for k, v in sorted(r["images"].items())),
             *(f"  {k:15} {v}" for k, v in sorted((r.get("contents") or {}).items()))]
    if r.get("changes"):
        lines.append("  changes: " + "; ".join(r["changes"][:12]))
    if r.get("rollback_of"):
        lines.insert(1, f"  a rollback: base release {r['rollback_of']} again")
    return "\n".join(lines)


# ---------------------------------------------------------------- releases of format 2


REPO = HERE.parents[1]
#: The first version of Rouh for Mac that reads releases of format 2, applies a Rouh's own stack
#: file after its check, and runs the protected core.
MIN_APP_RELEASE = "0.3.4"
RELEASE_IMAGES = {"base": re.compile(r"^ghcr\.io/rouh-it/rouh-base@sha256:[0-9a-f]{64}$"),
                  "guard": re.compile(r"^ghcr\.io/rouh-it/rouh-guard@sha256:[0-9a-f]{64}$"),
                  "postgres": re.compile(r"^pgvector/pgvector:[0-9a-z.\-]+@sha256:[0-9a-f]{64}$")}
COMMIT = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
#: What check_sha256 covers: the stack check's code, its allow-list and its fixtures. Rouh for Mac
#: keeps a copy of exactly these (rouh-mac's rouh-core/) and computes the same number.
CHECK_FILES = ("guard/policy", "guard/rouh_guard/stackpolicy.py")


def check_sha256(root: Path = REPO) -> str:
    """One SHA-256 for the stack check at root: every file of CHECK_FILES, by its path from root
    and its own SHA-256, one "path NUL sha256" line each, sorted. Dot files and __pycache__ are
    left out, as git and the guard image leave them."""
    lines = []
    for top in CHECK_FILES:
        start = root / top
        files = [start] if start.is_file() else sorted(start.rglob("*"))
        for f in files:
            rel = f.relative_to(root).as_posix()
            if not f.is_file() or any(part.startswith(".") or part == "__pycache__" for part in rel.split("/")):
                continue
            lines.append(f"{rel}\0{hashlib.sha256(f.read_bytes()).hexdigest()}\n")
    if not lines:
        die(f"no stack check under {root}")
    return hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()


def _guard_facts() -> dict:
    """The protected core's version and contracts, from guard/ in this checkout."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("rouh_guard", REPO / "guard" / "rouh_guard" / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return {"version": mod.VERSION, "contracts": mod.CONTRACTS}


def check_release(envelope: dict) -> dict:
    """The app's checks for a release of format 2, in Python."""
    r = _signed(envelope)
    if r.get("kind") != "rouh-release" or r.get("format") != 2:
        raise ValueError("not a Rouh release of format 2")
    if not re.fullmatch(r"\d+\.\d+", str(r.get("line"))) or not str(r.get("level", "")).startswith(f"{r['line']}."):
        raise ValueError("its line and level do not hold together")
    for key in ("compose", "policy"):
        if hashlib.sha256(str(r.get(key, "")).encode()).hexdigest() != r.get(f"{key}_sha256"):
            raise ValueError(f"the {key} does not match its SHA-256")
    images = r.get("images") or {}
    if set(images) != set(RELEASE_IMAGES) or any(not RELEASE_IMAGES[k].match(v) for k, v in images.items()):
        raise ValueError("it must name base, guard and postgres, each pinned by its digest")
    json.loads(r["policy"])
    for var in ("${ROUH_BASE_IMAGE", "${ROUH_GUARD_IMAGE", "${ROUH_POSTGRES_IMAGE"):
        if var not in r["compose"]:
            raise ValueError(f"the stack file does not take its images from the release ({var}}})")
    code = r.get("code")
    if code is not None and not COMMIT.match(str(code.get("commit", ""))):
        raise ValueError("code.commit is not a commit")
    if "check_sha256" in r and not SHA256.match(str(r["check_sha256"])):
        raise ValueError("check_sha256 is not a SHA-256")
    return r


def make_release(*, line: str, level: str, commit: str, run: str, images: dict, postgres_version: str,
                 code: dict | None, contents: dict, changes: list, min_app: str, rollback_of: int | None,
                 key_pem: bytes, compose: str | None = None, policy: str | None = None,
                 guard: dict | None = None, check: str | None = None) -> dict:
    """A release of format 2. compose, policy, guard and check come from this checkout unless given
    (a rollback gives the old release's own); base.yml checks out the exact commit it built."""
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    if compose is None and policy is None and check is None:
        check = check_sha256()
    compose = compose if compose is not None else (REPO / "deploy" / "stack" / "compose.yml").read_text()
    policy = policy if policy is not None else (REPO / "guard" / "policy" / "stack-policy.json").read_text()
    release = {
        "kind": "rouh-release", "format": 2, "channel": CHANNEL,
        "version": int(now.strftime("%Y%m%d%H%M%S")), "released": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "line": line, "level": level, "min_app": min_app, "commit": commit, "run": run,
        "rollback_of": rollback_of, "images": images,
        "guard": guard or _guard_facts(), "postgres": {"version": postgres_version},
        "compose": compose, "compose_sha256": hashlib.sha256(compose.encode()).hexdigest(),
        "policy": policy, "policy_sha256": hashlib.sha256(policy.encode()).hexdigest(),
        "contents": {k: str(v) for k, v in sorted((contents or {}).items())},
        "changes": [str(c)[:200] for c in (changes or [])][:60],
    }
    if code:
        release["code"] = code
    if check:
        release["check_sha256"] = check
    payload = json.dumps(release, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    env = {"format": 1, "key": KEY_ID, "payload": payload, "signature": sign_payload(payload, key_pem)}
    check_release(env)
    return env


def release_matches(r: dict, src: Path, *, commit: str, base: str, guard: str, code: str = "",
                    tag: str = "") -> list[str]:
    """Every way release r is not the one commit it names (an empty list when it is). With `tag`,
    also that the tag is base-<the release's level> and is that commit's (base.yml tags it first)."""
    out = []
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(src), "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    if not COMMIT.match(commit):
        out.append(f"{commit!r} is not a whole commit id, which could move")
    if r.get("commit") != commit:
        out.append(f"it names commit {r.get('commit')}, not {commit}")
    if head != commit:
        out.append(f"the checkout it was made from is at {head or 'nothing'}, not {commit}")
    if dirty:
        out.append("the checkout it was made from has changes of its own: " + dirty.replace("\n", "; ")[:200])
    if r.get("compose") != (src / "deploy" / "stack" / "compose.yml").read_text():
        out.append("its stack file is not that commit's deploy/stack/compose.yml")
    if r.get("policy") != (src / "guard" / "policy" / "stack-policy.json").read_text():
        out.append("its allow-list is not that commit's guard/policy/stack-policy.json")
    if r.get("check_sha256") != check_sha256(src):
        out.append("its check_sha256 is not that commit's stack check")
    if r.get("images", {}).get("base") != base or r.get("images", {}).get("guard") != guard:
        out.append("its base or guard image is not the one built from that commit")
    if code and (r.get("code") or {}).get("commit") != code:
        out.append(f"new installs would start from {(r.get('code') or {}).get('commit')}, not the tested {code}")
    if tag:
        tagged = subprocess.run(["git", "-C", str(src), "rev-parse", "-q", "--verify", f"refs/tags/{tag}^{{commit}}"],
                                capture_output=True, text=True).stdout.strip()
        if tag != f"base-{r.get('level')}":
            out.append(f"the tag {tag} is not base-{r.get('level')}, the release's level")
        if tagged != commit:
            out.append(f"the tag {tag} is {'the tag of ' + tagged if tagged else 'not in the checkout'}, not of {commit}")
    return out


def describe_release(r: dict) -> str:
    lines = [f"release {r['version']} ({r['released']}): base {r['level']} (line {r['line']}), protected core "
             f"{r['guard']['version']}, PostgreSQL {r['postgres'].get('version') or '?'}, for Rouh for Mac {r['min_app']} or later",
             *(f"  {k:9} {v}" for k, v in sorted(r["images"].items()))]
    if r.get("code"):
        lines.append(f"  new installs start from main at {r['code']['commit'][:12]}")
    if r.get("check_sha256"):
        lines.append(f"  stack check {r['check_sha256'][:16]}")
    if r.get("changes"):
        lines.append("  changes: " + "; ".join(r["changes"][:12]))
    if r.get("rollback_of"):
        lines.insert(1, f"  a rollback: release {r['rollback_of']} again")
    return "\n".join(lines)


def make_code_pass(commit: str, run: str, key_pem: bytes) -> dict:
    """Signed: this commit of main passed its tests (.github/workflows/main-tests.yml)."""
    if not COMMIT.match(commit):
        die("--commit is not a whole commit id")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    record = {"kind": "rouh-code-pass", "format": 1, "branch": "main", "commit": commit, "run": run,
              "version": int(now.strftime("%Y%m%d%H%M%S")), "passed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    payload = json.dumps(record, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return {"format": 1, "key": KEY_ID, "payload": payload, "signature": sign_payload(payload, key_pem)}


# ---------------------------------------------------------------- rouh.land


class FetchError(Exception):
    """rouh.land did not hand out what was asked for: the address, what it answered, and the User-Agent sent."""


def _get(path: str):
    # Always our own User-Agent: Cloudflare in front of rouh.land refuses Python's own
    # (Python-urllib/3.x answers 403), so a request without it never reaches the site.
    url = SITE + path
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise FetchError(f"{url} answered HTTP {e.code} {e.reason} (User-Agent {UA})") from None
    except urllib.error.URLError as e:
        raise FetchError(f"{url} could not be reached ({e.reason})") from None


def publish(envelope: dict, kind: str = "stack"):
    body = json.dumps(envelope).encode()
    req = urllib.request.Request(SITE + (f"/mac/{kind}/publish" if kind != "code" else "/mac/code/passed"),
                                 data=body, method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            answer = json.loads(r.read())
    except urllib.error.HTTPError as e:
        said = e.read().decode(errors='replace')[:400]
        if kind == "code" and e.code == 409:
            print(f"rouh.land keeps a newer commit as the newest that passed: {said}")
            return
        die(f"rouh.land refused it ({e.code}): {said}")
    sent = json.loads(envelope["payload"])
    if kind == "code":
        print(f"published: commit {sent['commit'][:12]} passed, {answer.get('state')} on {SITE}/mac/code/newest.json")
        return
    where = f"/mac/{kind}/{CHANNEL if kind == 'stack' else sent['line']}.json"
    print(f"published: release {answer.get('version')} is {answer.get('state')} on {SITE}{where}")
    live = {"stack": check, "base": check_base, "release": check_release}[kind](_get(where))
    if live["version"] != sent["version"]:
        die(f"rouh.land serves release {live['version']}, not the one just published")
    print(f"checked: {SITE}{where} serves it, signature good")


def describe(r: dict) -> str:
    lines = [f"release {r['version']} ({r['released']}), channel {r['channel']}, for Rouh for Mac {r['min_app']} or later",
             f"  from commit {r['commit'][:12]}" + (f", {r['run']}" if r.get("run") else ""),
             *(f"  {k:9} {v}" for k, v in sorted(r["images"].items()))]
    if r.get("rollback_of"):
        lines.insert(1, f"  a rollback: release {r['rollback_of']} again")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sign")
    s.add_argument("compose")
    s.add_argument("--commit", required=True)
    s.add_argument("--run", default="")
    s.add_argument("--min-app", default=MIN_APP)
    s.add_argument("--rollback-of", type=int)
    s.add_argument("--key")
    s.add_argument("out")
    sub.add_parser("verify").add_argument("file")
    sub.add_parser("publish").add_argument("file")
    sub.add_parser("status")
    sub.add_parser("list")
    rb = sub.add_parser("rollback")
    rb.add_argument("version", type=int)
    rb.add_argument("--key")
    bp = sub.add_parser("base-pin")
    bp.add_argument("--base", required=True, help="ghcr.io/rouh-it/rouh-base@sha256:...")
    bp.add_argument("--code", required=True, help="ghcr.io/rouh-it/rouh-code@sha256:...")
    bp.add_argument("--postgres", required=True, help=f"{POSTGRES}@sha256:..., the line's own pin (line.json)")
    bp.add_argument("--commit", default="")
    bp.add_argument("--source", required=True, help="a format-1 stack file (compose.ghcr.yml before 24 October 2026)")
    bp.add_argument("out")
    bs = sub.add_parser("base-sign")
    bs.add_argument("compose")
    bs.add_argument("--line", required=True)
    bs.add_argument("--level", required=True)
    bs.add_argument("--commit", required=True)
    bs.add_argument("--run", default="")
    bs.add_argument("--contents", help="a base.env file: name=value lines")
    bs.add_argument("--changes", help="a plan.json from base_patch.py look")
    bs.add_argument("--min-app", default=MIN_APP_BASE)
    bs.add_argument("--rollback-of", type=int)
    bs.add_argument("--key")
    bs.add_argument("out")
    sub.add_parser("base-verify").add_argument("file")
    sub.add_parser("base-publish").add_argument("file")
    sub.add_parser("base-status")
    sub.add_parser("base-list")
    br = sub.add_parser("base-rollback")
    br.add_argument("version", type=int)
    br.add_argument("--key")
    bg = sub.add_parser("bridge")
    bg.add_argument("--code-as-core", required=True, help="ghcr.io/rouh-it/rouh-core@sha256:... (the code image)")
    bg.add_argument("--base-as-workers", required=True, help="ghcr.io/rouh-it/rouh-workers@sha256:... (the base)")
    bg.add_argument("--base-as-keyproxy", required=True, help="ghcr.io/rouh-it/rouh-keyproxy@sha256:... (the base)")
    bg.add_argument("--postgres", required=True)
    bg.add_argument("--commit", default="")
    bg.add_argument("--source", required=True)
    bg.add_argument("out")
    rs = sub.add_parser("release-sign")
    rs.add_argument("--line", required=True)
    rs.add_argument("--level", required=True)
    rs.add_argument("--commit", required=True)
    rs.add_argument("--run", default="")
    rs.add_argument("--base", required=True)
    rs.add_argument("--guard", required=True)
    rs.add_argument("--postgres", required=True, help="the line's own pin, by digest (line.json postgres_image)")
    rs.add_argument("--postgres-version", default="")
    rs.add_argument("--code-commit", default="")
    rs.add_argument("--code-run", default="")
    rs.add_argument("--code-passed-at", default="")
    rs.add_argument("--contents")
    rs.add_argument("--changes")
    rs.add_argument("--min-app", default=MIN_APP_RELEASE)
    rs.add_argument("--key")
    rs.add_argument("out")
    sub.add_parser("release-verify").add_argument("file")
    sub.add_parser("release-publish").add_argument("file")
    sub.add_parser("release-status")
    sub.add_parser("release-list")
    rr = sub.add_parser("release-rollback")
    rr.add_argument("version", type=int)
    rr.add_argument("--key")
    cp = sub.add_parser("code-pass")
    cp.add_argument("--commit", required=True)
    cp.add_argument("--run", default="")
    cp.add_argument("--key")
    cp.add_argument("out")
    sub.add_parser("code-publish").add_argument("file")
    sub.add_parser("code-newest")
    sub.add_parser("check-sha256").add_argument("root", nargs="?", default=str(REPO))
    rm = sub.add_parser("release-matches")
    rm.add_argument("file")
    rm.add_argument("--src", required=True)
    rm.add_argument("--commit", required=True)
    rm.add_argument("--base", required=True)
    rm.add_argument("--guard", required=True)
    rm.add_argument("--code", default="")
    rm.add_argument("--tag", default="")
    a = ap.parse_args()

    def contents_and_changes():
        contents = {}
        if getattr(a, "contents", None):
            for line in Path(a.contents).read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    contents[k.strip()] = v.strip()
        changes = []
        if getattr(a, "changes", None):
            plan = json.loads(Path(a.changes).read_text())
            changes = [f"{c['what']} {c['from'] or '(new)'} -> {c['to']}" for c in plan.get("changes", [])]
            if plan.get("security"):
                changes.append(f"Debian security updates: {', '.join(s['package'] for s in plan['security'])}")
        return contents, changes

    if a.cmd == "release-sign":
        contents, changes = contents_and_changes()
        if a.postgres_version:
            contents["postgres"] = a.postgres_version
        code = None
        if a.code_commit:
            code = {"commit": a.code_commit, "run": a.code_run, "passed_at": a.code_passed_at}
        env = make_release(line=a.line, level=a.level, commit=a.commit, run=a.run,
                           images={"base": a.base, "guard": a.guard, "postgres": a.postgres},
                           postgres_version=a.postgres_version, code=code, contents=contents, changes=changes,
                           min_app=a.min_app, rollback_of=None, key_pem=_key_pem(a.key))
        Path(a.out).write_text(json.dumps(env, indent=1) + "\n")
        print(describe_release(json.loads(env["payload"])))
        return
    if a.cmd == "release-verify":
        try:
            print(describe_release(check_release(json.loads(Path(a.file).read_text()))))
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            die(f"refused: {e}")
        print("signature good")
        return
    if a.cmd == "release-publish":
        publish(json.loads(Path(a.file).read_text()), "release")
        return
    if a.cmd == "release-status":
        r = check_release(_get(f"/mac/release/{CHANNEL}.json"))
        print(f"live on {SITE}/mac/release/{CHANNEL}.json and /mac/release/{r['line']}.json, signature good:")
        print(describe_release(r))
        return
    if a.cmd == "release-list":
        for row in _get("/mac/release/releases.json")["releases"]:
            back = f", release {row['rollback_of']} again" if row.get("rollback_of") else ""
            print(f"{row['version']}  {row['released']}  base {row.get('level', '?')}  commit {row['commit'][:8]}"
                  f"{back}{'  (live)' if row.get('live') else ''}")
        return
    if a.cmd == "release-rollback":
        old = check_release(_get(f"/mac/release/releases/{a.version}.json"))
        env = make_release(line=old["line"], level=old["level"], commit=old["commit"], run=old.get("run", ""),
                           images=old["images"], postgres_version=(old.get("postgres") or {}).get("version", ""),
                           code=old.get("code"), contents=old.get("contents") or {}, changes=old.get("changes") or [],
                           min_app=old["min_app"], rollback_of=old["version"], key_pem=_key_pem(a.key),
                           compose=old["compose"], policy=old["policy"], guard=old["guard"],
                           check=old.get("check_sha256"))
        print(describe_release(json.loads(env["payload"])))
        publish(env, "release")
        return
    if a.cmd == "code-pass":
        env = make_code_pass(a.commit, a.run, _key_pem(a.key))
        Path(a.out).write_text(json.dumps(env, indent=1) + "\n")
        print(f"signed: main at {a.commit[:12]} passed its tests")
        return
    if a.cmd == "code-publish":
        publish(json.loads(Path(a.file).read_text()), "code")
        return
    if a.cmd == "release-matches":
        try:
            r = check_release(json.loads(Path(a.file).read_text()))
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            die(f"refused: {e}")
        wrong = release_matches(r, Path(a.src).resolve(), commit=a.commit, base=a.base, guard=a.guard, code=a.code,
                               tag=a.tag)
        for w in wrong:
            print(f"not the commit it names: {w}", file=sys.stderr)
        if wrong:
            sys.exit(1)
        print(f"release {r['version']}: commit {a.commit[:12]}'s own stack file, allow-list, stack check and images"
              + (f", tagged {a.tag}" if a.tag else ""))
        return
    if a.cmd == "check-sha256":
        print(check_sha256(Path(a.root).resolve()))
        return
    if a.cmd == "code-newest":
        print(json.dumps(_get("/mac/code/newest.json"), indent=1))
        return

    if a.cmd == "sign":
        env = make(Path(a.compose).read_text(), commit=a.commit, run=a.run, min_app=a.min_app,
                   rollback_of=a.rollback_of, key_pem=_key_pem(a.key))
        Path(a.out).write_text(json.dumps(env, indent=1) + "\n")
        print(describe(json.loads(env["payload"])))
    elif a.cmd == "verify":
        try:
            print(describe(check(json.loads(Path(a.file).read_text()))))
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            die(f"refused: {e}")
        print("signature good")
    elif a.cmd == "publish":
        publish(json.loads(Path(a.file).read_text()))
    elif a.cmd == "status":
        r = check(_get(f"/mac/stack/{CHANNEL}.json"))
        print(f"live on {SITE}/mac/stack/{CHANNEL}.json, signature good:")
        print(describe(r))
    elif a.cmd == "list":
        for row in _get("/mac/stack/releases.json")["releases"]:
            back = f", release {row['rollback_of']} again" if row.get("rollback_of") else ""
            print(f"{row['version']}  {row['released']}  commit {row['commit'][:8]}{back}{'  (live)' if row.get('live') else ''}")
    elif a.cmd == "rollback":
        old = check(_get(f"/mac/stack/releases/{a.version}.json"))
        env = make(old["compose"], commit=old["commit"], run=old.get("run", ""), min_app=old["min_app"],
                   rollback_of=old["version"], key_pem=_key_pem(a.key))
        print(describe(json.loads(env["payload"])))
        publish(env)
    elif a.cmd == "base-pin":
        images = {"base": a.base, "code": a.code, "postgres": a.postgres}
        for k, v in images.items():
            if not DIGEST.search(v):
                die(f"--{k} is not pinned by digest: {v}")
        Path(a.out).write_text(pin_base(Path(a.source).read_text(), images, a.commit))
        print(f"pinned: {a.out}")
        for k, v in sorted(images.items()):
            print(f"  {k:9} {v}")
    elif a.cmd == "base-sign":
        contents = {}
        if a.contents:
            for line in Path(a.contents).read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    contents[k.strip()] = v.strip()
        changes = []
        if a.changes:
            plan = json.loads(Path(a.changes).read_text())
            changes = [f"{c['what']} {c['from'] or '(new)'} -> {c['to']}" for c in plan.get("changes", [])]
            if plan.get("security"):
                changes.append(f"Debian security updates: {', '.join(s['package'] for s in plan['security'])}")
        env = make_base(Path(a.compose).read_text(), line=a.line, level=a.level, commit=a.commit, run=a.run,
                        contents=contents, changes=changes, min_app=a.min_app, rollback_of=a.rollback_of,
                        key_pem=_key_pem(a.key))
        Path(a.out).write_text(json.dumps(env, indent=1) + "\n")
        print(describe_base(json.loads(env["payload"])))
    elif a.cmd == "base-verify":
        try:
            print(describe_base(check_base(json.loads(Path(a.file).read_text()))))
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            die(f"refused: {e}")
        print("signature good")
    elif a.cmd == "base-publish":
        publish(json.loads(Path(a.file).read_text()), "base")
    elif a.cmd == "base-status":
        r = check_base(_get(f"/mac/base/{CHANNEL}.json"))
        print(f"live on {SITE}/mac/base/{CHANNEL}.json and /mac/base/{r['line']}.json, signature good:")
        print(describe_base(r))
    elif a.cmd == "base-list":
        for row in _get("/mac/base/releases.json")["releases"]:
            back = f", base release {row['rollback_of']} again" if row.get("rollback_of") else ""
            print(f"{row['version']}  {row['released']}  base {row.get('level', '?')}  commit {row['commit'][:8]}"
                  f"{back}{'  (live)' if row.get('live') else ''}")
    elif a.cmd == "base-rollback":
        old = check_base(_get(f"/mac/base/releases/{a.version}.json"))
        env = make_base(old["compose"], line=old["line"], level=old["level"], commit=old["commit"],
                        run=old.get("run", ""), contents=old.get("contents") or {}, changes=old.get("changes") or [],
                        min_app=old["min_app"], rollback_of=old["version"], key_pem=_key_pem(a.key))
        print(describe_base(json.loads(env["payload"])))
        publish(env, "base")
    elif a.cmd == "bridge":
        images = {"core": a.code_as_core, "workers": a.base_as_workers, "keyproxy": a.base_as_keyproxy,
                  "postgres": a.postgres}
        for k, v in images.items():
            if not DIGEST.search(v):
                die(f"the {k} image is not pinned by digest: {v}")
        text = pin_bridge(Path(a.source).read_text(), images, a.commit)
        images_in(text)
        Path(a.out).write_text(text)
        print(f"the bridge: {a.out}")
        for k, v in sorted(images.items()):
            print(f"  {k:9} {v}")


if __name__ == "__main__":
    main()
