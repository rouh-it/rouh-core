"""The MCP servers a person connected on Anatomy, Connections, MCP servers (`rouh/mcp_servers.py`).

Petar, 15 November 2026: "somewhere in anatomy we should have mcps and ability to easily connect
one." A server is somebody else's program whose tools become Rouh's tools (`rouh/mcp.py`). The
servers named in the installation's setting (`ROUH_MCP_SERVERS`, `ROUH_MCP_CONFIG`) are not rows:
they are shown beside these, read-only.

Every row names the organisation and the person who connected it (AGENTS.md, "Whose data is it"),
and its tools are offered only in that person's turns. What can open a server - a header's value,
an environment value - is sealed with the instance's key (`rouh/encryption.py`); only its name and
last four characters are kept in the open, for the page to say which token it holds.
"""
from django.db import models


class McpServer(models.Model):
    """One MCP server one person connected: an address to post to, or a command to run."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Its name, letters, digits and underscores: its tools are `mcp__<name>__<tool>`.
    name = models.TextField()
    #: "http" (an address, streamable HTTP) or "stdio" (a command run on this machine).
    kind = models.TextField(default="http")
    url = models.TextField(blank=True, default="")
    #: The command and its arguments, as a JSON list.
    command = models.JSONField(default=list, blank=True)
    #: The headers (http) and environment values (stdio), sealed JSON {name: value}.
    headers_sealed = models.TextField(blank=True, default="")
    env_sealed = models.TextField(blank=True, default="")
    #: What the page may show of them: {name: "...1a2b"}.
    hints = models.JSONField(default=dict, blank=True)
    #: The well-known server it was filled in from, if any (`mcp_servers.PRESETS`).
    preset = models.TextField(blank=True, default="")
    #: Off: kept, and not opened.
    enabled = models.BooleanField(default=True)
    #: On: every one of its tools asks the person before it runs (`rouh/permissions.py`).
    ask_first = models.BooleanField(default=True)
    #: What it offered when it last opened: [{name, description}].
    tools = models.JSONField(default=list, blank=True)
    #: The last time it was opened or tested, and why it failed then, in plain words.
    checked_at = models.FloatField(default=0)
    last_error = models.TextField(blank=True, default="")
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "mcp_servers"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "name"],
                                               name="mcp_servers_one_name")]
