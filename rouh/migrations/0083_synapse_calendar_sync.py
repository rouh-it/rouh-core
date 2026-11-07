"""Every calendar event kept in Synapse Master, all the time (5 October 2026; `rouh/synapse/calsync.py`).

`synapse.calendar_sync` is the setting and the state together: one row per Master dataset and calendar on
its owner's Google calendar list, made by the sync itself when it finds the calendar (`discover`), with
Google's sync token, the first listing's page token, the last read, and the night's check. `enabled` is
the setting; a calendar shared as free and busy only has a row that says so and is never read.
"""
from django.db import migrations

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS synapse.calendar_sync (
    dataset_id uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
    calendar_id text NOT NULL,
    name text NOT NULL DEFAULT '',
    access text NOT NULL DEFAULT '',
    enabled boolean NOT NULL DEFAULT true,
    on_list boolean NOT NULL DEFAULT true,
    state text NOT NULL DEFAULT '',
    sync_token text NOT NULL DEFAULT '',
    page_token text NOT NULL DEFAULT '',
    listed integer NOT NULL DEFAULT 0,
    listing_started_at timestamptz,
    listed_at timestamptz,
    last_read_at timestamptz,
    last_ok_at timestamptz,
    counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text NOT NULL DEFAULT '',
    failures integer NOT NULL DEFAULT 0,
    last_reconcile_at timestamptz,
    reconcile jsonb NOT NULL DEFAULT '{}'::jsonb,
    added_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, calendar_id)
);
"""

UNDO = "DROP TABLE IF EXISTS synapse.calendar_sync;"


class Migration(migrations.Migration):

    dependencies = [("rouh", "0082_fact_proposal")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
