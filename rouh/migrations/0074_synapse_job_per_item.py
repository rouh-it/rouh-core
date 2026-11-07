"""An item's unfinished jobs, indexed (card 1125, change 5, 4 October 2026).

The queue now asks, for every job it would claim, whether the same item has an older job waiting or
one running, so an item's model part never runs twice at once; and a job asked for again while the
same one waits is that job (`ingest.enqueue`).
"""
from django.db import migrations

SCHEMA = r"""
CREATE INDEX IF NOT EXISTS job_item_open ON synapse.job (dataset_id, item_id, kind) WHERE done_at IS NULL;
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.job_item_open;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0073_synapse_link_lookups")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
