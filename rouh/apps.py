"""Rouh, as a Django application.

The package is the whole of Rouh: the models, the migrations, the templates,
the views under `web/`, and every module that does the work - the model loop,
the voice, the stores, the tools. Django is what serves it and what keeps its
data; what Rouh does is still said by those modules.
"""
from django.apps import AppConfig


class RouhConfig(AppConfig):
    name = "rouh"
    label = "rouh"
    verbose_name = "Rouh"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # One database connection per thread, also in a thread running an event loop
        # (`rouh/project/db/base.py`, task 137).
        from .project.db.base import one_connection_per_thread

        one_connection_per_thread()

        from django.db.models.signals import post_migrate

        post_migrate.connect(_synapse_bg_words, sender=self, dispatch_uid="rouh.synapse_bg_words")


def _synapse_bg_words(using="default", **_):
    """Synapse's Bulgarian word forms, made again after every `migrate` if they are missing.

    Every Synapse search runs `to_tsvector('synapse.bg', ...)`. A database copied back from a
    dump (the creator switch's way back, 31 October 2026) came back without it, and every
    synapse_query failed until somebody noticed (fr_ff415b038226). Migration 0222 mended it
    once; a migration never runs twice, so this runs its same few lines on every `migrate`,
    which both the server's deploy and a container's start do. It changes nothing where they
    are there.
    """
    import importlib

    from django.db import connections

    connection = connections[using]
    if connection.vendor != "postgresql":
        return
    ensure = importlib.import_module("rouh.migrations.0222_synapse_bg_again").ENSURE
    with connection.cursor() as cursor:
        cursor.execute(ensure)
