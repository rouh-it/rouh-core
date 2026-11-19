"""Which side of Chat Options each tool is on: Rouh Tools or LLM Tools, and a few words for each.

Petar, 18 November 2026: "the tools should be split in 2 toggles. Rouh Tools, LLM Tools. Each should have a
line with a few listed ellipsis plus (?) for showing a hover tooltip with the list of all tools and few words
explanation. not long sentences."

- **Rouh Tools** (`ROUH`) are Rouh's own: mail, calendar, Drive, contacts, tasks and the workspace, the screen
  and its cards, jobs, Synapse, the home, Slack, the server, and any MCP server's tools.
- **LLM Tools** (`LLM`) are what a model brings with it, or what any plain chat with a model has: searching
  and reading the web, running code in the provider's sandbox, and drawing pictures.

The one place a tool is put on a side is here. Every area of the catalogue (`toolsearch.AREAS`) has its side in
`AREA_SIDE`, which refuses to load without one for each area, so a new area is put on a side when it is made;
a tool takes its area's side unless `LLM_TOOLS` names it. The search tools a deferred catalogue is found by
(`toolsearch.SEARCH_NAMES`) are on neither: they come with whichever side is on.

`side_of` is asked by `brain.Brain.tool_entries` (a side that is off is not declared to the model at all) and by
`tools.ToolRegistry.call` (a tool of a side that is off is refused); `listing` is what the panel's tooltips say.
"""
from __future__ import annotations

from . import toolsearch

ROUH, LLM = "rouh", "llm"

#: Each side as Chat Options names it.
NAMES = {ROUH: "Rouh Tools", LLM: "LLM Tools"}

#: Every area of the catalogue, on its side.
AREA_SIDE: dict[str, str] = {
    "screen": ROUH, "gmail": ROUH, "calendar": ROUH, "drive": ROUH, "contacts": ROUH, "research": ROUH,
    "live_browser": ROUH, "pictures": LLM, "jobs": ROUH, "one": ROUH, "tasks": ROUH, "slack": ROUH,
    "home": ROUH, "memory": ROUH, "reminders": ROUH, "heartbeat": ROUH, "self": ROUH, "synapse": ROUH,
    "other": ROUH,
}
_missing = set(toolsearch.AREA_KEYS) ^ set(AREA_SIDE)
if _missing:   # a new area of the catalogue is put on a side here when it is made
    raise RuntimeError(f"toolsides.AREA_SIDE does not match toolsearch.AREAS: {sorted(_missing)}")

#: The model's own tools, whatever area the catalogue lists them under: Anthropic's and OpenAI's web search
#: and web fetch, the provider's code sandbox, and pictures.
LLM_TOOLS = frozenset({"web_search", "web_fetch", "code_execution", "make_picture", "change_picture"})


def side_of(name: str, area: str | None = None) -> str:
    """"rouh" or "llm" for a tool, or "" for a search tool, which goes with whichever side is on."""
    if name in toolsearch.SEARCH_NAMES or name.startswith("tool_search_tool"):
        return ""
    if name in LLM_TOOLS:
        return LLM
    return AREA_SIDE.get(area or toolsearch.area_of(name), ROUH)


def keep(name: str, area: str | None, reads: dict) -> bool:
    """Whether a turn with these switches (`reading.switches`) may be offered this tool."""
    side = side_of(name, area)
    if not side:
        return bool(reads.get("rouh_tools", True)) or bool(reads.get("llm_tools", True))
    return bool(reads.get(side + "_tools", True))


#: A few words for each tool, for the tooltip: what it does, never a sentence. A tool not here is said by
#: the first words of its own description (`words`).
WORDS: dict[str, str] = {
    # LLM Tools
    "web_search": "searches the web", "web_fetch": "reads a web page", "code_execution": "runs code in a sandbox",
    "make_picture": "draws a picture", "change_picture": "edits a picture",
    # Cards and the screen
    "show_on_screen": "draws a card", "what_was_on_screen": "reads what was shown", "show_again": "shows a card again",
    "read_card": "reads a card", "recall_result": "gets an earlier result back", "revise_on_screen": "changes a card",
    "set_panels": "opens or closes panels", "show_canvas": "shows the canvas", "ask_for_location": "asks where you are",
    "actions": "buttons on a card",
    # Gmail
    "read_recent_mail": "lists recent mail", "read_mail": "reads an email", "read_mail_attachment": "reads an attachment",
    "mail_alerts": "new-mail alerts", "send_mail": "sends an email", "draft_mail": "drafts an email",
    "forward_mail": "forwards an email", "forward_thread": "forwards a thread", "modify_mail": "archives, labels, deletes",
    "show_inbox": "shows the inbox", "worker_outbox": "a job's mail to you", "to_answer": "mail waiting on you",
    "reply_times": "how fast people reply", "unread_lists": "unread newsletters", "promised_to_you": "what was promised",
    "between_us": "mail with one person", "handle_email_again": "handles an email again",
    # Calendar
    "list_calendars": "lists calendars", "list_calendar_events": "lists events", "read_calendar_event": "reads an event",
    "create_calendar_event": "adds an event", "update_calendar_event": "changes an event",
    "delete_calendar_event": "deletes an event", "restore_calendar_event": "brings an event back",
    "add_shared_calendar": "adds a shared calendar", "create_calendar": "makes a calendar",
    "share_calendar": "shares a calendar", "meeting_people": "who is in a meeting", "block_my_time": "blocks time",
    "when_free": "finds free time", "read_calendar_link": "reads a calendar link", "public_holidays": "public holidays",
    "meeting_hours": "hours spent in meetings",
    # Drive and Docs
    "search_drive": "searches Drive", "list_drive_folder": "lists a folder", "list_shared_drives": "lists shared drives",
    "write_drive_file": "writes a file", "upload_drive_file": "uploads a file", "create_drive_folder": "makes a folder",
    "manage_drive_file": "moves, renames, deletes", "share_drive_file": "shares a file",
    "create_shared_drive": "makes a shared drive", "add_shared_drive_members": "adds people to a drive",
    "list_drive_permissions": "who can open it", "open_files": "files open in a chat", "take_off_files": "closes files",
    "read_doc": "reads a document", "doc_changes": "what changed in a doc", "comments_by": "comments by a person",
    "find_slides": "finds slides", "edit_sheet": "edits a sheet", "edit_slides": "edits slides",
    "copy_drive_file": "copies a file", "create_doc": "makes a document", "edit_doc": "edits a document",
    "reply_to_doc_comment": "answers a doc comment", "print_page": "prints a page to PDF",
    # Contacts
    "search_contacts": "finds a contact", "show_contact": "shows a contact", "no_company": "contacts with no company",
    "same_contact": "merges duplicates", "contact_card": "a contact's card", "contact_changes": "what changed",
    "contact_relationships": "family and colleagues", "update_contact_profile": "updates a profile",
    "save_contact": "saves a contact", "save_pet": "saves a pet", "delete_contact": "deletes a contact",
    "link_person": "links a person",
    # Web, YouTube and LinkedIn (Rouh's own)
    "youtube_transcript": "reads a video's words", "youtube_search": "searches YouTube",
    "look_into": "researches a question", "linkedin_search": "searches LinkedIn", "linkedin_profile": "reads a profile",
    # Live browser
    "browser": "drives the live browser",
    # Background jobs
    "assistant_job": "starts a job", "delegate_task": "hands work to a job", "check_tasks": "lists jobs",
    "look_at_task": "looks at a job", "reply_to_task": "answers a job", "read_task_log": "reads a job's log",
    "what_task_changed": "what a job changed", "tidy_tasks": "tidies jobs", "stop_task": "stops a job",
    "what_is_running": "what is running", "answer_conflict": "settles a clash", "long_work": "long work",
    # The one program
    "one_runs": "lists runs", "one_start": "starts a run", "one_say": "talks to a run", "one_stop": "stops a run",
    "one_answer": "answers a run", "one_take": "takes over a run", "one_give": "hands a run back",
    # Tasks, chats and the workspace
    "make_a_task": "makes a task", "move_task": "moves a task", "rename_task": "renames a task",
    "move_step": "moves a subtask", "pin": "pins a chat", "rename_this_chat": "renames the chat",
    "read_workspace": "reads the workspace", "show_workspace_page": "opens a page", "edit_page": "edits a page",
    "publish_task": "makes a page public", "check_task_sharing": "who sees a task",
    "share_with_person": "shares a task", "page_asks": "questions on a page", "page_comments": "comments on a page",
    "shared_task": "a task shared with you", "read_granted_tasks": "tasks you were given",
    "share_granted_page": "shares a given page", "decisions": "what waits on you",
    # Memory and Telegram
    "remember": "remembers a fact", "forget": "forgets a fact", "list_memory": "lists what it knows",
    "agent_instructions": "rules for jobs", "capture_thought": "keeps a thought", "thoughts": "your thoughts",
    "new_box": "makes a box", "open_box": "opens a box", "send_telegram": "texts your phone",
    "remember_for_contact": "remembers for a contact",
    # Slack
    "slack_channels": "lists channels", "slack_read": "reads Slack", "slack_search": "searches Slack",
    "slack_join": "joins a channel", "slack_send": "posts to Slack", "slack_link": "links Slack",
    # Home
    "hue": "the lights", "vacuum": "the robot vacuum",
    # Reminders and goals
    "schedule": "reminders and repeats", "upcoming": "what is coming", "change_scheduled": "changes a reminder",
    "set_goal": "sets a goal", "plan_goal": "plans a goal", "goal_step": "a goal's step", "goals": "your goals",
    "goal_control": "pauses or ends a goal", "clockwork_for_contact": "reminders for a contact",
    # Heartbeat, quests and payments
    "heartbeat": "Rouh's own turn", "heartbeat_ask": "asks you later", "heartbeat_brief": "the heartbeat's brief",
    "heartbeat_end": "ends a heartbeat", "heartbeat_ledger": "what it noted", "heartbeat_next": "the next heartbeat",
    "heartbeat_thread": "a heartbeat thread", "heartbeat_record": "a subject's record",
    "heartbeat_reported": "marks a run reported", "quest": "a quest", "payments": "the card vault",
    "shipping": "shipping options", "stripe": "Stripe",
    # Delegation
    "delegate": "a contact's authority", "delegate_act": "acts for a contact", "read_capability": "what a contact may do",
    # Server and self
    "run_command": "runs a command", "server_health": "server health", "improve_myself": "changes Rouh's code",
    "read_rouh_log": "reads Rouh's log", "connection_status": "connection status",
    "deploy_myself": "deploys Rouh", "show_the_gaps": "what Rouh cannot do", "model_defaults": "which model answers",
    "mcp_servers": "MCP servers", "update_rouh": "updates Rouh", "cloudflare": "Cloudflare",
    "gene_offer": "offers a gene", "gene_draft": "drafts a gene", "incubator_list": "lists ideas",
    "incubator_read": "reads an idea", "incubator_add": "adds an idea", "incubator_edit": "edits an idea",
    "incubator_status": "an idea's status", "incubator_merge": "merges ideas", "incubator_link": "links ideas",
    "incubator_score": "scores an idea", "trials": "tester trials",
    # Synapse
    "synapse_find": "finds in memory", "synapse_query": "asks memory", "synapse_add": "adds to memory",
    "synapse_edit": "edits memory", "synapse_delete": "deletes from memory", "synapse_dream": "memory's nightly pass",
    "synapse_eval": "tests a dataset", "synapse_generate": "makes test data", "synapse_improvements": "tries to improve memory",
    "synapse_learn": "learns from use", "synapse_settings": "memory's settings", "synapse_trace": "reads a past look-up",
    "synapse_why": "why an item came up",
    # Others
    "case_report": "reports a wrong answer", "comment_on_doc": "comments on a doc", "find_for_them": "finds for a contact",
    "meeting_read": "reads a meeting", "meeting_search": "finds meetings", "read_rouh_link": "reads a Rouh link",
}


def words(name: str, brief: str = "") -> str:
    """A tool's few words: its own in `WORDS`, else the first words of its description, lower case."""
    if name in WORDS:
        return WORDS[name]
    got = " ".join(str(brief or "").replace(".", " ").split()[:4]).strip()
    if not got:
        return name.replace("_", " ")
    return got[0].lower() + got[1:]


def listing(entries) -> dict[str, list[dict]]:
    """{"rouh": [...], "llm": [...]}: every tool this Rouh has, by side, each as {"name", "words"}, by name."""
    out: dict[str, list[dict]] = {ROUH: [], LLM: []}
    seen: set[str] = set()
    for t in entries or ():
        name = str(getattr(t, "name", "") or "")
        side = side_of(name, getattr(t, "area", None))
        if not side or name in seen:
            continue
        seen.add(name)
        out[side].append({"name": name, "words": words(name, getattr(t, "brief", ""))})
    for side in out:
        out[side].sort(key=lambda x: x["name"])
    return out
