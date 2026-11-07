"""Clears every "A change of Rouh's code is live: undo point N" notice still on the person's screen.

Petar, 3 November 2026: "I have plenty of those. They don't mean anything to me and I should not
be receiving them." Since this day a change that passed its checks is no longer told
(`rouh/codechanges.py`, `quiet`); the ones already said are dismissed here, so nobody has to press
Clear all. The undo points themselves are the protected core's and are not touched: Changes still
lists every one. A change that did not go live, or the doctor's putting the code back, is left as
it was.
"""

import time

from django.db import migrations


def dismiss(apps, schema_editor):
    Notice = apps.get_model("rouh", "Notice")
    rows = Notice.objects.filter(key__startswith="codechange-",
                                 title__startswith="A change of Rouh's code is live")
    rows.filter(phone="due").update(phone="skipped")
    rows.exclude(state="dismissed").update(state="dismissed", handled_at=time.time())


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0227_incubator'),
    ]

    operations = [
        migrations.RunPython(dismiss, migrations.RunPython.noop),
    ]
