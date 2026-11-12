# SPDX-License-Identifier: Apache-2.0
"""Build the open orb's instrument samples, `rouh/static/orb_cornfield/`.

The Cornfield Chase arrangement (`rouh/static/app/orb_cornfield.js`) plays real
recorded instruments: a pipe organ in two registrations with its pedal, an
upright piano, a cello section, a violin section and a contrabass. They come
from the Versilian Community Sample Library, VSCO 2 Community Edition, which
is CC0 1.0 (public domain dedication), pinned here to one commit.

A few notes of each instrument are taken, the rest are reached by playing them
faster or slower. Each note is cut short (a couple of seconds), mixed to one
channel, evened in loudness, and, for the instruments that hold a note, given a
seamless loop: the end of the loop is crossfaded into the sound just before its
start, and a little of what follows the start is copied after its end, so a
small shift in where a decoder puts the first sample still loops without a
click. Then everything is compressed to MP3, which every browser decodes, and
packed into one file, `samples.bin`, with `samples.json` saying where each note
is, its pitch and its loop.

Run it again from the top of the repository, in a virtualenv of its own:

    python3 -m venv /tmp/cf && /tmp/cf/bin/pip install numpy soundfile lameenc
    /tmp/cf/bin/python tools/orb_cornfield/build_samples.py [--raw <folder of wavs>]

It downloads the source WAVs (about 60 MB) into the folder given, or a
temporary one, from raw.githubusercontent.com at the pinned commit.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import tempfile
import urllib.parse
import urllib.request

import lameenc
import numpy as np
import soundfile as sf

#: The library, at one commit, so the same notes come out every time.
VSCO = "https://raw.githubusercontent.com/sgossner/VSCO-2-CE/440300901dfe9275fd84e0b7763af1f8443ae62e/"

#: What is taken. Each instrument: its source notes as (file, the MIDI note it
#: sounds, measured from the recording), whether it is held (looped) or left to
#: ring out, and how long a piece of each is kept, in seconds.
INSTRUMENTS = {
    # The main voice: the third manual's quiet flue stops (an 8' and a 2 2/3').
    "organ": {"hold": True, "keep": 2.6, "notes": [
        ("Keys/Organ/Quiet/NT5_Man3Quiet_146_rr1.wav", 60),
        ("Keys/Organ/Quiet/NT5_Man3Quiet_152_rr1.wav", 66),
        ("Keys/Organ/Quiet/NT5_Man3Quiet_158_rr1.wav", 72),
        ("Keys/Organ/Quiet/NT5_Man3Quiet_164_rr1.wav", 78),
        ("Keys/Organ/Quiet/NT5_Man3Quiet_170_rr1.wav", 84)]},
    # The climax: the same manual with everything drawn, a 16' under it.
    "organ_full": {"hold": True, "keep": 2.6, "notes": [
        ("Keys/Organ/Loud/Rode_Man3Open_19.wav", 54),
        ("Keys/Organ/Loud/Rode_Man3Open_25.wav", 60),
        ("Keys/Organ/Loud/Rode_Man3Open_31.wav", 66),
        ("Keys/Organ/Loud/Rode_Man3Open_37.wav", 72),
        ("Keys/Organ/Loud/Rode_Man3Open_43.wav", 78)]},
    "pedal": {"hold": True, "keep": 2.6, "notes": [
        ("Keys/Organ/Quiet/NT5_PedalQuiet_064_rr1.wav", 36),
        ("Keys/Organ/Quiet/NT5_PedalQuiet_076_rr1.wav", 48)]},
    "pedal_full": {"hold": True, "keep": 2.6, "notes": [
        ("Keys/Organ/Loud/Rode_Pedal_13.wav", 36),
        ("Keys/Organ/Loud/Rode_Pedal_25.wav", 48)]},
    "piano": {"hold": False, "keep": 3.4, "notes": [
        ("Keys/Upright Piano/Player_dyn2_rr1_016.wav", 53),
        ("Keys/Upright Piano/Player_dyn2_rr1_020.wav", 61),
        ("Keys/Upright Piano/Player_dyn2_rr1_024.wav", 69),
        ("Keys/Upright Piano/Player_dyn2_rr1_028.wav", 77),
        ("Keys/Upright Piano/Player_dyn2_rr1_032.wav", 85)]},
    "cellos": {"hold": True, "keep": 2.6, "notes": [
        ("Strings/Cello Section/susvib/susvib_E1_v1_1.wav", 40),
        ("Strings/Cello Section/susvib/susvib_B1_v1_1.wav", 47),
        ("Strings/Cello Section/susvib/susvib_F2_v1_1.wav", 53),
        ("Strings/Cello Section/susvib/susvib_C3_v1_1.wav", 60),
        ("Strings/Cello Section/susvib/susvib_E3_v1_1.wav", 64)]},
    "violins": {"hold": True, "keep": 2.6, "notes": [
        ("Strings/Violin Section/susVib/VlnEns_susVib_A3_v1.wav", 69),
        ("Strings/Violin Section/susVib/VlnEns_susVib_C4_v1.wav", 72),
        ("Strings/Violin Section/susVib/VlnEns_susVib_E4_v1.wav", 76),
        ("Strings/Violin Section/susVib/VlnEns_susVib_G4_v1.wav", 79),
        ("Strings/Violin Section/susVib/VlnEns_susVib_D5_v1.wav", 86)]},
    "basses": {"hold": True, "keep": 2.6, "notes": [
        ("Strings/Solo Contrabass/SusVib/BKCtbss_SusVib_C1_v1_rr1.wav", 36),
        ("Strings/Solo Contrabass/SusVib/BKCtbss_SusVib_E1_v1_rr1.wav", 40),
        ("Strings/Solo Contrabass/SusVib/BKCtbss_SusVib_A1_v1_rr1.wav", 45)]},
}

RATE = 32000          # samples a second, which keeps everything under 16 kHz
KBPS = 64             # the MP3's bit rate, one channel
LOOP_FROM = 1.0       # the loop's start, seconds after the note begins
LOOP_TO = 2.3         # its end
XFADE = 0.3           # the crossfade into the start, seconds
TAIL = 0.15           # what is copied after the end, seconds
RMS = 0.12            # the loudness every note is evened to


def fetch(path: str, raw: str) -> str:
    local = os.path.join(raw, path.replace("/", "__").replace(" ", "_"))
    if not os.path.exists(local):
        url = VSCO + urllib.parse.quote(path)
        with urllib.request.urlopen(url, timeout=60) as r, open(local, "wb") as fh:
            fh.write(r.read())
    return local


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Linear interpolation after a gentle low-pass, enough for 44.1 to 32 kHz."""
    if src == dst:
        return x
    k = np.hanning(9)
    k /= k.sum()
    x = np.convolve(x, k, mode="same")
    n = int(len(x) * dst / src)
    return np.interp(np.arange(n) * src / dst, np.arange(len(x)), x)


def onset(x: np.ndarray) -> int:
    env = np.abs(x)
    first = int(np.argmax(env > env.max() * 0.06))
    return max(0, first - int(0.01 * RATE))


def shape(x: np.ndarray, hold: bool, keep: float) -> tuple[np.ndarray, float, float]:
    x = x[onset(x):]
    x = x[: int((LOOP_TO + TAIL + 0.05) * RATE) if hold else int(keep * RATE)].copy()
    x *= RMS / max(1e-6, float(np.sqrt(np.mean(x[: int(1.5 * RATE)] ** 2))))
    if not hold:
        fade = int(0.5 * RATE)
        x[-fade:] *= np.linspace(1, 0, fade) ** 2
        return x, 0.0, 0.0
    a, b, f, t = (int(v * RATE) for v in (LOOP_FROM, LOOP_TO, XFADE, TAIL))
    out = x[: b + t].copy()
    w = np.sin(np.linspace(0, math.pi / 2, f)) ** 2       # equal-power-ish
    out[b - f: b] = x[b - f: b] * (1 - w) + x[a - f: a] * w
    out[b: b + t] = x[a: a + t]
    return out, a / RATE, b / RATE


def mp3(x: np.ndarray) -> bytes:
    peak = float(np.abs(x).max())
    if peak > 0.98:
        x = x * (0.98 / peak)
    enc = lameenc.Encoder()
    enc.set_bit_rate(KBPS)
    enc.set_in_sample_rate(RATE)
    enc.set_channels(1)
    enc.set_quality(2)
    pcm = (x * 32767).astype("<i2").tobytes()
    return bytes(enc.encode(pcm) + enc.flush())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=None)
    ap.add_argument("--out", default=os.path.join("rouh", "static", "orb_cornfield"))
    args = ap.parse_args()
    raw = args.raw or tempfile.mkdtemp(prefix="vsco-")
    os.makedirs(raw, exist_ok=True)
    os.makedirs(args.out, exist_ok=True)
    blob = bytearray()
    manifest = {"source": "VSCO 2 Community Edition (CC0 1.0), " + VSCO, "rate": RATE, "instruments": {}}
    for name, inst in INSTRUMENTS.items():
        zones = []
        for path, midi in inst["notes"]:
            x, sr = sf.read(fetch(path, raw), always_2d=True)
            x = resample(x.mean(axis=1), sr, RATE)
            y, ls, le = shape(x, inst["hold"], inst["keep"])
            data = mp3(y)
            zones.append({"midi": midi, "at": len(blob), "size": len(data),
                          "loop": [round(ls, 4), round(le, 4)] if inst["hold"] else None})
            blob += data
        manifest["instruments"][name] = {"hold": inst["hold"], "zones": zones}
        print(f"{name:11s} {len(zones)} notes")
    with open(os.path.join(args.out, "samples.bin"), "wb") as fh:
        fh.write(blob)
    with open(os.path.join(args.out, "samples.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
        fh.write("\n")
    print(f"samples.bin {len(blob) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
