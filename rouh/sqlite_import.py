"""Everything Rouh kept in SQLite, copied into PostgreSQL, once.

Until 23 September 2026 every store kept its own tables in one SQLite file,
`rouh.sqlite3` in the data directory. This is the move out of it: every row of
every table that still means something, into the Django models of the same
name (`rouh/models/`), in one transaction, so it either all arrives or none
of it does. It runs from `manage.py import_sqlite`, and from the deploy that
switched Rouh to Django (`manage.py predeploy`), with the old service stopped
so nothing is written to the file while it is read.

What it takes, and what it leaves:

- **Taken, as they are:** every table a model names, column by column, with
  each value turned into the column's type (SQLite's 0 and 1 become false and
  true, a number in a text column becomes its text). Ids are kept, so user 1,
  chat `general` and card 37 are the same things afterwards, and every
  sequence is moved past the highest id it was given.
- **The accounts**, into Django's: the same id, name and email, the password
  hash kept in the form `rouh.accounts.LegacyScryptHasher` reads, so the old
  password still works until the handover replaces it (`rouh/handover.py`).
  The organisation's administrator becomes the Django admin's too.
- **Left behind on purpose:** the old sign-ins and the key that signed them
  (everybody signs in once more, which is expected), the refused attempts and
  the Google consent states (both short-lived), and SQLite's own full-text
  tables - PostgreSQL keeps its own index of the same words, made from the
  bodies that are copied (`ContentFile.search`).
- **A row that points at nothing** where PostgreSQL enforces the link - a
  message whose chat is gone, a version whose artifact is gone - is left out,
  as SQLite's own ON DELETE would have left it out, and counted in what it
  says. A pointer that SQLite would have set to null is set to null.

It is marked done in `app_state` (`MARKER`), and asked again it says so and
does nothing. The SQLite file is only ever opened read-only, and is left
exactly where it was: it is the backup of the moment before the move.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import time

log = logging.getLogger("rouh.import")

#: The key in `app_state` that says the move has happened, and how it went.
MARKER = "imported_from_sqlite"

#: Tables that are not copied, and why, in a word each.
LEFT_BEHIND = {
    "auth_sessions": "old sign-ins",
    "auth_keys": "the old cookie key",
    "auth_failures": "short-lived",
    "google_oauth_states": "short-lived",
    "sqlite_sequence": "SQLite's own",
    "content_search": "SQLite's full-text index",
    "content_search_config": "SQLite's full-text index",
    "content_search_content": "SQLite's full-text index",
    "content_search_data": "SQLite's full-text index",
    "content_search_docsize": "SQLite's full-text index",
    "content_search_idx": "SQLite's full-text index",
}

#: Links PostgreSQL enforces, and what SQLite's ON DELETE did about a missing
#: target: "drop" the row, or "null" the pointer. (table, column, target table)
ENFORCED = [
    ("message", "chat_id", "chat", "drop"),
    ("artifact_version", "artifact_id", "artifact", "drop"),
    ("artifact_version", "made_by_run", "run", "null"),
    ("run", "parent_run_id", "run", "null"),
    ("askai_messages", "thread_id", "askai_threads", "drop"),
]


class ImportFailed(RuntimeError):
    """The move did not happen, and nothing of it was kept."""


def done() -> dict | None:
    """What the move said when it happened, or None if it has not."""
    from .models import AppState

    row = AppState.objects.filter(key=MARKER).first()
    if row is None:
        return None
    try:
        return json.loads(row.value)
    except ValueError:
        return {"said": row.value}


def pending(path: str) -> bool:
    """Whether there is a file to move and it has not been moved yet."""
    return bool(path) and os.path.isfile(path) and done() is None


def _open(path: str) -> sqlite3.Connection:
    """The file, read-only. A lock the old process left is waited on, not broken."""
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def _as(field, value):
    """One SQLite value, as what the PostgreSQL column holds."""
    from django.db import models

    if value is None:
        return None
    if isinstance(field, models.BooleanField):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "t")
        return bool(value)
    if isinstance(field, (models.BigIntegerField, models.IntegerField, models.AutoField,
                          models.BigAutoField, models.SmallIntegerField)):
        return int(value)
    if isinstance(field, models.FloatField):
        return float(value)
    if isinstance(field, models.TextField) or isinstance(field, models.CharField):
        if isinstance(value, bytes):
            value = value.decode("utf-8", "replace")
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        # PostgreSQL's text cannot hold a NUL, and SQLite's could: one indexed
        # file on the server had one. It is dropped; nothing reads a NUL.
        return str(value).replace("\x00", "")
    return value


def _columns(model) -> list:
    """The model's real columns: everything but a generated one."""
    from django.db import models

    return [f for f in model._meta.concrete_fields
            if not isinstance(f, models.GeneratedField)]


def _tables(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _column_names(db: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}


def run(path: str, *, keep: bool = True) -> dict:
    """Move everything, in one transaction. ``keep=False`` rolls it back at the
    end, which is how the move is proved against a copy before it is done.

    Returns what it did: rows per table, rows left out and why.
    """
    from django.apps import apps
    from django.core.management.color import no_style
    from django.db import connection, transaction

    from .accounts import legacy_to_django
    from .models import DEFAULT_ORG_ID, AppState, Organisation, User

    if not os.path.isfile(path):
        raise ImportFailed(f"there is no SQLite file at {path}")
    if keep and done() is not None:
        raise ImportFailed("the move has already been done")
    if keep and User.objects.exists():
        raise ImportFailed("PostgreSQL already has accounts in it, so nothing was "
                           "imported over the top of them")

    db = _open(path)
    have = _tables(db)
    said: dict = {"source": path, "tables": {}, "left_out": {}, "left_behind": []}
    started = time.time()

    # Every id that exists, for the enforced links, read before anything moves.
    present = {table: {r[0] for r in db.execute(f'SELECT id FROM "{table}"')}
               for table in {t for _, _, t, _ in ENFORCED} if table in have}

    by_table = {m._meta.db_table: m for m in apps.get_app_config("rouh").get_models()
                if m._meta.managed}

    class _Undo(Exception):
        pass

    try:
        with transaction.atomic():
            with connection.cursor() as cur:
                # Constraints at the end of the transaction, whatever order the
                # tables arrive in.
                cur.execute("SET CONSTRAINTS ALL DEFERRED")

            # --- the organisations and the people, first -------------------------
            if "organisations" in have:
                for row in db.execute("SELECT * FROM organisations"):
                    Organisation.objects.update_or_create(
                        id=row["id"], defaults={"name": row["name"] or "An organisation",
                                                "created_at": float(row["created_at"] or 0)})
            Organisation.objects.get_or_create(
                id=DEFAULT_ORG_ID, defaults={"name": "My organisation",
                                             "created_at": time.time()})
            people = 0
            if "users" in have:
                cols = _column_names(db, "users")
                for row in db.execute("SELECT * FROM users ORDER BY id"):
                    org = (row["org_id"] if "org_id" in cols else "") or DEFAULT_ORG_ID
                    Organisation.objects.get_or_create(
                        id=org, defaults={"name": "An organisation", "created_at": time.time()})
                    admin = bool(row["is_admin"]) if "is_admin" in cols else False
                    joined = dt.datetime.fromtimestamp(float(row["created_at"] or 0),
                                                       tz=dt.timezone.utc)
                    User.objects.create(
                        id=int(row["id"]), username=row["username"],
                        email=row["email"] or "",
                        password=legacy_to_django(row["password_hash"] or ""),
                        date_joined=joined, org_id=org, is_org_admin=admin,
                        # Whoever managed the organisation manages the install.
                        is_staff=admin, is_superuser=admin, is_active=True)
                    people += 1
            said["tables"]["users"] = people

            # --- everything else, table by table ------------------------------
            for table, model in sorted(by_table.items()):
                if table in ("users", "organisations") or table in LEFT_BEHIND:
                    continue
                if table not in have:
                    continue
                cols_there = _column_names(db, table)
                fields = [f for f in _columns(model) if f.column in cols_there]
                missing = [f for f in _columns(model) if f.column not in cols_there]
                rules = [(col, target, how) for t, col, target, how in ENFORCED if t == table]
                rows, dropped = [], 0
                for row in db.execute(f'SELECT * FROM "{table}"'):
                    record = {f.column: _as(f, row[f.column]) for f in fields}
                    skip = False
                    for col, target, how in rules:
                        value = record.get(col)
                        if value is None or value in present.get(target, ()):
                            continue
                        if how == "drop":
                            skip = True
                        else:
                            record[col] = None
                    if skip:
                        dropped += 1
                        continue
                    for f in missing:
                        if f.has_default():
                            record[f.column] = f.get_default()
                    rows.append(record)
                if rows:
                    names = list(rows[0])
                    sql = (f'INSERT INTO "{table}" ({", ".join(chr(34) + n + chr(34) for n in names)})'
                           f' VALUES ({", ".join(["%s"] * len(names))})')
                    with connection.cursor() as cur:
                        cur.executemany(sql, [[r[n] for n in names] for r in rows])
                said["tables"][table] = len(rows)
                if dropped:
                    said["left_out"][table] = dropped

            said["left_behind"] = sorted(t for t in have if t in LEFT_BEHIND)
            unknown = sorted(t for t in have - set(by_table) - set(LEFT_BEHIND)
                             - {"users", "organisations"})
            if unknown:
                said["not_moved"] = unknown

            # --- every sequence past the highest id it was given --------------
            with connection.cursor() as cur:
                for sql in connection.ops.sequence_reset_sql(
                        no_style(), list(by_table.values())):
                    cur.execute(sql)
            said["seconds"] = round(time.time() - started, 2)
            said["at"] = time.time()
            if keep:
                AppState.objects.update_or_create(key=MARKER,
                                                  defaults={"value": json.dumps(said)})
            else:
                raise _Undo()
    except _Undo:
        pass
    except Exception as exc:
        raise ImportFailed(f"{type(exc).__name__}: {exc}") from exc
    finally:
        db.close()
    return said


def stale(path: str) -> bool:
    """Whether the SQLite file was written after it was moved.

    After the move nothing writes it: Rouh reads PostgreSQL, and the import
    only ever opens the file read-only. The one thing that writes it is the
    Rouh from before the move, running again because a deploy was rolled back
    - and then what it wrote since is in the file and nowhere else, so the
    move has to be made again rather than keep what PostgreSQL has.
    """
    said = done()
    if said is None or not os.path.isfile(path):
        return False
    newest = max(os.path.getmtime(p) for p in (path, path + "-wal") if os.path.exists(p))
    return newest > float(said.get("at") or 0) + 60


def forget_everything() -> None:
    """Empty every table the move fills, so it can be made again from the file."""
    from django.apps import apps
    from django.db import connection

    tables = sorted(m._meta.db_table for m in apps.get_app_config("rouh").get_models()
                    if m._meta.managed)
    with connection.cursor() as cur:
        cur.execute("TRUNCATE " + ", ".join(f'"{t}"' for t in tables)
                    + " RESTART IDENTITY CASCADE")
