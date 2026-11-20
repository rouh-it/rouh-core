"""A placeholder left in an email: "[Name]", "{{first_name}}" or "<insert date>" is caught before it goes.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
Rouh writes many emails from an earlier one or from a template, and a model asked for "a short
intro I can send to the three of them" writes "Hi [Name]," and "[your company]" for the parts it
does not know. When one of those is sent as it is, the other side reads "[Name]", and a second email
has to say sorry.

So, while its switch is on, before send_mail sends an email or draft_mail drafts one (the person's
own turns and Rouh's jobs alike), its subject and words are read in plain rules, no model, for a
placeholder: a word in square brackets that names what is missing ("[Name]", "[first name]",
"[Company]", "[date]", "[link]", "[insert X]", anything in capitals such as "[COMPANY NAME]"),
template marks ("{{first_name}}", "{first_name}", "<<Name>>", "%FIRST_NAME%", "*|FNAME|*"),
"<insert ...>" and "<your name>", a run of capital X ("XXX", "XX.XX"), "Lorem ipsum" and "TODO".
When one is there nothing is sent or drafted: Rouh is told each one and writes it again with the
real words, or asks the person for them. `placeholders_checked` sends it as written, when the
person says it is right.

The quoted part of a reply is not read: those are somebody else's words, already sent. Nothing is
kept and nothing is changed.

**Whose.** Nothing of anybody's is read but the email being written.

**Its switch** is `mail_placeholder` (`rouh/switches.py`): off, an email goes as written.
"""
from __future__ import annotations

import re

SWITCH = "mail_placeholder"
TITLE = ("A placeholder left in an email: [Name], {{first_name}} or <insert date> is caught before it goes")

FIELD = {"type": "boolean",
         "description": "Send or draft it although it has what looks like a placeholder left in it "
                        "([Name], {{first_name}}, <insert date>, XXX): only when the person says the "
                        "words are right as written, after being told."}

#: Words that name what a placeholder stands for.
_NAMES = (r"(?:first|last|full|sur|given|family|company|client|customer|contact|recipient|your|their|his|her|my)"
          r"?[ _-]?(?:name|names|surname)|name|company|organi[sz]ation|title|role|position|date|day|time|"
          r"address|city|country|phone|number|email|e-mail|link|url|website|amount|price|fee|figure|"
          r"budget|product|project|topic|event|meeting|signature|recipient|person|someone|client|"
          r"customer|team|department|location|venue|deadline|details|here|x+|tbd|tbc|todo|"
          r"име|фирма|компания|дата|час|адрес|телефон|линк|сума")
_BRACKET = re.compile(
    r"\[(?:(?:insert|add|enter|put|your|their|the|recipient'?s?|client'?s?)\s+)?(?:" + _NAMES + r")"
    r"(?:\s+(?:here|of [a-z ]{2,20}|name|date|number|link))?\]"
    r"|\[(?:insert|add|enter|put)\b[^\]\n]{1,40}\]",
    re.I)
#: Anything in capitals in square brackets, such as [COMPANY NAME]: matched case by case.
_CAPS = re.compile(r"\[[A-Z][A-Z0-9 _/-]{2,30}\]")
#: Capital-only brackets are only counted when they are not a short known label ([PDF], [EN], [ACK]).
_LABELS = {"PDF", "EN", "BG", "ACK", "FYI", "EXT", "EXTERNAL", "DRAFT", "URGENT", "SPAM", "WIP", "NEW", "OK", "INFO",
           "REDACTED", "SIC", "UPDATE", "AI", "CET", "EET", "UTC", "GMT"}
_TEMPLATE = re.compile(
    r"\{\{\s*[\w .-]{1,40}\s*\}\}"            # {{first_name}}, {{ Company }}
    r"|(?<![\w{$])\{[a-z]+(?:_[a-z]+)+\}"     # {first_name}, never ${x} or a word in braces
    r"|<<\s*[\w .-]{1,40}\s*>>"               # <<Name>>
    r"|%[A-Z]+(?:_[A-Z]+)+%"                  # %FIRST_NAME%
    r"|\*\|[A-Z_]{2,20}\|\*"                  # *|FNAME|* (Mailchimp)
    r"|<(?:insert|add|enter|your|their|recipient'?s?)\b[^<>\n]{1,40}>",  # <insert date>, <your name>
    re.I)
_FILLER = re.compile(r"(?<![\w.])X{3,}(?![\w])|(?<![\w.])XX[.,]XX(?![\w])|\blorem ipsum\b|(?<![\w-])TODO\b|"
                     r"\bFIXME\b")

#: Where somebody else's words start in a reply: they are not read.
_QUOTED = re.compile(r"^\s*(?:On .{4,200}wrote:|На .{4,200}написа:|-{2,}\s*Original Message|"
                     r"-{2,}\s*Forwarded message|From: .+@)", re.M | re.I)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def own_part(text: str) -> str:
    """The words being written, without the quoted reply under them."""
    text = text or ""
    cut = _QUOTED.search(text)
    if cut:
        text = text[: cut.start()]
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))


def found(subject: str, body: str) -> list[str]:
    """Every placeholder in the email's own words, each once, in the order they come."""
    text = f"{subject or ''}\n{own_part(body)}"
    hits: list[tuple[int, str]] = []
    for hit in list(_BRACKET.finditer(text)) + list(_CAPS.finditer(text)):
        words = hit.group(0)
        inner = words[1:-1].strip()
        if inner.isupper() and inner in _LABELS:
            continue
        hits.append((hit.start(), words))
    for pattern in (_TEMPLATE, _FILLER):
        for hit in pattern.finditer(text):
            hits.append((hit.start(), hit.group(0)))
    seen: list[str] = []
    for _, words in sorted(hits):
        if words not in seen:
            seen.append(words)
    return seen


def check(subject: str, body: str, *, verb: str = "sent") -> str:
    """Why it is held, or "" when no placeholder is left in it."""
    got = found(subject, body)
    if not got:
        return ""
    listed = ", ".join(f"“{one}”" for one in got[:8])
    return (f"Not {verb}: the email still has what looks like a placeholder left in it: {listed}. "
            "The person it goes to would read it as it is. Put the real words in its place, from what "
            "the person said or what Rouh knows (the contact, the event, the file), and write it again; "
            "ask the person for any you do not know. If the person says it is right as written, call it "
            "again with placeholders_checked true.")


__all__ = ["FIELD", "SWITCH", "TITLE", "check", "found", "on", "own_part"]
