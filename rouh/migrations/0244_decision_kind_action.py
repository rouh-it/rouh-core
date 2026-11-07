"""Actions beside decisions (`rouh/actions.py`, Petar, 7 November 2026): a hands-on step only
the person can do is kept in the same record as a decision, with the same number and the same
one way back, and told apart by `kind`; `action` holds what its own page shows (what to do, the
steps, how Rouh checks, the story so far) and what the person did there (steps ticked, questions
asked). Every row there is starts as "" (not read yet), and the desk reads the open ones once.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0243_incubator_gist'),
    ]

    operations = [
        migrations.AddField(model_name='decision', name='kind',
                            field=models.TextField(blank=True, default='', db_default='')),
        migrations.AddField(model_name='decision', name='action',
                            field=models.JSONField(default=dict, db_default={})),
        migrations.AddIndex(model_name='decision',
                            index=models.Index(fields=['org_id', 'user_id', 'kind', 'status'],
                                               name='decisions_kind')),
    ]
