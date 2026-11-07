"""Small, redacted event bodies for the one program's agent hooks."""
from __future__ import annotations

import re
from typing import Any, Mapping

from rouh import worklabel

#: The fields of a tool's input kept in the list. Enough to say what the call
#: did; never a whole file's contents.
INPUT_FIELDS = ("command", "description", "file_path", "path", "pattern", "glob", "url", "query",
                "prompt", "subagent_type", "notebook_path", "offset", "limit", "run_in_background")
INPUT_TEXT = 400

#: The most of a run's closing words kept, in characters. They are the report the
#: person reads in the chat and on the canvas, so they are kept whole (`ListFile.append`
#: with ``whole``); this is only a guard against a runaway. Until 3 November 2026 they
#: were cut at 4,000, and a 4,360 character report ended "This was a diagno [cut]"
#: in the chat, on its card and in its notice (feedback fr_ca65f242fcbd).
CLOSING_TEXT = 100_000

_STEP = re.compile(r"tasks/\d{1,3}\.[^/\s\"']+/(\d{1,3}-\d{2})\.[A-Za-z]")


def small_input(tool_input: Mapping[str, Any] | None) -> dict[str, Any]:
    """The part of a tool's input worth keeping: short fields, secrets hidden."""
    out: dict[str, Any] = {}
    for name in INPUT_FIELDS:
        value = (tool_input or {}).get(name)
        if isinstance(value, str) and value:
            text = worklabel.redact(value)
            out[name] = text if len(text) <= INPUT_TEXT else text[: INPUT_TEXT - 6] + " [cut]"
        elif isinstance(value, (int, float, bool)):
            out[name] = value
    return out


def step_of(tool_input: Mapping[str, Any] | None) -> str | None:
    """The workspace step a call is working in, "30-10", from a path it names."""
    for name in ("file_path", "path", "notebook_path", "command"):
        value = (tool_input or {}).get(name)
        if isinstance(value, str):
            found = _STEP.search(value)
            if found:
                return found.group(1)
    return None


def _effort(payload: Mapping[str, Any]) -> str | None:
    raw = payload.get("effort")
    if isinstance(raw, Mapping):
        return str(raw.get("level") or "") or None
    return str(raw) if isinstance(raw, str) and raw else None


def tool_body(payload: Mapping[str, Any]) -> dict[str, Any]:
    """What a PreToolUse says about the call, as the list keeps it."""
    tool = str(payload.get("tool_name") or "tool")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), Mapping) else {}
    said = worklabel.describe_step(tool, tool_input)
    body: dict[str, Any] = {"call": payload.get("tool_use_id"), "tool": tool,
                            "input": small_input(tool_input), "what": said["what"],
                            "detail": said["detail"]}
    if payload.get("agent_id"):
        body["agent"] = payload["agent_id"]
    if payload.get("agent_type"):
        body["agent_type"] = payload["agent_type"]
    effort = _effort(payload)
    if effort:
        body["effort"] = effort
    step = step_of(tool_input)
    if step:
        body["step"] = step
    return body


def closed_body(payload: Mapping[str, Any], *, failed: bool = False) -> dict[str, Any]:
    body: dict[str, Any] = {"call": payload.get("tool_use_id"),
                            "tool": str(payload.get("tool_name") or "tool")}
    if payload.get("agent_id"):
        body["agent"] = payload["agent_id"]
    ms = payload.get("duration_ms")
    if isinstance(ms, (int, float)):
        body["ms"] = int(ms)
    response = payload.get("tool_response")
    ok = not failed
    if isinstance(response, str):
        # Codex sends what the call printed, as text; Claude Code sends an
        # object. There is nothing in the text that says it went wrong, so a
        # call that came back at all counts as having worked.
        pass
    elif isinstance(response, Mapping):
        if response.get("is_error") or response.get("isError") or response.get("interrupted") is True:
            ok = False
        status = str(response.get("status") or "")
        if status:
            body["status"] = status[:40]
            if status.lower() in {"error", "failed", "cancelled", "canceled", "rejected", "denied"}:
                ok = False
        spawned = response.get("agentId") or response.get("agent_id")
        if spawned:
            body["spawned"] = str(spawned)
    body["ok"] = ok
    return body


def plain(text: Any, limit: int) -> str:
    text = worklabel.redact(str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 6].rstrip() + " [cut]"


def simple_entry(kind: str, payload: Mapping[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """The entry for a hook that needs no decision, or None for one that is not kept."""
    if kind == "prompt":
        return "agent.prompted", {"text": plain(payload.get("prompt"), 4000)}
    if kind == "post_tool_use":
        return "tool.closed", closed_body(payload)
    if kind == "subagent_start":
        return "subagent.opened", {"agent": payload.get("agent_id"),
                                   "agent_type": payload.get("agent_type")}
    if kind == "subagent_stop":
        return "subagent.closed", {"agent": payload.get("agent_id")}
    if kind == "notification":
        return "agent.notified", {"type": payload.get("notification_type"),
                                  "message": plain(payload.get("message"), 500)}
    if kind == "session_end":
        return "agent.ended", {"reason": payload.get("reason")}
    return None

