"""Receipts: every receipt and invoice in the person's mail, by month, for the accountant.

Built by the nightly feature run, night 4, 7 October 2026 (task 94, idea I-006,
"Receipts and spending gathered from mail"), from task 66's OpenClaw build 4 and
task 55's receipts. A company's receipts and invoices arrive by mail: in September
2026 about sixty of them reached the owner's work mailbox (Anthropic, GitHub, Auth0, Calendly,
Linear, Postmark, Xero, Google Workspace, Amazon Web Services, an accountant's
"Фактура"), most with the PDF attached. Gathering them for the books was a search,
a download per email and a list typed by hand. So Rouh gathers them:

- **Which emails.** Every email of the month that Gmail files under Purchases, or
  whose subject says receipt, invoice, billing, фактура or разписка, in the
  person's own inboxes (read only, `rouh/inboxes.py`) and in Rouh's own. Left out:
  a reply or a forward (the original is there already), an automatic reply, one
  the person or Rouh sent, one marked [TEST], and a Purchases email with neither an amount nor a file
  in it (a subscription notice is not a receipt).
- **What each one says.** When, from whom (`'Anthropic, PBC' via Reg` is
  Anthropic, PBC), its subject, the amount it says was paid, read from its own
  words (`amount`: "Amount paid", "Total" and the rest before any figure, never a
  "Subtotal"), and its files: PDFs, XML invoices and pictures big enough to be a
  scan rather than a logo.
- **One download for the accountant** (`bundle`): a zip of the month, every file
  named by its date and who sent it, an email with no file kept as its own page,
  and `receipts.csv` listing them all.

Nothing is asked of a model: Gmail's search finds them and the amount is read
from the email's own words.

**Its switch** is `receipts` (`rouh/switches.py`): off, the sidebar has no
Receipts and the routes answer that it is off.

**Whose.** Everything is read as the person asking, from their own inboxes and
their own Rouh's; a month read is kept a few minutes by both their ids.
"""
from __future__ import annotations

import asyncio
import csv
import html
import io
import logging
import re
import time
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation

log = logging.getLogger("rouh.receipts")

#: The feature's switch (`rouh/switches.py`).
SWITCH = "receipts"
TITLE = ("Receipts: every receipt and invoice in your mail, by month, with one "
         "download for the accountant")

#: The searches, each made for one month in every inbox. One word each rather than
#: one search with OR, so each says plainly why an email is on the list.
SEARCHES = ("category:purchases", "subject:receipt", "subject:invoice", "subject:billing",
            "subject:фактура", "subject:разписка")
#: The one search that also finds notices, so what it alone found needs an amount or a file.
LOOSE = "category:purchases"
#: How many pages of one search are read, at 500 a page.
PAGES = 3
#: How many emails are read at once from one inbox.
AT_ONCE = 8
#: How long a month read is kept, in seconds.
KEEP = 10 * 60
#: How many months back the page offers.
MONTHS = 12
#: A picture smaller than this is a logo or a signature, not a scanned receipt.
SMALLEST_PICTURE = 30 * 1024

#: A reply or a forward: the original is on the list already.
ANSWERED = re.compile(r"^\s*(re|fwd?|aw|wg|tr|отг|пр)\s*:", re.I)
#: An answer a machine wrote while somebody was away, which only quotes the receipt.
AUTOMATIC = re.compile(r"^\s*(automatic\s+reply|auto[- ]?reply|out\s+of\s+(the\s+)?office|"
                       r"автоматичен\s+отговор)\b", re.I)
#: A test payment of the person's own product is not a receipt of theirs.
TESTING = re.compile(r"\[\s*test\s*\]", re.I)

#: An amount: a currency, then a figure, or a figure, then a currency.
_FIGURE = r"\d{1,3}(?:[,.\u00a0 ]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{1,2})?"
_CURRENCY = r"US\$|\$|€|£|USD|EUR|GBP|BGN|CHF|лв\.?"
MONEY = re.compile(
    rf"(?:(?P<c1>{_CURRENCY})\s?(?P<n1>{_FIGURE}))|(?:(?P<n2>{_FIGURE})\s?(?P<c2>{_CURRENCY}))",
    re.I)
#: The words before the amount that was paid, the surest first. `\b` keeps
#: "Subtotal" from being read as "total".
PAID = [re.compile(rf"\b{words}\b", re.I) for words in (
    r"amount\s+paid", r"total\s+paid", r"you\s+paid", r"payment\s+amount", r"grand\s+total",
    r"total\s+due", r"amount\s+due", r"total\s+amount", r"total", r"charged",
    r"сума\s+за\s+плащане", r"обща\s+сума", r"общо", r"сума")]
_CODES = {"$": "USD", "US$": "USD", "USD": "USD", "€": "EUR", "EUR": "EUR", "£": "GBP",
          "GBP": "GBP", "BGN": "BGN", "ЛВ": "BGN", "ЛВ.": "BGN", "CHF": "CHF"}

_kept: dict[tuple[str, str, str], tuple[float, dict]] = {}


class Refused(ValueError):
    """A request that cannot be answered, with the reason a person can read."""


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


# --- reading one email -------------------------------------------------------


def _number(text: str) -> Decimal | None:
    """A figure as written, "1,234.50", "1.234,50", "1 234,50" or "72", as a number."""
    text = text.replace(" ", "").replace("\u00a0", "")
    if "," in text and "." in text:
        text = text.replace(",", "") if text.rfind(".") > text.rfind(",") else \
            text.replace(".", "").replace(",", ".")
    elif "," in text:
        whole, _, tail = text.rpartition(",")
        text = whole.replace(",", "") + "." + tail if len(tail) in (1, 2) else text.replace(",", "")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _money(found) -> dict | None:
    code = _CODES.get((found.group("c1") or found.group("c2") or "").upper())
    value = _number(found.group("n1") or found.group("n2") or "")
    if not code or value is None or value <= 0:
        return None
    return {"currency": code, "value": value}


def amount(text: str) -> dict | None:
    """The amount an email says was paid, as {currency, value}, or None.

    After the surest words first ("Amount paid", then "Total" and the rest), and
    failing those, the first amount with a currency anywhere in it.
    """
    text = str(text or "")
    for words in PAID:
        for said in words.finditer(text):
            # The rest of its line, or the next line where the figure stands
            # under its words, as an email's table read as text puts it.
            after = text[said.end():said.end() + 90]
            lines = after.split("\n")
            near = lines[0] if lines[0].strip(" \t:*-") else "\n".join(lines[:2])
            found = MONEY.search(near)
            got = _money(found) if found else None
            if got:
                return got
    for found in MONEY.finditer(text):
        got = _money(found)
        if got:
            return got
    return None


def merchant(sender: str) -> str:
    """Who an email is from, as a person says it: `"'Anthropic, PBC' via Reg" <x>` is
    "Anthropic, PBC", and an address with no name is its domain."""
    sender = str(sender or "").strip()
    found = re.match(r'^\s*"?(?P<name>[^"<]*?)"?\s*<(?P<address>[^>]+)>\s*$', sender)
    name = (found.group("name") if found else "").strip().strip("'\"")
    address = (found.group("address") if found else sender).strip().lower()
    name = re.sub(r"\s+via\s+.*$", "", name, flags=re.I).strip().strip("'\"")
    if name:
        return name[:80]
    return address.rsplit("@", 1)[-1] if "@" in address else address[:80]


def _address(sender: str) -> str:
    found = re.search(r"<([^>]+)>", str(sender or ""))
    return (found.group(1) if found else str(sender or "")).strip().lower()


def kept_files(attachments) -> list[dict]:
    """The files worth keeping: documents and scans, not a logo or a signature's picture."""
    out = []
    for one in attachments or []:
        kind = str(one.get("type") or "").lower()
        name = str(one.get("name") or "")
        if (kind == "application/pdf" or name.lower().endswith((".pdf", ".xml"))
                or kind in ("application/xml", "text/xml")
                or (kind.startswith("image/") and int(one.get("size") or 0) >= SMALLEST_PICTURE)):
            out.append({"part": str(one.get("part")), "name": name or "file",
                        "type": kind or "application/octet-stream",
                        "size": int(one.get("size") or 0)})
    return out


def is_receipt(message: dict, found_by: set[str], own: set[str]) -> bool:
    """Whether an email the searches found belongs on the list."""
    subject = str(message.get("subject") or "")
    if ANSWERED.match(subject) or AUTOMATIC.match(subject) or TESTING.search(subject):
        return False
    if str(message.get("auto_submitted") or "no").strip().lower() not in ("", "no"):
        return False
    if _address(message.get("from")) in own:
        return False
    if found_by <= {LOOSE}:
        return bool(message.get("amount") or message.get("files"))
    return True


# --- a month -----------------------------------------------------------------


def month_of(text: str, zone) -> tuple[int, int]:
    """The month asked for, "2026-09", or this one on the person's clock."""
    found = re.fullmatch(r"\s*(\d{4})-(\d{1,2})\s*", str(text or ""))
    if found and 1 <= int(found.group(2)) <= 12 and 2000 <= int(found.group(1)) <= 2100:
        return int(found.group(1)), int(found.group(2))
    if text:
        raise Refused("A month is written like 2026-09.")
    now = datetime.now(zone)
    return now.year, now.month


def bounds(year: int, month: int, zone) -> tuple[int, int]:
    """The month's first and last second on the person's clock, as seconds since 1970."""
    start = datetime(year, month, 1, tzinfo=zone)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=zone)
    return int(start.timestamp()), int(end.timestamp())


def recent_months(zone, count: int = MONTHS) -> list[str]:
    now = datetime.now(zone)
    year, month, out = now.year, now.month, []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    return out


def _readers(who, services) -> list[tuple[str, object, str]]:
    """Every inbox looked in: (its address, its reader, whose), theirs first, then Rouh's."""
    from . import inboxes

    out: list[tuple[str, object, str]] = []
    if inboxes.ready():
        for one in inboxes.theirs(who):
            if one.needs_reconnect:
                continue
            try:
                out.append((one.email, inboxes.open_one(who, one).gmail, "yours"))
            except Exception as exc:  # noqa: BLE001
                log.info("inbox %s could not be opened for receipts: %s", one.email, exc)
    rouh = inboxes.rouh_address(who)
    if services is not None and rouh and rouh not in [address for address, _, _ in out]:
        out.append((rouh, services.gmail, "rouh"))
    return out


def own_addresses(who) -> set[str]:
    from .meeting_prep import own_addresses as theirs

    return theirs(who)


def _gmail_link(inbox: str, thread: str) -> str:
    from .meeting_prep import _gmail_link

    return _gmail_link(inbox, thread)


async def _found(gmail, after: int, before: int) -> dict[str, set[str]]:
    """Every email the searches find in one inbox in the month, and which found each."""
    out: dict[str, set[str]] = {}
    for search in SEARCHES:
        token = ""
        for _ in range(PAGES):
            ids, token = await gmail.listing(query=f"{search} after:{after} before:{before}",
                                             page_token=token, spam_and_trash=False)
            for one in ids:
                out.setdefault(one, set()).add(search)
            if not token:
                break
    return out


def _row(message: dict, inbox: str, whose: str) -> dict:
    files = kept_files(message.get("attachments"))
    text = f"{message.get('subject') or ''}\n{(message.get('body') or '')[:20000]}"
    paid = amount(text)
    return {"id": message.get("id") or "", "thread_id": message.get("thread_id") or "",
            "inbox": inbox, "whose": whose, "at": float(message.get("at") or 0),
            "merchant": merchant(message.get("from")), "from": str(message.get("from") or "")[:200],
            "subject": str(message.get("subject") or "(no subject)")[:240],
            "amount": ({"currency": paid["currency"], "value": f"{paid['value']:.2f}"}
                       if paid else None),
            "files": files,
            "link": _gmail_link(inbox, message.get("thread_id") or message.get("id") or "")}


async def _inbox(gmail, inbox: str, whose: str, after: int, before: int,
                 own: set[str]) -> list[dict]:
    found = await _found(gmail, after, before)
    gate = asyncio.Semaphore(AT_ONCE)

    async def one(ident: str):
        async with gate:
            return await gmail.message(ident)

    read = await asyncio.gather(*(one(ident) for ident in found), return_exceptions=True)
    out = []
    for ident, message in zip(found, read):
        if isinstance(message, BaseException):
            log.info("a receipt %s in %s could not be read: %s", ident, inbox, message)
            continue
        row = _row(message, inbox, whose)
        if is_receipt({**message, "amount": row["amount"], "files": row["files"]},
                      found[ident], own):
            out.append(row)
    return out


def totals(rows: list[dict]) -> list[dict]:
    """What the month's receipts add up to, one line a currency, the biggest first."""
    held: dict[str, Decimal] = {}
    counted: dict[str, int] = {}
    for row in rows:
        if row.get("amount"):
            code = row["amount"]["currency"]
            held[code] = held.get(code, Decimal(0)) + Decimal(row["amount"]["value"])
            counted[code] = counted.get(code, 0) + 1
    return [{"currency": code, "value": f"{value:.2f}", "count": counted[code]}
            for code, value in sorted(held.items(), key=lambda kv: -kv[1])]


async def month(who, *, services, zone, asked: str = "", again: bool = False) -> dict:
    """One month's receipts: {ok, month, months, inboxes, rows, totals, trouble}.

    `services` is the person's Google services, whose Gmail is Rouh's own inbox;
    None leaves Rouh's inbox out.
    """
    from asgiref.sync import sync_to_async

    if not await sync_to_async(on)(who):
        return {"ok": True, "off": True, "rows": []}
    year, number = month_of(asked, zone)
    name = f"{year:04d}-{number:02d}"
    key = (str(who.org_id), str(who.user_id), name)
    held = _kept.get(key)
    if held and not again and time.time() - held[0] < KEEP:
        return held[1]
    after, before = bounds(year, number, zone)
    readers = await sync_to_async(_readers)(who, services)
    own = await sync_to_async(own_addresses)(who)
    answers = await asyncio.gather(
        *(_inbox(gmail, inbox, whose, after, before, own) for inbox, gmail, whose in readers),
        return_exceptions=True)
    rows: list[dict] = []
    trouble: list[str] = []
    for (inbox, _, _), answer in zip(readers, answers):
        if isinstance(answer, BaseException):
            log.warning("receipts could not be read from %s: %s", inbox, answer)
            trouble.append(f"{inbox} could not be read just now.")
            continue
        rows.extend(answer)
    rows.sort(key=lambda row: -row["at"])
    made = {"ok": True, "month": name, "months": recent_months(zone),
            "said": datetime(year, number, 1).strftime("%B %Y"),
            "inboxes": [{"address": inbox, "whose": whose} for inbox, _, whose in readers],
            "rows": rows, "totals": totals(rows), "trouble": trouble, "read_at": time.time()}
    if not readers:
        made["trouble"] = ["No inbox is connected: connect yours in Settings, Read-only "
                           "mailboxes, and Rouh's in Settings, Google."]
    if not trouble:
        _kept[key] = (time.time(), made)
    return made


def forget(who) -> None:
    for key in [one for one in _kept if one[:2] == (str(who.org_id), str(who.user_id))]:
        _kept.pop(key, None)


# --- the files ---------------------------------------------------------------


def _reader_for(who, services, inbox: str):
    for address, gmail, _ in _readers(who, services):
        if address == str(inbox or "").strip().lower():
            return gmail
    raise Refused("That inbox is not one of yours.")


async def one_file(who, *, services, inbox: str, message_id: str, part: str) -> dict:
    """One file of one receipt, as {name, type, data}, read from the inbox it is in."""
    from asgiref.sync import sync_to_async

    if not await sync_to_async(on)(who):
        raise Refused("Receipts is switched off: turn it on in Evolution, Mutations.")
    gmail = await sync_to_async(_reader_for)(who, services, inbox)
    return await gmail.attachment(str(message_id), str(part))


def _safe(text: str, most: int = 60) -> str:
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", " ", str(text or "")).strip()
    return re.sub(r"\s+", " ", text)[:most].strip() or "file"


def _page_of(message: dict) -> bytes:
    """An email with no file of its own, kept as a page that opens anywhere."""
    head = (f"<p><b>From:</b> {html.escape(message.get('from') or '')}<br>"
            f"<b>Date:</b> {html.escape(message.get('date') or '')}<br>"
            f"<b>Subject:</b> {html.escape(message.get('subject') or '')}</p><hr>")
    body = message.get("html") or ("<pre style=\"white-space:pre-wrap\">"
                                   + html.escape(message.get("body") or "") + "</pre>")
    # Kept as it was sent, and nothing in it runs where the accountant opens it.
    return ("<!doctype html><html><head><meta charset=\"utf-8\">"
            "<meta http-equiv=\"Content-Security-Policy\" content=\"script-src 'none'\"><title>"
            + html.escape(message.get("subject") or "Receipt") + "</title></head><body>"
            + head + body + "</body></html>").encode("utf-8")


def csv_of(rows: list[dict], names: dict[str, list[str]], zone) -> bytes:
    out = io.StringIO()
    out.write("﻿")  # so a spreadsheet reads the Cyrillic right
    writer = csv.writer(out)
    writer.writerow(["Date", "From", "Subject", "Amount", "Currency", "Inbox", "Files",
                     "Gmail"])
    for row in sorted(rows, key=lambda one: one["at"]):
        when = datetime.fromtimestamp(row["at"], zone).strftime("%Y-%m-%d") if row["at"] else ""
        paid = row.get("amount") or {}
        writer.writerow([when, row["merchant"], row["subject"], paid.get("value", ""),
                         paid.get("currency", ""), row["inbox"],
                         "; ".join(names.get(row["id"], [])), row["link"]])
    return out.getvalue().encode("utf-8")


async def bundle(who, *, services, zone, asked: str) -> tuple[str, bytes]:
    """The month for the accountant: (the zip's name, the zip).

    Every file of every receipt, named by its date and who sent it; an email with
    no file as its own page; and `receipts.csv` with every row and which files are
    whose.
    """
    from asgiref.sync import sync_to_async

    made = await month(who, services=services, zone=zone, asked=asked)
    if made.get("off"):
        raise Refused("Receipts is switched off: turn it on in Evolution, Mutations.")
    readers = {address: gmail for address, gmail, _ in
               await sync_to_async(_readers)(who, services)}
    gate = asyncio.Semaphore(AT_ONCE)
    taken: set[str] = set()
    names: dict[str, list[str]] = {}

    def name_for(row: dict, wanted: str) -> str:
        when = datetime.fromtimestamp(row["at"], zone).strftime("%Y-%m-%d") if row["at"] else ""
        stem, dot, ext = _safe(wanted, 80).rpartition(".")
        base = f"{when} {_safe(row['merchant'], 40)} - {stem if dot else ext}"
        ext = ext if dot else "bin"
        name, n = f"{base}.{ext}", 2
        while name.lower() in taken:
            name, n = f"{base} ({n}).{ext}", n + 1
        taken.add(name.lower())
        return name

    async def files_of(row: dict) -> list[tuple[str, bytes]]:
        gmail = readers.get(row["inbox"])
        if gmail is None:
            return []
        async with gate:
            if not row["files"]:
                message = await gmail.message(row["id"])
                return [(name_for(row, (row["subject"] or "email") + ".html"), _page_of(message))]
            out = []
            for one in row["files"]:
                got = await gmail.attachment(row["id"], one["part"])
                out.append((name_for(row, got.get("name") or one["name"]), got["data"]))
            return out

    got = await asyncio.gather(*(files_of(row) for row in made["rows"]), return_exceptions=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        missing = []
        for row, files in zip(made["rows"], got):
            if isinstance(files, BaseException):
                log.warning("a receipt's files could not be read: %s", files)
                missing.append(f"{row['merchant']}: {row['subject']}")
                continue
            names[row["id"]] = [name for name, _ in files]
            for name, data in files:
                archive.writestr(name, data)
        archive.writestr("receipts.csv", csv_of(made["rows"], names, zone))
        if missing:
            archive.writestr("not-included.txt", "These could not be read from the mail just "
                             "now; open them in Gmail:\n\n" + "\n".join(missing) + "\n")
    from . import evolution

    await sync_to_async(evolution.used)(SWITCH, "month_downloaded", who=who,
                                        detail=f"{made['month']}: {len(made['rows'])} receipts")
    return f"receipts-{made['month']}.zip", buffer.getvalue()


__all__ = ["Refused", "SWITCH", "TITLE", "amount", "bounds", "bundle", "forget", "is_receipt",
           "kept_files", "merchant", "month", "month_of", "one_file", "on", "recent_months",
           "totals"]
