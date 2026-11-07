"""Forks from Petar's phone: which point each answer on Telegram finished, and
which forks were made there.

Petar, 27 September 2026: a Fork button under Rouh's answers on Telegram, the
next thing he writes being the fork's first message, and /chats to move
between General and the forks he made there (`rouh/telegram_forks.py`).

`telegram_reply` is one row per message Rouh sent in answer to him: the chat
and the exchange it finished, which is where Fork under it comes off.
`telegram_fork` is one row per fork made on the phone, which is what /chats
offers. Both cascade from the chat, the way `chat_fork` does (`0014`).

Two empty tables, so a Rouh rolled back past this loses nothing it had before:
a fork made from the phone in between is still a fork, and only the phone's
list of them is gone.
"""
from django.db import migrations, models

FOREIGN_KEYS = [
    ("telegram_reply", "telegram_reply_chat_fk", "chat_id"),
    ("telegram_fork", "telegram_fork_chat_fk", "chat_id"),
]


def _add(table: str, name: str, column: str) -> str:
    return (f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" FOREIGN KEY ("{column}") '
            'REFERENCES "chat" ("id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED')


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0031_reminders_and_goals"),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramReply",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("tg_chat", models.TextField()),
                ("message_id", models.BigIntegerField()),
                ("chat", models.ForeignKey(db_column="chat_id", db_constraint=False,
                                           on_delete=models.DO_NOTHING, related_name="+",
                                           to="rouh.chat")),
                ("root", models.BigIntegerField()),
                ("created_at", models.FloatField()),
            ],
            options={
                "db_table": "telegram_reply",
                "indexes": [models.Index(fields=["chat"], name="telegram_reply_chat")],
                "constraints": [models.UniqueConstraint(fields=("tg_chat", "message_id"),
                                                        name="telegram_reply_one")],
            },
        ),
        migrations.CreateModel(
            name="TelegramFork",
            fields=[
                ("chat", models.OneToOneField(db_column="chat_id", db_constraint=False,
                                              on_delete=models.DO_NOTHING, primary_key=True,
                                              related_name="+", serialize=False,
                                              to="rouh.chat")),
                ("created_at", models.FloatField()),
                ("used_at", models.FloatField()),
            ],
            options={
                "db_table": "telegram_fork",
            },
        ),
    ] + [
        migrations.RunSQL(_add(table, name, column),
                          reverse_sql=f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"')
        for table, name, column in FOREIGN_KEYS
    ]
