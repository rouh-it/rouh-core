"""The weekly copy of a Rouh off its machine, encrypted, to Cloudflare R2 or any S3, and the
nightly copies it is made from.

Petar, 29 October 2026: the containers carry everything his own Rouh on a server does. The server
has a nightly pg_dump and a weekly encrypted copy to R2 (deploy/backup_offsite.py, systemd and the
host's PostgreSQL); a stack has neither, so:

- **Every night** the stack's backup part (guard/bin/rouh-backup, on PostgreSQL's own image, so its
  pg_dump is the server's own version) copies the database into the backups volume, which the core
  reads at ROUH_BACKUP_DIR. `nightly` says what is there.
- **Every week** the core (this file) takes the newest of those, makes one bundle of the Rouh with
  it (`rouh/bundle.py`: the database, both keys, the data directory, the workspace), encrypts it in
  age's format (`rouh/agefile.py`) for the public key or the passphrase in the settings file, and
  sends it to the bucket. The size and SHA-256 of what arrived are compared with what was sent; the
  newest `KEEP` are kept and older ones under the same prefix deleted. Nothing outside the prefix is
  listed, read or deleted, and nothing readable ever reaches the bucket.

The core does it because the core is what holds what goes in: the keys, the data and the way out.
No other part gains a key or a way out, and no AI key is near it.

Set up in the settings file (deploy/stack/settings.env.example, "Backups"):

    ROUH_OFFSITE_ENDPOINT, ROUH_OFFSITE_BUCKET, ROUH_OFFSITE_KEY_ID, ROUH_OFFSITE_SECRET
    ROUH_OFFSITE_RECIPIENT  an age public key, age1... (its private half kept off this machine), or
    ROUH_OFFSITE_PASSPHRASE a long passphrase, a copy of it kept off this machine

Without them nothing is sent, and that is said plainly. To restore: download the newest
(`python manage.py offsite_backup fetch`), open it with the private key or the passphrase (the
stock `age -d`, or `python -m rouh.agefile decrypt`), and import the bundle into a fresh stack
(`linux_stack.py import`).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import socket
import threading
import time

log = logging.getLogger("rouh.offsite")

#: Copies kept in the bucket, as on the server (deploy/backup_offsite.py).
KEEP = int(os.environ.get("ROUH_OFFSITE_KEEP") or 8)
#: How often a copy goes out, in days.
EVERY_DAYS = float(os.environ.get("ROUH_OFFSITE_EVERY_DAYS") or 7)
#: A nightly copy older than this is not last night's, and is not sent.
FRESH_HOURS = 30
#: After a failure, the next try is this long after.
RETRY_HOURS = 6
SUFFIX = ".bundle.age"
NIGHTLY = re.compile(r"rouh-\d{8}-\d{6}\.dump")


class NotSetUp(RuntimeError):
    """The settings file does not say where the copy goes, or how it is locked: the reason."""


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def backup_dir() -> str:
    return _env("ROUH_BACKUP_DIR")


def work_dir() -> str:
    from .config import config

    return _env("ROUH_OFFSITE_WORK") or os.path.join(config.data_dir, "offsite")


def settings() -> dict:
    """Where the copy goes and how it is locked; NotSetUp, saying what is missing, otherwise."""
    s = {k: _env(f"ROUH_OFFSITE_{k.upper()}") for k in ("endpoint", "bucket", "key_id", "secret", "recipient", "passphrase")}
    if not any(s[k] for k in ("endpoint", "bucket", "key_id", "secret")):
        raise NotSetUp("no off-site copy is set up: ROUH_OFFSITE_ENDPOINT, _BUCKET, _KEY_ID and _SECRET in the "
                       "settings file say where it goes")
    missing = [f"ROUH_OFFSITE_{k.upper()}" for k in ("endpoint", "bucket", "key_id", "secret") if not s[k]]
    if missing:
        raise NotSetUp(f"the off-site copy is half set up: {', '.join(missing)} is not set")
    if bool(s["recipient"]) == bool(s["passphrase"]):
        raise NotSetUp("the off-site copy needs ROUH_OFFSITE_RECIPIENT (an age public key) or "
                       "ROUH_OFFSITE_PASSPHRASE, one of the two, to be encrypted with; nothing is sent unencrypted")
    name = _env("ROUH_OFFSITE_NAME") or _env("ROUH_STACK_NAME") or socket.gethostname()
    s["prefix"] = _env("ROUH_OFFSITE_PREFIX") or f"rouh-backups/{name}/"
    return s


def set_up() -> bool:
    try:
        settings()
        return True
    except NotSetUp:
        return False


def client(s: dict):
    import boto3
    from botocore.config import Config

    # Path-style addressing and checksums only when an operation needs one: what R2 and every
    # other S3 that is not Amazon's take.
    cfg = Config(s3={"addressing_style": "path"}, request_checksum_calculation="when_required",
                 response_checksum_validation="when_required", retries={"max_attempts": 5, "mode": "standard"})
    return boto3.client("s3", endpoint_url=s["endpoint"], aws_access_key_id=s["key_id"],
                        aws_secret_access_key=s["secret"], region_name="auto", config=cfg)


# --- the nightly copies (the backup part's) -----------------------------------------------------

def nightly() -> dict:
    """What the backup part has made: the newest copy and when, how many are kept, the last try."""
    root = backup_dir()
    if not root:
        return {"on": False, "human": "This Rouh keeps no nightly database copies of its own here "
                                      "(ROUH_BACKUP_DIR is not set; a server's own backups are the server's)."}
    daily = os.path.join(root, "daily")
    try:
        found = sorted(n for n in os.listdir(daily) if NIGHTLY.fullmatch(n))
    except OSError:
        found = []
    last = _read_json(os.path.join(daily, "last.json"))
    out: dict = {"on": True, "kept": len(found), "last_try": last}
    if found:
        newest = os.path.join(daily, found[-1])
        made = os.path.getmtime(newest)
        out.update(newest=found[-1], made_at=_stamp(made), bytes=os.path.getsize(newest))
        human = (f"The newest nightly copy of the database was made {_stamp(made)} ({_ago(made)}), "
                 f"{os.path.getsize(newest) / 1e6:.1f} MB; {len(found)} kept.")
    else:
        human = "No nightly copy of the database has been made yet."
    if last and not last.get("ok"):
        human += f" The last try, {last.get('at')}, failed: {last.get('error') or 'no reason given'}."
    out["human"] = human
    return out


def newest_nightly(max_hours: float = FRESH_HOURS) -> str:
    n = nightly()
    if not n.get("newest"):
        return ""
    path = os.path.join(backup_dir(), "daily", n["newest"])
    return path if time.time() - os.path.getmtime(path) < max_hours * 3600 else ""


# --- the weekly copy ----------------------------------------------------------------------------

def status() -> dict:
    return _read_json(os.path.join(work_dir(), "last.json"))


def describe() -> dict:
    """What server_health says about the off-site copy."""
    try:
        settings()
    except NotSetUp as e:
        return {"on": False, "human": str(e)[0].upper() + str(e)[1:] + "."}
    last = status()
    good = last.get("last_good") or {}
    if good:
        human = f"The newest off-site copy was sent {good.get('at')}, {int(good.get('bytes') or 0) / 1e6:.1f} MB."
    else:
        human = "No off-site copy has been sent yet."
    if last and not last.get("ok"):
        human += f" The last try, {last.get('at')}, failed: {last.get('error')}."
    bucket = in_bucket()
    human += " " + bucket["human"]
    return {"on": True, "last": last, "bucket": bucket, "human": human}


#: How long what the bucket holds is believed before it is listed again.
BUCKET_LOOK_EVERY = 60 * 60


def in_bucket(now: float | None = None) -> dict:
    """What the bucket itself holds under this Rouh's prefix: how many copies, and the newest's name,
    size and when it arrived. Petar, 5 November 2026: a backup counts when it is in the bucket, not
    when a status file says it was sent. Listed at most once an hour (kept in the work folder), with
    one quick try, so server_health never waits long on the bucket."""
    now = now or time.time()
    path = os.path.join(work_dir(), "bucket.json")
    seen = _read_json(path)
    if seen and now - float(seen.get("ts") or 0) < BUCKET_LOOK_EVERY:
        return seen
    try:
        s = settings()
        from botocore.config import Config

        quick = Config(s3={"addressing_style": "path"}, request_checksum_calculation="when_required",
                       response_checksum_validation="when_required", connect_timeout=5, read_timeout=10,
                       retries={"max_attempts": 1, "mode": "standard"})
        import boto3

        s3 = boto3.client("s3", endpoint_url=s["endpoint"], aws_access_key_id=s["key_id"],
                          aws_secret_access_key=s["secret"], region_name="auto", config=quick)
        found = objects(s3, s)
    except NotSetUp as e:
        return {"ok": False, "ts": now, "human": str(e)}
    except Exception as e:  # noqa: BLE001 - said, and looked at again next time
        got = {"ok": False, "ts": now, "count": None,
               "human": f"The bucket could not be listed just now ({type(e).__name__}: {str(e)[:160]})."}
        _keep_bucket(path, got)
        return got
    if not found:
        got = {"ok": False, "ts": now, "count": 0, "human": "The bucket holds no off-site copy of this Rouh."}
    else:
        newest = found[-1]
        when = newest["LastModified"].astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        got = {"ok": True, "ts": now, "count": len(found), "newest": newest["Key"], "bytes": int(newest["Size"]),
               "arrived_at": when,
               "human": (f"In the bucket itself, looked at {_stamp(now)}: {len(found)} cop{'y' if len(found) == 1 else 'ies'}, "
                         f"the newest {newest['Key'].rsplit('/', 1)[-1]}, {int(newest['Size']) / 1e6:.1f} MB, "
                         f"arrived {when}.")}
    _keep_bucket(path, got)
    return got


def _keep_bucket(path: str, got: dict) -> None:
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(got, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def due(now: float | None = None) -> bool:
    if not set_up():
        return False
    now = now or time.time()
    last = status()
    good = (last.get("last_good") or {}).get("ts") or 0
    if now - good < EVERY_DAYS * 86400:
        return False
    if last and not last.get("ok") and now - float(last.get("ts") or 0) < RETRY_HOURS * 3600:
        return False
    return bool(newest_nightly())


def run() -> dict:
    """One copy, now: the newest nightly copy, bundled with the keys, data and workspace,
    encrypted, sent and checked. Its result is kept (status) whatever happens."""
    s = settings()
    work = work_dir()
    os.makedirs(work, mode=0o700, exist_ok=True)
    try:
        result = _send(s, work)
    except Exception as e:
        last = status()
        _write_status(work, {"ok": False, "ts": time.time(), "at": _stamp(time.time()), "error": str(e)[:400],
                             "last_good": last.get("last_good") or {}})
        raise
    _write_status(work, {"ok": True, "ts": time.time(), "at": result["at"], "error": "", "last_good": result})
    return result


def _send(s: dict, work: str) -> dict:
    from . import agefile, bundle, filestore
    from .config import config

    dump = newest_nightly()
    if not dump:
        raise RuntimeError("there is no nightly copy of the database from the last day to send "
                           f"({nightly()['human']})")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    sealed = os.path.join(work, f"{stamp}{SUFFIX}")
    enc, django = bundle.find_encryption_key(config.data_dir), bundle.find_django_key(config.data_dir)
    # The bundle goes straight into the encryption through a pipe: nothing readable, and no key,
    # is ever written to a disk on the way.
    about: dict = {}
    failed: list[BaseException] = []
    r, w = os.pipe()

    def make() -> None:
        try:
            with os.fdopen(w, "wb") as into:
                about.update(bundle.make(into, dump=dump, data_dir=config.data_dir, workspace=config.assistant_repo,
                                         files_dir=filestore.root(),
                                         encryption_key=enc, django_key=django, made_by="the weekly off-site copy"))
        except BaseException as e:  # noqa: BLE001 - said by the thread that waits for it
            failed.append(e)

    maker = threading.Thread(target=make, name="offsite-bundle", daemon=True)
    maker.start()
    fd = os.open(sealed, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(r, "rb") as plain, os.fdopen(fd, "wb") as out:
            agefile.encrypt(plain, out, recipients=[s["recipient"]] if s["recipient"] else [],
                            passphrase=s["passphrase"])
    except BaseException:
        os.unlink(sealed)
        raise
    finally:
        maker.join()
        enc = django = ""
    if failed:
        os.unlink(sealed)
        raise RuntimeError(f"the bundle could not be made: {failed[0]}")
    try:
        size, digest = os.path.getsize(sealed), bundle.sha256_of(sealed)
        s3, key = client(s), s["prefix"] + os.path.basename(sealed)
        log.info("sending the off-site copy, %.1f MB, to %s/%s", size / 1e6, s["bucket"], key)
        s3.upload_file(sealed, s["bucket"], key, ExtraArgs={"Metadata": {"sha256": digest, "dump": os.path.basename(dump)}})
        head = s3.head_object(Bucket=s["bucket"], Key=key)
        if head["ContentLength"] != size or (head.get("Metadata") or {}).get("sha256") != digest:
            raise RuntimeError(f"the bucket holds {head['ContentLength']} bytes of {size}; it is not trusted")
        gone = prune(s3, s)
    finally:
        os.unlink(sealed)
    log.info("the off-site copy is in %s, %d older one(s) deleted", key, len(gone))
    return {"ts": time.time(), "at": _stamp(time.time()), "key": key, "bytes": size, "sha256": digest,
            "dump": os.path.basename(dump), "data_files": about["data_files"],
            "workspace_files": about["workspace_files"], "deleted_old": gone}


def objects(s3, s: dict) -> list[dict]:
    got, token = [], None
    while True:
        kw = {"Bucket": s["bucket"], "Prefix": s["prefix"]}
        if token:
            kw["ContinuationToken"] = token
        page = s3.list_objects_v2(**kw)
        got += [o for o in page.get("Contents", []) if o["Key"].endswith(SUFFIX)]
        if not page.get("IsTruncated"):
            return sorted(got, key=lambda o: o["Key"])
        token = page["NextContinuationToken"]


def prune(s3, s: dict) -> list[str]:
    old = objects(s3, s)[:-KEEP]
    for o in old:
        s3.delete_object(Bucket=s["bucket"], Key=o["Key"])
    return [o["Key"] for o in old]


def fetch(to: str, key: str = "") -> dict:
    """The newest copy (or key), downloaded as it is, still encrypted, and checked against the
    SHA-256 it was sent with."""
    from . import bundle

    s = settings()
    s3 = client(s)
    if not key:
        found = objects(s3, s)
        if not found:
            raise RuntimeError("there is no off-site copy in the bucket yet")
        key = found[-1]["Key"]
    if not key.startswith(s["prefix"]):
        raise RuntimeError(f"{key} is not under this Rouh's prefix, {s['prefix']}")
    fd = os.open(to, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    s3.download_file(s["bucket"], key, to)
    want = (s3.head_object(Bucket=s["bucket"], Key=key).get("Metadata") or {}).get("sha256")
    if bundle.sha256_of(to) != want:
        raise RuntimeError("the downloaded copy does not match the SHA-256 it was sent with")
    return {"key": key, "to": to, "bytes": os.path.getsize(to), "sha256": want}


# --- small helpers ------------------------------------------------------------------------------

def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            got = json.load(fh)
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_status(work: str, data: dict) -> None:
    tmp = os.path.join(work, ".last.json")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, os.path.join(work, "last.json"))


def _stamp(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _ago(ts: float) -> str:
    hours = (time.time() - ts) / 3600
    if hours < 1:
        n = max(1, int(hours * 60))
        return f"{n} minute{'s' if n != 1 else ''} ago"
    if hours < 48:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
    return f"{int(hours / 24)} days ago"
