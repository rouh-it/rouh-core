"""Three tasks a job made are given the chat that asked for the job.

Petar, 13 October 2026 (fr_b662c3fe9778): he forked General and asked for
research "in a new [company] task", Rouh started a job, and the job made task
107. The fork was left loose, so task 107's page had no chat and the one he
asked in was nowhere to be found from the task. Since today a chat that asks
for a job is the chat of the task that job makes (`conversations.adopt_made_task`).

Before today it happened three times on the live database, each a fork of
General whose one job made exactly one task, read off each job's brief and
the task it landed: 100 (OpenHands, Cline and mem0), 104 and
107. Each is given its chat here, and the fork is cut from General
as `forks.cut` does. Anywhere those chats are not there, or the task already
has a chat, or the chat already has a task, nothing is done.
"""
import time
import uuid

from django.db import migrations

#: (the task's number, the chat that asked for the job that made it)
MADE = (
    (100, "chat-26995be3ed38"),
    (104, "chat-083531e8c48b"),
    (107, "chat-e736a53308a9"),
)


def give_chats(apps, schema_editor):
    Chat = apps.get_model("rouh", "Chat")
    ChatFork = apps.get_model("rouh", "ChatFork")
    Link = apps.get_model("rouh", "Link")
    Task = apps.get_model("rouh", "Task")
    now = time.time()
    for number, chat_id in MADE:
        task = Task.objects.filter(number=number).first()
        if task is None or not Chat.objects.filter(id=chat_id).exists():
            continue
        if Link.objects.filter(rel="owns", src_type="task", src_id=task.id,
                               dst_type="chat").exists():
            continue
        owner = Link.objects.filter(rel="owns", dst_type="chat", dst_id=chat_id).first()
        if owner is not None and owner.src_type != "project":
            continue
        if owner is not None:
            owner.delete()
        Link.objects.create(id="link-" + uuid.uuid4().hex[:12], rel="owns",
                            src_type="task", src_id=task.id, dst_type="chat",
                            dst_id=chat_id, created_at=now)
        ChatFork.objects.filter(chat_id=chat_id, cut_at__isnull=True) \
            .update(cut_at=now, open=False)


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0141_gene_log"),
    ]

    operations = [
        migrations.RunPython(give_chats, migrations.RunPython.noop),
    ]
