"""Changing a task's status, summary or meta from outside Rouh: `rouh-task`'s two doors.

The database is the only place a task's status and summary are kept (`rouh/taskrecord.py`),
so a job, a run of the one program, a terminal and a copy of the workspace elsewhere all change
them here, and nowhere else.

- ``/internal/task`` is for this machine: a job or a run in its checkout, or a terminal.
  Only a caller on this machine that did not come through the proxy is answered
  (`from_this_machine`), on the same terms as the notes a job queues (`/internal/outbox`).
  Who it was is what the caller's environment said: the run (``ONE_RUN``) or the crew job
  (``ROUH_JOB``) that started it, or the Linux user at a terminal.
- ``/api/task`` is for anywhere else, over https, with a key in ``Authorization: Bearer``
  that `manage.py task_token add` made for one person. The gate lets this one address
  through to here without a sign-in (`gate.TOKEN_PATHS`), and this refuses anything without
  a live key. A key opens nothing else.

GET ``?ref=58`` answers what the task says now, with its latest changes, its meta and the
chats it owns, main first (`rouh/taskchats.py`); GET ``?check=chats`` (this machine only) lists every task's chat
that looks as if it belongs to another task, and changes nothing. POST
``{"ref": "58", "status": "waiting"}`` or ``{"ref": "58", "summary": "..."}`` changes it,
and ``{"ref": "58", "how": "merge", "meta": {...}}`` its meta (`rouh/taskmeta.py`),
with ``id`` and ``folder`` when the caller could read them off its checkout, which is how a
task a job made and has not landed is told apart (`taskrecord.change`).
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest
from django.views.decorators.csrf import csrf_exempt

from rouh import taskmeta, taskrecord

from .common import answer, body_of, from_this_machine, only

log = logging.getLogger(__name__)


def _rt():
    from rouh import runtime

    return runtime


@csrf_exempt
@only("GET", "POST")
async def internal_task(request: HttpRequest):
    """A job, a run or a terminal on this machine, reading or changing a task."""
    if not from_this_machine(request):
        return answer({"ok": False, "error": "Only this machine may use this address."},
                      status=403)
    if request.method == "GET" and request.GET.get("check") == "chats":
        from rouh import taskchats

        return answer({"ok": True, "misbound": await asyncio.to_thread(taskchats.misbound)})
    body = body_of(request) if request.method == "POST" else {}
    run = str(body.get("run") or "")[:80]
    by = " ".join(str(body.get("by") or "").split())[:120] or (
        f"run {run}" if run else "this machine")
    return await _answer(request, body, by=by, run=run)


@csrf_exempt
@only("GET", "POST")
async def api_task(request: HttpRequest):
    """The same, from anywhere, for a person holding one of their keys."""
    said = request.headers.get("authorization") or ""
    raw = said[7:].strip() if said.lower().startswith("bearer ") else ""
    key = await asyncio.to_thread(taskrecord.token_owner, raw) if raw else None
    if key is None:
        return answer({"ok": False, "error": "That key is not one Rouh knows, or it was "
                       "revoked. Make one with manage.py task_token add on the server."},
                      status=401)
    who = await asyncio.to_thread(_username, key.user_id)
    body = body_of(request) if request.method == "POST" else {}
    return await _answer(request, body, by=f"{who} ({key.name})", run="")


def _username(user_id: str) -> str:
    from rouh.models import User

    row = User.objects.filter(id=user_id).first()
    return row.username if row is not None else f"user {user_id}"


async def _answer(request: HttpRequest, body: dict, *, by: str, run: str):
    if request.method == "GET":
        ref = request.GET.get("ref") or ""
        got = await asyncio.to_thread(_show, ref, request.GET.get("id") or "",
                                      request.GET.get("folder") or "")
        if got is None:
            return answer({"ok": False, "error": f"Rouh has no task {ref}."}, status=404)
        return answer({"ok": True, **got})
    if "meta" in body:
        try:
            done = await asyncio.to_thread(
                taskmeta.from_outside, str(body.get("ref") or ""), str(body.get("how") or ""),
                body.get("meta"), key=str(body.get("key") or ""), by=by, run=run,
                ident=str(body.get("id") or ""), folder=str(body.get("folder") or ""))
        except taskrecord.Refused as exc:
            return answer({"ok": False, "error": str(exc)}, status=400)
        log.info("%s: %s", by, done["did"])
        await _announce(body.get("ref"))
        return answer(done)
    status = body.get("status")
    summary = body.get("summary")
    try:
        done = await asyncio.to_thread(
            taskrecord.change, str(body.get("ref") or ""),
            status=None if status is None else str(status),
            summary=None if summary is None else str(summary),
            by=by, run=run, ident=str(body.get("id") or ""),
            folder=str(body.get("folder") or ""))
    except taskrecord.Refused as exc:
        return answer({"ok": False, "error": str(exc)}, status=400)
    log.info("%s: %s", by, done["did"])
    if not done.get("pending"):
        await _announce(body.get("ref"))
    return answer(done)


async def _announce(ref) -> None:
    """Every open tab draws the task as it now is: the task browser, the rail, the control
    room and the decisions list all read the row."""
    rt = _rt()
    for say in (rt.announce_objects, rt._announce_workspace):
        try:
            await say()
        except Exception:
            log.exception("the change to %s could not be announced", ref)


def _show(ref: str, ident: str, folder: str) -> dict | None:
    st = taskrecord._store()
    row = taskrecord.find(st, ref, ident=ident, folder=folder)
    if row is None:
        return None
    from rouh import taskchats

    return {"task": taskrecord.view(row), "history": taskrecord.history(row.id, 10),
            "meta": taskmeta.of(row.id), "chats": taskchats.of_task(row.id)}
