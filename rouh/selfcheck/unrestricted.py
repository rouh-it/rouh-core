"""The owner's mode switch, Restricted or Unrestricted, checked (`rouh/unrestricted.py`, task 191).

Petar, 20 November 2026: "Add tests for each part". What these prove, each by calling Rouh's own
code the way a run or a page does and looking only at what comes back:

- the switch cannot be written by a tool, a model turn, anything scheduled, a job, or anybody but the
  owner's own press, and no module but the Permissions page's view writes it;
- Unrestricted lets the calls of Decisions 498 and 499 (Cloudflare Email Routing off, and a DNS
  record deleted) straight through, with no decision, and each is in What Rouh did with Undo;
- a run a trusted contact's mail or one of Rouh's own processes started is still held;
- the debris rules of 191-02 package 1.7 work: words typed to a one-program run are the owner's,
  a finished job's approvals are withdrawn after a day, a withdrawn call leaves its bundle, each call
  has its own yes or no, a bundle is named by its own calls, every tool has a class, and read-only
  shell commands are reads while chained ones stay risky;
- what is still asked in every mode is still asked.

Every person, address and zone here is made up, on .example domains. Nothing reaches a service: a
tool's own handler is stood in for while it is called.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from . import check, expect

CODE = Path(__file__).resolve().parent.parent.parent

#: The two calls job fb0023a2 made on 19 November 2026 that became Decisions 498 and 499.
CALL_498 = ("cloudflare", {"action": "email_routing_disable", "zone": "rouh-check.example"})
CALL_499 = ("cloudflare", {"action": "dns_delete", "zone": "rouh-check.example",
                           "record": {"type": "MX", "name": "rouh-check.example",
                                      "content": "mx.mail.example"}})


def _owner():
    """The installation's owner in the throwaway database: the default organisation's first admin."""
    from rouh import accounts, telegram, tenancy
    from rouh.models import User

    t = tenancy.Tenancy()
    owner = telegram.phone_owner(t)
    if owner is None:
        if not User.objects.filter(username="check-owner").exists():
            accounts.add_user("check-owner", "pw-check-owner-Example-123",
                              email="owner@rouh-check.example", org_id=tenancy.DEFAULT_ORG_ID,
                              is_org_admin=True)
        owner = telegram.phone_owner(t)
    expect(owner is not None, "no owner could be made in the throwaway database")
    return owner


def _set_mode(who, mode: str, how: str = "until_back", until=None) -> None:
    """The mode written straight into the row, as only a check may: a press is tested apart."""
    from rouh import run_access
    from rouh.models import PermissionMode

    at, how = time.time(), how if mode == "unrestricted" else ""
    uid, org = str(who.user_id), str(who.org_id or "")
    # Sealed as a press seals it (task 191), or the tripwire would take it for a forged mode.
    PermissionMode.objects.update_or_create(
        user_id=uid, org_id=org,
        defaults={"mode": mode, "how": how, "until": until, "set_at": at, "set_by": "a check",
                  "seal": run_access.seal(org, uid, mode, how, until, at)})


def _run(run_id: str, who, *, made_by: str = "", words: str = "Fix the sign-in mail of "
         "rouh-check.example: do all of the ones you can", state: str = "running") -> None:
    from rouh.models import Run, RunWords

    now = time.time()
    Run.objects.update_or_create(id=run_id, defaults={"title": f"check {run_id}", "state": state,
                                                      "started_at": now, "made_by": made_by,
                                                      "ended_at": None if state == "running" else now})
    if words:
        RunWords.objects.get_or_create(run_id=run_id, words=words, defaults={
            "user_id": str(who.user_id), "org_id": str(who.org_id or ""), "how": "started",
            "at": now})


class _Registry:
    """A stand-in for the tool registry a job's call reaches: it records, and does nothing."""

    def __init__(self, names):
        self.ran = []
        self._handlers = {n: object() for n in names}

    async def call(self, name, args, _emit):
        from rouh import unrestricted

        self.ran.append(name)
        if name == "cloudflare":
            # As the real tool keeps the record it changes (`cloudflare.ZoneAPI._undo`).
            unrestricted.note_undo({"kind": "cloudflare", "zone": args.get("zone"),
                                    "ops": [{"do": "email_enable"}]})
        return f"{name} done (a stand-in)"

    def definitions(self):
        return [{"name": n, "input_schema": {"type": "object"}} for n in self._handlers]


def _gateway_call(scope, name, args, names=("cloudflare", "slack_send", "send_mail",
                                            "share_drive_file", "delete_contact", "payments")):
    from rouh import job_gateway

    reg = _Registry(names)
    before = job_gateway.hooks.registry
    job_gateway.hooks.registry = reg
    try:
        return asyncio.run(job_gateway.call(scope, name, dict(args))), reg.ran
    finally:
        job_gateway.hooks.registry = before


def _scope(who, run_id, kind=None, verified=True):
    from rouh import job_gateway, job_policy as policy

    return job_gateway.Scope(kind or policy.OWNER, who, run_id, f"check {run_id}", (), frozenset(),
                             "", [run_id], verified=verified)


# --- 1. The switch is the owner's press, and nothing else --------------------------------------


@check("unrestricted", "no tool or turn can switch the mode",
       "the mode is written only through the owner's press: a tool call, a scheduled turn, a job and "
       "a made-up press are all refused, and no module but the Permissions view writes it", needs_db=True)
def switch_is_the_owners() -> None:
    from rouh import job_policy as policy, protected, unrestricted

    who = _owner()
    _set_mode(who, "restricted")
    # No other module calls the writer or makes a press.
    writers = []
    for path in list((CODE / "rouh").rglob("*.py")) + list((CODE / "one").rglob("*.py")):
        rel = path.relative_to(CODE).as_posix()
        if rel in ("rouh/unrestricted.py", "rouh/web/permissions.py") or rel.startswith("rouh/selfcheck/"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"unrestricted\.flip\(|OwnerPress\.of\(|PermissionMode\.objects\.(update|create|"
                     r"update_or_create|bulk|filter\([^)]*\)\.update)", text):
            writers.append(rel)
    expect(not writers, "these write the mode outside the Permissions view: " + ", ".join(writers))
    # A press cannot be made up.
    try:
        unrestricted.OwnerPress(object(), who)
        expect(False, "a press was made without the owner's request")
    except unrestricted.NotAPress:
        pass
    # Nor made inside a tool call, a scheduled turn, or by a job.
    for var, value, what in ((unrestricted.CALLING, "agent_instructions", "a tool call"),
                             (protected.UNATTENDED, True, "a scheduled turn")):
        token = var.set(value)
        try:
            unrestricted.OwnerPress.of(None, who)
            expect(False, f"a press was accepted inside {what}")
        except unrestricted.NotAPress:
            pass
        finally:
            var.reset(token)
    for name in ("permission_mode", "set_permission_mode", "unrestricted"):
        ruling = policy.decide(policy.OWNER, name, {"mode": "unrestricted"})
        expect(ruling.verdict == policy.REFUSE, f"a job's {name} was not refused: {ruling.verdict}")
    expect(unrestricted.current(who).mode == "restricted", "the mode moved without a press")


@check("unrestricted", "only the owner's own press in the page switches it",
       "a signed-in POST of the owner's switches the mode and logs the flip; somebody else's is "
       "refused; a GET changes nothing", needs_db=True)
def press_in_the_page() -> None:
    from django.test import Client
    from rouh import accounts, tenancy, unrestricted
    from rouh.models import PermissionModeFlip, User

    who = _owner()
    _set_mode(who, "restricted")
    owner = User.objects.get(pk=int(who.user_id))
    c = Client(HTTP_HOST="localhost")
    c.force_login(owner)
    before = PermissionModeFlip.objects.filter(user_id=str(who.user_id)).count()
    r = c.post("/api/permissions", {"mode": "unrestricted", "how": "hours", "hours": 2},
               content_type="application/json")
    expect(r.status_code == 200, f"the owner's press was answered {r.status_code}: {r.content[:200]!r}")
    now = unrestricted.current(who)
    expect(now.unrestricted and now.until and now.until > time.time() + 3500,
           f"the press did not make it Unrestricted for 2 hours: {now.as_dict()}")
    expect(PermissionModeFlip.objects.filter(user_id=str(who.user_id)).count() == before + 1,
           "the flip was not written down")
    # Somebody else, even signed in, cannot.
    t = tenancy.Tenancy()
    if not User.objects.filter(username="check-guest-member").exists():
        accounts.add_user("check-guest-member", "pw-check-guest-Example-123",
                          org_id=tenancy.DEFAULT_ORG_ID, is_org_admin=False)
    other = User.objects.get(username="check-guest-member")
    c2 = Client(HTTP_HOST="localhost")
    c2.force_login(other)
    r = c2.post("/api/permissions", {"mode": "restricted"}, content_type="application/json")
    expect(r.status_code == 403, f"somebody else's press was answered {r.status_code}")
    expect(unrestricted.current(who).unrestricted, "somebody else's press changed the mode")
    _ = t
    r = c.post("/api/permissions", {"mode": "restricted"}, content_type="application/json")
    expect(r.status_code == 200 and not unrestricted.current(who).unrestricted,
           "the owner could not switch it back")
    # Some hours end by themselves.
    _set_mode(who, "unrestricted", "hours", until=time.time() - 5)
    expect(not unrestricted.current(who).unrestricted, "an Unrestricted whose hours ended still held")


# --- 2. Unrestricted lets the 498/499 calls through ------------------------------------------


@check("unrestricted", "Unrestricted runs the calls of Decisions 498 and 499 at once",
       "in the owner's own live run, Email Routing off and a DNS record deleted run with no decision, "
       "and each is in What Rouh did with Undo; in Restricted the same calls wait", needs_db=True)
def lets_498_499_through() -> None:
    from rouh import unrestricted
    from rouh.models import HeartbeatApproval, UnrestrictedAction

    who = _owner()
    _run("check-498", who)
    _set_mode(who, "unrestricted")
    try:
        queued = HeartbeatApproval.objects.filter(duty="job:check-498").count()
        for name, args in (CALL_498, CALL_499):
            got, ran = _gateway_call(_scope(who, "check-498"), name, args)
            expect(got.get("unrestricted") and name in ran,
                   f"{args.get('action')} did not run under Unrestricted: {got.get('text', '')[:300]}")
        expect(HeartbeatApproval.objects.filter(duty="job:check-498").count() == queued,
               "a decision was made under Unrestricted")
        rows = list(UnrestrictedAction.objects.filter(where="check-498").order_by("-id")[:2])
        expect(len(rows) == 2 and all((r.undo or {}).get("steps") for r in rows),
               "What Rouh did does not hold both calls with their undo")
        feed = unrestricted.feed(who)
        expect(any(f["can_undo"] and f["where"] == "check-498" for f in feed),
               "the feed offers no Undo for them")
    finally:
        _set_mode(who, "restricted")
    got, ran = _gateway_call(_scope(who, "check-498"), *CALL_498)
    expect(got.get("pending") and not ran, "in Restricted the call ran without a yes")


# --- 3. Strangers', contacts' and processes' runs are held ------------------------------------


@check("unrestricted", "a run nobody of the owner's started is still held",
       "under Unrestricted, a contact's run, a process's run, an ended run and a run with no words "
       "of the owner's get nothing: their calls wait or are refused", needs_db=True)
def strangers_held() -> None:
    from rouh import job_policy as policy, unrestricted

    who = _owner()
    _set_mode(who, "unrestricted")
    try:
        _run("check-contact", who, words="")
        why = asyncio.run(unrestricted.for_job(_scope(who, "check-contact", policy.CONTACT)))
        expect(why, "a contact's run got Unrestricted")
        got, ran = _gateway_call(_scope(who, "check-contact", policy.CONTACT), *CALL_498)
        expect(not got.get("unrestricted") and not ran, "a contact's run's call ran")
        _run("check-process", who, made_by="process:heartbeat", words="")
        why = asyncio.run(unrestricted.for_job(_scope(who, "check-process", policy.PROCESS)))
        expect(why, "a process's run got Unrestricted")
        _run("check-ended", who, state="done")
        why = asyncio.run(unrestricted.for_job(_scope(who, "check-ended")))
        expect(why, "an ended run got Unrestricted")
        _run("check-nowords", who, words="")
        why = asyncio.run(unrestricted.for_job(_scope(who, "check-nowords")))
        expect(why, "a run with no words of the owner's got Unrestricted")
        expect(not unrestricted.for_chat(who), "a turn nobody started got Unrestricted")
    finally:
        _set_mode(who, "restricted")


# --- 4. What still asks, in every mode --------------------------------------------------------


@check("unrestricted", "what every mode still asks is still asked",
       "under Unrestricted, money not checked against the caps, deleting for good and access for "
       "an outsider still wait for the owner's yes", needs_db=True)
def still_asks() -> None:
    from rouh import unrestricted

    who = _owner()
    expect(unrestricted.still_asks("payments", {"action": "charge", "amount": 900}, who),
           "a payment was not kept for the owner")
    expect(unrestricted.still_asks("delete_contact", {"contact_id": "x"}, who),
           "deleting a contact for good was not kept for the owner")
    expect(unrestricted.still_asks("share_drive_file", {"file_id": "f", "email": "eve@stranger.example",
                                                         "role": "writer"}, who),
           "sharing with an outsider was not kept for the owner")
    expect(not unrestricted.still_asks(*CALL_499, who), "a DNS record Undo can make again was held")
    expect(not unrestricted.still_asks(*CALL_498, who), "Email Routing off was held")
    _run("check-asks", who)
    _set_mode(who, "unrestricted")
    try:
        got, ran = _gateway_call(_scope(who, "check-asks"), "delete_contact", {"contact_id": "x"},
                                 names=("delete_contact",))
        expect(not got.get("unrestricted") and "delete_contact" not in ran,
               "deleting a contact ran under Unrestricted")
    finally:
        _set_mode(who, "restricted")


# --- 5. The debris of 191-02 package 1.7 ------------------------------------------------------


@check("unrestricted", "words typed to a one-program run are the owner's",
       "what the owner typed or said to a run from their own devices is read as theirs; what Rouh's "
       "device, the program or the run wrote is not")
def typed_words() -> None:
    from rouh import his_word

    entries = [
        {"kind": "run.requested", "by": "rouh-ab12", "body": {"brief": "Rouh's own brief"}},
        {"kind": "message.sent", "by": "laptop-browser-1f", "body": {"text": "do all of the ones you can"}},
        {"kind": "message.sent", "by": "program", "body": {"text": "carried on"}},
        {"kind": "message.sent", "by": "run", "body": {"text": "the run's own"}},
        {"kind": "message.queued", "by": "phone-9a", "body": {"text": "and switch email routing off"}},
        {"kind": "tool.closed", "by": "run", "body": {"text": "not words"}},
    ]
    got = his_word.typed_of(entries, "rouh-ab12")
    expect(got == ["do all of the ones you can", "and switch email routing off"],
           f"typed words read as {got}")


@check("unrestricted", "a finished job's approvals are withdrawn after a day",
       "an approval whose job ended more than 24 hours ago is withdrawn, one whose job is still going "
       "waits on", needs_db=True)
def stale_withdrawn() -> None:
    from rouh import heartbeat, job_gateway
    from rouh.models import HeartbeatApproval, Run

    who = _owner()
    _run("check-old", who, state="done")
    Run.objects.filter(id="check-old").update(ended_at=time.time() - 30 * 3600)
    _run("check-live", who)
    mine = (str(who.user_id), str(who.org_id or ""))
    old = heartbeat.queue(None, mine, tool="slack_send", args={"text": "old"}, what="Send an old note",
                          to_whom="", why="a check", cost="", blocking=False, duty="job:check-old")
    live = heartbeat.queue(None, mine, tool="slack_send", args={"text": "live"}, what="Send a note",
                           to_whom="", why="a check", cost="", blocking=False, duty="job:check-live")
    gone = job_gateway.expire_stale(who)
    expect(int(old) in gone, "the old job's approval was not withdrawn")
    expect(HeartbeatApproval.objects.get(id=live).state == "waiting", "a live job's approval was withdrawn")
    expect(HeartbeatApproval.objects.get(id=old).state == job_gateway.WITHDRAWN, "not marked withdrawn")


@check("unrestricted", "a withdrawn call leaves its bundle, and each call has its own yes or no",
       "a job takes one call back in code; the bundle that is left lists only its own calls, is named "
       "by them, and holds one item per call answered yes or no", needs_db=True)
def bundles() -> None:
    from rouh import decision_sources, heartbeat, job_gateway
    from rouh.models import HeartbeatApproval

    who = _owner()
    _run("check-bundle", who)
    # A run of the checks before, in the same throwaway database, left its own calls.
    HeartbeatApproval.objects.filter(duty="job:check-bundle").delete()
    mine = (str(who.user_id), str(who.org_id or ""))
    q = lambda tool, what, to="": heartbeat.queue(  # noqa: E731
        None, mine, tool=tool, args={"what": what}, what=f"{what}, for job check-bundle",
        to_whom=to, why="a check", cost="", blocking=False, duty="job:check-bundle")
    slack = q("slack_send", "Send a Slack note", "ivaylo@team.example")
    cf1 = q("cloudflare", "Switch Email Routing off")
    cf2 = q("cloudflare", "Delete an MX record")
    got = job_gateway.withdraw(_scope(who, "check-bundle"), {"withdraw": True, "tool": "slack_send"})
    expect(got.get("ok") and HeartbeatApproval.objects.get(id=slack).state == job_gateway.WITHDRAWN,
           f"the call could not be taken back: {got}")
    calls = [a for a in heartbeat.waiting(who) if a.duty == "job:check-bundle"]
    ask = decision_sources.ApprovalSource()._job_calls(sorted(calls, key=lambda a: a.id))
    ids = {int(i["id"]) for i in ask.items}
    expect(ids == {cf1, cf2}, f"the bundle holds {ids}, not the two calls left")
    expect("ivaylo" not in (ask.title + ask.why + ask.risk_note).lower(),
           f"the bundle is still named by the call taken back: {ask.title}")
    expect(ask.title.startswith("2 calls: Switch Email Routing off; Delete an MX record"),
           f"the bundle is not named by its own calls: {ask.title}")
    expect({o["id"] for o in ask.options} == {"yes", "no"} and all(o.get("each") for o in ask.options),
           "the bundle's calls cannot each be answered yes or no")


@check("unrestricted", "every tool has a class, and read-only shell commands are reads",
       "every tool the registry lists to a job is in one of the policy's tables; ls, grep and their "
       "pipelines are reads, and a chained or redirected command stays risky")
def every_tool_classified() -> None:
    from rouh import job_policy as policy, runtime

    # What the gateway lists: the registry's tools Rouh's own code runs (`job_gateway.tools_for`),
    # never a provider's server tools such as its web search.
    reg = runtime.tools
    missing = sorted(d.get("name", "") for d in reg.definitions()
                     if d.get("name", "") in reg._handlers and policy.listed(d.get("name", ""))
                     and not policy.known(d.get("name", "")))
    expect(not missing, "tools with no class: " + ", ".join(missing))
    for command in ("ls /data/rouh/logs", "grep -rn timeout /code/rouh | head -20", "ps aux | grep python"):
        expect(policy.classify("run_command", {"command": command}) == policy.READ,
               f"{command!r} is not a read")
    for command in ("ls; rm x", "cat a > b", "ls && rm -rf /", "find . -delete", "sort -o out in",
                    "cat $HOME/.env", "echo `id`"):
        expect(policy.classify("run_command", {"command": command}) == policy.RISKY,
               f"{command!r} is not risky")
    for name, args in (("find_slides", {}), ("incubator_list", {}), ("page_asks", {}),
                       ("comments_by", {}), ("trials", {"action": "list"}), ("payments", {}),
                       ("cloudflare", {"action": "email_routing_status"})):
        expect(policy.classify(name, args) == policy.READ, f"{name} is not a read")
