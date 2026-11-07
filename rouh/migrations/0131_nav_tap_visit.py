"""nav_taps.visit: the page load a press of the navigation was made in, so Settings,
Stats can draw where the person went next (`rouh/navtaps.py`; Petar, 12 October 2026,
fr_0ef0ca151b48). Presses from before it have none."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0130_message_notice'),
    ]

    operations = [
        migrations.AddField(
            model_name='navtap',
            name='visit',
            field=models.TextField(blank=True, default=''),
        ),
    ]
