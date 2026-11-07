"""One scripted conversation with a running Rouh, over the real websocket."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

import httpx
import websockets


async def close_quickly(ws, limit: float = 5.0) -> None:
    """Close a websocket, and never wait more than `limit` seconds for it.

    websockets' own close() waits for the other end to finish the closing
    handshake, then closes the connection gracefully and waits, with no time
    limit at all, for it to be lost. A graceful close first sends whatever is
    still queued, and if the other end has stopped reading that takes for ever:
    live, through Cloudflare, verify.py sat in that wait for over twelve minutes.
    So the handshake gets `limit` seconds, and then the connection is aborted,
    which drops what is queued and ends it at once.
    """
    if ws is None:
        return
    closed = False
    try:
        await asyncio.wait_for(ws.close(), limit)
        closed = True
    except Exception:
        pass
    finally:
        if not closed:
            transport = getattr(ws, "transport", None)
            if transport is not None:
                transport.abort()


async def sign_in(base_url: str, username: str, password: str) -> str:
    """Trade an account's password for the cookie the socket needs.

    The live site is behind an account, so a test that cannot sign in can only
    ever be run against a laptop - which is exactly the gap that let a fault
    reach production.
    """
    import re

    base = base_url.rstrip("/")
    async with httpx.AsyncClient(follow_redirects=False, timeout=20) as http:
        # The form first, as a browser would: Django will not take a sign-in
        # that does not carry the token the form was given (CSRF), and checks
        # that it came from this site's own page.
        form = await http.get(f"{base}/login")
        found = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form.text)
        token = found.group(1) if found else ""
        r = await http.post(f"{base}/login",
                            data={"username": username, "password": password,
                                  "csrfmiddlewaretoken": token},
                            headers={"Referer": f"{base}/login", "Origin": base})
        for name, value in r.cookies.items():
            if name == "rouh_session":
                return f"{name}={value}"
    raise RuntimeError("the sign-in was refused, so nothing can be tested")


@dataclass
class Turn:
    """What one question produced, measured rather than described."""

    asked: str = ""                 # what we meant to say
    heard: str = ""                 # what Rouh transcribed
    reply: str = ""                 # what it wrote
    spoken: str = ""                # what its audio actually said, transcribed back
    tools: list[str] = field(default_factory=list)
    cards: list[dict] = field(default_factory=list)
    panels: list[dict] = field(default_factory=list)
    audio_bytes: int = 0
    audio: bytes = b""
    turn_id: int | None = None       # which question the server thinks this answers
    stale: int = 0                   # messages belonging to an earlier question
    heard_pieces: list = field(default_factory=list)   # every final transcript
    turns_heard: set = field(default_factory=set)     # how many turns they belonged to
    answers: int = 0                                  # how many replies came back
    first_word_ms: int = 0
    first_sound_ms: int = 0
    total_ms: int = 0
    errors: list[str] = field(default_factory=list)


class Client:
    """A tab, without the tab.

    Speaks the protocol in PROTOCOL.md: JSON text frames, raw PCM binary
    frames, 16000 Hz up and 24000 Hz down.
    """

    MIC_RATE = 16000
    FRAME_MS = 20

    def __init__(self, url: str = "ws://127.0.0.1:8021/ws", session_id: str | None = None,
                 cookie: str | None = None):
        self.url = url
        self.session_id = session_id
        self.ws = None
        self.ready: dict = {}
        self.cookie = cookie

    async def __aenter__(self):
        headers = {"Cookie": self.cookie} if self.cookie else None
        self.ws = await websockets.connect(
            self.url, max_size=None, ping_interval=20, additional_headers=headers
        )
        await self._send({"type": "hello", "client": "testing", "session_id": self.session_id})
        while True:
            msg = await self._recv(timeout=20)
            if msg.get("type") == "ready":
                self.ready = msg
                self.session_id = msg.get("session_id")
                return self
            if msg.get("type") == "error" and msg.get("fatal"):
                raise RuntimeError(f"refused: {msg.get('message')}")

    async def __aexit__(self, *exc):
        await close_quickly(self.ws)

    async def _send(self, obj: dict) -> None:
        await self.ws.send(json.dumps(obj))

    async def _recv(self, timeout: float = 60) -> dict:
        """The next JSON message. Binary frames are audio and are skipped here."""
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            if isinstance(raw, bytes):
                continue
            return json.loads(raw)

    async def settle(self, quiet: float = 0.6, limit: float = 20) -> None:
        """Wait until the last turn has finished arriving.

        The spoken audio of one answer can still be arriving while the next
        question is asked. Without this the test reads the tail of the previous
        turn as the result of this one, and every answer looks one question
        late - which is a real failure mode, but not the one being measured
        here.
        """
        end = time.monotonic() + limit
        while time.monotonic() < end:
            try:
                await asyncio.wait_for(self.ws.recv(), timeout=quiet)
            except asyncio.TimeoutError:
                return

    async def say(self, pcm16k: bytes, meant: str = "", timeout: float = 120) -> Turn:
        """Push audio in as if it came from the microphone, then collect the reply.

        The browser is what decides where an utterance ends, so this says so
        the way a browser does. Whether the utterance was a whole question is
        the model's to answer, and a fragment is deliberately not answered at
        all (`rouh/turnmarks.py`), so what this hands back for one is a turn
        with nothing in it.
        """
        await self.settle()
        step = int(self.MIC_RATE * self.FRAME_MS / 1000) * 2      # bytes per 20ms
        started = time.monotonic()

        await self._send({"type": "speech_start"})
        for i in range(0, len(pcm16k), step):
            await self.ws.send(pcm16k[i:i + step])
            # Real time, so the server's transcriber sees the same arrival
            # pattern it sees from a browser. Sending it all at once hides
            # exactly the bug where the socket was still opening.
            await asyncio.sleep(self.FRAME_MS / 1000)
        await self._send({"type": "speech_end"})
        return await self._collect(started, meant, timeout)

    async def type(self, text: str, timeout: float = 120) -> Turn:
        await self.settle()
        started = time.monotonic()
        await self._send({"type": "text", "text": text})
        return await self._collect(started, text, timeout, heard=text)

    async def _collect(self, started: float, meant: str, timeout: float,
                       heard: str = "") -> Turn:
        turn = Turn(asked=meant, heard=heard)
        audio = bytearray()
        deadline = time.monotonic() + timeout
        done_text = False
        spoke = False              # an audio_start was seen for this turn
        done_audio = False
        # The written reply finishes before the audio does, and the audio may
        # not have started when it does. Breaking on assistant_done alone
        # therefore caught a fraction of the speech and read as "it only said
        # 64% of what it wrote", which is a bug in the test rather than in
        # Rouh. So after the text is done we wait a bounded time for the
        # sound to start, and then for it to end.
        AUDIO_GRACE = 6.0
        text_done_at = None
        while time.monotonic() < deadline:
            left = deadline - time.monotonic()
            if done_text and not spoke:
                left = min(left, 0.5)      # only waiting to see if sound starts
            try:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=left)
            except asyncio.TimeoutError:
                if done_text:
                    continue               # the grace above decides when to stop
                turn.errors.append("timed out waiting for the reply")
                break
            if isinstance(raw, bytes):
                if not audio:
                    turn.first_sound_ms = int((time.monotonic() - started) * 1000)
                audio += raw
                continue
            m = json.loads(raw)
            kind = m.get("type")
            if kind == "stt" and m.get("final"):
                text = m.get("text") or ""
                if text:
                    turn.heard_pieces.append(text)
                if m.get("turn_id"):
                    turn.turns_heard.add(m["turn_id"])
                # One utterance should produce one transcript. When it produces
                # several, the person was cut off mid-thought - so they are
                # joined rather than overwritten, and counted.
                turn.heard = " ".join(turn.heard_pieces) if turn.heard_pieces else turn.heard
            elif kind == "assistant_delta":
                # The server stamps every piece of an answer with the number of
                # the question it belongs to. Anything older is the tail of a
                # previous turn, and counting it as this answer is exactly the
                # failure being tested for.
                tid = m.get("turn_id")
                if tid is not None:
                    if turn.turn_id is None:
                        turn.turn_id = tid
                    elif tid < turn.turn_id:
                        turn.stale += 1
                        continue
                if not turn.first_word_ms:
                    turn.first_word_ms = int((time.monotonic() - started) * 1000)
            elif kind == "assistant_done":
                tid = m.get("turn_id")
                if tid is not None and turn.turn_id is not None and tid < turn.turn_id:
                    turn.stale += 1
                    continue
                if tid is not None:
                    turn.turn_id = tid
                turn.reply = m.get("text") or ""
                turn.answers += 1
                turn.total_ms = int((time.monotonic() - started) * 1000)
                done_text = True
            elif kind == "tool_start":
                tid = m.get("turn_id")
                if tid and turn.turn_id and tid < turn.turn_id:
                    turn.stale += 1
                    continue
                if tid and turn.turn_id is None:
                    turn.turn_id = tid
                turn.tools.append(m.get("name") or "?")
            elif kind == "ui":
                turn.cards.append(m.get("spec") or {})
            elif kind == "panels":
                turn.panels.append({k: v for k, v in m.items() if k != "type"})
            elif kind == "audio_start":
                spoke = True
                done_audio = False
            elif kind == "audio_end":
                done_audio = True
            elif kind == "error":
                turn.errors.append(m.get("message") or "error")
            if done_text and text_done_at is None:
                text_done_at = time.monotonic()
            if done_text and (
                (spoke and done_audio)
                or (not spoke and time.monotonic() - text_done_at > AUDIO_GRACE)
            ):
                # Give any trailing audio frame a moment to land.
                await asyncio.sleep(0.35)
                while True:
                    try:
                        extra = await asyncio.wait_for(self.ws.recv(), timeout=0.1)
                    except asyncio.TimeoutError:
                        break
                    if isinstance(extra, bytes):
                        audio += extra
                break
        turn.audio = bytes(audio)
        turn.audio_bytes = len(audio)
        return turn
