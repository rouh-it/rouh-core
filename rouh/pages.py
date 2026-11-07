"""Pages from the person's workspace, shown whole on Rouh's canvas.

The person's own assistant delivers its work as pages: one self-contained
``index.html`` per step, under the task that owns it. Until this module a
finished page reached the canvas only as a link to the laptop's own Ask AI
server, which opened on the laptop and nowhere else. Rouh serves the pages
itself, from the workspace in its own checkout (``config.assistant_repo``,
which since 21 September 2026 is ``workspace/`` beside this file), to a
signed-in session only, and the canvas shows them in a frame.

What may be served. Every rule is checked on the path as asked, and again after
every link in it has been followed:

- only files under one of the top folders in ``TOPS``
- only the kinds of file a page is made of (``TYPES``). This is a list of what
  is allowed, not of what is refused: the laptop's proxy once refused by
  suffix, and a file named just ``.env`` has no suffix, so it handed out the
  key (workspace commit 5376061)
- never a name starting with a dot, at any depth: ``.env``, ``.git``,
  ``.claude``, and ``..``
- never a database (any name holding ``.sqlite3``, which covers its ``-wal``
  and ``-shm`` files), never a ``.md`` file (a task's ``AGENTS.md`` is its
  whole internal record), and never a folder, so there are no listings
- never an encoded slash, backslash, percent sign, dot or NUL in the address as
  it arrived, so nothing is decoded twice
- and never anything ``read_workspace`` refuses: its own checks run as well
  (``workspace.resolve``), rather than a second list kept here

One page at a time can be let out from behind that sign-in, and only by the
person who owns it: **Share** in the top bar makes it public and gives it an
address of its own under ``/p/<token>``. That route is in ``rouh/web/views.py`` and
the store is ``sharing.py``; what it serves is this module's own ``read``,
with no ``at``, so a public page is checked, sandboxed and assembled exactly
as a page opened at its own address always was - and gets no Ask AI drawer,
because there is no signed-in page around it to carry a question. A link the
owner said may be changed, and a page shared with a person by email, are the
exception: Rouh serves a page of its own around them, which frames this
module's page exactly as the canvas does and carries the drawer's questions
(``rouh/web/guests.py``). Nothing here needed relaxing for any of it.

A page runs its own scripts, so it is kept apart from Rouh. Every file goes
out with ``HEADERS``, whose Content-Security-Policy sandboxes it: the browser
gives it an origin of its own that matches nothing. It then cannot read
Rouh's cookies or reach into the page around it, and it cannot send anything
with fetch, a WebSocket or a form. Without that last part a page could open
Rouh's own socket and talk to Rouh as the person. The frame on the canvas
carries the same sandbox (``FRAME_SANDBOX``, in app.js), so a page stays apart
even if a header were ever lost on the way.

A sandboxed page gets no storage either: the browser throws the moment a script
touches ``localStorage``. A page that does not guard that line stops dead. So
every page is given a stand-in, a store in memory that is forgotten when the
frame closes, put in at serve time the way the laptop's Ask AI server puts in
its drawer. The page on disk is never changed.

A framed page also says where it is. Nothing around a sandboxed page can read
its address or its title, and the task browser needs both: to say where the
reader has got to, and to take them back a step after they have followed a link
inside the frame. So the page tells the page that frames it, and nobody else
(``address_script``).

Who fetches a framed page. Not the frame. The browser sends Rouh's sign-in
with a request the page around the frame starts, and does not send it with a
request the frame starts for itself, because a sandboxed frame has an origin of
its own. The first load was the page's and worked; every page the reader
reached from inside the frame was the frame's own request, and Rouh answered
it "Sign in to Rouh first." That is what the task browser showed on the live
server. So Rouh's own page fetches the markup, with its own sign-in, and
hands it to the frame as text. It is the same page, sandboxed by the frame's
own ``sandbox`` attribute, with a few lines more in its head (``frame_head``,
``frame_script``):

- where it is, in a ``<base>``, because a page handed over as text has no
  address of its own and every relative link and picture in it has to go on
  resolving as it did
- the half of ``CSP`` the frame's attribute does not carry, said where the page
  can read it (``FRAME_CSP``)
- a link clicked inside the frame, handed to the page around it rather than
  followed by the frame (``follow_script``)
- the few keys that have to cross the frame's edge, both ways (``keys_script``)
- the Ask AI drawer's questions, and the index's own category changes, handed
  out through the page around the frame for the same reason a link is
  (``ask_script``, and ``askai.py``)

There was a fourth until 21 September 2026: a drag anywhere on the page moved
the page under your hand, the way a map moves. It had to go. It took the
pointer on ``pointerdown`` and put ``user-select: none`` on everything as soon
as the hand moved three pixels, so **nothing on a workspace page could be
selected** - and selecting a passage is the whole way in to Ask AI. It also
took the pointer off the index's own drag, which is how a task is filed into
another category. Two of the three things a person does on these pages were
dead so that the third could scroll without a wheel. The frame scrolls.

Nothing can catch a page sending *itself* somewhere, which the workspace's own
index does every time Enter is pressed on a task. So the refusal is a page too
(``signed_out_page``): it hands its own address back to the page around the
frame, which is signed in, fetches it and puts it back.

Files kept beside a page. The browser sends no sign-in with the requests a
sandboxed page makes by itself, so a picture, style sheet, script or font kept
beside a page would be refused, and the page would show without it. So when a
page is sent, every such file its markup names is put into it, each as a
``data:`` address holding the whole file (``with_files``). A file goes in only
if it passes exactly the rules above, through ``check``, as if the browser had
asked for it from the page's own address, and only as what the browser would
have used it as: a picture as a picture, a style sheet as a style sheet, a
script as a script. A reference that fails is left as it was, and so are
absolute addresses and other sites' addresses. So are a file over
``INLINE_FILE_MAX`` and any file that would take the page past
``INLINE_PAGE_MAX``, each with a line in the log. Pictures a script loads by
itself, and style sheets a style sheet imports, are not covered.

Except a page Rouh frames on the canvas for a signed-in person: there a
picture an ``<img>``, ``<source>`` or SVG ``<image>`` names is given an address
of its own that carries its own credential, and is fetched by the browser as it
comes into view (``read(pictures=...)``, `rouh/picturelinks.py`). Put in, the
211 screenshots of one step's page made it 16.9 MB, and it took more than 30
seconds to arrive (7 November 2026). A picture a style names is still put in.

Ask AI. A page of work has a drawer on it: select a passage and ask about it.
It is the workspace's own drawer, put into the page as it is sent the way the
laptop's own proxy puts it in, and the only thing changed about it is how its
questions leave the page - they cannot, so they go out through the page that
frames it, which is signed in. ``askai.py`` is the whole of it. A page opened
at its own address gets no drawer, because there is no signed-in page around it
to carry a question, and a drawer that cannot ask anything is worse than none.

How a page is drawn. Rouh is dark, and only dark. A workspace page that has
no storage would otherwise fall back to the reader's own machine and come out
light inside a dark screen, so the storage stand-in answers the page's own
colour lookup with "dark" until the page sets one itself (``storage_script``).
app.css says the same thing to the frame, which Chromium passes on to the page
inside; Safari does not, which is why the stand-in answers as well.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import posixpath
import re
from pathlib import Path
from urllib.parse import quote, unquote

from . import addressing
from .workspace import Refused, resolve

log = logging.getLogger("rouh.pages")

#: The address pages are served under. The page's own path follows it, so its
#: relative links to its pictures, styles and scripts resolve under it too.
ROUTE = "/workspace/"

#: The only top folders anything is served from.
#:
#: `work`, `private` and `unfiled` arrived on 21 September 2026, when the flat
#: `tasks/NN.name` became a tree of projects and a task moved under the project
#: that owns it. `tasks` stays for a workspace that has not been reshaped -
#: there is none here now, and the rule costs nothing to keep true. The rule
#: this enforces is unchanged and is the one that matters: a named top folder
#: and nothing else, so the workspace root, `_context/`, `bin/` and `.git/` are
#: unreachable however the address is written - as `_askai/` was, before it was
#: deleted along with the rest of the retired proxy.
#:
#: `rouh` is the Rouh column's folder, beside Work and Personal since 29
#: September 2026 (`objecttree.columns_are_folders`). Left out of this, every
#: page in it answered "Not found." and a task folder made in it by hand - task
#: 69, the Rouh logo - was never walked, so never became a row. A column made
#: later needs its folder named here too.
TOPS = ("tasks", "archive", "examples", "work", "private", "rouh", "unfiled")

#: The only kinds of file served, each with the type it is sent as.
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".woff2": "font/woff2",
}

#: Scripts run, and the page is given an origin of its own; it may be framed
#: only by Rouh's own page; and it cannot send anything by fetch, WebSocket,
#: EventSource, beacon or form.
CSP = ("sandbox allow-scripts; frame-ancestors 'self'; "
       "connect-src 'none'; form-action 'none'")

#: Sent with every file served, and with every refusal.
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Cloudflare sits in front and keeps some files by their extension. A
    # private page kept there would go to the next person who asks for it,
    # signed in or not.
    "Cache-Control": "no-store, private",
}

#: The frame's own sandbox on the canvas, in app.js: scripts, and nothing else.
#: No same origin, no forms, no navigating Rouh's page. The task frame adds
#: downloads, for a task's files (`rouh/filelinks.py`), and new tabs, so a link
#: in a page is a link the browser opens in one (`follow_script`).
FRAME_SANDBOX = "allow-scripts"

#: What a page is given in its own markup when Rouh puts it in a frame. The
#: page arrives there as text, so the header above never reaches the browser
#: for it; the sandbox comes from the frame's own attribute, and this is the
#: rest of that header said where the page can read it.
FRAME_CSP = "connect-src 'none'; form-action 'none'"

#: Encoded forms never followed, looked for in the address as it arrived.
ENCODED = ("%2f", "%5c", "%25", "%2e", "%00")

#: The largest file served. A page and its pictures are far smaller.
MAX_BYTES = 50_000_000

#: The largest file put into a page, by its own size.
INLINE_FILE_MAX = 8_000_000

#: The most put into one page in all, counted by the files' own sizes, each time
#: one is put in. Past either limit a reference is left as it was. The largest
#: page in the workspace takes in 2.9 MB, and a phone is never sent more than
#: this.
INLINE_PAGE_MAX = 15_000_000

#: What each kind of reference may be given. A reference only ever becomes
#: what the browser would have used it as, so a page can never take in another
#: page, a PDF, or a script under a picture's name.
PICTURES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
IN_CSS = PICTURES + (".woff2",)
STYLESHEETS = (".css",)
SCRIPTS = (".js",)

#: The address prefixes that name an object rather than a file, which is the
#: other half of what a link inside a framed page may point at. One segment for
#: what it is - `/chat/`, `/run/`, `/artifact/`, `/task/`, `/project/` - and
#: then the name the object already has. `rouh/addressing.py` owns the scheme
#: and this reads it, so a sixth kind is a line there and nothing here.
OBJECT_ROUTES = addressing.KINDS

#: The link under every frame, drawn by app.js.
FULL_SCREEN = "Open full screen"

#: A second place the same page can be opened, named by
#: `config.assistant_review_url`. That was the laptop's own Ask AI server until
#: it was retired on 21 September 2026, and nothing names one now, so no card
#: carries this link; it is kept for a machine that really has somewhere else
#: to send a reader.
MAC_LINK = "Open on your Mac, with Ask AI"


#: The message a framed page sends back, saying which address it is at and what
#: it is called. A page is sandboxed, so the page around it cannot read either
#: from the frame; without this the canvas's breadcrumb could not say where the
#: reader is or take them back a level (``objectindex.py``, and the tasks
#: section of app.js).
ADDRESS_MESSAGE = "rouh-page-address"

#: The message a framed page sends when the reader follows a link inside it.
#: The browser does not send Rouh's sign-in cookie with a request a sandboxed
#: frame starts for itself, so such a page never navigates itself: it names the
#: address, and the page around it - which is signed in - loads it instead.
FOLLOW_MESSAGE = "rouh-page-follow"

#: The message Rouh sends a framed page it has just loaded, when the link that
#: led there named a place in it (``other.html#part``). A fetch carries no
#: fragment, so the page arrives at its top, and this takes it the rest of the
#: way, the same way a link inside the page does (``follow_script``).
HASH_MESSAGE = "rouh-frame-hash"

#: The message a framed page sends when a key Rouh owns is pressed inside it:
#: Escape, and the two ways of saying "back". Keys pressed inside a frame never
#: reach the page around it on their own.
KEY_MESSAGE = "rouh-page-key"

#: The message Rouh sends the other way, when a key was pressed while the
#: page around the frame had the keyboard and the page inside it owns that key
#: - the arrows, Enter, Space and "/" of the workspace's own index.
TYPE_MESSAGE = "rouh-frame-key"

#: The message a framed page sends when the Ask AI drawer on it wants to ask
#: Rouh something. A sandboxed page cannot call out at all - ``connect-src
#: 'none'``, and an origin of its own, so no sign-in would go with the request
#: either - so the request is handed to the page around the frame, which is
#: signed in and makes it (``ask_script``, and ``askRelay`` in app.js).
ASK_MESSAGE = "rouh-page-ask"

#: The pair a framed page and Rouh exchange about the conversation Rouh is
#: drawing beside it, since the Ask AI drawer and the chat column were made one
#: surface on 23 September 2026.
#:
#: Up: a passage was selected and Ask or Change pressed on the bar over it, a
#: mark was pressed, the star in the corner was pressed, or the page is handing
#: back its own words. Down: hand back the words, or draw the marks again.
#:
#: It is shaped like ``FILE_MESSAGE`` and not like ``ASK_MESSAGE``: it carries
#: a passage, a topic number and the page's own text, and no address at all, so
#: there is nothing in it to point anywhere. Which page it is all about is
#: Rouh's own answer, read off the frame it loaded, and only the canvas's own
#: frame is listened to (``askFromPage`` in app.js, ``ASKAI_HOSTED`` in
#: askai.js, and the head of ``askai.py`` for why the surface is one).
ASKAI_MESSAGE = "rouh-askai"
ASKAI_ASK = "rouh-askai-do"

#: The message the task browser sends when the person has moved a task onto
#: another project, or renamed, added or deleted one. A sandboxed page cannot
#: write any more than it can read, so the change is handed to the page around
#: the frame, which is signed in and makes the request (``fileRelay`` in
#: app.js, and ``POST /api/workspace/filing``).
#:
#: It is not shaped like ``ASK_MESSAGE`` and the difference is the point: that
#: one carries an address, and is allowlisted against three of them; this one
#: carries an action name and object ids and no address at all, so there is
#: nothing in it for a page to point somewhere it was not meant to go. The
#: server decides what each action is allowed to do (``objectindex.change``).
FILE_MESSAGE = "rouh-page-file"

#: The message back: whether it was saved, why not when it was not, and the
#: whole index as it is now, so the page draws what is really on disk rather
#: than what it hoped it had done.
FILED_MESSAGE = "rouh-frame-filed"

#: The message the task browser sends when the list it shows changes - a
#: project or a column pressed, words typed into its search box - and, with
#: ``ask`` on it and nothing else, when it has just been drawn. Rouh keeps the
#: last one for the tab (``TASKS_VIEW`` in app.js) and answers the ask with it,
#: as ``VIEWED_MESSAGE``, so the browser opened again - by Back from a task or
#: a page opened out of it, above all - shows the list the person left.
#:
#: It is kept by Rouh because the frame cannot keep it: the frame is thrown
#: away every time something is opened out of it, and a sandboxed page has no
#: storage. It used to be a step in the tab's history, pushed from inside the
#: frame, and a step a frame leaves behind is one Back lands on once the frame
#: is gone - a press that does nothing in Chromium, and a blank white page in
#: Safari (fr_08e89370f7c7, and ``frameWrite`` in app.js). It carries a view
#: and some words, and no address.
VIEW_MESSAGE = "rouh-page-view"
VIEWED_MESSAGE = "rouh-frame-view"

#: The message a project's own page sends when the box at the top of it has
#: been typed into and Enter pressed, or the floating button pressed: start a
#: chat in this project, and take me to it.
#:
#: A task's or a step's own page sends it too, with ``task`` on it instead of
#: ``project``, when its Start chat is pressed: start a new conversation about
#: the task and put it on the screen, beside the page, with the cursor in it.
#: It is the task's own while nothing has been said about the task, and a new
#: chat under the task once something has (`conversations.start_for_task`).
#: Which task is Rouh's answer, read off the page it framed (``taskChat`` in
#: app.js), not the id the page sent.
#:
#: An answer from the question box on a waiting task's page sends the same
#: message with ``say`` and ``answers`` on it: which task, what it asked and
#: what the person pressed or wrote in that box, which Rouh sends in the new
#: chat as if typed (``taskSaidIt`` in app.js). The press in that box is the
#: person's Send. Only Rouh's own pages of an object may carry words to send
#: (``ownPage`` in app.js, by the address Rouh itself loaded into the frame):
#: a page a job built is shown in the same frame and runs its own scripts, and
#: it can start a chat but never speak in it.
#:
#: It is not a filing action and could not be one. Making a conversation and
#: moving the person into it is the socket's work, not a route's
#: (`new_chat` in PROTOCOL.md), and every tab follows the switch. Like
#: ``FILE_MESSAGE`` it carries an object id and words, and no address at all:
#: which project is named by the id the page was drawn from, and Rouh looks it
#: up rather than believing anything about it.
CHAT_MESSAGE = "rouh-page-chat"

#: The message a waiting task's page sends when its question is dismissed:
#: what the box asked, and nothing else. Rouh writes it down against the task
#: it read off the canvas (``taskDismiss`` in app.js, `dismiss_question` in
#: PROTOCOL.md), and only from its own page of that task (``ownPage``).
DISMISS_MESSAGE = "rouh-page-dismiss"

#: The message a project's own page sends when a file has been chosen on it:
#: the project's id, the name the browser gave the file, and its bytes as an
#: ArrayBuffer, **transferred** rather than copied. Rouh makes the request
#: (`POST /api/workspace/file`).
#:
#: The bytes and not the `File`, and the difference is not a preference. A
#: framed page is sandboxed and has an origin of its own, so a file the browser
#: hands it belongs to that origin; a `File` cloned up to Rouh and put in a
#: request from there is refused inside the browser before it goes anywhere -
#: `net::ERR_ALPN_NEGOTIATION_FAILED`, and not one line in the server's log to
#: say so. An ArrayBuffer has no origin and crosses, and transferring it means
#: a sixty-four megabyte file is moved rather than copied, and never becomes an
#: eighty-five megabyte string the way base64 would.
UPLOAD_MESSAGE = "rouh-page-upload"

#: The message back for both of those: whether it worked, why not when it did
#: not, and the project as it now stands.
PROJECT_MESSAGE = "rouh-frame-project"

#: The message a page in the workspace sends to put a report in Rouh's
#: Gene therapy drawer: ``body``, the words, ``shots``, up to four screenshots as
#: addresses beside the page, and ``edit``, whether the cursor goes in the
#: words or on Send. The bug reports a job writes after using Rouh as a
#: customer are the first such page (task 30, step 44).
#:
#: It fills the drawer and never sends it. A page a job built never speaks for
#: the person (``ownPage`` in app.js), and a feedback is read and built by
#: itself the moment it lands, so the press that sends it is the person's own
#: Mutate (``gtFromPage``). Only the canvas's own frame, only a page of
#: the workspace, and only screenshots under ``/workspace/``, which Rouh
#: fetches itself, signed in. The drawer was Feedback until 12 October 2026, and the
#: two messages keep that name, because pages already written send and read them.
FEEDBACK_MESSAGE = "rouh-page-feedback"

#: The message back: whether the drawer took it, how many screenshots went
#: with it, and why not when it did not.
FEEDBACK_TAKEN_MESSAGE = "rouh-frame-feedback"

#: The message back: one part of one answer. ``part`` is "open" with the status,
#: then "chunk" for each piece of the body as it arrives, then "end". Three
#: parts rather than one because the answer is streamed and the drawer draws it
#: as it comes.
ANSWER_MESSAGE = "rouh-page-answer"

#: What a framed page's own request has to start with before it is handed up at
#: all. The drawer is the workspace's own code, so it asks for the laptop
#: proxy's addresses - ``/api/ask``, ``/api/threads`` - and app.js maps those
#: three onto Rouh's own routes and refuses every other one. Anything a page
#: fetches that does not start with this is left to the browser, which refuses
#: it as it always did.
ASK_PREFIX = "/api/"

#: The keys a framed page hands up to Rouh. The first three climb one level
#: of the canvas's breadcrumb - a page to its task, a task to the index, the
#: index out - which is what a reader means by Escape and by back. Everything
#: else belongs to the page.
#:
#: `k` is the exception and it is not a plain `k`: Cmd+K, or Ctrl+K, opens
#: search, and a task page loaded on the canvas takes the whole window with the
#: keyboard inside the frame, so without this the one shortcut that is supposed
#: to work from anywhere is the one that stops working the moment you open a
#: task. A `k` with neither of those held is the page's, like every other
#: letter, and is dropped below before it is handed up.
FRAME_KEYS = ("Escape", "Backspace", "ArrowLeft", "k", "K")

#: What the stand-in answers when a page asks how it should be drawn. Rouh
#: is dark, and only dark, so a page framed inside it is too.
DARK = "dark"


def storage_script() -> bytes:
    """The storage stand-in, answering a colour lookup with ``DARK``.

    A lookup under any key holding "theme" gets "dark" until the page sets that
    key itself; the pages in the workspace keep theirs under names such as
    ``t38-theme`` and ``bb-theme``. Without this a sandboxed page, which has no
    storage to read, would fall back to the reader's own machine and come out
    light inside a dark screen.
    """
    told = json.dumps(DARK).encode("ascii")
    return (
        b"<script>/* Put in by Rouh. This page is sandboxed, so the browser gives it"
        b" no storage and throws when a script touches it. This stand-in lives in"
        b" memory and is forgotten when the page closes. Asked how it should be"
        b" drawn, it answers dark, which is how Rouh is drawn. */\n"
        b"(function(){var T=" + told + b";"
        b"function m(){var d=Object.create(null);return{"
        b"getItem:function(k){k=String(k);return k in d?d[k]:(/theme/i.test(k)?T:null)},"
        b"setItem:function(k,v){d[String(k)]=String(v)},"
        b"removeItem:function(k){delete d[String(k)]},"
        b"clear:function(){for(var k in d)delete d[k]},"
        b"key:function(i){var s=Object.keys(d);return i>=0&&i<s.length?s[i]:null},"
        b"get length(){return Object.keys(d).length}}}"
        b"['localStorage','sessionStorage'].forEach(function(n){"
        b"try{if(window[n])return}catch(e){}"
        b"try{Object.defineProperty(window,n,{value:m(),configurable:true})}catch(e){}"
        b"});"
        b"})();</script>\n"
    )


def address_script() -> bytes:
    """The page telling the page that frames it where it is and what it is called.

    A framed page is sandboxed and has an origin of its own, so nothing around
    it can read its address, its title or its history. The canvas's breadcrumb
    needs all three: to say where the reader is, and to take them back a level
    when they have followed a link inside the frame. So the page says so itself, in
    a message to its parent and to nobody else, once as soon as this runs and
    again when the page's own ``<title>`` has been read.

    It carries the address and the title and nothing else, and it is sent only
    when there is a parent to send it to.
    """
    kind = ADDRESS_MESSAGE.encode("ascii")
    return (
        b"<script>/* Also put in by Rouh. This page is sandboxed, so the page that"
        b" frames it cannot read where it is. It says so itself, to that page and to"
        b" nobody else. */\n"
        b"(function(){var p;try{p=window.parent}catch(e){return}"
        b"if(!p||p===window)return;"
        b"function tell(){try{p.postMessage({type:'" + kind + b"',"
        b"href:String(location.href),title:String(document.title||'')},'*')}catch(e){}}"
        b"tell();"
        b"if(document.readyState==='loading')"
        b"document.addEventListener('DOMContentLoaded',tell);else tell();"
        b"})();</script>\n"
    )


def follow_script() -> bytes:
    """A link followed inside the frame, handed to the page around it.

    A sandboxed frame has an origin of its own, and the browser will not send
    Rouh's sign-in cookie with a request such a frame starts for itself. The
    first load is fine, because the page around the frame starts it; a link
    clicked inside the frame is not, and Rouh answered it with "Sign in to
    Rouh first." That is what a reader saw when they clicked a task.

    So a framed page never navigates itself. A left click on a link into the
    workspace, **or onto any object's own address**, is stopped here and the
    address is handed to the page around the frame. A link of this site's that
    is neither is left exactly as it was; another site, a place in the page
    itself, and a click meant for a new tab, are below.

    The second half of that is what makes an object page's rows work. A project
    lists its chats, its runs and what it has drawn, and each of those is a
    plain link to the address that object already has (`rouh/addressing.py`);
    a chat is a conversation and a run is a terminal, so neither is a page to
    load into a frame, and app.js opens them where they live instead
    (`frameGo`). Only the prefixes below are carried, and they are written here
    rather than taken from the page: the worst a page can say is the name of
    something to open, and Rouh decides whether there is anything there.

    A left click on an http or https address of another site opens it in a
    tab of its own, with no opener and no referrer, from here, inside the
    press. Left to the browser it would take the frame itself there. It was
    handed up to Rouh to open from 27 September 2026, when the frame could not
    open a tab at all (fr_e2dde690a576); the frame on the canvas may since
    2 October 2026 (`allow-popups` in app.js), and a tab opened from inside
    the press needs no browser to carry the press across the frame's edge,
    which Safari does not. ``frameOut`` in app.js still opens one for a frame
    that hands it up.

    A link to a place in the page itself - ``#part``, or the page's own name
    with ``#part`` on it - is moved to here, and is not left to the browser.
    The page is handed to the frame as text, so the browser has it at
    ``about:srcdoc``, and every relative address in it is read against the
    ``<base>`` Rouh put in (``frame_head``). The browser read ``#p-email``
    the same way, as the page's real address with ``#p-email`` on it, and took
    the frame there: out of ``about:srcdoc``, to an address the frame is not
    signed in at, which Rouh then loaded again from the top. Every section
    menu and every footnote on a workspace page did it. Petar, 1 October 2026,
    on a client's GDPR explainer: clicking "Her email, point by point" did
    not go there, "the whole thing refreshes". So the fragment is put onto the
    address the frame really has, with ``location.replace``: the same page,
    scrolled, with ``hashchange`` fired for a page that routes on it, and no
    step left in the tab's history (``frameWrite`` in app.js says why a step
    a frame leaves is one Back lands on with nothing to show).

    The same move is made when Rouh asks for it (``HASH_MESSAGE``), after it
    has loaded another page of the task for a link that named a place in it.

    A link pressed to open somewhere else - Cmd or Ctrl held for a new tab,
    Shift for a new window, the middle button - is the browser's, exactly as
    on any page, and nothing of the page's own sees the press. Before
    2 October 2026 the page's own script could: the "source 1" links of a
    playbook switch its section by script, and Cmd on one switched the section
    in this tab with nothing opened anywhere (Petar, "even if I hold CMD the
    page loads in the same tab", fr_2d5208267e36). So it is caught first, on
    the way down, and stopped there without being prevented: the browser opens
    the link's own address in a new tab, and the tab the person is in stays
    exactly where it was. That address is the file, `/workspace/...`, and a
    tab opened straight onto one is sent on to Rouh's own address for it by
    the server (`_rouh_address` in views.py), so the new tab is Rouh with the
    page in it. A bare ``#`` is a button dressed as a link and is left alone.
    """
    kind = FOLLOW_MESSAGE.encode("ascii")
    hashed = HASH_MESSAGE.encode("ascii")
    route = ROUTE.encode("ascii")
    # And a task's Sources (`objectindex._sources_section`), which is a place in Rouh, not a page.
    mine = json.dumps([f"/{one}/" for one in OBJECT_ROUTES] + [addressing.SOURCES + "/"],
                      separators=(",", ":")).encode("ascii")
    return (
        b"<script>/* Put in by Rouh. This page is sandboxed, so the browser sends no"
        b" sign-in with a request it starts for itself. It asks the page that frames"
        b" it to load the address instead. */\n"
        b"(function(){var p;try{p=window.parent}catch(e){return}"
        b"if(!p||p===window)return;var mine=" + mine + b";"
        b"function jump(h){try{location.replace(String(location.href).split('#')[0]+(h||'#'))}catch(err){}}"
        b"function ours(at){if(at.indexOf('" + route + b"')===0)return true;"
        b"for(var i=0;i<mine.length;i++)if(at.indexOf(mine[i])===0)return true;"
        b"return false}"
        b"document.addEventListener('click',function(e){"
        b"if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;"
        b"var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;"
        b"if(!a)return;"
        b"var raw=a.getAttribute('href')||'';"
        b"if(!raw)return;"
        # The frame's own origin is "null", so what "this site" means here is
        # the address the page was told it is at, in its <base>.
        b"var u,home;try{u=new URL(a.href);home=new URL(document.baseURI)}catch(err){return}"
        # A place in this very page: moved to here, never followed (above).
        b"if(raw.charAt(0)==='#'||(raw.indexOf('#')>=0&&u.href.split('#')[0]===home.href.split('#')[0])){"
        b"if(a.target&&a.target!=='_self')return;"
        b"e.preventDefault();jump(u.hash);return}"
        b"if(u.origin!==home.origin&&/^https?:$/.test(u.protocol)){e.preventDefault();"
        b"try{window.open(u.href,'_blank','noopener,noreferrer')}catch(err){}"
        b"return}"
        b"if(a.target&&a.target!=='_self')return;"
        b"if(u.origin!==home.origin||!ours(u.pathname))return;"
        b"e.preventDefault();"
        b"try{p.postMessage({type:'" + kind + b"',href:u.pathname+u.search+u.hash},'*')}catch(err){}"
        b"},false);"
        # Cmd, Ctrl or Shift held, or the middle button: the browser's own, and
        # nothing of the page's sees it (above).
        b"function tab(e){"
        b"if(e.defaultPrevented||e.altKey)return;"
        b"if(e.type==='click'?(e.button!==0||!(e.metaKey||e.ctrlKey||e.shiftKey)):e.button!==1)return;"
        b"var a=e.target&&e.target.closest?e.target.closest('a[href]'):null;"
        b"if(!a)return;var raw=a.getAttribute('href')||'';"
        b"if(!raw||raw==='#'||/^javascript:/i.test(raw))return;"
        b"e.stopImmediatePropagation()}"
        b"window.addEventListener('click',tab,true);window.addEventListener('auxclick',tab,true);"
        b"window.addEventListener('message',function(e){"
        b"var m=e.data;if(e.source!==p||!m||m.type!=='" + hashed + b"'"
        b"||typeof m.hash!=='string'||m.hash.charAt(0)!=='#')return;jump(m.hash)})"
        b"})();</script>\n"
    )


def keys_script() -> bytes:
    """The keyboard, both ways across the frame's edge.

    Keys pressed inside a frame stay inside it, and keys pressed outside it
    stay outside. Both halves of the tasks view's keyboard need to cross.

    Up: Escape, Backspace and Alt/Cmd + Left are Rouh's - they climb one
    level of the canvas's breadcrumb - so the page hands them up. Escape goes
    up even where the page has a use of its own for it: backing out of what is
    loaded is what a reader means by Escape, and it is the one key they cannot
    get wrong. Cmd+K, or Ctrl+K, goes up too: it opens search, which is
    supposed to work from anywhere, and a task page on the canvas holds the
    whole window.

    Down: every other key is the page's - the arrows that walk its tasks, Enter
    that opens one, Space that unfolds one, "/" that goes to its search box. A
    reader who has not yet clicked into the frame has the keyboard on Rouh's
    own page, so Rouh sends those keys down and they are pressed here.
    """
    up = KEY_MESSAGE.encode("ascii")
    down = TYPE_MESSAGE.encode("ascii")
    mine = json.dumps(list(FRAME_KEYS), separators=(",", ":")).encode("ascii")
    return (
        b"<script>/* Also put in by Rouh. A key pressed in a frame never reaches the"
        b" page around it, and the other way about. These two carry the few that have"
        b" to cross. */\n"
        b"(function(){var p;try{p=window.parent}catch(e){return}"
        b"if(!p||p===window)return;var M=" + mine + b";"
        b"window.addEventListener('keydown',function(e){"
        b"if(e.defaultPrevented||M.indexOf(e.key)<0)return;"
        b"var a=document.activeElement,typing=a&&/^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName);"
        b"if(e.key==='Backspace'&&typing)return;"
        b"if(e.key==='ArrowLeft'&&!e.altKey&&!e.metaKey)return;"
        b"if((e.key==='k'||e.key==='K')&&!e.metaKey&&!e.ctrlKey)return;"
        b"try{p.postMessage({type:'" + up + b"',key:e.key,alt:!!e.altKey,meta:!!e.metaKey,"
        b"ctrl:!!e.ctrlKey},'*')}catch(err){}"
        b"},false);"
        b"window.addEventListener('message',function(e){"
        b"if(e.source!==p)return;var m=e.data;"
        b"if(!m||m.type!=='" + down + b"'||typeof m.key!=='string')return;"
        b"var a=document.activeElement,t=a&&a!==document.body?a:(document.body||document);"
        b"try{t.dispatchEvent(new KeyboardEvent('keydown',{key:m.key,bubbles:true,cancelable:true,"
        b"altKey:!!m.alt,ctrlKey:!!m.ctrl,metaKey:!!m.meta,shiftKey:!!m.shift}))}catch(err){}"
        b"},false)})();</script>\n"
    )


def ask_script() -> bytes:
    """The Ask AI drawer's questions, carried out through the page around the frame.

    The drawer is the workspace's own code and fetches the laptop proxy's own
    addresses. In Rouh it cannot: the page is sandboxed, so ``connect-src
    'none'`` refuses the request before it leaves the page, and the origin the
    browser gives the page means no sign-in would travel with it anyway. That
    is not a limit to work around - it is what keeps a page that runs its own
    scripts from talking to Rouh as the person.

    So ``fetch`` gets a stand-in, in exactly the same spirit as the storage
    stand-in above: a request to ``/api/...`` is handed to the page that frames
    this one, which is signed in, and comes back a piece at a time. Everything
    else a page fetches is left to the browser and is refused as it always was.

    What comes back is a real ``Response`` over a real stream, so the drawer's
    own reader loop is untouched. What goes up is the path, the method and the
    body, and not the query: the only thing the drawer puts in a query is which
    page it is asking about, and that is the one thing the page around the frame
    decides for itself, from the frame it is showing.
    """
    up = ASK_MESSAGE.encode("ascii")
    down = ANSWER_MESSAGE.encode("ascii")
    prefix = ASK_PREFIX.encode("ascii")
    return (
        b"<script>/* Also put in by Rouh. This page may not call out, so the Ask AI"
        b" drawer on it asks the page that frames it, which is signed in. */\n"
        b"(function(){var p;try{p=window.parent}catch(e){return}"
        b"if(!p||p===window)return;"
        b"var n=0,waiting=Object.create(null),enc=new TextEncoder();"
        b"window.addEventListener('message',function(e){"
        b"if(e.source!==p)return;var m=e.data;"
        b"if(!m||m.type!=='" + down + b"')return;"
        b"var job=waiting[m.id];if(!job)return;"
        b"if(m.part==='open')job.open(m);"
        b"else if(m.part==='chunk')job.chunk(String(m.text||''));"
        b"else if(m.part==='end'){job.end();delete waiting[m.id]}},false);"
        b"var was=window.fetch;"
        b"window.fetch=function(input,init){var here,url;"
        b"try{here=new URL(document.baseURI);"
        b"url=new URL(typeof input==='string'?input:input.url,here)}"
        b"catch(err){return was.apply(window,arguments)}"
        b"if(url.origin!==here.origin||url.pathname.indexOf('" + prefix + b"')!==0)"
        b"return was.apply(window,arguments);"
        b"var id=++n,control=null,opened=false;"
        b"var stream=new ReadableStream({start:function(c){control=c}});"
        b"return new Promise(function(resolve){"
        b"waiting[id]={"
        b"open:function(m){if(opened)return;opened=true;"
        b"resolve(new Response(stream,{status:m.status||500}))},"
        b"chunk:function(t){try{control.enqueue(enc.encode(t))}catch(err){}},"
        b"end:function(){if(!opened){opened=true;resolve(new Response(stream,{status:500}))}"
        b"try{control.close()}catch(err){}}};"
        b"try{p.postMessage({type:'" + up + b"',id:id,path:url.pathname,"
        b"method:String((init&&init.method)||'GET').toUpperCase(),"
        b"body:(init&&typeof init.body==='string')?init.body:''},'*')}"
        b"catch(err){waiting[id].end()}})}"
        b"})();</script>\n"
    )


#: What Rouh says to a request for the workspace that carries no sign-in.
SIGNED_OUT = "Sign in to Rouh first."


def signed_out_page() -> bytes:
    """The refusal, as a page, for a browser that navigated to it.

    A sandboxed frame that takes itself somewhere carries no sign-in - the
    browser sends Rouh's cookie with a request the page around the frame
    starts, and not with one the frame starts for itself - so Rouh refuses
    it. The workspace's own index takes itself somewhere every time Enter is
    pressed on a task, and the reader was left looking at these four words
    instead of at their task.

    A link clicked inside a frame is handed to the page around it before the
    frame can go anywhere (``follow_script``). Nothing can catch a page sending
    itself somewhere, so this catches it after the fact: the refusal names its
    own address to the page around the frame, which is signed in, fetches it
    and puts it back. A frame that goes anywhere by itself still lands where it
    meant to.

    Opened on its own, at its own address, it is four words and nothing else
    happens: there is no page around it to hand anything to.
    """
    kind = FOLLOW_MESSAGE.encode("ascii")
    words = SIGNED_OUT.encode("ascii")
    return (
        b'<!doctype html><meta charset="utf-8"><title>' + words + b"</title>\n"
        b'<body style="margin:0;padding:24px;color:#8b95a3;background:transparent;'
        b'font:15px/1.5 -apple-system,BlinkMacSystemFont,sans-serif">' + words + b"\n"
        b"<script>/* Put in by Rouh. A frame cannot be signed in, so it hands the"
        b" address back to the page that frames it, which is. */\n"
        b"(function(){var p;try{p=window.parent}catch(e){return}"
        b"if(!p||p===window)return;"
        b"try{p.postMessage({type:'" + kind + b"',"
        b"href:location.pathname+location.search},'*')}catch(e){}})();</script>\n"
    )


def frame_head(at: str, base: bool = True) -> bytes:
    """The two lines a page gets before anything else when Rouh frames it.

    ``at`` is the address the page is at. A framed page arrives as text rather
    than at an address of its own - that is what keeps Rouh's sign-in out of
    the browser's hands - so it is told where it is, in a ``<base>``, and every
    relative link and picture in it resolves as it always did. A page that
    already says where it is itself keeps its own answer (``base`` is False).

    The frame's own ``sandbox`` attribute keeps the page apart from Rouh, as
    ``CSP`` does when the page is opened at its own address. What the attribute
    does not carry is the promise that the page cannot call out, so that half
    is said again here, where the page itself can read it.
    """
    here = html.escape(at, quote=True).encode("utf-8", "surrogateescape")
    said = (b'<base href="' + here + b'">\n') if base else b""
    return b'<meta http-equiv="Content-Security-Policy" content="' \
           + FRAME_CSP.encode("ascii") + b'">\n' + said


#: A button tapped while a field has an on-screen keyboard is pressed on that
#: one tap. Rouh's own page loads the same file; a page on the canvas has the
#: same text boxes beside buttons (its Ask AI drawer, its comments, a task's
#: question), so it gets it too (fr_f180995a3a50).
PRESS = Path(__file__).resolve().parent / "static" / "press.js"


def press_script() -> bytes:
    """`press.js`, put into the page, or nothing when it cannot be read."""
    try:
        code = PRESS.read_bytes()
    except OSError:
        log.warning("a framed page goes without press.js: it could not be read")
        return b""
    return b"<script>" + code + b"</script>\n"


def frame_script() -> bytes:
    """The four things a page can only do while Rouh is framing it: follow a
    link through the page around it, share the keyboard with it, reach Rouh's
    own routes through it, and take a tap on a button while a field has the
    keyboard."""
    return follow_script() + keys_script() + ask_script() + press_script()


def page_script(at: str | None = None, base: bool = True,
                askai: bytes = b"") -> bytes:
    """Everything Rouh puts into a workspace page: the storage stand-in, the
    page saying where it is, and - when Rouh is the one framing it - where it
    is, its links, its keyboard and the Ask AI drawer.

    ``askai`` is the drawer, built by ``askai.py`` and handed in rather than
    built here: it comes off the workspace, and this module knows nothing about
    the workspace's own code. It goes in last, after the stand-in the drawer's
    script reads its width out of.
    """
    put = storage_script() + address_script()
    if at is None:
        # A page opened at its own address is on its own: the drawer could not
        # reach Rouh from there, because there is no signed-in page around it
        # to carry the request. So it is not offered rather than offered broken.
        return put
    return frame_head(at, base) + put + frame_script() + askai


#: What is put into a page opened at its own address, rather than framed.
STORAGE = page_script()

#: A page that names a ``<base>`` of its own, in the bytes as they arrive. The
#: first ``<base href>`` in a page is the one the browser follows, so Rouh
#: puts none in over the top of one the page already has.
_HAS_BASE = re.compile(rb"<base\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*\bhref\s*=", re.IGNORECASE)

_HEAD = re.compile(rb"<head(?:\s[^>]*)?>", re.IGNORECASE)
_HTML = re.compile(rb"<html(?:\s[^>]*)?>", re.IGNORECASE)
_DOCTYPE = re.compile(rb"<!doctype[^>]*>", re.IGNORECASE)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title\s*>", re.IGNORECASE | re.DOTALL)


class Missing(Refused):
    """A path that passes every rule but names no file."""


def _check_parts(parts, asked: str) -> None:
    parts = list(parts)
    for part in parts:
        if not part:
            raise Refused(f"{asked} has an empty part in it.")
        if part.startswith("."):
            raise Refused(
                f"{asked} goes through {part}, and nothing whose name starts with a dot "
                "is ever served."
            )
    if not parts or parts[0] not in TOPS:
        raise Refused(
            f"{asked} is not under one of {', '.join(t + '/' for t in TOPS)}, and "
            "only pages there are shown."
        )


def _check_kind(name: str, asked: str) -> None:
    low = name.lower()
    if ".sqlite3" in low:
        raise Refused(f"{asked} is a database, and databases are never served.")
    suffix = os.path.splitext(low)[1]
    if suffix == ".md":
        raise Refused(
            f"{asked} is a notes file. No .md file is served, a task's AGENTS.md "
            "included."
        )
    if suffix not in TYPES:
        raise Refused(
            f"{asked} is not a kind of file a page is made of "
            f"({', '.join(sorted(TYPES))})."
        )


def check(root, asked: str, raw: str = "") -> Path:
    """The file ``asked`` names, if it may be served, or Refused saying why.

    ``asked`` is relative to the workspace and decoded once, as the route
    receives it. ``raw`` is the address as it arrived, still encoded.
    """
    if not root:
        raise Refused("There is no workspace on this machine.")
    low = (raw or "").lower()
    if any(token in low for token in ENCODED):
        raise Refused(
            "The address holds an encoded slash, backslash, percent sign, dot or NUL, "
            "which is never followed."
        )
    rel = str(asked or "")
    if not rel:
        raise Refused("No path was given.")
    if rel.startswith("/") or "\\" in rel or "\x00" in rel or "%" in rel:
        raise Refused(f"{rel} is not a plain path inside the workspace.")
    parts = rel.split("/")
    _check_parts(parts, rel)
    _check_kind(parts[-1], rel)

    # read_workspace's own checks: git's files, names secrets are kept under,
    # and anything a link leads to outside the folder.
    base = Path(root).resolve()
    target = resolve(base, rel)
    # And this module's rules again, on where the links actually led.
    inside = target.relative_to(base).parts
    _check_parts(inside, rel)
    _check_kind(inside[-1], rel)
    if not target.is_file():
        raise Missing(f"There is no file at {rel} in the workspace.")
    return target


def _read_upto(target: Path, limit: int) -> bytes:
    """Up to ``limit`` + 1 bytes of a file that has passed ``check``.

    The path is already resolved, so a link appearing at its end since the
    check is refused rather than followed.
    """
    fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as fh:
        return fh.read(limit + 1)


def read(root, asked: str, raw: str = "", at: str | None = None,
         askai: bytes = b"", mark: bool = False,
         source: str | None = None, pictures=None) -> tuple[bytes, str]:
    """A file's bytes and its type. A page comes with the files it names put
    into it, and with the storage stand-in.

    ``at`` is the address the page is at, and is given only when Rouh is the
    one framing it: a framed page is handed to the frame as text, so it has to
    be told where it is and given the few things it can only do in a frame.

    ``askai`` is the Ask AI drawer for this page, built by ``askai.py``, and is
    put in only where ``at`` is.

    ``mark`` marks every element with where it is in the file, for a reader
    who may change the page and points at part of it (`with_marks`). It is
    done first, on the file as it is on disk, so the numbers are the file's.

    ``source`` is the page as it was at some earlier moment, served in place of
    the file on disk (`rouh/pagehistory.py`). The path is still checked as it
    always is, so an old version is only ever of a page that may be served.

    ``pictures`` links the pictures the page names rather than putting them in
    (``with_files``), and is given only with ``at``.
    """
    target = check(root, asked, raw)
    suffix = os.path.splitext(target.name.lower())[1]
    try:
        body = _read_upto(target, MAX_BYTES) if source is None \
            else source.encode("utf-8", "surrogateescape")
    except OSError:
        raise Missing(f"There is no file at {asked} in the workspace.") from None
    if len(body) > MAX_BYTES:
        raise Refused(f"{asked} is larger than {MAX_BYTES // 1_000_000} MB.")
    if suffix == ".html":
        if mark:
            body = with_marks(body.decode("utf-8", "surrogateescape")).encode(
                "utf-8", "surrogateescape")
        body = with_storage(with_files(root, asked, body,
                                       pictures if at is not None else None), at, askai)
    return body, TYPES[suffix]


def with_storage(page: bytes, at: str | None = None,
                 askai: bytes = b"") -> bytes:
    """The page with everything Rouh puts in first inside its head.

    It has to run before any of the page's own scripts, and a page reads how it
    should be drawn out of storage in the head. Never before the doctype, which
    would drop the page into the browser's old quirks mode.

    A page that already names a ``<base>`` of its own keeps it: the first one
    in a page is the one the browser follows, so Rouh's would silently take
    the page's own answer away.
    """
    script = page_script(at, base=at is not None and not _HAS_BASE.search(page),
                         askai=askai)
    for pattern in (_HEAD, _HTML, _DOCTYPE):
        found = pattern.search(page)
        if found:
            return page[: found.end()] + script + page[found.end():]
    return script + page


# --------------------------------------------------------------------------
# Files kept beside a page, put into it as it is sent
# --------------------------------------------------------------------------

#: A reference that starts with a scheme (https:, data:, mailto:) is another
#: site's or not a file at all.
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_SPACE = " \t\n\r\f"
_TAG = re.compile(
    r"<!--.*?(?:-->|\Z)"                                     # a comment, left as it is
    r"|<(?P<name>[A-Za-z][A-Za-z0-9:-]*)"                    # a start tag
    r"(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)>",
    re.DOTALL)
_ATTR = re.compile(
    r"(?P<name>[^\s\"'>/=]+)"
    r"(?:\s*=\s*(?P<value>\"(?P<dq>[^\"]*)\"|'(?P<sq>[^']*)'|(?P<uq>[^\s\"'=<>`]+)))?")
_CSS_URL = re.compile(
    r"/\*.*?(?:\*/|\Z)"                                      # a comment, left as it is
    r"|url\(\s*(?:\"(?P<dq>[^\"\\\n]*)\"|'(?P<sq>[^'\\\n]*)'|(?P<uq>[^\"'()\\\s]*))\s*\)",
    re.DOTALL | re.IGNORECASE)
#: A <base> sends every relative reference somewhere else, so such a page is
#: left as it is.
_BASE = re.compile(r"<base\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*\bhref\s*=", re.IGNORECASE)
#: Elements whose content is not markup. It is passed on as it is, except that
#: a <style>'s own url()s are put in.
_RAW_END = {name: re.compile(rf"</{name}[\s/>]", re.IGNORECASE) for name in (
    "script", "style", "textarea", "title", "xmp", "iframe", "noembed", "noframes", "noscript")}


def _value(attr: re.Match) -> str:
    for group in ("dq", "sq", "uq"):
        if attr.group(group) is not None:
            return attr.group(group)
    return ""


def _candidates(srcset: str):
    """The (address, descriptors) pairs of a srcset, read as a browser reads them."""
    pos, end = 0, len(srcset)
    while pos < end:
        while pos < end and srcset[pos] in _SPACE + ",":
            pos += 1
        if pos >= end:
            return
        start = pos
        while pos < end and srcset[pos] not in _SPACE:
            pos += 1
        url, descriptor = srcset[start:pos], ""
        if url.endswith(","):
            url = url.rstrip(",")
        else:
            depth, begin = 0, pos
            while pos < end and not (srcset[pos] == "," and depth == 0):
                depth += {"(": 1, ")": -1}.get(srcset[pos], 0)
                depth = max(depth, 0)
                pos += 1
            descriptor = " ".join(srcset[begin:pos].split())
            pos += 1
        if url:
            yield url, descriptor


class _Inliner:
    """Puts the files one page names into it. One for each page sent."""

    def __init__(self, root, page: str, pictures=None) -> None:
        self.root = root
        self.page = page
        self.folder = page.rsplit("/", 1)[0]
        self.total = 0
        # The address of a picture by its path, when pictures are linked rather
        # than put in (`rouh/picturelinks.py`), else None.
        self.pictures = pictures
        self.linked = 0

    def address(self, folder: str, ref: str, kinds: tuple[str, ...],
                link: bool = False) -> str | None:
        """A data: address holding the file ``ref`` names, read from ``folder``,
        or None to leave ``ref`` exactly as it was. With ``link``, and pictures
        linked for this page, the picture's own address instead."""
        ref = re.sub(r"[\t\n\r]", "", ref.strip(_SPACE))
        if not ref or ref[0] in "#/?\\" or _SCHEME.match(ref):
            return None
        path, _, fragment = ref.partition("#")
        path = path.split("?", 1)[0]
        if not path:
            return None
        # `../booklet.css` from a page in `pages/` is read the way the browser
        # would read it, from the folder above. Folded away before the check,
        # because the check refuses any part starting with a dot. Climbing
        # stops at the page's own task: a page shared with somebody carries
        # its task's files and never another task's.
        asked = posixpath.normpath(f"{folder}/{unquote(path)}")
        if asked == ".." or asked.startswith(("../", "/")):
            return None
        if ".." in unquote(path).split("/"):
            from .steps import task_part
            task = task_part(self.folder)
            if not asked.startswith(task + "/"):
                return None
        try:
            # The same function, and so the same rules, as a file asked for by
            # its own address: ``path`` is the address as the page wrote it.
            target = check(self.root, asked, path)
        except Refused:
            return None
        suffix = os.path.splitext(target.name.lower())[1]
        if suffix not in kinds or os.path.splitext(asked.lower())[1] not in kinds:
            return None
        if link and self.pictures is not None and suffix in PICTURES:
            linked = self.pictures(asked)
            if linked:
                self.linked += 1
                return linked + (f"#{fragment}" if fragment else "")
        try:
            data = _read_upto(target, INLINE_FILE_MAX)
        except OSError:
            return None
        if len(data) > INLINE_FILE_MAX:
            log.warning("pages: %s in %s is left as a plain reference: it is %.1f MB, "
                        "and no file over %d MB is put into a page", ref, self.page,
                        target.stat().st_size / 1e6, INLINE_FILE_MAX // 1_000_000)
            return None
        if self.total + len(data) > INLINE_PAGE_MAX:
            log.warning("pages: %s in %s is left as a plain reference: the page already "
                        "holds %.1f MB of files, and at most %d MB is put into one page",
                        ref, self.page, self.total / 1e6, INLINE_PAGE_MAX // 1_000_000)
            return None
        self.total += len(data)
        if suffix in STYLESHEETS:
            # A style sheet's own references are read from its own folder.
            text = data.decode("utf-8", "surrogateescape")
            data = self.css(text, asked.rsplit("/", 1)[0]).encode("utf-8", "surrogateescape")
        kind = TYPES[suffix].replace(" ", "")
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{kind};base64,{encoded}" + (f"#{fragment}" if fragment else "")

    def css(self, text: str, folder: str) -> str:
        """Style sheet text with every url() it may have put in."""
        def swap(found: re.Match) -> str:
            if found.group(0).startswith("/*"):
                return found.group(0)
            ref = next(g for g in (found.group("dq"), found.group("sq"), found.group("uq"))
                       if g is not None)
            new = self.address(folder, ref, IN_CSS)
            return f'url("{new}")' if new else found.group(0)
        return _CSS_URL.sub(swap, text)

    def srcset(self, value: str) -> str | None:
        parts, changed = [], False
        for url, descriptor in _candidates(value):
            new = self.address(self.folder, url, PICTURES, link=True)
            if new:
                url, changed = new, True
            parts.append(f"{url} {descriptor}" if descriptor else url)
        return ", ".join(parts) if changed else None

    def attrs(self, tag: str, attrs: str) -> str:
        """A start tag's attributes, with the files they name put in."""
        found: dict[str, re.Match] = {}
        for attr in _ATTR.finditer(attrs):
            # As in a browser, the first of a repeated attribute is the one used.
            found.setdefault(attr.group("name").lower(), attr)
        swaps: list[tuple[re.Match, str]] = []

        def one(name: str, kinds: tuple[str, ...], link: bool = False) -> None:
            attr = found.get(name)
            if attr is not None and attr.group("value"):
                new = self.address(self.folder, html.unescape(_value(attr)), kinds, link)
                if new:
                    swaps.append((attr, new))

        def srcset() -> None:
            attr = found.get("srcset")
            if attr is not None and attr.group("value"):
                new = self.srcset(html.unescape(_value(attr)))
                if new:
                    swaps.append((attr, new))

        before = self.linked
        if tag == "img":
            one("src", PICTURES, link=True)
            srcset()
        elif tag == "source":
            srcset()
        elif tag == "image":
            one("href", PICTURES, link=True)
            one("xlink:href", PICTURES, link=True)
        elif tag == "link":
            rel = found.get("rel")
            words = html.unescape(_value(rel)).lower().split() if rel is not None else []
            if "stylesheet" in words and "alternate" not in words:
                one("href", STYLESHEETS)
        elif tag == "script":
            one("src", SCRIPTS)
        style = found.get("style")
        if style is not None and style.group("value"):
            text = html.unescape(_value(style))
            new = self.css(text, self.folder)
            if new != text:
                swaps.append((style, new))
        if not swaps:
            return attrs
        out, pos = [], 0
        for attr, new in sorted(swaps, key=lambda swap: swap[0].start("value")):
            out.append(attrs[pos: attr.start("value")])
            out.append('"' + new.replace("&", "&amp;").replace('"', "&quot;") + '"')
            pos = attr.end("value")
        out.append(attrs[pos:])
        done = "".join(out)
        if tag == "img" and self.linked > before:
            # A linked picture is fetched when it is near the screen, not all
            # at once before the first draw, unless the page says otherwise.
            # Before a closing slash, so `<img ... />` stays one.
            more = ""
            if "loading" not in found:
                more += ' loading="lazy"'
            if "decoding" not in found:
                more += ' decoding="async"'
            if more:
                bare = done.rstrip()
                if bare.endswith("/"):
                    done = bare[:-1].rstrip() + more + " /"
                else:
                    done = done + more
        return done

    def walk(self, text: str) -> str:
        out: list[str] = []
        pos = 0
        while True:
            found = _TAG.search(text, pos)
            if found is None:
                out.append(text[pos:])
                return "".join(out)
            out.append(text[pos: found.start()])
            pos = found.end()
            name = found.group("name")
            if name is None:
                out.append(found.group(0))
                continue
            name = name.lower()
            out.append(text[found.start(): found.start("attrs")])
            out.append(self.attrs(name, found.group("attrs")))
            out.append(">")
            if name in _RAW_END:
                close = _RAW_END[name].search(text, pos)
                stop = close.start() if close else len(text)
                body = text[pos:stop]
                out.append(self.css(body, self.folder) if name == "style" else body)
                pos = stop


# --------------------------------------------------------------------------
# Where each element is in the file, for a reader who points at one
# --------------------------------------------------------------------------
#
# Petar, 24 September 2026: "for editing, pointing to a section might be a
# better approach. If I point to a headline or a div, it knows exactly which
# HTML element to edit. Who knows, maybe it would make sense that, whatever
# HTML we build, every element needs to have a unique ID."
#
# Not an id written into every page, which would be a rewrite of every page in
# the workspace and a rule every page built later would have to keep. The
# page is marked as it is sent instead: every element that can be pointed at
# carries where its start tag begins in the file (`MARK`), and the page on
# disk is never changed. A reader pointing at a heading hands back that
# number, and the heading's own source is read out of the file at it
# (`element_at`). Nothing about the page has to be unique, and a page built a
# year ago can be pointed at exactly as well as one built today.
#
# Only for a page served to somebody who may change it (`read(mark=True)`):
# nobody else has anything to point with.

#: The attribute each element is marked with.
MARK = "data-rouh-at"

#: What is never marked: nothing in the head is on the screen to point at.
_UNMARKED = frozenset({"html", "head", "meta", "link", "title", "style", "script", "base",
                       "noscript", "template"})

#: Elements with no end tag, whose source is the start tag alone.
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                   "meta", "param", "source", "track", "wbr"})

#: Elements HTML lets a page leave unclosed: one ends where the next of its
#: kind begins.
_OPTIONAL_END = frozenset({"li", "p", "dt", "dd", "tr", "td", "th", "option", "thead",
                           "tbody", "tfoot"})

#: The most of one element's source handed on. A `<main>` is the whole page;
#: past this the start of it and its end are what say where it is.
ELEMENT_MAX = 12_000

_TAG_OR_END = re.compile(
    r"<!--.*?(?:-->|\Z)"
    r"|<(?P<end>/)?(?P<name>[A-Za-z][A-Za-z0-9:-]*)"
    r"(?P<attrs>(?:[^>\"']|\"[^\"]*\"|'[^']*')*)>",
    re.DOTALL)


def with_marks(text: str) -> str:
    """The page's markup with every element that can be pointed at marked
    with where it starts in ``text`` (`MARK`)."""
    out: list[str] = []
    pos = 0
    while True:
        found = _TAG.search(text, pos)
        if found is None:
            out.append(text[pos:])
            return "".join(out)
        name = found.group("name")
        if name is None:
            out.append(text[pos: found.end()])
            pos = found.end()
            continue
        low = name.lower()
        out.append(text[pos: found.start("attrs")])
        if low not in _UNMARKED:
            out.append(f' {MARK}="{found.start()}"')
        out.append(text[found.start("attrs"): found.end()])
        pos = found.end()
        if low in _RAW_END:
            close = _RAW_END[low].search(text, pos)
            stop = close.start() if close else len(text)
            out.append(text[pos:stop])
            pos = stop


def element_at(text: str, at: int, tag: str) -> tuple[str, int] | None:
    """The source of the element whose start tag begins at ``at``, and its line.

    None when what is at ``at`` is not a ``tag`` start tag, which is what a
    page changed since it was marked looks like. The end is found by counting
    the same name in and out, skipping comments and the insides of scripts and
    styles; an element whose end cannot be found is given as far as
    `ELEMENT_MAX` goes, which is still where it is.
    """
    tag = str(tag or "").lower()
    if not re.fullmatch(r"[a-z][a-z0-9:-]*", tag) or not 0 <= at < len(text):
        return None
    first = _TAG_OR_END.match(text, at)
    if first is None or first.group("end") or (first.group("name") or "").lower() != tag:
        return None
    line = text.count("\n", 0, at) + 1
    if tag in _VOID or first.group("attrs").rstrip().endswith("/"):
        return text[at: first.end()], line
    # What has been opened inside it and not yet closed. An end tag for
    # something that is not in here, and is not this element's own, belongs to
    # its parent: the element ended before it, which is how a `<li>` or a `<p>`
    # written without its end tag ends.
    opened: list[str] = []
    pos, limit = first.end(), min(len(text), at + 2_000_000)
    end = None
    while pos < limit:
        found = _TAG_OR_END.search(text, pos, limit)
        if found is None:
            break
        pos = found.end()
        name = (found.group("name") or "").lower()
        if not name:
            continue
        if not found.group("end"):
            if name in _RAW_END:
                close = _RAW_END[name].search(text, pos)
                pos = close.start() if close else limit
                continue
            if name == tag and not opened and tag in _OPTIONAL_END:
                end = found.start()                  # the next one of its kind
                break
            if name not in _VOID and not found.group("attrs").rstrip().endswith("/"):
                opened.append(name)
            continue
        if name in opened:
            while opened and opened.pop() != name:
                pass
            continue
        end = found.end() if name == tag else found.start()
        break
    whole = text[at: end if end is not None else min(len(text), at + ELEMENT_MAX)]
    if len(whole) > ELEMENT_MAX:
        half = ELEMENT_MAX // 2
        whole = whole[:half] + "\n[... the middle of this element is left out here ...]\n" \
            + whole[-half:]
    return whole, line


#: A start tag that ends an element a page may leave open: which ones it ends,
#: and what it does not look past for one. A new `<li>` ends the list item
#: before it, but not one in the list around this list.
_ENDS = {
    "li": ({"li"}, {"ul", "ol", "menu"}),
    "dt": ({"dt", "dd"}, {"dl"}),
    "dd": ({"dt", "dd"}, {"dl"}),
    "td": ({"td", "th"}, {"tr", "table"}),
    "th": ({"td", "th"}, {"tr", "table"}),
    "tr": ({"tr"}, {"table", "thead", "tbody", "tfoot"}),
    "thead": ({"thead", "tbody", "tfoot"}, {"table"}),
    "tbody": ({"thead", "tbody", "tfoot"}, {"table"}),
    "tfoot": ({"thead", "tbody", "tfoot"}, {"table"}),
    "option": ({"option"}, {"select", "datalist", "optgroup"}),
    "optgroup": ({"optgroup", "option"}, {"select"}),
}
#: And the blocks that end a paragraph left open, as a browser ends it.
_ENDS_A_P = frozenset({
    "address", "article", "aside", "blockquote", "details", "dialog", "div", "dl",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5",
    "h6", "header", "hgroup", "hr", "main", "menu", "nav", "ol", "p", "pre", "section",
    "table", "ul"})
_P_SCOPE = frozenset({"applet", "caption", "html", "table", "td", "th", "marquee",
                      "object", "template", "button"})


def element_spans(text: str) -> list[tuple[int, int, str]]:
    """Every element in ``text``, as (where its start tag begins, where it
    ends, its name), in the order they start.

    The same reading of the markup as `element_at`, for the whole page at once:
    comments and the insides of scripts and styles skipped, an element HTML
    lets a page leave open ended where a browser ends it (`_ENDS`,
    `_ENDS_A_P`) or by its parent's end, and an end tag for nothing open
    ignored, as a browser ignores it.
    """
    spans: list[tuple[int, int, str]] = []
    opened: list[tuple[str, int]] = []

    def end_open(kinds, stop, at: int) -> None:
        for n in range(len(opened) - 1, -1, -1):
            name = opened[n][0]
            if name in kinds:
                while len(opened) > n:
                    was, start = opened.pop()
                    spans.append((start, at, was))
                return
            if name in stop:
                return

    pos = 0
    while True:
        found = _TAG_OR_END.search(text, pos)
        if found is None:
            break
        pos = found.end()
        name = (found.group("name") or "").lower()
        if not name:
            continue
        if not found.group("end"):
            if name in _ENDS:
                end_open(*_ENDS[name], found.start())
            if name in _ENDS_A_P:
                end_open({"p"}, _P_SCOPE, found.start())
            if name in _VOID or found.group("attrs").rstrip().endswith("/"):
                spans.append((found.start(), found.end(), name))
                continue
            if name in _RAW_END:
                close = _RAW_END[name].search(text, pos)
                if close is None:
                    end = len(text)
                else:
                    shut = text.find(">", close.start())
                    end = shut + 1 if shut >= 0 else len(text)
                spans.append((found.start(), end, name))
                pos = end
                continue
            opened.append((name, found.start()))
            continue
        if not any(was == name for was, _ in opened):
            continue
        while opened:
            was, start = opened.pop()
            if was == name:
                spans.append((start, found.end(), was))
                break
            spans.append((start, found.start(), was))
    for was, start in opened:
        spans.append((start, len(text), was))
    spans.sort()
    return spans


def enclosing(spans, lo: int, hi: int) -> tuple[int, int, str] | None:
    """The smallest element that holds everything from ``lo`` to ``hi``.

    An element holds a change when its start tag begins before the change
    does - so a change to an attribute is held by the element it is on - and
    it ends where the change ends or after.
    """
    best = None
    for start, end, name in spans:
        if start >= lo:
            break
        if end >= hi and (best is None or end - start < best[1] - best[0]):
            best = (start, end, name)
    return best


def with_files(root, asked: str, page: bytes, pictures=None) -> bytes:
    """The page with every file its markup names put in, as data: addresses.

    ``asked`` is the page's path in the workspace as the route received it, so
    its references are read from that folder, as the browser would read them.
    A page with nothing to put in comes back as the very same bytes.

    ``pictures``, when given, is the address of a picture by its path in the
    workspace (`rouh/picturelinks.py`), and a picture the markup names is
    linked rather than put in.
    """
    text = page.decode("utf-8", "surrogateescape")
    if _BASE.search(text):
        log.info("pages: %s has a <base> address, so its references are left as they are",
                 asked)
        return page
    done = _Inliner(root, str(asked), pictures).walk(text)
    return page if done == text else done.encode("utf-8", "surrogateescape")


def url_for(rel: str) -> str:
    """Rouh's own address for a page in the workspace."""
    return ROUTE + "/".join(quote(part, safe="") for part in str(rel).split("/"))


def frame_block(rel: str, title: str = "") -> dict:
    """The block that puts a page on a card: a tile that opens it on the canvas.

    Named for what it drew until 23 September 2026, the whole page in a frame
    inside the card. It draws a tile now (``frame`` in app.js): a page is only
    ever seen as itself, and the card says what it is and takes you there.
    """
    return {"block": "frame", "href": url_for(rel), "title": title or rel}


def blocks_for(rel: str, title: str = "", review_url: str = "") -> list[dict]:
    """A page's tile, and the same page on the laptop where there is one."""
    blocks = [frame_block(rel, title)]
    if review_url:
        blocks.append({"block": "link", "text": MAC_LINK, "href": review_url + rel})
    return blocks


def title_of(path) -> str:
    """The page's own title, from its <title>, or nothing."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(32768).decode("utf-8", "replace")
    except OSError:
        return ""
    found = _TITLE.search(head)
    if not found:
        return ""
    return " ".join(html.unescape(found.group(1)).split())[:120]


def pages_near(root, asked: str, limit: int = 12) -> list[str]:
    """Pages that do exist in the task a path points into, for when it named none."""
    parts = [p for p in str(asked or "").split("/") if p]
    if len(parts) < 2 or parts[0] not in TOPS:
        return []
    base = Path(root).resolve()
    try:
        folder = resolve(base, f"{parts[0]}/{parts[1]}")
    except Refused:
        return []
    if not folder.is_dir():
        return []
    found: list[str] = []
    for candidate in sorted([*folder.glob("*.html"), *folder.glob("*/*.html")]):
        rel = f"{parts[0]}/{parts[1]}/{candidate.relative_to(folder).as_posix()}"
        try:
            check(base, rel)
        except Refused:
            continue
        found.append(rel)
        if len(found) >= limit:
            break
    return found


#: A step folder's numbers: "30-10.one-system-build" is (30, 10). A folder with
#: one number, "02.parts-manuals", comes before any with two.
_STEP = re.compile(r"^(\d+)(?:[-.](\d+))?(?=[-.])")


def _step_key(name: str) -> tuple[int, int]:
    found = _STEP.match(name)
    if not found:
        return (-1, -1)
    if found.group(2) is None:
        return (0, int(found.group(1)))
    return (int(found.group(1)), int(found.group(2)))
