# Decisions: everything waiting on the person, in one model

Petar, 5 October 2026: "I feel like questions/answers should be a system unified thing. we have it with tasks, we have it with quests, but somehow it is hooked to beats also. I think it should be one model, one design, one place to look at them and make decisions. they can also be appearing contextually in their places but also in this one place."

This file is two things: the audit of every place in Rouh that asked Petar something before that day, and the design of the one model that every one of them now goes through.
The code is `rouh/decisions.py` (the record and the one way an answer goes), `rouh/decision_sources.py` (one adapter per source), `rouh/decision_desk.py` (the loop that keeps it level and sends answers back), `rouh/web/decisions.py` (the API), `rouh/static/decision.js` (the one drawing of a question) and `rouh/static/decisionspage.js` (the Decisions page).

## The audit: what asked him, and how, on 5 October 2026

| Source | Where it is kept | Where it was shown | How it was answered | How it ended |
|---|---|---|---|---|
| A task waiting on him | The task's row at `waiting` (its status, kept in the database since 6 October 2026, `rouh/taskrecord.py`) and the `question` {ask, options, several, then} in its meta, else a passage in its `AGENTS.md` (`waiting.py`) | The Decision box on the task's page (`objectindex._waiting_panel`), the amber mark on its row, the task browser's Waiting pill | A press or own words on the box, sent into the task's chat as "Task N is waiting on me for this: ... My answer: ..." and recorded in `task_answer` (`answering.py`); Dismiss | A job writes it into the task and takes the task off `waiting` with `rouh-task status` (`brain.WAITING`) |
| A goal step that is his decision | The step's meta's `goal_step` {kind, ask, options, your_choice} (`goals.py`) | The goal's page, the step's page, its How to do it page (radios and Other) | `rouh-page-goal` -> `/api/goals/step` -> `change_step(choice)` and Mark complete | The step is done by the person, and what follows starts |
| The heartbeat's and the quests' approvals | `heartbeat_approvals` {tool, args, what, to_whom, why, cost, blocking, state} | The Heartbeat page's "Waiting for your yes", a count on a quest's page, the beat's Telegram | Yes / No on the Heartbeat page, "yes 12" on Telegram, the `heartbeat` tool; Delete | yes runs exactly the queued tool once; no runs nothing; never expired |
| A run of the one program asking leave, or posing a choice | The program's own list (`one/questions.py`) | The run's card (Allow / Deny), its terminal, Rouh saying it out loud, the program's own phone link | The card over `/one/ws`, the `one_answer` tool, the phone link | Answered, or expired after 9 minutes and told no |
| A landing that collided | JSON records in `/srv/rouh-land/conflicts` (`conflicts.py`) | A conflict card in the run's thread, the orb, Telegram | The card's four buttons, `answer_conflict` by voice, a typed number | Answered or parked; stale after 7 days |
| A crew job stopped at a prompt | Only on its tmux screen (`crew.read_screen`) | Metabolism "Needs you" | `reply_to_task`, through the model only | When it moves on |
| LIVE BROWSER NEEDED | The job's report (`browser_handoff.py`) | A card and a note in the job's thread | The person in the live browser, then `reply_to_task` | When the job is sent what it asked for |
| Synapse dream changes | `synapse.dream_change.state = waiting` | Synapse lab, Dreams tab | Approve / Reject there | Never expire |
| Rules said in a chat or a mail | `synapse.item.meta.pending_rules` | Rules page, Synapse item page | Keep / Not a rule there | Never expire; since 6 October 2026 nothing new is added and the Rules page no longer lists them (`ingest.write_rules`, fr_210b5ae6725a) |
| Old memory facts | `facts.proposal` | Rules page | Apply there | Never expire |
| A job's email waiting for his yes | `worker_outbox` | Inside the job's report note | The model asks, then `send_mail` | Never expire |
| A trusted contact's mail case | `mail_approvals` | `/mail/approvals`, `/mail/case/<key>` (inside Rouh since 15 October 2026, one page with its trace: MAIL.md D26), a Telegram link | The case page only | Expire after 48 hours |
| Gated tools (`ROUH_CONFIRM_TOOLS`), ask cards | In memory / a signed card block | The transcript, a card | Allow / Not now, a spoken yes | 2 minutes / 24 hours |

What was "preselected choices and something else" before: the task box offered its options as buttons (several, as toggles) and a field "Or answer in your own words"; a goal step's How to do it page had radios with the one he picked checked and an Other with a field.
Nothing showed a recommendation, nothing said what an option would do beyond a line under it, and no two of these looked or answered alike.

## The gate: only what truly needs him

Petar, 18 October 2026: his decisions list was flooded with questions nobody needed, and even dismissing them cost him energy, which he called unacceptable.
That morning 41 waited on him: eight meetings' worth of work Rouh could start, three nights of Synapse's housekeeping, ten genes to review, and two dozen tasks whose research ended with a question such as "which pair do you want to buy?" or "which next step, if any, should a job take?".

So one gate stands in front of every source (`rouh/decision_gate.py`), and a question becomes a decision only when both of these are true:

1. Work he asked for has truly stopped, and cannot go on without him. Finished work has not stopped: research ends with Rouh's recommendation on its page, never with a follow-up question.
2. The answer is his to give: it spends money, sends, publishes or commits something in his name, cannot be undone, needs a fact only he has, or is a choice that really changes what happens next and that Rouh cannot sensibly make itself.

Everything else is not created at all, and nothing of it is shown to him.
What the gate said of every question is a row of `decision_gate` (migration 0181) and a line in the log, for whoever debugs it; `manage.py decisions_migrate` names the gate's reason for anything open at its source with no decision.

**Who judges.** Each source says what its own questions are where code can tell (`Source.gate`):

| Source | The gate |
|---|---|
| task | A done task asks nothing (its work is finished); one marked waiting that says nothing is kept back; every other question is read by the judge |
| goal | An action only he can do gets through; a decision, or Rouh stuck, is read by the judge |
| approval | Gets through only when what it runs spends, sends, publishes or cannot be undone |
| run, job, offline, mail, delegate, promise | Get through: a run held on a hook, a job at its prompt or on a live-browser step, his own offline action, somebody's request for his permission, what a delegate may not decide, a late promise whose chase sends in his name |
| casefix | Only a fix that would loosen a safety rule; one that did not work is Rouh's to look at again |
| conflict | Only a clash that would lose his own words (`conflicts.his_words`) |
| dream, nightly, genes, meeting, after_meeting | Kept back: Rouh's own housekeeping, a feature already live, genes kept in Mutations, its own preparation for a meeting, suggested work |

The judge is one model call per question, under its key, with the question's words and what is known about the work it came from (`Source.background`: the task's status, summary and notes; the goal's steps).
It is its own use on the Models page, "Whether a question needs you" (`decision_gate`, on the Daily tier in the standard): with Each use's Auto toggle on it is what the Rouh model service says, and with that Auto off whatever the person set, which Each use's Sync makes the service's again. Since 18 October 2026 it asks through the LLM service (`llm.ask`), so either company's model can be its pick.
The sync never waits for it: a question still to be judged is held back, the desk asks the model between syncs (`Desk.judge`), and the next sync makes the decision or does not.
When the model cannot answer it is asked again later, and after three tries a plain rule stands in: what spends, sends, publishes or cannot be undone gets through, the rest does not.

**What was already waiting** is judged the same way the first time each open decision is seen after the gate shipped.
One that fails is closed as **cleared by Rouh** (status `cleared`), never deleted: its line in History and its own page say why and what Rouh recommends, and **Open again** puts it back on his list (`decisions.reopen`), telling the gate it is his (`by` "person") so it is never cleared again.
For a task, clearing also takes the question out of its meta (kept beside it as `question_cleared`, with what its notes said and its status, which is what Open again puts back), labels "Waiting on" the owner (with their name) in its notes as cleared, so nothing reads the task as waiting on them, and takes the task out of waiting: done when the judge read the work as finished, in progress otherwise (`TaskSource.on_cleared`).
A new task question the gate refuses is let go of the same way, without ever becoming a decision.

**Asked less in the first place.** Every agent is told the same rule: the agent instruction "Waiting tasks and their questions" (given its new words in every organisation that still had the old ones, `agent_instructions.REVISED`), the brief of an assistant job (`assistant_job.BRIEF`) and of the one program's runs (`one/agents.py`).
A goal's plan has a decision step for him only when the goal truly cannot go on without his choice (`brain.py`, "Time and goals"; `plan_goal`; `goals.plan_problems`); otherwise the research step ends with Rouh's recommendation and the plan goes on with it.

**Landings settle themselves.** `land.sh` keeps both sides of a notes file kept by adding to it, such as a shared.md (`ROUH_UNION_PATHS`, git's union merge), and where its merge pass finds that two sides want opposite things it takes the side the pass recommends and says what it kept and why in the landing's last sentence, which is the job's report.
Only when the side it would drop carries a commit of Rouh's saver, which is how an edit he made in place reaches main, does it write the record for him (`needs_person` "his_words"); that is then one decision per file, however many jobs collided in it, titled "Which version of <file> to keep", with what each side changed and Rouh's recommendation.
The eight conflicts that waited on 18 October 2026 (seven cf-*-2 records on shared.md, which were the one program's own tests, and Rouh's saver's cf-workspace-saves-2) had already been closed that morning by d6534219, which also keeps a conflict from being announced twice.

## The model

**One record per question**, `decisions` (`models.Decision`), and its history, `decision_events`.
Every row carries `org_id` and `user_id` and every query names both.

- Where it came from: `source` (task, goal, approval, run, conflict), `source_id`, and `key`, the source's id and the words it asked, hashed, so a new question is a new row and an answer is always to the words it was given.
- Its context: `link` (an address in Rouh), `context` ("Task 89 · AI with Rouh"), `project`, `batch` (related questions share it and are drawn together).
- What it asks: `title`, `question`, `why` (why it matters), `then` (what happens next), `prepared` (what Rouh already made for it), `options` [{id, label, detail, go, more?}] (`more` is what there is to read about one answer before picking it, {facts: [[label, value]], photo?, href?, href_label?}, folded under its button on the card, each fold opened on its own and opening one picks nothing), `recommended` and `recommended_why`, `allow_other`, `answer_type` (choice, multi, yes_no, text, date, approval).
- How much it matters: `urgency` (now, today, soon, whenever), `due_at`, `risk` (reversible, money, sending, publishing, irreversible) and `risk_note`, the risk in plain words.
- Where it stands: `status` - open, snoozed, answered (inside its undo window), applying, applied, failed (answerable again), expired, withdrawn (the source stopped asking), dismissed, or cleared (by Rouh's gate, because it never needed him; opened again with one press) - with `snoozed_until`, `answer` {choice, text, said}, `answered_by` (the account, or `rouh` when he asked Rouh to decide), `channel` (screen, telegram, voice, or the source's own page), `result` (what the source said), `apply_at`, the Telegram message it went out in, and its times.

**Taken in, not copied.** `decisions.sync` asks every source what it asks now, adds what is new, keeps the open ones' words current, and closes what the source no longer asks: answered at the source - its own page, "yes 12" on Telegram, the terminal - which it reads back (`settled`) and records as answered there, or withdrawn.
A source that cannot be read (the one program away) changes nothing.
So the open asks of the day it shipped were migrated by the first sync, and nothing waiting was lost.
The desk syncs every 30 seconds and a second after anything says a source moved (the heartbeat's queue, the program's questions, a task taken in from its file).

**One way back.** Every answer - the Decisions page, a task's or a step's page, the Heartbeat or a quest's page, a run's card, a Telegram button, Rouh's `decisions` tool - goes through `decisions.answer`, which checks it and writes it down, and waits `UNDO_SECONDS` (8) with Undo before the desk claims it once (`take`) and hands it to its source's `apply`.
Answering anywhere answers it everywhere, because there is one row; the same answer again is a no-op and a different one is refused.

| Source | What an answer does (`apply`) | Dismiss |
|---|---|---|
| task | Said in the task's chat as his own words, "Task N is waiting on me for this: ... My answer: ...", and recorded in `task_answer`; Rouh hands it to a job (`brain.WAITING`) | `task_answer` dismissed, nothing sent |
| goal | His choice (and words) written into the step, which he marks complete; what waits on it starts | - |
| approval | `Heartbeat.answer`: yes runs exactly the queued tool once, no runs nothing; his own words are a no, passed to the heartbeat | Deleted from the queue |
| run | `answer` to the one program: yes allows, no refuses | - |
| conflict | `ConflictFeed.answer` with the pick, back to the job that wrote the code | - |
| job | His words typed into the job's prompt (`reply_to_task`); for a LIVE BROWSER NEEDED hand-off, what the job asked to be sent back | - |
| dream | `dreaming.decide` for each change the group holds that was answered: Approve makes the change in Synapse (undoable on the Dreams page), Reject leaves it and it is never proposed again | - |
| delegate | What a trusted contact with authority asked for that stays his, with their words: his yes or no said in the work's own chat as his answer | Closed, nothing done |

## Your part: actions, beside decisions

Petar, 7 November 2026, of a run's report that said "that waits on Petar's one-minute install check (Decision 430)": "this is not a decision. This is a blocker action I need to do. Rouh is doing stuff and requires of me to do this. It is hardly a decision, mostly an action. Can we add another section in the "now" of the navigation that will contain those actions required of me to Complete and unblock."

So what waits on him is of two kinds, in the one record (`rouh/actions.py`, task 62, step 62-28, whose journeys it follows).
A **decision** is a choice between options. An **action** is something he has to do with his own hands that work Rouh is doing waits on: install an app on a repository, sign Codex in, run one command on his Mac, check something on his phone.

- **One record, one number, one way back.** An action is a row of `decisions` with `kind` "action" (migration 0244), numbered from the same sequence and called "Action 430" (`decision_numbers.called`, `decisions.name_of`); `/decisions/430` forwards to `/actions/430`, and "action 430" is read like "decision 430". It passes the same gate, has the same 8 seconds of Undo, and goes back through its source's `apply` like any answer.
- **Raised as an action** where the source knows: a goal step that is his action (`GoalSource`), a job stopped on a step for the live browser (`JobSource`), a job's request_from_rouh the gateway read as hands-on (`job_gateway`, `hands_on`), a task question its job marked `"kind": "action"` (the agent instruction "Waiting tasks and their questions", given its new words in every organisation, `agent_instructions.REVISED`). **Read once** where it does not: a task's question, a job's ask, a heartbeat's ask with nothing to run, or a run's choice, by one model call (`actions.read_pending`, the Models page's "Whether it is something only you can do", `action_reader`), which also writes the action's page. A call to run, a landing's clash, Synapse's changes and the other choices are decisions by code (`actions.by_code`). So Decision 430, asked before any of this, was read by the first pass after the deploy and is Action 430 since.
- **Its page** (`action`, drawn by `actionspage.js` at `/actions/<number>`): what to do in one line, what it unblocks with links (its task or step, the job that asked, the goal step), how long, the steps ticked one by one with their direct links, what happens after, what waiting costs, how Rouh checks it, and the story so far, written for someone who forgot everything, with its age said plainly ("asked 3 weeks ago, on 14 October").
- **Answered by doing** (`actions.answer`): Done (with a note, such as what a command answered), Not doing this (with a reason) and Do it another way (his words) are answers: the source's yes, its no, or his words alone, led by which button it was ("Not doing this. We do not need it."), and his words kept on the answer exactly as he gave them. A goal step he will not do, or wants done another way, is started again with his words rather than marked complete. Later is a snooze. Ask is answered in place by one model call (`answer_question`, "Questions about something you have to do", `action_ask`), kept on the page, and reaches nothing.
- **Checked where it can be.** The work that asked checks it: the job told at its prompt, the goal step started again. When the job that asked has ended, his answer goes on to the task's chat as well, with how to check it, and Rouh hands it to a job that carries the work on (`actions.after_applied`).
- **Never left to tidy.** An open action whose task is done or put away, or whose job was put away, is withdrawn by itself (`actions.withdraw_stale`, each pass of the desk), shown in Done lately with why, and Open again brings it back.
- **Where it is.** Your part, the row after Decisions under Now, with its own count (amber while one holds work up); the Now tab counts both. The `decisions` message carries `actions` and `actions_blocking`, and `open` counts decisions only. The Decisions page and the `decisions` tool leave actions out and say how many there are; Rouh's `actions` tool lists, reads and answers them by number, on his own words only, as the decisions tool does. A new action that is urgent drops in as a notice and then on Telegram with Done and Later (`actions.telegram_text`).

## Decided by a delegate

Petar, 9 October 2026: a trusted contact he gives authority over a goal, a quest or a task decides its decisions for him (`rouh/delegation.py`, `DELEGATION.md`).
A decision of a goal step, a task or a quest's approval inside their grant, whose risk is reversible, is theirs: the desk emails it to them once from Rouh's own address (`delegation.brief_delegates`), does not tell the owner's phone, and the card says "Sam decides this" (`decider`); the owner can still answer it first.
Their answer goes the one way every answer goes (`decisions.answer`, its undo window, the source's `apply`), with `answered_by` `delegate:<contact id>`, channel `email`, and their own words kept on the answer (`by_name`, `words`), so every card, history line and the morning brief say "Decided by Sam" with their words; a task's chat and a quest's beat are told it was theirs, never the owner's.
A gated decision inside their grant stays his: what they said is kept as their recommendation and drawn on its card (`delegate_notes`).
What they asked for that is never theirs - spending, deleting, publishing, sending, committing him - is a decision of its own, source `delegate` (`DelegateSource`): yes or no is said in the work's own chat as his answer.

## A number to say: Decision 42

Petar, 18 October 2026: drop the letter-and-three-digit handles (a482).
"The letters mean nothing and confuse him, because similar decisions get different letters. Numbering should be consecutive, not random."
So every decision has a plain `number`, starting at 1 for each person and going up by one, shown as "Decision 42", or "#42" where there is little room (`rouh/decision_numbers.py`).

- **Given once, kept for good.** It is given when the question is first taken in (`decisions._Numbers`): one more than the highest that person was ever given, so there are no gaps, and the database holds each person's numbers unique (`decisions_one_number`). It grows as far as it needs to; there is no cap and no switch to more digits. Migration 0187 numbered every decision there was, open or finished, in the order its row was made; on the live database that made each decision's number its own row number (304 rows, ids 1 to 304, one person), so an old Telegram link to `/decisions/<id>` still opens the same decision. A row made by older code during a deploy is given one by the next sync.
- **Read tolerantly.** Wherever a decision is named - the `decisions` tool's `id`, `/decisions/42`, a Rouh link, the Decisions page's Find box, "yes decision 42" to a heartbeat approval on Telegram - "42", "#42", "decision 42", "Decision #42", "number 42", "forty-two", "one hundred and five" and "four two" are all read (`decision_numbers.read`). A bare number is a decision only where decisions are the subject: the tool's `id`, Find, the decision's own address. Anywhere else a number is a task's, and Rouh's prompt says so.
- **In code, an int is a row's id, words are his reference.** `decisions.ref_of` takes an int as the row's own `id`, which the pages' presses (`/api/decisions/<id>/act`), the card's reads and Telegram's buttons carry, and text as what the person said, read as a number and nothing else. A decision's own page reads it by number, `/api/decisions/at/<number>`, and the card acts on it by its row's id after that.
- **The number is the only name.** Petar, 29 October 2026: "no, I don't want duplicates. if we don't need the r24 format, just get rid of it altogether". Nothing but a number is read as a decision anywhere: Find, `/decisions/<number>`, `/api/decisions/at/<number>`, the tool, and "yes 42" on Telegram, where a bare number is the decision's and no longer the heartbeat queue's own id ("yes 16" used to answer Decision 351). The handles of 8 to 18 October 2026 (a482), kept in the `handle` column, and the ids Rouh's gateway gave a job for its ask until 29 October (r24, a `JobRequest`'s row) are not read; typed into Find, either gets the same "found by their number" as any other words. Nothing gives either any more: a job is told "Decision 351" and request_status takes that number (`job_gateway`), the answers jobs were given before were rewritten on 29 October to name the Decision number, and a heartbeat approval is named by its decision's number alone, to him, to a beat and to Rouh's heartbeat tool, which turn the number back into the queue's own id themselves (`heartbeat.approval_line`, `heartbeat.approval_ids_of`).
- **Shown wherever a decision is.** "Decision 42" first on every card (`decision.js`) and on every line of the Decisions page; "#42" on a history line, a dream change in the Synapse lab and a gene's state chip in Mutations; in the decisions tool's list and read, so Rouh says it; on Telegram, in a decision's own message, the heartbeat's approvals and a landing's conflict, and the brief's lines; in a check fix on a mail case.
- **Nothing else changes.** Answering by number goes the one way every answer goes, with the same checks: his own words, a gated risk confirmed by itself, the undo window.

## The safety rules, in code

- **A gated risk is confirmed by itself.** A question whose risk is money, sending, publishing or irreversible refuses an option that carries it out (`go`) - and, where his words are handed to a job that might carry it out (`text_acts`: tasks, goal steps), his words too - unless the answer names that risk (`confirm`). The page asks a second press that names it ("Sends something to someone: Mail Sam ... Yes, send it"); Telegram asks a second button; the tool asks that the risk be said back and his yes to it passed as `confirmed_risk`. The server refuses without it (409).
- **A recommendation is drawn, never picked.** Nothing answers a question without an answer given. "Rouh, decide this one" is his press or his words, and only on a reversible question with a recommendation; it is recorded as Rouh's, at his word.
- **Only he answers.** The pages are his signed-in session, and a framed task page may act only on its own question (`from_page`, `decisions.of_page`). Telegram presses are his own chat's (`telegram_chat._press`). The tool answers only in a turn he started - never a heartbeat beat, a scheduled turn or an email being handled (`protected.check`, `heartbeat.held`, `mail_turn`) - and only with words that are in his own last message in that chat (`tools._his_latest_words`). Nothing in a mail, a page or a tool's output answers a question.
- **Approvals keep their own rules.** What a beat may never do by itself still goes to the queue; a yes still runs exactly what was queued. The risk of an approval is read from its tool: nothing to run is reversible, mail and messages are sending, publishing and posting publishing, Stripe, cards and buying money, anything else irreversible (`decision_sources.risk_of_tool`).

## The one design, and the one place

`decision.js` is the only drawing of a question: where it came from and its context, how soon and how risky, the question and why, what Rouh prepared, Rouh's recommendation and its reason, the answers as large buttons with what each means, Something else, what happens next, and Later (an hour, this evening, tomorrow morning, next week), "Rouh, decide this one", Dismiss and Show me the context.
After an answer it says what was answered, by whom and where, counts down with Undo, then says what the source said.

- **The Decisions page**, `/decisions`: from the sidebar's Decisions row, with its count (red when one is urgent), and from the Control Room's header. Since 7 November 2026 it is a desk for clearing them, one decision in focus at a time; see "The desk" below (it replaced "A line each", kept below as the record). `/decisions/<number>` (which a Telegram links to) opens the item's own page when its source has one, in place of that address, and otherwise draws that one decision in full on a page of its own.
- **In place**, the same card: on a task's page and a goal step's page (sandboxed, so every press goes up through Rouh's page, `taskDecision` in `app/cards.js`), on the Heartbeat page and a quest's page for their approvals, and on a run's card for its question.
- **Telegram**: a new question that is urgent and whose source does not tell the phone itself (approvals, runs and conflicts already do) drops in on his screen first as a notification that carries it, answerable there (`rouh/notices.py`, since 10 October 2026), and goes to Telegram once if that notification is left untouched, with a button for each answer when they are few and short, Later, and its address; the buttons come off once it is answered anywhere.
- **Voice and chat**: Rouh's `decisions` tool (list, read, answer, later, delegate), and the protected built-in rule "decisions" on the Rules page (`rouh/builtin_rules_seed.py`), so "what is waiting on me" is answered from the one list.

## The desk

Petar, 7 November 2026 (task 62, step 62-27): "This is definitely something I avoid always ... redesign the page to serve me fully and quickly and easily and intuitively."
So the page is no longer a list of links to other pages: it is a desk where a decision is answered in one press, the way an inbox is cleared one message at a time.

- **One decision in focus** (`decisionspage.js`): its kind and number, what it is, what a yes does, what waiting costs, and Rouh's pick as the one big button with its reason under it; the other answers quieter beside it; Later (with when), You decide, Open (its own page, as the line used to), Dismiss where its source allows it, and Show everything, which draws the whole card (`decision.js`) in place for items one by one, his own words or several answers. A pick that spends, sends, publishes or cannot be undone asks once more, naming the risk.
- **An answer moves to the next one** by itself, and a toast keeps Undo for `UNDO_SECONDS`; Later and You decide get the same toast (Later is undone with `wake`).
- **The queue in lanes** by the cost of waiting: Holding work up (it blocks something, is urgent, or failed), Due soon (dated, today, or gated), When you have a minute, Can wait (whenever, and Synapse), Probably stale (`stale`). Can wait and Probably stale start folded, each with "Rouh decides N" (only what can be changed later and has a pick) and "Later, all". Inside a lane the server's order (`line_order`) is kept. Under the lanes, folded: Put off (with Bring back) and Your delegates decide (`lines()["theirs"]`, shown and never counted as his).
- **Repeats folded**: decisions of the same source with the same words and answers are one row, "asked 4 times", and one answer goes to every copy; Decided lately folds them the same way. The page counts answers to give ("11 answers to give, about 2 min") and the line under its name says how many decisions wait, the number on the sidebar's row and on Now.
- **Keys on a desk**, shown on each button and listed under "?": j and k to move, y or Enter for the pick, 1 to 9 for the other answers, s then 1 to 4 for Later, d you decide, o open, e everything, x select, u undo, / a number, Escape to close what is open. They act only while the page is open and nothing is being typed. On a phone the keys are hidden and every target is at least 44 px.
- **Select** (x, or the Select button): several at once, then Rouh decides or Later.
- **Decided lately**: who decided (you, Rouh for you, a delegate, closed by itself), where (Telegram, voice), when and what came back, with Undo or Open again while allowed.
- **When nothing waits** the page says so as a finished thing: answers given today, when the first put-off one comes back, what delegates hold.

## A line each

**Replaced (7 November 2026, by "The desk" above):** what follows was the page from 18 October to 7 November 2026. What a line says (`line_of`) is still the data each decision carries and what Rouh's tool reads out; the page draws it on the desk's card.

Petar, 18 October 2026, approving it with "Do it": the Decisions page becomes a short list of lines, and each line is one link to the item's own page, where the real decision is made with everything there is to know.
The generic boxes and their buttons are gone from the page, and so is a batch line such as "Mutations, 10 in one".

- **What a line says** (`decisions.line_of`, kept as the decision's `line`, migration 0182): what it is in plain words with its task or step number ("Task 19, Pricing: Which price do we quote Acme for the pilot?"); what a yes would do, concretely; what waiting costs, after its due date when it has one, or "Nothing waits on it"; a few tags (where it came from, its project, what the source adds); Rouh's recommendation in a few words; and its number, "Decision 42". Long words wrap; nothing is cut.
- **Where it opens** (`Source.own_page`): a task its task, a goal step its step, a heartbeat or quest approval its page, a run's question its run, a mail case its case at the step (`#approval-N`, carried into the framed case page), a check fix its case, a Synapse night its Dreams page, a gene its own page in Mutations. A source with no page that answers it (a job at its prompt, a delegate's ask, an offline action, a late promise, a landing's clash, a meeting) opens `/decisions/<number>`, the one decision drawn in full. Each line is a real link, so Cmd-click opens a new tab and Back comes back to the list.
- **What kind it is, at a glance.** Petar, the same day: "the decisions I need to have a good visual sense what type they are. Gene mutation, person communication etc". Each line starts with a badge, its source's icon and word (`Source.tag`: Gene, Message, Promise, Delegate, Meeting, Task, Goal step, Approval, Run, Job, Landing, Check fix, Memory, Offline), and the badge and the line's left edge are in its family's colour: people (messages, promises, delegates, meetings), genes, tasks and goals, approvals, runs and fixes, memory.
- **Show only one kind**: a chip per family waiting, with its count and colour, above the list (`decisionspage.js`, `FAMILY`).
- **The order** (`decisions.line_order`): what is dated or holds something up first, soonest first; then the rest, newest first. The same on every width.
- **Under the list**, in brown toggles: what he put off till later, and what was answered lately.
- **Every source says both** (`Ask.yes_does`, `Ask.wait_cost`, `blocks`, `tags`, `advice`, `about`). One that cannot say what a yes does or what waiting costs is kept back by the gate before anything else (`decision_gate.verdict_for`, `decisions.missing_line`), never shown with an empty field.
- **Rouh's tool says the same lines** in the same order (`decisions.listing_for_model`, `line_words`), so what is read out matches the page.
- **Each gene is its own line** (`GeneSource`): its name, one sentence on what it does, what Keep would do, tags, Rouh's word and its number, opening its page in Mutations, which says what changes if he keeps it. Answering there brings its line level at once (`evolution._poke`), so it is gone when he goes back. A gene left for later is not a line: it waits first in the next deck. The gate lets genes through, by this request, where it had kept them in Mutations that morning.

## What a source may say about its question

A task's meta's `question` keeps its shape (`ask`, `options`, `several`, `then`) and may now also say, all optional: `why` (why it matters), `recommended` (the label of the option Rouh would pick) and `recommended_why` (one line), `risk` and `risk_note` (for a question whose answer spends money, sends, publishes or cannot be undone), `urgency` (now, today, soon, whenever) and `prepared` ([{label, href?, text?}]).
The agent instructions every job starts with (`rouh/agent_instructions.py`) ask it to write them.

A `prepared` entry with a `part` (A, B, C) is one step of what a yes does, in the order it happens, and is drawn in sight on the card rather than folded under What Rouh prepared; the tool says them in its line (`decisions.parts_of`).

## A trusted contact's message

Since 11 October 2026 a trusted contact's email or Telegram message has at most one decision, made from its ledger of asks (`MailSource`, source `mail`, `CaseDesk.sync_decision`), and `MAIL.md` is the whole record.
It lists what needs the owner, ask by ask: what waits for a choice (a grant the contact does not hold, a new grant, a hard limit), and what he approved or what failed and was not run yet.
When something waits for a choice it offers Approve and run, Allow once and run, Decline, I'll see to it and Open the case, for all of them or one by one; when nothing does, Run it now and Open the case.
Open the case is a link, not an answer (`options[].href`, `decisions._links`).
The owner's own words run the message again, read with them.
When the ledger changes the decision is made again and the old one superseded, and his phone is told only of asks he was not told of before.
What the contact already had from Rouh is shown as sent, from the case's outbox (`mail_outbox.views`).
On the case page a choice only saves, Test grants shows at once what a run would let through, and Redo runs.

Before that date a message's decision showed A, the immediate reply, B, the action, and C, the final reply (8 October 2026), and from the morning of 11 October each held ask was routed on its own with a second look by a model beside it (`mail_look`, night 8 of the nightly feature run).
The ledger replaced all three: there is no immediate reply to approve, since the one acknowledgement and the status part are the code's words, and permission is the code's, not a reading of the words.

## A false alarm's fix that needs him

Petar, 8 October 2026, by voice: marking a step of a mail or Telegram case a false alarm starts a run that fixes the check behind it (`rouh/case_fixes.py`), shown on the case page while it goes and summed up there when it ends.
A fix that did not work, or that stopped because the only fix would loosen a safety rule (money, sending outside the owner's company or beyond the trusted sender, publishing or sharing, private or health data, anything irreversible, taking a message's words as instructions), is a decision (`CaseFixSource`, source `casefix`), with its number on the case page beside the fix.
Try again starts a new fix run on the same step with his words as its reason; Leave it closes it, and the check goes on stopping messages like that one.
His phone hears one line when a fix lands or fails, from the fix itself, so the source says it notifies and the desk tells it nothing more.

## The work a meeting calls for

Night 6 of the nightly feature run, 9 October 2026 (task 94, I-073), behind the switch `meeting_next`.
Once a meeting's notes reach his Master from the meeting library, one model call reads them with his open tasks and says which work the meeting calls for that Rouh can do by itself, at most three pieces, each with why and the task it belongs to (`rouh/meeting_next.py`).
They are one decision for the meeting (`AfterMeetingSource`, source `after_meeting`), "After “<the meeting>”: 2 pieces of work Rouh can start", whose items are the pieces: Start all, Not needed, or each on its own, the way a night of Synapse's changes is.
Start begins a run of his assistant (`starting.start`, preset `assistant_job`) briefed with the piece of work, why, the date it is needed by and the meeting's notes as somebody else's words, in the chat of the task named, so it writes into that task; nothing is ever sent to anybody.
A meeting answered in part stays open for the rest; one answered in full closes as applied, with the runs it started.
It waits until he answers, with no time limit; turning the switch off withdraws it, and turning it on again asks it again without asking the model again.

## Promises made in Slack

Petar, 16 October 2026, the second of five Slack ideas ("do all of those"): a commitment with a deadline, made by him or to him in a Slack message Rouh keeps, is kept as a promise (`rouh/slack_promises.py`, `slack_promises` table, migrations 0167 and 0171), never as a task, because tasks were already cluttering his board.
Every kept message is read once (`slack_messages.promises_read`) by one model call per conversation, once Slack has been quiet for 30 seconds, with a few earlier messages and the promises already open there, through the LLM service under its own use, Promises in Slack (`slack_promises`, Sonnet 5 to start).
The same call says which open promise a new message shows kept.
What the 90-day look back read is read only over its last 30 days, and of that only what is not yet due is kept.
Promises between other people are never kept: only the author of a message can promise in it, and only to him or by him.

**A deadline until it is late.** Petar, 16 October 2026, asking why Slack promises went to the decisions list, and then "Do it": a promise is not a decision until it is overdue and he must choose what to do; before that it is a deadline, and deadlines belong on Clockwork.
Until 17 October every open promise was an item of one line with a count here ("N open promises in Slack"), and one of his own came up in full a day before it was due; that line is withdrawn and never asked again.

- **His own** are never here. Each is a Clockwork reminder for him (`slack_promises.clockwork`), made as the schedule tool makes one, so it is listed on Clockwork like any other and is handed to Rouh in General and sent to his phone when due. It is due a day before the promise: at the hour said, the day before; at 09:00 in the owner's time zone the day before when only a day was said; on the morning of it when the day before has passed (`remind_at`). It says what he promised, to whom, by when, and links to the message. One reminder a promise, ever (`clockwork_id`, `clockwork_at`, migration 0171): a later message that shows it kept cancels it (`cancel`).
- **Made to him** are kept quietly and shown nowhere until their time has passed with nothing since to show them kept. Then each is a decision of its own (`PromiseSource`, source `promise`, urgency Today): who promised what, by when, how late it is, the link, and Chase, Wait or Drop.
- **Chase** posts the nudge drafted when the promise was read, or his own words given as Something else, as Rouh's bot in the thread the promise was made in; for a promise in one of his own direct messages, which the bot cannot post in, as a direct message from Rouh to the person who promised. The decision is gated as sending, so it goes only on his second press, and it is written to the sent log like every Slack post. It comes back two days later if still not kept.
- **Wait** asks again three days later (`slack_promises.wait`, `waits`, `wait_until`), unless it is kept before then.
- **Closed by itself**: when a later message shows a late one kept, the promise closes and its line in History says "Closed by itself", with what was written, and Undo (`decisions.reopen`, `Source.can_reopen`). Undo opens the promise again and that message is never read as kept again. One not late yet closes as quietly as it waited.
- The promises kept before 17 October moved to these places on the first pass after the deploy (`slack_promises.settle`, every pass): his own still ahead to Clockwork, once, the rest to waiting quietly.
- Its dates are what it is about, so a late promise is never "Probably stale" (`Source.dated`).

## A question he already answered in a chat

Night 9 of the nightly feature run, 12 October 2026 (task 94, I-085), behind the switch `answered_in_chat`.
He answers many questions where he happens to be talking, and the question goes on waiting: on 11 October he told step 89-10's chat the two things he wanted changed in the teaching framework, and goal 89's "Agree the framework, or say what to change" was still open the next morning.
So every question waiting on the install's owner, but a message's (`mail`) and an offline answer's, is read against his own chat messages since it was asked (`rouh/answered_in_chat.py`).
Code picks the few that are about it: any message in a chat of its task or a step under it that shares a word with it, and any other message sharing two of its rare words, weighed down by length; nothing about it costs no call.
When there are some, one model call (its own pick on the Models page, "Questions you already answered in a chat") says whether one answers it, with his exact words, which are checked to be in that message, the offered answer they amount to, or his answer in his words, and why.
The card shows it above the answers, "You may have answered this already": the chat, when, his words, what they answer, and **Answer with that** and **Not this**.
Answer with that is his own press the usual way, with Undo and, where it spends, sends or publishes, the second press: an offered answer is given with his words beside it where the question takes words, and words of his own open Something else with them written in, for him to send.
Not this keeps the question open and never offers that message for it again.
A reading is kept by the question and the messages it read (`user_settings` `answered_in_chat_made`) and made again only when a new message about it arrives, at most once an hour; what a beat finds is one notice on the screen, never the phone.
Rouh's tool reads it too, and is told to ask him, never to answer on it alone.

## Which LinkedIn profile is a meeting guest's

Petar, 9 October 2026 (fr_3cd6569317e8), of a meeting decision that only took words: "I should have the buttons to pick which of the two. Second I should be able to expand them and see the rest of the information you have on them. Third I described in words which one to pick and I got this error message."
So every candidate is an answer of its own (`MeetingSource`): "Sam 1", "Sam 2", with the short line it always had under it and everything kept on that profile folded below (name on LinkedIn, headline, where, the profile's address and a link to it, its face when LinkedIn gave one, and where it came in LinkedIn's list).
A meeting with several guests waiting shows each guest's candidates while they fit on the card; a press keeps that one and the decision is open again for whoever is still waiting (`Applied.reopen`), saying so.
His own words are read for a name and a number first (`meeting_people.answer_words`); whatever that cannot read is read by a model against the candidates, letter by letter where he points at a spelling or a capital (`meeting_people.read_with_model`, its own pick on the Models page, "Reading which profile a meeting guest is").
His words that fit more than one candidate are not failed: the decision is open again with Rouh's question on it, "Which one do you mean ...", above the same buttons.
The error he saw was the old reader splitting his sentence at its commas and finding no number in any part.

## Migrating what was open

Petar, the same evening: "also migrate the current decisions to the new decision platform".
`python manage.py decisions_migrate` takes every ask open at every source into the model, with its own words, options, context address and history (earlier answers on a task's page, the beat that queued an approval, Rouh's part on a goal step, the night a dream change came from), and marks each "taken in".
It counts the open asks at each source itself and the open decisions of each, before and after, and lists every ask open at its source that has no open decision, with the reason (a goal step is counted with the goal steps, a task answered on its page waits on its job, a source that could not be reached).
It is idempotent: one row per question, keyed by its source and its words, so a second run takes in nothing; and it answers, dismisses and changes nothing at any source, so each stays answerable where it was and through Decisions, once.
`--dry-run` only counts.
The deploy runs it (`manage.py predeploy`), so it runs on the live data with every deploy and its report is in the deploy log; what the deploy cannot reach (the one program, if it is down) Rouh takes in at start.

A goal step waits on him when it is marked waiting with something asked of him - Rouh did its part and left an action or a decision, or Rouh is stuck - or when its part for him is a decision not yet made. Task 67's two steps were the first of the actions.
A batch of related questions that can all be changed later and share the same answers shows its first three with Show all, and an "Approve all N" that asks once and then answers each the one way.

## When the list overflowed

Petar, 8 October 2026, by voice: "Decisions is overflowing, needs a fix."
155 waited on him, 142 of them one night of Synapse's dreaming, each small change its own decision, and what mattered (a SOC 2 window that sends a message, the night's feature to accept or undo, a meeting's guests) was buried among them.

- **One decision for many small ones.** A decision may hold `items` (migration 0104): a night's Synapse changes of one kind are one decision, "Synapse, night 1: 32 link changes", with Approve all, Reject all, and "Decide them one by one", a row each with its own Approve or Reject and one Send for those picked (`DreamSource`). Every answer, all or some, goes the one way: `decisions.answer` keeps which item got which answer, the same 8 seconds of Undo, then `dreaming.decide` for each, exactly as on the Dreams page, where each stays undoable. A group answered in part is open again for the rest (`Applied.reopen`), saying what was done. The per-change decisions waiting that day were folded by the first sync into their group: each is withdrawn with "Folded into #N", and History leaves them out. The Dreams page shows each waiting change with its group's decision number.
- **The order.** `decisions.arrange`, the one order the page draws and the tool says: first and always in sight, whatever else is true of them, what spends money, sends, publishes or cannot be undone; then Now, Today and Soon, each by source with its count, a long group showing its first three and Show more; below the fold and folded, "Whenever, and low stakes" (Synapse's groups); last and folded, "Probably stale".
- **Probably stale** (`stale_reasons`): its own deadline has passed (`due_at`, or the latest "by 2 October"-style date in its own words), or the task it belongs to (a goal step's goal too) is done or archived. A line each with why, Dismiss where the source has the idea, and Answer it. Nothing is closed, answered or dismissed for him.
- **The tool's list** (`listing_for_model`): the ones that matter in full, then a line a group with its count and numbers.

## Nothing expires by time alone

Petar, 8 October 2026, by voice: "Nothing expires due to time only. This question may be valid in 1 year. So remove time expiration."
A question waiting on him stays open until he answers it, or until something it is about really changes.
Every time limit on a waiting question was looked at that day; this is what each one became.

Removed, because they closed a question only because time passed:

- **A trusted contact's mail-case or Telegram approval** (`rouh/mail_cases.py`). It lapsed 48 hours after it was asked (`APPROVAL_HOURS`), was marked expired and blocked its case. Now it waits however long it takes, with one reminder (`CaseDesk._remind`). It still lapses, and Rouh asks again, when a newer message in the thread changes or withdraws the request, the proposal or a file the reply carries changes, the email in Gmail is gone or different, or his change to the contact's permissions makes Rouh read it again. `MailApproval.expires_at` is history only.
- **A landing that collided** (`rouh/conflicts.py`). A waiting or parked conflict older than seven days (`STALE_AFTER`) stopped needing anybody, and its decision closed as withdrawn with the work still off main. Now it waits until it is answered or dismissed.
- **The nightly feature's Accept or Reject and undo** (`NightlySource`). Only the newest 14 nights were read, so a night left unanswered for two weeks closed as withdrawn with its feature still switched on. Now every unanswered night is read (`nightly_feature.unanswered`).

What had already run out of time is not brought back. Petar, the same day: "No need to reopen expired - set them dismissed as I don't want to deal with old stuff." Migration 0106 dismissed every expired mail and Telegram approval and every expired decision: closed, nothing done, nothing sent, off the Decisions list and the morning report, and kept in its history as dismissed. A case whose approval was dismissed stays blocked, with Redo on its page.

Kept, each for a reason that is not the question going stale:

- **A run of the one program asking leave** (`one/questions.py`, `RunSource`): told no after 9 minutes (`ONE_QUESTION_TIMEOUT`), and its decision closes as expired. The run is stopped inside a hook that Claude Code itself abandons at 10 minutes (`hook_timeout`), and no answer has to mean no rather than whatever Claude Code does with a hook that died. It is only asked at all when a run's access is guarded; the default, full, asks nothing. A choice a run poses (`pose`, `lasting`) has no limit.
- **Gated tools** (`rouh/permissions.py`, `ROUH_CONFIRM_TOOLS`, off unless set): 2 minutes, because the model's turn is held open while it waits; the model is told it was not done and says it is waiting on him.
- **Ask cards and draft cards** (`rouh/asking.py` 24 hours, `rouh/composing.py` 7 days): a button signed into a card in a chat, which shares a location, saves a contact or sends an email in one press. A press on last week's card does not quietly act today; it says to ask again, and Rouh shows it afresh. These are buttons in a transcript, not questions in this list.
- **A meeting guest's LinkedIn pick** (`MeetingSource`): asked for the meeting's preparation and withdrawn when the meeting begins, an event rather than a clock. The guest stays unresolved on their contact card, where the question can still be answered.
- **Codes and grants**: a trusted contact's Telegram link code (48 hours), a device pairing code (10 minutes) and a sign-up grant (24 hours) are one-time secrets or permissions he gave for a while, not questions waiting on him.

Display only, nothing closed: "Probably stale" in the list (`stale_reasons`), a snooze that runs out (it brings the question back), and a goal step's "3 days ago".

## What is not in it yet

These still ask in their own place and are not decisions yet:

- Old memory facts (Apply on the Rules page). Synapse's pending rules, said in a chat or somebody else's mail, are no longer made at all since 6 October 2026: Petar had them removed as noise.
- A job's email waiting in `worker_outbox`. Trusted contacts' mail-case approvals are, since 8 October 2026 (`MailSource`), except a question about his inbox.
- Gated tools and ask cards, which belong to the turn that asked.
- The goal step's own How to do it page still has its radios; the step's page carries the decision card.
- Telegram buttons on the heartbeat's own "needs yes" message: "yes 12" still works and is recorded as answered on Telegram.
