"""The workspace task a card purchase was for (`payments.task_ref`).

At an online shop's checkout on 17 October 2026 Rouh named task 122 where fill_card takes a
quest, and was refused with "There is no such quest". A task's number is now kept with the
purchase instead.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0174_card_charge_submitted"),
    ]

    operations = [
        migrations.AddField(
            model_name="cardcharge",
            name="task_ref",
            field=models.TextField(blank=True, default=""),
        ),
    ]
