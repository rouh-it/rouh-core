"""Rouh's own letters, sent through Brevo from this install's own address.

Petar, 24 September 2026 (fr_edecde0ad6e6): "What we're missing here is an
email service, and I think we're going to use Brevo..." The address the
letters come from is the installation's own (`config.mail_from`,
``ROUH_MAIL_FROM``), set by its installer (SETUP.md). With none set nothing is
sent: `ready` is False and `send` refuses, saying so, and it never falls back
to another installation's address.

What it is for, and what it is not
----------------------------------

A page shared with somebody by their email address has to tell them so, and
somebody who has no account yet has to be told how to make one
(`rouh/web/guests.py`). Neither of them has anything Rouh could send through:
no Google account connected here, often no account here at all. So those
letters come from this install itself, from its own address (such as
``noreply@example.com``), the way any service's invitations do.

That is not the global credential AGENTS.md forbids, and the difference is
worth saying once. The rule is about credentials Rouh holds on somebody's
behalf - an organisation's Google client, a person's tokens - and it says
there is never a server-wide pair standing in for the ones somebody has not
entered. This key is nobody's but this install's, like its Anthropic key, and
it stands in for nobody: it sends Rouh's own few letters, from Rouh's own
address, and never a person's mail. A person's mail still goes from their own
Google account (`send_mail`, `rouh/password_reset.py`), and nothing here reads
anything.

Where the key is
----------------

Not in the repository and not in ``.env``: in one file on the server, outside
the checkout, owned by the user the service runs as and readable by nobody
else (``ROUH_BREVO_FILE``, ``/var/www/rouh/.secrets/brevo.json``), the same
arrangement Telegram's bot has. Either ``{"api_key": "xkeysib-..."}`` or the
bare key on one line. It is read when a letter goes out and never held, so the
file can be written on a running server. With no file there, or no sender
address set, `configured` (and `ready`) is False and a caller says the letter
could not be sent rather than pretending.

Every letter's subject and body, text and HTML, has its owner marks filled in
(`rouh/owner.py`) right before it goes, for the person it is sent on behalf of
(`Letter.who`), so no letter leaves with a mark in it.

The key never reaches a log line, an answer or an exception's text: Brevo's
own refusal is passed on, capped, and the kind of a network failure, never the
failure itself.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger("rouh.mailer")

#: Brevo's transactional mail endpoint, under `config.brevo_url`.
ENDPOINT = "/v3/smtp/email"

#: The longest subject sent. A subject is a line, and Brevo refuses an empty one.
SUBJECT_MAX = 200


class NotSetUp(RuntimeError):
    """There is no Brevo key, or no sender address, on this machine, so there is nothing to send with."""


class NotSent(RuntimeError):
    """Brevo was asked and the letter did not go."""


@dataclass(frozen=True)
class Letter:
    """One letter: who to, what it says, in plain text and in HTML."""

    to: str
    subject: str
    text: str
    html: str = ""
    #: Whose behalf it is sent on, for filling in the owner marks; None is the
    #: context's person (`owner.resolve`).
    who: object = None


def _key(path: Path) -> str:
    """The key set in Settings, Keys (`rouh/service_keys.py`), else the one in the file, else the
    settings file's. JSON with ``api_key``, or the bare key."""
    from . import service_keys

    kept = service_keys.stored("ROUH_BREVO_API_KEY")
    if kept:
        return kept
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        # An installation that sets the key in its settings file instead (the containers' stack.env
        # or .env, deploy/stack/settings.env.example); a file written there wins.
        return os.environ.get("ROUH_BREVO_API_KEY", "").strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError:
            return ""
        return str(data.get("api_key") or "").strip() if isinstance(data, dict) else ""
    return raw.splitlines()[0].strip() if raw else ""


def ready(cfg) -> bool:
    """Whether this installation can send a letter: a sender address and a key to send with."""
    return Mailer(cfg).configured()


class Mailer:
    """Brevo, as far as Rouh is concerned: one address to send from."""

    def __init__(self, cfg, *, timeout: float = 20.0) -> None:
        self.path = Path(cfg.brevo_file)
        self.url = str(cfg.brevo_url or "").rstrip("/") + ENDPOINT
        self.from_address = str(getattr(cfg, "mail_from", "") or "").strip()
        self.sender = {"email": self.from_address, "name": cfg.mail_from_name or "Rouh"}
        self.timeout = timeout

    def configured(self) -> bool:
        """There is a sender address set and a key to send with on this machine."""
        return bool(self.from_address) and bool(_key(self.path))

    async def send(self, letter: Letter) -> str:
        """Send one letter. Returns Brevo's id for it.

        Raises `NotSetUp` when there is no sender address or no key, and
        `NotSent` when Brevo was asked and said no or could not be reached.
        """
        if not self.from_address:
            raise NotSetUp("This installation has no sender address set for Rouh's letters "
                           "(ROUH_MAIL_FROM), so the letter could not be sent.")
        key = _key(self.path)
        if not key:
            raise NotSetUp("Rouh has no mail service set up on this machine, so the "
                           "letter could not be sent.")
        to = str(letter.to or "").strip()
        if not to:
            raise NotSent("There was nobody to send it to.")
        from . import outside_links, owner

        # No letter of Rouh's carries a link that opens only on this computer (task 140, step 140-14).
        subject = owner.say(str(letter.subject or ""), letter.who)
        try:
            payload = {
                "sender": self.sender,
                "to": [{"email": to}],
                "subject": " ".join(subject.split())[:SUBJECT_MAX] or "Rouh",
                "textContent": outside_links.guard(owner.say(letter.text, letter.who)),
            }
            if letter.html:
                payload["htmlContent"] = outside_links.guard(owner.say(letter.html, letter.who), html=True)
        except outside_links.LocalAddress as exc:
            raise NotSent(str(exc)) from None
        headers = {"api-key": key, "accept": "application/json",
                   "content-type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(self.url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("a letter was not sent: Brevo could not be reached (%s)",
                        type(exc).__name__)
            raise NotSent(f"The mail service could not be reached ({type(exc).__name__}).") \
                from None
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code not in (200, 201, 202):
            because = str((body or {}).get("message") or "").strip()[:200] \
                if isinstance(body, dict) else ""
            log.warning("Brevo refused a letter with status %s", response.status_code)
            raise NotSent("The mail service refused it"
                          + (f": {because}" if because else f" ({response.status_code})") + ".")
        sent_id = str((body or {}).get("messageId") or "") if isinstance(body, dict) else ""
        log.info("a letter went out through Brevo: %s", sent_id or "no id given")
        return sent_id
