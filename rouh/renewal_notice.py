"""Renews soon: an email that says a subscription or a trial will renew or charge is told at once.

Built by the nightly feature run, night 31 (the ledger's night 35), 6 November 2026 (task 94).
A service says it before it takes the money: "Your plan renews on 20 November for $29", "Your free
trial ends in 3 days, then you will be charged €12 a month". That email lands in Rouh's inbox among
the machines' mail, which Rouh passes over as junk (`mail_alerts.junk_because`), and the services a
nightly run signs up to write to `rouh+<service>@...`, which is set aside for the run. Nobody reads
it, and the person finds the renewal on the card statement, after it charged.

So, while its switch is on, every email that reaches Rouh's inbox (`mail_alerts`, before it is
passed over) is read in plain rules, no model:

1. **It says a renewal or a charge is coming** (`COMING`): "will renew", "renews on", "auto-renew",
   "trial ends", "will be charged", "upcoming payment", "подновява", "пробният период изтича", ...
   and is not a receipt for money already taken (`TAKEN`) or a person's own email.
2. **When**: the first date it names after those words, in the common shapes ("20 November 2026",
   "November 20", "2026-11-20", "20.11.2026"), or "in 3 days"; a date already past is not told.
3. **How much**: the first amount it names ("$29.00", "€12", "12 EUR", "24 лв.").
4. **What**: the sender's name, or its domain.

A notice says it at once (`rouh/notices.py`): what renews, when (and in how many days), for how much,
the subject, and the address it came to when it is one a nightly run signed up with, with Open the
email. Left alone, it goes to the phone, as every notice does. One email is told once.

**Whose.** Rouh's own connected inbox and the person it belongs to, by `org_id` and `user_id`.

**Its switch** is `renewal_notice` (`rouh/switches.py`): off, nothing is read or told.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime, timedelta

log = logging.getLogger("rouh.renewal_notice")

SWITCH = "renewal_notice"
TITLE = ("Renews soon: an email saying a subscription or trial will renew or charge is told to you at "
         "once, with what, when and how much")

#: A renewal further away than this is not worth a notice today, in days.
MOST_DAYS = 45
OPENS = "renewal_notice_opens"

COMING = re.compile(
    r"\bwill (?:automatically |auto-?)?(?:renew|be renewed|be (?:charged|billed)|charge|bill)\b"
    r"|\b(?:renews|renewing|is renewing) (?:on|in|soon|automatically)\b|\bauto-?renew"
    r"|\b(?:upcoming|scheduled|next) (?:renewal|charge|payment|billing|invoice)\b"
    r"|\brenewal (?:notice|reminder|date|is coming)\b|\bsubscription (?:will|renews|is about to)\b"
    r"|\b(?:free )?trial (?:ends|will end|is ending|expires|will expire|is about to end|period ends)\b"
    r"|\bbefore (?:you(?:'re| are)|we) (?:charged|charge you|bill you)\b"
    r"|ще бъде (?:подновен|подновена|таксуван|таксувана|удържан)|подновява(?:не)? се|автоматично подновяване"
    r"|пробният период (?:изтича|приключва)|предстоящо (?:плащане|подновяване)",
    re.I)
TAKEN = re.compile(
    r"\b(?:receipt|payment (?:received|successful|confirmation)|thank(?:s| you) for your (?:payment|purchase|order)"
    r"|(?:has|have) been (?:charged|renewed|billed)|was (?:charged|renewed|billed)|successfully renewed"
    r"|payment failed|card was declined|refund)\b|разписка|плащането е получено|успешно подновен", re.I)

_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], 1)}
_MONTHS.update({k[:3]: v for k, v in list(_MONTHS.items())})
_MONTHS["sept"] = 9
_BG_MONTHS = {m: i for i, m in enumerate(
    ["януари", "февруари", "март", "април", "май", "юни", "юли", "август", "септември", "октомври",
     "ноември", "декември"], 1)}
_M = "(" + "|".join(sorted(list(_MONTHS) + list(_BG_MONTHS), key=len, reverse=True)) + r")\.?"
_DATES = re.compile(
    r"(?P<iso>(?P<iy>20\d\d)-(?P<im>[01]?\d)-(?P<id>[0-3]?\d))"
    r"|(?P<dot>(?P<dd>[0-3]?\d)[./](?P<dm>[01]?\d)[./](?P<dy>20\d\d))"
    r"|(?P<dmy>(?P<a_d>[0-3]?\d)(?:st|nd|rd|th)?\s+(?:of\s+)?" + _M.replace("(", "(?P<a_m>", 1)
    + r"(?:,?\s+(?P<a_y>20\d\d))?)"
    r"|(?P<mdy>" + _M.replace("(", "(?P<b_m>", 1) + r"\s+(?P<b_d>[0-3]?\d)(?:st|nd|rd|th)?(?:,?\s+(?P<b_y>20\d\d))?)"
    r"|(?P<rel>in (?P<n>\d{1,2}) days?|tomorrow|след (?P<bn>\d{1,2}) дни|утре)",
    re.I)
_AMOUNT = re.compile(
    r"(?:(?P<cur>US\$|\$|€|£|USD|EUR|GBP|BGN)\s?(?P<num>\d[\d,]*(?:\.\d{1,2})?))"
    r"|(?:(?P<num2>\d[\d,]*(?:[.,]\d{1,2})?)\s?(?P<cur2>USD|EUR|GBP|BGN|лв\.?|евро|€|\$))",
    re.I)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _month(name: str) -> int:
    low = name.lower().rstrip(".")
    return _MONTHS.get(low) or _BG_MONTHS.get(low) or 0


def when(text: str, sent: date) -> date | None:
    """The first date the words name, read against the day the email was sent; None when none is."""
    for found in _DATES.finditer(text or ""):
        g = found.groupdict()
        try:
            if g["iso"]:
                got = date(int(g["iy"]), int(g["im"]), int(g["id"]))
            elif g["dot"]:
                got = date(int(g["dy"]), int(g["dm"]), int(g["dd"]))
            elif g["dmy"] or g["mdy"]:
                day, month, year = ((g["a_d"], g["a_m"], g["a_y"]) if g["dmy"] else (g["b_d"], g["b_m"], g["b_y"]))
                month_n = _month(month)
                if not month_n:
                    continue
                got = date(int(year) if year else sent.year, month_n, int(day))
                if not year and got < sent - timedelta(days=7):
                    got = date(sent.year + 1, month_n, int(day))
            else:
                n = g["n"] or g["bn"]
                got = sent + timedelta(days=int(n) if n else 1)
        except ValueError:
            continue
        return got
    return None


def amount(text: str) -> str:
    found = _AMOUNT.search(text or "")
    if not found:
        return ""
    if found.group("cur"):
        cur, num = found.group("cur"), found.group("num")
        return f"{cur}{num}" if cur in ("$", "€", "£", "US$") else f"{num} {cur.upper()}"
    cur = found.group("cur2")
    return f"{found.group('num2')} {cur}" if cur not in ("€", "$") else f"{cur}{found.group('num2')}"


def service_of(sender: str) -> str:
    name, address = email.utils.parseaddr(sender or "")
    name = name.strip().strip('"')
    for cut in (" billing", " team", " support", " notifications", " no-reply"):
        if name.lower().endswith(cut):
            name = name[: -len(cut)].strip()
    if name:
        return name[:60]
    domain = address.split("@")[-1].lower()
    parts = [p for p in domain.split(".") if p not in ("mail", "email", "billing", "notifications", "em")]
    return (parts[-2] if len(parts) >= 2 else domain).capitalize()[:60]


def read(message: dict, today: date) -> dict | None:
    """What the notice says, or None when the email says no renewal coming."""
    from . import ghosts

    subject = str(message.get("subject") or "")
    text = ghosts.own_words(str(message.get("body") or ""))[:4000] or str(message.get("body") or "")[:4000]
    found = COMING.search(subject) or COMING.search(text)
    if not found:
        return None
    if TAKEN.search(subject) or (not COMING.search(subject) and TAKEN.search(text[:400])):
        return None
    at = message.get("at") or 0
    sent = datetime.fromtimestamp(at).date() if at else today
    whole = subject + "\n" + text
    start = found.start() if COMING.search(subject) is None else 0
    rest = whole if start == 0 else text[max(0, start - 80):]
    due = when(rest, sent) or when(whole, sent)
    if due is not None and (due < today or (due - today).days > MOST_DAYS):
        return None
    return {"service": service_of(str(message.get("from") or "")), "due": due,
            "amount": amount(rest) or amount(whole), "subject": subject[:200],
            "trial": bool(re.search(r"trial|пробн", found.group(0), re.I))}


def key_of(message_id: str) -> str:
    return "rn-" + hashlib.sha256(str(message_id).encode()).hexdigest()[:16]


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def _held(who) -> dict:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=OPENS)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _remember(who, key: str, where: dict) -> None:
    from .models import UserSetting

    held = _held(who)
    held[key] = dict(where, at=time.time())
    if len(held) > 200:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-200:])
    user_id, org_id = _ids(who)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=OPENS, value=json.dumps(held),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def opens(who, key: str) -> dict | None:
    return _held(who).get(key)


def where_to(who, key: str) -> str:
    from . import ghosts

    got = opens(who, key) or {}
    if not got.get("thread"):
        return "https://mail.google.com/"
    return ghosts.link_to(got.get("mailbox") or "", got["thread"])


async def seen(who, message: dict, *, mailbox: str = "", signed_up: str = "") -> str:
    """A renewal coming, told to the person: the sentence for the mail log, or "" when there is none."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution, notices

    try:
        if not await asyncio.to_thread(on, who):
            return ""
        zone = clock.zone_of(who)
        today = datetime.now(zone).date()
        got = read(message, today)
        if got is None:
            return ""
        what = got["service"]
        title = f"{'Trial ends' if got['trial'] else 'Renews soon'}: {what}"
        if got["due"] is not None:
            days = (got["due"] - today).days
            in_days = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
            on_day = f"on {got['due'].strftime('%A %-d %B')} ({in_days})"
        else:
            on_day = "soon (the email names no date)"
        body = (f"{what}'s free trial ends {on_day}, and then it charges" if got["trial"]
                else f"{what} renews {on_day}")
        body += f" for {got['amount']}." if got["amount"] else ", for an amount the email does not say."
        body += f" The email: “{got['subject']}”."
        if signed_up:
            body += f" It came to {signed_up}, an address a nightly run signed up with."
        body += " If it is still wanted, there is nothing to do; to stop it, cancel it before then."
        key = key_of(message.get("id") or "")
        link = f"/mail/renewal/{key}"
        said = await notices.notify(
            title=title, body=body, link=link, link_label="Open the email",
            links=[{"label": "Open the email", "href": link}], kind="mail", key=key, who=who,
            phone_text=f"{title}. {body}")
        if said is None:
            return f"A renewal of {what}: told before, not told again."
        await sync_to_async(_remember)(who, key, {"thread": str(message.get("thread_id") or ""),
                                                  "mailbox": mailbox, "service": what})
        await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"{what} {on_day}"[:200])
        return f"A renewal coming: {what} {on_day}. You were told in a notice."
    except Exception as exc:  # noqa: BLE001 - the email is handled on without it
        log.info("renews soon: the email could not be read: %s", exc)
        return ""


__all__ = ["COMING", "SWITCH", "TAKEN", "TITLE", "amount", "key_of", "on", "opens", "read", "seen",
           "service_of", "when", "where_to"]
