# rouh-guard: a Rouh's protected core

Task 98, step 98-23, built on 24 October 2026.
The small set of safety and repair parts that leave a Rouh's own code, so the Rouh can use them and not edit them, and Rouh's makers can still fix them.
It ships as its own image, `ghcr.io/rouh-it/rouh-guard`, named by digest in the same signed release on rouh.land as the base.

Why: a Rouh's code is its own (`/code`, a git repository each Rouh changes itself and no update touches).
Until this, everything that kept a Rouh safe and repairable lived there too, so a Rouh could rewrite its own safety parts, and no fix of ours could reach them.
Petar's rule since this day: **a gene may change Rouh in any way except the protected core** (GENES.md, "What a gene may change").

## What is here

| Path | What it is |
|---|---|
| `rouh_guard/keyproxy.py` | The key proxy: adds the model keys to the workers' calls on the way out, and the owner's GitHub token while a timed grant is open; reaches the servers a timed grant lists (`deploy/grants/README.md`). It runs on this image itself, never from `/code`. |
| `bin/rouh-check`, `bin/check-base.sh` | The check a new base must pass with a Rouh's own code, in a throwaway container. |
| `frozen/` | The frozen copy of the security checks, which call the Rouh only through its check face (`rouh/checkface.py`), and their runner. |
| `rouh_guard/server.py`, `rouh_guard/daemon.py`, `bin/rouh-guard` | The guard service and its socket (the changes contract). |
| `rouh_guard/changes.py` | The change step: a proposed commit checked, then made the code that runs, with an undo point kept where the Rouh cannot reach it. |
| `rouh_guard/doctor.py` | The doctor: puts `/code` back to the last undo point when Rouh stops answering right after a change. |
| `rouh_guard/geneverify.py` | The signature checks on a shared gene (moved from `rouh/genelab.py`). |
| `rouh_guard/stackpolicy.py`, `policy/` | The stack check: what a Rouh's own stack file may and may not ask for. `policy/stack-policy.json` is the one allow-list: each release signs this commit's copy of it, and both checks read the release's. A Linux machine runs this file out of the release's guard image (`deploy/container/linux_stack.py`). Rouh for Mac's `StackPolicy.swift` (in `rouh-it/rouh-mac`) is its twin; both are held to `policy/fixtures/`, and Rouh for Mac's build stops while its copy of these files is not the one the live release names (`check_sha256`). No file of the machine may reach a stack: `include`, `extends` and `label_file` are refused in the stack file's text, an `env_file` must be the release's settings file or one of the stack's own folder, and Linux resolves the Rouh's own stack sealed; `policy/fixtures/host_files.py` proves it on real Docker on every push to main. |
| `bin/rouh-core-entrypoint`, `bin/rouh-workers-entrypoint`, `bin/rouh-guard-run` | How the core and the worker start: the core asks the guard first (`verify`), and both run their program under `rouh-guard-run`, which starts it again when the guard puts other code in place. |
| `rouh_guard/deploywait.py`, `bin/rouh-deploy-wait` | No deploy cuts a chat answer: before a restart, wait until Rouh says no answer is in progress (`rouh/answers_now.py` keeps the count), ten minutes at most; `rouh-guard-run` runs it in the containers and `update-all.sh` on a server (below). |
| `bin/rouh-propose` | For a run in the worker: hands the commits of its clone of the code to the guard through Rouh, and waits for the answer. |
| `bin/rouh-code-install` | A Rouh's first start: the newest tested Rouh into `/code`, free, with no account (the commit from rouh.land's signed record or the signed release, the code from the public GitHub repository), and the libraries it needs into `/extra`. |
| `bin/rouh-keys`, `bin/rouh-extra-pip`, `bin/rouh-guard-install` | Keys into the keys volume; a library into `/extra`; these files into a volume. |
| `bin/rouh-backup` | The stack's backup part, on PostgreSQL's own image: a copy of the database every night into the backups volume, kept a week, and a copy put back (`linux_stack.py restore`). The only part besides those above that mounts these files, read-only (`policy/stack-policy.json`). |

## How a Rouh reaches it

The Rouh's code never imports it. It talks to it through four numbered contracts (`rouh_guard/__init__.py`, `CONTRACTS`):

| Contract | Way | Carries |
|---|---|---|
| keys 1 | HTTP, `http://keyproxy:8080/anthropic/...`, `/openai/...`, `/health` | model calls, with the key added on the way out |
| changes 1 | the socket `/run/guard/guard.sock`, one line of JSON a request and one a reply | `status`, `points`, `propose {commit, why}`, `undo {point}`, `verify {who}`, `gene {fn, ...}` |
| check 1 | the last line a check prints, `ROUH-CHECK {json}` | passed, failed with reasons, known gaps |
| checkface 1 | `rouh/checkface.py` in the Rouh's code | the few calls the frozen security checks make |

Within one number the core only adds; an old number is kept for at least a year.
A gene that needs a newer core says `"needs_guard": ">=1.1"` in its manifest; the change step makes it wait until that core arrives.

## Where it sits in the stack

`deploy/stack/compose.yml` (the Rouh's own stack file; `/code/deploy/stack/` in a running Rouh):

- `guard-init` copies `/opt/rouh-guard` of this image into the `guard-bin` volume on every start; the guard, the core, the worker and the code install mount it read-only.
- `guard` runs `rouh-guard serve` on the base image, with `/code` read-write, its own `guard-state` volume (undo points and their history), `guard-run` (the socket, mounted only by the core) and `guard-signal` (what the start scripts read, read-only to the core and the worker).
- `keyproxy` runs this image. It mounts the keys, read-only, and nothing of the Rouh's.
- `checkdb` is a throwaway PostgreSQL in memory, on a network shared only with the guard, for checking a proposed change.

No container has the Docker socket, so nothing inside the machine can change which containers run: only Rouh for Mac, or `linux_stack.py` on a Linux machine, applies a stack file, after its check.

## Building it

```bash
docker buildx build -f guard/Dockerfile -t rouh-guard .
guard/bin/check-base.sh --base rouh-base:1.0.2 --guard rouh-guard --code-dir .
```

`.github/workflows/base.yml` builds it with each base level, for Intel and Arm, and the signed release names it by digest.

## A change, from start to finish

1. A run in the worker clones `/code`, changes it, commits, and runs `rouh-propose "what it is"`. Or the Rouh commits in `/code` itself.
2. Rouh (`rouh/codechanges.py`) reads the commits into `/code` and asks the guard to `propose` them. A main moved without the guard is proposed by the core's start (`verify`).
3. The guard checks the commit in a folder of its own, as a user that can write nothing of its own (`checks.py`): the frozen security checks, then the Rouh's own, against `checkdb`. About 30 seconds.
4. Passed: an undo point is kept in `/guard/history.git`, `/code`'s main moves to it, and the core (and the worker, when the one program changed) start again on it. Failed: nothing runs, and a commit already on main is kept on a branch `refused/<time>`.
5. The person sees each in Meta, Changes, with Put back on every earlier point, and a notice.
6. If Rouh then stops answering for fifteen minutes (within half an hour of the change), the doctor puts the code back to the point before and says so once (`ROUH_GUARD_DOCTOR_PATIENCE`, 900 seconds; five until 11 November 2026, when Petar found it too low because some operations take longer).
   The fifteen minutes count from when the core really started on the change, as its start asks `verify`, never from a core still busy with the code before: a start still migrating for other code has not run this one.
   The start's migrations run under `rouh-guard-run --step`, so a migration that takes too long is stopped when the doctor puts other code back, and the container starts again on that code (11 November 2026: undo point 174's migration ran for fourteen minutes, nothing stopped it, and the doctor blamed 173 too, which had never started).

Proven on 24 October 2026 in this server's Docker, with every step driven in a real browser (task 98, step 98-23).

## The Creator Rouh's push (task 161)

Every Rouh instance stops at "restart": a checked change is live as an undo point and goes nowhere
else. The Creator Rouh, Petar's own, where Rouh's code is made, sets one more setting in its
settings file, `ROUH_GUARD_UPSTREAM=git@github.com:rouh-it/rouh-core.git`, and makes the key once:

    docker compose exec guard python -I /opt/rouh-guard/bin/rouh-guard upstream-key

which prints only the public half; it goes on rouh-core as a deploy key with write access
(GitHub's API, `repos/rouh-it/rouh-core/keys`), so it can write to that one repository and no
other. The private half stays in the guard's own volume, which nothing else mounts.

From then on (`rouh_guard/upstream.py`) the guard pushes a change to rouh-core's main only after
its checks passed, its undo point was saved and Rouh answered on it for
`ROUH_GUARD_UPSTREAM_SETTLE` seconds without the doctor putting it back; never forced. It fetches
rouh-core into /code as `refs/upstream/...` every `ROUH_GUARD_UPSTREAM_EVERY` seconds, so a run's
landing fits its work onto rouh-core's main with land.sh's own steps (`bin/rouh-land`), and a main
that moved on elsewhere runs here only once it passed here. The 00:40 base level is pushed as
`base-patch/<level>` by `push_branch`, only when it changes `deploy/container/base/` alone and its
checks pass. It reaches GitHub through the key proxy (`rouh-connect`, ssh.github.com:443, GitHub's
host key pinned). Turning it off: remove the setting and delete the deploy key.

## No deploy cuts a chat answer (3 November 2026)

Petar, 3 November 2026: "don't group a couple, but lets wait if a chat answer is in progress. make sure it doesn't cut a chat answer. so restart only if a chat answer is not in progress."
Every restart a deploy makes waits first (`rouh_guard/deploywait.py`): in the containers `rouh-guard-run`, when the guard moves a restart number - a change landed by a run or a nightly job, `deploy_myself`'s change, an undo, the doctor - and on a server `update-all.sh`, which `land.sh` and `deploy_myself` run.
Deploys are not grouped: each waits only for the answers in progress when it comes.

- Rouh counts every answer from the moment its turn starts until its answer and its speaking are over (`rouh/answers_now.py`): General, task chats, forks, mail cases, Telegram, Slack and scheduled turns all start through `runtime.Turns.start`. An entry is taken off by its tasks' own done callbacks, and one that has sent nothing for five minutes (`ROUH_ANSWER_EXPIRE`) is not counted, so a crashed turn cannot hold a deploy.
- The waiter writes `ask.json` in Rouh's data folder, `deploy-wait/`; Rouh writes `state.json` there every second. With nothing in progress Rouh says ready at once. With answers in progress new turns still start for 20 seconds (`ROUH_DEPLOY_GRACE`), then are held back - kept, not refused: what the person typed or said on a screen is also written to `held.json` and answered by the next Rouh, in the same chat and as them; Telegram is not read while held, so its messages wait at Telegram - the last answers finish, and Rouh says ready.
- At ten minutes (`ROUH_DEPLOY_WAIT_CAP`) the deploy goes anyway and names each answer it cut in `cut.json`; the next Rouh writes under it that an update cut it and after how long.
- Every wait is a line of `deploy-wait/waits.log`: who, how long, for which answers, how it ended (`idle`, `ready`, `cap`, `no-app`).
- The worker's program waits too, watching the same count, which the core also writes beside the runs (`/run/one/deploy-wait/state.json`); it may not ask the core to hold anything.
- A Rouh that keeps no count (not running, not answering, or from before this) is not waited for.

Checked in the containers by `core.deploy-waits-for-answers` (CONTAINERS.md). Not yet waiting: a whole-stack update by `deploy/container/linux_stack.py update`, which replaces the images.

## Taking a released master change (task 140, step 140-19)

Changes contract 1 adds `features.master_changes`, `features.database_rehearsal`, `database_inventory` (schema names and types, plus applied migration names; no row data), and an optional `update` field on `propose`.
Older clients keep their existing proposal behaviour; the new updater refuses to use an older core that would ignore its proof.
`updatecheck.py` runs the adapting job's proof as the isolated check user, on the old and new trees for security changes.
A before failure must be an explicit vulnerability with named assertions, and the same assertions must pass afterwards; a crashed test is not proof.

The protected database gate has a migration connection on the database network, apart from the check database.
Its credentials never reach the worker or ordinary checks.
The materialised old and new code and the proof program are root-owned and read-only; check users can write only their scratch data, so a leftover check cannot rewrite code that later receives a live connection.
The base includes the line's PostgreSQL server and backup tools in `/opt/pg`, with private libraries so they do not replace the base's other libraries.
`database_update.py` makes a new full backup, restores it into a private disk-backed PostgreSQL instance (`rehearsal.py`), rehearses the adapted atomic migration, compares counts and existing values table by table (including declared renames), and runs the change's proof and the Rouh's own self-checks against the copy.
The earlier code must also pass its own checks against the migrated copy; otherwise the job must replan as expand and contract before any live application.
Only afterwards does `rouh-update-database` lock writers, hold a full backup of that exact snapshot, and migrate the real schema and check preservation in one transaction; it reads back committed counts afterwards too. Original values are compared under the migration’s writer locks; a later session refresh or memory edit is recorded as live activity rather than falsely reported as migration data loss.
The real helper starts with unusable credentials and database access denied during Django startup; a readiness handshake grants its live connection only after startup completes without such access or extra threads.
After application, another full backup is restored into a second private instance and the change proof and self-checks run again.
Each rehearsal has its own PostgreSQL role, socket and data directory, with no TCP listener, and is removed with its WAL afterwards. Disk space is checked against the real database size.
A failed rehearsal leaves the real database alone; a failed transaction rolls back. An interrupted final verification records an uncertain application outcome, never a known rollback.
Each attempt keeps its backup, counts, result and reverse/restore instructions under `/guard/database-updates/`, beside the protected undo history.
The migration's model must be frontier even when its files could otherwise have been copied exactly.
