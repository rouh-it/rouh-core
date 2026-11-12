#!/usr/bin/env python
"""Django's command line for Rouh.

    uv run manage.py migrate                    the schema, in PostgreSQL
    uv run manage.py account add alex --generate
    uv run manage.py import_sqlite              the data Rouh kept before 23 September 2026
    uv run manage.py predeploy                  what the deploy runs before a restart
"""
import os
import sys


#: The commands that make or change the schema, which run before the keys' table may exist.
SCHEMA = {"migrate", "makemigrations", "showmigrations", "sqlmigrate", "predeploy", "check", "help"}


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rouh.project.settings")
    from django.core.management import execute_from_command_line

    if len(sys.argv) > 1 and sys.argv[1] not in SCHEMA:
        # The keys the owner set in Settings, Keys, for a command run in its own process, as the
        # server has them (`rouh/service_keys.py`). Never for the schema's own commands.
        import django

        django.setup()
        try:
            from rouh import service_keys

            service_keys.start()
        except Exception:  # noqa: BLE001 - a command runs with the settings file's alone
            pass

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
