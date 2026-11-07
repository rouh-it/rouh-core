"""Asked again: a request Petar keeps typing by hand, offered once as Clockwork work that does it.

Built by the nightly feature run, night 11, 14 October 2026 (task 94, idea I-090), after Gemini's
Tasks page began suggesting the recurring jobs a person keeps asking for by hand (12 October
2026). Rouh already has the other half: Clockwork runs scheduled work by itself, as `do` work,
and says what it found (`rouh/reminders.py`). What nothing did was notice that the same request
had come in again and again, typed by hand, and say so at the moment it comes in the third time.

So when one of his own messages is close to two or more of his earlier ones, from different days
in the last four weeks, the turn's prompt says so beside the clock: when he asked it, in his own
words, and the rhythm and time those asks fall into. The model answers him as usual and then
offers, in one sentence, to do it for him by itself from then on; a yes is made with the usual
`schedule` tool as `do` work. Nothing is scheduled without his yes.

**No model call of its own.** Which messages are the same request is decided by code: the words
of each message that carry its meaning (`_words`, stop words out, stems in), and two messages
are the same request when they share most of them, two at the least (`similar`, `SIMILAR`). A
message of fewer than `LEAST_WORDS` such words ("yes", "go on") is never one.

**Once.** An offer is kept by its words in his own `user_settings` (`KEPT`), and a request close
to one already offered is never offered again, whatever he answered. Work already on Clockwork
that is close to it is not offered either.

**Only his own turns.** Never a note of Rouh's own software, the heartbeat's turn, an unattended
turn or a mail's (`brain._asked_again_block`); only the owner's messages are read, by
`answered_in_chat.his_messages`, and what is kept is kept under his user and organisation.

**Its switch** is `asked_again` (`rouh/switches.py`), off until Petar keeps it in Mutations: off,
nothing is read, nothing is offered and nothing is kept.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime

log = logging.getLogger("rouh.asked_again")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "asked_again"
TITLE = ("Asked again: a request you keep typing by hand is offered, once, as Clockwork work "
         "that does it for you")

#: How far back his earlier messages are read, in days.
LOOK_BACK_DAYS = float(os.environ.get("ASKED_AGAIN_DAYS") or 28)
#: How many earlier days he must have asked it on, besides now.
LEAST_DAYS = 2
#: The fewest meaningful words a message needs to be a request at all.
LEAST_WORDS = 2
#: Two messages are the same request when they share this much of their words (`similar`).
SIMILAR = 0.67
#: A message newer than this many seconds is the one being answered, never an earlier ask.
NOW_SECONDS = 120
#: The setting the offers are kept in, and how many are kept.
KEPT = "asked_again_offered"
KEEP = 200
#: How much of each earlier ask is quoted.
QUOTE_CHARS = 160
#: The most earlier asks named in the prompt.
MOST_NAMED = 4

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_DAY_IDS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


#: Words that carry no request of their own, besides `answered_in_chat`'s stop words.
_ALSO_STOP = frozenset("""
what's whats anything anyone tell whether did does there any me show give find look looking
update updates latest newest new last recent
""".split())
_WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)?|\d{2,}", re.UNICODE)


def _stem(w: str) -> str:
    """A word without its ending, roughly: replied, replies and reply are one."""
    w = w.split("'")[0]
    for end in ("ings", "ing", "ied", "ies", "ed", "es", "s", "y"):
        if len(w) > len(end) + 2 and w.endswith(end):
            return w[:-len(end)]
    return w


def _words(text: str) -> set[str]:
    """The words of a message that say what it asks for, stemmed."""
    from .answered_in_chat import _STOP

    out = set()
    for w in _WORD.findall(str(text or "").lower().replace("\u2019", "'")):
        if w in _STOP or w in _ALSO_STOP or len(w) < 3:
            continue
        out.add(_stem(w))
    return out


def similar(a: set[str], b: set[str]) -> float:
    """How much two requests share: twice the words they share over all their words (Dice), and
    nothing when they share fewer than two."""
    shared = len(a & b)
    if shared < 2:
        return 0.0
    return 2 * shared / (len(a) + len(b))


def _zone():
    from . import clock

    try:
        return clock.zone()
    except Exception:  # noqa: BLE001 - the server's own zone is a fair second
        return None


def _local(ts: float, zone) -> datetime:
    return datetime.fromtimestamp(ts, zone) if zone is not None else datetime.fromtimestamp(ts)


def rhythm(times: list[datetime]) -> dict:
    """The rhythm and time a list of asks falls into: every weekday, every <day> or every day,
    a little before the earliest of them, to five minutes. {repeat, days, at, words}."""
    days = sorted({t.weekday() for t in times})
    dates = {t.date() for t in times}
    if len(days) == 1 and len(dates) >= 2:
        repeat, on_days, said = "weekly", [_DAY_IDS[days[0]]], "every " + _WEEKDAYS[days[0]]
    elif days and max(days) <= 4:
        repeat, on_days, said = "weekdays", [], "every weekday"
    else:
        repeat, on_days, said = "daily", [], "every day"
    first = min(t.hour * 60 + t.minute for t in times)
    at = max(0, first - 10) // 5 * 5
    hhmm = f"{at // 60:02d}:{at % 60:02d}"
    return {"repeat": repeat, "days": on_days, "at": hhmm, "words": f"{said} at {hhmm}"}


def _held(who) -> dict:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {k: v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _keep(who, key: str, entry: dict) -> None:
    from .models import UserSetting

    held = _held(who)
    held[key] = entry
    newest = sorted(held, key=lambda k: held[k].get("at") or 0, reverse=True)[:KEEP]
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps({k: held[k] for k in newest}, ensure_ascii=False),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _scheduled(who) -> list[set[str]]:
    """The words of everything on his Clockwork that is still to happen."""
    from .models import Reminder

    rows = (Reminder.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "")
            .exclude(state="done")
            .values_list("title", "what"))
    return [_words(f"{t or ''} {w or ''}") for t, w in rows]


def find(who, text: str, now: float | None = None) -> dict | None:
    """The earlier asks of the same request as `text`, when there are enough of them and it was
    never offered: {words, asks: [{ts, text, when}], rhythm}, or None."""
    from .answered_in_chat import his_messages

    now = now or time.time()
    words = _words(text)
    if len(words) < LEAST_WORDS:
        return None
    zone = _zone()
    today = _local(now, zone).date()
    asks = []
    for m in his_messages(now - LOOK_BACK_DAYS * 86400):
        if m["ts"] > now - NOW_SECONDS:
            continue
        if similar(words, _words(m["text"])) >= SIMILAR:
            asks.append(m)
    days = {_local(m["ts"], zone).date() for m in asks} - {today}
    if len(days) < LEAST_DAYS:
        return None
    for entry in _held(who).values():
        if similar(words, set(entry.get("words") or [])) >= SIMILAR:
            return None
    if any(similar(words, done) >= SIMILAR * 0.75 for done in _scheduled(who)):
        return None
    # One ask a day is named: the first of each day, newest days first.
    firsts: dict = {}
    for m in sorted(asks, key=lambda m: m["ts"]):
        firsts.setdefault(_local(m["ts"], zone).date(), m)
    named = sorted(firsts.values(), key=lambda m: m["ts"], reverse=True)[:MOST_NAMED]
    times = [_local(m["ts"], zone) for m in firsts.values()] + [_local(now, zone)]
    return {
        "words": sorted(words),
        "asks": [{"ts": m["ts"], "text": " ".join(m["text"].split())[:QUOTE_CHARS],
                  "when": _local(m["ts"], zone).strftime("%A %d %B at %H:%M").replace(" 0", " ")}
                 for m in sorted(named, key=lambda m: m["ts"])],
        "days": len(days),
        "rhythm": rhythm(times),
    }


def block(found: dict) -> str:
    """What the turn's prompt is told about a request asked again."""
    r = found["rhythm"]
    asks = "; ".join(f"on {a['when']}: \"{a['text']}\"" for a in found["asks"])
    days = (f", and repeating on {', '.join(r['days'])}" if r["days"] else "")
    return (
        "Asked again: ‹owner› has asked for this by hand on "
        f"{found['days']} other days in the last four weeks - {asks}. Answer ‹his› message now as "
        "you always would. Then end with one short sentence offering to do it for ‹him› by itself "
        f"from now on, {r['words']}, as scheduled work on Clockwork, so ‹he› no longer has to ask; "
        "say it is because ‹he› has asked for it before. Only if ‹he› says yes, add it with the "
        f"schedule tool: kind do, repeat {r['repeat']}{days}, at {r['at']}, its title naming the "
        "thing, and its what ‹his› request in full. Offer it this once, in this answer only; it "
        "is never offered again.")


def for_turn(who, text: str) -> str:
    """The prompt's block for this message, or "" (off, too short, not asked again, offered
    before). Keeps the offer the moment it is made, so it is made once. Never raises."""
    try:
        if who is None or not on(getattr(who, "org_id", None)):
            return ""
        found = find(who, text)
        if found is None:
            return ""
        key = hashlib.sha1(" ".join(found["words"]).encode()).hexdigest()[:16]
        _keep(who, key, {"at": time.time(), "words": found["words"], "text": text[:QUOTE_CHARS],
                         "rhythm": found["rhythm"]["words"]})
        from . import evolution

        evolution.used(SWITCH, "offered_again", who=who,
                       detail=f"offered after {found['days']} earlier days: {text[:120]}")
        log.info("asked again: offered %r as work %s", text[:80], found["rhythm"]["words"])
        return block(found)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("asked again could not be read for this message")
        return ""


__all__ = ["SWITCH", "TITLE", "block", "find", "for_turn", "on", "rhythm", "similar"]
