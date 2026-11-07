"""Gmail kept in Synapse Master, all the time (card 1163, 5 October 2026; `rouh/synapse/gmailsync.py`).

`synapse.mail_sync` is the setting and the state together: one row per Master dataset and inbox
it keeps, with where its history was read to, its backfill's page token, its watch and its last
reconciliation. `enabled` is the setting: `manage.py synapse_mail add|remove` changes it.

It starts with Rouh's own inbox, the Google connection of each Master's owner, and with
nothing else: the owner's own inbox is added later by `synapse_mail add`.

The index finds a message's job still waiting by its key, so the same email is never queued twice
however many times Gmail's history, the backfill and the nightly check name it.
"""
from django.db import migrations

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS synapse.mail_sync (
    dataset_id uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
    inbox text NOT NULL,
    enabled boolean NOT NULL DEFAULT true,
    added_at timestamptz NOT NULL DEFAULT now(),
    added_by text NOT NULL DEFAULT '',
    history_id text NOT NULL DEFAULT '',
    last_push_at timestamptz,
    last_history_at timestamptz,
    last_history_ok_at timestamptz,
    last_history_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    history_error text NOT NULL DEFAULT '',
    history_failures integer NOT NULL DEFAULT 0,
    backfill_state text NOT NULL DEFAULT '',
    backfill_token text NOT NULL DEFAULT '',
    backfill_listed integer NOT NULL DEFAULT 0,
    backfill_started_at timestamptz,
    backfill_listed_at timestamptz,
    backfill_error text NOT NULL DEFAULT '',
    watch_by text NOT NULL DEFAULT '',
    watch_expires_at timestamptz,
    watch_renewed_at timestamptz,
    watch_error text NOT NULL DEFAULT '',
    last_reconcile_at timestamptz,
    reconcile jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_id, inbox)
);
CREATE INDEX IF NOT EXISTS job_mail_key ON synapse.job (dataset_id, kind, (payload->>'key'))
    WHERE done_at IS NULL AND kind IN ('mail_add', 'mail_delete', 'mail_labels');

INSERT INTO synapse.mail_sync (dataset_id, inbox, added_by)
SELECT d.id, lower(g.google_email), 'migration 0081: Rouh''s own inbox'
FROM synapse.dataset d JOIN google_connections g ON g.user_id = d.user_id AND g.org_id = d.org_id
WHERE d.master AND coalesce(g.google_email, '') <> ''
ON CONFLICT DO NOTHING;
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.job_mail_key;
DROP TABLE IF EXISTS synapse.mail_sync;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0080_contacts_into_master")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
