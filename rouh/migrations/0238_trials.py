"""Trials (`rouh/trials/`, 4 November 2026): a made-up person tries a change the way a real one
would, step by step, and every moment they trip on is kept on one list of problems.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0237_chat_links_kept_in_chain'),
    ]

    operations = [
        migrations.CreateModel(
            name='Trial',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('number', models.IntegerField()),
                ('persona', models.TextField()),
                ('goal', models.TextField()),
                ('subject', models.TextField(blank=True, default='')),
                ('gene', models.TextField(blank=True, default='')),
                ('page', models.TextField(blank=True, default='')),
                ('round', models.IntegerField(default=1)),
                ('first_id', models.BigIntegerField(blank=True, null=True)),
                ('state', models.TextField(default='queued')),
                ('managed', models.TextField(blank=True, default='')),
                ('nearly_gave_up', models.TextField(blank=True, default='')),
                ('ending', models.TextField(blank=True, default='')),
                ('steps', models.IntegerField(default=0)),
                ('seconds', models.FloatField(default=0)),
                ('problems', models.IntegerField(default=0)),
                ('why', models.TextField(blank=True, default='')),
                ('by', models.TextField(blank=True, default='')),
                ('run_id', models.TextField(blank=True, default='')),
                ('model', models.TextField(blank=True, default='')),
                ('screens', models.JSONField(blank=True, default=list)),
                ('created_at', models.FloatField()),
                ('started_at', models.FloatField(blank=True, null=True)),
                ('ended_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'trials',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'created_at'], name='trial_whose_when')],
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id', 'number'), name='trial_number_once')],
            },
        ),
        migrations.CreateModel(
            name='TrialProblem',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('number', models.IntegerField()),
                ('screen', models.TextField(blank=True, default='')),
                ('screen_name', models.TextField(blank=True, default='')),
                ('what', models.TextField()),
                ('how_bad', models.TextField(default='minor')),
                ('source', models.TextField(default='persona')),
                ('personas', models.JSONField(blank=True, default=list)),
                ('gene', models.TextField(blank=True, default='')),
                ('count', models.IntegerField(default=1)),
                ('status', models.TextField(default='open')),
                ('closed_at', models.FloatField(blank=True, null=True)),
                ('closed_by', models.BigIntegerField(blank=True, null=True)),
                ('closed_note', models.TextField(blank=True, default='')),
                ('first_at', models.FloatField()),
                ('last_at', models.FloatField()),
            ],
            options={
                'db_table': 'trial_problems',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'status'], name='trial_problem_whose_status')],
                'constraints': [models.UniqueConstraint(fields=('org_id', 'user_id', 'number'), name='trial_problem_number_once')],
            },
        ),
        migrations.CreateModel(
            name='TrialSighting',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('problem_id', models.BigIntegerField()),
                ('trial_id', models.BigIntegerField(blank=True, null=True)),
                ('step', models.IntegerField(blank=True, null=True)),
                ('quote', models.TextField()),
                ('how_bad', models.TextField(default='minor')),
                ('source', models.TextField(default='persona')),
                ('persona', models.TextField(blank=True, default='')),
                ('chat', models.TextField(blank=True, default='')),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'trial_sightings',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'problem_id'], name='trial_sighting_problem')],
            },
        ),
        migrations.CreateModel(
            name='TrialStep',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('trial_id', models.BigIntegerField()),
                ('n', models.IntegerField()),
                ('at', models.FloatField()),
                ('url', models.TextField(blank=True, default='')),
                ('screen', models.TextField(blank=True, default='')),
                ('title', models.TextField(blank=True, default='')),
                ('shot', models.TextField(blank=True, default='')),
                ('see', models.TextField(blank=True, default='')),
                ('think', models.TextField(blank=True, default='')),
                ('does', models.TextField(blank=True, default='')),
                ('action', models.JSONField(blank=True, default=dict)),
                ('answers', models.JSONField(blank=True, default=dict)),
                ('found', models.JSONField(blank=True, default=list)),
            ],
            options={
                'db_table': 'trial_steps',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'trial_id'], name='trial_step_whose')],
                'constraints': [models.UniqueConstraint(fields=('trial_id', 'n'), name='trial_step_once')],
            },
        ),
    ]
