# What Rouh can do, and whether the containers carry it

Petar, 29 October 2026: "okay, fix that, we need it done right away. all of the functionalities, no exception".
Every feature the Creator Rouh has on its server must also work in the containers every Rouh instance runs: `deploy/stack/compose.yml`, the base and `rouh-guard` images, `deploy/container/`, `guard/`.
This file is the one list of those features and where each stands, and it is what the stack test reads.

## How this list is used

- Every row has an id, the feature in plain words, its status **before** this work began (29 October 2026) and its status **now**, and how it is checked.
- **works**: the stack test checks it on every change and it passes. `tests/stack/smoke.py` has a check of that id; a row says works only when that check passes.
- **broken**: known not to work in the containers, with the reason.
- **untested**: nobody had looked yet. Only in the before column once this work is done.
- **manual**: only a person can check it (a real microphone, a real phone); the steps are under "Checks a person makes".
- **replaced**: the containers do the same job another way, named in the row; the row's check proves that way, and must pass as a works row's does.
- **creator-only**: only the Creator Rouh does it, and it moves with the Creator Rouh itself (task 161); left out on purpose. Since 30 October 2026 no row is: the three that were now work through the protected core, behind one setting only the Creator Rouh sets (`ROUH_GUARD_UPSTREAM`), and the stack test runs as a Creator Rouh to check them.

The stack test is `tests/stack/run.sh`: it builds the base and the protected core from the change, starts the real stack with this checkout as the Rouh's own code and every outside service a stand-in (`tests/stack/standins.py`, the same stand-ins the test worlds use), and runs `tests/stack/smoke.py`, which drives what the person drives: the first-run pages in a real Chromium, the page's own socket with the stand-in model calling the tool a message names, and the containers themselves for what only happens between them.
It runs at GitHub on Intel and Arm (`.github/workflows/stack-tests.yml`): for every push to main from "Tests on main", which decides the code a new Rouh installs, and before landing for work that touches the containers' side (`land.sh`, `stack_guard`).
A change that breaks a row marked works fails there.

To change a row: make the feature work, add or fix its check in `tests/stack/smoke.py`, set it to works, all in one commit.
A new feature adds its row and its check in the commit that adds it.

**Windows is not built yet.** Rouh for Windows does not exist: there is no Windows install, and nothing in this list has been checked on Windows. The stack test runs on Linux, on Intel and on Arm (task 161, task 158 step 158-05).

## The stack and its walls

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `stack.check` | The release's stack file passes the stack check it is held to (`guard/policy`) | works | works | `run.sh` runs `stackpolicy.py check` on `deploy/stack/compose.yml` alone |
| `stack.up` | Every part comes up healthy from empty volumes | works | works | `run.sh` waits for every part; the smoke test reads `docker compose ps` |
| `walls.no-root` | No part runs as root once started (the guard only in its own box) | untested | works | `id -u` in the core, the worker and the key proxy |
| `keys.proxy-adds-key` | A run's model call gets the installation's key from the key proxy | works | works | a call from the worker with a wrong key reaches the stand-in model and is answered |
| `keys.worker-holds-none` | The worker holds no key: not in its environment, not on disk | works | works | the worker's environment, `/keys`, its home and `/run/one` searched for the stand-in key |
| `walls.worker-no-database` | The worker cannot reach the database | works | works | `postgres` does not resolve in the worker |
| `walls.worker-no-direct-internet` | The worker reaches the internet only through the key proxy | works | works | a request with the proxy unset fails |
| `walls.proxy-refuses-private` | The key proxy refuses private and internal addresses | works | works | a CONNECT to `core:8021` through the proxy is refused |
| `walls.core-cannot-change-guard` | Rouh cannot change its protected core | untested | works | a write into `/opt/rouh-guard` from the core or the worker fails |
| `guard.change-step` | A change a run proposes is checked, kept as an undo point and put live | works | works | the same: a run's change of Rouh's code is checked, kept as an undo point and put live, and Rouh comes back on it |
| `guard.undo` | An earlier undo point can be put back | works | works | Meta, Changes, Put back on the point before a run's change: the code that runs is that point's again, and Rouh comes back on it |
| `updates.press` | Update to the newest Rouh (Meta, Changes; `update_rouh`): an older Rouh takes the newest release of Rouh's code, its own genes kept on top, a clashing gene's file kept as it was and named, checked by the protected core and live as an undo point, and General says how it went after the restart (`rouh/code_update.py`, task 140, step 140-18) | untested | works | `checks_updates.py`: the Rouh is made one that came from an older release with two genes of its own, a stand-in rouh.land serves a newer release built from that code, the button is pressed, and the code, the undo point and General's note are read |
| `updates.ride` | Ride along: a Connected Rouh takes a new release by itself at a quiet moment, at most once a day, with no press | untested | works | `checks_updates.py`: a second release is served, the choice is Ride along, and the code becomes it with no press, saying it rode along |

## The person's first minutes

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `first-run` | The setup address makes the owner and opens Rouh | works | works | every first-run page answered in a real Chromium, ending signed in on Rouh's page; the address comes from `manage.py setup_link`, and its code is in none of the core's logs (since step 176-25 a start never prints it) |
| `sign-in.email` | Signing in by email: one box, then a link and code by email, or a password | untested | works | the sign-in page signed out in a real Chromium: one email box, no Google; Continue leads to "Check your email" or the password, the password set at the first run signs in, and `manage.py signin_link` prints a one-time link that signs the owner in from another browser |
| `page-loads` | Rouh's page and its main pages open | untested | works | `/`, `/settings`, `/healthz`, and every page the navigation links to (the rail's rows and Anatomy's groups, read off Rouh's page), each opened in a real Chromium with no error in its script |
| `chat-turn` | A typed message is answered | untested | works | a message over the page's socket, answered by the stand-in model |
| `claude.installed` | The worker installs Claude Code on its first start | works | works | `claude --version` in the worker |
| `voice.listen` | Speaking to Rouh through the microphone | untested | manual | a person, below: a browser opens a microphone only for a real press |
| `phone.real` | Rouh on a real phone, from its Home Screen | untested | manual | a person, below: only a real iPhone meets the relay, the certificate and iOS's microphone rules |
| `claude.signin` | Claude Code's sign-in page (`/setup/claude`) | untested | works | `/setup/claude/state` says what the one program in the worker says (signed out), and the page opens in a real Chromium |
| `codex.signin` | Codex's sign-in with a ChatGPT plan (`/setup/codex`, and Settings, Models, Agents' sign-ins) | untested | works | `/setup/codex/state` says what `codex login status` in the worker says, Codex's folder there is `/home/rouh/.codex` on the `worker-home` volume (so a sign-in outlives a rebuilt worker), and the page opens in a real Chromium. The device code itself comes from OpenAI, which a stack test never reaches: it was proved in a browser on 6 November 2026, a real code from `codex login --device-auth` in the worker shown on the page |
| `agents.subscriptions` | Claude Code and Codex subscriptions in Anatomy Connections | untested | works | Both owner-only cards read the worker account state and open at 1440 and 390 px; no vendor sign-in or sign-out is performed by the stack check. Full account switching is proved against isolated worker stubs. |

## Conversation, cards and the things that need only Rouh

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `tool.show-on-screen` | Cards on the canvas | untested | works | `show_on_screen` |
| `tool.memory` | Remembering and the Rules page | untested | works | `remember` |
| `tool.server-health` | How the machine is | untested | works | `server_health` |
| `tool.what-is-running` | What is running (the orb's tree) | untested | works | `what_is_running` |
| `tool.tasks` | Tasks: make, find, read | untested | works | `make_a_task`, then `read_workspace` finds it |
| `tool.clockwork` | Reminders and scheduled work | untested | works | `schedule`, then `upcoming` lists it |
| `tool.goals` | Goals and their steps | untested | works | `set_goal` makes a task, then `goals` lists it |
| `tool.decisions` | Decisions waiting on the person | untested | works | `decisions`, and the page's `/api/decisions` |
| `tool.thoughts` | Thoughts | untested | works | `capture_thought`, then `thoughts` finds it |
| `tool.incubator` | The Incubator's tools | untested | works | `incubator_add`, then `incubator_list` finds it and `incubator_status` parks it |
| `tool.trials` | Trials' tool: trials and the list of problems | untested | works | `trials` lists the trials and the problems |
| `tool.box` | Sealed boxes | untested | works | `new_box`, the person's words put in it through the Boxes page's API, then `open_box` by the number the person said hands them back |
| `tool.payments` | The card vault and spending caps | untested | works | `payments`, and the Payments page's `/api/payments` |
| `tool.shipping` | Shipping preferences | untested | works | `shipping`, and the Shipping page's `/api/shipping` |
| `tool.look-into` | A helper that reads for Rouh | untested | works | `look_into`, its own loop answered by the stand-in model |
| `tool.agent-instructions` | Agent instructions | untested | works | `agent_instructions` adds one in the person's words; the Agent instructions page has it |
| `tool.models` | Which model answers (Anatomy, Rouh Land Account, Models) | untested | works | `model_defaults` reads the tiers, switches the mode to Saver (Anatomy, Rouh Land Account, Models says so) and back |
| `tool.publish` | Public pages and sharing a task | untested | works | a task's built page, `publish_task`, and the link from its card opens signed out |
| `tool.print-page` | A page or a chat as a PDF | untested | works | `print_page` on a page of the workspace with a picture beside it: laid out in the browser container, which the core hands the page and its files (`page_pdf.FOLDER`); the PDF, with the picture in it, is kept beside the page |
| `tool.picture` | Pictures made and changed | untested | works | `make_picture` against the stand-in for OpenAI, with the installation's key from the keys volume |
| `tool.web` | Web search and reading a page | untested | works | a page named in a message is read with `web_fetch` through the stand-in model, which reads it only when Rouh offers the web tools as the model's own |
| `tool.youtube` | YouTube search and transcripts | untested | works | `youtube_search` through the Data API at its stand-in (`ROUH_YOUTUBE_API`, `rouh/testing/fake_youtube.py`), never the scraped results page; the browser fallback for transcripts is off |
| `tool.shell` | A read-only shell for Rouh (`run_command`) | untested | works | `run_command` keeps its read-only rules and runs in the worker, which holds no key, through the one program (`one/shell.py`); a key file is not read |
| `tool.shell-sandbox` | The shell's commands in a box the kernel holds, behind narrowed rules | untested | works | the rules refuse what does more than read (`awk`, `sed`, `curl`, `env`, `find -fls`, `git -c`, `sort -o`); each stage in the worker runs under Landlock (`rouh/sandbox.py`; Docker's filter refuses bubblewrap its namespaces), `ROUH_SANDBOX=required` there, and `server_health` says so; the same commands handed to the worker's shell past the rules write nothing and reach no one; `grep` and `ls` still answer |

## Accounts the owner connects (checked with stand-ins)

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `google.connect` | Connecting Google (the organisation's client, then the person's consent) | untested | works | the stand-in's: Settings, Email, the organisation's client typed in, Connect Google, Allow on the stand-in's consent page, all in a real Chromium; Settings then shows the account |
| `google.mail` | Gmail: read, send, draft, forward | untested | works | the stand-in's Gmail: `read_recent_mail` reads its inbox, `send_mail` reaches it |
| `google.calendar` | Calendar | untested | works | the stand-in's Calendar: `list_calendar_events`, and `create_calendar_event` reaches it |
| `google.drive` | Drive and Docs | untested | works | the stand-in's Drive: `search_drive` finds its document, `read_doc` reads it |
| `mail.alerts` | New mail handled as it arrives | untested | works | the Pub/Sub topic and On posted as the New mail card does, Gmail's watch made at the stand-in, and new mail read and on Rouh's mail log after its push (`mail.push`) |
| `mail.push` | Gmail's push (`/hooks/gmail/<token>`) | untested | works | mail delivered at the stand-in with its note lost, then Pub/Sub's push posted to the hook's public address (the published port, as the relay hands it on): taken, and the message on the mail log; an address nobody holds is a 404 |
| `contacts.icloud` | iCloud contacts | untested | works | the stand-in's iCloud: Settings, Apple filled in in a real Chromium, then `search_contacts`; the home is on a partition host beside the one asked (`p52.standins`), as iCloud's is |
| `slack` | Slack | untested | works | the stand-in's Slack: the three tokens posted as Settings, Slack posts them, Socket Mode opened, then `slack_channels` lists the workspace |
| `telegram.send` | Messages to the owner's phone | untested | works | `send_telegram`, then the message is on the stand-in phone |
| `telegram.chat` | Talking to Rouh from Telegram | untested | works | a message written at the stand-in phone becomes a turn, and the answer reaches the phone |
| `brevo.letters` | Rouh's own letters (sharing by email, resets) | untested | works | a forgotten password sends the owner a letter through the stand-in for Brevo |
| `hue` | Philips Hue lights | untested | works | the stand-in's Hue cloud: the Hue app posted as Settings, Hue posts it, Connect, Allow on its sign-in page in a real Chromium (`ROUH_HUE_SIGN_IN`), the link button, then `hue` lists the lights |
| `vacuum` | The robot vacuum | untested | works | the stand-in's Dreamehome: the account posted as Settings, Dreame posts it, then `vacuum` reads the robot |
| `cloudflare` | Cloudflare zones | untested | works | the stand-in's Cloudflare: a zone and its token posted as Settings, Cloudflare posts them, then `cloudflare` reads the zone's records and its Email Routing (`email_routing_status`), lists its Origin CA certificates (`origin_certificates`) and deletes one named record (`dns_delete`), refusing a record that matches none |
| `stripe` | Payments through Stripe | untested | works | the stand-in's Stripe: the restricted key posted as Payments posts it, then `stripe` |
| `stripe.webhook` | Stripe's events (`/hooks/stripe/<token>`) | untested | works | Payments makes the webhook at the stand-in; an event signed with its secret, posted to the hook's public address (the published port, as the relay hands it on), is taken and the owner told on the phone; a forged one is refused |
| `linkedin` | LinkedIn research | untested | works | `linkedin_search` against the stand-in for Apify |
| `synapse` | Synapse, the memory, with its vectors | untested | works | `synapse_add` into Synapse Master with vectors from Voyage's stand-in, then `synapse_find` |
| `meetings` | The meeting library | untested | works | a meeting made in the library's stand-in, its webhook taken (`meetings.webhook`), then `meeting_search` finds it |
| `meetings.webhook` | The meeting library's webhook | untested | works | a post to `/api/hooks/meeting-library` through the published port: signed with the settings file's secret it is taken, signed wrongly it is a 401 |
| `voice.speak` | Rouh speaks its answers | untested | works | spoken replies on over the page's socket (`set_mode`), and an answer's audio reaches the page from the stand-in for ElevenLabs, which was asked to say it |
| `phone.relay` | Your Rouh's URL through rouh.land's relay (the phone address until 7 November 2026) | untested | manual | a person, below: the stack test's Rouh is an Independent Rouh, and the relay's side (frps, its claim endpoint) and Let's Encrypt are rouh.land's and the internet's, with no stand-in here |

## The one program and its runs

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `one.paired` | Rouh is paired with the one program | works | works | `one_runs` answers |
| `one.attach-late` | Rouh finds the one program when it pairs after Rouh started | untested | works | the pairing taken away, Rouh started again, the pairing put back: Rouh finds the one program and its tools |
| `one.run` | A run starts, works and finishes | untested | works | `one_start` with the stand-in agent (`tests/stack/fake-claude`); the run does what its brief says and finishes |
| `one.run-screen` | The run screen on Rouh's page (`/one/`) | broken | works | `/one/runs` through the core, signed in to Rouh (`rouh/onebridge.py`) |
| `one.terminal` | A run's terminal on Rouh's page (`/one/ws`) | broken | works | the one program's socket through the core, answered and not refused as an unknown browser |
| `one.phone-question` | A run's question answered from the phone (`/one/q/<token>`) | broken | works | `/one/q/<token>` through the core with no sign-in, answered by the one program |
| `one.phone-note` | A run's question sent to the owner's phone | broken | works | the one program's phone note, from the worker, sent with Rouh's own bot through `/internal/phone` (the worker holds no bot token) |
| `one.many-runs` | As many runs at once as the owner sets | untested | works | `ONE_MAX_RUNS` from the settings file is in the one program's environment, and with 2 set two runs work at once and a third waits, saying why (`tests/stack/checks_limits.py`); the gates also keep to the worker's own `mem_limit` (`ROUH_WORKER_MEMORY`), read from its read-only cgroup |
| `one.run-memory` | A memory limit for each run | broken | works | no cgroup in the container, so the run's holder adds up its processes' memory from `/proc` (`one/runprocs.py`): a run holding 400 MB over the test's 256 MB `ONE_RUN_MEMORY_MAX` is ended with what it started, failed, and the program says why (`ended_why`) |
| `one.run-stop` | Stopping a run ends everything it started | broken | works | `one_stop` on a run that started a detached `setsid sleep`: the run ends and the sleep is gone, found by the `ONE_RUN` mark in its environment (`one/runprocs.py`) |
| `one.deploy-keeps-runs` | A deploy of the one program does not kill the runs | broken | works | the protected core's signal for the worker moved, as a change to the program going live moves it: `rouh-guard-run` starts the program again in place, and a working run keeps its holder and its process, neither lost nor started again (`tests/stack/checks_limits.py`) |
| `core.deploy-waits-for-answers` | No deploy cuts a chat answer | broken | works | the protected core's signal for the core moved in the middle of a slow answer: `rouh-guard-run` waits until Rouh says no answer is in progress (`guard/rouh_guard/deploywait.py`, `rouh/answers_now.py`), the answer arrives whole and Rouh starts again after it, and the wait is written down; moved again with nothing being answered, it goes at once (`tests/stack/checks_limits.py`) |
| `runs.internet` | A run reaches the internet through the key proxy (git, npm, pages) | untested | works | the run fetches https://example.com through the key proxy |
| `runs.ssh` | A narrow way from runs to the owner's other servers | broken | works | ssh in the worker goes through the key proxy (`rouh-connect`): a server listed in `ROUH_KEYPROXY_ALLOW` is reached, any other is refused; `rouh-ssh-key NAME` makes one key per purpose |
| `runs.proxy-grant` | More of the internet opened to runs for some hours from the owner's machine (`rouh-proxy-grant`, `rouh-open`, `deploy/grants/`) | untested | works | `rouh-grant open` in the keys volume, with no restart of the key proxy: `all` reaches a public server on a port nothing lists and never a private address or the core, and is refused again after its end and after `revoke all`; a name grant covers the names under it; `open ssh NAME` opens both at once and `revoke ssh` closes one; `servers add` puts a server under an open servers grant; `lan` reaches the office network (the stand-ins' network here) but never a container or loopback; each connection a grant let through is in the key proxy's log as `GRANT <grant>` |
| `runs.github` | GitHub for runs, with the owner's token, for some hours (`rouh-github-grant`, `deploy/grants/`) | untested | works | with no grant a run's request reaches GitHub's stand-in with nothing added and its own credential taken off; with `rouh-grant github set` the token is added (bearer for the API, password for git, also for a request named by its Host as gh sends it); after its end nothing is added and the prune deletes it; the token is in no log and not in the worker |
| `callbacks.notify-owner` | A run tells the owner (`notify_owner`) | broken | works | the run calls `notify_owner` over Rouh's MCP server for runs, and Rouh queues the note (`rouh/workerkey.py`) |
| `callbacks.job-tools` | A run uses Rouh's tools (mail, calendar, Drive, memory) | broken | works | the run lists Rouh's job tools over the same server, which Rouh hands it |
| `callbacks.agent-instructions` | Runs start with the agent instructions | broken | works | the worker asks Rouh for a run's agent instructions with its key |
| `walls.internal-needs-key` | Rouh's internal addresses refuse a caller with no key, from another container or the published port | untested | works | the worker, and the published port, asking with no key are refused |
| `callbacks.tasks` | A run sets a task's status and tree (`rouh-task`, `rouh objecttree`) | broken | works | a run makes a task with `rouh objecttree` (the tree carried to Rouh and the changes made back in the checkout) and sets its status with `rouh-task`; the task reaches Rouh's workspace when the run lands |
| `workspace.one` | Rouh and its runs work on one workspace | broken | works | a task Rouh makes reaches the runs' workspace, and a run's committed note reaches Rouh's: one main in the workspace volume, written only by the core, the runs' work handed over as bundles (`rouh/workspace_follow.py`, `bin/rouh-land`) |
| `workspace.github` | The workspace saved to GitHub | broken | works | main is pushed to the owner's repository (`ROUH_WORKSPACE_REMOTE`, a stand-in git server) and what is pushed there comes back |

## Rouh changing itself, and the nightly work

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `self.improve` | Rouh changes its own code when asked (`improve_myself`, Gene therapy) | broken | works | `improve_myself` starts a run in a clone of the code; its commit is checked by the protected core and becomes the code that runs |
| `self.deploy` | A change goes live | replaced | replaced | the protected core's change step puts a checked change live (`guard.change-step`), in place of `deploy_myself` and the one program's update button |
| `self.gene-grow` | Growing a gene | broken | works | a gene drafted and grown starts its run in a clone of the code; its `./land.sh` hands the work to the protected core (`bin/rouh-land`) |
| `self.gene-log` | Each change written into its genes' history | broken | works | after a run's change goes live through the protected core, Read now in the gene log reads it in; the run it came from is written down beside it (`rouh/codechanges.py`) |
| `nightly.feature` | The nightly feature run (04:30) | broken | works | its home task made, its Clockwork row made as Rouh makes it, then Try it now starts it in the worker |
| `nightly.refactor` | The nightly code tidy-up (03:00) | broken | broken | Its row is there and Try it now starts it, but on a Rouh whose refactoring model is OpenAI's it runs on Codex, and Codex was never signed in in the worker: nights 17 to 21 (1 to 5 November 2026) each stopped on Codex's sign-in screen a minute in. Since 5 November such a run ends at once saying so (`one/runs.py`, `_codex_signed_in`); it works once Codex is signed in in the worker (`codex login --device-auth`), or the run is billed to the OpenAI API key, or a Claude model is picked for it. Until 5 November this row said works because Try it now started it. Since 6 November the night keeps its run's own reason (`nightly_refactor.run_ended`, `settle`), so the morning check and Clockwork say why instead of "left no reason". Since 6 November 2026 Codex is signed in from Rouh's page, `/setup/codex` (`one/codex_signin.py`), with no terminal, and a run refused for it says one line, "Codex needs signing in again", with that address, told to the phone once rather than once a run; this row says works once a night has run on it |
| `nightly.synapse` | Synapse's nightly experiment (05:00) | broken | broken | Its worker cannot reach the database or the frozen benchmark copy from the worker container (by design: it is off the database network and holds no password), so nights #47 to #51 (1 to 5 November 2026) did nothing and left no reason. Since 5 November Rouh does not start the worker there and writes the night as failed with that reason (`nightly.cannot_measure`, checked in `jobs.watched`). It works once the owner's Decision 422 (a safe way for a job to reach the live database) names the way (`ROUH_SYNAPSE_NIGHTLY_ROUTE`). Until 5 November this row said works because Try it now started it |
| `nightly.callbacks` | The nightly runs' own tools (`nightly_*`, `refactor_done`, `case_fix_*`) answer a run in the worker | broken | works | each internal address asked from the worker with its key, and not refused |
| `nightly.case-fix` | Fix runs for a mail case that went wrong | broken | works | a fix run starts as any run of the program (`one.run`); its tools answer it from the worker (`nightly.callbacks`) |
| `nightly.base-patch` | The nightly base fixes (00:40), as a pull request on main that merges itself when its checks pass | creator-only | works | on a Creator Rouh (`ROUH_GUARD_UPSTREAM`), a level made on top of rouh-core's main as the protected core fetches it is checked by the protected core and pushed as `base-patch/<level>` (`push_branch`); a level that changes more than `deploy/container/base/` is refused; published and failed levels are read back from the refs the core fetches into /code |
| `creator.push-main` | Accepted changes pushed to rouh-core's main | creator-only | works | the protected core makes its key for rouh-core (`rouh-guard upstream-key`, kept in the guard's own volume: neither the core nor the worker can see it); Rouh's checked change, live as an undo point and healthy for `ROUH_GUARD_UPSTREAM_SETTLE`, is pushed to the stand-in rouh-core's main, never forced (guard/rouh_guard/upstream.py). Every Rouh instance leaves the setting blank and pushes nothing |
| `creator.merge-runs` | Many runs' work fitted together before proposing | creator-only | works | rouh-core's main moves while a run works; the run's landing (`bin/rouh-land`) fits its work onto it with land.sh's own replay and merge steps (`ROUH_LAND_FIT_ONLY`, into a scratch repository), the protected core checks the result, and it is pushed on top of the other run's work |
| `crew.tools` | The older crew of workers (`assistant_job`, `delegate_task`, `check_tasks`) | replaced | replaced | the one program's runs do this work: `assistant_job` and `check_tasks` are offered without the crew and start runs of the program |

## The live browser

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `browser.live` | The live browser Rouh drives and the person watches | broken | works | the `browser` tool opens the stand-in website in the browser container (`ROUH_BROWSER_REMOTE`), and a tab watching gets its screen (`browser_frame`); the browser container is not root, holds no key or file of anybody's, cannot reach the database or the internet past the key proxy, and a private address is refused |
| `browser.handoff` | The person takes the browser over and hands it back | broken | works | `browser_take`, Rouh held off, the person's click on the page (`browser_input`), `browser_give`: Rouh is told in its chat that they clicked once, and sees the page as the click left it |
| `browser.fallback` | Pages and transcripts read in a browser when a plain fetch fails | broken | works | a page that turns web_fetch away (403) is read again in the browser container (`browser_fetch`), and its words reach the answer |
| `signups` | Sign-ups and purchases in the live browser | broken | works | a sign-up asked for in the person's words is authorized, the form filled in the browser container with `fill_password` (the model never passes the password) and sent; the stand-in website gets the email and the password the person gave |

## Settings an installer puts in

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `install.telegram` | Telegram's bot, from the settings file | broken | works | `ROUH_TELEGRAM_BOT_TOKEN` and `ROUH_TELEGRAM_CHAT_ID` in the settings file are the bot (`telegram.send`) |
| `install.brevo` | Brevo's key, from the settings file | broken | works | `ROUH_BREVO_API_KEY` in the settings file is the key (`brevo.letters`) |
| `install.meeting-library` | The meeting library's address and key, from the settings file | untested | works | the core reads `MEETING_LIBRARY_URL`, `MEETING_LIBRARY_KEY` and `MEETING_LIBRARY_WEBHOOK_SECRET` from the settings file, with nothing missing |
| `install.max-runs` | How many runs at once, from the settings file | untested | works | `ONE_MAX_RUNS` in the settings file reaches the one program and is held to, as `one.many-runs`; `ROUH_WORKER_MEMORY` and `ONE_RUN_MEMORY_MAX` sit beside it (`deploy/stack/settings.env.example`) |

## The machine, backups and moving in

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `machine.load` | The machine's load on the orb | untested | works | `/api/machine/load` answers with the core container's own processors and processes |
| `machine.ups` | The UPS's state on the orb | broken | works | `/api/machine/load` reads the UPS over NUT's own protocol from the core (`ROUH_UPS=ups@host.docker.internal`; a stand-in upsd in the test) |
| `backup.daily` | A database copy every night | broken | works | the backup part (`guard/bin/rouh-backup`, PostgreSQL's own `pg_dump`) copies the database into the backups volume, rouh's alone and read-only to the core, nothing in it running as root; `server_health` says when the newest was made; a restore under a running core is refused, and with the core stopped it puts a changed saved login back as it was |
| `backup.offsite` | The weekly encrypted copy to R2 | broken | works | `offsite_backup run` in the core sends the whole Rouh (`rouh/bundle.py`) to the stand-in for R2, encrypted in age's format (`rouh/agefile.py`); not set up, it says so and sends nothing; the copy holds nothing readable, the real `age` opens it with the key `run.sh` made, its keys are this Rouh's and its database restores |
| `jobs.watched` | Each scheduled job checked against what it really left behind, said once a morning when one did not work | broken | works | `manage.py job_watch --json` in the core lists every scheduled job and the backups; server_health has the newest check (`scheduled_jobs`); the Synapse night is held back with its reason (`rouh/job_watch.py`) |
| `linux.server` | Rouh on a Linux server with no screen: the one command, `rouh setup` in the terminal, the `rouh` command, the nightly update, Keep or Wipe on uninstall and Bring back (task 176, step 176-25) | untested | manual | below: a whole clean server, which the stack test does not stand up |
| `edge.domain` | The owner's own domain: the stack's edge part (Caddy) on ports 80 and 443 with a Let's Encrypt certificate, only with a domain set and an owner | untested | manual | below; the stack check's side by `guard/policy/fixtures/check.py` (expect-edge.json: refused with no domain, on another port, changed, or for another part) |
| `import.existing` | Bringing in an existing Rouh: its database, key file and files | broken | works | `export_rouh` in this stack, never printing a key, then `linux_stack.import_bundle` into a fresh second stack, which starts with the same owner and signed-in cookie, the saved login opening and the file of its data directory there |

## Every other gene and page

Every gene in `rouh/genes/owners.json` and every page Rouh serves that no row above covers, each checked in `tests/stack/checks_genes.py`: the page's own address signed in, the page's own API doing what the page does with it, a tool called as the model calls it, or, for a gene that only changes what a turn or a run is told, its own words asked for in the core.

| ID | Feature | Before | Now | How it is checked |
|---|---|---|---|---|
| `page.in-browser` | Rouh's page in a real browser | untested | works | `/` in a real Chromium, signed in: every file it loads answers, no script fails, and it goes live on its socket |
| `page.heartbeat` | The heartbeat (Anatomy, Behaviour, Heartbeat) | untested | works | its page and state, then Beat now |
| `page.beats` | The heartbeat's beats | untested | works | its page and `/api/heartbeat/beats` |
| `page.quests` | Quests | untested | works | `/quests` and `/api/quests` |
| `page.goals` | The Goals page | untested | works | a goal saved on the page is listed there |
| `page.decisions` | The Decisions page | untested | works | `/decisions` and `/api/decisions` |
| `page.brief` | The morning brief and its settings | untested | works | Make it now makes today's brief; the brief, the past briefs and its settings answer |
| `page.receipts` | Receipts | untested | works | `/receipts` and the month's rows |
| `page.control` | The control room | untested | works | `/control` and its clusters |
| `page.thoughts` | The Thoughts page | untested | works | a thought typed there is listed |
| `page.box` | The Boxes page | untested | works | a sealed box made there opens again with what was put in |
| `page.rules` | The Rules page | untested | works | the defaults are on it and none is locked, every rule says when it is told; a rule added there is listed, with its Agent switch on is in what an agent starts with, and deleted is gone from both |
| `page.agent-instructions` | The Agent instructions page | untested | works | an instruction added there is in what a run is handed |
| `page.anatomy` | Anatomy, with its six groups | untested | works | `/anatomy`, each group's page and `/api/anatomy`; every old address of a moved section, You, Profile among them, is not found |
| `page.profile` | About You (Profile until 4 November 2026) | untested | works | its page at `/anatomy/you/about-you`, a nickname saved is kept, and who you are and your company are kept on your own contact card |
| `page.location` | Location and time | untested | works | a point the page reports is kept with its clock |
| `page.silos` | Silos | untested | works | a silo added is listed, and taken out is gone |
| `page.models` | The Models page | untested | works | the page and its mode, tiers and uses |
| `page.services` | Services (Money) | untested | works | a service added is listed |
| `page.payments` | The Payments page | untested | works | a billing entity added is listed |
| `page.shipping` | Shipping | untested | works | who receives a parcel is kept |
| `page.signups` | The Sign-ups page | untested | works | its hours and grants |
| `page.stats` | Stats | untested | works | its page, its Event log tab and `/api/settings/stats` |
| `gene.event-log` | The event log of what the person does | untested | works | an event the page sends is taken and counted on Stats' Event log |
| `gene.llm-request-log` | The log of every request made of a model | untested | works | a turn's request is in the day's usage and in the turn records' export |
| `page.rouh-land-account` | Your rouh.land account (You, Your account; Your profile until 7 November 2026): whether you have a rouh.land account and whether this Rouh is connected to it | untested | works | Your account's page and `/api/rouh-land/account`: a free Rouh, not connected, nothing wrong, and none of the Rouh's own fields |
| `page.build` | This build (Meta): the session, version, commit and its day | untested | works | its page carries the session, version and commit |
| `page.birthday` | Your Rouh (Rouh profile until 7 November 2026; Birthday until 4 November) | untested | works | set up on its own it is a free Rouh: no birth, no name, its nickname kept, one plain line |
| `page.genes` | Gene registry (Meta; Rouh Land Account, Gene Pool until 7 November 2026): shared genes and the registry | untested | works | its page and `/api/settings/genes` |
| `page.home` | Home: lights and the vacuum | untested | works | `/home`, and its lights and vacuum say they are not connected |
| `page.metabolism` | Metabolism: runs, work and spend | untested | works | `/metabolism`, the work asked for and the spend |
| `page.gaps` | The agent loop gaps page | untested | works | `/gaps` and its list |
| `page.demo` | Demo mode | untested | works | turned on it is on, turned off it is off |
| `page.offline` | Offline: the service worker and the sealed copy | untested | works | `/sw.js`, `/offline` and every part of the offline copy |
| `page.evolution-parameters` | Evolution, Parameters | untested | works | the parameters saved are kept as the person's |
| `page.mutations` | Evolution, Mutations, and the gene log | untested | works | its pages, the month and the gene log |
| `page.gene-pool` | Evolution, the Gene Pool | untested | works | its pages, and what this Rouh shares and is offered |
| `page.incubator` | Evolution, the Incubator: every idea for a new gene or a mutation | untested | works | its page, an idea added there is listed and opens whole, its category changed |
| `page.nightly-run` | Evolution, the nightly run's own page: its schedule, switch, nights and rules | untested | works | its page, and its caps and nights read |
| `page.trials` | Evolution, Trials: a made-up person tries each change, and the problems they hit | untested | works | its pages, a trial started and a step refused without a tester, and the list of problems |
| `page.trusted-contacts` | Trusted contacts, their levels and grants (capabilities, delegation) | untested | works | its page, its grants page, and every grant there is to give |
| `page.mail-approvals` | Mail approvals | untested | works | `/mail/approvals` and its queues |
| `gene.mail-replay` | A trusted contact's mail judged case by case | untested | works | `python -m rouh.mail_replay` in the core: every kept case comes out as it must |
| `page.sources` | Sources checked | untested | works | `/sources` and `/api/sources` |
| `gene.voice-detection` | Voice detection in the browser | untested | works | `vad.js`, ONNX Runtime and the Silero model are served with the types a browser runs them as |
| `gene.orb-sound` | The orb's sounds | untested | works | `app/orb_sound.js` is served as a script; hearing it is `voice.listen`'s person |
| `gene.falling-stars` | Falling stars on the navigation | untested | works | `app/stars.js` is served as a script, and the page runs with no script error (`page.in-browser`) |
| `page.account` | Account: who is signed in | untested | works | its page names the owner; with no sign-in, Rouh's page sends to the sign-in page |
| `gene.ask-ai-edit` | Ask AI changes a page when asked | untested | works | a page written into a task, Ask AI asked to change a heading (the stand-in model's `edit_page`), and the page Rouh serves has the change |
| `gene.page-history` | A page's history, and a version kept as an option | untested | works | the change is in the page's history with who made it, and kept as an option it gives the page two versions |
| `gene.askai-show` | Show me where, beside a change Ask AI made | untested | works | `/api/askai/where` names the part of the page the change is in |
| `gene.copy-exact` | Copy kept word for word | untested | works | copy given with the question that is not on the page after the change is said to the reader |
| `gene.page-facts` | Facts told on a page | untested | works | Ask AI's `keep_fact` on the page keeps the fact in the task's notes |
| `page.shared-public` | A page made public | untested | works | its `/p/` link opens with no sign-in, and taken down it does not |
| `page.shared-guests` | A page shared with people by email, who sign in with rouh.land, and who opened it | untested | works | On its own, sharing with a person is refused; Connected, a person invited is listed with when they opened it, `/shared` answers, and their link opened signed out goes to `/shared/in` and on to the relay address |
| `gene.page-comments` | Comments pinned on a page | untested | works | a comment left is listed |
| `gene.page-highlights` | Highlights on a page | untested | works | a highlight kept is listed |
| `gene.page-definitions` | Define, beside Ask | untested | works | a passage defined by the model is kept and listed |
| `gene.x-ray` | The X-ray layer over a report | untested | works | an X-ray beside the page is laid over it as it opens on the canvas |
| `gene.self-link` | Links to Rouh's own pages read inside Rouh | untested | works | `read_rouh_link` on the page's own address reads it as the owner |
| `gene.since-read` | Since you last read it | untested | works | `/api/since-read` for the page |
| `gene.page-pdf` | A page as a PDF for paper (Printable PDF), from the page's Share | untested | works | `/api/page-pdf` on a page of a task starts it, and the PDF is made, laid out in the browser container as `tool.print-page` is, and kept |
| `gene.page-listen` | Listen to this page | untested | works | the model writes the narration and the stand-in voice reads its first part |
| `gene.forks` | Conversation forks | untested | works | a fork of a chat answers in a new chat that knows its parent |
| `gene.memory-recall` | Memory recalled before Rouh answers | untested | works | a turn sends the page its recall reading |
| `gene.addresses` | Every chat and task has its own address | untested | works | `/chat/<id>` and `/task/<folder>` open Rouh's page, and the socket opens that chat |
| `gene.search` | Search | untested | works | the page's search finds the task by its words |
| `gene.notifications` | Notifications | untested | works | a notice reaches the page, and marked read there it is read |
| `gene.plain-words` | Plain words | untested | works | a term asked about is explained in every later turn and run |
| `gene.offline-outbox` | What was done offline, carried out | untested | works | a note sent from a device's offline outbox is given to Rouh |
| `page.mail-case` | A trusted contact's mail case page | untested | works | a case's page and `/api/mail/case/<key>`; a case that is not there is 404 |
| `gene.feedback-board` | The feedback board (Gene therapy) | untested | works | feedback given becomes a feature request on the board, with automatic building off for the check |
| `gene.task-rename` | Rename a task in words | untested | works | `rename_task` in the task's chat, and the task list has the new name |
| `gene.step-move` | Move a step in words | untested | works | `move_step` takes a task's step out as a task of its own |
| `gene.short-answers` | Short answers in Ask AI | untested | works | its words for Ask AI with "shortly", and none when more is asked for |
| `gene.askai-words` | Where your words are | untested | works | quoted words found on the page before Ask AI answers, and nothing without them |
| `gene.askai-follow` | Follow-ups stay where you were | untested | works | the part of the page a change was in is found |
| `gene.each-point` | Every point accounted for | untested | works | a job asked to apply comments is given the rule, and another is not |
| `gene.follow-through` | Followed through | untested | works | a step promised for after a job is found, and a plain "I'll tell you" is not |
| `gene.chat-kinds` | General and other chats as two kinds | untested | works | General is the general kind and another chat is not |
| `gene.newest-first` | Newest in the thread first | untested | works | a reply over a newer message is held with what it says, given Gmail's answers for a thread |
| `gene.mail-pictures` | Pictures in mail seen | untested | works | a picture attachment is shown to the model as an image and kept in the chat's files |
| `gene.sent-by-you` | Sent by you | untested | works | a reply sent from the person's own mail is found in the sent mail and its section written |
| `gene.copies-in-step` | Copies kept in step | untested | works | runs are told the rule |
| `gene.asked-again` | Asked again | untested | works | a request typed on two earlier days is offered as scheduled work the third time |
| `gene.answered-in-chat` | Answered in a chat | untested | works | a waiting decision the person answered in a chat shows their answer |
| `gene.meeting-prep` | Before you meet | untested | works | the outside guests of a meeting are found, the person and the room left out |
| `gene.what-to-raise` | What to raise | untested | works | with no mail it says so; with an email, the model's reading says where things stand |
| `gene.what-to-raise-remembers` | What to raise remembers | untested | works | a correction kept is remembered for the next meeting with them |
| `gene.after-meeting` | After the meeting | untested | works | a recorded meeting's action items are read as the work it calls for |
| `gene.meeting-guests` | Meeting guests looked up on LinkedIn | untested | works | a meeting's guests to look up are found |
| `gene.meeting-contacts` | Meeting guests into contacts | untested | works | a small meeting is not skipped, and `manage.py meeting_contacts status` answers |
| `gene.owed-to-you` | Owed to you | untested | works | a meeting in Synapse with an action an outside guest owes is a line of the brief |
| `gene.next-meeting` | Agreed, not booked | untested | works | a next meeting agreed in a meeting's notes is a line of the brief |
| `gene.others-changed` | Changed by others | untested | works | a page somebody else changed is a line of the brief, and Seen answers |
| `gene.not-opened` | Not opened yet, and Remind them | untested | works | a share not opened in three days is a line of the brief, and Remind them is offered beside the person |
| `page.draft-edits` | Draft edits | untested | works | what the person changed in a drafted email is listed on its page |
| `gene.to-send` | To send from your mail | untested | works | a reply a task drafted waits on the task's page, and Write it in Gmail answers |
| `gene.doc-changes` | What changed in a doc | untested | works | `doc_changes` on the stand-in's Doc names the paragraph added since the day |
| `gene.doc-comments` | Comments read with the doc | untested | works | `read_doc` gives the Doc's open comments |
| `gene.doc-last-changed` | Who last changed it | untested | works | `read_doc` gives who last changed the Doc |
| `gene.doc-comment` | Leave a comment | untested | works | `comment_on_doc`, and the comment is on the stand-in's Doc |
| `gene.doc-reply` | Answer a comment | untested | works | `reply_to_doc_comment`, and the answer is on the stand-in's Doc |
| `gene.task-docs` | The task's documents | untested | works | a Doc in the task's notes is on its page, with What changed and its name |
| `gene.doc-add` | Add a document | untested | works | a pasted Doc link is kept in the task's notes, and the same again refused |
| `gene.doc-on-page` | On the page? | untested | works | the task's Doc compared with its pages |
| `gene.task-comments` | Comments on the task's documents | untested | works | the open comments on the task's Doc are listed |
| `gene.comments-by` | Their comments | untested | works | `comments_by` finds one person's comments on the Docs the tasks link |
| `gene.new-comments` | New comments on your documents | untested | works | the brief's line finds the new comment on the task's Doc |
| `gene.deck-slides` | Decks read slide by slide | untested | works | `read_doc` on the stand-in's deck gives each slide with its notes and the comment on it |
| `gene.find-slides` | Find a slide | untested | works | `find_slides` finds the slide by its words, with a link to it |
| `gene.talk-deck` | The deck for your talk | untested | works | the brief's line names the slide with no notes and the comment nobody answered |
| `gene.rehearse` | Rehearse | untested | works | the task's deck has Rehearse, is read slide by slide for it, and a slide's picture is given |
| `gene.doc-pictures` | Pictures in docs seen | untested | works | `read_doc` on the stand-in's Doc marks its picture where it stands |
| `gene.page-asks` | What they asked on your pages | untested | works | `page_asks` lists the request made to Ask AI on the page, in its own words |
| `gene.not-handed` | Made, not handed over | untested | works | the brief's line names who the task's work is for, and Handed over and Undo answer |
| `gene.open-items` | Open on this task | untested | works | the task's open items are on its page, and Done marks one done in its notes, and Undo |
| `gene.sheet-tabs` | Sheets read tab by tab | untested | works | `read_doc` on the stand-in's sheet gives its second tab by name, with its rows |
| `gene.sheet-write` | Written into a sheet | untested | works | `edit_sheet` writes a cell and adds a row on the stand-in's sheet, saying what the cell held |
| `gene.share-ends` | Shared until | untested | works | a share is given an end in the Share panel, and once it has passed the share is taken away |
| `gene.task-dates` | Dates your tasks wait on | untested | works | the brief's line names a date an open task's notes say is due, and Done and Undo answer |
| `gene.doc-suggestions` | Suggested edits read as suggestions | untested | works | `read_doc` on the stand-in's Doc marks its suggested deletion and insertion where they stand, and counts them |
| `gene.slide-write` | Written into a deck | untested | works | `edit_slides` replaces a word on the stand-in's deck and writes its notes, saying what they said |
| `gene.share-meeting` | With a meeting's guests | untested | works | the Share panel offers a meeting whose title shares a word with the page, and Share with them shares with its guest |
| `gene.drive-files` | Files in Drive read | untested | works | `read_doc` on a PDF in the stand-in's Drive reads its words and says it was a PDF |
| `gene.raise-attached` | What to raise reads what is attached | untested | works | the document attached to a meeting's invitation is read into What to raise's question |
| `gene.drive-copy` | A copy made when asked | untested | works | `copy_drive_file` copies the stand-in's Doc and fills in its words, the original unchanged |
| `gene.meeting-attach` | Attach to a meeting | untested | works | a task's Doc is offered the meeting about it the owner organises |
| `gene.askai-docs` | The Google Doc you link, read by Ask AI | untested | works | a Doc linked in a question is read before Ask AI answers |
| `gene.page-gdoc` | A Google Doc of this page | untested | works | the page is made into a Doc in the stand-in's Drive |
| `gene.shared-with-you` | Shared with you | untested | works | the brief's line answers Seen and Undo |
| `gene.notes-missing` | Meetings with no notes | untested | works | the brief's line answers its acts |
| `gene.inside-files` | Files inside files read | untested | works | a zip archive with a forwarded email in it is read, the email's words too |
| `gene.calendar-away` | Away and focus time | untested | works | `block_my_time` puts an out-of-office on the stand-in's calendar, with its message |
| `gene.flight-open` | Flights left open | untested | works | a flight on another calendar, with the main calendar free then, is found for the brief |
| `gene.task-time` | Time before its date | untested | works | Find time on a task due soon says the free hours before its date |
| `gene.mail-invites` | Invitations read on your clock | untested | works | `read_mail` on an Outlook-style invitation says its time on the person's clock and the sender's |
| `gene.invite-missing` | Invitations not in your calendar | untested | works | an invitation on none of the stand-in's calendars is found for the brief |
| `gene.when-free` | When others are free | untested | works | `when_free` reads a colleague's busy times through free/busy and names one Google would not show |
| `gene.busy-guard` | Not booked over someone busy | untested | works | `create_calendar_event` with a busy guest is not booked, and other times are offered |
| `gene.meet-link` | Booked with a call link | untested | works | `create_calendar_event` with a guest and no place asks the stand-in for a Meet link and says so |
| `gene.no-place` | Meetings with nowhere to meet | untested | works | a meeting with a guest and no place, made on the stand-in's calendar, is found for the brief, and Add a Meet link gives it one |
| `gene.calendar-link` | A calendar link read | untested | works | a published calendar with a weekly repeat, a date taken out and a moved occurrence is read on the person's clock |
| `gene.address-check` | A mistyped address caught | untested | works | an address a letter off the owner's own is held, with the known one named; a new address is not |
| `gene.away-replies` | Away, said their automatic reply | untested | works | `create_calendar_event` with a guest whose automatic reply says they are away is held, with the reply's words |
| `gene.not-arrived` | Did not arrive | untested | works | a bounce in Rouh's inbox becomes a notice naming the address that failed |
| `gene.to-answer` | Waiting on your answer | untested | works | `to_answer` finds an email that asked the owner something and was not answered |
| `gene.inbox-unsubscribe` | Unsubscribe in the inbox card | untested | works | a list's one-click unsubscribe is offered, and refused for an address on the machine's own network |
| `gene.attach-promised` | A file promised, not attached | untested | works | `send_mail` with "please find attached" and no file is held, and nothing is sent; so is "please find the proposal attached" |
| `gene.not-said-yes` | Guests who have not said yes | untested | works | a meeting of the owner's tomorrow whose guest has not answered, made on the stand-in's calendar, is found for the brief |
| `gene.public-holidays` | Public holidays read from Google | untested | works | `public_holidays` reads a day from the stand-in's Polish holiday calendar and names it |
| `gene.inbox-remind` | Remind me about this email | untested | works | Remind me makes one reminder for tomorrow morning naming the email's sender |
| `gene.their-clock` | On their clock too | untested | works | `send_mail` naming a time, to somebody whose own email is written on UTC-05:00, is held with the hour on their clock |
| `gene.renewal-notice` | Renews soon | untested | works | an email saying a plan renews in nine days becomes a notice with the service and the amount |
| `gene.unread-lists` | Newsletters you never open | untested | works | `unread_lists` finds a list none of whose three emails was opened, and leaves out one that is read |
| `gene.their-hours` | Not in their night | untested | works | `create_calendar_event` at a time in the night of a guest whose own email is written on UTC-05:00 is held, with their hour |
| `gene.holiday-guard` | Not booked on a guest's public holiday | untested | works | `create_calendar_event` with a guest at a .pl address on a day the stand-in's Polish holiday calendar has as a public holiday is held, with the holiday's name |
| `gene.not-answered` | Invitations you have not answered | untested | works | an invitation of somebody else's tomorrow that the owner has not answered, put on the stand-in's calendar, is found for the brief, and Yes answers it there |
| `gene.meeting-hours` | Where your meeting time went, by company | untested | works | `meeting_hours` counts two meetings with one company put on the stand-in's calendar last week, and leaves out one the owner declined |
| `gene.meeting-soon` | You meet them soon | untested | works | an opened email whose sender is a guest of a meeting in three days on the stand-in's calendar gets the line naming that meeting |
| `gene.got-it` | Got it on Telegram | untested | works | a message written to the bot on the stand-in phone is marked 👀 there by Rouh |
| `gene.gone-quiet` | Gone quiet | untested | works | a company met every week until seven weeks ago on the stand-in's calendar, with nothing booked, is named for the brief |
| `gene.reply-times` | Reply times with a company | untested | works | `reply_times` counts a company's email delivered to the stand-in's inbox and says it is still waiting on the owner |
| `gene.waiting-too` | Also waiting on you | untested | works | an opened email names the same sender's other email in the stand-in's inbox that is still waiting on the owner |
| `gene.their-language` | In their language | untested | works | `send_mail` in English to somebody whose own email is in Bulgarian is held, saying Bulgarian |
| `gene.my-word` | Your word, by mail | untested | works | a promise in the owner's sent mail, by a day now passed, with no email to that person since, is found for the brief |
| `gene.promised-to-you` | Promised to you by mail | untested | works | `promised_to_you` finds a promise by a day now passed, from somebody who has not written since |
| `gene.promise-watch` | If it does not come | untested | works | If it does not come makes one reminder at 09:00 the morning after the promised day, naming the sender |
| `gene.their-questions` | Their other questions | untested | works | `send_mail` to somebody whose other email asking the owner something is unanswered is held, with that question |
| `gene.answer-waiting` | Waiting on your answer, in the brief | untested | works | an email from a person asking the owner something, two days old and unanswered, is found for the brief |
| `gene.between-us` | Between you and them | untested | works | `between_us` for one person says what they asked, unanswered, and what they promised |
| `gene.answer-watch` | If I have not answered it, remind me | untested | works | the press makes one reminder at 09:00 the next working morning, naming the sender |
| `gene.not-twice` | Not put on twice | untested | works | the same event asked for twice, a quarter of an hour apart under another title, is booked once and the second answer says where it already is |
| `gene.away-after` | Away, after Rouh wrote | untested | works | an out-of-office reply in Rouh's inbox is told in a notice with until when and the colleague it names |
| `gene.no-company` | Contacts with no company | untested | works | `no_company` reads every contact and says how many have no company (or that none are connected) |
| `gene.know-them` | How you know them | untested | works | an email from somebody last written with eight months ago says when, the last subject and the first |
| `gene.sent-twice` | Not sent twice | untested | works | the same email sent twice to the same person goes once, and the second answer says it already went |
| `gene.new-number` | A new number in their signature | untested | works | a signature's mobile that a contact lacks is found, and a number the contact has is not |
| `gene.same-contact` | Contacts kept twice | untested | works | `same_contact` reads every contact and says who is there more than once (or that nobody is) |
| `gene.save-sender` | Save them as a contact | untested | works | a sender on no contact gets the card that would be saved: name, address, company from the domain and the signature's number |
| `gene.draft-twice` | Not drafted twice | untested | works | the same draft asked for twice is made once, and the second answer gives the draft already there |
| `gene.new-address` | A new address for a contact | untested | works | a contact's name at an address on none of their cards is matched to that one card; a known address, a one-word name and a name on two cards are not |
| `gene.contact-card` | Their card to pass on | untested | works | a contact's card file keeps the name, numbers and addresses and leaves the notes and birthday out |
| `gene.card-in-mail` | A contact card in an email | untested | works | a card file is read, and somebody new is offered as a new contact, somebody known as what their contact lacks |
| `core.commands-open-credentials` | A command run in the core beside Rouh (`docker compose exec core python manage.py ...`) opens what Rouh sealed | broken | works | with Google connected, Python in the core opens the sealed refresh token with the key from the keys volume (`ROUH_ENCRYPTION_KEY_FILE`), and Google is still connected after. It was broken: only the core's start put the key in Rouh's environment, so a command beside it made a key of its own in `/data`, could open no credential, and marked the owner's Google to be connected again |

## Checks a person makes

Only a person can check these, so the stack test does not; each is done by hand before a release, in the order given.

- **The microphone** (`voice.listen`): on the computer the stack runs on, open `http://127.0.0.1:8420`, press the microphone, say "What time is it?", and see the words appear and an answer spoken. A browser opens a microphone only for a real press, and only a real voice tests the turn marks.
- **A real phone** (`phone.real`): with the URL on (Anatomy, Your Rouh, Turn on URL), open the address on an iPhone in Safari, add it to the Home Screen, open it from there, and speak one sentence. The relay, the certificate and iOS's own microphone rules are only met there.
- **Your Rouh's URL** (`phone.relay`): on a Rouh whose first run chose Connected, open Anatomy, Your Rouh: its URL card shows the address on the relay's domain (a Rouh set up before the first run asked, such as the Creator Rouh, is connected to its owner's rouh.land account first, on the same page's rouh.land card, or Get its URL when it is in the account already; it keeps its name, and the address comes). Press Turn on URL, wait for it to say the address is open, and open that address from a phone on its mobile data, not the house's network: Rouh's sign-in page answers over HTTPS with a valid certificate. The relay's side and Let's Encrypt are only met there.

- **A Linux server** (`linux.server`): on a clean Ubuntu 24.04 or Debian 12 with Docker removed, `curl -fsSL https://rouh.land/install.sh | sh` over a terminal; `rouh setup` Connected (a real emailed code) and Independent; the link it prints opens General with the greeting; every `rouh` command; `systemctl start rouh-update`; a reboot; `rouh uninstall` Keep, then Bring back, identical (`rouh fingerprint` before and after); a tampered `stable.json` stops the install; the old setup code is refused. Proved on GitHub's runners, task 176, step 176-25.
- **Your own domain** (`edge.domain`): a name pointed at the server, `rouh domain NAME` (`--staging` for Let's Encrypt's staging service), `https://NAME/healthz` answers, `/setup` through it is 404, `rouh domain --off` closes 80 and 443.

## Totals

Counted by `tests/stack/smoke.py` from the rows above; it prints them on every run.
