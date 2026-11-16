"""A rule about one kind of tool is told with that tool, not in every turn.

Petar, 15 November 2026, in the chat "Chat Change Planning": tool-specific instructions - calendar rules, mail
rules, purchase and checkout rules, browser rules, Slack, contacts - "load with the tool when it is loaded, not in
every turn's system prompt", his own rules about one tool included, and "rules split. you pick."

Every tool is declared and deferred (`rouh/toolsearch.py`): a turn starts with a catalogue of one line per tool,
and a tool's definition reaches the model only when the model searches for it. So that definition is where a
rule about the tool goes. A rule whose `when` says `with` - a list of the catalogue's areas (`toolsearch.AREAS`,
"calendar", "gmail") or of tools by name - is left out of the system prompt of a chat (`rules.placed`,
`rules.prompt_parts`), and its words are put at the end of the description of every tool it names
(`attach`), so they arrive in the turn at the moment the tool does and cost nothing in a turn that never uses it.

What stays in every turn is what is needed before any tool is touched: who Rouh is and who the person is, every
rule about permission, privacy and safety, plain words, the rule that Rouh never signs the person's name, and
the rules that say which tool to reach for at all (where work goes, research comes back as a task). Those are
never given a `with`. Nothing here changes what a rule says, who may change it, or where else it is told: agents
are told a rule with `with` exactly as before (`rules.reach` does not read it), and the Rules page says where it
is told in its "Conditions:" lines (`rules.condition_lines`). The report of which rule went where is step 62 of
the workspace's task on Rouh's chats.

When the model is asked with every tool whole (`toolsearch` mode "off"), every description is sent, so a rule
told with its tool is still told every turn there; nothing is lost, it is only not saved.
"""
from __future__ import annotations

import dataclasses
import logging

from . import toolsearch

log = logging.getLogger("rouh.tool_rules")

#: The key of a rule's `when` that says which tools it is told with.
KEY = "with"


def targets(r: dict) -> list[str]:
    """The areas and tool names a rule is told with, or [] when it is told in the prompt like any other."""
    got = (r.get("when") or {}).get(KEY)
    if isinstance(got, str):
        got = [got]
    return [str(x) for x in got or [] if str(x).strip()] if isinstance(got, list) else []


def told_with_tools(r: dict) -> bool:
    return bool(targets(r))


def area_title(key: str) -> str:
    for k, title, _ in toolsearch.AREAS:
        if k == key:
            return title
    return key.replace("_", " ")


def said(names: list[str]) -> str:
    """"the Calendar tools", "the Gmail and Contacts tools", "the browser tool", "the browser and shipping tools"."""
    words = [area_title(n) if n in toolsearch.AREA_KEYS else n for n in names] or ["named"]
    joined = words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]
    one = len(words) == 1 and names and names[0] not in toolsearch.AREA_KEYS
    return f"the {joined} tool" + ("" if one else "s")


def _matches(tool: toolsearch.Tool, wanted: list[str]) -> bool:
    return tool.name in wanted or tool.area in wanted


def _rules_now(situation=None) -> list[dict]:
    """The rules on that are told with a tool in this chat turn."""
    from . import rules

    ds = rules.master()
    if not ds:
        return []
    return [r for r in rules.rules(ds) if told_with_tools(r) and not r.get("for")
            and rules.in_chat(r, situation)]


def block_for(tool: toolsearch.Tool, got: list[dict], say=None) -> str:
    """The words put at the end of one tool's description: every rule told with it, word for word."""
    mine = [r for r in got if _matches(tool, targets(r))]
    if not mine:
        return ""
    lines = ["", "", "Standing rules for using this tool. They are the person's rules (Rules page), told with the "
             "tool rather than in every turn; follow them as you would any rule in your instructions:"]
    for r in mine:
        text = " ".join(str(r.get("text") or "").split())
        if text:
            lines.append("- " + text)
    out = "\n".join(lines)
    return say(out) if say else out


def attach(entries, situation=None, *, rules_now=None, say=None) -> list:
    """The tools of a request with each tool's rules at the end of its description.

    `entries` are `toolsearch.Tool`s; only Rouh's own (with a description) carry rules, never a provider's
    server tool. A turn is never lost to its rules: if they cannot be read, the tools go as they are."""
    entries = list(entries)
    try:
        got = rules_now if rules_now is not None else _rules_now(situation)
    except Exception:  # noqa: BLE001 - the tools still go out
        log.exception("the rules told with tools could not be read; the tools go without them")
        return entries
    if not got:
        return entries
    from . import owner

    say = say or owner.say
    out = []
    for tool in entries:
        extra = block_for(tool, got, say=say) if tool.portable else ""
        if extra:
            d = dict(tool.definition)
            d["description"] = str(d.get("description") or tool.brief) + extra
            tool = dataclasses.replace(tool, definition=d)
        out.append(tool)
    return out


def for_page(r: dict) -> str:
    """The "Conditions:" line of a rule told with its tools, for the Rules page."""
    return (f"In chats: told with {said(targets(r))}, at the moment one of them is loaded in a turn, "
            "not in every turn")
