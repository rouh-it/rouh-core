"""CONTAINERS.md: the nightly copies of the database, the weekly encrypted copy off the machine,
and an existing Rouh brought into a fresh stack.

What is checked is what a person would lose: a saved login (a Cloudflare token sealed with
rouh/encryption.py, read back the way Rouh reads it, `cloudflare.cloudflare_token`) and a file of
the data directory. Each check puts them there, takes the copy, and gets them back from it.

- backup.daily: the backup part copies the database into the backups volume (rouh's alone), the
  core says when (server_health), and a copy puts a changed database back as it was.
- backup.offsite: the core sends the weekly copy to the stand-in for R2 (rouh/testing/fake_s3.py);
  what arrived is age's format and nothing readable, the real `age` opens it with the private key
  run.sh made (STACK_OFFSITE_KEY), and its database restores into a database of its own.
- import.existing: `manage.py export_rouh` in this stack, `linux_stack.import_bundle` into a second,
  fresh stack (this one's project and -import), which starts with the same owner, the same signed-in cookie, the
  saved login opening with the key that came with it, and the file there. It stops this stack to
  free its ports, so smoke.py runs it last.
"""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import smoke
from smoke import Failed, Stack, check, expect

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "deploy" / "container"))

BACKUP = "/opt/rouh-guard/bin/rouh-backup"
S3 = 9019
ZONE, TOKEN = "stack-test.example", "cf-stack-test-saved-login-0123456789"
FILE, TEXT = "/data/rouh/attachments/stack-test/kept.txt", "a file of the Rouh, to be found again"
#: A command in the core as rouh, with the encryption key the server has (the core's start hands it
#: only to the server; rouh-core-entrypoint).
AS_ROUH = "cd /code && export ROUH_ENCRYPTION_KEY=\"$(tr -d '\\r\\n' < /keys/encryption.key)\"; "


def _core(s: Stack, command: str, compose: list[str] | None = None, timeout: float = 600) -> str:
    args = [*(compose or s.compose), "exec", "-T", "--user", "10001", "core", "bash", "-c", AS_ROUH + command]
    r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if r.returncode:
        raise Failed(f"in the core, {command[:60]}... exited {r.returncode}: {(r.stderr.strip() + ' ' + r.stdout.strip())[-700:]}")
    return r.stdout


def _shell(code: str) -> str:
    """Python with Rouh's Django set up, as its own commands set it up (smoke.Stack.manage)."""
    return "python - <<'PY'\nfrom rouh.project import setup\nsetup()\n" + code.strip("\n") + "\nPY"


def _token(s: Stack, compose: list[str] | None = None) -> str:
    """What Rouh opens for the saved login now: "same", "other", or why it could not."""
    return _core(s, _shell(f"""
from rouh import cloudflare
try:
    print("same" if cloudflare.cloudflare_token({ZONE!r}) == {TOKEN!r} else "other")
except Exception as e:
    print("cannot", type(e).__name__)
"""), compose).strip().splitlines()[-1]


_MARKED: list = []


def _mark(s: Stack) -> None:
    """The saved login and the file, once."""
    if _MARKED:
        return
    got = _core(s, _shell(f"""
import time
from rouh.encryption import box
from rouh.models import CloudflareZone, User
org = str(User.objects.filter(is_active=True, is_guest=False).first().org_id)
CloudflareZone.objects.update_or_create(org_id=org, zone={ZONE!r}, defaults=dict(
    token_sealed=box().seal({TOKEN!r}), last4={TOKEN[-4:]!r}, saved_at=time.time(), source="settings",
    carried=True, made_at=time.time()))
print("sealed with the key from", box().key_source)
"""))
    expect("environment" in got, f"the saved login was not sealed with the stack's own key: {got[-300:]}")
    _core(s, f"mkdir -p {os.path.dirname(FILE)} && printf %s {shlex.quote(TEXT)} > {FILE}")
    expect(_token(s) == "same", "the saved login does not open in the stack it was saved in")
    _MARKED.append(True)


def _copy_now(s: Stack) -> str:
    r = s.run("backup", f"{BACKUP} now")
    expect(r.returncode == 0 and "copied the database into" in r.stdout, f"rouh-backup now: {(r.stdout + r.stderr)[-500:]}")
    return r.stdout.split("copied the database into ", 1)[1].split(",", 1)[0].strip()


def _wait_core(compose: list[str], limit: float = 900, settled: float = 45) -> None:
    """Until the core is healthy and has been up a while: a change put in place, or put back, starts
    the core's container again a moment after it still says healthy (guard.undo)."""
    import datetime as dt

    end = time.time() + limit
    while time.time() < end:
        box = subprocess.run([*compose, "ps", "-q", "core"], capture_output=True, text=True, timeout=60).stdout.strip()
        got = subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}} {{.State.Health.Status}}", box],
                             capture_output=True, text=True, timeout=60).stdout.split() if box else []
        if len(got) == 2 and got[1] == "healthy":
            started = dt.datetime.fromisoformat(got[0][:19]).replace(tzinfo=dt.timezone.utc).timestamp()
            if time.time() - started > settled:
                return
        time.sleep(5)
    raise Failed(f"the core did not come up healthy in {int(limit / 60)} minutes")


@check("backup.daily")
def backup_daily(s: Stack) -> None:
    _mark(s)
    name = _copy_now(s)
    # rouh's alone, and the core can read it but not change it.
    listed = s.run("core", "ls -ln /backups/daily; touch /backups/daily/x 2>&1 || true", user="10001").stdout
    row = next((line for line in listed.splitlines() if name in line), "")
    expect(row.startswith("-rw-------") and " 10001 10001 " in row, f"the copy is not rouh's alone: {row or listed[-300:]}")
    expect("Read-only file system" in listed, f"the core can write the copies: {listed[-300:]}")
    # Nothing in the backup part runs as root once it is started.
    procs = s.run("backup", "for p in /proc/[0-9]*; do n=${p#/proc/}; [ \"$n\" = 1 ] || [ \"$n\" = $$ ] && continue; "
                            "u=$(awk '/^Uid:/{print $2}' $p/status 2>/dev/null); [ -n \"$u\" ] && echo \"$n $u $(tr '\\0' ' ' < $p/cmdline | cut -c1-60)\"; done",
                  user="10001").stdout
    root = [line for line in procs.splitlines() if line.split(" ")[1:2] == ["0"]]
    expect(procs.strip() and not root, f"the backup part runs something as root: {root[:3] or procs[-300:]}")
    # Rouh says when the newest was made.
    said = s.tool("server_health", {})
    expect("nightly copy of the database was made" in said and "kept" in said, f"server_health on the copies: {said[-600:]}")

    # A copy puts the database back as it was: the saved login changed, then the copy restored.
    _core(s, _shell(f"from rouh.models import CloudflareZone; from rouh.encryption import box; "
                    f"CloudflareZone.objects.filter(zone={ZONE!r}).update(token_sealed=box().seal('changed since'))"))
    expect(_token(s) == "other", "the saved login did not change")
    refused = s.run("backup", f"{BACKUP} restore {name}")
    expect(refused.returncode != 0 and "Stop the core first" in refused.stderr,
           f"a restore under a running Rouh was not refused: {(refused.stdout + refused.stderr)[-300:]}")
    subprocess.run([*s.compose, "stop", "core"], capture_output=True, timeout=300)
    try:
        put = s.run("backup", f"{BACKUP} restore {name}", timeout=600)
    finally:
        subprocess.run([*s.compose, "start", "core"], capture_output=True, timeout=300)
        s.ws = None
    expect(put.returncode == 0 and "is as it was in" in put.stdout, f"rouh-backup restore: {(put.stdout + put.stderr)[-500:]}")
    _wait_core(s.compose)
    expect(_token(s) == "same", "the database restored from the copy does not hold the saved login as it was")


@check("backup.offsite")
def backup_offsite(s: Stack) -> None:
    _mark(s)
    # Not set up, it says so and sends nothing.
    off = _core(s, "env -u ROUH_OFFSITE_ENDPOINT -u ROUH_OFFSITE_BUCKET -u ROUH_OFFSITE_KEY_ID -u ROUH_OFFSITE_SECRET "
                   "python manage.py offsite_backup run")
    expect("Nothing done: no off-site copy is set up" in off, f"offsite_backup run with nothing set up: {off[-300:]}")
    _copy_now(s)
    # As a person runs it, beside the server: the key is found in the keys volume.
    sent = _core(s, "env -u ROUH_ENCRYPTION_KEY python manage.py offsite_backup run")
    expect(f"Sent rouh-backups/{_project(s)}/" in sent, f"offsite_backup run: {sent[-500:]}")
    seen = s.standin(S3, "/_objects")
    objs = [o for o in seen.get("objects", []) if o["key"].endswith(".bundle.age")]
    expect(objs and seen.get("keys_seen") == ["stack-test-key-id"], f"what reached the stand-in for R2: {json.dumps(seen)[:500]}")
    said = s.tool("server_health", {})
    expect("newest off-site copy was sent" in said, f"server_health on the off-site copy: {said[-600:]}")

    key = os.environ.get("STACK_OFFSITE_KEY", "")
    expect(key and os.path.isfile(key) and shutil.which("age"),
           "the real age and the key run.sh made with it are needed to open the copy (STACK_OFFSITE_KEY)")
    with tempfile.TemporaryDirectory() as tmp:
        _core(s, "rm -f /tmp/offsite.age && python manage.py offsite_backup fetch --to /tmp/offsite.age")
        subprocess.run([*s.compose, "cp", "core:/tmp/offsite.age", f"{tmp}/copy.age"], check=True, capture_output=True, timeout=300)
        s.run("core", "rm -f /tmp/offsite.age", user="10001")
        raw = Path(f"{tmp}/copy.age").read_bytes()
        expect(raw.startswith(b"age-encryption.org/v1\n-> X25519 "), f"the copy is not age's format: {raw[:60]!r}")
        for plain in (b"rouh-bundle", TEXT.encode(), b"bundle.json", b"PGDMP"):
            expect(plain not in raw, f"the copy in the bucket has {plain!r} readable in it")
        opened = subprocess.run(["age", "-d", "-i", key, "-o", f"{tmp}/bundle.tar", f"{tmp}/copy.age"],
                                capture_output=True, text=True, timeout=300)
        expect(opened.returncode == 0, f"the real age could not open the copy: {opened.stderr[-300:]}")
        from rouh import bundle

        about = bundle.read_about(f"{tmp}/bundle.tar")
        bundle.check_dump(f"{tmp}/bundle.tar", about)
        expect(about.get("encryption_key") and about.get("django_key"), f"the copy does not hold the keys: {about}")
        with tarfile.open(f"{tmp}/bundle.tar") as t:
            got = t.extractfile(f"{bundle.DATA}/{FILE.removeprefix('/data/rouh/')}").read().decode()
            expect(got == TEXT, f"the copy's file is not the one saved: {got[:100]!r}")
            mine = hashlib.sha256(t.extractfile(bundle.ENCRYPTION_KEY).read().strip()).hexdigest()
            t.extract(bundle.DUMP, tmp, filter="data")
        theirs = s.run("core", "tr -d '\\r\\n' < /keys/encryption.key | sha256sum", user="10001").stdout.split()[0]
        expect(mine == theirs, "the copy's encryption key is not this Rouh's")
        # And its database restores, into a database of its own beside Rouh's.
        subprocess.run([*s.compose, "cp", f"{tmp}/{bundle.DUMP}", "postgres:/tmp/offsite.dump"], check=True,
                       capture_output=True, timeout=300)
    r = s.run("postgres", "set -e; dropdb -U rouh --if-exists offsitecheck; createdb -U rouh offsitecheck; "
                          "pg_restore -U rouh -d offsitecheck --no-owner --no-privileges --exit-on-error /tmp/offsite.dump; "
                          f"psql -U rouh -d offsitecheck -Atc \"select count(*) from cloudflare_zones where zone = '{ZONE}'\"; "
                          "dropdb -U rouh offsitecheck; rm -f /tmp/offsite.dump", timeout=600)
    expect(r.returncode == 0 and r.stdout.strip().splitlines()[-1:] == ["1"],
           f"the copy's database did not restore: {(r.stdout + r.stderr)[-500:]}")


def _project(s: Stack) -> str:
    """This stack's Compose project, run.sh's -p."""
    return s.compose[s.compose.index("-p") + 1]


def _second(s: Stack) -> tuple[list[str], str]:
    """The Compose command of the second stack, the one a Rouh is brought into, and its name."""
    c = list(s.compose)
    name = _project(s) + "-import"
    c[c.index("-p") + 1] = name
    return c, name


def _release_env(s: Stack) -> dict:
    out: dict = {}
    for i, a in enumerate(s.compose):
        if a == "--env-file" and Path(s.compose[i + 1]).is_file():
            for line in Path(s.compose[i + 1]).read_text().splitlines():
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    out.setdefault(k.strip(), v.strip())
    return out


# A restore starts Rouh again, and bringing it into a second stack stops this one.
smoke.LAST.add("backup.daily")
smoke.FINAL.add("import.existing")
smoke.LIMIT.update({"backup.daily": 900, "backup.offsite": 600, "import.existing": 2400})


@check("import.existing")
def import_existing(s: Stack) -> None:
    import linux_stack

    # The check before may have put other code in place (guard.undo), and the core be starting
    # again: it does within a second of the change, so after a pause its container is the new one.
    time.sleep(15)
    _wait_core(s.compose)
    _mark(s)
    _copy_now(s)
    # The export, in this stack's core, never saying a key.
    said = _core(s, "rm -f /data/export.bundle; out=$(env -u ROUH_ENCRYPTION_KEY python manage.py export_rouh --out /data/export.bundle --dump newest 2>&1); "
                    "k=$(tr -d '\\r\\n' < /keys/encryption.key); case \"$out\" in *\"$k\"*) echo LEAKED;; esac; "
                    "echo \"$out\"; stat -c '%a %u' /data/export.bundle")
    expect("LEAKED" not in said and "Made /data/export.bundle" in said and said.strip().endswith("600 10001"),
           f"export_rouh: {said[-500:]}")
    django = s.run("core", "sha256sum < /data/rouh/django-secret.key", user="10001").stdout.split()[0]
    base = _release_env(s).get("ROUH_BASE_IMAGE", "")
    expect(base, "the stack test's release.env names no base image")
    second, SECOND = _second(s)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "rouh.bundle"
        subprocess.run([*s.compose, "cp", "core:/data/export.bundle", str(path)], check=True, capture_output=True, timeout=600)
        s.run("core", "rm -f /data/export.bundle", user="10001")
        # This stack stops, so the second can have its ports; its code and libraries are copied into
        # the second's volumes, as run.sh made them, since a code install would ask rouh.land.
        subprocess.run([*s.compose, "stop"], capture_output=True, timeout=600)
        try:
            for vol in ("code", "extra"):
                subprocess.run(["docker", "volume", "create", "--label", f"com.docker.compose.project={SECOND}",
                                "--label", f"com.docker.compose.volume={vol}", f"{SECOND}_{vol}"], check=True,
                               capture_output=True, timeout=60)
                subprocess.run(["docker", "run", "--rm", "--network", "none", "--user", "0:0",
                                "-v", f"{_project(s)}_{vol}:/from:ro", "-v", f"{SECOND}_{vol}:/to",
                                "--entrypoint", "sh", base, "-c", "cp -a /from/. /to/"], check=True, capture_output=True,
                               timeout=900)
            try:
                linux_stack.import_bundle(path, second, SECOND, base)
            except linux_stack.Stop as e:
                raise Failed(f"linux_stack.import_bundle: {e}") from None
            path.unlink()
            up = subprocess.run([*second, "up", "--detach"], capture_output=True, text=True, timeout=1800)
            expect(up.returncode == 0, f"the second stack did not start: {up.stderr[-500:]}")
            _wait_core(second)
            opened = _token(s, second)
            expect(opened == "same", f"the saved login does not open in the stack it was brought into ({opened})")
            got = _core(s, f"cat {FILE}; echo; stat -c '%a %u' /keys/encryption.key; sha256sum < /data/rouh/django-secret.key",
                        second).splitlines()
            expect(got[:1] == [TEXT], f"the file did not come with it: {got[:1]}")
            expect(got[1:2] == ["400 10001"], f"the encryption key is not as the core's start gives it: {got[1:2]}")
            expect(got[2:3] and got[2].split()[0] == django, "the Django key did not come with it")
            logs = subprocess.run([*second, "logs", "--no-color", "core"], capture_output=True, text=True, timeout=120).stdout
            (s.out / "import-stack.log").write_text(logs)
            expect("has no owner yet" not in logs, "the second stack asked for an owner: the database did not come with it")
            code, _, headers = s.get("/", follow=False)
            expect(code == 200, f"the signed-in cookie from the first stack is refused: {code} {headers.get('Location', '')}")
        finally:
            subprocess.run([*second, "down", "-v", "--remove-orphans"], capture_output=True, timeout=600)


@check("jobs.watched")
def jobs_watched(s: Stack) -> None:
    """Each scheduled job checked against what it left behind (rouh/job_watch.py), and the nightly Synapse
    run written down as failed with its reason in the containers rather than started for nothing."""
    got = json.loads(_core(s, "python manage.py job_watch --json"))
    expect(isinstance(got.get("jobs"), list) and got.get("human"), f"job_watch --json: {str(got)[:400]}")
    ids = {j.get("job") for j in got["jobs"]}
    expect("backup.nightly" in ids, f"the nightly copy is not among the checked jobs: {sorted(ids)}")
    said = s.manage("from rouh.synapse.lab import nightly\nprint(nightly.cannot_measure()[:60])")
    expect("was not started" in said, f"in the containers the Synapse night is not held back with its reason: {said[-300:]}")
    health = s.manage("import json\nfrom rouh import tools\nprint(json.dumps(tools.server_health().get('scheduled_jobs')))")
    expect('"human"' in health, f"server_health has no scheduled_jobs section: {health[-300:]}")
