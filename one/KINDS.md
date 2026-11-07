# What the list holds

Every entry has the same six fields: `n` (its number), `at` (UTC, to the millisecond), `run` (the run it is about, or null), `kind` (below), `by` (who caused it) and `body` (the fields listed here).

`by` is a device id, `console` (the server's own terminal), `program`, `run` (the run's Claude Code, through its hooks), or `phone`.

A kind's fields, once written, never change meaning. A changed shape gets a new kind.
A body over 16,000 bytes has its longest text fields shortened, and says which in `_cut`.

## The program

| Kind | Fields |
|---|---|
| `program.started` | `version`, `commit`, `build`, `pid` |
| `program.stopping` | `pid` |
| `list.repaired` | `file`, `dropped_bytes`: a line cut off by a power cut was trimmed |

## Devices

| Kind | Fields |
|---|---|
| `device.paired` | `device`, `name`, `surface` (terminal, browser or voice), `token_hash` (SHA-256; the token itself is never written) |
| `device.revoked` | `device` |
| `pair.code-issued` | `surface`, `name` (the code itself is never written) |

## Runs

| Kind | Fields |
|---|---|
| `run.requested` | `brief`, `title`, `kind` (agent or shell), `space` (the assistant, scratch, or a repository added as a space), `model`, `engine` (`claude` or `codex`; a run with no `engine` at all is from before 17 September 2026 and is Claude Code), `task`, `surface`, `interactive` (true for the person's own session, started with `one claude` or `one codex`) |
| `run.queued` | `why`: it cannot start yet |
| `run.instructions` | `what`, `from` (`rouh`, `the last copy` when Rouh did not answer, or `none`), `chars`, and `why` when Rouh did not answer: the agent instructions the run was started with, read from Rouh's database as it started (`agents.fetch_instructions`). The text itself is kept by Rouh, against the run, and shown on its Agent instructions page |
| `run.started` | `cwd`, `branch`, `repo`, `session_id`, `engine`, `target` (the branch it started from), `flow` (`main`, or `branch` in a repository with a development branch, or `in place` in a folder added as it is), `own` (where the run's own files are, its brief and its hooks' key) |
| `run.ungoverned` | `engine`, `waited`, `why`: a run of Codex did not send its SessionStart hook within `ONE_CODEX_HANDSHAKE` seconds, so the program cannot tell whether its rules are running, and stopped it. Codex skips hooks it has not been told to trust and says nothing when it does |
| `run.adopted` | `holder`: the program restarted and reconnected to it |
| `run.close-resumed` | `holder`, `why`, and `how` when the run had not ended: the program found a run it had been asked to end still holding a terminal, after a restart or on an archive, and is asking that terminal to end now, through the run's own holder and nothing else |
| `space.added` | `space` and `kind`: a `repository` added as a space, with `repo`, `target` and `flow`, or a `folder` added as it is (D43), with `folder` and `made` when it was made just now (D44); from a terminal or the browser (D42) |
| `run.restarted` | `why`, and `code` and `signal` when it stopped by itself; `billing` true when it was started again because a person moved it onto the OpenAI API key, which does not count as one of a crash's restarts |
| `run.billing` | `billing` (`api`), `was` (`subscription`), `why`, and `resume` (the Codex session carried on) or `fresh` (true: a new session in the same checkout), and `stop` (what the subscription did): who pays for a run of Codex changed, because the person said yes to it. A run's `run.requested` carries `billing` only when it was asked for on the key; nothing is the subscription |
| `codex.turn-failed` | `turn`, `info` (Codex's own `codex_error_info`: `usage_limit_exceeded`, `unauthorized`, `other` ...), `message`, `billing`: Codex ended a turn with an error, read out of its session file because it sends no hook for it |
| `codex.resume-failed` | `why`, `code`, `signal`: `codex resume` on the API key would not start, so the person is asked about a fresh session instead of it being started over |
| `codex.not-switched` | `why`: a yes to the API key that could not be carried out (no key, or no session to resume); the run stays paused and nothing was billed |
| `run.stop-requested` | `how`; `durable: true` on every one written since 3 October 2026, which means the stop stands until the run is started again (`run.restarted`): a program that restarts before the run has gone asks it again, and a run asked to end is never started again as if it had crashed; `why` when it was written for an ended run whose terminal was still there |
| `run.ended` | `how` (exited, stopped, closed-idle, closed-for-room when the program neared its memory limit (D49), succeeded when the program closed a run whose turn ended well to archive it, reaped when its process had been alive for `ONE_RUN_LIFETIME` and the run ends `reaped`, lost, failed-to-start), `code`, `signal`, `ok` (false only when the run really failed: a run that was asked to end is done whatever number it gave on the way out), `forced` (SIGTERM or SIGKILL, when it would not leave when asked), `saved` (whether any of its work reached its branch), `target`, `dirty` and `unsaved` (what its checkout still held as it ended, which is what makes a run unfinished rather than done), and `why` or `while` when there is more to say |
| `run.attached` / `run.detached` | `surface`: a device started or stopped watching its terminal |
| `run.taken-over` | `device`: that device has the keyboard; `by` is who asked, which is the voice when it was said out loud |
| `run.handed-back` | `device`, `typed` (what was typed, keys named), `prompts` (what was sent to Claude), `screen` (its last 40 lines), `minutes` |
| `input.typed` | `text`: keys typed while someone had the keyboard, in batches |
| `run.archived` | `on`: true when a person put the run out of the list's way, or the program did because the run succeeded (`by` is `program`), false when they brought it back. Putting one away stops it: a run that has not ended is stopped, and `run.stop-requested` follows this on the list. Bringing one back starts nothing, and the checkout is untouched either way. A message to an archived run brings it back by itself, with `why`, because the run is going to work again (`one say`, or carrying on a person's own session) |
| `run.forgotten` | Nothing in the body. The person asked for an ended run to be forgotten for good (`one forget`): from here on it is in no view, and every other entry whose `run` is this run has been taken out of the list's files (`ListFile.scrub`), the one exception to the list never being changed. Its own folder is deleted too. Rouh forgets its side of the run on hearing it: its row, its report cards and what memory made of them (`one_jobs.forget_run`) |
| `run.retitled` | `title`, and `brief` when given: the person gave the run another title, and another brief, from here on (`one retitle`) |
| `run.forget-requested` | `after`: seconds. The person asked for the run to be forgotten once it has ended and that long has gone, so its report is still delivered first (`one forget --when-ended`); the program then writes `run.forgotten` |
| `file.dropped` | `name`, `path`, `bytes`: a file dropped on the run's terminal from a browser, written into the run's own folder; its path is then pasted at the run's prompt, which is how Claude Code takes it as an attachment (D52) |

## Claude Code, through its hooks

| Kind | Fields |
|---|---|
| `agent.session` | `session_id`, `transcript` |
| `agent.prompted` | `text`: a prompt Claude Code received, from the brief or typed by a person |
| `tool.opened` | `call`, `tool`, `input` (short fields only, secrets hidden), `what`, `detail`, and `agent`, `agent_type`, `effort`, `step`, `rule` when they apply; with full access, `guarded` (`deny` or `ask`) says what the guarded rules would have done |
| `tool.closed` | `call`, `tool`, `ok`, and `ms`, `status`, `spawned`, `agent` when they apply |
| `subagent.opened` / `subagent.closed` | `agent`, and `agent_type` on opening |
| `permission.decided` | `call`, `tool`, `decision` (deny), `rule`, `why`, `what`: a call that did not happen |
| `hook.missed` | `hook` (PreToolUse), `tool`, `call`, `what`, `caught`: the program was not asked before this call. `caught` is `PermissionRequest` when the second chance decided it; empty when it ran unchecked, which is what Claude Code does by itself with a read-only command. `hook` is `Stop`, caught by `Notification`, when a turn's end was never heard and was ended when Claude Code said it was waiting at its prompt |
| `agent.notified` | `type`, `message`: Claude Code wants a person, on its own screen |
| `agent.stopped` | `message` (its closing words), `again` (a follow-up had been given), `saving` (its work is being saved), `background` (commands it started and had not waited for, named by Claude Code in the Stop hook), `paused` (the turn ended and the work did not: `background` names the sub-agents, background commands, monitors and scheduled wake-ups that will wake it, from the Stop hook's `background_tasks` and `session_crons`; nothing is saved or reported, and the run stays working) |
| `agent.pause-ended` | `why`, `background`, `saving`: a paused turn nothing woke for `pause_silence`, called over by the program, and saved the ordinary way when `saving` |
| `agent.ended` | `reason` |
| `message.sent` | `text`, `via` (typed, end of turn, handed back, carried on); `taken` when Claude Code's UserPromptSubmit hook said it took a typed one (since 30 September 2026) |
| `message.queued` | `text`: it gets this when its turn ends |
| `message.failed` | `text`, `via` (typed, end of turn, handed back, queued), `why`: it never reached the run. `left` marks one found left unsent in Claude Code's box after a restart, which puts a run shown as working back at its prompt |

## Questions

| Kind | Fields |
|---|---|
| `question.asked` | `id`, `text`, `tool`, `what`, `detail` (the call in full), `why`, `expires_at`; a posed choice also has `kind` (`codex-billing`, `codex-fresh`), `choices` (what its yes and no buttons say) and `lasting` (no time limit, and not withdrawn by a restart) |
| `question.answered` | `id`, `answer` (yes or no), and `said`, the button's words, for a posed choice |
| `question.expired` | `id`: nobody answered in time, so it was not allowed |
| `question.withdrawn` | `id`, `why`: the run stopped, or the program restarted |
| `phone.sent` | `kind` (question or notice), `question` or `reason`, `ok` |

## The run's work

| Kind | Fields |
|---|---|
| `run.settled` | `why`, `dirty`, `unsaved`: an ended run that was called unfinished has nothing left after all, its work being on its target; it is done, said to nobody (`Runs._settle`) |
| `work.swept` | `dirty`, `unsaved`: a run that had finished its turn ended with commits after its last landing, or changes left in its tree, and its end lands them before it is judged (`Runs._end`) |
| `work.landed` | `sha`, `files`, `commits`: on main and pushed; `landed_head`, the run's own commit the landing took (everything up to it is on the target, whatever ids the replay gave it); in a repository with a development branch, the `branch` it was pushed on, `target`, and `compare`, where its pull request is opened |
| `work.not-landed` | `reason`, `files`, `sent_back` (it was sent back once to fix a clash) |
| `work.nothing-new` | `dirty`, `unsaved`: the turn committed nothing, and whether its checkout still holds changes never committed or commits not on main |
| `work.unfinished` | `why`, `sent_back`: the turn ended with work uncommitted and the run was asked, once, to finish it |
| `copy.kept` | `branch`, `sha`, `commits`: commits made on the server's copy's own main were kept on `branch` and the copy moved onto main (no run) |
| `copy.kept-landed` | `branch`, `sha`: those commits reached main through land.sh |
| `copy.kept-not-landed` | `branch`, `reason`, `conflict`: they did not, and stay on `branch` |
| `checkout.removed` | `cwd`: the run ended with nothing unsaved, and its checkout was taken away |
| `checkout.kept` | `cwd`, `why`: the run ended with work not on main, so its checkout stays for a person |
| `run.checkout` | `cwd`, `branch`, `repo`: a run carried on after its checkout was removed, in a fresh one from main |
