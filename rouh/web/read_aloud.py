"""Read a message aloud, over the web (`rouh/read_aloud.py`).

``POST /api/read-aloud`` with ``{text}``: the message's words in Rouh's own voice, streamed back as
they are said, PCM16 mono, with the rate in ``X-Sample-Rate``. For the signed-in person only.
A voice that is not set up answers 503 with the words to show; one that fails part way ends the
stream early, and the page stops where the sound stopped.
"""
from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.http import HttpRequest, StreamingHttpResponse

from .common import body_of, only, refuse, who

log = logging.getLogger("rouh.web.read_aloud")


@only("POST")
async def say(request: HttpRequest):
    from rouh import read_aloud, runtime
    from rouh.config import config
    from rouh.speech import SpeechError

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    text = str(body_of(request).get("text") or "")
    if not read_aloud.pieces(text):
        return refuse("There are no words in this message to read.", 400)
    voice = runtime.voice
    if not voice.ready:
        return refuse("Rouh has no voice set up to read with.", 503)

    async def chunks():
        try:
            async for chunk in read_aloud.stream(text, voice):
                yield chunk
        except SpeechError as exc:
            log.warning("read aloud: %s", exc)

    response = StreamingHttpResponse(chunks(), content_type="audio/pcm")
    response["X-Sample-Rate"] = str(int(config.tts_sample_rate))
    response["Cache-Control"] = "no-store"
    return response


__all__ = ["say"]
