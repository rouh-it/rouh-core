"""The words of the protocol that were the first owner's name, rewritten as "owner".

Petar, 20 October 2026: nobody's name is written into Rouh (SETUP.md). Some
values Rouh stores were words with his name in them - an ask "waiting_for_petar",
a case fix that "needs_petar", a delegate's act held "for_petar", a reminder
that goes to "petar". The code writes the "owner" words now and still reads the
old ones; this rewrites the rows already there, so a fresh installation and an
old one hold the same words, and changes the two column defaults that still
said them.

Only these protocol words are touched, in the columns that hold them: never
anybody's text, never a username (`changed_by`, `resolved_by` hold who did
something and are left as they are), and never a column name
(`mail_alert_seen.from_petar` and `slack_promises.by_petar` keep theirs).
Run twice, the second run finds nothing. Undone, every word goes back.
"""
from django.db import migrations, models

#: A column holding one of these words as its whole value: table, column, old, new.
EXACT = (
    ("mail_asks", "status", "waiting_for_petar", "waiting_for_owner"),
    ("mail_asks", "hard_limit", "as_petar", "as_owner"),
    ("mail_case_fixes", "outcome", "needs_petar", "needs_owner"),
    ("delegations", "granted_by", "petar", "owner"),
    ("delegate_acts", "outcome", "for_petar", "for_owner"),
    ("reminders", "goes_to", "petar", "owner"),
    ("long_work_ledger", "by", "petar", "owner"),
    ("mail_alert_seen", "triage", "petar", "owner"),
    ("mail_alert_seen", "stage", "needs_petar", "needs_owner"),
)

#: Columns of JSON (or text holding JSON) where the words are inside: every
#: `<word>_petar` the protocol has becomes `<word>_owner`.
INSIDE = (
    ("public", "mail_approvals", "asks"),
    ("public", "mail_outbox", "ledger"),
    ("public", "mail_case_attempts", "snapshot"),
    ("public", "mail_case_dry_runs", "steps"),
    ("public", "mail_case_fixes", "summary"),
    ("public", "mail_cases", "assessment"),
    ("synapse", "mail_sync", "reconcile"),
)
WORDS = r"(waiting_for|needs|as|hold_for|for|to|by|started_by|tell|told|answer_to|claims)_"

#: A task's origin says who started it: {"by": "petar"} is {"by": "owner"}.
ORIGIN = (("public", "task", "origin"),)


def _type(cursor, schema, table, column):
    cursor.execute("SELECT data_type FROM information_schema.columns WHERE table_schema = %s "
                   "AND table_name = %s AND column_name = %s", [schema, table, column])
    row = cursor.fetchone()
    return row[0] if row else None


def _rewrite(apps, schema_editor, old_word, new_word):
    with schema_editor.connection.cursor() as cursor:
        for table, column, old, new in EXACT:
            if old_word == "owner":
                old, new = new, old
            if _type(cursor, "public", table, column):
                cursor.execute(f'UPDATE "{table}" SET "{column}" = %s WHERE "{column}" = %s',
                               [new, old])
        for schema, table, column in INSIDE:
            kind = _type(cursor, schema, table, column)
            if not kind:
                continue
            cast = "jsonb" if kind == "jsonb" else ("json" if kind == "json" else "text")
            cursor.execute(
                f'UPDATE "{schema}"."{table}" SET "{column}" = regexp_replace("{column}"::text, '
                f"%s, %s, 'g')::{cast} WHERE \"{column}\"::text ~ %s",
                [r"\m" + WORDS + old_word + r"\M", r"\1_" + new_word, r"\m" + WORDS + old_word + r"\M"])
        for schema, table, column in ORIGIN:
            if _type(cursor, schema, table, column) == "jsonb":
                cursor.execute(
                    f'UPDATE "{schema}"."{table}" SET "{column}" = jsonb_set("{column}", '
                    "'{by}', to_jsonb(%s::text)) WHERE \"" + column + "\"->>'by' = %s",
                    [new_word, old_word])
        # A dataset's owner's name had the first owner's as its default (0062). It is
        # blank now, both ways: a name is the account's (`synapse/people.owner_name_of`),
        # and undoing this does not put anybody's name back into the schema.
        if _type(cursor, "synapse", "dataset", "owner_name"):
            cursor.execute("ALTER TABLE synapse.dataset ALTER COLUMN owner_name SET DEFAULT ''")


def forward(apps, schema_editor):
    _rewrite(apps, schema_editor, "petar", "owner")


def backward(apps, schema_editor):
    _rewrite(apps, schema_editor, "owner", "petar")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0194_night_gene_target"),
    ]

    operations = [
        migrations.AlterField(
            model_name="mailask", name="status",
            field=models.TextField(default="waiting_for_owner"),
        ),
        migrations.AlterField(
            model_name="delegation", name="granted_by",
            field=models.TextField(default="owner"),
        ),
        migrations.RunPython(forward, backward),
    ]
