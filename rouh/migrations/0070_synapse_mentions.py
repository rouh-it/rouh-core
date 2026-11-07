"""People mentioned in an item's text, kept as data on the item (Q21 stays open).

Petar, 4 October 2026, by voice: prepare for a future feature that turns the
people an item's text mentions into person items, without building the
matching or making anyone yet. The X-ray call (still one call, D82) returns
them, code checks their quotes, and they are stored here and nowhere else.

- `mentions` is that answer as checked (`rouh/synapse/mentions.py`): the
  people, the identifiers that are nobody's for sure, and each check. NULL
  means no model read the item for people: an X-ray made before this, or no
  model X-ray at all. It is never a passage, never searched, never resolved
  against the people set, and no identity, person item or link comes from it.
- `mentions_gold` is what an evaluation expects the X-ray to find, for
  Evaluate's precision and recall by name and identifier.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS mentions jsonb;
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS mentions_gold jsonb;
"""

UNDO = r"""
ALTER TABLE synapse.item DROP COLUMN IF EXISTS mentions_gold;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS mentions;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0069_synapse_chat")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
