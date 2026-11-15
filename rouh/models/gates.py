"""Permission gates: the tools this Rouh asks its owner about before they run (`rouh/gates.py`,
Anatomy, Behaviour, Permission gates).

One row is one tool switched to "ask me first" on the Anatomy page. No row is no gate, which is
the default for every tool. `ROUH_CONFIRM_TOOLS` in the environment names more, which the page
shows as locked on by the server. Every row is the organisation's (AGENTS.md, "Whose data is it")."""
from django.db import models


class PermissionGate(models.Model):
    """One tool that must get the owner's yes before it runs."""

    pk = models.CompositePrimaryKey("org_id", "tool")
    org_id = models.TextField()
    tool = models.TextField()
    #: Who switched it on, in words: "the owner on Anatomy".
    by = models.TextField(blank=True, default="")
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "permission_gates"
