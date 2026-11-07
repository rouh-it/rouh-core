"""A project's colour, picked by the person.

Petar, 29 September 2026 (fr_0e0dcb5b0c7b): "In project manager I should be
able to pick any color, not just the preset ones." Until now a project's colour
was worked out from its place in its column and was not stored at all. Empty is
still that: a project nobody has given a colour keeps the one its place gives
it. Otherwise it is one of the task browser's own names or `#rrggbb`
(`objectindex._coloured`).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0039_page_option_final"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="color",
            field=models.TextField(blank=True, default=""),
        ),
    ]
