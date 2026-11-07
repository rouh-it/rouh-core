"""Rouh's weekly copy off this machine, to Cloudflare R2.

Petar, 5 October 2026: "You have r2, setup weekly backups". The daily dumps
(`pg_dump@18-main`, 03:40, seven kept in /var/backups/postgresql/18-main) are on
the same disk as the database: they mend a bad migration, not a lost machine.
So once a week the newest of them goes to R2, with Rouh's data folder:

- **What.** The newest whole-cluster dump folder (Rouh's database, any other
  database on the cluster, the roles), and /var/www/rouh/data without `workspace-saves` (a git
  checkout of main, which GitHub has) and the SQLite files left from before
  PostgreSQL. Not /var/www/rouh/.env: its keys are re-entered from their
  providers, and nothing here reads it.
- **Encrypted before it leaves.** One tar, encrypted with gpg (AES-256) under the
  passphrase in /etc/rouh/backup-passphrase (root, 600). The bucket is whichever
  the key file names, and may be shared with something that is public one day,
  so nothing readable is ever put there. A copy of the passphrase must be kept
  off this machine too, or a lost machine takes the only key with it.
- **Checked.** The object's size and SHA-256 are compared with the file sent, and
  `check` downloads the newest, decrypts it and reads every dump's table of
  contents back with pg_restore.
- **Kept.** The newest `KEEP` copies under `rouh-backups/<host>/`; older ones there
  are deleted. Nothing outside that prefix is listed, read or deleted.

The R2 endpoint, bucket and key are in /etc/rouh/r2-backup.json (root, 600),
written by whoever installs the backup on a machine. Every path below can be
changed with an environment variable of the same name prefixed `ROUH_BACKUP_`
(`ROUH_BACKUP_KEYS`, `ROUH_BACKUP_PASSPHRASE`, `ROUH_BACKUP_DUMPS`,
`ROUH_BACKUP_WORK`), and the data folder with `ROUH_DATA_DIR`, for a machine laid
out differently; the defaults are the layout `deploy/rouh.sh` makes.

    python deploy/backup_offsite.py run      # what the weekly timer runs
    python deploy/backup_offsite.py list     # what is in R2
    python deploy/backup_offsite.py check    # the newest, downloaded and read back

Run as root (`deploy/install_offsite_backup.sh` installs the timer). Restoring by
hand: download the object, `gpg --decrypt --passphrase-file
/etc/rouh/backup-passphrase file.tar.gpg | tar -x`, then `pg_restore` the dumps.
"""
from __future__ import annotations

import datetime as dt
import glob
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

KEYS = os.environ.get("ROUH_BACKUP_KEYS") or "/etc/rouh/r2-backup.json"
PASSPHRASE = os.environ.get("ROUH_BACKUP_PASSPHRASE") or "/etc/rouh/backup-passphrase"
DUMPS = os.environ.get("ROUH_BACKUP_DUMPS") or "/var/backups/postgresql/18-main"
DATA = os.environ.get("ROUH_DATA_DIR") or "/var/www/rouh/data"
#: Left out of the data folder: a git checkout of main, and SQLite from before PostgreSQL.
SKIP = ("workspace-saves", "rouh.sqlite3*")
WORK = os.environ.get("ROUH_BACKUP_WORK") or "/var/backups/rouh-offsite"
STATUS = os.path.join(WORK, "last.json")
KEEP = 8
#: A dump older than this is not last night's: a fresh one is taken first.
FRESH_HOURS = 30


def say(text: str) -> None:
    print(text, flush=True)


def client():
    import boto3

    with open(KEYS) as f:
        c = json.load(f)
    s3 = boto3.client("s3", endpoint_url=c["endpoint"], aws_access_key_id=c["access_key_id"],
                      aws_secret_access_key=c["secret_access_key"], region_name="auto")
    return s3, c.get("bucket") or c["library_bucket"]


def prefix() -> str:
    return f"rouh-backups/{socket.gethostname()}/"


def newest_dump() -> str:
    found = sorted(d for d in glob.glob(os.path.join(DUMPS, "*.dump")) if os.path.isdir(d))
    return found[-1] if found else ""


def fresh_dump() -> str:
    """Last night's dump folder, or a new one when there is none that recent."""
    got = newest_dump()
    if got and time.time() - os.path.getmtime(got) < FRESH_HOURS * 3600:
        return got
    say("no dump from the last day, taking one now")
    subprocess.run(["systemctl", "start", "--wait", "pg_dump@18-main.service"], check=True, timeout=3600)
    got = newest_dump()
    if not got or time.time() - os.path.getmtime(got) > 3600:
        raise RuntimeError("pg_dump@18-main ran but left no new dump folder")
    return got


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run() -> dict:
    os.makedirs(WORK, mode=0o700, exist_ok=True)
    dump = fresh_dump()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = os.path.join(WORK, f"{stamp}.tar.gpg")
    excludes = [f"--exclude=./{p}" for p in SKIP]
    say(f"packing {dump} and {DATA}")
    tar = subprocess.Popen(["tar", "-cf", "-", "-C", os.path.dirname(dump), os.path.basename(dump),
                            "-C", DATA, *excludes, "--transform", "s,^\\.,rouh-data,", "."],
                           stdout=subprocess.PIPE)
    gpg = subprocess.run(["gpg", "--batch", "--yes", "--quiet", "--pinentry-mode", "loopback",
                          "--passphrase-file", PASSPHRASE, "--symmetric", "--cipher-algo", "AES256",
                          "--compress-algo", "none", "-o", out], stdin=tar.stdout)
    tar.stdout.close()
    if tar.wait() not in (0, 1) or gpg.returncode != 0:  # tar 1: a file changed while it was read
        raise RuntimeError(f"packing failed: tar {tar.returncode}, gpg {gpg.returncode}")
    size, digest = os.path.getsize(out), sha256(out)
    s3, bucket = client()
    key = prefix() + os.path.basename(out)
    say(f"uploading {size / 1e6:.0f} MB to {bucket}/{key}")
    s3.upload_file(out, bucket, key, ExtraArgs={"Metadata": {"sha256": digest, "dump": os.path.basename(dump)}})
    head = s3.head_object(Bucket=bucket, Key=key)
    if head["ContentLength"] != size or head.get("Metadata", {}).get("sha256") != digest:
        raise RuntimeError(f"R2 holds {head['ContentLength']} bytes of {size}; not trusting it")
    os.remove(out)
    gone = prune(s3, bucket)
    result = {"ok": True, "at": stamp, "key": key, "bytes": size, "sha256": digest,
              "dump": os.path.basename(dump), "deleted_old": gone}
    write_status(result)
    say(f"kept in R2: {key}, {size / 1e6:.0f} MB; {len(gone)} older one(s) deleted")
    return result


def objects(s3, bucket) -> list[dict]:
    got, token = [], None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefix()}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        got += [o for o in page.get("Contents", []) if o["Key"].endswith(".tar.gpg")]
        if not page.get("IsTruncated"):
            return sorted(got, key=lambda o: o["Key"])
        token = page["NextContinuationToken"]


def prune(s3, bucket) -> list[str]:
    old = objects(s3, bucket)[:-KEEP]
    for o in old:
        s3.delete_object(Bucket=bucket, Key=o["Key"])
    return [o["Key"] for o in old]


def check() -> dict:
    """The newest copy, downloaded, decrypted and read back: every dump's table of contents."""
    s3, bucket = client()
    found = objects(s3, bucket)
    if not found:
        raise RuntimeError("there is no copy in R2 yet")
    key = found[-1]["Key"]
    with tempfile.TemporaryDirectory(dir=WORK) as tmp:
        enc = os.path.join(tmp, "copy.tar.gpg")
        s3.download_file(bucket, key, enc)
        want = s3.head_object(Bucket=bucket, Key=key).get("Metadata", {}).get("sha256")
        if sha256(enc) != want:
            raise RuntimeError("the downloaded copy does not match the SHA-256 it was sent with")
        dec = subprocess.Popen(["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase-file",
                                PASSPHRASE, "--decrypt", enc], stdout=subprocess.PIPE)
        subprocess.run(["tar", "-xf", "-", "-C", tmp], stdin=dec.stdout, check=True)
        dec.stdout.close()
        if dec.wait() != 0:
            raise RuntimeError("gpg could not decrypt it")
        dumps = {}
        for path in sorted(glob.glob(os.path.join(tmp, "*.dump", "*.dump"))):
            toc = subprocess.run(["pg_restore", "--list", path], capture_output=True, text=True)
            if toc.returncode != 0:
                raise RuntimeError(f"pg_restore cannot read {os.path.basename(path)}: {toc.stderr[:300]}")
            dumps[os.path.basename(path)] = sum(1 for line in toc.stdout.splitlines() if " TABLE DATA " in line)
        files = sum(len(f) for _, _, f in os.walk(os.path.join(tmp, "rouh-data")))
    if "rouh.dump" not in dumps:
        raise RuntimeError("the copy has no rouh.dump in it")
    result = {"ok": True, "key": key, "tables_with_data": dumps, "data_files": files}
    say(json.dumps(result))
    return result


def write_status(result: dict) -> None:
    os.makedirs(WORK, mode=0o700, exist_ok=True)
    with open(STATUS, "w") as f:
        json.dump(result, f)


def main() -> None:
    action = (sys.argv[1:] or ["run"])[0]
    try:
        if action == "run":
            run()
        elif action == "check":
            check()
        elif action == "list":
            s3, bucket = client()
            for o in objects(s3, bucket):
                say(f"{o['Key']}  {o['Size'] / 1e6:.0f} MB  {o['LastModified']:%Y-%m-%d %H:%M}")
        else:
            raise SystemExit(f"run, list or check, not {action}")
    except Exception as exc:
        if action == "run":
            write_status({"ok": False, "at": dt.datetime.now(dt.timezone.utc).isoformat(), "error": str(exc)[:500]})
        say(f"failed: {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
