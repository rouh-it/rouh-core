"""Promises in mail: a sentence in an email that promises something by a day, read in plain rules.

Built by the nightly feature run, night 32 of this Rouh (7 November 2026, task 94), for three genes
that read the same sentences: Your word, by mail (`rouh/my_word.py`, what the person promised by
email, in the morning brief when its day comes), Promised to you by mail (`rouh/promised_to_you.py`,
asked in words, what people promised the person by email and has not come) and If it does not come
(`rouh/promise_watch.py`, a button on the inbox card). Slack had this since 16 October 2026
(`rouh/slack_promises.py`, read by a model); mail had nothing, though most of what is promised to
‹him›, and by ‹him›, outside the company is promised by email: "I'll send you the signed contract
by Friday", "we will get back to you next week", "ще ти изпратя офертата утре".

**What counts.** A sentence of what the writer wrote themselves (quoted mail, a forward and the
signature cut off, `ghosts.own_words`) that:

1. says the writer will do something: "I'll", "I will", "we will", "I am going to", "you'll have
   it", "ще ти изпратя", "ще ви върна отговор" and the like, with a verb of doing (send, share,
   get back, confirm, finish, pay, sign ...);
2. names when: today, tonight, end of day, tomorrow, a weekday, this or next week, the end of the
   week or the month, "in 3 days", a date ("10 November", "November 10", "10.11", "2026-11-10"),
   in English or in Bulgarian;
3. is not a question ("Shall I send it tomorrow?") and not about the past ("I sent it on Monday").

The day is worked out from the email's own day on the person's clock: "Friday" in an email of
Wednesday is two days later, and in an email of Friday the Friday after.

Nothing here reads a mailbox, keeps anything or asks a model; `scan_sent` and `scan_received` read
one mailbox with GET alone, through the readers `rouh/ghosts.py` already uses.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import date, datetime, timedelta

log = logging.getLogger("rouh.mail_promises")

#: At most this many emails are read in one mailbox, and this many people on one.
MOST_EMAILS = 60
MOST_PEOPLE = 8
#: A later email to (or from) the same people this soon after does not count as the promise met.
SAME_BREATH = 120

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5,
             "sunday": 6, "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3,
             "fri": 4, "sat": 5, "sun": 6,
             "понеделник": 0, "вторник": 1, "сряда": 2, "сряда.": 2, "четвъртък": 3, "петък": 4,
             "събота": 5, "неделя": 6}
_MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
           "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
           "януари": 1, "февруари": 2, "март": 3, "април": 4, "май": 5, "юни": 6, "юли": 7,
           "август": 8, "септември": 9, "октомври": 10, "ноември": 11, "декември": 12}
_MONTHS.update({m[:3]: n for m, n in list(_MONTHS.items()) if m.isascii()})
_MONTHS["sept"] = 9

_EN_VERB = (r"send|share|forward|get\s+back|come\s+back|revert|reply|respond|follow\s+up|deliver|"
            r"prepare|finish|complete|provide|update|confirm|have\s+(?:it|this|that|them|the)|"
            r"let\s+you\s+know|check|review|sign|pay|transfer|write|draft|book|schedule|call|"
            r"look\s+into|look\s+at|put\s+together|circle\s+back|submit|upload|return|ship|issue|"
            r"get\s+(?:it|this|that|them|the|you)|make\s+sure|sort|fix|set\s+up|arrange|organi[sz]e")
#: Somebody saying they will do something.
_EN = re.compile(
    r"(?<![\w'])(?:I|we)\s*(?:'ll|’ll|\s+will|\s+shall|'m\s+going\s+to|’m\s+going\s+to|\s+am\s+going\s+to|"
    r"'re\s+going\s+to|’re\s+going\s+to|\s+are\s+going\s+to|\s+plan\s+to|\s+aim\s+to|\s+promise\s+to|"
    r"\s+expect\s+to|\s+hope\s+to|\s+intend\s+to)\s+(?:(?:try\s+to|be\s+able\s+to|definitely|also|"
    r"certainly|surely|then|still|aim\s+to|make\s+sure\s+to|get\s+to)\s+)*(?:" + _EN_VERB + r")\b"
    r"|(?<![\w'])you\s*(?:'ll|’ll|\s+will|\s+should)\s+(?:have|get|receive|hear\s+from\s+(?:me|us))\b"
    r"|(?<![\w'])(?:it|this|that|they|the\s+\w+)\s+(?:will|should)\s+be\s+(?:with\s+you|in\s+your\s+inbox|"
    r"ready|sent|done|delivered)\b",
    re.IGNORECASE)
_BG_VERB = (r"изпрат|прат|върн|отговор|каж|потвърд|звънн|обад|сподел|подготв|приготв|завърш|"
            r"плат|преведе|преведа|напиш|подпиш|провер|прегледа|уточн|организир|резервир|"
            r"пусн|качим|кача|предостав|оправ|направ|дам|дадем|пиш")
_BG = re.compile(
    r"(?<![а-яА-Я])ще\s+(?:(?:ти|ви|Ви|го|я|ги|се|му|ѝ|им|още|веднага|днес|утре)\s+){0,3}(?:" + _BG_VERB + r")",
    re.IGNORECASE)
#: A sentence about the past, or a question, promises nothing.
_PAST = re.compile(r"\b(?:sent|shared|forwarded|delivered|signed|paid|did|attached|have\s+sent|"
                   r"has\s+been|was|were)\b(?![\s\w]{0,12}\b(?:will|'ll)\b)", re.IGNORECASE)
_IF_YOU = re.compile(r"^\s*(?:if\s+you|in\s+case|should\s+you|ако\s+(?:ти|ви|Ви))\b", re.IGNORECASE)

_D = r"(?:by|on|until|till|before|this|next|coming|до|в|във|на|този|тази|следващия|следващата|другия)"
_WHEN = re.compile(
    r"(?P<today>\b(?:today|tonight|this\s+(?:evening|afternoon)|end\s+of\s+(?:the\s+)?day|EOD|COB|later\s+today)\b|"
    r"(?<![а-я])(?:днес|довечера|до\s+края\s+на\s+деня)(?![а-я]))"
    r"|(?P<tomorrow>\b(?:tomorrow|tmrw)\b|(?<![а-я])(?:утре|утре\s+сутринта)(?![а-я]))"
    r"|(?P<after_tomorrow>\bthe\s+day\s+after\s+tomorrow\b|(?<![а-я])вдругиден(?![а-я]))"
    r"|(?P<weekend>\b(?:(?:by|before)\s+)?(?:the\s+)?(?:end\s+of\s+(?:the|this)\s+week|this\s+week)\b|"
    r"(?<![а-я])(?:до\s+края\s+на\s+(?:седмицата|тази\s+седмица)|тази\s+седмица)(?![а-я]))"
    r"|(?P<nextweek>\b(?:(?:by\s+)?(?:the\s+)?end\s+of\s+next\s+week|next\s+week|early\s+next\s+week)\b|"
    r"(?<![а-я])(?:следващата\s+седмица|до\s+края\s+на\s+следващата\s+седмица|другата\s+седмица)(?![а-я]))"
    r"|(?P<month>\b(?:by\s+)?(?:the\s+)?end\s+of\s+(?:the|this)\s+month\b|(?<![а-я])до\s+края\s+на\s+месеца(?![а-я]))"
    r"|(?P<indays>\bin\s+(?P<n>\d{1,2}|a\s+couple\s+of|two|three|a\s+few)\s+(?:working\s+|business\s+)?days?\b|"
    r"(?<![а-я])след\s+(?P<nbg>\d{1,2}|два|три|няколко)\s+дни(?![а-я]))"
    r"|(?P<wd>\b(?:(?:" + _D + r")\s+)?(?P<next>next\s+)?(?P<day>monday|tuesday|wednesday|thursday|friday|"
    r"saturday|sunday|mon|tues?|wed|thu(?:rs?)?|fri)\b\.?|"
    r"(?<![а-я])(?:(?:до|в|във|на|следващия|следващата|другия)\s+)?(?P<daybg>понеделник|вторник|сряда|"
    r"четвъртък|петък|събота|неделя)(?![а-я]))"
    r"|(?P<dm>\b(?P<d1>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<m1>january|february|march|april|may|june|"
    r"july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\b\.?|"
    r"(?<![\w])(?P<d1bg>\d{1,2})\s+(?P<m1bg>януари|февруари|март|април|май|юни|юли|август|септември|"
    r"октомври|ноември|декември)(?![а-я]))"
    r"|(?P<md>\b(?P<m2>january|february|march|april|may|june|july|august|september|october|november|"
    r"december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?\s+(?P<d2>\d{1,2})(?:st|nd|rd|th)?\b)"
    r"|(?P<iso>\b20\d\d-\d\d-\d\d\b)"
    r"|(?P<dotted>(?<![\d.])(?P<d3>[0-3]?\d)[./](?P<m3>[01]\d)(?:[./](?P<y3>20\d\d|\d\d))?(?!\d)(?!\.\d))",
    re.IGNORECASE)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")
_WORDNUM = {"a couple of": 2, "two": 2, "three": 3, "a few": 3, "два": 2, "три": 3, "няколко": 3}


def _friday_of(d: date, weeks: int = 0) -> date:
    monday = d - timedelta(days=d.weekday()) + timedelta(weeks=weeks)
    friday = monday + timedelta(days=4)
    if weeks == 0 and d.weekday() >= 5:
        friday += timedelta(weeks=1)
    return friday


def _near_year(day: date, month: int, num: int, year: int | None = None) -> date | None:
    try:
        if year:
            return date(year if year > 100 else 2000 + year, month, num)
        found = date(day.year, month, num)
        if (day - found).days > 60:
            found = date(day.year + 1, month, num)
        return found
    except ValueError:
        return None


def due_of(found: re.Match, sent: date) -> date | None:
    """The day a `_WHEN` match names, counted from the day the email was written."""
    g = found.groupdict()
    if g["today"]:
        return sent
    if g["tomorrow"]:
        return sent + timedelta(days=1)
    if g["after_tomorrow"]:
        return sent + timedelta(days=2)
    if g["weekend"]:
        return _friday_of(sent)
    if g["nextweek"]:
        return _friday_of(sent, 1) if sent.weekday() < 5 else _friday_of(sent)
    if g["month"]:
        nxt = (sent.replace(day=28) + timedelta(days=4))
        return nxt - timedelta(days=nxt.day)
    if g["indays"]:
        raw = (g["n"] or g["nbg"] or "").lower()
        n = int(raw) if raw.isdigit() else _WORDNUM.get(raw, 3)
        return sent + timedelta(days=n)
    if g["wd"]:
        name = (g["day"] or g["daybg"] or "").lower().rstrip(".")
        wd = _WEEKDAYS.get(name)
        if wd is None:
            return None
        ahead = (wd - sent.weekday()) % 7 or 7
        out = sent + timedelta(days=ahead)
        nxt = bool(g["next"]) or found.group(0).lower().lstrip().startswith(("next", "следващ", "другия"))
        if nxt and sent.weekday() < 5 and wd > sent.weekday():
            out += timedelta(weeks=1)        # "next Friday" on a Wednesday is next week's
        return out
    if g["dm"]:
        mon = (g["m1"] or g["m1bg"] or "").lower().rstrip(".")
        month = _MONTHS.get(mon) or _MONTHS.get(mon[:3])
        return _near_year(sent, month, int(g["d1"] or g["d1bg"])) if month else None
    if g["md"]:
        mon = g["m2"].lower().rstrip(".")
        month = _MONTHS.get(mon) or _MONTHS.get(mon[:3])
        return _near_year(sent, month, int(g["d2"])) if month else None
    if g["iso"]:
        try:
            return date.fromisoformat(g["iso"])
        except ValueError:
            return None
    if g["dotted"]:
        num, month = int(g["d3"]), int(g["m3"])
        if not (1 <= month <= 12 and 1 <= num <= 31):
            return None
        year = int(g["y3"]) if g["y3"] else None
        return _near_year(sent, month, num, year)
    return None


def promises(text: str, sent: date) -> list[dict]:
    """Each promise with a day in what the writer wrote: {sentence, due (a date), when (the words)}.

    `text` is the email's plain text; quoted mail and the signature are cut off here. At most three.
    """
    from . import ghosts

    out: list[dict] = []
    for piece in _SENTENCES.split(ghosts.own_words(text or "")[:6000])[:80]:
        sentence = " ".join(piece.split())
        if len(sentence) < 8 or sentence.endswith("?") or _IF_YOU.search(sentence):
            continue
        said = _EN.search(sentence) or _BG.search(sentence)
        if not said:
            continue
        # The day said after the promise first ("I'll send it by Friday"), else before it
        # ("Tomorrow I will send it").
        after = [m for m in _WHEN.finditer(sentence) if m.start() >= said.start()]
        before = [m for m in _WHEN.finditer(sentence) if m.end() <= said.start()]
        when = due = None
        for one in after + before[::-1]:
            day = due_of(one, sent)
            if day is not None and sent <= day and (day - sent).days <= 120:
                when, due = one, day
                break
        if when is None:
            continue
        clipped = sentence if len(sentence) <= 240 else sentence[:239].rstrip() + "…"
        out.append({"sentence": clipped, "due": due, "when": when.group(0).strip().rstrip(".,;")})
        if len(out) >= 3:
            break
    return out


def key_of(mailbox: str, message_id: str, sentence: str) -> str:
    return hashlib.sha1(f"{mailbox}|{message_id}|{sentence}".encode("utf-8")).hexdigest()[:14]


def day_words(due: date, today: date) -> str:
    """"today", "tomorrow", "yesterday", "Friday 6 November, 3 days ago", "Monday 9 November"."""
    gap = (due - today).days
    named = due.strftime("%A %-d %B")
    if gap == 0:
        return "today"
    if gap == 1:
        return "tomorrow"
    if gap == -1:
        return f"yesterday, {named}"
    if gap < 0:
        return f"{named}, {-gap} days ago"
    return named


def _is_list(named: dict) -> bool:
    return bool(named.get("list-id") or named.get("list-unsubscribe")
                or (named.get("precedence") or "").lower() in ("bulk", "list", "junk"))


async def _later(reader, query: str, after: float, not_id: str) -> bool:
    """Whether a search finds an email after `after` (by more than `SAME_BREATH`), other than `not_id`."""
    from . import ghosts

    try:
        found = await reader.search(f"{query} after:{int(after)}", 5)
    except Exception as exc:  # noqa: BLE001 - not known is not met
        log.info("promises: could not look for later mail: %s", exc)
        return False
    for one in found[:5]:
        if one.get("id") == not_id:
            continue
        try:
            head = await reader.headers(one["id"])
        except Exception:  # noqa: BLE001
            continue
        if ghosts.is_auto_reply(ghosts._named(head)):
            continue
        if ghosts._at(head) > after + SAME_BREATH:
            return True
    return False


async def scan_sent(reader, zone, *, days: int, mailbox: str = "", person: str = "",
                    now: float | None = None) -> list[dict]:
    """The promises with a day in the person's own sent mail of the last `days` days, each with
    whether they wrote to the same people again since (`wrote_since`). `person` narrows it to mail
    sent to one name or address (Between you and them, `rouh/between_us.py`)."""
    from . import ghosts

    now = now or time.time()
    own = await reader.addresses()
    query = f"in:sent newer_than:{days}d"
    if person:
        query += f" to:({person})" if " " in person else f" to:{person}"
    found = await reader.search(query, MOST_EMAILS)
    out: list[dict] = []
    for got in await ghosts._gathered([reader.message(one["id"]) for one in found[:MOST_EMAILS]]):
        if isinstance(got, BaseException) or not isinstance(got, dict):
            continue
        named = ghosts._named(got)
        if _is_list(named) or ghosts._CALENDAR_SUBJECT.match(named.get("subject") or ""):
            continue
        to, cc = ghosts.people(named.get("to", "")), ghosts.people(named.get("cc", ""))
        if len(to) + len(cc) > MOST_PEOPLE:
            continue
        them = [(n, a) for n, a in to if a not in own and not ghosts.is_machine(a)]
        if not them:
            continue
        at = ghosts._at(got)
        sent = datetime.fromtimestamp(at, zone).date()
        for one in promises(ghosts._body_text(got), sent):
            out.append({"key": key_of(mailbox, got.get("id") or "", one["sentence"]),
                        "message_id": got.get("id") or "", "thread_id": got.get("threadId") or "",
                        "subject": (named.get("subject") or "(no subject)")[:200], "at": at,
                        "to": [{"name": n[:80], "email": a} for n, a in them[:4]], **one})
    for item in out:
        item["wrote_since"] = False
        for person in item["to"][:3]:
            if await _later(reader, f"in:sent to:{person['email']}", item["at"], item["message_id"]):
                item["wrote_since"] = True
                break
    return out


async def scan_received(reader, zone, *, days: int, person: str = "", mailbox: str = "",
                        now: float | None = None) -> list[dict]:
    """The promises with a day made to the person in their inbox of the last `days` days, by people,
    each with whether the one who promised wrote again since (`wrote_since`)."""
    from . import ghosts

    now = now or time.time()
    own = await reader.addresses()
    query = (f"in:inbox newer_than:{days}d -in:sent -category:promotions -category:social "
             f"-category:updates -category:forums")
    if person:
        # One word as Gmail's from: takes it; several in brackets, so they are read as one.
        query += f" from:({person})" if " " in person else f" from:{person}"
    found = await reader.search(query, MOST_EMAILS)
    out: list[dict] = []
    for got in await ghosts._gathered([reader.message(one["id"]) for one in found[:MOST_EMAILS]]):
        if isinstance(got, BaseException) or not isinstance(got, dict):
            continue
        named = ghosts._named(got)
        labels = set(got.get("labelIds") or [])
        if labels & {"SENT", "DRAFT", "SPAM", "TRASH"} or _is_list(named) or ghosts.is_auto_reply(named):
            continue
        sender = (ghosts.people(named.get("from", "")) or [("", "")])[0]
        if not sender[1] or sender[1] in own or ghosts.is_machine(sender[1]):
            continue
        to, cc = ghosts.people(named.get("to", "")), ghosts.people(named.get("cc", ""))
        if len(to) + len(cc) > MOST_PEOPLE:
            continue
        at = ghosts._at(got)
        sent = datetime.fromtimestamp(at, zone).date()
        for one in promises(ghosts._body_text(got), sent):
            out.append({"key": key_of(mailbox, got.get("id") or "", one["sentence"]),
                        "message_id": got.get("id") or "", "thread_id": got.get("threadId") or "",
                        "subject": (named.get("subject") or "(no subject)")[:200], "at": at,
                        "name": sender[0][:80], "email": sender[1], **one})
    for item in out:
        item["wrote_since"] = await _later(reader, f"from:{item['email']} -in:sent", item["at"],
                                           item["message_id"])
    return out


__all__ = ["day_words", "due_of", "key_of", "promises", "scan_received", "scan_sent"]
