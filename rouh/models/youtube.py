"""Every YouTube video Rouh has transcribed, kept, so it is never transcribed twice (`rouh/youtube_store.py`).

Petar, 22 October 2026 (fr_5e01b7502268): "every YouTube that has been transcribed should be stored in
our database so we check from there and don't do it manually."

One row per video and per language asked for, in one organisation: the words of a public video are
nobody's own, but which videos an organisation's people read is theirs, so every row names the
organisation and the person who first had it read (`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class YouTubeTranscript(models.Model):
    """One video's transcript, as it was first got, and how often it has been read back since."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The eleven-character id, so a watch?v=, a youtu.be and a /shorts/ address of one video are one row.
    video_id = models.TextField()
    #: The language that was asked for, '' for the best track there is: the two can have different
    #: right answers for one video (`youtube.cache_path`).
    language_asked = models.TextField(blank=True, default="")
    title = models.TextField(blank=True, default="")
    channel = models.TextField(blank=True, default="")
    #: Seconds.
    duration = models.FloatField(default=0)
    published = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    views = models.TextField(blank=True, default="")
    language_code = models.TextField(blank=True, default="")
    language_name = models.TextField(blank=True, default="")
    generated = models.BooleanField(default=False)
    #: How it was got the first time: "http", "phone", "browser" or "panel" (`youtube.Transcript.how`).
    fetched_how = models.TextField(blank=True, default="")
    #: Every line with its start and length in seconds, `[{start, duration, text}]`.
    cues = models.JSONField(default=list)
    #: The words alone, for reading and searching without the timings.
    text = models.TextField(blank=True, default="")
    made_at = models.FloatField(default=0)
    made_by = models.TextField(blank=True, default="")
    #: How many times it was read back instead of being transcribed again, and when last.
    uses = models.IntegerField(default=0)
    used_at = models.FloatField(default=0)

    class Meta:
        db_table = "youtube_transcripts"
        constraints = [models.UniqueConstraint(fields=["org_id", "video_id", "language_asked"],
                                               name="youtube_transcripts_one")]
        indexes = [models.Index(fields=["org_id", "video_id"], name="youtube_transcripts_video")]
