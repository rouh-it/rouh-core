"""A provider's spending limit, told to the person once.

Petar, 18 November 2026 (task 182, step 182-05): when Anthropic or OpenAI refuses calls because the
account's usage or spending limit is reached, say so once: which company, that chat replies fail
until a date, and the date. On 23 and 29 October 2026 Anthropic refused every call with "You have
reached your specified API usage limits", and the chats failed for an hour before anybody knew why.

Every request made of a model is written down by `rouh/llmlog.py`, and each one that failed is
handed here (`seen`, from the log's writer thread). A refusal that is a spending limit becomes one
notice (`rouh/notices.py`), on the screen and on Telegram at once, keyed on the company and the day
access comes back, so a thousand refused calls are one notice, and a restart does not say it again
(the notice's key is unique). It is a notice only: nothing asks the person to decide anything.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger("rouh.spend_limits")

#: Anthropic's words (a 400, `invalid_request_error`), and the day it says access comes back.
ANTHROPIC = re.compile(r"reached your specified API usage limits", re.I)
REGAIN = re.compile(r"regain access on (\d{4}-\d{2}-\d{2})(?: at (\d{2}:\d{2}) UTC)?", re.I)
#: OpenAI's (a 429 `insufficient_quota`, or a budget's hard limit). OpenAI names no day.
OPENAI = re.compile(r"insufficient_quota|exceeded your current quota|billing_hard_limit_reached|"
                    r"billing hard limit", re.I)

#: Where each company's limit is raised.
WHERE = {"anthropic": "console.anthropic.com/settings/limits",
         "openai": "platform.openai.com/settings/organization/limits"}
NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}

#: The loop notices are said on: Rouh's own, remembered when it starts (`remember_loop`).
_LOOP: list = []
#: The keys already said by this process, so the database is not asked once per refused call.
_said: set[str] = set()
_lock = threading.Lock()


def remember_loop() -> None:
    try:
        lp = asyncio.get_running_loop()
    except RuntimeError:
        return
    _LOOP[:] = [lp]


def limit_of(provider: str, http_status: int | None, error_type: str, words: str) -> dict | None:
    """The limit a refusal says, or None when it is not a spending limit: the company, and when
    access comes back (a `datetime` in UTC, or None when the company names no day)."""
    text = f"{error_type} {words}"
    if provider == "anthropic" and ANTHROPIC.search(text):
        back = None
        found = REGAIN.search(text)
        if found:
            try:
                back = datetime.fromisoformat(f"{found.group(1)}T{found.group(2) or '00:00'}+00:00")
            except ValueError:
                back = None
        return {"provider": provider, "back": back}
    if provider == "openai" and OPENAI.search(text):
        return {"provider": provider, "back": None}
    return None


def _key(limit: dict, now: float) -> str:
    back = limit["back"]
    if back is not None:
        return f"spend-limit:{limit['provider']}:{back.date().isoformat()}"
    # No day given: one notice per company per month, the period a budget runs for.
    month = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m")
    return f"spend-limit:{limit['provider']}:{month}"


def words(limit: dict, now: float | None = None) -> tuple[str, str]:
    """The notice's title and its text."""
    from . import clock

    provider = limit["provider"]
    name = NAMES.get(provider, provider)
    back = limit["back"]
    title = f"{name}'s spending limit is reached"
    where = WHERE.get(provider, name)
    start = (f"{name} refuses Rouh's calls: the account's spending limit is reached. Chat replies and "
             f"anything else on {name}'s models will fail")
    if back is not None:
        local = back.astimezone(clock.zone())
        text = (f"{start} until {local:%-d %B %Y} at {local:%H:%M}, when {name} gives access back, "
                f"or until the limit is raised at {where}.")
    else:
        now_utc = datetime.fromtimestamp(now or time.time(), timezone.utc)
        text = (f"{start} until the limit is raised at {where}. {name} named no date; if it is the "
                f"monthly budget, it starts again on {_next_month(now_utc)}.")
    return title, text


def _next_month(now_utc: datetime) -> str:
    year, month = (now_utc.year + 1, 1) if now_utc.month == 12 else (now_utc.year, now_utc.month + 1)
    return datetime(year, month, 1).strftime("%-d %B %Y")


def seen(provider: str, http_status: int | None, error_type: str, said: str, now: float | None = None) -> bool:
    """A failed call, from the log's writer: told once when it is a spending limit. True when this
    call is the one that told."""
    limit = limit_of(provider, http_status, error_type or "", said or "")
    if limit is None:
        return False
    now = time.time() if now is None else now
    key = _key(limit, now)
    with _lock:
        if key in _said:
            return False
        _said.add(key)
    title, text = words(limit, now)
    log.warning("%s: %s", title, text)
    lp = _LOOP[0] if _LOOP else None
    if lp is None or lp.is_closed():
        log.info("no loop to say the spending limit on; it is in the log only")
        return False
    from . import notices

    async def say() -> None:
        try:
            await notices.notify(title=title, body=text, kind="alarm", key=key, phone_text=text,
                                 at_once=True)
        except Exception:  # noqa: BLE001 - the log has it either way
            log.exception("the spending limit could not be told")

    asyncio.run_coroutine_threadsafe(say(), lp)
    return True
