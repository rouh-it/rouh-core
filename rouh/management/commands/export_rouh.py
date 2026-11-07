"""``python manage.py export_rouh``: this Rouh in one file, to bring it into a stack of containers.

The bundle (`rouh/bundle.py`): Rouh's database (pg_dump), the key every saved login is sealed
with, the key sign-ins are signed with, its data directory and its workspace. Put into a fresh
stack, before its first start, with ``linux_stack.py import BUNDLE`` (deploy/container/
INSTALL-LINUX-VM.md, "Bringing in a Rouh you already have").

    python manage.py export_rouh --out /var/tmp/rouh.bundle
    python manage.py export_rouh --out - | ssh new-machine 'umask 077; cat > rouh.bundle'
    python manage.py export_rouh --out /data/export/rouh.bundle --dump newest     (in a stack's core)

On a server Rouh run it with the service's own settings, which say where its data, workspace,
keys and database are; on such a server, as root:

    systemd-run --quiet --wait --pipe --collect -p EnvironmentFile=-/var/www/rouh/.env \\
      -p WorkingDirectory=/var/www/rouh/app /var/www/rouh/.venv/bin/python \\
      manage.py export_rouh --out - > /var/tmp/rouh.bundle

The database is dumped with this machine's pg_dump, which must be as new as the database's
server. A stack's core has none of its own; there ``--dump newest`` takes the newest nightly
copy the backup part made (``docker compose exec backup rouh-backup now`` makes one now).

The file opens every saved login it holds, so it is made readable by its owner alone, never
written to a terminal, and no key is ever printed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

from django.core.management.base import BaseCommand, CommandError


def newest_nightly() -> str:
    """The newest copy the stack's backup part made (guard/bin/rouh-backup), or ""."""
    root = os.path.join(os.environ.get("ROUH_BACKUP_DIR") or "/backups", "daily")
    try:
        found = sorted(n for n in os.listdir(root) if re.fullmatch(r"rouh-\d{8}-\d{6}\.dump", n))
    except OSError:
        return ""
    return os.path.join(root, found[-1]) if found else ""


def pg_dump_into(path: str) -> None:
    """Rouh's own database, dumped with this machine's pg_dump, as Django connects to it."""
    from django.db import connection

    db = connection.settings_dict
    binary = shutil.which("pg_dump")
    if not binary:
        raise CommandError("this machine has no pg_dump. In a stack's core take the newest nightly copy: "
                           "--dump newest (docker compose exec backup rouh-backup now makes one).")
    with connection.cursor() as cur:
        cur.execute("show server_version_num")
        server = int(cur.fetchone()[0]) // 10000
    said = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout
    found = re.search(r"(\d+)", said)
    mine = int(found.group(1)) if found else 0
    if mine < server:
        raise CommandError(f"this machine's pg_dump is version {mine} and the database is {server}: "
                           f"pg_dump must be as new as the server. Install postgresql-client-{server}, "
                           "or give --dump a dump made with one.")
    env = {**os.environ, "PGPASSWORD": str(db.get("PASSWORD") or "")}
    args = [binary, "-Fc", "-f", path, "-d", str(db["NAME"])]
    if db.get("HOST"):
        args += ["-h", str(db["HOST"])]
    if db.get("PORT"):
        args += ["-p", str(db["PORT"])]
    if db.get("USER"):
        args += ["-U", str(db["USER"])]
    r = subprocess.run(args, env=env, capture_output=True, text=True)
    if r.returncode:
        raise CommandError(f"pg_dump failed: {r.stderr.strip()[-400:]}")


class Command(BaseCommand):
    help = "This Rouh in one file (database, keys, data, workspace), to import into a stack."

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="the bundle to make, a new file; - for stdout (never a terminal)")
        parser.add_argument("--dump", default="", help="a pg_dump -Fc file to put in instead of dumping now; newest "
                                                        "for the stack's newest nightly copy")

    def handle(self, *args, **opts):
        from rouh import bundle, filestore
        from rouh.config import config
        from rouh.version import get_version

        out = opts["out"]
        tell = sys.stderr if out == "-" else self.stdout
        if out == "-" and sys.stdout.isatty():
            raise CommandError("the bundle holds the keys to every saved login: it is not written to a terminal. "
                               "Give --out a file, or send - into one (> rouh.bundle) or over ssh.")
        data_dir, workspace = config.data_dir, config.assistant_repo
        enc, django = bundle.find_encryption_key(data_dir), bundle.find_django_key(data_dir)
        if not enc:
            tell.write("This Rouh has no encryption key yet, so it has sealed nothing: the bundle holds none.\n")

        work = tempfile.mkdtemp(prefix="rouh-export-", dir=os.path.dirname(os.path.abspath(out)) if out != "-" else None)
        os.chmod(work, 0o700)
        handle = None
        try:
            dump = opts["dump"]
            if dump == "newest":
                dump = newest_nightly()
                if not dump:
                    raise CommandError("there is no nightly copy of the database in "
                                       f"{os.environ.get('ROUH_BACKUP_DIR') or '/backups'}/daily yet: "
                                       "docker compose exec backup rouh-backup now")
                tell.write(f"The database as it was in {os.path.basename(dump)}.\n")
            elif not dump:
                dump = os.path.join(work, "database.dump")
                pg_dump_into(dump)
            elif not os.path.isfile(dump):
                raise CommandError(f"there is no dump at {dump}")
            if out == "-":
                handle = os.fdopen(os.dup(sys.stdout.fileno()), "wb")
            else:
                try:
                    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    raise CommandError(f"{out} is there already; nothing is written over") from None
                handle = os.fdopen(fd, "wb")
            version = get_version() or {}
            about = bundle.make(handle, dump=dump, data_dir=data_dir, workspace=workspace,
                                files_dir=filestore.root(), encryption_key=enc,
                                django_key=django, made_by=f"export_rouh at {version.get('short_sha') or 'an unknown commit'}")
            handle.close()
            handle = None
        except BaseException:
            if handle is not None:
                handle.close()
                if out != "-":
                    os.unlink(out)
            raise
        finally:
            shutil.rmtree(work, ignore_errors=True)
            enc = django = ""
        tell.write(f"Made {'the bundle' if out == '-' else out}: {bundle.describe(about)}.\n"
                   "It opens every saved login it holds: keep it as you would the keys themselves, and delete "
                   "it once it is imported (linux_stack.py import).\n")
