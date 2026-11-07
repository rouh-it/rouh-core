"""`/internal/phone`: the one program's note to the owner's phone, sent with Rouh's own bot.

On the server the one program has a bot of its own (`/etc/one/telegram.json`, `one/phone.py`) and
sends a run's unanswered question to the owner's phone with Allow and Deny under it. In the
containers the one program is in the worker, where other people's code runs, so it holds no bot
token: it asks Rouh instead, on this address, with the key Rouh gave the worker
(`rouh/workerkey.py`), and Rouh sends it with the bot the installation set
(`ROUH_TELEGRAM_BOT_TOKEN` and `ROUH_TELEGRAM_CHAT_ID`, or its file), to the owner's one chat.

Held narrow: only from this machine or the worker (`from_this_machine`), only to the owner's own
chat, only text, and only buttons that open one of Rouh's own addresses, so a run that holds the
key can send the owner nothing they could not already be sent by the one program on the server.
"""
from __future__ import annotations

import logging

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from .common import answer, body_of, from_this_machine, only

log = logging.getLogger(__name__)

MOST = 3500


@csrf_exempt
@only("POST")
async def internal_phone(request: HttpRequest):
    if not from_this_machine(request):
        return answer({"ok": False, "error": "only this machine, or the worker with its key"}, status=403)
    from rouh import telegram
    from rouh.config import config

    body = body_of(request) or {}
    text = str(body.get("text") or "").strip()[:MOST]
    if not text:
        return answer({"ok": False, "error": "nothing to send"}, status=400)
    own = config.public_url.rstrip("/") + "/"
    rows = []
    for pair in body.get("buttons") or []:
        if not (isinstance(pair, (list, tuple)) and len(pair) == 2):
            continue
        label, url = str(pair[0])[:40], str(pair[1])
        if url.startswith(own) or url == own.rstrip("/"):
            rows.append({"text": label, "url": url})
    phone = telegram.Telegram(config.telegram_file, api_base=config.telegram_api_base)
    if not phone.configured():
        return answer({"ok": False, "error": "this Rouh has no Telegram bot set up"}, status=503)
    try:
        await phone.send_parts(text, buttons=[rows] if rows else None)
    except Exception as exc:  # noqa: BLE001 - one plain sentence back to the program
        log.warning("the one program's phone note was not sent: %s", type(exc).__name__)
        return answer({"ok": False, "error": f"Telegram did not take it ({type(exc).__name__})"}, status=502)
    return answer({"ok": True})
