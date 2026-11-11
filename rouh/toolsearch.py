"""Every tool declared, and none of them loaded until the model asks for it.

Until 26 September 2026 every request carried every tool whole: 78 of them,
each with its name, its description and its full schema, about 35,000 tokens
before a word of the conversation, on every request of every turn. Measured
on a test Rouh that day, that was four fifths of what a plain question sent.

Now each tool is declared but deferred. The model starts a turn with only a
search tool loaded, and a catalogue in the system prompt that names every tool
in one line, grouped by what it is for. When it needs one it searches for it
by name, the tool's definition is loaded where the search happened, at the end
of the conversation so far, and from then on it is called as it always was.

What is in here, and nothing else:

- :class:`Tool`, one tool as the registry declares it, whichever provider is
  asked: its name, the area it belongs to, a one-line brief, and its
  definition. `ToolRegistry.entries()` makes these (`rouh/tools.py`).
- :func:`catalogue`, the block of the system prompt that lists them. It is
  made from the registry on every turn, so a tool added tomorrow is in it
  without anybody writing a line, and it is the same text turn after turn,
  which is what lets it sit in the cached part of the prompt.
- :func:`find`, the search this process runs itself, for any provider whose
  own search is not used. It is the same search whoever asks.
- Two adapters, one per provider, each putting out that provider's own shape
  of the same declaration: :func:`anthropic_tools` for the Messages API, where
  deferred tools carry `defer_loading` and are found with
  `tool_search_tool_regex_20251119` (or the BM25 one, or :data:`CLIENT_SEARCH`,
  which returns `tool_reference` blocks); and :func:`openai_tools` for
  OpenAI's Responses API, where the same flag sits on functions grouped into
  namespaces by area and `{"type": "tool_search"}` does the finding, hosted or
  run here.

Which tools are always loaded is a list in the config (`config.TOOLS_ALWAYS_LOADED`),
empty on purpose until the owner says which ones they use.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

#: How the model finds a tool it needs.
#:
#: - "regex": Anthropic's own search tool, which takes a regular expression
#:   and runs on Anthropic's side inside the same response. The default,
#:   because the catalogue gives the model every tool's exact name, and a
#:   pattern of exact names loads exactly those.
#: - "bm25": Anthropic's other one, which takes words.
#: - "client": the search in this file, run here, the same for every provider.
#: - "off": nothing is deferred and every tool is sent whole, as before.
MODES = ("regex", "bm25", "client", "off")

#: Anthropic's two search tools, by mode. Never deferred themselves: the API
#: refuses a request where every tool is.
ANTHROPIC_SEARCH = {
    "regex": {"type": "tool_search_tool_regex_20251119", "name": "tool_search_tool_regex"},
    "bm25": {"type": "tool_search_tool_bm25_20251119", "name": "tool_search_tool_bm25"},
}

#: The search this process runs itself, when that is the mode.
CLIENT_SEARCH = "find_tools"

#: Every name a search tool goes by, whichever mode sent it.
SEARCH_NAMES = frozenset({CLIENT_SEARCH, *(t["name"] for t in ANTHROPIC_SEARCH.values())})

#: How many tools one search loads unless it asks for more. Anthropic's own
#: search says five, so this one does too.
DEFAULT_LIMIT = 5
MOST = 20

#: The areas the catalogue groups tools into, in the order it lists them: the
#: key (which is also the namespace an OpenAI model sees), the heading, and a
#: line saying what is in it.
#:
#: A key is never a name OpenAI keeps for its own tools. Its API refuses the
#: whole request when a namespace is called `web`, `browser`, `python`,
#: `file_search`, `computer`, `image_gen` or `multi_tool_use` ("Function
#: 'web.look_into' is not allowed in reserved namespace 'web'"), which is what
#: every Luna turn met on 26 September 2026, the day it was first given a key,
#: until the web and live browser areas were renamed. Those seven were found by
#: asking the real API; `rouh/testing/fake_openai.py` refuses them the same way.
AREAS: tuple[tuple[str, str, str], ...] = (
    ("screen", "Cards and the screen",
     "cards on the canvas, the canvas itself and the columns beside it"),
    ("gmail", "Gmail", "the person's connected mailbox, and mail jobs have queued for them"),
    ("calendar", "Calendar", "the person's Google Calendar and the calendars shared with it"),
    ("drive", "Drive and Docs", "files and folders in Google Drive, and Google Docs"),
    ("contacts", "Contacts", "the person's iCloud contacts, the ones on their iPhone"),
    ("research", "Web, YouTube and LinkedIn", "searching and reading the live web, YouTube, "
                                              "people on LinkedIn, and a helper that researches"),
    ("live_browser", "Live browser", "the real browser the person watches and can take over"),
    ("pictures", "Pictures", "drawing new pictures and images, and changing ones in this chat"),
    ("jobs", "Background jobs", "work handed to a worker: starting it, watching it, "
                                "answering it"),
    ("one", "The one program", "runs of Claude Code in the one program"),
    ("tasks", "Tasks, chats and the workspace",
     "numbered tasks, this chat, the workspace and its public pages"),
    ("slack", "Slack", "‹owner›'s Slack workspace: the channels Rouh is in, ‹his› own direct messages, "
                       "and posting as Rouh's bot"),
    ("home", "Home", "‹owner›'s home: Philips Hue rooms, zones, lights and scenes, and the Dreame robot vacuum"),
    ("memory", "Rules, thoughts and Telegram",
     "rules, notes and words kept between conversations, the person's own thoughts, and the person's phone"),
    ("reminders", "Clockwork and goals",
     "reminders and anything done at a time or on a repeat (the Clockwork page), and the "
     "person's goals and their plans"),
    ("heartbeat", "Heartbeat, quests and payments",
     "Rouh's own unprompted turn, the quests it carries, the card vault, shipping options and Stripe"),
    ("self", "Server and self", "this machine, Rouh's own code, its genes, and the Incubator: the one list of "
                                "ideas for new genes and mutations (incubator_list, incubator_read, incubator_add, "
                                "incubator_edit, incubator_status, incubator_merge, incubator_link), and Trials: a made-up "
                                "person trying each change, and the problems they hit (trials)"),
    ("synapse", "Synapse lab", "the Synapse dataset this chat sits beside: storing, editing, deleting, asking, "
                               "tuning and evaluating it"),
    ("other", "Other", "tools not filed under an area above, such as an MCP server's"),
)

AREA_KEYS = tuple(key for key, _, _ in AREAS)

#: Which area each tool is in. A tool not named here is still in the
#: catalogue, under Other, so a new tool is never missing from it; putting it
#: here, or passing `area` where it is declared, is only about which heading
#: it sits under.
AREA_OF: dict[str, str] = {
    # Cards and the screen
    "show_on_screen": "screen", "what_was_on_screen": "screen", "show_again": "screen",
    "read_card": "screen",
    "revise_on_screen": "screen", "set_panels": "screen", "show_canvas": "screen",
    # Gmail
    "read_recent_mail": "gmail", "read_mail": "gmail", "read_mail_attachment": "gmail",
    "mail_alerts": "gmail",
    "send_mail": "gmail", "draft_mail": "gmail", "forward_mail": "gmail",
    "forward_thread": "gmail",
    "modify_mail": "gmail",
    "show_inbox": "gmail", "worker_outbox": "gmail", "to_answer": "gmail", "reply_times": "gmail", "unread_lists": "gmail", "promised_to_you": "gmail", "between_us": "gmail",
    # Calendar
    "list_calendars": "calendar", "list_calendar_events": "calendar",
    "read_calendar_event": "calendar", "create_calendar_event": "calendar",
    "update_calendar_event": "calendar", "delete_calendar_event": "calendar",
    "restore_calendar_event": "calendar",
    "add_shared_calendar": "calendar", "create_calendar": "calendar",
    "share_calendar": "calendar", "meeting_people": "calendar", "block_my_time": "calendar", "when_free": "calendar",
    "read_calendar_link": "calendar", "public_holidays": "calendar", "meeting_hours": "calendar",
    # Drive and Docs
    "search_drive": "drive", "list_drive_folder": "drive", "list_shared_drives": "drive",
    "write_drive_file": "drive", "upload_drive_file": "drive", "create_drive_folder": "drive",
    "manage_drive_file": "drive", "share_drive_file": "drive",
    "create_shared_drive": "drive", "add_shared_drive_members": "drive",
    "list_drive_permissions": "drive", "read_doc": "drive", "doc_changes": "drive", "comments_by": "drive",
    "find_slides": "drive", "edit_sheet": "drive", "edit_slides": "drive", "copy_drive_file": "drive",
    "create_doc": "drive",
    "edit_doc": "drive",
    # Contacts
    "search_contacts": "contacts", "show_contact": "contacts", "no_company": "contacts", "same_contact": "contacts", "contact_card": "contacts",
    "update_contact_profile": "contacts", "save_contact": "contacts",
    "delete_contact": "contacts", "link_person": "contacts",
    # Web, YouTube and LinkedIn
    "web_search": "research", "web_fetch": "research", "youtube_transcript": "research",
    "youtube_search": "research", "look_into": "research", "linkedin_search": "research",
    "linkedin_profile": "research",
    # Live browser
    "browser": "live_browser",
    # Pictures
    "make_picture": "pictures", "change_picture": "pictures",
    # Background jobs
    "assistant_job": "jobs", "delegate_task": "jobs", "check_tasks": "jobs",
    "look_at_task": "jobs", "reply_to_task": "jobs", "read_task_log": "jobs",
    "what_task_changed": "jobs", "tidy_tasks": "jobs", "stop_task": "jobs",
    "what_is_running": "jobs", "answer_conflict": "jobs",
    # The one program
    "one_runs": "one", "one_start": "one", "one_say": "one", "one_stop": "one",
    "one_answer": "one", "one_take": "one", "one_give": "one",
    # Tasks, chats and the workspace
    "make_a_task": "tasks", "move_task": "tasks", "rename_task": "tasks", "move_step": "tasks", "pin": "tasks", "rename_this_chat": "tasks",
    "read_workspace": "tasks", "show_workspace_page": "tasks", "publish_task": "tasks",
    "check_task_sharing": "tasks", "share_with_person": "tasks", "page_asks": "tasks",
    "page_comments": "tasks",
    # Memory and Telegram
    "remember": "memory", "forget": "memory", "list_memory": "memory",
    "agent_instructions": "memory",
    "capture_thought": "memory", "thoughts": "memory", "new_box": "memory", "open_box": "memory",
    "send_telegram": "memory",
    # Slack
    "slack_channels": "slack", "slack_read": "slack", "slack_search": "slack", "slack_join": "slack",
    "slack_send": "slack", "slack_link": "slack",
    # Home
    "hue": "home", "vacuum": "home",
    # Reminders and goals
    "schedule": "reminders", "upcoming": "reminders", "change_scheduled": "reminders",
    "set_goal": "reminders", "plan_goal": "reminders", "goal_step": "reminders",
    "goals": "reminders", "goal_control": "reminders",
    # Server and self
    "run_command": "self", "server_health": "self", "improve_myself": "self",
    "deploy_myself": "self", "show_the_gaps": "self", "code_execution": "self",
    "model_defaults": "self", "update_rouh": "self", "cloudflare": "self", "gene_offer": "self", "gene_draft": "self",
    "incubator_list": "self", "incubator_read": "self", "incubator_add": "self", "incubator_edit": "self",
    "incubator_status": "self", "incubator_merge": "self", "incubator_link": "self", "trials": "self", "incubator_score": "self",
}

#: One-liners for the tools that have no description of their own to take one
#: from: Anthropic's, which run on Anthropic's side and are declared by type.
SERVER_BRIEFS = {
    "web_search": "Search the live web for a few words and read what comes back.",
    "web_fetch": "Read one web page whose address is already in the conversation.",
    "code_execution": "Run code in Anthropic's own sandbox, which has no network.",
}

#: The longest a brief is allowed to be before it is cut.
BRIEF_MAX = 140


def area_of(name: str) -> str:
    return AREA_OF.get(name, "other")


def brief_of(description: str) -> str:
    """One line out of a tool's description: its first sentence, kept short.

    A first sentence longer than a line is cut where its details begin: at
    the last colon, dash or semicolon that still fits, since what follows one
    of those in these descriptions is the list of particulars. Failing that,
    at the last comma that fits, and failing that at the last word.
    """
    text = " ".join(str(description or "").split())
    if not text:
        return ""
    found = re.match(r"(.+?[.!?])(\s|$)", text)
    first = found.group(1) if found else text
    if len(first) <= BRIEF_MAX:
        return first
    at = max(first.rfind(mark, 60, BRIEF_MAX) for mark in (": ", " - ", "; "))
    if at < 0:
        at = first.rfind(", ", 60, BRIEF_MAX)
    if at > 0:
        return first[:at].rstrip(" ,;:-") + "."
    cut = first[:BRIEF_MAX].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "..."


@dataclass(frozen=True)
class Tool:
    """One tool as the registry declares it, whichever provider will be asked."""

    name: str
    area: str
    brief: str
    #: As the Messages API takes it: `name`, `description` and `input_schema`
    #: for one of ours, or a server tool's own `type` and settings.
    definition: dict = field(compare=False)

    @property
    def portable(self) -> bool:
        """Ours, with a schema any provider can take, rather than Anthropic's own."""
        return "input_schema" in self.definition and "type" not in self.definition


def tool_from(definition: dict, *, area: str | None = None, brief: str | None = None) -> Tool:
    name = str(definition.get("name") or "")
    return Tool(
        name=name,
        area=area if area in AREA_KEYS else area_of(name),
        brief=brief or brief_of(definition.get("description") or "")
        or SERVER_BRIEFS.get(name, name.replace("_", " ")),
        definition=definition,
    )


# --- which mode a request goes out in -----------------------------------------

_VERSION = re.compile(r"(sonnet|opus|haiku|fable|mythos)-(\d{1,2})(?:[-.](\d{1,2}))?(?!\d)")


def searches_natively(model: str) -> bool:
    """Whether this model takes deferred tools and a search tool at all.

    Anthropic lists every model from the 4.5 generation on, Haiku 4.5
    included, and nothing before it. Sonnet 5 is missing from that list, and
    was asked on 26 September 2026 and does it. A name that cannot be read is
    taken as one that cannot: the worst of sending every tool whole is a
    dearer request, and the worst of deferring to a model that does not know
    how is a turn that never answers.
    """
    found = _VERSION.search((model or "").lower())
    if not found:
        return False
    major = int(found.group(2))
    minor = int(found.group(3)) if found.group(3) and len(found.group(3)) <= 2 else 0
    return (major, minor) >= (4, 5)


def mode_for(model: str, wanted: str) -> str:
    """The mode a request to this model goes out in, given the one configured."""
    wanted = (wanted or "regex").strip().lower()
    if wanted not in MODES:
        wanted = "regex"
    if wanted == "off" or not searches_natively(model):
        return "off"
    return wanted


def _always(entries, always) -> set[str]:
    names = {t.name for t in entries}
    return {name for name in (always or ()) if name in names}


# --- the catalogue ------------------------------------------------------------

_HOW = {
    "regex": (
        "Only tool_search_tool_regex is loaded when a turn starts{loaded}. Every tool "
        "below is there and waiting, and you load one by searching for it before "
        "you call it. Search with the exact names you need as the pattern, several "
        'at once when the answer needs several: "^(show_on_screen|what_was_on_screen)$". '
        "A search loads at most five unless you give it a limit. A tool you loaded "
        "earlier in this conversation stays loaded, so call it again without "
        "searching; if one you need is not in your tools, search for it. Never tell "
        "the person you cannot do something until you have searched for the tool "
        "that does it."),
    "bm25": (
        "Only tool_search_tool_bm25 is loaded when a turn starts{loaded}. Every tool "
        "below is there and waiting, and you load one by searching for it before "
        "you call it: search with the tool's exact name, or with the words of what "
        "you need done. A search loads at most five unless you give it a limit. A "
        "tool you loaded earlier in this conversation stays loaded; if one you need "
        "is not in your tools, search for it. Never tell the person you cannot do "
        "something until you have searched for the tool that does it."),
    "client": (
        "Only " + CLIENT_SEARCH + " is loaded when a turn starts{loaded}. Every tool "
        "below is there and waiting, and you load one by calling " + CLIENT_SEARCH +
        " with its exact name before you call it, several names at once when the "
        "answer needs several: \"show_on_screen what_was_on_screen\". It loads at "
        "most five unless you give it a limit. A tool you loaded earlier in this "
        "conversation stays loaded; if one you need is not in your tools, load it. "
        "Never tell the person you cannot do something until you have looked for "
        "the tool that does it."),
    "openai": (
        "Only tool_search is loaded when a turn starts{loaded}. Every tool below is "
        "there and waiting, grouped into namespaces named after these headings' "
        "keys, and you load what you need with tool_search before you call it. A "
        "tool you loaded earlier in this conversation stays loaded. Never tell the "
        "person you cannot do something until you have searched for the tool that "
        "does it."),
}


#: Said after how to load a tool, because a search before a call makes a tool
#: look dearer than an answer without it, and it is not: on 26 September 2026,
#: with nothing loaded, a list the rules put on the screen was once said aloud
#: instead.
_STILL = ("Needing a search first is never a reason to do without a tool: everything "
          "these instructions say to do with one still holds.")


def catalogue(entries, *, mode: str, provider: str = "anthropic", always=()) -> str:
    """The system prompt's list of every tool, one line each, grouped by area.

    Nothing in it changes from one turn to the next unless the tools do, and
    that is on purpose: it sits in the cached half of the system prompt, and a
    catalogue that moved every turn would take the cache with it. Empty when
    nothing is deferred, because then every definition is in the request whole
    and a second list of them says nothing.
    """
    entries = list(entries)
    if mode == "off" or not entries:
        return ""
    loaded = sorted(_always(entries, always))
    how = _HOW["openai" if provider == "openai" else mode]
    said = ", along with " + ", ".join(loaded) if loaded else ""
    how = how.format(loaded=said) + " " + _STILL
    if any(t.name == "show_on_screen" for t in entries):
        how += " A list or a table still goes on the screen with show_on_screen."
    lines = ["Your tools:", how]
    by_area: dict[str, list[Tool]] = {}
    for tool in entries:
        by_area.setdefault(tool.area if tool.area in AREA_KEYS else "other", []).append(tool)
    for key, title, _ in AREAS:
        mine = by_area.get(key)
        if not mine:
            continue
        heading = f"{title} ({key}):" if provider == "openai" else f"{title}:"
        lines.append("")
        lines.append(heading)
        for tool in mine:
            lines.append(f"- {tool.name}: {tool.brief}")
    return "\n".join(lines)


# --- the search this process runs itself ----------------------------------------

_WORD = re.compile(r"[a-z0-9]+")
_NAME = re.compile(r"[a-z][a-z0-9_]+")


def _fields(tool: Tool) -> list[str]:
    """Everything a search may match, field by field, as Anthropic's own search
    reads a tool: its name, its description, and each argument's name and
    description."""
    d = tool.definition
    parts = [tool.name, tool.brief, str(d.get("description") or "")]
    props = ((d.get("input_schema") or {}).get("properties") or {})
    for key, value in props.items():
        parts.append(str(key))
        if isinstance(value, dict):
            parts.append(str(value.get("description") or ""))
    return parts


def _haystack(tool: Tool) -> str:
    return "\n".join(_fields(tool))


def find(entries, query, limit=None) -> list[str]:
    """The names of the tools a query asks for, best first.

    Exact names first, in the order they were asked for, because the
    catalogue gives the model every name and a model that knows the name
    should get that tool and not five that mention it. Then, if the query is a
    regular expression, every tool it matches; then the words of the query,
    scored against each tool's name, brief and description.
    """
    entries = [t for t in entries if isinstance(t, Tool)]
    try:
        limit = int(limit) if limit not in (None, "") else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(MOST, limit))
    query = " ".join(str(query or "").split())
    if not query:
        return []
    by_name = {t.name: t for t in entries}
    out: list[str] = []

    def take(name):
        if name not in out:
            out.append(name)

    for name in _NAME.findall(query.lower()):
        if name in by_name:
            take(name)
    # Nothing but names, however they were strung together - "a b",
    # "a, b", "^(a|b)$" - is a request for exactly those and no others.
    rest = _NAME.sub(lambda m: " " if m.group(0) in by_name else m.group(0), query.lower())
    if out and not re.sub(r"[\s,;^$|()]+", "", rest):
        return out[:limit]
    if len(out) < limit and re.search(r"[\^$|()\[\]*+?\\]", query):
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error:
            pattern = None
        if pattern is not None:
            for tool in entries:
                if any(pattern.search(part) for part in _fields(tool)):
                    take(tool.name)
    if len(out) < limit:
        words = [w for w in _WORD.findall(query.lower()) if len(w) > 2]
        scored = []
        for index, tool in enumerate(entries):
            name_words = set(_WORD.findall(tool.name.replace("_", " ")))
            brief_words = set(_WORD.findall(tool.brief.lower()))
            rest = _haystack(tool).lower()
            score = sum(3 * (w in name_words) + 2 * (w in brief_words) + (w in rest)
                        for w in words)
            if score:
                scored.append((-score, index, tool.name))
        for _, _, name in sorted(scored):
            take(name)
    return out[:limit]


# --- Anthropic: the Messages API --------------------------------------------------

def client_search_definition() -> dict:
    """The search tool of :data:`CLIENT_SEARCH` mode, as the Messages API takes it."""
    return {
        "name": CLIENT_SEARCH,
        "description": (
            "Load tools you need before you call them. Give the exact names from the "
            "catalogue in your instructions, several at once, or the words of what you "
            "need done. It answers with the tools it loaded, and from then on they can be "
            "called like any other."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Tool names, or words saying what the tool is for."},
                "limit": {"type": "integer",
                          "description": f"How many to load at most, default {DEFAULT_LIMIT}."},
            },
            "required": ["query"],
        },
    }


def anthropic_tools(entries, *, mode: str, always=()) -> list[dict]:
    """The `tools` of one Messages API request.

    The search tool first, then every tool in the registry's own order, each
    one deferred unless the config says it is always loaded. Deferred tools
    are not part of the cached prefix at all (Anthropic strips them from it),
    so only the search tool and the always-loaded ones decide what is cached,
    and a search that loads one does not move the cache: its definition goes
    in where the search happened, at the end of the conversation.
    """
    entries = list(entries)
    if mode == "off":
        return [dict(t.definition) for t in entries]
    keep = _always(entries, always)
    out = [dict(ANTHROPIC_SEARCH[mode]) if mode in ANTHROPIC_SEARCH
           else client_search_definition()]
    for tool in entries:
        definition = dict(tool.definition)
        if tool.name not in keep:
            definition["defer_loading"] = True
        out.append(definition)
    return out


def anthropic_search_result(names) -> list[dict]:
    """What :data:`CLIENT_SEARCH` answers, as a tool_result's content.

    `tool_reference` blocks, which the API turns into the tools' definitions
    in place. A search that found nothing says so in words, since a result
    with nothing in it at all is refused.
    """
    found = [{"type": "tool_reference", "tool_name": name} for name in names]
    return found or [{"type": "text", "text": (
        "No tool matched that. Every tool is in the catalogue in your instructions, "
        "by its exact name.")}]


def declared_names(tools: list[dict]) -> set[str]:
    return {str(t.get("name")) for t in tools if isinstance(t, dict) and t.get("name")}


def clean_references(messages: list, declared: set[str]) -> list:
    """The window with every reference to a tool this request does not declare taken out.

    A search result in the history names the tools it loaded, and the API
    turns each name back into that tool's definition on every later request.
    A name that is not among this request's tools is refused outright - "Tool
    reference 'x' not found in available tools" - and refused on every turn
    after it, so a tool that went away (an MCP server that did not start, a
    turn about somebody's email that may use only a few) would kill the chat.

    Only what came back from the database is looked at: the blocks this turn
    added itself are the SDK's objects, and they only name tools this very
    turn declared. The list is rebuilt, never edited in place, because the
    caller's copy is the one that goes in the database.
    """
    out = []
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            out.append(message)
            continue
        changed = False
        blocks = []
        for block in content:
            fixed = _cleaned(block, declared)
            changed = changed or fixed is not block
            blocks.append(fixed)
        out.append(dict(message, content=blocks) if changed else message)
    return out


def _cleaned(block, declared: set[str]):
    if not isinstance(block, dict):
        return block
    kind = block.get("type")
    if kind == "tool_search_tool_result":
        body = block.get("content")
        refs = body.get("tool_references") if isinstance(body, dict) else None
        if isinstance(refs, list):
            kept = [r for r in refs
                    if not isinstance(r, dict) or r.get("tool_name") in declared]
            if len(kept) != len(refs):
                return dict(block, content=dict(body, tool_references=kept))
        return block
    if kind == "tool_result" and isinstance(block.get("content"), list):
        body = block["content"]
        kept = [b for b in body if not (isinstance(b, dict) and b.get("type") == "tool_reference"
                                        and b.get("tool_name") not in declared)]
        if len(kept) != len(body):
            if not kept:
                kept = [{"type": "text", "text": "Those tools are not available any more."}]
            return dict(block, content=kept)
    return block


def loaded_by(block) -> list[str]:
    """The tools a search result loaded, whichever search it was."""
    data = block.model_dump() if hasattr(block, "model_dump") else block
    if not isinstance(data, dict):
        return []
    body = data.get("content")
    if data.get("type") == "tool_search_tool_result" and isinstance(body, dict):
        return [str(r.get("tool_name")) for r in body.get("tool_references") or []
                if isinstance(r, dict) and r.get("tool_name")]
    if isinstance(body, list):
        return [str(b.get("tool_name")) for b in body
                if isinstance(b, dict) and b.get("type") == "tool_reference"]
    return []


# --- OpenAI: the Responses API ----------------------------------------------------

#: Anthropic's own tools that OpenAI has one of its own for. Hosted tools are
#: always loaded there: deferring is for functions, namespaces and MCP servers.
OPENAI_HOSTED = {"web_search": {"type": "web_search"}}


def _openai_function(tool: Tool, deferred: bool) -> dict:
    d = tool.definition
    out = {
        "type": "function",
        "name": tool.name,
        "description": str(d.get("description") or tool.brief),
        "parameters": d.get("input_schema") or {"type": "object", "properties": {}},
        # Strict is the Responses API's default and wants every property
        # required and no others allowed, which Rouh's schemas were never
        # written for. Said outright so the default cannot change under them.
        "strict": False,
    }
    if deferred:
        out["defer_loading"] = True
    return out


def openai_client_search() -> dict:
    """The Responses API's tool search, run here rather than by OpenAI."""
    return {
        "type": "tool_search",
        "execution": "client",
        "description": ("Load tools you need before you call them, by their exact names from "
                        "the catalogue in your instructions or by what you need done."),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string",
                          "description": "Tool names, or words saying what the tool is for."},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }


def openai_tools(entries, *, mode: str, always=()) -> list[dict]:
    """The `tools` of one Responses API request.

    Rouh's own tools become functions, grouped into one namespace per area,
    which is the shape OpenAI says its models search best, each deferred
    unless the config says it is always loaded. Anthropic's server tools have
    no function to become: web search becomes OpenAI's own hosted one, and the
    rest (web fetch, code execution) are left out, because nothing on OpenAI's
    side takes them.
    """
    entries = list(entries)
    keep = _always(entries, always)
    ours = [t for t in entries if t.portable]
    hosted = [dict(OPENAI_HOSTED[t.name]) for t in entries
              if not t.portable and t.name in OPENAI_HOSTED]
    if mode == "off":
        return [_openai_function(t, False) for t in ours] + hosted
    out = []
    for key, title, what in AREAS:
        mine = [t for t in ours if (t.area if t.area in AREA_KEYS else "other") == key]
        if not mine:
            continue
        out.append({
            "type": "namespace",
            "name": key,
            "description": f"{title}: {what}.",
            "tools": [_openai_function(t, t.name not in keep) for t in mine],
        })
    out += hosted
    out.append(openai_client_search() if mode == "client" else {"type": "tool_search"})
    return out


def openai_search_output(call_id: str, names, entries) -> dict:
    """What a client-run `tool_search_call` is answered with: the tools it loaded.

    In their namespaces, as they were declared, with only the ones found in
    each, so what the model is handed is exactly what the request declared.
    """
    wanted = set(names)
    loaded = []
    for key, title, what in AREAS:
        mine = [t for t in entries if t.portable and t.name in wanted
                and (t.area if t.area in AREA_KEYS else "other") == key]
        if mine:
            loaded.append({"type": "namespace", "name": key,
                           "description": f"{title}: {what}.",
                           "tools": [_openai_function(t, True) for t in mine]})
    return {"type": "tool_search_output", "execution": "client", "call_id": call_id,
            "status": "completed", "tools": loaded}


def said_loaded(names) -> str:
    """A search's outcome as the line on the screen says it."""
    names = [n for n in names if n]
    if not names:
        return "no tool matched"
    return "loaded " + ", ".join(names)


def query_of(args) -> str:
    """What a search was asked, whichever of the three searches it was."""
    if not isinstance(args, dict):
        try:
            args = json.loads(args)
        except (TypeError, ValueError):
            return ""
    return str(args.get("pattern") or args.get("query") or "")


@dataclass
class Plan:
    """What one request declares: the tools, in whichever mode, and the catalogue."""

    mode: str
    tools: list
    catalogue: str
    declared: set = field(default_factory=set)


def anthropic_plan(entries, *, model: str, wanted: str, always=()) -> Plan:
    """The tools and the catalogue of a Messages API request to this model."""
    entries = list(entries)
    mode = mode_for(model, wanted)
    tools = anthropic_tools(entries, mode=mode, always=always)
    return Plan(mode=mode, tools=tools, declared=declared_names(tools),
                catalogue=catalogue(entries, mode=mode, always=always))
