"""The check face: the few calls the protected core's frozen security tests make of this Rouh.

Task 98, step 98-23 (Petar, 24 October 2026). The permission and approval code runs inside the
Rouh's own program, so it cannot be moved where the Rouh cannot reach it; instead a frozen copy
of the security tests lives in the protected core (``guard/frozen/security.py``, inside the
``rouh-guard`` image, which a Rouh uses but cannot edit), and a change of this Rouh's code goes
live only when those tests pass against it. They never reach into Rouh's tool registry, models or
stores. They call this module and nothing else, and look only at what it gives back: plain text,
numbers, lists and dictionaries, never one of Rouh's own objects.

So a Rouh may rebuild its tools, models and pages however it likes, as long as these calls keep
answering in the same way. They are numbered: this is **check face contract 1** (``CONTRACT``).
Within one number calls are only ever added, never taken away or changed; the protected core
says which numbers it can test (``guard/rouh_guard/__init__.py``, ``CONTRACTS``), and keeps an
old number for at least a year.

Every person, address and organisation made here is made up, on ``.example`` domains, and only
ever in the throwaway database the check runs on (the frozen runner refuses any other).
"""
from __future__ import annotations

import asyncio
import contextlib

#: The check face's contract number. Calls are only added within a number.
CONTRACT = 1


# --- 1. Text from outside --------------------------------------------------------------------


def wrap(text: str, source: str) -> str:
    """Somebody else's words as Rouh hands them to a model: inside a wrapper they cannot close."""
    from rouh import untrusted

    return untrusted.wrap(text, source)


def wrap_tool_result(tool: str, text: str) -> str:
    """What the tool `tool` hands a model when it returns `text` written by somebody else."""
    from rouh import untrusted

    return untrusted.wrap_for(tool, text)


def own_words_through(tool: str, text: str) -> str:
    """What `tool` hands a model when the text is Rouh's own words, not somebody else's."""
    from rouh import untrusted

    return untrusted.wrap_for(tool, untrusted.ours(text))


def is_wrapped(text: str) -> bool:
    from rouh import untrusted

    return bool(untrusted.is_wrapped(text))


def inner(text: str) -> str:
    """The words inside a wrapper, exactly as they were written."""
    from rouh import untrusted

    return str(untrusted.inner(text))


def wraps(tool: str) -> bool:
    """Whether the tool `tool` (an MCP tool too, mcp__server__tool) wraps what it returns."""
    from rouh import untrusted

    return bool(untrusted.source_for(tool))


def built_in_rules() -> str:
    """The rules a new Rouh starts with whatever else it has (`ruledefaults.fallback`), as one text: those a
    Rouh takes in before it has reached rouh.land, the rule about wrapped text first among them. Every rule is the
    person's to change since 30 October 2026, and there are no built-in rules any more; the name is the frozen
    checks'."""
    from rouh import ruledefaults

    return repr(ruledefaults.fallback())


# --- 2. Mail from somebody else --------------------------------------------------------------


def hard_limits() -> list[str]:
    """The things no message can ever make Rouh do without the person: paying, sending as them..."""
    from rouh import grants

    return sorted(grants.HARD_LIMITS)


def judge_mail(asks: list[dict], sender: str) -> list[dict]:
    """How Rouh judges what an email asks for. `asks` is [{"quote", "hard_limit"}] as a model read
    them, every one already claiming to be allowed; `sender` is "trusted" (a trusted contact with
    the widest levels) or "stranger" (an address nobody listed). Gives back, for each ask in order,
    {"hard_limit", "allowed"}."""
    from rouh import grants, mail_ledger as ledger, trusted

    tree = grants.seed_tree()
    if sender == "trusted":
        contact = trusted.Trusted(id=1, name="Sam Example", contact_id="", trusted=True,
                                  levels=trusted.with_lower(["communicate", "tasks", "use"]),
                                  addresses=["sam@friend.example"], extra_grants=["memory", "clockwork"])
    else:
        contact = trusted.implicit("someone@stranger.example", "Someone")
    rows = [ledger.Ask(ident=ledger.ident_of(a["quote"]), quote=a["quote"], n=n,
                       hard_limit=str(a.get("hard_limit") or ""), choice="", status=ledger.status_of("allowed"))
            for n, a in enumerate(asks, start=1)]
    return [{"hard_limit": a.hard_limit, "allowed": a.status == ledger.ALLOWED}
            for a in ledger.judge(rows, contact, tree)]


def senders_besides_outbox() -> list[str]:
    """Every module but the outbox that can send mail, forward or post to somebody: "name: where"."""
    from rouh import mail_replay

    return [f"{name}: {'; '.join(found[:3])}" for name, found in mail_replay.outbox_guard() if found]


def secrets_in(text: str) -> list[str]:
    """What the outbox finds in an outgoing message that must never leave: a card, an IBAN, a password."""
    from rouh import mail_outbox

    return [str(s) for s in mail_outbox.secrets_in(text)]


# --- 3. Actions that need the person's yes ---------------------------------------------------


def _registry():
    from rouh import runtime

    return runtime.tools


def tool_names() -> list[str]:
    return sorted({d["name"] for d in _registry()._defs})


def refused_when_scheduled() -> list[str]:
    """The tools this Rouh says it refuses in scheduled work (a reminder, a nightly job)."""
    from rouh import protected

    names = set(tool_names())
    out = [n for n in (*protected.REFUSED, *protected.OWN_WORDS) if n in names]
    out += [n for n in sorted(names) if protected._deletes(n) and n not in out]
    return out


def _scheduled():
    from rouh import mail_turn, protected

    return [(protected.UNATTENDED, protected.UNATTENDED.set(True)), (mail_turn.CURRENT, mail_turn.CURRENT.set(None))]


def _contact_case():
    from rouh import mail_turn

    turn = mail_turn.MailTurn(user_id="1", org_id="org-check-a", message_id="m-check-1", mode=mail_turn.CARRY_OUT)
    return [(mail_turn.CURRENT, mail_turn.CURRENT.set(turn))]


def call_tool(name: str, args: dict, *, when: str = "") -> dict:
    """Ask the tool registry to run `name` with `args`, the way a turn does, with the tool's own
    work stood in for, so a call that got through is seen and does nothing. `when` is "" (an
    ordinary turn), "scheduled" (a reminder or nightly job, nobody there) or "contact" (while Rouh
    works on a contact's message). Gives back {"answer": what the registry said, "ran": whether the
    tool's own work was reached}."""
    reg = _registry()
    ran = []
    real = reg._handlers.get(name)

    async def stand_in(*_a, **_k):
        ran.append(name)
        return "done"

    async def _emit(_event) -> None:
        return None

    setup = {"scheduled": _scheduled, "contact": _contact_case}.get(when)
    reg._handlers[name] = stand_in
    try:
        async def go():
            tokens = setup() if setup else []
            try:
                return str(await reg.call(name, args, _emit))
            finally:
                for var, tok in reversed(tokens):
                    var.reset(tok)
        answer = asyncio.run(go())
    finally:
        if real is None:
            reg._handlers.pop(name, None)
        else:
            reg._handlers[name] = real
    return {"answer": answer, "ran": bool(ran)}


def is_refusal(answer: str) -> bool:
    """Whether a registry's answer is Rouh's refusal."""
    from rouh import protected

    return bool(protected.was_refused(answer))


def never_in_contact_case() -> list[str]:
    """The tools this Rouh says a contact's message can never use: sending, forwarding, paying..."""
    from rouh import mail_turn

    return sorted(set(mail_turn.NEVER_IN_CASE) | set(mail_turn.EFFECTS))


def contact_case_may_use(name: str) -> bool:
    from rouh import mail_turn

    turn = mail_turn.MailTurn(user_id="1", org_id="org-check-a", message_id="m-check-1", mode=mail_turn.CARRY_OUT)
    return bool(turn.may_use(name))


def browser_press_refused(words: str, *, submits: bool = True, in_form: bool = True, search: bool = False) -> bool:
    """Whether the browser refuses to press a control with these words by itself."""
    from rouh import protected

    return bool(protected.commit_step({"words": words, "submits": submits, "field": False,
                                       "in_form": in_form, "search": search}))


def browser_unreadable_press_refused() -> bool:
    from rouh import protected

    return bool(protected.commit_step("not readable"))


def heartbeat_holds(tool: str, args: dict) -> bool:
    """Whether a heartbeat beat holds `tool` back for the person rather than doing it."""
    from rouh import heartbeat

    beat = heartbeat.Beat(id=1, user_id="1", org_id="org-check-a", chat="c-check")
    token = heartbeat.BEAT.set(beat)
    try:
        return bool(heartbeat.check(tool, args))
    finally:
        heartbeat.BEAT.reset(token)


def capability_lock_problems() -> list[str]:
    """What a contact could be allowed beyond the capabilities that were locked; empty when none."""
    from rouh import capabilities

    return [str(p) for p in capabilities.lock_problems(capabilities.catalogue(), capabilities.read_lock())]


# --- 4. People and organisations -------------------------------------------------------------


def two_people() -> list[dict]:
    """Two people in two organisations, made once: [{"user_id", "org_id", "username"}] x 2."""
    from rouh import accounts, tenancy
    from rouh.models import User

    t = tenancy.Tenancy()
    out = []
    for org, name in (("org-check-a", "check-alice"), ("org-check-b", "check-bob")):
        if not User.objects.filter(username=name).exists():
            t.add_organisation(org.replace("org-check-", "Check ").upper(), org)
            accounts.add_user(name, f"pw-{name}-Example-123", org_id=org)
        user = User.objects.get(username=name)
        who = t.identity_of(str(user.pk))
        out.append({"user_id": str(who.user_id), "org_id": str(who.org_id), "username": name})
    return out


def _who(person: dict):
    from rouh import tenancy
    from rouh.models import User

    user = User.objects.get(username=person["username"])
    return tenancy.Tenancy().identity_of(str(user.pk))


def note_keep(person: dict, text: str, title: str = "") -> str:
    """A note this person keeps; gives back its id."""
    from rouh import thoughts

    row, _ = thoughts.capture(_who(person), text, title=title)
    return str(row["id"])


def note_ids(person: dict) -> list[str]:
    from rouh import thoughts

    return [str(t.get("id")) for t in (thoughts.listing(_who(person)).get("thoughts") or [])]


def note_opens(person: dict, note: str) -> bool:
    """Whether this person can open the note by its id."""
    from rouh import thoughts

    try:
        thoughts.one(_who(person), note)
        return True
    except thoughts.NotFound:
        return False


def page_status(path: str, person: dict | None = None) -> int:
    """The HTTP status Rouh's page answers `path` with, for this person signed in or for nobody."""
    from django.test import Client
    from rouh.models import User

    web = Client(HTTP_HOST="localhost")
    if person is not None:
        web.force_login(User.objects.get(username=person["username"]))
    return int(web.get(path).status_code)


def note_page(note: str) -> str:
    """The address on Rouh's page that opens one note."""
    return f"/api/thoughts/{note}"


def reminder_add(person: dict, what: str) -> str:
    from datetime import datetime, timedelta, timezone

    from rouh import reminders

    row = reminders.add(_who(person), what=what, title=what[:40],
                        first=datetime.now(timezone.utc) + timedelta(days=1))
    return str(row.id)


def reminder_ids(person: dict) -> list[str]:
    from rouh import reminders

    return [str(r.id) for r in reminders.rows(_who(person))]


def case_with_ask(person: dict, quote: str) -> str:
    """A contact's case for this person, holding one ask that touches money; gives back its id."""
    from rouh import mail_ledger
    from rouh.models import MailCase

    who = _who(person)
    case, _ = MailCase.objects.get_or_create(key=f"check-case-{person['username']}", defaults=dict(
        user_id=who.user_id, org_id=who.org_id, message_id=f"m-check-{person['username']}"))
    mail_ledger.write(who.user_id, who.org_id, case.id, [mail_ledger.Ask(
        ident="pay-check", quote=quote, n=1, hard_limit="money")])
    return str(case.id)


def case_ask_count(user_id: str, org_id: str, case: str) -> int:
    """How many of a case's asks are read for this person in this organisation. Raises ValueError
    when asked with no person and no organisation at all."""
    from rouh import mail_ledger

    return len(mail_ledger.rows(user_id, org_id, int(case)))


def case_message_count(user_id: str, org_id: str, case: str) -> int:
    from rouh import mail_outbox

    return len(mail_outbox.rows(user_id, org_id, int(case)))


@contextlib.contextmanager
def quiet():
    """Nothing the checks call may print into the check's own lines."""
    import io
    import sys

    keep = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdout = keep
