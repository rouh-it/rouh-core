"""The "Ready:" card on task 58, taken away once.

Until 23 September 2026 a job that built a page drew a card for it: "Ready:"
and the job's name, its summary around a tile that opened the page, and where
the page was saved. On task 58 that card was the only way to the page at all,
and Petar said what it was: "a card that is type 'here you go'". Cards are for
what he asked to see. A finished job now opens its page on the canvas and
draws no card (`Lander._show_page`), and the task's own page lists the page at
its very top, under Pages (`objectindex.built_pages`).

He asked for the one on task 58 to go, so this removes that one and nothing
else: a card - an artifact of kind `card` - whose title begins "Ready: " and
which is under task 58, owned by the task or by anything the task owns, which
is where a card drawn in the task's chat is kept. Every other "Ready:" card on
every other task is left exactly where it is.

Its versions go with it, which is the database's doing (`ON DELETE CASCADE`,
`0002_database_rules`), and so does every link to or from it. It runs once, in
the deploy, like every migration (`manage.py predeploy`), and says in the
deploy's log what it removed. On a database with no task 58, or no such card
under it, it does nothing. There is nothing to put back on the way down.
"""
from django.db import migrations
from django.db.models import Q

#: The task the card is under, and how its title begins.
TASK = "task-58"
READY = "Ready: "

#: How far down from the task a card is looked for: the task, its chats and
#: steps, their runs, and what those drew.
DEPTH = 6


def forward(apps, schema_editor):
    Artifact = apps.get_model("rouh", "Artifact")
    Link = apps.get_model("rouh", "Link")

    under: set[tuple[str, str]] = set()
    reach = [("task", TASK)]
    for _ in range(DEPTH):
        found = []
        for kind, ident in reach:
            for pair in Link.objects.filter(rel="owns", src_type=kind, src_id=ident) \
                    .values_list("dst_type", "dst_id"):
                if pair not in under:
                    under.add(pair)
                    found.append(pair)
        if not found:
            break
        reach = found
    owned = [ident for kind, ident in under if kind == "artifact"]
    ready = list(Artifact.objects.filter(id__in=owned, kind="card",
                                         title__startswith=READY)
                 .values_list("id", "title"))
    gone = [ident for ident, _title in ready]
    if not gone:
        return
    Link.objects.filter(Q(src_type="artifact", src_id__in=gone)
                        | Q(dst_type="artifact", dst_id__in=gone)).delete()
    Artifact.objects.filter(id__in=gone).delete()
    for ident, title in ready:
        print(f"ready cards: removed {ident} {title!r} under {TASK}")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0004_remove_empty_task_chats"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
