"""What Rouh did to somebody's Google account, written down where it can be read.

Reading mail leaves no trace worth keeping. Sending it does. From the moment
Rouh can send a message, create a draft, archive a thread, edit a document or
overwrite a file in Drive, there has to be somewhere a person can look
afterwards and see exactly what happened without taking anybody's word for it.

So every write goes through :meth:`WriteLog.wrote` and lands as one JSON line in
``{log_dir}/google-writes.log``:

    {"at": "2026-09-16T10:04:11Z", "tool": "send_mail",
     "target": "ana@northwind.test", "summary": "Sent - subject \\"Invoice 4471\\" - id 18f2",
     "user_id": "user-default", "org_id": "org-default", "account": "alex@example.com"}

One line per write, appended and flushed as it happens, so a crash a second
later still leaves the record of what was already done. JSON lines rather than
prose because the file has to be readable both by a person with ``tail`` and by
a test that asserts on a field.

There is deliberately no confirmation step anywhere near this. Rouh asks the
person out loud before it sends; this file is what says afterwards that it did.

Everything written here goes through :func:`redaction.scrub` first. An audit
trail that quotes a token back is a worse leak than no audit trail, because it
is a file rather than a moment.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from .redaction import scrub

log = logging.getLogger("rouh.google")

#: The file itself, inside the configured log directory.
FILE_NAME = "google-writes.log"

#: Caps, so one enormous argument cannot make a line nobody can read.
TARGET_MAX = 300
SUMMARY_MAX = 500


class WriteLog:
    """The append-only record of every Google write, one JSON line each."""

    def __init__(self, folder: str, *, name: str = FILE_NAME) -> None:
        self.folder = folder
        self.path = os.path.join(folder, name)
        self._lock = threading.Lock()

    def wrote(self, tool: str, target: str, summary: str, *,
              user_id: str = "", org_id: str = "", account: str = "") -> dict:
        """Write one line down, and hand the same line back to the caller.

        Never raises. A write to Gmail that worked must not be reported as
        having failed because this machine's disk is full - the failure is
        logged instead, loudly, because an audit trail that has stopped being
        written is itself worth knowing about.
        """
        line = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": str(tool or "")[:60],
            "target": scrub(str(target or ""))[:TARGET_MAX],
            "summary": scrub(str(summary or ""))[:SUMMARY_MAX],
            "user_id": str(user_id or ""),
            "org_id": str(org_id or ""),
            "account": str(account or ""),
        }
        try:
            with self._lock:
                os.makedirs(self.folder, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                    fh.flush()
        except OSError:
            log.exception("the Google write could not be recorded in %s", self.path)
        return line

    def lines(self) -> list[dict]:
        """Everything written down so far, oldest first. For a test, and for /healthz."""
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError:
            return []
        out = []
        for one in raw.splitlines():
            one = one.strip()
            if not one:
                continue
            try:
                found = json.loads(one)
            except ValueError:
                continue
            if isinstance(found, dict):
                out.append(found)
        return out


__all__ = ["WriteLog", "FILE_NAME"]
