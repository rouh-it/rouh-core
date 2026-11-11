"""Fresh backups and atomic migrations, rehearsed against a full copy of this Rouh's database.

No live credentials reach the ordinary proof or the rehearsal. The guard retains the backup,
counts, preservation hashes, restore instructions and outcome. A real migration locks out writers
and checks preservation in the same transaction as the schema change; failure rolls it all back.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path


def live() -> dict:
    names = {"HOST": "postgres", "PORT": "5432", "NAME": "rouh", "USER": "rouh", "PASSWORD": ""}
    got = {k: os.environ.get("ROUH_GUARD_DB_" + k, v) for k, v in names.items()}
    if not got["PASSWORD"] and not os.environ.get("ROUH_GUARD_DB_HOST"):
        raise ValueError("the protected core has no database migration connection configured")
    return got


def _kw(db: dict) -> dict:
    return {"host": db["HOST"], "port": db["PORT"], "dbname": db["NAME"], "user": db["USER"],
            "password": db["PASSWORD"], "connect_timeout": 10}


def inventory() -> list[dict]:
    """Schema for a frontier planning job, never people's rows or credentials."""
    import psycopg

    with psycopg.connect(**_kw(live())) as conn:
        rows = conn.execute("SELECT table_name,column_name,data_type FROM information_schema.columns "
                            "WHERE table_schema='public' ORDER BY table_name,ordinal_position").fetchall()
    return [{"table": t, "column": c, "type": ty} for t, c, ty in rows]


def pg(tool: str, db: dict, *args: str) -> None:
    root = Path(os.environ.get("ROUH_GUARD_PG_BIN", "/opt/pg/bin"))
    command = root / tool
    if not command.is_file():
        raise ValueError("the protected core needs PostgreSQL's backup tools before database updates can run")
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": "/tmp",
                   "LD_LIBRARY_PATH": os.environ.get("ROUH_GUARD_PG_LIB", "/opt/pg/lib"),
                   **{"PG" + k: str(v) for k, v in db.items() if k != "NAME"}, "PGDATABASE": db["NAME"]}
    extra = ["--dbname=" + db["NAME"]] if tool == "pg_restore" else []
    r = subprocess.run([str(command), *extra, *args], env=environment, capture_output=True, text=True, timeout=1800)
    if r.returncode:
        raise ValueError(f"{tool} failed: " + r.stderr[-700:])


def _write(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def _real(helper: Path, tree: Path, data: Path, db: dict, planfile: Path, backup: Path) -> subprocess.CompletedProcess:
    """Keep the writer locks while pg_dump reads the exact pre-migration snapshot."""
    from .updatecheck import CHECK_USER, env

    pre = ["setpriv", f"--reuid={CHECK_USER}", f"--regid={CHECK_USER}", "--clear-groups", "--"] if os.getuid() == 0 else []
    snapshot, go = data / "snapshot", data / "go"
    snapshot.unlink(missing_ok=True)
    go.unlink(missing_ok=True)
    with open(data / "real.log", "w+") as log:
        proc = subprocess.Popen([*pre, "python", str(helper), str(planfile), "real"], cwd=tree,
                                env=env(data, db), stdout=log, stderr=log)
        try:
            end = time.monotonic() + 120
            while not snapshot.exists():
                if proc.poll() is not None or time.monotonic() >= end:
                    raise ValueError("the real migration could not lock its pre-migration snapshot")
                time.sleep(.2)
            pg("pg_dump", db, "-Fc", "--snapshot=" + snapshot.read_text(), "--file=" + str(backup))
            os.chmod(backup, 0o600)
            go.write_text("the protected backup is complete")
            proc.wait(timeout=1500)
            log.seek(0)
            return subprocess.CompletedProcess(proc.args, proc.returncode, log.read(), "")
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


def run(tree: Path, proof: Path, plan: dict, state: Path, commit: str, *, before: Path | None = None,
        security: bool = False, not_applicable: bool = False) -> None:
    import psycopg
    from psycopg import sql

    from .updatecheck import CHECK_USER, env, run_program, security_result

    if not plan.get("restore") or not isinstance(plan.get("tables", {}), dict):
        raise ValueError("the database plan needs its table mapping and written restore path")
    db = live()
    tag = commit[:12] + "-" + uuid.uuid4().hex[:8]
    keep = state / "database-updates" / tag
    keep.mkdir(parents=True, mode=0o700)
    backup = keep / "before.dump"
    record = {"commit": commit, "at": time.time(), "plan": plan, "backup": str(backup),
              "restore": "Stop the core, then restore before.dump with pg_restore into a new database; "
                         "check it, and switch the database names before starting the earlier undo point.",
              "rehearsal": False, "applied": False}
    _write(keep / "outcome.json", record)
    # Full pg_dump, not last night's copy. No backup is pruned while its undo point may need it.
    pg("pg_dump", db, "-Fc", "--file=" + str(backup))
    os.chmod(backup, 0o600)
    copy = {"HOST": os.environ.get("ROUH_GUARD_CHECK_DB", "checkdb"),
            "PORT": os.environ.get("ROUH_GUARD_CHECK_DB_PORT", "5432"),
            "NAME": "rehearse_" + uuid.uuid4().hex[:20], "USER": "rouh", "PASSWORD": "check"}
    admin = {**copy, "NAME": "postgres"}
    data = tree.parent / ("migration-" + tag)
    data.mkdir()
    planfile = data / "plan.json"
    planfile.write_text(json.dumps(plan))
    helper = Path(__file__).resolve().parents[1] / "bin/rouh-update-database"
    try:
        with psycopg.connect(**_kw(admin), autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {} OWNER rouh").format(sql.Identifier(copy["NAME"])))
        pg("pg_restore", copy, "--no-owner", "--no-privileges", "--exit-on-error", str(backup))
        if os.getuid() == 0:
            subprocess.run(["chown", "-R", f"{CHECK_USER}:{CHECK_USER}", str(data)], check=True)
        if security:
            was = run_program(proof, before, env(data, copy))
            b = security_result(was)
            if was.returncode != (0 if not_applicable else 1) or b.get("vulnerable") is not (not not_applicable) or not b.get("checks"):
                raise ValueError("the security test did not prove the hole before the database change")
        r = run_program(helper, tree, env(data, copy), str(planfile), "rehearsal")
        if r.returncode:
            raise ValueError("rehearsal on the real database copy failed: " + (r.stdout + r.stderr)[-1400:])
        counts = json.loads((data / "counts.json").read_text())
        r = run_program(proof, tree, env(data, copy))
        if r.returncode:
            raise ValueError("master's migration test on the real copy failed: " + (r.stdout + r.stderr)[-1200:])
        if security:
            a = security_result(r)
            if a.get("vulnerable") is not False or a.get("checks") != b.get("checks"):
                raise ValueError("the same security assertions did not show the hole closed on the migrated copy")
        # This is explicitly a disposable real-data copy; the normal CLI refuses live accounts.
        check = data / "selfcheck.py"
        check.write_text("import django; django.setup()\nfrom rouh import selfcheck\n"
                         "r=selfcheck.run('own', db_ready=True)\nprint(r.line())\nraise SystemExit(0 if r.ok else 1)\n")
        r = run_program(check, tree, env(data, copy))
        if r.returncode:
            raise ValueError("this Rouh's self-checks on the migrated copy failed: " + (r.stdout + r.stderr)[-1200:])
        record.update(rehearsal=True, counts=counts)
        _write(keep / "outcome.json", record)
        # The same protected helper holds all the table locks and migrates in one transaction.
        # Its preservation checks precede COMMIT. An exception leaves the live database untouched.
        r = _real(helper, tree, data, db, planfile, keep / "immediately-before.dump")
        if r.returncode:
            raise ValueError("the real migration rolled back: " + (r.stdout + r.stderr)[-1400:])
        record.update(applied=True, after=json.loads((data / "counts.json").read_text()))
        _write(keep / "outcome.json", record)
    except Exception as exc:
        record["error"] = str(exc)
        _write(keep / "outcome.json", record)
        raise
    finally:
        with psycopg.connect(**_kw(admin), autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(copy["NAME"])))


def migrate(planfile: Path, phase: str) -> None:
    """Protected helper, running with the proposed code, against only the database it is given."""
    import hashlib
    import sys
    from collections import Counter

    sys.path.insert(0, str(Path.cwd()))
    import django
    django.setup()
    from django.core.management import call_command
    from django.db import connection, transaction
    from django.db.migrations.executor import MigrationExecutor

    plan = json.loads(planfile.read_text())
    q = connection.ops.quote_name

    def tables():
        with connection.cursor() as c:
            c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
            return [r[0] for r in c.fetchall()]

    def columns(table):
        with connection.cursor() as c:
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                      "AND table_name=%s ORDER BY ordinal_position", [table])
            return [r[0] for r in c.fetchall()]

    def rows(table, cols):
        hashes = Counter()
        with connection.cursor() as c:
            c.execute("SELECT ROW(" + ",".join(q(x) for x in cols) + ")::text FROM " + q(table))
            while batch := c.fetchmany(1000):
                hashes.update(hashlib.sha256(r[0].encode()).hexdigest() for r in batch)
        return hashes

    result = {"phase": phase, "tables": {}}
    with transaction.atomic():
        with connection.cursor() as c:
            c.execute("SET LOCAL lock_timeout='30s'")
            c.execute("SET LOCAL statement_timeout='15min'")
            # SHARE blocks INSERT/UPDATE/DELETE while permitting readers and the backup.
            names = tables()
            if names:
                c.execute("LOCK TABLE " + ",".join(q(t) for t in names) + " IN SHARE MODE")
            if phase == "real":
                c.execute("SELECT pg_export_snapshot()")
                planfile.with_name("snapshot").write_text(c.fetchone()[0])
                end = time.monotonic() + 1800
                while not planfile.with_name("go").exists():
                    if time.monotonic() >= end:
                        raise ValueError("the protected pre-migration backup did not complete")
                    time.sleep(.2)
        before = {}
        for table in names:
            if table == "django_migrations":
                continue  # Its new rows are expected and never memory.
            cols = columns(table)
            before[table] = (cols, rows(table, cols))
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if any(not migration.atomic for migration, _backwards in pending):
            raise ValueError("a non-atomic migration needs an adapted atomic or expand-and-contract plan")
        executor.migrate(executor.loader.graph.leaf_nodes())
        after_tables = tables()
        for old, (cols, old_rows) in before.items():
            new = plan.get("tables", {}).get(old, old)
            mapping = plan.get("columns", {}).get(old, {})
            newcols = [mapping.get(c, c) for c in cols]
            if new not in after_tables or not set(newcols) <= set(columns(new)):
                raise ValueError(f"{old}: existing data has no destination in the migration plan")
            new_rows = rows(new, newcols)
            if old_rows - new_rows:
                raise ValueError(f"{old}: the migration lost or changed existing memory")
            result["tables"][old] = {"destination": new, "before": sum(old_rows.values()),
                                    "after": sum(new_rows.values()), "preserved": True}
        call_command("check", verbosity=0)
    # Read the result back after COMMIT as well, before reporting it applied.
    for old, (cols, old_rows) in before.items():
        new = plan.get("tables", {}).get(old, old)
        newcols = [plan.get("columns", {}).get(old, {}).get(c, c) for c in cols]
        if old_rows - rows(new, newcols):
            raise RuntimeError(f"{old}: preservation check after migration failed; use the protected backup")
    planfile.with_name("counts.json").write_text(json.dumps(result))
