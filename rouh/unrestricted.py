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
`models.UnrestrictedAction`, shown on the Permissions page, with Undo where the service allows one:
Cloudflare keeps each record as it was before a change (`UNDO`, `cloudflare.ZoneAPI`), so a DNS
change, a deletion or Email Routing switched on or off can be put back.

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
    return current(who)


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


def note_undo(step: dict) -> None:
    """A tool says how to undo what it just did. Nothing happens unless a caller collects."""
    got = UNDO.get()
    if got is not None and isinstance(step, dict):
        got.append(step)


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
           result: str, ok: bool = True, undo: list | None = None) -> int:
    """One call that ran because of Unrestricted, for What Rouh did. Never raises."""
    try:
        from .models import UnrestrictedAction

        steps = [u for u in undo or [] if isinstance(u, dict)]
        said = "" if steps else ("No undo: nothing it changed was kept to put back." if ok
                                 else "Nothing ran, so there is nothing to undo.")
        if isinstance(args, dict) and args.get("action") and (not what or what.startswith("Using ")):
            what = f"{tool}: {str(args['action']).replace('_', ' ')}" + (
                f" on {args['zone']}" if args.get("zone") else "")
        row = UnrestrictedAction.objects.create(
            **_whose(who), via=via, where=str(where)[:120], title=str(title)[:300], tool=tool,
            args=_masked(args), what=str(what)[:600], why=str(why)[:1000],
            result=str(result)[:4000], ok=bool(ok), undo={"steps": steps} if steps else {},
            undo_said=said, at=time.time())
        return row.id
    except Exception:  # noqa: BLE001
        log.exception("what %s did under Unrestricted could not be written down", tool)
        return 0


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


def undo(who, ident: int) -> dict:
    """Put back what one row of What Rouh did changed, where its service allows. Sync."""
    from .models import UnrestrictedAction

    row = UnrestrictedAction.objects.filter(**_whose(who), id=int(ident)).first()
    if row is None:
        return {"ok": False, "said": "There is no such action."}
    if row.undone_at:
        return {"ok": False, "said": "It was undone already."}
    steps = (row.undo or {}).get("steps") or []
    if not steps:
        return {"ok": False, "said": row.undo_said or "It cannot be undone here."}
    said = []
    try:
        for step in reversed(steps):
            if step.get("kind") == "cloudflare":
                from . import cloudflare

                api = cloudflare.zone_api(step["zone"], str(who.org_id or ""))
                said += api.put_back(step.get("ops") or [])
            else:
                said.append(f"no way to undo a {step.get('kind')!r} step")
    except Exception as exc:  # noqa: BLE001 - said, and the row stays undoable
        log.exception("action %s could not be undone", ident)
        return {"ok": False, "said": f"It could not be undone: {exc}"}
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
           "undo"]
