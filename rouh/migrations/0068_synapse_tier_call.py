"""Synapse's tier call: code gathers an item's signals, a model decides its tier (D80).

Petar, 3 October 2026, by voice: code no longer decides an item's tier. Code
gathers every signal it can about the item and a model reads them with its
text and makes the call, for every item, every time, with a one-line reason.

- `tier_by` says who set the tier: `model` (the helper model's tier call),
  `decision` (a decision model, when the helper model could not answer),
  `none` (neither answered, so tier 1 with why), `pending` (the call has not
  returned yet), `xray` (the helper model moved it when it read the item), or
  `code` for every item tiered before this, by D58's rules.
  An item Synapse made itself (a person, a layer, a topic or a rule drawn
  from claims) keeps '' and the tier it was made with.
- `tier_signals` is what code gathered, exactly as the model was shown it, so
  the debugger can show the evidence beside the call.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS tier_by text NOT NULL DEFAULT '';
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS tier_signals jsonb;

UPDATE synapse.item SET tier_by = CASE
    WHEN tier_why LIKE 'the helper model read it%' THEN 'xray'
    WHEN tier_why LIKE 'triage:%' THEN 'decision'
    ELSE 'code' END
WHERE tier_by = '' AND kind NOT IN ('person', 'layer')
  AND NOT (source = 'synapse' AND kind IN ('topic', 'rule'));
"""

UNDO = r"""
ALTER TABLE synapse.item DROP COLUMN IF EXISTS tier_signals;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS tier_by;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0067_synapse_passage_seq")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
