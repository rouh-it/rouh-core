"""Every attempt to make Synapse better, one row each, and Rouh's own scheduled jobs (5 October 2026).

`synapse.attempt` is the record of the nightly self-improvement loop (`rouh/synapse/improvements.py`,
`rouh/synapse/nightly.py`): what was tried, why, the benchmark's numbers before and after, what it cost and
what became of it. It is a person's: every row carries `org_id` and `user_id`, and every query names both.
The rows that came before the loop are backfilled from task 85's notes, each marked as such.

`reminders.job` names the server job a row of kind `server` starts (the nightly Synapse run is the first),
so Rouh's own scheduled work is listed, paused and moved like any reminder, and never a chat turn.
"""
from django.db import migrations, models

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS synapse.attempt (
    id bigserial PRIMARY KEY,
    org_id text NOT NULL,
    user_id text NOT NULL,
    number integer NOT NULL,
    mode text NOT NULL DEFAULT 'full',
    source text NOT NULL DEFAULT 'nightly',
    notes_ref text NOT NULL DEFAULT '',
    run_id text NOT NULL DEFAULT '',
    started_at timestamptz,
    finished_at timestamptz,
    ideas jsonb NOT NULL DEFAULT '[]'::jsonb,
    chosen text NOT NULL DEFAULT '',
    why_chosen text NOT NULL DEFAULT '',
    earlier text NOT NULL DEFAULT '',
    hypothesis text NOT NULL DEFAULT '',
    changes jsonb NOT NULL DEFAULT '{}'::jsonb,
    benchmark text NOT NULL DEFAULT '',
    benchmark_version text NOT NULL DEFAULT '',
    before jsonb NOT NULL DEFAULT '{}'::jsonb,
    after jsonb NOT NULL DEFAULT '{}'::jsonb,
    spend_usd numeric(10, 4),
    duration_s integer,
    conclusion text NOT NULL DEFAULT '',
    outcome text NOT NULL DEFAULT 'running',
    decision jsonb NOT NULL DEFAULT '{}'::jsonb,
    report text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT attempt_outcome_known CHECK (outcome IN
        ('running', 'kept', 'discarded', 'needs_decision', 'failed', 'baseline')),
    CONSTRAINT attempt_number_once UNIQUE (org_id, user_id, number)
);
CREATE INDEX IF NOT EXISTS attempt_whose_newest ON synapse.attempt (org_id, user_id, number DESC);
"""

UNDO = "DROP TABLE IF EXISTS synapse.attempt;"


class Migration(migrations.Migration):

    dependencies = [("rouh", "0086_telegram_links")]

    operations = [
        migrations.RunSQL(SCHEMA, UNDO),
        migrations.AddField(
            model_name="reminder",
            name="job",
            field=models.TextField(blank=True, default=""),
        ),
    ]
