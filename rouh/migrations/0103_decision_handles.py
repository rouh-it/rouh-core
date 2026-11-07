"""Every decision gets a spoken handle, such as a482 (`rouh/decision_handles.py`).

Petar, 8 October 2026, by voice: "I need a simple number for approvals or id that I can
quickly quote so you know which I am referring to when I speak ... could be something like
a482." Every decision there is gets one here, open or long finished, each person's in the
order they were asked, picked by the same rules every new one is: never one already given to
that person, and apart from the ones still waiting. The database then holds each person's
handles unique.
"""
from django.db import migrations, models


def give_handles(apps, schema_editor):
    """Nothing, since 18 October 2026: handles are no longer given (`0187_decision_numbers`
    numbers every decision instead), and the rules that picked them are gone. The live
    database ran this when it shipped; a new one has no decisions yet at this point."""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0102_page_link_kept'),
    ]

    operations = [
        migrations.AddField(
            model_name='decision',
            name='handle',
            field=models.TextField(blank=True, default='', db_default=''),
        ),
        migrations.RunPython(give_handles, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='decision',
            constraint=models.UniqueConstraint(condition=models.Q(('handle', ''), _negated=True),
                                               fields=('org_id', 'user_id', 'handle'),
                                               name='decisions_one_handle'),
        ),
    ]
