"""A person's Slack member as one of their identifiers (`rouh/synapse/people.py`, `rouh/slack.py`).

Petar, 22 October 2026: "Somehow we need to tie the person in Slack to the contact in Synapse so we
know that 'Tomasz Wiśniewski' from Slack @Tomek is the same as email tomasz@brightfield.example.com and the
same as in notes." So a person carries their Slack member as an identifier of its own, type
`slack`, valued `<team id>:<member id>` and shown as `@Tomek`, beside their addresses, phone numbers
and names. Like an address it is one person's only: one member of a workspace is never two people.
"""
from django.db import migrations

FORWARD = """
ALTER TABLE synapse.identity DROP CONSTRAINT IF EXISTS identity_type_check;
ALTER TABLE synapse.identity ADD CONSTRAINT identity_type_check
  CHECK (type IN ('email', 'phone', 'name', 'handle', 'slack'));
DROP INDEX IF EXISTS synapse.identity_one;
CREATE UNIQUE INDEX IF NOT EXISTS identity_one ON synapse.identity (scope_id, type, value)
  WHERE type IN ('email', 'phone', 'handle', 'slack');
"""

BACKWARD = """
DELETE FROM synapse.identity WHERE type = 'slack';
ALTER TABLE synapse.identity DROP CONSTRAINT IF EXISTS identity_type_check;
ALTER TABLE synapse.identity ADD CONSTRAINT identity_type_check
  CHECK (type IN ('email', 'phone', 'name', 'handle'));
DROP INDEX IF EXISTS synapse.identity_one;
CREATE UNIQUE INDEX IF NOT EXISTS identity_one ON synapse.identity (scope_id, type, value)
  WHERE type IN ('email', 'phone', 'handle');
"""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0204_task_icon'),
    ]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
