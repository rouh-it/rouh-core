"""The Django project Rouh is served by: settings, addresses, the ASGI door.

`setup` is for the few modules a person runs with ``python -m`` rather than
through ``manage.py``: they call it before importing anything that reads the
database, and inside the server, where Django is already set up, it does
nothing.
"""
from __future__ import annotations

import os


def setup() -> None:
    """Django, ready, for a command run outside manage.py and outside the server."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "rouh.project.settings")
    from django.apps import apps

    if apps.ready or apps.loading:
        return
    import django

    django.setup()
