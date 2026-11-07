"""Every decision gets a plain number, Decision 1, 2, 3, each person's in the order asked
(`rouh/decision_numbers.py`).

Petar, 18 October 2026: drop the letter-and-three-digit handles (a482); "the letters mean
nothing and confuse him, because similar decisions get different letters. Numbering should be
consecutive, not random." Every decision there is, open or long finished, is numbered here
from 1 for each person, in the order its row was made. On the live database that is each
decision's own row number (304 rows, ids 1 to 304, one person), so an old link to
/decisions/<id> still opens the same decision. The handle column stays, so an old link or
message that names one is still found and sent on to its number.
"""
from django.db import migrations, models


def give_numbers(apps, schema_editor):
    Decision = apps.get_model("rouh", "Decision")
    nexts: dict[tuple, int] = {}
    for row_id, org, user in (Decision.objects.order_by("org_id", "user_id", "id")
                              .values_list("id", "org_id", "user_id")):
        n = nexts.get((org, user), 0) + 1
        nexts[(org, user)] = n
        Decision.objects.filter(id=row_id).update(number=n)


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0186_models_auto_per_box'),
    ]

    operations = [
        migrations.AddField(
            model_name='decision',
            name='number',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.RunPython(give_numbers, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='decision',
            constraint=models.UniqueConstraint(condition=models.Q(('number__isnull', False)),
                                               fields=('org_id', 'user_id', 'number'),
                                               name='decisions_one_number'),
        ),
    ]
