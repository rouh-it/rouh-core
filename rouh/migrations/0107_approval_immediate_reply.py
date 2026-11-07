"""What a mail case's sender is told at once, bound to the approval Petar sees.

Petar, 8 October 2026, by voice: "There are actually three things that need looking at:
A) the immediate answer, B) the action performed, C) the answer with the delivery ... I
don't see the immediate reply in my decision." The note that tells the sender their request
is under way (`mail_cases.ack_text`) was written only when it went. It is written when he is
asked now, kept on the approval and part of what his yes is bound to (`fingerprint`), and
exactly that goes (`CaseDesk._acknowledge`).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0106_dismiss_expired'),
    ]

    operations = [
        migrations.AddField(
            model_name='mailapproval',
            name='immediate_reply',
            field=models.TextField(blank=True, default='', db_default=''),
        ),
    ]
