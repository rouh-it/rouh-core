"""Trials, redesigned (4 November 2026): the people who test are rows of their own (`TrialTester`),
every try belongs to a job, what is being tested (`TrialJob`), and every problem has what should
have happened, what did, a suggested fix, the owner's verdict and a discussion (`TrialNote`).

Petar: "I need to be able to see and manage the people testing the software ... I want a list of
jobs. Each job will have multiple tries." The tries already kept are put into jobs here, one job for
each thing that was tried (its subject, or its page when it had none), so no try is left without one.
The testers are written from the two persona files the first time a person's Trials are read
(`rouh/trials.ensure_testers`), since they are per person and this has no person to give them to.
"""

from django.db import migrations, models


def into_jobs(apps, schema_editor):
    Trial = apps.get_model("rouh", "Trial")
    TrialJob = apps.get_model("rouh", "TrialJob")
    groups: dict = {}
    for t in Trial.objects.filter(job_id__isnull=True).order_by("created_at", "id"):
        what = " ".join((t.subject or t.page or "a page of Rouh").split())
        groups.setdefault((t.org_id, t.user_id, what.lower()), []).append((what, t))
    numbers: dict = {}
    for (org, user, _), rows in groups.items():
        if (org, user) not in numbers:
            numbers[(org, user)] = TrialJob.objects.filter(org_id=org, user_id=user).count()
        numbers[(org, user)] += 1
        what, first = rows[0]
        last = rows[-1][1]
        job = TrialJob.objects.create(
            org_id=org, user_id=user, number=numbers[(org, user)], name=what[:1].upper() + what[1:],
            goal=last.goal, covers="", page=last.page, gene=last.gene, created_at=first.created_at,
            updated_at=last.created_at)
        Trial.objects.filter(id__in=[t.id for _, t in rows]).update(job_id=job.id)


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0238_trials'),
    ]

    operations = [
        migrations.AddField(model_name='trial', name='job_id', field=models.BigIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='trialproblem', name='expected', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trialproblem', name='actual', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trialproblem', name='fix', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trialproblem', name='verdict', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trialproblem', name='decision', field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='trialproblem', name='verdict_at', field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='trialproblem', name='feedback_id', field=models.TextField(blank=True, default='')),
        migrations.CreateModel(
            name='TrialTester',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('key', models.TextField()),
                ('name', models.TextField()),
                ('age', models.IntegerField(blank=True, null=True)),
                ('job', models.TextField(blank=True, default='')),
                ('city', models.TextField(blank=True, default='')),
                ('short', models.TextField(blank=True, default='')),
                ('device', models.TextField(default='phone')),
                ('them', models.TextField(default='them')),
                ('profile', models.TextField(blank=True, default='')),
                ('made_by', models.TextField(blank=True, default='owner')),
                ('archived_at', models.FloatField(blank=True, null=True)),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
            ],
            options={'db_table': 'trial_testers'},
        ),
        migrations.AddConstraint(
            model_name='trialtester',
            constraint=models.UniqueConstraint(fields=('org_id', 'user_id', 'key'), name='trial_tester_key_once'),
        ),
        migrations.CreateModel(
            name='TrialJob',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('number', models.IntegerField()),
                ('name', models.TextField()),
                ('goal', models.TextField(blank=True, default='')),
                ('covers', models.TextField(blank=True, default='')),
                ('page', models.TextField(blank=True, default='')),
                ('gene', models.TextField(blank=True, default='')),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
            ],
            options={'db_table': 'trial_jobs'},
        ),
        migrations.AddConstraint(
            model_name='trialjob',
            constraint=models.UniqueConstraint(fields=('org_id', 'user_id', 'number'), name='trial_job_number_once'),
        ),
        migrations.CreateModel(
            name='TrialNote',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('problem_id', models.BigIntegerField()),
                ('who', models.TextField()),
                ('kind', models.TextField(default='said')),
                ('text', models.TextField()),
                ('model', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={'db_table': 'trial_notes'},
        ),
        migrations.AddIndex(
            model_name='trialnote',
            index=models.Index(fields=['org_id', 'user_id', 'problem_id'], name='trial_note_problem'),
        ),
        migrations.RunPython(into_jobs, migrations.RunPython.noop),
    ]
