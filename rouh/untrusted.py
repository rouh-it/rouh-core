"""Third-party text, marked as third-party text.

A web page, an email, a document somebody else wrote: all of it arrives as a
tool result and lands in the window looking exactly like something the person
said. There is nothing in the shape of the conversation that tells the model
the difference between "book the flight" typed by the owner of this assistant
and "book the flight" written into a signature block by a stranger.

So anything fetched from outside is wrapped here before it reaches the window:

    <untrusted-content-a1b2c3d4 source="an email, from bob@example.com">
    ...whatever it said...
    </untrusted-content-a1b2c3d4>

and the system prompt carries the standing rule about what that means. Two
halves of one thing: the marks are worthless without the rule, and the rule is
worthless without the marks.

The tag carries a nonce, drawn fresh for every wrap. Without it, a page that
simply contains the closing tag ends its own quotation and everything after it
reads as the assistant's own context again, which is the whole attack in one
line. The nonce is not in the page, is not guessable, and is different every
time, so no text can close a box it is inside.

The nonce is the whole of that defence, and nothing rewrites the body. An
earlier version here also defused anything that looked like a closing tag, and
that was worse than useless: it cannot help, because the nonce has already made
the close unforgeable, and it means the model and the person are both shown
something other than what the file said. Quoted material is quoted exactly or
it is not quoted.

What is wrapped is decided in one place, `SOURCES`, and it is an allow list of
tools rather than a rule about content. A tool that starts returning somebody
else's words is a one-line change here, and a tool nobody has thought about is
not quietly trusted: it is simply not marked, which is what it was before.

The one exception goes the other way. A listed tool still says things in its
own voice: "that path is outside the workspace", "there is no Google account
connected yet". Boxing those as a quoted file would be a lie about who said
them, and it teaches the model to distrust its own tooling, so a handler wraps
them in `ours` and they come through untouched. The default is still to box,
so forgetting is safe and only the exception has to be said out loud.
"""
from __future__ import annotations

import re
import secrets

#: Which tool results are somebody else's words, and how to say whose.
#:
#: The value is the phrase that goes in `source`, and it is written to be read
#: out loud: the model repeats it when it reports that a fetched page tried to
#: give it an instruction.
SOURCES = {
    "read_mail": "an email, written by whoever sent it",
    "read_mail_attachment": "a file attached to an email, written by whoever sent it",
    # A calendar published at a link (`rouh/calendar_link.py`).
    "read_calendar_link": "a calendar published at a link, written by whoever publishes it",
    "read_recent_mail": "the inbox, written by whoever sent each message",
    # The inbox card's list, in a box of its own inside Rouh's own words about
    # the card (`tools._show_inbox`).
    "show_inbox": "the inbox, written by whoever sent each message",
    # What became of new mail. Rouh's own account of it, with the senders and
    # subjects boxed by the tool itself (`MailAlerts.report`).
    "mail_alerts": "the senders and subjects of new mail, written by whoever sent it",
    "read_doc": "a document, written by whoever wrote it",
    "comments_by": "comments on documents, written by whoever left each comment",
    "page_asks": "requests made to Ask AI on the person's pages, written by whoever asked",
    # What the tool did is its own words (`untrusted.ours`); a reading is boxed.
    "page_comments": "comments people pinned to one of the person's pages, written by whoever left each",
    "find_slides": "slides of decks in Drive, written by whoever wrote them",
    "edit_sheet": "what a Google Sheet held before it was written, written by whoever wrote it",
    "edit_slides": "what a Google Slides deck said before it was changed, written by whoever wrote it",
    "read_workspace": "a file from the workspace, which may quote anything",
    "search_drive": "file names and owners from Drive, written by whoever made them",
    "list_drive_folder": "file names and owners from Drive, written by whoever made them",
    "list_shared_drives": "shared drive names, written by whoever made them",
    "list_drive_permissions": "names and addresses of people a file is shared with",
    "list_calendars": "calendar names, written by whoever made each calendar",
    "list_calendar_events": ("calendar events, each titled and placed by whoever made "
                             "or sent the invitation"),
    "read_calendar_event": ("a calendar event, its title, place, guests and description "
                            "written by whoever made or sent the invitation"),
    "search_contacts": ("the person's iCloud contacts, whose names and notes may have "
                        "been written by anybody"),
    # A contact whole, with the research about them, which came off the web.
    "show_contact": ("a contact card, which anybody could have written, and research "
                     "about them gathered from the web"),
    "youtube_transcript": ("a YouTube video, its title, description and the words "
                           "spoken in it, written by whoever made it"),
    "youtube_search": ("YouTube search results, with each video's title and "
                       "description written by whoever made it"),
    # People on LinkedIn, and one person's whole profile and posts, which are
    # theirs only where labelled so: a repost is the original author's words
    # (`rouh/linkedin.py`, `relation`). Each tool boxes these itself inside
    # Rouh's own words about the card it drew.
    "linkedin_search": ("LinkedIn search results, each person's name, headline and "
                        "location written by that person"),
    "linkedin_profile": ("a LinkedIn profile written by the person it belongs to and "
                         "by whoever recommended them, and posts each labelled with "
                         "whose words they are: their own, or somebody else's that "
                         "they reposted, commented on or reacted to"),
    # A meeting's guests, with what their public LinkedIn profiles said when Rouh looked them up
    # ahead of the meeting (`rouh/meeting_people.py`). Boxed by the tool itself, inside Rouh's own
    # words about the card it drew.
    "meeting_people": ("a meeting's guests as the invitation names them, and what each one's "
                       "public LinkedIn profile says, written by that person"),
    # The page in the Live browser, as the outline Rouh acts on, with its
    # title and address (`rouh/browsing.py`). What the tool says in its own
    # voice - a refusal, a hand-over - is marked `ours` there.
    "browser": "a web page open in your browser, written by whoever made the page",
    # A page web_fetch could not read, read again in a headless browser of
    # its own (`rouh/fetchfallback.py`). Boxed there, inside Rouh's own words
    # saying why it was read that way.
    "browser_fetch": "a web page read in a browser, written by whoever made the page",
    # One of Rouh's own pages, read inside Rouh as the person (`rouh/rouhlinks.py`).
    # Boxed there, by kind of page, inside Rouh's own line saying what was read.
    "read_rouh_link": ("a page of Rouh's own, which may quote emails, messages, pages and "
                       "files written by others"),
    # A note a background job queued for the person to be emailed. The job may
    # have read anything before it wrote it, so each note's body is boxed by
    # the tool itself (`outbox.describe`) and the rest is Rouh's own words.
    "worker_outbox": "a note a background job wrote, which may quote anything it read",
    # Slack (`rouh/slack.py`): the messages Rouh's app keeps, and the names and topics of the
    # conversations, written by whoever is in the workspace. Each tool boxes them itself, inside
    # Rouh's own words about them.
    "slack_channels": "Slack conversation names and topics, written by whoever made them",
    "slack_read": "Slack messages, each written by the person it names",
    "slack_search": "Slack messages, each written by the person it names",
    # A Slack case's reading of the owner's meetings, tasks and files (`rouh/slack_team.py`), boxed
    # by the tool itself.
    "find_for_them": "‹owner›'s meetings, tasks and files, which quote whoever wrote or said them",
}

#: The standing rule, for the system prompt. Only worth sending when something
#: in the request can actually produce a marked box.
# The standing rule about text that is not from the person is the rule "untrusted" on the Rules page, which a
# new Rouh starts with (`rouh/rule_defaults_fallback.json`), told whenever `rule_needed` says a tool of the turn
# can bring a box in. Until 21 October 2026 it was `RULE`, here. Whether it is on or off, what is boxed is boxed:
# the marks are this module's, and no rule turns them off.

#: What a box looks like, for finding one and for reading inside it.
_BOX = re.compile(
    r"<untrusted-content-([0-9a-f]{8}) source=\"(.*?)\">\n(.*)\n</untrusted-content-\1>",
    re.DOTALL)

class Ours(str):
    """A string Rouh said itself, inside a tool that usually quotes others.

    A `str` subclass rather than a wrapper object on purpose: every caller
    between the handler and the window treats it as the string it is, so
    marking one return can never change anything but whether it is boxed.
    """

    __slots__ = ()


def ours(text) -> Ours:
    """Mark a tool's answer as Rouh's own words, not the ones it fetched."""
    return text if isinstance(text, Ours) else Ours(text)


def rule_needed(names) -> bool:
    """Whether any tool in this request can produce a marked box."""
    return any(source_for(name) for name in (names or ()))


def wrap(body, source: str) -> str:
    """Put somebody else's words in a box of their own.

    Anything that is not already text is turned into text first, because a tool
    that hands back a structure still hands back somebody else's strings inside
    it, and a box round part of a result is not a box.
    """
    if not isinstance(body, str):
        import json

        try:
            body = json.dumps(body, ensure_ascii=False)
        except (TypeError, ValueError):
            body = str(body)
    if not body.strip():
        return body
    nonce = secrets.token_hex(4)
    return (f'<untrusted-content-{nonce} source="{_said(source)}">\n'
            f"{body}\n"
            f"</untrusted-content-{nonce}>")


#: What an MCP server returns is somebody else's words too, and the whole
#: namespace counts (`rouh/mcp.py`). It is a program somebody else wrote,
#: usually talking to a service somebody else runs, so its answer is quoted
#: material exactly as a web page is. Matched by prefix rather than listed,
#: because the names are not known until the servers are opened.
MCP_PREFIX = "mcp__"
MCP_SOURCE = "an MCP server, {server}, which is not this machine"


def source_for(name: str) -> str:
    """Whose words a tool's answer is, or nothing if it is Rouh's own."""
    if name in SOURCES:
        return SOURCES[name]
    if str(name or "").startswith(MCP_PREFIX):
        server = str(name)[len(MCP_PREFIX):].split("__", 1)[0] or "unnamed"
        return MCP_SOURCE.format(server=server)
    return ""


class Blocks(list):
    """A tool's result that carries a file to be shown, not only words: its blocks.

    Words in it are already boxed by the handler that made it, and its files are
    attachment markers (`attachments.marker`), stored as markers and turned into
    the file itself only on the request (`attachments.hydrate`), the way a file
    the person attached is. `said` is the words alone, for a person's screen and
    for any caller that can only take words (Pictures in mail seen, night 19,
    `rouh/mail_pictures.py`).
    """

    def __init__(self, blocks, said: str = ""):
        super().__init__(blocks)
        self.said = said

    def __str__(self) -> str:
        return self.said


def wrap_for(name: str, body):
    """Wrap a tool's result if that tool returns somebody else's words.

    Anything the handler marked with `ours` comes through as it was: it is
    this machine saying it cannot do something, not a file saying anything.
    A result with files in it (`Blocks`) was boxed where it was made.
    """
    if isinstance(body, Ours):
        return str(body)
    if isinstance(body, Blocks):
        return body
    source = source_for(name)
    return wrap(body, source) if source else body


def inner(body):
    """What is inside the box, for anything that has to show it to a person.

    The chip under a tool call on screen and the summary on the orb are for the
    person, and a marker in place of the first line of an email tells them
    nothing. The model is the one that needs the marks, and the model still
    has them.
    """
    if isinstance(body, Blocks):
        body = body.said
    if not isinstance(body, str):
        return body
    found = _BOX.search(body)
    return found.group(3) if found else body


def source_of(body) -> str:
    """Whose words a box says these are, or nothing if it is not a box."""
    if not isinstance(body, str):
        return ""
    found = _BOX.search(body)
    return found.group(2) if found else ""


def is_wrapped(body) -> bool:
    return bool(isinstance(body, str) and _BOX.search(body))


def _said(source: str) -> str:
    """The source phrase, safe to put inside the quotes of the opening line."""
    return " ".join(str(source or "somewhere else").split()).replace('"', "'")[:120]
