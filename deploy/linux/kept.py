"""Keep my data, Wipe my data and Bring back your Rouh, for ``rouh uninstall`` on Linux (task 176, step
176-25), the way Rouh for Mac 0.3.23 does them (KeptData.swift, step 176-17).

Keep my data saves a copy and checks it before anything is removed:

1. Rouh stopped, and its database alone started;
2. ``pg_dump -Fc``, restored once into the throwaway database ``rouh_keep_check``, its tables counted;
3. the volumes that make the same Rouh come back as itself (``VOLUMES``), each a tar with owners and
   modes, read back, with ``git fsck --full`` on the code and the workspace, in a container of the
   release's base with no network and the volumes read-only;
4. all of it into ``~/rouh-kept/<stamp>/`` (0700, files 0600: it holds Rouh's keys), with the
   settings file and the release in use, every file's SHA-256 compared after the copy, and a
   ``manifest.json``.

Nothing is removed unless the whole copy checks out. Bring back checks every checksum again, makes
each volume with Compose's own labels, unpacks it (fsck again), starts the database alone and
restores the dump into it, counting its tables, all before Rouh's stack first starts.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path

from common import PROJECT, Stop, compose, debug, kept_dir, release_env, rouh_dir, run, say, settings_file

VOLUMES = ["workspace", "code", "extra", "keys", "core-data", "guard-state", "worker-home"]
NAMES = {"workspace": "your workspace", "code": "Rouh's own code", "extra": "the libraries Rouh added",
         "keys": "the keys it seals your logins with", "core-data": "its identity and data folder",
         "guard-state": "its undo points", "worker-home": "its agents' sign-ins"}
CHECK_DB = "rouh_keep_check"
COUNT = "select count(*) from pg_tables where schemaname not in ('pg_catalog','information_schema')"
DUMP_INSIDE = "/tmp/rouh-keep.dump"

SAVE = r"""
set -e
mkdir -p /out /check
for n in $NAMES; do tar -C "/v/$n" --numeric-owner -cpf "/out/$n.tar" . ; done
for n in $NAMES; do tar -tf "/out/$n.tar" >/dev/null || { echo "TAR-FAILED $n"; exit 3; }; done
for n in code workspace; do
  [ -f "/out/$n.tar" ] || continue
  mkdir -p "/check/$n" && tar -C "/check/$n" -xpf "/out/$n.tar"
  found=0
  for d in "/check/$n" "/check/$n"/*.git "/check/$n/.git"; do
    if [ -f "$d/HEAD" ] && [ -d "$d/objects" ]; then
      found=1
      git -c safe.directory='*' --git-dir="$d" fsck --full --no-progress >/dev/null 2>&1 || { echo "FSCK-FAILED $n"; exit 4; }
    fi
  done
  [ $found = 1 ] && echo "FSCK-OK $n" || echo "FSCK-NONE $n"
  rm -rf "/check/$n"
done
cd /out && sha256sum *.tar | sed 's/^/SUM /'
echo SAVED
"""

RESTORE = r"""
set -e
for n in $NAMES; do tar -C "/v/$n" --numeric-owner -xpf "/in/$n.tar"; done
for n in code workspace; do
  for d in "/v/$n" "/v/$n"/*.git "/v/$n/.git"; do
    if [ -f "$d/HEAD" ] && [ -d "$d/objects" ]; then
      git -c safe.directory='*' --git-dir="$d" fsck --full --no-progress >/dev/null 2>&1 || { echo "FSCK-FAILED $n"; exit 4; }
      echo "FSCK-OK $n"
    fi
  done
done
echo RESTORED
"""


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _size(n: int) -> str:
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


def _base() -> str:
    for line in release_env().read_text().splitlines():
        if line.startswith("ROUH_BASE_IMAGE="):
            return line.split("=", 1)[1].strip()
    raise Stop("No release of Rouh's images is named here (stack/release.env).")


def _volumes_present() -> list[str]:
    r = run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"], timeout=60)
    there = set((r.stdout or b"").decode().split())
    return [n for n in VOLUMES if f"{PROJECT}_{n}" in there]


def _db_ready(timeout: float = 120) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if run(compose("exec", "-T", "postgres", "pg_isready", "-U", "rouh", "-d", "rouh"), timeout=30).returncode == 0:
            return
        time.sleep(3)
    raise Stop("Rouh's database did not answer.")


def _last_number(text: bytes) -> int | None:
    for line in reversed(text.decode(errors="replace").splitlines()):
        if line.strip().isdigit():
            return int(line.strip())
    return None


def save(progress=say) -> Path:
    """Keep my data: the checked copy, or Stop with why (and Rouh started again by the caller)."""
    base = _base()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = kept_dir() / stamp
    tmp = kept_dir() / f".saving-{stamp}"
    kept_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(kept_dir(), 0o700)
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "volumes").mkdir(parents=True, mode=0o700)
    os.chmod(tmp, 0o700)
    box = f"{PROJECT}-keep"
    try:
        progress("Stopping Rouh, and starting its database alone")
        run(compose("stop"), timeout=600, check=True)
        run(compose("up", "--detach", "--no-deps", "postgres"), timeout=600, check=True)
        _db_ready()
        progress("Saving the database, and checking it by restoring it once into a test database")
        source = run(compose("exec", "-T", "postgres", "psql", "-U", "rouh", "-d", "rouh", "-tAc", COUNT), timeout=120, check=True)
        tables = _last_number(source.stdout)
        run(compose("exec", "-T", "postgres", "pg_dump", "-U", "rouh", "-d", "rouh", "-Fc", "-f", DUMP_INSIDE), timeout=7200, check=True)
        script = (f"set -e; dropdb -U rouh --if-exists {CHECK_DB}; createdb -U rouh {CHECK_DB}; "
                  f"pg_restore -U rouh -d {CHECK_DB} --exit-on-error --single-transaction {DUMP_INSIDE}; "
                  f'psql -U rouh -d {CHECK_DB} -tAc "{COUNT}"; dropdb -U rouh {CHECK_DB}')
        checked = run(compose("exec", "-T", "postgres", "sh", "-c", script), timeout=7200, check=True)
        if tables is None or _last_number(checked.stdout) != tables:
            raise Stop(f"the database copy came back with {_last_number(checked.stdout)} tables of {tables}")
        run(compose("cp", f"postgres:{DUMP_INSIDE}", str(tmp / "database.dump")), timeout=7200, check=True)
        run(compose("exec", "-T", "postgres", "rm", "-f", DUMP_INSIDE), timeout=60)
        os.chmod(tmp / "database.dump", 0o600)
        progress(f"The database: {tables} tables, checked")

        names = _volumes_present()
        progress("Saving and checking " + ", ".join(NAMES[n] for n in names))
        run(["docker", "rm", "--force", box], timeout=60)
        args = ["docker", "create", "--name", box, "--network", "none", "--user", "0:0", "-e", f"NAMES={' '.join(names)}",
                "--entrypoint", "sh"]
        for n in names:
            args += ["--volume", f"{PROJECT}_{n}:/v/{n}:ro"]
        run(args + [base, "-c", SAVE], timeout=120, check=True)
        ran = run(["docker", "start", "--attach", box], timeout=7200)
        out = (ran.stdout or b"").decode(errors="replace") + (ran.stderr or b"").decode(errors="replace")
        if ran.returncode or "SAVED" not in out:
            bad = next((line for line in out.splitlines() if "FAILED" in line), out.strip()[-300:])
            raise Stop(f"a saved volume did not check out ({bad})")
        sums = {p[2][:-4]: p[1] for p in (line.split() for line in out.splitlines()) if len(p) == 3 and p[0] == "SUM"}
        fsck = [line.split()[1] for line in out.splitlines() if line.startswith("FSCK-OK ")]
        run(["docker", "cp", f"{box}:/out/.", str(tmp / "volumes")], timeout=7200, check=True)
        items = []
        for n in names:
            f = tmp / "volumes" / f"{n}.tar"
            os.chmod(f, 0o600)
            got = _sha(f)
            if sums.get(n) != got:
                raise Stop(f"{n}.tar changed on its way out of Docker")
            items.append({"name": n, "file": f"volumes/{n}.tar", "bytes": f.stat().st_size, "sha256": got})
        for f in (settings_file(), rouh_dir() / "releases" / "current.json"):
            if f.is_file():
                shutil.copy2(f, tmp / ("settings.env" if f.name == ".env" else "release.json"))
                os.chmod(tmp / ("settings.env" if f.name == ".env" else "release.json"), 0o600)
        db = tmp / "database.dump"
        manifest = {"format": 1, "made": stamp, "made_at": int(time.time()), "tables": tables,
                    "database": {"name": "database", "file": "database.dump", "bytes": db.stat().st_size, "sha256": _sha(db)},
                    "volumes": items, "checked": [f"database restored into a test database: {tables} tables"]
                    + [f"git fsck: {n}" for n in fsck], "restored_at": None}
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        os.chmod(tmp / "manifest.json", 0o600)
        tmp.rename(folder)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    finally:
        run(["docker", "rm", "--force", box], timeout=60)
    total = manifest["database"]["bytes"] + sum(i["bytes"] for i in items)
    progress(f"Kept, and checked: {folder} ({_size(total)})")
    return folder


def copies() -> list[Path]:
    """Every whole kept copy, newest first; a folder with no manifest is a save that never finished."""
    if not kept_dir().is_dir():
        return []
    return sorted((p for p in kept_dir().iterdir() if p.is_dir() and (p / "manifest.json").is_file()), reverse=True)


def waiting() -> Path | None:
    """The newest kept copy not brought back yet."""
    for p in copies():
        try:
            if json.loads((p / "manifest.json").read_text()).get("restored_at") is None:
                return p
        except ValueError:
            continue
    return None


def problem(folder: Path) -> str:
    m = json.loads((folder / "manifest.json").read_text())
    for item in [m["database"]] + m["volumes"]:
        f = folder / item["file"]
        if not f.is_file():
            return f"{item['file']} is missing from the kept copy"
        if _sha(f) != item["sha256"]:
            return f"{item['file']} in the kept copy has changed since it was saved"
    return ""


def bring_back(folder: Path, progress=say) -> int:
    """Puts a kept copy into this machine's volumes, before Rouh's stack first starts here. The
    release's images must be pulled already, and stack.json written (linux_stack.py does both)."""
    progress("Checking the kept copy")
    bad = problem(folder)
    if bad:
        raise Stop(bad)
    m = json.loads((folder / "manifest.json").read_text())
    names = [v["name"] for v in m["volumes"]]
    there = set(_volumes_present()) | ({"pgdata"} if not run(["docker", "volume", "inspect", f"{PROJECT}_pgdata"], timeout=30).returncode else set())
    if there:
        raise Stop("this machine has a Rouh's volumes already (" + ", ".join(sorted(there)) + "); a kept Rouh is brought "
                   "back only before a fresh start. Remove this one first: rouh uninstall")
    base = _base()
    progress(f"Putting back {', '.join(NAMES.get(n, n) for n in names)}")
    for n in names:
        run(["docker", "volume", "create", "--label", f"com.docker.compose.project={PROJECT}",
             "--label", f"com.docker.compose.volume={n}", f"{PROJECT}_{n}"], timeout=60, check=True)
    box = f"{PROJECT}-bring-back"
    run(["docker", "rm", "--force", box], timeout=60)
    args = ["docker", "create", "--name", box, "--network", "none", "--user", "0:0", "-e", f"NAMES={' '.join(names)}",
            "--entrypoint", "sh"]
    for n in names:
        args += ["--volume", f"{PROJECT}_{n}:/v/{n}"]
    try:
        run(args + [base, "-c", RESTORE], timeout=120, check=True)
        run(["docker", "cp", f"{folder / 'volumes'}/.", f"{box}:/in"], timeout=7200, check=True)
        ran = run(["docker", "start", "--attach", box], timeout=7200)
        out = (ran.stdout or b"").decode(errors="replace")
        if ran.returncode or "RESTORED" not in out:
            raise Stop(f"the kept volumes could not be put back ({out.strip()[-300:]})")
    finally:
        run(["docker", "rm", "--force", box], timeout=120)
    progress("Putting back Rouh's database")
    run(compose("up", "--detach", "--no-deps", "postgres"), timeout=600, check=True)
    _db_ready()
    run(compose("cp", str(folder / "database.dump"), f"postgres:{DUMP_INSIDE}"), timeout=7200, check=True)
    got = run(compose("exec", "-T", "postgres", "sh", "-c",
                      f'set -e; pg_restore -U rouh -d rouh --exit-on-error --single-transaction {DUMP_INSIDE}; '
                      f'rm -f {DUMP_INSIDE}; psql -U rouh -d rouh -tAc "{COUNT}"'), timeout=7200)
    tables = _last_number(got.stdout or b"")
    if got.returncode or tables != m["tables"]:
        raise Stop(f"the database could not be restored ({(got.stderr or b'').decode(errors='replace').strip()[-300:]})"
                   if got.returncode else f"the database came back with {tables} tables of {m['tables']}")
    run(compose("stop", "postgres"), timeout=300)
    m["restored_at"] = int(time.time())
    (folder / "manifest.json").write_text(json.dumps(m, indent=1) + "\n")
    progress(f"Your Rouh is back: {len(names)} volumes and the database ({tables} tables), from {folder}")
    debug(json.dumps(m["checked"]))
    return tables


def settings_of(folder: Path) -> Path | None:
    f = folder / "settings.env"
    return f if f.is_file() else None


def fingerprint() -> dict:
    """What is in Rouh's volumes and database now, to compare before and after (for the proof):
    each volume's file list with sizes and modes, hashed, and the database's row counts per table."""
    base = _base()
    names = _volumes_present()
    out: dict = {}
    for n in names:
        r = run(["docker", "run", "--rm", "--network", "none", "--user", "0:0", "-v", f"{PROJECT}_{n}:/v:ro", "--entrypoint", "sh",
                 base, "-c", "cd /v && find . -printf '%p %s %m %U %G\\n' | LC_ALL=C sort | sha256sum"], timeout=600)
        out[n] = (r.stdout or b"").decode().split()[0] if r.returncode == 0 else "unreadable"
    q = ("select format('%s.%s', schemaname, tablename) || '=' || (xpath('/row/c/text()', query_to_xml("
         "format('select count(*) as c from %I.%I', schemaname, tablename), false, true, '')))[1]::text "
         "from pg_tables where schemaname not in ('pg_catalog','information_schema') order by 1")
    r = run(compose("exec", "-T", "postgres", "psql", "-U", "rouh", "-d", "rouh", "-tAc", q), timeout=600)
    rows = (r.stdout or b"").decode().split()
    out["database_rows"] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    out["database_tables"] = len(rows)
    return out
