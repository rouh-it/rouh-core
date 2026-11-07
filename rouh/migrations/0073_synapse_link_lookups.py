"""Two exact lookups link candidates make, indexed (card 1125, change 2, 4 October 2026).

- An item by its source key alone (`ingest.find_by_key`: the email a reply answers, the emails a
  file came on). The unique index starts with the source, which these lookups do not know, so at a
  million items each one read the dataset's whole key index.
- Items by the hash of their file (`meta.sha256`): the same file stored twice, once as an upload
  and once off an email, is found as the same file.
"""
from django.db import migrations

SCHEMA = r"""
CREATE INDEX IF NOT EXISTS item_key ON synapse.item (dataset_id, source_key);
CREATE INDEX IF NOT EXISTS item_sha256 ON synapse.item (dataset_id, (meta->>'sha256')) WHERE meta ? 'sha256';
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.item_sha256;
DROP INDEX IF EXISTS synapse.item_key;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0072_synapse_fact_sets")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
