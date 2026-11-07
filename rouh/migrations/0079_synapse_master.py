"""Each person's master dataset: the one Rouh itself reads and writes (Petar, 4 October 2026).

`synapse.dataset.master` marks it, at most one per person (`rouh/synapse/master.py`). Nothing is
made here: `manage.py synapse_master make` makes it, from the person's people set.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.dataset ADD COLUMN IF NOT EXISTS master boolean NOT NULL DEFAULT false;
CREATE UNIQUE INDEX IF NOT EXISTS dataset_one_master ON synapse.dataset (org_id, user_id) WHERE master;
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.dataset_one_master;
ALTER TABLE synapse.dataset DROP COLUMN IF EXISTS master;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0078_synapse_pg_search")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
