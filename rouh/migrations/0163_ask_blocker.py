"""What stopped an ask's work (`MailAsk.blocker`).

Petar, 16 October 2026, on a trusted contact's case: the start could not add their plans to a task,
and the case wrote a fourth ask into the ledger, "Resolve or authorize shared-task contribution
access ...", which they never asked for. Asks come only from the sender's own words: what the
work needs now goes onto the very ask it stopped, which waits for Petar as that ask, and the
work's own sentence is kept here (MAIL.md D29). The asks raised before are folded onto the asks
they served when their cases are next judged (`mail_ledger.fold`), which every open case is at
the first start after this.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0162_task_access'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailask',
            name='blocker',
            field=models.TextField(blank=True, db_default='', default=''),
        ),
    ]
