"""Drafts learn your edits, recorded only (`rouh/draft_edits.py`, mutation request 2).

Petar, 16 October 2026: "We keep only the recording part of this feature. Don't modify
responses. For now we will log changes and one day when we have hundreds of changes we can run
an analysis". So every edit he makes to a drafted email before Send is a row of its own,
`draft_edits`, kept whole and never cut to the newest eight, and nothing puts them in a prompt.
The newest eight the first version kept in the user setting `draft_edits_kept` are moved into
the table, oldest first, and the setting is deleted.
"""
import json

from django.db import migrations, models


def _moved(apps, schema_editor):
    UserSetting = apps.get_model("rouh", "UserSetting")
    DraftEdit = apps.get_model("rouh", "DraftEdit")
    for row in UserSetting.objects.filter(name="draft_edits_kept"):
        try:
            held = json.loads(row.value or "[]")
        except (TypeError, ValueError):
            held = []
        for h in reversed(held if isinstance(held, list) else []):
            if isinstance(h, dict):
                DraftEdit.objects.create(
                    user_id=row.user_id, org_id=row.org_id or "", at=float(h.get("at") or 0),
                    to=str(h.get("to") or ""), subject=str(h.get("subject") or ""),
                    changes=list(h.get("changes") or []))
    UserSetting.objects.filter(name="draft_edits_kept").delete()


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0164_task_made_by'),
    ]

    operations = [
        migrations.CreateModel(
            name='DraftEdit',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('user_id', models.TextField()),
                ('org_id', models.TextField()),
                ('at', models.FloatField()),
                ('card', models.TextField(default='')),
                ('chat', models.TextField(default='')),
                ('to', models.TextField(default='')),
                ('subject', models.TextField(default='')),
                ('drafted', models.JSONField(default=dict)),
                ('sent', models.JSONField(default=dict)),
                ('changes', models.JSONField(default=list)),
            ],
            options={
                'db_table': 'draft_edits',
                'indexes': [models.Index(fields=['org_id', 'user_id', '-id'], name='draft_edits_newest')],
            },
        ),
        migrations.RunPython(_moved, migrations.RunPython.noop),
    ]
