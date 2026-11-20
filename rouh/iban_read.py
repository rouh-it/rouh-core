"""The bank accounts an email gives: every IBAN in its own words, checked by the IBAN's own sum.

Shared by two genes of night 49 (20 November 2026, task 94): Bank details that changed
(`rouh/bank_changed.py`), which remembers which account a sender gave, and Pay an invoice from the
inbox card (`rouh/bank_copy.py`), which offers the account with Copy. Plain rules, no model.
An IBAN is two letters, two check figures and up to thirty letters and figures, written in fours or
run together; it counts only when its own check (ISO 13616, the remainder 1 of 97) holds, so an order
number, a VAT number or a phone number is never taken for one.
"""
from __future__ import annotations

import re

#: How long each country's IBAN is (the SEPA countries, and the others Petar's mail is likely to give).
LENGTHS = {
    "AD": 24, "AE": 23, "AL": 28, "AT": 20, "AZ": 28, "BA": 20, "BE": 16, "BG": 22, "BH": 22, "BR": 29,
    "CH": 21, "CY": 28, "CZ": 24, "DE": 22, "DK": 18, "EE": 20, "EG": 29, "ES": 24, "FI": 18, "FO": 18,
    "FR": 27, "GB": 22, "GE": 22, "GI": 23, "GL": 18, "GR": 27, "HR": 21, "HU": 28, "IE": 22, "IL": 23,
    "IS": 26, "IT": 27, "JO": 30, "KW": 30, "KZ": 20, "LB": 28, "LI": 21, "LT": 20, "LU": 20, "LV": 21,
    "MC": 27, "MD": 24, "ME": 22, "MK": 19, "MT": 31, "MU": 30, "NL": 18, "NO": 15, "PK": 24, "PL": 28,
    "PS": 29, "PT": 25, "QA": 29, "RO": 24, "RS": 22, "SA": 24, "SE": 24, "SI": 19, "SK": 24, "SM": 27,
    "TN": 24, "TR": 26, "UA": 29, "VA": 22, "XK": 20,
}
_CANDIDATE = re.compile(r"(?<![A-Za-z0-9])(?P<iban>[A-Z]{2}\d{2}(?:[  ]?[A-Z0-9]){11,30})(?![A-Za-z0-9])")
_BIC = re.compile(r"\b(?:BIC|SWIFT)(?:/SWIFT| code| \(SWIFT\))?\s*[:.]?\s*(?P<bic>[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b")
_HOLDER = re.compile(r"(?im)^\s*(?:beneficiary|account (?:holder|name)|payee|recipient|in favou?r of|получател|титуляр)"
                     r"\s*(?:name)?\s*[:\-]\s*(?P<holder>[^\n]{2,80})$")


def valid(raw: str) -> bool:
    """Whether the characters are an IBAN: its country's length and the remainder 1 of 97."""
    iban = re.sub(r"\s", "", raw or "").upper()
    if len(iban) < 15 or LENGTHS.get(iban[:2], 0) not in (0, len(iban)):
        return False
    if iban[:2] not in LENGTHS:
        return False
    moved = iban[4:] + iban[:4]
    try:
        number = int("".join(str(int(ch, 36)) for ch in moved))
    except ValueError:
        return False
    return number % 97 == 1


def plain(raw: str) -> str:
    return re.sub(r"\s", "", raw or "").upper()


def spaced(raw: str) -> str:
    """In fours, as a bank writes it."""
    iban = plain(raw)
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def ending(raw: str) -> str:
    """What may be said of it where others may read: its country, the bank's code and its last four.

    The bank's code is public (it names the bank, not the account) and keeps two accounts that end
    in the same four figures apart: "BG, bank STSA, ending 5678".
    """
    iban = plain(raw)
    return f"{iban[:2]}, bank {iban[4:8]}, ending {iban[-4:]}"


def found(text: str) -> list[str]:
    """Every IBAN in the words, each once, as plain characters, in the order they come.

    A run of fours can swallow the next word's start ("BG80 BNBG 9661 1020 3456 78 BIC"): each
    candidate is tried whole and then a group shorter at a time, until it is one.
    """
    out: list[str] = []
    for hit in _CANDIDATE.finditer(text or ""):
        raw = plain(hit.group("iban"))
        want = LENGTHS.get(raw[:2])
        tries = [raw[:want]] if want and len(raw) >= want else [raw[:n] for n in range(len(raw), 14, -1)]
        for one in tries:
            if valid(one):
                if one not in out:
                    out.append(one)
                break
    return out


def bic(text: str) -> str:
    hit = _BIC.search(text or "")
    return hit.group("bic") if hit else ""


def holder(text: str) -> str:
    hit = _HOLDER.search(text or "")
    return hit.group("holder").strip(" .,;") if hit else ""


__all__ = ["LENGTHS", "bic", "ending", "found", "holder", "plain", "spaced", "valid"]
