"""To send from your mail: a reply a task drafted for ‹him› to send from ‹his› own mail, waiting on
the task's page with Write it in Gmail, until ‹he› has sent it.

Built by the nightly feature run, night 24, 27 October 2026 (task 94, idea I-148). ‹His› own
inbox is read-only to Rouh, so a reply a job prepares for ‹him› is sent by ‹him›, by hand, from
‹his› own mail (Sent by you, `rouh/sent_by_you.py`, keeps what ‹he› sent). On 26 October 2026 a
job drafted "Next steps after the interviews" to a client for task 93 and wrote it into the
task's notes; ‹he› looked for it among the task's steps and said "I can't seem to find it. 93 has
many sub tasks none called next steps after the interviews". The draft had to be put on the
screen again, and copied from there into Gmail field by field: whom it goes to, the subject, the
words.

So, while its switch is on, two things happen:

- **Every run is told** (`for_runs`, after Sent by you's rule): the entry it adds to the task's
  `sends_himself` list carries the draft's whole text too, as `body`.
- **The task's own page has a section, To send from your mail**, last, after its work, for as
  long as a reply in its `sends_himself` list is neither sent (Sent by you marks it) nor let go:
  the subject, whom it goes to, which mailbox, when it was drafted, the draft itself in a closed
  section, and **Write it in Gmail**, which opens Gmail's own new-message window in that mailbox
  with whom it goes to, the subject and the words already in, so sending it is one press there;
  **Open the email** when the run named the thread it answers; and **Not sending**, which lets
  it go (Sent by you stops looking for it) with Undo.

**No model call.** Nothing is sent, and nothing in the mailbox changes: Gmail opens in ‹his›
browser, and ‹he› presses Send there or not.

**Whose.** The task's own meta in ‹his› workspace (`rouh/taskmeta.py`), on ‹his› own page,
for ‹him› signed in.

**Its switch** is `to_send` (`rouh/switches.py`): off, no section and no line for runs.
"""
from __future__ import annotations

import html
import logging
import time
from datetime import date
from urllib.parse import quote, urlencode

log = logging.getLogger("rouh.to_send")

SWITCH = "to_send"
TITLE = ("To send from your mail: a reply a task drafted for you to send yourself waits on the "
         "task's page, with Write it in Gmail, until you have sent it")
#: The longest draft carried into Gmail's address (Gmail's own window takes about this much).
BODY_MOST = 6000
#: The most replies listed.
MOST = 10

RULE = ("Put the draft's whole text in that entry too, as `\"body\"`, exactly as the person is to "
        "send it, so the task's page can open it in their own mail in one press.")


class Refused(ValueError):
    """What cannot be done, in the words the page shows."""


def on(who=None, org=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org or getattr(who, "org_id", None) or None)


def for_runs(org: str) -> str:
    """One more line for every run, after Sent by you's rule, or "" (off, or Sent by you off)."""
    from . import sent_by_you

    try:
        if not org or not on(org=org) or not sent_by_you.on(org):
            return ""
        return RULE
    except Exception:  # noqa: BLE001 - a run starts whatever this says
        log.exception("to send could not be put in a run's instructions")
        return ""


def _waiting(entry) -> bool:
    from . import sent_by_you

    return sent_by_you._waiting(entry)


def compose_link(entry: dict) -> str:
    """Gmail's own new-message window, in the mailbox the reply goes from, filled in."""
    subject = str(entry.get("subject") or "").strip()
    if entry.get("thread") and subject and not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    asked = {"view": "cm", "fs": "1", "to": str(entry.get("to") or "").strip(), "su": subject}
    body = str(entry.get("body") or "")
    if body:
        asked["body"] = body[:BODY_MOST]
    inbox = str(entry.get("inbox") or "").strip()
    if inbox:
        asked = {"authuser": inbox, **asked}
    return "https://mail.google.com/mail/?" + urlencode(asked, quote_via=quote)


def thread_link(entry: dict) -> str:
    thread = str(entry.get("thread") or "").strip()
    if not thread or not thread.isalnum():
        return ""
    inbox = str(entry.get("inbox") or "").strip()
    who = f"?authuser={quote(inbox)}" if inbox else ""
    return f"https://mail.google.com/mail/{who}#all/{thread}"


def _when(entry: dict) -> str:
    try:
        day = date.fromisoformat(str(entry.get("since") or "")[:10])
    except ValueError:
        return ""
    ago = (date.today() - day).days
    said = f"{day.day} {day.strftime('%B')}"
    return said + (" (today)" if ago <= 0 else " (yesterday)" if ago == 1 else f" ({ago} days ago)")


def waiting(root, rel: str) -> list[tuple[int, dict]]:
    """The replies of the task at ``rel`` still to be sent, with their places in its list."""
    from . import sent_by_you, taskmeta

    data = taskmeta.get(rel, root)
    return [(n, e) for n, e in enumerate(sent_by_you._entries(data)) if _waiting(e)][:MOST]


def section(person, root, rel: str) -> str:
    """The section on a task's own page; "" when off, nobody is signed in, or nothing waits."""
    from . import steps

    if person is None or not rel or steps.is_step(rel):
        return ""
    try:
        if not on(person):
            return ""
        found = waiting(root, rel)
    except Exception:  # noqa: BLE001 - the page is drawn without it
        log.exception("the replies to send under %s could not be read", rel)
        return ""
    if not found:
        return ""
    rows = []
    for n, entry in found:
        subject = str(entry.get("subject") or "").strip() or "(no subject)"
        to = str(entry.get("to") or "").strip()
        inbox = str(entry.get("inbox") or "").strip()
        when = _when(entry)
        step = str(entry.get("step") or "").strip()
        # The task's own number is the page it is on already (W2): only a step is named.
        if step and rel.rsplit("/", 1)[-1].split(".", 1)[0] == step:
            step = ""
        about = " · ".join(x for x in (
            f"to {to}" if to else "", f"from {inbox}" if inbox else "",
            f"drafted {when}" if when else "", f"in {step}" if step else "") if x)
        body = str(entry.get("body") or "").strip()
        draft = (f'<details class="osend-draft"><summary>The draft</summary>'
                 f'<pre>{html.escape(body)}</pre></details>') if body else ""
        opened = thread_link(entry)
        rows.append(
            f'<div class="osend" data-n="{n}" data-subject="{html.escape(subject, quote=True)}">'
            f'<p class="osend-line"><span class="osend-what">{html.escape(subject)}</span>'
            f'<span class="osend-about">{html.escape(about)}</span></p>{draft}'
            f'<p class="osend-acts"><a class="obtn osend-write" target="_blank" rel="noopener" '
            f'href="{html.escape(compose_link(entry), quote=True)}">Write it in Gmail</a>'
            + (f'<a class="obtn osend-open" target="_blank" rel="noopener" '
               f'href="{html.escape(opened, quote=True)}">Open the email</a>' if opened else "")
            + '<button type="button" class="obtn osend-skip" hidden>Not sending</button>'
              '<span class="osend-said" role="status"></span></p></div>')
    return (f'<section class="oset osends" id="tkToSend" aria-label="To send from your mail">'
            f'<h2 class="divider">To send from your mail<span class="c">{len(found)}</span></h2>'
            f'<div class="rows">{"".join(rows)}</div></section>')


def act(person, root, rel: str, n, do: str, subject: str = "") -> dict:
    """One press on a reply: ``opened`` (Write it in Gmail), ``let_go`` (Not sending) or
    ``undo``."""
    from . import evolution, sent_by_you, steps, taskmeta

    if person is None or not on(person):
        raise Refused("To send from your mail is switched off.")
    if not rel or steps.is_step(rel):
        raise Refused("That is not a task's page.")
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise Refused("That reply is not on this task.") from None
    entries = sent_by_you._entries(taskmeta.get(rel, root))
    entry = entries[n] if 0 <= n < len(entries) and isinstance(entries[n], dict) else None
    if entry is None or (subject and str(entry.get("subject") or "").strip() != subject.strip()):
        raise Refused("That reply is not on this task any more. Reload the page.")
    if do == "opened":
        evolution.used(SWITCH, "opened", who=person, detail=f"Write it in Gmail: {entry.get('subject')}")
        return {"ok": True}
    if do not in ("let_go", "undo"):
        raise Refused("That is not something this does.")

    def how(data):
        held = sent_by_you._entries(data or {})
        if n < len(held) and isinstance(held[n], dict):
            one = dict(held[n])
            if do == "let_go":
                one["let_go"] = date.today().isoformat()
                one["let_go_by"] = "person"
            else:
                one.pop("let_go", None)
                one.pop("let_go_by", None)
            held[n] = one
            data[sent_by_you.KEY] = held[0] if isinstance(data.get(sent_by_you.KEY), dict) else held
        return data

    done = taskmeta.change(rel, how, root, by="the person, on the task's page")
    if done is None:
        raise Refused("The task's notes could not be changed. Try again in a moment.")
    if do == "let_go":
        evolution.used(SWITCH, "let_go", who=person, detail=f"Not sending: {entry.get('subject')}")
    return {"ok": True, "at": time.time()}


__all__ = ["Refused", "SWITCH", "TITLE", "act", "compose_link", "for_runs", "on", "section",
           "thread_link", "waiting"]
