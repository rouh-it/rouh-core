"""A night of dreaming keeps its plan, so a night cut off by a restart carries on (15 November 2026).

`synapse.dream.plan` is what a night has worked out and must not lose when Rouh stops under it: the seeds and
groups its gather made, the groups already judged and what they found. A night picked up again
(`rouh/synapse/dreaming.py`, `run`) reads it and goes on from there, rather than being called failed. It is
emptied when the night ends; the page never reads it.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.dream ADD COLUMN IF NOT EXISTS plan jsonb NOT NULL DEFAULT '{}'::jsonb;
"""

UNDO = r"""
ALTER TABLE synapse.dream DROP COLUMN IF EXISTS plan;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0249_service_keys")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
