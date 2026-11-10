"""Starting work, once, for every way of asking for it.

There were four verbs - `assistant_job`, `delegate_task`, `improve_myself`,
`one_start` - and four code paths behind them, and the four paths were the same
path. Every one of them is Claude Code doing a job; what actually differed
between them was two fields:

    workspace   where the work belongs
    policy      under what rules it works

which is exactly what a run row carries (`objects.Run`). So there is one call
here, `start`, and the four are presets over it: a name the spoken model routes
with, a workspace and a policy, and nothing else of their own. The person is
never asked to choose between them and never will be - that is the whole reason
the four names stay on the surface.

What is genuinely particular to one of them stays, and stays as configuration
rather than as a fourth code path: the assistant's job is composed into the
workspace's own words (`assistant_job.compose_task`), a change to Rouh lands
itself with `land.sh`, a job on this server may use sudo. Each of those is a
field of a `Preset` below.

Where a run actually runs
-------------------------

Two transports, and the policy picks between them, because the policy *is* the
difference: a run under the one program's rules is a run of the one program,
and a run under a Claude Code permission mode is a worker here. There is no
third thing to decide.

* **policy "one"** - the one program, in a space of its own. Every tool call it
  makes is decided by `one/rules.py`, which is what the single word "one" says.
* **anything else** - a worker of the crew, in a worktree, under that mode.

A preset may say it would rather be a run of the program (`prefers_one`), and
then the program is asked first and the crew takes it if the program is not
there or will not have it. That is the fallback that has been in place since
D42; it is one branch inside one function now instead of being written out
three times.

The run row is written here
---------------------------

Whichever transport took it, the row goes into the register at once, with the
workspace and the policy this call resolved - so a run exists as a row before
anything else has heard of it, which is what lets it be attached to a task in
the same breath as being started. The feeds (`runs.crew_run`, `runs.one_run`)
go on bringing it up to date afterwards; they write the same two fields from
the same two facts, so nothing can contradict anything.

Two links are written with it, and neither is ownership:

* `from` - which chat asked for it, when one did. A reference, never a hold: a
  run outlives the chat it came from, and deleting that chat leaves the run and
  its diff exactly where they are. Starting it does not make that chat anything
  either: a run started in a loose conversation leaves it a loose conversation,
  because numbered work is made when the person asks for it and at no other
  moment. When the person asked for a task and the run is what made it, the
  chat becomes that task's chat once the work lands
  (`conversations.adopt_made_task`).
* `owns` - only when the caller named an owner. Nothing here gives a run an
  owner by itself: an orphan is legal and is what a run starts as.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from . import events, modeldefaults, objects, owning, runs, saving, workspace_repo

log = logging.getLogger("rouh.starting")


#: The policy that means the one program's own rules, and the word a row is
#: read back by. `runs.ONE_POLICY` is where it lives; this is the same string.
ONE = runs.ONE_POLICY

#: How long a start waits for what Rouh has just made to reach main, in seconds.
#: A landing is a fetch, a replay and a push; longer than this and the run
#: starts anyway, told where its task is, and land.sh stops a second one.
SAVE_WAIT = 90.0


def with_its_task(brief: str, chat: str) -> str:
    """The brief, and which task it belongs to when it was asked in a task's chat.

    On 22 September 2026 the person said "Make a new task that finds the movies
    we can go to today", in a chat. Rouh made task 56 out of that chat
    and started a job, and the job, told only the request, made a task 56 of its
    own: two tasks, one number, for two days. A run asked for in a task's
    conversation is that task's work, so it is told so, in words that win over
    a request that says to make one, because Rouh already did.
    """
    if not chat:
        return brief
    try:
        from . import conversations

        from . import forks

        # A fork of a task's chat is that task's work too (`forks.task_above`).
        task = conversations.task_of(chat) or forks.task_above(chat)
    except Exception:
        log.debug("which task chat %s is could not be read", chat, exc_info=True)
        return brief
    if task is None or not task.folder:
        return brief
    name = f"task {task.number}, {task.title}" if task.number is not None else task.title
    return (f"{brief}\n\n## The task this belongs to\n\n"
            f"This was asked in the conversation of {name}, and that task already "
            f"exists: `{workspace_repo.in_run(task.folder)}`. It is the task this work belongs "
            "to, even where the request above says to make one, because Rouh made it "
            "when it was asked for. Write what you make for it into that task, as its "
            "next step, and do not make another task for the same work. If the folder "
            "is not in your checkout, run `git pull --rebase origin main` once; if it "
            "is still not there, make it at exactly that path, with that number.")


def _task_in_play(chat: str, owner: tuple[str, str] | None) -> str:
    """The id of the task a run is for: the one it is filed under, else its chat's task."""
    if owner and owner[0] == "task" and owner[1]:
        return str(owner[1])
    if not chat:
        return ""
    try:
        from . import conversations

        from . import forks

        task = conversations.task_of(chat) or forks.task_above(chat)
    except Exception:
        log.debug("which task chat %s is could not be read", chat, exc_info=True)
        return ""
    return str(task.id) if task is not None else ""


#: The presets that are the person's own work, and so begin with their rules.
#: Not `improve_myself` or `delegate_task`: those change Rouh or this server.
FOR_THE_PERSON = frozenset({"assistant_job", "one_start"})


def for_the_person(spec: "Preset | None", where: dict, workspace: str = "") -> bool:
    """Whether this run is the person's own work: their standing rules go first.

    A preset says it by its name. The Start box, which has none, says it by
    where the run works: the one program's own space, which is the person's
    workspace, or the person's workspace on disk, but never "This server, as
    administrator", which is the same space under another name.
    """
    if spec is not None:
        return spec.name in FOR_THE_PERSON
    if str(workspace or "").strip() == "server":
        return False
    if where.get("policy") == ONE:
        # A run of the program works in the space it is sent, and in the
        # person's own when it is sent none.
        return where.get("space") in ("", "assistant")
    return bool(where.get("path")) and where.get("path") == _assistant_repo()


def _assistant_repo() -> str:
    from .config import config

    return str(getattr(config, "assistant_repo", "") or "")


def _with_rules(brief: str, chat: str, task: str) -> str:
    """The brief with the standing rules read now in front of it; the brief alone when that fails."""
    try:
        from . import rules

        return rules.with_rules(brief, chat_id=chat, task_id=task)
    except Exception as exc:  # noqa: BLE001 - a run is never held back for its rules
        log.warning("the standing rules could not be put in front of a run's brief: %s", exc, exc_info=True)
        return brief


class CannotStart(RuntimeError):
    """Nothing took the job, and the message is the sentence to say."""


@dataclass(frozen=True)
class Preset:
    """One of the four surface names, as the two fields that actually differ.

    `workspace` is worked out from the configuration when the run starts, so a
    machine with no copy of the person's workspace says so rather than starting
    a job in the wrong place.
    """

    #: The tool's name, which is also what the register's `title` falls back to.
    name: str
    #: Which attribute of the configuration names the workspace on disk. Empty
    #: means the job has no repository and gets a scratch directory.
    repo_from: str = ""
    #: The one program's space for this preset, when it may be a run of the
    #: program at all.
    space: str = ""
    #: The policy a worker of the crew runs under. Overridden by `mode` for
    #: `delegate_task`, which is the one preset that lets the model choose.
    policy: str = "safe"
    #: The crew's worker profile, when this preset has one of its own.
    profile: str = ""
    #: When the one program is asked first: the policies for which it is the
    #: right home. Empty means always, which is what three of the four are.
    #: `delegate_task` is the one exception: a job the person wants to approve
    #: step by step stays with the crew, because a run of the program never
    #: stops to ask.
    one_if_policy: tuple[str, ...] = ()
    #: The line the card shows while it starts.
    detail: str = "started"
    #: What the model is told when the program took it, and when the crew did.
    note_one: str = ""
    note_crew: str = ""
    #: What the brief becomes. The assistant's is composed into the workspace's
    #: own words; everything else is sent as it was written.
    compose: Callable[[str], str] | None = field(default=None, repr=False)


def _assistant_brief(brief: str) -> str:
    from .assistant_job import compose_task

    return compose_task(brief)


#: The four, and the whole of what makes them four. Read down the `space`,
#: `repo_from` and `policy` columns: that is the entire difference between them.
PRESETS: dict[str, Preset] = {
    "assistant_job": Preset(
        name="assistant_job",
        repo_from="assistant_repo",
        space="assistant",
        # Auto, not yolo: Claude Code's own reviewer approves each step, so the
        # job runs unattended and the riskiest steps stop and ask, which Rouh
        # reads out. It cannot push either; landing does that.
        policy="auto",
        profile="assistant",
        compose=_assistant_brief,
        note_one="Started as a run of the one program.",
        note_crew="",
    ),
    "delegate_task": Preset(
        name="delegate_task",
        repo_from="",
        space="assistant",
        # Unattended by default. A prompt nobody can answer is not a safety
        # feature, it is a hang.
        policy="yolo",
        one_if_policy=("yolo",),
        note_one=("Started as a run of the one program: your assistant, working on this "
                  "server, which may use sudo."),
        note_crew="",
    ),
    "improve_myself": Preset(
        name="improve_myself",
        repo_from="app_dir",
        space="rouh",
        policy="self",
        detail="changing Rouh itself",
        note_one=("Started as a run of the one program, in its own checkout of your code. "
                  "It commits only once it has proved the change, lands it on main through "
                  "land.sh when it finishes, and you are restarted onto it at once, with "
                  "nobody asked. Do not call deploy_myself for it."),
        note_crew=("Watch it with check_tasks. When it says it has pushed, call "
                   "deploy_myself."),
    ),
    "one_start": Preset(
        name="one_start",
        # The program's own workspace: the space it starts a run in when
        # nothing names one, which is the person's own.
        space="assistant",
        policy="one",
        note_one="",
        note_crew="",
    ),
}

def workspaces() -> list[dict]:
    """The workspaces this machine has names for, for the interface's Start box.

    Each entry says both things a start needs: the one program's space for it,
    and the path on disk a worker of the crew would work in. Which of the two
    is used is decided by the policy, not here.

    The one program's own spaces are added to this list by the Start box, which
    asks the program for them directly and can also add one.
    """
    from .config import config

    out: list[dict] = []
    seen: set[str] = set()

    def add(name: str, label: str, *, space: str = "", path: str = "") -> None:
        if name in seen:
            return
        seen.add(name)
        out.append({"name": name, "label": label, "space": space, "path": path})

    if getattr(config, "assistant_repo", ""):
        add("assistant", "The assistant, in your workspace",
            space="assistant", path=config.assistant_repo)
    add("server", "This server, as administrator", space="assistant", path="")
    if getattr(config, "app_dir", ""):
        add("rouh", "Rouh's own code", space="rouh", path=config.app_dir)
    return out


def resolve(preset: str = "", *, workspace: str = "", policy: str = "",
            mode: str = "", repo: str = "") -> dict:
    """The two fields, worked out once, whoever asked.

    A preset supplies them; an explicit workspace or policy - which is what the
    Start box in the interface sends - wins over the preset's, because a person
    naming a workspace means that workspace.
    """
    from .config import config

    spec = PRESETS.get(preset)
    chosen = str(policy or "").strip().lower()
    if not chosen:
        chosen = str(mode or "").strip().lower() if preset == "delegate_task" else ""
    if not chosen and spec is not None:
        chosen = spec.policy
    if not chosen:
        chosen = ONE
    if chosen not in objects.POLICIES:
        raise CannotStart(
            f"{chosen!r} is not one of the policies a run works under: "
            + ", ".join(objects.POLICIES))

    named = str(workspace or "").strip()
    space = named
    path = ""
    if named.startswith("/"):
        space, path = "", named
    else:
        for known in workspaces():
            if known["name"] == named:
                space, path = known["space"], known["path"]
                break
    if not named and spec is not None:
        space = spec.space
        path = str(getattr(config, spec.repo_from, "") or "") if spec.repo_from else ""
    if repo:
        path = repo
    return {"policy": chosen, "space": space, "path": path,
            "profile": spec.profile if spec is not None else "",
            "preset": spec}


async def start(*, brief: str, title: str = "", preset: str = "",
                workspace: str = "", policy: str = "", mode: str = "",
                repo: str = "", agent: str = "", billing: str = "",
                expects: Sequence[str] = (),
                chat: str = "", owner: tuple[str, str] | None = None,
                org_id: str = "", model: str = "", use: str = "",
                one_fields: dict | None = None, standing_rules: bool | None = None,
                made_by: str | None = None, boxes: dict | None = None,
                asked_for: str | None = None, agent_chosen: bool = False,
                cfg: Any, crew: Any = None, one: Any = None,
                emit: Callable | None = None) -> dict:
    """Start one run, whoever asked and whatever they called it.

    The one call. Every start on this machine comes through here: the four
    surface tools, and the Start box in the interface that names a workspace
    and a policy and belongs to nothing.

    A run of the one program is told which model to be and how deeply to
    think: `org_id`'s default pair, or the pair of whoever is speaking
    (`rouh/modeldefaults.py`). A worker here asks for the same pair itself.

    Raises `CannotStart` with the sentence to say when nothing would take it.

    ``billing`` is "api" only when the person asked for a run of Codex billed
    to the OpenAI API key (one/billing.py). Only the one program can do that,
    so such a run is never handed to a worker here instead, where it would
    quietly be something else.

    ``model`` is this run's own model, picked for this run alone, which wins
    over the pick on the Models page and changes nothing for any other run
    (Petar, 6 October 2026). ``use`` is a Models page pick of its own to read
    instead of the engine's, as the nightly feature run's is
    (`modeldefaults.USES`, "nightly_feature_run"). ``one_fields`` are what
    else the one program is told about the run, such as the nightly run's
    "signups" and "browser_port" (`one/rules.py`); a run that has any can only
    be a run of the program.

    A run for the person's own work begins with their standing rules, read
    from the Rules page as it starts (`for_the_person`, `rouh/rules.py`).
    ``standing_rules`` says so for a run whose preset alone would not, as the
    nightly feature run's night does; False keeps them out.

    ``made_by`` is the process of Rouh's starting it, "process:<name>", and
    "" the person's own words; left out, it is whatever the code starting it
    is making (`task_origin.making`). It is kept on the run, and the steps the
    run brings in when it lands are that process's (`task_origin.mark_run_work`).

    ``boxes`` is what `boxes.for_job` gave for the boxes the person handed this
    run: a one-time key and each box's number and name, never what is in it. A
    run of the program collects them with the key as it starts; a worker here is
    written them by Rouh as it is made (`crew.spawn`). Either way the brief
    already says where they are, and the grant is tied to the run's id here.

    ``asked_for`` is the request as the tool was given it, before anything was
    added to it. When it names Codex, an OpenAI model such as Astra, or OpenAI as
    the model to use, and no agent was chosen on purpose (``agent_chosen``, which
    is the tool's agent "claude" or "codex" said out loud), the run is Codex on the
    ChatGPT subscription, with that model, and its record says which word did it
    (`rouh/codex_route.py`, Petar, 9 November 2026). A model of OpenAI's named for
    the run with no agent chosen is Codex too.
    """
    from . import task_origin

    made_by = task_origin.run_maker(made_by)
    brief = str(brief or "").strip()
    if not brief:
        raise CannotStart("There was nothing to do, so nothing was started.")
    routed = route_to_codex(asked_for, agent=agent, agent_chosen=agent_chosen, model=model)
    if routed is not None:
        agent, model = "codex", model or routed.model
        log.info("starting as Codex%s: the request named %r",
                 f" on {model}" if model else "", routed.word)
        brief = f"{brief}\n\n{routed.line()}"
    from .config import OPENAI_CHOICES, ANTHROPIC_CHOICES

    if model:
        known = dict(OPENAI_CHOICES if agent == "codex" else ANTHROPIC_CHOICES)
        if model not in known:
            raise CannotStart(f"Unknown model for {agent or 'claude'}: {model}. Nothing was started.")
    brief = with_its_task(brief, chat)
    if preset == "improve_myself":
        # Every run of gene therapy changes Rouh's code, and what it changes that a person sees goes
        # through a trial after its Playwright proof (`rouh/trials/`, Petar, 4 November 2026). While the
        # person has paused testing it is built as before trials existed, told only to say so (6 November).
        from . import trials

        stage = await asyncio.to_thread(trials.stage_section, brief)
        if stage:
            brief = brief + "\n\n" + stage
    if preset in ("improve_myself", "delegate_task"):
        # Anything a person sees is designed by the design standard, in two tiers, one direction, and
        # landing checks its record (`rouh/design_standard.py`, Petar, 7 November 2026, task 169).
        from . import design_standard

        stage = design_standard.stage_section(brief)
        if stage:
            brief = brief + "\n\n" + stage
    # A task Rouh made a moment ago, in the turn that is starting this, is on
    # its way to main (`rouh/saving.py`), and the run's checkout is made from
    # main. Waiting for it here is what puts the task in that checkout.
    await asyncio.to_thread(saving.wait, SAVE_WAIT)
    spec = PRESETS.get(preset)
    where = resolve(preset, workspace=workspace, policy=policy, mode=mode, repo=repo)
    said = (str(title or "").strip() or brief.splitlines()[0])[:80]
    asked = brief
    # The task this run is for, when it is one task's: its record follows the
    # agent instructions every run starts with (`rouh/agent_instructions.py`).
    in_play = await asyncio.to_thread(_task_in_play, chat, owner)
    if standing_rules if standing_rules is not None else for_the_person(spec, where, workspace):
        brief = await asyncio.to_thread(
            _with_rules, brief, chat, owner[1] if owner and owner[0] == "task" else "")

    run_id = ""
    took = ""
    note = ""
    billed = "api" if billing == "api" and agent == "codex" else ""
    if agent == "codex" or billed or one_fields or _the_program_first(spec, where["policy"]):
        # Each engine its own pick on the Models page (`modeldefaults.USES`).
        use = use or ("codex_runs" if agent == "codex" else "code_runs")
        if model:
            # A model of its own thinks at its own level, as every model does.
            from . import modelstandard

            work = modeldefaults.Pair(model, modelstandard.effort(model))
        else:
            work = await asyncio.to_thread(modeldefaults.use_pair, use, org_id or None, cfg)
        model = work.model
        run_id = await _ask_the_program(one, brief, said, where, agent, expects, work,
                                        billing=billed, extra=one_fields, task=in_play,
                                        boxes=boxes)
        if run_id:
            took, note = ONE, (spec.note_one if spec is not None else "")
        elif one_fields:
            raise CannotStart("This run can only be a run of the one program, and the program "
                              "would not take it. Nothing was started.")
    if not run_id and agent == "codex":
        raise CannotStart("The one program could not start Codex. Nothing was started.")
    if not run_id:
        if where["policy"] == ONE:
            raise CannotStart(
                "The one program is not there, and a run under its own rules can only "
                "be one of its runs. Pick another policy to run it here instead.")
        run_id = await _ask_the_crew(crew, brief, said, where, expects, cfg, in_play=in_play,
                                     boxes=boxes)
        took, note = where["policy"], (spec.note_crew if spec is not None else "")

    if boxes:
        from . import boxes as _boxes

        await asyncio.to_thread(_boxes.started, boxes["grant"], run_id)
    kind = runs.kind_of(preset=preset, space=where["space"], policy=took,
                        workspace=where["path"])
    written = _write_it_down(run_id, brief=asked, title=said, policy=took,
                             where=where, agent=agent, chat=chat, owner=owner, kind=kind,
                             made_by=made_by, model=model)
    # The owner's own words behind it, exactly as said, so what it does for them is judged
    # against what they asked for rather than put back to them (`rouh/his_word.py`).
    from . import his_word

    await asyncio.to_thread(lambda: his_word.keep(run_id, his_word.words_now(chat)))
    if took != ONE:
        # A worker here (`rouh/events.py`). A run of the program is told by its feed,
        # which sees every run, however it was started (`OneFeed.on_runs`). A preset is
        # a tool of Rouh's model asking; the Start box has none and is the person.
        events.started("job", run_id, actor="rouh" if spec is not None else "person",
                       source="server", chat_id=chat, owner=True,
                       props={"preset": preset, "policy": took, "agent": agent or "claude"})
    # And where what it finishes with will be said, for the model that asked
    # for it. The Start box has no preset and no model reading its answer.
    if spec is not None:
        note = " ".join(x for x in (note, reported_where(chat)) if x)
    if emit is not None:
        await emit({"type": "task", "id": run_id, "status": "starting", "title": said,
                    "detail": spec.detail if spec is not None else "started",
                    "mode": took, "kind": kind, "model": model, "agent": agent or "claude"})
    return {"id": run_id, "status": "starting", "title": said, "mode": took,
            "model": model, "agent": agent or "claude",
            "workspace": written["workspace"], "policy": took, "kind": kind,
            "note": note or "It is on the orb and on the Metabolism page."}


def route_to_codex(asked_for: str | None, *, agent: str = "", agent_chosen: bool = False,
                   model: str = ""):
    """The word that makes this run Codex, as `codex_route.Named`, or None.

    Explicit Claude keeps a model mentioned as the subject from routing the run.
    Explicit Codex still infers its model from the request when none was passed.
    A model named for the run that is OpenAI's makes it Codex as well, since Claude Code
    cannot be one.
    """
    if (agent_chosen and agent != "codex") or (agent and agent != "codex"):
        return None
    from . import codex_route
    from .config import is_openai

    if model and is_openai(model):
        return codex_route.Named(model, model)
    if model:
        return None
    return codex_route.named(asked_for or "")


#: Where what a run finishes with is said, as the model that started it is told.
REPORTED_HERE = ("What it finishes with comes back to this conversation by itself, "
                 "and you are told so you can say it.")
REPORTED_ON_THE_RUN = (
    "It was started from no conversation, so what it finishes with is not said here: "
    "it stays on its own run, and the Metabolism page marks it for them when it is done. Do "
    "not say you will tell them when it is done.")


def reported_where(chat: str) -> str:
    """The sentence that tells the model where a run it started will report.

    A run started from a conversation reports back into it, General included
    (`runs.report_chat`; Petar, 12 October 2026: "when the run completes the
    chat receives the report"). Only a run started from no conversation, or
    from a chat a heartbeat beats in, keeps its report on its own run, so the
    model must not promise to come back with the result then: nothing would.
    """
    return REPORTED_HERE if runs.hears_back(chat) else REPORTED_ON_THE_RUN


def _the_program_first(spec: Preset | None, policy: str) -> bool:
    """Whether the one program is asked before a worker here is.

    Always when the policy asked for is the program's own rules, because there
    is nowhere else those rules exist. Otherwise when the preset says this is
    work that belongs there, for the policy it ended up with.
    """
    if policy == ONE:
        return True
    if spec is None:
        return False
    return not spec.one_if_policy or policy in spec.one_if_policy


async def _ask_the_program(one: Any, brief: str, title: str, where: dict,
                           agent: str, expects: Sequence[str],
                           work: modeldefaults.Pair | None = None, *,
                           billing: str = "", extra: dict | None = None, task: str = "",
                           boxes: dict | None = None) -> str:
    """The one program, or an empty string when it would not or could not take it.

    A run is told the model its tier on the Models page says (`work`, the use
    "code_runs" or "codex_runs"), and the level that comes with that model.

    A Codex run cannot fall back to another worker or model. Its refusal is
    returned unchanged to the caller.
    """
    if one is None or not one.configured():
        if billing:
            raise CannotStart("A run of Codex billed to the OpenAI API key can only be a run "
                              "of the one program, and it is not there. Nothing was started.")
        return ""
    fields: dict[str, Any] = {"brief": brief, "title": title}
    if where["space"] and where["space"] != "assistant":
        fields["space"] = where["space"]
    if agent:
        fields["engine"] = agent
    if work is not None and agent in ("", "claude"):
        fields["model"] = work.model
        fields["effort"] = work.effort
    elif work is not None and agent == "codex" and work.model:
        fields["model"] = work.model
        if work.effort:
            fields["effort"] = work.effort
    if billing:
        fields["billing"] = billing
    if expects:
        fields["expects"] = list(expects)[:40]
    if task:
        fields["task"] = task
    fields.update(extra or {})
    if boxes:
        # The key and the boxes' numbers and names; what is in them the program collects
        # from Rouh itself as the run starts (`one/runs.py`, `_hand_boxes`).
        fields["boxes"] = {"key": boxes["key"],
                           "boxes": [{"number": b["number"], "name": b["name"]}
                                     for b in boxes["boxes"]]}
    try:
        got = await one.ask("start", **fields)
    except Exception as exc:
        if agent == "codex":
            raise CannotStart(str(exc)) from exc
        if billing:
            raise CannotStart(f"The one program would not start it billed to the OpenAI API "
                              f"key: {exc} Nothing was started.") from exc
        log.warning("the one program did not take the job (%s)", exc)
        return ""
    return str((got or {}).get("run") or "")


async def _ask_the_crew(crew: Any, brief: str, title: str, where: dict,
                        expects: Sequence[str], cfg: Any, *, in_play: str = "",
                        boxes: dict | None = None) -> str:
    """A worker here, under the policy asked for, written the boxes it was handed."""
    if crew is None:
        raise CannotStart(
            "There is nothing on this machine to run it: no worker layer and no one "
            "program. Nothing was started.")
    spec: Preset | None = where["preset"]
    composed = brief
    if spec is not None and spec.compose:
        # The standing rules stay at the very start, in front of the
        # workspace's own words, as they are for a run of the program.
        from . import rules

        asked = rules.unruled(brief)
        composed = brief[:len(brief) - len(asked)] + spec.compose(asked)
    given: list[dict] = []
    if boxes:
        from . import boxes as _boxes

        try:
            given = await asyncio.to_thread(_boxes.collect, boxes["key"], "")
        except _boxes.NotCollected as exc:
            raise CannotStart(f"Its boxes could not be handed over: {exc} Nothing was started.") from exc
    try:
        mate = await crew.spawn(
            task=composed,
            repo=where["path"] or None,
            mode=where["policy"],
            title=title,
            profile=where["profile"] or None,
            expects=list(expects) or None,
            in_play=in_play or None,
            **({"secrets": given} if given else {}),
        )
    except Exception as exc:
        if boxes:
            from . import boxes as _boxes

            await asyncio.to_thread(_boxes.ended, grant=boxes["grant"], how="not started")
        raise CannotStart(f"It could not be started here: {_boxes_out(str(exc), given)}") from exc
    finally:
        given.clear()
    return str(mate.id)


def _boxes_out(text: str, given: list[dict]) -> str:
    """An error's words with nothing a box held in them."""
    if not given:
        return text
    from . import boxes as _boxes

    return _boxes.redact(text, [(g["number"], g["content"]) for g in given])


def _write_it_down(run_id: str, *, brief: str, title: str, policy: str,
                   where: dict, agent: str, chat: str,
                   owner: tuple[str, str] | None, kind: str = "", made_by: str = "",
                   model: str = "") -> dict:
    """The row, and the two links, at once - so the run exists before anything asks.

    The workspace written here is the one this call resolved: the space when a
    run of the program took it, the path when a worker did. Both feeds write
    the same field from the same fact afterwards, so nothing can drift.

    `kind` is which half of Metabolism it is on (`runs.kind_of`), decided here
    because only here is the tool that started it known. The feeds only ever
    fill it in where it is empty, so they never overrule it.
    """
    workspace = where["space"] if policy == ONE else (where["path"] or "")
    runs.record(run_id, title=title, brief=brief[:4000], workspace=workspace, model=model,
                policy=policy if policy in objects.POLICIES else "safe",
                agent=agent if agent in objects.AGENTS else "claude",
                state="running", phase="starting", first=True,
                **({"kind": kind} if kind in objects.RUN_KINDS and kind else {}))
    if made_by:
        # Which process started it (`rouh/task_origin.py`), on its row beside the rest.
        from .models import Run as RunRow

        with contextlib.suppress(Exception):
            RunRow.objects.filter(id=run_id).update(made_by=made_by)
    st = owning.store()
    if st is not None:
        if chat:
            # Which conversation asked for it, written down while somebody
            # still knows: by the time it finishes the person is looking at
            # something else, and this is what sends its report back to where
            # it was asked for rather than into the middle of whatever is on
            # the screen then (`runs.chat_of`).
            #
            # **And that is the whole of what a run does to the chat it came
            # from.** Until 22 September 2026 a loose conversation with a run
            # started in it was given a task number here, on the reasoning
            # that starting work is the person saying it matters. The person's
            # rule is the other way round: a chat stays a chat until they ask
            # for a task to be made out of it, and starting a run is not that
            # asking (`conversations.promote`).
            runs.came_from(run_id, chat)
        if owner:
            got = owning.attach("run", run_id, owner[0], owner[1])
            if not got.get("ok"):
                log.warning("run %s could not be attached: %s", run_id, got.get("why"))
    return {"workspace": workspace}


def as_json(started: dict) -> str:
    """What a tool hands back to the model: the id, and one line about it.

    The workspace is on it even when it is empty, because empty is an answer -
    a job with no repository of its own gets a scratch directory - and because
    the workspace and the policy are the two fields that tell one run from
    another. A field with nothing in it at all is left out.
    """
    return json.dumps({k: v for k, v in started.items()
                       if v is not None and (v != "" or k == "workspace")})


# ---------------------------------------------------------------------------
# A job that died, started again
# ---------------------------------------------------------------------------

#: Which of the surface names a worker of the crew was started under, read off
#: its row. The two fields that make them different are on every row: the
#: assistant's jobs run under the `assistant` profile, and a change to Rouh
#: itself runs under the `self` policy. Everything else is `delegate_task`.
KIND_WORDS = {
    "assistant_job": "A job in your workspace",
    "improve_myself": "A change to Rouh itself",
    "delegate_task": "A job on this server",
}

#: The restarts in flight, by the id of the job being restarted. Two presses of
#: one Restart button - a double click, or the same card in two tabs - start
#: one job, not two: the second finds the first here, or finds `restarted_as`
#: on the row once the first has finished.
_restarting: set[str] = set()


def kind_of(mate: Any) -> str:
    """`assistant_job`, `improve_myself` or `delegate_task`, for a crew row."""
    meta = mate.get("meta") or {}
    if isinstance(meta, dict) and meta.get("profile") == "assistant":
        return "assistant_job"
    if str(mate.get("mode") or "") == "self":
        return "improve_myself"
    return "delegate_task"


def restartable(mate: Any) -> bool:
    """Whether this job can be started again from its card: it died, and it
    has not already been started again."""
    meta = mate.get("meta") or {}
    return (str(mate.get("status") or "") == "lost"
            and not (isinstance(meta, dict) and meta.get("restarted_as")))


async def restart(run_id: str, *, crew: Any, emit: Callable | None = None) -> dict:
    """The same job again, as a fresh job with a new id, for a job that died.

    Petar asked for it on 24 September 2026: a card that says a job died has a
    Restart button, and pressing it starts the same job with the same brief,
    of the same kind, with the same files hint. So it is exactly the worker the
    first one was - the same instruction as it was handed over, the same
    checkout it was made from, the same policy and profile, the files it said
    it would touch - started the way `assistant_job` already redoes a job whose
    work collided (`_redo` there). What is new is only the id.

    Everything that pointed at the dead job follows it: the conversation that
    asked for it hears the new one's report, and the task it was filed under
    owns the new one. The dead job is marked with the new id and put away, so
    its card is replaced by the new job's rather than left beside it.

    Returns what `start` returns, with `restarted` set to the dead job's id, or
    `already` when it had been restarted before. Raises `CannotStart` with the
    sentence to say when it cannot be.
    """
    run_id = str(run_id or "").strip()
    if crew is None:
        raise CannotStart("There are no background workers on this machine, so there is "
                          "nothing to restart it with.")
    mate = crew.get(run_id)
    if mate is None:
        raise CannotStart("That job is not on record any more, so it cannot be restarted.")
    meta = mate.meta or {}
    if meta.get("restarted_as"):
        return {"id": meta["restarted_as"], "already": True, "restarted": run_id}
    if mate.status != "lost":
        raise CannotStart("Only a job that died can be restarted, and this one did not.")
    # Checked and taken before anything is awaited, so two presses cannot both
    # get past it.
    if run_id in _restarting:
        return {"id": "", "already": True, "restarted": run_id}
    _restarting.add(run_id)
    try:
        task = mate.task
        if kind_of(mate) == "assistant_job":
            # The person's own work starts again with their rules as they are
            # now, not as they were when it first started.
            task = await asyncio.to_thread(_with_rules, task, runs.chat_of(run_id), "")
        try:
            fresh = await crew.spawn(
                task=task,
                repo=mate.repo or None,
                mode=mate.mode,
                title=mate.title,
                profile=meta.get("profile") or None,
                expects=meta.get("expects") or None,
                in_play=meta.get("in_play") or None,
            )
        except Exception as exc:
            raise CannotStart(f"It could not be started again: {exc}") from exc
        new_id = str(fresh.id)
        owner = owning.owner_of("run", run_id)
        _write_it_down(new_id, brief=runs.request_of(mate.task), title=mate.title, policy=mate.mode,
                       where={"space": "", "path": mate.repo or ""}, agent="claude",
                       chat=runs.chat_of(run_id),
                       owner=(owner["type"], owner["id"]) if owner else None)
        crew.set_meta(new_id, restart_of=run_id)
        crew.set_meta(run_id, restarted_as=new_id)
        try:
            await crew.archive(run_id, True)
        except Exception:
            log.exception("job %s was restarted as %s and could not be put away", run_id, new_id)
        log.info("job %s died and was restarted as %s", run_id, new_id)
    finally:
        _restarting.discard(run_id)
    if emit is not None:
        await emit({"type": "task", "id": new_id, "status": "starting", "title": mate.title,
                    "detail": "started again", "mode": mate.mode})
    return {"id": new_id, "status": "starting", "title": mate.title, "mode": mate.mode,
            "kind": kind_of(mate), "restarted": run_id}


async def about(run_id: str, *, crew: Any) -> dict | None:
    """One of Rouh's own jobs, as its page on the canvas shows it, or None.

    What it was asked, what kind of job it is, how it ended - and for a job
    that died, what it died of, which `crew.death_of` wrote on its row when it
    was found dead - what it printed, and whether it can be started again.
    """
    if crew is None:
        return None
    mate = crew.get(str(run_id or ""))
    if mate is None:
        return None
    meta = mate.meta or {}
    log_text, log_path = await crew.printed(mate)
    kind = kind_of(mate)
    return {
        "id": mate.id,
        "title": mate.title,
        "status": mate.status,
        "mode": mate.mode,
        "kind": kind,
        "kind_words": KIND_WORDS.get(kind, ""),
        "brief": mate.task,
        "created_at": mate.created_at,
        "finished_at": mate.finished_at,
        "exit_code": mate.exit_code,
        "branch": mate.branch,
        "repo": mate.repo,
        "expects": list(meta.get("expects") or []),
        "death": meta.get("death") or None,
        "closing": meta.get("closing") or "",
        "restarted_as": meta.get("restarted_as") or "",
        "restart_of": meta.get("restart_of") or "",
        "restartable": restartable(mate),
        "log": log_text,
        "log_path": log_path,
    }
