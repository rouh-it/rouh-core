"""Agent brief templates and composition, independent of run lifecycle handling."""
from __future__ import annotations

import os
import shutil

from rouh import attachments, browser_handoff

from .engines import DEFAULT_ENGINE, ENGINE_WORDS


# ---------------------------------------------------------------------------
# Whose machine it is
# ---------------------------------------------------------------------------

#: What a run is told about the machine it runs on. On a server of its own the
#: run's user may use sudo; in Rouh's containers (deploy/stack/compose.yml) the
#: worker has no sudo at all, and reaches the person's own servers only by ssh,
#: through the key proxy, to the ones the stack's settings let through
#: (ROUH_KEYPROXY_ALLOW, CONTAINERS.md runs.ssh), each set up as a Host of its
#: own in the worker's ~/.ssh/config. Until 1 November 2026 every brief said
#: "which may use sudo", which had been false since the move into the containers.
SSH_HOSTS = ("The person's own servers are reached by ssh, through Rouh's key proxy, and only the ones "
             "its settings let through: `grep -A4 '^Host ' ~/.ssh/config` lists the ones set up, each "
             "with its key and user, so `ssh <that name>` is all it takes. Where a server is set up with "
             "root, that root is yours to use for the work, with the same care.")


def machine_words(user: str) -> dict:
    """`machine`, a whole sentence, and `as_user`, a phrase, for the brief: sudo when the run has it."""
    if shutil.which("sudo"):
        return {"machine": f"You work as the Linux user `{user}`, which may use sudo, so you can also change "
                           "anything on this server, where Rouh, the one program and the person's websites "
                           "run too. Never edit `/var/www/rouh/app` or `/srv/one/app`: those are the copies the "
                           "two services run from, and a deploy overwrites them.",
                "as_user": f"as the Linux user `{user}`, which may use sudo"}
    return {"machine": f"You work as the Linux user `{user}` in Rouh's worker container, with no sudo: nothing "
                       "of this machine outside your checkout and the worker's home is yours to change. "
                       "The code the live Rouh and the one program run is `/code`, read-only here; it changes only "
                       "by landing your checkout. There is no systemd here and no `/var/www/rouh`: a server's "
                       "commands for those (`systemctl`, `systemd-run`, `deploy/with-rouh-env.sh`) do not work, "
                       "and the worker cannot reach Rouh's database, so ask Rouh's own tools for what is in it. "
                       + SSH_HOSTS,
            "as_user": f"as the Linux user `{user}` in Rouh's worker container, with no sudo"}


# ---------------------------------------------------------------------------
# The brief
# ---------------------------------------------------------------------------

WORKSPACE_BRIEF = """{request}

---

## Where this came from

The person asked for this through the one program, from their {surface}, instead of typing it to you in a terminal. You are their assistant and this is their workspace, so handle it exactly as you would in the terminal, under the agent instructions you were given before this message. Where they call for them, that includes the task and step folders, testing, the task's AGENTS.md, its status and its summary, and the commit. A task's status and summary are kept in Rouh's database and nowhere else: change them with `rouh-task status <number> <status>` and `rouh-task summary <number> "<50 to 90 words>"`, run from inside the workspace, never in a file and never in `_tasks.md`, which Rouh generates from its database. A task's steps, groups, arrows, tags and question are its meta, also kept in Rouh's database: see it with `rouh-task meta <number>` and change it with `rouh-task meta <number> merge '<JSON>'`. If `rouh-task` says it could not reach Rouh, say so in your last message rather than writing either anywhere else.

{where_it_is} It is a tree: Work and Personal are projects at the top, each category is a project inside one of them, and a task sits under the project that owns it, so a task is `{ws}work/acme/19.pricing` rather than `tasks/19.pricing`. `{ws}README.md` says what the shape is; the agent instructions at the start of your instructions, which Rouh keeps in its database and gives every run as it starts, are the rules you work under; `{ws}_migration-map.json` and each folder's `.object.json` say what every object is. A `.md` you write is shown by its file name and never by the heading inside it, so name it for what is in it, in a few plain words after its step's number: `61-01.site-plan-and-homepage-copy.md`, never `61-01.notes.md`. {the_code}

## How this run works

- You are run `{run_id}`, in your own checkout at `{cwd}`, on the branch `{branch}`. Nothing you do here touches anyone else's work.
- {machine} Before anything that cannot be undone, such as deleting data, or that interrupts something in use, such as restarting a service, look for a gentler way first, and say exactly what you changed.
{rules}
- The person can take over this terminal at any time and hand it back. If they do, you will be told what they did.
- Commit everything you changed before you stop. When you stop, the program pushes your commits to main for you; you may push yourself when that is the job, and you never wait for anybody to approve it.
- Never end your work with a question for the person, and never put one in a task's meta, unless the work they asked for has truly stopped without them and the answer is theirs to give: it spends money, sends or publishes in their name, cannot be undone, or needs a fact only they have. Otherwise choose yourself and end with your recommendation, on the step's page, in the task's AGENTS.md and in your last message. Research ends with a recommendation, never with "buy now or later?" or "which direction?". Rouh keeps any other question from them.
- Other runs save to main while you work. Just before you commit, run `git fetch origin main`. If the step number you picked is now taken on `origin/main` (`git ls-tree --name-only origin/main {ws}<the task's folder>/` lists its steps), take the next free number, and change every reference to it before you commit.

{finishing}
## Your last message

If you made a page, the first line of your last message names it, exactly like this:

PAGE: work/acme/19.pricing/19-04.packages/index.html

which is the page's path inside the workspace.

Then say plainly what you did or what you found, in two or three sentences. It is shown on every screen and may be read out loud.
"""

SCRATCH_BRIEF = """{request}

---

## How this run works

- You are run `{run_id}` of the one program, working in the folder `{cwd}`, which is yours alone.
{rules}
- The person can take over this terminal at any time and hand it back. If they do, you will be told what they did.

When you finish, say plainly what you did or found, in two or three sentences.
"""

#: Work in a repository added as a space (D42), Rouh's own code among them:
#: the run's own checkout of it, whose commits are saved when it stops.
CODE_BRIEF = """{request}

---

## Where this came from

The person asked for this through the one program, from their {surface}. It is work in the repository `{space}`.

## How this run works

- You are run `{run_id}`, in your own checkout of `{space}` at `{cwd}`, on the branch `{branch}`, made from `{target}`. Follow the repository's own AGENTS.md, CLAUDE.md or README.
{rules}
- The person can take over this terminal at any time and hand it back. If they do, you will be told what they did.
- Prove the change yourself before you commit, the way the repository's own AGENTS.md or CLAUDE.md says, and commit once you have, with a message that says what changed and why.
- {saving}
{approval}- Never end your work with a question for the person unless the work they asked for has truly stopped without them and the answer is theirs to give: it spends money, sends or publishes in their name, cannot be undone, or needs a fact only they have. Otherwise make the sensible choice yourself and say in your last message which choice you made and why.
- Anything you leave uncommitted is not saved. If you cannot get the change right, do not commit: say what is wrong and what you would need.
{note}
{finishing}
## Your last message

Say what you did, in plain language, in two or three sentences, and name what was pushed and where, and what was deployed. It is shown on every screen and may be read out loud.
"""


#: The person's standing policy on finishing, said in so many words to every
#: run whose work is saved to a branch.
#:
#: Written on 19 September 2026. Run 8921e843 was asked to merge a branch into
#: main and deploy it. It did the merge, checked it was clean, and then stopped
#: and said it was waiting for approval before pushing - so the work sat on a
#: branch and nothing went live. There was no approval coming, because there is
#: no approval step: "a change is only done when it is committed, merged to
#: main AND deployed", and a run that waits for a person has not finished the
#: job it was given.
PUSH_AND_DEPLOY = (
    "- **Nobody approves your work, and you never wait for anybody.** Pushing and deploying "
    "need no permission from anyone: once you have proved your change, work going to `{target}` and being "
    "deployed from there is what the person has already decided. Never end a turn asking "
    "whether you may push, merge or deploy, and never leave finished work on a branch for "
    "somebody to merge later. If merging, pushing or deploying is the job, do it yourself.\n")


#: What every run that saves work to a branch is told about finishing, and the
#: whole of the person's standing policy on it: the run proves its own change,
#: commits it, and the change goes to main and is deployed from there without
#: anybody being asked first. So a run that stops short of committing has not
#: delivered anything at all, however good its last message reads.
#:
#: Written on 17 September 2026, after run 8109f4b5 wrote a whole fix to
#: Rouh, ended its turn saying "Waiting on the `rouh/` suite" while pytest
#: was still going, and was closed three minutes later with every file of that
#: fix uncommitted.
FINISHING = """## Finishing

Your work only exists if it is committed. {where} Nobody approves it on the way, and there is no step at which you wait for a person to say yes. Nothing you leave uncommitted is saved: it goes with your checkout.

So, in this order, every time:

1. **Wait for every command you started.** If something you started is still going, wait for it, however long it takes, and read its result. Never end a turn while a command is still running. "Waiting on it" is not a finish; it is the middle of one.
2. **Commit.** Once your own checks pass, commit everything you changed, with a message that says what changed and why.
3. **Say so.** Your last message says what you checked and what it said, what you committed, what was pushed and to where, and what was deployed. Only the deployed commit counts: if the landing says the work is on the target and not live, say that plainly and say the reason it gave, and do not call it done.

If a check cannot finish, or will not pass, say that plainly and say what you would need. That is a proper finish too, and a far better one than a report of work that is about to be thrown away. What you must never do is report that you are done while anything is uncommitted.
"""


#: Where a finished run's commits go, in the sentence the checklist opens with.
#: Straight to the branch everything is deployed from, or up on the run's own
#: branch for a person to merge.
FINISHED_TO_MAIN = ("The program lands your commits on `{target}` when your turn ends, through "
                    "`./land.sh`, which pushes and then deploys what it pushed, without the "
                    "person being asked first and without you waiting for anybody. It does not "
                    "call that done until both services answer with the commit it pushed, so "
                    "read what it says: a change that is on `{target}` and not live is not "
                    "done, and is never reported as done. If your work collides with something "
                    "that landed while you worked, you are handed both sides and asked to "
                    "reconcile them yourself; nothing is lost either way.")
FINISHED_ON_BRANCH = ("The program pushes your commits on your own branch, for a pull request "
                      "into `{target}` that the person merges.")
FINISHED_TO_WORKSPACE = ("The program lands your commits on `main` when your turn ends, through "
                         "`land.sh`, which is the only thing here allowed to push. A commit "
                         "that moves only `workspace/` restarts neither service, because nothing "
                         "runs what is in there; a commit that touches anything else is deployed. "
                         "Either way what you committed is what the person and Rouh read from "
                         "then on.")
#: The same, for a checkout that is the workspace and nothing else (21 October 2026).
FINISHED_IN_WORKSPACE = ("The program lands your commits on `main` of the workspace when your turn "
                         "ends, through `land.sh`, which is the only thing here allowed to push, "
                         "and moves the live workspace onto them: nothing restarts, because "
                         "nothing runs what is in it, and what you committed is what the person "
                         "and Rouh read from then on. Work in Rouh's own code is its own checkout "
                         "and its own landing, as above.")

#: Where the workspace is, said two ways: the whole of the checkout, which is
#: how it is since it became a repository of its own on 21 October 2026, or
#: `workspace/` inside a checkout of Rouh's code, which is how it was from 21
#: September and how a checkout made before the split still holds it.
WORKSPACE_IS_THE_CHECKOUT = ("This checkout is the person's workspace: a repository of its own, "
                             "with nothing of Rouh's code in it.")
WORKSPACE_IN_THE_CHECKOUT = ("The workspace is `workspace/` inside this checkout, which is a checkout "
                             "of Rouh's own code as well.")
CODE_ELSEWHERE = ("Rouh's and the one program's own code is a separate repository, which this "
                  "checkout does not hold. If the work changes it, make a checkout of your own "
                  "beside this one - `git -C {code_repo} fetch origin main && git -C {code_repo} "
                  "worktree add -b one/<what-it-is>-{run_id} {cwd}-code origin/main` - work and "
                  "prove the change there the way that repository's AGENTS.md says, and land it "
                  "from there with its `./land.sh`, which deploys it; say what it said. Commit "
                  "only the workspace's own files here.")
CODE_HERE = ("Everything outside `workspace/` in this checkout is Rouh's and the one program's "
             "own code, under the repository's own AGENTS.md, and a change there is proved the "
             "way that file says.")


def workspace_layout(cwd: str, code_repo: str = "", run_id: str = "") -> dict:
    """What the workspace brief says about where things are, for this checkout."""
    if os.path.isfile(os.path.join(cwd or "", "_migration-map.json")):
        return {"ws": "", "where_it_is": WORKSPACE_IS_THE_CHECKOUT,
                "the_code": CODE_ELSEWHERE.format(code_repo=code_repo or "/srv/spaces/rouh",
                                                  run_id=run_id or "<run>", cwd=cwd),
                "finished": FINISHED_IN_WORKSPACE}
    return {"ws": "workspace/", "where_it_is": WORKSPACE_IN_THE_CHECKOUT,
            "the_code": CODE_HERE, "finished": FINISHED_TO_WORKSPACE}


#: How a repository's work is saved, as its runs are told (D42). Until 19
#: September 2026 both of these opened with "Do not push", which a run asked to
#: push read as a rule against the job it had been given.
SAVED_TO_MAIN = ("When your turn ends the program lands your commits on `{target}` for you, "
                 "through `./land.sh`, which is the only thing here allowed to push: it replays "
                 "your work over whatever landed there while you worked, one job at a time, "
                 "pushes it, and then deploys it and waits for the machine to be serving the "
                 "commit it pushed. Landing includes deploying, and only the deployed commit "
                 "counts as done. You may run `./land.sh` yourself when that is what the job "
                 "is: nothing refuses you. Never `git push` to `{target}` by hand - that is what "
                 "loses a collision instead of resolving it.")
SAVED_ON_BRANCH = ("When your turn ends the program pushes your branch `{branch}` for a pull "
                   "request into `{target}`, which the person merges. Open the pull request "
                   "yourself if the job asks for one: nothing refuses you.")

#: Work in a folder already on the server, added as it is (D43): the run
#: works in it directly, like a terminal, and nothing is saved for it.
FOLDER_BRIEF = """{request}

---

## Where this came from

The person asked for this through the one program, from their {surface}. It is work in the folder `{cwd}` on their server, the space `{space}`.

## How this run works

- You are run `{run_id}`, working directly in `{cwd}`, {as_user}. Other sessions may be working in this folder at the same time, as in a terminal.
{rules}
- The person can take over this terminal at any time and hand it back. If they do, you will be told what they did.
- Nothing is saved for you. If the folder is a git repository and your work should be committed or pushed, do that yourself, the way the folder's own AGENTS.md, CLAUDE.md or README says.

## Your last message

Say plainly what you did or what you found, in two or three sentences. It is shown on every screen and may be read out loud.
"""

#: What only a run in Rouh's own code is told.
ROUH_NOTE = ("- This is Rouh's own code. There are no committed tests in it and no suite to "
               "run: you prove your own change, with a real browser over Playwright MCP and a "
               "check of your own that you run and do not commit, and nothing you did not change "
               "is re-checked. `AGENTS.md` there says how. The live Rouh runs from another copy, so nothing "
               "here changes it until it is deployed. You do not have to deploy or restart "
               "Rouh yourself, and you never have to ask: the moment your work is on main "
               "Rouh deploys onto it by itself and writes down what it deployed, so "
               "committing is the whole of what you have to do for it to go live. That deploy "
               "is both services on the server - this program and Rouh, onto the same commit, "
               "through `update-all.sh` - so a change anywhere in this repository goes live "
               "everywhere it belongs.\n")

FINISH_THE_WORK = """You have ended your turn with changes in this checkout that were never committed, so the program has nothing to save and nothing of this run's work would reach `{target}`. Anything left uncommitted goes when the checkout goes.{waiting}

Finish it now:

1. If a command you started is still running, wait for it and read its result. Do not end another turn while one is running.
2. Prove the change if you have not, the way the repository's own AGENTS.md or CLAUDE.md says, and fix what is wrong.
3. Once it is right, commit everything you changed, with a message that says what changed and why. The program pushes your commits to `{target}` when your turn ends; nobody has to approve that.

If the change will not come right, or a check cannot finish, leave the work uncommitted and say so plainly: what is wrong, and what you would need. Then stop. That is a proper answer, and it is the only reason to stop with anything uncommitted.

Your last message is what the person sees about this whole run. Say what you checked and what it said, what you committed, and anything you left undone.
"""

#: Nothing here writes the brief a run gets when its work clashes with main any
#: more. ``land.sh`` does, because it is the thing that knows what collided: it
#: hands back both sides, the file list, the branch that holds the work exactly
#: as the run wrote it, and the sequence for reconciling the intent rather than
#: the text (``rouh/conflicts.py``, ``handback``). Two templates saying nearly
#: the same thing was how a run came to be told to keep both sides of a conflict
#: whose two sides were answers to the same question.

#: The person's own session (stage 4): the agent on the server, typed to
#: from a terminal connected to it. There is no brief, so how
#: the run works is added to the agent's own instructions instead - on Claude
#: Code's command line, and for Codex as the answer to its SessionStart hook,
#: which is the only place Codex takes such a thing.
SESSION_BRIEF = """This is the person's own {agent} session, run `{run_id}` of the one program on their server. They type to you from a terminal connected to it.

- You are in your own checkout of their workspace at `{cwd}`, on the branch `{branch}`. Nothing you do here touches anyone else's work. {where_it_is} The person's own tasks, notes and pages are a tree of projects and tasks. {the_code}
- {machine} Take care with anything that cannot be undone, and say what you changed.
{rules}
- Commit what you changed before you finish each turn. When your turn ends the program pushes your commits to main for you, where every other copy takes them in; nobody has to approve that.
- Other runs save to main while you work. Just before you commit, run `git fetch origin main`. If the step number you picked is now taken on `origin/main`, take the next free number, and change every reference to it before you commit.
"""

SESSION_SCRATCH = """This is the person's own {agent} session, run `{run_id}` of the one program on their server, in the folder `{cwd}`, which is yours alone. They type to you from their terminal.
{rules}
"""

SESSION_CODE = """This is the person's own {agent} session, run `{run_id}` of the one program on their server, in their own checkout of the repository `{space}` at `{cwd}`, on the branch `{branch}`, made from `{target}`. They type to you from their terminal.
{rules}
- Prove the change yourself before you commit, the way the repository's own AGENTS.md or CLAUDE.md says, and commit only once you have.
- {saving} Anything left uncommitted is not saved. Nobody approves a push or a deploy: never wait for one.
- Never end a turn while something you started is still running: wait for it and read its result. If it cannot finish, say that plainly rather than reporting the work as done.
{note}"""


SESSION_FOLDER = """This is the person's own {agent} session, run `{run_id}` of the one program on their server, working directly in the folder `{cwd}`, the space `{space}`, {as_user}. They type to you from their terminal, and other sessions may work in this folder at the same time.
{rules}
- Nothing is saved for you: commit or push yourself when they ask, as in a terminal.
"""


def _code_parts(space: str, branch: str | None, target: str | None,
                flow: str | None) -> dict[str, str]:
    """What a run in a repository is told about saving, and about Rouh's own code."""
    target = target or "main"
    saving = (SAVED_ON_BRANCH if flow == "branch" else SAVED_TO_MAIN).format(
        branch=branch or "-", target=target)
    rouh = space == "rouh"
    return {"saving": saving, "target": target,
            "approval": PUSH_AND_DEPLOY.format(target=target),
            "note": ROUH_NOTE if rouh else "",
            "finishing": FINISHING.format(
                where=(FINISHED_ON_BRANCH if flow == "branch"
                       else FINISHED_TO_MAIN).format(target=target))}


def session_brief(*, space: str, run_id: str, cwd: str, branch: str | None,
                  access: str = "full", user: str = "",
                  target: str | None = None, flow: str | None = None,
                  engine: str = DEFAULT_ENGINE, code_repo: str = "") -> str:
    rules = _rules_for(access, engine)
    agent = ENGINE_WORDS.get(engine, ENGINE_WORDS[DEFAULT_ENGINE])
    if space == "assistant":
        layout = workspace_layout(cwd, code_repo, run_id)
        return SESSION_BRIEF.format(run_id=run_id, cwd=cwd, branch=branch or "-", user=user,
                                    rules=rules, agent=agent, **machine_words(user),
                                    where_it_is=layout["where_it_is"],
                                    the_code=layout["the_code"])
    if space == "scratch":
        return SESSION_SCRATCH.format(run_id=run_id, cwd=cwd, rules=rules, agent=agent)
    if flow == "in place":
        return SESSION_FOLDER.format(run_id=run_id, space=space, cwd=cwd, user=user, rules=rules,
                                     agent=agent, **machine_words(user))
    return SESSION_CODE.format(run_id=run_id, space=space, cwd=cwd, branch=branch or "-",
                               rules=rules, agent=agent,
                               **_code_parts(space, branch, target, flow))


#: What a run is told when it went down with the program, a deploy most often,
#: and was started again: it did nothing wrong, and its own landing may be
#: what deployed.
CARRIED_ON = ("Your process went down with the program ({why}). The program started "
              "you again, in the same conversation and the same checkout. Look at where the work "
              "stands - a landing you started may already have finished - then carry on.")

RESTARTED = ("Your process stopped unexpectedly and the program started it again, in the same "
             "conversation and the same checkout. Look at where the work stands, then carry on.")


#: What a run is told about the program's rules, by how much access it has.
RULES = {
    "full": "- You have full access: no tool call is refused and nobody is asked first. Every call is still written down.",
    "guarded": ("- The program checks every tool call before it runs. A refusal says why: do something else, or finish without it and say so.\n"
                "- A few things are asked of the person before they happen, such as sending data out of this machine. The run waits for the answer."),
}


#: What only a run of Codex is told, on top of the rest. A Claude Code run has
#: a second line behind the program's answers - the deny rules in its own
#: settings, which it enforces with no hook involved - and Codex has nothing of
#: the kind, so the same rules reach a Codex run only through its hooks.
CODEX_RULE = ("- You are Codex. The program decides your tool calls through Codex's hooks. A call "
              "it cannot be asked about, because it is not answering, is refused rather than "
              "allowed: if that happens, say so instead of trying another way round it.")


def _rules_for(access: str, engine: str) -> str:
    rules = RULES.get(access, RULES["guarded"])
    return f"{rules}\n{CODEX_RULE}" if engine == "codex" else rules


#: What a run given a job is told about email, because it cannot send any: no
#: mail on the server, no account to send from, and Rouh's own ``send_mail``
#: is Rouh's alone. Rouh's server, which every run is given with the machine's
#: MCP servers (mcp-servers.json), has one tool for it, and Rouh does the
#: sending (rouh/outbox.py); and it lends the run Rouh's own tools, with
#: Rouh's own logins (rouh/job_gateway.py). Rouh's crew tells its workers the same thing
#: (rouh/crew.py, MAIL_INSTRUCTION). A person's own session is not told: it
#: has the person at its terminal.
MAIL_RULE = ("- You cannot send email: this server has no mail and you have no account to "
             "send from, so never try with a command or look for credentials. If you are asked "
             "to email or message the person, call the notify_owner tool with a subject and the "
             "text. It queues them for Rouh, which says who it goes to, asks the person, and "
             "sends it from their own account after you finish. Say in your last message that "
             "you queued it. Anything that needs the person's or Rouh's accounts - mail and its "
             "files (mail_find, mail_file), calendar, Drive and Docs, contacts, Slack, "
             "meetings, memory - you do with the rouh server's tools: Rouh runs them with its "
             "own logins, so never say a job cannot get it, and never look for a login. A call "
             "that sends, shares, pays or deletes comes back pending, as a decision for the "
             "person: carry on. For anything no tool gives, call request_from_rouh with what "
             "you need, why and what you do meanwhile, and carry on with the rest of the work "
             "rather than stopping.")


#: What a run given a job is told about its browser: headless Playwright is
#: for work nobody watches, and a step that is the person's - a login, a code,
#: a captcha, a payment, a button that cannot be undone - is stopped at and
#: handed to Rouh's live browser in a statement Rouh knows
#: (`rouh/browser_handoff.py`). Rouh's crew tells its workers the same thing
#: (rouh/crew.py). A person's own session is told too: it may not be watching.
BROWSER_RULE = browser_handoff.WORKER_RULE

#: What a run started with ``signups`` is told instead: the nightly feature run
#: (`rouh/nightly_feature.py`), which Petar allowed on 6 October 2026 to sign
#: up for services and pay for them through Rouh's tools without asking.
SIGNUPS_RULE = browser_handoff.SIGNUPS_RULE


#: What a run given a job is told about a file it is handed: open it and look,
#: and if it will not open, ask rather than guess (`rouh/attachments.py`).
#: Rouh's crew tells its workers the same thing (rouh/crew.py).
FILES_RULE = attachments.WORKER_RULE


def compose_brief(request: str, *, space: str, surface: str | None, run_id: str, cwd: str,
                  branch: str | None, access: str = "full", user: str = "",
                  target: str | None = None, flow: str | None = None,
                  engine: str = DEFAULT_ENGINE, signups: bool = False,
                  code_repo: str = "") -> str:
    browser = SIGNUPS_RULE if signups else BROWSER_RULE
    rules = f"{_rules_for(access, engine)}\n{MAIL_RULE}\n{browser}\n{FILES_RULE}"
    if space == "assistant":
        layout = workspace_layout(cwd, code_repo, run_id)
        return WORKSPACE_BRIEF.format(request=request.strip(), surface=surface or "terminal",
                                      run_id=run_id, cwd=cwd, branch=branch or "-", user=user,
                                      rules=rules, ws=layout["ws"], **machine_words(user),
                                      where_it_is=layout["where_it_is"],
                                      the_code=layout["the_code"],
                                      finishing=FINISHING.format(where=layout["finished"]))
    if space == "scratch":
        return SCRATCH_BRIEF.format(request=request.strip(), run_id=run_id, cwd=cwd, rules=rules)
    if flow == "in place":
        return FOLDER_BRIEF.format(request=request.strip(), surface=surface or "terminal",
                                   run_id=run_id, space=space, cwd=cwd, user=user, rules=rules,
                                   **machine_words(user))
    return CODE_BRIEF.format(request=request.strip(), surface=surface or "terminal", run_id=run_id,
                             space=space, cwd=cwd, branch=branch or "-", rules=rules,
                             **_code_parts(space, branch, target, flow))


#: Named back to a run that left work uncommitted and also walked away from a
#: command it had started. 8109f4b5 did both at once, and the second is why.
STILL_RUNNING = " These are still running, and you have not read what they said: {names}."


def finish_the_work(*, target: str | None = None,
                    running: list[str] | None = None) -> str:
    """What a run that ended a turn with uncommitted changes is told, once.

    Once, and not again: a run that comes back and says its change is not right
    yet is telling the truth as often as not, and being asked twice would turn
    a plain answer into a loop.
    """
    waiting = (STILL_RUNNING.format(names=", ".join(f"`{n}`" for n in running))
               if running else "")
    return FINISH_THE_WORK.format(target=target or "main", waiting=waiting)


def first_prompt(brief: str, brief_path: str, limit: int = 32 * 1024) -> str:
    """The brief itself, or where to read it when it is too long to pass whole."""
    if len(brief.encode("utf-8")) <= limit:
        return brief
    return (f"Read the file {brief_path} and carry out the task it describes. It is your full "
            "brief, including how this run works.")
