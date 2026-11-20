"""A cost cap for each run that pays by the token: told first, then stopped.

191-01 weak spot 21 (task 191, 20 November 2026): "No cost limit per run or for chats. A run
that keeps working is never stopped; only beats and quests have budgets." 191-02's answer: "a
run that keeps going stops at its cost cap", a protection that costs the person nothing.

**Which runs.** Only a run that pays by the token: a run of Codex billed to the OpenAI API key
(`billing.API`), and a run of Claude Code while this program's Claude Code is on the
installation's Anthropic API key through the key proxy (`claude_signin`, the containers). A run
on a subscription costs nothing by the token, and its plan's own limits hold it, so it is not
counted: a long run of the person's own on their plan is never stopped by a dollar figure it
never spends.

**What it has cost.** Worked out from what the run itself wrote down, at list price
(`rouh/costs.py`, the same prices Rouh's own calls are counted at): for Claude Code, every
assistant message's usage in its transcript, read from where it was last read to, each message
once however many lines it was written in; for Codex, the token totals its sessions in the run's
folder keep (`codex_usage.for_run`). A model priced nowhere counts nothing, and the log says so.

**Told, then stopped.** At ``run_cost_warn`` of the cap (80%) the run is told, once, in its own
terminal as a message from the program, what it has spent and that it is stopped at the cap, so
it saves and reports first, as a run near the memory cap is. At the cap it is stopped
(``views.OVER_COST``): it ends failed, with the reason on it, and is never started again. A run
being saved or in a person's hands is left until that is over.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from . import agents, billing, claude_signin, codex_usage
from .views import ENDED, OVER_COST

if TYPE_CHECKING:
    from .program import Program

log = logging.getLogger("one.costcap")

#: How often each live run's cost is worked out again, in seconds.
EVERY = 60.0


def claude_on_key() -> bool:
    """Whether this program's Claude Code is on the API key through the key proxy."""
    if not claude_signin.enabled():
        return False
    try:
        return claude_signin.SignIn()._api_mode()
    except Exception:  # noqa: BLE001 - unknown is the subscription, which is never capped
        return False


def pays_by_token(run: dict[str, Any], *, claude_key: bool | None = None) -> bool:
    """Whether a run is billed by the token, which is what the cap is for."""
    engine = agents.engine_of(run.get("engine"))
    if engine == "codex":
        return billing.billing_of(engine, run.get("billing")) == billing.API
    return claude_on_key() if claude_key is None else bool(claude_key)


def price(usage: dict[str, Any], model: str) -> float:
    """What a usage cost at list price, in dollars; 0 for a model priced nowhere."""
    try:
        from rouh import costs
    except Exception:  # noqa: BLE001 - nothing to price with is nothing counted
        return 0.0
    got = costs.cost_of(usage, model)
    if got is None:
        log.warning("a run's usage on %s has no price, so it is not counted", model or "no model")
        return 0.0
    return float(got)


class ClaudeTally:
    """A Claude Code transcript's usage, read on from where it was last read to.

    Claude Code writes one assistant message as several lines, one per content block, each
    carrying the message's usage so far: the last line of a message id is its usage."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.offset = 0
        self.messages: dict[str, tuple[str, dict[str, Any]]] = {}

    def read(self) -> None:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read()
        except OSError:
            return
        cut = chunk.rfind(b"\n")
        if cut < 0:
            return
        self.offset += cut + 1
        for line in chunk[:cut].splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("type") != "assistant":
                continue
            message = record.get("message") or {}
            usage = message.get("usage")
            model = str(message.get("model") or "")
            if not isinstance(usage, dict) or not model or model == "<synthetic>":
                continue
            ident = str(message.get("id") or record.get("uuid") or len(self.messages))
            self.messages[ident] = (model, usage)

    def usages(self) -> list[tuple[str, dict[str, Any]]]:
        self.read()
        return list(self.messages.values())


def codex_usages(run: dict[str, Any], home: str) -> list[tuple[str, dict[str, Any]]]:
    """What a run of Codex has used, from the token totals of its sessions."""
    folder = codex_usage.run_folder(run)
    got = codex_usage.for_run(folder, home=home, since=codex_usage.requested_epoch(run)) \
        if folder else None
    if not got:
        return []
    tokens = got.get("tokens") or {}
    cached = int(tokens.get("cached_input_tokens") or 0)
    usage = {"input_tokens": max(0, int(tokens.get("input_tokens") or 0) - cached),
             "cache_read_input_tokens": cached,
             "output_tokens": int(tokens.get("output_tokens") or 0)}
    models = got.get("models") or []
    return [(models[-1] if models else "", usage)]


def cost_of(usages: list[tuple[str, dict[str, Any]]]) -> float:
    """What those usages cost at list price. On the event loop, where the prices are read
    without the database (`rouh/modelstandard.py`, `prices`)."""
    return sum(price(usage, model) for model, usage in usages)


def money(dollars: float) -> str:
    return f"${dollars:,.2f}"


def warning(spent: float, cap: float) -> str:
    """What a run near its cap is told."""
    return (f"[one] This run has spent {money(spent)} of the {money(cap)} one run may spend "
            "(ONE_RUN_COST_MAX). At the cap the program stops it. Commit and save what you have "
            "now, and finish with your report.")


def stop_why(spent: float, cap: float) -> str:
    """Why a run was stopped, said on it and to the person ("<title> <why>.")."""
    return (f"was stopped for spending {money(spent)}, over the {money(cap)} one run may spend "
            "(ONE_RUN_COST_MAX)")


class CostCap:
    """The program's cost cap, worked out on the scheduler's loop (`Scheduler._loop`)."""

    def __init__(self, program: "Program") -> None:
        self.p = program
        self.tallies: dict[str, ClaudeTally] = {}
        self.told: set[str] = set()
        self.checked_at = 0.0

    def usages(self, run: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        """What a run has used so far, by model: read off disk, so in a thread."""
        if agents.engine_of(run.get("engine")) == "codex":
            home = os.environ.get("ONE_ASUSER_HOME") or ""
            if not home:
                try:
                    home = self.p.runs._home(run)
                except Exception:  # noqa: BLE001
                    home = ""
            return codex_usages(run, home)
        path = str(run.get("transcript") or "")
        if not path:
            return []
        tally = self.tallies.get(run["id"])
        if tally is None or tally.path != path:
            tally = self.tallies[run["id"]] = ClaudeTally(path)
        return tally.usages()

    async def check(self, *, now: float | None = None) -> None:
        """Tell each paying run near its cap, and stop each one over it."""
        import asyncio

        s = self.p.settings
        cap = float(getattr(s, "run_cost_max", 0) or 0)
        now = time.monotonic() if now is None else now
        if cap <= 0 or now - self.checked_at < EVERY:
            return
        self.checked_at = now
        runs = self.p.runs
        claude_key = None
        live = set()
        for run in list(self.p.views.runs.values()):
            if run.get("kind") != "agent" or run.get("state") in ENDED or \
                    run.get("state") in ("queued", "saving"):
                continue
            live.add(run["id"])
            if run["id"] in runs.stopping or run["id"] in runs.takeovers:
                continue
            if agents.engine_of(run.get("engine")) != "codex" and claude_key is None:
                claude_key = await asyncio.to_thread(claude_on_key)
            if not pays_by_token(run, claude_key=claude_key):
                continue
            try:
                spent = cost_of(await asyncio.to_thread(self.usages, run))
            except Exception:  # noqa: BLE001 - one run that cannot be read never stops the rest
                log.exception("what run %s has spent could not be worked out", run["id"])
                continue
            if spent >= cap:
                log.info("stopping run %s: it has spent %s, over its cap of %s", run["id"],
                         money(spent), money(cap))
                runs.stopped_why[run["id"]] = stop_why(spent, cap)
                try:
                    await runs.stop(run["id"], by="program", how=OVER_COST)
                except Exception:
                    runs.stopped_why.pop(run["id"], None)
                    log.exception("could not stop run %s at its cost cap", run["id"])
            elif spent >= cap * float(getattr(s, "run_cost_warn", 0.8) or 0.8) and \
                    run["id"] not in self.told:
                self.told.add(run["id"])
                log.info("run %s has spent %s of its cap of %s: telling it", run["id"],
                         money(spent), money(cap))
                try:
                    await runs.say(run["id"], warning(spent, cap), by="program")
                except Exception:
                    log.exception("could not tell run %s it is near its cost cap", run["id"])
        for gone in set(self.tallies) - live:
            self.tallies.pop(gone, None)
        self.told &= live


__all__ = ["CostCap", "ClaudeTally", "EVERY", "claude_on_key", "codex_usages", "cost_of",
           "pays_by_token", "price", "stop_why", "warning"]
