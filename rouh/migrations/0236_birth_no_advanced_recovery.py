"""Recover without rouh.land (advanced) is gone, the same day it came (4 November 2026): Petar asked
for no recovery words and no new security features, only a free Rouh that gets its birth and
name from rouh.land. Its switch, never on anywhere but a test, is taken out of the table. Nothing
else of a Rouh's birth changes: names, keys and words stay exactly as they are."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("rouh", "0235_birth_advanced_recovery")]

    operations = [migrations.RemoveField(model_name="rouhbirth", name="advanced_recovery")]
