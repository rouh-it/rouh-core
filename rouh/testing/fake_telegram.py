"""A stand-in for Telegram, both ways, so a test can write to Rouh from a "phone".

`fake_model.py` and `fake_voice.py` are the same idea either side of this one:
a real HTTP server in front of the real client, so what a test proves is what
really went over the wire rather than what a mock was asked to pretend.

**Sending.** It answers the Bot API's ``sendMessage``, ``sendChatAction`` and
``setMessageReaction`` (drawn on the message in the phone page below),
and writes down every request it was given, whole: the bot token out of the
address, the chat id, the text and the rest of the body. `rouh/telegram.py` is
unchanged in front of it, so a test asserting on those files is asserting on
the bytes Telegram itself would have received. It refuses a text longer than
Telegram takes, with Telegram's own words, so a reply that was not split
fails here as it would there.

**Receiving.** A test writes to the bot as a person would, with ``POST
/_send``, and the message waits here as an update until Rouh asks for it with
``getUpdates``, which is held open the way Telegram holds a long poll. Asking
with an offset confirms every update before it and they are gone, as on
Telegram; ``POST /_forget`` brings them all back, which is Telegram never
having heard the confirmation, so a test can prove Rouh's own record of where
it got to is what keeps a message from being answered twice. Photos,
documents and voice notes carry a file, handed over with ``getFile`` and the
file address, exactly as the real API has it. ``POST /_conflict`` makes every
read fail with the 409 Telegram gives when somebody else is reading the bot.

**Buttons.** A message sent with inline buttons keeps them, and ``POST
/_press`` presses one, as a finger on the phone would: the update Rouh reads
is a ``callback_query`` carrying the button's data and the message it was
under. ``answerCallbackQuery`` and ``editMessageReplyMarkup`` are answered and
written down like everything else, and the second changes the buttons the
message has from then on. ``reply_to_message_id`` in ``/_send`` writes a
reply to a message that is really in the chat, whole, buttons and all.

**Groups and topics.** ``POST /_group`` makes a group with the bot in it, as a
person adding the bot would, and Rouh is told with a ``my_chat_member``
update; ``POST /_group_change`` turns its Topics on or off, makes the bot an
admin or not, moves it to a supergroup (``migrate``) or takes the bot out.
``createForumTopic`` opens a topic only where the real one would - a forum,
with the bot an admin who can manage topics - and a message written or sent
into a topic carries its ``message_thread_id``, and, as on Telegram, a reply to
the message that opened the topic when it is not a reply to anything else.
``setMyCommands`` is kept per scope, and ``GET /_menu`` answers which commands
the menu of a chat shows a person, the way the apps work it out.

**The person's own account.** What Rouh does as the owner, with their own account
(`rouh/telegram_account.py`), it asks here under ``/_account/`` instead of
Telegram's MTProto: sending a login code (it is always ``CODE``), signing in
(a phone number ending in 99 has two-step verification, and its password is
``PASSWORD``), making a basic group with the bot in it, making the bot its
admin, posting in it as them, and logging out. The bot hears what it would on
Telegram, with its privacy mode on: in a group, a command, a reply to it, or
everything once it is an admin.

**The phone.** ``GET /phone?chat=4242`` is Telegram as the phone shows it: the
private chat and every group, each group's topics, every message either way,
the buttons under Rouh's, the "/" menu of commands, and a box to write in -
so a browser can do what the owner does.

Point ``ROUH_TELEGRAM_API_BASE`` at it and give Rouh a secrets file of its
own with ``ROUH_TELEGRAM_FILE``.

    python -m rouh.testing.fake_telegram --port 8097 --record /tmp/telegram

    curl -s localhost:8097/_send -H 'content-type: application/json' \\
         -d '{"chat_id": 4242, "text": "What is on today?"}'
    curl -s localhost:8097/_send -H 'content-type: application/json' \\
         -d '{"chat_id": 4242, "photo": {"path": "/tmp/cat.jpg"}, "caption": "Who is this?"}'
    curl -s localhost:8097/how-it-went
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

#: The chat this stand-in refuses: a bot that has never been written to by
#: that person, which is what a chat id copied down wrong really gives.
UNKNOWN_CHAT = 999

#: Telegram's limit on one message, in UTF-16 code units.
LIMIT = 4096

#: Where update ids start. Real ones are big numbers; nothing depends on it.
FIRST_UPDATE = 100_000

#: The person whose phone this is: who writes in a group, and adds the bot to
#: one, unless a test says somebody else did.
PERSON = 4242

#: The login code Telegram "sends", and the two-step verification password of
#: a phone number that ends in 99.
CODE = "12345"
PASSWORD = "open sesame"

#: A token Telegram does not know: the secret after the colon starts with this. What a token
#: copied wrong really gives is a 401 from every method, getMe first (`rouh/telegram_bot.py`).
WRONG_TOKEN = "AAwrong"

#: The bot, as getMe says it.
BOT = {"id": 123456789, "is_bot": True, "first_name": "Rouh", "username": "rouh_telegram_bot",
       "can_join_groups": True, "can_read_all_group_messages": False}


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def build_app(record_dir: str | None = None, first_update: int = FIRST_UPDATE) -> FastAPI:
    app = FastAPI()
    counter = {"n": 0, "read": 0, "actions": 0}
    #: Every update ever written to the bot, oldest first, and the lowest id
    #: not yet confirmed.
    held: list[dict] = []
    state = {"next": first_update, "confirmed_below": 0, "message": 1, "conflict": False,
             "offsets": []}
    files: dict[str, dict] = {}
    arrived = asyncio.Event()
    #: The chat as the phone shows it, oldest first: every message the bot
    #: sent and every one written to it, by id, with the buttons it has now.
    shown: list[dict] = []
    #: What the phone showed at the top for a moment after a press.
    toasts: list[dict] = []
    #: Every group the bot is in or was in, by id: its title, whether it has
    #: topics, the bot's place in it, and its topics by thread.
    groups: dict[int, dict] = {}
    #: The menus set with setMyCommands, by scope.
    menus: dict[str, list] = {}
    next_group = {"n": 0}

    def scope_key(scope) -> str:
        if isinstance(scope, str):
            try:
                scope = json.loads(scope)
            except ValueError:
                scope = {}
        scope = scope or {"type": "default"}
        return json.dumps({k: str(v) for k, v in sorted(scope.items())})

    def group_of(chat_id) -> dict | None:
        try:
            return groups.get(int(chat_id))
        except (TypeError, ValueError):
            return None

    def chat_object(chat_id) -> dict:
        found = group_of(chat_id)
        if found is None:
            return {"id": int(chat_id), "type": "private", "first_name": "Alex"}
        out = {"id": found["id"], "type": found["type"], "title": found["title"]}
        if found["is_forum"]:
            out["is_forum"] = True
        return out

    def bot_member(found: dict, token: str = "") -> dict:
        me = {"id": int(token.split(":")[0]) if token and token.split(":")[0].isdigit()
              else 123456789, "is_bot": True, "first_name": "Rouh"}
        out = {"user": me, "status": found["bot_status"]}
        if found["bot_status"] == "administrator":
            out.update(can_manage_topics=bool(found["can_manage_topics"]),
                       can_delete_messages=True, can_pin_messages=True,
                       can_manage_chat=True, can_invite_users=True)
        return out

    def bot_hears(found: dict, message: dict) -> bool:
        """What a bot with privacy mode on is given in a group."""
        if found["bot_status"] == "administrator":
            return True
        if found["bot_status"] != "member":
            return False
        replied = message.get("reply_to_message") or {}
        return (str(message.get("text") or "").startswith("/")
                or bool((replied.get("from") or {}).get("is_bot")))

    #: Signed-in and half-signed-in sessions of the person's own account.
    sessions: dict[str, dict] = {}

    def queue(update_body: dict) -> dict:
        update = {"update_id": state["next"], **update_body}
        state["next"] += 1
        held.append(update)
        arrived.set()
        return update

    def shown_message(message_id) -> dict | None:
        try:
            wanted = int(message_id)
        except (TypeError, ValueError):
            return None
        return next((m for m in shown if m["message_id"] == wanted), None)

    def write(name: str, body: dict) -> None:
        if not record_dir:
            return
        counter["n"] += 1
        at = f"{counter['n']:04d}-{int(time.time() * 1000)}-{name}.json"
        with open(os.path.join(record_dir, at), "w", encoding="utf-8") as fh:
            json.dump(body, fh)

    async def body_of(request: Request) -> dict:
        try:
            got = await request.json()
        except ValueError:
            form = await request.form()
            got = dict(form)
        return got if isinstance(got, dict) else {}

    def refused(code: int, words: str, **extra) -> JSONResponse:
        return JSONResponse({"ok": False, "error_code": code, "description": words, **extra},
                            status_code=code)

    @app.post("/bot{token}/sendMessage")
    async def send_message(token: str, request: Request):
        body = await body_of(request)
        write("sendMessage", {"token": token, "body": body})
        text = str(body.get("text") or "")
        # A chat id nobody has ever written to is the one refusal worth
        # standing in for, because it is what a wrong chat id really gives:
        # a 400 with words in it, not a connection that fails.
        if str(body.get("chat_id") or "") == str(UNKNOWN_CHAT):
            return refused(400, "Bad Request: chat not found")
        if not text.strip():
            return refused(400, "Bad Request: message text is empty")
        if _units(text) > LIMIT:
            return refused(400, "Bad Request: message is too long")
        markup = body.get("reply_markup")
        if isinstance(markup, str):
            try:
                markup = json.loads(markup)
            except ValueError:
                markup = None
        buttons = (markup or {}).get("inline_keyboard") if isinstance(markup, dict) else None
        for row in buttons or []:
            for button in row:
                if len(str(button.get("callback_data") or "").encode()) > 64:
                    return refused(400, "Bad Request: BUTTON_DATA_INVALID")
        replying = (body.get("reply_parameters") or {}).get("message_id") \
            if isinstance(body.get("reply_parameters"), dict) else None
        found = group_of(body.get("chat_id"))
        thread = body.get("message_thread_id")
        if found is not None:
            if found["bot_status"] not in ("member", "administrator"):
                return refused(403, "Forbidden: bot is not a member of the supergroup chat")
            if thread and int(thread) not in found["topics"]:
                return refused(400, "Bad Request: message thread not found")
        elif thread:
            return refused(400, "Bad Request: message thread not found")
        state["message"] += 1
        sent = {
            "message_id": state["message"], "date": int(time.time()),
            "chat": chat_object(body.get("chat_id")),
            "from": {"id": 1, "is_bot": True, "first_name": "Rouh"},
            "text": text,
        }
        if thread:
            sent["message_thread_id"] = int(thread)
            sent["is_topic_message"] = True
            if replying is None:
                replying = int(thread)
        if buttons:
            sent["reply_markup"] = {"inline_keyboard": buttons}
        quoted = shown_message(replying)
        if quoted is not None:
            sent["reply_to_message"] = {k: v for k, v in quoted.items()
                                        if k != "reply_to_message"}
        shown.append(dict(sent))
        return JSONResponse({"ok": True, "result": sent})

    @app.post("/bot{token}/createForumTopic")
    async def create_forum_topic(token: str, request: Request):
        body = await body_of(request)
        write("createForumTopic", {"token": token, "body": body})
        found = group_of(body.get("chat_id"))
        name = str(body.get("name") or "")
        if found is None:
            return refused(400, "Bad Request: chat not found")
        if not found["is_forum"]:
            return refused(400, "Bad Request: the chat is not a forum")
        if found["bot_status"] != "administrator" or not found["can_manage_topics"]:
            return refused(400, "Bad Request: not enough rights to create a topic")
        if not 1 <= len(name) <= 128:
            return refused(400, "Bad Request: TOPIC_TITLE_EMPTY" if not name
                           else "Bad Request: topic name is too long")
        state["message"] += 1
        thread = state["message"]
        found["topics"][thread] = name
        shown.append({"message_id": thread, "date": int(time.time()),
                      "chat": chat_object(found["id"]),
                      "from": {"id": 1, "is_bot": True, "first_name": "Rouh"},
                      "message_thread_id": thread, "is_topic_message": True,
                      "forum_topic_created": {"name": name, "icon_color": 7322096}})
        return JSONResponse({"ok": True, "result": {"message_thread_id": thread, "name": name,
                                                    "icon_color": 7322096}})

    @app.post("/bot{token}/getMe")
    async def get_me(token: str):
        if token.partition(":")[2].startswith(WRONG_TOKEN):
            return refused(401, "Unauthorized")
        return JSONResponse({"ok": True, "result": BOT})

    @app.post("/bot{token}/createChatInviteLink")
    async def create_chat_invite_link(token: str, request: Request):
        body = await body_of(request)
        write("createChatInviteLink", {"token": token, "body": body})
        found = group_of(body.get("chat_id"))
        if found is None:
            return refused(400, "Bad Request: chat not found")
        if found["bot_status"] != "administrator":
            return refused(400, "Bad Request: not enough rights to manage chat invite link")
        return JSONResponse({"ok": True, "result": {
            "invite_link": f"https://t.me/+standin{abs(found['id'])}", "name": body.get("name"),
            "creator": BOT, "creates_join_request": False, "is_primary": False,
            "is_revoked": False}})

    # --- the person's own account, as Rouh's Telethon asks it ------------------------

    def account_refused(words: str) -> JSONResponse:
        return JSONResponse({"error": words})

    @app.post("/_account/send_code")
    async def account_send_code(request: Request):
        body = await body_of(request)
        write("account-send_code", {"api_id": body.get("api_id"), "phone": body.get("phone")})
        if int(body.get("api_id") or 0) <= 0 or len(str(body.get("api_hash") or "")) < 16:
            return account_refused("Telegram does not know that API id and hash. Copy them "
                                   "again from my.telegram.org, under API development tools.")
        phone = str(body.get("phone") or "")
        if len(phone) < 8:
            return account_refused("Telegram says that phone number is not valid. Write it "
                                   "with the country code.")
        n = len(sessions) + 1
        session = f"pending-{n}"
        sessions[session] = {"phone": phone, "authorized": False, "hash": f"hash-{n}",
                             "password": phone.endswith("99")}
        return JSONResponse({"session": session, "phone_code_hash": f"hash-{n}"})

    @app.post("/_account/sign_in")
    async def account_sign_in(request: Request):
        body = await body_of(request)
        write("account-sign_in", {"phone": body.get("phone")})
        held = sessions.get(str(body.get("session") or ""))
        if held is None or body.get("phone_code_hash") != held["hash"]:
            return account_refused("That code has expired. Start again for a new one.")
        if str(body.get("code") or "") != CODE:
            return account_refused("That code is not right. Check it in Telegram and type "
                                   "it again.")
        if held["password"]:
            return JSONResponse({"password_needed": True, "session": body["session"]})
        held["authorized"] = True
        return JSONResponse({"session": body["session"], "name": "Alex Morgan"})

    @app.post("/_account/password")
    async def account_password(request: Request):
        body = await body_of(request)
        write("account-password", {})
        held = sessions.get(str(body.get("session") or ""))
        if held is None:
            return account_refused("That code has expired. Start again for a new one.")
        if str(body.get("password") or "") != PASSWORD:
            return account_refused("That is not your Telegram password.")
        held["authorized"] = True
        return JSONResponse({"session": body["session"], "name": "Alex Morgan"})

    def signed_in(body: dict) -> dict | None:
        held = sessions.get(str(body.get("session") or ""))
        return held if held is not None and held["authorized"] else None

    REVOKED = ("Telegram no longer accepts Rouh's session: it was logged out, perhaps from "
               "the list of devices in Telegram's settings. Connect the account again in "
               "Rouh's Settings.")

    @app.post("/_account/create_group")
    async def account_create_group(request: Request):
        """A basic group made as the person, with the bot in it."""
        body = await body_of(request)
        write("account-create_group", {"title": body.get("title"), "users": body.get("users")})
        if signed_in(body) is None:
            return account_refused(REVOKED)
        if [u for u in body.get("users") or [] if u != BOT["username"]]:
            return account_refused("Telegram said no (UsernameNotOccupiedError).")
        next_group["n"] += 1
        chat_id = -4000000000 - next_group["n"]
        found = {"id": chat_id, "title": str(body.get("title") or ""), "type": "group",
                 "is_forum": False, "bot_status": "member", "can_manage_topics": False,
                 "topics": {}}
        groups[chat_id] = found
        state["message"] += 1
        shown.append({"message_id": state["message"], "date": int(time.time()),
                      "chat": chat_object(chat_id),
                      "from": {"id": PERSON, "is_bot": False, "first_name": "Alex"},
                      "group_chat_created": True})
        queue({"my_chat_member": {
            "chat": chat_object(chat_id), "date": int(time.time()),
            "from": {"id": PERSON, "is_bot": False, "first_name": "Alex"},
            "old_chat_member": {"user": BOT, "status": "left"},
            "new_chat_member": {"user": BOT, "status": "member"}}})
        return JSONResponse({"chat_id": chat_id})

    @app.post("/_account/make_admin")
    async def account_make_admin(request: Request):
        body = await body_of(request)
        write("account-make_admin", {"chat_id": body.get("chat_id"), "user": body.get("user")})
        if signed_in(body) is None:
            return account_refused(REVOKED)
        found = group_of(body.get("chat_id"))
        if found is None:
            return account_refused("Telegram said no (ChatIdInvalidError).")
        was = bot_member(found)
        found["bot_status"] = "administrator"
        queue({"my_chat_member": {
            "chat": chat_object(found["id"]), "date": int(time.time()),
            "from": {"id": PERSON, "is_bot": False, "first_name": "Alex"},
            "old_chat_member": was, "new_chat_member": bot_member(found)}})
        return JSONResponse({"ok": True})

    @app.post("/_account/send")
    async def account_send(request: Request):
        """A message posted in a group as the person, with their own account."""
        body = await body_of(request)
        write("account-send", {"chat_id": body.get("chat_id"), "text": body.get("text")})
        if signed_in(body) is None:
            return account_refused(REVOKED)
        found = group_of(body.get("chat_id"))
        if found is None:
            return account_refused("Telegram said no (ChatIdInvalidError).")
        state["message"] += 1
        message = {"message_id": state["message"], "date": int(time.time()),
                   "chat": chat_object(found["id"]),
                   "from": {"id": PERSON, "is_bot": False, "first_name": "Alex",
                            "username": "alex"},
                   "text": str(body.get("text") or "")}
        shown.append(message)
        if bot_hears(found, message):
            queue({"message": message})
        return JSONResponse({"ok": True, "message_id": message["message_id"]})

    @app.post("/_account/log_out")
    async def account_log_out(request: Request):
        body = await body_of(request)
        write("account-log_out", {})
        sessions.pop(str(body.get("session") or ""), None)
        return JSONResponse({"ok": True})

    @app.post("/bot{token}/getChat")
    async def get_chat(token: str, request: Request):
        body = await body_of(request)
        write("getChat", {"token": token, "body": body})
        found = group_of(body.get("chat_id"))
        if found is None and str(body.get("chat_id")).lstrip("-").isdigit() \
                and int(body["chat_id"]) < 0:
            return refused(400, "Bad Request: chat not found")
        return JSONResponse({"ok": True, "result": chat_object(body.get("chat_id"))})

    @app.post("/bot{token}/getChatMember")
    async def get_chat_member(token: str, request: Request):
        body = await body_of(request)
        write("getChatMember", {"token": token, "body": body})
        found = group_of(body.get("chat_id"))
        if found is None:
            return refused(400, "Bad Request: chat not found")
        if str(body.get("user_id")) == token.split(":")[0]:
            return JSONResponse({"ok": True, "result": bot_member(found, token)})
        return JSONResponse({"ok": True, "result": {
            "user": {"id": int(body.get("user_id") or 0), "is_bot": False, "first_name": "Alex"},
            "status": "creator"}})

    @app.post("/bot{token}/setMyCommands")
    async def set_my_commands(token: str, request: Request):
        body = await body_of(request)
        write("setMyCommands", {"token": token, "body": body})
        commands = body.get("commands") or []
        if isinstance(commands, str):
            commands = json.loads(commands)
        for one in commands:
            name = str(one.get("command") or "")
            if not name or len(name) > 32 or not all(c.islower() or c.isdigit() or c == "_"
                                                     for c in name):
                return refused(400, "Bad Request: BOT_COMMAND_INVALID")
            if not 1 <= len(str(one.get("description") or "")) <= 256:
                return refused(400, "Bad Request: BOT_COMMAND_DESCRIPTION_INVALID")
        menus[scope_key(body.get("scope"))] = commands
        return JSONResponse({"ok": True, "result": True})

    @app.post("/bot{token}/getMyCommands")
    async def get_my_commands(token: str, request: Request):
        body = await body_of(request)
        return JSONResponse({"ok": True, "result": menus.get(scope_key(body.get("scope")), [])})

    @app.post("/bot{token}/answerCallbackQuery")
    async def answer_callback_query(token: str, request: Request):
        body = await body_of(request)
        write("answerCallbackQuery", {"token": token, "body": body})
        if body.get("text"):
            toasts.append({"text": str(body["text"]), "at": time.time()})
        return JSONResponse({"ok": True, "result": True})

    @app.post("/bot{token}/editMessageReplyMarkup")
    async def edit_message_reply_markup(token: str, request: Request):
        body = await body_of(request)
        write("editMessageReplyMarkup", {"token": token, "body": body})
        found = shown_message(body.get("message_id"))
        if found is None or not found["from"].get("is_bot"):
            return refused(400, "Bad Request: message to edit not found")
        markup = body.get("reply_markup") or {}
        if isinstance(markup, str):
            markup = json.loads(markup or "{}")
        buttons = markup.get("inline_keyboard") or []
        if (found.get("reply_markup") or {}).get("inline_keyboard", []) == buttons:
            return refused(400, "Bad Request: message is not modified")
        if buttons:
            found["reply_markup"] = {"inline_keyboard": buttons}
        else:
            found.pop("reply_markup", None)
        return JSONResponse({"ok": True, "result": found})

    @app.post("/bot{token}/sendChatAction")
    async def send_chat_action(token: str, request: Request):
        body = await body_of(request)
        found = group_of(body.get("chat_id"))
        thread = body.get("message_thread_id")
        if thread and (found is None or int(thread) not in found["topics"]):
            return refused(400, "Bad Request: message thread not found")
        counter["actions"] += 1
        write("sendChatAction", {"token": token, "body": body})
        return JSONResponse({"ok": True, "result": True})

    @app.post("/bot{token}/setMessageReaction")
    async def set_message_reaction(token: str, request: Request):
        """A reaction on a message in the chat, as Got it puts one (`rouh/got_it.py`): shown
        on the message from then on, the bot's own replacing the last."""
        body = await body_of(request)
        found = shown_message(body.get("message_id"))
        if found is None or str(found["chat"].get("id")) != str(body.get("chat_id")):
            return refused(400, "Bad Request: message to react not found")
        reaction = body.get("reaction") or []
        if isinstance(reaction, str):
            reaction = json.loads(reaction or "[]")
        found["reactions"] = [r.get("emoji") for r in reaction if isinstance(r, dict)]
        write("setMessageReaction", {"token": token, "body": body})
        return JSONResponse({"ok": True, "result": True})

    def waiting(offset) -> list[dict]:
        if offset is not None:
            try:
                offset = int(offset)
            except (TypeError, ValueError):
                offset = None
        if offset is not None:
            # Asking from here confirms everything before it, for good.
            state["confirmed_below"] = max(state["confirmed_below"], offset)
        floor = state["confirmed_below"]
        return [u for u in held if u["update_id"] >= floor]

    @app.get("/bot{token}/getUpdates")
    @app.post("/bot{token}/getUpdates")
    async def get_updates(token: str, request: Request):
        """A long poll: held open until something arrives or `timeout` runs out."""
        body = dict(request.query_params)
        if request.method == "POST":
            body.update(await body_of(request))
        counter["read"] += 1
        state["offsets"] = (state["offsets"] + [body.get("offset")])[-50:]
        if state["conflict"]:
            return refused(409, "Conflict: terminated by other getUpdates request; make "
                                "sure that only one bot instance is running")
        try:
            wait = min(float(body.get("timeout") or 0), 50.0)
        except (TypeError, ValueError):
            wait = 0.0
        got = waiting(body.get("offset"))
        end = time.monotonic() + wait
        while not got and time.monotonic() < end:
            arrived.clear()
            with _quietly():
                await asyncio.wait_for(arrived.wait(), timeout=max(0.05, end - time.monotonic()))
            got = waiting(body.get("offset"))
        return JSONResponse({"ok": True, "result": got[:100]})

    @app.post("/bot{token}/getFile")
    async def get_file(token: str, request: Request):
        body = await body_of(request)
        found = files.get(str(body.get("file_id") or ""))
        if found is None:
            return refused(400, "Bad Request: invalid file_id")
        return JSONResponse({"ok": True, "result": {
            "file_id": found["id"], "file_unique_id": found["id"] + "u",
            "file_size": len(found["data"]), "file_path": found["path"]}})

    @app.get("/file/bot{token}/{path:path}")
    async def file_itself(token: str, path: str):
        for found in files.values():
            if found["path"] == path:
                return Response(found["data"], media_type="application/octet-stream")
        return Response(b"not found", status_code=404)

    # --- what a test does ------------------------------------------------------------

    def keep(spec: dict, kind: str, default_name: str) -> dict:
        """A file a test sends, from a path on disk or from base64."""
        if spec.get("path"):
            with open(spec["path"], "rb") as fh:
                data = fh.read()
            name = spec.get("name") or os.path.basename(spec["path"])
        else:
            data = base64.b64decode(spec.get("b64") or "")
            name = spec.get("name") or default_name
        file_id = f"file-{len(files) + 1}"
        files[file_id] = {"id": file_id, "data": data,
                          "path": f"{kind}/{file_id}-{name}"}
        return {"file_id": file_id, "file_unique_id": file_id + "u", "file_size": len(data),
                "name": name}

    @app.post("/_send")
    async def a_person_writes(request: Request):
        """A message to the bot, as somebody on a phone would send it."""
        spec = await body_of(request)
        chat = int(spec.get("chat_id") or 0)
        found = group_of(chat)
        person = int(spec.get("from_id") or (PERSON if found is not None else chat))
        state["message"] += 1
        message: dict = {
            "message_id": state["message"],
            "date": int(spec.get("date") or time.time()),
            "chat": (chat_object(chat) if found is not None else
                     {"id": chat, "type": spec.get("chat_type") or "private",
                      "first_name": "Alex"}),
            "from": {"id": person, "is_bot": bool(spec.get("is_bot")),
                     "first_name": spec.get("first_name") or "Alex",
                     "username": spec.get("username") or "alex"},
        }
        thread = int(spec.get("thread") or 0)
        if thread:
            if found is None or thread not in found["topics"]:
                return JSONResponse({"ok": False, "why": "no such topic"}, status_code=404)
            message["message_thread_id"] = thread
            message["is_topic_message"] = True
            # Every message in a topic is a reply to the one that opened it,
            # unless it is a reply to something else, as on Telegram.
            opened = shown_message(thread)
            if opened is not None:
                message["reply_to_message"] = {k: v for k, v in opened.items()
                                               if k != "reply_to_message"}
        if spec.get("text"):
            message["text"] = str(spec["text"])
        if spec.get("caption"):
            message["caption"] = str(spec["caption"])
        if spec.get("media_group_id"):
            message["media_group_id"] = str(spec["media_group_id"])
        if spec.get("reply_to"):
            message["reply_to_message"] = {
                "message_id": 1, "date": int(time.time()) - 60,
                "chat": message["chat"], "from": {"id": 1, "is_bot": True, "first_name": "Rouh"},
                "text": str(spec["reply_to"])}
        quoted = shown_message(spec.get("reply_to_message_id"))
        if quoted is not None:
            message["reply_to_message"] = {k: v for k, v in quoted.items()
                                           if k != "reply_to_message"}
        if isinstance(spec.get("photo"), dict):
            got = keep(spec["photo"], "photos", "photo.jpg")
            message["photo"] = [
                {"file_id": got["file_id"], "file_unique_id": got["file_unique_id"] + "s",
                 "file_size": max(1, got["file_size"] // 10), "width": 90, "height": 90},
                {"file_id": got["file_id"], "file_unique_id": got["file_unique_id"],
                 "file_size": got["file_size"], "width": 1280, "height": 960}]
        if isinstance(spec.get("document"), dict):
            got = keep(spec["document"], "documents", "file.bin")
            message["document"] = {"file_id": got["file_id"],
                                   "file_unique_id": got["file_unique_id"],
                                   "file_name": got["name"],
                                   "mime_type": spec["document"].get("mime") or "",
                                   "file_size": got["file_size"]}
        if isinstance(spec.get("voice"), dict):
            voice = dict(spec["voice"])
            if not voice.get("path") and not voice.get("b64"):
                # An Ogg page header and some bytes: nothing reads the audio,
                # and the stand-in voice hears whatever its script says.
                voice["b64"] = base64.b64encode(b"OggS" + bytes(2000)).decode()
            got = keep(voice, "voice", "voice.oga")
            message["voice"] = {"file_id": got["file_id"], "file_unique_id": got["file_unique_id"],
                                "duration": int(voice.get("seconds") or 3),
                                "mime_type": "audio/ogg", "file_size": got["file_size"]}
        if spec.get("sticker"):
            message["sticker"] = {"file_id": "sticker-1", "emoji": "👍", "width": 512,
                                  "height": 512, "is_animated": False, "type": "regular"}
        shown.append(message)
        if found is not None and not bot_hears(found, message):
            # Written in the group, and never given to the bot.
            return JSONResponse({"update_id": None, "message_id": message["message_id"]})
        update = {"update_id": state["next"], "message": message}
        state["next"] += 1
        held.append(update)
        arrived.set()
        return JSONResponse({"update_id": update["update_id"],
                             "message_id": message["message_id"]})

    @app.post("/_press")
    async def a_person_presses(request: Request):
        """A finger on a button under one of the bot's messages.

        ``{"message_id", "data"}`` at the least; ``from_id`` and ``chat_id``
        say whose finger and whose chat, as in ``/_send``. The data is the
        button's own unless it is given, so a test can also press a button
        that is not there any more, which a phone left open for a day does.
        """
        spec = await body_of(request)
        found = shown_message(spec.get("message_id"))
        if found is None:
            return JSONResponse({"ok": False, "why": "no such message"}, status_code=404)
        data = spec.get("data")
        if data is None:
            wanted = str(spec.get("text") or "")
            for row in (found.get("reply_markup") or {}).get("inline_keyboard") or []:
                for button in row:
                    if not wanted or button.get("text") == wanted:
                        data = button.get("callback_data")
                        break
                if data is not None:
                    break
        if data is None:
            return JSONResponse({"ok": False, "why": "no such button"}, status_code=404)
        chat = int(spec.get("chat_id") or found["chat"]["id"] or 0)
        person = int(spec.get("from_id") or chat)
        on = dict(found, chat={"id": chat, "type": spec.get("chat_type") or "private",
                               "first_name": "Alex"})
        on.pop("reply_to_message", None)
        update = {"update_id": state["next"], "callback_query": {
            "id": f"press-{state['next']}",
            "from": {"id": person, "is_bot": bool(spec.get("is_bot")),
                     "first_name": spec.get("first_name") or "Alex",
                     "username": spec.get("username") or "alex"},
            "message": on, "chat_instance": "4242-rouh", "data": str(data)}}
        state["next"] += 1
        held.append(update)
        arrived.set()
        return JSONResponse({"update_id": update["update_id"], "data": data})

    @app.post("/_group")
    async def a_group_with_the_bot(request: Request):
        """A group made on the phone, with the bot added to it by `from_id`.

        ``{"title", "forum": bool, "admin": bool, "can_manage_topics": bool,
        "from_id"}``. Rouh hears it as Telegram tells a bot: a ``my_chat_member``
        update saying who put it there and as what.
        """
        spec = await body_of(request)
        next_group["n"] += 1
        chat_id = -1001000000000 - next_group["n"]
        admin = bool(spec.get("admin"))
        found = {"id": chat_id, "title": str(spec.get("title") or "Rouh forks"),
                 "type": "supergroup", "is_forum": bool(spec.get("forum")),
                 "bot_status": "administrator" if admin else "member",
                 "can_manage_topics": bool(spec.get("can_manage_topics", admin)),
                 "topics": {}}
        groups[chat_id] = found
        update = queue({"my_chat_member": {
            "chat": chat_object(chat_id), "date": int(time.time()),
            "from": {"id": int(spec.get("from_id") or PERSON), "is_bot": False,
                     "first_name": "Alex"},
            "old_chat_member": {"user": bot_member(found)["user"], "status": "left"},
            "new_chat_member": bot_member(found)}})
        return JSONResponse({"chat_id": chat_id, "update_id": update["update_id"]})

    @app.post("/_group_change")
    async def a_group_changes(request: Request):
        """Topics on or off, the bot made an admin or not, a move to a new id, or
        the bot taken out: ``{"chat_id", "forum"?, "admin"?, "can_manage_topics"?,
        "migrate"?, "left"?, "from_id"?}``."""
        spec = await body_of(request)
        found = group_of(spec.get("chat_id"))
        if found is None:
            return JSONResponse({"ok": False, "why": "no such group"}, status_code=404)
        who = {"id": int(spec.get("from_id") or PERSON), "is_bot": False, "first_name": "Alex"}
        was = bot_member(found)
        if "forum" in spec:
            found["is_forum"] = bool(spec["forum"])
        if spec.get("migrate"):
            # A basic group made a supergroup: a new id, and Telegram says so
            # in the old chat.
            next_group["n"] += 1
            new_id = -1001000000000 - next_group["n"]
            old_id = found["id"]
            state["message"] += 1
            queue({"message": {"message_id": state["message"], "date": int(time.time()),
                               "chat": chat_object(old_id), "from": who,
                               "migrate_to_chat_id": new_id}})
            groups.pop(old_id)
            found["id"] = new_id
            groups[new_id] = found
        if "admin" in spec:
            found["bot_status"] = "administrator" if spec["admin"] else "member"
            found["can_manage_topics"] = bool(spec.get("can_manage_topics", spec["admin"]))
        elif "can_manage_topics" in spec:
            found["can_manage_topics"] = bool(spec["can_manage_topics"])
        if spec.get("left"):
            found["bot_status"] = "left"
        now = bot_member(found)
        if now != was:
            queue({"my_chat_member": {"chat": chat_object(found["id"]),
                                      "date": int(time.time()), "from": who,
                                      "old_chat_member": was, "new_chat_member": now}})
        return JSONResponse({"ok": True, "chat_id": found["id"]})

    @app.get("/_chat")
    async def the_chat(chat: str = ""):
        """The chat as the phone shows it, for the page below and for a test."""
        mine = [m for m in shown if not chat or str(m["chat"].get("id")) == str(chat)]
        return JSONResponse({"messages": mine, "toasts": toasts[-5:]})

    @app.get("/_chats")
    async def the_chats(person: str = str(PERSON)):
        """The phone's list of chats: the private chat, then every group and its topics."""
        out = [{"id": int(person), "title": "Rouh", "type": "private", "topics": []}]
        for found in groups.values():
            if found["bot_status"] == "left":
                continue
            out.append({"id": found["id"], "title": found["title"], "type": found["type"],
                        "is_forum": found["is_forum"],
                        "topics": [{"thread": t, "name": n} for t, n in found["topics"].items()]})
        return JSONResponse({"chats": out})

    @app.get("/_menu")
    async def the_menu(chat: str, person: str = str(PERSON)):
        """The commands the "/" menu of a chat shows a person, found the way the
        apps find them: the narrowest scope that has any."""
        if group_of(chat) is not None:
            tries = [{"type": "chat_member", "chat_id": chat, "user_id": person},
                     {"type": "chat", "chat_id": chat}, {"type": "all_group_chats"},
                     {"type": "default"}]
        else:
            tries = [{"type": "chat", "chat_id": chat}, {"type": "all_private_chats"},
                     {"type": "default"}]
        for scope in tries:
            got = menus.get(scope_key(scope))
            if got:
                return JSONResponse({"commands": got, "scope": scope})
        return JSONResponse({"commands": [], "scope": None})

    @app.get("/_state")
    async def the_state():
        return JSONResponse({"groups": {str(k): v for k, v in groups.items()}, "menus": menus})

    @app.get("/phone")
    async def phone():
        return Response(PHONE, media_type="text/html")

    @app.post("/_forget")
    async def forget():
        """As though Telegram never heard a confirmation: every update is back."""
        state["confirmed_below"] = 0
        return JSONResponse({"ok": True, "held": len(held)})

    @app.post("/_conflict")
    async def conflict(request: Request):
        spec = await body_of(request)
        state["conflict"] = bool(spec.get("on", True))
        return JSONResponse({"ok": True, "conflict": state["conflict"]})

    @app.get("/_updates")
    async def updates():
        return JSONResponse({"held": held, "confirmed_below": state["confirmed_below"]})

    @app.get("/how-it-went")
    async def how_it_went():
        """What a test asks, when it would rather not read the directory."""
        return JSONResponse({"sent": counter["n"], "reads": counter["read"],
                             "actions": counter["actions"], "offsets": state["offsets"],
                             "confirmed_below": state["confirmed_below"],
                             "held": len(held)})

    return app


#: The phone, as far as a browser needs one: the chats and the topics in them,
#: every message, the buttons, the "/" menu, and a box.
PHONE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Telegram (stand-in)</title>
<link rel="icon" href="data:,">
<style>
  :root { --bg: #d9e4ec; --me: #e1ffc7; --bot: #ffffff; --ink: #111; --soft: #6b7b88;
          --key: #f4f7fa; --line: #c7d3dc; --side: #ffffff; --pick: #e3edf6; --head: #517da2; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.4 system-ui, sans-serif; color: var(--ink);
         background: var(--bg); display: flex; height: 100vh; }
  nav { width: 260px; flex: none; background: var(--side); border-right: 1px solid var(--line);
        overflow-y: auto; }
  nav h2 { font-size: 13px; color: var(--soft); margin: 14px 16px 6px; font-weight: 600; }
  nav button { display: block; width: 100%; text-align: left; border: 0; background: none;
               font: inherit; padding: 9px 16px; cursor: pointer; color: var(--ink); }
  nav button.topic { padding-left: 32px; font-size: 14px; }
  nav button[aria-current="true"] { background: var(--pick); font-weight: 600; }
  main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
  header { background: var(--head); color: #fff; padding: 10px 16px; font-weight: 600; }
  #log { flex: 1; overflow-y: auto; padding: 12px 16px; display: flex;
         flex-direction: column; gap: 8px; }
  .msg { max-width: 85%; padding: 7px 10px; border-radius: 12px; white-space: pre-wrap;
         overflow-wrap: anywhere; box-shadow: 0 1px 1px rgba(0,0,0,.12); }
  .msg.me { align-self: flex-end; background: var(--me); }
  .msg.bot { align-self: flex-start; background: var(--bot); }
  .msg.service { align-self: center; background: rgba(0,0,0,.18); color: #fff;
                 font-size: 13px; box-shadow: none; }
  .quote { border-left: 3px solid var(--head); padding-left: 6px; margin-bottom: 4px;
           color: var(--soft); font-size: 13px; max-height: 3.2em; overflow: hidden; }
  .keys { display: flex; flex-direction: column; gap: 4px; margin-top: 6px; }
  .keys div { display: flex; gap: 4px; }
  .keys button { flex: 1; border: 1px solid var(--line); background: var(--key);
                 border-radius: 8px; padding: 7px; font: inherit; color: #2a6496;
                 cursor: pointer; }
  .reactions { display: inline-block; margin-top: 4px; padding: 1px 7px; border-radius: 10px;
               background: rgba(81,125,162,.15); font-size: 14px; }
  .actions { font-size: 12px; margin-top: 2px; }
  .actions button { border: 0; background: none; padding: 0; font: inherit;
                    color: var(--soft); cursor: pointer; }
  #toast { position: fixed; top: 52px; left: 50%; transform: translateX(-50%);
           background: rgba(0,0,0,.75); color: #fff; padding: 6px 12px; border-radius: 8px;
           display: none; }
  #replying { padding: 4px 16px; background: #eef3f7; color: var(--soft); font-size: 13px;
              display: none; }
  #menu { display: none; background: #fff; border-top: 1px solid var(--line);
          max-height: 260px; overflow-y: auto; }
  #menu button { display: flex; gap: 12px; width: 100%; border: 0; background: none;
                 font: inherit; text-align: left; padding: 8px 16px; cursor: pointer; }
  #menu button:hover { background: var(--pick); }
  #menu b { color: #2a6496; min-width: 80px; }
  #menu span { color: var(--soft); }
  form { display: flex; gap: 8px; padding: 10px 16px; background: #fff; }
  #box { flex: 1; font: inherit; padding: 8px; border: 1px solid var(--line);
         border-radius: 8px; min-width: 0; }
  form button { font: inherit; padding: 8px 14px; border: 0; border-radius: 8px;
                background: var(--head); color: #fff; cursor: pointer; }
  form #menuBtn { background: var(--key); color: #2a6496; border: 1px solid var(--line); }
</style></head>
<body>
<nav aria-label="Chats"></nav>
<main>
<header id="title">Rouh</header>
<div id="log" aria-label="Messages"></div>
<div id="toast" role="status"></div>
<div id="replying"></div>
<div id="menu" role="menu" aria-label="Commands"></div>
<form id="send"><button type="button" id="menuBtn" aria-label="Menu"
 aria-expanded="false">/</button>
<input id="box" aria-label="Message" autocomplete="off" placeholder="Message">
<button type="submit">Send</button></form>
</main>
<script>
const person = Number(new URLSearchParams(location.search).get("chat") || 4242);
let here = {chat: person, thread: 0, title: "Rouh"};
let replyTo = 0, drawn = "", lastToast = 0, listed = "";
async function post(path, body) {
  await fetch(path, {method: "POST", headers: {"content-type": "application/json"},
                     body: JSON.stringify(body)});
  setTimeout(draw, 150);
}
function go(chat, thread, title) {
  here = {chat, thread: thread || 0, title};
  drawn = ""; replyTo = 0;
  document.getElementById("replying").style.display = "none";
  closeMenu(); draw();
}
function inHere(m) {
  if (String(m.chat.id) !== String(here.chat)) return false;
  if (m.chat.type === "private") return true;
  const t = m.is_topic_message ? (m.message_thread_id || 0) : 0;
  return t === here.thread;
}
async function drawChats() {
  const got = await (await fetch("/_chats?person=" + person)).json();
  const key = JSON.stringify(got.chats) + JSON.stringify(here);
  if (key === listed) return;
  listed = key;
  const nav = document.querySelector("nav");
  nav.textContent = "";
  for (const c of got.chats) {
    if (c.is_forum) {
      const h = document.createElement("h2"); h.textContent = c.title; nav.appendChild(h);
    }
    const b = document.createElement("button"); b.type = "button";
    b.textContent = c.type === "private" ? "Rouh" : (c.is_forum ? "General" : c.title);
    b.setAttribute("aria-current", String(String(here.chat) === String(c.id) && !here.thread));
    b.onclick = () => go(c.id, 0, c.type === "private" ? "Rouh"
                         : (c.is_forum ? c.title + " · General" : c.title));
    nav.appendChild(b);
    for (const t of c.topics) {
      const tb = document.createElement("button"); tb.type = "button"; tb.className = "topic";
      tb.textContent = "# " + t.name;
      tb.setAttribute("aria-current", String(String(here.chat) === String(c.id)
                                             && here.thread === t.thread));
      tb.onclick = () => go(c.id, t.thread, c.title + " · " + t.name);
      nav.appendChild(tb);
    }
  }
}
async function draw() {
  drawChats();
  document.getElementById("title").textContent = here.title;
  const got = await (await fetch("/_chat?chat=" + here.chat)).json();
  const mine = got.messages.filter(inHere);
  const key = JSON.stringify(mine);
  if (key !== drawn) {
    drawn = key;
    const log = document.getElementById("log");
    log.textContent = "";
    for (const m of mine) {
      const el = document.createElement("div");
      el.dataset.id = m.message_id;
      if (m.forum_topic_created || m.group_chat_created) {
        el.className = "msg service";
        el.textContent = m.group_chat_created ? "Alex created the group “" + m.chat.title + "”"
                         : "Topic created: " + m.forum_topic_created.name;
        log.appendChild(el);
        continue;
      }
      el.className = "msg " + (m.from && m.from.is_bot ? "bot" : "me");
      const r = m.reply_to_message;
      if (r && !r.forum_topic_created) {
        const q = document.createElement("div");
        q.className = "quote";
        q.textContent = r.text || "";
        el.appendChild(q);
      }
      el.appendChild(document.createTextNode(m.text || m.caption || ""));
      if ((m.reactions || []).length) {
        const re = document.createElement("div");
        re.className = "reactions";
        re.setAttribute("aria-label", "Reactions: " + m.reactions.join(" "));
        // Named beside it too, for a screen with no emoji font (a headless browser's).
        const NAMES = {"👀": "eyes", "👍": "thumbs up"};
        re.textContent = m.reactions.map(e => e + (NAMES[e] ? " " + NAMES[e] : "")).join("  ");
        el.appendChild(re);
      }
      const rows = (m.reply_markup || {}).inline_keyboard || [];
      if (rows.length) {
        const keys = document.createElement("div");
        keys.className = "keys";
        for (const row of rows) {
          const line = document.createElement("div");
          for (const b of row) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = b.text;
            btn.onclick = () => post("/_press", {chat_id: here.chat, message_id: m.message_id,
                                                 data: b.callback_data});
            line.appendChild(btn);
          }
          keys.appendChild(line);
        }
        el.appendChild(keys);
      }
      if (m.from && m.from.is_bot) {
        const acts = document.createElement("div");
        acts.className = "actions";
        const a = document.createElement("button");
        a.type = "button";
        a.textContent = "Reply";
        a.setAttribute("aria-label", "Reply to: " + (m.text || "").slice(0, 60));
        a.onclick = () => { replyTo = m.message_id; const rp = document.getElementById("replying");
          rp.textContent = "Replying to: " + (m.text || "").slice(0, 80);
          rp.style.display = "block"; document.getElementById("box").focus(); };
        acts.appendChild(a);
        el.appendChild(acts);
      }
      log.appendChild(el);
    }
    log.scrollTop = log.scrollHeight;
  }
  const t = got.toasts[got.toasts.length - 1];
  if (t && t.at > lastToast) {
    lastToast = t.at;
    const el = document.getElementById("toast");
    el.textContent = t.text; el.style.display = "block";
    setTimeout(() => { el.style.display = "none"; }, 2500);
  }
}
function send(text) {
  const body = {chat_id: here.chat, text};
  if (here.thread) body.thread = here.thread;
  if (replyTo) body.reply_to_message_id = replyTo;
  replyTo = 0;
  document.getElementById("replying").style.display = "none";
  post("/_send", body);
}
function closeMenu() {
  document.getElementById("menu").style.display = "none";
  document.getElementById("menuBtn").setAttribute("aria-expanded", "false");
}
document.getElementById("menuBtn").onclick = async () => {
  const menu = document.getElementById("menu");
  if (menu.style.display === "block") { closeMenu(); return; }
  const got = await (await fetch("/_menu?chat=" + here.chat + "&person=" + person)).json();
  menu.textContent = "";
  if (!got.commands.length) {
    const none = document.createElement("div");
    none.style.padding = "8px 16px"; none.style.color = "#6b7b88";
    none.textContent = "This bot has no commands here.";
    menu.appendChild(none);
  }
  for (const c of got.commands) {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "menuitem");
    const k = document.createElement("b"); k.textContent = "/" + c.command;
    const d = document.createElement("span"); d.textContent = c.description;
    b.appendChild(k); b.appendChild(d);
    // Pressing a command in the menu sends it, as the apps do.
    b.onclick = () => { closeMenu(); send("/" + c.command); };
    menu.appendChild(b);
  }
  menu.style.display = "block";
  document.getElementById("menuBtn").setAttribute("aria-expanded", "true");
};
document.getElementById("send").onsubmit = (e) => {
  e.preventDefault();
  const box = document.getElementById("box");
  if (!box.value.trim()) return;
  const text = box.value; box.value = "";
  send(text);
};
draw(); setInterval(draw, 700);
</script>
</body></html>
"""


class _quietly:
    """A wait that ran out is not an error here."""

    def __enter__(self):
        return self

    def __exit__(self, kind, exc, tb):
        return kind is asyncio.TimeoutError or kind is TimeoutError


def messages(record_dir: str) -> list[dict]:
    """Every request this server was given, oldest first. For a test to read."""
    out = []
    if not os.path.isdir(record_dir):
        return out
    for name in sorted(os.listdir(record_dir)):
        with open(os.path.join(record_dir, name), encoding="utf-8") as fh:
            one = json.load(fh)
        one["kind"] = name.rsplit("-", 1)[-1].removesuffix(".json")
        out.append(one)
    return out


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--record", default=None)
    # Telegram's numbering never starts again. A stand-in started again in
    # the middle of a test, as the network coming back, carries on from here.
    ap.add_argument("--first-update", type=int, default=FIRST_UPDATE)
    args = ap.parse_args()
    if args.record:
        os.makedirs(args.record, exist_ok=True)
    uvicorn.run(build_app(args.record, args.first_update), host="127.0.0.1", port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
