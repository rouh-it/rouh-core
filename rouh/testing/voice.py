"""Speech in both directions, so a test can talk and listen.

The voice used to ask questions is deliberately NOT the voice Rouh replies
in. Testing a transcriber with the same voice it was tuned on proves less than
nothing.
"""
from __future__ import annotations

import audioop
import io
import re
import wave

import httpx

API = "https://api.elevenlabs.io/v1"

#: A different speaker from the one Rouh answers in.
ASK_VOICE = "21m00Tcm4TlvDq8ikWAM"       # Rachel, a stock ElevenLabs voice


async def speak(text: str, api_key: str, *, voice_id: str = ASK_VOICE,
                rate: int = 16000, model: str = "eleven_flash_v2_5") -> bytes:
    """Turn a written question into microphone-shaped audio: PCM16 mono, 16 kHz."""
    async with httpx.AsyncClient(timeout=60) as http:
        r = await http.post(
            f"{API}/text-to-speech/{voice_id}/stream",
            params={"output_format": f"pcm_{rate}"},
            json={"text": text, "model_id": model},
            headers={"xi-api-key": api_key, "accept": "audio/pcm"},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"could not synthesise the question ({r.status_code}): {r.text[:200]}")
        return r.content


async def listen(pcm: bytes, api_key: str, *, rate: int = 24000,
                 model: str = "scribe_v1") -> str:
    """What that audio actually says, so a reply can be checked against its text."""
    if len(pcm) < 3200:
        return ""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    async with httpx.AsyncClient(timeout=120) as http:
        r = await http.post(
            f"{API}/speech-to-text",
            files={"file": ("reply.wav", buf.getvalue(), "audio/wav")},
            data={"model_id": model, "tag_audio_events": "false"},
            headers={"xi-api-key": api_key},
        )
        if r.status_code >= 400:
            raise RuntimeError(f"could not transcribe the reply ({r.status_code}): {r.text[:200]}")
        return (r.json().get("text") or "").strip()


def mix_noise(speech: bytes, noise: bytes, *, speech_over_noise_db: float = 10.0) -> bytes:
    """Lay background noise under speech at a stated loudness difference.

    The dryer was louder than it sounded and the microphone opened on it, so
    "does it still hear me over that" is a real test rather than a nicety.
    """
    if not noise:
        return speech
    while len(noise) < len(speech):
        noise += noise
    noise = noise[:len(speech)]
    s_rms = audioop.rms(speech, 2) or 1
    n_rms = audioop.rms(noise, 2) or 1
    wanted = s_rms / (10 ** (speech_over_noise_db / 20))
    noise = audioop.mul(noise, 2, wanted / n_rms)
    return audioop.add(speech, noise, 2)


#: Unicode-aware on purpose. `[a-z0-9']+` matches nothing in Cyrillic, so a
#: perfectly spoken Bulgarian reply scored 2% against its own recording.
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)*", re.UNICODE)


def words(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def accuracy(said: str, heard: str) -> float:
    """Share of the words we said that came back, 0 to 1.

    Deliberately not a full edit distance: word order is not what breaks, words
    are - a domain such as "example.com" arriving as "example calm" is the failure this measures.
    """
    want = words(said)
    if not want:
        return 1.0
    got = list(words(heard))
    hit = 0
    for w in want:
        if w in got:
            got.remove(w)
            hit += 1
    return hit / len(want)
