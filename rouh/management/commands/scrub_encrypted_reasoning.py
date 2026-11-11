"""Remove old private reasoning payloads from the model request log.

Rouh's core runs this scrub by itself, a few minutes after it starts, in small
batches and from where it last got to, and then VACUUMs both tables
(`rouh/reasoning_scrub.py`); a job asks it to start sooner, or how far it has
got, with ``core_command`` (`rouh/core_commands.py`). Nobody has to type this.

    python manage.py scrub_encrypted_reasoning --status    the core's scrub so far

This is an explicit maintenance command. It is never called during startup or
by a migration. Each bounded batch commits independently and can safely be
repeated after interruption. Optional PostgreSQL VACUUM runs separately, with
ordinary table locks, and never uses VACUUM FULL.
"""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def sizes() -> dict[str, int]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_database_size(current_database())")
        result = {"database": int(cursor.fetchone()[0])}
        for table in ("llm_requests", "llm_pieces"):
            cursor.execute("SELECT pg_total_relation_size(%s::regclass)", (table,))
            result[table] = int(cursor.fetchone()[0])
    return result


class Command(BaseCommand):
    help = "Scrub encrypted reasoning and signatures from stored model log rows."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=2000,
                            help="rows per short transaction (1 to 5000; default 2000)")
        parser.add_argument("--pause", type=float, default=0.1,
                            help="seconds to sleep between batches (default 0.1)")
        parser.add_argument("--after-request-id", type=int, default=0,
                            help="resume after the last reported request id")
        parser.add_argument("--after-piece-hash", default="",
                            help="resume after the last reported piece hash")
        parser.add_argument("--vacuum", action="store_true",
                            help="after scrubbing, run ordinary VACUUM on both log tables")
        parser.add_argument("--status", action="store_true",
                            help="only say how far the core's own scrub has got; changes nothing")

    def handle(self, *args, batch_size=2000, pause=0.1, after_request_id=0,
               after_piece_hash="", vacuum=False, status=False, **options):
        from rouh.llmlog import scrub_historical_reasoning

        if status:
            from rouh import reasoning_scrub

            self.stdout.write(reasoning_scrub.describe())
            return

        if not 1 <= batch_size <= 5000:
            raise CommandError("--batch-size must be between 1 and 5000")
        if not 0 <= pause <= 60:
            raise CommandError("--pause must be between 0 and 60 seconds")
        if after_request_id < 0:
            raise CommandError("--after-request-id must not be negative")
        before = sizes() if vacuum else None

        def progress(stage, cursor_value, count, scanned, report):
            self.stdout.write(
                f"{stage}: batch={count:,}, cursor={cursor_value}, "
                f"scanned={scanned[stage]:,}, scrubbed="
                f"requests={report['request_rows']:,}, pieces={report['piece_rows']:,}"
            )
            self.stdout.flush()

        report = scrub_historical_reasoning(batch_size=batch_size, pause=pause,
                                            after_request_id=after_request_id,
                                            after_piece_hash=after_piece_hash,
                                            progress=progress)
        self.stdout.write("scrub complete: " + json.dumps(report, sort_keys=True))
        self.stdout.flush()
        if not vacuum:
            return
        if not connection.get_autocommit():
            raise CommandError("ordinary VACUUM requires autocommit")
        with connection.cursor() as cursor:
            for table in ("llm_requests", "llm_pieces"):
                cursor.execute(f'VACUUM "{table}"')
                self.stdout.write(f"VACUUM completed: {table}")
                self.stdout.flush()
        after = sizes()
        self.stdout.write("before sizes: " + json.dumps(before, sort_keys=True))
        self.stdout.write("after sizes: " + json.dumps(after, sort_keys=True))
