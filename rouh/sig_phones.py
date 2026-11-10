"""The phone numbers in an email's signature, read in plain rules.

The part two genes of night 39 (10 November 2026, task 94) share: A new number in their signature
(`rouh/new_number.py`) and Save them as a contact (`rouh/save_sender.py`). Nothing is asked of a
model and nothing is kept: the words of the email in, the numbers out.

A signature is the last lines of the sender's own words, above anything quoted or forwarded. A
number in it is one that looks like a phone: at least eight digits, written with the usual spaces,
dots, dashes and brackets, an international one with its plus, often after "Tel", "Mobile", "M:"
or "Phone". A number that is a date, an amount, an order or a reference is not one: those carry
words before them that say so, or are too short, and are left out.
"""
from __future__ import annotations

import re

#: Lines from the end of the sender's own words read as the signature.
LINES = 14

#: Where the sender's own words end: a quoted reply, a forwarded message, a mobile footer.
_QUOTE = re.compile(
    r"^(?:>|on .{4,120}wrote:\s*$|-{2,} ?(?:original message|forwarded message) ?-{2,}|from: .+@|"
    r"на .{4,120}написа:\s*$|am .{4,120}schrieb:\s*$|le .{4,120}a écrit ?:\s*$)", re.I)

#: A phone as people write one: a plus or a digit, then digits with spaces, dots, dashes or brackets.
_NUMBER = re.compile(r"(?<![\w+/.-])(\+?\(?\d[\d ()./-]{6,22}\d)(?![\w/-]|\.\d)")

#: Words before a number that say it is a phone.
_PHONE_WORD = re.compile(
    r"(?<![\w])(?:tel|telephone|phone|mobile|mob|cell|direct|office|whatsapp|viber|gsm|тел|телефон|моб|мобилен|"
    r"handy|telefon|téléphone|portable|m|t|p|d|o)\s*[.:]?\s*$", re.I)

#: Words before a number that say it is not a phone.
_NOT_PHONE = re.compile(
    r"(?<![\w])(?:fax|vat|iban|bic|swift|eik|еик|ддс|uic|reg(?:istration)?|company no|account|order|invoice|ref|"
    r"reference|ticket|case|id|no|№|#|bulstat|булстат|zip|postcode|p\.?o\.? box)\s*[.:]?\s*$", re.I)


def own_words(body: str) -> str:
    """The sender's own words: everything above the first quoted or forwarded line."""
    out = []
    for line in str(body or "").splitlines():
        if _QUOTE.match(line.strip()):
            break
        out.append(line)
    return "\n".join(out)


def signature(body: str) -> str:
    """The last lines of the sender's own words, where a signature is."""
    lines = [ln.rstrip() for ln in own_words(body).splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines[-LINES:])


def digits(number: str) -> str:
    return re.sub(r"\D", "", str(number or ""))


def _plausible(raw: str) -> bool:
    d = digits(raw)
    if not 8 <= len(d) <= 15:
        return False
    # A date written with dots, slashes or dashes: 10.11.2026, 2026-11-10.
    if re.fullmatch(r"\d{1,4}[./-]\d{1,2}[./-]\d{2,4}", raw.strip()):
        return False
    # The same digit again and again, or a plain count up: a placeholder.
    if len(set(d)) <= 2:
        return False
    return True


def phones(body: str) -> list[str]:
    """The phone numbers in the signature, as written there, each once, at most four."""
    out: list[str] = []
    seen: set[str] = set()
    for line in signature(body).splitlines():
        for found in _NUMBER.finditer(line):
            raw = found.group(1).strip(" .-/")
            before = line[:found.start()]
            if _NOT_PHONE.search(before[-24:]):
                continue
            if not _plausible(raw):
                continue
            # A bare number with no plus, no leading zero and no phone word before it is most
            # likely an amount or a reference.
            if not raw.startswith(("+", "0", "(")) and not _PHONE_WORD.search(before[-16:]):
                continue
            key = digits(raw)[-9:]
            if key in seen:
                continue
            seen.add(key)
            out.append(" ".join(raw.split()))
            if len(out) == 4:
                return out
    return out


def same(a: str, b: str) -> bool:
    """Whether two ways of writing a number are the same phone: the last nine digits decide."""
    da, db = digits(a), digits(b)
    if not da or not db:
        return False
    n = min(9, len(da), len(db))
    return da[-n:] == db[-n:]


def label_for(body: str, number: str) -> str:
    """"mobile" or "work", from the words before the number in the signature."""
    for line in signature(body).splitlines():
        at = line.find(number.split()[0]) if number else -1
        if at < 0:
            continue
        before = line[:at].lower()
        if re.search(r"(?<![\w])(?:mobile|mob|cell|gsm|whatsapp|viber|моб|handy|portable|m)\s*[.:]?\s*$", before):
            return "mobile"
        return "work"
    return "work"


__all__ = ["label_for", "own_words", "phones", "same", "signature"]
