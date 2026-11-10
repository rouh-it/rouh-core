# one

The program from step 07 of task 30 in the assistant workspace: one process that holds every run, keeps one list of everything that happens, decides what a run may do, and answers a terminal, a browser, Rouh's voice and the phone over one set of messages.

It runs beside Rouh on the server as its own service, `one`, under its own Linux user, and replaces nothing.
The name is only a label: it is the one program, and it keeps one list.

## Using it

**From another computer.** The `one` command talks to the server through ssh, as a paired device such as "My Mac". It is optional: the runs themselves are workers on the server, started just as well from Rouh by voice or from its page, and nobody needs a copy of any repository on their own computer for them.

```bash
one ls                              # what is running, and what ran recently
one claude                          # your own Claude Code, on the server; this terminal is its keyboard
one claude 6aa9                     # back to that session, carrying it on if it had ended
one start "what to do"              # a run of Claude Code in the workspace; its work lands on main
one start "what to do" --codex      # the same, but Codex does the work
one codex                           # your own Codex, on the server, as `one claude` is
one start "..." --space scratch     # in a folder of its own, saving nothing anywhere
one spaces                          # the repositories a run can work in
one space add owner/repo            # add one, by its GitHub name
one claude --space repo             # your own Claude Code in it; one start takes --space too
one shell                           # a shell of your own, in a checkout, driven by you
one show 6aa9                       # one run: what it did, its last entries, its screen now
one attach 6aa9                     # watch its terminal, typing nothing; Ctrl-] leaves
one take 6aa9                       # watch it and type into it; Ctrl-] hands it back and leaves
one say 6aa9 "text"                 # a message for it, or carry on a run that ended
one stop 6aa9
one questions                       # what the runs are asking
one answer 3bc7 no                  # answer one
one tree                            # the work tree, as text
one tail [6aa9]                     # the list, as it grows
one pair browser                    # a six-digit code, for <public address>/one/pair
one devices                         # paired devices
one revoke <device>                 # a device stops working, at once
```

A run is named by the start of its id.

**In a shell on the server.** The same commands, and they reach the program
here rather than over ssh.
The socket is the program's own, mode 0600, so any other account here runs
`one proxy` as root through sudo without being asked anything; an account with
no sudo is told to use it (`sudo one take 6aa9`).
Until 16 September being refused the socket was read as "this is not the
server", and the command went looking for the server by its ssh name, which
only the person's laptop can find.

A machine with no `one` command of its own runs it over ssh:
`ssh -t root@<the server's address> one take 6aa9`.
That address is the server's own, worked out from the route it takes to the
internet, or `ONE_SSH_TARGET` in the service file; the public address is usually
a proxy's (Cloudflare's) and ssh never reaches this machine through it.

**In a browser:** the installation's public address (`ONE_PUBLIC_URL`, such as https://rouh.example.com/one/) is the one page (D45, D47): Rouh's voice and orb, every run with its terminal live, and the workspace's tasks, once the browser is signed in to Rouh and paired with a code from `one pair browser`.
It starts and stops runs, answers questions, and types into a run's terminal: click into it and type (D46). The run's terminal takes the page's size, and its history scrolls (D50).
Beside a run's title is a button that copies the command for taking the same run over in a real terminal, `one take <run>`, with the command for a machine without `one` on its hover (D52).
While a real terminal has a run open, the run is that terminal's size and no page may change it: a page shows what it draws at that size, small enough to fit its box but never too small to read, and scrolls to the rest (D52).
Claude Code's fullscreen renderer draws on the terminal's full screen and uses the mouse: the page's wheel, clicks and drags go to it without taking the keyboard, so it scrolls back through the whole run, and what it copies reaches the clipboard of the page that selected it; every page watching a run is told when its size changes (D51).
On a touch screen a finger drawn up or down over the terminal is the wheel: it moves through the run's history a line for every row the finger travels, a flick carries on and slows, and a tap still opens the keyboard.
xterm.js leaves a touch alone once the run asks for the mouse, so until 24 September 2026 no swipe on a phone moved a run's terminal at all (fr_66d95f663c91).
A run of an agent has two tabs at the top of its page in Rouh, **Read** and **Terminal** (card 723).
Terminal is the terminal above, unchanged.
Read is the run's own transcript, the file Claude Code or Codex writes as it goes, set as an ordinary page the phone scrolls itself: what it was asked, what it answered with its Markdown drawn, and each tool call as one line that opens on a tap.
Nothing the terminal showed is left out of it: a `!` command or a slash command typed into the terminal is a line with what it printed, a Codex command's output is what the command printed rather than the JSON Codex wraps it in, and a turn that ended in an error, such as Codex's "Your workspace is out of credits", says so in red.
A long output or input is sent cut to its start and its end, and **Show all of it** under it asks for the whole (fr_631835dca7bb, 27 September 2026).
It follows the end while the reader is at the end, stays put once they scroll up, and offers **Latest** to go back.
A finger's swipe over a terminal goes to the server and comes back as a new picture a line later, so it lags and jumps however it is tuned; the Read tab is what that report asked for instead.
The terminal stays attached under Read, so switching back finds it live and as it was; the message box, a question and anything the run is waiting on on its own screen are on both tabs.
The tab chosen is remembered by each browser; with none yet, a touch screen opens on Read and a computer on Terminal.
The program reads the transcript as the run's user, through `asuser.py transcript`, which reads nothing but an agent's own transcript and with `--follow` hands on every line as it is written (`transcripts.py`); the page asks with `transcript` and is sent only what changed.
Rouh asks with `calls` for every tool call a run made, its sub-agents' with them (each in `<transcript>/subagents/agent-<id>.jsonl`, read the same way), never cut: how it judges what a finished job of an email case did before the case is redone (card 1307, 6 October 2026).
Drag a screenshot or a document onto a run's terminal, or paste a picture into it, and it is attached to what you are about to say to the run (D52): the file is written into `drops` inside the run's own `.one` folder, which git ignores, and its whole path is put in at the run's prompt as one paste with no Enter, so you can add words before sending it.
Claude Code turns a pasted path into an attachment, shown as `[Image #1]`, so nothing of the file itself goes down the terminal; a path typed key by key is not attached, which is why it goes in as a paste.
It takes png, jpg, gif and webp pictures, and pdf, txt, md, csv, json, docx and xlsx files, up to 20 MB each and ten at a time; a name that is already there gets a `-2` rather than overwriting.
A browser can also put a run out of the way, and bring it back: `archive` writes a flag on the run, and putting one away stops it as well.
A run that has not ended is stopped first, down the same path `stop` takes, so its terminal is closed; bringing it back starts nothing, and its checkout is untouched either way.
Every run the program sends out says whether its terminal session is open this instant, asked of the system rather than guessed from the run's state, because "it has finished its turn" and "its terminal has gone" both read as done.
The program's own page, every run full screen, is at /one/runs, and /one/ falls back to it when Rouh does not answer.
It shows a run's terminal and nothing else: the Read tab is on Rouh's page.
Every row of its run list carries the same archive button, whatever the run is doing, and a run put away is off the list until "Archived too" is ticked.

**By voice:** ask Rouh, naming the program: "start it in one", "what is running in one", "tell it to use the shorter opening", "let me drive", "carry on".
The voice may start a run and say where it works, say something to one, stop one, answer yes or no, read the list, and take or hand back a run a terminal is watching; the program refuses anything else.
Saying something to a run is the same `say` message a terminal sends and it lands the same way, at the run's own prompt, so Rouh's `reply_to_task`, `look_at_task`, `read_task_log` and `stop_task` all work on a run of this program exactly as they work on one of Rouh's own background jobs, and `one_say` is the same thing under the name a person uses when they name the program.
A `say` may carry `files`, each a name, a type and its bytes in base64: pictures dropped into a chat with Rouh, which keeps them where no run can read them, so `one_say` sends the bytes and the program writes them into the run's own `drops` folder, as it does a file dropped on the run's terminal, and ends the message with their paths (`rouh/runfiles.py`).
Before 19 September 2026 a message could only come from a terminal or a browser, so a run that stopped to ask something waited while the person, who was in the room, was told to go and find a terminal.
The voice still gained one sentence and not a keyboard: typing keys into a run's terminal, resizing it, pairing a device and putting a run away are all still somewhere else's.
Since stage 5, every job Rouh hands to the person's assistant is a run of the program as well; Rouh puts its result on its screen and says it, as it did for its own jobs (`rouh/one_jobs.py`).
Since D42 the assistant and Rouh are one: Rouh's jobs on the server (`delegate_task`) are the assistant's runs too, and its changes to itself (`improve_myself`) run in the space `rouh`; a job the person wants to approve step by step still goes to Rouh's own crew.

**On the phone:** a question nobody answers within 20 seconds, and a run that is stuck, arrive by Telegram.
Allow and Deny open a page that asks you to confirm with a button.

## Your own session

`one claude` is a Claude Code session of the person's own, running on the server in its own checkout of the workspace, typed to from any terminal connected through ssh: each turn's work lands on main as the turn ends. It is a worker on the server like every other run, not a program installed on the person's computer.

The workspace is a repository of its own, beside the code (`ONE_WORKSPACE`, `/srv/spaces/workspace` on the server), since 21 October 2026; from 21 September to then it was `workspace/` inside this repository.
A run's brief says which of the two its checkout is (`agents.workspace_layout`), and a run that changes Rouh's code as well makes a checkout of the code beside its own.
Before 21 September there was a separate copy of it at `/srv/assistant`, a repository of its own, with an Ask AI page server beside it (`assistant-askai`, on 127.0.0.1:1111), a timer that ran its `bin/sync` against GitHub every thirty seconds (`assistant-sync`), and a `deploy/laptop-window` script that made the laptop a window onto both.
All of that is retired: both units are stopped and disabled and are kept that way by `one/deploy/install.sh`, and the folder itself was archived and moved aside to `/srv/assistant.retired` on 22 September 2026.
Rouh serves the pages itself, at `/workspace/`, with the Ask AI drawer on them (`rouh/askai.py`).
The workspace's own `README.md` has the whole of the object model.

## Spaces: where a run works

The assistant is one place: every run Rouh hands out, and every run started without naming a space, works in its own checkout of this repository, which is where the person's workspace lives (`workspace/`), and saves to its main after every turn.
Any other repository is a space of its own, added once, with `one space add owner/name` in a terminal or "Add a repository" in the browser page's Start box, which clones it into `/srv/spaces/<name>`; and `one claude --space <name>` or `one start --space <name>` works in it, in a checkout of its own, so Claude never mixes projects up.
Rouh's own code is the space `rouh`.

| A repository... | A run's work |
|---|---|
| with a `develop` or `development` branch | starts from that branch and goes up on the run's own branch, for a pull request into it; nothing else is touched |
| without one, like the workspace | lands on its main after every turn |

In a code repository, what a run left uncommitted is not saved: its brief says to commit only once it has proved its own change.
In the workspace it is committed for the run, as before.
`scratch` is a folder of its own that saves nothing; it is kept a week.

**Landing on main is not this program's own git any more.**
It is `land.sh`, at the root of the repository, which is the only thing anywhere allowed to push to main (cards 488 and 489, 20 September 2026).
`one/asuser.py land` still commits what the workspace leaves behind, still refuses to let a run's own `.one` folder out, and still pushes a run's branch for a pull request where the repository has a development branch, because that branch never touches main and so can never collide with it.
Everything else is the ladder in `land.sh`: work already on main recognised by patch rather than by text and reported as landed rather than as a collision with itself; one landing at a time under a lock; `rerere`, so a conflict resolved once resolves itself; the work exactly as the run wrote it kept on a branch of its own before anything is resolved; and a real collision handed back to the run with both sides and a brief telling it to reconcile the intent rather than the text.
Twice failed, or both sides rewriting the same thing, is the one case that stops and asks the person, and `rouh/conflicts.py` is the record and the four choices they are offered.

### Nobody approves it

A run that has proved its change lands and is deployed, and there is no step anywhere in that where a person is asked.
The program lands the run's commits as its turn ends, through `land.sh`, and a run may push for itself when merging, pushing or deploying is the job it was given; `agents.PUSH_AND_DEPLOY` is the sentence every run that saves work to a branch is told, and it says so in as many words.
Work in the space `rouh` goes one step further: the moment it is on main, Rouh deploys it by itself (`rouh/one_jobs.py`), and that deploy is both services - this program first and then Rouh, onto the one commit, through `update-all.sh` at the root of the repository.
It used to deploy this program only when the change had touched `one/`, which is how Rouh reached `7596716` with this program four commits behind it on `6edd106`.
What was pushed and what was deployed are both on the card the person is shown and in what Rouh says out loud.

This is written down because it was not true, and the way it was untrue was quiet.
Every run was told "Do not push", the rules refused `git push` and a run's own settings refused it a third time, so on 19 September 2026 run `8921e843`, asked to merge a branch into main and deploy it, did the merge, checked it was clean, and then ended its turn saying it was waiting for approval.
There was no approval coming, because there is no approval step: the person's standing policy is that a change is done when it is committed, merged to main and deployed.
The deploy had the same shape of hole at the other end - it was a sentence asking the model to remember to call `deploy_myself`, and a step a model has to remember is a step that can be skipped.

### Done means committed

A run is only called **done** when its work is on the branch it saves to.

On 17 September 2026 run `8109f4b5` wrote the whole of a fix to Rouh, started the `rouh/` suite, ended its turn saying "Waiting on the `rouh/` suite" without having committed a file of it, and was closed three minutes later to make room.
It exited 0, and the list, the page, the `one` command and Rouh all said **Done**.
Nothing had looked at the checkout, and the program itself had chosen that run to close.

Three things now hold, and each closes one of those doors:

- A turn that ends with changes never committed is handed the words back through its Stop hook, once, telling it to wait for whatever it started and commit (`agents.finish_the_work`). Once only: a run that comes back saying its change is not right yet is telling the truth as often as not.
- When a run's process ends, its checkout is read before the run is called anything (`runs.what_is_left`). A run that would otherwise be done, but still holds changes never committed or commits that never reached its branch, is **unfinished**, with the reason on the run, on the page, in `one runs` and in what Rouh says out loud. The exit code stays on the record either way.
- A run that a **stopping signal** ended, after it had delivered its turn, is done rather than failed (`views.ended_state`). Being hung up, interrupted, quit, killed or terminated is something happening to a run, not something the run did; a fault such as SIGSEGV or SIGABRT is the process coming apart and stays a failure, and so does any signal that catches a run in the middle of working, which the program still resumes. On 22 September 2026 a run rebooted this machine on purpose to measure the boot. Seven runs went down with it and not one of them held a line of uncommitted work, but five were sent SIGTERM, exited 143 and were called done, while two were sent SIGHUP, exited 129 and were called **failed** - one of them a feature that had been on main and deployed for an hour. The rule had named a number where it meant a kind.
- The scheduler passes over a run that still holds work when it needs to close one for memory, and closes one with nothing left to lose. If every finished run is holding work, it closes none and tells the person.
- A run that says up front which files it expects to touch waits for a run already working on the same ones rather than both starting and one of them finding at the end that its work will not go onto main. Only a delay, never a refusal, and only between runs in the same space.

A folder can be a space too, added as it is (D43): by a project's name, `one space add --folder linkedin-video` or "Add a folder…" on the page, which makes `$ONE_FOLDERS_DIR/linkedin-video` on the server if it is not there yet, no longer the same path as on the person's Mac (D44); or by a folder's whole path.
Runs work in the folder itself, like a terminal: two at once can step on each other, and nothing is saved for them.
Their own files, the brief and the hooks' key, stay in `/srv/one-runs/<run>/` beside it, and the spaces folder holds only a link to it.

Every run works as the `assistant` user, which may use sudo with nobody asked, the person's decision of 15 September (D42): the assistant and Rouh are one assistant, and a run can do anything on this server.
Runs reach GitHub with the server's own key on the person's account, `~assistant/.ssh/github_one`, so a space can be any repository the person can reach.

## What a run may do

**Full access, the person's decision on 14 September:** a run may do anything its Linux user can (the `assistant` user, which may use sudo since D42), and nobody is asked. Runs start in Claude Code's bypass mode, and the program answers "allow" to every call and writes it down; a call the guarded rules below would have refused or asked about is marked in the list (`guarded`).

`ONE_ACCESS=guarded` in the service file brings the guarded rules back. Then every tool call comes to the program first, through its PreToolUse hook, and is allowed, refused, or asked about. The rules are one table in `rules.py`:

- **Never:** become another user, log in or copy to another machine, read or write files that hold keys, write outside the run's own checkout or a temporary folder.
- **Asked first:** anything that sends data out of the machine (an upload with curl or wget, nc, mail, an HTTP POST), and any tool from outside Claude Code.
- **Everything else** goes ahead.

On the server on 14 September a run's first tool call twice never reached the program through PreToolUse, and the cause was not found, so the rules do not rest on that one hook.
Claude Code's PermissionRequest hook, sent just before it would ask on its own screen, is decided the same way; each run's own settings refuse pushing, sudo, ssh and key files with no hook at all; and a call that finishes without the program having decided it is written down as `hook.missed`.

## Nothing a run starts outlives it

A run starts things to prove its work: a copy of Rouh on a free port, a stand-in for a model, a browser with eight Chromium processes behind it, a world in a temporary folder.
None of them ends by itself, and on 22 September 2026 that had cost this machine 14.82 GB of the 20 GB its service may use, with the cgroup pushed against that ceiling 4,972 times.
Two things were nearly all of it and neither had an owner: 2.25 GB in 28 processes left by a run that finished three days earlier, and 7.9 GB of working files in `/tmp`, which on this machine is a filesystem that lives in memory.

Three things keep it from coming back, in the order they act, and a fourth that is wanted and not yet possible.

**A run's temporary files are its own, and on disk.** `asuser.py` points `TMPDIR` at `<checkout>/.one/tmp`, so a world the harness stands up lands in the run's own folder - on a disk with 395 GB rather than in 16 GB of memory - and is thrown away with the checkout when the run is tidied.

**A run's processes are in a box it cannot escape.** `holder.py` puts the run's command in a cgroup of its own and empties it with `cgroup.kill` when the run ends.
A process can cut itself loose from its parent; it cannot leave a cgroup.

**Each box would have a ceiling, and does not yet.** `ONE_RUN_MEMORY_MAX` is written onto the box as `memory.high` and `memory.max`, but nothing accepts it.
The kernel only accounts a cgroup whose parent has the memory controller turned on for its children, and cgroup v2 refuses to turn one on for the children of a cgroup that holds processes itself, which `one.service` does.
Turning it on there anyway was tried and deployed on 22 September 2026, and it stopped systemd being able to start the service at all: `Failed to spawn executor: Device or resource busy`, because systemd starts a service by forking into that service's own cgroup.
The same rule that makes the layout necessary forbids the result.
Doing it properly needs a slice of its own beside the service, which the unit would have to make and hand over; `reaper.py` says so at length, under "Why there is no per-run memory ceiling".
Until then the service's own `MemoryMax` bounds the lot, and a run's box still ends the run completely, which is the part that keeps processes from leaking.

**And a reaper sweeps what got past all three**, every `ONE_REAP_EVERY` seconds: boxes whose run is over, processes that are orphaned and outside every box and older than `ONE_STRAY_AFTER`, and leftover worlds older than `ONE_SCRATCH_AFTER` that nothing holds open.
It sweeps nothing at all unless it is really the machine's own service, which is what keeps a program stood up in a test world from emptying the real one's boxes.

**In the containers there is no box, and the holder keeps one by hand** (`runprocs.py`, 29 October 2026).
The worker of every Rouh instance's stack is an unprivileged container: `/sys/fs/cgroup` is read-only in it, and a writable cgroup tree would take a privileged container, the host's cgroup namespace or a capability the stack check refuses, each of them a wall taken down.
So where `_make_box` finds nowhere to make a box, the holder finds the run's processes in `/proc` every two seconds: every descendant of its command, and every process whose environment carries the run's mark, `ONE_RUN=<id>`, which a process keeps after `setsid` or a double fork has handed it to init.
It adds up their own share of anonymous memory (`Pss_Anon` and `SwapPss`), and over `ONE_RUN_MEMORY_MAX` it says so on the run's screen, sends every one SIGTERM, and kills what is left three seconds later; the run ends **failed**, with the sentence why in its `run.ended` (`ended_why`, `one show`) and on the phone, and is not started again.
When the run ends for any reason, every process it still has goes too, detached ones included.
The gates read the worker's own cgroup, read-only but there (`ONE_CGROUP` is blank in the containers), so `mem_limit` on the worker (`ROUH_WORKER_MEMORY` in the settings file) is the memory they keep to, and the reaper sweeps only what its own ended runs left, by the same mark: a container's root cgroup is never taken for the service, because its pid 1 is the container's init and the worker's start script is an orphan by that test.

**Runs are garbage collected** (fr_61710d502d1c, 5 October 2026), by the scheduler's own loop.
Petar's words: "Every run that was successful should have a green status and be archived. The Claude code and all its sub-processes and browsers should be closed after 6 hours."

- A run that succeeded is closed and archived. Succeeded is a run that ended **done**, or a run of Claude Code at its prompt whose last turn ended well - its work on main and live, or nothing to save and nothing left behind - once `ONE_ARCHIVE_AFTER` (ten minutes) has passed with nobody at its terminal, no question, no conflict, no message waiting and no step handed to the live browser. Closing it ends it **done**, which is green on every screen. The person's own session is never put away open, and a run somebody brings back out of the archive is not put away again until it is started again. A message to an archived run carries it on and brings it back, as before. This applies to runs that succeeded before it shipped too, twenty a pass.
- A run that nothing has happened in for `ONE_RUN_LIFETIME` (six hours) is stopped. The six hours are counted from the run's last activity (`last_at`: a tool call opened or closed, its own or a sub-agent's, a turn ended or woken by a background command or monitor, a message to it), never from its start, so a run that is working is never stopped however long it works. Petar, 30 October 2026: "the 6h limit should be after the run has completed and has not been moving ... not 6h after the run has started". Stopping empties the run's own box, so every process it started, a Playwright MCP and every browser behind it included, goes with it. It ends **reaped**, "Cleaned up" on every screen: not green, not red. It is not archived, so it stays in view, and if its checkout still held work the person is told. A run saving its work or taken over by a person is stopped the moment that is over.

**Both halves of the sweep cross users, and neither needs new privilege.**
The program runs as `one` and everything a run makes belongs to the run's own user, so `kill` is refused and so is `unlink` in a sticky `/tmp`.
Until 22 September 2026 that made the sweep useless where it mattered: it reported "7 loose folders, 0 MB" and freed nothing, because it could not read inside a folder it did not own and would not have been allowed to delete it either.
Processes are stopped by moving them into a cgroup and emptying it, which is how a run ends anyway and which a signal's permissions do not apply to.
Files are deleted by `asuser.py sweep-scratch`, run as the run's own user through the same sudo rule that starts every run, and the rules about what a leftover is travel with the code rather than in the arguments: only a root and an age are passed.
What the sweep cannot read it now counts as unreadable rather than as nothing, because a silent zero on a screen reads as "there is nothing there".

What any of it is holding right now:

```bash
one processes          # every process, biggest first, with what has no owner marked
```

Rouh's orb shows the same leftover figure on its readout, so memory held by files nobody is using is visible before anybody feels it.

## Codex instead of Claude Code

A run is Claude Code unless Codex is asked for by name. Nothing else about a
run changes: the same spaces, the same checkouts, the same landing on main, the
same list, the same page.

```bash
one start "what to do" --codex      # a run of Codex instead of Claude Code
one codex                           # your own Codex session, as `one claude` is
one codex 6aa9                      # back to that session
```

In the browser's Start box there is an **Agent** picker: Claude Code or Codex.
By voice, name it - "start it in one with codex" - and Rouh passes it on; ask
for nothing and every job is Claude Code, as before.

Every screen says which agent a run is. The run's own heading always names it;
the row in the list carries a **Codex** label only when it is Codex, because a
label on every row would hide the one row that is different.

**Before the first Codex run, two things have to be there.**

1. **Codex itself.** `sudo npm install -g @openai/codex`, which puts it at
   `/usr/bin/codex`. `ONE_CODEX` says where it is if it is somewhere else. A
   run started on a machine without it ends at once and says so on its own
   screen; it never quietly becomes a Claude Code run.
2. **The ChatGPT subscription, in the run's user's own Codex folder.**
   In the containers it is one press, with no terminal: **Sign in Codex with
   ChatGPT**, in Rouh's Settings, Models, under Agents' sign-ins, or on
   `/setup/codex` (`one/codex_signin.py`, `rouh/web/codex_signin.py`). The worker
   runs `codex login --device-auth`, and the page shows its address and its
   one-time code large, with a QR code for a phone; the code goes to the phone
   too when the page is not in front of anybody. The page follows the sign-in
   by itself, says "Codex: signed in as ..." with the plan, and then runs one
   trivial `codex exec` to prove a real run gets past the sign-in. A code not
   approved in 15 minutes is given up and its process killed; Try again starts
   a new one. Sign out is `codex logout`. On the server it is still one command:

   ```bash
   sudo -u assistant codex login
   ```

   Either way the sign-in is `auth.json` in Codex's folder, `$CODEX_HOME` or
   `~/.codex` (`one/codexhome.py`, the one rule every place that starts Codex
   follows). In the containers that is `/home/rouh/.codex` on the `worker-home`
   volume, so it outlives a rebuilt or redeployed worker. The page keeps it mode
   600, and reads from it only the email and plan Codex itself shows; nothing of
   it is answered back, logged or sent.

   **Until it is there, no Codex run on the subscription starts.** Since 5
   November 2026 such a run is refused at once, and since 6 November it says
   one line, "Codex needs signing in again", with the page's address; the
   phone is told once, until Codex is signed in again, not once a run. A run
   whose sign-in stops working mid-way (`unauthorized`) is stopped the same
   way, with no question for each run. Before 5 November a run without the
   sign-in sat on Codex's sign-in screen for a minute and was stopped as
   `run.ungoverned` (run `8a52a3e8`, 17 September 2026; nights 17 to 21 of the
   refactoring run, 1 to 5 November).

   **No ChatGPT plan?** The same page has **Use the OpenAI key instead**, off
   until the person turns it on: then every run of Codex asked for with no
   billing is billed to the OpenAI API key, per token (`rouh-billing.json` in
   Codex's folder, read by `protocol._do_start`).

### Who pays for a run of Codex: the subscription, or the API key

A run of Codex is paid for by the ChatGPT subscription above unless the person
picks the **OpenAI API key** for that one run, billed per token. Nothing else
changes when they do, and no other run is touched. `one/billing.py` has the
whole of it; in short:

```bash
one start "what to do" --codex --api   # this run billed to the API key
```

In both Start boxes, the one program's and Rouh's, **Billed to** appears once
Codex is picked, on the subscription by default. By voice, Rouh passes
`billing: "api"` only when the person asks for the key by name. Every screen
says who pays: the row's **Codex · subscription** or, in orange, **Codex · API
key**; the run's heading; the line under it in Rouh's list; `one ls`.

**Where the key comes from.** Rouh's environment has `OPENAI_API_KEY`, and Rouh
hands it to the program over its own connection each time it connects
(`codex_key`, which only the voice may send). The program also takes one from
its own environment. It is held in memory only; a page is told only whether
there is one (`codex_api` in the hello), and the key is offered only then.

**How it reaches a run, and what cannot see it.** A run on the key gets a
Codex provider of its own on its command line (`env_key = "OPENAI_API_KEY"`),
which makes Codex send that key and never the ChatGPT login, and refuse to
start the turn rather than fall back to the subscription if the key is missing.
The key goes into a mode-600 file in the run's `.one/`, written from stdin;
`asuser.py agent` reads it, deletes it, and puts it in that one Codex
process's environment. It is never an argument, never in the list, never in a
log. The model's own commands see the variable empty. The one thing it cannot
be kept from is another process of the same Linux user, which can read
`/proc/<pid>/environ` just as it can read `auth.json`.

**When the subscription runs out.** Codex sends no hook when a turn fails; it
writes the failure into its session file, and the program reads that file
(`billing.Watcher`). A turn that ends in `usage_limit_exceeded` or
on the subscription the usage limit pauses the run with a question: **Continue
on the API key** or **Not now** (a lost sign-in, `unauthorized`, is the one line above instead). Nothing is switched and nothing is billed
until somebody presses yes, on any screen, or says yes to Rouh. The question
does not expire and outlives a restart of the program.

A yes asks Codex to leave at its prompt - the failed turn has already ended,
so nothing is cut off mid-request - and starts it again as `codex resume
<session>` on the key, in the same checkout. Watched with codex-cli 0.154.0:
the same session file, the earlier conversation sent with the next request,
and only the key on the wire. If the API refuses the carried-over
conversation (its reasoning was written under the subscription, and whether
the API accepts that could not be tried without real spend), the first turn
fails, and the run asks again: **Start fresh on the API key** - a new Codex
session in the same checkout, told where the old conversation is - or **Leave
it stopped**. It is never started over without that second yes.

### How a Codex run is governed, and what is not the same

The program's rules are one table in `rules.py` and they bind on both agents,
because Codex's hooks carry the same names, the same payloads and the same
answers as Claude Code's. A shell call arrives as `tool_name` `Bash` with
`tool_input` `{"command": ...}` from either. So the deny rules, the questions
put to the person, and the work tree on the orb are the same code for both.

Seven things are not the same. The four that matter most are in
`agents.CODEX_GAPS` as well as here, so that a person reading the code finds
them:

| What | Claude Code | Codex |
|---|---|---|
| **The hooks themselves** | posted straight to the program (`"type": "http"`) | Codex has no such hook: each one runs `one/codexhook.py`, which posts the same JSON to the same address and prints the answer back |
| **A hook that cannot reach the program** | the run still has the deny rules in its own settings, which Claude Code enforces with no hook involved | there are no such rules, so `codexhook.py` **refuses** the call rather than letting it through |
| **Hooks being on at all** | always on: they are in the settings file the program writes and hands it | **off, silently**, unless Codex is started with `--dangerously-bypass-hook-trust`. The program passes it, and then proves the hooks are live: a Codex run that has sent no SessionStart within `ONE_CODEX_HANDSHAKE` seconds (a minute) is stopped, and `run.ungoverned` says why |
| **Being told how the run works** | `--append-system-prompt` on its command line | Codex has neither a flag nor a setting for it, so the same text is the answer to its SessionStart hook, which Codex puts in front of the model as a developer message |
| **How hard the run thinks** | `--effort <level>` on its command line: the level its request said, which Rouh always says from the defaults in its Settings (`rouh/modeldefaults.py`), and `ONE_EFFORT` otherwise | Codex has no such flag: the level is the config setting `model_reasoning_effort`, so it goes on the command line as `-c model_reasoning_effort="xhigh"` (`ONE_CODEX_EFFORT`). It is the model's level, not Codex's, so one the model has not got is taken without a word and the run starts anyway |
| **`Notification`** | sent when Claude Code is waiting on its own screen; the program uses it to tell the person a run is stuck, and to end a turn whose `Stop` hook was lost | **Codex has no such hook.** Neither of those two happens for a Codex run |
| **Tools that run on OpenAI's side** | every tool goes through the hooks | a hosted tool never reaches a hook, so the program could not see or refuse it. Codex's web search is the one of those, so **a run is never started with `--search`**: the only tools a Codex run has are the ones the program can decide |

The first five are handled. **The last two are real gaps.** A Codex run that
stops to ask something on its own screen will not tell anybody, and a Codex run
whose `Stop` hook is lost will sit at its prompt instead of having its turn
ended a minute late; both are visible on the page, in the run's own terminal,
which is where a person looks anyway, but neither reaches the phone. And a
Codex run cannot search the web, where a Claude Code run can.

Two things are better on the Codex side, and are worth knowing:

* Codex refuses some commands itself, from its own `.rules`, whatever the
  program says. `rm -rf` is one: it is refused even with the sandbox off and
  every approval turned off. Claude Code has nothing of the kind.
* Codex's `PermissionRequest` hook fires whenever it is about to stop and ask a
  person, which for a run nobody is watching turns a wait into a decision the
  program makes. The program answers it with the same rules as `PreToolUse`.

**What to do next, and why it is not done here.** OpenAI's better answer to the
trust problem is *managed hooks*: hooks that arrive from an administrator's
`requirements.toml`, which are trusted by policy, cannot be switched off, and -
with `allow_managed_hooks_only = true` - make Codex ignore every other hook,
including any a repository being worked in carries. That is the right shape for
this program and would replace both the flag and the handshake. It is a change
to the machine rather than to a run, so it is a step of its own.

**In OpenAI's own words, about their hooks: "Treat tool hooks as a useful
guardrail, not a complete enforcement boundary."** That is why a Codex run
keeps Codex's own sandbox and its own command rules underneath the program's,
and why the handshake exists at all.

Every one of these was watched on this server on 17 September 2026 against
Codex CLI 0.154.0, driven by a stand-in model so nothing was spent. The
findings are written next to the code that acts on them, in `one/agents.py`,
and the survey they build on is step 30-19 of task 30 in the person's
workspace.

## Its version

The program has a version number of the ordinary kind: **MAJOR.MINOR.PATCH**, three numbers and two dots, like `1.4.0`.
It is written in one place, `one/__init__.py`, as `__version__`, and nowhere else.
`one/version.py` reads it from there, adds the commit the running process was started from, and hands both out: `/one/healthz` reports them, every connection's `hello` carries them, and a restart writes them into the list as `program.started`.

**When to move it.**
Move it in the same commit as the change it describes, so the number and the code can never disagree.

| Part | Move it when | Example |
|---|---|---|
| **PATCH** (`1.4.0` to `1.4.1`) | Something that was broken now works, and nothing else changed. | A run's terminal no longer loses its size when a second browser watches it. |
| **MINOR** (`1.4.1` to `1.5.0`) | There is something new that a person can do, and everything they could do before still works the same way. | A run can be put out of the runs list's way. |
| **MAJOR** (`1.5.0` to `2.0.0`) | Something a person or another program relied on has changed or gone: a message renamed, a field removed, a command that now means something else. | `one attach` stops typing into a run and only watches it. |

`1.0.0` is where the numbering starts rather than where the program did.
It had been serving runs, terminals, the phone, a paired browser and Rouh's voice for a while under `0.1.0`, a number nobody had moved since the first day and which therefore told nobody anything.

**Why the number is worth keeping honest.**
This program and Rouh are two services, deployed from two checkouts, restarted on two schedules.
On 16 September Rouh was deployed at `f4eb8a4`, the commit that put a button for archiving a run on its page, while this program's checkout at `/srv/one/app` was still at `5d1d755` and had never heard of archiving.
Nothing on any screen said so; the first anybody knew was an error in the browser when the button was pressed.
Rouh's top bar now carries the commit this program was built from, read from the program that is actually answering, next to the commit `origin/main` is at in this program's own checkout, `/srv/one/app`, and says so when the two differ.
Both halves come out of that one clone: reading Rouh's checkout for the second of them, which is what it used to do, compares one service's running code against another service's copy of the repository, and announced an update for this program every time Rouh was deployed.
The comparison is the commit rather than this number, because a version somebody forgot to move would hide exactly the failure the chip is for; this number is still what the program says about itself when asked.
It is in `rouh/one_version.py`, which is one of two chips - Rouh has one of its own beside it, `rouh/rouh_version.py`, and `rouh/versions.py` is the reading they share.
The chips are checked by driving Rouh's top bar in a real browser: `./e2e.sh serve two_chip_world` stands up a Rouh and a one program with a checkout each, which is what it takes to move one chip without touching the other.

**Catching up.**
When the chip says this program is behind, the panel it opens carries a button naming the commit that is waiting, and pressing it deploys this program on that machine.
That is `one/deploy/update.sh`: fetch `main` into `/srv/one/app`, fast-forward the checkout onto it, install this program's packages if `one/requirements.txt` was one of the things that changed, import the new code, restart `one.service`, and put the old commit back if the program does not answer `/one/healthz` within twenty seconds.
It is deliberately smaller than `one/deploy/install.sh` beside it, which owns the users, the sudo rules and the rest of the machine: a button in a browser moves the code, the packages and the service, and nothing else.
Run it by hand the same way, `sudo bash /srv/one/app/one/deploy/update.sh`.

That script is this program and nothing else, and the button under the chip is the only thing left that runs it alone: a person pressing it is asking for this program by name and is not asking Rouh to restart itself.
Every other deploy runs `update-all.sh` at the root of the repository, which resolves `origin/main` once, runs this script with that commit, and then runs Rouh's `deploy/rouh.sh` with the same one. It is the only deploy: this script refuses to run unless `update-all.sh` started it.
This program goes first because updating Rouh restarts the process that asked for the deploy, so nothing after it would be reached.
If this half fails, that is said in the update log and in the line Rouh reads when it comes back up, so a deploy that moved one of the two services is never reported as one that worked.
When the two are answering from different commits anyway, both panels in Rouh's top bar say so.

## How it is built

| File | What it is |
|---|---|
| `deploy/update.sh` | This program brought up to `main` and restarted, and put back if it does not answer. The first half of `../update-all.sh`, and not to be run on its own. |
| `listfile.py` | The list: plain text, one file per day, one line per entry, only ever added to. |
| `KINDS.md` | Every kind of entry, and its fields. |
| `views.py` | Runs, questions, devices and the work tree, worked out from the list. The tree is Rouh's own `tree.py`. |
| `holder.py` | One small process per run that holds its terminal, so runs outlive the program. Standard library only. |
| `runprocs.py` | A run's processes where no cgroup can be had (the containers): found by parentage and the `ONE_RUN` mark, their memory added up, and every one ended. Standard library only, for the holder. |
| `terminals.py` | The program's side of every holder: its screen (pyte), its watchers, its keyboard. |
| `rules.py` | What each place may ask for, and what a run may do. |
| `runs.py` | Starting, the hooks, stopping, taking over, handing back, landing, restarting, adopting. |
| `agents.py` | Runs of Claude Code or Codex: the brief, each agent's hook settings, hooks into entries, and what Codex has not got. |
| `codexhook.py` | What each of a Codex run's hooks runs: it posts the hook to the program and prints the answer, and refuses a call it cannot get an answer for. |
| `reaper.py` | What owns whatever a run leaves behind: run boxes whose run is over, orphaned processes outside every box, and leftover worlds in a filesystem that lives in memory. It also lays the service out (`main/` and `runs/`) so a run's box can carry a memory ceiling, and answers `one processes`. |
| `scheduler.py` | What may start and when: thirty runs of Claude Code at once (`ONE_MAX_RUNS`), the processor (`ONE_CPU_BUDGET`, nine tenths of the service's `CPUQuota`) and memory. A run that has to wait carries the reason in its own words, and every screen shows it. Runs stay open until closed; when memory runs short, the one left unwatched the longest is closed (D49). It also queues a run whose declared files overlap one already working, which is the cheap half of the conflict work on card 488: a run may say up front what it expects to touch (`expects`), a folder counts as everything in it, and a run that declared nothing is neither held back nor holds anything back. |
| `questions.py` | Asking a person, and the runs waiting for the answers. |
| `documents.py` | Each run's checkout, and putting its work on main. |
| `drops.py` | A file dropped on a run's terminal: what is taken, what it is called, and where it lands. |
| `transcripts.py` | A run's own transcript as a conversation, for the Read tab: read as the run's user, followed as it grows, one follower per run however many read it. |
| `asuser.py` | The one command the program may run as the run's user, under sudo. Standard library only. |
| `devices.py` | Pairing, and device tokens (kept in the list only as their SHA-256). |
| `protocol.py` | One set of messages, for every place that talks to the program. |
| `web.py` | The socket on the server, and the web address behind nginx: a Django application (with Channels for the browser's socket) built inside the program's own process since 23 September 2026. `urls.py` is its list of addresses. |
| `phone.py` | Telegram, sending only. |
| `cli.py` | The `one` command. Standard library only, so it runs with any Python. |
| `version.py` | The version above, and the commit the running process was started from. |
| `program.py` | Puts the parts together; the watchdog; `python -m one.program`. |
| `static/` | The page. xterm.js is stored here, so it loads nothing from outside. |
| `deploy/` | The service, the sudo rule, the nginx addition, the install script. |
| `tests/` | A stand-in for each agent (`fake_claude.py`, `fake_codex.py`), a throwaway local world (`dev_server.py`) and the reaper (`strays.py`). No tests: they went on 20 September 2026. |
| `../tests/e2e/serve.py` | The worlds above, stood up and held, for a browser driven live over Playwright MCP. |
| `../tests/e2e/conftest.py` | The harness the page is driven against: `one_app`, `rouh_with_one`, `two_chip_world` and `one_deploy_world`, each in a world of its own. |

## Tests

**Every feature proves itself, and nothing else is run**, this program's as much as Rouh's: nothing is committed until whoever built it has driven the page over Playwright MCP and seen the thing work. There are no committed tests, of any kind. The rule, the harness and a worked example are in [../AGENTS.md](../AGENTS.md). `./e2e.sh serve one` stands this program up in the throwaway world `one/tests/dev_server.py` builds, with a stand-in for Claude Code, so driving it costs nothing.

```bash
./e2e.sh serve one                              # this program, up and held, for a browser to drive
./e2e.sh path/to/your_check.py                  # a check of your own, run and then thrown away
```

To look at it by hand instead:

```bash
.venv-e2e/bin/python -m one.tests.dev_server /tmp/one-dev 18031    # a throwaway world at http://127.0.0.1:18031/one/
ONE_SOCKET=/tmp/one-dev/s.sock .venv-e2e/bin/python -m one.cli pair browser   # a code, to let the browser in
ONE_SOCKET=/tmp/one-dev/s.sock .venv-e2e/bin/python -m one.cli ls             # and its terminal
```

A venv of this program's own, if you want one without Rouh's requirements in it:

```bash
uv venv -q --python 3.12 .venv-one
uv pip install -q --python .venv-one/bin/python -r one/requirements.txt
```

## On the server

| Where | What |
|---|---|
| `/srv/one/app` | The program's own checkout of this repository, owned by root. A deploy fast-forwards it; nothing else does. |
| `/srv/one/venv` | Its Python packages. |
| `/var/lib/one/list/` | The list. |
| `/var/lib/one/runs/<run>/` | Each run's terminal log, how it ended, its hook key. |
| `/var/lib/one/views.json` | The views' saved position. Delete it and they are worked out again from the list. |
| `/srv/one-runs/` | Each run's checkout, in any space, owned by the `assistant` user. |
| `/srv/spaces/` | Every repository added as a space, one clone each, owned by the `assistant` user. |
| `/var/log/one/one.log` | The program's log. |
| `/etc/one/telegram.json` | The phone's Telegram bot, readable by the program only. |
| `/etc/sudoers.d/one` | The one command the program may run as `assistant`. |
| `/etc/sudoers.d/assistant` | Every run may use sudo, with nobody asked (D42). |
| `/run/one/one.sock` | The socket. |

New code: push to `main`, then `ssh <the server> 'bash /srv/one/app/one/deploy/install.sh --update'`.
It checks the code imports before restarting, prints the command that goes back, and never stops a run: only the program restarts, and it reconnects to them.

`ONE_CLAUDE_DEBUG=1` (a systemd drop-in, `one.service.d/debug.conf`) makes each run write Claude Code's own debug log into its `.one` folder; it is copied to `/var/lib/one/runs/<run>/claude-debug.log` before the checkout is removed.

### Worker subscriptions in Anatomy Connections

`/anatomy/connections` reuses the setup sign-in protocol for Claude Code and Codex.
Only the owner gate used by setup can read or change these instance subscriptions.
`/api/subscriptions/claude` and `/api/subscriptions/codex` return identity metadata and current capacity, never credentials.
POST actions start or cancel the vendor's own sign-in, finish Claude's returned-code flow, or sign out after confirmation.

Codex uses `login --device-auth` and `logout` in the worker's shared Codex home.
Whatever account is signed in there is the one every run uses, whatever its plan or workspace: there is no workspace to choose and nothing a run waits for.
A new sign-in replaces the earlier login in every home a run reads it from (`codexhome.spread`, which in the containers is the one `/home/rouh/.codex`), and a sign-out removes it from all of them.
The card's "Personal" or "Team" is only a label read from the plan OpenAI names (`subscriptions.workspace`): a known shared-workspace plan is Team and any other plan is Personal.
The only refusal at the start of a subscription run is no ChatGPT login at all, which says to sign in under Anatomy > Connections.
From 9 to 10 November 2026 a workspace chosen on the card was a gate: a run was refused unless the signed-in workspace matched it, and a plan the code did not know, such as `prolite` (ChatGPT Pro Lite), was labelled "Unknown" and so never matched, whatever was signed in.
The gate is gone; `subscriptions.release` takes away what it left behind, the chosen workspace file and any `forced_chatgpt_workspace_id` in Codex's `config.toml`, at every sign-in and at the start of every subscription run.
Capacity comes from Codex's `account/rateLimits/read`, with no model request; Claude's usage endpoint stays inside the worker.
Unknown windows and credit balances stay unknown, and capacity cached for at most 45 seconds is invalidated when credentials change.

New jobs read the shared credentials at launch.
An existing idle job with changed credentials resumes its saved conversation in a new CLI process before its next message, including a queued follow-up at the end of a turn.
This does not interrupt a working turn or require a manual restart of the one program.
Browser proof uses isolated homes and stand-ins; it must never sign the installation's live accounts out.
