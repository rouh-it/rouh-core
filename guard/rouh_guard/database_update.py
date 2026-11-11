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


def inventory() -> dict:
    """Schema for a frontier planning job, never people's rows or credentials."""
    import psycopg

    with psycopg.connect(**_kw(live())) as conn:
        rows = conn.execute("SELECT table_schema,table_name,column_name,data_type FROM information_schema.columns "
                            "WHERE table_schema NOT IN ('pg_catalog','information_schema') AND table_schema NOT LIKE 'pg_%' "
                            "ORDER BY table_schema,table_name,ordinal_position").fetchall()
        history = conn.execute("SELECT app,name FROM django_migrations ORDER BY app,name").fetchall() \
            if conn.execute("SELECT to_regclass('django_migrations')").fetchone()[0] else []
    return {"schema": [{"table": t if s == "public" else s + "." + t, "column": c, "type": ty} for s, t, c, ty in rows],
            "migrations": [{"app": app, "name": name} for app, name in history]}


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
    from .updatecheck import env
    from .rehearsal import APPLY_USER, stop_children

    pre = ["setpriv", f"--reuid={APPLY_USER}", f"--regid={APPLY_USER}", "--clear-groups", "--"] if os.getuid() == 0 else []
    snapshot, go, ready = data / "snapshot", data / "go", data / "ready"
    snapshot.unlink(missing_ok=True)
    go.unlink(missing_ok=True)
    ready.unlink(missing_ok=True)
    with open(data / "real.log", "w+") as log:
        unavailable = {"HOST": "/no-live-database-during-setup", "PORT": "5432", "NAME": "unavailable",
                       "USER": "unavailable", "PASSWORD": "unavailable"}
        proc = subprocess.Popen([*pre, "python", str(helper), str(planfile), "real"], cwd=tree,
                                env=env(data, unavailable), stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            end = time.monotonic() + 120
            while not ready.exists():
                if proc.poll() is not None or time.monotonic() >= end:
                    log.seek(0)
                    raise ValueError("the migration's startup must finish without database access: " + log.read()[-1200:])
                time.sleep(.2)
            proc.stdin.write((json.dumps(db) + "\n").encode())
            proc.stdin.close()
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
                if os.getuid() == 0:
                    stop_children(APPLY_USER)
                else:
                    proc.kill()
                proc.wait(timeout=30)
            stop_children(APPLY_USER)


def run(tree: Path, proof: Path, plan: dict, state: Path, commit: str, *, before: Path | None = None,
        security: bool = False, not_applicable: bool = False) -> None:
    import psycopg
    from . import rehearsal
    from .updatecheck import env, run_program, security_result

    if not plan.get("restore") or not isinstance(plan.get("tables", {}), dict):
        raise ValueError("the database plan needs its table mapping and written restore path")
    db = live()
    tag = commit[:12] + "-" + uuid.uuid4().hex[:8]
    keep = state / "database-updates" / tag
    keep.mkdir(parents=True, mode=0o700)
    backup = keep / "before.dump"
    record = {"commit": commit, "at": time.time(), "plan": plan, "backup": str(backup),
              "restore": "Stop the core, then restore immediately-before.dump (before.dump if application never began) "
                         "with pg_restore into a new database; "
                         "check it, and switch the database names before starting the earlier undo point.",
              "rehearsal": False, "applied": False}
    _write(keep / "outcome.json", record)
    with psycopg.connect(**_kw(db)) as conn:
        size = conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
    if shutil.disk_usage(state).free < max(4 * size, 1024**3) + 1024**3:
        raise ValueError("more free disk space is needed for the full backups and private real-data verification copies")
    # Full pg_dump, not last night's copy. No backup is pruned while its undo point may need it.
    pg("pg_dump", db, "-Fc", "--file=" + str(backup))
    os.chmod(backup, 0o600)
    data = tree.parent / ("migration-" + tag)
    # Distinct users keep an ordinary check from reading either proof credentials or the
    # real migration's environment. Only these private data folders are writable by each.
    if os.getuid() == 0:
        os.chmod(tree.parent, 0o711)
    rehearsal.private(data, rehearsal.PROOF_USER)
    planfile = data / "plan.json"
    planfile.write_text(json.dumps(plan))

    def test(program, cwd, environment, *args):
        return run_program(program, cwd, environment, *args, user=rehearsal.PROOF_USER)

    helper = Path(__file__).resolve().parents[1] / "bin/rouh-update-database"
    try:
        with rehearsal.database(state) as copy:
            pg("pg_restore", copy, "--no-owner", "--no-privileges", "--exit-on-error", str(backup))
            if security:
                was = test(proof, before, env(data, copy))
                b = security_result(was)
                if was.returncode != (0 if not_applicable else 1) or b.get("vulnerable") is not (not not_applicable) or not b.get("checks"):
                    raise ValueError("the security test did not prove the hole before the database change")
            r = test(helper, tree, env(data, copy), str(planfile), "rehearsal")
            if r.returncode:
                raise ValueError("rehearsal on the real database copy failed: " + (r.stdout + r.stderr)[-1400:])
            counts = json.loads((data / "counts.json").read_text())
            r = test(proof, tree, env(data, copy))
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
            r = test(check, tree, env(data, copy))
            if r.returncode:
                raise ValueError("this Rouh's self-checks on the migrated copy failed: " + (r.stdout + r.stderr)[-1200:])
            if before is not None:
                # The old code remains live until the new undo point activates, and may be
                # restored if activation fails. Require expand/contract compatibility here.
                r = test(check, before, env(data, copy))
                if r.returncode:
                    raise ValueError("the code still running cannot use the migrated copy; replan as expand and contract: "
                                     + (r.stdout + r.stderr)[-1200:])
        record.update(rehearsal=True, private_copy_removed=True, running_code_compatible=before is not None, counts=counts)
        _write(keep / "outcome.json", record)
        # The same protected helper holds all the table locks and migrates in one transaction.
        # Its preservation checks precede COMMIT. Failure inside that transaction rolls it back.
        record.update(application_started=True, applied=None)
        _write(keep / "outcome.json", record)
        real_data = tree.parent / ("apply-" + tag)
        rehearsal.private(real_data, rehearsal.APPLY_USER)
        real_plan = real_data / "plan.json"
        real_plan.write_text(json.dumps(plan))
        r = _real(helper, tree, real_data, db, real_plan, keep / "immediately-before.dump")
        if r.returncode:
            raise ValueError("the real migration did not finish its verification; its application outcome needs checking "
                             "against the protected backup and restore path: " + (r.stdout + r.stderr)[-1400:])
        record.update(applied=True, after=json.loads((real_data / "counts.json").read_text()))
        _write(keep / "outcome.json", record)
        # Prove the result actually applied, without giving a general proof live credentials.
        after_backup = keep / "after.dump"
        pg("pg_dump", db, "-Fc", "--file=" + str(after_backup))
        os.chmod(after_backup, 0o600)
        with rehearsal.database(state) as actual:
            pg("pg_restore", actual, "--no-owner", "--no-privileges", "--exit-on-error", str(after_backup))
            r = test(proof, tree, env(data, actual))
            if r.returncode:
                raise ValueError("master's proof on a copy of the applied database failed: " + (r.stdout + r.stderr)[-1200:])
            if security:
                result = security_result(r)
                if result.get("vulnerable") is not False or result.get("checks") != b.get("checks"):
                    raise ValueError("the applied database did not pass the same security assertions")
            r = test(check, tree, env(data, actual))
            if r.returncode:
                raise ValueError("the applied database did not pass this Rouh's self-checks: " + (r.stdout + r.stderr)[-1200:])
        record.update(verified_after_application=True)
        _write(keep / "outcome.json", record)
    except Exception as exc:
        record["error"] = str(exc)
        _write(keep / "outcome.json", record)
        raise


def migrate(planfile: Path, phase: str) -> None:
    """Protected helper, running with the proposed code, against only the database it is given."""
    import hashlib
    import sys
    from collections import Counter

    sys.path.insert(0, str(Path.cwd()))
    import django
    if phase == "real":
        import threading
        from django.db.backends.base.base import BaseDatabaseWrapper

        connect = BaseDatabaseWrapper.ensure_connection
        attempted = []
        def no_startup_database(*args, **kwargs):
            attempted.append(True)
            raise ValueError("startup database work must move into the protected migration transaction")
        BaseDatabaseWrapper.ensure_connection = no_startup_database
        try:
            django.setup()
        finally:
            BaseDatabaseWrapper.ensure_connection = connect
        if attempted or threading.active_count() != 1:
            raise ValueError("database access and background threads during startup must be replanned before migrating")
        planfile.with_name("ready").write_text("startup completed without live credentials")
        db = json.loads(sys.stdin.readline())
        from django.db import connections
        connections.close_all()
        connections["default"].settings_dict.update(db)
        os.environ.update({"ROUH_DB_" + k: str(v) for k, v in db.items()})
    else:
        django.setup()
    from django.core.management import call_command
    from django.db import connection, transaction
    from django.db.migrations.executor import MigrationExecutor

    plan = json.loads(planfile.read_text())
    q = connection.ops.quote_name

    def parts(table):
        return table.split(".", 1) if "." in table else ("public", table)

    def relation(table):
        return ".".join(q(p) for p in parts(table))

    def tables():
        with connection.cursor() as c:
            c.execute("SELECT schemaname,tablename FROM pg_tables "
                      "WHERE schemaname NOT IN ('pg_catalog','information_schema') AND schemaname NOT LIKE 'pg_%' "
                      "ORDER BY schemaname,tablename")
            return [t if s == "public" else s + "." + t for s, t in c.fetchall()]

    def columns(table):
        with connection.cursor() as c:
            c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=%s "
                      "AND table_name=%s ORDER BY ordinal_position", list(parts(table)))
            return [r[0] for r in c.fetchall()]

    def rows(table, cols):
        hashes = Counter()
        with connection.cursor() as c:
            c.execute("SELECT ROW(" + ",".join(q(x) for x in cols) + ")::text FROM " + relation(table))
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
                c.execute("LOCK TABLE " + ",".join(relation(t) for t in names) + " IN SHARE MODE")
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
            if not old_rows and (new not in after_tables or not set(newcols) <= set(columns(new))):
                result["tables"][old] = {"destination": new, "before": 0, "after": 0, "preserved": True}
                continue
            if new not in after_tables or not set(newcols) <= set(columns(new)):
                raise ValueError(f"{old}: existing data has no destination in the migration plan")
            new_rows = rows(new, newcols)
            if old_rows - new_rows:
                raise ValueError(f"{old}: the migration lost or changed existing memory")
            result["tables"][old] = {"destination": new, "before": sum(old_rows.values()),
                                    "after": sum(new_rows.values()), "preserved": True}
        destinations = {r["destination"] for r in result["tables"].values()}
        for new in after_tables:
            if new in destinations:
                continue
            with connection.cursor() as c:
                c.execute("SELECT count(*) FROM " + relation(new))
                count = c.fetchone()[0]
            result["tables"][new] = {"destination": new, "before": 0, "after": count,
                                     "preserved": True, "new": True}
        call_command("check", verbosity=0)
    # Preservation was proved after the migration while writer locks still held. Once
    # COMMIT releases them, sessions and memory may legitimately change. Read committed
    # counts back without treating a person's subsequent edit as migration data loss;
    # the parent also proves the actual result on a fresh, consistent database copy.
    with transaction.atomic():
        with connection.cursor() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        committed_tables = tables()
        for old, item in result["tables"].items():
            destination = item["destination"]
            if destination not in committed_tables:
                if item["before"] or item.get("new"):
                    raise RuntimeError(f"{old}: the committed migration is missing its destination")
                item["committed_after"] = 0
                continue
            with connection.cursor() as c:
                c.execute("SELECT count(*) FROM " + relation(destination))
                item["committed_after"] = c.fetchone()[0]
    planfile.with_name("counts.json").write_text(json.dumps(result))
