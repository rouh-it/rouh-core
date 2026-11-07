"""A PostgreSQL of its own, for a world that is thrown away afterwards.

Rouh keeps everything in PostgreSQL, so every copy of it the browser
environment stands up needs a database, and no copy may ever share one with
the server's or with another world. This makes a whole cluster in a folder -
`initdb`, then `pg_ctl start` on a socket in that folder and on no network
address at all - and one database in it, owned by whoever ran it. It takes a
second or two, needs no password and no root, and is gone with the folder.

    cluster = postgres.start(folder / "pg")
    env.update(cluster.env())          # ROUH_DB_HOST, _PORT, _NAME, _USER
    ...
    postgres.stop(cluster)

Nothing here touches the machine's own PostgreSQL. It uses that
installation's programs (`initdb`, `pg_ctl`), found by `bin_dir`.
"""
from __future__ import annotations

import glob
import getpass
import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


def bin_dir() -> str:
    """Where `initdb` and `pg_ctl` are: on the PATH, or Debian's own folder."""
    said = os.environ.get("ROUH_PG_BIN")
    if said:
        return said
    found = shutil.which("initdb")
    if found:
        return os.path.dirname(found)
    versions = sorted(glob.glob("/usr/lib/postgresql/*/bin/initdb"),
                      key=lambda p: int(p.split("/")[-3]) if p.split("/")[-3].isdigit() else 0)
    if versions:
        return os.path.dirname(versions[-1])
    for mac in ("/opt/homebrew/bin", "/usr/local/bin"):
        if os.path.exists(os.path.join(mac, "initdb")):
            return mac
    raise RuntimeError("There is no PostgreSQL here to make a throwaway database with: "
                       "no initdb on the PATH or under /usr/lib/postgresql. "
                       "Set ROUH_PG_BIN to the folder that has it.")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@dataclass
class Cluster:
    folder: Path
    port: int
    user: str
    name: str = "rouh"
    #: The folder the socket is in. Short on purpose: a unix socket's path
    #: may be at most 107 bytes, and a pytest temporary folder is often longer.
    socket_dir: str = ""

    def env(self) -> dict[str, str]:
        """What to put in a Rouh's environment so it uses this database."""
        return {
            "ROUH_DB_HOST": self.socket_dir,
            "ROUH_DB_PORT": str(self.port),
            "ROUH_DB_NAME": self.name,
            "ROUH_DB_USER": self.user,
            "ROUH_DB_PASSWORD": "",
            # So nothing reads the server's password file by accident.
            "ROUH_DB_PASSWORD_FILE": str(self.folder / "no-password.json"),
        }


def start(folder: Path | str, *, name: str = "rouh", options: str = "") -> Cluster:
    """A running cluster in `folder`, with one empty database called `name`; `options` are more
    `-c name=value` settings for the server (the Synapse benchmark loads pg_search with one)."""
    folder = Path(folder)
    data = folder / "data"
    folder.mkdir(parents=True, exist_ok=True)
    run = folder / "run"
    if len(str(run)) > 80:
        run = Path(tempfile.mkdtemp(prefix="rouh-pg-", dir="/tmp"))
    run.mkdir(parents=True, exist_ok=True)
    tools = bin_dir()
    user = getpass.getuser()
    if not (data / "PG_VERSION").exists():
        subprocess.run(
            [os.path.join(tools, "initdb"), "-D", str(data), "-U", user, "-A", "trust",
             "-E", "UTF8", "--no-instructions",
             # Text sorts by code point, as it did in SQLite and as it does in
             # the server's database (`rouh/management/commands/predeploy.py`),
             # so an ORDER BY on a title means the same thing everywhere.
             "--lc-collate=C", "--lc-ctype=C.UTF-8"],
            check=True, capture_output=True, timeout=120)
    port = _free_port()
    # No TCP at all: only the socket in this folder, so nothing outside this
    # machine's own user can reach it, and two worlds can never collide.
    flags = (f"-k {run} -p {port} -c listen_addresses='' -c fsync=off "
             "-c full_page_writes=off -c synchronous_commit=off" + (f" {options}" if options else ""))
    subprocess.run(
        [os.path.join(tools, "pg_ctl"), "-D", str(data), "-l", str(folder / "postgres.log"),
         "-o", flags, "-w", "-t", "60", "start"],
        check=True, capture_output=True, timeout=90)
    cluster = Cluster(folder=folder, port=port, user=user, name=name, socket_dir=str(run))
    until = time.time() + 30
    while True:
        made = subprocess.run(
            [os.path.join(tools, "createdb"), "-h", str(run), "-p", str(port), "-U", user, name],
            capture_output=True, text=True, timeout=30)
        if made.returncode == 0 or "already exists" in made.stderr:
            break
        if time.time() > until:
            raise RuntimeError(f"the throwaway database would not be made: {made.stderr}")
        time.sleep(0.3)
    return cluster


def stop(cluster: Cluster | None) -> None:
    """Stop it, fast. The folder is left for whoever made it to delete."""
    if cluster is None:
        return
    subprocess.run(
        [os.path.join(bin_dir(), "pg_ctl"), "-D", str(cluster.folder / "data"), "-m", "immediate",
         "-w", "-t", "30", "stop"],
        capture_output=True, timeout=60)
    if cluster.socket_dir.startswith("/tmp/rouh-pg-"):
        shutil.rmtree(cluster.socket_dir, ignore_errors=True)


# --- one database per world ---------------------------------------------------------

#: The repository, for `manage.py`.
REPO = Path(__file__).resolve().parents[2]

#: The clusters the worlds have started, by the folder each world lives in, so
#: whoever stops the world stops its database with it.
_WORLDS: dict[str, Cluster] = {}


def migrate(env: dict[str, str]) -> None:
    """Django's schema, into the database `env` names."""
    import sys

    done = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"],
                          cwd=str(REPO), env=env, capture_output=True, text=True, timeout=300)
    if done.returncode != 0:
        raise RuntimeError(f"the schema would not go in:\n{done.stdout}\n{done.stderr}")


def for_world(folder: Path | str, env: dict[str, str]) -> Cluster:
    """A database for one world, migrated, with its settings put into `env`.

    Asked twice for the same folder, it is the same database: a world that
    makes two accounts has one database with two accounts in it.
    """
    key = str(Path(folder).resolve())
    cluster = _WORLDS.get(key)
    if cluster is None:
        cluster = start(Path(folder) / "pg")
        _WORLDS[key] = cluster
    env.update(cluster.env())
    migrate(env)
    return cluster


def stop_world(folder: Path | str) -> None:
    """Stop the database a world was given, if it was given one."""
    stop(_WORLDS.pop(str(Path(folder).resolve()), None))
