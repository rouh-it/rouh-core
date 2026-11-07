"""In their language: an email Rouh writes goes in the language the other person writes in.

Built by the nightly feature run, night 32 of this Rouh (the ledger's night 36), 7 November 2026
(task 94). ‹owner› talks to Rouh in one language and writes to people in several: a supplier in
Sofia who has only ever written in Bulgarian, a partner in Warsaw who writes in English, a client
who writes in German. Asked in English "tell Ivan the offer is fine", Rouh wrote to Ivan in
English, because that was the language it was asked in, though every email Ivan ever sent ‹him› was
in Bulgarian. Nothing in Rouh knew which language a person writes in, and the model could not see it
without being told.

Their own mail says it. So, while its switch is on, when Rouh writes an email in the person's own
turn, it reads, for each person it goes to, their newest email in the person's mailboxes (Rouh's
own and each read-only one, `ghosts.sources`) of the last `DAYS` days, and tells the language of
what they wrote themselves (quotes and the signature cut off) and of the email, in plain rules and
no model: the share of Cyrillic letters, and for Latin letters the most common short words of each
language (`_WORDS`). When the email is in another language than everybody it goes to writes in:

- `send_mail` is held, and the model is told in which language each person writes, to write it
  again in theirs (`language_checked` sends it as it is: the person asked for that language, or
  the other side reads it well);
- after `draft_mail` the model is told the same, so it can change the draft.

A text too short to tell, or a person whose language cannot be told, is left alone. Nothing is kept,
changed or sent by this module: it reads with GET alone, and at most `SECONDS`.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`, in their own turns only.

**Its switch** is `their_language` (`rouh/switches.py`): off, an email is written as it was.
"""
from __future__ import annotations

import asyncio
import logging
import re

log = logging.getLogger("rouh.their_language")

SWITCH = "their_language"
TITLE = ("In their language: an email Rouh writes to somebody is told the language they write to you in, "
         "and is not sent in another one without saying so")

#: How far back their newest email still says what they write in, in days.
DAYS = 365
SECONDS = 8.0
MOST_PEOPLE = 6
#: Fewer letters than this, and the language is not told.
LEAST_LETTERS = 40

FIELD = {"type": "boolean",
         "description": "Send it in the language it is written in although a recipient writes to the person in "
                        "another: only when the person asked for this language, or says it is fine."}

NAMES = {"bg": "Bulgarian", "ru": "Russian", "en": "English", "de": "German", "fr": "French",
         "es": "Spanish", "it": "Italian", "pl": "Polish", "nl": "Dutch", "pt": "Portuguese"}

#: The most common short words of each language written in Latin letters.
_WORDS = {
    "en": set("the and you for that with this have will are your not but from please thanks thank "
              "would could can what when our about just let know also should".split()),
    "de": set("der die das und ich sie nicht mit ist wir ein eine für auf den dem bitte danke "
              "haben ihnen sind auch wie gerne viele grüße".split()),
    "fr": set("le la les et je vous pour que des une est pas avec nous sur merci dans bien "
              "cordialement votre bonjour".split()),
    "es": set("el la los las y que de por para con una muy gracias saludos usted estamos pero "
              "como hola nos".split()),
    "it": set("il che di per con una sono non grazie della gli ciao buongiorno cordiali saluti "
              "anche come questo".split()),
    "pl": set("się nie jest że na do dla jak czy ale dziękuję pozdrawiam proszę już będzie "
              "mamy tak oraz".split()),
    "nl": set("het een van de en ik je niet met voor dat zijn wij jullie bedankt groet graag "
              "ook maar".split()),
    "pt": set("o os que de não com uma para obrigado obrigada cumprimentos você estamos mas "
              "como olá".split()),
}
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def language(text: str) -> str | None:
    """"bg", "en", "de" ... for what a text is written in, or None when it cannot be told surely."""
    letters = _LETTER.findall(text or "")
    if len(letters) < LEAST_LETTERS:
        return None
    cyrillic = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    share = cyrillic / len(letters)
    if share >= 0.6:
        lower = (text or "").lower()
        return "ru" if ("ы" in lower or "э" in lower) and "ъ" not in lower else "bg"
    if share > 0.15:
        return None
    words = [w.lower() for w in _WORD.findall(text or "")]
    counts = {lang: sum(1 for w in words if w in common) for lang, common in _WORDS.items()}
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    best, second = ranked[0], ranked[1]
    if best[1] < 3 or best[1] < second[1] * 1.6:
        return None
    return best[0]


async def _newest_words(reader, address: str) -> dict | None:
    from . import ghosts

    found = await reader.search(f"from:{address} newer_than:{DAYS}d", 4)
    for one in found:
        got = await reader.message(one["id"])
        named = ghosts._named(got)
        sender = ghosts.people(named.get("from", ""))
        if not sender or sender[0][1] != address or ghosts.is_auto_reply(named):
            continue
        lang = language(ghosts.own_words(ghosts._body_text(got)))
        if lang is None:
            continue
        return {"address": address, "name": sender[0][0], "language": lang, "at": ghosts._at(got)}
    return None


async def find(who, addresses: list[str]) -> list[dict]:
    """For each address, the language of their newest email found in any of the person's mailboxes."""
    from asgiref.sync import sync_to_async

    from . import ghosts, runtime

    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None or not addresses:
        return []
    sources = await sync_to_async(ghosts.sources)(who, auth)
    best: dict[str, dict] = {}
    for source in sources:
        if source.needs_reconnect:
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("their language: %s could not be opened: %s", source.email, exc)
            continue
        if reader is None:
            continue
        for address in addresses[:MOST_PEOPLE]:
            try:
                got = await _newest_words(reader, address)
            except Exception as exc:  # noqa: BLE001
                log.info("their language: %s in %s could not be read: %s", address, source.email, exc)
                continue
            if got and (got["at"] or 0) >= (best.get(address) or {}).get("at", 0):
                best[address] = got
    return [best[a] for a in addresses if a in best]


def said(found: list[dict], written_in: str, zone, *, sending: bool) -> str:
    """The words for the model, or "" when the email is in a language they write in."""
    from datetime import datetime

    if not found or any(one["language"] == written_in for one in found):
        return ""
    lines = []
    for one in found:
        who = f"{one['name']} <{one['address']}>" if one.get("name") else one["address"]
        when = datetime.fromtimestamp(one["at"], zone).strftime("%-d %B %Y") if one.get("at") else "lately"
        lines.append(f"- {who} writes to the person in {NAMES[one['language']]} (their own email of {when}).")
    theirs = {one["language"] for one in found}
    want = NAMES[next(iter(theirs))] if len(theirs) == 1 else "the language each of them writes in"
    head = (f"In their language (read from their own newest email). The email is written in "
            f"{NAMES.get(written_in, written_in)}, and nobody it goes to writes in it:\n" + "\n".join(lines) + "\n")
    if sending:
        return ("Not sent yet, and nobody was emailed. " + head
                + f"Write it again in {want}, keeping what it says, then send it; if the person asked for "
                  f"{NAMES.get(written_in, written_in)}, or says it is fine as it is, send it again with "
                  "language_checked.")
    return ("\n\n" + head + f"Unless the person asked for {NAMES.get(written_in, written_in)}, change the draft to "
            f"{want}, keeping what it says, and say you did.")


async def note(who, body: str, addresses: list[str], zone, *, sending: bool) -> str:
    """Everything in one call, never longer than `SECONDS`, never raising: "" when there is nothing."""
    from asgiref.sync import sync_to_async

    from . import evolution

    try:
        written_in = language(body)
        if not written_in or not addresses or not await asyncio.to_thread(on, who):
            return ""
        found = await asyncio.wait_for(find(who, addresses), SECONDS)
        text = said(found, written_in, zone, sending=sending)
    except Exception as exc:  # noqa: BLE001 - the email goes on without it
        log.info("their language: the look did not finish: %s", exc)
        return ""
    if not text:
        return ""
    await sync_to_async(evolution.used)(
        SWITCH, "told", who=who,
        detail=(("sending: " if sending else "drafting: ") + f"written in {written_in}; "
                + ", ".join(f"{one['address']} {one['language']}" for one in found))[:200])
    return text


__all__ = ["FIELD", "NAMES", "SWITCH", "TITLE", "find", "language", "note", "on", "said"]
