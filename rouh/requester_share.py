"""A task made for somebody outside, shared with them to edit, once.

Petar, 14 October 2026: "I want when a task is created by outside person to be
automatically shared with edit rights to them. The entire task, not just the HTML
page, the person shouldn't be requesting it every time. And when they log into
Rouh they should see all the tasks."

How it was before: a trusted contact asks by email or Telegram, a job does the
work as a task of Petar's labelled Guest (`mail_cases.work_brief`: tags `guest`,
and `"guest": "<their address>"` in its meta), and their result is mailed
back to them. The task itself was never shared, so they could not open it in
Rouh: task 114, for a contact, said "nothing is sent, shared or published from here".
Edit rights, a grant of its own until 16 October 2026, shared only the tasks made
under the Shared task grant, and only while the contact held it.

So, now, every task made for somebody outside is shared with them, whole and to
edit, the moment Rouh first sees it:

- **Who.** A task or a step whose meta is tagged `guest` (`trusted.GUEST_TAG`)
  names who asked in `"guest"`: an address, or a Telegram account linked to a
  trusted contact, whose own address is then used (`address_for`).
  Only that person: never anybody they copied or named, never Petar's own
  addresses or Rouh's, never a member of his organisation, who sees it anyway,
  and never a contact he has switched off.
- **What.** The whole task, exactly as the Share panel shares it with a person to
  edit (`sharing.EDIT` on `_task/<folder>`, `rouh/taskshare.py`): its pages, its
  notes and its subtasks, each page changeable with Ask AI. A step made later
  inside it is inside the shared folder, so it is shared with it; a step tagged
  for somebody in a task that is not theirs is shared on its own.
- **The letter, once.** The usual sharing letter (`web.guests.share_and_tell`): the
  invitation to make an account, or the note with the link. A share to read they
  had already turns to edit on the same link, and no second letter goes when one
  went before.
- **Once, and Petar can take it back.** Each task and address is written down
  (`RequesterShare`) the first time, whatever came of it, and never done again,
  so a share Petar stops in the Share panel, or turns to read, stays the way he
  left it. Never public: no link anybody can open is made.
- **When.** As a job's landed work is taken in (`assistant_job._task_made`), as the
  `shared_task` tool makes one (`tools.ToolRegistry._shared_task`), as soon as the
  rows take in a new task or step (`conversations.reconcile` wakes `keep`), and
  every few minutes besides. The first pass after this landed shared every guest
  task made before it (the backfill), skipping those shared to edit already.

Every query names the owner's user and organisation (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from . import sharing
from . import trusted as trust

log = logging.getLogger("rouh.requester_share")

#: What became of a task and an address, as the ledger keeps it.
SHARED, UPGRADED, ALREADY, COVERED = "shared", "upgraded", "already", "covered"

#: How long `keep` waits between passes when nothing woke it, in seconds.
EVERY = 300.0

#: One share at a time, here and in `task_access.keep_ticks`, so no task is shared twice at once.
LOCK = asyncio.Lock()
_WOKEN = threading.Event()


def _root() -> str:
    from .config import config

    return getattr(config, "assistant_repo", "") or ""


def _owner():
    """Whose workspace this is: the one person on this install (`Tenancy.only_person`)."""
    from .tenancy import Tenancy

    return Tenancy().only_person()


def address_for(contact, meta: dict) -> str:
    """Where a task is shared with a contact: the address it was asked from, when that is one of
    theirs, or their first one. Never a Telegram account, which has no letter."""
    guest = sharing.clean_email(meta.get("guest"))
    if guest and guest in contact.addresses:
        return guest
    return next((a for a in (sharing.clean_email(x) for x in contact.addresses) if a), "")


def _owner_name(owner) -> str:
    from .models import User
    from .web import guests

    user = User.objects.filter(pk=owner.user_id).first()
    return guests._owner_name(user) if user is not None else "Somebody"


def _filed(root: str, folder: str) -> str:
    """Where a task is once it is filed. A task made under Shared task is made in the Personal
    column and filed into a project of it a moment later, by the tidy every reading of the
    tree runs (`objectindex._ready`), so it is run here first and the task followed by its
    number (`objectindex.moved_to`): task 113 was made at `private/113...` and was at
    `private/misc/113...` before anybody looked."""
    from . import objectindex

    objectindex._ready(root)
    return objectindex.moved_to(folder) or folder


def _ours(owner, address: str) -> bool:
    """Whether an address is the owner's own, Rouh's, or a member of their organisation's."""
    from . import my_card
    from .models import User

    if my_card.never_mine(address) or my_card.is_own(owner.user_id, owner.org_id, address):
        return True
    return User.objects.filter(email__iexact=address, is_guest=False,
                               org_id=owner.org_id).exists()


def requester(owner, meta: dict, contact=None) -> tuple[str, object]:
    """Who asked for the task a meta describes: (their address, their trusted contact
    or None), or ("", None) when it was not asked for by somebody outside."""
    tags = [str(t).strip().lower() for t in meta.get("tags") or [] if isinstance(t, str)]
    if trust.GUEST_TAG not in tags:
        return "", None
    raw = str(meta.get("guest") or "").strip().lower()
    asked = meta.get("requested_by")
    if not raw and isinstance(asked, dict):
        raw = str(asked.get("contact") or "").strip().lower()
    if contact is None and raw:
        contact = next((c for c in trust.TrustStore().all(owner.user_id, owner.org_id)
                        if c.recognises(raw)), None)
    if contact is not None:
        if not contact.trusted:
            return "", None
        # `address_for` takes the address it was asked from when it is theirs.
        address = address_for(contact, meta)
    else:
        address = sharing.clean_email(raw)
    if not address or _ours(owner, address):
        return "", None
    return address, contact


def _task_id(folder: str) -> str:
    from .models import Task

    return Task.objects.filter(folder=folder).values_list("id", flat=True).first() or ""


def _done(owner, task_id: str, address: str) -> bool:
    from .models import RequesterShare

    return RequesterShare.objects.filter(user_id=owner.user_id, org_id=owner.org_id,
                                         task_id=task_id, email=address).exists()


def _write(owner, task_id: str, folder: str, address: str, outcome: str, *, token: str = "",
           mailed: bool = False, error: str = "") -> None:
    from .models import RequesterShare

    RequesterShare.objects.get_or_create(
        user_id=owner.user_id, org_id=owner.org_id, task_id=task_id, email=address,
        defaults={"folder": folder, "outcome": outcome, "token": token, "mailed": mailed,
                  "mail_error": (error or "")[:300], "at": time.time()})


def _covered(owner, folder: str, address: str) -> bool:
    """Whether a task above this folder is shared with this address to edit already."""
    from . import taskshare
    from .models import PageGuest

    parts = folder.split("/")
    above = [taskshare.PREFIX + "/".join(parts[:n]) for n in range(1, len(parts))]
    return PageGuest.objects.filter(user_id=owner.user_id, org_id=owner.org_id, rel__in=above,
                                    email=address,
                                    role__in=(sharing.EDIT, sharing.DECIDE)).exists()


async def share(owner, folder: str, *, root: str | None = None, contact=None) -> str:
    """The task at `folder` shared with whoever outside asked for it, to edit, once.

    The sentence of what became of it, or "" when nothing was done: it was not asked for by
    somebody outside, it was done before, or it cannot be shared yet (its row is not there).
    `owner` is whose task it is (`tenancy.Identity`); `contact`, when the caller knows it, is
    the trusted contact who asked.
    """
    async with LOCK:
        try:
            return await _share(owner, folder, root=_root() if root is None else root,
                                contact=contact)
        except Exception:  # noqa: BLE001 - one task that cannot be shared never stops the rest
            log.exception("requester share: task %s could not be shared", folder)
            return ""


async def _share(owner, folder: str, *, root: str, contact) -> str:
    from . import pages, taskshare
    from .web import guests

    if not folder or not root or owner is None:
        return ""
    folder = await asyncio.to_thread(_filed, root, folder)
    meta = await asyncio.to_thread(trust.task_meta, root, folder)
    address, contact = await asyncio.to_thread(requester, owner, meta, contact)
    if not address:
        return ""
    task_id = await asyncio.to_thread(_task_id, folder)
    if not task_id or await asyncio.to_thread(_done, owner, task_id, address):
        return ""
    try:
        rel, title = await asyncio.to_thread(sharing.shareable, root, taskshare.PREFIX + folder)
    except (pages.Refused, OSError) as exc:
        log.warning("requester share: task %s cannot be shared: %s", folder, exc)
        return ""
    if await asyncio.to_thread(_covered, owner, folder, address):
        await asyncio.to_thread(_write, owner, task_id, folder, address, COVERED)
        return ""
    people = await asyncio.to_thread(sharing.Guests().people, owner, rel)
    there = next((p for p in people if p["email"] == address), None)
    if there is not None and sharing.can_edit(there["role"]):
        # Edit, or decide, which includes it: never lowered by this.
        await asyncio.to_thread(_write, owner, task_id, folder, address, ALREADY,
                                token=there["token"], mailed=there["mailed"])
        log.info("requester share: %s was shared with its requester to edit already", rel)
        return ""
    name = await asyncio.to_thread(_owner_name, owner)
    try:
        # `again=False`: a share to read whose letter went turns to edit with no second one.
        told = await guests.share_and_tell(owner, name, rel, title, address, sharing.EDIT,
                                           again=False)
    except ValueError as exc:
        log.warning("requester share: task %s was not shared with its requester: %s",
                    folder, exc)
        return ""
    outcome = UPGRADED if there is not None else SHARED
    await asyncio.to_thread(_write, owner, task_id, folder, address, outcome,
                            token=told.share["token"], mailed=told.sent, error=told.trouble)
    who = getattr(contact, "name", "") or address
    log.info("requester share: %s %s with %s to edit, %s", rel, outcome, address,
             "and the letter went" if told.sent else
             "with no second letter" if told.already else "and the letter did not go")
    said = f"{title} is shared with {who} to edit"
    if there is not None:
        return f"{said} now, on the link they had."
    if told.trouble:
        return f"{said}, but the email with its link to {address} did not go: {told.trouble}"
    return f"{said}, and the email with its link went to {address}."


def _candidates(owner, root: str) -> list[str]:
    """The folder of every live task and step tagged `guest` that no pass has shared yet,
    oldest first."""
    from .models import RequesterShare, Task

    done = set(RequesterShare.objects.filter(user_id=owner.user_id, org_id=owner.org_id)
               .values_list("task_id", flat=True))
    out = []
    for ident, folder in (Task.objects.filter(archived_at__isnull=True).exclude(folder="")
                          .order_by("created_at").values_list("id", "folder")):
        if ident in done:
            continue
        tags = trust.task_meta(root, folder).get("tags")
        if isinstance(tags, list) and trust.GUEST_TAG in {
                str(t).strip().lower() for t in tags if isinstance(t, str)}:
            out.append(folder)
    return out


async def sweep(root: str | None = None) -> list[str]:
    """Every task made for somebody outside that has not been shared with them yet, shared.
    What was done, a sentence each."""
    from django.db import close_old_connections

    root = _root() if root is None else root
    if not root:
        return []
    await asyncio.to_thread(close_old_connections)
    owner = await asyncio.to_thread(_owner)
    if owner is None:
        return []
    # Who each new one was made for, kept on its row first, so the person's own views leave
    # it out from the moment it is there (`rouh/task_origin.py`).
    from . import task_origin

    try:
        # And which of Rouh's processes made one, where its own record says so: a thought's
        # task, a night's step. Before the sweep, which then marks whatever of those was made
        # for somebody else.
        await asyncio.to_thread(task_origin.backfill, root, write=True)
        await asyncio.to_thread(task_origin.sweep, root, owner)
    except Exception:  # noqa: BLE001 - marked on the next pass
        log.exception("requester share: who the new tasks were made for could not be kept")
    out = []
    for folder in await asyncio.to_thread(_candidates, owner, root):
        said = await share(owner, folder, root=root)
        if said:
            out.append(said)
    # And what is ticked on each contact's page reaches Rouh's own pages too: every task under
    # it shared with them to read, kept by the tick (`rouh/task_access.py`). After the requests,
    # so a task somebody asked for is shared with them to edit first.
    from . import task_access

    async with LOCK:
        try:
            await asyncio.to_thread(task_access.keep_ticks, owner, root=root)
        except Exception:  # noqa: BLE001 - tried again on the next pass
            log.exception("requester share: the ticked tasks could not be shared")
    return out


def wake() -> None:
    """Ask `keep` for a pass now: a task or a step was just taken in. Any thread."""
    _WOKEN.set()


async def keep() -> None:
    """For as long as Rouh runs: a pass at the start, which is the backfill, then one whenever
    `wake` is called and every `EVERY` seconds besides."""
    last = 0.0
    log.info("requester share: sharing every task made for somebody outside with them")
    while True:
        if _WOKEN.is_set() or time.monotonic() - last >= EVERY:
            _WOKEN.clear()
            last = time.monotonic()
            try:
                for one in await sweep():
                    log.info("requester share: %s", one)
            except Exception:  # noqa: BLE001 - tried again on the next pass
                log.exception("requester share: a pass stumbled")
        await asyncio.sleep(2)


__all__ = ["ALREADY", "COVERED", "SHARED", "UPGRADED", "address_for", "keep", "requester",
           "share", "sweep", "wake"]
