"""The empty chats opening a task left behind, taken away once.

Until 23 September 2026 every task the person clicked on was given a chat on
the spot, and left owning it with nothing ever said in it: fifteen of them on
the live database that day, task 08 among them. Opening a task makes nothing
now (`conversations.open_draft`); this removes the ones already made, and only
the ones that are provably that and nothing more. `rouh/emptychats.py` says
exactly what that means and why, and what is left alone instead.

It runs once, in the deploy, like every migration (`manage.py predeploy`), and
says in the deploy's log what it removed and what it left. There is nothing to
put back on the way down: what it removes is rows with nothing in them.
"""
from django.db import migrations


def forward(apps, schema_editor):
    from rouh import emptychats
    from rouh.config import config

    def get(name):
        return apps.get_model("rouh", name)

    found = emptychats.survey(get, data_dir=config.data_dir)
    gone = emptychats.remove(get, [row["id"] for row in found["remove"]])
    for row in found["remove"]:
        print(f"empty chats: removed {row['id']} {row['title']!r} under "
              f"{row['owner']} ({row['owner_title']})")
    for row in found["keep"]:
        print(f"empty chats: left {row['id']} {row['title']!r} under "
              f"{row['owner'] or 'nothing'}: {row['why']}")
    if gone or found["keep"]:
        print(f"empty chats: {gone} removed, {len(found['keep'])} left alone")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0003_feedback_board"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
