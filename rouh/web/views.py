"""Every address Rouh answers that is not the sign-in, the Gene therapy board or
Google: the page itself, its files, and the JSON it asks for.

Each view does three things and no more: it reads what the request says, it
asks the part of Rouh that knows (`rouh/runtime.py` holds the process's
stores and its live state), and it answers the way the page expects. What each
answer means - why the canvas is paged, why a workspace page is sandboxed, why
a public page's token is a secret - is said beside the view, as it was said
beside the FastAPI route it replaced on 23 September 2026.

Nothing here checks who is signed in: the gate (`gate.py`) has already turned
away anybody who is not, before a view runs. Where a view needs to know *who*
it is - their organisation, to scope a query - it asks `common.who`.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import mimetypes
import os
import re
from urllib.parse import quote

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from django.shortcuts import render
from django.utils.http import content_disposition_header
from django.views.decorators.csrf import csrf_exempt

from rouh import (addressing, artifacts, askai, attachments, comments, conversations, dbwork,
                  filelinks,
                  gaps, genes, machine_load, modeldefaults, moving, objectindex, outbox, pagehistory,
                  page_listen, pageplaces, pages, picture, picturelinks, sharing, starting, steps,
                  stopping, switches,
                  turnrecords,
                  uploads, usage, waiting)
from rouh import restarts
from rouh.config import config, effort_for, luna_ready, model_name
from rouh.version import BUILD, REVISION, VERSION, get_version
from rouh.web.assets import ASSETS

from .common import (answer, body_of, file_response, from_this_machine, methods, only, refuse,
                     who)
from .offline import owner_of as offline_owner

log = logging.getLogger("rouh.web")


def _rt():
    from rouh import runtime

    return runtime


NO_STORE = {"Cache-Control": "no-store"}


# --- the health check --------------------------------------------------------------


@only("GET")
async def healthz(request: HttpRequest):
    """What systemd, the deploy and the rollback read before anybody signs in.

    ``ok`` is only true when the database answers and has every migration in
    it: a deploy that came up on a schema it does not match is not healthy, and
    saying so here is what makes the deploy roll it back rather than leave it.
    """
    rt = _rt()
    database = await asyncio.to_thread(_database_state)
    people = database.get("accounts", 0)
    return answer({
        "ok": database["ok"],
        "database": database["said"],
        "framework": "django",
        # How much of PostgreSQL this process is holding, and whether anything
        # is waiting for a connection: only counts (`rouh/dbwork.py`).
        "database_pool": dbwork.pool_state(),
        # The model every chat but General answers with, for the organisation
        # a turn with nobody speaking would use (`rouh/modeldefaults.py`).
        "model": modeldefaults.use_model("chats", cfg=config),
        # Whether OpenAI's models can be asked: there is an OpenAI key to ask
        # them with. Never the key, only that there is one.
        "luna_ready": luna_ready(config),
        "voice_ready": rt.voice.ready,
        "ears_ready": rt.ears.ready,
        "delegation": rt.crew is not None,
        # How many accounts there are, never who they are. A deploy that
        # somehow landed with none would answer ok and let nobody in, and this
        # is the one line that says so.
        "accounts": people,
        "tools": rt.tools.names(),
        "missing_config": config.missing(),
        # Where the key that encrypts stored credentials came from: the
        # environment, or a file beside the data made on first use.
        "encryption_key": rt.encryption_key_source,
        "version": VERSION,
        "revision": REVISION,
        "build": BUILD,
        # When this process started and whether the one before went on purpose,
        # which a page with no socket asks here to tell a deploy from its own
        # bad connection (`rouh/restarts.py`, `probeDrop` in app/socket.js).
        **restarts.said(),
        # The build of the page it serves, as the handshake says it (`assets`).
        "assets": ASSETS,
        # The same commit said in full: date, branch, and whether the tree it
        # was built from had been edited.
        "git": get_version(),
    })


def _database_state() -> dict:
    """Whether PostgreSQL answers, and whether the schema is the code's."""
    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    from rouh import accounts

    try:
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if pending:
            return {"ok": False, "said": f"{len(pending)} migration(s) not applied"}
        return {"ok": True, "said": "postgresql", "accounts": accounts.count()}
    except Exception as exc:                                 # the database is not there
        log.warning("the health check could not read the database: %s", type(exc).__name__)
        return {"ok": False, "said": f"unreachable ({type(exc).__name__})"}


# --- how busy the machine is, and what it has cost -----------------------------------


@only("GET")
async def machine_load_now(request: HttpRequest):
    """How busy this machine is right now: CPU, processes, memory, and what
    our own two services are holding of it.

    The orb polls this every few seconds while it is on the screen. Every
    number comes out of `machine_load.snapshot`; a reader that cannot answer
    says so there and leaves the others alone. The reading blocks for a moment
    on a cold start, which is why it goes to a thread.
    """
    snapshot = await asyncio.to_thread(machine_load.snapshot)
    # What it has cost goes out with how busy it is, on the same poll: "how
    # hard is this box working" and "what is it spending" are the same
    # question asked twice (`rouh/costs.py`).
    with contextlib.suppress(Exception):
        snapshot["spend"] = await asyncio.to_thread(_rt().spend_now)
    return answer(snapshot)


@only("GET")
async def spend_record(request: HttpRequest):
    """What Rouh has spent, for the status page at /gaps."""
    try:
        return answer(await asyncio.to_thread(_rt().spend_now, request.GET.get("chat", "")),
                      headers=NO_STORE)
    except Exception as exc:
        log.exception("the spend could not be read")
        return refuse(f"the spend could not be read: {exc}", 500)


@only("GET")
async def usage_by_day(request: HttpRequest):
    """What the models cost, day by day and model by model, out of the log.

    The open orb's usage screen asks for it (`rouh/usage.py`). `days` is how
    far back, thirty unless it says otherwise.
    """
    identity = who(request)
    if identity is None:
        return refuse("sign in first", 401)
    try:
        days = int(request.GET.get("days") or usage.DAYS)
    except ValueError:
        return refuse("days is a number of days", 400)
    try:
        return answer(await asyncio.to_thread(usage.daily, identity, days), headers=NO_STORE)
    except Exception as exc:
        log.exception("the usage could not be read")
        return refuse(f"the usage could not be read: {exc}", 500)


@only("GET")
async def turns_export(request: HttpRequest):
    """Every turn of the person's from one day to another, with every time and result its timeline showed,
    for weighing speed against quality (`rouh/turnrecords.py`). `from` and `to` are days, YYYY-MM-DD, in the
    person's zone, both in, today when left out; `chat` narrows it to one chat; `format` is json (whole,
    each turn with its requests from the log) or csv (a row per turn, the numbers worth sorting by); `turn` is
    one turn's record alone, whatever its day."""
    identity = who(request)
    if identity is None:
        return refuse("sign in first", 401)
    since = request.GET.get("from") or request.GET.get("day") or None
    until = request.GET.get("to") or since
    fmt = (request.GET.get("format") or "json").lower()
    if fmt not in ("json", "csv"):
        return refuse("format is json or csv", 400)
    try:
        rows = await asyncio.to_thread(turnrecords.export, identity, since, until,
                                       chat=str(request.GET.get("chat") or "")[:200],
                                       turn=str(request.GET.get("turn") or "")[:200])
    except ValueError:
        return refuse("from and to are days, YYYY-MM-DD", 400)
    turn = str(request.GET.get("turn") or "")[:200]
    one = turn.split("@", 1)[0][:40]
    name = ((f"rouh-{one}" if one.startswith("turn-") else f"rouh-turn-{one}") if turn else
            f"rouh-turns-{since or 'today'}" + (f"-to-{until}" if until and until != since else ""))
    if fmt == "csv":
        return HttpResponse(turnrecords.as_csv(rows), content_type="text/csv; charset=utf-8",
                            headers={**NO_STORE, "Content-Disposition": content_disposition_header(
                                False, name + ".csv")})
    return HttpResponse(turnrecords.as_json(rows), content_type="application/json; charset=utf-8",
                        headers={**NO_STORE, "Content-Disposition": content_disposition_header(False, name + ".json")})


@only("POST")
async def stop_the_turn(request: HttpRequest):
    """Stop the turn Rouh is in the middle of. The Stop control, and Escape.

    All it does is set a flag (`rouh/stopping.py`); the loop reads it at the
    next point it can be left cleanly and abandons the turn there. Setting a
    flag takes no locks and waits for nothing, which is why this answers in a
    millisecond even while the model is still streaming into the page. What it
    does not stop is anything Rouh has already handed over: a background job
    or a run of the one program is the person's work, not Rouh's turn.

    It answers the same way when there was nothing running, with an empty
    list. A stop pressed a moment too late is not an error.

    `chat` is the conversation on the screen of the tab that pressed it, which
    is that tab's own: another tab may be in another chat entirely. Left out,
    it is the chat opened last.
    """
    rt = _rt()
    asked = str(body_of(request).get("chat") or "")[:200]
    session_id = asked if rt.chat_is_there(asked) else rt.memory.ensure_session()
    stopped = stopping.stops.stop(session_id)
    for tab in list(rt.Hub.sockets):
        if tab.session_id != session_id:
            continue
        # Every screen in this conversation, not only the one that pressed it:
        # the tab doing the talking may not be the one in their hand.
        with contextlib.suppress(Exception):
            await tab.emit({"type": "stopped", "turns": stopped, "chat": session_id})
    return answer({"ok": True, "stopped": stopped})


# --- the agent loop's gaps -------------------------------------------------------------


@only("GET")
async def gaps_page(request: HttpRequest):
    """The status page for the gaps between this loop and the Agent SDK.

    No-store because the whole point of the page is that it says what is true
    right now.
    """
    response = await asyncio.to_thread(render, request, "rouh/gaps.html")
    response["Cache-Control"] = "no-store, must-revalidate"
    return response


@only("GET")
async def gaps_record(request: HttpRequest):
    """The record itself, read off disk on every request, so a row that moves
    shows without Rouh being restarted."""
    try:
        record = await asyncio.to_thread(gaps.load)
    except (OSError, ValueError) as exc:
        log.exception("the gaps record could not be read")
        return refuse(f"the record could not be read: {exc}", 500)
    record["summary"] = gaps.summary()
    record["statuses"] = list(gaps.STATUSES)
    return answer(record, headers=NO_STORE)


# --- the canvas ---------------------------------------------------------------------------


@only("GET")
async def canvas_cards(request: HttpRequest):
    """A page of one chat's canvas, newest first.

    `before` is the number of the oldest card the page already has; leaving it
    out asks for the newest. `more` says whether there is anything older still.
    `chat` is which conversation's canvas is wanted, and leaving it out means
    the active one; the page says which, so a switch that crosses with a
    request in flight cannot answer with the other chat's cards.
    """
    rt = _rt()
    try:
        before = request.GET.get("before")
        before = int(before) if before not in (None, "") else None
        limit = int(request.GET.get("limit") or rt.CANVAS_PAGE)
    except ValueError:
        return refuse("before and limit are numbers", 422)
    # The ceiling, so one request cannot ask for the whole history and undo
    # the point of paging it. One more than asked for answers "is there
    # anything older" in the same query.
    want = max(1, min(limit, rt.CANVAS_PAGE_MAX))
    wanted_chat = (request.GET.get("chat") or "").strip() or rt.memory.active_chat()
    if artifacts.enabled():
        cards = await asyncio.to_thread(artifacts.history, wanted_chat,
                                        rt.memory.task_of(wanted_chat), before, want + 1)
        page = await asyncio.to_thread(artifacts.mark_drawn_here, cards[:want], wanted_chat)
        return answer({"cards": page, "more": len(cards) > want})
    rows = await asyncio.to_thread(rt.memory.card_history, before, want + 1, wanted_chat)
    more = len(rows) > want
    cards = []
    for row in rows[:want]:
        spec = row["spec"] if isinstance(row["spec"], dict) else {}
        cards.append(dict(spec, card_id=row["id"], at=row["ts"],
                          after_message_id=row.get("after_message_id"), here=True,
                          title=spec.get("title") or row["title"],
                          description=spec.get("description") or row["description"]))
    return answer({"cards": cards, "more": more})


@only("GET")
async def transcript_page(request: HttpRequest):
    """A page of one chat's conversation older than what the page holds, as the person scrolls up.

    `before` is the mark the page was handed with what it holds (`older` on `ready`,
    `chat_switched` and the page before this), and the answer carries the mark for the page
    before this one, "" at the beginning of the chat (`Memory.transcript_page`).
    """
    rt = _rt()
    chat = (request.GET.get("chat") or "").strip()
    if not chat:
        return refuse("no chat was asked for", 400)
    try:
        exchange, row = (int(x) for x in (request.GET.get("before") or "").split(".", 1))
        limit = max(1, min(int(request.GET.get("limit") or rt.TRANSCRIPT_PAGE), 200))
    except ValueError:
        return refuse("before is two numbers with a dot between them, and limit a number", 422)
    rows, older = await asyncio.to_thread(rt.memory.transcript_page, chat, limit, (exchange, row))
    return answer({"chat": chat, "transcript": rows, "older": older}, headers=NO_STORE)


@only("GET")
async def canvas_drawn(request: HttpRequest):
    """Every card drawn in one chat, oldest first, for its Cards on the canvas.

    Cards on the chat's three dots (`artifacts.drawn_in`). Which chat is said
    by the page, and the task it is in is read here, never taken from it.
    """
    wanted = (request.GET.get("chat") or "").strip()
    if not wanted:
        return refuse("no chat was asked for", 400)
    if not artifacts.enabled():
        return refuse("The object store is not open on this machine, so cards cannot be "
                      "read back.", 404)
    memory = _rt().memory
    got = await asyncio.to_thread(
        lambda: artifacts.drawn_in(wanted, memory.task_of(wanted)))
    return answer(got, headers=NO_STORE)


@only("GET")
async def canvas_card(request: HttpRequest):
    """One artifact, whole, for the viewer that opens when it is clicked."""
    wanted = (request.GET.get("id") or "").strip()
    if not wanted:
        return refuse("no card was asked for", 400)
    if not artifacts.enabled():
        return refuse("The object store is not open on this machine, so cards cannot be "
                      "read back.", 404)
    got = await asyncio.to_thread(artifacts.about, wanted, root=_workspace_root())
    if got is None:
        return refuse("That card is not here any more.", 404)
    return answer(got, headers=NO_STORE)


@only("GET")
async def job_page(request: HttpRequest, job_id: str):
    """One of Rouh's own background jobs, for its page on the canvas.

    What it was asked, how it ended, what it died of when it died, what it
    printed, and whether it can be restarted (`starting.about`). A run of the
    one program is not answered here: it opens on the program's own socket.
    """
    got = await starting.about(job_id, crew=_rt().crew)
    if got is None:
        return refuse("That job is not on record here.", 404)
    return answer(got, headers=NO_STORE)


@only("POST")
async def job_restart(request: HttpRequest, job_id: str):
    """Start a job that died again, from the Restart button on its card or page.

    The same brief, the same kind and the same files hint, as a fresh job with
    a new id (`starting.restart`). Pressed twice, it starts one job: the second
    press is answered with the first one's id and `already`.
    """
    me = await sync_to_async(who)(request)
    try:
        got = await _rt().restart_job(job_id, org_id=me.org_id if me is not None else "")
    except starting.CannotStart as exc:
        return refuse(str(exc), 409)
    except Exception as exc:                                 # pragma: no cover
        log.exception("job %s could not be restarted", job_id)
        return refuse(f"It could not be restarted: {exc}", 500)
    return answer({"ok": True, **got})


@only("GET")
async def canvas_image(request: HttpRequest):
    """A picture on a card, fetched by Rouh because the browser could not.

    What may be fetched, and what happens to the bytes on the way back, is
    picture.py. Behind the sign-in: nobody who is not signed in can use Rouh
    as a way to fetch anything.
    """
    try:
        body, media = await picture.fetch(request.GET.get("src", ""))
    except picture.Refused as exc:
        return refuse(str(exc), 400)
    except picture.Unreadable as exc:
        return refuse(str(exc), 502)
    response = HttpResponse(body, content_type=media)
    for name, value in dict(picture.ANSWER_HEADERS).items():
        response[name] = value
    return response


# --- what the canvas's breadcrumb knows ---------------------------------------------------
#
# The tasks are drawn in the canvas by `objectindex.py`, in a frame. These are
# what Rouh's own chrome around that frame needs and the frame cannot tell it.
# They answer JSON to Rouh's own signed-in page, not a file to a sandboxed
# frame, which is why they may read a step's markdown where `/workspace/` may
# not (see `steps.py`). Everything is read off the workspace on every request.


def _workspace_root() -> str:
    return config.assistant_repo or ""


def _no_workspace(status: int = 404, **more):
    return answer({"error": "no workspace on this machine", **more}, status=status)


@only("GET")
async def workspace_index(request: HttpRequest):
    """Every task in the workspace, with its state, its line and when it moved."""
    root = _workspace_root()
    if not root or not os.path.isdir(root):
        return answer({"tasks": [], "why": "no workspace on this machine"})
    return answer({"tasks": await asyncio.to_thread(steps.index_rows, root)})


@only("GET")
async def workspace_task(request: HttpRequest):
    """One task and its steps: the step level of the breadcrumb, and its siblings."""
    root = _workspace_root()
    if not root or not os.path.isdir(root):
        return _no_workspace()
    try:
        return answer(await asyncio.to_thread(steps.task_detail, root,
                                              request.GET.get("rel", "")))
    except steps.Refused as exc:
        return refuse(str(exc), 400)


@only("GET")
async def workspace_destinations(request: HttpRequest):
    """Every place the task at one folder could be moved to, for the picker
    its page's Move opens (`rouh/moving.py`). Read only."""
    root = _workspace_root()
    if not root or not os.path.isdir(root):
        return _no_workspace()

    def listed():
        store = objectindex._ready(root)
        return moving.destinations(root, store, request.GET.get("folder", ""))

    try:
        got = await asyncio.to_thread(listed)
    except pages.Refused as exc:
        return refuse(str(exc), 400)
    return answer(got, status=200 if got.get("ok") else 404,
                  headers={"Cache-Control": "no-store"})


@only("POST")
async def workspace_filing(request: HttpRequest):
    """One change the task browser made: a task filed under another project, or
    a project renamed, added, moved between the columns or deleted.

    The only address under which anything a framed page asks for writes, and
    the shape is what keeps that safe: an action name and object ids - never a
    path, never a query - and `objectindex.change` decides what each may do.
    The answer always carries the index as it is afterwards, refusal or not.
    """
    root = _workspace_root()
    if not root or not os.path.isdir(root):
        return answer({"ok": False, "error": "no workspace on this machine"}, status=404)
    body = body_of(request)
    if not body:
        return answer({"ok": False, "error": "That was not a change."}, status=400)
    try:
        names = waiting.names_of(getattr(request, "user", None))
        person = await sync_to_async(who)(request)
        done = await asyncio.to_thread(objectindex.change, root, body, names, person)
    except pages.Refused as exc:
        return answer({"ok": False, "error": str(exc)}, status=400)
    if done.get("ok") and str(body.get("action") or "") in MOVES_FOLDERS:
        await _moved_folders()
    return answer(done)


#: The task browser's changes that move a folder in the workspace: a task
#: filed under another project, a project moved to the other column, and a
#: project deleted with whatever it held. And two that move none but change
#: the same lists: a task archived or brought back, which leaves the rail's
#: Tasks or comes back to it (`rouh/archiving.py`), and a task or a step
#: pinned or unpinned, which the rail's Pinned section and the Control Room
#: both draw (`rouh/pinning.py`). And a task said to be his own or somebody
#: else's, which brings it into his lists or takes it out (`rouh/task_origin.py`).
#: And a task renamed from the three dots on its line, whose name the rail and
#: its chats carry. And a subtask dragged onto another task, promoted to a task or
#: moved to a new task from its line (`rouh/moving.py`).
MOVES_FOLDERS = ("move", "side", "delete", "archive", "relocate", "pin", "mine", "rename_task",
                 "move_step")


async def _moved_folders() -> None:
    """Tell every tab that tasks have moved, the way a move over the socket does.

    Every chat under a task carries that task's folder and its project, and the
    rail's Tasks list carries both of those too, so a move the task browser
    made is a change to all three lists. The socket's own moves have always
    said so (`attach`, `NewTasks`); this route said nothing, so the rest of the
    page went on reading the folder a task had left.
    """
    rt = _rt()
    for tell in (rt.announce_objects, rt._announce_workspace, rt.announce_chats):
        try:
            await tell()
        except Exception:  # noqa: BLE001 - the move is made; telling is a courtesy
            log.exception("the move was made, and the tabs could not be told")


async def _uploaded(request: HttpRequest):
    """The one file a form carried, parsed off the event loop."""
    files = await asyncio.to_thread(lambda: request.FILES)
    return files.get("file")


@only("POST")
async def workspace_file(request: HttpRequest):
    """One file attached to one project, from the Add files button on its page,
    or uploaded to one task, from Upload on the task's.

    A project's page names a **project id** and nothing else; where the bytes
    land is worked out from that id (`objectindex.files_key`). A task's is named
    by ``folder``, the task Rouh framed, which Rouh read off its own canvas and
    never off the page (`taskUpload` in app.js), and its files are kept under
    the task's id (`objectindex.task_files_key`). What may be attached and how
    big it may be are `attachments.py`'s answer and not a second set of rules.
    """
    root = _workspace_root()
    if not root or not os.path.isdir(root):
        return answer({"ok": False, "error": "no workspace on this machine"}, status=404)
    upload = await _uploaded(request)
    if upload is None:
        return answer({"ok": False, "error": "No file was sent."}, status=400)
    limit = attachments.MAX_BYTES
    if upload.size > limit:
        return answer({"ok": False,
                       "error": f"{attachments.safe_name(upload.name or 'That file')} is "
                                f"larger than {attachments.human_size(limit)}, so it was not "
                                "attached."}, status=413)
    folder = str(request.POST.get("folder") or "")
    doc = str(request.POST.get("doc") or "")
    if folder and doc:
        return await _into_folder(root, folder, doc, upload)
    body = await asyncio.to_thread(upload.read)
    icon = str(request.POST.get("icon") or "")
    try:
        if icon:
            # A picture for a task's icon, from the icon picker (`rouh/taskicons.py`), named
            # by the task's id as every change the task browser makes names it.
            done = await asyncio.to_thread(objectindex.icon_upload, icon, bytes(body))
        elif folder:
            done = await asyncio.to_thread(
                objectindex.attach_to_task, root, folder,
                upload.name or "", bytes(body), upload.content_type or "")
        else:
            done = await asyncio.to_thread(
                objectindex.attach_to_project, root, str(request.POST.get("id") or ""),
                upload.name or "", bytes(body), upload.content_type or "")
    except pages.Refused as exc:
        return answer({"ok": False, "error": str(exc)}, status=400)
    return answer(done, status=200 if done.get("ok") else 400)


async def _into_folder(root: str, folder: str, doc: str, upload):
    """One file uploaded into a working folder of a task, from that folder's three dots
    (`rouh/folder_acts.py`): ``folder`` the task Rouh framed, ``doc`` the folder inside it."""
    from rouh import folder_acts

    if upload.size > folder_acts.MOST_BYTES:
        return answer({"ok": False,
                       "error": f"{attachments.safe_name(upload.name or 'That file')} is larger "
                                f"than {attachments.human_size(folder_acts.MOST_BYTES)}, and a "
                                "file put into a task's folder can be at most that."}, status=413)
    body = await asyncio.to_thread(upload.read)
    try:
        done = await asyncio.to_thread(folder_acts.upload, root, folder, doc,
                                       upload.name or "", bytes(body))
    except folder_acts.Refused as exc:
        return answer({"ok": False, "error": str(exc)}, status=400)
    except OSError:
        log.exception("a file could not be put into %s/%s", folder, doc)
        return answer({"ok": False, "error": "It could not be saved there."}, status=500)
    return answer(done)


@only("POST")
async def workspace_folder(request: HttpRequest):
    """A press in the three dots of a working folder of a task, or of a line in its listing
    (`rouh/folder_acts.py`): ``{folder, doc, act, name}``, where ``folder`` is the task Rouh
    framed, read off its own canvas (`taskFolderAct` in cards.js), ``doc`` the folder or the file
    inside it, and ``act`` new_folder, rename or delete."""
    from rouh import folder_acts

    root = _workspace_root()
    if not root or not os.path.isdir(root):
        return answer({"ok": False, "error": "no workspace on this machine"}, status=404)
    sent = body_of(request)
    try:
        done = await asyncio.to_thread(
            folder_acts.act, root, str(sent.get("folder") or ""), str(sent.get("doc") or ""),
            str(sent.get("act") or ""), str(sent.get("name") or ""))
    except folder_acts.Refused as exc:
        return answer({"ok": False, "error": str(exc)}, status=400)
    except OSError:
        log.exception("a working folder could not be changed: %s", sent)
        return answer({"ok": False, "error": "That could not be done to the folder."}, status=500)
    return answer(done)


@only("GET")
async def workspace_step(request: HttpRequest):
    """One step: which page to load for it, or its blocks where it has none."""
    root = _workspace_root()
    if not root or not os.path.isdir(root):
        return _no_workspace()
    try:
        read = await asyncio.to_thread(steps.read_step, root, request.GET.get("rel", ""))
    except steps.Refused as exc:
        return refuse(str(exc), 400)
    # A step folder that was only ever a folder becomes the artifact row it
    # always was, the first time anybody opens it (`artifacts.register_step`).
    if artifacts.enabled():
        await asyncio.to_thread(artifacts.register_step, root, read["rel"],
                                task_rel=read.get("task") or "",
                                title=read.get("title") or "")
    return answer(read)


# --- the one program -----------------------------------------------------------------------


@only("POST")
async def deploy_the_one_program(request: HttpRequest):
    """Bring the one program on this machine up to what the repository has.

    The button under the one program's version chip. It answers straight away:
    a fetch, a restart and a health check is twenty seconds on a good day,
    which is longer than a proxy will wait. The outcome goes to every open tab
    as `one_deploy`, followed by a fresh `one_version`.
    """
    from rouh import one_deploy

    rt = _rt()
    if not rt.one.configured():
        return answer({"ok": False, "error": "This Rouh is not paired with a one program, "
                                             "so there is nothing here to deploy."}, status=409)
    try:
        work = rt.deployer.start()
    except one_deploy.AlreadyDeploying:
        return answer({"ok": False, "deploying": True, "error": one_deploy.BUSY}, status=409)
    rt.watch_one_deploy(work)
    return answer({"ok": True, "deploying": True}, status=202)


# --- the page itself --------------------------------------------------------------------


def _nickname(request: HttpRequest) -> str:
    """What the person asked to be called on their profile (`rouh/profile.py`), or ""."""
    from rouh import profile

    me = who(request)
    try:
        return profile.nickname(getattr(me, "user_id", ""), getattr(me, "org_id", "")) if me else ""
    except Exception:
        return ""


def _own_name(user, nickname: str = "") -> str:
    """What the foot of the navigation calls the person: their nickname, their
    name, or the name they sign in with."""
    full = " ".join(filter(None, [(getattr(user, "first_name", "") or "").strip(),
                                  (getattr(user, "last_name", "") or "").strip()]))
    return nickname or full or (getattr(user, "username", "") or "")


def _greeting_name(user, nickname: str = "") -> str:
    """What the welcome on an empty conversation calls the person: "Hello, Alex".

    The nickname on their profile, when they gave one, and otherwise the first
    name on the account, which is what signing in with Google fills in. An account made with `manage.py account add` has a username and
    nothing else, and for most people that is their own name in lower case,
    so a username that is one word of letters is used, with a capital. One
    that is not a name - `jdoe2`, `ops-bot` - is not guessed at, and the
    welcome says Hello and nothing after it.
    """
    if nickname:
        return nickname
    first = (getattr(user, "first_name", "") or "").strip()
    if first:
        return first
    username = (getattr(user, "username", "") or "").strip()
    if username.isalpha():
        return username[:1].upper() + username[1:]
    return ""


def _asked_of(me) -> str:
    """The model a page's Ask AI drawer is answered by, for the box beside its
    Send to name: its tier's, for this person's organisation (`rouh/modeldefaults.py`)."""
    return modeldefaults.use_model("askai", modeldefaults.org_now(me), config)


def _shared_for(request: HttpRequest) -> list[dict]:
    """The shared genes in the asking organisation's lab (`rouh/genelab.py`), as manifests,
    read once a request."""
    if not hasattr(request, "rouh_shared"):
        from rouh import genelab

        request.rouh_shared = genelab.shared_manifests(getattr(who(request), "org_id", None) or None)
    return request.rouh_shared


def _switch_for(request: HttpRequest):
    """Whether a named feature switch is on for the organisation of whoever asked."""
    org = getattr(who(request), "org_id", None) or None

    def on(name: str) -> bool:
        return switches.on(name, org)
    return on


def _chats_need_key(request: HttpRequest) -> dict | None:
    """What the welcome says when no provider has a key here, with the setup page to link to."""
    from rouh import providerkeys
    from rouh.web import claude_signin

    org = getattr(who(request), "org_id", None) or None
    if providerkeys.chats_can_answer(org, config):
        return None
    return {"said": providerkeys.where_to_add_a_key(),
            "href": claude_signin.PATH if claude_signin.enabled() else genes.BY_ID["models"]["route"]}


def _rouh_self(request: HttpRequest) -> str:
    """This Rouh's own name, or "" before its birth."""
    from rouh import birth

    try:
        row = birth.current(str(getattr(who(request), "org_id", "") or ""))
    except Exception:
        return ""
    return row.name if row else ""


def _setting_up(request: HttpRequest) -> bool:
    from rouh.web import firstrun

    try:
        return firstrun.guiding(str(getattr(who(request), "org_id", "") or ""))
    except Exception:
        return False


def _phone_address() -> str:
    """The phone address on the relay, for the chat's "Reach me from my phone" step; "" for none."""
    from rouh import relay

    try:
        return relay.hostname() if relay.enabled() and relay.chose_connected() else ""
    except Exception:
        return ""


def _page_for(request: HttpRequest) -> HttpResponse:
    """The one page, with the values the server fills in."""
    from rouh import demo_style

    user = getattr(request, "user", None)
    # What the This page side asks: Ask AI's tier, for this person's organisation.
    work = modeldefaults.use_pair("askai", modeldefaults.org_now(who(request)), config)
    nickname = _nickname(request)
    response = render(request, "rouh/index.html", {
        "VERSION": VERSION,
        "REVISION": REVISION or "local",
        # The marker itself has room for a hash and nothing else. The date is
        # what makes the hash mean something, so it goes in the tooltip.
        "BUILD_DETAIL": get_version()["human_readable"],
        # What the file picker offers. The list of formats lives in
        # attachments.py, which is also what refuses one on the way in.
        "ATTACH_ACCEPT": attachments.ACCEPT,
        # And how big one file may be, so the page refuses a bigger one before
        # it goes up rather than after (`attachments.MAX_BYTES`).
        "ATTACH_MAX": attachments.MAX_BYTES,
        # Who is signed in, for the Settings panel.
        "USERNAME": getattr(user, "username", "") or "",
        # What the foot of the navigation calls them, on the button to their profile.
        "OWN_NAME": _own_name(user, nickname),
        # Who the welcome on an empty conversation says hello to.
        "GREET_NAME": _greeting_name(user, nickname),
        # Its own name, once it is born, for the welcome to say who it is (`rouh/birth.py`).
        "ROUH_SELF": _rouh_self(request),
        # A few days after the first run the welcome's things to try are the rest of setting
        # up, which the chat takes the owner through (`firstrun.guiding`, the rule new-rouh).
        "SETTING_UP": _setting_up(request),
        "PHONE_ADDRESS": _phone_address(),
        # When the chats have no model key at all, the welcome says so and where to add one,
        # in place of "Ask me what I can do" (`providerkeys.where_to_add_a_key`).
        "CHATS_NEED_KEY": _chats_need_key(request),
        # The model the This page side asks, named beside its own box.
        "ASKAI_MODEL": work.model,
        "ASKAI_MODEL_NAME": model_name(work.model),
        # And how deeply it thinks, when it is asked a level (`config.effort_for`).
        "ASKAI_EFFORT": effort_for(work.model, work.effort),
        # The navigation's five groups and the links under each, from the gene
        # registry (`rouh/genes`, GENES.md): a gene behind a switch that is
        # off for this organisation is not there. The same, as JSON, for the page.
        "NAV_GROUPS": genes.nav_groups(_switch_for(request), _shared_for(request)),
        "GENES": genes.for_page(_switch_for(request), _shared_for(request)),
        # Whose offline copy this page keeps and opens, and nobody else's (`rouh/web/offline.py`).
        "OWNER": offline_owner(who(request)),
        # Demo mode's style and first script, the first thing in the head (`rouh/demo_style.py`).
        "DEMO_HEAD": demo_style.head(),
    })
    response["Cache-Control"] = "no-store, must-revalidate"
    # Said to the service worker too, which keeps this page for opening with no connection
    # only under this person, and clears what it kept when another person's page comes.
    response["X-Rouh-Owner"] = offline_owner(who(request))
    return response


async def index(request: HttpRequest, rest: str = ""):
    """The one page: Rouh's voice, the orb, the one program's runs with their
    terminals, and the workspace's tasks. Also at /one/, where nginx sends
    exactly /one/ here and every address under it to the program.

    The same page answers at every object's own address - `/chat/<id>`,
    `/task/<its folder>`, `/project/<its folder>`, `/run/<id>`,
    `/artifact/<id>` and the task browser's `/tasks` - because all of them are
    drawn by it. Nothing here reads the address: the browser does, and asks
    what it names over the socket (`find_object`).
    """
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD"})
    # No chat opens before the first run is over: its owner goes back to the screen they
    # reached (`rouh/web/firstrun.py`): the chats need a working key first.
    from rouh.web import firstrun

    user = await request.auser()
    if await asyncio.to_thread(firstrun.unfinished, user):
        return HttpResponseRedirect(await asyncio.to_thread(firstrun.next_path, user), status=303)
    return await asyncio.to_thread(_page_for, request)


# --- files attached in the chat --------------------------------------------------------------


async def _attach(request: HttpRequest, session_id: str):
    """One file, one at a time on purpose: the browser shows a progress bar per
    file, and one file failing its own check must not throw away the others."""
    rt = _rt()
    upload = await _uploaded(request)
    if upload is None:
        return refuse("No file was sent.", 400)
    limit = attachments.MAX_BYTES
    if upload.size > limit:
        return refuse(f"{attachments.safe_name(upload.name or 'That file')} is larger than "
                      f"{attachments.human_size(limit)} per file, so it was not attached. "
                      "Ask me to open it from a path on this machine instead.", 413)
    try:
        record = await asyncio.to_thread(rt.files.save_upload, session_id,
                                         upload.name or "", upload,
                                         upload.content_type or "")
    except attachments.AttachmentError as exc:
        return refuse(str(exc), 400)
    except OSError as exc:
        log.exception("an attachment could not be written")
        return refuse(f"It could not be saved here: {exc}", 500)
    log.info("attached %s (%s) to session %s", record["name"],
             attachments.human_size(record["size"]), record["session_id"])
    # Its words are read now, while the person is still typing, so that by the
    # time the message carrying it is sent they are there to search and for the
    # model to read (`rouh/uploads.py`). Off this request: a PDF can take a while.
    uploads.read_soon(record)
    # The path on disk is deliberately not sent back to the browser. The model
    # is told it, because a job may have to open the file; the page has no use
    # for it and every reason not to know the server's layout.
    return answer({k: v for k, v in record.items() if k != "path"})


attach = only("POST")(_attach)


@only("GET")
async def attached(request: HttpRequest, session_id: str, att_id: str):
    """The file itself, for the thumbnail in the transcript and for opening it."""
    record = _rt().files.get(session_id, att_id)
    if record is None:
        return refuse("not found", 404)
    # What may be rendered in place and what must be handed over as a download
    # is attachments.serving(): an uploaded .html or .svg run on this address
    # would be running inside the person's signed-in session.
    media, how = attachments.serving(record, download=request.GET.get("download") in ("1",))
    response = file_response(record["path"], media)
    # The name is already down to safe characters, and quoting it keeps a
    # space in it from ending the header value early.
    response["Content-Disposition"] = f'{how}; filename="{record["name"]}"'
    # Private: the person's own file, behind their sign-in.
    response["Cache-Control"] = "private, max-age=86400"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    if how == "attachment":
        # The third lock on the same door: if one of these were ever opened as
        # a page it would have no origin, no script, and nothing it could reach.
        response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response


# --- pages from the person's workspace, for a frame on the canvas ------------------------------


def _page_response(body, kind, status=200, headers=pages.HEADERS) -> HttpResponse:
    response = HttpResponse(body, status=status, content_type=kind)
    for name, value in headers.items():
        response[name] = value
    return response


#: What a workspace file has to be called for a tab opened straight onto it to
#: be taken to Rouh's own address for it rather than shown bare: what the
#: canvas shows as a page. A picture, a PDF or a sheet opens as itself, which
#: is what any link to one does.
_SHOWN_IN_ROUH = (".html", ".htm", ".md")


def _opened_in_a_tab(request: HttpRequest) -> bool:
    """Is this the browser loading the address into a tab of its own?

    A link in a page on the canvas opened with Cmd, Ctrl, Shift or the middle
    button, right-click's Open in new tab, a copied link pasted: each is a
    navigation of a whole tab, and the browser says so. Rouh's own fetch of a
    page for its frame says ``empty``, and a frame loading itself ``iframe``.
    """
    return (request.headers.get("Sec-Fetch-Dest") == "document"
            and request.headers.get("Sec-Fetch-Mode") == "navigate")


def _rouh_address(path: str, doc: str) -> str | None:
    """Rouh's own address for a workspace path, or None to serve it as it is.

    The workspace's own index is the task browser, an object's own page is
    that object, and a page or a note in a task or a project is that, at the
    address the bar says when it is open on the canvas (`addrPlace` in
    app.js). `/task/` finds a page inside a project as well as inside a task
    (`addressing.inside`), so only an object's own page needs telling apart.
    """
    if path in ("", "index.html"):
        return addressing.BROWSER
    if path.startswith(objectindex.TASK_PREFIX):
        rel = path[len(objectindex.TASK_PREFIX):].strip("/")
        if not rel:
            return None
        kind = "project" if addressing.at("project", rel) is not None else "task"
        if doc and "/" not in doc and not doc.startswith("."):
            rel = rel + "/" + doc
        return f"/{kind}/" + quote(rel, safe="/")
    if path.lower().endswith(_SHOWN_IN_ROUH):
        return "/task/" + quote(path.strip("/"), safe="/")
    return None


@only("GET")
async def workspace_page(request: HttpRequest, path: str = ""):
    """The workspace, read-only, to a signed-in session only.

    - ``/workspace/`` itself is the task browser, drawn out of the object rows
      by ``objectindex.py``.
    - ``/workspace/_task/<folder>/`` is one object's own page, and
      ``?doc=<name>`` on it is one of its notes, read (``rouh/docview.py``).
    - anything else is one file of one page: the page itself, or a picture, a
      style sheet or a script beside it (``pages.py`` says what may be served).

    ``?framed=1`` says Rouh's own page is asking, to put the page in a frame
    on the canvas; the same markup comes back with a few lines more in its
    head (``pages.frame_head``).
    """
    raw = (request.scope.get("raw_path") or b"").decode("latin-1") \
        if hasattr(request, "scope") else request.path
    framed = request.GET.get("framed") == "1"
    # A tab of its own is Rouh with the page in it, not the bare file: a link
    # in a page on the canvas is a plain link to the file, which is what lets
    # the browser open it in a new tab itself (fr_2d5208267e36). A redirect
    # keeps the place in the page (`#part`), which the browser never sends.
    if not framed and _opened_in_a_tab(request):
        there = await asyncio.to_thread(_rouh_address, path, request.GET.get("doc", ""))
        if there:
            return HttpResponseRedirect(there)
    at = pages.ROUTE + quote(path) if framed else None
    root = config.assistant_repo
    # What the person is called, which is what their tasks' notes call them
    # when they say what a task is waiting on them for.
    names = waiting.names_of(getattr(request, "user", None))
    # In demo mode the page is handed over in demo mode, approved or not (`_in_demo`), and the
    # task browser knows to draw its purple dots (`demo.browser_marks`).
    lens = getattr(request, "rouh_demo", None)
    from rouh import demo

    demo.PAGE_LENS.set(lens)
    try:
        if path in ("", "index.html"):
            # Whose "Others' tasks" switch the browser starts from (`rouh/task_origin.py`).
            person = await sync_to_async(who)(request)
            body = await asyncio.to_thread(objectindex.index_page, root, at, names, person)
            return _page_response(_in_demo(body, pages.TYPES[".html"], lens, path), pages.TYPES[".html"])
        if path.startswith(objectindex.TASK_PREFIX):
            rel = path[len(objectindex.TASK_PREFIX):]
            # Whose scheduled steps a goal's own page reads (`goals.listing`).
            person = await sync_to_async(who)(request)
            try:
                body = await asyncio.to_thread(objectindex.task_page, root, rel, raw, at,
                                               request.GET.get("doc", ""), names, person)
            except pages.Missing:
                # The task moved - often during this very request, which is
                # what files a task made a moment ago - so the page is
                # wherever its folder is now. The frame follows the redirect
                # and the breadcrumb follows where it landed (`canvasLoad`).
                now = await _moved(rel)
                if not now:
                    raise
                query = request.META.get("QUERY_STRING", "")
                return HttpResponseRedirect(pages.url_for(objectindex.TASK_PREFIX + now)
                                            + "/" + ("?" + query if query else ""))
            return _page_response(_in_demo(body, pages.TYPES[".html"], lens, path), pages.TYPES[".html"])
        drawer = b""
        mark = False
        source = None
        pictures = None
        if framed and path.lower().endswith(".html"):
            # The Ask AI drawer, for the page Rouh is about to frame. `hosted=1`
            # is the canvas saying it draws the conversation itself, beside
            # the frame, so the page keeps only the selection bar and the marks.
            # It is also the owner, who may change the page: so the page is
            # marked for pointing at (`pages.with_marks`), and `y` is where
            # they were reading when it is sent again after a change.
            hosted = request.GET.get("hosted") == "1"
            try:
                scroll = max(0, int(str(request.GET.get("y") or "0")[:9]))
            except ValueError:
                scroll = 0
            me = await sync_to_async(who)(request)
            version = str(request.GET.get("version") or "")[:48]
            if version and hosted and me is not None:
                # One line of the page's history, opened: the page as it was
                # then, read only, with the bar that says which moment it is
                # and the way back (`rouh/pagehistory.py`). No comments on it:
                # they are pinned to the page as it is now.
                try:
                    await asyncio.to_thread(askai.resolve, root, path)
                    source, viewing = await asyncio.to_thread(
                        pagehistory.version_source, root, me.org_id, path, version)
                except (askai.Unavailable, pagehistory.Refused):
                    return _page_response("Not found.", "text/plain", status=404)
                drawer = await asyncio.to_thread(
                    askai.drawer_head, root, path, hosted, _asked_of(me),
                    can_edit=False, history=True, viewing=viewing)
            else:
                # Comments pinned to the page, on the canvas, where the one
                # looking is its owner (`rouh/comments.py`). `comment` is a
                # thread to open, from the link in a letter that tagged them.
                person = comments.person_of(getattr(request, "user", None), owner=True) \
                    if hosted else None
                # The options kept over the page, which every reader may switch
                # between, drawn over it rather than written into it.
                options = await asyncio.to_thread(pagehistory.options_now, root, me.org_id,
                                                  path) if me is not None else []
                # Listen to this page, for its owner while its switch is on (`rouh/page_listen.py`).
                listening = person is not None and me is not None and \
                    await asyncio.to_thread(page_listen.on, me)
                drawer = await asyncio.to_thread(
                    askai.drawer_head, root, path, hosted, _asked_of(me), scroll=scroll,
                    comments=comments.page_config(person, _comment_asked(request), ai_pass=True)
                    if person else None,
                    options=options, history=hosted and me is not None,
                    highlights=person is not None,
                    listen=listening)
                mark = hosted or bool(options)
                if hosted and me is not None:
                    # Its owner has it open, which the Control Room asks
                    # about before it says a page has not been read.
                    await asyncio.to_thread(pageplaces.opened, path, root)
            # Its pictures by addresses of their own, fetched as they come into
            # view, rather than put into the page, which made a step of 211
            # screenshots 16.9 MB (`rouh/picturelinks.py`). Not for the copy a
            # device keeps for offline, which has to be whole.
            if me is not None and request.headers.get("X-Rouh-Later") != "1":
                pictures = picturelinks.linker(me, path)
        body, kind = await asyncio.to_thread(pages.read, root, path, raw, at, drawer, mark,
                                             source, pictures)
        body = _in_demo(body, kind, lens, path)
        if pictures is not None:
            # The service worker never keeps this over a whole copy (`sw.js`).
            response = _page_response(body, kind)
            response["X-Rouh-Pictures"] = "linked"
            return response
    except (pages.Refused, OSError):
        # A page under a task whose folder has since been renamed or moved is
        # the same page under the task's new folder, found by its number.
        now = await _moved(path) if path and not path.startswith(objectindex.TASK_PREFIX) \
            else None
        if now:
            query = request.META.get("QUERY_STRING", "")
            return HttpResponseRedirect(pages.url_for(now) + ("?" + query if query else ""))
        return _page_response("Not found.", "text/plain", status=404)
    return _page_response(body, kind)


def _in_demo(body, kind: str, lens, path: str):
    """A workspace page handed over while demo mode is on: demo mode's style and first script
    first in its head, since a page in a frame has no storage or cookie to read it from, and
    the whole page approved when its task or step was (`rouh/demo_style.py`)."""
    from rouh import demo_style

    if lens is None or not kind.startswith("text/html"):
        return body
    rel = path[len(objectindex.TASK_PREFIX):] if path.startswith(objectindex.TASK_PREFIX) else path
    rel = rel.strip("/")
    approved = bool(rel) and (lens.shows_folder(rel) or lens.shows_folder(rel.rsplit("/", 1)[0]))
    own = re.match(r"^(\d+(?:-\d+)*)\.", rel.rsplit("/", 1)[-1]) if path.startswith(objectindex.TASK_PREFIX) else None
    put = demo_style.frame_head(approved, own.group(1) if own else "").encode("utf-8")
    raw = body if isinstance(body, bytes) else str(body).encode("utf-8", "surrogateescape")
    found = re.search(rb"<head(?:\s[^>]*)?>", raw, re.I)
    if found:
        return raw[:found.end()] + put + raw[found.end():]
    found = re.search(rb"<html(?:\s[^>]*)?>", raw, re.I)
    if found:
        return raw[:found.end()] + put + raw[found.end():]
    return put + raw


@only("GET")
async def file_link(request: HttpRequest, token: str, name: str = ""):
    """A task's working file, downloaded by the link drawn beside it.

    Open at the gate, because it is pressed inside the task frame, which sends
    no sign-in; the token is the credential (`rouh/filelinks.py`). It names
    the account it was drawn for, and that account must still be a whole,
    active one of the same organisation, and the file must still pass every
    rule the reading view opens it by (`objectindex.doc_download`). The name
    on the end of the address is never read: the token says which file.
    """
    try:
        said = filelinks.read(token)
    except filelinks.Refused as exc:
        return _page_response(str(exc), "text/plain; charset=utf-8", status=404)
    me = await sync_to_async(_rt().tenancy.identity_of)(said["u"])
    if me is None or me.org_id != said["o"]:
        return _page_response("Not found.", "text/plain", status=404)
    try:
        found = await asyncio.to_thread(objectindex.doc_download, config.assistant_repo,
                                        said["r"], said["d"])
    except (pages.Refused, OSError):
        return _page_response("Not found.", "text/plain", status=404)
    kind = mimetypes.guess_type(found.name)[0] or "application/octet-stream"
    response = file_response(str(found), kind)
    for header, value in pages.HEADERS.items():
        response[header] = value
    response["Content-Disposition"] = content_disposition_header(True, found.name)
    return response


@only("GET")
async def picture_link(request: HttpRequest, token: str, rel: str):
    """One picture of a page on the canvas, fetched by the frame as it comes into view.

    Open at the gate, because the frame is sandboxed and sends no sign-in; the
    token is the credential (`rouh/picturelinks.py`). It names the account it
    was drawn for, which must still be a whole, active one of the same
    organisation, and the task it reads inside; the picture must pass every
    rule a file asked for by its own address does (`pages.check`), and be a
    picture.
    """
    raw = (request.scope.get("raw_path") or b"").decode("latin-1") \
        if hasattr(request, "scope") else request.path
    nothing = _page_response("Not found.", "text/plain", status=404, headers=picturelinks.HEADERS)
    try:
        said = picturelinks.read(token)
    except picturelinks.Refused:
        return nothing
    rel = "/".join(part for part in str(rel or "").split("/") if part)
    if not picturelinks.inside(said, rel):
        return nothing
    me = await sync_to_async(_rt().tenancy.identity_of)(said["u"])
    if me is None or me.org_id != said["o"]:
        return nothing
    try:
        found = await asyncio.to_thread(pages.check, config.assistant_repo, rel,
                                        raw.split(picturelinks.ROUTE, 1)[-1].split("/", 1)[-1])
    except (pages.Refused, OSError):
        return nothing
    suffix = os.path.splitext(found.name.lower())[1]
    if suffix not in pages.PICTURES or os.path.splitext(rel.lower())[1] not in pages.PICTURES:
        return nothing
    response = file_response(str(found), pages.TYPES[suffix])
    for header, value in picturelinks.HEADERS.items():
        response[header] = value
    return response


#: A folder named the way a task's is: its number, then its name.
_NUMBERED = re.compile(r"^\d+[.-]")


async def _moved(rel: str) -> str | None:
    """Where the task folder `rel` is inside is now, when it has moved; else None.

    A job renames a task's folder and lands it: `68.untitled-task` became
    `68.bluf-proposal` on 28 September 2026, and Rouh's rows and every open
    tab went on naming the old folder until a reload, so pressing the task drew
    an empty page and its step's page answered 404 for seven minutes. The rows
    are brought up to date with the disk first (`conversations.reconcile`), so
    the number finds the new folder (`objectindex.moved_to`), and every tab is
    told, so its lists stop naming the old one too. Only an address with a
    numbered folder in it can be a task's, so nothing else costs a reconcile.
    """
    if not any(_NUMBERED.match(part) for part in str(rel or "").split("/")):
        return None
    try:
        await asyncio.to_thread(conversations.reconcile, config.assistant_repo or "")
    except Exception:  # noqa: BLE001 - the answer is still "not found"
        log.exception("the rows could not be brought up to date for %s", rel)
    now = await asyncio.to_thread(objectindex.moved_to, rel)
    if now:
        await _moved_folders()
    return now


def _comment_asked(request: HttpRequest) -> int:
    """The comment thread an address asks to have open, or 0."""
    try:
        return max(0, int(str(request.GET.get("comment") or "0")[:12]))
    except ValueError:
        return 0


# --- Ask AI on a workspace page ---------------------------------------------------------------
#
# The drawer cannot call out from inside the frame, so Rouh's own page carries
# its questions here. `doc` is the page the question is about, decided by
# Rouh's own page from the frame it is showing, never by the page inside the
# frame, and every one of these is scoped to the person asking.


@only("GET")
async def askai_threads(request: HttpRequest):
    """This person's Ask AI threads about this page, newest first."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    doc = request.GET.get("doc", "")
    try:
        await asyncio.to_thread(askai.resolve, config.assistant_repo, doc)
    except askai.Unavailable as exc:
        return refuse(str(exc), 404)
    return answer(await asyncio.to_thread(_rt().ask_threads.threads, me, doc))


@only("GET")
async def askai_thread(request: HttpRequest, thread_id: int):
    """One thread's messages. Empty for a thread that is not this person's, or
    is not about this page: "not found" rather than somebody else's reading."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    return answer(await asyncio.to_thread(_rt().ask_threads.messages, me,
                                          request.GET.get("doc", ""), thread_id))


@only("POST")
async def askai_ask(request: HttpRequest):
    """One question, answered as it is written - or the page changed, when that
    is what was asked for (`askai.py`, "Changing the page").

    The answer streams back as server-sent events, which is what the drawer's
    own reader loop already expects; app.js passes the bytes on to the frame
    without looking inside them.

    Anybody who reaches this route is signed in with a whole account - a guest
    is turned away at the gate - and the workspace is theirs, so they may
    change its pages. A reader who is not the owner asks through the routes
    under their own token instead (`rouh/web/guests.py`).
    """
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    doc = str(request.GET.get("doc") or asked.get("doc") or "")
    # The exchange goes into the conversation the page had on the screen as
    # well, which is the one the orb talks in (`runtime.askai_said`).
    said_to = _rt().askai_said(str(asked.get("chat") or "")[:80], doc,
                               str(asked.get("title") or "").strip()[:200])
    response = StreamingHttpResponse(
        askai.answer(config, _rt().ask_threads, me, doc, asked, can_edit=True,
                     said_to=said_to),
        content_type="text/event-stream")
    response["Cache-Control"] = "no-store, private"
    response["X-Accel-Buffering"] = "no"
    return response


@only("POST")
async def askai_undo(request: HttpRequest):
    """Put a page back as it was before one change Ask AI made to it, for the
    person who asked for that change."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    doc = str(request.GET.get("doc") or asked.get("doc") or "")
    try:
        done = await asyncio.to_thread(askai.undo, config.assistant_repo, me, doc,
                                       asked.get("edit"))
    except (askai.EditRefused, askai.Unavailable) as exc:
        return refuse(str(exc), 409)
    return answer(done, headers=NO_STORE)


@only("POST")
async def askai_type(request: HttpRequest):
    """What the person typed straight into a piece of a page's text, written
    into the page and kept as a change like Ask AI's (`askai.type_text`)."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    doc = str(request.GET.get("doc") or asked.get("doc") or "")
    try:
        done = await asyncio.to_thread(askai.type_text, config.assistant_repo, me, doc, asked)
    except (askai.EditRefused, askai.Unavailable) as exc:
        return refuse(str(exc), 409)
    return answer(done, headers=NO_STORE)


# --- a page's history, and the options kept over it -------------------------------------------
#
# Petar, 24 September 2026 (fr_b91369ea7ba2): a history of every change to a
# page, who made it and when, each one openable as the page was then; and for
# every change, whether it is kept as an option viewers can switch between.
# `rouh/pagehistory.py` is all of it. These are asked through the page around
# the frame, like the three above, and name the page the same way.


def _page_now(root, doc: str) -> str:
    return askai.read_source(askai.resolve(root, doc))


@only("GET")
async def askai_history(request: HttpRequest):
    """Every change to this page, newest first, for the History panel."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    doc = request.GET.get("doc", "")
    root = config.assistant_repo
    try:
        source = await asyncio.to_thread(_page_now, root, doc)
    except (askai.Unavailable, askai.EditRefused) as exc:
        return refuse(str(exc), 404)
    entries = await asyncio.to_thread(pagehistory.history, root, me.org_id, doc, source)
    return answer({"entries": entries}, headers=NO_STORE)


@only("POST")
async def askai_where(request: HttpRequest):
    """Where one change Ask AI made is on its page, for Show me (`rouh/askai_show.py`)."""
    from rouh import askai_show

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    doc = str(request.GET.get("doc") or asked.get("doc") or "")
    try:
        done = await asyncio.to_thread(askai_show.place, me, doc, asked.get("edit"))
    except askai_show.Refused as exc:
        return refuse(str(exc), 409)
    return answer(done, headers=NO_STORE)


@only("POST")
async def askai_keep(request: HttpRequest):
    """Keep one change as final, or as an option beside the version before it."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    doc = str(request.GET.get("doc") or asked.get("doc") or "")
    root = config.assistant_repo
    try:
        done = await asyncio.to_thread(pagehistory.keep, root, me, me.org_id, doc,
                                       asked.get("edit"), str(asked.get("keep") or ""))
    except (pagehistory.Refused, askai.Unavailable, askai.EditRefused) as exc:
        return refuse(str(exc), 409)
    done["options"] = await asyncio.to_thread(pagehistory.options_now, root, me.org_id, doc)
    return answer(done, headers=NO_STORE)


@only("POST")
async def askai_option(request: HttpRequest):
    """Make one version of an option the default or final, or stop offering it."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    doc = str(request.GET.get("doc") or asked.get("doc") or "")
    return await option_action(config.assistant_repo, me, me.org_id, doc, asked, True)


async def option_action(root, me, org_id: str, doc: str, asked: dict,
                        may_remove: bool) -> HttpResponse:
    """One thing done to one option, for the owner here and for a reader of a
    shared page (`rouh/web/guests.py`). Anybody who can read the page may pick
    its default; only somebody who may change the page may make one final, open
    it again, stop offering one, or write why one of its versions exists.
    ``list`` changes nothing and answers with the options as they are now: Ask
    AI's pass over the comments may have offered another version since the
    page was sent."""
    action = str(asked.get("action") or "")
    try:
        if action == "list":
            await asyncio.to_thread(askai.resolve, root, doc)
            done = {}
        elif action == "default":
            done = await asyncio.to_thread(pagehistory.choose, root, me, org_id, doc,
                                           asked.get("option"), asked.get("choice"))
        elif action == "final" and may_remove:
            done = await asyncio.to_thread(pagehistory.decide, root, me, org_id, doc,
                                           asked.get("option"), asked.get("choice"))
        elif action == "reopen" and may_remove:
            await asyncio.to_thread(askai.resolve, root, doc)
            done = await asyncio.to_thread(pagehistory.reopen, me, org_id, doc,
                                           asked.get("option"))
        elif action == "remove" and may_remove:
            done = await asyncio.to_thread(pagehistory.remove, me, org_id, doc,
                                           asked.get("option"))
        elif action == "reason" and may_remove:
            await asyncio.to_thread(askai.resolve, root, doc)
            done = await asyncio.to_thread(pagehistory.set_reason, me, org_id, doc,
                                           asked.get("option"), asked.get("choice"),
                                           asked.get("reason"))
        else:
            return refuse("That cannot be done to these options from here.", 400)
    except (pagehistory.Refused, askai.Unavailable, askai.EditRefused) as exc:
        return refuse(str(exc), 409)
    done["options"] = await asyncio.to_thread(pagehistory.options_now, root, org_id, doc)
    return answer(done, headers=NO_STORE)


# --- public pages ----------------------------------------------------------------------------
#
# A page built in the workspace, and its one link. `sharing.py` is the store
# and says what is shared and what is not. Three of these are the owner's and
# behind the sign-in like everything else; the fourth, `GET /p/<token>`, is
# the only address that answers a stranger, with exactly one page - the one
# whose token was in the address - and only while that page is public.

def _shareable(rel: str) -> tuple[str, str]:
    """The page `rel` names and its title, or Refused saying why not.

    The rule is `sharing.shareable`, one copy of it for this panel and for
    the assistant's own `publish_task`: a page, and exactly what `pages.py`
    would serve a signed-in person.
    """
    return sharing.shareable(config.assistant_repo, rel)


def _inherited(me, rel: str) -> list[dict]:
    from rouh import task_access

    try:
        return task_access.inherited(me, rel)
    except Exception:  # noqa: BLE001 - the panel shows the rest
        log.exception("sharing: who inherits %s could not be read", rel)
        return []


def _share_state(me, rel: str, title: str = "") -> dict:
    """What the panel is told about one page: its link, whether it is public,
    what a visitor may do with it, and who else it is shared with.

    The link is there whether or not the page is public, made the first time
    the panel asks (`Shares.link`), because it is the same link either way:
    whether it is public, and who it is shared with, is only who it lets in.
    """
    from rouh import mailer, taskshare

    from . import guests as guests_web

    row = _rt().shares.link(me, rel, title)
    return {
        "rel": rel,
        # A task or a subtask, which the panel says in its own words: its
        # link is read only, and a person may be given either (`rouh/taskshare.py`).
        "kind": "task" if taskshare.is_task(rel) else "page",
        "title": row.get("title") or title,
        "public": bool(row.get("public")),
        # The path and not the whole address. The browser puts its own origin
        # in front of it (`shareLink` in app.js), so the link the person copies
        # is a link to the Rouh they are looking at.
        "path": row.get("path") or "",
        "role": row.get("role") or sharing.VIEW,
        # With when each last opened it, while that gene is on (`rouh/share_opens.py`).
        "people": guests_web._people(me, rel),
        # Who may do something here by a record above it, a quest's or a task's: the one
        # permission inherits down (`rouh/task_access.py`), so the panel says so.
        "inherited": _inherited(me, rel),
        # Whether an invitation can be sent from here at all, so the panel can
        # say so before anybody types an address rather than after.
        "can_mail": mailer.Mailer(config).configured(),
    }


async def _share_read(request: HttpRequest):
    """Whether this page is public, for the panel that has just opened."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    try:
        rel, title = await asyncio.to_thread(_shareable, request.GET.get("rel", ""))
    except (pages.Refused, OSError) as exc:
        return refuse(str(exc), 404)
    return answer(await asyncio.to_thread(_share_state, me, rel, title), headers=NO_STORE)


async def _share_set(request: HttpRequest):
    """Make this page public, or take it down again. Both directions are
    idempotent: making a page public twice hands back the link that is already
    out there, and taking down a page that is not public is not an error. The
    link is the same before and after either: only who it lets in changes."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    want = bool(asked.get("public"))
    # What a visitor may do: read it, which every link could until 24
    # September 2026, or change it with Ask AI too. Left out, it is kept as
    # it was.
    role = sharing.role_of(asked["role"]) if "role" in asked else None
    try:
        rel, title = await asyncio.to_thread(_shareable, str(asked.get("rel") or ""))
    except (pages.Refused, OSError) as exc:
        return refuse(str(exc), 404)
    shares = _rt().shares
    if want:
        await asyncio.to_thread(shares.share, me, rel, title, role)
        log.info("sharing: %s is public%s", rel,
                 ", and a visitor may change it" if role == sharing.EDIT else "")
    elif await asyncio.to_thread(shares.stop, me, rel):
        log.info("sharing: %s is not public any more", rel)
    return answer(await asyncio.to_thread(_share_state, me, rel, title), headers=NO_STORE)


share = methods(GET=_share_read, POST=_share_set)


@only("GET")
async def share_all(request: HttpRequest):
    """Every page this person has public, newest first. The only listing there
    is, behind the sign-in, and scoped to the person asking."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    return answer({"pages": await asyncio.to_thread(_rt().shares.mine, me)}, headers=NO_STORE)


@only("POST")
async def share_stop(request: HttpRequest):
    """Take one page down, named by its token: a share whose folder has moved
    since it was shared still has to be possible to take down."""
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("Sign in to Rouh first.", 401)
    token = sharing.clean_token(str(body_of(request).get("token") or ""))
    if not token:
        return refuse("That is not a share.", 400)
    stopped = await asyncio.to_thread(_rt().shares.stop_token, me, token)
    if stopped:
        log.info("sharing: a page was taken down from the list of public pages")
    return answer({"stopped": stopped, "token": token}, headers=NO_STORE)


#: Sent with a public page on top of `pages.HEADERS`: a link the person sends
#: somebody is not an invitation to the whole web.
PUBLIC_HEADERS = {**pages.HEADERS, "X-Robots-Tag": "noindex, nofollow, noarchive"}


@only("GET")
async def public_page(request: HttpRequest, token: str):
    """A page's one link: the page, to whoever it lets in.

    Who that is, in order (`sharing.py`, "One link per page"):

    - **Its owner**, signed in, lands on the page in their own Rouh, public or
      not, as the owner of a Drive file opening its link lands in Drive.
    - **A person it is shared with by email**, signed in with that address,
      lands on their own reader's page (`/shared/<token>`), with what they may
      do there, public or not.
    - **Anybody at all**, while it is public, as below.
    - Otherwise, **somebody not signed in** is asked to sign in, and comes
      back here once they have; **somebody signed in** is told it is not shared
      with them. Neither is shown a word of it.

    When it is public:

    - It serves the page the token names, and nothing else. The token comes
      out of the address and goes nowhere near the filesystem: the path does,
      and that comes out of the row the token found.
    - It runs `pages.read` with no `at`, so the page is sandboxed by
      `pages.CSP` exactly as it always was.
    - **There is no Ask AI on it** (`sharing.py` says why), unless the owner
      said a visitor may change it: then it is the reader's page, with the
      page in a frame and Ask AI in it (`rouh/web/guests.py`).
    - A share whose page has since gone is a 404 rather than a 500, and the
      row stays so the person can still see it in their list and take it down.
    """
    from rouh import taskshare

    found = await asyncio.to_thread(_rt().shares.opened, token)
    if found is None:
        return _page_response("Not found.", "text/plain", status=404, headers=PUBLIC_HEADERS)
    user = await request.auser()
    if user.is_authenticated:
        me = await sync_to_async(who)(request)
        if me is not None and (str(me.user_id), str(me.org_id)) == (found["owner_id"],
                                                                    found["org_id"]):
            # A task's link is its folder, and its address in Rouh is that
            # folder's under `/task/`, a subtask's included.
            mine = taskshare.folder_of(found["rel"]) or found["rel"]
            return HttpResponseRedirect("/task/" + quote(mine, safe="/"))
        held = await asyncio.to_thread(_rt().guests.held_by, found["owner_id"],
                                       found["org_id"], found["rel"], user)
        if held is not None:
            return HttpResponseRedirect(held["path"])
    if not found["public"]:
        if not user.is_authenticated:
            from urllib.parse import urlencode

            return HttpResponseRedirect("/login?" + urlencode({"next": request.path}))
        from . import guests

        return await asyncio.to_thread(guests.not_shared_page, request)
    if taskshare.is_task(found["rel"]):
        return await _task_response(found, request.GET.get("at", ""),
                                    sharing.ROUTE + found["token"], PUBLIC_HEADERS)
    if found["role"] == sharing.EDIT:
        from . import guests

        return await guests.LINK["view"](request, token)
    try:
        body, kind = await asyncio.to_thread(pages.read, config.assistant_repo,
                                             found["rel"], found["rel"])
    except (pages.Refused, OSError):
        log.info("sharing: %s is public but could not be read", found["rel"])
        return _page_response("This page is not there any more.", "text/plain", status=404,
                              headers=PUBLIC_HEADERS)
    return _page_response(body, kind, headers=PUBLIC_HEADERS)


def _owner_called(owner_id: str) -> str:
    from rouh.models import User

    owner = User.objects.filter(pk=int(owner_id)).first() if str(owner_id).isdigit() else None
    return ((owner.get_full_name() or owner.username or "").strip() if owner else "") \
        or "Somebody"


async def _task_response(found: dict, at: str, base: str, headers: dict,
                         can_edit: bool = False, home: str = "",
                         person: bool = False) -> HttpResponse:
    """A shared task, at one place inside it, for somebody it lets in.

    What is shown and what never is, is `rouh/taskshare.py`. A place that is
    not one of the task's levels, pages or notes is "Not found", the same as
    a page that has gone. `can_edit` is a person it was shared with to
    change, which the view says (`rouh/web/guests.py` opens its pages).
    """
    from rouh import taskshare

    owner = await asyncio.to_thread(_owner_called, found["owner_id"])
    try:
        body, kind = await asyncio.to_thread(taskshare.view, config.assistant_repo,
                                             found["rel"], str(at or ""), base, owner,
                                             can_edit, home, person)
    except (pages.Refused, OSError):
        log.info("sharing: a place in the shared task %s could not be read", found["rel"])
        return _page_response("Not found.", "text/plain", status=404, headers=headers)
    return _page_response(body, kind, headers=headers)


# --- this machine's own callers ----------------------------------------------------------------


@csrf_exempt
@only("POST")
async def crew_event(request: HttpRequest):
    """Claude Code hooks in a worker's worktree POST here.

    Every legitimate caller is on this machine: the hooks are curl calls
    straight to 127.0.0.1:8021 and never pass through nginx. What each hook
    means, and why most of them are only stored, is `runtime.crew_event`.

    Exempt from the CSRF check, because no browser is involved: the check is
    `from_this_machine`, which is stricter than a sign-in, not looser.
    """
    if not from_this_machine(request):
        return answer({"ok": False}, status=403)
    return answer(await _rt().crew_event(dict(request.GET.items()), body_of(request)))


@csrf_exempt
@only("POST")
async def outbox_note(request: HttpRequest):
    """A background job queueing an email for Rouh to send the person.

    The `notify_owner` tool every worker is given posts here
    (`rouh/worker_mcp.py`), on the same terms as the hook endpoint above: only
    this machine, never through the proxy. Three fields are read - the job's
    id, a subject and a body - and all that can come of them is one pending
    row (`outbox.queue`). There is no address to give, and nothing here sends
    a message or marks one: that is Rouh's own tool, in a turn the person is
    in (`worker_outbox` in `rouh/tools.py`).
    """
    if not from_this_machine(request):
        return answer({"ok": False}, status=403)
    body = body_of(request)
    try:
        made = await asyncio.to_thread(outbox.queue, str(body.get("job") or ""),
                                       str(body.get("subject") or ""),
                                       str(body.get("body") or ""))
    except outbox.Refused as exc:
        return answer({"ok": False, "reason": str(exc)}, status=400)
    return answer({"ok": True, **made})


@csrf_exempt
@only("POST")
async def nightly_tool(request: HttpRequest):
    """One of the nightly feature run's tools (`rouh/nightly_feature.py`, `act`).

    Posted by the `nightly_*` tools of `rouh/worker_mcp.py`, on the outbox's terms: only
    this machine, never through the proxy, and the run's own id, which is answered only
    when it is a night's run (or the run undoing one, or the run a mutation request started for
    itself, `evolution.start_mutation`).
    """
    if not from_this_machine(request):
        return answer({"ok": False}, status=403)
    from rouh import nightly_feature

    body = body_of(request)
    return answer(await nightly_feature.act(str(body.get("job") or ""),
                                            str(body.get("action") or ""),
                                            body.get("args") or {}))


@csrf_exempt
@only("POST")
async def case_fix_tool(request: HttpRequest):
    """One of the tools of a run fixing a false alarm's check (`rouh/case_fixes.py`, `act`).

    Posted by the `case_fix_*` tools of `rouh/worker_mcp.py`, on the outbox's terms: only this
    machine, never through the proxy, and the run's own id, answered only when it is a fix's.
    """
    if not from_this_machine(request):
        return answer({"ok": False}, status=403)
    from rouh import case_fixes

    body = body_of(request)
    return answer(await case_fixes.act(str(body.get("job") or ""), str(body.get("action") or ""),
                                       body.get("args") or {}))


@csrf_exempt
@only("POST")
async def refactor_tool(request: HttpRequest):
    """The nightly refactoring run's one tool, `refactor_done` (`rouh/nightly_refactor.py`, `act`).

    Posted by `rouh/worker_mcp.py`, on the outbox's terms: only this machine, never through the
    proxy, and the run's own id, answered only when it is a night's own run.
    """
    if not from_this_machine(request):
        return answer({"ok": False}, status=403)
    from rouh import nightly_refactor

    body = body_of(request)
    return answer(await nightly_refactor.act(str(body.get("job") or ""), str(body.get("action") or ""),
                                             body.get("args") or {}))


@csrf_exempt
@only("POST")
async def job_tools_tool(request: HttpRequest):
    """A background job listing or calling Rouh's own tools (`rouh/job_gateway.py`).

    Posted by the `rouh` MCP server of `rouh/worker_mcp.py`, on the outbox's terms: only this
    machine, never through the proxy, and the job's own id, from which Rouh decides whom the
    job works for. Every call is ruled on in code (`rouh/job_policy.py`) before anything runs.
    """
    if not from_this_machine(request):
        return answer({"ok": False}, status=403)
    from rouh import job_gateway

    body = body_of(request)
    return answer(await job_gateway.act(str(body.get("job") or ""), str(body.get("action") or ""),
                                        str(body.get("tool") or ""), body.get("args") or {}))


@only("GET")
async def job_requests(request: HttpRequest):
    """What background jobs asked Rouh for, by gap, for the Metabolism page (`job_gateway.recent`)."""
    from rouh import job_gateway

    me = await asyncio.to_thread(who, request)
    if me is None:
        return answer({"ok": False, "reason": "Sign in first."}, status=401)
    got = await asyncio.to_thread(job_gateway.recent, me)
    return answer({"ok": True, **got}, headers={"Cache-Control": "no-store"})


@csrf_exempt
@only("POST")
async def wipe_test_jobs(request: HttpRequest):
    """Forget every finished job a live check started ("... - safe to delete").

    Only this machine may call it, on the same terms as the hook endpoint
    above. There is no tool for it, so the model cannot call it either.
    """
    if not from_this_machine(request):
        return answer({"ok": False}, status=403)
    return answer(await _rt().wipe_test_jobs())


def not_found(request: HttpRequest, exception=None):
    """What an address nobody answers gets: a sentence, not Django's page."""
    if request.path.startswith("/api/"):
        return refuse("not found", 404)
    return HttpResponse("Not found.", status=404, content_type="text/plain; charset=utf-8")


def server_error(request: HttpRequest):
    """A 500 that gives nothing of the machine away. The log has the rest."""
    if request.path.startswith("/api/"):
        return refuse("Something went wrong on the server. Its log says what.", 500)
    return HttpResponse("Something went wrong on the server.", status=500,
                        content_type="text/plain; charset=utf-8")

