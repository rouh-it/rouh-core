#!/usr/bin/env python3
"""The base image's patch levels: what a new rouh-base would change, patch-level only.

Petar, 23 October 2026: "latest" means only patch-level fixes to what Rouh runs on, and those go
in automatically; everything else - features, Rouh's own logic, its own security fixes, big
library upgrades - reaches a Rouh only as a gene. So a base belongs to a **line** (1.0, 1.1, ...)
that fixes the Python minor version and every library's minor version, and each night that finds
patch-level fixes makes the next **patch level** of that line (1.0.0, 1.0.1, ...).

A line's state is a folder, kept in main at ``deploy/container/base/`` since 30 October 2026,
so one commit of main holds both the code and the exact versions its images are built with
(until then it was the branch ``base``, now ``archive/base-branch-until-2026-10``):

    line.json          the line, its patch number and level, the commit its code was cut from,
                       and every pin that is not a Python library (the Python and Node images,
                       Codex, Playwright MCP, and the database image, pinned by its digest with
                       the PostgreSQL version inside it: postgres_image, postgres_version)
    pyproject.toml     the cut commit's, each pinned library held within its minor line
    uv.lock            the line's lock: the cut's versions, moved on by patch levels only
    requirements.txt   that lock written out for the image (Dockerfile.base installs it)
    plan.json          what this level changes over the one before, and what is newer than a
                       patch, which it lists and leaves for genes; the release signs its changes

What a build made is not kept in git: base.yml puts each level's records - how the check went on
Intel and Arm, what was published, every Debian package in the images (dpkg-<arch>.txt) and
their base.env - on that level's GitHub Release, ``base-<level>``. The look reads the published
level's Debian packages out of its image instead, which anyone may pull.

    base_patch.py cut --repo DIR --line 1.0 --commit SHA STATE
                                                   a new line from a checkout: level <line>.0
    base_patch.py look STATE [--write]             the patch-level updates there are; --write
                                                   makes them the line's next level in STATE
    base_patch.py report STATE                     plan.json in words
    base_patch.py changes BEFORE AFTER             every version that differs between two states,
                                                   as a table (the pull request's body)

What counts as a patch, the same for everything: the same major and minor version and a larger
patch (3.12.14 -> 3.12.15, 5.2.17 -> 5.2.18, 24.22.1 -> 24.22.2). PostgreSQL is the one exception:
since version 10 it numbers a fix release with its second part, so for it 18.1 -> 18.2 is a patch
(the same major, a larger second number) and 18 -> 19 never is (task 98, step 98-23). For a 0.x version that is the
same 0.minor; a 0.0.x version promises nothing between releases, so it never moves by itself
(Playwright MCP is one). Pre-releases never count. Debian's security updates - Chromium's
security releases among them, which trixie-security carries for Intel and Arm alike - are taken
whole, as Debian ships them for the release, by the build's apt upgrade; this only says which.

Every Python library is tried on its own (``uv lock --upgrade-package 'name<next minor'``), and
kept only when the whole lock then moved by patch levels alone; one that would drag another
library past its minor is left and listed. Django stays on 5.2, its long-term support line,
because the line holds it there like any other.

Standard library only, plus uv for the lock, so it runs inside the Creator Rouh (the owner's Rouh
that makes Rouh's releases), where Clockwork starts it (rouh/base_patches.py), and on GitHub's runners.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import io
import lzma
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = "rouh-base-patch/1"
HUB = "https://hub.docker.com/v2/repositories"
#: The database image's tag. Its digest and the PostgreSQL inside it are the line's (line.json).
POSTGRES = "pgvector/pgvector:0.8.2-pg18-trixie"
REGISTRY = "https://registry-1.docker.io"
DOCKER_AUTH = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
PYPI = "https://pypi.org/pypi"
NPM = "https://registry.npmjs.org"
DEBIAN_SECURITY = "https://security.debian.org/debian-security/dists/trixie-security/main/binary-{arch}/Packages.xz"
ARCHES = ("amd64", "arm64")
#: Where the published base is, which anyone may pull (the look reads its Debian packages there).
GHCR = os.environ.get("ROUH_BASE_REGISTRY", "https://ghcr.io")
BASE_REPO = "rouh-it/rouh-base"
#: What the one program needs that Rouh's own lock does not have (one/requirements.txt, without
#: its test-only pins).
HEADER = """# Every Python library of Rouh and of the one program, pinned, for the base image
# (deploy/container/Dockerfile.base). Generated, never edited: {how}.
"""


def die(msg: str):
    print(f"base_patch: {msg}", file=sys.stderr)
    sys.exit(1)


def _get(url: str, *, raw: bool = False, timeout: float = 60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return body if raw else json.loads(body)


# ---------------------------------------------------------------- versions


def parts(v: str) -> tuple[int, ...] | None:
    """1.2.3 -> (1, 2, 3); None for anything that is not plain numbers (a pre-release)."""
    if not re.fullmatch(r"\d+(\.\d+)*", v or ""):
        return None
    return tuple(int(p) for p in v.split("."))


def is_patch(old: str, new: str) -> bool:
    """Whether `new` is a newer patch of `old`'s minor line (see the module's rule)."""
    a, b = parts(old), parts(new)
    if not a or not b or len(a) < 2 or b <= a:
        return False
    if a[0] == 0 and (len(a) < 3 or a[1] == 0):
        return False  # 0.0.x promises nothing between releases
    return b[:2] == a[:2]


def newer_kind(old: str, new: str) -> str:
    """"patch", "minor" or "major" for a newer `new`, "" otherwise."""
    a, b = parts(old), parts(new)
    if not a or not b or b <= a:
        return ""
    if is_patch(old, new):
        return "patch"
    return "major" if b[0] != a[0] else "minor"


def is_pg_patch(old: str, new: str) -> bool:
    """For PostgreSQL, major.patch: 18.1 -> 18.2 is a patch, 18.x -> 19.0 is not."""
    a, b = parts(old), parts(new)
    if not a or not b or len(a) < 2 or len(b) < 2:
        return False
    return a[0] == b[0] and b[:2] > a[:2]


def pg_newer_kind(old: str, new: str) -> str:
    """"patch", "major" or "" for PostgreSQL versions (major.patch)."""
    a, b = parts(old), parts(new)
    if not a or not b or b[:2] <= a[:2]:
        return ""
    return "patch" if is_pg_patch(old, new) else "major"


def bound(v: str) -> str:
    """The first version past `v`'s minor line: 5.2.17 -> 5.3."""
    p = parts(v) or (0, 0)
    return f"{p[0]}.{(p[1] if len(p) > 1 else 0) + 1}"


# ---------------------------------------------------------------- the lock


def lock_versions(lock: Path) -> dict[str, str]:
    out, name = {}, None
    for line in lock.read_text().splitlines():
        if line == "[[package]]":
            name = None
        m = re.match(r'^name = "([^"]+)"$', line)
        if m:
            name = m.group(1)
        m = re.match(r'^version = "([^"]+)"$', line)
        if m and name:
            out[name] = m.group(1)
            name = None
    out.pop("rouh", None)
    return out


def relax(pyproject: str) -> str:
    """Every "name==X.Y.Z" in the dependencies held within its minor line instead: >=X.Y.Z,<X.(Y+1)."""
    def one(m):
        name, ver = m.group(1), m.group(2)
        return f'"{name}>={ver},<{bound(ver)}"' if parts(ver) and len(parts(ver)) >= 2 else m.group(0)
    return re.sub(r'"([A-Za-z0-9_.\-]+(?:\[[A-Za-z0-9_,\-]+\])?)==([0-9][0-9.]*)"', one, pyproject)


#: The uv the look locks with, the same one base.yml installs on GitHub.
UV_VERSION = "0.12.15"


class NoUv(RuntimeError):
    """uv is not here and could not be had: says the path looked for and why."""


def _find_uv() -> str:
    """uv, from PATH, else the pinned one installed once into a folder of its own.

    The base image has no uv (the image installs with pip), and the Creator Rouh's look runs in
    its core container since 31 October 2026, where the old "/usr/local/bin/uv" of the server is
    not: every night from then on stopped on FileNotFoundError. So a uv that is not on PATH is
    installed with pip, pinned, into ``ROUH_UV_DIR`` (base_patches.py gives its own data folder),
    else ``~/.cache/rouh/uv-<version>``, and used from there. Never a silent pass: if it cannot
    be had, NoUv says the exact path and the reason."""
    found = shutil.which("uv")
    if found:
        return found
    if Path("/usr/local/bin/uv").is_file():
        return "/usr/local/bin/uv"
    where = Path(os.environ.get("ROUH_UV_DIR") or Path.home() / ".cache" / "rouh" / f"uv-{UV_VERSION}")
    uv = where / "bin" / "uv"
    if uv.is_file() and os.access(uv, os.X_OK):
        return str(uv)
    try:
        where.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                            "--no-deps", "--upgrade", "--target", str(where), f"uv=={UV_VERSION}"],
                           capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as e:
        raise NoUv(f"uv is not on PATH or at /usr/local/bin/uv, and uv {UV_VERSION} could not be installed "
                   f"into {where}: {type(e).__name__}: {e}") from None
    if r.returncode or not uv.is_file():
        said = [ln.strip() for ln in (r.stderr or r.stdout).splitlines() if ln.strip()]
        why = next((ln for ln in reversed(said) if ln.startswith("ERROR")), said[-1] if said else f"pip left no {uv}")
        raise NoUv(f"uv is not on PATH or at /usr/local/bin/uv, and uv {UV_VERSION} could not be installed "
                   f"into {where}: {why}")
    return str(uv)


def _uv(*args, cwd: Path) -> subprocess.CompletedProcess:
    uv = _find_uv()
    return subprocess.run([uv, *args], cwd=str(cwd), capture_output=True, text=True, timeout=600,
                          env=dict(os.environ, UV_NO_PROGRESS="1", UV_PYTHON_DOWNLOADS="automatic"))


def one_pins(repo: Path) -> list[str]:
    """The one program's own run pins (one/requirements.txt, without the test-only part)."""
    out = []
    for line in (repo / "one" / "requirements.txt").read_text().splitlines():
        if line.startswith("# Only for the tests"):
            break
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def export(folder: Path, how: str) -> str:
    r = _uv("export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project", "--no-header",
            "--no-annotate", cwd=folder)
    if r.returncode:
        die(f"uv export failed: {r.stderr.strip()[-400:]}")
    return HEADER.format(how=how) + r.stdout


def runtime_names(folder: Path) -> set[str]:
    """The libraries a lock installs for running (no dev group), by name."""
    r = _uv("export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project", "--no-header",
            "--no-annotate", cwd=folder)
    if r.returncode:
        die(f"uv export failed: {r.stderr.strip()[-400:]}")
    return {re.split(r"[=<>\[ ;]", line, maxsplit=1)[0].lower() for line in r.stdout.splitlines()
            if line and not line.startswith(("#", " "))}


def with_one(pyproject: str, pins: list[str], installed: set[str]) -> str:
    """The one program's pins added to the dependencies where Rouh's own do not have them (the
    dev group's do not count: the image never installs those)."""
    missing = []
    for pin in pins:
        name = re.split(r"[=<>\[]", pin, maxsplit=1)[0].lower()
        if name not in installed:
            missing.append(pin)
    if not missing:
        return pyproject
    at = pyproject.index("dependencies = [") + len("dependencies = [")
    add = "".join(f'\n    # The one program\'s own (one/requirements.txt).\n    "{p}",' for p in missing)
    return pyproject[:at] + add + pyproject[at:]


# ---------------------------------------------------------------- the commands


def cmd_cut(repo: Path, line: str, commit: str, state: Path) -> None:
    """A new line from a checkout of `commit`: its pins as they are, level <line>.0."""
    if not re.fullmatch(r"\d+\.\d+", line):
        die("a line is two numbers, such as 1.0")
    state.mkdir(parents=True, exist_ok=True)
    shutil.copy(repo / "uv.lock", state / "uv.lock")
    shutil.copy(repo / "pyproject.toml", state / "pyproject.toml")
    text = (repo / "pyproject.toml").read_text()
    text = relax(with_one(text, one_pins(repo), runtime_names(state)))
    (state / "pyproject.toml").write_text(text)
    before = lock_versions(state / "uv.lock")
    r = _uv("lock", cwd=state)
    if r.returncode:
        die(f"uv lock failed: {r.stderr.strip()[-400:]}")
    moved = {k: (before.get(k), v) for k, v in lock_versions(state / "uv.lock").items() if before.get(k, v) != v}
    if moved:
        die(f"holding the pins within their minor lines moved some of them: {moved}")
    docker = re.search(r"^ARG PYTHON_IMAGE=(\S+)", (repo / "deploy/container/Dockerfile.base").read_text(), re.M).group(1)
    node = re.search(r"^ARG NODE_IMAGE=(\S+)", (repo / "deploy/container/Dockerfile.base").read_text(), re.M).group(1)
    codex = re.search(r"^ARG CODEX_VERSION=(\S+)", (repo / "deploy/container/Dockerfile.base").read_text(), re.M).group(1)
    mcp = re.search(r"^ARG PLAYWRIGHT_MCP_VERSION=(\S+)", (repo / "deploy/container/Dockerfile.base").read_text(), re.M).group(1)
    info = {"line": line, "patch": 0, "level": f"{line}.0", "cut_commit": commit,
            "cut_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "python_image": docker, "node_image": node, "codex": codex, "playwright_mcp": mcp}
    digest, version = _pg_image(POSTGRES)
    info.update(postgres_image=f"{POSTGRES}@{digest}", postgres_version=version)
    (state / "line.json").write_text(json.dumps(info, indent=1) + "\n")
    (state / "requirements.txt").write_text(export(state, f"the base line {line}'s lock, deploy/container/base"))
    plan = {"level": info["level"], "line": line, "cut": commit, "changes": [], "security": [], "left_for_genes": []}
    (state / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    print(f"cut line {line} at {commit[:12]}: level {info['level']}, {len(before)} Python libraries")


#: What every base is built for: a tag is taken only once Docker Hub has its image for each.
ARCHES = {"amd64", "arm64"}


def _hub_tags(repo: str, prefix: str, suffix: str) -> list[str]:
    """The tags that start with `prefix` and end with `suffix`, and whose images for linux/amd64
    and linux/arm64 are both published. A new release's tag appears before all its images do: on
    11 November 2026 node:24.22.3-trixie-slim had only ppc64le and s390x, base 1.0.13 took it, and
    its build stopped on "no match for platform in manifest". Such a tag is taken a night later."""
    url = f"{HUB}/{repo if '/' in repo else 'library/' + repo}/tags?name={urllib.parse.quote(prefix)}&page_size=100"
    names = []
    seen = 0
    while url and seen < 1000:
        page = _get(url)
        for t in page.get("results", []):
            seen += 1
            arches = {i.get("architecture") for i in t.get("images") or [] if i.get("os") == "linux"}
            if ARCHES <= arches:
                names.append(t["name"])
        url = page.get("next")
    return [n for n in names if n.startswith(prefix) and n.endswith(suffix)]


def _image_update(image: str, kind: str) -> tuple[str, str]:
    """The newest patch of an image tag such as python:3.12.14-slim-trixie: (new tag or "", newest any)."""
    name, tag = image.split(":", 1)
    m = re.match(r"^(\d+\.\d+\.\d+)(-.+)$", tag)
    if not m:
        return "", ""
    version, suffix = m.groups()
    major_minor = ".".join(version.split(".")[:2]) + "."
    best, newest = "", ""
    seen = set(_hub_tags(name, major_minor, suffix)) | set(_hub_tags(name, version.split(".")[0] + ".", suffix))
    for t in sorted(seen):
        v = t[: -len(suffix)]
        if not parts(v) or len(parts(v)) != 3:
            continue
        if is_patch(version, v) and (not best or parts(v) > parts(best)):
            best = v
        if parts(v) > parts(version) and (not newest or parts(v) > parts(newest)):
            newest = v
    return (f"{name}:{best}{suffix}" if best else ""), newest


def _pg_image(ref: str) -> tuple[str, str]:
    """The digest a tag of the database image points to now, and the PostgreSQL inside it (its
    PG_VERSION, "18.4-1.pgdg13+1" read as 18.4), from the registry itself."""
    name, tag = ref.split("@", 1)[0].split(":", 1)
    auth = {"Authorization": "Bearer " + _get(DOCKER_AUTH.format(repo=name))["token"]}
    accept = ("application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, "
              "application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json")

    def fetch(path, accept_one=accept):
        req = urllib.request.Request(f"{REGISTRY}/v2/{name}/{path}",
                                     headers={"User-Agent": UA, "Accept": accept_one, **auth})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.headers.get("Docker-Content-Digest", ""), json.loads(r.read())

    digest, index = fetch(f"manifests/{tag}")
    manifests = index.get("manifests") or []
    one = next((m for m in manifests if (m.get("platform") or {}).get("architecture") == "amd64"), None)
    manifest = fetch(f"manifests/{one['digest']}")[1] if one else index
    _, config = fetch(f"blobs/{manifest['config']['digest']}", "*/*")
    env = dict(e.split("=", 1) for e in (config.get("config") or {}).get("Env") or [] if "=" in e)
    version = re.match(r"^(\d+(?:\.\d+)?)", env.get("PG_VERSION", "")) if env.get("PG_VERSION") else None
    return digest, version.group(1) if version else ""


def _pg_majors(name: str, pgvector: str, suffix: str) -> list[int]:
    """The PostgreSQL majors the database image has a tag for, for this pgvector version."""
    found = set()
    for t in _hub_tags(name, f"{pgvector}-pg", ""):
        m = re.fullmatch(re.escape(pgvector) + r"-pg(\d+)" + re.escape(re.sub(r"^-pg\d+", "", suffix)), t)
        if m:
            found.add(int(m.group(1)))
    return sorted(found)


def _postgres(info: dict, new_info: dict, changes: list, left: list) -> None:
    """The database image: a newer pgvector patch of the same PostgreSQL major, and the digest its
    tag points to now. A rebuild or a PostgreSQL fix (18.1 -> 18.2) is a patch level; another
    PostgreSQL major is listed and left for genes."""
    pinned = info.get("postgres_image") or POSTGRES
    old_version = info.get("postgres_version", "")
    if "@" not in pinned:
        # A line from before the database image was pinned: first what its tag gives today.
        d, old_version = _pg_image(pinned)
        pinned = f"{pinned}@{d}"
        new_info.update(postgres_image=pinned, postgres_version=old_version)
    ref = pinned.split("@", 1)[0]
    name, tag = ref.split(":", 1)
    m = re.match(r"^(\d+\.\d+\.\d+)(-pg(\d+)-.+)$", tag)
    target = ref
    if m:
        newer, _ = _image_update(ref, "pgvector")
        if newer:
            target = newer
        majors = _pg_majors(name, m.group(1), m.group(2))
        bigger = [n for n in majors if n > int(m.group(3))]
        if bigger:
            left.append({"what": "PostgreSQL", "from": m.group(3), "to": str(max(bigger)), "kind": "major"})
    digest, version = _pg_image(target)
    old_digest = pinned.split("@", 1)[1]
    if not digest:
        return
    if old_digest and digest == old_digest and target == ref:
        return
    if old_version and version and pg_newer_kind(old_version, version) == "major":
        left.append({"what": "PostgreSQL", "from": old_version, "to": version, "kind": "major"})
        return
    to = version if version != old_version else f"{version}, rebuilt"
    changes.append({"what": "PostgreSQL", "from": old_version or "unknown", "to": to + (
        f" ({target.split(':', 1)[1]})" if target != ref else "")})
    new_info["postgres_image"] = f"{target}@{digest}"
    new_info["postgres_version"] = version


def _npm_update(package: str, version: str) -> tuple[str, str]:
    doc = _get(f"{NPM}/{urllib.parse.quote(package, safe='@')}")
    versions = [v for v in doc.get("versions", {}) if parts(v)]
    best = max((v for v in versions if is_patch(version, v)), key=parts, default="")
    newest = max((v for v in versions if parts(v) > (parts(version) or ())), key=parts, default="")
    return best, newest


def _pypi_versions(name: str) -> list[str]:
    try:
        doc = _get(f"{PYPI}/{name}/json", timeout=30)
    except Exception:  # noqa: BLE001 - a library PyPI cannot answer for is left as it is
        return []
    out = []
    for v, files in doc.get("releases", {}).items():
        if not parts(v) or not files or all(f.get("yanked") for f in files):
            continue
        out.append(v)
    return out


def published_contents(tag: str) -> dict[str, dict[str, str]]:
    """What the published base `tag` (a level, a line, or latest) holds, per platform, read out of
    the image itself with no sign-in: {arch: {"dpkg.txt": ..., "base.env": ...}}. Both files are
    in the image's last layer (Dockerfile.base writes them last), a few kilobytes, so nothing
    else is downloaded."""
    token = _get(f"{GHCR}/token?scope=repository:{BASE_REPO}:pull")["token"]

    def fetch(path: str, accept: str) -> bytes:
        req = urllib.request.Request(f"{GHCR}/v2/{BASE_REPO}/{path}", headers={
            "User-Agent": UA, "Authorization": f"Bearer {token}", "Accept": accept})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    index = json.loads(fetch(f"manifests/{tag}", "application/vnd.oci.image.index.v1+json"))
    out = {}
    for m in index.get("manifests", []):
        arch = (m.get("platform") or {}).get("architecture")
        if (m.get("platform") or {}).get("os") != "linux" or arch not in ARCHES:
            continue
        manifest = json.loads(fetch(f"manifests/{m['digest']}", m["mediaType"]))
        for layer in reversed(manifest["layers"][-3:]):
            if layer.get("size", 0) > 4_000_000:
                continue
            with tarfile.open(fileobj=io.BytesIO(fetch(f"blobs/{layer['digest']}", "*/*")), mode="r:*") as tar:
                names = set(tar.getnames())
                if "opt/rouh-base/dpkg.txt" in names:
                    out[arch] = {f: tar.extractfile(f"opt/rouh-base/{f}").read().decode()
                                 for f in ("dpkg.txt", "base.env") if f"opt/rouh-base/{f}" in names}
                    break
        if arch not in out:
            die(f"base {tag} for {arch} has no /opt/rouh-base/dpkg.txt in its last layers")
    if set(out) != set(ARCHES):
        die(f"base {tag} is not published for {', '.join(sorted(set(ARCHES) - set(out)))}")
    return out


def _dpkg_text(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        bits = line.split()
        if len(bits) == 2:
            out[bits[0].split(":")[0]] = bits[1]
    return out


def _version_gt(a: str, b: str) -> bool:
    return subprocess.run(["dpkg", "--compare-versions", a, "gt", b]).returncode == 0


def _security(line: str) -> list[dict]:
    """Every Debian package in what every Rouh of `line` runs - its newest published level, the
    image tag <line>, or latest for a line with none yet - that trixie-security has a newer build of."""
    found = {}
    try:
        contents = published_contents(line)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        contents = published_contents("latest")
    for arch in ARCHES:
        installed = _dpkg_text(contents[arch]["dpkg.txt"])
        index = lzma.decompress(_get(DEBIAN_SECURITY.format(arch=arch), raw=True)).decode(errors="replace")
        pkg = ver = ""
        for line in index.splitlines() + [""]:
            if line.startswith("Package: "):
                pkg = line[9:].strip()
            elif line.startswith("Version: "):
                ver = line[9:].strip()
            elif not line.strip():
                if pkg in installed and ver and _version_gt(ver, installed[pkg]):
                    found.setdefault(pkg, {"package": pkg, "from": installed[pkg], "to": ver, "arches": []})
                    if arch not in found[pkg]["arches"]:
                        found[pkg]["arches"].append(arch)
                pkg = ver = ""
    return sorted(found.values(), key=lambda d: d["package"])


def cmd_look(state: Path, write: bool) -> dict:
    """What the next patch level would change; with `write`, that level made in `state`."""
    info = json.loads((state / "line.json").read_text())
    changes, left = [], []

    # The Python and Node images.
    new_info = dict(info)
    for key, label in (("python_image", "Python"), ("node_image", "Node")):
        tag, newest = _image_update(info[key], label)
        old_v = re.search(r":(\d+\.\d+\.\d+)", info[key]).group(1)
        if tag:
            new_v = re.search(r":(\d+\.\d+\.\d+)", tag).group(1)
            changes.append({"what": label, "from": old_v, "to": new_v})
            new_info[key] = tag
        if newest and newer_kind(old_v, newest) in ("minor", "major"):
            left.append({"what": label, "from": old_v, "to": newest, "kind": newer_kind(old_v, newest)})

    # Codex, and Playwright MCP (0.0.x: listed, never taken).
    for key, package in (("codex", "@openai/codex"), ("playwright_mcp", "@playwright/mcp")):
        best, newest = _npm_update(package, info[key])
        if best:
            changes.append({"what": package, "from": info[key], "to": best})
            new_info[key] = best
        if newest and newest != best:
            kind = newer_kind(info[key], newest) or "patch"
            if kind != "patch" or not best:
                left.append({"what": package, "from": info[key], "to": newest,
                             "kind": kind if kind != "patch" else "0.0.x"})

    # The database image: its digest pinned, PostgreSQL major.patch (18.1 -> 18.2 is a patch).
    _postgres(info, new_info, changes, left)

    # The Python libraries, each on its own, kept only when the whole lock moved by patches alone.
    with tempfile.TemporaryDirectory() as t:
        work = Path(t)
        for f in ("pyproject.toml", "uv.lock"):
            shutil.copy(state / f, work / f)
        current = lock_versions(work / "uv.lock")
        start = dict(current)
        # Only what the image installs: the dev group's test tools never reach a base.
        runtime = runtime_names(work)
        for name in sorted(n for n in current if n.lower() in runtime):
            versions = _pypi_versions(name)
            v = current[name]
            newest = max((x for x in versions if parts(x) > (parts(v) or ())), key=parts, default="")
            if newest and newer_kind(v, newest) in ("minor", "major"):
                left.append({"what": name, "from": v, "to": newest, "kind": newer_kind(v, newest)})
            if not any(is_patch(v, x) for x in versions):
                continue
            keep = (work / "uv.lock").read_text()
            r = _uv("lock", "--upgrade-package", f"{name}<{bound(v)}", cwd=work)
            after = lock_versions(work / "uv.lock") if r.returncode == 0 else {}
            moved = {k: (current.get(k), nv) for k, nv in after.items() if current.get(k) != nv}
            if r.returncode or any(not is_patch(o, n) for o, n in moved.values() if o):
                (work / "uv.lock").write_text(keep)
                why = (r.stderr.strip().splitlines() or ["uv could not lock it"])[-1] if r.returncode else \
                      "it needs " + ", ".join(f"{k} {o} -> {n}" for k, (o, n) in moved.items() if o and not is_patch(o, n))
                left.append({"what": name, "from": v, "to": max((x for x in versions if is_patch(v, x)), key=parts),
                             "kind": "patch held back", "why": why[:200]})
                continue
            current = after
        for k, nv in sorted(current.items()):
            if k.lower() not in runtime:
                continue
            if start.get(k) and start[k] != nv:
                changes.append({"what": k, "from": start[k], "to": nv})
            elif not start.get(k):
                changes.append({"what": k, "from": "", "to": nv})
        lock_changed = current != start
        if write and lock_changed:
            shutil.copy(work / "uv.lock", state / "uv.lock")

    security = _security(info["line"])
    level = info["level"]
    changed = bool(changes or security)
    if changed:
        new_info["patch"] = int(info["patch"]) + 1
        new_info["level"] = f"{info['line']}.{new_info['patch']}"
        level = new_info["level"]
    plan = {"level": level, "line": info["line"], "from_level": info["level"], "changed": changed,
            "changes": changes, "security": security, "left_for_genes": left,
            "looked_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if write and not changed and "postgres_image" not in info and new_info.get("postgres_image"):
        # A line from before the database image was pinned: pinned now, at the level it is on.
        (state / "line.json").write_text(json.dumps(new_info, indent=1) + "\n")
    if write and changed:
        (state / "line.json").write_text(json.dumps(new_info, indent=1) + "\n")
        (state / "requirements.txt").write_text(export(state, f"the base line {info['line']}'s lock, deploy/container/base"))
        (state / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
    return plan


def report(plan: dict) -> str:
    lines = [f"# Base {plan['level']}", ""]
    if plan.get("cut"):
        lines.append(f"A new line, {plan['line']}, cut from commit {str(plan['cut'])[:12]}: every pin as that commit has it.")
    elif plan.get("changed"):
        lines.append(f"Patch-level updates over {plan['from_level']}:")
        lines += [f"- {c['what']} {c['from'] or '(new)'} -> {c['to']}" for c in plan["changes"]]
        if plan["security"]:
            lines.append(f"- Debian security updates: {len(plan['security'])} packages "
                         f"({', '.join(s['package'] for s in plan['security'][:12])}"
                         f"{', ...' if len(plan['security']) > 12 else ''})")
    else:
        lines.append(f"Nothing new: {plan['from_level']} has every patch-level update there is.")
    if plan.get("left_for_genes"):
        lines += ["", "Newer than a patch, so left for genes:"]
        lines += [f"- {c['what']} {c['from']} -> {c['to']} ({c['kind']}{': ' + c['why'] if c.get('why') else ''})"
                  for c in plan["left_for_genes"]]
    return "\n".join(lines) + "\n"


def _pins(state: Path) -> dict[str, str]:
    """Every version a state pins: line.json's, and each library the image installs."""
    info = json.loads((state / "line.json").read_text())
    out = {"Python image": info.get("python_image", ""), "Node image": info.get("node_image", ""),
           "@openai/codex": info.get("codex", ""), "@playwright/mcp": info.get("playwright_mcp", ""),
           "PostgreSQL image": info.get("postgres_image", ""), "PostgreSQL": info.get("postgres_version", "")}
    for line in (state / "requirements.txt").read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==(\S+)", line)
        if m:
            out[m.group(1).lower()] = m.group(2)
    return out


def changes_table(before: Path, after: Path) -> str:
    """Every version that differs between two states, as a Markdown table."""
    a, b = _pins(before), _pins(after)
    la, lb = (json.loads((x / "line.json").read_text())["level"] for x in (before, after))
    rows = [(k, a.get(k, ""), b.get(k, "")) for k in sorted(set(a) | set(b), key=lambda k: (k[0].islower(), k))
            if a.get(k, "") != b.get(k, "")]
    out = [f"Base {la} -> {lb}: {len(rows)} pinned versions change.", ""]
    if rows:
        out += ["| What | From | To |", "| --- | --- | --- |"]
        out += [f"| {k} | `{o or '(none)'}` | `{n or '(none)'}` |" for k, o, n in rows]
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut")
    c.add_argument("--repo", required=True)
    c.add_argument("--line", required=True)
    c.add_argument("--commit", required=True)
    c.add_argument("state")
    lk = sub.add_parser("look")
    lk.add_argument("state")
    lk.add_argument("--write", action="store_true")
    lk.add_argument("--json", action="store_true")
    sub.add_parser("report").add_argument("state")
    ch = sub.add_parser("changes")
    ch.add_argument("before")
    ch.add_argument("after")
    a = ap.parse_args()
    if a.cmd == "report":
        print(report(json.loads((Path(a.state) / "plan.json").read_text())), end="")
    elif a.cmd == "changes":
        print(changes_table(Path(a.before), Path(a.after)), end="")
    elif a.cmd == "cut":
        cmd_cut(Path(a.repo), a.line, a.commit, Path(a.state))
    else:
        try:
            plan = cmd_look(Path(a.state), a.write)
        except NoUv as e:
            die(str(e))
        print(json.dumps(plan, indent=1) if a.json else report(plan), end="")


if __name__ == "__main__":
    main()
