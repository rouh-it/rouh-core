"""Checks a page asks for about a name: its .ai and .com now, and a trade mark screening on demand.

Built 20 November 2026 for task 149, step 149-02, the page where Petar picks a new name for
BigBongo. His words: when he adds a name of his own, start its .ai and .com checks at once and show
them working until the answers are in; and "also add a button for checking trademark on demand. I
press it, you immediately start a Claude Code run and it update the site when ready".

A workspace page is sandboxed and cannot reach anything (`pages.py`), so it asks through the
canvas's relay, as Ask AI and Listen do (``/api/checks`` in cards.js, `rouh/web/name_checks.py`),
for the page's owner only. ``do`` says what:

- ``domains`` with ``spellings``: each one that is a domain label (`LABEL`, at most `MOST`) is
  asked of the .ai registry's RDAP (Identity Digital) and the .com registry's (Verisign) now, and
  answered ``free`` (no registration found), ``taken`` (with the date it was registered) or
  ``unknown`` (no clear answer after three tries). A spelling that is not a label is answered
  ``refused`` and asked of nobody. Answers are kept for `KEEP_S`, so pressing again does not ask
  again.
- ``trademark`` with ``word`` and ``spellings``: a run is started, one at a time for each word and
  page, from Rouh's own brief (`BRIEF`), never from words the page sends: the word is cut to letters,
  digits, spaces, hyphens and apostrophes, at most `WORD_CHARS`, and the spellings to labels. The
  run screens the name at EUIPO (through TMview), USPTO and UKIPO in Nice classes 9, 42 and 35, and
  looks for software or AI products of the same name; it writes what it found into
  ``source-code/trademarks.json`` in the page's folder, under the word, with the request's own
  ``token``, and rebuilds the page. It never files, buys or registers anything.
- ``trademark_status`` with ``words``: for each word, ``none``, ``running`` (with when it started),
  ``done`` (the entry from trademarks.json whose token is the latest request's, or any entry when
  no request was made here) or ``failed`` (could not be started, or no answer in `RUN_S`).

What a run was asked is kept per person under the data folder's ``name_checks/``.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import os
import re
import secrets
import time
import unicodedata
from pathlib import Path

log = logging.getLogger("rouh.name_checks")

LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
#: The most spellings asked about at once, and the most words asked about for their state.
MOST = 8
WORDS_MOST = 80
#: The longest word a trade mark run is asked about.
WORD_CHARS = 40
#: How long a domain answer is kept before it is asked again.
KEEP_S = 600
#: How long a trade mark run may take before it is said to have failed.
RUN_S = 3 * 3600
RDAP = {"ai": "https://rdap.identitydigital.services/rdap/domain/{}.ai",
        "com": "https://rdap.verisign.com/com/v1/domain/{}.com"}
RESULTS = "source-code/trademarks.json"

BRIEF = """Trade mark screening, started from the "Check trademark" button on the page {page}.

The name: {word}
Its domain spellings: {spellings}
Request token: {token}

Do a trade mark screening of this name, not a legal clearance, and file or buy nothing:

1. Search for identical and similar-sounding or similar-looking marks (the name and each spelling) at
   EUIPO through TMview (tmdn.org/tmview), at the USPTO (tmsearch.uspto.gov) and at the UKIPO
   (trademarks.ipo.gov.uk), in Nice classes 9 (software), 42 (software as a service, software work)
   and 35 (business services). Use headless Playwright. If a site needs a login, a captcha or a
   payment, do not work round it: note that office as not searched, with the reason.
2. A same-field check: the web, the app stores and GitHub, for software or AI products, companies or
   projects with this name or a near spelling.
3. Write the findings into {results} (the folder {folder}), as JSON. Keep every other word's entry
   exactly as it is and change only this one, under "words" -> "{word}":
   {{"request": "{token}", "checked_at": "<ISO time now>", "spellings": [...],
     "verdict": "clear so far" | "watch" | "conflict",
     "summary": "<one or two plain sentences>",
     "offices": {{"EUIPO (TMview)": {{"searched": true, "how": "..."}}, "USPTO": {{...}}, "UKIPO": {{...}}}},
     "marks": [{{"mark": "...", "owner": "...", "office": "...", "classes": [9, 42],
                "status": "registered | pending | dead", "link": "<the record's address>",
                "why": "<why it matters>"}}],
     "same_field": [{{"name": "...", "what": "...", "link": "..."}}]}}
   "clear so far": nothing identical or close in those classes or in the same field. "watch": a close
   or similar mark or product that a lawyer should look at. "conflict": an identical or nearly
   identical live mark in classes 9, 42 or 35, or a same-field product with the name.
4. If {folder}/source-code/build.py exists, run it from {folder} so the page shows the result, and
   check that the page still opens. Commit only the files of that folder.
5. Add one line to the latest step's notes in {folder} saying the word, the verdict and the date.

Say in your last message the verdict and the marks that matter. This is a screening, not a legal
clearance: a lawyer's clearance search is still the last step before a name is chosen."""


class Refused(ValueError):
    def __init__(self, words: str, status: int = 400) -> None:
        super().__init__(words)
        self.status = status


class Hooks:
    """What the runtime lends: starting a run (`starting.start`). None until it is set."""

    start = None


hooks = Hooks()
_kept: dict[tuple[str, str], tuple[float, dict]] = {}
_starting: dict[str, asyncio.Lock] = {}


def labels(raw) -> tuple[list[str], list[str]]:
    """The spellings that are domain labels, and the ones that are not, at most `MOST` in all."""
    ok, bad = [], []
    for s in (raw if isinstance(raw, list) else [])[:MOST]:
        s = str(s or "").strip().lower()
        if not s:
            continue
        (ok if LABEL.fullmatch(s) else bad).append(s[:80])
    return list(dict.fromkeys(ok)), list(dict.fromkeys(bad))


def clean_word(raw) -> str:
    """The word as it may reach a brief: letters of any script, digits, spaces, hyphens and
    apostrophes, at most `WORD_CHARS`."""
    w = unicodedata.normalize("NFC", str(raw or ""))
    w = "".join(c for c in w if c.isalnum() or c in " -'")
    return " ".join(w.split())[:WORD_CHARS].strip()


async def _ask(client, name: str, tld: str) -> dict:
    url = RDAP[tld].format(name)
    for attempt in range(3):
        try:
            r = await client.get(url, headers={"Accept": "application/rdap+json"})
            if r.status_code == 404:
                return {"status": "free"}
            if r.status_code == 200:
                d = r.json()
                if str(d.get("ldhName", "")).lower() == f"{name}.{tld}":
                    when = next((e.get("eventDate", "")[:10] for e in d.get("events", [])
                                 if e.get("eventAction") == "registration"), "")
                    return {"status": "taken", "created": when}
        except Exception:  # noqa: BLE001 - any failure is asked again, then said as unknown
            log.info("rdap: %s.%s did not answer on try %d", name, tld, attempt + 1)
        await asyncio.sleep(1.5 * (attempt + 1))
    return {"status": "unknown"}


async def domains(raw) -> dict:
    """Each label's .ai and .com, asked now: ``{checked, domains: {name: {ai, com}}, refused}``."""
    import httpx

    ok, bad = labels(raw)
    if not ok and not bad:
        raise Refused("Say which spellings to check.")
    today = datetime.date.today().isoformat()
    out: dict = {}
    want = []
    now = time.time()
    for name in ok:
        for tld in ("ai", "com"):
            hit = _kept.get((name, tld))
            if hit and now - hit[0] < KEEP_S:
                out.setdefault(name, {})[tld] = hit[1]
            else:
                want.append((name, tld))
    if want:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=8.0)) as client:
            got = await asyncio.gather(*(_ask(client, n, t) for n, t in want))
        for (name, tld), a in zip(want, got):
            a["checked"] = today
            out.setdefault(name, {})[tld] = a
            if a["status"] != "unknown":
                _kept[(name, tld)] = (now, a)
    return {"checked": today, "domains": out, "refused": bad}


def _folder_of(rel: str) -> str:
    return os.path.dirname(rel.strip("/"))


def _state_file(who, folder: str, word: str) -> Path:
    from .config import config

    mine = re.sub(r"[^A-Za-z0-9_-]", "_", f"{getattr(who, 'org_id', '') or 'none'}-{who.user_id}")
    key = hashlib.sha256(f"{folder}\n{word}".encode("utf-8")).hexdigest()[:32]
    return Path(config.data_dir) / "name_checks" / mine / f"{key}.json"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _results(root: str, folder: str) -> dict:
    got = _read(Path(root) / folder / RESULTS)
    words = got.get("words") if isinstance(got, dict) else None
    return words if isinstance(words, dict) else {}


def _status(who, root: str, folder: str, word: str, results: dict) -> dict:
    asked = _read(_state_file(who, folder, word))
    entry = results.get(word) if isinstance(results.get(word), dict) else None
    if asked.get("token"):
        if entry and entry.get("request") == asked["token"]:
            return {"state": "done", "result": entry, "started": asked.get("started")}
        if asked.get("state") == "failed":
            return {"state": "failed", "why": asked.get("why", ""), "started": asked.get("started"),
                    "result": entry}
        if time.time() - float(asked.get("started") or 0) > RUN_S:
            return {"state": "failed", "why": "No answer came back in three hours.",
                    "started": asked.get("started"), "result": entry}
        return {"state": "running", "started": asked.get("started"), "run": asked.get("run", ""),
                "result": entry}
    if entry:
        return {"state": "done", "result": entry}
    return {"state": "none"}


async def trademark_status(who, root: str, rel: str, raw_words) -> dict:
    folder = _folder_of(rel)
    words = [clean_word(w) for w in (raw_words if isinstance(raw_words, list) else [])[:WORDS_MOST]]
    results = await asyncio.to_thread(_results, root, folder)
    return {"words": {w: await asyncio.to_thread(_status, who, root, folder, w, results)
                      for w in dict.fromkeys(words) if w}}


async def trademark(who, root: str, rel: str, raw_word, raw_spellings) -> dict:
    """Start the screening run for one word, or say the one already running."""
    from asgiref.sync import sync_to_async

    from . import conversations, steps

    word = clean_word(raw_word)
    if not word:
        raise Refused("Say which name to check.")
    spellings, _ = labels(raw_spellings)
    folder = _folder_of(rel)
    path = _state_file(who, folder, word)
    lock = _starting.setdefault(str(path), asyncio.Lock())
    async with lock:
        results = await asyncio.to_thread(_results, root, folder)
        now = await asyncio.to_thread(_status, who, root, folder, word, results)
        if now["state"] == "running":
            return {**now, "word": word, "again": True}
        if hooks.start is None:
            raise Refused("Runs cannot be started from here.", 503)
        token = secrets.token_hex(8)
        started = time.time()
        brief = BRIEF.format(page=rel, word=word, spellings=", ".join(spellings) or "none given",
                             token=token, results=f"{folder}/{RESULTS}", folder=folder)
        chat = ""
        try:
            task = steps.task_part(folder)
            chat = await sync_to_async(conversations.answer_for_task)(task) or ""
        except Exception:  # noqa: BLE001 - a page with no task's chat still gets its run
            log.info("name_checks: no task chat for %s", folder)
        await asyncio.to_thread(_write, path, {"word": word, "token": token, "started": started,
                                               "state": "starting", "folder": folder})
        try:
            got = await hooks.start(brief=brief, title=f"Trade mark screening: {word}"[:120],
                                    preset="assistant_job", chat=chat,
                                    owner=(str(who.user_id), str(who.org_id)), org_id=str(who.org_id))
        except Exception as exc:  # noqa: BLE001 - CannotStart says why in words
            log.warning("name_checks: the screening of %r could not be started: %s", word, exc)
            await asyncio.to_thread(_write, path, {"word": word, "token": token, "started": started,
                                                   "state": "failed", "folder": folder,
                                                   "why": str(exc) or "The run could not be started."})
            return {"state": "failed", "why": str(exc) or "The run could not be started.",
                    "started": started, "word": word}
        run = str((got or {}).get("id") or (got or {}).get("run") or "")
        await asyncio.to_thread(_write, path, {"word": word, "token": token, "started": started,
                                               "state": "running", "folder": folder, "run": run})
        return {"state": "running", "started": started, "run": run, "word": word}


__all__ = ["BRIEF", "Refused", "clean_word", "domains", "hooks", "labels", "trademark",
           "trademark_status"]
