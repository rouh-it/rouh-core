"""Ears and mouth.

**Mouth.** One HTTP request per sentence to ElevenLabs, streaming the audio back
as it is produced. The websocket endpoint exists and shaves off a little more,
but it adds a connection to keep alive, a flush protocol to get right and a
failure mode where the socket dies mid-sentence and the person hears half a
word. Since the brain already hands over whole sentences, a streamed request per
sentence gets most of the benefit for a fraction of the ways it can break.

**Ears.** Two implementations. `LiveEars` streams the microphone to a websocket
while the person is still speaking, so the transcript is ready the moment they
stop; that is the normal path and it removes roughly seven tenths of a second
from every spoken turn. `Ears` uploads the finished utterance in one request and
is the fallback for when the socket will not open.

Audio is PCM throughout. No MP3 anywhere, because decoding it in the browser
costs a frame of latency per chunk and the saving does not matter on a link that
is already carrying a voice.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import os
import re
import urllib.parse
import struct
import time
from typing import AsyncIterator

import httpx

log = logging.getLogger("rouh.speech")

#: Where ElevenLabs is. Overridable for the same reason `ANTHROPIC_BASE_URL`
#: is: a test that points this at `rouh.testing.fake_voice` exercises this
#: file unchanged - the same request, the same streaming, the same bytes
#: arriving at the page - while spending nothing and reaching no network. It
#: is never set on the server, so the default is what runs in production.
#: The trailing slash is taken off because every use below appends a path with
#: one of its own, and a base url copied out of a browser usually carries one.
API = (os.environ.get("ELEVENLABS_BASE_URL")
       or "https://api.elevenlabs.io/v1").rstrip("/")


class SpeechError(RuntimeError):
    pass


# "[background noise]", "[clicking]", "[sniffs]". The transcriber labels sounds
# it heard but could not turn into words. They are not something a person said,
# and passing one on as if it were makes the assistant answer a cough.
_EVENT_TAG = re.compile(r"\[[^\]]{1,40}\]")


def words_only(text: str) -> str:
    """The transcript with sound labels removed. Empty if there were no words."""
    if not text:
        return ""
    stripped = _EVENT_TAG.sub(" ", text)
    stripped = " ".join(stripped.split())
    # A stray bit of punctuation left behind by a removed tag is not speech.
    if not any(ch.isalnum() for ch in stripped):
        return ""
    return stripped


class Voice:
    """Text to speech."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=8.0))

    @property
    def ready(self) -> bool:
        return bool(self.cfg.elevenlabs_api_key and self.cfg.voice_id)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Yield raw PCM16 mono at the configured rate for one sentence."""
        if not self.ready:
            raise SpeechError("No ElevenLabs key or voice id configured.")
        text = text.strip()
        if not text:
            return
        url = f"{API}/text-to-speech/{self.cfg.voice_id}/stream"
        params = {
            "output_format": f"pcm_{self.cfg.tts_sample_rate}",
            "optimize_streaming_latency": "3",
        }
        body = {
            "text": text,
            "model_id": self.cfg.tts_model,
            "voice_settings": {"stability": 0.4, "similarity_boost": 0.75, "speed": 1.0},
        }
        headers = {"xi-api-key": self.cfg.elevenlabs_api_key, "accept": "audio/pcm"}
        started = time.monotonic()
        first = True
        async with self._client.stream(
            "POST", url, params=params, json=body, headers=headers
        ) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "replace")[:300]
                raise SpeechError(f"Speech synthesis failed ({resp.status_code}): {detail}")
            async for chunk in resp.aiter_bytes(4096):
                if first:
                    log.info("tts first byte in %dms", int((time.monotonic() - started) * 1000))
                    first = False
                if chunk:
                    yield chunk

    async def voices(self) -> list[dict]:
        headers = {"xi-api-key": self.cfg.elevenlabs_api_key}
        r = await self._client.get(f"{API}/voices", headers=headers)
        r.raise_for_status()
        return [
            {"voice_id": v["voice_id"], "name": v.get("name")}
            for v in r.json().get("voices", [])
        ]

    async def aclose(self) -> None:
        await self._client.aclose()


class Ears:
    """Speech to text."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=8.0))

    @property
    def ready(self) -> bool:
        return bool(self.cfg.elevenlabs_api_key)

    async def transcribe(self, pcm: bytes, sample_rate: int | None = None) -> str:
        if not self.ready:
            raise SpeechError("No ElevenLabs key configured.")
        if len(pcm) < 3200:  # under 100ms at 16kHz: a click, not a sentence
            return ""
        wav = pcm_to_wav(pcm, sample_rate or self.cfg.mic_sample_rate)
        started = time.monotonic()
        text = await self._words_of("speech.wav", wav, "audio/wav")
        log.info(
            "stt(batch) %.1fs audio in %dms -> %r",
            len(pcm) / 2 / (sample_rate or self.cfg.mic_sample_rate),
            int((time.monotonic() - started) * 1000),
            text[:80],
        )
        return text

    async def transcribe_file(self, data: bytes, name: str, media_type: str) -> str:
        """A recording as it came, in whatever format it came in, as words.

        A voice note from Telegram is Ogg Opus (`rouh/telegram_chat.py`), and
        the same endpoint reads it as it is, so it is handed over untouched
        rather than decoded here.
        """
        if not self.ready:
            raise SpeechError("No ElevenLabs key configured.")
        if not data:
            return ""
        started = time.monotonic()
        text = await self._words_of(name, data, media_type or "application/octet-stream")
        log.info("stt(file) %s of %d bytes in %dms -> %r", media_type, len(data),
                 int((time.monotonic() - started) * 1000), text[:80])
        return text

    async def _words_of(self, name: str, data: bytes, media_type: str) -> str:
        files = {"file": (name, data, media_type)}
        # tag_audio_events defaults on, which is how a cough became a message.
        form = {"model_id": self.cfg.stt_model, "tag_audio_events": "false"}
        headers = {"xi-api-key": self.cfg.elevenlabs_api_key}
        r = await self._client.post(
            f"{API}/speech-to-text", files=files, data=form, headers=headers
        )
        if r.status_code >= 400:
            raise SpeechError(f"Transcription failed ({r.status_code}): {r.text[:300]}")
        return words_only((r.json().get("text") or "").strip())

    async def aclose(self) -> None:
        await self._client.aclose()


class LiveEars:
    """Speech to text over a websocket, transcribing while the person is talking.

    The socket is opened the moment speech starts, which costs nothing because
    the person is still mid-sentence, and by the time they stop the words are
    already transcribed. That removes most of the pause between the end of a
    question and the start of the answer - the single most noticeable delay in
    a spoken assistant.

    Two settings here are not optional and were both learned the hard way:

    - `include_language_detection=true`. Without it the session silently assumes
      English and any Bulgarian comes back as an empty string. Not an error, just
      nothing.
    - `commit_strategy=manual`. The browser already decides when a turn ended.
      Letting the server decide as well means two voice detectors disagreeing,
      and the turn ends twice or not at all.
    """

    URL = "wss://api.elevenlabs.io/v1/speech-to-text/realtime"

    def __init__(self, cfg, heard=None):
        self.cfg = cfg
        # The names this Rouh answers to for the person speaking (`birth.heard_names`): "Rouh",
        # its own name and the nickname they gave it, said to the transcriber with the product's
        # own words so a nickname is heard as itself. Read as the socket opens; never raises.
        self.heard = heard
        self._ws = None
        self._reader: asyncio.Task | None = None
        # Audio that arrived before the socket finished opening. Opening takes
        # 250 to 550 milliseconds, which is the first words of a sentence.
        # Dropping them was not a silent failure, it was worse: a short
        # Bulgarian question with its opening cut off was transcribed as
        # Russian, and answered in Russian, with no error anywhere.
        self._pending: list[bytes] = []
        self._failed = False
        # Did the socket do its job? Empty-because-silence and
        # empty-because-broken need different answers, and only this can tell
        # them apart. Treating silence as a failure is what made every quiet
        # moment fall through to the batch transcriber and come back as
        # "[background noise]", which was then answered as if it were speech.
        self.worked = False
        self.partial = ""
        self.final: asyncio.Future | None = None

    @property
    def ready(self) -> bool:
        return bool(self.cfg.elevenlabs_api_key)

    @property
    def live(self) -> bool:
        return self._ws is not None

    async def open(self, on_partial=None) -> None:
        import websockets

        # A language hint rather than pure detection. Bulgarian and Russian are
        # both Cyrillic and close enough that a short clip can go either way;
        # naming the two languages this assistant is actually spoken to removes
        # the choice. Leave the list empty to fall back to open detection.
        params = (
            f"?model_id={self.cfg.stt_realtime_model}"
            f"&audio_format=pcm_{self.cfg.mic_sample_rate}"
            "&include_language_detection=true"
            "&commit_strategy=manual"
        )
        if self.cfg.stt_language:
            params += f"&language_code={self.cfg.stt_language}"
            if self.cfg.stt_secondary_languages:
                params += f"&secondary_languages={self.cfg.stt_secondary_languages}"
        terms = [t.strip()[:20] for t in (self.cfg.stt_keyterms or "").split(",") if t.strip()]
        if self.heard is not None:
            try:
                names = await asyncio.to_thread(self.heard)
            except Exception:  # noqa: BLE001 - the product's own words are still said
                names = []
            terms = list(dict.fromkeys([n.strip()[:20] for n in names if n.strip()] + terms))
        for term in terms[:50]:
            params += f"&keyterms={urllib.parse.quote(term)}"

        self.partial = ""
        self.final = asyncio.get_running_loop().create_future()
        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(
                    self.URL + params,
                    additional_headers={"xi-api-key": self.cfg.elevenlabs_api_key},
                    max_size=4 * 1024 * 1024,
                    ping_interval=20,
                ),
                timeout=8,
            )
        except Exception:
            self._failed = True
            raise
        self._reader = asyncio.create_task(self._read(on_partial))
        # Everything said while we were connecting, in order, before anything new.
        pending, self._pending = self._pending, []
        for chunk in pending:
            await self._raw_send(chunk, False)

    async def _read(self, on_partial) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                kind = msg.get("message_type") or msg.get("type")
                if kind == "partial_transcript":
                    self.partial = words_only((msg.get("text") or "").strip())
                    if on_partial and self.partial:
                        await on_partial(self.partial)
                elif kind == "committed_transcript":
                    text = words_only((msg.get("text") or "").strip())
                    self.worked = True
                    if self.final and not self.final.done():
                        self.final.set_result(text)
                elif kind in _STT_ERRORS:
                    detail = msg.get("message") or msg.get("error") or kind
                    log.warning("realtime stt error: %s", detail)
                    if self.final and not self.final.done():
                        self.final.set_exception(SpeechError(f"Transcription: {detail}"))
        except Exception as exc:
            if self.final and not self.final.done():
                self.final.set_exception(SpeechError(str(exc)))

    # At 16 kHz this is 30 seconds, which is longer than any single utterance
    # and stops a socket that never opens from growing without limit.
    MAX_PENDING_BYTES = 16000 * 2 * 30

    async def send(self, pcm: bytes, commit: bool = False) -> None:
        if self._ws is None:
            if self._failed:
                return
            if sum(len(c) for c in self._pending) < self.MAX_PENDING_BYTES:
                self._pending.append(pcm)
            return
        await self._raw_send(pcm, commit)

    async def _raw_send(self, pcm: bytes, commit: bool) -> None:
        await self._ws.send(
            json.dumps(
                {
                    "message_type": "input_audio_chunk",
                    "audio_base_64": base64.b64encode(pcm).decode("ascii"),
                    "commit": commit,
                }
            )
        )

    async def finish(self, timeout: float = 6.0) -> str:
        """Commit, wait for the final transcript, and close."""
        started = time.monotonic()
        try:
            if self._ws is None:
                log.info("stt(realtime) socket never opened; partial %r", self.partial[:60])
                return self.partial
            # Flush whatever was buffered during the connect, then commit.
            pending, self._pending = self._pending, []
            for chunk in pending:
                await self._raw_send(chunk, False)
            await self._raw_send(b"\x00\x00", True)
            text = await asyncio.wait_for(self.final, timeout=timeout)
            log.info(
                "stt(realtime) committed in %dms -> %r",
                int((time.monotonic() - started) * 1000), text[:80],
            )
            return text
        except asyncio.TimeoutError:
            log.warning("realtime stt did not commit in time; using the last partial")
            return self.partial
        finally:
            await self.close()

    async def close(self) -> None:
        if self._reader and not self._reader.done():
            self._reader.cancel()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._ws = None
        self._reader = None


_STT_ERRORS = {
    "auth_error", "quota_exceeded", "rate_limited", "commit_throttled",
    "queue_overflow", "resource_exhausted", "session_time_limit_exceeded",
    "chunk_size_exceeded", "insufficient_audio_activity", "transcriber_error",
    "input_error", "invalid_request", "unaccepted_terms", "error",
}


def pcm_to_wav(pcm: bytes, sample_rate: int, channels: int = 1, width: int = 2) -> bytes:
    """Wrap raw PCM in a WAV header.

    Written by hand rather than with the `wave` module because that wants a
    seekable file and this is one 44-byte header we already know the shape of.
    """
    block_align = channels * width
    byte_rate = sample_rate * block_align
    header = b"".join(
        [
            b"RIFF",
            struct.pack("<I", 36 + len(pcm)),
            b"WAVEfmt ",
            struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, width * 8),
            b"data",
            struct.pack("<I", len(pcm)),
        ]
    )
    return header + pcm
