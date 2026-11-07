"""Every YouTube video Rouh has transcribed, kept in the database and read from there first.

Petar, 22 October 2026 (fr_5e01b7502268): "every YouTube that has been transcribed should be stored
in our database so we check from there and don't do it manually."

`youtube.fetch_transcript` is handed a `Store` and asks it before anything goes to YouTube: a video
already read comes straight back from its row (`how` "stored"), and one that was not is read as
before and then kept. A row is kept for good: a video's words do not go stale the way a page does,
and nothing here refreshes or forgets one. The rows are the organisation's (`models.YouTubeTranscript`),
and every query names it.

Until this, transcripts were kept for a fortnight as files under the data directory
(`youtube.read_cache`), which is still there for a script that loads `youtube.py` on its own
without Django.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time

from . import youtube

log = logging.getLogger("rouh.youtube_store")


def _asked(language: str) -> str:
    """The language asked for as a key, '' for the best track there is."""
    return re.sub(r"[^a-z0-9-]", "", str(language or "").lower())


def find(org_id: str, vid: str, language: str = "") -> youtube.Transcript | None:
    """The stored transcript of a video in this organisation, or None.

    The row asked for in exactly these words first; then, for a language asked by name, any row
    of the video whose track was that language, since "the best track" of an English video and
    "the English one" are the same words.
    """
    from django.db.models import F

    from .models import YouTubeTranscript

    if not org_id or not vid:
        return None
    asked = _asked(language)
    rows = YouTubeTranscript.objects.filter(org_id=org_id, video_id=vid)
    row = rows.filter(language_asked=asked).first()
    if row is None and asked:
        row = rows.filter(language_code__iexact=asked).order_by("generated", "-made_at").first()
    if row is None or not row.cues:
        return None
    now = time.time()
    YouTubeTranscript.objects.filter(org_id=org_id, pk=row.pk).update(
        uses=F("uses") + 1, used_at=now)
    found = youtube.Transcript.from_dict({
        "video_id": row.video_id, "title": row.title, "channel": row.channel,
        "duration": row.duration, "published": row.published, "description": row.description,
        "views": row.views, "language_code": row.language_code,
        "language_name": row.language_name, "generated": row.generated, "cues": row.cues,
    })
    found.how = "stored"
    found.stored_at = row.made_at
    return found


def keep(org_id: str, user_id: str, vid: str, language: str, found: youtube.Transcript) -> None:
    """Keep a transcript just got, for every later ask in this organisation."""
    from .models import YouTubeTranscript

    if not org_id or not vid or not found.cues:
        return
    raw = found.as_dict()
    YouTubeTranscript.objects.update_or_create(
        org_id=org_id, video_id=vid, language_asked=_asked(language),
        defaults={
            "title": found.title, "channel": found.channel, "duration": found.duration,
            "published": found.published, "description": found.description,
            "views": found.views, "language_code": found.language_code,
            "language_name": found.language_name, "generated": found.generated,
            "fetched_how": found.how, "cues": raw["cues"], "text": found.text,
            "made_at": time.time(), "made_by": user_id or "",
        })


class Store:
    """The store as `youtube.fetch_transcript` asks it, for one organisation and person.

    Never the reason a transcript is not had: a store that cannot be read is a store with
    nothing in it, and one that cannot be written is told to the log.
    """

    def __init__(self, org_id: str, user_id: str = ""):
        self.org_id = org_id
        self.user_id = user_id

    @classmethod
    def of(cls, who) -> "Store | None":
        """The store of whoever is asking (`tenancy.Identity`), or None when nobody is known."""
        return cls(who.org_id, who.user_id) if who is not None and who.org_id else None

    async def find(self, vid: str, language: str) -> youtube.Transcript | None:
        try:
            return await asyncio.to_thread(find, self.org_id, vid, language)
        except Exception:  # noqa: BLE001 - YouTube is still there to ask
            log.warning("could not read the stored transcript of %s", vid, exc_info=True)
            return None

    async def keep(self, vid: str, language: str, found: youtube.Transcript) -> None:
        try:
            await asyncio.to_thread(keep, self.org_id, self.user_id, vid, language, found)
        except Exception:  # noqa: BLE001 - the transcript is had either way
            log.warning("could not store the transcript of %s", vid, exc_info=True)
