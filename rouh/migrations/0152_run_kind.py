"""Which half of Metabolism a run is on: a mutation or everyday work (`runs.kind_of`).

Petar, 14 October 2026: "use metabolism. and within the runs page, split it in two types -
mutations and everyday work." A mutation is a run that changes Rouh itself: improve_myself,
a delegate_task on this server or on Rouh, the nightly Rouh feature run, anything that lands
on Rouh's own repository. Everyday work is everything else: assistant_job, one_start and the
person's errands.

Since 22 September 2026 both kinds of run of the one program work in the same checkout, Rouh's
own (the person's workspace is `workspace/` inside it), so the workspace on a run no longer
tells them apart, and the run says which it is from now on. The runs already kept are given
theirs here by the same rule wherever the row can say:

* the `self` policy, or a workspace that is Rouh's own code (`/var/www/<rouh or jarvis>/app`,
  and `/srv/spaces/jarvis`, the one program's space for Rouh's code before it was renamed to
  `rouh`), is a mutation;
* a job of the crew under `auto` is the assistant's, everyday work; under any other of the
  crew's policies it was a delegate_task, a mutation;
* a run of the program in `/srv/assistant`, the person's workspace before 22 September, is
  everyday work;
* a run of the program whose start is in the event log is the space it was started in:
  `rouh` a mutation, anything else everyday work;
* a sub-agent is what its parent is.

What is left - runs of the program in Rouh's checkout between 22 September and 10 October -
is asked of the program when Rouh next connects to it, which still knows each run's space
(`runtime.OneFeed`), and is drawn as everyday work until then.
"""
from django.db import migrations, models


def backfill(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cur:
        cur.execute("""
            UPDATE run SET kind = 'mutation'
             WHERE kind = '' AND (policy = 'self'
                OR workspace ~ '/(rouh|jarvis)/app/?$'
                OR workspace ~ '/spaces/jarvis/?$'
                OR policy IN ('yolo', 'safe', 'local-only', 'direct-pr'))""")
        cur.execute("UPDATE run SET kind = 'everyday' WHERE kind = '' AND policy = 'auto'")
        cur.execute("""
            UPDATE run SET kind = 'everyday'
             WHERE kind = '' AND policy = 'one' AND workspace ~ '/srv/assistant/?$'""")
        cur.execute("SELECT to_regclass('analytics.event') IS NOT NULL")
        if cur.fetchone()[0]:
            cur.execute("""
                UPDATE run r
                   SET kind = CASE WHEN e.space IN ('rouh', 'jarvis') THEN 'mutation'
                                   ELSE 'everyday' END
                  FROM (SELECT DISTINCT ON (object_id) object_id, props->>'space' AS space
                          FROM analytics.event
                         WHERE name = 'run.started' AND object_type = 'run'
                           AND props ? 'space'
                         ORDER BY object_id, occurred_at) e
                 WHERE r.kind = '' AND r.id = e.object_id""")
        cur.execute("""
            UPDATE run c SET kind = p.kind FROM run p
             WHERE c.kind = '' AND c.parent_run_id = p.id AND p.kind <> ''""")


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0151_thought_enrich'),
    ]

    operations = [
        migrations.AddField(model_name='run', name='kind',
                            field=models.TextField(blank=True, default='')),
        migrations.AddConstraint(
            model_name='run',
            constraint=models.CheckConstraint(
                condition=models.Q(kind__in=('', 'mutation', 'everyday')),
                name='run_kind_known')),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
