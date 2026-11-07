"""Synapse's passages are numbered 1, 2, 3 in their item, and the X-ray passage has no number.

3 October 2026, Petar: an item's text pieces were numbered from 0, and its X-ray
passage was given 1000 to set it apart. A pasted book of more than a thousand
pieces runs into that number, and a number far above the others is no way to
say "a different kind". So `seq` now means only the order of the item's text
pieces, starting at 1 with no ceiling, and the X-ray passage is marked by
`from_xray` alone, with no seq.

Every existing passage is renumbered, in every dataset: text pieces become
1..n in the order they had, and every X-ray passage loses its seq. Then the
database holds the scheme itself: a text piece has a seq of 1 or more and an
X-ray passage has none, no two text pieces of an item share a seq, and an item
has at most one X-ray passage. Should an item ever have held two X-ray
passages, the newest is kept, as `write_xray` would have kept it.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.passage ALTER COLUMN seq DROP NOT NULL;
DELETE FROM synapse.passage p USING synapse.passage q
 WHERE p.from_xray AND q.from_xray AND p.dataset_id = q.dataset_id AND p.item_id = q.item_id AND p.id < q.id;
UPDATE synapse.passage SET seq = NULL WHERE from_xray;
UPDATE synapse.passage p SET seq = n.seq
  FROM (SELECT id, row_number() OVER (PARTITION BY dataset_id, item_id ORDER BY seq, id) AS seq
          FROM synapse.passage WHERE NOT from_xray) n
 WHERE p.id = n.id AND p.seq IS DISTINCT FROM n.seq;
ALTER TABLE synapse.passage ADD CONSTRAINT passage_seq_kind
  CHECK ((from_xray AND seq IS NULL) OR (NOT from_xray AND seq >= 1));
CREATE UNIQUE INDEX passage_text_seq ON synapse.passage (dataset_id, item_id, seq) WHERE NOT from_xray;
CREATE UNIQUE INDEX passage_one_xray ON synapse.passage (dataset_id, item_id) WHERE from_xray;
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.passage_one_xray;
DROP INDEX IF EXISTS synapse.passage_text_seq;
ALTER TABLE synapse.passage DROP CONSTRAINT IF EXISTS passage_seq_kind;
UPDATE synapse.passage SET seq = seq - 1 WHERE NOT from_xray;
UPDATE synapse.passage SET seq = 1000 WHERE from_xray;
ALTER TABLE synapse.passage ALTER COLUMN seq SET NOT NULL;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0066_synapse_people")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
