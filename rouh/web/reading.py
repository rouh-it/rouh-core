"""What Rouh reads in a chat: Chat Options beside the composer, and the strip under the chat's title (`rouh/reading.py`).

    GET  /api/reading?chat=<id>     what the panel draws for that chat
    POST /api/reading               {"chat", "change": {
                                    how Rouh works (Chat Options): "mode": "simple"|"full"|"custom",
                                    "memory"|"rules"|"tools": bool, "off": [item ids turned off one by one],
                                    "reset": true (how Rouh works back to Rouh's defaults);
                                    what the chat is about (the strip's panel, never moving the mode):
                                    "task"|"others"|"step_histories"|"parent_task"|"parent_task_history"|
                                    "fork_history": bool, "subtasks": "none"|"all"|"some", "picked": [task ids],
                                    "steps_what": "all"|"md"|"html"}}; what both draw now

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
        await sync_to_async(reading.put)(chat, change, me)
    else:
        chat = str(request.GET.get("chat") or "")
        if not await sync_to_async(_exists)(chat):
            return refuse("There is no such chat.", 404)
    return answer(await sync_to_async(reading.view)(chat, me))


@only("POST")
async def incognito_api(request: HttpRequest):
    """POST /api/incognito {"start": true}: a new incognito chat, as {"chat": id}; {"end": "<id>"} ends one
    nobody is in (`rouh/incognito.py`). The page opens the new chat itself, and leaving it ends it."""
    from rouh import incognito, runtime

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    sent = body_of(request)
    if sent.get("start"):
        # Any other incognito chat nobody is in goes first: one started and never opened is not left behind.
        await runtime.incognito_left(incognito.ids())
        chat = await sync_to_async(incognito.start)()
        return answer({"chat": chat})
    if sent.get("end"):
        await runtime.incognito_left([str(sent.get("end"))])
        return answer({"ended": True})
    return refuse("Say start or end.", 400)
