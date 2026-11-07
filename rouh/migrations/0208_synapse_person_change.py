"""Every link and unlink of a person's identifiers, kept with what undoes it (`rouh/synapse/aka.py`).

Petar, 22 October 2026: "give me interface to do that. I am guessing I should be doing this from
contacts card of the person?! also from typing a message like you suggest?" - that being to say which
Slack member, address or name written in a meeting's notes is which of his contacts, as one person.
Each change he makes, on a card or by telling Rouh, is one row here: what it was, in words, who made
it, and `undo`, what was moved, so the change can be taken back exactly (his principles C1 and D1:
every result has a control to correct it, and every version is kept).
"""
from django.db import migrations

FORWARD = """
CREATE TABLE IF NOT EXISTS synapse.person_change (
  id         bigserial PRIMARY KEY,
  scope_id   uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  person     uuid NOT NULL,
  other      uuid,
  action     text NOT NULL CHECK (action IN ('link', 'unlink', 'apart')),
  what       text NOT NULL DEFAULT '',
  by         text NOT NULL DEFAULT '',
  undo       jsonb NOT NULL DEFAULT '{}'::jsonb,
  made_at    timestamptz NOT NULL DEFAULT now(),
  undone_at  timestamptz,
  undone_by  text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS person_change_person ON synapse.person_change (scope_id, person, made_at DESC);
CREATE INDEX IF NOT EXISTS person_change_other ON synapse.person_change (scope_id, other, made_at DESC);
"""

BACKWARD = "DROP TABLE IF EXISTS synapse.person_change;"


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0207_task_numbers_before'),
    ]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
