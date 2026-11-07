"""A guest's requests of a model, counted by the organisation that pays for them.

Petar, 3 October 2026 (fr_6b7d307db6eb): "Please make sure no LLM code runs
outside of our service that tracks usage and pricing for statistics."

Ask AI's answers to a guest, and a comment pass a guest started, were written
down under `tenancy.GUEST_ORG`, the organisation a guest's own rows are kept
under, so the usage screen (`rouh/usage.py`), which adds up an organisation's
rows, never counted them, though the organisation that shared the page paid
for every one. They are written under the page's organisation since then
(`askai.answer`, `commentpass._run`); this moves the ones written before.

A row moves to the organisation that invited that guest, and only when exactly
one did: a guest asked by two organisations cannot be told apart by the row
alone, and is left where it was rather than guessed.
"""
from django.db import migrations

GUEST_ORG = "guests"


def to_page_org(apps, schema_editor):
    LLMRequest = apps.get_model("rouh", "LLMRequest")
    PageGuest = apps.get_model("rouh", "PageGuest")
    guests = (LLMRequest.objects.filter(org_id=GUEST_ORG).exclude(user_id="")
              .values_list("user_id", flat=True).distinct())
    for guest in list(guests):
        orgs = set(PageGuest.objects.filter(guest_id=guest).values_list("org_id", flat=True))
        orgs.discard("")
        if len(orgs) == 1:
            LLMRequest.objects.filter(org_id=GUEST_ORG, user_id=guest).update(org_id=orgs.pop())


class Migration(migrations.Migration):

    dependencies = [("rouh", "0060_reprepare_nikolas_guide")]

    operations = [migrations.RunPython(to_page_org, migrations.RunPython.noop)]
