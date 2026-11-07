"""The work tree: what every background worker is doing, right now, as data.

One function matters here, :func:`build_tree`. It takes a list of plain
dictionaries and returns a plain dictionary. No database, no sockets, no clock:
the current time is passed in. That is deliberate. The tree is the only part of
this feature that has real logic in it, so it is the part that has to be
testable with nothing but a list of events, which is what `test_tree.py` did
until the committed tests went on 20 September 2026.

Where the events come from
--------------------------

Claude Code fires hooks. Each worker's worktree gets a settings file pointing
``PreToolUse``, ``PostToolUse``, ``SubagentStart``, ``SubagentStop``, ``Stop``,
``Notification`` and ``SessionEnd`` at Rouh, which stores every one of them,
raw, in the ``crew_tree_events`` table. The worker itself is not a hook: it
comes from the ``crewmates`` row, handed in as a ``worker`` event.

Storing the events raw and deriving the tree on every read is the whole design.
A close that never arrives is then a bug that can be fixed and replayed, rather
than a structure on screen that nothing will ever correct.

Four facts from the real payloads, measured on the server on 8 September 2026
against Claude Code 2.1.263, make the tree exact rather than guessed:

* ``agent_id`` is present on every event inside a sub-agent and absent on the
  worker's own events, so each event attributes to one node with no inference.
* ``tool_use_id`` is the same on ``PreToolUse`` and ``PostToolUse``, so a tool
  call is one node that opens and closes.
* ``duration_ms`` arrives on ``PostToolUse``.
* ``effort`` arrives as ``{"level": "high"}``, a small object rather than a
  string. Both spellings are accepted here because that is the kind of thing
  that changes between releases.

Two shapes that are not obvious
-------------------------------

**Starting a sub-agent is itself a tool call.** ``PreToolUse`` for the ``Agent``
tool, then ``SubagentStart``, and later ``SubagentStop``. Drawing both would put
a tool node and a sub-agent node on screen for one piece of work, so the
``Agent`` tool call gets no node of its own: it is remembered, and the sub-agent
node takes its place. The parent's ``PostToolUse`` for that call names the
sub-agent it started, in ``tool_response.agentId``, which ties the two together
with no guessing.

**A sub-agent outlives the call that started it.** Watching a real job on the
server, ``PostToolUse`` for the ``Agent`` call arrived 32 milliseconds after the
sub-agent began, carrying ``"status": "async_launched"`` and ``"isAsync": true``
while the sub-agent went on working for another ten seconds. The parent then
fired ``Stop`` and ended its turn with the sub-agent still running. So neither
the ``Agent`` call finishing nor the parent's turn ending means the sub-agent is
done. Only ``SubagentStop`` does. This is why a worker that has finished a turn
still reads as running while something inside it is working: nothing is finished
while its own work is not.
"""
from __future__ import annotations

import re

from typing import Any, Iterable, Mapping

from . import worklabel

__all__ = [
    "describe_tree",
    "build_tree",
    "empty_tree",
    "AGENT_TOOLS",
    "PRUNE_AFTER",
    "STALE_AFTER",
    "MAX_CHILDREN",
    "RECENT_STEPS",
]

#: The tool names that start a sub-agent. Claude Code 2.1.263 calls it ``Agent``;
#: older builds called it ``Task``. Neither gets a tool node of its own.
#:
#: ``look_into`` is Rouh's own (``rouh/subagent.py``): a short model loop
#: with a window of its own, run inside a spoken turn. It is the same kind of
#: thing and it draws the same way, as a branch with the lookup's own tool
#: calls hanging off it rather than as one twig that says nothing.
AGENT_TOOLS = frozenset({"Agent", "Task", "look_into"})

#: How long a finished node stays in the tree after it closed, in seconds. The
#: tree is "now". A finished node is sent at least once as finished, so the page
#: can show it end - even a tool call that lasted 200 milliseconds - and the
#: page fades it out over a second and a half. Kept a little longer than that
#: here, so nothing finished comes back in a later push, and no longer, so the
#: shape on screen is what is happening rather than what happened.
PRUNE_AFTER = 2.0

#: A node open this long with no close is called ``lost`` rather than left
#: running for ever. Half an hour is well past any real tool call and well short
#: of a person noticing a lie. The normal way an orphan closes is its worker
#: closing, which cascades; this is the backstop for the case where the worker
#: is still alive and only the close went missing.
STALE_AFTER = 1800.0

#: The most children one node keeps. Open children are always kept; closed ones
#: are dropped oldest first. A worker that has run four hundred tool calls
#: should not turn into a four hundred kilobyte message every half second.
MAX_CHILDREN = 40

#: How many steps a job's card lists, newest first. Worked out before finished
#: steps are pruned, since the tree keeps one for only two seconds, and a card
#: showing only what runs this instant would say nothing of what the job did.
RECENT_STEPS = 6

#: Who runs a worker, from its mode. "auto" is the person's own assistant (task
#: 36), "self" is Rouh changing its own code, and every other mode is a job
#: Rouh started on the server.
_OWNER = {"auto": "assistant", "self": "self"}

#: How a crewmate's status reads as a node state.
_WORKER_STATE = {
    "starting": "running",
    "running": "running",
    "waiting": "waiting",
    "done": "done",
    "failed": "failed",
    "lost": "lost",
    # We stopped it on purpose, so we know it did not finish. From the tree's
    # point of view that is the same as never hearing how it ended.
    "killed": "lost",
}

_OPEN_STATES = frozenset({"running", "waiting"})


def empty_tree(*, state: str = "running") -> dict[str, Any]:
    """The tree with nothing in it. Idle is a shape too, not an absence."""
    return {"id": "root", "kind": "root", "state": state, "children": []}


# ---------------------------------------------------------------------------
# Reading the payloads
# ---------------------------------------------------------------------------


def _short_agent_id(raw: Any) -> str:
    """``aa73a53b0f2a8c900`` -> ``aa73a53b0f2a``."""
    return str(raw or "")[:12]


def _short_tool_id(raw: Any) -> str:
    """``toolu_019Nwy9Ca9AvSouvs9NBFYcB`` -> ``uvs9NBFYcB``.

    The prefix is the same on every id and the front of the body is close to the
    same, so the tail is what identifies a call. Ten characters of it is far
    more than enough inside one tree, and the id travels in every message.
    """
    text = str(raw or "")
    if text.startswith("toolu_"):
        text = text[len("toolu_"):]
    return text[-10:]


def _effort(payload: Mapping[str, Any]) -> str | None:
    """``{"level": "high"}`` and ``"high"`` both mean high."""
    raw = payload.get("effort")
    if isinstance(raw, Mapping):
        level = raw.get("level")
        return str(level) if level else None
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _tool_state(payload: Mapping[str, Any]) -> str:
    """Did that tool call work? Read conservatively: only say failed if told."""
    response = payload.get("tool_response")
    if isinstance(response, Mapping):
        if response.get("is_error") or response.get("isError"):
            return "failed"
        status = str(response.get("status") or "").strip().lower()
        if status in {"error", "failed", "cancelled", "canceled", "rejected", "denied"}:
            return "failed"
        if response.get("interrupted") is True:
            return "failed"
    if payload.get("is_error") or payload.get("error"):
        return "failed"
    return "done"


def _agent_id_of(payload: Mapping[str, Any]) -> str:
    return _short_agent_id(payload.get("agent_id"))


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


class _Node:
    """One thing on screen. Kept as an object while building, emitted as JSON."""

    __slots__ = ("id", "kind", "label", "what", "detail", "owner", "state", "effort",
                 "mode", "opened_at", "closed_at", "ms", "doing", "recent", "step", "children")

    def __init__(self, node_id: str, kind: str, opened_at: float, *,
                 label: str | None = None, state: str = "running") -> None:
        self.id = node_id
        self.kind = kind
        self.label = label
        # In words, from worklabel only: what a step did, or a helper's task.
        self.what: str | None = None
        self.detail: str | None = None
        # A worker's: who runs it ("assistant", "self" or "server").
        self.owner: str | None = None
        self.state = state
        self.effort: str | None = None
        self.mode: str | None = None
        self.opened_at = opened_at
        self.closed_at: float | None = None
        self.ms: int | None = None
        # A worker's or a helper's: what it is doing now, and its last steps.
        self.doing: str | None = None
        self.recent: list[dict[str, Any]] | None = None
        # A worker's: the workspace task and step it is working in, "30-02".
        self.step: str | None = None
        self.children: list[_Node] = []

    @property
    def open(self) -> bool:
        return self.state in _OPEN_STATES

    def close(self, at: float, state: str = "done", ms: int | None = None) -> None:
        if not self.open:
            return  # a repeated close is not a correction, it is a duplicate
        self.state = state
        self.closed_at = at
        if ms is None and self.opened_at is not None:
            ms = int(max(0.0, at - self.opened_at) * 1000)
        self.ms = ms

    def close_descendants(self, at: float, state: str) -> None:
        for child in self.children:
            child.close_descendants(at, state)
            child.close(at, state)

    def as_dict(self) -> dict[str, Any]:
        """Only the fields that apply. A tool has no effort; a worker has no ms."""
        out: dict[str, Any] = {"id": self.id, "kind": self.kind}
        if self.label is not None:
            out["label"] = self.label
        if self.what:
            out["what"] = self.what
        if self.detail:
            out["detail"] = self.detail
        if self.owner:
            out["owner"] = self.owner
        out["state"] = self.state
        if self.effort:
            out["effort"] = self.effort
        if self.mode:
            out["mode"] = self.mode
        out["opened_at"] = self.opened_at
        if self.closed_at is not None:
            out["closed_at"] = self.closed_at
        if self.ms is not None:
            out["ms"] = self.ms
        if self.doing:
            out["doing"] = self.doing
        if self.recent:
            out["recent"] = [dict(step) for step in self.recent]
        if self.step:
            out["step"] = self.step
        out["children"] = [child.as_dict() for child in self.children]
        return out


class _Worker:
    """One crewmate, plus the bookkeeping needed to place its events."""

    def __init__(self, node: _Node) -> None:
        self.node = node
        #: What the crewmates row says the worker itself is doing. Applied after
        #: every event rather than in timestamp order, because the row is not a
        #: thing that happened at a moment: it is the answer now.
        self.status: str | None = None
        self.closed_at: float | None = None
        self.agents: dict[str, _Node] = {}
        self.tools: dict[str, _Node] = {}
        #: ``Agent`` tool calls seen but not yet matched to a sub-agent, oldest
        #: first. Each is ``(tool_use_id, parent_agent_id)``.
        self.pending_agents: list[tuple[str, str]] = []
        #: ``Agent`` tool_use_id -> the sub-agent it started.
        self.agent_of_call: dict[str, str] = {}
        #: ``Agent`` tool_use_id -> the helper's task in words, from the call's
        #: input. The sub-agent's own events never say what it was asked to do.
        self.agent_text: dict[str, dict[str, Any]] = {}

    def node_for(self, agent_id: str, at: float, *, label: str | None = None) -> _Node:
        """The node an event belongs to: a sub-agent if it names one, else the worker.

        A sub-agent that has not been announced yet is created here rather than
        dropped, because ``SubagentStart`` and the first ``PreToolUse`` inside
        that sub-agent can arrive in either order.
        """
        if not agent_id:
            return self.node
        agent = self.agents.get(agent_id)
        if agent is None:
            agent = _Node(agent_id, "subagent", at, label=label or "sub-agent")
            self.agents[agent_id] = agent
            self._attach_agent(agent, agent_id, at)
        return agent

    def _attach_agent(self, agent: _Node, agent_id: str, at: float) -> None:
        """Hang a new sub-agent under whatever asked for it."""
        parent = self.node
        if self.pending_agents:
            call_id, parent_agent = self.pending_agents.pop(0)
            self.agent_of_call[call_id] = agent_id
            _name_helper(self, call_id, agent)
            if parent_agent and parent_agent in self.agents:
                parent = self.agents[parent_agent]
        else:
            # The parent's close for the call can name the sub-agent before
            # the sub-agent's own first event arrives.
            call_id = next((c for c, a in self.agent_of_call.items() if a == agent_id), None)
            if call_id:
                _name_helper(self, call_id, agent)
        parent.children.append(agent)


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------


def build_tree(
    events: Iterable[Mapping[str, Any]],
    *,
    now: float,
    own_events: Iterable[Mapping[str, Any]] = (),
    own_state: str | None = None,
    prune_after: float = PRUNE_AFTER,
    stale_after: float = STALE_AFTER,
    max_children: int = MAX_CHILDREN,
) -> dict[str, Any]:
    """Turn a list of events into the tree.

    ``events`` are dictionaries with ``kind``, ``at`` (unix seconds),
    ``crew_id`` and ``payload`` (the hook JSON exactly as it arrived). Order does
    not matter; they are sorted here. Anything unrecognised is ignored rather
    than raised on, because this runs behind an HTTP endpoint that a stale
    worktree with an old settings file can still reach.

    ``now`` is the only clock reading, and it is given, not taken.
    """
    workers: dict[str, _Worker] = {}

    for event in sorted(events, key=lambda e: (_as_float(e.get("at")), str(e.get("kind") or ""))):
        try:
            _apply(workers, event)
        except Exception:  # pragma: no cover - a bad event must not lose the tree
            continue

    root = _Node("root", "root", 0.0)

    # Rouh's own tool calls hang straight off the core rather than off a
    # spike, because Rouh is the core. Without this the tree only ever showed
    # delegated workers, so asking it to search the web changed nothing on
    # screen - the work was real, it just had nowhere to appear.
    own = _Worker(root)
    for event in sorted(own_events, key=lambda e: _as_float(e.get("at"))):
        try:
            kind = str(event.get("kind") or "")
            at = _as_float(event.get("at"))
            payload = event.get("payload") or {}
            if kind == "PreToolUse":
                _apply_pre_tool(own, at, payload, own=True)
            elif kind == "PostToolUse":
                _apply_post_tool(own, at, payload, own=True)
            elif kind == "ToolUpdate":
                _apply_tool_update(own, payload)
            elif kind == "ToolWaiting":
                _apply_tool_waiting(own, payload)
            elif kind == "SubagentStart":
                # Rouh's own subagent, which is a branch off the core in
                # exactly the way a worker's sub-agent is a branch off a spike.
                _apply_subagent_start(own, at, payload)
            elif kind == "SubagentStop":
                _apply_subagent_stop(own, at, payload)
        except Exception:  # one bad event must not lose the tree
            continue
    _close_stale(root, now=now, stale_after=stale_after)
    _prune(root, now=now, prune_after=prune_after, max_children=max_children)

    # Rouh's own work can wait on a person too: a tool that has to be asked
    # about stops until somebody presses a button (rouh/permissions.py).
    # That is the same "must never be left alone" as a worker asking, so it
    # reaches the top of the tree the same way.
    waiting = any(_has_waiting(child) for child in root.children)
    for worker in workers.values():
        node = worker.node
        _finalise(worker)
        _close_stale(node, now=now, stale_after=stale_after)
        if (not node.open and node.closed_at is not None
                and now - node.closed_at > prune_after
                and not _has_open_descendant(node)):
            continue
        _describe_work(node)
        _prune(node, now=now, prune_after=prune_after, max_children=max_children)
        waiting = waiting or _has_waiting(node)
        root.children.append(node)

    root.children.sort(key=lambda n: n.opened_at)
    out = root.as_dict()
    out.pop("opened_at", None)
    # A worker asking a human is the one thing that must not be missed, so it is
    # visible at the top of the tree as well as on the node itself. Otherwise
    # the core carries what Rouh itself is doing - thinking, listening,
    # speaking - so the middle of the picture is never dead while it works.
    if waiting:
        out["state"] = "waiting"
    elif own_state:
        out["state"] = own_state
    else:
        out["state"] = "running"
    return out


def _finalise(worker: _Worker) -> None:
    """Apply what the crewmates row says, once every event has been read.

    The row is the answer now, not something that happened at the moment the
    worker was created, so it is applied last. Two rules come out of watching a
    real job run.

    A worker that is ``lost``, ``killed`` or ``failed`` has no process any more,
    so everything still open under it never reported and is lost with it.

    A worker that is ``done`` has finished a turn, which is not the same as
    being finished. It can have a sub-agent still running, because Claude Code
    launches those asynchronously and ends the turn without them. Nothing is
    finished while something inside it is still working, so it reads as running
    until the last thing under it closes.
    """
    node = worker.node
    if worker.status is None:
        return  # no row for this worker: the hooks are all we know
    state = _WORKER_STATE.get(worker.status, "running")
    if state in _OPEN_STATES:
        node.state = state
        node.closed_at = None
        node.ms = None
        return

    closed_at = worker.closed_at or node.opened_at
    if state == "done" and _has_open_descendant(node):
        node.state = "running"
        node.closed_at = None
        node.ms = None
        return
    node.state = state
    node.closed_at = closed_at
    node.ms = int(max(0.0, closed_at - node.opened_at) * 1000)
    if state != "done":
        node.close_descendants(closed_at, "lost")


def _has_open_descendant(node: _Node) -> bool:
    return any(child.open or _has_open_descendant(child) for child in node.children)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _apply(workers: dict[str, _Worker], event: Mapping[str, Any]) -> None:
    kind = str(event.get("kind") or "").strip().lower()
    at = _as_float(event.get("at"))
    crew_id = str(event.get("crew_id") or "").strip()
    payload = event.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    if not crew_id:
        return

    if kind == "worker":
        _apply_worker(workers, crew_id, at, payload)
        return

    worker = workers.get(crew_id)
    if worker is None:
        # A hook event for a worker nobody told us about. Draw it anyway: an
        # event proves the worker exists, and dropping it would leave a hole.
        worker = _Worker(_Node(crew_id, "worker", at, label=crew_id))
        workers[crew_id] = worker

    if kind == "pre_tool_use":
        _apply_pre_tool(worker, at, payload)
    elif kind == "post_tool_use":
        _apply_post_tool(worker, at, payload)
    elif kind == "subagent_start":
        _apply_subagent_start(worker, at, payload)
    elif kind == "subagent_stop":
        _apply_subagent_stop(worker, at, payload)
    elif kind == "notification":
        # Only a real stop-and-ask. Claude Code fires this hook for two
        # unrelated things: a permission prompt, which genuinely blocks, and
        # going idle at the prompt, which is what every worker does a minute
        # after it finishes and which blocks nothing. A worker in the middle of
        # an ordinary long tool call - a browser waiting for a page, a build -
        # is working, and drawing it red and dashed with NEEDS YOU against it
        # sends the person to a job that needs nothing from them.
        if worker.node.open and not is_idle_notification(payload):
            worker.node.state = "waiting"
    elif kind == "stop":
        # The worker finished a turn. Its own tool calls are therefore over: a
        # tool call cannot outlive the turn that made it. Its sub-agents can,
        # and often do - Claude Code 2.1.263 launches them asynchronously and
        # the turn ends while they are still working - so they are left alone.
        for child in worker.node.children:
            if child.kind == "tool":
                child.close(at, "lost")
    elif kind == "session_end":
        # The session itself is gone, so nothing inside it is still running.
        worker.node.close_descendants(at, "lost")


#: What a notification says when nobody is actually needed.
#:
#: Measured on the live database on 8 September 2026: eighteen notifications
#: ever recorded, fifteen of them "Claude is waiting for your input" and three
#: "Claude needs your permission". So five out of six of them were a job that
#: was already over, and reading the two as one thing is what put finished jobs
#: under NEEDS YOU for ever. `crew.py` filters its own status on this too.
IDLE_NOTIFICATION = "waiting for your input"


def is_idle_notification(payload: Mapping[str, Any] | None) -> bool:
    """Whether a notification is a worker sitting at its prompt rather than a question."""
    message = ""
    if isinstance(payload, Mapping):
        message = str(payload.get("message") or "")
    return IDLE_NOTIFICATION in message.lower()


def _apply_worker(workers: dict[str, _Worker], crew_id: str, at: float,
                  payload: Mapping[str, Any]) -> None:
    """The crewmates row, as an event: who the worker is and how it is doing."""
    worker = workers.get(crew_id)
    if worker is None:
        worker = _Worker(_Node(crew_id, "worker", at))
        workers[crew_id] = worker
    node = worker.node
    node.opened_at = at or node.opened_at
    node.label = str(payload.get("title") or node.label or crew_id)
    node.mode = str(payload.get("mode") or "") or None
    node.owner = _OWNER.get(node.mode or "", "server")
    worker.status = str(payload.get("status") or "running").strip().lower()
    worker.closed_at = _as_float(payload.get("closed_at")) or None


def _apply_pre_tool(worker: _Worker, at: float, payload: Mapping[str, Any], *,
                    own: bool = False) -> None:
    tool_id = _short_tool_id(payload.get("tool_use_id"))
    if not tool_id:
        return
    agent_id = _agent_id_of(payload)
    parent = worker.node_for(agent_id, at, label=payload.get("agent_type"))
    _remember_effort(parent, payload)

    name = str(payload.get("tool_name") or "tool")
    if name in AGENT_TOOLS:
        # Starting a sub-agent. The sub-agent node stands for this call, so no
        # tool node is made; the call is remembered until SubagentStart names it.
        if tool_id not in worker.agent_text and isinstance(payload.get("tool_input"), Mapping):
            worker.agent_text[tool_id] = worklabel.describe_helper(payload.get("tool_input"))
        if tool_id not in worker.agent_of_call and not any(
            call == tool_id for call, _ in worker.pending_agents
        ):
            worker.pending_agents.append((tool_id, agent_id))
        return

    if tool_id in worker.tools:
        return  # duplicate PreToolUse
    node = _Node(tool_id, "tool", at, label=name)
    _describe_step(node, name, payload, own=own)
    worker.tools[tool_id] = node
    parent.children.append(node)


def _apply_post_tool(worker: _Worker, at: float, payload: Mapping[str, Any], *,
                     own: bool = False) -> None:
    tool_id = _short_tool_id(payload.get("tool_use_id"))
    if not tool_id:
        return
    agent_id = _agent_id_of(payload)
    parent = worker.node_for(agent_id, at, label=payload.get("agent_type"))
    _remember_effort(parent, payload)

    ms = payload.get("duration_ms")
    ms = int(ms) if isinstance(ms, (int, float)) else None
    name = str(payload.get("tool_name") or "tool")

    if name in AGENT_TOOLS:
        _close_agent_call(worker, tool_id, at, payload, ms)
        return

    node = worker.tools.get(tool_id)
    if node is None:
        # A close with no open. Draw the call anyway, already finished: it did
        # happen, and its duration says when it started.
        opened_at = at - (ms / 1000.0 if ms else 0.0)
        node = _Node(tool_id, "tool", opened_at, label=name)
        worker.tools[tool_id] = node
        parent.children.append(node)
    _describe_step(node, name, payload, own=own)
    node.close(at, _tool_state(payload), ms)


def _apply_tool_waiting(worker: _Worker, payload: Mapping[str, Any]) -> None:
    """A tool call that stopped to ask a person, and the moment it stops waiting.

    Rouh's own, from `permissions.py`. It is the call itself that waits, so
    the state goes on the call's node rather than on a node of its own: one
    piece of work, one thing on screen.
    """
    node = worker.tools.get(_short_tool_id(payload.get("tool_use_id")))
    if node is None or not node.open:
        return
    node.state = "waiting" if payload.get("waiting") else "running"
    if payload.get("waiting") and payload.get("what"):
        node.detail = str(payload["what"])[:200]


def _close_agent_call(worker: _Worker, tool_id: str, at: float,
                      payload: Mapping[str, Any], ms: int | None) -> None:
    """The parent's close for an ``Agent`` call. It names the sub-agent; it does
    not end it.

    Measured on the server on 8 September 2026: this fired 32 milliseconds after
    the sub-agent started, with ``"status": "async_launched"`` and
    ``"isAsync": true``, while the sub-agent went on working for another ten
    seconds. So the call returning is the launch returning, not the work
    finishing. ``SubagentStop`` is the close, and nothing else is.
    """
    response = payload.get("tool_response")
    agent_id = ""
    if isinstance(response, Mapping):
        agent_id = _short_agent_id(response.get("agentId") or response.get("agent_id"))
    worker.pending_agents = [p for p in worker.pending_agents if p[0] != tool_id]
    if tool_id not in worker.agent_text and isinstance(payload.get("tool_input"), Mapping):
        worker.agent_text[tool_id] = worklabel.describe_helper(payload.get("tool_input"))
    if agent_id:
        worker.agent_of_call[tool_id] = agent_id
        agent = worker.agents.get(agent_id)
        if agent is not None:
            # This names the sub-agent exactly. Matching by order when it
            # started can pair two helpers started together the wrong way round.
            _name_helper(worker, tool_id, agent)


def _apply_subagent_start(worker: _Worker, at: float, payload: Mapping[str, Any]) -> None:
    agent_id = _agent_id_of(payload)
    if not agent_id:
        return
    label = str(payload.get("agent_type") or "sub-agent")
    node = worker.agents.get(agent_id)
    if node is None:
        worker.node_for(agent_id, at, label=label)
        return
    # It announced itself late: keep the node, correct the label and the time.
    node.label = label
    node.opened_at = min(node.opened_at, at)


def _apply_subagent_stop(worker: _Worker, at: float, payload: Mapping[str, Any]) -> None:
    agent_id = _agent_id_of(payload)
    node = worker.agents.get(agent_id)
    if node is None:
        return  # a stop for something we never saw start
    node.close_descendants(at, "lost")
    node.close(at, "done")


def _remember_effort(node: _Node, payload: Mapping[str, Any]) -> None:
    effort = _effort(payload)
    if effort:
        node.effort = effort


# --- saying what the work is --------------------------------------------------
#
# Asked for on 13 September: a line that said only "Bash" or "Searching the web"
# meant nothing. Every word here comes from `worklabel`, which hides secrets and
# caps lengths, and only those words leave in the tree, never a raw input.


def _describe_step(node: _Node, name: str, payload: Mapping[str, Any], *, own: bool) -> None:
    """Put into words what one call is doing, from what it was given.

    A worker's step is described from its hook payload's ``tool_input``. One of
    Rouh's own arrives already described, because only those words are kept
    for it (``server.OwnWork``), and they pass through ``worklabel.given`` so
    they are hidden and capped the same way.
    """
    if own:
        if payload.get("what"):
            said = worklabel.given(payload.get("what"), payload.get("detail"))
        elif node.what is None:
            said = worklabel.describe_step(name, None)
        else:
            return
    else:
        tool_input = payload.get("tool_input")
        if node.what is not None and not tool_input:
            return  # a close with no input says nothing new about the call
        said = worklabel.describe_step(name, tool_input)
    node.what, node.detail = said["what"], said["detail"]


def _apply_tool_update(worker: _Worker, payload: Mapping[str, Any]) -> None:
    """Rouh learned what one of its own calls was given after it started.

    And, for one of OpenAI's web calls, what it was: a call Luna starts is
    only known to have opened a page rather than searched once it is done
    (`rouh/luna.py`), and its twig takes the name, and so the colour, of what
    it turned out to be. Anthropic's calls never change their name.
    """
    node = worker.tools.get(_short_tool_id(payload.get("tool_use_id")))
    renamed = str(payload.get("tool_name") or "")
    if node is not None and renamed and renamed != node.label:
        node.label = renamed
    if node is not None and payload.get("what"):
        said = worklabel.given(payload.get("what"), payload.get("detail"))
        node.what, node.detail = said["what"], said["detail"]


def _name_helper(worker: _Worker, call_id: str, agent: _Node) -> None:
    """Give a sub-agent the task its ``Agent`` call gave it."""
    said = worker.agent_text.get(call_id)
    if said:
        agent.what, agent.detail = said["what"], said["detail"]


# Which task and step of the workspace a job is in, named the way its folders
# are: ".../private/assistant/30.jarvis/30-02.pipecat/..." is "30-02". Asked
# for on 14 September 2026, so the orb's label says which piece of work a job
# is.
#
# What is matched is the folder names themselves rather than a `tasks/` in
# front of them, because there is no `tasks/` any more: a task sits under the
# projects that own it, at whatever depth, so nothing above the numbers is
# fixed. A step is `NN.name/NN-MM.name`, which is specific enough on its own
# that no ordinary path matches it by accident.
_STEP_IN_PATH = re.compile(r"/\d{1,3}\.[^/\s\"']+/(\d{1,3}-\d{2})\.[A-Za-z]")
_TASK_IN_PATH = re.compile(r"/(\d{1,3})\.[A-Za-z][^/\s\"']*/")
_WRITES = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})


def _task_step(steps: list[_Node]) -> str | None:
    """The workspace task and step a job is working in, from its steps newest
    first: the last step folder it wrote in, else the last it read or searched,
    else only the task, "30". None for a job that never touched a task."""
    def text(step: _Node) -> str:
        return " ".join(part for part in (step.detail, step.what) if part)

    for only_writes in (True, False):
        for step in steps:
            if only_writes and step.label not in _WRITES:
                continue
            found = _STEP_IN_PATH.search(text(step))
            if found:
                return found.group(1)
    for step in steps:
        found = _TASK_IN_PATH.search(text(step))
        if found:
            return found.group(1)
    return None


def _describe_work(node: _Node) -> None:
    """What a job, and each helper in it, is doing now, and its last steps.

    Worked out before finished steps are pruned: the tree keeps a finished step
    for two seconds, so without this a card could list only what is running at
    that instant.
    """
    for child in node.children:
        if child.kind == "subagent":
            _describe_work(child)
    steps: list[tuple[_Node, _Node | None]] = []   # each step, and the helper it ran in
    helpers: list[_Node] = []

    def walk(parent: _Node, helper: _Node | None) -> None:
        for child in parent.children:
            if child.kind == "tool":
                steps.append((child, helper))
            elif child.kind == "subagent":
                if child.open:
                    helpers.append(child)
                walk(child, child)

    walk(node, None)
    steps.sort(key=lambda pair: pair[0].opened_at, reverse=True)
    recent: list[dict[str, Any]] = []
    for step, helper in steps[:RECENT_STEPS]:
        item: dict[str, Any] = {"what": step.what or step.label or "tool", "state": step.state}
        # The tool's own name, so the card on the orb can mark each step with
        # its kind's colour and mark.
        if step.label:
            item["tool"] = step.label
        if step.ms is not None:
            item["ms"] = step.ms
        if helper is not None:
            item["helper"] = helper.what or helper.label or "a helper"
        recent.append(item)
    node.recent = recent or None
    if node.kind == "worker":
        node.step = _task_step([step for step, _ in steps])
    if not node.open:
        node.doing = None
        return
    node.doing = worklabel.describe_doing(
        [step.what or step.label for step, _ in steps if step.open],
        waiting=node.state == "waiting",
        helpers=[h.what or h.label for h in helpers],
    )


# ---------------------------------------------------------------------------
# Closing and pruning
# ---------------------------------------------------------------------------


def _close_stale(node: _Node, *, now: float, stale_after: float) -> None:
    """Nothing stays open for ever.

    Two ways a node stops running without being told to. Its parent finished, so
    it is an orphan and never reported. Or it has been open far longer than any
    real tool call, which means the close went missing.
    """
    for child in node.children:
        if child.open and (not node.open or now - child.opened_at > stale_after):
            child.close_descendants(now, "lost")
            child.close(now, "lost")
        _close_stale(child, now=now, stale_after=stale_after)


def _prune(node: _Node, *, now: float, prune_after: float, max_children: int) -> None:
    kept: list[_Node] = []
    for child in node.children:
        if (not child.open and child.closed_at is not None
                and now - child.closed_at > prune_after
                and not _has_open_descendant(child)):
            continue
        _prune(child, now=now, prune_after=prune_after, max_children=max_children)
        kept.append(child)
    if len(kept) > max_children:
        openers = [c for c in kept if c.open]
        closers = [c for c in kept if not c.open]
        closers.sort(key=lambda c: c.closed_at or c.opened_at)
        keep_closed = closers[max(0, len(openers) + len(closers) - max_children):]
        kept = sorted(openers + keep_closed, key=lambda c: c.opened_at)
    node.children = kept


def _has_waiting(node: _Node) -> bool:
    if node.state == "waiting":
        return True
    return any(_has_waiting(child) for child in node.children)


# --- saying it out loud ------------------------------------------------------

_KIND_WORDS = {
    "worker": "worker",
    "subagent": "sub-agent",
    "tool": "tool",
}


def _ago(node: Mapping[str, Any], now: float) -> str:
    """How long a node has been going, or how long it took."""
    ms = node.get("ms")
    if ms is not None:
        return f"{int(ms) / 1000:.1f}s" if int(ms) < 60000 else f"{int(ms) // 60000}m"
    start = _as_float(node.get("opened_at"))
    end = node.get("closed_at")
    end = _as_float(end) if end is not None else now
    secs = max(0, int(end - start))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s"
    return f"{secs // 3600}h {(secs % 3600) // 60}m"


def describe_tree(tree: Mapping[str, Any], *, now: float | None = None) -> str:
    """The tree as text, for the assistant to read and then talk about.

    The orb draws this same structure as a shape. Nobody can be asked to read a
    shape aloud, so this is the same thing in words: one line per node, indented
    by depth, with what it is, what it is called, whether it is open and how
    long it has been going.
    """
    import time as _time

    now = _time.time() if now is None else now
    lines: list[str] = []
    counts = {"worker": 0, "subagent": 0, "tool": 0}
    open_counts = dict(counts)
    waiting: list[str] = []

    def walk(node: Mapping[str, Any], depth: int) -> None:
        kind = str(node.get("kind") or "")
        state = str(node.get("state") or "")
        if kind in counts:
            counts[kind] += 1
            if state in _OPEN_STATES:
                open_counts[kind] += 1
        label = str(node.get("label") or _KIND_WORDS.get(kind, kind))
        if kind != "root":
            # A call straight under the root is the assistant's own, made while it
            # answers. Unmarked, it read like any other, and asked whether the orb
            # shows its own work, the assistant said it did not.
            words = _KIND_WORDS.get(kind, kind)
            if kind == "tool" and depth == 1:
                words = "your own " + words
            bits = [f"{words} {label!r}", state, _ago(node, now)]
            effort = node.get("effort")
            if effort:
                bits.append(f"effort {effort}")
            line = "  " * (depth - 1) + "- " + ", ".join(b for b in bits if b)
            lines.append(line)
            if state == "waiting":
                # A job stuck on a merge conflict carries the question itself,
                # because there is no screen to read it off: it is a record on
                # disk (rouh/conflicts.py), and the whole point of it is that
                # the question travels with the thing that is waiting.
                asked = str(node.get("detail") or "") if node.get("conflict") else ""
                waiting.append(f"{label} - {asked}" if asked else label)
        for child in node.get("children") or ():
            walk(child, depth + 1)

    walk(tree, 0)

    if not lines:
        return (
            "Nothing is running. No workers, no sub-agents, no tool calls open. "
            "The orb is drawing its idle shape."
        )

    head = (
        f"{open_counts['worker']} of {counts['worker']} workers still going, "
        f"{open_counts['subagent']} of {counts['subagent']} sub-agents, "
        f"{open_counts['tool']} of {counts['tool']} tool calls open."
    )
    out = [head]
    if waiting:
        out.append(
            "Waiting on a person: " + "; ".join(waiting) + ". "
            "One whose line already carries a question is a job whose work will not go "
            "onto main; answer it with answer_conflict and nothing else. For any other, "
            "read it with look_at_task before saying anything about it."
        )
    out.append("")
    out.extend(lines)
    return "\n".join(out)
