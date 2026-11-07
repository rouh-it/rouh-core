"""What every Google client shares: where each API lives, the timeouts and
retries, the ceilings on one call, and how Google's refusals are read.
"""
from __future__ import annotations

import html as html_module
import random
import re

import httpx

from ..google_oauth import why_missing
from ..redaction import scrub


#: Where each API really lives. `ROUH_GOOGLE_API_BASE` replaces all four at
#: once and exists so a test can be the far end; it is never set in production.
REAL_BASES = {
    "gmail": "https://gmail.googleapis.com",
    "drive": "https://www.googleapis.com",
    "docs": "https://docs.googleapis.com",
    "calendar": "https://www.googleapis.com",
    "slides": "https://slides.googleapis.com",
    "sheets": "https://sheets.googleapis.com",
}

#: A request to Google is a network call on the far side of a voice turn. Long
#: enough for a slow mailbox, short enough that nobody is left listening to
#: silence.
CONNECT_SECONDS = 10.0
READ_SECONDS = 30.0

#: How many times a request that failed in a way that might pass is tried
#: again, and how long the waits between them start at. 429 and 5xx only;
#: anything else is an answer, not a wobble.
ATTEMPTS = 4
BACKOFF_SECONDS = 0.5
BACKOFF_CEILING_SECONDS = 20.0

#: The ceiling on anything a tool can ask for in one call, so a spoken turn
#: cannot accidentally pull a whole mailbox.
MAX_MESSAGES = 25
MAX_FILES = 25

#: The most one email may come to, files and all, once it is put together:
#: Gmail's own limit on a message. What is measured is the message as sent,
#: where every file is a third bigger than on disk, because base64 is.
MAIL_LIMIT = 25 * 1024 * 1024

#: What is in a conversation without being part of what anybody sent in it:
#: a draft not sent yet, and whatever was binned or marked spam.
LEFT_OUT_OF_A_THREAD = frozenset({"DRAFT", "TRASH", "SPAM"})


class GoogleSaidNo(RuntimeError):
    """Google answered with an error. The message is safe to show.

    `status` is the HTTP status it answered with, for the one caller that has
    to tell one refusal from another: a history Gmail no longer keeps is a 404,
    and is a thing to start again from rather than a fault (`Gmail.added_since`).
    `reason` is Google's own machine-readable word for it, when it gave one,
    for a caller that says one refusal differently from another
    (`Drive.add_drive_member`).
    """

    def __init__(self, message: str = "", status: int = 0, reason: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason


def _pause(answer: httpx.Response, wait: float) -> float:
    """How long to wait, honouring Google's own Retry-After when it sends one."""
    header = answer.headers.get("Retry-After", "")
    if header:
        try:
            return max(0.0, min(float(header), BACKOFF_CEILING_SECONDS))
        except ValueError:
            pass
    # A little jitter, so two calls that failed together do not come back together.
    return wait * (1.0 + random.random() * 0.25)


#: Google's own word for "that API is switched off in the project", in both
#: the shape it says it in now and the older one.
API_SWITCHED_OFF = {"SERVICE_DISABLED", "accessNotConfigured"}

#: And its word for "the token does not carry the permission this needs".
SCOPE_TOO_NARROW = {"ACCESS_TOKEN_SCOPE_INSUFFICIENT", "insufficientPermissions"}

#: The APIs, in the words the Google Cloud console uses on the button that
#: switches each one on, keyed by the host Google names it by. Calendar's host
#: is `calendar-json`, not `calendar`: that is what Google's own refusal says
#: and what the console's address for it is.
API_NAMES = {
    "gmail.googleapis.com": "Gmail API",
    "drive.googleapis.com": "Google Drive API",
    "docs.googleapis.com": "Google Docs API",
    "slides.googleapis.com": "Google Slides API",
    "sheets.googleapis.com": "Google Sheets API",
    "calendar-json.googleapis.com": "Google Calendar API",
    "pubsub.googleapis.com": "Cloud Pub/Sub API",
}


def _reason(answer: httpx.Response) -> tuple[str, dict]:
    """Google's machine-readable reason for a refusal, and what it is about.

    Two shapes, because Google sends both: `error.details[].reason` with a
    `metadata` object beside it, and the older `error.errors[].reason`. Empty
    when there is neither, which is most failures.
    """
    try:
        error = (answer.json() or {}).get("error")
    except Exception:
        return "", {}
    if not isinstance(error, dict):
        return "", {}
    for one in error.get("details") or []:
        if isinstance(one, dict) and one.get("reason"):
            return str(one["reason"]), dict(one.get("metadata") or {})
    for one in error.get("errors") or []:
        if isinstance(one, dict) and one.get("reason"):
            return str(one["reason"]), {}
    return "", {}


def _switched_off(metadata: dict) -> str:
    """The sentence for an API nobody has switched on in the project yet.

    Google's own is three lines long and has a console URL in the middle of
    it. This is the two facts a person acts on: which API, and which project.
    """
    service = (metadata.get("service") or "").strip()
    project = (metadata.get("consumer") or "").rsplit("/", 1)[-1].strip()
    named = API_NAMES.get(service) or (f"{service} API" if service else "")
    what = f"The {named}" if named else "A Google API this needs"
    where = f" in Google Cloud project {project}" if project else ""
    switch = (f" Switch {service} on" if service else " Switch it on") + (
        " for that project" if project else "")
    return (f"{what} is switched off{where}, so Google refused this."
            f"{switch} in the Google Cloud console, then ask me again.")


def _first_of(scope: str | tuple[str, ...]) -> str:
    """The scope to name in a sentence when a call would accept any of several."""
    if isinstance(scope, str):
        return scope
    return scope[0] if scope else ""


def _too_narrow(scope: str, said: str) -> str:
    """The sentence for a permission the person never granted.

    With the scope the call needed, it is named, because naming it is the
    difference between one press of Connect and an afternoon. Without it -
    a call that did not declare one - Google's own words are kept, so nothing
    is lost by guessing wrong about which permission was meant.
    """
    if scope:
        return why_missing(scope)
    return (f"This Google connection was not granted enough access for that: "
            f"Google said {said.rstrip('.')!r}. Open Settings and press Connect "
            f"Google to grant it.")


def _said(answer: httpx.Response) -> str:
    """What Google refused with, in words a person can act on.

    Two refusals get their own sentence because both are somebody's next
    five minutes of work: an API nobody switched on in the Cloud project, and
    a permission nobody granted. Everything else is Google's own message,
    scrubbed.
    """
    reason, metadata = _reason(answer)
    if reason in API_SWITCHED_OFF:
        return _switched_off(metadata)
    try:
        body = answer.json()
        error = body.get("error")
        if isinstance(error, dict):
            said = error.get("message") or ""
        else:
            said = str(error or "")
    except Exception:
        said = (answer.text or "")[:300]
    return scrub(said) or f"Google answered {answer.status_code}."


#: How long a request carrying a whole file is given. `READ_SECONDS` is right
#: for a message header and far too short for sixty megabytes.
UPLOAD_SECONDS = 600.0


class SeveralOfThose(RuntimeError):
    """A name that fits more than one thing in Drive, listing what it fits.

    Not a refusal from Google: Drive answered perfectly well and the answer was
    two folders called Plans. Picking one of them silently is how a file ends
    up somewhere nobody can find, so the whole message is the candidates and
    their ids, and it is shown to the person as it is.
    """


class CannotDoThat(ValueError):
    """A tool asked for something that cannot be done as asked.

    A time that cannot be read, an end before a start, an answer to an
    invitation this calendar was never sent, a tab a document does not have.
    Nothing more goes to Google, and the message says what to ask for instead.
    """


def _text_of_html(markup: str) -> str:
    """What a reader would see, when plain text is the one thing not sent."""
    text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()
