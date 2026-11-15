"""What Rouh reads in a chat: the panel beside the composer, "What I'm reading" (`rouh/reading.py`).

    GET  /api/reading?chat=<id>     what the panel draws for that chat
    POST /api/reading               {"chat", "change": {"memory"|"rules"|"tools"|"md"|"html"|"histories": bool,
                                    "subtasks": "none"|"all"|"some", "picked": [task ids]}}; what it draws now

The owner's own chats, so anybody signed in to this Rouh, and nobody a page was only shared with: a reader of a
shared page is served by `rouh/web/guests.py` and never reaches here.
"""
from __future__ import annotations

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import reading

from .common import answer, body_of, only, refuse, who


def _exists(chat_id: str) -> bool:
    from rouh import conversations
    from rouh.models.objects import Chat

    return bool(chat_id) and (Chat.objects.filter(id=chat_id).exists() or bool(conversations.draft(chat_id)))


@only("GET", "POST")
async def reading_api(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    if request.method == "POST":
        sent = body_of(request)
        chat = str(sent.get("chat") or "")
        if not await sync_to_async(_exists)(chat):
            return refuse("There is no such chat.", 404)
        change = sent.get("change") if isinstance(sent.get("change"), dict) else {}
        await sync_to_async(reading.put)(chat, change)
    else:
        chat = str(request.GET.get("chat") or "")
        if not await sync_to_async(_exists)(chat):
            return refuse("There is no such chat.", 404)
    return answer(await sync_to_async(reading.view)(chat))
