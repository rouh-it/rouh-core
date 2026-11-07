"""A stand-in for ElevenLabs, so a test can hear Rouh and be heard by it.

`fake_model.py` is the same idea one layer up: a real HTTP server in front of
the real client, so what a test proves is what actually went over the wire.
This one answers the text-to-speech endpoint `rouh/speech.py` calls, and
answers it with real PCM16 at the rate that was asked for, streamed in pieces
the way the real one streams it.

Point `ELEVENLABS_BASE_URL` at it and Rouh is unchanged - same `Voice`, same
request, same streaming - while a browser on the other end gets a reply with
audio in it. That is what lets a browser test assert that speech was actually
scheduled into a speaker rather than thrown away, which is a thing no unit test
can see.

What it says is a tone, not words. Nothing in these tests listens; what is
being measured is whether the bytes reached the speaker, and a tone has the
one property that matters for that, which is being audibly not silence.

Every sentence it was asked to say is written down, one file per request, so a
test can also check what Rouh chose to speak.

It answers the other direction too, speech to text, because that is the same
account and the same key. What it hears is not worked out from the audio -
nothing here could - but read line by line from a file a test writes first,
named by `ROUH_FAKE_HEARS`: the first utterance is the first line, the second
the second, and once the file runs out it hears nothing, which is the right
answer to a room that has gone quiet. `rouh/testing/fake_microphone.py` is
the other half of it, and is what makes the browser speak at all.

    python -m rouh.testing.fake_voice --port 8098 --record /tmp/spoken
"""
from __future__ import annotations

import argparse
import array
import json
import math
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

#: Roughly how long a real voice takes over a character, so a sentence comes
#: back at about the length the page would really have to play.
SECONDS_PER_CHAR = 0.055

#: The least any sentence lasts. A reply of "Yes." still has to be long enough
#: for the page to schedule something.
MIN_SECONDS = 0.5

#: And the most, so a model that runs away cannot hang a test.
MAX_SECONDS = 6.0

#: What the real endpoint streams back at a time.
CHUNK = 4096


def tone(text: str, rate: int) -> bytes:
    """PCM16 mono that sounds like something, for as long as `text` would take."""
    seconds = min(MAX_SECONDS, max(MIN_SECONDS, len(text) * SECONDS_PER_CHAR))
    n = int(rate * seconds)
    # A falling pitch with the ends faded, because a buffer that starts and
    # stops at full amplitude clicks, and a click is what a person hears first.
    samples = array.array("h", bytes(2 * n))
    fade = max(1, int(rate * 0.01))
    for i in range(n):
        hz = 220.0 - 60.0 * (i / n)
        amp = 0.35
        if i < fade:
            amp *= i / fade
        elif i > n - fade:
            amp *= (n - i) / fade
        samples[i] = int(32767 * amp * math.sin(2 * math.pi * hz * i / rate))
    return samples.tobytes()


#: Where a test writes what is to be heard, one utterance per line.
HEARS = "ROUH_FAKE_HEARS"


def build_app(record_dir: str | None = None) -> FastAPI:
    app = FastAPI()
    counter = {"n": 0}
    heard = {"n": 0, "written": 0.0}

    @app.post("/v1/speech-to-text")
    async def transcribe(request: Request):
        # The audio is read and thrown away. What a test is proving is what
        # Rouh does with words it was given, and the words are the test's.
        await request.form()
        said = ""
        path = os.environ.get(HEARS)
        if path and os.path.isfile(path):
            # A test that writes the file again is starting again, which is
            # what lets two tests in one file each have their own script.
            written = os.path.getmtime(path)
            if written != heard["written"]:
                heard["written"], heard["n"] = written, 0
            with open(path, encoding="utf-8") as fh:
                lines = [line.strip() for line in fh if line.strip()]
            if heard["n"] < len(lines):
                said = lines[heard["n"]]
                heard["n"] += 1
        return JSONResponse({"text": said, "language_code": "eng"})

    @app.get("/v1/voices")
    async def voices():
        return JSONResponse({"voices": [{"voice_id": "test-voice", "name": "A test voice"}]})

    @app.post("/v1/text-to-speech/{voice_id}/stream")
    async def speak(voice_id: str, request: Request):
        body = await request.json()
        text = (body or {}).get("text") or ""
        # `pcm_24000`, the way Rouh asks for it. Anything else and the page
        # would be handed audio at a rate it was not told about, which is a
        # real failure and not one to paper over here.
        fmt = request.query_params.get("output_format", "pcm_24000")
        rate = int(fmt.rsplit("_", 1)[-1])

        if record_dir:
            counter["n"] += 1
            name = f"{counter['n']:04d}-{int(time.time() * 1000)}.json"
            with open(os.path.join(record_dir, name), "w", encoding="utf-8") as fh:
                json.dump({"voice_id": voice_id, "text": text, "rate": rate}, fh)

        pcm = tone(text, rate)

        async def stream():
            for at in range(0, len(pcm), CHUNK):
                yield pcm[at:at + CHUNK]

        return StreamingResponse(stream(), media_type="audio/pcm")

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--record", default=None)
    args = ap.parse_args()
    if args.record:
        os.makedirs(args.record, exist_ok=True)
    uvicorn.run(build_app(args.record), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
