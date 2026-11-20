"""A document waiting for your signature: a signing service's request is told at once, and a fake one named.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
A contract, an offer letter, a board resolution or an NDA comes to be signed through DocuSign, Adobe
Acrobat Sign, Dropbox Sign, PandaDoc, Yousign, Evrotrust and the like. Their emails are machine
mail, which Rouh's inbox passes over, and they look like every other notification: one missed
holds up a deal or a hire until somebody chases it. And "DocuSign" is also the name a fake email
borrows most often, to get a password typed into a page that is not DocuSign's.

So, while its switch is on, an email somebody else sends to Rouh's inbox that asks for a signature
("Please DocuSign: ...", "... requested your signature on ...", "review and sign", "за подписване")
is told at once in a notice, read in plain rules with no model: who asks (Dana Reed, from "Dana Reed
via DocuSign"), the document, the service, the day it expires when the email says one, and where it
came from. When the email names a signing service but did not come from that service's own domain,
the notice says so plainly instead: it looks like that service and is not from it, so nothing in it
should be pressed. A finished, declined or withdrawn envelope is not told. Open the email
(`/mail/sign-request/<key>`) goes to it in Gmail; no link out of the email is offered.

**Whose.** Only what is needed to open the email again is kept (`user_settings`, `sign_request_opens`,
by `org_id` and `user_id`).

**Its switch** is `sign_request` (`rouh/switches.py`): off, nothing is read.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time
from datetime import date, datetime

log = logging.getLogger("rouh.sign_request")

SWITCH = "sign_request"
TITLE = "A document waiting for your signature: a signing service's request is told at once, and a fake one named"
OPENS = "sign_request_opens"

#: Each service, the words that name it, and the domains its email comes from.
SERVICES = (
    ("DocuSign", r"docusign", ("docusign.net", "docusign.com")),
    ("Adobe Acrobat Sign", r"adobe (?:acrobat )?sign|echosign", ("adobesign.com", "echosign.com", "adobe.com")),
    ("Dropbox Sign", r"dropbox sign|hellosign", ("hellosign.com", "dropboxsign.com", "dropbox.com")),
    ("PandaDoc", r"pandadoc", ("pandadoc.net", "pandadoc.com")),
    ("Yousign", r"yousign", ("yousign.com", "yousign.app", "yousign.fr")),
    ("Evrotrust", r"evrotrust", ("evrotrust.com", "evrotrust.bg")),
    ("SignNow", r"signnow", ("signnow.com",)),
    ("Zoho Sign", r"zoho sign", ("zohosign.com", "zoho.com", "zoho.eu")),
    ("SignWell", r"signwell", ("signwell.com",)),
    ("Docusign CLM", r"docusign clm", ("docusign.net",)),
)
ASKS = re.compile(
    r"\bplease (?:docusign|sign|review and sign|e-?sign)\b|\breview and (?:e-?)?sign\b|\bcomplete with docusign\b"
    r"|\brequested your (?:e-?)?signature\b|\b(?:is |are )?waiting for your (?:e-?)?signature\b"
    r"|\bsignature request(?:ed)?\b|\b(?:sent|shared) you (?:a |the )?(?:document|documents|contract|agreement)s? to"
    r" (?:review and )?sign\b|\byou(?:'ve| have) been (?:asked|invited) to sign\b|\bneeds your (?:e-?)?signature\b"
    r"|\bready for (?:your )?signature\b|\bsign(?:ature)? required\b"
    r"|за подпис(?:ване)?|очаква (?:вашия )?подпис|покана за подписване|изпрати(?:ха)? (?:ви )?документ за подпис",
    re.I)
#: The same services' emails that ask for nothing more.
DONE = re.compile(
    r"^\s*(?:completed|voided|declined|signed|you(?:'ve| have) signed|everyone has signed|document (?:completed|signed))\b"
    r"|\b(?:has been|was|is) (?:completed|voided|declined|cancelled|canceled|withdrawn)\b|\ball parties have signed\b"
    r"|\bsigned by (?:all|everyone)\b|\bthank you for signing\b|\bподписан(?:о|а)? от всички\b",
    re.I)
_VIA = re.compile(r"^\s*\"?(?P<who>[^\"<(]{2,80}?)\"?\s*(?:\(?\s*via\s+[^)]+\)?|from [A-Za-z ]+)\s*$", re.I)
_WHO_IN_BODY = re.compile(
    r"(?m)^\s*(?P<who>[A-Z][\w.'-]+(?: [A-Z][\w.'-]+){0,3})\s+(?:has )?(?:sent you|requested your signature|"
    r"invited you to sign|shared a document)")
_EXPIRES = re.compile(r"\b(?:expires?|will expire|valid until|must be signed by|sign by|due(?: date)?|изтича)\b"
                      r"[^\n.]{0,80}", re.I)
_DOC_IN_SUBJECT = (
    re.compile(r"^(?:re:\s*|fw:\s*|reminder:\s*)*(?:please docusign|complete with docusign|docusign)\s*:\s*(?P<doc>.+)$", re.I),
    re.compile(r"signature (?:on|for)\s+[\"'“]?(?P<doc>[^\"'”]+?)[\"'”]?\s*$", re.I),
    re.compile(r"(?:sign|signature request)\s*[:\-]\s*(?P<doc>.+)$", re.I),
    re.compile(r"[\"'“](?P<doc>[^\"'”]{3,120})[\"'”]"),
)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _domain_of(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def _is_of(domain: str, domains: tuple[str, ...]) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in domains)


def read(message: dict, today: date) -> dict | None:
    """What the notice says, or None when the email asks for no signature."""
    from . import ghosts, renewal_notice

    subject = str(message.get("subject") or "").strip()
    body = str(message.get("body") or "")
    text = (ghosts.own_words(body)[:4000] or body[:4000])
    if DONE.search(subject) or not (ASKS.search(subject) or ASKS.search(text[:1500])):
        return None
    name, address = email.utils.parseaddr(str(message.get("from") or ""))
    domain = _domain_of(address.lower())
    whole = f"{name}\n{subject}\n{text}"
    service, real = "", False
    for said, words, domains in SERVICES:
        if _is_of(domain, domains):
            service, real = said, True
            break
    if not service:
        for said, words, domains in SERVICES:
            if re.search(words, whole, re.I):
                service = said
                break
    if not service:
        return None  # a request to sign from no signing service is a person's email, handled as one
    asker = ""
    hit = _VIA.match(name or "")
    if hit and real:
        asker = hit.group("who").strip()
    if not asker:
        hit = _WHO_IN_BODY.search(text)
        asker = hit.group("who").strip() if hit else ""
    if asker.lower() in {s[0].lower() for s in SERVICES} or asker.lower() in ("docusign", "dropbox sign"):
        asker = ""
    document = ""
    for pattern in _DOC_IN_SUBJECT:
        hit = pattern.search(subject)
        if hit:
            document = hit.group("doc").strip(" .\"'“”")
            break
    at = message.get("at") or 0
    sent = datetime.fromtimestamp(at).date() if at else today
    expires = None
    for hit in _EXPIRES.finditer(text):
        got = renewal_notice.when(hit.group(0), sent)
        if got is not None and got >= sent:
            expires = got
            break
    return {"service": service, "real": real, "asker": asker[:80], "document": (document or subject)[:160],
            "expires": expires, "from": address.lower()[:120], "subject": subject[:200]}


def words(got: dict, today: date) -> tuple[str, str]:
    """The notice's title and body."""
    if not got["real"]:
        title = f"Not from {got['service']}: a request to sign"
        body = (f"An email that looks like a {got['service']} request to sign “{got['document']}” came from "
                f"{got['from'] or 'an address it does not give'}, which is not {got['service']}'s. "
                "Real requests come from the service's own address. Do not press anything in it or type a "
                "password into a page it opens; if somebody did mean to send you a document, ask them by "
                "another way.")
        return title, body
    who = got["asker"] or "Somebody"
    title = f"To sign: {got['document'][:80]}"
    body = f"{who} asks you to sign “{got['document']}” through {got['service']}."
    if got["expires"] is not None:
        days = (got["expires"] - today).days
        in_days = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days} days")
        body += f" It expires on {got['expires'].strftime('%A %-d %B')} ({in_days})."
    body += f" It came from {got['from']}, {got['service']}'s own address. Open the email to read and sign it."
    return title, body


def key_of(message_id: str) -> str:
    return "sr-" + hashlib.sha256(str(message_id).encode()).hexdigest()[:16]


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
        [UserSetting(user_id=user_id, org_id=org_id, name=OPENS, value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])


def opens(who, key: str) -> dict | None:
    return _held(who).get(key)


def where_to(who, key: str) -> str:
    from . import ghosts

    got = opens(who, key) or {}
    if not got.get("thread"):
        return "https://mail.google.com/"
    return ghosts.link_to(got.get("mailbox") or "", got["thread"])


async def seen(who, message: dict, *, mailbox: str = "") -> str:
    """A request to sign, told to the person: the sentence for the mail log, or "" when there is none."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution, notices

    try:
        if not await asyncio.to_thread(on, who):
            return ""
        today = datetime.now(clock.zone_of(who)).date()
        got = read(message, today)
        if got is None:
            return ""
        title, body = words(got, today)
        key = key_of(message.get("id") or "")
        link = f"/mail/sign-request/{key}"
        told = await notices.notify(
            title=title, body=body, link=link, link_label="Open the email",
            links=[{"label": "Open the email", "href": link}], kind="mail", key=key, who=who,
            phone_text=f"{title}. {body}")
        if told is None:
            return f"A request to sign through {got['service']}: told before, not told again."
        await sync_to_async(_remember)(who, key, {"thread": str(message.get("thread_id") or ""),
                                                  "mailbox": mailbox, "document": got["document"][:120],
                                                  "real": got["real"]})
        detail = f"{got['service']}: {got['document']}"[:200]
        if got["real"]:
            await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=detail)
        else:
            await sync_to_async(evolution.used)(SWITCH, "fake", who=who, detail=detail)
        return (f"A request to sign “{got['document']}” through {got['service']}. You were told in a notice."
                if got["real"] else f"An email that only looks like {got['service']}: you were warned in a notice.")
    except Exception as exc:  # noqa: BLE001 - the email is handled on without it
        log.info("a request to sign: the email could not be read: %s", exc)
        return ""


__all__ = ["ASKS", "DONE", "OPENS", "SERVICES", "SWITCH", "TITLE", "key_of", "on", "opens", "read", "seen",
           "where_to", "words"]
