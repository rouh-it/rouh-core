"""Joins the kept 0228 step back into the one chain of migrations.

0229 now follows 0227 directly, so an installation that has already run
everything up to here runs only the empty 0228 step and this one, and a new
installation runs them all in order.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0228_chat_links_kept"),
        ("rouh", "0236_birth_no_advanced_recovery"),
    ]

    operations = []
