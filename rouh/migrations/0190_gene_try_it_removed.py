"""A gene's Try it out is gone (`rouh/evolution.py`).

Petar, 19 October 2026 (fr_666eae944e93): "Remove this try it out feature". The brown toggle
on a gene's page and its Try it now button are taken out, so the field that held what it
opened or put in the message box has nothing left to read it.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [("rouh", "0189_genes_on_by_default")]

    operations = [migrations.RemoveField(model_name="mutationsgene", name="try_it")]
