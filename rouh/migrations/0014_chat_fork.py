"""Forks: a side conversation that hangs off a point in another one.

Petar, 24 September 2026 (fr_6fd33e631405): "anytime I'm in a conversation
and don't understand something, I would like to ask for clarification. That
might trigger an entirely new conversation, but at the same time, I don't want
to lose where we are in the main thread."

A fork is a chat, and `chat_fork` is the one row that says where it hangs: the
chat it came off, that chat's last message when it did, and whether it is
still laid out beside it (`rouh/forks.py`). Both ends cascade, the way the
object model's other foreign keys do (`0002_database_rules`).

The table starts empty, so a Rouh rolled back past this migration loses
nothing it had before; any fork made in between is an ordinary chat to it.
"""
from django.db import migrations, models

FOREIGN_KEYS = [
    ("chat_fork_chat_fk", "chat_id"),
    ("chat_fork_parent_fk", "parent_id"),
]


def _add(name: str, column: str) -> str:
    return (f'ALTER TABLE "chat_fork" ADD CONSTRAINT "{name}" FOREIGN KEY ("{column}") '
            'REFERENCES "chat" ("id") ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED')


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0013_uploaded_file"),
    ]

    operations = [
        migrations.CreateModel(
            name="ChatFork",
            fields=[
                ("chat", models.OneToOneField(db_column="chat_id", db_constraint=False,
                                              on_delete=models.DO_NOTHING, primary_key=True,
                                              related_name="+", serialize=False,
                                              to="rouh.chat")),
                ("parent", models.ForeignKey(db_column="parent_id", db_constraint=False,
                                             on_delete=models.DO_NOTHING, related_name="+",
                                             to="rouh.chat")),
                ("at", models.BigIntegerField(blank=True, null=True)),
                ("open", models.BooleanField(default=True)),
                ("created_at", models.FloatField()),
            ],
            options={
                "db_table": "chat_fork",
                "indexes": [models.Index(fields=["parent"], name="chat_fork_parent")],
            },
        ),
    ] + [
        migrations.RunSQL(_add(name, column),
                          reverse_sql=f'ALTER TABLE "chat_fork" DROP CONSTRAINT "{name}"')
        for name, column in FOREIGN_KEYS
    ]
