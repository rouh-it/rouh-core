"""One switch, Restricted or Unrestricted: what the owner's own chats and runs may do without asking.

Petar, 20 November 2026 (task 191): "we aim at unblocking the things that slow me down. Things I
asked and I got a NO, I CAN'T or something like that... maybe we should go for something like 2
modes. restricted and unrestricted ... in unrestricted mode we should remove the barriers that cost
something and keep the protections that don't cost my time and usability... I want to see toggle
for unrestricted mode."

**The switch.** One row per person (`models.PermissionMode`), Restricted when there is none. It is
written in one place, `flip`, and `flip` takes an `OwnerPress`, which only `OwnerPress.of` makes,
from a signed-in web request of the installation's owner that is a POST through Django's CSRF check
(`rouh/web/permissions.py`). No tool, model turn, scheduled turn, heartbeat beat, mail turn or job
can make one: `of` refuses inside any of them (`_why_not_here`), there is no tool for it in the
registry, and every job gateway name for it is `NEVER` (`job_policy.NEVERS`). Every flip is a row
of `models.PermissionModeFlip`, in the same transaction. It lasts some hours (it ends by itself and
Restricted is back), until switched back, or permanently.

**What Unrestricted does, for the owner's own chats and runs only** (`for_job`, `for_chat`):

- the job gateway runs a risky call at once, with no decision and no judge (`job_gateway._pend`):
  Cloudflare, run_command, server work, self-change and deploy, mail, Slack and Drive actions, and
  tools nobody has classified;
- the owner's own "ask me first" gates and an MCP server's Ask first are not asked in their own
  chat (`tools.ToolRegistry.call`); the server's own ROUH_CONFIRM_TOOLS still is, because only the
  machine's settings can turn those off;
- the model is told which mode it is in (`told`), and in Unrestricted that these calls run.

**Who never gets it.** A run doing a trusted contact's work, a run one of Rouh's processes started
(heartbeat, quests, the nights), a beat, a turn about somebody's mail, a scheduled turn. A run's
scope is decided by Rouh from its run register (`job_gateway.scope_of`), never from what the caller
says; on top of that a run gets Unrestricted only while it is live in the register and only when
Rouh itself recorded words of the owner's behind it (`his_word.words_of_scope`, which includes what
they typed to it in the one program), so an id of an ended run, or of one nobody of theirs started,
gets nothing. Since 20 November 2026 (run b631957c) a run must also show Rouh its own token, which
only the one program holds, in memory, and hands to the run's own processes as the kernel's process
tree says (`one/rundoor.py`, `rouh/run_access.verify`); a run with no token, or another run's,
never gets Unrestricted (`scope.verified`).

**Still asked, even in Unrestricted** (`STILL_ASKS`, `still_asks`): money above the owner's own
payment caps, deleting their data for good, and giving credentials or account access to people
outside. One small list, here, to change later.

**What Rouh did.** Every call that ran because of Unrestricted is one row of
`models.UnrestrictedAction`, shown on the Permissions page, with Undo where the service allows one.
Each tool records how to put back what it changed as it runs (`note_undo`, `UNDO`): Cloudflare
each record as it was (`cloudflare.ZoneAPI`), Drive a file out of the bin, its old name and its old
folders, Calendar a deleted event restored and a changed or moved one's fields and calendar as
Google held them, Gmail labels, archive and the bin, iCloud a contact's card as it was (or a card
Rouh added taken away), and Slack a message Rouh's bot posted deleted (`_put_back`). Where a
service cannot undo, the row says so in plain words (`NO_UNDO`).

**Switching on lets what was waiting through.** `flip` ends with `after_flip`: the approvals
already waiting from the owner's own live runs, except what `STILL_ASKS` keeps, are answered yes
through the decisions' one answer path, each written into What Rouh did, its undo added once it
has run (`ran_released`, from `heartbeat.answer`).

**rouh-open.** Since 20 November 2026 the switch covers all five of rouh-open's items, per run
(`rouh/run_access.py`): while it is Unrestricted, the owner's own live runs get the internet on
any port, GitHub as the owner, and the logins of rouh.land, the relay and the host, from standing
access the host keeps in the keys volume; nothing else gets any of them. rouh-open's own timed
grants still open for some hours, now for the owner's own runs only (`grants_open` reads them).

**The seal.** `flip` writes the mode with a seal made with this Rouh's own key (`run_access.seal`);
`current` opens it, and a mode row that says Unrestricted without the seal of its own press is
taken for what it is, something other than the owner's press, and trips the tripwire back to
Restricted (`run_access.trip`).
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
from dataclasses import dataclass

log = logging.getLogger("rouh.unrestricted")

RESTRICTED, UNRESTRICTED = "restricted", "unrestricted"
MODES = (RESTRICTED, UNRESTRICTED)
HOURS, UNTIL_BACK, PERMANENT = "hours", "until_back", "permanent"
HOWS = (HOURS, UNTIL_BACK, PERMANENT)
#: Hours an Unrestricted of some hours may last.
MOST_HOURS = 72

#: Set around every tool call of a turn (`tools.ToolRegistry.call`): no flip happens inside one.
CALLING: contextvars.ContextVar[str] = contextvars.ContextVar("rouh_unrestricted_calling",
                                                              default="")

#: The undo steps a tool records while it runs, when its caller collects them (`collecting`):
#: [{"kind": "cloudflare", "zone": ..., "ops": [...]}]. A tool appends; nobody else reads it.
UNDO: contextvars.ContextVar[list | None] = contextvars.ContextVar("rouh_unrestricted_undo",
                                                                  default=None)


# --- still asked, in every mode ---------------------------------------------------------------

MONEY_ABOVE_CAPS, DELETES_FOR_GOOD, OUTSIDER_ACCESS = ("money_above_caps", "deletes_for_good",
                                                       "outsider_access")

#: What still waits for the owner's yes when the mode is Unrestricted. Change it here.
STILL_ASKS = {
    MONEY_ABOVE_CAPS: "it spends money, and only a purchase checked in code against your own "
                      "payment caps goes without asking",
    DELETES_FOR_GOOD: "it deletes your data for good",
    OUTSIDER_ACCESS: "it gives credentials or access to an account to somebody outside",
}

#: Tools that spend money only after checking the owner's caps in code, refusing above them
#: (`payments.check_purchase`): these run in Unrestricted; any other money call is asked.
CAPPED_IN_CODE = frozenset({"place_order"})
#: Deletions that can be put back, so they are not "for good": a Cloudflare DNS record (the tool
#: says the record as it was, and Undo makes it again).
RESTORABLE = frozenset({("cloudflare", "dns_delete")})
#: Access calls that take access away rather than give it, or join Rouh itself somewhere.
NOT_GIVING = frozenset({"take_off_files", "slack_join"})
_CREDENTIAL_WORDS = ("token", "password", "credential", "api_key", "secret", "login", "key")


def _addresses(args: dict) -> list[str]:
    from email.utils import getaddresses

    said = []
    for key in ("to", "cc", "bcc", "email", "emails", "people", "members", "share_with", "invite",
                "guests", "who", "user", "users"):
        value = args.get(key)
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v.get("email") if isinstance(v, dict) else v) for v in value)
        if value:
            said.append(str(value))
    return [a.lower() for _n, a in getaddresses(said) if "@" in a]


def _own_domains(who) -> set[str]:
    try:
        from . import heartbeat

        return {a.rsplit("@", 1)[-1] for a in heartbeat._owners((str(who.user_id),
                                                                str(who.org_id or ""))) if "@" in a}
    except Exception:  # noqa: BLE001 - nobody's own is everybody outside
        log.exception("the owner's own domains could not be read")
        return set()


def still_asks(name: str, args: dict | None, who=None) -> str:
    """The `STILL_ASKS` key this call is, or "": what waits for the owner's yes in every mode."""
    from . import his_word

    name = str(name or "").strip()
    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or args.get("act") or "").strip().lower()
    kind = his_word.held(name, args)
    if kind == his_word.MONEY and name not in CAPPED_IN_CODE:
        return MONEY_ABOVE_CAPS
    if kind == his_word.DELETION and (name, action) not in RESTORABLE:
        return DELETES_FOR_GOOD
    said = f"{name} {action} " + " ".join(str(k) for k in args)
    if any(w in said.lower() for w in _CREDENTIAL_WORDS) and kind in (his_word.ACCESS,
                                                                      his_word.RULES):
        return OUTSIDER_ACCESS
    if kind == his_word.ACCESS and name not in NOT_GIVING:
        wanted = _addresses(args)
        own = _own_domains(who) if who is not None else set()
        if not wanted or any(a.rsplit("@", 1)[-1] not in own for a in wanted):
            # Nobody named is nobody known to be inside: asked, on the side of asking.
            return OUTSIDER_ACCESS
    return ""


# --- the mode ---------------------------------------------------------------------------------


@dataclass
class Mode:
    mode: str = RESTRICTED
    how: str = ""
    until: float | None = None
    set_at: float = 0.0
    set_by: str = ""

    @property
    def unrestricted(self) -> bool:
        return self.mode == UNRESTRICTED

    def as_dict(self) -> dict:
        return {"mode": self.mode, "how": self.how, "until": self.until, "set_at": self.set_at,
                "set_by": self.set_by, "said": self.said()}

    def said(self) -> str:
        if not self.unrestricted:
            return "Restricted"
        if self.how == PERMANENT:
            return "Unrestricted, permanently"
        if self.how == UNTIL_BACK or not self.until:
            return "Unrestricted until you switch it back"
        from . import clock

        at = clock.moment(self.until)
        return f"Unrestricted until {at:%H:%M}" + ("" if at.date() == clock.moment(time.time()).date()
                                                   else f" on {at:%A %-d %B}")


def _whose(who) -> dict:
    return {"user_id": str(who.user_id), "org_id": str(getattr(who, "org_id", "") or "")}


def current(who, now: float | None = None) -> Mode:
    """The mode now for this person. Restricted when nothing is set, when an Unrestricted of some
    hours has ended, and when it cannot be read: fails closed. Never raises."""
    if who is None:
        return Mode()
    try:
        from .models import PermissionMode

        row = PermissionMode.objects.filter(**_whose(who)).first()
    except Exception:  # noqa: BLE001
        log.exception("the mode could not be read")
        return Mode()
    if row is None or row.mode != UNRESTRICTED:
        return Mode(set_at=getattr(row, "set_at", 0.0) or 0.0, set_by=getattr(row, "set_by", "") or "")
    from . import run_access

    if not run_access.seal_ok(row):
        # Unrestricted with no seal of the owner's press: something else wrote it (task 191).
        run_access.trip("the mode said Unrestricted, but the owner's press did not write it",
                        by="the mode's seal", who=who)
        return Mode(set_at=time.time(), set_by="the tripwire")
    moment = time.time() if now is None else now
    if row.how == HOURS and (not row.until or row.until <= moment):
        return Mode(set_at=row.until or row.set_at, set_by="its hours ended")
    return Mode(UNRESTRICTED, row.how, row.until, row.set_at, row.set_by)


def owner_mode(now: float | None = None) -> Mode:
    """The installation owner's mode (`telegram.phone_owner`), for code that has no person."""
    try:
        from . import telegram
        from .tenancy import Tenancy

        return current(telegram.phone_owner(Tenancy()), now)
    except Exception:  # noqa: BLE001
        log.exception("the owner's mode could not be read")
        return Mode()


class NotAPress(PermissionError):
    """Something other than the owner's own press in the web page tried to change the mode."""


_PRESS = object()


class OwnerPress:
    """Proof that the installation's owner pressed the switch in the web page. Only `of` makes one."""

    def __init__(self, key, who, agent: str = "") -> None:
        if key is not _PRESS:
            raise NotAPress("The mode is changed only by the owner's own press on the "
                            "Permissions page.")
        self.who = who
        self.agent = str(agent or "")[:200]

    @classmethod
    def of(cls, request, me) -> "OwnerPress":
        """From a signed-in POST of the owner's, which Django's CSRF check let through. Raises
        `NotAPress` for anything else."""
        why = _why_not_here()
        if why:
            raise NotAPress(why)
        if request is None or getattr(request, "method", "") != "POST":
            raise NotAPress("Only a press in the page changes the mode.")
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False) or getattr(user, "is_guest", False):
            raise NotAPress("Sign in first.")
        if me is None or not getattr(me, "is_admin", False) or not _is_owner(me):
            raise NotAPress("Only the owner of this Rouh can change its mode.")
        return cls(_PRESS, me, request.headers.get("user-agent", ""))


def _is_owner(me) -> bool:
    try:
        from . import telegram
        from .tenancy import Tenancy

        owner = telegram.phone_owner(Tenancy())
        return owner is not None and str(owner.user_id) == str(me.user_id)
    except Exception:  # noqa: BLE001 - nobody known is nobody allowed
        log.exception("whether this is the owner could not be read")
        return False


def _why_not_here() -> str:
    """Why the mode may not change from where this code is running, or "": inside a tool call, a
    scheduled turn, a beat, a mail turn or a job's gateway call, it never may."""
    from . import heartbeat, mail_turn, protected

    if CALLING.get():
        return f"The mode cannot be changed from a tool ({CALLING.get()})."
    if protected.UNATTENDED.get():
        return "The mode cannot be changed by anything scheduled."
    if heartbeat.BEAT.get() is not None:
        return "The mode cannot be changed by the heartbeat."
    if mail_turn.now() is not None:
        return "The mode cannot be changed by a turn about somebody's message."
    return ""


def flip(press: OwnerPress, mode: str, how: str = "", hours: float | None = None) -> Mode:
    """Set the mode, on the owner's own press, and write the flip down. The only writer."""
    if not isinstance(press, OwnerPress) or getattr(press, "who", None) is None:
        raise NotAPress("The mode is changed only by the owner's own press on the Permissions page.")
    why = _why_not_here()
    if why:
        raise NotAPress(why)
    if mode not in MODES:
        raise ValueError("The mode is restricted or unrestricted.")
    until = None
    if mode == UNRESTRICTED:
        if how not in HOWS:
            raise ValueError("Say how long: some hours, until switched back, or permanently.")
        if how == HOURS:
            try:
                hours = float(hours)
            except (TypeError, ValueError):
                raise ValueError("How many hours?") from None
            if not 0 < hours <= MOST_HOURS:
                raise ValueError(f"From 1 to {MOST_HOURS} hours.")
            until = time.time() + hours * 3600
    else:
        how = ""
    from django.db import transaction

    from .models import PermissionMode, PermissionModeFlip

    who = press.who
    was = current(who)
    now = time.time()
    by = "the owner on the Permissions page"
    from . import run_access

    whose = _whose(who)
    sealed = run_access.seal(whose["org_id"], whose["user_id"], mode, how, until, now)
    with transaction.atomic():
        PermissionMode.objects.update_or_create(
            **whose, defaults={"mode": mode, "how": how, "until": until, "set_at": now,
                               "set_by": by, "seal": sealed})
        PermissionModeFlip.objects.create(**_whose(who), was=was.mode, now=mode, how=how,
                                          until=until, at=now, by=by, agent=press.agent)
    log.info("the mode was switched from %s to %s (%s%s) by the owner's press", was.mode, mode,
             how or "-", f", until {until:.0f}" if until else "")
    after_flip(who, was, current(who))
    return current(who)


def after_flip(who, was: Mode, now: Mode) -> list[int]:
    """What a flip does at once, after it is written: switched to Unrestricted (or its length
    changed while it is on), the approvals already waiting from the owner's own live runs go
    through, as they would have had they been asked now, except what every mode still asks
    (`STILL_ASKS`). Each is answered yes through the one answer path (`decisions.answer`) and
    written into What Rouh did; its undo is added when it has run (`ran_released`).

    Never released: a trusted contact's run, a mail run, a run one of Rouh's processes started,
    a beat of the heartbeat, the heartbeat's own queue, a run that is not live, one with no words
    of the owner's behind it, and a job's ask for something only the owner can give (no tool).
    The approval ids it let through. Never raises: the flip stands whatever happens here."""
    if not now.unrestricted:
        return []
    try:
        return _release(who)
    except Exception:  # noqa: BLE001 - they wait, as before
        log.exception("the approvals waiting when the mode was switched could not be let through")
        return []


def _releasable(who) -> dict:
    """{approval id: (approval row, its job's scope)}: what `after_flip` lets through."""
    from . import his_word, job_gateway, job_policy as policy
    from .models import HeartbeatApproval

    rows = (HeartbeatApproval.objects.filter(**_whose(who), state="waiting",
                                             duty__startswith=job_gateway.DUTY)
            .exclude(tool="").order_by("id"))
    scopes: dict = {}
    out = {}
    for a in rows:
        job = str(a.duty)[len(job_gateway.DUTY):]
        if job not in scopes:
            scope, _why = job_gateway.scope_of(job)
            mine = (scope is not None and scope.kind == policy.OWNER
                    and str(scope.who.user_id) == str(who.user_id) and _live(scope.run)
                    and bool(his_word.words_of_scope(scope)))
            scopes[job] = scope if mine else None
        scope = scopes[job]
        if scope is None or still_asks(a.tool, a.args or {}, who):
            continue
        out[a.id] = (a, scope)
    return out


def _holding(who, ids) -> list:
    """[(open decision, [approval ids of `ids` it holds])], each decision once."""
    from . import decisions
    from .models import Decision

    found = []
    for d in Decision.objects.filter(**_whose(who), source="approval",
                                     status__in=decisions.ANSWERABLE).order_by("id"):
        held = [int(p["approval"]) for p in d.prepared or []
                if isinstance(p, dict) and str(p.get("approval") or "").isdigit()]
        if not held and str(d.source_id or "").isdigit():
            held = [int(d.source_id)]
        mine = [i for i in held if i in ids]
        if mine:
            found.append((d, mine))
    return found


def _release(who) -> list[int]:
    from . import decisions

    free = _releasable(who)
    if not free:
        return []
    found = _holding(who, free)
    if set(free) - {i for _d, ids in found for i in ids}:
        # A call queued a moment ago may not be a decision yet: brought level first.
        decisions.sync(who, kinds=["approval"], by="the switch to Unrestricted")
        found = _holding(who, free)
    out = []
    for d, ids in found:
        try:
            if d.items:
                items = {str(i): "yes" for i in ids
                         if any(str(it.get("id")) == str(i) for it in d.items or [])}
                got = decisions.answer(who, d.id, items=items, confirm=d.risk, channel="screen")
            else:
                got = decisions.answer(who, d.id, choice=["yes"], confirm=d.risk, channel="screen")
        except Exception:  # noqa: BLE001 - this one waits, the rest go on
            log.exception("decision %s could not be answered by the switch", d.id)
            continue
        called = decisions.name_of(got.get("decision") or d)
        for i in ids:
            a, scope = free[i]
            record(who, via="job", where=scope.run, title=scope.title, tool=a.tool,
                   args=a.args or {}, what=" ".join(str(a.what or "").split()) or f"Run {a.tool}",
                   why="It was waiting for your yes when you switched to Unrestricted, so the "
                       f"switch answered yes to it ({called}).",
                   result="Answered yes; it runs exactly as queued.", approval=i)
            out.append(i)
    if out:
        log.info("the switch to Unrestricted let %d waiting approval(s) through: %s", len(out), out)
    return out


def flips(who, most: int = 30) -> list[dict]:
    from .models import PermissionModeFlip

    rows = PermissionModeFlip.objects.filter(**_whose(who)).order_by("-at", "-id")[:most]
    return [{"was": r.was, "now": r.now, "how": r.how, "until": r.until, "at": r.at, "by": r.by}
            for r in rows]


# --- who gets it ------------------------------------------------------------------------------

#: The run register's states of a run that is still going.
LIVE = ("running", "waiting", "idle", "starting", "queued")


def _live(run_id: str) -> bool:
    from .models import Crewmate, Run

    state = Run.objects.filter(id=run_id).values_list("state", flat=True).first()
    if state is not None:
        return state in LIVE
    status = Crewmate.objects.filter(id=run_id).values_list("status", flat=True).first()
    return status is not None and status in ("running", "waiting", "starting", "queued")


async def for_job(scope) -> str:
    """"" when this job's risky calls run under Unrestricted now, else why not, in a few words."""
    import asyncio

    from . import his_word, job_policy as policy

    if scope is None or scope.kind != policy.OWNER:
        return "only the owner's own runs get Unrestricted"
    if not getattr(scope, "verified", False):
        # The run showed no token of its own that the one program vouches for (rouh/run_access.py).
        return "this run's identity could not be checked with the one program"
    mode = await asyncio.to_thread(current, scope.who)
    if not mode.unrestricted:
        return "the mode is Restricted"
    try:
        if not await asyncio.to_thread(_live, scope.run):
            return "this run is not live in Rouh's register"
        words = await his_word.words_of_scope_now(scope)
    except Exception:  # noqa: BLE001 - fails closed
        log.exception("whether job %s gets Unrestricted could not be read", scope.run)
        return "whether this run is the owner's could not be read"
    if not words:
        return "Rouh has no words of the owner's behind this run"
    return ""


def for_chat(who) -> bool:
    """Whether a tool call in this turn runs under Unrestricted: the owner's own live chat only."""
    from . import heartbeat, mail_turn, protected, signups

    if who is None or not signups.PERSON_TURN.get() or protected.UNATTENDED.get() or \
            heartbeat.BEAT.get() is not None or mail_turn.now() is not None:
        return False
    return _is_owner(who) and current(who).unrestricted


def told(who) -> str:
    """What the model is told about the mode, for its instructions (a chat's, or a job's tools)."""
    mode = current(who) if who is not None else Mode()
    if not mode.unrestricted:
        return ("Permissions mode: Restricted. A call that sends, shares, publishes, pays, deletes "
                "or changes something outside your own work may wait for the owner's yes.")
    return (f"Permissions mode: {mode.said()}, switched on by the owner. Do what they ask: "
            "Cloudflare, commands on the server, changes to Rouh itself and deploys, mail, Slack "
            "and Drive actions run at once, with no decision and nobody asked, and each is written "
            "into What Rouh did with its undo. Do not say you cannot or need their permission for "
            "these. Still asked in every mode: " + "; ".join(STILL_ASKS.values()) + ".")


def told_for_turn() -> str:
    """`told` for the turn being answered: Unrestricted only in the owner's own live chat."""
    from .tenancy import SPEAKER

    try:
        who = SPEAKER.get()
        if for_chat(who):
            return told(who)
    except Exception:  # noqa: BLE001 - told Restricted
        log.exception("the mode could not be told")
    return told(None)


# --- what Rouh did ----------------------------------------------------------------------------


def collecting() -> list:
    """A fresh list for this call's undo steps (`UNDO`), set for what runs from here."""
    got: list = []
    UNDO.set(got)
    return got


def collecting_now() -> bool:
    """Whether a caller collects undo steps for the call running now: a tool reads what it is
    about to change only then, so a call nobody records costs nothing more."""
    return UNDO.get() is not None


def note_undo(step: dict) -> None:
    """A tool says how to undo what it just did. Nothing happens unless a caller collects.

    The kinds `undo` can put back, each recorded by the tool as it runs:
    - "cloudflare" {zone, ops}: each DNS record, setting and Email Routing as it was;
    - "drive" {do: "untrash" | "rename" | "reparent", id, ...}: out of the bin, its old name, its
      old folders;
    - "calendar" {do: "restore" | "fields" | "move", calendar, id, ...}: a deleted event restored,
      a changed one's fields as Google held them, a moved one moved back;
    - "gmail" {do: "untrash" | "labels", id, add, remove}: out of the bin, labels and archive back;
    - "contact" {do: "card" | "remove", href, ...}: the card as it was, or a card Rouh added
      taken away;
    - "slack" {do: "delete", channel, ts}: a message Rouh's bot posted, deleted."""
    got = UNDO.get()
    if got is not None and isinstance(step, dict):
        got.append(step)


#: What a row says when its call kept nothing to put back, by tool, in plain words.
NO_UNDO = {
    "send_mail": "No undo: an email that has gone cannot be called back.",
    "forward_mail": "No undo: an email that has gone cannot be called back.",
    "forward_thread": "No undo: an email that has gone cannot be called back.",
    "send_telegram": "No undo: a Telegram message Rouh sent stays sent.",
    "run_command": "No undo: what a command changed on the server is not kept to put back.",
    "deploy_myself": "No undo here: a deploy is put back by deploying the commit before it.",
    "improve_myself": "No undo here: a change to Rouh is put back by reverting its commit.",
    "share_drive_file": "No undo here: take the access away again with take_off_files.",
}


def _masked(args) -> str:
    from . import redaction

    try:
        text = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(args)
    try:
        return redaction.scrub(text)[:4000]
    except Exception:  # noqa: BLE001
        return text[:4000]


def record(who, *, via: str, where: str, title: str, tool: str, args, what: str, why: str,
           result: str, ok: bool = True, undo: list | None = None, approval: int = 0) -> int:
    """One call that ran because of Unrestricted, for What Rouh did. Never raises.

    `approval` is a waiting approval let through by the switch (`after_flip`): it has not run
    yet, so its undo comes when it does (`ran_released`)."""
    try:
        from .models import UnrestrictedAction

        steps = [u for u in undo or [] if isinstance(u, dict)]
        said = "" if steps else (
            "Undo comes here once it has run, wherever the service keeps what was there before."
            if approval else _no_undo(tool) if ok else "Nothing ran, so there is nothing to undo.")
        if isinstance(args, dict) and args.get("action") and (not what or what.startswith("Using ")):
            what = f"{tool}: {str(args['action']).replace('_', ' ')}" + (
                f" on {args['zone']}" if args.get("zone") else "")
        row = UnrestrictedAction.objects.create(
            **_whose(who), via=via, where=str(where)[:120], title=str(title)[:300], tool=tool,
            args=_masked(args), what=str(what)[:600], why=str(why)[:1000],
            result=str(result)[:4000], ok=bool(ok),
            undo=({"steps": steps} if steps else {}) | ({"approval": int(approval)} if approval
                                                        else {}),
            undo_said=said, at=time.time())
        return row.id
    except Exception:  # noqa: BLE001
        log.exception("what %s did under Unrestricted could not be written down", tool)
        return 0


def _no_undo(tool: str) -> str:
    return NO_UNDO.get(str(tool or ""), "No undo: nothing it changed was kept to put back.")


def ran(who, ident: int, *, result: str, steps: list | None, ok: bool = True) -> None:
    """A row written before its call ran (a gate not asked in the owner's chat), given what the
    call answered and how to undo it, once it has. Never raises."""
    try:
        from .models import UnrestrictedAction

        got = [u for u in steps or [] if isinstance(u, dict)]
        UnrestrictedAction.objects.filter(**_whose(who), id=int(ident)).update(
            result=str(result)[:4000], ok=bool(ok), undo={"steps": got} if got else {},
            undo_said="" if got else _no_undo(
                UnrestrictedAction.objects.filter(id=int(ident)).values_list("tool", flat=True)
                .first() or ""))
    except Exception:  # noqa: BLE001
        log.exception("what action %s did could not be written onto its row", ident)


def ran_released(row, *, state: str, result: str, steps: list | None) -> None:
    """A waiting approval the switch let through (`after_flip`) has run (`heartbeat.answer`): its
    row of What Rouh did is given the answer and its undo. Nothing for any other approval."""
    try:
        from .models import UnrestrictedAction

        found = UnrestrictedAction.objects.filter(
            user_id=str(row.user_id), org_id=str(row.org_id or ""), undo__approval=int(row.id),
            undone_at=None).first()
        if found is None:
            return
        got = [u for u in steps or [] if isinstance(u, dict)]
        ok = state == "yes"
        UnrestrictedAction.objects.filter(id=found.id).update(
            result=str(result or ("It ran." if ok else "It did not run."))[:4000], ok=ok,
            undo={"approval": int(row.id), **({"steps": got} if got else {})},
            undo_said="" if got else (_no_undo(found.tool) if ok else
                                      "Nothing ran, so there is nothing to undo."))
    except Exception:  # noqa: BLE001
        log.exception("what approval %s did could not be written onto its row", row.id)


def feed(who, most: int = 100) -> list[dict]:
    from .models import UnrestrictedAction

    rows = UnrestrictedAction.objects.filter(**_whose(who)).order_by("-at", "-id")[:most]
    return [{"id": r.id, "via": r.via, "where": r.where, "title": r.title, "tool": r.tool,
             "what": r.what, "why": r.why, "result": r.result[:600], "ok": r.ok,
             "can_undo": bool((r.undo or {}).get("steps")) and r.undone_at is None,
             "undo_said": r.undo_said, "undone_at": r.undone_at, "undone_said": r.undone_said,
             "at": r.at} for r in rows]


def feed_total(who) -> int:
    """How many rows What Rouh did holds in all, so the page can say "the latest 100 of N"."""
    from .models import UnrestrictedAction

    return UnrestrictedAction.objects.filter(**_whose(who)).count()


def _wait(coro, loop=None):
    """Run one of a service's coroutines from this thread: on the server's own loop when one is
    given and running (its clients and locks live there), else on a loop of its own."""
    import asyncio

    if loop is not None and loop.is_running():
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)
    return asyncio.run(coro)


def _google(who):
    from . import runtime

    if runtime.google_desk is None:
        raise RuntimeError("Google is not set up on this Rouh")
    return runtime.google_desk.services_of(who)


def _put_back(who, step: dict, loop=None) -> list[str]:
    """One undo step put back, said in a line or two. Raises when the service refuses."""
    kind, do = step.get("kind"), step.get("do")
    if kind == "cloudflare":
        from . import cloudflare

        api = cloudflare.zone_api(step["zone"], str(who.org_id or ""))
        return api.put_back(step.get("ops") or [])
    if kind == "drive":
        drive = _google(who).drive
        name = step.get("name") or step.get("id")
        if do == "untrash":
            _wait(drive.untrash(step["id"]), loop)
            return [f"{name!r} is out of the Drive bin, where it was"]
        if do == "rename":
            _wait(drive.rename(step["id"], step["name"]), loop)
            return [f"{step.get('now')!r} is called {step['name']!r} again"]
        if do == "reparent":
            _wait(drive.reparent(step["id"], list(step.get("add") or []),
                                 list(step.get("remove") or [])), loop)
            return [f"{name!r} is back in the folder it was in"]
    if kind == "calendar":
        calendar = _google(who).calendar
        title = step.get("title") or "the event"
        if do == "restore":
            got = _wait(calendar.restore(step["calendar"], step["id"], notify=False), loop)
            return [f"{title!r} is restored on the calendar, and nobody was emailed"
                    if got.get("restored") else f"{title!r} was not cancelled, so it stands"]
        if do == "fields":
            _wait(calendar.put_fields(step["calendar"], step["id"], step.get("fields") or {}), loop)
            return [f"{title!r} has its title, place, time, words and guests as they were, "
                    "and nobody was emailed"]
        if do == "move":
            _wait(calendar.move_to(step["calendar"], step["id"], step["back"], notify=False), loop)
            return [f"{title!r} is back on the calendar it was on"]
    if kind == "gmail":
        gmail = _google(who).gmail
        if do == "untrash":
            _wait(gmail.untrash(step["id"]), loop)
            return [f"message {step['id']} is out of the bin"]
        if do == "labels":
            add, remove = list(step.get("add") or []), list(step.get("remove") or [])
            _wait(gmail.modify(step["id"], add=add, remove=remove), loop)
            words = (["back in the inbox"] if "INBOX" in add else []) + \
                (["read again"] if "UNREAD" in remove else []) + \
                (["unread again"] if "UNREAD" in add else []) + \
                (["out of the inbox again"] if "INBOX" in remove else [])
            rest = [x for x in add + remove if x not in ("INBOX", "UNREAD")]
            return [f"message {step['id']}: " + ", ".join(
                words + ([f"its labels as they were ({len(rest)})"] if rest else []))]
    if kind == "contact":
        from . import runtime

        if runtime.contacts is None:
            raise RuntimeError("iCloud contacts are not set up on this Rouh")
        return [_wait(runtime.contacts.put_back(who, step), loop)]
    if kind == "slack":
        from . import slack

        conn = slack.connection(str(who.org_id or ""))
        if conn is None:
            raise RuntimeError("Slack is not connected any more")
        slack.delete_message(conn, channel=step["channel"], ts=step["ts"])
        return [f"the message Rouh posted in {step.get('where') or 'Slack'} is deleted"]
    return [f"no way to undo a {kind!r} step"]


def undo(who, ident: int, loop=None) -> dict:
    """Put back what one row of What Rouh did changed, where its service allows. Sync: run it on a
    thread, and give it the server's loop for the services that are asynchronous."""
    from .models import UnrestrictedAction

    row = UnrestrictedAction.objects.filter(**_whose(who), id=int(ident)).first()
    if row is None:
        return {"ok": False, "said": "There is no such action."}
    if row.undone_at:
        return {"ok": False, "said": "It was undone already."}
    steps = (row.undo or {}).get("steps") or []
    if not steps:
        return {"ok": False, "said": row.undo_said or "It cannot be undone here."}
    said, left = [], list(steps)
    try:
        while left:
            said += _put_back(who, left[-1], loop)
            left.pop()
    except Exception as exc:  # noqa: BLE001 - said, and the row stays undoable
        log.exception("action %s could not be undone", ident)
        if len(left) < len(steps):
            # What was put back is kept off the row, so a second Undo does only the rest.
            UnrestrictedAction.objects.filter(id=row.id).update(
                undo={**(row.undo or {}), "steps": left})
        done = f" What was put back: {'; '.join(said)}." if said else ""
        return {"ok": False, "said": f"It could not be undone: {exc}.{done}"}
    text = "; ".join(said) or "Put back."
    UnrestrictedAction.objects.filter(id=row.id).update(undone_at=time.time(), undone_said=text[:2000])
    return {"ok": True, "said": text}


# --- rouh-open's grants, read only ------------------------------------------------------------


def grants_open(now: float | None = None) -> list[dict]:
    """What the owner's rouh-open has open now, read from the keys volume, never written: [{what,
    until}]. The switch never opens or closes these; each runs to its own end."""
    import os

    moment = time.time() if now is None else now
    root = os.environ.get("ROUH_KEYS_DIR", "/keys")
    out = []

    def load(name):
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    gh = load("github_grant.json")
    if isinstance(gh, dict) and float(gh.get("until") or 0) > moment:
        out.append({"what": "GitHub" + (f" as {gh['login']}" if gh.get("login") else ""),
                    "until": float(gh["until"])})
    for g in (load("keyproxy_grants.json") or {}).get("grants") or []:
        if isinstance(g, dict) and float(g.get("until") or 0) > moment:
            out.append({"what": {"all": "Internet, any public server", "internet": "Internet, any "
                                 "public server", "ssh": "ssh to public servers", "servers":
                                 "your own servers", "lan": "the office network"}.get(
                str(g.get("kind") or ""), str(g.get("name") or g.get("kind") or "a server")),
                "until": float(g["until"])})
    return out


__all__ = ["CALLING", "MODES", "Mode", "NotAPress", "OwnerPress", "RESTRICTED", "STILL_ASKS",
           "UNDO", "UNRESTRICTED", "collecting", "current", "feed", "flip", "flips", "for_chat",
           "for_job", "grants_open", "note_undo", "owner_mode", "record", "still_asks", "told",
           "undo", "after_flip", "collecting_now", "ran", "ran_released"]
