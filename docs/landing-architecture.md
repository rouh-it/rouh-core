# Landing: why finished work is reported as unfinished, and one path for all of it

Written on 3 November 2026 by run ee48b2f7, on Petar's words: "when I request a feature it gets built but I get telegram messages that it can't be merged, or committed or something ... look at the whole picture from above and think of what the best architectural solution would be".
This is a diagnosis and a design.
Nothing here changes how anything runs yet; the migration at the end is the work to do next, step by step.

## In one paragraph

Every "unfinished" message on the phone since the move into the containers (31 October to 3 November 2026, the whole of the record this machine holds) was a false alarm: six runs, six messages, and every one of their commits is on main.
They come from one design fault: **the code that decides whether a run's work reached main does not ask the code that put it there.**
`land.sh` lands the work, often as a new commit with a new id, and forgets which of the run's commits it landed; afterwards a second piece of code (`one/asuser.py` `status`) guesses, by comparing patches, and any landing that had to change the patch at all - a file already on main, a generated file taken as main had it, a clash resolved - is guessed as "never reached main".
The real clashes (five in the same window) all had one shape: two writers of one task's `AGENTS.md`, usually a job and Rouh itself writing straight into the server's copy.
All five were settled by the job that wrote the work, with nobody asked, but Rouh's own merge pass, the rung meant to settle them, cannot run in the containers at all.
The design below makes landing one thing with one owner and one record, so that "did it reach main?" is read from that record and never guessed, and so that only that owner may tell Petar anything about it.

## 1. The case: run 5979a8ce, "Create Gene Nursery list"

The run's own list (`~/one-data/list/2026-11-03.jsonl`), in time order, UTC:

| Time | What happened |
|---|---|
| 08:08:50 | Started in `/home/rouh/runs/5979a8ce` from workspace main `aedb7ac`. |
| ~08:10 | The run made task 166 with `rouh objecttree create`. Rouh wrote the task's folder and `.object.json` into **the server's copy** of the workspace too, and its saver (`rouh/saving.py`) committed that to main at 08:10:27 as `a022f02` "workspace: Rouh saves 2 changes it made to the tree" (`_tasks.md` and `rouh/assistant/166.gene-nursery/.object.json`). |
| 08:14:51 | The run committed its work, `2bcd6f3`: eight files, the task's `.object.json` among them, byte for byte the same as the one already on main. |
| 08:15:04 | Its turn ended (`agent.stopped`). |
| 08:15:37 | The program landed it through `land.sh`: `work.landed`, sha `c95a5b7`, 1 commit. The rebase dropped the hunk for the `.object.json` main already had, so `c95a5b7` holds **seven** files where `2bcd6f3` held eight. |
| 08:25:39 | The run sat idle and was archived. |
| 08:25:40 | `run.ended`: `"ok": false, "saved": true, "unsaved": 1`. The run is called **unfinished** and its checkout is kept. |
| 08:25:41 | `phone.sent reason=unfinished`: "Create Gene Nursery list ended unfinished: it left 1 commit that never reached main" (`one/program.py` `tell`, from `one/runs.py` `_end`). |
| after | Rouh's own reporter (`rouh/one_jobs.py` `_show_left_behind`, then `Lander._phone`) put an "Unfinished" card up, told the conversation, and sent the second message, "⚠️ Needs you: Create Gene Nursery list" (`rouh/job_phone.py` `stuck_text`). |

**Verdict: a false alarm. All of 5979a8ce's work is on the workspace's main.**
`git diff 2bcd6f3 origin/main -- <its eight files>` is empty: every file it wrote is on main exactly as it wrote it, seven of them by `c95a5b7` and the eighth by Rouh's own save `a022f02` five minutes earlier.
The step's notes and page, the list `gene-nursery.md`, the task's `AGENTS.md` and the line added to `94.nightly-rouh-feature-run/ideas.md` are all there.
Task 166-01 being done is not a second path at work: status is the database's, and the files are on main too.
Nothing was missing, so nothing was landed for it by this run.

**Why it was called unfinished.**
`one/asuser.py` `status` counts the run's commits that are "not on main" with `git rev-list --right-only --cherry-pick origin/main...HEAD`, which matches commits by patch id.
The patch of `c95a5b7` is not the patch of `2bcd6f3` (one file fewer), so `2bcd6f3` counts as unsaved.
The landing knew perfectly well that it had landed `2bcd6f3` as `c95a5b7`; it did not write that down (`work.landed` carries `sha`, `files`, `commits` and nothing naming the run's own head), so the check at the end could only guess.

**Why two messages.**
Two pieces of code each decide on their own to tell the phone about one ending: the one program (`Program.tell`, reason `unfinished`) and Rouh (`OneLander._phone` with the result kind `unfinished`, which `job_phone` always sends as "Needs you").
Neither knows the other sent.

## 2. Every bad ending in the record, grouped by its real cause

The one program's list on this machine starts on 31 October 2026, the day the Creator Rouh moved into the containers; what the old server held before that is not on this host.
For 13 October to 30 October the evidence is the repositories' history and the incidents written into the code's own comments, and it is listed separately below.

### 31 October to 3 November 2026, from the run list (every case there is)

| Cause | Count | Runs | Real? |
|---|---|---|---|
| A. Landed, then called "unfinished: 1 commit never reached main" because the run's checkout had a stale `origin/main` and compared commit ids. Fixed by `b33c1c16` (31 Oct 20:56): fetch first, compare by patch. Each one's patch id matches its landed commit exactly. | 5 runs, 6 phone messages from the program (+ Rouh's "Needs you" for each) | 9cac1ec6 (twice: unfinished, then reaped), 2d6c494e, 1d79af90, f2f3d5ad, f18345b8 | False alarm |
| B. Landed, then called unfinished because the landing changed the patch (a file already on main), so comparing by patch fails too. The case above. Not covered by `b33c1c16`. | 1 run, 2 phone messages | 5979a8ce | False alarm |
| C. A real clash, two writers of the same task `AGENTS.md`: two jobs on one task at once, or a job and Rouh's own write into the server's copy (the decisions gate's "Cleared by Rouh", `rouh/decision_sources.py` `_clear_marks`, committed by the saver as `2a665b1`). Sent back to the worker (rung four) and settled by it, nobody asked. | 5 | 2d6c494e (task 161), 0b4e1d37, 3e6d297e, ab01dfe5, 199ddb6a (all task 165) | Real, settled by Rouh |
| C1. Of those, Rouh's own merge pass (rung six) could not run: "Rouh could not merge it itself: Claude Code is not on this machine for this user" (`rouh/merge_pass.py` `find_claude`). The worker container has Claude Code at `~/.local/bin/claude`, but a run's workspace work is landed in the core (`rouh/workspace_follow.py` `take_landings`), which has none: the merge pass depends on where the landing happens to run. | 1 | 0b4e1d37 | Real gap |
| D. Reaped after six hours idle with nothing left to land, called failed ("ok": false) although all its work was on main. No phone message, but the state is wrong. | 2 | 5cf20ca4, 0b4e1d37 | Wrong state, not told |
| E. Work truly not on main. | **0** | - | - |

So in the window the program sent 7 phone messages about these endings, and Rouh's own reporter can send a "⚠️ Needs you" beside each one (Petar received both for 5979a8ce; Rouh's side of the record for the others is in its database, not on this host). **None of them was about work that was really missing.**
Every clash was technical and was settled without Petar, which is his rule; but each still produced a "could not be saved to main" line in the run list and, while the worker settled it, a "Needs you" path was armed for it.

### 13 to 30 October 2026, from the repositories' history

- **The workspace copy that stuck** (`ba4cd5a0`, 27 October): run e9df64d0 committed step 139-06 straight onto the server's copy's own main. Once main moved on, the copy's fast-forward failed every minute for eleven hours and Petar heard "has not taken in main for N minutes" every half hour. Cause: a second place that commits (the server's copy) outside the landing. Same day, `abb9e21` "Task 139: step 139-07 ... rescued from the server's copy": the same class, found by hand.
- **Eight questions on 18 October** (card 1684, in `rouh/conflicts.py`): Petar was asked about eight clashes that day and none needed him; three of the "clashes" of 6 to 18 October were a rebase with no committer name, not a clash at all. That is what moved rung six to Rouh's merge pass and rung seven to Rouh's own pick.
- **Six scratch records reached Petar as real decisions** on 18 October (`scratch_repo` in `rouh/conflicts.py`): a test's landing wrote into the real landing directory.
- **The move into the containers** (29 to 31 October): Rouh's own code now lands through the protected core, which pushes from elsewhere and replays commits under new ids; that is cause A above. The landing directory `/srv/rouh-land`, where conflict records and the questions live, does not exist in the containers, and neither does Claude Code for the user that runs the merge pass (cause C1).

The pattern across both periods is the same three things: something other than the landing commits; something other than the landing decides whether the landing worked; and more than one thing tells Petar.

## 3. Every path by which work reaches main, today

Today `land.sh` runs in **three different places**, as three different users, and two pieces of code tell Petar about how it went.
The table lists every path; file and line references are to this commit.

| Path | Who commits | Who lands (replays and pushes) | Who decides it failed | Who tells Petar |
|---|---|---|---|---|
| **One program run** (Rouh's `one_start`, and most start tools: `rouh/starting.py:427`) | The run itself. Leftovers are committed at landing (`one/asuser.py:514`), except in the `rouh` space (`--leave-uncommitted`). | At each turn end: `Runs._land` (`one/runs.py:1244`) → `asuser land` → `land.sh`. **In the containers** `land.sh` hands off to `bin/rouh-land` (`land.sh:214`), which for the workspace drops a bundle in `/run/one/landings` for the **core** to land (`rouh/workspace_follow.py:160` `take_landings`, a second copy of `land.sh` in another container), and for Rouh's code goes to the protected core (`guard/rouh_guard/changes.py:230`). `Runs._end` re-lands only shell runs (`one/runs.py:1956`). | `Runs._end` → `what_is_left` → `asuser status` (patch comparison, `one/asuser.py:228`) → `ended_state` (`one/views.py:120`). Clashes: the `land.sh` ladder. | **Twice:** the program's own `Program.tell` (`one/program.py:226`; reasons `unfinished`, `reaped`, `failed`, `not-landed`), and Rouh's `OneLander.report` (`rouh/one_jobs.py:198`), which shows a card, speaks, and sends "⚠️ Needs you" (`rouh/job_phone.py:143`). |
| **assistant_job** (the crew, the fallback when the one program is not there) | The job, and `CrewManager.land` for leftovers (`rouh/crew.py`). | `crew.run_land_script` → `land.sh`. | `Lander._land` (`rouh/assistant_job.py:564`): sent back, redo, `needs_person`. | `Lander` card, speech, `_phone` ("Needs you" always). |
| **delegate_task** (`rouh/starting.py:241`) | In yolo mode it is a one program run in the `assistant` space, so the first row applies. In any other mode it is a crew job with no repository. | As the first row, or nothing. | As the first row. | As the first row. |
| **improve_myself** and the **nightly runs** (`rouh/nightly_feature.py:634`, `rouh/nightly_refactor.py:329`, preset `improve_myself`) | The run, in a clone of Rouh's code. It is told to run `./land.sh` itself (`pushed_itself`). | The protected core (`bin/rouh-land` `land_code` → `guard`), which replays under new commit ids and keeps an undo point. Then the program lands again, and finds the work is already there. | As the first row. The nightly `still_filling` silences Rouh's done notice, but not its unfinished notice and not the program's own message. | As the first row, plus the morning decision. |
| **Ask AI** page edits (`rouh/askai.py:804`) | Nobody directly: the edit is written into the server's copy, and the saver below commits it. | The saver below. | The saver. If the page will not merge, the change is **only logged** (`rouh/saving.py`). | Nobody. |
| **Rouh's own writes to the tree**: objecttree's folders and `.object.json`, `_tasks.md` from the database, quests, the offline outbox, `task_docs`, `open_items`, `sent_by_you`, and the decisions gate's "Cleared by Rouh" marks (`rouh/decision_sources.py:564`) | Rouh writes into **the server's live copy**. The saver (`rouh/saving.py:314`) copies the changes into its own clone and commits them as "workspace: Rouh saves ...", every 300 s or when poked. In four days that made 58 task-list commits and 6 tree commits on the workspace's main. | `Saver._land` → `land.sh --no-deploy` from the core: a **third** place `land.sh` runs, with no run id and no merge pass. | The saver. | Nobody: log lines only. |
| **Status, summary and meta of tasks** (`rouh-task`) | Nobody: they live in the database. Only the `_tasks.md` made out of them reaches git, through the saver. | - | - | - |
| **Syncs** | Nobody. The one program's follow (`one/runs.py:1411`, every 60 s) fast-forwards the copy. Commits found on the copy's own main are put aside on `kept/...` and landed with `land.sh --merge` (`ba4cd5a0`). The core's follow (`rouh/workspace_follow.py`, every 30 s) takes the run landings, levels with GitHub (a direct `push`, `:129`), and resets the core's live copy onto main. **There is no 10-minute task sync.** The only 600 s loop (`rouh/runtime.py:678`) does no git work. | The follow jobs, through `land.sh`. | The follow job. | The program: "copy-stuck", once per reason since `ba4cd5a0`. |

### History that shaped it

- **20 September 2026**: three jobs finished good work and pushed none of it, because the rebase failed. This produced the ladder in `land.sh` and the records in `rouh/conflicts.py`.
- **22 September 2026, stale conflict records**: each record is kept twice, once beside the run and once in the shared landing directory that everything reads. `cf-a6aa24af-2` said `answered` in the first and `waiting` in the second, because the second write was refused (`fs.protected_regular`) and the error was swallowed. The orb went on drawing NEEDS YOU for three finished jobs. The fix opens an existing file without `O_CREAT` first (`rouh/conflicts.py` `write_bytes`), so an answer reaches the shared copy. The same day the orb drew five NEEDS YOU for three jobs, because a job and its conflict were each drawn (`rouh/runtime.py` `_with_conflicts`). It is the same pattern as today's: **two copies of one fact, and something reading the wrong one.**
- **18 October 2026, merge_pass**: Petar was asked eight times in one day, and none of them needed him. Rung six became Rouh's own merge pass (`rouh/merge_pass.py`): Claude Code `-p`, on the model the Models page names for "Merging a clash", read from the landing directory. Rung seven became Rouh's own pick. Only `his_words` reaches Petar (`ConflictFeed`, `rouh/runtime.py:2055`; `ConflictSource`, `rouh/decision_sources.py:1364`). Only the program's own landing passes `--claude` to it. The saver, the core's `take_landings` and `land_kept` run where there is no Claude Code, so in the containers the merge pass is out of reach for most landings. When it fails, `land.sh` falls back to sending the work back to the job (`land.sh:2069`).
- **23 October 2026, "Followed through"** (`e03140d2`, `rouh/follow_through.py`): a finished job's note carries what Rouh said it would do once the job was done. It reads the landing's outcome but does not change it. So a false "unfinished" also stops a promised follow-up from being offered as done.
- **27 October 2026** (`ba4cd5a0`): a run committed onto the server's copy's own main, and the copy stuck for eleven hours.
- **31 October 2026** (`b33c1c16`): a stale `origin/main` in the run's checkout made five landed runs "unfinished". The fix was to compare by patch, and 5979a8ce shows that this is not enough.

## 4. The target design: one landing, one owner, one record

### The principle

**Only the landing may say whether work landed, and it says so in a record it writes as it lands. Everything else reads that record.**

Concretely, four rules, each replacing a guess with a fact.

1. **One owner: the landing service.**
   `land.sh` stays the one thing that pushes, and the one program's landing (`Runs._land` through `asuser land`) stays the one caller for runs.
   Today it runs in three places (the program for runs, the core's `take_landings` for a run's workspace bundle, the core's saver for Rouh's own writes), as three users, with the merge pass reachable in one of them.
   The target is **one landing service, in the worker container where Claude Code is**, with one queue: a run's branch, a protected-core proposal's fit, and every change Rouh makes to the tree arrive there and are landed one at a time under one lock.
   Rouh's own writers (objecttree, the task list, the decisions gate, Ask AI's page edits, quests, the offline outbox) stop writing into the live copy and waiting for a saver to notice: each **hands its change to the queue as a change set** (paths and bytes, or a patch against the main it read), which the landing applies on a fresh checkout of main.
   The core only receives the landed main (it already resets its copy onto main every 30 s).
   The server's checkout becomes read-only for git purposes: it is moved onto main by deploys and nothing else, so it can never again hold commits of its own (the 27 October incident) or be a second writer of a file a job is editing (cause C).

2. **One record: the landing ledger.**
   Each landing writes, under its lock, one row: the run (or the saver, or the follow job), the run's own head it took (`from_head`), the commit it became on main (`landed_sha`), the files, and how each run commit fared (`as` patch, `already`, `dropped` with the file main had, `merged` by the merge pass).
   It lives where both services can read it - the one program's list already carries `work.landed`, which only has to gain `from_head` and per-commit fate; Rouh reads it over the socket as it does now.
   **"What is left" becomes exact:** unsaved = the run's commits after its last `from_head` (`git rev-list <from_head>..HEAD`), plus a dirty tree.
   No fetch, no patch ids, no guessing; it is right whatever the landing did to the patch, and it is right for the protected core, which pushes from somewhere else.
   Patch comparison stays only as the landing's own rung one, where it belongs.

3. **Commits after the report are swept in, not reported.**
   A run that ends (archived, idled out, reaped, stopped) and holds commits after its last `from_head`, or a dirty tree, is landed once more by the same landing, as `Runs._end` already does for shell runs and not for agent runs.
   Dirty files are committed by the program first with a plain message ("what run X left uncommitted when it ended"), on its own branch for a run that was stopped half way, so nothing half-done goes to main unasked.
   Only if that final landing truly fails is the run unfinished.

4. **One voice: the landing decides, Rouh tells, once.**
   The one program stops sending phone notices about landing and endings (`Program.tell` for `unfinished`, `not-landed`, `reaped`); it writes the facts, and Rouh's reporter (`OneLander`) is the only one that turns them into words, a card, a phone line or a decision, keyed once per run and outcome as `job_phone` already is.
   A one program with no Rouh paired to it keeps its own `tell` as the fallback, so it is never silent; the two are never both on.
   What reaches Petar is decided by one rule, written once in `rouh/one_jobs.py`: **only an outcome the ledger marks `needs_person` reaches Telegram or Decisions.**
   A clash is never `needs_person`: rungs four to seven are Rouh's (Petar's rule that merge clashes are technical choices), and if every rung fails the work is kept on its `land/pre` branch and retried by a fresh run (rung five) on the next pass, and Petar hears about it only if the retries are exhausted and it is a day old, once, with what was tried.
   `needs_person` is left for the one case `land.sh` already names: the side that would be dropped holds his own words.

### What it fixes, case by case

| Cause | Fixed by |
|---|---|
| A, B (false "never reached main") | Rule 2: unsaved is read from `from_head`, which the landing wrote. |
| C (two writers of `AGENTS.md`) | Rule 1: Rouh's own writes go through the landing as change sets on fresh main, so they are ordinary landings that rebase like any job's, and a run's rebase meets them as main, the case rerere and the worker settle every time. |
| C1 (merge pass missing in the containers) | Rule 1: the one landing runs in the worker container, which has Claude Code, so rung six is always reachable. |
| D (reaped and called failed with nothing left) | Rule 2: a reap with nothing after `from_head` is `done`, not `failed`. |
| Two messages for one ending | Rule 4. |
| The 27 October stuck copy | Rule 1: the copy has no commits of its own to stick on. |

### What it does not change

The ladder in `land.sh`, its lock, its checks (types, mail replay, LLM guard, stack test, owners), `land/pre` branches, the deploy, `asuser.status` for a checkout never landed at all, and every screen's words.
Runs keep their own checkouts and their own branches.

## 5. Alternatives weighed

### Alternative 1: patch the check again (compare trees, not patches)

Make `asuser.status` call a commit landed when main holds every file it touched with the same bytes or a later version.
**Cost:** a day. **Migrates:** nothing.
**Breaks / leaves:** it fixes cause B and nothing else, and it is the third guess at the same question in four days (ids, then patches, then trees). "A later version" cannot be told from "somebody else overwrote my change" without the landing's own knowledge, so it trades false alarms for silent losses on files two writers share, which are exactly the files that clash. Two senders, the second writer and the missing merge pass stay. It will need replacing; that is the refactor Petar asked to avoid.

### Alternative 2: runs commit straight onto one shared checkout of main, no branches

Every run works in one checkout under a lock, so nothing ever needs replaying.
**Cost:** large; every run serialised. **Migrates:** the runs folder, worktrees, `land/pre`, the redo rung.
**Breaks:** parallel runs (several at once is ordinary here), a run's own proof in its own world, and recovery of a half-done run. It removes clashes by removing concurrency, which is not a trade Rouh can make.

### Alternative 3: move task text that clashes out of git (status, "Where this stands" into the database)

Status and summary already live in the database; extend that to the task's `AGENTS.md` head.
**Cost:** medium. **Migrates:** every task's notes and every agent instruction that writes them.
**Breaks:** the rule that a task's `AGENTS.md` holds everything about the task, which every agent obeys and Petar reads; and it only removes one file's clashes, not the false alarms or the two senders.
Worth keeping as a later refinement for the generated parts only (the decisions gate's marks), not as the fix.

### Why the recommended design

It answers the question at its source instead of guessing it again, it is mostly a re-routing of code that exists (the saver already lands through `land.sh`; the follow job already does for kept commits; `OneLander` already holds the once-per-result claim), and it adds one field to a record that already exists.
Every later change to how landing works - a new rung, a new place that writes - plugs into the one queue and the one record, so it should not need another refactor.

## 6. Migration, in order

Each step is safe alone and proves itself before the next.

1. **Record what was landed.** `land.sh` puts `from_head` (the run's `HEAD` it replayed) and per-commit fate in its last JSON line; `asuser land` and `Runs._land` carry them onto `work.landed`. No behaviour changes. Prove with a throwaway script on a scratch remote: the 5979a8ce shape (one file already on main) and a plain landing.
2. **Read what is left from the record.** `Runs.what_is_left` counts `rev-list <last from_head>..HEAD` when the run has landed, falling back to today's patch check only for a run with no `from_head`. This alone ends causes A, B and D. Prove on the kept checkouts 5979a8ce and 9cac1ec6 (both must say unsaved 0) and on a scratch run with a real unlanded commit (must say 1).
3. **Sweep at the end.** `Runs._end` lands an agent run's commits after `from_head` once before judging it, as it does for shell runs.
4. **One voice.** The program stops `tell`ing about `unfinished`, `not-landed` and `reaped`; `OneLander` is the only sender, and only `needs_person` reaches the phone and Decisions. Prove in the browser on the `talking` world: a clash sent back shows on the run's screen and nothing reaches the stand-in Telegram.
5. **Land where the merge pass is.** Move the workspace landing from the core's `take_landings` into the one program in the worker container, where Claude Code is. The core keeps only receiving main. Make a missing Claude Code a check at deploy time, so it never surfaces as a surprise at runtime. Add a row for it to `CONTAINERS.md`.
6. **One writer.** Rouh's own writers to the tree (`objecttree`, `tasklist`, the decisions gate's marks, Ask AI, quests, offline) hand change sets to the program's landing queue instead of writing into the live copy for `rouh/saving.py` to find. The saver then shrinks to a shim and is retired. The live copy becomes read-only to git outside deploys, so `land_kept` and the copy-stuck notice can go.
7. **Fix `_clear_marks`** (found on the way): it rewrites "Waiting on Petar" anywhere in the notes, including inside quotes in labelled history - `2a665b1` turned `the four "Waiting on Petar" items` into `the four "Cleared by Rouh ..." items`. It should change only the paragraph that starts `**Waiting on Petar`.
8. Add the landing rows to `CONTAINERS.md` and checks to `tests/stack/` as each step lands, since every one of them runs in the containers.

## 7. How we will know it worked

- **The metric:** the share of `run.ended` with `ok: false` whose run has a `work.landed` and nothing after its `from_head`. Today it is 6 of 6 "unfinished" endings. After step 2 it must be 0, read from the run list each week.
- **Phone messages about landing per real loss:** today 7 from the program alone (and Rouh's "Needs you" beside them) for 0 losses in four days. Target: exactly one message per run whose work is truly not on main after the sweep, and none otherwise.
- **Clashes asked of Petar:** target 0, except `his_words`.
- **A check of its own for steps 1 to 3**, on a scratch remote: a commit with a file main already has; a commit made after the turn's landing and before the run ends; a real clash settled by the worker; a genuinely lost commit. Only the last may come out unfinished.
