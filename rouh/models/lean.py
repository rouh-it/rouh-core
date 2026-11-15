"""What this Rouh keeps and runs: its preset, the owner's own choices and the limits confirmed
for deleting old records (`rouh/lean.py`, Anatomy, Meta, What Rouh keeps and runs).

The defaults are in the code (`lean.ITEMS`, `lean.PRESETS`); these rows hold only what this
Rouh has chosen itself, so an update that changes a default reaches every Rouh that has not
changed that row. Every row is the organisation's (AGENTS.md, "Whose data is it")."""
from django.db import models


class LeanState(models.Model):
    """The organisation's preset, and when the retention sweep last ran."""

    org_id = models.TextField(primary_key=True)
    #: installed, developer or creator (`lean.PRESETS`).
    preset = models.TextField()
    changed_by = models.TextField(blank=True, default="")
    updated_at = models.FloatField(default=0)
    swept_at = models.FloatField(default=0)

    class Meta:
        db_table = "lean_state"


class LeanChoice(models.Model):
    """One item the organisation set itself, over its preset. No row: the preset's value."""

    pk = models.CompositePrimaryKey("org_id", "item")
    org_id = models.TextField()
    item = models.TextField()
    #: A job: off, on or one of its own modes. A record: off, keep or forever.
    mode = models.TextField()
    #: Days (or copies) for keep; null otherwise.
    days = models.IntegerField(null=True, blank=True)
    by = models.TextField(blank=True, default="")
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "lean_choice"


class LeanApplied(models.Model):
    """The limit the daily sweep deletes beyond: raised at once, lowered only once the owner
    pressed to confirm what would go (or nothing would). No row: nothing is ever deleted."""

    pk = models.CompositePrimaryKey("org_id", "item")
    org_id = models.TextField()
    item = models.TextField()
    mode = models.TextField()
    days = models.IntegerField(null=True, blank=True)
    #: Everything older than this (seconds since 1970) is already gone; 0 when never swept.
    done_before = models.FloatField(default=0)
    by = models.TextField(blank=True, default="")
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "lean_applied"
