"""A mail case's approval never runs out of time (`rouh/mail_cases.py`).

Petar, 8 October 2026, by voice: "Nothing expires due to time only. This question may be
valid in 1 year. So remove time expiration."

Until then an approval lapsed 48 hours after it was asked. Nothing reads that limit any
more, so an approval still open carries none. The first version of this migration also
opened again the approvals that had lapsed by time alone; Petar said the same day not to
("No need to reopen expired - set them dismissed as I don't want to deal with old stuff"),
so 0106 dismisses them instead. On the live server it had opened none.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    MailApproval = apps.get_model("rouh", "MailApproval")
    MailApproval.objects.filter(status="pending").exclude(expires_at=0).update(expires_at=0)


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0104_decision_items'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
