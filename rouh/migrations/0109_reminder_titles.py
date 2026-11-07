"""reminder_titles: a reminder is a one-line title and a description under it
(`rouh/reminder_titles.py`, Petar, 8 October 2026, fr_b6dabdcc28e2).

Every row keeps what it said as its description, and words short enough to be
a title already are one. Rouh's own scheduled jobs get their fixed titles here;
every other row is given one by a model once Rouh is running
(`reminder_titles.Titles`), because a title has to read on its own a month
later, and no rule cutting the old words short can promise that.
"""
from django.db import migrations, models

#: Rouh's own scheduled jobs, by `job`: the `TITLE` of each one's module, the
#: words they had, which began with the title, and the `WHAT` they have now,
#: which is only the rest.
SERVER_TITLES = {
    "synapse_nightly": ("Synapse nightly improvement run",
                        "Synapse nightly improvement: try one idea, measure it, keep it only if it helps",
                        "Try one idea to make Synapse better, measure it, and keep it only if it helps"),
    "synapse_dream": ("Synapse nightly dreaming",
                      "Synapse dreaming: compare what changed with what came before, mark what is replaced "
                      "or closed",
                      "Compare what changed in Synapse with what came before, and mark what is replaced or "
                      "closed"),
    "nightly_feature": ("Nightly Rouh feature run",
                        "Nightly Rouh feature run: research, pick and build one new feature, and ask you "
                        "about it in the morning",
                        "Research, pick and build one new feature, and ask you about it in the morning"),
}


#: Words this short are their own title (`reminders.SHORT`).
SHORT = 60


def titles(apps, schema_editor):
    Reminder = apps.get_model("rouh", "Reminder")
    for job, (title, was, now) in SERVER_TITLES.items():
        Reminder.objects.filter(kind="server", job=job, title="").update(title=title)
        Reminder.objects.filter(kind="server", job=job, what=was).update(what=now)
    for row in Reminder.objects.filter(title="").exclude(kind="server"):
        words = " ".join(row.what.split())
        if 0 < len(words) <= SHORT:
            row.title = words.rstrip(".")
            row.save(update_fields=["title"])


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0108_mail_case_fixes'),
    ]

    operations = [
        migrations.AddField(
            model_name='reminder',
            name='title',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.RunPython(titles, migrations.RunPython.noop),
    ]
