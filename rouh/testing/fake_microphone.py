"""A microphone that says something, for a browser that has none.

Chromium will take a WAV file as its microphone
(`--use-file-for-fake-audio-capture`) and loops it for as long as the page
listens. Its own fake device will not do: that is a steady tone, and the page
decides whether a sound is speech with Silero (`rouh/static/vad.js`), which
was chosen precisely because a tone does not fool it. Measured against the
model this repository ships, the tone scores near zero and what is written
here scores 0.99.

What comes out is not words and nothing transcribes it. `fake_voice.py` stands
in for the transcriber, and a test writes there what was heard. The only thing
this has to get right is the shape of the sound, so that the page opens an
utterance on it and closes one on the silence after it, exactly as it does for
a person - which is what lets a browser test have somebody speak at all.

The silence matters as much as the speech. The page measures the room for its
first second and then needs a clear pause to close an utterance on, so the file
starts quiet, speaks, goes quiet for longer than the page's silence setting,
and speaks again.

    python -m rouh.testing.fake_microphone /tmp/said.wav
"""
from __future__ import annotations

import array
import math
import struct

RATE = 16000

#: How long one burst of speech lasts, and the quiet either side of it. The
#: quiet is comfortably longer than the page's own `silenceMs`, which is 700
#: milliseconds by default, or an utterance would never close.
SPEECH_SECONDS = 1.1
QUIET_SECONDS = 1.6

#: A voice's pitch, and how many harmonics of it to build the pulse train from.
#: Twenty-five is plenty: what Silero reads is the formants above, and every
#: harmonic beyond this costs a sine per sample and buys nothing.
PITCH_HZ = 118.0
HARMONICS = 25

#: Three formants that move, which is what makes this read as a vowel going
#: somewhere rather than as a chord. Centre frequency and bandwidth, in hertz.
FORMANTS = ((600.0, 80.0), (1300.0, 110.0), (2600.0, 160.0))

#: Syllables per second. Speech is amplitude-modulated at about this rate and
#: Silero is looking for it.
SYLLABLES_HZ = 3.6


def _speech(seconds: float = SPEECH_SECONDS) -> list[float]:
    """A burst of something a speech detector calls speech."""
    n = int(RATE * seconds)
    # A glottal pulse train with a little vibrato, so no two syllables are
    # identical and nothing sits perfectly on one frequency.
    source = [0.0] * n
    phase = 0.0
    for i in range(n):
        t = i / RATE
        phase += 2 * math.pi * (PITCH_HZ * (1 + 0.03 * math.sin(2 * math.pi * 4.5 * t))) / RATE
        total = 0.0
        for k in range(1, HARMONICS + 1):
            total += math.sin(k * phase) / k ** 1.1
        source[i] = total

    out = [0.0] * n
    for centre, band in FORMANTS:
        r = math.exp(-math.pi * band / RATE)
        rr = r * r
        y1 = y2 = 0.0
        voice = [0.0] * n
        for i in range(n):
            t = i / RATE
            # The centre wanders, which is a mouth moving.
            hz = centre * (1 + 0.35 * math.sin(2 * math.pi * 2.7 * t + centre))
            a1 = 2 * r * math.cos(2 * math.pi * hz / RATE)
            y1, y2 = source[i] + a1 * y1 - rr * y2, y1
            voice[i] = y1
        loudest = max(abs(v) for v in voice) or 1.0
        for i in range(n):
            out[i] += voice[i] / loudest

    loudest = max(abs(v) for v in out) or 1.0
    for i in range(n):
        # Syllables, and a fade at each end: a burst that starts at full
        # amplitude clicks, and a click is a sound of its own.
        t = i / RATE
        syllable = 0.5 + 0.5 * math.sin(2 * math.pi * SYLLABLES_HZ * t - math.pi / 2)
        edge = min(1.0, i / (RATE * 0.02), (n - i) / (RATE * 0.02))
        out[i] = out[i] / loudest * 0.6 * syllable * edge
    return out


def samples(bursts: int = 2) -> array.array:
    """The whole pattern: quiet, then `bursts` of speech with quiet between."""
    quiet = [0.0] * int(RATE * QUIET_SECONDS)
    said = _speech()
    whole: list[float] = list(quiet)
    for _ in range(bursts):
        whole += said + quiet
    return array.array("h", (int(max(-1.0, min(1.0, v)) * 32000) for v in whole))


def write(path: str, bursts: int = 2) -> str:
    """Write the WAV Chromium is to use as its microphone. Returns the path."""
    pcm = samples(bursts).tobytes()
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE")
        fh.write(b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16))
        fh.write(b"data" + struct.pack("<I", len(pcm)) + pcm)
    return path


if __name__ == "__main__":
    import sys

    print(write(sys.argv[1] if len(sys.argv) > 1 else "said.wav"))
