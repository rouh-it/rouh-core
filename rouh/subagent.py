"""A short model loop with a window of its own, whose window is thrown away.

Some questions are answered by reading twenty things and saying one sentence.
Asked in the turn itself, those twenty things land in the conversation and stay
there: twenty pages of HTML, twenty file listings, all of it read once and none
of it ever read again. Context editing (`rouh/context_editing.py`) cleans that
up afterwards. This stops it happening.

A subagent is one model loop with its own message list, a subset of the tools,
and no memory. It is given a task in words, it works, and the only thing that
crosses back into the turn is what it wrote at the end. The window it filled up
goes out of scope with the function.

What it is not:

- It is not `assistant_job`. That hands work to Claude Code in the person's
  workspace, takes minutes, and comes back to the screen by itself.
- It is not `delegate_task`. That is an administrator on this machine.

This is seconds long, it is inside the spoken turn, and it may only read.

On the orb it is a branch, drawn exactly the way a Claude Code sub-agent is
drawn, because it is the same kind of thing: the events carry an `agent_id`,
every tool call it makes hangs off that branch, and `look_into` itself gets no
twig of its own (`tree.AGENT_TOOLS`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets

from . import costs, fetchfallback, llmlog, modeldefaults, promptcache, servercalls

from .config import effort_for, thinking_for

log = logging.getLogger("rouh.subagent")

#: The name of the tool that starts one.
TOOL = "look_into"

#: What a subagent is allowed to do. Reading, and nothing else.
#:
#: This list is the whole of the safety argument for the feature, so it is an
#: allow list and never a deny list: a tool added to the registry tomorrow is
#: not a tool a subagent can call until somebody puts it here on purpose.
#: Nothing that writes, nothing that sends, nothing that starts work, nothing
#: that draws on the screen, and never `look_into` itself. Not `run_command`
#: either, since 30 October 2026 (task 139, finding S1): a helper reads pages
#: anybody wrote, and what it read could talk it into running a command.
MAY_USE = (
    "web_search",
    "web_fetch",
    "read_rouh_link",
    "youtube_transcript",
    "youtube_search",
    "read_workspace",
    "server_health",
    "what_is_running",
    "read_doc",
    "read_mail",
    "read_mail_attachment",
    "read_recent_mail",
    "search_drive",
    "list_drive_folder",
    "list_shared_drives",
    "list_drive_permissions",
    "list_calendars",
    "list_calendar_events",
    "read_calendar_event",
    "list_memory",
)

#: How many times round the loop before it has to answer with what it has.
MAX_ROUNDS = 8

#: The most that crosses back into the turn. A subagent that writes an essay
#: has defeated its own purpose, so the answer is cut and said to be cut rather
#: than quietly let through.
MAX_ANSWER = 2000

SYSTEM = """You are a research subagent working for Rouh, inside one of its turns.

You have been given one task. Do it with the tools you have, then write the
answer and stop.

How to answer:
- Short. A few sentences, or a few short lines. What you write is the only
  thing that reaches the conversation; everything you read is thrown away.
- Facts, with the names and numbers in them. Say where each one came from.
- Say plainly what you could not find out. Never fill a gap with a guess.
- No markdown headings and no bullet characters. Plain sentences and plain
  short lines.
- Never use an em dash. Use a plain dash or start a new sentence.
- You cannot ask anybody anything and nobody is reading while you work. If the
  task is unclear, answer the most useful reading of it and say which you took.

You may only read. You cannot change anything, send anything, or put anything
on the screen.{limit}"""


def allowed_definitions(definitions, wanted=None) -> list[dict]:
    """The tool definitions a subagent gets: the allow list, and no more.

    `wanted` narrows it further, and is what the caller asked for rather than
    what it may have. Anything in it that is not in the allow list is dropped
    without comment: a model asking for a tool it may not have is not an error
    worth failing a lookup over.
    """
    may = set(MAY_USE)
    if wanted:
        may &= {str(name) for name in wanted}
    out = []
    for definition in definitions or []:
        name = definition.get("name") if isinstance(definition, dict) else None
        if name in may:
            out.append(definition)
    return out


def _text_of(blocks) -> str:
    out = []
    for block in blocks or []:
        if getattr(block, "type", None) == "text":
            out.append(getattr(block, "text", "") or "")
        elif isinstance(block, dict) and block.get("type") == "text":
            out.append(block.get("text") or "")
    return "".join(out).strip()


def _serialisable(blocks) -> list:
    out = []
    for block in blocks or []:
        if hasattr(block, "model_dump"):
            out.append(block.model_dump(exclude_none=True))
        elif isinstance(block, dict):
            out.append(block)
    return out


_client = None
_client_key = ""


def _client_for(api_key: str):
    """The one client every subagent asks with, made once and kept.

    A lookup is made fresh each time and is gone a moment later; its client
    need not be. One made per lookup was a connection pool per lookup, and the
    HTTP client under it, which writes down every request (`rouh/llmlog.py`),
    is not one the SDK closes by itself when it is dropped.
    """
    global _client, _client_key
    if _client is None or _client_key != api_key:
        _client = llmlog.client(api_key, max_retries=0)
        _client_key = api_key
    return _client


class Subagent:
    """One lookup, run and thrown away.

    Made fresh for each call on purpose: there is no state worth keeping
    between two of them, and sharing one would be sharing a window, which is
    the one thing this exists to avoid.
    """

    def __init__(self, cfg, tools, client=None):
        self.cfg = cfg
        self.tools = tools
        # max_retries=0 for the same reason as in brain.py: one retry policy,
        # in one place, that knows whether anything has been said yet.
        self.client = client or _client_for(cfg.anthropic_api_key)

    def _system(self, rounds: int) -> str:
        return SYSTEM.format(
            limit=f"\n\nYou have at most {rounds} rounds of tool calls. "
                  "Answer with what you have when they run out.")

    async def run(self, task: str, emit, *, wanted=None, rounds: int = 0,
                  label: str = "") -> str:
        """Do the task and return the answer. Never raises.

        `emit` is the turn's own emitter, so everything below reaches the page
        and the work tree exactly as Rouh's own tool calls do, except that it
        carries an `agent_id` and therefore hangs off a branch.
        """
        task = " ".join(str(task or "").split())
        if not task:
            return "No task was given, so nothing was looked into."

        rounds = rounds or getattr(self.cfg, "subagent_rounds", MAX_ROUNDS)
        agent_id = "sub-" + secrets.token_hex(4)
        label = (label or task)[:60]
        tool_defs = allowed_definitions(self.tools.definitions(), wanted)

        await emit({"type": "subagent_start", "id": agent_id, "label": label,
                    "where": "rouh"})
        try:
            # Its requests are the turn's, in the log of requests, under a name
            # of their own (`rouh/llmlog.py`).
            with llmlog.about(purpose="subagent", subject=agent_id):
                work = await asyncio.to_thread(modeldefaults.use_pair, "subagent", None, self.cfg)
                if work.fallback or not work.model:
                    return await self._plain(task, work)
                return await self._loop(task, emit, agent_id, tool_defs, rounds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("a subagent failed")
            return (f"The lookup could not be finished: {type(exc).__name__}: {exc}. "
                    "Nothing was changed. Answer from what you already know, or try "
                    "the tools yourself.")
        finally:
            await emit({"type": "subagent_end", "id": agent_id, "where": "rouh"})

    async def _plain(self, task: str, work) -> str:
        """With no Anthropic key, whose web tools this loop reads with: the first model this Rouh
        can ask answers the task as one plain question, from what it knows, and says so
        (`modeldefaults.Use.fallback`, 24 October 2026)."""
        if not work.model:
            return ("The lookup could not be run: no model on its list can be asked here. "
                    "Answer from what you already know.")
        from . import llm

        got = await llm.ask_model(work.model, work.effort, max_tokens=getattr(self.cfg, "subagent_max_tokens", 2000),
                                  system=self._system(1) + "\n\nYou cannot read the web for this one: answer "
                                         "from what you know, and say plainly what you could not check.",
                                  messages=task, cfg=self.cfg)
        return _capped(got.text) or "The lookup finished without writing anything down."

    async def _loop(self, task: str, emit, agent_id: str, tool_defs: list,
                    rounds: int) -> str:
        messages: list[dict] = [{"role": "user", "content": task}]
        answer = ""
        # The same for every round of this lookup, and for every lookup given
        # the same tools, so it carries a breakpoint of its own and the tools
        # are cached with it (`rouh/promptcache.py`).
        system = [{"type": "text", "text": self._system(rounds),
                   "cache_control": dict(promptcache.BRIEF)}]
        # A page web_fetch could not read is read again in a browser, as in
        # the turn itself (`rouh/fetchfallback.py`).
        second = fetchfallback.Second(getattr(self.tools, "browsing", None), links=self.tools)
        for n in range(1, rounds + 1):
            # Streamed, like every other request this process makes. Nothing
            # here is spoken and nobody reads it as it arrives, but the
            # stand-in in front of Anthropic answers in one shape and one
            # shape only, and so, in practice, does every proxy in front of a
            # real one. One way of talking to the API is one thing to keep
            # working.
            # Its use's model on the Models page, at the level that comes with it
            # (`rouh/modeldefaults.py`). The use can only ask Anthropic, because this
            # loop reads the web with Anthropic's own server tools, so the page gives
            # it its tier's Anthropic model or an Anthropic model of its own, and that
            # is the one asked: nothing here swaps it.
            work = modeldefaults.use_pair("subagent", cfg=self.cfg)
            model = work.model
            # A call of Anthropic's that lost its result is a 400
            # (`rouh/servercalls.py`); the newest reply's are left waiting.
            messages = servercalls.repair(messages, in_flight=True, where=agent_id)
            request = dict(
                model=model,
                max_tokens=getattr(self.cfg, "subagent_max_tokens", 2000),
                system=system,
                # The newest round's results carry a breakpoint, so the next
                # round reads everything up to them back out of the cache
                # rather than paying for the whole lookup again each time.
                messages=promptcache.marked(messages),
                tools=tool_defs,
            )
            # It thinks either way; asked, it says what it thought, for the log
            # of requests and nothing else (`config.thinking_for`).
            thinking = thinking_for(model)
            if thinking:
                request["thinking"] = thinking
            # How deeply: the default level, to a model that takes one.
            effort = effort_for(model, work.effort)
            if effort:
                request["output_config"] = {"effort": effort}
            second.forget()
            async with self.client.messages.stream(**request) as stream:
                reply = await _read(stream, second, messages)
            log.info("%s, request %d: %s", agent_id, n,
                     costs.call_said(costs.tokens_of(reply.usage)))
            said = _text_of(reply.content)
            if said:
                answer = said
            # Stopped at a page web_fetch could not get: the reply ends in a
            # call of Rouh's own for it, and the page the browser read is
            # that call's result.
            cut = reply.stop_reason is None and bool(second.waiting)
            messages.append({"role": "assistant", "content": _serialisable(reply.content)
                             + (second.calls() if cut else [])})
            if cut:
                results = await second.run(emit, agent_id=agent_id)
                messages.append({"role": "user", "content": results})
                continue

            calls = [b for b in reply.content if getattr(b, "type", None) == "tool_use"]
            if reply.stop_reason != "tool_use" or not calls:
                break
            results = await asyncio.gather(
                *(self._one_tool(call, emit, agent_id) for call in calls))
            messages.append({"role": "user", "content": list(results)})
        else:
            # It used every round it had. Whatever it last said is the answer,
            # and the turn is told that it was cut short rather than being
            # handed a confident half-answer.
            if answer:
                answer += ("\n\n(This lookup ran out of rounds, so it may be "
                           "incomplete.)")

        return _capped(answer) or (
            "The lookup finished without writing anything down, so there is "
            "nothing to report from it.")

    async def _one_tool(self, block, emit, agent_id: str) -> dict:
        """One tool call, drawn on the branch rather than on the core."""
        from . import worklabel

        said = worklabel.describe_step(block.name, block.input)
        # Its calls send the page no input, except a command, whose line in
        # the chat shows it the way the turn's own does (`worklabel.command_input`).
        await emit({"type": "tool_start", "id": block.id, "name": block.name,
                    "input": worklabel.command_input(block.name, block.input) or "",
                    "what": said["what"], "detail": said["detail"],
                    "where": "rouh", "agent_id": agent_id})
        try:
            out = await self.tools.call(block.name, block.input, emit,
                                        call_id=block.id)
            ok, payload = True, out
        except Exception as exc:                # a failing tool ends the call, not the lookup
            log.exception("a subagent's tool %s failed", block.name)
            ok, payload = False, f"{type(exc).__name__}: {exc}"
        output = worklabel.command_output(block.name, payload)
        await emit({"type": "tool_end", "id": block.id, "name": block.name,
                    "ok": ok, "summary": "", "where": "rouh", "agent_id": agent_id,
                    **({"output": output} if output is not None else {})})
        return {
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": _content(payload),
            **({"is_error": True} if not ok else {}),
        }


def _content(payload):
    """A result as a tool_result's content. A file a tool showed (`untrusted.Blocks`) is read in at
    once: a look-up's history lives only in this call, so there is nothing to keep a marker for."""
    from . import attachments, untrusted
    from .tools import _files_store

    if isinstance(payload, untrusted.Blocks):
        store = _files_store()
        if store is None:
            return payload.said
        return attachments.expand(list(payload), store, attachments.INLINE_BUDGET)[0]
    return payload if isinstance(payload, str) else json.dumps(payload)


async def _read(stream, second, history):
    """The reply, read to its end, or up to a page web_fetch could not get
    and nothing after it (`rouh/fetchfallback.py`)."""
    async for event in stream:
        if event.type != "content_block_stop":
            continue
        so_far = stream.current_message_snapshot.content
        block = so_far[event.index] if event.index < len(so_far) else None
        if str(getattr(block, "type", "")).endswith("_tool_result"):
            second.note(block, so_far, history)
            if second.due(so_far):
                return stream.current_message_snapshot
    return await stream.get_final_message()


def _capped(answer: str) -> str:
    answer = (answer or "").strip()
    if len(answer) <= MAX_ANSWER:
        return answer
    return (answer[:MAX_ANSWER].rstrip()
            + f"\n\n(cut here: the lookup wrote more than {MAX_ANSWER} characters, "
              "and only this much is worth carrying in the conversation)")
