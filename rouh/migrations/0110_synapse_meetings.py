"""Every meeting of the meeting library kept in Synapse Master (9 October 2026; `rouh/synapse/meetings.py`).

- **A passage can be part of something other than the item's own text** (`part`). An item's text
  pieces are part '' and numbered 1, 2, 3 as before; a meeting's transcript passages are part
  'transcript' and numbered 1, 2, 3 among themselves, so a summary that grows by a passage never
  collides with them. `sha256` is the hash of a passage's text, so an edit embeds again only the
  passages whose words changed, and `meta` says where in the meeting a passage is (its segment ids,
  first and last millisecond, its speakers). The X-ray passage stays as it was: no seq, at most one.
- **`synapse.meeting_sync`**: one row per Master that keeps the library, with the last change it read
  (`since_seq`), the backfill, the last poll, the last webhook, the night's check, and what happened lately.
- **`synapse.meeting_queue`**: the meetings heard of and not yet read again, one row each, with the
  highest revision heard and when it is due: at once for a meeting ready for the first time, ten
  minutes after its last change for one already kept.
- **`synapse.meeting_hook`**: the signatures of the webhook messages already taken, so one sent again
  is refused.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS part text NOT NULL DEFAULT '';
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS sha256 text NOT NULL DEFAULT '';
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS meta jsonb;
DROP INDEX IF EXISTS synapse.passage_text_seq;
CREATE UNIQUE INDEX passage_text_seq ON synapse.passage (dataset_id, item_id, part, seq) WHERE NOT from_xray;

CREATE TABLE IF NOT EXISTS synapse.meeting_sync (
    dataset_id uuid PRIMARY KEY REFERENCES synapse.dataset(id) ON DELETE CASCADE,
    enabled boolean NOT NULL DEFAULT true,
    since_seq bigint NOT NULL DEFAULT 0,
    backfill_state text NOT NULL DEFAULT '',
    backfill_offset integer NOT NULL DEFAULT 0,
    backfill_started_at timestamptz,
    backfill_done_at timestamptz,
    backfill jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_poll_at timestamptz,
    last_poll_ok_at timestamptz,
    last_event_at timestamptz,
    last_check_at timestamptz,
    check_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    recent jsonb NOT NULL DEFAULT '[]'::jsonb,
    error text NOT NULL DEFAULT '',
    failures integer NOT NULL DEFAULT 0,
    added_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS synapse.meeting_queue (
    dataset_id uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
    meeting_id text NOT NULL,
    revision integer,
    state text NOT NULL DEFAULT '',
    heard_by text NOT NULL DEFAULT '',
    first_heard_at timestamptz NOT NULL DEFAULT now(),
    heard_at timestamptz NOT NULL DEFAULT now(),
    heard integer NOT NULL DEFAULT 1,
    due_at timestamptz NOT NULL DEFAULT now(),
    tries integer NOT NULL DEFAULT 0,
    error text NOT NULL DEFAULT '',
    PRIMARY KEY (dataset_id, meeting_id)
);
CREATE INDEX IF NOT EXISTS meeting_queue_due ON synapse.meeting_queue (due_at);

CREATE TABLE IF NOT EXISTS synapse.meeting_hook (
    digest text PRIMARY KEY,
    seen_at timestamptz NOT NULL DEFAULT now()
);
"""

UNDO = r"""
DROP TABLE IF EXISTS synapse.meeting_hook;
DROP TABLE IF EXISTS synapse.meeting_queue;
DROP TABLE IF EXISTS synapse.meeting_sync;
DROP INDEX IF EXISTS synapse.passage_text_seq;
DELETE FROM synapse.passage WHERE part <> '';
CREATE UNIQUE INDEX passage_text_seq ON synapse.passage (dataset_id, item_id, seq) WHERE NOT from_xray;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS meta;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS sha256;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS part;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0109_reminder_titles")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
