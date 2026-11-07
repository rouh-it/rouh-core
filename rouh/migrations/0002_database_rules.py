"""The rules the object model's tables had in SQLite that Django cannot say.

Three of them, each exactly what `rouh/objects.py` made its tables with:

- **Foreign keys the database carries out.** Deleting a chat takes its
  messages with it; deleting an artifact takes its versions; a run that goes
  leaves its children and the versions it made pointing at nothing. The
  store's own code relies on the database doing that, so the database does it,
  with ``ON DELETE`` on the constraint, and the model fields say
  ``DO_NOTHING`` (`rouh/models/objects.py`). Deferred to the end of a
  transaction, so a move that writes both ends of a pair in either order works.
- **The ownership ranking.** An ``owns`` link has to point down the ranking
  (a project owns a task, a task a chat, ...), or be a project in a project or
  a task in a task and never one in itself. It is a CASE over two columns,
  which is why it is SQL rather than a CheckConstraint.
- **The `object` view**: projects and tasks as one list.
"""
from django.db import migrations

from rouh.models.objects import owns_check_sql

FOREIGN_KEYS = [
    ("message", "message_chat_fk", "chat_id", "chat", "CASCADE"),
    ("artifact_version", "artifact_version_artifact_fk", "artifact_id", "artifact", "CASCADE"),
    ("artifact_version", "artifact_version_run_fk", "made_by_run", "run", "SET NULL"),
    ("run", "run_parent_fk", "parent_run_id", "run", "SET NULL"),
]

OBJECT_VIEW = """
CREATE VIEW object AS
    SELECT id, 'project' AS type, title, slug, number, status, folder, pinned,
           created_at, updated_at
      FROM project
    UNION ALL
    SELECT id, 'task' AS type, title, slug, number, state AS status, folder, pinned,
           created_at, updated_at
      FROM task
"""


def _forward_keys() -> list[str]:
    return [
        f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" FOREIGN KEY ("{column}") '
        f'REFERENCES "{target}" ("id") ON DELETE {action} DEFERRABLE INITIALLY DEFERRED'
        for table, name, column, target, action in FOREIGN_KEYS
    ]


def _backward_keys() -> list[str]:
    return [f'ALTER TABLE "{table}" DROP CONSTRAINT "{name}"'
            for table, name, *_ in FOREIGN_KEYS]


class Migration(migrations.Migration):
    dependencies = [
        ("rouh", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(_forward_keys(), _backward_keys()),
        migrations.RunSQL(
            f'ALTER TABLE "link" ADD CONSTRAINT "link_owns_down" CHECK ({owns_check_sql()})',
            'ALTER TABLE "link" DROP CONSTRAINT "link_owns_down"'),
        migrations.RunSQL(OBJECT_VIEW, "DROP VIEW object"),
    ]
