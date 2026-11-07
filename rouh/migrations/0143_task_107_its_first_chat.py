"""Task 107 is given the chat that asked for it, as its own conversation.

0142 gave tasks 100, 104 and 107 the forks of General their jobs were asked
for in, but only a task holding no chat yet. Task 107 held one by then:
Petar opened it at 20:23 on 13 October 2026, eight minutes after reporting
fr_b662c3fe9778, and asked for the work there. So the first fork
was left loose again. A chat that asked for a task is the task's own
conversation whatever else was started in it since
(`conversations.adopt_made_task`), so it is given to the task here, as the
oldest of its chats, which is the one opening the task brings back; the 20:23
chat stays the task's too. Anywhere the chat is not there, or already has a
task, nothing is done.
"""
import time
import uuid

from django.db import migrations

#: (the task's number, the chat that asked for the job that made it)
MADE = ((107, "chat-e736a53308a9"),)


def give_chat(apps, schema_editor):
    Chat = apps.get_model("rouh", "Chat")
    ChatFork = apps.get_model("rouh", "ChatFork")
    Link = apps.get_model("rouh", "Link")
    Task = apps.get_model("rouh", "Task")
    for number, chat_id in MADE:
        task = Task.objects.filter(number=number).first()
        if task is None or not Chat.objects.filter(id=chat_id).exists():
            continue
        owner = Link.objects.filter(rel="owns", dst_type="chat", dst_id=chat_id).first()
        if owner is not None and owner.src_type != "project":
            continue
        if owner is not None:
            owner.delete()
        Link.objects.create(id="link-" + uuid.uuid4().hex[:12], rel="owns",
                            src_type="task", src_id=task.id, dst_type="chat",
                            dst_id=chat_id, created_at=task.created_at)
        ChatFork.objects.filter(chat_id=chat_id, cut_at__isnull=True) \
            .update(cut_at=time.time(), open=False)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0142_chats_of_tasks_jobs_made"),
    ]

    operations = [
        migrations.RunPython(give_chat, migrations.RunPython.noop),
    ]
