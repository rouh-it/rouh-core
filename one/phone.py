"""The phone: the one place that can reach a person who is not looking.

Step 07, section 5: the phone is "uniquely good at being in your pocket; the
only surface that can interrupt you", and so the prompt that a run is stuck
belongs here and nowhere else.

It uses the Telegram bot the laptop's ``tg-ask`` already uses, and only ever
sends: it never reads the bot's messages, so ``tg-ask`` goes on working. The
bot's key is in its own file on the server, readable only by the program's
user, and is read when a message is sent. It is never written to the list,
the log or any page.

Two kinds of message:

* **A question** a run is waiting on, with Allow and Deny. Each is a link to a
  page on the program that asks you to confirm with a button. The link alone
  never answers, because Telegram opens links by itself to show a preview.
* **A notice**, with a link to the run: it is waiting in its terminal, it
  could not save its work, it stopped with an error.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("one.phone")


class Phone:
    def __init__(self, config_path: str | Path, *, timeout: float = 15.0) -> None:
        self.path = Path(config_path)
        self._timeout = timeout

    def configured(self) -> bool:
        return self._config() is not None or bool(_through_rouh())

    def _config(self) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None
        if not data.get("bot_token") or not data.get("chat_id"):
            return None
        return data

    async def send(self, text: str, *, buttons: list[tuple[str, str]] | None = None) -> bool:
        config = self._config()
        if config is None:
            key = _through_rouh()
            return await self._through_rouh(key, text, buttons) if key else False
        payload: dict[str, Any] = {"chat_id": config["chat_id"], "text": text[:3500],
                                   "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "url": u} for t, u in buttons]]}
        url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
            ok = response.status_code == 200 and bool(response.json().get("ok"))
        except (httpx.HTTPError, ValueError) as exc:
            # The address holds the key, so only the kind of failure is logged.
            log.warning("the phone message was not sent: %s", type(exc).__name__)
            return False
        if not ok:
            log.warning("Telegram refused the message with status %s", response.status_code)
        return ok

    async def _through_rouh(self, key: dict, text: str, buttons: list[tuple[str, str]] | None) -> bool:
        """The note, sent by Rouh with its own bot, to the owner's one chat (rouh/web/phoneapi.py)."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                response = await client.post(str(key["url"]).rstrip("/") + "/internal/phone",
                                             headers={"X-Rouh-Worker-Key": key["token"]},
                                             json={"text": text[:3500], "buttons": [list(b) for b in buttons or []]})
            return response.status_code == 200 and bool(response.json().get("ok"))
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("Rouh did not send the phone note: %s", type(exc).__name__)
            return False


class FakePhone:
    """What the tests use: remembers every message instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def configured(self) -> bool:
        return True

    async def send(self, text: str, *, buttons: list[tuple[str, str]] | None = None) -> bool:
        self.sent.append({"text": text, "buttons": list(buttons or [])})
        return True


def _through_rouh() -> dict:
    """In the containers the program holds no bot token: the worker's key and Rouh's address
    (`rouh/workerkey.py`), to have Rouh send the note with its own bot (`/internal/phone`)."""
    path = os.environ.get("ROUH_WORKER_KEY_FILE", "").strip()
    if not path:
        return {}
    try:
        said = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return said if isinstance(said, dict) and said.get("token") and said.get("url") else {}

