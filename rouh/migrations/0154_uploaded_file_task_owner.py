"""A file the person uploads can belong to a task as well as a chat or a project.

Petar, 15 October 2026 (fr_f79f49b86538): "when I open a task, please put an upload button so I
can upload files directly there". The file is kept under the task's id in the attachment store
(`objectindex.task_files_key`) and indexed for search like every other upload, so the check on
what an `uploaded_file` row may be owned by takes "task" too.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0153_requester_shares'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='uploadedfile',
            name='uploaded_file_owner_known',
        ),
        migrations.AddConstraint(
            model_name='uploadedfile',
            constraint=models.CheckConstraint(
                condition=models.Q(('owner_type__in', ('chat', 'project', 'task'))),
                name='uploaded_file_owner_known'),
        ),
    ]
