"""Earlier key facts kept beside the current ones, so a run can be scored against either.

Petar, 4 October 2026, by voice: every improvement gets an evaluation run of its
own, so we know which one gave the result. Rewording a question's key facts is
one such improvement, and its baseline needs the facts as they were. They are
kept here by name (`{"v1": [...]}`), never overwritten by a later rewrite, and a
run picks them with the `key_facts` number; `facts` stays what the set holds now.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.eval_question ADD COLUMN IF NOT EXISTS facts_sets jsonb NOT NULL DEFAULT '{}'::jsonb;
"""

UNDO = r"""
ALTER TABLE synapse.eval_question DROP COLUMN IF EXISTS facts_sets;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0071_synapse_scale")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
