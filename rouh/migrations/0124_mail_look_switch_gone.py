"""The switch of night 8's second look at held messages (`mail_look`) taken off Settings, Services.

The feature is gone since the rebuild of trusted contacts' mail on 11 October 2026 (`MAIL.md`):
code decides what may go from grants, so no message is held for reasons a model could look at
again. A switch with nothing behind it is not listed any more. The night's own question to the owner
is left as it is: it is theirs to answer.
"""

from django.db import migrations


def forwards(apps, schema_editor):
    apps.get_model("rouh", "FeatureSwitch").objects.filter(name="mail_look").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0123_old_sends_into_the_outbox"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
