"""Every message Rouh sends to somebody other than Petar, written down whole.

Petar, 6 October 2026 (card 1315): a trusted contact's travel case said a
reply had gone to them on Telegram as message 568, and nothing on the machine
could say what message 568 held - not the log, not Telegram, which keeps no
copy a bot can read back. "Give yourself access to the logs." So each message
to a case's sender, and each answer to somebody's own Telegram account, is
written down as it goes: its whole text, the channel, who it went to, the id
the provider gave it, and the case it belongs to.

In two places, both readable by `run_command` (whose sandbox reads the whole
filesystem and changes nothing):

- one JSON line in ``sent.log``, in the directory the Google writes are
  recorded in (`config.Config.logs_path`, ``/var/www/rouh/data/logs`` on the
  server): ``grep <case key or message id> .../sent.log``;
- one line in ``rouh.log`` (``/var/www/rouh/logs/rouh.log``), from the
  ``rouh.sent`` logger, with the same JSON after ``sent:``.

Never a credential: sign-in letters and password resets do not come through
here, only words written to a person about their request.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

log = logging.getLogger("rouh.sent")

FILE_NAME = "sent.log"

#: Where `record` writes, set once at start-up (`configure`); "" writes only
#: to rouh.log.
_FOLDER = ""
_LOCK = threading.Lock()


def configure(folder: str) -> None:
    """The directory ``sent.log`` lives in."""
    global _FOLDER
    _FOLDER = str(folder or "")


def path() -> str:
    """The whole path of ``sent.log``, or "" when none is set."""
    return os.path.join(_FOLDER, FILE_NAME) if _FOLDER else ""


def record(*, channel: str, to: str, text: str, message_id: str = "", case_key: str = "",
           kind: str = "", parts: list | None = None, user_id: str = "", org_id: str = "",
           ok: bool = True, error: str = "") -> dict:
    """One message written down, whole, and the same line handed back. Never raises:
    a message that went is never reported as failed because the disk is full."""
    line = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "channel": str(channel or ""),
        "to": str(to or ""),
        "kind": str(kind or ""),
        "case": str(case_key or ""),
        "message_id": str(message_id or ""),
        "parts": [int(p) for p in parts or [] if str(p).lstrip("-").isdigit()],
        "ok": bool(ok),
        "error": str(error or "")[:500],
        "user_id": str(user_id or ""),
        "org_id": str(org_id or ""),
        "chars": len(text or ""),
        "text": str(text or ""),
    }
    said = json.dumps(line, ensure_ascii=False)
    log.info("sent: %s", said)
    where = path()
    if where:
        try:
            with _LOCK:
                os.makedirs(os.path.dirname(where), exist_ok=True)
                with open(where, "a", encoding="utf-8") as fh:
                    fh.write(said + "\n")
        except OSError:
            log.exception("a sent message could not be written down in %s", where)
    return line


def lines(*, case_key: str = "", message_id: str = "") -> list[dict]:
    """What ``sent.log`` holds, oldest first, for one case or one message id."""
    where = path()
    if not where:
        return []
    try:
        with open(where, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError:
        return []
    out = []
    for one in raw.splitlines():
        if (case_key and case_key not in one) or (message_id and message_id not in one):
            continue
        try:
            found = json.loads(one)
        except ValueError:
            continue
        if case_key and found.get("case") != case_key:
            continue
        if message_id and found.get("message_id") != message_id:
            continue
        out.append(found)
    return out


__all__ = ["FILE_NAME", "configure", "lines", "path", "record"]
