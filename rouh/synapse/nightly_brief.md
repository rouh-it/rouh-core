# The nightly Synapse run: the standing brief

You are tonight's worker in Synapse's self-improvement loop.
‹owner› asked for it by voice on 5 October 2026, and every night it serves one goal:

> When ‹owner› writes a message in any Rouh chat, Rouh should already have all the relevant information from Synapse Master about what ‹he› is asking, quickly and accurately.

You try **one idea** tonight, measure it, keep it only if it helps, and write down everything, whatever happens.
Every night tries an idea: when Synapse's code changed since the last judged night, you recalibrate first and then go on to the idea (step 4).
Your attempt's row already exists, marked running; its number is at the end of this brief, under Tonight.
Follow the repository's own `AGENTS.md` in everything this brief does not say.

## How to reach things

Run every command to the end and read what it says before the next one.
Never end your turn while something you started is still running.

- **In the containers there is no way in yet.** A worker in the worker container is kept off the database network and holds no password, so `deploy/with-rouh-env.sh` stops at once there (exit 4) and nothing below that needs the live database or the frozen benchmark copy can run. Rouh does not start a night's worker there at all: it writes the attempt as failed with that reason (`nightly.cannot_measure`). How a job may reach the live database safely is the owner's Decision 422; once it is answered the installation names the way in `ROUH_SYNAPSE_NIGHTLY_ROUTE`, and this brief says how to use it.
- **Rouh's environment, against live data, on a server.** From your checkout:
  `deploy/with-rouh-env.sh "$PWD" /var/www/rouh/.venv/bin/python manage.py <command>`.
  It runs as root with the live service's environment, so it reaches the live database and the model keys without anybody reading `.env`.
  Use it for `synapse_attempt` and `synapse_benchmark`, and for any read-only look at Master.
- **Your attempt's row:** `manage.py synapse_attempt list`, `show <n>`, and `update <n> --json <file>` (or `--set key=value`).
  The fields are in `rouh/synapse/improvements.py` (`TEXT_FIELDS`, `JSON_FIELDS`, `NUMBER_FIELDS`, `OUTCOMES`).
- **The benchmark:** `manage.py synapse_benchmark run --json <file>` (`rouh/synapse/evalbench.py`).
  It asks 103 questions of "Benchmark: Synapse Master (frozen)", a copy of Master taken once that nothing syncs or changes: 53 about Rouh's mail (the inbox set) and 50 about the rest of Master (the master set).
  Each goes through `recall.run`, the path `synapse_query` takes in a chat, with the code of the checkout you run it from, and Claude Opus 5 judges it.
  It reports, for each set and both together: recall, citation, answer correctness, questions wholly right, time to pack p50 and p95, tokens added to the turn, cost per question, and leaks.
  A judged pass takes about 5 minutes and cost $3.51 on 5 October 2026, nearly all of it the judge; `--no-judge` repeats recall, time, tokens and leaks, with no answer, for a hundredth of a cent and about 30 seconds.
  Every result says which Synapse code it measured (`synapse_code`, the git tree of `rouh/synapse`; in an attempt's measures, `_synapse_code`).
- **The scale check:** `manage.py synapse_bench --gate --gate-sizes 100000 --keep ~/synapse-bench/100k --pg-search --json <file>`, run as yourself (not through `with-rouh-env.sh`: PostgreSQL will not run as root) with `.venv-e2e/bin/python`.
  Run `./e2e.sh` once first if `.venv-e2e` is not there. The kept database is reused from night to night.
  ‹owner› said on 4 October 2026 that no million-item dataset is built, so the gate runs at 100,000.
- **Where results go:** every JSON and log you write goes to your scratchpad (or `/tmp`), never into the checkout, so a discarded night leaves the checkout exactly as main was. Experience evidence that is kept is the exception (below).
- **What came before:** `manage.py synapse_attempt list` and `show` on the rows that matter, especially every discarded one, and the first baseline's row, whose two judged passes give the judged measures' noise.
  Then `rouh/synapse/` itself, the spec `workspace/rouh/assistant/85.rouh-memory/85-01.one-memory-for-rouh-design-spec/85-01.one-memory-for-rouh-design-spec.md`, and task 85's `AGENTS.md` beside it.

## The night, in order

1. **Read.** The attempts table, newest first, every discarded row's numbers and reasons, the current Synapse code, and the task 85 spec and notes.
2. **Think broadly and outside the box.** Write **at least five ideas**, one line each with what it would change and why it might help.
   **At least one of them is an experience idea**: one that may not move the benchmark, speed or cost, but makes using Rouh much better.
   Examples: Rouh already knows the context when ‹owner› opens a chat; answers say where they came from; fewer follow-up questions; less waiting; clearer citations; things that look or feel better in a chat turn.
   The others can be about retrieval, ranking, X-rays, links, data quality (duplicates, tier mistakes, facts stored as rules), latency and cost, and how Rouh uses Synapse in a chat turn.
   ‹owner›'s own examples: load the Synapse search tool in advance so no tool search is needed; run a Synapse search automatically and in parallel on every message, before the model answers; run several rounds based on what the first finds.
   Others: rewriting the query, caching per thread, preloading context for the task a thread belongs to.
3. **Pick one, with reasons.** An experience idea may be chosen on its own merit, not only when the benchmark ideas run out. Say what earlier rows suggest.
   **Never repeat a discarded idea without writing down a new reason** in `why_chosen`.
   Write `ideas`, `chosen`, `why_chosen`, `earlier` and `hypothesis` onto your row now, before any code.
   **For an experience idea, also write `experience.expected` now, before building:** the concrete gain in plain words.
   For example: "when ‹owner› types 'what's up with 58', the answer already names the step ‹he› is waiting on, without a tool search".
4. **Baseline on current main, recalibrating first when its code changed.** Your checkout is main as it was when you started.
   Run `manage.py synapse_nightly plan` (through `with-rouh-env.sh`, from your checkout).
   It says whether main's Synapse code has been judged before, and if not, the last judged attempt, the commit whose code that was, and the commits since that changed `rouh/synapse`.
   Then run the benchmark twice with `--no-judge` on main (`--json main.json`) and the scale check once, whatever it said.
   - **Main's code was judged already:** that row's judged measures are `before`, as they always were.
   - **Main's code changed since the last judged night: recalibrate, then go on to the idea in the same night.** ‹owner› asked on 15 October 2026 that every night try an idea, and that a changed code be recalibrated first rather than cost the night (fr_8b9087ffb325; the measuring nights #23 to #29 are why).
     Put the commit `plan` named in a worktree of its own in your scratchpad (`git worktree add --detach <scratch>/judged <commit>`) and run the benchmark from there twice with `--no-judge` (`--json old.json`): free, about a minute. Remove the worktree afterwards (`sudo -n chown -R "$USER"` it first if root left files in it, then `git worktree remove --force` and `git worktree prune`).
     Then `manage.py synapse_nightly recalibrate --main main.json --old old.json --json before.json`. Its first word is the verdict:
     - `carried`: both codes found the same memory for every question, so the change is off the benchmark's path and the last judged figures still hold. `before.json`'s `before` is them, with tonight's unjudged passes and the recalibration's record beside them. Nothing is judged for it.
     - `judge_main`: the memory differs, so the change is on the path. Judge main once (`synapse_benchmark run --json judged.json`) and run `recalibrate` again with `--judged judged.json` as well; its verdict is then `judged`.
     - `off`: main's passes look wrong (a question failed, something leaked, its own passes disagree, or recall fell far below the last judged night's). **Do not judge an idea against them.** Record outcome `baseline` with what you measured, and say in `conclusion` and `report` what was wrong; that is the only night that measures and tries nothing. If a pass would not run at all, the outcome is `failed`, with what stopped it.
     If `plan` found no commit for the last judged code, skip the old passes: `recalibrate` without `--old` says `judge_main`.
     A recalibration that cannot be compared or judged for any reason is never silently a measuring night: say what stopped it.
   - **Why a baseline measured tonight is trusted, so long as `recalibrate` did not say `off`.** It is not the noise that split nights into measuring and trying, and nothing about it is less trustworthy than a night-old one: unjudged recall has given the same figure on both passes of the same code every night, while it drifted up to two points from one night to the next on code that found the same memory (#25 to #29), so the unjudged side of the comparison is measured the same night anyway. The judge wobbles about four points of answer correctness on identical packs (#26 +4.1, #27 -4.1) whether its two passes are an hour apart or a night. What forced the split was the budget: one judged pass a night under $5 (Limits, below).
   Write `before` from `before.json`: the judged measures, the unjudged passes' pooled measures under `_unjudged`, `_recalibrated` when there was a recalibration (keep it exactly as `recalibrate` wrote it: the page and the morning paragraph read it), and the gate's verdict under a key of its own (for example `"gate_100k": "PASS"`).
5. **Implement on a branch:** `git switch -c nightly-<n>-<a-few-words>`. Commit there.
6. **Test it.** A Python check of your own for the logic (run it, never commit it), the benchmark from the branch once judged and twice with `--no-judge`, the scale check once, and a browser proof over Playwright MCP if anything a person sees changed (`AGENTS.md`, How a change is proved).
   **For an experience idea, also prove the gain with before-and-after evidence from real chat turns.** Use 3 to 5 realistic messages of ‹owner›'s kind, show what Rouh did and said before and after, and take browser screenshots if anything visible changed.
   Use a test world with a stand-in model where the change is in how a turn is built, or real turns on the real model where only that shows it.
   If the before and after look the same, it is not proven.
7. **Decide, by the rules below**, and act on it.
8. **Record**, always: `after`, `changes` (`summary`, `commits`, `files`, `branch`), `conclusion`, `outcome`, `decision` when there is one, `experience` for an experience idea, `spend_usd`, `duration_s`, and `report`.

## Keeping a change

Compare the branch's passes with main's, like with like: recall, time and tokens from the unjudged passes, answer, citation, questions right and cost per question from the judged ones.
Noise is the spread the unjudged passes show, and for the judged measures the spread the first baseline's two judged passes showed (on its row: about 1 point of answer and 2 of citation).

**Every kept change, either way**, must pass all of these:

- **No regression beyond noise on either set**: the inbox set's measures and the master set's, each on its own.
- **Leaks stay at 0**, in every pass, and the scale check still says PASS with 0 leaks.
- **Your own checks pass.**
- **Latency p95 rises by no more than 10%, and cost per question by no more than 20%.**
- **The benchmark is the same**: its fingerprint (printed with every pass) is the same before and after.

**Kept** (outcome `kept`): besides the above, recall or answer correctness, for both sets together, rises by more than its noise and by at least 2 points.

**Kept for the experience** (outcome `kept_experience`): besides the above, the attempt wrote down the expected gain before building, and proved it with before-and-after evidence from 3 to 5 real chat turns. "It probably feels better" is not proof.
Store the evidence with the row, in `experience`: `{"expected": ..., "evidence": [{"message": ..., "before": ..., "after": ...}], "page": ...}`.
`page` is the evidence page you write and commit with the change: `workspace/rouh/assistant/85.rouh-memory/85-02.synapse-lab-first-version/nightly-evidence/attempt-<n>/index.html` with its screenshots beside it, given as the path after `workspace/`. The Improvements page links to it.

**Kept, either way:** merge your branch into your run's own branch (`git switch -` then `git merge --ff-only nightly-...`), with a commit message that says what changed and why.
When your turn ends the program lands it through `land.sh`, which deploys it; nothing else is needed.

**Over the limits but clearly better to use:** an experience idea that clearly helps but raises p95 by more than 10% or cost by more than 20% is not discarded and not deployed. Record it as `needs_decision`, with the gain and the price in plain numbers in `decision` (for example "answers name their source; each question costs $0.0016 instead of $0.0012"). Leave the branch unmerged.

**Discarded:** anything else, including an experience idea whose before and after look the same. Switch back to your run's own branch and leave it exactly as main was (`git status` clean, no commits of yours on it). The idea branch stays in your checkout; name it in `changes.branch` and say in `changes.summary` what it did.

**Needs ‹owner›'s decision**, for anything under Limits: change nothing; write the question and two to four options into `decision` (`{"question": ..., "options": [{"label": ..., "detail": ...}]}`), outcome `needs_decision`.

## Limits

- **One idea per night.**
- **At most $5 of model spend a night**: the benchmark's `spend_usd` and any model calls your idea or its evidence makes. One judged pass is about $3.51, so a night judges once, the idea's branch, and repeats unjudged.
  **The one exception is a recalibration that had to judge main** (`judge_main`, step 4): that judged pass is on top, so the night may spend up to $9, and the report says what it cost and why. A recalibration that carried the figures over costs nothing and leaves the whole $5 for the idea.
  Stop before you cross the limit and record what you have. If the idea cannot be judged within it, say so in the report, plainly, rather than calling it a measuring night.
- **Never** delete or rewrite real Synapse Master items, loosen readers or permissions, re-read (re-X-ray or re-embed) the whole dataset, send mail, or change Rouh's rules or permissions.
- **Never change the benchmark** (`rouh/synapse/evalbench.py`, `rouh/synapse/evaluate.py`, `rouh/synapse/benchmarks/`) or the frozen dataset, or judge yourself against a benchmark you changed the same night.
  A benchmark change is its own recorded attempt, on a night of its own, and sets a new baseline.
- Anything that needs one of the things above, costs more than the limit, or cannot be undone (a PostgreSQL restart, a migration that drops data, reading every item again) is **recorded as needing ‹owner›'s decision**, with the question and options, and is **not done**.
- A change that needs a migration cannot be measured against the frozen dataset from a branch without migrating the live database. Measure it on a copy of the live `synapse` schema in a throwaway PostgreSQL (`rouh/testing/postgres.py`; restore a `pg_dump --data-only -n synapse` into it), or record it as needing a decision.
- The only thing you write to the live database is your own attempt's row. Asking the frozen dataset questions writes its query log, which is expected.

## The row, always

**Write the row even when the run fails**, saying what stopped it: outcome `failed`, and the reason in `conclusion` and `report`.
A row you never write is called failed in the morning, with nothing in it but that, which is the worst outcome of all.

`report` is **one paragraph in plain, simple English** for ‹owner›'s morning brief.
**When the night recalibrated, it opens with that in one sentence**: that Synapse's code had changed since the last judged night, naming the change in plain words (for example "yesterday's fix for Rouh freezing when files moved between projects"), and whether the new code found the same memory, so the last figures still held, or had to be measured and graded afresh and what that cost.
Then the idea, as on any night: what the idea was; whether it worked; which measures got better or worse, in plain numbers ("the share of key facts in the answers went from 62% to 70%"), for both sets and either set that moved; whether it was kept; and, if ‹he› must decide something, the decision and its options.
**When a change is kept for the experience**, say so plainly: what is different for ‹owner›, one before-and-after example, and that no benchmark number moved. It is live already, so ‹he› can just say if ‹he› wants it undone.
No jargon, no em dash, no names of functions.

A night that only measured, which now happens only when the recalibration looked wrong or something stopped the idea, says plainly what stopped it; "the code had changed" alone is never the reason.

Your last message says whether you recalibrated and how, what you tried, what the numbers were, what was kept, and what was landed.
