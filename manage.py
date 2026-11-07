#!/usr/bin/env python
"""Django's command line for Rouh.

    uv run manage.py migrate                    the schema, in PostgreSQL
    uv run manage.py account add alex --generate
    uv run manage.py import_sqlite              the data Rouh kept before 23 September 2026
    uv run manage.py predeploy                  what the deploy runs before a restart
"""
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rouh.project.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
