"""One private PostgreSQL instance per real-data rehearsal, removed with its WAL afterwards.

The ordinary check database remains synthetic. These three users are separate from ordinary
checks (10004): the copy's proof, its PostgreSQL server, and the real migration helper.
"""
from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

PROOF_USER, SERVER_USER, APPLY_USER = 10005, 10006, 10007


def private(path: Path, user: int) -> None:
    path.mkdir(exist_ok=True, parents=True)
    os.chmod(path, 0o700)
    if os.getuid() == 0:
        subprocess.run(["chown", "-R", f"{user}:{user}", str(path)], check=True)


def stop_children(user: int) -> None:
    if os.getuid() == 0:
        # Only this protected operation uses this reserved uid, under Changes.lock.
        subprocess.run(["setpriv", f"--reuid={user}", f"--regid={user}", "--clear-groups", "--",
                        "pkill", "-KILL", "-u", str(user)], capture_output=True, timeout=20)


@contextlib.contextmanager
def database(state: Path):
    import psycopg

    root = Path(tempfile.mkdtemp(prefix="rehearsal-", dir=state))
    socket = Path(tempfile.mkdtemp(prefix="guard-pg-"))
    private(root, SERVER_USER)
    if os.getuid() == 0:
        os.chown(socket, SERVER_USER, PROOF_USER)
    os.chmod(socket, 0o750)
    data, password = root / "data", root / "password"
    db = {"HOST": str(socket), "PORT": "5432", "NAME": "rouh", "USER": "rouh", "PASSWORD": secrets.token_urlsafe(32)}
    password.write_text(db["PASSWORD"])
    os.chmod(password, 0o600)
    if os.getuid() == 0:
        os.chown(password, SERVER_USER, SERVER_USER)
    binaries = Path(os.environ.get("ROUH_GUARD_PG_BIN", "/opt/pg/bin"))
    environment = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(root), "LANG": "C",
                   "LD_LIBRARY_PATH": os.environ.get("ROUH_GUARD_PG_LIB", "/opt/pg/lib")}
    pre = ["setpriv", f"--reuid={SERVER_USER}", f"--regid={SERVER_USER}", "--clear-groups", "--"] if os.getuid() == 0 else []

    def run(tool, *args):
        r = subprocess.run([*pre, str(binaries / tool), *map(str, args)], env=environment,
                           cwd=root, capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise ValueError("the private PostgreSQL rehearsal could not " + tool + ": " + (r.stderr + r.stdout)[-800:])

    started = False
    try:
        run("initdb", "-D", data, "-U", "rouh", "--pwfile", password,
            "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C")
        password.unlink()
        run("pg_ctl", "-D", data, "-l", root / "server.log", "-w", "-t", "60", "start",
            "-o", "-h '' -k " + str(socket) + " -p 5432 -c max_connections=20 -c jit=off")
        started = True
        with psycopg.connect(host=db["HOST"], port=db["PORT"], dbname="postgres", user="rouh",
                              password=db["PASSWORD"], autocommit=True) as conn:
            conn.execute("CREATE DATABASE rouh OWNER rouh")
        yield db
    finally:
        stop_children(PROOF_USER)
        try:
            if started or (data / "postmaster.pid").exists():
                run("pg_ctl", "-D", data, "-w", "-t", "30", "stop", "-m", "immediate")
        except Exception:
            # Keep the private files if shutdown could not be confirmed; never prune a running
            # server's data. Ordinary checks cannot traverse either private directory.
            raise ValueError("the private real-data rehearsal did not stop safely; its files remain protected") from None
        else:
            stop_children(SERVER_USER)
            shutil.rmtree(root)
            shutil.rmtree(socket)
