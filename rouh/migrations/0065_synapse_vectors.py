"""Synapse's vectors move from OpenAI to Voyage AI's voyage-4, safely.

3 October 2026, asked by voice: Synapse's search by meaning is Voyage's, as the
spec's D37 always said, with OpenAI kept for everything generative. Vectors of
two models mean nothing to each other, so a dataset's vectors are always one
model's, named on the dataset (`vec_model`), and search asks in that model and
reads only that model's vectors. Moving a dataset to another model
(`rouh/synapse/vectors.py`) fills a second column beside the first
(`vec_next`), checks it, and swaps the two in one transaction, keeping the old
vectors (`vec_prev`) so the move can be put back. Nothing is deleted.

Every dataset that already has vectors keeps the model they were made with,
so nothing changes for search until somebody moves it; one with none at all
starts on voyage-4.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.dataset ADD COLUMN IF NOT EXISTS vec_model text NOT NULL DEFAULT 'voyage-4';
ALTER TABLE synapse.dataset ADD COLUMN IF NOT EXISTS vec_move jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS vec_next halfvec(1024);
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS next_model text NOT NULL DEFAULT '';
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS vec_prev halfvec(1024);
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS prev_model text NOT NULL DEFAULT '';

UPDATE synapse.dataset d SET vec_model = m.embed_model
FROM (SELECT DISTINCT ON (dataset_id) dataset_id, embed_model
      FROM synapse.passage WHERE vec IS NOT NULL AND embed_model <> ''
      GROUP BY dataset_id, embed_model ORDER BY dataset_id, count(*) DESC) m
WHERE m.dataset_id = d.id;
"""

# Going back puts any moved dataset's old vectors back where search reads
# them before the columns holding them go.
UNDO = r"""
UPDATE synapse.passage SET vec = vec_prev, embed_model = prev_model
WHERE prev_model <> '' AND dataset_id IN (
  SELECT id FROM synapse.dataset WHERE vec_move->>'state' = 'switched');
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS prev_model;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS vec_prev;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS next_model;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS vec_next;
ALTER TABLE synapse.dataset DROP COLUMN IF EXISTS vec_move;
ALTER TABLE synapse.dataset DROP COLUMN IF EXISTS vec_model;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0064_synapse_explanations")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
