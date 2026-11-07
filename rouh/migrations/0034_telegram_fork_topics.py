"""Each fork made from the phone gets a topic of its own in the owner's forks group.

Petar, 27 September 2026: "after I fork, I expect you to setup and start a new
group chat in telegram with that specific fork". A bot cannot make a group, so
he makes one, once, with Topics on and Rouh an admin, and every /fork gets a
topic in it (`rouh/telegram_forks.py`). `telegram_fork` says which topic each
fork is: the Telegram chat and the topic's thread.

Both columns have a default the database keeps, so a Rouh rolled back past this
still writes rows the table takes; it only stops knowing which topic is which.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0033_goals_are_tasks"),
    ]

    operations = [
        migrations.AddField(
            model_name="telegramfork",
            name="tg_chat",
            field=models.TextField(blank=True, db_default="", default=""),
        ),
        migrations.AddField(
            model_name="telegramfork",
            name="thread_id",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddIndex(
            model_name="telegramfork",
            index=models.Index(fields=["tg_chat", "thread_id"], name="telegram_fork_topic"),
        ),
    ]
