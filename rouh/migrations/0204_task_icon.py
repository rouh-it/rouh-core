"""A task's icon, as a Notion page has one (`rouh/taskicons.py`).

Petar, 22 October 2026 (fr_0ac90fe38f73): "I would love it if each task has its own emoji ...
should be stored in db, not in files." One emoji, or the file name of a small picture uploaded
for it, kept beside its title; every change is a row of `task_change`. Every task starts with
none, and Rouh's icon picker gives each one when it next starts (`taskicons.Picker`).
"""
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0203_task_meta'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='icon',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
        migrations.RemoveConstraint(
            model_name='taskchange',
            name='task_change_field_known',
        ),
        migrations.AddConstraint(
            model_name='taskchange',
            constraint=models.CheckConstraint(
                condition=Q(field__in=('status', 'summary', 'origin', 'meta', 'icon')),
                name='task_change_field_known'),
        ),
    ]
