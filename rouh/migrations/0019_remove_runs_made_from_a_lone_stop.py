"""The jobs nobody started, taken off the runs list once.

Petar, 24 September 2026, looking at /run/abaa3d7103f5: "something is wrong
with that job. fix it. should look like the rest. find out where it came from
why is it different so it doesn't happen again" (fr_1d8c9f71239b).

It was never a job. Since that afternoon Claude Code, on this machine's
account, works out the grey next prompt it offers after every turn, and it
does that in a hidden fork of the conversation which ends with `SubagentStop`
and no `SubagentStart` before it. Rouh took that stop for a sub-agent closing
(`crew._register_subagent`, `runs.sub_done`), and writing it down made the run
it had never heard of: its id for a title, nothing asked, no workspace, no
parent, `safe` for a policy because that is the column's default, and an end
a moment before its start. So the runs list showed a job of Rouh's own called
abaa3d7103f5, and its page said "That job is not on record here." The next job
to finish made another, a71f46fe7806, four minutes later. News about a run no
longer makes one (`runs.record`), and this takes away the ones already made.

A row goes only when it has exactly that shape, which nothing else writes: a
title that is its own id, no brief, no workspace, no worktree, no branch, no
parent, not a run of the one program, and no background job of that id
behind it. One that owns anything is left where it is and said so, so nothing
with anything in it is lost. What pointed at one - a link, a sub-agent, a
version it wrote - is let go of by the database (`0002_database_rules`).

It runs once, in the deploy, and says in the deploy's log what it removed. On
a database with no such rows it does nothing. There is nothing to put back on
the way down: the rows said nothing that is not in the job each came from.
"""
from django.db import migrations
from django.db.models import F, Q


def say(what: str) -> None:
    print(f"runs made from a lone stop: {what}")


def forward(apps, schema_editor):
    Run = apps.get_model("rouh", "Run")
    Link = apps.get_model("rouh", "Link")
    Crewmate = apps.get_model("rouh", "Crewmate")

    shaped = (Run.objects.filter(title=F("id"), parent_run__isnull=True,
                                 brief="", workspace="")
              .filter(Q(worktree__isnull=True) | Q(worktree=""))
              .filter(Q(branch__isnull=True) | Q(branch=""))
              .exclude(policy="one"))
    for run in shaped.values("id", "state", "started_at"):
        ident = run["id"]
        if Crewmate.objects.filter(id=ident).exists():
            say(f"left {ident} as it is: a background job of that id is behind it")
            continue
        if Link.objects.filter(rel="owns", src_type="run", src_id=ident).exists():
            say(f"left {ident} as it is: it owns something")
            continue
        Link.objects.filter(Q(src_type="run", src_id=ident)
                            | Q(dst_type="run", dst_id=ident)).delete()
        Run.objects.filter(id=ident).delete()
        say(f"removed {ident} ({run['state']}), which no job ever was")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0018_facts_belong_to_a_project"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
