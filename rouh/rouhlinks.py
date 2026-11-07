"""A link to Rouh itself, read inside Rouh, as the person who is talking.

Petar, 6 October 2026, by voice: "I definitely want when I send you a link to
our system that you look things up in the system, not through the browser."

He had pasted a link to a mail case on Rouh's own address, ending #approval-2,
into a chat ("Approval process untangling") and asked for the details of that
approval. The model reached for web_fetch, which runs on Anthropic's side and
could not reach Rouh's address at all; the second try (`rouh/fetchfallback.py`) then
opened the address in a headless browser, which carries none of his logins and
read the sign-in page. Three tries in that chat, and the approval was never
read once.

What happens now
----------------

An address on one of Rouh's own names - `ROUH_PUBLIC_HOSTS`, the public URL's own host and port, and any
retired name the installation still answers to (`ROUH_RETIRED_HOSTS`) - is never
read from outside. It is turned into the object it
names and read here, as the speaker (`tenancy.speaker`), through the same
checks the page itself makes:

- a mail case is the speaker's own or "There is no such case", exactly as
  `/mail/case/<key>` answers (`CaseDesk.view` is scoped by user and org), and
  the part after `#` picks the step it points at, `#approval-2` being the
  second time the case asked for a decision (`case_trace.build`);
- decisions, reminders, goals and the rest go through the tools that already
  read them for the speaker, or through the very view the page asks
  (`_api`), handed the speaker's own account;
- tasks, projects, chats, runs, cards and workspace pages are behind the
  sign-in and nothing more, as on the page, so anybody signed in who is not a
  guest reads them, and a guest reads nothing here at all.

Three ways in, one reader:

1. `read_rouh_link`, a tool of Rouh's own (`tools.py`), which the prompt tells
   the model to use for these addresses (`brain.ROUH_LINKS`).
2. web_fetch, out of habit. Rouh's own names are its `blocked_domains`, so
   Anthropic refuses the fetch at once without going near the server, and a
   web_fetch of one of them, refused or not, has its reply cut there and
   answered with this reader instead (`fetchfallback.Second`), the way a
   page that failed is answered with a browser.
3. The browser tool and the headless reader both refuse these names and say
   to use this instead (`browsing.py`).

A route nobody has mapped yet says so - "This kind of Rouh page is not
supported yet: <path>" - and tells the model to say that in a sentence,
rather than failing quietly or leaving it to guess.

What came from outside - an email, a message, a page, a file - is boxed as
somebody else's words (`untrusted.py`), inside Rouh's own line saying what
was read and as whom.
"""
from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import logging
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit

from . import untrusted

log = logging.getLogger("rouh.rouhlinks")

#: The tool, and the call Rouh adds to a reply it cut at a web_fetch of one of
#: its own addresses (`fetchfallback.py`).
TOOL = "read_rouh_link"

def retired() -> tuple[str, ...]:
    """Names this installation answered to once and its web server still sends here.

    The installation's own (`ROUH_RETIRED_HOSTS`, comma separated, blank by
    default), never a name written here.
    """
    from .config import _env

    return tuple(h.strip().lower() for h in _env("ROUH_RETIRED_HOSTS").split(",") if h.strip())

#: The most text one read hands back. A mail case's whole trace is far more.
MOST = 24000

#: Whose words each kind of page carries, for its box.
SOURCE = {
    "mail": ("a mail case in Rouh: the email or message as its sender wrote it, and what "
             "Rouh's turns made of it"),
    "chat": "a conversation in Rouh, whose words may quote pages, emails and files",
    "file": "a file from the workspace, which may quote anything",
    "page": "a page in the workspace, which may quote anything",
    "data": "a page of Rouh's own, which may quote emails, pages and files written by others",
}


@dataclass
class Got:
    """One link read: what the model is handed, and what its line on the screen says."""

    ok: bool
    text: str
    #: What it was, in a few words, for the line on the screen.
    title: str = ""
    #: Rouh's own address of it, for the line on the screen.
    url: str = ""
    kind: str = ""
    extra: dict = field(default_factory=dict)


# --- which addresses are Rouh's own ---------------------------------------------------


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


def names(cfg) -> list[str]:
    """Rouh's own names, which answer on any port: never an IP address or localhost."""
    try:
        listed = cfg.public_host_list()
    except Exception:  # noqa: BLE001 - a config without the list still has the old names
        listed = []
    out = {h for h in (*listed, *retired()) if h and h != "localhost" and not _is_ip(h)}
    out |= {"www." + h for h in out if not h.startswith("www.")}
    return sorted(out)


def blocked(cfg) -> list[str]:
    """What web_fetch is told never to fetch: Rouh's own names (`tools.py`)."""
    return [h for h in names(cfg) if not h.startswith("www.")]


def _split(url: str):
    said = str(url or "").strip()
    if not said or any(c.isspace() for c in said) or len(said) > 4000:
        return None
    if "://" not in said:
        said = "https://" + said.lstrip("/")
    try:
        parts = urlsplit(said)
        parts.port  # noqa: B018 - a port that is not a number raises here
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts


def own(url: str, cfg) -> bool:
    """Whether an address is one of Rouh's own pages, wherever it is written.

    One of Rouh's names on any port, or exactly the host and port of this
    server's public URL, which in a test world is 127.0.0.1 and the world's
    own port and nothing else on that machine.
    """
    if cfg is None:
        return False
    parts = _split(url)
    if parts is None:
        return False
    host = (parts.hostname or "").lower()
    if host in names(cfg):
        return True
    mine = _split(getattr(cfg, "public_url", "") or "")
    if mine is None or (mine.hostname or "").lower() != host:
        return False
    default = {"http": 80, "https": 443}
    return (parts.port or default[parts.scheme]) == (mine.port or default[mine.scheme])


# --- who is asking ----------------------------------------------------------------------


async def _speaker():
    from .tenancy import Tenancy, speaker

    return speaker() or await asyncio.to_thread(Tenancy().only_person)


def _refused(url: str, why: str) -> Got:
    return Got(False, untrusted.ours(why), title="refused", url=url)


# --- reading one ------------------------------------------------------------------------


async def read(tools, url: str, who=None) -> Got:
    """The page one of Rouh's own addresses names, read inside Rouh as `who`.

    `who` is the speaker when left out. Never raises: what went wrong is the
    answer's own text.
    """
    from . import mail_turn
    from .tenancy import GUEST_ORG

    cfg = getattr(tools, "cfg", None)
    parts = _split(url)
    if parts is None or not own(url, cfg):
        return _refused(str(url or ""), (
            f"{url!r} is not an address of Rouh's own, so there is nothing to read inside "
            "Rouh. A page on the web is web_fetch's."))
    turn = mail_turn.now()
    if turn is not None and not getattr(turn, "from_owner", getattr(turn, "from_petar", False)):
        # An email or a message from somebody else is never a way into the
        # person's own pages, whatever link it carries.
        return _refused(url, (
            "This turn is about somebody else's email or message, and Rouh's own pages are "
            "never read for one. Say that the link was not opened."))
    who = who or await _speaker()
    if who is None:
        return _refused(url, (
            "Nobody is signed in on this turn, so Rouh cannot tell whose page this is and "
            "did not open it. Say so in one sentence."))
    if getattr(who, "org_id", "") == GUEST_ORG:
        return _refused(url, "A guest reads only the pages shared with them, so this was not opened.")
    path = unquote(parts.path or "/")
    query = parse_qs(parts.query or "", keep_blank_values=False)
    fragment = unquote(parts.fragment or "").strip()
    here = path + (f"?{parts.query}" if parts.query else "") + (f"#{fragment}" if fragment else "")
    try:
        got = await _route(tools, who, path, query, fragment)
    except Exception as exc:  # noqa: BLE001 - a link read must never end the turn
        log.exception("reading Rouh's own %s failed", path)
        return Got(False, untrusted.ours(
            f"Rouh could not read its own page {here}: {type(exc).__name__}: {exc}. Say that "
            "plainly, and do not answer as if you had read it."), title="failed", url=url)
    if got is None:
        return Got(False, untrusted.ours(
            f"This kind of Rouh page is not supported yet: {path}. It was not opened in a "
            "browser either, because from outside it is only a sign-in page. Say in one "
            "sentence that reading this kind of Rouh page is not supported yet, and do not "
            "guess what it shows."), title="not supported yet", url=url, kind="unsupported")
    got.url = got.url or url
    name = getattr(who, "name", "") or getattr(who, "email", "") or "the person"
    # The first line is what the call's line on the screen says (`brain._run_tools`).
    head = (f"Read inside Rouh as {name}, never through the web: {got.title or here}\n"
            f"Address: {here}\n")
    beside = (query.get("chat") or [""])[0]
    if beside and not path.startswith("/chat/"):
        head += (f"The address also opens chat {beside} beside it; read /chat/{beside} for "
                 "that conversation.\n")
    body = got.text
    if len(body) > MOST:
        body = body[:MOST] + "\n... the rest is cut off here."
    got.text = untrusted.ours(head + "\n" + body)
    log.info("read Rouh's own %s for user %s: %s", path, getattr(who, "user_id", "?"),
             "ok" if got.ok else "not ok")
    return got


# Each route: a pattern over the path, and the reader for it. In the order
# the URL config has them (`rouh/project/urls.py`): the narrow before the wide.
async def _route(tools, who, path: str, query: dict, fragment: str) -> Got | None:
    from . import addressing, pages, sharing

    found = re.fullmatch(r"/mail/case/([A-Za-z0-9_-]{6,80})(/.*)?", path)
    if found:
        return await _mail_case(tools, who, found.group(1), found.group(2) or "", fragment)
    if path.rstrip("/") == "/mail/approvals":
        return await _approvals(who)
    # A decision by its number, or by the handle (a482) it had before 18 October 2026.
    found = re.fullmatch(r"/decisions(?:/(\d+|[A-Za-z]\d{3,4}))?/?", path)
    if found:
        ref = found.group(1) or ""
        return await _tool(tools, "decisions", {"action": "read", "id": ref}
                           if ref else {"action": "list"}, "decision", "data",
                           title=f"decision {ref}" if ref else "decisions")
    if path.rstrip("/") in (addressing.CLOCKWORK, addressing.REMINDERS_OLD):
        return await _tool(tools, "upcoming", {}, "clockwork", "data", title="Clockwork")
    if path.rstrip("/") == addressing.GOALS:
        return await _tool(tools, "goals", {}, "goals", "data", title="goals")
    # Gene therapy, and /feedback, its address while it was Feedback: the whole board.
    if path.rstrip("/") in (addressing.GENE_THERAPY, addressing.GENE_THERAPY_OLD):
        return await _api(who, "/api/gene-therapy", "gene-therapy", title="Gene therapy")
    found = re.fullmatch(r"/(quests)(?:/(\d+))?/?", path)
    if found:
        return await _api(who, "/api/quests" + (f"/{found.group(2)}" if found.group(2) else ""),
                          "quest", title=f"quest {found.group(2)}" if found.group(2) else "quests")
    if path.rstrip("/") == addressing.CONTROL:
        return await _api(who, "/api/control", "control", title="the Control Room")
    if path.rstrip("/") == addressing.BRIEF:
        return await _api(who, "/api/brief", "brief", title="today's brief")
    if path.rstrip("/") == addressing.BRIEF + "/past":
        return await _api(who, "/api/brief/past", "brief", title="the past briefs")
    found = re.fullmatch(re.escape(addressing.BRIEF) + r"/(\d{4}-\d{2}-\d{2})/?", path)
    if found:
        return await _api(who, f"/api/brief/day/{found.group(1)}", "brief",
                          title=f"the brief of {found.group(1)}")
    found = re.fullmatch(r"/synapse(?:/(improvements)(?:/(\d+))?|/([0-9a-f-]{36}))?/?", path)
    if found:
        if found.group(1):
            return await _api(who, "/api/synapse/improvements"
                              + (f"/{found.group(2)}" if found.group(2) else ""),
                              "synapse", title="Synapse improvements")
        if found.group(3):
            return await _api(who, f"/api/synapse/ds/{found.group(3)}", "synapse",
                              title="a Synapse dataset")
        return await _api(who, "/api/synapse/home", "synapse", title="Synapse")
    if (path.rstrip("/") in (addressing.METABOLISM, addressing.RUNS_OLD)
            or re.fullmatch(r"/(?:metabolism|runs)/(?:everyday|mutations)/?", path)):
        return await _runs()
    if path.rstrip("/") == addressing.BROWSER:
        return await _workspace_file(tools, "_tasks.md", "", title="the task list")
    for kind in addressing.KINDS:
        if path.startswith(f"/{kind}/"):
            return await _object(tools, kind, path[len(kind) + 2:], fragment, query)
    if path.startswith(pages.ROUTE):
        return await _workspace_page(tools, path[len(pages.ROUTE):], fragment, query)
    found = re.fullmatch(re.escape(sharing.ROUTE) + r"([A-Za-z0-9_-]{8,80})/?", path)
    if found:
        return await _public(tools, found.group(1), fragment)
    if path in ("", "/", "/one/"):
        return Got(True, "This is Rouh's front page. It shows nothing by itself: nothing on it "
                         "names a chat, a task or a page.", title="the front page")
    return None


async def _tool(tools, name: str, args: dict, kind: str, source: str, *, title: str) -> Got:
    """One of the tools that already reads this for the speaker, called as the turn would."""
    async def quiet(_message):
        return None

    out = await tools.call(name, args, quiet)
    text = untrusted.inner(out) if untrusted.is_wrapped(out) else str(out)
    return Got(True, untrusted.wrap(text, SOURCE[source]) if source != "data" else text,
               title=title, kind=kind)


# --- one view of the page, as the person -------------------------------------------------


async def _api(who, path: str, kind: str, *, title: str) -> Got:
    """What the page asks the server for at this address, asked of the same view with
    the speaker's own account, so every check it makes is made here too."""
    from asgiref.sync import iscoroutinefunction, sync_to_async
    from django.test import RequestFactory
    from django.urls import Resolver404, resolve

    from .models import User

    try:
        user = await asyncio.to_thread(User.objects.get, pk=int(who.user_id))
    except (User.DoesNotExist, ValueError, TypeError):
        return Got(False, f"There is no account {who.user_id} here, so {path} was not read.",
                   title=title, kind=kind)
    try:
        match = resolve(path)
    except Resolver404:
        return Got(False, f"Rouh answers nothing at {path}.", title=title, kind=kind)
    request = RequestFactory().get(path, HTTP_HOST="127.0.0.1")
    request.user = user
    view = match.func
    if iscoroutinefunction(view):
        response = await view(request, *match.args, **match.kwargs)
    else:
        response = await sync_to_async(view)(request, *match.args, **match.kwargs)
    raw = bytes(getattr(response, "content", b"") or b"").decode("utf-8", "replace")
    if response.status_code >= 400:
        try:
            said = json.loads(raw).get("error") or raw
        except (ValueError, AttributeError):
            said = raw
        return Got(False, f"Rouh refused {path} for this person: {str(said)[:400]}",
                   title=title, kind=kind)
    try:
        data = json.loads(raw)
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    except ValueError:
        text = _html_text(raw)
    return Got(True, untrusted.wrap(text, SOURCE["data"]), title=title, kind=kind)


# --- mail cases ------------------------------------------------------------------------


def _desk():
    from . import runtime

    alerts = getattr(runtime, "mail_alerts", None)
    return alerts.cases if alerts is not None else None


async def _mail_case(tools, who, key: str, rest: str, fragment: str) -> Got:
    desk = _desk()
    if desk is None:
        return Got(False, "New mail is not handled on this server, so there are no mail cases "
                          "to read.", title="no mail cases", kind="mail")
    got = await asyncio.to_thread(_case_text, desk, who, key, rest, fragment)
    if got is None:
        # The page's own words, for a key that is not this person's: another
        # person's case is "not there", never "not yours".
        return Got(False, f"There is no such case ({key}) for this person. Say so; do not "
                          "guess what it holds.", title="no such case", kind="mail")
    return got


def _case_text(desk, who, key: str, rest: str, fragment: str) -> Got | None:
    """One case as text: what it is, the step the address points at whole, and the rest
    one line each. `CaseDesk.view` is the page's own check: the speaker's case or None."""
    from . import case_trace

    view = desk.view(who, key)
    if view is None:
        return None
    case = view["case"]
    trace = case_trace.build(case, desk.store, contact_now=view["contact"],
                             working=view["working"], state=view["state"])
    steps = trace["steps"]
    email = case.email or {}
    # Where it is, exactly as its page says it at the top, from its ledger judged now and
    # what is live (`case_state`, MAIL.md D14): never a stored route or an earlier diagnosis.
    state = view["state"]
    action = state.action or {}
    lines = [f"{view['kind']} case from {case.sender_name} <{view['from_said']}>, received "
             f"{view['received']}.",
             f"Subject: {email.get('subject') or case.subject or '(none)'}",
             f"Where it is now: {state.words}. {state.line}",
             ("What the person does next: press " + json.dumps(action.get("label"))
              + (f" on Decision {action['number']} (on the case page at its top, or on "
                 "Decisions)" if action.get("number") else " on the case page")
              + (f". It {action['detail'][:1].lower()}{action['detail'][1:].rstrip('.')}"
                 if action.get("detail") else "") + "." if action else
              f"Nothing of it is the person's to press now: it waits on {state.waits_on}."
              if state.waits_on else "Nothing of it waits for the person."),
             "Running now: " + ("yes" if state.working else "no") + ".",
             f"Attempt {view['attempt_no']}."]
    ready = [a for a in state.asks if a.possible]
    for a in ready:
        lines.append(f"Ask \u201c{a.named}\u201d failed ({a.why.rstrip('.')}); a run does it: "
                     f"{a.possible}.")
    if view.get("summary"):
        lines.append(f"What Rouh made of it when it read it: {view['summary']}")
    if view.get("chat_link"):
        lines.append(f"Its own chat: {view['chat_link']}")
    pointed = next((s for s in steps if fragment and (s["id"] == fragment or
                                                      s.get("card") == fragment)), None)
    if rest:
        lines.append(f"The address goes on past the case ({rest}); this is the case itself.")
    if fragment and pointed is None:
        lines.append(f"The address points at #{fragment}, which is not one of this case's "
                     "steps; the whole case is below.")
    asked = [s for s in steps if s["kind"] == "approval"]
    if pointed is not None:
        lines += ["", f"# The step the address points at: #{pointed['id']}"]
        if pointed["kind"] == "approval":
            number = asked.index(pointed) + 1
            lines.append(f"This is decision {number} of {len(asked)} the case asked for.")
            lines.append(_approval_text(pointed))
        else:
            lines.append(case_trace.step_text(case, pointed)[:12000])
    if asked:
        lines += ["", f"# Every decision this case asked for ({len(asked)})"]
        for n, s in enumerate(asked, 1):
            a = s.get("approval") or {}
            lines.append(f"{n}. #{s['id']}, asked {a.get('asked') or s['when']}: "
                         f"{a.get('status') or s.get('status') or '?'}"
                         + (f", decided {a['decided']}" if a.get("decided") else "")
                         + (f". {a['why_invalid']}" if a.get("why_invalid") else ""))
    open_one = view.get("approval")
    if open_one is not None:
        lines += ["", "Waiting for the person's decision now. It does not run out: it waits "
                      "until they answer, or until the message, its conversation, the proposal "
                      "or the contact's permissions change."]
    lines += ["", "# Every step, one line each (read #<id> for one whole)"]
    for s in steps:
        lines.append(f"- #{s['id']} {s['title']} at {s['when']}"
                     + (f" [{s['status']}]" if s.get("status") else "")
                     + (f": {_one_line(s['summary'], 200)}" if s.get("summary") else ""))
    if view.get("reply_sent"):
        lines += ["", "The reply that was sent:", str(view["reply_sent"])[:3000]]
    lines += ["", "# The message itself", (email.get("body") or "")[:6000]]
    body = "\n".join(lines)
    return Got(True, untrusted.wrap(body, SOURCE["mail"]),
               title=f"mail case from {case.sender_name}"
               + (f", {pointed['title'].lower()} (#{pointed['id']})" if pointed else ""),
               kind="mail")


def _approval_text(step: dict) -> str:
    a = step.get("approval") or {}
    out = [f"Status: {a.get('status') or step.get('status') or '?'}",
           f"Asked: {a.get('asked') or step.get('when')}"]
    if a.get("decided"):
        out.append(f"Decided: {a['decided']}")
    if a.get("why_invalid"):
        out.append(f"Why it no longer stands: {a['why_invalid']}")
    if step.get("summary"):
        out.append(f"What it asked: {step['summary']}")
    if a.get("action"):
        out.append(f"The action proposed:\n{a['action']}")
    if a.get("reply"):
        out.append(f"The reply proposed{' (edited)' if a.get('edited') else ''}:\n{a['reply']}")
    if a.get("instruction"):
        out.append(f"The person's instruction: {a['instruction']}")
    files = [f.get("name") for f in step.get("files") or [] if isinstance(f, dict)]
    if files:
        out.append("Files with it: " + ", ".join(str(f) for f in files))
    for line in step.get("log") or []:
        out.append(f"  {line.get('when')}: {line.get('said')}")
    return "\n".join(out)


async def _approvals(who) -> Got:
    desk = _desk()
    if desk is None:
        return Got(False, "New mail is not handled on this server.", kind="mail")
    got = await asyncio.to_thread(desk.queue, who)
    lines = [f"{got['waiting']} case(s) waiting for a decision."]
    for queue in got["queues"]:
        lines.append(f"\n{queue['name']}:")
        lines += [_case_row(r) for r in queue["rows"]]
    if got["recent"]:
        lines.append("\nLatest after them:")
        lines += [_case_row(r) for r in got["recent"][:25]]
    return Got(True, untrusted.wrap("\n".join(lines), SOURCE["mail"]), title="approvals",
               kind="mail")


def _case_row(r: dict) -> str:
    from .mail_cases import case_path

    return (f"- {r['when']} {r['who']} <{r['address']}>: {r['subject'] or '(no subject)'} - "
            f"{r['stage_words']}" + (f" ({_one_line(r['blocker'], 120)})" if r.get("blocker")
                                     else "") + f" [{case_path(r['key'])}]")


# --- the workspace's objects -------------------------------------------------------------


def _root(tools) -> str:
    root = getattr(getattr(tools, "cfg", None), "assistant_repo", "") or ""
    return root if root and os.path.isdir(root) else ""


async def _object(tools, kind: str, name: str, fragment: str, query: dict) -> Got:
    from . import addressing

    name = name.strip("/")
    row = await asyncio.to_thread(addressing.at, kind, name)
    if row is not None:
        if kind in ("task", "project"):
            return await _folder_object(tools, kind, row, "", fragment)
        if kind == "chat":
            return await _chat(tools, name)
        if kind == "run":
            return _run(row)
        if kind == "artifact":
            return await _tool(tools, "read_card", {"id": row.id}, "artifact", "data",
                               title=row.title or f"card {row.id}")
    if kind in ("task", "project"):
        inside = await asyncio.to_thread(addressing.inside, kind, name)
        if inside is not None:
            each, row, rest = inside
            return await _folder_object(tools, each, row, rest, fragment)
    if kind == "chat":
        return await _chat(tools, name)
    if kind == "artifact":
        return await _tool(tools, "read_card", {"id": name}, "artifact", "data",
                           title=f"card {name}")
    return Got(False, f"There is no {kind} at {name} any more.", title=f"no such {kind}",
               kind=kind)


async def _folder_object(tools, kind: str, row, rest: str, fragment: str) -> Got:
    root = _root(tools)
    folder = (getattr(row, "folder", "") or "").strip("/")
    if rest:
        if not root or not folder:
            return Got(False, "The workspace is not on this machine.", kind=kind)
        return await _workspace_file(tools, f"{folder}/{rest}", fragment,
                                     title=f"{rest} in {row.title}")
    lines = []
    if kind == "task":
        number = f"Task {row.number}" if row.number is not None else "Task"
        lines += [f"{number}: {row.title}", f"Status: {row.status} ({row.state})",
                  f"Folder: {folder or '(none)'}"]
        if row.summary:
            lines.append(f"Summary: {row.summary}")
    else:
        lines += [f"Project: {row.title}", f"Folder: {folder or '(none)'}"]
        if getattr(row, "description", ""):
            lines.append(f"What belongs in it: {row.description}")
    if root and folder and os.path.isdir(os.path.join(root, folder)):
        inside = sorted(e for e in os.listdir(os.path.join(root, folder))
                        if not e.startswith("."))
        if inside:
            lines.append("In its folder: " + ", ".join(inside[:80]))
        text = await asyncio.to_thread(_file_text, root, f"{folder}/AGENTS.md")
        if text:
            lines += ["", f"# {folder}/AGENTS.md", text]
    return Got(True, untrusted.wrap("\n".join(lines), SOURCE["file"]),
               title=(f"task {row.number}: {row.title}" if kind == "task" and row.number
                      is not None else row.title), kind=kind)


async def _chat(tools, chat_id: str) -> Got:
    memory = getattr(tools, "memory", None)
    chat = await asyncio.to_thread(memory.chat, chat_id) if memory is not None else None
    if not chat or chat.get("draft"):
        return Got(False, f"There is no chat {chat_id}.", title="no such chat", kind="chat")
    said = await asyncio.to_thread(memory.transcript, chat_id, 80)
    from . import clock

    lines = [f"Chat: {chat.get('title') or chat_id} ({len(said)} messages shown, newest last)"]
    for row in said:
        who = "The person" if row["role"] == "user" else "Rouh"
        lines.append(f"\n{who}, {clock.clock(row['ts'])} {clock.ago(row['ts'])}:\n"
                     f"{(row.get('text') or '').strip()[:4000]}")
    return Got(True, untrusted.wrap("\n".join(lines), SOURCE["chat"]),
               title=f"chat: {chat.get('title') or chat_id}", kind="chat")


def _run(row) -> Got:
    lines = [f"Run {row.id}: {row.title}", f"State: {row.state}"
             + (f", {row.phase}" if row.phase else ""), f"Agent: {row.agent}"]
    for label, value in (("Summary", row.summary), ("Doing", row.detail),
                         ("Waiting on", row.question), ("Branch", row.branch)):
        if value:
            lines.append(f"{label}: {value}")
    if row.exit_code is not None:
        lines.append(f"Exit code: {row.exit_code}")
    if row.brief:
        lines += ["", "Its brief:", row.brief[:6000]]
    return Got(True, untrusted.wrap("\n".join(lines), SOURCE["data"]),
               title=f"run: {row.title}", kind="run")


async def _runs() -> Got:
    from . import objects

    store = objects.shared_store(even_when_off=True)
    rows = await asyncio.to_thread(store.list_runs, parent_run_id=None, limit=40) if store else []
    lines = [f"- {r.id} [{r.state}] {r.title}" + (f": {_one_line(r.summary, 160)}"
                                                  if r.summary else "")
             for r in rows if not r.archived][:30]
    return Got(True, untrusted.wrap("Runs, newest first:\n" + "\n".join(lines or ["(none)"]),
                                    SOURCE["data"]), title="runs", kind="run")


# --- pages and files in the workspace ----------------------------------------------------


def _file_text(root: str, rel: str) -> str:
    from . import workspace

    try:
        return workspace.read(root, rel)
    except workspace.Refused:
        return ""


async def _workspace_file(tools, rel: str, fragment: str, *, title: str) -> Got:
    from . import workspace

    root = _root(tools)
    if not root:
        return Got(False, "The workspace is not on this machine.", kind="page")
    try:
        target = workspace.resolve(root, rel)
    except workspace.Refused as exc:
        return Got(False, f"Refused: {exc}", kind="page")
    if target.is_dir():
        inside = sorted(e for e in os.listdir(target) if not e.startswith("."))
        return Got(True, untrusted.wrap(f"The folder {rel} holds: " + ", ".join(inside[:120]),
                                        SOURCE["file"]), title=title, kind="page")
    if target.suffix.lower() in (".html", ".htm"):
        raw = await asyncio.to_thread(target.read_text, "utf-8", "replace")
        text = _html_text(raw, fragment)
        if fragment and text.startswith(_NO_PART):
            text = (f"The address points at #{fragment}, which this page has no part "
                    "called; the whole page is below.\n\n" + text[len(_NO_PART):])
        return Got(True, untrusted.wrap(text, SOURCE["page"]), title=title, kind="page")
    try:
        text = await asyncio.to_thread(workspace.read, root, rel)
    except workspace.Refused as exc:
        return Got(False, f"Refused: {exc}", kind="page")
    return Got(True, untrusted.wrap(text, SOURCE["file"]), title=title, kind="page")


async def _workspace_page(tools, rest: str, fragment: str, query: dict) -> Got:
    from . import addressing, objectindex

    rest = rest.strip("/")
    if rest in ("", "index.html"):
        return await _workspace_file(tools, "_tasks.md", "", title="the task list")
    if rest.startswith(objectindex.TASK_PREFIX.strip("/")):
        folder = rest[len(objectindex.TASK_PREFIX.strip("/")):].strip("/")
        doc = (query.get("doc") or [""])[0]
        for kind in ("task", "project"):
            row = await asyncio.to_thread(addressing.at, kind, folder)
            if row is not None:
                return await _folder_object(tools, kind, row, doc, fragment)
        return Got(False, f"Nothing in the workspace is at {folder} any more.", kind="page")
    return await _workspace_file(tools, rest, fragment, title=rest)


async def _public(tools, token: str, fragment: str) -> Got:
    shares = getattr(tools, "shares", None)
    found = await asyncio.to_thread(shares.find, token) if shares is not None else None
    if found is None:
        return Got(False, "That public link names no page.", kind="page")
    return await _workspace_file(tools, found["rel"], fragment,
                                 title=found.get("title") or found["rel"])


# --- HTML as the words a reader sees -----------------------------------------------------

_NO_PART = "\x00no part\x00"


class _Words(HTMLParser):
    """A page's words, a block to a line, and only one part of it when the address names one."""

    SKIP = {"script", "style", "head", "template", "noscript", "svg"}
    BLOCKS = {"p", "div", "section", "article", "header", "footer", "main", "aside", "nav",
              "table", "tr", "ul", "ol", "li", "dl", "dt", "dd", "pre", "blockquote", "form",
              "details", "summary", "figure", "figcaption", "br", "hr",
              "h1", "h2", "h3", "h4", "h5", "h6"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
            "source", "track", "wbr"}

    def __init__(self, part: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.part = part
        self.skipping = 0
        self.depth = 0          # inside the part named, how deep
        self.found = False
        self.words: list[str] = []
        self.title = ""
        self._in_title = False

    def _taking(self) -> bool:
        return not self.skipping and (not self.part or self.depth > 0)

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if self.part and self.depth == 0 and dict(attrs).get("id") == self.part:
            self.found = True
            self.depth = 1 if tag not in self.VOID else 0
            return
        if self.depth and tag not in self.VOID:
            self.depth += 1
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BLOCKS and self._taking():
            self.words.append("\n")
        elif tag in ("td", "th") and self._taking():
            self.words.append(" | ")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in self.BLOCKS and self._taking():
            self.words.append("\n")
        if self.depth and tag not in self.VOID:
            self.depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._taking():
            self.words.append(data)


def _html_text(raw: str, part: str = "") -> str:
    """The words a person reading the page sees, or only the part with this id."""
    def words_of(page: _Words) -> str:
        text = "".join(page.words)
        lines = [" ".join(line.split()) for line in text.split("\n")]
        return "\n".join(line for line in lines if line)

    page = _Words(part)
    page.feed(raw or "")
    page.close()
    if part and page.found:
        return f"The part #{part} of the page:\n" + words_of(page)
    whole = _Words()
    whole.feed(raw or "")
    whole.close()
    title = " ".join(html.unescape(whole.title).split())
    text = (f"Page: {title}\n\n" if title else "") + words_of(whole)
    return (_NO_PART + text) if part else text


def _one_line(text, most: int) -> str:
    said = " ".join(str(text or "").split())
    return said if len(said) <= most else said[: most - 1] + "…"
