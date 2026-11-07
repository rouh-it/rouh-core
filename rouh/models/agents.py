"""The instructions every agent Rouh starts begins with (`rouh/agent_instructions.py`).

Until 15 October 2026 they were two files in the workspace, `workspace/AGENTS.md` and the
`AGENTS_ASSISTANT.md` it imported. Petar, that day: "Why do we need files, cannot we pass this
dynamically? ... we end up modifying the system all the time and no need to save in files", and
"save it in db, write it so agents start with this and give me interface like rules that I can
CRUD". So they are rows: statements in groups, an organisation's own, with every change kept.
"""
from django.db import models
from django.db.models import Q


class AgentInstructionGroup(models.Model):
    """A heading the statements sit under, in the order the groups are told."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    name = models.TextField()
    position = models.IntegerField(default=0)
    created_at = models.FloatField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "agent_instruction_group"
        indexes = [models.Index(fields=["org_id", "position"], name="agent_instr_group_org")]


class AgentInstruction(models.Model):
    """One statement an agent is told, word for word, while it is enabled."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    group = models.ForeignKey(AgentInstructionGroup, on_delete=models.PROTECT, related_name="statements")
    #: A few words that name it on the page.
    title = models.TextField()
    #: The statement itself, as the agent reads it.
    text = models.TextField()
    enabled = models.BooleanField(default=True)
    #: Its place inside its group.
    position = models.IntegerField(default=0)
    created_at = models.FloatField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "agent_instruction"
        indexes = [models.Index(fields=["org_id", "group", "position"], name="agent_instr_org")]


class AgentInstructionChange(models.Model):
    """One change to a statement or a group: what, by whom, from what, to what, when.

    The same idea as `task_change`. `before` and `after` are the whole statement (or group) as
    it was and as it became, so any earlier version can be put back; a statement that was
    deleted keeps its id here, and putting it back makes it again under that id.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The statement's id, or None for a change to a group. No foreign key: a deleted one
    #: keeps its history.
    instruction_id = models.BigIntegerField(null=True, blank=True)
    group_id = models.BigIntegerField(null=True, blank=True)
    action = models.TextField()
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    at = models.FloatField()
    #: Who, in words: "the owner on the Agent instructions page", "Rouh, asked by voice".
    by = models.TextField(blank=True, default="")

    class Meta:
        db_table = "agent_instruction_change"
        indexes = [models.Index(fields=["org_id", "instruction_id", "at"], name="agent_instr_change")]
        constraints = [
            models.CheckConstraint(
                condition=Q(action__in=("seed", "create", "edit", "enable", "disable", "move",
                                        "delete", "restore", "group-create", "group-rename",
                                        "group-move", "group-delete")),
                name="agent_instr_change_action_known"),
        ]


class AgentInstructionIssue(models.Model):
    """What one run was given as it started: the exact text, so it can be checked afterwards."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The run of the one program or the crew job, as each names itself.
    run_id = models.TextField(blank=True, default="")
    #: Who started it: "the one program", "the crew".
    via = models.TextField(blank=True, default="")
    #: The task in play, when there was one, by its id.
    task_id = models.TextField(blank=True, default="")
    text = models.TextField()
    at = models.FloatField()

    class Meta:
        db_table = "agent_instruction_issue"
        indexes = [models.Index(fields=["org_id", "at"], name="agent_instr_issue_org"),
                   models.Index(fields=["run_id"], name="agent_instr_issue_run")]
