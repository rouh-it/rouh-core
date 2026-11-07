"""On their clock too: a time Rouh writes to somebody on another clock says whose it is.

Built by the nightly feature run, night 31 (the ledger's night 35), 6 November 2026 (task 94).
Asked "tell Marco we can talk at 3 tomorrow", Rouh wrote "15:00 tomorrow" on the person's own clock,
to somebody who lives seven hours behind. Either the other side wrote back "your time or mine?", or
they took it as theirs and the call was missed. Nothing in Rouh knew where the other person is, and
the model could not see it without being told.

The other person's own mail says it. The Date line of every email carries the clock it was written
on ("Tue, 3 Nov 2026 09:12:33 -0500"), and Gmail and most mail programs write it on the writer's own
time. So, while its switch is on, when Rouh writes an email in the person's own turn whose words
name a time of day ("15:00", "3pm", "at 9.30 am", "в 15 ч"), and does not already say whose clock
("your time", "CET", "UTC", ...), it reads, for each person it goes to, their newest email in the
person's mailboxes (Rouh's own and each read-only one, `ghosts.sources`) of the last `DAYS` days, in
plain rules and no model:

- the offset on its Date line, when it is not +0000 (a server's clock, which says nothing of where
  the writer is) and differs from the person's own clock now;
- each time the email names, said again on that clock ("15:00 for you is 08:00 for them").

`send_mail` is held until the email says whose clock it means (`clock_checked` sends it as it is);
after `draft_mail` the model is told, so it can change the draft. Nothing is kept, changed or sent
by this module: it reads with GET alone, and at most `SECONDS`.

**Whose.** The person's own mailboxes, by `org_id` and `user_id`, in their own turns only.

**Its switch** is `their_clock` (`rouh/switches.py`): off, an email is written as it was.
"""
from __future__ import annotations

import asyncio
import email.utils
import logging
import re
import time

log = logging.getLogger("rouh.their_clock")

SWITCH = "their_clock"
TITLE = ("On their clock too: before Rouh writes a time to somebody who writes from another time zone, "
         "it is told the hour on their clock")

#: How far back their newest email still says where they are, in days.
DAYS = 120
SECONDS = 8.0
MOST_TIMES = 4
MOST_PEOPLE = 6

FIELD = {"type": "boolean",
         "description": "Send it as written although a recipient writes from another time zone and the "
                        "email's times do not say whose clock: only after the email says it, or the person "
                        "says the times are fine as they are."}

#: A time of day: 15:00, 9:30, 3pm, 3 pm, 9.30am, 9 a.m., в 15 ч, 15 ч.
_TIMES = re.compile(
    r"(?<![\d:.])(?P<h24>[01]?\d|2[0-3]):(?P<m24>[0-5]\d)(?![\d:])(?:\s*(?P<ap1>[ap]\.?\s?m\.?)(?![a-z]))?"
    r"|(?<![\d:.])(?P<h12>1[0-2]|0?[1-9])(?:[.:](?P<m12>[0-5]\d))?\s*(?P<ap2>[ap]\.?\s?m\.?)(?![a-z])"
    r"|(?<![\d:.])(?P<hbg>[01]?\d|2[0-3])(?:[.:](?P<mbg>[0-5]\d))?\s*ч(?:аса)?\.?(?![а-я])",
    re.I)

#: Words that already say whose clock a time is on.
_SAID = re.compile(
    r"\b(?:your|my|our|their|his|her|local|own)\s+time\b|\btime\s+zone\b|\btimezone\b"
    r"|\b(?:utc|gmt|cet|cest|eet|eest|bst|est|edt|cst|cdt|pst|pdt|mst|mdt|ist|jst|aest|sgt)\b"
    r"|\b(?:sofia|london|new york|berlin|paris|lisbon|dubai|singapore|tokyo)\s+time\b"
    r"|ваше(?:то)? време|наше(?:то)? време|българско време|местно време|часова зона", re.I)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def times(body: str) -> list[tuple[int, int, str]]:
    """Each time of day the words name, as (hour 0-23, minute, the words as written), at most `MOST_TIMES`."""
    out: list[tuple[int, int, str]] = []
    for found in _TIMES.finditer(body or ""):
        g = found.groupdict()
        if g["h24"] is not None:
            hour, minute, ap = int(g["h24"]), int(g["m24"]), g["ap1"]
        elif g["h12"] is not None:
            hour, minute, ap = int(g["h12"]), int(g["m12"] or 0), g["ap2"]
        else:
            hour, minute, ap = int(g["hbg"]), int(g["mbg"] or 0), None
        if ap:
            pm = ap.lower().startswith("p")
            if hour > 12:
                continue
            hour = (hour % 12) + (12 if pm else 0)
        item = (hour, minute, found.group(0).strip())
        if item not in out:
            out.append(item)
        if len(out) >= MOST_TIMES:
            break
    return out


def says_whose(body: str) -> bool:
    return bool(_SAID.search(body or ""))


def offset_of(date_line: str) -> int | None:
    """The Date line's offset from UTC in minutes, or None when it has none or says +0000."""
    try:
        parsed = email.utils.parsedate_tz(date_line or "")
    except (TypeError, ValueError):
        return None
    if not parsed or parsed[9] is None or parsed[9] == 0:
        return None
    if "-0000" in (date_line or ""):
        return None
    return int(parsed[9] // 60)


def utc_said(minutes: int) -> str:
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def on_their_clock(hour: int, minute: int, mine: int, theirs: int) -> str:
    """"08:00", or "23:00 the day before", for a time on the person's clock said on theirs."""
    total = hour * 60 + minute + (theirs - mine)
    day = ""
    if total < 0:
        day = " the day before"
    elif total >= 24 * 60:
        day = " the next day"
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}{day}"


async def _newest_date(reader, address: str) -> dict | None:
    from . import ghosts

    found = await reader.search(f"from:{address} newer_than:{DAYS}d", 3)
    for one in found:
        head = await reader.summary(one["id"])
        named = ghosts._named(head)
        sender = ghosts.people(named.get("from", ""))
        if not sender or sender[0][1] != address:
            continue
        theirs = offset_of(named.get("date", ""))
        if theirs is None:
            continue
        return {"address": address, "name": sender[0][0], "offset": theirs, "at": ghosts._at(head),
                "date": named.get("date", "")}
    return None


async def find(who, addresses: list[str]) -> list[dict]:
    """For each address, the clock of their newest email found in any of the person's mailboxes."""
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
            log.info("their clock: %s could not be opened: %s", source.email, exc)
            continue
        if reader is None:
            continue
        for address in addresses[:MOST_PEOPLE]:
            try:
                got = await _newest_date(reader, address)
            except Exception as exc:  # noqa: BLE001
                log.info("their clock: %s in %s could not be read: %s", address, source.email, exc)
                continue
            if got and (got["at"] or 0) >= (best.get(address) or {}).get("at", 0):
                best[address] = got
    return [best[a] for a in addresses if a in best]


def said(found: list[dict], said_times: list[tuple[int, int, str]], zone, *, sending: bool,
         now: float | None = None) -> str:
    """The words for the model, or "" when everybody is on the person's clock."""
    from datetime import datetime

    now = now or time.time()
    off = datetime.fromtimestamp(now, zone).utcoffset()
    mine = int((off.total_seconds() if off else 0) // 60)
    lines = []
    for one in found:
        if one["offset"] == mine:
            continue
        gap = (mine - one["offset"]) / 60
        ahead = (f"{abs(gap):g} hour{'s' if abs(gap) != 1 else ''} "
                 + ("ahead of them" if gap > 0 else "behind them"))
        who = f"{one['name']} <{one['address']}>" if one.get("name") else one["address"]
        when = datetime.fromtimestamp(one["at"], zone).strftime("%-d %B") if one.get("at") else "lately"
        converted = "; ".join(f"{words} on the person's clock is {on_their_clock(h, m, mine, one['offset'])} "
                              f"on theirs" for h, m, words in said_times)
        lines.append(f"- {who} writes from {utc_said(one['offset'])} (the clock on their email of {when}); "
                     f"the person is on {utc_said(mine)}, {ahead}. {converted}.")
    if not lines:
        return ""
    head = ("On their clock too (read from the Date line of their own newest email). The email names a time "
            "and does not say whose clock it is on, and somebody it goes to is on another clock:\n"
            + "\n".join(lines) + "\n")
    if sending:
        return ("Not sent yet, and nobody was emailed. " + head
                + "Say the time on both clocks in the email (for example \"15:00 my time, 08:00 yours\"), "
                  "then send it again; if the times are already meant as theirs, or the person says so, "
                  "send it again with clock_checked.")
    return ("\n\n" + head + "If the times are on the person's clock, change the draft to say both clocks "
            "(for example \"15:00 my time, 08:00 yours\") before it goes, and say you did.")


async def note(who, body: str, addresses: list[str], zone, *, sending: bool) -> str:
    """Everything in one call, never longer than `SECONDS`, never raising: "" when there is nothing."""
    from asgiref.sync import sync_to_async

    from . import evolution

    try:
        said_times = times(body)
        if not said_times or not addresses or says_whose(body) or not await asyncio.to_thread(on, who):
            return ""
        found = await asyncio.wait_for(find(who, addresses), SECONDS)
        text = said(found, said_times, zone, sending=sending)
    except Exception as exc:  # noqa: BLE001 - the email goes on without it
        log.info("their clock: the look did not finish: %s", exc)
        return ""
    if not text:
        return ""
    await sync_to_async(evolution.used)(
        SWITCH, "told", who=who,
        detail=(("sending: " if sending else "drafting: ")
                + ", ".join(f"{one['address']} {utc_said(one['offset'])}" for one in found))[:200])
    return text


__all__ = ["FIELD", "SWITCH", "TITLE", "find", "note", "offset_of", "on", "on_their_clock", "said",
           "says_whose", "times"]
