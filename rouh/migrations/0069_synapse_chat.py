"""Synapse's chats: one for the whole of Synapse, and the forks made off it.

Petar, 4 October 2026 (fr_df883b2daae8): "I should have a chat for the entire
synapse, not for a specific dataset. When I'm in the synapse, the chat on the
left should be the usual synapse chat, and then I can fork anything I want for
different datasets, different features, or anything like that."

- `general` marks a person's one Synapse chat. Its `dataset_id` is the dataset
  open on the screen this minute, or none on the homepage, and its tools act
  on that one (`rouh/synapse/chat.py`).
- Every other row is a fork, written the first time the fork answers: its
  `dataset_id` is the dataset it was made over, and it stays on that one
  whatever the screen shows. A fork made over no dataset keeps none and
  follows the screen like the chat it came off.
- `synapse.dataset.chat_id` stays: the chats each dataset had before this keep
  their conversation and still act on their own dataset, and no new ones are
  made.
"""
from django.db import migrations

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS synapse.chat (
  chat_id     text PRIMARY KEY,
  org_id      text NOT NULL,
  user_id     text NOT NULL,
  general     boolean NOT NULL DEFAULT false,
  dataset_id  uuid REFERENCES synapse.dataset(id) ON DELETE SET NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS chat_general ON synapse.chat (org_id, user_id) WHERE general;
"""

UNDO = r"""
DROP TABLE IF EXISTS synapse.chat;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0068_synapse_tier_call")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
