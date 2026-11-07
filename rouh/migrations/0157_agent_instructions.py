"""The instructions every agent Rouh starts begins with (`rouh/agent_instructions.py`).

Petar, 15 October 2026: "save it in db, write it so agents start with this and give me interface
like rules that I can CRUD the statements you hand picked." They replace `workspace/AGENTS.md` and
`workspace/AGENTS_ASSISTANT.md`. The first set is written the first time an organisation's are
read (`agent_instructions.ensure_seeded`), not here, so a world made today starts with it too.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0156_gene_mutation_run'),
    ]

    operations = [
        migrations.CreateModel(
            name='AgentInstructionGroup',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('name', models.TextField()),
                ('position', models.IntegerField(default=0)),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
            ],
            options={
                'db_table': 'agent_instruction_group',
                'indexes': [models.Index(fields=['org_id', 'position'], name='agent_instr_group_org')],
            },
        ),
        migrations.CreateModel(
            name='AgentInstruction',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('title', models.TextField()),
                ('text', models.TextField()),
                ('enabled', models.BooleanField(default=True)),
                ('position', models.IntegerField(default=0)),
                ('created_at', models.FloatField()),
                ('updated_at', models.FloatField()),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                            related_name='statements', to='rouh.agentinstructiongroup')),
            ],
            options={
                'db_table': 'agent_instruction',
                'indexes': [models.Index(fields=['org_id', 'group', 'position'], name='agent_instr_org')],
            },
        ),
        migrations.CreateModel(
            name='AgentInstructionChange',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('instruction_id', models.BigIntegerField(blank=True, null=True)),
                ('group_id', models.BigIntegerField(blank=True, null=True)),
                ('action', models.TextField()),
                ('before', models.JSONField(blank=True, null=True)),
                ('after', models.JSONField(blank=True, null=True)),
                ('at', models.FloatField()),
                ('by', models.TextField(blank=True, default='')),
            ],
            options={
                'db_table': 'agent_instruction_change',
                'indexes': [models.Index(fields=['org_id', 'instruction_id', 'at'], name='agent_instr_change')],
                'constraints': [models.CheckConstraint(
                    condition=models.Q(action__in=('seed', 'create', 'edit', 'enable', 'disable', 'move',
                                                   'delete', 'restore', 'group-create', 'group-rename',
                                                   'group-move', 'group-delete')),
                    name='agent_instr_change_action_known')],
            },
        ),
        migrations.CreateModel(
            name='AgentInstructionIssue',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('run_id', models.TextField(blank=True, default='')),
                ('via', models.TextField(blank=True, default='')),
                ('task_id', models.TextField(blank=True, default='')),
                ('text', models.TextField()),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'agent_instruction_issue',
                'indexes': [models.Index(fields=['org_id', 'at'], name='agent_instr_issue_org'),
                            models.Index(fields=['run_id'], name='agent_instr_issue_run')],
            },
        ),
    ]
