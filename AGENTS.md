# Working in this repository

Read this before you change anything here.
It is the standing instruction for every person and every agent that touches this code, whatever tool it is, and it is not a suggestion.

This file was `CLAUDE.md` until 26 September 2026, with a short `AGENTS.md` beside it pointing here.
Petar asked that day for the instruction files to be vendor agnostic, so it is `AGENTS.md` now, the one name Codex, Claude Code (2.1.277 and later) and the other agents all read, and the two are one file.
There is deliberately no `CLAUDE.md` anywhere in this repository: Claude Code reads `AGENTS.md` only where no `CLAUDE.md` sits in the folder or any folder above it.

In short, the two rules that are never waived, each written out in full below:

> **Every feature proves itself, and nothing else is run.**
> There are no committed tests here at all: not a browser test, not a unit test, not an end-to-end test.
> No feature, no fix and no change may be committed, or reported as done, until you have opened the running app in a real browser over Playwright MCP, done what the person would do, and seen it work.
> A Python test is still the right tool for logic with no face, and you write it, run it and leave it out of the commit.
> No suite is run before a commit or a deploy, nothing you did not change is re-checked, and no test file is added back to this repository.
> "It should work" and "I verified by reading the code" are not reports.
> What you saw on the screen is.

> **Finish, then commit, then say so.**
> Never stop while something you started is still running: wait for it, however long it takes.
> When your own checks pass, commit everything you changed, to main.
> If a check cannot finish, or will not pass, say that plainly instead of reporting the work as done.

Three steps, every time.
`./e2e.sh serve` stands the real app up for you, on a free port, with an account and nothing that reaches the network.
The `browser_*` tools from Playwright MCP drive it; they are configured in `.mcp.json` and allowed in `.claude/settings.json`, so they are there without anybody being asked.
Then you say what you saw.

## The rule: every feature proves itself, and nothing else is run

> "Every feature should be Playwright tested that it works.
> Don't give me untested half-ass completions." - Petar, 16 September 2026.

> "Every feature should test itself. We're not going to run tests on every single feature or deploy.
> Each feature is responsible for its own MCP browser testing and Python tests, as well as integration and functional testing.
> We will not be doing regression testing or testing the entire system." - Petar, 20 September 2026.

Those two are one rule, and the second finished what the first started.
A change is proved hard, by whoever makes it, while they are making it.
What is never done is running the whole repository again afterwards to see whether anything else moved.

**There are no committed tests in this repository.**
Not a browser test, not a unit test, not an end-to-end test.
No feature, no fix and no change may be committed, or reported as done, until you have proved it yourself: driven it in a real browser over Playwright MCP, and run whatever Python you had to write to be sure of the logic underneath it.
What you wrote to prove it is yours, and it goes with your checkout.

This is what that means in practice.

- You start the real server, open a real Chromium through the MCP tools, and click, type and press exactly as the person would.
  If the person would press a button, you press that button.
- You look at what the person would see: text on the screen, a panel that is gone, a URL they landed on.
  Never a variable inside the page, and never a function you called directly.
- A change to `rouh/static/` or `one/static/` is a UI change.
  So is a change to a route that serves a page, a redirect, a cookie, a websocket message the page acts on, or anything that alters what a person sees or can do.
- **"It should work" is not a report. "I verified by reading the code" is not a report.**
  Neither is "the unit tests pass".
  The report is what you saw on the screen, named: the page you were on, the control you pressed, and the words that came back.
- If a feature genuinely cannot be driven from a browser, say so in your final message, say why, and say what you did instead.
  Do not quietly skip it.

Fixing a bug follows the same rule from the other end.
Drive the browser to the bug first and watch it happen, then fix the code, then drive the browser back to the same place and watch it not happen.
A fix nobody watched fail is a guess.

A Python test is still exactly the right tool for logic with no face: a parser, the scheduler's arithmetic, a trimmer, a wire format.
Write one whenever it helps, run it with `./e2e.sh <your file>`, read what it says, and leave it out of the commit.
Integration and functional checks are the same: yours to write, yours to run, not left behind for anybody else to run again.

### What is never asked of you

- **No suite is run before a commit.** There is none to run, and none is to be written back into this repository. The page's type check, below under "The page's types", the mail replay, below under "The mail replay", and the LLM service check (`python -m rouh.llmguard`, under "Every call to a model") are not suites: `land.sh` runs each only on work that touches what it checks. The stack test (`tests/stack/`, below under "Every feature in the containers") is the same: `land.sh` hands it to GitHub only for work that touches the containers' side, and waits for it.
- **No suite is run before a deploy.** The deploy checks that the new code imports and that the service answers, and that is the whole of it.
- **Nothing you did not change is re-checked.** Regression testing, and testing the whole system, are not done here. That is a decision, not an oversight.
- **A test file is never added to `rouh/`, `one/tests/` or `tests/e2e/`.** If you want one while you work, write it, run it, and let it go with your checkout.
  The one exception is the screenshot comparisons in `tests/e2e/visual/`, below under "The screenshot comparisons", which Petar asked for on 5 October 2026.
  The second is `rouh/selfcheck/`, below under "What every Rouh checks before it moves to a newer base", which Petar asked for on 23 October 2026.
  The third is the protected core's frozen security checks and stack-file fixtures, `guard/frozen/` and `guard/policy/fixtures/`, which came with the protected core on 24 October 2026 (`guard/README.md`): a Rouh is held to them and cannot edit them.
  The fourth is the stack test, `tests/stack/` with its list `CONTAINERS.md`, which Petar asked for on 29 October 2026: every feature must work in the containers every Rouh instance runs, and a change that breaks one must fail. It runs at GitHub on Intel and Arm, from "Tests on main" and, for work touching the containers' side, from `land.sh` before it pushes (`stack_guard`); a new feature adds its row to `CONTAINERS.md` and its check to `tests/stack/smoke.py` in the commit that adds it.

### The definition of done

A piece of work is done when all of these are true, and not before.

1. **You have driven the change in a real browser over Playwright MCP and seen it work**, and your final message says what you saw.
2. Whatever you wrote to prove the part with no face, you have run, and it passed. It stays out of the commit.
3. You commit, with a message that says what changed and why.

## Finishing

A long command is where work gets lost, and there is still one of those here: a browser being driven, or a check of your own that takes minutes.

On 17 September 2026 a run wrote the whole of a fix to the Ask AI drawer, started the `rouh/` suite, ended its turn saying "Waiting on the `rouh/` suite", and was closed three minutes later to make room.
Every file of that fix was still uncommitted.
The run exited 0 and every screen said **Done**.
Nothing it had done was saved, and nobody was told.
That suite is gone; the way the work went is not.

So, in this order, every time:

1. **Wait for every command you started.**
   If something you started is still running, wait for it, however long it takes, and read its result.
   Never end a turn while a command is still running.
   "Waiting on it" is not a finish; it is the middle of one.
2. **Commit, and land it with `./land.sh`, which deploys it.**
   Once your own checks pass, commit everything you changed, with a message that says what changed and why, and end with `./land.sh`, which is the only thing in this repository allowed to push to main.
   Never `git push` to main by hand: that is what loses a collision instead of resolving it.
   `land.sh` replays your work over whatever landed on main while you worked, one job at a time, pushes it, **and then deploys it.**
   The deploy is its own last step and not somebody else's job: it runs `update-all.sh`, which is both services on the server, the one program first and Rouh second, onto the one commit, so a change anywhere in this repository goes live everywhere it belongs.
   It waits for both of them to answer their health pages with the commit it just pushed, and only then does it say it worked.
   If it says your work collides with something, it hands you both sides, the files and the branch holding your work exactly as you wrote it, and tells you what to do: read both sides, reconcile the intent rather than the text, prove it in the browser again, and run `./land.sh` again.
   Nothing is ever thrown away on any path, including the one where the person is asked to decide.
   The README section "Landing work on main" has the whole ladder.
   Petar's standing policy is that a change that passes goes to main and is deployed from there without him being asked first, so committing and landing is the whole of what you have to do for it to go live.
   In a run of the one program you need not run `land.sh` yourself: the program ends every turn with it, on your checkout, and hands you back whatever it says. Run it yourself when that is what the job is; never `git push` to main instead of it.
3. **Read what it said, because only the deployed commit counts.**
   `land.sh` ends with one sentence that is one of exactly three things, and you repeat whichever it was:
   pushed to main and deployed, naming the commit; pushed to main and **not live**, naming the commit and the reason; or nothing pushed.
   A change that is on main and not live is **not done**, whatever else went right, and saying it is done is the failure this whole rule exists to stop.
   If it comes back not live, say so plainly, say the reason it gave, and do not call the work finished.
   On 21 September 2026 job 711a5e4a landed 9890a50 at about 01:40 and the server went on serving 3edf051 for six hours, because landing and deploying were two things and only one of them happened.
   Since then they are one thing.
4. **Say so.**
   Your last message names what you saw in the browser, what your own checks said, what you committed, and what was deployed.

If a check cannot finish, or will not pass, say that plainly and say what you would need, and leave the work uncommitted.
That is a proper finish, and a far better one than a report of work that is about to be thrown away.
What you must never do is report that you are done while anything is uncommitted.

The program now checks this rather than trusting it.
A run that ends a turn with uncommitted changes is asked once to finish them, and a run whose process ends while its checkout still holds work that never reached main is called **unfinished**, never done, with the reason on the run and in what Rouh says out loud.

### Done means deployed

A commit on main that nothing is serving is not done.
That is the whole of the rule, and it is the reason `land.sh` no longer stops at the push.

- **The deploy is part of landing.** You do not call it, ask for it or wait for anybody to approve it. `land.sh` starts it, detached so that the restart of the very program running you cannot kill it half way, and then checks the two health pages until both answer with the commit it pushed.
- **A deploy that failed is a failed job.** It is not a success with a note on it. `land.sh` exits 13, its JSON says `deployed: false`, and its last sentence says why: the new code was not healthy and was rolled back, the deploy would not start, it never came up. Repeat that sentence and leave the work reported as not live.
- **One deploy happens at a time.** If one is already in flight, yours waits for it rather than racing it. That wait is inside `update-all.sh`, so it holds for every way of starting a deploy.
- **There is nothing to deploy from some places, and it says so.** A checkout of another repository, a landing onto a branch this machine does not serve, and a machine with no deployment on it are each answered with a plain sentence rather than with a claim.

## How a change is proved

Three steps, every time: stand the app up, drive it over MCP, confirm it on screen.

### 1. Stand the app up with the harness

Do not build a world by hand.
`tests/e2e/conftest.py` already builds every one worth having, on a free port, with a PostgreSQL of its own and an account made by the real admin command, with this machine's API keys stripped out so nothing reaches the network or spends a token, and with everything torn down afterwards.

```bash
./e2e.sh serve            # Rouh, up and held, and it prints its address
./e2e.sh serve --list     # the other worlds
./e2e.sh serve one_deploy_world
```

It prints the address, the sign-in, and the process id to stop it with.
Stop it when you are finished, by that process id and no other way.

| World | What it stands up |
|---|---|
| `rouh_app` (`rouh`) | Rouh, with an empty data directory, a throwaway PostgreSQL of its own with the schema migrated in (`rouh/testing/postgres.py`), one account made by `python manage.py account add`, a small workspace to serve, no API keys, no tmux worker, no one program. |
| `rouh_with_tree` | Rouh serving **a copy of a real workspace** (`ROUH_TEST_WORKSPACE`, else the installation's own, `rouh/testing/workspace_source.py`), which is the tree: Work and Personal as top-level projects, the categories as projects inside them, a `.object.json` in every object folder. The task browser draws it from the database (`objectindex.py`), so this is the world for anything about the hierarchy. A copy, not the checkout itself: Rouh writes `_tasks.md` and task folders out of its rows, so a world pointed straight at it would change files in this repository. A task's status and summary are the database's and not in the files, so here every task starts not started, with no summary; the small worlds give theirs to the database as they start (`seed_tasks`). The copy is a git checkout of its own, because moving an object moves its folder with `git mv`, and `rouh/testing/fake_model.py` stands in front of it, because a card filed into a task as its next numbered step is drawn by the model. |
| `one_app` (`one`) | The one program in the throwaway world `one/tests/dev_server.py` builds: its own git remote, its own workspace, a stand-in for Claude Code, its own socket. |
| `rouh_with_one` | A second Rouh, paired with the `one_app` that is really running, and pointed at a throwaway checkout of the repository you can move. For the top bar's version chip, which has nothing to say until there is a program to say it about. |
| `two_chip_world` | Rouh and the one program, each read out of a checkout of its very own, so either of the top bar's two version chips can be made to say an update is waiting without touching the other service. |
| `one_deploy_world` | A one program served out of a checkout you can move, a `main` to move it onto, and a Rouh that can deploy it. For the button under the version chip: it really fetches, really fast-forwards and really starts the program again, with only systemctl stood in for (`tests/e2e/fake_systemctl.py`). |
| `talking` | Rouh with stand-ins for the model and the voice in front of it, so it really answers and really speaks. Not a fixture: it comes out of `rouh/testing/browser.py`. |
| `talking_luna` | `talking` with the key the stand-in for OpenAI takes (`rouh/testing/fake_openai.py`), so Luna can be picked and General, whose own model it is, answers with it (`rouh/luna.py`). `talking` has no OpenAI key at all, which is the server as it is until Petar adds one. |

`conftest.py` is the harness and it is not to be trimmed, tidied or simplified.
Every fixture in it is kept, whether or not anything is using it this week.
`tests/e2e/serve.py` asks it for the same fixture functions pytest used to ask it for, so a world can never drift away from the one the fixture builds.

Two things in it are pytest's own and mean nothing to a live drive: `signed_in` and `started` hand a `page` to a test that asked for one.
Driving live, you sign in by typing into the form, which is what they did anyway.

`talking` is the one that is not a fixture, and is the one to reach for whenever Rouh has to answer.
`talking` starts `rouh/testing/browser.py`, which puts a stand-in for the model in front of Rouh (`rouh/testing/fake_model.py`, a real HTTP server speaking enough of the Messages API to be the far end of Anthropic's own SDK) and a stand-in for ElevenLabs beside it (`rouh/testing/fake_voice.py`), so a reply really is worked out and really is spoken, with no key and nothing reaching the network.
The other stand-ins are there too, for Google, MCP and Telegram, and `rouh/testing/` is where they all live.
Its account is `tester`, not `alex`; `./e2e.sh serve talking` prints whichever it is.

### 2. Drive it over Playwright MCP

The server is configured in this repository, in `.mcp.json`, and allowed in `.claude/settings.json`, so a worker here has the `browser_*` tools without being asked for permission.
It is headless and isolated: there is no display on the server, and several jobs share this machine, so no two of them may share a browser profile on disk.

The sequence for Rouh is always the same.

```
browser_navigate   http://127.0.0.1:<port>/         lands on /login
browser_type       Username or email   alex
browser_type       Password   correct-horse-battery-staple-42
browser_click      Sign in
browser_wait_for   text: Connected
```

From there, do the thing the person would do, and then `browser_snapshot` to read the page back or `browser_take_screenshot` to look at it.
The sign-in cannot be turned off, here or anywhere: every address Rouh serves is behind an account.

### 3. Confirm it on screen, then commit

Name in your final message what you saw: the page, the control you pressed, and the words that came back.
"The task list column is gone and the button now says Show the task list" is a report.
"It should work" is not.

Then commit, and run `./land.sh`.

### A worked example

Proving that the top bar's button hides the task list column:

```bash
./e2e.sh serve                    # prints http://127.0.0.1:57425 and a pid
```

```
browser_navigate  http://127.0.0.1:57425/
browser_type      Username or email alex,  Password correct-horse-battery-staple-42
browser_click     Sign in
browser_wait_for  text: Connected
browser_snapshot                  # the three columns are there: Threads, Canvas, Conversation
browser_click     Hide the task list
browser_snapshot                  # the "Threads and running work" region is gone,
                                  # and the button now reads "Show the task list"
```

```bash
kill <the pid it printed>
git commit -am "rouh: what changed, and why"
./land.sh                         # pushes to main, and deploys what it pushed
```

Read its last line before you say you are done.
"Landed on main at `<sha>` and deployed it" is a finish.
"Landed on main at `<sha>`, and it is NOT live" is not, and neither is anything you did not read.

## The browser environment

### One command builds it

```bash
./e2e.sh
```

That makes `.venv-e2e`, installs `tests/e2e/requirements.txt` into it, and installs the Chromium build the pinned Playwright wants.
It takes a few minutes once.
There are no committed tests for it to run, so it says so and stops.

Anything you put after `./e2e.sh` still goes straight to pytest, so a throwaway test file you write while you are working runs the way it always did.
Throwaway is the word: it is not committed.

### The MCP servers every run gets

Every agent started on this machine gets the same MCP servers, in every repository and every worktree, and playwright is the one that matters: the rule above is that you prove your change by driving a real browser, and you cannot do that if your checkout came up without the server.

The list is one committed file at the top of this repository.

```
mcp-servers.json
```

**To give every run another server, add it there and change nothing else.**
Both places that start an agent read that one file: `rouh/crew.py` for a background job, and `one/asuser.py` for a run of the one program, including a crewmate or a sub-agent, because each of those is started the same way.

What happens at launch, every time, in a worktree made a minute ago:

- The servers in `mcp-servers.json` are merged with the checkout's own `.mcp.json`, and the result is written into the run's own scratch folder, `.one/mcp.json` or `.rouh/mcp.json`, each of which carries a `.gitignore` of `*` so it can never reach the repository.
- The agent is handed that whole file with `--mcp-config`.
- Codex has no `--mcp-config`, so its servers go into `~/.codex/config.toml` instead, which is that user's and is shared by every run. A name already in that file is left alone.

**A repository that has its own `.mcp.json` keeps its own servers.**
They are merged, not clobbered, and on a name collision the checkout's own entry wins, because the checkout's entries are written over the machine's in the merge.

`{repo}` in a command, an argument or an environment value in `mcp-servers.json` is the folder that file is in, filled in by both readers, so a server that is a file of this repository runs from the deployment's own copy, which no run can change.
The second server there is Rouh's own, `rouh` (`rouh/worker_mcp.py`), whose one tool, `notify_owner` (the old name `notify_petar` is still accepted), is how a job asks Rouh to email the person: it queues the text and Rouh sends it after asking (`rouh/outbox.py`, and the README under "When the person asks to be emailed about a job").
It learns which job it belongs to from the environment the launcher set, `ROUH_JOB` from the crew and `ONE_RUN` from the one program, which is why `one/asuser.py` tells Codex to pass `ONE_RUN` on to it.

### Why it is `--mcp-config` and not an approval

The `.mcp.json` a checkout commits is **not loaded at all** unless something turns it on, and what turns it on is `enabledMcpjsonServers` in that checkout's own `.claude/settings.json`.
That is why this repository has one, and it is why work here had a browser while work in a repository without one did not.

The per-path approval under `projects.<path>.enabledMcpjsonServers` in `~/.claude.json` is **not what Claude Code 2.1.274 reads.**
Measured on 21 September 2026, and worth repeating before anyone trusts it again: two worktrees, one of this repository and one of the person's workspace, were approved identically in `~/.claude.json` and both committed a playwright to `.mcp.json`.
The first came up `playwright · ✔ connected · 25 tools`; the second said **"No MCP servers configured. Run claude doctor if this is unexpected"**, which is the exact sentence that started this.
The only difference between them was the committed `.claude/settings.json`.

A server passed with `--mcp-config` needs no approval anywhere.
It came up connected in a git directory made seconds earlier with no entry in `~/.claude.json` at all, and it wins a name collision against the project's own rather than losing one, which is why the checkout's entry is put into that file rather than left out of it.
So everything goes down that one road, and nothing depends on an approval left over from a previous path.

The approval is still seeded, for a build that does read it and so that nothing ever stops to ask, and one bug in that seeding is fixed: a path already trusted used to be skipped outright, so a checkout trusted before it had an `.mcp.json` never got its servers and no later run could mend it.
On 21 September 2026, of the 251 project paths in one user's `~/.claude.json`, 22 had a server approved; the `rouh` user's 59 had none at all.

Why the worktree's own entry is not read was found on 24 September 2026, in the binary: Claude Code keys `projects.<path>` on the repository a folder belongs to, and for a git worktree that is the repository the worktree was made from, so a crew job in `crew/worktrees/<id>` is filed under `/var/www/rouh/app`.
Trust on the worktree alone gets past the first question, but a checkout whose `.claude/settings.json` pre-approves a tool, as this one does with `mcp__playwright`, is asked again unless that repository is trusted: "This folder pre-approves 1 tool permission in .claude/settings.json ... No, continue without these permissions".
Two crew jobs started on 24 September 2026 sat on that screen for more than an hour, because nobody was there to answer it.
So both `rouh/crew.py` and `one/asuser.py` now seed the worktree and the repository it came from (`_claude_project_root` in each).

### The browser the MCP server uses

Playwright MCP brings its own Playwright and wants its own browser build, which is not the one `.venv-e2e` installs.
It is already on this machine, in `~/.cache/ms-playwright`, for the user the workers run as.
On a machine that has never had it:

```bash
npx @playwright/mcp@latest install-browser chrome-for-testing
```

If a browser will not start at all, the system libraries may be missing, and then, once:

```bash
sudo .venv-e2e/bin/python -m playwright install-deps chromium
```

### Live Chrome or headless Playwright

There are two browsers on this machine, and Petar set which one does what on 24 September 2026.

1. **Live Chrome** is Rouh's own `browser` tool (`rouh/browsing.py`), the one the person watches on their screen, takes over and hands back.
   It is for anything in Petar's own accounts or behind his logins, anything where a person might have to step in (a login, a one-time code, a captcha, card details, a payment), and anything that ends in a real-world action (booking, buying, sending a message, submitting a form or an application, signing up).
2. **Headless Playwright** is the Playwright MCP above, which every background worker has.
   It is for anything that runs unattended: testing Rouh's own changes in a browser, which is everything under "How a change is proved", reading public pages, reading many pages, and checks that repeat or run on a schedule.
3. **A headless job that reaches a login, a captcha, a code, a payment or a button that cannot be undone stops there.**
   It does not work round it, guess, make an account or try another route.
   It commits what it has and hands that step to live Chrome, by ending its turn with this statement as the end of its last message:

```
LIVE BROWSER NEEDED
Address: <the exact address the page was on>
Step: <what has to be done there, such as: Log in to booking.com, or: Press Book on the prepared basket>
Ready: <what it had already filled in, chosen or found>
Send back: <what it needs to be told to carry on>
```

Rouh finds that statement in the job's report (`rouh/browser_handoff.py`), says it even in General, and marks the run as waiting on the person, with the step as its question.
It opens the address in its live browser, gets everything ready up to the step, hands the browser to the person, and once they hand it back sends the job what it asked for with `reply_to_task`, which carries the job on at its own prompt.
The live browser does not share a job's logins, so a job asks to be sent what it needs to know, never for a session.
Rouh still never types a password, a code or a card number, and never presses the button that books, buys, sends or submits.

A world you log into while proving your own change is not this: its account and password are the harness's, printed by `./e2e.sh serve`, and typing them is part of the proof.
The rule is about real sites and the person's real accounts.

### GitHub and the owner's other servers from a run

A run reaches the outside only through the key proxy, which tunnels ports 80 and 443 to public addresses and nothing else (`ROUH_KEYPROXY_PORTS`, `ROUH_KEYPROXY_ALLOW`).
The owner opens more for some hours from their own Mac, and each grant runs out by itself (`deploy/grants/README.md`): `rouh-github-grant 8` lets runs use GitHub as the owner, with the token kept in the key proxy and never in the worker, `rouh-proxy-grant all 8` lets runs reach any public server on any port (`ssh`, `servers`, `lan`, a name such as `example.com`, or `HOST:PORT` open less), and `rouh-open 8` opens GitHub and `all` together. Private addresses stay closed but under `lan`, and `lan` never reaches Rouh's own containers.
In a run, `/code/bin/rouh-github setup` once sets git and gh up to use the grant, and `/code/bin/rouh-github status` says whether one is open.
A refused server or a missing grant is the owner's to open: say which, with the command, and never work round the proxy.

### Looking at either app by hand

```bash
# Rouh, on the laptop, with the real keys
./run-local.sh

# The one program, in a throwaway world, at http://127.0.0.1:18031/one/
.venv-e2e/bin/python -m one.tests.dev_server /tmp/one-dev 18031
ONE_SOCKET=/tmp/one-dev/s.sock .venv-e2e/bin/python -m one.cli pair browser
```

### What the page does before you touch it

There is no splash screen: the page loads straight into the task list, the canvas and the conversation, and the socket opens by itself.
A browser will not start a speaker outside a real press, so nothing is audible until something on the page has been pressed; the name in the top bar is a safe place to press, because nothing else happens there.

The microphone is a separate thing and is never open unless somebody opens it.
Nothing on the page asks for one until the microphone button is pressed, hold-to-talk is held, or dictation is started, and turning it off ends every track rather than muting one that stays open, because a track that stays open keeps the orange dot lit in an iPhone's status bar.
`acquireMic` and `releaseMic` in `rouh/static/app/voice.js` are the only two functions anywhere that may touch a `MediaStream`, and that is the whole of the rule.
The orb has nothing to do with any of it: it is the picture of what the machine is doing, in both its places, and is never a control for a microphone.

## Everything a person sees follows the design standard

Petar, 7 November 2026 (task 169): every build, gene therapy included, designs what a person sees by one process, v2-full from design test 3, with **one** design direction, never three.
`rouh/design_standard.py` holds it, and every agent is told it after its agent instructions; a build's brief names it again (`starting.start`).

- **Two tiers, chosen by the agent, never asked.** The full tier is for a new or reworked screen: journeys first (`journeys.md`, in the person's words, always derived and never asked for), then the page structure, the full brief and the must-keep list, one direction built after reading the guide, the skill's `shoot.mjs` at 1440 and 390 px, critic rounds of the corrected critic prompt until no blocker is left (at most 3), and a handoff with tokens. Aim: about 45 to 60 minutes and about 15 dollars a screen, measured. The small tier is for a label, a button, a field or a fix: the same instructions in full, with no critic loop.
- **The skill is the workspace's, at `.claude/skills/bb-local-design/`, and nowhere else.** `python3 tools/design/record.py skill` finds it. Anthropic's `craft.md` and the design rules of its Design type have no published licence: they are read where they are at run time and are never committed here, in a gene, or in anything the Gene Pool sends. Without them a run uses the Apache-licensed frontend-design skill and Rouh's own rules, and says so.
- **The record, and the check before landing.** A run keeps its design record with `tools/design/record.py` in `.design/` (never committed). `screens` signs in to a test world and checks each changed screen at 1440 and 390 px, dark and light, for the faults `shoot.mjs` finds. `land.sh` (`design_guard`), and in the containers `bin/rouh-land` before it hands the work to the protected core (`design_check`), does not push a change to `rouh/static/`, `rouh/templates/` or `one/static/` without a record that passes: every journey met, no fault, and on the full tier a critic round with no blocker left and a clean prototype check. A commit that changes those files and shows nothing new says so with a line `Design: none - <why>` in its own message, which covers only that commit's files.
- **Ask AI and the comment pass** change a page in one model call, so they are told the small tier (`FOR_PAGE_EDITS`) and cannot check widths in a browser.

## The screenshot comparisons

On 5 October 2026 Petar asked for one committed suite, so that work meant to change nothing on the screen - splitting `app.js` into modules, renaming the static files by their content - can be shown to have changed nothing.
It is `tests/e2e/visual/`: Rouh's screens photographed at a phone's width (390 x 844) and a desk's (1440 x 900) and compared with the pictures committed in `tests/e2e/visual/baselines/`.

```bash
./e2e.sh visual              # compare every screen with its baseline, about a minute
./e2e.sh visual -k brief     # one screen, at both widths
./e2e.sh visual --update     # take new baselines, on purpose
```

The screens are the main page idle, a card with a number, words, a table and a drawn page, the task browser, the task list closed at a desk and open on a phone, a conversation with the canvas beside it (and switched to on a phone), the orb full screen, Synapse, the morning brief and an email case.
It builds its own world (a fixed workspace, the stand-in model, nothing reaching the network), holds the browser's clock, hides the orb and masks what is right to differ, such as times and the commit on the version chip; `tests/e2e/visual/conftest.py` says exactly what, and what tolerance a screen is allowed.

Run it whenever a change is meant to leave the screens alone, and before landing one that touches `rouh/static/app.js`, its modules in `rouh/static/app/`, or the way static files are served.
When a change is meant to change a screen, it fails, and that is it working: look at the three pictures it leaves in `tests/e2e/.artifacts/visual/` (expected, actual, and the difference in red), and if the new one is right, take new baselines with `--update`, look at each changed PNG, and commit them with the change that made them, saying why in the message.
Never take new baselines to make a failure go away without looking at the difference first.
The baselines are this server's Chromium and fonts; taken anywhere else every screen differs by a pixel of anti-aliasing.

It is still not a regression suite, and nobody runs it for a change it has nothing to do with.

## A job in the containers is not a job on the server

Since 31 October 2026 Rouh runs in containers (`deploy/stack/compose.yml`), and a run works in the worker container.
There is no systemd there, no `/var/www/rouh`, no sudo and no way to the database: the worker is off the database network on purpose and holds no password.
So `systemctl`, `systemd-run`, `journalctl` and `deploy/with-rouh-env.sh` do not work from a run, and neither does a `manage.py` command against the live database; `with-rouh-env.sh` says so and exits 4.
In the core itself a command already has Rouh's environment: `docker compose exec core python manage.py <command>`, from the machine.
What a run needs from the database it gets from Rouh's own tools (the `rouh` MCP server, `rouh-task`, `rouh-files`), or Rouh puts it in the run's brief, as a case fix's brief now carries its whole trace.
How a job may reach the live database safely is the owner's Decision 422; until it is answered, the nightly Synapse run is written down as failed with that reason rather than started for nothing (`rouh/synapse/lab/nightly.py`, `cannot_measure`).

Two checks keep this from failing quietly again (Petar, 5 November 2026):

- **No code tied to the old server without saying why.** `python -m rouh.hostguard` fails on a mention of systemd, `/var/www/rouh` or `with-rouh-env.sh` in `rouh/`, `one/` or `bin/` that `rouh/hostpaths.json` does not list with why it is right in the containers too. The protected core runs it with Rouh's own checks on every change (`rouh/selfcheck/own.py`), and `land.sh` before pushing (`host_guard`).
- **Every scheduled job checked against what it left behind.** `rouh/job_watch.py` looks every half hour at each of Rouh's server jobs on Clockwork, the job's own record (the Synapse attempt, the refactoring night) and the backups, keeps the answer for `server_health` (`scheduled_jobs`), and says the failures once a morning as one notice. `python manage.py job_watch` says it in a shell of the core.

A row of `CONTAINERS.md` says works only when its check proves the job does its work, not that it starts.

## Every feature in the containers

Petar, 29 October 2026: every feature Rouh has must work in the containers every Rouh instance runs (`deploy/stack/compose.yml`), and a change that breaks one must fail.
`CONTAINERS.md` is the one list of those features, each with its status and how it is checked, and `tests/stack/` is the test that reads it: the real stack on images built from the change, the change as the Rouh's own code, every outside service a stand-in, and every row marked works checked from outside.

```bash
tests/stack/run.sh                        # needs Docker; there is none on the server
git push -f origin HEAD:refs/heads/proof/stack-<name>    # the same at GitHub, Intel and Arm
```

It runs at GitHub (`.github/workflows/stack-tests.yml`) for every push to main, from "Tests on main", whose record is the code a new Rouh installs, and before `land.sh` pushes work that touches the stack file, the images, the protected core, the libraries or the test itself (`stack_guard`, which waits for the result on the branch `stack-checks`).
A new feature adds its row to `CONTAINERS.md` and its check to `tests/stack/checks_<area>.py` in the commit that adds it; a row says works only when its check passes.
On the Creator Rouh's machine the assistant user has a rootless Docker of its own (`~/.local/share/rouh-docker`, no change to the machine's services or firewall): `~/.local/share/rouh-docker/stack-test.sh NAME BASEPORT [--record]` runs the stack test there, at most two at a time, and `--record` writes a whole run of a clean checkout down on `stack-checks` for `land.sh`, saying it ran on this machine's architecture only.

## The page's types

Since 5 October 2026 the page's own script, `rouh/static/app.js` and its modules in `rouh/static/app/`, is type checked: plain JavaScript with JSDoc types, checked by TypeScript in place, with nothing compiled and nothing built.
TypeScript is a tool for whoever changes the page, pinned in `tools/typecheck/package.json` and never installed on the server's runtime or sent to a browser.

```bash
tools/typecheck/check.sh     # tsc --noEmit over tsconfig.json; installs the pinned TypeScript once, into ~/.cache
```

`land.sh` runs it before it pushes anything that touches those files, and refuses to land work that does not pass, saying the first error (`types_guard`).
That is one of the two checks run before landing, on Petar's instruction of the same day, and it takes a few seconds; the other is the mail replay, below.

The types that matter most are in `rouh/static/app/protocol.d.ts`: every WebSocket message both ways, by its `type`, and every card block, by its `block`.
`handleMessage` takes a `ServerMessage` and `send` a `ClientMessage`, so a field the protocol does not have, in either direction, is an error.
A message or a field added on the wire is added there and in `PROTOCOL.md` in the same change, and a value's type can be pinned down from `any` whenever it is known.
`rouh/static/app/globals.d.ts` says what the other scripts put on `window` for the page and what it puts there for them.
The check starts non-strict; tighten it a module at a time rather than all at once.

## The mail replay

On 11 October 2026 Petar asked that a change to how Rouh handles trusted contacts' mail and messages cannot land if it makes a real case come out differently (`MAIL.md`, D9).

```bash
python3 -m rouh.mail_replay     # every kept case, ask by ask, and the outbox guard; a second or two
```

It judges every case in `rouh/testing/mail_replay.json` with the very code a run uses (`mail_ledger.judge`) and compares each ask with the outcome it must have, and it fails if any module but `rouh/mail_outbox.py` can send to a contact.
It needs nothing but the standard library.
`land.sh` runs it before it pushes anything that touches the mail code (`mail_guard`, `MAIL_PATHS`), and refuses to land work that does not pass, saying the first case that failed.
When a change is meant to change an outcome, change that case's expected statuses in the same commit and say why in the message.
A new kind of case that went wrong live is added to the file as a case of its own.

## There is no suite

On 20 September 2026 the last committed tests in this repository were deleted, on Petar's instruction.
There were 2,034 under `rouh/` and 334 under `one/tests`: 2,368 tests in 97 files and 32,678 lines, which was 42% of the Python here.
Both were green when they went, and both were run once more to be sure of it: `rouh/` in 2 minutes 17 seconds and `one/tests` in 10 minutes 7 seconds.
Every job on this server had been paying that on top of its own work, and step `30-21.where-the-time-goes` measured where it went: over six days, 11.1 of the 16.4 hours these jobs spent running commands was a test suite.

Nothing about them is lost, and any one of them comes back in a command.

```bash
git log --diff-filter=D --oneline -- rouh/test_brain.py   # the commit that removed it
git show <sha>^:rouh/test_brain.py                        # read it
git checkout <sha>^ -- rouh/test_brain.py                 # put it in a checkout
```

Every test in `rouh/test_brain.py` and most of `rouh/test_crew.py` was there because something had failed silently once, and its comment says which.
That history is worth reading before you change either file.

**What is kept is everything that stands the real thing up, and it is not to be trimmed:** `tests/e2e/conftest.py` and `tests/e2e/serve.py`, `rouh/testing/` (with `postgres.py`, which gives every world a database of its own), and in `one/tests/` the throwaway world `dev_server.py`, the stand-in agents `fake_claude.py` and `fake_codex.py`, the reaper `strays.py`, and the two `conftest.py` files that keep a check of your own off the live database and off other people's processes.
`.venv-e2e` holds both apps' pinned requirements, so a check you write runs in it whatever it imports.
On the server there is also `/var/www/rouh/.venv`, which is the deployment's own and should be left alone.

**Four of the deleted files were guards rather than tests of a feature, and nothing checks them for you now.**
`rouh/test_telegram.py` refused an endpoint that could read a reply from the bot; that one rule is the exception below, because Petar asked for Telegram both ways on 26 September 2026, and what stands in its place is that only his own chat is ever read (`rouh/telegram_chat.py`).
`rouh/test_hook_endpoint_guard.py` and `rouh/test_untrusted.py` held the line on what an unsigned caller may reach.
`rouh/test_never_hangs.py` refused a section of `verify.py` with no time limit.
Every other rule they enforced is unchanged, and is in this file and in `README.md`.

## Whose data is it

Rouh is becoming a service that several organisations use, so everything that belongs to anybody belongs at one of two levels, and the code never mixes them up.

- An **organisation** owns what its people share. Its Google Cloud OAuth client - the client id and the encrypted client secret its administrator entered - is the first of those.
- A **user** owns their own connections: their Google account, their tokens, their mail, their files.

Three rules follow, and they are not negotiable anywhere in this repository.

1. **Org-owned and user-owned data is always keyed and always queried scoped.**
   Every row that belongs to an organisation carries `org_id`, every row that belongs to a person carries `user_id`, and every query names the one it is asking about.
   There is no "the settings", no "the connection", no global anything.
   Prefer putting both ids in the `WHERE` clause even when one of them is already unique: a caller holding the wrong organisation is exactly the bug worth turning into "not found" rather than into one customer being handed another customer's credentials.
2. **Credentials are always encrypted at rest.**
   Anything Rouh holds on somebody else's behalf - a client secret, a refresh token, an access token, an API key that is not this instance's own - goes through `rouh/encryption.py` before it reaches the database.
   Never into a log line, never into an HTTP response body, never into the repository, a workspace or a commit.
3. **There is never a global credential fallback.**
   If an organisation has not entered its own credentials, the answer is a clear "not set up yet" with what to do about it.
   It is never quietly somebody else's credentials, and never a server-wide pair from an environment file.

Who is asking is answered in one place, `Tenancy.current` in `rouh/tenancy.py`.
Every route and every tool goes through it rather than assuming, which is what lets real accounts land without touching any of them.
`GOOGLE.md` is the worked example of all of this.

## The rest of the house rules

- Never use the em dash. A plain dash instead.
- Do not put an agent's name in a commit message as a co-author.
- Commit only once you have proved the change. What a run leaves uncommitted is not saved.
- In a long Markdown file, one sentence per line.
- Prefer quality, simplicity, robustness and long term maintainability over how long something takes to build.
- Be picky about the UI. If something looks off while you are in there, even if it is not yours, fix it.
- **Brown toggles.** Petar, 15 October 2026 (fr_fa2525969751): what he is not sure he wants to keep on a page is moved inside a brown toggle, closed until pressed, rather than taken out. It is `<details class="brown-toggle">` with a `<summary>` and a `<div class="brown-toggle-body">`, styled once in `rouh/static/app.css`; never a toggle of a page's own.
- Hold engineering to the same standard: something broken that you find on the way, or a lint error, gets fixed whether or not you caused it.
- **What a conversation is told is rules, never text in the code.** Petar, 21 October 2026: one place rules Rouh's behaviour, and it is the Rules page. Since 30 October 2026 every rule is in the person's Synapse Master and none is in the code: a new instruction for Rouh's conversations is a rule added on the Rules page, with its conditions, and tagged defaults when every Rouh should get it (`rouh/ruledefaults.py`), never a string in `brain.py` or beside it; README.md, "What a conversation is told", has the whole of it.
- **Nobody's life in this repository.** Petar, 21 October 2026: the code will one day be public, and anyone reading every commit of it must find software, not his life. The person's workspace is a repository of its own (README.md, "The workspace is a repository of its own"), and nothing of it - a task, a note, a page, a mail, a chat, a screenshot of real data - is committed here. Examples, fixtures and screenshots use fictional people on `.example` and `.test` domains; a real person's name, address, number, account, machine or domain is an installation's setting or nothing.
- **Nobody's name in the code.** Text about the person a Rouh belongs to says `‹owner›` (and `‹he›`, `‹his›`, `‹company›` ...), filled in by `rouh/owner.py` where the text leaves Rouh.
  Their addresses, clock and permissions are read from their account and settings, and an installation's own values from its environment (`SETUP.md`).
  Never write a person's name, address, company, city or permission into code, a prompt, a default or a fixture.

## The models are values, not code

Which model answers is a mode, two tiers and a tier for every use, in Rouh's database, set in Settings under Models (`rouh/modeldefaults.py`, since 18 October 2026; the mode and two tiers since 23 October 2026): the mode Best, Balanced or Saver, and the tiers Cheaper and Smart, each an OpenAI and an Anthropic model with one of them main, and every use of a model on one of them or on a model of its own (Custom); each of the page's two boxes (the tiers, and Each use) has its own Auto toggle: on, that box follows the Rouh model service's daily standard (which, for Each use, may route the chats' messages to a tier, `rouh/modelrouter.py`), and off, its manual settings apply, which that box's Sync makes the service's once; while either is on the counts are sent and double calls run; locks hold either way.
How deeply a model thinks comes with the model, from the model standard (`rouh/model_standard.json`), which Petar publishes on rouh.land and every Rouh fetches once a day (`rouh/modelstandard.py`); README.md, "Which model answers", has the whole of it.
Petar asked on 27 September 2026 that when he asks for a different model, it is these values that change, so a request like "put Sonnet in Cheaper" or "switch to Saver" is answered by changing them, never by editing a model name into the code.
On this machine that is one command, which is his explicit request to write to the live database for this and nothing else:

```bash
sudo -n systemd-run --quiet --wait --pipe --collect -p EnvironmentFile=-/var/www/rouh/.env \
  -p WorkingDirectory=/var/www/rouh/app /var/www/rouh/.venv/bin/python \
  manage.py model_defaults --use code_runs=smart
```

With no options it only says what they are; `--help` lists the tiers and the uses.
Rouh can do the same when asked, with its `model_defaults` tool, and the Models page is the third way; all three are `modeldefaults.put`.
A model's level is the standard's and nobody's pick: a request to change one is a change to the standard (`rouh/model_standard.json`, and the copy rouh.land publishes).
Say in your last message what they were and what they are now.

## Every call to a model

Petar, 5 October 2026 (fr_74d5e6383c34): "every new ai call as usual needs to go through llm service but also needs to appear as a model selection in the models page."
And the evening of 18 October 2026: "Every call that we make now has to route through our new model selection. Whatever we select here should be the one called. No exceptions."
So a new place in Rouh that asks a model does two things, and is not done until both are true.

1. **It asks through the LLM service, `rouh/llm.py`.**
   `await llm.ask("<use id>", system=..., messages=..., max_tokens=..., who=who)` asks the model the Models page has for that use, Anthropic's or OpenAI's, at the level that comes with it, through the clients that write every request down (`rouh/llmlog.py`), and gives back the words with the model that said them.
   Pass `read_only=True` when the answer only says something and changes nothing, so with Auto on it may be compared with a second model's (double calls).
   Nothing swaps a model: a model that cannot be asked here raises `llm.Cannot`, and the Models page says so beside the use.
   The only other places a model is asked are the loops that are more than one question (a chat's turn in `brain.py` and `luna.py`, Ask AI and its comment pass, look_into, Synapse's engine), each with its use's model; README.md, "The log of every request made of a model", has the log.
2. **It has its own place on the Models page.**
   It is a `Use` in `USES` in `rouh/modeldefaults.py`: an id, the group it is listed under, a name and a line a person can read, and its `llm_requests` purposes; and the choice it starts on, with the reason, in the model standard (`rouh/model_standard.json`, `uses`), which refuses to load without one.
   A use is marked `only` one company, with `needs` saying why, only when the code truly needs that company (a Claude Code run, a Codex run, a loop written for one API), never because of which client it was handed.
   That alone puts it on the page, in Rouh's `model_defaults` tool and in `manage.py model_defaults --use`, and its calls into what Rouh learns about which model succeeds (`rouh/modeloutcomes.py`).

A model id in the code is only ever in the list of models there are to pick (`config.MODEL_CHOICES`) and the tables of their facts (prices, context sizes), and a model added there needs its level in the standard too.
`python -m rouh.llmguard` fails on a model asked past the LLM service, a client made past `rouh/llmlog.py`, or a model named in code; `land.sh` runs it before every push that touches Rouh's Python (`llm_guard`), and the deploy runs it too.
Two things are not on the Models page, and say so: Synapse's embeddings, which belong to a dataset's stored vectors, and the picture models, picked in the picture editor.

## Every change names its gene

Petar, 13 October 2026 (task 98, step 98-16): "Everything that remains in my Rouh needs to be formulated as a gene in a list ... automatically populated by anything I build."
So Rouh keeps a gene log (`rouh/genelog.py`, GENES.md "The gene log"), and it reads every commit that lands.

**Every file belongs to a gene.** Petar, 19 October 2026: "there is no plumbing that is not gene".
`rouh/genes/owners.json` maps every file of this repository but `workspace/` to the gene or genes it is part of, the shared parts underneath included (the turn loop, Synapse, mail, the screen, model calls, the one program, landing).
`land.sh` refuses a change that adds or changes a file no gene owns, naming the file (`owners_guard`), so a new file goes into the map in the same commit: under the gene it is part of, and under a new gene only when Rouh gains a new ability.
Every landed change is then one version in the history of each gene whose files it touched, with where it was asked for, read from the run that landed it.
A gene marked `core` in the map is one Rouh breaks without: it has versions, history and sharing like any gene, and no off switch.
`python -m rouh.genes.owners check` holds the whole map, and `python -m rouh.genes.owners who <path>` says whose a file is.

A commit that changes Rouh's code still ends with one line naming the gene it builds on:

```
Gene: decisions
```

The key is a gene manifest's id (`rouh/genes/manifests/<id>.json`), or a key already in the gene log, or a new key for a new ability, which the log then makes as a new gene.
A commit that changes several genes has one `Gene:` line for each.
A commit that takes a gene out ends with `Gene-removed: <key>` instead.
Change the gene's manifest in the same commit whenever what it is, where it appears, what it touches or how to remove it changes: that is what grows a sub-gene in the log rather than a revision.
The genes a change goes to are its files' owners; the line names a gene being installed or grown, whose files are given to its key in the map.
A commit from before the map, with no line, was put to a gene by the gene writer, a model call.

## What every Rouh checks before it moves to a newer base

Petar, 23 October 2026: "latest" means only patch-level fixes to what Rouh runs on, and those go in by themselves; everything else - features, Rouh's own logic, its own security fixes, big library upgrades - reaches a Rouh only as a gene, because each Rouh changes its own code and an update must never overwrite it.
So in containers Rouh runs on `rouh-base` (`deploy/container/Dockerfile.base`), which holds no Rouh code, and its code is the person's own, in the code volume at `/code`, a git repository that the first start fills once from rouh.land (`guard/bin/rouh-code-install`) and that only the Rouh changes after, each change through its protected core; the libraries a gene adds go into the extra volume at `/extra` (`rouh-extra-pip`).
Since 24 October 2026 the parts that keep a Rouh safe and repairable are its **protected core**, the `rouh-guard` image (`guard/`, `guard/README.md`, GENES.md "What a gene may change"): a Rouh uses it and cannot edit it.
`deploy/container/README.md` has the whole of it, and `deploy/container/base_patch.py`, `rouh/base_patches.py` and `.github/workflows/base.yml` the nightly patch job: the exact versions a base is built with are in main, `deploy/container/base/`, a new level arrives as a pull request on main from the Creator Rouh that merges itself only when its checks pass on Intel and Arm, and a release is a tagged commit of main, `base-<level>`, with its records on that GitHub Release.

Before any Rouh moves onto a newer base it runs the protected core's `rouh-check` on it with its own code: the base's own parts, the headless browser over MCP, the frozen security checks (`guard/frozen/`, which ask the Rouh only through `rouh/checkface.py`: injection through untrusted mail and pages, every action that needs the person's yes still guarded, no data across people or organisations), and the Rouh's own checks (`python -m rouh.selfcheck --only own`). Every change of a Rouh's own code passes the same two before it goes live.
That suite is committed, in `rouh/selfcheck/`, and it is the one committed Python suite: it travels inside every Rouh's own code, so a Rouh changed by its genes is checked with its own code.
It is not a regression suite of this repository and nobody runs it for a change it has nothing to do with; a change that alters what it checks changes it in the same commit, and a gene that adds an ability adds its checks there.
Run it on a throwaway database only (it refuses one that holds accounts): `guard/bin/check-base.sh --base <image> --guard <image> --code-dir <checkout>` does the whole check in containers.

## Rouh for Mac is its own repository

Rouh for Mac, the menu-bar app that runs Rouh on a Mac, is `rouh-it/rouh-mac` since 27 October 2026 (task 140, step 140-09), on Petar's word: "The Mac app is a separate thing and should be separated." From 22 to 27 October it was `mac/` here; its history went with it.
What ties the two together is rouh.land, never a build: this repository signs the releases a Mac follows (`deploy/container/mac_release.py`, `.github/workflows/base.yml`) and the app reads them from rouh.land.
One thing is shared as files: `guard/policy/` (the stack check's allow-list and its fixtures), which the app's `StackPolicy.swift` is held to through a copy in `rouh-mac/rouh-core/guard/policy/`. When you change `guard/policy/`, say so in your last message: the copy is brought up with that repository's `scripts/sync-rouh-core.sh`.

## Where everything is

`README.md` has the shape of Rouh - a Django project on PostgreSQL, managed with uv on pyenv's Python, with its section "The backend: Django on PostgreSQL" - `one/README.md` the shape of the one program, `PROTOCOL.md` the wire protocol between the page and the server, `TELEMETRY.md` the work tree, `EVENTS.md` the event log - every press, opening, message and piece of work, kept as counts and ids in `analytics.event` - `rouh/turnmarks.py` how a turn of speech begins and ends, `DECISIONS.md` the one model of everything waiting on the person's answer - the audit of every place that asked, the record, the sources and the safety rules -
`MAIL.md` how a trusted contact's email or Telegram message is handled - the ledger of asks, the outbox and the decisions behind them -
`DELEGATION.md` a trusted contact's authority to decide for the person over a goal, quest or task,
`CAPABILITIES.md` what Rouh may do for somebody other than the person - capabilities each gene declares, grants as data, and every call of a contact's case checked on its arguments -
`GENES.md` the gene registry - what a gene is (an ability of Rouh, never a line on the orb), one manifest per gene, the navigation's rail of five group boxes and their links drawn from them, and the rule that a new gene ships a manifest and never a hard-coded link -
`EVOLUTION.md` Evolution - Parameters, Mutations (the Gene library until 14 October 2026), the Gene Pool, the morning deck, mutations and how a gene is learned -
`GOOGLE.md` the Google connection - organisations, tokens, and what the next stage of mail and Drive builds against -
`APPLE.md` the Apple Contacts connection over iCloud's CardDAV,
`docs/landing-architecture.md` why finished work was reported as unfinished and the one landing path designed to end it,
and `SETUP.md` whose Rouh it is: the owner, the installation's own settings and a fresh installation.
