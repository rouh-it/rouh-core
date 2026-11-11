"""A job asks Rouh's core to run one management command from a short allowlist.

Petar, 11 November 2026: "I am not supposed to run manually commands." A job works in the worker
container, which never reaches the live database and holds no password for it (`CONTAINERS.md`,
walls.worker-no-database), so a ``manage.py`` command that needs the database could only be typed
by a person, in a shell of the core. This is the narrow way round that: the job gateway's
``core_command`` tool (`rouh/job_gateway.py`), which names one command from `COMMANDS` and
nothing else. There is no shell, no argument of the job's is passed to a command, and no
credential leaves the core.

- **Read** commands (`job_policy.CORE_READS`) run in the core at once, in a thread, within
  `SECONDS`, and their output is the answer.
- **Maintenance** commands (`job_policy.CORE_MAINTENANCE`) are ones the owner has already agreed
  to. They are started in the core's background and the answer says they started; their
  progress is read with the matching read command. The first is the scrub of private reasoning
  out of the model request log (`rouh/reasoning_scrub.py`), agreed 11 November 2026.
- **Logged**: every call is a row of `job_requests` (kind ``command``, the command in ``tool``,
  what was said in ``answer``), which the job reads back with request_status and the owner sees
  on Metabolism, and a line in Rouh's log.

A job doing a trusted contact's work never has it (`job_policy.decide`). A command not in
`COMMANDS` is refused before anything runs.
"""
from __future__ import annotations

import asyncio
import io
import logging
import time

from . import job_policy as policy

log = logging.getLogger("rouh.core_commands")

#: How long a read command may take.
SECONDS = 60.0
#: The most of a command's output handed back.
MOST = 20_000

#: Every command a job may name: what it is, its class, and how it runs.
COMMANDS = {
    "table_sizes": {
        "what": "The database's size and its largest tables, with rows, table, TOAST and index "
                "sizes (manage.py table_sizes). Only reads.",
        "manage": ["table_sizes"],
    },
    "scrub_status": {
        "what": "How far the core's scrub of private reasoning out of llm_requests and llm_pieces "
                "has got: its phase, rows read and scrubbed, its resume point, the sizes before and "
                "after, and roughly how long is left (manage.py scrub_encrypted_reasoning --status). "
                "Only reads.",
        "manage": ["scrub_encrypted_reasoning", "--status"],
    },
    "scrub_encrypted_reasoning": {
        "what": "Start the core's scrub of OpenAI encrypted_content and Anthropic thinking "
                "signatures and redacted_thinking out of the stored model log now, in small "
                "batches, carrying on from where it last got to, then ordinary VACUUM on both "
                "tables. Answers at once; read its progress with scrub_status. Nothing happens if "
                "it is running or done. The owner agreed to it on 11 November 2026.",
        "start": "reasoning_scrub",
    },
}
assert set(COMMANDS) == set(policy.CORE_READS) | set(policy.CORE_MAINTENANCE), \
    "core_commands.COMMANDS and job_policy's CORE_ lists must name the same commands"


def tool_definition() -> dict:
    """The gateway's ``core_command`` tool, in MCP's shape."""
    listed = "\n".join(f"- {name}: {c['what']}" for name, c in COMMANDS.items())
    return {
        "name": policy.CORE_COMMAND,
        "description": (
            "Have Rouh's core run one management command from a short allowlist, for what needs "
            "the live database, which a job cannot reach. No shell and no other command; each "
            "call is logged, and request_status lists this job's calls with what they said. "
            "The commands:\n" + listed),
        "inputSchema": {"type": "object", "properties": {
            "command": {"type": "string", "enum": list(COMMANDS),
                        "description": "One command from the list."},
            policy.WHY_ARG: {"type": "string", "description": (
                "Why the work needs it, in one plain sentence; it is logged with the call.")}},
            "required": ["command"], "additionalProperties": False}}


def _manage(argv: list[str]) -> str:
    """One management command in this process, its output as text. On a thread."""
    from django.core.management import call_command

    from . import dbwork

    out = io.StringIO()
    try:
        call_command(*argv, stdout=out, stderr=out)
    finally:
        dbwork.release()
    return out.getvalue()


async def run(command: str) -> tuple[str, str]:
    """(outcome, text): "ran", "started" or "failed", and what to hand the job."""
    spec = COMMANDS.get(command)
    if spec is None:
        return "refused", (f"{command!r} is not a command the core runs for a job. The commands: "
                           + ", ".join(COMMANDS) + ".")
    if spec.get("start") == "reasoning_scrub":
        from . import reasoning_scrub

        got = await asyncio.to_thread(reasoning_scrub.start)
        # A moment for a new run to write its first state, so the answer says where it is.
        for _ in range(20):
            if got != "started" or await asyncio.to_thread(reasoning_scrub.state):
                break
            await asyncio.sleep(0.25)
        said = {"started": "Started in the core now, on a background thread of its own.",
                "running": "It is already running in the core, so nothing new was started.",
                "done": "It has already finished, so nothing was started."}[got]
        text = said + "\n\n" + await asyncio.to_thread(reasoning_scrub.describe)
        return ("started" if got == "started" else "ran"), text
    try:
        text = await asyncio.wait_for(asyncio.to_thread(_manage, list(spec["manage"])), SECONDS)
    except asyncio.TimeoutError:
        return "failed", f"{command} did not finish within {SECONDS:.0f} seconds."
    except Exception as exc:  # noqa: BLE001 - said to the job
        log.exception("core command %s failed", command)
        return "failed", f"{command} failed: {type(exc).__name__}: {exc}"
    text = text.strip() or "(it printed nothing)"
    if len(text) > MOST:
        text = text[:MOST] + f"\n[... cut: {len(text) - MOST:,} more characters]"
    return "ran", text


async def call(scope, args: dict, why: str = "") -> dict:
    """The gateway's ``core_command``: run, logged as a row of `job_requests`, answered."""
    from . import job_gateway

    command = str((args or {}).get("command") or "").strip()
    began = time.time()
    outcome, text = await run(command)
    took = time.time() - began
    await asyncio.to_thread(job_gateway._row, scope, kind="command", tool=command[:100],
                            need=f"core_command {command}"[:300], why=why[:1000],
                            outcome=outcome, answer=text[:4000], settled_at=time.time())
    log.info("%s had the core run %s: %s in %.1f s", job_gateway._job_said(scope), command,
             outcome, took)
    return {"ok": outcome in ("ran", "started"), "text": text}


__all__ = ["COMMANDS", "call", "run", "tool_definition"]
