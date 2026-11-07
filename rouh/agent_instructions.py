"""Agent instructions: what every agent Rouh starts is told before anything else.

Until 15 October 2026 they were two files in the workspace, `workspace/AGENTS.md` and the
`AGENTS_ASSISTANT.md` it imported. Petar, that day: "Why do we need files, cannot we pass this
dynamically? ... save it in db, write it so agents start with this and give me interface like rules
that I can CRUD the statements you hand picked." So from then until 30 October 2026 they were
statements in groups, an organisation's own rows (`models/agents.py`), on a page of their own.

Since 30 October 2026 they are rules (fr_61e683ffbada): "I want you to merge the rules and the agents
instructions. We will have one interface. and each rule will have 2 toggles: Chat ON/OFF button and
Agent ON/OFF button." Every rule is on the Rules page (`rouh/rules.py`), and its Agent switch says
whether every agent is told it. The statements were moved there (`move_to_rules`), and the first set
(`SEED`) and anything `ADDED` since still reach a new organisation the same way: given as rows,
then moved.

**How an agent gets them.** `assemble` makes the text, read the moment a run starts: the rules with
their Agent switch on (`agent_rules`), under their headings, with nothing in it that changes from
one run to the next, so the start of every run's prompt is the same and is cached. After it, and
only when there is one, the task in play: its status, its summary and its own `AGENTS.md`, never the
whole task list. A run of the one program asks for it at `/internal/agent-instructions` as it
starts (`one/runs.py`), Claude Code takes it with `--append-system-prompt` and Codex as its
SessionStart hook's context; a worker of Rouh's own crew is given it the same way by `crew.py`.
Every run's copy is written down (`issue`), and the Rules page shows what each run was given
(`/rules/agents`). Rouh's tool `agent_instructions` reads and changes them by voice.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

#: The most characters a statement may have, and its title, as `ADDED` and `REVISED` give them.
MOST_TEXT = 8000
MOST_TITLE = 120
#: How much of the task in play's own `AGENTS.md` an agent is given. A task's file can run to
#: thousands of lines; the rest is in the file, which the agent can read.
MOST_TASK_NOTES = 30_000

HEADING = "# Agent instructions"
LEAD = (
    "These are the standing instructions for every agent that Rouh starts. Rouh keeps them in its "
    "database and gives them to you when you start. The person changes them on the Rules page in "
    "Rouh, where each rule has an Agent switch. Obey each instruction where it applies to your work. "
    "They do not let you do more than your run allows."
)
TASK_HEADING = "## The task in play"


# --- the first set ------------------------------------------------------------------------

#: When a job asks Petar something, and how. Petar, 18 October 2026: only when the work he asked for
#: has stopped without him and the answer is his to give (`rouh/decision_gate.py`).
_WAITING = """\
Ask ‹owner› a question only when both of these are true:
1. The work that ‹he› asked for has stopped, and it cannot continue without ‹him›.
2. The answer is ‹his› to give: it spends money, sends or publishes something or commits ‹him› to something in ‹his› name, it cannot be undone, it needs a fact that only ‹he› has, or it is a choice that changes what happens next and that you cannot make from what you know.
If one of them is false, do not ask. Choose yourself. Write your recommendation and the reason for it on the page of the step and in the `AGENTS.md` of the task, and continue or finish. Research ends with your recommendation, never with a question such as "Buy now or later?", "Which direction?" or "Which next step should a job take?". Do not put the task in `waiting` and do not write a `question` block. Rouh has a gate in front of the decisions of ‹owner›: it removes a question that fails this test, and ‹owner› never sees it.

When a question passes the test, the task goes to `waiting` (the next move is ‹owner›'s). Do these steps:
1. In the `AGENTS.md` of the task, under Where this stands, write one paragraph that starts `**Waiting on ‹owner›:**`. Then ask the question so that ‹he› can answer it in one sentence. Example: `**Waiting on ‹owner›:** whether to pay the deposit of 400 euros for the venue.` For two or more things, write `**Waiting on ‹owner›, two things.**` with a numbered list under it. Start each item with its question in bold. Rouh shows this paragraph in the task browser and at the top of the page of the task.
2. Put a `question` block in the meta of the task, with `rouh-task meta <the task> merge '{"question": {...}}'`. It has these fields:
   - `ask`: the question, in one sentence.
   - `options`: two to six answers that ‹owner› will most probably give. Each has a short `label` and a one-line `detail` that says what that choice means or needs. Leave out `options` only when you cannot guess an answer.
   - `several`: `true` when ‹he› can choose more than one together.
   - `then`: one sentence that says what the answer will do, for example "A job pays the deposit and sends the booking to the venue."
   - `why`: one line that says why the work cannot continue without ‹him›.
   - `recommended`: the label of the option that you recommend, with `recommended_why`, one line that says why.
   - `risk`: `money`, `sending`, `publishing` or `irreversible`, when the answer spends money, sends something to a person, publishes, or cannot be undone. Add `risk_note`, which says the risk in plain words.
   - `urgency`: `now`, `today`, `soon` or `whenever`. Write it only when it is not `soon`.
   - `prepared`: a list of `{label, href}` for what you made for ‹him› to look at.
   The page of the task shows the options as buttons. ‹He› answers with one press or in ‹his› own words, and the answer goes to a job. Rouh only shows a recommendation. It never chooses for ‹him›.
3. When ‹he› answers, do all of these in the same turn: write the decision in the `AGENTS.md` of the task, remove the question with `rouh-task meta <the task> merge '{"question": null}'`, and take the task off `waiting` with `rouh-task status`. Nothing else does this.
- A task that is `done` asks nothing. Put what is left to do in its `AGENTS.md` as your recommendation."""

#: Research comes back as a task, and ends with a recommendation (Petar, 15 and 18 October 2026).
_RESEARCH = """\
When the person asks for research, deliver it as a task or as a subtask of a task. Never deliver it only as an answer, and never as a card on the canvas.
- Research is a request to research, look into, compare, or find and weigh options, for example "which vacuum should I buy". A quick fact (a price, a date, one number) is not research.
- If the job started from the conversation of a task, or the request names a task, make a new step (a subtask) of that task.
- If not, make a new task under the project that it fits, and put the research in its first step. A request for research is the request for a task that "New tasks and steps" asks for.
- Put the findings on the page of the step. Give the task a status and a summary, and update its `AGENTS.md`.
- End the research with your recommendation on the page of the step, and say what you recommend in your last message. Do not end it with a question for ‹owner›."""

#: What an organisation starts with: the statements Petar picked out of the two old files on
#: 15 October 2026, written again in Simplified Technical English. (group, enabled, statements).
#: They name the owner with marks (`rouh/owner.py`), filled in when a run is given them (`issue`),
#: and nothing in them is one person's own rule: those are the person's own rows, never a seed.
SEED: tuple[tuple[str, bool, tuple[tuple[str, str], ...]], ...] = (
    ("Research and writing", True, (
        ("Sources and footnotes", """\
Research output must name its sources.
- Each output that you make from web research must end with a numbered Sources list. This includes a page, the notes of a step, and the last message of a job.
- Each entry is the title of one page, as a link to its exact address.
- Put in the list each page that you used, and only those pages. A page that you read and did not use is not a source.
- In the body, put the number of the source immediately after each finding. In a list of suggestions, options or findings, give each item its own number. One item can have two numbers. One page can support many items.
- On an HTML page, the number is a link to its entry: `<sup class="cite"><a href="#source-3" title="The page's title">3</a></sup>`, and the entry is `<li id="source-3">`. In the `bb-visual-explainer` layout of one page for each nav item, Sources is its own nav item, the last in the menu.
- In Markdown (notes, and the last message of a job), the number is `[3]`. The list is a line `Sources`, with the entries numbered under it: `3. [The page's title](https://the.exact/address)`. Rouh shows this as footnotes that a person can press.
- Never say a number or an address aloud. Text that is for speech names the site in words, if it names it at all."""),
        ("Markdown file names", """\
Rouh shows each `.md` file by its file name only. It never shows the heading inside the file.
- Name each `.md` file for what it holds, in a few plain words, after the step number. Examples: `61-01.site-plan-and-copy.md`, `58-01.should-we-adopt-it.md`, `61-01.what-the-tests-found.md`.
- Do not use a name that fits any step. Bad examples: `61-01.notes.md`, `61-01.what-was-done.md`, `61-01.findings.md`.
- Choose the name before you write the file, and keep it.
- Do not rename `AGENTS.md`, `README.md`, the `step.md` that Rouh writes, or a `.md` file that exists. Pages and notes link to them by name."""),
        ("X-ray for long reports", """\
A report page of more than approximately 3,000 words must have an X-ray file, `<page>.xray.json`, next to it. A report that the person asks to X-ray also gets one.
- The X-ray is the argument of the report as a numbered outline of one-sentence claims. Each claim has its evidence in the words of the report and a jump to its passage. Rouh shows it over the page behind an X-ray button.
- Use the `bb-report-xray` skill for the format and the rules.
- Before you commit, run `rouh xray check <page>` from inside the workspace. It must pass."""),
    )),
    ("Browsers", True, (
        ("Live Chrome or headless Playwright", """\
There are two browsers. Use the correct one.
1. Live Chrome is the browser of Rouh. ‹Owner› watches it on ‹his› screen, takes it over and gives it back. Use it for ‹his› own accounts and anything behind ‹his› logins; for any step where a person must help (a login, a one-time code, a captcha, card details, a payment); and for any real-world action (booking, buying, sending a message, submitting a form or an application, signing up).
2. Headless Playwright is the browser of a job (the Playwright MCP). Use it for work that nobody watches: testing a page before you show it, reading public pages, reading many pages or scraping, and checks that repeat.
3. If your headless browser gets to a login, a captcha, a code, a payment or a button that you cannot undo, stop there. Do not work around it. Do not guess. Do not make an account. Do not try another route. Write down and commit what you found. Then end your turn with this block as the end of your last message, in exactly this shape:

```
LIVE BROWSER NEEDED
Address: <the exact address the page was on>
Step: <what has to be done there, such as: Log in to booking.com, or: Press Book on the prepared basket>
Ready: <what it had already filled in, chosen or found>
Send back: <what it needs to be told to carry on>
```

Rouh reads the block and marks the job as waiting on ‹owner›. It opens the address in its live browser, gets everything ready up to that step, and gives the browser to ‹him›. When ‹he› gives it back, Rouh sends the job what it asked for, and the job continues from there.
- The live browser does not share the logins of the job. Ask for the information that you need, for example the booking reference or what the page showed after the login. Never ask for a session.
- The job waits, not the task. Do not change the status of the task for this step.
- This rule is for real sites and the real accounts of the person. When you sign in to an app that you started yourself for a test, with the account that its test harness gave you, that is testing. Continue."""),
    )),
    ("Tasks and decisions", True, (
        ("A task's AGENTS.md", """\
Each task has an `AGENTS.md` at the root of its folder. It holds everything about the task: what it is, what was decided and why, the numbers, what was delivered and where, and what is open.
- It starts with a short section, **Where this stands**: the current position first, then what is open.
- Update it in the same turn when the position of the task changes: a step delivered, a decision made, a number corrected, something deployed or taken down.
- When you correct or replace something, keep it and label it, for example `**Replaced (2026-03-14, by the second quote below):**`. Do not delete it, and do not leave it so that it looks current. An agent obeys a stale conclusion that looks current.
- Step folders keep their own notes. Only the record of the task goes in the `AGENTS.md` of the task.
- Detail that does not fit in the summary of the task goes in its `AGENTS.md`."""),
        ("Waiting tasks and their questions", _WAITING),
        ("New tasks and steps", """\
- Do not make a new task unless the person asks for one.
- A new round of work on a task that exists is a new numbered step in that task. It is not a new task.
- A job that starts from the conversation of a task is told which task it is. Put its work in that task."""),
    )),
    ("Delivery", True, (
        ("A visual explainer for each step", """\
Each step of a task delivers a visual explainer. This is the default deliverable. Do not wait for a request.
- Build it with the `bb-visual-explainer` skill. Use the skill before you write the page. Do not make your own layout.
- Do not use the Tailwind CDN. It breaks the rule of the skill that a page makes no network requests.
- Each step gets its own `index.html`. For a new round of information, make a new step folder with the next number and a new `index.html`. Do not overwrite the previous one.
- Test the page before you show it: links resolve and images show. Take screenshots in Playwright and examine the screenshots, not only the HTTP status."""),
        ("Scratch files", """\
- Put throwaway files in the `temp/` folder of the step: Playwright snapshot `.yml` files, raw scraped HTML, debug dumps, scratch JSON and intermediate search results. Git ignores `temp/`.
- Never put them in the root of the task, the root of the step or `source-code/`. `source-code/` is for source material that the person gives, and for helper scripts that they can run again.
- Never put files in the root of the workspace. All work goes in the folder of its task and step."""),
    )),
    ("Safety", True, (
        ("Secrets and private material", """\
- Never read, print or ask for a secret, a key, a password or a token. Do not open `.env` files.
- Never ask the person to paste a key into a chat.
- Never publish or share client material, credentials or personal data. If you are not sure, ask first."""),
    )),
    ("Workspace mechanics, until code enforces them", True, (
        ("Status and summary with bin/task", """\
The status and the summary of a task are in the database of Rouh only. Change them only with `rouh-task`, from anywhere in the workspace:

```sh
rouh-task status 58 waiting         # not-started, in-progress, waiting, stopped or done
rouh-task status 67-03 done         # a step, by its two numbers, or by its folder
rouh-task summary 58 "What it is.
Where it stands.
What is open."                     # 50 to 90 words, one sentence per line
rouh-task summary 58 - < summary.txt
rouh-task show 58                   # what it says now, and its latest changes
```

- Never write `status` or `summary` in the meta of a task (`rouh-task meta`).
- Never edit `_tasks.md`. Rouh makes it from its database and replaces anything that you write in it.
- When the position of a task changes, change its status and summary in the same turn as its `AGENTS.md`. Give a new task a status and a summary at the start.
- If `rouh-task` says that it could not reach Rouh, nothing changed. Say so. Never write a status, a summary or a meta in a file instead."""),
        ("Make and move with objecttree", """\
Make and move projects, tasks and steps only with `rouh objecttree`, from inside the workspace. It writes the database row first, then the folder, the `.object.json` and the `AGENTS.md`, and gives a new task an empty list of steps in its meta. Do not make a task folder by hand: the database does not know it, and its number can be one that is in use.

```sh
rouh objecttree create "What it is called" --type task --owner <id>
rouh objecttree create "What it is called" --type task --owner <the task's id>   # a step: a task inside a task
rouh objecttree move <id> --to <owner id>
rouh objecttree verify
```

- One number is one task. The next number is the highest one on main plus one: `rouh numbering next --at origin/main`.
- Only `./land.sh` pushes to main. Never run `git push` to main."""),
        ("New steps in a task's meta", """\
The steps, groups, arrows, tags and question of a task are its meta. Rouh keeps the meta in its database, and nowhere else.
- See the meta with `rouh-task meta 58`. Change it with `rouh-task meta 58 merge '<JSON>'`. Each key that you give replaces that key, and `null` removes it. `steps` is merged step by step, so give only the steps that you change.
- When you add a step to a task, add it to the meta of the task in the same turn: a display title, a description of a few words, and its group. For example: `rouh-task meta 58 merge '{"steps": {"58-03.the-folder": {"title": "The title", "description": "A few words", "group": "the group"}}}'`.
- Add arrows to the steps that it builds on, corrects or replaces. Give each arrow a short plain label. `arrows` is one list of `{"from", "to", "label"}`: read the list, add your arrows, and give the whole list back with `merge`.
- A step that is not in the meta shows in the column "Not in a group yet". To rename a step, change its `title` in the meta. Never rename its folder."""),
        ("Goal tasks", """\
A task with the tag Goal (`"tags": ["goal"]` in its meta) is one of the goals of the person. It has a `goal` block, and its `goal.md` holds what the person knows about it. Each of its steps has a `goal_step` block: who does it, how, the hard part and what to do about it, and when Rouh does it. The page of the goal shows the steps in streams, kept as `streams` in the `goal` block.
- When you change the meta of a goal or of one of its steps, keep the `goal` and `goal_step` blocks. Use `rouh-task meta <task> merge`, which keeps each key that you do not give.
- Set the status of a step with `rouh-task status <its two numbers> <status>`, for example `rouh-task status 67-03 done`."""),
    )),
    ("Sharing outside Rouh", False, (
        ("Publish to briefings.page", """\
`./bin/publish`, in the workspace, puts a page online at briefings.page, with its Ask AI drawer.

```bash
./bin/publish work/acme/19.pricing/19-01.research/index.html       # publish or update
./bin/publish list                                                  # what is online
./bin/publish rm <id>                                               # take one down
./bin/publish whoami                                                # which account, how many pages are live
```

- A published page is public. Anyone with the link can read the page and the `.md` notes of its step and task. An `AGENTS.md` is never sent. Never publish client material, credentials or personal data. If you are not sure, ask first.
- When you publish the same step again, the same address changes.
- The free plan limits how many pages are live at the same time. If `publish` says that the limit is reached, show `./bin/publish list` and offer to take an old page down.
- `./bin/publish mirror on` keeps a private copy of the whole workspace on briefings.page. Turn it on only when the person asks: it sends each task folder, with its `AGENTS.md`, off this machine. `./bin/publish mirror` shows its state, and `./bin/publish mirror off` stops it."""),
        ("Share files with R2", """\
Use this only where `bin/r2` exists. If it does not exist, say that file sharing is not set up, and do nothing.
- Big binaries and files for a colleague go to Cloudflare R2 with `./bin/r2`. Never use `aws s3` directly. R2 keeps no versions, so you cannot undo an overwrite or a delete.
- `./bin/r2 put <file> [dest]`: the private bucket, in the folder of the person.
- `./bin/r2 share <file> [dest]`: stores it and prints a signed link that expires (1 day by default).
- `./bin/r2 link <path> [seconds]`: a new link for a file that is already uploaded.
- `./bin/r2 ls` and `./bin/r2 rm <path>`: only in the folder of the person.
- A share link works for anyone who has it, with no login, until it expires. Use it only for what the person asked to send, and say when the link expires. Never share credentials, infrastructure details, personal data or client material."""),
    )),
)

SEEDED_BY = "Rouh, from the two workspace files it replaced"

#: Statements written here after the first set, each given once to every organisation: to one
#: that already has the first set, the next time its instructions are read, and to a new one
#: straight after it. (who added it, group, title, text). Who added it is written down as the
#: change's `by` and is how it is known to have been given, so it is never given twice, and a
#: person who deletes it is not handed it back. A group the person deleted or renamed is made
#: again, last, under the name here.
ADDED: tuple[tuple[str, str, str, str], ...] = (
    # Petar, 15 October 2026 (fr_ca09476b2109): "Make it a rule that whenever I ask for research
    # it comes back as a task or sub task, not card/widget in the canvas. Also whenever I ask for
    # purchase comparison or research of objects, include the images so I can see them".
    # Rouh's own half, handing research to a job, is `RESEARCH` in `rouh/brain.py`.
    ("Rouh, from Petar's request fr_ca09476b2109 (research as a task)", "Research and writing",
     "Research comes back as a task", _RESEARCH),
    ("Rouh, from Petar's request fr_ca09476b2109 (pictures of things)", "Research and writing",
     "Pictures of the things compared", """\
When the research compares things to buy, or is about other physical objects, show a picture of each item next to its details.
- Take each picture from a page that you used for the item. The product page of the shop or of the maker is best: its main product photo, or its `og:image`.
- Download each picture into `images/` in the step folder, and make it small (approximately 600 px wide). The page shows it with a relative address, for example `<img src="images/dyson-v15.jpg" alt="Dyson V15 Detect">`. Do not link to a picture on another site: a page makes no network requests.
- Give each picture the number of its source, the same as a finding.
- If you cannot get a picture of an item, show the item without one. Never show a broken image or an empty frame.
- Before you commit, look at a screenshot of the page and make sure that each picture shows the correct item."""),
)


#: Statements of the first set or of `ADDED` written again here, each changed once in every
#: organisation: (who changed it, title, the words it had, the words it has now, and a new
#: title where it has one). Changed only
#: where the statement still has the words it was given, so a statement the person rewrote
#: himself is left as he wrote it; who changed it is the change's `by`, and is how it is known
#: to have been done. Kept in full, because the words it had are how it is found.
def _seed_text(title: str) -> str:
    """A statement's words as the first set has them now."""
    return next(text for _, _, rows in SEED for t, text in rows if t == title)


REVISED: tuple[tuple[str, ...], ...] = (
    # Every revision written here so far has been given to every organisation there is, and was
    # taken out once it had been: a new one is (who, title, the old words, the new words), and
    # a fifth value when its title changes too.
)


class Refused(ValueError):
    """What was asked cannot be done, and the message is the sentence that says why."""


# --- rows ---------------------------------------------------------------------------------


def _models():
    from .models import AgentInstruction, AgentInstructionChange, AgentInstructionGroup, AgentInstructionIssue

    return AgentInstruction, AgentInstructionChange, AgentInstructionGroup, AgentInstructionIssue


def _clean(text, most: int) -> str:
    """A statement's text as kept: its lines' ends trimmed, no blank lines at either end."""
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines).strip("\n")
    if len(out) > most:
        raise Refused(f"That is {len(out)} characters; one can have at most {most}.")
    return out


def _title(text) -> str:
    title = " ".join(str(text or "").split())
    if not title:
        raise Refused("A statement needs a short title.")
    if len(title) > MOST_TITLE:
        raise Refused(f"A title can have at most {MOST_TITLE} characters.")
    return title


def _snap(row) -> dict:
    """A statement as its history keeps it: everything needed to put it back."""
    return {"title": row.title, "text": row.text, "enabled": bool(row.enabled),
            "group_id": row.group_id, "group": row.group.name, "position": row.position}


def _gsnap(g) -> dict:
    return {"name": g.name, "position": g.position}


def _log(org: str, action: str, *, by: str, instruction=None, group=None, before=None, after=None,
         at: float | None = None) -> None:
    _, Change, _, _ = _models()
    Change.objects.create(org_id=org, instruction_id=instruction, group_id=group, action=action,
                          before=before, after=after, at=at or time.time(), by=str(by or "")[:200])


def ensure_seeded(org: str) -> None:
    """Give an organisation the first set, once: never again after anything has been changed,
    so a person who deletes every statement is not handed them back. Then each statement
    `ADDED` since that it has not been given."""
    _first_set(org)
    if org not in _added_for:
        _give_added(org)
        _give_revised(org)
        _added_for.add(org)


#: The organisations this process has given every statement in `ADDED`, so that is asked once.
_added_for: set[str] = set()


def _give_added(org: str) -> None:
    from django.db import transaction

    Statement, Change, Group, _ = _models()
    for by, group, title, text in ADDED:
        if Change.objects.filter(org_id=org, action="seed", by=by).exists():
            continue
        with transaction.atomic():
            # The group's row is the lock: two runs starting at once give it once.
            g = Group.objects.select_for_update().filter(org_id=org, name=group).order_by("id").first()
            if Change.objects.filter(org_id=org, action="seed", by=by).exists():
                continue
            now = time.time()
            if g is None:
                place = (Group.objects.filter(org_id=org).order_by("-position")
                         .values_list("position", flat=True).first())
                g = Group.objects.create(org_id=org, name=group, position=0 if place is None else place + 1,
                                         created_at=now, updated_at=now)
                _log(org, "group-create", by=by, group=g.id, after=_gsnap(g), at=now)
            row = Statement.objects.create(org_id=org, group=g, title=title, text=text, enabled=True,
                                           position=_next_position(org, g.id), created_at=now, updated_at=now)
            _log(org, "seed", by=by, instruction=row.id, group=g.id, after=_snap(row), at=now)
        log.info("gave organisation %s the agent instruction %r", org, title)


def _as_given(text: str) -> set[str]:
    """A statement's old words as a row may hold them: with the owner's marks, or with the
    marks filled in, the way a row given new words before the marks existed holds them."""
    from . import owner

    marked = _clean(text, MOST_TEXT)
    out = {marked}
    try:
        out.add(_clean(owner.say(text), MOST_TEXT))
    except Exception:  # noqa: BLE001 - no owner to fill in is the marked words alone
        log.debug("the owner's marks could not be filled in", exc_info=True)
    return out


def _give_revised(org: str) -> None:
    """Each statement in `REVISED` given its new words, once, where it still has its old ones."""
    from django.db import transaction

    Statement, Change, _, _ = _models()
    for by, title, was, now, *retitle in REVISED:
        if Change.objects.filter(org_id=org, action="edit", by=by).exists():
            continue
        with transaction.atomic():
            row = (Statement.objects.select_for_update().filter(org_id=org, title=title)
                   .order_by("id").first())
            if row is None or row.text not in _as_given(was):
                # Gone, or worded by the person since: theirs as it is.
                continue
            before = _snap(row)
            row.text = _clean(now, MOST_TEXT)
            if retitle:
                row.title = _title(retitle[0])
            row.updated_at = time.time()
            row.save()
            _log(org, "edit", by=by, instruction=row.id, group=row.group_id, before=before,
                 after=_snap(row))
        log.info("gave organisation %s the new words of the agent instruction %r", org, title)


def _first_set(org: str) -> None:
    from django.db import transaction

    Statement, Change, Group, _ = _models()
    if Change.objects.filter(org_id=org).exists() or Group.objects.filter(org_id=org).exists():
        return
    with transaction.atomic():
        if Change.objects.select_for_update().filter(org_id=org).exists():
            return
        now = time.time()
        for gpos, (name, enabled, statements) in enumerate(SEED):
            g = Group.objects.create(org_id=org, name=name, position=gpos, created_at=now, updated_at=now)
            _log(org, "group-create", by=SEEDED_BY, group=g.id, after=_gsnap(g), at=now)
            for pos, (title, text) in enumerate(statements):
                row = Statement.objects.create(org_id=org, group=g, title=title, text=text, enabled=enabled,
                                               position=pos, created_at=now, updated_at=now)
                _log(org, "seed", by=SEEDED_BY, instruction=row.id, group=g.id, after=_snap(row), at=now)
    log.info("gave organisation %s its first agent instructions", org)


def _statements(org: str):
    Statement, _, _, _ = _models()
    return list(Statement.objects.filter(org_id=org).select_related("group")
                .order_by("group__position", "group_id", "position", "id"))


def _next_position(org: str, group_id: int) -> int:
    from django.db.models import Max

    Statement, _, _, _ = _models()
    top = Statement.objects.filter(org_id=org, group_id=group_id).aggregate(m=Max("position"))["m"]
    return 0 if top is None else top + 1


# --- into the Rules page ------------------------------------------------------------------
#
# Petar, 30 October 2026 (fr_61e683ffbada): "I want you to merge the rules and the agents
# instructions. We will have one interface. and each rule will have 2 toggles: Chat ON/OFF button
# and Agent ON/OFF button." So every statement is a rule in the owner's Synapse Master
# (`rouh/rules.py`), with its Agent switch on and its Chat switch off, so nothing an agent or a chat
# is told changes until the person changes it. A statement keeps its title, its words, whether it
# was on, and its heading and place among the others (`meta.agent`), so agents are told them as
# before, in the same order under the same headings; on the page it is in the group its words are
# about. Its row here is then deleted with the move written down (`by` is `MOVED_BY`), so it is
# moved once, its history stays in `agent_instruction_change`, and a statement given to every
# organisation later (`ADDED`) is moved the next time the instructions are read.

MOVED_BY = "Rouh, moving it to the Rules page"
#: The Rules page group each first-set heading goes into; another heading is sorted by its words.
_INTO_GROUP = {"Research and writing": "work", "Browsers": "web", "Tasks and decisions": "work",
               "Delivery": "product", "Safety": "asking",
               "Workspace mechanics, until code enforces them": "work"}


def owner_master(org: str) -> dict | None:
    """The Synapse Master the organisation's agent rules are kept in: its first person's, who is
    the person this Rouh belongs to (`Tenancy.members`, in the order the accounts were made)."""
    from . import rules
    from .tenancy import Tenancy

    people = Tenancy().members(org)
    if not people:
        return None
    return rules.master(str(people[0].user_id), org)


def _seeded(org: str) -> set[int]:
    """The statements Rouh gave the organisation and nobody has reworded since: Rouh's, and kept
    as one of the defaults every Rouh starts with."""
    _, Change, _, _ = _models()
    given = set(Change.objects.filter(org_id=org, action="seed").values_list("instruction_id", flat=True))
    worded = set(Change.objects.filter(org_id=org, action__in=("edit", "restore"))
                 .exclude(by__in=[r[0] for r in REVISED]).values_list("instruction_id", flat=True))
    return given - worded


def move_to_rules(org: str) -> int:
    """Every statement the organisation still has, moved into its owner's rules; how many."""
    from django.db import connection, transaction

    from . import rule_groups, rules

    ensure_seeded(org)
    if not _statements(org):
        return 0
    ds = owner_master(org)
    if not ds:
        log.warning("organisation %s has nobody whose rules the agent instructions could go in", org)
        return 0
    moved = 0
    with transaction.atomic():
        # One move at a time for an organisation: two runs starting together move each once.
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"agent-instructions:{org}"])
        rouhs = _seeded(org)
        kept = {r["key"] for r in rules.rules(ds, every=True)}
        for rank, row in enumerate(_statements(org)):
            key = f"agent-instruction:{org}:{row.id}"
            if key not in kept:
                heading = row.group.name
                if row.id in rouhs:
                    origin = rules.origin_of("gene", "Came with Rouh, as one of the instructions every agent "
                                             "Rouh starts was told; moved here from the Agent instructions page.")
                else:
                    origin = rules.origin_of("manual", "Moved here from the Agent instructions page, where it was "
                                             f"kept under {heading}.")
                made = rules.add_rule(
                    ds, row.text, by=MOVED_BY, origin=origin,
                    group=_INTO_GROUP.get(heading) or rule_groups.sort(row.text), title=row.title,
                    where={"runs"}, more={"agent": {"heading": heading, "rank": rank, "statement": row.id},
                                          "defaults": row.id in rouhs, "off": not row.enabled})
                from .synapse import db

                db.run("UPDATE synapse.item SET source_key = %s WHERE id = %s::uuid", (key, made["id"]))
            ident, before = row.id, _snap(row)
            row.delete()
            _log(org, "delete", by=MOVED_BY, instruction=ident, group=before["group_id"], before=before)
            moved += 1
    log.info("moved %d agent instructions of organisation %s to the Rules page", moved, org)
    return moved


# --- what an agent is told ----------------------------------------------------------------


def agent_rules(org: str) -> list[dict]:
    """The rules every agent is told (`rules.for_every_agent`), in the order they are told: the
    statements moved from the Agent instructions page first, in their old order, then every other
    rule with its Agent switch on, by the Rules page's groups and then the order they were kept."""
    from . import rule_groups, rules

    move_to_rules(org)
    ds = owner_master(org)
    if not ds:
        return []
    order = {k: i for i, k in enumerate(rule_groups.KEYS)}
    got = [(i, r) for i, r in enumerate(rules.rules(ds)) if rules.for_every_agent(r)]

    def place(item):
        i, r = item
        moved = r["agent"] or {}
        if moved:
            return (0, int(moved.get("rank") or 0), 0, i)
        return (1, 0, order.get(r["group"], len(order)), i)

    return [r for _, r in sorted(got, key=place)]


def heading_of(r: dict) -> str:
    """The heading a rule is told under: the one it had among the agent instructions, else its
    group's name on the Rules page."""
    from . import rule_groups

    return str((r.get("agent") or {}).get("heading") or "") or rule_groups.NAMES.get(r["group"], "Rules")


def _rule_run_parts(org: str) -> list[str]:
    """The standing text: each rule under its heading, by its title when it has one."""
    parts = [HEADING, LEAD]
    current = None
    for r in agent_rules(org):
        heading = heading_of(r)
        if heading != current:
            current = heading
            parts.append(f"## {heading}")
        parts.append(f"### {r['title']}\n\n{r['text']}" if r["title"] else r["text"])
    return parts


def _gene_run_parts(org: str) -> list[str]:
    """The gene-owned rules, with a mail draft's rule attached to Sent by you."""
    parts = []
    # Plain words, while its switch is on (`rouh/plain_words.py`): a gene's rule, not a statement
    # of the page's, so it comes and goes with the switch and never appears among his statements.
    from . import plain_words

    extra = plain_words.for_runs(org)
    if extra:
        parts.append(extra)
    # Trials (`rouh/trials/`): how every agent runs a trial and reads and keeps the list of problems.
    from . import trials

    parts.append(trials.for_runs(org))
    # Copies kept in step, while its switch is on (`rouh/copies.py`): a gene's rule, the same way.
    from . import copies

    extra = copies.for_runs(org)
    if extra:
        parts.append(extra)
    # Sent by you, while its switch is on (`rouh/sent_by_you.py`): a gene's rule, the same way.
    from . import sent_by_you

    extra = sent_by_you.for_runs(org)
    if extra:
        # To send from your mail, while its switch is on (`rouh/to_send.py`): the draft's words too.
        from . import to_send

        more = to_send.for_runs(org)
        parts.append(extra + (" " + more if more else ""))
    return parts


def block(org: str) -> str:
    """The rules with their Agent switch on, as the text every agent starts with. The same text,
    byte for byte, for every run until a rule changes, so the start of a run's prompt is cached."""
    parts = _rule_run_parts(org)
    parts.extend(_gene_run_parts(org))
    return "\n\n".join(parts) + "\n"


def task_block(ref: str) -> tuple[str, str]:
    """The task in play: its status, its summary and its own `AGENTS.md`, and its id.
    Nothing when there is no such task, or no task at all."""
    ref = str(ref or "").strip()
    if not ref:
        return "", ""
    try:
        from . import instructions, taskrecord
        from .config import config

        row = taskrecord.find(taskrecord._store(), ref)
    except Exception:
        log.warning("the task in play, %s, could not be read", ref, exc_info=True)
        return "", ""
    if row is None:
        return "", ""
    name = f"Task {row.number}, {row.title}" if row.number is not None else row.title
    lines = [TASK_HEADING, "",
             f"{name}, in `workspace/{row.folder}`." if row.folder else f"{name}.",
             f"Status: {row.status or 'not-started'}."]
    if row.summary:
        lines += ["", "Its summary:", "", row.summary.strip()]
    notes = ""
    root = str(getattr(config, "assistant_repo", "") or "")
    if root and row.folder:
        try:
            path = instructions.in_folder(Path(root) / row.folder)
            if path.is_file():
                notes = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            log.warning("the AGENTS.md of task %s could not be read", ref, exc_info=True)
    # The copies of the same work in this task, while Copies kept in step is on (`rouh/copies.py`),
    # before its AGENTS.md, which can be long.
    from . import copies

    kept = copies.for_task(row.folder, str(getattr(row, "org_id", "") or ""))
    if kept:
        lines += ["", kept]
    if notes:
        cut = len(notes) > MOST_TASK_NOTES
        lines += ["", f"Its `AGENTS.md`, as it was when you started"
                      f"{', cut here: read the rest in the file' if cut else ''}:", "",
                  notes[:MOST_TASK_NOTES]]
    return "\n".join(lines) + "\n", str(row.id)


def _assemble_for_run(org: str, task: str) -> tuple[str, str]:
    """The instruction text and the task id that belongs in the run's record."""
    text = block(org)
    extra, task_id = task_block(task)
    if extra:
        text += "\n" + extra
    return text, task_id


def assemble(org: str, task: str = "") -> str:
    """Everything an agent starts with: the instructions, then the task in play when there is one."""
    text, _ = _assemble_for_run(org, task)
    return text


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# --- what each run was given --------------------------------------------------------------


def _record_issue(issue_model, org: str, *, run_id: str, via: str, task_id: str, text: str) -> None:
    """Keep what the run was given without stopping it when the record cannot be written."""
    try:
        issue_model.objects.create(org_id=org, run_id=str(run_id or "")[:80], via=str(via or "")[:60],
                                   task_id=task_id, text=text, at=time.time())
    except Exception:
        log.warning("what run %s was told could not be written down", run_id, exc_info=True)


def issue(org: str, *, run_id: str, via: str, task: str = "", who=None) -> str:
    """The text for a run that is starting, written down against the run, and returned.

    A worker's brief leaves Rouh here, past the place model requests have their marks filled
    in, so the owner's marks (`rouh/owner.py`: "Ask ‹owner› a question only when ...") are
    filled in here, for `who` when it is known and else for the person this context is for."""
    from . import owner

    _, _, _, Issue = _models()
    text, task_id = _assemble_for_run(org, task)
    text = owner.say(text, who)
    _record_issue(Issue, org, run_id=run_id, via=via, task_id=task_id, text=text)
    return text


def issued(org: str, limit: int = 30) -> list[dict]:
    """The latest runs and what each was given, newest first, without the text."""
    _, _, _, Issue = _models()
    rows = Issue.objects.filter(org_id=org).order_by("-at", "-id")[:limit]
    titles = _run_titles([r.run_id for r in rows])
    return [{"id": r.id, "run_id": r.run_id, "via": r.via, "task_id": r.task_id, "at": r.at,
             "title": titles.get(r.run_id, ""), "chars": len(r.text), "fingerprint": fingerprint(r.text)}
            for r in rows]


def issued_text(org: str, ident) -> dict | None:
    _, _, _, Issue = _models()
    try:
        row = Issue.objects.filter(org_id=org, id=int(ident)).first()
    except (TypeError, ValueError):
        return None
    if row is None:
        return None
    return {"id": row.id, "run_id": row.run_id, "via": row.via, "at": row.at, "text": row.text}


def _run_titles(ids: list[str]) -> dict[str, str]:
    """Each run's title from Rouh's register, where it has one."""
    try:
        from .models import Run

        return {r.id: r.title for r in Run.objects.filter(id__in=[i for i in ids if i]).only("id", "title")}
    except Exception:
        return {}


# --- for Rouh's tool, and the old page's addresses ----------------------------------------


def _group_key(said: str) -> str:
    """A Rules page group by its key or its name, or "" to sort a rule by its words."""
    from . import rule_groups

    said = " ".join(str(said or "").split()).lower()
    return next((k for k, n in rule_groups.NAMES.items() if said in (k, n.lower())), "")


def add(org: str, *, title: str, text: str, group: str = "", by: str, origin: dict | None = None) -> dict:
    """A new rule with its Agent switch on and its Chat switch off: what adding an agent
    instruction is now."""
    from . import rules

    ds = owner_master(org)
    if not ds:
        raise Refused("There is nobody in this organisation whose rules it could be kept in.")
    return rules.add_rule(ds, text, by=by, origin=origin or rules.origin_of("chat", f"Added by {by}."),
                          group=_group_key(group), title=_title(title or " ".join(str(text).split()[:6])),
                          where={"runs"})


def page(org: str) -> dict:
    """The rules every agent is told, under their headings: what `GET /api/agent-instructions`
    answers, and what the tool lists. Each is named by its Rules page `ref`."""
    groups: list[dict] = []
    for r in agent_rules(org):
        heading = heading_of(r)
        if not groups or groups[-1]["name"] != heading:
            groups.append({"id": heading, "name": heading, "statements": []})
        groups[-1]["statements"].append({"id": f"r:{r['id']}", "ref": f"r:{r['id']}", "title": r["title"],
                                         "text": r["text"], "enabled": True})
    return {"groups": groups, "rules_page": "/rules?label=agent"}


def listing(org: str) -> str:
    """The rules every agent is told, one line each, for Rouh's tool."""
    lines = []
    for g in page(org)["groups"]:
        lines.append(f"## {g['name']}")
        lines += [f"- {s['ref']}: {s['title'] or ' '.join(s['text'].split()[:12])}" for s in g["statements"]]
    return "\n".join(lines) or "No rule has its Agent switch on."
