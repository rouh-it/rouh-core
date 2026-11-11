"""Pages shared with people, and read by somebody who is not the owner.

Petar, 24 September 2026 (fr_edecde0ad6e6):

    "in rare cases, we would like shared and public pages to have the ability
    to edit that HTML. The reason is that this becomes like a collaboration
    project, but since we can't onboard everyone on our system, at least not
    for now, we have to operate with hidden public pages... Maybe that's a good
    idea: do the guest registrations. The way it would work is that I invite a
    specific person with a specific email. If that person doesn't have an
    account, he receives an email saying he needs to register. They can
    register, and when they go to the website, they would see the thing I have
    shared with them. That would be like the guest account: just a list of the
    things that have been shared with them, and then they can use the Ask AI
    active feature... If they have an account, they're just notified that there
    is a new thing that's been shared with them."

So there are two readers who are not the owner, and one page that serves both.

- **A person the page was shared with**, by their email address, from the
  Share panel (`invite`). With no account yet, they get a letter with a link
  to make one (`join`): the address is the invitation's, fixed, and what they
  give is their first name and last name, and, only when this Rouh cannot send
  mail, a password, the rules it is held to listed and ticked off as they type
  (`rouh/password_rules.py`). Opening the invitation proves the address, so
  from then on they sign in to this Rouh by email (`rouh/signin.py`), never
  through rouh.land and never with Google (4 November 2026). With
  an account already, they get a note that there is something new. Either way
  it is `/shared/<token>`, which answers only somebody signed in with that
  address, and `/shared` lists everything shared with them. An account made
  this way is a **guest** (`users.is_guest`): the gate lets it reach `/shared`
  and nothing else (`rouh/web/gate.py`).
- **A visitor to a public link the owner said may be changed**
  (`public_pages.role = "edit"`). `/p/<token>` stays exactly what it was for a
  read-only link; for one that may be changed it is this page too.

The reader's page is Rouh's own, not the workspace page: a thin bar and the
page in a sandboxed frame, exactly as the owner's canvas frames it, with the
Ask AI drawer in it. The drawer cannot call out of its frame (`pages.py` says
why), so this page carries its questions - to routes under the reader's own
token, which is the "ask route scoped to the token" `sharing.py` said a
visitor would need - and the one who may change the page can.

What such a reader can never reach is anything else. Every route here starts
from the token, finds the one page it names, and serves that page and its
questions: never a path from the request, never a listing, never the rest of
the workspace, never Rouh's own chat. Their questions are kept as their own
(`askai_threads`, under the guest's own id, or ``link:<token>`` for everybody
holding one link, which is the "collaboration" Petar asked for), and there is
a ceiling on them a day, because they are paid for by the owner.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from asgiref.sync import sync_to_async
from django.contrib.auth import alogin
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import render

from rouh import (askai, comments, mailer, modeldefaults, pagehistory, pages,
                  password_rules, sharing, taskshare)
from rouh.config import config
from rouh.tenancy import GUEST_ORG, Identity

from .common import answer, body_of, only, refuse, who

log = logging.getLogger("rouh.guests")

#: Questions a day, for a reader whose questions somebody else pays for. A
#: person the page was shared with is somebody the owner chose; a link is
#: whoever has it, so it gets fewer.
GUEST_A_DAY = 200
LINK_A_DAY = 60

NO_STORE = {"Cache-Control": "no-store, private"}

#: Sent with a reader's page on top of that: it is Rouh's own page, never to
#: be framed by anybody else's, and a public one is not for search engines.
#:
#: The referrer is kept to this site and not refused outright. The token is in
#: this page's address and must never reach another site in a Referer, which
#: "same-origin" already promises; "no-referrer" would also make the browser
#: send the page's own writes with an Origin of "null", and Django's CSRF check
#: refuses every one of those (found driving the invitation's form).
READER_HEADERS = {**NO_STORE, "X-Frame-Options": "DENY", "Referrer-Policy": "same-origin",
                  "X-Content-Type-Options": "nosniff"}


def _store() -> sharing.Guests:
    from rouh import runtime

    return runtime.guests


def _rt():
    from rouh import runtime

    return runtime


def _owner_name(user) -> str:
    return (user.get_full_name() or user.username or "Somebody").strip()


# --- the owner's side: sharing a page with a person --------------------------------------


def _existing_account(email: str):
    """The account this address already belongs to, if exactly one does."""
    from rouh import signin
    from rouh.models import User

    signs_in = signin.user_for(email)
    if signs_in is not None:
        return signs_in
    found = list(User.objects.filter(email__iexact=email, is_active=True)[:2])
    return found[0] if len(found) == 1 else None


#: The longest message the owner may put in a letter. A note, not a document.
MESSAGE_MAX = 2000


def clean_message(raw) -> str:
    """The owner's own words for the letter, trimmed and capped, or empty."""
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:MESSAGE_MAX].strip()


#: What the invitation says about rouh.land (Petar, 11 November 2026: "people should not have accounts
#: in places they did not explicitly agree to signup for"): nobody gets an account by opening the link.
LAND_SAID = ("To view it you need a rouh.land account for {email}. If you have none, you create one "
             "yourself when you open the link (no password: rouh.land emails you a link to confirm "
             "the address), then open what was shared. Opening the link alone creates nothing.")


def _letter(owner: str, share: dict, has_account: bool, message: str = "") -> mailer.Letter:
    """The invitation, or the note to somebody who already has an account.

    With `message`, the owner's own words go in it too, between what was
    shared and the link to it, as Google Drive puts the line its sharer typed
    (fr_55056f9ffcc2).
    """
    what = "a task" if taskshare.is_task(share["rel"]) else "a page"
    title = share["title"] or what
    edit = sharing.can_edit(share["role"])
    decide = share["role"] == sharing.DECIDE
    if what == "a task":
        can = ("read it, its pages, its notes and its subtasks, and change its pages with "
               "Rouh's AI" if edit else "read it, its pages, its notes and its subtasks")
        if decide:
            can += f", and decide for {owner} there by email"
    else:
        can = ("read it, ask Rouh's AI about it, and change it" if edit
               else "read it and ask Rouh's AI about it")
    # What they may do, in so many words, so the letter says it before they open it.
    access = "Can decide" if decide else "Can edit" if edit else "Can view"
    base = config.public_url.rstrip("/")
    message = clean_message(message)
    head = f"{owner} shared {what} with you on Rouh:\n\n  {title}\n  ({access})\n\n"
    if message:
        head += f"{owner} wrote:\n\n" + "\n".join(
            "  " + line if line else "" for line in message.split("\n")) + "\n\n"
    if has_account:
        link = base + share["path"]
        text = (head + f"You can {can}. Open it here, signed in as {share['email']}:\n\n"
                f"  {link}\n\nEverything shared with you is at " + base + "/shared\n")
        button, lead = f"Open the {what[2:]}", f"You can {can}."
    else:
        # Through rouh.land (step 176-26): the link is the share on this Rouh's relay address, and
        # opening it asks rouh.land who they are. No account is made here and no form is filled in.
        from rouh import landshare

        link = landshare.link(share["path"])
        text = (head + f"You can {can}. Open it here:\n\n  {link}\n\n"
                + LAND_SAID.format(email=share["email"]) + "\n\n"
                f"This invitation is for {share['email']} alone. If you were not expecting "
                "it, you can ignore this letter.\n")
        button = f"Open the {what[2:]}"
        lead = f"You can {can}. " + LAND_SAID.format(email=share["email"])
    e = html.escape
    said = ("" if not message else
            f'<p style="margin:16px 0 4px;color:#5d6674;font-size:13px">{e(owner)} wrote:</p>'
            '<div style="margin:0 0 16px;padding:10px 14px;border-left:3px solid #4c8dff;'
            'background:#f3f6fb;border-radius:4px">'
            + "<br>".join(e(line) for line in message.split("\n")) + "</div>")
    body = (
        '<div style="font:15px/1.55 -apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'
        'color:#1b1c1e;max-width:520px">'
        f"<p>{e(owner)} shared {e(what)} with you on Rouh:</p>"
        f'<p style="font-size:18px;font-weight:600;margin:14px 0 4px">{e(title)}</p>'
        f'<p style="margin:0 0 14px;color:#5d6674;font-size:13px">{e(access)}</p>'
        + said +
        f"<p>{e(lead)}</p>"
        f'<p style="margin:22px 0"><a href="{e(link, quote=True)}" style="background:#4c8dff;'
        'color:#04070c;padding:11px 18px;border-radius:9px;text-decoration:none;'
        f'font-weight:600">{e(button)}</a></p>'
        f'<p style="color:#5d6674;font-size:13px">Or open this link:<br>'
        f'<a href="{e(link, quote=True)}" style="color:#2f6fe0">{e(link)}</a></p>'
        + ("" if has_account else
           f'<p style="color:#5d6674;font-size:13px">This invitation is for {e(share["email"])} '
           "alone. If you were not expecting it, you can ignore this letter.</p>")
        + "</div>")
    return mailer.Letter(to=share["email"], subject=f"{owner} shared “{title}” with you",
                         text=text, html=body)


async def _send(owner: str, share: dict, has_account: bool, message: str = "") -> str:
    """Send the letter. Empty when it went, or the sentence saying why not."""
    letter = _letter(owner, share, has_account, message)
    try:
        await mailer.Mailer(config).send(letter)
    except (mailer.NotSetUp, mailer.NotSent) as exc:
        await asyncio.to_thread(_store().mailed, share["token"], str(exc))
        return str(exc)
    await asyncio.to_thread(_store().mailed, share["token"])
    return ""


@dataclass
class Told:
    """What sharing with one person came to: the share, and whether they were told."""

    share: dict
    has_account: bool
    new: bool
    #: Whether a letter was asked for at all.
    notified: bool
    #: Empty when the letter went, or the sentence saying why it did not.
    trouble: str = ""
    #: A letter had already gone and `again` said not to send another.
    already: bool = False

    @property
    def sent(self) -> bool:
        return self.notified and not self.trouble and not self.already


async def share_and_tell(me, owner: str, rel: str, title: str, email: str, role: str, *,
                         notify: bool = True, message: str = "", again: bool = True) -> Told:
    """Share `rel` with `email` and, unless `notify` is off, email them the link.

    The one way a page or a task is shared with a person, for the Share panel
    (`invite`) and the assistant's own tools alike (`rouh/tools.py`). Petar,
    13 October 2026 (fr_55056f9ffcc2): "When sharing a link with someone send
    them an email with the link, they would not know they have received it."
    The panel may untick the letter; the assistant never does. `again` False
    sends nothing to somebody whose letter already went, which is what a
    retried mail case wants. Raises `ValueError` when it cannot be shared.
    """
    from rouh import landshare

    why = await asyncio.to_thread(landshare.refusal, me.org_id)
    if why:
        # Petar, 11 November 2026 (step 176-26): the person shared with signs in with rouh.land, so a
        # Rouh On its own cannot share privately, and never makes an account here instead.
        raise ValueError(why)
    account = await asyncio.to_thread(_existing_account, email)
    if account is not None and getattr(account, "is_guest", False):
        # A guest is somebody rouh.land says who they are now: the letter is the same for everybody
        # who is not one of this Rouh's own people.
        account = None
    share, new = await asyncio.to_thread(
        _store().invite, me, rel, title, email, role,
        str(account.pk) if account is not None else "")
    told = Told(share=share, has_account=account is not None, new=new, notified=notify)
    if not notify:
        return told
    if not again and not new and share.get("mailed"):
        told.already = True
        return told
    told.trouble = await _send(owner, share, account is not None, message)
    return told


def _inherited(me, rel: str) -> list[dict]:
    """Who may do something here only by a record above it (`task_access.inherited`)."""
    from rouh import task_access

    try:
        return task_access.inherited(me, rel)
    except Exception:  # noqa: BLE001 - the panel shows the rest
        log.exception("sharing: who inherits %s could not be read", rel)
        return []


def _people(me, rel: str) -> list[dict]:
    """Everybody a page or a task is shared with by a record of their own, as the Share panel
    draws them: with when each last opened it (`rouh/share_opens.py`), whether they may be
    given decide, and what a share a tick keeps comes from (`task_access.people_here`)."""
    from rouh import share_opens, share_remind, task_access

    people = [{k: p[k] for k in ("token", "email", "role", "joined", "mailed", "mail_error",
                                 "via", "opened") if k in p}
              for p in share_opens.with_opens(me, _store().people(me, rel))]
    # And Remind them beside who has not opened it, while that gene is on (`rouh/share_remind.py`).
    people = share_remind.with_remind(me, people, rel)
    # And Until beside each person shared with by hand, while that gene is on (`rouh/share_ends.py`).
    from rouh import share_ends

    people = share_ends.with_ends(me, people, rel)
    try:
        return task_access.people_here(me, rel, people)
    except Exception:  # noqa: BLE001 - the panel shows the rest
        log.exception("sharing: who may decide on %s could not be read", rel)
        return people


@only("POST")
async def remind(request: HttpRequest):
    """POST /api/share/remind {rel}: Remind them was pressed in the Share panel, kept as its use
    (`rouh/share_remind.py`). The email itself is opened in Gmail by the browser."""
    from rouh import share_remind

    me = await sync_to_async(who)(request)
    if me is None or me.org_id == GUEST_ORG:
        return refuse("Sign in to Rouh first.", 401)
    if not await asyncio.to_thread(share_remind.on, me):
        return refuse("Remind them is switched off.", 400)
    await asyncio.to_thread(share_remind.pressed, me)
    return answer({"ok": True})


@only("POST")
async def ends(request: HttpRequest):
    """POST /api/share/ends {rel, token, days}: Until was set beside a person in the Share panel
    (`rouh/share_ends.py`); days 0 takes the end off."""
    from rouh import share_ends

    me = await sync_to_async(who)(request)
    if me is None or me.org_id == GUEST_ORG:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    rel = str(asked.get("rel") or "")
    token = sharing.clean_token(str(asked.get("token") or ""))
    try:
        days = int(asked.get("days") or 0)
    except (TypeError, ValueError):
        return refuse("An end is a number of days.", 400)
    if not token:
        return refuse("That is not somebody this is shared with.", 400)
    at, why = await asyncio.to_thread(share_ends.set_end, me, rel, token, days)
    if why:
        return refuse(why, 400)
    return answer({"ends": at, "people": await asyncio.to_thread(_people, me, rel),
                   "inherited": await asyncio.to_thread(_inherited, me, rel)}, headers=NO_STORE)


@only("GET", "POST")
async def meetings(request: HttpRequest):
    """With a meeting's guests, in the Share panel (`rouh/share_meeting.py`).

    GET /api/share/meetings?rel=: up to three meetings about this page or task, with their guests
    from outside not on it yet, or none while the switch is off. POST {rel, key, role, notify,
    message}: shared with every one of that meeting's guests, as Send shares with one.
    """
    from rouh import evolution, share_meeting

    me = await sync_to_async(who)(request)
    if me is None or me.org_id == GUEST_ORG:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request) if request.method == "POST" else request.GET
    if not await asyncio.to_thread(share_meeting.on, me):
        if request.method == "GET":
            return answer({"meetings": []}, headers=NO_STORE)
        return refuse("With a meeting's guests is switched off.", 400)
    try:
        rel, title = await asyncio.to_thread(sharing.shareable, config.assistant_repo,
                                             str(asked.get("rel") or ""))
    except (pages.Refused, OSError) as exc:
        return refuse(str(exc), 404)
    people = await asyncio.to_thread(_people, me, rel)
    already = {str(p.get("email") or "").lower() for p in people} | {sharing.clean_email(me.email) or ""}
    if request.method == "GET":
        found = await asyncio.to_thread(share_meeting.meetings, me, rel, title, already=already)
        return answer({"meetings": found}, headers=NO_STORE)
    key = str(asked.get("key") or "")[:40]
    meeting = await asyncio.to_thread(share_meeting.one, me, rel, title, key, already)
    if meeting is None:
        return refuse("That meeting has nobody left to share with.", 400)
    notify = asked.get("notify", True) is not False
    message = clean_message(asked.get("message"))
    role = sharing.role_of(asked.get("role"))
    owner = _owner_name(request.user)
    went, not_sent, refused = [], [], []
    for email in meeting["guests"]:
        try:
            told = await share_and_tell(me, owner, rel, title, email, role, notify=notify, message=message)
        except ValueError as exc:
            refused.append(f"{email} ({exc})")
            continue
        (went if (told.sent or not notify) else not_sent).append(email)
    shared = went + not_sent
    said = (f"Shared with {len(shared)} of {meeting['title']}'s guests: " + ", ".join(shared) + "."
            if shared else "It was not shared with anybody.")
    if notify and went:
        said += " An email with the link went to " + ("each of them." if not not_sent else ", ".join(went) + ".")
    if not_sent:
        said += " The email did not go to " + ", ".join(not_sent) + "."
    if refused:
        said += " Not shared: " + "; ".join(refused) + "."
    if shared:
        await asyncio.to_thread(evolution.used, share_meeting.SWITCH, "shared", who=me,
                                detail=f"shared with {len(shared)} guests of a meeting")
    return answer({"said": said, "shared": shared, "sent": bool(went) and not not_sent,
                   "people": await asyncio.to_thread(_people, me, rel),
                   "inherited": await asyncio.to_thread(_inherited, me, rel)}, headers=NO_STORE)


@only("POST")
async def invite(request: HttpRequest):
    """Share one page with one address, and tell them unless asked not to.

    `notify` False is the panel's "Notify by email" unticked: the page is
    shared and no letter goes. `message` is the owner's own words for the
    letter. Pressing it again for the same address sends the letter again and
    changes what they may do; their link stays the same.
    """
    me = await sync_to_async(who)(request)
    if me is None or me.org_id == GUEST_ORG:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    try:
        rel, title = await asyncio.to_thread(sharing.shareable, config.assistant_repo,
                                             str(asked.get("rel") or ""))
    except (pages.Refused, OSError) as exc:
        return refuse(str(exc), 404)
    email = sharing.clean_email(asked.get("email"))
    if not email:
        return refuse("That is not an email address.", 400)
    if email == sharing.clean_email(me.email):
        return refuse("That is your own address, and the page is already yours.", 400)
    notify = asked.get("notify", True) is not False
    try:
        told = await share_and_tell(me, _owner_name(request.user), rel, title, email,
                                    sharing.role_of(asked.get("role")), notify=notify,
                                    message=clean_message(asked.get("message")))
    except ValueError as exc:
        return refuse(str(exc), 400)
    log.info("sharing: %s was shared with a person (%s), %s", rel, told.share["role"],
             "with no letter" if not notify else
             "and the letter went" if told.sent else "and the letter did not go")
    return answer({"said": said_of(told, email), "sent": told.sent, "notified": notify,
                   "people": await asyncio.to_thread(_people, me, rel),
                   "inherited": await asyncio.to_thread(_inherited, me, rel)}, headers=NO_STORE)


def said_of(told: Told, email: str) -> str:
    """What became of sharing with one person, in the panel's words."""
    # "It may land in spam" is measured, not modesty: the first letters from
    # a new noreply address passed DKIM, SPF and DMARC and Gmail still filed them
    # there, which is what a sending address with no history gets.
    if not told.notified:
        if told.has_account:
            return (f"Shared with {email}. No email was sent, so they will not know until "
                    "you tell them; it is under Shared when they sign in.")
        return (f"Shared with {email}. No email was sent, so they will not know until you tell "
                "them; they open it by signing in with rouh.land as that address.")
    if told.trouble:
        return f"Shared with {email}, but the email did not go: {told.trouble}"
    if told.has_account:
        return (f"Shared with {email}, and an email with the link went to them. "
                "It may land in their spam.")
    return (f"Shared with {email}, and an email with the link went to them: they sign in with "
            "rouh.land as that address, or create a rouh.land account themselves if they have none, "
            "then open what was shared. It may land in their spam.")


@only("POST")
async def uninvite(request: HttpRequest):
    """Stop sharing a page with one person. Their link stops at once."""
    me = await sync_to_async(who)(request)
    if me is None or me.org_id == GUEST_ORG:
        return refuse("Sign in to Rouh first.", 401)
    asked = body_of(request)
    token = sharing.clean_token(str(asked.get("token") or ""))
    if not token:
        return refuse("That is not somebody this page is shared with.", 400)
    rel = str(asked.get("rel") or "")
    # A task shared with a trusted contact because what it is in is ticked on their page is the
    # tick's: taken away there, by unticking, or it would only come back (`rouh/task_access.py`).
    from rouh import task_access

    there = next((p for p in await asyncio.to_thread(_store().people, me, rel)
                  if p["token"] == token), None)
    if there is not None and there.get("via") == task_access.TICK:
        held = await asyncio.to_thread(task_access.tick_holding, me, rel, there["email"])
        if held:
            return refuse(held, 409)
    gone = await asyncio.to_thread(_store().remove, me, token)
    if gone and there is not None:
        await asyncio.to_thread(task_access.taken_away, me, rel, there["email"])
    return answer({"removed": gone, "people": await asyncio.to_thread(_people, me, rel),
                   "inherited": await asyncio.to_thread(_inherited, me, rel)},
                  headers=NO_STORE)


# --- the invitation: making an account from it ---------------------------------------------


def _join_page(request, share, *, problems=(), missing=(), first_name="", last_name="",
               status=200, there=""):
    from rouh import signin

    email = share["email"] if share else ""
    # Opening the invitation proves the address. A Rouh that can send mail signs them in by email
    # from then on and asks for no password; one that cannot asks for one, set here, once.
    needs_password = not signin.can_send()
    response = render(request, "rouh/join.html", {
        "share": share, "problems": problems, "missing": list(missing), "needs_password": needs_password,
        "first_name": first_name, "last_name": last_name,
        "min_length": password_rules.min_length(),
        "password_rules": password_rules.for_page({"username": email, "email": email},
                                                  username_is_email=True),
        "owner": share.get("owner_name", "") if share else "",
        "what": "task" if share and taskshare.is_task(share["rel"]) else "page",
    }, status=status)
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "same-origin"
    return response


def _with_owner(share: dict | None) -> dict | None:
    if share is None:
        return None
    from rouh.models import User

    owner = User.objects.filter(pk=int(share["owner_id"])).first() \
        if str(share.get("owner_id") or "").isdigit() else None
    return {**share, "owner_name": _owner_name(owner) if owner else "Somebody"}


def _guest(email: str, first_name: str, last_name: str):
    """The account an invitation makes, before it is saved: what its password
    is checked against, so "not too like your name" holds here as it does
    everywhere else a password is set, and what `_make_guest` then saves.
    A guest: the pages shared with this address and nothing else. Its name to
    sign in with is the address itself."""
    from rouh.models import User

    return User(username=email, email=email, first_name=first_name, last_name=last_name,
                is_guest=True)


def _make_guest(guest, password: str):
    """The account, made, with both names kept apart, and its address as its way in. With no
    password given (this Rouh sends sign-in emails), it has none, and signs in by email."""
    from rouh import signin
    from rouh.models import User

    user = User.objects.create_user(username=guest.username, email=guest.email,
                                    password=password or None, first_name=guest.first_name,
                                    last_name=guest.last_name, is_guest=True)
    _store().claim(guest.email, str(user.pk))
    try:
        signin.set_primary(user, guest.email, source="invitation")
    except signin.Taken:
        log.warning("a guest's address already signs another account in")
    return user


def _name(request, field: str) -> str:
    """One name off the form, its spaces tidied. Empty if it was only spaces."""
    return " ".join(str(request.POST.get(field) or "").split())[:150]


async def join(request: HttpRequest, token: str):
    """The link in an invitation: make an account for that address, and open
    the page. Somebody who already has an account is sent to sign in."""
    if request.method not in ("GET", "HEAD", "POST"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD, POST"})
    share = await asyncio.to_thread(lambda: _with_owner(_store().find(token)))
    if share is None:
        return await asyncio.to_thread(_join_page, request, None, status=404)
    there = "/shared/" + share["token"]
    from rouh import landshare

    if await asyncio.to_thread(landshare.ready):
        # Since step 176-26 nobody makes an account from an invitation: the share itself, where
        # rouh.land says who they are. An older letter's link lands there too, query and all.
        query = request.META.get("QUERY_STRING", "")
        return HttpResponseRedirect(there + ("?" + query if query else ""), status=303)
    # A comment thread to open once they are in: the letter that tagged
    # somebody with no account yet links here (`rouh/comments.py`). The form
    # posts back to this same address, so it is still here after the post.
    thread = _number(request.GET.get("comment"))
    # And the page of a task it is on, for a task shared with them to change.
    at = str(request.GET.get("at") or "")[:taskshare.AT_MAX]
    asked = {**({"at": at} if at else {}), **({"comment": thread} if thread else {})}
    if asked:
        there += "?" + urlencode(asked)
    user = await request.auser()
    if user.is_authenticated and sharing.Guests.belongs_to(share, user):
        return HttpResponseRedirect(there, status=303)
    if await asyncio.to_thread(_existing_account, share["email"]) is not None:
        return HttpResponseRedirect("/login?" + urlencode({"next": there, "email": share["email"]}), status=303)
    if request.method != "POST":
        return await asyncio.to_thread(_join_page, request, share, there=there)

    # Both names, always: Petar, 24 September 2026 (fr_a5aa0123f5d1), "the
    # registration of guest users needs to have first and last names
    # separately, and they need to be obligatory". Held here, not only by the
    # form, which a request need not come from.
    first_name, last_name = _name(request, "first_name"), _name(request, "last_name")
    missing = [field for field, value in (("first_name", first_name),
                                          ("last_name", last_name)) if not value]
    guest = _guest(share["email"], first_name, last_name)
    from rouh import signin

    needs_password = await asyncio.to_thread(lambda: not signin.can_send())
    first = request.POST.get("password1") or "" if needs_password else ""
    again = request.POST.get("password2") or "" if needs_password else ""
    problems: list[str] = []
    if not needs_password:
        pass
    elif first != again:
        problems.append("The two passwords are not the same.")
    else:
        try:
            await asyncio.to_thread(validate_password, first, guest)
        except ValidationError as exc:
            # A guest's username is their address, so Django's "too similar
            # to the username" would name something they never chose.
            problems.extend("The password is too like your name or email address."
                            if one.code == "password_too_similar" else said
                            for one in exc.error_list for said in one.messages)
    if problems or missing:
        return await asyncio.to_thread(_join_page, request, share, problems=problems,
                                       missing=missing, first_name=first_name,
                                       last_name=last_name, status=400, there=there)
    try:
        made = await asyncio.to_thread(_make_guest, guest, first)
    except IntegrityError:
        return HttpResponseRedirect("/login?" + urlencode({"next": there}), status=303)
    await alogin(request, made, backend="rouh.accounts.CaseInsensitiveBackend")
    log.info("a guest account was made from an invitation")
    return HttpResponseRedirect(there, status=303)


# --- through rouh.land: who is opening it (`rouh/landshare.py`) ---------------------------------


def _landshare_page(request, said: str, *, again: str = "", status: int = 400):
    response = render(request, "rouh/shared_in.html", {"said": said, "again": again}, status=status)
    for name, value in READER_HEADERS.items():
        response[name] = value
    return response


@only("GET")
async def shared_in(request: HttpRequest):
    """GET /shared/in?next=: somebody opening what was shared with them, not signed in here. On the
    relay address, sent to rouh.land to say who they are; anywhere else, first to the relay address,
    where the sign-in will be kept."""
    from rouh import landshare

    then = landshare._then(request.GET.get("next"))
    why = await asyncio.to_thread(landshare.refusal)
    if why:
        # A Rouh On its own: its own sign-in, as before.
        return HttpResponseRedirect("/login?" + urlencode({"next": then}), status=303)
    if not landshare.on_address(request):
        return HttpResponseRedirect(landshare.link(landshare.IN_PATH + "?" + urlencode({"next": then})),
                                    status=303)
    share = None
    token = then.split("/")[2] if then.startswith("/shared/") else ""
    if token:
        share = await asyncio.to_thread(lambda: _with_owner(_store().find(token.split("?")[0])))
    email = share["email"] if share else ""
    way = str(request.GET.get("go") or "")
    if way not in landshare.WAYS:
        # Who shared what, and that a rouh.land account is needed to view it: two presses, one to
        # create an account and one to sign in, and nothing is made or sent until one is pressed
        # (Petar, 11 November 2026: "a shared link to a project should ask you to make an account
        # to view it").
        return await asyncio.to_thread(_shared_door_page, request, share, then)
    go = await sync_to_async(landshare.start)(request, then, email, way)
    return HttpResponseRedirect(go, status=303)


def _shared_door_page(request, share, then: str):
    what = ("a task" if taskshare.is_task(share["rel"]) else "a page") if share else ""
    role = share["role"] if share else ""
    access = ("Can decide" if role == sharing.DECIDE else "Can edit" if role and sharing.can_edit(role)
              else "Can view") if share else ""
    q = {"next": then}
    response = render(request, "rouh/shared_in.html", {
        "door": True, "share": share, "what": what, "access": access,
        "door_up": "/shared/in?" + urlencode({**q, "go": "up"}),
        "door_in": "/shared/in?" + urlencode({**q, "go": "in"})}, status=200)
    for name, value in READER_HEADERS.items():
        response[name] = value
    return response


@only("GET")
async def shared_back(request: HttpRequest):
    """GET /shared/in/back?vouch=&state=: rouh.land's answer. Held to everything, then the person is
    the email it vouches for, signed in as the guest record by that email, and on to what they opened.
    The share itself still decides whether that email may open it (`_for_guest`)."""
    from rouh import landshare

    try:
        said = await sync_to_async(landshare.check)(request, request.GET.get("vouch", ""),
                                                    request.GET.get("state", ""))
    except landshare.Refused as exc:
        then = getattr(exc, "then", "")
        if then:
            # Opened on another device than the one that asked: ask again here, which rouh.land,
            # signed in now on this device, answers with one press.
            return HttpResponseRedirect(landshare.IN_PATH + "?" + urlencode({"next": then, "go": "in"}),
                                        status=303)
        log.info("landshare: an answer from rouh.land was not let in: %s", exc)
        return await asyncio.to_thread(_landshare_page, request, str(exc))
    try:
        guest = await asyncio.to_thread(landshare.guest_for, said["email"], said["land_id"])
    except landshare.NotAGuest as exc:
        return HttpResponseRedirect("/login?" + urlencode({"next": said["then"], "email": said["email"]}),
                                    status=303)
    except landshare.Refused as exc:
        return await asyncio.to_thread(_landshare_page, request, str(exc))
    await alogin(request, guest, backend="rouh.accounts.CaseInsensitiveBackend")
    await sync_to_async(landshare.vouched)(request)
    log.info("landshare: guest %s signed in by rouh.land", guest.pk)
    return HttpResponseRedirect(said["then"], status=303)


# --- a guest's own list --------------------------------------------------------------------


#: A task's status as the list of what is shared says it (`models.TASK_STATUSES`).
STATUS_WORDS = {"not-started": "Not started", "in-progress": "In progress",
                "waiting": "Waiting", "stopped": "Stopped", "done": "Done"}

_STEP_CODE = re.compile(r"^(\d+(?:-\d+)+)\.")
_TASK_NUMBER = re.compile(r"(?:^|/)(\d+)\.[^/]+/")


def _listed(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """What is shared with them, as two lists: the tasks, each with its number, its name and
    its status, newest task first; and the pages, newest share first, each with the task it is
    in. Petar, 14 October 2026: "when they log into Rouh they should see all the tasks".

    Only what the rows name: a task's number, name and status are read off that task's own
    row, by the folder the share names, and nothing else of the owner's is looked at.
    """
    from rouh.models import Task

    folders = {taskshare.folder_of(r["rel"]) for r in rows if taskshare.is_task(r["rel"])}
    found = {t.folder: t for t in Task.objects.filter(folder__in=folders - {""})}
    tasks, loose = [], []
    for row in rows:
        if not taskshare.is_task(row["rel"]):
            inside = _TASK_NUMBER.search(row["rel"])
            loose.append({**row, "in_task": inside.group(1) if inside else ""})
            continue
        folder = taskshare.folder_of(row["rel"])
        task = found.get(folder)
        name = folder.rsplit("/", 1)[-1]
        code = _STEP_CODE.match(name)
        number = (str(task.number) if task is not None and task.number is not None
                  else code.group(1) if code else "")
        title = (task.title if task is not None and task.title else
                 row["title"].split(": ", 1)[-1] if row["title"] else name)
        status = task.status if task is not None else ""
        tasks.append({**row, "number": number, "name": title, "step": bool(code),
                      "status": status, "status_words": STATUS_WORDS.get(status, ""),
                      "made": (task.created_at if task is not None else 0) or row["created_at"]})
    _levels_now(tasks, loose)
    tasks.sort(key=lambda r: r["made"], reverse=True)
    return tasks, loose


def _levels_now(tasks: list[dict], loose: list[dict]) -> None:
    """What they may do with each, as the one permission says it now (`rouh/task_access.py`):
    deciding for a quest reaches its goals, and a record above a page says what it is unless
    the page has its own. A quest's goals they have no row of their own for are listed too,
    each opened through the quest's own share (`taskshare.GOAL_MARK`). In place."""
    from rouh import task_access
    from rouh.models import Task
    from rouh.tenancy import Identity

    found: dict = {}
    for row in tasks + loose:
        key = (row["owner_id"], row["org_id"], row["email"])
        if key not in found:
            try:
                found[key] = task_access.for_email(
                    Identity(user_id=str(row["owner_id"]), org_id=str(row["org_id"])),
                    row["email"])
            except Exception:  # noqa: BLE001 - the row's own level still says it
                log.exception("sharing: the levels of a shared list could not be read")
                found[key] = None
        access = found[key]
        if access is not None:
            row["role"] = access.of_rel(row["rel"]) or row["role"]
    have = {taskshare.folder_of(r["rel"]) for r in tasks}
    for row in list(tasks):
        access = found.get((row["owner_id"], row["org_id"], row["email"]))
        if access is None:
            continue
        for number, goal in taskshare.linked_goals(
                config.assistant_repo, taskshare.folder_of(row["rel"])).items():
            level = access.of_rel(taskshare.PREFIX + goal["folder"])
            if goal["folder"] in have or not level:
                continue
            have.add(goal["folder"])
            task = Task.objects.filter(folder=goal["folder"]).first()
            status = task.status if task is not None else ""
            tasks.append({**row, "role": level, "number": number, "name": goal["title"],
                          "step": False, "status": status,
                          "status_words": STATUS_WORDS.get(status, ""), "through": row["number"],
                          "path": row["path"] + "?at=" + taskshare.GOAL_MARK + number,
                          "made": (task.created_at if task is not None else 0)
                          or row["made"]})


@only("GET")
async def shared_list(request: HttpRequest):
    """Everything shared with the address this account has: the tasks, then the pages."""
    rows = await asyncio.to_thread(_store().for_person, request.user)
    owners = await asyncio.to_thread(_owner_names, {r["owner_id"] for r in rows})
    for row in rows:
        row["owner_name"] = owners.get(row["owner_id"], "Somebody")
    tasks, loose = await asyncio.to_thread(_listed, rows)
    response = render(request, "rouh/shared.html", {
        "rows": rows, "tasks": tasks, "pages": loose,
        "me": request.user.email or request.user.username,
        "guest": bool(getattr(request.user, "is_guest", False)),
    })
    for name, value in READER_HEADERS.items():
        response[name] = value
    return response


def _owner_names(ids) -> dict[str, str]:
    from rouh.models import User

    wanted = [int(i) for i in ids if str(i).isdigit()]
    return {str(u.pk): _owner_name(u) for u in User.objects.filter(pk__in=wanted)}


# --- one page, for a reader who is not its owner ---------------------------------------------


@dataclass(frozen=True)
class Reader:
    """Who is reading which page, and what they may do with it."""

    rel: str
    title: str
    owner: str
    #: Whose questions and changes these are (`askai_threads`, `askai_edits`).
    who: Identity
    can_edit: bool
    #: Where this page's own routes are: `/shared/<token>/` or `/p/<token>/`.
    base: str
    most_a_day: int
    guest: bool
    #: The page as its owner shared it, which is whose comments are on it
    #: (`rouh/comments.py`), and whose history and options (`rouh/pagehistory.py`):
    #: a guest's own rows are kept under `tenancy.GUEST_ORG`, and a change a guest
    #: makes is filed under this. Only a person it was shared with sees comments:
    #: a visitor to a link is nobody, with no name to put on a comment.
    owner_id: str = ""
    org_id: str = ""
    comments: bool = False
    #: For a page inside a task shared to change: where it is in the task,
    #: which every one of this page's routes carries as `?at=`, and the
    #: task's own share, to go back to.
    at: str = ""
    task: str = ""


def _for_guest(request, token: str) -> Reader | None:
    # A share given an end that has passed is taken away before it is read (`rouh/share_ends.py`).
    from rouh import share_ends

    share_ends.before_open(token)
    share = _store().find(token)
    if not sharing.Guests.belongs_to(share, request.user):
        return None
    me = _rt().tenancy.current(request.user)
    if me is None:
        return None
    owner = _owner_names([share["owner_id"]]).get(share["owner_id"], "Somebody")
    rel, title, at, task = share["rel"], share["title"] or "A shared page", "", ""
    # What they may do is the one permission as it stands now (`rouh/task_access.py`): their
    # level here, inherited from a task or a quest above it unless something more specific
    # says otherwise; deciding includes editing.
    from rouh import task_access

    can_edit = sharing.can_edit(task_access.level_of_share(share))
    goal, _rest = taskshare.goal_of(str(request.GET.get("at") or ""))
    if goal and taskshare.is_task(rel):
        # Inside one of a shared quest's goals: their level there, which the quest's gives
        # unless something on the goal says otherwise.
        found = taskshare.linked_goals(config.assistant_repo, taskshare.folder_of(rel)).get(goal)
        can_edit = bool(found) and sharing.can_edit(task_access.level_of_share(
            {**share, "rel": taskshare.PREFIX + found["folder"]}))
    if taskshare.is_task(rel) and can_edit:
        # A task shared with this person to change: `?at=` naming one of its
        # pages, or one of its subtasks' (`taskshare.page_at`), is that page,
        # read and changed with Ask AI exactly as one page shared to change
        # is. Anywhere else in the task is the task's own view (`reader_view`).
        at = str(request.GET.get("at") or "")[:taskshare.AT_MAX]
        page = taskshare.page_at(config.assistant_repo, rel, at, person=True) if at else None
        try:
            named = pages.title_of(pages.check(config.assistant_repo, page, page)) \
                if page is not None else ""
        except (pages.Refused, OSError):
            page = None
        if page is not None:
            task, rel, title = f"/shared/{share['token']}", page, named or title
            # A page of its own may say less than the task it is in: the most specific wins.
            can_edit = sharing.can_edit(task_access.level_of_share({**share, "rel": page}))
    return Reader(rel=rel, title=title, owner=owner, who=me,
                  can_edit=can_edit, base=f"/shared/{share['token']}/",
                  most_a_day=0 if not getattr(request.user, "is_guest", False) else GUEST_A_DAY,
                  guest=True, owner_id=str(share["owner_id"]), org_id=str(share["org_id"]),
                  comments=True, at=at if task else "", task=task)


def _for_link(token: str) -> Reader | None:
    """A public page that may be changed. A read-only link is not a reader of
    this kind at all: it is served as it always was, with no Ask AI."""
    from rouh.models import PublicPage

    share = _rt().shares.find(token)
    if share is None or share["role"] != sharing.EDIT:
        return None
    row = PublicPage.objects.filter(token=share["token"]).values("user_id", "org_id").first()
    if row is None:
        return None
    owner = _owner_names([row["user_id"]]).get(row["user_id"], "Somebody")
    visitor = Identity(user_id="link:" + share["token"], org_id=row["org_id"],
                       name="a visitor with the link")
    return Reader(rel=share["rel"], title=share["title"] or "A shared page", owner=owner,
                  who=visitor, can_edit=True, base=f"/p/{share['token']}/",
                  most_a_day=LINK_A_DAY, guest=False, owner_id=str(row["user_id"]),
                  org_id=str(row["org_id"]))


async def _reader(request, kind: str, token: str, task: bool = False) -> Reader | None:
    """Who is reading, and what. A shared task is read on its own view
    (`reader_view`): it has no page, no Ask AI and no comments of its own, so
    every other route here answers it as not shared. One of its pages, for a
    person it was shared with to change, is a page like any other here, named
    by the `?at=` every route of it carries (`_for_guest`)."""
    if kind == "p":
        found = await asyncio.to_thread(_for_link, token)
    elif not request.user.is_authenticated:
        return None
    else:
        found = await asyncio.to_thread(_for_guest, request, token)
    if found is not None and taskshare.is_task(found.rel) != task:
        return None
    return found


def _not_here(kind: str) -> HttpResponse:
    headers = {**pages.HEADERS, "X-Robots-Tag": "noindex, nofollow, noarchive"} \
        if kind == "p" else pages.HEADERS
    response = HttpResponse("Not found.", status=404, content_type="text/plain")
    for name, value in headers.items():
        response[name] = value
    return response


async def reader_view(request: HttpRequest, kind: str, token: str):
    """The reader's page: a bar, and the shared page in a frame with Ask AI."""
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD"})
    reader = await _reader(request, kind, token)
    if reader is None and kind == "shared":
        reader = await _reader(request, kind, token, task=True)
        if reader is not None:
            await asyncio.to_thread(_opened, request, token)
            # A task shared with this person: the task, read only, every
            # place in it under this same address (`rouh/taskshare.py`).
            from . import views

            response = await views._task_response(
                {"rel": reader.rel, "owner_id": reader.owner_id},
                request.GET.get("at", ""), reader.base.rstrip("/"), pages.HEADERS,
                can_edit=reader.can_edit, home="/shared", person=True)
            response["X-Frame-Options"] = "DENY"
            return response
    if reader is None:
        if kind == "shared" and request.user.is_authenticated:
            return await asyncio.to_thread(_gone_page, request)
        return _not_here(kind)
    if kind == "shared":
        await asyncio.to_thread(_opened, request, token)
    get_token(request)             # the page's writes carry Django's token
    response = render(request, "rouh/reader.html", {
        "title": reader.title, "owner": reader.owner, "can_edit": reader.can_edit,
        "base": reader.base, "guest": reader.guest, "at": reader.at,
        # Back to the level of the task the page is on, for a page of a task.
        "back": (reader.task + ("?" + urlencode({"at": reader.at.rsplit("/", 1)[0]})
                                if "/" in reader.at else "")) if reader.task else "",
        "me": getattr(request.user, "email", "") if reader.guest else "",
    })
    for name, value in READER_HEADERS.items():
        response[name] = value
    if kind == "p":
        response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def _opened(request, token: str) -> None:
    """The person it was shared with opened it: kept for the owner's Share panel, while its
    switch is on (`rouh/share_opens.py`)."""
    from rouh import share_opens

    share_opens.opened(_store().find(token), str(getattr(request.user, "pk", "") or ""))


def _gone_page(request):
    response = render(request, "rouh/shared.html", {
        "rows": [], "gone": True, "me": request.user.email or request.user.username,
        "guest": bool(getattr(request.user, "is_guest", False))}, status=404)
    for name, value in READER_HEADERS.items():
        response[name] = value
    return response


def not_shared_page(request):
    """A page's link, opened by somebody signed in whom it does not let in.

    The same words as a `/shared/` link that is not theirs, over the list of
    what is shared with them, and a 403 rather than a 404: the link is real,
    it is only not for this account (`views.public_page`).
    """
    rows = _store().for_person(request.user)
    owners = _owner_names({r["owner_id"] for r in rows})
    for row in rows:
        row["owner_name"] = owners.get(row["owner_id"], "Somebody")
    tasks, loose = _listed(rows)
    response = render(request, "rouh/shared.html", {
        "rows": rows, "tasks": tasks, "pages": loose, "gone": True, "me": request.user.email or request.user.username,
        "guest": bool(getattr(request.user, "is_guest", False))}, status=403)
    for name, value in READER_HEADERS.items():
        response[name] = value
    response["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


def _at(reader: Reader) -> str:
    """The `?at=` a page inside a shared task is addressed with, or nothing."""
    return "?" + urlencode({"at": reader.at}) if reader.at else ""


def _number(raw) -> int:
    try:
        return max(0, int(str(raw or "0")[:12]))
    except ValueError:
        return 0


async def reader_markup(request: HttpRequest, kind: str, token: str):
    """The shared page itself, as the reader's frame takes it: sandboxed, with
    the Ask AI drawer in it, marked for pointing when it may be changed."""
    reader = await _reader(request, kind, token)
    if reader is None:
        return _not_here(kind)
    root = config.assistant_repo
    # Comments, for a person the page was shared with: `comment` is a thread
    # to open, from the link in a letter that tagged them.
    person = comments.person_of(request.user, owner=False) if reader.comments else None
    try:
        # The options kept over the page, which this reader may switch between
        # and pick the default of like anybody else. Not its history: an old
        # version can show what the owner took out before sharing it.
        options = await asyncio.to_thread(pagehistory.options_now, root, reader.org_id,
                                          reader.rel)
        drawer = await asyncio.to_thread(
            askai.drawer_head, root, reader.rel, False,
            modeldefaults.use_model("askai", reader.org_id, config),
            can_edit=reader.can_edit, shown_as=reader.title,
            open_thread=_number(request.GET.get("thread")), scroll=_number(request.GET.get("y")),
            comments=comments.page_config(person, _number(request.GET.get("comment")),
                                          ai_pass=reader.can_edit)
            if person else None, options=options, highlights=person is not None)
        body, kind_of = await asyncio.to_thread(pages.read, root, reader.rel, reader.rel,
                                                reader.base + "page" + _at(reader), drawer,
                                                reader.can_edit or bool(options))
    except (pages.Refused, OSError):
        response = HttpResponse("This page is not there any more.", status=404,
                                content_type="text/plain")
    else:
        response = HttpResponse(body, content_type=kind_of)
    for name, value in pages.HEADERS.items():
        response[name] = value
    return response


async def reader_ask(request: HttpRequest, kind: str, token: str):
    """One question about the shared page, answered - and the page changed,
    when this reader may and asked for it."""
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    reader = await _reader(request, kind, token)
    if reader is None:
        return refuse("That page is not shared with you.", 404)
    asked = body_of(request)
    response = StreamingHttpResponse(
        askai.answer(config, _rt().ask_threads, reader.who, reader.rel, asked,
                     can_edit=reader.can_edit, most_a_day=reader.most_a_day,
                     page_org=reader.org_id),
        content_type="text/event-stream")
    response["Cache-Control"] = "no-store, private"
    response["X-Accel-Buffering"] = "no"
    return response


async def reader_threads(request: HttpRequest, kind: str, token: str):
    reader = await _reader(request, kind, token)
    if reader is None:
        return refuse("That page is not shared with you.", 404)
    return answer(await asyncio.to_thread(_rt().ask_threads.threads, reader.who, reader.rel),
                  headers=NO_STORE)


async def reader_thread(request: HttpRequest, kind: str, token: str, thread_id: int):
    reader = await _reader(request, kind, token)
    if reader is None:
        return refuse("That page is not shared with you.", 404)
    return answer(await asyncio.to_thread(_rt().ask_threads.messages, reader.who, reader.rel,
                                          thread_id), headers=NO_STORE)


async def reader_undo(request: HttpRequest, kind: str, token: str):
    """Put the page back as it was before one of this reader's own changes."""
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    reader = await _reader(request, kind, token)
    if reader is None or not reader.can_edit:
        return refuse("That page is not shared with you.", 404)
    try:
        done = await asyncio.to_thread(askai.undo, config.assistant_repo, reader.who,
                                       reader.rel, body_of(request).get("edit"))
    except (askai.EditRefused, askai.Unavailable) as exc:
        return refuse(str(exc), 409)
    return answer(done, headers=NO_STORE)


async def reader_type(request: HttpRequest, kind: str, token: str):
    """What this reader typed straight into the page's text, for a reader who
    may change the page (`askai.type_text`)."""
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    reader = await _reader(request, kind, token)
    if reader is None or not reader.can_edit:
        return refuse("That page is not shared with you.", 404)
    try:
        done = await asyncio.to_thread(askai.type_text, config.assistant_repo, reader.who,
                                       reader.rel, body_of(request), reader.org_id)
    except (askai.EditRefused, askai.Unavailable) as exc:
        return refuse(str(exc), 409)
    return answer(done, headers=NO_STORE)


async def reader_option(request: HttpRequest, kind: str, token: str):
    """Make one version of an option on the shared page the default - which
    anybody who can read the page may do - or, for a reader who may change
    the page, stop offering it."""
    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    reader = await _reader(request, kind, token)
    if reader is None:
        return refuse("That page is not shared with you.", 404)
    from . import views

    return await views.option_action(config.assistant_repo, reader.who, reader.org_id,
                                     reader.rel, body_of(request), reader.can_edit)


def routes(kind: str):
    """The views of one kind of reader, each with `kind` filled in."""
    def bind(view):
        async def bound(request, token, **more):
            return await view(request, kind, token, **more)
        bound.__name__ = f"{view.__name__}_{kind}"
        return bound
    return {name: bind(view) for name, view in (
        ("view", reader_view), ("page", reader_markup), ("ask", reader_ask),
        ("threads", reader_threads), ("thread", reader_thread), ("undo", reader_undo),
        ("type", reader_type), ("option", reader_option))}


SHARED = routes("shared")
LINK = routes("p")

__all__ = ["invite", "uninvite", "join", "shared_in", "shared_back", "shared_list", "not_shared_page", "SHARED", "LINK"]
