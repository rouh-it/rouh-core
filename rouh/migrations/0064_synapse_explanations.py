"""Synapse's explanations: what each label on its page means (`rouh/synapse/explain.py`).

Petar, 3 October 2026 (fr_bc51d0de9b2b): an (i) beside every section, title and
attribute on the Synapse page, opening a generic explanation of it. The first
explanation of a label in a place is written once by the helper model and kept
here, one row per organisation, so the same label says the same thing on every
dataset; nothing of any dataset is in it.
"""
from django.db import migrations

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS synapse.explanation (
  org_id   text NOT NULL,
  key      text NOT NULL,
  label    text NOT NULL,
  place    text NOT NULL DEFAULT '',
  text     text NOT NULL,
  model    text NOT NULL DEFAULT '',
  made_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, key)
);
"""

UNDO = "DROP TABLE IF EXISTS synapse.explanation;"


class Migration(migrations.Migration):

    dependencies = [("rouh", "0063_word_review")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
