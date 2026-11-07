"""The address of every object, and the object at every address.

Rouh is one HTML document, so for a long time it had one address: `/`. A chat
opened, a task read, a project browsed and a run watched were all `/`, which
meant none of them could be linked to, sent to anybody, bookmarked, or reached
again with the browser's Back button. The person asked for that on 22 September
2026, in these words: every chat, run, task, project or other thing on the
screen should have a URL of its own, so that opening that URL goes straight to
that thing with that layout.

The scheme
----------

One segment for what it is, and then what it is called::

    /chat/<id>                          a conversation
    /task/work/acme/19.pricing      a task, or a step of one
    /project/work/acme              a project
    /run/<id>                           a run, with its terminal
    /artifact/<id>                      a card
    /tasks                              the task browser, with nothing opened
                                        out of it yet
    /browser                            the Live browser, Rouh's own browser
                                        for errands, watched live
    /clockwork                          everything Rouh will say or do at a time
                                        (/reminders until 8 October 2026, sent on to it)
    /goals                              the person's goals, and the plan for each
    /control                            the Control Room: the work in flight, its
                                        stages, decisions and evidence
    /metabolism                         every run, with what each is doing:
                                        everyday work, and at /metabolism/mutations
                                        the runs that change Rouh itself (/runs
                                        until 14 October 2026, sent on to it)
    /anatomy/connections                one of Anatomy's six groups, and /anatomy
                                        its status board (/settings until 14 October
                                        2026, sent on to it)

The ones that are not an object
-------------------------------

`/tasks` is the first exception. The task browser's own top -
both columns, every project, nothing opened out of it - is a place a person can
be and stay, and it is not any single object: Work and Personal are two
top-level projects and the browser is the both of them at once.

It earns an address because it failed the test this whole scheme exists to
pass. Until 22 September 2026 it had none, so the bar fell through to whatever
was underneath it, which is the conversation - and opening a task picks that
task's thread, and a thread a numbered task owns carries that task's address.
So pressing **Task browser** after reading task 19 left the bar saying
`/task/work/acme/19.pricing` while the screen showed the whole workspace.
The bar named something the person had walked away from.

It is still not navigation, and "Navigation is still not in an address" below
still holds. `/tasks` says what is on the canvas; it does not say whether the
sidebar is open, which of its lists is showing, or which pane a phone is on.
What it names happens to be a view of everything rather than one row, and a
view of everything is a thing you can be looking at. It takes `?chat=` beside
it like any other path, for the same reason any other path does: open a
conversation next to the browser and both panels are in the link.

**An object is addressed by its own name, and nothing else.** A task and a
project are named by their folder, because that is what they are called
everywhere a person meets them: in the workspace, in git, in the breadcrumb and
in the canvas's own address. A chat, a run and a card have no folder, so they
are named by their id, which is the only name they have. That is one rule, not
two: the address is what the object is called.

Reading one back is the same rule in reverse, with two kindnesses: a name that
matches no folder is tried as a numbered task's number, and then as an id
(`at` below). So a task that never had a folder is still reachable, and so is
an address written down when it had a different one.

What is inside one
------------------

A task's page lists its subtasks and what is directly in its folder - its
`.md` files, its `source-code`, the page it built - and a subtask's page the
same one level down, and every line of it opens on the canvas. Until 23 September 2026 none of those had an
address: the bar stayed on the task, so Back could not undo one click inside
it, and the only way out was the close button, which shut the whole task.
Petar: "if I click on folder or notes, the url doesn't change, so I can't go
back... urls should change on every click."

So the same name goes on downward. A task and a project are called by their
folder, and what is in that folder is called by its path under it::

    /task/private/misc/58.new-tool                  the task's page
    /task/private/misc/58.new-tool/58-01.should-we-adopt-it
                                                    a step of it
    /task/private/misc/58.new-tool/58-01.should-we-adopt-it/58-01.research-notes.md
                                                    its research notes
    /task/private/misc/58.new-tool/58-01.should-we-adopt-it/source-code/research
                                                    a folder in its source-code
    /task/private/misc/58.new-tool/58-01.should-we-adopt-it/index.html
                                                    the page it built

Read back, a name that is not itself a task or a project is the deepest one
it starts with, and the rest is the path inside that one's folder (`inside`).
The address is where the thing is in the workspace, so it reads the same in
the bar as in the eyebrow over it, and it is never a query a person would not
recognise.

**The middle of the screen is two panels, and an address names both.** The
conversation is one and the canvas is the other, and they are often two
different things: a run watched beside a chat, a project's page read beside
the conversation you are in. An address that named only one of them - which is
what this was until Petar caught it the same day - brought back the run next
to whichever conversation happened to be active rather than next to the one in
the link. So the conversation goes on the end when it is not already implied::

    /run/25d54848?chat=chat-9f2a1b3c      a run, and the chat beside it
    /project/work/acme?chat=…         a project's page, and the chat
    /task/work/acme/19.pricing        one thing: the task's page **and**
                                          the task's own thread, which is the
                                          same object twice

It is only ever there when there is something to say: a task beside its own
thread is one object, a step beside its task's thread is the same, and a page
browsed with the conversation folded away is one panel. `addrNow` in
`rouh/static/app.js` is where that is decided, because only the browser knows
what is on the screen; nothing here ever writes it (`url_for` addresses one
object, which is all a search result is).

The one that is nothing
-----------------------

`/` names no object at all, and that is not an oversight either: it is the
front door, and the front door is empty. A page opened there opens nothing,
draws nothing and keeps the bar at `/`.

It used to go looking for something to be. The handshake says which chat the
person is in, the page drew that chat, and the bar followed it, so opening
the front door landed on `/task/private/misc/56.team-offsite` with last
night's conversation on the screen. Petar asked for that to stop on 22
September 2026: going to the root should not redirect to the last thing, and
should not load anything on the screen, neither chat nor anything in the
canvas.

Nothing here is what makes that true, and nothing on the wire is: which chat
is active belongs to the person and is shared by the phone and the desk alike,
and a page at the front door simply does not show it. Section 10g of
`rouh/static/app.js` is the whole of it, including what happens when something
is said at a door with no conversation behind it: a new chat is opened to say
it in.

**Navigation is still not in an address.** There is no `?panel=`, no
`#sidebar`, no `&pane=canvas`. `chat` names an object - a conversation, by the
only name a conversation has - and it is there for the reason the path is
there: something is on the screen and a link has to bring it back. Which of
the sidebar's three lists is showing, whether the sidebar is open at all,
whether the projects dashboard, the search box or the Gene therapy
drawer are up, and which pane a phone is on are things a person does in order
to look at an object. They are not objects, and none of them is in an address.

Who uses it
-----------

* `rouh/web/views.py` (`index`) answers every one of these addresses with the one page, and
  the page reads the address and asks for what it names over the socket
  (`find_object`). `/tasks` and `/browser` are the exceptions at both ends:
  neither has a `{rest}` to carry a name, and the page opens each itself
  rather than asking, because there is no row to look up.
* `rouh/searching.py` puts the address on every search result, so "open in new
  tab" is a real link, and turns an address back into the same open
  instruction a result row carries. One path for a link, a search result and a
  press on a row.
* `rouh/static/app.js` keeps the address bar level with what is on the screen,
  reads an address back into a kind, a name and the conversation beside it
  (`addrRead`), and answers Back and Forward from it. It owns the pair,
  because what is on the screen is the browser's to know.

Nothing else invents an address. There is one scheme and this file is it.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote

from . import genes, objects

log = logging.getLogger("rouh.addressing")

#: The five, by the names the object model already calls them
#: (`objects.KINDS`). One vocabulary, so an address never has to be translated
#: into anything: `/artifact/<id>` and not `/card/<id>`.
KINDS: tuple[str, ...] = objects.KINDS

#: The two that are named by where they are rather than by their id, which are
#: exactly the two that nest and are folders in the person's workspace.
FOLDERED: tuple[str, ...] = objects.NESTS

#: The task browser's own top, which is the one address that names a place
#: rather than an object. Plural, and `/task/<folder>` is singular, so the two
#: cannot be mistaken for one another by a person or by a router. `app.js`
#: reads it straight and opens the browser: there is no object to resolve, so
#: it is the one address that never asks `find_object`.
BROWSER = "/tasks"

#: The Live browser (`rouh/browsing.py`): the browser Rouh drives for errands,
#: watched on the canvas. The second address that names a place rather than an
#: object, for the same reason `/tasks` is one: it is on the canvas and is not a
#: row, and without an address of its own the bar would name whatever the
#: conversation is. `app.js` opens it without asking the server anything.
WEB = "/browser"

#: Clockwork and the Goals page (`rouh/reminders.py`, `rouh/goals.py`):
#: two more places rather than objects, on the canvas like the Live browser.
#: A goal itself is a task, at its own `/task/...` address as well. Clockwork
#: was called Reminders, at `/reminders`, until 8 October 2026, when Petar
#: renamed it because most of what is on it is work done at a time rather than
#: reminders; the old address is sent on to the new one (`REMINDERS_OLD`).
CLOCKWORK = "/clockwork"
REMINDERS = CLOCKWORK
REMINDERS_OLD = "/reminders"
GOALS = "/goals"
#: Gene therapy, what the person tells Rouh to change about itself: the page with its drawer
#: open on the right, ready to be written in. A door rather than a place, because the drawer
#: is navigation and not in an address (above): the page opens it and the bar then says
#: whatever is on the screen beside it. It was Feedback, at `/feedback`, until 12 October
#: 2026, and that address is sent on to this one (`GENE_THERAPY_OLD`).
GENE_THERAPY = "/gene-therapy"
GENE_THERAPY_OLD = "/feedback"
#: The Control Room (`rouh/controlroom.py`): the foundational work in flight,
#: and where each piece stands. A place like the two
#: above: every line on it has an address of its own, and it is none of them.
CONTROL = "/control"
#: Synapse's lab (`rouh/synapse/`): its homepage at `/synapse`, and one
#: dataset's debugger at `/synapse/<dataset id>`, with the dataset's own chat
#: beside it named by `?chat=` like any other conversation.
SYNAPSE = "/synapse"
#: The runs: every run of the one program and every job, as a page of its own
#: since 30 September 2026. It was one of three lists the sidebar switched
#: between until then, and the only one of them Petar used. It was Runs, at
#: `/runs`, until 14 October 2026, when Petar named it Metabolism and split it in
#: two: everyday work at `/metabolism` and the runs that change Rouh itself at
#: `/metabolism/mutations` (`METABOLISM_TABS`). The old address is sent on to the
#: new one (`RUNS_OLD`), and `/runs/<tab>` to that tab.
METABOLISM = "/metabolism"
RUNS = METABOLISM
RUNS_OLD = "/runs"
METABOLISM_TABS: tuple[str, ...] = ("everyday", "mutations")
#: The morning brief (`rouh/morning_brief.py`): today's, made each morning,
#: and where the link sent to the phone goes.
BRIEF = "/brief"
#: The heartbeat (`rouh/heartbeat.py`) was a page of its own here on 5 October 2026;
#: it is the Settings group `/settings/heartbeat` since the same day, and this old
#: address, which its first Telegrams linked to, lands there.
HEARTBEAT = "/heartbeat"
#: The quests the heartbeat carries (`rouh/quests.py`): every one at `/quests`, and each
#: at `/quests/<its task's number>`, since 5 October 2026.
QUESTS = "/quests"
#: Decisions (`rouh/decisions.py`): everything waiting on the person's answer, from every part
#: of Rouh that asks, at `/decisions`, and one of them at `/decisions/<id>`, which is where a
#: Telegram about one links to. Since 5 October 2026; since 18 October `<id>` is its number,
#: Decision 42 (`decision_numbers.py`), and a handle it had (a482) is sent on to it.
DECISIONS = "/decisions"
#: Your part (`rouh/actions.py`): the hands-on things only the person can do, which hold up
#: work Rouh is doing, at `/actions`, and one at `/actions/<number>` ("Action 430", from the
#: decisions' numbers). Since 7 November 2026; `/decisions/<number>` of an action lands here.
ACTIONS = "/actions"
#: Receipts (`rouh/receipts.py`): every receipt and invoice in the person's mail, by month,
#: with one download for the accountant. Since 7 October 2026, behind the switch `receipts`.
RECEIPTS = "/receipts"
#: Home (`homepage.js`): the house itself - its lights first, through Philips Hue, and every
#: other kind of device as a section of its own. Opened from the house in the navigation's head.
#: Since 17 October 2026.
HOME = "/home"
#: Agent instructions (`rouh/agent_instructions.py`): what every agent Rouh starts is told before
#: anything else, kept in the database and edited here. Since 15 October 2026, when they replaced
#: `workspace/AGENTS.md` and `workspace/AGENTS_ASSISTANT.md`.
AGENT_INSTRUCTIONS = "/agent-instructions"
#: Rules (`rouh/rules.py`, `rouh/rule_groups.py`): every rule Rouh follows, in groups, at `/rules`, one group
#: alone at `/rules/<group>` (`/rules/mail`), and what a request was told at `/rules/told`; `?label=gene`,
#: `instances` or another of the page's labels (`RULE_LABELS` in `runs.js`) shows only the rules with it, several
#: at once comma-separated (`?label=from-chat,agent`, any of one facet's and every facet named), and
#: `?from=`, its name until 30 October 2026, still does. Opened from the account menu. Until 29 October 2026 it was a
#: panel with no address of its own, held on the conversation it was opened over.
RULES = "/rules"
#: Approvals (`rouh/mail_cases.py`, `approvalspage.js`): every email and message Rouh stopped
#: on for the person's decision, in its group's queue, and the latest after them. A page of its
#: own drawn by the server until 15 October 2026, when Petar asked for it under Now, inside Rouh
#: with the orb like every other page: "It is not a setting page, it is content page"
#: (fr_37cea76c6db3).
MAIL_APPROVALS = "/mail/approvals"
#: One mail case, `/mail/case/<key>`, in the same layer as Approvals, with the orb beside it
#: (fr_7d4948ef128b): its one page, the server's (`mail_case.html`), in a frame - what they
#: asked and the decision on each at the top (`mailcasepage.js`), then every step, the logs,
#: tests and fixes. One address since the evening of 15 October 2026 (fr_65ed87c8685b), when
#: the trace beside it, `/trace`, became a way to it. `/attachment/...` and the rest under it
#: are the server's.
MAIL_CASE = "/mail/case"
#: Sources (`rouh/source_check.py`): the footnoted pages' sources in one task, read against what
#: each page says they say, at `/sources/<the task's or step's folder>`. Since 13 October 2026,
#: behind the switch `source_check`. Reached from the task's page; `/sources` alone, every page,
#: was taken out the same day (fr_fce8f51c00d6) and opens the task browser.
SOURCES = "/sources"
#: Evolution (`rouh/evolution.py`): Parameters at `/evolution/parameters`, how many genes a night the
#: nightly run builds and of which kinds, and Mutations at `/evolution/mutations`, with its views
#: (`/new`, `/trial`, `/passed`, `/rejected`, `/unused`, `/month`) and one gene (`/gene/<id>`); the
#: older views' and the morning deck's addresses (`/failed`, split into Rejected and Not used on 27
#: October 2026, `/out`, `/week`, `/deck` and before them `/review`, `/rouh` and `/off`) are still
#: read, and the page sends each on to the view that holds it now.
#: Since 13 October 2026 (task 94, step 94-08). And the gene log at
#: `/evolution/mutations/log` and one gene of it at `/log/<id>` (`rouh/genelog.py`; task 98, step
#: 98-17), and the Gene Pool at `/evolution/pool` and one family of it at `/pool/<id>`
#: (`rouh/genepool.py`), its review list of this Rouh's genes on their way to it at `/pool/yours` and
#: one of them, as it would leave, at `/pool/yours/<id>` (task 141, step 141-09), since 25 October
#: 2026 its Outgoing genes at `/pool/outgoing` and `/pool/outgoing/<id>` (the `yours` addresses open
#: them) and its Incoming genes at `/pool/incoming` (step 141-15). Mutations was
#: the Gene library, at `/evolution/library`, and the Pool one of its views, until 14 October 2026
#: (fr_a982710d30c7); those addresses are sent on to these.
EVOLUTION = "/evolution"
#: Thoughts (`rouh/thoughts.py`): the person's own thoughts, in their words, newest first by month,
#: at `/thoughts`, and one of them at `/thoughts/<its number>`. Since 12 October 2026.
THOUGHTS = "/thoughts"
#: The box (`rouh/boxes.py`): what the person keeps from the model, sealed - a secret on its way to
#: an env file, an idea held back until they give it to Rouh - at `/box`, and one of them at
#: `/box/<its number>`. Since 13 October 2026.
BOX = "/box"
#: Offline (`rouh/offline.py`): what this device keeps for when there is no connection, what
#: it did offline and what became of it, and everything it holds to read, search and act on
#: with no connection. Since 12 October 2026 (card 1457).
OFFLINE = "/offline"
#: A quest's page by its record, `/work/<id>`, as long-running work was addressed for the
#: first day; the server sends it on to the quest's page (`web/quests.old_address`).
WORK = "/work"
#: Settings, a place since 30 September 2026 (fr_59e04ad20ac8), with a group of cards at
#: `/settings/<group>`, until 14 October 2026, when it became Anatomy's five groups (card
#: 1554): the status board at `/anatomy`, a group's menu of its sections at `/anatomy/<group>`,
#: and one of its sections, a page of its own, at `/anatomy/<group>/<section>`. Which section is
#: in which group is the gene manifests' (`genes.SECTIONS`), and so are the names below.
#: Every old address under `/settings` is sent on (`anatomy_address`), except the server page
#: already under it (`/settings/mail-alerts/log`), which is routed before and no section may be
#: called. Trusted contacts were a server page at `/settings/trusted-contacts` until 2 October
#: 2026, and one contact is still `<its section>/<id>`.
ANATOMY = genes.ANATOMY_ROOT
SETTINGS = "/settings"
#: Where rouh.land sends the person back to with a code: a birth or connect code (`?birth=`), or
#: the id of the new key they asked for (`?recovery=`). rouh.land's site writes this path itself
#: (its `birth/views.py`, `account` and `_back`) and accepts no other, so it stays its address
#: although Birthday moved (Rouh profile from 4 November 2026, Your Rouh since 7 November). It is not
#: a page: only a return carrying one of those two is sent on to Your Rouh; anything else
#: here is not found (`web/anatomy.rouh_land_return`), as every other old address of a moved
#: section is (`genes.MOVED`).
ROUH_LAND_RETURN = "/anatomy/meta/birthday"
ROUH_LAND_CARRIES = ("birth", "recovery")


def anatomy_address(rest: str = "") -> str | None:
    """Where an old Settings address, `rest` being what came after `/settings/`, is now: the
    group page of the section it names, with anything under the section kept, or the status
    board for no section or one there is no longer. None for a section moved on 4 November 2026
    (`genes.MOVED`): Petar asked that a move leaves no forwarding, so that address is not found."""
    rest = str(rest or "").strip("/")
    section = rest.split("/")[0]
    if section in genes.MOVED:
        return None
    group = genes.SECTIONS.get(section)
    return f"{ANATOMY}/{group}/{rest}" if group else ANATOMY


#: How long a name in an address may be. An address arrives from outside and
#: is never trusted to be small.
LONGEST = 400

#: A numbered task's folder, `56.team-offsite`: the number, a dot, a
#: name. A step (`56-01.x`) is not one, and has no number of its own.
_NUMBERED = re.compile(r"^(\d+)\.")


def name_of(kind: str, ident: str, folder: str = "") -> str:
    """What one object is called in an address: its folder, or its id."""
    rel = str(folder or "").strip().strip("/")
    if kind in FOLDERED and rel:
        return rel
    return str(ident or "").strip()


def url_for(kind: str, ident: str, folder: str = "") -> str:
    """One object's address, or `/` where there is no object to address."""
    name = name_of(kind, ident, folder)
    if kind not in KINDS or not name:
        return "/"
    return f"/{kind}/" + quote(name, safe="/")


def at(kind: str, name: str):
    """The object one address names, as its row, or None.

    The folder first for the two that have one, because that is what their
    address is; the id after it, for the ones with no folder and for a name
    written down before there was one.
    """
    store = objects.shared_store(even_when_off=True)
    name = str(name or "").strip().strip("/")[:LONGEST]
    if store is None or kind not in KINDS or not name:
        return None
    if kind in FOLDERED:
        try:
            row = store.by_folder(kind, name)
        except Exception:
            log.exception("could not look up the %s at %r", kind, name)
            row = None
        if row is not None:
            return row
    if kind == "task":
        # A numbered task by its number, when no row names this folder: an
        # address kept from before the task moved, or one naming the other
        # copy of a task that exists twice. Task 56's was
        # `/task/private/misc/56.team-offsite-today`, and once its row
        # settled on the copy under Personal that address said "It is not
        # there any more" over an empty canvas. The number is what the person
        # calls the task by, and it does not change when the folder does.
        #
        # Only where the name ends at the task's own folder. One that goes on
        # past it is something inside the task (`inside`), whatever its last
        # part is called: a step's research note `03.press-funding.md` is not
        # task 3.
        parts = name.split("/")
        if _task_at(parts) == len(parts) - 1:
            row = _by_number(store, parts[-1])
            if row is not None:
                return row
    getter = {"project": store.get_project, "task": store.get_task,
              "chat": store.get_chat, "run": store.get_run,
              "artifact": store.get_artifact}[kind]
    try:
        return getter(name)
    except Exception:
        log.exception("could not look up %s %s", kind, name)
        return None


def inside(kind: str, name: str):
    """The object a deeper name is inside, and the path under its folder.

    ``(kind, row, rest)`` for `/task/<a task's folder>/<a path in it>`, or
    None when the name is not under any task or project. The deepest one
    wins, so a step's notes are its step's and not its task's, and either of
    the two words finds either: a project's notes reached through `/task/` is
    still that project's, because the path is the whole of what it names. A
    task's folder no row names any more is the task by its number, the same
    kindness `at` has, so a note linked to before its task moved still opens.

    Only the shape of ``rest`` is checked, the same way `build_doc` checks it:
    no part empty or hidden, no backslash or NUL. Whether it is still on disk
    is for the page that opens it to say (`canvasLost`), with the task it was
    in beside the words, which is more use to somebody following an old link
    than a bare "not there".
    """
    store = objects.shared_store(even_when_off=True)
    name = str(name or "").strip().strip("/")[:LONGEST]
    if store is None or kind not in FOLDERED or not name:
        return None
    parts = name.split("/")
    if "\\" in name or "\x00" in name or any(not p or p.startswith(".") for p in parts):
        return None
    kinds = (kind,) + tuple(k for k in FOLDERED if k != kind)
    task_at = _task_at(parts)
    for cut in range(len(parts) - 1, 0, -1):
        folder, rest = "/".join(parts[:cut]), "/".join(parts[cut:])
        for each in kinds:
            try:
                row = store.by_folder(each, folder)
            except Exception:
                log.exception("could not look up the %s at %r", each, folder)
                row = None
            if row is not None:
                return each, row, rest
        if cut - 1 == task_at:
            # The task's own folder, and no row names it any more: the task
            # by its number, as `at` finds it, and the rest under wherever
            # its folder is now. Never a project further up, which would read
            # the task's folder name as a file in the project.
            row = _by_number(store, parts[task_at])
            if row is not None and getattr(row, "folder", ""):
                return "task", row, rest
    return None


def _task_at(parts: list[str]) -> int:
    """Which part of a path is its numbered task's folder, or -1.

    The first one named like a task, `56.team-offsite`: that is how the
    workspace tells a task from the projects over it (`objecttree.is_a_task`),
    and everything after it is inside that task, however it is named.
    """
    for i, part in enumerate(parts):
        if _NUMBERED.match(part):
            return i
    return -1


def _by_number(store, part: str):
    """The numbered task a folder name says it is, `56.x` being task 56."""
    found = _NUMBERED.match(part)
    if not found:
        return None
    try:
        return store.numbered_task(int(found.group(1)))
    except Exception:
        log.exception("could not look up task %s", found.group(1))
        return None
