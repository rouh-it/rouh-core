"""Every rule on the Rules page can be turned off, moved to another group, and says where it came from.

Petar, 29 October 2026: "they need to be in groups", "every rule should be able to be turned of, like the
agents", and "I want to be able to see clearly what was added automatically vs what I added manually". A rule
of the person's keeps all of that in its item's meta already (`rouh/rules.py`); a built-in rule gets the group
it was moved to by hand, and a word of the person's (a pinned line of Synapse's map) gets a meta of its own for
its switch, group, origin and history.
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0219_page_states'),
    ]

    operations = [
        migrations.AddField(
            model_name='builtinrule',
            name='group',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.RemoveConstraint(
            model_name='builtinrulechange',
            name='builtin_rule_change_action_known',
        ),
        migrations.AddConstraint(
            model_name='builtinrulechange',
            constraint=models.CheckConstraint(
                condition=Q(action__in=("seed", "upgrade", "held", "edit", "enable", "disable", "restore", "group")),
                name='builtin_rule_change_action_known'),
        ),
        migrations.RunSQL(
            "ALTER TABLE synapse.map_line ADD COLUMN IF NOT EXISTS meta jsonb NOT NULL DEFAULT '{}'::jsonb",
            "ALTER TABLE synapse.map_line DROP COLUMN IF EXISTS meta",
        ),
    ]
