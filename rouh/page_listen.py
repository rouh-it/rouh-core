"""Listen to this page: a page of the workspace told out loud, as a narration written for it.

Version 1 was built by the nightly feature run, night 19, 22 October 2026 (task 94, idea I-116):
a section of the share icon's menu that read the page's words from the top in the device's own
voice. Petar asked for a new version on 27 October 2026 (mutation request 6):

    "listen shouldn't be in the share button, instead it should be in the tooltip with comments,
    highlights and so on. Second, there are no controls, when it starts, there is no stopping.
    Third, the pages are way too non-linear to be able to read them directionally ... the only
    way to listen to that page is if a special narration is generated that kind of walks me
    through this content ... Let's read it with eleven labs voice ... Also, I should be able in
    listen mode to click exactly the element / paragraph and start from there somehow."

So version 2, all of it on the page itself (`rouh/static/askai/listen.js`):

- **Where.** A speaker button in the page's floating control, beside Comment and the highlighter,
  and L. Only for the page's owner on Rouh's canvas, as version 1 was.
- **What is said.** The page as the browser drew it is cut into its elements, each numbered on the
  page (`data-listen-n`), with whether it is showing or behind a toggle or a tab. A model writes a
  narration for it that walks the listener through the page - how it is laid out first, then each
  part, tables and lists told rather than read cell by cell - as a list of parts, each one to three
  sentences, each naming the elements it speaks about (`narrate`, the use ``page_listen`` on the
  Models page). It is kept per person and per page as it was (`_kept`), so the same page as it was
  is never written twice.
- **The voice** is Rouh's own, ElevenLabs, one request per part (`speak`), the next ones asked for
  while one is being said.
- **Controls.** A bar at the bottom while it plays: back a part, pause and play, on a part, and
  close. Escape closes it too.
- **Start from there.** While listening, the element under the pointer is outlined, and a press on
  it starts the narration at the part that speaks about it. The part being said is lit on the page,
  brought into view if it is not, and a closed toggle it is in is opened.

Petar asked for a third version the same day (mutation request 7):

    "I press listen and it says getting page ready to listen and nothing happens for a while. Also
    I did it multiple times. Once text is generated and voice, I shouldn't be generating it again
    on next click of the same page. Also maybe we should have this page but page not the entire
    visual explainer at once"

The live log said why: the narration of a whole explainer took the model two minutes, the browser
gave up on the request, and the narration that came back was thrown away with it, so every press
started again. So version 3:

- **Written once, whatever the browser does.** The narration is written in the background, apart
  from the request that asked for it (`_writing`), and kept when it is done. A second press while
  it is being written joins it instead of asking again, and a press after it is kept is answered
  from the file.
- **The first part is said while the rest is written.** The model's words are read as they arrive
  (`llm.ask`'s ``on_text``), each part is ready once its JSON is whole (`parts_so_far`), and the
  page asks again for what is ready until all of it is.
- **The voice is kept too.** Each part said is kept beside its narration (`_voice`), so a page
  listened to again is never sent to the voice again.
- **Only the page that is showing.** The browser sends only what is drawn now, so an explainer
  of several pages is narrated a page at a time (`rouh/static/askai/listen.js`).

**Its switch** is `page_listen` (`rouh/switches.py`): off, the button is not on the page and this
answers nothing.

**How it says it was used** (GENES.md): ``listened``, the narration asked for by a press of
Listen, and ``jumped``, a part of the page pressed to listen from there.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("rouh.page_listen")

SWITCH = "page_listen"
#: The use on the Models page the narration is written by (`rouh/modeldefaults.py`).
USE = "page_listen"
#: Which way of writing it the kept narrations were written by: a new one is written once the
#: instructions change.
VERSION = 3

#: The most elements of a page sent, the longest text of one, and of all of them together.
ELEMENTS_MAX = 700
ELEMENT_CHARS = 1500
OUTLINE_CHARS = 60_000
#: How long the narration may be, in tokens.
ANSWER_TOKENS = 9000
#: The longest part said in one request to the voice.
PART_CHARS = 900
#: The narrations kept for one person; the oldest go first, with their voice.
KEPT_MAX = 300
#: How long a narration may take to be written before it is given up.
WRITE_S = 300

SYSTEM = """You turn a page into a narration that walks a listener through it, to be read out loud by a voice.

The page is not linear: it has sections, boxes side by side, tables, lists, toggles and tabs. The listener is not reading it. So do not read it word by word. Guide them through it the way a good presenter walks a colleague through a document:

- Begin with the lay of the land, in one to three sentences: what the page is about and how it is built. For example: "This page compares four ways to pay for the flat. There are four sections, each describing one scenario: buying now, renting, waiting a year and selling first. Let's go through them."
- Then go through the content in a sensible order, saying where you are as you go: "The first scenario, buying now, ...". Give the main point of each part and the facts that matter. Tell tables and lists rather than reading every cell: "The table compares three vacuums. The cheapest is the Dyson at four hundred euros; the best for pets is ...".
- Content marked (in a closed toggle) or (not showing) is behind a toggle or a tab. Include it where it adds something, and say it is there: "Inside the toggle on costs, ...".
- End with the page's conclusion or recommendation, if it has one.
- Spoken style: short sentences, natural, lively, with variety, like a person talking, never a list read out. Plain, common words. Say numbers the way a person says them.
- Never say footnote numbers, source lists, web addresses, file names, code, menu items or button labels.
- Write in the language of the page.
- Never use the em dash.

Split the narration into parts, in the order they are spoken. Each part is one to three sentences, at most about 50 words. Each part names the elements of the page it speaks about, by their numbers in the outline, in "at". Every element that carries content belongs to exactly one part, the one that talks about it, so that a listener who taps that element starts listening there. The first part names the page's title element.

Answer with JSON only, and nothing else: {"parts": [{"say": "...", "at": [1, 2]}, ...]}. The parts are read as they arrive, so start with the first part at once."""


class Refused(ValueError):
    """Listen could not do what was asked, and the sentence that says why."""

    def __init__(self, words: str, status: int = 400) -> None:
        super().__init__(words)
        self.status = status


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _words(text, most: int) -> str:
    return " ".join(str(text or "").replace("\u2014", " - ").split())[:most]


def clean_outline(raw) -> list[dict]:
    """The page's elements as its browser numbered them: ``{n, kind, text, shown}``."""
    if not isinstance(raw, list):
        raise Refused("There is nothing on this page to read.")
    out, total, seen = [], 0, set()
    for one in raw[:ELEMENTS_MAX]:
        if not isinstance(one, dict):
            continue
        try:
            n = int(one.get("n"))
        except (TypeError, ValueError):
            continue
        text = _words(one.get("text"), ELEMENT_CHARS)
        if n < 0 or n in seen or not re.search(r"\w", text):
            continue
        kind = re.sub(r"[^a-z0-9]", "", str(one.get("kind") or "").lower())[:12] or "text"
        shown = str(one.get("shown") or "")
        shown = shown if shown in ("toggle", "hidden") else ""
        total += len(text)
        if total > OUTLINE_CHARS:
            break
        seen.add(n)
        out.append({"n": n, "kind": kind, "text": text, "shown": shown})
    if not out:
        raise Refused("There is nothing on this page to read.")
    return out


def question(title: str, outline: list[dict]) -> str:
    """What the model is asked: the page's title, then every element, numbered."""
    where = {"toggle": " (in a closed toggle)", "hidden": " (not showing)"}
    lines = [f"[{e['n']}] {e['kind']}{where.get(e['shown'], '')}: {e['text']}" for e in outline]
    head = f"The page is called: {title}\n\n" if title else ""
    return head + "The page's elements, in the order they are on the page:\n<page>\n" + \
        "\n".join(lines) + "\n</page>"


def _rows(text: str) -> list:
    """The part objects whole so far in the model's answer, in order, as it is being written."""
    said = str(text or "")
    found = re.search(r'"parts"\s*:\s*\[', said)
    if not found:
        start = said.find("[")
        if start < 0 or said[:start].strip():
            return []
        at = start + 1
    else:
        at = found.end()
    rows, dec = [], json.JSONDecoder()
    while True:
        while at < len(said) and said[at] in " \t\r\n,":
            at += 1
        if at >= len(said) or said[at] != "{":
            return rows
        try:
            one, at = dec.raw_decode(said, at)
        except ValueError:
            return rows
        rows.append(one)


def _clean_parts(rows: list, known: set[int]) -> list[dict]:
    """Validate decoded narration parts and allocate each known element once."""
    out, taken = [], set()
    for one in rows:
        if not isinstance(one, dict):
            continue
        say = _words(one.get("say"), PART_CHARS)
        if not re.search(r"\w", say):
            continue
        at = []
        for n in one.get("at") or []:
            try:
                n = int(n)
            except (TypeError, ValueError):
                continue
            if n in known and n not in taken:
                taken.add(n)
                at.append(n)
        out.append({"say": say, "at": at})
    return out


def parts_of(text: str, known: set[int]) -> list[dict]:
    """The model's answer as parts to say, each with the elements it is about. Called on the
    answer while it is being written, it gives the parts that are whole so far."""
    return _clean_parts(_rows(text), known)


def _folder(who) -> Path:
    from .config import config

    mine = re.sub(r"[^A-Za-z0-9_-]", "_", f"{getattr(who, 'org_id', '') or 'none'}-{who.user_id}")
    return Path(config.data_dir) / "page_listen" / mine


def _digest(rel: str, outline: list[dict]) -> str:
    """Which narration this page as it is has: by its words, not by which toggles are open."""
    words = [[e["n"], e["kind"], e["text"]] for e in outline]
    said = json.dumps({"v": VERSION, "rel": rel, "outline": words}, ensure_ascii=False)
    return hashlib.sha256(said.encode("utf-8")).hexdigest()[:32]


def _kept(who, key: str) -> dict | None:
    if not re.fullmatch(r"[0-9a-f]{32}", key or ""):
        return None
    try:
        return json.loads((_folder(who) / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _keep(who, key: str, said: dict) -> None:
    folder = _folder(who)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f".{key}.tmp"
        tmp.write_text(json.dumps(said, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, folder / f"{key}.json")
        files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
        for old in files[:-KEPT_MAX]:
            old.unlink(missing_ok=True)
            for voice in folder.glob(f"{old.stem}.*.pcm"):
                voice.unlink(missing_ok=True)
    except OSError:
        log.exception("the narration of %s could not be kept", said.get("rel"))


class _Writing:
    """A narration being written: its parts so far, whether it is done, and why it failed."""

    def __init__(self, rel: str) -> None:
        self.rel = rel
        self.parts: list[dict] = []
        self.done = False
        self.error: Refused | None = None
        self.task = None


#: The narrations being written now, by person and page as it is. One process serves Rouh, so
#: this is every one there is.
_writing: dict[tuple[str, str], _Writing] = {}
#: The parts being said now, by person, narration and part, so two presses ask the voice once.
_saying: dict[tuple[str, str, int], object] = {}


async def _write(who, key: str, rel: str, title: str, outline: list[dict], job: _Writing, cfg):
    import asyncio

    from . import llm

    known = {e["n"] for e in outline}
    got_words: list[str] = []

    def heard(piece: str) -> None:
        got_words.append(piece)
        job.parts = parts_of("".join(got_words), known)

    try:
        got = await llm.ask(USE, system=SYSTEM, max_tokens=ANSWER_TOKENS, who=who, cfg=cfg,
                            subject=rel[:200], read_only=True, timeout=WRITE_S, on_text=heard,
                            messages=question(_words(title, 300), outline))
        parts = parts_of(got.text, known)
        if not parts:
            raise Refused("No narration came back for this page. Try again.", 502)
        job.parts = parts
        await asyncio.to_thread(_keep, who, key, {"rel": rel, "model": got.model,
                                                 "made": time.time(), "parts": parts})
    except Refused as exc:
        job.error = exc
    except llm.Cannot as exc:
        job.error = Refused(f"Rouh cannot write the narration here: {exc}.", 503)
    except Exception:
        log.exception("the narration of %s could not be written", rel)
        job.error = Refused("The model could not be reached. Try again in a moment.", 502)
    finally:
        job.done = True
        if job.error is None:
            _writing.pop((str(_folder(who)), key), None)


async def _narration_state(who, rel: str, key: str, *, title: str = "",
                           outline: list[dict] | None = None, cfg=None) -> dict:
    """Read the cache or the shared writer, starting one only when an outline is supplied.

    Polling must also match the page; a new request's digest already identifies its page.
    A writer's error is delivered once and removed so the next press can try again.
    """
    import asyncio

    kept = await asyncio.to_thread(_kept, who, key)
    if kept and (outline is not None or kept.get("rel") == rel) and kept.get("parts"):
        return {"key": key, "parts": kept["parts"], "done": True}
    mine = (str(_folder(who)), key)
    job = _writing.get(mine)
    if outline is not None:
        if job is None:
            job = _writing[mine] = _Writing(rel)
            # Apart from the request: a browser that gives up, or a press that stops it, does not
            # throw away what the model is writing.
            job.task = asyncio.get_running_loop().create_task(
                _write(who, key, rel, title, outline, job, cfg))
    elif job is None or job.rel != rel:
        raise Refused("That narration is not there any more. Press Listen again.", 404)
    if job.error is not None:
        # Said once, and the next press asks again.
        _writing.pop(mine, None)
        raise job.error
    return {"key": key, "parts": list(job.parts), "done": job.done}


async def narrate(who, rel: str, title: str, raw_outline, cfg=None) -> dict:
    """The narration of the page as its browser drew it: ``{key, parts, done}``, with the parts
    written so far while it is still being written. Listen was pressed."""
    import asyncio

    from . import evolution

    if not on(who):
        raise Refused("Listen is switched off: the gene page_listen is off in Evolution, Mutations.",
                      409)
    outline = clean_outline(raw_outline)
    key = _digest(rel, outline)
    await asyncio.to_thread(evolution.used, SWITCH, "listened", who=who,
                            detail=f"listened to {rel}")
    return await _narration_state(who, rel, key, title=title, outline=outline, cfg=cfg)


async def ready(who, rel: str, key: str) -> dict:
    """What there is so far of the narration `key` that Listen started: ``{key, parts, done}``."""
    if not on(who):
        raise Refused("Listen is switched off: the gene page_listen is off in Evolution, Mutations.",
                      409)
    key = str(key or "")
    return await _narration_state(who, rel, key)


def _voice(who, key: str, i: int, rate: int) -> Path:
    return _folder(who) / f"{key}.{i}.{rate}.pcm"


def _said_part(who, rel: str, key: str, i) -> tuple[int, dict]:
    """Part `i` of the narration `key`, kept or being written."""
    kept = _kept(who, key)
    parts = kept.get("parts") if kept and kept.get("rel") == rel else None
    if parts is None:
        job = _writing.get((str(_folder(who)), key))
        parts = job.parts if job is not None and job.rel == rel else None
    if parts is None:
        raise Refused("That narration is not there any more. Press Listen again.", 404)
    try:
        i = int(i)
        if i < 0:
            raise IndexError
        return i, parts[i]
    except (TypeError, ValueError, IndexError):
        raise Refused("There is no such part of the narration.", 404) from None


async def _ask_voice(who, rel: str, i: int, say: str, path: Path, cfg) -> bytes:
    import asyncio

    import httpx

    from . import speech

    rate = int(cfg.tts_sample_rate)
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=8.0)) as client:
            r = await client.post(
                f"{speech.API}/text-to-speech/{cfg.voice_id}/stream",
                params={"output_format": f"pcm_{rate}"},
                headers={"xi-api-key": cfg.elevenlabs_api_key, "accept": "audio/pcm"},
                json={"text": say, "model_id": cfg.tts_model,
                      "voice_settings": {"stability": 0.35, "similarity_boost": 0.75,
                                         "style": 0.25, "speed": 1.0}})
    except httpx.HTTPError:
        log.exception("the voice could not be reached for %s", rel)
        raise Refused("The voice could not be reached. Try again in a moment.", 502) from None
    if r.status_code >= 400:
        log.error("the voice refused part %s of %s: %s %s", i, rel, r.status_code, r.text[:300])
        raise Refused("The voice could not read this part.", 502)

    def keep() -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f".{path.name}.tmp")
            tmp.write_bytes(r.content)
            os.replace(tmp, path)
        except OSError:
            log.exception("the voice of part %s of %s could not be kept", i, rel)

    await asyncio.to_thread(keep)
    return r.content


async def speak(who, rel: str, key: str, i, jump: bool = False, cfg=None) -> dict:
    """One part of a narration in Rouh's own voice: ``{rate, pcm}``, PCM16 mono in base64. Said
    once: what the voice gave back is kept, and a second ask for it while it is being said waits
    for the first."""
    import asyncio

    from . import evolution
    from .config import config

    cfg = cfg or config
    if not on(who):
        raise Refused("Listen is switched off: the gene page_listen is off in Evolution, Mutations.",
                      409)
    key = str(key or "")
    if not re.fullmatch(r"[0-9a-f]{32}", key):
        raise Refused("That narration is not there any more. Press Listen again.", 404)
    i, part = await asyncio.to_thread(_said_part, who, rel, key, i)
    if jump:
        await asyncio.to_thread(evolution.used, SWITCH, "jumped", who=who,
                                detail=f"listened from part {i + 1} of {rel}")
    rate = int(cfg.tts_sample_rate)
    path = _voice(who, key, i, rate)
    try:
        pcm = await asyncio.to_thread(path.read_bytes)
    except OSError:
        pcm = None
    if pcm is None:
        if not (cfg.elevenlabs_api_key and cfg.voice_id):
            raise Refused("Rouh has no voice set up to read with.", 503)
        mine = (str(_folder(who)), key, i)
        task = _saying.get(mine)
        if task is None:
            task = _saying[mine] = asyncio.get_running_loop().create_task(
                _ask_voice(who, rel, i, part["say"], path, cfg))
            task.add_done_callback(lambda _t: _saying.pop(mine, None))
        # Shielded, so a browser that stops waiting does not lose the part for the next ask.
        pcm = await asyncio.shield(task)
    return {"rate": rate, "pcm": base64.b64encode(pcm).decode("ascii")}


__all__ = ["SWITCH", "SYSTEM", "USE", "Refused", "clean_outline", "narrate", "on", "parts_of",
           "question", "ready", "speak"]
