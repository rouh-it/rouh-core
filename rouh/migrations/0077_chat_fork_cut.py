"""A fork that became a task's own chat is cut from the chat it came off.

Petar, 4 October 2026 (fr_3702d01d197d): task 85's chat opened with the task,
but its head said it was a fork of General, because he had forked General to
ask for the task and the fork was what the task was made of. Closing such a
fork left General beside task 85's page. "Where I started this task from has
little relevance or importance", so a fork made a task is cut (`forks.cut`):
the row stays, for what the model reads above the fork's first words and for
the mark in the parent, and `cut_at` says it is no longer laid out as a fork.

Every fork a task already owns is cut here, so the tasks made that way before
today open like every other task.
"""
import time

from django.db import migrations, models


def cut_task_chats(apps, schema_editor):
    ChatFork = apps.get_model("rouh", "ChatFork")
    Link = apps.get_model("rouh", "Link")
    owned = Link.objects.filter(rel="owns", src_type="task", dst_type="chat") \
        .values_list("dst_id", flat=True)
    ChatFork.objects.filter(chat_id__in=list(owned), cut_at__isnull=True) \
        .update(cut_at=time.time(), open=False)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0076_synapse_vector_graph"),
    ]

    operations = [
        migrations.AddField(
            model_name="chatfork",
            name="cut_at",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.RunPython(cut_task_chats, migrations.RunPython.noop),
    ]
