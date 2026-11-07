"""Every YouTube video Rouh has transcribed, kept so it is not transcribed again (`rouh/youtube_store.py`).

Petar, 22 October 2026 (fr_5e01b7502268): "every YouTube that has been transcribed should be stored in
our database so we check from there". One row per organisation, video and language asked for. It
starts empty: what the fourteen-day file cache under the data directory held is not brought in.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0205_synapse_identity_slack'),
    ]

    operations = [
        migrations.CreateModel(
            name='YouTubeTranscript',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('video_id', models.TextField()),
                ('language_asked', models.TextField(blank=True, default='')),
                ('title', models.TextField(blank=True, default='')),
                ('channel', models.TextField(blank=True, default='')),
                ('duration', models.FloatField(default=0)),
                ('published', models.TextField(blank=True, default='')),
                ('description', models.TextField(blank=True, default='')),
                ('views', models.TextField(blank=True, default='')),
                ('language_code', models.TextField(blank=True, default='')),
                ('language_name', models.TextField(blank=True, default='')),
                ('generated', models.BooleanField(default=False)),
                ('fetched_how', models.TextField(blank=True, default='')),
                ('cues', models.JSONField(default=list)),
                ('text', models.TextField(blank=True, default='')),
                ('made_at', models.FloatField(default=0)),
                ('made_by', models.TextField(blank=True, default='')),
                ('uses', models.IntegerField(default=0)),
                ('used_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'youtube_transcripts',
                'indexes': [models.Index(fields=['org_id', 'video_id'], name='youtube_transcripts_video')],
                'constraints': [models.UniqueConstraint(fields=('org_id', 'video_id', 'language_asked'), name='youtube_transcripts_one')],
            },
        ),
    ]
