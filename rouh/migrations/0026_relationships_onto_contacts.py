"""What the owner had told Rouh about the people close to them, moved onto their contacts.

Petar, 25 September 2026 (fr_b657bd8f6100): "I've already told you about a
couple of relationships that are stored in memory. Please transfer those to
the contacts themselves." And, of himself: "I should have a contact, and you
should update it with all my emails so you know that if it comes from any of
those emails, you should be doing it because I asked for it."

On the installation it was written for, this wrote the profiles
(`contact_profiles`, 0025) of the people close to that installation's owner,
and the owner's own card with every address they write from, from what the
general memory said about them. It only ever wrote for that one account, onto
cards that were really there, and never replaced a relationship or research
already on a profile.

Those relationships and addresses now live only in that installation's
database. Anywhere else - a test world, a fresh install - there was never
anything for it to find, so it does nothing.
"""
from django.db import migrations


def forward(apps, schema_editor):
    """Nothing to do: the profiles it wrote belong to the installation they were written on."""


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0025_contact_profiles_and_mail_by_rouh"),
    ]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
    ]
