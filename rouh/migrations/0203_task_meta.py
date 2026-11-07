"""A task's meta, kept in the task's row (`rouh/taskmeta.py`).

Petar, 22 October 2026, of a task's steps, tags and question: "should not be in this file,
should be in DB". So a task keeps, beside its status and its summary, its steps' titles and groups,
its arrows, its tags, a goal's blocks, a waiting task's question and the replies he sends
himself, as one JSON value, and every change to it is a row of `task_change`.
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0202_capability_grants'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='meta',
            field=models.JSONField(blank=True, default=None, null=True),
        ),
        migrations.RemoveConstraint(
            model_name='taskchange',
            name='task_change_field_known',
        ),
        migrations.AddConstraint(
            model_name='taskchange',
            constraint=models.CheckConstraint(
                condition=Q(field__in=('status', 'summary', 'origin', 'meta')),
                name='task_change_field_known'),
        ),
    ]
