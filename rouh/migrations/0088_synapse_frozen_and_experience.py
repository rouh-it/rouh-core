"""A frozen benchmark dataset, and attempts kept for the experience (Petar, 5 October 2026).

`synapse.dataset.frozen`: a lab dataset that is a snapshot taken once (`rouh/synapse/snapshot.py`), the
benchmark's "Benchmark: Synapse Master (frozen)". Nothing stores into it, edits it or deletes from it, no sync
touches it, and a nightly run never changes it.

`synapse.attempt.experience` and the outcome `kept_experience`: a change that moves no benchmark number but
makes using Rouh better is kept on its own terms, with the gain it expected written before it was built and
before-and-after evidence from real chat turns (`rouh/synapse/nightly_brief.md`).
"""
from django.db import migrations

SQL = r"""
ALTER TABLE synapse.dataset ADD COLUMN IF NOT EXISTS frozen boolean NOT NULL DEFAULT false;
ALTER TABLE synapse.attempt ADD COLUMN IF NOT EXISTS experience jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE synapse.attempt DROP CONSTRAINT IF EXISTS attempt_outcome_known;
ALTER TABLE synapse.attempt ADD CONSTRAINT attempt_outcome_known CHECK (outcome IN
    ('running', 'kept', 'kept_experience', 'discarded', 'needs_decision', 'failed', 'baseline'));
"""

UNDO = r"""
ALTER TABLE synapse.attempt DROP CONSTRAINT IF EXISTS attempt_outcome_known;
ALTER TABLE synapse.attempt ADD CONSTRAINT attempt_outcome_known CHECK (outcome IN
    ('running', 'kept', 'discarded', 'needs_decision', 'failed', 'baseline'));
ALTER TABLE synapse.attempt DROP COLUMN IF EXISTS experience;
ALTER TABLE synapse.dataset DROP COLUMN IF EXISTS frozen;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0087_synapse_attempts")]

    operations = [migrations.RunSQL(SQL, UNDO)]
