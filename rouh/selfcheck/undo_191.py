"""Undo beyond Cloudflare, and the waiting calls the switch lets through, checked (`rouh/unrestricted.py`,
task 191, 191-03).

What these prove, each by calling Rouh's own code the way a run or the Permissions page does, with
every service stood in for by an object that only writes down what it was asked:

- a Drive file put in the bin, renamed or moved, a message's labels changed, archived or binned,
  and a calendar event deleted each keep, as the tool runs, how to put it back;
- Undo in What Rouh did puts each kind back with its own service (Drive, Calendar, Gmail, iCloud
  contacts, Slack), newest first, and a step that fails leaves only what is still to do;
- switching to Unrestricted lets through the calls already waiting from the owner's own live run,
  answered yes through the decisions' one answer path and written into What Rouh did, and nothing
  else: a payment, a process's run, an ended run and a run with no words of the owner's still wait;
- a released call's row is given its undo once it has run.

Every person, address and id here is made up, on .example domains.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from . import check, expect
from .unrestricted import _owner, _run, _set_mode


class _Said:
    """A stand-in service: every call is written down, and answers come from `answers`."""

    def __init__(self, **answers):
        self.calls: list = []
        self.answers = answers

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        async def call(*args, **kw):
            self.calls.append((name, args, kw))
            got = self.answers.get(name)
            return got(*args, **kw) if callable(got) else got

        return call


def _desk(**services):
    google = SimpleNamespace(not_ready_because=lambda: "", wrote=lambda *a, **k: None,
                             services=lambda: SimpleNamespace(**services))
    return google


def _collect(coro) -> list:
    from rouh import unrestricted

    async def go():
        steps = unrestricted.collecting()
        await coro
        return steps

    return asyncio.run(go())


@check("undo_191", "Drive, Gmail and Calendar tools keep how to undo what they change",
       "a file binned, renamed and moved, a message's labels and archive changed or binned, and an "
       "event deleted each leave an undo step with what was there before; nothing is kept when "
       "nobody collects")
def tools_keep_their_undo() -> None:
    from rouh import tools, unrestricted

    reg = tools.ToolRegistry
    meta = {"id": "f1", "name": "Plan.doc", "parents": ["old-folder"], "mime_type": "text/plain",
            "type": "file", "trashed": False}
    drive = _Said(trash=lambda *a: {"name": "Plan.doc", "mime_type": "text/plain"},
                  metadata=lambda *a: dict(meta),
                  rename=lambda *a: {"mime_type": "text/plain"},
                  folder_id=lambda *a, **k: "new-folder",
                  move=lambda fid, folder: {"name": "Plan.doc", "mime_type": "text/plain",
                                            "folder_id": folder})
    me = SimpleNamespace(google=_desk(drive=drive))

    async def which(*_a):
        return ""

    me._on_which_drive = which
    steps = _collect(reg._manage_drive_file(me, {"file_id": "f1", "trash": True}, None))
    expect(steps == [{"kind": "drive", "do": "untrash", "id": "f1", "name": "Plan.doc",
                      "what": "file"}], f"a file put in the bin kept {steps}")
    steps = _collect(reg._manage_drive_file(me, {"file_id": "f1", "new_name": "Plan v2.doc",
                                                 "folder": "Archive"}, None))
    kinds = [(s["do"], s.get("name"), s.get("add"), s.get("remove")) for s in steps]
    expect(kinds == [("rename", "Plan.doc", None, None),
                     ("reparent", "Plan.doc", ["old-folder"], ["new-folder"])],
           f"a rename and a move kept {kinds}")
    # Nobody collecting: nothing is read before, nothing kept.
    drive.calls.clear()
    asyncio.run(reg._manage_drive_file(me, {"file_id": "f1", "new_name": "Plan v3.doc"}, None))
    expect(not any(c[0] == "metadata" for c in drive.calls),
           "the file was read for an undo nobody collects")
    expect(not unrestricted.collecting_now(), "an undo list was left set")

    gmail = _Said(labels_now=lambda *a: ["INBOX", "UNREAD", "Label_7"],
                  modify=lambda mid, add=(), remove=(): {"labels": ["Label_7", "Label_9"]},
                  label_ids=lambda names, **k: ({n: "Label_9" for n in names}, []),
                  trash=lambda *a: {})

    async def theirs(*_a):
        return ""

    me = SimpleNamespace(google=_desk(gmail=gmail), _refused_theirs=theirs)
    steps = _collect(reg._modify_mail(me, {"message_id": "m1", "archive": True, "mark_read": True,
                                           "add_labels": ["Follow up"]}, None))
    expect(steps == [{"kind": "gmail", "do": "labels", "id": "m1", "add": ["INBOX", "UNREAD"],
                      "remove": ["Label_9"]}], f"a label change kept {steps}")
    steps = _collect(reg._modify_mail(me, {"message_id": "m1", "trash": True}, None))
    expect(steps == [{"kind": "gmail", "do": "untrash", "id": "m1"}], f"a binned message kept {steps}")

    gone = {"id": "e1", "title": "Team lunch", "series": "", "guests": [], "mine": True,
            "calendar": "Work", "start": None, "end": None, "all_day": False}
    calendar = _Said(find_event=lambda *a: "work@team.example", delete=lambda *a, **k: dict(gone))
    me = SimpleNamespace(google=_desk(calendar=calendar))
    old = tools._calendar_when
    tools._calendar_when = lambda e: "today"
    try:
        steps = _collect(reg._delete_calendar_event(me, {"event_id": "e1", "confirmed": True}, None))
    finally:
        tools._calendar_when = old
    expect(steps == [{"kind": "calendar", "do": "restore", "calendar": "work@team.example",
                      "id": "e1", "title": "Team lunch"}], f"a deleted event kept {steps}")


@check("undo_191", "Undo puts each kind back with its own service",
       "a row of What Rouh did holding Drive, Calendar, Gmail, contact and Slack steps is put back "
       "newest first, each by its own service, and is then undone; a step that fails is said, and "
       "a second Undo does only what is left", needs_db=True)
def undo_puts_back() -> None:
    from rouh import runtime, slack, unrestricted
    from rouh.models import UnrestrictedAction

    who = _owner()
    drive, calendar, gmail = _Said(), _Said(restore=lambda *a, **k: {"restored": True}), _Said()
    contacts = _Said(put_back=lambda who, step: f"{step['name']} is as it was again")
    deleted = []
    old = (unrestricted._google, runtime.contacts, slack.connection, slack.delete_message)
    unrestricted._google = lambda _who: SimpleNamespace(drive=drive, calendar=calendar, gmail=gmail)
    runtime.contacts = contacts
    slack.connection = lambda org: object()
    slack.delete_message = lambda conn, channel, ts: deleted.append((channel, ts))
    try:
        steps = [{"kind": "drive", "do": "untrash", "id": "f1", "name": "Plan.doc"},
                 {"kind": "drive", "do": "rename", "id": "f1", "name": "Plan.doc", "now": "Plan v2"},
                 {"kind": "drive", "do": "reparent", "id": "f1", "add": ["a"], "remove": ["b"]},
                 {"kind": "calendar", "do": "restore", "calendar": "c", "id": "e1", "title": "Lunch"},
                 {"kind": "calendar", "do": "fields", "calendar": "c", "id": "e2",
                  "fields": {"summary": "Lunch"}, "title": "Lunch"},
                 {"kind": "calendar", "do": "move", "calendar": "d", "id": "e2", "back": "c"},
                 {"kind": "gmail", "do": "labels", "id": "m1", "add": ["INBOX"], "remove": []},
                 {"kind": "gmail", "do": "untrash", "id": "m2"},
                 {"kind": "contact", "do": "card", "href": "/c/1.vcf", "name": "Ana Example",
                  "vcard": "BEGIN:VCARD\r\nEND:VCARD"},
                 {"kind": "slack", "do": "delete", "channel": "C1", "ts": "1.2", "where": "#team"}]
        ident = unrestricted.record(who, via="job", where="check-undo", title="check", tool="many",
                                    args={}, what="Many things", why="a check", result="done",
                                    undo=steps)
        got = unrestricted.undo(who, ident)
        expect(got["ok"], f"Undo failed: {got}")
        # Newest first, each service in the reverse of the order the changes were made.
        for service, wanted in ((drive, ["reparent", "rename", "untrash"]),
                                (calendar, ["move_to", "put_fields", "restore"]),
                                (gmail, ["untrash", "modify"]), (contacts, ["put_back"])):
            asked = [c[0] for c in service.calls]
            expect(asked == wanted, f"a service was asked {asked}, not {wanted}")
        expect(gmail.calls[1][2] == {"add": ["INBOX"], "remove": []},
               f"the labels were not put back as kept: {gmail.calls[1]}")
        expect(deleted == [("C1", "1.2")], "Rouh's Slack message was not deleted")
        row = UnrestrictedAction.objects.get(id=ident)
        expect(row.undone_at and "Ana Example is as it was again" in row.undone_said,
               f"the row was not marked undone: {row.undone_said!r}")
        # A step that fails: what was put back stays done, and only the rest is left.
        def refuse(*_a, **_k):
            raise RuntimeError("Google said no")

        gmail.answers["modify"] = refuse
        ident = unrestricted.record(who, via="job", where="check-undo", title="check", tool="many",
                                    args={}, what="Two things", why="a check", result="done",
                                    undo=[{"kind": "gmail", "do": "labels", "id": "m1",
                                           "add": ["INBOX"], "remove": []},
                                          {"kind": "gmail", "do": "untrash", "id": "m2"}])
        got = unrestricted.undo(who, ident)
        expect(not got["ok"] and "Google said no" in got["said"], f"a failure was not said: {got}")
        left = (UnrestrictedAction.objects.get(id=ident).undo or {}).get("steps")
        expect(left == [{"kind": "gmail", "do": "labels", "id": "m1", "add": ["INBOX"],
                         "remove": []}], f"what is left to undo is {left}")
    finally:
        unrestricted._google, runtime.contacts, slack.connection, slack.delete_message = old


@check("undo_191", "switching on lets the owner's waiting calls through, and nothing else",
       "the owner's own live run's waiting Slack post is answered yes by the switch through the "
       "decisions and written into What Rouh did; its payment, a process's run, an ended run and a "
       "run with no words of the owner's still wait; once it has run, its row has its undo",
       needs_db=True)
def switch_releases_waiting() -> None:
    from rouh import decisions, heartbeat, unrestricted
    from rouh.models import Decision, HeartbeatApproval, UnrestrictedAction

    who = _owner()
    _set_mode(who, "restricted")
    runs = ("check-rel-own", "check-rel-proc", "check-rel-ended", "check-rel-mute")
    HeartbeatApproval.objects.filter(duty__in=[f"job:{r}" for r in runs]).delete()
    _run("check-rel-own", who)
    _run("check-rel-proc", who, made_by="process:nightly")
    _run("check-rel-ended", who, state="done")
    _run("check-rel-mute", who, words="")
    mine = (str(who.user_id), str(who.org_id or ""))

    def q(run, tool, args, what):
        return int(heartbeat.queue(None, mine, tool=tool, args=args, what=f"{what}, for job {run}",
                                   to_whom="", why="a check", cost="", blocking=False,
                                   duty=f"job:{run}"))

    post = q("check-rel-own", "slack_send", {"to": "#team", "text": "Done."}, "Post in #team")
    pay = q("check-rel-own", "payments", {"action": "charge", "amount": 40}, "Pay 40")
    kept = [q("check-rel-proc", "slack_send", {"to": "#team", "text": "Night."}, "Night note"),
            q("check-rel-ended", "slack_send", {"to": "#team", "text": "Old."}, "Old note"),
            q("check-rel-mute", "slack_send", {"to": "#team", "text": "Mute."}, "Mute note")]
    decisions.sync(who, kinds=["approval"])
    try:
        _set_mode(who, "unrestricted")
        let = unrestricted.after_flip(who, unrestricted.Mode(), unrestricted.current(who))
        expect(let == [post], f"the switch let through {let}, not only the owner's Slack post {post}")
        d = next(d for d in Decision.objects.filter(user_id=mine[0], source="approval")
                 .order_by("-id") if any(p.get("approval") == post for p in d.prepared or []))
        expect(d.status in (decisions.ANSWERED, decisions.APPLYING, decisions.APPLIED)
               and (d.answer or {}).get("items") == {str(post): "yes"},
               f"the decision holding it was answered {d.status} {d.answer}")
        row = UnrestrictedAction.objects.filter(undo__approval=post).first()
        expect(row is not None and "switched to Unrestricted" in row.why,
               "What Rouh did has no row for the call let through")
        for ident in [pay] + kept:
            expect(HeartbeatApproval.objects.get(id=ident).state == "waiting",
                   f"approval {ident} did not wait")
        # Switched back, nothing is let through.
        expect(unrestricted.after_flip(who, unrestricted.current(who), unrestricted.Mode()) == [],
               "switching back let something through")
        # Once it has run, its row has its undo.
        approval = HeartbeatApproval.objects.get(id=post)
        unrestricted.ran_released(approval, state="yes", result="Posted (message 1.2).",
                                  steps=[{"kind": "slack", "do": "delete", "channel": "C1",
                                          "ts": "1.2"}])
        feed = {f["id"]: f for f in unrestricted.feed(who)}
        expect(feed[row.id]["can_undo"] and "Posted" in feed[row.id]["result"],
               f"the released row has no Undo after it ran: {feed[row.id]}")
    finally:
        _set_mode(who, "restricted")
