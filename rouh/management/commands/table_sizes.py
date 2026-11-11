"""``python manage.py table_sizes``: the database's size and its largest tables. Only reads.

    python manage.py table_sizes             the 20 largest tables
    python manage.py table_sizes --most 50   more of them
    python manage.py table_sizes --json      the same, as JSON

A job asks the core for it with ``core_command table_sizes`` (`rouh/core_commands.py`), because a
job never reaches the live database itself.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


def _gb(n: int) -> str:
    return f"{n / 1e9:,.2f} GB" if n >= 1e8 else f"{n / 1e6:,.1f} MB"


def measure(most: int = 20) -> dict:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), pg_database_size(current_database())")
        name, size = cursor.fetchone()
        cursor.execute("""
            SELECT CASE WHEN n.nspname = 'public' THEN c.relname ELSE n.nspname || '.' || c.relname END,
                   COALESCE(s.n_live_tup, GREATEST(c.reltuples, 0))::bigint,
                   pg_total_relation_size(c.oid), pg_relation_size(c.oid),
                   COALESCE(pg_total_relation_size(NULLIF(c.reltoastrelid, 0)), 0),
                   pg_indexes_size(c.oid),
                   COALESCE(s.n_dead_tup, 0), s.last_vacuum, s.last_autovacuum
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE c.relkind = 'r' AND n.nspname NOT IN ('pg_catalog', 'information_schema')
            ORDER BY pg_total_relation_size(c.oid) DESC
            LIMIT %s""", (most,))
        tables = [{"table": r[0], "rows_estimate": int(r[1]), "total": int(r[2]),
                   "table_only": int(r[3]), "toast": int(r[4]), "indexes": int(r[5]),
                   "dead_rows": int(r[6]),
                   "last_vacuum": (r[7] or r[8]).isoformat(timespec="minutes") if (r[7] or r[8]) else ""}
                  for r in cursor.fetchall()]
    return {"database": name, "size": int(size), "tables": tables}


class Command(BaseCommand):
    help = "The database's size and its largest tables. Only reads."

    def add_arguments(self, parser):
        parser.add_argument("--most", type=int, default=20, help="how many tables (default 20)")
        parser.add_argument("--json", action="store_true", help="as JSON")

    def handle(self, *args, most=20, json=False, **options):  # noqa: A002 - the option's name
        got = measure(max(1, min(200, most)))
        if json:
            import json as _json

            self.stdout.write(_json.dumps(got, indent=1))
            return
        self.stdout.write(f"Database {got['database']}: {_gb(got['size'])}")
        for t in got["tables"]:
            self.stdout.write(
                f"{t['table']}: {_gb(t['total'])} in all (table {_gb(t['table_only'])}, TOAST "
                f"{_gb(t['toast'])}, indexes {_gb(t['indexes'])}), about {t['rows_estimate']:,} live rows, "
                f"{t['dead_rows']:,} dead" + (f", vacuumed {t['last_vacuum']}" if t["last_vacuum"] else ""))
