"""Who a task was made for (`rouh/task_origin.py`).

Petar, 15 October 2026: "When other people create tasks through email and telegram. Can we
please separate them from my tasks somehow? I don't want those to pollute my workspace." So a
task keeps, beside its status, who it was made for: nobody said (his own), somebody else and on
which channel, or his own because he said so. Every change to it is a row of `task_change`, as a
status or a summary is, so what was marked, by whom and why can be read back.
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0157_agent_instructions'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='origin',
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
        migrations.RemoveConstraint(
            model_name='taskchange',
            name='task_change_field_known',
        ),
        migrations.AddConstraint(
            model_name='taskchange',
            constraint=models.CheckConstraint(condition=Q(field__in=('status', 'summary', 'origin')),
                                              name='task_change_field_known'),
        ),
    ]
