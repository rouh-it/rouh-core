import time

from django.db import migrations

GENERAL = "conversation"


def belong(apps, schema_editor):
    """Every chat with no home becomes a fork of General that started fresh (`forks.belong`).

    Petar, 15 November 2026: "A chat is exactly one of: General, a fork of General, or a task's (or step's)
    chat. There are no loose chats ... any other becomes a fork of General. Delete nothing." So each chat
    that is not General, not a fork and not owned by a task gets one row of `chat_fork`, `at` None (it carries
    nothing of General, so what the model reads in it is unchanged) and cut (it stays in the list of chats).
    An archived chat is left alone: it is a goal's old stream, kept where it belongs."""
    Chat = apps.get_model("rouh", "Chat")
    ChatFork = apps.get_model("rouh", "ChatFork")
    with schema_editor.connection.cursor() as cur:
        cur.execute("SELECT dst_id FROM link WHERE rel = 'owns' AND dst_type = 'chat' AND src_type = 'task'")
        owned = {r[0] for r in cur.fetchall()}
    forked = set(ChatFork.objects.values_list("chat_id", flat=True))
    now = time.time()
    rows = []
    for chat_id, state in Chat.objects.values_list("id", "state"):
        if chat_id == GENERAL or chat_id in forked or chat_id in owned or state == "archived":
            continue
        rows.append(ChatFork(chat_id=chat_id, parent_id=GENERAL, at=None, created_at=now, cut_at=now))
    ChatFork.objects.bulk_create(rows, ignore_conflicts=True)


def nothing(apps, schema_editor):
    """Going back leaves the rows: each is a chat that belongs to General, and reads as a loose chat did."""


class Migration(migrations.Migration):
    dependencies = [("rouh", "0251_lean_settings")]
    operations = [migrations.RunPython(belong, nothing)]
