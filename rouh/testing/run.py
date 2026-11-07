"""Talk to a running Rouh and measure what came back.

    python -m rouh.testing.run --url ws://127.0.0.1:8021/ws

Every scenario is spoken, not typed, unless it says otherwise: typing skips the
half of the system most likely to be wrong.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time

from .session import Client
from .voice import accuracy, listen, mix_noise, speak

#: Said out loud, then checked three ways: did it hear it, did it answer, did
#: the audio it sent match the words it wrote.
SPOKEN = [
    ("plain", "What is running right now?", {"tools": ["what_is_running"]}),
    ("short", "Are you there?", {}),
    ("number", "How many background jobs finished today?", {}),
    ("domain", "Open the page at example.com and tell me what it says.", {}),
    ("bulgarian", "Колко задачи работят в момента?", {"lang": "bul"}),
    # The failure that made this unusable: one thought, said with a pause in
    # the middle, arriving as several turns and cut mid-word. Six user messages
    # and one answer, on the live site.
    ("pausing", "I have a metal bar for fitness that is about thirty centimetres long.",
     {"pause_after": "fitness", "one_turn": True}),
]

#: Typed, because these are about which tool gets called rather than about ears.
TYPED = [
    ("recall", "What have you put on the screen so far?", {"tools": ["what_was_on_screen"]}),
    ("panels", "Hide the transcript column.", {"tools": ["set_panels"]}),
    ("pipeline", 'Run this and show me the output: grep -rn "def _show" '
                 '/var/www/rouh/app/rouh --include=*.py | head -3',
     {"tools": ["run_command"], "not_in_reply": ["Refused"]}),
]


async def one_spoken(client: Client, key: str, text: str, want: dict,
                     api_key: str, noise: bytes) -> dict:
    after = want.get("pause_after")
    if after:
        # Said as two halves with a real gap between them, which is what a
        # person does when they are still working out what they want.
        head, _, tail = text.partition(after)
        a = await speak(head + after, api_key)
        b = await speak(tail.strip(), api_key)
        gap = b"\x00" * int(16000 * 0.7) * 2          # 700 ms of quiet
        pcm = a + gap + b
    else:
        pcm = await speak(text, api_key)
    if noise:
        pcm = mix_noise(pcm, noise)
    turn = await client.say(pcm, meant=text)
    spoken_back = ""
    if turn.audio:
        try:
            spoken_back = await listen(turn.audio, api_key)
        except Exception as exc:            # noqa: BLE001
            turn.errors.append(f"could not transcribe the reply: {exc}")
    return grade(key, turn, want, spoken_back)


async def one_typed(client: Client, key: str, text: str, want: dict) -> dict:
    turn = await client.type(text)
    return grade(key, turn, want, "")


def grade(key: str, turn, want: dict, spoken_back: str) -> dict:
    problems = []
    heard = accuracy(turn.asked, turn.heard) if turn.asked else 1.0
    if turn.asked and heard < 0.7:
        problems.append(f"heard {heard:.0%} of the words: {turn.heard!r}")
    if not turn.reply.strip():
        problems.append("no reply was written")
    said = accuracy(turn.reply, spoken_back) if (turn.reply and spoken_back) else None
    if turn.reply and turn.audio and said is not None and said < 0.6:
        problems.append(f"the audio said {said:.0%} of what was written: {spoken_back[:80]!r}")
    if turn.reply and not turn.audio:
        problems.append("it wrote a reply and never spoke it")
    for tool in want.get("tools", []):
        if tool not in turn.tools:
            problems.append(f"never called {tool} (called {turn.tools or 'nothing'})")
    if want.get("one_turn"):
        # What matters is not how many transcripts the transcriber emitted -
        # it emits several for one sentence and they can all feed one question.
        # What matters is that they were treated as ONE question, so nothing
        # said is dropped and one answer comes back.
        if len(turn.turns_heard) > 1:
            problems.append(
                f"one sentence was treated as {len(turn.turns_heard)} questions: "
                + " | ".join(repr(p) for p in turn.heard_pieces)
            )
        if turn.answers > 1:
            problems.append(f"one question got {turn.answers} answers")
    for bad in want.get("not_in_reply", []):
        if bad.lower() in turn.reply.lower():
            problems.append(f"the reply contains {bad!r}")
    if turn.stale:
        problems.append(f"{turn.stale} message(s) belonged to an earlier question")
    problems += turn.errors
    return {
        "case": key, "ok": not problems, "problems": problems,
        "turn_id": turn.turn_id, "stale": turn.stale,
        "pieces": len(turn.heard_pieces), "turns": len(turn.turns_heard),
        "answers": turn.answers,
        "heard_pct": round(heard * 100),
        "spoken_pct": None if said is None else round(said * 100),
        "first_word_ms": turn.first_word_ms, "first_sound_ms": turn.first_sound_ms,
        "total_ms": turn.total_ms, "tools": turn.tools,
        "cards": len(turn.cards), "audio_bytes": turn.audio_bytes,
        "asked": turn.asked, "heard": turn.heard,
        "reply": turn.reply[:300], "spoken_back": spoken_back[:300],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="ws://127.0.0.1:8021/ws")
    ap.add_argument("--noise", help="WAV or raw PCM16 16kHz to lay under every question")
    ap.add_argument("--only", help="run one case by name")
    ap.add_argument("--out", help="write the full report here as JSON")
    ap.add_argument("--label", default="", help="what this run is testing")
    ap.add_argument("--site", help="https base url to sign in to first, e.g. https://rouh.example.com")
    ap.add_argument("--username", default="", help="or set ROUH_USERNAME")
    ap.add_argument("--password", default="", help="or set ROUH_PASSWORD")
    args = ap.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not api_key:
        print("ELEVENLABS_API_KEY is not set, so nothing can be spoken.", file=sys.stderr)
        return 2

    noise = b""
    if args.noise:
        with open(args.noise, "rb") as fh:
            noise = fh.read()
        if noise[:4] == b"RIFF":
            import wave
            with wave.open(args.noise, "rb") as w:
                noise = w.readframes(w.getnframes())

    cookie = None
    if args.site:
        from .session import sign_in

        name = args.username or os.environ.get("ROUH_USERNAME", "")
        word = args.password or os.environ.get("ROUH_PASSWORD", "")
        if not (name and word):
            print("that site needs an account; pass --username and --password, or set"
                  " ROUH_USERNAME and ROUH_PASSWORD", file=sys.stderr)
            return 2
        cookie = await sign_in(args.site, name, word)

    results = []
    started = time.monotonic()
    async with Client(args.url, cookie=cookie) as client:
        print(f"connected: session {client.session_id}, "
              f"model {client.ready.get('model')}, "
              f"ears {client.ready.get('ears')}\n")
        for key, text, want in SPOKEN:
            if args.only and args.only != key:
                continue
            print(f"  saying {key} ...", flush=True)
            results.append(await one_spoken(client, key, text, want, api_key, noise))
        for key, text, want in TYPED:
            if args.only and args.only != key:
                continue
            print(f"  typing {key} ...", flush=True)
            results.append(await one_typed(client, key, text, want))

    ok = sum(1 for r in results if r["ok"])
    print(f"\n{ok}/{len(results)} cases clean in {time.monotonic() - started:.0f}s"
          f"{' - ' + args.label if args.label else ''}\n")
    for r in results:
        mark = "ok  " if r["ok"] else "BAD "
        spoken = "" if r["spoken_pct"] is None else f" spoken {r['spoken_pct']}%"
        pieces = "" if r.get("turns", 1) <= 1 else f" SPLIT INTO {r['turns']}"
        print(f"{mark}{r['case']:<10} heard {r['heard_pct']}%{spoken}{pieces} "
              f"first word {r['first_word_ms']}ms  sound {r['first_sound_ms']}ms  "
              f"total {r['total_ms']}ms  {','.join(r['tools']) or '-'}")
        for p in r["problems"]:
            print(f"       {p}")
    lat = [r["first_sound_ms"] for r in results if r["first_sound_ms"]]
    if lat:
        print(f"\nfirst sound: median {int(statistics.median(lat))}ms, "
              f"worst {max(lat)}ms, over {len(lat)} turns")
    if args.out:
        with open(args.out, "w") as fh:
            json.dump({"label": args.label, "url": args.url, "results": results}, fh, indent=2)
        print(f"full report in {args.out}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
